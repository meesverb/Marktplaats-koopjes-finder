"""The HTML report.

Phase 6 of PLAN_FIETSWAARDE.md pulls HTML_TEMPLATE out of racefiets_jev.py
into its own file. These tests describe what the report must still do
afterwards, so that refactor can be verified instead of eyeballed.
"""
import re
import unittest

from helpers import make_listing, mp


def render(listings, query="racefiets"):
    return mp.render_html(listings, query)


class TemplateTest(unittest.TestCase):
    def test_no_placeholder_is_left_unsubstituted(self):
        html = render([make_listing(price_eur=100.0, pct_of_median=50.0, deal_score=80.0)])
        leftovers = re.findall(r"\{[a-z_]+\}", html)
        self.assertEqual(leftovers, [], f"unsubstituted placeholders: {leftovers}")

    def test_renders_with_no_listings_at_all(self):
        html = render([])
        self.assertIn("<table", html)

    def test_html_in_listing_text_is_escaped(self):
        nasty = make_listing(title='<script>alert("x")</script>', city="Utrecht & Co")
        html = render([nasty])
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Utrecht &amp; Co", html)

    def test_every_listing_gets_a_row(self):
        listings = [make_listing(item_id=str(i), price_eur=float(i + 1) * 10) for i in range(5)]
        mp.flag_bargains(listings, 0.6)
        self.assertEqual(render(listings).count("<tr data-new="), 5)


class FilterTabTest(unittest.TestCase):
    """Each tab's count must match the rows it can actually show."""

    def test_counts_match_the_rows(self):
        listings = [
            make_listing(item_id="a", is_new=True, deal_score=90.0, price_eur=10.0),
            make_listing(item_id="b", is_bargain=True, price_eur=20.0),
            make_listing(item_id="c", price_is_bid=True, bid_count=0, bid_open=True, price_eur=30.0),
            make_listing(item_id="d", price_is_bid=True, bid_count=2, price_eur=40.0),
            make_listing(item_id="e", ref_better=True, price_eur=50.0),
            make_listing(item_id="f", price_dropped=True, price_drop_from=99.0, price_eur=60.0),
        ]
        html = render(listings)
        expected = {
            "Nieuw": ("data-new='1'", 1),
            "Koopjes": ("data-bargain='1'", 1),
            "Beter dan referentie": ("data-better='1'", 1),
            "Prijsverlaging": ("data-dropped='1'", 1),
            "Topdeals": ("data-topdeal='1'", 1),
            "Bieden": ("data-bidding='1'", 2),
            "Vrij te bieden": ("data-openbid='1'", 1),
        }
        for tab, (attribute, count) in expected.items():
            with self.subTest(tab=tab):
                self.assertIn(f"{tab} ({count})", html, f"{tab} tab shows the wrong count")
                self.assertEqual(html.count(attribute), count)

    def test_every_tab_button_has_rows_that_can_match_it(self):
        html = render([make_listing(price_eur=10.0)])
        filters = set(re.findall(r'data-filter="(\w+)"', html))
        row_attributes = set(re.findall(r"data-(\w+)='[01]'", html))
        self.assertTrue(
            filters - {"all"} <= row_attributes,
            f"tabs without a matching row attribute: {filters - {'all'} - row_attributes}",
        )


class ScoreCellTest(unittest.TestCase):
    def test_score_breakdown_is_available_as_a_tooltip(self):
        listing = make_listing(price_eur=50.0, pct_of_median=50.0)
        mp.score_listing(listing)
        html = render([listing])
        self.assertIn("van mediaan", html)
        self.assertIn("score-pill", html)

    def test_priceless_listing_shows_a_dash_not_a_zero(self):
        html = render([make_listing(price_eur=None, price_type="RESERVED")])
        self.assertIn("data-score='-1'", html)

    def test_rows_are_sorted_best_first(self):
        listings = [
            make_listing(item_id="a", title="Matige deal", price_eur=100.0, deal_score=20.0),
            make_listing(item_id="b", title="Topdeal hier", price_eur=10.0, deal_score=95.0),
        ]
        html = render(listings)
        self.assertLess(html.index("Topdeal hier"), html.index("Matige deal"))


if __name__ == "__main__":
    unittest.main()
