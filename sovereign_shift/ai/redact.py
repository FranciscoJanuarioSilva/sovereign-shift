"""Strip anything secret-looking before a payload goes to an LLM."""

import re
from typing import Any

SECRET_KEYS = re.compile(r"pass|secret|token|credential|private|user_?data|environment|env_vars|auth|cert", re.I)
ACCOUNT_ID = re.compile(r"(?<!\d)\d{12}(?!\d)")
# a bare ip, but not a cidr (cidrs stay, the reviewer needs 0.0.0.0/0)
HOST_IP = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d./])")
ARN = re.compile(r"arn:aws[\w-]*:[^\s\"']+")


def redact_text(text: str) -> str:
    text = ARN.sub("<arn>", text)
    text = ACCOUNT_ID.sub("<account>", text)
    return HOST_IP.sub("<ip>", text)


def redact(value: Any) -> Any:
    """Return a copy with secret keys dropped and ids/ips masked."""
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if not SECRET_KEYS.search(str(k))}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
