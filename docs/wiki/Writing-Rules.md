# Writing Rules

Rules live in `~/.good-cop/rules.yaml`. Each rule has an `id`, an optional `when`, an `action` (`log`, `ask` or `deny`) and an optional `threshold`. There are three kinds.

Most people start from a [[Rulesets|Rulesets]] include and add a few rules of their own:

```yaml
include: [solo-dev, infra]          # bundled starter rulesets, or paths relative to this file
rules:
  - {id: prod_target, threshold: 0.95}   # same id as an included rule: only these fields change
  - {id: pipe_to_shell, disabled: true}  # drop an included rule
  - id: my_rule                          # new rules are added after the included ones
    ...
```

`good-cop rules show` prints the effective rules after includes and overrides.

## Scoping: `when`

- `when.tools`: globs for the tool name (`Bash`, `mcp__*`, `Write`). Codex's `apply_patch` also matches `Edit`/`Write`.
- `when.command`: a regex the shell command (or, for other tools, the JSON of the input) must match. Use it to aim a fact at the commands it's about: "the kube context is prod" should only matter for `kubectl`, not for `ls`.

```yaml
- id: kube_prod_context
  when: {tools: [Bash], command: '\b(kubectl|helm)\b'}
  fact: ledger.env.kube_context
  matches: '(?i)prod'
```

## 1. Pattern: a regex, no model
```yaml
- id: destructive_rm
  when: {tools: [Bash]}
  pattern: 'rm\s+-rf\s+(/|~|\$HOME)(\s|$)'
  action: deny
```
Matched against the shell command, or the JSON of the tool input for other tools. For shell commands, patterns also see each simple command with quotes removed and variables substituted, so `r''m -rf ~` and `X=rm; $X -rf ~` match. They skip heredoc bodies that are only written to a file (`cat > x.sh <<EOF … EOF`); that content is checked when it runs, through `resolved.script.head`.

## 2. Fact: a check on recorded state, no model
```yaml
- id: outside_workspace
  fact: resolved.writes[].outside_cwd        # truthy anywhere
- id: prod_context
  fact: ledger.env.kube_context
  matches: '^prod'          # or equals: x, in: [a, b], not_in: [a, b], not_matches: regex
- id: unknown_egress
  fact: resolved.hosts[]
  not_matches: '(^|\.)(github\.com|pypi\.org)$'   # any host off the allowlist trips
```
The rule trips if **any** value at the path meets the condition (so `not_in` / `not_matches` trip on any value outside the list).
`[]` fans out over a list. Useful paths:
- `call.tool`, `call.input.*`
- `resolved.script.path`, `resolved.script.written_this_session`
- `resolved.writes[].path`, `resolved.writes[].outside_cwd`
- `resolved.hosts[]`: hosts in URLs in this call's input (shell commands, WebFetch, MCP arguments; not file contents)
- `resolved.env[]`: inline assignments in a shell command, as `"VAR=value"` (`AWS_PROFILE=prod aws …`; the hook's own environment never sees these)
- `resolved.commands[]`: simple commands whose words differ once quotes are removed and earlier variables substituted (`r''m -rf ~` → `rm -rf ~`). Patterns see these too.
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
- **Write criteria.** They define yes and no, including the near-misses. In our evals they roughly doubled a decision model's F1 at the default threshold. For LLMs (Haiku, gpt-5-mini, qwen2.5-7b) they left F1 about the same and improved recall. Keep the question consistent with its criteria.
- Point at state paths in backticks (`call.input.command`, `ledger.files_written`).

## Thresholds
A question rule trips when the judge's probability ≥ threshold. Precedence: the rule's own `threshold`, then the judge's calibrated `judge.threshold` in config, then `defaults.threshold`. LLMs answer near 0/1; decision models return graded probabilities and need a higher threshold (Jev ~0.85–0.9, Kev ~0.7).

## When a rule trips
`action` decides what the agent sees. To also notify you (Slack, syslog, …), add `on_trip: [handler-name]`. See [[Handlers]].

## Tips
- Put exact things in code (`pattern`, `fact`) and judgement in questions. See the [model strategy](Model-Strategy).
- Scope question rules with `when.tools`: each one adds judge latency to every matching call.
- Measure before enforcing: [[Backtesting]].
