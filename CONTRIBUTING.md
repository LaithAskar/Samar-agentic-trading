# Contributing

Samar is a paper-trading practice app with an optional live path. It is not financial advice. You can lose money. Simulated fills stay inside Samar. Order functions belong only in `apps/api/src/samar_api/live/`. Do not add `public_live.py`.

## Check

```bash
uv sync --all-packages --group dev
corepack enable
corepack prepare pnpm@11.4.0 --activate
pnpm install
make verify
```

`make verify` is the gate. It includes the secret scan when `gitleaks` is on PATH, the lint and type checks, the behavior tests, and the order-path ban. Without `gitleaks`, the local run prints the v8.24.3 install link and continues. CI installs that release and fails if it is missing. CI also runs gitleaks over the full git history. Use pnpm 11.4.0, the version in `packageManager`.

## Keys

Do not commit `.env`, a database, or a provider key. Put keys in Settings. They are encrypted before they are stored.

## Engine

`packages/engine` stays pure. Pass bars and the clock in. Do not import HTTP, the filesystem, or `datetime.now` there.
