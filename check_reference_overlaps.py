#!/usr/bin/env python3
"""Sanity-check reference_prices.csv for patterns that overlap each other.

As the file grows, it's easy for a pattern to be broader than intended and
accidentally match a different row's own label — e.g. a lone "Mission"
pattern (no model number) would match every other Mission row's label too,
silently stealing matches from the more specific rows beneath it.

This checks every row's pattern against every OTHER row's label text and
reports any unexpected match. It's a heuristic (labels aren't real listing
titles), not a guarantee of full correctness, but catches the common
mistake cheaply with no network access needed.

Usage:
    python check_reference_overlaps.py
    python check_reference_overlaps.py --file reference_prices.csv
"""
from __future__ import annotations

import argparse
import sys

from racefiets_jev import load_reference_data


def find_overlaps(reference: list[dict]) -> list[tuple[str, str]]:
    """Returns (pattern_owner_label, other_row_label) pairs where a row's
    pattern matches the label of a row *below* it in the file.

    Only that direction can do damage. Matching is first-match-wins in file
    order, so an earlier, broader pattern swallows the listings meant for a
    later, more specific row. The other way around is harmless and normal:
    a broad "Mission" row at the bottom matching "Mission 731" above it
    steals nothing, because the specific row is reached first. Reporting
    those too would make a correctly ordered file fail this check."""
    problems = []
    for i, row in enumerate(reference):
        for other in reference[i + 1 :]:
            if row["regex"].search(other["label"]):
                problems.append((row["label"], other["label"]))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="reference_prices.csv", help="Path to the reference CSV")
    args = parser.parse_args(argv)

    reference = load_reference_data(args.file)
    if not reference:
        print(f"error: no rows loaded from {args.file}", file=sys.stderr)
        return 1

    problems = find_overlaps(reference)
    print(f"Checked {len(reference)} rows in {args.file}.")

    if not problems:
        print("No overlaps found — every pattern only matches its own label.")
        return 0

    print(f"\n{len(problems)} potential overlap(s) found:\n")
    for owner_label, other_label in problems:
        print(f"  Pattern for {owner_label!r} also matches {other_label!r}")
    print(
        "\nThe first row comes before the second in the file, so a listing meant for "
        "the second model gets matched to the first one instead (first match wins). "
        "Make the first row's pattern more specific, or move the specific row above it."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
