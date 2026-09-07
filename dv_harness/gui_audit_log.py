"""dv_harness/gui_audit_log.py -- Structured GUI Audit Log (2026-09-06)

Every dashboard POST /api/control command is a consequential action -- there
is no read-only command on that dispatch table -- and every one of them
already logs SOMETHING via `commands.py`'s own `h.store.event({"ts": ...,
"cmd": ...})` calls: a real, but ad hoc, per-command shape that differs from
one cmd_* function to the next (a "correct" event carries `note`/
`reset_attempts`; an "approve" event carries `reviewer_id`/`note`; neither
carries a `before`/`after` snapshot or a distinct `who`/`result` field).
Grepped before writing anything: no module anywhere in this repo produced a
FIXED-SHAPE record for a GUI action. `dashboard._audit_trail()` /
`dv-harness audit` already read that ad hoc trail back and print it verbatim
-- real, useful, and exactly what it is: a generic event log.

This module is a SECOND, STRUCTURED SHAPE over the SAME underlying
mechanism, not a second store. Every record here carries exactly the 7
named fields -- who / when / before / after / evidence / approval / result
-- plus the two small discriminator fields (`type`, `action`) needed to find
and identify one, and is written through the REAL, EXISTING
`dv_harness.storage.StateStore.event()` call (see `record_gui_action()`),
appending to the identical `.dv-harness/events.jsonl` file the generic trail
already reads. `dv-harness audit` / `GET /api/audit` therefore see these
records too (they are real events.jsonl lines, unchanged format); a reader
that wants ONLY the structured shape calls `read_gui_audit_log()`, which
filters on `type == GUI_AUDIT_RECORD_TYPE`.

Wiring: `wrap_dispatch()` is the ONE integration point. `dashboard.py`'s
`_handle_control()` calls it instead of calling `_dispatch_control()`
directly, so every dashboard-issued PAUSE / RESUME / TAKEOVER /
RELEASE_TAKEOVER / REDIRECT / APPROVE / CORRECT / CONSTRAINT_ADD /
CONSTRAINT_REMOVE / COSIGN / RESEARCH_APPROVE / RESEARCH_REJECT /
RESEARCH_HOLD gets exactly one structured record -- whether the dispatch
succeeds or raises -- with no change to `commands.py`'s own per-command
functions (and their existing generic events) at all.

Evidence Truth Rule, applied to every one of the 7 fields:
  - `who`  never a fabricated placeholder: the real request-supplied actor
    (reviewer_id/corrected_by/taken_by) or, absent one, the SAME real
    `control_plane._default_user()` OS-user resolution every cmd_* function
    already falls back to.
  - `when` a real ISO-8601 timestamp from `control_plane.now()`.
  - `before`/`after` a REAL, PASSIVE read of exactly the sub-state the
    dispatched command actually mutates -- never `StateStore.load()` /
    `ControlPlane.load()`, both of which MINT a default file on an absent
    one; capturing an audit snapshot must never itself be a mutating act.
    A command this module has no real scope mapping for reports an honest
    `_scope_status` reason rather than a guessed or empty-looking snapshot.
  - `evidence` the real request body that drove the action, JSON-round-
    tripped so a stored line always stays parseable.
  - `approval` the real approval/cosign entry THIS action itself granted
    (APPROVE / RESEARCH_APPROVE / COSIGN only) -- `None`, honestly, for
    every other command; never some OTHER stage's currently-active
    approval copied in to make the field look populated.
  - `result` a real `{"status": "OK"|"ERROR", ...}` -- the dispatched
    command's own return value, or the real exception it raised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .control_plane import now as _cp_now, _default_user

GUI_AUDIT_RECORD_TYPE = "GUI_AUDIT_RECORD"

# The 7 fields the task names, verbatim. Every record build_gui_audit_record()
# produces carries exactly these (plus the `type`/`action` discriminator --
# see module docstring for why those two are not counted among the 7: they
# identify a record rather than describing the audited action itself).
GUI_AUDIT_FIELDS = ("who", "when", "before", "after", "evidence", "approval", "result")

RESULT_OK = "OK"
RESULT_ERROR = "ERROR"
_RESULT_STATUSES = (RESULT_OK, RESULT_ERROR)


def _assert_no_verification_verdict_vocabulary() -> None:
    """This module's own result vocabulary (OK/ERROR) must never collide
    with a real stage verdict (dv_harness.models.Status) -- the same
    disjointness discipline several sibling modules in this codebase already
    apply to their own domain vocabularies."""
    from .models import Status
    collision = set(_RESULT_STATUSES) & {s.value for s in Status}
    if collision:
        raise AssertionError(
            f"gui_audit_log result vocabulary collides with models.Status: {sorted(collision)}")


_assert_no_verification_verdict_vocabulary()


class GuiAuditLogError(Exception):
    """Raised only for a caller-usage defect building a record -- a required
    KEY genuinely absent. Never raised for an honestly-absent VALUE (`None`
    is legal for `approval`/`before`/`after`), which is real evidence, not a
    bug."""


def build_gui_audit_record(*, who: str, when: str, action: str,
                            before: Any, after: Any, evidence: Any,
                            approval: Optional[Dict[str, Any]],
                            result: Dict[str, Any]) -> Dict[str, Any]:
    """The one constructor for a structured GUI audit record. `who`/`when`/
    `action` must be real, non-blank strings; `result` must be a dict
    carrying a `status` in {"OK","ERROR"}. `before`/`after`/`evidence`/
    `approval` may legitimately be `None` or `{}` -- that is real reported
    evidence (nothing to snapshot, no approval granted), never refused."""
    if not who or not str(who).strip():
        raise GuiAuditLogError("who is required (the real actor, never blank)")
    if not when or not str(when).strip():
        raise GuiAuditLogError("when is required (a real ISO-8601 timestamp)")
    if not action or not str(action).strip():
        raise GuiAuditLogError("action is required (the dispatched GUI command name)")
    if not isinstance(result, dict) or "status" not in result:
        raise GuiAuditLogError("result must be a dict carrying a real 'status' key")
    if result["status"] not in _RESULT_STATUSES:
        raise GuiAuditLogError(
            f"result.status must be one of {_RESULT_STATUSES}, got {result['status']!r}")
    return {
        "type": GUI_AUDIT_RECORD_TYPE,
        "action": action,
        "who": who,
        "when": when,
        "before": before,
        "after": after,
        "evidence": evidence,
        "approval": approval,
        "result": result,
    }


def record_gui_action(root: Path, *, who: str, action: str, before: Any, after: Any,
                       evidence: Any, approval: Optional[Dict[str, Any]],
                       result: Dict[str, Any], when: Optional[str] = None) -> Dict[str, Any]:
    """Builds one structured record (`build_gui_audit_record`) and writes it
    through the REAL, EXISTING `dv_harness.storage.StateStore.event()` --
    the same append-only `.dv-harness/events.jsonl` every `commands.cmd_*`
    generic `{"ts","cmd",...}` event already goes through. No second audit
    store is created or opened here."""
    from .storage import StateStore
    record = build_gui_audit_record(
        who=who, when=when or _cp_now(), action=action,
        before=before, after=after, evidence=evidence,
        approval=approval, result=result,
    )
    StateStore(Path(root)).event(record)
    return record


def _read_json_passive(path: Path) -> Optional[Dict[str, Any]]:
    """A plain, non-mutating read: returns None on anything short of a real,
    present, parseable JSON object -- never mints/creates `path`. Capturing a
    before/after snapshot for an audit record must never itself be a
    mutating act (unlike `StateStore.load()`/`ControlPlane.load()`, both of
    which materialize a default file on an absent one)."""
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# Which real /api/control commands mutate control.json (as opposed to
# state.json, for REDIRECT, or a capability-evolution candidate's own
# Blackboard-backed record, for RESEARCH_REJECT) -- used only to decide
# which passive reader capture_control_scope() reaches for.
_CONTROL_JSON_COMMANDS = frozenset({
    "PAUSE", "RESUME", "TAKEOVER", "RELEASE_TAKEOVER",
    "APPROVE", "CORRECT", "CONSTRAINT_ADD", "CONSTRAINT_REMOVE", "COSIGN",
    "RESEARCH_APPROVE", "RESEARCH_HOLD",
})

# Every real /api/control command this module knows how to scope a
# before/after snapshot for. wrap_dispatch() is never restricted to this set
# -- every dispatched command is audited regardless -- but a command outside
# it reports an honest NO_SCOPE_MAPPING_FOR_ACTION reason rather than a
# fabricated snapshot (see capture_control_scope()'s final branch).
KNOWN_SCOPED_ACTIONS = frozenset(_CONTROL_JSON_COMMANDS | {"REDIRECT", "RESEARCH_REJECT"})


def capture_control_scope(root: Path, action: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """The real current state of exactly the sub-record `action` is actually
    going to mutate -- read passively (`_read_json_passive`), never minted.
    Always carries `_scope_status` ("CAPTURED", or a real, named reason it
    could not be) so an honestly-absent snapshot (no control.json/state.json
    written yet; a candidate id that does not exist) is never presented as,
    or confused with, a real empty one.

    Scoped rather than a whole-file snapshot on purpose: an APPROVE for one
    stage must not carry every OTHER stage's unrelated approval/correction/
    cosign history into its own audit record."""
    root = Path(root)
    stage = body.get("stage")

    if action in ("PAUSE", "RESUME"):
        cp = _read_json_passive(root / ".dv-harness" / "control.json")
        if cp is None:
            return {"_scope_status": "NO_CONTROL_FILE_YET"}
        return {"_scope_status": "CAPTURED", "paused": cp.get("paused"),
                "paused_reason": cp.get("paused_reason"), "paused_at": cp.get("paused_at")}

    if action in ("TAKEOVER", "RELEASE_TAKEOVER"):
        cp = _read_json_passive(root / ".dv-harness" / "control.json")
        if cp is None:
            return {"_scope_status": "NO_CONTROL_FILE_YET"}
        return {"_scope_status": "CAPTURED", "takeover": cp.get("takeover")}

    if action == "REDIRECT":
        st = _read_json_passive(root / ".dv-harness" / "state.json")
        if st is None:
            return {"_scope_status": "NO_STATE_FILE_YET"}
        return {"_scope_status": "CAPTURED", "current_stage": st.get("current_stage")}

    if action == "APPROVE":
        cp = _read_json_passive(root / ".dv-harness" / "control.json")
        if cp is None:
            return {"_scope_status": "NO_CONTROL_FILE_YET"}
        return {"_scope_status": "CAPTURED", "stage": stage,
                "approval": (cp.get("approvals") or {}).get(stage) if stage else None}

    if action == "CORRECT":
        cp = _read_json_passive(root / ".dv-harness" / "control.json")
        if cp is None:
            return {"_scope_status": "NO_CONTROL_FILE_YET"}
        return {"_scope_status": "CAPTURED", "stage": stage,
                "correction": (cp.get("corrections") or {}).get(stage) if stage else None}

    if action in ("CONSTRAINT_ADD", "CONSTRAINT_REMOVE"):
        cp = _read_json_passive(root / ".dv-harness" / "control.json")
        if cp is None:
            return {"_scope_status": "NO_CONTROL_FILE_YET"}
        return {"_scope_status": "CAPTURED", "constraints": cp.get("constraints") or []}

    if action == "COSIGN":
        cp = _read_json_passive(root / ".dv-harness" / "control.json")
        if cp is None:
            return {"_scope_status": "NO_CONTROL_FILE_YET"}
        field_path = body.get("field_path")
        stage_cosigns = (cp.get("cosigns") or {}).get(stage, {}) if stage else {}
        return {"_scope_status": "CAPTURED", "stage": stage, "field_path": field_path,
                "cosign": stage_cosigns.get(field_path) if field_path else None}

    if action in ("RESEARCH_APPROVE", "RESEARCH_HOLD"):
        cp = _read_json_passive(root / ".dv-harness" / "control.json")
        if cp is None:
            return {"_scope_status": "NO_CONTROL_FILE_YET"}
        from .capability_evolution import HUMAN_APPROVAL_STAGE
        return {"_scope_status": "CAPTURED",
                "approval": (cp.get("approvals") or {}).get(HUMAN_APPROVAL_STAGE)}

    if action == "RESEARCH_REJECT":
        candidate_id = body.get("candidate_id")
        if not candidate_id:
            return {"_scope_status": "NO_CANDIDATE_ID"}
        try:
            from . import capability_evolution as ce
            candidate = ce.read_candidate(root, candidate_id)
        except Exception:
            candidate = None
        return {"_scope_status": "CAPTURED" if candidate is not None else "CANDIDATE_NOT_FOUND",
                "candidate_id": candidate_id,
                "current_status": candidate.get("current_status") if candidate else None}

    return {"_scope_status": f"NO_SCOPE_MAPPING_FOR_ACTION:{action}"}


def extract_who(body: Dict[str, Any]) -> str:
    """The real actor for this GUI action: whichever of `reviewer_id` /
    `corrected_by` / `taken_by` the request body itself names (the SAME real
    fields `commands.py`'s own cmd_* functions already accept), falling back
    to the identical real OS-user resolution `control_plane._default_user()`
    already uses -- never a fabricated placeholder string."""
    for key in ("reviewer_id", "corrected_by", "taken_by"):
        value = body.get(key)
        if value and str(value).strip():
            return str(value)
    return _default_user()


# The only 3 real /api/control commands that grant a ControlPlane approval
# or cosign entry -- see ControlPlane.approve()/add_cosign() and
# commands.cmd_research_approve(). Every other command's `approval` field is
# honestly None.
_APPROVAL_ACTIONS = frozenset({"APPROVE", "RESEARCH_APPROVE", "COSIGN"})


def extract_approval(action: str, result: Any) -> Optional[Dict[str, Any]]:
    """The approval/cosign entry THIS action itself granted, when `action`
    is one of the 3 real approval-granting commands. Every other command's
    `approval` is `None` -- a PAUSE is not an approval action, and copying in
    some OTHER stage's currently-active approval would misrepresent what
    this record is actually about."""
    if action not in _APPROVAL_ACTIONS or not isinstance(result, dict):
        return None
    if action == "RESEARCH_APPROVE":
        # cmd_research_approve()'s own return shape nests the real
        # ControlPlane approval entry under "approval".
        nested = result.get("approval")
        return dict(nested) if isinstance(nested, dict) else None
    # cmd_approve()/cmd_cosign() both return {"stage": ..., **entry}, where
    # `entry` already carries these real ControlPlane fields.
    keys = ("reviewer_id", "reviewer_confidence", "note", "approved_at",
            "cosigned_at", "value", "field_path")
    approval = {k: result[k] for k in keys if k in result}
    return approval or None


def _safe_evidence(body: Dict[str, Any]) -> Any:
    """The real request body that drove this action -- the record's own
    `evidence` field. JSON-round-tripped so the stored events.jsonl line
    always stays parseable even if a caller's COSIGN `value` carries some
    exotic JSON-adjacent type; a body that fails to round-trip at all is
    reported as a string repr rather than silently dropped."""
    try:
        return json.loads(json.dumps(body, ensure_ascii=False, default=str))
    except Exception:
        return {"_unserializable_body_repr": repr(body)}


def wrap_dispatch(root: Path, body: Dict[str, Any],
                   dispatch_fn: Callable[[Path, Dict[str, Any]], Any]) -> Any:
    """Runs `dispatch_fn(root, body)` -- dashboard.py's real
    `_dispatch_control()`, or any callable sharing its `(root, body) ->
    result` signature -- and writes exactly ONE structured GUI audit record
    for it before returning the real result or re-raising the real
    exception unchanged. This is the ONE integration point: dashboard.py's
    POST /api/control handler calls this instead of `_dispatch_control()`
    directly, so every dispatched command is audited with no change needed
    to `commands.py`'s own per-command functions (or their existing generic
    events) at all -- every real /api/control command mutates project
    state, so every one is a consequential GUI action."""
    root = Path(root)
    action = body.get("command") or "UNKNOWN"
    who = extract_who(body)
    evidence = _safe_evidence(body)
    before = capture_control_scope(root, action, body)
    try:
        result = dispatch_fn(root, body)
    except Exception as exc:
        after = capture_control_scope(root, action, body)
        record_gui_action(
            root, who=who, action=action, before=before, after=after,
            evidence=evidence, approval=None,
            result={"status": RESULT_ERROR, "error_type": type(exc).__name__, "message": str(exc)},
        )
        raise
    after = capture_control_scope(root, action, body)
    record_gui_action(
        root, who=who, action=action, before=before, after=after,
        evidence=evidence, approval=extract_approval(action, result),
        result={"status": RESULT_OK, "value": result},
    )
    return result


def read_gui_audit_log(root: Path, *, limit: Optional[int] = None,
                        action: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every structured `GUI_AUDIT_RECORD_TYPE` line in
    `.dv-harness/events.jsonl` -- oldest first, matching
    `dashboard._tail_events()`'s own convention -- filtered out of the SAME
    file the generic `/api/audit` trail reads, never a second store.
    `limit` (if given) keeps the last N matching records; `action` (if
    given) narrows to one GUI command. A line that fails to parse (a torn
    write caught mid-append) is skipped, not fatal -- matching
    `dashboard._tail_events()`'s own tolerance."""
    root = Path(root)
    events_file = root / ".dv-harness" / "events.jsonl"
    if not events_file.exists():
        return []
    try:
        raw = events_file.read_text(encoding="utf-8")
    except Exception:
        return []
    records: List[Dict[str, Any]] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict) or obj.get("type") != GUI_AUDIT_RECORD_TYPE:
            continue
        if action and obj.get("action") != action:
            continue
        records.append(obj)
    if limit:
        records = records[-max(limit, 0):]
    return records


def execute_verb(argv) -> int:
    """`python -m dv_harness.gui_audit_log show [--root .] [--limit 50]
    [--action APPROVE] [--json]` -- an ad hoc reader; no `dv-harness` CLI
    verb was added (cli.py is a large, actively-evolving argparse tree),
    matching several sibling standalone modules' own disclosed choice."""
    import argparse
    parser = argparse.ArgumentParser(prog="python -m dv_harness.gui_audit_log")
    parser.add_argument("verb", choices=["show"])
    parser.add_argument("--root", default=".")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--action")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    records = read_gui_audit_log(Path(args.root), limit=args.limit, action=args.action)
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        if not records:
            print("No structured GUI audit records found.")
        for r in records:
            result = r.get("result") or {}
            print(f"{r.get('when')}  {str(r.get('action')):<20} "
                  f"who={r.get('who')}  result={result.get('status')}")
    return 0


def main() -> None:
    import sys
    sys.exit(execute_verb(sys.argv[1:]))


if __name__ == "__main__":
    main()
