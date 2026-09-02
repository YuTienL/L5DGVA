import json
import sys
from pathlib import Path

import dv_harness.cli as cli_mod
from dv_harness.self_tuning import (
    record_adjustment, apply_proposal, get_param, set_param, read_overrides,
    PROTECTED_PARAMETERS, PROTECTED_REMOVALS,
)
from dv_harness.memory import MemoryStore


def _run_cli(monkeypatch, tmp_path, args, capsys):
    monkeypatch.setattr(sys, "argv", ["dv-harness", "--project-root", str(tmp_path)] + args)
    rc = cli_mod.main()
    out = capsys.readouterr().out
    return rc, out


def test_self_tune_status_shows_execution_count(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "status"], capsys)
    assert rc == 0
    data = json.loads(out)
    assert "executions_since_last_review" in data


def test_self_tune_list_shows_pending_adjustment(monkeypatch, tmp_path, capsys):
    proposal = {"gate_id": "g", "change": {"param": "x", "from": 1, "to": 2},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "list", "--pending"], capsys)
    assert rc == 0
    data = json.loads(out)
    ids = [r["memory_id"] for r in data["records"]]
    assert mem_id in ids


def test_self_tune_approve_applies_a_pending_adjustment(monkeypatch, tmp_path, capsys):
    proposal = {"gate_id": "g", "change": {"param": "x", "from": 1, "to": 2},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 0
    assert get_param(tmp_path, "g", "x", None) == 2


def test_self_tune_reject_rejects_a_pending_adjustment(monkeypatch, tmp_path, capsys):
    proposal = {"gate_id": "g", "change": {"param": "x", "from": 1, "to": 2},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "reject", mem_id], capsys)
    assert rc == 0
    result = json.loads(out)
    assert result["ok"] is True

    # Verify the record is now REJECTED
    store = MemoryStore(tmp_path)
    record = store.get(mem_id)
    assert record["status"] == "REJECTED"


def test_self_tune_reject_rejects_applied_record_with_error(monkeypatch, tmp_path, capsys):
    proposal = {"gate_id": "g", "change": {"param": "x", "from": 1, "to": 2},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    # Apply it first
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 0

    # Try to reject it (should fail because it's now APPLIED, not PENDING)
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "reject", mem_id], capsys)
    assert rc == 1
    result = json.loads(out)
    assert result["ok"] is False
    assert result["error"] == "NOT_FOUND_OR_NOT_PENDING"


def test_self_tune_reject_nonself_tuning_record_with_error(monkeypatch, tmp_path, capsys):
    # Create a non-self-tuning record at project level with a different kind
    store = MemoryStore(tmp_path)
    other_record = {
        "kind": "engineering_finding",
        "status": "OPEN",
        "title": "Some finding"
    }
    added = store.add("project", other_record)
    mem_id = added["memory_id"]

    # Try to reject it (should fail because it's not a self_tuning_adjustment)
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "reject", mem_id], capsys)
    assert rc == 1
    result = json.loads(out)
    assert result["ok"] is False
    assert result["error"] == "NOT_FOUND_OR_NOT_PENDING"

    # Verify the record was NOT modified - check all original fields are unchanged
    record_after = store.get(mem_id)
    assert record_after["kind"] == other_record["kind"]
    assert record_after["status"] == other_record["status"]
    assert record_after["title"] == other_record["title"]


def test_self_tune_revert_param_change_restores_original_value(monkeypatch, tmp_path, capsys):
    # Finding I3 (2026-09-02 final-review fix wave): revert must restore the
    # REAL prior value captured at approve time, never the proposal's own
    # self-reported change["from"] -- so the real prior value (10) is set
    # here directly, and the proposal deliberately CLAIMS A WRONG "from"
    # (99) to prove the fix doesn't trust it.
    set_param(tmp_path, "g", "threshold", 10)
    proposal = {"gate_id": "g", "change": {"param": "threshold", "from": 99, "to": 20},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    # Approve it
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 0
    assert get_param(tmp_path, "g", "threshold", None) == 20

    # Revert it -- must restore the REAL prior value (10), not the
    # proposal's wrong claimed "from" (99).
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "revert", mem_id], capsys)
    assert rc == 0
    assert get_param(tmp_path, "g", "threshold", None) == 10


