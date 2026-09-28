"""computers.py: herkenning, functiescore, upgrade en flipmarge voor
fietscomputers, plus de hygiëne van reference_bike_computers.csv."""
import csv
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from helpers import make_listing

import computers as pc
import db
import racefiets_jev as mp

CATALOG = pc.load_catalog()
CONFIG = pc.load_config()


def model(label: str) -> pc.ComputerModel:
    merk, _, naam = label.partition(" ")
    found = pc.find_model(CATALOG, merk, naam)
    assert found is not None, label
    return found


class CatalogHygieneTest(unittest.TestCase):
    def test_file_loads_with_known_values(self):
        # load_catalog() raises on an unknown value; getting here is the test.
        self.assertGreater(len(CATALOG), 50)

    def test_every_price_has_a_source(self):
        for m in CATALOG:
            if m.get("nieuwprijs_eur"):
                with self.subTest(model=m.label):
                    self.assertTrue(m.get("prijs_bron"))

    def test_every_filled_feature_has_a_source(self):
        # CLAUDE.md: geen marktfeiten zonder bron. A row without bron_url may
        # only carry what the owner's own list said, and has to say so.
        for m in CATALOG:
            if not m.get("bron_url"):
                with self.subTest(model=m.label):
                    for key in ("rerouting", "planning_op_apparaat", "route_sync", "bediening"):
                        self.assertEqual(m.get(key), "", key)

    def test_no_model_is_shadowed_by_an_earlier_row(self):
        # The file order is the match order. A title that is exactly a row's
        # own name must land on that row, not on an earlier, looser pattern.
        for m in CATALOG:
            title = f"{m.merk} {m.model}"
            if m.pattern.search(title):
                with self.subTest(model=m.label):
                    self.assertIs(pc.match_model(title, CATALOG), m)

    def test_baseline_is_in_the_catalog(self):
        base = CONFIG["baseline"]
        self.assertIsNotNone(pc.find_model(CATALOG, base["merk"], base["model"]))

    def test_unknown_value_stops_loading(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = tmp / "c.csv"
        with open(pc.CATALOG_PATH, encoding="utf-8") as f:
            header = next(csv.reader(f))
        row = {c: "" for c in header}
        row.update(merk="X", model="Y", pattern="xy", rerouting="misschien")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            w.writerow(row)
        with self.assertRaisesRegex(pc.CatalogError, "rerouting='misschien'"):
            pc.load_catalog(path)


class MatchTest(unittest.TestCase):
    CASES = {
        "Garmin Edge 530": "Garmin Edge 530",
        "garmin edge530 zgan": "Garmin Edge 530",
        "Garmin 830 met hartslagband": "Garmin Edge 830",
        "Garmin Edge 1030 Plus": "Garmin Edge 1030 Plus",
        "Garmin edge 1030": "Garmin Edge 1030",
        "Garmin Edge 130": "Garmin Edge 130",
        "Garmin Edge 130 plus": "Garmin Edge 130 Plus",
        "Garmin Edge 520 Plus": "Garmin Edge 520 Plus",
        "Garmin Edge 520": "Garmin Edge 520",
        "Garmin Edge 540 Solar": "Garmin Edge 540 Solar",
        "Garmin Edge Explore 2": "Garmin Edge Explore 2",
        "Garmin Edge Explore": "Garmin Edge Explore",
        "Wahoo Elemnt Roam v2": "Wahoo ELEMNT ROAM v2",
        "Wahoo Roam": "Wahoo ELEMNT ROAM v1",
        "Wahoo Elemnt Bolt": "Wahoo ELEMNT BOLT v1",
        "Wahoo Elemnt": "Wahoo ELEMNT",
        "Hammerhead Karoo 2": "Hammerhead Karoo 2",
        "Sigma Rox 12.1 Evo": "Sigma ROX 12.1 EVO",
        "Sigma ROX 12.0 sport": "Sigma ROX 12.0 SPORT",
        "Bryton Rider 750 SE": "Bryton Rider 750 SE",
        "Bryton Rider 750": "Bryton Rider 750",
        "Magene C606": "Magene C606",
        "Garmin Edge 530 met houder": "Garmin Edge 530",
        # Real titles from the full crawl of 28-09-2026 that were first missed.
        "Garmin Edge 800 fiets Navigatie met accessoires": "Garmin Edge 800",
        "Garmin Edge 130 MTB fietscomputer inclusief beugel": "Garmin Edge 130",
        "Garmin Edge Explorer": "Garmin Edge Explore",
        "Garmin Edge Touring Plus Fietsnavigatie": "Garmin Edge Touring Plus",
        "Garmin edge Touring": "Garmin Edge Touring",
        "Compacte Fietscomputer Garmin Edge 25": "Garmin Edge 20/25",
        "Te koop Wahoo ELEMNT MINI  fietscomputer": "Wahoo ELEMNT MINI",
        "2x Bryton Rider 420T fietscomputer met hartslagband": "Bryton Rider 420",
        "M460 polar fietscomputer": "Polar M460",
    }
    NOT_A_COMPUTER = (
        "Racefiets met Garmin Edge 530",
        "Houder voor Garmin Edge 530",
        "Wahoo Kickr",
        "Wahoo Kickr met Elemnt Bolt",
        "Racefiets Cube + Garmin Edge 130 Plus",
        "Siliconen beschermhoes voor Garmin Edge 1030",
        "wahoo fietscomputerhouders (2 stuks) element Bolt v1 v2",
        "Garmin Varia RTL515",
        "Testadvertentie",
    )

    def test_titles(self):
        for title, expected in self.CASES.items():
            with self.subTest(title=title):
                found = pc.match_model(title, CATALOG)
                self.assertIsNotNone(found)
                self.assertEqual(found.label, expected)

    def test_not_a_computer(self):
        for title in self.NOT_A_COMPUTER:
            with self.subTest(title=title):
                self.assertIsNone(pc.match_model(title, CATALOG))


class FeatureScoreTest(unittest.TestCase):
    def test_owners_choices_rank_the_well_known_models(self):
        # Rerouting + planning + training + buttons (the owner's choices,
        # 28-09-2026) put the Edge 530 above a Bolt v1 and a breadcrumb 130.
        score = lambda label: pc.feature_score(model(label), CONFIG).score
        self.assertGreater(score("Garmin Edge 530"), score("Wahoo ELEMNT BOLT v1"))
        self.assertGreater(score("Wahoo ELEMNT BOLT v1"), score("Garmin Edge 130"))
        self.assertGreater(score("Garmin Edge 840"), score("Garmin Edge 540"))

    def test_buttons_beat_touch_all_else_equal(self):
        cfg = dict(CONFIG, bediening={"knoppen": 1.0, "touch+knoppen": 0.7, "touch": 0.3})
        fields = dict(model("Garmin Edge 530").fields)
        buttons = pc.ComputerModel("X", "knoppen", model("Garmin Edge 530").pattern, dict(fields, bediening="knoppen"))
        touch = pc.ComputerModel("X", "touch", model("Garmin Edge 530").pattern, dict(fields, bediening="touch"))
        self.assertGreater(pc.feature_score(buttons, cfg).score, pc.feature_score(touch, cfg).score)

    def test_no_updates_costs_points(self):
        fields = dict(model("Hammerhead Karoo 2").fields)
        supported = pc.ComputerModel("X", "Y", model("Hammerhead Karoo 2").pattern, dict(fields, ondersteund="ja"))
        diff = pc.feature_score(supported, CONFIG).score - pc.feature_score(model("Hammerhead Karoo 2"), CONFIG).score
        self.assertAlmostEqual(diff, CONFIG["support_penalty"]["nee"])
        self.assertIn("geen updates meer", pc.feature_score(model("Hammerhead Karoo 2"), CONFIG).summary)

    def test_unknown_fields_are_named_and_earn_nothing(self):
        f = pc.feature_score(model("Garmin Edge 705"), CONFIG)
        self.assertEqual(f.score, 0.0)
        self.assertIn("rerouting", f.unknown)
        self.assertIn("onbekend: ", f.summary)


class SignalTest(unittest.TestCase):
    def listing(self, item_id, title, price, **kw):
        return make_listing(item_id=item_id, title=title, price_eur=price, **kw)

    def test_non_computers_get_nothing(self):
        bike = self.listing("b", "Racefiets met Garmin Edge 530", 900.0)
        self.assertEqual(pc.apply_computer_signals([bike]), 0)
        self.assertIsNone(bike.computer)

    def test_upgrade_is_relative_to_the_own_roam(self):
        edge = self.listing("e", "Garmin Edge 1040", 200.0)
        roam = self.listing("r", "Wahoo Elemnt Roam", 150.0)
        pc.apply_computer_signals([edge, roam])
        self.assertEqual(roam.computer.upgrade_delta, 0.0)
        self.assertFalse(roam.computer.is_upgrade)
        self.assertTrue(edge.computer.is_upgrade)
        self.assertAlmostEqual(edge.computer.upgrade_per_100, edge.computer.upgrade_delta / 2, places=1)
        self.assertEqual(pc.upgrades([edge, roam]), [edge])

    def test_flip_margin_needs_enough_comparables(self):
        few = [self.listing(f"a{i}", "Garmin Edge 530", p) for i, p in enumerate((150.0, 160.0, 170.0))]
        pc.apply_computer_signals(few)
        # Each has only two others: below min_comps (3).
        self.assertTrue(all(l.computer.flip_margin_eur is None for l in few))
        self.assertIn("te weinig", few[0].computer.comp_note)

    def test_flip_margin_is_median_of_others_after_negotiation(self):
        others = [self.listing(f"a{i}", "Garmin Edge 530", p) for i, p in enumerate((160.0, 180.0, 200.0))]
        cheap = self.listing("c", "Garmin edge 530 zgan", 90.0)
        pc.apply_computer_signals(others + [cheap])
        expected = 180.0 * CONFIG["flip"]["negotiation_factor"]
        self.assertAlmostEqual(cheap.computer.resale_eur, expected)
        self.assertAlmostEqual(cheap.computer.flip_margin_eur, expected - 90.0)
        self.assertEqual(cheap.computer.comp_count, 3)
        self.assertEqual(pc.flips(others + [cheap])[0], cheap)

    def test_repair_listing_is_shown_but_not_scored_as_a_deal(self):
        # Two of these in the first real crawl (28-09-2026): a repair service
        # at €110 topped the flip list.
        others = [self.listing(f"a{i}", "Garmin Edge 830", p) for i, p in enumerate((200.0, 220.0, 240.0))]
        repair = self.listing("r", "Garmin Edge 830 scherm vervangen", 110.0)
        pc.apply_computer_signals(others + [repair])
        self.assertIn("reparatie", repair.computer.excluded)
        self.assertIsNone(repair.computer.flip_margin_eur)
        self.assertFalse(repair.computer.is_upgrade)
        self.assertNotIn(repair, pc.flips(others + [repair]))
        # ... and its price doesn't drag the others' comparables down.
        self.assertEqual(others[0].computer.comp_count, 2)
        _, html = pc.render_panel(others + [repair])
        self.assertIn("reparatie of defect", html)

    def test_parts_are_never_a_computer_deal(self):
        # From the full category crawl, 28-09-2026: these topped the flip list.
        others = [self.listing(f"a{i}", "Garmin Edge 830", p) for i, p in enumerate((170.0, 185.0, 225.0))]
        lcd = self.listing("l", "Garmin LCD scherm Edge 830", 35.0)
        pc.apply_computer_signals(others + [lcd])
        self.assertEqual(lcd.computer.excluded, "los onderdeel of accessoire")
        self.assertNotIn(lcd, pc.flips(others + [lcd]) + pc.upgrades(others + [lcd]))

    def test_cheap_holder_is_an_accessory_expensive_one_a_computer(self):
        others = [self.listing(f"a{i}", "Wahoo Elemnt Roam", p) for i, p in enumerate((120.0, 140.0, 160.0))]
        holder = self.listing("h", "Wahoo Roam I stuurhouder", 15.0)
        bundle = self.listing("b", "Garmin Edge 530 + Stuurmount", 170.0)
        pc.apply_computer_signals(others + [holder, bundle])
        self.assertIn("vermoedelijk accessoire", holder.computer.excluded)
        self.assertNotIn(holder, pc.flips(others + [holder]))
        # Only 0 other Edge 530s: can't judge, so it stays a computer.
        self.assertEqual(bundle.computer.excluded, "")
        # The holder's €15 isn't a comparable for the Roams.
        self.assertEqual(others[0].computer.comp_count, 2)

    def test_a_running_bid_is_not_a_comparable(self):
        bids = [
            self.listing(f"b{i}", "Garmin Edge 530", 20.0, price_type="FAST_BID", price_is_bid=True, bid_count=2)
            for i in range(3)
        ]
        cheap = self.listing("c", "Garmin Edge 530", 90.0)
        pc.apply_computer_signals(bids + [cheap])
        self.assertEqual(cheap.computer.comp_count, 0)

    def test_comparables_from_earlier_runs(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = str(tmp / "koopjes.db")
        conn = db.connect(path)
        try:
            earlier = [self.listing(f"old{i}", "Garmin Edge 530", p) for i, p in enumerate((150.0, 170.0, 190.0))]
            db.sync_listings(conn, "garmin edge", earlier, datetime.now(timezone.utc).isoformat(timespec="seconds"))
            conn.commit()
        finally:
            conn.close()
        cheap = self.listing("c", "Garmin Edge 530", 90.0)
        pc.apply_computer_signals([cheap], db_path=path)
        self.assertEqual(cheap.computer.comp_count, 3)
        self.assertAlmostEqual(cheap.computer.resale_eur, 170.0 * CONFIG["flip"]["negotiation_factor"])

    def test_missing_database_is_not_an_error(self):
        cheap = self.listing("c", "Garmin Edge 530", 90.0)
        pc.apply_computer_signals([cheap], db_path=os.path.join(tempfile.gettempdir(), "bestaat_niet.db"))
        self.assertEqual(cheap.computer.comp_count, 0)


class PanelTest(unittest.TestCase):
    def test_panel_lists_upgrades_and_flips_separately(self):
        listings = [make_listing(item_id=f"a{i}", title="Garmin Edge 530", price_eur=p)
                    for i, p in enumerate((160.0, 180.0, 200.0))]
        listings.append(make_listing(item_id="c", title="Garmin Edge 1040", price_eur=150.0))
        listings.append(make_listing(item_id="d", title="Garmin Edge 530", price_eur=90.0))
        pc.apply_computer_signals(listings)
        count, html = pc.render_panel(listings)
        self.assertEqual(count, 5)
        self.assertIn("Upgrade voor mij", html)
        self.assertIn("Doorverkopen", html)
        self.assertIn("Garmin Edge 1040", html)

    def test_report_has_the_tab(self):
        listing = make_listing(title="Garmin Edge 530")
        pc.apply_computer_signals([listing])
        html = mp.render_html([listing], "garmin edge")
        self.assertIn("Fietscomputers (1)", html)
        self.assertIn('id="panel-computers"', html)

    def test_no_computers_says_so(self):
        count, html = pc.render_panel([make_listing()])
        self.assertEqual(count, 0)
        self.assertIn("Geen fietscomputers herkend", html)


class CliTest(unittest.TestCase):
    def test_overview_runs(self):
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(pc.main(["--merk", "wahoo"]), 0)
        self.assertIn("← eigen", out.getvalue())


if __name__ == "__main__":
    unittest.main()
