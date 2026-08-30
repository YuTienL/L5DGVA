param([string]$ProjectRoot=".")
$root=(Resolve-Path $ProjectRoot).Path
$required=@(
 ".claude\agents\dv-lead.md",
 ".claude\agents\analysis-agent.md",
 ".claude\agents\implementation-agent.md",
 ".claude\agents\build-agent.md",
 ".claude\agents\regression-agent.md",
 ".claude\agents\debug-agent.md",
 ".claude\agents\review-agent.md",
 ".claude\skills\CORE\dv-workflow\SKILL.md",
 ".claude\skills\CORE\hierarchy-discovery\SKILL.md",
 ".claude\skills\CORE\vip-topology-planner\SKILL.md",
 ".claude\skills\CORE\tb-topology-planner\SKILL.md",
 ".claude\skills\CORE\command-gap-analysis\SKILL.md",
 ".claude\skills\CORE\reference-environment\SKILL.md"
)
$bad=@()
foreach($r in $required){if(-not(Test-Path (Join-Path $root $r))){$bad+=$r}}
if($bad.Count){
 Write-Error ("DV workflow preflight FAILED:`n"+($bad -join "`n"))
 exit 1
}
Write-Host "DV workflow preflight PASS"
Write-Host "7 agents present; core SoC/VIP/TB/command workflow present."
