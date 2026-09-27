# Security

good-cop is **not a security boundary**. It runs as client-side hooks that the user (or a
sufficiently capable agent) can edit or remove, and its judges can be wrong or talked around.
Use it to catch ordinary mistakes and indirection; put hard limits (credentials, network egress,
sandboxes) somewhere the agent can't reach. See [docs/use-cases.md](docs/use-cases.md).

What good-cop sends where:
- **Local judges** (Ollama, a Kev server on localhost): nothing leaves the machine.
- **Cloud judges** (Anthropic, OpenAI, TypeSafe): the decision state for each tool call (the call,
  resolved script head, file paths, recent tool output snippets). Common secret formats and the
  values of secret-named environment variables are redacted first (`redact: auto`).
- **Session logs** stay in `~/.good-cop/` and may contain tool output. Treat them like shell history.

Please report vulnerabilities privately via GitHub's "Report a vulnerability" (Security tab)
rather than a public issue.
