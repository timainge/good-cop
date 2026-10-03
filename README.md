# good-cop

**A second opinion on every tool call your coding agent makes.**

[![test](https://github.com/timainge/good-cop/actions/workflows/test.yml/badge.svg)](https://github.com/timainge/good-cop/actions/workflows/test.yml)
![status: experimental](https://img.shields.io/badge/status-experimental-orange)
![license: MIT](https://img.shields.io/badge/license-MIT-blue)

> **Experimental.** Built and evaluated on one developer's sessions. Measured and honest about its limits, but not hardened.

good-cop hooks into **Claude Code** or **OpenAI Codex** and, for every tool call:

1. **records** what happened (an append-only log you can replay),
2. **remembers** the facts that matter: files the session wrote, scripts it ran, hosts it contacted, the active kube context or cloud profile,
3. **checks your rules**, written as a regex, a check on those facts, or a plain-English question for a judge model (frontier LLM, fast decision model, or local),
4. **logs, asks you, or blocks**, and can **notify you** (Slack, syslog, …) via [handlers](https://github.com/timainge/good-cop/wiki/Handlers).

It also **backtests**: replay your past sessions through a new rule or judge and measure it before you trust it.

It's for catching mistakes and indirection, not a security boundary ([SECURITY.md](SECURITY.md)).

## What we found

Backtests on 600 labelled tool calls from our own Claude Code history, with five harmless test rules. Anecdotal.

| judge | quality (mean F1) | latency p50 | cost / 1k calls | local |
|---|---|---|---|---|
| **Jev** (TypeSafe decision model) + rule criteria | **0.84–0.97** | **0.29 s** | ~$0.08 | no |
| Claude Haiku 4.5 | 0.57–0.91 | 1.1 s | ~$2.40 | no |
| gpt-5-mini | 0.66–0.79 | 1.0 s | ~$0.85 | no |
| Kev-4B / qwen2.5-7b | 0.71–0.84 | 2–8 s | $0 | yes |

A decision model given a precise yes/no spec matched or beat the LLMs at a fraction of the latency and cost. Models were often right where our parser was wrong. Exact facts still belong in code. → [Full results](https://github.com/timainge/good-cop/wiki/Results) · [Model strategy](https://github.com/timainge/good-cop/wiki/Model-Strategy)

## Quick start

Python 3.12+, [uv](https://docs.astral.sh/uv/), macOS or Linux.

```sh
uv tool install git+https://github.com/timainge/good-cop   # PyPI release pending
good-cop install                          # Claude Code (or: --harness codex; --ruleset infra|data|unattended)
export ANTHROPIC_API_KEY=...              # default judge; see "Choosing a Judge"
# use your agent, then:
good-cop show
good-cop review                           # label what it flagged
```

It starts in log-only mode and fails open. → [Getting Started](https://github.com/timainge/good-cop/wiki/Getting-Started)

## Documentation: [the wiki](https://github.com/timainge/good-cop/wiki)

| | |
|---|---|
| [Getting Started](https://github.com/timainge/good-cop/wiki/Getting-Started) | install for Claude Code or Codex |
| [Writing Rules](https://github.com/timainge/good-cop/wiki/Writing-Rules) | patterns, facts, questions with criteria, thresholds |
| [Rulesets](https://github.com/timainge/good-cop/wiki/Rulesets) | starter rulesets: solo-dev, infra, data, unattended |
| [Red-team](https://github.com/timainge/good-cop/wiki/Red-team) | what the rules and judges catch when the agent is adversarial |
| [Benchmarks](https://github.com/timainge/good-cop/wiki/Benchmarks) | RedCode and R-Judge: good-cop vs. a regex guard and whole-trajectory judges |
| [Choosing a Judge](https://github.com/timainge/good-cop/wiki/Choosing-a-Judge) | Jev, Haiku, gpt-5-mini, local models, cascades |
| [Handlers](https://github.com/timainge/good-cop/wiki/Handlers) | Slack, syslog or any command when a rule trips |
| [Backtesting](https://github.com/timainge/good-cop/wiki/Backtesting) | measure rules and judges on your own history |
| [Other Agents](https://github.com/timainge/good-cop/wiki/Other-Agents) | Codex (verified), Cursor, Copilot, OpenCode |
| [Results](https://github.com/timainge/good-cop/wiki/Results) · [Model Strategy](https://github.com/timainge/good-cop/wiki/Model-Strategy) · [Use Cases](https://github.com/timainge/good-cop/wiki/Use-Cases) · [FAQ](https://github.com/timainge/good-cop/wiki/FAQ) | findings and background |

## Contributing & license

Experimental, but issues and small PRs are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Design notes are in [plan.md](plan.md). MIT licensed.
