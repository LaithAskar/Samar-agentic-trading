from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages" / "engine" / "src"
BANNED_MODULES = {"yfinance", "requests", "httpx", "urllib", "sqlite3", "os"}
BANNED_CALLS = {("datetime", "now"), ("datetime", "utcnow")}


def main() -> None:
    problems: list[str] = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in BANNED_MODULES:
                        problems.append(f"{path}: import {alias.name}")
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in BANNED_MODULES:
                    problems.append(f"{path}: from {node.module}")
                if node.module == "os" or node.module.startswith("os."):
                    problems.append(f"{path}: os import")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if (node.value.id, node.attr) in BANNED_CALLS:
                    problems.append(f"{path}: {node.value.id}.{node.attr}")
    if problems:
        raise SystemExit("\n".join(problems))
    print("engine purity ok")


if __name__ == "__main__":
    main()