def test_self_tune_revert_param_change_previously_unset_deletes_key(monkeypatch, tmp_path, capsys):
    # Finding I3(a) regression: the parameter was never set before this
    # apply -- revert must DELETE the key (so the gate's own hardcoded
    # default takes over again), not write back the proposal's claimed
    # "from" value or any other fabricated value.
    proposal = {"gate_id": "g_never_set", "change": {"param": "threshold", "from": 999, "to": 20},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 0
    assert get_param(tmp_path, "g_never_set", "threshold", None) == 20

    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "revert", mem_id], capsys)
    assert rc == 0
    assert get_param(tmp_path, "g_never_set", "threshold", "GATE_DEFAULT") == "GATE_DEFAULT"

    # Truly absent from the on-disk parameters.json, not merely defaulting
    # for some other reason.
    params_path = tmp_path / ".dv-harness" / "self_tuning" / "parameters.json"
    data = json.loads(params_path.read_text(encoding="utf-8"))
    assert "g_never_set" not in data or "threshold" not in data.get("g_never_set", {})


def test_self_tune_approve_protected_parameter_fails_cleanly(monkeypatch, tmp_path, capsys):
    # Finding I1 regression: approving a PENDING record targeting a
    # PROTECTED_PARAMETERS entry must fail cleanly (a JSON error response,
    # not a raw traceback) and must never actually write the value.
    gate_id, param = next(iter(PROTECTED_PARAMETERS))
    proposal = {"gate_id": gate_id, "change": {"param": param, "from": 0.5, "to": 0.9},
                "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 1
    result = json.loads(out)
    assert result["ok"] is False
    assert result["error"] == "BLOCKED_PROTECTED"

    assert get_param(tmp_path, gate_id, param, "UNSET") == "UNSET"

    store = MemoryStore(tmp_path)
    record = store.get(mem_id)
    assert record["status"] == "BLOCKED_PROTECTED"


def test_self_tune_approve_protected_removal_fails_cleanly(monkeypatch, tmp_path, capsys):
    # Finding I2 regression: approving a PENDING "remove" record targeting a
    # PROTECTED_REMOVALS pair must fail cleanly and record BLOCKED_PROTECTED
    # (never APPLIED), not silently no-op while looking successful.
    protected_stage, protected_gate = next(iter(PROTECTED_REMOVALS))
    proposal = {"gate_id": protected_gate, "stage": protected_stage,
                "change": {"action": "remove", "gate_id": protected_gate},
                "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 1
    result = json.loads(out)
    assert result["ok"] is False
    assert result["error"] == "BLOCKED_PROTECTED"

    overrides = read_overrides(tmp_path)
    assert protected_gate not in overrides.get(protected_stage, {}).get("remove", [])

    store = MemoryStore(tmp_path)
    record = store.get(mem_id)
    assert record["status"] == "BLOCKED_PROTECTED"


def test_self_tune_revert_add_removes_gate_from_overlay(monkeypatch, tmp_path, capsys):
    # Create an "add" change record and apply it
    proposal = {"gate_id": "new_gate", "stage": "VERIFY", "change": {"action": "add", "gate_id": "new_gate"},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    # Approve it
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 0

    # Verify gate is in overlay add list
    overrides = read_overrides(tmp_path)
    assert "new_gate" in overrides.get("VERIFY", {}).get("add", [])

    # Revert it
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "revert", mem_id], capsys)
    assert rc == 0

    # Verify gate is removed from overlay add list
    overrides = read_overrides(tmp_path)
    assert "new_gate" not in overrides.get("VERIFY", {}).get("add", [])


def test_self_tune_revert_add_preserves_other_gates_in_overlay(monkeypatch, tmp_path, capsys):
    # Add two gates to overlay add list
    proposal1 = {"gate_id": "gate1", "stage": "VERIFY", "change": {"action": "add", "gate_id": "gate1"},
                 "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id1 = record_adjustment(tmp_path, proposal1, status="PENDING")

    proposal2 = {"gate_id": "gate2", "stage": "VERIFY", "change": {"action": "add", "gate_id": "gate2"},
                 "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id2 = record_adjustment(tmp_path, proposal2, status="PENDING")

    # Approve both
    rc, _ = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id1], capsys)
    assert rc == 0
    rc, _ = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id2], capsys)
    assert rc == 0

    # Verify both gates are in overlay
    overrides = read_overrides(tmp_path)
    assert "gate1" in overrides.get("VERIFY", {}).get("add", [])
    assert "gate2" in overrides.get("VERIFY", {}).get("add", [])

    # Revert only gate1
    rc, _ = _run_cli(monkeypatch, tmp_path, ["self-tune", "revert", mem_id1], capsys)
    assert rc == 0

    # Verify gate1 is removed but gate2 remains
    overrides = read_overrides(tmp_path)
    assert "gate1" not in overrides.get("VERIFY", {}).get("add", [])
    assert "gate2" in overrides.get("VERIFY", {}).get("add", [])


