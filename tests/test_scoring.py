"""Bargain flagging and the composite deal score."""
import unittest

from helpers import make_listing, mp


class BargainFlaggingTest(unittest.TestCase):
    def test_pct_of_median_and_bargain_threshold(self):
        listings = [make_listing(item_id=str(i), price_eur=p) for i, p in enumerate([50, 100, 150])]
        mp.flag_bargains(listings, bargain_ratio=0.6)
        cheap, middle, dear = listings
        self.assertEqual(cheap.pct_of_median, 50.0)
        self.assertEqual(middle.pct_of_median, 100.0)
        self.assertEqual(dear.pct_of_median, 150.0)
        self.assertTrue(cheap.is_bargain)
        self.assertFalse(middle.is_bargain)

    def test_too_few_prices_to_compare(self):
        listings = [make_listing(price_eur=100.0)]
        mp.flag_bargains(listings, 0.6)
        self.assertIsNone(listings[0].pct_of_median)

    def test_minimum_bid_is_measured_against_the_median_too(self):
        listings = [
            make_listing(item_id="a", price_eur=100.0),
            make_listing(item_id="b", price_eur=100.0),
            make_listing(item_id="c", price_eur=80.0, bid_minimum=50.0, price_is_bid=True),
        ]
        mp.flag_bargains(listings, 0.6)
        self.assertEqual(listings[2].bid_minimum_pct_of_median, 50.0)

    def test_stats_ignore_priceless_listings(self):
        listings = [make_listing(price_eur=100.0), make_listing(price_eur=None)]
        stats = mp.price_stats(listings)
        self.assertEqual(stats["count"], 1)
        self.assertEqual(mp.price_stats([])["count"], 0)

    def test_the_printed_median_is_the_one_the_percentages_use(self):
        # A free listing (priceType FREE, EUR 0) used to count towards the
        # median printed under the table while flag_bargains left it out, so
        # the "% v. mediaan" column was measured against a different number
        # than the one shown.
        listings = [
            make_listing(item_id="a", price_eur=100.0),
            make_listing(item_id="b", price_eur=200.0),
            make_listing(item_id="gratis", price_eur=0.0),
        ]
        mp.flag_bargains(listings, 0.6)
        stats = mp.price_stats(listings)
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["median"], 150.0)
        self.assertEqual(listings[0].pct_of_median, 66.7)


class RatioScoreTest(unittest.TestCase):
    def test_sitting_on_the_benchmark_scores_fifty(self):
        # Every signal's range is centred so 1.0 -> 50; that's what makes the
        # signals comparable when the weights are renormalized.
        for best, worst, _weight in (
            mp.SCORE_MEDIAN_RANGE,
            mp.SCORE_MARKET_RANGE,
            mp.SCORE_ORIGINAL_RANGE,
        ):
            with self.subTest(best=best, worst=worst):
                midpoint = (best + worst) / 2
                self.assertAlmostEqual(mp.ratio_score(midpoint, best, worst), 50.0)

    def test_clamped_at_both_ends(self):
        self.assertEqual(mp.ratio_score(0.01, 0.3, 1.7), 100.0)
        self.assertEqual(mp.ratio_score(99.0, 0.3, 1.7), 0.0)

    def test_cheaper_always_scores_higher(self):
        scores = [mp.ratio_score(r, 0.3, 1.7) for r in (0.4, 0.8, 1.2, 1.6)]
        self.assertEqual(scores, sorted(scores, reverse=True))


