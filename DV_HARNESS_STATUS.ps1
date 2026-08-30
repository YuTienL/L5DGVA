param([string]$ProjectRoot=".")
python -m dv_harness --project-root (Resolve-Path $ProjectRoot).Path status
