"""Merge / remove good-cop hooks in ~/.claude/settings.json (with backup). See plan.md §1."""

import json
import shlex
import shutil
import sys
import time
from pathlib import Path

from good_cop import config, store

SETTINGS = Path.home() / ".claude" / "settings.json"
EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]
TOOL_EVENTS = {"PreToolUse", "PostToolUse"}


def hook_command() -> str:
    exe = Path(sys.argv[0]).resolve()
    if exe.name != "good-cop":
        exe = Path(shutil.which("good-cop") or "good-cop")
    return f"{shlex.quote(str(exe))} hook"


def is_ours(hook: dict) -> bool:
    cmd = hook.get("command", "")
    return "good-cop" in cmd and cmd.endswith(" hook")


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    shutil.copy(path, path.with_name(f"{path.name}.bak-{int(time.time())}"))
    return json.loads(path.read_text() or "{}")


def _strip(settings: dict) -> dict:
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if not is_ours(h)]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return settings


def install(settings_path: str | None = None) -> int:
    path = Path(settings_path) if settings_path else SETTINGS
    settings = _strip(_load(path))
    hook = {"type": "command", "command": hook_command()}
    hooks = settings.setdefault("hooks", {})
    for event in EVENTS:
        group = {"matcher": "*", "hooks": [hook]} if event in TOOL_EVENTS else {"hooks": [hook]}
        hooks.setdefault(event, []).append(group)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    store.ROOT.mkdir(parents=True, exist_ok=True)
    for name in ("config.yaml", "rules.yaml"):
        if not (store.ROOT / name).exists():
            shutil.copy(config.DEFAULTS_DIR / name, store.ROOT / name)
    print(f"installed good-cop hooks in {path}; config in {store.ROOT}")
    return 0


def uninstall(settings_path: str | None = None) -> int:
    path = Path(settings_path) if settings_path else SETTINGS
    if not path.exists():
        return 0
    path.write_text(json.dumps(_strip(_load(path)), indent=2) + "\n")
    print(f"removed good-cop hooks from {path}")
    return 0
