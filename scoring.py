"""Kwaliteitsscore — PLAN_FIETSWAARDE.md fase 4.

Dit is de *kwaliteitsscore* uit §7 van het plan: hoe goed een fiets is,
losstaand van de prijs. Niet te verwarren met `Listing.deal_score` in
racefiets_jev.py, dat is hoe goed de prijs is (zie CLAUDE.md, "Valkuilen").

Eén functie scoort zowel een advertentie als de eigen fiets (`owned_item`):
beide worden eerst omgezet naar een `Build` — het genormaliseerde plaatje
waarop score_build() rekent — via build_from_listing() resp.
build_from_owner_specs(). Zo blijft er precies één plek die de gewichten uit
§7 toepast.

Vijf dimensies, elk 0-100, daarna gewogen gemengd tot één totaal:
frame, drivetrain, brakes, wheels, extras. `fit` (framemaat) staat er
expliciet buiten — dat is in §7 een harde poort, geen score, en wordt pas in
fase 5 aangesloten op de echte maatbepaling (`frame_height_bounds()` in
racefiets_jev.py). fits_frame_size() hieronder is alvast de losse, pure
rekenkern daarvoor.

De gewichten en de scoretabellen staan in scoring_config.json, niet
hardgecodeerd — dat is precies wat het plan vraagt ("gewicht aanpassen in de
JSON verandert de uitkomst voorspelbaar").

Net als bij deal_score hoort bij elk dimensiegetal een reden-string: een
niet-uitlegbaar cijfer wordt hier niet vertrouwd (§7)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

DEFAULT_CONFIG_PATH = "scoring_config.json"


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --- Build: het genormaliseerde plaatje waarop gescoord wordt --------------


@dataclass(frozen=True)
class Build:
    """Wat een fiets (advertentie of eigen bezit) voor de scoring vaststelt.
    Elk veld is optioneel: ontbrekende informatie scoort neutraal met een
    reden die dat zegt, in plaats van een gok."""

    label: str = ""
    frame_material: Optional[str] = None  # carbon/aluminium/titanium/staal
    frame_carbon_high_mod: bool = False
    frame_class: Optional[str] = None  # endurance/performance/race
    model_year: Optional[int] = None
    groupset_tier: Optional[int] = None
    electronic: bool = False
    speeds: Optional[int] = None
    brake_type: Optional[str] = None  # velrem/schijfrem/mechanische schijfrem/hydraulische schijfrem
    wheel_material: Optional[str] = None  # carbon/aluminium
    wheel_branded: bool = False
    has_powermeter: bool = False
    has_computer: bool = False
    has_extra_wheelset: bool = False
    has_pedals: bool = False


# Merken die een carbon wielset uit de "naamloos AliExpress"-categorie tillen
# (§6 en mijn_fiets.md: een herkenbaar merk/naaftype verkoopt beter dan een
# gelijkwaardig merkloos wiel). Inclusief de Chinese velrem-merken die het
# plan noemt als vergelijkingsmateriaal voor de eigen CSC-wielset.
WHEEL_BRAND_RE = re.compile(
    r"\bzipp\b|\benve\b|\broval\b|\bbontrager\b|\bmavic\b|\bfulcrum\b|"
    r"\bdt[\s-]?swiss\b|\bcampagnolo\b|\breynolds\b|\bnovatec\b|\bcsc\b|"
    r"\belitewheels\b|\bsuperteam\b|\byoeleo\b|\bwinspace\b|\blight\s*bicycle\b|"
    r"\bican\b|\bhed\b|\bcorima\b|\blightweight\b|\bvision\b|\bffwd\b|\bparcours\b",
    re.I,
)


def detect_wheel_branded(text: str) -> bool:
    """Of `text` een herkenbaar wielmerk noemt. Geen marktfeit maar tekstherkenning,
    dezelfde soort best-effort match als detect_groupset() in racefiets_jev.py."""
    return bool(WHEEL_BRAND_RE.search(text))


# Merken waarvan een losse vermelding in een advertentie vrijwel altijd de
# wielen betreft ("Roval Rapide CLX", "Newmen wielen"), ook als er geen
# "wiel" of "carbon" bij staat. Bewust een deelverzameling van WHEEL_BRAND_RE:
# Campagnolo en Bontrager staan in advertenties vaker voor de groepset of
# een stuur, Novatec en CSC zijn naafmerken, "vision" en "lightweight" zijn
# ook gewone woorden. Die tellen alleen mee als het wieltype al carbon is.
WHEEL_FIRST_BRAND_RE = re.compile(
    r"\bzipp\b|\benve\b|\broval\b|\bmavic\b|\bfulcrum\b|\bdt[\s-]?swiss\b|"
    r"\breynolds\b|\bffwd\b|\bparcours\b|\bnewmen\b|\bhed\b|\bcorima\b|"
    r"\belitewheels\b|\bsuperteam\b|\byoeleo\b|\bwinspace\b|\blight\s*bicycle\b",
    re.I,
)
# Dezelfde merken maken ook sturen, zadelpennen en vorken: "Roval cockpit" of
# "Enve stuur" zegt niets over de wielen.
NON_WHEEL_PART_RE = re.compile(
    r"[\s-]*(?:\w+[\s-]+)?(?:cockpit|stuur\w*|handlebar\w*|stem|zadel\w*|seatpost|vork|fork)\b",
    re.I,
)


def detect_wheel_brand_only(text: str) -> bool:
    """Of `text` een wielmerk noemt dat ook zonder materiaal naar de wielen
    wijst — voor een advertentie waar extract_specs() geen wieltype vond."""
    return any(
        not NON_WHEEL_PART_RE.match(text, found.end())
        for found in WHEEL_FIRST_BRAND_RE.finditer(text)
    )


# --- Build vanuit een advertentie -------------------------------------------


def build_from_listing(
    *,
    specs: dict[str, str],
    groupset_label: str = "",
    groupset_tier: Optional[int] = None,
    text: str = "",
    label: str = "",
) -> Build:
    """Build voor een advertentie: `specs` is racefiets_jev.extract_specs()'
    uitvoer, `groupset_label`/`groupset_tier` komen van detect_groupset().
    `text` (titel + omschrijving) wordt alleen gebruikt om een wielmerk te
    herkennen — extract_specs() zelf onderscheidt geen merk- van naamloos
    carbon, dat is precies waar de kwaliteitsscore méér uit haalt dan de
    ruwe spec-extractie."""
    speeds_raw = specs.get("speeds", "")
    year_raw = specs.get("model_year", "")
    wheel_material = specs.get("wheel_type") or None
    return Build(
        label=label,
        frame_material=specs.get("frame_material") or None,
        model_year=int(year_raw) if year_raw.isdigit() else None,
        groupset_tier=groupset_tier,
        electronic="elektronisch" in groupset_label.lower(),
        speeds=int(speeds_raw) if speeds_raw.isdigit() else None,
        brake_type=specs.get("brake_type") or None,
        wheel_material=wheel_material,
        wheel_branded=(
            detect_wheel_branded(text)
            if wheel_material == "carbon"
            else wheel_material is None and detect_wheel_brand_only(text)
        ),
        has_powermeter=specs.get("has_powermeter") == "1",
        has_computer=specs.get("has_computer") == "1",
    )


# --- Build vanuit mijn_fiets.md ---------------------------------------------

FRAME_CLASS_RE = {
    "endurance": re.compile(r"endurance", re.I),
    "race": re.compile(r"\brace\b|\baero\b", re.I),
    "performance": re.compile(r"performance", re.I),
}
HIGH_MOD_RE = re.compile(r"high[\s-]?mod(?:ulus)?\b|\bhm\s*carbon\b", re.I)
EXTRA_WHEELSET_RE = re.compile(r"(extra|tweede|reserve)[\s-]*wielset", re.I)
PEDALS_RE = re.compile(r"\bpedalen\b|\bpedals?\b", re.I)
ELECTRONIC_WORD_RE = re.compile(r"\bja\b|\bdi2\b|\betap\b|\baxs\b", re.I)

_LEADING_INT_RE = re.compile(r"\s*(\d+)")


def _leading_int(value: Optional[str]) -> Optional[int]:
    """Het getal vooraan de waarde: "5   (Ultegra, ...)" -> 5. Zelfde
    aanpak als valuation._int_prefix(), hier los gehouden zodat scoring.py
    geen afhankelijkheid van valuation.py nodig heeft."""
    if not value:
        return None
    match = _LEADING_INT_RE.match(value)
    return int(match.group(1)) if match else None


def _detect_frame_class(frame_tier_raw: str) -> Optional[str]:
    for label, pattern in FRAME_CLASS_RE.items():
        if pattern.search(frame_tier_raw):
            return label
    return None


def build_from_owner_specs(specs: dict[str, str], label: str = "") -> Build:
    """Build vanuit het `Voor de scoring`-blok in mijn_fiets.md — hetzelfde
    key/waarde-dict dat valuation.parse_owner_bike() teruggeeft als
    OwnerBike.specs, dus zonder dat bestand hier opnieuw te parsen."""
    frame_material = (specs.get("frame_material") or "").strip().lower() or None
    frame_tier_raw = specs.get("frame_tier", "")
    electronic_raw = specs.get("electronic", "").strip().lower()
    brake_type = (specs.get("brake_type") or "").strip().lower() or None
    wheel_type_raw = specs.get("wheel_type", "")
    wheel_lower = wheel_type_raw.lower()
    if "carbon" in wheel_lower:
        wheel_material = "carbon"
    elif "aluminium" in wheel_lower or "alu" in wheel_lower:
        wheel_material = "aluminium"
    else:
        wheel_material = None
    extras_raw = specs.get("extras", "").lower()

    return Build(
        label=label,
        frame_material=frame_material,
        frame_carbon_high_mod=bool(HIGH_MOD_RE.search(frame_tier_raw)),
        frame_class=_detect_frame_class(frame_tier_raw),
        model_year=_leading_int(specs.get("model_year")),
        groupset_tier=_leading_int(specs.get("groupset_tier")),
        electronic=bool(ELECTRONIC_WORD_RE.search(electronic_raw)) if electronic_raw else False,
        speeds=_leading_int(specs.get("speeds")),
        brake_type=brake_type,
        wheel_material=wheel_material,
        wheel_branded=detect_wheel_branded(wheel_type_raw),
        has_powermeter="powermeter" in extras_raw or "vermogensmeter" in extras_raw,
        has_computer=any(w in extras_raw for w in ("fietscomputer", "computer", "garmin", "wahoo")),
        has_extra_wheelset=bool(EXTRA_WHEELSET_RE.search(extras_raw)),
        has_pedals=bool(PEDALS_RE.search(extras_raw)),
    )


# --- De dimensies (§7) ------------------------------------------------------


@dataclass(frozen=True)
class DimensionScore:
    score: float
    reasons: tuple[str, ...] = ()


def _clip(value: float) -> float:
    return max(0.0, min(100.0, value))


def score_frame(build: Build, config: dict, *, as_of_year: Optional[int] = None) -> DimensionScore:
    reasons: list[str] = []
    cfg = config["frame"]

    material_key = build.frame_material
    if material_key == "carbon" and build.frame_carbon_high_mod:
        material_key = "carbon_high_mod"
    material_scores = cfg["material_score"]
    if material_key and material_key in material_scores:
        base = material_scores[material_key]
        reasons.append(f"materiaal {build.frame_material} ({base:.0f})")
    else:
        base = cfg["material_score_unknown"]
        reasons.append(f"materiaal onbekend, neutrale aanname ({base:.0f})")

    if build.frame_class and build.frame_class in cfg["tier_multiplier"]:
        multiplier = cfg["tier_multiplier"][build.frame_class]
        reasons.append(f"frameklasse {build.frame_class} (×{multiplier:.2f})")
    else:
        multiplier = cfg["tier_multiplier_unknown"]
        reasons.append(f"frameklasse onbekend, neutraal (×{multiplier:.2f})")

    year = as_of_year or date.today().year
    if build.model_year is not None:
        age = max(0, year - build.model_year)
        decay = min(age * cfg["age_decay_per_year"], cfg["age_decay_max"])
        reasons.append(f"bouwjaar {build.model_year}, leeftijdsverval -{decay * 100:.0f}%")
    else:
        decay = 0.0
        reasons.append("bouwjaar onbekend, geen verval toegepast")

    score = _clip(base * multiplier * (1 - decay))
    return DimensionScore(score, tuple(reasons))


def score_drivetrain(build: Build, config: dict) -> DimensionScore:
    reasons: list[str] = []
    cfg = config["drivetrain"]

    tier_scores = cfg["tier_score"]
    tier_key = str(build.groupset_tier) if build.groupset_tier is not None else None
    if tier_key and tier_key in tier_scores:
        score = float(tier_scores[tier_key])
        reasons.append(f"groepsettier {build.groupset_tier} ({score:.0f})")
    else:
        score = float(cfg["tier_score_unknown"])
        reasons.append(f"groepset niet herkend, neutrale aanname ({score:.0f})")

    if build.electronic:
        score += cfg["electronic_bonus"]
        reasons.append(f"elektronisch schakelen (+{cfg['electronic_bonus']:.0f})")

    if build.speeds and build.speeds > 10:
        bonus = (build.speeds - 10) * cfg["speeds_bonus_per_speed_above_10"]
        score += bonus
        reasons.append(f"{build.speeds}-speed (+{bonus:.0f})")

    return DimensionScore(_clip(score), tuple(reasons))


def score_brakes(build: Build, config: dict) -> DimensionScore:
    cfg = config["brakes"]
    if build.brake_type and build.brake_type in cfg["score"]:
        score = float(cfg["score"][build.brake_type])
        reason = f"{build.brake_type} ({score:.0f})"
    else:
        score = float(cfg["score_unknown"])
        reason = f"remtype onbekend, neutrale aanname ({score:.0f})"
    return DimensionScore(_clip(score), (reason,))


def score_wheels(build: Build, config: dict) -> DimensionScore:
    cfg = config["wheels"]
    if build.wheel_material == "aluminium":
        score = float(cfg["aluminium"])
        reason = f"aluminium wielen ({score:.0f})"
    elif build.wheel_material == "carbon":
        if build.wheel_branded:
            score = float(cfg["carbon_merk"])
            reason = f"merk-carbon wielen ({score:.0f})"
        else:
            score = float(cfg["carbon_naamloos"])
            reason = f"naamloos carbon wielen ({score:.0f})"
    elif build.wheel_branded:
        # Een merkwielset waarvan de advertentie het materiaal niet noemt:
        # hoger dan helemaal onbekend, lager dan merk-carbon, want het kan
        # ook een aluminium set van hetzelfde merk zijn.
        # .get(): een eigen scoring_config.json van vóór deze sleutel moet
        # blijven werken.
        score = float(cfg.get("merk_materiaal_onbekend", cfg["carbon_naamloos"]))
        reason = f"merkwielen, materiaal niet genoemd ({score:.0f})"
    else:
        score = float(cfg["score_unknown"])
        reason = f"wieltype onbekend, neutrale aanname ({score:.0f})"
    return DimensionScore(_clip(score), (reason,))


def score_extras(build: Build, config: dict, *, owner_already_has: frozenset = frozenset()) -> DimensionScore:
    """Extras tellen relatief aan wat de eigenaar al heeft (§7): geef
    `owner_already_has` mee (bv. {"computer"}) om een extra die hij al bezit
    tegen een gekort tarief te laten meetellen, in plaats van vol. Voor de
    eigen fiets scoren blijft dit leeg — daar telt "wat hij al heeft" niet
    tegen zichzelf mee."""
    cfg = config["extras"]
    reasons: list[str] = []
    score = 0.0

    if build.has_powermeter:
        score += cfg["powermeter"]
        reasons.append(f"powermeter (+{cfg['powermeter']:.0f})")
    if build.has_computer:
        if "computer" in owner_already_has:
            bonus = cfg["computer"] * cfg["computer_owned_discount"]
            reasons.append(
                f"fietscomputer (+{bonus:.0f}, gekort — eigenaar heeft er al een)"
            )
        else:
            bonus = cfg["computer"]
            reasons.append(f"fietscomputer (+{bonus:.0f})")
        score += bonus
    if build.has_extra_wheelset:
        score += cfg["extra_wheelset"]
        reasons.append(f"extra wielset (+{cfg['extra_wheelset']:.0f})")
    if build.has_pedals:
        score += cfg["pedals"]
        reasons.append(f"pedalen (+{cfg['pedals']:.0f})")

    if not reasons:
        reasons.append("geen extra's")

    return DimensionScore(_clip(min(score, cfg["max"])), tuple(reasons))


# --- Totaal ------------------------------------------------------------------


@dataclass(frozen=True)
class QualityScore:
    total: float
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)


def score_build(
    build: Build,
    config: dict,
    *,
    owner_already_has: frozenset = frozenset(),
    as_of_year: Optional[int] = None,
) -> QualityScore:
    """De kwaliteitsscore uit §7: vijf dimensies, gewogen gemengd tot één
    totaal 0-100. Dezelfde functie voor een advertentie (via
    build_from_listing()) en voor de eigen fiets (via
    build_from_owner_specs()) — allebei geven ze een Build, en verder maakt
    de herkomst voor deze functie niets uit."""
    dimensions = {
        "frame": score_frame(build, config, as_of_year=as_of_year),
        "drivetrain": score_drivetrain(build, config),
        "brakes": score_brakes(build, config),
        "wheels": score_wheels(build, config),
        "extras": score_extras(build, config, owner_already_has=owner_already_has),
    }
    weights = config["weights"]
    total_weight = sum(weights[name] for name in dimensions)
    total = sum(dimensions[name].score * weights[name] for name in dimensions) / total_weight
    return QualityScore(total=_clip(total), dimensions=dimensions)


def format_quality_score(quality: QualityScore, label: str = "") -> str:
    lines = [f"Kwaliteitsscore {label}: {quality.total:.0f}/100".strip()]
    for name, dimension in quality.dimensions.items():
        lines.append(f"  {name}: {dimension.score:.0f}/100 — {' · '.join(dimension.reasons)}")
    return "\n".join(lines)


# --- Fit-poort (§7): geen score, een harde ja/nee --------------------------


def fits_frame_size(
    bounds: Optional[tuple[float, float]], target_cm: float, tolerance_cm: float = 2.0
) -> bool:
    """Of een framemaat-bandbreedte (racefiets_jev.frame_height_bounds()) de
    doelmaat toelaat, binnen `tolerance_cm`. Onbekende maat (bounds is None)
    faalt de poort niet stil — de aanroeper beslist hoe daarmee om te gaan.
    Puur en zonder database, zodat fase 5 'm zo in de upgrade-finder kan
    hangen naast frame_height_bounds()."""
    if bounds is None:
        return False
    low, high = bounds
    return low <= target_cm + tolerance_cm and high >= target_cm - tolerance_cm


# --- CLI: baseline van de eigen fiets ---------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Kwaliteitsscore van de eigen fiets uit mijn_fiets.md (fase 4).",
    )
    parser.add_argument("--mijn-fiets", default="mijn_fiets.md")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)

    import valuation as val

    try:
        with open(args.mijn_fiets, encoding="utf-8") as f:
            bike = val.parse_owner_bike(f.read())
    except FileNotFoundError:
        print(f"fout: {args.mijn_fiets} niet gevonden", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"fout: {exc}", file=sys.stderr)
        return 1

    config = load_config(args.config)
    build = build_from_owner_specs(bike.specs, label=bike.label)
    quality = score_build(build, config)
    print(format_quality_score(quality, label=bike.label))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
