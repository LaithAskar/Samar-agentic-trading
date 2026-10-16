from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "apps" / "api" / "src" / "samar_api" / "live"
BANNED = {"place_order", "cancel_order", "preflight", "replace_order"}
SKIP = {".venv", "node_modules", ".git"}


def main() -> None:
    problems: list[str] = []
    for path in ROOT.rglob("*.py"):
        if set(path.parts) & SKIP:
            continue
        if path.name == "public_live.py":
            problems.append(f"{path}: public_live.py is not part of this build")
            continue
        if path == LIVE or LIVE in path.parents:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in BANNED:
                problems.append(f"{path}: {node.name}")
    if problems:
        raise SystemExit("\n".join(problems))
    print("orders only in samar_api.live")


if __name__ == "__main__":
    main()
