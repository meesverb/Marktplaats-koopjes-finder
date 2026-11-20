
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
