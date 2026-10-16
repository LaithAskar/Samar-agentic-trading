#!/bin/sh
# Run the working-tree secret scan. CI fails when gitleaks is missing.
# A local machine without the binary gets the install command and continues.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
if ! command -v gitleaks >/dev/null 2>&1; then
  echo "warning: gitleaks is not on PATH, so the secret scan was skipped." >&2
  echo "Install v8.24.3: https://github.com/gitleaks/gitleaks/releases/download/v8.24.3/gitleaks_8.24.3_linux_x64.tar.gz" >&2
  echo "Unpack it and put the gitleaks binary on PATH. CI installs that release and fails the job if it is missing." >&2
  if [ "${CI:-}" = "true" ] || [ "${SAMAR_REQUIRE_GITLEAKS:-}" = "1" ]; then
    exit 1
  fi
  exit 0
fi
gitleaks detect --no-banner --source . --no-git --config .gitleaks.toml
sh scripts/test_gitleaks.sh
