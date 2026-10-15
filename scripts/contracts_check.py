from __future__ import annotations

from pathlib import Path

from samar_contracts.models import BacktestView, SecretStatus, StrategyView

ROOT = Path(__file__).resolve().parents[1]
TS = (ROOT / "apps/web/src/lib/contracts.ts").read_text()


def main() -> None:
    missing: list[str] = []
    for model in (StrategyView, BacktestView, SecretStatus):
        for name in model.model_fields:
            if name not in TS:
                missing.append(f"{model.__name__}.{name}")
    secret_fields = set(SecretStatus.model_fields)
    if secret_fields != {"kind", "last4", "status", "validated_at"}:
        missing.append("SecretStatus gained a field")
    if missing:
        raise SystemExit("contracts drift: " + ", ".join(missing))
    print("contracts ok")


if __name__ == "__main__":
    main()
