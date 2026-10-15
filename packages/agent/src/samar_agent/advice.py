from __future__ import annotations

import re

_ADVICE = re.compile(
    r"\b(you should buy|you should sell|i recommend buying|i recommend selling|guaranteed return)\b",
    re.IGNORECASE,
)
_REPLACEMENT = "I can show a simulated result. I cannot tell you what to buy or sell."


def scrub_advice(text: str) -> str:
    return _ADVICE.sub(_REPLACEMENT, text)


def contains_advice(text: str) -> bool:
    return _ADVICE.search(text) is not None
