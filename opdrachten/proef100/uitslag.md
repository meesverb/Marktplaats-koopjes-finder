# Uitslag beeldtest 100 advertenties

Per cel: goed/fout/weet niet (precisie = goed van wat het model durfde te zeggen). +N∅ = advertenties zonder antwoord van dat model.

Meerderheidsklasse: rem altijd 'rim': 94/98; materiaal altijd 'aluminium': 64/95; wielprofiel altijd 'shallow': 98/100

| model | merk leesbaar (n=94) | merk niet leesbaar (n=4) | groep leesbaar (n=54) | groep niet leesbaar (n=13) | groep genoemd, sleutel leeg | rem | materiaal | wielprofiel |
|---|---|---|---|---|---|---|---|---|
| claude-haiku | 87/5/2 (94%) | 0/0/4 | 43/2/9 (95%) | 5/0/8 (100%) | 0 | 95/0/3 (100%) | 28/4/63 (87%) | 89/1/10 (98%) |
| claude-sonnet | 93/1/0 (98%) | 0/0/4 | 51/2/1 (96%) | 8/0/5 (100%) | 0 | 96/1/1 (98%) | 70/0/25 (100%) | 100/0/0 (100%) |
| claude-opus | 94/0/0 (100%) | 0/0/4 | 50/1/3 (98%) | 8/1/4 (88%) | 0 | 97/1/0 (98%) | 61/0/34 (100%) | 99/1/0 (99%) |
| embeddinggemma-2 | 93/1/0 (98%) | 0/4/0 (0%) | 0/0/54 | 0/0/13 | 0 | 69/29/0 (70%) | 63/32/0 (66%) | 64/36/0 (64%) |
| embeddinggemma-2 (repo-merken) | 68/26/0 (72%) | 0/4/0 (0%) | 0/0/54 | 0/0/13 | 0 | 69/29/0 (70%) | 63/32/0 (66%) | 64/36/0 (64%) |
| florence2-b | 42/1/51 (97%) | 0/0/4 | 19/3/32 (86%) | 0/0/13 | 0 | 0/0/98 | 0/0/95 | 0/0/100 |
| gemma4_12b | 0/0/0 +94∅ | 0/0/0 +4∅ | 0/0/0 +54∅ | 0/0/0 +13∅ | 0 | 0/0/0 +98∅ | 0/0/0 +95∅ | 0/0/0 +100∅ |
| qwen3.5_2b | 71/16/6 (81%) +1∅ | 0/2/2 (0%) | 18/0/35 (100%) +1∅ | 0/1/12 (0%) | 0 | 11/51/35 (17%) +1∅ | 41/14/39 (74%) +1∅ | 28/28/43 (50%) +1∅ |
| qwen3.5_4b | 49/11/0 (81%) +34∅ | 0/1/1 (0%) +2∅ | 20/2/10 (90%) +22∅ | 1/1/6 (50%) +5∅ | 1 | 12/0/48 (100%) +38∅ | 10/4/43 (71%) +38∅ | 0/10/52 (0%) +38∅ |
| siglip2-b | 9/85/0 (9%) | 0/4/0 (0%) | 0/0/54 | 0/0/13 | 0 | 97/1/0 (98%) | 52/43/0 (54%) | 94/6/0 (94%) |
| siglip2-b (repo-merken) | 7/87/0 (7%) | 0/4/0 (0%) | 0/0/54 | 0/0/13 | 0 | 97/1/0 (98%) | 52/43/0 (54%) | 94/6/0 (94%) |

## Staat (niet gescoord): aandeel 'unknown'

| model | chain_rusty | tyres_worn | bar_tape_or_saddle_torn | parts_missing | paint_damage |
|---|---|---|---|---|---|
| claude-haiku | 0.16 | 0.54 | 0.04 | 0.27 | 0.35 |
| claude-sonnet | 0.36 | 0.27 | 0.01 | 0.05 | 0.49 |
| claude-opus | 0.36 | 0.36 | 0.12 | 0.03 | 0.44 |
| qwen3.5_2b | 0.25 | 0.25 | 0.25 | 0.95 | 1.0 |
| qwen3.5_4b | 0.4 | 0.53 | 0.44 | 0.48 | 1.0 |

## Kosten

- **claude-haiku**: batches met uitkomst: 20, batches met tokentelling: 20, tokens (bekende batches): 2895159, advertenties daarin: 100, foto's daarin: 910, tokens per advertentie: 28952, tokens per foto: 3181, per foto (lijn): 1399, vaste voet per batch (lijn): 81109, seconden per advertentie: 32.5, onbekend: []
- **claude-sonnet**: batches met uitkomst: 20, batches met tokentelling: 14, tokens (bekende batches): 1595027, advertenties daarin: 70, foto's daarin: 575, tokens per advertentie: 22786, tokens per foto: 2774, per foto (lijn): 1141, vaste voet per batch (lijn): 67052, seconden per advertentie: 17.0, onbekend: ['sonnet_b12', 'sonnet_b13', 'sonnet_b14', 'sonnet_b15', 'sonnet_b18', 'sonnet_b20']
- **claude-opus**: batches met uitkomst: 20, batches met tokentelling: 11, tokens (bekende batches): 1328717, advertenties daarin: 55, foto's daarin: 540, tokens per advertentie: 24158, tokens per foto: 2461, per foto (lijn): 1019, vaste voet per batch (lijn): 70770, seconden per advertentie: 23.5, onbekend: ['opus_b01', 'opus_b02', 'opus_b03', 'opus_b04', 'opus_b05', 'opus_b06', 'opus_b08', 'opus_b09', 'opus_b10']
- **embeddinggemma-2**: foto's: 910, seconden totaal: 4546.9, tokens in (som): 213508
- **florence2-b**: foto's: 910, seconden totaal: 1668, tokens uit (som): 8263
- **gemma4_12b**: advertenties: 0
- **qwen3.5_2b**: advertenties: 100, fouten: 0, tokens in (som): 499007, tokens uit (som): 17500, tokens per advertentie: 5165, seconden per advertentie (mediaan): 108.5, seconden totaal: 13496
- **qwen3.5_4b**: advertenties: 64, fouten: 2, tokens in (som): 300799, tokens uit (som): 13132, tokens per advertentie: 4905, seconden per advertentie (mediaan): 171.1, seconden totaal: 11563
- **siglip2-b**: foto's: 910, seconden totaal: 348.5
