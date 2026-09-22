"""Watchlist: named searches with their own filters (fase 8 of
PLAN_FIETSWAARDE.md).

The acceptance criterion is isolation: a "powermeter" watchlist runs with its
own price filters without the bike queries noticing — and the reverse, the
bike query's filters don't leak into the watchlist either. main() is driven
with a faked collect_listings(), the same way test_db_wiring.py does it, so no
network call happens.
"""
import contextlib
import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import make_listing, mp, repo_file

import db


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db_path = self.path("koopjes.db")

    def path(self, name: str) -> str:
        return str(self.tmp / name)

    def base_argv(self):
        return [
            "--no-html", "--no-log", "--no-price-history", "--no-notify-better",
            "--open-browser", "never",
            "--db", self.db_path,
            "--history-file", self.path("history.json"),
            "--reference-file", self.path("geen-referentie.csv"),
            "--price-history-file", self.path("geen-price-history.csv"),
            "--output", self.path("out.csv"),
        ]

    def run_main(self, argv, listings_by_query=None):
        """Returns (exit code, queries crawled, stdout, stderr)."""
        listings_by_query = listings_by_query or {}
        crawled = []
        self.crawl_options = []

        def fake_collect(query, pages, delay, **crawl_options):
            crawled.append(query)
            self.crawl_options.append(crawl_options)
            return mp.CrawlResult(listings_by_query.get(query, []), complete=True)

        def fake_enrich(ls, delay, mode, session=None):
            pass

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(mp, "collect_listings", fake_collect), mock.patch.object(
            mp, "enrich_bid_listings", fake_enrich
        ):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = mp.main(argv)
        return code, crawled, out.getvalue(), err.getvalue()

    def csv_ids(self, name):
        with open(self.path(name), newline="", encoding="utf-8") as f:
            return {row["item_id"] for row in csv.DictReader(f)}


class DbWatchlistTest(TempDirTest):
    def test_save_get_list_delete(self):
        conn = db.connect(self.db_path)
        db.save_watchlist(conn, "powermeter", "powermeter", {"max_price": 400.0})
        db.save_watchlist(conn, "computer", "wahoo,garmin edge", {})

        entry = db.get_watchlist(conn, "powermeter")
        self.assertEqual(entry["query"], "powermeter")
        self.assertEqual(entry["filters"], {"max_price": 400.0})
        self.assertTrue(entry["active"])
        self.assertEqual([e["name"] for e in db.list_watchlists(conn)], ["computer", "powermeter"])

        self.assertTrue(db.delete_watchlist(conn, "computer"))
        self.assertFalse(db.delete_watchlist(conn, "computer"))
        self.assertIsNone(db.get_watchlist(conn, "computer"))
        conn.close()

    def test_saving_the_same_name_replaces_it(self):
        conn = db.connect(self.db_path)
        db.save_watchlist(conn, "powermeter", "powermeter", {"max_price": 400.0})
        db.save_watchlist(conn, "powermeter", "assioma", {"max_price": 300.0})
        rows = db.list_watchlists(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["query"], "assioma")
        self.assertEqual(rows[0]["filters"], {"max_price": 300.0})
        conn.close()

    def test_active_only_skips_inactive(self):
        conn = db.connect(self.db_path)
        db.save_watchlist(conn, "aan", "a", {})
        db.save_watchlist(conn, "uit", "b", {}, active=False)
        self.assertEqual([e["name"] for e in db.list_watchlists(conn, active_only=True)], ["aan"])
        conn.close()

    def test_unreadable_filters_refuse_instead_of_running_unfiltered(self):
        conn = db.connect(self.db_path)
        conn.execute(
            "INSERT INTO watchlist (name, query, filters_json) VALUES ('kapot', 'x', '{niet json')"
        )
        conn.commit()
        with self.assertRaises(ValueError):
            db.get_watchlist(conn, "kapot")
        conn.close()


