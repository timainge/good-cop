# FAQ

**Is this a security tool?** No. It's a guardrail against ordinary mistakes and indirection. Hooks are client-side and removable, and judges can be wrong or manipulated by content they read. Put hard limits (credentials, egress, sandboxes) somewhere the agent can't reach. See [use cases](Use-Cases).

**Will it slow my agent down?** Pattern and fact rules take a few milliseconds. A model judge adds roughly 0.3 s (Jev), 1 s (Haiku) or 2 s (Kev, local) to each call its rules apply to. Scope rules with `when.tools`.

**What if good-cop breaks?** It fails open: errors are logged and the tool call proceeds.

**Does it send my code anywhere?** Only to the judge you configure, and only the decision state for the pending call: the call, the head of any script it runs, file paths, and snippets of recent output. Secrets are redacted before cloud calls. Local judges (Kev, Ollama) send nothing.

**Why are probabilities so different between judges?** LLMs answer near 0 or 1; decision models like Jev and Kev return graded, calibrated-ish probabilities. That's why `judge.threshold` exists and why backtesting matters.

**Can I use it with a subagent-heavy workflow?** Yes. Claude Code subagent tool calls fire hooks under the parent session with an `agent_id`, and good-cop records them.

**Where's my data?** `~/.good-cop/`, or set `GOOD_COP_HOME`. Session logs may contain tool output, so treat them like shell history.
