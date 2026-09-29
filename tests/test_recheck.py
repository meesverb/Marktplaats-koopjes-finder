"""recheck.py: de knop controleer in het live dashboard — één advertentie nu
ophalen bij Marktplaats en vastleggen wat erop staat."""
import contextlib
import io
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import requests
from helpers import FakeResponse, FakeSession, make_listing

import computers as pc
import dashboard
import db
import racefiets_jev as mp
import recheck as rc

CATEGORY_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/{}-x"


def computer(item_id, title, price, **kw):
    kw.setdefault("url", CATEGORY_URL.format(item_id))
    return make_listing(item_id=item_id, title=title, price_eur=price, **kw)


def listing_page(item_id, price_cents, price_type="FIXED", reserved=False, bids_info=None, **extra):
    """Een advertentiepagina zoals Marktplaats hem stuurt: window.__CONFIG__
    met listing.isReserved, priceInfo en (bij bieden) bidsInfo."""
    listing = {"itemId": item_id, "isReserved": reserved,
               "priceInfo": {"priceCents": price_cents, "priceType": price_type}, **extra}
    if bids_info is not None:
        listing["bidsInfo"] = bids_info
    return f"<html><script>window.__CONFIG__ = {json.dumps({'listing': listing})};</script></html>"


def bids(*values, minimum=-1):
    return {"isBiddingEnabled": True, "currentMinimumBid": minimum,
            "bids": [{"id": i, "value": v} for i, v in enumerate(values)]}


class RecheckCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.later = (self.now + timedelta(hours=3)).isoformat()
        patcher = mock.patch.object(rc, "MIN_INTERVAL_S", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sync(self, listings, when=None):
        conn = db.connect(self.db)
        try:
            db.sync_listings(conn, "garmin edge", listings, (when or self.now).isoformat())
        finally:
            conn.close()

    def market(self):
        return [computer(f"a{i}", "Garmin Edge 530", p) for i, p in enumerate((160.0, 180.0, 200.0, 220.0))]

    def row(self, item_id):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT * FROM listing WHERE item_id = ?", (item_id,)).fetchone()
        finally:
            conn.close()

    def check(self, item_id, page):
        session = FakeSession({CATEGORY_URL.format(item_id): page})
        result = rc.recheck_listing(self.db, item_id, session=session, now=self.later)
        self.assertEqual(len(session.requested), 1)  # één verzoek per klik
        return result

    def flip_ids(self):
        return {l.item_id for l in dashboard.load_dashboard(self.db).flips}


class ReservedTest(RecheckCase):
    def test_a_flip_found_reserved_leaves_the_flips(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.assertIn("c", self.flip_ids())

        result = self.check("c", listing_page("c", 9000, reserved=True))

        self.assertNotIn("c", self.flip_ids())
        self.assertEqual(self.row("c")["reserved_at"], self.later)
        self.assertIn("gereserveerd", result.summary())
        self.assertNotIn("nog steeds", result.summary())

    def test_a_reservation_that_was_lifted_is_cleared(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0, reserved=True)])
        self.assertNotIn("c", self.flip_ids())

        result = self.check("c", listing_page("c", 9000))

        self.assertIsNone(self.row("c")["reserved_at"])
        self.assertIn("c", self.flip_ids())
        self.assertIn("niet meer gereserveerd", result.summary())

    def test_a_reservation_keeps_its_first_sighting(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0, reserved=True)])
        result = self.check("c", listing_page("c", 9000, reserved=True))
        self.assertEqual(self.row("c")["reserved_at"], self.now.isoformat())
        self.assertIn("nog steeds gereserveerd", result.summary())


