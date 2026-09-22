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
import sys
import time
import webbrowser
from dataclasses import dataclass, asdict, fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

import db

BASE_URL = "https://www.marktplaats.nl"
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
    bid_count: Optional[int] = None
    bid_minimum: Optional[float] = None
    bid_minimum_pct_of_median: Optional[float] = None
    bid_open: bool = False
    deal_score: Optional[float] = None
    deal_label: str = ""
    deal_reasons: str = ""


LISTING_FIELDS = [f.name for f in dataclass_fields(Listing)]


def fetch_page(session: requests.Session, query: str, page: int) -> dict:
    """Fetch one Marktplaats search results page and return its embedded JSON data."""
    # The query goes into the URL *path*, so it has to be encoded as one.
    # requests leaves "?", "#" and "&" alone (they're legal in a URL, just not
    # in a path segment), so a query like "wat?" would turn into an empty
    # query string and a search for "wat". safe="" also catches a slash, which
    # would otherwise add a path segment.
    quoted = quote(query, safe="")
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
    return data["props"]["pageProps"]["searchRequestAndResponse"]


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


def resolve_bid_price(bids_info: dict) -> Optional[float]:
    """The relevant "price" for a bidding listing: the current highest bid
    if there is one, otherwise the minimum bid Marktplaats will accept."""
    bids = bids_info.get("bids") or []
    # A bid entry without a usable value is not worth taking the run down for;
    # fall back to the minimum bid as if there were no bids at all.
    values = [b.get("value") for b in bids if isinstance(b, dict)]
    values = [v for v in values if isinstance(v, (int, float))]
    if values:
        return max(values) / 100
    minimum = bids_info.get("currentMinimumBid")
    if minimum:
        return minimum / 100
    return None


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
            bids = bids_info.get("bids") or []
            listing.bid_count = len(bids)
            minimum = bids_info.get("currentMinimumBid")
            listing.bid_minimum = minimum / 100 if minimum else None
            price = resolve_bid_price(bids_info)
            # A MIN_BID listing already has a price from the search results
            # (what the seller is asking) and Marktplaats will accept a
            # *lower* minimum bid than that — seen in the wild: asking €47.50,
            # minimum bid €35. Those are two different numbers, so the asking
            # price stays the price (otherwise these listings would look
            # cheaper than fixed-price ones purely for being biddable) and the
            # minimum lands in bid_minimum. Only a real bid above the asking
            # price replaces it: below that bid the listing can't be had.
            if price is not None and (
                listing.price_eur is None or (bids and price > listing.price_eur)
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
            return max(dominant, key=lambda c: c.get("histogramCount", 0)).get("id")
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
ELECTRONIC_GROUPSET_RE = re.compile(r"\bdi2\b|\betap\b|\baxs\b", re.I)


def detect_groupset(text: str) -> tuple[str, Optional[int]]:
    """Best-effort groupset detection from free text. Returns (label, tier)
    for the highest-tier match found, or ("", None) if nothing recognized."""
    text_lower = text.lower()
    best_label = ""
    best_tier: Optional[int] = None
    for brand, name, pattern, tier, needs_brand in GROUPSET_CATALOG:
        if needs_brand and brand.lower() not in text_lower:
            continue
        if pattern.search(text):
            if best_tier is None or tier > best_tier:
                best_tier = tier
                best_label = f"{brand} {name}"

    if best_label and ELECTRONIC_GROUPSET_RE.search(text):
        best_label += " (elektronisch)"

    return best_label, best_tier


def parse_listing(raw: dict) -> Listing:
    price_info = raw.get("priceInfo", {})
    price_cents = price_info.get("priceCents")
    price_type = price_info.get("priceType", "")
    # priceCents is 0 for listings with no real price shown (e.g. an
    # unstarted bid or "see description") except when priceType is FREE,
    # where 0 genuinely means the item is free.
    has_real_price = isinstance(price_cents, (int, float)) and (
        price_cents > 0 or price_type == "FREE"
    )
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


def collect_listings(
    query: str, pages: int, delay: float, session: Optional[requests.Session] = None
) -> list[Listing]:
    """Fetch listings page by page. pages <= 0 means "fetch everything
    Marktplaats allows browsing to" (it caps pagination at a few hundred
    listings regardless of the total match count)."""
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})

    print(f"Zoeken naar '{query}' op Marktplaats...", file=sys.stderr)
    listings: dict[str, Listing] = {}
    dominant_category: Optional[int] = None
    skipped_offtopic = 0
    skipped_without_id = 0
    page = 1
    while True:
        try:
            data = fetch_page(session, query, page)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"warning: failed to fetch page {page}: {exc}", file=sys.stderr)
            break

        raw_listings = data.get("listings", [])
        if not raw_listings:
            break

        if dominant_category is None:
            dominant_category = extract_dominant_category(data)

        for raw in raw_listings:
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
            listings[listing.item_id] = listing

        max_page = data.get("maxAllowedPageNumber", page)
        target = min(pages, max_page) if pages > 0 else max_page
        print(f"  pagina {page}/{target} opgehaald — {len(listings)} advertenties tot nu toe", file=sys.stderr)

        reached_requested_limit = pages > 0 and page >= pages
        reached_site_limit = page >= max_page
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
    if skipped_offtopic:
        print(
            f"  {skipped_offtopic} advertenties buiten de hoofdcategorie overgeslagen "
            "(Marktplaats' zoekresultaten waaieren op diepere pagina's uit naar losse "
            "woord-matches)",
            file=sys.stderr,
        )

    return list(listings.values())


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
    listings: list[Listing], min_height: Optional[float], max_height: Optional[float]
) -> list[Listing]:
    if min_height is None and max_height is None:
        return listings

    lo = min_height if min_height is not None else 0.0
    hi = max_height if max_height is not None else float("inf")

    result = []
    for listing in listings:
        bounds = frame_height_bounds(listing.frame_height)
        if bounds is None:
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
    isn't one yet (no file, or an empty one)."""
    try:
        with open(path, newline="", encoding=CSV_READ_ENCODING) as f:
            return next(csv.reader(f), None)
    except FileNotFoundError:
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

    with open(path, "a", newline="", encoding="utf-8") as f:
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

    with open(path, "a", newline="", encoding="utf-8") as f:
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
                "label": (row.get("label") or pattern).strip(),
                "original_price_eur": original_price,
                "score": (row.get("score") or "").strip(),
                "specs": (row.get("specs") or "").strip(),
                "better": (row.get("better_than_baseline") or "").strip().lower() in ("1", "true", "yes", "ja"),
            }
        )
    return reference


