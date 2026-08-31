"""dv_harness/waiver_store.py -- shared, human-authored waiver records at
.dv-harness/waivers/waivers.json, readable by the six waiver-consuming
gate scripts under tools/verification_flow/. Distinct from an AI agent's
own fenced dv-harness-evidence waiver blocks -- this is the human-facing
persistence layer a dashboard form writes to.

Adapter note (Task 4, step 7): each of the six gate scripts
(waiver_scope_consistency_gate.py, waiver_revision_freshness_gate.py,
waiver_revalidation_gate.py, coverage_hole_regeneration_gate.py,
coverage_hole_to_test_generation_gate.py, sequence_coverage_closure_gate.py)
expects its own bespoke JSON payload shape (different top-level keys --
"waivers"/"coverage_holes"/"items"/"waivers" nested under "coverage" --
and different per-record field names -- waiver_id/coverage_id/id/sequence),
and dv_harness/gates.run_gate() assembles that payload purely from the
agent's own fenced ```dv-harness-evidence:<gate_id>``` block at stage-run
time (extract_evidence_blocks() -> a fresh tempfile.NamedTemporaryFile per
invocation -- see gates.py). There is no fixed harness code path today that
reads a waivers store from a known location before invoking a gate. This
module intentionally does not force an integration point into that ad hoc
flow; it exposes read_waivers() as the durable, human-facing source of
truth an agent/skill should consult when assembling a gate's evidence block,
without changing any gate script's own pass/fail logic.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

REQUIRED_FIELDS = ("gate_id", "item_id", "approved", "evidence")


def _store_path(root: Path) -> Path:
    return root / ".dv-harness" / "waivers" / "waivers.json"


def read_waivers(root: Path) -> List[Dict[str, Any]]:
    path = _store_path(root)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def append_waiver(root: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    missing = [f for f in REQUIRED_FIELDS if f not in record or record[f] in (None, "")]
    if missing:
        raise ValueError(f"waiver record missing required fields: {missing}")
    record = dict(record)
    record["recorded_at"] = time.time()
    path = _store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    waivers = read_waivers(root)
    waivers.append(record)
    path.write_text(json.dumps(waivers, indent=2), encoding="utf-8")
    return record
