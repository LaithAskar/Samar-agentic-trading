from __future__ import annotations

import os

from samar_api.service import AppState


def main() -> None:
    state = AppState.open(os.environ.get("SAMAR_DB", "data/samar.db"))
    ran = state.run_once()
    print(f"jobs_run={ran}")


if __name__ == "__main__":
    main()
