"""db.py — the SQLite schema and the legacy-file import (fase 1a).

racefiets_jev.py doesn't call any of this yet (fase 1b wires it in); these
tests work directly against db.py with throwaway files, per
PLAN_FIETSWAARDE.md fase 1a's acceptance criteria.
"""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from helpers import mp, repo_file  # noqa: F401  (adds the repo root to sys.path)

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

    def test_a_database_from_a_newer_version_is_refused(self):
        # The migration slice is empty in that case, so the old code would
        # otherwise carry on writing into a schema it does not know.
        path = self.path("koopjes.db")
        conn = db.connect(path)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (len(db.MIGRATIONS) + 1, "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()

        with self.assertRaises(RuntimeError) as caught:
            db.connect(path)
        self.assertIn("schemaversie", str(caught.exception))

    def test_a_failed_migration_leaves_nothing_behind(self):
        # A migration that dies partway used to leave its tables committed
        # while the version row was still pending, and the next start then ran
        # the same CREATE TABLEs against tables that already existed — an
        # error on every run from then on, with no way back but deleting the
        # database. Schema and version have to land together.
        path = self.path("koopjes.db")
        broken = db.MIGRATIONS[0] + "\nCREATE TABLE crawl_run (nope INTEGER);"
        with unittest.mock.patch.object(db, "MIGRATIONS", [broken]):
            with self.assertRaises(sqlite3.OperationalError):
                db.connect(path)

        conn = db.connect(path)
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertIn("crawl_run", tables)
        self.assertEqual(
            conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"],
            len(db.MIGRATIONS),
        )

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

    def test_json_that_is_not_a_history_is_skipped_with_a_warning(self):
        # Valid JSON, wrong shape: used to die on .items() and take the whole
        # migration down with it.
        path = self.path("seen_listings.json")
        Path(path).write_text('["m1", "m2"]', encoding="utf-8")
        conn = db.connect(self.path("koopjes.db"))

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            counts = self.import_legacy(conn, seen_listings_path=path)
        self.assertEqual(counts["listings_from_history"], 0)
        self.assertIn("geen advertentie-geschiedenis", stderr.getvalue())

    def test_an_entry_that_is_not_a_listing_is_skipped(self):
        path = self.path("seen_listings.json")
        Path(path).write_text(
            '{"m1": {"title": "Goed", "last_seen": "2026-01-01", "last_price": 50}, '
            '"m2": "kapot"}',
            encoding="utf-8",
        )
        conn = db.connect(self.path("koopjes.db"))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            counts = self.import_legacy(conn, seen_listings_path=path)

        self.assertEqual(counts["listings_from_history"], 1)
        self.assertIn("overgeslagen", stderr.getvalue())

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

    def test_a_file_saved_from_excel_still_imports(self):
        path = self.path("reference_prices.csv")
        Path(path).write_text(
            "\ufeffpattern,label,original_price_eur,specs,score,better_than_baseline\n"
            "Mission 731,Mission 731,300,,,\n",
            encoding="utf-8",
        )
        conn = db.connect(self.path("koopjes.db"))
        counts = self.import_legacy(conn, reference_prices_path=path)
        self.assertEqual(counts["models_from_reference"], 1)

    def test_a_duplicate_pattern_is_reported_and_counted_once(self):
        # The upsert is on (kind, pattern): two rows with the same pattern
        # leave one model behind, so reporting two would be a lie about what
        # is in the database.
        path = self.write_reference("Mission 731,Eerste,100,,,\n" "Mission 731,Tweede,200,,,\n")
        conn = db.connect(self.path("koopjes.db"))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            counts = self.import_legacy(conn, reference_prices_path=path)

        self.assertEqual(counts["models_from_reference"], 1)
        self.assertIn("meer dan één keer", stderr.getvalue())
        rows = conn.execute("SELECT model FROM model").fetchall()
        self.assertEqual([r["model"] for r in rows], ["Tweede"])

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


class ReferenceKindAndSourceTest(TempDirTest):
    """Fase 7: the bike reference files carry kind/brand/source_url columns
    that reference_prices.csv doesn't have."""

    def test_optional_columns_land_in_model(self):
        path = self.path("reference_bikes.csv")
        Path(path).write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline,kind,brand,source_url\n"
            '"Defy.{0,20}Composite",Giant Defy Composite,,carbon,,0,bike,Giant,https://example.org/defy\n',
            encoding="utf-8",
        )
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, reference_prices_path=path)
        row = conn.execute("SELECT kind, brand, source_url FROM model").fetchone()
        self.assertEqual(
            (row["kind"], row["brand"], row["source_url"]),
            ("bike", "Giant", "https://example.org/defy"),
        )

    def test_a_file_without_those_columns_imports_as_before(self):
        path = self.path("reference_prices.csv")
        Path(path).write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline\n"
            "Mission 731,Mission 731,300,,,1\n",
            encoding="utf-8",
        )
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, reference_prices_path=path)
        row = conn.execute("SELECT kind, brand, source_url FROM model").fetchone()
        self.assertEqual((row["kind"], row["brand"], row["source_url"]), ("other", None, None))

    def test_an_unknown_kind_warns_and_falls_back_to_other(self):
        # A typo'd kind would otherwise open its own UNIQUE(kind, pattern)
        # namespace and never be exported or matched with its siblings.
        path = self.path("ref.csv")
        Path(path).write_text(
            "pattern,label,kind\nEdge 530,Garmin Edge 530,compuetr\n", encoding="utf-8"
        )
        conn = db.connect(self.path("koopjes.db"))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.import_legacy(conn, reference_prices_path=path)
        self.assertIn("compuetr", stderr.getvalue())
        self.assertEqual(conn.execute("SELECT kind FROM model").fetchone()["kind"], "other")

    def test_the_checked_in_bike_files_import_with_a_source_on_every_row(self):
        conn = db.connect(self.path("koopjes.db"))
        for name in ("reference_bikes.csv", "reference_bike_accessories.csv"):
            self.import_legacy(conn, reference_prices_path=repo_file(name))
        rows = conn.execute("SELECT kind, model, source_url FROM model").fetchall()
        self.assertGreater(len(rows), 0)
        self.assertNotIn("other", {r["kind"] for r in rows})
        self.assertEqual([r["model"] for r in rows if not r["source_url"]], [])


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

    def test_a_whole_new_price_is_written_back_without_a_decimal(self):
        # SQLite hands REALs back as 110.0. Writing that into
        # reference_prices.csv turns every priced row into a diff the moment
        # the file is exported, in a file that is reviewed by hand.
        path = self.path("reference_prices.csv")
        Path(path).write_text(
            "pattern,label,original_price_eur,specs,score,better_than_baseline\n"
            "Heel,Heel getal,110,,,\n"
            "Half,Half getal,47.5,,,\n"
            "Leeg,Geen prijs,,,,\n",
            encoding="utf-8",
        )
        conn = db.connect(self.path("koopjes.db"))
        self.import_legacy(conn, reference_prices_path=path)

        out = self.path("export.csv")
        db.export_csv(conn, out)
        prices = [line.split(",")[2] for line in Path(out).read_text(encoding="utf-8").splitlines()[1:]]
        self.assertEqual(prices, ["110", "47.5", ""])

    def test_only_the_asked_for_kind_is_exported(self):
        # reference_prices.csv is read as one flat list of patterns matched
        # against whatever query runs, so a bike pattern in the speakers file
        # would start matching speaker titles. Fase 7 adds bike rows.
        conn = db.connect(self.path("koopjes.db"))
        for kind, model, pattern in (
            ("other", "Mission 731", "Mission 731"),
            ("bike", "Giant Defy", "Giant Defy"),
        ):
            conn.execute(
                "INSERT INTO model (kind, model, pattern, specs_json, score) "
                "VALUES (?, ?, ?, '{}', '')",
                (kind, model, pattern),
            )
        conn.commit()

        out = self.path("export.csv")
        self.assertEqual(db.export_csv(conn, out), 1)
        self.assertIn("Mission 731", Path(out).read_text(encoding="utf-8"))
        self.assertNotIn("Giant Defy", Path(out).read_text(encoding="utf-8"))
        self.assertEqual(db.export_csv(conn, out, kind="bike"), 1)
        self.assertIn("Giant Defy", Path(out).read_text(encoding="utf-8"))

    def test_an_unreadable_specs_json_does_not_stop_the_export(self):
        conn = db.connect(self.path("koopjes.db"))
        conn.execute(
            "INSERT INTO model (kind, model, pattern, specs_json, score) "
            "VALUES ('other', 'Stuk', 'stuk', '{kapot', '')"
        )
        conn.commit()

        out = self.path("export.csv")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(db.export_csv(conn, out), 1)
        self.assertIn("specs_json", stderr.getvalue())
        self.assertIn("Stuk", Path(out).read_text(encoding="utf-8"))

    def test_empty_model_table_still_writes_a_header(self):
        conn = db.connect(self.path("koopjes.db"))
        out_path = self.path("exported.csv")
        written = db.export_csv(conn, out_path)
        self.assertEqual(written, 0)
        self.assertEqual(mp.load_reference_data(out_path), [])


