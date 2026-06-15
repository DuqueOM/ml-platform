#!/usr/bin/env bash
# Uso: ./bench.sh <puerto> <nombre>
set -euo pipefail
PORT=$1; NAME=$2
PROMPT='Clasifica: tienen coca de 600 fria?'
START=$(date +%s.%N)
RESP=$(curl -s http://127.0.0.1:$PORT/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"'"$PROMPT"'"}],"max_tokens":120,"temperature":0}')
END=$(date +%s.%N)
TOKENS=$(echo "$RESP" | python3 -c 'import sys,json; data=json.load(sys.stdin); print(data["usage"]["completion_tokens"])' 2>&1) || {
  echo "Error parsing response from port $PORT"
  echo "$RESP" | python3 -m json.tool
  exit 1
}
LATENCY=$(echo "$END-$START" | bc -l)
TOKS=$(echo "$TOKENS/$LATENCY" | bc -l | cut -c1-5)
echo "$NAME: $TOKS tok/s (${TOKENS}tok in ${LATENCY}s)" | tee -a RESULTS.md
