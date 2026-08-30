param([Parameter(Mandatory=$true)][string]$MemoryId)
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
python -m dv_harness.memory_cli --project-root $root get $MemoryId
