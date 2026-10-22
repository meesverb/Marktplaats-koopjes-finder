"""Tests voor beeld/: alleen stdlib, geen torch, geen netwerk.

    python -m unittest discover -s beeld/tests -t beeld/tests

Los van de tests van de repo (tests/): die blijven zonder beeld/ draaien.
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

BEELD_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BEELD_DIR))

import candidates as cand  # noqa: E402
import meet  # noqa: E402
import photos  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


class FakeResponse:
    def __init__(self, status_code=200, body=b"", content_type="image/jpeg", payload=None, text=""):
        self.status_code = status_code
        self.content = body
        self.headers = {"Content-Type": content_type}
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Geeft per aanroep het volgende antwoord uit de lijst; een Exception
    in de lijst wordt opgegooid."""

    def __init__(self, get=(), post=()):
        self.get_answers, self.post_answers = list(get), list(post)
        self.gets, self.posts = [], []

    def _next(self, answers):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def get(self, url, timeout=None):
        self.gets.append(url)
        return self._next(self.get_answers)

    def post(self, url, json=None, timeout=None):
        self.posts.append(json)
        return self._next(self.post_answers)


def make_db(path: Path, rows, columns="item_id, title, url, image_urls, disappeared_at, last_seen"):
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE listing ({columns})")
    for row in rows:
        conn.execute("INSERT INTO listing (item_id, title, url, image_urls, disappeared_at, last_seen) "
                     "VALUES (?, ?, ?, ?, ?, ?)", row)
    conn.commit()
    conn.close()


RACE = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/m1-giant.html"
PARTS = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsonderdelen-racefiets/m2-crank.html"


class TestReadingDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "koopjes.db"

    def test_only_road_bikes_with_photos(self):
        make_db(self.db, [
            ("m1", "Giant Defy", RACE, "https://img/a.jpg https://img/b.jpg", None, "2026-10-20"),
            ("m2", "Crank", PARTS, "https://img/c.jpg", None, "2026-10-21"),
            ("m3", "Heren racefiets", RACE, "", None, "2026-10-21"),
            ("m4", "Trek", RACE.replace("m1", "m4"), "https://img/d.jpg", "2026-10-01", "2026-09-30"),
        ])
        conn = photos.open_readonly(self.db)
        self.addCleanup(conn.close)
        bikes = photos.road_bikes(conn)
        self.assertEqual([b.item_id for b in bikes], ["m1", "m4"])
        self.assertEqual(bikes[0].urls, ["https://img/a.jpg", "https://img/b.jpg"])
        self.assertTrue(bikes[1].disappeared)

    def test_readonly_never_writes(self):
        make_db(self.db, [])
        conn = photos.open_readonly(self.db)
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO listing (item_id) VALUES ('x')")

    def test_missing_database_is_a_clear_error(self):
        with self.assertRaises(FileNotFoundError) as caught:
            photos.open_readonly(self.db)
        self.assertIn("--db", str(caught.exception))

    def test_old_schema_is_a_clear_error(self):
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE listing (item_id, title, url)")
        conn.close()
        with self.assertRaises(photos.SchemaError) as caught:
            photos.open_readonly(self.db)
        self.assertIn("image_urls", str(caught.exception))


class TestSample(unittest.TestCase):
    def bikes(self):
        return ([photos.Bike(f"a{i}", "", ["https://x"], False) for i in range(20)]
                + [photos.Bike(f"g{i}", "", ["https://x"], True) for i in range(3)])

    def test_counts_and_repeatable(self):
        first = photos.sample(self.bikes(), active=5, gone=2)
        self.assertEqual(sum(not b.disappeared for b in first), 5)
        self.assertEqual(sum(b.disappeared for b in first), 2)
        self.assertEqual([b.item_id for b in first], [b.item_id for b in photos.sample(self.bikes(), 5, 2)])

    def test_asks_for_more_than_there_is(self):
        picked = photos.sample(self.bikes(), active=50, gone=50)
        self.assertEqual(len(picked), 23)

    def test_split_urls_keeps_only_https(self):
        self.assertEqual(photos.split_urls("https://a  http://b https://c"), ["https://a", "https://c"])
        self.assertEqual(photos.split_urls(None), [])


