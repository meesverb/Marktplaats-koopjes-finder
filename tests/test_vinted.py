"""vinted.py: Vinted-exports inlezen en naast Marktplaats zetten."""
import csv
import io
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from helpers import make_listing

import computers as pc
import dashboard
import db
import vinted as vn

HEADER = [
    "Item Title", "Item Price", "Item Total Price", "Item Service Fee", "Item Currency", "Item Brand",
    "Item Size", "Item Status", "Item URL", "All Photos", "Item Favorites", "Seller ID", "Seller Username",
    "Seller URL", "Seller Photo", "Is Business Seller", "Is Promoted", "Created Date", "Timestamp",
]
CATEGORY_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsaccessoires-fietscomputers/{}-x"


def vinted_row(item_id, title, price, **kw):
    """Een rij zoals de export van 28-09-2026 hem heeft: kopersbescherming
    €0,70 + 5%, "Not Available" voor wat ontbreekt."""
    fee = round(0.70 + 0.05 * price, 2)
    row = {
        "Item Title": title, "Item Price": f"{price:.2f}", "Item Total Price": f"{price + fee:.2f}",
        "Item Service Fee": f"{fee:.2f}", "Item Currency": "EUR", "Item Brand": "Garmin",
        "Item Size": "Not Available", "Item Status": "Heel goed",
        "Item URL": f"https://www.vinted.nl/items/{item_id}-x",
        "All Photos": f"https://images1.vinted.net/t/{item_id}/f800/a.webp?s=1",
        "Item Favorites": "5", "Seller ID": "42", "Seller Username": "Not Available",
        "Seller URL": "https://www.vinted.com/member/42", "Seller Photo": "Not Available",
        "Is Business Seller": "No", "Is Promoted": "No", "Created Date": "Not Available",
        "Timestamp": "Not Available",
    }
    row.update(kw)
    return row


class VintedTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = str(self.dir / "koopjes.db")

    def export(self, rows, name="productsList_2026-09-28T14-57-35-028Z.csv", header=HEADER):
        path = self.dir / name
        # utf-8-sig: de echte exports beginnen met een BOM.
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return path

    def load(self, *paths, at=None):
        conn = db.connect(self.db)
        try:
            return [vn.import_export(conn, p, at) for p in paths]
        finally:
            conn.close()

    def marktplaats(self, title, prices, when=None):
        when = when or datetime.now(timezone.utc).replace(microsecond=0)
        listings = [make_listing(item_id=f"mp{title[-4:]}{i}", title=title, price_eur=p,
                                 url=CATEGORY_URL.format(f"mp{i}")) for i, p in enumerate(prices)]
        conn = db.connect(self.db)
        try:
            db.sync_listings(conn, "fietscomputer", listings, when.isoformat())
        finally:
            conn.close()

    def rows(self, table):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
        finally:
            conn.close()


class ReadExportTest(VintedTestCase):
    def test_reads_a_row_as_the_export_has_it(self):
        path = self.export([vinted_row("10169550300", "Garmin edge 1040", 310.0, **{"Item Favorites": "0"})])
        rows, skipped = vn.read_export(path)
        self.assertEqual(skipped, {})
        r = rows[0]
        self.assertEqual((r.item_id, r.title, r.price_eur, r.fee_eur, r.total_eur),
                         ("10169550300", "Garmin edge 1040", 310.0, 16.2, 326.2))
        self.assertEqual(r.size, "")  # "Not Available"
        self.assertEqual(r.favorites, 0)
        self.assertTrue(r.image_url.startswith("https://images1.vinted.net/"))

    def test_time_comes_from_the_file_name(self):
        path = self.export([])
        self.assertEqual(vn.export_time(path), "2026-09-28T14:57:35+00:00")
        self.assertEqual(vn.export_time(path, "2026-09-28T16:00:00+02:00"), "2026-09-28T14:00:00+00:00")

    def test_another_file_stops_with_the_missing_column(self):
        path = self.export([], header=["Item Title", "Item Price"])
        with self.assertRaisesRegex(vn.ExportError, "'Item Service Fee'"):
            vn.read_export(path)

    def test_a_price_that_is_not_a_number_stops_with_the_line(self):
        path = self.export([vinted_row("1", "Garmin Edge 530", 100.0, **{"Item Price": "honderd"})])
        with self.assertRaisesRegex(vn.ExportError, "regel 2"):
            vn.read_export(path)

    def test_rows_without_id_or_in_another_currency_are_skipped_and_counted(self):
        path = self.export([
            vinted_row("1", "Garmin Edge 530", 100.0, **{"Item URL": "https://www.vinted.nl/catalog"}),
            vinted_row("2", "Garmin Edge 530", 100.0, **{"Item Currency": "PLN"}),
            vinted_row("4", "Garmin Edge 530", 100.0, **{"Item URL": "javascript:alert(1)//items/4"}),
            vinted_row("3", "Garmin Edge 530", 100.0),
        ])
        rows, skipped = vn.read_export(path)
        self.assertEqual([r.item_id for r in rows], ["3"])
        self.assertEqual(sum(skipped.values()), 3)


