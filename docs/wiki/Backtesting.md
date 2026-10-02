# Backtesting

Every hook event is recorded, so good-cop can replay sessions through new rules or judges without running the agent again.

```sh
good-cop import --all                    # past Claude Code transcripts -> good-cop sessions
good-cop backtest <session…> | --all \
    --rules my-rules.yaml --limit 50 --note "prod rule v2"
good-cop backtest ... --config a.yaml --config b.yaml   # two judges, identical calls
good-cop review [--since 7d] [--from-backtest RUN]       # label calls interactively (below)
good-cop label <session> <seq> <rule_id> yes|no          # or record one answer by hand
good-cop evals                           # list runs: accuracy, latency, errors
uv run python evals/thresholds.py "prod rule"   # re-score saved answers at other thresholds (free)
```

- **Faithful:** backtest rebuilds exactly the state live mode would have seen (tested with identical state hashes). It never modifies session files; results go to `~/.good-cop/backtests/`.
- **Each run saves** `<ts>.jsonl` (every decision) and `<ts>.summary.json` (note, git sha, rules, judge config, metrics).
- **Labels are the durable asset.** They outlive any model choice. Accuracy, precision and recall are reported against whatever labels exist.
- **Read the disagreements.** In our evals, the "judge errors" were more often label or parser errors than model errors.
- **Hold out a sample.** Tune thresholds on one set of sessions and check them on another; with tens of positives, thresholds overfit easily.

## The review → backtest → tune loop

Labels are what turn "the judge said 0.7" into a threshold you can trust. `good-cop review` makes them cheap: it walks tool calls in the order that teaches you the most, shows a one-screen card per call, and takes a single key.

```sh
good-cop review                          # live decisions from sessions active in the last 7 days
good-cop review --since 30d --rule prod_target
good-cop review --from-backtest latest   # a saved run: judges' disagreements come first
```

Order of the queue (anything already labelled, including "unsure", is never asked again):

1. **Disagreements** (with `--from-backtest` over two `--config`s): one judge tripped, the other didn't.
2. **Tripped** calls: are these real? This measures precision.
3. **Near-misses:** p within ±0.2 of the rule's threshold, most borderline first.
4. **A sample of clear negatives** (`--negatives 10`): the only way to estimate what was missed (recall).

Each card shows the tool and command, cwd, the first lines of any script being run, the files the call writes, the rule's question and criteria, and every judge's p (`!` = tripped). Keys: `y` yes, `n` no, `u` unsure (stored, excluded from scoring), `s` skip, `o` open the full event and decision state, `q` quit. Labels are appended to `~/.good-cop/labels.jsonl` with `source: review`, your user name (`--labeller`) and a timestamp.

On exit, review prints how many you labelled, how often each judge agreed with you, and a **suggested threshold** per rule and judge: the one with the best F1 over all your labels. Then:

1. Put the suggestion in config (`judge.threshold`, or a rule's own `threshold`).
2. Backtest again on *other* sessions to check it holds (`good-cop backtest --all --note "t=0.85"`).
3. When a rule keeps tripping on the same false positive, reword the question or add `criteria`, then review the new run's disagreements.

For imported sessions (no live decisions), backtest first and review the run: `good-cop backtest --all --limit 50 && good-cop review --from-backtest latest`.

## Worked example

For a worked example with code-computed labels, see `examples/contrived/` and `evals/run-comparison.sh`.
