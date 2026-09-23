"""Slapers: advertenties waar de tekst niets over de fiets zegt, maar de
omstandigheden op een haastige verkoper wijzen.

Aanleiding: een Cannondale CAAD10 ging op 23-09-2026 voor een bod van €45
weg, twee uur na plaatsing. Titel "Heren racefiets", beschrijving "Moet weg
wegens verhuizing!", merk "Overige merken", bieden zonder minimum. De
dealscore kan daar niets mee — er is geen prijs en geen herkend model — en
wat het een goede fiets maakte stond alleen op de foto's. Dit signaal taxeert
dus niets: het zet zulke advertenties bovenaan zodat de eigenaar zelf de
foto's bekijkt.

Alles hier komt uit de zoekresultaten die de crawl al ophaalt: geen enkel
extra verzoek naar Marktplaats.

Bewust los van `Listing.deal_score` (prijs t.o.v. ijkpunten) en van de
waardescore (geschatte waarde / prijs): dit is geen van beide.
"""
from __future__ import annotations

import csv
import html as html_lib
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

CATALOG_PATH = Path(__file__).resolve().parent / "reference_bike_catalog.csv"

# Words a title can consist of and still say nothing about which bike it is:
# the type, who it's for, a size, a material, a colour, the condition. A
# title made up of only these is what the Cannondale had ("Heren racefiets"),
# and it's what keeps a listing out of every search on brand or model.
# Precision over coverage: one word outside this list — a brand, a groupset,
# a model name — and the title counts as descriptive. "Racefiets shimano 105"
# is therefore not a sleeper even though it names no brand; the groupset is
# something a buyer searches for.
GENERIC_TITLE_WORDS = frozenset(
    """
    racefiets racefietsen race racer koersfiets koersfietsen wielrenfiets wielrenfietsen
    wielren wielrenner wielrennen sportfiets fiets fietsen tourfiets wegfiets wegracefiets
    bike road roadbike gravel gravelbike gravelfiets tijdritfiets triathlonfiets triathlon
    heren herenracefiets herenfiets dames damesracefiets damesfiets heer dame
    jongens meisjes kinder kinderracefiets unisex
    oude oud mooie mooi nette net goede goed prima lichte licht snelle snel sportieve
    klassieke retro vintage
    carbon aluminium alu staal stalen
    maat frame framemaat framehoogte cm inch
    zwart zwarte wit witte rood rode blauw blauwe grijs grijze groen groene geel gele
    zilver zilveren oranje
    te koop en met in op staat zgan z.g.a.n gebruikt weinig zo als nieuw nieuwe
    de het een voor van
    versnellingen versnelling speed
    s m l xl xs
    """.split()
)

# A word in a title: letters (with accents and inner dots/hyphens, for
# "z.g.a.n" and "e-bike"). Digits are left out entirely — "56", "56cm",
# "2x10" are sizes and gear counts, generic by nature.
TITLE_WORD_RE = re.compile(r"[^\W\d_]+(?:[.\-][^\W\d_]+)*", re.UNICODE)

# Brands a description can name. When it does, the seller has said what the
# bike is and a search on that brand finds it — then it isn't a sleeper, and
# whether it's cheap is the deal score's job. The catalogue's brands, plus
# the ones that turned up in a crawl of the racefietsen category (23-09-2026)
# without being in the catalogue, spelled as the sellers spelled them
# ("myata"). Names only, nothing about the market. Brands that are also
# ordinary words ("Look": "retro look") stay out — a false hit here hides a
# sleeper.
EXTRA_BRANDS = (
    "Koga", "Miyata", "Myata", "Gazelle", "Peugeot", "Diamant", "Cinelli", "Haibike",
    "Triban", "Van Rysel", "Principia", "Alan", "3T", "Enve", "S-Works", "Paul Milnes",
)
# Catalogue brands that are ordinary words too, for the same reason.
BRANDS_THAT_ARE_WORDS = frozenset({"time", "rose"})


