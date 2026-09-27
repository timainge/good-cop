# Contributing

good-cop is an experiment. Issues and small PRs are welcome; please open an issue before large changes.

```sh
uv sync
uv run pytest -q
```

- Read [plan.md](plan.md) (the spec) and [CLAUDE.md](CLAUDE.md) (codebase rules): small flat
  modules, stdlib + `httpx` + `pyyaml`, no provider SDKs, and every hook path fails open.
- Tests never call real model APIs; use the `home` and `fake_llm` fixtures.
- New harness adapters: capture real payloads into `tests/fixtures/<harness>/` first, then write
  the adapter against them (see `src/good_cop/harness.py` and [Harness Research](https://github.com/timainge/good-cop/wiki/Harness-Research)).
- Eval changes: record runs with `--note` and add summaries under `evals/runs/`.
