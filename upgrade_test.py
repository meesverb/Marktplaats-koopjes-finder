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
   (`apply_saved_rule()`). Zonder opgeslagen regel: scoring_config.json.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import db
import racefiets_jev as mp
import scoring as sc
import upgrade as up

RULE_KEY = "upgrade_regel"
LABELS = ("ja", "nee", "twijfel")
LABEL_TEXT = {"ja": "upgrade", "nee": "geen upgrade", "twijfel": "twijfel"}
DIMENSIONS = ("frame", "drivetrain", "brakes", "wheels", "extras")
DIMENSION_LABELS = {"frame": "frame", "drivetrain": "aandrijving", "brakes": "remmen", "wheels": "wielen",
                    "extras": "extra's"}
HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "lijsten" / "upgrade_uitdraai.csv"


class RuleError(ValueError):
    """Een regel die niet kan; de tekst gaat terug naar de pagina."""


# --- De regel -------------------------------------------------------------------

# Leesbare namen voor de meldingen en de lijst "wat wijkt af".
NAMES = {
    "weights": "gewicht", "frame": "frame", "drivetrain": "aandrijving", "brakes": "remmen",
    "wheels": "wielen", "extras": "extra's", "upgrade": "upgrade",
    "material_score": "materiaal", "material_score_unknown": "materiaal onbekend",
    "tier_multiplier": "frameklasse", "tier_multiplier_unknown": "frameklasse onbekend",
    "age_decay_per_year": "leeftijd per jaar", "age_decay_max": "leeftijd hooguit",
    "tier_score": "groepsetniveau", "tier_score_unknown": "groepset onbekend",
    "electronic_bonus": "elektronisch", "speeds_bonus_per_speed_above_10": "per versnelling boven 10",
    "score": "", "score_unknown": "onbekend", "aluminium": "aluminium", "carbon_naamloos": "naamloos carbon",
    "carbon_merk": "merk-carbon", "merk_materiaal_onbekend": "merk, materiaal onbekend",
    "eigen_wielen": "jouw eigen wielen", "powermeter": "powermeter", "computer": "fietscomputer",
    "computer_owned_discount": "computer als je er al een hebt", "extra_wheelset": "extra wielset",
    "pedals": "pedalen", "max": "hooguit", "marge": "marge", "onbekend": "onbekend telt als",
}


def path_name(path: tuple) -> str:
    return " ".join(n for n in (NAMES.get(str(k), str(k)) for k in path) if n)


def _bounds(path: tuple) -> tuple[float, float]:
    key = path[-1]
    if path[0] == "weights":
        return 0.0, 10.0
    if key == "age_decay_per_year":
        return 0.0, 0.2
    if key in ("age_decay_max", "computer_owned_discount"):
        return 0.0, 1.0
    if path[:2] == ("frame", "tier_multiplier") or key == "tier_multiplier_unknown":
        return 0.0, 3.0
    if key == "marge":
        return -20.0, 50.0
    return 0.0, 100.0