def load_brands(path: Path = CATALOG_PATH) -> frozenset:
    """The catalogue's brand column plus EXTRA_BRANDS, lower-cased. A missing
    or unreadable catalogue leaves just the extras rather than failing the
    run: fewer brands means more sleepers, never fewer listings."""
    brands = {b.lower() for b in EXTRA_BRANDS}
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            brands.update(
                row["brand"].strip().lower() for row in csv.DictReader(f) if row.get("brand")
            )
    except (OSError, KeyError, csv.Error):
        pass
    return frozenset(b for b in brands if b and b not in BRANDS_THAT_ARE_WORDS)


@lru_cache(maxsize=None)
def brand_pattern(path: Path = CATALOG_PATH) -> re.Pattern:
    # Longest first, so "Eddy Merckx" wins over "Merckx" in the reason text.
    names = sorted(load_brands(path), key=len, reverse=True)
    return re.compile(
        r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w-])", re.I
    )


def named_brand(text: str) -> Optional[str]:
    match = brand_pattern().search(text or "")
    return match.group(0) if match else None


# The seller wants it gone, soon, and isn't holding out for the best price.
# Each phrase seen in real listings; kept to phrases that mean exactly that,
# not "snel" or "weg" on their own ("snelle fiets", "weg- en wielrennen").
URGENCY_RE = re.compile(
    r"\bmoet\s+(?:nu\s+|snel\s+|echt\s+)?(?:weg|de\s+deur\s+uit)\b"
    r"|\bverhui[sz]\w*"
    r"|\bopruim\w*"
    r"|\bz\.?\s?s\.?\s?m\.?(?=\W|$)"
    r"|\bzo\s+snel\s+mogelijk\b"
    r"|\bweg\s*(?:=|is)\s*weg\b"
    r"|\bplaatsgebrek\b|\bgeen\s+(?:plek|ruimte)\s+meer\b"
    r"|\bnalatenschap\b|\berfenis\b"
    r"|\bemigr\w+",
    re.I,
)

# At or under this many words the description tells as little as the title.
# Marktplaats' own thinContent flag says the same, but it's not set on every
# short one (the Cannondale's five words had it; plenty of one-liners don't).
THIN_DESCRIPTION_WORDS = 15
# Below this share of the search's median price, a listing with a real price
# counts as cheap for this signal. Deliberately looser than the bargain
# threshold: here it only has to make the listing worth a look.
CHEAP_PCT_OF_MEDIAN = 60.0

# Points per signal. The generic title is required (see sleeper_signal());
# the rest add up. SLEEPER_MIN_SCORE needs the title plus two of the three
# stronger signals — the Cannondale scored 100.
POINTS_GENERIC_TITLE = 35
POINTS_THIN_DESCRIPTION = 20
POINTS_URGENCY = 20
POINTS_PRICE = 15
POINTS_NEW = 10
SLEEPER_MIN_SCORE = 70


def is_generic_title(title: str) -> bool:
    words = TITLE_WORD_RE.findall((title or "").lower())
    return bool(words) and all(word in GENERIC_TITLE_WORDS for word in words)


def urgency_phrase(text: str) -> Optional[str]:
    match = URGENCY_RE.search(text or "")
    return match.group(0).strip() if match else None


def description_word_count(description: str) -> int:
    return len((description or "").split())


def sleeper_signal(listing) -> tuple[Optional[float], str]:
    """(score 0-100, reasons) for one listing, or (None, "") when the text
    says what the bike is — a title with more than generic words, or a brand
    in the description. Then a buyer searching for it finds it, and whether
    it's cheap is the deal score's job. A reserved listing is skipped too:
    someone got there first."""
    if listing.reserved or not is_generic_title(listing.title):
        return None, ""
    if named_brand(listing.description):
        return None, ""

    score = POINTS_GENERIC_TITLE
    reasons = ["titel zonder merk of model"]

    words = description_word_count(listing.description)
    if listing.thin_content or words <= THIN_DESCRIPTION_WORDS:
        score += POINTS_THIN_DESCRIPTION
        reasons.append(f"beschrijving van {words} woord{'' if words == 1 else 'en'}")

    phrase = urgency_phrase(f"{listing.title} {listing.description}")
    if phrase:
        score += POINTS_URGENCY
        reasons.append(f"haast: \"{phrase}\"")

    # Either there is nothing to pay yet — a bid listing nobody has made a
    # usable bid on, so the first reasonable bid can take it — or the asking
    # price is low for the search. A MIN_BID's price is an asking price (see
    # CLAUDE.md), a FAST_BID's is the bidding so far, which says neither.
    if listing.price_is_bid and (listing.price_eur is None or listing.bid_open):
        score += POINTS_PRICE
        reasons.append("bieden, nog geen bod")
    elif (
        listing.price_type != "FAST_BID"
        and listing.pct_of_median is not None
        and listing.pct_of_median <= CHEAP_PCT_OF_MEDIAN
    ):
        score += POINTS_PRICE
        reasons.append(f"{listing.pct_of_median:.0f}% van mediaan")

    if listing.is_new:
        score += POINTS_NEW
        reasons.append("nieuw sinds vorige run")

    return float(score), " · ".join(reasons)


