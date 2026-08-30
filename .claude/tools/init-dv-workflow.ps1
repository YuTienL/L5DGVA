param([string]$ProjectRoot=".")
$ErrorActionPreference="Stop"
Push-Location $ProjectRoot
try{
 New-Item -ItemType Directory -Force ".dv-workflow"|Out-Null
 $templates="hierarchy.json","dut_ports.csv","interface_inventory.csv","vip_topology.csv","vip_binding.csv","tb_topology.json","branch_a.csv","branch_fw.csv","branch_b.csv","command_inventory.csv","command_gap.csv","command_mapping.csv","evidence.csv","vplan.csv","project_model.json","validation.json","remote_context.json","reference_context.json","amba_fabric.csv","amba_resource_map.csv","lsf_jobs.csv","regression_results.csv","failure_clusters.csv","regression_summary.json","pattern_registry.csv","regression_patterns.csv","promotion_history.csv","interrupt_map.csv","branch_b_scenarios.csv","generic_infrastructure_audit.csv","devops_trace.csv","workflow_findings.csv","requirements_traceability.csv","soc_scenarios.csv","change_impact.csv","regression_selection.csv","workflow_closure.json","git_state.json","scoreboard_by_port_audit.csv","dma_scoreboard_by_port_audit.csv","performance_by_port_audit.csv","coverage_by_port_audit.csv","pattern.yaml"
 foreach($f in $templates){
  $src=Join-Path ".claude\templates" $f
  $dst=Join-Path ".dv-workflow" $f
  if((Test-Path $src) -and -not(Test-Path $dst)){Copy-Item $src $dst}
 }
 if(Test-Path ".\.claude\tools\dv-project-scan.ps1"){& ".\.claude\tools\dv-project-scan.ps1" -ProjectRoot "."}
 & ".\.claude\tools\dv-readiness.ps1" -ProjectRoot "."
 Write-Host "`nClaude Code:"
 Write-Host '  /dv-workflow <DV request>'
}finally{Pop-Location}
