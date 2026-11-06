# Fotolabels — verhuisd

Het ontwerp van het beeldmodel (labels, dataset, model) staat sinds
06-11-2026 in een eigen repo: **meesverb/fiets-beeldmodel**, in
`docs/ontwerp.md`. Daar wordt het verder bijgehouden; dit bestand niet meer.

Taakverdeling (vastgelegd in de `CLAUDE.md` van die repo):

- **fiets-beeldmodel**: dataset, labelpagina, training. Praat nooit met
  Marktplaats; leest `koopjes.db` en de opgeslagen foto's alleen.
  Levert `python -m beeldmodel herken <map>` → JSON per onderdeel.
- **deze repo**: alle contact met Marktplaats (ook de kleine zoekopdracht elke
  20 minuten, besluit van de eigenaar), foto's ophalen op `$_57`, tekst en
  foto samenvoegen, onderdelenwaarde, opknapkosten, Telegram-melding. Zonder
  model rekent hij op de tekst.
