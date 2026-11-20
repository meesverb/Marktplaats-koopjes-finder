
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
