"""The one model seam: LLM protocol with anthropic / openai / ollama / jev over httpx. See plan.md §6."""

import os
import time
from typing import Protocol
from urllib.parse import urlparse

from good_cop import redact, store


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, *, timeout: float) -> str: ...


RETRYABLE = {429, 500, 502, 503, 504}


def _post(url: str, headers: dict, body: dict, timeout: float, retries: int = 0) -> dict:
    """POST JSON. Retries 429/5xx with backoff (honouring retry-after); live mode uses retries=0."""
    import httpx  # lazy: keeps hook startup fast when no model call is needed

    for attempt in range(retries + 1):
        r = httpx.post(url, headers=headers, json=body, timeout=timeout)
        if r.status_code not in RETRYABLE or attempt == retries:
            break
        try:
            wait = float(r.headers.get("retry-after", ""))
        except ValueError:
            wait = 2.0 ** attempt
        time.sleep(min(wait, 30.0))
    if r.status_code >= 400:
        raise RuntimeError(f"{url} -> {r.status_code}: {r.text[:500]}")
    return r.json()


class Anthropic:
    def __init__(self, cfg: dict):
        self.model = cfg["model"]
        self.base_url = cfg.get("base_url", "https://api.anthropic.com").rstrip("/")
        self.extra = cfg.get("extra") or {}
        self.retries = cfg.get("retries", 0)
        self.name = f"anthropic:{self.model}"

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        body = {"model": self.model, "max_tokens": 1024, "system": system,
                "messages": [{"role": "user", "content": user}], **self.extra}
        headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
        data = _post(f"{self.base_url}/v1/messages", headers, body, timeout, self.retries)
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")


class OpenAI:
    def __init__(self, cfg: dict):
        self.model = cfg["model"]
        self.base_url = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.extra = cfg.get("extra") or {}
        self.retries = cfg.get("retries", 0)
        self.name = f"openai:{self.model}"

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        body = {"model": self.model, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                **self.extra}
        key = os.environ.get("OPENAI_API_KEY", "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        data = _post(f"{self.base_url}/chat/completions", headers, body, timeout, self.retries)
        return data["choices"][0]["message"]["content"] or ""


class Ollama:
    def __init__(self, cfg: dict):
        self.model = cfg["model"]
        self.base_url = cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self.extra = cfg.get("extra") or {}
        self.retries = cfg.get("retries", 0)
        self.name = f"ollama:{self.model}"

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        body = {"model": self.model, "stream": False, "format": "json",
                "options": {"temperature": 0, "num_ctx": 16384},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                **self.extra}
        data = _post(f"{self.base_url}/api/chat", {}, body, timeout, self.retries)
        return data["message"]["content"]


class Jev:
    """TypeSafe's System One model. Not a text model: it answers the rule questions directly as
    `noul` (yes/no) probabilities, so the judge calls `decide` instead of `complete`.
    Works against TypeSafe (https://api.typesafe.ai, TYPESAFE_API_KEY), Vercel AI Gateway
    (https://ai-gateway.vercel.sh/typesafe, AI_GATEWAY_API_KEY), or any local server with the
    same API, e.g. Kev (http://127.0.0.1:8009, no key)."""

    def __init__(self, cfg: dict):
        self.model = cfg.get("model", "jev-latest")
        self.base_url = cfg.get("base_url", "https://api.typesafe.ai").rstrip("/")
        self.key_env = cfg.get("api_key_env", "TYPESAFE_API_KEY")
        self.retries = cfg.get("retries", 0)
        self.name = f"jev:{self.model}"

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        raise NotImplementedError("jev answers typed questions only; use it as the judge, not the summariser")

    def decide(self, state: dict, questions: dict[str, str], *, timeout: float) -> dict[str, float]:
        body = {"model": self.model, "state": state,
                "questions": {rid: {"type": "noul", "instructions": q.strip()} for rid, q in questions.items()}}
        key = os.environ.get(self.key_env)
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        data = _post(f"{self.base_url}/v1/systemone", headers, body, timeout, self.retries)
        return {rid: float(a["noul"]) for rid, a in data["answers"].items() if "noul" in a}


class Redacting:
    """Wraps an LLM and strips secrets from prompts before they leave the machine."""

    def __init__(self, inner: LLM):
        self.inner = inner
        self.name = inner.name
        if hasattr(inner, "decide"):
            self.decide = self._decide

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        user, n = redact.redact(user)
        if n:
            store.log_error(f"redact: {n} secret(s) removed before {self.name}")
        return self.inner.complete(system, user, timeout=timeout)

    def _decide(self, state: dict, questions: dict[str, str], *, timeout: float) -> dict[str, float]:
        state, n = redact.redact_obj(state)
        if n:
            store.log_error(f"redact: {n} secret(s) removed before {self.name}")
        return self.inner.decide(state, questions, timeout=timeout)


PROVIDERS = {"anthropic": Anthropic, "openai": OpenAI, "ollama": Ollama, "jev": Jev}


def is_local(cfg: dict) -> bool:
    if cfg["provider"] == "ollama" and not cfg.get("base_url"):
        return True
    host = urlparse(cfg.get("base_url") or "").hostname or ""
    return host in ("localhost", "127.0.0.1", "::1")


def make_llm(cfg: dict, redact_setting="auto") -> LLM:
    """Build a provider. Redaction `auto` is on unless the endpoint is on this machine."""
    llm = PROVIDERS[cfg["provider"]](cfg)
    on = not is_local(cfg) if redact_setting == "auto" else bool(redact_setting)
    return Redacting(llm) if on else llm
