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


RULESETS_DIR = Path(__file__).parent / "rulesets"


def rulesets() -> dict[str, Path]:
    """Bundled starter rulesets by name."""
    return {p.stem: p for p in sorted(RULESETS_DIR.glob("*.yaml"))}


def _resolve_include(name: str, base: Path) -> Path:
    """A bundled ruleset name, or a path relative to the including file."""
    if name in rulesets():
        return rulesets()[name]
    p = (base.parent / Path(name).expanduser()).resolve()
    if not p.exists():
        raise FileNotFoundError(f"include {name!r}: no bundled ruleset or file {p}")
    return p


def _compose(path: Path, seen: tuple = ()) -> dict:
    """A rules file with its `include:` list expanded. Later files win: rules merge by id (field by
    field, so a local `{id: x, threshold: 0.9}` only retunes x), `defaults` and `handlers` by key."""
    if path in seen:
        raise ValueError(f"include cycle: {' -> '.join(str(p) for p in (*seen, path))}")
    doc = _load(path)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    includes = doc.get("include") or []
    includes = [includes] if isinstance(includes, str) else includes
    layers = []
    for name in includes:
        try:
            layers.append(_compose(_resolve_include(str(name), path), (*seen, path)))
        except Exception as e:  # a bad include must not take every rule down
            store.log_error(f"rules: include {name!r}: {e}")
    layers.append(doc)
    out = {"rules": [], "defaults": {}, "handlers": {}}
    index: dict[str, int] = {}
    for layer in layers:
        for k, v in layer.items():
            if k in ("defaults", "handlers"):
                out[k] = {**out[k], **(v or {})}
            elif k == "rules":
                for r in v or []:
                    if r.get("id") in index:
                        out["rules"][index[r["id"]]] = {**out["rules"][index[r["id"]]], **r}
                    else:
                        index[r.get("id")] = len(out["rules"])
                        out["rules"].append(dict(r))
            elif k != "include":
                out[k] = v
    out["included"] = list(includes)
    return out


def load_rules(path: str | Path | None = None) -> dict:
    """An explicit rules file, else ~/.good-cop/rules.yaml, else the bundled rules; includes expanded."""
    p = Path(path) if path else store.ROOT / "rules.yaml"
    if not p.exists():
        if path:
            raise FileNotFoundError(p)
        p = DEFAULTS_DIR / "rules.yaml"
    rules = _compose(p.resolve())
    rules.setdefault("enforce", False)
    rules["defaults"] = {"threshold": 0.6, "action": "ask", **(rules.get("defaults") or {})}
    rules["rules"] = [r for r in rules["rules"] if not r.get("disabled")]
    for r in rules["rules"]:
        if isinstance(r.get("criteria"), dict):  # YAML reads bare `true:` / `false:` keys as booleans
            r["criteria"] = {str(k).lower() if isinstance(k, bool) else k: v for k, v in r["criteria"].items()}
    return rules
