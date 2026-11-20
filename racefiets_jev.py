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
import os
import re
import statistics
import sys
import time
import webbrowser
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

import computers
import console
import crawl
import db
import dealscore
import report
import sleepers
import upgrade


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


# --- The listing page: full description and "Kenmerken" ---------------------


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


def append_bargain_log(path: str, listings: list[crawl.Listing]) -> int:
    """Append newly-discovered bargains (is_new and is_bargain) to a running
    CSV log, so you keep a history of every bargain ever spotted instead of
    only the current snapshot. Returns how many rows were appended."""
    new_bargains = [l for l in listings if l.is_new and l.is_bargain]
    if not new_bargains:
        return 0

    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current_fields = ["logged_at"] + crawl.LISTING_FIELDS
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


def apply_reference_market_stats(listings: list[crawl.Listing], stats: dict) -> None:
    for listing in listings:
        if listing.ref_label and listing.ref_label in stats:
            s = stats[listing.ref_label]
            listing.ref_market_avg = s["mean"]
            listing.ref_market_count = s["count"]


PRICE_HISTORY_FIELDS = ["date", "ref_label", "item_id", "price_eur", "title"]


def append_reference_price_observations(path: str, listings: list[crawl.Listing]) -> int:
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
        if l.is_new and l.ref_label and l.price_eur and l.price_is_asking
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


def apply_history(listings: list[crawl.Listing], history: dict) -> dict:
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
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        return []

    # reference_bike_catalog.csv sits next to the pattern files and looks
    # like one, but has no pattern column: every row would be skipped below
    # and the run would quietly match nothing.
    if rows and "pattern" not in (reader.fieldnames or []):
        print(
            f"warning: {path} heeft geen 'pattern'-kolom en is dus geen referentiebestand "
            "(reference_bike_catalog.csv is een catalogus, zie docs/referentiedata.md); er wordt niets herkend",
            file=sys.stderr,
        )
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


def apply_reference_data(listings: list[crawl.Listing], reference: list[dict]) -> dict[str, list[str]]:
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


