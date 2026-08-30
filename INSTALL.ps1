param([string]$ProjectRoot=".")
$ErrorActionPreference="Stop"
$bundle=Split-Path -Parent $MyInvocation.MyCommand.Path
$src=Join-Path $bundle ".claude"
$dst=Join-Path (Resolve-Path $ProjectRoot).Path ".claude"
if(Test-Path $dst){
 $backup=$dst+".backup."+(Get-Date -Format "yyyyMMdd_HHmmss")
 Copy-Item $dst $backup -Recurse -Force
 Write-Host "Backup: $backup"
}
Copy-Item $src $dst -Recurse -Force
Push-Location $ProjectRoot
try{& ".\.claude\tools\dv-preflight.ps1" -ProjectRoot "."; & ".\.claude\tools\init-dv-workflow.ps1" -ProjectRoot "."}finally{Pop-Location}
Write-Host "`nInstalled. Start Claude Code and run:"
Write-Host '  /dv-workflow <your DV request>'


Write-Host ""
Write-Host "標準啟動方式:"
Write-Host "  .\START_CLAUDE_DV.ps1 -ProjectRoot ."
Write-Host "或:"
Write-Host "  claude --dangerously-skip-permissions"
