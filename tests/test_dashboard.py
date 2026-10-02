"""dashboard.py: één pagina met alle fietscomputers, gebouwd uit koopjes.db."""
import io
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import make_listing

import dashboard
import db

CATEGORY_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/{}-x"
BIKE_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/{}-x"


def computer(item_id, title, price, **kw):
    kw.setdefault("url", CATEGORY_URL.format(item_id))
    kw.setdefault("image_urls", f"https://images.example/{item_id}.jpg")
    return make_listing(item_id=item_id, title=title, price_eur=price, **kw)


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def sync(self, listings, when=None):
        conn = db.connect(self.db)
        try:
            db.sync_listings(conn, "garmin edge", listings, (when or self.now).isoformat())
        finally:
            conn.close()

    def market(self):
        return [computer(f"a{i}", "Garmin Edge 530", p) for i, p in enumerate((160.0, 180.0, 200.0, 220.0))]


class DashboardTest(DatabaseCase):
    def test_flips_upgrades_and_filtered_out_from_the_database(self):
        cheap = computer("c", "Garmin Edge 530 fietscomputer met houder", 90.0)
        holder = computer("h", "Houder voor Garmin Edge 530", 12.0)
        unknown = computer("u", "Van Rysel GPS 500 Fietscomputer - Nieuw in doos", 50.0)
        mount = computer("m", "Garmin Edge Aero Mount - Zo goed als nieuw", 12.5)
        bike = make_listing(item_id="b", title="Giant Defy met Garmin Edge 530", price_eur=900.0,
                            url=BIKE_URL.format("b"))
        self.sync(self.market() + [cheap, holder, unknown, mount, bike])

        d = dashboard.load_dashboard(self.db)
        ids = lambda items: {l.item_id for l in items}
        self.assertNotIn("b", ids(d.listings))  # another category: not on the dashboard
        self.assertEqual(ids(d.flips) & {"c"}, {"c"})
        self.assertIn("c", ids(d.upgrades))
        self.assertEqual({u.listing.item_id for u in d.unknown_computers}, {"u"})
        self.assertEqual({l.item_id for l, _, _ in d.excluded}, {"h", "m"})

        html = dashboard.render(d)
        for label in ("Flips (", "Upgrades (", "Alle computers (", "Marktprijzen", "Uitgefilterd (2)"):
            self.assertIn(label, html)
        self.assertIn("https://images.example/c.jpg", html)  # migration 6 kept the photo
        self.assertIn("model onbekend", html)

    def test_only_listings_from_the_latest_round_are_active(self):
        old = computer("old", "Garmin Edge 830", 150.0)
        self.sync([old], when=self.now - timedelta(days=10))
        self.sync(self.market())
        d = dashboard.load_dashboard(self.db)
        self.assertNotIn("old", {l.item_id for l in d.listings})

    def test_disappeared_listings_are_gone(self):
        self.sync(self.market())
        conn = db.connect(self.db)
        try:
            conn.execute("UPDATE listing SET disappeared_at = ? WHERE item_id = 'a0'", (self.now.isoformat(),))
            conn.commit()
        finally:
            conn.close()
        self.assertNotIn("a0", {l.item_id for l in dashboard.load_dashboard(self.db).listings})

    def test_new_means_first_seen_in_the_last_day_but_not_on_the_first_round(self):
        self.sync(self.market(), when=self.now - timedelta(days=2))
        self.assertEqual(dashboard.load_dashboard(self.db).new_ids, set())  # first round: nothing is "new"
        fresh = computer("f", "Garmin Edge 830", 150.0)
        self.sync(self.market() + [fresh])
        self.assertEqual(dashboard.load_dashboard(self.db).new_ids, {"f"})

    def test_a_reserved_listing_is_no_flip_and_no_comp_while_it_is_online(self):
        reserved = computer("r", "Garmin Edge 530", 90.0, reserved=True)
        self.sync(self.market() + [reserved])
        d = dashboard.load_dashboard(self.db)
        ids = lambda items: {l.item_id for l in items}
        self.assertIn("r", ids(d.computers))  # nog wel in Alle computers
        self.assertNotIn("r", ids(d.flips))
        self.assertNotIn("r", ids(d.upgrades))
        self.assertIn("gereserveerd", dashboard.all_panel(d))
        # Niet als vergelijkingsprijs: de mediaan blijft die van de vier andere.
        comps = dashboard.pc.db_comparables(self.db, dashboard.pc._default_catalog(), 180)
        self.assertEqual(set(comps["Garmin Edge 530"]), {"a0", "a1", "a2", "a3"})

    def test_a_reserved_listing_that_disappeared_counts_as_a_comp_again(self):
        self.sync(self.market() + [computer("r", "Garmin Edge 530", 90.0, reserved=True)])
        conn = db.connect(self.db)
        try:
            db.sweep_disappeared(conn, "garmin edge", {"a0", "a1", "a2", "a3"}, self.now.isoformat())
        finally:
            conn.close()
        comps = dashboard.pc.db_comparables(self.db, dashboard.pc._default_catalog(), 180)
        self.assertEqual(comps["Garmin Edge 530"]["r"], 90.0)

    def test_a_database_from_before_migration_9_still_has_comps(self):
        # Het dashboard opent alleen-lezen en migreert niet.
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        conn = db.connect(self.db)
        try:
            conn.execute("ALTER TABLE listing DROP COLUMN reserved_at")
            conn.commit()
        finally:
            conn.close()
        d = dashboard.load_dashboard(self.db)
        self.assertIn("c", {l.item_id for l in d.flips})

    def test_a_running_bid_is_labelled_as_one(self):
        bid = computer("x", "Garmin Edge 530", 60.0, price_type="FAST_BID", price_is_bid=True, bid_count=3)
        self.sync(self.market() + [bid])
        listing = next(l for l in dashboard.load_dashboard(self.db).listings if l.item_id == "x")
        self.assertIn("huidig bod", dashboard.price_cell(listing))

    def test_empty_database_says_what_to_do(self):
        conn = db.connect(self.db)
        conn.close()
        html = dashboard.render(dashboard.load_dashboard(self.db))
        self.assertIn("python koopjes.py run nacht", html)

    def test_cli_writes_the_page(self):
        self.sync(self.market())
        out = self.dir / "dashboard.html"
        with redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(dashboard.main(["--db", self.db, "--out", str(out)]), 0)
        self.assertTrue(out.exists())
        self.assertIn("4 computers", printed.getvalue())

    def test_cli_without_database_fails_clearly(self):
        from contextlib import redirect_stderr

        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(dashboard.main(["--db", str(self.dir / "nee.db"), "--out", str(self.dir / "d.html")]), 1)
        self.assertIn("bestaat niet", err.getvalue())