class SyncListingSpecsTest(TempDirTest):
    """spec — fase 2: racefiets_jev.extract_specs() written per listing."""

    def setUp(self):
        super().setUp()
        self.conn = db.connect(self.path("koopjes.db"))
        self.conn.execute(
            "INSERT INTO listing (item_id, title) VALUES ('a', 'Test')"
        )
        self.conn.commit()

    def test_specs_become_rows(self):
        db.sync_listing_specs(self.conn, {"a": {"frame_material": "carbon", "speeds": "11"}})
        rows = {
            r["key"]: r["value"]
            for r in self.conn.execute("SELECT key, value FROM spec WHERE listing_id='a'")
        }
        self.assertEqual(rows, {"frame_material": "carbon", "speeds": "11"})

    def test_a_listing_with_no_specs_writes_no_rows(self):
        db.sync_listing_specs(self.conn, {"a": {}})
        n = self.conn.execute("SELECT COUNT(*) AS n FROM spec").fetchone()["n"]
        self.assertEqual(n, 0)

    def test_resyncing_replaces_rather_than_duplicates(self):
        db.sync_listing_specs(self.conn, {"a": {"frame_material": "aluminium"}})
        db.sync_listing_specs(self.conn, {"a": {"frame_material": "carbon"}})
        rows = self.conn.execute("SELECT value FROM spec WHERE listing_id='a'").fetchall()
        self.assertEqual([r["value"] for r in rows], ["carbon"])

    def test_a_different_source_is_left_alone(self):
        self.conn.execute(
            "INSERT INTO spec (listing_id, key, value, source, confidence) "
            "VALUES ('a', 'weight_kg', '7.8', 'handmatig', 1.0)"
        )
        self.conn.commit()
        db.sync_listing_specs(self.conn, {"a": {"frame_material": "carbon"}})
        rows = {r["key"]: r["source"] for r in self.conn.execute("SELECT key, source FROM spec")}
        self.assertEqual(rows, {"weight_kg": "handmatig", "frame_material": "regex"})