class FilterStorageTest(unittest.TestCase):
    def test_only_non_default_filters_are_stored(self):
        args = mp.parse_args([
            "--query", "powermeter", "--max-price", "400",
            "--reference-file", "reference_bike_accessories.csv",
            # Not a filter: how the run is done, not what it looks for.
            "--pages", "3", "--delay", "5",
        ])
        self.assertEqual(
            mp.watchlist_filters_from_args(args),
            {"max_price": 400.0, "reference_file": "reference_bike_accessories.csv"},
        )

    def test_bid_lookup_is_not_stored(self):
        # It decides how many requests a run makes, like --pages.
        args = mp.parse_args(["--query", "x", "--bid-lookup", "all"])
        self.assertEqual(mp.watchlist_filters_from_args(args), {})

    def test_watchlist_run_starts_from_defaults_not_from_the_command_line(self):
        args = mp.parse_args([
            "--query", "racefiets", "--max-frame-height", "58", "--max-price", "150",
            "--bids-only", "--no-bid-lookup", "--pages", "3",
        ])
        entry = {"name": "powermeter", "query": "powermeter", "filters": {"min_price": 100.0}}
        run_args = mp.args_for_watchlist(args, entry)

        self.assertEqual(run_args.min_price, 100.0)
        self.assertIsNone(run_args.max_price)
        self.assertIsNone(run_args.max_frame_height)
        self.assertFalse(run_args.bids_only)
        # Run settings do carry over — including the bid lookup: found in a
        # live run, where --bid-lookup none was quietly reset to fast and the
        # watchlist fetched 24 listing pages it was told not to.
        self.assertEqual(run_args.pages, 3)
        self.assertTrue(run_args.no_bid_lookup)
        # And the original is untouched, for the regular query.
        self.assertEqual(args.max_price, 150.0)
        self.assertEqual(args.max_frame_height, 58.0)

    def test_a_stored_bid_lookup_from_before_is_ignored_with_a_warning(self):
        args = mp.parse_args(["--bid-lookup", "none"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            run_args = mp.args_for_watchlist(
                args, {"name": "oud", "query": "x", "filters": {"bid_lookup": "all"}}
            )
        self.assertEqual(run_args.bid_lookup, "none")
        self.assertIn("bid_lookup", err.getvalue())

    def test_unknown_filter_key_is_an_error(self):
        args = mp.parse_args([])
        entry = {"name": "x", "query": "x", "filters": {"pages": 0}}
        with self.assertRaises(ValueError):
            mp.args_for_watchlist(args, entry)


class FilterValidationTest(unittest.TestCase):
    def test_a_value_of_the_wrong_type_is_refused(self):
        args = mp.parse_args([])
        for filters in [{"max_price": "400"}, {"bids_only": 1},
                        {"category": ["fietsonderdelen"]}, {"max_price": True}]:
            with self.subTest(filters=filters):
                with self.assertRaises(ValueError):
                    mp.args_for_watchlist(args, {"name": "x", "query": "x", "filters": filters})

    def test_valid_values_pass(self):
        args = mp.parse_args([])
        run_args = mp.args_for_watchlist(args, {"name": "x", "query": "x", "filters": {
            "max_price": 400, "bids_only": True,
            "category": "fietsonderdelen", "strict_frame_height": True,
        }})
        self.assertEqual(run_args.max_price, 400)
        self.assertEqual(run_args.category, "fietsonderdelen")
        self.assertTrue(run_args.strict_frame_height)


class ManageTest(TempDirTest):
    def test_add_list_remove(self):
        code, crawled, out, _ = self.run_main([
            "--db", self.db_path, "--watchlist-add", "powermeter",
            "--query", "powermeter", "--min-price", "100", "--max-price", "400",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(crawled, [])

        code, _, out, _ = self.run_main(["--db", self.db_path, "--watchlist-list"])
        self.assertEqual(code, 0)
        self.assertIn("powermeter: --query 'powermeter' --max-price 400.0 --min-price 100.0", out)

        code, _, _, _ = self.run_main(["--db", self.db_path, "--watchlist-remove", "powermeter"])
        self.assertEqual(code, 0)
        code, _, _, err = self.run_main(["--db", self.db_path, "--watchlist-remove", "powermeter"])
        self.assertEqual(code, 1)

    def test_add_needs_a_query_and_a_usable_name(self):
        code, _, _, err = self.run_main(["--db", self.db_path, "--watchlist-add", "x"])
        self.assertEqual(code, 1)
        self.assertIn("--query", err)
        code, _, _, _ = self.run_main(
            ["--db", self.db_path, "--watchlist-add", "all", "--query", "x"]
        )
        self.assertEqual(code, 1)

    def test_category_and_strict_frame_height_are_stored(self):
        self.run_main([
            "--db", self.db_path, "--watchlist-add", "powermeter", "--query", "powermeter",
            "--category", "fietsonderdelen", "--strict-frame-height",
        ])
        conn = db.connect(self.db_path)
        self.assertEqual(
            db.get_watchlist(conn, "powermeter")["filters"],
            {"category": "fietsonderdelen", "strict_frame_height": True},
        )
        conn.close()

    def test_a_missing_reference_file_is_warned_about(self):
        _, _, _, err = self.run_main([
            "--db", self.db_path, "--watchlist-add", "pm", "--query", "powermeter",
            "--reference-file", self.path("bestaat-niet.csv"),
        ])
        self.assertIn("bestaat-niet.csv niet gevonden", err)

    def test_running_and_managing_in_one_command_is_refused(self):
        code, crawled, _, err = self.run_main(
            ["--db", self.db_path, "--watchlist", "all", "--watchlist-list"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(crawled, [])

    def test_list_without_database_does_not_create_one(self):
        code, _, out, _ = self.run_main(["--db", self.db_path, "--watchlist-list"])
        self.assertEqual(code, 0)
        self.assertFalse(Path(self.db_path).exists())


class IsolationTest(TempDirTest):
    """PLAN_FIETSWAARDE.md fase 8, acceptance: a "powermeter" watchlist runs
    with its own price filters without affecting the bike queries."""

    def setUp(self):
        super().setUp()
        conn = db.connect(self.db_path)
        db.save_watchlist(
            conn,
            "powermeter",
            "powermeter",
            {
                "min_price": 100.0,
                "max_price": 400.0,
                "reference_file": repo_file("reference_bike_accessories.csv"),
            },
        )
        conn.close()
        self.listings = {
            "racefiets": [
                make_listing(item_id="fiets-goedkoop", title="Giant Defy", price_eur=120.0),
                make_listing(item_id="fiets-duur", title="Giant Defy", price_eur=350.0),
            ],
            "powermeter": [
                make_listing(item_id="pm-te-goedkoop", title="Assioma Uno kapot", price_eur=40.0),
                make_listing(item_id="pm-ok", title="Favero Assioma Duo", price_eur=350.0),
                make_listing(item_id="pm-te-duur", title="Assioma Duo Shi nieuw", price_eur=600.0),
            ],
        }

    def test_each_side_keeps_its_own_filters_and_report(self):
        code, crawled, _, err = self.run_main(
            self.base_argv()
            + ["--query", "racefiets", "--max-price", "150", "--watchlist", "powermeter"],
            self.listings,
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(crawled, ["racefiets", "powermeter"])

        # The bike query: its own --max-price 150, nothing from the watchlist.
        self.assertEqual(self.csv_ids("out.csv"), {"fiets-goedkoop"})
        # The watchlist: 100-400, not the command line's max 150, and its own
        # file rather than the bike report's.
        self.assertEqual(self.csv_ids("out_powermeter.csv"), {"pm-ok"})

    def test_watchlist_reference_file_matches_its_own_models(self):
        self.run_main(self.base_argv() + ["--watchlist", "powermeter"], self.listings)
        with open(self.path("out_powermeter.csv"), newline="", encoding="utf-8") as f:
            rows = {r["item_id"]: r for r in csv.DictReader(f)}
        self.assertEqual(rows["pm-ok"]["ref_label"], "Favero Assioma Duo")

        conn = sqlite3.connect(self.db_path)
        kinds = {
            r[0]
            for r in conn.execute(
                "SELECT m.kind FROM listing_model lm JOIN model m ON m.id = lm.model_id "
                "WHERE lm.listing_id = 'pm-ok'"
            )
        }
        conn.close()
        self.assertEqual(kinds, {"powermeter"})

    def test_the_watchlist_category_reaches_the_crawl_and_the_cli_one_does_not(self):
        conn = db.connect(self.db_path)
        db.save_watchlist(conn, "onderdelen", "powermeter", {"category": "fietsonderdelen"})
        conn.close()
        self.run_main(
            self.base_argv() + ["--query", "racefiets", "--category", "fietsen-racefietsen",
                                "--sort", "newest", "--watchlist", "onderdelen"],
            self.listings,
        )
        by_query = dict(zip(["racefiets", "onderdelen"], self.crawl_options))
        self.assertEqual(by_query["racefiets"]["categories"], ["fietsen-racefietsen"])
        self.assertEqual(by_query["onderdelen"]["categories"], ["fietsonderdelen"])
        # The sort order is how the run is done, so it carries over.
        self.assertEqual(by_query["onderdelen"]["sort"], "newest")

    def test_frame_size_filter_keeps_unknown_sizes_unless_strict(self):
        listings = {"racefiets": [
            make_listing(item_id="past", frame_height="53 tot 57 cm"),
            make_listing(item_id="te-groot", frame_height="61 cm of meer"),
            make_listing(item_id="onbekend", frame_height=""),
        ]}
        self.run_main(self.base_argv() + ["--min-frame-height", "54", "--max-frame-height", "58"], listings)
        self.assertEqual(self.csv_ids("out.csv"), {"past", "onbekend"})
        self.run_main(
            self.base_argv() + ["--min-frame-height", "54", "--max-frame-height", "58", "--strict-frame-height"],
            listings,
        )
        self.assertEqual(self.csv_ids("out.csv"), {"past"})

    def test_without_query_only_the_watchlist_runs(self):
        code, crawled, _, _ = self.run_main(
            self.base_argv() + ["--watchlist", "powermeter"], self.listings
        )
        self.assertEqual(code, 0)
        self.assertEqual(crawled, ["powermeter"])
        self.assertFalse(Path(self.path("out.csv")).exists())

    def test_plain_run_still_defaults_to_racefiets(self):
        code, crawled, _, _ = self.run_main(self.base_argv(), self.listings)
        self.assertEqual(code, 0)
        self.assertEqual(crawled, ["racefiets"])

    def test_all_runs_every_active_watchlist(self):
        conn = db.connect(self.db_path)
        db.save_watchlist(conn, "computer", "wahoo", {})
        db.save_watchlist(conn, "uit", "iets", {}, active=False)
        conn.close()
        code, crawled, _, _ = self.run_main(self.base_argv() + ["--watchlist", "all"], self.listings)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(crawled), ["powermeter", "wahoo"])

    def test_unknown_watchlist_fails_before_anything_is_crawled(self):
        code, crawled, _, err = self.run_main(
            self.base_argv() + ["--query", "racefiets", "--watchlist", "powermeter,typo"],
            self.listings,
        )
        self.assertEqual(code, 1)
        self.assertEqual(crawled, [])
        self.assertIn("typo", err)

    def test_missing_database_is_an_error_not_an_empty_db(self):
        Path(self.db_path).unlink()
        code, crawled, _, err = self.run_main(
            self.base_argv() + ["--watchlist", "powermeter"], self.listings
        )
        self.assertEqual(code, 1)
        self.assertEqual(crawled, [])
        self.assertFalse(Path(self.db_path).exists())


if __name__ == "__main__":
    unittest.main()
