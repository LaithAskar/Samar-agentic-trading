from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import httpx
from samar_agent.http_model import (
    ANTHROPIC_URL,
    NOUS_URL,
    OPENAI_URL,
    OPENROUTER_URL,
    HttpChatModel,
    ProviderName,
)
from samar_contracts.models import ArenaEntryView, ArenaProposalView, ArenaRunView, EquityPoint, SkepticismView
from samar_data.market import MarketData
from samar_engine.arena import (
    RANDOM_SEED,
    HistorySplit,
    RankRow,
    Scorecard,
    best_train_index,
    deflated_sharpe,
    random_specs,
    rank_labels,
    score_buy_and_hold,
    score_spec,
    split_history,
)
from samar_engine.core.events import Bar
from samar_engine.dsl import StrategySpec, sma_cross_spec


def arena_prompt(ticker: str, train_start: str, train_end: str) -> str:
    return (
        f"Propose one {ticker} strategy. Put a StrategySpec JSON string in final. "
        "action is null. action_input is {}. "
        f"You may use bars from {train_start} through {train_end} only. "
        f"Bars after {train_end} are hidden. "
        "Do not tell the person what to buy or sell."
    )


_URLS: dict[ProviderName, tuple[str, str]] = {
    "anthropic": ("SAMAR_ANTHROPIC_URL", ANTHROPIC_URL),
    "openrouter": ("SAMAR_OPENROUTER_URL", OPENROUTER_URL),
    "openai": ("SAMAR_OPENAI_URL", OPENAI_URL),
    "nous": ("SAMAR_NOUS_URL", NOUS_URL),
}


@dataclass
class _Built:
    provider: str
    model: str
    card: Scorecard | None
    n_trials: int
    n_failures: int
    tokens_in: int
    tokens_out: int
    proposals: list[dict[str, object]]
    fold_sharpes: list[float]
    spec_json: str | None


@dataclass
class _Board:
    ticker: str
    budget: int
    token_cap: int
    train: list[Bar]
    test: list[Bar]
    folds: tuple[list[Bar], list[Bar]]
    train_start: str
    train_end: str
    http: httpx.Client
    read_key: Callable[[str, str], str | None]
    user_id: str


def load_history_split(market: MarketData, ticker: str) -> HistorySplit:
    try:
        bars = market.bars(ticker, date(1990, 1, 1), date(2100, 1, 1))
        return split_history(bars)
    except (ValueError, KeyError) as exc:
        raise ValueError(
            f"{ticker} has no cached bars and no synthetic fixture. Run: uv run python -m samar_data.fetch " + ticker
        ) from exc


def execute_arena(  # noqa: PLR0917
    conn: sqlite3.Connection,
    market: MarketData,
    http: httpx.Client,
    read_key: Callable[[str, str], str | None],
    user_id: str,
    run_id: str,
) -> None:  # noqa: PLR0917
    run = conn.execute("SELECT * FROM arena_runs WHERE id = ? AND user_id = ?", (run_id, user_id)).fetchone()
    if run is None:
        raise KeyError(run_id)
    ticker = str(run["ticker"])
    split = load_history_split(market, ticker)
    board = _Board(
        ticker=ticker,
        budget=int(run["budget_proposals"]),
        token_cap=int(run["token_cap"]),
        train=split.train,
        test=split.test,
        folds=split.folds,
        train_start=split.train[0].timestamp.date().isoformat(),
        train_end=split.train[-1].timestamp.date().isoformat(),
        http=http,
        read_key=read_key,
        user_id=user_id,
    )
    conn.execute(
        """UPDATE arena_runs
        SET train_start = ?, train_end = ?, test_start = ?, test_end = ?, data_label = ?
        WHERE id = ?""",
        (
            board.train_start,
            board.train_end,
            split.test[0].timestamp.date().isoformat(),
            split.test[-1].timestamp.date().isoformat(),
            market.data_label((ticker,)),
            run_id,
        ),
    )
    conn.execute("DELETE FROM arena_entries WHERE run_id = ?", (run_id,))
    built = [_contestant(item, board) for item in _contestants(str(run["contestants_json"]))]
    built.append(_baseline("buy_and_hold", score_buy_and_hold(board.test)))
    sma = _annotate(score_spec(sma_cross_spec(ticker), board.test), 1, baseline=True)
    built.append(_baseline("sma_20_50", sma))
    labels = rank_labels([_rank_row(item) for item in built])
    for item in built:
        _insert(conn, run_id, user_id, item, labels.index(_label(item)) + 1)
    conn.commit()


