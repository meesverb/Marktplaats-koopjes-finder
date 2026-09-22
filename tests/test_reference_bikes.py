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
