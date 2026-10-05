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
