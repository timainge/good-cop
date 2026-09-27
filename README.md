# good-cop

A local-first observer for Claude Code sessions. It records every hook event and keeps a deterministic ledger of facts: environment, files written (including from the shell), scripts run and hosts contacted. For each tool call it asks an LLM judge (Anthropic, OpenAI, a local Ollama model, or TypeSafe's Jev decision model) whether any rule trips. By default it only logs; enforcement (`ask`/`deny`) is opt-in.

Two modes share the same code:

- **Live:** `good-cop install` wires it into Claude Code hooks.
- **Backtest:** `good-cop backtest` replays recorded sessions through any rules and model config, and reports trip rates, agreement between configs, label accuracy and latency.

See [plan.md](plan.md) for the design, what was verified, and backtest results on real sessions.

## Setup

```sh
uv sync
uv run good-cop install                      # hooks -> ~/.claude/settings.json (backed up), config -> ~/.good-cop/
uv run good-cop install --settings path.json # or any other settings file (e.g. for claude --settings)
```

Edit `~/.good-cop/config.yaml` (provider, model, optional summary) and `~/.good-cop/rules.yaml`. Keys come from `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `TYPESAFE_API_KEY` (or `AI_GATEWAY_API_KEY` for Jev via Vercel, see `examples/configs/jev-vercel.yaml`); Ollama needs none. Hooks inherit Claude Code's environment, so export keys there; for backtests from this repo, `set -a; . ./.env.local; set +a`. Set `GOOD_COP_HOME` to use another data dir.

## Live

```sh
good-cop show [session]        # ledger, summary, recent decisions, hook/judge latency
good-cop uninstall
```

Rules are either a regex `pattern` (no model call) or a `question` (all model questions for a call are batched into one judge call). Set `enforce: true` in rules.yaml to turn tripped `ask`/`deny` actions into real hook decisions.

## Backtest

```sh
good-cop import --all                            # Claude Code transcripts -> sessions (test data)
good-cop backtest <session…> | --all [--limit N] [--rules r.yaml] \
    [--config a.yaml --config b.yaml] [--with-summary]
good-cop label <session> <seq> <rule_id> yes|no  # human labels; backtest reports accuracy
```

To reproduce the results in plan.md with harmless contrived rules that have code-computed ground truth:

```sh
uv run good-cop import --all
uv run python examples/contrived/autolabel.py
uv run good-cop backtest <sessions…> --rules examples/contrived/rules.yaml --limit 100 \
    --config examples/configs/anthropic.yaml --config examples/configs/openai.yaml
```
