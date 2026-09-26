"""Redact secrets from prompt text at the provider boundary. See plan.md §6."""

import os
import re

PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                  # AWS access key id
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),         # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),                            # OpenAI / Anthropic style
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"),                    # Slack
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
]
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.I)
MASK = "[REDACTED]"


def redact(text: str) -> tuple[str, int]:
    """Return (redacted text, number of redactions)."""
    count = 0
    for name, value in os.environ.items():
        if SECRET_ENV.search(name) and len(value) >= 8 and value in text:
            count += text.count(value)
            text = text.replace(value, MASK)
    for pat in PATTERNS:
        text, n = pat.subn(MASK, text)
        count += n
    return text, count
