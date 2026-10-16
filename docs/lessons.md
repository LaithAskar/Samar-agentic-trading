# Lessons

| Lesson | Check |
| --- | --- |
| A fill at the signal close is lookahead. | `test_order_fills_at_next_bar_open_not_current_close` |
| Two workers must not double-apply one backtest. | `test_backtest_job_runs_once` |
| An agent draft is not a write. | `test_unapproved_proposal_does_not_write_a_strategy` |
| A brokerage order method stays inside `apps/api/src/samar_api/live/`. | `scripts/check_no_orders.py` |
| A response model must not grow a secret field. | `test_secret_status_schema_has_no_secret_field` |
| The capital cap is total buy exposure, not one order. | `test_capital_cap_totals_exposure_across_buys` |
| The worker and /live/check must not send one order twice. | `test_worker_and_check_cannot_send_the_same_order_twice` |
