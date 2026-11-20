"""De flippagina `/flips` van `dashboard.py --serve`: elke eigen flip als
kaart (fase, klussen, onderdelen en aanbiedingen, foto's, biedingen van
kopers, verkoop), de totalen bovenaan, en de acties achter de knoppen
(FLIP_ACTIONS). Het rekenwerk staat in flips.py; dit bestand maakt er HTML
van. Alleen live: zonder knoppen is een afvinklijst niets waard.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

import db
import flips as fl
import flips_sheets as fs
import markets as mk
import pages as pg
import trades as tr
from util import euro, local_time
import views as vw


FLIPS_PHOTO_PATH = "/flips/foto"
# De sleutel van de Google Sheet (SHEETS.md); niet in git.
SHEETS_CONFIG = str(Path(__file__).resolve().parent / "sheets.json")


def flip_input(name: str, value, label: str, size: int = 6, kind: str = "text", placeholder: str = "") -> str:
    shown = "" if value is None else (f"{value:.2f}".replace(".", ",") if isinstance(value, float) else str(value))
    mode = " inputmode='decimal'" if kind == "euro" else ""
    typ = "date" if kind == "date" else "text"
    ph = f" placeholder='{pg.esc(placeholder, quote=True)}'" if placeholder else ""
    return (f"<input type='{typ}' name='{name}' value='{pg.esc(shown, quote=True)}' size='{size}'{mode}{ph} "
            f"aria-label='{pg.esc(label, quote=True)}'>")


def flip_select(name: str, options, chosen: str, label: str) -> str:
    opts = "".join(f"<option value='{pg.esc(k, quote=True)}'{' selected' if k == chosen else ''}>{pg.esc(v)}</option>"
                   for k, v in options)
    return f"<select name='{name}' aria-label='{pg.esc(label, quote=True)}'>{opts}</select>"


def flip_totals(book: fl.FlipBook) -> str:
    t = book.totals
    hours = (f"{euro(t.per_hour_eur, cents=True)} per uur over {t.hours:g} uur" if t.per_hour_eur is not None
             else (f"{t.hours:g} uur gewerkt" if t.hours else "vul per flip je uren in"))
    tools = f"{euro(t.tools_spent_eur, cents=True)} uitgegeven"
    if t.tools_planned_eur:
        tools += f", {euro(t.tools_planned_eur, cents=True)} nog gepland"
    return pg.tiles([
        ("Verdiend", euro(t.realized_eur, cents=True, sign=True) if t.sold else "—",
         f"{t.sold} verkocht, {euro(t.revenue_eur, cents=True)} omzet" if t.sold else "nog niets verkocht"),
        ("Netto na investeringen", euro(t.net_eur, cents=True, sign=True), "verdiend min gereedschap en voorraad"),
        ("Zit erin", euro(t.stock_spent_eur, cents=True), f"{t.stock} lopende flip{'s' if t.stock != 1 else ''}"),
        ("Verwachte winst lopend", euro(t.stock_expected_eur, cents=True, sign=True), "op het midden van je doelprijs"),
        ("Investeringen", euro(t.tools_spent_eur + t.tools_planned_eur, cents=True), tools),
        ("Tijd", f"{t.avg_days:.0f} dagen" if t.avg_days is not None else "—",
         "gemiddeld van kopen tot verkopen · " + hours),
    ])


def flip_task_row(k: fl.Task) -> str:
    """Eén regel van de klussenlijst: afvinken, de echte prijs, en wat erbij hoort."""
    item = str(k.id)
    done = "on" if k.done else ""
    check = pg.act("/flips/klus", item, f"<button class='quiet tick {done}' name='doe' value='gedaan' "
                                     f"aria-pressed='{'true' if k.done else 'false'}' title='gedaan'>✓</button>")
    facts = []
    if k.shop:
        facts.append(pg.esc(k.shop))
    if k.price_source in fl.SOURCES:
        facts.append(f"<span class='badge{' est' if k.price_source == 'schatting' else ''}'>"
                     f"{pg.esc(fl.SOURCES[k.price_source])}</span>")
    if pg.web_link(k.url):
        facts.append(f"<a href='{pg.esc(pg.web_link(k.url), quote=True)}' target='_blank' rel='noopener'>link</a>")
    if k.notes:
        facts.append(pg.esc(k.notes))
    offers = flip_offers(k) if k.kind == "onderdeel" else ""
    status = {"gedaan": "gedaan", "gekocht": "gekocht, nog niet gemonteerd", "open": ""}[k.status]
    if k.kind == "onderdeel" and k.status == "open" and k.est_eur is not None:
        status = "nog kopen"
    if k.investment and k.trade_id is None:
        # Gereedschap wordt niet "gedaan": je hebt het, of nog niet.
        status = "in bezit" if k.bought else "nog kopen"
        check = ""
    if status:
        facts.insert(0, f"<strong>{pg.esc(status)}</strong>")
    what = (f"<div class='{'struck' if k.done else ''}'>{pg.esc(k.title)}</div>"
            f"<div class='note'>{' · '.join(facts)}</div>{offers}")
    if k.kind == "reis":
        cost = (flip_input("tarief", k.fare_eur, "Vol tarief", 5, "euro", "vol tarief")
                + flip_select("korting", fl.DISCOUNT_LABELS.items(), k.discount or "vol", "Korting")
                + "<button class='quiet' name='doe' value='prijs'>opslaan</button>")
        money = (f"<td class='num'>{euro(k.cost_eur, cents=True)}"
                 f"<div class='sub'>{pg.esc(fl.DISCOUNT_LABELS.get(k.discount or 'vol', ''))}</div></td>")
    elif k.kind == "klus" and k.price_eur is None:
        # Een klus kost meestal niets; wie er toch iets voor betaalde kan
        # het als onderdeel toevoegen.
        cost = ""
        money = "<td></td>"
    else:
        cost = (flip_input("prijs", k.price_eur, "Echte prijs", 5, "euro", "echte prijs")
                + "<button class='quiet' name='doe' value='prijs'>opslaan</button>")
        est = (f"<div class='sub{' struck' if k.cost_eur is not None else ''}'>geschat "
               f"{euro(k.est_eur, cents=True)}</div>") if k.est_eur is not None else ""
        money = (f"<td class='num'>{euro(k.cost_eur, cents=True) if k.cost_eur is not None else ''}"
                 f"{'' if k.cost_eur is not None else ('<span class=muted>' + euro(k.est_eur, cents=True) + '</span>' if k.est_eur is not None else '')}"
                 f"{est if k.cost_eur is not None else ''}</td>")
    # Losse investeringen horen bij geen flip: "naar flip" kan daar niet.
    toggle = "" if k.trade_id is None else (
               f"<button class='quiet' name='doe' value='investering' title='{'terug naar de kosten van de flip' if k.investment else 'gereedschap: telt niet bij deze flip, wel bij de investeringen'}'>"
               f"{'naar flip' if k.investment else 'gereedschap'}</button>")
    menu = pg.act("/flips/klus", item, toggle + "<button class='quiet' name='doe' value='weg'>weg</button>", "menu")
    return (f"<tr data-task='{item}' class='{k.status}'><td class='tickcell'>{check}</td>"
            f"<td class='what'>{what}</td>{money}<td>{pg.act('/flips/klus', item, cost) if cost else ''}</td><td>{menu}</td></tr>")


def flip_offers(k: fl.Task) -> str:
    """Aanbiedingen bij een onderdeel (flip_offer): de links die je plakte met
    de prijs die je zag, goedkoopste (met verzending) eerst, met "kies deze"
    en weg; een nieuwe toevoegen; en winkel en link van de regel zelf."""
    items = []
    for o in k.offers:
        chosen = (o.url == k.url) if o.url else (o.shop == k.shop and o.total_eur == k.est_eur)
        link = (f"<a href='{pg.esc(pg.web_link(o.url), quote=True)}' target='_blank' rel='noopener'>{pg.esc(o.domain)}</a>"
                if pg.web_link(o.url)
                else "<span class='badge est'>geen link</span>")
        ship = (f" + {euro(o.shipping_eur, cents=True)} verzending = {euro(o.total_eur, cents=True)}" if o.shipping_eur
                else (" incl. verzending" if o.shipping_eur == 0 else ""))
        source = " <span class='badge est'>schatting</span>" if o.source == "schatting" else ""
        extra = " · ".join(x for x in (pg.esc(o.note), f"bekeken {pg.esc(pg.nl_date(o.checked_at))}" if o.checked_at else "") if x)
        pick = ("<span class='badge'>gekozen</span>" if chosen
                else pg.act("/flips/aanbod-kies", str(o.id), "<button class='quiet'>kies deze</button>", "tiny"))
        items.append(f"<li><strong>{euro(o.price_eur, cents=True)}</strong>{ship} · {pg.esc(o.shop or '')} {link}{source} "
                     f"<span class='muted'>{extra}</span> {pick}"
                     f"{pg.act('/flips/aanbod-weg', str(o.id), '<button class=quiet>weg</button>', 'tiny')}</li>")
    add = pg.act("/flips/aanbod", str(k.id),
              flip_input("link", "", "Link plakken", 26, placeholder="link plakken")
              + flip_input("prijs", "", "Prijs", 5, "euro", "prijs €")
              + flip_input("verzending", "", "Verzending", 5, "euro", "verzending €")
              + flip_input("winkel", "", "Winkel", 10, placeholder="winkel (uit de link)")
              + flip_input("notitie", "", "Notitie", 16, placeholder="notitie, bv. variant")
              + "<button>toevoegen</button>", "addoffer")
    own = pg.act("/flips/klus", str(k.id),
              "<span class='sub'>deze regel:</span>"
              + flip_input("winkel", k.shop, "Winkel van deze regel", 10, placeholder="winkel")
              + flip_input("url", k.url, "Link van deze regel", 26, placeholder="link")
              + "<button class='quiet' name='doe' value='winkel'>opslaan</button>", "addoffer")
    empty = "<li class='muted'>nog geen — plak een link met de prijs die je zag</li>"
    return (f"<details class='offers'><summary>Aanbiedingen ({len(k.offers)})</summary>"
            f"<ul>{''.join(items) or empty}</ul>{add}{own}</details>")


def flip_task_table(tasks: list, table_id: str = "") -> str:
    if not tasks:
        return "<p class='empty'>Nog niets op de lijst.</p>"
    order = {"reis": 0, "onderdeel": 1, "klus": 2}
    rows = [flip_task_row(k) for k in sorted(tasks, key=lambda k: (k.done, order.get(k.kind, 3), k.position))]
    ident = f" id='{table_id}'" if table_id else ""
    return (f"<div class='table-wrap'><table class='tasks'{ident}><thead><tr><th></th><th>Wat</th>"
            "<th class='num'>Kost</th><th>Echte prijs</th><th></th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def flip_add_task(trade_id: Optional[int], investment: bool = False) -> str:
    kinds = [("onderdeel", "onderdeel"), ("klus", "klus"), ("reis", "reis (OV)")]
    inner = (flip_select("soort", kinds, "onderdeel", "Soort")
             + flip_input("titel", "", "Wat", 26, placeholder="wat")
             + flip_input("winkel", "", "Winkel", 10, placeholder="winkel")
             + flip_input("geschat", "", "Geschatte prijs", 5, "euro", "geschat €")
             + flip_input("prijs", "", "Echte prijs", 5, "euro", "echt €")
             + ("<input type='hidden' name='investering' value='1'>" if investment else "")
             + "<button name='doe' value='nieuw'>toevoegen</button>")
    return pg.act("/flips/klus-nieuw", "" if trade_id is None else str(trade_id), inner, "addtask")


def flip_basket(tasks: list) -> str:
    groups = fl.basket(tasks)
    if not groups:
        return "<p class='empty'>Alles gekocht.</p>"
    out = []
    for shop, items, subtotal, short in groups:
        warn = (f"<div class='sub warn'>nog {euro(short, cents=True)} tot gratis verzending</div>" if short is not None
                else "")
        names = "".join(f"<li>{pg.esc(k.title)} <span class='muted'>{euro(k.est_eur, cents=True)}</span></li>" for k in items)
        out.append(f"<div class='shop'><div class='model'>{pg.esc(shop)} · {euro(subtotal, cents=True)}</div>{warn}"
                   f"<ul>{names}</ul></div>")
    return "<div class='shops'>" + "".join(out) + "</div>"


def flip_stage_buttons(f: fl.Flip) -> str:
    buttons = "".join(
        f"<button class='quiet{' on' if f.stage == key else ''}' name='fase' value='{key}'>{pg.esc(label)}</button>"
        for key, label in fl.STAGES if key != "verkocht")
    return pg.act("/flips/fase", str(f.id), buttons, "stages")


def flip_money_grid(f: fl.Flip) -> str:
    t = f.trade
    low, high = f.target
    cells = [("Inkoop", euro(t.buy_price_eur, cents=True), f"+ {euro(t.buy_costs_eur, cents=True)} kosten" if t.buy_costs_eur else "")]
    extra = round(f.spent_eur - t.cost_basis_eur, 2)
    cells.append(("Uitgegeven", euro(f.spent_eur, cents=True), f"waarvan {euro(extra, cents=True)} aan de lijst" if extra else ""))
    if not f.sold:
        cells.append(("Nog gepland", euro(f.planned_eur, cents=True), "schattingen, tot je de echte prijs invult"))
        cells.append(("Kostprijs verwacht", euro(f.expected_cost_eur, cents=True), ""))
        target = (euro(low, cents=True) if low == high else f"{euro(low, cents=True)} – {euro(high, cents=True)}") if low is not None else "—"
        cells.append(("Doelprijs", target, "wat je wilt ontvangen"))
        mc = f.market_check
        if mc is not None:
            if mc.n:
                cells.append(("Marktcheck", euro(mc.median_eur, cents=True),
                              f"mediaan vraagprijs van {mc.n} advertenties met '{mc.words}'"
                              + (f", midden 50%: {euro(mc.low_eur, cents=True)} – {euro(mc.high_eur, cents=True)}"
                                 if mc.n >= 4 else "")))
            else:
                cells.append(("Marktcheck", "—", f"geen advertenties met '{mc.words}' in de laatste 180 dagen"))
        if low is not None:
            pl, ph = f.expected_profit(low), f.expected_profit(high)
            profit = euro(pl, cents=True, sign=True) if low == high else f"{euro(pl, cents=True, sign=True)} – {euro(ph, cents=True, sign=True)}"
            cells.append(("Verwachte winst", profit, "doelprijs min verwachte kostprijs"))
        top = f.top_bid
        if top is not None:
            cells.append(("Hoogste bod", euro(top["amount_eur"], cents=True),
                          f"winst bij dat bod {euro(f.expected_profit(top['amount_eur']), cents=True, sign=True)}"))
    else:
        cells.append(("Verkocht voor", euro(t.sell_price_eur, cents=True),
                      f"− {euro(t.sell_costs_eur, cents=True)} kosten" if t.sell_costs_eur else pg.esc(t.sold_via or "")))
        cells.append(("Winst", euro(f.profit_eur, cents=True, sign=True), f"in {t.days_held()} dagen"))
    if f.hours:
        cells.append(("Uren", f"{f.hours:g}", f"{euro(f.per_hour_eur, cents=True)} per uur" if f.per_hour_eur is not None else ""))
    return "<div class='money'>" + "".join(
        f"<div><div class='label'>{pg.esc(a)}</div><div class='value'>{b}</div><div class='sub'>{pg.esc(c)}</div></div>"
        for a, b, c in cells) + "</div>"


def flip_progress(f: fl.Flip) -> str:
    total = len(f.tasks)
    if not total:
        return ""
    done = sum(1 for k in f.tasks if k.done)
    pct = round(100 * done / total)
    return (f"<div class='progress' title='{done} van {total} gedaan'><div style='width:{pct}%'></div></div>"
            f"<div class='sub'>{done} van {total} gedaan</div>")


def flip_specs(f: fl.Flip) -> str:
    fields = "".join(f"<label>{pg.esc(label)}{flip_input('spec_' + key, f.specs.get(key, ''), label, 22)}</label>"
                     for key, label in fl.SPEC_FIELDS)
    form = pg.act("/flips/gegevens", str(f.id), fields + "<button name='doe' value='specs'>opslaan</button>", "specform")
    draft = pg.esc(fl.ad_draft(f))
    return (f"{form}<h4>Concept voor je advertentie</h4>"
            f"<textarea class='draft' rows='8' readonly>{draft}</textarea>"
            "<div class='inline'><button class='quiet copy'>kopiëren</button>"
            "<span class='muted'>Je plaatst hem zelf; hier gaat niets naar Marktplaats.</span></div>")


def flip_details_form(f: fl.Flip) -> str:
    t = f.trade
    inner = (f"<label>Titel{flip_input('titel', t.title, 'Titel', 28)}</label>"
             f"<label>Inkoop €{flip_input('inkoop', t.buy_price_eur, 'Inkoop', 6, 'euro')}</label>"
             f"<label>Inkoopkosten €{flip_input('inkoopkosten', t.buy_costs_eur or None, 'Inkoopkosten', 5, 'euro')}</label>"
             f"<label>Doel laag €{flip_input('doel_laag', f.target_low_eur, 'Doelprijs laag', 6, 'euro')}</label>"
             f"<label>Doel hoog €{flip_input('doel_hoog', f.target_high_eur, 'Doelprijs hoog', 6, 'euro')}</label>"
             f"<label>Uren{flip_input('uren', f.hours, 'Uren', 4, 'euro')}</label>"
             f"<label>Zoekwoorden marktcheck{flip_input('zoekwoorden', f.comp_words, 'Zoekwoorden', 16)}</label>"
             f"<label>Jouw advertentie (link){flip_input('verkooplink', f.sale_url, 'Verkooplink', 28)}</label>"
             f"<label>Notitie{flip_input('notitie', t.notes or '', 'Notitie', 28)}</label>"
             "<button name='doe' value='gegevens'>opslaan</button>")
    return pg.act("/flips/gegevens", str(f.id), inner, "specform")


def flip_sale(f: fl.Flip) -> str:
    bids = "".join(
        f"<li>{euro(b['amount_eur'], cents=True)} <span class='muted'>{pg.esc(local_time(b['at']))}"
        f"{' · ' + pg.esc(b['note']) if b['note'] else ''}</span> "
        f"{pg.act('/flips/bod-weg', str(b['id']), '<button class=quiet>weg</button>', 'tiny')}</li>"
        for b in f.bids)
    add_bid = pg.act("/flips/bod", str(f.id),
                  flip_input("bedrag", "", "Bod", 6, "euro", "bod €") + flip_input("wie", "", "Van wie / notitie", 18,
                                                                                  placeholder="van wie, notitie")
                  + "<button>bod noteren</button>")
    today = date.today().isoformat()
    guess = f.top_bid["amount_eur"] if f.top_bid else f.target_mid_eur
    sell = pg.act("/flips/verkocht", str(f.id),
               flip_input("prijs", guess, "Verkoopprijs", 6, "euro", "verkoopprijs")
               + flip_input("kosten", None, "Verkoopkosten", 4, "euro", "kosten")
               + f"<input type='date' name='datum' value='{today}' aria-label='Verkocht op'>"
               + flip_select("via", [("marktplaats", "marktplaats"), ("vinted", "vinted"), ("anders", "anders")],
                             "marktplaats", "Verkocht via")
               + "<button>verkocht</button>")
    return (f"<h4>Biedingen op je advertentie</h4><ul class='bids'>{bids or '<li class=muted>nog geen</li>'}</ul>"
            f"{add_bid}<h4>Verkocht?</h4>{sell}")


def flip_photos(f: fl.Flip) -> str:
    pics = "".join(
        f"<figure><a href='{FLIPS_PHOTO_PATH}/{p['id']}' target='_blank'><img src='{FLIPS_PHOTO_PATH}/{p['id']}' "
        f"alt='' loading='lazy'></a><figcaption>{pg.esc(p['kind'])} "
        f"{pg.act('/flips/foto-weg', str(p['id']), '<button class=quiet>weg</button>', 'tiny')}</figcaption></figure>"
        for p in f.photos)
    upload = (f"<div class='inline upload' data-flip='{f.id}'>"
              "<select aria-label='Voor of na'><option value='voor'>voor</option><option value='na'>na</option></select>"
              "<input type='file' accept='image/*' multiple aria-label='Foto'></div>")
    empty = "<p class='empty'>Nog geen foto's.</p>"
    return f"<div class='photos'>{pics or empty}</div>{upload}"


def flip_card(f: fl.Flip) -> str:
    t = f.trade
    days = f.days_in_stage
    since = f" · {days} dag{'en' if days != 1 else ''}" if days is not None else ""
    links = []
    if pg.web_link(t.url):
        links.append(f"<a href='{pg.esc(pg.web_link(t.url), quote=True)}' target='_blank' rel='noopener'>"
                     "gekocht via deze advertentie</a>")
    if pg.web_link(f.sale_url):
        links.append(f"<a href='{pg.esc(pg.web_link(f.sale_url), quote=True)}' target='_blank' rel='noopener'>"
                     "jouw advertentie</a>")
    meta = [pg.esc(f.kind_label), f"gekocht {pg.esc(pg.nl_date(t.bought_at))}", *links]
    views_html = flip_views(f)
    cover = next((p for p in reversed(f.photos) if p["kind"] == "na"), f.photos[0] if f.photos else None)
    img = (f"<img class='cover' src='{FLIPS_PHOTO_PATH}/{cover['id']}' alt=''>" if cover else "")
    open_list = " open" if f.stage in ("gekocht", "opknappen") else ""
    open_sale = " open" if f.stage == "te_koop" else ""
    tasks = f.tasks + f.tools
    body = ""
    if not f.sold:
        body = (
            f"{flip_stage_buttons(f)}"
            f"<details{open_list}><summary>Klussenlijst ({sum(1 for k in f.tasks if k.done)}/{len(f.tasks)})</summary>"
            f"{flip_task_table(tasks)}{flip_add_task(f.id)}</details>"
            f"<details><summary>Winkelmandje</summary>{flip_basket(tasks)}</details>"
            f"<details><summary>Specs en advertentietekst</summary>{flip_specs(f)}</details>"
            f"<details><summary>Foto's ({len(f.photos)})</summary>{flip_photos(f)}</details>"
            f"<details{open_sale}><summary>Verkoop</summary>{flip_sale(f)}</details>"
            f"<details><summary>Gegevens</summary>{flip_details_form(f)}</details>"
        )
    else:
        body = (f"<details><summary>Klussenlijst ({len(f.tasks)})</summary>{flip_task_table(tasks)}</details>"
                f"<details><summary>Foto's ({len(f.photos)})</summary>{flip_photos(f)}</details>"
                + pg.act("/flips/fase", str(f.id), "<button class='quiet' name='fase' value='te_koop'>"
                                                "verkoop ongedaan maken</button>"))
    delete = pg.act("/flips/weg", str(f.id), "<button class='quiet' name='doe' value='weg'>flip verwijderen</button>",
                 "tiny right")
    return (
        f"<section class='flipcard stage-{f.stage}' id='flip-{f.id}' data-flip='{f.id}'>"
        f"<header>{img}<div><h2>{pg.esc(t.title)}</h2>"
        f"<div class='meta'><span class='pill'>{pg.esc(fl.STAGE_LABELS[f.stage])}{since}</span> "
        f"{' · '.join(meta)}</div>"
        f"{'<div class=note>' + pg.esc(t.notes) + '</div>' if t.notes else ''}{views_html}</div></header>"
        f"{flip_money_grid(f)}{flip_progress(f)}{body}{delete}</section>"
    )


def flip_views(f: fl.Flip) -> str:
    """Weergaven en likes van jouw advertentie, met het verloop als lijntje
    (views.py meet hem elke 6 uur zolang hij te koop staat)."""
    if not f.views:
        if f.stage == "te_koop" and f.sale_url and "marktplaats.nl" in f.sale_url:
            return "<div class='note'>Weergaven en likes: de eerstvolgende ronde meet ze.</div>"
        return ""
    latest = vw.latest(f.views)
    first = f.views[0]
    grew = ""
    if len(f.views) > 1 and latest.views is not None and first.get("views") is not None:
        grew = (f" · sinds {pg.nl_date(first['observed_at'])}: +{latest.views - first['views']} bekeken, "
                f"+{(latest.favorites or 0) - (first.get('favorites') or 0)} bewaard")
    lines = (vw.sparkline([o.get("views") for o in f.views], color="var(--accent)")
             + vw.sparkline([o.get("favorites") for o in f.views], color="var(--good)"))
    legend = "<span class='sub'>blauw bekeken, groen bewaard</span>" if lines else ""
    return (f"<div class='note'>{pg.esc(latest.label)} (gemeten {pg.esc(pg.nl_date(latest.observed_at))}){pg.esc(grew)}</div>"
            f"<div class='sparks'>{lines}{legend}</div>")


def flip_stock_row(f: fl.Flip) -> str:
    t = f.trade
    buttons = ("<button name='fase' value='te_koop'>flippen</button>"
               "<button class='quiet' name='fase' value='opknappen'>eerst opknappen</button>")
    note = f"<div class='note'>{pg.esc(t.notes)}</div>" if t.notes else ""
    return (f"<tr data-flip='{f.id}'><td class='what'>{pg.esc(t.title)}{note}</td>"
            f"<td class='num'>{euro(t.cost_basis_eur, cents=True)}</td>"
            f"<td>{pg.act('/flips/fase', str(f.id), buttons)}</td>"
            f"<td>{pg.act('/flips/weg', str(f.id), '<button class=quiet name=doe value=weg>weg</button>')}</td></tr>")


def flip_tools(book: fl.FlipBook) -> str:
    loose = [k for k in book.tools if k.trade_id is None]
    on_flips = [k for k in book.tools if k.trade_id is not None]
    t = book.totals
    head = (f"<p class='explain'>Gereedschap en spullen die je bij meer dan één flip gebruikt. Ze tellen niet "
            f"mee in de winst van één flip, wel in <em>Netto na investeringen</em>: "
            f"{euro(t.tools_spent_eur, cents=True)} uitgegeven"
            + (f", {euro(t.tools_planned_eur, cents=True)} nog te kopen" if t.tools_planned_eur else "") + ".</p>")
    extra = ""
    if on_flips:
        extra = (f"<p class='muted'>Plus {len(on_flips)} regel{'s' if len(on_flips) != 1 else ''} die op de "
                 "lijst van een flip staan en als gereedschap gemarkeerd zijn (daar te zien).</p>")
    return (head + flip_task_table(loose, "tools-table") + flip_add_task(None, investment=True)
            + f"<details><summary>Winkelmandje investeringen</summary>{flip_basket(loose)}</details>" + extra)


def flip_new_form() -> str:
    today = date.today().isoformat()
    kinds = [("fietsen", "fiets"), ("spullen", "spullen"), ("fietscomputers", "fietscomputer"),
             ("sporthorloges", "sporthorloge")]
    stages = [(k, v) for k, v in fl.STAGES if k != "verkocht"]
    return ("<form class='addform' method='post' action='/flips/nieuw'>"
            "<input type='hidden' name='token' value='TOKEN'>"
            "<label>Wat<input name='titel' required placeholder='merk, model, maat'></label>"
            f"<label>Soort{flip_select('markt', kinds, 'fietsen', 'Soort')}</label>"
            "<label>Inkoop €<input name='prijs' inputmode='decimal' size='6' required></label>"
            f"<label>Gekocht op<input type='date' name='datum' value='{today}'></label>"
            f"<label>Fase{flip_select('fase', stages, 'gekocht', 'Fase')}</label>"
            "<label>Doel laag €<input name='doel_laag' inputmode='decimal' size='5'></label>"
            "<label>Doel hoog €<input name='doel_hoog' inputmode='decimal' size='5'></label>"
            "<label>Link advertentie<input name='url' size='24'></label>"
            "<label>Zoekwoorden marktcheck<input name='zoekwoorden' size='14' placeholder='bijv. cube peloton'></label>"
            "<button>Toevoegen</button></form>")


def render_flips(book: fl.FlipBook, token: str = "", message: str = "", other_links: Sequence = (),
                 sheets: str = "") -> str:
    links = "".join(f" · <a href='{pg.esc(href, quote=True)}'>{pg.esc(label)}</a>" for label, href in other_links)
    running = [f for key in ("te_koop", "opknappen", "gekocht") for f in book.by_stage(key)]
    stock = book.by_stage("voorraad")
    sold = sorted(book.by_stage("verkocht"), key=lambda f: f.trade.sold_at or "", reverse=True)
    parts = [f"<div id='flip-totals'>{flip_totals(book)}</div>"]
    parts.append(f"<h3>Lopend ({len(running)})</h3>")
    parts.append("".join(flip_card(f) for f in running) or
                 "<p class='empty'>Geen lopende flips. Voeg er onderaan een toe, of zet iets uit je voorraad te koop.</p>")
    parts.append(f"<h3>Voorraad ({len(stock)})</h3><p class='explain'>Spullen die je hebt en zou kunnen verkopen. "
                 "<em>Flippen</em> zet ze te koop; dan krijgen ze een eigen kaart.</p>")
    if stock:
        parts.append(f"<div class='table-wrap'><table><thead><tr><th>Wat</th><th class='num'>Inkoop</th><th></th>"
                     f"<th></th></tr></thead><tbody>{''.join(flip_stock_row(f) for f in stock)}</tbody></table></div>")
    else:
        parts.append("<p class='empty'>Niets op voorraad.</p>")
    parts.append(f"<h3>Verkocht ({len(sold)})</h3>")
    parts.append("".join(flip_card(f) for f in sold) or "<p class='empty'>Nog niets verkocht.</p>")
    parts.append(f"<h3>Investeringen</h3><div id='flip-tools'>{flip_tools(book)}</div>")
    parts.append("<h3>Nieuwe flip</h3>" + flip_new_form().replace("TOKEN", pg.esc(token, quote=True)))
    if sheets:
        parts.append(f"<h3>Google Sheets</h3>{sheets}")
    notice = f"<div class='banner' role='status'>{pg.esc(message)}</div>" if message else ""
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Flips</title><style>{pg.CSS}{FLIPS_CSS}{pg.SITE_CSS}</style></head><body>"
        f"<main data-token='{pg.esc(token, quote=True)}'>{pg.site_nav(pg.FLIPS_PATH)}"
        "<h1>Flips</h1>"
        f"<div class='meta'>Alles wat je kocht om te verkopen{links} · <strong>live</strong> (gaat in koopjes.db)</div>"
        f"{notice}{''.join(parts)}"
        f"</main><div id='toast' role='status' hidden></div><script>{pg.LIVE_JS}{pg.JS}{FLIPS_JS}</script></body></html>"
    )


FLIPS_CSS = """
.sparks { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; margin-top: 4px; }
.flipcard { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px;
  margin: 0 0 16px; }
