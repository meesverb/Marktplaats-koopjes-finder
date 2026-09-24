"""reference_bikes.csv and reference_bike_accessories.csv — fase 7's data.

These are hand-researched files, so the tests guard the things that break
silently: a row without a source, a pattern that steals another row's
listings (first match wins), and a realistic Marktplaats title landing on
the wrong model. The titles below are written the way sellers write them,
not copied from the labels.
"""
import csv
import unittest

from helpers import mp, repo_file

import check_reference_overlaps
import db

BIKES = repo_file("reference_bikes.csv")
ACCESSORIES = repo_file("reference_bike_accessories.csv")


def first_label(reference, title):
    for row in reference:
        if row["regex"].search(title):
            return row["label"]
    return None


class ReferenceFileHygieneTest(unittest.TestCase):
    def test_both_files_load_and_are_clean(self):
        for path in (BIKES, ACCESSORIES):
            with self.subTest(path=path):
                reference = mp.load_reference_data(path)
                self.assertGreater(len(reference), 0)
                self.assertEqual(check_reference_overlaps.find_overlaps(reference), [])
                self.assertEqual(check_reference_overlaps.find_dead_patterns(reference), [])

    def test_every_row_names_a_known_kind_and_a_source(self):
        for path in (BIKES, ACCESSORIES):
            with open(path, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    with self.subTest(label=row["label"]):
                        self.assertIn(row["kind"], db.MODEL_KINDS)
                        self.assertTrue(row["source_url"].startswith("https://"))

    def test_the_bike_file_holds_no_accessories(self):
        # One --reference-file per run, and the first match sets the
        # nieuwprijs the dealscore compares against. A Garmin row in the bike
        # file would turn "Cube met Garmin Edge 530, €900" into 300% of a
        # €299.99 original price. That's why accessories have their own file.
        with open(BIKES, encoding="utf-8-sig") as f:
            self.assertEqual({row["kind"] for row in csv.DictReader(f)}, {"bike"})
        reference = mp.load_reference_data(BIKES)
        self.assertIsNone(first_label(reference, "Garmin Edge 530 met hartslagband"))


class BikeTitleMatchingTest(unittest.TestCase):
    CASES = [
        ("Giant Defy Composite 1 maat 56 Ultegra carbon", "Giant Defy Composite 1"),
        ("Giant Defy Composite 2 racefiets", "Giant Defy Composite 2"),
        ("Carbon racefiets Giant Defy Composite, Ultegra 10 speed", "Giant Defy Composite (uitvoering onbekend)"),
        ("Giant Defy Advanced 2 disc 105 maat M/L", "Giant Defy Advanced"),
        ("Giant Defy Advanced SL 0 Dura-Ace", "Giant Defy Advanced SL"),
        ("Giant Defy 1 aluminium 105", "Giant Defy 0-5 (aluminium)"),
        ("Giant Defy Aluxx mt L Shimano 105", "Giant Defy 0-5 (aluminium)"),
        ("Giant Defy Advanced Pro 1 ML Nieuw", "Giant Defy Advanced"),
        ("Canyon Endurace CF SL Disc 8.0 maat M", "Canyon Endurace CF SL(X) Disc"),
        ("Canyon Endurace AL 7.0", "Canyon Endurace (overig)"),
        ("Specialized Roubaix Sport 2018", "Specialized Roubaix"),
        ("Trek Domane SL5 disc", "Trek Domane"),
    ]

    def test_titles_land_on_the_expected_model(self):
        reference = mp.load_reference_data(BIKES)
        for title, expected in self.CASES:
            with self.subTest(title=title):
                self.assertEqual(first_label(reference, title), expected)

    # Titles from lijsten/zonder_referentie.txt (September 2026): the families
    # that most often went unrecognised. Mostly about the split rows, where a
    # material rides along and the order decides which one wins.
    FAMILY_CASES = [
        ("Racefiets Giant TCR Advanced SL maat M/L carbon", "Giant TCR Advanced"),
        ("Giant TCR racefiets – opknapper / projectfiets", "Giant TCR (overig)"),
        ("Trek Emonda ALR5", "Trek Émonda ALR"),
        ("Trek emonda Sl-6 maat 58.", "Trek Émonda (overig)"),
        ("Trek Madone 2.1 racefiets", "Trek Madone 2.1-2.5"),
        ("Te koop Trek Madone 5.2 SL racefiets", "Trek Madone (overig)"),
        ("Trek 1.2 Alpha racefiets - Maat 56 - Shimano Tiagra/Sora", "Trek 1-/2-serie (Alpha)"),
        ("Racefiets, Trek 2,1 alpha", "Trek 1-/2-serie (Alpha)"),
        ("Trek Domane 2.3 compact", "Trek Domane"),
        ("Cube Attain GTC SL 105", "Cube Attain GTC"),
        ("Cube Attain SL | 105 | Maat 58", "Cube Attain (overig)"),
        ("Cannondale Synapse Women's Carbon Shimano 105 (ZGAN)", "Cannondale Synapse Carbon"),
        ("Nette cannondale synapse", "Cannondale Synapse (overig)"),
        ("Cannondale CAAD 10 Ultegra - 54cm", "Cannondale CAAD / Optimo"),
        ("Specialized S-Works Tarmac SL8 2025 | 54cm", "Specialized Tarmac"),
        ("Sensa Terentino SL perfecte staat maat 58", "Sensa Trentino"),
        ("Merida Sculptura 300 Racefiets Shimano Tiagra", "Merida Scultura"),
        ("Koga Miyata Racefiets PA46140 HardLite FM2 uit 1987", "Koga-Miyata (merknaam tot 2010)"),
        ("Vintage Koga myata Prologue", "Koga-Miyata (merknaam tot 2010)"),
        ("Koga Kimera | Ultegra | Maat 56", "Koga Kimera"),
        ("Gazelle Champion Mondial (55) MOET WEG !!", "Gazelle Champion Mondial"),
        ("Fuji Roubaix One.1 racefiets", "Fuji Roubaix"),
    ]

    def test_common_families_land_on_their_row(self):
        reference = mp.load_reference_data(BIKES)
        for title, expected in self.FAMILY_CASES:
            with self.subTest(title=title):
                self.assertEqual(first_label(reference, title), expected)

    def test_look_alikes_from_other_brands_stay_unmatched(self):
        # Same model word, different bike: these must not borrow a row (and
        # with it a frame material) from another brand.
        reference = mp.load_reference_data(BIKES)
        for title in (
            "Batavus Champion racefiets - Vintage",
            "Giant Peloton 8400 racefiets - 59 cm frame",
            "Eddy Merckx San Remo 76 Carbon – Ultegra",
            "Racefiets met nieuwe banden, rijdt soepel over tarmac",
        ):
            with self.subTest(title=title):
                self.assertIsNone(first_label(reference, title))

    def test_family_rows_carry_no_original_price(self):
        # A family spans trims and years with very different prices; one
        # number would feed the dealscore a made-up nieuwprijs.
        with open(BIKES, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for row in rows[10:]:
            with self.subTest(label=row["label"]):
                self.assertEqual(row["original_price_eur"], "")

    def test_a_defy_advanced_is_never_read_as_a_composite(self):
        # §4 of the plan: Advanced is a higher carbon grade and pulls the
        # valuation of a Composite too high if it ends up among its comps.
        reference = mp.load_reference_data(BIKES)
        self.assertNotIn(
            "Composite", first_label(reference, "Giant Defy Advanced 1 Ultegra 2013")
        )

    def test_only_the_own_bike_row_is_marked_as_the_baseline(self):
        baseline = [r["label"] for r in mp.load_reference_data(BIKES) if "Baseline" in r["score"]]
        self.assertEqual(baseline, ["Giant Defy Composite (uitvoering onbekend)"])


class AccessoryTitleMatchingTest(unittest.TestCase):
    CASES = [
        ("Wahoo Elemnt Roam V2 fietscomputer", "Wahoo Elemnt Roam v2"),
        ("Wahoo Elemnt Roam 3 nieuw in doos", "Wahoo Elemnt Roam 3"),
        ("Wahoo Elemnt Roam met stuurhouder", "Wahoo Elemnt Roam (v1, 2019)"),
        ("Wahoo Elemnt Roam 2023 gekocht", "Wahoo Elemnt Roam (v1, 2019)"),
        ("Wahoo Elemnt Bolt v2", "Wahoo Elemnt Bolt v2 (2021)"),
        ("Wahoo Elemnt Bolt", "Wahoo Elemnt Bolt (v1)"),
        ("Garmin Edge 540 Solar", "Garmin Edge 540 Solar"),
        ("Garmin Edge 540 bundel", "Garmin Edge 540"),
        ("Garmin Edge 840 Solar", "Garmin Edge 840 Solar"),
        ("Garmin Edge 840", "Garmin Edge 840"),
        ("Garmin Edge 530 + sensoren", "Garmin Edge 530"),
        ("Garmin Edge 830", "Garmin Edge 830"),
        ("Garmin Edge 1030", "Garmin Edge 1030"),
        ("Favero Assioma Duo powermeter pedalen", "Favero Assioma Duo"),
        ("Assioma UNO", "Favero Assioma Uno"),
        ("Garmin Rally RS200 vermogensmeter", "Garmin Rally (RS/XC/RK 100/200)"),
    ]

    def test_titles_land_on_the_expected_model(self):
        reference = mp.load_reference_data(ACCESSORIES)
        for title, expected in self.CASES:
            with self.subTest(title=title):
                self.assertEqual(first_label(reference, title), expected)

    def test_a_1030_plus_does_not_get_the_1030s_price(self):
        # Different device, different price; there is no researched row for
        # the Plus, so it must stay unmatched rather than borrow one.
        reference = mp.load_reference_data(ACCESSORIES)
        self.assertIsNone(first_label(reference, "Garmin Edge 1030 Plus"))


if __name__ == "__main__":
    unittest.main()
