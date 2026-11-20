
// Een lange ronde niet per ongeluk (vóór LIVE_JS, dat de klik anders verstuurt).
document.addEventListener('click', e => {
  const button = e.target.closest('.act button[data-confirm]');
  if (button && !confirm(button.dataset.confirm)) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);
// Terwijl een ronde draait: het logboek bijwerken, en herladen als hij klaar is.
if (document.getElementById('round-running')) {
  const poll = () => fetch('/start/status').then(r => r.json()).then(data => {
    const log = document.getElementById('round-log');
    if (log && data.log !== undefined) { log.textContent = data.log; log.scrollTop = log.scrollHeight; }
    if (!data.running) location.replace('/start?melding=' + encodeURIComponent('De ronde is klaar.'));
    else setTimeout(poll, 4000);
  }).catch(() => setTimeout(poll, 8000));
  setTimeout(poll, 4000);
  const log = document.getElementById('round-log');
  if (log) log.scrollTop = log.scrollHeight;
}
