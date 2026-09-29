"""dv_harness/waiver_store.py -- shared, human-authored waiver records at
.dv-harness/waivers/waivers.json. Distinct from an AI agent's own fenced
dv-harness-evidence waiver blocks (per-gate, ad hoc, assembled at
evidence-writing time into a NamedTemporaryFile -- see gates.run_gate()):
this is the human-facing persistence layer a dashboard form writes to."""
from __future__ import annotations

import pytest

from dv_harness.waiver_store import append_waiver, read_waivers


def test_append_and_read_roundtrip(tmp_path):
    record = {
        "gate_id": "coverage_hole_regeneration_gate",
        "item_id": "cov-hole-42",
        "approved": True,
        "evidence": "manually reviewed against spec section 4.2",
    }
    append_waiver(tmp_path, record)
    waivers = read_waivers(tmp_path)
    assert len(waivers) == 1
    assert waivers[0]["gate_id"] == "coverage_hole_regeneration_gate"
    assert waivers[0]["item_id"] == "cov-hole-42"
    assert "recorded_at" in waivers[0]


def test_append_requires_approved_and_evidence(tmp_path):
    with pytest.raises(ValueError):
        append_waiver(tmp_path, {"gate_id": "x", "item_id": "y"})  # missing approved/evidence


def test_read_waivers_empty_when_no_store_file(tmp_path):
    assert read_waivers(tmp_path) == []


def test_append_rejects_empty_string_evidence(tmp_path):
    # evidence="" is present but falsy -- REQUIRED_FIELDS treats it the same
    # as missing (record[f] in (None, "")), so it must still raise.
    with pytest.raises(ValueError):
        append_waiver(tmp_path, {"gate_id": "x", "item_id": "y", "approved": True, "evidence": ""})


def test_append_multiple_waivers_accumulate_in_order(tmp_path):
    append_waiver(tmp_path, {"gate_id": "g1", "item_id": "i1", "approved": True, "evidence": "e1"})
    append_waiver(tmp_path, {"gate_id": "g2", "item_id": "i2", "approved": True, "evidence": "e2"})
    waivers = read_waivers(tmp_path)
    assert [w["gate_id"] for w in waivers] == ["g1", "g2"]
