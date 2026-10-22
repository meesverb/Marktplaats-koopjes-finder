# Opdracht: een zelf getraind beeldmodel voor racefietsen (`beeld/`)

> **Stand (22-10-2026): stap 0 is gebouwd** (`beeld/meet.py`), nog niet
> gedraaid op de laptop van de eigenaar. Volgende: de eigenaar draait stap 0
> (zie `beeld/README.md`) en zet de uitkomst in `beeld/metingen/`; pas
> daarna worden de modellen gekozen.

Voor een agent die hier verder aan werkt. Lees eerst `CLAUDE.md` en werk
vanaf een verse `main`. **Eén stap per sessie**, net als de fases in het
plan. De werkwijze is **samen, stap voor stap**: de eigenaar wil het leren
(ook met het oog op geneeskunde). Leg per stap uit wat en waarom, laat de
eigenaar het draaien, en bouw niet drie stappen vooruit.

## Wat de eigenaar wil

Vastgesteld in een gesprek op 22-10-2026. Wijk hier niet van af zonder te
vragen.

- **Doelen**, alle vier: slapers vinden (fietsen waarvan titel en tekst niets
  zeggen), de taxatie aanvullen (model invullen waar de tekst zwijgt),
  verkopers controleren ("Ultegra" terwijl er 105 op zit), en ervan leren.
- **Velden**: merk en model; groepset (groep én generatie); remmen en
  framemateriaal; wielen (carbon of alu, profiel, merk); staat: *werk nodig*
  en *cosmetisch*. **Geen bouwjaar** (bewust niet gekozen; het zwakste
  veld).
- **Hints, geen taxatie.** Wat het model zegt, telt niet mee in de taxatie,
  de vergelijkingsfietsen, de dealscore of de waardescore. Wat de eigenaar
  bevestigt of verbetert, wordt wél een trainingslabel.
- **Zelf trainen, goedkoop.** Geen betaalde API. De laptop mag meerdere
  avonden rekenen. Kaggle of Colab (gratis GPU) alleen als dat nodig blijkt,
  en dan met zo min mogelijk data: de eigenaar wil de data niet allemaal
  weggeven.
- **Zekerheid per veld kiezen**, na de meting: per veld een drempel,
  daaronder "weet niet".
- **Bereik**: alle racefietsen (met een budget per ronde, voor
  trainingsmateriaal), en de kansrijke eerst (slapers, ≥ 15% onder de
  schatting, favorieten).
- **Labelen**: veel tijd beschikbaar. Een vaste testset met de knoppen, en
  de eigenaar wil later gevallen aan de testset kunnen toevoegen (zie
  "Testset" hieronder). Labelen op een **eigen pagina** `/labelen`, met
  sneltoetsen zoals de upgradetest.
- **Staat** betekent: *werk nodig* (ketting, banden, stuurlint/zadel,
  onderdeel ontbreekt; elk ja/nee) en *cosmetisch* (geen, licht, zwaar).
  Niet "schade" en niet "verzorgd/verwaarloosd". Staat zit niet in de data:
  die labels geeft de eigenaar zelf.
- **Foto's bewaren** (lokaal, `beeld/data/`, niet in git): nodig om later
  met een beter netwerk opnieuw te rekenen.
- **In deze repo, maar los te koppelen**: zie `beeld/README.md`, "Los te
  koppelen". De repo importeert niets uit beeld/, beeld/ niets uit de repo;
  `koopjes.db` alleen lezen.
- **Wanneer draaien**: "wat het het beste laat leren". Dus: eerst met de hand
  (de eigenaar ziet wat er gebeurt), daarna verzamelt de nachtronde foto's
  met een budget (meer data), en opnieuw trainen gaat met de hand na nieuwe
  labels.
- **DINOv3**: ja, de eigenaar vraagt toegang aan. **Leraar via Ollama.**
- **De leraar is het grootste model dat lokaal draait** (eigenaar,
  22-10-2026, na de proef met de kleine): `qwen3.5:35b`, 34,7B in Q4_K_M
  (~22 GB, `qwen35moe`, ~3B actief per woord). Terugval als het niet past:
  `gemma4:26b` (25,2B, 3,8B actief, 16-19 GB). Groter past niet in 32 GB
  (het volgende Qwen-model is 122B); de gewone 27B/31B zijn kleiner en op de
  processor veel trager. **Niet getest in de sandbox** (15,7 GB geheugen,
  te weinig): de meting op de laptop moet laten zien of het past en hoe
  snel het is.

