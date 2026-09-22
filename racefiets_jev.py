#!/usr/bin/env python3
"""Find racefiets (road bike) bargains on Marktplaats.

Scrapes Marktplaats search result pages for a query (default: "racefiets"),
collects the listed prices, and flags listings priced well below the median
of what was found as potential bargains.

Usage:
    pip install -r requirements.txt
    python racefiets_jev.py --pages 10
"""
from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import os
import re
import statistics
import string
import sys
import time
import webbrowser
from dataclasses import dataclass, asdict, fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlencode

import requests

import db

BASE_URL = "https://www.marktplaats.nl"
DEFAULT_QUERY = "racefiets"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


@dataclass
class Listing:
    item_id: str
    title: str
    description: str
    price_eur: Optional[float]
    price_type: str
    city: str
    date: str
    condition: str
    frame_height: str
    groupset: str
    groupset_tier: Optional[int]
    url: str
    is_bargain: bool = False
    price_is_bid: bool = False
    is_new: bool = False
    first_seen: str = ""
    ref_label: str = ""
    ref_original_price: Optional[float] = None
    ref_score: str = ""
    ref_pct_of_original: Optional[float] = None
    ref_specs: str = ""
    ref_better: bool = False
    ref_market_avg: Optional[float] = None
    ref_market_count: int = 0
    pct_of_median: Optional[float] = None
    price_dropped: bool = False
    price_drop_from: Optional[float] = None
    # Counts usable bids only (see usable_bid_values()) — the same count
    # resolve_bid_price() bases the price on, so a listing's price and its
    # bid_count never tell two different stories about the same raw list.
    # None (lookup never ran) and 0 (ran, nothing usable) are not the same.
    bid_count: Optional[int] = None
    bid_minimum: Optional[float] = None
    bid_minimum_pct_of_median: Optional[float] = None
    bid_open: bool = False
    deal_score: Optional[float] = None
    deal_label: str = ""
    deal_reasons: str = ""


LISTING_FIELDS = [f.name for f in dataclass_fields(Listing)]


def as_number(value) -> Optional[float]:
    """A number out of Marktplaats' JSON, or None when the field holds
    something else. Two shapes get through a plain isinstance check: a bool
    (True is an int in Python, so a stray "priceCents": true would read as one
    cent) and a number sent as a string, which then blows up on the division
    that follows. Neither shows up in the console, so both are cheap to
    exclude here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


PAGE_SIZE = 30

# The search API the site's own "sorteer op"/category menus call. The HTML
# page ignores sort parameters in its URL (tested: ?sortBy=... and the #sortBy
# fragment both come back unsorted), so sorting by date and restricting to a
# category server-side can only go through here.
SEARCH_API_PATH = "/lrp/api/search"
SORT_OPTIONS = {
    # Marktplaats' default ("Standaard"). Not by date: on a 40-page crawl of
    # "racefiets" today's listings were spread over all 40 pages, only 83 of
    # 314 on the first three — and 1200 result slots held just 951 distinct
    # listings, the rest repeats.
    "optimized": ("OPTIMIZED", "DECREASING"),
    "newest": ("SORT_INDEX", "DECREASING"),
}


class CrawlResult(list):
    """collect_listings()'s listings, plus whether the crawl provably saw
    every result for the query. Only then may the disappearance sweep treat
    "not seen" as "gone": Marktplaats stops paging at maxAllowedPageNumber
    (167 pages, ~5000 listings, for "racefiets" with 26000+ results), and a
    page that fails to load ends the crawl early."""

    def __init__(self, listings=(), complete: bool = False, note: str = ""):
        super().__init__(listings)
        self.complete = complete
        self.note = note


def check_page_offset(data: dict, page: int) -> None:
    """Marktplaats answers a page it doesn't like by redirecting to page 1
    rather than with an error — that's how every multi-word query used to
    get page 1 over and over. The response says which offset it served;
    refuse anything but the one asked for, so the crawl stops loudly instead
    of storing page 1 N times and calling it N pages."""
    pagination = (data.get("searchRequest") or {}).get("pagination") or {}
    offset = as_number(pagination.get("offset"))
    limit = as_number(pagination.get("limit")) or PAGE_SIZE
    if offset is not None and page > 1 and offset != (page - 1) * limit:
        raise RuntimeError(
            f"Marktplaats gaf offset {int(offset)} terug voor pagina {page} "
            f"(verwacht {(page - 1) * int(limit)}) — de paginering werkt niet meer zoals "
            "het script verwacht."
        )


def fetch_page(session: requests.Session, query: str, page: int) -> dict:
    """Fetch one Marktplaats search results page and return its embedded JSON data."""
    # The query goes into the URL *path*, so it has to be encoded as one.
    # requests leaves "?", "#" and "&" alone (they're legal in a URL, just not
    # in a path segment), so a query like "wat?" would turn into an empty
    # query string and a search for "wat". safe="" also catches a slash, which
    # would otherwise add a path segment. A space has to become "+", not
    # "%20": Marktplaats 301-redirects /q/giant%20defy/p/2/ to /q/giant+defy/
    # — page 1 — so every page of a multi-word query used to be page 1.
    quoted = quote_plus(query, safe="")
    path = f"/q/{quoted}/" if page <= 1 else f"/q/{quoted}/p/{page}/"
    resp = session.get(BASE_URL + path, timeout=15)
    resp.raise_for_status()

    match = NEXT_DATA_RE.search(resp.text)
    if not match:
        raise RuntimeError(
            "Could not find listing data on the page — Marktplaats may have "
            "changed its page structure or shown a verification challenge."
        )
    data = json.loads(match.group(1))
    result = data["props"]["pageProps"]["searchRequestAndResponse"]
    check_page_offset(result, page)
    return result


def fetch_api_page(
    session: requests.Session,
    query: str,
    page: int,
    sort: str = "optimized",
    category_filter: Optional[tuple[int, list[int]]] = None,
) -> dict:
    """Like fetch_page(), through the search API: same response shape, but
    it honours a sort order and a server-side category restriction.
    category_filter is (l1 id, [l2 ids]) as resolve_categories() makes it."""
    sort_by, sort_order = SORT_OPTIONS[sort]
    params = [
        ("query", query),
        ("limit", PAGE_SIZE),
        ("offset", (page - 1) * PAGE_SIZE),
        ("sortBy", sort_by),
        ("sortOrder", sort_order),
    ]
    if category_filter is not None:
        l1, l2s = category_filter
        params.append(("l1CategoryId", l1))
        # Plural and repeated: "l2CategoryId" (singular) is silently ignored
        # and returns every category.
        params.extend(("l2CategoryIds", l2) for l2 in l2s)
    resp = session.get(BASE_URL + SEARCH_API_PATH + "?" + urlencode(params), timeout=15)
    resp.raise_for_status()
    try:
        data = json.loads(resp.text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or "listings" not in data:
        raise RuntimeError(
            "De zoek-API van Marktplaats gaf geen advertentielijst terug — mogelijk is die "
            "gewijzigd of werd er een verificatie getoond. Draai zonder --sort/--category "
            "om de gewone zoekpagina te gebruiken."
        )
    check_page_offset(data, page)
    return data


CONFIG_MARKER = "window.__CONFIG__ = "


def extract_balanced_json(text: str, start: int) -> Optional[dict]:
    """Extract one JSON object starting at `start` (the opening '{'),
    respecting quoted strings, and return it parsed."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# Once the page structure changes, every single listing hits the same wall, so
# warn once per run instead of printing the same line a hundred times.
_bid_structure_warned = False


def warn_bid_structure_changed(detail: str) -> None:
    global _bid_structure_warned
    if _bid_structure_warned:
        return
    _bid_structure_warned = True
    print(
        f"warning: biedinformatie niet te lezen ({detail}) — Marktplaats heeft "
        "waarschijnlijk zijn paginastructuur gewijzigd. Biedprijzen en minimumbod "
        "blijven leeg; de rest van de run gaat gewoon door.",
        file=sys.stderr,
    )


def fetch_bid_info(session: requests.Session, vip_url: str) -> Optional[dict]:
    """Fetch a listing's own page and return its bidsInfo (current bids /
    minimum bid) — this isn't included in the search results for FAST_BID
    listings, only on the listing page itself (loaded client-side there via
    window.__CONFIG__).

    Returns None both when the page simply has no bid data (normal: not every
    listing is biddable) and when the page couldn't be read at all. Only the
    second case is worth a warning — without one, a changed page structure
    just looks like a run where nobody happened to be bidding."""
    resp = session.get(vip_url, timeout=15)
    resp.raise_for_status()

    marker_pos = resp.text.find(CONFIG_MARKER)
    if marker_pos == -1:
        warn_bid_structure_changed(f"{CONFIG_MARKER.strip()} niet gevonden")
        return None
    brace_pos = resp.text.find("{", marker_pos)
    if brace_pos == -1:
        warn_bid_structure_changed("geen JSON-object achter de marker")
        return None
    config = extract_balanced_json(resp.text, brace_pos)
    if config is None:
        warn_bid_structure_changed("JSON achter de marker niet te lezen")
        return None
    # "listing" can be present and null — .get()'s default only covers a
    # missing key, not a null value.
    return (config.get("listing") or {}).get("bidsInfo")


def usable_bid_values(bids_info: dict) -> list[float]:
    """The bid entries in bids_info["bids"] that carry a usable numeric
    value — anything else (a non-dict entry, a missing/unparseable value)
    isn't a bid we can act on. Used both to resolve the bid price and to
    count "how many bids are there" (bid_count), so the two never diverge."""
    bids = bids_info.get("bids") or []
    values = [as_number(b.get("value")) for b in bids if isinstance(b, dict)]
    return [v for v in values if v is not None]


def resolve_bid_price(bids_info: dict) -> Optional[float]:
    """The relevant "price" for a bidding listing: the current highest bid
    if there is one, otherwise the minimum bid Marktplaats will accept."""
    # A bid entry without a usable value is not worth taking the run down for;
    # fall back to the minimum bid as if there were no bids at all.
    values = usable_bid_values(bids_info)
    if values:
        return max(values) / 100
    minimum = real_minimum_bid(bids_info)
    if minimum is not None:
        return minimum
    return None


def real_minimum_bid(bids_info: dict) -> Optional[float]:
    """currentMinimumBid in euros, or None when there is no minimum.
    Marktplaats sends -1 for "bieden zonder minimum" (seen on every FAST_BID
    listing without bids we checked, 2026-09-22), and 0 means the same. The
    old truthiness test let -1 through as a price of EUR -0.01, which
    scored every such listing 100/100 "Topdeal" at "min. €-0"."""
    minimum = as_number(bids_info.get("currentMinimumBid"))
    if minimum is None or minimum <= 0:
        return None
    return minimum / 100


def enrich_bid_listings(
    listings: list[Listing],
    delay: float,
    mode: str = "fast",
    session: Optional[requests.Session] = None,
) -> None:
    """Fetch bid details from bidding listings' own pages. FAST_BID listings
    report €0 in search results, so without this they have no usable price at
    all; MIN_BID listings do report an asking price, so for those this adds
    the minimum bid that's actually accepted (usually lower) and how many
    bids have already been placed (mode "all").

    mode: "fast" (default, FAST_BID only), "all" (also MIN_BID), "none".
    """
    if mode == "none":
        return

    targets = [l for l in listings if l.price_type == "FAST_BID" and l.price_eur is None]
    if mode == "all":
        targets += [l for l in listings if l.price_type == "MIN_BID"]
    if not targets:
        return

    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})

    print(f"Biedprijzen ophalen voor {len(targets)} bied-advertenties...", file=sys.stderr)
    for i, listing in enumerate(targets, start=1):
        try:
            bids_info = fetch_bid_info(session, listing.url)
        except requests.RequestException as exc:
            print(f"  warning: kon bod niet ophalen voor {listing.item_id}: {exc}", file=sys.stderr)
            continue

        if bids_info:
            # bid_count counts usable bids, not raw entries — a bid without
            # a parseable value doesn't move resolve_bid_price() either, so
            # the two must count the same thing (see usable_bid_values()).
            listing.bid_count = len(usable_bid_values(bids_info))
            listing.bid_minimum = real_minimum_bid(bids_info)
            price = resolve_bid_price(bids_info)
            # A MIN_BID listing already has a price from the search results
            # (what the seller is asking) and Marktplaats will accept a
            # *lower* minimum bid than that — seen in the wild: asking €47.50,
            # minimum bid €35. Those are two different numbers, so the asking
            # price stays the price (otherwise these listings would look
            # cheaper than fixed-price ones purely for being biddable) and the
            # minimum lands in bid_minimum. Only a real bid above the asking
            # price replaces it: below that bid the listing can't be had.
            raw_bids = bids_info.get("bids") or []
            if price is not None and (
                listing.price_eur is None or (raw_bids and price > listing.price_eur)
            ):
                listing.price_eur = price
                listing.price_is_bid = True

        print(f"  {i}/{len(targets)} verwerkt", file=sys.stderr)
        if i < len(targets):
            time.sleep(delay)


