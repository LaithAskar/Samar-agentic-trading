.PHONY: verify test lint api web

export PATH := $(HOME)/.local/bin:$(PATH)

verify:
	gitleaks detect --no-banner --source . --no-git --config .gitleaks.toml
	sh scripts/test_gitleaks.sh
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run lint-imports
	uv run python scripts/check_engine_purity.py
	uv run python scripts/check_no_orders.py
	uv run pytest -q
	pnpm -r typecheck
	pnpm -r lint
	pnpm -r test
	node scripts/no_raw_hex.mjs
	uv run python scripts/contracts_check.py

api:
	uv run python -m samar_api

web:
	pnpm --filter web dev
