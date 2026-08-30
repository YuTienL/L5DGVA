param(
  [ValidateSet("LOCAL_ANALYSIS","REMOTE_CONTROL")]
  [string]$Mode="LOCAL_ANALYSIS"
)

Write-Host "AI Agent Harness L5 - Ultimate Block/IP -> Full SoC Platform"
Write-Host "============================================================"

if ($Mode -eq "REMOTE_CONTROL") {
    & "$PSScriptRoot\REMOTE_CONTROL_READINESS.ps1"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & "$PSScriptRoot\REMOTE_CONTROL_START.ps1"
    exit $LASTEXITCODE
}

Write-Host "這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。"
Write-Host "Builder family is ready for DUT + Spec + VIP discovery and environment planning."
