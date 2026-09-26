# CLAUDE.md

good-cop is a POC observer for Claude Code sessions. **plan.md is the spec**: read it before starting work, and build milestones in order. Each milestone ends with working software and passing tests.

## Commands

```sh
uv sync                      # install deps (httpx, pyyaml, pytest)
uv run pytest -q             # tests
uv run good-cop --help       # CLI
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
- Tests use `tmp_path` + monkeypatched `store.ROOT`; captured real hook payloads live in `tests/fixtures/`. Tests must not call real model APIs.
- Verify Claude Code hook schemas against the current hooks docs rather than trusting plan.md (see "Verify before building").