def extract_dominant_category(search_response: dict) -> Optional[int]:
    """Marktplaats flags the category a query is really about (dominant:
    true) in its RelevantCategories facet. Past a certain page depth its
    search loosens to fuzzy/partial word matches and starts returning
    listings from unrelated categories (e.g. "racefiets" eventually pulling
    in PS2 games because their titles contain "racer"); this lets us filter
    those back out."""
    for facet in search_response.get("facets", []):
        if facet.get("key") == "RelevantCategories":
            dominant = [c for c in facet.get("categories", []) if c.get("dominant")]
            if not dominant:
                return None
            # For an ambiguous query Marktplaats can flag more than one
            # category as dominant (e.g. "boxen" flags both baby playpens
            # and speakers) — the one with the most matches is the real one.
            # `or 0`: a null count would come back out of .get() as None and
            # take max() down comparing it to an int, same as a count that
            # arrives as a string.
            return max(dominant, key=lambda c: as_number(c.get("histogramCount")) or 0).get("id")
    return None


def extract_attribute(raw_listing: dict, key: str) -> str:
    for group in ("attributes", "extendedAttributes"):
        # `or []`: Marktplaats can send the key with a null value, and the
        # default of .get() only covers a missing key.
        for attr in raw_listing.get(group) or []:
            if attr.get("key") == key:
                return attr.get("value", "")
    return ""


# Marktplaats groups frame height into fixed buckets (e.g. "53 tot 57 cm")
# rather than exposing an exact size, so filtering can only match on
# whichever buckets overlap the requested range.
FRAME_HEIGHT_PATTERNS = [
    (re.compile(r"^Minder dan (\d+)", re.I), lambda m: (0.0, float(m.group(1)))),
    (re.compile(r"^(\d+)\s*tot\s*(\d+)", re.I), lambda m: (float(m.group(1)), float(m.group(2)))),
    (re.compile(r"^(\d+)\s*cm of meer", re.I), lambda m: (float(m.group(1)), float("inf"))),
    (re.compile(r"^(\d+(?:[.,]\d+)?)\s*cm$", re.I), lambda m: (float(m.group(1).replace(",", ".")),) * 2),
]


def frame_height_bounds(value: str) -> Optional[tuple[float, float]]:
    """Parse a Marktplaats frame-height bucket string into a (min, max) cm range."""
    value = value.strip()
    for pattern, to_bounds in FRAME_HEIGHT_PATTERNS:
        match = pattern.match(value)
        if match:
            return to_bounds(match)
    return None


# Groupset isn't a structured Marktplaats field, so this is detected from
# free text (title + description) by keyword. Tiers are on a rough unified
# 1-6 scale (entry to top-of-the-line) so groupsets from different brands
# can be compared: Shimano Claris/Sora/Tiagra/105/Ultegra/Dura-Ace, SRAM
# Apex/Rival/Force/Red, Campagnolo Veloce/Centaur/Chorus/Record(/Super
# Record). SRAM/Campagnolo tier words are ambiguous English/Dutch words on
# their own ("force", "record", ...), so those require the brand name to
# also appear somewhere in the text.
GROUPSET_CATALOG = [
    ("Shimano", "Dura-Ace", re.compile(r"dura[\s-]?ace", re.I), 6, False),
    ("Shimano", "Ultegra", re.compile(r"\bultegra\b", re.I), 5, False),
    ("Shimano", "105", re.compile(r"(?<!\d)\b105\b(?!\s*(cm|euro|eur|,-|km|mm|kg))", re.I), 4, False),
    ("Shimano", "Tiagra", re.compile(r"\btiagra\b", re.I), 3, False),
    ("Shimano", "Sora", re.compile(r"\bsora\b", re.I), 2, False),
    ("Shimano", "Claris", re.compile(r"\bclaris\b", re.I), 1, False),
    ("SRAM", "Red", re.compile(r"\bred\b", re.I), 6, True),
    ("SRAM", "Force", re.compile(r"\bforce\b", re.I), 5, True),
    ("SRAM", "Rival", re.compile(r"\brival\b", re.I), 4, True),
    ("SRAM", "Apex", re.compile(r"\bapex\b", re.I), 3, True),
    ("Campagnolo", "Super Record", re.compile(r"super\s*record", re.I), 6, True),
    ("Campagnolo", "Record", re.compile(r"\brecord\b", re.I), 5, True),
    ("Campagnolo", "Chorus", re.compile(r"\bchorus\b", re.I), 4, True),
    ("Campagnolo", "Centaur", re.compile(r"\bcentaur\b", re.I), 3, True),
    ("Campagnolo", "Veloce", re.compile(r"\bveloce\b", re.I), 2, True),
]
# Di2 is Shimano's electronic groupset, eTap and AXS are SRAM's — a mention of
# one says nothing about a groupset from the other brand. (Campagnolo's EPS is
# deliberately absent: no rows in the catalog need it yet.)
ELECTRONIC_MARKERS = {
    "Shimano": re.compile(r"\bdi2\b", re.I),
    "SRAM": re.compile(r"\betap\b|\baxs\b", re.I),
}
# The marker has to belong to the same phrase as the groupset name: close by,
# with nothing but words, digits, spaces, hyphens or slashes in between.
# "Shimano Ultegra R8050 Di2" is one name; in "Shimano 105, Di2-upgrade
# mogelijk" the comma separates the groupset that's for sale from a sales
# pitch about one that isn't, and tagging that 105 as electronic would put a
# wrong spec in front of every later comparison.
ELECTRONIC_MAX_GAP = 30
ELECTRONIC_GAP_RE = re.compile(r"[\w\s/-]*")


def mentions_electronic(text: str, brand: str, groupset_match: re.Match) -> bool:
    """Whether `text` says the groupset found at `groupset_match` is the
    electronic version of itself."""
    marker = ELECTRONIC_MARKERS.get(brand)
    if marker is None:
        return False
    for found in marker.finditer(text):
        between = (
            text[groupset_match.end():found.start()]
            if found.start() >= groupset_match.end()
            else text[found.end():groupset_match.start()]
        )
        if len(between) <= ELECTRONIC_MAX_GAP and ELECTRONIC_GAP_RE.fullmatch(between):
            return True
    return False


def detect_groupset(text: str) -> tuple[str, Optional[int]]:
    """Best-effort groupset detection from free text. Returns (label, tier)
    for the highest-tier match found, or ("", None) if nothing recognized."""
    text_lower = text.lower()
    best_label = ""
    best_tier: Optional[int] = None
    best_brand = ""
    best_match: Optional[re.Match] = None
    for brand, name, pattern, tier, needs_brand in GROUPSET_CATALOG:
        if needs_brand and brand.lower() not in text_lower:
            continue
        match = pattern.search(text)
        if match and (best_tier is None or tier > best_tier):
            best_tier = tier
            best_label = f"{brand} {name}"
            best_brand = brand
            best_match = match

    if best_match is not None and mentions_electronic(text, best_brand, best_match):
        best_label += " (elektronisch)"

    return best_label, best_tier


# --- Spec extraction beyond groupset ----------------------------------------
#
# PLAN_FIETSWAARDE.md fase 2: more structured fields, detected the same
# best-effort way as the groupset above. These are not Listing fields — they
# don't feed the report or the CSV/JSON files (adding them there would shift
# every existing column, see LISTING_FIELDS/append_bargain_log) — they go
# straight to the `spec` table via db.sync_listing_specs(). Precision over
# coverage throughout: a spec extract_specs() isn't confident about is left
# out entirely rather than guessed, because a wrong spec silently pollutes
# the comps fase 3 builds on top of it.

FRAME_MATERIAL_PATTERNS = [
    ("carbon", re.compile(r"\bcarbon\b", re.I)),
    ("titanium", re.compile(r"\btita(?:a)?n(?:ium)?\b", re.I)),
    ("aluminium", re.compile(r"\b(?:aluminium|alu)\b", re.I)),
    ("staal", re.compile(r"\b(?:staal|stalen|steel|chromoly|cro-?mo)\b", re.I)),
]
# "Carbon" (or aluminium, ...) in an ad is as often about the wheels as the
# frame — "aluminium frame, carbon wielset" is a common combination on
# exactly this kind of bike (see mijn_fiets.md). A material word is only
# trusted for frame_material within its own clause (split on . , ;): a
# clause naming a wheel word without also naming "frame" is a wheel mention,
# not a frame one, and is skipped in favor of another clause/material. When a
# clause names both a frame word and a wheel word, the clause alone can't
# say which one the material belongs to, so proximity is used as a vangnet:
# whichever word — "frame" or the wheel word — sits closer to the material
# mention wins. This only kicks in for that ambiguous case; it doesn't
# replace the material-first outer loop above it.
WHEEL_CONTEXT_WORD_RE = re.compile(r"\b(?:velg\w*|wiel\w*|wheel\w*)\b", re.I)
FRAME_WORD_RE = re.compile(r"\bframe\w*\b", re.I)
CLAUSE_SPLIT_RE = re.compile(r"[.,;]")


def _nearest_word_distance(
    clause: str, match: "re.Match[str]", word_re: "re.Pattern[str]"
) -> Optional[int]:
    """Character distance from `match` to the nearest word_re match in
    `clause`, or None if word_re doesn't occur at all."""
    best: Optional[int] = None
    for word_match in word_re.finditer(clause):
        if word_match.end() <= match.start():
            distance = match.start() - word_match.end()
        elif match.end() <= word_match.start():
            distance = word_match.start() - match.end()
        else:
            distance = 0
        if best is None or distance < best:
            best = distance
    return best


def detect_frame_material(text: str) -> Optional[str]:
    clauses = CLAUSE_SPLIT_RE.split(text)
    for label, pattern in FRAME_MATERIAL_PATTERNS:
        for clause in clauses:
            match = pattern.search(clause)
            if not match:
                continue
            has_wheel_word = bool(WHEEL_CONTEXT_WORD_RE.search(clause))
            has_frame_word = bool(FRAME_WORD_RE.search(clause))
            if has_wheel_word and not has_frame_word:
                continue
            if has_wheel_word and has_frame_word:
                frame_dist = _nearest_word_distance(clause, match, FRAME_WORD_RE)
                wheel_dist = _nearest_word_distance(clause, match, WHEEL_CONTEXT_WORD_RE)
                if frame_dist is None or (wheel_dist is not None and wheel_dist <= frame_dist):
                    continue
            return label
    return None

# Order matters: the more specific hydraulic/mechanical phrasing has to be
# tried before the bare "schijfrem" pattern, or it would win first and the
# brake type would never come out more specific than "disc".
BRAKE_TYPE_PATTERNS = [
    (
        "hydraulische schijfrem",
        re.compile(r"hydraulisch\w*\s+schijfrem\w*|hydraulic\s+disc", re.I),
    ),
    (
        "mechanische schijfrem",
        re.compile(r"mechanisch\w*\s+schijfrem\w*|mechanical\s+disc", re.I),
    ),
    ("schijfrem", re.compile(r"\bschijfrem\w*\b|\bdisc[\s-]?brakes?\b", re.I)),
    ("velrem", re.compile(r"\bvelg?rem\w*\b|\brim[\s-]?brakes?\b", re.I)),
]

# Restricted to the range that's actually used on a road bike (8-13 sprockets
# at the cassette) — a bare "22 speed" or "24 speed" almost always turns out
# to describe hub gears or a kids' bike miscounting front x rear, not a
# racefiets groupset, so those are deliberately left unmatched.
SPEEDS_RE = re.compile(r"\b(8|9|10|11|12|13)[\s-]*(?:speed|spd|versnellingen|v)\b", re.I)

WHEEL_TYPE_PATTERNS = [
    (
        "carbon",
        re.compile(
            r"carbon\s*(?:velg\w*|wiel\w*|wheel\w*)|(?:velg\w*|wiel\w*|wheel\w*)"
            r"[^.,;]{0,15}\bcarbon\b",
            re.I,
        ),
    ),
    (
        "aluminium",
        re.compile(
            r"(?:aluminium|alu)\s*(?:velg\w*|wiel\w*)|(?:velg\w*|wiel\w*)"
            r"[^.,;]{0,15}\b(?:aluminium|alu)\b",
            re.I,
        ),
    ),
]

# Requires an explicit label ("bouwjaar", "model(jaar)", "uit") rather than
# any bare 20xx number in the text — a price, a phone number in the
# description or "sinds 2018 in bezit" would otherwise all misread as the
# bike's model year.
MODEL_YEAR_RE = re.compile(r"\b(?:bouwjaar|model(?:jaar)?|uit)\s*[:\s]*((?:19|20)\d{2})\b", re.I)

WEIGHT_KG_RE = re.compile(r"\b(\d{1,2}[.,]\d{1,2})\s*kg\b", re.I)

