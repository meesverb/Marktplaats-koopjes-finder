#!/usr/bin/env python3
"""Render reference_prices.csv (and any accumulated market price history) as
a standalone, browsable HTML page — so you can review/skim your whole
reference database without opening the CSV.

Usage:
    python reference_overview.py
    python reference_overview.py --file reference_prices.csv --output reference_overview.html
"""
from __future__ import annotations

import argparse
import html as html_lib
from pathlib import Path

from racefiets_jev import load_reference_data, load_reference_market_stats

TEMPLATE = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>Referentiedatabase overzicht</title>
<style>
  :root {{
    --bg: #f7f7f8; --card: #ffffff; --text: #1a1a1a; --muted: #6b7280;
    --border: #e5e7eb; --better: #7c3aed; --accent: #2563eb;
  }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: var(--bg);
         color: var(--text); margin: 0; padding: 24px; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 16px; }}
  input#search {{ width: 100%; max-width: 400px; padding: 8px 12px; border: 1px solid var(--border);
                 border-radius: 8px; font-size: 0.9rem; margin-bottom: 16px; box-sizing: border-box; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px;
          overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 0.88rem; }}
  th {{ cursor: pointer; user-select: none; color: var(--muted); font-weight: 600; white-space: nowrap; }}
  th:hover {{ color: var(--text); }}
  tr:last-child td {{ border-bottom: none; }}
  tr.hidden {{ display: none; }}
  code {{ font-size: 0.8rem; color: var(--muted); }}
  .badge {{ display: inline-block; font-size: 0.72rem; font-weight: 700; padding: 2px 7px;
           border-radius: 4px; color: white; background: var(--better); }}
</style>
</head>
<body>
<h1>Referentiedatabase overzicht</h1>
<div class="meta">{total} modellen · {better_count} gemarkeerd als beter dan hun referentiepunt</div>
<input id="search" type="text" placeholder="Zoek op naam...">
<table id="listings">
<thead>
<tr>
  <th data-key="label">Label</th>
  <th data-key="pattern">Patroon</th>
  <th data-key="price">Nieuwprijs</th>
  <th data-key="market">2e-hands gem.</th>
  <th data-key="specs">Specs</th>
  <th data-key="score">Score</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
<script>
  const search = document.getElementById('search');
  const rows = Array.from(document.querySelectorAll('#listings tbody tr'));
  search.addEventListener('input', () => {{
    const q = search.value.toLowerCase();
    rows.forEach(r => r.classList.toggle('hidden', !r.dataset.search.includes(q)));
  }});
  const table = document.getElementById('listings');
  const tbody = table.querySelector('tbody');
  let sortState = {{}};
  table.querySelectorAll('th[data-key]').forEach(th => {{
    th.addEventListener('click', () => {{
      const key = th.dataset.key;
      const asc = !sortState[key];
      sortState = {{ [key]: asc }};
      const rowsNow = Array.from(tbody.querySelectorAll('tr'));
      rowsNow.sort((a, b) => {{
        let av = a.dataset[key] || '', bv = b.dataset[key] || '';
        if (key === 'price' || key === 'market') {{ av = parseFloat(av) || -1; bv = parseFloat(bv) || -1; }}
        if (av < bv) return asc ? -1 : 1;
        if (av > bv) return asc ? 1 : -1;
        return 0;
      }});
      rowsNow.forEach(r => tbody.appendChild(r));
    }});
  }});
</script>
</body>
</html>
"""


def render_overview(reference: list[dict], market_stats: dict) -> str:
    rows_html = []
    for row in reference:
        label = row["label"]
        market = market_stats.get(label)
        market_str = f"€{market['mean']:.0f} (n={market['count']})" if market else "—"
        market_sort = market["mean"] if market else -1
        price_str = f"€{row['original_price_eur']:.0f}" if row["original_price_eur"] else "—"
        badge = '<span class="badge">BETER</span> ' if row["better"] else ""
        search_text = f"{label} {row['specs']} {row['score']}".lower()

        rows_html.append(
            "<tr data-label='{label_attr}' data-price='{price_sort}' data-market='{market_sort}' "
            "data-search='{search}'>"
            "<td>{badge}{label}</td>"
            "<td><code>{pattern}</code></td>"
            "<td>{price}</td>"
            "<td>{market}</td>"
            "<td>{specs}</td>"
            "<td>{score}</td>"
            "</tr>".format(
                label_attr=html_lib.escape(label, quote=True),
                price_sort=row["original_price_eur"] or -1,
                market_sort=market_sort,
                search=html_lib.escape(search_text, quote=True),
                badge=badge,
                label=html_lib.escape(label),
                pattern=html_lib.escape(row["regex"].pattern),
                price=price_str,
                market=market_str,
                specs=html_lib.escape(row["specs"]),
                score=html_lib.escape(row["score"]),
            )
        )

    return TEMPLATE.format(
        total=len(reference),
        better_count=sum(1 for r in reference if r["better"]),
        rows="\n".join(rows_html),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="reference_prices.csv", help="Path to the reference CSV")
    parser.add_argument(
        "--price-history-file", default="reference_price_history.csv",
        help="Path to the observed-price history CSV (optional, used if present)",
    )
    parser.add_argument("--output", default="reference_overview.html", help="Path to write the HTML page to")
    args = parser.parse_args(argv)

    reference = load_reference_data(args.file)
    market_stats = load_reference_market_stats(args.price_history_file)

    html = render_overview(reference, market_stats)
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"Wrote {len(reference)} models to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