def apply_sleeper_signals(listings) -> None:
    """Fill in sleeper_score / sleeper_reasons. Run after the bid lookup,
    the history (is_new) and flag_bargains (pct_of_median)."""
    for listing in listings:
        listing.sleeper_score, listing.sleeper_reasons = sleeper_signal(listing)


def is_sleeper(listing) -> bool:
    return listing.sleeper_score is not None and listing.sleeper_score >= SLEEPER_MIN_SCORE


def sleepers(listings) -> list:
    """The sleepers, strongest first, then newest."""
    return sorted(
        (l for l in listings if is_sleeper(l)),
        key=lambda l: (-l.sleeper_score, not l.is_new),
    )


def price_text(listing) -> str:
    if listing.price_eur is not None:
        text = f"€{listing.price_eur:.0f}"
        # A MIN_BID's price is the seller's asking price, a FAST_BID's the
        # bidding so far (CLAUDE.md, "Valkuilen").
        if listing.price_type == "MIN_BID":
            return text + " (vraagprijs, bieden)"
        # A FAST_BID nobody bid on only has a price when the seller set a
        # minimum bid (resolve_bid_price()); that is what it costs to open.
        if listing.price_type == "FAST_BID" and listing.bid_count == 0:
            return f"minimumbod {text}, nog geen bod"
        return text + " (bod)" if listing.price_is_bid else text
    if listing.price_type == "FAST_BID":
        return "bieden zonder minimum"
    return listing.price_type or "?"


def render_panel(listings) -> tuple[int, str]:
    """(count, html) for the report's Slapers tab: one card per sleeper with
    its photos, because the photos are the whole point."""
    found = sleepers(listings)
    esc = html_lib.escape
    parts = [
        "<h2>Slapers</h2>",
        "<p class='muted'>Advertenties waar de titel geen merk of model noemt, met weinig "
        "tekst, haast of een bod zonder minimum. De tekst zegt niets over de fiets — kijk "
        "naar de foto's. Dit is geen taxatie en geen dealscore; het zegt alleen dat de "
        "verkoper weinig moeite doet en dat maar weinig kopers hem zullen vinden.</p>",
    ]
    if not found:
        parts.append("<p class='muted'>Geen slapers in deze run.</p>")
        return 0, "\n".join(parts)

    parts.append("<div class='cards'>")
    for l in found:
        photos = "".join(
            f"<a href='{esc(l.url, quote=True)}' target='_blank' rel='noopener'>"
            f"<img class='sleeper-photo' src='{esc(url, quote=True)}' alt='' loading='lazy'></a>"
            for url in l.image_urls.split()
        ) or "<div class='muted'>geen foto in de zoekresultaten</div>"
        new = "<span class='badge new'>NIEUW</span>" if l.is_new else ""
        description = esc(l.description) if l.description else "<em>geen beschrijving</em>"
        parts.append(
            "<div class='card sleeper'>"
            f"<div class='sleeper-photos'>{photos}</div>"
            f"<h4>{new}<a href='{esc(l.url, quote=True)}' target='_blank' rel='noopener'>"
            f"{esc(l.title)}</a></h4>"
            f"<div><span class='score-pill top'>{l.sleeper_score:.0f}</span> "
            f"<strong>{esc(price_text(l))}</strong> · {esc(l.city or '?')}"
            f"{' · ' + esc(l.frame_height) if l.frame_height else ''}</div>"
            f"<p class='muted'>{esc(l.sleeper_reasons)}</p>"
            f"<p>{description}</p>"
            "</div>"
        )
    parts.append("</div>")
    return len(found), "\n".join(parts)
