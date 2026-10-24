# Proef: 100 advertenties, alle foto's (22-24 oktober 2026)

Archief van een eenmalige proef, niet om vanuit de repo te draaien. De
uitkomst en de conclusies staan in het logboek van
`opdrachten/beeldmodel.md`; hier staat hoe het gedaan is, zodat een volgende
proef (op de laptop, met labels van de eigenaar) hetzelfde kan meten.

**Geen data in git.** De testset (100 advertenties, 910 foto's), de
antwoordsleutel en de antwoorden per advertentie stonden in de scratchpad
van de cloudsessie; de eigenaar kreeg ze los als zip. Foto's en labels horen
in `beeld/data/` (niet in git), zoals in de rest van `beeld/`.

**Paden** wijzen naar die scratchpad (`HERE` = de map `test100`, `HERE.parent`
voor `blind100/`, `venv-beeld/`, `ollama/`). Twee scripts lenen iets uit de
repo, wat `beeld/` zelf nooit doet: `ophalen.py` importeert `dossier` en
`racefiets_jev` (foto's van de advertentiepagina), `prompts.py` leest de
merkenlijst uit `reference_bike_catalog.csv`. `lokaal.py` gebruikt de vraag
en de keuzes uit `beeld/candidates.py`.

## Volgorde

| Stap | Script | Wat |
| --- | --- | --- |
| 1 | `ophalen.py` | advertentiepagina's en alle foto's (`$_85`, 726x544) van de selectie; één verzoek tegelijk, 2 s tussen pagina's, 1,5 s tussen foto's |
| 2 | `bladen.py` | per advertentie overzichtsbladen met 4 genummerde foto's, om de sleutel te maken |
| 3 | `info.py`, `sleutel.py`, `sleutel_instructie.txt` | antwoordsleutel: titel, omschrijving en Kenmerken plus alle foto's; per advertentie merk (+ leesbaar), rem, materiaal, wielprofiel, groep (+ leesbaar), notitie. Door Claude Opus gemaakt, niet door de eigenaar |
| 4 | `claude_prompt.txt`, `valideer.py`, `tok.py` | Claude Haiku/Sonnet/Opus blind: neutrale namen `adv###_NN.jpg`, 5 advertenties per subagent, alle foto's in één bericht; `valideer.py` controleert de uitvoer tegen de manifesten, `tok.py` noteert de tokentelling per batch |
| 5 | `pijplijn.sh` | alle lokale modellen na elkaar, hervatbaar: `lokaal.py` (Ollama-leraren, alle foto's van een advertentie in één verzoek, exacte tokens uit `prompt_eval_count`/`eval_count`), `visie.py` (Florence-2 OCR, SigLIP 2 vectoren), `emb_gemma.py` (embeddinggemma-2 vectoren) |
| 6 | `prompts.py`, `tekstvectoren.py` | zonder training: tekstprompts per keuze ("a photo of a Gazelle road bike") en hun vectoren |
| 7 | `scoren.py` | alles tegen de sleutel, goed/fout/weet niet per veld, met het vaakste antwoord als ondergrens; schrijft `uitslag.md` |

`uitslag.md` is de laatste stand van stap 7 toen dit archief gemaakt werd.
