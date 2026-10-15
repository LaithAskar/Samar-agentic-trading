from __future__ import annotations

import math

from samar_engine.arena import RankRow, best_train_index, deflated_sharpe, random_specs, rank_labels


def test_one_trial_has_no_haircut() -> None:
    assert deflated_sharpe(1.0, 0.5, 1) == 1.0


def test_three_trials_subtract_se_times_sqrt_two_ln_n() -> None:
    assert deflated_sharpe(1.0, 0.5, 3) == 1.0 - 0.5 * math.sqrt(2.0 * math.log(3))


def test_rank_uses_held_out_deflated_sharpe_not_name_order() -> None:
    order = rank_labels(
        [
            RankRow("openai:gpt-4o-mini", 0.2, 12.0, 4),
            RankRow("baseline:buy_and_hold", 0.9, 30.0, 0),
            RankRow("random:random-search", 0.4, 18.0, 2),
            RankRow("anthropic:claude-haiku-4-5", None, None, None),
        ]
    )
    assert order == [
        "baseline:buy_and_hold",
        "random:random-search",
        "openai:gpt-4o-mini",
        "anthropic:claude-haiku-4-5",
    ]


def test_tied_deflated_sharpe_prefers_smaller_drawdown_then_turnover() -> None:
    order = rank_labels(
        [
            RankRow("a", 0.5, 20.0, 1),
            RankRow("b", 0.5, 10.0, 4),
            RankRow("c", 0.5, 10.0, 2),
        ]
    )
    assert order == ["c", "b", "a"]


def test_random_search_seed_is_sma_20_then_sma_10() -> None:
    first = random_specs(2)
    second = random_specs(2)
    assert first[0].model_dump() == second[0].model_dump()
    assert first[0].model_dump()["rules"][0]["when"]["left"] == {
        "kind": "indicator",
        "name": "sma",
        "ticker": "AAPL",
        "period": 20,
    }
    assert first[1].model_dump()["rules"][0]["when"]["left"]["period"] == 10


def test_best_train_index_skips_failures() -> None:
    assert best_train_index([None, 0.1, 0.4, 0.2]) == 2
    assert best_train_index([None, None]) is None
