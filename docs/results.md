# Judge comparison: speed, cost, quality, privacy

*Backtests run 2026-09-27 on our own Claude Code transcripts. Anecdotal: one person's sessions, 150 tool calls, contrived rules, and between 2 and 23 positive examples per rule. Treat differences of a few points as noise. Raw run data: [evals/runs/](../evals/runs/); rerun with [evals/run-comparison.sh](../evals/run-comparison.sh), tabulate with [evals/compare.py](../evals/compare.py).*

## Setup

- **Data.** 50 Claude Code transcripts imported with `good-cop import` (~9,700 events). The fixed sample is the first 30 applicable tool calls from each of 5 sessions: 150 calls, mostly Bash, plus Write/Edit and web tools. The state averages 1,738 tokens (max ~4.4k with the LLM prompt).
- **Rules.** Five harmless yes/no questions whose correct answer can be computed in code ([examples/contrived/](../examples/contrived/)): does this call edit Markdown, run tests, create a git commit, run a script written earlier in the session, or access the web? Contrived so we'd get positives from ordinary sessions, and so ground truth is checkable.
- **Judges.** Same states, same questions, one request per tool call with all applicable questions batched.

| judge | where it runs | how it answers |
|---|---|---|
| Claude Haiku 4.5 | Anthropic API | JSON of probabilities from a prompt |
| gpt-5-mini (minimal reasoning) | OpenAI API | same prompt, JSON mode |
| qwen2.5:7b-instruct | Ollama on an M5 MacBook (24 GB) | same prompt, JSON format |
| Kev-4B (bf16, MLX) | local server on the same M5 | native yes/no ("noul") decisions over Jev's API |
| Jev | TypeSafe via Vercel AI Gateway | native yes/no decisions |

## Quality

Accuracy per rule; (precision / recall) in brackets; the number of positives in the sample is shown next to each rule name.

