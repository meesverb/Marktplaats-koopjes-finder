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
import re
import statistics
import sys
import time
import webbrowser
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

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
    pct_of_median: Optional[float] = None


def fetch_page(session: requests.Session, query: str, page: int) -> dict:
    """Fetch one Marktplaats search results page and return its embedded JSON data."""
    path = f"/q/{query}/" if page <= 1 else f"/q/{query}/p/{page}/"
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


def fetch_bid_info(session: requests.Session, vip_url: str) -> Optional[dict]:
    """Fetch a listing's own page and return its bidsInfo (current bids /
    minimum bid) — this isn't included in the search results for FAST_BID
    listings, only on the listing page itself (loaded client-side there via
    window.__CONFIG__)."""
    resp = session.get(vip_url, timeout=15)
    resp.raise_for_status()

    marker_pos = resp.text.find(CONFIG_MARKER)
    if marker_pos == -1:
        return None
    brace_pos = resp.text.find("{", marker_pos)
    if brace_pos == -1:
        return None
    config = extract_balanced_json(resp.text, brace_pos)
    if config is None:
        return None
    return config.get("listing", {}).get("bidsInfo")


def resolve_bid_price(bids_info: dict) -> Optional[float]:
    """The relevant "price" for a bidding listing: the current highest bid
    if there is one, otherwise the seller's minimum starting bid."""
    bids = bids_info.get("bids") or []
    if bids:
        return max(b["value"] for b in bids) / 100
    minimum = bids_info.get("currentMinimumBid")
    if minimum:
        return minimum / 100
    return None


def enrich_fast_bid_listings(
    listings: list[Listing], delay: float, session: Optional[requests.Session] = None
) -> None:
    """FAST_BID listings report €0 in search results; fetch their own page
    to fill in the real minimum/current bid."""
    targets = [l for l in listings if l.price_type == "FAST_BID" and l.price_eur is None]
    if not targets:
        return

    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})

    print(f"Biedprijzen ophalen voor {len(targets)} FAST_BID advertenties...", file=sys.stderr)
    for i, listing in enumerate(targets, start=1):
        try:
            bids_info = fetch_bid_info(session, listing.url)
        except requests.RequestException as exc:
            print(f"  warning: kon bod niet ophalen voor {listing.item_id}: {exc}", file=sys.stderr)
            continue

        if bids_info:
            price = resolve_bid_price(bids_info)
            if price is not None:
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
        for attr in raw_listing.get(group, []):
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
        price_eur=price_eur,
        price_type=price_type,
        city=raw.get("location", {}).get("cityName", ""),
        date=raw.get("date", ""),
        condition=extract_attribute(raw, "condition"),
        frame_height=extract_attribute(raw, "frameHeight"),
        groupset=groupset,
        groupset_tier=groupset_tier,
        url=url,
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

    if skipped_offtopic:
        print(
            f"  {skipped_offtopic} advertenties buiten de hoofdcategorie overgeslagen "
            "(Marktplaats' zoekresultaten waaieren op diepere pagina's uit naar losse "
            "woord-matches)",
            file=sys.stderr,
        )

    return list(listings.values())


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


def flag_bargains(listings: list[Listing], bargain_ratio: float) -> list[Listing]:
    priced = [l.price_eur for l in listings if l.price_eur]
    if len(priced) < 2:
        return listings

    median_price = statistics.median(priced)
    threshold = median_price * bargain_ratio
    for listing in listings:
        if listing.price_eur is not None:
            listing.pct_of_median = round(listing.price_eur / median_price * 100, 1)
            if listing.price_eur <= threshold:
                listing.is_bargain = True
    return listings


def price_stats(listings: list[Listing]) -> dict:
    priced = [l.price_eur for l in listings if l.price_eur is not None]
    if not priced:
        return {"count": 0, "mean": None, "median": None}
    return {
        "count": len(priced),
        "mean": statistics.mean(priced),
        "median": statistics.median(priced),
    }


def append_bargain_log(path: str, listings: list[Listing]) -> int:
    """Append newly-discovered bargains (is_new and is_bargain) to a running
    CSV log, so you keep a history of every bargain ever spotted instead of
    only the current snapshot. Returns how many rows were appended."""
    new_bargains = [l for l in listings if l.is_new and l.is_bargain]
    if not new_bargains:
        return 0

    file_exists = Path(path).exists()
    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fieldnames = ["logged_at"] + list(asdict(new_bargains[0]).keys())
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for listing in new_bargains:
            writer.writerow({"logged_at": logged_at, **asdict(listing)})
    return len(new_bargains)


