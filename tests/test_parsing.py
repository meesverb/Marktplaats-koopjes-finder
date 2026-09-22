"""Parsing of Marktplaats' own data: prices, attributes, categories, free text."""
import contextlib
import io
import unittest

from helpers import FakeSession, mp, raw_listing, search_page


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

    def test_a_price_that_is_not_a_number_is_no_price(self):
        # bool is a subclass of int in Python, so a stray "priceCents": true
        # would otherwise be read as a listing of one cent — a listing that
        # then leads every price sort and every bargain list.
        for cents in (True, "12550", None, {}):
            with self.subTest(cents=cents):
                listing = mp.parse_listing(
                    raw_listing(priceInfo={"priceCents": cents, "priceType": "FIXED"})
                )
                self.assertIsNone(listing.price_eur)

    def test_a_null_price_block_is_no_price(self):
        self.assertIsNone(mp.parse_listing(raw_listing(priceInfo=None)).price_eur)

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


class FetchPageTest(unittest.TestCase):
    """The query ends up in the URL path, so it has to be encoded as one."""

    def requested_url(self, query: str, page: int = 1) -> str:
        session = FakeSession({})
        with self.assertRaises(RuntimeError):  # the canned page has no data
            mp.fetch_page(session, query, page)
        return session.requested[0]

    def test_a_question_mark_does_not_become_a_query_string(self):
        # "/q/wat?/" is a path plus an empty query string: Marktplaats would
        # search for "wat" instead.
        self.assertTrue(self.requested_url("wat?").endswith("/q/wat%3F/"))

    def test_a_slash_does_not_become_a_path_segment(self):
        self.assertTrue(self.requested_url("ac/dc").endswith("/q/ac%2Fdc/"))

    def test_a_plain_query_still_looks_the_way_it_did(self):
        self.assertTrue(self.requested_url("racefiets", page=3).endswith("/q/racefiets/p/3/"))


class CollectListingsTest(unittest.TestCase):
    def test_listings_without_an_item_id_are_dropped(self):
        # They are keyed by item id from here on, so two of them would
        # overwrite each other — one ad silently standing in for another.
        page = search_page([raw_listing(itemId="", title="Eerste"),
                            raw_listing(itemId="", title="Tweede"),
                            raw_listing(itemId="m9", title="Met id")])
        session = FakeSession({mp.BASE_URL + "/q/test/": page})
        with contextlib.redirect_stderr(io.StringIO()):
            listings = mp.collect_listings("test", pages=1, delay=0, session=session)
        self.assertEqual([l.title for l in listings], ["Met id"])


    def test_a_null_page_limit_does_not_end_the_run(self):
        # maxAllowedPageNumber present but null: .get()'s default doesn't
        # apply, and the page bookkeeping used to raise a TypeError on it.
        page = search_page([raw_listing(itemId="m1")], max_page=None)
        session = FakeSession({mp.BASE_URL + "/q/test/": page})
        with contextlib.redirect_stderr(io.StringIO()) as err:
            listings = mp.collect_listings("test", pages=3, delay=0, session=session)
        self.assertEqual([l.item_id for l in listings], ["m1"])
        # Without a known limit, the page we just fetched is the last one.
        self.assertIn("pagina 1/1", err.getvalue())

    def test_a_page_limit_stays_a_whole_number(self):
        page = search_page([raw_listing(itemId="m1")], max_page=4)
        session = FakeSession({mp.BASE_URL + "/q/test/": page})
        with contextlib.redirect_stderr(io.StringIO()) as err:
            mp.collect_listings("test", pages=1, delay=0, session=session)
        self.assertIn("pagina 1/1 opgehaald", err.getvalue())


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

    def test_a_null_histogram_count_does_not_end_the_run(self):
        # A null count comes back out of .get(key, 0) as None, and max() then
        # compares it to an int.
        response = {
            "facets": [
                {
                    "key": "RelevantCategories",
                    "categories": [
                        {"id": 1, "dominant": True, "histogramCount": None},
                        {"id": 2, "dominant": True, "histogramCount": 12},
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
