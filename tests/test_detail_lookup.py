"""--detail-lookup: the listing page's full description and "Kenmerken" for
the few listings that could be an upgrade.

The search results stop at 200 characters, and that's where the groupset
usually is. Checked on the real site (27-09-2026): a Canyon Ultimate CF SLX
scored 38 against 51 for the owner's bike on its snippet; its page says
"Groepset: Ultegra 11 speed", velgrem, carbon, 53 tot 57 cm. The page below
is written in the same markup, with made-up text.
"""
import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import make_listing, mp, repo_file

import db
import report
import scoring as sc
import upgrade as up

PAGE = """<html><head><meta name="description" content="Nette racefiets"/></head><body>
<div class="Description-module-description"><div data-collapsable="description">Nette racefiets, weinig gereden.<br /><br />Groepset: Ultegra 11 speed 52/36<br />Cassette: Dura Ace 12/30<br />Garmin houder &amp; bel<br />Velgremmen, carbon wielen</div></div>
<div class="Attributes-module-root"><h2 class="Attributes-module-title">Kenmerken</h2><div class="Attributes-module-list">
<div class="Attributes-module-item"><div class="Attributes-module-label">Conditie</div><div class="Attributes-module-value">Gebruikt</div></div>
<div class="Attributes-module-item"><div class="Attributes-module-label">Rem</div><div class="Attributes-module-value">Velgrem</div></div>
<div class="Attributes-module-item"><div class="Attributes-module-label">Materiaal</div><div class="Attributes-module-value"><a class="hz-Link" href="/l/x/">Carbon</a></div></div>
<div class="Attributes-module-item"><div class="Attributes-module-label">Framehoogte</div><div class="Attributes-module-value">53 tot 57 cm</div></div>
</div></div></body></html>"""

ROAD_BIKE_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/m{}-racefiets"


class ParseListingPageTest(unittest.TestCase):
    def test_full_description_and_attributes(self):
        text, attributes = mp.parse_listing_page(PAGE)
        self.assertIn("Groepset: Ultegra 11 speed 52/36\nCassette: Dura Ace", text)
        self.assertIn("Garmin houder & bel", text)
        self.assertEqual(attributes["framehoogte"], "53 tot 57 cm")
        self.assertEqual(mp.page_specs(attributes), {"frame_material": "carbon", "brake_type": "velrem"})

    def test_a_page_without_the_description_block_is_none(self):
        self.assertIsNone(mp.parse_listing_page("<html>verificatie</html>"))

    def test_the_labelled_groupset_line_wins_over_a_higher_cassette(self):
        text, _ = mp.parse_listing_page(PAGE)
        self.assertEqual(mp.detect_groupset(text), ("Shimano Ultegra", 5))
        # Without a label the old rule stands: highest tier mentioned.
        self.assertEqual(mp.detect_groupset("Ultegra met Dura-Ace cassette")[1], 6)

    def test_a_computer_mount_is_not_a_computer(self):
        for text in ("Garmin houder", "garmin-mount", "Wahoo Kickr trainer", "Garmin Varia radar"):
            with self.subTest(text=text):
                self.assertNotIn("has_computer", mp.extract_specs(text))
        for text in ("Garmin Edge 530 erbij", "met Wahoo Elemnt", "inclusief Garmin"):
            with self.subTest(text=text):
                self.assertEqual(mp.extract_specs(text).get("has_computer"), "1")


def budgets(amount=640.0):
    return up.budgets_from_valuation(amount - 250, extra_budget_eur=250)


