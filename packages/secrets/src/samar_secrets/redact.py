from __future__ import annotations

import logging
import re

_KEY_RE = re.compile(r"sk-(?:ant|or)-[A-Za-z0-9_\-]{6,}")


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _KEY_RE.sub("sk-redacted", record.msg)
        return True


def install_redaction() -> None:
    logging.getLogger().addFilter(RedactSecretsFilter())
