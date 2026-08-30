param([string]$ProjectRoot=".")
$root=(Resolve-Path $ProjectRoot).Path
$env:DVROOT=$root
python -c "import os,json;from pathlib import Path;from dv_harness.graph_runtime import GraphRuntime;r=GraphRuntime(Path(os.environ['DVROOT']));print(json.dumps(r.gstate.data,ensure_ascii=False,indent=2))"
