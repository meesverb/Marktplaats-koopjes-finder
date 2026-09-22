"""db.py — the SQLite schema and the legacy-file import (fase 1a).

racefiets_jev.py doesn't call any of this yet (fase 1b wires it in); these
tests work directly against db.py with throwaway files, per
PLAN_FIETSWAARDE.md fase 1a's acceptance criteria.
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import mp  # noqa: F401  (adds the repo root to sys.path)

import db


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def path(self, name: str) -> str:
        return str(self.tmp / name)

    def import_legacy(self, conn, **kwargs) -> dict:
        """db.import_legacy() with every path defaulted to a file that does
        not exist in the tmp dir. Without this, a test that only overrides
        one of the three paths would fall back to db.import_legacy()'s own
        defaults ("seen_listings.json", "reference_prices.csv") — which,
        since tests run with the repo root as cwd, would silently import the
        real, checked-in reference_prices.csv (and any seen_listings.json
        left over from a manual run) instead of nothing."""
        kwargs.setdefault("seen_listings_path", self.path("__absent_seen_listings.json"))
        kwargs.setdefault("reference_prices_path", self.path("__absent_reference_prices.csv"))
        kwargs.setdefault(
            "reference_price_history_path", self.path("__absent_reference_price_history.csv")
        )
        return db.import_legacy(conn, **kwargs)


class SchemaTest(TempDirTest):
    def test_connect_creates_every_table(self):
        conn = db.connect(self.path("koopjes.db"))
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "crawl_run", "listing", "listing_price", "model", "listing_model",
            "spec", "owned_item", "valuation", "valuation_evidence",
            "component_price", "schema_version", "watchlist",
        }
        self.assertTrue(expected.issubset(tables))

    def test_reconnecting_does_not_duplicate_schema_version_rows(self):
        path = self.path("koopjes.db")
        db.connect(path).close()
        conn = db.connect(path)
        rows = conn.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()
        self.assertEqual(rows["n"], 1)

    def test_foreign_keys_are_enforced(self):
        conn = db.connect(self.path("koopjes.db"))
        with self.assertRaises(Exception):
            conn.execute(
                "INSERT INTO listing_price (item_id, observed_at, price_eur) "
                "VALUES ('does-not-exist', '2026-01-01T00:00:00Z', 10.0)"
            )


class ImportSeenListingsTest(TempDirTest):
    def write_history(self, data: dict) -> str:
        path = self.path("seen_listings.json")
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_missing_file_imports_nothing(self):
        conn = db.connect(self.path("koopjes.db"))
        counts = self.import_legacy(conn, seen_listings_path=self.path("nope.json"))
        self.assertEqual(counts["listings_from_history"], 0)

    def test_entries_become_listing_and_listing_price_rows(self):
        path = self.write_history(
            {
                "m1": {
                    "first_seen": "2026-01-01T00:00:00Z",
                    "last_seen": "2026-01-05T00:00:00Z",
                    "title": "Giant Defy 2012",
                    "last_price": 450.0,
                }
            }
        )
        conn = db.connect(self.path("koopjes.db"))
        counts = self.import_legacy(conn, seen_listings_path=path)
        self.assertEqual(counts["listings_from_history"], 1)

        listing = conn.execute("SELECT * FROM listing WHERE item_id='m1'").fetchone()
        self.assertEqual(listing["title"], "Giant Defy 2012")
        self.assertEqual(listing["price_eur"], 450.0)
        self.assertEqual(listing["first_seen"], "2026-01-01T00:00:00Z")

        prices = conn.execute("SELECT * FROM listing_price WHERE item_id='m1'").fetchall()
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0]["price_eur"], 450.0)

    def test_importing_twice_does_not_duplicate_rows(self):
        path = self.write_history(
            {"m1": {"first_seen": "t0", "last_seen": "t1", "title": "X", "last_price": 100.0}}
        )
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, seen_listings_path=path)
        self.import_legacy(conn, seen_listings_path=path)

        self.assertEqual(
            conn.execute("SELECT COUNT(*) AS n FROM listing").fetchone()["n"], 1
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) AS n FROM listing_price").fetchone()["n"], 1
        )

    def test_entry_without_a_price_gets_no_listing_price_row(self):
        path = self.write_history(
            {"m1": {"first_seen": "t0", "last_seen": "t1", "title": "X", "last_price": None}}
        )
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, seen_listings_path=path)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) AS n FROM listing_price").fetchone()["n"], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) AS n FROM listing").fetchone()["n"], 1
        )


class ImportReferencePricesTest(TempDirTest):
    def write_reference(self, rows: str) -> str:
        path = self.path("reference_prices.csv")
        Path(path).write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline\n" + rows,
            encoding="utf-8",
        )
        return path

    def test_missing_file_imports_nothing(self):
        conn = db.connect(self.path("koopjes.db"))
        counts = self.import_legacy(conn, reference_prices_path=self.path("nope.csv"))
        self.assertEqual(counts["models_from_reference"], 0)

    def test_row_becomes_a_model(self):
        path = self.write_reference('Mission 731,Mission 731,300,"89 dB",7/10,1\n')
        conn = db.connect(self.path("koopjes.db"))
        counts = self.import_legacy(conn, reference_prices_path=path)
        self.assertEqual(counts["models_from_reference"], 1)

        row = conn.execute("SELECT * FROM model WHERE pattern='Mission 731'").fetchone()
        self.assertEqual(row["model"], "Mission 731")
        self.assertEqual(row["kind"], "other")
        self.assertEqual(row["original_price_eur"], 300.0)
        self.assertEqual(row["score"], "7/10")
        extra = json.loads(row["specs_json"])
        self.assertEqual(extra["specs"], "89 dB")
        self.assertTrue(extra["better_than_baseline"])

    def test_blank_original_price_is_allowed(self):
        path = self.write_reference("Mission 731,Mission 731,,,,\n")
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, reference_prices_path=path)
        row = conn.execute("SELECT * FROM model WHERE pattern='Mission 731'").fetchone()
        self.assertIsNone(row["original_price_eur"])

    def test_an_unreadable_original_price_does_not_abort_the_import(self):
        # This column is maintained by hand, so "ca. 300" will happen. One bad
        # cell used to raise ValueError out of import_legacy(), which rolls
        # back the migration of every other file with it.
        path = self.write_reference(
            "Mission 731,Mission 731,ca. 300,,,\n" "Wharfedale,Wharfedale Diamond,120,,,\n"
        )
        conn = db.connect(self.path("koopjes.db"))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            counts = self.import_legacy(conn, reference_prices_path=path)

        self.assertEqual(counts["models_from_reference"], 2)
        self.assertIn("ca. 300", stderr.getvalue())
        rows = {
            r["pattern"]: r["original_price_eur"]
            for r in conn.execute("SELECT pattern, original_price_eur FROM model")
        }
        self.assertIsNone(rows["Mission 731"])
        self.assertEqual(rows["Wharfedale"], 120.0)

    def test_rows_without_a_pattern_are_ignored(self):
        path = self.write_reference(",Geen patroon,100,,,\n")
        conn = db.connect(self.path("koopjes.db"))
        counts = self.import_legacy(conn, reference_prices_path=path)
        self.assertEqual(counts["models_from_reference"], 0)

    def test_importing_twice_updates_in_place(self):
        path = self.write_reference("Mission 731,Mission 731,300,old specs,6/10,0\n")
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, reference_prices_path=path)

        path = self.write_reference("Mission 731,Mission 731,320,new specs,8/10,1\n")
        self.import_legacy(conn, reference_prices_path=path)

        self.assertEqual(
            conn.execute("SELECT COUNT(*) AS n FROM model").fetchone()["n"], 1
        )
        row = conn.execute("SELECT * FROM model WHERE pattern='Mission 731'").fetchone()
        self.assertEqual(row["original_price_eur"], 320.0)
        self.assertEqual(row["score"], "8/10")


class ImportReferencePriceHistoryTest(TempDirTest):
    def write_history_csv(self, rows: str) -> str:
        path = self.path("reference_price_history.csv")
        Path(path).write_text("date,ref_label,item_id,price_eur,title\n" + rows, encoding="utf-8")
        return path

    def test_missing_file_imports_nothing(self):
        conn = db.connect(self.path("koopjes.db"))
        counts = self.import_legacy(conn, reference_price_history_path=self.path("nope.csv"))
        self.assertEqual(counts["prices_from_reference_history"], 0)

    def test_row_becomes_a_listing_price_and_a_listing_stub(self):
        path = self.write_history_csv("2026-01-01T00:00:00Z,Model A,m9,55.0,Some title\n")
        conn = db.connect(self.path("koopjes.db"))
        counts = self.import_legacy(conn, reference_price_history_path=path)
        self.assertEqual(counts["prices_from_reference_history"], 1)

        listing = conn.execute("SELECT * FROM listing WHERE item_id='m9'").fetchone()
        self.assertIsNotNone(listing)
        self.assertEqual(listing["title"], "Some title")

        price = conn.execute("SELECT * FROM listing_price WHERE item_id='m9'").fetchone()
        self.assertEqual(price["price_eur"], 55.0)
        self.assertEqual(price["observed_at"], "2026-01-01T00:00:00Z")

    def test_does_not_overwrite_an_already_known_listing(self):
        conn = db.connect(self.path("koopjes.db"))
        conn.execute("INSERT INTO listing (item_id, title) VALUES ('m9', 'Real title')")
        conn.commit()
        path = self.write_history_csv("2026-01-01T00:00:00Z,Model A,m9,55.0,Stale title\n")
        self.import_legacy(conn, reference_price_history_path=path)
        listing = conn.execute("SELECT * FROM listing WHERE item_id='m9'").fetchone()
        self.assertEqual(listing["title"], "Real title")

    def test_importing_twice_does_not_duplicate_rows(self):
        path = self.write_history_csv("2026-01-01T00:00:00Z,Model A,m9,55.0,Some title\n")
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, reference_price_history_path=path)
        self.import_legacy(conn, reference_price_history_path=path)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) AS n FROM listing_price").fetchone()["n"], 1
        )

    def test_row_missing_a_price_is_skipped(self):
        path = self.write_history_csv("2026-01-01T00:00:00Z,Model A,m9,,Some title\n")
        conn = db.connect(self.path("koopjes.db"))
        counts = self.import_legacy(conn, reference_price_history_path=path)
        self.assertEqual(counts["prices_from_reference_history"], 0)


class ExportCsvTest(TempDirTest):
    def test_export_round_trips_through_load_reference_data(self):
        reference_path = self.path("reference_prices.csv")
        Path(reference_path).write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline\n"
            'Mission 731,Mission 731,300,"89 dB",7/10,1\n'
            "Wharfedale,Wharfedale,,,,\n",
            encoding="utf-8",
        )
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, reference_prices_path=reference_path)

        out_path = self.path("exported.csv")
        written = db.export_csv(conn, out_path)
        self.assertEqual(written, 2)

        reloaded = mp.load_reference_data(out_path)
        self.assertEqual([r["label"] for r in reloaded], ["Mission 731", "Wharfedale"])
        self.assertEqual(reloaded[0]["original_price_eur"], 300.0)
        self.assertEqual(reloaded[0]["specs"], "89 dB")
        self.assertTrue(reloaded[0]["better"])
        self.assertIsNone(reloaded[1]["original_price_eur"])
        self.assertFalse(reloaded[1]["better"])

    def test_export_preserves_file_order_for_first_match_wins(self):
        reference_path = self.path("reference_prices.csv")
        Path(reference_path).write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline\n"
            "Mission 731,Specifiek,300,,,\n"
            "Mission,Algemeen,100,,,\n",
            encoding="utf-8",
        )
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, reference_prices_path=reference_path)
        out_path = self.path("exported.csv")
        db.export_csv(conn, out_path)

        reloaded = mp.load_reference_data(out_path)
        self.assertEqual([r["label"] for r in reloaded], ["Specifiek", "Algemeen"])

    def test_empty_model_table_still_writes_a_header(self):
        conn = db.connect(self.path("koopjes.db"))
        out_path = self.path("exported.csv")
        written = db.export_csv(conn, out_path)
        self.assertEqual(written, 0)
        self.assertEqual(mp.load_reference_data(out_path), [])


if __name__ == "__main__":
    unittest.main()
