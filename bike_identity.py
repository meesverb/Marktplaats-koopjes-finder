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
- **Uitvoering**: de 1-3 woorden direct na het model in de titel die op een
  uitvoering lijken ("SL6", "Advanced 2", "CF SLX 8"). Model + uitvoering is
  waar een fiets aan hangt (de eigenaar, 01-10-2026: "Trek Domane SL6"),
  model alleen is de grovere trede.
- **Eigen koppeling** (bike_link, migratie 19): wat de eigenaar op
  /racefietsen koppelde gaat altijd voor de herkenning, en zijn bouwjaar voor
  dat uit de tekst. Daarna een **regel** die hij goedkeurde (bike_rule,
  migratie 20): "wat als X herkend wordt, is model Y".
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
import dataclasses
import re
import unicodedata
from dataclasses import dataclass, field
from functools import cached_property, lru_cache
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


def _alternatives(pattern: str) -> list[str]:
    """De delen van een patroon tussen de `|` op het hoogste niveau (niet
    binnen haakjes of een [klasse])."""
    parts, depth, in_class, current, i = [], 0, False, "", 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            current += pattern[i:i + 2]
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "|" and depth == 0:
            parts.append(current)
            current, i = "", i + 1
            continue
        current += c
        i += 1
    parts.append(current)
    return parts


def needles(pattern: str) -> Optional[frozenset]:
    """Woorden waarvan er minstens één (kleine letters) in de tekst moet staan
    als het patroon past: per alternatief de letters en cijfers waarmee het
    begint ("Defy.{0,20}Advanced" → "defy"). None als een alternatief niet
    met zo'n woord begint (een groep, een klasse): dan altijd zoeken. Alleen
    om sneller over te slaan; de uitkomst blijft die van het patroon."""
    found = set()
    for alt in _alternatives(pattern):
        i = 0
        while alt.startswith(("\\b", "^"), i):
            i += 2 if alt.startswith("\\b", i) else 1
        run = re.match(r"[A-Za-z0-9]+", alt[i:])
        if not run:
            return None
        word, after = run.group(0), alt[i + run.end():]
        if after[:1] in ("?", "*") or after.startswith(("{0", "{,")):
            word = word[:-1]  # de laatste letter is optioneel
        if not word:
            return None
        found.add(word.lower())
    return frozenset(found)


@lru_cache(maxsize=None)
def reference_index(path: str = str(REFERENCE_PATH)) -> tuple:
    return tuple((row["label"], row["regex"], needles(row["regex"].pattern)) for row in reference_rows(path))


def reference_model(listing: mp.Listing) -> Optional[str]:
    """Het eerste referentiemodel waarvan het patroon past, in bestandsvolgorde
    — dezelfde regel als racefiets_jev.apply_reference_data(). Een patroon
    waarvan geen beginwoord in de tekst staat, wordt overgeslagen
    (`needles()`): 339 patronen per advertentie waren een kwart van de
    opbouw van /racefietsen."""
    haystack = f"{listing.title} {listing.description}"
    low = haystack.lower()
    for label, regex, words in reference_index():
        if words is not None and not any(w in low for w in words):
            continue
        if regex.search(haystack):
            return label
    return None
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
    text = text or ""
    if text.isascii():  # bijna altijd; normaliseren per teken kostte ~1 s per opbouw
        return text.lower()
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


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


