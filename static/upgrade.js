
(() => {
const D = JSON.parse(document.getElementById('data').textContent);
const token = document.querySelector('main').dataset.token || '';
const LABEL = {ja: 'upgrade', nee: 'geen upgrade', twijfel: 'twijfel'};
const toast = document.getElementById('toast');
let toastTimer = null;
function say(message) {
  if (!message) return;
  toast.textContent = message; toast.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 3500);
}
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const nl = (x, d = 1) => x == null ? '—' : Number(x).toFixed(d).replace('.', ',');
const signed = (x, d = 1) => x == null ? '—' : (x > 0 ? '+' : '') + nl(x, d);
const euro = x => x == null ? '—' : '€' + Math.round(x).toLocaleString('nl-NL');
const byId = Object.fromEntries(D.bikes.map(b => [b.id, b]));
let S = D.s, own = D.own, rule = D.rule;
const labels = {};
D.bikes.forEach(b => { if (b.lab) labels[b.id] = b.lab; });

function post(path, data) {
  const body = new URLSearchParams({token, ...data});
  return fetch(path, {method: 'POST', body}).then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(j => { if (j.reload) { location.reload(); return Promise.reject('reload'); } return j; });
}

// --- tabbladen
const tabs = document.getElementById('tabs');
function showTab(name) {
  if (!document.getElementById('p-' + name)) name = 'test';
  tabs.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.panel === name));
  document.querySelectorAll('section.panel').forEach(s => { s.hidden = s.id !== 'p-' + name; });
  if (name === 'uitslag') renderAgree();
  if (name === 'uitdraai') renderOut();
}
tabs.addEventListener('click', e => {
  const b = e.target.closest('button[data-panel]');
  if (!b) return;
  showTab(b.dataset.panel);
  history.replaceState(null, '', '#' + b.dataset.panel);
});
document.addEventListener('click', e => {
  const a = e.target.closest('[data-goto]');
  if (!a) return;
  e.preventDefault(); showTab(a.dataset.goto); history.replaceState(null, '', '#' + a.dataset.goto);
});

function renderOwn() {
  document.getElementById('ownscore').textContent = `${nl(own.tot, 0)}/100 (`
    + D.dimnames.map((n, i) => `${n} ${nl(own.dims[i], 0)}`).join(' · ') + `) · marge ${nl(own.margin)}`;
}

// --- uitleg per fiets, onthouden per regel
const explained = {};
const ruleKey = () => JSON.stringify(rule);
function explainFor(id) {
  const key = id + '|' + ruleKey();
  if (!explained[key]) explained[key] = post(D.paths.explain, {item_id: id, regel: ruleKey()})
    .then(j => j.error ? null : j, () => null);
  return explained[key];
}
function partsTable(info) {
  return '<div class="table-wrap"><table class="parts"><thead><tr><th>Onderdeel</th><th class="num">Fiets</th>'
    + '<th class="num">Jouw fiets</th><th class="num">Telt</th><th>Waarom</th></tr></thead><tbody>'
    + info.onderdelen.map(p => `<tr><td>${esc(p.naam)}</td><td class="num">${nl(p.fiets, 0)}</td>`
      + `<td class="num">${nl(p.eigen, 0)}</td><td class="num"><span class="delta ${p.punten > 0.05 ? 'plus' : p.punten < -0.05 ? 'minus' : ''}">${signed(p.punten)}</span></td>`
      + `<td class="why">${esc(p.waarom)}</td></tr>`).join('')
    + `</tbody></table></div><p class="sub">${esc(info.redenen.join(' · '))}</p>`;
}
function verdictLine(id) {
  const s = S[id];
  if (!s) return '';
  return `Regel: ${nl(s[0])} tegen jouw ${nl(own.tot)} = <strong>${signed(s[1])}</strong> → `
    + (s[2] ? '<span class="good">beter dan jouw fiets</span>' : '<span class="bad">niet beter</span>')
    + ` (marge ${nl(own.margin)})` + (s[3] ? ' · ook een upgrade op /racefietsen (maat en budget)' : '');
}

