"""catalog_match.py: van lijn naar uitvoering en modeljaar, alleen op wat de
advertentie zelf zegt, en wat daarvan in koopjes.db terechtkomt."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import close_databases_before_cleanup, make_listing, mp, repo_file

import catalog_match as cm
import db
import model_lines as ml


def row(model, year, market="ES", groupset="", price=None, brand="Giant"):
    return cm.CatalogRow(
        brand=brand, model=model, year=year, market=market, groupset=groupset,
        frame_material="carbon", brake_type="", electronic="", new_price=price,
        currency="EUR", price_basis="", source_url="https://example.invalid/" + model,
    )


# Een kleine, zelfgemaakte catalogus: de tests gaan over de regels, niet over
# wat er toevallig in reference_bike_catalog.csv staat.
ROWS = [
    row("TCR ADVANCED 2", 2016, "NL", "Shimano 105", 1599.0),
    row("TCR ADVANCED 2", 2019, "ES", "Shimano 105", 1699.0),
    row("TCR ADVANCED 2 DISC", 2019, "ES", "Shimano 105"),
    row("TCR ADVANCED PRO 1", 2019, "NL", "Shimano Ultegra", 3099.0),
    row("TCR COMPOSITE 1", 2010, "ES"),
]
LINES = [ml.ModelLine("Giant", "tcr", "Giant TCR", "tcr")]


class VariantMatcherTest(unittest.TestCase):
    def setUp(self):
        self.matcher = cm.VariantMatcher(LINES, ROWS)

    def match(self, title, text="", year=None):
        return self.matcher.match("Giant TCR", title, text, year)

    def test_trim_and_year_from_the_title(self):
        found = self.match("Giant TCR Advanced 2 2016 maat M")
        self.assertEqual(found.label, "Giant TCR Advanced 2")
        self.assertEqual((found.year, found.year_source), (2016, "titel"))
        self.assertEqual(found.best_row.market, "NL")
        self.assertIn("nieuw €1599 (NL)", found.describe())

    def test_the_longest_trim_in_the_text_wins(self):
        self.assertEqual(self.match("Giant TCR Advanced 2 Disc").label, "Giant TCR Advanced 2 Disc")
        self.assertEqual(self.match("Giant TCR Advanced Pro 1").label, "Giant TCR Advanced Pro 1")

    def test_a_trim_written_without_spaces(self):
        self.assertEqual(self.match("Giant TCR Advanced2").label, "Giant TCR Advanced 2")

    def test_a_trailing_point_zero_may_be_left_out(self):
        matcher = cm.VariantMatcher(
            [ml.ModelLine("Canyon", "aeroad", "Canyon Aeroad", "aeroad")],
            [row("AEROAD CF SLX 8.0 DI2", 2015, brand="Canyon")],
        )
        found = matcher.match("Canyon Aeroad", "Canyon Aeroad CF SLX 8 Di2 2015", "")
        self.assertEqual(found.label, "Canyon Aeroad CF SLX 8.0 DI2")
        self.assertEqual(found.year, 2015)

    def test_the_line_alone_is_no_trim(self):
        self.assertIsNone(self.match("Giant TCR racefiets"))

    def test_words_that_are_not_next_to_each_other_are_no_trim(self):
        self.assertIsNone(self.match("Giant TCR, 2 wielsets, advanced shifting"))

    def test_the_description_names_the_trim_and_a_labelled_year(self):
        found = self.match("Racefiets Giant TCR", "Giant TCR Advanced Pro 1, bouwjaar 2019", "2019")
        self.assertEqual(found.label, "Giant TCR Advanced Pro 1")
        self.assertEqual((found.year, found.year_source), (2019, "tekst"))
        self.assertEqual(found.best_row.groupset, "Shimano Ultegra")

    def test_no_year_means_no_year_guessed(self):
        found = self.match("Giant TCR Advanced 2")
        self.assertIsNone(found.year)
        self.assertEqual(found.exact, [])
        self.assertIsNone(found.best_row)
        self.assertEqual(found.variant.years, [2016, 2019])
        self.assertIn("2016–2019", found.describe())

    def test_a_year_the_catalogue_doesnt_have_is_said_so(self):
        found = self.match("Giant TCR Advanced 2 2021")
        self.assertEqual(found.exact, [])
        self.assertIn("niet uit 2021", found.describe())
        self.assertIn("niet in catalogus", found.matched_on)

    def test_a_spanish_price_says_it_is_spanish(self):
        found = self.match("Giant TCR Advanced 2 2019")
        self.assertIn("(ES)", found.describe())

    def test_another_line_gets_nothing(self):
        self.assertIsNone(self.matcher.match("Giant Defy", "Giant Defy Advanced 2", ""))


class TitleYearTest(unittest.TestCase):
    def test_years(self):
        today = date(2026, 9, 28)
        cases = {
            "Trek Domane SL5 disk 2019 maat 54": 2019,
            "Cube Attain Pro 2026 - Zo goed als nieuw": 2026,
            "Giant TCR (2015)": 2015,
            "TCR 2016, maat M": 2016,
            "Trek 2018-2020": None,
            "Racefiets €2000": None,
            "Nog maar 2000 km gereden": None,
            "Emonda 2031": None,
            "Nieuw model 2027": 2027,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(cm.title_year(title, today), expected)


class RealCatalogueTest(unittest.TestCase):
    def test_every_trim_pattern_is_a_valid_regex_that_finds_its_own_label(self):
        lines = ml.load_lines(repo_file("reference_bike_catalog.csv"))
        matcher = cm.VariantMatcher(lines, cm.load_catalog(repo_file("reference_bike_catalog.csv")))
        import re

        variants = matcher.variants()
        self.assertGreater(len(variants), 1000)
        for variant in variants[:300]:
            with self.subTest(label=variant.label):
                self.assertRegex(ml.fold(variant.label), re.compile(variant.pattern))


class ApplyAndStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        close_databases_before_cleanup(self)
        self.conn = db.connect(str(Path(self._tmp.name) / "koopjes.db"))
        self.matcher = cm.VariantMatcher(LINES, ROWS)

    def listing(self, item_id, title, **kw):
        listing = make_listing(item_id=item_id, title=title, **kw)
        listing.model_line = "Giant TCR"
        listing.ref_label = "Giant TCR"
        return listing

    def test_a_line_label_becomes_the_trim(self):
        listing = self.listing("a", "Giant TCR Advanced 2 2016")
        mp.apply_catalog_variants([listing], self.matcher)
        self.assertEqual(listing.ref_label, "Giant TCR Advanced 2")
        self.assertIn("Catalogus 2016", listing.ref_specs)

    def test_a_reference_row_keeps_its_label(self):
        listing = self.listing("a", "Giant TCR Advanced 2 2016")
        listing.ref_label, listing.ref_specs = "Onderzochte rij", "met de hand"
        matches = mp.apply_catalog_variants([listing], self.matcher)
        self.assertEqual((listing.ref_label, listing.ref_specs), ("Onderzochte rij", "met de hand"))
        self.assertEqual(matches["a"].label, "Giant TCR Advanced 2")

    def test_the_full_description_is_read_when_it_is_there(self):
        listing = self.listing("a", "Racefiets Giant TCR")
        listing.detail_text = "Te koop mijn Giant TCR Advanced Pro 1 uit 2019."
        found = mp.apply_catalog_variants([listing], self.matcher)["a"]
        self.assertEqual(found.label, "Giant TCR Advanced Pro 1")
        self.assertEqual(found.year, 2019)

    def links(self, item_id):
        return self.conn.execute(
            "SELECT m.model, m.year_from, m.year_to, lm.matched_on, lm.confidence FROM listing_model lm "
            "JOIN model m ON m.id = lm.model_id WHERE lm.listing_id = ?", (item_id,)
        ).fetchall()

    def test_stored_with_how_sure_it_is(self):
        db.sync_listings(self.conn, "q", [self.listing("a", "x"), self.listing("b", "y")], "2026-09-28")
        exact = self.listing("a", "Giant TCR Advanced 2 2016")
        vague = self.listing("b", "Giant TCR Advanced 2")
        matches = mp.apply_catalog_variants([exact, vague], self.matcher)
        db.sync_catalog_matches(self.conn, matches)

        (a,) = self.links("a")
        self.assertEqual(a["model"], "Giant TCR Advanced 2")
        self.assertEqual((a["year_from"], a["year_to"]), (2016, 2019))
        self.assertIn("jaar 2016", a["matched_on"])
        self.assertGreater(a["confidence"], self.links("b")[0]["confidence"])
        specs = db.read_listing_specs(self.conn)
        self.assertEqual(specs["a"]["catalog_year"], "2016")
        self.assertEqual(specs["a"]["catalog_market"], "NL")
        self.assertNotIn("catalog_year", specs["b"])

    def test_a_better_answer_replaces_the_old_link(self):
        db.sync_listings(self.conn, "q", [self.listing("a", "x")], "2026-09-28")
        first = self.listing("a", "Giant TCR Advanced 2")
        db.sync_catalog_matches(self.conn, mp.apply_catalog_variants([first], self.matcher))
        # Een latere run heeft de volledige omschrijving.
        later = self.listing("a", "Giant TCR Advanced 2")
        later.detail_text = "Het is een Giant TCR Advanced 2 Disc"
        db.sync_catalog_matches(self.conn, mp.apply_catalog_variants([later], self.matcher))
        self.assertEqual([r["model"] for r in self.links("a")], ["Giant TCR Advanced 2 Disc"])

    def test_a_listing_without_a_trim_loses_an_old_one(self):
        db.sync_listings(self.conn, "q", [self.listing("a", "x")], "2026-09-28")
        db.sync_catalog_matches(
            self.conn, mp.apply_catalog_variants([self.listing("a", "Giant TCR Advanced 2")], self.matcher)
        )
        db.sync_catalog_matches(
            self.conn, mp.apply_catalog_variants([self.listing("a", "Giant TCR")], self.matcher)
        )
        self.assertEqual(self.links("a"), [])


class MarketFallbackTest(unittest.TestCase):
    def test_a_trim_with_too_few_sightings_uses_its_line(self):
        listing = make_listing(ref_label="Giant TCR Advanced 2")
        listing.model_line = "Giant TCR"
        listing.catalog_label = listing.ref_label
        stats = {
            listing.ref_label: {"count": 1, "mean": 900.0, "median": 900.0},
            "Giant TCR": {"count": 12, "mean": 700.0, "median": 650.0},
        }
        mp.apply_reference_market_stats([listing], stats)
        self.assertEqual((listing.ref_market_avg, listing.ref_market_count), (700.0, 12))
        self.assertEqual(listing.ref_market_label, "Giant TCR")

    def test_a_trim_with_enough_sightings_uses_its_own(self):
        listing = make_listing(ref_label="Giant TCR Advanced 2")
        listing.model_line = "Giant TCR"
        stats = {
            "Giant TCR Advanced 2": {"count": 3, "mean": 900.0, "median": 900.0},
            "Giant TCR": {"count": 12, "mean": 700.0, "median": 650.0},
        }
        listing.catalog_label = "Giant TCR Advanced 2"
        mp.apply_reference_market_stats([listing], stats)
        self.assertEqual(listing.ref_market_avg, 900.0)
        self.assertEqual(listing.ref_market_label, "")

    def test_a_reference_row_never_falls_back_to_its_line(self):
        # Onder "Giant Defy" vallen ook aluminium Defy's; de gemiddelde prijs
        # daarvan zegt niets over een carbon Defy Composite.
        listing = make_listing(ref_label="Giant Defy Composite (uitvoering onbekend)")
        listing.model_line = "Giant Defy"
        stats = {
            "Giant Defy Composite (uitvoering onbekend)": {"count": 1, "mean": 600.0, "median": 600.0},
            "Giant Defy": {"count": 40, "mean": 450.0, "median": 400.0},
        }
        mp.apply_reference_market_stats([listing], stats)
        self.assertEqual(listing.ref_market_avg, 600.0)
        self.assertEqual(listing.ref_market_label, "")


if __name__ == "__main__":
    unittest.main()
