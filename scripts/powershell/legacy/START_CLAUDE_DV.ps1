param(
  [string]$ProjectRoot="."
)

$ErrorActionPreference="Stop"
Set-Location (Resolve-Path $ProjectRoot)

Write-Host "啟動 Claude Code DV Workflow..."
Write-Host "模式: --dangerously-skip-permissions"
Write-Host "Coverage 預設: OFF"
Write-Host "驗證流程: PUSH -> BUILD -> VERIFY -> WAVE=1 -> fsdbreport"

claude --dangerously-skip-permissions
