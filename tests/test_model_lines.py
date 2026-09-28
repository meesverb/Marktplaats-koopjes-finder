"""model_lines.py: brede herkenning op merk + modellijn uit de catalogus, en
dat een run alles wat hij crawlt bewaart, niet alleen wat door de filters komt.
"""
import contextlib
import csv
import io
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import close_databases_before_cleanup, make_listing, mp, repo_file

import db
import model_lines


class MatcherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = model_lines.load_lines(repo_file("reference_bike_catalog.csv"))
        cls.matcher = model_lines.LineMatcher(cls.lines)

    def label(self, title, description=""):
        line = self.matcher.match(title, description)
        return line.label if line else None

    def test_titles_from_a_real_run_get_their_line(self):
        # Titels uit het rapport van 28-09-2026 die toen nergens aan
        # gekoppeld waren.
        cases = {
            "Giant TCR": "Giant TCR",
            "Racefiets Trek Emonda SL6 Carbon Ultegra maat 58": "Trek Émonda",
            "Canyon Ultimate CF SLX": "Canyon Ultimate",
            "Cervélo S3 racefiets - Ultegra 11 speed mechanisch": "Cervélo S3",
            "Racefiets Cannondale CAAD10 maat 56 Shimano Ultegra 11-speed": "Cannondale CAAD10",
            "Scott Addict 40 racefiets te koop": "Scott Addict",
            "Focus Cayo Wielrenfiets - Carbon Frame - Campagnolo Athena": "Focus Cayo",
            "Te koop: Racefiets Merida ride 7000 cabon disk (Maat 56)": "Merida Ride",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(self.label(title), expected)

    def test_spelling_variants_land_on_the_same_line(self):
        self.assertEqual(self.label("Cervelo S3"), self.label("Cervélo S3"))
        self.assertEqual(self.label("Cannondale CAAD 10"), "Cannondale CAAD10")
        self.assertEqual(self.label("cannondale caad-10 105"), "Cannondale CAAD10")

    def test_s_works_stands_for_specialized(self):
        self.assertEqual(self.label("S-Works Tarmac SL7 Dura Ace Di2"), "Specialized Tarmac")

    def test_the_longest_line_wins(self):
        # CAAD en CAAD10 zijn allebei lijnen in de catalogus.
        self.assertEqual(self.label("Cannondale CAAD10"), "Cannondale CAAD10")

    def test_a_line_needs_its_own_brand(self):
        # Zonder merk geen lijn: Ventoux en Stelvio zijn ook Columbus- en
        # Concorde-fietsen, niet alleen Stevens.
        self.assertIsNone(self.label("Columbus Ventoux Racefiets"))
        self.assertIsNone(self.label("Concorde Stelvio racefiets"))
        self.assertIsNone(self.label("Emonda SL6"))
        # Een lijn van een ander merk telt niet ("Trek" + Giant-lijn).
        self.assertIsNone(self.label("Trek giant sensa wielrenfiets"))

    def test_a_brand_alone_is_no_line(self):
        self.assertIsNone(self.label("Racefiets Giant"))
        self.assertIsNone(self.label("Giant Pro racefiets"))

    def test_a_size_is_not_a_line(self):
        self.assertIsNone(self.label("Felt racefiets 56"))

    def test_the_description_only_counts_with_brand_and_line_together(self):
        self.assertEqual(self.label("Racefiets", "Mooie Giant TCR, weinig gereden"), "Giant TCR")
        self.assertIsNone(self.label("Racefiets", "Giant fiets, vergelijkbaar met een TCR"))

    def test_the_title_goes_before_the_description(self):
        self.assertEqual(
            self.label("Giant Defy 2", "Vorige fiets was een Trek Madone"), "Giant Defy"
        )

    def test_every_stored_pattern_finds_its_own_line(self):
        # Het patroon komt in `model` terecht; het moet op zichzelf kloppen.
        for line in self.lines:
            with self.subTest(label=line.label):
                self.assertRegex(model_lines.fold(line.label), re.compile(line.pattern))

    def test_no_market_facts_in_a_line(self):
        # Alleen een naam: nieuwprijs, jaar en materiaal staan per modeljaar
        # in de catalogus en gelden niet voor een hele lijn.
        self.assertEqual(
            set(model_lines.ModelLine.__dataclass_fields__), {"brand", "line", "label", "pattern"}
        )

    def test_a_missing_catalogue_recognises_nothing(self):
        self.assertEqual(model_lines.load_lines("bestaat-niet.csv"), [])


class ApplyLinesTest(unittest.TestCase):
    def setUp(self):
        self.matcher = model_lines.LineMatcher(
            model_lines.load_lines(repo_file("reference_bike_catalog.csv"))
        )

    def test_a_reference_label_is_kept_and_the_line_is_added(self):
        listing = make_listing(item_id="a", title="Giant Defy Composite 1", ref_label="Giant Defy Composite 1")
        matches = {"a": ["Defy.{0,20}Composite.{0,3}1\\b"]}
        added = model_lines.apply_lines([listing], self.matcher, matches)
        self.assertEqual(added, 0)
        self.assertEqual(listing.ref_label, "Giant Defy Composite 1")
        self.assertEqual(len(matches["a"]), 2)

    def test_an_unlabelled_listing_gets_its_line(self):
        listing = make_listing(item_id="b", title="Giant TCR Advanced")
        matches = {}
        self.assertEqual(model_lines.apply_lines([listing], self.matcher, matches), 1)
        self.assertEqual(listing.ref_label, "Giant TCR")
        self.assertIn("b", matches)

    def test_only_a_bike_reference_file_switches_lines_on(self):
        self.assertTrue(model_lines.is_bike_reference(mp.load_reference_data(repo_file("reference_bikes.csv"))))
        self.assertFalse(model_lines.is_bike_reference(mp.load_reference_data(repo_file("reference_prices.csv"))))
        self.assertFalse(
            model_lines.is_bike_reference(mp.load_reference_data(repo_file("reference_bike_accessories.csv")))
        )


class RunKeepsEverythingTest(unittest.TestCase):
    """Een run bewaart alles wat hij crawlt; de filters gaan alleen over het
    rapport. Voorheen verdween een fiets boven --max-price of in een andere
    maat spoorloos, en bouwde zijn model dus nooit geschiedenis op."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        close_databases_before_cleanup(self)

    def path(self, name):
        return str(self.tmp / name)

    def run_query(self, listings, extra_argv, near_complete=False):
        def fake_collect(query, pages, delay, **crawl_options):
            return mp.CrawlResult(listings, complete=False, note="", near_complete=near_complete)

        argv = [
            "--query", "test", "--no-html", "--no-log", "--no-notify-better",
            "--open-browser", "never", "--delay", "0",
            "--history-file", self.path("history.json"),
            "--reference-file", repo_file("reference_bikes.csv"),
            "--price-history-file", self.path("price_history.csv"),
            "--db", self.path("koopjes.db"),
        ] + extra_argv
        args = mp.parse_args(argv)
        with mock.patch.object(mp, "collect_listings", fake_collect), mock.patch.object(
            mp, "enrich_bid_listings", lambda *a, **k: None
        ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            mp.run_for_query(args, "test", False)

    def listings(self):
        return [
            make_listing(item_id="goedkoop", title="Giant TCR", price_eur=400.0),
            make_listing(item_id="duur", title="Trek Emonda SL6", price_eur=1500.0),
        ]

    def test_a_listing_above_max_price_still_lands_in_the_database(self):
        self.run_query(self.listings(), ["--max-price", "900"])
        conn = db.connect(self.path("koopjes.db"))
        ids = {r["item_id"] for r in conn.execute("SELECT item_id FROM listing")}
        self.assertEqual(ids, {"goedkoop", "duur"})
        linked = conn.execute(
            "SELECT m.model FROM listing_model lm JOIN model m ON m.id = lm.model_id "
            "WHERE lm.listing_id = 'duur'"
        ).fetchall()
        self.assertEqual([r["model"] for r in linked], ["Trek Émonda"])

    def test_a_listing_above_max_price_still_counts_for_its_line(self):
        self.run_query(self.listings(), ["--max-price", "900"])
        with open(self.path("price_history.csv"), encoding="utf-8") as f:
            rows = {r["item_id"]: r["ref_label"] for r in csv.DictReader(f)}
        self.assertEqual(rows, {"goedkoop": "Giant TCR", "duur": "Trek Émonda"})

    def test_the_report_still_sticks_to_the_filters(self):
        self.run_query(self.listings(), ["--max-price", "900", "--output", self.path("out.csv")])
        with open(self.path("out.csv"), encoding="utf-8-sig") as f:
            ids = [r["item_id"] for r in csv.DictReader(f)]
        self.assertEqual(ids, ["goedkoop"])

    def test_near_complete_survives_the_filters(self):
        # Werd na het filteren van een gewone lijst gelezen en was dus altijd
        # False zodra er een prijs- of maatfilter aan stond.
        with mock.patch.object(mp, "sync_database") as sync:
            self.run_query(self.listings(), ["--max-price", "900"], near_complete=True)
        self.assertTrue(sync.call_args.kwargs["crawl_near_complete"])


if __name__ == "__main__":
    unittest.main()