// --- de test
const skipped = new Set();
const answered = [];
let current = null;
const nextId = (not) => D.queue.find(id => id !== not && !labels[id] && !skipped.has(id) && S[id]);
function progress() {
  const values = Object.values(labels);
  const count = v => values.filter(x => x === v).length;
  const left = D.queue.filter(id => !labels[id] && !skipped.has(id) && S[id]).length;
  document.getElementById('progress').textContent = `${values.length} beoordeeld: ${count('ja')} ja, `
    + `${count('nee')} nee, ${count('twijfel')} twijfel · nog ${left} in de rij`
    + (skipped.size ? ` (${skipped.size} overgeslagen)` : '');
}
function pics(urls) {
  return (urls || []).map(u => `<img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer">`).join('');
}
function showCard() {
  current = nextId();
  progress();
  const card = document.getElementById('card');
  if (!current) {
    card.innerHTML = '<p class="empty">Alles wat nu te koop is heeft een oordeel of is overgeslagen. Na de volgende ronde komen er nieuwe fietsen bij.</p>';
    return;
  }
  const b = byId[current];
  card.innerHTML = `<div class="pics" id="pics">${pics(b.img)}</div><div>`
    + `<h2><a href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a></h2>`
    + `<div class="price">${euro(b.p)} <span class="muted">${esc(b.pk)}</span></div>`
    + `<div class="specs">${esc(b.sp) || '<span class="muted">geen specs herkend</span>'}</div>`
    + `<div class="q">Is dit een upgrade van jouw ${esc(D.label)}? <span class="muted">Los van prijs en maat.</span></div>`
    + `<div class="peekbox" id="peekbox"></div><div class="desc" id="desc">…</div></div>`;
  const id = current;
  explainFor(id).then(info => {
    if (current !== id) return;
    const desc = document.getElementById('desc');
    if (!info) { desc.textContent = ''; return; }
    if (info.img && info.img.length > (b.img || []).length) document.getElementById('pics').innerHTML = pics(info.img);
    desc.textContent = info.d || '(geen omschrijving)';
  });
  renderPeek();
  const following = nextId(id);
  if (following) explainFor(following);
}
function renderPeek() {
  const box = document.getElementById('peekbox');
  if (box) box.innerHTML = current && document.getElementById('peek').checked ? verdictLine(current) : '';
}
document.getElementById('peek').addEventListener('change', renderPeek);
function showLast(id) {
  const box = document.getElementById('last');
  if (!id || !labels[id]) { box.innerHTML = ''; return; }
  const b = byId[id], lab = labels[id], s = S[id];
  const same = lab === 'twijfel' ? '' : ((lab === 'ja') === !!s[2]
    ? ' · <span class="good">de regel is het met je eens</span>' : ' · <span class="bad">de regel zegt het andere</span>');
  box.innerHTML = `<h3>Vorige: <a href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a></h3>`
    + `<p>Jij: <strong>${esc(LABEL[lab])}</strong> · ${verdictLine(id)}${same}</p><div id="lastparts">…</div>`;
  explainFor(id).then(info => {
    const el = document.getElementById('lastparts');
    if (el && info && answered[answered.length - 1] === id) el.innerHTML = partsTable(info);
  });
}
function answer(kind) {
  if (kind === 'undo') return undo();
  if (!current) return;
  if (kind === 'skip') { skipped.add(current); showCard(); return; }
  const id = current;
  post(D.paths.label, {item_id: id, oordeel: kind}).then(r => {
    if (r.error) { say(r.message); return; }
    labels[id] = kind; answered.push(id);
    showLast(id); showCard(); updateCounts();
  }, e => { if (e !== 'reload') say('Niet opgeslagen: de server antwoordde niet.'); });
}
function undo() {
  const id = answered.pop();
  if (!id) { say('Niets om ongedaan te maken.'); return; }
  post(D.paths.label, {item_id: id, oordeel: ''}).then(r => {
    if (r.error) { say(r.message); answered.push(id); return; }
    delete labels[id];
    D.queue = [id, ...D.queue.filter(x => x !== id)];
    showLast(answered[answered.length - 1]); showCard(); updateCounts(); say('Vorige ongedaan.');
  });
}
document.querySelector('.answer').addEventListener('click', e => {
  const b = e.target.closest('button[data-answer]');
  if (b) answer(b.dataset.answer);
});
document.addEventListener('keydown', e => {
  if (document.getElementById('p-test').hidden || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
  const kind = {j: 'ja', n: 'nee', t: 'twijfel', s: 'skip', u: 'undo'}[e.key];
  if (kind) { e.preventDefault(); answer(kind); }
});

// --- uitslag
function agreement() {
  const a = {yy: [], nn: [], missed: [], wrong: [], unsure: 0};
  for (const [id, lab] of Object.entries(labels)) {
    const s = S[id];
    if (!s) continue;
    if (lab === 'twijfel') a.unsure++;
    else if (lab === 'ja') (s[2] ? a.yy : a.missed).push(id);
    else if (lab === 'nee') (s[2] ? a.wrong : a.nn).push(id);
  }
  a.missed.sort((x, y) => S[x][1] - S[y][1]);
  a.wrong.sort((x, y) => S[y][1] - S[x][1]);
  a.correct = a.yy.length + a.nn.length;
  a.judged = a.correct + a.missed.length + a.wrong.length;
  return a;
}
function deltaChips(id) {
  return S[id].slice(4).map((v, i) => {
    const d = v - own.dims[i];
    return `<span class="delta ${d > 0.05 ? 'plus' : d < -0.05 ? 'minus' : ''}" title="${esc(D.dimnames[i])}: ${nl(v)} tegen jouw ${nl(own.dims[i])}">${esc(D.dimnames[i])} ${signed(d, 0)}</span>`;
  }).join(' ');
}
function labelSelect(id) {
  return `<select data-label="${esc(id)}" aria-label="Jouw oordeel">`
    + ['', 'ja', 'nee', 'twijfel'].map(v => `<option value="${v}"${(labels[id] || '') === v ? ' selected' : ''}>${v ? LABEL[v] : '—'}</option>`).join('')
    + '</select>';
}
function agreeRow(id) {
  const b = byId[id];
  return `<tr><td>${labelSelect(id)}</td><td><a href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a>`
    + `<div class="sub">${esc(b.sp)}${b.act ? '' : ' · niet meer te koop'}</div><div class="sub">${deltaChips(id)}</div>`
    + `<details class="why" data-id="${esc(id)}"><summary>waarom</summary><div>…</div></details></td>`
    + `<td class="num">${euro(b.p)}</td><td class="num"><strong>${signed(S[id][1])}</strong></td></tr>`;
}
function agreeSection(title, ids) {
  if (!ids.length) return '';
  return `<h3>${esc(title)} (${ids.length})</h3><div class="table-wrap"><table><thead><tr><th>Jij</th><th>Fiets</th>`
    + `<th class="num">Prijs</th><th class="num">Winst</th></tr></thead><tbody>${ids.map(agreeRow).join('')}</tbody></table></div>`;
}
function renderAgree() {
  const a = agreement(), box = document.getElementById('agree');
  if (!a.judged) {
    box.innerHTML = `<p class="empty">Nog geen oordelen (ja of nee)${a.unsure ? `; ${a.unsure} keer twijfel` : ''}. Begin bij <a href="#test" data-goto="test">Test</a>.</p>`;
    return;
  }
  box.innerHTML = `<div class="tiles"><div class="tile"><div class="label">Goed</div><div class="value">${a.correct}/${a.judged}</div>`
    + `<div class="sub">${Math.round(a.correct / a.judged * 100)}% van je oordelen${a.unsure ? `; ${a.unsure} twijfel telt niet mee` : ''}</div></div>`
    + `<div class="tile"><div class="label">Jij upgrade, regel niet</div><div class="value">${a.missed.length}</div><div class="sub">te laag gewaardeerd</div></div>`
    + `<div class="tile"><div class="label">Jij geen upgrade, regel wel</div><div class="value">${a.wrong.length}</div><div class="sub">te hoog gewaardeerd</div></div></div>`
    + `<div class="table-wrap" style="display:inline-block"><table class="matrix"><thead><tr><th></th><th>Regel: beter</th><th>Regel: niet</th></tr></thead><tbody>`
    + `<tr><th>Jij: upgrade</th><td>${a.yy.length}</td><td>${a.missed.length}</td></tr>`
    + `<tr><th>Jij: geen upgrade</th><td>${a.wrong.length}</td><td>${a.nn.length}</td></tr></tbody></table></div>`
    + agreeSection('Jij zei upgrade, de regel niet', a.missed) + agreeSection('Jij zei geen upgrade, de regel wel', a.wrong)
    + `<p class="explain">Per onderdeel staat het verschil met jouw fiets. Pas de regel aan onder `
    + `<a href="#regel" data-goto="regel">Jouw regel</a>, of laat hem daar zoeken.</p>`;
}
document.addEventListener('toggle', e => {
  const d = e.target;
  if (!(d instanceof HTMLDetailsElement) || !d.matches('details.why') || !d.open) return;
  explainFor(d.dataset.id).then(info => {
    if (info) d.querySelector('div').innerHTML = partsTable(info) + `<p class="sub">${esc(info.waarom)}</p>`;
  });
}, true);
document.addEventListener('change', e => {
  const sel = e.target.closest('select[data-label]');
  if (!sel) return;
  const id = sel.dataset.label;
  post(D.paths.label, {item_id: id, oordeel: sel.value}).then(r => {
    say(r.message);
    if (r.error) return;
    if (sel.value) labels[id] = sel.value; else delete labels[id];
    updateCounts(); progress();
  });
});
function updateCounts() {
  const a = agreement();
  document.getElementById('agreecount').textContent = a.judged ? `(${a.correct}/${a.judged})` : '';
  renderStatus(a);
  if (!document.getElementById('p-uitslag').hidden) renderAgree();
  if (!document.getElementById('p-uitdraai').hidden) renderOut();
}

// --- jouw regel
const form = document.getElementById('ruleform');
function readForm() {
  const out = JSON.parse(JSON.stringify(rule));
  form.querySelectorAll('[data-path]').forEach(el => {
    const path = el.dataset.path.split('.');
    let node = out;
    path.slice(0, -1).forEach(k => { node = node[k] = node[k] || {}; });
    const key = path[path.length - 1];
    if (el.tagName === 'SELECT') { node[key] = el.value; return; }
    const raw = el.value.trim().replace(',', '.');
    if (raw === '') { node[key] = key === 'eigen_wielen' ? null : raw; return; }
    let v = Number(raw);
    if (el.dataset.kind === 'pct') v = v / 100;
    node[key] = Number.isFinite(v) ? Math.round(v * 1e6) / 1e6 : raw;
  });
  return out;
}
function fillForm(r) {
  form.querySelectorAll('[data-path]').forEach(el => {
    let v = el.dataset.path.split('.').reduce((n, k) => n == null ? n : n[k], r);
    if (el.tagName === 'SELECT') { el.value = v; return; }
    if (v == null) { el.value = ''; return; }
    if (el.dataset.kind === 'pct') v = Math.round(v * 100 * 1e6) / 1e6;
    el.value = String(v);
  });
}
let tryTimer = null, trySeq = 0;
form.addEventListener('input', () => { clearTimeout(tryTimer); tryTimer = setTimeout(tryRule, 350); });
form.addEventListener('change', () => { clearTimeout(tryTimer); tryRule(); });
function tryRule() {
  const seq = ++trySeq;
  const status = document.getElementById('rulestatus');
  status.classList.add('busy');
  post(D.paths.try, {regel: JSON.stringify(readForm())}).then(r => {
    if (seq !== trySeq) return;
    if (r.error) { say(r.message); status.textContent = r.message; return; }
    applyState(r);
  }, e => { if (e !== 'reload') say('Doorrekenen lukte niet.'); })
    .finally(() => { if (seq === trySeq) status.classList.remove('busy'); });
}
function applyState(r) {
  S = r.s; own = r.own; rule = r.rule;
  renderOwn(); renderChanges(r.changes); updateCounts(); renderPeek();
  const last = answered[answered.length - 1];
  if (last) showLast(last);
}
function renderChanges(changes) {
  document.getElementById('changes').innerHTML = changes.length
    ? '<li class="head">Wijkt af van de standaard:</li>' + changes.map(c => `<li>${esc(c)}</li>`).join('')
    : '<li class="head">Gelijk aan de standaard (scoring_config.json).</li>';
}
let savedCorrect = null;
function renderStatus(a) {
  const active = D.bikes.filter(b => b.act && S[b.id]);
  const better = active.filter(b => S[b.id][2]).length, upgrade = active.filter(b => S[b.id][3]).length;
  document.getElementById('rulestatus').innerHTML = `Met deze regel: <strong>${a.judged ? `${a.correct} van je ${a.judged}` : 'nog geen'}</strong> oordelen goed`
    + (savedCorrect != null && a.judged ? ` (bij opslaan: ${savedCorrect})` : '')
    + ` · jouw fiets ${nl(own.tot)} · van de ${active.length} te koop zijn er ${better} beter dan jouw fiets, ${upgrade} ook binnen maat en budget.`;
}
document.getElementById('save').addEventListener('click', () => {
  post(D.paths.rule, {actie: 'opslaan', regel: JSON.stringify(readForm())}).then(r => {
    say(r.message);
    if (r.error) return;
    applyState(r); fillForm(r.rule); savedCorrect = agreement().correct;
    document.getElementById('rulename').textContent = 'jouw regel (net opgeslagen)';
  });
});
document.getElementById('standard').addEventListener('click', () => {
  if (!confirm('Je opgeslagen regel weghalen en terug naar de standaard (scoring_config.json)?')) return;
  post(D.paths.rule, {actie: 'standaard'}).then(r => {
    say(r.message);
    if (r.error) return;
    applyState(r); fillForm(r.rule); savedCorrect = agreement().correct;
    document.getElementById('rulename').textContent = 'de standaard (scoring_config.json)';
  });
});
document.getElementById('search').addEventListener('click', () => {
  const box = document.getElementById('found');
  box.innerHTML = '<p class="muted">Zoeken… dat duurt een paar seconden.</p>';
  post(D.paths.search, {regel: JSON.stringify(readForm())}).then(r => {
    if (r.error) { box.innerHTML = ''; say(r.message); return; }
    if (!r.changes.length) {
      box.innerHTML = `<div class="banner">${esc(r.note || `De regel van nu past al het best: ${r.before} van ${r.judged} goed.`)}</div>`;
      return;
    }
    box.innerHTML = `<div class="banner"><strong>${r.correct} van je ${r.judged}</strong> oordelen goed met deze regel (nu ${r.before}).`
      + `<ul>${r.changes.map(c => `<li>${esc(c)}</li>`).join('')}</ul>${r.note ? `<p class="sub">${esc(r.note)}</p>` : ''}`
      + '<button id="takeover">Neem over (daarna nog opslaan)</button></div>';
    document.getElementById('takeover').addEventListener('click', () => { fillForm(r.rule); box.innerHTML = ''; tryRule(); });
  }, e => { box.innerHTML = ''; if (e !== 'reload') say('Zoeken lukte niet.'); });
});

// --- uitdraai
const COLS = [['Jij', null], ['Fiets', b => b.t.toLowerCase()], ['Prijs', b => b.p ?? -1], ['Jaar', b => b.yr ?? 0],
  ...D.dimnames.map((n, i) => [n, b => S[b.id][4 + i]]), ['Totaal', b => S[b.id][0]], ['Winst', b => S[b.id][1]],
  ['Beter', b => S[b.id][2]], ['Upgrade', b => S[b.id][3]]];
let sortCol = COLS.findIndex(c => c[0] === 'Winst'), sortDir = -1, shownRows = 200;
function outRows() {
  const show = document.getElementById('show').value, q = document.getElementById('q').value.trim().toLowerCase();
  return D.bikes.filter(b => {
    const s = S[b.id];
    if (!s) return false;
    if (show === 'te koop' && !b.act) return false;
    if (show === 'beoordeeld' && !labels[b.id]) return false;
    if (show === 'oneens') {
      const l = labels[b.id];
      if ((l !== 'ja' && l !== 'nee') || (l === 'ja') === !!s[2]) return false;
    }
    if (show === 'beter' && !s[2]) return false;
    if (show === 'upgrade' && !s[3]) return false;
    return !q || (b.t + ' ' + b.sp).toLowerCase().includes(q);
  });
}
function renderOut() {
  const table = document.getElementById('out');
  table.tHead.innerHTML = '<tr>' + COLS.map(([name, key], i) => `<th${key ? ` data-col="${i}"` : ''}${i >= 2 ? ' class="num"' : ''}>`
    + `${esc(name)}${i === sortCol ? (sortDir < 0 ? ' ↓' : ' ↑') : ''}</th>`).join('') + '</tr>';
  const rows = outRows();
  const key = COLS[sortCol][1];
  rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * sortDir; });
  table.tBodies[0].innerHTML = rows.slice(0, shownRows).map(b => {
    const s = S[b.id];
    const parts = s.slice(4).map((v, i) => {
      const d = v - own.dims[i];
      return `<td class="num">${nl(v, 0)}<div class="sub delta ${d > 0.05 ? 'plus' : d < -0.05 ? 'minus' : ''}">${signed(d, 0)}</div></td>`;
    }).join('');
    return `<tr><td>${labelSelect(b.id)}</td><td><a href="${esc(b.u)}" target="_blank" rel="noopener">${esc(b.t)}</a>`
      + `<div class="sub">${esc(b.sp)}${b.act ? '' : ' · niet meer te koop'}</div></td><td class="num">${euro(b.p)}</td>`
      + `<td class="num">${b.yr ?? '—'}${b.ys ? `<div class="sub">${esc(b.ys)}</div>` : ''}</td>${parts}`
      + `<td class="num">${nl(s[0])}</td><td class="num"><strong>${signed(s[1])}</strong></td>`
      + `<td class="num">${s[2] ? '<span class="good">ja</span>' : '—'}</td><td class="num">${s[3] ? '<span class="good">ja</span>' : '—'}</td></tr>`;
  }).join('');
  document.getElementById('outcount').textContent = `${rows.length} fiets${rows.length === 1 ? '' : 'en'}`;
  document.getElementById('outmore').innerHTML = rows.length > shownRows
    ? `<button class="quiet" id="more">Toon nog ${Math.min(200, rows.length - shownRows)} (van ${rows.length - shownRows})</button>` : '';
}
document.getElementById('out').addEventListener('click', e => {
  const th = e.target.closest('th[data-col]');
  if (!th) return;
  const col = Number(th.dataset.col);
  sortDir = col === sortCol ? -sortDir : (col === 1 ? 1 : -1);
  sortCol = col; renderOut();
});
document.getElementById('outmore').addEventListener('click', e => {
  if (e.target.closest('#more')) { shownRows += 200; renderOut(); }
});
document.getElementById('show').addEventListener('change', () => { shownRows = 200; renderOut(); });
document.getElementById('q').addEventListener('input', () => { shownRows = 200; renderOut(); });

renderOwn();
renderChanges(D.changes);
updateCounts();
showCard();
showTab(location.hash.slice(1) || 'test');
})();
