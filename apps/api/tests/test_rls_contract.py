from __future__ import annotations

import re
from pathlib import Path

MIGRATION = Path("supabase/migrations/0001_init.sql")


def test_every_table_enables_rls_and_user_secrets_has_no_authenticated_policy() -> None:
    sql = MIGRATION.read_text()
    tables = re.findall(r"CREATE TABLE (\w+)", sql)
    assert tables == [
        "profiles",
        "paper_accounts",
        "strategies",
        "backtests",
        "paper_orders",
        "paper_positions",
        "deployments",
        "agent_runs",
        "agent_messages",
        "jobs",
        "user_secrets",
        "broker_links",
        "broker_snapshots",
        "audit_log",
    ]
    for table in tables:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in sql
    policies = re.findall(r"CREATE POLICY (\w+) ON (\w+)", sql)
    policy_tables = {table for _name, table in policies}
    assert "user_secrets" not in policy_tables
    assert policy_tables == set(tables) - {"user_secrets"}
