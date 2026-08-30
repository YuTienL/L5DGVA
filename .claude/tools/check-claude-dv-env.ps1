param(
  [string]$ProjectRoot = "."
)

$ErrorActionPreference = "Continue"
$root = (Resolve-Path $ProjectRoot).Path
$claudeDir = Join-Path $root ".claude"
$dvDir = Join-Path $root ".dv-workflow"
New-Item -ItemType Directory -Force -Path $dvDir | Out-Null

$rows = @()

function Add-Row($Type,$Name,$Scope,$Path,$Expected,$Found,$Enabled,$Status,$Notes) {
  $script:rows += [pscustomobject]@{
    TYPE=$Type; NAME=$Name; SCOPE=$Scope; PATH=$Path; EXPECTED=$Expected
    FOUND=$Found; ENABLED=$Enabled; STATUS=$Status; NOTES=$Notes
  }
}

# Claude CLI
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
  $ver = (& claude --version 2>&1 | Out-String).Trim()
  Add-Row "CLI" "claude" "system" $claude.Source "yes" "yes" "n/a" "READY" $ver
} else {
  Add-Row "CLI" "claude" "system" "" "yes" "no" "n/a" "BLOCKED" "claude executable not found"
}

# Settings JSON
foreach ($f in @("settings.json","settings.local.json")) {
  $p = Join-Path $claudeDir $f
  if (Test-Path $p) {
    try {
      Get-Content $p -Raw | ConvertFrom-Json | Out-Null
      Add-Row "SETTINGS" $f "project" $p "yes" "yes" "n/a" "READY" "valid JSON"
    } catch {
      Add-Row "SETTINGS" $f "project" $p "yes" "yes" "n/a" "BLOCKED" "invalid JSON"
    }
  } else {
    Add-Row "SETTINGS" $f "project" $p "yes" "no" "n/a" "PARTIAL" "missing"
  }
}

# Required core skills
$requiredSkills = @(
  "dv-workflow","dv-intake","protocol-router","subsystem-to-soc-verification",
  "generic-infrastructure-audit","failure-triage","systematic-debug",
  "verification-signoff","vcs-build","git-workflow","devops-pipeline",
  "claude-environment-readiness"
)
foreach ($s in $requiredSkills) {
  $hits = Get-ChildItem (Join-Path $claudeDir "skills") -Recurse -Filter "SKILL.md" -ErrorAction SilentlyContinue |
          Where-Object { $_.Directory.Name -eq $s }
  if ($hits) {
    Add-Row "SKILL" $s "project" $hits[0].FullName "yes" "yes" "n/a" "READY" ""
  } else {
    Add-Row "SKILL" $s "project" "" "yes" "no" "n/a" "BLOCKED" "required core skill missing"
  }
}

# Agents
$requiredAgents = @(
  "dv-lead","analysis-agent","implementation-agent","build-agent",
  "debug-agent","regression-agent","review-agent"
)
foreach ($a in $requiredAgents) {
  $p = Join-Path (Join-Path $claudeDir "agents") ($a + ".md")
  if (Test-Path $p) {
    Add-Row "AGENT" $a "project" $p "yes" "yes" "n/a" "READY" ""
  } else {
    Add-Row "AGENT" $a "project" $p "yes" "no" "n/a" "BLOCKED" "required agent missing"
  }
}

# Inventory all project skills
$allSkills = Get-ChildItem (Join-Path $claudeDir "skills") -Recurse -Filter "SKILL.md" -ErrorAction SilentlyContinue
foreach ($s in $allSkills) {
  if ($requiredSkills -notcontains $s.Directory.Name) {
    Add-Row "SKILL" $s.Directory.Name "project" $s.FullName "optional/task-dependent" "yes" "n/a" "READY" ""
  }
}

$csv = Join-Path $dvDir "claude_environment_inventory.csv"
$rows | Export-Csv -NoTypeInformation -Encoding UTF8 $csv

$blocked = @($rows | Where-Object STATUS -eq "BLOCKED").Count
$partial = @($rows | Where-Object STATUS -eq "PARTIAL").Count

Write-Host ""
Write-Host "CLAUDE / DV WORKFLOW READINESS"
Write-Host "=============================="
Write-Host ("CLI        : " + $(if($claude){"FOUND"}else{"MISSING"}))
Write-Host ("Agents     : " + (@($rows | Where-Object TYPE -eq "AGENT" | Where-Object FOUND -eq "yes").Count) + "/7")
Write-Host ("Skills     : " + $allSkills.Count)
Write-Host ("Inventory  : " + $csv)

if ($blocked -gt 0) {
  Write-Host "STATUS     : BLOCKED"
  exit 2
} elseif ($partial -gt 0) {
  Write-Host "STATUS     : PARTIAL"
  exit 1
} else {
  Write-Host "STATUS     : READY"
  exit 0
}

# Plugin/Superpowers note:
# Claude Code plugin state should be verified through the CLI/plugin UI supported
# by the installed Claude version. Do not infer plugin enabled state from project
# .claude/skills alone.
