from __future__ import annotations

import json
import os

import httpx
from samar_agent.http_model import ANTHROPIC_URL, NOUS_URL, OPENAI_URL, OPENROUTER_URL, ProviderName

from samar_api.live.limits import ALLOWLIST
from samar_api.live.types import OrderIntent

_URLS: dict[ProviderName, str] = {
    "anthropic": ANTHROPIC_URL,
    "openrouter": OPENROUTER_URL,
    "openai": OPENAI_URL,
    "nous": NOUS_URL,
}
_ENV = {
    "anthropic": "SAMAR_ANTHROPIC_URL",
    "openrouter": "SAMAR_OPENROUTER_URL",
    "openai": "SAMAR_OPENAI_URL",
    "nous": "SAMAR_NOUS_URL",
}


class ModelOutputError(ValueError):
    pass


def model_intent(provider: ProviderName, model: str, api_key: str, client: httpx.Client) -> OrderIntent:
    prompt = (
        "Reply with one JSON object and no markdown. "
        "Keys are symbol, side, quantity, limit_price, reason. "
        "side is BUY or SELL. quantity is a whole number of shares. "
        f"Symbols must be one of {', '.join(sorted(ALLOWLIST))}. "
        "No options, crypto, shorts, or margin."
    )
    url = os.environ.get(_ENV[provider], _URLS[provider])
    if provider == "anthropic":
        response = client.post(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 300,
                "system": prompt,
                "messages": [{"role": "user", "content": "One order ticket."}],
            },
        )
    else:
        response = client.post(
            url,
            headers={"authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "One order ticket."},
                ],
            },
        )
    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ModelOutputError("model output invalid") from exc
    return parse_intent(_message_text(provider, response.json()), model)


def parse_intent(text: str, model: str) -> OrderIntent:
    raw = text.strip()
    if raw.startswith("```"):
        lines = [line for line in raw.splitlines() if not line.startswith("```")]
        raw = "\n".join(lines).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelOutputError("model output invalid") from exc
    if not isinstance(payload, dict):
        raise ModelOutputError("model output invalid")
    data = {key: value for key, value in payload.items() if isinstance(key, str) and key != "model"}
    data["model"] = model
    try:
        return OrderIntent.model_validate(data)
    except ValueError as exc:
        raise ModelOutputError("model output invalid") from exc


def _message_text(provider: ProviderName, body: object) -> str:
    if not isinstance(body, dict):
        raise ModelOutputError("model output invalid")
    if provider == "anthropic":
        content = body.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str):
                return text
        raise ModelOutputError("model output invalid")
    choices = body.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            text = message.get("content")
            if isinstance(text, str):
                return text
    raise ModelOutputError("model output invalid")
