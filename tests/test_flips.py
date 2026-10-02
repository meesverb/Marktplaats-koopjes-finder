"""flips.py, de pagina /flips in dashboard.py en de Sheet-koppeling
(flips_sheets.py): wat een flip kost, wat hij oplevert, en dat afvinken,
prijzen en de Sheet elkaar niet in de weg zitten."""
import http.client
import json
import re
import shutil
import tempfile
import threading
import unittest
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dashboard
import db
import flips as fl
import flips_sheets as fs

HERE = Path(__file__).resolve().parent.parent
CUBE = HERE / "flips_import" / "cube_peloton_pro.json"


class FlipTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")
        self.conn = db.connect(self.db)
        self.addCleanup(self.conn.close)

    def bike(self, **kw):
        values = dict(title="Cube", market="fietsen", bought_at="2026-09-01", buy_price_eur=70.0,
                      target_low_eur=400.0, target_high_eur=450.0)
        values.update(kw)
        return fl.create_flip(self.conn, **values)


class CostTest(FlipTest):
    def test_spent_planned_and_expected_profit(self):
        t = self.bike()
        fl.add_task(self.conn, t, kind="reis", title="OV heen", fare_eur=10.0, discount="40")
        fl.add_task(self.conn, t, kind="reis", title="OV terug", fare_eur=10.0, discount="gratis")
        cassette = fl.add_task(self.conn, t, kind="onderdeel", title="Cassette", est_eur=29.95)
        fl.add_task(self.conn, t, kind="onderdeel", title="Banden", est_eur=40.0)
        fl.add_task(self.conn, t, kind="klus", title="Poetsen")
        fl.add_task(self.conn, t, kind="onderdeel", title="Kettingpons", est_eur=3.0, investment=True)
        f = fl.load_book(self.db).get(t)
        self.assertEqual(f.spent_eur, 76.0)  # 70 + 6 (40% korting) + 0 (gratis)
        self.assertEqual(f.planned_eur, 69.95)  # het gereedschap telt niet mee
        self.assertEqual(f.expected_profit(400.0), 254.05)
        # De echte prijs vervangt de schatting en zet hem op gekocht.
        fl.update_task(self.conn, cassette, price_eur=27.5)
        f = fl.load_book(self.db).get(t)
        self.assertEqual((f.spent_eur, f.planned_eur), (103.5, 40.0))
        task = next(k for k in f.tasks if k.id == cassette)
        self.assertEqual((task.status, task.bought_at), ("gekocht", date.today().isoformat()))

    def test_after_the_sale_only_what_was_really_spent_counts(self):
        t = self.bike()
        fl.add_task(self.conn, t, kind="onderdeel", title="Cassette", price_eur=30.0)
        fl.add_task(self.conn, t, kind="onderdeel", title="Nooit gekocht", est_eur=50.0)
        fl.sell(self.conn, t, sold_at="2026-09-20", price_eur=420.0, costs_eur=5.0, via="marktplaats")
        book = fl.load_book(self.db)
        f = book.get(t)
        self.assertEqual((f.stage, f.profit_eur, f.planned_eur), ("verkocht", 315.0, 0.0))
        self.assertEqual((book.totals.realized_eur, book.totals.sold), (315.0, 1))

    def test_investments_lower_the_net_result_not_a_flip(self):
        t = self.bike()
        fl.sell(self.conn, t, sold_at="2026-09-20", price_eur=100.0)
        fl.add_task(self.conn, None, kind="onderdeel", title="Cassettesleutel", price_eur=12.0, investment=True)
        fl.add_task(self.conn, None, kind="onderdeel", title="Pons", est_eur=3.0, investment=True)
        tot = fl.load_book(self.db).totals
        self.assertEqual((tot.realized_eur, tot.tools_spent_eur, tot.tools_planned_eur, tot.net_eur),
                         (30.0, 12.0, 3.0, 18.0))

    def test_stock_is_not_a_running_flip_until_it_is_put_up_for_sale(self):
        self.bike()
        wheels = self.bike(title="Wielen", market="spullen", buy_price_eur=0.0, stage="voorraad",
                           target_low_eur=None, target_high_eur=None)
        self.assertEqual(fl.load_book(self.db).totals.stock, 1)
        fl.set_stage(self.conn, wheels, "te_koop")
        book = fl.load_book(self.db)
        self.assertEqual((book.get(wheels).stage, book.get(wheels).days_in_stage, book.totals.stock),
                         ("te_koop", 0, 2))

    def test_days_in_stage_count_from_when_the_stage_began(self):
        t = self.bike(bought_at=(date.today() - timedelta(days=9)).isoformat())
        self.assertEqual(fl.load_book(self.db).get(t).days_in_stage, 9)

    def test_a_computer_bought_off_the_dashboard_is_a_flip_too(self):
        db.add_trade(self.conn, title="Edge 530", bought_at="2026-09-01", buy_price_eur=100.0,
                     expected_resale_eur=150.0, market="fietscomputers")
        (f,) = fl.load_book(self.db).flips
        self.assertEqual((f.stage, f.kind_label, f.target, f.expected_profit(150.0)),
                         ("te_koop", "fietscomputer", (150.0, 150.0), 50.0))

    def test_basket_warns_below_free_shipping(self):
        t = self.bike()
        fl.add_task(self.conn, t, kind="onderdeel", title="Cassette", shop="FuturumShop", est_eur=29.95)
        fl.add_task(self.conn, t, kind="onderdeel", title="Stuurlint", shop="AliExpress", est_eur=12.0)
        fl.add_task(self.conn, t, kind="onderdeel", title="Gekocht", shop="FuturumShop", price_eur=5.0)
        groups = {shop: (sub, short) for shop, _, sub, short in fl.basket(fl.load_book(self.db).get(t).tasks)}
        self.assertEqual(groups, {"FuturumShop": (29.95, 19.05), "AliExpress": (12.0, None)})

    def test_bad_values_are_refused(self):
        t = self.bike()
        with self.assertRaises(ValueError):
            fl.add_task(self.conn, t, kind="iets", title="x")
        with self.assertRaises(ValueError):
            fl.add_task(self.conn, t, kind="reis", title="x", discount="50")
        with self.assertRaises(ValueError):
            fl.update_task(self.conn, 1, bestaat_niet=1)
        self.assertFalse(fl.set_stage(self.conn, t, "verkocht"))

    def test_ad_draft_uses_only_what_the_owner_entered(self):
        t = self.bike(specs={"merk": "Cube Peloton Pro", "maat": "62", "groep": "Shimano 105"})
        k = fl.add_task(self.conn, t, kind="onderdeel", title="Cassette 11-32", price_eur=30.0)
        fl.add_task(self.conn, t, kind="onderdeel", title="Nog niet erop", est_eur=5.0)
        fl.update_task(self.conn, k, done_at="2026-09-02")
        text = fl.ad_draft(fl.load_book(self.db).get(t))
        self.assertIn("Te koop: Cube Peloton Pro, maat 62.", text)
        self.assertIn("Groep: Shimano 105", text)
        self.assertIn("Onlangs vervangen: Cassette 11-32.", text)
        self.assertNotIn("Nog niet erop", text)

    def test_market_check_uses_asking_prices_with_all_words(self):
        now = datetime.now(timezone.utc).isoformat()
        rows = [("a", "Cube Peloton racefiets", 300.0, 0), ("b", "cube peloton 58", 500.0, 0),
                ("c", "Cube Peloton", 50.0, 1), ("d", "Cube Attain", 400.0, 0), ("e", "CUBE PELOTON", 400.0, 0)]
        for item, title, price, bid in rows:
            self.conn.execute("INSERT INTO listing (item_id, title, price_eur, is_bid, last_seen) VALUES (?,?,?,?,?)",
                              (item, title, price, bid, now))
        self.conn.commit()
        mc = fl.market_check(self.db, "cube peloton", exclude={"e"})
        self.assertEqual((mc.n, mc.median_eur), (2, 400.0))