POWERMETER_RE = re.compile(
    r"\bpowermeter\b|\bpower\s*meter\b|\bvermogensmeter\b|\bquarq\b|\bstages\b|"
    r"\bfavero\b|\b4iiii\b|\bsrm\b",
    re.I,
)
# has_computer is relative to what the owner already has (see PLAN_FIETSWAARDE.md
# §7 — he keeps his own Wahoo Elemnt Roam), but that weighting is scoring.py's
# job (fase 4); extraction here only records that a computer was mentioned.
COMPUTER_RE = re.compile(
    r"\bfietscomputer\b|\bbike\s*computer\b|\bgarmin\b|\bwahoo\b|\belemnt\b|\bedge\s*\d+\b",
    re.I,
)


def _first_pattern_label(text: str, patterns: list[tuple[str, "re.Pattern[str]"]]) -> Optional[str]:
    for label, pattern in patterns:
        if pattern.search(text):
            return label
    return None


def extract_specs(text: str) -> dict[str, str]:
    """Best-effort structured specs from free text (title + description),
    beyond the groupset already covered by detect_groupset(). Only keys that
    were confidently recognized are present; nothing is guessed for the
    rest."""
    specs: dict[str, str] = {}

    material = detect_frame_material(text)
    if material:
        specs["frame_material"] = material

    brake = _first_pattern_label(text, BRAKE_TYPE_PATTERNS)
    if brake:
        specs["brake_type"] = brake

    speeds_match = SPEEDS_RE.search(text)
    if speeds_match:
        specs["speeds"] = speeds_match.group(1)

    wheel = _first_pattern_label(text, WHEEL_TYPE_PATTERNS)
    if wheel:
        specs["wheel_type"] = wheel

    year_match = MODEL_YEAR_RE.search(text)
    if year_match:
        specs["model_year"] = year_match.group(1)

    weight_match = WEIGHT_KG_RE.search(text)
    if weight_match:
        specs["weight_kg"] = weight_match.group(1).replace(",", ".")

    if POWERMETER_RE.search(text):
        specs["has_powermeter"] = "1"
    if COMPUTER_RE.search(text):
        specs["has_computer"] = "1"

    return specs


def extract_listing_specs(listings: list[Listing]) -> dict[str, dict[str, str]]:
    """extract_specs() for every listing, keyed by item_id, ready to hand to
    db.sync_listing_specs()."""
    return {
        listing.item_id: extract_specs(f"{listing.title} {listing.description}")
        for listing in listings
    }


def parse_listing(raw: dict) -> Listing:
    price_info = raw.get("priceInfo") or {}
    price_cents = as_number(price_info.get("priceCents"))
    price_type = price_info.get("priceType", "")
    # priceCents is 0 for listings with no real price shown (e.g. an
    # unstarted bid or "see description") except when priceType is FREE,
    # where 0 genuinely means the item is free.
    has_real_price = price_cents is not None and (price_cents > 0 or price_type == "FREE")
    price_eur = price_cents / 100 if has_real_price else None

    vip_url = raw.get("vipUrl", "")
    url = BASE_URL + vip_url if vip_url.startswith("/") else vip_url

    title = raw.get("title", "")
    description = raw.get("description", "")
    groupset, groupset_tier = detect_groupset(f"{title} {description}")

    return Listing(
        item_id=raw.get("itemId", ""),
        title=title,
        description=description,
        price_eur=price_eur,
        price_type=price_type,
        city=raw.get("location", {}).get("cityName", ""),
        date=raw.get("date", ""),
        condition=extract_attribute(raw, "condition"),
        frame_height=extract_attribute(raw, "frameHeight"),
        groupset=groupset,
        groupset_tier=groupset_tier,
        url=url,
        # A MIN_BID listing's search-result price is what the seller is
        # asking; the minimum bid Marktplaats actually accepts (usually lower)
        # and the number of bids placed are only on the listing page itself,
        # so bid_minimum/bid_count stay empty until --bid-lookup all fills
        # them in.
        price_is_bid=price_type in ("MIN_BID", "FAST_BID"),
    )


def relevant_categories(search_response: dict) -> list[dict]:
    for facet in search_response.get("facets", []):
        if facet.get("key") == "RelevantCategories":
            return facet.get("categories") or []
    return []


def resolve_categories(search_response: dict, wanted: list[str]) -> tuple[int, list[int]]:
    """Turn --category values (a Marktplaats category key such as
    "fietsonderdelen", or its number) into what fetch_api_page() sends: one
    main category and the subcategories under it. Resolved against the
    query's own RelevantCategories facet, which lists every category the
    query has results in, with its parent — so a category that isn't in
    there has nothing to find anyway, and the error can list what is."""
    by_name: dict[str, dict] = {}
    for cat in relevant_categories(search_response):
        if cat.get("id") is None:
            continue
        by_name[str(cat["id"])] = cat
        if cat.get("key"):
            by_name[str(cat["key"]).lower()] = cat

    chosen = []
    for name in wanted:
        cat = by_name.get(name.strip().lower())
        if cat is None:
            counted = [c for c in relevant_categories(search_response) if c.get("histogramCount")]
            counted.sort(key=lambda c: as_number(c.get("histogramCount")) or 0, reverse=True)
            available = ", ".join(
                f"{c.get('key')} ({c.get('histogramCount')})" for c in counted[:10]
            )
            raise ValueError(
                f"categorie {name!r} komt niet voor in de resultaten voor deze zoekterm. "
                f"Wel: {available or 'geen'}"
            )
        chosen.append(cat)

    main_ids = {c.get("parentId") or c["id"] for c in chosen}
    if len(main_ids) > 1:
        raise ValueError(
            "de gekozen categorieën vallen onder verschillende hoofdcategorieën; "
            "Marktplaats zoekt er maar één tegelijk. Maak er twee zoekopdrachten van."
        )
    l1 = int(main_ids.pop())
    if any(not c.get("parentId") for c in chosen):
        # The main category itself was asked for: that already covers every
        # subcategory under it.
        return l1, []
    return l1, [int(c["id"]) for c in chosen]


# A "wanted" ad: someone looking to buy, listed in the same category as the
# things for sale. Nothing in the listing data marks it (adType and traits
# look like any other ad's), so the title is all there is. Only where the
# word stands alone — at the start, at the end, or in brackets — since "veel
# gezocht model" is a seller's sales pitch. Without this they came out on top:
# no price, a "bieden" button, and a 100/100 Topdeal.
WANTED_AD_RE = re.compile(
    r"^\W*gezocht\b|\(\s*gezocht\s*\)|(?<!veel )(?<!zeer )(?<!vaak )\bgezocht\W*$",
    re.I,
)


def is_wanted_ad(title: str) -> bool:
    return bool(WANTED_AD_RE.search(title or ""))


def other_dominant_categories(search_response: dict, kept: Optional[int]) -> list[dict]:
    return [
        c for c in relevant_categories(search_response) if c.get("dominant") and c.get("id") != kept
    ]


def collect_listings(
    query: str,
    pages: int,
    delay: float,
    session: Optional[requests.Session] = None,
    *,
    sort: str = "optimized",
    categories: Optional[list[str]] = None,
) -> CrawlResult:
    """Fetch listings page by page. pages <= 0 means "fetch everything
    Marktplaats allows browsing to" (it caps pagination at a few hundred
    listings regardless of the total match count).

    sort "newest" and categories go through the search API
    (fetch_api_page()); the default goes through the search page as it
    always has. With categories, the first request is an unrestricted one
    to resolve them (see resolve_categories()), and Marktplaats does the
    category filtering from there — instead of the dominant-category guess
    below, which keeps only one category."""
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})

    print(f"Zoeken naar '{query}' op Marktplaats...", file=sys.stderr)
    category_filter: Optional[tuple[int, list[int]]] = None
    if categories:
        try:
            first = fetch_api_page(session, query, 1, sort)
            category_filter = resolve_categories(first, categories)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"error: --category: {exc}", file=sys.stderr)
            return CrawlResult([], complete=False, note=f"--category: {exc}")
        time.sleep(delay)

    use_api = sort != "optimized" or category_filter is not None

    def fetch(page_number: int) -> dict:
        if use_api:
            return fetch_api_page(session, query, page_number, sort, category_filter)
        return fetch_page(session, query, page_number)

    listings: dict[str, Listing] = {}
    raw_ids: set = set()
    total_results: Optional[float] = None
    dominant_category: Optional[int] = None
    skipped_offtopic = 0
    skipped_without_id = 0
    skipped_wanted = 0
    fetch_error: Optional[str] = None
    reached_end = False
    page = 1
    while True:
        try:
            data = fetch(page)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"warning: failed to fetch page {page}: {exc}", file=sys.stderr)
            fetch_error = f"pagina {page} kon niet worden opgehaald"
            break

        raw_listings = data.get("listings", [])
        if not raw_listings:
            reached_end = True
            break

        if total_results is None:
            total_results = as_number(data.get("totalResultCount"))
        if dominant_category is None and category_filter is None:
            dominant_category = extract_dominant_category(data)
            others = other_dominant_categories(data, dominant_category)
            if dominant_category is not None and others:
                names = ", ".join(f"{c.get('key')} ({c.get('histogramCount')})" for c in others)
                print(
                    f"  let op: Marktplaats noemt voor '{query}' ook {names} als hoofdcategorie; "
                    "die worden overgeslagen. Neem ze mee met --category.",
                    file=sys.stderr,
                )

        for raw in raw_listings:
            if raw.get("itemId"):
                raw_ids.add(raw.get("itemId"))
            if dominant_category is not None and raw.get("categoryId") != dominant_category:
                skipped_offtopic += 1
                continue
            listing = parse_listing(raw)
            if not listing.item_id:
                # Listings are keyed by item id from here on (deduplicating
                # across pages, and everything the history remembers), so
                # without one they would overwrite each other and be "new"
                # forever. Rather drop them than merge two ads into one.
                skipped_without_id += 1
                continue
            if is_wanted_ad(listing.title):
                skipped_wanted += 1
                continue
            listings[listing.item_id] = listing

        # The key can be there with a null value (and .get()'s default only
        # covers a missing key), which would take both the min() below and the
        # page >= max_page test down with a TypeError. int(), because the page
        # number ends up in the progress line and "pagina 1/3.0" reads as a bug.
        site_max_page = as_number(data.get("maxAllowedPageNumber"))
        max_page = int(site_max_page) if site_max_page else page
        target = min(pages, max_page) if pages > 0 else max_page
        print(f"  pagina {page}/{target} opgehaald — {len(listings)} advertenties tot nu toe", file=sys.stderr)

        reached_requested_limit = pages > 0 and page >= pages
        reached_site_limit = page >= max_page
        if reached_site_limit:
            reached_end = True
        if reached_requested_limit or reached_site_limit:
            break
        page += 1
        time.sleep(delay)

    if skipped_without_id:
        print(
            f"  {skipped_without_id} advertentie(s) zonder item-id overgeslagen "
            "(niet uit elkaar te houden en niet te onthouden)",
            file=sys.stderr,
        )
    if skipped_wanted:
        print(
            f"  {skipped_wanted} 'gezocht'-advertentie(s) overgeslagen (iemand die zoekt, "
            "geen aanbod)",
            file=sys.stderr,
        )
    if skipped_offtopic:
        print(
            f"  {skipped_offtopic} advertenties buiten de hoofdcategorie overgeslagen "
            "(Marktplaats' zoekresultaten waaieren op diepere pagina's uit naar losse "
            "woord-matches)",
            file=sys.stderr,
        )

    # Complete = every result for the query went past us: no page failed,
    # paging ran to the end, and the distinct listings seen (before any
    # filtering) add up to the total Marktplaats reports. The last test is
    # what catches the page cap, and also the default sort's habit of
    # serving the same listing on several pages while skipping others.
    if fetch_error:
        complete, note = False, fetch_error
    elif not reached_end:
        complete, note = False, "niet alle pagina's opgehaald"
    elif total_results is not None and len(raw_ids) < total_results:
        complete = False
        note = (
            f"{len(raw_ids)} van de {int(total_results)} resultaten gezien — Marktplaats "
            "toont er niet meer, of herhaalde advertenties over pagina's heen"
        )
    else:
        complete, note = True, ""
    return CrawlResult(listings.values(), complete=complete, note=note)


def filter_by_price(
    listings: list[Listing], min_price: Optional[float], max_price: Optional[float]
) -> list[Listing]:
    """Drop listings outside the price range. A listing without a price at all
    passes: a FAST_BID reports none in the search results, and unknown isn't
    the same as out of range — it gets tested again once the bid lookup has
    given it a price."""
    if min_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur >= min_price]
    if max_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur <= max_price]
    return listings


def filter_by_frame_height(
    listings: list[Listing],
    min_height: Optional[float],
    max_height: Optional[float],
    keep_unknown: bool = False,
) -> list[Listing]:
    """keep_unknown decides what happens to a listing without a (readable)
    frame size. The CLI keeps them unless --strict-frame-height: on a
    40-page crawl of "racefiets", 76% of the bikes had no size filled in, so
    dropping them hid three out of four bikes — most of which just say
    "maat 56" in the text instead."""
    if min_height is None and max_height is None:
        return listings

    lo = min_height if min_height is not None else 0.0
    hi = max_height if max_height is not None else float("inf")

    result = []
    for listing in listings:
        bounds = frame_height_bounds(listing.frame_height)
        if bounds is None:
            if keep_unknown:
                result.append(listing)
            continue
        bucket_lo, bucket_hi = bounds
        if bucket_hi >= lo and bucket_lo <= hi:
            result.append(listing)
    return result


