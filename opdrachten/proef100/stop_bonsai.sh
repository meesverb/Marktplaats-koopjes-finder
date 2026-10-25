#!/bin/bash
# Stopt de lopende bonsai-run zodra er 20 advertenties zijn (keuze van de
# eigenaar); de pijplijn gaat dan door met de proef van qwen3.5:35b.
cd /tmp/claude-0/-home-user-Marktplaats-koopjes-finder/edcedf17-4525-561e-b9e7-4e563201e580/scratchpad/test100
while :; do
  n=$(python3 -c "import json;print(len(json.load(open('uitkomst/bonsai-2_27b.json'))))" 2>/dev/null || echo 0)
  if [ "$n" -ge 20 ]; then
    pkill -f "lokaal.py bonsai-2:27[b]"
    echo "$(date '+%F %T') bonsai gestopt na $n advertenties" >> pijplijn.log
    break
  fi
  pgrep -f "lokaal.py bonsai-2:27[b]" > /dev/null || break
  sleep 30
done
