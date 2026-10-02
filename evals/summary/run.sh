#!/usr/bin/env bash
# Does the optional rolling summary change judge quality? Fixed contrived sample, criteria rules,
# summary regenerated incrementally (no future leakage), compared with the no-summary runs.
set -u
cd "$(dirname "$0")/../.."
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }
uv run good-cop backtest 18774b8f 3c286050 bb46e7b3 85a1357b cc2ffdb5 --rules examples/contrived/rules-criteria.yaml \
  --limit 30 --workers 4 --with-summary --config evals/summary/haiku.yaml --config evals/summary/jev.yaml \
  --note "summary-$(date +%F) fixed: haiku + jev, summary by haiku"
