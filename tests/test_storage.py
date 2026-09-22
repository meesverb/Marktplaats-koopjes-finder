"""The four on-disk files the script reads and writes.

These matter most: phase 1 of PLAN_FIETSWAARDE.md moves all of this into
SQLite while these files must keep being written in the same format. If a
migration changes behaviour here, these tests are what catches it.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from helpers import make_listing, mp, read_csv_rows


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def path(self, name: str) -> str:
        return str(self.tmp / name)


class HistoryTest(TempDirTest):
    """seen_listings.json — what makes a listing "new" and spots price drops."""

    def test_missing_or_broken_file_is_an_empty_history(self):
        self.assertEqual(mp.load_history(self.path("nope.json")), {})
        broken = self.path("broken.json")
        Path(broken).write_text("{not json", encoding="utf-8")
        self.assertEqual(mp.load_history(broken), {})

    def test_first_sighting_is_new_second_is_not(self):
        listing = make_listing(item_id="a", price_eur=100.0)
        history = mp.apply_history([listing], {})
        self.assertTrue(listing.is_new)

        again = make_listing(item_id="a", price_eur=100.0)
        mp.apply_history([again], history)
        self.assertFalse(again.is_new)
        self.assertFalse(again.price_dropped)

    def test_price_drop_is_detected_and_measured(self):
        history = mp.apply_history([make_listing(item_id="a", price_eur=200.0)], {})
        cheaper = make_listing(item_id="a", price_eur=150.0)
        mp.apply_history([cheaper], history)
        self.assertTrue(cheaper.price_dropped)
        self.assertEqual(cheaper.price_drop_from, 200.0)

    def test_price_rise_is_not_a_drop(self):
        history = mp.apply_history([make_listing(item_id="a", price_eur=100.0)], {})
        pricier = make_listing(item_id="a", price_eur=120.0)
        mp.apply_history([pricier], history)
        self.assertFalse(pricier.price_dropped)

    def test_history_survives_a_save_load_round_trip(self):
        path = self.path("seen.json")
        history = mp.apply_history([make_listing(item_id="a", price_eur=100.0)], {})
        mp.save_history(path, history)

        listing = make_listing(item_id="a", price_eur=80.0)
        mp.apply_history([listing], mp.load_history(path))
        self.assertFalse(listing.is_new)
        self.assertTrue(listing.price_dropped)

    def test_json_that_is_not_a_history_is_ignored_with_a_warning(self):
        # Valid JSON, wrong shape (hand-edited, or a different file under this
        # name): used to reach apply_history() and die on .get().
        path = self.path("history.json")
        Path(path).write_text('["m1", "m2"]', encoding="utf-8")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            history = mp.load_history(path)
        self.assertEqual(history, {})
        self.assertIn("geen advertentie-geschiedenis", stderr.getvalue())

        listing = make_listing()
        mp.apply_history([listing], history)
        self.assertTrue(listing.is_new)

    def test_an_unknown_price_does_not_erase_the_known_one(self):
        # One run with --bid-lookup none leaves a FAST_BID priceless. That is
        # unknown, not gone: keep the last price so the next drop is still
        # measurable against it.
        listing = make_listing(item_id="a", price_eur=50.0)
        history = mp.apply_history([listing], {})

        priceless = make_listing(item_id="a", price_eur=None)
        history = mp.apply_history([priceless], history)
        self.assertEqual(history["a"]["last_price"], 50.0)

        cheaper = make_listing(item_id="a", price_eur=40.0)
        mp.apply_history([cheaper], history)
        self.assertTrue(cheaper.price_dropped)
        self.assertEqual(cheaper.price_drop_from, 50.0)

    def test_a_failed_save_keeps_the_previous_history(self):
        # A half-written file would be unparseable, and load_history() treats
        # unparseable as empty — so a crash mid-save would quietly wipe every
        # first_seen date and mark the whole market new again.
        path = self.path("history.json")
        mp.save_history(path, {"a": {"first_seen": "2026-01-01T00:00:00+00:00"}})

        with self.assertRaises(TypeError):
            mp.save_history(path, {"b": {"first_seen": object()}})

        self.assertEqual(mp.load_history(path), {"a": {"first_seen": "2026-01-01T00:00:00+00:00"}})
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])

    def test_first_seen_is_preserved_across_runs(self):
        first = make_listing(item_id="a")
        history = mp.apply_history([first], {})
        later = make_listing(item_id="a")
        mp.apply_history([later], history)
        self.assertEqual(later.first_seen, first.first_seen)


class ReferenceFileTest(TempDirTest):
    """reference_prices.csv — the hand-maintained model database."""

    def write_reference(self, rows: str) -> str:
        path = self.path("reference.csv")
        Path(path).write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline\n" + rows,
            encoding="utf-8",
        )
        return path

    def test_missing_file_is_optional(self):
        self.assertEqual(mp.load_reference_data(self.path("nope.csv")), [])

    def test_row_is_parsed(self):
        path = self.write_reference("Mission 731,Mission 731,300,\"89 dB\",7/10,1\n")
        (row,) = mp.load_reference_data(path)
        self.assertEqual(row["label"], "Mission 731")
        self.assertEqual(row["original_price_eur"], 300.0)
        self.assertEqual(row["specs"], "89 dB")
        self.assertTrue(row["better"])

    def test_blank_original_price_is_allowed(self):
        path = self.write_reference("Mission 731,Mission 731,,,,\n")
        (row,) = mp.load_reference_data(path)
        self.assertIsNone(row["original_price_eur"])
        self.assertFalse(row["better"])

    def test_a_file_saved_from_excel_still_loads(self):
        # Excel writes a UTF-8 BOM, which lands in the first column's name
        # ("\ufeffpattern"). Every row then looked like it had no pattern at
        # all, so the whole reference database quietly came back empty.
        path = self.path("ref.csv")
        Path(path).write_text(
            "\ufeffpattern,label,original_price_eur,specs,score,better_than_baseline\n"
            "mission,Mission 731,300,,,\n",
            encoding="utf-8",
        )
        (row,) = mp.load_reference_data(path)
        self.assertEqual(row["label"], "Mission 731")
        self.assertEqual(row["original_price_eur"], 300.0)

    def test_an_unreadable_original_price_is_treated_as_empty(self):
        # The new-price column is filled in by hand, so "ca. 300" is a matter
        # of time. The row still has to match; only the price goes missing.
        path = self.path("ref.csv")
        Path(path).write_text(
            "pattern,label,original_price_eur\nmission,Mission 731,ca. 300\n",
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            (row,) = mp.load_reference_data(path)
        self.assertEqual(row["label"], "Mission 731")
        self.assertIsNone(row["original_price_eur"])
        self.assertIn("ca. 300", stderr.getvalue())

    def test_invalid_regex_is_skipped_not_fatal(self):
        path = self.write_reference("Mission [731,Kapot,,,,\nWharfedale,Wharfedale,100,,,\n")
        # The loader warns on stderr about the bad pattern; that's the point of
        # the test, but it shouldn't clutter the suite's output.
        with contextlib.redirect_stderr(io.StringIO()):
            rows = mp.load_reference_data(path)
        self.assertEqual([r["label"] for r in rows], ["Wharfedale"])

    def test_rows_without_a_pattern_are_ignored(self):
        path = self.write_reference(",Geen patroon,100,,,\n")
        self.assertEqual(mp.load_reference_data(path), [])

    def test_first_match_in_file_order_wins(self):
        path = self.write_reference(
            "Mission 731,Specifiek,300,,,\n"
            "Mission,Algemeen,100,,,\n"
        )
        listing = make_listing(title="Mission 731 speakers", price_eur=60.0)
        mp.apply_reference_data([listing], mp.load_reference_data(path))
        self.assertEqual(listing.ref_label, "Specifiek")
        self.assertEqual(listing.ref_pct_of_original, 20.0)

    def test_pattern_matches_the_description_too(self):
        path = self.write_reference("Mission 731,Mission 731,,,,\n")
        listing = make_listing(title="Set speakers", description="Het gaat om Mission 731")
        mp.apply_reference_data([listing], mp.load_reference_data(path))
        self.assertEqual(listing.ref_label, "Mission 731")


class PriceHistoryTest(TempDirTest):
    """reference_price_history.csv — the self-growing secondhand price record."""

    def test_only_new_listings_with_a_price_are_logged(self):
        path = self.path("prices.csv")
        listings = [
            make_listing(item_id="a", is_new=True, ref_label="Model A", price_eur=50.0),
            make_listing(item_id="b", is_new=False, ref_label="Model A", price_eur=60.0),
            make_listing(item_id="c", is_new=True, ref_label="", price_eur=70.0),
            make_listing(item_id="d", is_new=True, ref_label="Model A", price_eur=None),
        ]
        self.assertEqual(mp.append_reference_price_observations(path, listings), 1)

        rows = read_csv_rows(path)
        self.assertEqual([r["item_id"] for r in rows], ["a"])

    def test_appending_keeps_earlier_rows_and_writes_one_header(self):
        path = self.path("prices.csv")
        mp.append_reference_price_observations(
            path, [make_listing(item_id="a", is_new=True, ref_label="M", price_eur=50.0)]
        )
        mp.append_reference_price_observations(
            path, [make_listing(item_id="b", is_new=True, ref_label="M", price_eur=70.0)]
        )
        lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("date,ref_label"))

    def test_stats_are_built_per_model(self):
        path = self.path("prices.csv")
        for item_id, price in (("a", 40.0), ("b", 60.0), ("c", 200.0)):
            label = "Model A" if item_id in ("a", "b") else "Model B"
            mp.append_reference_price_observations(
                path, [make_listing(item_id=item_id, is_new=True, ref_label=label, price_eur=price)]
            )
        stats = mp.load_reference_market_stats(path)
        self.assertEqual(stats["Model A"]["count"], 2)
        self.assertEqual(stats["Model A"]["mean"], 50.0)
        self.assertEqual(stats["Model B"]["count"], 1)

    def test_stats_are_attached_to_matching_listings_only(self):
        listings = [make_listing(ref_label="Model A"), make_listing(ref_label="Onbekend")]
        mp.apply_reference_market_stats(listings, {"Model A": {"count": 3, "mean": 55.0, "median": 50.0}})
        self.assertEqual(listings[0].ref_market_avg, 55.0)
        self.assertEqual(listings[0].ref_market_count, 3)
        self.assertIsNone(listings[1].ref_market_avg)

    def test_missing_file_gives_no_stats(self):
        self.assertEqual(mp.load_reference_market_stats(self.path("nope.csv")), {})

    def test_a_free_listing_is_not_a_price_observation(self):
        # priceType FREE is a giveaway, not an asking price; logging EUR 0
        # would pull the model's observed secondhand average down for good.
        path = self.path("prices.csv")
        recorded = mp.append_reference_price_observations(
            path,
            [make_listing(item_id="gratis", is_new=True, ref_label="M", price_eur=0.0)],
        )
        self.assertEqual(recorded, 0)

    def test_a_standing_bid_is_not_an_asking_price(self):
        # Mid-auction the price only goes up, so logging it would say more
        # about how long the auction had left than about what the model costs.
        # A bid listing nobody has bid on yet still shows the seller's floor
        # price, and that one counts.
        path = self.path("prices.csv")
        listings = [
            make_listing(
                item_id="loopt", is_new=True, ref_label="M", price_eur=500.0,
                price_type="FAST_BID", price_is_bid=True, bid_count=3,
            ),
            make_listing(
                item_id="vrij", is_new=True, ref_label="M", price_eur=40.0,
                price_type="FAST_BID", price_is_bid=True, bid_count=0,
            ),
            make_listing(
                item_id="vraagprijs", is_new=True, ref_label="M", price_eur=47.5,
                price_type="MIN_BID", price_is_bid=True, bid_count=None,
            ),
        ]
        self.assertEqual(mp.append_reference_price_observations(path, listings), 2)
        self.assertEqual([r["item_id"] for r in read_csv_rows(path)], ["vrij", "vraagprijs"])

    def test_a_file_without_the_expected_columns_is_reported(self):
        # A hand-edited or pre-historic file used to raise KeyError here and
        # take the whole run down with it.
        path = self.path("prices.csv")
        Path(path).write_text("date,item_id,price_eur\n2026-01-01,a,50\n", encoding="utf-8")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            stats = mp.load_reference_market_stats(path)
        self.assertEqual(stats, {})
        self.assertIn("ref_label", stderr.getvalue())

    def test_a_blank_first_line_does_not_look_like_wrong_columns(self):
        # [] is not a header with the wrong columns in it; refusing to write
        # over a file that only has a blank line in it loses the run's
        # observations for nothing.
        path = self.path("prices.csv")
        Path(path).write_text("\n", encoding="utf-8")
        listings = [make_listing(item_id="a", is_new=True, ref_label="Model X", price_eur=50.0)]

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(mp.append_reference_price_observations(path, listings), 1)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual([r["item_id"] for r in read_csv_rows(path)], ["a"])

    def test_unreadable_and_free_rows_are_skipped_not_fatal(self):
        path = self.path("prices.csv")
        Path(path).write_text(
            "date,ref_label,item_id,price_eur,title\n"
            "2026-01-01,Model A,a,50,Eerste\n"
            "2026-01-01,Model A,b,kapot,Tweede\n"
            "2026-01-01,Model A,c,0,Gratis\n"
            "2026-01-01,,d,70,Zonder label\n"
            "2026-01-01,Model A,e\n",
            encoding="utf-8",
        )
        stats = mp.load_reference_market_stats(path)
        self.assertEqual(stats["Model A"]["count"], 1)
        self.assertEqual(stats["Model A"]["mean"], 50.0)

    def test_a_bom_does_not_look_like_a_different_file_format(self):
        # Open the history in Excel once and it comes back with a BOM. The
        # column check would then refuse to append and report "andere
        # kolommen", which is both wrong and unfixable-looking.
        path = self.path("prices.csv")
        Path(path).write_text(
            "\ufeffdate,ref_label,item_id,price_eur,title\n", encoding="utf-8"
        )
        recorded = mp.append_reference_price_observations(
            path, [make_listing(item_id="a", is_new=True, ref_label="M", price_eur=50.0)]
        )
        self.assertEqual(recorded, 1)
        self.assertEqual([r["item_id"] for r in read_csv_rows(path)], ["a"])

    def test_a_file_with_other_columns_is_left_alone(self):
        # Appending under a header that isn't ours would misalign the file that
        # feeds the observed secondhand average, and skew every valuation
        # built on it afterwards. Better to record nothing and say so.
        path = self.path("prices.csv")
        Path(path).write_text("iets,heel,anders\n", encoding="utf-8")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            recorded = mp.append_reference_price_observations(
                path, [make_listing(is_new=True, ref_label="M", price_eur=50.0)]
            )
        self.assertEqual(recorded, 0)
        self.assertIn("andere kolommen", stderr.getvalue())
        self.assertEqual(Path(path).read_text(encoding="utf-8"), "iets,heel,anders\n")


class BargainLogTest(TempDirTest):
    """bargains_log.csv — the running record of every bargain ever spotted."""

    def test_only_listings_that_are_both_new_and_a_bargain(self):
        path = self.path("log.csv")
        listings = [
            make_listing(item_id="a", is_new=True, is_bargain=True),
            make_listing(item_id="b", is_new=True, is_bargain=False),
            make_listing(item_id="c", is_new=False, is_bargain=True),
        ]
        self.assertEqual(mp.append_bargain_log(path, listings), 1)
        rows = read_csv_rows(path)
        self.assertEqual([r["item_id"] for r in rows], ["a"])

    def test_nothing_to_log_creates_no_file(self):
        path = self.path("log.csv")
        self.assertEqual(mp.append_bargain_log(path, [make_listing(is_new=False)]), 0)
        self.assertFalse(Path(path).exists())

    def test_log_carries_every_listing_field(self):
        path = self.path("log.csv")
        mp.append_bargain_log(path, [make_listing(is_new=True, is_bargain=True, deal_score=88.0)])
        (row,) = read_csv_rows(path)
        self.assertIn("logged_at", row)
        self.assertEqual(row["deal_score"], "88.0")

    def test_a_new_listing_field_does_not_shift_the_existing_columns(self):
        # The nightmare this guards against: Listing grows a field in the
        # middle (the fields are grouped ref_*/bid_*/deal_*, so that is where
        # one lands), the appended rows follow the new order, and every value
        # in the file from that run on sits one column off.
        path = self.path("log.csv")
        header = ["logged_at", "item_id", "title", "price_eur"]
        Path(path).write_text(",".join(header) + "\n", encoding="utf-8")

        with contextlib.redirect_stderr(io.StringIO()):
            mp.append_bargain_log(
                path, [make_listing(item_id="a", is_new=True, is_bargain=True, price_eur=42.0)]
            )

        lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(lines[0], ",".join(header))
        (row,) = read_csv_rows(path)
        self.assertEqual(row["item_id"], "a")
        self.assertEqual(row["price_eur"], "42.0")
        self.assertEqual(len(row), len(header))

    def test_a_file_that_starts_with_a_blank_line_still_gets_a_header(self):
        # An empty first row is not a header, but it isn't "no header" either:
        # the rows used to be appended under no column names at all, and the
        # file could never be read back.
        path = self.path("log.csv")
        Path(path).write_text("\n", encoding="utf-8")

        with contextlib.redirect_stderr(io.StringIO()):
            mp.append_bargain_log(path, [make_listing(item_id="a", is_new=True, is_bargain=True)])
        (row,) = read_csv_rows(path)
        self.assertEqual(row["item_id"], "a")

    def test_a_header_below_a_blank_line_is_still_the_header(self):
        path = self.path("log.csv")
        Path(path).write_text("\nlogged_at,item_id,title\n", encoding="utf-8")

        with contextlib.redirect_stderr(io.StringIO()):
            mp.append_bargain_log(path, [make_listing(item_id="a", is_new=True, is_bargain=True)])
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        # The file's own columns win, no second header is written under them,
        # and the blank line the file came with is left where it was — there
        # are rows under it, so this one is not ours to rewrite.
        self.assertEqual(lines[0], "")
        self.assertEqual(lines[1], "logged_at,item_id,title")
        self.assertEqual(len(lines[2].split(",")), 3)

    def test_columns_the_file_lacks_are_reported_not_dropped_in_silence(self):
        path = self.path("log.csv")
        Path(path).write_text("logged_at,item_id,title\n", encoding="utf-8")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            mp.append_bargain_log(path, [make_listing(is_new=True, is_bargain=True)])
        self.assertIn("deal_score", stderr.getvalue())

    def test_a_column_the_listing_no_longer_has_stays_empty(self):
        path = self.path("log.csv")
        Path(path).write_text("logged_at,item_id,verdwenen_veld\n", encoding="utf-8")

        with contextlib.redirect_stderr(io.StringIO()):
            mp.append_bargain_log(path, [make_listing(item_id="a", is_new=True, is_bargain=True)])
        (row,) = read_csv_rows(path)
        self.assertEqual(row["verdwenen_veld"], "")


class CsvExportTest(TempDirTest):
    def test_every_dataclass_field_is_exported(self):
        path = self.path("out.csv")
        mp.write_csv([make_listing()], path)
        header = Path(path).read_text(encoding="utf-8").splitlines()[0]
        for field in ("item_id", "price_eur", "deal_score", "bid_open", "ref_label"):
            self.assertIn(field, header)

    def test_empty_result_writes_the_headers_and_says_so(self):
        # A blank file looks corrupt; a header-only file opens as an empty
        # table, which is what an empty run actually produced.
        path = self.path("out.csv")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            mp.write_csv([], path)
        header = Path(path).read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(header.startswith("item_id,title,"))
        self.assertIn("kolomkoppen", stderr.getvalue())
        self.assertEqual(read_csv_rows(path), [])


class QueryPathTest(unittest.TestCase):
    def test_slug_is_filesystem_safe(self):
        self.assertEqual(mp.safe_query_slug("Canon EOS 700D"), "canon-eos-700d")
        self.assertEqual(mp.safe_query_slug("!!!"), "query")

    def test_single_query_keeps_the_plain_path(self):
        self.assertEqual(mp.per_query_path("report.html", "racefiets", multi=False), "report.html")

    def test_multiple_queries_get_their_own_file(self):
        self.assertEqual(
            mp.per_query_path("report.html", "luidsprekers", multi=True),
            "report_luidsprekers.html",
        )


if __name__ == "__main__":
    unittest.main()
