$ErrorActionPreference = "Stop"
& "$PSScriptRoot\REMOTE_CONTROL_READINESS.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$stateDir = Join-Path $PSScriptRoot ".dv-harness\remote-control"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
@{
  state="STARTING"
  host=$env:COMPUTERNAME
  working_directory=(Get-Location).Path
  started_at=(Get-Date).ToString("o")
  remote_control_enabled=$true
} | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $stateDir "session.json")
Write-Host "Starting Claude Code Remote Control..."
Write-Host "LOCAL_ANALYSIS = local files only; no server/VCS."
Write-Host "REMOTE_EXECUTION = server/build/simulation only after explicit mode declaration."
& claude remote-control
