"""De pagina `/fiets` van `dashboard.py --serve`: de vergelijkingslijst voor
de taxatie van de eigen fiets (bike_comps.py), per advertentie meenemen of
niet, met de taxatie die daaruit volgt. Alleen live: zonder knoppen is het
een lijst zonder doel; de uitkomst staat ook in het rapport en het overzicht.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import bike_comps as bc
import db
import pages as pg
import report
import upgrade as up
from util import euro
import valuation as val


INTAKE_PATH = Path(__file__).resolve().parent / "mijn_fiets.md"


BIKE_CHOICE_PATH = "/fiets/keuze"


BIKE_SHOW = (("open", "Te beoordelen"), (bc.MEE, "Meegenomen"), (bc.NIET, "Niet"), ("alles", "Alles"))


@dataclass
class BikeView:
    rows: list  # bike_comps.Row, nieuwste en online eerst
    owner: Optional[report.OwnerContext] = None
    problem: str = ""  # waarom er geen eigen fiets is (mijn_fiets.md onleesbaar)

    def count(self, show: str) -> int:
        if show == "alles":
            return len(self.rows)
        return sum(1 for r in self.rows if (r.choice or "open") == show)


def load_bike_view(db_path, intake_path=INTAKE_PATH, cache=None) -> BikeView:
    """De lijst en de taxatie zoals het rapport hem ook maakt
    (report.load_owner_context), zodat /fiets en de tab Mijn fiets
    hetzelfde bedrag noemen. `cache`: de LiveCache van dashboard.py."""
    comps = cache.comps(db_path) if cache is not None else None
    owner, problem = report.load_owner_context(str(intake_path), str(db_path), comps=comps)
    if owner is None:
        return BikeView([], None, problem or "")
    conn = bc.open_readonly(db_path)
    try:
        rows = bc.load_rows(conn, val.subject_from_owner_bike(owner.bike)) if conn else []
    finally:
        if conn:
            conn.close()
    # Online eerst, nieuwste bovenaan; daarna wat verdween, laatst verdwenen eerst.
    online = sorted((r for r in rows if not r.gone), key=lambda r: r.first_seen or "", reverse=True)
    gone = sorted((r for r in rows if r.gone), key=lambda r: r.disappeared_at or "", reverse=True)
    return BikeView(online + gone, owner)


def bike_price_kind(r: bc.Row) -> str:
    if r.price_eur is None:
        return "bieden, geen prijs"
    if not r.counts:
        return "huidig bod, loopt nog op"
    return {"FIXED": "vaste prijs", "MIN_BID": "vraagprijs, bieden kan"}.get(r.price_type, "vraagprijs")


def bike_material(r: bc.Row) -> str:
    if not r.material:
        return "materiaal onbekend"
    # Wat de verkoper bij de kenmerken aanklikte klopt niet altijd; het
    # model of de tekst zegt meer.
    return f"{r.material} volgens de verkoper" if r.material_source == bc.FROM_SELLER else r.material


def bike_row(r: bc.Row) -> str:
    choice = r.choice or "open"
    badges = ""
    if r.choice == bc.MEE:
        badges += "<span class='badge fav'>meegenomen</span> "
    if r.reserved and not r.gone:
        badges += "<span class='badge reserved'>gereserveerd</span> "
    if r.gone:
        days = f", {r.days_online} dagen online" if r.days_online is not None else ""
        badges += f"<span class='badge reserved'>weg sinds {pg.esc(pg.nl_date(r.disappeared_at))}{pg.esc(days)}</span> "
    facts = [r.model_label,
             str(r.year) if r.year else "",
             f"maat {r.frame_height}" if r.frame_height else "",
             bike_material(r),
             f"in {r.category_label}" if r.category_label else "",
             "" if r.family_in_text else "gevonden door de zoekopdracht, de modelnaam staat niet in de tekst",
             r.city,
             f"sinds {pg.nl_date(r.first_seen)}" if r.first_seen and not r.gone else ""]
    bids = ""
    if r.bid_count:
        high = f", hoogste {euro(r.bid_high)}" if r.bid_high is not None else ""
        bids = f"<div class='sub'>{r.bid_count} bieding{'en' if r.bid_count != 1 else ''}{pg.esc(high)}</div>"
    why = f"<div class='sub warn'>telt niet mee: {pg.esc(r.why_not)}</div>" if r.why_not else ""
    price = f"{r.price_eur}" if r.price_eur is not None else ""

    def button(value: str, label: str) -> str:
        on = r.choice == value
        # Nog eens op de gekozen knop: terug naar te beoordelen.
        return (f"<button class='quiet{' on' if on else ''}' name='keuze' value='{'' if on else value}' "
                f"aria-pressed='{'true' if on else 'false'}'>{pg.esc(label)}</button>")

    item = pg.esc(r.item_id, quote=True)
    return (
        f"<tr data-item='{item}' data-choice='{choice}'>"
        f"<td class='pic'>{pg.thumb(r)}</td>"
        f"<td class='num' data-sort='{price}'>{euro(r.price_eur)}<div class='sub'>{pg.esc(bike_price_kind(r))}</div>"
        f"{bids}{why}</td>"
        f"<td class='what'><div class='model'>{badges}</div>"
        f"<a href='{pg.esc(r.url, quote=True)}' target='_blank' rel='noopener'>{pg.esc(r.title)}</a>"
        f"<div class='note'>{pg.esc(' · '.join(f for f in facts if f))}</div></td>"
        f"<td>{pg.act(BIKE_CHOICE_PATH, r.item_id, button(bc.MEE, '✓ meenemen') + button(bc.NIET, '✗ niet'))}</td>"
        "</tr>"
    )


def bike_summary(view: BikeView) -> str:
    owner = view.owner
    taken = [r for r in view.rows if r.choice == bc.MEE]
    counting = sum(1 for r in taken if r.counts)
    b = owner.valuations.get("b") if owner else None
    if b is not None:
        value = euro(b.mid_eur)
        sub = f"{euro(b.low_eur)} – {euro(b.high_eur)} · n={owner.comp_count} · vertrouwen {b.confidence}"
    else:
        value = "—"
        manual = up.manual_sale_price_from(owner.bike.specs) if owner else None
        sub = ("nog niets meegenomen met een vraagprijs"
               + (f"; tot dan rekent de upgrade-finder met {euro(manual)} uit mijn_fiets.md" if manual else ""))
    parts = [pg.tiles([
        ("Jouw fiets, originele wielen", value, sub),
        ("Meegenomen", str(len(taken)), f"{counting} met een vraagprijs, die tellen mee"),
        ("Te beoordelen", str(view.count("open")), "nieuw of nog niet bekeken"),
        ("Niet", str(view.count(bc.NIET)), "telt nooit mee"),
    ])]
    if b is not None:
        if b.confidence == "indicatief":
            manual = up.manual_sale_price_from(owner.bike.specs)
            if manual is not None:
                parts.append(f"<p class='explain'>Onder de {val.MIN_COMPS_FOR_A_HARD_NUMBER} meegenomen "
                             f"advertenties is dit een richting, geen prijs: de upgrade-finder rekent nog met "
                             f"{euro(manual)} uit mijn_fiets.md.</p>")
        lines = "".join(f"<li>{pg.esc(e.note)}</li>" for e in b.evidence if e.kind != "comp" or not e.ref_id)
        parts.append(f"<details class='how'><summary>Hoe dit bedrag ontstaat</summary><ul class='evidence'>{lines}</ul>"
                     "</details>")
    return "".join(parts)


def bike_show_options(view: BikeView) -> str:
    return "".join(f"<option value='{key}'>{pg.esc(label)} ({view.count(key)})</option>" for key, label in BIKE_SHOW)


def render_bike(view: BikeView, token: str = "", message: str = "", other_links: Sequence = ()) -> str:
    owner = view.owner
    links = "".join(f" · <a href='{pg.esc(href, quote=True)}'>{pg.esc(label)}</a>" for label, href in other_links)
    if owner is None:
        body = f"<div class='banner'>{pg.esc(view.problem)}</div>"
        about = ""
    else:
        specs = owner.bike.specs
        about = " · ".join(pg.esc(x) for x in (
            owner.bike.label, specs.get("model_year", ""), specs.get("frame_material", ""),
            f"maat {specs['size_cm']}" if specs.get("size_cm") else "") if x)
        subject = val.subject_from_owner_bike(owner.bike)
        family = " / ".join(subject.family_patterns)
        show = "open" if view.count("open") else "alles"
        rows = [bike_row(r) for r in view.rows]
        body = (
            f"<div id='bike-summary'>{bike_summary(view)}</div>"
            "<p class='explain'>Alle advertenties van de laatste "
            f"{val.DEFAULT_COMP_WINDOW_DAYS} dagen met <strong>{pg.esc(family)}</strong> in de tekst of gevonden "
            "door een zoekopdracht met dat woord erin, ook die al weg zijn (verkocht of ingetrokken), uit elke "
            "categorie behalve onderdelen en accessoires, en van "
            "elk materiaal. Het materiaal staat erbij: van het model (Defy 0-5 en Aluxx zijn aluminium, "
            "Composite en Advanced carbon), uit de tekst, of <em>volgens de verkoper</em> (wat bij de kenmerken "
            "is aangeklikt, en dat klopt niet altijd: kijk dan naar de foto's). "
            "<strong>Alleen wat je meeneemt telt mee</strong> in de taxatie, met zijn vraagprijs; een "
            "biedadvertentie waarop al geboden is telt niet mee (de prijs loopt nog op). Nog eens op de "
            "gekozen knop zet hem terug naar te beoordelen.</p>"
            "<div class='filters'>"
            f"<select id='bike-show' aria-label='Toon' data-default='{show}'>{bike_show_options(view)}</select>"
            "<span class='muted' id='bike-count'></span></div>"
            + pg.table([("", ""), ("Prijs", "num"), ("Advertentie", "text"), ("Vergelijken?", "")], rows, "bike-table")
            + "<p class='empty' id='bike-empty' hidden>Niets in deze selectie.</p>"
        )
    notice = f"<div class='banner' role='status'>{pg.esc(message)}</div>" if message else ""
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Mijn fiets</title><style>{pg.CSS}{pg.SITE_CSS}</style></head><body>"
        f"<main data-token='{pg.esc(token, quote=True)}'>{pg.site_nav(pg.BIKE_PATH)}"
        "<h1>Mijn fiets: vergelijkbare advertenties</h1>"
        f"<div class='meta'>{about}{links} · <strong>live</strong> (keuzes gaan in koopjes.db)</div>{notice}{body}"
        f"</main><div id='toast' role='status' hidden></div><script>{pg.LIVE_JS}{pg.JS}{BIKE_JS}</script></body></html>"
    )


BIKE_JS = """
const bikeShow = document.getElementById('bike-show');
function filterBike() {
  if (!bikeShow) return;
  const which = bikeShow.value;
  let shown = 0;
  document.querySelectorAll('#bike-table tbody tr').forEach(r => {
    const ok = which === 'alles' || r.dataset.choice === which;
    r.classList.toggle('hidden', !ok);
    if (ok) shown++;
  });
  document.getElementById('bike-count').textContent = shown + ' getoond';
  document.getElementById('bike-empty').hidden = shown > 0;
}
if (bikeShow) {
  bikeShow.value = bikeShow.dataset.default;
  bikeShow.addEventListener('input', filterBike);
  filterBike();
}
// Meenemen/niet: zonder herladen. De rij, de taxatie bovenaan en de
// aantallen komen van de server; in "Te beoordelen" verdwijnt de rij.
LIVE['/fiets/keuze'] = data => {
  const row = document.querySelector(`#bike-table tr[data-item="${CSS.escape(data.item)}"]`);
  if (row && data.row) row.outerHTML = data.row;
  if (data.summary) document.getElementById('bike-summary').innerHTML = data.summary;
  if (data.options) { const value = bikeShow.value; bikeShow.innerHTML = data.options; bikeShow.value = value; }
  filterBike();
};
"""


def action_choice(db_path, form: dict) -> str:
    """Meenemen, niet, of (leeg) terug naar te beoordelen."""
    item_id = form.get("item_id", "")
    choice = form.get("keuze", "")
    if choice and choice not in bc.CHOICES:
        raise pg.FormError(f"Onbekende keuze '{choice}'.")
    conn = db.connect(str(db_path))
    try:
        row = conn.execute("SELECT title FROM listing WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            raise pg.FormError("Onbekende advertentie.")
        db.set_comp_choice(conn, item_id, choice or None)
    finally:
        conn.close()
    title = row["title"] or item_id
    if choice == bc.MEE:
        return f"Meegenomen: {title}."
    if choice == bc.NIET:
        return f"Niet meegenomen: {title}."
    return f"Terug naar te beoordelen: {title}."


def bike_update(view: BikeView, item_id: str, message: str) -> dict:
    """Wat /fiets na een klik vervangt: de rij, de taxatie en de aantallen."""
    row = next((r for r in view.rows if r.item_id == item_id), None)
    return {"message": message, "item": item_id, "row": bike_row(row) if row else "",
            "summary": bike_summary(view) if view.owner else "", "options": bike_show_options(view)}
