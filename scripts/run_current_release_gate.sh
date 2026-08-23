#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

echo "[1/5] Python compile"
python -m compileall -q motorcad_studio scripts tests

echo "[2/5] Clean source contract"
python - <<'PY'
from pathlib import Path
root=Path('.')
assert not (root/'config').exists(), 'duplicate root config must not be shipped'
assert not (root/'docs'/'archive').exists(), 'historical docs archive must not be shipped'
assert not (root/'tests'/'history').exists(), 'historical tests must not be shipped'
assert not list(root.glob('TEST_REPORT_V*.md'))
assert not list(root.glob('V0.*_IMPLEMENTATION_AND_NEXT.md'))
assert not list((root/'scripts').glob('verify_v*'))
assert not list((root/'motorcad_studio'/'static').rglob('*-v0*.js'))
assert not list((root/'motorcad_studio'/'static').rglob('*-v0*.css'))
print('clean source contract: PASS')
PY

echo "[3/5] Current static asset contract"
python - <<'PY'
from pathlib import Path
import re
from motorcad_studio.version import __version__
root=Path('motorcad_studio/static')
html=(root/'index.html').read_text(encoding='utf-8')
scripts=re.findall(r'<script[^>]+src="/static/([^"?]+\.js)\?v=([^"]+)"',html)
styles=re.findall(r'<link[^>]+href="/static/([^"?]+\.css)\?v=([^"]+)"',html)
assert scripts and styles
assert all(v==__version__ for _,v in scripts+styles)
assert all((root/p).is_file() for p,_ in scripts+styles)
print(f'current assets: {len(scripts)} JS / {len(styles)} CSS')
PY
if command -v node >/dev/null 2>&1; then
  find motorcad_studio/static -name '*.js' -type f -print | sort | xargs -n 1 -P 8 node --check >/dev/null
fi

echo "[4/5] Current backend/product qualification suite (isolated files)"
for test_file in \
  tests/test_api.py \
  tests/test_mtt_parser.py \
  tests/test_canonical_project_flow_ui.py \
  tests/test_global_product_flow.py \
  tests/test_guided_golden_starters.py \
  tests/test_engineering_semantics_standard_validation.py \
  tests/test_parameter_study_optimization_decision.py \
  tests/test_v088_engineering_closure.py \
  tests/test_v088a_native_semantic_binding_authority.py \
  tests/test_runtime_lifecycle_qualification.py \
  tests/test_windows_production_qualification.py \
  tests/test_production_soak_hardening.py
do
  echo "  - $test_file"
  python -m pytest -q "$test_file"
done

echo "[5/5] Current browser HMI suite"
python -m pytest -q -m e2e tests/e2e