def load_history(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_history(path: str, history: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


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
            entry["last_seen"] = now
            entry["last_price"] = listing.price_eur
    return history


def load_reference_data(path: str) -> list[dict]:
    """Load a user-maintained reference file (pattern,label,original_price_eur,
    score,notes) used to recognize known models and compare the asking price
    against what they cost new. Returns [] if the file doesn't exist — this
    feature is entirely optional."""
    try:
        with open(path, encoding="utf-8") as f:
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
        original_price = row.get("original_price_eur", "").strip()
        reference.append(
            {
                "regex": compiled,
                "label": (row.get("label") or pattern).strip(),
                "original_price_eur": float(original_price) if original_price else None,
                "score": (row.get("score") or "").strip(),
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
        for row in reference:
            if row["regex"].search(listing.title):
                listing.ref_label = row["label"]
                listing.ref_original_price = row["original_price_eur"]
                listing.ref_score = row["score"]
                if listing.price_eur is not None and row["original_price_eur"]:
                    listing.ref_pct_of_original = round(
                        listing.price_eur / row["original_price_eur"] * 100, 1
                    )
                break


def print_table(listings: list[Listing]) -> None:
    if not listings:
        print("No listings found.")
        return

    rows = sorted(
        listings,
        key=lambda l: (l.price_eur is None, l.price_eur if l.price_eur is not None else 0),
    )
    print(f"{'':4} {'PRICE':>8} {'%MED':>6}  {'FRAME':<12} {'GROUPSET':<22} {'CONDITION':<20} {'CITY':<15} {'TITLE'}")
    for l in rows:
        mark = (
            ("N" if l.is_new else " ")
            + ("*" if l.is_bargain else " ")
            + ("B" if l.price_is_bid else " ")
        )
        if l.price_eur is None:
            price_str = l.price_type
        elif l.price_eur < 1:
            price_str = f"€{l.price_eur:.2f}"
        else:
            price_str = f"€{l.price_eur:.0f}"
        pct_str = f"{l.pct_of_median:.0f}%" if l.pct_of_median is not None else "—"
        print(
            f"{mark:4} {price_str:>8} {pct_str:>6}  {l.frame_height[:12]:<12} {l.groupset[:22]:<22} "
            f"{l.condition[:20]:<20} {l.city[:15]:<15} {l.title[:60]}"
        )
        print(f"      {l.url}")
        if l.ref_label:
            bits = [l.ref_label]
            if l.ref_original_price is not None:
                bits.append(f"nieuw €{l.ref_original_price:.0f}")
            if l.ref_pct_of_original is not None:
                bits.append(f"nu {l.ref_pct_of_original:.0f}% daarvan")
            if l.ref_score:
                bits.append(f"score: {l.ref_score}")
            print(f"      referentie: {' · '.join(bits)}")

    bargains = [l for l in listings if l.is_bargain]
    new_ones = [l for l in listings if l.is_new]
    bids = [l for l in listings if l.price_is_bid]
    print(
        f"\n{len(listings)} listings, {len(bargains)} bargains (*), "
        f"{len(new_ones)} new since last run (N), {len(bids)} bidding (B, price = huidig/minimum bod)"
    )

    stats = price_stats(listings)
    if stats["count"] >= 2:
        print(f"gemiddelde prijs: €{stats['mean']:.0f} · mediaan: €{stats['median']:.0f} (over {stats['count']} geprijsde advertenties)")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>Racefiets koopjes — {query}</title>
<style>
  :root {{
    --bg: #f7f7f8; --card: #ffffff; --text: #1a1a1a; --muted: #6b7280;
    --border: #e5e7eb; --new: #16a34a; --bargain: #dc2626; --accent: #2563eb;
  }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: var(--bg);
         color: var(--text); margin: 0; padding: 24px; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 16px; }}
  .filters {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .filters button {{ border: 1px solid var(--border); background: var(--card); padding: 6px 14px;
                     border-radius: 999px; cursor: pointer; font-size: 0.85rem; }}
  .filters button.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px;
          overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
  th {{ cursor: pointer; user-select: none; color: var(--muted); font-weight: 600; white-space: nowrap; }}
  th:hover {{ color: var(--text); }}
  tr:last-child td {{ border-bottom: none; }}
  tr.hidden {{ display: none; }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .badge {{ display: inline-block; font-size: 0.72rem; font-weight: 700; padding: 2px 7px;
           border-radius: 4px; margin-right: 4px; color: white; }}
  .badge.new {{ background: var(--new); }}
  .badge.bargain {{ background: var(--bargain); }}
  .price {{ font-weight: 600; white-space: nowrap; }}
  .bid-tag {{ font-weight: 400; font-size: 0.72rem; color: var(--muted); }}
</style>
</head>
<body>
<h1>Racefiets koopjes — "{query}"</h1>
<div class="meta">Bijgewerkt {generated} · {total} advertenties · {new_count} nieuw sinds vorige run · {bargain_count} koopjes{price_stats_str}</div>
<div class="filters">
  <button data-filter="all" class="active">Alles ({total})</button>
  <button data-filter="new">Nieuw ({new_count})</button>
  <button data-filter="bargain">Koopjes ({bargain_count})</button>
</div>
<table id="listings">
<thead>
<tr>
  <th data-key="flags"></th>
  <th data-key="price">Prijs</th>
  <th data-key="pctmedian">% v. mediaan</th>
  <th data-key="title">Titel</th>
  <th data-key="frame">Framemaat</th>
  <th data-key="groupset">Groupset</th>
  <th data-key="condition">Conditie</th>
  <th data-key="city">Plaats</th>
  <th data-key="ref">Referentie</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
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
      const asc = !sortState[key];
      sortState = {{ [key]: asc }};
      const rows = Array.from(tbody.querySelectorAll('tr'));
      rows.sort((a, b) => {{
        let av = a.dataset[key], bv = b.dataset[key];
        if (key === 'price' || key === 'groupset' || key === 'ref' || key === 'pctmedian') {{ av = parseFloat(av); bv = parseFloat(bv); }}
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


def render_html(listings: list[Listing], query: str) -> str:
    rows_sorted = sorted(
        listings,
        key=lambda l: (
            not (l.is_new and l.is_bargain),
            not l.is_new,
            not l.is_bargain,
            l.pct_of_median is None,
            l.pct_of_median if l.pct_of_median is not None else float("inf"),
        ),
    )

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
        price_sort_value = l.price_eur if l.price_eur is not None else -1

        ref_bits = []
        if l.ref_label:
            ref_bits.append(l.ref_label)
            if l.ref_pct_of_original is not None:
                ref_bits.append(f"{l.ref_pct_of_original:.0f}% van €{l.ref_original_price:.0f} nieuw")
            elif l.ref_original_price is not None:
                ref_bits.append(f"nieuw €{l.ref_original_price:.0f}")
            if l.ref_score:
                ref_bits.append(f"score: {l.ref_score}")
        ref_str = html_lib.escape(" · ".join(ref_bits)) if ref_bits else "—"
        ref_sort = l.ref_pct_of_original if l.ref_pct_of_original is not None else 1e9

        pct_median_str = f"{l.pct_of_median:.0f}%" if l.pct_of_median is not None else "—"
        pct_median_sort = l.pct_of_median if l.pct_of_median is not None else 1e9

        row_html.append(
            "<tr data-new='{is_new}' data-bargain='{is_bargain}' "
            "data-price='{price_sort}' data-title='{title_attr}' "
            "data-frame='{frame_attr}' data-groupset='{groupset_sort}' "
            "data-condition='{condition_attr}' data-city='{city_attr}' data-ref='{ref_sort}' "
            "data-pctmedian='{pct_median_sort}'>"
            "<td>{badges}</td>"
            "<td class='price'>{price}</td>"
            "<td>{pct_median}</td>"
            "<td><a href='{url}' target='_blank' rel='noopener'>{title}</a></td>"
            "<td>{frame}</td>"
            "<td>{groupset}</td>"
            "<td>{condition}</td>"
            "<td>{city}</td>"
            "<td>{ref}</td>"
            "</tr>".format(
                is_new="1" if l.is_new else "0",
                is_bargain="1" if l.is_bargain else "0",
                price_sort=price_sort_value,
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
        price_stats_str=price_stats_str,
        rows="\n".join(row_html),
    )


def write_html(listings: list[Listing], path: str, query: str) -> None:
    Path(path).write_text(render_html(listings, query), encoding="utf-8")


def write_csv(listings: list[Listing], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(listings[0]).keys()) if listings else [])
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
        "--no-bid-lookup",
        action="store_true",
        help="Skip fetching each FAST_BID listing's own page for its real minimum/current bid "
        "(faster, but those listings keep showing as FAST_BID with no price instead)",
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


def run_for_query(args: argparse.Namespace, query: str, multi: bool) -> None:
    if multi:
        print(f"\n=== {query} ===")

    listings = collect_listings(query, args.pages, args.delay)

    if not args.no_bid_lookup:
        enrich_fast_bid_listings(listings, args.delay)

    if args.min_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur >= args.min_price]
    if args.max_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur <= args.max_price]

    listings = filter_by_frame_height(listings, args.min_frame_height, args.max_frame_height)

    reference = load_reference_data(args.reference_file)
    apply_reference_data(listings, reference)

    listings = flag_bargains(listings, args.bargain_ratio)

    history = load_history(args.history_file)
    history = apply_history(listings, history)
    save_history(args.history_file, history)

    if not args.no_log:
        logged = append_bargain_log(args.log_file, listings)
        if logged:
            print(f"Logged {logged} new bargain(s) to {args.log_file}")

    print_table(listings)

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
