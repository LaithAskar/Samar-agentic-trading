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
  created_at TEXT NOT NULL,
  data_label TEXT NOT NULL DEFAULT 'SYNTHETIC DATA'
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
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL DEFAULT ''
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
  created_at TEXT NOT NULL,
  train_start TEXT NOT NULL DEFAULT '',
  train_end TEXT NOT NULL DEFAULT '',
  test_start TEXT NOT NULL DEFAULT '',
  test_end TEXT NOT NULL DEFAULT '',
  data_label TEXT NOT NULL DEFAULT 'SYNTHETIC DATA'
);
CREATE TABLE IF NOT EXISTS live_settings (
  user_id TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 0,
  mode TEXT NOT NULL DEFAULT 'approve',
  capital_cap REAL NOT NULL DEFAULT 200,
  max_order_dollars REAL NOT NULL DEFAULT 200,
  max_orders_per_day INTEGER DEFAULT 4,
  max_orders_per_minute INTEGER NOT NULL DEFAULT 2,
  daily_loss_stop REAL NOT NULL DEFAULT 50,
  permission TEXT NOT NULL DEFAULT 'unknown',
  source TEXT NOT NULL DEFAULT 'off',
  strategy_id TEXT NOT NULL DEFAULT '',
  model_provider TEXT NOT NULL DEFAULT '',
  model_name TEXT NOT NULL DEFAULT '',
  reject_streak INTEGER NOT NULL DEFAULT 0,
  halted_reason TEXT NOT NULL DEFAULT '',
  day_pnl REAL NOT NULL DEFAULT 0,
  day_key TEXT NOT NULL DEFAULT '',
  day_start_equity REAL,
  buying_power REAL,
  settled_cash REAL,
  account_id TEXT NOT NULL DEFAULT '',
  positions_json TEXT NOT NULL DEFAULT '[]',
  equity REAL
);
CREATE TABLE IF NOT EXISTS live_tickets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty INTEGER NOT NULL,
  limit_price REAL NOT NULL,
  est_cost REAL NOT NULL,
  reason TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,
  order_id TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS live_orders (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  ticket_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty INTEGER NOT NULL,
  limit_price REAL NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS live_audit (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  at TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL
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
    _migrate_live_settings(conn)
    _migrate_result_labels(conn)
    _migrate_sessions(conn)
    return conn


def _migrate_result_labels(conn: sqlite3.Connection) -> None:
    _add_column(
        conn,
        "backtests",
        "data_label",
        "ALTER TABLE backtests ADD COLUMN data_label TEXT NOT NULL DEFAULT 'SYNTHETIC DATA'",
    )
    _add_column(
        conn,
        "arena_runs",
        "train_start",
        "ALTER TABLE arena_runs ADD COLUMN train_start TEXT NOT NULL DEFAULT ''",
    )
    _add_column(
        conn,
        "arena_runs",
        "train_end",
        "ALTER TABLE arena_runs ADD COLUMN train_end TEXT NOT NULL DEFAULT ''",
    )
    _add_column(
        conn,
        "arena_runs",
        "test_start",
        "ALTER TABLE arena_runs ADD COLUMN test_start TEXT NOT NULL DEFAULT ''",
    )
    _add_column(
        conn,
        "arena_runs",
        "test_end",
        "ALTER TABLE arena_runs ADD COLUMN test_end TEXT NOT NULL DEFAULT ''",
    )
    _add_column(
        conn,
        "arena_runs",
        "data_label",
        "ALTER TABLE arena_runs ADD COLUMN data_label TEXT NOT NULL DEFAULT 'SYNTHETIC DATA'",
    )
    conn.commit()


def _migrate_sessions(conn: sqlite3.Connection) -> None:
    names = {str(row["name"]) for row in conn.execute("PRAGMA table_info(sessions)")}
    if "expires_at" not in names:
        conn.execute("ALTER TABLE sessions ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE sessions SET expires_at = datetime(created_at, '+30 days') WHERE expires_at = ''")
        conn.commit()


def _add_column(conn: sqlite3.Connection, table: str, column: str, statement: str) -> None:
    if table == "backtests":
        rows = conn.execute("PRAGMA table_info(backtests)")
    elif table == "arena_runs":
        rows = conn.execute("PRAGMA table_info(arena_runs)")
    else:
        raise ValueError(table)
    names = {str(row["name"]) for row in rows}
    if column not in names:
        conn.execute(statement)


def _migrate_live_settings(conn: sqlite3.Connection) -> None:
    info = list(conn.execute("PRAGMA table_info(live_settings)"))
    if not info:
        return
    names = {str(row["name"]) for row in info}
    if "max_orders_per_minute" not in names:
        conn.execute("ALTER TABLE live_settings ADD COLUMN max_orders_per_minute INTEGER NOT NULL DEFAULT 2")
    if "settled_cash" not in names:
        conn.execute("ALTER TABLE live_settings ADD COLUMN settled_cash REAL")
    info = list(conn.execute("PRAGMA table_info(live_settings)"))
    cap = next(row for row in info if row["name"] == "max_orders_per_day")
    if int(cap["notnull"]) == 0:
        conn.commit()
        return
    conn.execute("ALTER TABLE live_settings RENAME TO live_settings_old")
    conn.executescript(
        """
        CREATE TABLE live_settings (
          user_id TEXT PRIMARY KEY,
          enabled INTEGER NOT NULL DEFAULT 0,
          mode TEXT NOT NULL DEFAULT 'approve',
          capital_cap REAL NOT NULL DEFAULT 200,
          max_order_dollars REAL NOT NULL DEFAULT 200,
          max_orders_per_day INTEGER DEFAULT 4,
          max_orders_per_minute INTEGER NOT NULL DEFAULT 2,
          daily_loss_stop REAL NOT NULL DEFAULT 50,
          permission TEXT NOT NULL DEFAULT 'unknown',
          source TEXT NOT NULL DEFAULT 'off',
          strategy_id TEXT NOT NULL DEFAULT '',
          model_provider TEXT NOT NULL DEFAULT '',
          model_name TEXT NOT NULL DEFAULT '',
          reject_streak INTEGER NOT NULL DEFAULT 0,
          halted_reason TEXT NOT NULL DEFAULT '',
          day_pnl REAL NOT NULL DEFAULT 0,
          day_key TEXT NOT NULL DEFAULT '',
          day_start_equity REAL,
          buying_power REAL,
          settled_cash REAL,
          account_id TEXT NOT NULL DEFAULT '',
          positions_json TEXT NOT NULL DEFAULT '[]',
          equity REAL
        );
        INSERT INTO live_settings (
          user_id, enabled, mode, capital_cap, max_order_dollars, max_orders_per_day,
          max_orders_per_minute, daily_loss_stop, permission, source, strategy_id,
          model_provider, model_name, reject_streak, halted_reason, day_pnl, day_key,
          day_start_equity, buying_power, settled_cash, account_id, positions_json, equity
        )
        SELECT
          user_id, enabled, mode, capital_cap, max_order_dollars, max_orders_per_day,
          max_orders_per_minute, daily_loss_stop, permission, source, strategy_id,
          model_provider, model_name, reject_streak, halted_reason, day_pnl, day_key,
          day_start_equity, buying_power, settled_cash, account_id, positions_json, equity
        FROM live_settings_old;
        DROP TABLE live_settings_old;
        """
    )
    conn.commit()


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
