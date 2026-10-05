"""De upgradetest (upgrade_test.py, /upgrade): de nieuwe knoppen van de score,
de regel van de eigenaar, zijn oordelen, de uitslag, het zoeken naar een
regel die past, de uitdraai, en dat een opgeslagen regel overal doorwerkt."""
import contextlib
import copy
import http.client
import io
import json
import math
import re
import shutil
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from helpers import close_databases_before_cleanup, make_listing, repo_file

import dashboard
import db
import racebikes as rb
import report
import scoring as sc
import upgrade as up
import upgrade_test as ut
import valuation as val

BIKE_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsen-racefietsen/{}-x"
PART_URL = "https://www.marktplaats.nl/v/fietsen-en-brommers/fietsonderdelen/{}-x"
OWNER_SPECS = val.parse_owner_bike(Path(repo_file("mijn_fiets.md")).read_text(encoding="utf-8")).specs


def bike(item_id, price, title, description, frame_height="56 cm", **kw):
    kw.setdefault("url", BIKE_URL.format(item_id))
    kw.setdefault("image_urls", f"https://images.example/{item_id}.jpg")
    return make_listing(item_id=item_id, title=title, price_eur=price, description=description,
                        frame_height=frame_height, **kw)


BIKES = [
    bike("tcr", 600.0, "Giant TCR Advanced 2016 Ultegra", "Carbon frame, Shimano Ultegra 11 speed, velgremmen."),
    bike("emonda", 900.0, "Trek Emonda 2021 105", "Carbon frame, Shimano 105 11 speed, hydraulische schijfremmen."),
    bike("dura", 450.0, "Racefiets 2010 Dura-Ace powermeter", "Carbon frame, Dura-Ace 10 speed, velgremmen, powermeter."),
    bike("staal", 250.0, "Stalen racefiets 1990 Dura-Ace", "Stalen frame, Dura-Ace, velgremmen."),
    bike("alu", 350.0, "Cube Attain 2019 Tiagra", "Aluminium frame, Shimano Tiagra, velgremmen."),
    bike("kaal", 300.0, "Racefiets", "Mooie fiets."),
    bike("groot", 500.0, "Specialized Tarmac 2020 Ultegra", "Carbon frame, Ultegra, velgremmen.", frame_height="61 cm"),
    bike("frame", 200.0, "Giant TCR frame 2018", "Carbon frame los.", url=PART_URL.format("frame")),
]


def config(**changes):
    """scoring_config.json met wijzigingen als {"weights.frame": 0.5}."""
    out = sc.load_config()
    for path, value in changes.items():
        *parents, key = path.split(".")
        node = out
        for name in parents:
            node = node.setdefault(name, {})
        node[key] = value
    return out


