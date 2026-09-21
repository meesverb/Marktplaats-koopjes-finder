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
    url: str
    is_bargain: bool = False
    is_new: bool = False
    first_seen: str = ""


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


def print_table(listings: list[Listing]) -> None:
    if not listings:
        print("No listings found.")
        return

    rows = sorted(
        listings,
        key=lambda l: (l.price_eur is None, l.price_eur if l.price_eur is not None else 0),
    )
    print(f"{'':3} {'PRICE':>8}  {'CONDITION':<20} {'CITY':<15} {'TITLE'}")
    for l in rows:
        mark = ("N" if l.is_new else " ") + ("*" if l.is_bargain else " ")
        if l.price_eur is None:
            price_str = l.price_type
        elif l.price_eur < 1:
            price_str = f"€{l.price_eur:.2f}"
        else:
            price_str = f"€{l.price_eur:.0f}"
        print(f"{mark:3} {price_str:>8}  {l.condition[:20]:<20} {l.city[:15]:<15} {l.title[:60]}")
        print(f"      {l.url}")

    bargains = [l for l in listings if l.is_bargain]
    new_ones = [l for l in listings if l.is_new]
    print(
        f"\n{len(listings)} listings, {len(bargains)} bargains (*), "
        f"{len(new_ones)} new since last run (N)"
    )


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
</style>
</head>
<body>
<h1>Racefiets koopjes — "{query}"</h1>
<div class="meta">Bijgewerkt {generated} · {total} advertenties · {new_count} nieuw sinds vorige run · {bargain_count} koopjes</div>
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
  <th data-key="title">Titel</th>
  <th data-key="condition">Conditie</th>
  <th data-key="city">Plaats</th>
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
        if (key === 'price') {{ av = parseFloat(av); bv = parseFloat(bv); }}
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
            l.price_eur is None,
            l.price_eur if l.price_eur is not None else float("inf"),
        ),
    )

    row_html = []
    for l in rows_sorted:
        price_str = (
            html_lib.escape(l.price_type) if l.price_eur is None
            else f"€{l.price_eur:.2f}" if l.price_eur < 1
            else f"€{l.price_eur:.0f}"
        )
        badges = ""
        if l.is_new:
            badges += '<span class="badge new">NIEUW</span>'
        if l.is_bargain:
            badges += '<span class="badge bargain">KOOPJE</span>'
        price_sort_value = l.price_eur if l.price_eur is not None else -1
        row_html.append(
            "<tr data-new='{is_new}' data-bargain='{is_bargain}' "
            "data-price='{price_sort}' data-title='{title_attr}' "
            "data-condition='{condition_attr}' data-city='{city_attr}'>"
            "<td>{badges}</td>"
            "<td class='price'>{price}</td>"
            "<td><a href='{url}' target='_blank' rel='noopener'>{title}</a></td>"
            "<td>{condition}</td>"
            "<td>{city}</td>"
            "</tr>".format(
                is_new="1" if l.is_new else "0",
                is_bargain="1" if l.is_bargain else "0",
                price_sort=price_sort_value,
                title_attr=html_lib.escape(l.title, quote=True),
                condition_attr=html_lib.escape(l.condition, quote=True),
                city_attr=html_lib.escape(l.city, quote=True),
                badges=badges,
                price=price_str,
                url=html_lib.escape(l.url, quote=True),
                title=html_lib.escape(l.title),
                condition=html_lib.escape(l.condition),
                city=html_lib.escape(l.city),
            )
        )

    return HTML_TEMPLATE.format(
        query=html_lib.escape(query),
        generated=datetime.now().strftime("%d-%m-%Y %H:%M"),
        total=len(listings),
        new_count=sum(1 for l in listings if l.is_new),
        bargain_count=sum(1 for l in listings if l.is_bargain),
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
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    listings = collect_listings(args.query, args.pages, args.delay)

    if args.min_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur >= args.min_price]
    if args.max_price is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur <= args.max_price]

    listings = flag_bargains(listings, args.bargain_ratio)

    history = load_history(args.history_file)
    history = apply_history(listings, history)
    save_history(args.history_file, history)

    print_table(listings)

    if args.output:
        write_csv(listings, args.output)
        print(f"\nWrote {len(listings)} listings to {args.output}")

    if not args.no_html:
        write_html(listings, args.html, args.query)
        print(f"Wrote HTML overview to {args.html}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
