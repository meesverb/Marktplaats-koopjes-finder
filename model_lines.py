"""Modellijnen: brede herkenning van racefietsen op merk + modelnaam.

reference_bikes.csv herkent een handvol onderzochte modellen tot op de
uitvoering (Defy Composite 1 vs Advanced), met materiaal en remtype erbij.
Daarbuiten bleef alles ongekoppeld: een "Giant TCR" of "Trek Emonda SL6"
kreeg geen label, en zonder label geen prijsgeschiedenis per model — dus ook
nooit een 2e-hands gemiddelde om tegen af te zetten.

Dit is de brede laag eronder. De lijnnamen komen uit
reference_bike_catalog.csv (merk + eerste woord van de modelnaam: TCR, Defy,
Emonda, CAAD10, Addict, ...). Er wordt niets over de fiets beweerd — geen
nieuwprijs, geen jaar, geen materiaal. Het label groepeert alleen
advertenties van dezelfde lijn, zodat hun vraagprijzen samen een
2e-hands-gemiddelde opbouwen.

Een lijn telt alleen als het merk ervoor staat ("Giant ... TCR", met hooguit
drie woorden ertussen in de titel, direct erachter in de beschrijving). Een
lijnnaam los herkennen levert te veel valse treffers op: "Paris", "Stelvio",
"Ventoux" en "Terra" zijn ook fietsen van andere merken, of gewone woorden.

De hand-onderzochte rijen gaan altijd voor: een Defy Composite blijft
"Giant Defy Composite (uitvoering onbekend)" en telt daarnaast in
`listing_model` ook als "Giant Defy".
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

CATALOG_PATH = Path(__file__).resolve().parent / "reference_bike_catalog.csv"

# Eerste modelwoorden in de catalogus die geen lijn zijn maar een toevoeging
# die achter elk merk kan staan ("Giant Pro", "Trek Carbon", "Cube Cross").
# Na een merknaam in een titel betekenen ze niets over welke fiets het is.
NOT_A_LINE = frozenset(
    """
    pro team carbon cross race road dama donna classic track pista gravel touring
    ultra premium speed super six custom aluminium alu full air world power check
    prima via mono she san gran mach newest finest nuovo sworks s-works disc
    """.split()
)

# Andere namen waaronder een merk in titels staat. S-Works is Specializeds
# topuitvoering en staat vaak in plaats van de merknaam: "S-Works Tarmac SL7".
BRAND_ALIASES = {"Specialized": ("S-Works",)}

# Tussen merk en lijn in een titel: "Giant racefiets TCR", "Trek - Emonda".
TITLE_GAP_WORDS = 3


def fold(text: str) -> str:
    """Kleine letters zonder accenten: "Émonda" en "Cervélo" worden zo
    gevonden in een titel die "Emonda" of "Cervelo" schrijft, en andersom."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


@dataclass(frozen=True)
class ModelLine:
    brand: str
    line: str  # gevouwen lijnwoord, bv. "tcr", "emonda", "caad10"
    label: str  # voor het rapport: "Giant TCR", "Trek Émonda"
    pattern: str  # regex op gevouwen tekst; sleutel in model/listing_model


def _line_token(model: str) -> Optional[str]:
    words = [w for w in re.split(r"[\s/\-]+", model.strip()) if w]
    if not words:
        return None
    return words[0].strip(".,:;()")


def _usable(token: str) -> bool:
    folded = fold(token)
    if folded in NOT_A_LINE or len(folded) < 2:
        return False
    if folded.isalpha():
        # Twee letters ("SL", "CX", "AC") staan in te veel titels als
        # toevoeging om er een lijn van te maken.
        return len(folded) >= 3
    if re.fullmatch(r"[\d.]+", folded):
        # Trek 1.2 en 2.3 zijn lijnen, net als Bianchi 928; een los getal van
        # één of twee cijfers is eerder een maat of een versnelling.
        return "." in folded or len(folded) >= 3
    return True


def _display(token: str) -> str:
    # Het grootste deel van de catalogus komt uit een Spaanse bron die alles
    # in hoofdletters schrijft. Korte namen en namen met cijfers zijn daar
    # meestal ook echt afkortingen (TCR, CLX, CAAD10); de rest wordt "Emonda".
    if token.isupper() and (len(token) <= 3 or any(c.isdigit() for c in token)):
        return token
    if token.isupper():
        return token[:1] + token[1:].lower()
    return token


def _token_regex(folded: str) -> str:
    # "caad10" moet ook "CAAD 10" en "caad-10" vinden: tussen een letter- en
    # een cijferreeks mag een spatie of streepje staan.
    runs = re.findall(r"[a-z]+|\d+|[^a-z\d]+", folded)
    return r"[\s\-]?".join(re.escape(run) for run in runs)


