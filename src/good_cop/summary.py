"""Optional rolling summary: trigger, detached worker, prompt + validation. See plan.md §4."""

import json
import os
import subprocess
import sys
import time
import traceback

from good_cop import config, context, judge, store

SYSTEM = """You maintain a short rolling summary of an AI coding agent's session.
You receive the previous summary (may be null), new events since then, and a ledger of
deterministic facts. UPDATE the summary; do not rewrite it from scratch. Do not restate
ledger facts (files, commands, environment); focus on intent. Keep it under 400 tokens.
Respond with only a JSON object:
{"goal": str, "current_task": str, "next_intent": str, "notable": [up to 10 short strings]}"""

CHUNK = 40
STALE_LOCK_S = 300


def validate(data: dict) -> dict:
    out = {}
    for k in ("goal", "current_task", "next_intent"):
        if not isinstance(data.get(k), str):
            raise ValueError(f"summary field {k!r} missing or not a string")
        out[k] = data[k][:500]
    notable = data.get("notable", [])
    if not isinstance(notable, list):
        raise ValueError("summary field 'notable' is not a list")
    out["notable"] = [str(n)[:200] for n in notable][:10]
    return out


def update(llm, previous: dict | None, events: list[dict], ledger: dict, timeout: float) -> dict:
    """One summariser step over `events`. Raises on invalid output; caller keeps the old summary."""
    prev = {k: v for k, v in previous.items() if k != "last_event_seq"} if previous else None
    view = {k: v for k, v in ledger.items() if k not in ("last_event_seq", "files_written")}
    user = json.dumps({"previous_summary": prev, "new_events": [context.compact(e) for e in events],
                       "ledger": view}, indent=1, default=str)
    data = judge.extract_json(llm.complete(SYSTEM, user, timeout=timeout))
    return {**validate(data), "last_event_seq": events[-1]["seq"]}


def summary_path(session_id: str):
    return store.session_dir(session_id) / "summary.json"


def lock_path(session_id: str):
    return store.session_dir(session_id) / "summarise.lock"


def lock_active(session_id: str) -> bool:
    p = lock_path(session_id)
    try:
        if time.time() - p.stat().st_mtime > STALE_LOCK_S:
            p.unlink(missing_ok=True)
            return False
        return True
    except FileNotFoundError:
        return False


def maybe_spawn(session_id: str, ledger: dict, cfg: dict) -> bool:
    scfg = cfg.get("summary") or {}
    if not scfg.get("enabled"):
        return False
    done = (store.read_json(summary_path(session_id)) or {}).get("last_event_seq", 0)
    if ledger["last_event_seq"] - done < scfg.get("every", 8) or lock_active(session_id):
        return False
    subprocess.Popen([sys.executable, "-m", "good_cop.cli", "summarise", session_id],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return True


def worker(session_id: str) -> int:
    from good_cop import ledger as ledger_mod, providers

    lock_active(session_id)  # clears a stale lock
    try:
        fd = os.open(lock_path(session_id), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return 0
    try:
        os.write(fd, str(os.getpid()).encode())
        cfg = config.load_config()
        scfg = cfg["summary"]
        llm = providers.make_llm(scfg, cfg.get("redact", "auto"))
        while True:
            events = store.read_events(session_id)
            current = store.read_json(summary_path(session_id))
            done = (current or {}).get("last_event_seq", 0)
            new = [e for e in events if e["seq"] > done]
            if not new:
                break
            chunk = new[:CHUNK]
            ledger = ledger_mod.rebuild([e for e in events if e["seq"] <= chunk[-1]["seq"]])
            try:
                summary = update(llm, current, chunk, ledger, scfg.get("timeout", 120))
            except Exception:
                store.log_error(f"summarise {session_id}:\n{traceback.format_exc()}")
                break
            store.write_json_atomic(summary_path(session_id), summary)
    finally:
        os.close(fd)
        lock_path(session_id).unlink(missing_ok=True)
    return 0
