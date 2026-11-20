
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
