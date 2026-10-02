# CLAUDE.md

good-cop is a POC observer for Claude Code sessions. **plan.md is the spec**: read it before changing behaviour. All six milestones are built; plan.md's Results section records what backtests on real sessions showed.

## Commands

```sh
uv sync                      # install deps (httpx, pyyaml, pytest)
uv run pytest -q             # tests
uv run good-cop --help       # CLI
uv run good-cop import --all && uv run python examples/contrived/autolabel.py   # backtest data
uv run good-cop backtest <sid…> --rules examples/contrived/rules.yaml --limit 50  # costs API calls
uv run good-cop review --from-backtest latest         # label interactively
uv run good-cop rules show [--ruleset infra]          # effective rules after include:
uv run python evals/redteam/run.py                    # red-team, code rules only (also in pytest)
```

Set `GOOD_COP_HOME=/some/tmp/dir` to keep dev runs out of `~/.good-cop`.

Public-facing docs (guides, results, model strategy, use cases, harness research) live in the GitHub wiki; source is `docs/wiki/`, published with `scripts/publish-wiki.sh`. Keep the README a short landing page that links there. Eval run summaries are in `evals/runs/` (`evals/run-comparison.sh`, `evals/compare.py`, `evals/thresholds.py`).

## Rules for this codebase

- **Keep it simple.** Small flat modules in `src/good_cop/`, plain functions and dicts, no class hierarchies or plugin systems. The only abstraction is the `LLM` protocol in `providers.py`. If something needs a new layer, change plan.md first.
- **Dependencies:** stdlib + `httpx` + `pyyaml`. No provider SDKs (anthropic/openai/ollama are plain HTTP calls). Ask before adding anything.
- **Fail open.** Nothing in the `hook` path may raise, block, or exit non-zero (except an explicit enforce-mode deny). Log to `errors.log` via `store.log_error` and move on. Respect the time budget.
- **Event log is the source of truth.** Ledger, summary and decisions are projections; `rebuild(events)` must equal the incrementally folded ledger. Anything live mode reads from the outside world (probes, script heads) gets recorded as an event so backtest sees the same thing.
- **Summary is optional.** No rule may depend on the summary. Code must work with `summary.enabled: false` (state has `"summary": null`).
- **Live and backtest share code.** `ledger`, `context`, `rules`, `judge` must not know which mode they run in.
- **Never log secrets.** Redaction runs on prompts for cloud providers; log counts, not values.
- Tests use the `home` fixture (monkeypatched `store.ROOT`) and `fake_llm`; captured real hook payloads and a transcript live in `tests/fixtures/`. Tests must not call real model APIs.
- State given to the judge must be a pure function of recorded events, so live and backtest produce the same `state_hash` (`test_replay_matches_live_state`). Anything read from disk or the environment goes into an event first.
- Starter rulesets live in `src/good_cop/rulesets/` and ship in the wheel; every question rule needs `criteria` and `when.tools` (tested). A red-team scenario's `code_caught` is asserted in CI: when a fix changes it, update the scenario file.
- Verify Claude Code hook schemas against the current hooks docs rather than trusting plan.md (see "Verify before building").
