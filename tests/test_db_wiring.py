"""racefiets_jev.py <-> db.py wiring (fase 1b of PLAN_FIETSWAARDE.md).

test_db.py covers db.py standalone; these tests cover the other side, using
run_for_query() with a faked collect_listings() the same way test_bids.py
does, so no real network call happens.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import make_listing, mp

import db


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def path(self, name: str) -> str:
        return str(self.tmp / name)

    def run_query(self, listings, extra_argv):
        def fake_collect(query, pages, delay):
            return list(listings)

        def fake_enrich(ls, delay, mode, session=None):
            pass

        argv = [
            "--query", "test", "--no-html", "--no-log", "--no-price-history",
            "--no-notify-better", "--open-browser", "never",
            "--history-file", self.path("history.json"),
            "--reference-file", self.path("geen-referentie.csv"),
            "--price-history-file", self.path("geen-price-history.csv"),
        ] + extra_argv
        args = mp.parse_args(argv)

        with mock.patch.object(mp, "collect_listings", fake_collect), mock.patch.object(
            mp, "enrich_bid_listings", fake_enrich
        ):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                mp.run_for_query(args, "test", False)
        return args


class NoDbTest(TempDirTest):
    def test_no_db_writes_nothing(self):
        db_path = self.path("koopjes.db")
        self.run_query([make_listing(item_id="a")], ["--no-db", "--db", db_path])
        self.assertFalse(Path(db_path).exists())


class SyncListingsTest(TempDirTest):
    def test_a_run_upserts_its_listings_and_logs_a_crawl(self):
        db_path = self.path("koopjes.db")
        self.run_query(
            [make_listing(item_id="a", price_eur=123.0), make_listing(item_id="b", price_eur=None)],
            ["--db", db_path, "--pages", "1"],
        )

        conn = db.connect(db_path)
        rows = {r["item_id"]: r for r in conn.execute("SELECT * FROM listing").fetchall()}
        self.assertEqual(set(rows), {"a", "b"})
        self.assertEqual(rows["a"]["price_eur"], 123.0)
        self.assertEqual(rows["a"]["query"], "test")

        prices = conn.execute("SELECT * FROM listing_price WHERE item_id='a'").fetchall()
        self.assertEqual(len(prices), 1)
        # A priceless listing (a FAST_BID never looked up) gets no fabricated
        # observation.
        self.assertEqual(
            conn.execute("SELECT COUNT(*) AS n FROM listing_price WHERE item_id='b'").fetchone()["n"],
            0,
        )

        runs = conn.execute("SELECT * FROM crawl_run").fetchall()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["query"], "test")
        self.assertEqual(runs[0]["pages_requested"], 1)
        self.assertEqual(runs[0]["listing_count"], 2)

    def test_explicit_paths_are_always_passed_to_import_legacy(self):
        # If sync_database() ever left one of the three legacy paths out, it
        # would silently fall back to db.import_legacy()'s own defaults —
        # which, since tests run with the repo root as cwd, means the real
        # checked-in reference_prices.csv. Catch that here rather than in
        # test_db.py, since it's specifically about what racefiets_jev.py
        # hands to db.import_legacy().
        db_path = self.path("koopjes.db")
        with mock.patch.object(db, "import_legacy", wraps=db.import_legacy) as spy:
            self.run_query([make_listing(item_id="a")], ["--db", db_path])

        self.assertEqual(spy.call_count, 1)
        _, kwargs = spy.call_args
        self.assertEqual(kwargs["seen_listings_path"], self.path("history.json"))
        self.assertEqual(kwargs["reference_prices_path"], self.path("geen-referentie.csv"))
        self.assertEqual(
            kwargs["reference_price_history_path"], self.path("geen-price-history.csv")
        )


class DisappearanceSweepTest(TempDirTest):
    def test_a_shallow_crawl_never_sweeps(self):
        db_path = self.path("koopjes.db")
        self.run_query([make_listing(item_id="a")], ["--db", db_path, "--pages", "3"])
        # Second run, same query, "a" no longer turns up. --pages 3 is not a
        # full crawl, so nothing should be marked disappeared.
        self.run_query([make_listing(item_id="b")], ["--db", db_path, "--pages", "3"])

        conn = db.connect(db_path)
        row = conn.execute("SELECT disappeared_at FROM listing WHERE item_id='a'").fetchone()
        self.assertIsNone(row["disappeared_at"])

    def test_a_full_crawl_sweeps_listings_that_did_not_turn_up(self):
        db_path = self.path("koopjes.db")
        self.run_query([make_listing(item_id="a")], ["--db", db_path, "--pages", "0"])
        self.run_query([make_listing(item_id="b")], ["--db", db_path, "--pages", "0"])

        conn = db.connect(db_path)
        gone = conn.execute("SELECT disappeared_at FROM listing WHERE item_id='a'").fetchone()
        self.assertIsNotNone(gone["disappeared_at"])
        still_here = conn.execute("SELECT disappeared_at FROM listing WHERE item_id='b'").fetchone()
        self.assertIsNone(still_here["disappeared_at"])

    def test_a_filter_does_not_make_listings_look_disappeared(self):
        # The sweep has to compare against what the crawl saw, not against
        # what survived --max-price: those listings are still online, they
        # are only out of this report. Marking them gone also writes a
        # days_online that fase 3 would later take at face value.
        db_path = self.path("koopjes.db")
        listings = [
            make_listing(item_id="goedkoop", price_eur=50.0),
            make_listing(item_id="duur", price_eur=2000.0),
        ]
        self.run_query(listings, ["--db", db_path, "--pages", "0"])
        self.run_query(listings, ["--db", db_path, "--pages", "0", "--max-price", "150"])

        conn = db.connect(db_path)
        rows = {
            r["item_id"]: r
            for r in conn.execute("SELECT item_id, disappeared_at, days_online FROM listing")
        }
        self.assertIsNone(rows["duur"]["disappeared_at"])
        self.assertIsNone(rows["duur"]["days_online"])
        self.assertIsNone(rows["goedkoop"]["disappeared_at"])

    def test_a_listing_that_reappears_is_no_longer_disappeared(self):
        db_path = self.path("koopjes.db")
        self.run_query([make_listing(item_id="a")], ["--db", db_path, "--pages", "0"])
        self.run_query([], ["--db", db_path, "--pages", "0"])
        conn = db.connect(db_path)
        self.assertIsNotNone(
            conn.execute("SELECT disappeared_at FROM listing WHERE item_id='a'").fetchone()[
                "disappeared_at"
            ]
        )

        self.run_query([make_listing(item_id="a")], ["--db", db_path, "--pages", "0"])
        conn = db.connect(db_path)
        self.assertIsNone(
            conn.execute("SELECT disappeared_at FROM listing WHERE item_id='a'").fetchone()[
                "disappeared_at"
            ]
        )


class SpecAndModelWiringTest(TempDirTest):
    """fase 2: extract_specs() and every reference match land in the DB
    alongside what fase 1b already wired up, without changing report
    behaviour."""

    def write_reference(self, rows: str) -> str:
        path = self.path("reference.csv")
        Path(path).write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline\n" + rows,
            encoding="utf-8",
        )
        return path

    def test_specs_are_written_for_a_synced_listing(self):
        db_path = self.path("koopjes.db")
        self.run_query(
            [make_listing(item_id="a", title="Carbon frame", description="velgrem, 11-speed")],
            ["--db", db_path],
        )
        conn = db.connect(db_path)
        rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM spec")}
        self.assertEqual(
            rows, {"frame_material": "carbon", "brake_type": "velrem", "speeds": "11"}
        )

    def test_every_reference_match_lands_in_listing_model(self):
        db_path = self.path("koopjes.db")
        ref_path = self.write_reference(
            "Mission 731,Specifiek,300,,,\nMission,Algemeen,100,,,\n"
        )
        listing = make_listing(item_id="a", title="Mission 731 speakers", price_eur=60.0)
        self.run_query([listing], ["--db", db_path, "--reference-file", ref_path])

        conn = db.connect(db_path)
        matched = {
            r["model"]
            for r in conn.execute(
                "SELECT m.model FROM listing_model lm JOIN model m ON m.id = lm.model_id "
                "WHERE lm.listing_id = 'a'"
            )
        }
        self.assertEqual(matched, {"Specifiek", "Algemeen"})
        # The "Beter dan referentie" filter's own field is untouched by
        # having more than one match: it's still only the first one.
        self.assertEqual(listing.ref_label, "Specifiek")


if __name__ == "__main__":
    unittest.main()
