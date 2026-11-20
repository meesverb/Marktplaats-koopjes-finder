
window.addEventListener('error', e => {
  const box = document.getElementById('more');
  if (box) { box.hidden = false; box.textContent = 'De pagina kon de fietsen niet tonen: ' + e.message; }
});
const BIKES = JSON.parse(document.getElementById('bikes').textContent);
const MODELS = JSON.parse(document.getElementById('models').textContent);
let RULES = JSON.parse(document.getElementById('rules').textContent);
const MODEL_PATH = '/racefietsen/model', RULE_PATH = '/racefietsen/regel', RESERVE_PATH = '/racefietsen/reserves';
const COMPS_PATH = '/racefietsen/vergelijk', COMPS_SHOWN = 12;
const DOSSIER_PATH = '/racefietsen/dossier';
const SPARES = JSON.parse(document.getElementById('spares').textContent);
const GONE = JSON.parse(document.getElementById('gone').textContent);
const REASONS = JSON.parse(document.getElementById('reasons').textContent);
const STATUSES = JSON.parse(document.getElementById('statuses').textContent);
const HOME = document.getElementById('list').dataset.home === '1';
const list = document.getElementById('list');
const more = document.getElementById('more');
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const euro = v => v == null ? '—' : '€' + Math.round(v);
const signed = v => v == null ? '—' : (v >= 0 ? '+' : '−') + '€' + Math.abs(Math.round(v));
const BATCH = 40;
let view = 'open', shown = [], drawn = 0, cur = -1;
const byId = new Map(BIKES.map(b => [b.id, b]));
const modelByKey = new Map(MODELS.map(m => [m.k, m]));
// Zoeken zonder accenten en hoofdletters: "emonda" vindt "Émonda".
const fold = s => String(s == null ? '' : s).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

function state() {
  let s = {};
  try { s = JSON.parse(localStorage.getItem('racefietsen') || '{}'); } catch (_) {}
  return s;
}
function remember() {
  const s = {view, sort: $('sort').value, fmin: $('fmin').value, fmax: $('fmax').value, unk: $('unk').checked,
             pmax: $('pmax').value, km: $('km').value, nokm: $('nokm').checked, res: $('res').checked};
  try { localStorage.setItem('racefietsen', JSON.stringify(s)); } catch (_) {}
}
function restoreFilters() {
  const s = state();
  if (s.view) view = s.view;
  for (const k of ['sort', 'fmin', 'fmax', 'pmax', 'km']) if (s[k] != null && $(k)) $(k).value = s[k];
  for (const k of ['unk', 'nokm', 'res']) if (s[k] != null && $(k)) $(k).checked = s[k];
}

let modelFilter = '';
function inView(b) {
  if (modelFilter && b.mk !== modelFilter) return false;
  const bid = b.b.length > 0;
  if (view === 'open') return !b.m && !bid && !b.own && !b.res;
  if (view === 'fav') return b.m === 'favoriet';
  if (view === 'bids') return bid;
  if (view === 'away') return b.m === 'weg';
  if (view === 'all') return b.m !== 'weg';
  return true;
}
function passes(b) {
  if (view !== 'bids' && view !== 'fav' && b.res && !$('res').checked) return false;
  const q = $('q').value.trim().toLowerCase();
  if (q && !(b.t + ' ' + b.sp + ' ' + b.c + ' ' + b.no).toLowerCase().includes(q)) return false;
  const lo = parseFloat($('fmin').value), hi = parseFloat($('fmax').value);
  if (b.fr) { if ((!isNaN(lo) && b.fr[1] < lo) || (!isNaN(hi) && b.fr[0] > hi)) return false; }
  else if (!$('unk').checked) return false;
  const pmax = parseFloat($('pmax').value);
  if (!isNaN(pmax) && b.p != null && b.p > pmax) return false;
  if (HOME) {
    const km = parseFloat($('km').value);
    if (km < parseFloat($('km').max)) {
      if (b.km == null) { if (!$('nokm').checked) return false; }
      else if (b.km > km) return false;
    }
  }
  if ($('new').checked && !b.n) return false;
  return true;
}
const SORTS = {
  newest: (a, b) => (b.fs || '').localeCompare(a.fs || ''),
  flip: (a, b) => (b.fm ?? -1e9) - (a.fm ?? -1e9),
  value: (a, b) => (b.vr ?? -1) - (a.vr ?? -1),
  near: (a, b) => (a.km ?? 1e9) - (b.km ?? 1e9),
  upgrade: (a, b) => (b.uo - a.uo) || ((b.ug ?? -1e9) - (a.ug ?? -1e9)),
  cheap: (a, b) => (a.p ?? 1e9) - (b.p ?? 1e9),
};

const SOURCES = {eigen: 'eigen model', regel: 'eigen model via een regel', referentie: 'referentiemodel',
                 automatisch: 'herkend uit de titel'};