def market_prices(listings: list[Listing]) -> list[float]:
    """The prices that say something about what a thing costs here. A listing
    without a price is out for obvious reasons, and so is a EUR 0 one: that's
    a FREE listing (priceType FREE — see parse_listing), a giveaway rather
    than an asking price, and averaging it in drags every benchmark down."""
    return [l.price_eur for l in listings if l.price_eur]


def flag_bargains(listings: list[Listing], bargain_ratio: float) -> list[Listing]:
    priced = market_prices(listings)
    if len(priced) < 2:
        return listings

    median_price = statistics.median(priced)
    threshold = median_price * bargain_ratio
    for listing in listings:
        if listing.price_eur is not None:
            listing.pct_of_median = round(listing.price_eur / median_price * 100, 1)
            if listing.price_eur <= threshold:
                listing.is_bargain = True
        # What being the first bidder would cost, on the same scale — for a
        # listing whose accepted minimum bid sits well under the asking price,
        # that's the number that says whether it's worth a try.
        if listing.bid_minimum is not None:
            listing.bid_minimum_pct_of_median = round(
                listing.bid_minimum / median_price * 100, 1
            )
    return listings


def price_stats(listings: list[Listing]) -> dict:
    # Same definition as flag_bargains uses, so the median printed under the
    # table is the median the "% v. mediaan" column is measured against.
    priced = market_prices(listings)
    if not priced:
        return {"count": 0, "mean": None, "median": None}
    return {
        "count": len(priced),
        "mean": statistics.mean(priced),
        "median": statistics.median(priced),
    }


def existing_csv_header(path: str) -> Optional[list[str]]:
    """The header row of a CSV we're about to append to, or None when there
    isn't one yet (no file, an empty one, or one that opens with blank
    lines)."""
    try:
        with open(path, newline="", encoding=CSV_READ_ENCODING) as f:
            for row in csv.reader(f):
                # A blank first line reads as an empty row, not as no row at
                # all — and these files get hand-edited. Taken at face value
                # it's a header with no columns in it, which is neither the
                # "no header yet, write one" case nor a real header to append
                # under: the callers would write rows with no header above
                # them, or refuse to write at all over columns that aren't
                # there. Skip past the blanks to whatever the file really has.
                if any(cell.strip() for cell in row):
                    return row
    except FileNotFoundError:
        return None
    return None


