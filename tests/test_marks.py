"""marks.py en db.py (migratie 12): eigen markeringen op advertenties."""
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from helpers import make_listing

import db
import marks as mr


class MarkStorageTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")
        conn = db.connect(self.db)
        try:
            db.sync_listings(conn, "garmin edge", [make_listing(item_id="a", title="Garmin Edge 530", price_eur=120.0)],
                             datetime.now(timezone.utc).isoformat())
        finally:
            conn.close()

    def test_one_mark_per_listing_and_marking_again_replaces_it(self):
        conn = db.connect(self.db)
        try:
            db.set_mark(conn, "a", mr.FAVORITE, price_eur=120.0)
            db.set_mark(conn, "a", mr.DISMISSED, reason="niet waard", price_eur=110.0)
        finally:
            conn.close()
        (mark,) = mr.load_marks(self.db).values()
        self.assertEqual((mark.mark, mark.reason, mark.price_eur), (mr.DISMISSED, "niet waard", 110.0))
        self.assertEqual(mark.label, "weggezet (niet waard)")
        # Wat `listing` ervan weet komt mee, voor een favoriet die offline ging.
        self.assertEqual((mark.title, mark.current_price_eur), ("Garmin Edge 530", 120.0))

    def test_a_note_is_independent_of_the_mark(self):
        conn = db.connect(self.db)
        try:
            db.set_note(conn, "a", "zonder markering")
            db.set_mark(conn, "a", mr.FAVORITE, price_eur=120.0)
            db.set_note(conn, "a", "gereserveerd tot zaterdag")  # vervangt
            db.clear_mark(conn, "a")
        finally:
            conn.close()
        self.assertEqual(mr.load_notes(self.db), {"a": "gereserveerd tot zaterdag"})
        conn = db.connect(self.db)
        try:
            db.set_note(conn, "a", "")
        finally:
            conn.close()
        self.assertEqual(mr.load_notes(self.db), {})

    def test_migration_15_moves_the_notes_from_13_over(self):
        # Een database zoals migratie 13 hem achterliet: de notitie bij de markering.
        conn = db.connect(self.db)
        try:
            db.set_mark(conn, "a", mr.FAVORITE, price_eur=120.0)
            conn.execute("DROP TABLE listing_note")
            # En wat de migraties daarna aanmaakten: die draaien opnieuw.
            conn.execute("DROP TABLE comp_choice")
            conn.execute("DELETE FROM schema_version WHERE version >= 15")
            conn.execute("UPDATE listing_mark SET note = 'gevraagd of 100 kan' WHERE item_id = 'a'")
            conn.commit()
        finally:
            conn.close()
        conn = db.connect(self.db)  # migreert naar 15
        try:
            self.assertEqual(db.list_notes(conn), {"a": "gevraagd of 100 kan"})
            self.assertIsNone(conn.execute("SELECT note FROM listing_mark WHERE item_id = 'a'").fetchone()[0])
            (noted_at,) = conn.execute("SELECT noted_at FROM listing_note").fetchone()
            (marked_at,) = conn.execute("SELECT marked_at FROM listing_mark").fetchone()
        finally:
            conn.close()
        self.assertEqual(noted_at, marked_at)

    def test_clearing(self):
        conn = db.connect(self.db)
        try:
            db.set_mark(conn, "a", mr.FAVORITE)
            self.assertTrue(db.clear_mark(conn, "a"))
            self.assertFalse(db.clear_mark(conn, "a"))
        finally:
            conn.close()
        self.assertEqual(mr.load_marks(self.db), {})

    def test_a_database_from_before_migration_12_has_no_marks(self):
        conn = db.connect(self.db)
        try:
            conn.execute("DROP TABLE listing_mark")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(mr.load_marks(self.db), {})
        self.assertEqual(mr.load_marks(str(self.dir / "bestaat-niet.db")), {})

    def test_marks_stay_out_of_the_listing_table(self):
        conn = db.connect(self.db)
        try:
            db.set_mark(conn, "a", mr.DISMISSED, reason="gereserveerd", price_eur=120.0)
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(listing)")}
        finally:
            conn.close()
        self.assertFalse({"mark", "reason", "marked_at"} & columns)
        with sqlite3.connect(self.db) as raw:
            self.assertEqual(raw.execute("SELECT price_eur FROM listing WHERE item_id = 'a'").fetchone()[0], 120.0)


class DismissedTest(unittest.TestCase):
    def mark(self, price):
        return mr.Mark(item_id="a", mark=mr.DISMISSED, reason="niet waard", price_eur=price, marked_at="2026-09-29")

    def test_a_dismissed_listing_stays_away_until_its_price_drops(self):
        listing = make_listing(item_id="a", price_eur=150.0)
        self.assertTrue(mr.is_dismissed(self.mark(150.0), listing))
        listing.price_eur = 160.0
        self.assertTrue(mr.is_dismissed(self.mark(150.0), listing))
        listing.price_eur = 120.0
        self.assertFalse(mr.is_dismissed(self.mark(150.0), listing))
        self.assertTrue(mr.price_dropped(self.mark(150.0), listing))

    def test_without_a_price_there_is_nothing_to_compare(self):
        self.assertTrue(mr.is_dismissed(self.mark(None), make_listing(item_id="a", price_eur=50.0)))
        self.assertTrue(mr.is_dismissed(self.mark(150.0), make_listing(item_id="a", price_eur=None)))

    def test_a_favorite_or_no_mark_is_not_dismissed(self):
        listing = make_listing(item_id="a", price_eur=150.0)
        self.assertFalse(mr.is_dismissed(None, listing))
        favorite = mr.Mark(item_id="a", mark=mr.FAVORITE, marked_at="2026-09-29", price_eur=150.0)
        self.assertFalse(mr.is_dismissed(favorite, listing))


if __name__ == "__main__":
    unittest.main()
