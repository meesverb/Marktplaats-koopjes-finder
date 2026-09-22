"""Bidding listings: what the numbers mean and which ones are still open.

The distinction these tests pin down is the one that's easy to get wrong: a
MIN_BID listing's search-result price is the seller's asking price, while the
minimum bid Marktplaats accepts lives on the listing page and is often lower.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import FakeSession, config_page, make_listing, mp, read_csv_rows


class ResolveBidPriceTest(unittest.TestCase):
    def test_highest_bid_wins_over_the_minimum(self):
        info = {"currentMinimumBid": 5000, "bids": [{"value": 6000}, {"value": 8000}]}
        self.assertEqual(mp.resolve_bid_price(info), 80.0)

    def test_falls_back_to_the_minimum_bid(self):
        self.assertEqual(mp.resolve_bid_price({"currentMinimumBid": 3500, "bids": []}), 35.0)

    def test_nothing_to_go_on(self):
        self.assertIsNone(mp.resolve_bid_price({"bids": []}))
        self.assertIsNone(mp.resolve_bid_price({"currentMinimumBid": 0, "bids": []}))

    def test_values_that_are_not_numbers_are_not_bids(self):
        # bool passes an isinstance(x, (int, float)) check, so a "value": true
        # would count as a bid of one cent and win over a real minimum.
        info = {"currentMinimumBid": 5000, "bids": [{"value": True}, {"value": "6000"}]}
        self.assertEqual(mp.resolve_bid_price(info), 50.0)

    def test_a_minimum_that_is_not_a_number_is_no_minimum(self):
        self.assertIsNone(mp.resolve_bid_price({"currentMinimumBid": "3500", "bids": []}))
        self.assertIsNone(mp.resolve_bid_price({"currentMinimumBid": True, "bids": []}))


class EnrichBidListingsTest(unittest.TestCase):
    def enrich(self, listing, bids_info, mode):
        session = FakeSession({listing.url: config_page(bids_info)})
        # The lookup reports its progress on stderr; silence it so the suite's
        # own output stays readable.
        with contextlib.redirect_stderr(io.StringIO()):
            mp.enrich_bid_listings([listing], delay=0, mode=mode, session=session)
        return session

    def test_fast_bid_gets_a_price_it_did_not_have(self):
        listing = make_listing(price_eur=None, price_type="FAST_BID", price_is_bid=True)
        self.enrich(listing, {"currentMinimumBid": 4000, "bids": []}, "fast")
        self.assertEqual(listing.price_eur, 40.0)
        self.assertEqual(listing.bid_minimum, 40.0)
        self.assertEqual(listing.bid_count, 0)

    def test_a_minimum_bid_that_is_not_a_number_is_left_empty(self):
        # A string here used to end the run on the division; the listing keeps
        # the price it already had and simply has no known minimum.
        listing = make_listing(price_eur=47.50, price_type="MIN_BID", price_is_bid=True)
        self.enrich(listing, {"currentMinimumBid": "3500", "bids": []}, "all")
        self.assertEqual(listing.price_eur, 47.50)
        self.assertIsNone(listing.bid_minimum)

    def test_min_bid_keeps_its_asking_price(self):
        # Seen in the wild: asking EUR 47.50, minimum bid EUR 35. Replacing the
        # asking price with the minimum would make bid listings look cheaper
        # than fixed-price ones for no real reason.
        listing = make_listing(price_eur=47.50, price_type="MIN_BID", price_is_bid=True)
        self.enrich(listing, {"currentMinimumBid": 3500, "bids": []}, "all")
        self.assertEqual(listing.price_eur, 47.50)
        self.assertEqual(listing.bid_minimum, 35.0)

    def test_a_bid_above_the_asking_price_does_replace_it(self):
        # Below the standing bid the listing simply can't be had.
        listing = make_listing(price_eur=100.0, price_type="MIN_BID", price_is_bid=True)
        self.enrich(listing, {"currentMinimumBid": 8000, "bids": [{"value": 15000}]}, "all")
        self.assertEqual(listing.price_eur, 150.0)
        self.assertEqual(listing.bid_count, 1)

    def test_unusable_bid_values_do_not_count_and_leave_bidding_open(self):
        # Same payload as test_values_that_are_not_numbers_are_not_bids:
        # a bool and a numeric string are not usable bids, so bid_count
        # must land on 0, not 2 — and with 0 usable bids, the listing is
        # still open to bid on.
        listing = make_listing(price_eur=50.0, price_type="MIN_BID", price_is_bid=True)
        self.enrich(
            listing,
            {"currentMinimumBid": 5000, "bids": [{"value": True}, {"value": "6000"}]},
            "all",
        )
        self.assertEqual(listing.bid_count, 0)
        mp.apply_bid_flags([listing])
        self.assertTrue(listing.bid_open)

    def test_entries_without_a_value_do_not_count_as_bids(self):
        listing = make_listing(price_eur=50.0, price_type="MIN_BID", price_is_bid=True)
        self.enrich(
            listing,
            {"currentMinimumBid": 5000, "bids": [{"bidder": "anoniem"}, "niet-een-dict"]},
            "all",
        )
        self.assertEqual(listing.bid_count, 0)

    def test_only_the_usable_bid_is_counted(self):
        listing = make_listing(price_eur=50.0, price_type="MIN_BID", price_is_bid=True)
        self.enrich(
            listing,
            {"currentMinimumBid": 5000, "bids": [{"bidder": "anoniem"}, {"value": 6000}]},
            "all",
        )
        self.assertEqual(listing.bid_count, 1)

    def test_mode_fast_leaves_min_bid_listings_alone(self):
        listing = make_listing(price_eur=47.50, price_type="MIN_BID", price_is_bid=True)
        session = self.enrich(listing, {"currentMinimumBid": 3500, "bids": []}, "fast")
        self.assertEqual(session.requested, [])
        self.assertIsNone(listing.bid_count)

    def test_mode_none_fetches_nothing_at_all(self):
        listing = make_listing(price_eur=None, price_type="FAST_BID", price_is_bid=True)
        session = self.enrich(listing, {"currentMinimumBid": 4000, "bids": []}, "none")
        self.assertEqual(session.requested, [])
        self.assertIsNone(listing.price_eur)

    def test_a_page_without_bid_data_is_survivable(self):
        listing = make_listing(price_eur=None, price_type="FAST_BID", price_is_bid=True)
        session = FakeSession({listing.url: "<html>geen config</html>"})
        with contextlib.redirect_stderr(io.StringIO()):
            mp.enrich_bid_listings([listing], delay=0, mode="fast", session=session)
        self.assertIsNone(listing.price_eur)
        self.assertIsNone(listing.bid_count)


class MalformedPageTest(unittest.TestCase):
    """What the site can hand back that is valid JSON but not what we expect.
    None of it is worth ending a run over."""

    def test_a_null_listing_is_not_bid_data(self):
        url = "https://www.marktplaats.nl/v/x/m1-test"
        page = '<html><script>window.__CONFIG__ = {"listing": null};</script></html>'
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(mp.fetch_bid_info(FakeSession({url: page}), url))

    def test_a_bid_without_a_value_falls_back_to_the_minimum(self):
        info = {"currentMinimumBid": 3500, "bids": [{"bidder": "iemand"}]}
        self.assertEqual(mp.resolve_bid_price(info), 35.0)

    def test_a_usable_bid_next_to_a_broken_one_still_counts(self):
        info = {"currentMinimumBid": 3500, "bids": [{"bidder": "x"}, {"value": 8000}]}
        self.assertEqual(mp.resolve_bid_price(info), 80.0)

    def test_null_attributes_are_not_a_crash(self):
        raw = {"attributes": None, "extendedAttributes": [{"key": "condition", "value": "Gebruikt"}]}
        self.assertEqual(mp.extract_attribute(raw, "condition"), "Gebruikt")


class BidStructureWarningTest(unittest.TestCase):
    """A changed page structure has to be loud: silently returning "no bid
    info" looks exactly like a run where nobody happened to be bidding, so
    the bid columns would just quietly go empty for weeks."""

    def setUp(self):
        mp._bid_structure_warned = False
        self.addCleanup(setattr, mp, "_bid_structure_warned", False)

    def fetch(self, page: str):
        url = "https://www.marktplaats.nl/v/x/m1-test"
        session = FakeSession({url: page})
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            info = mp.fetch_bid_info(session, url)
        return info, stderr.getvalue()

    def test_a_missing_marker_is_reported(self):
        info, stderr = self.fetch("<html>geen config</html>")
        self.assertIsNone(info)
        self.assertIn("paginastructuur", stderr)

    def test_unreadable_json_behind_the_marker_is_reported(self):
        info, stderr = self.fetch("<html>window.__CONFIG__ = {kapot</html>")
        self.assertIsNone(info)
        self.assertIn("paginastructuur", stderr)

    def test_a_listing_that_simply_has_no_bid_data_is_not_a_change(self):
        info, stderr = self.fetch(config_page(None))
        self.assertIsNone(info)
        self.assertEqual(stderr, "")

    def test_the_warning_is_printed_once_not_per_listing(self):
        url = "https://www.marktplaats.nl/v/x/m1-test"
        session = FakeSession({url: "<html>geen config</html>"})
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            for _ in range(3):
                mp.fetch_bid_info(session, url)
        self.assertEqual(stderr.getvalue().count("paginastructuur"), 1)


class LookupOrderTest(unittest.TestCase):
    """Every bid lookup is its own request plus a --delay wait, so the filters
    that the search results alone can already decide run first — and the price
    range runs again afterwards, because a FAST_BID has no price to judge
    until the lookup has been done."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def run_query(self, listings, extra_argv, enrich=None):
        handed_to_lookup = []

        def fake_collect(query, pages, delay):
            return list(listings)

        def fake_enrich(ls, delay, mode, session=None):
            handed_to_lookup.extend(l.item_id for l in ls)
            if enrich is not None:
                enrich(ls, mode)

        argv = [
            "--query", "test", "--no-html", "--no-log", "--no-price-history",
            "--no-notify-better", "--open-browser", "never",
            "--history-file", str(self.tmp / "history.json"),
            "--reference-file", str(self.tmp / "geen-referentie.csv"),
            "--output", str(self.tmp / "out.csv"),
            "--no-db",
        ] + extra_argv
        args = mp.parse_args(argv)

        with mock.patch.object(mp, "collect_listings", fake_collect), mock.patch.object(
            mp, "enrich_bid_listings", fake_enrich
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                mp.run_for_query(args, "test", False)

        reported = [r["item_id"] for r in read_csv_rows(str(self.tmp / "out.csv"))]
        return handed_to_lookup, reported

    def test_a_listing_outside_the_range_is_never_looked_up(self):
        listings = [
            make_listing(item_id="binnen", price_eur=50.0),
            make_listing(item_id="buiten", price_eur=2000.0, price_type="MIN_BID", price_is_bid=True),
        ]
        looked_up, reported = self.run_query(
            listings, ["--max-price", "150", "--bid-lookup", "all"]
        )
        self.assertNotIn("buiten", looked_up)
        self.assertEqual(reported, ["binnen"])

    def test_the_wrong_frame_size_is_never_looked_up_either(self):
        listings = [
            make_listing(item_id="klein", frame_height="50 cm", price_type="MIN_BID", price_is_bid=True),
            make_listing(item_id="groot", frame_height="62 cm", price_type="MIN_BID", price_is_bid=True),
        ]
        looked_up, _ = self.run_query(
            listings, ["--min-frame-height", "58", "--bid-lookup", "all"]
        )
        self.assertEqual(looked_up, ["groot"])

    def test_a_bid_that_turns_out_too_high_still_drops_out(self):
        # The whole reason the range is applied twice: filtering only before
        # the lookup would let a FAST_BID standing at EUR 2000 through
        # --max-price 150, because at filter time it had no price at all.
        listings = [
            make_listing(item_id="duur", price_eur=None, price_type="FAST_BID", price_is_bid=True),
            make_listing(item_id="koopje", price_eur=None, price_type="FAST_BID", price_is_bid=True),
        ]
        prices = {"duur": 2000.0, "koopje": 40.0}

        def enrich(ls, mode):
            for l in ls:
                l.price_eur = prices[l.item_id]

        looked_up, reported = self.run_query(listings, ["--max-price", "150"], enrich=enrich)
        self.assertEqual(sorted(looked_up), ["duur", "koopje"])
        self.assertEqual(reported, ["koopje"])


class OpenBidTest(unittest.TestCase):
    def test_zero_bids_is_open_unknown_is_not(self):
        looked_up = make_listing(price_is_bid=True, bid_count=0)
        has_bids = make_listing(price_is_bid=True, bid_count=3)
        never_looked_up = make_listing(price_is_bid=True, bid_count=None)
        fixed_price = make_listing(price_is_bid=False, bid_count=0)

        listings = [looked_up, has_bids, never_looked_up, fixed_price]
        mp.apply_bid_flags(listings)

        self.assertTrue(looked_up.bid_open)
        self.assertFalse(has_bids.bid_open)
        self.assertFalse(never_looked_up.bid_open, "unknown is not the same as zero")
        self.assertFalse(fixed_price.bid_open)

        self.assertEqual(len(mp.bid_listings(listings)), 3)
        self.assertEqual(len(mp.open_bid_listings(listings)), 1)


class FormatBidInfoTest(unittest.TestCase):
    def test_nothing_for_a_fixed_price_listing(self):
        self.assertEqual(mp.format_bid_info(make_listing(price_is_bid=False)), "")

    def test_bid_counts_are_spelled_out(self):
        cases = {None: "biedingen onbekend", 0: "nog geen bod", 1: "1 bod", 4: "4 biedingen"}
        for count, expected in cases.items():
            with self.subTest(count=count):
                listing = make_listing(price_is_bid=True, bid_count=count)
                self.assertIn(expected, mp.format_bid_info(listing))

    def test_a_real_discount_is_shown_against_the_median(self):
        listing = make_listing(
            price_eur=200.0, price_is_bid=True, bid_count=0,
            bid_minimum=120.0, bid_minimum_pct_of_median=35.0,
        )
        self.assertIn("min. €120 (35% v. mediaan)", mp.format_bid_info(listing))

    def test_the_minimum_stops_being_a_discount_once_someone_has_bid(self):
        # With a standing bid the price column already shows that bid, and the
        # minimum no longer buys the listing. It stays visible as a number, but
        # advertising it as a cheap way in would be misleading.
        listing = make_listing(
            price_eur=150.0, price_is_bid=True, bid_count=1,
            bid_minimum=80.0, bid_minimum_pct_of_median=30.0,
        )
        info = mp.format_bid_info(listing)
        self.assertIn("min. €80", info)
        self.assertNotIn("mediaan", info)
        self.assertIn("1 bod", info)

    def test_an_uncounted_listing_is_not_sold_as_a_cheap_way_in(self):
        # Unknown is not zero: with the bids never counted, "nobody has bid
        # yet" is a claim we can't make, so the invitation stays off — the
        # same rule VRIJ TE BIEDEN follows.
        listing = make_listing(
            price_eur=200.0, price_is_bid=True, bid_count=None,
            bid_minimum=120.0, bid_minimum_pct_of_median=35.0,
        )
        info = mp.format_bid_info(listing)
        self.assertIn("min. €120", info)
        self.assertNotIn("mediaan", info)
        self.assertIn("biedingen onbekend", info)

    def test_a_one_cent_difference_is_not_a_discount(self):
        # Marktplaats sometimes sets the minimum a cent under the asking price;
        # calling that a discount would be noise.
        listing = make_listing(
            price_eur=175.0, price_is_bid=True, bid_count=0,
            bid_minimum=174.99, bid_minimum_pct_of_median=51.0,
        )
        info = mp.format_bid_info(listing)
        self.assertIn("min. €175", info)
        self.assertNotIn("v. mediaan", info)


class BidOverviewOrderTest(unittest.TestCase):
    """The bid panel sorts on headroom once fase 5 can supply it, and keeps
    the original order where it can't (PLAN_FIETSWAARDE.md §7)."""

    def bid(self, item_id, **overrides):
        fields = dict(price_is_bid=True, price_type="FAST_BID", price_eur=100.0)
        fields.update(overrides)
        return make_listing(item_id=item_id, **fields)

    def test_without_headroom_the_open_bids_still_come_first(self):
        bid_on = self.bid("bid_on", bid_count=2, deal_score=90.0)
        still_open = self.bid("open", bid_count=0, bid_open=True, deal_score=10.0)
        order = mp.bid_overview_order([bid_on, still_open])
        self.assertEqual([l.item_id for l in order], ["open", "bid_on"])

    def test_headroom_decides_the_order(self):
        small = self.bid("small", deal_score=90.0)
        large = self.bid("large", deal_score=10.0)
        order = mp.bid_overview_order([small, large], {"small": 50.0, "large": 400.0})
        self.assertEqual([l.item_id for l in order], ["large", "small"])

    def test_unknown_headroom_sinks_below_the_known_ones(self):
        # Unknown is not the same as no room, so it doesn't get to lead the
        # panel — but it doesn't disappear either.
        known = self.bid("known", deal_score=10.0)
        unknown = self.bid("unknown", bid_count=0, bid_open=True, deal_score=99.0)
        order = mp.bid_overview_order([known, unknown], {"known": 25.0, "unknown": None})
        self.assertEqual([l.item_id for l in order], ["known", "unknown"])

    def test_every_bid_listing_stays_in_the_panel(self):
        listings = [self.bid("a", deal_score=1.0), self.bid("b"), self.bid("c")]
        order = mp.bid_overview_order(listings, {"a": 10.0})
        self.assertEqual({l.item_id for l in order}, {"a", "b", "c"})


class BidHeadroomWiringTest(unittest.TestCase):
    def test_headroom_reaches_the_overview(self):
        listings = [
            make_listing(item_id="bid", price_is_bid=True, price_type="FAST_BID",
                         price_eur=100.0, bid_count=1),
            make_listing(item_id="fixed", price_eur=500.0),
        ]
        headroom = mp.bid_headroom_by_id(listings, median=1000.0)
        # Only bidding listings get a row, and the number is the value estimate
        # minus what it costs to get in — not the raw median.
        self.assertEqual(set(headroom), {"bid"})
        self.assertGreater(headroom["bid"], 0)

    def test_a_bid_that_was_never_looked_up_has_no_headroom(self):
        listings = [
            make_listing(item_id="bid", price_is_bid=True, price_type="FAST_BID",
                         price_eur=None, bid_count=None),
        ]
        self.assertIsNone(mp.bid_headroom_by_id(listings, median=1000.0)["bid"])

    def test_printing_the_overview_with_headroom_shows_the_column(self):
        listings = [
            make_listing(item_id="bid", title="Biedfiets", price_is_bid=True,
                         price_type="FAST_BID", price_eur=100.0, bid_count=1),
        ]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mp.print_bid_overview(listings, headroom={"bid": 250.0})
        printed = out.getvalue()
        self.assertIn("RUIMTE", printed)
        self.assertIn("€250", printed)

    def test_an_unknown_headroom_never_prints_as_zero(self):
        listings = [
            make_listing(item_id="bid", title="Biedfiets", price_is_bid=True,
                         price_type="MIN_BID", price_eur=100.0),
        ]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mp.print_bid_overview(listings, headroom={"bid": None})
        self.assertNotIn("€0", out.getvalue())


if __name__ == "__main__":
    unittest.main()
