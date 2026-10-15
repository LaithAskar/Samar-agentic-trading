# Samar

Paper-trading practice app. One engine, one strategy spec, one job table.

## Commands

- `make verify` is the gate.
- API: `uv run python -m samar_api` on port 43124.
- Web: `pnpm --filter web dev` on port 43123.

## Boundaries

- `packages/engine` does not import network, clock, or environment. Bars and `now` are arguments.
- Routers in `apps/api` call `AppState`. They do not reimplement fills.
- `packages/secrets` is the only package that imports `cryptography`.
- `packages/brokers` exposes list accounts, portfolio, and quotes. There is no order function.
- Agent writes go through a proposal row. Approval is a separate call.

## Never

- Do not add `place_order`, `robin_stocks`, scrapers, or a live-order module.
- Do not commit `.env`, keys, parquet, or HTML result dumps.
- Do not weaken a check to get green. No blanket `type: ignore`, no skipped tests, no `--no-verify`.
- Do not phrase model output as advice. `scrub_advice` is the check.

## When a review comment repeats

Add a test or a lint, then a line in `docs/lessons.md`. Do not add a paragraph here.
