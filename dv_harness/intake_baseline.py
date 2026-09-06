"""dv_harness/intake_baseline.py -- INTAKE-domain freeze/baseline, mirroring
signoff_export.py's SIGNOFF FREEZE / BASELINE (spec section 238) pattern over
a different fact set: the facts a project commits to at INTAKE time, before
generation begins, rather than signoff's fifteen post-verification fields.

WHAT IT MIRRORS, AND WHY IT DOES NOT IMPORT IT
------------------------------------------------
`signoff_export.py` established the real shape this module reuses: capture
every declared field from a real value or report NOT_AVAILABLE with a real
reason (never silently default or guess -- the Evidence Truth Rule), fold a
multi-file fact into ONE digest through the shared aggregation primitive
(never a second hashing scheme), record one immutable freeze, and re-derive
-- never store -- a VALID / INVALIDATED / UNKNOWN verdict on every later
read, worst-wins across independent checks, where "we could not check" a
field is NEVER read as VALID.

This module's own task scope is deliberately narrower than signoff_export's:
every one of the twelve intake facts below is accepted as a generic,
duck-typed parameter -- a DUT SHA, a bind-topology hash, a VIP declaration --
rather than discovered by importing env_manifest.py / connectivity_check.py /
question_queue.py / source_authority.py / signoff_export.py itself to go and
read them off a real project. That is a deliberate boundary, not an
omission: it keeps this module usable by any caller who already has these
facts in hand (an intake agent, a CLI script, a future generator), without
coupling it to which OTHER module happened to produce them, and without
risking a collision with the several other gap-closure modules editing this
package concurrently. The one import this module DOES make is
`source_identity.aggregate_source_id()` -- the same primitive
`harness_deploy.py` and `signoff_export.py`'s own `_aggregate()` already
reuse for exactly this "fold {name: hash} into one deterministic token"
job -- via the identical `tools/remote/` sys.path convention those modules
already establish, so there is still only ONE hash-aggregation rule in this
codebase.

THE TWELVE INTAKE FIELDS
------------------------
DUT top/boundary, DUT SHA, TB SHA, source file hashes, VIP declaration, bind
topology hash, reference-UVM hash, DE command.txt hash, known-test list,
count of unresolved critical unknowns, count of unresolved conflicts, and
count of recorded user decisions -- `INTAKE_FIELDS`, held equal against
`FIELD_CAPTORS` in both directions by `assert_intake_fields_have_captors()`
at import, so a field can never be silently uncapturable and a captor can
never be silently orphaned.

Four field SHAPES, four captors, chosen from what each fact actually is
rather than forced into one shape:
- **declared fact** (`dut_top_boundary`, `vip_declaration`) -- an arbitrary
  caller-declared string/dict/list, hashed via canonical (sorted-key) JSON.
  There is no notion of "file" here; the fact IS the declaration.
- **hash-or-files** (`dut_sha`, `tb_sha`, `source_file_hashes`,
  `bind_topology_hash`, `reference_uvm_hash`, `de_command_txt_hash`) --
  either a single already-computed hex digest (accepted as-is), a single raw
  content string (hashed), or a `{path: hash-or-content}` mapping, which is
  the multi-file case this module folds through
  `source_identity.aggregate_source_id()` rather than a second hashing rule.
- **list** (`known_test_list`) -- a list/tuple/set of test names, folded
  through the SAME aggregation primitive (each name a "path", each value a
  constant marker), so there remains exactly one aggregation rule in this
  module even though a test list is not a set of files.
- **count** (the three unresolved-unknowns/conflicts/decisions counters) --
  a non-negative int; anything else (`None`, a bool, a negative number, a
  string) is honestly NOT_AVAILABLE rather than coerced.

"WE COULD NOT CHECK" IS NEVER VALID
------------------------------------
`capture_intake_baseline()` never guesses a missing fact; a field with
nothing real behind it is NOT_AVAILABLE, and NOT_AVAILABLE never counts
toward VALID. `evaluate_intake_freeze_invalidation()` re-derives the
verdict on every call, across two independent, worst-wins checks -- (1) each
field re-captured NOW against what was frozen, by digest, exactly as
`signoff_export.evaluate_freeze_invalidation()`'s own field-divergence check
does; (2) the frozen RECORD's own self-integrity (its stored `freeze_id` is
independently recomputed from its own stored baseline and compared) -- and a
check that could not run (a field absent from an old/malformed frozen
record, a malformed baseline with nothing to recompute against) reports
INDETERMINATE, which floors the verdict at UNKNOWN, never VALID.

WHAT THIS MODULE DOES NOT DO
------------------------------
It never runs a build, a regression, or an LSF submission. It never touches
`.dv-harness/state.json`, `events.jsonl`, `ControlPlane`, `can_signoff()`, or
any other human-approval/governance mechanism -- it only reads the facts a
caller hands it and reports/records what they say. `freeze_intake_baseline()`
writes exactly one new, immutable JSON record per freeze under the project's
own `.dv-harness/intake/baselines/` directory (mirroring
`signoff_export.py`'s own `.dv-harness/signoff/freezes/` convention) and
nothing else. There is deliberately no stage gate here: a gate that passed
because an intake baseline existed, or failed because one did not, would be
worse than none.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# tools/remote/ is not an installed package -- the identical sys.path
# convention dv_harness/harness_deploy.py, dv_harness/signoff_export.py's
# `_aggregate()`, and dv_harness_tests/test_source_identity.py already use,
# not a second import mechanism.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "tools" / "remote") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools" / "remote"))

from source_identity import aggregate_source_id  # noqa: E402

SCHEMA_VERSION = "1.0"

#: Per-field capture outcome, the same two-value vocabulary
#: `signoff_export.py`'s baseline fields already use. CAPTURED means a real
#: value was supplied and hashed; NOT_AVAILABLE means nothing usable was
#: supplied and says why -- never silently defaulted or guessed.
CAPTURED = "CAPTURED"
NOT_AVAILABLE = "NOT_AVAILABLE"

#: Freeze-evaluation verdict vocabulary, spelled identically to
#: `signoff_export.py`'s own FREEZE_VALID/FREEZE_INVALIDATED/FREEZE_UNKNOWN
#: (mirrored, not imported -- see this module's own docstring). Worst-wins,
#: and UNKNOWN outranks VALID for the same reason `platform_health.py`'s
#: HEALTH_SEVERITY puts UNKNOWN above HEALTHY: an unmeasurable field must
#: never be reported as a still-good one.
INTAKE_FREEZE_VALID = "VALID"
INTAKE_FREEZE_INVALIDATED = "INVALIDATED"
INTAKE_FREEZE_UNKNOWN = "UNKNOWN"
_FREEZE_SEVERITY = {INTAKE_FREEZE_VALID: 0, INTAKE_FREEZE_UNKNOWN: 1,
                    INTAKE_FREEZE_INVALIDATED: 2}

#: A finding either invalidates the freeze or leaves it indeterminate --
#: the same two-severity vocabulary `signoff_export.py`'s own
#: SEV_INVALIDATING/SEV_INDETERMINATE use.
SEV_INVALIDATING = "INVALIDATING"
SEV_INDETERMINATE = "INDETERMINATE"

#: The twelve intake facts this baseline freezes, in the order the task
#: names them.
INTAKE_FIELDS: tuple = (
    "dut_top_boundary",
    "dut_sha",
    "tb_sha",
    "source_file_hashes",
    "vip_declaration",
    "bind_topology_hash",
    "reference_uvm_hash",
    "de_command_txt_hash",
    "known_test_list",
    "unresolved_critical_unknowns_count",
    "unresolved_conflicts_count",
    "recorded_user_decisions_count",
)

#: A frozen record's own directory, under the project's existing
#: `.dv-harness/` state tree -- never a new parallel state root, and never
#: only inside some other artifact that could be moved or deleted out from
#: under it.
FREEZE_DIR_PARTS = (".dv-harness", "intake", "baselines")

#: Detail payloads are capped so a single huge fact (a thousand-file source
#: map, a giant test list) cannot make a baseline record unreadable -- the
#: same context-budget discipline this project applies everywhere evidence
#: is summarized rather than inlined wholesale.
_MAX_INLINE_DETAIL_CHARS = 2000

#: Hex-digest lengths this module recognizes as "already a computed hash"
#: (md5 / sha1 / sha256) rather than raw content to hash.
_HEX_DIGEST_LENGTHS = (32, 40, 64)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: Any) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _looks_like_hex_digest(value: Any) -> bool:
    if not isinstance(value, str) or len(value) not in _HEX_DIGEST_LENGTHS:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _normalize_hash_value(value: Any) -> str:
    """One entry of a {path: hash-or-content} mapping -> a hash. A value
    that already looks like a hex digest is accepted as-is (lower-cased);
    anything else is treated as raw content and hashed -- never left
    un-normalized, since `aggregate_source_id()` folds these deterministically
    only when every entry is really a fixed-shape hash string."""
    if _looks_like_hex_digest(value):
        return value.lower()
    return _sha256_text(value)


def _aggregate(mapping: Dict[str, str]) -> str:
    """Fold a {name: hash} mapping into one token through the real,
    already-tested `source_identity.aggregate_source_id()` -- the same
    primitive `harness_deploy.py` and `signoff_export.py`'s own
    `_aggregate()` already reuse. There is no second aggregation rule
    anywhere this module touches."""
    return aggregate_source_id(mapping)


def _bounded_detail(key: str, value: Any) -> Dict[str, Any]:
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        serialized = str(value)
    if len(serialized) <= _MAX_INLINE_DETAIL_CHARS:
        return {key: value}
    return {f"{key}_truncated": True, f"{key}_length_chars": len(serialized)}


def _field(name: str, status: str, *, reason: str,
           digest: Optional[str] = None,
           detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"field": name, "status": status, "reason": reason,
            "digest": digest, "detail": detail or {}}


# --- the four captors --------------------------------------------------

def _capture_declared_fact(name: str, value: Any) -> Dict[str, Any]:
    """`dut_top_boundary` / `vip_declaration`: an arbitrary caller-declared
    string/dict/list/scalar, hashed via canonical (sorted-key) JSON so two
    callers describing the same fact in a different key order still agree.
    There is no file concept here -- the DECLARATION is the fact."""
    if value is None:
        return _field(name, NOT_AVAILABLE, reason="NO_FACT_SUPPLIED")
    if isinstance(value, str):
        if not value.strip():
            return _field(name, NOT_AVAILABLE, reason="EMPTY_FACT_SUPPLIED")
        canonical = value
    elif isinstance(value, (dict, list, tuple)):
        if not value:
            return _field(name, NOT_AVAILABLE, reason="EMPTY_FACT_SUPPLIED")
        canonical = _canonical_json(value)
    else:
        # A bare scalar (int/float/bool) is still a real declared fact.
        canonical = _canonical_json(value)
    return _field(name, CAPTURED, reason="DECLARED_FACT_HASHED",
                  digest=_sha256_text(canonical),
                  detail=_bounded_detail("value", value))


def _capture_hash_or_files_field(name: str, value: Any) -> Dict[str, Any]:
    """`dut_sha` / `tb_sha` / `source_file_hashes` / `bind_topology_hash` /
    `reference_uvm_hash` / `de_command_txt_hash`: either an already-computed
    hex digest, a single raw content string, or a real {path: hash-or-
    content} multi-file mapping -- the last folded through
    `source_identity.aggregate_source_id()`, never a second hashing scheme."""
    if value is None:
        return _field(name, NOT_AVAILABLE, reason="NO_FACT_SUPPLIED")
    if isinstance(value, dict):
        if not value:
            return _field(name, NOT_AVAILABLE, reason="EMPTY_FILE_MAP_SUPPLIED")
        normalized = {str(k): _normalize_hash_value(v) for k, v in value.items()}
        digest = _aggregate(normalized)
        detail = {"file_count": len(normalized)}
        detail.update(_bounded_detail("files", normalized))
        return _field(name, CAPTURED, reason="MULTI_FILE_CONTENT_AGGREGATED",
                      digest=digest, detail=detail)
    if isinstance(value, str):
        if not value.strip():
            return _field(name, NOT_AVAILABLE, reason="EMPTY_FACT_SUPPLIED")
        if _looks_like_hex_digest(value):
            return _field(name, CAPTURED, reason="ALREADY_COMPUTED_HASH_ACCEPTED",
                          digest=value.lower(),
                          detail={"supplied_as": "precomputed_hash"})
        return _field(name, CAPTURED, reason="SINGLE_VALUE_CONTENT_HASHED",
                      digest=_sha256_text(value),
                      detail={"supplied_as": "raw_content_string"})
    return _field(name, NOT_AVAILABLE, reason="UNSUPPORTED_FACT_SHAPE",
                  detail={"python_type": type(value).__name__})


def _capture_list_field(name: str, value: Any) -> Dict[str, Any]:
    """`known_test_list`: a list/tuple/set of test names, folded through the
    SAME aggregation primitive the multi-file fields use (each name a
    "path", each value a constant marker) -- one aggregation rule, even
    though a test list is not a set of files."""
    if value is None:
        return _field(name, NOT_AVAILABLE, reason="NO_FACT_SUPPLIED")
    if not isinstance(value, (list, tuple, set)):
        return _field(name, NOT_AVAILABLE, reason="UNSUPPORTED_FACT_SHAPE",
                      detail={"python_type": type(value).__name__})
    items = sorted({str(v) for v in value})
    if not items:
        return _field(name, NOT_AVAILABLE, reason="EMPTY_FACT_SUPPLIED")
    digest = _aggregate({item: "1" for item in items})
    detail = {"count": len(items)}
    detail.update(_bounded_detail("tests", items))
    return _field(name, CAPTURED, reason="TEST_LIST_AGGREGATED",
                  digest=digest, detail=detail)


def _capture_count_field(name: str, value: Any) -> Dict[str, Any]:
    """The three unresolved-unknowns/conflicts/decisions counters: a
    non-negative int, or honestly NOT_AVAILABLE -- `bool` is explicitly
    rejected even though it is a Python `int` subclass, since `True`/`False`
    are never a meaningful count."""
    if value is None:
        return _field(name, NOT_AVAILABLE, reason="NO_COUNT_SUPPLIED")
    if isinstance(value, bool) or not isinstance(value, int):
        return _field(name, NOT_AVAILABLE, reason="INVALID_COUNT_VALUE",
                      detail={"python_type": type(value).__name__})
    if value < 0:
        return _field(name, NOT_AVAILABLE, reason="INVALID_COUNT_VALUE",
                      detail={"value": value,
                              "explanation": "a count cannot be negative"})
    return _field(name, CAPTURED, reason="COUNT_SUPPLIED",
                  digest=_sha256_text(str(value)), detail={"value": value})


FIELD_CAPTORS = {
    "dut_top_boundary": _capture_declared_fact,
    "dut_sha": _capture_hash_or_files_field,
    "tb_sha": _capture_hash_or_files_field,
    "source_file_hashes": _capture_hash_or_files_field,
    "vip_declaration": _capture_declared_fact,
    "bind_topology_hash": _capture_hash_or_files_field,
    "reference_uvm_hash": _capture_hash_or_files_field,
    "de_command_txt_hash": _capture_hash_or_files_field,
    "known_test_list": _capture_list_field,
    "unresolved_critical_unknowns_count": _capture_count_field,
    "unresolved_conflicts_count": _capture_count_field,
    "recorded_user_decisions_count": _capture_count_field,
}


def assert_intake_fields_have_captors() -> None:
    """Both directions, mirroring `signoff_export.
    assert_baseline_covers_section_238()`: a declared field with no captor
    would be silently uncapturable, and a captor for an undeclared field
    would widen the baseline without anyone deciding to. Runs at import."""
    declared = set(INTAKE_FIELDS)
    implemented = set(FIELD_CAPTORS)
    missing = sorted(declared - implemented)
    extra = sorted(implemented - declared)
    if missing or extra:
        raise AssertionError(
            f"intake baseline fields drifted from FIELD_CAPTORS: "
            f"no captor for {missing}; captor for undeclared field {extra}")


assert_intake_fields_have_captors()


def capture_intake_baseline(facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """All twelve intake fields, each from a real caller-supplied fact or
    NOT_AVAILABLE with the reason. `facts` is a plain {field_name: value}
    mapping -- this function reads no file and calls no other dv_harness
    module; every fact is exactly what the caller declared."""
    facts = facts or {}
    if not isinstance(facts, dict):
        raise TypeError("facts must be a dict of {field_name: value}, or None")
    fields = {name: FIELD_CAPTORS[name](name, facts.get(name))
              for name in INTAKE_FIELDS}
    captured = sum(1 for f in fields.values() if f["status"] == CAPTURED)
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": _now_iso(),
        "fields": fields,
        "captured_field_count": captured,
        "not_available_field_count": len(INTAKE_FIELDS) - captured,
    }


# --- freeze record: write, load, list -----------------------------------

def freeze_dir(root: Path) -> Path:
    return Path(root).joinpath(*FREEZE_DIR_PARTS)


def _freeze_id(baseline: Optional[Dict[str, Any]], frozen_at: Any) -> str:
    """Deterministic id over the frozen content -- also the value
    `evaluate_intake_freeze_invalidation()` independently recomputes to
    detect a hand-edited record. Defensive against a malformed/partial
    baseline (`.get(...)` throughout) so recomputing over a broken record
    never raises -- it should read as a mismatch, not crash the check."""
    fields = (baseline or {}).get("fields") or {}
    material = [f"frozen_at:{frozen_at}"]
    for name in INTAKE_FIELDS:
        f = fields.get(name) or {}
        material.append(f"{name}:{f.get('status')}:{f.get('digest')}")
    return hashlib.sha256("\n".join(material).encode("utf-8")).hexdigest()[:16]


def freeze_intake_baseline(root: Path, facts: Optional[Dict[str, Any]], *,
                           frozen_by: str, note: str = "") -> Dict[str, Any]:
    """Record one immutable frozen intake baseline for the project at
    `root`. Requires a real `frozen_by`: an unattributable baseline is not a
    freeze, the same rule `signoff_export.freeze_signoff_baseline()`'s CLI
    wrapper enforces for its own `--frozen-by`.

    Writes `.dv-harness/intake/baselines/<freeze_id>.json` and nothing else
    -- no state, control, or approval file is touched, and no other project
    artifact is read or written."""
    if not frozen_by or not str(frozen_by).strip():
        raise ValueError(
            "frozen_by is required: an unattributable intake baseline is "
            "not a freeze")
    root = Path(root).resolve()
    baseline = capture_intake_baseline(facts)
    frozen_at = _now_iso()
    fid = _freeze_id(baseline, frozen_at)
    record = {
        "schema_version": SCHEMA_VERSION,
        "freeze_id": fid,
        "frozen_at": frozen_at,
        "frozen_by": str(frozen_by),
        "note": note,
        "project_root": str(root),
        "baseline": baseline,
    }
    fdir = freeze_dir(root)
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / (fid + ".json")).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def list_intake_freezes(root: Path) -> List[Dict[str, Any]]:
    fdir = freeze_dir(root)
    out: List[Dict[str, Any]] = []
    if not fdir.is_dir():
        return out
    for p in sorted(fdir.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("freeze_id"):
            out.append(doc)
    out.sort(key=lambda r: str(r.get("frozen_at") or ""))
    return out


def load_intake_freeze(root: Path, freeze_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One freeze record. With no `freeze_id`, the most recently frozen one
    -- `frozen_at` order, not filesystem mtime."""
    records = list_intake_freezes(root)
    if not records:
        return None
    if freeze_id is None:
        return records[-1]
    for r in records:
        if r.get("freeze_id") == freeze_id:
            return r
    return None