.flipcard.stage-verkocht { opacity: .92; }
.flipcard header { display: flex; gap: 14px; align-items: flex-start; }
.flipcard h2 { font-size: 1.2rem; margin: 0 0 2px; }
.flipcard .meta { margin-bottom: 6px; }
img.cover { width: 96px; height: 72px; object-fit: cover; border-radius: 8px; }
.pill { display: inline-block; font-size: .78rem; font-weight: 700; padding: 1px 8px; border-radius: 10px;
  background: var(--badge); color: var(--text); }
.stage-te_koop .pill { background: var(--fav); }
.stage-verkocht .pill { background: var(--good); color: #fff; }
.money { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px 14px; margin: 10px 0; }
.money .label { font-size: .78rem; color: var(--text-2); }
.money .value { font-size: 1.15rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.progress { height: 8px; background: var(--line); border-radius: 4px; overflow: hidden; margin-top: 4px; }
.progress div { height: 100%; background: var(--good); }
.flipcard details { border-top: 1px solid var(--line); padding: 6px 0; }
.flipcard details > summary { cursor: pointer; font-weight: 600; padding: 4px 0; }
.flipcard h4 { font-size: .9rem; margin: 12px 0 4px; }
table.tasks td { padding: 6px 8px; }
table.tasks td.tickcell { width: 40px; }
button.tick { width: 30px; height: 30px; padding: 0; font-weight: 700; }
button.tick.on { background: var(--good); border-color: var(--good); color: #fff; }
tr.gedaan .what { color: var(--muted); }
.struck { text-decoration: line-through; }
.badge.est { background: var(--line); color: var(--text-2); }
.act.menu { flex-wrap: nowrap; margin: 0; }
.act.menu button { font-size: .75rem; padding: 2px 7px; white-space: nowrap; }
table.tasks .act { margin-top: 0; }
.act.tiny { display: inline-flex; margin: 0; }
.act.tiny button { font-size: .72rem; padding: 0 6px; }
.act.right { justify-content: flex-end; }
.act.stages button { font-size: .8rem; }
.act.addtask, .act.specform { margin-top: 10px; }
.act.specform label { display: flex; flex-direction: column; font-size: .78rem; color: var(--text-2); gap: 2px; }
.shops { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
.shop { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: .88rem; }
.shop ul { margin: 4px 0 0; padding-left: 18px; }
textarea.draft { width: 100%; font: inherit; font-size: .88rem; padding: 8px; border: 1px solid var(--line);
  border-radius: 8px; background: var(--surface); color: var(--text); }
.photos { display: flex; flex-wrap: wrap; gap: 8px; }
.photos figure { margin: 0; }
.photos img { width: 140px; height: 105px; object-fit: cover; border-radius: 8px; display: block; }
.photos figcaption { font-size: .75rem; color: var(--muted); display: flex; gap: 6px; align-items: center; }
ul.bids { margin: 0; padding-left: 18px; }
.flipcard details.offers, #flip-tools details.offers { border-top: 0; padding: 2px 0 0; }
details.offers > summary { font-weight: 400; font-size: .8rem; color: var(--text-2); }
details.offers ul { margin: 4px 0; padding-left: 18px; font-size: .85rem; }
details.offers li { margin: 2px 0; }
.act.addoffer { margin-top: 4px; }
.act.addoffer input { font-size: .82rem; }
@media (max-width: 640px) {
  .flipcard { padding: 12px; }
  .flipcard header { flex-direction: column; }
  .flipcard details > summary, details.offers > summary { padding: 10px 0; }
  button.tick { min-width: 40px; }
  table.tasks th:nth-child(4), table.tasks td:nth-child(4) { min-width: 150px; }
}
"""


FLIPS_JS = """
// Elke knop op /flips gaat zonder herladen: de server stuurt de kaart van
// die flip (en de totalen) terug. Fase, verkocht, nieuw en verwijderen
// verschuiven een kaart naar een ander blok: die herladen de pagina.
function flipUpdate(data) {
  if (data.card && data.flip) {
    const card = document.getElementById('flip-' + data.flip);
    if (card) {
      const open = [...card.querySelectorAll('details')].map(d => d.open);
      card.outerHTML = data.card;
      const fresh = document.getElementById('flip-' + data.flip);
      fresh.querySelectorAll('details').forEach((d, i) => { if (i < open.length) d.open = open[i]; });
    }
  }
  if (data.totals) document.getElementById('flip-totals').innerHTML = data.totals;
  if (data.tools) {
    const box = document.getElementById('flip-tools');
    const open = [...box.querySelectorAll('details')].map(d => d.open);
    box.innerHTML = data.tools;
    box.querySelectorAll('details').forEach((d, i) => { if (i < open.length) d.open = open[i]; });
  }
}
['/flips/klus', '/flips/klus-nieuw', '/flips/gegevens', '/flips/bod', '/flips/bod-weg', '/flips/foto-weg',
 '/flips/aanbod', '/flips/aanbod-kies', '/flips/aanbod-weg']
  .forEach(a => { LIVE[a] = flipUpdate; });
// Na een Sheet-ronde die iets overnam kan alles veranderd zijn: herladen.
LIVE['/flips/sync'] = data => {
  if (data.changed) { location.replace('/flips?melding=' + encodeURIComponent(data.message)); return; }
  const status = document.getElementById('sheet-status');
  if (status && data.status) status.textContent = data.status;
};
document.addEventListener('click', e => {
  const copy = e.target.closest('button.copy');
  if (!copy) return;
  const text = copy.closest('details').querySelector('textarea.draft');
  if (navigator.clipboard) navigator.clipboard.writeText(text.value).then(() => say('Gekopieerd.'));
  else { text.select(); document.execCommand('copy'); say('Gekopieerd.'); }
});
// Foto's gaan als losse upload (geen formulier: een foto is groter dan de
// 10 kB die een formulier hier mag zijn), één voor één.
document.addEventListener('change', async e => {
  const input = e.target.closest('.upload input[type=file]');
  if (!input) return;
  const box = input.closest('.upload');
  const kind = box.querySelector('select').value;
  box.classList.add('busy');
  let data = null;
  for (const file of input.files) {
    const r = await fetch(`/flips/foto?flip=${box.dataset.flip}&soort=${kind}`, {method: 'POST', body: file,
      headers: {'Content-Type': file.type || 'application/octet-stream', 'X-Token': pageData.token || ''}});
    data = r.ok ? await r.json() : {message: 'Uploaden mislukt (' + r.status + ').'};
    if (data.reload) { location.reload(); return; }
  }
  box.classList.remove('busy');
  if (data) { say(data.message); flipUpdate(data); }
});
// Een flip verwijderen gaat niet per ongeluk (vóór LIVE_JS, dat de klik anders verstuurt).
document.addEventListener('click', e => {
  const button = e.target.closest('.act[data-action="/flips/weg"] button');
  if (button && !confirm('Deze flip met zijn klussen en biedingen verwijderen?')) {
    e.preventDefault(); e.stopImmediatePropagation();
  }
}, true);
const syncButton = document.getElementById('sheet-sync');
if (syncButton && syncButton.dataset.auto === '1') {
  // Bij het openen: eerst wat in de Sheet veranderde ophalen.
  fetch('/flips/sync', {method: 'POST', headers: {'X-Live': '1', 'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({token: pageData.token || '', item_id: '', auto: '1'})})
    .then(r => r.json()).then(data => {
      if (data.changed) location.replace('/flips?melding=' + encodeURIComponent(data.message));
      else document.getElementById('sheet-status').textContent = data.status || data.message || '';
    }).catch(() => {});
}
"""


def flips_update(book: fl.FlipBook, trade_id: Optional[int], message: str) -> dict:
    """Wat /flips na een klik vervangt: de kaart, de totalen, de investeringen."""
    f = book.get(trade_id) if trade_id is not None else None
    out = {"message": message, "totals": flip_totals(book), "tools": flip_tools(book)}
    if f is not None:
        out.update(flip=f.id, card=flip_card(f))
    return out


def _flip_id(form: dict, key: str = "item_id") -> int:
    return pg.parse_id(form.get(key))


def flip_action_task(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    task_id = _flip_id(form)
    what = form.get("doe", "")
    conn = db.connect(str(db_path))
    try:
        row = conn.execute("SELECT * FROM flip_task WHERE id = ? AND deleted_at IS NULL", (task_id,)).fetchone()
        if row is None:
            raise pg.FormError("Onbekende regel.")
        task = fl.task_from_row(row)
        if what == "gedaan":
            fl.update_task(conn, task_id, done_at=None if task.done else date.today().isoformat())
            message = f"{'Weer open' if task.done else 'Gedaan'}: {task.title}."
        elif what == "prijs":
            if task.kind == "reis":
                fare = pg.parse_euro(form.get("tarief"), "Tarief", required=False)
                discount = form.get("korting") or "vol"
                if discount not in fl.DISCOUNTS:
                    raise pg.FormError("Onbekende korting.")
                fl.update_task(conn, task_id, fare_eur=fare, discount=discount)
                cost = None if fare is None else round(fare * fl.DISCOUNTS[discount], 2)
                message = f"{task.title}: {euro(cost, cents=True)} ({fl.DISCOUNT_LABELS[discount]})."
            else:
                price = pg.parse_euro(form.get("prijs"), "Prijs", required=False)
                values = {"price_eur": price}
                if price is None:
                    values["bought_at"] = None
                fl.update_task(conn, task_id, **values)
                message = (f"{task.title}: {euro(price, cents=True)}." if price is not None
                           else f"{task.title}: echte prijs gewist, de schatting telt weer.")
        elif what == "investering":
            fl.update_task(conn, task_id, investment=not task.investment)
            message = (f"{task.title} telt nu bij de flip." if task.investment
                       else f"{task.title} is nu een investering (telt niet bij deze flip).")
        elif what == "weg":
            fl.delete_task(conn, task_id)
            message = f"Weggehaald: {task.title}."
        elif what == "winkel":
            url = (form.get("url") or "").strip()
            url = fl.clean_url(url) if url else None
            shop = " ".join((form.get("winkel") or "").split()) or (fl.shop_from_url(url) if url else None)
            fl.update_task(conn, task_id, shop=shop, url=url)
            message = f"{task.title}: {shop or 'winkel onbekend'}{', met link' if url else ''}."
        else:
            raise pg.FormError("Onbekende knop.")
    except ValueError as exc:
        raise pg.FormError(str(exc)) from None
    finally:
        conn.close()
    return message, task.trade_id


def flip_action_offer(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    """Een aanbieding bij een regel: een geplakte link en de prijs die je zag."""
    task_id = _flip_id(form)
    price = pg.parse_euro(form.get("prijs"), "Prijs")
    shipping = pg.parse_euro(form.get("verzending"), "Verzending", required=False)
    conn = db.connect(str(db_path))
    try:
        row = conn.execute("SELECT title, trade_id FROM flip_task WHERE id = ? AND deleted_at IS NULL",
                           (task_id,)).fetchone()
        if row is None:
            raise pg.FormError("Onbekende regel.")
        fl.add_offer(conn, task_id, url=form.get("link", ""), price_eur=price, shipping_eur=shipping,
                     shop=form.get("winkel", ""), note=form.get("notitie", ""))
    except ValueError as exc:
        raise pg.FormError(str(exc)[:1].upper() + str(exc)[1:] + ".") from None
    finally:
        conn.close()
    return f"Aanbieding bij {row['title']}: {euro(price, cents=True)}.", row["trade_id"]


def flip_action_offer_choose(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    conn = db.connect(str(db_path))
    try:
        offer = fl.choose_offer(conn, _flip_id(form))
        if offer is None:
            raise pg.FormError("Onbekende aanbieding.")
        row = conn.execute("SELECT title, trade_id FROM flip_task WHERE id = ?", (offer.task_id,)).fetchone()
    finally:
        conn.close()
    return (f"{row['title']}: {offer.shop or 'deze aanbieding'} voor {euro(offer.total_eur, cents=True)}; "
            "de geplande kosten zijn bijgewerkt."), row["trade_id"]


def flip_action_offer_delete(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    conn = db.connect(str(db_path))
    try:
        offer = fl.delete_offer(conn, _flip_id(form))
        if offer is None:
            raise pg.FormError("Onbekende aanbieding.")
        trade_id = fl.task_trade(conn, offer.task_id)
    finally:
        conn.close()
    return f"Aanbieding weggehaald ({offer.shop or offer.domain or 'zonder link'}, {euro(offer.price_eur, cents=True)}).", trade_id


def flip_action_new_task(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    trade_id = pg.parse_id(form["item_id"]) if form.get("item_id") else None
    title = " ".join((form.get("titel") or "").split())
    if not title:
        raise pg.FormError("Vul in wat het is.")
    kind = form.get("soort", "onderdeel")
    values = {"shop": (form.get("winkel") or "").strip() or None,
              "investment": form.get("investering") == "1"}
    est = pg.parse_euro(form.get("geschat"), "Geschatte prijs", required=False)
    price = pg.parse_euro(form.get("prijs"), "Echte prijs", required=False)
    if kind == "reis":
        values.update(fare_eur=price if price is not None else est, discount="vol")
    else:
        values.update(est_eur=est, price_eur=price)
        if est is not None:
            values["price_source"] = "schatting"
        if price is not None:
            values["bought_at"] = date.today().isoformat()
    conn = db.connect(str(db_path))
    try:
        fl.add_task(conn, trade_id, kind=kind, title=title, **values)
    except ValueError as exc:
        raise pg.FormError(str(exc)) from None
    finally:
        conn.close()
    return f"Op de lijst: {title}.", trade_id


def flip_action_details(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    trade_id = _flip_id(form)
    conn = db.connect(str(db_path))
    try:
        if form.get("doe") == "specs":
            specs = {key: " ".join((form.get("spec_" + key) or "").split()) for key, _ in fl.SPEC_FIELDS}
            specs = {k: v for k, v in specs.items() if v}
            ok = fl.update_flip(conn, trade_id, specs_json=json.dumps(specs, ensure_ascii=False))
            message = "Specs opgeslagen."
        else:
            values = {
                "target_low_eur": pg.parse_euro(form.get("doel_laag"), "Doelprijs laag", required=False),
                "target_high_eur": pg.parse_euro(form.get("doel_hoog"), "Doelprijs hoog", required=False),
                "hours": pg.parse_euro(form.get("uren"), "Uren", required=False),
                "comp_words": " ".join((form.get("zoekwoorden") or "").split()),
                "sale_url": (form.get("verkooplink") or "").strip(),
                "notes": " ".join((form.get("notitie") or "").split()),
            }
            if "titel" in form:
                values["title"] = " ".join(form["titel"].split())
            if "inkoop" in form:
                values["buy_price_eur"] = pg.parse_euro(form.get("inkoop"), "Inkoop")
            if "inkoopkosten" in form:
                values["buy_costs_eur"] = pg.parse_euro(form.get("inkoopkosten"), "Inkoopkosten", required=False) or 0.0
            if values["sale_url"] and not values["sale_url"].startswith(("http://", "https://")):
                raise pg.FormError("De link naar je advertentie moet met http(s):// beginnen.")
            ok = fl.update_flip(conn, trade_id, **values)
            message = "Opgeslagen."
    except ValueError as exc:
        raise pg.FormError(str(exc)) from None
    finally:
        conn.close()
    if not ok:
        raise pg.FormError("Onbekende flip.")
    return message, trade_id


def flip_action_bid(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    trade_id = _flip_id(form)
    amount = pg.parse_euro(form.get("bedrag"), "Bod")
    conn = db.connect(str(db_path))
    try:
        fl.add_bid(conn, trade_id, amount, " ".join((form.get("wie") or "").split()))
    except ValueError as exc:
        raise pg.FormError(str(exc)) from None
    finally:
        conn.close()
    return f"Bod van {euro(amount, cents=True)} genoteerd.", trade_id


def flip_action_bid_delete(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    conn = db.connect(str(db_path))
    try:
        trade_id = fl.delete_bid(conn, _flip_id(form))
    finally:
        conn.close()
    if trade_id is None:
        raise pg.FormError("Onbekend bod.")
    return "Bod weggehaald.", trade_id


def flip_action_photo_delete(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    conn = db.connect(str(db_path))
    try:
        trade_id = fl.delete_photo(conn, _flip_id(form), ctx.photo_dir if ctx else fl.PHOTO_DIR)
    finally:
        conn.close()
    if trade_id is None:
        raise pg.FormError("Onbekende foto.")
    return "Foto weggehaald.", trade_id


def flip_action_stage(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    trade_id = _flip_id(form)
    stage = form.get("fase", "")
    conn = db.connect(str(db_path))
    try:
        ok = fl.set_stage(conn, trade_id, stage)
    finally:
        conn.close()
    if not ok:
        raise pg.FormError("Onbekende flip of fase.")
    return f"Naar {fl.STAGE_LABELS[stage]}.", trade_id


def flip_action_sold(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    trade_id = _flip_id(form)
    price, costs, via, sold_at, bought = parse_sale(db_path, form, trade_id, "Onbekende flip.")
    conn = db.connect(str(db_path))
    try:
        fl.sell(conn, trade_id, sold_at=sold_at, price_eur=price, costs_eur=costs, via=via)
    finally:
        conn.close()
    return f"Verkocht voor {euro(price, cents=True)}: {bought.title}.", trade_id


def flip_action_new(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    title = " ".join((form.get("titel") or "").split())
    if not title:
        raise pg.FormError("Vul in wat het is.")
    market = form.get("markt") if form.get("markt") in (*fl.OWN_MARKETS, *mk.MARKETS) else "fietsen"
    url = (form.get("url") or "").strip() or None
    if url and not url.startswith(("http://", "https://")):
        raise pg.FormError("De link moet met http(s):// beginnen.")
    # Een Marktplaats-link zonder de volgcodes erachter (?_gl=..., honderden tekens).
    if url and "marktplaats.nl" in url:
        url = url.split("?")[0].split("#")[0]
    item_id = None
    if url:
        found = re.search(r"/(m\d{6,})", url)
        item_id = found.group(1) if found else None
    conn = db.connect(str(db_path))
    try:
        trade_id = fl.create_flip(
            conn, title=title, market=market, bought_at=pg.parse_day(form.get("datum")),
            buy_price_eur=pg.parse_euro(form.get("prijs"), "Inkoopprijs"), url=url, item_id=item_id,
            stage=form.get("fase") or "gekocht",
            target_low_eur=pg.parse_euro(form.get("doel_laag"), "Doelprijs laag", required=False),
            target_high_eur=pg.parse_euro(form.get("doel_hoog"), "Doelprijs hoog", required=False),
            comp_words=" ".join((form.get("zoekwoorden") or "").split()))
    except ValueError as exc:
        raise pg.FormError(str(exc)) from None
    finally:
        conn.close()
    return f"Toegevoegd: {title}.", trade_id


def flip_action_delete(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    trade_id = _flip_id(form)
    conn = db.connect(str(db_path))
    try:
        title = conn.execute("SELECT title FROM trade WHERE id = ?", (trade_id,)).fetchone()
        if title is None or not db.delete_trade(conn, trade_id):
            raise pg.FormError("Onbekende flip.")
        # De klussen, biedingen en fasen horen bij de flip; de foto's op
        # schijf blijven staan (je gooit geen foto's weg met een klik).
        conn.execute("UPDATE flip_task SET deleted_at = ?, updated_at = ? WHERE trade_id = ? AND deleted_at IS NULL",
                     (fl.now_iso(), fl.now_iso(), trade_id))
        for table in ("flip", "trade_stage", "flip_bid", "flip_photo"):
            conn.execute(f"DELETE FROM {table} WHERE trade_id = ?", (trade_id,))
        conn.commit()
    finally:
        conn.close()
    return f"Verwijderd: {title[0]}.", None


def flip_action_sync(db_path, form: dict, ctx=None) -> tuple[str, Optional[int]]:
    try:
        result = fs.sync(db_path, config_path=ctx.sheets_config if ctx else SHEETS_CONFIG)
    except fs.SheetError as exc:
        raise pg.FormError(str(exc)) from None
    return result.summary(), None


# Live (JSON terug, kaart vervangen) of met herladen: zie FLIPS_JS.
FLIP_ACTIONS = {
    "/flips/klus": flip_action_task,
    "/flips/klus-nieuw": flip_action_new_task,
    "/flips/aanbod": flip_action_offer,
    "/flips/aanbod-kies": flip_action_offer_choose,
    "/flips/aanbod-weg": flip_action_offer_delete,
    "/flips/gegevens": flip_action_details,
    "/flips/bod": flip_action_bid,
    "/flips/bod-weg": flip_action_bid_delete,
    "/flips/foto-weg": flip_action_photo_delete,
    "/flips/sync": flip_action_sync,
    "/flips/fase": flip_action_stage,
    "/flips/verkocht": flip_action_sold,
    "/flips/nieuw": flip_action_new,
    "/flips/weg": flip_action_delete,
}


FLIP_RELOAD = {"/flips/fase", "/flips/verkocht", "/flips/nieuw", "/flips/weg"}


def parse_sale(db_path, form: dict, trade_id: int, unknown: str) -> tuple:
    """(prijs, kosten, via, datum, de aankoop) uit een verkocht-formulier, voor
    Mijn flips en /flips. `unknown` is de melding bij een aankoop die niet
    bestaat."""
    price = pg.parse_euro(form.get("prijs"), "Verkoopprijs")
    costs = pg.parse_euro(form.get("kosten"), "Kosten", required=False) or 0.0
    via = form.get("via") if form.get("via") in ("marktplaats", "vinted", "anders") else "anders"
    sold_at = pg.parse_day(form.get("datum"))
    bought = next((t for t in tr.load_trades(db_path) if t.id == trade_id), None)
    if bought is None:
        raise pg.FormError(unknown)
    if sold_at < bought.bought_at[:10]:
        raise pg.FormError(f"Verkocht op {pg.nl_date(sold_at)} ligt vóór de aankoop ({pg.nl_date(bought.bought_at)}).")
    return price, costs, via, sold_at, bought
