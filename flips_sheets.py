"""/flips en een Google Sheet in twee richtingen gelijk houden.

Sheets kan niet bij je laptop (het dashboard draait op 127.0.0.1), dus de
laptop gaat naar de Sheet: een klein Apps Script in de Sheet (flips_sheets.gs)
staat online als webapp met een geheime sleutel, en dit bestand praat
daarmee via `requests`. Geen Google Cloud-project, geen extra library.

Een ronde (knop op /flips, en vanzelf bij het openen van de pagina):
1. ophalen wat er in de Sheet staat;
2. wat je in de Sheet wijzigde sinds de vorige ronde overnemen. Het script
   zet bij elke wijziging met de hand de kolom `bijgewerkt` van die rij op
   nu; een rij zonder id met een titel is een nieuwe klus; een rij die
   verdween is weggehaald. Is dezelfde regel op de pagina én in de Sheet
   gewijzigd, dan wint de laatste wijziging en zegt de melding wat er
   overschreven is;
3. alles opnieuw naar de Sheet schrijven (Flips, Klussen, Investeringen,
   Totalen), met getallen als getallen, zodat je er eigen formules en
   grafieken op kunt bouwen. Maak die op een eigen tabblad: deze vier
   worden elke ronde overschreven.

Wat vanuit de Sheet te wijzigen is: bij klussen en investeringen alles
behalve id, flip, kost en bijgewerkt; bij flips de fase (niet verkocht:
dat gaat op de pagina, met een prijs), doelprijzen, uren, zoekwoorden,
verkooplink en notitie. De rest is uitkomst en wordt overschreven.

Instellen: zie SHEETS.md. De sleutel staat in sheets.json (niet in git).
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape as esc
from pathlib import Path
from typing import Optional

import db
import flips as fl

STATE_SUFFIX = ".state.json"
TIMEOUT_S = 30


class SheetError(RuntimeError):
    """Iets met de Sheet dat de gebruiker moet weten; de tekst gaat naar de pagina."""


@dataclass
class Result:
    taken: list = field(default_factory=list)  # wat uit de Sheet is overgenomen
    overwritten: list = field(default_factory=list)  # conflicten: wat verloor
    pushed: int = 0

    def summary(self) -> str:
        if not self.taken:
            text = "Sheet: niets nieuws overgenomen"
        else:
            text = f"Sheet: {len(self.taken)} wijziging{'en' if len(self.taken) != 1 else ''} overgenomen ("
            text += "; ".join(self.taken[:5]) + ("; …" if len(self.taken) > 5 else "") + ")"
        if self.overwritten:
            text += ". Overschreven, want later gewijzigd: " + "; ".join(self.overwritten[:5])
        return text + f". {self.pushed} regels naar de Sheet geschreven."


def load_config(config_path) -> Optional[dict]:
    path = Path(config_path)
    if not path.exists():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SheetError(f"{path.name} is geen geldige JSON: {exc}") from None
    if not config.get("url") or not config.get("secret"):
        raise SheetError(f"{path.name} mist 'url' of 'secret' (zie SHEETS.md).")
    return config


def _state_path(config_path) -> Path:
    return Path(str(config_path) + STATE_SUFFIX)


def load_state(config_path) -> dict:
    try:
        return json.loads(_state_path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(config_path, state: dict) -> None:
    _state_path(config_path).write_text(json.dumps(state, indent=1), encoding="utf-8")


def parse_time(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _call(config: dict, payload: dict, session=None) -> dict:
    import requests

    session = session or requests
    try:
        # Apps Script stuurt een POST door (302) naar het antwoord; requests volgt dat.
        response = session.post(config["url"], data=json.dumps({"secret": config["secret"], **payload}),
                                headers={"Content-Type": "text/plain"}, timeout=TIMEOUT_S)
    except Exception as exc:  # requests.RequestException en alles eronder
        raise SheetError(f"Sheet niet bereikbaar: {exc}") from None
    if response.status_code != 200:
        raise SheetError(f"Sheet gaf HTTP {response.status_code}.")
    try:
        data = response.json()
    except ValueError:
        raise SheetError("Sheet gaf geen JSON terug; staat de webapp op 'Iedereen' en is de URL die van "
                         "de implementatie (…/exec)?") from None
    if not data.get("ok"):
        raise SheetError(f"Sheet weigerde: {data.get('error', 'onbekende fout')}")
    return data


# --- Van de database naar tabellen -------------------------------------------------

TASK_HEADERS = ["id", "flip", "flip_naam", "soort", "titel", "winkel", "geschat", "prijs", "bron", "investering",
                "tarief", "korting", "kost", "gedaan", "notitie", "bijgewerkt"]
FLIP_HEADERS = ["id", "titel", "soort", "fase", "dagen_in_fase", "gekocht_op", "inkoop", "uitgegeven", "gepland",
                "doel_laag", "doel_hoog", "winst_laag", "winst_hoog", "hoogste_bod", "verkocht_op", "verkocht_voor",
                "winst", "uren", "per_uur", "zoekwoorden", "verkooplink", "notitie", "bijgewerkt"]


def _yes(value: bool) -> str:
    return "ja" if value else "nee"


def task_row(k: fl.Task, flip_name: str = "") -> list:
    return [k.id, k.trade_id or "", flip_name, k.kind, k.title, k.shop, k.est_eur, k.price_eur, k.price_source,
            _yes(k.investment), k.fare_eur, k.discount if k.kind == "reis" else "", k.cost_eur,
            _yes(k.done), k.notes, k.updated_at]


def flip_row(f: fl.Flip) -> list:
    t = f.trade
    low, high = f.target
    sold = f.sold
    return [f.id, t.title, f.kind_label, f.stage, f.days_in_stage, t.bought_at, t.buy_price_eur, f.spent_eur,
            f.planned_eur, f.target_low_eur, f.target_high_eur,
            None if sold else f.expected_profit(low), None if sold else f.expected_profit(high),
            f.top_bid["amount_eur"] if f.top_bid else None, t.sold_at or "", t.sell_price_eur, f.profit_eur,
            f.hours, f.per_hour_eur, f.comp_words, f.sale_url, t.notes or "", f.updated_at]


def snapshot(book: fl.FlipBook) -> dict:
    names = {f.id: f.trade.title for f in book.flips}
    tasks = [k for f in book.flips for k in f.tasks + f.tools]
    loose = [k for k in book.tools if k.trade_id is None]
    t = book.totals
    totals = [["verdiend", t.realized_eur], ["verkocht", t.sold], ["omzet", t.revenue_eur],
              ["investeringen_uitgegeven", t.tools_spent_eur], ["investeringen_gepland", t.tools_planned_eur],
              ["netto", t.net_eur], ["lopend", t.stock], ["zit_erin", t.stock_spent_eur],
              ["verwachte_winst_lopend", t.stock_expected_eur], ["uren", t.hours], ["per_uur", t.per_hour_eur],
              ["gem_dagen_tot_verkoop", t.avg_days], ["bijgewerkt", fl.now_iso()]]
    return {
        "Flips": {"headers": FLIP_HEADERS, "rows": [flip_row(f) for f in book.flips]},
        "Klussen": {"headers": TASK_HEADERS, "rows": [task_row(k, names.get(k.trade_id, "")) for k in tasks]},
        "Investeringen": {"headers": TASK_HEADERS, "rows": [task_row(k) for k in loose]},
        "Totalen": {"headers": ["wat", "waarde"], "rows": totals},
    }


# --- Van de Sheet naar de database ----------------------------------------------


def _num(value) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).replace("€", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _truthy(value) -> bool:
    return _text(value).lower() in ("ja", "j", "x", "1", "true", "waar", "yes", "✓")


def task_values(row: dict, current: Optional[fl.Task]) -> dict:
    """De bewerkbare velden van een Sheet-rij, in de vorm van update_task()."""
    values = {
        "title": _text(row.get("titel")), "shop": _text(row.get("winkel")), "est_eur": _num(row.get("geschat")),
        "price_eur": _num(row.get("prijs")), "price_source": _text(row.get("bron")),
        "investment": _truthy(row.get("investering")), "fare_eur": _num(row.get("tarief")),
        "notes": _text(row.get("notitie")),
    }
    kind = _text(row.get("soort")).lower() or (current.kind if current else "onderdeel")
    if kind in fl.KINDS:
        values["kind"] = kind
    discount = _text(row.get("korting")).lower().replace("%", "")
    values["discount"] = discount if discount in fl.DISCOUNTS else (current.discount if current else "vol")
    done = _truthy(row.get("gedaan"))
    if current is None or done != current.done:
        values["done_at"] = datetime.now().date().isoformat() if done else None
    return values


def _differs(values: dict, k: fl.Task) -> bool:
    for key, value in values.items():
        if key == "done_at":
            return True
        old = getattr(k, key)
        if key == "investment":
            old, value = bool(old), bool(value)
        if (old or None) != (value or None):
            return True
    return False


def apply_tasks(conn, rows: list, book: fl.FlipBook, last: Optional[datetime], known_ids: set,
                result: Result, loose: bool) -> None:
    tasks = {k.id: k for f in book.flips for k in f.tasks + f.tools}
    tasks.update({k.id: k for k in book.tools})
    flip_ids = {f.id for f in book.flips}
    seen = set()
    for row in rows:
        ident = _num(row.get("id"))
        edited = parse_time(row.get("bijgewerkt"))
        if ident is None:
            title = _text(row.get("titel"))
            if not title:
                continue
            trade = None if loose else _num(row.get("flip"))
            trade = int(trade) if trade is not None and int(trade) in flip_ids else None
            if not loose and trade is None:
                result.overwritten.append(f"'{title}' (geen bestaande flip-id in kolom flip, niet overgenomen)")
                continue
            values = task_values(row, None)
            kind = values.pop("kind", "onderdeel")
            values.pop("title")
            if loose:
                values["investment"] = True
            values = {k: v for k, v in values.items() if v not in (None, "")}
            fl.add_task(conn, trade, kind=kind, title=title, **values)
            result.taken.append(f"nieuw: {title}")
            continue
        seen.add(int(ident))
        k = tasks.get(int(ident))
        if k is None or edited is None or (last is not None and edited <= last):
            continue
        values = task_values(row, k)
        if not values.get("title") or not _differs(values, k):
            continue
        db_time = parse_time(k.updated_at)
        if last is not None and db_time is not None and db_time > last and db_time > edited:
            result.overwritten.append(f"Sheet-wijziging aan '{k.title}' (pagina was later)")
            continue
        if last is not None and db_time is not None and db_time > last:
            result.overwritten.append(f"pagina-wijziging aan '{k.title}' (Sheet was later)")
        fl.update_task(conn, k.id, updated_at=edited.isoformat(timespec="seconds"), **values)
        result.taken.append(values["title"])
    # Weg uit de Sheet: alleen wat bij de vorige ronde in de Sheet stond,
    # en niet sindsdien op de pagina gewijzigd.
    for ident in known_ids - seen:
        k = tasks.get(ident)
        if k is None or (loose != (k.trade_id is None)):
            continue
        db_time = parse_time(k.updated_at)
        if last is not None and db_time is not None and db_time > last:
            result.overwritten.append(f"weghalen van '{k.title}' in de Sheet (pagina was later)")
            continue
        fl.delete_task(conn, ident)
        result.taken.append(f"weg: {k.title}")


def apply_flips(conn, rows: list, book: fl.FlipBook, last: Optional[datetime], result: Result) -> None:
    for row in rows:
        ident = _num(row.get("id"))
        edited = parse_time(row.get("bijgewerkt"))
        f = book.get(int(ident)) if ident is not None else None
        if f is None or edited is None or (last is not None and edited <= last):
            continue
        db_time = parse_time(f.updated_at)
        if last is not None and db_time is not None and db_time > last and db_time > edited:
            result.overwritten.append(f"Sheet-wijziging aan '{f.trade.title}' (pagina was later)")
            continue
        values = {"target_low_eur": _num(row.get("doel_laag")), "target_high_eur": _num(row.get("doel_hoog")),
                  "hours": _num(row.get("uren")), "comp_words": _text(row.get("zoekwoorden")),
                  "sale_url": _text(row.get("verkooplink")), "notes": _text(row.get("notitie"))}
        if values["sale_url"] and not values["sale_url"].startswith(("http://", "https://")):
            values["sale_url"] = f.sale_url
        changed = [k for k, v in values.items()
                   if ((getattr(f, k) if k != "notes" else f.trade.notes) or None) != (v or None)]
        stage = _text(row.get("fase")).lower().replace(" ", "_")
        if stage != f.stage and stage in fl.STAGE_LABELS and stage != "verkocht" and not f.sold:
            fl.set_stage(conn, f.id, stage)
            result.taken.append(f"{f.trade.title}: fase {fl.STAGE_LABELS[stage]}")
        if changed:
            fl.update_flip(conn, f.id, updated_at=edited.isoformat(timespec="seconds"), **values)
            result.taken.append(f"{f.trade.title}: {', '.join(changed)}")


def sync(db_path, config_path, session=None) -> Result:
    config = load_config(config_path)
    if config is None:
        raise SheetError("Nog geen Sheet gekoppeld (sheets.json ontbreekt; zie SHEETS.md).")
    state = load_state(config_path)
    last = parse_time(state.get("last_sync"))
    started = datetime.now(timezone.utc)
    pulled = _call(config, {"action": "pull"}, session).get("sheets", {})
    result = Result()
    book = fl.load_book(db_path, with_market_check=False)
    conn = db.connect(str(db_path))
    try:
        apply_tasks(conn, pulled.get("Klussen", []), book, last, set(state.get("task_ids", [])), result, loose=False)
        apply_tasks(conn, pulled.get("Investeringen", []), book, last, set(state.get("tool_ids", [])), result,
                    loose=True)
        apply_flips(conn, pulled.get("Flips", []), book, last, result)
    finally:
        conn.close()
    book = fl.load_book(db_path)
    sheets = snapshot(book)
    _call(config, {"action": "push", "sheets": sheets}, session)
    result.pushed = sum(len(s["rows"]) for s in sheets.values())
    save_state(config_path, {
        "last_sync": started.isoformat(timespec="seconds"),
        "task_ids": [r[0] for r in sheets["Klussen"]["rows"]],
        "tool_ids": [r[0] for r in sheets["Investeringen"]["rows"]],
    })
    return result


def new_secret() -> str:
    return secrets.token_urlsafe(24)


def panel(config_path) -> str:
    """Het blok onderaan /flips: de knop, of hoe je hem aanzet."""
    try:
        config = load_config(config_path)
    except SheetError as exc:
        return f"<p class='sub warn'>{esc(str(exc))}</p>"
    if config is None:
        return ("<p class='explain'>Nog niet gekoppeld. Eenmalig: maak een Google Sheet, plak "
                "<code>flips_sheets.gs</code> in Extensies → Apps Script, zet hem online als webapp, en zet de "
                "URL en de sleutel in <code>sheets.json</code>. Het stappenplan staat in <code>SHEETS.md</code>; "
                "<code>python flips_sheets.py sleutel</code> maakt een sleutel.</p>")
    state = {}
    try:
        state = json.loads(_state_path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    last = state.get("last_sync")
    status = f"laatst gelijk: {last[:16].replace('T', ' ')} UTC" if last else "nog nooit gesynchroniseerd"
    auto = "1" if config.get("auto", True) else "0"
    sheet = config.get("sheet_url")
    link = f" · <a href='{esc(sheet, quote=True)}' target='_blank' rel='noopener'>open de Sheet</a>" if sheet else ""
    return ("<div class='inline act' data-action='/flips/sync' data-item=''>"
            f"<button id='sheet-sync' data-auto='{auto}'>Nu synchroniseren</button>"
            f"<span class='muted' id='sheet-status'>{esc(status)}</span>{link}</div>"
            "<p class='explain'>Wat je in de Sheet wijzigt komt bij de volgende ronde hierheen (bij het openen van "
            "deze pagina, of met de knop); bij een conflict wint de laatste wijziging. De tabbladen Flips, "
            "Klussen, Investeringen en Totalen worden elke ronde overschreven: bouw je eigen formules en "
            "grafieken op een eigen tabblad.</p>")


def main(argv=None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Flips en een Google Sheet gelijk houden (zie SHEETS.md).")
    parser.add_argument("--db", default="koopjes.db")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "sheets.json"))
    parser.add_argument("command", choices=["sync", "sleutel"], nargs="?", default="sync")
    args = parser.parse_args(argv)
    if args.command == "sleutel":
        print(new_secret())
        return 0
    try:
        print(sync(args.db, args.config).summary())
    except SheetError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
