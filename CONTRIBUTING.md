# Contributing

Samar is a paper-trading practice app with an optional live path. It is not financial advice. You can lose money. Simulated fills stay inside Samar. Order functions belong only in `apps/api/src/samar_api/live/`. Do not add `public_live.py`.

## Check

```bash
uv sync --all-packages --group dev
pnpm install
make verify
```

`make verify` is the gate. It includes gitleaks on the working tree, the lint and type checks, the behavior tests, and the order-path ban. CI runs that command and also runs gitleaks over the full git history.

## Keys

Do not commit `.env`, a database, or a provider key. Put keys in Settings. They are encrypted before they are stored.

## Engine

`packages/engine` stays pure. Pass bars and the clock in. Do not import HTTP, the filesystem, or `datetime.now` there.