def arena_view(conn: sqlite3.Connection, user_id: str, run_id: str) -> ArenaRunView:
    run = conn.execute("SELECT * FROM arena_runs WHERE id = ? AND user_id = ?", (run_id, user_id)).fetchone()
    if run is None:
        raise KeyError(run_id)
    rows = conn.execute(
        "SELECT * FROM arena_entries WHERE run_id = ? ORDER BY rank IS NULL, rank, contestant, model",
        (run_id,),
    ).fetchall()
    return ArenaRunView(
        id=str(run["id"]),
        status=str(run["status"]),
        ticker=str(run["ticker"]),
        train_start=str(run["train_start"] or ""),
        train_end=str(run["train_end"] or ""),
        test_start=str(run["test_start"] or ""),
        test_end=str(run["test_end"] or ""),
        data_label=str(run["data_label"] or "SYNTHETIC DATA"),
        budget_proposals=int(run["budget_proposals"]),
        token_cap=int(run["token_cap"]),
        entries=[_entry_view(row) for row in rows],
        error=None if run["error"] is None else str(run["error"]),
    )


def _contestants(raw: str) -> list[tuple[str, str]]:
    parsed: object = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("contestants must be a list")
    contestants: list[tuple[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("contestant must be an object")
        provider = item.get("provider")
        model = item.get("model")
        if not isinstance(provider, str) or not isinstance(model, str):
            raise ValueError("contestant provider and model are required")
        contestants.append((provider, model))
    return contestants


def _contestant(item: tuple[str, str], board: _Board) -> _Built:
    provider, model = item
    if provider == "random":
        specs = random_specs(board.budget, board.ticker, RANDOM_SEED)
        return _from_specs("random", "random-search", specs, board)
    name = _provider(provider)
    key = board.read_key(board.user_id, provider) if name is not None else None
    if name is None or key is None:
        return _Built(provider, model, None, 0, 1, 0, 0, [{"index": 0, "ok": False, "error": "key missing"}], [], None)
    env_name, url = _URLS[name]
    chat = HttpChatModel(name, key, board.http, model, os.environ.get(env_name, url))
    return _from_model(provider, model, chat, board)


def _from_model(provider: str, model: str, chat: HttpChatModel, board: _Board) -> _Built:
    observations: list[str] = []
    specs: list[StrategySpec] = []
    proposals: list[dict[str, object]] = []
    tokens_in = 0
    tokens_out = 0
    failures = 0
    for index in range(board.budget):
        if tokens_in + tokens_out >= board.token_cap:
            break
        try:
            step = chat.step(arena_prompt(board.ticker, board.train_start, board.train_end), observations)
        except (ValueError, httpx.HTTPError) as exc:
            failures += 1
            proposals.append({"index": index, "ok": False, "error": str(exc)})
            continue
        tokens_in += step.input_tokens
        tokens_out += step.output_tokens
        try:
            spec = StrategySpec.model_validate_json(step.final or "")
            if spec.universe != [board.ticker]:
                raise ValueError("spec ticker must be the arena ticker")
        except ValueError as exc:
            failures += 1
            proposals.append({"index": index, "ok": False, "error": str(exc)})
            continue
        train_score = score_spec(spec, board.train)
        observations.append(
            "train sharpe="
            f"{train_score.sharpe:.6f} max_drawdown_pct={train_score.max_drawdown_pct:.6f} "
            f"round_trips={train_score.turnover}"
        )
        specs.append(spec)
        proposals.append(
            {
                "index": index,
                "ok": True,
                "error": None,
                "train_sharpe": train_score.sharpe,
                "spec_name": spec.name,
            }
        )
        if tokens_in + tokens_out >= board.token_cap:
            break
    attempt = _Attempt(specs, proposals, failures, tokens_in, tokens_out)
    return _chosen(provider, model, attempt, board)


def _from_specs(provider: str, model: str, specs: list[StrategySpec], board: _Board) -> _Built:
    proposals: list[dict[str, object]] = []
    for index, spec in enumerate(specs):
        train_score = score_spec(spec, board.train)
        proposals.append(
            {
                "index": index,
                "ok": True,
                "error": None,
                "train_sharpe": train_score.sharpe,
                "spec_name": spec.name,
            }
        )
    return _chosen(provider, model, _Attempt(specs, proposals, 0, 0, 0), board)


@dataclass
class _Attempt:
    specs: list[StrategySpec]
    proposals: list[dict[str, object]]
    failures: int
    tokens_in: int
    tokens_out: int


def _chosen(provider: str, model: str, attempt: _Attempt, board: _Board) -> _Built:
    successes = [item for item in attempt.proposals if item.get("ok") is True]
    chosen = best_train_index([_optional_float(item.get("train_sharpe")) for item in successes])
    if chosen is None:
        return _Built(
            provider,
            model,
            None,
            len(attempt.proposals),
            attempt.failures,
            attempt.tokens_in,
            attempt.tokens_out,
            attempt.proposals,
            [],
            None,
        )
    spec = attempt.specs[chosen]
    card = _annotate(score_spec(spec, board.test), len(attempt.proposals), baseline=False)
    fold_sharpes = [score_spec(spec, fold).sharpe for fold in board.folds]
    return _Built(
        provider,
        model,
        card,
        len(attempt.proposals),
        attempt.failures,
        attempt.tokens_in,
        attempt.tokens_out,
        attempt.proposals,
        fold_sharpes,
        spec.model_dump_json(),
    )


def _baseline(model: str, card: Scorecard) -> _Built:
    return _Built("baseline", model, card, 1, 0, 0, 0, [], [], None)


def _annotate(card: Scorecard, n_trials: int, baseline: bool) -> Scorecard:
    warnings = list(card.skepticism.warnings)
    if baseline:
        warnings.insert(0, "Baseline. No model searched this rule.")
    else:
        warnings.append("Rank uses the held-out window. Train Sharpe is not the rank.")
        if n_trials > 1:
            warnings.append(f"{n_trials} trials were tried. The rank subtracts a multiple-testing haircut.")
    warnings.append("Historical backtest on a small sample. Not a prediction.")
    return _replace_warnings(card, warnings)


def _replace_warnings(card: Scorecard, warnings: list[str]) -> Scorecard:
    skepticism = card.skepticism.model_copy(update={"warnings": warnings})
    return Scorecard(
        sharpe=card.sharpe,
        sharpe_se=card.sharpe_se,
        max_drawdown_pct=card.max_drawdown_pct,
        turnover=card.turnover,
        total_return_pct=card.total_return_pct,
        p_value=card.p_value,
        sample_days=card.sample_days,
        benchmark_return_pct=card.benchmark_return_pct,
        equity=card.equity,
        skepticism=skepticism,
    )


def _label(item: _Built) -> str:
    return f"{item.provider}:{item.model}"


def _rank_row(item: _Built) -> RankRow:
    if item.card is None or item.n_trials < 1:
        return RankRow(_label(item), None, None, None)
    return RankRow(
        _label(item),
        deflated_sharpe(item.card.sharpe, item.card.sharpe_se, item.n_trials),
        item.card.max_drawdown_pct,
        item.card.turnover,
    )


def _insert(conn: sqlite3.Connection, run_id: str, user_id: str, item: _Built, rank: int) -> None:
    card = item.card
    conn.execute(
        """INSERT INTO arena_entries (
        id, run_id, user_id, contestant, model, status, n_trials, n_failures,
        tokens_in, tokens_out, rank, deflated_sharpe, test_sharpe, test_sharpe_se,
        test_max_drawdown_pct, turnover, fold_sharpe_json, skepticism_json, equity_json,
        proposals_json, spec_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            f"ent_{run_id}_{item.provider}_{item.model}",
            run_id,
            user_id,
            item.provider,
            item.model,
            "failed" if card is None else "scored",
            item.n_trials,
            item.n_failures,
            item.tokens_in,
            item.tokens_out,
            rank,
            None if card is None else deflated_sharpe(card.sharpe, card.sharpe_se, max(item.n_trials, 1)),
            None if card is None else card.sharpe,
            None if card is None else card.sharpe_se,
            None if card is None else card.max_drawdown_pct,
            None if card is None else card.turnover,
            json.dumps(item.fold_sharpes),
            None if card is None else card.skepticism.model_dump_json(),
            None if card is None else json.dumps([{"date": day, "equity": value} for day, value in card.equity]),
            json.dumps(item.proposals),
            item.spec_json,
        ),
    )


def _entry_view(row: sqlite3.Row) -> ArenaEntryView:
    raw_skepticism = row["skepticism_json"]
    skepticism = None if raw_skepticism is None else SkepticismView.model_validate_json(str(raw_skepticism))
    return ArenaEntryView(
        contestant=str(row["contestant"]),
        model=str(row["model"]),
        status=str(row["status"]),
        n_trials=int(row["n_trials"]),
        n_failures=int(row["n_failures"]),
        tokens_in=int(row["tokens_in"]),
        tokens_out=int(row["tokens_out"]),
        rank=None if row["rank"] is None else int(row["rank"]),
        deflated_sharpe=None if row["deflated_sharpe"] is None else float(row["deflated_sharpe"]),
        test_sharpe=None if row["test_sharpe"] is None else float(row["test_sharpe"]),
        test_sharpe_se=None if row["test_sharpe_se"] is None else float(row["test_sharpe_se"]),
        test_max_drawdown_pct=None if row["test_max_drawdown_pct"] is None else float(row["test_max_drawdown_pct"]),
        turnover=None if row["turnover"] is None else int(row["turnover"]),
        fold_sharpes=_floats(row["fold_sharpe_json"]),
        skepticism=skepticism,
        equity=_equity(row["equity_json"]),
        proposals=_proposals(row["proposals_json"]),
    )


def _floats(raw: object) -> list[float]:
    parsed: object = json.loads(str(raw or "[]"))
    if not isinstance(parsed, list):
        return []
    return [float(item) for item in parsed if isinstance(item, int | float)]


def _equity(raw: object) -> list[EquityPoint]:
    if raw is None:
        return []
    parsed: object = json.loads(str(raw))
    if not isinstance(parsed, list):
        return []
    points: list[EquityPoint] = []
    for item in parsed:
        if isinstance(item, dict) and isinstance(item.get("date"), str) and isinstance(item.get("equity"), int | float):
            points.append(EquityPoint(date=str(item["date"]), equity=float(item["equity"])))
    return points


def _proposals(raw: object) -> list[ArenaProposalView]:
    parsed: object = json.loads(str(raw or "[]"))
    if not isinstance(parsed, list):
        return []
    views: list[ArenaProposalView] = []
    for item in parsed:
        if not isinstance(item, dict) or not isinstance(item.get("index"), int) or not isinstance(item.get("ok"), bool):
            continue
        error = item.get("error")
        train = item.get("train_sharpe")
        name = item.get("spec_name")
        views.append(
            ArenaProposalView(
                index=item["index"],
                ok=item["ok"],
                error=error if isinstance(error, str) else None,
                train_sharpe=float(train) if isinstance(train, int | float) else None,
                spec_name=name if isinstance(name, str) else None,
            )
        )
    return views


def _provider(value: str) -> ProviderName | None:
    if value == "anthropic":
        return "anthropic"
    if value == "openrouter":
        return "openrouter"
    if value == "openai":
        return "openai"
    if value == "nous":
        return "nous"
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None
