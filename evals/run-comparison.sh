#!/usr/bin/env bash
# One fixed sample (5 sessions x 30 calls, contrived rules) through every judge.
# Cloud judges run concurrently; local ones one at a time so they don't share the GPU.
# Needs: transcripts imported + autolabelled, ANTHROPIC/OPENAI keys, AI_GATEWAY_API_KEY (Jev),
# a Kev server on :8009 and Ollama with qwen2.5:7b-instruct.
set -u
cd "$(dirname "$0")/.."
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }
SAMPLE="18774b8f 3c286050 bb46e7b3 85a1357b cc2ffdb5"
BT() { uv run good-cop backtest $SAMPLE --rules examples/contrived/rules.yaml --limit 30 "$@"; }
TAG="${1:-comparison}"

BT --config examples/configs/anthropic.yaml --workers 4 --note "$TAG: haiku 4.5 (run 1)" > /tmp/gc-haiku1.log 2>&1 &
BT --config examples/configs/anthropic.yaml --workers 4 --note "$TAG: haiku 4.5 (run 2, variance)" > /tmp/gc-haiku2.log 2>&1 &
BT --config examples/configs/openai.yaml --workers 4 --note "$TAG: gpt-5-mini minimal reasoning" > /tmp/gc-openai.log 2>&1 &
BT --config examples/configs/jev-vercel.yaml --workers 1 --note "$TAG: jev via vercel (latency includes 429 retries)" > /tmp/gc-jev.log 2>&1 &
BT --config examples/configs/kev-local.yaml --workers 1 --note "$TAG: kev-4b local bf16 MLX M5" > /tmp/gc-kev.log 2>&1
BT --config examples/configs/ollama.yaml --workers 1 --note "$TAG: ollama qwen2.5:7b-instruct M5" > /tmp/gc-ollama.log 2>&1
wait
tail -n 3 /tmp/gc-*.log
