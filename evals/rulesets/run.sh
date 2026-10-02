#!/usr/bin/env bash
# Starter rulesets on real recorded sessions: Jev (t=0.9) vs Haiku, identical calls.
# Unlabelled until R1 labels exist: read trips and agreement, then `good-cop review --from-backtest latest`.
set -u
cd "$(dirname "$0")/../.."
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }
uv run good-cop backtest --all --limit "${LIMIT:-20}" --workers 8 --rules evals/rulesets/all.yaml \
  --config evals/rulesets/jev.yaml --config examples/configs/anthropic.yaml --note "rulesets-$(date +%F): jev-0.9 vs haiku"