def append_bargain_log(path: str, listings: list[Listing]) -> int:
    """Append newly-discovered bargains (is_new and is_bargain) to a running
    CSV log, so you keep a history of every bargain ever spotted instead of
    only the current snapshot. Returns how many rows were appended."""
    new_bargains = [l for l in listings if l.is_new and l.is_bargain]
    if not new_bargains:
        return 0

    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current_fields = ["logged_at"] + LISTING_FIELDS
    # An existing log was written with the columns of whatever version of
    # Listing wrote it. Writing today's columns under yesterday's header shifts
    # every value one place over as soon as a field is added anywhere but at
    # the very end of the dataclass — and the fields are grouped (ref_*, bid_*,
    # deal_*), so a new one lands in the middle by default. From that run on
    # the whole file reads as nonsense. The header on disk therefore wins, and
    # a column that doesn't fit in it is reported instead of silently landing
    # in the wrong one.
    existing_fields = existing_csv_header(path)
    fieldnames = existing_fields or current_fields
    missing = [name for name in current_fields if name not in fieldnames]
    if missing:
        print(
            f"warning: {path} heeft de kolommen van een oudere versie, dus "
            f"{', '.join(missing)} wordt niet gelogd. Hernoem of verplaats het "
            "bestand om met de huidige kolommen opnieuw te beginnen.",
            file=sys.stderr,
        )

    # No header found means the file is missing, empty, or holds nothing but
    # blank lines — no data to lose in any of those cases, so it's written
    # from scratch. Appending instead would leave the header sitting under a
    # blank first line, where csv.DictReader takes the blank for the header
    # and the file reads as columnless.
    with open(path, "a" if existing_fields else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if existing_fields is None:
            writer.writeheader()
        for listing in new_bargains:
            row = {"logged_at": logged_at, **asdict(listing)}
            # A column the file has but this version no longer fills stays
            # empty rather than failing the run.
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    return len(new_bargains)


# Save a CSV from Excel and it starts with a UTF-8 BOM, which lands in the
# first column's name ("\ufeffpattern") and makes every lookup by that name
# miss. Reading as utf-8-sig strips it when it's there and changes nothing
# when it isn't. Writing stays plain utf-8: we don't add one ourselves.
CSV_READ_ENCODING = "utf-8-sig"


def load_reference_market_stats(path: str) -> dict:
    """Build actual observed secondhand asking prices per reference model
    from every past run's price_history.csv rows — a self-growing market
    price database, distinct from the (often unknown/outdated) original
    retail price in reference_prices.csv."""
    try:
        with open(path, encoding=CSV_READ_ENCODING) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames or []
    except FileNotFoundError:
        return {}

    missing = [name for name in ("ref_label", "price_eur") if name not in fieldnames]
    if rows and missing:
        print(
            f"warning: {path} mist de kolom(men) {', '.join(missing)}; er worden geen "
            "2e-hands gemiddelden uit gehaald.",
            file=sys.stderr,
        )
        return {}

    by_label: dict[str, list[float]] = {}
    for row in rows:
        # A short row hands back None for its missing cells and a hand-edited
        # one can hold anything at all; neither is worth taking the run down
        # for. EUR 0 is skipped for the same reason as in market_prices().
        try:
            price = float(row.get("price_eur"))
        except (TypeError, ValueError):
            continue
        label = (row.get("ref_label") or "").strip()
        if not label or not price:
            continue
        by_label.setdefault(label, []).append(price)

    stats = {}
    for label, prices in by_label.items():
        stats[label] = {
            "count": len(prices),
            "mean": statistics.mean(prices),
            "median": statistics.median(prices),
        }
    return stats


def apply_reference_market_stats(listings: list[Listing], stats: dict) -> None:
    for listing in listings:
        if listing.ref_label and listing.ref_label in stats:
            s = stats[listing.ref_label]
            listing.ref_market_avg = s["mean"]
            listing.ref_market_count = s["count"]


PRICE_HISTORY_FIELDS = ["date", "ref_label", "item_id", "price_eur", "title"]


def append_reference_price_observations(path: str, listings: list[Listing]) -> int:
    """Log one row per newly-seen listing that matched a reference model,
    so future runs can compute the real observed secondhand price for
    that model. Only logs on first sighting (is_new) so the same active
    ad isn't counted again every run."""
    # EUR 0 is a giveaway, not an asking price; recording it would pull the
    # model's observed secondhand average down for good. A price that is a
    # standing bid is out for the mirror-image reason: it's a number caught
    # mid-auction that only goes up from there, so it says more about how long
    # the auction still had to run than about what the model costs. A bid
    # listing nobody has bid on yet keeps its seller's floor price, which is
    # exactly what an asking price is, and stays in.
    observations = [
        l
        for l in listings
        if l.is_new and l.ref_label and l.price_eur and not (l.price_is_bid and l.bid_count)
    ]
    if not observations:
        return 0

    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # This file feeds the observed secondhand average, so a misaligned append
    # doesn't just look wrong, it skews every future valuation. If the header
    # on disk isn't the one we write, say so and record nothing this run.
    existing_fields = existing_csv_header(path)
    if existing_fields is not None and existing_fields != PRICE_HISTORY_FIELDS:
        print(
            f"warning: {path} heeft andere kolommen dan verwacht "
            f"({', '.join(existing_fields)}); er wordt niets bijgeschreven om "
            "het bestand niet te vervuilen.",
            file=sys.stderr,
        )
        return 0

    # "w" when there's no header: see append_bargain_log() — a file of blank
    # lines has nothing in it worth appending to.
    with open(path, "a" if existing_fields else "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if existing_fields is None:
            writer.writerow(PRICE_HISTORY_FIELDS)
        for listing in observations:
            writer.writerow([logged_at, listing.ref_label, listing.item_id, listing.price_eur, listing.title])
    return len(observations)


def load_history(path: str) -> dict:
    try:
        # utf-8-sig here too: a history file opened and saved in an editor can
        # come back with a BOM, and json.load() rejects that outright — which
        # this function would report as "no history at all".
        with open(path, encoding=CSV_READ_ENCODING) as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(history, dict):
        # Valid JSON, wrong shape — a hand-edited file, or something else
        # entirely under this name. Treating it as "no history" is what
        # happens for an unreadable file too; saying so beats an
        # AttributeError three functions later.
        print(
            f"warning: {path} bevat geen advertentie-geschiedenis "
            f"({type(history).__name__}); genegeerd, alles telt als nieuw.",
            file=sys.stderr,
        )
        return {}
    return history


def save_history(path: str, history: dict) -> None:
    """Write the history, all of it or none of it. Opening the real file in
    "w" mode truncates it first, so a run that dies halfway (Ctrl-C, a full
    disk) leaves half a JSON document behind — and load_history() reads an
    unparseable file as "no history at all", which silently makes every
    listing new again and throws away every first_seen date you had."""
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def apply_history(listings: list[Listing], history: dict) -> dict:
    """Mark each listing as new/seen-before using the on-disk history, and
    return the updated history to be saved."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for listing in listings:
        entry = history.get(listing.item_id)
        if entry is None:
            listing.is_new = True
            listing.first_seen = now
            history[listing.item_id] = {
                "first_seen": now,
                "last_seen": now,
                "title": listing.title,
                "last_price": listing.price_eur,
            }
        else:
            listing.is_new = False
            listing.first_seen = entry.get("first_seen", now)
            old_price = entry.get("last_price")
            if (
                old_price is not None
                and listing.price_eur is not None
                and listing.price_eur < old_price
            ):
                listing.price_dropped = True
                listing.price_drop_from = old_price
            entry["last_seen"] = now
            # A price we couldn't see this run — a FAST_BID under
            # --bid-lookup none — is unknown, not gone. Writing None over the
            # last known price would throw away the baseline the next price
            # drop is measured against.
            if listing.price_eur is not None:
                entry["last_price"] = listing.price_eur
    return history


def load_reference_data(path: str) -> list[dict]:
    """Load a user-maintained reference file (pattern,label,original_price_eur,
    score,specs,better_than_baseline) used to recognize known models and
    compare the asking price against what they cost new. Returns [] if the
    file doesn't exist — this feature is entirely optional."""
    try:
        with open(path, encoding=CSV_READ_ENCODING) as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return []

    reference = []
    for row in rows:
        pattern = (row.get("pattern") or "").strip()
        if not pattern:
            continue
        try:
            compiled = re.compile(pattern, re.I)
        except re.error as exc:
            print(f"warning: skipping invalid pattern in {path}: {pattern!r} ({exc})", file=sys.stderr)
            continue
        original_price_raw = (row.get("original_price_eur") or "").strip()
        try:
            original_price = float(original_price_raw) if original_price_raw else None
        except ValueError:
            # This column gets filled in by hand, so "ca. 300" or "?" is a
            # matter of time. An empty new-price costs one signal; a crash
            # costs the whole run.
            print(
                f"warning: {path}: onleesbare nieuwprijs {original_price_raw!r} bij "
                f"patroon {pattern!r} — als leeg behandeld",
                file=sys.stderr,
            )
            original_price = None
        reference.append(
            {
                "regex": compiled,
                "pattern": pattern,
                "label": (row.get("label") or pattern).strip(),
                "original_price_eur": original_price,
                "score": (row.get("score") or "").strip(),
                "specs": (row.get("specs") or "").strip(),
                "better": (row.get("better_than_baseline") or "").strip().lower() in ("1", "true", "yes", "ja"),
            }
        )
    return reference


def apply_reference_data(listings: list[Listing], reference: list[dict]) -> dict[str, list[str]]:
    """Match each listing's title+description against the reference rows
    (first match in file order wins — put more specific patterns first) and
    fill in ref_* fields when found.

    PLAN_FIETSWAARDE.md fase 2 wants every matching model recorded for
    `listing_model`, not just the one that wins the report's columns, so this
    no longer stops at the first hit. What lands on Listing.ref_* is
    unchanged from before though — still only the first match in file order —
    so the report and the "Beter dan referentie" filter read exactly as they
    did. The full match list (every pattern that matched, in file order) is
    returned separately instead, keyed by item_id, for
    db.sync_listing_models() to write."""
    matches: dict[str, list[str]] = {}
    if not reference:
        return matches
    for listing in listings:
        haystack = f"{listing.title} {listing.description}"
        first = True
        for row in reference:
            if row["regex"].search(haystack):
                if first:
                    listing.ref_label = row["label"]
                    listing.ref_original_price = row["original_price_eur"]
                    listing.ref_score = row["score"]
                    listing.ref_specs = row["specs"]
                    listing.ref_better = row["better"]
                    if listing.price_eur is not None and row["original_price_eur"]:
                        listing.ref_pct_of_original = round(
                            listing.price_eur / row["original_price_eur"] * 100, 1
                        )
                    first = False
                matches.setdefault(listing.item_id, []).append(row["pattern"])
    return matches


def apply_bid_flags(listings: list[Listing]) -> None:
    """Mark bidding listings nobody has bid on yet — for those the seller's
    minimum bid is still the whole asking price, so they're the ones where
    you can actually still get in cheap. Listings whose bid count was never
    looked up (MIN_BID without --bid-lookup all) stay unmarked: unknown is
    not the same as zero."""
    for listing in listings:
        listing.bid_open = listing.price_is_bid and listing.bid_count == 0


def open_bid_listings(listings: list[Listing]) -> list[Listing]:
    return [l for l in listings if l.bid_open]


def bid_listings(listings: list[Listing]) -> list[Listing]:
    return [l for l in listings if l.price_is_bid]


# Marktplaats' accepted minimum bid is sometimes a cent under the asking
# price (€174.99 on a €175 listing) — that's not a discount worth pointing at,
# so only a minimum this far below the asking price counts as one.
MEANINGFUL_MINIMUM_BID_RATIO = 0.98


def format_bid_info(listing: Listing) -> str:
    """Short human-readable summary of a listing's bid state."""
    if not listing.price_is_bid:
        return ""
    bits = []
    if listing.bid_minimum is not None:
        minimum = f"min. €{listing.bid_minimum:.0f}"
        # The "% v. mediaan" here is an invitation: that's what opening the
        # bidding would cost you. It only holds while nobody has bid — after
        # that the listing can't be had for the minimum any more (the price
        # column has moved up to the standing bid, see resolve_bid_price), so
        # presenting it as a cheap way in would be wrong. The minimum itself
        # stays visible; only the framing goes. And as before, it's only worth
        # spelling out when it's really under the asking price, otherwise it
        # just repeats the "% v. mediaan" column.
        #
        # An unknown bid count is not a zero one (the same rule apply_bid_flags
        # applies to VRIJ TE BIEDEN): if we never counted the bids, we can't
        # claim nobody has bid.
        if (
            listing.bid_minimum_pct_of_median is not None
            and listing.bid_count == 0
            and (
                listing.price_eur is None
                or listing.bid_minimum <= listing.price_eur * MEANINGFUL_MINIMUM_BID_RATIO
            )
        ):
            minimum += f" ({listing.bid_minimum_pct_of_median:.0f}% v. mediaan)"
        bits.append(minimum)
    if listing.bid_count is None:
        bits.append("biedingen onbekend")
    elif listing.bid_count == 0:
        bits.append("nog geen bod")
    elif listing.bid_count == 1:
        bits.append("1 bod")
    else:
        bits.append(f"{listing.bid_count} biedingen")
    return " · ".join(bits)


# --- Deal score -------------------------------------------------------------
#
# The report already carries several independent price signals (share of the
# median of this search, share of the original retail price, share of the
# secondhand average observed in past runs, price drops, better-than-baseline).
# Judging a listing meant weighing those columns by hand every time, so they're
# folded into one 0-100 number: 50 is roughly "priced like everything else",
# higher is cheaper than its benchmarks.
#
# Each signal is a price ratio (1.0 = exactly at that benchmark) mapped onto
# 0-100 between a "this is a steal" and a "this is expensive" ratio, then
# averaged with the weights below. Only signals that are actually available
# count, and the weights are renormalized over those, so a listing with no
# reference data is scored on what's known instead of being penalized for the
# missing columns. That does mean a score can rest on a single signal, so
# every listing also carries deal_reasons — the signals that actually went
# into its score, shown in the console and as the HTML score cell's tooltip.

# (best ratio -> 100, worst ratio -> 0, weight). Each range is centered so
# that sitting exactly on its benchmark scores 50 — that way a 50 means the
# same thing ("priced normally") no matter which signals a listing happened to
# have, and the weights below are the only thing that shifts the balance.
SCORE_MEDIAN_RANGE = (0.30, 1.70, 1.0)
# The secondhand average is the strongest signal — it's what this exact model
# actually goes for, observed first-hand, rather than a retail price from
# whenever it was new. It needs a couple of sightings to mean anything.
SCORE_MARKET_RANGE = (0.40, 1.60, 2.0)
SCORE_MARKET_MIN_OBSERVATIONS = 2
# Original retail price is the weakest: for anything vintage, every listing
# sits far below it, so it barely separates a good deal from a bad one.
SCORE_ORIGINAL_RANGE = (0.15, 0.85, 0.75)

SCORE_DROP_BONUS_MAX = 10.0
SCORE_BETTER_BONUS = 8.0

# (score at or above -> label, CSS class for the HTML score pill), best first.
SCORE_LABELS = [
    (80.0, "Topdeal", "top"),
    (65.0, "Goede deal", "good"),
    (45.0, "Redelijk", "ok"),
    (25.0, "Aan de prijs", "low"),
    (0.0, "Duur", "low"),
]
TOP_DEAL_SCORE = SCORE_LABELS[0][0]


def ratio_score(ratio: float, best: float, worst: float) -> float:
    """Map a price ratio (1.0 = at the benchmark) onto 0-100, where `best`
    (a low ratio, i.e. cheap) is 100 and `worst` (a high ratio) is 0."""
    if ratio <= best:
        return 100.0
    if ratio >= worst:
        return 0.0
    return (worst - ratio) / (worst - best) * 100.0


def score_listing(listing: Listing) -> None:
    """Fill in deal_score / deal_label / deal_reasons for one listing."""
    if listing.price_eur is None:
        return

    parts: list[tuple[float, float, str]] = []  # (score, weight, explanation)

    if listing.pct_of_median is not None:
        best, worst, weight = SCORE_MEDIAN_RANGE
        ratio = listing.pct_of_median / 100
        parts.append(
            (ratio_score(ratio, best, worst), weight, f"{listing.pct_of_median:.0f}% van mediaan")
        )

    if (
        listing.ref_market_avg
        and listing.ref_market_count >= SCORE_MARKET_MIN_OBSERVATIONS
    ):
        best, worst, weight = SCORE_MARKET_RANGE
        ratio = listing.price_eur / listing.ref_market_avg
        parts.append(
            (
                ratio_score(ratio, best, worst),
                weight,
                f"{ratio * 100:.0f}% van 2e-hands gem. (n={listing.ref_market_count})",
            )
        )

    if listing.ref_pct_of_original is not None:
        best, worst, weight = SCORE_ORIGINAL_RANGE
        ratio = listing.ref_pct_of_original / 100
        parts.append(
            (
                ratio_score(ratio, best, worst),
                weight,
                f"{listing.ref_pct_of_original:.0f}% van nieuwprijs",
            )
        )

    if not parts:
        return

    total_weight = sum(w for _, w, _ in parts)
    score = sum(s * w for s, w, _ in parts) / total_weight
    reasons = [text for _, _, text in parts]

    # Bonuses, on top of the price signals rather than averaged into them: a
    # listing without a price drop shouldn't be scored as if it had a bad one.
    if listing.price_dropped and listing.price_drop_from:
        drop_pct = (listing.price_drop_from - listing.price_eur) / listing.price_drop_from * 100
        bonus = min(SCORE_DROP_BONUS_MAX, drop_pct / 2)
        score += bonus
        reasons.append(f"prijsdaling {drop_pct:.0f}% (+{bonus:.0f})")

    if listing.ref_better:
        score += SCORE_BETTER_BONUS
        reasons.append(f"beter dan referentie (+{SCORE_BETTER_BONUS:.0f})")

    # A bid listing's price is where the bidding stands now, not what it will
    # sell for, so its score is an upper bound — say so rather than quietly
    # ranking it above fixed-price listings it may well end up more expensive
    # than.
    if listing.price_is_bid:
        reasons.append("bod — eindprijs kan hoger uitvallen")

    # Rounded to a whole number, and the label/threshold work off that same
    # number — otherwise a 79.6 would show as "80" while being sorted and
    # counted as something below the Topdeal cutoff. Whole numbers are also
    # about as much precision as a heuristic like this honestly has.
    listing.deal_score = float(round(max(0.0, min(100.0, score))))
    listing.deal_reasons = " · ".join(reasons)
    for threshold, label, _ in SCORE_LABELS:
        if listing.deal_score >= threshold:
            listing.deal_label = label
            break


def score_listings(listings: list[Listing]) -> None:
    """Combine every price signal collected so far into one score per listing.
    Run this last — it reads pct_of_median, the reference match, the observed
    secondhand average and the price-drop flag, so all of those have to be
    filled in already."""
    for listing in listings:
        score_listing(listing)


def sort_by_score(listings: list[Listing]) -> list[Listing]:
    """Best deal first; unscored listings (no price) last."""
    return sorted(
        listings,
        key=lambda l: (
            l.deal_score is None,
            -(l.deal_score if l.deal_score is not None else 0),
            l.price_eur if l.price_eur is not None else float("inf"),
        ),
    )


def print_table(listings: list[Listing], stats: Optional[dict] = None) -> None:
    if not listings:
        print("No listings found.")
        return

    rows = sort_by_score(listings)
    print(
        f"{'':6} {'SCORE':>6} {'PRICE':>8} {'%MED':>6}  {'FRAME':<12} {'GROUPSET':<22} "
        f"{'CONDITION':<20} {'CITY':<15} {'TITLE'}"
    )
    for l in rows:
        mark = (
            ("N" if l.is_new else " ")
            + ("*" if l.is_bargain else " ")
            + ("B" if l.price_is_bid else " ")
            + ("!" if l.ref_better else " ")
            + ("v" if l.price_dropped else " ")
        )
        if l.price_eur is None:
            price_str = l.price_type
        elif l.price_eur < 1:
            price_str = f"€{l.price_eur:.2f}"
        else:
            price_str = f"€{l.price_eur:.0f}"
        pct_str = f"{l.pct_of_median:.0f}%" if l.pct_of_median is not None else "—"
        score_str = f"{l.deal_score:.0f}" if l.deal_score is not None else "—"
        print(
            f"{mark:6} {score_str:>6} {price_str:>8} {pct_str:>6}  {l.frame_height[:12]:<12} "
            f"{l.groupset[:22]:<22} {l.condition[:20]:<20} {l.city[:15]:<15} {l.title[:60]}"
        )
        print(f"      {l.url}")
        if l.deal_score is not None:
            print(f"      score {l.deal_score:.0f}/100 ({l.deal_label}): {l.deal_reasons}")
        if l.price_is_bid:
            bid_info = format_bid_info(l)
            if bid_info:
                print(f"      bieden: {bid_info}")
        if l.price_dropped:
            print(f"      prijsverlaging: €{l.price_drop_from:.0f} → €{l.price_eur:.0f}")
        if l.ref_label:
            bits = [l.ref_label]
            if l.ref_original_price is not None:
                bits.append(f"nieuw €{l.ref_original_price:.0f}")
            if l.ref_pct_of_original is not None:
                bits.append(f"nu {l.ref_pct_of_original:.0f}% daarvan")
            if l.ref_market_count > 0:
                bits.append(f"tweedehands gem. €{l.ref_market_avg:.0f} (n={l.ref_market_count})")
            if l.ref_specs:
                bits.append(f"specs: {l.ref_specs}")
            if l.ref_score:
                bits.append(f"score: {l.ref_score}")
            marker = " [BETER DAN REFERENTIE]" if l.ref_better else ""
            print(f"      referentie{marker}: {' · '.join(bits)}")

    bargains = [l for l in listings if l.is_bargain]
    new_ones = [l for l in listings if l.is_new]
    bids = [l for l in listings if l.price_is_bid]
    better = [l for l in listings if l.ref_better]
    dropped = [l for l in listings if l.price_dropped]
    open_bids = open_bid_listings(listings)
    top_deals = [l for l in listings if l.deal_score is not None and l.deal_score >= TOP_DEAL_SCORE]
    print(
        f"\n{len(listings)} listings, {len(bargains)} bargains (*), "
        f"{len(new_ones)} new since last run (N), {len(bids)} bidding (B, price = huidig/minimum bod, "
        f"waarvan {len(open_bids)} zonder bod), "
        f"{len(better)} beter dan referentie (!), {len(dropped)} prijsverlaging (v), "
        f"{len(top_deals)} topdeals (score >= {TOP_DEAL_SCORE:.0f})"
    )

    if stats is None:
        stats = price_stats(listings)
    if stats["count"] >= 2:
        shown_count = len(market_prices(listings))
        suffix = f" ({shown_count} van {stats['count']} getoond)" if shown_count != stats["count"] else ""
        print(
            f"gemiddelde prijs: €{stats['mean']:.0f} · mediaan: €{stats['median']:.0f} "
            f"(over {stats['count']} geprijsde advertenties){suffix}"
        )


def bid_overview_order(
    bids: list[Listing], headroom: Optional[dict[str, Optional[float]]] = None
) -> list[Listing]:
    """The order the bid overview is printed in.

    Without headroom figures this is the original order: listings nobody has
    bid on yet first (there the minimum bid is still the real price), each
    group by deal score. With them, the panel sorts on headroom instead —
    estimated value minus what it costs to get in — because that, not the
    price column, is what says which bid listing is underbid (see
    PLAN_FIETSWAARDE.md §7). Listings whose headroom is unknown keep the old
    ordering and sink below the ones that have a number: unknown is not the
    same as no room."""
    known: list[Listing] = []
    unknown = bids
    if headroom:
        known = [l for l in bids if headroom.get(l.item_id) is not None]
        known.sort(key=lambda l: headroom[l.item_id], reverse=True)
        unknown = [l for l in bids if headroom.get(l.item_id) is None]
    return (
        known
        + sort_by_score([l for l in unknown if l.bid_open])
        + sort_by_score([l for l in unknown if not l.bid_open])
    )


def print_bid_overview(
    listings: list[Listing],
    limit: int = 25,
    headroom: Optional[dict[str, Optional[float]]] = None,
) -> None:
    """A separate look at the bidding listings — what it would cost to be the
    first bidder, how much room there is between that and what the thing is
    worth, and how it compares to the median and to what the model is known to
    go for."""
    bids = bid_listings(listings)
    if not bids:
        return

    open_bids = open_bid_listings(listings)
    print(f"\nBIED-OVERZICHT — {len(bids)} bied-advertenties, waarvan {len(open_bids)} nog zonder bod")
    room_header = f"{'RUIMTE':>8} " if headroom else ""
    print(
        f"  {'SCORE':>5} {'PRIJS':>8} {'%MED':>6} {room_header} {'BOD':<42} "
        f"{'REFERENTIE':<28} TITEL"
    )

    ordered = bid_overview_order(bids, headroom)
    for l in ordered[:limit]:
        score_str = f"{l.deal_score:.0f}" if l.deal_score is not None else "—"
        price_str = f"€{l.price_eur:.0f}" if l.price_eur is not None else l.price_type
        pct_str = f"{l.pct_of_median:.0f}%" if l.pct_of_median is not None else "—"
        room_str = ""
        if headroom:
            room = headroom.get(l.item_id)
            # A missing headroom prints as a dash, never as EUR 0 — that
            # distinction is the whole point of the column.
            room_str = f"{('€%.0f' % room) if room is not None else '—':>8} "
        status = format_bid_info(l) or "bod"
        if l.ref_label:
            ref = l.ref_label
            if l.ref_market_count > 0:
                ref += f" (2e-hands gem. €{l.ref_market_avg:.0f})"
            elif l.ref_original_price is not None:
                ref += f" (nieuw €{l.ref_original_price:.0f})"
        else:
            ref = "—"
        print(
            f"  {score_str:>5} {price_str:>8} {pct_str:>6} {room_str} {status[:42]:<42} "
            f"{ref[:28]:<28} {l.title[:40]}"
        )
        print(f"        {l.url}")

    if len(ordered) > limit:
        print(f"  ... en nog {len(ordered) - limit} (zie het HTML-rapport, tab 'Bieden')")


def bid_headroom_by_id(
    listings: list[Listing], median: Optional[float]
) -> dict[str, Optional[float]]:
    """Headroom per bidding listing, for the overview above.

    The import is local on purpose: upgrade.py reads this module, so this
    module can only reach back into it from inside a function (the same way
    scoring.main() imports valuation). Keeping the result a plain dict of
    euros means nothing else here has to know about upgrade.py's types."""
    import upgrade

    return {row.listing.item_id: row.headroom_eur for row in upgrade.bid_panel(listings, median)}


# The report's HTML lives in its own file (PLAN_FIETSWAARDE.md §8). It used to
# be a str.format() string in here, where every brace in the CSS and the
# JavaScript had to be doubled — writing an object literal in that was an
# accident waiting to happen. string.Template's $-placeholders leave braces
# alone; the one character to watch in the template is now `$` itself (write
# `$$` for a literal one).
REPORT_TEMPLATE_PATH = Path(__file__).resolve().parent / "report_template.html"


def load_report_template(path: Path = REPORT_TEMPLATE_PATH) -> string.Template:
    """Read the template at render time rather than at import, so a missing
    file only matters to a run that actually writes a report (--no-html runs
    and the tools that import this module don't need it)."""
    try:
        return string.Template(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(
            f"error: HTML-sjabloon {path} ontbreekt — dat bestand hoort naast "
            f"{Path(__file__).name}; zet het terug of draai met --no-html"
        ) from None


def score_css_class(score: Optional[float]) -> str:
    """The pill colour for a score — same tiers as its label."""
    if score is not None:
        for threshold, _, css_class in SCORE_LABELS:
            if score >= threshold:
                return css_class
    return "low"


def render_html(
    listings: list[Listing], query: str, stats: Optional[dict] = None, panels=None
) -> str:
    """`panels` is a report.Panels (the Biedpaneel / Upgrade / Mijn fiets
    tabs). Left out, only the bid panel is filled — it needs nothing but the
    listings — and the other two say there is no bike to compare against.
    The import is local for the same reason as in bid_headroom_by_id():
    report.py reads this module."""
    rows_sorted = sort_by_score(listings)

    row_html = []
    for l in rows_sorted:
        price_str = (
            html_lib.escape(l.price_type) if l.price_eur is None
            else f"€{l.price_eur:.2f}" if l.price_eur < 1
            else f"€{l.price_eur:.0f}"
        )
        if l.price_is_bid and l.price_eur is not None:
            price_str += ' <span class="bid-tag">bod</span>'
        badges = ""
        if l.is_new:
            badges += '<span class="badge new">NIEUW</span>'
        if l.is_bargain:
            badges += '<span class="badge bargain">KOOPJE</span>'
        if l.ref_better:
            badges += '<span class="badge better">BETER</span>'
        if l.price_dropped:
            badges += f'<span class="badge dropped">-€{l.price_drop_from - l.price_eur:.0f}</span>'
        if l.bid_open:
            badges += '<span class="badge bid">VRIJ TE BIEDEN</span>'
        price_sort_value = l.price_eur if l.price_eur is not None else -1

        if l.deal_score is not None:
            score_cell = (
                f"<span class='score-pill {score_css_class(l.deal_score)}'>{l.deal_score:.0f}</span>"
                f"<div class='score-label'>{html_lib.escape(l.deal_label)}</div>"
            )
        else:
            score_cell = "<span class='score-pill low'>—</span>"
        score_sort = l.deal_score if l.deal_score is not None else -1
        score_title = html_lib.escape(l.deal_reasons, quote=True)

        bid_str = html_lib.escape(format_bid_info(l)) or "—"
        # Sort the Bod column by what it would cost to bid right now.
        if l.bid_minimum is not None:
            bid_sort = l.bid_minimum
        elif l.price_is_bid and l.price_eur is not None:
            bid_sort = l.price_eur
        else:
            bid_sort = -1

        ref_str = html_lib.escape(l.ref_label) if l.ref_label else "—"
        ref_sort = l.ref_pct_of_original if l.ref_pct_of_original is not None else 1e9

        if l.ref_pct_of_original is not None:
            ref_price_str = f"€{l.ref_original_price:.0f} ({l.ref_pct_of_original:.0f}% nu)"
        elif l.ref_original_price is not None:
            ref_price_str = f"€{l.ref_original_price:.0f}"
        else:
            ref_price_str = "—" if not l.ref_label else "onbekend"
        if l.ref_market_count > 0:
            ref_price_str += f" · 2e-hands gem. €{l.ref_market_avg:.0f} (n={l.ref_market_count})"
        ref_specs_str = html_lib.escape(l.ref_score) if l.ref_score else (
            html_lib.escape(l.ref_specs) if l.ref_specs else "—"
        )
        if l.ref_specs and l.ref_score:
            ref_specs_str = html_lib.escape(f"{l.ref_specs} — {l.ref_score}")

        pct_median_str = f"{l.pct_of_median:.0f}%" if l.pct_of_median is not None else "—"
        pct_median_sort = l.pct_of_median if l.pct_of_median is not None else 1e9

        row_html.append(
            "<tr data-new='{is_new}' data-bargain='{is_bargain}' data-better='{is_better}' "
            "data-dropped='{is_dropped}' data-topdeal='{is_topdeal}' "
            "data-bidding='{is_bidding}' data-openbid='{is_openbid}' "
            "data-price='{price_sort}' data-title='{title_attr}' "
            "data-frame='{frame_attr}' data-groupset='{groupset_sort}' "
            "data-condition='{condition_attr}' data-city='{city_attr}' data-ref='{ref_sort}' "
            "data-pctmedian='{pct_median_sort}' data-score='{score_sort}' data-bid='{bid_sort}'>"
            "<td>{badges}</td>"
            "<td class='score' title='{score_title}'>{score_cell}</td>"
            "<td class='price'>{price}</td>"
            "<td>{bid}</td>"
            "<td>{pct_median}</td>"
            "<td><a href='{url}' target='_blank' rel='noopener'>{title}</a></td>"
            "<td>{frame}</td>"
            "<td>{groupset}</td>"
            "<td>{condition}</td>"
            "<td>{city}</td>"
            "<td>{ref}</td>"
            "<td>{ref_price}</td>"
            "<td>{ref_specs}</td>"
            "</tr>".format(
                is_new="1" if l.is_new else "0",
                is_bargain="1" if l.is_bargain else "0",
                is_better="1" if l.ref_better else "0",
                is_dropped="1" if l.price_dropped else "0",
                is_topdeal="1" if (l.deal_score is not None and l.deal_score >= TOP_DEAL_SCORE) else "0",
                is_bidding="1" if l.price_is_bid else "0",
                is_openbid="1" if l.bid_open else "0",
                price_sort=price_sort_value,
                score_sort=score_sort,
                score_title=score_title,
                score_cell=score_cell,
                bid=bid_str,
                bid_sort=bid_sort,
                title_attr=html_lib.escape(l.title, quote=True),
                frame_attr=html_lib.escape(l.frame_height, quote=True),
                groupset_sort=l.groupset_tier if l.groupset_tier is not None else -1,
                condition_attr=html_lib.escape(l.condition, quote=True),
                city_attr=html_lib.escape(l.city, quote=True),
                ref_sort=ref_sort,
                pct_median_sort=pct_median_sort,
                badges=badges,
                frame=html_lib.escape(l.frame_height) or "—",
                groupset=html_lib.escape(l.groupset) or "—",
                price=price_str,
                pct_median=pct_median_str,
                url=html_lib.escape(l.url, quote=True),
                title=html_lib.escape(l.title),
                condition=html_lib.escape(l.condition),
                city=html_lib.escape(l.city),
                ref=ref_str,
                ref_price=ref_price_str,
                ref_specs=ref_specs_str,
            )
        )

    if stats is None:
        stats = price_stats(listings)
    price_stats_str = (
        f" · gemiddeld €{stats['mean']:.0f} · mediaan €{stats['median']:.0f}"
        if stats["count"] >= 2
        else ""
    )
    if panels is None:
        import report

        panels = report.build_panels(
            listings, stats.get("median"),
            owner_problem="Geen eigen fiets meegegeven aan dit rapport.",
        )

    # substitute(), not safe_substitute(): a placeholder in the template that
    # nobody fills in should fail here, not end up as literal text in the page.
    return load_report_template().substitute(
        query=html_lib.escape(query),
        generated=datetime.now().strftime("%d-%m-%Y %H:%M"),
        total=len(listings),
        new_count=sum(1 for l in listings if l.is_new),
        bargain_count=sum(1 for l in listings if l.is_bargain),
        better_count=sum(1 for l in listings if l.ref_better),
        dropped_count=sum(1 for l in listings if l.price_dropped),
        topdeal_count=sum(
            1 for l in listings if l.deal_score is not None and l.deal_score >= TOP_DEAL_SCORE
        ),
        bid_count=len(bid_listings(listings)),
        open_bid_count=len(open_bid_listings(listings)),
        price_stats_str=price_stats_str,
        rows="\n".join(row_html),
        bidpanel_count=panels.bid_row_count,
        upgrade_count=panels.upgrade_count,
        bid_panel=panels.bids_html,
        upgrade_panel=panels.upgrade_html,
        bike_panel=panels.bike_html,
    )


def write_html(
    listings: list[Listing], path: str, query: str, stats: Optional[dict] = None, panels=None
) -> None:
    Path(path).write_text(
        render_html(listings, query, stats=stats, panels=panels), encoding="utf-8"
    )


def build_report_panels(args: argparse.Namespace, listings: list[Listing], median: Optional[float]):
    """The report's extra tabs for this run. The own-bike valuation reads
    koopjes.db — which sync_database() has just written, so it already holds
    this crawl — but never writes to it. With --no-db there is nothing to
    value against, and the tabs say that rather than guess a budget."""
    import report

    owner, problem = report.load_owner_context(
        args.mijn_fiets, None if args.no_db else args.db
    )
    reason = problem or (owner.valuation_problem if owner else None)
    if reason:
        print(f"Rapport, tabs 'Mijn fiets'/'Upgrade': {reason}", file=sys.stderr)
    return report.build_panels(listings, median, owner=owner, owner_problem=problem)


def write_csv(listings: list[Listing], path: str) -> None:
    if not listings:
        # The file is still written (leaving a stale one from a previous run
        # would be worse), but with its column headers rather than as a blank
        # line — that way it opens as an empty table instead of looking like a
        # corrupt file.
        print(
            f"warning: niets te exporteren; {path} bevat alleen de kolomkoppen.",
            file=sys.stderr,
        )
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LISTING_FIELDS)
        writer.writeheader()
        for listing in listings:
            writer.writerow(asdict(listing))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query",
        # None rather than DEFAULT_QUERY, so main() can tell "--watchlist
        # powermeter" (run only that) from "--query racefiets --watchlist
        # powermeter" (run both). See resolve_queries().
        default=None,
        help=f"Search query (default: {DEFAULT_QUERY}). Comma-separate multiple terms (e.g. "
        "\"racefiets,luidsprekers\") to run them all in one go — each gets its own HTML/CSV "
        "report (named after the query), while history/log/reference files stay shared. "
        "With --watchlist and no --query, only the watchlists run.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of result pages to fetch (30 listings/page). Use 0 to fetch "
        "everything Marktplaats allows browsing to (a few hundred pages) — useful "
        "for a first run to seed the full history.",
    )
    parser.add_argument("--min-price", type=float, default=None, help="Ignore listings cheaper than this (EUR)")
    parser.add_argument("--max-price", type=float, default=None, help="Ignore listings pricier than this (EUR)")
    parser.add_argument(
        "--min-frame-height", type=float, default=None, help="Ignore listings with a smaller frame size (cm)"
    )
    parser.add_argument(
        "--max-frame-height", type=float, default=None, help="Ignore listings with a bigger frame size (cm)"
    )
    parser.add_argument(
        "--strict-frame-height",
        action="store_true",
        help="With --min/--max-frame-height, also drop listings that don't state a frame size. "
        "By default they're kept: most bikes on Marktplaats have no size filled in",
    )
    parser.add_argument(
        "--sort",
        choices=sorted(SORT_OPTIONS),
        default="optimized",
        help="Result order to crawl in: 'optimized' (default, Marktplaats' own 'Standaard' "
        "order via the search page) or 'newest' (newest first, via Marktplaats' search API) — "
        "use newest for scheduled runs, so a few pages cover everything new since the last run",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Only search in these Marktplaats categories (comma-separated key or number, e.g. "
        "'fietsonderdelen' or 'fietsaccessoires-fietscomputers'), filtered by Marktplaats "
        "itself. Replaces the automatic main-category guess, which keeps only one category. "
        "An unknown category lists the ones that do have results",
    )
    parser.add_argument(
        "--bargain-ratio",
        type=float,
        default=0.6,
        help="Flag listings priced at or below this fraction of the median price (default: 0.6)",
    )
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds to wait between page requests (default: 1.5)")
    parser.add_argument("--output", default=None, help="Optional path to write results as CSV")
    parser.add_argument(
        "--html",
        default="racefiets_report.html",
        help="Path to write an HTML overview to (default: racefiets_report.html)",
    )
    parser.add_argument("--no-html", action="store_true", help="Skip writing the HTML overview")
    parser.add_argument(
        "--history-file",
        default="seen_listings.json",
        help="Path to the file that remembers which listings were already seen (default: seen_listings.json)",
    )
    parser.add_argument(
        "--reference-file",
        default="reference_prices.csv",
        help="Optional CSV of known models (pattern,label,original_price_eur,score) to match "
        "against listing titles and compare the asking price to. Skipped if the file doesn't "
        "exist (default: reference_prices.csv)",
    )
    parser.add_argument(
        "--bid-lookup",
        choices=["fast", "all", "none"],
        default="fast",
        help="Which bidding listings to fetch bid details for (one extra request each): "
        "'fast' (default) only FAST_BID listings, which report no price in search results at "
        "all; 'all' also fetches MIN_BID listings, which do report an asking price but not the "
        "(usually lower) minimum bid that's actually accepted, nor whether anyone has bid yet; "
        "'none' skips it entirely (FAST_BID listings then stay priceless)",
    )
    parser.add_argument(
        "--no-bid-lookup",
        action="store_true",
        help="Alias for --bid-lookup none",
    )
    parser.add_argument(
        "--bids-only",
        action="store_true",
        help="Only report bidding listings (Bieden). Prices, the median and the deal score are "
        "still computed over everything found, so the comparison stays against the whole market "
        "rather than only against other bidding listings",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Only report listings with at least this deal score (0-100). Listings with no "
        "price, and so no score, are dropped by this filter too",
    )
    parser.add_argument(
        "--open-browser",
        choices=["auto", "always", "never"],
        default="auto",
        help="Open the HTML report in your browser after writing it: 'auto' only does so when "
        "there are new listings since the last run (the default — handy for a cron/scheduled "
        "run so it doesn't pop up a browser tab every time), 'always' every run, 'never' skips it",
    )
    parser.add_argument(
        "--log-file",
        default="bargains_log.csv",
        help="CSV that newly found bargains get appended to on every run, building a running "
        "history instead of just the current snapshot (default: bargains_log.csv)",
    )
    parser.add_argument("--no-log", action="store_true", help="Skip appending to the bargains log")
    parser.add_argument(
        "--price-history-file",
        default="reference_price_history.csv",
        help="CSV that logs the price of every newly-seen listing matching a reference model, "
        "building your own observed secondhand market price per model over time (shown as "
        "'2e-hands gem.') independent of reference_prices.csv's original retail price "
        "(default: reference_price_history.csv)",
    )
    parser.add_argument(
        "--no-price-history", action="store_true", help="Skip recording/using observed secondhand prices"
    )
    parser.add_argument(
        "--no-notify-better",
        action="store_true",
        help="Skip the sound/highlighted-line notification when a new listing beats the reference baseline",
    )
    parser.add_argument(
        "--db",
        default="koopjes.db",
        help="Path to the SQLite database that mirrors the CSV/JSON files (PLAN_FIETSWAARDE.md "
        "fase 1b) — every run upserts its listings, logs a crawl_run, and re-imports the legacy "
        "files (default: koopjes.db)",
    )
    parser.add_argument(
        "--no-db", action="store_true", help="Skip writing to the SQLite database"
    )
    parser.add_argument(
        "--mijn-fiets",
        default="mijn_fiets.md",
        help="Intake of your own bike, for the report's 'Mijn fiets' and 'Upgrade' tabs "
        "(PLAN_FIETSWAARDE.md fase 6). Missing file = those tabs say so (default: mijn_fiets.md)",
    )
    parser.add_argument(
        "--watchlist",
        default=None,
        help="Run saved searches from the database by name (comma-separated, or 'all' for every "
        "active one), each with its own filters and its own report "
        "(<html>_<name>.html) — PLAN_FIETSWAARDE.md fase 8. Filters given on the command line "
        "don't apply to them, and theirs don't apply to --query",
    )
    parser.add_argument(
        "--watchlist-add",
        metavar="NAME",
        default=None,
        help="Save --query plus the filter flags given on this command line (--min-price, "
        "--max-price, --reference-file, --category, ...) as watchlist NAME, replacing an existing one. "
        "Doesn't crawl",
    )
    parser.add_argument(
        "--watchlist-remove", metavar="NAME", default=None, help="Delete watchlist NAME. Doesn't crawl"
    )
    parser.add_argument(
        "--watchlist-list", action="store_true", help="List the saved watchlists. Doesn't crawl"
    )
    return parser.parse_args(argv)


# The flags a watchlist carries itself (fase 8): everything that decides
# *which* listings end up in its report and what they're compared against.
# The rest — --pages, --sort, --bid-lookup, --delay, --db, the history/log
# files, --open-browser — is how this run is done, not what it's looking
# for, and stays the command line's. That's also everything that decides how
# many requests a run makes: a watchlist that carried its own page count or
# bid lookup could quietly turn a shallow scheduled run into a full crawl,
# or ignore a --bid-lookup none given for exactly that reason.
WATCHLIST_FILTERS = {
    "min_price": "number",
    "max_price": "number",
    "min_frame_height": "number",
    "max_frame_height": "number",
    "strict_frame_height": "flag",
    "bargain_ratio": "number",
    "reference_file": "text",
    "category": "text",
    "bids_only": "flag",
    "min_score": "number",
}
WATCHLIST_ALL = "all"


def watchlist_filters_from_args(args: argparse.Namespace) -> dict:
    """The filters to store for --watchlist-add: only those that differ from
    the default, so a watchlist saved before a default changes follows the new
    default instead of freezing the old one."""
    defaults = parse_args([])
    current = {k: getattr(args, k) for k in WATCHLIST_FILTERS}
    return {k: v for k, v in current.items() if v != getattr(defaults, k)}


def args_for_watchlist(args: argparse.Namespace, entry: dict) -> argparse.Namespace:
    """A copy of `args` for one watchlist run: every filter back at its
    default, then the watchlist's own on top. Starting from the defaults
    rather than from the command line is the point — `--max-frame-height 58
    --watchlist powermeter` would otherwise drop every powermeter, since
    filter_by_frame_height() drops listings without a frame size."""
    defaults = parse_args([])
    run_args = argparse.Namespace(**vars(args))
    for key in WATCHLIST_FILTERS:
        setattr(run_args, key, getattr(defaults, key))

    filters = dict(entry["filters"])
    if "bid_lookup" in filters:
        # Stored by the first version of --watchlist-add, before bid lookup
        # moved to the command line's side (see WATCHLIST_FILTERS).
        filters.pop("bid_lookup")
        print(
            f"warning: watchlist {entry['name']!r} heeft een opgeslagen bid_lookup; die wordt "
            "genegeerd, --bid-lookup komt van de commandoregel. Sla hem opnieuw op om dit te "
            "laten verdwijnen.",
            file=sys.stderr,
        )
    unknown = sorted(set(filters) - set(WATCHLIST_FILTERS))
    if unknown:
        # Only reachable by editing the database by hand (--watchlist-add
        # stores nothing else). Skipping the key would run a wider search than
        # the one that was saved.
        raise ValueError(
            f"watchlist {entry['name']!r} heeft onbekende filter(s): {', '.join(unknown)}"
        )
    for key, value in filters.items():
        kind = WATCHLIST_FILTERS[key]
        # Same reasoning as the unknown-key check: a value that was edited
        # into the wrong type would otherwise fail halfway through the run
        # ("400" < 350), or worse, be compared as a string without failing.
        if kind == "number":
            ok = value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))
        elif kind == "flag":
            ok = isinstance(value, bool)
        elif kind == "text":
            ok = value is None or isinstance(value, str)
        else:
            ok = value in kind
        if not ok:
            raise ValueError(
                f"watchlist {entry['name']!r}: filter {key} heeft een ongeldige waarde {value!r}"
            )
        setattr(run_args, key, value)
    return run_args


