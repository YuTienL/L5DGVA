from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

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


_ABSENT = object()


def delete_param(root: Path, gate_id: str, name: str) -> None:
    """Removes a single (gate_id, name) entry from parameters.json entirely,
    so a subsequent get_param() call falls back to the gate's own hardcoded
    default again -- the real "restore to unset" counterpart to set_param()
    (Finding I3: a revert of a param that was never actually set before the
    self-tuning apply must delete the key, not write back some fabricated
    value). If gate_id's own sub-dict becomes empty as a result, the whole
    gate_id key is dropped too (kept minimal/tidy) rather than leaving an
    empty {} behind -- either choice is behaviorally identical to
    get_param() (an absent gate_id and an empty dict under it both fall
    through to `default`), this just keeps the on-disk file smaller.
    No-op (does not raise) if the file, gate_id, or name doesn't exist."""
    data = _read_json(_params_path(root), {})
    if not isinstance(data, dict):
        return
    gate_params = data.get(gate_id)
    if not isinstance(gate_params, dict) or name not in gate_params:
        return
    del gate_params[name]
    if not gate_params:
        del data[gate_id]
    _write_json_atomic(_params_path(root), data)


def capture_prior_param_state(root: Path, gate_id: str, name: str) -> Dict[str, Any]:
    """Real backing for Finding I3: captures whatever get_param() would
    currently return for (gate_id, name) -- BEFORE a caller is about to
    apply_proposal() a param-change -- as a JSON-serializable
    {"prior_was_absent": bool, "prior_value": <value or None>} pair meant
    to be threaded through to record_adjustment() and later consulted by a
    revert. A private, non-serializable sentinel (never written to disk)
    distinguishes "no entry existed at all" from a real prior value of
    None/0/False/"" -- get_param()'s own `default` parameter already
    supports exactly this distinction, it's just never been used for
    anything other than a gate script's own hardcoded fallback before."""
    value = get_param(root, gate_id, name, _ABSENT)
    if value is _ABSENT:
        return {"prior_was_absent": True, "prior_value": None}
    return {"prior_was_absent": False, "prior_value": value}


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


# Finding I1 fix (2026-09-02 final-review fix wave): this list previously
# lived ONLY inside tools/verification_flow/self_tuning_proposal_gate.py,
# which the CLI `self-tune approve` path (dv_harness/cli.py) never invokes
# -- approving a stored PENDING record for one of these parameters went
# straight to apply_proposal() -> set_param() with no protection at all.
# Moved here (the real engine module, same home as PROTECTED_REMOVALS) and
# enforced directly inside apply_proposal() below, so every caller --
# engine.py's AUTO_APPLY path, the CLI approve path, anything else that
# ever calls apply_proposal() -- gets real protection for free. The
# proposal gate script now imports this constant from here (see that
# script's own header) instead of maintaining its own separate copy, the
# same pattern it already used for PROTECTED_REMOVALS.
PROTECTED_PARAMETERS = {
    ("fix_risk_approval_gate", "risk_classification_threshold"),
    ("deep_rca_evidence_gate", "min_hypothesis_count"),
    ("root_cause_evidence_gate", "min_hypothesis_count"),
    ("regression_submission_policy_gate", "wave_default_off"),
    ("regression_submission_policy_gate", "require_prior_failure_ref"),
}


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


def read_last_reviewed_index(root: Path) -> int:
    """The gate_history.jsonl line index (per gate_history_length()'s own
    line-count convention) up through which the last SUCCESSFUL self-tuning
    review cycle already consumed history -- read_gate_history_since()
    callers use this instead of always re-reading the full cumulative log
    since project inception. Defaults to 0 (read from the very start) for a
    project that has never completed a review cycle, or whose state.json
    predates this field."""
    return read_execution_state(root).get("last_reviewed_gate_history_index", 0)


def reset_execution_counter(root: Path, last_reviewed_index: Optional[int] = None) -> None:
    """Always zeroes executions_since_last_review. When last_reviewed_index
    is given (engine.py's _maybe_run_self_tuning_review passes it only on a
    SUCCESSFUL review cycle's normal completion path, never on an internal-
    failure early-reset), also advances last_reviewed_gate_history_index so
    the NEXT cycle's read_gate_history_since() call only sees history
    entries appended after this one -- see read_last_reviewed_index()'s
    docstring. Reads the existing state first and updates it in place
    (rather than overwriting the whole file with a fresh dict) specifically
    so an internal-failure reset (last_reviewed_index omitted) never
    clobbers an index a prior successful cycle already advanced."""
    state = read_execution_state(root)
    state["executions_since_last_review"] = 0
    if last_reviewed_index is not None:
        state["last_reviewed_gate_history_index"] = last_reviewed_index
    _write_json_atomic(_state_path(root), state)


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


def _compute_elevated_scrutiny_gates() -> set:
    """Finding I4 fix (2026-09-02 final-review fix wave): this was a
    hardcoded 14-entry literal that had already drifted from the real
    STAGE_GATES table (missing fix_effectiveness_gate, a real live RE_AUDIT
    gate added after the literal was written). Computed the same way
    PROTECTED_REMOVALS is computed just above -- union of RE_AUDIT's and
    FAILURE_RECOVERY's real gate_ids (the spec's own rule: "anything in
    RE_AUDIT's or FAILURE_RECOVERY's gate list not already fully
    protected"), minus whatever gate_id already appears in PROTECTED_REMOVALS
    (a gate that can never even be REMOVED needs no extra elevated-scrutiny
    defer-on-param-change treatment layered on top). Same lazy
    `from . import gates` pattern as _compute_protected_removals() to avoid
    the import cycle (gates.py itself imports this module)."""
    from . import gates as _gates
    ids = set()
    for stage in ("RE_AUDIT", "FAILURE_RECOVERY"):
        for entry in _gates.STAGE_GATES.get(stage, []):
            ids.add(entry[0])
    protected_gate_ids = {gate_id for (_stage, gate_id) in PROTECTED_REMOVALS}
    return ids - protected_gate_ids


