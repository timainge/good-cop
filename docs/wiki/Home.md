# good-cop wiki

**good-cop** gives your coding agent a second opinion on every tool call. It hooks into Claude Code or OpenAI Codex, records what the agent does, keeps a ledger of facts (files written, scripts run, environment), and asks your rules whether a pending call is a problem. It logs by default, and can ask you or block when you trust a rule.

> Experimental. See the [README](https://github.com/timainge/good-cop/blob/main/README.md) for the overview and headline results.

**Start here**
- [[Getting Started]]: install for Claude Code or Codex in two minutes
- [[Writing Rules]]: patterns, facts and questions, with criteria
- [[Choosing a Judge]]: Haiku, Jev, gpt-5-mini, local models; speed, cost, quality, privacy
- [[Backtesting]]: measure a rule on your past sessions before trusting it
- [[Other Agents]]: Codex, Cursor, Copilot, OpenCode
- [[FAQ]]

**Deeper reading (in the repo)**
- [Results: the judge comparison](https://github.com/timainge/good-cop/blob/main/docs/results.md)
- [Model strategy: LLMs vs decision models vs code](https://github.com/timainge/good-cop/blob/main/docs/model-strategy.md)
- [Use cases: when good-cop fits](https://github.com/timainge/good-cop/blob/main/docs/use-cases.md)
- [Design and plan](https://github.com/timainge/good-cop/blob/main/plan.md)
