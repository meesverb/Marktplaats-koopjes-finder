"""views.py en own_bids.py: weergaven en likes meten, en de eigen biedingen."""
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import FakeResponse, FakeSession, close_databases_before_cleanup, make_listing

import db
import flips as fl
import own_bids as ob
import racefiets_jev as mp
import recheck as rc
import views as vw

BIKE_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/{}-x"
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def listing_page(views=158, favorites=4, since="2026-09-27T12:00:00Z", price_cents=45000) -> str:
    data = {"listing": {"itemId": "x", "priceInfo": {"priceCents": price_cents, "priceType": "FIXED"},
                        "isReserved": False, "stats": {"viewCount": views, "favoritedCount": favorites,
                                                       "since": since}}}
    return f"<script>window.__CONFIG__ = {json.dumps(data)};</script>"


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        close_databases_before_cleanup(self)
        self.db = str(self.dir / "koopjes.db")
        self.conn = db.connect(self.db)
        self.addCleanup(setattr, rc, "MIN_INTERVAL_S", rc.MIN_INTERVAL_S)
        rc.MIN_INTERVAL_S = 0

    def bikes(self, *ids, first_seen=None):
        listings = [make_listing(item_id=i, url=BIKE_URL.format(i), title=f"Fiets {i}") for i in ids]
        db.sync_listings(self.conn, "racefiets", listings, (first_seen or NOW).isoformat())
        return listings


class PageStatsTest(Case):
    def test_read_from_the_listing_page(self):
        page = mp.listing_page_data(listing_page())
        self.assertEqual(mp.page_stats(page), {"views": 158, "favorites": 4, "since": "2026-09-27T12:00:00Z"})
        self.assertIsNone(mp.page_stats({"stats": None}))
        self.assertIsNone(mp.page_stats({}))

    def test_a_bid_lookup_brings_the_stats_along_and_the_round_stores_them(self):
        (l,) = self.bikes("b1")
        l.price_type, l.price_eur = "FAST_BID", None
        session = FakeSession({l.url: listing_page(views=12, favorites=1)})
        mp.enrich_bid_listings([l], 0, "fast", session=session)
        self.assertEqual(l.page_stats["source"], "biedopvraging")
        db.sync_listings(self.conn, "racefiets", [l], NOW.isoformat())
        (obs,) = db.list_stats(self.conn)["b1"]
        self.assertEqual((obs["views"], obs["favorites"], obs["source"]), (12, 1, "biedopvraging"))


class PlanTest(Case):
    def test_own_ads_favourites_bids_then_the_sample_within_the_budget(self):
        sampled = [f"m{n}" for n in range(1000, 1400) if vw.in_sample(f"m{n}")][:3]
        others = [f"m{n}" for n in range(1000, 1400) if not vw.in_sample(f"m{n}")][:2]
        self.bikes(*sampled, *others, first_seen=NOW - timedelta(days=3, hours=2))
        db.set_mark(self.conn, others[0], "favoriet")
        ob.place(self.conn, others[1], 200.0)
        trade = fl.create_flip(self.conn, title="Eigen Cube", market="fietsen", bought_at="2026-09-01",
                               buy_price_eur=300, stage="te_koop")
        fl.update_flip(self.conn, trade, sale_url="https://www.marktplaats.nl/v/fietsen/racefietsen/m999888777-cube?x=1")

        plan = vw.plan(self.conn, 10, now=NOW)
        self.assertEqual([t.why for t in plan[:3]], ["eigen advertentie", "favoriet", "bod"])
        self.assertEqual(plan[0].url, "https://www.marktplaats.nl/v/fietsen/racefietsen/m999888777-cube")
        self.assertEqual({t.item_id for t in plan[3:]}, set(sampled))
        self.assertTrue(all(t.why == "steekproef 3 d" for t in plan[3:]))
        self.assertEqual(len(vw.plan(self.conn, 2, now=NOW)), 2)
        self.assertEqual(vw.plan(self.conn, 0, now=NOW), [])

        # Gemeten: de volgende ronde niet nog eens, tot het volgende leeftijdsvak.
        for t in plan:
            db.record_stats(self.conn, t.item_id, NOW.isoformat(), {"views": 1, "favorites": 0})
        self.assertEqual(vw.plan(self.conn, 10, now=NOW + timedelta(hours=1)), [])
        later = vw.plan(self.conn, 10, now=NOW + timedelta(days=4))
        self.assertEqual({t.why for t in later if t.item_id in sampled}, {"steekproef 7 d"})
        self.assertIn("eigen advertentie", {t.why for t in later})

    def test_a_round_measures_logs_and_stops_after_three_failures(self):
        # Wat koopjes.py elke ronde draait (measure_round): plannen, meten,
        # loggen; drie mislukte op rij en hij houdt op.
        import requests
        ids = ["m2001", "m2002", "m2003", "m2004"]
        listings = self.bikes(*ids)
        for i in ids:
            db.set_mark(self.conn, i, "favoriet")
        self.conn.commit()
        lines = []
        pages = {l.url: listing_page(views=10 + n, favorites=n) for n, l in enumerate(listings)}
        self.assertEqual(vw.measure_round(self.db, 10, session=FakeSession(pages), log=lines.append), 4)
        self.assertIn("4 advertentie(s)", lines[0])
        self.assertTrue(all("bekeken" in line for line in lines[1:]))
        self.assertEqual(vw.measure_round(self.db, 0, session=FakeSession(pages), log=lines.append), 0)

        class Down:
            headers = {}
            requested = []

            def get(self, url, timeout=0):
                self.requested.append(url)
                raise requests.ConnectionError("geen verbinding")

        for i in ids:  # opnieuw aan de beurt
            self.conn.execute("DELETE FROM listing_stats WHERE item_id = ?", (i,))
        self.conn.commit()
        lines, down = [], Down()
        self.assertEqual(vw.measure_round(self.db, 10, session=down, log=lines.append), 3)
        self.assertEqual(len(down.requested), 3)
        self.assertIn("drie keer achter elkaar", lines[-1])
        # Een gewijzigde pagina telt ook als mislukt.
        lines = []
        changed = FakeSession({l.url: "<html>anders</html>" for l in listings})
        self.assertEqual(vw.measure_round(self.db, 10, session=changed, log=lines.append), 3)
        self.assertIn("paginastructuur gewijzigd", lines[-2])

    def test_measure_records_and_a_gone_listing_is_marked(self):
        a, b = self.bikes("m1001", "m1002")
        session = FakeSession({a.url: listing_page(views=40, favorites=2), b.url: FakeResponse("", 410)})
        self.assertEqual(vw.measure(self.conn, vw.Target(a.item_id, a.url, "favoriet"), session,
                                    now=NOW.isoformat()), "40× bekeken, 2× bewaard")
        self.assertEqual(vw.measure(self.conn, vw.Target(b.item_id, b.url, "favoriet"), session,
                                    now=NOW.isoformat()), "weg")
        self.assertIsNotNone(self.conn.execute("SELECT disappeared_at FROM listing WHERE item_id = 'm1002'").fetchone()[0])
        latest = vw.load_latest(self.db)["m1001"]
        self.assertEqual((latest.views, latest.favorites, latest.label), (40, 2, "40× bekeken · 2× bewaard"))


