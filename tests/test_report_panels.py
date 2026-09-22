"""The report's panels — PLAN_FIETSWAARDE.md fase 6.

Biedpaneel, Upgrade and Mijn fiets. The numbers themselves are tested where
they are computed (test_upgrade.py, test_valuation.py, test_quality_scoring.py);
these tests are about what reaches the page: the right rows in the right
order, counts that match, links that are there, and the waardescore kept
apart from the dealscore.
"""
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from helpers import make_listing, mp, repo_file

import db
import report
import upgrade as up


def render(listings, panels=None, query="racefiets"):
    return mp.render_html(listings, query, panels=panels)


def panel(html, name):
    """The HTML of one panel section."""
    match = re.search(
        rf'<section class="panel" id="panel-{name}"[^>]*>(.*?)</section>', html, re.S
    )
    assert match, f"no panel {name}"
    return match.group(1)


def defy_comps(n=8):
    """Fixed-price Giant Defy Composite ads around EUR 700, enough for a
    trede-1 valuation of the owner's bike in mijn_fiets.md."""
    return [
        make_listing(
            item_id=f"defy{i}",
            # The year goes in the title: that's where select_comps() reads
            # an unlabelled one from.
            title=f"Giant Defy Composite 2012 Ultegra 10 speed nr. {i}",
            description="carbon, velremmen",
            price_eur=650.0 + 20 * i,
            url=f"https://www.marktplaats.nl/v/fietsen/defy{i}",
        )
        for i in range(n)
    ]


class ValueScoreTest(unittest.TestCase):
    def test_fixed_price_at_the_median_scores_one(self):
        # The negotiation factor is on both sides and cancels out.
        score = up.value_score(make_listing(price_eur=100.0), median_eur=100.0)
        self.assertAlmostEqual(score.ratio, 1.0)

    def test_cheaper_than_its_value_scores_above_one(self):
        score = up.value_score(make_listing(price_eur=50.0), median_eur=100.0)
        self.assertAlmostEqual(score.ratio, 2.0)

    def test_bid_listing_divides_by_the_entry_price(self):
        listing = make_listing(
            price_eur=200.0, price_type="MIN_BID", price_is_bid=True, bid_count=0, bid_minimum=120.0
        )
        score = up.value_score(listing, median_eur=200.0)
        self.assertAlmostEqual(score.ratio, 200.0 * 0.875 / 120.0)
        self.assertIn("minimumbod", score.basis)

    def test_no_benchmark_is_unknown_not_zero(self):
        score = up.value_score(make_listing(price_eur=100.0), median_eur=None)
        self.assertIsNone(score.ratio)

    def test_unfetched_fast_bid_is_unknown(self):
        listing = make_listing(price_eur=None, price_type="FAST_BID", price_is_bid=True)
        self.assertIsNone(up.value_score(listing, median_eur=100.0).ratio)


class PanelTabsTest(unittest.TestCase):
    def test_every_panel_tab_has_a_section(self):
        html = render([make_listing()])
        tabs = re.findall(r'data-panel="(\w+)"', html)
        self.assertEqual(tabs, ["listings", "bidpanel", "upgrade", "mybike"])
        for name in tabs:
            with self.subTest(panel=name):
                self.assertIn(f'id="panel-{name}"', html)

    def test_only_the_listings_panel_is_visible_at_first(self):
        html = render([make_listing()])
        self.assertRegex(html, r'id="panel-listings">')
        for name in ("bidpanel", "upgrade", "mybike"):
            self.assertRegex(html, rf'id="panel-{name}" hidden>')

    def test_existing_row_filters_stay_in_the_listings_panel(self):
        html = render([make_listing()])
        listings_panel = panel(html, "listings")
        self.assertIn('data-filter="bidding"', listings_panel)
        self.assertIn('<table id="listings">', listings_panel)

    def test_without_a_bike_the_bike_tabs_say_so(self):
        html = render([make_listing()])
        self.assertIn("Geen eigen fiets", panel(html, "mybike"))
        self.assertIn("Geen eigen fiets", panel(html, "upgrade"))


class BidPanelTest(unittest.TestCase):
    def _listings(self):
        return [
            make_listing(item_id="vast", price_eur=100.0),
            make_listing(item_id="vast2", price_eur=100.0),
            make_listing(
                item_id="weinig", title="Weinig ruimte", price_eur=80.0,
                price_type="MIN_BID", price_is_bid=True, bid_count=0, bid_minimum=80.0,
            ),
            make_listing(
                item_id="veel", title="Veel ruimte", price_eur=90.0,
                price_type="MIN_BID", price_is_bid=True, bid_count=0, bid_minimum=20.0,
            ),
            make_listing(
                item_id="onbekend", title="Nooit opgehaald", price_eur=None,
                price_type="FAST_BID", price_is_bid=True,
            ),
        ]

    def test_count_matches_the_rows(self):
        html = render(self._listings())
        self.assertIn("Biedpaneel (3)", html)
        self.assertEqual(panel(html, "bidpanel").count("data-bidrow='1'"), 3)

    def test_sorted_on_headroom_with_unknown_last(self):
        section = panel(render(self._listings()), "bidpanel")
        order = [section.index(t) for t in ("Veel ruimte", "Weinig ruimte", "Nooit opgehaald")]
        self.assertEqual(order, sorted(order))

    def test_unknown_headroom_is_not_shown_as_zero(self):
        section = panel(render(self._listings()), "bidpanel")
        row = section[section.rindex("<tr", 0, section.index("Nooit opgehaald")):]
        self.assertIn("onbekend", row.split("</tr>")[0])
        self.assertNotIn("€0<", row.split("</tr>")[0])

    def test_value_score_and_deal_score_are_separate_columns(self):
        section = panel(render(self._listings()), "bidpanel")
        self.assertIn("<th>Waardescore</th>", section)
        self.assertIn("<th>Dealscore</th>", section)

    def test_titles_are_escaped(self):
        listing = make_listing(
            title="<img src=x>", price_eur=50.0, price_type="MIN_BID", price_is_bid=True,
        )
        section = panel(render([listing]), "bidpanel")
        self.assertNotIn("<img src=x>", section)
        self.assertIn("&lt;img src=x&gt;", section)


