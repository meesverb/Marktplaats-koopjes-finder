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
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, asdict
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
    url: str
    is_bargain: bool = False


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


def extract_condition(raw_listing: dict) -> str:
    for attr in raw_listing.get("attributes", []):
        if attr.get("key") == "condition":
            return attr.get("value", "")
    return ""


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

    return Listing(
        item_id=raw.get("itemId", ""),
        title=raw.get("title", ""),
        price_eur=price_eur,
        price_type=price_info.get("priceType", ""),
        city=raw.get("location", {}).get("cityName", ""),
        date=raw.get("date", ""),
        condition=extract_condition(raw),
        url=url,
    )



def collect_listings(
    query: str, pages: int, delay: float, session: Optional[requests.Session] = None
) -> list[Listing]:
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})

    listings: dict[str, Listing] = {}
    for page in range(1, pages + 1):
        try:
            data = fetch_page(session, query, page)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"warning: failed to fetch page {page}: {exc}", file=sys.stderr)
            break

        raw_listings = data.get("listings", [])
        if not raw_listings:
            break

        for raw in raw_listings:
            listing = parse_listing(raw)
            listings[listing.item_id] = listing

        max_page = data.get("maxAllowedPageNumber", pages)
        if page >= max_page:
            break
        if page < pages:
            time.sleep(delay)

    return list(listings.values())


def flag_bargains(listings: list[Listing], bargain_ratio: float) -> list[Listing]:
    priced = [l.price_eur for l in listings if l.price_eur]
    if len(priced) < 2:
        return listings

    median_price = statistics.median(priced)
    threshold = median_price * bargain_ratio
    for listing in listings:
        if listing.price_eur is not None and listing.price_eur <= threshold:
            listing.is_bargain = True
    return listings


def print_table(listings: list[Listing]) -> None:
    if not listings:
        print("No listings found.")
        return

    rows = sorted(
        listings,
        key=lambda l: (l.price_eur is None, l.price_eur if l.price_eur is not None else 0),
    )
    print(f"{'':2} {'PRICE':>8}  {'CONDITION':<20} {'CITY':<15} {'TITLE'}")
    for l in rows:
        mark = "*" if l.is_bargain else " "
        if l.price_eur is None:
            price_str = l.price_type
        elif l.price_eur < 1:
            price_str = f"€{l.price_eur:.2f}"
        else:
            price_str = f"€{l.price_eur:.0f}"
        print(f"{mark:2} {price_str:>8}  {l.condition[:20]:<20} {l.city[:15]:<15} {l.title[:60]}")
        print(f"     {l.url}")

    bargains = [l for l in listings if l.is_bargain]
    print(f"\n{len(listings)} listings, {len(bargains)} flagged as bargains (*)")


def write_csv(listings: list[Listing], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(listings[0]).keys()) if listings else [])
        writer.writeheader()
        for listing in listings:
            writer.writerow(asdict(listing))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="racefiets", help="Search query (default: racefiets)")
    parser.add_argument("--pages", type=int, default=1, help="Number of result pages to fetch (30 listings/page)")
    parser.add_argument("--min-price", type=float, default=None, help="Ignore listings cheaper than this (EUR)")
    parser.add_argument("--max-price", type=float, default=None, help="Ignore listings pricier than this (EUR)")
    parser.add_argument(
        "--bargain-ratio",
        type=float,
        default=0.6,
        help="Flag listings priced at or below this fraction of the median price (default: 0.6)",
    )
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds to wait between page requests (default: 1.5)")
    parser.add_argument("--output", default=None, help="Optional path to write results as CSV")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    listings = collect_listings(args.query, args.pages, args.delay)

    if args.min_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur >= args.min_price]
    if args.max_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur <= args.max_price]

    listings = flag_bargains(listings, args.bargain_ratio)
    print_table(listings)

    if args.output:
        write_csv(listings, args.output)
        print(f"\nWrote {len(listings)} listings to {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
