from __future__ import annotations

from dataclasses import dataclass

PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "anthropic/claude-haiku-4.5": (1.0, 5.0),
    "gpt-4o-mini": (0.15, 0.6),
}
_FALLBACK = PRICING_PER_MTOK["claude-sonnet-4-6"]


@dataclass(frozen=True)
class CostEstimate:
    input_tokens: int
    output_tokens: int
    total_dollars: float


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> CostEstimate:
    input_rate, output_rate = PRICING_PER_MTOK.get(model, _FALLBACK)
    total = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    return CostEstimate(input_tokens, output_tokens, total)
