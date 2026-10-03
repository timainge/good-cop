# Changelog

good-cop is experimental: `0.x` versions may change rules, config and file formats.

## 0.2.0 (unreleased)

- **`good-cop review`**: label tool calls in value order (judge disagreements, tripped, near-misses,
  a sample of negatives), one key per call; suggests a threshold per rule and judge on exit.
- **Starter rulesets** `solo-dev` (default), `infra`, `data`, `unattended`, composed with
  `include:` in `rules.yaml` (rules merge by id; `disabled: true` drops one). `good-cop install
  --ruleset X`, `good-cop rules list|show`.
- `secret_print` (pattern: unmasked env/printenv, `echo $KEY`, `cat .env` / credentials, token commands) and a sharper `secret_exposure` rubric (value revealed vs. presence checked).
- New default rules: `tamper_write` / `tamper_command` (edits to good-cop's or the harness's hook
  config), `inline_prod_env` (`AWS_PROFILE=prod aws …`), `destructive_script` (rm -rf ~ or curl|sh
  inside a script being run), `force_push_main`, `pipe_to_shell`, `runs_session_script` (log).
- Rules: per-judge thresholds (`threshold: {jev:jev-latest: 0.5, anthropic: 0.7, default: 0.8}`); `when.command` regex scoping; fact conditions `not_in` / `not_matches`; state gains
  `resolved.hosts`, `resolved.env` and `resolved.commands` (quotes removed, variables substituted,
  so `r''m -rf ~` and `X=rm; $X -rf ~` match patterns). Patterns ignore heredoc bodies that are only
  written to a file.
- **Per-rule cascades**: named `judges:` in config, `cascade: [fast, strong]`, `band`,
  `ask_when_unsure`. One request per judge per call. Backtest reports escalations and added latency.
- **Handler types** `webhook` (templated body, `${ENV}` in url/headers) and `file`; `retries` with
  backoff and `max_per_minute` for every type.
- **Red-team suite** (`evals/redteam/`): 17 adversarial scenarios; the code-only part runs in CI.
- Fixes: rule `criteria` written as bare YAML `true:` / `false:` keys were never sent to text-LLM
  judges (Jev was unaffected). `sed -i` targets now count as writes. Context switches inside a
  script (`kubectl config use-context` in `./x.sh`) now re-probe the environment.
- Packaging: single-sourced version, `uvx` / `pipx run` installs write a launcher-based hook command,
  CI smoke-tests the wheel, and a tag-triggered release workflow publishes with PyPI trusted publishing.

## 0.1.0 (2026-09-28)

First public version: hooks for Claude Code and Codex, event log and ledger, pattern / fact /
question rules, Anthropic / OpenAI / Ollama / Jev judges, backtesting and labels, optional summary,
enforcement, handlers (command type).
