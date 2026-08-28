#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
DATA_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/motorcad-studio-long-regression.XXXXXX")
trap 'rm -rf "$DATA_ROOT"' EXIT HUP INT TERM
python scripts/run_pytest_matrix.py --data-root "$DATA_ROOT/backend" --timeout 90 tests
python scripts/run_pytest_matrix.py --data-root "$DATA_ROOT/e2e" --timeout 90 --marker e2e tests/e2e
