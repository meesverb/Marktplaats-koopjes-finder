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
from typing import Optional

import markets as mk
import util


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


CSS = """
:root { color-scheme: light; --surface: #fcfcfb; --card: #ffffff; --line: #e4e3df;
  --text: #0b0b0b; --text-2: #52514e; --muted: #6b6a66; --accent: #2a78d6; --good: #0ca30c;
  --bad: #d03b3b; --badge: #e8f0fb; --fav: #fbeec2; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --surface: #1a1a19; --card: #222221;
  --line: #3a3a38; --text: #ffffff; --text-2: #c3c2b7; --muted: #a3a29a; --accent: #3987e5;
  --good: #0ca30c; --bad: #e06666; --badge: #23344a; --fav: #4a3c10; } }
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
.badge.reserved { background: var(--line); color: var(--text-2); }
.badge.fav { background: var(--fav); }
.mark { margin-top: 4px; gap: 4px; }
.mark button { font-size: .78rem; padding: 2px 8px; }
.mynote { margin-top: 5px; padding: 2px 8px; border-left: 3px solid var(--fav); font-size: .85rem;
  color: var(--text); white-space: pre-wrap; overflow-wrap: anywhere; }
details.note-edit summary { margin-top: 4px; font-size: .78rem; color: var(--text-2); cursor: pointer; }
ul.changes { margin: 0; padding: 0; list-style: none; font-size: .82rem; }
ul.changes li::before { display: inline-block; width: 1.1em; font-weight: 700; }
ul.changes li.plus::before { content: "+"; color: var(--good); }
ul.changes li.minus::before { content: "−"; color: var(--bad); }
.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 10px; }
.filters input[type=search], .filters select { font: inherit; padding: 6px 8px; border: 1px solid var(--line);
  border-radius: 6px; background: var(--card); color: var(--text); }
.filters input[type=search] { min-width: 240px; }
tr.hidden, tr.far { display: none; }
.empty { color: var(--muted); padding: 12px 0; }
code { font-size: .85em; }
.banner { background: var(--badge); border-radius: 8px; padding: 10px 14px; margin: 0 0 14px; }
.owned { margin-top: 4px; font-size: .82rem; font-weight: 600; }
#toast { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); max-width: min(90vw, 640px);
  background: var(--text); color: var(--surface); border-radius: 8px; padding: 10px 16px; font-size: .9rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, .25); z-index: 10; }
#toast[hidden] { display: none; }
.busy { opacity: .5; pointer-events: none; }
button.quiet.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.sub.warn { color: var(--bad); }
ul.evidence { margin: 6px 0 0; padding-left: 20px; font-size: .85rem; color: var(--text-2); }
details.how > summary { cursor: pointer; color: var(--text-2); font-size: .88rem; margin: 4px 0 12px; }
.inline { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 6px; font-size: .85rem; }
.inline input, .inline select, .addform input, .addform select { font: inherit; padding: 3px 6px;
  border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--text); }
.inline input[size] { width: auto; }
button { font: inherit; font-size: .85rem; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--accent);
  background: var(--accent); color: #fff; cursor: pointer; }
button.quiet { background: none; color: var(--text-2); border-color: var(--line); }
nav.tabs button { font-size: inherit; border-radius: 0; }
.addform { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; background: var(--card);
  border: 1px solid var(--line); border-radius: 10px; padding: 12px; }
.addform label { display: flex; flex-direction: column; font-size: .8rem; color: var(--text-2); gap: 3px; }
svg.chart { width: 100%; max-width: 720px; height: auto; background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; }
.meter { height: 10px; border-radius: 4px; background: var(--accent); min-width: 2px; }
svg.chart .bar { fill: var(--accent); }
svg.chart .axis { stroke: var(--line); }
svg.chart text { font-size: 15px; text-anchor: middle; fill: var(--text-2); }
svg.chart text.val { fill: var(--text); font-weight: 600; }
"""


