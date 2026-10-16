# Lessons

| Lesson | Check |
| --- | --- |
| A fill at the signal close is lookahead. | `test_order_fills_at_next_bar_open_not_current_close` |
| Two workers must not double-apply one backtest. | `test_backtest_job_runs_once` |
| An agent draft is not a write. | `test_unapproved_proposal_does_not_write_a_strategy` |
| A brokerage order method stays inside `apps/api/src/samar_api/live/`. | `scripts/check_no_orders.py` |
| A response model must not grow a secret field. | `test_secret_status_schema_has_no_secret_field` |
