"""Scheduled search rounds: one command per time slot.

    python koopjes.py run overdag     # one round, as the scheduler starts it
    python koopjes.py status          # what's configured, when it last ran
    python koopjes.py schedule        # Task Scheduler / cron commands to paste
    python koopjes.py overview        # rebuild overzicht.html

Everything is described in schedule.json: the searches (a query plus the
filters racefiets_jev.py already knows, stored as watchlists) and the time
slots (which searches, how deep, how sorted, at what times). A round:

1. takes a lock, so a round that starts while another is still running is
   skipped instead of hitting Marktplaats twice in parallel;
2. writes the searches into the watchlist table, so the file stays the one
   place to change them;
3. runs racefiets_jev.py once for all of the slot's searches (one after the
   other, --delay between requests, as always);
4. optionally runs valuation.py, so the valuation history grows by itself;
5. rebuilds overzicht.html: one page with every search's latest numbers, the
   new listings worth a look, and links to the full reports.

Each step runs as its own process and everything it prints goes into the
log file, so a scheduled round that goes wrong can be read back afterwards.
"""
from __future__ import annotations

import argparse
import contextlib
import html
import json
import os
import subprocess
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

import db
import racefiets_jev as mp

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "schedule.json"

BID_LOOKUP_CHOICES = ("fast", "all", "none")
OPEN_BROWSER_CHOICES = ("auto", "always", "never")

# Dutch day abbreviations, as the times in schedule.json are written, mapped
# to what schtasks and cron call them.
DAYS = {
    "ma": ("MON", 1),
    "di": ("TUE", 2),
    "wo": ("WED", 3),
    "do": ("THU", 4),
    "vr": ("FRI", 5),
    "za": ("SAT", 6),
    "zo": ("SUN", 0),
}

# valuation.py's exit code when there are too few comparable listings: an
# outcome of the data, not a failure of the round.
VALUATION_NO_COMPS = 2

LOG_MAX_BYTES = 2_000_000


class ConfigError(Exception):
    pass


class LockBusy(Exception):
    pass


@dataclass(frozen=True)
class SlotTime:
    hour: int
    minute: int
    day: Optional[str] = None  # None = every day

    def label(self) -> str:
        clock = f"{self.hour:02d}:{self.minute:02d}"
        return f"{self.day} {clock}" if self.day else clock


@dataclass(frozen=True)
class Slot:
    name: str
    searches: tuple[str, ...]
    pages: int
    sort: str
    bid_lookup: str
    times: tuple[SlotTime, ...]
    valuation: bool = False
    open_browser: str = "never"


@dataclass(frozen=True)
class Config:
    path: Path
    searches: dict[str, dict]
    slots: dict[str, Slot]
    db: str = "koopjes.db"
    summary_file: str = "logs/runs.jsonl"
    overview: str = "overzicht.html"
    log_file: str = "logs/koopjes.log"
    html: str = "racefiets_report.html"
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    @property
    def base_dir(self) -> Path:
        return self.path.parent


# --- Config -----------------------------------------------------------------


def parse_time(text: str) -> SlotTime:
    parts = str(text).strip().lower().split()
    day = None
    if len(parts) == 2:
        day, clock = parts
        if day not in DAYS:
            raise ConfigError(
                f"onbekende dag {day!r} in tijd {text!r} (gebruik {', '.join(DAYS)})"
            )
    elif len(parts) == 1:
        clock = parts[0]
    else:
        raise ConfigError(f"tijd {text!r} is geen 'HH:MM' of 'dag HH:MM'")
    try:
        hour_text, minute_text = clock.split(":")
        hour, minute = int(hour_text), int(minute_text)
    except ValueError:
        raise ConfigError(f"tijd {text!r} is geen 'HH:MM' of 'dag HH:MM'") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(f"tijd {text!r} bestaat niet")
    return SlotTime(hour, minute, day)


def validate_search(name: str, spec) -> dict:
    """A search is a watchlist: a query plus racefiets_jev's watchlist
    filters. Validated with the same code that runs it, so a typo in
    schedule.json fails here, at load time, not at 03:00."""
    if not isinstance(spec, dict):
        raise ConfigError(f"zoekopdracht {name!r} moet een object zijn")
    if not name or name == mp.WATCHLIST_ALL or "," in name:
        raise ConfigError(f"{name!r} kan geen naam van een zoekopdracht zijn")
    query = spec.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ConfigError(f"zoekopdracht {name!r} heeft geen 'query'")
    filters = {k: v for k, v in spec.items() if k not in ("query", "note")}
    try:
        mp.args_for_watchlist(mp.parse_args([]), {"name": name, "query": query, "filters": filters})
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    return {"query": query.strip(), "filters": filters}


