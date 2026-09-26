from good_cop import redact


def test_patterns(monkeypatch):
    monkeypatch.setenv("MY_SERVICE_TOKEN", "hunter2hunter2")
    text = ("key AKIAABCDEFGHIJKLMNOP gh ghp_" + "a" * 36 + " sk-ant-" + "b" * 30 +
            " auth: Bearer abcdefghijklmnopqrstu and hunter2hunter2 and "
            "-----BEGIN RSA PRIVATE KEY-----\nxyz\n-----END RSA PRIVATE KEY-----")
    out, n = redact.redact(text)
    assert n == 6
    for s in ("AKIA", "ghp_", "sk-ant", "abcdefghijklmnop", "hunter2", "xyz"):
        assert s not in out


def test_no_false_positive():
    out, n = redact.redact("ls -la && git status")
    assert n == 0 and out == "ls -la && git status"
