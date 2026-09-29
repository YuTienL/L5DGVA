# PreToolUse guard for the 3-tier context budget (2026-09-03).
#
# Closes the gap block-destructive.ps1 never covered: that hook matches only
# Bash|PowerShell and only inspects the command for DESTRUCTIVE patterns --
# it never fires on Read and never looks at WHAT is being read. So nothing
# stopped an agent pulling VIP source full text, a raw user-guide PDF, a
# whole-chip/waveform/evidence database, or a complete regression log into
# context, even though the MCP fixed-verb interface (dv_harness/mcp) exists
# precisely to answer those questions cheaply.
#
# All policy lives in dv_harness/context_budget.policy.json; all logic lives
# in dv_harness/context_budget.py. This file is a transport only: hook JSON
# in on stdin, deny JSON out on stdout, nothing on an allow.
#
# FAIL-OPEN, on purpose: if python is unavailable or the module errors, this
# exits 0 silently. A context budget that bricks every Read the moment an
# interpreter moves is worse than one that occasionally misses -- and the
# destructive-operation guard, which must fail closed, is a separate hook.
$raw = [Console]::In.ReadToEnd()
if (-not $raw) { exit 0 }

$projectDir = $env:CLAUDE_PROJECT_DIR
if (-not $projectDir) { $projectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }

$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue) }
if (-not $py) { exit 0 }

# dv_harness must be importable regardless of the hook's working directory.
$env:PYTHONPATH = $projectDir
try {
  $out = $raw | & $py.Source -m dv_harness.context_budget hook 2>$null
} catch {
  exit 0
}
if ($LASTEXITCODE -ne 0) { exit 0 }
if ($out) { $out }
exit 0
