"""koopjes.py — scheduled rounds from schedule.json.

No network: the round's steps go through a fake runner, and the summary line
racefiets_jev.py writes is tested with a faked collect_listings(), the same
way test_watchlist.py does it.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import make_listing, mp, repo_file

import db
import koopjes


def write_config(directory: Path, **overrides) -> Path:
    config = {
        "searches": {
            "racefietsen": {"query": "racefiets", "category": "fietsen-racefietsen",
                            "min_frame_height": 54, "max_frame_height": 58},
            "fietscomputer": {"query": "wahoo elemnt,garmin edge", "max_price": 350},
        },
        "slots": {
            "overdag": {"searches": ["racefietsen"], "pages": 8, "sort": "newest",
                        "times": ["08:30", "13:30"]},
            "nacht": {"searches": ["fietscomputer"], "pages": 0, "times": ["zo 03:00"],
                      "valuation": True},
        },
    }
    config.update(overrides)
    path = directory / "schedule.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)


class ShippedConfigTest(unittest.TestCase):
    def test_the_schedule_in_the_repo_is_valid(self):
        config = koopjes.load_config(Path(repo_file("schedule.json")))
        self.assertIn("overdag", config.slots)
        for slot in config.slots.values():
            self.assertTrue(slot.times, slot.name)

    def test_every_reference_file_it_names_exists(self):
        config = koopjes.load_config(Path(repo_file("schedule.json")))
        for name, search in config.searches.items():
            ref = search["filters"].get("reference_file")
            if ref:
                self.assertTrue(Path(repo_file(ref)).exists(), f"{name}: {ref}")


class ConfigTest(TempDirTest):
    def test_times(self):
        self.assertEqual(koopjes.parse_time("08:30"), koopjes.SlotTime(8, 30))
        self.assertEqual(koopjes.parse_time("zo 05:00"), koopjes.SlotTime(5, 0, "zo"))
        for bad in ["8.30", "25:00", "zondag 05:00", "ma di 05:00", "12"]:
            with self.subTest(bad=bad), self.assertRaises(koopjes.ConfigError):
                koopjes.parse_time(bad)

    def test_a_valid_config_loads(self):
        config = koopjes.load_config(write_config(self.dir))
        self.assertEqual(config.slots["overdag"].pages, 8)
        self.assertEqual(config.searches["racefietsen"]["filters"]["category"], "fietsen-racefietsen")
        self.assertTrue(config.slots["nacht"].valuation)

    def test_mistakes_fail_at_load_time_with_a_readable_message(self):
        cases = {
            "unknown filter": {"searches": {"x": {"query": "x", "maxprice": 3}}},
            "wrong type": {"searches": {"x": {"query": "x", "max_price": "400"}}},
            "no query": {"searches": {"x": {"max_price": 400}}},
            "reserved name": {"searches": {"all": {"query": "x"}}},
            "unknown search in slot": {"slots": {"s": {"searches": ["bestaat-niet"]}}},
            "bad sort": {"slots": {"s": {"searches": ["racefietsen"], "sort": "datum"}}},
            "bad pages": {"slots": {"s": {"searches": ["racefietsen"], "pages": -1}}},
            "bad time": {"slots": {"s": {"searches": ["racefietsen"], "times": ["25:00"]}}},
        }
        for label, override in cases.items():
            with self.subTest(label):
                with self.assertRaises(koopjes.ConfigError):
                    koopjes.load_config(write_config(self.dir, **override))

    def test_not_json_is_a_config_error(self):
        path = self.dir / "schedule.json"
        path.write_text("{ niet json", encoding="utf-8")
        with self.assertRaises(koopjes.ConfigError):
            koopjes.load_config(path)

    def test_the_search_command_carries_the_slot_settings(self):
        config = koopjes.load_config(write_config(self.dir))
        command = koopjes.search_command(config, config.slots["overdag"])
        joined = " ".join(command)
        for part in ["--watchlist racefietsen", "--pages 8", "--sort newest",
                     "--open-browser never", "--summary-file logs/runs.jsonl"]:
            self.assertIn(part, joined)


class RunSlotTest(TempDirTest):
    def run_slot(self, slot, codes=None):
        config = koopjes.load_config(write_config(self.dir))
        calls = []
        codes = dict(codes or {})

        def runner(command, log, cwd):
            script = Path(command[1]).name
            calls.append(script)
            log.line(f"(nep) {script}")
            return codes.get(script, 0)

        with koopjes.working_directory(self.dir):
            code = koopjes.run_slot(config, slot, runner=runner, echo=False)
        return code, calls, config

    def test_a_round_syncs_the_searches_runs_the_steps_and_writes_the_overview(self):
        code, calls, config = self.run_slot("nacht")
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["racefiets_jev.py", "valuation.py"])
        conn = db.connect(str(self.dir / "koopjes.db"))
        names = [w["name"] for w in db.list_watchlists(conn)]
        conn.close()
        self.assertEqual(names, ["fietscomputer", "racefietsen"])
        self.assertTrue((self.dir / "overzicht.html").exists())
        log = (self.dir / "logs" / "koopjes.log").read_text(encoding="utf-8")
        self.assertIn("ronde 'nacht'", log)

    def test_too_few_comps_is_not_a_failed_round(self):
        code, _, _ = self.run_slot("nacht", {"valuation.py": koopjes.VALUATION_NO_COMPS})
        self.assertEqual(code, 0)
        log = (self.dir / "logs" / "koopjes.log").read_text(encoding="utf-8")
        self.assertIn("Geen taxatie", log)

    def test_a_failed_search_fails_the_round_but_still_writes_the_overview(self):
        code, calls, _ = self.run_slot("nacht", {"racefiets_jev.py": 1})
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["racefiets_jev.py", "valuation.py"])
        self.assertTrue((self.dir / "overzicht.html").exists())

    def test_a_round_that_finds_another_running_is_skipped(self):
        config = koopjes.load_config(write_config(self.dir))
        with koopjes.run_lock(koopjes.lock_path(config)):
            code, calls, _ = self.run_slot("overdag")
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        log = (self.dir / "logs" / "koopjes.log").read_text(encoding="utf-8")
        self.assertIn("Overgeslagen", log)

    def test_the_lock_is_free_again_afterwards(self):
        self.run_slot("overdag")
        code, calls, _ = self.run_slot("overdag")
        self.assertEqual(calls, ["racefiets_jev.py"])

    def test_an_unexpected_error_ends_up_in_the_log(self):
        def broken(*args, **kwargs):
            raise RuntimeError("database is locked")

        with mock.patch.object(koopjes, "sync_searches", broken):
            code, calls, _ = self.run_slot("overdag")
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        log = (self.dir / "logs" / "koopjes.log").read_text(encoding="utf-8")
        self.assertIn("database is locked", log)
        # And the lock is released for the next round.
        _, calls, _ = self.run_slot("overdag")
        self.assertEqual(calls, ["racefiets_jev.py"])

    def test_a_console_that_cannot_show_a_title_does_not_stop_the_round(self):
        raw = io.BytesIO()
        console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        log = koopjes.Log(self.dir / "logs" / "x.log")
        with contextlib.redirect_stdout(console):
            log.line("Gazelle racefiets ✅ ≥ €100")
        console.flush()
        log.close()
        self.assertIn("✅", (self.dir / "logs" / "x.log").read_text(encoding="utf-8"))
        self.assertIn(b"Gazelle racefiets", raw.getvalue())

    def test_unknown_slot(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, calls, _ = self.run_slot("middag")
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("overdag", err.getvalue())


class SummaryTest(TempDirTest):
    def test_the_script_appends_one_line_per_report(self):
        listings = {
            "wahoo elemnt": [
                make_listing(item_id="roam", title="Wahoo Elemnt Roam v2", price_eur=200.0),
                make_listing(item_id="bolt", title="Wahoo Elemnt Bolt", price_eur=90.0),
            ],
            "garmin edge": [make_listing(item_id="edge", title="Garmin Edge 830", price_eur=150.0)],
        }
        conn = db.connect(str(self.dir / "koopjes.db"))
        db.save_watchlist(conn, "fietscomputer", "wahoo elemnt,garmin edge", {})
        conn.close()

        def fake_collect(query, pages, delay, **options):
            return mp.CrawlResult(listings[query], complete=True)

        argv = [
            "--watchlist", "fietscomputer", "--no-html", "--no-log", "--no-price-history",
            "--no-notify-better", "--open-browser", "never",
            "--db", str(self.dir / "koopjes.db"),
            "--history-file", str(self.dir / "history.json"),
            "--summary-file", str(self.dir / "runs.jsonl"),
        ]
        with mock.patch.object(mp, "collect_listings", fake_collect), \
                mock.patch.object(mp, "enrich_bid_listings", lambda *a, **k: None), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mp.main(argv), 0)

        summaries = koopjes.load_summaries(self.dir / "runs.jsonl")
        self.assertEqual(set(summaries), {"fietscomputer wahoo elemnt", "fietscomputer garmin edge"})
        wahoo = summaries["fietscomputer wahoo elemnt"]
        self.assertEqual(wahoo["listings"], 2)
        self.assertEqual(wahoo["new"], 2)
        self.assertTrue(wahoo["crawl_complete"])
        self.assertEqual(len(wahoo["highlights"]), 2)
        self.assertEqual(
            [s["name"] for s in koopjes.summaries_for_search(
                "fietscomputer", "wahoo elemnt,garmin edge", summaries)],
            ["fietscomputer wahoo elemnt", "fietscomputer garmin edge"],
        )

    def test_latest_line_wins_and_a_broken_line_is_skipped(self):
        path = self.dir / "runs.jsonl"
        path.write_text(
            json.dumps({"name": "x", "new": 1}) + "\n{kapot\n" + json.dumps({"name": "x", "new": 5}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(koopjes.load_summaries(path)["x"]["new"], 5)
        self.assertEqual(koopjes.load_summaries(self.dir / "bestaat-niet.jsonl"), {})


class HighlightSelectionTest(unittest.TestCase):
    def test_running_bids_only_count_when_they_beat_the_reference(self):
        listings = [
            make_listing(item_id="bod", price_type="FAST_BID", price_is_bid=True, price_eur=20.0),
            make_listing(item_id="vast", price_eur=500.0),
            make_listing(item_id="beter", price_type="FAST_BID", price_is_bid=True, price_eur=30.0),
        ]
        for l in listings:
            l.is_new = True
        listings[0].deal_score, listings[1].deal_score, listings[2].deal_score = 100.0, 60.0, 90.0
        listings[2].ref_better = True
        summary = mp.run_summary(listings, name="x", query="x", finished_at="t", report_path=None,
                                 crawl_complete=True, crawl_note="")
        self.assertEqual([h["url"] for h in summary["highlights"]],
                         [listings[2].url, listings[1].url])
        self.assertEqual(summary["upgrades"], [])


class OverviewTest(TempDirTest):
    def test_the_page_shows_every_search_highlights_and_the_schedule(self):
        config = koopjes.load_config(write_config(self.dir))
        summaries = {
            "racefietsen": {
                "name": "racefietsen", "query": "racefiets", "finished_at": "2026-09-22T11:30:00+00:00",
                "report": "racefiets_report_racefietsen.html", "listings": 39, "new": 3,
                "better": 1, "top_deals": 2, "price_drops": 0,
                "highlights": [{"title": "Canyon <Endurace>", "price_eur": 900.0, "deal_score": 85.0,
                                "better": True, "ref_label": "Canyon Endurace CF SL(X) Disc",
                                "url": "https://www.marktplaats.nl/v/x/m1"}],
            }
        }
        valuations = [{"scenario": "B", "low_eur": 400.0, "mid_eur": 450.0, "high_eur": 500.0,
                       "confidence": "laag", "created_at": "2026-09-22T01:00:00+00:00"}]
        summaries["racefietsen"]["upgrades"] = [{
            "title": "Canyon Endurace CF SL Disc 8.0", "price_eur": 1200.0, "price_basis": "vraagprijs ×0,90",
            "quality": 72, "gain": 21, "per_100_eur": 1.8, "new": True, "url": "https://www.marktplaats.nl/v/x/m2",
        }]
        page = koopjes.render_overview(config, summaries, valuations)
        self.assertIn("Beste upgrades", page)
        self.assertIn("kwaliteit 72 (+21)", page)
        self.assertIn("racefiets_report_racefietsen.html", page)
        self.assertIn("Canyon &lt;Endurace&gt;", page)
        self.assertIn("beter: Canyon Endurace", page)
        self.assertIn("nog niet gedraaid", page)  # fietscomputer
        self.assertIn("€450", page)
        self.assertIn("08:30, 13:30", page)
        self.assertIn("zo 03:00", page)


class ScheduleCommandsTest(TempDirTest):
    def test_windows_and_cron(self):
        config = koopjes.load_config(write_config(self.dir))
        windows = koopjes.windows_commands(config, r"C:\Python\python.exe", r"C:\repo\koopjes.py")
        self.assertEqual(len(windows), 3)
        self.assertIn('/SC DAILY /ST 08:30', windows[0])
        self.assertIn(r'/TR "\"C:\Python\python.exe\" \"C:\repo\koopjes.py\" run overdag"', windows[0])
        self.assertIn("/SC WEEKLY /D SUN /ST 03:00", windows[2])
        cron = koopjes.cron_lines(config, "/usr/bin/python3", "/repo/koopjes.py")
        self.assertEqual(cron[0], "30 8 * * *  '/usr/bin/python3' '/repo/koopjes.py' run overdag")
        self.assertTrue(cron[2].startswith("0 3 * * 0 "))


class MainTest(TempDirTest):
    def test_a_broken_config_stops_with_a_message(self):
        path = self.dir / "schedule.json"
        path.write_text("[]", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(koopjes.main(["--config", str(path), "status"]), 1)
        self.assertIn("fout in het schema", err.getvalue())

    def test_paths_are_relative_to_the_schedule_and_the_cwd_is_restored(self):
        path = write_config(self.dir)
        before = Path.cwd()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(koopjes.main(["--config", str(path), "overview"]), 0)
        self.assertTrue((self.dir / "overzicht.html").exists())
        self.assertEqual(Path.cwd(), before)


class ListsTest(TempDirTest):
    def test_model_family_groups_on_brand_and_first_model_word(self):
        brands = koopjes.known_brands(koopjes.load_config(write_config(self.dir)))
        self.assertEqual(koopjes.model_family("Giant TCR Advanced maat M", brands), "Giant Tcr")
        self.assertEqual(koopjes.model_family("Mooie racefiets Canyon Ultimate CF", brands),
                         "Canyon Ultimate")
        self.assertEqual(koopjes.model_family("Giant racefiets", brands), "Giant")
        self.assertEqual(koopjes.model_family("Eddy Merckx EMX-3", brands), "Eddy Merckx Emx-3")
        self.assertEqual(koopjes.model_family("Vintage koersfiets", brands), "(merk onbekend)")

    def test_unmatched_are_road_bikes_without_a_bike_model(self):
        from datetime import datetime, timezone
        config = koopjes.load_config(write_config(self.dir))
        conn = db.connect(str(self.dir / "koopjes.db"))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        bike = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/"
        db.sync_listings(conn, "racefiets", [
            make_listing(item_id="los", title="Canyon Ultimate", url=bike + "m1-canyon"),
            make_listing(item_id="bekend", title="Giant Defy Composite", url=bike + "m2-defy"),
            make_listing(item_id="onderdeel", title="Canyon zadelpen",
                         url="https://www.marktplaats.nl/v/fietsen-en-brommers/fietsonderdelen/m3-x"),
        ], now)
        conn.execute("INSERT INTO model (kind, model, pattern) VALUES ('bike', 'Defy', 'Defy')")
        db.sync_listing_models(conn, {"bekend": ["Defy"]})
        conn.close()
        with koopjes.working_directory(self.dir):
            unmatched, deals = koopjes.write_lists(config)
        text = unmatched.read_text(encoding="utf-8")
        self.assertIn("Canyon Ultimate", text)
        self.assertNotIn("Giant Defy Composite", text)
        self.assertNotIn("zadelpen", text)
        self.assertIn("Nog niets", deals.read_text(encoding="utf-8"))

    def test_best_deals_list_urls_and_reasons_but_no_running_bids(self):
        listings = [
            make_listing(item_id="vast", title="Canyon Endurace", price_eur=400.0,
                         url="https://www.marktplaats.nl/v/x/vast"),
            make_listing(item_id="bod", title="Lopend bod", price_type="FAST_BID",
                         price_is_bid=True, price_eur=20.0, url="https://www.marktplaats.nl/v/x/bod"),
        ]
        for l in listings:
            l.deal_score, l.deal_reasons = 95.0, "40% van mediaan"
        summary = mp.run_summary(listings, name="racefietsen", query="racefiets", finished_at="t",
                                 report_path=None, crawl_complete=True, crawl_note="")
        self.assertEqual([d["url"] for d in summary["deals"]], ["https://www.marktplaats.nl/v/x/vast"])
        config = koopjes.load_config(write_config(self.dir))
        text = koopjes.render_best_deals(config, {"racefietsen": summary})
        self.assertIn("https://www.marktplaats.nl/v/x/vast", text)
        self.assertIn("waarom: 40% van mediaan", text)
        self.assertNotIn("Lopend bod", text)


if __name__ == "__main__":
    unittest.main()