# --- post-freeze invalidation --------------------------------------------

def _finding(code: str, severity: str, field_name: Optional[str],
             detail: Dict[str, Any]) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "field": field_name,
            "detail": detail}


def evaluate_intake_freeze_invalidation(
        frozen: Dict[str, Any],
        current_facts: Optional[Dict[str, Any]] = None, *,
        current_baseline: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """VALID / INVALIDATED / UNKNOWN for one frozen intake baseline, from
    real evidence only. Two independent comparisons, worst-wins:

    1. **Baseline field divergence.** All twelve fields are re-captured NOW
       from `current_facts` and compared by digest against the frozen
       record, exactly as `signoff_export.evaluate_freeze_invalidation()`'s
       own field check does: a field CAPTURED at freeze that no longer
       matches, or that can no longer be captured at all, INVALIDATES. A
       field that was NOT_AVAILABLE at freeze and is CAPTURED now is
       INDETERMINATE, not invalidating -- new evidence appearing after a
       freeze is a real change but not proof the frozen evidence was wrong.
    2. **Frozen-record self-integrity.** The stored `freeze_id` is
       independently recomputed from the record's own stored baseline and
       compared -- a mismatch means the record was hand-edited since it was
       written, which INVALIDATES. A record whose stored baseline is
       missing/malformed cannot be recomputed against at all, which is
       INDETERMINATE rather than a fabricated TAMPERED claim.

    `current_baseline` is injectable so one recomputation can serve many
    freezes (`evaluate_all_intake_freezes()`). Nothing here writes,
    revalidates, or re-runs anything -- REVALIDATION is a human act."""
    frozen = frozen or {}
    frozen_baseline = frozen.get("baseline") or {}
    frozen_fields = frozen_baseline.get("fields") if isinstance(frozen_baseline, dict) else None
    frozen_fields = frozen_fields if isinstance(frozen_fields, dict) else {}
    current = (current_baseline if current_baseline is not None
               else capture_intake_baseline(current_facts))
    findings: List[Dict[str, Any]] = []

    for name in INTAKE_FIELDS:
        was = frozen_fields.get(name)
        now = current["fields"][name]
        if not isinstance(was, dict):
            findings.append(_finding(
                "FIELD_NOT_IN_FROZEN_BASELINE", SEV_INDETERMINATE, name,
                {"explanation": "the frozen record carries no usable entry "
                                "for this field, so nothing about it can be "
                                "compared",
                 "current_status": now["status"]}))
            continue
        if was.get("status") == CAPTURED and now["status"] == CAPTURED:
            if was.get("digest") != now.get("digest"):
                findings.append(_finding(
                    "BASELINE_FIELD_CHANGED", SEV_INVALIDATING, name,
                    {"frozen_digest": was.get("digest"),
                     "current_digest": now.get("digest"),
                     "current_reason": now.get("reason")}))
        elif was.get("status") == CAPTURED and now["status"] == NOT_AVAILABLE:
            findings.append(_finding(
                "BASELINE_EVIDENCE_DISAPPEARED", SEV_INVALIDATING, name,
                {"frozen_digest": was.get("digest"),
                 "current_reason": now.get("reason")}))
        elif was.get("status") == NOT_AVAILABLE and now["status"] == CAPTURED:
            findings.append(_finding(
                "NEW_EVIDENCE_AFTER_FREEZE", SEV_INDETERMINATE, name,
                {"frozen_reason": was.get("reason"),
                 "current_digest": now.get("digest")}))

    frozen_fields_present = bool(frozen_fields)
    if not frozen_fields_present:
        integrity_status = "FROZEN_BASELINE_MALFORMED_OR_EMPTY"
        findings.append(_finding(
            "FROZEN_BASELINE_MALFORMED", SEV_INDETERMINATE, None,
            {"explanation": "the frozen record's own baseline carries no "
                            "usable field entries, so its self-integrity "
                            "cannot be checked"}))
    else:
        recomputed_fid = _freeze_id(frozen_baseline, frozen.get("frozen_at"))
        recorded_fid = frozen.get("freeze_id")
        if not recorded_fid:
            integrity_status = "NO_RECORDED_FREEZE_ID"
            findings.append(_finding(
                "FROZEN_RECORD_HAS_NO_FREEZE_ID", SEV_INDETERMINATE, None, {}))
        elif recomputed_fid != recorded_fid:
            integrity_status = "FROZEN_RECORD_TAMPERED"
            findings.append(_finding(
                "FROZEN_RECORD_TAMPERED", SEV_INVALIDATING, None,
                {"recorded_freeze_id": recorded_fid,
                 "recomputed_freeze_id": recomputed_fid}))
        else:
            integrity_status = "RECORD_UNCHANGED"

    if any(f["severity"] == SEV_INVALIDATING for f in findings):
        status = INTAKE_FREEZE_INVALIDATED
    elif findings:
        status = INTAKE_FREEZE_UNKNOWN
    else:
        status = INTAKE_FREEZE_VALID

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "freeze_id": frozen.get("freeze_id"),
        "frozen_at": frozen.get("frozen_at"),
        "frozen_by": frozen.get("frozen_by"),
        "evaluated_at": _now_iso(),
        "findings": findings,
        "invalidating_count": sum(1 for f in findings if f["severity"] == SEV_INVALIDATING),
        "indeterminate_count": sum(1 for f in findings if f["severity"] == SEV_INDETERMINATE),
        "record_integrity": integrity_status,
        "current_baseline": current,
    }