class ScoringOptionsTest(unittest.TestCase):
    def setUp(self):
        self.config = sc.load_config()
        self.owner = sc.owner_build(OWNER_SPECS, "Giant Defy Composite", self.config)

    def test_the_new_options_are_off_in_the_shipped_config(self):
        self.assertEqual(self.config["drivetrain"]["age_decay_per_year"], 0)
        self.assertIsNone(self.config["wheels"]["eigen_wielen"])
        self.assertEqual(self.config["upgrade"], {"marge": 5, "onbekend": "neutraal"})
        # en de eigen fiets scoort dus als altijd
        self.assertAlmostEqual(sc.score_build(self.owner, self.config, as_of_year=2026).total, 50.8, places=1)

    def test_age_on_the_drivetrain(self):
        old = sc.Build(groupset_tier=6, model_year=2010)
        self.assertEqual(sc.score_drivetrain(old, self.config, as_of_year=2026).score, 100)
        decayed = sc.score_drivetrain(old, config(**{"drivetrain.age_decay_per_year": 0.015}), as_of_year=2026)
        self.assertAlmostEqual(decayed.score, 100 * (1 - 0.24))
        self.assertIn("-24% op de aandrijving", " ".join(decayed.reasons))
        capped = sc.score_drivetrain(old, config(**{"drivetrain.age_decay_per_year": 0.05}), as_of_year=2026)
        self.assertAlmostEqual(capped.score, 70.0)  # age_decay_max 0,30
        self.assertEqual(sc.score_drivetrain(sc.Build(groupset_tier=6), config(
            **{"drivetrain.age_decay_per_year": 0.05})).score, 100)  # zonder jaar geen verval

    def test_own_wheels_get_the_score_the_owner_gave_them(self):
        self.assertEqual(sc.score_wheels(self.owner, self.config).score, 85)  # CSC telt als merk
        own = sc.owner_build(OWNER_SPECS, "Defy", config(**{"wheels.eigen_wielen": 55}))
        wheels = sc.score_wheels(own, self.config)
        self.assertEqual(wheels.score, 55)
        self.assertIn("zelf ingesteld", wheels.reasons[0])

    def test_fill_unknown_takes_what_the_listing_does_not_say_from_the_own_bike(self):
        listing = sc.Build(frame_material="carbon", model_year=2021)
        filled = sc.fill_unknown(listing, self.owner)
        self.assertEqual((filled.frame_material, filled.model_year), ("carbon", 2021))  # wat bekend is blijft
        self.assertEqual(filled.groupset_tier, 5)
        self.assertEqual(filled.brake_type, "velrem")
        self.assertEqual(filled.wheel_material, "carbon")
        self.assertEqual(set(filled.assumed), {"frame_class", "groupset_tier", "speeds", "brake_type", "wheels"})
        quality = sc.score_build(filled, self.config)
        self.assertIn("gelijk aan jouw fiets", quality.dimensions["drivetrain"].reasons[0])
        self.assertIn("gelijk aan jouw fiets", quality.dimensions["wheels"].reasons[0])
        # elektronisch alleen mee als de groepset onbekend was
        self.assertFalse(sc.fill_unknown(sc.Build(groupset_tier=4), sc.Build(groupset_tier=6, electronic=True)).electronic)
        self.assertTrue(sc.fill_unknown(sc.Build(), sc.Build(groupset_tier=6, electronic=True)).electronic)
        self.assertIs(sc.fill_unknown(self.owner, self.owner), self.owner)  # niets onbekend: dezelfde

    def test_a_branded_wheel_without_material_is_not_unknown(self):
        listing = sc.Build(wheel_branded=True)
        self.assertNotIn("wheels", sc.fill_unknown(listing, self.owner).assumed)


class FinderOptionsTest(unittest.TestCase):
    def setUp(self):
        self.listings = [l for l in BIKES]
        self.budgets = up.budgets_from_valuation(390.0, extra_budget_eur=250.0)

    def run_finder(self, cfg, **kw):
        owner = sc.owner_build(OWNER_SPECS, "Defy", cfg)
        baseline = sc.score_build(owner, cfg).total
        return up.find_upgrades(self.listings, baseline=baseline, config=cfg, budgets=self.budgets,
                                target_size_cm=56.0, owner_wheels=up.owner_wheels(owner), owner_build=owner, **kw)

    def test_the_margin_comes_from_the_rule(self):
        strict = self.run_finder(config(**{"upgrade.marge": 40}))
        self.assertEqual(strict.candidates, ())
        loose = self.run_finder(config(**{"upgrade.marge": -20}))
        self.assertGreater(len(loose.candidates), 0)
        # een meegegeven marge gaat voor
        self.assertEqual(self.run_finder(config(**{"upgrade.marge": -20}), margin=40).candidates, ())

    def test_scored_has_every_listing_that_got_a_score(self):
        result = self.run_finder(config())
        # het onderdeel en de te grote fiets vallen vóór de score af
        self.assertEqual(set(result.scored), {"tcr", "emonda", "dura", "staal", "alu", "kaal"})
        reasons = {r.listing.item_id: r.reason for r in result.rejected}
        self.assertIn("categorie fietsonderdelen", reasons["frame"])
        self.assertIn("buiten de maat", reasons["groot"])

    def test_like_own_bike_scores_unknown_parts_as_the_own_bike(self):
        cfg = config(**{"upgrade.onbekend": "gelijk"})
        result = self.run_finder(cfg)
        kaal = result.scored["kaal"]
        owner = sc.owner_build(OWNER_SPECS, "Defy", cfg)
        own = sc.score_build(owner, cfg)
        for name in ("drivetrain", "brakes", "wheels", "frame"):
            self.assertAlmostEqual(kaal.quality.dimensions[name].score, own.dimensions[name].score, places=6)
        self.assertEqual(kaal.route, up.ROUTE_UNKNOWN)  # de route rekent op wat de advertentie zegt
        self.assertIn("onbekend, gelijk aan jouw fiets gerekend", " ".join(kaal.reasons))
        self.assertFalse(up.needs_year(kaal, cfg))
        self.assertTrue(up.needs_year(self.run_finder(config()).scored["kaal"], config()))

    def test_own_wheel_score_moves_to_a_rim_brake_bike(self):
        cfg = config(**{"wheels.eigen_wielen": 70})
        tcr = self.run_finder(cfg).scored["tcr"]
        self.assertEqual(tcr.route, up.ROUTE_RIM)
        self.assertEqual(tcr.quality.dimensions["wheels"].score, 70)
        self.assertIn("wielset verhuist mee", " ".join(tcr.reasons))
        emonda = self.run_finder(cfg).scored["emonda"]  # schijfrem: niet
        self.assertNotEqual(emonda.quality.dimensions["wheels"].score, 70)

    def test_old_two_tuple_owner_wheels_still_work(self):
        build, moved = up.with_owner_wheels(sc.Build(), ("carbon", True), config())
        self.assertEqual(build.wheel_material, "carbon")
        self.assertEqual(moved, "eigen carbon wielset verhuist mee (velremkandidaat)")


class RuleTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        close_databases_before_cleanup(self)
        self.db = str(self.dir / "koopjes.db")
        db.connect(self.db).close()
        self.shape = sc.load_config()

    def test_clean_rule_keeps_the_shape(self):
        rule = ut.clean_rule({"weights": {"frame": "0,5", "nieuw": 3}, "onzin": 1}, self.shape)
        self.assertEqual(rule["weights"]["frame"], 0.5)
        self.assertEqual(rule["weights"]["drivetrain"], 0.25)  # niet meegestuurd: uit de vorm
        self.assertNotIn("nieuw", rule["weights"])
        self.assertNotIn("onzin", rule)
        self.assertEqual(rule["upgrade"]["onbekend"], "neutraal")
        self.assertIsNone(rule["wheels"]["eigen_wielen"])
        self.assertEqual(ut.clean_rule({"wheels": {"eigen_wielen": ""}}, self.shape)["wheels"]["eigen_wielen"], None)
        self.assertEqual(ut.clean_rule({"wheels": {"eigen_wielen": 60}}, self.shape)["wheels"]["eigen_wielen"], 60)

    def test_clean_rule_refuses_what_cannot_be(self):
        bad = [
            {"weights": {"frame": "nan"}}, {"weights": {"frame": float("inf")}}, {"weights": {"frame": -1}},
            {"weights": {"frame": True}}, {"brakes": {"score": {"velrem": 101}}},
            {"drivetrain": {"age_decay_per_year": 0.5}}, {"upgrade": {"onbekend": "misschien"}},
            {"upgrade": {"marge": 1e9}}, {"weights": {"frame": 0, "drivetrain": 0, "brakes": 0, "wheels": 0, "extras": 0}},
            {"weights": {"frame": "veel"}}, "geen dict",
        ]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ut.RuleError):
                ut.clean_rule(raw, self.shape)

    def test_save_load_apply_and_reset(self):
        self.assertEqual(ut.apply_saved_rule(self.shape, self.db), (self.shape, None))
        before = ut.rule_stamp(self.db)
        saved = ut.save_rule(self.db, {"weights": {"frame": 0.6}, "upgrade": {"marge": 2}})
        self.assertEqual(saved["weights"]["frame"], 0.6)
        self.assertNotEqual(ut.rule_stamp(self.db), before)
        applied, at = ut.apply_saved_rule(sc.load_config(), self.db)
        self.assertEqual(applied["weights"]["frame"], 0.6)
        self.assertEqual(up.config_margin(applied), 2)
        self.assertTrue(at)
        self.assertIn("gewicht frame: 0,3 → 0,6", ut.rule_changes(applied))
        self.assertIn("upgrade marge: 5 → 2", ut.rule_changes(applied))
        ut.reset_rule(self.db)
        self.assertEqual(ut.apply_saved_rule(self.shape, self.db)[1], None)

    def test_a_broken_stored_rule_is_ignored(self):
        conn = db.connect(self.db)
        try:
            for raw in ("{niet json", json.dumps({"config": {"weights": {"frame": "x"}}}), json.dumps([1])):
                db.set_setting(conn, ut.RULE_KEY, raw)
                self.assertEqual(ut.apply_saved_rule(self.shape, self.db), (self.shape, None))
        finally:
            conn.close()
        self.assertEqual(ut.apply_saved_rule(self.shape, str(self.dir / "bestaat_niet.db")), (self.shape, None))

    def test_the_owner_context_uses_the_saved_rule(self):
        ut.save_rule(self.db, {"weights": {"wheels": 0}, "upgrade": {"marge": 1}, "wheels": {"eigen_wielen": 60}})
        owner, problem = report.load_owner_context(repo_file("mijn_fiets.md"), self.db)
        self.assertEqual(owner.config["weights"]["wheels"], 0)
        self.assertEqual(owner.build.wheel_score, 60)
        self.assertEqual(up.config_margin(owner.config), 1)
        # een eigen config-bestand: alleen dat
        other = self.dir / "eigen.json"
        other.write_text(json.dumps(sc.load_config()), encoding="utf-8")
        owner, _ = report.load_owner_context(repo_file("mijn_fiets.md"), self.db, config_path=other)
        self.assertEqual(owner.config["weights"]["wheels"], 0.15)


