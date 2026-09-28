"""Het dashboard: één pagina voor alles wat er op Marktplaats aan
fietscomputers te koop staat, in plaats van een rapport per zoekterm.

    python dashboard.py                 # schrijft dashboard.html uit koopjes.db
    python dashboard.py --open          # en opent hem

Gebouwd uit de database, niet uit één run: de zoekopdracht "fietscomputer"
in schedule.json zoekt op 17 merken, en elk merk leverde een eigen rapport op
(racefiets_report_garmin-edge.html, ..._wahoo-roam.html, ...). Die hingen niet
aan elkaar, en een flip-schatting per rapport zag alleen de advertenties van
dat ene merk. Hier staat alles bij elkaar, met de vergelijkingsprijzen over
alle zoektermen en eerdere rondes heen.

Tabs: Flips (wat je per advertentie verdient), Upgrades (t.o.v. de eigen
computer), Alle computers, Marktprijzen per model, en Uitgefilterd (houders,
hoesjes, onderdelen, defecte en gezochte — om na te kijken dat er geen echte
computer tussen zit). De rekenregels staan in computers.py en
computer_scoring.json; dit bestand toont alleen.

Leest alleen uit de database, schrijft er niets in.
"""
from __future__ import annotations

import argparse
import html
import sqlite3
import statistics
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import computers as pc
import racefiets_jev as mp

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = "dashboard.html"
COMPUTER_CATEGORY = "fietsaccessoires-fietscomputers"

esc = html.escape


@dataclass
class Unknown:
    """Een advertentie zonder bekend model: een computer met onbekend model,
    of iets dat is uitgefilterd."""
    listing: mp.Listing
    kind: str
    reason: str


@dataclass
class Dashboard:
    listings: list  # alle actieve advertenties in de categorie
    unknown: list = field(default_factory=list)  # Unknown
    newest_seen: str = ""
    new_ids: set = field(default_factory=set)
    config: dict = field(default_factory=dict)

    @property
    def computers(self) -> list:
        return pc.active_computers(self.listings)

    @property
    def unknown_computers(self) -> list:
        return [u for u in self.unknown if u.kind == "computer"]

    @property
    def excluded(self) -> list:
        """(listing, soort, reden) voor alles wat geen computer is."""
        rows = [(l, l.computer.kind, l.computer.reason) for l in pc.filtered_out(self.listings)]
        rows += [(u.listing, u.kind, u.reason) for u in self.unknown if u.kind != "computer"]
        return sorted(rows, key=lambda r: (r[1], r[0].title.lower()))

    @property
    def flips(self) -> list:
        return [l for l in pc.flips(self.listings) if l.computer.profit_eur > 0]

    @property
    def open_bids(self) -> list:
        return pc.open_bids(self.listings)

    @property
    def upgrades(self) -> list:
        return pc.upgrades(self.listings)


# --- Uit de database ---------------------------------------------------------


