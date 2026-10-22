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

## De aanpak

### Lezen, niet alleen herkennen

Merk, model en groepset staan vaak op de fiets geschreven ("GIANT", "DEFY",
"ULTEGRA", "FULCRUM"). Een classifier op vectoren leert vormen en kleuren en
heeft per merk honderden voorbeelden nodig; een model dat kan lezen heeft er
geen nodig. Daarom twee soorten modellen.

### Leraar en leerling

- **Leraar**: een klein beeld-taalmodel, lokaal via Ollama (Qwen3.5-2B,
  Gemma 4 E2B). Leest stickers en zegt wat hij ziet, zonder labels. Traag:
  hij draait 's nachts op een paar honderd fietsen.
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
| leraar | Qwen3.5-2B (OCRBench 84,5), 4B | Apache 2.0 | [HF](https://huggingface.co/Qwen/Qwen3.5-2B), [Ollama](https://ollama.com/library/qwen3.5) |
| leraar | Gemma 4 E2B, E4B (instelbaar detail, ook OCR) | Apache 2.0 | [modelkaart](https://ai.google.dev/gemma/docs/core/model_card_4), [Ollama](https://ollama.com/library/gemma4) |
| versnellen (later) | OpenVINO (Intel CPU/iGPU) | Apache 2.0 | [release notes](https://docs.openvino.ai/2025/about-openvino/release-notes-openvino.html) |

Bewust niet: YOLOE (AGPL), Grounding DINO en OWLv2 (te zwaar voor de CPU),
beeld-taalmodellen van 8B of groter (te traag op deze laptop).

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
