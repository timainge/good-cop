# CLAUDE.md

good-cop is a POC observer for Claude Code sessions. **plan.md is the spec**: read it before changing behaviour. All six milestones are built; plan.md's Results section records what backtests on real sessions showed.

## Commands

```sh
uv sync                      # install deps (httpx, pyyaml, pytest)
uv run pytest -q             # tests
uv run good-cop --help       # CLI
uv run good-cop import --all && uv run python examples/contrived/autolabel.py   # backtest data
uv run good-cop backtest <sid…> --rules examples/contrived/rules.yaml --limit 50  # costs API calls
```

Set `GOOD_COP_HOME=/some/tmp/dir` to keep dev runs out of `~/.good-cop`.

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
- Verify Claude Code hook schemas against the current hooks docs rather than trusting plan.md (see "Verify before building").