function modelLine(b) {
  if (!b.grp) return '<span class="muted">aan geen model gekoppeld</span>';
  return `gekoppeld aan <a href="#" data-model="${esc(b.mk)}">${esc(b.grp)}</a> <span class="muted">(${esc(SOURCES[b.src] || b.src)})</span>`
    + (b.ok ? ' <span class="cheap">✓ gecontroleerd</span>' : '')
    + ` · ${b.lk} advertentie${b.lk === 1 ? '' : 's'}`;
}
// "6 snel verkocht (≤7 d), mediaan €620 · 14 te koop, mediaan €690 — deze €480 (−23%)"
function compareLine(b) {
  if (!b.lv) return '';
  const parts = [];
  if (b.sv[0]) parts.push(`<span class="fast">${b.sv[0]} snel verkocht</span> (≤7 d), mediaan ${euro(b.sv[1])}`);
  if (b.tk[0]) parts.push(`${b.tk[0]} te koop, mediaan ${euro(b.tk[1])}`);
  const cls = b.fg ? '' : b.pc <= -10 ? 'cheap' : b.pc >= 10 ? 'dear' : '';
  const pc = b.pc == null ? '' : ` — deze ${euro(b.p)} (<strong class="${cls}">${b.pc > 0 ? '+' : b.pc < 0 ? '−' : ''}${Math.abs(b.pc)}%</strong> t.o.v. de schatting)`;
  return `<div class="why">vergeleken op ${esc(b.lv)}: ${parts.join(' · ') || 'alleen verdwenen advertenties'}${pc}</div>`;
}
function fixRow(b) {
  return '<div class="row fix">'
    + (b.grp && !b.ok ? '<button class="quiet" data-do="klopt" title="het model klopt">klopt</button>' : '')
    + '<button class="quiet" data-do="ander" title="toets m">ander model</button>'
    + `<label>bouwjaar <input name="jaar" value="${b.yo ? esc(b.yr) : ''}" placeholder="${b.yr && !b.yo ? esc(b.yr) : 'onbekend'}" size="5" maxlength="4" inputmode="numeric" aria-label="Bouwjaar"></label>`
    + '<button class="quiet" data-do="jaar">opslaan</button>'
    + (b.lnk ? '<button class="quiet" data-do="ontkoppel" title="terug naar wat de advertentie zegt">ontkoppelen</button>' : '')
    + '</div><div class="picker" hidden></div>';
}
function modelSearch(q) {
  const words = fold(q).split(/\s+/).filter(Boolean);
  if (!words.length) return MODELS.slice();
  return MODELS.filter(m => { const n = m._f || (m._f = fold(m.n)); return words.every(w => n.includes(w)); });
}
const PICK_MAX = 300;
function fillPicker(box, q) {
  const hits = modelSearch(q);
  box.querySelector('.plist').innerHTML = hits.slice(0, PICK_MAX).map(m => `<button type="button" class="pick" data-do="kies" data-v="${esc(m.n)}">${esc(m.n)} <span class="muted">${m.lk} gekoppeld${m.s === 'eigen' ? ' · eigen' : ''}</span></button>`).join('')
    + (hits.length > PICK_MAX ? `<div class="muted">nog ${hits.length - PICK_MAX} — typ om te zoeken</div>` : '')
    + (hits.length ? '' : '<div class="muted">niets gevonden — maak hieronder een nieuw model</div>');
}
function openPicker(art) {
  const box = art.querySelector('.picker');
  if (!box.hidden) { box.hidden = true; return; }
  box.innerHTML = '<input type="search" name="mq" placeholder="zoek een model, bv. domane sl6" aria-label="Zoek een model"><div class="plist"></div>'
    + '<div class="row"><input name="nieuw" size="34" maxlength="80" placeholder="nieuw model: merk model uitvoering, bv. Koga Kinsei Pro" aria-label="Nieuw model">'
    + '<button class="quiet" data-do="nieuw">aanmaken en koppelen</button></div>';
  box.hidden = false;
  fillPicker(box, '');
  box.querySelector('input[name=mq]').focus();
}
function mergeModels(items) {
  for (const m of items || []) {
    const i = MODELS.findIndex(x => x.k === m.k);
    if (m.gone) { if (i >= 0) MODELS.splice(i, 1); modelByKey.delete(m.k); continue; }
    if (i >= 0) MODELS[i] = m; else MODELS.push(m);
    modelByKey.set(m.k, m);
  }
  if (view === 'models') drawModelRows();
}

