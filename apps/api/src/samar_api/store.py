from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  dsl_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backtests (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  status TEXT NOT NULL,
  metrics_json TEXT,
  skepticism_json TEXT,
  equity_json TEXT,
  benchmark_json TEXT,
  trades_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  job_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  backtest_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deployments (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  started_on TEXT NOT NULL,
  active INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_orders (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  eval_key TEXT NOT NULL UNIQUE,
  ticker TEXT NOT NULL,
  side TEXT NOT NULL,
  quantity REAL NOT NULL,
  price REAL NOT NULL,
  filled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_cash (
  user_id TEXT PRIMARY KEY,
  starting_cash REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS user_secrets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  ciphertext BLOB NOT NULL,
  wrapped_dek BLOB NOT NULL,
  nonce BLOB NOT NULL,
  dek_nonce BLOB NOT NULL,
  kek_version INTEGER NOT NULL,
  last4 TEXT NOT NULL,
  status TEXT NOT NULL,
  validated_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, kind)
);
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_snapshots (
  user_id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_spend (
  user_id TEXT PRIMARY KEY,
  spent_dollars REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assistant_choice (
  user_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  model TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS arena_runs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  status TEXT NOT NULL,
  ticker TEXT NOT NULL,
  budget_proposals INTEGER NOT NULL,
  token_cap INTEGER NOT NULL,
  contestants_json TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS arena_entries (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  contestant TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,
  n_trials INTEGER NOT NULL,
  n_failures INTEGER NOT NULL,
  tokens_in INTEGER NOT NULL,
  tokens_out INTEGER NOT NULL,
  rank INTEGER,
  deflated_sharpe REAL,
  test_sharpe REAL,
  test_sharpe_se REAL,
  test_max_drawdown_pct REAL,
  turnover INTEGER,
  fold_sharpe_json TEXT,
  skepticism_json TEXT,
  equity_json TEXT,
  proposals_json TEXT,
  spec_json TEXT
);
"""


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


_USER_ROWS: dict[str, str] = {
    "strategies": "SELECT * FROM strategies WHERE user_id = ?",
    "backtests": "SELECT * FROM backtests WHERE user_id = ?",
    "jobs": "SELECT * FROM jobs WHERE user_id = ?",
    "deployments": "SELECT * FROM deployments WHERE user_id = ?",
    "paper_orders": "SELECT * FROM paper_orders WHERE user_id = ?",
    "proposals": "SELECT * FROM proposals WHERE user_id = ?",
    "user_secrets": "SELECT * FROM user_secrets WHERE user_id = ?",
}


def rows_for_user(conn: sqlite3.Connection, table: str, user_id: str) -> list[sqlite3.Row]:
    query = _USER_ROWS.get(table)
    if query is None:
        raise ValueError(f"unknown table {table}")
    return list(conn.execute(query, (user_id,)))