ELEVATED_SCRUTINY_GATES = _compute_elevated_scrutiny_gates()


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
    # Finding C1 fix (2026-09-02 final-review fix wave): an "add" proposal
    # is a membership change exactly like "remove" -- effective_stage_gates()
    # (dv_harness/gates.py) materializes an unrecognized add gate_id as a
    # placeholder (gate_id, "<gate_id>.py", "--evidence") entry that can
    # never produce a passing evidence block (no such script exists on
    # disk), permanently breaking that stage with no auto-rollback if it is
    # ever auto-applied. The spec's own auto-apply rule is "the change is a
    # parameter adjustment (not a membership change)" -- both "add" and
    # "remove" are membership changes and must always defer to a human.
    if change.get("action") in ("add", "remove"):
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
        # Finding I2 fix (2026-09-02 final-review fix wave): propose_remove_
        # override() returns False (writing nothing) when (stage, gate_id) is
        # in PROTECTED_REMOVALS -- this used to be silently discarded here,
        # so an "approve" of a protected removal would still get recorded as
        # if it had genuinely succeeded. Raise the same way every other
        # apply_proposal() failure mode already does, so callers (engine.py,
        # cli.py's approve handler) can catch it and record the real outcome
        # instead of a misleading APPLIED.
        applied = propose_remove_override(root, stage, change["gate_id"])
        if not applied:
            raise ValueError(
                f"remove proposal for gate {change['gate_id']!r} on stage {stage!r} "
                f"blocked: this (stage, gate_id) pair is in PROTECTED_REMOVALS "
                f"and can never be removed"
            )
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
        # Finding I1 fix (2026-09-02 final-review fix wave): PROTECTED_
        # PARAMETERS was previously enforced ONLY inside the LLM-analysis
        # proposal gate (tools/verification_flow/self_tuning_proposal_gate.py)
        # -- the CLI `self-tune approve` path calls apply_proposal() directly
        # and never re-runs that gate, so approving a stored PENDING record
        # targeting a protected parameter silently overwrote a
        # safety-critical threshold. Enforced here, the one real
        # apply-time chokepoint every caller goes through.
        if (gate_id, change["param"]) in PROTECTED_PARAMETERS:
            raise ValueError(
                f"param-change proposal for gate {gate_id!r} targets protected "
                f"parameter {change['param']!r}: (gate_id, param) is in "
                f"PROTECTED_PARAMETERS and can never be auto-applied or approved"
            )
        set_param(root, gate_id, change["param"], change["to"])


def record_adjustment(root: Path, proposal: Dict[str, Any], status: str,
                       applied_by: str = "system",
                       prior_value: Any = None, prior_was_absent: Optional[bool] = None) -> str:
    """prior_value/prior_was_absent (Finding I3, 2026-09-02 final-review fix
    wave) are only meaningful for a param-change proposal that has actually
    been applied -- the REAL previously-in-effect state, as captured by
    capture_prior_param_state() immediately before apply_proposal() ran, NOT
    the proposal's own self-reported change["from"] (which may be a
    hallucinated or stale value, or simply absent if the parameter had never
    been set before). Left at their None/None defaults for add/remove
    proposals and for a proposal recorded as PENDING (nothing has been
    applied yet, so there is no real prior state to capture). cli.py's
    `self-tune revert` handler consults these fields instead of
    change["from"] for a param-change record."""
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
        "prior_value": prior_value,
        "prior_was_absent": prior_was_absent,
    }
    stored = MemoryStore(root).add("project", record)
    return stored["memory_id"]


def gate_ids_with_recent_reverts(root: Path) -> set:
    """Real backing for classify_proposal()'s recent_reverts anti-thrashing
    parameter (bundled fix alongside I3, 2026-09-02 final-review fix wave):
    engine.py's _maybe_run_self_tuning_review() previously hardcoded
    recent_reverts=set(), so that defer rule could never actually fire even
    though the data (REVERTED self_tuning_adjustment records, written by
    cli.py's `self-tune revert` via record_adjustment/store.add) already
    exists. Same _index()-then-get() enumeration pattern cli.py's
    _project_self_tuning_records() helper already uses.

    DESIGN JUDGMENT CALL: "recent" is scoped here to "any REVERTED record
    for this gate_id currently exists in project memory" -- no time window
    or review-cycle count. The finding explicitly says this coarser rule is
    acceptable for this fix wave ("no time-window logic needed... that's a
    refinement for later"); a gate_id that was ever reverted defers forever
    under this rule until a human explicitly re-approves a fresh proposal
    for it, which is a conservative (safe) default, not a correctness bug --
    but a real future refinement (e.g. only the last N cycles, or a
    timestamp-based window) may want to narrow this."""
    from .memory import MemoryStore
    store = MemoryStore(root)
    reverted_gate_ids = set()
    for entry in store._index():
        if entry.get("level") != "project":
            continue
        rec = store.get(entry["memory_id"])
        if rec and rec.get("kind") == "self_tuning_adjustment" and rec.get("status") == "REVERTED":
            gate_id = rec.get("gate_id")
            if gate_id:
                reverted_gate_ids.add(gate_id)
    return reverted_gate_ids
