"""dashboard.py: één pagina met alle fietscomputers, gebouwd uit koopjes.db."""
import io
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

    def test_a_database_from_before_migration_12_still_loads(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        conn = db.connect(self.db)
        try:
            conn.execute("DROP TABLE listing_mark")
            conn.execute("DELETE FROM schema_version WHERE version = 12")
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

    def request(self, method, path="/", fields=None, host=None, origin=None):
        conn = self.http.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
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

    def test_buying_from_a_flip_row_and_selling_it(self):
        import trades as tr

        status, location, _ = self.request("POST", "/gekocht", {"token": self.token(), "item_id": "c", "prijs": "85"})
        self.assertEqual(status, 303)
        self.assertIn("Gekocht", location)
        (trade,) = tr.load_trades(self.db)
        self.assertEqual((trade.item_id, trade.buy_price_eur, trade.model), ("c", 85.0, "Garmin Edge 530"))
        self.assertIsNotNone(trade.expected_resale_eur)

        _, _, page = self.request("GET")
        self.assertIn("✓ gekocht", page)
        # Bought is no longer a chance: gone from the flips.
        self.assertNotIn("c", {l.item_id for l in dashboard.load_dashboard(self.db).flips})

        self.request("POST", "/verkocht", {"token": self.token(), "id": trade.id, "prijs": "150,50",
                                           "kosten": "3", "datum": "2026-10-01", "via": "vinted"})
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

        _, _, page = self.request("GET")
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
        # Na Gekocht blijft het Mijn flips, ook als er een tab meekomt.
        _, location, _ = self.request("POST", "/gekocht", {"token": self.token(), "item_id": "c", "prijs": "85",
                                                           "tab": "flips"})
        self.assertTrue(location.endswith("#mijn"))

    def test_static_page_has_no_forms(self):
        html = dashboard.render(dashboard.load_dashboard(self.db))
        self.assertNotIn("<form", html)
        self.assertIn("python dashboard.py --serve", html)


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
