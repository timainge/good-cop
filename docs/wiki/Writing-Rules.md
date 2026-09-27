# Writing Rules

Rules live in `~/.good-cop/rules.yaml`. Each rule has an `id`, optional `when: {tools: [...]}` (globs such as `mcp__*`), an `action` (`log`, `ask` or `deny`) and an optional `threshold`. There are three kinds.

## 1. Pattern: a regex, no model
```yaml
- id: destructive_rm
  when: {tools: [Bash]}
  pattern: 'rm\s+-rf\s+(/|~|\$HOME)(\s|$)'
  action: deny
```
Matched against the shell command, or the JSON of the tool input for other tools.

## 2. Fact: a check on recorded state, no model
```yaml
- id: outside_workspace
  fact: resolved.writes[].outside_cwd        # truthy anywhere
- id: prod_context
  fact: ledger.env.kube_context
  matches: '^prod'                           # or equals: x, or in: [a, b]
```
`[]` fans out over a list. Useful paths:
- `call.tool`, `call.input.*`
- `resolved.script.path`, `resolved.script.written_this_session`
- `resolved.writes[].path`, `resolved.writes[].outside_cwd`
- `ledger.env.*` (git_branch, kube_context, aws_profile, tf_workspace)
- `ledger.files_written`, `ledger.hosts_contacted`, `ledger.flags.*`

## 3. Question: answered by a judge
```yaml
- id: runs_tests
  when: {tools: [Bash]}
  question: Does the shell command in `call.input.command` execute an automated test suite?
  criteria:
    true: It runs a test runner directly or through a package script (pytest, vitest, npm test, ...).
    false: It only writes, reads, lints, type-checks or builds; writing a test file is not running tests.
```
- All questions that apply to a call go to the judge in **one** request.
- **Write criteria.** They define yes and no, including the near-misses. In our evals they roughly doubled a decision model's F1 at the default threshold and helped the small local LLM, while leaving the strong LLMs about the same. Keep the question consistent with its criteria.
- Point at state paths in backticks (`call.input.command`, `ledger.files_written`).

## Thresholds
A question rule trips when the judge's probability ≥ threshold. Precedence: the rule's own `threshold`, then the judge's calibrated `judge.threshold` in config, then `defaults.threshold`. LLMs answer near 0/1; decision models return graded probabilities and need a higher threshold (Jev ~0.85–0.9, Kev ~0.7).

## Tips
- Put exact things in code (`pattern`, `fact`) and judgement in questions. See the [model strategy](https://github.com/timainge/good-cop/blob/main/docs/model-strategy.md).
- Scope question rules with `when.tools`: each one adds judge latency to every matching call.
- Measure before enforcing: [[Backtesting]].
