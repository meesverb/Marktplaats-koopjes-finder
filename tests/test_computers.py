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
        self.assertAlmostEqual(cheap.computer.flip_margin_eur, expected - 90.0 - CONFIG["flip"]["costs_eur"])
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
        self.assertEqual(lcd.computer.kind, "onderdeel")
        self.assertIn("LCD", lcd.computer.excluded)
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
        self.assertIn("Flips met winst", html)
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


class ClassifyTitleTest(unittest.TestCase):
    """Every title here is a real one from the full crawl of the category,
    28-09-2026 (361 listings). The rule of thumb found there: a real computer
    names the device or a connector before the holder/case word; a loose
    accessory has that word before the model, or right after it."""

    KINDS = {
        # computers with extras
        "Garmin Edge 530 + Stuurmount": "computer",
        "Garmin Edge 830 incl frontmount": "computer",
        "Garmin Edge Explore 2 met Power Mount": "computer",
        "Garmin Edge 520 met Garmin mount.": "computer",
        "Garmin Edge 130 MTB fietscomputer inclusief beugel": "computer",
        "Garmin Edge 820 fietscomputer met steun": "computer",
        "GARMIN EDGE 830 fietscomputer navigatie gps + bumper": "computer",
        "Garmin 840 Sensor Bundle": "computer",
        "Garmin Edge 530 Sensor Bundel - Zo goed als nieuw": "computer",
        "Wahoo ELEMNT BOLT v3 nieuw in doos": "computer",
        "Wahoo ELEMNT ROAM GPS Doos met nieuwe accessoires": "computer",
        "Garmin Edge 510 fietscomputer met houder en kabel": "computer",
        "Wahoo ELEMNT BOLT V1 GPS + sensor + 2 houders": "computer",
        "Garmin Edge 1030 Fietscomputer met GPS": "computer",
        # accessories, parts, repairs, wanted
        "Fietscomputerhouder voor Wahoo Roam": "accessoire",
        "Hoesje voor Garmin 1000 serie. Past perfect op de 1000": "accessoire",
        "Zwart siliconen beschermhoes Garmin Edge 1030 (plus)": "accessoire",
        "K-EDGE WAHOO ELEMNT BOLT 2.0 AERO RACE MOUNT": "accessoire",
        "garmin LCD scherm Edge 830": "onderdeel",
        "Hammerhead Karoo 2 Custom Color Kit (Blauw)": "onderdeel",
        "Wahoo ELEMNT Bolt & Roam Veiligheidskoord / tether": "onderdeel",
        "Garmin Edge 830 scherm vervangen": "defect",
        "ik zoek een kapotte garmin edge 1030": "gevraagd",
        # the price decides
        "Hammerhead Karoo 3 houder nieuw": "twijfel",
        "Wahoo Roam I stuurhouder": "twijfel",
        # a bike
        "Racefiets Cube + Garmin Edge 130 Plus": "fiets",
    }

    def test_real_titles(self):
        for title, kind in self.KINDS.items():
            with self.subTest(title=title):
                verdict = pc.classify_title(title, CATALOG)
                self.assertIsNotNone(verdict)
                self.assertEqual(verdict.kind, kind, verdict.reason)

    UNKNOWN = {
        "Van Rysel GPS 500 Fietscomputer - Nieuw in doos": "computer",
        "Wahoo zeer complete set!": "computer",
        "Magene Fiets GPS mooie set met 4 Cadans sensoren.": "computer",
        "dr.bike COM 90 HR fietscomputer met hartslagmeting": "computer",
        "Garmin fietscomputer houder": "accessoire",
        "Garmin Edge Aero Mount - Zo goed als nieuw": "accessoire",
        "K-Edge Garmin fiets computer mount": "accessoire",
        "Garmin Snelheidssensor 2 - nieuw": "accessoire",
        "Garmin Varia RTL515": "accessoire",
        "Garmin Edge Explore 820 doosje met boekje": "accessoire",
        "Garmin Edge batterij vervangen": "defect",
        "Wahoo veiligheidskoort voor Roam en Bolt v1 en V2": "onderdeel",
    }

    def test_real_titles_without_a_known_model(self):
        for title, kind in self.UNKNOWN.items():
            with self.subTest(title=title):
                self.assertIsNone(pc.classify_title(title, CATALOG))
                self.assertEqual(pc.classify_unknown(title)[0], kind)

    def test_no_model_is_no_verdict(self):
        self.assertIsNone(pc.classify_title("Garmin stuurhouder - Zo goed als nieuw", CATALOG))


