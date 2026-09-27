from conftest import FakeLLM
from good_cop import providers, rules

JEV_VERCEL = {"provider": "jev", "model": "jev-latest", "base_url": "https://ai-gateway.vercel.sh/typesafe",
              "api_key_env": "AI_GATEWAY_API_KEY"}


def test_jev_request_and_parse(monkeypatch):
    sent = {}

    def post(url, headers, body, timeout, retries=0):
        sent.update(url=url, headers=headers, body=body)
        return {"model": "jev-1.13.0", "answers": {"commit": {"type": "noul", "noul": 0.93},
                                                   "deletes": {"type": "noul", "noul": 0.02}}}

    monkeypatch.setattr(providers, "_post", post)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "vck_test")
    monkeypatch.setenv("SOME_TOKEN", "hunter2hunter2")
    llm = providers.make_llm(JEV_VERCEL)  # cloud -> redacted
    assert llm.name == "jev:jev-latest"
    state = {"call": {"tool": "Bash", "input": {"command": "git commit -m x # hunter2hunter2"}}}
    cfg = {"enforce": False, "defaults": {"threshold": 0.6, "action": "ask"},
           "rules": [{"id": "commit", "question": "Does this create a git commit?"},
                     {"id": "deletes", "question": "Does this delete files?"}]}
    d = rules.evaluate(cfg, state, llm)
    assert sent["url"] == "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
    assert sent["headers"]["Authorization"] == "Bearer vck_test"
    assert sent["body"]["questions"]["commit"] == {"type": "noul", "instructions": "Does this create a git commit?"}
    assert "hunter2" not in str(sent["body"]["state"])
    assert d["results"]["commit"]["tripped"] and not d["results"]["deletes"]["tripped"]
    assert d["provider"] == "jev:jev-latest" and d["error"] is None


def test_text_providers_have_no_decide():
    assert not hasattr(providers.make_llm({"provider": "anthropic", "model": "m"}), "decide")
    assert not hasattr(FakeLLM(), "decide")


def test_post_retries_on_429(monkeypatch):
    import httpx
    codes = iter([429, 429, 200])
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(next(codes), json={"ok": 1}, headers={"retry-after": "0"}))
    assert providers._post("https://x", {}, {}, 1, retries=2) == {"ok": 1}
    codes = iter([429, 429])
    import pytest
    with pytest.raises(RuntimeError, match="429"):
        providers._post("https://x", {}, {}, 1, retries=1)
