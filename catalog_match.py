"""Uitvoering en modeljaar: een advertentie koppelen aan rijen uit de catalogus.

model_lines.py weet dat een advertentie een "Giant TCR" is. Maar een TCR uit
2010 en een uit 2020 zijn verschillende fietsen, en een TCR Advanced 2 is
een andere dan een TCR Advanced Pro 1. Dit gaat een stap verder, alleen op
wat de advertentie zelf zegt:

1. Uitvoering: de langste reeks woorden uit een catalogusnaam van die lijn
   die aaneengesloten in de titel of de omschrijving staat. "Giant TCR
   Advanced 2 uit 2016" vindt zo "TCR ADVANCED 2"; de catalogusnaam "TCR
   ADVANCED 2 DISC" telt als die langer is en er ook staat. Alleen de lijn
   ("TCR") is geen uitvoering.
2. Jaar: een jaartal met een label in de tekst ("bouwjaar 2016", via
   extract_specs()), anders een los jaartal in de titel ("Domane SL5 2019").
   Staat de uitvoering in dat jaar in de catalogus, dan is de match exact en
   gelden de gegevens van die rij (groepset, materiaal, rem, nieuwprijs met
   markt en bron).

Er wordt niets geraden. Geen jaar in de advertentie: dan blijft het bij de
uitvoering en de jaren waarin de catalogus hem kent. Een jaartal dat de
catalogus voor die uitvoering niet heeft: dan staat dat er ook zo.

De catalogus is grotendeels een Spaanse bron (bikezona, `market` ES). Een
Spaanse catalogusprijs wordt daarom altijd met zijn markt getoond en niet als
Nederlandse nieuwprijs in de dealscore gestopt.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

import model_lines as ml

CATALOG_PATH = ml.CATALOG_PATH

# Een jaartal los in een titel: "Trek Domane SL5 disk 2019", "Cube Attain Pro
# 2026 - Zo goed als nieuw"). Niet na een euroteken of als deel van een
# groter getal, niet gevolgd door een eenheid ("2000 km", "2000,-") en niet
# als begin van een reeks jaren ("2018-2020").
TITLE_YEAR_RE = re.compile(
    r"(?<![\d€.,])(?<!\d-)((?:19[89]\d|20[0-4]\d))"
    r"(?!\d|[.,]\d|,-|-\d|\s*(?:mm|cm|km|kg|g|euro|eur)\b)",
    re.I,
)


def title_year(title: str, today: Optional[date] = None) -> Optional[int]:
    today = today or date.today()
    for match in TITLE_YEAR_RE.finditer(title):
        year = int(match.group(1))
        # Een fiets van volgend modeljaar staat al in de winkel; verder vooruit
        # is het geen bouwjaar.
        if 1980 <= year <= today.year + 1:
            return year
    return None


@dataclass(frozen=True)
class CatalogRow:
    brand: str
    model: str
    year: Optional[int]
    market: str
    groupset: str
    frame_material: str
    brake_type: str
    electronic: str
    new_price: Optional[float]
    currency: str
    price_basis: str
    source_url: str


def _tokens(model: str) -> tuple[str, ...]:
    return tuple(
        t for t in (w.strip(".,:;()´'`") for w in re.split(r"[\s/\-]+", ml.fold(model))) if t
    )


def _word_regex(token: str) -> str:
    # Canyon nummert "8.0", verkopers schrijven "8": ".0" mag wegblijven.
    whole = re.fullmatch(r"(\d+)\.0", token)
    if whole:
        return re.escape(whole.group(1)) + r"(?:[.,]0)?"
    return ml._token_regex(token)


def _phrase_regex(tokens: tuple[str, ...]) -> str:
    # Tussen twee woorden mag een spatie, streepje of niets staan: "SL 6" in
    # de catalogus is "SL6" in de meeste titels.
    return (
        r"(?<![a-z0-9])"
        + r"[^a-z0-9\n]{0,3}".join(_word_regex(t) for t in tokens)
        + r"(?![a-z0-9])"
    )


# Korte woorden die in de hoofdletter-catalogus (bikezona) als afkorting
# lijken te staan maar gewone woorden zijn: "TCR ADVANCED PRO 1" is een
# "Pro", terwijl TCR, SLR en CLX wel afkortingen zijn.
SHORT_WORDS = frozenset({"pro", "kom", "one", "air", "max", "evo", "gen", "lux", "wmn", "sport"})


def _display(tokens: Iterable[str], rows: Iterable[CatalogRow], n: int) -> str:
    """De uitvoeringsnaam in de spelling van de catalogus, afgekort tot de
    woorden die gematcht zijn. Een spelling van de merksite zelf (niet alles
    in hoofdletters) gaat voor."""
    spellings = []
    for row in rows:
        words = [w for w in re.split(r"[\s/\-]+", row.model.strip()) if w]
        if len(words) >= n:
            spellings.append(" ".join(words[:n]))
    if not spellings:
        return " ".join(tokens)
    for text in spellings:
        if not text.isupper():
            return text
    return " ".join(
        w if (len(w) <= 3 and w.lower() not in SHORT_WORDS) or any(c.isdigit() for c in w)
        else w[:1] + w[1:].lower()
        for w in spellings[0].split()
    )


def _number(value: str) -> Optional[float]:
    try:
        return float(value) if value.strip() else None
    except ValueError:
        return None


def _year(value: str) -> Optional[int]:
    value = value.strip()
    return int(value) if value.isdigit() else None


def load_catalog(path: Path | str = CATALOG_PATH) -> list[CatalogRow]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [
                CatalogRow(
                    brand=(r.get("brand") or "").strip(),
                    model=(r.get("model") or "").strip(),
                    year=_year(r.get("model_year") or ""),
                    market=(r.get("market") or "").strip(),
                    groupset=(r.get("groupset") or "").strip(),
                    frame_material=(r.get("frame_material") or "").strip(),
                    brake_type=(r.get("brake_type") or "").strip(),
                    electronic=(r.get("electronic") or "").strip(),
                    new_price=_number(r.get("new_price") or ""),
                    currency=(r.get("currency") or "").strip(),
                    price_basis=(r.get("price_basis") or "").strip(),
                    source_url=(r.get("source_url") or "").strip(),
                )
                for r in csv.DictReader(f)
                if (r.get("brand") or "").strip() and (r.get("model") or "").strip()
            ]
    except (OSError, csv.Error):
        return []


@dataclass(frozen=True)
class Variant:
    brand: str
    tokens: tuple[str, ...]
    label: str  # "Giant TCR Advanced 2"
    pattern: str  # regex op gevouwen tekst; sleutel in model/listing_model
    rows: tuple[CatalogRow, ...]  # elke catalogusrij waarvan de naam zo begint

    @property
    def years(self) -> list[int]:
        return sorted({r.year for r in self.rows if r.year})


@dataclass
class CatalogMatch:
    variant: Variant
    year: Optional[int] = None
    year_source: str = ""  # "tekst" (met label) of "titel"
    exact: list[CatalogRow] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.variant.label

    @property
    def best_row(self) -> Optional[CatalogRow]:
        """Van de rijen voor dit jaar de Nederlandse, als die er is."""
        if not self.exact:
            return None
        return sorted(self.exact, key=lambda r: (r.market != "NL", r.new_price is None))[0]

    @property
    def matched_on(self) -> str:
        if self.exact:
            return f"catalogus: uitvoering + jaar {self.year} ({self.year_source})"
        if self.year:
            return f"catalogus: uitvoering; jaar {self.year} ({self.year_source}) niet in catalogus"
        return "catalogus: uitvoering, jaar onbekend"

    @property
    def confidence(self) -> float:
        return 0.9 if self.exact else 0.7

    def describe(self) -> str:
        """Eén regel voor de Specs-kolom: wat de catalogus over precies deze
        fiets zegt, of in welke jaren hij bestond."""
        row = self.best_row
        if row is not None:
            parts = [p for p in (row.groupset, row.frame_material, row.brake_type) if p]
            text = f"Catalogus {row.year}"
            if parts:
                text += ": " + ", ".join(parts)
            if row.new_price:
                # De markt erbij: een Spaanse catalogusprijs is geen
                # Nederlandse nieuwprijs.
                text += f"; nieuw €{row.new_price:.0f} ({row.market or 'markt onbekend'})"
            return text
        years = self.variant.years
        span = (
            f"{years[0]}" if len(years) == 1 else f"{years[0]}–{years[-1]}" if years else "jaar onbekend"
        )
        if self.year:
            return f"Catalogus kent deze uitvoering uit {span}, niet uit {self.year}"
        return f"Catalogus: uitvoering uit {span}; bouwjaar niet in de advertentie"


class VariantMatcher:
    def __init__(self, lines: Iterable[ml.ModelLine], rows: Iterable[CatalogRow]):
        by_line: dict[tuple[str, str], list[CatalogRow]] = {}
        for row in rows:
            tokens = _tokens(row.model)
            if tokens:
                by_line.setdefault((row.brand, tokens[0]), []).append(row)
        # Per lijn: elke prefix van twee of meer woorden van een catalogusnaam,
        # met de rijen die zo beginnen. Langste eerst, zodat "TCR Advanced 2
        # Disc" wint van "TCR Advanced 2" als beide in de tekst staan.
        self._variants: dict[str, list[Variant]] = {}
        for line in lines:
            rows_for_line = by_line.get((line.brand, line.line), [])
            prefixes: dict[tuple[str, ...], list[CatalogRow]] = {}
            for row in rows_for_line:
                tokens = _tokens(row.model)
                for n in range(2, len(tokens) + 1):
                    prefixes.setdefault(tokens[:n], []).append(row)
            variants = []
            for tokens, prefix_rows in prefixes.items():
                label = f"{line.brand} {_display(tokens, prefix_rows, len(tokens))}"
                pattern = ml._brand_regex(line.brand) + r".{0,40}?" + _phrase_regex(tokens)
                variants.append(
                    Variant(line.brand, tokens, label, pattern, tuple(prefix_rows))
                )
            variants.sort(key=lambda v: -len(v.tokens))
            self._variants[line.label] = [(re.compile(_phrase_regex(v.tokens)), v) for v in variants]

    def match(
        self, line_label: str, title: str, text: str, labelled_year: Optional[str] = None
    ) -> Optional[CatalogMatch]:
        candidates = self._variants.get(line_label)
        if not candidates:
            return None
        in_title = self._longest(candidates, ml.fold(title))
        in_text = self._longest(candidates, ml.fold(text))
        # De titel gaat voor: een omschrijving noemt ook weleens een andere
        # fiets. Behalve als de omschrijving dezelfde uitvoering preciezer
        # noemt ("TCR Advanced 2" in de titel, "TCR Advanced 2 Disc" erin).
        variant = in_title
        if in_text is not None and (
            in_title is None
            or (len(in_text.tokens) > len(in_title.tokens)
                and in_text.tokens[: len(in_title.tokens)] == in_title.tokens)
        ):
            variant = in_text
        if variant is None:
            return None

        year, source = None, ""
        if labelled_year and labelled_year.isdigit():
            year, source = int(labelled_year), "tekst"
        else:
            year = title_year(title)
            source = "titel" if year else ""
        found = CatalogMatch(variant, year, source)
        if year:
            found.exact = [r for r in variant.rows if r.year == year]
        return found

    @staticmethod
    def _longest(candidates, haystack: str) -> Optional[Variant]:
        for compiled, candidate in candidates:
            if compiled.search(haystack):
                return candidate
        return None

    def variants(self) -> list[Variant]:
        return [v for pairs in self._variants.values() for _, v in pairs]


@lru_cache(maxsize=1)
def default_matchers() -> tuple:
    """(lines, LineMatcher, VariantMatcher) op de catalogus naast de code.
    Eén keer per proces: het opbouwen kost ongeveer een seconde, en een run
    met meerdere zoekopdrachten of watchlists hoeft dat niet elke keer."""
    lines = ml.load_lines(CATALOG_PATH)
    return lines, ml.LineMatcher(lines), VariantMatcher(lines, load_catalog(CATALOG_PATH))
