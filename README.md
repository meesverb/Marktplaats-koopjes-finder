# Marktplaats koopjes finder

`racefiets_jev.py` searches [Marktplaats](https://www.marktplaats.nl) for
road bike ("racefiets") listings and flags ones priced well below the
median of what it found — a quick way to spot bargains.

## Usage

```bash
pip install -r requirements.txt
python racefiets_jev.py --pages 10
```

Listings marked with `*` are priced at or below `--bargain-ratio` (default
`0.6`, i.e. 60%) of the median price across all listings fetched.

Every run also writes `racefiets_report.html` — open it in a browser for a
sortable, filterable overview (Nieuw / Koopjes) with clickable links to each
listing. It compares against `seen_listings.json` (created automatically) so
listings you've already seen in a previous run are marked accordingly instead
of showing up as "new" every time — handy if you run this script on a
schedule (e.g. every 15 minutes via cron / Task Scheduler).

### Options

| Flag | Description | Default |
| --- | --- | --- |
| `--query` | Search query | `racefiets` |
| `--pages` | Number of result pages to fetch (30 listings/page) | `1` |
| `--min-price` / `--max-price` | Filter by price in EUR | none |
| `--bargain-ratio` | Fraction of the median price at/below which a listing is flagged | `0.6` |
| `--delay` | Seconds between page requests | `1.5` |
| `--output` | Write results to a CSV file | none |
| `--html` | Path to write the HTML overview to | `racefiets_report.html` |
| `--no-html` | Skip writing the HTML overview | off |
| `--history-file` | Path to the file that remembers which listings were already seen | `seen_listings.json` |

## Notes

This scrapes Marktplaats' public search result pages directly (no API key
or third-party service required). Marktplaats may change its page
structure at any time, which can break parsing — the script prints a
clear error if that happens rather than failing silently.