class DoubtTest(unittest.TestCase):
    def test_holder_without_comparables_is_judged_on_the_floor(self):
        # Karoo 3: no nieuwprijs in the catalogue, no other listings.
        holder = make_listing(item_id="h", title="Hammerhead Karoo 3 houder nieuw", price_eur=20.0)
        pc.apply_computer_signals([holder])
        self.assertEqual(holder.computer.kind, "accessoire")
        self.assertIn("minder dan €30", holder.computer.reason)

    def test_holder_word_but_a_computer_price_stays_a_computer(self):
        roam = make_listing(item_id="r", title="Wahoo Roam I stuurhouder", price_eur=140.0)
        pc.apply_computer_signals([roam])
        # No comparables, but the Roam v1 has a nieuwprijs (€349,99): 40% of it.
        self.assertEqual(roam.computer.kind, "computer")
        self.assertIn("past bij een computer", roam.computer.reason)

    def test_doubt_without_price_is_kept(self):
        holder = make_listing(item_id="h", title="Hammerhead Karoo 3 houder nieuw", price_eur=None,
                              price_type="FAST_BID", price_is_bid=True)
        pc.apply_computer_signals([holder])
        self.assertEqual(holder.computer.kind, "computer")
        self.assertIn("kijk op de foto", holder.computer.reason)


class DescriptionTest(unittest.TestCase):
    def test_accessories_without_the_computer(self):
        # Real listing, 28-09-2026: €200, title says GPS, description says not.
        box = make_listing(item_id="x", title="Wahoo ELEMNT ROAM GPS Doos met nieuwe accessoires", price_eur=200.0,
                           description="Te koop: wahoo elemnt roam 3 accessoires zonder de fietscomputer. "
                                       "Mijn fiets en wahoo zijn gestolen")
        pc.apply_computer_signals([box])
        self.assertEqual(box.computer.kind, "accessoire")
        self.assertIn("zonder de fietscomputer", box.computer.reason)

    def test_other_mentions_of_zonder_are_fine(self):
        edge = make_listing(item_id="e", title="Garmin Edge 840 GPS Fietscomputer, zonder sensoren", price_eur=350.0,
                            description="Zonder doos, zonder computerhouder. Werkt perfect.")
        pc.apply_computer_signals([edge])
        self.assertEqual(edge.computer.kind, "computer")

    def test_unknown_model_with_the_same_description(self):
        self.assertEqual(pc.classify_unknown("Wahoo zeer complete set!", "alles zonder de wahoo zelf")[0],
                         "accessoire")


class CategoryTest(unittest.TestCase):
    def test_a_bike_listing_naming_a_computer_is_ignored(self):
        bike = make_listing(item_id="b", title="Giant Defy met Garmin Edge 530", price_eur=900.0,
                            url="https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/m1-giant")
        self.assertEqual(pc.apply_computer_signals([bike]), 0)
        self.assertIsNone(bike.computer)

    def test_category_from_url(self):
        self.assertEqual(pc.listing_category(
            "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/m2-x"),
            "fietsaccessoires-fietscomputers")
        self.assertIsNone(pc.listing_category("https://www.marktplaats.nl/v/x/m1-test"))


