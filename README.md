# good-cop

A local-first observer for Claude Code sessions. It records every hook event, keeps a deterministic ledger of facts (environment, files written, hosts contacted), and asks an LLM judge (Anthropic, OpenAI or a local Ollama model) whether each tool call trips a rule. By default it only logs; enforcement is opt-in.

Two modes:

- **Live:** `good-cop install` wires it into Claude Code hooks.
- **Backtest:** `good-cop backtest` replays recorded sessions through the rules with any model config and reports agreement, label accuracy and latency.

See [plan.md](plan.md) for the design and milestones.

## Setup

```sh
uv sync
uv run good-cop --help
mkdir -p ~/.good-cop
cp config.example.yaml ~/.good-cop/config.yaml
cp rules.example.yaml ~/.good-cop/rules.yaml
```

Status: scaffold. Milestone 1 (capture) is next.
