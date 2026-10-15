from __future__ import annotations

import json

import httpx
from samar_agent.http_model import ANTHROPIC_URL, NOUS_URL, OPENAI_URL, OPENROUTER_URL, HttpChatModel

_DRAFT = {
    "thought": "Draft the SMA and wait.",
    "action": "create_strategy_draft",
    "action_input": {"template": "sma_cross", "ticker": "AAPL"},
    "final": None,
}


def test_anthropic_step_parses_a_proposal_json() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": json.dumps(_DRAFT)}],
                "usage": {"input_tokens": 11, "output_tokens": 7},
            },
        )

    key = "sk-" + "ant-test-key-aaaa"
    model = HttpChatModel(
        "anthropic",
        key,
        httpx.Client(transport=httpx.MockTransport(handler)),
        "claude-haiku-4-5",
        ANTHROPIC_URL,
    )
    step = model.step("Build an sma cross", [])
    assert step.thought == "Draft the SMA and wait."
    assert step.action == "create_strategy_draft"
    assert step.action_input == {"template": "sma_cross", "ticker": "AAPL"}
    assert step.final is None
    assert step.input_tokens == 11
    assert step.output_tokens == 7
    assert str(seen[0].url) == ANTHROPIC_URL
    assert seen[0].headers["x-api-key"] == key
    assert seen[0].headers["anthropic-version"] == "2023-06-01"


def test_openrouter_step_reads_chat_completions() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert request.headers["authorization"] == "Bearer " + ("sk-" + "or-test-key-bbbb")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(_DRAFT)}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
            },
        )

    model = HttpChatModel(
        "openrouter",
        "sk-" + "or-test-key-bbbb",
        httpx.Client(transport=httpx.MockTransport(handler)),
        "anthropic/claude-haiku-4.5",
        OPENROUTER_URL,
    )
    step = model.step("Build an sma cross", [])
    assert step.input_tokens == 8
    assert step.output_tokens == 4
    assert step.action == "create_strategy_draft"
    assert seen == [OPENROUTER_URL]


def test_openai_step_posts_chat_completions() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(_DRAFT)}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        )

    key = "sk-" + "proj-openai-demo-key"
    model = HttpChatModel(
        "openai",
        key,
        httpx.Client(transport=httpx.MockTransport(handler)),
        "gpt-4o-mini",
        OPENAI_URL,
    )
    step = model.step("Build an sma cross", [])
    assert step.action == "create_strategy_draft"
    assert step.input_tokens == 5
    assert step.output_tokens == 3
    assert str(seen[0].url) == OPENAI_URL
    assert seen[0].headers["authorization"] == "Bearer " + key
    assert json.loads(seen[0].content)["model"] == "gpt-4o-mini"


def test_nous_step_posts_portal_chat_completions() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(_DRAFT)}}],
                "usage": {"prompt_tokens": 6, "completion_tokens": 2},
            },
        )

    key = "sk-" + "nous-portal-keyzz"
    model = HttpChatModel(
        "nous",
        key,
        httpx.Client(transport=httpx.MockTransport(handler)),
        "Hermes-4.3-36B",
        NOUS_URL,
    )
    step = model.step("Build an sma cross", [])
    assert step.action == "create_strategy_draft"
    assert step.input_tokens == 6
    assert step.output_tokens == 2
    assert str(seen[0].url) == "https://inference-api.nousresearch.com/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer " + key
    assert json.loads(seen[0].content)["model"] == "Hermes-4.3-36B"


def test_prose_reply_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": [{"type": "text", "text": "You should buy AAPL."}], "usage": {}})

    model = HttpChatModel(
        "anthropic",
        "sk-" + "ant-test-key-aaaa",
        httpx.Client(transport=httpx.MockTransport(handler)),
        "claude-haiku-4-5",
        ANTHROPIC_URL,
    )
    try:
        model.step("hello", [])
    except ValueError as exc:
        assert str(exc) == "model reply was not JSON"
    else:
        raise AssertionError("prose was accepted")
