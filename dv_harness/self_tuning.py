from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .storage import _atomic_replace

SELF_TUNING_DIR = ".dv-harness/self_tuning"


def _dir(root: Path) -> Path:
    d = root / ".dv-harness" / "self_tuning"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _params_path(root: Path) -> Path:
    return _dir(root) / "parameters.json"


def _overrides_path(root: Path) -> Path:
    return _dir(root) / "stage_gate_overrides.json"


def _state_path(root: Path) -> Path:
    return _dir(root) / "state.json"


def _history_path(root: Path) -> Path:
    return _dir(root) / "gate_history.jsonl"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json_atomic(path: Path, data) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def get_param(root: Path, gate_id: str, name: str, default: Any) -> Any:
    data = _read_json(_params_path(root), {})
    if not isinstance(data, dict):
        return default
    return data.get(gate_id, {}).get(name, default)


def set_param(root: Path, gate_id: str, name: str, value: Any) -> None:
    data = _read_json(_params_path(root), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault(gate_id, {})[name] = value
    _write_json_atomic(_params_path(root), data)


def read_overrides(root: Path) -> Dict[str, Any]:
    data = _read_json(_overrides_path(root), {})
    return data if isinstance(data, dict) else {}


def _compute_protected_removals() -> set:
    from . import gates as _gates
    protected = {
        ("IMPLEMENT", "rtl_write_scope_guard_gate"),
        ("RE_AUDIT", "fix_risk_approval_gate"),
        ("IMPLEMENT", "manual_lookup_before_edit_gate"),
        ("IMPLEMENT", "protocol_isolation_gate"),
    }
    for stage in ("PROMOTION_READINESS", "SIGNOFF"):
        for entry in _gates.STAGE_GATES.get(stage, []):
            gate_id = entry[0]
            protected.add((stage, gate_id))
    return protected


PROTECTED_REMOVALS = _compute_protected_removals()


def propose_add_override(root: Path, stage: str, gate_id: str) -> None:
    overrides = read_overrides(root)
    stage_entry = overrides.setdefault(stage, {"add": [], "remove": []})
    stage_entry.setdefault("add", [])
    if gate_id not in stage_entry["add"]:
        stage_entry["add"].append(gate_id)
    _write_json_atomic(_overrides_path(root), overrides)


def propose_remove_override(root: Path, stage: str, gate_id: str) -> bool:
    if (stage, gate_id) in PROTECTED_REMOVALS:
        return False
    overrides = read_overrides(root)
    stage_entry = overrides.setdefault(stage, {"add": [], "remove": []})
    stage_entry.setdefault("remove", [])
    if gate_id not in stage_entry["remove"]:
        stage_entry["remove"].append(gate_id)
    _write_json_atomic(_overrides_path(root), overrides)
    return True


def read_execution_state(root: Path) -> Dict[str, Any]:
    return _read_json(_state_path(root), {"executions_since_last_review": 0})


def increment_execution_counter(root: Path) -> int:
    state = read_execution_state(root)
    state["executions_since_last_review"] = state.get("executions_since_last_review", 0) + 1
    _write_json_atomic(_state_path(root), state)
    return state["executions_since_last_review"]


def reset_execution_counter(root: Path) -> None:
    _write_json_atomic(_state_path(root), {"executions_since_last_review": 0})


def append_gate_history(root: Path, gate_id: str, stage: str, ok: bool, reason: str, timestamp: float) -> None:
    entry = {"gate_id": gate_id, "stage": stage, "ok": ok, "reason": reason, "timestamp": timestamp}
    with open(_history_path(root), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def gate_history_length(root: Path) -> int:
    p = _history_path(root)
    if not p.exists():
        return 0
    with open(p, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def read_gate_history_since(root: Path, since_index: int) -> List[Dict[str, Any]]:
    p = _history_path(root)
    if not p.exists():
        return []
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < since_index:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


ELEVATED_SCRUTINY_GATES = {
    "deep_rca_evidence_gate", "root_cause_evidence_gate",
    "focused_wave_debug_window_gate", "fix_regression_non_regression_gate",
    "issue_triage_classification_gate", "unknown_failure_escalation_gate",
    "failure_signature_recurrence_gate", "failure_attribution",
    "nondeterminism_attribution_gate", "rca_confidence_escalation_gate",
    "regression_replay_equivalence_gate", "root_cause_attribution_consistency_gate",
    "dut_request_record_gate", "rca_replay_fix_closure_gate",
}


def classify_proposal(proposal: Dict[str, Any], cycle_proposals: List[Dict[str, Any]],
                       recent_reverts: set) -> str:
    """Pure classification -- see the design spec's "Apply / defer-to-human"
    section for the exact rule list. No I/O; callers pass in whatever
    context (this cycle's full proposal batch, the set of gate_ids
    reverted in recent cycles) they've already assembled."""
    change = proposal.get("change") or {}
    if proposal.get("confidence") != "HIGH":
        return "DEFER"
    if proposal.get("risk_level") == "HIGH":
        return "DEFER"
    if change.get("action") in ("remove",):
        return "DEFER"
    if proposal.get("gate_id") in ELEVATED_SCRUTINY_GATES:
        return "DEFER"
    if len(cycle_proposals) > 1:
        return "DEFER"
    if proposal.get("gate_id") in recent_reverts:
        return "DEFER"
    return "AUTO_APPLY"


def apply_proposal(root: Path, proposal: Dict[str, Any]) -> None:
    change = proposal.get("change") or {}
    action = change.get("action")
    gate_id = proposal.get("gate_id")

    if action == "add":
        stage = proposal.get("stage")
        if stage is None or change.get("gate_id") is None:
            raise ValueError(
                f"add/remove proposal for gate {gate_id!r} missing required keys: "
                f"stage={stage!r}, change.gate_id={change.get('gate_id')!r}"
            )
        propose_add_override(root, stage, change["gate_id"])
    elif action == "remove":
        stage = proposal.get("stage")
        if stage is None or change.get("gate_id") is None:
            raise ValueError(
                f"add/remove proposal for gate {gate_id!r} missing required keys: "
                f"stage={stage!r}, change.gate_id={change.get('gate_id')!r}"
            )
        propose_remove_override(root, stage, change["gate_id"])
    else:
        # Param-change path: requires "param" and "to" keys
        if change.get("param") is None:
            raise ValueError(
                f"param-change proposal for gate {gate_id!r} missing required key: "
                f"change.param={change.get('param')!r}"
            )
        if "to" not in change:
            raise ValueError(
                f"param-change proposal for gate {gate_id!r} missing required key: "
                f"'to' not in change (change keys: {list(change.keys())})"
            )
        set_param(root, gate_id, change["param"], change["to"])


def record_adjustment(root: Path, proposal: Dict[str, Any], status: str,
                       applied_by: str = "system") -> str:
    from .memory import MemoryStore
    record = {
        "kind": "self_tuning_adjustment",
        "status": status,
        "applied_by": applied_by,
        "gate_id": proposal.get("gate_id"),
        "stage": proposal.get("stage"),
        "change": proposal.get("change"),
        "rationale": proposal.get("rationale"),
        "confidence": proposal.get("confidence"),
        "risk_level": proposal.get("risk_level"),
    }
    stored = MemoryStore(root).add("project", record)
    return stored["memory_id"]
