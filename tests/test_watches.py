"""Sporthorloges: dezelfde flipberekening en hetzelfde dashboard als de
fietscomputers, op de categorieën sporthorloges, smartwatches en
activity-trackers (markets.WATCHES, watches.py)."""
import http.client
import io
import re
import shutil
import tempfile
import threading
import unittest
import urllib.parse
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import make_listing

import computers as pc
import dashboard
import db
import markets as mk
import patterns as pt
import trades as tr
import watches

WATCH_URL = "https://www.marktplaats.nl/v/sieraden-tassen-en-uiterlijk/{}/{}-x"
PHONE_URL = "https://www.marktplaats.nl/v/telecommunicatie/mobiele-telefoons-toebehoren-en-onderdelen/{}-x"
COMPUTER_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/{}-x"
CONFIG = pc.load_config()
FACTOR = CONFIG["flip"]["negotiation_factor"]
COSTS = CONFIG["flip"]["costs_eur"]


def watch(item_id, title, price, category="sporthorloges", **kw):
    kw.setdefault("url", WATCH_URL.format(category, item_id))
    return make_listing(item_id=item_id, title=title, price_eur=price, **kw)


def fenix_market():
    # Vier Fenix 6 Pro's; één in smartwatches en één in activity-trackers:
    # die categorieën tellen ook.
    return [watch(f"a{i}", "Garmin Fenix 6 Pro 47 mm", p, category=c)
            for i, (p, c) in enumerate(((200.0, "sporthorloges"), (200.0, "smartwatches"),
                                        (210.0, "activity-trackers"), (220.0, "sporthorloges")))]


class WatchDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")

    def sync(self, listings, when=None, query="garmin"):
        conn = db.connect(self.db)
        try:
            moment = (when or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
            db.sync_listings(conn, query, listings, moment)
        finally:
            conn.close()

    def board(self):
        return dashboard.load_dashboard(self.db, market=mk.WATCHES)


class WatchFlipsTest(WatchDatabaseTest):
    def test_cheap_watch_is_a_flip(self):
        cheap = watch("c", "Garmin fēnix 6X Pro Sapphire 51mm", 100.0)
        self.sync(fenix_market() + [cheap])
        found = {l.item_id: l for l in self.board().flips}
        self.assertEqual(set(found), {"c"})
        self.assertAlmostEqual(found["c"].computer.profit_eur, 205.0 * FACTOR - 100.0 - COSTS, places=2)
        self.assertEqual(found["c"].computer.model.label, "Garmin Fenix 6 Pro")

    def test_other_categories_are_neither_loaded_nor_comparables(self):
        # Een bandje of kabel met "Fenix 6 Pro" in de titel staat in een
        # telefooncategorie; als vergelijkingsprijs zou het de mediaan omlaag
        # trekken en de flips verbergen. Een fietscomputer hoort op het andere
        # dashboard.
        straps = [make_listing(item_id=f"s{i}", title="Garmin Fenix 6 Pro", price_eur=15.0,
                               url=PHONE_URL.format(f"s{i}")) for i in range(5)]
        edge = make_listing(item_id="e", title="Garmin Edge 530", price_eur=150.0, url=COMPUTER_URL.format("e"))
        cheap = watch("c", "Garmin Fenix 6 Pro", 100.0)
        self.sync(fenix_market() + straps + [edge, cheap])
        d = self.board()
        self.assertEqual({l.item_id for l in d.listings}, {"a0", "a1", "a2", "a3", "c"})
        self.assertIn("c", {l.item_id for l in d.flips})
        self.assertAlmostEqual(dashboard.model_resale(d)["Garmin Fenix 6 Pro"], 200.0 * FACTOR)
        # En omgekeerd: het fietscomputerdashboard ziet geen horloges.
        self.assertEqual({l.item_id for l in dashboard.load_dashboard(self.db).listings}, {"e"})

    def test_accessories_from_the_real_crawl_are_filtered_out(self):
        # Alle drie uit de crawl van 28-09-2026, in de categorie sporthorloges.
        accessory_set = watch("t", "Forerunner 945 Tri accessoires: HRM-Swim + Quick Release kit", 65.0)
        dock = watch("d", "25009 Docking Station Garmin Fenix 5/6/7/8", 10.0)
        strap = watch("b", "Garmin Fenix 6 Pro bandje", 12.0)
        market945 = [watch(f"f{i}", "Garmin Forerunner 945", p) for i, p in enumerate((200.0, 215.0, 230.0))]
        self.sync(fenix_market() + market945 + [accessory_set, dock, strap])
        d = self.board()
        self.assertTrue({"t", "d", "b"} <= {l.item_id for l, _, _ in d.excluded})
        self.assertEqual(d.flips, [])

    def test_watch_with_strap_is_still_a_watch(self):
        with_strap = watch("w", "Garmin Fenix 6S 42 mm zwart met een zwarte siliconen polsband", 100.0)
        self.sync(fenix_market() + [with_strap])
        self.assertIn("w", {l.item_id for l in self.board().items})

    def test_free_swap_offer_is_not_a_flip(self):
        swap = watch("r", "Garmin Fenix 6 Pro - Topconditie graag ruilen", 0.0, price_type="FREE")
        self.sync(fenix_market() + [swap])
        d = self.board()
        self.assertNotIn("r", {l.item_id for l in d.flips})
        self.assertIn("r", {l.item_id for l in d.open_bids})
        # En in Marktprijzen is de laagste prijs niet €0.
        self.assertNotIn(">€0<", dashboard.market_panel(d))


class BidMemoryTest(WatchDatabaseTest):
    """Migratie 11: het opgehaalde bod blijft staan tot de volgende opvraging."""

    def bidding(self, **kw):
        kw.setdefault("price_type", "FAST_BID")
        return watch("b", "Garmin Fenix 6 Pro", kw.pop("price", None), **kw)

    def test_a_round_without_lookup_keeps_the_last_bid(self):
        night = datetime.now(timezone.utc) - timedelta(hours=7)
        self.sync(fenix_market() + [self.bidding(price=120.0, price_is_bid=True, bid_count=3, bid_minimum=100.0)],
                  when=night)
        # Overdag: dezelfde advertentie zonder opvraging, dus zonder prijs.
        self.sync(fenix_market() + [self.bidding()])
        listing = {l.item_id: l for l in self.board().listings}["b"]
        self.assertEqual((listing.price_eur, listing.bid_count, listing.bid_minimum), (120.0, 3, 100.0))
        self.assertIn("huidig bod", pc.price_kind(listing))
        note = dashboard.bid_note(listing)
        self.assertIn("3 biedingen", note)
        self.assertIn("min. €100", note)
        self.assertIn("opgehaald", note)

    def test_a_new_lookup_replaces_the_old_one(self):
        self.sync([self.bidding(price=120.0, price_is_bid=True, bid_count=3)],
                  when=datetime.now(timezone.utc) - timedelta(hours=7))
        self.sync([self.bidding(price=150.0, price_is_bid=True, bid_count=5)])
        listing = self.board().listings[0]
        self.assertEqual((listing.price_eur, listing.bid_count), (150.0, 5))

    def test_without_any_lookup_there_is_no_bid_note(self):
        self.sync([self.bidding()])
        listing = self.board().listings[0]
        self.assertIsNone(listing.price_eur)
        self.assertEqual(dashboard.bid_note(listing), "")

    def test_no_bids_yet_shows_the_minimum(self):
        self.sync(fenix_market() + [self.bidding(price=90.0, price_is_bid=True, bid_count=0, bid_minimum=90.0)])
        listing = {l.item_id: l for l in self.board().listings}["b"]
        self.assertIn("nog geen bod", dashboard.bid_note(listing))
        # Een minimumbod zonder biedingen is een instapprijs: de flip rekent ermee.
        self.assertIn("b", {l.item_id for l in self.board().flips})


class UnknownWatchTest(unittest.TestCase):
    """Titels zonder bekend model, uit de crawl van 28-09-2026."""

    def test_kinds(self):
        cases = {
            "Te koop Garmin horloge": "horloge",
            "Garmin smartwatch - Werkt naar behoren": "horloge",
            "Garmin Tactix 7 - Premium Tactische GPS Smartwatch": "horloge",
            "Garmin QuickFit 22 Watch Band - Wit / Whitestone": "accessoire",
            "25122d Originele Garmin Quickfit horlogeband 22mm": "accessoire",
            "USB-C Oplaadkabel voor Garmin Smartwatches": "accessoire",
            "Horlogebandje voor GARMIN (22mm) - Nieuw": "accessoire",
            "Apple watch 10 zgan batterij 99%": "overig",
            "Fitbit Charge 5": "overig",
            "Garmin Index Sleep Monitor": "overig",
            "Garmin HRM-Pro Plus hartslagband": "overig",
            "Smartwatch": "overig",
            "ik zoek een garmin horloge": "gevraagd",
            "Garmin horloge defect": "defect",
            # Polar, Suunto en Coros zijn sinds 29-09-2026 ook gevolgde merken.
            "Polar M400 GPS sporthorloge - Gebruikt": "horloge",
            "Suunto Core All Black Outdoor Horloge": "horloge",
            "Suunto Traverse GPS-horloge + hartslagband": "horloge",
            "Suunto Traverse Graphite (met nieuw bandje)": "horloge",
            "Polsband voor Polar V2 zwart horlogeband siliconen": "accessoire",
            "Polar USB Oplaadkabel": "accessoire",
            "Polar CS300 Fietscomputer met Hartslagmeter en Cadanssensor": "overig",
            "Omega x Swatch Moonswatch Polar Lights": "overig",
        }
        for title, kind in cases.items():
            with self.subTest(title=title):
                self.assertEqual(watches.classify_unknown(title)[0], kind)


class WatchDashboardTest(WatchDatabaseTest):
    def test_page_has_its_own_tabs_and_words(self):
        self.sync(fenix_market() + [watch("c", "Garmin Fenix 6 Pro", 100.0),
                                    watch("u", "Te koop Garmin horloge", 90.0),
                                    watch("q", "Garmin QuickFit 22 Watch Band", 15.0)])
        html = dashboard.render(self.board())
        for text in ("<title>Sporthorloges</title>", "Sporthorloges op Marktplaats", "Flips (1)",
                     "Alle horloges (6)", "Marktprijzen", "Patronen", "Uitgefilterd (1)",
                     "reference_sport_watches.csv", "model onbekend"):
            with self.subTest(text=text):
                self.assertIn(text, html)
        for text in ("Upgrades (", "Vinted", "Score", "fietscomputers"):
            with self.subTest(text=text):
                self.assertNotIn(text, html)

    def test_empty_database_says_so(self):
        self.sync([make_listing(item_id="x", title="Racefiets",
                                url="https://www.marktplaats.nl/v/fietsen/fietsen-racefietsen/x-x")])
        self.assertIn("Nog geen sporthorloges in de database", dashboard.render(self.board()))

    def test_cli_writes_the_watch_dashboard_and_links_the_other(self):
        self.sync(fenix_market())
        out = self.dir / "dashboard_horloges.html"
        (self.dir / "dashboard.html").write_text("x", encoding="utf-8")
        with redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(dashboard.main(["--db", self.db, "--markt", "sporthorloges", "--out", str(out)]), 0)
        self.assertIn("horloges", printed.getvalue())
        self.assertIn("href='dashboard.html'", out.read_text(encoding="utf-8"))

    def test_cli_writes_both(self):
        self.sync(fenix_market())
        with redirect_stdout(io.StringIO()):
            previous = Path.cwd()
            import os
            os.chdir(self.dir)
            try:
                self.assertEqual(dashboard.main(["--db", self.db, "--markt", "alle"]), 0)
            finally:
                os.chdir(previous)
        self.assertTrue((self.dir / "dashboard.html").exists())
        self.assertTrue((self.dir / "dashboard_horloges.html").exists())

    def test_patterns_count_watches_only(self):
        start = datetime.now(timezone.utc) - timedelta(days=10)
        self.sync(fenix_market(), when=start)
        self.sync([make_listing(item_id="e", title="Garmin Edge 530", price_eur=150.0,
                                url=COMPUTER_URL.format("e"))], when=start)
        self.assertEqual(pt.load_patterns(self.db, market=mk.WATCHES).total, 4)
        self.assertEqual(pt.load_patterns(self.db).total, 1)

    def test_own_buys_show_on_their_own_dashboard(self):
        self.sync(fenix_market() + [watch("c", "Garmin Fenix 6 Pro", 100.0)])
        conn = db.connect(self.db)
        try:
            db.add_trade(conn, title="Garmin Fenix 6 Pro", bought_at="2026-09-28", buy_price_eur=100.0,
                         item_id="c", model="Garmin Fenix 6 Pro", market="sporthorloges")
            # Van vóór migratie 10: geen markt, wel een model.
            db.add_trade(conn, title="Garmin Edge 530", bought_at="2026-09-20", buy_price_eur=90.0,
                         model="Garmin Edge 530")
        finally:
            conn.close()
        watch_board, computer_board = self.board(), dashboard.load_dashboard(self.db)
        self.assertEqual([s.trade.title for s in watch_board.progress.stock], ["Garmin Fenix 6 Pro"])
        self.assertEqual([s.trade.title for s in computer_board.progress.stock], ["Garmin Edge 530"])
        # De voorraad wordt gewaardeerd tegen de horlogemarkt, zonder het eigen koopje.
        self.assertAlmostEqual(watch_board.progress.stock[0].expected_resale_eur, 205.0 * FACTOR, places=2)
        self.assertNotIn("c", {l.item_id for l in watch_board.flips})

    def test_trade_market_falls_back_to_the_model(self):
        old = tr.Trade(id=1, title="x", bought_at="2026-01-01", buy_price_eur=1.0, model="Garmin Venu 3")
        self.assertIs(mk.trade_market(old), mk.WATCHES)
        self.assertIs(mk.trade_market(tr.Trade(id=2, title="x", bought_at="2026-01-01", buy_price_eur=1.0)),
                      mk.COMPUTERS)


class WatchConsoleTest(WatchDatabaseTest):
    def test_main_prints_market_and_flips(self):
        self.sync(fenix_market() + [watch("c", "Garmin Fenix 6 Pro", 100.0)])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(watches.main(["--db", self.db]), 0)
        text = out.getvalue()
        self.assertIn("Garmin Fenix 6 Pro", text)
        self.assertIn("1 boven €0", text)

    def test_no_watches_says_what_to_do(self):
        self.sync([make_listing(item_id="x", title="Racefiets",
                                url="https://www.marktplaats.nl/v/fietsen/fietsen-racefietsen/x-x")])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(watches.main(["--db", self.db]), 0)
        self.assertIn("sporthorloges", out.getvalue())


class WatchLiveServerTest(WatchDatabaseTest):
    def setUp(self):
        super().setUp()
        self.sync(fenix_market() + [watch("c", "Garmin Fenix 6 Pro", 100.0)])
        self.httpd = dashboard.make_server(self.db, 0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, fields=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        body = None
        if fields is not None:
            body = urllib.parse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        text = response.read().decode()
        conn.close()
        return response.status, urllib.parse.unquote(response.getheader("Location") or ""), text

    def token(self):
        _, _, page = self.request("GET", "/horloges")
        return re.search(r"name='token' value='([^']+)'", page).group(1)

    def test_watch_page_and_buying_from_it(self):
        status, _, page = self.request("GET", "/horloges")
        self.assertEqual(status, 200)
        self.assertIn("Sporthorloges op Marktplaats", page)
        self.assertIn("name='markt' value='sporthorloges'", page)
        status, location, _ = self.request("POST", "/gekocht", {"token": self.token(), "markt": "sporthorloges",
                                                                 "item_id": "c", "prijs": "95"})
        self.assertEqual(status, 303)
        self.assertTrue(location.startswith("/horloges?melding=Gekocht"), location)
        (trade,) = tr.load_trades(self.db)
        self.assertEqual((trade.market, trade.model), ("sporthorloges", "Garmin Fenix 6 Pro"))
        # The bike computer page is still at / and links to the watches.
        status, _, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Fietscomputers op Marktplaats", page)
        self.assertIn("href='/horloges'", page)

    def test_adding_by_hand_checks_the_model_against_the_market(self):
        _, location, _ = self.request("POST", "/toevoegen", {"token": self.token(), "markt": "sporthorloges",
                                                              "titel": "Edge", "model": "Garmin Edge 530",
                                                              "prijs": "10"})
        self.assertIn("Onbekend model", location)
        _, location, _ = self.request("POST", "/toevoegen", {"token": self.token(), "markt": "sporthorloges",
                                                              "titel": "Fenix van Vinted",
                                                              "model": "Garmin Fenix 6 Pro", "prijs": "120"})
        self.assertIn("Toegevoegd", location)
        (trade,) = tr.load_trades(self.db)
        self.assertEqual(trade.market, "sporthorloges")


if __name__ == "__main__":
    unittest.main()
