param(
  [switch]$Install,
  [switch]$ResumeOnly,
  [int]$Port = 8000,
  [string]$EvidenceRoot = "",
  [string]$FaultEvidence = "",
  [string]$HumanAcceptanceJson = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
if (-not $EvidenceRoot) { $EvidenceRoot = Join-Path $Root ("acceptance_evidence\V089F-" + (Get-Date -Format "yyyyMMdd-HHmmss")) }
New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$EvidenceRoot = [System.IO.Path]::GetFullPath($EvidenceRoot)
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { py -m venv .venv }
if ($Install) {
  & $VenvPython -m pip install -e ".[e2e,motorcad]"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $VenvPython -m playwright install chromium
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$Gate = @{
  latest_only_frontend = $false
  backend_regression = $false
  baseline_fail_closed = $false
  hmi_regression = $false
  wheel_install_smoke = $false
  runtime_lifecycle_qualification = $false
  native_semantic_authority = $false
  native_model_readback_authority = $false
  native_repair_orchestration_authority = $false
  editor_transaction_reconciliation_authority = $false
  native_preview_visualization_reconciliation_authority = $false
  native_spatial_geometry_result_overlay_authority = $false
  global_workflow_truth = $false
  full_button_hmi_qualification = $false
  editor_navigation_transaction_hardening = $false
  windows_native_golden_journey = $false
  ui_soak_recovery_fault_qualification = $false
  engineer_ux_convergence = $false
  release_candidate_gate = $false
  global_shell_typography_copy_convergence = $false
}
& $VenvPython -m pytest -q tests\test_windows_production_qualification.py
if ($LASTEXITCODE -eq 0) { $Gate.latest_only_frontend = $true } else { throw "Windows production qualification contract failed" }
$RegressionFiles = @(
  "tests\test_runtime_lifecycle_qualification.py",
  "tests\test_parameter_study_optimization_decision.py",
  "tests\test_engineering_semantics_standard_validation.py",
  "tests\test_v088_engineering_closure.py",
  "tests\test_v088a_native_semantic_binding_authority.py",
  "tests\test_v088b_native_geometry_winding_readback_authority.py",
  "tests\test_v088c_validation_fault_tree_native_repair_orchestration.py",
  "tests\test_v088d_editor_transaction_convergence_native_state_reconciliation.py",
  "tests\test_v088e_native_preview_design_visualization_reconciliation.py",
  "tests\test_v088f_native_spatial_geometry_result_overlay_authority.py",
  "tests\test_v089a_global_workflow_truth.py",
  "tests\test_v089b_full_button_hmi_qualification.py",
  "tests\test_v089c_editor_navigation_transaction_hardening.py",
  "tests\test_v089d_windows_native_golden_journey_qualification.py",
  "tests\test_v089e_ui_soak_recovery_fault_injection_qualification.py",
  "tests\test_v089f_engineer_ux_release_candidate_gate.py",
  "tests\test_v089g1_global_shell_typography_copy_cleanup.py"
)
$BackendOK = $true
foreach ($TestFile in $RegressionFiles) {
  if (Test-Path $TestFile) {
    & $VenvPython -m pytest -q $TestFile
    if ($LASTEXITCODE -ne 0) { $BackendOK = $false; break }
  }
}
$Gate.backend_regression = $BackendOK
$Gate.editor_transaction_reconciliation_authority = $BackendOK
$Gate.native_preview_visualization_reconciliation_authority = $BackendOK
$Gate.native_spatial_geometry_result_overlay_authority = $BackendOK
$Gate.global_workflow_truth = $BackendOK
$Gate.full_button_hmi_qualification = $BackendOK
$Gate.editor_navigation_transaction_hardening = $BackendOK
$Gate.engineer_ux_convergence = $BackendOK
$Gate.global_shell_typography_copy_convergence = $BackendOK
if (-not $BackendOK) { throw "current-release backend regression failed" }
& $VenvPython -m pytest -q tests\test_windows_production_qualification.py::test_v088a_release_contract_is_fail_closed_for_missing_semantic_authority tests\test_windows_production_qualification.py::test_v088b_release_contract_is_fail_closed_for_missing_native_model_readback tests\test_windows_production_qualification.py::test_v088c_release_contract_is_fail_closed_for_missing_repair_orchestration_authority tests\test_windows_production_qualification.py::test_v088d_release_contract_is_fail_closed_for_missing_editor_transaction_reconciliation_authority tests\test_windows_production_qualification.py::test_v088e_release_contract_is_fail_closed_for_missing_native_preview_visualization_reconciliation_authority tests\test_windows_production_qualification.py::test_v088f_release_contract_is_fail_closed_for_missing_native_spatial_geometry_result_overlay_authority
if ($LASTEXITCODE -eq 0) { $Gate.baseline_fail_closed = $true } else { throw "baseline fail-closed gate failed" }
& $VenvPython -m pytest -q -m e2e tests\e2e\test_windows_production_qualification_hmi.py tests\e2e\test_v089d_windows_native_golden_journey_hmi.py tests\e2e\test_v089e_ui_soak_recovery_fault_injection_hmi.py tests\e2e\test_v089f_engineer_ux_release_candidate_hmi.py tests\e2e\test_v089g1_global_shell_typography_copy_cleanup_hmi.py
if ($LASTEXITCODE -eq 0) { $Gate.hmi_regression = $true } else { throw "Windows production qualification HMI gate failed" }

$ExpectedStudioVersion = ((Select-String -Path (Join-Path $Root "pyproject.toml") -Pattern '^version = "([^"]+)"$').Matches[0].Groups[1].Value)
$WheelDir = Join-Path $EvidenceRoot "wheel"
New-Item -ItemType Directory -Force -Path $WheelDir | Out-Null
& $VenvPython -m pip wheel $Root --no-deps --no-build-isolation -w $WheelDir
if ($LASTEXITCODE -ne 0) { throw "Production qualification wheel build failed" }
$Wheel = Get-ChildItem -Path $WheelDir -Filter ("motorcad_studio_mvp-{0}-*.whl" -f $ExpectedStudioVersion) | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Wheel) { throw "Production qualification wheel artifact not found" }
& $VenvPython -m pip install --force-reinstall --no-deps $Wheel.FullName
if ($LASTEXITCODE -ne 0) { throw "Production qualification wheel install failed" }
$env:MOTORCAD_STUDIO_ACCEPTANCE_SOURCE_ROOT = $Root
$env:MOTORCAD_STUDIO_ACCEPTANCE_EXPECTED_VERSION = $ExpectedStudioVersion
Push-Location $EvidenceRoot
try {
  & $VenvPython -c 'from pathlib import Path; import os,motorcad_studio; from motorcad_studio.version import __version__; f=Path(motorcad_studio.__file__).resolve(); root=Path(os.environ["MOTORCAD_STUDIO_ACCEPTANCE_SOURCE_ROOT"]).resolve(); assert __version__==os.environ["MOTORCAD_STUDIO_ACCEPTANCE_EXPECTED_VERSION"]; assert root not in f.parents; print(f)'
  if ($LASTEXITCODE -ne 0) { throw "installed-wheel neutral-directory import failed" }
  $Gate.wheel_install_smoke = $true
} finally { Pop-Location }

$GatePath = Join-Path $EvidenceRoot "release_gates.json"
$Gate | ConvertTo-Json | Set-Content -Encoding UTF8 $GatePath
$env:MOTORCAD_STUDIO_DATA_DIR = Join-Path $EvidenceRoot "runtime_data"
$env:MOTORCAD_STUDIO_ENABLE_MOCK = "false"
$env:MOTORCAD_STUDIO_DEFAULT_SOLVER = "motorcad"
$env:MOTORCAD_STUDIO_MOTORCAD_VERSION = "2026R1"
$env:PYTHONUNBUFFERED = "1"
$BaseUrl = "http://127.0.0.1:$Port"
$StatePath = Join-Path $EvidenceRoot "state.json"
$ArtifactDir = Join-Path $EvidenceRoot "evidence"
$GoldenJourneyArtifactDir = Join-Path $EvidenceRoot "golden_journey_evidence"
$GoldenJourneyResult = Join-Path $GoldenJourneyArtifactDir "v089d_qualification_result.json"
$ProductionSoakStatePath = Join-Path $EvidenceRoot "production_soak_state.json"
$ProductionSoakArtifactDir = Join-Path $EvidenceRoot "production_soak_evidence"
$UISoakArtifactDir = Join-Path $EvidenceRoot "ui_soak_evidence"
$UISoakResult = Join-Path $UISoakArtifactDir "v089e_qualification_result.json"
$StartCount = 0

function Start-Studio([string]$PhaseName) {
  $script:StartCount += 1
  $StopFile = Join-Path $EvidenceRoot ("studio.{0}.{1}.stop" -f $script:StartCount,$PhaseName)
  if (Test-Path $StopFile) { Remove-Item $StopFile -Force }
  $Stdout = Join-Path $EvidenceRoot ("studio.{0}.{1}.stdout.log" -f $script:StartCount,$PhaseName)
  $Stderr = Join-Path $EvidenceRoot ("studio.{0}.{1}.stderr.log" -f $script:StartCount,$PhaseName)
  $ServerScript = Join-Path $Root "scripts\run_acceptance_server.py"
  $proc = Start-Process -FilePath $VenvPython -ArgumentList @($ServerScript,"--host","127.0.0.1","--port",$Port,"--stop-file",$StopFile) -WorkingDirectory $EvidenceRoot -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr -PassThru
  for ($i=0; $i -lt 120; $i++) {
    Start-Sleep -Seconds 1
    try { $h = Invoke-RestMethod -Uri "$BaseUrl/api/health" -TimeoutSec 5; if ($h.status -eq "ok") { return @{ Process=$proc; StopFile=$StopFile } } } catch {}
    if ($proc.HasExited) { throw "Studio exited during startup. See $Stderr" }
  }
  try { Stop-Process -Id $proc.Id -Force } catch {}
  throw "Studio did not become ready"
}
function Stop-Studio-Gracefully($Handle) {
  if (-not $Handle) { return }
  $proc = $Handle.Process
  if ($proc -and -not $proc.HasExited) {
    New-Item -ItemType File -Force -Path $Handle.StopFile | Out-Null
    if (-not $proc.WaitForExit(45000)) {
      Stop-Process -Id $proc.Id -Force
      throw "Studio graceful shutdown timed out"
    }
  }
}


function Invoke-GoldenJourneyQualification {
  New-Item -ItemType Directory -Force -Path $GoldenJourneyArtifactDir | Out-Null
  $JourneyArgs = @("-m","motorcad_studio.acceptance.windows_golden_journey","--formal","--base-url",$BaseUrl,"--artifact-dir",$GoldenJourneyArtifactDir,"--release-gates",$GatePath)
  Push-Location $EvidenceRoot
  try { & $VenvPython @JourneyArgs } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw "V0.89-D live UI Golden Journey qualification failed" }
  if (-not (Test-Path $GoldenJourneyResult)) { throw "V0.89-D qualification result evidence missing" }
  $Golden = Get-Content $GoldenJourneyResult -Raw | ConvertFrom-Json
  if (-not $Golden.imported.run.formal_workstation_qualified) {
    Write-Host "V0.89-D qualification blockers:"
    $Golden.imported.run.qualification_blockers | ForEach-Object { Write-Host " - $_" }
    throw "V0.89-D formal workstation qualification did not pass"
  }
  $script:Gate.windows_native_golden_journey = $true
  $script:Gate | ConvertTo-Json | Set-Content -Encoding UTF8 $script:GatePath
}


