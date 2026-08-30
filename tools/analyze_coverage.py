#!/usr/bin/env python3
# Mirrors tools/generate_amba_fabric_environment.py's exact shape -- a
# standalone script, not a dv-harness CLI subcommand. Operates only on a real
# coverage summary JSON the project/agent already produced from whatever real
# coverage tool it uses; this script does not itself parse UCIS/urg.
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dv_harness.coverage_analysis import (
    parse_coverage_summary, identify_holes, compute_coverage_trend, CoverageAnalysisError,
)
ap = argparse.ArgumentParser()
ap.add_argument('--summary', required=True, help='path to a real coverage summary JSON')
ap.add_argument('--history', required=False, help='optional path to a coverage history JSON')
a = ap.parse_args()

summary_data = json.loads(pathlib.Path(a.summary).read_text())
try:
    parsed = parse_coverage_summary(summary_data)
except CoverageAnalysisError as e:
    print(json.dumps({"error": e.reason, "detail": e.detail}))
    sys.exit(1)

result = {
    "categories": parsed["categories"],
    "holes": identify_holes(parsed),
}

if a.history:
    history_data = json.loads(pathlib.Path(a.history).read_text())
    try:
        result["trend"] = compute_coverage_trend(history_data)
    except CoverageAnalysisError as e:
        print(json.dumps({"error": e.reason, "detail": e.detail}))
        sys.exit(1)

print(json.dumps(result))
