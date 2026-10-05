# Opdracht: upgradetest — zelf bepalen wat een upgrade is

Van de eigenaar, 05-10-2026, na de uitleg hoe de ranking nu werkt:

> ik wil graag dat je alles gaat uitdraaien en een test maakt zodat ik zelf
> kan bepalen wat een upgrade is, nu zijn er fietsen die duidelijk een
> upgrade zijn lager gewaardeerd dan mijn fiets, doe dit echt in 1 keer goed
> en als mijn tokenlimiet bereikt is begin dan opnieuw als deze weer vrij
> is, bekijk ook kort de optie om bikereviews hierin mee te nemen

Push naar `claude/claude-fietsmodellen-stap-1-80kp1n` (de eigenaar merget zelf).
Een vangnet (send_later) start een sessie opnieuw als de limiet op was; die
leest dit logboek.

## Wat het probleem is (gemeten op de code van 5dbf076)

De kwaliteitsscore (`scoring.py`, gewichten in `scoring_config.json`) geeft
de eigen Defy 51. Voorbeeldfietsen door dezelfde code: een TCR Advanced 2016
Ultegra 11s velrem +4 (geen upgrade, marge 5), een carbon 2021 105
hydraulisch +5 (geen), een carbon 2010 Dura-Ace 10s met powermeter +12
(beste upgrade), een stalen 1990 Dura-Ace −1. Oorzaken: leeftijd telt alleen
op het frame en weinig (1,5% per jaar van 30% gewicht), de groepsetgeneratie
telt niet, de eigen CSC-wielen scoren als merk-carbon (85), onbekend scoort
neutraal-laag, en een powermeter weegt evenveel als de hele marge.

## Wat er komt

1. **Uitdraai**: elke actieve racefiets met de score per onderdeel, het
   verschil met de eigen fiets per onderdeel, winst, oordeel (en waarom),
   prijs/budget/maat en jouw oordeel. Op de pagina als tabel, als CSV
   (`/upgrade/uitdraai.csv`) en met `python upgrade_test.py uitdraai`.
2. **De test** (`/upgrade` in `dashboard.py --serve`): één fiets tegelijk,
   "is dit een upgrade van jouw fiets — los van prijs en maat?" ja / nee /
   twijfel (toetsen j/n/t, u = ongedaan). De score staat er pas na je
   antwoord bij (anders stuurt hij je). Volgorde: verspreid over het hele
   scorebereik, zodat ook de laag gescoorde fietsen langskomen. Opgeslagen
   in `upgrade_label` (migratie 22).
3. **Uitslag**: hoeveel van je antwoorden de regel goed heeft, en de fietsen
   waar jij en de regel het oneens zijn, met per onderdeel waarom.
4. **Jouw regel**: alle knoppen van de score op één plek (gewichten, marge,
   materiaal/leeftijd, groepsetniveaus, remmen, wielen, eigen wielen,
   extra's, onbekend = neutraal getal of gelijk aan je eigen fiets, leeftijd
   ook op de aandrijving). Elke wijziging rekent meteen door op je
   antwoorden en de fietsen van nu. "Zoek de regel die het best bij mijn
   antwoorden past" probeert gewichten, marge en opties en stelt de beste
   voor. Opslaan zet hem in `setting` (`upgrade_regel`); dan rekent alles
   ermee: `/racefietsen`, het rapport, het overzicht, `upgrade.py`.
   `scoring_config.json` blijft de standaard.
5. **Bikereviews**: kort onderzoek, als voorstel (zie onder).

Nieuwe opties in de score zijn standaard uit: zonder opgeslagen regel
rekent alles precies als nu.

## Logboek

- 05-10 — opzet en plan (dit bestand).
- 05-10 — kern af (commit "Upgradetest: regel, oordelen, uitslag, zoeken en
  uitdraai (kern)"): score-knoppen, regel opslaan/toepassen, migratie 22,
  uitslag, zoeken (1,8 s op 120 oordelen), CSV, console, LiveCache. Nog te
  doen: de pagina /upgrade, Playwright, bikereviews, documentatie.
