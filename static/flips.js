
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
