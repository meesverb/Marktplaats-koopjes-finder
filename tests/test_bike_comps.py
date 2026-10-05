"""bike_comps.py: de vergelijkingslijst voor de eigen fiets (/fiets), en de
taxatie die alleen rekent met wat de eigenaar meenam."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import make_listing, repo_file

import bike_comps as bc
import db
import valuation as val

BIKE_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/{}-x"
PARTS_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsonderdelen-racefietsen/{}-x"
SPORT_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-heren-sportfietsen-en-toerfietsen/{}-x"
OMA_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-dames-omafietsen/{}-x"
ACCESSORY_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/{}-x"
CYCLING_URL = "https://www.marktplaats.nl/v/sport-en-fitness/wielrennen/{}-x"


def bike(item_id, title, price=600.0, **kw):
    kw.setdefault("url", BIKE_URL.format(item_id))
    return make_listing(item_id=item_id, title=title, price_eur=price, **kw)


class ListTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.conn = db.connect(str(self.dir / "koopjes.db"))
        self.addCleanup(self.conn.close)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        bike_text = Path(repo_file("mijn_fiets.md")).read_text(encoding="utf-8")
        self.subject = val.subject_from_owner_bike(val.parse_owner_bike(bike_text))

    def sync(self, listings, when=None, query="giant defy"):
        db.sync_listings(self.conn, query, listings, (when or self.now).isoformat())

    def rows(self):
        return {r.item_id: r for r in bc.load_rows(self.conn, self.subject)}

    def link_model(self, item_id, label, material=None):
        specs = json.dumps({"frame_material": material} if material else {})
        self.conn.execute("INSERT OR IGNORE INTO model (kind, model, pattern, specs_json) VALUES ('bike', ?, ?, ?)",
                          (label, label, specs))
        model_id = self.conn.execute("SELECT id FROM model WHERE pattern = ?", (label,)).fetchone()[0]
        self.conn.execute("INSERT INTO listing_model (listing_id, model_id) VALUES (?, ?)", (item_id, model_id))
        self.conn.commit()

    def test_every_material_is_in_with_where_it_comes_from(self):
        # De eigenaar kiest zelf (29-09-2026): ook aluminium staat erin.
        self.sync([
            bike("adv", "Giant Defy Advanced 2"),
            bike("kaal", "Giant Defy 2016"),
            bike("tekst", "Giant Defy 1 aluminium"),  # nog geen specs: de tekst beslist
            bike("aluxx", "Giant Defy Aluxx"),
            bike("kenmerk", "Giant Defy racefiets"),
        ])
        self.sync([bike("trek", "Trek Domane carbon")], query="racefiets")
        db.sync_listing_specs(self.conn, {"kenmerk": {"frame_material": "aluminium"}}, source="marktplaats")
        self.link_model("adv", "Giant Defy Advanced", "carbon")
        self.link_model("adv", "Giant Defy (overig)")
        self.link_model("aluxx", "Giant Defy 0-5 (aluminium)", "aluminium")

        rows = self.rows()
        self.assertEqual(set(rows), {"adv", "kaal", "tekst", "aluxx", "kenmerk"})  # zonder "defy" niet
        self.assertEqual((rows["adv"].material, rows["adv"].material_source), ("carbon", bc.FROM_MODEL))
        self.assertEqual(rows["adv"].model_label, "Giant Defy Advanced")  # het specifiekste
        self.assertEqual((rows["aluxx"].material, rows["aluxx"].material_source), ("aluminium", bc.FROM_MODEL))
        self.assertEqual((rows["tekst"].material, rows["tekst"].material_source), ("aluminium", bc.FROM_TEXT))
        # Alleen de kenmerken zeggen aluminium; die klopten niet altijd
        # (een Defy met "COMPOSITE" op de achterbrug, 29-09-2026).
        self.assertEqual((rows["kenmerk"].material, rows["kenmerk"].material_source),
                         ("aluminium", bc.FROM_SELLER))
        self.assertIsNone(rows["kaal"].material)  # materiaal onbekend: de eigenaar beslist
        self.assertEqual(rows["kaal"].material_source, "")
        self.assertEqual(rows["kaal"].year, 2016)

    def test_the_text_wins_over_the_seller_for_the_source(self):
        self.sync([bike("beide", "Giant Defy carbon")])
        db.sync_listing_specs(self.conn, {"beide": {"frame_material": "aluminium"}}, source="marktplaats")
        db.sync_listing_specs(self.conn, {"beide": {"frame_material": "carbon"}})
        row = self.rows()["beide"]
        self.assertEqual((row.material, row.material_source), ("carbon", bc.FROM_TEXT))

    def test_what_the_defy_search_found_is_in_without_the_word(self):
        # Marktplaats gaf voor "giant defy" ook "Giant racefiets maat L" (geen
        # "defy" in titel of omschrijving) en een advertentie waarvan "Carbon
        # Defy frame" na de 200 tekens van de zoekresultaten stond.
        self.sync([bike("zoek", "Giant racefiets maat L")])
        self.sync([bike("tekst", "Giant Defy racefiets")], query="racefiets")
        self.sync([bike("ander", "Giant racefiets maat M")], query="racefiets")
        rows = self.rows()
        self.assertEqual(set(rows), {"zoek", "tekst"})
        self.assertFalse(rows["zoek"].family_in_text)
        self.assertTrue(rows["tekst"].family_in_text)

    def test_every_category_but_parts_and_accessories(self):
        # Een Defy onder sportfietsen of omafietsen is nog steeds een Defy
        # (29-09-2026: een Defy Composite 1 onder heren-sportfietsen).
        self.sync([
            bike("race", "Giant Defy Composite"),
            bike("sport", "Giant Defy Composite 1 Carbon Racefiets", url=SPORT_URL.format("sport")),
            bike("oma", "Giant Defy composite", url=OMA_URL.format("oma")),
            bike("wielren", "Giant defy advanced 1", url=CYCLING_URL.format("wielren")),
            bike("vreemd", "Giant Defy", url="https://example.com/defy"),
            bike("frame", "Giant Defy Composite frame", url=PARTS_URL.format("frame")),
            bike("computer", "Garmin Edge van mijn Giant Defy", url=ACCESSORY_URL.format("computer")),
        ])
        rows = self.rows()
        self.assertEqual(set(rows), {"race", "sport", "oma", "wielren", "vreemd"})
        self.assertEqual(rows["race"].category_label, "")
        self.assertEqual(rows["sport"].category_label, "heren sportfietsen en toerfietsen")
        self.assertEqual(rows["oma"].category_label, "dames omafietsen")
        self.assertEqual(rows["wielren"].category_label, "wielrennen")
        self.assertEqual(rows["vreemd"].category, "")

    def test_gone_listings_stay_for_the_window(self):
        self.sync([bike("weg", "Giant Defy carbon"), bike("online", "Giant Defy carbon")])
        # Een volledige ronde een dag later ziet alleen "online" nog.
        db.sweep_disappeared(self.conn, "giant defy", {"online"}, (self.now + timedelta(days=1)).isoformat())
        self.sync([bike("te_oud", "Giant Defy carbon")],
                  when=self.now - timedelta(days=val.DEFAULT_COMP_WINDOW_DAYS + 5))
        rows = self.rows()
        self.assertEqual(set(rows), {"weg", "online"})
        self.assertTrue(rows["weg"].gone)
        self.assertFalse(rows["online"].gone)

    def test_bids_are_listed_but_their_price_does_not_count(self):
        self.sync([
            bike("vast", "Giant Defy carbon", 650.0),
            bike("vraag", "Giant Defy carbon", 700.0, price_type="MIN_BID", price_is_bid=True),
            bike("bod", "Giant Defy carbon", 400.0, price_type="FAST_BID", price_is_bid=True, bid_count=3),
            bike("leeg", "Giant Defy carbon", None, price_type="FAST_BID", price_is_bid=True),
        ])
        rows = self.rows()
        self.assertTrue(rows["vast"].counts)
        self.assertTrue(rows["vraag"].counts)  # MIN_BID: de prijs is de vraagprijs
        self.assertFalse(rows["bod"].counts)
        self.assertIn("al geboden", rows["bod"].why_not)
        self.assertEqual(rows["leeg"].why_not, "geen prijs")

    def test_the_choice_comes_along(self):
        self.sync([bike("a", "Giant Defy carbon"), bike("b", "Giant Defy carbon")])
        db.set_comp_choice(self.conn, "a", bc.MEE)
        db.set_comp_choice(self.conn, "b", bc.NIET)
        rows = self.rows()
        self.assertEqual((rows["a"].choice, rows["b"].choice), ("mee", "niet"))
        self.assertEqual(val.chosen_comp_ids(self.conn), frozenset({"a"}))
        db.set_comp_choice(self.conn, "a", None)
        self.assertIsNone(self.rows()["a"].choice)


def candidate(item_id, price, title="Giant Defy Composite 2012"):
    return val.CompCandidate(item_id=item_id, title=title, url="", price_eur=price, text=title.lower(),
                             specs={"frame_material": "carbon"}, groupset_tier=5)


class ChosenCompsTest(unittest.TestCase):
    def setUp(self):
        text = Path(repo_file("mijn_fiets.md")).read_text(encoding="utf-8")
        self.subject = val.subject_from_owner_bike(val.parse_owner_bike(text))
        self.candidates = [candidate(f"c{i}", 500.0 + 50 * i) for i in range(6)]
        # Een Advanced die de ladder weghoudt: wie hem zelf meeneemt, krijgt hem.
        self.candidates.append(candidate("adv", 1500.0, "Giant Defy Advanced 2012"))

    def test_only_the_chosen_count(self):
        comps = val.select_comps(self.subject, self.candidates, frozenset({"c0", "c1", "adv"}))
        self.assertEqual({c.item_id for c in comps.comps}, {"c0", "c1", "adv"})
        self.assertEqual((comps.rung, comps.confidence), (val.CHOSEN_RUNG, "indicatief"))

    def test_five_or_more_is_a_hard_number(self):
        comps = val.select_comps(self.subject, self.candidates, frozenset(f"c{i}" for i in range(5)))
        self.assertEqual(comps.confidence, "hoog")

    def test_nothing_chosen_is_no_comps(self):
        self.assertIsNone(val.select_comps(self.subject, self.candidates, frozenset()))
        # Gekozen, maar zonder vraagprijs (niet onder de kandidaten): ook niets.
        self.assertIsNone(val.select_comps(self.subject, self.candidates, frozenset({"bod"})))
        self.assertIsNone(val.value_subject(self.subject, self.candidates, chosen=frozenset()))

    def test_the_evidence_says_where_the_comps_come_from(self):
        valuation = val.value_subject(self.subject, self.candidates, chosen=frozenset({"c0", "c1"}))
        self.assertTrue(valuation.evidence[0].note.startswith("E1: zelf meegenomen op /fiets, n=2"))

    def test_without_chosen_the_ladder_still_works(self):
        comps = val.select_comps(self.subject, self.candidates)
        self.assertNotIn("adv", {c.item_id for c in comps.comps})


class CliTest(unittest.TestCase):
    def test_the_cli_says_to_choose_on_the_page(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = str(tmp / "koopjes.db")
        conn = db.connect(path)
        try:
            db.sync_listings(conn, "giant defy", [bike(f"d{i}", "Giant Defy Composite 2012") for i in range(6)],
                             datetime.now(timezone.utc).isoformat())
        finally:
            conn.close()
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = val.main(["--db", path, "--mijn-fiets", repo_file("mijn_fiets.md"), "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("nog geen advertenties meegenomen", err.getvalue())


class StorageTest(unittest.TestCase):
    def test_a_database_from_before_migration_16_has_no_choices(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = tmp / "koopjes.db"
        conn = db.connect(str(path))
        conn.execute("DROP TABLE comp_choice")
        for table in db.FLIP_TABLES + db.PLACE_TABLES + db.MODEL_TABLES + db.RULE_TABLES + db.OFFER_TABLES + db.LABEL_TABLES:  # migratie 17-22 draaien daarna ook opnieuw
            conn.execute(f"DROP TABLE {table}")
        conn.execute("DELETE FROM schema_version WHERE version >= 16")
        conn.commit()
        conn.close()
        readonly = bc.open_readonly(path)
        try:
            self.assertEqual(db.list_comp_choices(readonly), {})
        finally:
            readonly.close()
        conn = db.connect(str(path))  # migreert naar 16
        try:
            db.set_comp_choice(conn, "a", "mee")
            db.set_comp_choice(conn, "a", "niet")  # vervangt
            self.assertEqual(db.list_comp_choices(conn), {"a": "niet"})
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
