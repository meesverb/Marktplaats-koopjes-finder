"""reference_bike_catalog.csv — one row per brand/model/model year.

Unlike reference_bikes.csv this file is not matched against listing titles, so
there is no first-match-wins to guard. What can go wrong silently is the data
itself: a price without the page it came from, a model year the source never
stated, a Spanish catalogue price passed off as a Dutch one. That's what these
tests pin down.
"""
import csv
import re
import unittest

from helpers import repo_file

CATALOG = repo_file("reference_bike_catalog.csv")

COLUMNS = [
    "brand", "model", "model_year", "seen_date", "category", "frame_material", "groupset", "electronic",
    "speeds", "brake_type", "weight_kg", "new_price", "currency", "market", "price_basis", "specs",
    "source_url", "spec_source_url",
]


def load():
    with open(CATALOG, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


class CatalogShapeTest(unittest.TestCase):
    def setUp(self):
        self.header, self.rows = load()

    def test_header_is_stable(self):
        # Other code and the owner's own spreadsheets read these columns by name.
        self.assertEqual(self.header, COLUMNS)

    def test_the_four_brands_asked_for_are_all_there(self):
        brands = {r["brand"] for r in self.rows}
        for brand in ("Giant", "Trek", "Cube", "Sensa"):
            with self.subTest(brand=brand):
                self.assertIn(brand, brands)

    def test_no_duplicate_rows(self):
        seen = set()
        for r in self.rows:
            key = (r["brand"], r["model"].lower(), r["model_year"], r["seen_date"], r["market"], r["new_price"])
            with self.subTest(row=key):
                self.assertNotIn(key, seen)
            seen.add(key)


class CatalogProvenanceTest(unittest.TestCase):
    def setUp(self):
        _, self.rows = load()

    def test_every_row_has_a_source_page(self):
        for r in self.rows:
            with self.subTest(model=r["model"], year=r["model_year"]):
                self.assertTrue(r["brand"] and r["model"])
                self.assertTrue(r["source_url"].startswith("https://"))
                if r["spec_source_url"]:
                    self.assertTrue(r["spec_source_url"].startswith("https://"))

    def test_a_price_always_says_where_and_in_which_market(self):
        # A Spanish catalogue price is a real euro price but not a Dutch one;
        # the market column is what keeps the two apart in the valuation.
        for r in self.rows:
            with self.subTest(model=r["model"], year=r["model_year"]):
                if r["new_price"]:
                    self.assertEqual(r["currency"], "EUR")
                    self.assertIn(r["market"], ("NL", "ES"))
                    self.assertTrue(r["price_basis"])
                else:
                    self.assertEqual((r["currency"], r["market"], r["price_basis"]), ("", "", ""))

    def test_prices_are_plausible_for_a_complete_bike(self):
        for r in self.rows:
            if r["new_price"]:
                with self.subTest(model=r["model"], year=r["model_year"]):
                    self.assertTrue(150 <= float(r["new_price"]) <= 20000, r["new_price"])

    def test_a_year_is_either_stated_by_the_source_or_replaced_by_the_date_seen(self):
        # Sensa pages carry no model year. The capture date goes in seen_date,
        # it is never promoted to a model year.
        for r in self.rows:
            with self.subTest(model=r["model"]):
                self.assertTrue(r["model_year"] or r["seen_date"])
                if r["model_year"]:
                    self.assertRegex(r["model_year"], r"^20(0[89]|1\d|2[0-7])$")
                if r["seen_date"]:
                    self.assertRegex(r["seen_date"], r"^20\d\d-\d\d-\d\d$")

    def test_sensa_never_gets_a_model_year(self):
        for r in self.rows:
            if r["brand"] == "Sensa":
                with self.subTest(model=r["model"]):
                    self.assertEqual(r["model_year"], "")


class CatalogDerivedColumnsTest(unittest.TestCase):
    def setUp(self):
        _, self.rows = load()

    def test_derived_columns_use_a_fixed_vocabulary(self):
        for r in self.rows:
            with self.subTest(model=r["model"], year=r["model_year"]):
                self.assertIn(r["frame_material"], ("", "carbon", "aluminium", "staal", "titanium"))
                self.assertIn(r["brake_type"], ("", "velgrem", "schijfrem"))
                self.assertIn(r["electronic"], ("", "ja"))
                if r["speeds"]:
                    self.assertTrue(7 <= int(r["speeds"]) <= 13)
                if r["weight_kg"]:
                    self.assertTrue(4 <= float(r["weight_kg"]) <= 20, r["weight_kg"])

    def test_derived_values_come_from_the_row_itself(self):
        # The groupset is read from the spec text of the same row; a groupset
        # that appears nowhere in that row's specs or name was made up.
        words = {
            "Shimano Dura-Ace": r"dura[\s-]?ace", "Shimano Ultegra": r"ultegra", "Shimano 105": r"\b105\b",
            "Shimano Tiagra": r"tiagra", "Shimano Sora": r"sora", "Shimano Claris": r"claris",
        }
        for r in self.rows:
            pattern = words.get(r["groupset"])
            if pattern:
                with self.subTest(model=r["model"], year=r["model_year"]):
                    self.assertRegex(r["specs"] + " " + r["model"], re.compile(pattern, re.I))

    def test_disc_in_the_model_name_means_disc_brakes(self):
        for r in self.rows:
            if re.search(r"(?i)\bdisc\b", r["model"]):
                with self.subTest(model=r["model"], year=r["model_year"]):
                    self.assertEqual(r["brake_type"], "schijfrem")


class CatalogSpotCheckTest(unittest.TestCase):
    """A handful of rows checked by hand against their source page."""

    def setUp(self):
        _, rows = load()
        self.by = {(r["brand"], r["model"], r["model_year"], r["market"]): r for r in rows}

    def test_known_rows(self):
        cases = [
            # (brand, model, year, market, price, source fragment)
            ("Giant", "TCR Advanced 1", "2016", "NL", "1999.00", "giant-bicycles.com"),
            ("Giant", "Defy Advanced 2", "2020", "NL", "2099.00", "giant-bicycles.com/nl/"),
            ("Trek", "Émonda SLR 10", "2016", "NL", "11999.00", "trekbikes.com"),
            ("Cube", "AGREE GTC", "2014", "ES", "1380.00", "bikezona.com"),
        ]
        for brand, model, year, market, price, src in cases:
            with self.subTest(model=model, year=year):
                r = self.by.get((brand, model, year, market))
                self.assertIsNotNone(r)
                self.assertEqual(r["new_price"], price)
                self.assertIn(src, r["source_url"])


if __name__ == "__main__":
    unittest.main()
