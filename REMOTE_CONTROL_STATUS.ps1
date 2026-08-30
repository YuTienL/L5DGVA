$root=$PSScriptRoot
Write-Host "AI Agent Harness L5 - Remote Control Status"
$session=Join-Path $root ".dv-harness\remote-control\session.json"
if (Test-Path $session) { Get-Content $session }
$manifest=Join-Path $root "WORKFLOW_MANIFEST.json"
if (Test-Path $manifest) {
  $m=Get-Content $manifest -Raw | ConvertFrom-Json
  Write-Host "Iron Rules: $($m.iron_rules_count)"
  Write-Host "Skills: $($m.skills)"
}
