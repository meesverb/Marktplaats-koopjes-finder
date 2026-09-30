"""Welke fiets is het: merk, model(familie), bouwjaar en tijdperk. Voor de
vergelijking op /racefietsen (racebikes.py): een fiets wordt vergeleken met
hetzelfde model uit dezelfde jaren, niet met alles wat dezelfde groepset
heeft.

Waarom (de eigenaar, 30-09-2026): "een carbonfiets uit 2024 is niet te
vergelijken met een uit 2014, net als Di2 of Ultegra". De oude vergelijking
(upgrade.segment_keys: framemateriaal + groepsettier + remtype) zette een
Ultegra-fiets van 2012 naast een van 2023.

- **Merk**: zoals de slapers het herkennen (sleepers.named_brand(): de
  catalogus plus een paar merken uit de crawl).
- **Model**: het eerste woord van de modelnamen per merk in
  reference_bike_catalog.csv ("Defy", "TCR", "Émonda", "CAAD", "Synapse"),
  als los woord in de titel (of anders de tekst). Staat het merk er niet
  bij maar hoort het modelwoord bij precies één merk ("Emonda"), dan is het
  dat merk. Geen modelwoord gevonden: geen model — liever geen vergelijking
  dan een verkeerde.
- **Bouwjaar**: uit de tekst ("bouwjaar 2016") of de titel (upgrade.listing_specs()).
- **Tijdperk** als het bouwjaar ontbreekt: wat de advertentie zelf zegt en
  waarin fietsen van verschillende jaren van elkaar verschillen — schijf- of
  velgrem, elektronisch schakelen (Di2, eTap, AXS) en het aantal
  versnellingen. Bewust zonder jaartallen erbij: welke generatie wanneer
  uitkwam is een marktfeit dat hier niet nagezocht is (CLAUDE.md).

Alleen lezen; geen verzoeken.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import racefiets_jev as mp
import sleepers
import upgrade as up

CATALOG_PATH = Path(__file__).resolve().parent / "reference_bike_catalog.csv"
# De referentiemodellen met een patroon (fase 7): "Giant Defy Composite 1",
# "Trek Domane AL 2", ... Een advertentie die er een raakt, hangt aan dat
# model; de andere advertenties van hetzelfde model zijn zijn vergelijking
# (de eigenaar, 30-09-2026: "gelinkt aan een fietsmodel, en als daar 10
# andere aan hangen, vergelijken of hij goedkoop is").
REFERENCE_PATH = Path(__file__).resolve().parent / "reference_bikes.csv"


@lru_cache(maxsize=None)
def reference_rows(path: str = str(REFERENCE_PATH)) -> tuple:
    return tuple(mp.load_reference_data(path))


def reference_model(listing: mp.Listing) -> Optional[str]:
    """Het eerste referentiemodel waarvan het patroon past, in bestandsvolgorde
    — dezelfde regel als racefiets_jev.apply_reference_data()."""
    haystack = f"{listing.title} {listing.description}"
    return next((row["label"] for row in reference_rows() if row["regex"].search(haystack)), None)
# Eerste woorden van modelnamen die geen model zijn maar een toevoeging of
# een algemeen woord ("Speed Concept" is wel een model, maar "speed" staat in
# elke tweede titel).
NOT_A_FAMILY = frozenset({
    "pro", "speed", "ride", "gran", "road", "race", "sport", "s-works", "new", "sl", "team", "comp",
    "elite", "expert", "carbon", "alu", "disc", "women", "men", "lady", "junior", "kids", "bike",
    # Modelnamen in de catalogus die ook gewone woorden in een advertentie
    # zijn ("maat 56" werd een Pinarello MAAT, 30-09-2026).
    "maat", "cross", "classic", "newest", "track", "full", "aluminium", "arena", "san", "sara", "comet",
    "custom", "super", "six", "via", "mono", "ultra", "pure", "air", "arte", "ace", "master", "move",
    "prima", "world", "premium", "luna", "zero", "zero.", "strada", "pista", "terra", "aqua", "dama",
    "gravel", "touring", "fusion", "donna", "mares", "grade", "rose", "pro-", "ferrari", "nero", "prince",
    "paris", "cx", "cx-", "she", "vega", "king", "finest", "feather", "supreme", "plasma", "facet",
    "power-eps", "eps", "ultraligh", "impulso", "mach", "otg", "clx.",
})
# Woorden die direct na een merk staan maar geen model zijn ("Trek racefiets").
NOT_A_MODEL_AFTER_BRAND = NOT_A_FAMILY | frozenset({
    "racefiets", "racefietsen", "wielrenfiets", "racer", "fiets", "heren", "dames", "met", "frame", "maat",
    "size", "framemaat", "wielen", "shimano", "sram", "campagnolo", "ultegra", "tiagra", "sora", "claris",
    "dura", "dura-ace", "rival", "force", "red", "apex", "nieuw", "nieuwe", "zgan", "gebruikt", "limited",
    "edition", "team", "aero", "gravel", "gravelbike", "cyclocross", "tijdritfiets", "triathlon", "koersfiets",
    "vintage", "retro", "oude", "mooie", "goede", "te", "koop", "en", "de", "het", "van", "voor", "in",
})
ELECTRONIC_RE = re.compile(r"\b(di2|etap|e-tap|axs)\b", re.I)


def fold(text: str) -> str:
    """Kleine letters zonder accenten: "Émonda" en "emonda" zijn hetzelfde woord."""
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()


def _family_word(model: str) -> Optional[str]:
    words = fold(model).split()
    if not words:
        return None
    word = words[0].strip(".,")
    # "CAAD12", "CAAD10" en "CAAD8" zijn één lijn; "CR1" of "G6" zonder cijfer is niets.
    stripped = word.rstrip("0123456789")
    if len(stripped) >= 3:
        word = stripped
    if len(word) < 2 or word in NOT_A_FAMILY or word.isdigit():
        return None
    return word


@lru_cache(maxsize=None)
def families(path: str = str(CATALOG_PATH)) -> dict[str, frozenset]:
    """{merk (klein): modelwoorden} uit de catalogus."""
    found: dict[str, set] = {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                brand, word = fold((row.get("brand") or "").strip()), _family_word(row.get("model") or "")
                if brand and word:
                    found.setdefault(brand, set()).add(word)
    except (OSError, csv.Error):
        return {}
    return {b: frozenset(w) for b, w in found.items()}


@lru_cache(maxsize=None)
def _owner_of() -> dict[str, str]:
    """{modelwoord: merk} voor woorden die bij precies één merk horen."""
    owners: dict[str, set] = {}
    for brand, words in families().items():
        for w in words:
            owners.setdefault(w, set()).add(brand)
    return {w: next(iter(b)) for w, b in owners.items() if len(b) == 1 and len(w) >= 4}


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9][a-z0-9\-]*", fold(text)))


@dataclass(frozen=True)
class Identity:
    brand: Optional[str]
    family: Optional[str]
    material: Optional[str]
    year: Optional[int]
    disc: Optional[bool]  # None: remtype onbekend
    electronic: bool
    speeds: Optional[int]
    tier: Optional[int]
    reference: Optional[str] = None  # referentiemodel uit reference_bikes.csv

    @property
    def model(self) -> Optional[str]:
        return f"{self.brand} {self.family}" if self.brand and self.family else None

    @property
    def group(self) -> Optional[str]:
        """Waar hij aan hangt: het referentiemodel, anders merk + model."""
        return self.reference or (self.model.title() if self.model else None)

    def label(self) -> str:
        parts = [self.group or "model onbekend"]
        if self.year:
            parts.append(str(self.year))
        return " ".join(parts)


def identify(listing: mp.Listing) -> Identity:
    title, text = listing.title or "", mp.spec_text(listing)
    brand = sleepers.named_brand(title) or sleepers.named_brand(text)
    brand = fold(brand) if brand else None
    title_words, text_words = _words(title), _words(text)
    family = None
    if brand and brand in families():
        known = families()[brand]
        family = next((w for w in sorted(known) if w in title_words), None) or \
            next((w for w in sorted(known) if w in text_words), None)
    if family is None:
        # Geen merk (of geen model van dat merk) in de titel: een modelwoord
        # dat maar bij één merk hoort, zegt het merk ook. Ook als er een merk
        # staat dat de catalogus niet kent ("S-Works Tarmac").
        owners = _owner_of()
        hit = next((w for w in sorted(title_words) if w in owners), None)
        if hit and (brand is None or owners[hit] == brand or brand not in families()):
            brand, family = owners[hit], hit
    if family is None and brand:
        # Een model dat de catalogus niet kent ("Canyon Grail", "Koga
        # Kinsei"): het woord direct na het merk in de titel, als dat een
        # woord is en geen algemene term.
        after = re.search(re.escape(brand) + r"\s+([a-z][a-z\-]{2,})", fold(title))
        if after and after.group(1) not in NOT_A_MODEL_AFTER_BRAND:
            family = after.group(1)
    specs, _ = up.listing_specs(listing)
    year = specs.get("model_year")
    route = up.brake_route(specs.get("brake_type"))
    speeds = specs.get("speeds")
    return Identity(
        brand=brand, family=family, material=specs.get("frame_material"),
        year=int(year) if year and str(year).isdigit() else None,
        disc=True if route == up.ROUTE_DISC else False if route == up.ROUTE_RIM else None,
        electronic=bool(ELECTRONIC_RE.search(text)),
        speeds=int(speeds) if speeds and str(speeds).isdigit() else None,
        tier=listing.groupset_tier,
        reference=reference_model(listing),
    )


# Hoeveel jaar een vergelijkbare fiets mag schelen.
YEAR_WINDOW = 2
MIN_SAME_MODEL = 3
MIN_SAME_BUILD = 5


def same_era(a: Identity, b: Identity) -> bool:
    """Zonder bouwjaar: zelfde tijdperk volgens wat beide advertenties zeggen.
    Het remtype moet bij allebei bekend en gelijk zijn (schijf of velg is
    het duidelijkste verschil tussen oud en nieuw), elektronisch schakelen
    ook gelijk, en het aantal versnellingen gelijk als beide het noemen."""
    if a.disc is None or b.disc is None or a.disc != b.disc or a.electronic != b.electronic:
        return False
    return a.speeds is None or b.speeds is None or a.speeds == b.speeds


def close_years(a: Identity, b: Identity) -> bool:
    return a.year is not None and b.year is not None and abs(a.year - b.year) <= YEAR_WINDOW


def same_material(a: Identity, b: Identity) -> bool:
    return a.material is None or b.material is None or a.material == b.material


def comparables(me: Identity, same_model: list, same_build: list, same_reference: list = ()) -> tuple[str, list]:
    """(niveau, [(Identity, prijs, extra), ...]) van de beste trede met genoeg
    fietsen. `same_model`: de fietsen met hetzelfde merk en model,
    `same_build`: die met hetzelfde materiaal, groepsettier en remtype
    (Pool geeft ze), beide zonder de fiets zelf.

    1. zelfde merk en model, bouwjaar ±2 (beide bekend), zelfde materiaal;
    2. zelfde merk en model, waarvan een van beide geen bouwjaar heeft: zelfde
       tijdperk (same_era()), plus die van ±2 jaar;
    3. ander model, maar zelfde materiaal, groepsettier en remtype, bouwjaar ±2.
    4. alleen zelfde merk en model, als van de fiets zelf jaar én remtype
       onbekend zijn: "model, jaar onbekend" — onzeker, de pagina toont het
       niet als koopje (UNCERTAIN_LEVELS).
    Daarna niets: een mediaan van alle racefietsen is appels met peren.

    Nog vóór 1: hetzelfde referentiemodel (reference_bikes.csv), ±2 jaar als
    beide een jaar noemen — dat is de koppeling die de eigenaar bedoelt.
    `same_reference` komt als eerste; zonder referentiemodel is hij leeg."""
    if same_reference:
        ref_year = [c for c in same_reference if close_years(me, c[0])]
        if me.year is not None and len(ref_year) >= MIN_SAME_MODEL:
            return "referentiemodel+jaar", ref_year
        usable = ref_year + [c for c in same_reference if me.year is None or c[0].year is None]
        if len(usable) >= MIN_SAME_MODEL:
            return "referentiemodel", usable
    if me.model:
        same = [c for c in same_model if same_material(me, c[0])]
        by_year = [c for c in same if close_years(me, c[0])]
        if me.year is not None and len(by_year) >= MIN_SAME_MODEL:
            return "model+jaar", by_year
        era = by_year + [c for c in same if (me.year is None or c[0].year is None) and same_era(me, c[0])]
        if len(era) >= MIN_SAME_MODEL:
            return "model+tijdperk", era
    if me.year is not None and me.material and me.tier is not None and me.disc is not None:
        build = [c for c in same_build if close_years(me, c[0])]
        if len(build) >= MIN_SAME_BUILD:
            return "opbouw+jaar", build
    if me.model and me.year is None and me.disc is None:
        same = [c for c in same_model if same_material(me, c[0])]
        if len(same) >= MIN_SAME_MODEL:
            return "model, jaar onbekend", same
    return "", []


UNCERTAIN_LEVELS = frozenset({"model, jaar onbekend"})


class Pool:
    """De vergelijkingsfietsen, per model en per opbouw geïndexeerd: met
    ~20.000 fietsen is elke fiets tegen alle andere te traag."""

    def __init__(self, items: list):
        self.by_model: dict = {}
        self.by_build: dict = {}
        self.by_reference: dict = {}
        # Wie al herkend is, hoeft dat voor de actieve fietsen niet nog eens.
        self.identity_of: dict = {item[2][0]: item[0] for item in items}
        for item in items:
            ident = item[0]
            if ident.reference:
                self.by_reference.setdefault(ident.reference, []).append(item)
            if ident.model:
                self.by_model.setdefault(ident.model, []).append(item)
            if ident.material and ident.tier is not None and ident.disc is not None:
                self.by_build.setdefault((ident.material, ident.tier, ident.disc), []).append(item)

    def comparables(self, me: Identity, exclude: str) -> tuple[str, list]:
        """Zonder de fiets zelf (`exclude`: zijn item_id, het eerste veld van `extra`)."""
        same_model = [c for c in self.by_model.get(me.model, ()) if c[2][0] != exclude]
        same_build = [c for c in self.by_build.get((me.material, me.tier, me.disc), ()) if c[2][0] != exclude]
        same_reference = [c for c in self.by_reference.get(me.reference, ()) if c[2][0] != exclude]
        return comparables(me, same_model, same_build, same_reference)

    def linked(self, me: Identity) -> int:
        """Hoeveel advertenties (de laatste 180 dagen) aan hetzelfde model hangen."""
        if me.reference:
            return len(self.by_reference.get(me.reference, ()))
        return len(self.by_model.get(me.model, ())) if me.model else 0
