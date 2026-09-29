"""dv_harness/waiver_store.py -- the durable, human-authored waiver ledger at
.dv-harness/waivers/waivers.json, and (since 2026-09-06) the SOURCE OF TRUTH
the three waiver gate scripts under tools/verification_flow/ read their waiver
records from.

Before 2026-09-06 this module was a persistence layer nothing consumed: this
docstring itself disclosed that "there is no fixed harness code path today
that reads a waivers store from a known location before invoking a gate", and
dv_harness/gates.run_gate() assembled every waiver gate's payload purely from
the agent's own fenced ```dv-harness-evidence:<gate_id>``` block. A waiver was
therefore SELF-ATTESTED end to end -- the same agent wrote both the waiver and
the evidence that the waiver was still valid, and an expired waiver simply
stopped being mentioned.

What changed:

- `waiver_scope_consistency_gate`, `waiver_revision_freshness_gate` and
  `waiver_revalidation_gate` now read this store directly (through the
  DV_HARNESS_PACKAGE_ROOT / DV_HARNESS_PROJECT_ROOT env vars run_gate()
  supplies, the same mechanism rtl_write_scope_guard_gate.py already uses).
  When a store file EXISTS it is authoritative: the records evaluated are the
  store's, and an agent-declared waiver_id with no store record FAILs
  WAIVER_NOT_IN_STORE. A project with no store file keeps the original
  agent-attested behavior byte-identically, so a project that has not adopted
  the store is never retroactively failed.
- The record shape is spec section 237's own field list (waiver_id / item /
  reason / evidence / scope / approver / affected_version / risk /
  created_at / expiration+revalidation trigger / status), and `status` is
  section 237's five-value vocabulary: VALID / REVALIDATION_REQUIRED /
  EXPIRED / REVOKED / UNKNOWN.

`status` is DERIVED by `derive_status()` on every read and is REFUSED as a
stored field by `record_waiver()` -- a stored status is wrong the instant the
spec revision moves or the expiry passes, the same reason
`golden_scenario.evaluate_freshness()` computes freshness rather than storing
it.

"We could not check" is never VALID. A record missing section 237's fields, a
record declaring neither an expiry nor a revalidation trigger (nothing about
it can ever go stale, so nothing can show it is still good), and an
unparseable timestamp all derive UNKNOWN with a real reason.

This module ARBITRATES nothing. It records what a human approved and reports
what that record's own content implies; it revokes no waiver, revalidates
none, and grants no approval. Recording a waiver is a human act performed
through the dashboard form (POST /api/waiver) or `record_waiver()`.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .storage import _atomic_replace

SCHEMA_VERSION = "1.0"

# The original 4-field contract the dashboard's waiver form posts. Unchanged
# and still accepted by append_waiver(): a legacy record is real human intent
# and must not be dropped. It cannot, however, be shown to still be valid --
# it carries no expiry and no revalidation trigger -- so derive_status()
# reports it UNKNOWN with a reason naming the missing section 237 fields.
REQUIRED_FIELDS = ("gate_id", "item_id", "approved", "evidence")

# Spec section 237's own waiver record field list. `expiration/revalidation
# trigger` is `expires_at` and/or `revalidation_trigger` (at least one is
# required by derive_status, not by the schema, because which of the two a
# waiver carries is the approver's decision); `status` is derived, never
# stored.
CANONICAL_REQUIRED_FIELDS = (
    "waiver_id", "item", "reason", "evidence", "scope", "approver",
    "affected_version", "risk", "created_at",
)

# Spec section 237's status vocabulary, verbatim.
WAIVER_STATUSES = ("VALID", "REVALIDATION_REQUIRED", "EXPIRED", "REVOKED", "UNKNOWN")

# The gate-script FAIL reason each non-VALID status maps to. EXPIRED and
# REVALIDATION_REQUIRED reuse waiver_revalidation_gate.py's OWN pre-existing
# reason tokens rather than minting synonyms for them.
STATUS_FAIL_REASONS = {
    "EXPIRED": "WAIVER_EXPIRED",
    "REVALIDATION_REQUIRED": "WAIVER_REVALIDATION_REQUIRED",
    "REVOKED": "WAIVER_REVOKED",
    "UNKNOWN": "WAIVER_STATUS_UNKNOWN",
}

# The three gates that validate waiver records. A store record may name one of
# them in `gate_id`; because all three check the SAME waiver records from
# different angles (scope completeness / revision freshness / expiry and
# revalidation), a record targeted at any member applies to every member. A
# record naming a gate outside this family (e.g. coverage_hole_regeneration_gate)
# is not a waiver-gate record and is not returned to these three.
WAIVER_GATE_FAMILY = (
    "waiver_scope_consistency_gate",
    "waiver_revision_freshness_gate",
    "waiver_revalidation_gate",
)

# The scope fields waiver_scope_consistency_gate.py requires of every waiver.
SCOPE_FIELDS = (
    "requirement_ids", "subsystem", "spec_revision",
    "design_evidence_hash", "approval_id", "scope_hash",
)

# Which revalidation triggers may be DECLARED. Restricted to the facts one of
# the three gates really measures on a run -- declaring a trigger nothing
# checks would produce a waiver that silently reads VALID forever.
# record_waiver() refuses an unsupported key by name.
SUPPORTED_TRIGGER_KEYS = ("spec_revision", "rtl_hash", "revision")

# What each gate can independently supply to derive_status(). The three run in
# the SAME stage (REQUIREMENTS_TRACEABILITY), so between them every supported
# trigger key and the expiry are really checked on every run --
# assert_trigger_coverage() holds that, so adding a trigger key without a gate
# that measures it fails a test rather than producing an unchecked waiver.
GATE_STATUS_CONTEXT = {
    "waiver_scope_consistency_gate": {"current_keys": (), "checks_expiry": False},
    "waiver_revision_freshness_gate": {"current_keys": ("spec_revision", "rtl_hash"), "checks_expiry": False},
    "waiver_revalidation_gate": {"current_keys": ("revision",), "checks_expiry": True},
}


class WaiverStoreError(ValueError):
    """A waiver record refused by record_waiver(). Never raised on a read."""


def assert_trigger_coverage() -> None:
    """Every SUPPORTED_TRIGGER_KEYS entry is really measured by at least one
    gate, and at least one gate really checks expiry. Called at import so an
    unchecked trigger can never be declared."""
    measured = set()
    expiry_checked = False
    for spec in GATE_STATUS_CONTEXT.values():
        measured.update(spec["current_keys"])
        expiry_checked = expiry_checked or spec["checks_expiry"]
    missing = sorted(set(SUPPORTED_TRIGGER_KEYS) - measured)
    if missing:
        raise AssertionError(
            f"revalidation trigger keys no waiver gate measures: {missing} -- "
            "a declared trigger nothing checks would read VALID forever"
        )
    if not expiry_checked:
        raise AssertionError("no waiver gate checks expiry; every expires_at would be unchecked")


assert_trigger_coverage()


# --- store I/O ------------------------------------------------------------

def _store_path(root: Path) -> Path:
    return Path(root) / ".dv-harness" / "waivers" / "waivers.json"


def store_exists(root: Path) -> bool:
    """True when this project has a waiver ledger on disk. This is the switch
    that makes the store authoritative for the three gates -- a project with
    no ledger keeps the original agent-attested path."""
    return _store_path(root).is_file()


def read_waivers(root: Path) -> List[Dict[str, Any]]:
    path = _store_path(root)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_waivers(root: Path, waivers: List[Dict[str, Any]]) -> None:
    path = _store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, dir=str(path.parent), encoding="utf-8"
    )
    try:
        json.dump(waivers, tmp, indent=2)
        tmp.close()
        _atomic_replace(tmp.name, path)
    except Exception:
        tmp.close()
        try:
            Path(tmp.name).unlink()
        except FileNotFoundError:
            pass
        raise


def append_waiver(root: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    """The dashboard form's writer. Accepts BOTH the original 4-field record
    and a full section 237 record (dispatched to record_waiver() when it
    carries a waiver_id), so an existing caller is never broken and a caller
    supplying the real thing gets the real validation."""
    if isinstance(record, dict) and record.get("waiver_id"):
        return record_waiver(root, record)
    missing = [f for f in REQUIRED_FIELDS if f not in record or record[f] in (None, "")]
    if missing:
        raise ValueError(f"waiver record missing required fields: {missing}")
    record = dict(record)
    record["recorded_at"] = time.time()
    waivers = read_waivers(root)
    waivers.append(record)
    _write_waivers(root, waivers)
    return record


def record_waiver(root: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    """Record one section 237 waiver. Refuses:
      - a missing canonical field (section 237's own list),
      - a caller-supplied `status` (derived on every read, never stored),
      - a revalidation trigger key no gate measures,
      - a duplicate waiver_id (update it through revoke/revalidate instead of
        letting two records claim one id and disagree),
      - a scope missing any field waiver_scope_consistency_gate requires.
    """
    if not isinstance(record, dict):
        raise WaiverStoreError("waiver record must be a mapping")
    record = dict(record)
    if "status" in record:
        raise WaiverStoreError(
            "waiver `status` is derived from the record's own content on every "
            "read (derive_status()) and must not be stored -- a stored status "
            "is wrong the instant the expiry passes or the revision moves"
        )
    missing = [f for f in CANONICAL_REQUIRED_FIELDS if not record.get(f)]
    if missing:
        raise WaiverStoreError(f"waiver record missing section 237 fields: {missing}")
    scope = record.get("scope")
    if not isinstance(scope, dict):
        raise WaiverStoreError("waiver `scope` must be a mapping")
    missing_scope = [f for f in SCOPE_FIELDS if not scope.get(f)]
    if missing_scope:
        raise WaiverStoreError(f"waiver scope missing fields: {missing_scope}")
    affected = record.get("affected_version")
    if not isinstance(affected, dict):
        raise WaiverStoreError("waiver `affected_version` must be a mapping")
    trigger = record.get("revalidation_trigger") or {}
    if not isinstance(trigger, dict):
        raise WaiverStoreError("waiver `revalidation_trigger` must be a mapping")
    unsupported = sorted(set(trigger) - set(SUPPORTED_TRIGGER_KEYS))
    if unsupported:
        raise WaiverStoreError(
            f"revalidation_trigger keys no waiver gate measures: {unsupported}; "
            f"supported: {list(SUPPORTED_TRIGGER_KEYS)}"
        )
    if not record.get("expires_at") and not trigger:
        raise WaiverStoreError(
            "waiver declares neither `expires_at` nor `revalidation_trigger`; "
            "section 237 requires an expiration/revalidation trigger, and a "
            "waiver with neither can never be shown to still be valid"
        )
    gate_id = record.get("gate_id")
    if gate_id and gate_id not in WAIVER_GATE_FAMILY:
        raise WaiverStoreError(
            f"gate_id {gate_id!r} is not one of the waiver gates {list(WAIVER_GATE_FAMILY)}"
        )
    waivers = read_waivers(root)
    if any(w.get("waiver_id") == record["waiver_id"] for w in waivers):
        raise WaiverStoreError(f"waiver_id already recorded: {record['waiver_id']}")
    record["schema_version"] = SCHEMA_VERSION
    record["recorded_at"] = time.time()
    waivers.append(record)
    _write_waivers(root, waivers)
    return record


def revoke_waiver(root: Path, waiver_id: str, revoked_by: str, reason: str) -> Dict[str, Any]:
    """Mark one recorded waiver REVOKED. A revocation is a human act and is
    recorded as one: `revoked_by` and `revoked_reason` are required, matching
    the discipline loop_budget.reset() applies to clearing a spend."""
    if not revoked_by or not reason:
        raise WaiverStoreError("revoking a waiver requires both revoked_by and a reason")
    waivers = read_waivers(root)
    for w in waivers:
        if w.get("waiver_id") == waiver_id:
            w["revoked"] = True
            w["revoked_by"] = revoked_by
            w["revoked_reason"] = reason
            w["revoked_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
            _write_waivers(root, waivers)
            return w
    raise WaiverStoreError(f"no waiver recorded with waiver_id={waiver_id!r}")


# --- status derivation ----------------------------------------------------

def parse_timestamp(value: Any) -> Optional[_dt.datetime]:
    """ISO-8601 -> aware datetime, or None when unparseable. Mirrors
    waiver_revalidation_gate.py's own `Z` handling so the two agree."""
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def derive_status(record: Dict[str, Any],
                  now: Any = None,
                  current: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """Section 237's five-value status, DERIVED from the record's own content
    plus the caller's real current facts. Returns (status, reason).

    Worst-first, so a revoked-and-also-expired waiver reads REVOKED (the human
    decision outranks the clock):
      REVOKED -> UNKNOWN (uncheckable) -> EXPIRED -> REVALIDATION_REQUIRED -> VALID

    `now` is checked only when supplied, and a trigger key only when `current`
    carries it: the three gates split those facts between them and all three
    run in the same stage (GATE_STATUS_CONTEXT / assert_trigger_coverage()).
    """
    current = dict(current or {})
    if not isinstance(record, dict):
        return "UNKNOWN", "WAIVER_RECORD_NOT_A_MAPPING"
    if record.get("revoked") is True:
        return "REVOKED", "REVOKED_BY:" + str(record.get("revoked_by") or "UNRECORDED")
    missing = [f for f in CANONICAL_REQUIRED_FIELDS if not record.get(f)]
    if missing:
        return "UNKNOWN", "MISSING_SECTION_237_FIELDS:" + ",".join(missing)
    expires_at = record.get("expires_at")
    trigger = record.get("revalidation_trigger") or {}
    if not expires_at and not trigger:
        return "UNKNOWN", "NO_EXPIRATION_AND_NO_REVALIDATION_TRIGGER_DECLARED"
    if expires_at:
        expiry = parse_timestamp(expires_at)
        if expiry is None:
            return "UNKNOWN", f"UNPARSEABLE_EXPIRES_AT:{expires_at}"
        reference = parse_timestamp(now)
        if now is not None and reference is None:
            return "UNKNOWN", f"UNPARSEABLE_CURRENT_TIME:{now}"
        if reference is not None and reference > expiry:
            return "EXPIRED", f"EXPIRED_AT:{expires_at}"
    if record.get("trigger_conditions_changed") is True:
        return "REVALIDATION_REQUIRED", "TRIGGER_CONDITIONS_CHANGED_DECLARED"
    revalidated_for = record.get("revalidated_for") or {}
    for key in sorted(trigger):
        approved_value = trigger[key]
        observed = current.get(key)
        if observed in (None, ""):
            continue  # not measured by THIS gate; another gate in the stage measures it
        if str(observed) == str(approved_value):
            continue
        if str(revalidated_for.get(key, "")) == str(observed):
            continue
        return "REVALIDATION_REQUIRED", f"{key.upper()}_CHANGED:{approved_value}->{observed}"
    return "VALID", "WITHIN_EXPIRY_AND_NO_TRIGGER_FIRED"


# --- gate-facing projection ----------------------------------------------

def _legacy_waiver_id(record: Dict[str, Any]) -> str:
    """A legacy 4-field record carries no waiver_id. It gets a derived one so
    it can still be NAMED in a gate finding -- never so it can pass as a
    section 237 record (derive_status() reports it UNKNOWN)."""
    return f"{record.get('gate_id') or 'unknown_gate'}:{record.get('item_id') or 'unknown_item'}"


def waiver_id_of(record: Dict[str, Any]) -> str:
    return str(record.get("waiver_id") or _legacy_waiver_id(record))


def waivers_for_gate(root: Path, gate_id: str) -> List[Dict[str, Any]]:
    """Every stored record that applies to one waiver gate. A record naming no
    gate applies to all three; a record naming a gate outside
    WAIVER_GATE_FAMILY belongs to a different gate and is not returned."""
    if gate_id not in WAIVER_GATE_FAMILY:
        raise WaiverStoreError(f"{gate_id!r} is not a waiver gate: {list(WAIVER_GATE_FAMILY)}")
    out = []
    for record in read_waivers(root):
        if not isinstance(record, dict):
            continue
        target = record.get("gate_id")
        if target and target not in WAIVER_GATE_FAMILY:
            continue
        out.append(record)
    return out


def _projection(record: Dict[str, Any], gate_id: str, status: str) -> Dict[str, Any]:
    """One store record rendered into the field names one gate script reads.
    The three scripts spell the same waiver three different ways; this is the
    single place that knows the mapping."""
    scope = record.get("scope") or {}
    affected = record.get("affected_version") or {}
    revalidated_for = record.get("revalidated_for") or {}
    wid = waiver_id_of(record)
    if gate_id == "waiver_scope_consistency_gate":
        out: Dict[str, Any] = {"waiver_id": wid}
        for field in SCOPE_FIELDS:
            out[field] = scope.get(field)
        if scope.get("applied_requirement_ids"):
            out["applied_requirement_ids"] = scope["applied_requirement_ids"]
        if record.get("active_failure_ids"):
            out["active_failure_ids"] = record["active_failure_ids"]
        return out
    if gate_id == "waiver_revision_freshness_gate":
        return {
            "waiver_id": wid,
            "spec_revision": affected.get("spec_revision"),
            "rtl_hash": affected.get("rtl_hash"),
            "revalidated": bool(revalidated_for),
            "revalidation_evidence_hash": record.get("revalidation_evidence_hash"),
            "expired": status == "EXPIRED",
        }
    return {
        "waiver_id": wid,
        # `approved` is section 237's `approver` field having a real value and
        # the waiver not having been revoked -- never a self-attested boolean.
        "approved": bool(record.get("approver")) and record.get("revoked") is not True,
        "evidence": record.get("evidence"),
        "revision": affected.get("revision"),
        "revalidated_for_revision": revalidated_for.get("revision"),
        "expires_at": record.get("expires_at"),
        "trigger_conditions_changed": bool(record.get("trigger_conditions_changed")),
    }


def gate_records(root: Path, gate_id: str, now: Any = None,
                 current: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The authoritative waiver records for one gate, projected into that
    gate's own field names and carrying the DERIVED status
    (`waiver_status` / `waiver_status_reason`). `now` is honoured only for a
    gate whose GATE_STATUS_CONTEXT says it checks expiry, and `current` is
    narrowed to the keys that gate really measures -- so a gate can never
    decide a status on a fact it did not observe."""
    spec = GATE_STATUS_CONTEXT.get(gate_id)
    if spec is None:
        raise WaiverStoreError(f"{gate_id!r} is not a waiver gate: {list(WAIVER_GATE_FAMILY)}")
    observed = {k: (current or {}).get(k) for k in spec["current_keys"]}
    effective_now = now if spec["checks_expiry"] else None
    out = []
    for record in waivers_for_gate(root, gate_id):
        status, reason = derive_status(record, now=effective_now, current=observed)
        projected = _projection(record, gate_id, status)
        projected["waiver_status"] = status
        projected["waiver_status_reason"] = reason
        out.append(projected)
    return out


def unbacked_declared_ids(root: Path, gate_id: str,
                          declared: Optional[Iterable[Any]]) -> List[str]:
    """The waiver ids an agent's evidence block CITES that this store has no
    record of. A cited-but-unrecorded waiver is not a waiver: nobody approved
    it, so it exempts nothing and the gate must refuse it."""
    known = {waiver_id_of(r) for r in waivers_for_gate(root, gate_id)}
    out = []
    for entry in (declared or []):
        if not isinstance(entry, dict):
            continue
        wid = str(entry.get("waiver_id") or "").strip()
        if wid and wid not in known:
            out.append(wid)
    return out


def status_report(root: Path, now: Any = None,
                  current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every recorded waiver with its derived status. Reading is not a
    mutating act: nothing here writes, and a project with no ledger is
    reported as having none rather than having one created for it."""
    if not store_exists(root):
        return {"status": "NOT_AVAILABLE", "reason": "NO_WAIVER_STORE",
                "path": str(_store_path(root)), "waivers": []}
    reference = now if now is not None else _dt.datetime.now(_dt.timezone.utc).isoformat()
    rows = []
    for record in read_waivers(root):
        derived, reason = derive_status(record, now=reference, current=current)
        rows.append({
            "waiver_id": waiver_id_of(record),
            "item": record.get("item") or record.get("item_id"),
            "status": derived,
            "status_reason": reason,
            "approver": record.get("approver"),
            "expires_at": record.get("expires_at"),
            "risk": record.get("risk"),
        })
    blocking = [r for r in rows if r["status"] != "VALID"]
    return {
        "status": "CLEAR" if not blocking else "WAIVERS_NOT_VALID",
        "evaluated_at": reference,
        "waivers": rows,
        "not_valid": len(blocking),
    }


# --- front door -----------------------------------------------------------

def execute_verb(argv: Sequence[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="waiver-store", description=__doc__.split("\n")[0])
    ap.add_argument("verb", choices=["statuses", "list", "status"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv))
    root = Path(args.root).resolve()
    if args.verb == "statuses":
        payload = {"statuses": list(WAIVER_STATUSES),
                   "fail_reasons": dict(STATUS_FAIL_REASONS),
                   "gates": list(WAIVER_GATE_FAMILY),
                   "supported_trigger_keys": list(SUPPORTED_TRIGGER_KEYS)}
        print(json.dumps(payload, indent=2))
        return 0
    if args.verb == "list":
        print(json.dumps(read_waivers(root), indent=2))
        return 0
    report = status_report(root)
    print(json.dumps(report, indent=2))
    if report["status"] == "NOT_AVAILABLE":
        return 2
    return 1 if report["not_valid"] else 0


if __name__ == "__main__":
    sys.exit(execute_verb(sys.argv[1:]))
