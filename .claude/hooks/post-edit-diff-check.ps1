$null=[Console]::In.ReadToEnd()
try{
 git rev-parse --is-inside-work-tree *> $null
 if($LASTEXITCODE -ne 0){exit 0}
 $o=git diff --check 2>&1
 if($LASTEXITCODE -ne 0 -and $o){
  @{decision="block";reason="git diff --check found issues:`n$($o -join "`n")"}|ConvertTo-Json -Depth 5 -Compress
 }
}catch{}
exit 0
