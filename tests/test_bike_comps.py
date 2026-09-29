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

    def sync(self, listings, when=None):
        db.sync_listings(self.conn, "giant defy", listings, (when or self.now).isoformat())

    def rows(self):
        return {r.item_id: r for r in bc.load_rows(self.conn, self.subject)}

    def link_model(self, item_id, label, material=None):
        specs = json.dumps({"frame_material": material} if material else {})
        self.conn.execute("INSERT OR IGNORE INTO model (kind, model, pattern, specs_json) VALUES ('bike', ?, ?, ?)",
                          (label, label, specs))
        model_id = self.conn.execute("SELECT id FROM model WHERE pattern = ?", (label,)).fetchone()[0]
        self.conn.execute("INSERT INTO listing_model (listing_id, model_id) VALUES (?, ?)", (item_id, model_id))
        self.conn.commit()

    def test_carbon_and_unknown_are_in_aluminium_is_not(self):
        self.sync([
            bike("adv", "Giant Defy Advanced 2"),
            bike("kaal", "Giant Defy 2016"),
            bike("tekst", "Giant Defy 1 aluminium"),  # nog geen specs: de tekst beslist
            bike("aluxx", "Giant Defy Aluxx"),
            bike("kenmerk", "Giant Defy racefiets"),
            bike("frame", "Giant Defy Composite frame", url=PARTS_URL.format("frame")),
            bike("trek", "Trek Domane carbon"),
        ])
        db.sync_listing_specs(self.conn, {"kenmerk": {"frame_material": "aluminium"}}, source="marktplaats")
        self.link_model("adv", "Giant Defy Advanced", "carbon")
        self.link_model("adv", "Giant Defy (overig)")
        self.link_model("aluxx", "Giant Defy 0-5 (aluminium)", "aluminium")

        rows = self.rows()
        self.assertEqual(set(rows), {"adv", "kaal"})
        self.assertEqual(rows["adv"].material, "carbon")
        self.assertEqual(rows["adv"].model_label, "Giant Defy Advanced")  # het specifiekste
        self.assertIsNone(rows["kaal"].material)  # materiaal onbekend: de eigenaar beslist
        self.assertEqual(rows["kaal"].year, 2016)

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
