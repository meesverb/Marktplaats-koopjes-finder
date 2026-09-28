"""watches.py: de flipberekening van de fietscomputers op sporthorloges,
alleen uit de categorieën sporthorloges en smartwatches."""
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from helpers import make_listing

import computers as pc
import db
import watches

WATCH_URL = "https://www.marktplaats.nl/v/sieraden-tassen-en-uiterlijk/{}/{}-x"
PHONE_URL = "https://www.marktplaats.nl/v/telecommunicatie/mobiele-telefoons-toebehoren-en-onderdelen/{}-x"
CONFIG = pc.load_config()
FACTOR = CONFIG["flip"]["negotiation_factor"]
COSTS = CONFIG["flip"]["costs_eur"]


def watch(item_id, title, price, category="sporthorloges", **kw):
    kw.setdefault("url", WATCH_URL.format(category, item_id))
    return make_listing(item_id=item_id, title=title, price_eur=price, **kw)


class WatchesTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")

    def sync(self, listings):
        conn = db.connect(self.db)
        try:
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            db.sync_listings(conn, "fenix", listings, now)
        finally:
            conn.close()

    def market(self):
        # Vier Fenix 6 Pro's, één in smartwatches: die categorie telt ook.
        return [watch(f"a{i}", "Garmin Fenix 6 Pro 47 mm", p, category=c)
                for i, (p, c) in enumerate(((200.0, "sporthorloges"), (200.0, "sporthorloges"),
                                            (210.0, "smartwatches"), (220.0, "sporthorloges")))]

    def test_cheap_watch_is_a_flip(self):
        cheap = watch("c", "Garmin fēnix 6X Pro Sapphire 51mm", 100.0)
        self.sync(self.market() + [cheap])
        listings, newest = watches.load_watches(self.db)
        self.assertIsNotNone(newest)
        found = {l.item_id: l for l in watches.flips(listings)}
        self.assertIn("c", found)
        self.assertEqual(set(found), {"c"})
        self.assertAlmostEqual(found["c"].computer.profit_eur, 205.0 * FACTOR - 100.0 - COSTS, places=2)
        self.assertEqual(found["c"].computer.model.label, "Garmin Fenix 6 Pro")

    def test_other_categories_are_neither_loaded_nor_comparables(self):
        # Een bandje of kabel met "Fenix 6 Pro" in de titel staat in een
        # telefooncategorie; als vergelijkingsprijs zou het de mediaan omlaag
        # trekken en de flips verbergen.
        straps = [make_listing(item_id=f"s{i}", title="Garmin Fenix 6 Pro", price_eur=15.0,
                               url=PHONE_URL.format(f"s{i}")) for i in range(5)]
        cheap = watch("c", "Garmin Fenix 6 Pro", 100.0)
        self.sync(self.market() + straps + [cheap])
        listings, _ = watches.load_watches(self.db)
        self.assertFalse(any(l.item_id.startswith("s") for l in listings))
        self.assertIn("c", {l.item_id for l in watches.flips(listings)})
        self.assertAlmostEqual(watches.model_resale(self.db)["Garmin Fenix 6 Pro"], 200.0 * FACTOR)

    def test_accessories_from_the_real_crawl_are_filtered_out(self):
        # Alle drie uit de crawl van 28-09-2026, in de categorie sporthorloges.
        accessory_set = watch("t", "Forerunner 945 Tri accessoires: HRM-Swim + Quick Release kit", 65.0)
        dock = watch("d", "25009 Docking Station Garmin Fenix 5/6/7/8", 10.0)
        strap = watch("b", "Garmin Fenix 6 Pro bandje", 12.0)
        market945 = [watch(f"f{i}", "Garmin Forerunner 945", p) for i, p in enumerate((200.0, 215.0, 230.0))]
        self.sync(self.market() + market945 + [accessory_set, dock, strap])
        listings, _ = watches.load_watches(self.db)
        by_id = {l.item_id: l for l in listings}
        for item_id in ("t", "d", "b"):
            with self.subTest(item_id=item_id):
                self.assertFalse(by_id[item_id].computer.is_computer, by_id[item_id].computer.reason)
        self.assertEqual(watches.flips(listings), [])

    def test_watch_with_strap_is_still_a_watch(self):
        with_strap = watch("w", "Garmin Fenix 6S 42 mm zwart met een zwarte siliconen polsband", 100.0)
        self.sync(self.market() + [with_strap])
        listings, _ = watches.load_watches(self.db)
        self.assertTrue({l.item_id: l for l in listings}["w"].computer.is_computer)

    def test_free_swap_offer_is_not_a_flip(self):
        swap = watch("r", "Garmin Fenix 6 Pro - Topconditie graag ruilen", 0.0, price_type="FREE")
        self.sync(self.market() + [swap])
        listings, _ = watches.load_watches(self.db)
        self.assertNotIn("r", {l.item_id for l in watches.flips(listings)})

    def test_main_prints_market_and_flips(self):
        self.sync(self.market() + [watch("c", "Garmin Fenix 6 Pro", 100.0)])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(watches.main(["--db", self.db]), 0)
        text = out.getvalue()
        self.assertIn("Garmin Fenix 6 Pro", text)
        self.assertIn("1 boven €0", text)

    def test_empty_database_says_what_to_do(self):
        self.sync([make_listing(item_id="x", title="Racefiets", url="https://www.marktplaats.nl/v/fietsen/fietsen-racefietsen/x-x")])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(watches.main(["--db", self.db]), 0)
        self.assertIn("sporthorloges", out.getvalue())


if __name__ == "__main__":
    unittest.main()