def lookup_listing_details(args: argparse.Namespace, listings: list[crawl.Listing]) -> dict:
    """--detail-lookup: first put back what earlier runs fetched (no
    request), then fetch the listing page for the few new listings that could
    be an upgrade (upgrade.detail_lookup_targets()). Returns {item_id: full
    description} for the pages fetched now, for sync_database() to store.

    Needs the database — without it every run would fetch the same pages
    again — and a budget from mijn_fiets.md, since "could be an upgrade"
    means "within budget". Without either it does nothing, quietly for
    --no-db and with a line otherwise."""
    if args.no_db or getattr(args, "detail_lookup", "none") == "none" or not listings:
        return {}
    if Path(args.db).exists():
        conn = db.connect(args.db)
        try:
            stored = db.load_listing_details(conn, [l.item_id for l in listings])
            stored_site = db.read_listing_specs(conn, source=db.SITE_SPEC_SOURCE) if stored else {}
        finally:
            conn.close()
        for listing in listings:
            if listing.item_id in stored:
                text, frame_height = stored[listing.item_id]
                apply_listing_details(listing, text, stored_site.get(listing.item_id, {}), frame_height)

    owner, problem = report.load_owner_context(args.mijn_fiets, args.db)
    reason = problem or (None if owner is None or owner.budgets is not None else owner.valuation_problem)
    if owner is None or owner.budgets is None or owner.target_size_cm is None:
        if reason:
            print(f"--detail-lookup overgeslagen: {reason}", file=sys.stderr)
        return {}
    targets = upgrade.detail_lookup_targets(
        listings,
        budgets=owner.budgets,
        target_size_cm=owner.target_size_cm,
        config=owner.config,
    )
    if not targets:
        return {}

    session = requests.Session()
    session.headers.update({"User-Agent": crawl.USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9"})
    print(f"Advertentiepagina's ophalen voor {len(targets)} kanshebber(s) binnen budget...", file=sys.stderr)
    fetched = {}
    for i, listing in enumerate(targets, start=1):
        try:
            page = fetch_listing_page(session, listing.url)
        except requests.RequestException as exc:
            print(f"  warning: kon {listing.item_id} niet ophalen: {exc}", file=sys.stderr)
        else:
            try:
                stats = crawl.page_stats(crawl.listing_page_data(page))
            except crawl.ListingPageError:
                stats = None  # the description below is what this lookup is for
            if stats:
                listing.page_stats = {**stats, "source": "omschrijving"}
            parsed = crawl.parse_listing_page(page)
            if parsed is None:
                crawl.warn_detail_structure_changed("omschrijving niet gevonden")
            else:
                text, attributes = parsed
                apply_listing_details(
                    listing, text, crawl.page_specs(attributes), attributes.get(crawl.PAGE_FRAME_HEIGHT_LABEL, "")
                )
                fetched[listing.item_id] = text
        if i < len(targets):
            time.sleep(args.delay)
    return fetched


def fetch_listing_page(session: requests.Session, url: str) -> str:
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def apply_listing_details(
    listing: crawl.Listing, text: str, specs: dict[str, str], frame_height: str
) -> None:
    """The listing page's content onto a listing. The groupset is read again
    from the full text; the search's own attributes stay where the page has
    nothing, and a frame height only fills an empty one."""
    listing.detail_text = text
    listing.site_specs = {**specs, **listing.site_specs}
    if frame_height and not listing.frame_height:
        listing.frame_height = frame_height
    groupset, tier = crawl.detect_groupset(f"{listing.title} {text}")
    if tier is not None:
        listing.groupset, listing.groupset_tier = groupset, tier


def build_report_panels(args: argparse.Namespace, listings: list[crawl.Listing], median: Optional[float]):
    """The report's extra tabs for this run. The own-bike valuation reads
    koopjes.db — which sync_database() has just written, so it already holds
    this crawl — but never writes to it. With --no-db there is nothing to
    value against, and the tabs say that rather than guess a budget."""
    owner, problem = report.load_owner_context(
        args.mijn_fiets, None if args.no_db else args.db
    )
    reason = problem or (owner.valuation_problem if owner else None)
    if reason:
        print(f"Rapport, tabs 'Mijn fiets'/'Upgrade': {reason}", file=sys.stderr)
    return report.build_panels(listings, median, owner=owner, owner_problem=problem)


def write_csv(listings: list[crawl.Listing], path: str) -> None:
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
        writer = csv.DictWriter(f, fieldnames=crawl.LISTING_FIELDS)
        writer.writeheader()
        for listing in listings:
            row = asdict(listing)
            writer.writerow({name: row[name] for name in crawl.LISTING_FIELDS})


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query",
        # None rather than DEFAULT_QUERY, so main() can tell "--watchlist
        # powermeter" (run only that) from "--query racefiets --watchlist
        # powermeter" (run both). See resolve_queries().
        default=None,
        help=f"Search query (default: {crawl.DEFAULT_QUERY}). Comma-separate multiple terms (e.g. "
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
        choices=sorted(crawl.SORT_OPTIONS),
        default="optimized",
        help="Result order to crawl in: 'optimized' (default, Marktplaats' own 'Standaard' "
        "order via the search page) or 'newest' (newest first, via Marktplaats' search API) — "
        "use newest for scheduled runs, so a few pages cover everything new since the last run",
    )
    parser.add_argument(
        "--split",
        action="store_true",
        help="Met --pages 0 en --category: een zoekopdracht met meer resultaten dan Marktplaats "
        "doorbladert (~5000) in delen ophalen (per staat en prijsschijf), zodat alles binnenkomt",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Only search in these Marktplaats categories (comma-separated key or number, e.g. "
        "'fietsonderdelen' or 'fietsaccessoires-fietscomputers'), filtered by Marktplaats "
        "itself. Replaces the automatic main-category guess, which keeps only one category. "
        "An unknown category lists the ones that do have results. 'alle': every category, "
        "no filter and no guess — everything Marktplaats finds for the query",
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
        "--detail-lookup",
        choices=["budget", "none"],
        default="budget",
        help="Fetch the listing page (full description and 'Kenmerken') for complete road "
        "bikes that fit the frame size and the budget from mijn_fiets.md — at most 10 per "
        "run, each listing only once, and only with the database (it remembers what was "
        "fetched). 'none' skips it",
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
        "--summary-file",
        default=None,
        help="Append one JSON line per report (counts, report path, the most interesting new "
        "listings) to this file. koopjes.py uses it for its overview page",
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
    "split": "flag",
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
        return [crawl.DEFAULT_QUERY]
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
    listings: list[crawl.Listing],
    *,
    crawled_item_ids: set[str],
    started_at: str,
    finished_at: str,
    reference_matches: Optional[dict[str, list[str]]] = None,
    crawl_complete: bool = False,
    crawl_note: str = "",
    crawl_near_complete: bool = False,
    fetched_details: Optional[dict] = None,
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
        if fetched_details:
            db.save_listing_details(conn, fetched_details, finished_at)
        db.sync_listing_specs(conn, crawl.extract_listing_specs(listings))
        db.sync_listing_specs(
            conn, {l.item_id: l.site_specs for l in listings}, source=db.SITE_SPEC_SOURCE
        )
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
        if args.pages <= 0 and not crawl_complete and crawl_near_complete:
            missed, swept = db.sweep_disappeared(
                conn, query, crawled_item_ids, finished_at, confirmed=False, report_missed=True
            )
            print(
                f"verdwijn-sweep voorlopig: de crawl van '{query}' was compleet op een paar na "
                f"({crawl_note}) — waarschijnlijk verdween er een advertentie tijdens het "
                f"bladeren. {missed} gemiste advertentie(s) genoteerd; ze tellen pas als verdwenen "
                "als de volgende volledige crawl ze ook mist"
                + (f". {swept} die de vorige keer ook al ontbraken, nu gemarkeerd als verdwenen." if swept else "."),
                file=sys.stderr,
            )
        elif args.pages <= 0 and not crawl_complete:
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
    listings = crawl.collect_listings(
        query, args.pages, args.delay, sort=args.sort, categories=categories or None,
        split=getattr(args, "split", False),
    )
    # Kept before any filtering: this is what the crawl actually saw, which is
    # what "has this listing disappeared?" has to be answered against.
    crawled_item_ids = {listing.item_id for listing in listings}
    # A plain list (only a test's stand-in returns one) says nothing about
    # completeness, so it counts as incomplete: the sweep is the one step
    # where guessing wrong corrupts data.
    crawl_complete = getattr(listings, "complete", False)
    crawl_note = getattr(listings, "note", "")
    cut_off_ids = getattr(listings, "cut_off_ids", ())

    # Filter on what the search results already tell us before the bid lookup,
    # which costs one request (plus --delay) per bidding listing: a listing
    # that's out of range or the wrong frame size gets dropped either way, so
    # fetching its bids first is time spent on nothing. Under the default
    # --bid-lookup fast this changes little (FAST_BID listings carry no price
    # yet, so they all pass), but under --bid-lookup all it saves a request
    # for every MIN_BID outside the range.
    listings = crawl.filter_by_price(listings, args.min_price, args.max_price)
    listings = crawl.filter_by_frame_height(
        listings,
        args.min_frame_height,
        args.max_frame_height,
        keep_unknown=not args.strict_frame_height,
    )

    bid_lookup = "none" if args.no_bid_lookup else args.bid_lookup
    crawl.enrich_bid_listings(listings, args.delay, bid_lookup)
    crawl.apply_bid_flags(listings)

    # FAST_BID listings passed the filter above untested, for lack of a price.
    # Now that the lookup has given them one, the range applies to them too —
    # without this second pass a bid of EUR 2000 would sail through
    # --max-price 150.
    listings = crawl.filter_by_price(listings, args.min_price, args.max_price)

    reference = load_reference_data(args.reference_file)
    reference_matches = apply_reference_data(listings, reference)

    if not args.no_price_history:
        market_stats = load_reference_market_stats(args.price_history_file)
        apply_reference_market_stats(listings, market_stats)

    listings = dealscore.flag_bargains(listings, args.bargain_ratio)

    history = load_history(args.history_file)
    # Before apply_history(), which adds this round's listings to it.
    if args.sort == "newest" and crawl.window_too_small(
        cut_off_ids, history, {listing.item_id for listing in listings}
    ):
        print(
            f"let op: de onderste {crawl.WINDOW_CHECK_LISTINGS} advertenties op pagina {args.pages} waren "
            f"allemaal nieuw. Met --sort newest betekent dat dat er achter pagina {args.pages} nog "
            "nieuwe kunnen staan die deze ronde niet zag (een volledige crawl vindt ze wel). Zet "
            "'pages' hoger of draai deze ronde vaker.",
            file=sys.stderr,
        )
    history = apply_history(listings, history)
    save_history(args.history_file, history)

    if not args.no_price_history:
        recorded = append_reference_price_observations(args.price_history_file, listings)
        if recorded:
            print(f"Recorded {recorded} price observation(s) to {args.price_history_file}")

    fetched_details = lookup_listing_details(args, listings)

    dealscore.score_listings(listings)
    sleepers.apply_sleeper_signals(listings)
    # Before sync_database(), so the comparables from earlier runs don't
    # already contain this run twice; this run's own listings are added in
    # apply_computer_signals() itself.
    computers.apply_computer_signals(listings, db_path=None if args.no_db else args.db)

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
            crawl_near_complete=getattr(listings, "near_complete", False),
            fetched_details=fetched_details,
        )

    # Captured before --bids-only/--min-score filter the list for the
    # report: the "% v. mediaan" column (set in flag_bargains, above) is
    # already measured against the unfiltered set, and the footer under the
    # table has to report the same median or it contradicts its own column.
    all_stats = dealscore.price_stats(listings)

    if args.bids_only:
        listings = crawl.bid_listings(listings)
    if args.min_score is not None:
        listings = [
            l for l in listings if l.deal_score is not None and l.deal_score >= args.min_score
        ]

    console.print_table(listings, stats=all_stats)
    console.print_bid_overview(listings, headroom=console.bid_headroom_by_id(listings, all_stats.get("median")))
    console.print_sleepers(listings)
    computers.print_computers(listings)

    if args.output:
        output_path = report_path(args.output, query, multi, report_name)
        write_csv(listings, output_path)
        print(f"\nWrote {len(listings)} listings to {output_path}")

    html_path = None if args.no_html else report_path(args.html, query, multi, report_name)
    panels = None
    if html_path is not None:
        panels = build_report_panels(args, listings, all_stats.get("median"))
        report.write_html(listings, html_path, query, stats=all_stats, panels=panels)
        print(f"Wrote HTML overview to {html_path}")

    if args.summary_file:
        append_summary(
            args.summary_file,
            run_summary(
                listings,
                name=report_name or query,
                query=query,
                finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                report_path=html_path,
                crawl_complete=crawl_complete,
                crawl_note=crawl_note,
                upgrades=getattr(panels, "upgrades", ()),
            ),
        )

    if html_path is not None:
        new_count = sum(1 for l in listings if l.is_new)
        should_open = args.open_browser == "always" or (
            args.open_browser == "auto" and new_count > 0
        )
        if should_open:
            try:
                webbrowser.open(Path(html_path).resolve().as_uri())
            except webbrowser.Error as exc:
                print(f"warning: could not open browser: {exc}", file=sys.stderr)


# How many new listings a summary line carries for the overview page: enough
# to show what's worth a look, not a second copy of the report.
SUMMARY_HIGHLIGHTS = 5
# The deal list koopjes.py writes to lijsten/beste_koopjes.txt: long enough
# to paste into a conversation and have each one checked, not the whole run.
SUMMARY_DEALS = 20


def run_summary(
    listings: list[crawl.Listing],
    *,
    name: str,
    query: str,
    finished_at: str,
    report_path: Optional[str],
    crawl_complete: bool,
    crawl_note: str,
    upgrades: tuple = (),
) -> dict:
    """What koopjes.py's overview page shows for one report: the same counts
    as the console's summary line, the report's top upgrade candidates, and
    the new listings most worth a look — better than the reference first,
    then by deal score.

    A FAST_BID listing's price is the bid so far, so its deal score says how
    far the bidding has got, not what the thing costs: in a real run those
    were most of the "score 100" highlights. They only make the list when
    they beat the reference; the report's Biedpaneel is where they belong."""
    def is_top(l: crawl.Listing) -> bool:
        return l.deal_score is not None and l.deal_score >= dealscore.TOP_DEAL_SCORE

    new = [l for l in listings if l.is_new]
    highlights = sorted(
        (l for l in new if l.ref_better or l.price_type != "FAST_BID"),
        key=lambda l: (not l.ref_better, -(l.deal_score if l.deal_score is not None else -1)),
    )[:SUMMARY_HIGHLIGHTS]
    return {
        "name": name,
        "query": query,
        "finished_at": finished_at,
        "report": report_path,
        "listings": len(listings),
        "new": len(new),
        "bargains": sum(1 for l in listings if l.is_bargain),
        "top_deals": sum(1 for l in listings if is_top(l)),
        "better": sum(1 for l in listings if l.ref_better),
        "price_drops": sum(1 for l in listings if l.price_dropped),
        "bidding": sum(1 for l in listings if l.price_is_bid),
        "crawl_complete": crawl_complete,
        "crawl_note": crawl_note,
        # Only this run's new ones: the overview is read after every round,
        # and a sleeper is worth something for a few hours at most.
        "sleepers": [
            {
                "title": l.title,
                "price": sleepers.price_text(l),
                "score": l.sleeper_score,
                "reasons": l.sleeper_reasons,
                "city": l.city,
                "image": l.image_urls.split()[0] if l.image_urls else "",
                "url": l.url,
            }
            for l in sleepers.sleepers(new)[:SUMMARY_HIGHLIGHTS]
        ],
        "highlights": [
            {
                "title": l.title,
                "price_eur": l.price_eur,
                "price_type": l.price_type,
                "deal_score": l.deal_score,
                "better": l.ref_better,
                "ref_label": l.ref_label,
                "url": l.url,
            }
            for l in highlights
        ],
        "deals": [
            {
                "title": l.title,
                "price_eur": l.price_eur,
                "price_type": l.price_type,
                "deal_score": l.deal_score,
                "reasons": l.deal_reasons,
                "ref_label": l.ref_label,
                "frame_height": l.frame_height,
                "city": l.city,
                "url": l.url,
            }
            # Same rule as the highlights: a running FAST_BID's "price" is the
            # bid so far, so its score says nothing about the deal yet.
            for l in sorted(
                (l for l in listings
                 if is_top(l) and (l.ref_better or l.price_type != "FAST_BID")),
                key=lambda l: -l.deal_score,
            )[:SUMMARY_DEALS]
        ],
        "upgrades": [
            {
                "title": c.listing.title,
                "price_eur": c.effective.amount,
                "price_basis": c.effective.basis,
                "quality": round(c.quality.total),
                "gain": round(c.gain),
                "per_100_eur": round(c.points_per_100_eur, 1),
                "new": c.listing.is_new,
                "url": c.listing.url,
            }
            for c in upgrades[:SUMMARY_HIGHLIGHTS]
        ],
    }


def append_summary(path: str, summary: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


def notify_better_matches(listings: list[crawl.Listing]) -> None:
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
