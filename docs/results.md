# Judge comparison: speed, cost, quality, privacy

*Backtests run 2026-09-27/28 on our own Claude Code transcripts. Anecdotal: one person's sessions, 150 tool calls, contrived rules, and between 2 and 23 positive examples per rule. Treat differences of a few points as noise. Raw run data: [evals/runs/](../evals/runs/); rerun with [evals/run-comparison.sh](../evals/run-comparison.sh), tabulate with [evals/compare.py](../evals/compare.py).*

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
| Jev (jev-1.13.0) | TypeSafe API direct (and via Vercel AI Gateway) | native yes/no decisions |

## Quality

Accuracy per rule; (precision / recall) in brackets; the number of positives in the sample is shown next to each rule name.

| judge | edits_markdown (6+) | runs_tests (17+) | git_commit (5+) | runs_session_script (2+) | web_access (23+) | mean acc | mean recall | mean F1 |
|---|---|---|---|---|---|---|---|---|
| Haiku 4.5 (3 runs) | 1.00 (1.00/1.00) | 0.93 (0.73/0.94) | 0.99–1.00 | 0.98–0.99 | 1.00 (1.00/1.00) | **0.980–0.982** | **0.99** | **0.88–0.91** |
| gpt-5-mini | 0.93 (0.83/0.83) | 0.95 (0.93/0.77) | 0.99 (0.83/1.00) | 0.86 (0.12/1.00) | 0.99 (0.96/1.00) | 0.945 | 0.92 | 0.76 |
| qwen2.5-7b (Ollama) | 0.93 (1.00/0.67) | 0.95 (0.93/0.77) | 0.97 (0.62/1.00) | 0.98 (0.50/0.50) | 0.95 (1.00/0.74) | 0.956 | 0.73 | 0.75 |
| Kev-4B (local) | 0.93 (0.83/0.83) | 0.91 (0.67/0.94) | 0.93 (0.42/1.00) | 0.93 (0.22/1.00) | 0.99 (0.96/1.00) | 0.939 | 0.95 | 0.71 |
| Jev, TypeSafe direct (t = 0.5) | 0.97 (0.86/1.00) | 0.87 (0.58/0.88) | 0.98 (0.71/1.00) | 0.88 (0.14/1.00) | 0.98 (0.92/1.00) | 0.936 | 0.98 | 0.73 |
| Jev via Vercel | 149 of 150 calls rate-limited (429), so no score; see [Jev](#jev) | | | | | | | |

What it shows:

- **Haiku is the best judge here and it's stable.** Three runs on identical inputs differed by at most one call per rule.
- **Kev-4B and qwen2.5-7b fail in opposite directions.** Kev catches nearly everything (recall 0.95) but over-flags: its probabilities are flatter, and its false positives sit at p 0.5–0.77. A per-rule threshold around 0.8 would remove most of them (see [plan.md](../plan.md#local-decision-models-review-2026-09-27)). qwen misses a quarter of positives. For a guardrail, a miss costs more than a false alarm, so Kev is the better local judge despite the lower mean accuracy.
- **Jev at the default threshold looks like Kev: it catches nearly everything but over-flags.** Its probabilities are graded rather than near 0/1, so the threshold matters. See [Thresholds](#thresholds): at 0.8–0.9 Jev matches or beats Haiku.
- **gpt-5-mini over-calls "runs a session script" (precision 0.12) and under-calls tests. Its p95 latency is the tightest of the cloud judges.
- **Ground truth was the weakest link.** Two rounds of "judge errors" turned out to be label errors, and the judges were right both times:
  - The labeller missed Bash-heredoc-written scripts and `cd dir && ./x.sh`.
  - It missed `npm run check`, which runs `npm test` in that repo.

  After fixing the labeller, Haiku's `runs_tests` precision went from 0.41 to 0.73. The remaining disagreements are mostly genuine judgement calls (lint vs. test).

## Thresholds

LLM judges answer with near-0/1 probabilities, so the trip threshold barely changes their results. Decision models return graded probabilities, so the threshold is a real tuning knob. Re-scoring saved probabilities costs nothing ([evals/thresholds.py](../evals/thresholds.py)). Cells are mean F1 / mean recall across the five rules:

| judge | t=0.5 | t=0.7 | t=0.8 | t=0.9 |
|---|---|---|---|---|
| Haiku 4.5, fixed sample (53 positives) | 0.90 / 0.99 | 0.90 / 0.99 | 0.90 / 0.99 | 0.85 / 0.85 |
| **Jev, fixed sample** | 0.73 / 0.98 | 0.83 / 0.95 | **0.90 / 0.95** | 0.85 / 0.77 |
| Kev-4B, fixed sample | 0.71 / 0.95 | 0.75 / 0.73 | 0.60 / 0.48 | 0.28 / 0.19 |
| Haiku 4.5, held-out (450 calls, 27 positives) | 0.62 / 1.00 | 0.62 / 1.00 | 0.64 / 1.00 | 0.67 / 0.96 |
| **Jev, held-out** | 0.42 / 0.97 | 0.62 / 0.97 | 0.71 / 0.97 | **0.92 / 0.97** |

- **Jev's best threshold is 0.8–0.9 on both samples,** and there it matches Haiku on the fixed sample and beats it on the held-out one.
- **Why not pick one exact number:** 0.8 was chosen on the fixed sample and then checked on a held-out sample from different sessions. The held-out sample preferred 0.9, and at 0.9 the fixed sample loses recall. With 27–53 positives, **start around 0.85 and tune per rule on your own labels**.
- **Kev behaves differently.** Its best is 0.7, it never reaches Jev's F1, and its recall collapses above that. Thresholds are per model, not portable.
- **Why Haiku scores lower on the held-out sessions:** they contain more judgement calls, such as reading a test config vs. running tests, and scaffolding scripts in a scratch directory.

## Speed

Judge latency per tool call in backtest (all questions batched):

| judge | p50 | p95 | notes |
|---|---|---|---|
| gpt-5-mini | 1.0 s | 1.9 s | most consistent |
| Haiku 4.5 | 1.1 s | 3.6–4.0 s | live hook end to end: p50 1.7 s, p95 2.6 s (includes Python start-up and ledger sync) |
| Kev-4B local | 2.0 s | 5.4 s | ~1 s per 1k state tokens uncached on an M5; ~120 ms on an exact repeat (cache) |
| qwen2.5-7b local | 7.9 s | 15.2 s | too slow for live use at this state size |
| **Jev, TypeSafe direct** | **0.29 s** | **0.35 s** | 150 calls in 11 s with 4 workers; ~1.3 s p95 on the 450-call run (larger states) |
| Jev via Vercel | 0.75–1.0 s per successful call | – | extra hop, and nearly every call was rate-limited |

Live mode's judge timeout is 3 s and the whole hook's budget is 5 s. Jev direct is the only judge fast enough to be unnoticeable per tool call; Haiku and gpt-5-mini fit comfortably; Kev fits at p50 but not p95. The honest fix for latency is smaller state and fewer model calls: route crisp rules to code (see [model-strategy.md](model-strategy.md)).

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
| Jev (direct) | the same state, to TypeSafe | same redaction; TypeSafe says Jev is not trained on customer data; zero data retention is an enterprise option |
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

- **TypeSafe API direct (2026-09-28 ~06:45 AEST, Sunday afternoon PT):** a TypeSafe API key worked first time: **0 errors in 600 calls**, p50 0.29 s. The rate limiting was on the Vercel gateway's upstream allocation, not TypeSafe's own API.

Use Jev directly (`examples/configs/jev-typesafe.yaml`), not through Vercel. Kev-4B remains the option when nothing may leave the machine.

Two behaviours to know:

- **It's cautious on obvious cases.** `git commit -m x` alone scored 0.62–0.69; with the full tool-call state, true commits score higher. This is part of why the threshold matters.
- **Answers vary slightly between identical calls** (±0.04 in our probes). Don't set thresholds on a knife edge.

## Takeaways

1. **For live use:** Jev direct, with a threshold of ~0.85 tuned on your labels. It matches Haiku's quality at ~4× lower latency (0.3 s) and ~30× lower cost.
2. **Without tuning:** Haiku 4.5 is the most accurate out of the box and insensitive to threshold; gpt-5-mini is cheaper, with lower quality.
3. **For private or offline use:** Kev-4B, threshold ~0.7. Expect lower F1.
4. **For every rule:** move exact facts into code, and keep models for judgement. Label carefully; our labels were wrong more often than our best judge.