class BikesCase(unittest.TestCase):
    track_connections = True

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        if self.track_connections:
            close_databases_before_cleanup(self)
        self.db = str(self.dir / "koopjes.db")
        self.intake = repo_file("mijn_fiets.md")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        old = bike("weg", 700.0, "Canyon Ultimate 2019 Ultegra", "Carbon frame, Ultegra 11 speed, velgremmen.")
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", [old], (self.now - timedelta(days=20)).isoformat())
        db.sync_listings(conn, "racefiets", BIKES, self.now.isoformat())
        conn.close()

    def label(self, item_id, label):
        conn = db.connect(self.db)
        try:
            db.set_upgrade_label(conn, item_id, label, f"titel {item_id}", 100.0)
        finally:
            conn.close()

    def judge(self, cfg=None):
        owner, _ = ut.load_owner(self.db, self.intake)
        return owner, ut.make_judge(owner, cfg or owner.config)


class LabelTest(BikesCase):
    def test_labels_are_stored_changed_and_removed(self):
        self.label("tcr", "ja")
        self.label("tcr", "nee")
        conn = db.connect(self.db)
        try:
            labels = db.list_upgrade_labels(conn)
            self.assertEqual(labels["tcr"]["label"], "nee")
            self.assertEqual(labels["tcr"]["title"], "titel tcr")
            db.set_upgrade_label(conn, "tcr", None)
            self.assertEqual(db.list_upgrade_labels(conn), {})
            version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(version, len(db.MIGRATIONS))

    def test_bikes_with_a_label_stay_after_they_are_gone(self):
        self.label("weg", "ja")
        bikes = {b.listing.item_id: b for b in ut.load_bikes(self.db)}
        self.assertFalse(bikes["weg"].active)
        self.assertEqual(bikes["weg"].label, "ja")
        self.assertTrue(bikes["tcr"].active)
        self.assertIsNone(bikes["tcr"].label)

    def test_the_owners_own_year_counts(self):
        conn = db.connect(self.db)
        try:
            db.set_bike_link(conn, "kaal", year=2022)
        finally:
            conn.close()
        kaal = next(b for b in ut.load_bikes(self.db) if b.listing.item_id == "kaal")
        self.assertEqual(kaal.prepared.build.model_year, 2022)
        self.assertEqual(ut.year_source(kaal), "jij")

    def test_prepared_bikes_are_remembered(self):
        cache: dict = {}
        ut.load_bikes(self.db, prepared=cache)
        with mock.patch.object(up, "prepare_candidate", side_effect=AssertionError("opnieuw gelezen")):
            ut.load_bikes(self.db, prepared=cache)


