param([string]$Protocol="",[string]$Scope="",[string[]]$Symptom=@(),[string]$Text="")
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
$args=@("--project-root",$root,"search")
if($Protocol){$args+=@("--protocol",$Protocol)}
if($Scope){$args+=@("--scope",$Scope)}
foreach($s in $Symptom){$args+=@("--symptom",$s)}
if($Text){$args+=@("--text",$Text)}
python -m dv_harness.memory_cli @args
