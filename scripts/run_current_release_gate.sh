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
script_paths=[p for p,_ in scripts]; style_paths=[p for p,_ in styles]
assert len(script_paths)==len(set(script_paths)), f'duplicate script load: {[p for p in script_paths if script_paths.count(p)>1]}'
assert len(style_paths)==len(set(style_paths)), f'duplicate style load: {[p for p in style_paths if style_paths.count(p)>1]}'
assert html.count('id="engineerFocusBarV089F"')==1
print(f'current assets: {len(scripts)} unique JS / {len(styles)} unique CSS')
PY
if command -v node >/dev/null 2>&1; then
  find motorcad_studio/static -name '*.js' -type f -print | sort | xargs -n 1 -P 8 node --check >/dev/null
fi

TEST_DATA_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/motorcad-studio-current-gate.XXXXXX")
trap 'rm -rf "$TEST_DATA_ROOT"' EXIT HUP INT TERM

echo "[4/5] Current backend/product qualification suite (isolated files + isolated runtime data)"
python scripts/run_pytest_matrix.py --data-root "$TEST_DATA_ROOT/backend" --timeout 75 \
  tests/test_api.py \
  tests/test_mtt_parser.py \
  tests/test_canonical_project_flow_ui.py \
  tests/test_global_product_flow.py \
  tests/test_guided_golden_starters.py \
  tests/test_engineering_semantics_standard_validation.py \
  tests/test_parameter_study_optimization_decision.py \
  tests/test_v088_engineering_closure.py \
  tests/test_v088a_native_semantic_binding_authority.py \
  tests/test_v088b_native_geometry_winding_readback_authority.py \
  tests/test_v088c_validation_fault_tree_native_repair_orchestration.py \
  tests/test_v088d_editor_transaction_convergence_native_state_reconciliation.py \
  tests/test_v088e_native_preview_design_visualization_reconciliation.py \
  tests/test_v088f_native_spatial_geometry_result_overlay_authority.py \
  tests/test_v089a_global_workflow_truth.py \
  tests/test_v089b_full_button_hmi_qualification.py \
  tests/test_v089c_editor_navigation_transaction_hardening.py \
  tests/test_v089d_windows_native_golden_journey_qualification.py \
  tests/test_v089e_ui_soak_recovery_fault_injection_qualification.py \
  tests/test_v089f_engineer_ux_release_candidate_gate.py \
  tests/test_v089g1_global_shell_typography_copy_cleanup.py \
  tests/test_v089g1r_usability_repair.py \
  tests/test_v089g2_action_readiness_dead_end_elimination.py \
  tests/test_runtime_lifecycle_qualification.py \
  tests/test_windows_production_qualification.py \
  tests/test_production_soak_hardening.py

echo "[5/5] Current browser HMI suite (isolated test files)"
python scripts/run_pytest_matrix.py --data-root "$TEST_DATA_ROOT/e2e" --timeout 75 --marker e2e tests/e2e
