param(
  [ValidateSet("LOCAL_ANALYSIS","REMOTE_CONTROL")]
  [string]$Mode="LOCAL_ANALYSIS"
)

if ($Mode -eq "REMOTE_CONTROL") {
    Write-Host "Execution entry: REMOTE CONTROL"
    & "$PSScriptRoot\REMOTE_CONTROL_READINESS.ps1"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & "$PSScriptRoot\REMOTE_CONTROL_START.ps1"
    exit $LASTEXITCODE
}

Write-Host "Execution entry: LOCAL_ANALYSIS"
Write-Host "這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。"
Write-Host "Open Claude Code in this Harness root and start the requested workflow."
