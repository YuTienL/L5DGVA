param([string]$ProjectRoot=".",[string]$OutputDir=".dv-workflow")
$root=(Resolve-Path $ProjectRoot).Path
$out=Join-Path $root $OutputDir
New-Item -ItemType Directory -Force $out | Out-Null

$dimensions=[ordered]@{
 "DUT/Hierarchy"=0
 "DUT Ports"=0
 "Protocol Config"=0
 "Interface Topology"=0
 "VIP Topology"=0
 "VIP Binding"=0
 "TB Topology"=0
 "Command Interface"=0
 "Command Mapping"=0
 "Testbench"=0
 "Specification"=0
 "vPlan"=0
 "Build Flow"=0
 "Regression"=0
 "Coverage"=0
}
$weights=[ordered]@{
 "DUT/Hierarchy"=8;"DUT Ports"=6;"Protocol Config"=8;"Interface Topology"=7;
 "VIP Topology"=8;"VIP Binding"=8;"TB Topology"=8;"Command Interface"=7;
 "Command Mapping"=7;"Testbench"=7;"Specification"=5;"vPlan"=7;
 "Build Flow"=5;"Regression"=5;"Coverage"=4
}

function ExistsScore($file) { if(Test-Path (Join-Path $out $file)){100}else{0} }
$dimensions["DUT/Hierarchy"]=ExistsScore "hierarchy.json"
$dimensions["DUT Ports"]=ExistsScore "dut_ports.csv"
$dimensions["Interface Topology"]=ExistsScore "interface_inventory.csv"
$dimensions["VIP Topology"]=ExistsScore "vip_topology.csv"
$dimensions["VIP Binding"]=ExistsScore "vip_binding.csv"
$dimensions["TB Topology"]=ExistsScore "tb_topology.json"
$dimensions["Command Interface"]=ExistsScore "command_inventory.csv"
$dimensions["Command Mapping"]=ExistsScore "command_mapping.csv"
$dimensions["vPlan"]=ExistsScore "vplan.csv"

$model=Join-Path $out "project_model.json"
$blocking=0
if(Test-Path $model){
 try{
  $m=Get-Content $model -Raw|ConvertFrom-Json
  if($m.blocking_unknown_count){$blocking=[int]$m.blocking_unknown_count}
  if($m.readiness_overrides){
   foreach($p in $m.readiness_overrides.PSObject.Properties){
    if($dimensions.Contains($p.Name)){$dimensions[$p.Name]=[int]$p.Value}
   }
  }
 }catch{}
}

$total=0
foreach($k in $dimensions.Keys){$total += $dimensions[$k]*$weights[$k]}
$overall=[math]::Round($total/100)
$status=if($blocking -gt 0){"BLOCKED"}elseif($overall -ge 80){"READY"}elseif($overall -ge 35){"PARTIAL"}else{"BLOCKED"}

$result=[ordered]@{generated_at=(Get-Date).ToString("o");dimensions=$dimensions;weights=$weights;overall_readiness=$overall;status=$status;blocking_unknown_count=$blocking}
$result|ConvertTo-Json -Depth 8|Set-Content -Encoding UTF8 (Join-Path $out "readiness.json")

Write-Host "`nDV READINESS"
Write-Host "------------------------------------------------"
foreach($k in $dimensions.Keys){
 $pct=[int]$dimensions[$k];$n=[math]::Floor($pct/10)
 $bar=("█"*$n)+("░"*(10-$n))
 "{0,-20} {1} {2,3}%" -f $k,$bar,$pct|Write-Host
}
Write-Host "`nOverall readiness: $overall%"
Write-Host "STATUS: $status"