class FastSoldTest(DatabaseCase):
    """Snel verkocht ook bij fietscomputers en horloges (de eigenaar,
    02-10-2026): vanaf 3 die binnen 7 dagen weggingen rust de verkoopprijs op
    hun laatste vraagprijs, zonder afdingfactor — zoals op /racefietsen."""

    def gone(self, ids, days_online=3, reserved=False):
        conn = db.connect(self.db)
        try:
            for item_id in ids:
                conn.execute("UPDATE listing SET disappeared_at = ?, days_online = ?, reserved_at = ? WHERE item_id = ?",
                             ((self.now - timedelta(days=2)).isoformat(), days_online,
                              self.now.isoformat() if reserved else None, item_id))
            conn.commit()
        finally:
            conn.close()

    def setup_market(self):
        sold = [computer(f"s{i}", "Garmin Edge 530", p) for i, p in enumerate((120.0, 130.0, 140.0))]
        self.sync(sold, when=self.now - timedelta(days=6))
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])

    def test_what_counts_as_fast(self):
        gone, first = self.now.isoformat(), (self.now - timedelta(days=30)).isoformat()
        fast = dashboard.pc.is_fast_sold
        self.assertFalse(fast(None, None, 2, first))  # nog online
        self.assertTrue(fast(gone, None, 7, first))
        self.assertFalse(fast(gone, None, 8, first))
        self.assertTrue(fast(gone, gone, 30, first))  # gereserveerd en daarna weg
        self.assertFalse(fast(gone, None, None, first))
        self.assertTrue(fast(gone, None, None, (self.now - timedelta(days=5)).isoformat()))
        self.assertFalse(fast(gone, None, None, None))

    def test_three_sold_fast_set_the_price(self):
        self.setup_market()
        self.gone(["s0", "s1", "s2"])
        d = dashboard.load_dashboard(self.db)
        c = next(l for l in d.listings if l.item_id == "c").computer
        self.assertEqual((c.comp_basis, c.fast_count), ("snel verkocht", 3))
        self.assertEqual(c.resale_eur, 130.0)  # hun mediaan, zonder × 0,875
        self.assertEqual((c.resale_low_eur, c.resale_high_eur), (125.0, 135.0))
        self.assertIn("3 snel verkochte", c.comp_note)
        self.assertEqual(dashboard.comp_text(c), "3 snel verkocht")
        # Marktprijzen en de voorraad in Mijn flips rekenen hetzelfde.
        self.assertEqual(dashboard.model_resale(d)["Garmin Edge 530"], 130.0)
        self.assertEqual(dashboard.model_fast(d)["Garmin Edge 530"], [120.0, 130.0, 140.0])
        market = dashboard.market_panel(d)
        self.assertIn("Snel verkocht", market)
        self.assertIn("mediaan €130", market)

    def test_reserved_and_then_gone_counts_too(self):
        self.setup_market()
        self.gone(["s0", "s1"])
        self.gone(["s2"], days_online=20, reserved=True)
        c = next(l for l in dashboard.load_dashboard(self.db).listings if l.item_id == "c").computer
        self.assertEqual(c.fast_count, 3)

    def test_two_are_not_enough(self):
        import statistics
        self.setup_market()
        self.gone(["s0", "s1"])
        self.gone(["s2"], days_online=30)  # langzaam weg: telt als vraagprijs, niet als snel
        c = next(l for l in dashboard.load_dashboard(self.db).listings if l.item_id == "c").computer
        self.assertEqual((c.comp_basis, c.fast_count), ("vraagprijzen", 2))
        prices = [120.0, 130.0, 140.0, 160.0, 180.0, 200.0, 220.0]
        self.assertAlmostEqual(c.resale_eur, round(statistics.median(prices) * 0.875, 2))
        self.assertIn("nog maar 2 snel verkocht", c.comp_note)
        self.assertEqual(dashboard.comp_text(c), "n=7 vergelijkbaar")

    def test_own_purchases_do_not_count(self):
        self.setup_market()
        self.gone(["s0", "s1", "s2"])
        resale = dashboard.pc.market_resale(self.db, exclude=frozenset({"s0"}))
        # Zonder de eigen aankoop nog 2 snel verkocht: terug naar de vraagprijzen
        # (90, 130, 140, 160, 180, 200, 220: mediaan 160).
        self.assertAlmostEqual(resale["Garmin Edge 530"], round(160.0 * 0.875, 2))


