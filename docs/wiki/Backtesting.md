# Backtesting

Every hook event is recorded, so good-cop can replay sessions through new rules or judges without running the agent again.

```sh
uv run good-cop import --all                    # past Claude Code transcripts -> good-cop sessions
uv run good-cop backtest <session…> | --all \
    --rules my-rules.yaml --limit 50 --note "prod rule v2"
uv run good-cop backtest ... --config a.yaml --config b.yaml   # two judges, identical calls
uv run good-cop label <session> <seq> <rule_id> yes|no          # record the right answer
uv run good-cop evals                           # list runs: accuracy, latency, errors
uv run python evals/thresholds.py "prod rule"   # re-score saved answers at other thresholds (free)
```

- **Faithful:** backtest rebuilds exactly the state live mode would have seen (tested with identical state hashes). It never modifies session files; results go to `~/.good-cop/backtests/`.
- **Each run saves** `<ts>.jsonl` (every decision) and `<ts>.summary.json` (note, git sha, rules, judge config, metrics).
- **Labels are the durable asset.** They outlive any model choice. Accuracy, precision and recall are reported against whatever labels exist.
- **Read the disagreements.** In our evals, the "judge errors" were more often label or parser errors than model errors.
- **Hold out a sample.** Tune thresholds on one set of sessions and check them on another; with tens of positives, thresholds overfit easily.

For a worked example with code-computed labels, see `examples/contrived/` and `evals/run-comparison.sh`.