class PatternsTest(unittest.TestCase):
    def obs(self, item_id, days, views, favorites, since, price=300.0):
        return vw._Obs(item_id, since + timedelta(days=days), views, favorites, since, price)

    def test_growth_speed_and_promotion(self):
        since = NOW - timedelta(days=30)
        obs, listings, places = {}, {}, {}
        for n in range(36):
            item = f"m{n}"
            likes = n  # meer likes ...
            obs[item] = [self.obs(item, 1, 50 + n, likes, since), self.obs(item, 3, 120 + n, likes * 2, since)]
            gone = (since + timedelta(days=3 if n >= 24 else 20)).isoformat()  # ... sneller weg
            listings[item] = (since.isoformat(), gone, 300.0)
            places[item] = (52.0, 5.0, "DAGTOPPER" if n % 2 else "", "")
        p = vw.compute(obs, listings, places, now=NOW)
        self.assertEqual(p.measurements, 72)
        self.assertEqual([g[0] for g in p.growth], ["1-3 dagen", "3-7 dagen"])
        self.assertEqual([g.n for g in p.speed], [12, 12, 12])
        self.assertEqual((p.speed[0].median, p.speed[2].median), (0.0, 1.0))
        self.assertEqual({g.label for g in p.promotion}, {"Dagtopper", "geen promotie"})
        html = vw.patterns_html(p, "racefietsen")
        self.assertIn("Likes en hoe snel iets weg is", html)
        self.assertIn("Dagtopper", html)

    def test_without_measurements(self):
        self.assertIn("Nog geen metingen", vw.patterns_html(vw.ViewPatterns()))

    def test_sparkline(self):
        self.assertEqual(vw.sparkline([5]), "")
        self.assertIn("<polyline", vw.sparkline([1, 3, 2]))


class OwnBidsTest(Case):
    def test_history_status_and_accepted_goes_to_flips_once(self):
        self.bikes("m1")
        with self.assertRaisesRegex(ValueError, "onbekende advertentie"):
            ob.place(self.conn, "nope", 100)
        with self.assertRaisesRegex(ValueError, "nog geen bod"):
            ob.set_status(self.conn, "m1", "afgewezen", market="fietsen")
        ob.place(self.conn, "m1", 250, bid_at="2026-09-28T10:00:00+00:00")
        ob.place(self.conn, "m1", 280, bid_at="2026-09-29T10:00:00+00:00")
        trail = ob.load(self.db)["m1"]
        self.assertEqual([b.amount_eur for b in trail.bids], [250, 280])
        self.assertTrue(trail.active)

        bid, trade_id = ob.set_status(self.conn, "m1", ob.ACCEPTED, market="fietsen", expected_resale_eur=400,
                                      today="2026-09-29")
        self.assertEqual((bid.status, bid.trade_id), (ob.ACCEPTED, trade_id))
        book = fl.load_book(self.db, with_market_check=False)
        (flip,) = book.flips
        self.assertEqual((flip.trade.buy_price_eur, flip.trade.market, flip.stage, flip.target_low_eur),
                         (280, "fietsen", "gekocht", 400))
        # Nog eens geaccepteerd (per ongeluk): geen tweede flip.
        ob.set_status(self.conn, "m1", "open", market="fietsen")
        ob.set_status(self.conn, "m1", ob.ACCEPTED, market="fietsen")
        self.assertEqual(len(fl.load_book(self.db, with_market_check=False).flips), 1)
        self.assertFalse(ob.load(self.db)["m1"].active)

    def test_outbid_and_order(self):
        self.bikes("m1", "m2")
        ob.place(self.conn, "m1", 100, bid_at="2026-09-27T10:00:00+00:00")
        ob.place(self.conn, "m2", 50, bid_at="2026-09-28T10:00:00+00:00")
        ob.set_status(self.conn, "m2", "afgewezen", market="fietsen")
        self.conn.execute("UPDATE listing SET bid_high = 120 WHERE item_id = 'm1'")
        self.conn.commit()
        trails = ob.load(self.db)
        self.assertTrue(trails["m1"].outbid)
        self.assertEqual([t.item_id for t in ob.ordered(trails)], ["m1", "m2"])


if __name__ == "__main__":
    unittest.main()
