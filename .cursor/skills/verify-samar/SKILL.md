---
name: verify-samar
description: Launch Samar, hit health, drive the paper loop, save screenshots.
---

# Verify Samar

## Launch

1. `uv run python -m samar_api` on port 43124.
2. `pnpm --filter web dev` on port 43123.
3. Open `http://127.0.0.1:43123`.

## Doctor

`curl -s http://127.0.0.1:43124/health` returns `{"status":"ok"}`.

## Drive

1. Strategies, New rule, Backtest 2020–2024.
2. Read the skepticism panel. Click Paper trade this.
3. Dashboard shows a position or cash.
4. Settings rejects a short key and masks a shaped key.
5. Assistant stays disabled until that key exists. After it exists, a draft does not create a strategy until Approve.

## Evidence

Save screenshots under `artifacts/`.

## Cleanup

Stop the two processes you started.
