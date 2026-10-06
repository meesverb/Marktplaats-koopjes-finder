"""dossier.py: alles over één racefiets als tekst om aan Claude te geven —
de knop dossier op /racefietsen en `python dossier.py <id>`."""
import contextlib
import csv
import http.client
import io
import json
import re
import shutil
import sqlite3
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import requests
from helpers import FakeResponse, FakeSession, close_databases_before_cleanup, make_listing, repo_file

import dashboard
import db
import dossier as ds
import racebikes as rb
import recheck as rc

BIKE_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/{}-x"
TITLE = "Giant Defy Composite 2012 racefiets"


def bike(item_id, price, title=TITLE, **kw):
    kw.setdefault("url", BIKE_URL.format(item_id))
    kw.setdefault("description", "Carbon frame, Shimano Ultegra 10 speed, velgremmen.")
    kw.setdefault("frame_height", "56 cm")
    kw.setdefault("image_urls", f"https://images.example/{item_id}.jpg")
    return make_listing(item_id=item_id, title=title, price_eur=price, **kw)


def listing_page(item_id, price_cents, price_type="FIXED", description="Mooie fiets.<br>Ketting is versleten.",
                 attributes=(("Materiaal", "Carbon"), ("Framehoogte", "54 tot 57 cm")), **extra):
    """Een advertentiepagina: window.__CONFIG__ met het listing-object, en de
    omschrijving en Kenmerken zoals de pagina ze in de HTML zet."""
    listing = {"itemId": item_id, "isReserved": False,
               "priceInfo": {"priceCents": price_cents, "priceType": price_type},
               "gallery": {"microTipText": "Moet nu weg",
                           "imageUrls": [f"//images.marktplaats.com/api/v1/x/images/{n}?rule=ecg_mp_eps$_#.jpg"
                                         for n in ("een", "twee", "drie", "vier")],
                           "media": {"imageSizes": {"XL": "84", "XXL": "85"}}},
               "seller": {"name": "Jan Verkoper", "sellerType": "CONSUMER", "activeSinceDiff": "3 jaar"},
               "flags": {"shippable": False},
               "stats": {"viewCount": 120, "favoritedCount": 4, "since": "2026-09-20T10:00:00Z"}, **extra}
    attrs = "".join(f'<div class="Attributes-module-label">{k}</div><div class="Attributes-module-value">{v}</div>'
                    for k, v in attributes)
    return (f"<html><script>window.__CONFIG__ = {json.dumps({'listing': listing})};</script>{attrs}"
            f'<div data-collapsable="description">{description}</div></html>')


def csv_rows(text):
    block = re.search(r"```+csv\n(.*?)\n```", text, re.S).group(1)
    return list(csv.DictReader(io.StringIO(block)))


