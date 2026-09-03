# SessionStart hook: makes context-budget tier 2 ("ALWAYS resident") a real
# mechanism instead of an accident (2026-09-03).
#
# Before this, exactly one of the five declared tier-2 artifacts was truly
# resident -- CLAUDE.md -- and only because Claude Code auto-loads a project
# CLAUDE.md. Nothing this project built forced env.manifest.json,
# run_profile.json, hierarchy.json or phy_boundary.json into a session.
#
# This emits hookSpecificOutput.additionalContext holding the bounded pack
# built by dv_harness/context_budget.py (MAX_PACK_BYTES caps it -- a
# residency mechanism that can grow without bound is itself a context-budget
# bug). Artifacts that do not exist yet are reported as MISSING with the real
# command that would produce them, so the gap stays visible and actionable
# rather than silently absent.
#
# FAIL-OPEN for the same reason as context-budget-guard.ps1: no python, no
# injected context, session proceeds.
$projectDir = $env:CLAUDE_PROJECT_DIR
if (-not $projectDir) { $projectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }

$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue) }
if (-not $py) { exit 0 }

# dv_harness must be importable regardless of the hook's working directory.
$env:PYTHONPATH = $projectDir
try {
  $out = & $py.Source -m dv_harness.context_budget session-start --root $projectDir 2>$null
} catch {
  exit 0
}
if ($LASTEXITCODE -ne 0) { exit 0 }
if ($out) { $out }
exit 0