class DetailLookupTargetsTest(unittest.TestCase):
    def setUp(self):
        self.config = sc.load_config()

    def targets(self, listings, **kwargs):
        return up.detail_lookup_targets(
            listings, budgets=budgets(), target_size_cm=56, config=self.config, **kwargs
        )

    def test_only_bikes_that_could_be_a_candidate(self):
        listings = [
            make_listing(item_id="ok", price_eur=500.0, url=ROAD_BIKE_URL.format(1)),
            make_listing(item_id="duur", price_eur=2500.0, url=ROAD_BIKE_URL.format(2)),
            make_listing(item_id="klein", price_eur=500.0, frame_height="47 tot 50 cm",
                         url=ROAD_BIKE_URL.format(3)),
            make_listing(item_id="onderdeel", price_eur=100.0,
                         url="https://www.marktplaats.nl/v/fietsen-en-brommers/fietsonderdelen/m4-crank"),
            make_listing(item_id="al", price_eur=500.0, url=ROAD_BIKE_URL.format(5),
                         detail_text="al opgehaald"),
            make_listing(item_id="geenprijs", price_eur=None, price_type="FAST_BID",
                         price_is_bid=True, url=ROAD_BIKE_URL.format(6)),
        ]
        self.assertEqual([l.item_id for l in self.targets(listings)], ["ok"])

    def test_the_most_promising_first_and_no_more_than_the_limit(self):
        listings = [
            make_listing(item_id="kaal", title="Racefiets", price_eur=400.0, url=ROAD_BIKE_URL.format(1)),
            make_listing(item_id="ultegra", title="Carbon racefiets Ultegra", price_eur=400.0,
                         groupset="Shimano Ultegra", groupset_tier=5, url=ROAD_BIKE_URL.format(2)),
        ]
        self.assertEqual([l.item_id for l in self.targets(listings, limit=1)], ["ultegra"])


