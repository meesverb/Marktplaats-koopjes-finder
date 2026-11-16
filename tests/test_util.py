"""util.py en db.connect_readonly(): de hulpfuncties die bij de opschoning van
16-11-2026 de kopieën in de modules vervingen."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from helpers import mp  # noqa: F401  (zet de repo-root in sys.path)

import db
import util


class ParseTimeTest(unittest.TestCase):
    def test_reads_what_the_database_stores(self):
        self.assertEqual(util.parse_time("2026-09-28T10:00:00+00:00"),
                         datetime(2026, 9, 28, 10, tzinfo=timezone.utc))

    def test_anything_else_is_none(self):
        for value in (None, "", "gisteren", 12):
            with self.subTest(value=value):
                self.assertIsNone(util.parse_time(value))
                self.assertIsNone(util.parse_time_utc(value))

    def test_without_a_timezone_it_stays_naive_unless_asked(self):
        self.assertIsNone(util.parse_time("2026-09-28T10:00:00").tzinfo)
        self.assertEqual(util.parse_time_utc("2026-09-28T10:00:00"),
                         datetime(2026, 9, 28, 10, tzinfo=timezone.utc))

    def test_the_listing_page_writes_z(self):
        self.assertEqual(util.parse_time_utc("2026-09-28T10:00:00Z"),
                         datetime(2026, 9, 28, 10, tzinfo=timezone.utc))


class EuroTest(unittest.TestCase):
    def test_whole_euros_with_a_dot_per_thousand(self):
        self.assertEqual(util.euro(1250), "€1.250")
        self.assertEqual(util.euro(89.6), "€90")
        self.assertEqual(util.euro(None), "—")


class ConnectReadonlyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = str(Path(tmp.name) / "koopjes.db")
        db.connect(self.path).close()

    def test_reads_but_refuses_to_write(self):
        conn = db.connect_readonly(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM listing").fetchone()[0], 0)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM listing")

    def test_rows_by_name_only_when_asked(self):
        plain, named = db.connect_readonly(self.path), db.connect_readonly(self.path, rows=True)
        self.addCleanup(plain.close)
        self.addCleanup(named.close)
        self.assertIsInstance(plain.execute("SELECT 1 AS n").fetchone(), tuple)
        self.assertEqual(named.execute("SELECT 1 AS n").fetchone()["n"], 1)

    def test_does_not_create_a_missing_database(self):
        missing = str(Path(self.path).with_name("bestaat_niet.db"))
        with self.assertRaises(sqlite3.OperationalError):
            db.connect_readonly(missing)
        self.assertFalse(Path(missing).exists())


if __name__ == "__main__":
    unittest.main()
