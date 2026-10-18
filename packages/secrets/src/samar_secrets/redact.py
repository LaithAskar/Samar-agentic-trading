from __future__ import annotations

import logging
import re

_KEY_RE = re.compile(
    r"(sk-(?:ant|or|nous)-[A-Za-z0-9_\-]{6,}"
    r"|sk-[A-Za-z0-9_\-]{20,}"
    r"|pub-[A-Za-z0-9]{12,})"
)


def _replace(match: re.Match[str]) -> str:
    return "pub-redacted" if match.group(0).startswith("pub-") else "sk-redacted"


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _KEY_RE.sub(_replace, record.msg)
        return True


def install_redaction() -> None:
    logging.getLogger().addFilter(RedactSecretsFilter())