// --- Onderdelen: reserves voor het flippen (spares.py) ---
function passesPart(p) {
  const q = $('q').value.trim().toLowerCase();
  if (q && !(p.t + ' ' + p.c).toLowerCase().includes(q)) return false;
  const pmax = parseFloat($('pmax').value);
  if (!isNaN(pmax) && p.p != null && p.p > pmax) return false;
  if (HOME) {
    const km = parseFloat($('km').value);
    if (km < parseFloat($('km').max) && (p.km == null ? !$('nokm').checked : p.km > km)) return false;
  }
  return true;
}
function sparesShown() {
  const on = new Set(SPARES.on);
  return SPARES.parts.filter(p => p.m !== 'weg' && p.k.some(k => on.has(k)) && passesPart(p));
}
function partRow(p) {
  const img = p.img.length ? `<a href="${esc(p.u)}" target="_blank" rel="noopener"><img class="thumb" src="${esc(p.img[0])}" alt="" loading="lazy"></a>` : '';
  const km = p.km == null ? '' : `${p.kma ? 'ca. ' : ''}${p.km < 10 ? String(p.km).replace('.', ',') : Math.round(p.km)} km`;
  const last = p.b.length ? p.b[p.b.length - 1] : null;
  const fav = p.m === 'favoriet' ? '<button class="quiet" data-part="geen">★ uit favorieten</button>' : '<button class="quiet" data-part="fav">☆ favoriet</button>';
  return `<tr data-part-id="${esc(p.id)}"><td>${img}</td>`
    + `<td><a href="${esc(p.u)}" target="_blank" rel="noopener">${esc(p.t)}</a>${p.m === 'favoriet' ? ' <span class="badge fav">★</span>' : ''}${p.res ? ' <span class="badge reserved">gereserveerd</span>' : ''}`
    + `<div class="muted">${esc(p.c)} · ${esc(p.cat)} · sinds ${esc((p.fs || '').slice(0, 10))}${last ? ` · jouw bod ${euro(last.a)} (${esc(last.s)})` : ''}</div></td>`
    + `<td class="num"><strong>${euro(p.p)}</strong><div class="muted">${esc(p.pk)}</div></td><td class="num">${km}</td>`
    + `<td><div class="row">${fav}<button class="quiet" data-part="weg" title="niet waard">weg</button>`
    + `<label>€<input name="bod" size="4" inputmode="decimal" aria-label="Bod"></label><button class="quiet" data-part="bod">ik heb geboden</button></div></td></tr>`;
}
function drawSpares() {
  const on = new Set(SPARES.on);
  const shownParts = sparesShown();
  const chips = SPARES.kinds.map(([k, label, n]) => `<button class="quiet chip${on.has(k) ? ' on' : ''}" data-kind="${esc(k)}" aria-pressed="${on.has(k)}">${esc(label)} <span class="n">${n}</span></button>`).join('');
  const groups = SPARES.kinds.filter(([k]) => on.has(k)).map(([k, label, n]) => {
    const parts = shownParts.filter(p => p.k.includes(k)).sort((a, b) => (a.p ?? 1e9) - (b.p ?? 1e9));
    return `<h3>${esc(label)} <span class="muted">${parts.length}${n > parts.length ? ` van ${n}` : ''}</span></h3>`
      + (parts.length ? `<div class="table-wrap"><table class="spares"><tbody>${parts.map(partRow).join('')}</tbody></table></div>`
                      : '<p class="empty">Nu niets te koop in wat de rondes vinden.</p>');
  }).join('');
  $('spareview').innerHTML = '<p class="explain">Losse onderdelen die de rondes toch al tegenkomen, als reserve of extra voor je flips. Zet aan waar je reserves van wilt; per soort de goedkoopste (hooguit 40), met favoriet, weg en je bod zoals bij de fietsen. Weggezette staan er niet bij. De rondes zoeken vooral hele racefietsen, dus het zijn er weinig.</p>'
    + `<div class="chips">${chips}</div>${groups || '<p class="empty">Zet hierboven een soort aan.</p>'}`;
}
function updatePart(p) {
  const i = SPARES.parts.findIndex(x => x.id === p.id);
  if (i >= 0) SPARES.parts[i] = p; else SPARES.parts.push(p);
  if (view === 'spares') drawSpares();
  counts();
}