class ImportTest(FlipTest):
    def test_the_cube_list_imports_once(self):
        lines = fl.import_file(self.conn, CUBE)
        self.assertIn("ingelezen: Cube Peloton Pro, maat 62 (22 klussen)", lines)
        again = fl.import_file(self.conn, CUBE)
        self.assertTrue(all(l.startswith("overgeslagen") for l in again))
        book = fl.load_book(self.db)
        cube = next(f for f in book.flips if f.trade.title.startswith("Cube"))
        self.assertEqual((cube.trade.buy_price_eur, cube.spent_eur), (70.0, 92.92))  # + 2x OV 11,46
        self.assertEqual(cube.target, (400.0, 450.0))
        self.assertEqual(len(book.by_stage("voorraad")), 4)
        self.assertEqual(len([k for k in book.tools if k.trade_id is None]), 15)
        # Geschrapt omdat hij het al heeft.
        titles = {k.title for k in cube.tasks}
        self.assertFalse({t for t in titles if "Squirt" in t or "Kettingpons" in t})


    def test_a_better_offer_updates_the_existing_lines(self):
        fl.import_file(self.conn, CUBE)
        before = next(f for f in fl.load_book(self.db).flips if f.trade.title.startswith("Cube")).planned_eur
        lines = fl.update_file(self.conn, HERE / "flips_import" / "cube_bike24.json")
        self.assertEqual(sum(l.startswith("bijgewerkt") for l in lines), 5)
        cube = next(f for f in fl.load_book(self.db).flips if f.trade.title.startswith("Cube"))
        chain = next(k for k in cube.tasks if k.title == "Ketting KMC X10")
        self.assertEqual((chain.shop, chain.url, chain.est_eur, chain.price_source),
                         ("Bike24", "https://www.bike24.nl/producten/7753", 17.28, "gecontroleerd"))
        self.assertEqual(round(before - cube.planned_eur, 2), 21.56)

    def test_updating_leaves_what_was_bought_and_reports_what_it_cannot_find(self):
        t = self.bike()
        k = fl.add_task(self.conn, t, kind="onderdeel", title="Cassette", est_eur=30.0)
        fl.update_task(self.conn, k, price_eur=28.0)
        path = self.dir / "aanbod.json"
        path.write_text(json.dumps({"flips": [
            {"flip": "Cube", "klussen": [{"titel": "Cassette", "winkel": "X", "geschat": 20},
                                         {"titel": "Bestaat niet", "geschat": 1}]},
            {"flip": "Andere fiets", "klussen": []}]}), encoding="utf-8")
        lines = fl.update_file(self.conn, path)
        self.assertEqual(lines, ["al gekocht, niet bijgewerkt: Cassette", "niet gevonden in Cube: 'Bestaat niet'",
                                 "flip niet gevonden: 'Andere fiets'"])
        self.assertEqual(fl.load_book(self.db).get(t).tasks[0].est_eur, 30.0)


