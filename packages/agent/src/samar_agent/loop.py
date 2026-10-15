from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel

from samar_agent.advice import scrub_advice
from samar_agent.pricing import estimate_cost

ToolName = Literal[
    "list_strategies",
    "create_strategy_draft",
    "run_backtest",
    "read_backtest",
    "search_memory",
    "get_price_history",
]


class Proposal(BaseModel):
    proposal_id: str
    kind: Literal["create_strategy", "run_backtest"]
    payload: dict[str, str]


class AgentEvent(BaseModel):
    kind: Literal["thought", "action", "observation", "proposal", "final"]
    text: str
    proposal: Proposal | None = None


@dataclass(frozen=True)
class ModelStep:
    thought: str
    action: ToolName | None
    action_input: dict[str, str]
    final: str | None
    input_tokens: int
    output_tokens: int


class Budget:
    def __init__(self, limit_dollars: float) -> None:
        self.limit_dollars = limit_dollars
        self.spent = 0.0

    def charge(self, model: str, step: ModelStep) -> float:
        cost = estimate_cost(model, step.input_tokens, step.output_tokens).total_dollars
        if self.spent + cost > self.limit_dollars:
            raise RuntimeError("token budget exceeded")
        self.spent += cost
        return cost


class ChatModel(Protocol):
    def step(self, user_text: str, observations: list[str]) -> ModelStep:
        """One model turn."""
        ...


class ScriptedModel:
    """Local draft used when the user has no provider key, and in unit tests."""

    def step(self, user_text: str, observations: list[str]) -> ModelStep:
        if not observations and "sma" in user_text.lower():
            return ModelStep(
                thought="The user asked for an SMA cross. Draft it and wait for approval.",
                action="create_strategy_draft",
                action_input={"template": "sma_cross", "ticker": "AAPL"},
                final=None,
                input_tokens=20,
                output_tokens=10,
            )
        if not observations and "backtest" in user_text.lower():
            return ModelStep(
                thought="A backtest needs approval before it is queued.",
                action="run_backtest",
                action_input={"strategy_id": "pending", "ticker": "AAPL"},
                final=None,
                input_tokens=20,
                output_tokens=10,
            )
        return ModelStep(
            thought="Answer from the observations.",
            action=None,
            action_input={},
            final="Draft is ready for your approval. Nothing is saved until you approve it.",
            input_tokens=20,
            output_tokens=12,
        )


def run_turn(
    user_text: str,
    model: ChatModel,
    tool: Callable[[ToolName, dict[str, str]], tuple[str, Proposal | None]],
    budget: Budget,
    model_name: str = "claude-haiku-4-5",
) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    observations: list[str] = []
    for _ in range(4):
        step = model.step(user_text, observations)
        budget.charge(model_name, step)
        events.append(AgentEvent(kind="thought", text=step.thought))
        if step.action is None:
            events.append(AgentEvent(kind="final", text=scrub_advice(step.final or "")))
            return events
        events.append(AgentEvent(kind="action", text=step.action))
        observation, proposal = tool(step.action, step.action_input)
        observations.append(observation)
        events.append(AgentEvent(kind="observation", text=observation))
        if proposal is not None:
            events.append(AgentEvent(kind="proposal", text=proposal.kind, proposal=proposal))
    events.append(AgentEvent(kind="final", text=scrub_advice("Stopped after four steps.")))
    return events
