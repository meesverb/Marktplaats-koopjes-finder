"""patterns.py: lange-termijnpatronen uit koopjes.db."""
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import make_listing

import dashboard
import db
import patterns as pt

URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/{}-x"


class PatternsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")
        self.start = datetime(2026, 8, 3, 3, 0, tzinfo=timezone.utc)  # a Monday

    def history(self):
        """30 Edge 530s over four weeks: the cheap ones disappear in 3 days,
        the dear ones stay. Plus a holder, which must not count."""
        conn = db.connect(self.db)
        try:
            for i in range(30):
                first = self.start + timedelta(days=i % 28)
                price = 120.0 if i % 2 == 0 else 200.0
                listing = make_listing(item_id=f"e{i}", title="Garmin Edge 530", price_eur=price, url=URL.format(f"e{i}"))
                db.sync_listings(conn, "garmin edge", [listing], first.isoformat())
                if i % 2 == 0:
                    gone = first + timedelta(days=3)
                    conn.execute("UPDATE listing SET disappeared_at = ?, days_online = 3, last_seen = ? "
                                 "WHERE item_id = ?", (gone.isoformat(), gone.isoformat(), f"e{i}"))
            holder = make_listing(item_id="h", title="Houder voor Garmin Edge 530", price_eur=10.0, url=URL.format("h"))
            db.sync_listings(conn, "garmin edge", [holder], self.start.isoformat())
            conn.commit()
        finally:
            conn.close()

    def test_speed_price_and_factor(self):
        self.history()
        p = pt.load_patterns(self.db)
        self.assertEqual(p.total, 30)  # the holder isn't a computer
        self.assertEqual(p.gone, 15)
        (m,) = p.models
        self.assertEqual((m.model, m.median_days_gone, m.quick_share), ("Garmin Edge 530", 3, 1.0))
        self.assertEqual(m.median_ask, 160.0)
        self.assertEqual(m.quick_price, 120.0)
        self.assertAlmostEqual(m.factor, 0.75)
        # 15 quick ones is below the 20 needed for a global factor.
        self.assertIsNone(p.measured_factor)
        self.assertEqual(p.measured_n, 15)

    def test_gone_while_reserved_is_counted_apart(self):
        self.history()
        conn = db.connect(self.db)
        try:
            conn.execute("UPDATE listing SET reserved_at = first_seen WHERE item_id IN ('e0', 'e2', 'e1')")
            conn.commit()
        finally:
            conn.close()
        p = pt.load_patterns(self.db)
        # e0 en e2 zijn verdwenen; e1 staat gereserveerd nog online en telt niet.
        self.assertEqual(p.gone_reserved, 2)
        self.assertEqual(p.models[0].gone_reserved, 2)
        html = dashboard.patterns_panel(dashboard.load_dashboard(self.db))
        self.assertIn("2 eerst gereserveerd", html)
        self.assertIn("2 gereserveerd", html)

    def test_flips_in_hindsight(self):
        self.history()
        p = pt.load_patterns(self.db)
        # 120 < 160 × 0,875 − 3: every cheap one was a flip, and was gone in 3 days.
        self.assertEqual((p.flip_days, p.flip_n), (3, 15))
        self.assertIsNone(p.other_days)  # the dear ones never went

    def test_weekday_new_skips_the_first_crawl(self):
        self.history()
        p = pt.load_patterns(self.db)
        days = dict((day, n) for day, _, n in p.weekday_new)
        # Last sighting 1 Sep (a gone one, day 29): Mondays 10, 17, 24 and 31 Aug.
        self.assertEqual(days["maandag"], 4)

    def test_empty(self):
        p = pt.load_patterns(str(self.dir / "nee.db"))
        self.assertEqual((p.total, p.days_of_data), (0, 0))
        html = dashboard.patterns_panel(dashboard.Dashboard([], config=__import__("computers").default_config()))
        self.assertIn("Nog weinig gegevens", html)

    def test_dashboard_has_the_tab(self):
        self.history()
        html = dashboard.render(dashboard.load_dashboard(self.db))
        self.assertIn("data-panel='patronen'", html)
        self.assertIn("Gemeten afdingfactor", html)


if __name__ == "__main__":
    unittest.main()