class Case(unittest.TestCase):
    track_connections = True

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        if self.track_connections:
            close_databases_before_cleanup(self)
        self.db = str(self.dir / "koopjes.db")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.later = (self.now + timedelta(hours=1)).isoformat()
        patcher = mock.patch.object(rc, "MIN_INTERVAL_S", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        market = [bike(f"a{i}", p) for i, p in enumerate((500.0, 550.0, 600.0, 650.0, 700.0))]
        family = [bike("f1", 900.0, title="Giant Defy Advanced 2 2016 racefiets",
                       description="Carbon, Shimano 105, schijfremmen.")]
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", market + family + [bike("c", 400.0)], self.now.isoformat())
        conn.close()
        self.intake = repo_file("mijn_fiets.md")

    def base(self):
        return rb.build_base(self.db, self.intake)

    def row(self, item_id):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT * FROM listing WHERE item_id = ?", (item_id,)).fetchone()
        finally:
            conn.close()

    def fetch(self, item_id, page):
        session = FakeSession({BIKE_URL.format(item_id): page})
        result = ds.fetch(self.db, item_id, session=session, now=self.later)
        self.assertEqual(len(session.requested), 1)  # één verzoek per klik, zoals controleer
        return result


class FromTheDatabaseTest(Case):
    def test_everything_the_card_knows_and_more(self):
        text = ds.build(self.base(), self.db, "c", self.intake)
        for section in ("# Dossier: " + TITLE, "## Vraag aan Claude", "## De advertentie", "## Kenmerken",
                        "## Omschrijving", "## Foto's", "## Welke fiets het is",
                        "## Schatting en oordeel van de koopjesfinder", "## Mijn fiets", "## Vergelijkingsfietsen"):
            self.assertIn(section, text)
        self.assertIn("Alleen uit de database", text)
        # Zonder ophalen is de omschrijving het fragment, en dat staat erbij.
        self.assertIn("Alleen het fragment uit de zoekresultaten", text)
        self.assertIn("**Verwachte verkoopprijs:", text)
        self.assertIn("**Upgrade van mijn fiets:", text)
        self.assertIn("| Onderdeel | Deze fiets | Mijn fiets |", text)  # de score per onderdeel
        self.assertIn("Giant Defy **Composite**, modeljaar 2012", text)  # de eigen tabel uit mijn_fiets.md
        self.assertIn("https://images.example/c.jpg", text)

    def test_the_comparables_as_csv(self):
        text = ds.build(self.base(), self.db, "c", self.intake)
        rows = csv_rows(text)
        ids = {r["id"] for r in rows}
        self.assertNotIn("c", ids)  # niet met zichzelf vergeleken
        self.assertTrue({"a0", "a1", "a2", "a3", "a4"} <= ids)
        used = {r["id"] for r in rows if r["in_schatting"] == "ja"}
        self.assertEqual(used, {"a0", "a1", "a2", "a3", "a4"})
        # Ook wat de trede wegliet: dezelfde familie, ander jaar en ander remtype.
        f1 = next(r for r in rows if r["id"] == "f1")
        self.assertEqual((f1["in_schatting"], f1["relatie"], f1["rem"]), ("nee", "familie", "schijfrem"))
        a0 = next(r for r in rows if r["id"] == "a0")
        self.assertEqual((a0["vraagprijs"], a0["bouwjaar"], a0["groepset"], a0["framemaat"]),
                         ("500", "2012", "Shimano Ultegra", "56 cm"))
        # De eerste rijen zijn die van de schatting, goedkoopste eerst.
        self.assertEqual([r["id"] for r in rows[:5]], ["a0", "a1", "a2", "a3", "a4"])
        self.assertIn("Per bouwjaar", text)

    def test_at_most_max_comps_in_the_csv(self):
        with mock.patch.object(ds, "MAX_COMPS", 2):
            text = ds.build(self.base(), self.db, "c", self.intake)
        self.assertEqual(len(csv_rows(text)), 2)
        self.assertIn("hier de eerste 2", text)

    def test_a_bike_without_a_model_has_no_comparables(self):
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [bike("x", 300.0, title="Mooie racefiets", description="")],
                         self.now.isoformat())
        conn.close()
        text = ds.build(self.base(), self.db, "x", self.intake)
        self.assertIn("**Geen schatting**", text)
        self.assertIn("ander model", text)
        self.assertNotIn("```csv", text)

    def test_own_notes_bids_and_part_prices(self):
        conn = db.connect(self.db)
        db.set_note(conn, "c", "gevraagd of 350 kan")
        conn.commit()
        conn.close()
        import own_bids as ob
        conn = db.connect(self.db)
        ob.place(conn, "c", 330.0, bid_at="2026-10-05T10:00:00")
        conn.commit()
        conn.execute("INSERT INTO flip_task (kind, title, price_eur, shop, bought_at, updated_at) "
                     "VALUES ('onderdeel', 'KMC X10 ketting', 21.5, 'Bike24', '2026-09-30', '2026-09-30')")
        conn.execute("INSERT INTO flip_task (kind, title, est_eur, updated_at) "
                     "VALUES ('onderdeel', 'Buitenbanden 25 mm', 60, '2026-10-01')")
        conn.execute("INSERT INTO flip_task (kind, title, est_eur, updated_at) "
                     "VALUES ('klus', 'Wielen richten', 20, '2026-10-01')")
        conn.commit()
        conn.close()
        text = ds.build(self.base(), self.db, "c", self.intake)
        self.assertIn("- Notitie: gevraagd of 350 kan", text)
        self.assertIn("- Mijn biedingen: €330 op 2026-10-05 (open)", text)
        self.assertIn("| KMC X10 ketting | €22 | Bike24 | 2026-09-30 |", text)
        self.assertIn("| Buitenbanden 25 mm | €60 (geschat) |", text)
        self.assertNotIn("Wielen richten", text)  # een klus is geen onderdeelprijs

    def test_unknown_or_not_a_road_bike(self):
        conn = db.connect(self.db)
        db.sync_listings(conn, "garmin", [make_listing(item_id="g", title="Garmin Edge 530", price_eur=90.0,
                                                       url="https://www.marktplaats.nl/v/fietsen-en-brommers/"
                                                           "fietsaccessoires-fietscomputers/g-x")],
                         self.now.isoformat())
        conn.close()
        session = FakeSession({})
        for item_id in ("bestaat-niet", "g"):
            with self.assertRaises(ds.DossierError):
                ds.build(self.base(), self.db, item_id, self.intake)
            with self.assertRaises(ds.DossierError):
                ds.fetch(self.db, item_id, session=session)
        self.assertEqual(session.requested, [])  # geen verzoek voor iets zonder dossier

    def test_a_bid_above_the_asking_price_keeps_the_asking_price_visible(self):
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [bike("b", 450.0, price_type="MIN_BID", price_is_bid=True)],
                         self.now.isoformat())
        conn.execute("UPDATE listing SET bid_high = 480, bid_count = 2, bids_checked_at = ? WHERE item_id = 'b'",
                     (self.now.isoformat(),))
        conn.commit()
        conn.close()
        text = ds.build(self.base(), self.db, "b", self.intake)
        self.assertIn("| Prijs | €480 (huidig bod, loopt nog op) |", text)
        self.assertIn("| Vraagprijs | €450 |", text)


