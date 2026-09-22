#!/usr/bin/env python3
"""Look up which models a brand has on hifidatabase.com, with view/vote
counts as a quick popularity signal.

This is a research aid for filling in reference_prices.csv: one fetch per
brand is much cheaper than a full web search per model, and the vote count
tells you upfront whether a model is even worth researching further.

Usage:
    python check_hifi_brand.py "Mission"
    python check_hifi_brand.py "Wharfedale" --min-votes 3

Note: hifidatabase.com has bot-protection that kicks in after several rapid
requests, so use this a brand at a time rather than in a tight loop.
"""
from __future__ import annotations

import argparse
import re
import sys
from urllib.parse import quote

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def check_brand(brand: str) -> list[tuple[str, str, int, int, int]]:
    """Returns a list of (model_name, detail_url, views, votes, reviews) for
    the brand, sorted by votes descending. Raises RuntimeError if the site
    blocked us or the brand page wasn't found."""
    # safe="" so a brand with a slash, "#" or "?" in it lands in the path
    # instead of quietly turning into a fragment or query string.
    index_url = (
        f"https://www.hifidatabase.com/Manufacturer_Index_Detailed/{quote(brand, safe='')}/"
    )
    resp = requests.get(index_url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()

    if "window.location.reload" in resp.text and "setTimeout" in resp.text:
        raise RuntimeError(
            "hifidatabase.com returned a bot-check page instead of results — "
            "try again later, or look this brand up manually."
        )

    pattern = re.compile(
        r'<div id="l\d+" class="linklisting">\s*<h4 class="linktitle">\s*'
        + re.escape(brand)
        + r'\s*<a href="([^"]+)">\s*([^<]+?)\s*</a>\s*</h4>\s*<div class="small">.*?'
        r"\((\d[\d,]*) views : (\d+) votes? :\s*(\d+) reviews?\)",
        # The brand comes from the command line, so match it case-insensitively
        # against the page: a difference in capitalisation between what you
        # typed and what the page prints would otherwise surface as the
        # misleading "could not find any models".
        re.DOTALL | re.IGNORECASE,
    )
    matches = pattern.findall(resp.text)
    if not matches:
        raise RuntimeError(
            f"Could not find any models for '{brand}' — check the spelling matches "
            "hifidatabase.com's brand list, or the site's layout may have changed."
        )

    results = [
        (name.strip(), url, int(views.replace(",", "")), int(votes), int(reviews))
        for url, name, views, votes, reviews in matches
    ]
    results.sort(key=lambda r: r[3], reverse=True)  # most-voted first
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brand", help="Brand name as hifidatabase.com spells it, e.g. 'Mission'")
    parser.add_argument(
        "--min-votes", type=int, default=0, help="Only show models with at least this many votes"
    )
    args = parser.parse_args(argv)

    try:
        models = check_brand(args.brand)
    except (requests.RequestException, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    shown = [m for m in models if m[3] >= args.min_votes]
    print(f"{len(shown)}/{len(models)} {args.brand} models (min {args.min_votes} votes):\n")
    for name, detail_url, views, votes, reviews in shown:
        print(f"  {name:<30} {votes:>3} votes  {views:>7,} views  {reviews} reviews  {detail_url}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
