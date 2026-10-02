# good-cop wiki

**good-cop** gives your coding agent a second opinion on every tool call. It hooks into Claude Code or OpenAI Codex, records what the agent does, keeps a ledger of facts (files written, scripts run, environment), and asks your rules whether a pending call is a problem. It logs by default, and can ask you or block when you trust a rule.

> Experimental. See the [README](https://github.com/timainge/good-cop/blob/main/README.md) for the overview and headline results.

**Start here**
- [[Getting Started]]: install for Claude Code or Codex in two minutes
- [[Writing Rules]]: patterns, facts and questions, with criteria
- [[Rulesets]]: starter rulesets for solo developers, infrastructure, data and unattended agents
- [[Choosing a Judge]]: Haiku, Jev, gpt-5-mini, local models; speed, cost, quality, privacy
- [[Handlers]]: Slack, syslog or anything else when a rule trips
- [[Backtesting]]: measure a rule on your past sessions before trusting it
- [[Other Agents]]: Codex, Cursor, Copilot, OpenCode
- [[FAQ]]

**Findings and background**
- [Results: the judge comparison](Results)
- [Red-team: what's caught when the agent is adversarial](Red-team)
- [Model strategy: LLMs vs decision models vs code](Model-Strategy)
- [Use cases: when good-cop fits](Use-Cases)
- [Harness research: Codex, Cursor, Copilot, OpenCode](Harness-Research)
- [Design and plan (repo)](https://github.com/timainge/good-cop/blob/main/plan.md)