class SyncListingModelsTest(TempDirTest):
    """listing_model — fase 2: every matching pattern, not just the winner."""

    def setUp(self):
        super().setUp()
        self.conn = db.connect(self.path("koopjes.db"))
        self.conn.execute(
            "INSERT INTO listing (item_id, title) VALUES ('a', 'Test')"
        )
        self.conn.execute(
            "INSERT INTO model (kind, model, pattern) VALUES ('other', 'Specifiek', 'Mission 731')"
        )
        self.conn.execute(
            "INSERT INTO model (kind, model, pattern) VALUES ('other', 'Algemeen', 'Mission')"
        )
        self.conn.commit()

    def test_every_matched_pattern_gets_its_own_row(self):
        written = db.sync_listing_models(self.conn, {"a": ["Mission 731", "Mission"]})
        self.assertEqual(written, 2)
        rows = self.conn.execute(
            "SELECT m.model FROM listing_model lm JOIN model m ON m.id = lm.model_id "
            "WHERE lm.listing_id = 'a' ORDER BY m.model"
        ).fetchall()
        self.assertEqual([r["model"] for r in rows], ["Algemeen", "Specifiek"])

    def test_a_pattern_without_a_matching_model_row_is_skipped(self):
        written = db.sync_listing_models(self.conn, {"a": ["Geen zo'n patroon"]})
        self.assertEqual(written, 0)

    def test_a_bike_model_is_linked_without_naming_its_kind(self):
        # racefiets_jev.sync_database() calls this without a kind. Before
        # fase 7 that meant 'other' only, which would drop every bike match.
        self.conn.execute(
            "INSERT INTO model (kind, model, pattern) VALUES ('bike', 'Defy', 'Giant Defy')"
        )
        self.assertEqual(db.sync_listing_models(self.conn, {"a": ["Giant Defy"]}), 1)
        self.assertEqual(
            db.sync_listing_models(self.conn, {"a": ["Giant Defy"]}, kind="other"), 0
        )

    def test_resyncing_does_not_duplicate_rows(self):
        db.sync_listing_models(self.conn, {"a": ["Mission 731"]})
        db.sync_listing_models(self.conn, {"a": ["Mission 731"]})
        n = self.conn.execute("SELECT COUNT(*) AS n FROM listing_model").fetchone()["n"]
        self.assertEqual(n, 1)



class FrameMaterialImportTest(unittest.TestCase):
    def test_frame_material_goes_into_specs_json_and_bad_values_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "ref.csv"
            ref.write_text(
                "pattern,label,original_price_eur,specs,score,better_than_baseline,kind,brand,source_url,frame_material\n"
                "Alu,Alu,,,,0,bike,X,https://x,aluminium\n"
                "Hout,Hout,,,,0,bike,X,https://x,bamboe\n"
                "Leeg,Leeg,,,,0,bike,X,https://x,\n",
                encoding="utf-8",
            )
            conn = db.connect(str(Path(tmp) / "k.db"))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                db.import_legacy(conn, seen_listings_path=str(Path(tmp) / "g.json"),
                                 reference_prices_path=str(ref),
                                 reference_price_history_path=str(Path(tmp) / "g.csv"))
            got = {r["pattern"]: json.loads(r["specs_json"]).get("frame_material")
                   for r in conn.execute("SELECT pattern, specs_json FROM model")}
            conn.close()
        self.assertEqual(got, {"Alu": "aluminium", "Hout": None, "Leeg": None})
        self.assertIn("bamboe", err.getvalue())

    def test_the_real_bike_file_only_names_materials_its_specs_name(self):
        import csv
        with open(repo_file("reference_bikes.csv"), encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                material = row["frame_material"]
                if material:
                    self.assertIn(material[:4].lower(), row["specs"].lower() + row["label"].lower(),
                                  row["label"])


if __name__ == "__main__":
    unittest.main()
