"""racebikes.py en /racefietsen in dashboard.py --serve: alle racefietsen,
wegzetten met de fietsredenen, een bod vastleggen, afstand."""
import http.client
import json
import re
import shutil
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from helpers import close_databases_before_cleanup, make_listing, repo_file

import dashboard
import db
import distance as dm
import flips as fl
import marks as mr
import racebikes as rb

BIKE_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/{}-x"
COMPUTER_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/{}-x"


def bike(item_id, price, title="Cube Attain racefiets", **kw):
    kw.setdefault("url", BIKE_URL.format(item_id))
    kw.setdefault("description", "Carbon frame, Shimano 105, velgremmen.")
    kw.setdefault("frame_height", "56 cm")
    kw.setdefault("image_urls", f"https://images.example/{item_id}.jpg")
    return make_listing(item_id=item_id, title=title, price_eur=price, **kw)


class Case(unittest.TestCase):
    # De server opent zijn verbindingen in een eigen thread; die kan de
    # opruimhulp niet sluiten (en de server sluit ze zelf).
    track_connections = True

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        if self.track_connections:
            close_databases_before_cleanup(self)
        self.db = str(self.dir / "koopjes.db")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        market = [bike(f"a{i}", p, city="Zwolle", latitude=52.51, longitude=6.09)
                  for i, p in enumerate((500.0, 550.0, 600.0, 650.0))]
        cheap = bike("c", 300.0, title="Cube racefiets <b>koopje</b>", city="Utrecht", latitude=52.09,
                     longitude=5.12, promotion="DAGTOPPER")
        old = bike("old", 400.0)
        computer = make_listing(item_id="g", title="Garmin Edge 530", price_eur=90.0, url=COMPUTER_URL.format("g"))
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [old], (self.now - timedelta(days=20)).isoformat())
        db.sync_listings(conn, "racefiets", market + [cheap, computer], self.now.isoformat())
        conn.close()


class LoadTest(Case):
    def test_only_active_road_bikes_with_flip_and_value(self):
        base = rb.build_base(self.db, self.dir / "geen_fiets.md")
        ids = {r.listing.item_id for r in base.rows}
        self.assertEqual(ids, {"a0", "a1", "a2", "a3", "c"})  # geen computer, niet de oude
        c = base.row("c")
        self.assertEqual(c.listing.groupset_tier is not None, True)
        self.assertIn("56 cm", c.specs)
        self.assertIsNotNone(c.flip_margin)
        self.assertGreater(c.flip_margin, 0)
        self.assertGreater(c.value_ratio, 1)
        self.assertIn("geen_fiets.md", base.owner_problem)  # zonder eigen fiets geen upgradeoordeel
        self.assertFalse(c.upgrade_ok)

    def test_with_the_real_owner_bike_there_is_an_upgrade_verdict(self):
        base = rb.build_base(self.db, repo_file("mijn_fiets.md"))
        # mijn_fiets.md heeft verkoopprijs_handmatig, dus een budget, ook zonder comps.
        self.assertEqual(base.owner_problem, "")
        self.assertTrue(all(r.upgrade_why for r in base.rows))

    def test_bike_json_and_the_page(self):
        base = rb.build_base(self.db, self.dir / "geen_fiets.md")
        conn = db.connect(self.db)
        db.set_mark(conn, "a0", mr.DISMISSED, reason="geen racefiets", price_eur=500.0)
        db.set_note(conn, "c", "gevraagd of 280 kan")
        dm.save_home(conn, dm.Home("3511AB", 52.0952, 5.1161))
        conn.close()
        fresh = rb.load_fresh(self.db)
        c = rb.bike_json(base.row("c"), fresh)
        self.assertEqual((c["no"], c["promo"], c["m"]), ("gevraagd of 280 kan", "DAGTOPPER", ""))
        self.assertLess(c["km"], 5)
        self.assertEqual(rb.bike_json(base.row("a0"), fresh)["m"], "weg")
        html = rb.render(base, fresh, "tok")
        self.assertIn("Te beoordelen", html)
        self.assertIn("Afstand hemelsbreed vanaf <strong>3511AB</strong>", html)
        # De titel met <b> zit als JSON in een <script>: </ is ontsnapt, dus
        # geen tekst uit een advertentie kan het script afsluiten.
        self.assertIn("<b>koopje<\\/b>", html)
        self.assertNotIn("<b>koopje</b>", html)


class PermanentReasonTest(unittest.TestCase):
    def test_no_road_bike_stays_away_when_the_price_drops(self):
        listing = make_listing(price_eur=100.0)
        for reason, back in (("te hoge vraagprijs", True), ("geen racefiets", False)):
            mark = mr.Mark("m1", mr.DISMISSED, "2026-09-29", reason=reason, price_eur=150.0)
            self.assertEqual(mr.is_dismissed(mark, listing), not back, reason)