class OfferTest(FlipTest):
    """Aanbiedingen bij een onderdeel (flip_offer, migratie 21): een link
    plakken met de prijs die je zag, en er een kiezen."""

    def setUp(self):
        super().setUp()
        self.trade = self.bike()
        self.task = fl.add_task(self.conn, self.trade, kind="onderdeel", title="Ketting KMC X10", est_eur=13.0,
                                shop="AliExpress", price_source="schatting")

    def test_add_choose_and_remove(self):
        cheap = fl.add_offer(self.conn, self.task, url="https://www.bike24.nl/p/7753?utm_source=x", price_eur=17.28,
                             shipping_eur=4.95)
        dear = fl.add_offer(self.conn, self.task, url="https://www.futurumshop.nl/kmc-x10", price_eur=24.95)
        (k,) = fl.load_book(self.db).get(self.trade).tasks
        self.assertEqual([o.id for o in k.offers], [cheap, dear])  # goedkoopste (met verzending) eerst
        self.assertEqual((k.offers[0].shop, k.offers[0].url, k.offers[0].total_eur),
                         ("Bike24", "https://www.bike24.nl/p/7753", 22.23))
        fl.choose_offer(self.conn, cheap)
        (k,) = fl.load_book(self.db).get(self.trade).tasks
        self.assertEqual((k.shop, k.url, k.est_eur, k.price_source),
                         ("Bike24", "https://www.bike24.nl/p/7753", 22.23, "gecontroleerd"))
        self.assertIsNone(k.price_eur)  # gekozen is nog niet gekocht
        fl.delete_offer(self.conn, dear)
        self.assertEqual(len(fl.load_book(self.db).get(self.trade).tasks[0].offers), 1)
        self.assertIsNone(fl.delete_offer(self.conn, dear))

    def test_links(self):
        with self.assertRaisesRegex(ValueError, "http"):
            fl.add_offer(self.conn, self.task, url="bike24.nl/p/1", price_eur=10.0)
        with self.assertRaisesRegex(ValueError, "notitie"):
            fl.add_offer(self.conn, self.task, url="", price_eur=10.0)
        self.assertEqual(fl.clean_url("https://nl.aliexpress.com/item/1005001234567890.html?spm=a2g0&algo_pvid=b"),
                         "https://www.aliexpress.com/item/1005001234567890.html")
        self.assertEqual(fl.clean_url("https://a.aliexpress.com/_mKxyz"), "https://a.aliexpress.com/_mKxyz")
        self.assertEqual(fl.clean_url("https://shop.example/p?id=7&gclid=1&_gl=2*x&utm_medium=y"),
                         "https://shop.example/p?id=7")
        # Zonder link mag het, met een notitie: AliExpress uit de app.
        offer = fl.add_offer(self.conn, self.task, price_eur=12.5, shop="AliExpress",
                             note="KMC Official Store, zoek 'KMC X10'", source="schatting")
        fl.choose_offer(self.conn, offer)
        (k,) = fl.load_book(self.db).get(self.trade).tasks
        self.assertEqual((k.url, k.est_eur, k.price_source), ("", 12.5, "schatting"))

    def test_read_from_a_file_once(self):
        path = self.dir / "aanbod.json"
        path.write_text(json.dumps({"flips": [{"flip": "Cube", "klussen": [{"titel": "Ketting KMC X10", "aanbiedingen": [
            {"url": "https://www.bike24.nl/p/7753", "prijs": 17.28, "verzending": 4.95, "bekeken": "2026-10-02"},
            {"winkel": "AliExpress", "prijs": 12.5, "notitie": "KMC Official Store", "bron": "schatting"}]}]}]}),
            encoding="utf-8")
        self.assertEqual(fl.update_file(self.conn, path), ["2 aanbiedingen bij: Ketting KMC X10"])
        self.assertEqual(fl.update_file(self.conn, path), ["0 aanbiedingen bij: Ketting KMC X10"])
        (k,) = fl.load_book(self.db).get(self.trade).tasks
        self.assertEqual((k.est_eur, len(k.offers), k.offers[1].checked_at), (13.0, 2, "2026-10-02"))

    def test_the_cube_research_reads_onto_the_cube_list(self):
        conn = db.connect(self.db)
        try:
            fl.import_file(conn, CUBE)
            lines = fl.update_file(conn, HERE / "flips_import" / "cube_aanbiedingen.json")
        finally:
            conn.close()
        self.assertFalse([l for l in lines if "niet gevonden" in l])
        self.assertTrue(all("aanbieding" in l for l in lines), lines)
        cube = next(f for f in fl.load_book(self.db).flips if f.trade.title.startswith("Cube Peloton"))
        chain = next(k for k in cube.tasks if k.title == "Ketting KMC X10")
        self.assertEqual(chain.offers[0].shop, "bike-components")  # goedkoopste eerst
        self.assertTrue(all(o.checked_at == "2026-10-02" and o.url.startswith("https://") for o in chain.offers))

    def test_a_database_from_before_migration_21(self):
        self.conn.execute("DROP TABLE flip_offer")
        self.conn.execute("DELETE FROM schema_version WHERE version >= 21")
        self.conn.commit()
        self.assertEqual(fl.load_book(self.db).get(self.trade).tasks[0].offers, [])
        db.connect(self.db).close()  # migreert weer
        fl.add_offer(self.conn, self.task, url="https://x.nl/a", price_eur=1.0)
        self.assertEqual(len(fl.load_book(self.db).get(self.trade).tasks[0].offers), 1)


