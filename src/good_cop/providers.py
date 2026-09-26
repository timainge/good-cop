"""The one model seam: LLM protocol with anthropic / openai / ollama over httpx. See plan.md §6."""

import os
from typing import Protocol

from good_cop import redact, store


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, *, timeout: float) -> str: ...


def _post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    import httpx  # lazy: keeps hook startup fast when no model call is needed

    r = httpx.post(url, headers=headers, json=body, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"{url} -> {r.status_code}: {r.text[:500]}")
    return r.json()


class Anthropic:
    def __init__(self, cfg: dict):
        self.model = cfg["model"]
        self.base_url = cfg.get("base_url", "https://api.anthropic.com").rstrip("/")
        self.extra = cfg.get("extra") or {}
        self.name = f"anthropic:{self.model}"

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        body = {"model": self.model, "max_tokens": 1024, "system": system,
                "messages": [{"role": "user", "content": user}], **self.extra}
        headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
        data = _post(f"{self.base_url}/v1/messages", headers, body, timeout)
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")


class OpenAI:
    def __init__(self, cfg: dict):
        self.model = cfg["model"]
        self.base_url = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.extra = cfg.get("extra") or {}
        self.name = f"openai:{self.model}"

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        body = {"model": self.model, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                **self.extra}
        key = os.environ.get("OPENAI_API_KEY", "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        data = _post(f"{self.base_url}/chat/completions", headers, body, timeout)
        return data["choices"][0]["message"]["content"] or ""


class Ollama:
    def __init__(self, cfg: dict):
        self.model = cfg["model"]
        self.base_url = cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self.extra = cfg.get("extra") or {}
        self.name = f"ollama:{self.model}"

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        body = {"model": self.model, "stream": False, "format": "json",
                "options": {"temperature": 0, "num_ctx": 16384},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                **self.extra}
        data = _post(f"{self.base_url}/api/chat", {}, body, timeout)
        return data["message"]["content"]


class Redacting:
    """Wraps an LLM and strips secrets from prompts before they leave the machine."""

    def __init__(self, inner: LLM):
        self.inner = inner
        self.name = inner.name

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        user, n = redact.redact(user)
        if n:
            store.log_error(f"redact: {n} secret(s) removed before {self.name}")
        return self.inner.complete(system, user, timeout=timeout)


PROVIDERS = {"anthropic": Anthropic, "openai": OpenAI, "ollama": Ollama}


def make_llm(cfg: dict, redact_setting="auto") -> LLM:
    llm = PROVIDERS[cfg["provider"]](cfg)
    on = cfg["provider"] != "ollama" if redact_setting == "auto" else bool(redact_setting)
    return Redacting(llm) if on else llm
