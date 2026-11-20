"""De startpagina `/start` van `dashboard.py --serve` en `/bestanden/`: één
adres om te openen. De server toont de live pagina's én de bestanden die de
rondes schrijven (overzicht, rapporten, lijsten — alleen die patronen:
SERVED_FILES), met de laatste rondes, de knoppen om er een te starten
(launcher.py), je flips en je lopende biedingen.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import flips as fl
import koopjes
import launcher
import markets as mk
import own_bids as ob
import pages as pg
import racebikes as rb
from util import euro, local_time


# Wat /bestanden/ laat zien: alleen wat de rondes voor jou schrijven, nooit
# de database, sheets.json of de broncode. Een pad met een map erin moet in
# een van deze mappen liggen.
SERVED_FILES = ("overzicht.html", "racefiets_report*.html", "lijsten/*.txt", "taxatie_*.md", "logs/koopjes.log")


# De geschreven dashboards zijn een momentopname; het overzicht linkt ernaar,
# en dan wil je de live versie.
LIVE_INSTEAD = {"dashboard.html": "/", **{m.dashboard_file: m.serve_path for m in mk.MARKETS.values()}}


FILE_TYPES = {".html": "text/html; charset=utf-8", ".txt": "text/plain; charset=utf-8",
              ".md": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8"}


def served_file(files_dir, name: str) -> Optional[Path]:
    """Het bestand bij /bestanden/<name>, of None als het niet mag of er niet is."""
    from fnmatch import fnmatch

    if not name or "\\" in name or name.startswith("/") or ".." in name.split("/"):
        return None
    if not any(fnmatch(name, pattern) and name.count("/") == pattern.count("/") for pattern in SERVED_FILES):
        return None
    base = Path(files_dir).resolve()
    path = (base / name).resolve()
    if base not in path.parents or not path.is_file():
        return None
    return path


def with_file_nav(data: bytes) -> bytes:
    """Een rapport of het overzicht heeft een eigen opmaak zonder de balk van
    de server; hier komt een smalle balk bovenaan, met eigen stijl zodat
    die van het rapport hem niet raakt. Het bestand op schijf blijft zoals het
    is (dat opent ook zonder server)."""
    links = " · ".join(f"<a href='{pg.esc(href, quote=True)}' style='color:inherit'>{pg.esc(label)}</a>"
                       for label, href in pg.site_pages())
    bar = (f"<div style='font:14px/1.6 system-ui,sans-serif;padding:6px 16px;background:#2a78d6;color:#fff'>"
           f"{links}</div>").encode("utf-8")
    at = data.lower().find(b"<body")
    if at < 0:
        return bar + data
    end = data.find(b">", at)
    return data[:end + 1] + bar + data[end + 1:]


def list_files(files_dir) -> list:
    """(naam, gewijzigd) van alles onder /bestanden, nieuwste eerst."""
    base = Path(files_dir)
    found = []
    for pattern in SERVED_FILES:
        for path in base.glob(pattern):
            if path.is_file():
                found.append((path.relative_to(base).as_posix(), path.stat().st_mtime))
    return sorted(found, key=lambda f: -f[1])


def _file_label(name: str) -> str:
    if name == "overzicht.html":
        return "Overzicht van alle zoekopdrachten"
    if name.startswith("racefiets_report"):
        rest = name[len("racefiets_report"):-len(".html")].lstrip("_")
        return f"Rapport: {rest.replace('-', ' ')}" if rest else "Rapport"
    if name.startswith("lijsten/"):
        return "Lijst: " + name[len("lijsten/"):-len(".txt")].replace("_", " ")
    if name.startswith("taxatie_"):
        return "Taxatie " + name[len("taxatie_"):-len(".md")]
    if name == "logs/koopjes.log":
        return "Logboek van de rondes"
    return name


def load_recent_rounds(files_dir, limit: int = 5) -> list:

    try:
        config = koopjes.load_config(Path(files_dir) / "schedule.json")
        path = config.base_dir / config.rounds_file
    except Exception:  # geen of een kapotte schedule.json: dan het standaardpad
        path = Path(files_dir) / "logs" / "rondes.jsonl"
    return koopjes.load_rounds(path, limit=limit)


def load_schedule(files_dir):
    """schedule.json naast de rapporten, of None (dan geen knoppen)."""

    try:
        return koopjes.load_config(Path(files_dir) / "schedule.json")
    except Exception:  # ontbreekt of kapot: de pagina werkt dan zonder knoppen
        return None


def rounds_panel(files_dir, running: str = "") -> str:
    """Per tijdslot een knop starten, met wat hij doet en wanneer hij het
    laatst draaide. `running`: het slot dat de server net startte, of
    "ja" als een andere ronde (de taakplanner) bezig is."""

    config = load_schedule(files_dir)
    if config is None:
        return "<p class='empty'>Geen schedule.json gevonden; zonder die zijn er geen rondes om te starten.</p>"
    rows = []
    for info in launcher.slots(config):
        last = info.last
        when = (f"{pg.esc(local_time(last.get('started_at', '')))}"
                f"<div class='sub'>{pg.esc(str(last.get('status', '?')))}, {int(last.get('new', 0) or 0)} nieuw</div>"
                if last else "<span class='muted'>nog nooit</span>")
        depth = "alles" if info.full else f"{info.pages} pagina's"
        if running:
            button = "<span class='muted'>er draait een ronde</span>"
        elif info.ready_at is not None:
            button = (f"<span class='muted'>weer vanaf {pg.esc(info.ready_at.astimezone().strftime('%H:%M'))}</span>")
        else:
            warn = (" data-confirm='Deze ronde haalt alles op en duurt lang (vaak meer dan een uur). Starten?'"
                    if info.full else "")
            button = pg.act("/start/ronde", info.name, f"<button name='doe' value='start'{warn}>starten</button>")
        rows.append(
            f"<tr><td><div class='model'>{pg.esc(info.name)}</div><div class='sub'>{pg.esc(info.times)}</div></td>"
            f"<td>{pg.esc(', '.join(info.searches))}<div class='sub'>{pg.esc(depth)}</div></td>"
            f"<td>{when}</td><td>{button}</td></tr>")
    table_html = ("<div class='table-wrap'><table><thead><tr><th>Ronde</th><th>Zoekt</th><th>Laatst</th><th></th>"
                  f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")
    status = ""
    if running:
        tail = launcher.log_tail(config)
        label = f"Ronde '{running}' draait" if running != "ja" else "Er draait een ronde"
        status = (f"<div class='banner' id='round-running' role='status'><strong>{pg.esc(label)}.</strong> "
                  "Deze pagina ververst vanzelf als hij klaar is. Je kunt intussen gewoon verder op de andere "
                  f"pagina's.</div><pre class='log' id='round-log'>{pg.esc(tail)}</pre>")
    explain = ("<p class='explain'>Zelfde als de taakplanner: <code>python koopjes.py run &lt;ronde&gt;</code>, op de "
               "achtergrond. Nooit twee tegelijk, en per ronde een wachttijd sinds de vorige (een half uur, zes uur "
               "voor een ronde die alles ophaalt), zodat Marktplaats niet vaker bevraagd wordt dan nodig. Hij "
               "loopt door als je de server stopt.</p>")
    return status + table_html + explain


START_JS = """
// Een lange ronde niet per ongeluk (vóór LIVE_JS, dat de klik anders verstuurt).
document.addEventListener('click', e => {
  const button = e.target.closest('.act button[data-confirm]');
  if (button && !confirm(button.dataset.confirm)) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);
// Terwijl een ronde draait: het logboek bijwerken, en herladen als hij klaar is.
if (document.getElementById('round-running')) {
  const poll = () => fetch('/start/status').then(r => r.json()).then(data => {
    const log = document.getElementById('round-log');
    if (log && data.log !== undefined) { log.textContent = data.log; log.scrollTop = log.scrollHeight; }
    if (!data.running) location.replace('/start?melding=' + encodeURIComponent('De ronde is klaar.'));
    else setTimeout(poll, 4000);
  }).catch(() => setTimeout(poll, 8000));
  setTimeout(poll, 4000);
  const log = document.getElementById('round-log');
  if (log) log.scrollTop = log.scrollHeight;
}
"""


def render_start(db_path, files_dir, message: str = "", token: str = "", running: str = "") -> str:
    rounds = load_recent_rounds(files_dir)
    book = fl.load_book(db_path, with_market_check=False) if Path(db_path).exists() else None
    last = rounds[0] if rounds else None
    t = book.totals if book else None
    tile_list = [
        ("Laatste ronde", pg.esc(local_time(last.get("finished_at") or last.get("started_at", ""))) if last else "—",
         f"{last.get('slot', '?')}: {last.get('status', '?')}, {last.get('new', 0)} nieuw" if last
         else "nog geen ronde gedraaid (python koopjes.py run nacht)"),
    ]
    if t is not None:
        tile_list += [
            ("Verdiend met flips", euro(t.realized_eur, cents=True, sign=True) if t.sold else "—",
             f"netto na investeringen {euro(t.net_eur, cents=True, sign=True)}"),
            ("Lopende flips", str(t.stock), f"{euro(t.stock_spent_eur, cents=True)} erin, verwacht "
                                            f"{euro(t.stock_expected_eur, cents=True, sign=True)}"),
        ]
    trails = ob.ordered(ob.load(db_path))
    open_bids = [x for x in trails if x.active]
    if trails:
        outbid = sum(1 for x in open_bids if x.outbid)
        tile_list.append(("Lopende biedingen", str(len(open_bids)),
                          (f"samen {euro(sum(x.latest.amount_eur for x in open_bids), cents=True)} geboden"
                           + (f", {outbid} al overboden" if outbid else "")) if open_bids else "geen lopende"))
    live = [
        (rb.PATH, "Racefietsen", "alle racefietsen: snel beoordelen, wegzetten, bod vastleggen, afstand"),
        *[(m.serve_path, m.short, f"alle {m.items} te koop, flips, favorieten, marktprijzen")
          for m in mk.MARKETS.values()],
        (pg.BIKE_PATH, "Mijn fiets", "vergelijkbare advertenties voor de taxatie van je eigen fiets"),
        (pg.FLIPS_PATH, "Flips", "je eigen flips: klussenlijst, kosten, winst, investeringen, Google Sheet"),
    ]
    cards = "".join(f"<a class='card' href='{pg.esc(href, quote=True)}'><div class='model'>{pg.esc(label)}</div>"
                    f"<div class='sub'>{pg.esc(sub)}</div></a>" for href, label, sub in live)
    files = list_files(files_dir)
    if files:
        rows = "".join(
            f"<li><a href='{pg.FILES_PATH}/{quote(name)}'>{pg.esc(_file_label(name))}</a>"
            f"<span class='muted'>{pg.esc(datetime.fromtimestamp(mtime).strftime('%d-%m-%Y %H:%M'))}</span></li>"
            for name, mtime in files)
        file_list = f"<ul class='files'>{rows}</ul>"
    else:
        file_list = "<p class='empty'>Nog geen rapporten. Die schrijft een ronde: <code>python koopjes.py run nacht</code>.</p>"
    round_rows = "".join(
        f"<li><span>{pg.esc(r.get('slot', '?'))} — {pg.esc(str(r.get('status', '?')))}, {int(r.get('new', 0) or 0)} nieuw"
        f"</span><span class='muted'>{pg.esc(local_time(r.get('started_at', '')))}</span></li>" for r in rounds)
    notice = f"<div class='banner' role='status'>{pg.esc(message)}</div>" if message else ""
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Koopjes</title><style>{pg.CSS}{pg.SITE_CSS}</style></head><body>"
        f"<main data-token='{pg.esc(token, quote=True)}'>"
        f"{pg.site_nav(pg.START_PATH)}<h1>Koopjes</h1>"
        "<div class='meta'>Alles op één plek. Deze pagina draait op je eigen computer "
        "(<code>python dashboard.py --serve</code>); stoppen met Ctrl+C in dat venster.</div>"
        f"{notice}{pg.tiles(tile_list)}<h3>Live</h3><div class='cards'>{cards}</div>"
        f"<h3>Rondes</h3>{rounds_panel(files_dir, running)}"
        f"<h3>Rapporten en lijsten</h3>{file_list}"
        + (f"<h3>Laatste rondes</h3><ul class='files'>{round_rows}</ul>" if rounds else "")
        + f"</main><div id='toast' role='status' hidden></div><script>{pg.LIVE_JS}{START_JS}</script></body></html>"
    )