class ServeTest(FlipTest):
    def setUp(self):
        super().setUp()
        self.trade = self.bike()
        self.task = fl.add_task(self.conn, self.trade, kind="onderdeel", title="Cassette", est_eur=29.95)
        self.httpd = dashboard.make_server(self.db, 0, photo_dir=self.dir / "fotos",
                                           sheets_config=self.dir / "sheets.json")
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        if isinstance(body, dict):
            body = urllib.parse.urlencode(body)
            h["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, urllib.parse.unquote(r.getheader("Location") or ""), data

    def token(self):
        _, _, page = self.request("GET", "/flips")
        return re.search(r"data-token='([^']+)'", page.decode()).group(1)

    def test_the_page_shows_the_flip_and_its_list(self):
        status, _, page = self.request("GET", "/flips")
        page = page.decode()
        self.assertEqual(status, 200)
        self.assertIn("Cube", page)
        self.assertIn("Cassette", page)
        self.assertIn("€29,95", page)

    def test_only_web_links_become_a_link(self):
        # Links vult de eigenaar zelf in, ook via de Google Sheet: een
        # "javascript:"-link zou code worden op een pagina met het token.
        fl.update_task(self.conn, self.task, url="javascript:alert(1)")
        fl.update_flip(self.conn, self.trade, sale_url="JavaScript:alert(2)")
        self.conn.execute("UPDATE trade SET url = 'javascript:alert(3)' WHERE id = ?", (self.trade,))
        self.conn.commit()
        _, _, page = self.request("GET", "/flips")
        self.assertNotIn("href='javascript", page.decode().lower())
        fl.update_task(self.conn, self.task, url="https://www.futurumshop.nl/cassette")
        _, _, page = self.request("GET", "/flips")
        self.assertIn("href='https://www.futurumshop.nl/cassette'", page.decode())
        self.assertEqual(dashboard.web_link(" https://x.nl"), "")
        self.assertEqual(dashboard.web_link("HTTP://x.nl"), "HTTP://x.nl")

    def test_a_price_and_a_tick_without_reloading(self):
        token = self.token()
        status, _, data = self.request("POST", "/flips/klus", {"token": token, "item_id": self.task, "doe": "prijs",
                                                               "prijs": "27,50"}, {"X-Live": "1"})
        data = json.loads(data)
        self.assertEqual((status, data["flip"]), (200, self.trade))
        self.assertIn("€27,50", data["card"])
        self.request("POST", "/flips/klus", {"token": token, "item_id": self.task, "doe": "gedaan"}, {"X-Live": "1"})
        (k,) = fl.load_book(self.db).get(self.trade).tasks
        self.assertEqual((k.price_eur, k.done), (27.5, True))

    def test_offers_on_the_page_without_reloading(self):
        token = self.token()
        status, _, data = self.request("POST", "/flips/aanbod", {
            "token": token, "item_id": self.task, "link": "https://www.bike-components.de/nl/p/1?gclid=x",
            "prijs": "24,95", "verzending": "3,95"}, {"X-Live": "1"})
        data = json.loads(data)
        self.assertEqual((status, data["flip"]), (200, self.trade))
        self.assertIn("Aanbiedingen (1)", data["card"])
        self.assertIn("https://www.bike-components.de/nl/p/1'", data["card"])
        (offer,) = fl.load_book(self.db).get(self.trade).tasks[0].offers
        data = json.loads(self.request("POST", "/flips/aanbod-kies", {"token": token, "item_id": offer.id},
                                       {"X-Live": "1"})[2])
        self.assertIn("geplande kosten", data["message"])
        self.assertIn("€28,90", data["card"])  # de nieuwe geschatte prijs: 24,95 + 3,95
        self.assertIn("gekozen", data["card"])
        data = json.loads(self.request("POST", "/flips/aanbod", {"token": token, "item_id": self.task,
                                                                 "link": "geen link", "prijs": "5"},
                                       {"X-Live": "1"})[2])
        self.assertIn("Niet opgeslagen", data["message"])
        data = json.loads(self.request("POST", "/flips/klus", {"token": token, "item_id": self.task, "doe": "winkel",
                                                               "winkel": "", "url": "https://www.futurumshop.nl/a?_gl=1"},
                                       {"X-Live": "1"})[2])
        (k,) = fl.load_book(self.db).get(self.trade).tasks
        self.assertEqual((k.shop, k.url), ("FuturumShop", "https://www.futurumshop.nl/a"))
        data = json.loads(self.request("POST", "/flips/aanbod-weg", {"token": token, "item_id": offer.id},
                                       {"X-Live": "1"})[2])
        self.assertIn("Aanbiedingen (0)", data["card"])

    def test_stage_and_sale_reload_the_page(self):
        token = self.token()
        status, where, _ = self.request("POST", "/flips/fase", {"token": token, "item_id": self.trade,
                                                                "fase": "te_koop"}, {"X-Live": "1"})
        self.assertEqual((status, where), (303, f"/flips?melding=Naar te koop.#flip-{self.trade}"))
        self.request("POST", "/flips/verkocht", {"token": token, "item_id": self.trade, "prijs": "430",
                                                 "datum": "2026-09-10", "via": "marktplaats"})
        self.assertEqual(fl.load_book(self.db).get(self.trade).stage, "verkocht")

    def test_no_token_no_write(self):
        status, _, data = self.request("POST", "/flips/klus", {"token": "fout", "item_id": self.task,
                                                               "doe": "gedaan"}, {"X-Live": "1"})
        self.assertTrue(json.loads(data)["reload"])
        self.assertFalse(fl.load_book(self.db).get(self.trade).tasks[0].done)

    def test_a_photo_is_stored_and_served_but_only_by_id(self):
        token = self.token()
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 50
        status, _, data = self.request("POST", f"/flips/foto?flip={self.trade}&soort=na", png,
                                       {"X-Token": token, "Content-Type": "image/png"})
        self.assertEqual(json.loads(data)["message"], "Foto opgeslagen.")
        (photo,) = fl.load_book(self.db).get(self.trade).photos
        status, _, body = self.request("GET", f"/flips/foto/{photo['id']}")
        self.assertEqual((status, body), (200, png))
        self.assertEqual(self.request("GET", "/flips/foto/..%2F..%2Fkoopjes.db")[0], 404)
        _, _, data = self.request("POST", f"/flips/foto?flip={self.trade}", b"x",
                                  {"X-Token": "fout", "Content-Type": "image/png"})
        self.assertTrue(json.loads(data)["reload"])
        _, _, data = self.request("POST", f"/flips/foto?flip={self.trade}", b"x",
                                  {"X-Token": token, "Content-Type": "text/html"})
        self.assertIn("Niet opgeslagen", json.loads(data)["message"])

    def test_a_bike_is_not_a_bike_computer_in_mijn_flips(self):
        d = dashboard.load_dashboard(self.db)
        self.assertEqual(d.progress.stock, [])

    def test_a_new_flip_from_a_marktplaats_link_drops_the_tracking(self):
        token = self.token()
        self.request("POST", "/flips/nieuw", {"token": token, "titel": "Giant", "markt": "fietsen", "prijs": "90",
                                              "url": "https://www.marktplaats.nl/v/x/m123456789-giant?_gl=abc"})
        f = next(f for f in fl.load_book(self.db).flips if f.trade.title == "Giant")
        self.assertEqual((f.trade.url, f.trade.item_id), ("https://www.marktplaats.nl/v/x/m123456789-giant",
                                                          "m123456789"))


class FakeSheet:
    """De Apps Script-webapp: onthoudt wat er gepusht is, en geeft bij pull
    terug wat er in `sheets` staat (dat de test kan wijzigen)."""

    def __init__(self):
        self.sheets = {}
        self.calls = []

    def post(self, url, data, headers, timeout):
        body = json.loads(data)
        self.calls.append(body["action"])
        sheet = self

        class Response:
            status_code = 200

            def json(self):
                if body["secret"] != "geheim":
                    return {"ok": False, "error": "verkeerde sleutel"}
                if body["action"] == "pull":
                    return {"ok": True, "sheets": {name: [dict(zip(s["headers"], r)) for r in s["rows"]]
                                                   for name, s in sheet.sheets.items()}}
                sheet.sheets = json.loads(json.dumps(body["sheets"]))
                return {"ok": True}
        return Response()

    def rows(self, name):
        s = self.sheets[name]
        return [dict(zip(s["headers"], r)) for r in s["rows"]]

    def edit(self, name, ident, when, **values):
        s = self.sheets[name]
        for r in s["rows"]:
            if r[0] == ident:
                for k, v in values.items():
                    r[s["headers"].index(k)] = v
                r[s["headers"].index("bijgewerkt")] = when


class SheetsTest(FlipTest):
    def setUp(self):
        super().setUp()
        self.config = self.dir / "sheets.json"
        self.config.write_text(json.dumps({"url": "https://x/exec", "secret": "geheim"}))
        self.sheet = FakeSheet()
        self.trade = self.bike()
        self.task = fl.add_task(self.conn, self.trade, kind="onderdeel", title="Cassette", est_eur=29.95)
        fs.sync(self.db, self.config, self.sheet)

    def later(self, minutes=1):
        return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()

    def test_first_round_writes_every_tab(self):
        self.assertEqual(self.sheet.calls, ["pull", "push"])
        self.assertEqual(set(self.sheet.sheets), {"Flips", "Klussen", "Investeringen", "Totalen", "Aanbiedingen"})
        (row,) = self.sheet.rows("Klussen")
        self.assertEqual((row["titel"], row["geschat"], row["flip_naam"]), ("Cassette", 29.95, "Cube"))

    def test_offers_go_to_a_read_only_tab(self):
        fl.add_offer(self.conn, self.task, url="https://www.bike24.nl/p/7753", price_eur=17.28, shipping_eur=4.95)
        fs.sync(self.db, self.config, self.sheet)
        (row,) = self.sheet.rows("Aanbiedingen")
        self.assertEqual((row["regel"], row["winkel"], row["totaal"], row["link"]),
                         ("Cassette", "Bike24", 22.23, "https://www.bike24.nl/p/7753"))

    def test_an_edit_in_the_sheet_comes_over(self):
        self.sheet.edit("Klussen", self.task, self.later(), prijs="27,50", gedaan="ja")
        self.sheet.edit("Flips", self.trade, self.later(), uren=3, fase="te_koop")
        result = fs.sync(self.db, self.config, self.sheet)
        f = fl.load_book(self.db).get(self.trade)
        self.assertEqual((f.tasks[0].price_eur, f.tasks[0].done, f.hours, f.stage), (27.5, True, 3.0, "te_koop"))
        self.assertIn("overgenomen", result.summary())

    def test_last_change_wins_and_says_what_it_overwrote(self):
        self.sheet.edit("Klussen", self.task, (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
                        prijs=20)
        fl.update_task(self.conn, self.task, price_eur=25.0,
                       updated_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
        result = fs.sync(self.db, self.config, self.sheet)
        self.assertEqual(fl.load_book(self.db).get(self.trade).tasks[0].price_eur, 25.0)
        self.assertIn("pagina was later", result.summary())
        self.assertEqual(self.sheet.rows("Klussen")[0]["prijs"], 25.0)

    def test_new_rows_and_deleted_rows(self):
        klus = self.sheet.sheets["Klussen"]
        klus["rows"].append([None if h not in ("flip", "titel", "soort", "geschat") else
                             {"flip": self.trade, "titel": "Stuurlint", "soort": "onderdeel", "geschat": 5}[h]
                             for h in klus["headers"]])
        self.sheet.sheets["Investeringen"]["rows"].append(
            [{"titel": "Pons", "prijs": 3}.get(h) for h in self.sheet.sheets["Investeringen"]["headers"]])
        fs.sync(self.db, self.config, self.sheet)
        book = fl.load_book(self.db)
        self.assertEqual({k.title for k in book.get(self.trade).tasks}, {"Cassette", "Stuurlint"})
        self.assertEqual([(k.title, k.cost_eur) for k in book.tools], [("Pons", 3.0)])
        # Nu de cassette uit de Sheet halen.
        klus = self.sheet.sheets["Klussen"]
        klus["rows"] = [r for r in klus["rows"] if r[0] != self.task]
        fs.sync(self.db, self.config, self.sheet)
        self.assertEqual({k.title for k in fl.load_book(self.db).get(self.trade).tasks}, {"Stuurlint"})

    def test_an_old_edit_is_not_taken_again(self):
        # Een waarde in de Sheet zonder nieuwe bijgewerkt: de pagina wint (dat is de push van vorige keer).
        fl.update_task(self.conn, self.task, price_eur=25.0)
        fs.sync(self.db, self.config, self.sheet)
        self.assertEqual(fl.load_book(self.db).get(self.trade).tasks[0].price_eur, 25.0)

    def test_wrong_secret_or_no_config_is_a_clear_error(self):
        self.config.write_text(json.dumps({"url": "https://x/exec", "secret": "fout"}))
        with self.assertRaisesRegex(fs.SheetError, "verkeerde sleutel"):
            fs.sync(self.db, self.config, self.sheet)
        with self.assertRaisesRegex(fs.SheetError, "sheets.json ontbreekt"):
            fs.sync(self.db, self.dir / "geen.json", self.sheet)


if __name__ == "__main__":
    unittest.main()


class StartTest(unittest.TestCase):
    """/start en /bestanden: één adres voor alles, en alleen de bestanden
    die de rondes voor de eigenaar schrijven."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")
        db.connect(self.db).close()
        (self.dir / "overzicht.html").write_text("<html><body><h1>Overzicht</h1>"
                                                 "<a href='racefiets_report_giant-defy.html'>r</a></body></html>")
        (self.dir / "racefiets_report_giant-defy.html").write_text("<html><body>Rapport</body></html>")
        (self.dir / "lijsten").mkdir()
        (self.dir / "lijsten" / "beste_koopjes.txt").write_text("1. Giant")
        (self.dir / "sheets.json").write_text('{"secret": "geheim"}')
        (self.dir / "logs").mkdir()
        (self.dir / "logs" / "rondes.jsonl").write_text(json.dumps(
            {"slot": "nacht", "started_at": "2026-09-29T01:00:00+00:00", "finished_at": "2026-09-29T02:00:00+00:00",
             "status": "ok", "new": 7}) + "\n")
        self.httpd = dashboard.make_server(self.db, 0, files_dir=self.dir, photo_dir=self.dir / "fotos",
                                           sheets_config=self.dir / "sheets.json")
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
        r = conn.getresponse()
        body = r.read().decode("utf-8", errors="replace")
        conn.close()
        return r.status, r.getheader("Location"), body

    def test_the_start_page_links_everything(self):
        status, _, page = self.get("/start")
        self.assertEqual(status, 200)
        for href in ("/", "/horloges", "/fiets", "/flips", "/bestanden/overzicht.html",
                     "/bestanden/racefiets_report_giant-defy.html", "/bestanden/lijsten/beste_koopjes.txt"):
            self.assertIn(f"href='{href}'", page)
        self.assertIn("nacht — ok, 7 nieuw", page)

    def test_every_live_page_has_the_bar(self):
        for path in ("/", "/horloges", "/fiets", "/flips"):
            _, _, page = self.get(path)
            self.assertIn("<nav class='site'>", page, path)
            self.assertIn("href='/start'", page, path)

    def test_files_are_served_with_the_bar_and_relative_links_still_work(self):
        status, _, page = self.get("/bestanden/overzicht.html")
        self.assertEqual(status, 200)
        self.assertIn("href='/start'", page)
        self.assertIn("href='racefiets_report_giant-defy.html'", page)  # -> /bestanden/racefiets_report_...
        self.assertEqual(self.get("/bestanden/racefiets_report_giant-defy.html")[0], 200)
        self.assertEqual(self.get("/bestanden/lijsten/beste_koopjes.txt")[2], "1. Giant")

    def test_the_written_dashboards_go_to_the_live_ones(self):
        self.assertEqual(self.get("/bestanden/dashboard.html")[:2], (302, "/"))
        self.assertEqual(self.get("/bestanden/dashboard_horloges.html")[:2], (302, "/horloges"))

    def test_nothing_else_is_served(self):
        for path in ("/bestanden/koopjes.db", "/bestanden/sheets.json", "/bestanden/../koopjes.db",
                     "/bestanden/..%2Fkoopjes.db", "/bestanden/lijsten/../sheets.json", "/bestanden/dashboard.py",
                     "/bestanden/logs/rondes.jsonl", "/bestanden/", "/bestanden/%2Fetc%2Fpasswd"):
            self.assertEqual(self.get(path)[0], 404, path)