def evaluate_all_intake_freezes(root: Path,
                                current_facts: Optional[Dict[str, Any]] = None
                                ) -> Dict[str, Any]:
    """Every recorded intake freeze for the project at `root`, evaluated
    against ONE re-derived current baseline. The report's own status is the
    WORST present -- one invalidated freeze makes the report INVALIDATED."""
    root = Path(root).resolve()
    frozen = list_intake_freezes(root)
    if not frozen:
        return {"schema_version": SCHEMA_VERSION, "status": "NOT_AVAILABLE",
                "reason": "NO_FROZEN_INTAKE_BASELINE",
                "freeze_dir": str(freeze_dir(root)), "freezes": []}
    current = capture_intake_baseline(current_facts)
    results = [evaluate_intake_freeze_invalidation(f, current_facts,
                                                   current_baseline=current)
               for f in frozen]
    worst = max(results, key=lambda r: _FREEZE_SEVERITY[r["status"]])["status"]
    return {
        "schema_version": SCHEMA_VERSION, "status": worst,
        "freeze_count": len(results),
        "counts": {s: sum(1 for r in results if r["status"] == s)
                   for s in (INTAKE_FREEZE_VALID, INTAKE_FREEZE_UNKNOWN,
                             INTAKE_FREEZE_INVALIDATED)},
        "freezes": results, "evaluated_at": _now_iso(),
    }