function card(b) {
  const imgs = b.img.length ? b.img.map(u => `<a href="${esc(b.u)}" target="_blank" rel="noopener"><img src="${esc(u)}" alt="" loading="lazy"></a>`).join('')
    : '<div class="empty"></div>';
  const badges = (b.m === 'favoriet' ? '<span class="badge fav">★ favoriet</span> ' : '')
    + (b.m === 'weg' ? `<span class="badge reserved">weggezet (${esc(b.mr)})</span> ` : '')
    + (b.n ? '<span class="badge">nieuw</span> ' : '') + (b.res ? '<span class="badge reserved">gereserveerd</span> ' : '')
    + (b.promo ? `<span class="badge" title="betaalde promotie">${esc(b.promo.toLowerCase())}</span> ` : '')
    + (b.own ? `<span class="badge fav">✓ gekocht ${esc(b.own)}</span> ` : '');
  const km = b.km == null ? '' : `<span class="km">${b.kma ? 'ca. ' : ''}${b.km < 10 ? String(b.km).replace('.', ',') : Math.round(b.km)} km</span>`;
  const flip = b.fm == null ? '<span class="pill bad">flip —</span>'
    : `<span class="pill ${b.fm > 0 && !b.fg ? 'good' : 'bad'}" title="${esc(b.fb)}">flip ${signed(b.fm)}${b.fg ? ' (onzeker)' : ''}</span>`;
  const upg = b.uo ? `<span class="pill good" title="${esc(b.uw)}">upgrade +${b.ug}</span>`
    : `<span class="pill bad" title="${esc(b.uw)}">geen upgrade</span>`;
  const vr = b.vr == null ? '' : `<span class="pill ${b.vr >= 1.1 ? 'good' : ''}" title="geschatte waarde / prijs">waarde ${String(b.vr.toFixed(2)).replace('.', ',')}</span>`;
  const st = b.st ? `<div class="why">${b.st.v != null ? b.st.v + '× bekeken' : ''}${b.st.f != null ? ' · ' + b.st.f + '× bewaard' : ''}${b.st.df ? ` (${b.st.df > 0 ? '+' : ''}${b.st.df} sinds vorige meting)` : ''} · gemeten ${esc(b.st.at)}</div>` : '';
  const reasons = REASONS.map((r, i) => `<button class="quiet" data-do="weg" data-v="${esc(r)}" title="toets ${i + 1}">${esc(r)}</button>`).join('');
  const markBtns = b.m === 'weg' ? '<button class="quiet" data-do="geen">terugzetten</button>'
    : (b.m === 'favoriet' ? '<button class="quiet" data-do="geen">★ uit favorieten</button>' : '<button class="quiet" data-do="fav">☆ favoriet</button>')
      + '<span class="muted">weg:</span>' + reasons;
  const last = b.b.length ? b.b[b.b.length - 1] : null;
  const hist = b.b.map(x => `${euro(x.a)} op ${esc(x.at)}`).join(', ');
  const bidRow = `<div class="row bids">${last ? `<span>jouw bod: <span class="st">${euro(last.a)} — ${esc(last.s)}</span>${b.b.length > 1 ? ` <span class="muted">(${hist})</span>` : ''}</span>`
      + STATUSES.filter(s => s !== last.s).map(s => `<button class="quiet" data-do="status" data-v="${esc(s)}">${esc(s)}</button>`).join('') : ''}
    <label>€<input name="bod" inputmode="decimal" size="5" aria-label="Bod"></label><button class="quiet" data-do="bod">${last ? 'nieuw bod' : 'ik heb geboden'}</button></div>`;
  return `<article class="bike${b.m === 'weg' ? ' away' : ''}" data-id="${esc(b.id)}">
    <div class="photos">${imgs}</div>
    <div>
      <div class="top"><span class="price">${euro(b.p)}</span><span class="muted">${esc(b.pk)}${b.bi ? ' · ' + esc(b.bi) : ''}</span>${km}<span>${badges}</span></div>
      <a class="title" href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a>
      <div class="link">${modelLine(b)}</div>
      ${compareLine(b)}
      ${fixRow(b)}
      <span class="muted">${esc(b.c)}</span>
      <div class="specs">${esc(b.sp) || '<span class="muted">geen specs in de advertentie</span>'}</div>
      <div class="verdicts">${flip}${upg}${vr}</div>
      <div class="why">${b.rs != null ? 'verkoop ca. ' + euro(b.rs) + ' — ' : ''}${esc(b.fb)}</div>
      <div class="why">${esc(b.uw)}</div>
      ${st}
      ${b.back ? `<div class="note">${esc(b.back)}</div>` : ''}
      ${b.no ? `<div class="mynote">${esc(b.no)}</div>` : ''}
      ${b.nc ? `<details class="desc cmp"><summary>vergeleken met ${b.nc} fietsen${b.nc > COMPS_SHOWN ? ` (hier ${COMPS_SHOWN}: de snel verkochte en de goedkoopste)` : ''}</summary><div>${b.cmp ? cmpHtml(b.cmp) : 'laden…'}</div></details>` : ''}
      <details class="desc"><summary>beschrijving</summary><div>${esc(b.d)}</div></details>
      <div class="row">${markBtns}<span class="muted">·</span><button class="quiet" data-do="check">controleer</button><button class="quiet" data-do="dossier" title="haalt de advertentie op zoals controleer en kopieert alles over deze fiets als tekst voor Claude">dossier</button>${b.ck ? `<span class="muted">gecontroleerd ${esc(b.ck.replace('T', ' '))}</span>` : ''}</div>
      ${bidRow}
      <div class="row"><input name="notitie" value="${esc(b.no)}" maxlength="500" size="34" placeholder="notitie, bv. gevraagd of €300 kan" aria-label="Notitie"><button class="quiet" data-do="note">opslaan</button></div>
    </div></article>`;
}

function counts() {
  const n = {open: 0, fav: 0, bids: 0, all: 0, away: 0};
  const save = view;
  for (const k of Object.keys(n)) { view = k; n[k] = BIKES.filter(b => inView(b) && passes(b)).length; }
  view = save;
  n.bids += GONE.length;
  document.querySelectorAll('.views button[data-view]').forEach(bt => {
    const k = bt.dataset.view; if (k in n) bt.textContent = bt.dataset.label + ' (' + n[k] + ')';
    if (k === 'models') bt.textContent = bt.dataset.label + (RULES.p.length ? ` (${RULES.p.length} voorstel${RULES.p.length === 1 ? '' : 'len'})` : '');
    if (k === 'spares') bt.textContent = bt.dataset.label + ` (${sparesShown().length})`;
  });
}
// De lijst met alle modellen: eigen, referentie en herkend, ook zonder
// advertenties; zoeken, sorteren op een kolom, en tekenen in porties.
const MODEL_COLS = [['n', 'Model'], ['a', 'Te koop'], ['lk', 'Gekoppeld'], ['f', 'Snel verkocht'], ['fm', 'Mediaan snel'],
                    ['m', 'Mediaan vraag'], ['lo', 'Laagste']];