class AssessTest(BikesCase):
    def test_the_verdict_is_the_one_on_racefietsen(self):
        for rule in ({}, {"upgrade": {"marge": -10, "onbekend": "gelijk"}, "weights": {"frame": 1.0}},
                     {"upgrade": {"marge": 0}, "wheels": {"eigen_wielen": 50}, "drivetrain": {"age_decay_per_year": 0.03}}):
            with self.subTest(rule=rule):
                if rule:
                    ut.save_rule(self.db, rule)
                owner, judge = self.judge()
                base = rb.build_base(self.db, self.intake)
                verdicts = {a.bike.listing.item_id: a for a in ut.assess_all(ut.load_bikes(self.db), judge)}
                for row in base.rows:
                    a = verdicts[row.listing.item_id]
                    self.assertEqual(row.upgrade_ok, a.verdict, (row.listing.item_id, row.upgrade_why, a.why))
                    self.assertEqual(row.upgrade_why, a.why)

    def test_better_is_the_quality_question_only(self):
        _, judge = self.judge(config(**{"upgrade.marge": -20, "weights.frame": 0.0}))
        found = {a.bike.listing.item_id: a for a in ut.assess_all(ut.load_bikes(self.db), judge)}
        self.assertTrue(found["groot"].better)  # beter, al past hij niet
        self.assertFalse(found["groot"].verdict)
        self.assertIn("buiten de maat", found["groot"].why)

    def test_agreement_counts_and_sorts(self):
        for item_id, label in (("tcr", "ja"), ("emonda", "ja"), ("staal", "nee"), ("dura", "nee"), ("alu", "twijfel")):
            self.label(item_id, label)
        _, judge = self.judge()
        agree = ut.agreement(ut.assess_all(ut.load_bikes(self.db), judge))
        self.assertEqual(agree.judged, 4)
        self.assertEqual(agree.unsure, 1)
        self.assertEqual({a.bike.listing.item_id for a in agree.missed}, {"tcr", "emonda"})  # de klacht van de eigenaar
        self.assertEqual({a.bike.listing.item_id for a in agree.wrong}, {"dura"})  # oude Dura-Ace met powermeter
        self.assertEqual([a.bike.listing.item_id for a in agree.both_no], ["staal"])
        self.assertIn("1 van je 4", agree.text())
        self.assertEqual(ut.agreement([]).text(), "Nog geen oordelen (ja of nee).")

    def test_explain_adds_up_to_the_gain(self):
        _, judge = self.judge()
        for a in ut.assess_all(ut.load_bikes(self.db), judge):
            info = ut.explain(a, judge)
            self.assertAlmostEqual(sum(p["punten"] for p in info["onderdelen"]), info["winst"], delta=0.3)
            self.assertEqual(len(info["onderdelen"]), 5)

    def test_the_queue(self):
        self.label("tcr", "ja")
        conn = db.connect(self.db)
        try:
            db.set_mark(conn, "kaal", "weg", reason="geen racefiets", price_eur=300.0)
        finally:
            conn.close()
        _, judge = self.judge()
        order = ut.queue(ut.assess_all(ut.load_bikes(self.db), judge))
        self.assertEqual(sorted(order), ["alu", "dura", "emonda", "staal"])  # niet beoordeeld, past, racefiets
        self.assertEqual(order, ut.queue(ut.assess_all(ut.load_bikes(self.db), judge)))  # vaste volgorde
        # om en om uit de winstbanden: de eerste twee komen uit verschillende banden
        gains = {a.bike.listing.item_id: a.gain for a in ut.assess_all(ut.load_bikes(self.db), judge)}
        band = lambda i: sum(1 for edge in ut.QUEUE_BANDS if gains[i] > edge)
        self.assertNotEqual(band(order[0]), band(order[1]))


