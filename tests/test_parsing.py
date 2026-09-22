"""Parsing of Marktplaats' own data: prices, attributes, categories, free text."""
import unittest

from helpers import mp, raw_listing


class ParseListingTest(unittest.TestCase):
    def test_price_in_cents_becomes_euros(self):
        listing = mp.parse_listing(raw_listing(priceInfo={"priceCents": 12550, "priceType": "FIXED"}))
        self.assertEqual(listing.price_eur, 125.50)
        self.assertFalse(listing.price_is_bid)

    def test_zero_cents_means_no_price_except_when_free(self):
        # Marktplaats reports 0 cents for "no real price shown" as well as for
        # genuinely free items; only priceType tells them apart.
        priceless = mp.parse_listing(raw_listing(priceInfo={"priceCents": 0, "priceType": "FAST_BID"}))
        self.assertIsNone(priceless.price_eur)

        free = mp.parse_listing(raw_listing(priceInfo={"priceCents": 0, "priceType": "FREE"}))
        self.assertEqual(free.price_eur, 0.0)

    def test_bid_types_are_marked_as_bids(self):
        for price_type in ("FAST_BID", "MIN_BID"):
            with self.subTest(price_type=price_type):
                listing = mp.parse_listing(
                    raw_listing(priceInfo={"priceCents": 5000, "priceType": price_type})
                )
                self.assertTrue(listing.price_is_bid)

    def test_min_bid_has_no_minimum_until_looked_up(self):
        # A MIN_BID search result carries the seller's asking price, not the
        # minimum bid Marktplaats accepts — that needs the listing page.
        listing = mp.parse_listing(raw_listing(priceInfo={"priceCents": 4750, "priceType": "MIN_BID"}))
        self.assertEqual(listing.price_eur, 47.50)
        self.assertIsNone(listing.bid_minimum)
        self.assertIsNone(listing.bid_count)

    def test_relative_url_is_made_absolute(self):
        listing = mp.parse_listing(raw_listing(vipUrl="/v/fietsen/m1-test"))
        self.assertEqual(listing.url, "https://www.marktplaats.nl/v/fietsen/m1-test")

    def test_attributes_are_read_from_either_group(self):
        listing = mp.parse_listing(
            raw_listing(
                attributes=[{"key": "condition", "value": "Zo goed als nieuw"}],
                extendedAttributes=[{"key": "frameHeight", "value": "53 tot 57 cm"}],
            )
        )
        self.assertEqual(listing.condition, "Zo goed als nieuw")
        self.assertEqual(listing.frame_height, "53 tot 57 cm")


class FrameHeightTest(unittest.TestCase):
    def test_bucket_formats(self):
        cases = {
            "53 tot 57 cm": (53.0, 57.0),
            "Minder dan 48 cm": (0.0, 48.0),
            "61 cm of meer": (61.0, float("inf")),
            "56 cm": (56.0, 56.0),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(mp.frame_height_bounds(value), expected)

    def test_unparseable_value(self):
        self.assertIsNone(mp.frame_height_bounds("onbekend"))
        self.assertIsNone(mp.frame_height_bounds(""))

    def test_filter_keeps_overlapping_buckets(self):
        from helpers import make_listing

        listings = [
            make_listing(item_id="small", frame_height="Minder dan 48 cm"),
            make_listing(item_id="overlap", frame_height="53 tot 57 cm"),
            make_listing(item_id="big", frame_height="61 cm of meer"),
            make_listing(item_id="unknown", frame_height=""),
        ]
        kept = {l.item_id for l in mp.filter_by_frame_height(listings, 54, 60)}
        # The 53-57 bucket partially overlaps 54-60, so it's kept; a listing
        # with no frame size at all drops out once the filter is active.
        self.assertEqual(kept, {"overlap"})

    def test_filter_is_a_no_op_without_bounds(self):
        from helpers import make_listing

        listings = [make_listing(frame_height="")]
        self.assertEqual(mp.filter_by_frame_height(listings, None, None), listings)


class GroupsetDetectionTest(unittest.TestCase):
    def test_highest_tier_wins(self):
        label, tier = mp.detect_groupset("Racefiets met Shimano 105 en Ultegra remmen")
        self.assertEqual(label, "Shimano Ultegra")
        self.assertEqual(tier, 5)

    def test_ambiguous_words_need_their_brand(self):
        # "Force" and "Record" are ordinary words; without the brand they must
        # not count, or every listing mentioning "in perfecte staat" matches.
        self.assertEqual(mp.detect_groupset("Fiets in topstaat, force op de pedalen"), ("", None))
        label, tier = mp.detect_groupset("SRAM Force groepset")
        self.assertEqual(label, "SRAM Force")
        self.assertEqual(tier, 5)

    def test_105_is_not_matched_on_measurements(self):
        self.assertEqual(mp.detect_groupset("Framemaat 105 cm"), ("", None))
        self.assertEqual(mp.detect_groupset("Vraagprijs 105 euro"), ("", None))
        label, _ = mp.detect_groupset("Shimano 105 groepset")
        self.assertEqual(label, "Shimano 105")

    def test_electronic_tag(self):
        label, _ = mp.detect_groupset("Ultegra Di2 elektronisch")
        self.assertEqual(label, "Shimano Ultegra (elektronisch)")

    def test_nothing_recognized(self):
        self.assertEqual(mp.detect_groupset("Gewone stadsfiets"), ("", None))


class DominantCategoryTest(unittest.TestCase):
    def test_picks_the_biggest_dominant_category(self):
        # An ambiguous query can flag several categories as dominant; the one
        # with the most matches is the real subject of the query.
        response = {
            "facets": [
                {
                    "key": "RelevantCategories",
                    "categories": [
                        {"id": 1, "dominant": True, "histogramCount": 10},
                        {"id": 2, "dominant": True, "histogramCount": 400},
                        {"id": 3, "histogramCount": 9000},
                    ],
                }
            ]
        }
        self.assertEqual(mp.extract_dominant_category(response), 2)

    def test_no_dominant_category(self):
        response = {"facets": [{"key": "RelevantCategories", "categories": [{"id": 1}]}]}
        self.assertIsNone(mp.extract_dominant_category(response))
        self.assertIsNone(mp.extract_dominant_category({"facets": []}))


class BalancedJsonTest(unittest.TestCase):
    def test_stops_at_the_matching_brace(self):
        text = 'prefix {"a": {"b": 1}} suffix {"c": 2}'
        start = text.index("{")
        self.assertEqual(mp.extract_balanced_json(text, start), {"a": {"b": 1}})

    def test_braces_inside_strings_are_ignored(self):
        text = r'{"a": "een } accolade", "b": "escaped \" quote"}'
        self.assertEqual(
            mp.extract_balanced_json(text, 0),
            {"a": "een } accolade", "b": 'escaped " quote'},
        )

    def test_unterminated_object(self):
        self.assertIsNone(mp.extract_balanced_json('{"a": 1', 0))


if __name__ == "__main__":
    unittest.main()