class LookupRunTest(unittest.TestCase):
    """A whole run with a database: the page is fetched once, stored, and put
    back on the next run without a request."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        intake = Path(repo_file("mijn_fiets.md")).read_text(encoding="utf-8")
        intake, n = re.subn(r"^verkoopprijs_handmatig =.*$", "verkoopprijs_handmatig = 390",
                            intake, flags=re.M)
        self.assertEqual(n, 1)
        self.mijn_fiets = self.tmp / "mijn_fiets.md"
        self.mijn_fiets.write_text(intake, encoding="utf-8")
        self.fetched = []

    def listing(self):
        return make_listing(item_id="m1", title="Canyon Ultimate CF SLX", price_eur=500.0,
                            description="Wegens beëindigen hobby verkoop ik mijn fiets.",
                            url=ROAD_BIKE_URL.format(1))

    def run_query(self, *extra):
        def fake_page(session, url):
            self.fetched.append(url)
            return PAGE

        argv = [
            "--query", "test", "--pages", "3", "--no-html", "--no-log", "--no-price-history",
            "--no-notify-better", "--open-browser", "never", "--delay", "0",
            "--db", str(self.tmp / "koopjes.db"), "--mijn-fiets", str(self.mijn_fiets),
            "--history-file", str(self.tmp / "history.json"),
            "--reference-file", str(self.tmp / "geen-referentie.csv"),
        ] + list(extra)
        args = mp.parse_args(argv)
        with mock.patch.object(mp, "collect_listings",
                               lambda *a, **k: mp.CrawlResult([self.listing()])), \
                mock.patch.object(mp, "enrich_bid_listings", lambda *a, **k: None), \
                mock.patch.object(mp, "fetch_listing_page", fake_page), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            mp.run_for_query(args, "test", False)

    def stored(self):
        conn = db.connect(str(self.tmp / "koopjes.db"))
        self.addCleanup(conn.close)
        return conn

    def test_fetched_once_stored_and_read_back(self):
        self.run_query()
        self.assertEqual(len(self.fetched), 1)
        conn = self.stored()
        row = conn.execute(
            "SELECT description, full_description, frame_height, details_fetched_at FROM listing"
        ).fetchone()
        self.assertEqual(row["description"], "Wegens beëindigen hobby verkoop ik mijn fiets.")
        self.assertIn("Groepset: Ultegra", row["full_description"])
        self.assertEqual(row["frame_height"], "53 tot 57 cm")
        self.assertIsNotNone(row["details_fetched_at"])
        specs = db.read_listing_specs(conn)["m1"]
        self.assertEqual(specs["frame_material"], "carbon")
        self.assertEqual(specs["brake_type"], "velrem")
        self.assertEqual(specs["speeds"], "11")

        # upgrade.py scores from the database, with the full text.
        listing = up.fetch_candidate_listings(conn)[0]
        self.assertEqual(listing.groupset_tier, 5)
        self.assertEqual(listing.frame_height, "53 tot 57 cm")

        self.run_query()
        self.assertEqual(len(self.fetched), 1, "a listing is never fetched twice")
        # ...and the second run didn't wipe what the page gave.
        specs = db.read_listing_specs(self.stored())["m1"]
        self.assertEqual(specs["brake_type"], "velrem")
        self.assertEqual(
            self.stored().execute("SELECT frame_height FROM listing").fetchone()["frame_height"],
            "53 tot 57 cm",
        )

    def test_none_and_no_db_fetch_nothing(self):
        self.run_query("--detail-lookup", "none")
        self.run_query("--no-db")
        self.assertEqual(self.fetched, [])



class DetailLookupAllTest(unittest.TestCase):
    """--detail-lookup all: de volledige tekst van elke racefiets die de
    crawl zag, ook buiten de prijs- en maatfilters van het rapport, duurste
    eerst. Geen budget uit mijn_fiets.md nodig."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.fetched = []

    def listings(self):
        return [
            make_listing(item_id="goedkoop", title="Racefiets", price_eur=150.0, url=ROAD_BIKE_URL.format(1)),
            make_listing(item_id="duur", title="Trek Emonda SLR", price_eur=2500.0, url=ROAD_BIKE_URL.format(2)),
            make_listing(item_id="middel", title="Giant TCR", price_eur=800.0, url=ROAD_BIKE_URL.format(3)),
            make_listing(item_id="pedalen", title="Pedalen", price_eur=3000.0,
                         url="https://www.marktplaats.nl/v/fietsen-en-brommers/fietsonderdelen/m9-pedalen"),
        ]

    def run_query(self, *extra):
        def fake_page(session, url):
            self.fetched.append(url)
            return PAGE

        argv = [
            "--query", "test", "--pages", "3", "--no-html", "--no-log", "--no-price-history",
            "--no-notify-better", "--open-browser", "never", "--delay", "0",
            "--db", str(self.tmp / "koopjes.db"), "--mijn-fiets", str(self.tmp / "bestaat-niet.md"),
            "--history-file", str(self.tmp / "history.json"),
            "--reference-file", str(self.tmp / "geen-referentie.csv"),
            "--detail-lookup", "all", "--max-price", "900",
        ] + list(extra)
        args = mp.parse_args(argv)
        with mock.patch.object(mp, "collect_listings",
                               lambda *a, **k: mp.CrawlResult(self.listings())), \
                mock.patch.object(mp, "enrich_bid_listings", lambda *a, **k: None), \
                mock.patch.object(mp, "fetch_listing_page", fake_page), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            mp.run_for_query(args, "test", False)

    def stored(self):
        conn = db.connect(str(self.tmp / "koopjes.db"))
        self.addCleanup(conn.close)
        return conn

    def test_every_road_bike_most_expensive_first_also_above_max_price(self):
        self.run_query()
        self.assertEqual(self.fetched, [ROAD_BIKE_URL.format(n) for n in (2, 3, 1)])
        texts = {
            r["item_id"]: r["full_description"]
            for r in self.stored().execute("SELECT item_id, full_description FROM listing")
        }
        self.assertIn("Groepset: Ultegra", texts["duur"])
        self.assertIsNone(texts["pedalen"])

    def test_the_limit_takes_the_most_expensive(self):
        self.run_query("--detail-limit", "1")
        self.assertEqual(self.fetched, [ROAD_BIKE_URL.format(2)])
        self.run_query("--detail-limit", "1")
        self.assertEqual(self.fetched, [ROAD_BIKE_URL.format(n) for n in (2, 3)],
                         "de volgende run gaat verder waar de vorige ophield")

    def test_the_groupset_from_the_full_text_lands_in_spec(self):
        self.run_query()
        specs = db.read_listing_specs(self.stored())["duur"]
        self.assertEqual(specs["groupset"], "Shimano Ultegra")
        self.assertEqual(specs["groupset_tier"], "5")

    def test_a_later_run_keeps_the_full_text_specs_outside_the_filters(self):
        # "duur" valt buiten --max-price. Zonder zijn opgeslagen tekst terug
        # te zetten zou de tweede run zijn specs uit het zoekfragment opnieuw
        # schrijven, en het remtype van de pagina kwijtraken.
        self.run_query()
        for mode in ("budget", "none"):
            with self.subTest(mode=mode):
                self.run_query("--detail-lookup", mode)
                specs = db.read_listing_specs(self.stored())["duur"]
                self.assertEqual(specs["groupset"], "Shimano Ultegra")
                self.assertEqual(specs["speeds"], "11")


if __name__ == "__main__":
    unittest.main()