class FetchTest(Case):
    def test_fetch_like_controleer_and_keep_the_full_description(self):
        checked, problem, message = self.fetch("c", listing_page("c", 38000))
        self.assertEqual(problem, "")
        self.assertIn("€400 → €380", message)
        row = self.row("c")
        self.assertEqual(row["price_eur"], 380.0)  # vastgelegd zoals controleer
        self.assertEqual(row["full_description"], "Mooie fiets.\nKetting is versleten.")
        self.assertIsNotNone(row["details_fetched_at"])
        text = ds.build(self.base(), self.db, "c", self.intake, checked, problem)
        self.assertIn("De advertentiepagina is net opgehaald", text)
        self.assertIn("De volledige omschrijving van de advertentiepagina", text)
        self.assertIn("Ketting is versleten.", text)
        # Alle foto's van de pagina, in de grootste maat die hij noemt.
        self.assertIn("Alle 4 foto's", text)
        self.assertIn("4. https://images.marktplaats.com/api/v1/x/images/vier?rule=ecg_mp_eps$_85.jpg", text)
        self.assertIn("| materiaal | Carbon |", text)  # de Kenmerken van de pagina
        self.assertIn("| Framemaat | 56 cm |", text)  # die uit de zoekresultaten gaat voor
        self.assertIn("| Verkoper | particulier, op Marktplaats sinds 3 jaar |", text)
        self.assertIn("| Verzenden | alleen ophalen |", text)
        self.assertIn("„Moet nu weg”", text)
        self.assertIn("(sinds 2026-09-20, volgens de advertentiepagina)", text)
        self.assertIn("Prijsverloop: €400", text)
        self.assertNotIn("Jan Verkoper", text)  # de naam van de verkoper heeft Claude niet nodig

    def test_the_frame_size_from_the_page_when_the_search_had_none(self):
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [bike("z", 450.0, frame_height="")], self.now.isoformat())
        conn.close()
        checked, problem, _ = self.fetch("z", listing_page("z", 45000))
        text = ds.build(self.base(), self.db, "z", self.intake, checked, problem)
        self.assertIn("| Framemaat | 54 tot 57 cm (Kenmerken) |", text)

    def test_bids_without_who_bid(self):
        bids = {"isBiddingEnabled": True, "currentMinimumBid": 30000,
                "bids": [{"id": 1, "value": 33000, "date": "2026-10-04T09:53:05Z", "user": {"nickname": "Piet B"}}]}
        checked, problem, _ = self.fetch("c", listing_page("c", 40000, "MIN_BID", bidsInfo=bids))
        text = ds.build(self.base(), self.db, "c", self.intake, checked, problem)
        self.assertIn("| Biedingen op de pagina | €330 op 2026-10-04 |", text)
        self.assertIn("1 bieding, hoogste €330, minimumbod €300", text)
        self.assertNotIn("Piet B", text)
        # De vraagprijs blijft de prijs: het minimumbod overschrijft hem niet (CLAUDE.md).
        self.assertIn("| Prijs | €400 (vraagprijs, bieden kan) |", text)

    def test_a_description_that_is_not_where_it_was_says_so(self):
        page = listing_page("c", 40000).replace('data-collapsable="description"', 'data-x="y"')
        checked, problem, _ = self.fetch("c", page)
        self.assertIsNone(checked.description)
        self.assertIsNone(self.row("c")["full_description"])
        text = ds.build(self.base(), self.db, "c", self.intake, checked, problem)
        self.assertIn("paginastructuur gewijzigd", text)

    def test_gone_still_gives_a_dossier(self):
        checked, problem, message = self.fetch("c", FakeResponse("", status_code=410))
        self.assertTrue(checked.gone)
        self.assertIn("niet meer op Marktplaats", message)
        text = ds.build(self.base(), self.db, "c", self.intake, checked, problem)
        self.assertIn("de advertentie staat niet meer op Marktplaats", text)
        self.assertIn("verdwenen", text)

    def test_no_connection_gives_a_dossier_from_the_database(self):
        class Down:
            headers = {}

            def get(self, url, timeout=0):
                raise requests.ConnectionError("geen verbinding")

        checked, problem, message = ds.fetch(self.db, "c", session=Down(), now=self.later)
        self.assertIsNone(checked)
        self.assertIn("geen verbinding", problem)
        self.assertIn("uit de database", message)
        text = ds.build(self.base(), self.db, "c", self.intake, checked, problem)
        self.assertIn("**Ophalen lukte niet:**", text)
        self.assertIn("## Vergelijkingsfietsen", text)

    def test_controleer_itself_does_not_keep_the_description(self):
        rc.recheck_listing(self.db, "c", session=FakeSession({BIKE_URL.format("c"): listing_page("c", 40000)}),
                           now=self.later)
        self.assertIsNone(self.row("c")["full_description"])