# --- front door -----------------------------------------------------------

def _load_facts_file(path: str):
    p = Path(path)
    if not p.is_file():
        return None, f"FACTS_FILE_NOT_FOUND: {p}"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"FACTS_FILE_UNREADABLE: {type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return None, "FACTS_FILE_MUST_BE_A_JSON_OBJECT"
    return doc, None


def execute_verb(argv: Sequence[str]) -> int:
    """Shared implementation for `python -m dv_harness.intake_baseline
    <verb>`. Exit 0 clear, 1 a real finding (a freeze is INVALIDATED),
    2 nothing to report / usage refusal. A reporting signal, never an
    approval signal in either direction: no verb here approves, revalidates
    or runs anything."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="intake-baseline",
        description="Intake freeze / baseline over the twelve intake facts "
                    "(DUT top/boundary, DUT/TB SHA, source file hashes, VIP "
                    "declaration, bind topology hash, reference-UVM hash, "
                    "DE command.txt hash, known-test list, and the "
                    "unresolved-unknowns/conflicts/decisions counts).")
    ap.add_argument("verb", choices=["fields", "baseline", "freeze", "list", "status"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--facts", default=None,
                    help="path to a JSON object of intake facts, keyed by "
                         "the field names the `fields` verb prints")
    ap.add_argument("--freeze-id", default=None)
    ap.add_argument("--frozen-by", default=None)
    ap.add_argument("--note", default="")
    args = ap.parse_args(list(argv))
    root = Path(args.root).resolve()

    if args.verb == "fields":
        print(json.dumps({
            "intake_fields": list(INTAKE_FIELDS),
            "field_statuses": [CAPTURED, NOT_AVAILABLE],
            "freeze_statuses": [INTAKE_FREEZE_VALID, INTAKE_FREEZE_UNKNOWN,
                                INTAKE_FREEZE_INVALIDATED],
        }, indent=2))
        return 0

    if args.verb == "baseline":
        if not args.facts:
            print(json.dumps({"status": "REFUSED", "reason": "FACTS_REQUIRED"},
                             indent=2))
            return 2
        facts, err = _load_facts_file(args.facts)
        if err:
            print(json.dumps({"status": "REFUSED", "reason": err}, indent=2))
            return 2
        b = capture_intake_baseline(facts)
        print(json.dumps(b, ensure_ascii=False, indent=2))
        return 0 if b["captured_field_count"] else 2

    if args.verb == "freeze":
        if not args.frozen_by:
            print(json.dumps({
                "status": "REFUSED", "reason": "FROZEN_BY_REQUIRED",
                "detail": "a freeze records who froze it; an unattributable "
                         "baseline is not an intake baseline"}, indent=2))
            return 2
        if not args.facts:
            print(json.dumps({"status": "REFUSED", "reason": "FACTS_REQUIRED"},
                             indent=2))
            return 2
        facts, err = _load_facts_file(args.facts)
        if err:
            print(json.dumps({"status": "REFUSED", "reason": err}, indent=2))
            return 2
        rec = freeze_intake_baseline(root, facts, frozen_by=args.frozen_by,
                                     note=args.note)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0

    if args.verb == "list":
        rows = list_intake_freezes(root)
        print(json.dumps([{k: r.get(k) for k in
                           ("freeze_id", "frozen_at", "frozen_by")}
                          for r in rows], indent=2))
        return 0 if rows else 2

    # status
    if not args.facts:
        print(json.dumps({
            "status": "REFUSED", "reason": "CURRENT_FACTS_REQUIRED",
            "detail": "comparing a frozen baseline against nothing would "
                     "misreport every captured field as evidence that "
                     "disappeared"}, indent=2))
        return 2
    facts, err = _load_facts_file(args.facts)
    if err:
        print(json.dumps({"status": "REFUSED", "reason": err}, indent=2))
        return 2
    if args.freeze_id:
        rec = load_intake_freeze(root, args.freeze_id)
        if rec is None:
            print(json.dumps({"status": "NOT_AVAILABLE",
                              "reason": "FREEZE_ID_NOT_FOUND",
                              "freeze_id": args.freeze_id}, indent=2))
            return 2
        report = evaluate_intake_freeze_invalidation(rec, facts)
    else:
        report = evaluate_all_intake_freezes(root, facts)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == INTAKE_FREEZE_INVALIDATED:
        return 1
    if report["status"] in ("NOT_AVAILABLE", INTAKE_FREEZE_UNKNOWN):
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys as _sys
    return execute_verb(list(_sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
