"""De gedeelde bouwstenen van de live pagina's van `dashboard.py --serve`:
de paden, de balk bovenaan elke pagina (site_nav), de gedeelde CSS en
JavaScript, de knopjes (act), tabellen en tegels, en het lezen van een
formulier (FormError, parse_euro, parse_day, parse_id).

Elke pagina (dashboard, racebikes, upgrade_test, flips_page, bike_page,
start_page) importeert dit bestand; dit bestand importeert geen van die
pagina's, zodat ze elkaar niet in een kring nodig hebben.
"""
from __future__ import annotations

import html
import math
import re
from datetime import date
from pathlib import Path
from typing import Optional

import markets as mk
import util

STATIC = Path(__file__).resolve().parent / "static"


def static(name: str) -> str:
    """CSS of JavaScript uit static/, één keer gelezen bij het starten en
    letterlijk in de pagina gezet: elke pagina blijft één bestand dat ook
    zonder server opent (dashboard.html)."""
    return (STATIC / name).read_text(encoding="utf-8")


esc = html.escape


def web_link(url: Optional[str]) -> str:
    """De link als hij met http(s):// begint, anders "". Links die de
    eigenaar zelf invult (Mijn flips, /flips, en via de Google Sheet die in
    twee richtingen gaat) komen in een href; "javascript:..." zou daar code
    worden op een pagina met het token."""
    return url if url and re.match(r"https?://", url, re.I) else ""


MONTHS = ("jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec")


def nl_date(value: Optional[str]) -> str:
    day = util.parse_day(value)
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}" if day else (value or "?")


def thumb(listing) -> str:
    url = (listing.image_urls or "").split()
    if not url:
        return "<div class='thumb empty' aria-hidden='true'></div>"
    return (f"<a href='{esc(listing.url, quote=True)}' target='_blank' rel='noopener'>"
            f"<img class='thumb' src='{esc(url[0], quote=True)}' alt='' loading='lazy'></a>")


def act(action: str, item_id: str, inner: str, cls: str = "") -> str:
    """Knoppen (en invulvelden) die iets versturen, zonder <form>: de pagina
    had er drie per advertentie, en een browser doet met ~7400 formulieren
    op de horlogepagina tot twintig seconden over het laden (gemeten in
    Chromium, 29-09-2026; zonder formulieren 2,5 s). De klik gaat via de
    JavaScript onderaan (LIVE_JS), met het geheim en de markt uit <main>;
    de server krijgt dezelfde velden als van een formulier. Een knop met
    een eigen data-action (controleer) gaat daarheen."""
    return (f"<div class='inline act{f' {cls}' if cls else ''}' data-action='{action}' "
            f"data-item='{esc(item_id, quote=True)}'>{inner}</div>")


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


CSS = static("pagina.css")


JS = static("pagina.js")


# Gedeeld door alle live pagina's: een formulier versturen zonder te
# herladen, en de melding onderin in plaats van bovenaan een nieuwe pagina.
LIVE_JS = static("live.js")


# De live pagina's. Hier en niet bij elke pagina: de balk bovenaan
# (site_nav) linkt naar allemaal, en zo hoeft dit bestand geen pagina te
# importeren.
START_PATH = "/start"
FILES_PATH = "/bestanden"
RACEBIKES_PATH = "/racefietsen"
BIKE_PATH = "/fiets"
UPGRADE_PATH = "/upgrade"
FLIPS_PATH = "/flips"


def site_pages() -> list:
    return ([("Start", START_PATH), ("Racefietsen", RACEBIKES_PATH)] + [(m.short, m.serve_path) for m in mk.MARKETS.values()]
            + [("Mijn fiets", BIKE_PATH), ("Upgrade", UPGRADE_PATH), ("Flips", FLIPS_PATH),
               ("Overzicht", f"{FILES_PATH}/overzicht.html")])


def site_nav(current: str) -> str:
    """De balk bovenaan elke live pagina. Op de telefoon ingeklapt tot één
    knop met de naam van de pagina (SITE_CSS; een vinkje, geen JavaScript):
    zeven links op een rij namen daar drie regels voor de inhoud weg."""
    pages = site_pages()
    here = next((label for label, href in pages if href == current), "Menu")
    links = "".join(
        f"<a href='{esc(href, quote=True)}'{' aria-current=page' if href == current else ''}>{esc(label)}</a>"
        for label, href in pages)
    return (f"<nav class='site'><input type='checkbox' id='site-open' class='site-open' hidden>"
            f"<label for='site-open' class='site-menu'>☰ {esc(here)}</label>"
            f"<div class='site-links'>{links}</div></nav>")


SITE_CSS = static("balk.css")


class FormError(ValueError):
    """Een formulier met iets dat niet klopt; de tekst gaat terug naar de pagina."""


def parse_euro(value: str, what: str, required: bool = True) -> Optional[float]:
    text = (value or "").replace("€", "").replace(" ", "").replace(",", ".")
    if not text:
        if required:
            raise FormError(f"{what} ontbreekt.")
        return None
    try:
        amount = float(text)
    except ValueError:
        raise FormError(f"{what} '{value}' is geen bedrag.") from None
    if not math.isfinite(amount):  # "1e309" en "nan" zijn voor float() ook getallen
        raise FormError(f"{what} '{value}' is geen bedrag.")
    if amount < 0:
        raise FormError(f"{what} kan niet negatief zijn.")
    return round(amount, 2)


def parse_day(value: str) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise FormError(f"Datum '{value}' klopt niet (jjjj-mm-dd).") from None


def parse_id(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise FormError("Onbekende regel.") from None