def _number(value, path: tuple) -> float:
    if isinstance(value, bool):
        raise RuleError(f"{path_name(path)} moet een getal zijn")
    try:
        number = float(str(value).strip().replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        raise RuleError(f"{path_name(path)} moet een getal zijn") from None
    if not math.isfinite(number):
        raise RuleError(f"{path_name(path)} moet een getal zijn")
    low, high = _bounds(path)
    if not low <= number <= high:
        raise RuleError(f"{path_name(path)} moet tussen {low:g} en {high:g} liggen")
    return number


def clean_rule(raw, shape: dict) -> dict:
    """Een gecontroleerde regel in de vorm van `shape` (scoring_config.json):
    elke sleutel die `shape` kent, uit `raw` als die hem heeft (anders uit
    `shape`), elk getal eindig en binnen redelijke grenzen. Sleutels die
    `shape` niet kent vallen weg — zo blijft een opgeslagen regel werken als
    scoring_config.json later een sleutel krijgt of verliest. RuleError bij
    iets wat niet kan."""
    def walk(shape_part: dict, raw_part, path: tuple) -> dict:
        out = {}
        raw_part = raw_part if isinstance(raw_part, dict) else {}
        for key, default in shape_part.items():
            here = path + (key,)
            value = raw_part.get(key, default)
            if isinstance(default, dict):
                out[key] = walk(default, value, here)
            elif key == "onbekend":
                if value not in up.UNKNOWN_MODES:
                    raise RuleError(f"onbekend telt als: kies {' of '.join(up.UNKNOWN_MODES)}")
                out[key] = value
            elif key == "eigen_wielen":
                out[key] = None if value in (None, "") else _number(value, here)
            else:
                out[key] = _number(value, here)
        return out

    if not isinstance(raw, dict):
        raise RuleError("geen regel meegestuurd")
    clean = walk(shape, raw, ())
    if sum(clean["weights"].values()) <= 0:
        raise RuleError("minstens één gewicht moet boven 0 liggen")
    return clean


def default_config() -> dict:
    return sc.load_config()


def _read_setting(db_path) -> Optional[str]:
    if not db_path or not Path(db_path).exists():
        return None
    try:
        conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        return db.get_setting(conn, RULE_KEY)
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def load_rule(db_path) -> tuple[Optional[dict], Optional[str]]:
    """(opgeslagen regel, wanneer opgeslagen) of (None, None)."""
    raw = _read_setting(db_path)
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
    except ValueError:
        return None, None
    if not isinstance(data, dict) or not isinstance(data.get("config"), dict):
        return None, None
    return data["config"], data.get("opgeslagen")


def rule_stamp(db_path) -> str:
    """Verandert als de opgeslagen regel verandert (voor de LiveCache)."""
    return _read_setting(db_path) or ""


def apply_saved_rule(config: dict, db_path) -> tuple[dict, Optional[str]]:
    """(config met de opgeslagen regel erover, wanneer opgeslagen). Geen of
    een onleesbare regel: `config` zelf — een kapotte regel mag een ronde
    of pagina nooit laten stoppen."""
    saved, at = load_rule(db_path)
    if saved is None:
        return config, None
    try:
        return clean_rule(saved, config), at
    except RuleError:
        return config, None


def save_rule(db_path, raw) -> dict:
    """Controleren en opslaan; geeft de opgeslagen regel terug."""
    clean = clean_rule(raw, default_config())
    conn = db.connect(str(db_path))
    try:
        db.set_setting(conn, RULE_KEY, json.dumps(
            {"config": clean, "opgeslagen": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            sort_keys=True))
    finally:
        conn.close()
    return clean


def reset_rule(db_path) -> None:
    conn = db.connect(str(db_path))
    try:
        db.set_setting(conn, RULE_KEY, None)
    finally:
        conn.close()


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
    standard = standard if standard is not None else default_config()
    mine, base = _flat(config), _flat(standard)
    return [f"{path_name(path)}: {_show(base.get(path))} → {_show(value)}"
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
    listing: mp.Listing
    prepared: up.Prepared
    active: bool = True
    label: Optional[str] = None
    excluded: str = ""  # weggezet om een reden die blijft ("geen racefiets")
    own_year: bool = False


def _listings_by_id(conn: sqlite3.Connection, ids: Sequence[str]) -> list[mp.Listing]:
    """Fietsen die je beoordeelde maar die niet meer te koop zijn: uit de
    database, zoals racebikes ze leest."""
    import racebikes as rb

    if not ids:
        return []
    conn.row_factory = sqlite3.Row
    site = db.read_listing_specs(conn, source=db.SITE_SPEC_SOURCE)
    found = []
    for start in range(0, len(ids), 500):
        chunk = list(ids[start:start + 500])
        rows = conn.execute(rb.SELECT + f" AND item_id IN ({','.join('?' * len(chunk))})",
                            (f"%/{rb.CATEGORY}/%", *chunk)).fetchall()
        found += [rb._listing(r, site, {}) for r in rows]
    return found


def load_bikes(db_path, listings: Optional[Sequence[mp.Listing]] = None,
               prepared: Optional[dict] = None) -> list[Bike]:
    """De actieve racefietsen (`listings`, anders racebikes.load_listings())
    plus de fietsen met een oordeel die niet meer te koop zijn, met het
    bouwjaar dat de eigenaar zelf invulde en zijn oordeel. `prepared`: een
    dict om de gelezen tekst in te onthouden ({(item_id, jaar): Prepared},
    LiveCache), zolang de database niet verandert."""
    import marks as mr
    import racebikes as rb

    if listings is None:
        listings, _, _ = rb.load_listings(db_path)
    labels, links, marks = {}, {}, []
    inactive: list = []
    if db_path and Path(db_path).exists():
        conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
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
        category = mp.category_from_url(b.listing.url)
        if category is not None and category != mp.ROAD_BIKE_CATEGORY:
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
    current = clean_rule(config, default_config())
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
    rule = clean_rule(rule, default_config())
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
    import computers as pc

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

PATH = "/upgrade"
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
    for brand, name, _, tier, _ in mp.GROUPSET_CATALOG:
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
    wheels = [(("wheels", k), path_name((k,)), "num") for k in config["wheels"] if k != "eigen_wielen"]
    wheels.append((("wheels", "eigen_wielen"), "jouw eigen wielen (leeg = zoals de tekst ze leest)", "num"))
    groups.append(("Wielen", "Jouw CSC-set telt zonder eigen getal als merk-carbon, omdat CSC in de lijst met "
                             "wielmerken staat. Bij een velremfiets verhuist hij mee.", wheels))
    groups.append(("Extra's", "Opgeteld, tot het maximum.",
                   [(("extras", k), path_name((k,)), "pct" if k == "computer_owned_discount" else "num")
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
    import computers as pc
    import racebikes as rb

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
    import dashboard as dash

    notices = f"<div class='banner' role='status'>{html.escape(message)}</div>" if message else ""
    head = ("<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Upgradetest</title><style>{dash.CSS}{dash.SITE_CSS}{CSS}</style></head><body>"
            f"<main data-token='{html.escape(token, quote=True)}'>{dash.site_nav(PATH) if token else ''}"
            "<h1>Upgradetest</h1>")
    if owner is None:
        return (head + notices + f"<div class='banner'>Geen eigen fiets om mee te vergelijken: "
                f"{html.escape(problem or 'mijn_fiets.md ontbreekt')}</div></main></body></html>")
    judge = make_judge(owner, owner.config, problem)
    assessments = assess_all(bikes, judge)
    if not any(b.active for b in bikes):
        notices += ("<div class='banner'>Nog geen racefietsen in de database. Draai eerst een ronde: "
                    "<code>python koopjes.py run overdag</code>.</div>")
    data = {"bikes": bikes_json(bikes), **rule_state(judge, assessments), "std": default_config(),
            "saved": saved_at or "", "queue": queue(assessments), "label": judge.label,
            "dimnames": [DIMENSION_LABELS[d] for d in DIMENSIONS], "minJudged": MIN_JUDGED,
            "paths": {"label": LABEL_PATH, "try": TRY_PATH, "rule": RULE_PATH, "search": SEARCH_PATH,
                      "explain": EXPLAIN_PATH}}
    rule_text = (f"jouw regel van {html.escape(dash.local_time(saved_at)[:10])}" if saved_at
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
    except ValueError:
        raise RuleError("de regel was niet te lezen") from None
    return clean_rule(data, default_config())


def try_rule(owner, bikes: Sequence[Bike], form: dict) -> dict:
    """POST /upgrade/proef: de regel uit het formulier doorrekenen, niets opslaan."""
    try:
        rule = _form_rule(form)
    except RuleError as exc:
        return {"message": f"Niet doorgerekend: {exc}.", "error": True}
    judge = make_judge(owner, rule)
    return rule_state(judge, assess_all(bikes, judge))


def rule_action(db_path, owner, bikes: Sequence[Bike], form: dict) -> dict:
    """POST /upgrade/regel: opslaan (actie=opslaan) of terug naar de standaard."""
    if form.get("actie") == "standaard":
        reset_rule(db_path)
        rule, message, saved = default_config(), "Terug naar de standaard (scoring_config.json).", ""
    else:
        try:
            rule = save_rule(db_path, _form_rule(form))
        except RuleError as exc:
            return {"message": f"Niet opgeslagen: {exc}.", "error": True}
        message = "Opgeslagen: /racefietsen, het rapport en het overzicht rekenen nu met jouw regel."
        saved = load_rule(db_path)[1] or ""
    judge = make_judge(owner, rule)
    return {"message": message, "saved": saved, **rule_state(judge, assess_all(bikes, judge))}


def search_action(owner, bikes: Sequence[Bike], form: dict) -> dict:
    try:
        rule = _form_rule(form)
    except RuleError as exc:
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
    except RuleError as exc:
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


CSS = """
kbd { font: .8em ui-monospace, monospace; border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 4px;
  padding: 0 4px; background: var(--card); }
.progress { font-size: .9rem; color: var(--text-2); margin: 4px 0 10px; }
.testcard { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px;
  display: grid; grid-template-columns: minmax(0, 360px) minmax(0, 1fr); gap: 16px; min-height: 220px; }
.testcard .pics { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; align-content: start; }
.testcard .pics img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 8px; background: var(--line); }
.testcard .pics img:first-child { grid-column: 1 / -1; }
.testcard h2 { font-size: 1.15rem; margin: 0 0 4px; overflow-wrap: anywhere; }
.testcard .price { font-size: 1.2rem; font-weight: 600; }
.testcard .specs { margin-top: 4px; color: var(--text-2); }
.testcard .q { margin-top: 12px; font-weight: 600; }
.testcard .desc { white-space: pre-wrap; font-size: .88rem; color: var(--text-2); max-height: 20em; overflow: auto;
  margin-top: 8px; overflow-wrap: anywhere; }
.peekbox:not(:empty) { margin-top: 8px; padding: 6px 10px; border-radius: 8px; background: var(--badge); font-size: .9rem; }
.answer { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 6px; }
.answer button, .rulebar button, #takeover { font: inherit; padding: 9px 14px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--card); color: var(--text); cursor: pointer; }
.answer button.yes { background: var(--good); border-color: var(--good); color: #fff; font-weight: 600; }
.answer button.no { background: var(--bad); border-color: var(--bad); color: #fff; font-weight: 600; }
.answer button.yes kbd, .answer button.no kbd { color: var(--text); }
.rulebar #save { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
.peek { font-size: .85rem; color: var(--text-2); }
.last { margin-top: 18px; }
.last h3 { margin-top: 0; }
.good { color: var(--good); font-weight: 600; }
.bad { color: var(--bad); font-weight: 600; }
.delta { font-size: .78rem; white-space: nowrap; color: var(--muted); }
.delta.plus { color: var(--good); }
.delta.minus { color: var(--bad); }
table.parts td, table.parts th { padding: 4px 8px; font-size: .85rem; }
table.parts td.why { color: var(--text-2); font-size: .8rem; }
table.matrix { width: auto; margin: 4px 0 8px; }
table.matrix td, table.matrix th { text-align: center; }
details.why summary { cursor: pointer; font-size: .8rem; color: var(--text-2); }
fieldset { border: 1px solid var(--line); border-radius: 10px; margin: 0 0 12px; padding: 8px 14px 12px;
  background: var(--card); }
legend { font-weight: 600; padding: 0 4px; }
.fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 6px 18px; }
label.field { display: flex; justify-content: space-between; align-items: center; gap: 10px; font-size: .86rem; }
label.field input, label.field select { font: inherit; width: 7em; padding: 4px 6px; border: 1px solid var(--line);
  border-radius: 6px; background: var(--surface); color: var(--text); }
label.field select { width: 13em; }
.rulebar { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.rulestatus { margin: 6px 0 10px; }
ul.changelist { font-size: .85rem; color: var(--text-2); padding-left: 18px; }
ul.changelist li.head { list-style: none; margin-left: -18px; font-weight: 600; }
#out td { font-size: .86rem; }
#out td .sub { font-size: .75rem; }
#out th { cursor: pointer; }
#outmore button { margin-top: 8px; }
label.field.wide { grid-column: span 2; }
@media (max-width: 700px) {
  .testcard { grid-template-columns: 1fr; }
  /* De knoppen blijven onderin in beeld: anders na elke fiets scrollen. */
  .answer { position: sticky; bottom: 0; z-index: 2; background: var(--surface); padding: 8px 0;
    border-top: 1px solid var(--line); }
  .answer button { flex: 1 1 40%; min-height: 44px; }
  label.field input { width: 6em; }
  label.field.wide { grid-column: auto; }
}
"""

JS = r"""
(() => {
const D = JSON.parse(document.getElementById('data').textContent);
const token = document.querySelector('main').dataset.token || '';
const LABEL = {ja: 'upgrade', nee: 'geen upgrade', twijfel: 'twijfel'};
const toast = document.getElementById('toast');
let toastTimer = null;
function say(message) {
  if (!message) return;
  toast.textContent = message; toast.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 3500);
}
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const nl = (x, d = 1) => x == null ? '—' : Number(x).toFixed(d).replace('.', ',');
const signed = (x, d = 1) => x == null ? '—' : (x > 0 ? '+' : '') + nl(x, d);
const euro = x => x == null ? '—' : '€' + Math.round(x).toLocaleString('nl-NL');
const byId = Object.fromEntries(D.bikes.map(b => [b.id, b]));
let S = D.s, own = D.own, rule = D.rule;
const labels = {};
D.bikes.forEach(b => { if (b.lab) labels[b.id] = b.lab; });

function post(path, data) {
  const body = new URLSearchParams({token, ...data});
  return fetch(path, {method: 'POST', body}).then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(j => { if (j.reload) { location.reload(); return Promise.reject('reload'); } return j; });
}

// --- tabbladen
const tabs = document.getElementById('tabs');
function showTab(name) {
  if (!document.getElementById('p-' + name)) name = 'test';
  tabs.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.panel === name));
  document.querySelectorAll('section.panel').forEach(s => { s.hidden = s.id !== 'p-' + name; });
  if (name === 'uitslag') renderAgree();
  if (name === 'uitdraai') renderOut();
}
tabs.addEventListener('click', e => {
  const b = e.target.closest('button[data-panel]');
  if (!b) return;
  showTab(b.dataset.panel);
  history.replaceState(null, '', '#' + b.dataset.panel);
});
document.addEventListener('click', e => {
  const a = e.target.closest('[data-goto]');
  if (!a) return;
  e.preventDefault(); showTab(a.dataset.goto); history.replaceState(null, '', '#' + a.dataset.goto);
});

function renderOwn() {
  document.getElementById('ownscore').textContent = `${nl(own.tot, 0)}/100 (`
    + D.dimnames.map((n, i) => `${n} ${nl(own.dims[i], 0)}`).join(' · ') + `) · marge ${nl(own.margin)}`;
}

// --- uitleg per fiets, onthouden per regel
const explained = {};
const ruleKey = () => JSON.stringify(rule);
function explainFor(id) {
  const key = id + '|' + ruleKey();
  if (!explained[key]) explained[key] = post(D.paths.explain, {item_id: id, regel: ruleKey()})
    .then(j => j.error ? null : j, () => null);
  return explained[key];
}
function partsTable(info) {
  return '<div class="table-wrap"><table class="parts"><thead><tr><th>Onderdeel</th><th class="num">Fiets</th>'
    + '<th class="num">Jouw fiets</th><th class="num">Telt</th><th>Waarom</th></tr></thead><tbody>'
    + info.onderdelen.map(p => `<tr><td>${esc(p.naam)}</td><td class="num">${nl(p.fiets, 0)}</td>`
      + `<td class="num">${nl(p.eigen, 0)}</td><td class="num"><span class="delta ${p.punten > 0.05 ? 'plus' : p.punten < -0.05 ? 'minus' : ''}">${signed(p.punten)}</span></td>`
      + `<td class="why">${esc(p.waarom)}</td></tr>`).join('')
    + `</tbody></table></div><p class="sub">${esc(info.redenen.join(' · '))}</p>`;
}
function verdictLine(id) {
  const s = S[id];
  if (!s) return '';
  return `Regel: ${nl(s[0])} tegen jouw ${nl(own.tot)} = <strong>${signed(s[1])}</strong> → `
    + (s[2] ? '<span class="good">beter dan jouw fiets</span>' : '<span class="bad">niet beter</span>')
    + ` (marge ${nl(own.margin)})` + (s[3] ? ' · ook een upgrade op /racefietsen (maat en budget)' : '');
}

// --- de test
const skipped = new Set();
const answered = [];
let current = null;
const nextId = (not) => D.queue.find(id => id !== not && !labels[id] && !skipped.has(id) && S[id]);
function progress() {
  const values = Object.values(labels);
  const count = v => values.filter(x => x === v).length;
  const left = D.queue.filter(id => !labels[id] && !skipped.has(id) && S[id]).length;
  document.getElementById('progress').textContent = `${values.length} beoordeeld: ${count('ja')} ja, `
    + `${count('nee')} nee, ${count('twijfel')} twijfel · nog ${left} in de rij`
    + (skipped.size ? ` (${skipped.size} overgeslagen)` : '');
}
function pics(urls) {
  return (urls || []).map(u => `<img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer">`).join('');
}
function showCard() {
  current = nextId();
  progress();
  const card = document.getElementById('card');
  if (!current) {
    card.innerHTML = '<p class="empty">Alles wat nu te koop is heeft een oordeel of is overgeslagen. Na de volgende ronde komen er nieuwe fietsen bij.</p>';
    return;
  }
  const b = byId[current];
  card.innerHTML = `<div class="pics" id="pics">${pics(b.img)}</div><div>`
    + `<h2><a href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a></h2>`
    + `<div class="price">${euro(b.p)} <span class="muted">${esc(b.pk)}</span></div>`
    + `<div class="specs">${esc(b.sp) || '<span class="muted">geen specs herkend</span>'}</div>`
    + `<div class="q">Is dit een upgrade van jouw ${esc(D.label)}? <span class="muted">Los van prijs en maat.</span></div>`
    + `<div class="peekbox" id="peekbox"></div><div class="desc" id="desc">…</div></div>`;
  const id = current;
  explainFor(id).then(info => {
    if (current !== id) return;
    const desc = document.getElementById('desc');
    if (!info) { desc.textContent = ''; return; }
    if (info.img && info.img.length > (b.img || []).length) document.getElementById('pics').innerHTML = pics(info.img);
    desc.textContent = info.d || '(geen omschrijving)';
  });
  renderPeek();
  const following = nextId(id);
  if (following) explainFor(following);
}
function renderPeek() {
  const box = document.getElementById('peekbox');
  if (box) box.innerHTML = current && document.getElementById('peek').checked ? verdictLine(current) : '';
}
document.getElementById('peek').addEventListener('change', renderPeek);
function showLast(id) {
  const box = document.getElementById('last');
  if (!id || !labels[id]) { box.innerHTML = ''; return; }
  const b = byId[id], lab = labels[id], s = S[id];
  const same = lab === 'twijfel' ? '' : ((lab === 'ja') === !!s[2]
    ? ' · <span class="good">de regel is het met je eens</span>' : ' · <span class="bad">de regel zegt het andere</span>');
  box.innerHTML = `<h3>Vorige: <a href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a></h3>`
    + `<p>Jij: <strong>${esc(LABEL[lab])}</strong> · ${verdictLine(id)}${same}</p><div id="lastparts">…</div>`;
  explainFor(id).then(info => {
    const el = document.getElementById('lastparts');
    if (el && info && answered[answered.length - 1] === id) el.innerHTML = partsTable(info);
  });
}
function answer(kind) {
  if (kind === 'undo') return undo();
  if (!current) return;
  if (kind === 'skip') { skipped.add(current); showCard(); return; }
  const id = current;
  post(D.paths.label, {item_id: id, oordeel: kind}).then(r => {
    if (r.error) { say(r.message); return; }
    labels[id] = kind; answered.push(id);
    showLast(id); showCard(); updateCounts();
  }, e => { if (e !== 'reload') say('Niet opgeslagen: de server antwoordde niet.'); });
}
function undo() {
  const id = answered.pop();
  if (!id) { say('Niets om ongedaan te maken.'); return; }
  post(D.paths.label, {item_id: id, oordeel: ''}).then(r => {
    if (r.error) { say(r.message); answered.push(id); return; }
    delete labels[id];
    D.queue = [id, ...D.queue.filter(x => x !== id)];
    showLast(answered[answered.length - 1]); showCard(); updateCounts(); say('Vorige ongedaan.');
  });
}
document.querySelector('.answer').addEventListener('click', e => {
  const b = e.target.closest('button[data-answer]');
  if (b) answer(b.dataset.answer);
});
document.addEventListener('keydown', e => {
  if (document.getElementById('p-test').hidden || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
  const kind = {j: 'ja', n: 'nee', t: 'twijfel', s: 'skip', u: 'undo'}[e.key];
  if (kind) { e.preventDefault(); answer(kind); }
});

// --- uitslag
function agreement() {
  const a = {yy: [], nn: [], missed: [], wrong: [], unsure: 0};
  for (const [id, lab] of Object.entries(labels)) {
    const s = S[id];
    if (!s) continue;
    if (lab === 'twijfel') a.unsure++;
    else if (lab === 'ja') (s[2] ? a.yy : a.missed).push(id);
    else if (lab === 'nee') (s[2] ? a.wrong : a.nn).push(id);
  }
  a.missed.sort((x, y) => S[x][1] - S[y][1]);
  a.wrong.sort((x, y) => S[y][1] - S[x][1]);
  a.correct = a.yy.length + a.nn.length;
  a.judged = a.correct + a.missed.length + a.wrong.length;
  return a;
}
function deltaChips(id) {
  return S[id].slice(4).map((v, i) => {
    const d = v - own.dims[i];
    return `<span class="delta ${d > 0.05 ? 'plus' : d < -0.05 ? 'minus' : ''}" title="${esc(D.dimnames[i])}: ${nl(v)} tegen jouw ${nl(own.dims[i])}">${esc(D.dimnames[i])} ${signed(d, 0)}</span>`;
  }).join(' ');
}
function labelSelect(id) {
  return `<select data-label="${esc(id)}" aria-label="Jouw oordeel">`
    + ['', 'ja', 'nee', 'twijfel'].map(v => `<option value="${v}"${(labels[id] || '') === v ? ' selected' : ''}>${v ? LABEL[v] : '—'}</option>`).join('')
    + '</select>';
}
function agreeRow(id) {
  const b = byId[id];
  return `<tr><td>${labelSelect(id)}</td><td><a href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a>`
    + `<div class="sub">${esc(b.sp)}${b.act ? '' : ' · niet meer te koop'}</div><div class="sub">${deltaChips(id)}</div>`
    + `<details class="why" data-id="${esc(id)}"><summary>waarom</summary><div>…</div></details></td>`
    + `<td class="num">${euro(b.p)}</td><td class="num"><strong>${signed(S[id][1])}</strong></td></tr>`;
}
function agreeSection(title, ids) {
  if (!ids.length) return '';
  return `<h3>${esc(title)} (${ids.length})</h3><div class="table-wrap"><table><thead><tr><th>Jij</th><th>Fiets</th>`
    + `<th class="num">Prijs</th><th class="num">Winst</th></tr></thead><tbody>${ids.map(agreeRow).join('')}</tbody></table></div>`;
}
function renderAgree() {
  const a = agreement(), box = document.getElementById('agree');
  if (!a.judged) {
    box.innerHTML = `<p class="empty">Nog geen oordelen (ja of nee)${a.unsure ? `; ${a.unsure} keer twijfel` : ''}. Begin bij <a href="#test" data-goto="test">Test</a>.</p>`;
    return;
  }
  box.innerHTML = `<div class="tiles"><div class="tile"><div class="label">Goed</div><div class="value">${a.correct}/${a.judged}</div>`
    + `<div class="sub">${Math.round(a.correct / a.judged * 100)}% van je oordelen${a.unsure ? `; ${a.unsure} twijfel telt niet mee` : ''}</div></div>`
    + `<div class="tile"><div class="label">Jij upgrade, regel niet</div><div class="value">${a.missed.length}</div><div class="sub">te laag gewaardeerd</div></div>`
    + `<div class="tile"><div class="label">Jij geen upgrade, regel wel</div><div class="value">${a.wrong.length}</div><div class="sub">te hoog gewaardeerd</div></div></div>`
    + `<div class="table-wrap" style="display:inline-block"><table class="matrix"><thead><tr><th></th><th>Regel: beter</th><th>Regel: niet</th></tr></thead><tbody>`
    + `<tr><th>Jij: upgrade</th><td>${a.yy.length}</td><td>${a.missed.length}</td></tr>`
    + `<tr><th>Jij: geen upgrade</th><td>${a.wrong.length}</td><td>${a.nn.length}</td></tr></tbody></table></div>`
    + agreeSection('Jij zei upgrade, de regel niet', a.missed) + agreeSection('Jij zei geen upgrade, de regel wel', a.wrong)
    + `<p class="explain">Per onderdeel staat het verschil met jouw fiets. Pas de regel aan onder `
    + `<a href="#regel" data-goto="regel">Jouw regel</a>, of laat hem daar zoeken.</p>`;
}
document.addEventListener('toggle', e => {
  const d = e.target;
  if (!(d instanceof HTMLDetailsElement) || !d.matches('details.why') || !d.open) return;
  explainFor(d.dataset.id).then(info => {
    if (info) d.querySelector('div').innerHTML = partsTable(info) + `<p class="sub">${esc(info.waarom)}</p>`;
  });
}, true);
document.addEventListener('change', e => {
  const sel = e.target.closest('select[data-label]');
  if (!sel) return;
  const id = sel.dataset.label;
  post(D.paths.label, {item_id: id, oordeel: sel.value}).then(r => {
    say(r.message);
    if (r.error) return;
    if (sel.value) labels[id] = sel.value; else delete labels[id];
    updateCounts(); progress();
  });
});
function updateCounts() {
  const a = agreement();
  document.getElementById('agreecount').textContent = a.judged ? `(${a.correct}/${a.judged})` : '';
  renderStatus(a);
  if (!document.getElementById('p-uitslag').hidden) renderAgree();
  if (!document.getElementById('p-uitdraai').hidden) renderOut();
}

// --- jouw regel
const form = document.getElementById('ruleform');
function readForm() {
  const out = JSON.parse(JSON.stringify(rule));
  form.querySelectorAll('[data-path]').forEach(el => {
    const path = el.dataset.path.split('.');
    let node = out;
    path.slice(0, -1).forEach(k => { node = node[k] = node[k] || {}; });
    const key = path[path.length - 1];
    if (el.tagName === 'SELECT') { node[key] = el.value; return; }
    const raw = el.value.trim().replace(',', '.');
    if (raw === '') { node[key] = key === 'eigen_wielen' ? null : raw; return; }
    let v = Number(raw);
    if (el.dataset.kind === 'pct') v = v / 100;
    node[key] = Number.isFinite(v) ? Math.round(v * 1e6) / 1e6 : raw;
  });
  return out;
}
function fillForm(r) {
  form.querySelectorAll('[data-path]').forEach(el => {
    let v = el.dataset.path.split('.').reduce((n, k) => n == null ? n : n[k], r);
    if (el.tagName === 'SELECT') { el.value = v; return; }
    if (v == null) { el.value = ''; return; }
    if (el.dataset.kind === 'pct') v = Math.round(v * 100 * 1e6) / 1e6;
    el.value = String(v);
  });
}
let tryTimer = null, trySeq = 0;
form.addEventListener('input', () => { clearTimeout(tryTimer); tryTimer = setTimeout(tryRule, 350); });
form.addEventListener('change', () => { clearTimeout(tryTimer); tryRule(); });
function tryRule() {
  const seq = ++trySeq;
  const status = document.getElementById('rulestatus');
  status.classList.add('busy');
  post(D.paths.try, {regel: JSON.stringify(readForm())}).then(r => {
    if (seq !== trySeq) return;
    if (r.error) { say(r.message); status.textContent = r.message; return; }
    applyState(r);
  }, e => { if (e !== 'reload') say('Doorrekenen lukte niet.'); })
    .finally(() => { if (seq === trySeq) status.classList.remove('busy'); });
}
function applyState(r) {
  S = r.s; own = r.own; rule = r.rule;
  renderOwn(); renderChanges(r.changes); updateCounts(); renderPeek();
  const last = answered[answered.length - 1];
  if (last) showLast(last);
}
function renderChanges(changes) {
  document.getElementById('changes').innerHTML = changes.length
    ? '<li class="head">Wijkt af van de standaard:</li>' + changes.map(c => `<li>${esc(c)}</li>`).join('')
    : '<li class="head">Gelijk aan de standaard (scoring_config.json).</li>';
}
let savedCorrect = null;
function renderStatus(a) {
  const active = D.bikes.filter(b => b.act && S[b.id]);
  const better = active.filter(b => S[b.id][2]).length, upgrade = active.filter(b => S[b.id][3]).length;
  document.getElementById('rulestatus').innerHTML = `Met deze regel: <strong>${a.judged ? `${a.correct} van je ${a.judged}` : 'nog geen'}</strong> oordelen goed`
    + (savedCorrect != null && a.judged ? ` (bij opslaan: ${savedCorrect})` : '')
    + ` · jouw fiets ${nl(own.tot)} · van de ${active.length} te koop zijn er ${better} beter dan jouw fiets, ${upgrade} ook binnen maat en budget.`;
}
document.getElementById('save').addEventListener('click', () => {
  post(D.paths.rule, {actie: 'opslaan', regel: JSON.stringify(readForm())}).then(r => {
    say(r.message);
    if (r.error) return;
    applyState(r); fillForm(r.rule); savedCorrect = agreement().correct;
    document.getElementById('rulename').textContent = 'jouw regel (net opgeslagen)';
  });
});
document.getElementById('standard').addEventListener('click', () => {
  if (!confirm('Je opgeslagen regel weghalen en terug naar de standaard (scoring_config.json)?')) return;
  post(D.paths.rule, {actie: 'standaard'}).then(r => {
    say(r.message);
    if (r.error) return;
    applyState(r); fillForm(r.rule); savedCorrect = agreement().correct;
    document.getElementById('rulename').textContent = 'de standaard (scoring_config.json)';
  });
});
document.getElementById('search').addEventListener('click', () => {
  const box = document.getElementById('found');
  box.innerHTML = '<p class="muted">Zoeken… dat duurt een paar seconden.</p>';
  post(D.paths.search, {regel: JSON.stringify(readForm())}).then(r => {
    if (r.error) { box.innerHTML = ''; say(r.message); return; }
    if (!r.changes.length) {
      box.innerHTML = `<div class="banner">${esc(r.note || `De regel van nu past al het best: ${r.before} van ${r.judged} goed.`)}</div>`;
      return;
    }
    box.innerHTML = `<div class="banner"><strong>${r.correct} van je ${r.judged}</strong> oordelen goed met deze regel (nu ${r.before}).`
      + `<ul>${r.changes.map(c => `<li>${esc(c)}</li>`).join('')}</ul>${r.note ? `<p class="sub">${esc(r.note)}</p>` : ''}`
      + '<button id="takeover">Neem over (daarna nog opslaan)</button></div>';
    document.getElementById('takeover').addEventListener('click', () => { fillForm(r.rule); box.innerHTML = ''; tryRule(); });
  }, e => { box.innerHTML = ''; if (e !== 'reload') say('Zoeken lukte niet.'); });
});

// --- uitdraai
const COLS = [['Jij', null], ['Fiets', b => b.t.toLowerCase()], ['Prijs', b => b.p ?? -1], ['Jaar', b => b.yr ?? 0],
  ...D.dimnames.map((n, i) => [n, b => S[b.id][4 + i]]), ['Totaal', b => S[b.id][0]], ['Winst', b => S[b.id][1]],
  ['Beter', b => S[b.id][2]], ['Upgrade', b => S[b.id][3]]];
let sortCol = COLS.findIndex(c => c[0] === 'Winst'), sortDir = -1, shownRows = 200;
function outRows() {
  const show = document.getElementById('show').value, q = document.getElementById('q').value.trim().toLowerCase();
  return D.bikes.filter(b => {
    const s = S[b.id];
    if (!s) return false;
    if (show === 'te koop' && !b.act) return false;
    if (show === 'beoordeeld' && !labels[b.id]) return false;
    if (show === 'oneens') {
      const l = labels[b.id];
      if ((l !== 'ja' && l !== 'nee') || (l === 'ja') === !!s[2]) return false;
    }
    if (show === 'beter' && !s[2]) return false;
    if (show === 'upgrade' && !s[3]) return false;
    return !q || (b.t + ' ' + b.sp).toLowerCase().includes(q);
  });
}
function renderOut() {
  const table = document.getElementById('out');
  table.tHead.innerHTML = '<tr>' + COLS.map(([name, key], i) => `<th${key ? ` data-col="${i}"` : ''}${i >= 2 ? ' class="num"' : ''}>`
    + `${esc(name)}${i === sortCol ? (sortDir < 0 ? ' ↓' : ' ↑') : ''}</th>`).join('') + '</tr>';
  const rows = outRows();
  const key = COLS[sortCol][1];
  rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * sortDir; });
  table.tBodies[0].innerHTML = rows.slice(0, shownRows).map(b => {
    const s = S[b.id];
    const parts = s.slice(4).map((v, i) => {
      const d = v - own.dims[i];
      return `<td class="num">${nl(v, 0)}<div class="sub delta ${d > 0.05 ? 'plus' : d < -0.05 ? 'minus' : ''}">${signed(d, 0)}</div></td>`;
    }).join('');
    return `<tr><td>${labelSelect(b.id)}</td><td><a href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a>`
      + `<div class="sub">${esc(b.sp)}${b.act ? '' : ' · niet meer te koop'}</div></td><td class="num">${euro(b.p)}</td>`
      + `<td class="num">${b.yr ?? '—'}${b.ys ? `<div class="sub">${esc(b.ys)}</div>` : ''}</td>${parts}`
      + `<td class="num">${nl(s[0])}</td><td class="num"><strong>${signed(s[1])}</strong></td>`
      + `<td class="num">${s[2] ? '<span class="good">ja</span>' : '—'}</td><td class="num">${s[3] ? '<span class="good">ja</span>' : '—'}</td></tr>`;
  }).join('');
  document.getElementById('outcount').textContent = `${rows.length} fiets${rows.length === 1 ? '' : 'en'}`;
  document.getElementById('outmore').innerHTML = rows.length > shownRows
    ? `<button class="quiet" id="more">Toon nog ${Math.min(200, rows.length - shownRows)} (van ${rows.length - shownRows})</button>` : '';
}
document.getElementById('out').addEventListener('click', e => {
  const th = e.target.closest('th[data-col]');
  if (!th) return;
  const col = Number(th.dataset.col);
  sortDir = col === sortCol ? -sortDir : (col === 1 ? 1 : -1);
  sortCol = col; renderOut();
});
document.getElementById('outmore').addEventListener('click', e => {
  if (e.target.closest('#more')) { shownRows += 200; renderOut(); }
});
document.getElementById('show').addEventListener('change', () => { shownRows = 200; renderOut(); });
document.getElementById('q').addEventListener('input', () => { shownRows = 200; renderOut(); });

renderOwn();
renderChanges(D.changes);
updateCounts();
showCard();
showTab(location.hash.slice(1) || 'test');
})();
"""


# --- Laden voor de console ---------------------------------------------------------


def load_owner(db_path, intake_path):
    """(OwnerContext of None, probleem): de eigen fiets met de opgeslagen
    regel (report.load_owner_context() past hem toe)."""
    import report

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
    if not Path(args.db).exists():
        print(f"Database {args.db} bestaat niet.", file=sys.stderr)
        return 1
    owner, problem = load_owner(args.db, args.mijn_fiets)
    if owner is None:
        print(f"fout: {problem}", file=sys.stderr)
        return 1
    _, saved_at = load_rule(args.db)
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
