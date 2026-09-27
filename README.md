# good-cop

**A second opinion on every tool call your coding agent makes.**

[![test](https://github.com/timainge/good-cop/actions/workflows/test.yml/badge.svg)](https://github.com/timainge/good-cop/actions/workflows/test.yml)
![status: experimental](https://img.shields.io/badge/status-experimental-orange)
![license: MIT](https://img.shields.io/badge/license-MIT-blue)

> **Experimental.** Built and evaluated on one developer's sessions over a weekend. Useful, measured, and honest about its limits, but not hardened. Expect rough edges and breaking changes.

good-cop watches an AI coding agent (Claude Code or OpenAI Codex, with others in progress) through the agent's own hook system. For every tool call it:

1. **records** what happened in an append-only event log,
2. **remembers** the facts that matter: which files the session wrote (including from the shell), which scripts it ran, which hosts it contacted, which kube context, cloud profile or git branch is active,
3. **asks** your rules whether the pending call is a problem. A rule can be a regex, a check on those facts, or a plain-English question answered by a model (a frontier LLM, a fast decision model, or one running on your laptop),
4. **logs, asks you, or blocks.** Log-only by default.

And because everything is recorded, it can **replay your past sessions** through a new rule or model, so you can measure a rule before you trust it.

```
agent ──hooks──► good-cop hook ──► events.jsonl  (append-only log, the source of truth)
                        │          ledger.json   (facts: files written, scripts run, env, hosts)
                        └── pre-tool ──► rules ──► judge ──► allow / ask / deny  (+ decisions.jsonl)
```

## Why

Agents with broad permissions make ordinary mistakes: the wrong kube context, a script written three steps ago that now deploys to production, a destructive command in the wrong directory. Permission allowlists see `./deploy.sh`. They don't see what's inside it, whether the agent wrote it, or which environment is active.

good-cop keeps those facts and gives them to the judge, so a rule like *"does this call deploy to production?"* is answered in context.

It's for **catching mistakes and indirection**. It is not a security boundary: see [SECURITY.md](SECURITY.md) and [docs/use-cases.md](docs/use-cases.md).

## What we found

Backtests on our own Claude Code history (600 labelled tool calls, five harmless test rules). Anecdotal; full detail and caveats in [docs/results.md](docs/results.md).

| judge | quality (mean F1) | latency p50 | cost / 1k calls | data leaves machine |
|---|---|---|---|---|
| **Jev** (TypeSafe decision model) + rule criteria, threshold ~0.9 | **0.84–0.97** | **0.29 s** | ~$0.08 | yes (redacted) |
| Claude Haiku 4.5 | 0.57–0.91 | 1.1 s | ~$2.40 | yes (redacted) |
| gpt-5-mini | 0.66–0.79 | 1.0 s | ~$0.85 | yes (redacted) |
| Kev-4B (open decision model, local) | 0.71–0.76 | 2.0 s | $0 | no |
| qwen2.5-7b via Ollama (local) | ~0.75 | 8 s | $0 | no |

- **A decision model, given a precise spec, matched or beat the LLMs** at 4× lower latency and ~30× lower cost. Writing each rule's yes/no `criteria` roughly doubled Jev's held-out F1 at the default threshold.
- **Models were often right when our code was wrong.** Most early "judge errors" were our parser missing `cat > x.sh <<EOF`, `cd dir && ./x.sh` and `npm run check` (which runs the tests). The judges saw through them.
- **Some things belong in code.** A "writes outside the workspace" rule kept firing on reads however it was worded. It's now a fact check on recorded write paths. See [docs/model-strategy.md](docs/model-strategy.md).

## Getting started

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). macOS or Linux.

```sh
git clone https://github.com/timainge/good-cop && cd good-cop
uv sync
```

**Claude Code:**

```sh
uv run good-cop install              # adds hooks to ~/.claude/settings.json (backed up first)
```

**OpenAI Codex CLI:**

```sh
uv run good-cop install --harness codex   # writes ~/.codex/hooks.json; then trust it with /hooks in codex
```

Either command also creates `~/.good-cop/config.yaml` and `~/.good-cop/rules.yaml`. Now use your agent as normal, then:

```sh
uv run good-cop show                 # facts, recent decisions, hook and judge latency for the latest session
uv run good-cop uninstall            # (--harness codex) removes exactly what install added
```

Every hook fails open: if good-cop errors or a judge times out, the tool call proceeds and the error goes to `~/.good-cop/errors.log`.

### Choose a judge

Set `judge` in `~/.good-cop/config.yaml`. Keys come from environment variables. Hooks inherit your agent's environment, so export them where you launch it.

| provider | env | notes |
|---|---|---|
| `anthropic` (default) | `ANTHROPIC_API_KEY` | Haiku 4.5: accurate out of the box, insensitive to threshold |
| `jev` | `TYPESAFE_API_KEY` | TypeSafe's Jev: fastest and cheapest; set `threshold: 0.85`–`0.9` and write rule `criteria` ([example](examples/configs/jev-typesafe.yaml)) |
| `openai` | `OPENAI_API_KEY` | gpt-5-mini, or any OpenAI-compatible server via `base_url` |
| `ollama` | none | local; fine for backtests, too slow for live use at our state sizes |
| `jev` + local `base_url` | none | any Jev-compatible local server, e.g. [Kev](https://github.com/jaredpalmer/kev) ([example](examples/configs/kev-local.yaml)) |

Optional: `escalate` re-asks a second judge only when the first is unsure ([example](examples/configs/jev-cascade.yaml)).

### Write rules

`~/.good-cop/rules.yaml`. Three kinds, mixed freely:

```yaml
enforce: false                    # log only; set true to turn ask/deny into real decisions
defaults: {threshold: 0.6, action: ask}

rules:
  # 1. pattern: a regex over the command (or the tool input). No model call.
  - id: destructive_rm
    when: {tools: [Bash]}
    pattern: 'rm\s+-rf\s+(/|~|\$HOME)(\s|$)'
    action: deny

  # 2. fact: a check on recorded state. No model call.
  - id: outside_workspace
    fact: resolved.writes[].outside_cwd       # any file this call writes lies outside the project
  - id: prod_context
    fact: ledger.env.kube_context
    matches: '^prod'

  # 3. question: answered by the judge. All questions for a call go in one request.
  - id: prod_target
    when: {tools: [Bash, "mcp__*"]}
    question: Does this tool call deploy to, modify, or run commands against a production environment?
    criteria:                                 # optional, strongly recommended (esp. for Jev)
      true: It targets a production cluster, database, account or URL, directly or via a script it runs.
      false: It targets dev, staging or local resources, or only reads documentation or config.
```

The judge sees the pending call, the ledger's facts, any script the call will run (its first 4 KB), the files it will write, and recent events. `good-cop show` prints exactly that state.

### Backtest before you trust

```sh
uv run good-cop import --all                          # your past Claude Code transcripts become sessions
uv run good-cop backtest --all --limit 50 --rules my-rules.yaml --note "first try"
uv run good-cop label <session> <seq> <rule_id> yes|no    # record the right answers
uv run good-cop backtest ... --config a.yaml --config b.yaml    # compare two judges on identical calls
uv run good-cop evals                                 # every run: accuracy, latency, errors
uv run python evals/thresholds.py "first try"         # re-score saved answers at other thresholds
```

Backtest rebuilds the exact state live mode would have seen (tested: identical state hashes) and never modifies your sessions.

## Harness support

| harness | status |
|---|---|
| Claude Code | supported, verified |
| OpenAI Codex CLI | supported, verified with real payloads and a live block |
| Cursor | adapter from docs, untested (`--harness cursor`), or use Cursor's Claude-hooks compatibility |
| GitHub Copilot | adapter from docs, untested (`--harness copilot`) |
| OpenCode | plugin sketch, untested ([examples/opencode](examples/opencode/good-cop.ts)) |

Details and research: [docs/harnesses.md](docs/harnesses.md).

## Limitations

- **Client-side and removable.** Not a security boundary.
- **Judges can be wrong** and the state they read can be attacker-influenced. Measure your rules with backtest and labels; keep hard constraints in code (`pattern`, `fact`) or outside the agent entirely.
- **Latency:** a model judge adds 0.3–2 s to each tool call it applies to. Scope rules with `when.tools`.
- **Results are anecdotal:** one person's sessions, contrived rules, tens of positives per rule.

## Docs

Task-oriented guides are in the **[wiki](https://github.com/timainge/good-cop/wiki)**. Reference docs:

| | |
|---|---|
| [docs/results.md](docs/results.md) | judge comparison: quality, thresholds, criteria, cascade, speed, cost, privacy |
| [docs/model-strategy.md](docs/model-strategy.md) | LLMs vs decision models vs code as a ruleset matures |
| [docs/use-cases.md](docs/use-cases.md) | when good-cop fits, and when you want enterprise tooling instead |
| [docs/harnesses.md](docs/harnesses.md) | Codex, Cursor, Copilot, OpenCode |
| [plan.md](plan.md) | design, milestones, verified hook behaviour, follow-ups |
| [evals/](evals/) | every backtest run's metadata and metrics |

## Contributing & license

Experimental, but issues and small PRs are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). MIT licensed.