function Invoke-NativeProductionSoakQualification {
  if (Test-Path $ProductionSoakStatePath) {
    try {
      $ExistingSoak = Get-Content $ProductionSoakStatePath -Raw | ConvertFrom-Json
      if ($ExistingSoak.formal_production_hardened) {
        Write-Host "V0.87-F-C Native 100/500 Case soak already qualified in this evidence root."
        return
      }
    } catch {}
  }
  New-Item -ItemType Directory -Force -Path $ProductionSoakArtifactDir | Out-Null
  $handle = Start-Studio "native-soak-execute"
  try {
    Push-Location $EvidenceRoot
    try { & $VenvPython -m motorcad_studio.acceptance.production_soak --phase execute --formal --licensed-evidence --base-url $BaseUrl --artifact-dir $ProductionSoakArtifactDir --state $ProductionSoakStatePath } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Native 100/500 Case soak execute phase failed" }
  } finally { Stop-Studio-Gracefully $handle }
  $RuntimeEvidence = Get-ChildItem -Path (Join-Path $env:MOTORCAD_STUDIO_DATA_DIR "runtime\diagnostics") -Filter "lifecycle_qualification.json" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $RuntimeEvidence) { throw "Runtime Lifecycle evidence missing after Native soak shutdown" }
  $RuntimePayload = Get-Content $RuntimeEvidence.FullName -Raw | ConvertFrom-Json
  if (-not $RuntimePayload.local_qualified) { throw "Runtime Lifecycle qualification failed after Native soak shutdown" }
  $handle = Start-Studio "native-soak-resume"
  try {
    Push-Location $EvidenceRoot
    try { & $VenvPython -m motorcad_studio.acceptance.production_soak --phase resume --formal --licensed-evidence --base-url $BaseUrl --artifact-dir $ProductionSoakArtifactDir --state $ProductionSoakStatePath --runtime-lifecycle-evidence $RuntimeEvidence.FullName } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Native 100/500 Case soak resume/finalize failed" }
  } finally { Stop-Studio-Gracefully $handle }
  $Soak = Get-Content $ProductionSoakStatePath -Raw | ConvertFrom-Json
  if (-not $Soak.formal_production_hardened) {
    Write-Host "Native production soak blockers:"
    $Soak.qualification_blockers | ForEach-Object { Write-Host " - $_" }
    throw "Native 100/500 Case production soak did not formally qualify"
  }
}