def test_self_tune_revert_remove_restores_gate_to_overlay(monkeypatch, tmp_path, capsys):
    # Create a "remove" change record and apply it
    proposal = {"gate_id": "remove_gate", "stage": "VERIFY", "change": {"action": "remove", "gate_id": "remove_gate"},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    # Approve it
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 0

    # Verify gate is in overlay remove list
    overrides = read_overrides(tmp_path)
    assert "remove_gate" in overrides.get("VERIFY", {}).get("remove", [])

    # Revert it
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "revert", mem_id], capsys)
    assert rc == 0

    # Verify gate is removed from overlay remove list
    overrides = read_overrides(tmp_path)
    assert "remove_gate" not in overrides.get("VERIFY", {}).get("remove", [])


def test_self_tune_revert_remove_preserves_other_gates_in_overlay(monkeypatch, tmp_path, capsys):
    # Add two gates to overlay remove list
    proposal1 = {"gate_id": "gate1", "stage": "VERIFY", "change": {"action": "remove", "gate_id": "gate1"},
                 "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id1 = record_adjustment(tmp_path, proposal1, status="PENDING")

    proposal2 = {"gate_id": "gate2", "stage": "VERIFY", "change": {"action": "remove", "gate_id": "gate2"},
                 "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id2 = record_adjustment(tmp_path, proposal2, status="PENDING")

    # Approve both
    rc, _ = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id1], capsys)
    assert rc == 0
    rc, _ = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id2], capsys)
    assert rc == 0

    # Verify both gates are in overlay remove list
    overrides = read_overrides(tmp_path)
    assert "gate1" in overrides.get("VERIFY", {}).get("remove", [])
    assert "gate2" in overrides.get("VERIFY", {}).get("remove", [])

    # Revert only gate1
    rc, _ = _run_cli(monkeypatch, tmp_path, ["self-tune", "revert", mem_id1], capsys)
    assert rc == 0

    # Verify gate1 is removed but gate2 remains
    overrides = read_overrides(tmp_path)
    assert "gate1" not in overrides.get("VERIFY", {}).get("remove", [])
    assert "gate2" in overrides.get("VERIFY", {}).get("remove", [])


def test_self_tune_approve_rejects_nonself_tuning_record_with_error(monkeypatch, tmp_path, capsys):
    # Create a non-self-tuning record with PENDING status (vulnerable to the bug)
    store = MemoryStore(tmp_path)
    other_record = {
        "kind": "engineering_finding",
        "status": "PENDING",
        "title": "Some finding",
        "custom_field": "custom_value"
    }
    added = store.add("project", other_record)
    mem_id = added["memory_id"]

    # Try to approve it (should fail because it's not a self_tuning_adjustment)
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 1
    result = json.loads(out)
    assert result["ok"] is False
    assert result["error"] == "NOT_FOUND_OR_NOT_PENDING"

    # Verify the record was NOT modified - check all original fields are unchanged
    record_after = store.get(mem_id)
    assert record_after["kind"] == other_record["kind"]
    assert record_after["status"] == other_record["status"]
    assert record_after["title"] == other_record["title"]
    assert record_after["custom_field"] == other_record["custom_field"]


def test_self_tune_revert_rejects_nonself_tuning_record_with_error(monkeypatch, tmp_path, capsys):
    # Create a non-self-tuning record with APPLIED status (vulnerable to the bug)
    store = MemoryStore(tmp_path)
    other_record = {
        "kind": "corner_case",
        "status": "APPLIED",
        "title": "Some corner case",
        "data": {"nested": "value"}
    }
    added = store.add("project", other_record)
    mem_id = added["memory_id"]

    # Try to revert it (should fail because it's not a self_tuning_adjustment)
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "revert", mem_id], capsys)
    assert rc == 1
    result = json.loads(out)
    assert result["ok"] is False
    assert result["error"] == "NOT_FOUND_OR_NOT_APPLIED"

    # Verify the record was NOT modified - check all original fields are unchanged
    record_after = store.get(mem_id)
    assert record_after["kind"] == other_record["kind"]
    assert record_after["status"] == other_record["status"]
    assert record_after["title"] == other_record["title"]
    assert record_after["data"] == other_record["data"]
