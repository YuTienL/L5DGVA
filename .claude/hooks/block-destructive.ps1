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
 '(?i)\bRemove-Item\b[^\r\n]*-Force[^\r\n]*-Recurse',
 # RTL write-scope guard (2026-09-02): blocks a Bash/PowerShell-level write
 # (redirect/append/tee/sed -i/cp/copy/move/mv as a destination) that also
 # names this project's protected DUT/VIP RTL roots -- the Edit tool alone
 # was covered by settings.json's deny rules, this closes the Bash-level
 # gap for the same two paths.
 '(?i)(?=.*(>{1,2}|\btee\b|\bsed\s+-i\b|\bcp\b|\bcopy\b|\bmove\b|\bmv\b))(?=.*(D:[\\/]+DV[\\/]+Task[\\/]+USB[\\/]+(DUT|VIP)|//d/DV/Task/USB/(DUT|VIP)))'
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