function Invoke-UISoakRecoveryQualification {
  New-Item -ItemType Directory -Force -Path $UISoakArtifactDir | Out-Null
  $handle = Start-Studio "ui-soak"
  try {
    Push-Location $EvidenceRoot
    try { & $VenvPython -m motorcad_studio.acceptance.ui_soak_recovery --formal --base-url $BaseUrl --artifact-dir $UISoakArtifactDir --release-gates $GatePath } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "V0.89-E UI Soak / Recovery / Fault Injection qualification failed" }
  } finally { Stop-Studio-Gracefully $handle }
  if (-not (Test-Path $UISoakResult)) { throw "V0.89-E qualification result evidence missing" }
  $UIFinal = Get-Content $UISoakResult -Raw | ConvertFrom-Json
  if (-not $UIFinal.imported.run.formal_ui_resilience_qualified) {
    Write-Host "V0.89-E qualification blockers:"
    $UIFinal.imported.run.qualification_blockers | ForEach-Object { Write-Host " - $_" }
    throw "V0.89-E formal UI resilience qualification did not pass"
  }
  $script:Gate.ui_soak_recovery_fault_qualification = $true
  $script:Gate | ConvertTo-Json | Set-Content -Encoding UTF8 $script:GatePath
}

$FaultEvidenceSupplied = -not [string]::IsNullOrWhiteSpace($FaultEvidence)
if (-not $FaultEvidence) {
  $FaultEvidence = Join-Path $EvidenceRoot "fault_evidence.json"
  if (-not (Test-Path $FaultEvidence)) {
    & $VenvPython (Join-Path $Root "scripts\init_production_fault_matrix.py") $FaultEvidence
    Write-Host "Fault matrix initialized at $FaultEvidence"
  }
}

