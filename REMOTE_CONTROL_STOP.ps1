$state=Join-Path $PSScriptRoot ".dv-harness\remote-control\session.json"
if (Test-Path $state) {
  $d=Get-Content $state -Raw | ConvertFrom-Json
  $d.state="STOPPED"
  $d.last_status_update=(Get-Date).ToString("o")
  $d.remote_control_enabled=$false
  $d | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $state
}
Write-Host "Remote Control state marked STOPPED."
