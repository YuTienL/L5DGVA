$raw=[Console]::In.ReadToEnd()
if(-not $raw){exit 0}
try{$data=$raw|ConvertFrom-Json}catch{exit 0}
$cmd=[string]$data.tool_input.command
$blocked=@(
 '(?i)\bgit\s+reset\s+--hard\b',
 '(?i)\bgit\s+clean\b[^\r\n]*\s-f',
 '(?i)\bgit\s+push\b[^\r\n]*(--force|-f)\b',
 '(?i)\brm\s+-rf\b',
 '(?i)\bRemove-Item\b[^\r\n]*-Recurse[^\r\n]*-Force',
 '(?i)\bRemove-Item\b[^\r\n]*-Force[^\r\n]*-Recurse'
)
foreach($p in $blocked){
 if($cmd -match $p){
  @{
   hookSpecificOutput=@{
    hookEventName="PreToolUse"
    permissionDecision="deny"
    permissionDecisionReason="Blocked destructive operation by industrial DV workflow."
   }
  }|ConvertTo-Json -Depth 8 -Compress
  exit 0
 }
}
exit 0