## De aanpak

### Lezen, niet alleen herkennen

Merk, model en groepset staan vaak op de fiets geschreven ("GIANT", "DEFY",
"ULTEGRA", "FULCRUM"). Een classifier op vectoren leert vormen en kleuren en
heeft per merk honderden voorbeelden nodig; een model dat kan lezen heeft er
geen nodig. Daarom twee soorten modellen.

### Leraar en leerling

- **Leraar**: een beeld-taalmodel, lokaal via Ollama: het grootste dat op
  de laptop past, `qwen3.5:35b` (zie "Wat de eigenaar wil"). Leest stickers
  en zegt wat hij ziet, zonder labels. Traag: hij draait 's nachts op een
  paar honderd fietsen.
- **Leerling**: de eigen classifier op vectoren van een voorgetraind netwerk
  (DINOv2/DINOv3/SigLIP 2). Snel; draait op alle racefietsen.

Labels uit drie bronnen:

| Bron | Kost | Betrouwbaarheid |
| --- | --- | --- |
| tekst en Kenmerken van de verkoper | niets | rommelig |
| de leraar | niets, traag | maakt ándere fouten dan de verkoper |
| de eigenaar | tijd | goud |

- Tekst en leraar **eens** → zilveren label om op te trainen.
- **Oneens** → bovenaan de labelwachtrij. Dat is meteen "verkoper
  controleren".
- **De testset bevat alleen labels van de eigenaar.**
- **De leraar krijgt alleen de foto, nooit de titel of tekst** (anders praat
  hij de verkoper na en zegt "eens" niets). `TEACHER_PROMPT` in
  `beeld/candidates.py` houdt zich daaraan; er staat een test op.
- **Nooit trainen op de eigen onbevestigde gokken van de leerling**: dan leert
  hij zijn eigen fouten aan en wordt hij zekerder zonder beter te worden. De
  leraar is een onafhankelijke tweede bron; dat is iets anders.

### Uitsnedes

Op een overzichtsfoto is een crank ~100 pixels breed: "105" is daar niet te
lezen. Groepset, remmen en staat (ketting, banden) worden daarom op
uitsnedes bekeken, elk met een eigen vector en een eigen classifier.

**Bevinding uit de proef van 22-10-2026** (zie Logboek): Florence-2 vindt
wielen en remgrepen goed, maar zet "crankset" en "rear derailleur" op een
heel wiel of op de hele fiets. Plan voor stap 4: **de wielen als ankerpunt**.
De crank zit ongeveer midden tussen de naven en iets eronder, de derailleur
bij de achternaaf. Die uitsnedes reken je uit (een vierkant van ~0,6
wieldiameter rond het midden tussen de wielen; welk wiel achter is, maakt
dan niet uit) in plaats van ze te laten zoeken. Alleen bruikbaar op een
zijaanzicht met twee gevonden wielen; de rest valt terug op de hele foto en
de close-ups van de verkoper.

### Modellen

Kies niet op gevoel: stap 0 meet de snelheid, stap 3 de kwaliteit op de
testset.