JS = """
const buttons = document.querySelectorAll('nav.tabs button');
// Te beoordelen en Weggezet zijn Alle met een filter (data-mark): de knop
// zet Toon zodra de tabel er is; Alle zelf zet hem terug.
let presetMark = null;
function applyPreset() {
  if (presetMark === null || !markFilter) return;
  markFilter.value = presetMark; presetMark = null; filterAll();
}
// preset: zet Toon voor Te beoordelen/Weggezet; niet bij terugkomen na
// controleer, dan gelden de bewaarde filters.
function show(name, preset = true) {
  const view = Array.from(buttons).find(b => b.dataset.tab === name);
  const button = view || Array.from(buttons).find(b => b.dataset.panel === name && !b.dataset.tab);
  if (view) { if (preset) presetMark = view.dataset.mark; name = view.dataset.panel; }
  const target = document.getElementById('panel-' + name);
  if (!target) return;
  document.querySelectorAll('.panel').forEach(p => p.hidden = p !== target);
  buttons.forEach(b => b.classList.toggle('active', b === button));
  if (target.dataset.lazy) loadPanel(target, name); else applyPreset();
}
buttons.forEach(b => b.addEventListener('click', () => {
  // Van Te beoordelen of Weggezet naar Alle: Toon terug op de standaard;
  // anders houdt Alle wat je zelf koos.
  const from = document.querySelector('nav.tabs button.active');
  if (!b.dataset.tab && b.dataset.panel === 'alle' && from && from.dataset.tab) presetMark = '';
  const name = b.dataset.tab || b.dataset.panel;
  show(name); history.replaceState(null, '', '#' + name);
}));
window.addEventListener('hashchange', () => show(location.hash.slice(1)));

// Een tab uit LAZY_PANELS (dashboard.py) staat op de live pagina leeg en
// komt pas van de server als je hem opent. Alle computers is ruim de helft
// van de pagina, en de browser las hem bij elke keer laden terwijl je
// meestal alleen Flips bekijkt. Wat je tijdens het laden aanklikt, wordt
// daarna nog eens op de nieuwe rijen gezet.
let loading = 0, pendingItems = [], pendingOptions = null, pendingScroll = null;
function loadPanel(panel, name) {
  if (panel.dataset.loading) return;
  panel.dataset.loading = '1';
  loading++;
  panel.innerHTML = "<p class='empty'>Laden…</p>";
  const url = '/paneel?markt=' + encodeURIComponent(pageData.markt || '') + '&naam=' + encodeURIComponent(name);
  fetch(url)
    .then(r => r.ok ? r.text() : Promise.reject(r.status))
    .then(html => {
      delete panel.dataset.lazy;
      panel.innerHTML = html;
      initSortable(panel);
      initAll();
      applyPreset();
      pendingItems.splice(0).forEach(applyItem);
      if (pendingOptions !== null) { setMarkOptions(pendingOptions); pendingOptions = null; }
      if (search) filterAll();
      filterKm(panel);
      if (pendingScroll !== null && !panel.hidden) { window.scrollTo(0, pendingScroll); pendingScroll = null; }
    }, () => {
      panel.innerHTML = "<p class='empty'>Laden lukte niet; herlaad de pagina.</p>";
    })
    .finally(() => { delete panel.dataset.loading; loading--; });
}

// Controleer en Gekocht laden de pagina opnieuw (controleer haalt de
// advertentie bij Marktplaats en kan prijs, bod en reservering veranderen).
// Na controleer wil je terug waar je was: dezelfde tab (de server stuurt
// terug naar de tab die meegaat), en dezelfde plek en filters (via
// sessionStorage). Favoriet/weg en de notitie herladen niet: zie LIVE.
const RESTORE = 'koopjes-terug';
let restore = null;
try {
  restore = JSON.parse(sessionStorage.getItem(RESTORE) || 'null');
  sessionStorage.removeItem(RESTORE);
  if (restore && restore.path !== location.pathname) restore = null;
} catch (_) { restore = null; }
function rememberPlace() {
  const filters = {};
  document.querySelectorAll('.filters [id]').forEach(el => {
    if (el.matches('input, select')) filters[el.id] = el.type === 'checkbox' ? el.checked : el.value;
  });
  try {
    sessionStorage.setItem(RESTORE, JSON.stringify({path: location.pathname, y: window.scrollY, filters}));
  } catch (_) {}
}
// De bewaarde filters weer invullen, voor zover ze er al staan; die van een
// tab die nog moet laden, zodra hij er is.
function restoreFilters() {
  if (!restore) return;
  const filters = restore.filters || {};
  Object.keys(filters).forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const value = filters[id];
    if (el.type === 'checkbox') el.checked = !!value;
    else if (el.tagName !== 'SELECT' || Array.from(el.options).some(o => o.value === value)) el.value = value;
    delete filters[id];
  });
}
STAY['/controleer'] = rememberPlace;
LIVE['/markeer'] = applyMark;
LIVE['/notitie'] = applyMark;
LIVE['/bod'] = applyMark;
LIVE['/bod/status'] = applyMark;

// Max. afstand (schuifje bovenaan): verbergt op elke tab de rijen verder weg.
// Los van de filters van Alle (class far, niet hidden), zodat ze samengaan.
const kmMax = document.getElementById('km-max');
const kmNone = document.getElementById('km-none');
const kmOut = document.getElementById('km-out');
function filterKm(root) {
  if (!kmMax) return;
  const max = +kmMax.value, all = max >= +kmMax.max;
  kmOut.textContent = all ? 'alles' : 'max ' + max + ' km';
  (root || document).querySelectorAll('td.what[data-km]').forEach(td => {
    const km = td.dataset.km === '' ? null : parseFloat(td.dataset.km);
    const far = !all && (km === null ? !kmNone.checked : km > max);
    td.closest('tr').classList.toggle('far', far);
  });
  try { localStorage.setItem('koopjes-km', JSON.stringify({max, none: kmNone.checked})); } catch (_) {}
}
if (kmMax) {
  try {
    const saved = JSON.parse(localStorage.getItem('koopjes-km') || 'null');
    if (saved) { kmMax.value = saved.max; kmNone.checked = saved.none; }
  } catch (_) {}
  [kmMax, kmNone].forEach(el => el.addEventListener('input', () => filterKm()));
  filterKm();
}

// Sorteren: de sleutel één keer per rij (niet bij elke vergelijking
// opnieuw uit de cel), en de rijen in één keer op hun nieuwe plek.
function initSortable(root) {
 root.querySelectorAll('table.sortable').forEach(table => {
  const tbody = table.querySelector('tbody');
  table.querySelectorAll('th[data-type]').forEach((th, index) => {
    let asc = th.dataset.type !== 'num';
    th.addEventListener('click', () => {
      const col = Array.from(th.parentNode.children).indexOf(th);
      const num = th.dataset.type === 'num';
      const keyed = Array.from(tbody.rows, r => {
        const cell = r.cells[col];
        if (!num) return [cell.textContent.trim().toLowerCase(), r];
        const v = parseFloat(cell.dataset.sort);
        return [Number.isNaN(v) ? null : v, r];
      });
      keyed.sort((a, b) => {
        const x = a[0], y = b[0];
        if (x === null) return 1;
        if (y === null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
      });
      tbody.append(...keyed.map(k => k[1]));
      asc = !asc;
    });
  });
 });
}
initSortable(document);

// De filters van Alle computers; op de live pagina pas als die tab geladen is.
let search = null, brand = null, markFilter = null, onlyNew = null, count = null, maxPrice = null;
function filterAll() {
  if (!search) return;
  const q = search.value.trim().toLowerCase();
  const pmax = parseFloat(maxPrice ? maxPrice.value : '');
  const which = markFilter.value;
  let shown = 0;
  document.querySelectorAll('#all-table tbody tr').forEach(r => {
    // Standaard zonder weggezette; 'alles' toont ze erbij, 'notitie' alles met een notitie.
    const markOk = which === 'alles' || (which === 'notitie' ? r.dataset.note === '1'
      : which === 'beoordelen' ? r.dataset.review === '1'
      : which ? r.dataset.mark === which : r.dataset.mark !== 'weg');
    const price = r.dataset.price === '' ? null : parseFloat(r.dataset.price);
    const ok = (!q || r.dataset.text.includes(q)) && (!brand.value || r.dataset.brand === brand.value)
      && (!onlyNew.checked || r.dataset.new === '1') && markOk
      && (Number.isNaN(pmax) || price === null || price <= pmax);
    r.classList.toggle('hidden', !ok);
    if (ok) shown++;
  });
  count.textContent = shown + ' getoond';
}
function initAll() {
  const box = document.getElementById('all-search');
  if (!box || box === search) return;
  search = box;
  brand = document.getElementById('all-brand');
  markFilter = document.getElementById('all-mark');
  onlyNew = document.getElementById('all-new');
  maxPrice = document.getElementById('all-pmax');
  count = document.getElementById('all-count');
  restoreFilters();
  // Typen filtert als je even stopt: elke toets liep anders alle rijen langs.
  let typing = null;
  search.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(filterAll, 150); });
  [brand, markFilter, onlyNew, maxPrice].filter(Boolean).forEach(el => el.addEventListener('input', filterAll));
  filterAll();
}
function setMarkOptions(html) {
  if (!markFilter) return;
  const value = markFilter.value;
  markFilter.innerHTML = html;
  markFilter.value = value;
}

// Na favoriet/weg of een notitie: de server stuurt de stukjes die
// veranderden (live_update in dashboard.py).
function applyItem(it) {
  const sel = `[data-item="${CSS.escape(it.id)}"]`;
  // Weggezet (of gekocht, gereserveerd): weg uit Flips en Upgrades.
  document.querySelectorAll(`#panel-flips .mine${sel}, #panel-upgrades .mine${sel}`).forEach(el => {
    el.closest('tr').classList.toggle('hidden', !it.available);
  });
  document.querySelectorAll('.markbadge' + sel).forEach(el => { el.innerHTML = it.badge; });
  document.querySelectorAll('.mine' + sel).forEach(el => { el.innerHTML = it.mine; });
  document.querySelectorAll('#all-table tr' + sel).forEach(r => {
    r.dataset.mark = it.mark; r.dataset.note = String(it.note); r.dataset.text = it.text;
    if (it.review !== undefined) r.dataset.review = String(it.review);
  });
}
function applyMark(data) {
  Object.entries(data.panels || {}).forEach(([name, html]) => {
    const panel = document.getElementById('panel-' + name);
    if (panel) { panel.innerHTML = html; initSortable(panel); filterKm(panel); }
  });
  Object.entries(data.tabs || {}).forEach(([name, label]) => {
    const button = document.querySelector(`nav.tabs button[data-tab="${name}"]`)
      || document.querySelector(`nav.tabs button[data-panel="${name}"]:not([data-tab])`);
    if (button) button.textContent = label;
  });
  Object.entries(data.tiles || {}).forEach(([name, html]) => {
    const old = document.querySelector(`#panel-${name} .tiles`);
    if (old && !data.panels[name]) old.outerHTML = html;
  });
  const away = document.querySelector('#panel-flips .away');
  if (away && data.away !== undefined && !(data.panels || {}).flips) away.outerHTML = data.away;
  if (data.item) {
    applyItem(data.item);
    if (loading) pendingItems.push(data.item);
  }
  if (data.markOptions) {
    setMarkOptions(data.markOptions);
    if (loading) pendingOptions = data.markOptions;
  }
  if (search) filterAll();
  filterKm();
}

restoreFilters();
initAll();
if (location.hash) show(location.hash.slice(1), !restore);
if (restore) {
  // Terug op een tab die nog laadt: pas scrollen als hij er is.
  if (document.querySelector('.panel:not([hidden])[data-lazy]')) pendingScroll = restore.y || 0;
  else window.scrollTo(0, restore.y || 0);
}
"""