def apply_reference_data(listings: list[Listing], reference: list[dict]) -> None:
    """Match each listing's title+description against the reference rows
    (first match in file order wins — put more specific patterns first) and
    fill in ref_* fields when found."""
    if not reference:
        return
    for listing in listings:
        haystack = f"{listing.title} {listing.description}"
        for row in reference:
            if row["regex"].search(haystack):
                listing.ref_label = row["label"]
                listing.ref_original_price = row["original_price_eur"]
                listing.ref_score = row["score"]
                listing.ref_specs = row["specs"]
                listing.ref_better = row["better"]
                if listing.price_eur is not None and row["original_price_eur"]:
                    listing.ref_pct_of_original = round(
                        listing.price_eur / row["original_price_eur"] * 100, 1
                    )
                break


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
        if (
            listing.bid_minimum_pct_of_median is not None
            and listing.bid_count in (None, 0)
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


def print_table(listings: list[Listing]) -> None:
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

    stats = price_stats(listings)
    if stats["count"] >= 2:
        print(f"gemiddelde prijs: €{stats['mean']:.0f} · mediaan: €{stats['median']:.0f} (over {stats['count']} geprijsde advertenties)")


def print_bid_overview(listings: list[Listing], limit: int = 25) -> None:
    """A separate look at the bidding listings — what it would cost to be the
    first bidder, and how that compares to the median and to what the model is
    known to go for. Listings nobody has bid on yet come first: there the
    minimum bid is still the real price."""
    bids = bid_listings(listings)
    if not bids:
        return

    open_bids = open_bid_listings(listings)
    print(f"\nBIED-OVERZICHT — {len(bids)} bied-advertenties, waarvan {len(open_bids)} nog zonder bod")
    print(f"  {'SCORE':>5} {'PRIJS':>8} {'%MED':>6}  {'BOD':<42} {'REFERENTIE':<28} TITEL")

    ordered = sort_by_score(open_bids) + sort_by_score([l for l in bids if not l.bid_open])
    for l in ordered[:limit]:
        score_str = f"{l.deal_score:.0f}" if l.deal_score is not None else "—"
        price_str = f"€{l.price_eur:.0f}" if l.price_eur is not None else l.price_type
        pct_str = f"{l.pct_of_median:.0f}%" if l.pct_of_median is not None else "—"
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
            f"  {score_str:>5} {price_str:>8} {pct_str:>6}  {status[:42]:<42} {ref[:28]:<28} {l.title[:40]}"
        )
        print(f"        {l.url}")

    if len(ordered) > limit:
        print(f"  ... en nog {len(ordered) - limit} (zie het HTML-rapport, tab 'Bieden')")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>Koopjes — {query}</title>
