# beeld/ — het beeldmodel

Een model dat op de foto's van een racefietsadvertentie ziet wat er staat:
merk en model, groepset (groep en generatie), remmen en framemateriaal,
wielen, en de staat (werk nodig, cosmetisch). Zelf getraind, op de laptop,
zonder abonnement. Het levert **hints** naast de advertentie en telt nooit
mee in de taxatie, de dealscore of de waardescore.

Het hele plan, de keuzes van de eigenaar en de bronnen staan in
[`opdrachten/beeldmodel.md`](../opdrachten/beeldmodel.md). Dit bestand zegt
hoe je het draait.

## Los te koppelen

Dit is een harde eis van de eigenaar. Daarom:

- **beeld/ importeert niets uit de rest van de repo.** Wat het over
  `koopjes.db` moet weten (tabel `listing`, kolom `image_urls`, racefietsen
  herkend aan `fietsen-racefietsen` in de URL) staat als kopie in
  `photos.py`. Verandert het schema, dan stopt beeld/ met een duidelijke
  melding.
- **De rest van de repo importeert niets uit beeld/.** Komen er later hints
  of een pagina `/labelen`, dan alleen via een "bestaat beeld/ en zijn er
  hints?"-controle. Zonder beeld/ werkt alles zoals nu.
- **koopjes.db wordt alleen gelezen** (`mode=ro`). Wat beeld/ zelf bewaart,
  komt in `beeld/data/`.
- **Eigen requirements, eigen venv, eigen tests.** De tests van de repo
  (`tests/`) draaien zonder torch; die van beeld/ ook.

Loskoppelen is dus: de map `beeld/` weghalen, de regel `beeld/data/` uit
`.gitignore`, de rij in `CLAUDE.md`, en de uitzondering in §11 van
`PLAN_FIETSWAARDE.md`.

## Wat er in de map staat

| Bestand | Wat |
| --- | --- |
| `meet.py` | stap 0: meten wat de laptop aankan per model |
| `candidates.py` | de modellen die gemeten worden en hoe één foto erdoorheen gaat |
| `photos.py` | welke racefietsen foto's hebben (uit `koopjes.db`, alleen lezen) en ze beleefd ophalen |
| `tests/` | stdlib-tests, zonder torch en zonder netwerk |
| `metingen/` | uitkomsten van `meet.py`: alleen tijden en tellingen; mag in git |
| `data/` | foto's, antwoorden van de modellen, later vectoren en labels; **niet in git** |

## Installeren (Windows, PowerShell, vanuit de repo-map)

1. **Python-omgeving** (eenmalig):

   ```powershell
   py -m venv beeld\.venv
   beeld\.venv\Scripts\activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r beeld\requirements.txt
   ```

   Elke volgende keer alleen `beeld\.venv\Scripts\activate`.

2. **DINOv3** (vraagt toegang aan, eenmalig):
   - maak een account op [huggingface.co](https://huggingface.co);
   - vraag toegang op
     [dinov3-vits16plus](https://huggingface.co/facebook/dinov3-vits16plus-pretrain-lvd1689m)
     en [dinov3-vitb16](https://huggingface.co/facebook/dinov3-vitb16-pretrain-lvd1689m);
     de goedkeuring komt per mail;
   - maak een token (Settings → Access Tokens, soort *Read*) en log in met
     `hf auth login`.

   Zonder toegang slaat `meet.py` DINOv3 over met die melding; de rest gaat
   gewoon door.

3. **Ollama voor de leraar** (eenmalig): installeer Ollama voor Windows van
   [ollama.com](https://ollama.com), en dan:

   ```powershell
   ollama pull qwen3.5:2b
   ollama pull gemma4:e2b
   ```

   Ollama moet draaien tijdens de meting (het staat na installatie in het
   systeemvak).

**Schijfruimte:** reken op ongeveer 3 GB voor de modellen via Hugging Face
en 8 à 10 GB voor de twee leraren in Ollama.

## Stap 0 draaien

Voor een eerlijke meting: herstart de laptop eerst (hij stond 43 dagen aan
en gebruikte 25,7 van de 32 GB), laat hem aan de lader, en sluit zware
programma's. Dan:

```powershell
beeld\.venv\Scripts\activate
python beeld\meet.py
```

Wat er gebeurt:

1. Uit `koopjes.db` worden 10 actieve en 5 verdwenen racefietsen gekozen
   (willekeurig, maar steeds dezelfde). Van elk wordt één foto opgehaald:
   één verzoek tegelijk, minstens 1,5 s ertussen. Dat laat ook zien of de
   foto's van verdwenen advertenties nog bestaan.
2. Elk model krijgt die foto's. De eerste foto is opwarmen en telt niet mee.
   Florence-2 krijgt er 10, de leraren 5 (de leraar doet tientallen seconden
   per foto).
3. Per model komt er een regel: seconden per foto, foto's per uur, geheugen.

De eerste keer duurt het langer, omdat de modellen gedownload worden.

Andere mogelijkheden:

```powershell
python beeld\meet.py --lijst                         # alle modellen
python beeld\meet.py --modellen dinov2-s,siglip2-b   # alleen deze
python beeld\meet.py --modellen alle                 # alles, ook de grote leraren hieronder
python beeld\meet.py --map C:\pad\naar\fotos         # eigen foto's, zonder koopjes.db
```

### Grotere leraren

Qua geheugen kan de laptop (32 GB) veel grotere modellen aan; de grens is de
snelheid, want alles rekent op de processor. Een gewoon model is ruwweg zo
traag als het groot is. De twee "mixture of experts"-modellen rekenen per
woord met maar een paar miljard parameters, en zijn daardoor bijna zo snel
als een 4B-model. Ze moeten wel helemaal in het geheugen passen.

| Model | Download | Opmerking |
| --- | --- | --- |
| `qwen3.5:9b` | ~7 GB | gewoon model, ~2 keer zo traag als 4b |
| `gemma4:12b` | ~8 GB | gewoon model |
| `gemma4:26b` | 16-19 GB | 25B, waarvan 3,8B actief: **de interessantste voor deze laptop** |
| `qwen3.5:35b` | ~22 GB | 35B, waarvan 3B actief; krap, sluit eerst alles af |

```powershell
ollama pull gemma4:26b
python beeld\meet.py --modellen qwen3.5:2b,gemma4:26b --leraar-fotos 10
```

Herstart de laptop eerst: met 25 GB al in gebruik past een model van 16 GB
niet, en dan gaat Windows naar de schijf wisselen. Dat is tientallen keren
trager, en de meting zegt dan niets.

## Wat je daarna doet

`beeld\metingen\stap0-<datum>.json` bevat alleen tijden en tellingen: geen
foto's, geen advertentienummers, geen antwoorden. Zet het in git, zodat een
volgende sessie kan lezen wat de laptop haalde:

```powershell
git add beeld\metingen
git commit -m "Beeldmodel stap 0: meting op de laptop"
git push
```

Plak de uitvoer anders gewoon in de chat. Wat Florence-2 en de leraar per
foto zeiden, staat in `beeld\data\meting\antwoorden-<datum>.json`. Dat blijft
lokaal, maar is leuk om door te kijken: klopt wat de leraar las?

## Tests

```powershell
python -m unittest discover -s beeld/tests -t beeld/tests
```

Zonder torch, zonder netwerk. Los van de 1074 tests van de repo (`tests/`).