# Gedeeld door alle live pagina's: een formulier versturen zonder te
# herladen, en de melding onderin in plaats van bovenaan een nieuwe pagina.
LIVE_JS = """
const toast = document.getElementById('toast');
let toastTimer = null;
function say(message) {
  if (!toast || !message) return;
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 3500);
}
// Een knop in een .act (zie act() in dashboard.py) verstuurt de velden van
// zijn rij. Acties in LIVE gaan zonder herladen: de server antwoordt met
// JSON en de functie in LIVE werkt de pagina bij. De rest (Gekocht,
// controleer) gaat als gewoon formulier, met herladen; STAY onthoudt dan
// eerst waar je was.
const LIVE = {}, STAY = {};
const pageData = (document.querySelector('main') || document.body).dataset;
function fields(box, button) {
  const body = new URLSearchParams();
  body.set('token', pageData.token || '');
  if (pageData.markt) body.set('markt', pageData.markt);
  body.set('item_id', box.dataset.item || '');
  const active = document.querySelector('nav.tabs button.active');
  body.set('tab', active ? active.dataset.tab || active.dataset.panel : '');
  box.querySelectorAll('input[name], select[name]').forEach(el => body.set(el.name, el.value));
  if (button.name) body.set(button.name, button.value);
  return body;
}
function navigate(action, body) {
  if (STAY[action]) STAY[action]();
  const form = document.createElement('form');
  form.method = 'post';
  form.action = action;
  body.forEach((value, name) => {
    const input = document.createElement('input');
    input.type = 'hidden'; input.name = name; input.value = value;
    form.appendChild(input);
  });
  document.body.appendChild(form);
  form.submit();
}
function send(box, action, body) {
  box.classList.add('busy');
  fetch(action, {method: 'POST', body, headers: {'X-Live': '1'}})
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(data => {
      if (data.reload) { location.reload(); return; }
      say(data.message);
      LIVE[action](data);
    // Geen antwoord zoals verwacht: dan gewoon zoals vroeger, met herladen.
    // Alleen dan; een fout bij het bijwerken zou anders de klik nog eens sturen.
    }, () => navigate(action, body))
    .finally(() => box.classList.remove('busy'));
}
document.addEventListener('click', e => {
  const button = e.target.closest('.act button');
  if (!button) return;
  const box = button.closest('.act');
  const action = button.dataset.action || box.dataset.action;
  const body = fields(box, button);
  if (LIVE[action]) send(box, action, body);
  else navigate(action, body);
});
// Enter in een invulveld (notitie, inkoopprijs) is de knop ernaast.
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !e.target.matches('.act input')) return;
  e.preventDefault();
  const button = e.target.closest('.act').querySelector('button');
  if (button) button.click();
});
"""


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