const MODEL_BATCH = 200;
let modelSort = 'lk', modelDesc = true, modelRows = [], modelDrawn = 0;
function drawModels() {
  const box = $('modellist');
  if (!box.dataset.ready) {
    box.innerHTML = '<p class="explain">Elke fiets hangt aan een model: merk + model + uitvoering uit de titel ("Trek Domane SL6"), een referentiemodel uit reference_bikes.csv, of een model dat je zelf koppelde of aanmaakte (<em>eigen</em>). Klik op een model om zijn fietsen te zien. <em>Gekoppeld</em> telt ook verdwenen advertenties van de laatste 180 dagen; <em>snel verkocht</em> is binnen 7 dagen verdwenen of gereserveerd en daarna weg.</p>'
      + '<div id="rulebox"></div>'
      + '<div class="row"><input id="newmodel" size="40" maxlength="80" placeholder="nieuw model toevoegen: merk model uitvoering, bv. Koga Kinsei Pro" aria-label="Nieuw model"><button class="quiet" id="addmodel">toevoegen</button></div>'
      + '<div class="row"><input type="search" id="msearch" size="30" placeholder="zoek een model" aria-label="Zoek een model"><span class="muted" id="mcount"></span></div>'
      + `<div class="table-wrap"><table><thead><tr>${MODEL_COLS.map(([k, l]) => `<th${k === 'n' ? '' : ' class="num"'} data-sort="${k}">${l}</th>`).join('')}</tr></thead><tbody id="mbody"></tbody></table></div>`;
    box.dataset.ready = '1';
    $('msearch').addEventListener('input', drawModelRows);
    $('addmodel').addEventListener('click', addModel);
    $('newmodel').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addModel(); } });
    $('rulebox').addEventListener('click', e => {
      const bt = e.target.closest('button[data-rule]'); if (!bt) return;
      post(RULE_PATH, {from_key: bt.dataset.k, model_id: bt.dataset.m, answer: bt.dataset.rule}, $('rulebox'));
    });
    box.querySelector('thead').addEventListener('click', e => {
      const th = e.target.closest('th[data-sort]'); if (!th) return;
      if (modelSort === th.dataset.sort) modelDesc = !modelDesc; else { modelSort = th.dataset.sort; modelDesc = modelSort !== 'n'; }
      drawModelRows();
    });
  }
  drawRules(); drawModelRows();
}
// Voorstellen (na drie dezelfde correcties) en de regels die je toepaste.
function drawRules() {
  const box = $('rulebox'); if (!box) return;
  const btn = (r, what, label) => `<button class="quiet" data-rule="${what}" data-k="${esc(r.k)}" data-m="${r.id}">${label}</button>`;
  const p = RULES.p.map(r => `<div class="note">Voorstel: advertenties die als <strong>${esc(r.kn)}</strong> herkend worden → <strong>${esc(r.m)}</strong>? <span class="muted">(${r.n} keer zo gekoppeld)</span> ${btn(r, 'toepassen', 'toepassen')} ${btn(r, 'nee', 'nee')}</div>`).join('');
  const a = RULES.r.length ? `<details class="desc"><summary>${RULES.r.length} regel${RULES.r.length === 1 ? '' : 's'} toegepast</summary><div>${RULES.r.map(r => `${esc(r.kn)} → ${esc(r.m)} <span class="muted">(${r.n} advertenties)</span> ${btn(r, 'weg', 'weghalen')}`).join('<br>')}</div></details>` : '';
  box.innerHTML = p + a;
}
function drawModelRows() {
  if (!$('mbody')) return;
  const dir = modelDesc ? -1 : 1;
  modelRows = modelSearch($('msearch').value).sort((x, y) => {
    if (modelSort === 'n') return dir * fold(x.n).localeCompare(fold(y.n));
    const a = x[modelSort], b = y[modelSort];
    if (a == null || b == null) return a == null && b == null ? 0 : a == null ? 1 : -1;  // leeg altijd onderaan
    return dir * (a - b) || fold(x.n).localeCompare(fold(y.n));
  });
  $('modellist').querySelectorAll('th[data-sort]').forEach(th => {
    const label = MODEL_COLS.find(c => c[0] === th.dataset.sort)[1];
    th.textContent = label + (th.dataset.sort === modelSort ? (modelDesc ? ' ↓' : ' ↑') : '');
  });
  $('mbody').innerHTML = ''; modelDrawn = 0;
  $('mcount').textContent = modelRows.length + ' modellen';
  drawMoreModels();
}
function drawMoreModels() {
  const html = modelRows.slice(modelDrawn, modelDrawn + MODEL_BATCH).map(m =>
    `<tr><td><a href="#" data-model="${esc(m.k)}">${esc(m.n)}</a> <span class="muted">${m.s === 'automatisch' ? 'herkend' : esc(m.s)}</span></td>`
    + `<td class="num">${m.a}</td><td class="num">${m.lk}</td><td class="num">${m.f || ''}</td><td class="num">${m.fm == null ? '' : euro(m.fm)}</td>`
    + `<td class="num">${euro(m.m)}</td><td class="num">${euro(m.lo)}</td></tr>`).join('');
  $('mbody').insertAdjacentHTML('beforeend', html);
  modelDrawn = Math.min(modelDrawn + MODEL_BATCH, modelRows.length);
  more.hidden = modelDrawn >= modelRows.length;
  more.textContent = modelDrawn < modelRows.length ? `nog ${modelRows.length - modelDrawn} modellen — scroll verder` : '';
}
function addModel() {
  const input = $('newmodel'), v = input.value.trim();
  if (!v) { input.focus(); return; }
  post(MODEL_PATH, {model: v}).then(d => { if (d && d.models) input.value = ''; });
}
document.addEventListener('click', e => {
  const a = e.target.closest('a[data-model]'); if (!a) return;
  e.preventDefault();
  modelFilter = a.dataset.model;
  if (NO_CARDS.includes(view)) view = 'all';
  document.querySelectorAll('.views button').forEach(x => x.classList.toggle('on', x.dataset.view === view));
  draw(); window.scrollTo(0, 0);
});
const NO_CARDS = ['models', 'patterns', 'spares', 'flips'];
function draw() {
  shown = NO_CARDS.includes(view) ? [] : BIKES.filter(b => inView(b) && passes(b)).sort(SORTS[$('sort').value] || SORTS.newest);
  list.innerHTML = ''; drawn = 0; cur = -1;
  $('modellist').hidden = view !== 'models';
  $('modelchip').hidden = !modelFilter;
  const chip = modelFilter ? ((modelByKey.get(modelFilter) || {}).n || (BIKES.find(b => b.mk === modelFilter) || {}).grp || modelFilter) : '';
  $('modelchip').innerHTML = modelFilter ? `model: <strong>${esc(chip)}</strong> <button class="quiet" id="nomodel">× alle modellen</button>` : '';
  if (modelFilter) $('nomodel').onclick = () => { modelFilter = ''; draw(); };
  $('patterns').hidden = view !== 'patterns';
  $('gonebids').hidden = view !== 'bids' || !GONE.length;
  list.hidden = NO_CARDS.includes(view);
  $('spareview').hidden = view !== 'spares';
  $('flipview').hidden = view !== 'flips';
  $('count').textContent = NO_CARDS.includes(view) ? '' : shown.length + ' fietsen';
  if (view === 'models') drawModels(); else if (view === 'spares') { drawSpares(); more.hidden = true; } else drawMore();
  counts(); remember();
}
function drawMore() {
  if (view === 'models') { drawMoreModels(); return; }
  if (view === 'patterns' || view === 'spares' || view === 'flips') { more.hidden = true; return; }
  const html = shown.slice(drawn, drawn + BATCH).map(card).join('');
  list.insertAdjacentHTML('beforeend', html);
  drawn = Math.min(drawn + BATCH, shown.length);
  more.hidden = drawn >= shown.length;
  more.textContent = drawn < shown.length ? `nog ${shown.length - drawn} — scroll verder` : '';
}
new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) drawMore(); }, {rootMargin: '800px'}).observe(more);