class DealScoreTest(unittest.TestCase):
    def test_no_price_means_no_score(self):
        listing = make_listing(price_eur=None)
        mp.score_listing(listing)
        self.assertIsNone(listing.deal_score)
        self.assertEqual(listing.deal_label, "")

    def test_no_signals_means_no_score(self):
        # Priced, but nothing to compare against yet.
        listing = make_listing(price_eur=100.0)
        mp.score_listing(listing)
        self.assertIsNone(listing.deal_score)

    def test_single_signal_is_enough(self):
        listing = make_listing(price_eur=50.0, pct_of_median=50.0)
        mp.score_listing(listing)
        self.assertIsNotNone(listing.deal_score)
        self.assertIn("van mediaan", listing.deal_reasons)

    def test_secondhand_average_needs_enough_observations(self):
        thin = make_listing(price_eur=50.0, pct_of_median=100.0, ref_market_avg=100.0, ref_market_count=1)
        mp.score_listing(thin)
        self.assertNotIn("2e-hands", thin.deal_reasons)

        solid = make_listing(price_eur=50.0, pct_of_median=100.0, ref_market_avg=100.0, ref_market_count=5)
        mp.score_listing(solid)
        self.assertIn("2e-hands", solid.deal_reasons)
        # Asking half of what the model usually goes for beats being at the median.
        self.assertGreater(solid.deal_score, thin.deal_score)

    def test_price_drop_and_better_than_reference_add_bonuses(self):
        plain = make_listing(price_eur=100.0, pct_of_median=100.0)
        mp.score_listing(plain)

        dropped = make_listing(price_eur=100.0, pct_of_median=100.0, price_dropped=True, price_drop_from=200.0)
        mp.score_listing(dropped)
        self.assertEqual(dropped.deal_score, plain.deal_score + mp.SCORE_DROP_BONUS_MAX)

        better = make_listing(price_eur=100.0, pct_of_median=100.0, ref_better=True)
        mp.score_listing(better)
        self.assertEqual(better.deal_score, plain.deal_score + mp.SCORE_BETTER_BONUS)

    def test_bid_listings_are_flagged_as_an_upper_bound(self):
        listing = make_listing(price_eur=50.0, pct_of_median=50.0, price_is_bid=True)
        mp.score_listing(listing)
        self.assertIn("bod", listing.deal_reasons)

    def test_score_stays_within_range(self):
        steal = make_listing(
            price_eur=1.0, pct_of_median=1.0, ref_pct_of_original=1.0,
            ref_market_avg=1000.0, ref_market_count=9, ref_better=True,
            price_dropped=True, price_drop_from=500.0,
        )
        mp.score_listing(steal)
        self.assertEqual(steal.deal_score, 100.0)

        awful = make_listing(price_eur=9999.0, pct_of_median=9999.0)
        mp.score_listing(awful)
        self.assertEqual(awful.deal_score, 0.0)

    def test_label_and_pill_colour_agree_with_the_number(self):
        # A rounded 80 must be a Topdeal in the label, the colour and the
        # filter tab alike — they all read the same rounded score.
        listing = make_listing(price_eur=100.0, pct_of_median=100.0)
        for score, expected in ((100.0, "Topdeal"), (70.0, "Goede deal"), (50.0, "Redelijk"),
                                (30.0, "Aan de prijs"), (10.0, "Duur")):
            with self.subTest(score=score):
                listing.deal_score = score
                label = next(lbl for threshold, lbl, _ in mp.SCORE_LABELS if score >= threshold)
                self.assertEqual(label, expected)

        self.assertEqual(mp.score_css_class(mp.TOP_DEAL_SCORE), "top")
        self.assertEqual(mp.score_css_class(None), "low")

    def test_score_is_a_whole_number(self):
        listing = make_listing(price_eur=37.0, pct_of_median=37.0, ref_pct_of_original=23.0)
        mp.score_listing(listing)
        self.assertEqual(listing.deal_score, round(listing.deal_score))


class SortByScoreTest(unittest.TestCase):
    def test_best_first_unscored_last(self):
        best = make_listing(item_id="best", deal_score=90.0)
        worst = make_listing(item_id="worst", deal_score=10.0)
        unscored = make_listing(item_id="unscored", deal_score=None, price_eur=None)
        order = [l.item_id for l in mp.sort_by_score([worst, unscored, best])]
        self.assertEqual(order, ["best", "worst", "unscored"])

    def test_equal_scores_break_on_price(self):
        cheap = make_listing(item_id="cheap", deal_score=50.0, price_eur=10.0)
        dear = make_listing(item_id="dear", deal_score=50.0, price_eur=99.0)
        order = [l.item_id for l in mp.sort_by_score([dear, cheap])]
        self.assertEqual(order, ["cheap", "dear"])


if __name__ == "__main__":
    unittest.main()