class BidsTest(RecheckCase):
    def suunto(self):
        # Zoals in de zoekresultaten: MIN_BID met de vraagprijs, biedingen
        # onbekend (de ronde voor horloges vraagt MIN_BID niet op).
        return computer("s", "Garmin Edge 530", 90.0, price_type="MIN_BID", price_is_bid=True)

    def test_bids_above_the_asking_price_become_the_price(self):
        self.sync(self.market() + [self.suunto()])
        page = listing_page("s", 9000, "MIN_BID", bids_info=bids(19000, 12000, 10000, minimum=9000))
        self.assertIn("s", self.flip_ids())

        result = self.check("s", page)

        row = self.row("s")
        self.assertEqual((row["price_eur"], row["bid_count"], row["bid_high"], row["bid_minimum"]),
                         (190.0, 3, 190.0, 90.0))
        self.assertEqual(row["bids_checked_at"], self.later)
        summary = result.summary()
        self.assertIn("3 biedingen, hoogste €190, boven de vraagprijs van €90", summary)
        self.assertIn("prijs €90 → €190", summary)
        # Met €190 is het geen flip meer: dat is de mediaan vraagprijs, en
        # daar gaat nog afdingen en verzendkosten af.
        self.assertNotIn("s", self.flip_ids())
        listing = next(l for l in dashboard.load_dashboard(self.db).listings if l.item_id == "s")
        self.assertEqual(pc.price_kind(listing), "huidig bod, loopt nog op")

    def test_a_round_without_lookup_does_not_undo_a_bid_above_the_asking_price(self):
        self.sync(self.market() + [self.suunto()])
        self.check("s", listing_page("s", 9000, "MIN_BID", bids_info=bids(15000, minimum=9000)))
        # Overdag: de zoekresultaten zeggen weer €90, zonder biedopvraging.
        self.sync([self.suunto()], when=self.now + timedelta(hours=4))

        self.assertEqual(self.row("s")["price_eur"], 90.0)  # de database: wat de ronde zag
        listing = next(l for l in dashboard.load_dashboard(self.db).listings if l.item_id == "s")
        self.assertEqual(listing.price_eur, 150.0)  # maar onder het bod is hij niet te krijgen
        self.assertEqual(listing.bid_high, 150.0)
        # Opnieuw controleren: de melding gaat uit van wat het dashboard toonde.
        again = self.check("s", listing_page("s", 9000, "MIN_BID", bids_info=bids(15000, minimum=9000)))
        self.assertNotIn("→", again.summary())

    def test_bids_below_the_asking_price_leave_it_alone(self):
        self.sync(self.market() + [self.suunto()])
        result = self.check("s", listing_page("s", 9000, "MIN_BID", bids_info=bids(8000, minimum=7000)))
        self.assertEqual(self.row("s")["price_eur"], 90.0)
        listing = next(l for l in dashboard.load_dashboard(self.db).listings if l.item_id == "s")
        self.assertEqual(pc.price_kind(listing), "vraagprijs, bieden kan")
        self.assertIn("hoogste €80", dashboard.bid_note(listing))
        self.assertNotIn("boven de vraagprijs", result.summary())

    def test_a_fast_bid_without_bids_gets_its_minimum(self):
        self.sync(self.market() + [computer("f", "Garmin Edge 530", None, price_type="FAST_BID",
                                            price_is_bid=True)])
        result = self.check("f", listing_page("f", 0, "FAST_BID", bids_info=bids(minimum=8000)))
        self.assertEqual((self.row("f")["price_eur"], self.row("f")["bid_count"]), (80.0, 0))
        self.assertIn("nog geen bod", result.summary())

    def test_a_fixed_price_listing_keeps_its_bid_fields(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        result = self.check("c", listing_page("c", 8500))
        row = self.row("c")
        self.assertEqual(row["price_eur"], 85.0)
        self.assertIsNone(row["bid_count"])
        self.assertIsNone(row["bids_checked_at"])
        self.assertIn("prijs €90 → €85", result.summary())


class GoneTest(RecheckCase):
    def test_a_listing_marketplace_answers_410_for_is_marked_gone(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        result = self.check("c", FakeResponse("", status_code=410))
        self.assertTrue(result.gone)
        self.assertIn("staat niet meer op Marktplaats", result.summary())
        row = self.row("c")
        self.assertEqual((row["disappeared_at"], row["checked_at"]), (self.later, self.later))
        self.assertEqual(row["days_online"], 0)
        self.assertNotIn("c", {l.item_id for l in dashboard.load_dashboard(self.db).listings})

    def test_a_listing_that_is_back_online_loses_its_disappeared_mark(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.check("c", FakeResponse("", status_code=410))
        self.check("c", listing_page("c", 9000))
        self.assertIsNone(self.row("c")["disappeared_at"])


class WhatItLeavesAloneTest(RecheckCase):
    def test_last_seen_stays_the_last_crawl(self):
        # Het dashboard dateert "laatste ronde" en "nieuw" op last_seen.
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.check("c", listing_page("c", 9000))
        row = self.row("c")
        self.assertEqual(row["last_seen"], self.now.isoformat())
        self.assertEqual(row["checked_at"], self.later)

    def test_the_price_seen_is_recorded(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.check("c", listing_page("c", 8500))
        conn = sqlite3.connect(self.db)
        try:
            prices = conn.execute("SELECT observed_at, price_eur FROM listing_price WHERE item_id = 'c' "
                                  "ORDER BY observed_at").fetchall()
        finally:
            conn.close()
        self.assertEqual(prices, [(self.now.isoformat(), 90.0), (self.later, 85.0)])


class FailureTest(RecheckCase):
    """Lukt het niet, dan zegt de melding waarom en blijft de database zoals hij was."""

    def setUp(self):
        super().setUp()
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.before = dict(self.row("c"))

    def assertRefused(self, page, *words):
        with self.assertRaises(rc.RecheckError) as caught:
            self.check("c", page)
        for word in words:
            self.assertIn(word, str(caught.exception))
        self.assertEqual(dict(self.row("c")), self.before)

    def test_a_page_without_the_config_is_a_changed_structure(self):
        self.assertRefused("<html>iets anders</html>", "paginastructuur", "niets opgeslagen")

    def test_a_listing_without_is_reserved_is_a_changed_structure(self):
        page = "<html><script>window.__CONFIG__ = " + json.dumps(
            {"listing": {"itemId": "c", "priceInfo": {"priceCents": 9000, "priceType": "FIXED"}}}) + "</script>"
        self.assertRefused(page, "isReserved")

    def test_a_bid_listing_without_bid_data_is_a_changed_structure(self):
        self.assertRefused(listing_page("c", 9000, "MIN_BID"), "biedinformatie")

    def test_a_redirect_to_another_listing(self):
        self.assertRefused(listing_page("m999", 9000), "andere advertentie")

    def test_a_server_error(self):
        self.assertRefused(FakeResponse("", status_code=503), "Kon de advertentie niet ophalen")

    def test_no_connection(self):
        class Offline:
            def get(self, url, timeout=0):
                raise requests.ConnectionError("geen netwerk")

        with self.assertRaises(rc.RecheckError) as caught:
            rc.recheck_listing(self.db, "c", session=Offline(), now=self.later)
        self.assertIn("geen netwerk", str(caught.exception))
        self.assertEqual(dict(self.row("c")), self.before)

    def test_an_unknown_listing(self):
        with self.assertRaises(rc.RecheckError):
            rc.recheck_listing(self.db, "bestaat-niet", session=FakeSession({}), now=self.later)


class PolitenessTest(RecheckCase):
    def test_clicks_in_quick_succession_wait_like_a_round_does(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        waits = []
        with mock.patch.object(rc, "MIN_INTERVAL_S", 1.5), \
                mock.patch.object(rc.time, "sleep", waits.append), \
                mock.patch.object(rc, "_last_request", 0.0):
            self.check("c", listing_page("c", 9000))
            self.check("c", listing_page("c", 9000))
        self.assertEqual(len(waits), 1)  # de eerste hoeft niet te wachten
        self.assertGreater(waits[0], 1.0)

    def test_never_two_requests_at_once(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        busy, overlap = threading.Event(), []

        class Slow(FakeSession):
            def get(self, url, timeout=0):
                if busy.is_set():
                    overlap.append(url)
                busy.set()
                threading.Event().wait(0.05)
                busy.clear()
                return super().get(url, timeout)

        session = Slow({CATEGORY_URL.format("c"): listing_page("c", 9000)})
        threads = [threading.Thread(target=rc.recheck_listing, args=(self.db, "c", session, self.later))
                   for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(overlap, [])
        self.assertEqual(len(session.requested), 3)


class BidHighFromTheCrawlTest(unittest.TestCase):
    """De biedopvraging van een ronde vult bid_high net zo."""

    def test_enrich_sets_the_highest_bid(self):
        listing = make_listing(price_eur=90.0, price_type="MIN_BID", price_is_bid=True)
        session = FakeSession({listing.url: listing_page("m1", 9000, "MIN_BID", bids_info=bids(12000, 10000))})
        with contextlib.redirect_stderr(io.StringIO()):
            mp.enrich_bid_listings([listing], delay=0, mode="all", session=session)
        self.assertEqual((listing.price_eur, listing.bid_high, listing.bid_count), (120.0, 120.0, 2))

    def test_sync_keeps_it_until_the_next_lookup(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        path = str(directory / "koopjes.db")
        looked_up = make_listing(price_eur=120.0, price_type="MIN_BID", price_is_bid=True, bid_count=2, bid_high=120.0)
        plain = make_listing(price_eur=90.0, price_type="MIN_BID", price_is_bid=True)
        conn = db.connect(path)
        try:
            db.sync_listings(conn, "q", [looked_up], "2026-09-29T03:00:00+00:00")
            db.sync_listings(conn, "q", [plain], "2026-09-29T10:00:00+00:00")
            row = conn.execute("SELECT price_eur, bid_high, bid_count FROM listing").fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(row), (90.0, 120.0, 2))


class OlderDatabaseTest(RecheckCase):
    def test_a_database_from_before_migration_14_still_loads(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        conn = db.connect(self.db)
        try:
            conn.execute("ALTER TABLE listing DROP COLUMN bid_high")
            conn.execute("ALTER TABLE listing DROP COLUMN checked_at")
            conn.execute("DELETE FROM schema_version WHERE version >= 14")
            conn.commit()
        finally:
            conn.close()
        d = dashboard.load_dashboard(self.db)  # alleen-lezen: migreert niet
        self.assertIn("c", {l.item_id for l in d.flips})


class DashboardButtonTest(RecheckCase):
    def test_only_the_live_page_has_the_button(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        d = dashboard.load_dashboard(self.db)
        self.assertNotIn("data-action='/controleer'", dashboard.render(d))
        d.editable, d.token = True, "geheim"
        self.assertIn("data-action='/controleer'", dashboard.render(d))

    def test_the_live_page_says_when_it_was_checked(self):
        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        self.check("c", listing_page("c", 9000))
        d = dashboard.load_dashboard(self.db)
        d.editable, d.token = True, "geheim"
        self.assertIn(f"gecontroleerd {dashboard.local_time(self.later)}", dashboard.render(d))

    def test_the_live_server_checks_and_comes_back_on_the_tab(self):
        import http.client
        import re
        import urllib.parse

        self.sync(self.market() + [computer("c", "Garmin Edge 530", 90.0)])
        httpd = dashboard.make_server(self.db, 0)
        port = httpd.server_address[1]
        threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

        def request(method, fields=None, path="/"):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            body = urllib.parse.urlencode(fields) if fields is not None else None
            headers = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/x-www-form-urlencoded"}
            conn.request(method, path, body, headers)
            response = conn.getresponse()
            text = response.read().decode()
            conn.close()
            return response.status, urllib.parse.unquote(response.getheader("Location") or ""), text

        page = request("GET")[2]
        token = re.search(r"name='token' value='([^']+)'", page).group(1)
        session = FakeSession({CATEGORY_URL.format("c"): listing_page("c", 9000, reserved=True)})
        with mock.patch.object(rc, "make_session", lambda: session):
            status, location, _ = request("POST", {"token": token, "markt": "fietscomputers", "item_id": "c",
                                                   "tab": "flips"}, path="/controleer")
            self.assertEqual(status, 303)
            self.assertTrue(location.endswith("#flips"))
            self.assertIn("gereserveerd", location)
            self.assertNotIn("c", self.flip_ids())

            # Zonder geheim: niets opgehaald.
            request("POST", {"markt": "fietscomputers", "item_id": "c"}, path="/controleer")
        self.assertEqual(len(session.requested), 1)


if __name__ == "__main__":
    unittest.main()