function el(id) { return list.querySelector(`article[data-id="${CSS.escape(id)}"]`); }
function focusAt(i) {
  const cards = list.querySelectorAll('article.bike');
  if (!cards.length) { cur = -1; return; }
  cur = Math.max(0, Math.min(i, cards.length - 1));
  if (cur >= cards.length - 3 && drawn < shown.length) drawMore();
  cards.forEach((c, j) => c.classList.toggle('cur', j === cur));
  cards[cur].scrollIntoView({block: 'nearest'});
}
function curId() { const c = list.querySelectorAll('article.bike')[cur]; return c ? c.dataset.id : null; }

// Na een klik: de fiets vervangen, of weghalen als hij niet meer in deze weergave hoort.
function update(b) {
  if (!b) return;
  const i = BIKES.findIndex(x => x.id === b.id);
  if (i >= 0) BIKES[i] = b; else BIKES.push(b);
  byId.set(b.id, b);
  const old = el(b.id);
  if (old) {
    if (inView(b) && passes(b)) { old.outerHTML = card(b); }
    else {
      const idx = Array.from(list.children).indexOf(old);
      old.remove(); shown = shown.filter(x => x.id !== b.id); drawn--;
      if (idx <= cur) cur = Math.max(-1, cur - (idx < cur ? 1 : 0));
    }
  }
  $('count').textContent = shown.length + ' fietsen';
  counts();
  if (cur >= 0) focusAt(cur);
}
// toast, say() en pageData komen uit LIVE_JS (dashboard.py), net als de
// postcodeknop (een gewone .act, met herladen).
function post(path, fields, box) {
  const body = new URLSearchParams({token: pageData.token, markt: 'racefietsen', ...fields});
  if (box) box.classList.add('busy');
  return fetch(path, {method: 'POST', body, headers: {'X-Live': '1'}})
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(data => {
      if (data.reload) { location.reload(); return; }
      say(data.message);
      if (data.rules) { RULES = data.rules; if (view === 'models') drawRules(); counts(); }
      if (data.models) mergeModels(data.models);
      if (data.part) updatePart(data.part);
      if (data.on) SPARES.on = data.on;
      if (data.flips) {
        $('flipview').innerHTML = data.flips[1];
        const bt = document.querySelector('.views button[data-view=flips]');
        bt.dataset.label = bt.textContent = data.flips[0] ? `Mijn flips (${data.flips[0]})` : 'Mijn flips';
      }
      update(data.bike); (data.bikes || []).forEach(update);
      return data;
    })
    .catch(() => say('Niet gelukt; ververs de pagina (F5) en probeer het opnieuw.'))
    .finally(() => { if (box) box.classList.remove('busy'); });
}
// De laatst gemarkeerde fiets: u zet die terug als de fiets onder de cursor
// niets heeft (in Te beoordelen verdwijnt een gemarkeerde fiets meteen).
let lastMarked = null;
function reinsert(b, before) {
  if (el(b.id) || !(inView(b) && passes(b)) || !before || !before.isConnected) return;
  const at = shown.findIndex(x => x.id === before.dataset.id);
  if (at < 0) return;
  shown.splice(at, 0, b); drawn++;
  before.insertAdjacentHTML('beforebegin', card(b));
  $('count').textContent = shown.length + ' fietsen';
  focusAt(at);
}
function act(id, what, value, art) {
  const b = byId.get(id); if (!b) return;
  if (what === 'fav' || what === 'weg') lastMarked = id;
  if (what === 'fav') return post('/markeer', {item_id: id, soort: 'favoriet'}, art);
  if (what === 'weg') return post('/markeer', {item_id: id, soort: value}, art);
  if (what === 'geen') return post('/markeer', {item_id: id, soort: 'geen'}, art);
  if (what === 'check') return post('/controleer', {item_id: id}, art);
  if (what === 'dossier') return post(DOSSIER_PATH, {item_id: id}, art).then(data => {
    if (data && data.dossier) showDossier(id, data.dossier, data.message);
  });
  if (what === 'note') return post('/notitie', {item_id: id, notitie: art.querySelector('input[name=notitie]').value}, art);
  if (what === 'bod') {
    const v = art.querySelector('input[name=bod]').value.trim();
    if (!v) { art.querySelector('input[name=bod]').focus(); return; }
    return post('/bod', {item_id: id, bedrag: v}, art);
  }
  if (what === 'status') return post('/bod/status', {item_id: id, status: value}, art);
  // Het model en het bouwjaar (bike_link): de server rekent alleen deze fiets opnieuw.
  if (what === 'klopt') return post(MODEL_PATH, {item_id: id, confirm: '1'}, art);
  if (what === 'ander') return openPicker(art);
  if (what === 'kies') return post(MODEL_PATH, {item_id: id, model: value}, art);
  if (what === 'nieuw') {
    const v = art.querySelector('input[name=nieuw]').value.trim();
    if (!v) { art.querySelector('input[name=nieuw]').focus(); return; }
    return post(MODEL_PATH, {item_id: id, model: v}, art);
  }
  if (what === 'jaar') return post(MODEL_PATH, {item_id: id, year: art.querySelector('input[name=jaar]').value.trim()}, art);
  if (what === 'ontkoppel') return post(MODEL_PATH, {item_id: id, clear: '1'}, art);
}
// Het dossier (dossier.py): alles over één fiets als tekst voor Claude. Meteen
// naar het klembord; lukt dat niet (de browser wil een klik, en het ophalen
// duurde even), dan staat het in het venster met een knop kopieer.
let dossierUrl = null;
function showDossier(id, text, message) {
  const box = $('dossier');
  $('dtext').value = text;
  $('dsize').textContent = Math.round(text.length / 1000) + ' kB';
  if (dossierUrl) URL.revokeObjectURL(dossierUrl);
  dossierUrl = URL.createObjectURL(new Blob([text], {type: 'text/markdown;charset=utf-8'}));
  $('dsave').href = dossierUrl; $('dsave').download = 'dossier_' + id + '.md';
  box.hidden = false;
  copyDossier(message);
}
function copyDossier(message) {
  const text = $('dtext');
  const done = () => say((message ? message + ' ' : '') + 'Dossier gekopieerd: plak het in een gesprek met Claude.');
  const fallback = () => {
    text.focus(); text.select();
    try { if (document.execCommand('copy')) return done(); } catch (e) { /* hieronder */ }
    say((message ? message + ' ' : '') + 'Kopiëren lukte niet vanzelf: klik kopieer, of Ctrl+C (alles is al geselecteerd).');
  };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text.value).then(done, fallback);
  else fallback();
}
function closeDossier() { $('dossier').hidden = true; }
$('dcopy').addEventListener('click', () => copyDossier(''));
$('dclose').addEventListener('click', closeDossier);
// Alleen een klik die op de achtergrond begon sluit: een selectie in de tekst
// die je buiten het venster loslaat, telt in Chrome ook als klik daar.
let downOnBackdrop = false;
$('dossier').addEventListener('mousedown', e => { downOnBackdrop = e.target.id === 'dossier'; });
$('dossier').addEventListener('click', e => { if (e.target.id === 'dossier' && downOnBackdrop) closeDossier(); });
function cmpHtml(comps) {
  return comps.map(c => `<a href="${esc(c[2])}" target="_blank" rel="noopener">${esc(c[0])}</a> — ${euro(c[1])}${c[3] ? ' · ' + c[3] : ''}${c[5] ? ' · <span class="fast">snel verkocht</span> ' + esc(c[4]) : c[4] ? ' · verdwenen ' + esc(c[4]) : ''}`).join('<br>');
}
// De vergelijkingslijst komt pas van de server als je hem openklapt: in de
// pagina was hij twee derde van alles. 'toggle' bubbelt niet, dus capture.
list.addEventListener('toggle', e => {
  const box = e.target;
  if (!box.matches || !box.matches('details.cmp') || !box.open) return;
  const b = byId.get(box.closest('article.bike').dataset.id);
  if (!b || b.cmp) return;
  fetch(COMPS_PATH + '?id=' + encodeURIComponent(b.id))
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(data => {
      if (data.cmp) b.cmp = data.cmp;
      box.querySelector('div').innerHTML = data.cmp ? cmpHtml(data.cmp) : 'Niet meer te vinden; ververs de pagina (F5).';
    })
    .catch(() => { box.querySelector('div').textContent = 'Niet gelukt; ververs de pagina (F5).'; });
}, true);
list.addEventListener('click', e => {
  const bt = e.target.closest('button[data-do]'); if (!bt) return;
  const art = bt.closest('article.bike');
  const cards = Array.from(list.querySelectorAll('article.bike'));
  cur = cards.indexOf(art); cards.forEach((c, j) => c.classList.toggle('cur', j === cur));
  act(art.dataset.id, bt.dataset.do, bt.dataset.v, art);
});
list.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !e.target.matches('input')) return;
  e.preventDefault();
  const art = e.target.closest('article.bike');
  const what = {bod: 'bod', notitie: 'note', jaar: 'jaar', nieuw: 'nieuw'}[e.target.name];
  if (what) act(art.dataset.id, what, null, art);
});
list.addEventListener('input', e => { if (e.target.name === 'mq') fillPicker(e.target.closest('.picker'), e.target.value); });
document.addEventListener('keydown', e => {
  if (!$('dossier').hidden) { if (e.key === 'Escape') closeDossier(); return; }
  if (e.target.matches('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) {
    if (e.key === 'Escape') e.target.blur();
    return;
  }
  const k = e.key.toLowerCase();
  if (k === 'j' || e.key === 'ArrowDown') { e.preventDefault(); focusAt(cur + 1); return; }
  if (k === 'k' || e.key === 'ArrowUp') { e.preventDefault(); focusAt(cur - 1); return; }
  const id = curId(); if (!id) return;
  const art = el(id);
  if (k === 'f') act(id, byId.get(id).m === 'favoriet' ? 'geen' : 'fav', null, art);
  else if (k === 'w') act(id, 'weg', REASONS[0], art);
  else if (/^[1-9]$/.test(k) && REASONS[+k - 1]) act(id, 'weg', REASONS[+k - 1], art);
  else if (k === 'u') {
    const target = byId.get(id).m || !lastMarked || !byId.get(lastMarked) ? id : lastMarked;
    lastMarked = null;
    const done = act(target, 'geen', null, el(target) || art);
    if (target !== id && done) done.then(data => { if (data && data.bike) reinsert(data.bike, art); });
  }
  else if (k === 'c') act(id, 'check', null, art);
  else if (k === 'd') act(id, 'dossier', null, art);
  else if (k === 'm') { e.preventDefault(); act(id, 'ander', null, art); }
  else if (k === 'o') window.open(byId.get(id).u, '_blank', 'noopener');
  else if (k === 'b') { e.preventDefault(); art.querySelector('input[name=bod]').focus(); }
  else if (k === 'n') { e.preventDefault(); art.querySelector('input[name=notitie]').focus(); }
  else if (k === ' ') { e.preventDefault(); const d = art.querySelector('details.desc:not(.cmp)'); d.open = !d.open; }
});
document.querySelectorAll('.views button[data-view]').forEach(bt => bt.addEventListener('click', () => {
  view = bt.dataset.view;
  document.querySelectorAll('.views button').forEach(x => x.classList.toggle('on', x === bt));
  draw();
}));
$('spareview').addEventListener('click', e => {
  const chip = e.target.closest('button[data-kind]');
  if (chip) {
    const on = new Set(SPARES.on), k = chip.dataset.kind;
    if (on.has(k)) on.delete(k); else on.add(k);
    SPARES.on = SPARES.kinds.map(x => x[0]).filter(x => on.has(x));
    drawSpares(); counts();
    post(RESERVE_PATH, {soorten: SPARES.on.join(',')});
    return;
  }
  const bt = e.target.closest('button[data-part]'); if (!bt) return;
  const tr = bt.closest('tr'), id = tr.dataset.partId;
  if (bt.dataset.part === 'fav') post('/markeer', {item_id: id, soort: 'favoriet'}, tr);
  else if (bt.dataset.part === 'geen') post('/markeer', {item_id: id, soort: 'geen'}, tr);
  else if (bt.dataset.part === 'weg') post('/markeer', {item_id: id, soort: REASONS[0]}, tr);
  else if (bt.dataset.part === 'bod') {
    const input = tr.querySelector('input[name=bod]');
    if (!input.value.trim()) { input.focus(); return; }
    post('/bod', {item_id: id, bedrag: input.value.trim()}, tr);
  }
});
$('spareview').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.target.name !== 'bod') return;
  e.preventDefault(); e.target.closest('tr').querySelector('button[data-part=bod]').click();
});
const kmOut = $('kmval');
function kmLabel() { if (!kmOut) return; const v = +$('km').value; kmOut.textContent = v >= +$('km').max ? 'alles' : 'max ' + v + ' km'; }
['q', 'sort', 'fmin', 'fmax', 'unk', 'pmax', 'km', 'nokm', 'res', 'new'].forEach(id => $(id) && $(id).addEventListener('input', () => { kmLabel(); draw(); }));
restoreFilters(); kmLabel();
document.querySelectorAll('.views button').forEach(x => x.classList.toggle('on', x.dataset.view === view));
draw();
// Telefoon: de filters achter één knop (CSS verbergt ze zolang .bar niet open is).
$('filtersbtn').addEventListener('click', () => {
  const bar = document.querySelector('.bar'), open = bar.classList.toggle('open');
  $('filtersbtn').setAttribute('aria-expanded', String(open));
  $('filtersbtn').textContent = open ? 'Filters ▴' : 'Filters ▾';
});
// De gekozen weergave in beeld in de rij die zijwaarts scrollt.
function showView() {
  const on = document.querySelector('.views button.on');
  if (on && on.parentElement.scrollWidth > on.parentElement.clientWidth)
    on.parentElement.scrollLeft = on.offsetLeft - on.parentElement.offsetLeft - 8;
}
showView();
document.querySelectorAll('.views button').forEach(x => x.addEventListener('click', showView));