# --- Uitvoering -------------------------------------------------------------------
#
# Wat direct na het model in de titel staat en op een uitvoering lijkt (de
# opdracht van 01-10-2026: "Trek Domane SL6", "Giant Defy Advanced 2").
# Een lijst van wat wél mag, niet van wat niet mag: na het model staat net zo
# vaak "racefiets", "maat 56", "carbon" of "Shimano", en een woord te veel
# maakt van één model er twee.
VARIANT_WORDS = frozenset({
    "sl", "slr", "al", "alr", "cf", "cfr", "slx", "advanced", "pro", "comp", "sport", "elite", "expert",
    "disc", "team", "ltd",
})
# Afkortingen: in hoofdletters in de modelnaam ("CF SLX 8", "AL 2").
VARIANT_ABBREVIATIONS = frozenset({"sl", "slr", "al", "alr", "cf", "cfr", "slx", "ltd"})
# Een getal van één of twee cijfers ("2", "6", "8.0"): "105" is een groepset
# en "2024" een bouwjaar, geen uitvoering.
VARIANT_NUMBER_RE = re.compile(r"\d{1,2}(?:\.\d)?")
# Letters met een cijfer ("sl7", "r5"); "r7000" (een groepsetnummer) niet.
VARIANT_CODE_RE = re.compile(r"[a-z]{1,4}\d{1,3}")
# Letters met een cijfer die schakelen zijn, geen uitvoering.
NOT_A_VARIANT = frozenset({"di2", "etap", "axs", "e-tap", "11s", "10s", "12s"})
VARIANT_MAX_WORDS = 3
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def _is_variant_word(token: str) -> bool:
    if token in NOT_A_VARIANT:
        return False
    if token in VARIANT_WORDS:
        return True
    return bool(VARIANT_NUMBER_RE.fullmatch(token) or VARIANT_CODE_RE.fullmatch(token))


def variant_of(title: str, family: Optional[str]) -> Optional[str]:
    """De uitvoering: de woorden direct na het model in de titel ("advanced
    2", "sl6", "cf slx 8"), tot het eerste woord dat er geen is; None als de
    titel het model niet noemt of er niets op volgt. Alleen de titel: in de
    beschrijving staat na een modelnaam van alles."""
    if not family:
        return None
    tokens = TOKEN_RE.findall(fold(title))
    for i, token in enumerate(tokens):
        if token == family:
            found, rest = [], tokens[i + 1:]
            break
        # "CAAD12": het model is "caad" (zie _family_word), de cijfers zijn de uitvoering.
        if len(family) >= 3 and token.startswith(family) and token[len(family):].isdigit():
            found, rest = [token[len(family):]], tokens[i + 1:]
            break
    else:
        return None
    for token in rest:
        if len(found) >= VARIANT_MAX_WORDS or not _is_variant_word(token):
            break
        found.append(token)
    return " ".join(found) or None


# --- Modelnamen en sleutels -------------------------------------------------------


def model_key(name: Optional[str]) -> Optional[str]:
    """Waarop modellen gelijk zijn: kleine letters zonder accenten en zonder
    spaties ("SL 6" = "SL6"), en zonder wat tussen haakjes staat — "Trek
    Émonda (overig)" is een toelichting bij het referentiemodel, geen ander
    model dan "Trek Emonda". Zo komen een eigen model, een referentiemodel
    en een herkend model met dezelfde naam op één plek uit."""
    if not name:
        return None
    key = re.sub(r"\s+", "", re.sub(r"\([^)]*\)", "", fold(name)))
    return key or None