def warn_missing_reference_file(name: str, path: Optional[str]) -> None:
    """load_reference_data() treats a missing file as "no reference data",
    which is right for the default path but not for one a watchlist names on
    purpose: its report would silently lose every model match and new-price
    comparison. A relative path is looked up from the directory the script
    is started in, which a scheduled task doesn't always share."""
    if path and not Path(path).exists():
        print(
            f"warning: watchlist {name!r}: referentiebestand {path} niet gevonden "
            f"(gezocht vanuit {Path.cwd()}); deze run vergelijkt zonder referentiemodellen.",
            file=sys.stderr,
        )


def resolve_queries(args: argparse.Namespace) -> list[str]:
    """The plain --query terms to run. Without --query that's the default
    query, unless --watchlist was given: then the watchlists are the run."""
    if args.query is None:
        if args.watchlist:
            return []
        return [DEFAULT_QUERY]
    return [q.strip() for q in args.query.split(",") if q.strip()]


def load_watchlists(args: argparse.Namespace) -> list[dict]:
    """Look up every name in --watchlist before anything is crawled, so a
    typo fails at once instead of after the regular queries have run."""
    names = [n.strip() for n in args.watchlist.split(",") if n.strip()]
    if not names:
        raise ValueError("--watchlist zonder naam")
    if not Path(args.db).exists():
        # Not db.connect(): that would create an empty database just to say
        # there's nothing in it.
        raise ValueError(
            f"geen watchlists: {args.db} bestaat nog niet. Sla er eerst een op met "
            "--watchlist-add."
        )
    conn = db.connect(args.db)
    try:
        if names == [WATCHLIST_ALL]:
            entries = db.list_watchlists(conn, active_only=True)
            if not entries:
                raise ValueError(f"geen actieve watchlists in {args.db}")
            return entries
        entries = []
        for name in names:
            entry = db.get_watchlist(conn, name)
            if entry is None:
                known = ", ".join(e["name"] for e in db.list_watchlists(conn)) or "geen"
                raise ValueError(f"onbekende watchlist {name!r} (bekend: {known})")
            entries.append(entry)
        return entries
    finally:
        conn.close()