| Rol | Kandidaten | Licentie | Bron |
| --- | --- | --- | --- |
| vectoren | DINOv3 ViT-S+/16 (29M), ViT-B/16 (86M) | DINOv3-licentie, toegang aanvragen | [GitHub](https://github.com/facebookresearch/dinov3), [modelkaart](https://huggingface.co/facebook/dinov3-vits16plus-pretrain-lvd1689m) |
| vectoren | DINOv2 small/base | Apache 2.0 | [HF](https://huggingface.co/facebook/dinov2-base) |
| vectoren + zonder training | SigLIP 2 base/16-224 | Apache 2.0 | [HF](https://huggingface.co/google/siglip2-base-patch16-224) |
| uitsnede + OCR | Florence-2 base (230M), large (770M) | MIT | [transformers-docs](https://huggingface.co/docs/transformers/model_doc/florence2) |
| **leraar** | **Qwen3.5-35B-A3B** (`qwen3.5:35b`, ~22 GB): het grootste dat past | Apache 2.0 | [HF](https://huggingface.co/Qwen/Qwen3.5-35B-A3B), [Ollama](https://ollama.com/library/qwen3.5:35b) |
| terugval | Gemma 4 26B A4B (`gemma4:26b`, 16-19 GB; MMMU Pro 73,8% tegen 44,2% voor E2B) | Apache 2.0 | [modelkaart](https://ai.google.dev/gemma/docs/core/model_card_4), [Ollama](https://ollama.com/library/gemma4:26b) |
| vergelijking | Qwen3.5-2B (OCRBench 84,5), 4B, 9B; Gemma 4 E2B, 12B | Apache 2.0 | [HF](https://huggingface.co/Qwen/Qwen3.5-2B), [Ollama](https://ollama.com/library/qwen3.5) |
| versnellen (later) | OpenVINO (Intel CPU/iGPU) | Apache 2.0 | [release notes](https://docs.openvino.ai/2025/about-openvino/release-notes-openvino.html) |

Bewust niet: YOLOE (AGPL), Grounding DINO en OWLv2 (te zwaar voor de CPU),
en gewone ("dense") beeld-taalmodellen van 27B of meer (te traag op de
processor; de "mixture of experts"-modellen hierboven zijn groter maar
rekenen per woord met ~3-4B).

### Laptop

Acer Aspire 15, **Intel Core 7 150U** (10 kernen, 12 threads), 32 GB LPDDR5,
Intel Graphics (geen losse videokaart), Windows (de rondes lopen via
Taakplanner). PyTorch draait op de processor; de iGPU is waarschijnlijk niet
officieel ondersteund door PyTorch. Goed genoeg voor vectoren en kleine
classifiers. Fine-tunen kan, maar kost avonden.

## Foto's: beleefd

- De zoekresultaten geven al **3 foto's per advertentie** (`largeUrl`,
  `racefiets_jev.SEARCH_IMAGES`), sinds migratie 6 in `listing.image_urls`.
  Die ophalen kost geen extra paginaverzoeken, alleen de foto's zelf.
- De **volledige galerij** (met close-ups van crank en shifters) staat alleen
  op de advertentiepagina. Die niet extra ophalen: meeliften als hij toch
  opgehaald wordt (bouwjaar, controleer, dossier, biedopvraging), plus de
  kansrijke binnen een budget. CLAUDE.md: de crawl-frequentie niet opvoeren.
- Eén verzoek tegelijk, minstens 1,5 s ertussen (`photos.MIN_DELAY_S`).
- **Gevolg:** bij de meeste fietsen geen close-ups, dus de groepset blijft
  vaak "weet niet".
- **Snel beginnen:** advertenties verdwijnen. Stap 0 meet of de foto's van
  verdwenen advertenties nog bestaan.
- De foto's zijn van de verkopers: alleen lokaal, niet delen, het model niet
  publiceren.

## Testset

- **200 willekeurige advertenties, zonder voorinvulling.** Anders neemt de
  eigenaar onbewust de gok van het model over, en meet je de eigenaar in
  plaats van het model.
- Wat in de testset zit, gaat **nooit** de training in.
- **Lastige gevallen**: een aparte set die de eigenaar altijd mag aanvullen,
  los gemeten. Niet bij de willekeurige set: dan meet die iets anders.
- Splitsen per **advertentie** (niet per foto), per **verkoper** (handelaren
  met dezelfde achtergrond) en op **tijd**. Dubbele foto's (opnieuw geplaatst)
  opsporen.

## Stappen

| # | Stap | Status |
| --- | --- | --- |
| 0 | Meten op de laptop: seconden per foto per model (`beeld/meet.py`) | gebouwd 22-10-2026, nog te draaien |
| 1 | Inventaris: per veld tellen hoeveel labels tekst en Kenmerken al geven; foto's verzamelen (3 per advertentie, meeliften voor de galerij) | |
| 2 | Testset: 200 willekeurig, zonder voorinvulling, op `/labelen` | |
| 3 | Nulmeting zonder training: SigLIP 2 (tekstprompts) en de leraar op de testset | |
| 4 | Uitsnedes (wielen als anker) en vectoren voor alles | |
| 5 | Leerling trainen op goud en zilver; per veld tegen de nulmeting; drempels | |
| 6 | Hints tonen, klopt/fout wordt een label, wachtrij (oneens → leerling twijfelt → spreiding); de leraar 's nachts op de kansrijke | |
| 7 | Later: fine-tunen op uitsnedes, staat met de labels van de eigenaar | |

## Problemen om rekening mee te houden

- **Rommelige labels**: "met Shimano 105 en Mavic wielen" (Mavic is geen
  fietsmerk), het aankoopjaar als bouwjaar, staat door de verkoper.
- **Lange staart**: onder ~20 advertenties wordt een merk "overig".
- **Leakage**: dezelfde fiets in training en test (meerdere foto's, opnieuw
  geplaatst), handelaren met dezelfde achtergrond, stockfoto's.
- **Slapers hebben slechtere foto's** dan de testset: het moeilijkste deel.
- **De leraar verzint**: telt alleen mee als hij het eens is met de
  verkoper.
- **Kalibratie**: een model zegt 90% zeker en heeft het 70% van de keren
  goed. Drempels kiezen op de meting.
- **Warmte**: de 150U wordt trager bij lange runs. Aan de lader.
- **Veroudering**: elk jaar nieuwe modellen en kleuren. Af en toe opnieuw
  trainen.
- **Migraties**: als er ooit iets in `koopjes.db` moet (liever niet: alles in
  `beeld/data/`), dan nieuwe tabellen, geen kolommen (CLAUDE.md, valkuilen).

## Logboek

- 22-10 — gesprek met de eigenaar, plan en keuzes (dit bestand).
- 22-10 — stap 0 gebouwd: `beeld/meet.py`, `candidates.py`, `photos.py`, 22
  tests zonder torch. Geprobeerd in de sandbox van de sessie (4 kernen,
  geen GPU, géén Marktplaats-foto's maar twee Wikimedia-foto's plus
  spiegelingen en uitsnedes; alleen om de code te testen, niet om te
  kiezen): DINOv2-small 0,05-0,07 s per foto, DINOv2-base 0,14 s,
  SigLIP 2 base 0,13 s, Florence-2 base ~9 s per foto (OCR + 4 onderdelen),
  Florence-2 large ~29 s. Florence-2 vond de wielen en de remgreep, las
  "SCHWALBE DURANO" als "SCHMALDEURANO" (base) en "SCHWALBE SURANO" (large),
  en zette crank en derailleur op een wiel of de hele fiets. DINOv3: geen
  toegang in de sandbox (de melding werkt). Ollama: niet in de sandbox.
  Nog te doen: de eigenaar draait stap 0 op de laptop.
- 22-10 — **op echte Marktplaats-foto's** (op vraag van de eigenaar). Eén
  zoekpagina racefietsen (`--pages 1 --bid-lookup none --detail-lookup
  none`, naar een losse database), 10 foto's, Ollama 0.40.8 in de sandbox
  (4 kernen, geen GPU). Antwoordsleutel: de titels plus eigen oordeel van de
  foto's. **n = 10: richting, geen meting.**
  - **Fotomaat.** De link uit de zoekresultaten (`$_83`) is 358x268: te
    klein, Florence-2 las er losse letters. Met `$_85` (XXL) 726x544, zelfde
    aantal verzoeken. `photos.fetch_photo()` vraagt nu `$_85`.
  - **Florence-2 als lezer**: wisselend. "TREK" en "SCOTT" goed, "VANITELI"
    voor Van Rysel, maar "FREK" bij een Trek en **"CANNON" bij een Canyon**
    (Cannondale is een ander merk). Niet geschikt als bron voor het merk.
  - **Leraren**, merk / rem / materiaal als goed-fout-weet niet:

    | Leraar | s per foto | Merk | Rem | Materiaal |
    | --- | --- | --- | --- | --- |
    | qwen3.5:2b | 15,6 | 4-2-4 | 5-0-3 | 2-1-5 |
    | qwen3.5:4b | 28,1 | 3-3-4 | 3-0-5 | 3-0-5 |
    | gemma4:e2b | 25,7 | 3-3-4 | 0-0-8 | 0-0-8 |

    Groot merk op het frame (TREK, CUBE, CANYON) lezen ze meestal; bijna
    goed: MMR als "MMP"/"MNR"/"MMS", Van Rysel als "VANNIPEL"/"VAMVYS".
    Verzonnen: Brassworks als "Trek" (2b) en "Spumoni" (gemma), Scott als
    "SIDI" (4b), Canyon als "CANON" (gemma). **Model en groepset las geen
    van drieën**, ook niet "ULTEGRA" en "DURA-ACE" die leesbaar op twee
    cranks staan. **Staat is onbruikbaar**: 2b zegt bij 7 van de 9 fietsen
    "ketting roestig", ook in nieuwstaat. De slaper "Mooie racefiets" was
    een Cube; 2b en gemma lazen "CUBE".
  - De eerste vraag aan de leraar (vrije tekst, met voorbeelden) werd
    nagepraat; de vraag heeft nu vaste keuzes met "unknown"
    (`candidates.TEACHER_PROMPT`). 2b raakte één keer in een lus ("R72,
    R80, ..."): het antwoord is nu begrensd (`TEACHER_MAX_TOKENS`).
  - **Wat dit voor het plan betekent:**
    1. De leraar is een bron voor **merk, remtype en materiaal**, niet voor
       model, groepset of staat. Model en groepset komen uit de tekst en
       uit labels van de eigenaar; staat alleen uit labels van de eigenaar.
    2. Het merk van de leraar moet tegen een **lijst bekende merken**, met
       een strenge tolerantie (MMP → MMR mag, CANON/CANNON nooit
       automatisch naar Canyon of Cannondale). Welke lijst (de catalogus
       uit de repo als databestand lezen, of een eigen lijst in beeld/) is
       een keuze bij stap 1: beeld/ mag geen code uit de repo importeren.
    3. De **eens/oneens-regel** is onmisbaar: "Trek" voor een Brassworks
       valt alleen weg omdat de titel iets anders zegt.
    4. qwen3.5:2b is hier de beste én de snelste, ~230 foto's per uur op 4
       kernen: op de laptop 's nachts ruim duizend. De keus valt pas na de
       meting op de laptop en de testset.
- 22-10 — **groter op dezelfde 10 foto's** (op vraag van de eigenaar: "kan ik
  niet grotere modellen aan?"). qwen3.5:9b: 45,5 s per foto (2b: 15,3 s),
  merk 4-1-4 goed-fout-weet niet, rem 4-0-4, materiaal 0-0-8. Groter is hier
  **voorzichtiger en leest meer**: geen verzonnen merk meer (2b maakte van de
  Brassworks een "Trek"), wel SCOTT (2b miste het), CUBE met EASTON-wielen,
  "VAN RIJSEL", en als eerste een groepset: **DURA-ACE** op de Canyon. Nog
  fout: "MMP" voor MMR, "RIVAL" op een Scott met Force AXS, en staat blijft
  onbruikbaar ("banden versleten" bij fietsen in nieuwstaat). gemma4:12b
  startte niet in Ollama 0.40.8 ("Gemma4Assistant requires ctx_other to be
  set"); `meet.py` meldde het en ging door. Daarna koos de eigenaar voor het
  grootste model dat lokaal past: `qwen3.5:35b` (zie "Wat de eigenaar wil");
  dat past niet in de 15,7 GB van de sandbox.
- 22-10 — **Claude als leraar** (vraag van de eigenaar: "kan ik niet trainen
  met jou?", met abonnementen op Claude en Gemini). Haiku, Sonnet en Opus als
  losse subagents, blind: dezelfde 10 foto's hernoemd naar foto01-10, alleen
  de foto's, dezelfde vraag en vaste keuzes als de lokale leraar; alle tien
  in één opdracht per model. Merk / rem / materiaal / wielprofiel als
  goed-fout-weet niet:

  | Model | Merk | Rem | Materiaal | Wielen | Groepset gelezen |
  | --- | --- | --- | --- | --- | --- |
  | Haiku | 6-1-3 | 7-1-0 | 5-1-2 | 7-3-0 | geen |
  | Sonnet | 7-0-3 | 8-0-0 | 7-0-1 | 9-0-1 | DURA-ACE, ULTEGRA |
  | Opus | 7-0-3 | 8-0-0 | 7-0-1 | 8-0-2 | DURA-ACE, ULTEGRA, plus EASTON-wielen |
  | qwen3.5:9b (lokaal) | 4-1-4 | 4-0-4 | 0-0-8 | 2-0-8 | DURA-ACE |

  Sonnet en Opus: geen enkel fout merk; de drie "weet niet" zijn twee foto's
  zonder leesbaar merk (terecht) en de kleine Brassworks-sierletters. Haiku
  verwisselde foto's: de MMR kreeg het antwoord van niemand en de stalen
  Brassworks heette "MMR, carbon, hoge velgen" — één foto per verzoek
  voorkomt dat. Haiku zei verder overal "ketting niet roestig, banden goed";
  Sonnet en Opus zeiden bij staat meestal "unknown". Zonder antwoordsleutel
  voor staat is daar niets over te zeggen. Kosten in tokens: ~80-90k per
  model voor 10 foto's (inclusief overhead van de subagent). Gemini 4 Argon
  (13-10-2026) niet getest: geen toegang vanuit de sandbox.
