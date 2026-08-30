param([string]$ProjectRoot=".")
python -m dv_harness.dashboard --project-root (Resolve-Path $ProjectRoot).Path
