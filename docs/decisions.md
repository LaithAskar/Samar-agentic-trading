# Decisions

## Local store is sqlite, with a Postgres RLS contract beside it

The plan calls for Supabase and a live RLS test. This environment has no local Supabase. The app runs on sqlite so the demo starts with one command. `supabase/migrations/0001_init.sql` is the Postgres policy contract. A test fails if a table lacks `ENABLE ROW LEVEL SECURITY`, and `user_secrets` has RLS with no authenticated policy. A second test shows user A cannot read user B through the API. When Supabase is attached, apply that migration and keep the API on the service role for secrets.

## Settings sync is a read

`POST /broker/sync` opens the stored Public.com key, exchanges a short-lived token, and reads the first account's portfolio. The dashboard shows that snapshot beside the paper account. Order methods are not on that client.

## Live orders stay in one module

Order placement exists only in `apps/api/src/samar_api/live/`. `scripts/check_no_orders.py` fails if `place_order`, `cancel_order`, `preflight`, or `replace_order` is defined anywhere else, and it fails if `public_live.py` appears. Import-linter forbids the agent and the worker from importing `samar_api.live` or `samar_brokers.public_live`. Live mode is off until the user types a confirmation. Auto mode needs a second confirmation. Both paths call `evaluate`. The worker loop calls `AppState.run_live_cycles` during market hours. A broker error, three rejections, an unexpected position, or the daily loss stop turns live mode off and cancels orders Samar recorded.

## Default slippage is 5 bps

The ported engine constructor defaulted to 0. The documented fill contract, and Meridian, use 5 bps. Samar's engine defaults to 5. Tests that assert a raw open pass `slippage_bps=0`.

## Frozen bars replaced the README's AAPL sample

`ai-trading-agent` README reports SMA 20/50 on AAPL 2020–2024 as 99.71% return, 14.86% CAGR, 71.43% win rate, Sharpe 0.89, p-value 0.0464. A Yahoo chart pull on 2026-10-14 produced 111.63% return, 16.19% CAGR, 46.15% win rate, Sharpe 0.84, p-value 0.0596, 13 round trips. Buy-and-hold of those bars was 236.76%. That pull is not in the repository.

## Committed bars are a seeded series

Yahoo Finance says not to redistribute information it provides. The files under `packages/data/src/samar_data/fixtures/` are the output of `scripts/write_price_fixtures.py`. On that AAPL series the same SMA 20/50 rule returns -22.14%, CAGR -4.89%, win rate 33.33%, Sharpe -0.35, p-value 0.4215, 12 round trips. Buy-and-hold is -46.32%. `test_sma_cross_aapl_2020_2024_frozen_fixture` locks those numbers.

## Skepticism compares to holding the traded ticker

The chart overlays SPY. The warning panel compares the strategy with buy-and-hold of the same ticker. That is the comparison the README treats as the lesson.

## Yahoo chart HTTP instead of the yfinance package

The adapter lives in `packages/data` and hits the chart endpoint yfinance uses. The engine does not import it. Unit tests read the CSV fixture. `pytest` blocks sockets except the in-process API tests.

## Demo key check is a shape check

Saving a key encrypts it and returns last-4. Validation accepts `sk-ant-` / `sk-or-` shaped strings and `pub-` shaped public secrets so the app runs without a live provider call. A saved Anthropic key calls `https://api.anthropic.com/v1/messages`. OpenRouter, OpenAI, and Nous Research use chat completions. Nous Portal's OpenAPI server is `https://inference-api.nousresearch.com/v1`, and the key shape is `sk-nous-`. With no key, the turn uses `ScriptedModel`. A saved choice picks the provider when more than one model key exists. Either path stores a proposal and writes a strategy only after Approve.

## Local sessions, Supabase when configured

`SAMAR_SUPABASE_URL` and `SAMAR_SUPABASE_ANON_KEY` switch the API to Supabase Auth. The API checks `GET /auth/v1/user` and uses the returned user id. When those variables are absent, register and login store a PBKDF2 password and a hashed bearer token in sqlite. Routes read that token. They do not accept `X-User-Id`.

## Arena rank

Contestants search only the train window. The leaderboard sorts by held-out Sharpe after `sharpe_se * sqrt(2 * ln(n_trials))`. Buy-and-hold and SMA 20/50 are baselines with one trial. Random search uses seed 1. Invalid specs count as trials. The run is one queued job and a repeated post returns that job.

## KEK for local runs

If `SAMAR_KEK` is unset and `SAMAR_ENV` is empty or one of `dev`, `development`, `local`, or `test`, the process uses a fixed development key padded to 32 bytes and prints a warning. Any other `SAMAR_ENV` refuses to start when the variable is missing or equal to that development key. Set `SAMAR_KEK` to 64 hex characters before any shared deployment.
