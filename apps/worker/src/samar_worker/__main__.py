from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from samar_api.service import AppState


def cycle_once(state: AppState, now: datetime) -> tuple[int, int]:
    jobs = state.run_once()
    live = state.run_live_cycles(now)
    return jobs, live


def main() -> None:
    delay = float(os.environ.get("SAMAR_WORKER_SECONDS", "60"))
    if delay <= 0:
        raise SystemExit("SAMAR_WORKER_SECONDS must be positive")
    state = AppState.open(os.environ.get("SAMAR_DB", "data/samar.db"))
    while True:
        jobs, live = cycle_once(state, datetime.now(UTC))
        print(f"jobs_run={jobs} live_cycles={live}")
        time.sleep(delay)


if __name__ == "__main__":
    main()