<style>
  :root {{
    --bg: #f7f7f8; --card: #ffffff; --text: #1a1a1a; --muted: #6b7280;
    --border: #e5e7eb; --new: #16a34a; --bargain: #dc2626; --accent: #2563eb; --better: #7c3aed;
    --dropped: #ea580c; --bid: #0891b2;
    --score-top: #15803d; --score-good: #65a30d; --score-ok: #6b7280; --score-low: #b0b4bb;
  }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: var(--bg);
         color: var(--text); margin: 0; padding: 24px; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 16px; }}
  .filters {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }}
  .filters button {{ border: 1px solid var(--border); background: var(--card); padding: 6px 14px;
                     border-radius: 999px; cursor: pointer; font-size: 0.85rem; }}
  .filters button.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px;
          overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
  th {{ user-select: none; color: var(--muted); font-weight: 600; white-space: nowrap; }}
  /* Only the sortable columns look clickable — the badge column has nothing
     to sort on, and a header that does nothing on click reads as broken. */
  th[data-key] {{ cursor: pointer; }}
  th[data-key]:hover {{ color: var(--text); }}
  tr:last-child td {{ border-bottom: none; }}
  tr.hidden {{ display: none; }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .badge {{ display: inline-block; font-size: 0.72rem; font-weight: 700; padding: 2px 7px;
           border-radius: 4px; margin-right: 4px; color: white; }}
  .badge.new {{ background: var(--new); }}
  .badge.bargain {{ background: var(--bargain); }}
  .badge.better {{ background: var(--better); }}
  .badge.dropped {{ background: var(--dropped); }}
  .badge.bid {{ background: var(--bid); }}
  .score-pill {{ display: inline-block; min-width: 30px; text-align: center; font-weight: 700;
                font-size: 0.85rem; padding: 3px 8px; border-radius: 6px; color: white;
                background: var(--score-ok); }}
  .score-pill.top {{ background: var(--score-top); }}
  .score-pill.good {{ background: var(--score-good); }}
  .score-pill.low {{ background: var(--score-low); }}
  .score-label {{ font-size: 0.7rem; color: var(--muted); margin-top: 2px; white-space: nowrap; }}
  td.score {{ cursor: help; }}
  .price {{ font-weight: 600; white-space: nowrap; }}
  .bid-tag {{ font-weight: 400; font-size: 0.72rem; color: var(--muted); }}
</style>
</head>
<body>
<h1>Koopjes — "{query}"</h1>
<div class="meta">Bijgewerkt {generated} · {total} advertenties · {new_count} nieuw sinds vorige run · {bargain_count} koopjes · {bid_count} bieden ({open_bid_count} zonder bod){price_stats_str}</div>
<div class="meta">Gesorteerd op dealscore (0-100, hoger = goedkoper dan zijn ijkpunten). Beweeg over een score voor de onderbouwing.</div>
<div class="filters">
  <button data-filter="all" class="active">Alles ({total})</button>
  <button data-filter="new">Nieuw ({new_count})</button>
  <button data-filter="bargain">Koopjes ({bargain_count})</button>
  <button data-filter="better">Beter dan referentie ({better_count})</button>
  <button data-filter="dropped">Prijsverlaging ({dropped_count})</button>
  <button data-filter="topdeal">Topdeals ({topdeal_count})</button>
  <button data-filter="bidding">Bieden ({bid_count})</button>
  <button data-filter="openbid">Vrij te bieden ({open_bid_count})</button>
</div>
<div class="table-wrap">
<table id="listings">
<thead>
<tr>
  <th></th>
  <th data-key="score">Score</th>
  <th data-key="price">Prijs</th>
  <th data-key="bid">Bod</th>
  <th data-key="pctmedian">% v. mediaan</th>
  <th data-key="title">Titel</th>
  <th data-key="frame">Framemaat</th>
  <th data-key="groupset">Groupset</th>
  <th data-key="condition">Conditie</th>
  <th data-key="city">Plaats</th>
  <th data-key="ref">Referentie</th>
  <th data-key="refprice">Nieuwprijs</th>
  <th data-key="refspecs">Specs</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<script>
  const table = document.getElementById('listings');
  const tbody = table.querySelector('tbody');
  document.querySelectorAll('.filters button').forEach(btn => {{
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.filters button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const filter = btn.dataset.filter;
      tbody.querySelectorAll('tr').forEach(row => {{
        const show = filter === 'all' || row.dataset[filter] === '1';
        row.classList.toggle('hidden', !show);
      }});
    }});
  }});
  let sortState = {{}};
  table.querySelectorAll('th[data-key]').forEach(th => {{
    th.addEventListener('click', () => {{
      const key = th.dataset.key;
      // Score is the one column you want highest-first on the first click.
      const asc = key in sortState ? !sortState[key] : key !== 'score';
      sortState = {{ [key]: asc }};
      const rows = Array.from(tbody.querySelectorAll('tr'));
      rows.sort((a, b) => {{
        let av = a.dataset[key], bv = b.dataset[key];
        if (['price', 'groupset', 'ref', 'pctmedian', 'score', 'bid'].includes(key)) {{ av = parseFloat(av); bv = parseFloat(bv); }}
        if (av < bv) return asc ? -1 : 1;
        if (av > bv) return asc ? 1 : -1;
        return 0;
      }});
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
</script>
</body>
</html>
"""


def score_css_class(score: Optional[float]) -> str:
    """The pill colour for a score — same tiers as its label."""
    if score is not None:
        for threshold, _, css_class in SCORE_LABELS:
            if score >= threshold:
                return css_class
    return "low"


def render_html(listings: list[Listing], query: str) -> str:
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

    stats = price_stats(listings)
    price_stats_str = (
        f" · gemiddeld €{stats['mean']:.0f} · mediaan €{stats['median']:.0f}"
        if stats["count"] >= 2
        else ""
    )

    return HTML_TEMPLATE.format(
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
    )


def write_html(listings: list[Listing], path: str, query: str) -> None:
    Path(path).write_text(render_html(listings, query), encoding="utf-8")


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
        default="racefiets",
        help="Search query (default: racefiets). Comma-separate multiple terms (e.g. "
        "\"racefiets,luidsprekers\") to run them all in one go — each gets its own HTML/CSV "
        "report (named after the query), while history/log/reference files stay shared.",
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
    return parser.parse_args(argv)


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


def sync_database(
    args: argparse.Namespace,
    query: str,
    listings: list[Listing],
    *,
    started_at: str,
    finished_at: str,
) -> None:
    """Mirror this run into koopjes.db, alongside the CSV/JSON files that
    stay the ones actually read elsewhere (reference_overview.py etc.) —
    PLAN_FIETSWAARDE.md fase 1b. All three legacy paths are passed
    explicitly: db.import_legacy()'s own defaults point at the working
    directory, and leaving one out here would silently import whatever
    happens to sit there instead of the file this run actually used."""
    conn = db.connect(args.db)
    try:
        db.import_legacy(
            conn,
            seen_listings_path=args.history_file,
            reference_prices_path=args.reference_file,
            reference_price_history_path=args.price_history_file,
        )
        db.sync_listings(conn, query, listings, finished_at)
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
        if args.pages <= 0:
            seen_ids = {listing.item_id for listing in listings}
            swept = db.sweep_disappeared(conn, query, seen_ids, finished_at)
            if swept:
                print(
                    f"{swept} advertentie(s) gemarkeerd als verdwenen na volledige crawl",
                    file=sys.stderr,
                )
    finally:
        conn.close()


def run_for_query(args: argparse.Namespace, query: str, multi: bool) -> None:
    if multi:
        print(f"\n=== {query} ===")

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    listings = collect_listings(query, args.pages, args.delay)

    # Filter on what the search results already tell us before the bid lookup,
    # which costs one request (plus --delay) per bidding listing: a listing
    # that's out of range or the wrong frame size gets dropped either way, so
    # fetching its bids first is time spent on nothing. Under the default
    # --bid-lookup fast this changes little (FAST_BID listings carry no price
    # yet, so they all pass), but under --bid-lookup all it saves a request
    # for every MIN_BID outside the range.
    listings = filter_by_price(listings, args.min_price, args.max_price)
    listings = filter_by_frame_height(listings, args.min_frame_height, args.max_frame_height)

    bid_lookup = "none" if args.no_bid_lookup else args.bid_lookup
    enrich_bid_listings(listings, args.delay, bid_lookup)
    apply_bid_flags(listings)

    # FAST_BID listings passed the filter above untested, for lack of a price.
    # Now that the lookup has given them one, the range applies to them too —
    # without this second pass a bid of EUR 2000 would sail through
    # --max-price 150.
    listings = filter_by_price(listings, args.min_price, args.max_price)

    reference = load_reference_data(args.reference_file)
    apply_reference_data(listings, reference)

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
        sync_database(args, query, listings, started_at=started_at, finished_at=finished_at)

    if args.bids_only:
        listings = bid_listings(listings)
    if args.min_score is not None:
        listings = [
            l for l in listings if l.deal_score is not None and l.deal_score >= args.min_score
        ]

    print_table(listings)
    print_bid_overview(listings)

    if args.output:
        output_path = per_query_path(args.output, query, multi)
        write_csv(listings, output_path)
        print(f"\nWrote {len(listings)} listings to {output_path}")

    if not args.no_html:
        html_path = per_query_path(args.html, query, multi)
        write_html(listings, html_path, query)
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

    queries = [q.strip() for q in args.query.split(",") if q.strip()]
    if not queries:
        print("error: no search query given", file=sys.stderr)
        return 1
    multi = len(queries) > 1

    for query in queries:
        run_for_query(args, query, multi)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