$Studio = $null
try {
  if ($ResumeOnly) {
    if (-not (Test-Path $StatePath)) { throw "ResumeOnly requires existing state.json under EvidenceRoot" }
    if (-not (Test-Path $FaultEvidence)) { throw "ResumeOnly requires a fault evidence matrix" }
    $RuntimeEvidence = Get-ChildItem -Path (Join-Path $env:MOTORCAD_STUDIO_DATA_DIR "runtime\diagnostics") -Filter "lifecycle_qualification.json" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $RuntimeEvidence) { throw "ResumeOnly cannot find Runtime Lifecycle evidence under runtime\diagnostics" }
    $RuntimeEvidence = $RuntimeEvidence.FullName
    $RuntimePayload = Get-Content $RuntimeEvidence -Raw | ConvertFrom-Json
    if (-not $RuntimePayload.local_qualified) { throw "Runtime lifecycle qualification failed before resume" }
    $Gate.runtime_lifecycle_qualification = $true
    $Gate | ConvertTo-Json | Set-Content -Encoding UTF8 $GatePath
    $Studio = Start-Studio "resume"
    $ResumeArgs = @("-m","motorcad_studio.acceptance.windows_production","--phase","resume","--formal","--licensed-evidence","--base-url",$BaseUrl,"--artifact-dir",$ArtifactDir,"--state",$StatePath,"--release-gates",$GatePath,"--fault-evidence",[System.IO.Path]::GetFullPath($FaultEvidence),"--runtime-lifecycle-evidence",$RuntimeEvidence)
    Push-Location $EvidenceRoot
    try { & $VenvPython @ResumeArgs } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Production qualification resume/finalize phase failed" }
    Invoke-GoldenJourneyQualification
  } else {
  $Studio = Start-Studio "execute"
  Push-Location $EvidenceRoot
  try { & $VenvPython -m motorcad_studio.acceptance.windows_production --phase preflight --formal --licensed-evidence --base-url $BaseUrl --artifact-dir $ArtifactDir --state $StatePath --release-gates $GatePath } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw "Windows/Motor-CAD/PyMotorCAD preflight failed" }
  Push-Location $EvidenceRoot
  try { & $VenvPython -m motorcad_studio.acceptance.windows_production --phase execute --formal --licensed-evidence --base-url $BaseUrl --artifact-dir $ArtifactDir --state $StatePath --release-gates $GatePath } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw "Production qualification execute phase failed" }
  Stop-Studio-Gracefully $Studio
  $Studio = $null
  $RuntimeEvidence = Get-ChildItem -Path (Join-Path $env:MOTORCAD_STUDIO_DATA_DIR "runtime\diagnostics") -Filter "lifecycle_qualification.json" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $RuntimeEvidence) { throw "Runtime lifecycle shutdown evidence missing under runtime\diagnostics" }
  $RuntimeEvidence = $RuntimeEvidence.FullName
  $RuntimePayload = Get-Content $RuntimeEvidence -Raw | ConvertFrom-Json
  if (-not $RuntimePayload.local_qualified) { throw "Runtime lifecycle qualification failed after execute shutdown" }
  $Gate.runtime_lifecycle_qualification = $true
  $Gate | ConvertTo-Json | Set-Content -Encoding UTF8 $GatePath

  if (-not $FaultEvidenceSupplied) {
    Write-Host "Production qualification execute phase completed and Runtime Lifecycle evidence is frozen."
    Write-Host "Attach observed evidence to: $FaultEvidence"
    Write-Host "Then resume without repeating native scenarios:"
    Write-Host ("  .\run_windows_production_qualification.ps1 -ResumeOnly -EvidenceRoot `"{0}`" -FaultEvidence `"{1}`"" -f $EvidenceRoot,$FaultEvidence)
    exit 4
  }

  $Studio = Start-Studio "resume"
  $ResumeArgs = @("-m","motorcad_studio.acceptance.windows_production","--phase","resume","--formal","--licensed-evidence","--base-url",$BaseUrl,"--artifact-dir",$ArtifactDir,"--state",$StatePath,"--release-gates",$GatePath,"--fault-evidence",[System.IO.Path]::GetFullPath($FaultEvidence),"--runtime-lifecycle-evidence",$RuntimeEvidence)
  Push-Location $EvidenceRoot
  try { & $VenvPython @ResumeArgs } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw "Production qualification resume/finalize phase failed" }
  Invoke-GoldenJourneyQualification
  }
} finally {
  if ($Studio) { Stop-Studio-Gracefully $Studio }
}
# V0.89-E overlays Native production soak and live UI resilience qualification on the same runtime data authority.
Invoke-NativeProductionSoakQualification
Invoke-UISoakRecoveryQualification

