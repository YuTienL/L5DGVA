# Retargeted 2026-09-03 (gap-close-engine cleanup): previously constructed
# dv_harness.graph_runtime.GraphRuntime and printed its GraphState
# (.dv-harness/graph/graph_state.json) -- a standalone record that was never
# updated by the real engine (dv_harness/engine.py's run_stage() drives
# .dv-harness/state.json via StateStore/HarnessState instead) and therefore
# went permanently stale after the first stage. graph_runtime.py and its
# GraphState class have been removed; this now prints the SAME real, live
# status `dv-harness status` / dv_harness.cli.py's `status` subcommand reads
# (DVHarness.summary() over the actual HarnessState).
param([string]$ProjectRoot=".")
$root=(Resolve-Path $ProjectRoot).Path
$env:DVROOT=$root
python -c "import os;from pathlib import Path;from dv_harness.engine import DVHarness;h=DVHarness(Path(os.environ['DVROOT']));print(h.summary())"
