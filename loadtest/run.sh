#!/usr/bin/env sh
# Прогон k6 по ступеням RPS внутри сети compose + docker stats контейнера api.
# Использование: sh loadtest/run.sh [BASE] [ступени...]   (по умолчанию http://api:8000 и 200 400 800)
set -e
cd "$(dirname "$0")/.."
BASE=${1:-http://api:8000}; shift 2>/dev/null || true
RATES=${*:-200 400 800}
NET=$(docker network ls --format '{{.Name}}' | grep -m1 '_default$')
API=$(docker compose ps -q api | head -1)
mkdir -p loadtest/results
for r in $RATES; do
  : > "loadtest/results/stats_$r.txt"
  ( while [ ! -f loadtest/results/.stop ]; do
      docker stats --no-stream --format '{{.CPUPerc}};{{.MemUsage}}' "$API" >> "loadtest/results/stats_$r.txt"; done ) &
  MSYS_NO_PATHCONV=1 docker run --rm --network "$NET" -v "$PWD/loadtest:/scripts" -e BASE="$BASE" -e RATE="$r" \
    grafana/k6 run --quiet /scripts/k6.js > "loadtest/results/k6_$r.txt" 2>&1 || true
  touch loadtest/results/.stop; wait; rm -f loadtest/results/.stop
  echo "== $r RPS"; grep -E "http_req_duration\.|http_req_failed\.|http_reqs\.|dropped" "loadtest/results/k6_$r.txt"
  awk -F';' '{gsub("%","",$1); split($2,m," "); c+=$1; if($1+0>cm)cm=$1+0; n++} END {printf "   CPU avg %.0f%%  max %.0f%%  (100%% = 1 vCPU), RAM %s\n", c/n, cm, m[1]}' "loadtest/results/stats_$r.txt"
done
