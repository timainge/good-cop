"""Load config.yaml and rules.yaml with defaults. See plan.md §5, §6."""

from pathlib import Path

import yaml

from good_cop import store

DEFAULTS_DIR = Path(__file__).parent / "defaults"


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def load_config(path: str | Path | None = None) -> dict:
    """Bundled defaults, overlaid by ~/.good-cop/config.yaml or an explicit file."""
    cfg = _load(DEFAULTS_DIR / "config.yaml")
    p = Path(path) if path else store.ROOT / "config.yaml"
    if p.exists():
        cfg = _merge(cfg, _load(p))
    elif path:
        raise FileNotFoundError(p)
    return cfg


def load_rules(path: str | Path | None = None) -> dict:
    """An explicit rules file, else ~/.good-cop/rules.yaml, else the bundled rules."""
    p = Path(path) if path else store.ROOT / "rules.yaml"
    if not p.exists():
        if path:
            raise FileNotFoundError(p)
        p = DEFAULTS_DIR / "rules.yaml"
    rules = _load(p)
    rules.setdefault("enforce", False)
    rules["defaults"] = {"threshold": 0.6, "action": "ask", **(rules.get("defaults") or {})}
    rules.setdefault("rules", [])
    return rules
