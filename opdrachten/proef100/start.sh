#!/bin/bash
# Na een containerherstart: Ollama (met ruime laadtijd: 9b haalde de standaard
# 5 minuten niet) en de pijplijn starten, als ze nog niet draaien.
S=/tmp/claude-0/-home-user-Marktplaats-koopjes-finder/edcedf17-4525-561e-b9e7-4e563201e580/scratchpad
O=$S/ollama
cd $S/test100
if ! pgrep -f "ollam[a] serve" > /dev/null; then
  OLLAMA_MODELS=$O/models OLLAMA_LOAD_TIMEOUT=20m SSL_CERT_FILE=/root/.ccr/ca-bundle.crt \
    nohup setsid $O/bin/ollama serve > $O/serve.log 2>&1 < /dev/null &
  for i in $(seq 1 30); do curl -s localhost:11434/api/tags > /dev/null && break; sleep 1; done
fi
if grep -q "pijplijn2 KLAAR" pijplijn.log; then echo "pijplijn al klaar"; exit 0; fi
if ! pgrep -f "bash pijplij[n].sh" > /dev/null; then
  echo "$(date '+%F %T') herstart (start.sh)" >> pijplijn.log
  nohup setsid bash pijplijn.sh > /dev/null 2>&1 < /dev/null &
  echo "pijplijn gestart"
else
  echo "pijplijn draait al"
fi