class ImportTest(VintedTestCase):
    def test_the_same_export_twice_changes_nothing(self):
        path = self.export([vinted_row("1", "Garmin Edge 530", 120.0)])
        first, again = self.load(path, path)
        self.assertEqual((first.new, again.new, again.updated, again.repriced), (1, 0, 1, 0))
        self.assertEqual(len(self.rows("vinted_listing")), 1)
        self.assertEqual(len(self.rows("vinted_price")), 1)

    def test_a_later_export_updates_the_price_and_keeps_the_history(self):
        old = self.export([vinted_row("1", "Garmin Edge 530", 150.0)], "productsList_2026-09-20T10-00-00-000Z.csv")
        new = self.export([vinted_row("1", "Garmin Edge 530", 120.0)], "productsList_2026-09-28T10-00-00-000Z.csv")
        self.load(old)
        result = self.load(new)[0]
        self.assertEqual(result.repriced, 1)
        row = self.rows("vinted_listing")[0]
        self.assertEqual(row["price_eur"], 120.0)
        self.assertEqual(row["first_exported_at"], "2026-09-20T10:00:00+00:00")
        self.assertEqual([r["price_eur"] for r in self.rows("vinted_price")], [150.0, 120.0])

    def test_an_older_export_read_later_does_not_overwrite_the_newer_one(self):
        old = self.export([vinted_row("1", "Garmin Edge 530", 150.0)], "productsList_2026-09-20T10-00-00-000Z.csv")
        new = self.export([vinted_row("1", "Garmin Edge 530", 120.0)], "productsList_2026-09-28T10-00-00-000Z.csv")
        self.load(new, old)
        row = self.rows("vinted_listing")[0]
        self.assertEqual(row["price_eur"], 120.0)
        self.assertEqual(row["first_exported_at"], "2026-09-20T10:00:00+00:00")
        self.assertEqual(row["last_exported_at"], "2026-09-28T10:00:00+00:00")

    def test_vinted_is_never_a_marktplaats_comparable(self):
        self.marktplaats("Garmin Edge 530", [160.0, 180.0, 200.0])
        self.load(self.export([vinted_row(str(i), "Garmin Edge 530", 20.0) for i in range(5)]))
        comps = pc.db_comparables(self.db, pc._default_catalog(), 180)
        self.assertEqual(sorted(comps["Garmin Edge 530"].values()), [160.0, 180.0, 200.0])


class ClassifyTest(unittest.TestCase):
    """Echte titels uit de exports van 28-09-2026."""

    KINDS = {
        "Garmin Edge 530": "computer",
        "Compteur GPS Garmin Edge 1040 - Comme neuf": "computer",
        "Wahoo Elemnt Rival": "overig",
        "Wahoo élément rival – État impeccable": "overig",
        "Orologio Wahoo": "overig",
        "Garmin Forerunner 935": "overig",
        "Rodillo Wahoo KICKR core": "overig",
        "Wahoo speelplay comp pedalen met 2 paar plaatjes": "overig",
        "Garmin Drivesmart 61 Europe LMT-D": "overig",
        "Maglia Alè Donna lilla taglia M ciclismo bici da corsa mtb gravel road": "overig",
        "Wahoo Kickr V5": "accessoire",
        "Support compteur wahoo élément ace": "accessoire",
        "Garmin Edge Out-Front": "accessoire",
        "Garmin Edge Battery Pack": "accessoire",
        "Sensore cadenza cadence Wahoo": "accessoire",
        "Garmin Edge 1030 (senza GPS)": "accessoire",
        "Wahoo element bolt bloccato": "defect",
        "Garmin": "computer",  # model onbekend: kijk op de foto
    }

    def test_real_titles(self):
        config = pc.default_config()
        catalog = pc._default_catalog()
        for title, kind in self.KINDS.items():
            with self.subTest(title=title):
                row = vn.VintedRow("1", title, 100.0, 5.7, 105.7)
                self.assertEqual(vn.classify(row, catalog, {}, config)[1], kind)

    def test_a_bike_with_a_computer_is_not_a_computer(self):
        row = vn.VintedRow("1", "Pack vélo route Van Rysel NCR CF Carbone Tiagra + Garmin 1040 + D900",
                           2500.0, 125.7, 2625.7)
        model, kind, reason = vn.classify(row, pc._default_catalog(), {}, pc.default_config())
        self.assertEqual(kind, "overig")
        self.assertIn("€1000", reason)

    def test_a_cheap_holder_after_the_model_is_judged_on_the_marktplaats_median(self):
        catalog = pc._default_catalog()
        row = vn.VintedRow("1", "Wahoo Elemnt Roam V3 Halterung original", 19.0, 1.65, 20.65)
        mp_prices = {"Wahoo ELEMNT ROAM 3": {"a": 180.0, "b": 200.0, "c": 220.0}}
        self.assertEqual(vn.classify(row, catalog, mp_prices, pc.default_config())[1], "accessoire")