$Final = Get-Content $StatePath -Raw | ConvertFrom-Json
Write-Host "V0.88-F Native production qualification status: $($Final.status)"
Write-Host "V0.88-F formal Native workstation qualified: $($Final.formal_workstation_qualified)"
if (-not $Final.formal_workstation_qualified) {
  Write-Host "V0.88-F qualification blockers:"
  $Final.qualification_blockers | ForEach-Object { Write-Host " - $_" }
  exit 3
}
if (-not (Test-Path $GoldenJourneyResult)) { Write-Host "V0.89-D Golden Journey result is missing"; exit 3 }
$GoldenFinal = Get-Content $GoldenJourneyResult -Raw | ConvertFrom-Json
Write-Host "V0.89-D UI Golden Journeys: $($GoldenFinal.journey_passed)/$($GoldenFinal.journey_required)"
Write-Host "V0.89-D formal workstation qualified: $($GoldenFinal.imported.run.formal_workstation_qualified)"
if (-not $GoldenFinal.imported.run.formal_workstation_qualified) {
  $GoldenFinal.imported.run.qualification_blockers | ForEach-Object { Write-Host " - $_" }
  exit 3
}
if (-not (Test-Path $UISoakResult)) { Write-Host "V0.89-E UI soak result is missing"; exit 3 }
$UIFinal = Get-Content $UISoakResult -Raw | ConvertFrom-Json
Write-Host "V0.89-E UI resilience formally qualified: $($UIFinal.imported.run.formal_ui_resilience_qualified)"
Write-Host "V0.89-E UI evidence coverage: $($UIFinal.imported.run.coverage.coverage_percent)%"
if (-not $UIFinal.imported.run.formal_ui_resilience_qualified) {
  $UIFinal.imported.run.qualification_blockers | ForEach-Object { Write-Host " - $_" }
  exit 3
}
$RCResult = Join-Path $EvidenceRoot "v089f_release_candidate_gate.json"
$RCArgs = @((Join-Path $Root "scripts\evaluate_release_candidate.py"), "--output", $RCResult)
if ($HumanAcceptanceJson) {
  $RCArgs += @("--human-acceptance", [System.IO.Path]::GetFullPath($HumanAcceptanceJson), "--require-formal")
}
& $VenvPython @RCArgs
$RCExit = $LASTEXITCODE
if (-not (Test-Path $RCResult)) { Write-Host "V0.89-F RC Gate result is missing"; exit 3 }
$RCFinal = Get-Content $RCResult -Raw | ConvertFrom-Json
Write-Host "V0.89-F local RC ready: $($RCFinal.summary.local_rc_ready)"
Write-Host "V0.89-F formal RC qualified: $($RCFinal.summary.formal_rc_qualified)"
if (-not $HumanAcceptanceJson) {
  Write-Host "Formal RC still requires the 12-item engineer human acceptance checklist."
  Write-Host "Template: motorcad_studio\acceptance\rc_human_acceptance_checklist.json"
  Write-Host "Re-run with -HumanAcceptanceJson <completed-json> to freeze formal RC sign-off."
  exit 5
}
if ($RCExit -ne 0 -or -not $RCFinal.summary.formal_rc_qualified) {
  $RCFinal.summary.formal_blockers | ForEach-Object { Write-Host " - $_" }
  exit 5
}
$Gate.release_candidate_gate = $true
$Gate | ConvertTo-Json | Set-Content -Encoding UTF8 $GatePath
exit 0