class SearchTest(BikesCase):
    def test_too_few_judgments(self):
        self.label("tcr", "ja")
        owner, _ = self.judge()
        found = ut.search(ut.load_bikes(self.db), owner, owner.config)
        self.assertIn("Eerst meer oordelen", found.note)
        self.assertEqual(found.changes, [])

    def test_best_margin_is_exact(self):
        cases = [([1.0, 2.0, 3.0], [False, True, True]), ([10.0, -3.0, 4.0, 4.0], [True, False, True, False]),
                 ([], []), ([30.0, 40.0], [False, False]), ([-5.0, -1.0], [True, True])]
        for gains, yes in cases:
            correct, margin = ut._best_margin(gains, yes, 5.0)
            lo, hi = ut.MARGIN_RANGE
            self.assertTrue(lo <= margin <= hi)
            self.assertEqual(correct, sum((g > margin) if y else (g <= margin) for g, y in zip(gains, yes)))
            brute = max(sum((g > m) if y else (g <= m) for g, y in zip(gains, yes))
                        for m in [lo, hi] + [g for g in gains if lo <= g <= hi]
                        + [(a + b) / 2 for a, b in zip(sorted(gains), sorted(gains)[1:]) if lo <= (a + b) / 2 <= hi])
            self.assertEqual(correct, brute, (gains, yes))
        self.assertEqual(ut._best_margin([1.0, 9.0], [False, True], 5.0), (2, 5.0))  # de huidige als die kan

    def test_search_finds_a_rule_that_fits_better(self):
        # Een eigenaar die nieuwere carbon fietsen een upgrade vindt: meer
        # fietsen dan de vaste set, met jaartallen en groepsets door elkaar.
        extra = []
        for i, (year, groupset, brake) in enumerate([(2022, "105", "hydraulische schijfremmen"),
                                                       (2020, "Tiagra", "velgremmen"), (2023, "Ultegra", "schijfremmen"),
                                                       (2009, "Ultegra", "velgremmen"), (2011, "Dura-Ace", "velgremmen"),
                                                       (2008, "105", "velgremmen"), (2019, "105", "velgremmen"),
                                                       (2012, "Ultegra", "velgremmen"), (2021, "Sora", "schijfremmen"),
                                                       (2010, "Dura-Ace", "velgremmen")]):
            extra.append(bike(f"x{i}", 500.0, f"Racefiets {year} {groupset}",
                              f"Carbon frame, Shimano {groupset}, {brake}. Bouwjaar {year}."))
        conn = db.connect(self.db)
        db.sync_listings(conn, "racefiets", BIKES + extra, self.now.isoformat())
        conn.close()
        owner, judge = self.judge()
        for b in ut.load_bikes(self.db):
            year = b.prepared.build.model_year
            if b.listing.item_id in ("groot", "frame", "weg") or year is None:
                continue
            self.label(b.listing.item_id, "ja" if year >= 2015 and b.prepared.build.frame_material == "carbon" else "nee")
        bikes = ut.load_bikes(self.db)
        found = ut.search(bikes, owner, owner.config)
        self.assertGreater(found.correct, found.before)
        self.assertEqual(found.judged, sum(1 for b in bikes if b.label in ("ja", "nee")))
        self.assertTrue(found.changes)
        # De voorgestelde regel doet echt wat hij belooft.
        self.assertEqual(ut.agreement(ut.assess_all(bikes, ut.make_judge(owner, found.config))).correct, found.correct)
        self.assertAlmostEqual(sum(found.config["weights"].values()), 1.0, places=6)


