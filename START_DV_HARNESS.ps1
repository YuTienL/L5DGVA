param(
  [string]$ProjectRoot = ".",
  [Parameter(Mandatory=$true)][string]$Goal,
  [switch]$Loop
)
$ErrorActionPreference="Stop"
$root=(Resolve-Path $ProjectRoot).Path

Write-Host "============================================================"
Write-Host " DV Agent Harness Edition v15"
Write-Host " Generic Any Subsystem -> Full SoC"
Write-Host "============================================================"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python 3.10+ not found."
}
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
  throw "Claude Code CLI not found."
}

& claude --version
if (Test-Path "$root\.claude\tools\check-claude-dv-env.ps1") {
  & "$root\.claude\tools\check-claude-dv-env.ps1" -ProjectRoot $root
  if ($LASTEXITCODE -eq 2) { throw "Claude/DV environment BLOCKED." }
}

$loopArg = @()
if ($Loop) { $loopArg += "--loop" }

python -m dv_harness --project-root $root start --goal $Goal @loopArg