class HelpersTest(unittest.TestCase):
    def test_photos(self):
        page = {"gallery": {"imageUrls": ["//img.example/a?rule=x$_#.jpg", "http://img.example/b.jpg", 7,
                                          "https://img.example/c?rule=x$_#.jpg"]}}
        # Zonder maten van de pagina: PHOTO_SIZE; alleen https.
        self.assertEqual(ds.page_photos(page), ["https://img.example/a?rule=x$_85.jpg",
                                                "https://img.example/c?rule=x$_85.jpg"])
        page["gallery"]["media"] = {"imageSizes": {"L": "83", "XL": "84"}}
        self.assertEqual(ds.page_photos(page)[0], "https://img.example/a?rule=x$_84.jpg")
        self.assertEqual(ds.page_photos(None), [])
        self.assertEqual(ds.page_photos({"gallery": "kapot"}), [])

    def test_fence_survives_backticks_in_the_text(self):
        block = ds.fenced("ketting ```nieuw``` en ````")
        self.assertTrue(block.startswith("`````text\n"))
        self.assertTrue(block.endswith("\n`````"))

    def test_table_cells(self):
        self.assertEqual(ds.cell("a | b\nc"), "a \\| b c")
        self.assertEqual(ds.euro(1250), "€1.250")


class CommandLineTest(Case):
    def test_to_a_file(self):
        out = self.dir / "dossier.md"
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ds.main(["c", "--db", self.db, "--mijn-fiets", self.intake, "--uit", str(out)]), 0)
        self.assertIn("## Vergelijkingsfietsen", out.read_text(encoding="utf-8"))

    def test_no_database_or_unknown_bike(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ds.main(["c", "--db", str(self.dir / "geen.db")]), 1)
            self.assertEqual(ds.main(["bestaat-niet", "--db", self.db, "--mijn-fiets", self.intake]), 1)
            self.assertEqual(ds.main(["bestaat-niet", "--db", self.db, "--mijn-fiets", self.intake, "--ophalen"]), 1)
        self.assertIn("bestaat niet", err.getvalue())
        self.assertIn("niet in de database", err.getvalue())


class LiveTest(Case):
    track_connections = False

    def setUp(self):
        super().setUp()
        self.session = FakeSession({BIKE_URL.format("c"): listing_page("c", 38000)})
        patcher = mock.patch.object(rc, "make_session", lambda: self.session)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.httpd = dashboard.make_server(self.db, 0, intake_path=self.intake)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, fields=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}", "X-Live": "1"}
        body = None
        if fields is not None:
            body = urllib.parse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, headers)
        r = conn.getresponse()
        text = r.read().decode()
        conn.close()
        return r.status, text

    def test_the_button(self):
        status, page = self.request("GET", rb.PATH)
        self.assertEqual(status, 200)
        self.assertIn(f"DOSSIER_PATH = '{ds.PATH}'", page)
        self.assertIn('data-do="dossier"', page)
        self.assertIn("id='dtext'", page)
        token = re.search(r"data-token='([^']+)'", page).group(1)

        status, text = self.request("POST", ds.PATH, {"token": token, "markt": rb.MARKET_KEY, "item_id": "c"})
        self.assertEqual(status, 200)
        data = json.loads(text)
        self.assertEqual(len(self.session.requested), 1)
        self.assertIn("€400 → €380", data["message"])
        self.assertTrue(data["dossier"].startswith("# Dossier: " + TITLE))
        self.assertIn("Ketting is versleten.", data["dossier"])
        self.assertEqual(data["bike"]["p"], 380.0)  # de kaart is bijgewerkt, zoals na controleer

        data = json.loads(self.request("POST", ds.PATH, {"token": token, "item_id": "bestaat-niet"})[1])
        self.assertIn("Geen dossier", data["message"])
        self.assertNotIn("dossier", data)
        self.assertEqual(len(self.session.requested), 1)

    def test_a_stale_page_does_nothing(self):
        data = json.loads(self.request("POST", ds.PATH, {"token": "oud", "item_id": "c"})[1])
        self.assertTrue(data["reload"])
        self.assertEqual(self.session.requested, [])


if __name__ == "__main__":
    unittest.main()
