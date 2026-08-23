param(
  [switch]$Install,
  [switch]$ResumeOnly,
  [int]$Port = 8000,
  [string]$EvidenceRoot = "",
  [string]$FaultEvidence = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
if (-not $EvidenceRoot) { $EvidenceRoot = Join-Path $Root ("acceptance_evidence\V088A-" + (Get-Date -Format "yyyyMMdd-HHmmss")) }
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
}
& $VenvPython -m pytest -q tests\test_windows_production_qualification.py
if ($LASTEXITCODE -eq 0) { $Gate.latest_only_frontend = $true } else { throw "Windows production qualification contract failed" }
$RegressionFiles = @(
  "tests\test_runtime_lifecycle_qualification.py",
  "tests\test_parameter_study_optimization_decision.py",
  "tests\test_engineering_semantics_standard_validation.py",
  "tests\test_v088_engineering_closure.py",
  "tests\test_v088a_native_semantic_binding_authority.py"
)
$BackendOK = $true
foreach ($TestFile in $RegressionFiles) {
  if (Test-Path $TestFile) {
    & $VenvPython -m pytest -q $TestFile
    if ($LASTEXITCODE -ne 0) { $BackendOK = $false; break }
  }
}
$Gate.backend_regression = $BackendOK
if (-not $BackendOK) { throw "current-release backend regression failed" }
& $VenvPython -m pytest -q tests\test_windows_production_qualification.py::test_v088a_release_contract_is_fail_closed_for_missing_semantic_authority
if ($LASTEXITCODE -eq 0) { $Gate.baseline_fail_closed = $true } else { throw "baseline fail-closed gate failed" }
& $VenvPython -m pytest -q -m e2e tests\e2e\test_windows_production_qualification_hmi.py
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
  }
} finally {
  if ($Studio) { Stop-Studio-Gracefully $Studio }
}
$Final = Get-Content $StatePath -Raw | ConvertFrom-Json
Write-Host "Production qualification status: $($Final.status)"
Write-Host "Formal workstation qualified: $($Final.formal_workstation_qualified)"
if (-not $Final.formal_workstation_qualified) {
  Write-Host "Qualification blockers:"
  $Final.qualification_blockers | ForEach-Object { Write-Host " - $_" }
  exit 3
}
exit 0
