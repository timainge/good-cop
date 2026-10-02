# Rulesets

good-cop ships four starter rulesets. Your `~/.good-cop/rules.yaml` includes `solo-dev` by default. Add others for the work your agent does near real systems:

```sh
good-cop rules list                    # what's bundled
good-cop install --ruleset infra       # adds it to rules.yaml's `include:` (keeps the rest of the file)
good-cop rules show                    # the effective rules after includes and your overrides
good-cop rules show --ruleset data     # one ruleset on its own
```

```yaml
# ~/.good-cop/rules.yaml
include: [solo-dev, infra]               # later includes win; rules merge by id
rules:
  - {id: prod_target, threshold: 0.95}   # retune an included rule: only these fields change
  - {id: package_install, disabled: true}
```

| ruleset | for | rules |
|---|---|---|
| `solo-dev` (default) | individual developers whose agent has broad permissions | `destructive_rm`, `destructive_script`, `force_push_main`, `pipe_to_shell`, `tamper_write`, `tamper_command`, `inline_prod_env`, `outside_workspace`, `runs_session_script` (log), and questions `secret_exposure`, `irreversible`, `prod_target` |
| `infra` | agents near kubernetes, terraform and cloud CLIs | `kube_prod_context`, `aws_prod_profile` (facts, scoped to the tools they're about), `prod_flag`, `prod_in_script`, `terraform_apply_destroy`, `cloud_delete`, `iam_change`, and a stricter `prod_target` question |
| `data` | agents near databases and datasets | `sql_drop_truncate`, `delete_without_where`, and questions `bulk_data_change`, `migration_non_local`, `personal_data_export` |
| `unattended` | background agents, CI, `claude -p`, `/loop` | `defaults.action: deny`; a Slack `webhook` handler on trips (set `SLACK_WEBHOOK_URL`); `unknown_egress` (hosts off an allowlist), `package_install`, `credential_read` |

Design rules for the bundled sets:
- Anything exact is a `pattern` or `fact` (no model call, immune to prompt injection; see [[Red-team]]).
- Every question has `criteria` (what yes and no mean, including the near-misses) and a `when.tools` scope.
- Facts about the environment are scoped with `when.command`, so "the kube context is prod" only matters for `kubectl`/`helm` calls.

**Why `unattended` denies:** verified with Claude Code 2.1.287, a hook's `ask` in `claude -p` is treated as a denial, even with `--permission-mode bypassPermissions` or `--dangerously-skip-permissions`. Saying `deny` makes that explicit and gives the same result on harnesses without `ask`. Enforcement still needs `enforce: true` in your own file; no ruleset turns it on.

## Measured so far

**All rules are unmeasured: none has labelled positives yet.** The table below is a first pass on 698 real tool calls from 46 of our own Claude Code sessions, with all four rulesets loaded. It shows how often each rule trips, and how often Jev (t=0.9) and Haiku 4.5 agree, not whether they're right. The sessions are ordinary development work, so most of the dangerous-operation rules never had anything to fire on.

| rule | kind | evaluated | trips: Jev 0.9 | trips: Haiku | agree |
|---|---|---|---|---|---|
| outside_workspace | fact | 698 | 15 | 15 | 698/698 |
| runs_session_script | fact | 698 | 3 | 3 | 698/698 |
| tamper_write / tamper_command | fact / pattern | 698 / 508 | 1 / 1 | 1 / 1 | all |
| secret_exposure | question | 621 | 0 | **46** | 575/621 |
| irreversible | question | 508 | 0 | 6 | 502/508 |
| personal_data_export | question | 508 | 0 | **15** | 493/508 |
| prod_target, bulk_data_change, migration_non_local | question | 508 | 0 | 0 | all |
| sql_drop_truncate | pattern | 508 | 1 | 1 | all |
| unknown_egress | fact | 518 | 18 | 18 | all |
| credential_read | pattern | 611 | 12 | 12 | all |
| package_install | pattern | 508 | 5 | 5 | all |
| destructive_rm, destructive_script, force_push_main, pipe_to_shell, inline_prod_env, prod_flag, prod_in_script, terraform_apply_destroy, cloud_delete, iam_change, delete_without_where | code | 107–698 | 0 | 0 | all |

Judge latency p50 / p95: Jev 0.27 s / 1.3 s, Haiku 1.3 s / 5.7 s. Reproduce with [`evals/rulesets/run.sh`](https://github.com/timainge/good-cop/blob/main/evals/rulesets/run.sh), then label with `good-cop review --from-backtest latest`.

What the first pass already showed:
- **The judges disagree on the fuzzy rules.** Haiku flags `secret_exposure` on reads of `.env.example` and `gh auth status`, and `personal_data_export` on local queries over an iMessage database. Jev at 0.9 flags none of them. Which one is right is exactly what labels will settle. Until then, `solo-dev` keeps both rules, and the default judge stays Haiku (see below).
- **Written heredocs were the main source of code-rule false positives.** Patterns matched `npm install`, `DROP TABLE` or URLs inside `cat > README.md <<EOF … EOF`. Patterns and hosts now skip heredoc bodies that are only written to a file, which cut `credential_read` from 22 to 12 trips and `unknown_egress` from 27 to 18. Content that is written and then *run* is checked through `resolved.script`.
- **`credential_read` still fires on mentions**, such as `printf '.env' >> .gitignore` and `grep '\.env'`. It's a pattern, so it can't tell a read from a mention. Keep it for unattended agents, where a mention is cheap to review.

**Default judge:** still Haiku 4.5. Earlier contrived-rule results favour Jev at ~0.9, but on these safety rules the two judges diverge and there are no labels yet to say which is right. That will be revisited after dogfooding (roadmap R0/R2).