class FlipMathTest(unittest.TestCase):
    def listings(self, cheap_price=90.0, **cheap):
        others = [make_listing(item_id=f"a{i}", title="Garmin Edge 530", price_eur=p)
                  for i, p in enumerate((140.0, 160.0, 180.0, 200.0, 220.0))]
        target = make_listing(item_id="c", title="Garmin Edge 530", price_eur=cheap_price, **cheap)
        return others, target

    def test_profit_band_uses_the_quartiles(self):
        others, target = self.listings()
        pc.apply_computer_signals(others + [target])
        c = target.computer
        f = CONFIG["flip"]["negotiation_factor"]
        self.assertAlmostEqual(c.resale_eur, 180.0 * f)
        self.assertAlmostEqual(c.resale_low_eur, 160.0 * f)
        self.assertAlmostEqual(c.resale_high_eur, 200.0 * f)
        self.assertAlmostEqual(c.profit_eur, 180.0 * f - 90.0 - CONFIG["flip"]["costs_eur"])
        self.assertLess(c.profit_low_eur, c.profit_eur)
        self.assertGreater(c.profit_high_eur, c.profit_eur)

    def test_shipping_is_three_euro_by_default(self):
        # The owner's choice, 28-09-2026.
        self.assertEqual(CONFIG["flip"]["costs_eur"], 3)
        others, target = self.listings()
        pc.apply_computer_signals(others + [target])
        self.assertAlmostEqual(target.computer.profit_eur,
                               180.0 * CONFIG["flip"]["negotiation_factor"] - 90.0 - 3)

    def test_costs_come_off_every_flip(self):
        others, target = self.listings()
        config = pc.load_config()
        config["flip"]["costs_eur"] = 12.5
        pc.apply_computer_signals(others + [target], config=config)
        self.assertAlmostEqual(target.computer.profit_eur,
                               180.0 * config["flip"]["negotiation_factor"] - 90.0 - 12.5)

    def test_no_price_gives_a_max_bid(self):
        others, target = self.listings(cheap_price=None, price_type="FAST_BID", price_is_bid=True)
        pc.apply_computer_signals(others + [target])
        self.assertIsNone(target.computer.profit_eur)
        self.assertAlmostEqual(target.computer.max_bid_eur,
                               160.0 * CONFIG["flip"]["negotiation_factor"] - CONFIG["flip"]["costs_eur"])
        self.assertEqual(pc.open_bids(others + [target]), [target])

    def test_upgrade_net_cost_subtracts_what_the_own_computer_brings(self):
        roams = [make_listing(item_id=f"r{i}", title="Wahoo Elemnt Roam", price_eur=p)
                 for i, p in enumerate((100.0, 120.0, 140.0))]
        edge = make_listing(item_id="e", title="Garmin Edge 1040", price_eur=250.0)
        pc.apply_computer_signals(roams + [edge])
        own = 120.0 * CONFIG["flip"]["negotiation_factor"]
        self.assertAlmostEqual(edge.computer.own_resale_eur, own)
        self.assertAlmostEqual(edge.computer.net_upgrade_cost_eur, 250.0 - own)

    def test_price_kind(self):
        self.assertEqual(pc.price_kind(make_listing(price_type="MIN_BID", price_is_bid=True)),
                         "vraagprijs, bieden kan")
        self.assertEqual(pc.price_kind(make_listing(price_type="FAST_BID", price_is_bid=True, bid_count=2)),
                         "huidig bod, loopt nog op")
        self.assertEqual(pc.price_kind(make_listing()), "vaste prijs")


class FeatureChangesTest(unittest.TestCase):
    def test_edge_840_against_the_own_roam(self):
        gains, losses = pc.feature_changes(model("Garmin Edge 840"), pc.baseline_model())
        self.assertIn("plannen op het apparaat: volledig i.p.v. beperkt", gains)
        self.assertIn("touch+knoppen i.p.v. knoppen", losses)

    def test_unknown_on_either_side_is_no_change(self):
        gains, losses = pc.feature_changes(model("Garmin Edge 705"), pc.baseline_model())
        self.assertEqual((gains, losses), ([], []))


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
