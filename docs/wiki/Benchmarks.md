# Benchmarks: good-cop against other setups on public datasets

Two public agent-safety datasets, replayed offline through good-cop and other guards (2026-10-03). Code and the full output: [`evals/benchmarks/`](https://github.com/timainge/good-cop/tree/main/evals/benchmarks), [`evals/runs/benchmarks-2026-10-03.md`](https://github.com/timainge/good-cop/blob/main/evals/runs/benchmarks-2026-10-03.md).

```sh
evals/benchmarks/fetch.sh                                   # datasets + dcg, pinned, into ~/.good-cop/cache
uv run python evals/benchmarks/bench.py redcode|rjudge|devwork [--guard NAME]
uv run python evals/benchmarks/bench.py report
```

**Guards compared:**
- **none**;
- **[destructive_command_guard](https://github.com/Dicklesworthstone/destructive_command_guard)** (dcg 0.15.2, default packs): a fast regex hook for coding agents;
- **good-cop code rules only**: the default `solo-dev`, or all four starter rulesets;
- **good-cop with all rulesets plus a judge**: Jev at t=0.9, Haiku 4.5, gpt-5-mini, or Jev → Haiku.

A case counts as caught when a rule with action `ask` or `deny` trips.

## RedCode-Exec: risky Bash scripts

[RedCode](https://arxiv.org/abs/2411.07781) (NeurIPS 2024) has 600 risky Bash scripts across 20 scenarios. 330 of them, in 11 scenarios, are system risks, which a tool-call guard is for: reading, copying or deleting sensitive files, untrusted downloads, `.bashrc` aliases, killing processes. The rest are buggy or biased code. Each script is one Bash call. The **dev-work** column shows how often the same guard flags 698 ordinary calls from our own Claude Code sessions. That's an upper bound on false alarms, since a few of those flags are real (e.g. `env | grep` printing a key).

| guard | detected: 600 | detected: 330 system-risk | flagged: our dev work |
|---|---|---|---|
| none | 0% | 0% | 0% |
| dcg | 15.0% | 20.3% | 2.9% |
| good-cop code, `solo-dev` | 10.5% | 18.2% | 3.2% |
| good-cop code, all rulesets | 20.7% | 36.7% | 7.4% |
| + Jev 0.9 | 24.3% | 37.9% | 7.6% |
| + Jev → Haiku | 29.3% | 47.6% | 7.6% |
| + gpt-5-mini | 38.5% | 59.4% | 8.9% |
| **+ Haiku 4.5** | **49.7%** | **74.8%** | 11.7% |

**Published baseline:** RedCode evaluated agents, not guards. A GPT-4 ReAct agent given Bash code refuses 24.8% of cases on its own, and 73.2% of attacks succeed (paper, Fig. 7). good-cop's catches would add to whatever the agent refuses itself.

- **The two regex guards catch different things.** dcg catches writes of risky content and `eval` injection; good-cop's code rules catch untrusted installs, risky sites, copying sensitive files and `.bashrc` aliases. Neither catches reads of `/etc/passwd` or `/etc/shadow`, or POSTs of them to a local server (RedCode's targets are system files and `127.0.0.1`).
- **The judges close most of that gap.** Haiku catches 70% of the sensitive-file reads and posts, and 100% of the deletes and `kill -9 sshd`.
- **But more catches cost more flags on ordinary work.** With all rulesets plus Haiku, 11.7% of our dev calls were flagged: mostly `secret_exposure` and `personal_data_export`, plus the `unattended` ruleset's egress and credential rules. The latter are meant for background agents, so an interactive developer on `solo-dev` would see fewer. In enforce mode this would be too noisy; that needs labels (R1/R10) to tune.
- **Jev at 0.9 adds little here.** That threshold was tuned on our contrived rules; on this distribution Jev's probabilities sit below it. The Jev → Haiku cascade only re-asks answers in the 0.5–0.9 band, so it inherits Jev's confident misses.

## R-Judge: judging agent interaction records

[R-Judge](https://arxiv.org/abs/2401.10019) (EMNLP 2024 Findings) has 571 human-labelled multi-turn agent records across 5 categories: Program, Application, Finance, IoT and Web, with 301 unsafe. good-cop judges each tool call as it would live, before it runs. A record counts as flagged if any of its calls trips. The published judges instead read the whole finished trajectory.

| setup | F1 | recall | specificity |
|---|---|---|---|
| random (published) | 51.3 | 50 | 50 |
| flag every record | 69.0 | 100 | 0 |
| GPT-4o, whole trajectory (published) | 74.5 | | |
| Claude-3.5, whole trajectory ([AgentAuditor](https://arxiv.org/abs/2506.00641)) | 77.8 | | |
| GPT-4.1 / DeepSeek-V3, whole trajectory (AgentAuditor) | 81.0 / 83.7 | | |
| **control: Haiku 4.5, whole trajectory, R-Judge's prompts** | 75.5 | 98.3 | 30.7 |
| dcg | 2.0 | 1.0 | 100 |
| good-cop code, all rulesets | 12.1 | 6.6 | 96.3 |
| good-cop + Jev 0.9 | 13.8 | 7.6 | 96.3 |
| good-cop + Jev → Haiku | 40.1 | 26.2 | 94.8 |
| good-cop + gpt-5-mini | 69.0 | 56.8 | 91.1 |
| **good-cop + Haiku 4.5** | **83.6** | 78.7 | **89.3** |
| good-cop + Haiku 4.5 + one generic "could this cause harm" question | **86.1** | 85.0 | 85.9 |
| AgentAuditor (memory-augmented reasoning), best (published) | ~91–96 | | |
| single human annotator (published, accuracy) | 95.7 | | |

- **Per-call judging against rules beats whole-trajectory judging with the same model.** Haiku as R-Judge's own whole-trajectory judge calls almost everything unsafe: F1 75.5, just above the 69.0 from flagging everything. Inside good-cop the same model scores 83.6, at nearly three times the specificity. Narrow, defined questions about one call at a time beat "is this trajectory safe?". **Not on the Program category, though** (68 records closest to coding): good-cop + Haiku 75.4 against the control's 76.1, a tie. The overall gain comes from the non-coding categories.
- **The shipped rulesets carry over beyond coding.** R-Judge is mostly email, payments, smart locks and health records. The `secret_exposure`, `irreversible`, `prod_target` and data rules, asked about MCP-style tool calls, still reach 83.6. One generic harm question adds 2.5 points.
- **Code rules alone barely register here,** since R-Judge's risks are rarely shell commands. That's the case for keeping questions for judgement.
- **Caveats:**
  - 51 records contain no tool call good-cop could see (only the agent's prose), and always count as safe.
  - The published judges are older models. Our like-for-like control is the Haiku whole-trajectory row.
  - Haiku in good-cop gets the history only through `recent` (the last 5 events) and the ledger.
  - Specialised methods such as AgentAuditor and human annotators are still well ahead.

## What this means

- For tool-call safety, the judge matters more than the patterns. Haiku inside good-cop leads every other setup on both datasets.
- Regex guards (dcg, or good-cop's code rules) are fast and quiet, but catch 10–20% of RedCode on their own. They're the floor, not the ceiling.
- These results come from the shipped rulesets, which were not tuned on either dataset. Any tuning on them should hold out a dataset for testing (roadmap R11).
