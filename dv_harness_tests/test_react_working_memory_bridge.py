"""Tests for the ReactRecorder <-> WorkingMemoryStore cross-reference added
by the memory-engine-schema-completion audit (2026-09-01) -- see
dv_harness/react.py's ReactRecorder module-header RULING comment for the
full design rationale (write-time push through memory_router.route_and_store()
rather than a MemoryRetriever.search()-side reconciliation).
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from dv_harness.react import ReactRecorder
from dv_harness.memory import WorkingMemoryStore
from dv_harness.memory_router import route_memory


def test_react_recorder_record_writes_a_working_memory_tier_record():
    tmp = Path(tempfile.mkdtemp())
    try:
        rr = ReactRecorder(tmp)
        rr.record(
            node="VERIFY",
            iteration=1,
            reason_summary="sim.log shows UVM_ERROR count above threshold; hypothesis: scoreboard mismatch",
            action={"adapter": "ClaudeAdapter", "agent": "verify-agent"},
            tool="ClaudeAdapter.run",
            observation={"ok": True, "status": "PASS"},
            evidence={"uvm_error_count": 3, "sim_log": "run.log"},
            confidence="MEDIUM",
            next_action="rerun with WAVE=1 targeted at first UVM_ERROR",
        )

        # 1. The pre-existing react/ file-based record is unchanged.
        react_file = tmp / ".dv-harness" / "react" / "VERIFY" / "iteration_001.json"
        assert react_file.exists()
        react_json = json.loads(react_file.read_text(encoding="utf-8"))
        assert react_json["reason_summary"].startswith("sim.log shows")

        # 2. A genuinely new Working Memory tier record now also exists,
        #    carrying the SAME hypothesis/evidence/next-action content.
        store = WorkingMemoryStore(tmp)
        rows = [r for r in store.store._index() if r.get("level") == "working"]
        assert rows, f"no Working Memory record written by ReactRecorder.record(): {store.store._index()}"
        rec = store.get(rows[0]["memory_id"])
        assert rec is not None
        assert rec["level"] == "working"
        assert rec["node"] == "VERIFY"
        assert rec["iteration"] == 1
        assert rec["hypothesis"].startswith("sim.log shows")
        assert rec["evidence"] == {"uvm_error_count": 3, "sim_log": "run.log"}
        assert rec["next_action"] == "rerun with WAVE=1 targeted at first UVM_ERROR"
        assert rec["confidence"] == "MEDIUM"
    finally:
        shutil.rmtree(tmp)


def test_react_recorder_working_memory_record_is_idempotent_on_same_node_and_iteration():
    # Deterministic memory_id (node, iteration) means a repeat record() call
    # for the exact same stage attempt upserts in place rather than
    # duplicating -- same rationale as lsf_client's job-tier idempotency.
    tmp = Path(tempfile.mkdtemp())
    try:
        rr = ReactRecorder(tmp)
        for confidence in ("LOW", "HIGH"):
            rr.record(
                node="RE_AUDIT", iteration=2, reason_summary="r", action={}, tool="t",
                observation={}, evidence={}, confidence=confidence, next_action="n",
            )
        store = WorkingMemoryStore(tmp)
        rows = [r for r in store.store._index()
                if r.get("level") == "working" and r.get("memory_id") == "WM-REACT-RE_AUDIT-002"]
        assert len(rows) == 1
        assert store.get(rows[0]["memory_id"])["confidence"] == "HIGH"
    finally:
        shutil.rmtree(tmp)


def test_react_recorder_persistence_failure_never_raises_out_of_record():
    # Best-effort discipline: a broken memory_router path must never break
    # an already-completed react/ file write.
    tmp = Path(tempfile.mkdtemp())
    try:
        rr = ReactRecorder(tmp)
        with patch("dv_harness.memory_router.route_and_store", side_effect=RuntimeError("boom")):
            r = rr.record(
                node="INTAKE", iteration=1, reason_summary="r", action={}, tool="t",
                observation={}, evidence={}, confidence="LOW", next_action="n",
            )
        assert r["reason_summary"] == "r"
        react_file = tmp / ".dv-harness" / "react" / "INTAKE" / "iteration_001.json"
        assert react_file.exists()
    finally:
        shutil.rmtree(tmp)


def test_route_memory_routes_react_reasoning_step_to_working_memory_explicitly():
    # route_memory() should route this kind via its own named rule, not just
    # the generic fallthrough -- both are asserted here since the fallthrough
    # would also accept an unrelated/unclassified kind.
    assert route_memory({"kind": "react_reasoning_step"}) == "WORKING_MEMORY"
    # Distinct from the pre-existing "active_hypothesis" kind, which is a
    # current-run Blackboard concept, not a durable working-memory record.
    assert route_memory({"kind": "active_hypothesis"}) == "BLACKBOARD"