class ViewTest(VintedTestCase):
    def test_flip_is_marktplaats_resale_minus_what_you_pay_on_vinted(self):
        config = pc.default_config()
        self.marktplaats("Garmin Edge 530", [160.0, 180.0, 200.0])
        self.load(self.export([vinted_row("1", "Garmin Edge 530", 120.0),
                               vinted_row("2", "Garmin Edge 530", 200.0)]))
        view = vn.load_view(self.db, config)
        resale = 180.0 * config["flip"]["negotiation_factor"]
        cost = 120.0 + 6.70 + config["vinted"]["shipping_eur"]
        self.assertEqual([i.row.item_id for i in view.flips], ["1"])
        flip = view.flips[0]
        self.assertAlmostEqual(flip.cost_eur, cost)
        self.assertAlmostEqual(flip.profit_eur, resale - config["flip"]["costs_eur"] - cost)
        self.assertEqual(flip.mp_count, 3)
        model = view.models[0]
        self.assertEqual((len(model.vinted), model.vinted_median, model.mp_median), (2, 160.0, 180.0))
        self.assertAlmostEqual(model.ratio, 160.0 / 180.0)

    def test_too_few_marktplaats_listings_gives_no_flip_and_no_ratio(self):
        self.marktplaats("Garmin Edge 530", [160.0, 180.0])
        self.load(self.export([vinted_row("1", "Garmin Edge 530", 20.0)]))
        view = vn.load_view(self.db)
        self.assertEqual(view.flips, [])
        self.assertIsNone(view.models[0].ratio)

    def test_only_recent_exports_are_active(self):
        old = self.export([vinted_row("1", "Garmin Edge 530", 150.0)], "productsList_2026-09-01T10-00-00-000Z.csv")
        new = self.export([vinted_row("2", "Garmin Edge 830", 200.0)], "productsList_2026-09-28T10-00-00-000Z.csv")
        self.load(old, new)
        self.assertEqual([i.row.item_id for i in vn.load_view(self.db).items], ["2"])

    def test_no_export_no_view(self):
        self.marktplaats("Garmin Edge 530", [160.0, 180.0, 200.0])
        self.assertIsNone(vn.load_view(self.db))
        self.assertIsNone(vn.load_view(str(self.dir / "bestaat_niet.db")))

    def test_dashboard_tab_says_how_to_import_until_there_is_an_export(self):
        self.marktplaats("Garmin Edge 530", [160.0, 180.0, 200.0])
        html = dashboard.render(dashboard.load_dashboard(self.db))
        self.assertIn("panel-vinted", html)
        self.assertIn("python vinted.py import", html)
        self.assertIn(str(Path(self.db).resolve()), html)  # welke database het dashboard leest
        self.load(self.export([vinted_row("1", "Garmin Edge 530", 120.0)]))
        html = dashboard.render(dashboard.load_dashboard(self.db))
        self.assertIn("panel-vinted", html)
        self.assertIn("Vinted (1)", html)
        self.assertIn("https://www.vinted.nl/items/1-x", html)


class CliTest(VintedTestCase):
    def test_import_then_overview(self):
        path = self.export([vinted_row("1", "Garmin Edge 530", 120.0)])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(vn.main(["import", str(path), "--db", self.db]), 0)
            self.assertEqual(vn.main(["--db", self.db]), 0)
        text = out.getvalue()
        self.assertIn("1 advertenties, 1 nieuw", text)
        self.assertIn("Garmin Edge 530", text)

    def test_default_database_is_the_one_koopjes_py_uses(self):
        # Niet "koopjes.db" in de map waar je staat: vanuit Downloads gaf dat
        # een tweede, lege database die het dashboard nooit las.
        self.assertEqual(Path(vn.DEFAULT_DB), Path(vn.__file__).resolve().parent / "koopjes.db")

    def test_import_into_a_new_database_says_so(self):
        path = self.export([vinted_row("1", "Garmin Edge 530", 120.0)])
        fresh = str(self.dir / "ergens" / "anders.db")
        Path(fresh).parent.mkdir()
        out = io.StringIO()
        with redirect_stdout(out):
            vn.main(["import", str(path), "--db", fresh])
        self.assertIn(str(Path(fresh).resolve()), out.getvalue())
        self.assertIn("bestond nog niet", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            vn.main(["import", str(path), "--db", fresh])
        self.assertNotIn("bestond nog niet", out.getvalue())

    def test_a_wrong_file_fails_clearly(self):
        path = self.export([], header=["Title", "Price"])
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(vn.main(["import", str(path), "--db", self.db]), 1)
        self.assertIn("geen Vinted-export", err.getvalue())

    def test_overview_without_export_says_what_to_do(self):
        out = io.StringIO()
        with redirect_stdout(out):
            vn.main(["--db", self.db])
        self.assertIn("python vinted.py import", out.getvalue())


if __name__ == "__main__":
    unittest.main()
