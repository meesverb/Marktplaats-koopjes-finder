#!/bin/bash
# Alle lokale modellen na elkaar op de 100 testadvertenties. Hervatbaar:
# lokaal.py en visie.py slaan over wat al gedaan is. Snelle modellen eerst,
# zodat er na een containerherstart al uitkomsten liggen.
S=/tmp/claude-0/-home-user-Marktplaats-koopjes-finder/edcedf17-4525-561e-b9e7-4e563201e580/scratchpad
O=$S/ollama
V=$S/venv-beeld/bin/python
export OLLAMA_MODELS=$O/models SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
cd $S/test100
mkdir -p logs
log() { echo "$(date '+%F %T') $*" >> pijplijn.log; }
model() {  # draai één Ollama-model op alle advertenties
  log "start $1"
  python3 lokaal.py "$1" >> "logs/${1/:/_}.log" 2>&1
  log "klaar $1"
}
pull() { log "pull $1"; $O/bin/ollama pull "$1" > /dev/null 2>&1 || log "pull mislukt $1"; }
drop() { $O/bin/ollama rm "$1" > /dev/null 2>&1; log "verwijderd $1"; }
vision() {  # florence hervat per foto; siglip is in één keer klaar
  [ -f "uitkomst/$1.done" ] && return
  log "start $1"; HF_HOME=$S/hf $V visie.py $1 >> logs/$1.log 2>&1 && touch "uitkomst/$1.done"; log "klaar $1"
}

log "pijplijn start"
vision siglip2-b
if [ ! -f uitkomst/embeddinggemma-2.json ]; then
  log "start embeddinggemma-2"; python3 emb_gemma.py >> logs/embeddinggemma-2.log 2>&1; log "klaar embeddinggemma-2"
fi
drop embeddinggemma-2
model qwen3.5:2b; drop qwen3.5:2b
vision florence2-b
model gemma4:12b; drop gemma4:12b
for m in qwen3.5:4b gemma4:e2b; do pull $m; model $m; drop $m; done
model qwen3.5:9b; drop qwen3.5:9b
vision florence2-l
pull bonsai-2:27b; model bonsai-2:27b; drop bonsai-2:27b

# 35b (22 GB) past hier niet in het geheugen (15 GB): eerst 3 advertenties,
# dan pas de rest als het per advertentie onder de 20 minuten blijft.
rm -rf $S/hf   # 3,8 GB terug; de HF-modellen zijn dan al gedraaid
pull qwen3.5:35b
log "start qwen3.5:35b proef"
python3 lokaal.py qwen3.5:35b --aantal 3 >> logs/qwen3.5_35b.log 2>&1
if python3 - <<'PY'
import json, statistics, sys
d = json.load(open("uitkomst/qwen3.5_35b.json"))
t = [v["seconden"] for v in d.values() if "seconden" in v and "fout" not in v]
print("35b proef", t, file=sys.stderr)
sys.exit(0 if t and statistics.mean(t) < 1200 else 1)
PY
then model qwen3.5:35b; else log "35b te traag of werkt niet, gestopt na de proef"; fi
drop qwen3.5:35b
log "pijplijn KLAAR"
