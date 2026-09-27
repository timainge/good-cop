#!/usr/bin/env bash
# Criteria-style rules (examples/contrived/rules-criteria.yaml) through every judge, on the fixed
# 150-call sample and (cloud judges) the 450-call held-out sample. Compare with evals/thresholds.py.
set -u
cd "$(dirname "$0")/.."
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }
R=examples/contrived/rules-criteria.yaml
FIXED="18774b8f 3c286050 bb46e7b3 85a1357b cc2ffdb5"
HOLD="7746dc5b fd4f78e5 5d775dc0"
run() { uv run good-cop backtest $1 --rules $R --limit $2 --workers $3 --config examples/configs/$4.yaml --note "criteria-2026-09-28 $5: $4"; }
run "$FIXED" 30 4 anthropic fixed > /tmp/gcc-haiku-f.log 2>&1 &
run "$HOLD" 150 8 anthropic holdout > /tmp/gcc-haiku-h.log 2>&1 &
run "$FIXED" 30 4 openai fixed > /tmp/gcc-openai-f.log 2>&1 &
run "$HOLD" 150 8 openai holdout > /tmp/gcc-openai-h.log 2>&1 &
until curl -sf -m 2 localhost:8009/v1/models >/dev/null; do sleep 5; done
run "$FIXED" 30 1 kev-local fixed > /tmp/gcc-kev-f.log 2>&1
run "$FIXED" 30 1 ollama fixed > /tmp/gcc-ollama-f.log 2>&1
wait
head -n 4 /tmp/gcc-*.log
