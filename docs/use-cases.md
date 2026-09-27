# Use cases for good-cop

*When would you want local, self-refined guardrails on a coding agent rather than (or as well as) an enterprise monitoring system? Written 2026-09-27.*

## What good-cop is, and isn't

good-cop sits in one developer's agent harness. It watches every tool call, keeps a factual ledger of what the session has done (files written, scripts run, hosts contacted, environment switches), and asks a judge whether a call trips a rule. You own the rules, the model choice, the data and the thresholds, and you can backtest a change against your own history before trusting it.

It isn't a security boundary. Hooks run client-side, the user can remove them, and a determined adversary can phrase around any judge. It catches ordinary mistakes and indirection, the kind of thing a careful colleague looking over your shoulder would catch.

## Where it fits

| situation | why good-cop | why not only something else |
|---|---|---|
| **Solo developers and small teams running agents with broad permissions** (`--dangerously-skip-permissions`, auto-accept, long `/loop` runs) | a second opinion on each call without re-enabling every permission prompt; `ask` only on what trips | built-in permission prompts are per tool pattern, not per intent; enterprise tooling isn't there |
| **Agents near real infrastructure** (kube contexts, cloud profiles, terraform workspaces, prod databases) | the ledger records the environment the agent is actually pointed at, and catches indirection like "write deploy.sh, then run it" | allow/deny lists see `./deploy.sh`, not what's inside it or which context is active |
| **Unattended and background runs** (nightly agents, CI agents, scheduled loops) | log-first gives a replayable record of what happened and what would have tripped; enforce once trusted | central monitoring shows *that* a run happened, rarely *why* a call was risky in context |
| **Rule development** ("what does 'touches production' mean for us?") | write the rule as a question, backtest it on months of real sessions, label disagreements, tune | vendor guardrails are fixed categories you can't evaluate on your own data |
| **Privacy-sensitive or air-gapped work** (client code, regulated data, offline) | local judges (Kev, Ollama) with nothing leaving the machine; redaction for cloud judges | SaaS monitoring means shipping transcripts to a third party |
| **Personal habits and project norms** ("don't commit to main", "never touch `migrations/` without a plan", "no `curl \| sh`") | cheap to add, specific to one repo or person, easy to retire | too local and too numerous for an org-wide policy engine |
| **Evaluating agents or judges** | the event log and backtest harness compare models, prompts and thresholds on identical traces | — |
| **Teaching and demos** | shows what an agent actually did, step by step, with reasons | — |

## When you want enterprise monitoring instead (or as well)

- **Compliance and audit obligations.** You need tamper-evident central logs, retention policies and access controls. good-cop's logs are local files the user owns.
- **Many developers, one policy.** Central policy distribution, rollout and reporting are enterprise concerns. good-cop has no fleet management.
- **Adversarial insiders or compromised agents.** Anything client-side can be disabled. Use enforcement the agent can't reach: network egress controls, sandboxed execution, scoped credentials, server-side audit.
- **Cross-tool visibility.** Monitoring that covers every agent, IDE and CI system at the network or identity layer sees more than a hook in one harness.

They complement each other. An organisation might enforce hard boundaries centrally (credentials, egress, sandboxes) while developers use good-cop locally for the soft, contextual, fast-moving rules that central policy can't express, and some rules graduate from local practice into central policy once proven.

## Deciding in practice

Choose good-cop when **most** of these are true:

1. The risk is mistakes, not malice.
2. The rules are contextual ("this command, in this environment, after that edit") rather than categorical.
3. You want to iterate on rules quickly and measure them on your own history.
4. The data should stay on the machine, or at least under your control.
5. A wrong `ask` costs seconds, and a missed catch costs hours, not a breach.

If the risk is malice, or a miss would be a breach, good-cop is at most one layer. Put the hard boundary somewhere the agent can't edit.
