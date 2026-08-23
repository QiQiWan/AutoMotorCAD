#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
python -m pytest -q tests
python -m pytest -q -m e2e tests/e2e
