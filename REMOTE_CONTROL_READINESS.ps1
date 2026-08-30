$ErrorActionPreference = "Stop"
Write-Host "AI Agent Harness L5 - Remote Control Readiness"
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { Write-Host "[FAIL] claude not found"; exit 2 }
$ver = (& claude --version 2>$null | Out-String).Trim()
Write-Host "[INFO] Claude Code: $ver"
foreach ($p in @(".\CLAUDE.md",".\.claude\skills",".\.dv-harness")) {
  if (-not (Test-Path $p)) { Write-Host "[FAIL] Missing $p"; exit 3 }
}
Write-Host "[PASS] Harness root and core files detected"
Write-Host "Next: .\REMOTE_CONTROL_START.ps1"
