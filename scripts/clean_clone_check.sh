#!/bin/sh
# Clone HEAD into an empty directory and install there.
# Untracked files and the local database in the original worktree are not visible.
set -eu
root=$(git rev-parse --show-toplevel)
tmp=$(mktemp -d)
cleanup() {
  rm -rf "$tmp"
}
trap cleanup EXIT
git clone --local "$root" "$tmp/samar"
cd "$tmp/samar"
if [ -e data/samar.db ]; then
  echo "local database leaked into the clone" >&2
  exit 1
fi
test -f packages/data/pyproject.toml
test -f packages/data/src/samar_data/market.py
test -f packages/data/src/samar_data/fixtures/AAPL.csv
test -f packages/data/src/samar_data/fixtures/SPY.csv
uv sync --all-packages --group dev
# The pinned manager is pnpm 11.4.0. pnpm 10 ignores allowBuilds and hides this failure.
if ! command -v corepack >/dev/null 2>&1; then
  echo "corepack is required to install pnpm 11.4.0. It ships with Node.js 22." >&2
  exit 1
fi
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
corepack prepare pnpm@11.4.0 --activate
corepack pnpm --version
corepack pnpm install --frozen-lockfile
make verify