class LiveTest(Case):
    track_connections = False

    def setUp(self):
        super().setUp()
        self.httpd = dashboard.make_server(self.db, 0, intake_path=self.dir / "geen_fiets.md")
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, fields=None, live=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if live:
            headers["X-Live"] = "1"
        body = None
        if fields is not None:
            body = urllib.parse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, headers)
        r = conn.getresponse()
        text = r.read().decode()
        conn.close()
        return r.status, urllib.parse.unquote(r.getheader("Location") or ""), text

    def token(self):
        return re.search(r"data-token='([^']+)'", self.request("GET", rb.PATH)[2]).group(1)

    def live(self, path, fields):
        status, _, text = self.request("POST", path, {"token": self.token(), "markt": rb.MARKET_KEY, **fields},
                                       live=True)
        self.assertEqual(status, 200)
        return json.loads(text)

    def test_page_mark_note_and_bid_without_reloading(self):
        status, _, page = self.request("GET", rb.PATH)
        self.assertEqual(status, 200)
        self.assertIn("id='bikes'", page)
        data = self.live("/markeer", {"item_id": "c", "soort": "niet doorverkoopbaar"})
        self.assertIn("Weggezet (niet doorverkoopbaar)", data["message"])
        self.assertEqual((data["bike"]["m"], data["bike"]["mr"]), ("weg", "niet doorverkoopbaar"))
        self.assertEqual(self.live("/markeer", {"item_id": "c", "soort": "geen"})["bike"]["m"], "")
        self.assertEqual(self.live("/notitie", {"item_id": "c", "notitie": "ophalen za"})["bike"]["no"], "ophalen za")

        data = self.live("/bod", {"item_id": "c", "bedrag": "275"})
        self.assertIn("€275", data["message"])
        self.assertEqual(data["bike"]["b"][0]["s"], "open")
        self.assertIn("Niet opgeslagen", self.live("/bod", {"item_id": "c", "bedrag": "-5"})["message"])
        data = self.live("/bod/status", {"item_id": "c", "status": "geaccepteerd"})
        self.assertIn("/flips", data["message"])
        self.assertTrue(data["bike"]["own"])
        (flip,) = fl.load_book(self.db, with_market_check=False).flips
        self.assertEqual((flip.trade.market, flip.trade.buy_price_eur, flip.stage), ("fietsen", 275.0, "gekocht"))

    def test_computer_page_has_the_bid_control_and_tab(self):
        conn = db.connect(self.db)
        market = [make_listing(item_id=f"g{i}", title="Garmin Edge 530", price_eur=p, url=COMPUTER_URL.format(f"g{i}"))
                  for i, p in enumerate((160.0, 180.0, 200.0, 220.0))]
        db.sync_listings(conn, "garmin", market, self.now.isoformat())
        conn.close()
        _, _, page = self.request("GET", "/")
        self.assertIn("ik heb geboden", page)
        self.assertIn("Mijn biedingen", page)
        token = re.search(r"data-token='([^']+)'", page).group(1)
        status, _, text = self.request("POST", "/bod", {"token": token, "item_id": "g", "bedrag": "70"}, live=True)
        data = json.loads(text)
        self.assertIn("biedingen", data["panels"])
        self.assertEqual(data["tabs"]["biedingen"], "Mijn biedingen (1)")
        self.assertIn("jouw bod €70", data["item"]["mine"])

    def test_postcode_sets_the_distances(self):
        with mock.patch.object(dm, "locate_postcode", return_value=dm.Home("3511AB", 52.0952, 5.1161)) as found:
            status, where, _ = self.request("POST", "/afstand", {"token": self.token(), "markt": rb.MARKET_KEY,
                                                                 "item_id": "postcode", "postcode": "3511ab"})
        found.assert_called_once_with("3511ab")
        self.assertEqual(status, 303)
        self.assertTrue(where.startswith(rb.PATH + "?melding=Afstanden gemeten vanaf 3511AB"))
        _, _, page = self.request("GET", "/")
        self.assertIn("id='km-max'", page)
        with mock.patch.object(dm, "locate_postcode", side_effect=dm.LocateError("te weinig")):
            _, where, _ = self.request("POST", "/afstand", {"token": self.token(), "markt": "fietscomputers",
                                                            "item_id": "postcode", "postcode": "9999"})
        self.assertIn("Niet opgeslagen: te weinig", where)
        self.assertTrue(where.startswith("/?melding="))


if __name__ == "__main__":
    unittest.main()
