# Eval runs

One `*.summary.json` per `good-cop backtest` run, copied from `~/.good-cop/backtests/`: run metadata (`meta`: note, git sha, argv, sessions, rules as run, judge configs without keys, label count) and scored metrics (`metrics`: per-config latency and errors, per-rule trips, label accuracy/precision/recall, cross-config agreement). No transcript content; the per-decision `*.jsonl` files stay in `~/.good-cop/backtests/`.

Runs marked `backfilled` predate run summaries: they were re-scored from their saved decisions against the labels as of backfill, and their rules are the files as they stood then (the default safety rules were reworded between runs, see the notes).

```sh
uv run good-cop evals                      # list runs from ~/.good-cop/backtests
cp ~/.good-cop/backtests/*.summary.json evals/runs/
```
