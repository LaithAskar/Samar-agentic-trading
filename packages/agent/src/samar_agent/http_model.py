from __future__ import annotations

import json
from typing import Literal

import httpx

from samar_agent.loop import ModelStep, ToolName

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
NOUS_URL = "https://inference-api.nousresearch.com/v1/chat/completions"
ProviderName = Literal["anthropic", "openrouter", "openai", "nous"]
DEFAULT_MODELS: dict[ProviderName, str] = {
    "anthropic": "claude-haiku-4-5",
    "openrouter": "anthropic/claude-haiku-4.5",
    "openai": "gpt-4o-mini",
    "nous": "Hermes-4.3-36B",
}
_SYSTEM = (
    "You are Samar's research assistant. Reply with one JSON object and no markdown. "
    "Keys are thought (string), action (null or a tool name), action_input (object whose values are strings), "
    "and final (string or null). Tool names: list_strategies, create_strategy_draft, run_backtest, "
    "read_backtest, search_memory, get_price_history. "
    "create_strategy_draft and run_backtest do not run. They become proposals a person must approve. "
    "Do not tell the person what to buy or sell."
)


class HttpChatModel:
    def __init__(
        self,
        provider: ProviderName,
        api_key: str,
        client: httpx.Client,
        model: str,
        url: str,
    ) -> None:
        self.provider = provider
        self._api_key = api_key
        self._client = client
        self._model = model
        self._url = url

    def step(self, user_text: str, observations: list[str]) -> ModelStep:
        prompt = user_text if not observations else user_text + "\nObservations:\n" + "\n".join(observations)
        if self.provider == "anthropic":
            response = self._client.post(
                self._url,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 400,
                    "system": _SYSTEM,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        else:
            response = self._client.post(
                self._url,
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
        response.raise_for_status()
        body = _object(response.json())
        text, input_tokens, output_tokens = _message_text(self.provider, body)
        return _parse_step(text, input_tokens, output_tokens)


def _message_text(provider: str, body: dict[str, object]) -> tuple[str, int, int]:
    if provider == "anthropic":
        parts: list[str] = []
        for block in _objects(body.get("content")):
            raw = block.get("text")
            if isinstance(raw, str):
                parts.append(raw)
        usage = _object(body.get("usage") or {})
        return "".join(parts), _int(usage.get("input_tokens")), _int(usage.get("output_tokens"))
    text = ""
    choices = _objects(body.get("choices"))
    if choices:
        message = _object(choices[0].get("message") or {})
        content = message.get("content")
        text = content if isinstance(content, str) else ""
    usage = _object(body.get("usage") or {})
    return text, _int(usage.get("prompt_tokens")), _int(usage.get("completion_tokens"))


def _parse_step(text: str, input_tokens: int, output_tokens: int) -> ModelStep:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model reply was not JSON")
    payload = _object(json.loads(text[start : end + 1]))
    thought = payload.get("thought")
    if not isinstance(thought, str):
        raise ValueError("model reply missing thought")
    action = _tool(payload.get("action"))
    action_input = _string_map(payload.get("action_input"))
    final = payload.get("final")
    if final is not None and not isinstance(final, str):
        raise ValueError("model reply final must be a string")
    return ModelStep(
        thought=thought,
        action=action,
        action_input=action_input,
        final=final,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _tool(value: object) -> ToolName | None:
    if value is None:
        return None
    if value == "list_strategies":
        return "list_strategies"
    if value == "create_strategy_draft":
        return "create_strategy_draft"
    if value == "run_backtest":
        return "run_backtest"
    if value == "read_backtest":
        return "read_backtest"
    if value == "search_memory":
        return "search_memory"
    if value == "get_price_history":
        return "get_price_history"
    raise ValueError("model reply has an unknown action")


def _string_map(value: object) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for key, item in _pairs(value):
        if not isinstance(item, str):
            raise ValueError("action_input values must be strings")
        mapped[key] = item
    return mapped


def _objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [_object(item) for item in value if isinstance(item, dict)]


def _object(value: object) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, item in _pairs(value):
        parsed[key] = item
    return parsed


def _pairs(value: object) -> list[tuple[str, object]]:
    if not isinstance(value, dict):
        return []
    rows: list[tuple[str, object]] = []
    for key, item in value.items():
        if isinstance(key, str):
            rows.append((key, item))
    return rows


def _int(value: object) -> int:
    if isinstance(value, int):
        return value
    return 0