def _brand_regex(brand: str) -> str:
    names = [brand, *BRAND_ALIASES.get(brand, ())]
    alternatives = [
        r"[\s\-]?".join(re.escape(p) for p in re.split(r"[\s\-]+", fold(name)))
        for name in names
    ]
    return alternatives[0] if len(alternatives) == 1 else f"(?:{'|'.join(alternatives)})"


def _pattern(brand: str, line: str) -> str:
    return (
        rf"(?<![a-z0-9]){_brand_regex(brand)}(?:[^a-z0-9\n]+[\w.'\-]+){{0,{TITLE_GAP_WORDS}}}?"
        rf"[^a-z0-9\n]+{_token_regex(line)}(?![a-z0-9])"
    )


def load_lines(path: Path | str = CATALOG_PATH) -> list[ModelLine]:
    """Alle merk+lijn-combinaties uit de catalogus. Een ontbrekende of
    onleesbare catalogus geeft een lege lijst: dan wordt er alleen herkend
    wat in het referentiebestand staat, zoals vroeger."""
    spellings: dict[tuple[str, str], dict[str, int]] = {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                brand = (row.get("brand") or "").strip()
                token = _line_token(row.get("model") or "")
                if not brand or not token or not _usable(token):
                    continue
                counts = spellings.setdefault((brand, fold(token)), {})
                counts[token] = counts.get(token, 0) + 1
    except (OSError, csv.Error):
        return []

    lines = []
    for (brand, folded), counts in sorted(spellings.items()):
        # "ÉMONDA" en "Emonda" zijn één lijn. Een spelling met accent wint
        # (dat is de merknaam), dan een die niet in hoofdletters staat (die
        # komt van de merksite zelf), dan de meest voorkomende.
        best = max(counts, key=lambda s: (s.lower() != fold(s), not s.isupper(), counts[s]))
        lines.append(
            ModelLine(
                brand=brand,
                line=folded,
                label=f"{brand} {_display(best)}",
                pattern=_pattern(brand, folded),
            )
        )
    return lines


class LineMatcher:
    """Eén regex per merk met alle lijnen als alternatieven, langste eerst:
    "Cannondale CAAD 10" is CAAD10, niet de kortere lijn CAAD."""

    def __init__(self, lines: Iterable[ModelLine]):
        by_brand: dict[str, list[ModelLine]] = {}
        for line in lines:
            by_brand.setdefault(line.brand, []).append(line)
        self._brands = []
        for brand, brand_lines in by_brand.items():
            ordered = sorted(brand_lines, key=lambda l: len(l.line), reverse=True)
            alternatives = "|".join(
                f"(?P<l{i}>{_token_regex(l.line)})" for i, l in enumerate(ordered)
            )
            head = rf"(?<![a-z0-9]){_brand_regex(brand)}"
            tail = rf"[^a-z0-9\n]+(?:{alternatives})(?![a-z0-9])"
            title_re = re.compile(
                head + rf"(?:[^a-z0-9\n]+[\w.'\-]+){{0,{TITLE_GAP_WORDS}}}?" + tail
            )
            adjacent_re = re.compile(head + tail)
            self._brands.append((title_re, adjacent_re, ordered))

    def _search(self, text: str, which: int) -> Optional[ModelLine]:
        best = None
        for compiled in self._brands:
            match = compiled[which].search(text)
            if match and (best is None or match.start() < best[0]):
                name = next(k for k, v in match.groupdict().items() if v is not None)
                best = (match.start(), compiled[2][int(name[1:])])
        return best[1] if best else None

    def match(self, title: str, description: str = "") -> Optional[ModelLine]:
        """De lijn uit de titel; alleen als die niets oplevert de
        beschrijving, en daar alleen met merk en lijn direct na elkaar — een
        beschrijving noemt ook weleens de fiets die de verkoper hiervóór had."""
        found = self._search(fold(title), 0)
        if found is None and description:
            found = self._search(fold(description), 1)
        return found


def is_bike_reference(reference: list[dict]) -> bool:
    """Modellijnen horen alleen bij een fietszoekopdracht. Of het er een is,
    zegt het referentiebestand: reference_bikes.csv heeft rijen met kind
    'bike', de accessoire- en luidsprekerbestanden niet."""
    return any(row.get("kind") == "bike" for row in reference)


def apply_lines(listings, matcher: LineMatcher, matches: dict[str, list[str]]) -> int:
    """Koppel elke advertentie aan haar modellijn. Een advertentie die al
    door het referentiebestand herkend is houdt dat label (dat is preciezer);
    de lijn komt er in `matches` (voor listing_model) wel bij. Geeft het
    aantal advertenties terug dat hierdoor pas een label kreeg."""
    labelled = 0
    for listing in listings:
        line = matcher.match(listing.title or "", listing.description or "")
        if line is None:
            continue
        patterns = matches.setdefault(listing.item_id, [])
        if line.pattern not in patterns:
            patterns.append(line.pattern)
        if not listing.ref_label:
            listing.ref_label = line.label
            labelled += 1
    return labelled
