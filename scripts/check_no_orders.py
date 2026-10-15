from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BROKERS = ROOT / "packages" / "brokers" / "src"
BANNED = {"place_order", "cancel_order", "preflight", "replace_order"}


def main() -> None:
    if (BROKERS / "samar_brokers" / "public_live.py").exists():
        raise SystemExit("public_live.py is not part of this build")
    problems: list[str] = []
    for path in BROKERS.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in BANNED:
                problems.append(f"{path}: {node.name}")
    if problems:
        raise SystemExit("\n".join(problems))
    print("no order methods")


if __name__ == "__main__":
    main()
