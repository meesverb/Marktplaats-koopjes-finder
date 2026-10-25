#!/bin/bash
# Laatste ronde (25-10): bonsai-2:27b (op 20 advertenties, keuze van de eigenaar: ~24 min per advertentie) en de proef met qwen3.5:35b, die op
# 25-10 04:18 niet binnenkwamen omdat de schijf vol was.
S=/tmp/claude-0/-home-user-Marktplaats-koopjes-finder/edcedf17-4525-561e-b9e7-4e563201e580/scratchpad
O=$S/ollama
export OLLAMA_MODELS=$O/models SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
cd $S/test100
log() { echo "$(date '+%F %T') $*" >> pijplijn.log; }
pull() { log "pull $1"; $O/bin/ollama pull "$1" >> "logs/pull_${1/:/_}.log" 2>&1 || log "pull mislukt $1"; }
drop() { $O/bin/ollama rm "$1" > /dev/null 2>&1; log "verwijderd $1"; }

log "pijplijn2 start"
pull bonsai-2:27b
log "start bonsai-2:27b"; python3 lokaal.py bonsai-2:27b --aantal 20 >> logs/bonsai-2_27b.log 2>&1; log "klaar bonsai-2:27b"
drop bonsai-2:27b
# 35b (22 GB) past niet in de 15 GB geheugen hier: eerst 3 advertenties,
# de rest alleen als het per advertentie onder de 20 minuten blijft.
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
then log "start qwen3.5:35b"; python3 lokaal.py qwen3.5:35b >> logs/qwen3.5_35b.log 2>&1; log "klaar qwen3.5:35b"
else log "35b te traag of werkt niet, gestopt na de proef"; fi
drop qwen3.5:35b
log "pijplijn2 KLAAR"