@lru_cache(maxsize=None)
def _casing() -> dict[str, str]:
    """{woord (klein): zoals het hoort} uit de merken en modelnamen van de
    referentiemodellen en de catalogus: "TCR", "Émonda", "BMC", "SuperSix".
    De referentiemodellen eerst, die zijn met de hand geschreven; de
    catalogus komt van merksites die vaak alles in hoofdletters zetten
    ("AEROAD"), dus een lang woord in hoofdletters wordt daar gewoon
    "Aeroad"."""
    found: dict[str, str] = {}

    def add(text: str, shouting: bool = False) -> None:
        for word in (text or "").split():
            word = word.strip(".,()")
            if not word or not re.fullmatch(r"[\w\-.]+", word) or fold(word) in found:
                continue
            if word.isupper() != shouting:
                continue
            if shouting and len(word) > 4 and word.isalpha():
                word = word[:1] + word[1:].lower()
            found[fold(word)] = word

    for row in reference_rows():
        add(row["label"])
        add(row["label"], shouting=True)
    for brand in sleepers.EXTRA_BRANDS:
        found.setdefault(fold(brand), brand)
    try:
        with open(CATALOG_PATH, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        rows = []
    for row in rows:
        if row.get("brand"):
            found.setdefault(fold(row["brand"].strip()), row["brand"].strip())
    for shouting in (False, True):
        for row in rows:
            add((row.get("model") or "").split(" ")[0], shouting)
    return found


def _pretty_word(word: str, variant: bool = False) -> str:
    if variant and (word in VARIANT_ABBREVIATIONS or VARIANT_CODE_RE.fullmatch(word)):
        return word.upper()
    if variant and word in VARIANT_WORDS:
        return word.capitalize()  # "Pro", "Team", ook als een merksite "PRO" schrijft
    known = _casing().get(word)
    if known:
        return known
    if VARIANT_CODE_RE.fullmatch(word) or (len(word) <= 3 and word.isalpha() and not variant):
        return word.upper()
    return word[:1].upper() + word[1:]


def pretty_name(brand: Optional[str], family: Optional[str], variant: Optional[str] = None) -> Optional[str]:
    """"Trek Domane SL6", "Giant Defy Advanced 2" uit de herkende woorden."""
    if not brand or not family:
        return None
    known = _casing().get(brand)
    parts = [known or " ".join(_pretty_word(w) for w in brand.split()), _pretty_word(family)]
    parts += [_pretty_word(w, variant=True) for w in (variant or "").split()]
    return " ".join(parts)


def split_name(name: str) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Een zelf getypte modelnaam ("Koga Kinsei Pro") in (naam, merk,
    familie, uitvoering), alles behalve de naam in kleine letters. Het merk
    zoals de herkenning het kent, anders het eerste woord; de familie is het
    woord daarna, de rest de uitvoering. Begint de naam met een modelwoord
    dat maar bij één merk hoort ("Emonda SL6"), dan komt het merk ervoor,
    zodat hij bij de herkende "Trek Emonda SL6" uitkomt."""
    name = " ".join((name or "").split())
    folded = fold(name)
    hit = sleepers.named_brand(name)
    if hit and folded.startswith(fold(hit)):
        brand = fold(hit)
        rest = folded[len(brand):].split()
    else:
        words = folded.split()
        owner = _owner_of().get(words[0]) if words else None
        if owner:
            brand, rest = owner, words
            name = f"{_casing().get(owner) or owner.title()} {name}"
        else:
            brand, rest = (words[0] if words else None), words[1:]
    family = rest[0] if rest else None
    variant = " ".join(rest[1:]) or None
    return name, brand, family, variant


@dataclass(frozen=True)
class Identity:
    """Wat een advertentie over de fiets zegt. Bevroren: de namen en
    sleutels worden één keer uitgerekend (cached_property), want de pool
    vraagt ze voor elke fiets op."""
    brand: Optional[str]
    family: Optional[str]
    material: Optional[str]
    year: Optional[int]
    disc: Optional[bool]  # None: remtype onbekend
    electronic: bool
    speeds: Optional[int]
    tier: Optional[int]
    reference: Optional[str] = None  # referentiemodel uit reference_bikes.csv
    variant: Optional[str] = None  # uitvoering uit de titel ("advanced 2"), of van het eigen model
    own: Optional[str] = None  # het eigen model (bike_model.name) waaraan de eigenaar hem koppelde
    own_id: Optional[int] = None
    confirmed: bool = False  # de eigenaar klikte "klopt" of koos zelf het model
    own_year: bool = False  # het bouwjaar komt van de eigenaar (bike_link.year)
    linked: bool = False  # er is een eigen koppeling (model, jaar of klopt)
    via_rule: bool = False  # het eigen model komt uit een regel (bike_rule), niet uit een koppeling
    # Wat de advertentie zelf zegt, zonder koppeling of regel: daaruit leert
    # de pagina regels ("als X herkend, dan model Y").
    recognized: Optional[str] = None
    recognized_name: Optional[str] = None
    # De herkenning zelf (recognize()), zodat een correctie of regel hem
    # opnieuw kan toepassen zonder de advertentie opnieuw te lezen.
    seen: Optional["Identity"] = field(default=None, compare=False, repr=False)

    @property
    def model(self) -> Optional[str]:
        return f"{self.brand} {self.family}" if self.brand and self.family else None

    @cached_property
    def auto_name(self) -> Optional[str]:
        return pretty_name(self.brand, self.family, self.variant)

    @cached_property
    def name(self) -> Optional[str]:
        """Het model waaraan hij hangt: het eigen model, anders het
        referentiemodel, anders merk + model + uitvoering uit de titel.

        Het referentiemodel alleen als de titel niets preciezers zegt: een
        aantal referentiemodellen zijn een vangnet voor een hele lijn
        ("Trek Domane", "Giant Defy (overig)"), en dan is "Trek Domane SL6"
        uit de titel het model dat de eigenaar bedoelt (01-10-2026). Een
        referentiemodel dat zelf preciezer is ("Giant Defy Composite 1")
        gaat voor."""
        if self.own:
            return self.own
        auto = self.auto_name
        if self.reference:
            ref_key, auto_key = model_key(self.reference), model_key(auto)
            if not (auto_key and ref_key and auto_key != ref_key and auto_key.startswith(ref_key)):
                return self.reference
        return auto

    @cached_property
    def exact(self) -> Optional[str]:
        """De sleutel van het model met uitvoering (model_key())."""
        return model_key(self.name)

    @cached_property
    def coarse(self) -> Optional[str]:
        """De sleutel van merk + model, zonder uitvoering: de grovere trede."""
        return model_key(self.model)

    @cached_property
    def coarse_name(self) -> Optional[str]:
        return pretty_name(self.brand, self.family)

    @property
    def source(self) -> str:
        """Waar het model vandaan komt, voor de pagina."""
        if self.own:
            return "regel" if self.via_rule else "eigen"
        name = self.name
        if name and name == self.reference:
            return "referentie"
        return "automatisch" if name else ""

    @property
    def group(self) -> Optional[str]:
        """Waar hij aan hangt (de naam); zie name."""
        return self.name

    def label(self) -> str:
        parts = [self.group or "model onbekend"]
        if self.year:
            parts.append(str(self.year))
        return " ".join(parts)


def identify(listing: mp.Listing, link: Optional[dict] = None, rules: Optional[dict] = None) -> Identity:
    """Merk, model, uitvoering, bouwjaar en tijdperk van een advertentie.
    `link`: de eigen koppeling uit bike_link (db.list_bike_links()), die gaat
    voor wat de advertentie zegt. `rules`: {herkende sleutel: eigen model}
    van de goedgekeurde regels (bike_rule); een koppeling met een model gaat
    voor een regel."""
    return resolve(recognize(listing), link, rules)


def recognize(listing: mp.Listing) -> Identity:
    """Wat de advertentie zelf zegt, zonder koppeling of regel."""
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
    variant = variant_of(title, family)
    specs, _ = up.listing_specs(listing)
    year = specs.get("model_year")
    route = up.brake_route(specs.get("brake_type"))
    speeds = specs.get("speeds")
    seen = Identity(
        brand=brand, family=family, material=specs.get("frame_material"),
        year=int(year) if year and str(year).isdigit() else None,
        disc=True if route == up.ROUTE_DISC else False if route == up.ROUTE_RIM else None,
        electronic=bool(ELECTRONIC_RE.search(text)),
        speeds=int(speeds) if speeds and str(speeds).isdigit() else None,
        tier=listing.groupset_tier, reference=reference_model(listing), variant=variant,
    )
    return dataclasses.replace(seen, recognized=seen.exact, recognized_name=seen.name)


def resolve(seen: Identity, link: Optional[dict] = None, rules: Optional[dict] = None) -> Identity:
    """De herkenning (recognize()) met de eigen koppeling of een regel erop.
    `seen` mag ook een eerder resultaat zijn: dan telt zijn herkenning."""
    seen = seen.seen or seen
    changes: dict = {"seen": seen}
    model = None
    if link and link.get("model_id") is not None and link.get("model"):
        model = link
    elif rules and seen.exact in rules:
        model = rules[seen.exact]
        changes["via_rule"] = True
    if model:
        # Het merk en de familie van het eigen model: daarop gaat de grovere
        # trede, ook als de titel iets anders zegt.
        changes.update(
            own=model["model"], own_id=model["model_id"],
            brand=fold(model["brand"]) if model.get("brand") else seen.brand,
            family=fold(model["family"]) if model.get("family") else seen.family,
            variant=fold(model["variant"]) if model.get("variant") else None)
    if link:
        if link.get("year"):
            changes.update(year=int(link["year"]), own_year=True)
        changes.update(confirmed=bool(link.get("confirmed")) and model is link, linked=True)
    if len(changes) == 1:
        return seen  # niets van de eigenaar: de herkenning zelf (met zijn al berekende namen)
    return dataclasses.replace(seen, **changes)


# Hoeveel jaar een vergelijkbare fiets mag schelen: de "generatie" van de
# eigenaar (01-10-2026), bewust zonder opgezochte generatiejaren.
YEAR_WINDOW = 2
# Zoveel vergelijkbare advertenties wil een trede; minder, dan een stap
# grover. Lukt dat nergens, dan de trap nog eens met MIN_FEW ("weinig").
MIN_COMPS = 5
MIN_FEW = 3

# De treden van comparables(), met wat de pagina erbij zegt.
LEVEL_LABELS = {
    "model+jaar": "model, ±2 jaar",
    "model": "model",
    "familie+jaar": "modelfamilie, ±2 jaar",
    "familie+tijdperk": "modelfamilie, zelfde tijdperk",
    "opbouw+jaar": "zelfde opbouw, ±2 jaar",
    "onzeker": "onzeker",
}
UNCERTAIN_LEVELS = frozenset({"onzeker"})


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


def _ladder(me: Identity, exact, coarse, build, minimum: int, exclude=None) -> tuple[str, list]:
    # `exclude` hier in elke trede in plaats van vooraf uit elke lijst: de
    # opbouwlijst heeft er duizenden, en meestal slaagt een fijnere trede al.
    if me.exact:
        by_year = [c for c in exact if close_years(me, c[0]) and c[2][0] != exclude]
        if me.year is not None and len(by_year) >= minimum:
            return "model+jaar", by_year
        usable = by_year + [c for c in exact if (me.year is None or c[0].year is None) and c[2][0] != exclude]
        if len(usable) >= minimum:
            return "model", usable
    if me.coarse:
        # Binnen een modelfamilie zitten aluminium en carbon ("Giant Defy" en
        # "Defy Advanced"): daar wel op materiaal, zoals de oude trede.
        family = [c for c in coarse if same_material(me, c[0]) and c[2][0] != exclude]
        by_year = [c for c in family if close_years(me, c[0])]
        if me.year is not None and len(by_year) >= minimum:
            return "familie+jaar", by_year
        era = by_year + [c for c in family if (me.year is None or c[0].year is None) and same_era(me, c[0])]
        if len(era) >= minimum:
            return "familie+tijdperk", era
    if me.year is not None and me.material and me.tier is not None and me.disc is not None:
        same_build = [c for c in build if close_years(me, c[0]) and c[2][0] != exclude]
        if len(same_build) >= minimum:
            return "opbouw+jaar", same_build
    if me.coarse and me.year is None and me.disc is None:
        family = [c for c in coarse if same_material(me, c[0]) and c[2][0] != exclude]
        if len(family) >= minimum:
            return "onzeker", family
    return "", []


def comparables(me: Identity, exact, coarse, build, exclude=None) -> tuple[str, list, bool]:
    """(trede, [(Identity, prijs, extra), ...], weinig) van de eerste trede
    met minstens MIN_COMPS fietsen; lukt dat nergens, dan de trap nog eens
    met MIN_FEW en weinig = True. `exact`: de fietsen met hetzelfde model en
    dezelfde uitvoering (Identity.exact), `coarse`: met hetzelfde merk en
    model, `build`: met hetzelfde materiaal, groepsettier en remtype (Pool
    geeft ze), alle zonder de fiets zelf.

    1. model + uitvoering, bouwjaar ±2 (beide bekend);
    2. model + uitvoering, waarvan een van beide geen bouwjaar heeft, plus die van 1;
    3. merk + model, zelfde materiaal, bouwjaar ±2;
    4. merk + model, zelfde materiaal, zelfde tijdperk (same_era()) als een
       van beide geen bouwjaar heeft, plus die van 3;
    5. elk model, zelfde materiaal, groepsettier en remtype, bouwjaar ±2;
    6. alleen als van de fiets zelf jaar én remtype onbekend zijn: merk +
       model, elk jaar — onzeker, de pagina toont het nooit als koopje
       (UNCERTAIN_LEVELS).
    Daarna niets: een mediaan van alle racefietsen is appels met peren.
    `exclude`: het item_id van de fiets zelf, als die in de lijsten zit."""
    level, found = _ladder(me, exact, coarse, build, MIN_COMPS, exclude)
    if found:
        return level, found, False
    level, found = _ladder(me, exact, coarse, build, MIN_FEW, exclude)
    return level, found, bool(found)


def build_key(ident: Identity) -> Optional[tuple]:
    if ident.material and ident.tier is not None and ident.disc is not None:
        return (ident.material, ident.tier, ident.disc)
    return None


class Pool:
    """De vergelijkingsfietsen, per model, per familie en per opbouw
    geïndexeerd: met ~20.000 fietsen is elke fiets tegen alle andere te
    traag. Items: (Identity, prijs, extra), extra[0] is het item_id."""

    def __init__(self, items: list):
        self.by_exact: dict = {}
        self.by_coarse: dict = {}
        self.by_build: dict = {}
        self.item_of: dict = {}
        # Wie al herkend is, hoeft dat voor de actieve fietsen niet nog eens.
        self.identity_of: dict = {}
        for item in items:
            self._add(item)

    def _indexes(self, ident: Identity) -> list:
        return [(self.by_exact, ident.exact), (self.by_coarse, ident.coarse), (self.by_build, build_key(ident))]

    def _add(self, item: tuple) -> None:
        item_id = item[2][0]
        self.item_of[item_id] = item
        self.identity_of[item_id] = item[0]
        for index, key in self._indexes(item[0]):
            if key is not None:
                index.setdefault(key, []).append(item)

    def _remove(self, item: tuple) -> None:
        for index, key in self._indexes(item[0]):
            bucket = index.get(key)
            if not bucket:
                continue
            at = next((i for i, other in enumerate(bucket) if other is item), None)
            if at is not None:
                del bucket[at]
            if not bucket:
                del index[key]

    def replace(self, item_id: str, identity: Identity) -> Optional[Identity]:
        """Na een eigen koppeling: deze fiets met zijn nieuwe Identity op de
        goede plek in de indexen, zonder de rest opnieuw te herkennen.
        Geeft de oude Identity, of None als hij niet in de pool zit (geen
        vraagprijs, of ouder dan de pool)."""
        item = self.item_of.get(item_id)
        if item is None:
            return None
        self._remove(item)
        self._add((identity, item[1], item[2]))
        return item[0]

    def comparables(self, me: Identity, exclude: str) -> tuple[str, list, bool]:
        """Zonder de fiets zelf (`exclude`: zijn item_id, het eerste veld van `extra`)."""
        build = build_key(me)
        return comparables(me, self.by_exact.get(me.exact, ()) if me.exact else (),
                           self.by_coarse.get(me.coarse, ()) if me.coarse else (),
                           self.by_build.get(build, ()) if build else (), exclude)

    def linked(self, me: Identity) -> int:
        """Hoeveel advertenties (de laatste 180 dagen) aan hetzelfde model hangen."""
        return len(self.by_exact.get(me.exact, ())) if me.exact else 0