class TestPolite(unittest.TestCase):
    def test_waits_the_rest_of_the_delay(self):
        now, slept = [100.0], []
        polite = photos.Polite(1.5, sleep=lambda s: slept.append(s), clock=lambda: now[0])
        polite.wait()
        now[0] = 100.5
        polite.wait()
        self.assertEqual(slept, [1.0])


class TestFetchPhoto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name) / "fotos" / "m1_0.jpg"
        self.polite = photos.Polite(0, sleep=lambda s: None)

    def test_ok_writes_file(self):
        result = photos.fetch_photo(FakeSession(get=[FakeResponse(body=JPEG)]), "https://img/a", self.dest,
                                    self.polite)
        self.assertEqual(result.status, "ok")
        self.assertEqual(self.dest.read_bytes(), JPEG)

    def test_asks_for_the_large_size(self):
        session = FakeSession(get=[FakeResponse(body=JPEG)])
        url = "https://images.marktplaats.com/api/v1/hz-mp-pro-listing/images/ab-12?rule=ecg_mp_eps$_83.jpg"
        photos.fetch_photo(session, url, self.dest, self.polite)
        self.assertEqual(session.gets, [url.replace("$_83", "$_85")])

    def test_falls_back_when_large_size_is_gone(self):
        session = FakeSession(get=[FakeResponse(404), FakeResponse(body=JPEG)])
        url = "https://images.marktplaats.com/x?rule=ecg_mp_eps$_83.jpg"
        result = photos.fetch_photo(session, url, self.dest, self.polite)
        self.assertEqual(result.status, "ok")
        self.assertEqual(session.gets, [url.replace("$_83", "$_85"), url])

    def test_larger_leaves_other_links_alone(self):
        self.assertEqual(photos.larger("https://img.example/a$_83.jpg"), "https://img.example/a$_83.jpg")
        self.assertEqual(photos.larger("https://images.marktplaats.com/x?rule=ecg_mp_eps$_85.jpg"),
                         "https://images.marktplaats.com/x?rule=ecg_mp_eps$_85.jpg")

    def test_already_on_disk_no_request(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(JPEG)
        session = FakeSession()
        self.assertEqual(photos.fetch_photo(session, "https://img/a", self.dest, self.polite).status, "ok")
        self.assertEqual(session.gets, [])

    def test_gone_and_errors(self):
        cases = [
            (FakeResponse(410), "weg"),
            (FakeResponse(404), "weg"),
            (FakeResponse(503), "fout"),
            (FakeResponse(body=b"<html>", content_type="text/html"), "fout"),
            (FakeResponse(body=b""), "fout"),
            (ConnectionError("geen netwerk"), "fout"),
        ]
        for answer, status in cases:
            with self.subTest(answer=answer):
                result = photos.fetch_photo(FakeSession(get=[answer]), "https://img/a", self.dest, self.polite)
                self.assertEqual(result.status, status)
                self.assertFalse(self.dest.exists())


class TestCandidates(unittest.TestCase):
    def test_default_selection(self):
        keys = [c.key for c in cand.select(None)]
        self.assertIn("dinov2-s", keys)
        self.assertNotIn("florence2-l", keys)

    def test_explicit_and_unknown(self):
        self.assertEqual([c.key for c in cand.select("siglip2-b, qwen3.5:2b")], ["siglip2-b", "qwen3.5:2b"])
        self.assertEqual(len(cand.select("alle")), len(cand.CANDIDATES))
        with self.assertRaises(ValueError) as caught:
            cand.select("dinov9")
        self.assertIn("dinov2-s", str(caught.exception))

    def test_gated_model_gets_access_hint(self):
        hint = cand.access_hint(OSError("401 Client Error: gated repo"), "facebook/dinov3-x")
        self.assertIn("hf auth login", hint)
        self.assertTrue(cand.is_access_problem(hint))
        self.assertFalse(cand.is_access_problem(cand.access_hint(RuntimeError("iets anders"), "x")))

    def test_summary_has_no_answers_and_skips_warmup(self):
        m = cand.Measurement("dinov2-s", cand.VECTORS, "facebook/dinov2-small", first_s=9.0,
                             seconds=[1.0, 2.0, 3.0], outputs=[("m1_0.jpg", {"brand": "Giant"})])
        s = m.summary()
        self.assertEqual(s["mediaan_s"], 2.0)
        self.assertEqual(s["fotos_per_uur"], 1800)
        self.assertNotIn("Giant", json.dumps(s))
        self.assertNotIn("m1_0", json.dumps(s))


class TestTeacher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = []
        for i in range(3):
            path = Path(self.tmp.name) / f"m{i}_0.jpg"
            path.write_bytes(JPEG)
            self.paths.append(path)
        self.c = cand.BY_KEY["qwen3.5:2b"]

    def answer(self, brand="Giant"):
        return FakeResponse(payload={"message": {"content": json.dumps({"brand": brand})},
                                     "load_duration": 2e9, "eval_count": 50, "eval_duration": 5e9})

    def test_ollama_not_running(self):
        m = cand.measure_teacher(self.c, self.paths, FakeSession(get=[ConnectionError()]), "http://localhost:1")
        self.assertEqual(m.status, "overgeslagen")
        self.assertIn("Ollama", m.reason)

    def test_model_not_pulled(self):
        tags = FakeResponse(payload={"models": [{"name": "gemma4:e2b"}]})
        m = cand.measure_teacher(self.c, self.paths, FakeSession(get=[tags]), "http://x")
        self.assertEqual(m.status, "overgeslagen")
        self.assertIn("ollama pull qwen3.5:2b", m.reason)

    def test_measures_and_never_sends_listing_text(self):
        tags = FakeResponse(payload={"models": [{"name": "qwen3.5:2b"}]})
        ps = FakeResponse(payload={"models": [{"name": "qwen3.5:2b", "size": 3 * 1024 ** 3}]})
        session = FakeSession(get=[tags, ps], post=[self.answer(), self.answer(), self.answer("Trek")])
        m = cand.measure_teacher(self.c, self.paths, session, "http://x")
        self.assertEqual(m.status, "ok")
        self.assertEqual(len(m.seconds), 2)
        self.assertEqual(m.load_s, 2.0)
        self.assertEqual(m.extra["tokens_per_s"], 10.0)
        self.assertEqual(m.memory_mb, 3072)
        self.assertEqual(m.outputs[2][1], {"brand": "Trek"})
        # Alleen de vaste vraag en de foto: geen titel of omschrijving.
        sent = session.posts[0]["messages"][0]
        self.assertEqual(sent["content"], cand.TEACHER_PROMPT)
        self.assertEqual(set(sent), {"role", "content", "images"})

    def test_model_without_thinking_mode(self):
        tags = FakeResponse(payload={"models": [{"name": "qwen3.5:2b"}]})
        refused = FakeResponse(400, text='{"error":"model does not support thinking"}')
        session = FakeSession(get=[tags, FakeResponse(payload={})], post=[refused, self.answer()])
        m = cand.measure_teacher(self.c, self.paths[:1], session, "http://x")
        self.assertEqual(m.status, "ok")
        self.assertNotIn("think", session.posts[1])


class TestMeetCli(unittest.TestCase):
    def test_list(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(meet.main(["--lijst"]), 0)
        self.assertIn("florence2-b", out.getvalue())

    def test_refuses_impolite_delay(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            meet.main(["--vertraging", "0.2"])

    def test_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(meet.main(["--db", str(Path(tmp) / "geen.db"), "--modellen", "qwen3.5:2b"]), 1)


if __name__ == "__main__":
    unittest.main()
