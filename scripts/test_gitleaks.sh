#!/bin/sh
set -eu
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT
git -C "$tmpdir" init -q
python3 -c 'import secrets; print("token = \"sk-ant-api03-%s\"" % secrets.token_urlsafe(80))' > "$tmpdir/leak.txt"
git -C "$tmpdir" add leak.txt
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
if gitleaks detect --no-banner --source "$tmpdir" --no-git --config "$root/.gitleaks.toml"; then
  echo "gitleaks failed to block a planted key" >&2
  exit 1
fi
echo "gitleaks blocks a planted key"
