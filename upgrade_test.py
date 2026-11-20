"""De upgradetest: zelf bepalen wat een upgrade is (opdrachten/upgradetest.md).

De eigenaar, 05-10-2026: "ik wil graag dat je alles gaat uitdraaien en een
test maakt zodat ik zelf kan bepalen wat een upgrade is, nu zijn er fietsen
die duidelijk een upgrade zijn lager gewaardeerd dan mijn fiets".

Drie dingen:

1. **Oordelen.** Per fiets zegt de eigenaar of hij een upgrade is van zijn
   eigen fiets — los van prijs en maat, want dat zijn aparte poorten — ja,
   nee of twijfel (tabel `upgrade_label`, migratie 22). Op `/upgrade` in
   `dashboard.py --serve`.
2. **De regel.** Alles wat de kwaliteitsscore bepaalt (`scoring_config.json`:
   gewichten, materiaal, leeftijd, groepsets, remmen, wielen, extra's) plus
   de marge en wat "onbekend" betekent. De eigenaar past hem aan en ziet
   meteen hoeveel van zijn oordelen de regel goed heeft; `search()` zoekt de
   regel die het best past. Opgeslagen in `setting` (`upgrade_regel`); dan
   rekenen /racefietsen, het rapport, het overzicht en `upgrade.py` ermee
   (`up.apply_saved_rule()`). Zonder opgeslagen regel: scoring_config.json.
3. **De uitdraai.** Elke racefiets met de score per onderdeel, het verschil
   met de eigen fiets, de winst, het oordeel en waarom: op de pagina, als
   CSV en met `python upgrade_test.py uitdraai`.

"Beter dan jouw fiets" is hier de kwaliteitsvraag alleen: winst > marge.
Of hij ook binnen budget en maat valt (het oordeel op /racefietsen) staat
er los naast. Alleen lezen, behalve de oordelen en de regel; bieden doet de
eigenaar zelf.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import html
import io
import json
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import computers as pc
import crawl
import db
import marks as mr
import pages as pg
import racebikes as rb
import report
import scoring as sc
import upgrade as up
import util

LABELS = ("ja", "nee", "twijfel")
LABEL_TEXT = {"ja": "upgrade", "nee": "geen upgrade", "twijfel": "twijfel"}
DIMENSIONS = ("frame", "drivetrain", "brakes", "wheels", "extras")
DIMENSION_LABELS = {"frame": "frame", "drivetrain": "aandrijving", "brakes": "remmen", "wheels": "wielen",
                    "extras": "extra's"}
HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "lijsten" / "upgrade_uitdraai.csv"


def _flat(config, path=()) -> dict:
    if isinstance(config, dict):
        out = {}
        for key, value in config.items():
            out.update(_flat(value, path + (key,)))
        return out
    return {path: config}


def _show(value) -> str:
    if value is None:
        return "zoals de tekst zegt"
    if isinstance(value, float):
        return f"{value:g}".replace(".", ",")
    return str(value)


def rule_changes(config: dict, standard: Optional[dict] = None) -> list[str]:
    """Wat deze regel anders doet dan scoring_config.json, leesbaar."""
    standard = standard if standard is not None else up.default_config()
    mine, base = _flat(config), _flat(standard)
    return [f"{up.path_name(path)}: {_show(base.get(path))} → {_show(value)}"
            for path, value in mine.items() if path in base and base[path] != value]


# --- De eigen fiets onder een regel -----------------------------------------------


@dataclass(frozen=True)
class Judge:
    """De eigen fiets en wat er verder vastligt, onder één regel."""

    config: dict
    build: sc.Build
    quality: sc.QualityScore
    margin: float
    like: Optional[sc.Build]  # de eigen fiets als "onbekend = gelijk", anders None
    owner_has: frozenset
    budgets: Optional[up.Budgets]
    target_cm: Optional[float]
    label: str
    problem: str = ""


def make_judge(owner, config: dict, problem: str = "") -> Judge:
    """`owner`: report.OwnerContext. De eigen fiets opnieuw gescoord onder
    `config`; budget en doelmaat hangen niet van de regel af."""
    build = sc.owner_build(owner.bike.specs, owner.bike.label, config)
    like = build if up.config_unknown(config) == up.UNKNOWN_LIKE_OWN else None
    return Judge(config, build, sc.score_build(build, config), up.config_margin(config), like,
                 owner.owner_has, owner.budgets, owner.target_size_cm, owner.bike.label,
                 problem or (owner.valuation_problem or "" if owner.budgets is None else ""))


# --- De fietsen -------------------------------------------------------------------


@dataclass
class Bike:
    listing: crawl.Listing
    prepared: up.Prepared
    active: bool = True
    label: Optional[str] = None
    excluded: str = ""  # weggezet om een reden die blijft ("geen racefiets")
    own_year: bool = False


def _listings_by_id(conn: sqlite3.Connection, ids: Sequence[str]) -> list[crawl.Listing]:
    """Fietsen die je beoordeelde maar die niet meer te koop zijn: uit de
    database, zoals racebikes ze leest."""

    if not ids:
        return []
    conn.row_factory = sqlite3.Row
    site = db.read_listing_specs(conn, source=db.SITE_SPEC_SOURCE)
    found = []
    for start in range(0, len(ids), 500):
        chunk = list(ids[start:start + 500])
        rows = conn.execute(rb.SELECT + f" AND item_id IN ({','.join('?' * len(chunk))})",
                            (f"%/{rb.CATEGORY}/%", *chunk)).fetchall()
        found += [crawl.listing_from_row(r, site, {}) for r in rows]
    return found


def load_bikes(db_path, listings: Optional[Sequence[crawl.Listing]] = None,
               prepared: Optional[dict] = None) -> list[Bike]:
    """De actieve racefietsen (`listings`, anders racebikes.load_listings())
    plus de fietsen met een oordeel die niet meer te koop zijn, met het
    bouwjaar dat de eigenaar zelf invulde en zijn oordeel. `prepared`: een
    dict om de gelezen tekst in te onthouden ({(item_id, jaar): Prepared},
    LiveCache), zolang de database niet verandert."""

    if listings is None:
        listings, _, _ = rb.load_listings(db_path)
    labels, links, marks = {}, {}, []
    inactive: list = []
    if db_path and Path(db_path).exists():
        conn = db.connect_readonly(db_path)
        try:
            labels = db.list_upgrade_labels(conn)
            links = db.list_bike_links(conn)
            marks = db.list_marks(conn)
            active_ids = {l.item_id for l in listings}
            inactive = _listings_by_id(conn, [i for i in labels if i not in active_ids])
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    excluded = {m["item_id"]: m["reason"] for m in marks
                if m["mark"] == mr.DISMISSED and m.get("reason") in mr.PERMANENT_REASONS}
    bikes = []
    cache = prepared if prepared is not None else {}
    for listing, active in [(l, True) for l in listings] + [(l, False) for l in inactive]:
        year = (links.get(listing.item_id) or {}).get("year")
        key = (listing.item_id, year)
        if key not in cache:
            cache[key] = up.prepare_candidate(listing, year)
        bikes.append(Bike(listing, cache[key], active,
                          (labels.get(listing.item_id) or {}).get("label"),
                          excluded.get(listing.item_id, ""), year is not None))
    return bikes


# --- Beoordelen onder een regel -------------------------------------------------


@dataclass(frozen=True)
class Assessment:
    bike: Bike
    scored: up.Scored
    gain: float
    better: bool  # winst > marge: de kwaliteitsvraag van de test
    verdict: bool  # upgrade zoals /racefietsen hem noemt: ook maat, prijs en budget
    why: str
    size: str


def assess(bike: Bike, judge: Judge) -> Assessment:
    l = bike.listing
    target = judge.target_cm
    size, reject = (up.precheck(l, target) if target is not None else (up.SIZE_UNKNOWN, None))
    scored = up.finish_candidate(
        bike.prepared, config=judge.config, owner_wheels=up.owner_wheels(judge.build),
        owner_already_has=judge.owner_has, like_owner=judge.like,
        notes=(up.SIZE_UNKNOWN_NOTE,) if size == up.SIZE_UNKNOWN else ())
    gain = scored.quality.total - judge.quality.total
    better = gain > judge.margin
    if reject is not None:
        verdict, why = False, reject
    elif judge.budgets is None or target is None:
        verdict, why = False, judge.problem or "geen budget of doelmaat"
    else:
        outcome = up.decide(l, scored, size=size, baseline=judge.quality.total, margin=judge.margin,
                            budgets=judge.budgets)
        if isinstance(outcome, up.Candidate):
            verdict = True
            why = (f"+{outcome.gain:.0f} punten ({outcome.quality.total:.0f} tegen {judge.quality.total:.0f}), "
                   f"€{outcome.effective.amount:.0f} binnen {outcome.budget.route}budget €{outcome.budget.amount:.0f}")
            if up.needs_year(scored, judge.config):
                verdict, why = False, up.unknown_year_note(why)
        else:
            verdict, why = False, outcome.reason
    return Assessment(bike, scored, gain, better, verdict, why, size)


def assess_all(bikes: Sequence[Bike], judge: Judge) -> list[Assessment]:
    return [assess(b, judge) for b in bikes]


# --- De uitslag -------------------------------------------------------------------


@dataclass
class Agreement:
    """Hoe de regel het doet op de oordelen van de eigenaar (ja/nee; twijfel
    telt niet mee)."""

    both_yes: list = field(default_factory=list)  # jij ja, regel ja
    both_no: list = field(default_factory=list)
    missed: list = field(default_factory=list)  # jij ja, regel nee: te laag gewaardeerd
    wrong: list = field(default_factory=list)  # jij nee, regel ja: te hoog gewaardeerd
    unsure: int = 0

    @property
    def judged(self) -> int:
        return len(self.both_yes) + len(self.both_no) + len(self.missed) + len(self.wrong)

    @property
    def correct(self) -> int:
        return len(self.both_yes) + len(self.both_no)

    def text(self) -> str:
        if not self.judged:
            return "Nog geen oordelen (ja of nee)."
        return (f"De regel heeft {self.correct} van je {self.judged} oordelen goed "
                f"({self.correct / self.judged:.0%}): {len(self.missed)} keer zei jij upgrade en de regel niet, "
                f"{len(self.wrong)} keer andersom.")


def agreement(assessments: Sequence[Assessment]) -> Agreement:
    out = Agreement()
    for a in assessments:
        label = a.bike.label
        if label == "twijfel":
            out.unsure += 1
        elif label == "ja":
            (out.both_yes if a.better else out.missed).append(a)
        elif label == "nee":
            (out.wrong if a.better else out.both_no).append(a)
    # Het grootste verschil eerst: daar zit de regel het verst naast.
    out.missed.sort(key=lambda a: a.gain)
    out.wrong.sort(key=lambda a: -a.gain)
    return out


# --- De volgorde van de test ------------------------------------------------------

# Winst-banden waarover de test zijn fietsen verdeelt: anders zag de
# eigenaar alleen de fietsen die de score al hoog had, en juist de laag
# gewaardeerde ("duidelijk een upgrade, lager dan mijn fiets") kwamen niet langs.
QUEUE_BANDS = (-10.0, -3.0, 3.0, 10.0)


def _stable(item_id: str) -> str:
    return hashlib.sha1(item_id.encode("utf-8")).hexdigest()


def queue(assessments: Sequence[Assessment]) -> list[str]:
    """De fietsen om te beoordelen, in een vaste volgorde: alleen actieve,
    zonder oordeel, niet weggezet als geen racefiets en niet buiten de maat
    of buiten racefietsen; om en om uit elke winstband (zie QUEUE_BANDS),
    binnen een band eerst de fietsen waarvan bouwjaar en groepset bekend
    zijn (daar is een oordeel het meest waard), verder vast door elkaar."""
    bands: list[list] = [[] for _ in range(len(QUEUE_BANDS) + 1)]
    for a in assessments:
        b = a.bike
        if not b.active or b.label or b.excluded or a.size == up.SIZE_WRONG:
            continue
        category = crawl.category_from_url(b.listing.url)
        if category is not None and category != crawl.ROAD_BIKE_CATEGORY:
            continue
        band = sum(1 for edge in QUEUE_BANDS if a.gain > edge)
        known = b.prepared.build.model_year is not None and b.prepared.build.groupset_tier is not None
        bands[band].append((not known, _stable(b.listing.item_id), b.listing.item_id))
    for band in bands:
        band.sort()
    order = []
    while any(bands):
        for band in reversed(bands):  # de hoogste band eerst: die is het makkelijkst te beginnen
            if band:
                order.append(band.pop(0)[2])
    return order


# --- Zoeken naar een regel die past ----------------------------------------------

# Wat search() probeert naast de gewichten en de marge. Bewust weinig: met
# een handvol oordelen past anders elke regel, en dan zegt het niets.
SEARCH_DRIVETRAIN_DECAY = (0.0, 0.02, 0.04)
SEARCH_FRAME_DECAY = (0.015, 0.03)
MARGIN_RANGE = (0.0, 25.0)
MIN_JUDGED = 10
MIN_EACH = 3


@dataclass
class Suggestion:
    config: dict
    correct: int
    judged: int
    before: int
    changes: list
    note: str = ""


def _variants(config: dict) -> list[tuple[dict, int]]:
    """(regel, aantal veranderde opties) per combinatie die search() probeert."""
    wheels = config["wheels"]
    own_options = [wheels.get("eigen_wielen")]
    if wheels.get("carbon_naamloos") not in own_options:
        own_options.append(wheels.get("carbon_naamloos"))
    unknown_options = [up.config_unknown(config)] + [m for m in up.UNKNOWN_MODES if m != up.config_unknown(config)]
    drivetrain = [config["drivetrain"].get("age_decay_per_year", 0)]
    drivetrain += [d for d in SEARCH_DRIVETRAIN_DECAY if d != drivetrain[0]]
    frame = [config["frame"]["age_decay_per_year"]] + [d for d in SEARCH_FRAME_DECAY
                                                       if d != config["frame"]["age_decay_per_year"]]
    out = []
    for i, unknown in enumerate(unknown_options):
        for j, d_decay in enumerate(drivetrain):
            for k, f_decay in enumerate(frame):
                for m, own in enumerate(own_options):
                    variant = copy.deepcopy(config)
                    variant.setdefault("upgrade", {})["onbekend"] = unknown
                    variant["drivetrain"]["age_decay_per_year"] = d_decay
                    variant["frame"]["age_decay_per_year"] = f_decay
                    variant["wheels"]["eigen_wielen"] = own
                    out.append((variant, (i > 0) + (j > 0) + (k > 0) + (m > 0)))
    return out


def _diffs(bikes: Sequence[Bike], judge: Judge) -> list[list[float]]:
    """Per beoordeelde fiets het verschil met de eigen fiets per onderdeel."""
    own = [judge.quality.dimensions[d].score for d in DIMENSIONS]
    out = []
    for b in bikes:
        scored = assess(b, judge).scored
        out.append([scored.quality.dimensions[d].score - o for d, o in zip(DIMENSIONS, own)])
    return out


def _weight_grid(step: int):
    """Alle gewichten in stappen van 1/step die samen 1 zijn."""
    for a in range(step + 1):
        for b in range(step + 1 - a):
            for c in range(step + 1 - a - b):
                for d in range(step + 1 - a - b - c):
                    yield (a / step, b / step, c / step, d / step, (step - a - b - c - d) / step)


def _cut_in(lo: float, upper: float, high: float, current: float) -> Optional[float]:
    """Een marge m met lo <= m < upper en m <= high, zo dicht mogelijk bij
    `current` maar niet pal op een winst: daar zou hij na afronden aan de
    verkeerde kant kunnen vallen. None als er geen is."""
    top = min(upper, high)
    if lo > top or lo >= upper:
        return None
    if lo <= current <= high and current < upper and (current > lo or lo == -math.inf):
        return current
    room = min(0.5, (top - lo) / 2) if math.isfinite(top - lo) else 0.5
    want = lo + room if current <= lo else (top - room if top == upper else top)
    for cut in (round(want, 1), want):
        if lo <= cut < upper and cut <= high:
            return cut
    return lo


def _best_margin(gains: list, yes: list, current: float) -> tuple[int, float]:
    """(aantal goed, marge) met de beste marge binnen MARGIN_RANGE: ja moet
    boven de marge, nee erop of eronder. Eén keer sorteren en dan lopen: met
    de marge tussen de k-de en de (k+1)-de winst is het aantal goed de ja's
    erboven plus de nee's eronder. Bij gelijk de marge die het dichtst bij
    de huidige ligt."""
    low, high = MARGIN_RANGE
    pairs = sorted(zip(gains, yes))
    yes_above, no_below = sum(yes), 0
    best_key, best_cut = None, min(max(current, low), high)
    for k in range(len(pairs) + 1):
        lower = pairs[k - 1][0] if k else -math.inf
        upper = pairs[k][0] if k < len(pairs) else math.inf
        cut = _cut_in(max(lower, low), upper, high, current)
        if cut is not None:
            key = (yes_above + no_below, -abs(cut - current))
            if best_key is None or key > best_key:
                best_key, best_cut = key, cut
        if k < len(pairs):
            if pairs[k][1]:
                yes_above -= 1
            else:
                no_below += 1
    if best_key is None:
        return sum((g > best_cut) if y else (g <= best_cut) for g, y in zip(gains, yes)), best_cut
    return best_key[0], best_cut


def search(bikes: Sequence[Bike], owner, config: dict) -> Suggestion:
    """De regel die het best past bij de oordelen ja/nee: gewichten (stappen
    van 0,1, daarna 0,05 rond de beste), de marge, en een paar opties
    (_variants()). Bij gelijk aantal goed wint wat het minst verandert aan
    `config`: met weinig oordelen passen veel regels even goed. Zet niets
    vast; de eigenaar kijkt en slaat op."""
    judged = [b for b in bikes if b.label in ("ja", "nee")]
    yes = [b.label == "ja" for b in judged]
    current = up.clean_rule(config, up.default_config())
    before = agreement(assess_all(judged, make_judge(owner, current))).correct
    if len(judged) < MIN_JUDGED or sum(yes) < MIN_EACH or len(yes) - sum(yes) < MIN_EACH:
        return Suggestion(current, before, len(judged), before, [],
                          f"Eerst meer oordelen: minstens {MIN_JUDGED}, waarvan {MIN_EACH} ja en {MIN_EACH} nee "
                          f"(nu {sum(yes)} ja en {len(yes) - sum(yes)} nee).")
    total = sum(current["weights"][d] for d in DIMENSIONS)
    w_now = [current["weights"][d] / total for d in DIMENSIONS]
    margin_now = up.config_margin(current)

    def run(diffs, grid, changed):
        best = None
        for w in grid:
            w0, w1, w2, w3, w4 = w
            gains = [w0 * a + w1 * b + w2 * c + w3 * d + w4 * e for a, b, c, d, e in diffs]
            correct, margin = _best_margin(gains, yes, margin_now)
            distance = sum(abs(a - b) for a, b in zip(w, w_now)) + 0.15 * changed + 0.01 * abs(margin - margin_now)
            key = (correct, -distance)
            if best is None or key > best[0]:
                best = (key, w, margin)
        return best

    found = []
    for variant, changed in _variants(current):
        diffs = _diffs(judged, make_judge(owner, variant))
        best = run(diffs, list(_weight_grid(10)) + [tuple(w_now)], changed)
        found.append((best[0], variant, changed, diffs, best))
    found.sort(key=lambda f: f[0], reverse=True)
    _, variant, changed, diffs, (key, w, margin) = found[0]
    # Fijner rond de beste gewichten: ±0,1 in stappen van 0,05.
    near = [g for g in _weight_grid(20) if all(abs(a - b) <= 0.1 + 1e-9 for a, b in zip(g, w))]
    finer = run(diffs, near, changed)
    if finer[0] > key:
        key, w, margin = finer
    rule = copy.deepcopy(variant)
    rule["weights"] = {d: round(x, 2) for d, x in zip(DIMENSIONS, w)}
    # Zo rond mogelijk, maar alleen als dat niets verandert: de beste marge
    # zit soms in een gat van een paar honderdsten tussen twee fietsen.
    gains = [sum(wi * di for wi, di in zip(w, row)) for row in diffs]
    count = sum((g > margin) if y else (g <= margin) for g, y in zip(gains, yes))
    rule.setdefault("upgrade", {})["marge"] = next(
        (m for m in (round(margin, 1), round(margin, 2), round(margin, 3))
         if sum((g > m) if y else (g <= m) for g, y in zip(gains, yes)) == count), margin)
    rule = up.clean_rule(rule, up.default_config())
    correct = agreement(assess_all(judged, make_judge(owner, rule))).correct
    note = ""
    if len(judged) < 30:
        note = f"Op {len(judged)} oordelen: een eerste schatting. Hoe meer je beoordeelt, hoe betrouwbaarder."
    return Suggestion(rule, correct, len(judged), before, rule_changes(rule, current), note)


# --- Uitleg en uitdraai ------------------------------------------------------------


def dims(quality: sc.QualityScore) -> list[float]:
    return [round(quality.dimensions[d].score, 1) for d in DIMENSIONS]


def year_source(bike: Bike) -> str:
    if bike.own_year:
        return "jij"
    for reason in bike.prepared.reasons:
        if reason.endswith("uit de titel"):
            return "titel"
    return "tekst" if bike.prepared.build.model_year is not None else ""


def explain(a: Assessment, judge: Judge) -> dict:
    """Per onderdeel de score van de fiets en van de eigen fiets met de
    redenen: waarom de regel zegt wat hij zegt."""
    weights = judge.config["weights"]
    total_weight = sum(weights[d] for d in DIMENSIONS)
    parts = []
    for d in DIMENSIONS:
        mine, own = a.scored.quality.dimensions[d], judge.quality.dimensions[d]
        parts.append({
            "naam": DIMENSION_LABELS[d], "fiets": round(mine.score, 1), "eigen": round(own.score, 1),
            "gewicht": round(weights[d] / total_weight, 3),
            "punten": round((mine.score - own.score) * weights[d] / total_weight, 1),
            "waarom": " · ".join(mine.reasons), "eigen_waarom": " · ".join(own.reasons)})
    return {"id": a.bike.listing.item_id, "totaal": round(a.scored.quality.total, 1),
            "eigen": round(judge.quality.total, 1), "winst": round(a.gain, 1), "marge": judge.margin,
            "beter": a.better, "oordeel": a.verdict, "waarom": a.why, "redenen": list(a.scored.reasons),
            "onderdelen": parts}


CSV_COLUMNS = (
    "item_id", "titel", "prijs", "prijssoort", "effectief", "framemaat", "maat", "route", "bouwjaar",
    "bouwjaar_bron", "materiaal", "groepset", "versnellingen", "remmen", "wielen",
    "frame", "aandrijving", "remscore", "wielscore", "extras",
    "verschil_frame", "verschil_aandrijving", "verschil_remmen", "verschil_wielen", "verschil_extras",
    "totaal", "eigen_fiets", "winst", "marge", "beter_dan_jouw_fiets", "upgrade_op_racefietsen", "waarom",
    "jouw_oordeel", "oneens", "te_koop", "url", "onderbouwing")


def _nl(value, decimals: int = 1) -> str:
    if value is None:
        return ""
    return f"{value:.{decimals}f}".replace(".", ",")


def csv_text(assessments: Sequence[Assessment], judge: Judge) -> str:
    """De uitdraai als CSV voor Excel: puntkomma's, komma als decimaalteken,
    met een BOM zodat é en € goed aankomen. Hoogste winst eerst."""

    own = dims(judge.quality)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for a in sorted(assessments, key=lambda a: (-a.gain, a.bike.listing.item_id)):
        l, build = a.bike.listing, a.bike.prepared.build
        mine = dims(a.scored.quality)
        effective = up.effective_price(l).amount
        label = a.bike.label or ""
        disagree = ("ja" if (label == "ja") != a.better else "nee") if label in ("ja", "nee") else ""
        writer.writerow([
            l.item_id, l.title, _nl(l.price_eur, 0), pc.price_kind(l), _nl(effective, 0), l.frame_height, a.size,
            a.scored.route, build.model_year or "", year_source(a.bike), build.frame_material or "",
            l.groupset or "", build.speeds or "", build.brake_type or "",
            ("merk-" if build.wheel_branded else "") + (build.wheel_material or ""),
            *[_nl(x) for x in mine], *[_nl(m - o) for m, o in zip(mine, own)],
            _nl(a.scored.quality.total), _nl(judge.quality.total), _nl(a.gain), _nl(judge.margin),
            "ja" if a.better else "nee", "ja" if a.verdict else "nee", a.why, label, disagree,
            "ja" if a.bike.active else "nee", l.url,
            " | ".join(f"{DIMENSION_LABELS[d]}: {' · '.join(a.scored.quality.dimensions[d].reasons)}"
                       for d in DIMENSIONS) + " | " + " · ".join(a.scored.reasons)])
    return "﻿" + buffer.getvalue()


# --- De pagina /upgrade (dashboard.py --serve) -------------------------------------

PATH = pg.UPGRADE_PATH
LABEL_PATH = PATH + "/oordeel"
TRY_PATH = PATH + "/proef"
RULE_PATH = PATH + "/regel"
SEARCH_PATH = PATH + "/zoek"
EXPLAIN_PATH = PATH + "/uitleg"
CSV_PATH = PATH + "/uitdraai.csv"
POST_PATHS = (LABEL_PATH, TRY_PATH, RULE_PATH, SEARCH_PATH, EXPLAIN_PATH)
TEXT_CHARS = 1500  # zoveel van de omschrijving bij de testkaart


def _tier_names() -> dict:
    """{niveau: "Shimano Dura-Ace, SRAM Red, ..."} uit GROUPSET_CATALOG."""
    names: dict = {}
    for brand, name, _, tier, _ in crawl.GROUPSET_CATALOG:
        names.setdefault(str(tier), []).append(f"{brand} {name}")
    return {tier: ", ".join(found) for tier, found in names.items()}


# De knoppen van de regel, per groep: (pad, wat erbij staat, soort). Soort
# "pct": de waarde ×100 in het veld (leeftijd per jaar 0,015 → 1,5 %).
def form_groups(config: dict) -> list:
    tiers = _tier_names()
    groups = [
        ("Upgrade", "Wanneer heet een fiets beter: zijn score min die van jouw fiets moet boven de marge liggen.", [
            (("upgrade", "marge"), "marge in punten", "num"),
            (("upgrade", "onbekend"), "wat de advertentie niet zegt telt als", "select"),
        ]),
        ("Gewichten", "Hoe zwaar elk onderdeel telt. Het gaat om de verhouding; ze hoeven niet op te tellen tot 1.",
         [(("weights", d), DIMENSION_LABELS[d], "num") for d in DIMENSIONS]),
    ]
    frame = [(("frame", "material_score", m), m.replace("_", " "), "num") for m in config["frame"]["material_score"]]
    frame += [(("frame", "material_score_unknown"), "materiaal onbekend", "num")]
    frame += [(("frame", "tier_multiplier", c), f"frameklasse {c} (×)", "num") for c in config["frame"]["tier_multiplier"]]
    frame += [(("frame", "tier_multiplier_unknown"), "frameklasse onbekend (×)", "num"),
              (("frame", "age_decay_per_year"), "minder per jaar oud (%)", "pct"),
              (("frame", "age_decay_max"), "hooguit minder (%)", "pct")]
    groups.append(("Frame", "Materiaal × klasse × leeftijd. Bij advertenties is de frameklasse nooit bekend; jouw "
                            "fiets is endurance.", frame))
    drive = [(("drivetrain", "tier_score", t), f"niveau {t}: {tiers.get(t, '')}", "num")
             for t in config["drivetrain"]["tier_score"]]
    drive += [(("drivetrain", "tier_score_unknown"), "groepset onbekend", "num"),
              (("drivetrain", "electronic_bonus"), "elektronisch schakelen (+)", "num"),
              (("drivetrain", "speeds_bonus_per_speed_above_10"), "per versnelling boven 10 (+)", "num"),
              (("drivetrain", "age_decay_per_year"), "minder per jaar oud (%)", "pct"),
              (("drivetrain", "age_decay_max"), "hooguit minder (%)", "pct")]
    groups.append(("Aandrijving", "Het groepsetniveau zegt niets over de generatie (Ultegra 10-speed uit 2010 of "
                                  "12-speed uit 2022); leeftijd hier aanzetten laat het bouwjaar dat doen.", drive))
    groups.append(("Remmen", "", [(("brakes", "score", b), b, "num") for b in config["brakes"]["score"]]
                   + [(("brakes", "score_unknown"), "remtype onbekend", "num")]))
    wheels = [(("wheels", k), up.path_name((k,)), "num") for k in config["wheels"] if k != "eigen_wielen"]
    wheels.append((("wheels", "eigen_wielen"), "jouw eigen wielen (leeg = zoals de tekst ze leest)", "num"))
    groups.append(("Wielen", "Jouw CSC-set telt zonder eigen getal als merk-carbon, omdat CSC in de lijst met "
                             "wielmerken staat. Bij een velremfiets verhuist hij mee.", wheels))
    groups.append(("Extra's", "Opgeteld, tot het maximum.",
                   [(("extras", k), up.path_name((k,)), "pct" if k == "computer_owned_discount" else "num")
                    for k in config["extras"]]))
    return groups


def _get(config: dict, path: tuple):
    node = config
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def form_html(config: dict) -> str:
    parts = []
    for title, explain_text, fields in form_groups(config):
        rows = []
        for path, label, kind in fields:
            value = _get(config, path)
            name = ".".join(path)
            if kind == "select":
                options = "".join(
                    f"<option value='{m}'{' selected' if value == m else ''}>"
                    f"{'een vast getal (neutraal)' if m == up.UNKNOWN_NEUTRAL else 'hetzelfde als jouw fiets'}</option>"
                    for m in up.UNKNOWN_MODES)
                field_html = f"<select data-path='{name}'>{options}</select>"
            else:
                shown = "" if value is None else (value * 100 if kind == "pct" else value)
                shown = f"{shown:g}" if isinstance(shown, float) else str(shown)
                field_html = (f"<input type='number' step='any' data-path='{name}' data-kind='{kind}' "
                              f"value='{html.escape(shown, quote=True)}'>")
            wide = " wide" if kind == "select" else ""
            rows.append(f"<label class='field{wide}'><span>{html.escape(label)}</span>{field_html}</label>")
        parts.append(f"<fieldset><legend>{html.escape(title)}</legend>"
                     + (f"<p class='explain'>{html.escape(explain_text)}</p>" if explain_text else "")
                     + f"<div class='fields'>{''.join(rows)}</div></fieldset>")
    return "".join(parts)


def scores_json(assessments: Sequence[Assessment]) -> dict:
    """{id: [totaal, winst, beter, upgrade op /racefietsen, 5× onderdeel]} —
    kort, want het zijn er duizenden en het gaat bij elke proef heen en weer."""
    return {a.bike.listing.item_id: [round(a.scored.quality.total, 1), round(a.gain, 1), int(a.better),
                                     int(a.verdict), *dims(a.scored.quality)]
            for a in assessments}


def own_json(judge: Judge) -> dict:
    return {"tot": round(judge.quality.total, 1), "dims": dims(judge.quality),
            "why": [" · ".join(judge.quality.dimensions[d].reasons) for d in DIMENSIONS],
            "margin": judge.margin, "unknown": up.config_unknown(judge.config)}


def bikes_json(bikes: Sequence[Bike]) -> list:

    out = []
    for b in bikes:
        l = b.listing
        out.append({"id": l.item_id, "t": l.title, "u": l.url, "img": (l.image_urls or "").split()[:1],
                    "p": l.price_eur, "pk": pc.price_kind(l),
                    "sp": rb.specs_line(l, b.prepared.build.model_year if b.own_year else None),
                    "yr": b.prepared.build.model_year, "ys": year_source(b), "act": b.active,
                    "lab": b.label or "", "ex": b.excluded})
    return out


def rule_state(judge: Judge, assessments: Sequence[Assessment]) -> dict:
    """Wat de pagina na elke proef bijwerkt."""
    return {"s": scores_json(assessments), "own": own_json(judge), "changes": rule_changes(judge.config),
            "rule": judge.config}


def _page_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")


def render(owner, problem: str, bikes: Sequence[Bike], saved_at: Optional[str], token: str = "",
           message: str = "") -> str:
    notices = f"<div class='banner' role='status'>{html.escape(message)}</div>" if message else ""
    head = ("<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Upgradetest</title><style>{pg.CSS}{pg.SITE_CSS}{CSS}</style></head><body>"
            f"<main data-token='{html.escape(token, quote=True)}'>{pg.site_nav(PATH) if token else ''}"
            "<h1>Upgradetest</h1>")
    if owner is None:
        return (head + notices + f"<div class='banner'>Geen eigen fiets om mee te vergelijken: "
                f"{html.escape(problem or 'mijn_fiets.md ontbreekt')}</div></main></body></html>")
    judge = make_judge(owner, owner.config, problem)
    assessments = assess_all(bikes, judge)
    if not any(b.active for b in bikes):
        notices += ("<div class='banner'>Nog geen racefietsen in de database. Draai eerst een ronde: "
                    "<code>python koopjes.py run overdag</code>.</div>")
    data = {"bikes": bikes_json(bikes), **rule_state(judge, assessments), "std": up.default_config(),
            "saved": saved_at or "", "queue": queue(assessments), "label": judge.label,
            "dimnames": [DIMENSION_LABELS[d] for d in DIMENSIONS], "minJudged": MIN_JUDGED,
            "paths": {"label": LABEL_PATH, "try": TRY_PATH, "rule": RULE_PATH, "search": SEARCH_PATH,
                      "explain": EXPLAIN_PATH}}
    rule_text = (f"jouw regel van {html.escape(util.local_time(saved_at)[:10])}" if saved_at
                 else "de standaard (scoring_config.json)")
    return (
        head
        + f"<div class='meta'>Jouw fiets: <strong>{html.escape(judge.label)}</strong> · "
          f"<span id='ownscore'></span> · regel: <span id='rulename'>{rule_text}</span></div>{notices}"
        + "<nav class='tabs' id='tabs'>"
          "<button data-panel='test' class='active'>Test</button>"
          "<button data-panel='uitslag'>Uitslag <span id='agreecount'></span></button>"
          "<button data-panel='regel'>Jouw regel</button>"
          "<button data-panel='uitdraai'>Uitdraai</button></nav>"
        + "<section class='panel' id='p-test'>"
          "<p class='explain'>Zeg per fiets of hij een <strong>upgrade</strong> is van jouw fiets — <em>los van prijs "
          "en maat</em>, die komen er apart bij. De score van de regel staat er pas na je antwoord bij, zodat hij je "
          "niet stuurt. De fietsen komen uit het hele scorebereik, ook de laag gewaardeerde. Toetsen: <kbd>j</kbd> ja, "
          "<kbd>n</kbd> nee, <kbd>t</kbd> twijfel, <kbd>s</kbd> overslaan, <kbd>u</kbd> vorige ongedaan.</p>"
          "<div class='progress' id='progress'></div>"
          "<div id='card' class='testcard'></div>"
          "<div class='answer'><button data-answer='ja' class='yes'>Ja, upgrade <kbd>j</kbd></button>"
          "<button data-answer='nee' class='no'>Nee <kbd>n</kbd></button>"
          "<button data-answer='twijfel' class='quiet'>Twijfel <kbd>t</kbd></button>"
          "<button data-answer='skip' class='quiet'>Overslaan <kbd>s</kbd></button>"
          "<button data-answer='undo' class='quiet'>Vorige ongedaan <kbd>u</kbd></button></div>"
          "<label class='peek'><input type='checkbox' id='peek'> score al vóór mijn antwoord tonen</label>"
          "<div id='last' class='last'></div></section>"
        + "<section class='panel' id='p-uitslag' hidden><div id='agree'></div></section>"
        + "<section class='panel' id='p-regel' hidden>"
          "<p class='explain'>Alles wat de score bepaalt. Elke wijziging rekent meteen door op je oordelen en op de "
          "fietsen van nu; pas <strong>Opslaan</strong> laat /racefietsen, het rapport en het overzicht ermee rekenen. "
          "<strong>Zoek</strong> probeert gewichten, marge en een paar opties en stelt voor wat het best bij je "
          "oordelen past (minstens 10, ja én nee).</p>"
          "<div class='rulebar'><button id='save'>Opslaan als mijn regel</button>"
          "<button id='search' class='quiet'>Zoek de regel die het best bij mijn oordelen past</button>"
          "<button id='standard' class='quiet'>Terug naar de standaard</button></div>"
          "<div id='rulestatus' class='rulestatus'></div><div id='found'></div><ul id='changes' class='changelist'></ul>"
          f"<form id='ruleform' autocomplete='off' onsubmit='return false'>{form_html(judge.config)}</form></section>"
        + "<section class='panel' id='p-uitdraai' hidden>"
          "<div class='filters'><select id='show' aria-label='Welke fietsen'>"
          "<option value='te koop'>Te koop</option><option value='beoordeeld'>Beoordeeld</option>"
          "<option value='oneens'>Oneens met de regel</option><option value='beter'>Beter dan jouw fiets</option>"
          "<option value='upgrade'>Upgrade op /racefietsen</option><option value='alles'>Alles</option></select>"
          "<input type='search' id='q' placeholder='Zoek in titel en specs' aria-label='Zoeken'>"
          f"<a href='{CSV_PATH}' download>Alles als CSV (Excel)</a><span class='muted' id='outcount'></span></div>"
          "<div class='table-wrap'><table id='out'><thead></thead><tbody></tbody></table></div>"
          "<div id='outmore'></div></section>"
        + f"<script type='application/json' id='data'>{_page_json(data)}</script>"
        + f"</main><div id='toast' role='status' hidden></div><script>{JS}</script></body></html>")


def _form_rule(form: dict) -> dict:
    raw = form.get("regel", "")
    try:
        data = json.loads(raw) if raw else None
    except (ValueError, RecursionError):  # diep geneste haken geven RecursionError
        raise up.RuleError("de regel was niet te lezen") from None
    return up.clean_rule(data, up.default_config())


def try_rule(owner, bikes: Sequence[Bike], form: dict) -> dict:
    """POST /upgrade/proef: de regel uit het formulier doorrekenen, niets opslaan."""
    try:
        rule = _form_rule(form)
    except up.RuleError as exc:
        return {"message": f"Niet doorgerekend: {exc}.", "error": True}
    judge = make_judge(owner, rule)
    return rule_state(judge, assess_all(bikes, judge))


def rule_action(db_path, owner, bikes: Sequence[Bike], form: dict) -> dict:
    """POST /upgrade/regel: opslaan (actie=opslaan) of terug naar de standaard."""
    if form.get("actie") == "standaard":
        up.reset_rule(db_path)
        rule, message, saved = up.default_config(), "Terug naar de standaard (scoring_config.json).", ""
    else:
        try:
            rule = up.save_rule(db_path, _form_rule(form))
        except up.RuleError as exc:
            return {"message": f"Niet opgeslagen: {exc}.", "error": True}
        message = "Opgeslagen: /racefietsen, het rapport en het overzicht rekenen nu met jouw regel."
        saved = up.load_rule(db_path)[1] or ""
    judge = make_judge(owner, rule)
    return {"message": message, "saved": saved, **rule_state(judge, assess_all(bikes, judge))}


def search_action(owner, bikes: Sequence[Bike], form: dict) -> dict:
    try:
        rule = _form_rule(form)
    except up.RuleError as exc:
        return {"message": f"Niet gezocht: {exc}.", "error": True}
    found = search(bikes, owner, rule)
    return {"rule": found.config, "correct": found.correct, "judged": found.judged, "before": found.before,
            "changes": found.changes, "note": found.note}


def explain_action(owner, bikes: Sequence[Bike], form: dict) -> dict:
    """POST /upgrade/uitleg: één fiets onder de regel uit het formulier (of de
    opgeslagen), met de omschrijving voor de testkaart."""
    item_id = form.get("item_id", "")
    found = next((b for b in bikes if b.listing.item_id == item_id), None)
    if found is None:
        return {"message": "Deze fiets staat er niet (meer) bij.", "error": True}
    try:
        rule = _form_rule(form) if form.get("regel") else owner.config
    except up.RuleError as exc:
        return {"message": f"Niet doorgerekend: {exc}.", "error": True}
    judge = make_judge(owner, rule)
    l = found.listing
    return {**explain(assess(found, judge), judge), "d": (l.detail_text or l.description or "")[:TEXT_CHARS],
            "img": (l.image_urls or "").split()[:4], "fh": l.frame_height}


def label_action(db_path, bikes: Sequence[Bike], form: dict) -> dict:
    """POST /upgrade/oordeel: ja, nee, twijfel of leeg (= weg)."""
    item_id = form.get("item_id", "")
    label = form.get("oordeel", "")
    if label not in LABELS + ("",):
        return {"message": "Niet opgeslagen: kies ja, nee of twijfel.", "error": True}
    found = next((b for b in bikes if b.listing.item_id == item_id), None)
    if found is None:
        return {"message": "Niet opgeslagen: deze fiets staat er niet (meer) bij.", "error": True}
    conn = db.connect(str(db_path))
    try:
        db.set_upgrade_label(conn, item_id, label or None, found.listing.title, found.listing.price_eur)
    finally:
        conn.close()
    return {"id": item_id, "lab": label,
            "message": f"Opgeslagen: {LABEL_TEXT[label]}." if label else "Oordeel weggehaald."}


def csv_download(owner, bikes: Sequence[Bike], problem: str = "") -> str:
    judge = make_judge(owner, owner.config, problem)
    return csv_text(assess_all(bikes, judge), judge)


CSS = pg.static("upgrade.css")

JS = pg.static("upgrade.js")


# --- Laden voor de console ---------------------------------------------------------


def load_owner(db_path, intake_path):
    """(OwnerContext of None, probleem): de eigen fiets met de opgeslagen
    regel (report.load_owner_context() past hem toe)."""

    return report.load_owner_context(str(intake_path), str(db_path))


def console_summary(assessments: Sequence[Assessment], judge: Judge, saved_at: Optional[str]) -> str:
    lines = [f"Jouw fiets ({judge.label}): {judge.quality.total:.0f}/100 — "
             + ", ".join(f"{DIMENSION_LABELS[d]} {judge.quality.dimensions[d].score:.0f}" for d in DIMENSIONS)]
    lines.append(f"Regel: {'jouw regel van ' + saved_at[:10] if saved_at else 'scoring_config.json (standaard)'}"
                 f", marge {judge.margin:g}, onbekend = {up.config_unknown(judge.config)}")
    changes = rule_changes(judge.config)
    if changes:
        lines.append("  wijkt af: " + "; ".join(changes))
    active = [a for a in assessments if a.bike.active]
    lines.append(f"{len(active)} racefietsen te koop: {sum(a.better for a in active)} beter dan jouw fiets, "
                 f"{sum(a.verdict for a in active)} ook binnen maat en budget.")
    agree = agreement(assessments)
    lines.append(agree.text())
    for title, items in (("Jij zei upgrade, de regel niet", agree.missed),
                         ("Jij zei geen upgrade, de regel wel", agree.wrong)):
        if items:
            lines.append(f"{title}:")
            for a in items[:15]:
                lines.append(f"  {a.gain:+5.1f}  {a.bike.listing.title[:70]}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="De upgradetest: hoe de regel het doet op jouw oordelen, en de uitdraai van alle racefietsen.")
    parser.add_argument("actie", nargs="?", default="stand", choices=("stand", "uitdraai", "zoek"),
                        help="stand (standaard): de uitslag; uitdraai: alle fietsen als CSV; "
                             "zoek: de regel die het best bij je oordelen past (slaat niets op)")
    parser.add_argument("--db", default="koopjes.db")
    parser.add_argument("--mijn-fiets", default=str(HERE / "mijn_fiets.md"))
    parser.add_argument("--uit", default=str(DEFAULT_OUT), help="waar de uitdraai komt (CSV)")
    args = parser.parse_args(argv)
    if db.missing(args.db):
        return 1
    owner, problem = load_owner(args.db, args.mijn_fiets)
    if owner is None:
        print(f"fout: {problem}", file=sys.stderr)
        return 1
    _, saved_at = up.load_rule(args.db)
    judge = make_judge(owner, owner.config)
    bikes = load_bikes(args.db)
    assessments = assess_all(bikes, judge)
    if args.actie == "uitdraai":
        out = Path(args.uit)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(csv_text(assessments, judge), encoding="utf-8", newline="")
        print(f"{len(assessments)} fietsen naar {out}")
        return 0
    print(console_summary(assessments, judge, saved_at))
    if args.actie == "zoek":
        found = search(bikes, owner, owner.config)
        print()
        if found.changes:
            print(f"Beste regel bij je oordelen: {found.correct} van {found.judged} goed (nu {found.before}).")
            for change in found.changes:
                print(f"  {change}")
            print("Opslaan doe je op /upgrade (python dashboard.py --serve).")
        else:
            print(found.note or f"De huidige regel past al het best ({found.before} van {found.judged}).")
        if found.note and found.changes:
            print(found.note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
