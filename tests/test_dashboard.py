"""dashboard.py: één pagina met alle fietscomputers, gebouwd uit koopjes.db."""
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import make_listing

import dashboard
import db

CATEGORY_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/{}-x"
BIKE_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/{}-x"


def computer(item_id, title, price, **kw):
    kw.setdefault("url", CATEGORY_URL.format(item_id))
    kw.setdefault("image_urls", f"https://images.example/{item_id}.jpg")
    return make_listing(item_id=item_id, title=title, price_eur=price, **kw)


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def sync(self, listings, when=None):
        conn = db.connect(self.db)
        try:
            db.sync_listings(conn, "garmin edge", listings, (when or self.now).isoformat())
        finally:
            conn.close()

    def market(self):
        return [computer(f"a{i}", "Garmin Edge 530", p) for i, p in enumerate((160.0, 180.0, 200.0, 220.0))]

    def test_flips_upgrades_and_filtered_out_from_the_database(self):
        cheap = computer("c", "Garmin Edge 530 fietscomputer met houder", 90.0)
        holder = computer("h", "Houder voor Garmin Edge 530", 12.0)
        unknown = computer("u", "Van Rysel GPS 500 Fietscomputer - Nieuw in doos", 50.0)
        mount = computer("m", "Garmin Edge Aero Mount - Zo goed als nieuw", 12.5)
        bike = make_listing(item_id="b", title="Giant Defy met Garmin Edge 530", price_eur=900.0,
                            url=BIKE_URL.format("b"))
        self.sync(self.market() + [cheap, holder, unknown, mount, bike])

        d = dashboard.load_dashboard(self.db)
        ids = lambda items: {l.item_id for l in items}
        self.assertNotIn("b", ids(d.listings))  # another category: not on the dashboard
        self.assertEqual(ids(d.flips) & {"c"}, {"c"})
        self.assertIn("c", ids(d.upgrades))
        self.assertEqual({u.listing.item_id for u in d.unknown_computers}, {"u"})
        self.assertEqual({l.item_id for l, _, _ in d.excluded}, {"h", "m"})

        html = dashboard.render(d)
        for label in ("Flips (", "Upgrades (", "Alle computers (", "Marktprijzen", "Uitgefilterd (2)"):
            self.assertIn(label, html)
        self.assertIn("https://images.example/c.jpg", html)  # migration 6 kept the photo
        self.assertIn("model onbekend", html)

    def test_only_listings_from_the_latest_round_are_active(self):
        old = computer("old", "Garmin Edge 830", 150.0)
        self.sync([old], when=self.now - timedelta(days=10))
        self.sync(self.market())
        d = dashboard.load_dashboard(self.db)
        self.assertNotIn("old", {l.item_id for l in d.listings})

    def test_disappeared_listings_are_gone(self):
        self.sync(self.market())
        conn = db.connect(self.db)
        try:
            conn.execute("UPDATE listing SET disappeared_at = ? WHERE item_id = 'a0'", (self.now.isoformat(),))
            conn.commit()
        finally:
            conn.close()
        self.assertNotIn("a0", {l.item_id for l in dashboard.load_dashboard(self.db).listings})

    def test_new_means_first_seen_in_the_last_day_but_not_on_the_first_round(self):
        self.sync(self.market(), when=self.now - timedelta(days=2))
        self.assertEqual(dashboard.load_dashboard(self.db).new_ids, set())  # first round: nothing is "new"
        fresh = computer("f", "Garmin Edge 830", 150.0)
        self.sync(self.market() + [fresh])
        self.assertEqual(dashboard.load_dashboard(self.db).new_ids, {"f"})

    def test_a_running_bid_is_labelled_as_one(self):
        bid = computer("x", "Garmin Edge 530", 60.0, price_type="FAST_BID", price_is_bid=True, bid_count=3)
        self.sync(self.market() + [bid])
        listing = next(l for l in dashboard.load_dashboard(self.db).listings if l.item_id == "x")
        self.assertIn("huidig bod", dashboard.price_cell(listing))

    def test_empty_database_says_what_to_do(self):
        conn = db.connect(self.db)
        conn.close()
        html = dashboard.render(dashboard.load_dashboard(self.db))
        self.assertIn("python koopjes.py run nacht", html)

    def test_cli_writes_the_page(self):
        self.sync(self.market())
        out = self.dir / "dashboard.html"
        with redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(dashboard.main(["--db", self.db, "--out", str(out)]), 0)
        self.assertTrue(out.exists())
        self.assertIn("4 computers", printed.getvalue())

    def test_cli_without_database_fails_clearly(self):
        from contextlib import redirect_stderr

        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(dashboard.main(["--db", str(self.dir / "nee.db"), "--out", str(self.dir / "d.html")]), 1)
        self.assertIn("bestaat niet", err.getvalue())


if __name__ == "__main__":
    unittest.main()
