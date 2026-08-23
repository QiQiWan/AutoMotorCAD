param(
  [switch]$Install,
  [switch]$ResumeOnly,
  [switch]$LocalOnly,
  [switch]$SkipCancelRetry,
  [int]$Port = 8000,
  [string]$EvidenceRoot = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
if (-not $EvidenceRoot) { $EvidenceRoot = Join-Path $Root ("acceptance_evidence\V087FC-" + (Get-Date -Format "yyyyMMdd-HHmmss")) }
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

& $VenvPython -m pytest -q tests\test_production_soak_hardening.py
if ($LASTEXITCODE -ne 0) { throw "Production soak contract failed" }
& $VenvPython -m pytest -q -m e2e tests\e2e\test_production_soak_hmi.py
if ($LASTEXITCODE -ne 0) { throw "Production soak HMI failed" }

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
    if (-not $proc.WaitForExit(60000)) {
      Stop-Process -Id $proc.Id -Force
      throw "Studio graceful shutdown timed out"
    }
  }
}
function Latest-Runtime-Evidence() {
  $dir = Join-Path $env:MOTORCAD_STUDIO_DATA_DIR "runtime\diagnostics"
  $e = Get-ChildItem -Path $dir -Filter "lifecycle_qualification.json" -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $e) { throw "Runtime Lifecycle evidence missing under runtime\diagnostics" }
  return $e.FullName
}

$Studio = $null
try {
  if ($LocalOnly) {
    $Studio = Start-Studio "local"
    & $VenvPython -m motorcad_studio.acceptance.production_soak --phase local --base-url $BaseUrl --artifact-dir $ArtifactDir --state $StatePath
    if ($LASTEXITCODE -ne 0) { throw "Local control-plane soak failed" }
    Stop-Studio-Gracefully $Studio; $Studio = $null
    Write-Host "Local control-plane 100/500 operation soak completed. This is not formal Motor-CAD production qualification."
    exit 0
  }

  if ($ResumeOnly) {
    if (-not (Test-Path $StatePath)) { throw "ResumeOnly requires existing state.json under EvidenceRoot" }
    $RuntimeEvidence = Latest-Runtime-Evidence
    $Studio = Start-Studio "resume"
    & $VenvPython -m motorcad_studio.acceptance.production_soak --phase resume --formal --licensed-evidence --base-url $BaseUrl --artifact-dir $ArtifactDir --state $StatePath --runtime-lifecycle-evidence $RuntimeEvidence
    if ($LASTEXITCODE -ne 0) { throw "Production soak resume/finalize failed" }
  } else {
    $Studio = Start-Studio "execute"
    $ExecuteArgs = @("-m","motorcad_studio.acceptance.production_soak","--phase","execute","--formal","--licensed-evidence","--base-url",$BaseUrl,"--artifact-dir",$ArtifactDir,"--state",$StatePath)
    if ($SkipCancelRetry) { $ExecuteArgs += "--skip-cancel-retry" }
    & $VenvPython @ExecuteArgs
    if ($LASTEXITCODE -ne 0) { throw "Native 100/500 Case soak failed" }
    Stop-Studio-Gracefully $Studio; $Studio = $null
    $RuntimeEvidence = Latest-Runtime-Evidence
    $RuntimePayload = Get-Content $RuntimeEvidence -Raw | ConvertFrom-Json
    if (-not $RuntimePayload.local_qualified) { throw "Runtime Lifecycle qualification failed after soak shutdown" }
    $Studio = Start-Studio "resume"
    & $VenvPython -m motorcad_studio.acceptance.production_soak --phase resume --formal --licensed-evidence --base-url $BaseUrl --artifact-dir $ArtifactDir --state $StatePath --runtime-lifecycle-evidence $RuntimeEvidence
    if ($LASTEXITCODE -ne 0) { throw "Production soak restart/reopen/finalize failed" }
  }
} finally {
  if ($Studio) { Stop-Studio-Gracefully $Studio }
}
$Final = Get-Content $StatePath -Raw | ConvertFrom-Json
Write-Host "Production soak status: $($Final.status)"
Write-Host "Formal production hardened: $($Final.formal_production_hardened)"
if (-not $Final.formal_production_hardened) {
  Write-Host "Qualification blockers:"
  $Final.qualification_blockers | ForEach-Object { Write-Host " - $_" }
  exit 3
}
exit 0
