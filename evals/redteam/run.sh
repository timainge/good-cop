#!/usr/bin/env bash
# Red-team suite under code-only rules and every judge (model runs cost API calls; run by hand).
set -u
cd "$(dirname "$0")/../.."
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }
out="evals/runs/redteam-$(date +%F).md"
uv run python evals/redteam/run.py \
  --config evals/rulesets/jev.yaml \
  --config examples/configs/anthropic.yaml --config examples/configs/openai.yaml "$@" | tee "$out"
echo "saved $out"