class OwnerPanelsTest(unittest.TestCase):
    """Mijn fiets and Upgrade, on a throwaway database with Defy comps."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "koopjes.db")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = db.connect(self.db_path)
        db.sync_listings(conn, "giant defy", defy_comps(), now)
        conn.close()

    def tearDown(self):
        self._tmp.cleanup()

    def owner(self, db_path="use-default"):
        context, problem = report.load_owner_context(
            repo_file("mijn_fiets.md"), self.db_path if db_path == "use-default" else db_path
        )
        self.assertIsNone(problem)
        return context

    def test_valuation_per_scenario_with_band_and_n(self):
        context = self.owner()
        self.assertEqual(sorted(context.valuations), ["a", "b"])
        self.assertEqual(context.comp_count, 8)
        section = report.render_bike_panel(context, None)
        for key in ("a", "b"):
            self.assertIn(f"data-scenario='{key}'", section)
        self.assertIn("n=8 comps", section)
        self.assertIn("laag – midden – hoog", section)

    def test_evidence_links_to_the_comps(self):
        section = report.render_bike_panel(self.owner(), None)
        self.assertIn("href='https://www.marktplaats.nl/v/fietsen/defy0'", section)
        self.assertIn("E1: trede", section)

    def test_baseline_breakdown_per_dimension(self):
        section = report.render_bike_panel(self.owner(), None)
        for dimension in ("frame", "drivetrain", "brakes", "wheels", "extras"):
            self.assertIn(f"<td>{dimension}</td>", section)

    def test_no_database_means_no_valuation_but_an_explanation(self):
        context = self.owner(db_path=None)
        self.assertIsNone(context.budgets)
        self.assertIn("--no-db", report.render_bike_panel(context, None))
        panels = report.build_panels([make_listing()], 100.0, owner=context)
        self.assertIn("Geen upgrade-finder", panels.upgrade_html)
        self.assertEqual(panels.upgrade_count, 0)

    def test_missing_database_file_is_not_created(self):
        missing = str(Path(self._tmp.name) / "bestaat_niet.db")
        context = self.owner(db_path=missing)
        self.assertIn("bestaat nog niet", context.valuation_problem)
        self.assertFalse(Path(missing).exists())

    def test_missing_intake_is_reported(self):
        context, problem = report.load_owner_context("bestaat_niet.md", self.db_path)
        self.assertIsNone(context)
        self.assertIn("niet gevonden", problem)

    def test_report_is_read_only(self):
        self.owner()
        conn = db.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM valuation").fetchone()[0], 0)
        finally:
            conn.close()

    def test_upgrade_panel_lists_candidates_in_order_with_count(self):
        context = self.owner()
        budget = context.budgets.rim.amount
        listings = [
            make_listing(
                item_id="goed", title="Carbon racefiets Ultegra Di2 11 speed schijfrem goedkoop",
                price_eur=round(budget * 0.5), frame_height="56 cm",
            ),
            make_listing(
                item_id="duur", title="Carbon racefiets Ultegra Di2 11 speed schijfrem duur",
                price_eur=round(budget * 0.9), frame_height="56 cm",
            ),
            make_listing(
                item_id="klein", title="Carbon racefiets Ultegra Di2 11 speed schijfrem klein",
                price_eur=round(budget * 0.5), frame_height="48 cm",
            ),
        ]
        for listing in listings:
            listing.groupset, listing.groupset_tier = mp.detect_groupset(listing.title)
        panels = report.build_panels(listings, 1000.0, owner=context)
        html = render(listings, panels=panels)
        section = panel(html, "upgrade")
        self.assertEqual(panels.upgrade_count, 2)
        self.assertIn("Upgrade (2)", html)
        self.assertEqual(section.count("data-upgraderow='1'"), 2)
        self.assertLess(section.index("goedkoop"), section.index("duur"))
        # Out of size never shows up as a candidate — only under "Afgevallen".
        candidates, _, rejected = section.partition("<details>")
        self.assertNotIn("klein", candidates)
        self.assertIn("buiten de maat", rejected)
        self.assertIn("class='dim'", section)
        self.assertIn("<th>Waardescore</th>", section)


class CliFlagTest(unittest.TestCase):
    def test_mijn_fiets_flag_defaults_to_the_intake_file(self):
        self.assertEqual(mp.parse_args([]).mijn_fiets, "mijn_fiets.md")


if __name__ == "__main__":
    unittest.main()