def load_config(path: Path) -> Config:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path} niet gevonden") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is geen geldige JSON: {exc}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} moet een JSON-object zijn")

    searches = {
        name: validate_search(name, spec) for name, spec in (raw.get("searches") or {}).items()
    }
    if not searches:
        raise ConfigError(f"{path} heeft geen 'searches'")

    slots: dict[str, Slot] = {}
    for name, spec in (raw.get("slots") or {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"tijdslot {name!r} moet een object zijn")
        names = spec.get("searches") or []
        unknown = [s for s in names if s not in searches]
        if not names or unknown:
            raise ConfigError(
                f"tijdslot {name!r}: " + (f"onbekende zoekopdracht(en) {', '.join(unknown)}"
                                          if unknown else "geen 'searches'")
            )
        pages = spec.get("pages", 1)
        if not isinstance(pages, int) or isinstance(pages, bool) or pages < 0:
            raise ConfigError(f"tijdslot {name!r}: 'pages' moet een geheel getal ≥ 0 zijn")
        sort = spec.get("sort", "newest")
        if sort not in mp.SORT_OPTIONS:
            raise ConfigError(f"tijdslot {name!r}: 'sort' moet een van {', '.join(mp.SORT_OPTIONS)} zijn")
        bid_lookup = spec.get("bid_lookup", "fast")
        if bid_lookup not in BID_LOOKUP_CHOICES:
            raise ConfigError(
                f"tijdslot {name!r}: 'bid_lookup' moet een van {', '.join(BID_LOOKUP_CHOICES)} zijn"
            )
        open_browser = spec.get("open_browser", "never")
        if open_browser not in OPEN_BROWSER_CHOICES:
            raise ConfigError(
                f"tijdslot {name!r}: 'open_browser' moet een van "
                f"{', '.join(OPEN_BROWSER_CHOICES)} zijn"
            )
        slots[name] = Slot(
            name=name,
            searches=tuple(names),
            pages=pages,
            sort=sort,
            bid_lookup=bid_lookup,
            times=tuple(parse_time(t) for t in spec.get("times") or []),
            valuation=bool(spec.get("valuation", False)),
            open_browser=open_browser,
        )
    if not slots:
        raise ConfigError(f"{path} heeft geen 'slots'")

    files = raw.get("files") or {}
    extra_args = raw.get("extra_args") or []
    if not all(isinstance(a, str) for a in extra_args):
        raise ConfigError("'extra_args' moet een lijst met tekst zijn")
    return Config(
        path=Path(path).resolve(),
        searches=searches,
        slots=slots,
        db=files.get("db", "koopjes.db"),
        summary_file=files.get("summary", "logs/runs.jsonl"),
        overview=files.get("overview", "overzicht.html"),
        log_file=files.get("log", "logs/koopjes.log"),
        html=files.get("report", "racefiets_report.html"),
        extra_args=tuple(extra_args),
    )


# --- Running a slot ---------------------------------------------------------


@contextlib.contextmanager
def run_lock(path: Path) -> Iterator[None]:
    """An OS-level lock on a file: released by the OS when the process ends,
    however it ends, so a crashed round never blocks the next one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LockBusy() from None
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def lock_path(config: Config) -> Path:
    return config.base_dir / ".koopjes.lock"


def search_command(config: Config, slot: Slot) -> list[str]:
    return [
        sys.executable,
        str(HERE / "racefiets_jev.py"),
        "--watchlist", ",".join(slot.searches),
        "--pages", str(slot.pages),
        "--sort", slot.sort,
        "--bid-lookup", slot.bid_lookup,
        "--open-browser", "never",
        "--db", config.db,
        "--html", config.html,
        "--summary-file", config.summary_file,
        *config.extra_args,
    ]


def valuation_command(config: Config) -> list[str]:
    return [sys.executable, str(HERE / "valuation.py"), "--db", config.db]


class Log:
    """Appends to the log file and echoes to the console, so a manual round
    shows its progress and a scheduled one leaves a readable trail."""

    def __init__(self, path: Path, echo: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))
        self.handle = open(path, "a", encoding="utf-8")
        self.echo = echo

    def line(self, text: str) -> None:
        text = text.rstrip("\n")
        self.handle.write(text + "\n")
        self.handle.flush()
        if not self.echo or sys.stdout is None:
            return
        try:
            print(text)
        except UnicodeEncodeError:
            # A Windows console or a scheduler's redirected output is often
            # cp1252, and listing titles carry emoji ("Nieuw ✅"). The log
            # file has the real text; the console gets a readable stand-in
            # rather than a crashed round.
            encoding = sys.stdout.encoding or "ascii"
            print(text.encode(encoding, errors="replace").decode(encoding))

    def close(self) -> None:
        self.handle.close()


def run_process(command: list[str], log: Log, cwd: Path) -> int:
    log.line(f"$ {' '.join(command)}")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert process.stdout is not None
    for line in process.stdout:
        log.line(line)
    return process.wait()


def sync_searches(config: Config) -> None:
    conn = db.connect(str(config.base_dir / config.db))
    try:
        for name, search in config.searches.items():
            db.save_watchlist(conn, name, search["query"], search["filters"])
    finally:
        conn.close()


def now_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def run_slot(
    config: Config,
    slot_name: str,
    *,
    runner: Callable[[list[str], Log, Path], int] = run_process,
    echo: bool = True,
) -> int:
    slot = config.slots.get(slot_name)
    if slot is None:
        print(
            f"fout: onbekend tijdslot {slot_name!r} (bekend: {', '.join(config.slots)})",
            file=sys.stderr,
        )
        return 1

    log = Log(config.base_dir / config.log_file, echo=echo)
    try:
        log.line(f"=== {now_local()} ronde '{slot.name}': {', '.join(slot.searches)} ===")
        try:
            with run_lock(lock_path(config)):
                return _run_locked(config, slot, log, runner)
        except LockBusy:
            log.line("Overgeslagen: er draait al een ronde. Marktplaats krijgt nooit twee tegelijk.")
            return 0
        except Exception as exc:  # noqa: BLE001 — a scheduled round has no one watching its console
            # E.g. koopjes.db locked by a manual run for longer than sqlite
            # waits. Without this the traceback goes to a console nobody
            # sees, and the log just stops.
            log.line(f"FOUT: de ronde stopte onverwacht: {type(exc).__name__}: {exc}")
            return 1
    finally:
        log.close()


def _run_locked(config: Config, slot: Slot, log: Log, runner) -> int:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sync_searches(config)
    failed = False

    code = runner(search_command(config, slot), log, config.base_dir)
    if code != 0:
        failed = True
        log.line(f"FOUT: het zoeken stopte met code {code}")

    if slot.valuation:
        code = runner(valuation_command(config), log, config.base_dir)
        if code == VALUATION_NO_COMPS:
            log.line("Geen taxatie: te weinig vergelijkbare advertenties (dat is een uitkomst, geen fout).")
        elif code != 0:
            failed = True
            log.line(f"FOUT: de taxatie stopte met code {code}")

    overview = write_overview(config)
    log.line(f"Overzicht bijgewerkt: {overview}")
    unmatched, deals = write_lists(config)
    log.line(f"Lijsten bijgewerkt: {unmatched} en {deals}")

    new_this_round = sum(
        s.get("new", 0)
        for s in load_summaries(config.base_dir / config.summary_file).values()
        if s.get("finished_at", "") >= started and s.get("name") in slot.searches
    )
    if slot.open_browser == "always" or (slot.open_browser == "auto" and new_this_round):
        with contextlib.suppress(webbrowser.Error):
            webbrowser.open(overview.resolve().as_uri())

    log.line(f"Klaar: {new_this_round} nieuwe advertentie(s){' — met fouten, zie hierboven' if failed else ''}.")
    return 1 if failed else 0


# --- Overview page ----------------------------------------------------------


def load_summaries(path: Path) -> dict[str, dict]:
    """The latest summary line per report name. A damaged line is skipped:
    one bad write must not take the overview page down."""
    latest: dict[str, dict] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return latest
    for line in lines:
        try:
            summary = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(summary, dict) and summary.get("name"):
            latest[summary["name"]] = summary
    return latest


def summaries_for_search(name: str, query: str, summaries: dict[str, dict]) -> list[dict]:
    """A search with a comma-separated query writes one report per term,
    named "<search> <term>" (see racefiets_jev.main)."""
    terms = [t.strip() for t in query.split(",") if t.strip()]
    if len(terms) <= 1:
        return [summaries[name]] if name in summaries else []
    return [summaries[f"{name} {t}"] for t in terms if f"{name} {t}" in summaries]


def latest_valuations(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    conn = db.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT scenario, low_eur, mid_eur, high_eur, confidence, created_at FROM valuation "
            "WHERE id IN (SELECT MAX(id) FROM valuation GROUP BY scenario) ORDER BY scenario"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d-%m %H:%M")
    except (ValueError, AttributeError):
        return "?"


def euro(value) -> str:
    return "—" if value is None else f"€{value:,.0f}".replace(",", ".")


OVERVIEW_CSS = """
:root { color-scheme: light dark; --bg:#fff; --fg:#1d1d1f; --muted:#6b6b70; --line:#e3e3e6;
        --accent:#0a66c2; --good:#1a7f37; --warn:#b35900; }
@media (prefers-color-scheme: dark) { :root { --bg:#161618; --fg:#ececef; --muted:#a0a0a8;
        --line:#2e2e33; --accent:#5aa9ff; --good:#4ac26b; --warn:#f0a050; } }
body { background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, sans-serif;
       margin:0 auto; max-width:1100px; padding:16px; }
h1 { font-size:22px; margin:8px 0 2px; } h2 { font-size:17px; margin:28px 0 8px; }
.muted { color:var(--muted); } a { color:var(--accent); }
.table-wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-weight:600; font-size:13px; color:var(--muted); }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.good { color:var(--good); font-weight:600; } .warn { color:var(--warn); }
ul.hl { margin:4px 0 12px; padding-left:18px; } ul.hl li { margin:2px 0; }
.badge { display:inline-block; font-size:12px; padding:0 6px; border-radius:8px;
         border:1px solid var(--line); margin-left:4px; }
"""


def render_overview(config: Config, summaries: dict[str, dict], valuations: list[dict]) -> str:
    esc = html.escape
    parts = [
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Koopjes-overzicht</title>",
        f"<style>{OVERVIEW_CSS}</style></head><body>",
        "<h1>Koopjes-overzicht</h1>",
        f"<p class='muted'>Bijgewerkt {esc(now_local())} · schema: {esc(config.path.name)}</p>",
    ]

    parts.append("<h2>Mijn fiets</h2>")
    if valuations:
        items = "".join(
            f"<li>Scenario {esc(v['scenario'])}: {euro(v['low_eur'])} – <strong>{euro(v['mid_eur'])}"
            f"</strong> – {euro(v['high_eur'])} <span class='muted'>(vertrouwen: "
            f"{esc(v['confidence'] or '?')}, {esc(local_time(v['created_at'] or ''))})</span></li>"
            for v in valuations
        )
        parts.append(f"<ul>{items}</ul>")
    else:
        parts.append(
            "<p class='muted'>Nog geen taxatie opgeslagen. Die komt uit een ronde met "
            "\"valuation\": true, zodra er genoeg vergelijkbare advertenties zijn.</p>"
        )

    parts.append("<h2>Zoekopdrachten</h2><div class='table-wrap'><table><thead><tr>")
    parts.append(
        "<th>Zoekopdracht</th><th>Laatste run</th><th class='num'>Advertenties</th>"
        "<th class='num'>Nieuw</th><th class='num'>Beter dan ref.</th><th class='num'>Topdeals</th>"
        "<th class='num'>Prijs&shy;verlaging</th><th>Rapport</th></tr></thead><tbody>"
    )
    highlights = []
    for name, search in config.searches.items():
        found = summaries_for_search(name, search["query"], summaries)
        if not found:
            parts.append(
                f"<tr><td>{esc(name)}<div class='muted'>{esc(search['query'])}</div></td>"
                "<td class='muted' colspan='7'>nog niet gedraaid</td></tr>"
            )
            continue
        for summary in found:
            report = summary.get("report")
            link = f"<a href='{esc(report)}'>openen</a>" if report else "<span class='muted'>—</span>"
            parts.append(
                f"<tr><td>{esc(summary['name'])}<div class='muted'>{esc(summary.get('query', ''))}</div></td>"
                f"<td>{esc(local_time(summary.get('finished_at', '')))}</td>"
                f"<td class='num'>{summary.get('listings', 0)}</td>"
                f"<td class='num{' good' if summary.get('new') else ''}'>{summary.get('new', 0)}</td>"
                f"<td class='num{' good' if summary.get('better') else ''}'>{summary.get('better', 0)}</td>"
                f"<td class='num'>{summary.get('top_deals', 0)}</td>"
                f"<td class='num'>{summary.get('price_drops', 0)}</td>"
                f"<td>{link}</td></tr>"
            )
            for item in summary.get("highlights") or []:
                highlights.append((summary["name"], item))
    parts.append("</tbody></table></div>")

    upgrades = [
        (s["name"], u)
        for name, search in config.searches.items()
        for s in summaries_for_search(name, search["query"], summaries)
        for u in s.get("upgrades") or []
    ]
    parts.append("<h2>Beste upgrades</h2>")
    if upgrades:
        parts.append(
            "<p class='muted'>Uit de tab Upgrade van de rapporten: betere fietsen binnen je budget "
            "en maat, op upgrade per euro. De prijs is de effectieve prijs (vraagprijs × "
            "onderhandelingsruimte, of de instapprijs bij een bod).</p><ul class='hl'>"
        )
        for name, u in sorted(upgrades, key=lambda pair: -(pair[1].get("per_100_eur") or 0)):
            new = "<span class='badge good'>nieuw</span>" if u.get("new") else ""
            parts.append(
                f"<li><a href='{esc(u.get('url') or '#')}'>{esc(u.get('title') or '')}</a> — "
                f"{euro(u.get('price_eur'))} <span class='muted'>({esc(u.get('price_basis') or '')})</span>"
                f"<span class='badge'>kwaliteit {u.get('quality')} (+{u.get('gain')})</span>"
                f"<span class='badge'>{u.get('per_100_eur')} punt per €100</span>{new}"
                f" <span class='muted'>{esc(name)}</span></li>"
            )
        parts.append("</ul>")
    else:
        parts.append(
            "<p class='muted'>Geen upgrade-kandidaten in de laatste runs. Staat er in het "
            "rapport op de tab Mijn fiets dat er geen taxatie is, dan is er ook geen budget; "
            "vul dan verkoopprijs_handmatig in mijn_fiets.md in.</p>"
        )

    sleeper_items = [
        (s["name"], item)
        for name, search in config.searches.items()
        for s in summaries_for_search(name, search["query"], summaries)
        for item in s.get("sleepers") or []
    ]
    parts.append("<h2>Slapers — kijk naar de foto's</h2>")
    if sleeper_items:
        parts.append(
            "<p class='muted'>Nieuwe advertenties waar de titel geen merk of model noemt, met "
            "weinig tekst, haast of een bod zonder minimum. Zo'n verkoper weet vaak niet wat "
            "hij heeft, en wie op merk zoekt vindt hem niet. De tekst zegt niets over de "
            "fiets; de foto wel. Snel zijn telt: zulke advertenties zijn vaak binnen een paar "
            "uur weg.</p><ul class='hl'>"
        )
        for name, item in sleeper_items:
            image = (
                f"<img src='{esc(item['image'])}' alt='' loading='lazy' "
                "style='height:90px;vertical-align:middle;margin-right:8px;border-radius:4px'>"
                if item.get("image") else ""
            )
            parts.append(
                f"<li><a href='{esc(item.get('url') or '#')}'>{image}{esc(item.get('title') or '')}</a>"
                f" — {esc(item.get('price') or '?')} · {esc(item.get('city') or '?')}"
                f"<span class='badge good'>slaper {item.get('score') or 0:.0f}</span>"
                f" <span class='muted'>{esc(item.get('reasons') or '')} · {esc(name)}</span></li>"
            )
        parts.append("</ul>")
    else:
        parts.append("<p class='muted'>Geen nieuwe slapers bij de laatste runs.</p>")

    parts.append("<h2>Nieuw en het bekijken waard</h2>")
    if highlights:
        parts.append(
            "<p class='muted'>Per zoekopdracht de nieuwe advertenties van de laatste run: eerst "
            "wat beter is dan je referentie, dan op dealscore. De dealscore vergelijkt met de "
            "mediaan van de hele zoekopdracht: een los frame of een oude aluminium fiets scoort "
            "dus hoog. Advertenties met een lopend bod staan in het Biedpaneel van het rapport.</p>"
        )
        by_search: dict[str, list[dict]] = {}
        for name, item in highlights:
            by_search.setdefault(name, []).append(item)
        for name, items in by_search.items():
            rows = []
            for item in items:
                price = euro(item.get("price_eur")) if item.get("price_eur") is not None else esc(
                    item.get("price_type") or "?"
                )
                score = item.get("deal_score")
                badges = ""
                if item.get("better"):
                    badges += f"<span class='badge good'>beter: {esc(item.get('ref_label') or '')}</span>"
                if score is not None:
                    badges += f"<span class='badge'>score {score:.0f}</span>"
                rows.append(
                    f"<li><a href='{esc(item.get('url') or '#')}'>{esc(item.get('title') or '')}</a> "
                    f"— {price}{badges}</li>"
                )
            parts.append(f"<h3>{esc(name)}</h3><ul class='hl'>{''.join(rows)}</ul>")
    else:
        parts.append("<p class='muted'>Niets nieuws bij de laatste runs.</p>")

    parts.append(
        f"<h2>Lijsten om door te geven</h2><ul><li><a href='{LISTS_DIR}/beste_koopjes.txt'>"
        "Beste koopjes</a> — met URL en onderbouwing, om te laten controleren</li>"
        f"<li><a href='{LISTS_DIR}/zonder_referentie.txt'>Racefietsen zonder referentie</a> — "
        "welke modellen nog uitgezocht moeten worden</li></ul>"
    )
    parts.append("<h2>Planning</h2><div class='table-wrap'><table><thead><tr>")
    parts.append("<th>Ronde</th><th>Tijden</th><th>Zoekopdrachten</th><th>Diepte</th></tr></thead><tbody>")
    for slot in config.slots.values():
        depth = "alles (tot ~5000)" if slot.pages == 0 else f"{slot.pages} pagina's"
        parts.append(
            f"<tr><td>{esc(slot.name)}</td>"
            f"<td>{esc(', '.join(t.label() for t in slot.times) or 'handmatig')}</td>"
            f"<td>{esc(', '.join(slot.searches))}</td>"
            f"<td>{esc(depth)}, {esc(slot.sort)}{', taxatie' if slot.valuation else ''}</td></tr>"
        )
    parts.append("</tbody></table></div></body></html>")
    return "\n".join(parts)


def write_overview(config: Config) -> Path:
    summaries = load_summaries(config.base_dir / config.summary_file)
    valuations = latest_valuations(config.base_dir / config.db)
    path = config.base_dir / config.overview
    path.write_text(render_overview(config, summaries, valuations), encoding="utf-8")
    return path


# --- Lists to hand on --------------------------------------------------------

LISTS_DIR = "lijsten"
UNMATCHED_DAYS = 14
UNMATCHED_EXAMPLES = 5

# Brands to group unmatched listings by, on top of those in
# reference_bike_catalog.csv: the ones that turn up on Marktplaats a lot and
# aren't in the catalogue. Only used to group, never as a fact about a bike.
EXTRA_BRANDS = (
    "Koga", "Gazelle", "Batavus", "Isaac", "Van Rysel", "Look", "Eddy Merckx",
    "Argon 18", "Factor", "3T", "Cube", "Giant", "Trek", "Sensa", "Liv",
    "Cannondale", "Specialized", "Canyon", "Scott", "Ribble", "Vitus", "Boardman",
    "Principia", "Cervelo", "Cervélo", "Lapierre", "Merckx", "Jan Janssen", "Rih",
)
# Words after the brand that say nothing about the model.
GENERIC_WORDS = {
    "racefiets", "racefietsen", "fiets", "road", "roadbike", "carbon", "aluminium",
    "alu", "heren", "dames", "maat", "frame", "koersfiets", "wielrenfiets",
    "gravel", "gravelbike", "te", "koop", "in", "met", "de", "het", "een", "en",
}


def known_brands(config: Config) -> list[str]:
    brands = set(EXTRA_BRANDS)
    catalog = config.base_dir / "reference_bike_catalog.csv"
    try:
        import csv

        with open(catalog, encoding="utf-8-sig") as f:
            brands |= {row["brand"].strip() for row in csv.DictReader(f) if row.get("brand")}
    except (FileNotFoundError, KeyError):
        pass
    # Longest first, so "Eddy Merckx" wins over "Merckx".
    return sorted(brands, key=len, reverse=True)


def model_family(title: str, brands: list[str]) -> str:
    """"<Brand> <first model word>" from a title, or "(merk onbekend)".
    A grouping aid for the list, not a match: the reference file is what
    says which model a listing is."""
    lower = title.lower()
    for brand in brands:
        index = lower.find(brand.lower())
        if index == -1:
            continue
        before = lower[index - 1] if index else " "
        if before.isalnum():
            continue
        rest = title[index + len(brand):].split()
        for word in rest:
            clean = word.strip(".,:;!|/()-").lower()
            if clean and clean not in GENERIC_WORDS and not clean.isdigit():
                return f"{brand} {word.strip('.,:;!|/()-').capitalize()}"
        return brand
    return "(merk onbekend)"


def unmatched_listings(config: Config) -> list[dict]:
    """Complete road bikes seen in the last two weeks that no row in the
    bike reference file matched — the gaps in reference_bikes.csv."""
    path = config.base_dir / config.db
    if not path.exists():
        return []
    conn = db.connect(str(path))
    try:
        since = datetime.now(timezone.utc).timestamp() - UNMATCHED_DAYS * 86400
        since_iso = datetime.fromtimestamp(since, timezone.utc).isoformat(timespec="seconds")
        rows = conn.execute(
            """
            SELECT item_id, title, price_eur, price_type, url, last_seen FROM listing
            WHERE disappeared_at IS NULL AND (last_seen IS NULL OR last_seen >= ?)
              AND item_id NOT IN (
                SELECT lm.listing_id FROM listing_model lm
                JOIN model m ON m.id = lm.model_id WHERE m.kind = 'bike')
            ORDER BY last_seen DESC
            """,
            (since_iso,),
        ).fetchall()
    finally:
        conn.close()
    return [
        dict(row) for row in rows if mp.category_from_url(row["url"] or "") == mp.ROAD_BIKE_CATEGORY
    ]


def price_text(price, price_type) -> str:
    if price:
        return euro(price) + (" (bieden)" if price_type in ("MIN_BID", "FAST_BID") else "")
    return {"FAST_BID": "bieden", "SEE_DESCRIPTION": "zie omschrijving", "FREE": "gratis"}.get(
        price_type or "", "?"
    )


def render_unmatched(listings: list[dict], brands: list[str]) -> str:
    groups: dict[str, list[dict]] = {}
    for listing in listings:
        groups.setdefault(model_family(listing["title"] or "", brands), []).append(listing)
    ordered = sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    lines = [
        f"Racefietsen zonder referentie — {now_local()}",
        "",
        f"{len(listings)} complete racefietsen uit de laatste {UNMATCHED_DAYS} dagen die door geen enkele "
        "rij in reference_bikes.csv herkend worden, gegroepeerd op merk + eerste modelwoord",
        "(dat groeperen is een hulpmiddel, geen herkenning). Meest voorkomend eerst.",
        "Geef dit bestand aan Claude met de vraag welke modellen onderzocht en toegevoegd moeten worden.",
        "",
        "Samenvatting:",
    ]
    lines += [f"  {len(items):3d}×  {name}" for name, items in ordered]
    for name, items in ordered:
        lines += ["", f"== {name} ({len(items)}) =="]
        for listing in items[:UNMATCHED_EXAMPLES]:
            lines.append(f"  {price_text(listing['price_eur'], listing['price_type']):>18}  "
                         f"{listing['title']}")
            lines.append(f"  {'':>18}  {listing['url']}")
        if len(items) > UNMATCHED_EXAMPLES:
            lines.append(f"  ... en nog {len(items) - UNMATCHED_EXAMPLES}")
    return "\n".join(lines) + "\n"


def render_best_deals(config: Config, summaries: dict[str, dict]) -> str:
    lines = [
        f"Beste koopjes — {now_local()}",
        "",
        "Per zoekopdracht uit de laatste run. Geef dit bestand (of een paar regels eruit) aan Claude",
        "met de vraag of het echt koopjes zijn. 'score' is de dealscore (0-100, t.o.v. de mediaan van de",
        "zoekopdracht, het 2e-hands gemiddelde en de nieuwprijs); 'waarom' is de onderbouwing ervan.",
        "Lopende biedingen staan hier niet in: hun prijs is het bod tot nu toe (zie het Biedpaneel).",
    ]
    for name, search in config.searches.items():
        for summary in summaries_for_search(name, search["query"], summaries):
            upgrades = summary.get("upgrades") or []
            deals = summary.get("deals") or []
            if not upgrades and not deals:
                continue
            lines += ["", f"== {summary['name']} ({summary.get('query', '')}, "
                          f"{local_time(summary.get('finished_at', ''))}) =="]
            if upgrades:
                lines.append("Upgrades voor jouw fiets (binnen budget en maat, op upgrade per euro):")
                for u in upgrades:
                    lines.append(f"  {euro(u.get('price_eur')):>10}  kwaliteit {u.get('quality')} "
                                 f"(+{u.get('gain')})  {u.get('title')}")
                    lines.append(f"  {'':>10}  {u.get('url')}")
            if deals:
                lines.append("Hoogste dealscores:")
                for d in deals:
                    extra = " · ".join(x for x in (
                        f"ref: {d['ref_label']}" if d.get("ref_label") else "",
                        f"maat {d['frame_height']}" if d.get("frame_height") else "",
                        d.get("city") or "",
                    ) if x)
                    lines.append(f"  {price_text(d.get('price_eur'), d.get('price_type')):>18}  "
                                 f"score {d.get('deal_score') or 0:.0f}  {d.get('title')}")
                    if extra:
                        lines.append(f"  {'':>18}  {extra}")
                    if d.get("reasons"):
                        lines.append(f"  {'':>18}  waarom: {d['reasons']}")
                    lines.append(f"  {'':>18}  {d.get('url')}")
    if len(lines) == 6:
        lines += ["", "Nog niets: draai eerst een ronde (python koopjes.py run overdag)."]
    return "\n".join(lines) + "\n"


def write_lists(config: Config) -> tuple[Path, Path]:
    directory = config.base_dir / LISTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    unmatched = directory / "zonder_referentie.txt"
    unmatched.write_text(
        render_unmatched(unmatched_listings(config), known_brands(config)), encoding="utf-8"
    )
    deals = directory / "beste_koopjes.txt"
    deals.write_text(
        render_best_deals(config, load_summaries(config.base_dir / config.summary_file)),
        encoding="utf-8",
    )
    return unmatched, deals


# --- Scheduling -------------------------------------------------------------


def windows_commands(config: Config, python: str, script: str) -> list[str]:
    lines = []
    for slot in config.slots.values():
        for t in slot.times:
            name = f"Koopjes\\{slot.name} {t.hour:02d}{t.minute:02d}{' ' + t.day if t.day else ''}"
            when = f"/SC WEEKLY /D {DAYS[t.day][0]}" if t.day else "/SC DAILY"
            action = f'\\"{python}\\" \\"{script}\\" run {slot.name}'
            lines.append(
                f'schtasks /Create /F /TN "{name}" {when} /ST {t.hour:02d}:{t.minute:02d} /TR "{action}"'
            )
    return lines


def cron_lines(config: Config, python: str, script: str) -> list[str]:
    lines = []
    for slot in config.slots.values():
        for t in slot.times:
            dow = str(DAYS[t.day][1]) if t.day else "*"
            lines.append(f"{t.minute} {t.hour} * * {dow}  '{python}' '{script}' run {slot.name}")
    return lines


def print_schedule(config: Config) -> None:
    python = sys.executable
    script = str(HERE / "koopjes.py")
    print("Windows — plak dit in een opdrachtprompt (cmd). /F overschrijft een bestaande taak:")
    print()
    for line in windows_commands(config, python, script):
        print(line)
    print()
    print("macOS/Linux — voeg dit toe met 'crontab -e':")
    print()
    for line in cron_lines(config, python, script):
        print(line)
    print()
    print(
        "De ronde zoekt zelf zijn map op; het maakt dus niet uit in welke map de "
        "planner hem start. De uitvoer staat in "
        f"{config.base_dir / config.log_file}."
    )


def print_status(config: Config) -> None:
    summaries = load_summaries(config.base_dir / config.summary_file)
    print(f"Schema: {config.path}")
    try:
        with run_lock(lock_path(config)):
            running = False
    except LockBusy:
        running = True
    print("Er draait nu een ronde." if running else "Er draait nu geen ronde.")
    print()
    for slot in config.slots.values():
        times = ", ".join(t.label() for t in slot.times) or "handmatig"
        depth = "alles" if slot.pages == 0 else f"{slot.pages} pagina's"
        print(f"{slot.name}: {times} — {', '.join(slot.searches)} ({depth}, {slot.sort})")
    print()
    for name, search in config.searches.items():
        found = summaries_for_search(name, search["query"], summaries)
        if not found:
            print(f"  {name}: nog niet gedraaid")
        for s in found:
            print(
                f"  {s['name']}: {local_time(s.get('finished_at', ''))} — {s.get('listings', 0)} "
                f"advertenties, {s.get('new', 0)} nieuw, {s.get('better', 0)} beter dan referentie"
            )


# --- CLI ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="schedule file (default: schedule.json next to this script)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one time slot from the schedule")
    run.add_argument("slot")
    sub.add_parser("status", help="show the schedule and when each search last ran")
    sub.add_parser("schedule", help="print Task Scheduler (Windows) and cron commands")
    sub.add_parser("overview", help="rebuild the overview page")
    sub.add_parser(
        "lists",
        help="write lijsten/zonder_referentie.txt and lijsten/beste_koopjes.txt "
        "(also done after every round)",
    )
    return parser


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    """Relative paths in schedule.json mean "next to schedule.json" — a task
    scheduler starts programs in some system directory, not in the repo."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(Path(args.config))
    except ConfigError as exc:
        print(f"fout in het schema: {exc}", file=sys.stderr)
        return 1

    with working_directory(config.base_dir):
        if args.command == "run":
            return run_slot(config, args.slot)
        if args.command == "status":
            print_status(config)
            return 0
        if args.command == "schedule":
            print_schedule(config)
            return 0
        if args.command == "lists":
            unmatched, deals = write_lists(config)
            print(f"Geschreven: {unmatched}")
            print(f"Geschreven: {deals}")
            return 0
        print(f"Overzicht bijgewerkt: {write_overview(config)}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