class MarksTest(DatabaseCase):
    """Favoriet en weg (marks.py) in het dashboard."""

    def mark(self, item_id, mark, reason=None, price=None):
        conn = db.connect(self.db)
        try:
            db.set_mark(conn, item_id, mark, reason=reason, price_eur=price)
        finally:
            conn.close()

    def test_a_dismissed_flip_is_gone_from_flips_but_still_in_all_and_a_comp(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.mark("c", "weg", "niet waard", 90.0)
        d = dashboard.load_dashboard(self.db)
        ids = lambda items: {l.item_id for l in items}
        self.assertNotIn("c", ids(d.flips))
        self.assertNotIn("c", ids(d.upgrades))
        self.assertIn("c", ids(d.computers))
        self.assertEqual(ids(d.dismissed_flips), {"c"})
        self.assertIn("1 flip weggezet", dashboard.flips_panel(d))
        all_html = dashboard.all_panel(d)
        self.assertIn("data-mark='weg'", all_html)
        self.assertIn("weggezet (niet waard)", all_html)
        self.assertIn("Toon: weggezet (1)", all_html)
        # Zijn vraagprijs is net zo echt als een andere: hij blijft vergelijkingsprijs.
        comps = dashboard.pc.db_comparables(self.db, dashboard.pc._default_catalog(), 180)
        self.assertIn("c", comps["Garmin Edge 530"])

    def test_the_same_views_as_on_racefietsen(self):
        # Te beoordelen en Weggezet zijn tabknoppen die Alle met een filter
        # openen (de eigenaar, 02-10-2026: elke pagina dezelfde weergaven).
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0), computer("f", "Garmin Edge 530", 95.0)])
        self.mark("c", "weg", "niet waard", 90.0)
        self.mark("f", "favoriet")
        d = dashboard.load_dashboard(self.db)
        review = sum(1 for l, _, _ in d.all_rows if d.to_review(l))
        self.assertEqual(review, len(d.all_rows) - 2)
        page = dashboard.render(d)
        self.assertIn(f"data-tab='beoordelen' data-mark='beoordelen'>Te beoordelen ({review})</button>", page)
        self.assertIn("data-tab='weggezet' data-mark='weg'>Weggezet (1)</button>", page)
        self.assertLess(page.index("data-tab='beoordelen'"), page.index("data-panel='favorieten'"))
        all_html = dashboard.all_panel(d)
        self.assertIn(f"Toon: te beoordelen ({review})", all_html)
        self.assertIn("id='all-pmax'", all_html)
        row = lambda item: re.search(rf"<tr data-item='{item}'[^>]*>", all_html).group(0)
        self.assertIn("data-review='0'", row("c"))
        self.assertIn("data-review='0'", row("f"))
        self.assertIn("data-price='95.0'", row("f"))

    def test_a_dismissed_listing_comes_back_when_its_price_drops(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.mark("c", "weg", "gereserveerd", 90.0)
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 70.0)])
        d = dashboard.load_dashboard(self.db)
        self.assertIn("c", {l.item_id for l in d.flips})
        self.assertIn("Weer terug: de prijs zakte van €90 naar €70", dashboard.flips_panel(d))

    def test_a_dismissed_open_bid_is_gone_too(self):
        bid = computer("x", "Garmin Edge 530", None, price_type="BID", price_is_bid=True)
        self.sync(self.market() + [bid])
        self.assertIn("x", {l.item_id for l in dashboard.load_dashboard(self.db).open_bids})
        self.mark("x", "weg", "niet waard")
        self.assertNotIn("x", {l.item_id for l in dashboard.load_dashboard(self.db).open_bids})

    def test_favorites_have_their_own_tab_and_a_badge(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.mark("c", "favoriet", price=95.0)
        d = dashboard.load_dashboard(self.db)
        self.assertEqual([l.item_id for l, _, _ in d.favorites], ["c"])
        self.assertIn("c", {l.item_id for l in d.flips})  # een favoriet blijft een flip
        html = dashboard.render(d)
        self.assertIn("Favorieten (1)", html)
        self.assertIn("★ favoriet", dashboard.flips_panel(d))
        self.assertIn("bij bewaren €95", dashboard.favorites_panel(d))
        self.assertIn("data-mark='favoriet'", dashboard.all_panel(d))

    def test_a_favorite_that_went_offline_is_listed_as_such(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.mark("c", "favoriet", price=90.0)
        conn = db.connect(self.db)
        try:
            db.sweep_disappeared(conn, "garmin edge", {"a0", "a1", "a2", "a3"}, self.now.isoformat())
        finally:
            conn.close()
        d = dashboard.load_dashboard(self.db)
        self.assertEqual(d.favorites, [])
        self.assertEqual([m.item_id for m in d.gone_favorites], ["c"])
        panel = dashboard.favorites_panel(d)
        self.assertIn("Niet meer online (1)", panel)
        self.assertIn("verdwenen", panel)

    def test_a_favorite_from_the_other_market_stays_there(self):
        watch = computer("w", "Garmin Forerunner 255", 150.0,
                         url="https://www.marktplaats.nl/v/sieraden-tassen-en-uiterlijk/sporthorloges/w-x")
        self.sync(self.market() + [watch])
        self.mark("w", "favoriet", price=150.0)
        bikes = dashboard.load_dashboard(self.db)
        self.assertEqual((bikes.favorites, bikes.gone_favorites), ([], []))
        watches = dashboard.load_dashboard(self.db, market=dashboard.mk.WATCHES)
        self.assertEqual([l.item_id for l, _, _ in watches.favorites], ["w"])

    def note(self, item_id, text):
        conn = db.connect(self.db)
        try:
            db.set_note(conn, item_id, text)
        finally:
            conn.close()

    def test_any_listing_can_have_a_note_and_it_is_searchable(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.note("c", "gevraagd of €80 kan <b>")  # zonder markering
        d = dashboard.load_dashboard(self.db)
        self.assertEqual(d.marks, {})
        self.assertIn("gevraagd of €80 kan &lt;b&gt;", dashboard.flips_panel(d))  # ook in de geschreven pagina
        listing = next(l for l in d.listings if l.item_id == "c")
        self.assertIn("gevraagd of €80 kan", dashboard.search_text(listing, d, "Garmin Edge 530"))
        all_html = dashboard.all_panel(d)
        self.assertIn("gevraagd of €80 kan &lt;b&gt;'", all_html)  # in data-text, voor het zoekvak
        self.assertIn("Toon: met notitie (1)", all_html)
        self.assertEqual(all_html.count("data-note='1'"), 1)
        self.assertNotIn("<form", dashboard.render(d))

    def test_a_note_on_a_favorite_that_went_offline_stays_visible(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.mark("c", "favoriet", price=90.0)
        self.note("c", "verkocht aan een ander")
        conn = db.connect(self.db)
        try:
            db.sweep_disappeared(conn, "garmin edge", {"a0", "a1", "a2", "a3"}, self.now.isoformat())
        finally:
            conn.close()
        d = dashboard.load_dashboard(self.db)
        self.assertIn("verkocht aan een ander", dashboard.favorites_panel(d))
        self.assertIn("Toon: met notitie (0)", dashboard.all_panel(d))  # niet meer actief: niet in Alle

    def test_a_database_from_before_migration_15_shows_the_notes_kept_on_marks(self):
        # Alleen-lezen migreert niet; de notities van migratie 13 staan dan
        # nog bij de markering en moeten niet kwijt lijken.
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.mark("c", "favoriet", price=90.0)
        conn = db.connect(self.db)
        try:
            conn.execute("DROP TABLE listing_note")
            conn.execute("DELETE FROM schema_version WHERE version >= 15")
            conn.execute("UPDATE listing_mark SET note = 'uit migratie 13' WHERE item_id = 'c'")
            conn.commit()
        finally:
            conn.close()
        d = dashboard.load_dashboard(self.db)
        self.assertEqual(d.notes, {"c": "uit migratie 13"})
        self.assertIn("uit migratie 13", dashboard.favorites_panel(d))

    def test_a_database_from_before_migration_12_still_loads(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        conn = db.connect(self.db)
        try:
            conn.execute("DROP TABLE listing_mark")
            conn.execute("DELETE FROM schema_version WHERE version >= 12")
            conn.commit()
        finally:
            conn.close()
        d = dashboard.load_dashboard(self.db)
        self.assertIn("c", {l.item_id for l in d.flips})
        self.assertIn("Favorieten (0)", dashboard.render(d))


class LiveServerTest(unittest.TestCase):
    """--serve: the live dashboard that writes the owner's buys and sales."""

    def setUp(self):
        import http.client
        import re
        import threading
        import urllib.parse

        self.http, self.re, self.urlparse = http.client, re, urllib.parse
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")
        conn = db.connect(self.db)
        try:
            market = [computer(f"a{i}", "Garmin Edge 530", p) for i, p in enumerate((160.0, 180.0, 200.0, 220.0))]
            db.sync_listings(conn, "garmin edge", market + [computer("c", "Garmin Edge 530", 90.0)],
                             datetime.now(timezone.utc).isoformat())
        finally:
            conn.close()
        self.httpd = dashboard.make_server(self.db, 0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path="/", fields=None, host=None, origin=None, live=False):
        conn = self.http.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if live:
            headers["X-Live"] = "1"  # zoals de knoppen op de live pagina (fetch)
        body = None
        if fields is not None:
            body = self.urlparse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if origin:
            headers["Origin"] = origin
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        text = response.read().decode()
        conn.close()
        return response.status, self.urlparse.unquote(response.getheader("Location") or ""), text

    def token(self):
        _, _, page = self.request("GET")
        return self.re.search(r"name='token' value='([^']+)'", page).group(1)

    def every_tab(self):
        """De live pagina met de tabs die hij pas bij openen ophaalt
        (dashboard.LAZY_PANELS) erbij, zoals je hem na het openen van elke
        tab ziet."""
        _, _, page = self.request("GET")
        for name in dashboard.LAZY_PANELS:
            status, _, panel = self.request("GET", f"{dashboard.PANEL_PATH}?markt=fietscomputers&naam={name}")
            self.assertEqual(status, 200)
            page += panel
        return page

    def test_buying_from_a_flip_row_and_selling_it(self):
        import trades as tr

        status, location, _ = self.request("POST", "/gekocht", {"token": self.token(), "item_id": "c", "prijs": "85"})
        self.assertEqual(status, 303)
        self.assertIn("Gekocht", location)
        (trade,) = tr.load_trades(self.db)
        self.assertEqual((trade.item_id, trade.buy_price_eur, trade.model), ("c", 85.0, "Garmin Edge 530"))
        self.assertIsNotNone(trade.expected_resale_eur)

        page = self.every_tab()
        self.assertIn("✓ gekocht", page)
        # Bought is no longer a chance: gone from the flips.
        self.assertNotIn("c", {l.item_id for l in dashboard.load_dashboard(self.db).flips})

        # Verkocht op de dag van de aankoop (vandaag): een vaste datum ging
        # mis zodra "vandaag" erna lag (verkocht vóór gekocht wordt geweigerd).
        self.request("POST", "/verkocht", {"token": self.token(), "id": trade.id, "prijs": "150,50",
                                           "kosten": "3", "datum": trade.bought_at, "via": "vinted"})
        (trade,) = tr.load_trades(self.db)
        self.assertEqual((trade.sell_price_eur, trade.sold_via, trade.profit_eur), (150.5, "vinted", 62.5))
        _, _, page = self.request("GET")
        self.assertIn("Mijn flips (+€62)", page)

    def test_adding_a_buy_from_elsewhere(self):
        import trades as tr

        self.request("POST", "/toevoegen", {"token": self.token(), "titel": "Roam van Vinted",
                                            "model": "Wahoo ELEMNT ROAM v1", "prijs": "60", "kosten": "3"})
        (trade,) = tr.load_trades(self.db)
        self.assertEqual((trade.title, trade.buy_costs_eur, trade.item_id), ("Roam van Vinted", 3.0, None))

    def test_a_sale_before_the_buy_is_refused(self):
        import trades as tr

        self.request("POST", "/toevoegen", {"token": self.token(), "titel": "x", "prijs": "10",
                                            "datum": "2026-09-10"})
        (trade,) = tr.load_trades(self.db)
        _, location, _ = self.request("POST", "/verkocht", {"token": self.token(), "id": trade.id, "prijs": "20",
                                                            "datum": "2026-09-01"})
        self.assertIn("vóór de aankoop", location)
        self.assertFalse(tr.load_trades(self.db)[0].sold)

    def test_bad_input_is_reported_not_saved(self):
        import trades as tr

        _, location, _ = self.request("POST", "/toevoegen", {"token": self.token(), "titel": "x", "prijs": "abc"})
        self.assertIn("Niet opgeslagen", location)
        self.assertEqual(tr.load_trades(self.db), [])

    def test_no_token_no_write(self):
        import trades as tr

        _, location, _ = self.request("POST", "/toevoegen", {"titel": "x", "prijs": "10"})
        self.assertIn("niets opgeslagen", location)
        self.assertEqual(tr.load_trades(self.db), [])

    def test_other_sites_and_hosts_are_refused(self):
        token = self.token()
        status, _, _ = self.request("POST", "/toevoegen", {"token": token, "titel": "x", "prijs": "10"},
                                    origin="https://evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(self.request("GET", host="evil.example")[0], 403)

    def test_putting_a_listing_away_and_back(self):
        status, location, _ = self.request("POST", "/markeer", {"token": self.token(), "item_id": "c",
                                                                 "soort": "niet waard", "tab": "flips"})
        self.assertEqual(status, 303)
        self.assertTrue(location.endswith("#flips"))  # terug naar de tab waar je klikte
        self.assertIn("Weggezet (niet waard)", location)
        self.assertIn("onder €90 zakt", location)
        self.assertNotIn("c", {l.item_id for l in dashboard.load_dashboard(self.db).flips})

        page = self.every_tab()
        self.assertIn("terugzetten", page)
        self.request("POST", "/markeer", {"token": self.token(), "item_id": "c", "soort": "geen", "tab": "alle"})
        self.assertIn("c", {l.item_id for l in dashboard.load_dashboard(self.db).flips})

    def test_a_favorite_from_the_live_page(self):
        self.request("POST", "/markeer", {"token": self.token(), "item_id": "c", "soort": "favoriet"})
        (mark,) = dashboard.mr.load_marks(self.db).values()
        self.assertEqual((mark.item_id, mark.mark, mark.price_eur), ("c", "favoriet", 90.0))
        _, _, page = self.request("GET")
        self.assertIn("Favorieten (1)", page)
        self.assertIn("★ uit favorieten", page)

    def test_a_note_on_any_listing(self):
        _, _, page = self.request("GET")
        self.assertIn("notitie toevoegen", page)  # ook zonder markering
        _, location, _ = self.request("POST", "/notitie", {"token": self.token(), "item_id": "c",
                                                           "notitie": "  vraag of\r\n80 kan ", "tab": "flips"})
        self.assertIn("Notitie opgeslagen", location)
        self.assertTrue(location.endswith("#flips"))
        self.assertEqual(dashboard.mr.load_notes(self.db), {"c": "vraag of 80 kan"})
        _, _, page = self.request("GET")
        self.assertIn("notitie wijzigen", page)

        # De notitie staat los van de markering: die zetten en weghalen laat hem staan.
        self.request("POST", "/markeer", {"token": self.token(), "item_id": "c", "soort": "gereserveerd"})
        self.request("POST", "/markeer", {"token": self.token(), "item_id": "c", "soort": "geen"})
        self.assertEqual(dashboard.mr.load_notes(self.db), {"c": "vraag of 80 kan"})

    def test_an_empty_note_clears_it_and_a_long_or_stray_one_is_refused(self):
        self.request("POST", "/notitie", {"token": self.token(), "item_id": "c", "notitie": "x"})
        _, location, _ = self.request("POST", "/notitie", {"token": self.token(), "item_id": "c", "notitie": " "})
        self.assertIn("Notitie gewist", location)
        self.assertEqual(dashboard.mr.load_notes(self.db), {})
        _, location, _ = self.request("POST", "/notitie", {"token": self.token(), "item_id": "c",
                                                           "notitie": "x" * 501})
        self.assertIn("te lang", location)
        _, location, _ = self.request("POST", "/notitie", {"token": self.token(), "item_id": "zz",
                                                           "notitie": "bestaat niet"})
        self.assertIn("Onbekende advertentie", location)
        self.assertEqual(dashboard.mr.load_notes(self.db), {})

    def test_marking_refuses_what_it_does_not_know(self):
        _, location, _ = self.request("POST", "/markeer", {"token": self.token(), "item_id": "c", "soort": "weg"})
        self.assertIn("Niet opgeslagen", location)
        _, location, _ = self.request("POST", "/markeer", {"token": self.token(), "item_id": "zz",
                                                           "soort": "favoriet"})
        self.assertIn("staat niet (meer) in het dashboard", location)
        _, location, _ = self.request("POST", "/markeer", {"token": self.token(), "item_id": "c", "soort": "geen"})
        self.assertIn("had geen markering", location)
        self.assertEqual(dashboard.mr.load_marks(self.db), {})

    def test_the_tab_to_go_back_to_is_only_ever_a_tab_name(self):
        for tab in ("flips\r\nSet-Cookie: x=1", "../x", "Flips", ""):
            _, location, _ = self.request("POST", "/markeer", {"token": self.token(), "item_id": "c",
                                                               "soort": "favoriet", "tab": tab})
            self.assertNotIn("#", location, tab)
        # Te beoordelen is een knop op Alle met een filter; de pagina stuurt
        # zijn naam mee, zodat je na controleer daar terugkomt.
        _, location, _ = self.request("POST", "/markeer", {"token": self.token(), "item_id": "c",
                                                           "soort": "favoriet", "tab": "beoordelen"})
        self.assertTrue(location.endswith("#beoordelen"))
        _, _, page = self.request("GET")
        self.assertIn("active.dataset.tab || active.dataset.panel", page)
        # Na Gekocht blijft het Mijn flips, ook als er een tab meekomt.
        _, location, _ = self.request("POST", "/gekocht", {"token": self.token(), "item_id": "c", "prijs": "85",
                                                           "tab": "flips"})
        self.assertTrue(location.endswith("#mijn"))

    def live(self, path, fields):
        import json
        status, location, text = self.request("POST", path, {"token": self.token(), **fields}, live=True)
        self.assertEqual((status, location), (200, ""))
        return json.loads(text)

    def test_marking_without_reloading(self):
        _, _, page = self.request("GET")
        self.assertIn("Flips (2)", page)  # c en a0
        data = self.live("/markeer", {"item_id": "c", "soort": "niet waard", "tab": "flips"})
        self.assertIn("Weggezet (niet waard)", data["message"])
        item = data["item"]
        self.assertEqual((item["id"], item["mark"], item["available"]), ("c", "weg", False))
        self.assertIn("weggezet (niet waard)", item["badge"])
        self.assertIn("terugzetten", item["mine"])
        self.assertEqual(data["tabs"]["flips"], "Flips (1)")
        self.assertEqual(data["tabs"]["weggezet"], "Weggezet (1)")
        self.assertEqual(item["review"], 0)
        self.assertIn("1 flip weggezet", data["away"])
        # Weg is een rij verbergen; het hele tabblad komt pas mee bij terugzetten.
        self.assertEqual(set(data["panels"]), {"favorieten"})
        back = self.live("/markeer", {"item_id": "c", "soort": "geen"})
        self.assertTrue(back["item"]["available"])
        self.assertIn("flips", back["panels"])
        self.assertEqual(back["tabs"]["flips"], "Flips (2)")

    def test_a_favorite_and_a_note_without_reloading(self):
        data = self.live("/markeer", {"item_id": "c", "soort": "favoriet"})
        self.assertEqual(data["item"]["mark"], "favoriet")
        self.assertEqual(data["tabs"]["favorieten"], "Favorieten (1)")
        self.assertIn("data-item='c'", data["panels"]["favorieten"])
        self.assertIn("favorieten (1)", data["markOptions"])
        data = self.live("/notitie", {"item_id": "c", "notitie": "vraag of 80 kan"})
        self.assertEqual(data["item"]["note"], 1)
        self.assertIn("vraag of 80 kan", data["item"]["mine"])
        self.assertIn("vraag of 80 kan", data["item"]["text"])  # het zoekvak vindt hem

    def test_a_refusal_or_a_stale_page_without_reloading(self):
        import json
        self.assertIn("Niet opgeslagen", self.live("/markeer", {"item_id": "c", "soort": "weg"})["message"])
        _, _, text = self.request("POST", "/markeer", {"token": "oud", "item_id": "c", "soort": "favoriet"},
                                  live=True)
        self.assertTrue(json.loads(text)["reload"])
        self.assertEqual(dashboard.mr.load_marks(self.db), {})

    def test_the_live_page_has_buttons_not_a_form_per_listing(self):
        # Duizenden formulieren maakten de pagina traag; alleen Mijn flips
        # (een handvol) heeft ze nog.
        _, _, page = self.request("GET")
        self.assertNotIn("method='post' action='/markeer'", page)
        self.assertNotIn("method='post' action='/gekocht'", page)
        self.assertIn("data-action='/markeer' data-item='c'", page)
        self.assertIn("data-action='/gekocht' data-item='c'", page)
        self.assertIn("data-action='/notitie' data-item='c'", page)

    def test_all_listings_come_when_the_tab_is_opened(self):
        # Alle computers is het grootste deel van de pagina; live haalt de
        # pagina hem pas op als je de tab opent. Het geschreven bestand
        # heeft hem gewoon, dat heeft geen server om te vragen.
        _, _, page = self.request("GET")
        self.assertIn("<section class='panel' id='panel-alle' hidden data-lazy=1></section>", page)
        self.assertNotIn("id='all-table'", page)
        self.assertIn("data-action='/markeer' data-item='c'", page)  # Flips staat er wel
        status, _, panel = self.request("GET", "/paneel?markt=fietscomputers&naam=alle")
        self.assertEqual(status, 200)
        self.assertIn("id='all-table'", panel)
        self.assertIn("data-action='/markeer' data-item='a3'", panel)
        self.assertIn("id='all-table'", dashboard.render(dashboard.load_dashboard(self.db)))
        for query in ("markt=fietscomputers&naam=bestaatniet", "markt=onbekend&naam=alle", ""):
            self.assertEqual(self.request("GET", f"/paneel?{query}")[0], 404, query)
        self.assertEqual(self.request("GET", "/paneel?markt=fietscomputers&naam=alle", host="evil.example")[0], 403)

    def test_the_heavy_part_is_remembered_until_a_round_changes_the_data(self):
        cache = dashboard.LiveCache()
        first = cache.dashboard(self.db, dashboard.mk.COMPUTERS)
        conn = db.connect(self.db)
        try:
            db.set_mark(conn, "c", "favoriet", price_eur=90.0)
        finally:
            conn.close()
        again = cache.dashboard(self.db, dashboard.mk.COMPUTERS)
        self.assertIs(again.listings, first.listings)  # niet opnieuw gerekend
        self.assertIn("c", again.marks)  # maar de markering is vers
        conn = db.connect(self.db)
        try:
            db.sync_listings(conn, "garmin edge", [computer("n", "Garmin Edge 830", 120.0)],
                             (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
        finally:
            conn.close()
        after = cache.dashboard(self.db, dashboard.mk.COMPUTERS)
        self.assertIsNot(after.listings, first.listings)
        self.assertIn("n", {l.item_id for l in after.listings})

    def test_two_requests_at_once_build_once(self):
        # Een tweede verzoek (of het vooruitwerken van de server) wacht op de
        # lopende opbouw in plaats van hem nog eens te doen.
        import threading
        import time
        from unittest import mock
        cache = dashboard.LiveCache()
        real = dashboard.load_base

        def slow(*args, **kwargs):
            time.sleep(0.2)
            return real(*args, **kwargs)

        with mock.patch.object(dashboard, "load_base", side_effect=slow) as built:
            found = []
            threads = [threading.Thread(target=lambda: found.append(cache.dashboard(self.db, dashboard.mk.COMPUTERS)))
                       for _ in range(3)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        self.assertEqual(built.call_count, 1)
        self.assertEqual(len({id(d.listings) for d in found}), 1)

    def test_a_long_calculation_does_not_hold_up_other_pages(self):
        # De vergelijkingskandidaten voor /fiets (en het vooruitrekenen) mogen
        # een dashboard dat al klaarstaat niet laten wachten.
        import threading
        import time
        from unittest import mock
        cache = dashboard.LiveCache()
        cache.dashboard(self.db, dashboard.mk.COMPUTERS)
        started = threading.Event()

        def slow(conn):
            started.set()
            time.sleep(0.6)
            return []

        with mock.patch.object(dashboard.val, "fetch_comp_candidates", side_effect=slow):
            worker = threading.Thread(target=cache.comps, args=(self.db,))
            worker.start()
            started.wait(5)
            begin = time.monotonic()
            cache.dashboard(self.db, dashboard.mk.COMPUTERS)
            waited = time.monotonic() - begin
            worker.join()
        self.assertLess(waited, 0.3)

    def test_static_page_has_no_forms(self):
        html = dashboard.render(dashboard.load_dashboard(self.db))
        self.assertNotIn("<form", html)
        self.assertIn("python dashboard.py --serve", html)


class KeepWarmTest(unittest.TestCase):
    """De server rekent na het starten en na elke ronde alvast vooruit, maar
    niet tijdens een ronde (dan verandert de database steeds)."""

    def test_after_start_and_once_a_round_is_done(self):
        from unittest import mock
        stamps = iter(["A", "A", "B", "C", "C", "C", "D"])

        class Stop:
            calls = 0

            def is_set(self):
                return self.calls >= 7

            def wait(self, _seconds):
                self.calls += 1

        cache = mock.Mock()
        with mock.patch.object(dashboard, "data_stamp", side_effect=lambda *_: next(stamps)), \
                mock.patch.object(dashboard.Path, "exists", return_value=True):
            dashboard.keep_warm(cache, "koopjes.db", "mijn_fiets.md", Stop(), every=0)
        # A meteen; B en C veranderden nog (een ronde loopt); C bleef staan: dan.
        self.assertEqual(cache.warm.call_count, 2)

    def test_a_failure_only_means_no_head_start(self):
        from unittest import mock

        class Stop:
            calls = 0

            def is_set(self):
                return self.calls >= 2

            def wait(self, _seconds):
                self.calls += 1

        cache = mock.Mock()
        cache.warm.side_effect = RuntimeError("oude database")
        with mock.patch.object(dashboard, "data_stamp", return_value="A"), \
                mock.patch.object(dashboard.Path, "exists", return_value=True):
            dashboard.keep_warm(cache, "koopjes.db", "mijn_fiets.md", Stop(), every=0)
        self.assertEqual(cache.warm.call_count, 1)  # niet elke minuut opnieuw proberen


class AbortedConnectionTest(unittest.TestCase):
    def test_a_browser_that_hangs_up_is_not_an_error(self):
        # Windows, WinError 10053: de browser sloot de verbinding terwijl de
        # pagina nog werd verstuurd. Geen traceback in het venster.
        class Wfile:
            def write(self, data):
                raise ConnectionAbortedError(10053, "verbinding verbroken")

        handler = dashboard.DashboardHandler.__new__(dashboard.DashboardHandler)
        handler.wfile = Wfile()
        handler.send_response = handler.send_header = lambda *a: None
        handler.end_headers = lambda: None
        handler.close_connection = False
        handler._send(200, "<html></html>", "text/html; charset=utf-8")
        self.assertTrue(handler.close_connection)


if __name__ == "__main__":
    unittest.main()


class BikePageTest(unittest.TestCase):
    """/fiets: per advertentie meenemen of niet voor de taxatie van de eigen fiets."""

    def setUp(self):
        import http.client
        import threading
        import urllib.parse
        from helpers import repo_file

        self.http, self.urlparse = http.client, urllib.parse
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")
        conn = db.connect(self.db)
        try:
            bikes = [make_listing(item_id=f"d{i}", title=f"Giant Defy carbon Ultegra nr {i}", price_eur=p,
                                  url=BIKE_URL.format(f"d{i}")) for i, p in enumerate((500.0, 600.0, 700.0))]
            bikes.append(make_listing(item_id="alu", title="Giant Defy 1 aluminium", price_eur=300.0,
                                      url=BIKE_URL.format("alu")))
            bikes.append(make_listing(
                item_id="sport", title="Giant Defy racefiets", price_eur=450.0,
                url="https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-heren-sportfietsen-en-toerfietsen/sport-x"))
            db.sync_listings(conn, "giant defy", bikes, datetime.now(timezone.utc).isoformat())
            db.sync_listing_specs(conn, {"sport": {"frame_material": "aluminium"}}, source=db.SITE_SPEC_SOURCE)
        finally:
            conn.close()
        self.httpd = dashboard.make_server(self.db, 0, intake_path=repo_file("mijn_fiets.md"))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, fields=None, live=False):
        conn = self.http.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if live:
            headers["X-Live"] = "1"
        body = None
        if fields is not None:
            body = self.urlparse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        text = response.read().decode()
        conn.close()
        return response.status, self.urlparse.unquote(response.getheader("Location") or ""), text

    def token(self):
        import re
        _, _, page = self.request("GET", "/fiets")
        return re.search(r"data-token='([^']+)'", page).group(1)

    def choose(self, item_id, choice):
        import json
        status, _, text = self.request("POST", "/fiets/keuze",
                                       {"token": self.token(), "item_id": item_id, "keuze": choice}, live=True)
        self.assertEqual(status, 200)
        return json.loads(text)

    def test_the_list_has_every_defy_with_its_material_and_category(self):
        status, _, page = self.request("GET", "/fiets")
        self.assertEqual(status, 200)
        for item_id in ("d0", "d1", "d2", "alu", "sport"):
            self.assertIn(f"data-item='{item_id}' data-choice='open'", page)
        self.assertIn("Te beoordelen (5)", page)
        # Het materiaal staat erbij, en of alleen de verkoper het zegt.
        self.assertIn("Giant Defy 1 aluminium</a><div class='note'>aluminium", page)
        self.assertIn("aluminium volgens de verkoper · in heren sportfietsen en toerfietsen", page)
        self.assertIn("nog niets meegenomen", page)
        # Vanaf de andere live pagina's is hij te vinden.
        _, _, computers = self.request("GET", "/")
        self.assertIn("href='/fiets'", computers)

    def test_taking_listings_along_values_the_bike_without_reloading(self):
        data = self.choose("d0", "mee")
        self.assertEqual(data["message"], "Meegenomen: Giant Defy carbon Ultegra nr 0.")
        self.assertIn("data-choice='mee'", data["row"])
        self.assertIn("aria-pressed='true'", data["row"])
        self.assertIn("Meegenomen (1)", data["options"])
        self.assertIn("n=1", data["summary"])
        self.choose("d1", "mee")
        data = self.choose("d2", "niet")
        self.assertIn("n=2", data["summary"])
        self.assertIn("Niet (1)", data["options"])
        conn = db.connect(self.db)
        try:
            self.assertEqual(db.list_comp_choices(conn), {"d0": "mee", "d1": "mee", "d2": "niet"})
        finally:
            conn.close()
        # Nog eens op de gekozen knop: terug naar te beoordelen.
        data = self.choose("d0", "")
        self.assertIn("data-choice='open'", data["row"])
        self.assertIn("Terug naar te beoordelen", data["message"])

    def test_without_javascript_it_goes_back_to_the_page(self):
        status, location, _ = self.request("POST", "/fiets/keuze",
                                           {"token": self.token(), "item_id": "d0", "keuze": "mee"})
        self.assertEqual(status, 303)
        self.assertTrue(location.startswith("/fiets?melding=Meegenomen"))

    def test_nonsense_is_refused(self):
        self.assertIn("Niet opgeslagen", self.choose("d0", "misschien")["message"])
        self.assertIn("Onbekende advertentie", self.choose("zz", "mee")["message"])
        status, location, _ = self.request("POST", "/fiets/keuze", {"token": "oud", "item_id": "d0", "keuze": "mee"})
        self.assertIn("verouderd", location)
        conn = db.connect(self.db)
        try:
            self.assertEqual(db.list_comp_choices(conn), {})
        finally:
            conn.close()
