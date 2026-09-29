"""launcher.py en de knoppen op /start: een ronde starten zoals de
taakplanner dat doet, nooit twee tegelijk en niet vaker dan de wachttijd."""
import http.client
import json
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dashboard
import db
import koopjes
import launcher
from test_koopjes import write_config

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class FakeProc:
    def __init__(self, running=True):
        self.running = running

    def poll(self):
        return None if self.running else 0


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.config = koopjes.load_config(write_config(self.dir))
        self.calls = []

    def popen(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return FakeProc()

    def ran(self, slot, minutes_ago, status="ok"):
        path = self.dir / "logs" / "rondes.jsonl"
        path.parent.mkdir(exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"slot": slot, "started_at": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
                                "status": status, "new": 3}) + "\n")

    def test_start_runs_koopjes_run_slot_in_the_schedule_folder(self):
        launcher.start(self.config, "overdag", popen=self.popen, now=NOW)
        ((command, kwargs),) = self.calls
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(command[1].endswith("koopjes.py"))
        self.assertEqual(command[2:], ["--config", str(self.config.path), "run", "overdag"])
        self.assertEqual(kwargs["cwd"], str(self.dir.resolve()))

    def test_a_slot_that_just_ran_has_to_wait(self):
        self.ran("overdag", 10)
        self.ran("nacht", 120)
        info = {s.name: s for s in launcher.slots(self.config, NOW)}
        self.assertEqual(info["overdag"].ready_at, NOW + timedelta(minutes=20))
        self.assertEqual(info["nacht"].ready_at, NOW + timedelta(hours=4))  # alles ophalen: zes uur
        with self.assertRaisesRegex(launcher.LaunchError, "draaide net"):
            launcher.start(self.config, "overdag", popen=self.popen, now=NOW)
        with self.assertRaisesRegex(launcher.LaunchError, "haalt alles op"):
            launcher.start(self.config, "nacht", popen=self.popen, now=NOW)
        self.assertEqual(self.calls, [])

    def test_a_skipped_round_does_not_count_and_an_old_one_is_fine(self):
        self.ran("overdag", 45)
        self.ran("overdag", 5, status="overgeslagen")
        info = {s.name: s for s in launcher.slots(self.config, NOW)}
        self.assertIsNone(info["overdag"].ready_at)
        self.assertEqual(info["overdag"].last["status"], "ok")

    def test_never_two_at_once(self):
        with koopjes.run_lock(koopjes.lock_path(self.config)):
            self.assertTrue(launcher.is_running(self.config))
            with self.assertRaisesRegex(launcher.LaunchError, "draait al"):
                launcher.start(self.config, "overdag", popen=self.popen, now=NOW)
        self.assertFalse(launcher.is_running(self.config))

    def test_unknown_slot(self):
        with self.assertRaisesRegex(launcher.LaunchError, "Onbekend"):
            launcher.start(self.config, "bestaat-niet", popen=self.popen, now=NOW)

    def test_log_tail(self):
        (self.dir / "logs").mkdir(exist_ok=True)
        (self.dir / "logs" / "koopjes.log").write_text("\n".join(f"regel {i}" for i in range(100)))
        self.assertEqual(launcher.log_tail(self.config, 3), "regel 97\nregel 98\nregel 99")


class StartButtonTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        write_config(self.dir)
        self.db = str(self.dir / "koopjes.db")
        db.connect(self.db).close()
        self.started = []
        original = launcher.start

        def fake_start(config, slot, **kw):
            original(config, slot, popen=lambda command, **kwargs: self.started.append(command) or FakeProc())
            return FakeProc()
        launcher.start = fake_start
        self.addCleanup(setattr, launcher, "start", original)
        self.httpd = dashboard.make_server(self.db, 0, files_dir=self.dir, photo_dir=self.dir / "f",
                                           sheets_config=self.dir / "sheets.json")
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, fields=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        body = None
        if fields is not None:
            body = urllib.parse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, headers)
        r = conn.getresponse()
        text = r.read().decode()
        conn.close()
        return r.status, urllib.parse.unquote(r.getheader("Location") or ""), text

    def test_start_page_has_a_button_per_slot_and_starts_one(self):
        _, _, page = self.request("GET", "/start")
        self.assertIn("data-action='/start/ronde' data-item='overdag'", page)
        self.assertIn("data-item='nacht'", page)
        self.assertIn("data-confirm=", page)  # nacht haalt alles op
        token = re.search(r"data-token='([^']+)'", page).group(1)
        status, where, _ = self.request("POST", "/start/ronde", {"token": token, "item_id": "overdag"})
        self.assertEqual((status, where), (303, "/start?melding=Ronde 'overdag' gestart."))
        self.assertEqual(len(self.started), 1)
        # Draait nog: geen knoppen, wel het logboek; een tweede klik start niets.
        _, _, page = self.request("GET", "/start")
        self.assertIn("Ronde &#x27;overdag&#x27; draait", page)
        self.assertNotIn("data-action='/start/ronde'", page)
        _, where, _ = self.request("POST", "/start/ronde", {"token": token, "item_id": "nacht"})
        self.assertIn("Niet gestart", where)
        self.assertEqual(len(self.started), 1)
        self.assertTrue(json.loads(self.request("GET", "/start/status")[2])["running"])

    def test_no_token_nothing_starts(self):
        _, where, _ = self.request("POST", "/start/ronde", {"token": "fout", "item_id": "overdag"})
        self.assertIn("niets gestart", where)
        self.assertEqual(self.started, [])


if __name__ == "__main__":
    unittest.main()
