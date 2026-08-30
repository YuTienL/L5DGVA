param(
  [string]$ProjectRoot = ".",
  [string]$Request = ""
)
$ErrorActionPreference = "Stop"
$root=(Resolve-Path $ProjectRoot).Path
Write-Host "============================================================"
Write-Host " Generic DE + DV Industrial Workflow - One Click"
Write-Host " Any Subsystem -> Full SoC"
Write-Host "============================================================"

$doctor=Join-Path $root ".claude\tools\check-claude-dv-env.ps1"
if (!(Test-Path $doctor)) { throw "Missing Claude environment doctor: $doctor" }

Write-Host "[1/4] Claude/DV environment readiness..."
& powershell -ExecutionPolicy Bypass -File $doctor -ProjectRoot $root
$doctorCode=$LASTEXITCODE
if ($doctorCode -eq 2) {
  Write-Host "Environment BLOCKED. Fix minimum required dependency first."
  exit 2
}

Write-Host "[2/4] Initialize workflow state..."
$init=Join-Path $root ".claude\tools\init-dv-workflow.ps1"
if (Test-Path $init) {
  & powershell -ExecutionPolicy Bypass -File $init -ProjectRoot $root
}

Write-Host "[3/4] Git preflight..."
if (Test-Path (Join-Path $root ".git")) {
  git -C $root status --short
  git -C $root branch --show-current
  git -C $root rev-parse HEAD
} else {
  Write-Host "No Git repository detected yet; workflow intake will classify this."
}

Write-Host "[4/4] Launch Claude Code..."
$prompt = if ($Request) {
  "/dv-workflow $Request。請先執行 Claude Environment Readiness，然後依 one-click-dv-workflow 完整流程執行；所有 actionable findings 一次修完，完整 re-verify 並重跑原 audit 直到 closure。全程中文。"
} else {
  "/dv-workflow 啟動 one-click-dv-workflow。先做 readiness/intake，再執行 Generic Any Subsystem 到 Full SoC workflow；所有 actionable findings 一次修完，完整 re-verify 並重跑原 audit 直到 closure。全程中文。"
}
Write-Host ""
Write-Host "Claude startup prompt:"
Write-Host $prompt
Write-Host ""
claude --dangerously-skip-permissions $prompt
