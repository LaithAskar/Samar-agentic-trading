from __future__ import annotations

import os

import uvicorn

from samar_api.app import create_app


def main() -> None:
    port = int(os.environ.get("SAMAR_API_PORT", "43124"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