| judge | edits_markdown (6+) | runs_tests (17+) | git_commit (5+) | runs_session_script (2+) | web_access (23+) | mean acc | mean recall | mean F1 |
|---|---|---|---|---|---|---|---|---|
| Haiku 4.5 (3 runs) | 1.00 (1.00/1.00) | 0.93 (0.73/0.94) | 0.99–1.00 | 0.98–0.99 | 1.00 (1.00/1.00) | **0.980–0.982** | **0.99** | **0.88–0.91** |
| gpt-5-mini | 0.93 (0.83/0.83) | 0.95 (0.93/0.77) | 0.99 (0.83/1.00) | 0.86 (0.12/1.00) | 0.99 (0.96/1.00) | 0.945 | 0.92 | 0.76 |
| qwen2.5-7b (Ollama) | 0.93 (1.00/0.67) | 0.95 (0.93/0.77) | 0.97 (0.62/1.00) | 0.98 (0.50/0.50) | 0.95 (1.00/0.74) | 0.956 | 0.73 | 0.75 |
| Kev-4B (local) | 0.93 (0.83/0.83) | 0.91 (0.67/0.94) | 0.93 (0.42/1.00) | 0.93 (0.22/1.00) | 0.99 (0.96/1.00) | 0.939 | 0.95 | 0.71 |
| Jev | 149 of 150 calls rate-limited (429), so no score; see [Jev](#jev) | | | | | | | |

What it shows:

- **Haiku is the best judge here and it's stable.** Three runs on identical inputs differed by at most one call per rule.
- **Kev-4B and qwen2.5-7b fail in opposite directions.** Kev catches nearly everything (recall 0.95) but over-flags: its probabilities are flatter, and its false positives sit at p 0.5–0.77. A per-rule threshold around 0.8 would remove most of them (see [plan.md](../plan.md#local-decision-models-review-2026-09-27)). qwen misses a quarter of positives. For a guardrail, a miss costs more than a false alarm, so Kev is the better local judge despite the lower mean accuracy.
- **gpt-5-mini over-calls "runs a session script"** (precision 0.12) and under-calls tests. Its p95 latency is the tightest of the cloud judges.
- **Ground truth was the weakest link.** Two rounds of "judge errors" turned out to be label errors, and the judges were right both times:
  - The labeller missed Bash-heredoc-written scripts and `cd dir && ./x.sh`.
  - It missed `npm run check`, which runs `npm test` in that repo.

  After fixing the labeller, Haiku's `runs_tests` precision went from 0.41 to 0.73. The remaining disagreements are mostly genuine judgement calls (lint vs. test).

## Speed

Judge latency per tool call in backtest (all questions batched):

| judge | p50 | p95 | notes |
|---|---|---|---|
| gpt-5-mini | 1.0 s | 1.9 s | most consistent |
| Haiku 4.5 | 1.1 s | 3.6–4.0 s | live hook end to end: p50 1.7 s, p95 2.6 s (includes Python start-up and ledger sync) |
| Kev-4B local | 2.0 s | 5.4 s | ~1 s per 1k state tokens uncached on an M5; ~120 ms on an exact repeat (cache) |
| qwen2.5-7b local | 7.9 s | 15.2 s | too slow for live use at this state size |
| Jev | 0.75–1.0 s per successful call | – | TypeSafe advertises 70–500 ms; our calls include the Vercel hop, and most were rate-limited |

Live mode's judge timeout is 3 s and the whole hook's budget is 5 s. Haiku and gpt-5-mini fit comfortably; Kev fits at p50 but not p95. The honest fix for latency is smaller state and fewer model calls: route crisp rules to code (see [model-strategy.md](model-strategy.md)).

## Cost

Estimated from measured prompt sizes (2,100 input tokens per LLM call; 1,850 for native decision calls, which skip the prompt wrapper), ~60 output tokens for JSON answers, and list prices on 2026-09-27.

| judge | price (input / output per M tokens) | per 1,000 tool calls | notes |
|---|---|---|---|
| Haiku 4.5 | $1.00 / $5.00 | ~$2.40 | prompt caching doesn't apply: Haiku 4.5's minimum cacheable prefix is 4,096 tokens and the state changes every call |
| gpt-5-mini | $0.25 / $2.00 | ~$0.85 | includes ~100 tokens of minimal reasoning (estimate) |
| Jev | $0.042 / free | ~$0.08 | ~30× cheaper than Haiku |
| Kev-4B, qwen2.5-7b | local | $0 marginal | hardware already owned; one-off 9.3 GB (Kev) / 4.7 GB (qwen) download |

For scale, our 50 imported sessions contain ~3,200 Bash calls alone. A heavy agent user can make 1,000+ tool calls a day, so an always-on Haiku judge costs dollars per developer per day, Jev costs cents, and local costs nothing but latency and memory (~9 GB resident for Kev-4B).

## Privacy

| judge | what leaves the machine | mitigations |
|---|---|---|
| Haiku, gpt-5-mini | the decision state: the command, resolved script heads, file paths, recent tool output snippets | good-cop redacts common secret formats and secret-named env var values before sending (on by default for cloud providers); provider retention and training policies apply |
| Jev via Vercel | the same state, through two parties (Vercel, then TypeSafe) | same redaction; Vercel lists Jev as no-training but not zero-data-retention |
| Kev, Ollama | nothing | redaction off by default for localhost endpoints |

## Jev

Jev was the reason for building the `jev` provider, and it's still unmeasured:

- **First attempt (2026-09-27 ~10:30 AEST, US Friday evening):** 89 of 90 calls returned `429 rate_limit_exceeded` ("the upstream provider is currently experiencing high demand"), even with retries.
- **US-night retest (2026-09-27 ~13:00–14:30 AEST, Saturday 8–9:30 pm PT):**
  - A probe got 1 of 3 through; ten minutes later 0 of 10.
  - A fixed-sample run with 10 retries per call was still in 429 backoff after 80 minutes, so I stopped it (it saves nothing until it finishes).
  - A second pass with 2 retries per call got **1 of 150** through. Recorded in [evals/runs/](../evals/runs/) as `jev via vercel (2 retries; errors = 429s)`.
- **Sunday retest (2026-09-28 06:26 AEST, Sunday 1:30 pm PT):** probes got 0 of 16 through: fifteen 429s and one 403. The US was awake, so this wasn't the overnight test.
- **The calls that did succeed** answered in ~0.8 s through Vercel and were correct.

TypeSafe's docs say rate limits are "adjusting dynamically" while they add capacity. Until that settles, **Kev-4B is the practical Jev-shaped option**: same API, runs locally, 0.94 mean accuracy with 0.95 recall. It's slower than Jev's advertised latency, but it's available.

## Takeaways

1. **For live use today:** Haiku 4.5 is the most accurate judge; gpt-5-mini is cheaper and has tighter latency with somewhat lower quality.
2. **For private or offline use:** Kev-4B. Tune thresholds per rule with backtest and labels first.
3. **For cost at scale:** Jev, once its capacity is reliable. Retest before relying on it.
4. **For every rule:** move exact facts into code, and keep models for judgement. Label carefully; our labels were wrong more often than our best judge.
