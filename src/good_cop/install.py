"""Merge / remove good-cop hooks in a harness's hook config (with backup). See plan.md §1, https://github.com/timainge/good-cop/wiki/Harness-Research."""

import json
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

from good_cop import config, store

HOME = Path.home()
# harness -> (default config file, events in that harness's naming, entry layout)
TARGETS = {
    "claude": (HOME / ".claude" / "settings.json",
               ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"], "grouped"),
    "codex": (HOME / ".codex" / "hooks.json",
              ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"], "grouped"),
    "cursor": (HOME / ".cursor" / "hooks.json",
               ["sessionStart", "beforeSubmitPrompt", "preToolUse", "postToolUse", "stop"], "command"),
    "copilot": (HOME / ".copilot" / "hooks" / "good-cop.json",
                ["sessionStart", "userPromptSubmitted", "preToolUse", "postToolUse", "agentStop"], "bash"),
}
TOOL_EVENTS = {"PreToolUse", "PostToolUse"}
SETTINGS = TARGETS["claude"][0]


EPHEMERAL = {"/archive-v": "uvx good-cop", "/pipx/.cache/": "pipx run good-cop"}  # uvx / pipx run envs


def entry_point(argv0: str | None = None) -> str:
    """How hooks should invoke good-cop: this executable's absolute path (uv tool, pipx, a venv), or
    the launcher when running from an ephemeral cache (`uvx`, `pipx run`) that may be pruned."""
    exe = Path(argv0 or sys.argv[0]).resolve()
    if exe.name != "good-cop":
        exe = Path(shutil.which("good-cop") or "good-cop")
    for marker, launcher in EPHEMERAL.items():
        if marker in str(exe):
            return launcher
    return shlex.quote(str(exe))


def hook_command(harness: str = "claude", event: str | None = None) -> str:
    cmd = f"{entry_point()} hook"
    if harness != "claude":
        cmd += f" --harness {harness}"
    if event and TARGETS[harness][2] != "grouped":
        cmd += f" --event {event}"
    return cmd


def is_ours(hook: dict) -> bool:
    cmd = hook.get("command") or hook.get("bash") or ""
    return "good-cop" in cmd and " hook" in cmd


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    shutil.copy(path, path.with_name(f"{path.name}.bak-{int(time.time())}"))
    return json.loads(path.read_text() or "{}")


def _strip(settings: dict) -> dict:
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        kept = []
        for entry in hooks[event]:
            if "hooks" in entry:  # grouped: {"matcher", "hooks": [...]}
                inner = [h for h in entry["hooks"] if not is_ours(h)]
                if inner:
                    kept.append({**entry, "hooks": inner})
            elif not is_ours(entry):
                kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return settings


def _entry(harness: str, event: str) -> dict:
    layout = TARGETS[harness][2]
    cmd = hook_command(harness, event)
    if layout == "grouped":
        group = {"hooks": [{"type": "command", "command": cmd}]}
        return {"matcher": "*", **group} if event in TOOL_EVENTS else group
    if layout == "bash":
        return {"type": "command", "bash": cmd, "timeoutSec": 10}
    return {"command": cmd, "timeout": 10}


def add_includes(path: Path, names: list[str]) -> list[str]:
    """Add rulesets to a rules file's top-level `include: [...]`, keeping the rest of the text."""
    text = path.read_text()
    m = re.search(r"^include:\s*\[(.*?)\]\s*$", text, re.M)
    current = [n.strip().strip("'\"") for n in m.group(1).split(",") if n.strip()] if m else []
    merged = list(dict.fromkeys(current + names))
    line = f"include: [{', '.join(merged)}]"
    text = text[:m.start()] + line + text[m.end():] if m else f"{line}\n{text}"
    path.write_text(text)
    return merged


def install(settings_path: str | None = None, harness: str = "claude", rulesets: list[str] = ()) -> int:
    unknown = [n for n in rulesets if n not in config.rulesets()]
    if unknown:
        print(f"unknown ruleset(s) {unknown}; available: {', '.join(config.rulesets())}")
        return 1
    default, events, layout = TARGETS[harness]
    path = Path(settings_path) if settings_path else default
    settings = _strip(_load(path))
    if layout != "grouped":
        settings.setdefault("version", 1)
    hooks = settings.setdefault("hooks", {})
    for event in events:
        hooks.setdefault(event, []).append(_entry(harness, event))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    store.ROOT.mkdir(parents=True, exist_ok=True)
    for name in ("config.yaml", "rules.yaml"):
        if not (store.ROOT / name).exists():
            shutil.copy(config.DEFAULTS_DIR / name, store.ROOT / name)
    print(f"installed good-cop hooks for {harness} in {path}; config in {store.ROOT}")
    if entry_point() in EPHEMERAL.values():
        print(f"hooks run `{entry_point()} hook`; for faster hooks, `uv tool install good-cop` and re-run install")
    if rulesets:
        print(f"rules include: {', '.join(add_includes(store.ROOT / 'rules.yaml', list(rulesets)))}")
    if harness == "codex":
        print("codex: review and trust the hooks with /hooks (or pass --dangerously-bypass-hook-trust to codex exec)")
    return 0


def uninstall(settings_path: str | None = None, harness: str = "claude") -> int:
    path = Path(settings_path) if settings_path else TARGETS[harness][0]
    if not path.exists():
        return 0
    path.write_text(json.dumps(_strip(_load(path)), indent=2) + "\n")
    print(f"removed good-cop hooks from {path}")
    return 0


def rules_cmd(args) -> int:
    import yaml
    if args.rules_cmd == "list":
        for name, p in config.rulesets().items():
            doc = yaml.safe_load(p.read_text()) or {}
            print(f"{name:<12} {len(doc.get('rules') or []):>2} rules  {doc.get('description', '')}")
        return 0
    path = config.rulesets()[args.ruleset] if args.ruleset else args.rules
    rc = config.load_rules(path)
    kinds = {}
    for r in rc["rules"]:
        kinds[rules_kind(r)] = kinds.get(rules_kind(r), 0) + 1
    print(f"# {len(rc['rules'])} rules ({', '.join(f'{n} {k}' for k, n in kinds.items())})"
          + (f", includes {rc['included']}" if rc.get("included") else ""))
    out = {k: rc[k] for k in ("enforce", "defaults", "handlers", "rules") if rc.get(k) not in (None, {}, [])}
    print(yaml.safe_dump(out, sort_keys=False, width=110, allow_unicode=True))
    return 0


def rules_kind(rule: dict) -> str:
    from good_cop import rules
    return rules.kind(rule)