SITE_CSS = """
nav.site { margin: -6px 0 14px; padding-bottom: 8px; border-bottom: 1px solid var(--line); font-size: .92rem; }
nav.site .site-links { display: flex; flex-wrap: wrap; gap: 4px 16px; }
nav.site .site-menu { display: none; }
nav.site a { text-decoration: none; color: var(--text-2); }
nav.site a[aria-current] { color: var(--text); font-weight: 700; }
nav.site a:hover { color: var(--accent); }
/* Telefoon (de eigenaar, 02-10-2026): de balk bovenaan ingeklapt, rijen
   tabknoppen die zijwaarts scrollen in plaats van vier regels hoog, en
   knoppen en velden groot genoeg voor een duim. */
@media (max-width: 700px) {
  nav.site { margin-top: -10px; padding-bottom: 0; }
  nav.site .site-menu { display: flex; align-items: center; min-height: 44px; font-weight: 700; cursor: pointer;
    user-select: none; }
  nav.site .site-links { display: none; flex-direction: column; gap: 0; }
  nav.site .site-open:checked ~ .site-links { display: flex; }
  nav.site .site-links a { padding: 11px 0; border-top: 1px solid var(--line); }
  nav.tabs { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }
  nav.tabs::-webkit-scrollbar { display: none; }
  nav.tabs button { flex: none; }
  button, select, input[type=text], input[type=search], input[type=number], input[type=date], input:not([type]) {
    min-height: 40px; }
  input[type=checkbox], input[type=radio] { width: 20px; height: 20px; }
  summary { padding: 8px 0; }
}
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }
.card { display: block; background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; text-decoration: none; color: var(--text); }
a.card:hover { border-color: var(--accent); }
.card .model { font-size: 1.05rem; }
ul.files { list-style: none; margin: 0; padding: 0; background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; }
ul.files li { padding: 8px 12px; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between;
  gap: 12px; flex-wrap: wrap; }
ul.files li:last-child { border-bottom: 0; }
pre.log { max-height: 320px; overflow: auto; background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; padding: 10px 12px; font-size: .8rem; white-space: pre-wrap; }
"""


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
