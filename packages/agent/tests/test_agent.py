from __future__ import annotations

from samar_agent.advice import scrub_advice
from samar_agent.loop import AgentEvent, Budget, ModelStep, Proposal, ScriptedModel, run_turn
from samar_agent.pricing import estimate_cost


def test_haiku_cost_for_one_thousand_tokens() -> None:
    cost = estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000)
    assert cost.total_dollars == 6.0


def test_advice_phrasing_is_replaced() -> None:
    assert scrub_advice("You should buy AAPL today.") == (
        "I can show a simulated result. I cannot tell you what to buy or sell. AAPL today."
    )


def test_unapproved_tool_returns_a_proposal_and_writes_nothing() -> None:
    writes: list[str] = []

    def tool(name: str, payload: dict[str, str]) -> tuple[str, Proposal | None]:
        if name == "create_strategy_draft":
            return (
                "draft only",
                Proposal(proposal_id="p1", kind="create_strategy", payload=payload),
            )
        writes.append(name)
        return ("ok", None)

    events = run_turn("Build an sma cross", ScriptedModel(), tool, Budget(limit_dollars=1.0))
    assert writes == []
    proposals = [event.proposal for event in events if event.kind == "proposal"]
    assert proposals == [
        Proposal(proposal_id="p1", kind="create_strategy", payload={"template": "sma_cross", "ticker": "AAPL"})
    ]


def test_budget_blocks_the_second_charge() -> None:
    budget = Budget(limit_dollars=0.00001)
    step = ModelStep("t", None, {}, "done", input_tokens=1_000_000, output_tokens=0)
    try:
        budget.charge("claude-haiku-4-5", step)
    except RuntimeError as exc:
        assert str(exc) == "token budget exceeded"
    else:
        raise AssertionError("budget allowed a one-dollar call")
    assert budget.spent == 0.0


def test_final_event_is_scrubbed() -> None:
    class Rude(ScriptedModel):
        def step(self, user_text: str, observations: list[str]) -> ModelStep:
            return ModelStep("t", None, {}, "You should buy AAPL.", 1, 1)

    events = run_turn("hi", Rude(), lambda name, payload: ("", None), Budget(1.0))
    finals = [event.text for event in events if event.kind == "final"]
    assert finals == ["I can show a simulated result. I cannot tell you what to buy or sell. AAPL."]
    assert all(isinstance(event, AgentEvent) for event in events)