class OutputTest(BikesCase):
    def test_csv_for_excel(self):
        self.label("tcr", "ja")
        _, judge = self.judge()
        text = ut.csv_text(ut.assess_all(ut.load_bikes(self.db), judge), judge)
        self.assertTrue(text.startswith("﻿item_id;titel;prijs"))
        lines = text[1:].split("\r\n")
        rows = {line.split(";")[0]: line.split(";") for line in lines[1:] if line}
        header = lines[0].split(";")
        tcr = dict(zip(header, rows["tcr"]))
        self.assertEqual(tcr["jouw_oordeel"], "ja")
        self.assertEqual(tcr["oneens"], "ja")  # jij ja, de standaardregel nee
        self.assertEqual(tcr["bouwjaar"], "2016")
        self.assertIn(",", tcr["totaal"])  # komma als decimaalteken
        self.assertEqual(tcr["route"], "velrem")
        self.assertEqual(len(rows), len(ut.load_bikes(self.db)))
        gains = [float(dict(zip(header, r))["winst"].replace(",", ".")) for r in rows.values()]
        self.assertEqual(len(gains), len(rows))

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ut.main(["--db", self.db, "--mijn-fiets", self.intake]), 0)
        self.assertIn("Jouw fiets (Giant Defy Composite)", out.getvalue())
        self.assertIn("scoring_config.json (standaard)", out.getvalue())
        target = self.dir / "lijsten" / "uitdraai.csv"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ut.main(["uitdraai", "--db", self.db, "--mijn-fiets", self.intake, "--uit", str(target)]), 0)
        self.assertTrue(target.read_text(encoding="utf-8").startswith("﻿item_id;"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ut.main(["zoek", "--db", self.db, "--mijn-fiets", self.intake]), 0)
        self.assertIn("Eerst meer oordelen", out.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ut.main(["--db", str(self.dir / "nee.db")]), 1)
        self.assertFalse((self.dir / "nee.db").exists())

    def test_upgrade_cli_says_it_uses_the_saved_rule(self):
        ut.save_rule(self.db, {"upgrade": {"marge": 0}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            up.main(["--db", self.db, "--mijn-fiets", self.intake])
        self.assertIn("Jouw regel van /upgrade", out.getvalue())


class CacheTest(BikesCase):
    def test_a_new_rule_only_rescores_the_cached_racefietsen(self):
        cache = dashboard.LiveCache()
        base = cache.racebikes(self.db, self.intake)
        before = {r.listing.item_id: r.upgrade_ok for r in base.rows}
        ut.save_rule(self.db, {"upgrade": {"marge": -20, "onbekend": "gelijk"}})
        with mock.patch.object(rb, "build_base", side_effect=AssertionError("alles opnieuw")):
            again = cache.racebikes(self.db, self.intake)
        self.assertIs(again, base)
        after = {r.listing.item_id: r.upgrade_ok for r in again.rows}
        self.assertNotEqual(before, after)
        self.assertTrue(after["tcr"])
        self.assertEqual(up.config_margin(again.owner.config), -20)
        # en terug
        ut.reset_rule(self.db)
        self.assertEqual({r.listing.item_id: r.upgrade_ok for r in cache.racebikes(self.db, self.intake).rows}, before)

    def test_upgrade_bikes_come_from_the_cache(self):
        cache = dashboard.LiveCache()
        bikes = cache.upgrade_bikes(self.db, self.intake)
        self.assertEqual({b.listing.item_id for b in bikes}, {r.listing.item_id for r in cache.racebikes(self.db, self.intake).rows})
        self.label("tcr", "ja")
        self.assertEqual(next(b for b in cache.upgrade_bikes(self.db, self.intake) if b.listing.item_id == "tcr").label, "ja")


class ServerTest(BikesCase):
    track_connections = False

    def setUp(self):
        super().setUp()
        self.start(self.intake)

    def start(self, intake):
        self.httpd = dashboard.make_server(self.db, 0, intake_path=intake)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, fields=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        body = None
        if fields is not None:
            body = urllib.parse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, headers)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), data.decode("utf-8")

    def page_data(self):
        status, _, page = self.request("GET", ut.PATH)
        self.assertEqual(status, 200)
        return page, json.loads(re.search(r"<script type='application/json' id='data'>(.*?)</script>", page, re.S)
                                .group(1).replace("<\\/", "</"))

    def post(self, path, **fields):
        token = re.search(r"data-token='([^']+)'", self.request("GET", ut.PATH)[2]).group(1)
        status, _, text = self.request("POST", path, {"token": token, **fields})
        self.assertEqual(status, 200)
        return json.loads(text)

    def test_the_page(self):
        page, data = self.page_data()
        self.assertIn("<h1>Upgradetest</h1>", page)
        self.assertIn("aria-current=page>Upgrade</a>", page)  # in de balk bovenaan
        # alleen de categorie racefietsen, zoals /racefietsen: het losse frame niet
        self.assertEqual({b["id"] for b in data["bikes"]}, {"tcr", "emonda", "dura", "staal", "alu", "kaal", "groot"})
        self.assertEqual(set(data["s"]), {b["id"] for b in data["bikes"]})
        self.assertEqual(len(data["s"]["tcr"]), 9)
        self.assertEqual(data["own"]["tot"], 50.8)
        self.assertNotIn("groot", data["queue"])  # past niet
        self.assertEqual(data["saved"], "")
        self.assertIn("data-path='weights.frame'", page)
        self.assertIn("niveau 5: Shimano Ultegra", page)

    def test_judging_trying_saving_and_back(self):
        self.assertEqual(self.post(ut.LABEL_PATH, item_id="tcr", oordeel="ja")["lab"], "ja")
        self.assertIn("kies ja, nee", self.post(ut.LABEL_PATH, item_id="tcr", oordeel="misschien")["message"])
        self.assertTrue(self.post(ut.LABEL_PATH, item_id="onbekend", oordeel="ja")["error"])
        _, data = self.page_data()
        self.assertEqual(next(b for b in data["bikes"] if b["id"] == "tcr")["lab"], "ja")
        self.assertNotIn("tcr", data["queue"])
        rule = sc.load_config()
        rule["upgrade"]["marge"] = -20
        tried = self.post(ut.TRY_PATH, regel=json.dumps(rule))
        self.assertEqual(tried["s"]["tcr"][2], 1)
        self.assertIn("upgrade marge: 5 → -20", tried["changes"])
        self.assertEqual(ut.load_rule(self.db), (None, None))  # proef slaat niets op
        self.assertIn("niet te lezen", self.post(ut.TRY_PATH, regel="{kapot")["message"])
        # diep geneste haken: RecursionError in json, geen traceback (9 kB past nog in een formulier)
        self.assertIn("niet te lezen", self.post(ut.TRY_PATH, regel="[" * 3000)["message"])
        self.assertIn("tussen", self.post(ut.TRY_PATH, regel=json.dumps({"weights": {"frame": 99}}))["message"])
        saved = self.post(ut.RULE_PATH, actie="opslaan", regel=json.dumps(rule))
        self.assertIn("Opgeslagen", saved["message"])
        self.assertEqual(up.config_margin(ut.load_rule(self.db)[0]), -20)
        # /racefietsen rekent er meteen mee
        status, _, race = self.request("GET", rb.PATH)
        bikes = json.loads(re.search(r"<script type='application/json' id='bikes'>(.*?)</script>", race, re.S).group(1))
        self.assertTrue(next(b for b in bikes if b["id"] == "tcr")["uo"])
        back = self.post(ut.RULE_PATH, actie="standaard")
        self.assertIn("standaard", back["message"])
        self.assertEqual(ut.load_rule(self.db), (None, None))
        self.assertEqual(back["s"]["tcr"][2], 0)
        self.assertEqual(self.post(ut.LABEL_PATH, item_id="tcr", oordeel="")["message"], "Oordeel weggehaald.")

    def test_explain_and_search(self):
        info = self.post(ut.EXPLAIN_PATH, item_id="emonda")
        self.assertEqual(len(info["onderdelen"]), 5)
        self.assertIn("hydraulische schijfremmen", info["d"])
        self.assertEqual(info["img"], ["https://images.example/emonda.jpg"])
        rule = sc.load_config()
        rule["weights"]["brakes"] = 0
        self.assertNotEqual(self.post(ut.EXPLAIN_PATH, item_id="emonda", regel=json.dumps(rule))["winst"], info["winst"])
        self.assertTrue(self.post(ut.EXPLAIN_PATH, item_id="nee")["error"])
        found = self.post(ut.SEARCH_PATH, regel=json.dumps(sc.load_config()))
        self.assertIn("Eerst meer oordelen", found["note"])

    def test_csv_download(self):
        status, headers, text = self.request("GET", ut.CSV_PATH)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertTrue(text.startswith("\ufeffitem_id;titel"))

    def test_guards(self):
        status, _, text = self.request("POST", ut.LABEL_PATH, {"token": "fout", "item_id": "tcr", "oordeel": "ja"})
        self.assertEqual(json.loads(text)["reload"], True)
        conn = db.connect(self.db)
        try:
            self.assertEqual(db.list_upgrade_labels(conn), {})
        finally:
            conn.close()
        self.assertEqual(self.request("GET", ut.PATH, host="evil.example")[0], 403)
        self.assertEqual(self.request("POST", ut.TRY_PATH, {"regel": "x" * 20000})[0], 413)

    def test_without_an_own_bike(self):
        self.start(self.dir / "geen_fiets.md")
        page = self.request("GET", ut.PATH)[2]
        self.assertIn("Geen eigen fiets om mee te vergelijken", page)
        token = re.search(r"data-token='([^']+)'", page).group(1)
        answer = json.loads(self.request("POST", ut.LABEL_PATH, {"token": token, "item_id": "tcr", "oordeel": "ja"})[2])
        self.assertTrue(answer["error"])
        self.assertEqual(self.request("GET", ut.CSV_PATH)[0], 404)


if __name__ == "__main__":
    unittest.main()