def _parse_time(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def load_dashboard(db_path, config: Optional[dict] = None) -> Dashboard:
    """De actieve advertenties in de categorie fietscomputers: niet verdwenen
    en gezien binnen `active_days` van de nieuwste waarneming. Relatief aan de
    nieuwste en niet aan nu, zodat een dashboard na een week zonder rondes
    niet leeg is maar de stand van de laatste ronde laat zien."""
    config = config or pc.default_config()
    settings = config["dashboard"]
    if not Path(db_path).exists():
        return Dashboard([], config=config)
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(listing)")}
        images = "image_urls" if "image_urls" in columns else "'' AS image_urls"
        asking = "price_is_asking" if "price_is_asking" in columns else "NULL AS price_is_asking"
        rows = conn.execute(
            f"SELECT item_id, title, description, price_eur, price_type, is_bid, {asking}, "
            f"city, posted_date, condition, url, first_seen, last_seen, {images} "
            "FROM listing WHERE disappeared_at IS NULL AND url LIKE ?",
            (f"%/{COMPUTER_CATEGORY}/%",),
        ).fetchall()
    finally:
        conn.close()

    seen = [t for t in (_parse_time(r["last_seen"]) for r in rows) if t]
    if not seen:
        return Dashboard([], config=config)
    newest = max(seen)
    active_since = newest - timedelta(days=settings["active_days"])
    new_since = newest - timedelta(hours=settings["new_hours"])

    listings, new_ids = [], set()
    for r in rows:
        last = _parse_time(r["last_seen"])
        if last is None or last < active_since:
            continue
        listing = mp.Listing(
            item_id=r["item_id"],
            title=r["title"] or "",
            description=r["description"] or "",
            price_eur=r["price_eur"],
            price_type=r["price_type"] or "",
            city=r["city"] or "",
            date=r["posted_date"] or "",
            condition=r["condition"] or "",
            frame_height="",
            groupset="",
            groupset_tier=None,
            url=r["url"] or "",
            price_is_bid=bool(r["is_bid"]),
            first_seen=r["first_seen"] or "",
            image_urls=r["image_urls"] or "",
        )
        # Het bod zelf staat niet in de database; price_is_asking = 0 zegt
        # wel dat de prijs een lopend bod is (db.py, migratie 3). Eén bod is
        # genoeg om Listing.price_is_asking hetzelfde te laten zeggen.
        if r["is_bid"] and r["price_is_asking"] == 0:
            listing.bid_count = 1
        first = _parse_time(r["first_seen"])
        if first and first >= new_since:
            new_ids.add(listing.item_id)
        listings.append(listing)
    if len(new_ids) == len(listings):
        # De allereerste ronde: alles is "nieuw", en dan zegt het label niets.
        new_ids = set()

    pc.apply_computer_signals(listings, db_path=db_path, config=config)
    unknown = [
        Unknown(l, *pc.classify_unknown(l.title))
        for l in listings
        if l.computer is None
    ]
    return Dashboard(listings, unknown, newest.isoformat(timespec="minutes"), new_ids, config)


# --- HTML ---------------------------------------------------------------------


def euro(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    text = f"€{abs(amount):,.0f}".replace(",", ".")
    return f"−{text}" if amount < 0 else text


def band(low: Optional[float], high: Optional[float]) -> str:
    if low is None or high is None:
        return ""
    if round(low) == round(high):
        return f"weinig spreiding ({euro(low)})"
    return f"{euro(low)} tot {euro(high)}"


def signed_euro(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    return ("+" if amount >= 0 else "") + euro(amount)


def local_time(iso: str) -> str:
    moment = _parse_time(iso)
    if moment is None:
        return iso or "?"
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%d-%m-%Y %H:%M")


def thumb(listing) -> str:
    url = (listing.image_urls or "").split()
    if not url:
        return "<div class='thumb empty' aria-hidden='true'></div>"
    return (f"<a href='{esc(listing.url, quote=True)}' target='_blank' rel='noopener'>"
            f"<img class='thumb' src='{esc(url[0], quote=True)}' alt='' loading='lazy'></a>")


def listing_cell(listing, d: Dashboard, model_label: str, note: str = "") -> str:
    new = "<span class='badge'>nieuw</span> " if listing.item_id in d.new_ids else ""
    place = f" · {esc(listing.city)}" if listing.city else ""
    note_html = f"<div class='note'>{esc(note)}</div>" if note else ""
    return (
        f"<td class='what'><div class='model'>{new}{esc(model_label)}</div>"
        f"<a href='{esc(listing.url, quote=True)}' target='_blank' rel='noopener'>{esc(listing.title)}</a>"
        f"<span class='muted'>{place}</span>{note_html}</td>"
    )


def price_cell(listing) -> str:
    kind = pc.price_kind(listing)
    return (f"<td class='num' data-sort='{listing.price_eur if listing.price_eur is not None else ''}'>"
            f"{euro(listing.price_eur)}<div class='sub'>{esc(kind)}</div></td>")


def tiles(items: list[tuple[str, str, str]]) -> str:
    """Een rij stat-tegels: (label, waarde, toelichting)."""
    return "<div class='tiles'>" + "".join(
        f"<div class='tile'><div class='label'>{esc(label)}</div><div class='value'>{value}</div>"
        f"<div class='sub'>{esc(sub)}</div></div>"
        for label, value, sub in items
    ) + "</div>"


def table(head: list[tuple[str, str]], rows: list[str], table_id: str = "") -> str:
    """head: (kop, 'num'|'text'|'') — alleen kolommen met een soort zijn sorteerbaar."""
    ths = "".join(
        f"<th{' class=num' if kind == 'num' else ''}"
        f"{f' data-type={kind}' if kind else ''}>{esc(title)}</th>"
        for title, kind in head
    )
    ident = f" id='{table_id}'" if table_id else ""
    return (f"<div class='table-wrap'><table class='sortable'{ident}><thead><tr>{ths}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def flips_panel(d: Dashboard) -> str:
    flip = d.config["flip"]
    flips = d.flips
    best = flips[0] if flips else None
    parts = [tiles([
        ("Flips met winst", str(len(flips)), "advertenties onder de verwachte verkoopprijs"),
        ("Beste flip", signed_euro(best.computer.profit_eur) if best else "—",
         best.computer.model.label if best else "nog niets"),
        ("Samen", euro(sum(l.computer.profit_eur for l in flips)) if flips else "—",
         "als je ze allemaal koopt en verkoopt"),
        ("Zonder prijs", str(len(d.open_bids)), "met een maximaal bod"),
    ])]
    parts.append(
        "<p class='explain'><strong>Winst</strong> = verwachte verkoopprijs − prijs − kosten "
        f"({euro(flip.get('costs_eur', 0))} per flip, instelbaar in <code>computer_scoring.json</code>). "
        "De verkoopprijs is de mediaan van wat andere advertenties voor hetzelfde model vragen "
        f"(nu en de laatste {flip['comp_window_days']} dagen, verkochte meegeteld), "
        f"× {str(flip['negotiation_factor']).replace('.', ',')} voor afdingen. De band eronder is de winst "
        "bij het goedkoopste en duurste kwart van die advertenties. Bij <em>huidig bod</em> loopt de prijs "
        "nog op; bij <em>vraagprijs, bieden kan</em> kun je vaak lager uitkomen.</p>"
    )
    if flips:
        rows = []
        for l in flips:
            c = l.computer
            rows.append(
                "<tr>"
                f"<td class='pic'>{thumb(l)}</td>"
                f"<td class='num profit' data-sort='{c.profit_eur}'>"
                f"<span class='gain' aria-hidden='true'>▲</span>{signed_euro(c.profit_eur)}"
                f"<div class='sub'>{band(c.profit_low_eur, c.profit_high_eur)}</div></td>"
                f"{price_cell(l)}"
                f"<td class='num' data-sort='{c.resale_eur}'>{euro(c.resale_eur)}"
                f"<div class='sub'>n={c.comp_count} vergelijkbaar</div></td>"
                f"{listing_cell(l, d, c.model.label, c.reason)}"
                "</tr>"
            )
        parts.append(table([("", ""), ("Winst", "num"), ("Inkoop", "num"), ("Verkoop", "num"),
                            ("Advertentie", "text")], rows))
    else:
        parts.append("<p class='empty'>Geen computer die onder de verwachte verkoopprijs staat.</p>")

    if d.open_bids:
        parts.append("<h3>Zonder prijs — bied maximaal</h3>"
                     "<p class='explain'>Bieden zonder minimum of geen prijs genoemd. Het maximale bod is de "
                     "lage verkoopschatting min kosten: daarboven speel je bij een tegenvaller verlies.</p>")
        rows = [
            "<tr>"
            f"<td class='pic'>{thumb(l)}</td>"
            f"<td class='num' data-sort='{l.computer.max_bid_eur}'><strong>{euro(l.computer.max_bid_eur)}</strong>"
            f"<div class='sub'>verkoop ±{euro(l.computer.resale_eur)}, n={l.computer.comp_count}</div></td>"
            f"<td class='num'>{esc(pc.price_kind(l))}</td>"
            f"{listing_cell(l, d, l.computer.model.label, l.computer.reason)}"
            "</tr>"
            for l in d.open_bids
        ]
        parts.append(table([("", ""), ("Bied max.", "num"), ("Prijs", ""), ("Advertentie", "text")], rows))
    return "\n".join(parts)


def upgrades_panel(d: Dashboard) -> str:
    base = pc.baseline_model(config=d.config)
    ups = d.upgrades
    own = ups[0].computer.own_resale_eur if ups else None
    nets = [l.computer.net_upgrade_cost_eur for l in ups if l.computer.net_upgrade_cost_eur is not None]
    base_label = base.label if base else "eigen computer"
    parts = [tiles([
        ("Upgrades te koop", str(len(ups)), f"kunnen meer dan je {base_label}"),
        (f"Je {base.model if base else 'computer'} levert op", euro(own) if own is not None else "—",
         "verwachte verkoopprijs" if own is not None else "te weinig vergelijkbare advertenties"),
        ("Goedkoopste, netto", euro(min(nets)) if nets else "—",
         "prijs min wat je eigen computer oplevert (negatief: je houdt geld over)"),
    ])]
    parts.append(
        "<p class='explain'><strong>+punten</strong> = functiescore min die van je eigen computer "
        f"({esc(base_label)}). Rerouting, plannen op het apparaat en training wegen het zwaarst, knoppen "
        "gaan voor touch, geen updates kost punten (<code>python computers.py</code> toont de score per model). "
        "<strong>Netto</strong> = prijs min wat je eigen computer oplevert als je hem verkoopt.</p>"
    )
    if not ups:
        parts.append("<p class='empty'>Geen herkende computer die meer kan dan je eigen.</p>")
        return "\n".join(parts)
    rows = []
    for l in ups:
        c = l.computer
        gains, losses = pc.feature_changes(c.model, base, d.config)
        changes = "".join(f"<li class='plus'>{esc(g)}</li>" for g in gains)
        changes += "".join(f"<li class='minus'>{esc(x)}</li>" for x in losses)
        unknown = f"<div class='sub'>{len(c.features.unknown)} velden onbekend</div>" if c.features.unknown else ""
        rows.append(
            "<tr>"
            f"<td class='pic'>{thumb(l)}</td>"
            f"<td class='num' data-sort='{c.upgrade_delta}'><strong>+{c.upgrade_delta:.0f}</strong>"
            f"<div class='sub'>score {c.features.score:.0f}</div>{unknown}</td>"
            f"{price_cell(l)}"
            f"<td class='num' data-sort='{c.net_upgrade_cost_eur if c.net_upgrade_cost_eur is not None else ''}'>"
            f"{euro(c.net_upgrade_cost_eur)}</td>"
            f"<td><ul class='changes'>{changes or '<li>zelfde functies, beter bekend</li>'}</ul></td>"
            f"{listing_cell(l, d, c.model.label, c.reason)}"
            "</tr>"
        )
    parts.append(table([("", ""), ("+punten", "num"), ("Prijs", "num"), ("Netto", "num"),
                        ("Wat je erbij krijgt / inlevert", ""), ("Advertentie", "text")], rows))
    return "\n".join(parts)


def all_panel(d: Dashboard) -> str:
    items = [(l, l.computer.model.label, l.computer) for l in d.computers]
    items += [(u.listing, "model onbekend", None) for u in d.unknown_computers]
    brands = sorted({label.split(" ")[0] for _, label, c in items if c is not None})
    options = "".join(f"<option value='{esc(b)}'>{esc(b)}</option>" for b in brands)
    parts = [
        "<div class='filters'>"
        "<input type='search' id='all-search' placeholder='Zoek in titel of model' aria-label='Zoeken'>"
        f"<select id='all-brand' aria-label='Merk'><option value=''>Alle merken</option>{options}"
        "<option value='model onbekend'>Model onbekend</option></select>"
        "<label><input type='checkbox' id='all-new'> alleen nieuw</label>"
        "<span class='muted' id='all-count'></span></div>"
    ]
    rows = []
    for l, label, c in sorted(items, key=lambda i: (i[1] == "model onbekend", i[1], i[0].price_eur or 0)):
        brand = label.split(" ")[0] if c is not None else "model onbekend"
        profit = c.profit_eur if c else None
        delta = c.upgrade_delta if c else None
        score = c.features.score if c else None
        note = c.reason if c else next(u.reason for u in d.unknown if u.listing is l)
        rows.append(
            f"<tr data-brand='{esc(brand, quote=True)}' data-new='{int(l.item_id in d.new_ids)}' "
            f"data-text='{esc((label + ' ' + l.title).lower(), quote=True)}'>"
            f"<td class='pic'>{thumb(l)}</td>"
            f"{price_cell(l)}"
            f"<td class='num' data-sort='{profit if profit is not None else ''}'>{signed_euro(profit)}</td>"
            f"<td class='num' data-sort='{delta if delta is not None else ''}'>"
            f"{'—' if delta is None else f'{delta:+.0f}'}</td>"
            f"<td class='num' data-sort='{score if score is not None else ''}'>{'—' if score is None else f'{score:.0f}'}</td>"
            f"{listing_cell(l, d, label, note)}"
            "</tr>"
        )
    parts.append(table([("", ""), ("Prijs", "num"), ("Winst", "num"), ("Upgrade", "num"),
                        ("Score", "num"), ("Advertentie", "text")], rows, "all-table"))
    return "\n".join(parts)


def market_panel(d: Dashboard) -> str:
    factor = d.config["flip"]["negotiation_factor"]
    by_model: dict[str, list] = {}
    for l in d.computers:
        by_model.setdefault(l.computer.model.label, []).append(l)
    rows = []
    for label, items in sorted(by_model.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        model = items[0].computer.model
        asking = [l.price_eur for l in items if l.price_is_asking and l.price_eur is not None]
        median = statistics.median(asking) if asking else None
        resale = items[0].computer.resale_eur
        new_price = model.number("nieuwprijs_eur")
        rows.append(
            "<tr>"
            f"<td class='what'><div class='model'>{esc(label)}</div>"
            f"<span class='muted'>{esc(model.get('introductiejaar') or '')}</span></td>"
            f"<td class='num' data-sort='{len(items)}'>{len(items)}</td>"
            f"<td class='num' data-sort='{min(asking) if asking else ''}'>{euro(min(asking) if asking else None)}</td>"
            f"<td class='num' data-sort='{median if median is not None else ''}'>{euro(median)}</td>"
            f"<td class='num' data-sort='{resale if resale is not None else ''}'>"
            f"{euro(resale) if resale is not None else euro(median * factor) if median else '—'}</td>"
            f"<td class='num' data-sort='{new_price if new_price else ''}'>{euro(new_price)}</td>"
            f"<td class='num' data-sort='{items[0].computer.features.score}'>{items[0].computer.features.score:.0f}</td>"
            "</tr>"
        )
    intro = ("<p class='explain'>Per model wat er nu te koop staat. <strong>Verwacht verkoop</strong> is de "
             f"mediaan-vraagprijs × {str(factor).replace('.', ',')}, over alle advertenties van de laatste "
             f"{d.config['flip']['comp_window_days']} dagen (ook verkochte). Nieuwprijs alleen waar een bron "
             "hem gaf (<code>reference_bike_computers.csv</code>).</p>")
    return intro + table([("Model", "text"), ("Te koop", "num"), ("Laagste", "num"), ("Mediaan vraag", "num"),
                          ("Verwacht verkoop", "num"), ("Nieuwprijs", "num"), ("Score", "num")], rows)


def excluded_panel(d: Dashboard) -> str:
    rows_data = d.excluded
    counts: dict[str, int] = {}
    for _, kind, _ in rows_data:
        counts[kind] = counts.get(kind, 0) + 1
    summary = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    parts = [
        "<p class='explain'>Wat níet als computer meetelt, met de reden — om na te kijken dat er geen "
        "echte computer tussen zit. Houders en hoesjes herkent het filter aan hun plek in de titel: "
        "<em>vóór</em> de modelnaam (\"Hoesje voor Garmin 1000\") is een accessoire, <em>erna met</em> "
        "\"met\"/\"incl.\"/\"+\" (\"Edge 530 + stuurmount\") een computer met extra's. Staat het "
        "woord er direct achter (\"Karoo 3 houder nieuw\"), dan beslist de prijs t.o.v. hetzelfde model. "
        f"Nu: {esc(summary) or 'niets'}.</p>"
    ]
    rows = [
        "<tr>"
        f"<td class='pic'>{thumb(l)}</td>"
        f"<td>{esc(kind)}</td>"
        f"<td class='num' data-sort='{l.price_eur if l.price_eur is not None else ''}'>{euro(l.price_eur)}</td>"
        f"<td class='what'><a href='{esc(l.url, quote=True)}' target='_blank' rel='noopener'>{esc(l.title)}</a>"
        f"<div class='note'>{esc(reason)}</div></td>"
        "</tr>"
        for l, kind, reason in rows_data
    ]
    parts.append(table([("", ""), ("Soort", "text"), ("Prijs", "num"), ("Advertentie en reden", "text")], rows))
    return "\n".join(parts)


CSS = """
:root { color-scheme: light; --surface: #fcfcfb; --card: #ffffff; --line: #e4e3df;
  --text: #0b0b0b; --text-2: #52514e; --muted: #6b6a66; --accent: #2a78d6; --good: #0ca30c;
  --bad: #d03b3b; --badge: #e8f0fb; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --surface: #1a1a19; --card: #222221;
  --line: #3a3a38; --text: #ffffff; --text-2: #c3c2b7; --muted: #a3a29a; --accent: #3987e5;
  --good: #0ca30c; --bad: #e06666; --badge: #23344a; } }
* { box-sizing: border-box; }
body { margin: 0; padding: 20px 16px 48px; background: var(--surface); color: var(--text);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
h3 { font-size: 1.05rem; margin: 28px 0 6px; }
a { color: var(--accent); }
.meta, .muted, .sub, .note { color: var(--muted); }
.meta { font-size: .9rem; margin-bottom: 14px; }
.sub { font-size: .78rem; margin-top: 2px; }
.note { font-size: .78rem; margin-top: 3px; }
nav.tabs { display: flex; gap: 4px; flex-wrap: wrap; border-bottom: 1px solid var(--line); margin-bottom: 16px; }
nav.tabs button { background: none; border: 0; border-bottom: 3px solid transparent; color: var(--text-2);
  font: inherit; padding: 8px 12px; cursor: pointer; }
nav.tabs button.active { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
.panel[hidden] { display: none; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 4px 0 14px; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.tile .label { font-size: .85rem; color: var(--text-2); }
.tile .value { font-size: 1.7rem; font-weight: 600; margin-top: 2px; }
.explain { color: var(--text-2); font-size: .88rem; max-width: 90ch; }
.table-wrap { overflow-x: auto; background: var(--card); border: 1px solid var(--line); border-radius: 10px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; }
tbody tr:last-child td { border-bottom: 0; }
th { font-size: .82rem; color: var(--text-2); font-weight: 600; white-space: nowrap; }
th[data-type] { cursor: pointer; }
th[data-type]::after { content: " ↕"; color: var(--muted); font-weight: 400; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.profit { font-size: 1.15rem; font-weight: 600; }
.gain { color: var(--good); font-size: .75rem; margin-right: 4px; }
td.pic { width: 76px; padding-right: 0; }
img.thumb, .thumb.empty { width: 64px; height: 64px; object-fit: cover; border-radius: 6px; display: block;
  background: var(--line); }
td.what { min-width: 260px; }
.model { font-weight: 600; }
.badge { display: inline-block; font-size: .7rem; font-weight: 700; padding: 1px 6px; border-radius: 8px;
  background: var(--badge); color: var(--text); vertical-align: 1px; }
ul.changes { margin: 0; padding: 0; list-style: none; font-size: .82rem; }
ul.changes li::before { display: inline-block; width: 1.1em; font-weight: 700; }
ul.changes li.plus::before { content: "+"; color: var(--good); }
ul.changes li.minus::before { content: "−"; color: var(--bad); }
.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 10px; }
.filters input[type=search], .filters select { font: inherit; padding: 6px 8px; border: 1px solid var(--line);
  border-radius: 6px; background: var(--card); color: var(--text); }
.filters input[type=search] { min-width: 240px; }
tr.hidden { display: none; }
.empty { color: var(--muted); padding: 12px 0; }
code { font-size: .85em; }
"""

JS = """
const buttons = document.querySelectorAll('nav.tabs button');
function show(name) {
  const target = document.getElementById('panel-' + name);
  if (!target) return;
  document.querySelectorAll('.panel').forEach(p => p.hidden = p !== target);
  buttons.forEach(b => b.classList.toggle('active', b.dataset.panel === name));
}
buttons.forEach(b => b.addEventListener('click', () => {
  show(b.dataset.panel); history.replaceState(null, '', '#' + b.dataset.panel);
}));
if (location.hash) show(location.hash.slice(1));
window.addEventListener('hashchange', () => show(location.hash.slice(1)));

document.querySelectorAll('table.sortable').forEach(table => {
  const tbody = table.querySelector('tbody');
  table.querySelectorAll('th[data-type]').forEach((th, index) => {
    let asc = th.dataset.type !== 'num';
    th.addEventListener('click', () => {
      const col = Array.from(th.parentNode.children).indexOf(th);
      const rows = Array.from(tbody.rows);
      const key = r => {
        const cell = r.cells[col];
        if (th.dataset.type === 'num') {
          const v = parseFloat(cell.dataset.sort);
          return Number.isNaN(v) ? null : v;
        }
        return cell.textContent.trim().toLowerCase();
      };
      rows.sort((a, b) => {
        const x = key(a), y = key(b);
        if (x === null) return 1;
        if (y === null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
      });
      rows.forEach(r => tbody.appendChild(r));
      asc = !asc;
    });
  });
});

const search = document.getElementById('all-search');
const brand = document.getElementById('all-brand');
const onlyNew = document.getElementById('all-new');
const count = document.getElementById('all-count');
function filterAll() {
  const q = search.value.trim().toLowerCase();
  let shown = 0;
  document.querySelectorAll('#all-table tbody tr').forEach(r => {
    const ok = (!q || r.dataset.text.includes(q)) && (!brand.value || r.dataset.brand === brand.value)
      && (!onlyNew.checked || r.dataset.new === '1');
    r.classList.toggle('hidden', !ok);
    if (ok) shown++;
  });
  count.textContent = shown + ' getoond';
}
if (search) { [search, brand, onlyNew].forEach(el => el.addEventListener('input', filterAll)); filterAll(); }
"""


def render(d: Dashboard, overview_link: Optional[str] = None) -> str:
    computers = len(d.computers) + len(d.unknown_computers)
    tabs = [
        ("flips", f"Flips ({len(d.flips)})", flips_panel(d)),
        ("upgrades", f"Upgrades ({len(d.upgrades)})", upgrades_panel(d)),
        ("alle", f"Alle computers ({computers})", all_panel(d)),
        ("markt", "Marktprijzen", market_panel(d)),
        ("uitgefilterd", f"Uitgefilterd ({len(d.excluded)})", excluded_panel(d)),
    ]
    nav = "".join(
        f"<button data-panel='{name}'{' class=active' if i == 0 else ''}>{esc(label)}</button>"
        for i, (name, label, _) in enumerate(tabs)
    )
    panels = "".join(
        f"<section class='panel' id='panel-{name}'{'' if i == 0 else ' hidden'}>{body}</section>"
        for i, (name, _, body) in enumerate(tabs)
    )
    if not d.listings:
        panels = ("<p class='empty'>Nog geen fietscomputers in de database. Draai eerst een ronde: "
                  "<code>python koopjes.py run nacht</code>.</p>")
        nav = ""
    link = f" · <a href='{esc(overview_link, quote=True)}'>racefietsen: overzicht</a>" if overview_link else ""
    new = f" ({len(d.new_ids)} nieuw)" if d.new_ids else ""
    meta = (f"Bijgewerkt {datetime.now().strftime('%d-%m-%Y %H:%M')} · {computers} computers te koop{new} "
            f"· laatste ronde {local_time(d.newest_seen)}{link}")
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Fietscomputers</title><style>{CSS}</style></head><body><main>"
        "<h1>Fietscomputers op Marktplaats</h1>"
        f"<div class='meta'>{meta}</div>"
        f"<nav class='tabs'>{nav}</nav>{panels}"
        f"</main><script>{JS}</script></body></html>"
    )


def write_dashboard(db_path, out_path, overview_link: Optional[str] = None) -> Dashboard:
    d = load_dashboard(db_path)
    Path(out_path).write_text(render(d, overview_link), encoding="utf-8")
    return d


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bouw dashboard.html met alle fietscomputers uit koopjes.db.")
    parser.add_argument("--db", default="koopjes.db")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--open", action="store_true", help="open het dashboard in de browser")
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print(f"Database {args.db} bestaat niet. Draai eerst een ronde: python koopjes.py run nacht",
              file=sys.stderr)
        return 1
    overview = "overzicht.html" if (Path(args.out).resolve().parent / "overzicht.html").exists() else None
    d = write_dashboard(args.db, args.out, overview)
    print(f"Dashboard: {args.out} — {len(d.computers) + len(d.unknown_computers)} computers, "
          f"{len(d.flips)} flips, {len(d.upgrades)} upgrades, {len(d.excluded)} uitgefilterd")
    if args.open:
        webbrowser.open(Path(args.out).resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