def manage_watchlists(args: argparse.Namespace) -> int:
    """--watchlist-add / --watchlist-remove / --watchlist-list. None of them
    crawls: saving a search and running it are separate steps, so a typo in
    the filters can be seen in --watchlist-list before it costs requests."""
    if args.watchlist:
        print(
            "error: --watchlist draait zoekopdrachten, --watchlist-add/-remove/-list beheert "
            "ze; doe dat in twee aparte commando's.",
            file=sys.stderr,
        )
        return 1
    if args.no_db and (args.watchlist_add or args.watchlist_remove):
        print("error: watchlists staan in de database; laat --no-db weg.", file=sys.stderr)
        return 1

    if args.watchlist_add:
        name = args.watchlist_add.strip()
        if not name or name == WATCHLIST_ALL or "," in name:
            print(
                f"error: {name!r} kan geen watchlistnaam zijn ('{WATCHLIST_ALL}' en komma's "
                "zijn gereserveerd voor --watchlist).",
                file=sys.stderr,
            )
            return 1
        if not args.query or not args.query.strip():
            print("error: --watchlist-add heeft een --query nodig.", file=sys.stderr)
            return 1
        filters = watchlist_filters_from_args(args)
        warn_missing_reference_file(name, filters.get("reference_file"))
        conn = db.connect(args.db)
        try:
            db.save_watchlist(conn, name, args.query.strip(), filters)
        finally:
            conn.close()
        print(f"Watchlist {name!r} opgeslagen: {format_watchlist(name, args.query.strip(), filters)}")
        return 0

    if not Path(args.db).exists():
        if args.watchlist_remove:
            print(f"error: onbekende watchlist {args.watchlist_remove!r}", file=sys.stderr)
            return 1
        print(f"Geen watchlists ({args.db} bestaat nog niet).")
        return 0

    conn = db.connect(args.db)
    try:
        if args.watchlist_remove:
            if not db.delete_watchlist(conn, args.watchlist_remove):
                print(f"error: onbekende watchlist {args.watchlist_remove!r}", file=sys.stderr)
                return 1
            print(f"Watchlist {args.watchlist_remove!r} verwijderd.")
            return 0

        entries = db.list_watchlists(conn)
    finally:
        conn.close()
    if not entries:
        print("Geen watchlists.")
    for e in entries:
        status = "" if e["active"] else "  (inactief)"
        print(format_watchlist(e["name"], e["query"], e["filters"]) + status)
    return 0


