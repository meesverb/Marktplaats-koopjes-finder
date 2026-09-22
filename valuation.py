"""Waarderingsmotor — PLAN_FIETSWAARDE.md fase 3.

Drie onafhankelijke schatters uit §6, daarna gemengd tot één band:

- **E1 — comps.** Mediaan en spreiding van vergelijkbare advertenties uit
  `koopjes.db`, gekozen via een ladder met afnemend vertrouwen (zelfde model →
  zelfde modelfamilie → zelfde segment). Welke trede en welke n gebruikt is
  staat altijd in de bewijsregels; onder n=5 wordt het nooit als hard getal
  gepresenteerd.
- **E2 — vraagprijs → verkoopprijs.** Marktplaats publiceert vraagprijzen, geen
  verkoopprijzen. Advertenties die snel verdwijnen waren realistisch geprijsd,
  advertenties die maanden blijven staan niet; de verhouding tussen die twee
  medianen is een gemeten correctiefactor. Zolang er te weinig verdwijn-data is
  geldt een heuristische default.
- **E3 — som der delen.** Framewaarde + groepset + wielen + accessoires uit
  `component_price`, maal een bundelfactor.

Twee dingen zijn hier met opzet strikt:

1. **Niets verzinnen.** Ontbreekt de data voor een schatter, dan weegt hij niet
   mee en zegt de bewijsregel dát ook. Een taxatie zonder comps is geen taxatie
   en wordt niet uitgerekend.
2. **Nooit terugschrijven.** Een taxatie belandt alleen in `valuation` en
   `valuation_evidence`, nooit in `listing_price` of `component_price` — die
   blijven ruwe waarneming, anders voedt de waardering zichzelf.

De rekenkunde hieronder is puur: functies op getallen, zonder netwerk en zonder
connectie. De database-laag haalt rijen op en rekent niet. Dat is de scheiding
die fase 3 vraagt, en het is ook wat de tests op synthetische comps mogelijk
maakt.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Sequence

import db
import racefiets_jev as mp

# Staat in elke valuation-rij, zodat een latere fase kan zien met welke methode
# een opgeslagen taxatie gemaakt is. Ophogen zodra de rekenwijze verandert.
METHOD_VERSION = "e1e2e3-1"

# Onder dit aantal comps is de mediaan geen hard getal meer (§6). De taxatie
# gaat wel door — met een lager vertrouwen en een bewijsregel die het zegt.
MIN_COMPS_FOR_A_HARD_NUMBER = 5

# E2's default zolang de verdwijn-data te dun is: §6 schrijft 10-15%
# onderhandelingsruimte voor. Dit is een heuristiek, geen meting, en elke
# taxatie die hem gebruikt zegt dat in de bewijsregel.
NEGOTIATION_DEFAULT = (0.85, 0.875, 0.90)  # laag, midden, hoog

# Vanaf hier mag de gemeten factor de default overschrijven (§6: n>=20 per
# categorie). Een advertentie die binnen 14 dagen verdwijnt was realistisch
# geprijsd; de "blijvers" zijn elke advertentie die na 60 dagen nog staat —
# verdwenen óf nog altijd online, dat maakt voor "blijver" niet uit — die was
# dat niet.
EMPIRICAL_MIN_N = 20
QUICK_SALE_DAYS = 14
STALE_DAYS = 60
# Een gemeten factor buiten deze grenzen is geen marktsignaal maar een
# artefact van een scheve steekproef; dan blijft de default staan.
NEGOTIATION_BOUNDS = (0.60, 1.00)

# E3: losse onderdelen bij elkaar opgeteld brengen compleet minder op dan los
# verkocht. Ook dit is een heuristiek en geen meting — hij staat als aparte
# bewijsregel in de uitvoer, zodat zichtbaar is wat hij doet.
BUNDLE_FACTOR = 0.80
# Wat een upgrade terugverdient als hij mét de fiets meegaat. §6: kopers van
# een complete fiets betalen zelden mee aan andermans upgrades. Heuristiek.
UPGRADE_RECOVERY_WITH_BIKE = 0.50

# Hoe zwaar een trede meeweegt in de menging, en hoeveel E3 mag meewegen naast
# E1. E1 is voor een complete fiets de betere schatter: kopers vergelijken met
# andere advertenties, niet met een onderdelenlijst.
CONFIDENCE_WEIGHT = {"hoog": 1.0, "midden": 0.7, "laag": 0.4, "indicatief": 0.2}
PARTS_WEIGHT = 0.5

# Comps ouder dan dit zijn geen markt meer, alleen geschiedenis.
DEFAULT_COMP_WINDOW_DAYS = 180


# --- Gegevens -------------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    """Wat er getaxeerd wordt, in de termen waarin comps gezocht worden."""

    label: str
    kind: str = "bike"
    # Patronen in de advertentietekst. model_patterns moeten állemaal voorkomen
    # (trede 1), family_patterns één ervan (trede 2), exclude_patterns geen
    # enkele — die laatste houdt een duurdere uitvoering van hetzelfde model
    # buiten de comps.
    model_patterns: tuple[str, ...] = ()
    family_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    model_year: Optional[int] = None
    groupset_tier: Optional[int] = None
    frame_material: Optional[str] = None
    brake_type: Optional[str] = None
    speeds: Optional[int] = None
    segment_speeds: tuple[int, int] = (10, 11)
    segment_years: tuple[int, int] = (2009, 2015)


@dataclass(frozen=True)
class CompCandidate:
    """Eén advertentie uit de database, klaar om tegen de ladder te houden."""

    item_id: str
    title: str
    url: str
    price_eur: float
    text: str
    is_bid: bool = False
    days_online: Optional[int] = None
    disappeared: bool = False
    specs: dict[str, str] = field(default_factory=dict)
    groupset_tier: Optional[int] = None


@dataclass(frozen=True)
class Evidence:
    """Eén regel onderbouwing. kind volgt de kolom uit §5:
    'comp' | 'parts' | 'retail' | 'depreciation' | 'adjustment'."""

    kind: str
    note: str
    price_eur: Optional[float] = None
    weight: Optional[float] = None
    ref_id: Optional[str] = None
    ref_url: Optional[str] = None


@dataclass(frozen=True)
class Valuation:
    subject_type: str
    subject_id: str
    scenario: str
    low_eur: float
    mid_eur: float
    high_eur: float
    confidence: str
    evidence: tuple[Evidence, ...]
    method_version: str = METHOD_VERSION


@dataclass(frozen=True)
class CompSet:
    """De comps die de ladder heeft opgeleverd, met de trede waar ze vandaan
    komen — zonder die twee is de mediaan een getal zonder herkomst."""

    rung: int
    description: str
    confidence: str
    comps: tuple[CompCandidate, ...]

    @property
    def n(self) -> int:
        return len(self.comps)

    @property
    def prices(self) -> list[float]:
        return [c.price_eur for c in self.comps]


# --- Pure rekenkunde ------------------------------------------------------


def percentile(values: Sequence[float], fraction: float) -> float:
    """Lineair geïnterpoleerd percentiel. Eigen implementatie omdat
    statistics.quantiles() minstens twee waarnemingen eist en een taxatie op
    n=1 ook een (slecht onderbouwd) getal moet kunnen opleveren."""
    if not values:
        raise ValueError("percentiel van een lege reeks")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    below = int(position)
    above = min(below + 1, len(ordered) - 1)
    weight = position - below
    return float(ordered[below] * (1 - weight) + ordered[above] * weight)


def price_band(prices: Sequence[float]) -> tuple[float, float, float]:
    """(laag, midden, hoog) = 20e percentiel, mediaan, 80e percentiel."""
    return (
        percentile(prices, 0.20),
        float(statistics.median(prices)),
        percentile(prices, 0.80),
    )


def scale_band(band: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return (band[0] * factor, band[1] * factor, band[2] * factor)


def dutch(number: float, decimals: int = 2) -> str:
    """Een kommagetal, want de console-uitvoer van dit project is Nederlands."""
    return f"{number:.{decimals}f}".replace(".", ",")


def empirical_negotiation_factor(
    candidates: Sequence[CompCandidate],
) -> Optional[tuple[float, int, int]]:
    """De gemeten correctiefactor uit §6: mediaan vraagprijs van advertenties
    die snel weg waren, gedeeld door die van advertenties die bleven hangen.
    Geeft (factor, n_snel, n_blijvers) of None zolang er te weinig van beide
    is.

    "Blijvers" zijn niet alleen advertenties die uiteindelijk (na 60+ dagen)
    verdwenen — dat zou alleen de slechtst geprijsde staart van de blijvers
    meten. Een advertentie die na 60+ dagen nog altijd online staat telt net
    zo goed mee; candidate_from_row() leidt days_online voor zo'n advertentie
    af uit first_seen zodra de kolom zelf NULL is.

    Let op wat dit *niet* is: verdwenen is niet verkocht — een advertentie kan
    ook ingetrokken of verlopen zijn. Het is een proxy, en de bewijsregel die
    deze factor gebruikt zegt dat erbij."""
    quick = [
        c.price_eur
        for c in candidates
        if c.disappeared and c.days_online is not None and c.days_online <= QUICK_SALE_DAYS
    ]
    stale = [
        c.price_eur
        for c in candidates
        if c.days_online is not None and c.days_online >= STALE_DAYS
    ]
    if len(quick) < EMPIRICAL_MIN_N or len(stale) < EMPIRICAL_MIN_N:
        return None

    stale_median = statistics.median(stale)
    if stale_median <= 0:
        return None
    factor = statistics.median(quick) / stale_median
    low, high = NEGOTIATION_BOUNDS
    if not low <= factor <= high:
        return None
    return (factor, len(quick), len(stale))


def parts_total(component_values: Sequence[float], bundle_factor: float = BUNDLE_FACTOR) -> float:
    """E3: som der delen maal de bundelfactor."""
    return sum(component_values) * bundle_factor


def weigh(comps_mid: Optional[float], comps_weight: float,
          parts_mid: Optional[float], parts_weight: float) -> Optional[float]:
    """Gewogen gemiddelde van de schatters die er zijn. Geeft None als er
    niets te wegen valt — dan is er geen taxatie, en dat is een uitkomst."""
    pairs = [
        (value, weight)
        for value, weight in ((comps_mid, comps_weight), (parts_mid, parts_weight))
        if value is not None and weight > 0
    ]
    if not pairs:
        return None
    total_weight = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total_weight


# --- De comp-ladder (§6, E1) ----------------------------------------------


@dataclass(frozen=True)
class Rung:
    number: int
    description: str
    confidence: str
    matches: Callable[[Subject, CompCandidate], bool]


# Een advertentietitel zet het modeljaar er bijna altijd kaal in ("Giant Defy
# 2012"), terwijl extract_specs() met opzet alleen een gelábeld bouwjaar
# accepteert — in een omschrijving is "sinds 2018 in bezit" net zo goed een
# 20xx. In een titel is dat risico veel kleiner, en hier telt het alleen mee
# voor de vraag welke advertenties vergelijkbaar zijn (en, via upgrade.py, voor
# het leeftijdsverval in de kwaliteitsscore). Het wordt niet als spec
# weggeschreven.
TITLE_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")


def title_year(title: str) -> Optional[int]:
    match = TITLE_YEAR_RE.search(title)
    return int(match.group(1)) if match else None


def candidate_year(candidate: CompCandidate) -> Optional[int]:
    year = candidate.specs.get("model_year")
    if year and year.isdigit():
        return int(year)
    return title_year(candidate.title)


def _text_matches(candidate: CompCandidate, patterns: Sequence[str], *, all_of: bool) -> bool:
    if not patterns:
        return False
    hits = (pattern.lower() in candidate.text for pattern in patterns)
    return all(hits) if all_of else any(hits)


def _excluded(subject: Subject, candidate: CompCandidate) -> bool:
    return any(pattern.lower() in candidate.text for pattern in subject.exclude_patterns)


def _year_within(subject: Subject, candidate: CompCandidate, slack: int) -> bool:
    if subject.model_year is None:
        return False
    year = candidate_year(candidate)
    return year is not None and abs(year - subject.model_year) <= slack


def _same_model(subject: Subject, candidate: CompCandidate) -> bool:
    return (
        not _excluded(subject, candidate)
        and _text_matches(candidate, subject.model_patterns, all_of=True)
        and _year_within(subject, candidate, 2)
        and candidate.groupset_tier is not None
        and candidate.groupset_tier == subject.groupset_tier
    )


def _same_family(subject: Subject, candidate: CompCandidate) -> bool:
    return (
        not _excluded(subject, candidate)
        and _text_matches(candidate, subject.family_patterns, all_of=False)
        and _year_within(subject, candidate, 3)
    )


def _same_segment(subject: Subject, candidate: CompCandidate) -> bool:
    if _excluded(subject, candidate):
        return False
    year = candidate_year(candidate)
    if year is None or not subject.segment_years[0] <= year <= subject.segment_years[1]:
        return False
    material = candidate.specs.get("frame_material")
    if subject.frame_material and material and material != subject.frame_material:
        return False
    brake = candidate.specs.get("brake_type")
    if subject.brake_type and brake and brake != subject.brake_type:
        return False
    speeds = candidate.specs.get("speeds")
    if speeds and speeds.isdigit():
        if not subject.segment_speeds[0] <= int(speeds) <= subject.segment_speeds[1]:
            return False
    # Een advertentie die over geen van deze drie iets zegt is geen segment-comp
    # maar een onbekende fiets; vraag minstens één bevestigd kenmerk.
    return any(candidate.specs.get(key) for key in ("frame_material", "brake_type", "speeds"))


RUNGS = [
    Rung(1, "zelfde model, bouwjaar ±2, zelfde groepsettier", "hoog", _same_model),
    Rung(2, "zelfde modelfamilie, bouwjaar ±3", "midden", _same_family),
    Rung(3, "zelfde segment: framemateriaal, remtype, versnellingen, bouwjaarband", "laag", _same_segment),
]


def select_comps(subject: Subject, candidates: Sequence[CompCandidate]) -> Optional[CompSet]:
    """De hoogste trede die genoeg comps oplevert. Haalt geen enkele trede de
    drempel, dan wint de breedste trede die überhaupt iets vindt — met
    'indicatief' als vertrouwen, want dat is wat het dan is."""
    found: list[CompSet] = []
    for rung in RUNGS:
        comps = tuple(c for c in candidates if rung.matches(subject, c))
        if not comps:
            continue
        comp_set = CompSet(rung.number, rung.description, rung.confidence, comps)
        if comp_set.n >= MIN_COMPS_FOR_A_HARD_NUMBER:
            return comp_set
        found.append(comp_set)
    if not found:
        return None
    widest = max(found, key=lambda s: s.n)
    return CompSet(widest.rung, widest.description, "indicatief", widest.comps)


# --- Database -------------------------------------------------------------


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def fetch_comp_candidates(
    conn: sqlite3.Connection,
    *,
    window_days: int = DEFAULT_COMP_WINDOW_DAYS,
    query: Optional[str] = None,
    as_of: Optional[datetime] = None,
) -> list[CompCandidate]:
    """Alle advertenties met een bruikbare vraagprijs uit het meetvenster, met
    hun specs erbij. Filteren op vergelijkbaarheid gebeurt níet hier maar in
    select_comps(): dat is rekenwerk en moet zonder database testbaar blijven.

    Bied-advertenties blijven buiten de comps. De prijs in `listing` is bij een
    bod de stand van het bieden, en of er al geboden is weet deze tabel niet —
    dat is precies de onzekerheid die append_reference_price_observations() ook
    al buiten de waarderingsdata houdt."""
    sql = [
        "SELECT item_id, title, description, price_eur, url, is_bid, days_online,",
        "       disappeared_at, last_seen, first_seen",
        "FROM listing",
        "WHERE price_eur IS NOT NULL AND price_eur > 0 AND is_bid = 0",
    ]
    params: list = []
    if window_days > 0:
        sql.append("AND (last_seen IS NULL OR last_seen >= ?)")
        params.append(_iso_days_ago(window_days))
    if query:
        sql.append("AND query = ?")
        params.append(query)
    rows = conn.execute("\n".join(sql), params).fetchall()

    specs_by_listing: dict[str, dict[str, str]] = {}
    for spec_row in conn.execute("SELECT listing_id, key, value FROM spec").fetchall():
        specs_by_listing.setdefault(spec_row["listing_id"], {})[spec_row["key"]] = spec_row["value"]

    as_of = as_of or datetime.now(timezone.utc)
    return [
        candidate_from_row(row, specs_by_listing.get(row["item_id"], {}), as_of=as_of)
        for row in rows
    ]


def _derive_days_online(first_seen: Optional[str], as_of: datetime) -> Optional[int]:
    """Dagen sinds first_seen — sinds wíj de advertentie zagen, niet de
    plaatsdatum op Marktplaats (dat veld, `posted_date`, lezen we hier niet:
    het echte formaat ervan is niet vastgesteld, zie CLAUDE.md). None als
    first_seen ontbreekt of onleesbaar is, dezelfde twee vangnetten als
    sweep_disappeared() in db.py: import_legacy() kan een lege string
    wegschrijven, en een onleesbare datum mag deze taxatie niet laten
    crashen. Een stille NULL in de database blijft zo een stille NULL —
    er wordt niets verzonnen."""
    if not first_seen:
        return None
    try:
        delta = as_of - db._parse_iso(first_seen)
    except ValueError:
        return None
    return delta.days


def candidate_from_row(
    row, specs: dict[str, str], *, as_of: Optional[datetime] = None
) -> CompCandidate:
    """Eén databaserij als comp-kandidaat. De groepsettier wordt hier opnieuw
    uit de tekst afgeleid in plaats van uit `spec` gelezen: extract_specs()
    laat de groepset met opzet aan detect_groupset() over, en een afgeleide
    waarde hoort niet in de ruwe tabellen.

    days_online komt uit de kolom als die er staat. Staat hij op NULL en is
    de advertentie nog online, dan wordt hij hier afgeleid uit first_seen —
    dat gebeurt alleen bij het lezen, nooit teruggeschreven, dus de ruwe
    kolom blijft een ruwe waarneming. Een verdwenen advertentie zonder
    days_online (de parse in sweep_disappeared() faalde toen) wordt hier niet
    alsnog berekend: dat zou een ander getal kunnen geven dan wat op het
    moment van verdwijnen vastgesteld is."""
    title = row["title"] or ""
    description = row["description"] or ""
    _, tier = mp.detect_groupset(f"{title} {description}")
    disappeared = row["disappeared_at"] is not None
    days_online = row["days_online"]
    if days_online is None and not disappeared:
        days_online = _derive_days_online(row["first_seen"], as_of or datetime.now(timezone.utc))
    return CompCandidate(
        item_id=row["item_id"],
        title=title,
        url=row["url"] or "",
        price_eur=float(row["price_eur"]),
        text=f"{title} {description}".lower(),
        is_bid=bool(row["is_bid"]),
        days_online=days_online,
        disappeared=disappeared,
        specs=specs,
        groupset_tier=tier,
    )


def fetch_component_prices(conn: sqlite3.Connection, model_id: int) -> list[float]:
    """De waargenomen prijzen voor één onderdeel. Leeg is een geldig antwoord:
    dan weegt E3 voor dat onderdeel niet mee."""
    rows = conn.execute(
        "SELECT price_eur FROM component_price WHERE model_id = ? AND price_eur IS NOT NULL",
        (model_id,),
    ).fetchall()
    return [float(row["price_eur"]) for row in rows]


def load_owned_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM owned_item ORDER BY id").fetchall()


def upsert_owned_item(
    conn: sqlite3.Connection,
    *,
    kind: str,
    label: str,
    specs: Optional[dict] = None,
    acquired_price_eur: Optional[float] = None,
    notes: Optional[str] = None,
) -> int:
    """Eigen bezit bijwerken op (kind, label). Er staat geen UNIQUE op die
    twee kolommen — het schema is al uitgeleverd, en een migratie toevoegen
    voor iets dat één rij per fiets betreft is zwaarder dan deze lookup."""
    row = conn.execute(
        "SELECT id FROM owned_item WHERE kind = ? AND label = ?", (kind, label)
    ).fetchone()
    specs_json = json.dumps(specs or {}, ensure_ascii=False, sort_keys=True)
    if row is None:
        cursor = conn.execute(
            "INSERT INTO owned_item (kind, label, acquired_price_eur, specs_json, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, label, acquired_price_eur, specs_json, notes),
        )
        conn.commit()
        return int(cursor.lastrowid)
    conn.execute(
        "UPDATE owned_item SET acquired_price_eur = ?, specs_json = ?, notes = ? WHERE id = ?",
        (acquired_price_eur, specs_json, notes, row["id"]),
    )
    conn.commit()
    return int(row["id"])


def save_valuation(conn: sqlite3.Connection, valuation: Valuation) -> int:
    """Schrijf de taxatie weg in `valuation` + `valuation_evidence`, en
    nergens anders. Dit is de enige functie hier die schrijft; `listing_price`
    en `component_price` blijven onaangeraakt (§5)."""
    cursor = conn.execute(
        """
        INSERT INTO valuation (subject_type, subject_id, scenario, low_eur, mid_eur,
                               high_eur, confidence, method_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            valuation.subject_type,
            valuation.subject_id,
            valuation.scenario,
            valuation.low_eur,
            valuation.mid_eur,
            valuation.high_eur,
            valuation.confidence,
            valuation.method_version,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    valuation_id = int(cursor.lastrowid)
    for item in valuation.evidence:
        conn.execute(
            """
            INSERT INTO valuation_evidence (valuation_id, kind, ref_id, ref_url,
                                            price_eur, weight, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (valuation_id, item.kind, item.ref_id, item.ref_url,
             item.price_eur, item.weight, item.note),
        )
    conn.commit()
    return valuation_id


# --- mijn_fiets.md --------------------------------------------------------


@dataclass(frozen=True)
class OwnerBike:
    """Wat `mijn_fiets.md` over de eigen fiets vaststelt."""

    label: str
    specs: dict[str, str]
    wheelset_label: Optional[str] = None
    wheelset_price_eur: Optional[float] = None


SCORING_BLOCK_RE = re.compile(r"##\s*Voor de scoring.*?```(.*?)```", re.S)
TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$", re.M)
EURO_RE = re.compile(r"€\s*(\d+(?:[.,]\d+)?)")


def _plain(value: str) -> str:
    """Markdown-nadruk eruit; de tabel zet halve waarden vet."""
    return value.replace("**", "").replace("*", "").strip()


def parse_owner_bike(markdown_text: str) -> OwnerBike:
    """`mijn_fiets.md` → het blok waarop getaxeerd wordt.

    Leest twee dingen: de regel `| Model | ... |` uit de intaketabel en het
    `Voor de scoring`-blok onderaan. Dat blok is met opzet de bron voor de
    specs: het is het enige stuk van dat document dat als sleutel/waarde
    bedoeld is. Klopt de structuur niet, dan volgt een duidelijke fout — hier
    iets van maken wat er niet staat is precies hoe een verkeerde taxatie
    ontstaat."""
    block = SCORING_BLOCK_RE.search(markdown_text)
    if not block:
        raise ValueError(
            "geen 'Voor de scoring'-blok gevonden in mijn_fiets.md — zonder dat blok "
            "is niet vast te stellen wat er getaxeerd moet worden"
        )

    specs: dict[str, str] = {}
    for line in block.group(1).splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and value:
            specs[key] = value

    rows = {_plain(key): _plain(value) for key, value in TABLE_ROW_RE.findall(markdown_text)}
    model = rows.get("Model")
    if not model:
        raise ValueError("geen 'Model'-regel gevonden in de intaketabel van mijn_fiets.md")
    # "Giant Defy Composite, modeljaar 2012" -> "Giant Defy Composite"; het
    # modeljaar komt uit het scoringsblok, waar het als getal staat.
    label = model.split(",")[0].strip()

    wheelset = rows.get("Wielset (gemonteerd)")
    wheelset_price = None
    if wheelset:
        found = EURO_RE.search(wheelset)
        if found:
            wheelset_price = float(found.group(1).replace(",", "."))

    return OwnerBike(
        label=label,
        specs=specs,
        wheelset_label=wheelset.split(",")[0].strip() if wheelset else None,
        wheelset_price_eur=wheelset_price,
    )


def _int_prefix(value: Optional[str]) -> Optional[int]:
    """Het getal voor de eventuele toelichting: "5   (Ultegra, ...)" -> 5."""
    if not value:
        return None
    match = re.match(r"\s*(\d+)", value)
    return int(match.group(1)) if match else None


# Binnen één modelfamilie zit vaak een duurdere uitvoering met bijna dezelfde
# naam. mijn_fiets.md en §4 van het plan zeggen het voor deze fiets expliciet:
# Composite is Giants instapcarbon, Advanced de laag erboven, en een
# Advanced-advertentie trekt de schatting omhoog. Dit is een feit over het
# model, niet over de waarderingsmethode, dus het staat hier als data.
TRIM_CONFUSIONS = {"composite": ("advanced",)}


def subject_from_owner_bike(bike: OwnerBike) -> Subject:
    """De zoekcriteria voor de comps, afgeleid uit wat de eigenaar heeft
    vastgesteld. Het merk valt buiten de patronen: verkopers schrijven "Giant
    Defy" net zo vaak als "Defy", en het model alleen is al onderscheidend
    genoeg."""
    words = bike.label.split()
    # "Giant Defy Composite" -> familie "defy", model "defy composite".
    model_words = [word.lower() for word in words[1:]] if len(words) > 1 else [w.lower() for w in words]
    family = model_words[0] if model_words else bike.label.lower()
    frame_tier = (bike.specs.get("frame_tier") or "").split()[0].lower() if bike.specs.get("frame_tier") else ""

    speeds = _int_prefix(bike.specs.get("speeds"))
    return Subject(
        label=bike.label,
        kind="bike",
        model_patterns=tuple(model_words),
        family_patterns=(family,),
        exclude_patterns=TRIM_CONFUSIONS.get(frame_tier, ()),
        model_year=_int_prefix(bike.specs.get("model_year")),
        groupset_tier=_int_prefix(bike.specs.get("groupset_tier")),
        frame_material=(bike.specs.get("frame_material") or "").strip().lower() or None,
        brake_type=(bike.specs.get("brake_type") or "").strip().lower() or None,
        speeds=speeds,
        segment_speeds=(speeds, speeds + 1) if speeds else (10, 11),
    )


# --- De taxatie zelf ------------------------------------------------------


@dataclass(frozen=True)
class Component:
    """Een onderdeel voor E3, of een post die bij een scenario opgeteld wordt."""

    label: str
    observed_prices: tuple[float, ...] = ()
    acquired_price_eur: Optional[float] = None

    @property
    def market_value(self) -> Optional[float]:
        """De mediaan van wat het onderdeel los doet. Zonder waarnemingen:
        geen waarde. De nieuwprijs is hier met opzet géén vervanging — wat een
        wielset ooit kostte zegt niets over wat hij nu opbrengt."""
        if not self.observed_prices:
            return None
        return float(statistics.median(self.observed_prices))


def value_subject(
    subject: Subject,
    candidates: Sequence[CompCandidate],
    *,
    subject_type: str = "owned_item",
    subject_id: str = "",
    scenario: str = "",
    components: Sequence[Component] = (),
    extras: Sequence[Component] = (),
    negotiation: Optional[tuple[float, int, int]] = None,
) -> Optional[Valuation]:
    """E1 + E2 + E3 gemengd tot één band met bewijsregels.

    `components` zijn de onderdelen voor E3 (som der delen). `extras` zijn
    posten die bovenop de comps komen omdat ze in de comps niet zitten — de
    carbon wielset in scenario A bijvoorbeeld; daarvan telt alleen het deel mee
    dat een koper van een complete fiets er echt voor betaalt.

    Geeft None als er geen comps zijn: dan is er niets om op te taxeren, en een
    getal uit de losse onderdelen zou doen alsof dat wel zo is."""
    comp_set = select_comps(subject, candidates)
    if comp_set is None:
        return None

    evidence: list[Evidence] = []
    asking = price_band(comp_set.prices)
    # Het gewicht op elke bewijsregel is wat die regel in de menging heeft
    # meegeteld; voor E1 hangt dat aan de trede en aan hoeveel comps er zijn.
    comps_weight = CONFIDENCE_WEIGHT[comp_set.confidence] * min(comp_set.n, 10) / 10
    evidence.append(
        Evidence(
            kind="comp",
            note=(
                f"E1: trede {comp_set.rung} ({comp_set.description}), n={comp_set.n}, "
                f"mediaan vraagprijs €{asking[1]:.0f} "
                f"(20e-80e percentiel €{asking[0]:.0f}-€{asking[2]:.0f})"
            ),
            price_eur=asking[1],
            weight=comps_weight,
        )
    )
    for comp in sorted(comp_set.comps, key=lambda c: c.price_eur)[:10]:
        evidence.append(
            Evidence(
                kind="comp",
                note=f"comp: {comp.title[:70]}",
                price_eur=comp.price_eur,
                ref_id=comp.item_id,
                ref_url=comp.url,
            )
        )

    if negotiation is not None:
        factor, n_quick, n_stale = negotiation
        evidence.append(
            Evidence(
                kind="depreciation",
                note=(
                    f"E2: gemeten correctie vraagprijs → verkoopprijs ×{dutch(factor)} "
                    f"(mediaan van {n_quick} snel verdwenen advertenties tegen "
                    f"{n_stale} blijvers — verdwenen óf nog altijd online, 60+ dagen "
                    "sinds we ze zagen; verdwenen is niet hetzelfde als verkocht)"
                ),
                weight=factor,
            )
        )
        corrected = scale_band(asking, factor)
    else:
        # Aparte namen, want verderop staan low/mid/high voor bedragen in euro's
        # en dit zijn factoren.
        low_factor, mid_factor, high_factor = NEGOTIATION_DEFAULT
        evidence.append(
            Evidence(
                kind="depreciation",
                note=(
                    f"E2: heuristische correctie vraagprijs → verkoopprijs "
                    f"×{dutch(mid_factor, 3)} ({(1 - high_factor) * 100:.0f}-"
                    f"{(1 - low_factor) * 100:.0f}% onderhandelingsruimte, nog niet "
                    f"gemeten — daarvoor zijn ≥{EMPIRICAL_MIN_N} verdwenen én "
                    f"≥{EMPIRICAL_MIN_N} blijvende advertenties nodig)"
                ),
                weight=mid_factor,
            )
        )
        corrected = (asking[0] * low_factor, asking[1] * mid_factor, asking[2] * high_factor)

    parts_values: list[float] = []
    for component in components:
        value = component.market_value
        if value is None:
            evidence.append(
                Evidence(
                    kind="parts",
                    note=f"E3: geen prijswaarnemingen voor {component.label}; telt niet mee",
                    weight=0.0,
                )
            )
            continue
        parts_values.append(value)
        evidence.append(
            Evidence(
                kind="parts",
                note=f"E3: {component.label}, mediaan losse prijs €{value:.0f}",
                price_eur=value,
            )
        )

    parts_mid: Optional[float] = None
    parts_weight = 0.0
    if parts_values:
        parts_mid = parts_total(parts_values)
        parts_weight = PARTS_WEIGHT * len(parts_values) / max(len(components), 1)
        evidence.append(
            Evidence(
                kind="parts",
                note=(
                    f"E3: som der delen €{sum(parts_values):.0f} × bundelfactor "
                    f"{dutch(BUNDLE_FACTOR)} = €{parts_mid:.0f} (bundelfactor is een "
                    "heuristiek, geen meting)"
                ),
                price_eur=parts_mid,
                weight=parts_weight,
            )
        )

    mid = weigh(corrected[1], comps_weight, parts_mid, parts_weight)
    if mid is None:
        return None
    low, high = corrected[0], corrected[2]
    if parts_mid is not None:
        low, high = min(low, parts_mid), max(high, parts_mid)

    for extra in extras:
        value = extra.market_value
        if value is None:
            evidence.append(
                Evidence(
                    kind="adjustment",
                    note=(
                        f"{extra.label}: geen prijswaarnemingen, dus niet in het bedrag "
                        "verwerkt — de opbrengst ligt hoger dan hier staat"
                    ),
                    weight=0.0,
                )
            )
            continue
        share = value * UPGRADE_RECOVERY_WITH_BIKE
        evidence.append(
            Evidence(
                kind="adjustment",
                note=(
                    f"{extra.label}: los €{value:.0f}, waarvan €{share:.0f} "
                    f"({UPGRADE_RECOVERY_WITH_BIKE:.0%}) meetelt bij een complete fiets — "
                    "kopers betalen zelden mee aan andermans upgrades (heuristiek)"
                ),
                price_eur=share,
                weight=UPGRADE_RECOVERY_WITH_BIKE,
            )
        )
        mid += share
        low += share
        high += share

    # select_comps() heeft het vertrouwen hier al op 'indicatief' gezet; dit is
    # de regel die uitlegt waarom, zodat het getal niet zonder waarschuwing
    # doorreist naar het rapport.
    confidence = comp_set.confidence
    if comp_set.n < MIN_COMPS_FOR_A_HARD_NUMBER:
        evidence.append(
            Evidence(
                kind="adjustment",
                note=(
                    f"n={comp_set.n} ligt onder de {MIN_COMPS_FOR_A_HARD_NUMBER} comps die "
                    "nodig zijn voor een hard getal; lees dit als een richting, niet als "
                    "een prijs"
                ),
                weight=0.0,
            )
        )

    low, mid, high = sorted((low, mid, high))
    return Valuation(
        subject_type=subject_type,
        subject_id=subject_id,
        scenario=scenario,
        low_eur=low,
        mid_eur=mid,
        high_eur=high,
        confidence=confidence,
        evidence=tuple(evidence),
    )


# --- CLI ------------------------------------------------------------------


SCENARIOS = {
    "a": "compleet met carbon wielset",
    "b": "compleet met originele wielen, carbon wielset apart",
}


def format_valuation(valuation: Valuation, label: Optional[str] = None) -> str:
    lines = [
        f"Taxatie {label or valuation.subject_id or valuation.subject_type}"
        + (f" — scenario {valuation.scenario}" if valuation.scenario else ""),
        f"  bandbreedte   €{valuation.low_eur:.0f} – €{valuation.high_eur:.0f}"
        f"   midden €{valuation.mid_eur:.0f}   vertrouwen: {valuation.confidence}",
        "  onderbouwing:",
    ]
    for item in valuation.evidence:
        price = f" €{item.price_eur:.0f}" if item.price_eur is not None else ""
        lines.append(f"   - [{item.kind}]{price} {item.note}")
        if item.ref_url:
            lines.append(f"     {item.ref_url}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Taxeer de eigen fiets op de comps in koopjes.db (fase 3).",
    )
    parser.add_argument("--db", default="koopjes.db", help="pad naar de database (default: koopjes.db)")
    parser.add_argument(
        "--mijn-fiets", default="mijn_fiets.md",
        help="intakebestand met de eigen fiets (default: mijn_fiets.md)",
    )
    parser.add_argument(
        "--window-days", type=int, default=DEFAULT_COMP_WINDOW_DAYS,
        help=f"hoe ver terug comps meetellen (default: {DEFAULT_COMP_WINDOW_DAYS}, 0 = alles)",
    )
    parser.add_argument(
        "--query", default=None,
        help="beperk de comps tot advertenties uit één crawl-zoekopdracht",
    )
    parser.add_argument(
        "--scenario", choices=sorted(SCENARIOS), action="append",
        help="welk verkoopscenario (herhaalbaar; default: allebei)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="alleen tonen, niets naar de database schrijven",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        with open(args.mijn_fiets, encoding="utf-8") as f:
            bike = parse_owner_bike(f.read())
    except FileNotFoundError:
        print(f"fout: {args.mijn_fiets} niet gevonden", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"fout: {exc}", file=sys.stderr)
        return 1

    subject = subject_from_owner_bike(bike)
    conn = db.connect(args.db)
    try:
        # --dry-run raakt de database niet aan, dus ook `owned_item` niet; de
        # taxatie draagt dan geen rij-id, wat klopt: er is niets opgeslagen om
        # naar te verwijzen.
        owned_id = None
        if not args.dry_run:
            owned_id = upsert_owned_item(
                conn,
                kind="bike",
                label=bike.label,
                specs=bike.specs,
                notes=f"geïmporteerd uit {args.mijn_fiets}",
            )
            if bike.wheelset_label:
                upsert_owned_item(
                    conn,
                    kind="wheelset",
                    label=bike.wheelset_label,
                    acquired_price_eur=bike.wheelset_price_eur,
                    notes=f"geïmporteerd uit {args.mijn_fiets}",
                )

        candidates = fetch_comp_candidates(
            conn, window_days=args.window_days, query=args.query
        )
        print(
            f"{len(candidates)} advertenties met een vraagprijs in het meetvenster",
            file=sys.stderr,
        )
        negotiation = empirical_negotiation_factor(candidates)

        # Zonder waarnemingen van losse wielsets in de database blijft dit een
        # post zonder bedrag — zichtbaar in de bewijsregels, niet stilzwijgend
        # weggelaten. Vullen doe je met een eigen crawl op de wielset.
        wheelset = Component(label=bike.wheelset_label or "carbon wielset")

        scenarios = args.scenario or sorted(SCENARIOS)
        results: list[Valuation] = []
        for key in scenarios:
            valuation = value_subject(
                subject,
                candidates,
                subject_type="owned_item",
                subject_id=str(owned_id) if owned_id else "",
                scenario=SCENARIOS[key],
                extras=(wheelset,) if key == "a" else (),
                # Zonder deze regel werd de gemeten factor wel uitgerekend maar
                # nooit gebruikt, en viel de CLI altijd terug op de heuristiek —
                # terwijl upgrade.py en het rapport hem wél doorgaven.
                negotiation=negotiation,
            )
            if valuation is None:
                print(
                    f"Geen taxatie voor scenario {key}: geen vergelijkbare advertenties in "
                    f"{args.db}. Crawl eerst met --query op dit model, dan opnieuw.",
                    file=sys.stderr,
                )
                continue
            # subject_id is de owned_item-rij; het label maakt de uitvoer leesbaar.
            print(format_valuation(valuation, label=bike.label))
            print()
            results.append(valuation)
            if not args.dry_run:
                save_valuation(conn, valuation)

        if bike.wheelset_price_eur and bike.wheelset_label:
            print(
                f"Wielset {bike.wheelset_label}: nieuwprijs €{bike.wheelset_price_eur:.0f}. "
                "Wat daarvan terugkomt is nog niet te zeggen — daarvoor moeten er "
                "waarnemingen van losse wielsets in de database staan."
            )
        return 0 if results else 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