def format_watchlist(name: str, query: str, filters: dict) -> str:
    parts = [f"--{k.replace('_', '-')} {v}" if v is not True else f"--{k.replace('_', '-')}"
             for k, v in sorted(filters.items())]
    return f"{name}: --query {query!r}" + (" " + " ".join(parts) if parts else "")


def safe_query_slug(query: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "query"


def per_query_path(base: str, query: str, multi: bool) -> str:
    """When running multiple queries in one go, give each its own output
    file (derived from the base path) instead of them overwriting each
    other; a single query keeps using the base path unchanged."""
    if not multi:
        return base
    p = Path(base)
    return str(p.with_name(f"{p.stem}_{safe_query_slug(query)}{p.suffix}"))


def report_path(base: str, query: str, multi: bool, report_name: Optional[str]) -> str:
    if report_name is not None:
        return per_query_path(base, report_name, True)
    return per_query_path(base, query, multi)


def sync_database(
    args: argparse.Namespace,
    query: str,
    listings: list[Listing],
    *,
    crawled_item_ids: set[str],
    started_at: str,
    finished_at: str,
    reference_matches: Optional[dict[str, list[str]]] = None,
    crawl_complete: bool = False,
    crawl_note: str = "",
) -> None:
    """Mirror this run into koopjes.db, alongside the CSV/JSON files that
    stay the ones actually read elsewhere (reference_overview.py etc.) —
    PLAN_FIETSWAARDE.md fase 1b. All three legacy paths are passed
    explicitly: db.import_legacy()'s own defaults point at the working
    directory, and leaving one out here would silently import whatever
    happens to sit there instead of the file this run actually used.

    Fase 2 adds two more mirrors, both additive bookkeeping rather than
    anything the report reads: extract_specs() per listing into `spec`, and
    reference_matches (apply_reference_data()'s full match list, not just
    the one that wins the report's ref_* columns) into `listing_model`. The
    listing_model write needs the `model` rows import_legacy() just inserted
    to already exist, so it has to run after that call."""
    conn = db.connect(args.db)
    try:
        db.import_legacy(
            conn,
            seen_listings_path=args.history_file,
            reference_prices_path=args.reference_file,
            reference_price_history_path=args.price_history_file,
        )
        db.sync_listings(conn, query, listings, finished_at)
        db.sync_listing_specs(conn, extract_listing_specs(listings))
        if reference_matches:
            db.sync_listing_models(conn, reference_matches)
        db.record_crawl_run(
            conn,
            query=query,
            pages_requested=args.pages,
            pages_fetched=None,
            listing_count=len(listings),
            started_at=started_at,
            finished_at=finished_at,
        )
        # Only a full crawl (--pages 0, or any non-positive value per
        # collect_listings' own convention) has actually looked at every
        # listing for this query — a shallow --pages 3 run would otherwise
        # mark everything past page 3 as disappeared.
        if args.pages <= 0 and not crawl_complete:
            # --pages 0 is a request, not a guarantee: Marktplaats stops
            # paging at ~5000 results, and a failed page ends the crawl
            # early. Sweeping then marks everything the crawl didn't reach as
            # sold, with a days_online that E2 would take at face value.
            print(
                f"verdwijn-sweep overgeslagen: de crawl van '{query}' was niet compleet "
                f"({crawl_note or 'onbekende reden'}). Een smallere zoekterm, --category of "
                "--sort newest maakt hem compleet.",
                file=sys.stderr,
            )
        elif args.pages <= 0:
            # Against everything the crawl saw, not against what survived the
            # filters: with --max-price 150 the listings above it are still
            # online, they just aren't in this report. Sweeping on the
            # filtered set marks those as disappeared and writes a days_online
            # for them — exactly the number fase 3 wants to trust later.
            swept = db.sweep_disappeared(conn, query, crawled_item_ids, finished_at)
            if swept:
                print(
                    f"{swept} advertentie(s) gemarkeerd als verdwenen na volledige crawl",
                    file=sys.stderr,
                )
    finally:
        conn.close()


def run_for_query(
    args: argparse.Namespace, query: str, multi: bool, report_name: Optional[str] = None
) -> None:
    """report_name is set for a watchlist run: its HTML/CSV then always get
    their own file named after it, so a powermeter watch never overwrites
    the racefiets report that the same scheduled run just wrote."""
    if report_name is not None:
        print(f"\n=== watchlist {report_name}: {query} ===")
    elif multi:
        print(f"\n=== {query} ===")

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    categories = [c.strip() for c in (args.category or "").split(",") if c.strip()]
    listings = collect_listings(
        query, args.pages, args.delay, sort=args.sort, categories=categories or None
    )
    # Kept before any filtering: this is what the crawl actually saw, which is
    # what "has this listing disappeared?" has to be answered against.
    crawled_item_ids = {listing.item_id for listing in listings}
    # A plain list (only a test's stand-in returns one) says nothing about
    # completeness, so it counts as incomplete: the sweep is the one step
    # where guessing wrong corrupts data.
    crawl_complete = getattr(listings, "complete", False)
    crawl_note = getattr(listings, "note", "")

    # Filter on what the search results already tell us before the bid lookup,
    # which costs one request (plus --delay) per bidding listing: a listing
    # that's out of range or the wrong frame size gets dropped either way, so
    # fetching its bids first is time spent on nothing. Under the default
    # --bid-lookup fast this changes little (FAST_BID listings carry no price
    # yet, so they all pass), but under --bid-lookup all it saves a request
    # for every MIN_BID outside the range.
    listings = filter_by_price(listings, args.min_price, args.max_price)
    listings = filter_by_frame_height(
        listings,
        args.min_frame_height,
        args.max_frame_height,
        keep_unknown=not args.strict_frame_height,
    )

    bid_lookup = "none" if args.no_bid_lookup else args.bid_lookup
    enrich_bid_listings(listings, args.delay, bid_lookup)
    apply_bid_flags(listings)

    # FAST_BID listings passed the filter above untested, for lack of a price.
    # Now that the lookup has given them one, the range applies to them too —
    # without this second pass a bid of EUR 2000 would sail through
    # --max-price 150.
    listings = filter_by_price(listings, args.min_price, args.max_price)

    reference = load_reference_data(args.reference_file)
    reference_matches = apply_reference_data(listings, reference)

    if not args.no_price_history:
        market_stats = load_reference_market_stats(args.price_history_file)
        apply_reference_market_stats(listings, market_stats)

    listings = flag_bargains(listings, args.bargain_ratio)

    history = load_history(args.history_file)
    history = apply_history(listings, history)
    save_history(args.history_file, history)

    if not args.no_price_history:
        recorded = append_reference_price_observations(args.price_history_file, listings)
        if recorded:
            print(f"Recorded {recorded} price observation(s) to {args.price_history_file}")

    score_listings(listings)

    if not args.no_notify_better:
        notify_better_matches(listings)

    if not args.no_log:
        logged = append_bargain_log(args.log_file, listings)
        if logged:
            print(f"Logged {logged} new bargain(s) to {args.log_file}")

    if not args.no_db:
        finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        sync_database(
            args,
            query,
            listings,
            crawled_item_ids=crawled_item_ids,
            started_at=started_at,
            finished_at=finished_at,
            reference_matches=reference_matches,
            crawl_complete=crawl_complete,
            crawl_note=crawl_note,
        )

    # Captured before --bids-only/--min-score filter the list for the
    # report: the "% v. mediaan" column (set in flag_bargains, above) is
    # already measured against the unfiltered set, and the footer under the
    # table has to report the same median or it contradicts its own column.
    all_stats = price_stats(listings)

    if args.bids_only:
        listings = bid_listings(listings)
    if args.min_score is not None:
        listings = [
            l for l in listings if l.deal_score is not None and l.deal_score >= args.min_score
        ]

    print_table(listings, stats=all_stats)
    print_bid_overview(listings, headroom=bid_headroom_by_id(listings, all_stats.get("median")))

    if args.output:
        output_path = report_path(args.output, query, multi, report_name)
        write_csv(listings, output_path)
        print(f"\nWrote {len(listings)} listings to {output_path}")

    if not args.no_html:
        html_path = report_path(args.html, query, multi, report_name)
        panels = build_report_panels(args, listings, all_stats.get("median"))
        write_html(listings, html_path, query, stats=all_stats, panels=panels)
        print(f"Wrote HTML overview to {html_path}")

        new_count = sum(1 for l in listings if l.is_new)
        should_open = args.open_browser == "always" or (
            args.open_browser == "auto" and new_count > 0
        )
        if should_open:
            try:
                webbrowser.open(Path(html_path).resolve().as_uri())
            except webbrowser.Error as exc:
                print(f"warning: could not open browser: {exc}", file=sys.stderr)


def notify_better_matches(listings: list[Listing]) -> None:
    """Play a system sound and print a highlighted line for every newly
    seen listing that beats the reference baseline — separate from the
    general 'new listings' browser-open, so this specifically flags the
    thing you're actually hunting for."""
    matches = [l for l in listings if l.is_new and l.ref_better]
    if not matches:
        return

    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except ImportError:
        print("\a", end="", flush=True)

    print(f"\n!! {len(matches)} NIEUWE MATCH(ES) BETER DAN REFERENTIE:")
    for l in matches:
        price = f"€{l.price_eur:.0f}" if l.price_eur is not None else l.price_type
        print(f"   {price:>8}  {l.ref_label} — {l.title}")
        print(f"             {l.url}")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    if args.watchlist_add or args.watchlist_remove or args.watchlist_list:
        return manage_watchlists(args)

    queries = resolve_queries(args)
    watch_runs = []
    if args.watchlist:
        try:
            for entry in load_watchlists(args):
                run_args = args_for_watchlist(args, entry)
                warn_missing_reference_file(entry["name"], entry["filters"].get("reference_file"))
                terms = [q.strip() for q in entry["query"].split(",") if q.strip()]
                for term in terms:
                    name = entry["name"] if len(terms) == 1 else f"{entry['name']} {term}"
                    watch_runs.append((run_args, term, name))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if not queries and not watch_runs:
        print("error: no search query given", file=sys.stderr)
        return 1
    multi = len(queries) > 1

    for query in queries:
        run_for_query(args, query, multi)
    for run_args, query, name in watch_runs:
        run_for_query(run_args, query, True, report_name=name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
