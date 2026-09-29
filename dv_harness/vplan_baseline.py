"""dv_harness/vplan_baseline.py -- a vPlan-scoped signoff freeze/baseline,
mirroring `signoff_export.py`'s content-hash-based freeze/invalidation
PATTERN (2026-09-06, vplan-baseline gap close).

GAP THIS CLOSES. `signoff_export.py`'s section-238 baseline names fifteen
project-wide identity fields (spec version, DUT/TB SHA, waivers, coverage
databases, ...) but none of them is specifically about the vPlan/requirement/
configuration triad a vPlan-focused freeze needs: which spec version a vPlan
was written against, which version of the section-184 Canonical Requirement
Contract IR fed it, which configuration-variant IR it was planned over, and
exactly which vPlan items (by count and content) existed at freeze time.
`grep -rn "vplan.*freeze\\|freeze.*vplan" --include=*.py .` matched nothing --
`signoff_export.py`'s own freeze covers the whole project's signoff evidence,
not a vPlan document's own identity, and nothing else in this repo freezes a
vPlan at all.

WHAT IS REUSED, NOT REINVENTED.
  - **Hash aggregation.** Every multi-item digest here goes through the real,
    already-tested `tools/remote/source_identity.aggregate_source_id()`
    (imported through `dv_harness/harness_deploy.py`, exactly the way
    `signoff_export._aggregate()` already does it) -- sorted "key:value"
    lines, newline-joined, sha256. There is no second hashing scheme in this
    module.
  - **Freeze vocabulary.** `CAPTURED` / `NOT_AVAILABLE` (per-field capture
    outcome) and `FREEZE_VALID` / `FREEZE_UNKNOWN` / `FREEZE_INVALIDATED`
    (freeze verdict, worst-wins: `SEV_INVALIDATING` > `SEV_INDETERMINATE`,
    and UNKNOWN always outranks VALID -- "we could not check" is never a
    pass) are IMPORTED from `signoff_export.py`, not re-typed, so a freeze
    verdict means the same three words whether it names a vPlan baseline or
    a whole-project signoff baseline. `signoff_export.py` itself is
    untouched -- this module only reads its public constants.
  - **Post-freeze impact analysis.** The same real
    `change_impact.changed_files()` + `classify_risk()` +
    `MATERIAL_CHANGE_RISKS` (also imported from `signoff_export.py`) that
    `signoff_export.evaluate_freeze_invalidation()` and
    `golden_scenario.evaluate_freshness()` already use, so "did the project
    move since this was frozen" has ONE answer across every freeze mechanism
    in this codebase, never a second git-diff implementation.
  - **Requirement-IR shape detection.** `requirement_contract.
    declares_contract_shape()` (the real discriminator the extended
    `spec_to_vplan_requirement_quality_gate.py` already uses) decides whether
    a requirement record is genuinely in the section-184 canonical contract
    shape, rather than this module re-deriving its own notion of "looks like
    a requirement IR record".

WHAT IS DELIBERATELY *NOT* IMPORTED, AND WHY (file-safety scope). At the time
this module was written, `dv_harness/config_variant_coverage.py` was under
concurrent edit by a separate, already-running batch of agents. Per this
task's file-safety rules this module therefore never imports it, even though
`config_variant_coverage.ConfigSpace`/`load_config_space()` is the closest
real "configuration IR" producer in this repo. `configuration_ir_version`
instead accepts a GENERIC, duck-typed JSON document at `configuration_ir_path`
-- any project's configuration-variant IR, whatever produced it -- and hashes
its real content. Once `config_variant_coverage.py`'s shape has settled, a
caller may validate the same file through its `load_config_space()` before
naming it here; this field would then simply be hashing an
already-validated document, with no code change required in this module.

THE FOUR FIELDS, deliberately narrower than section 238's fifteen (that is
`signoff_export.py`'s job; this module is vPlan-scoped):
  - `spec_version` -- the vPlan document's own `spec_revision` field
    (`.dv-harness/vplan/vplan.schema.json`'s own top-level key) when present;
    otherwise a human-declared value, recorded as attested rather than
    derived (mirrors `signoff_export._capture_spec_version()` exactly).
  - `requirement_ir_version` -- content identity over every record in a
    supplied requirement-contract-records file that genuinely
    `declares_contract_shape()`. Reports which are absent, not just a bare
    NOT_AVAILABLE, so "no file supplied", "file has records but none in
    contract shape" and "file is empty" stay three distinct, actionable
    facts.
  - `configuration_ir_version` -- content identity of a supplied
    configuration-IR JSON document (see boundary note above).
  - `vplan_items` -- item COUNT plus a content-hash aggregate over every
    vPlan item, keyed by its own `req_id`/`item_id` (falling back to a
    positional key), from either the `.dv-harness/vplan/vplan.schema.json`
    shape (`{"requirements": [...]}`) or a plain `vplan_writer`-style item
    list -- both real shapes this repo already uses for a vPlan.

UNLIKE signoff_export's FIELDS, THESE HAVE NO FIXED CONVENTIONAL PATH UNDER
`root`. A project's vPlan/requirement-IR/configuration-IR files can live
anywhere a caller names them (there is no single canonical instance-file
location for any of the three in this repo today -- only schema files and ad
hoc CLI `--<x>` flags on their respective modules). So the frozen record
carries the EXACT paths supplied at capture time
(`vplan_path`/`requirements_path`/`configuration_ir_path`), and
re-derivation at evaluation time re-reads those SAME paths rather than
re-discovering them -- a file that moved or vanished since the freeze is
exactly a `BASELINE_EVIDENCE_DISAPPEARED` finding, never a silent
re-pointing at a different file.

FREEZE / INVALIDATION, the same three-part worst-wins design
`signoff_export.evaluate_freeze_invalidation()` uses: (1) every field is
re-derived NOW and compared by digest -- a CAPTURED field that moved, or that
can no longer be captured, INVALIDATES; a field that gained evidence after
freeze (NOT_AVAILABLE -> CAPTURED) is INDETERMINATE, never invalidating on
its own. (2) The real post-freeze git diff over the freeze's own recorded
`repo_head_sha`. A frozen record with no invalidated field is never reported
better than what the evidence supports: "we could not check" (no git, an
unreadable diff, a field absent from an older freeze schema) is always
`FREEZE_UNKNOWN`, never `FREEZE_VALID`.

DELIBERATELY BOUNDED, and stated rather than implied closed. (1) This module
DECIDES nothing: no stage runs, no gate is invoked, no build/regression/LSF
submission starts, and there is deliberately no stage gate -- a gate that
passed because a vPlan freeze had not been recorded, or failed because one
had, would be worse than none. (2) It ARBITRATES nothing: an INVALIDATED
report names exactly what diverged; REVALIDATION (deciding the divergence is
acceptable, or re-freezing) is a human act this module does not perform.
(3) `configuration_ir_version` validates NOTHING about its document's
internal legality (no dimension/constraint/critical-combination checking --
that is `config_variant_coverage.py`'s job, deliberately not imported here);
it is a content-identity field only. (4) No `dv-harness` CLI verb exists yet
-- the front door is `python -m dv_harness.vplan_baseline
fields|baseline|freeze|list|status`, the same `execute_verb()` convention
`signoff_export`/`power-intent`/`golden-scenario` already follow.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Freeze vocabulary is IMPORTED from signoff_export.py, never re-typed --
# one meaning for "CAPTURED"/"NOT_AVAILABLE"/"VALID"/"UNKNOWN"/"INVALIDATED"
# across every freeze mechanism in this codebase. signoff_export.py is not
# edited by this module.
from .signoff_export import (
    CAPTURED,
    NOT_AVAILABLE,
    FREEZE_VALID,
    FREEZE_INVALIDATED,
    FREEZE_UNKNOWN,
    SEV_INVALIDATING,
    SEV_INDETERMINATE,
    MATERIAL_CHANGE_RISKS,
)

SCHEMA_VERSION = "1.0"

#: The four vPlan-specific baseline fields this module freezes. Held equal,
#: in both directions, against `VPLAN_BASELINE_CAPTURES` below by
#: `assert_baseline_covers_declared_fields()` at import -- a field declared
#: here with no capture function would be silently absent from every freeze
#: record, and a capture function for an undeclared field would widen the
#: baseline without anyone deciding to.
VPLAN_BASELINE_FIELDS = (
    "spec_version",
    "requirement_ir_version",
    "configuration_ir_version",
    "vplan_items",
)

#: Worst-wins severity for `evaluate_all_vplan_freezes()`'s report-level
#: verdict -- the same ordering `signoff_export._FREEZE_SEVERITY` uses.
_FREEZE_SEVERITY = {FREEZE_VALID: 0, FREEZE_UNKNOWN: 1, FREEZE_INVALIDATED: 2}

#: Where a project's vPlan freeze records live -- under the project's own
#: `.dv-harness/`, never a new parallel state root, and deliberately NOT
#: inside `.dv-harness/vplan/` itself (which `signoff_export.
#: collect_signoff_bundle()` already copies wholesale into a signoff bundle;
#: nesting freeze records there would silently bundle them as if they were
#: vPlan content).
FREEZE_DIR_PARTS = (".dv-harness", "vplan_baseline", "freezes")

#: The one events.jsonl event name this module writes, so "was a vPlan
#: baseline frozen, when, by whom, over what" is answerable from the real
#: audit trail `dv-harness audit` already surfaces.
FREEZE_EVENT = "VPLAN_BASELINE_FROZEN"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    """Stable serialization for hashing one record -- sorted keys, no
    whitespace sensitivity, so the same logical item always hashes the same
    regardless of how it was re-serialized upstream."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _aggregate(manifest: Dict[str, str]) -> str:
    """The real, already-tested `tools/remote/source_identity.
    aggregate_source_id()`, reached the same way `signoff_export._aggregate()`
    reaches it (through `dv_harness.harness_deploy`'s re-export) -- lazy
    import, mirroring every capture function in `signoff_export.py`, which
    all import their dependency inside the function rather than at module
    top. There is no second aggregation rule in this module."""
    from .harness_deploy import aggregate_source_id
    return aggregate_source_id(manifest)


def _baseline_field(name: str, status: str, *, reason: str,
                    source: Optional[str] = None,
                    digest: Optional[str] = None,
                    detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "field": name,
        "status": status,
        "reason": reason,
        "source": source,
        "digest": digest,
        "detail": detail or {},
    }


def _load_json_or_none(path: Optional[Any]) -> Optional[Any]:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- the four capture functions ---------------------------------------------
# Each reads a REAL file/field or reports NOT_AVAILABLE naming the missing
# one -- nothing here invents a version, a count or a digest.


def _capture_spec_version(vplan_doc: Any, vplan_path: Optional[Any],
                          declared: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(vplan_doc, dict):
        value = vplan_doc.get("spec_revision")
        if isinstance(value, str) and value.strip():
            return _baseline_field(
                "spec_version", CAPTURED, reason="REAL_VPLAN_SPEC_REVISION_FIELD",
                source=f"{vplan_path} :: spec_revision", digest=_sha256_text(value),
                detail={"value": value})
    declared_value = (declared or {}).get("spec_version")
    if declared_value:
        return _baseline_field(
            "spec_version", CAPTURED, reason="DECLARED_BY_FREEZING_HUMAN",
            source="caller-declared", digest=_sha256_text(declared_value),
            detail={"value": str(declared_value), "attested": True,
                    "machine_verified": False})
    return _baseline_field(
        "spec_version", NOT_AVAILABLE, reason="NO_SPEC_VERSION_IN_VPLAN_OR_DECLARED",
        detail={"explanation":
                "the supplied vPlan document (if any) carries no non-empty "
                "`spec_revision` field (`.dv-harness/vplan/vplan.schema.json`'s "
                "own top-level field), and no declared spec_version was supplied. "
                "A human may declare one explicitly, recorded as attested rather "
                "than derived -- the same rule signoff_export.capture_baseline()'s "
                "own spec_version field already follows."})


def _capture_requirement_ir_version(requirements_path: Optional[Any],
                                    declared: Dict[str, Any]) -> Dict[str, Any]:
    if not requirements_path:
        return _baseline_field(
            "requirement_ir_version", NOT_AVAILABLE,
            reason="NO_REQUIREMENT_CONTRACT_FILE_SUPPLIED",
            detail={"expected": "a requirement-contract records file (section 184 "
                                "Canonical Requirement Contract, see "
                                "dv_harness/requirement_contract.py)"})
    p = Path(requirements_path)
    if not p.is_file():
        return _baseline_field(
            "requirement_ir_version", NOT_AVAILABLE,
            reason="REQUIREMENT_CONTRACT_FILE_NOT_FOUND", detail={"path": str(p)})
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _baseline_field(
            "requirement_ir_version", NOT_AVAILABLE,
            reason="REQUIREMENT_CONTRACT_FILE_MALFORMED", source=str(p),
            detail={"error": f"{type(exc).__name__}: {exc}"})

    if isinstance(doc, dict) and isinstance(doc.get("requirements"), list):
        records = doc["requirements"]
        top_schema_version = doc.get("schema_version")
    elif isinstance(doc, list):
        records = doc
        top_schema_version = None
    else:
        return _baseline_field(
            "requirement_ir_version", NOT_AVAILABLE,
            reason="REQUIREMENT_CONTRACT_FILE_UNRECOGNIZED_SHAPE", source=str(p))

    if not records:
        return _baseline_field(
            "requirement_ir_version", NOT_AVAILABLE,
            reason="REQUIREMENT_CONTRACT_FILE_EMPTY", source=str(p))

    # Lazy import, mirroring signoff_export's own per-capture-function lazy
    # imports (e.g. `_capture_waivers`'s `from . import waiver_store`).
    from .requirement_contract import declares_contract_shape

    contract_shaped = [r for r in records if declares_contract_shape(r)]
    if not contract_shaped:
        return _baseline_field(
            "requirement_ir_version", NOT_AVAILABLE,
            reason="NO_CONTRACT_SHAPED_RECORDS", source=str(p),
            detail={"record_count": len(records),
                    "explanation": "records exist but none declares "
                                   "contract_schema_version "
                                   "(requirement_contract.declares_contract_shape)"})

    versions = sorted({str(r.get("contract_schema_version")) for r in contract_shaped})
    manifest: Dict[str, str] = {}
    for idx, r in enumerate(contract_shaped):
        key = str(r.get("requirement_id") or r.get("req_id") or f"__index_{idx}")
        if key in manifest:
            key = f"{key}__{idx}"
        manifest[key] = _sha256_text(_canonical_json(r))
    return _baseline_field(
        "requirement_ir_version", CAPTURED, reason="REAL_REQUIREMENT_CONTRACT_RECORDS",
        source=f"{p} -> requirement_contract.declares_contract_shape()",
        digest=_aggregate(manifest),
        detail={"contract_record_count": len(contract_shaped),
                "total_record_count": len(records),
                "contract_schema_versions": versions,
                "top_level_schema_version": top_schema_version,
                "mixed_contract_schema_versions": len(versions) > 1})


def _capture_configuration_ir_version(configuration_ir_path: Optional[Any],
                                      declared: Dict[str, Any]) -> Dict[str, Any]:
    """See this module's docstring's "WHAT IS DELIBERATELY *NOT* IMPORTED"
    section: `config_variant_coverage.py` was under concurrent edit by a
    separate batch when this was written, so this field is deliberately
    generic/duck-typed -- it hashes whatever JSON document a caller names as
    the project's configuration IR, and validates nothing about its internal
    legality (no dimension/constraint/critical-combination checking)."""
    if not configuration_ir_path:
        return _baseline_field(
            "configuration_ir_version", NOT_AVAILABLE,
            reason="NO_CONFIGURATION_IR_FILE_SUPPLIED",
            detail={"explanation":
                    "no configuration IR document (e.g. a config_variant_coverage-"
                    "shaped configuration-space file) was named"})
    p = Path(configuration_ir_path)
    if not p.is_file():
        return _baseline_field(
            "configuration_ir_version", NOT_AVAILABLE,
            reason="CONFIGURATION_IR_FILE_NOT_FOUND", detail={"path": str(p)})
    try:
        raw = p.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, ValueError) as exc:
        return _baseline_field(
            "configuration_ir_version", NOT_AVAILABLE,
            reason="CONFIGURATION_IR_FILE_MALFORMED", source=str(p),
            detail={"error": f"{type(exc).__name__}: {exc}"})

    detail: Dict[str, Any] = {}
    if isinstance(doc, dict):
        dims = doc.get("dimensions")
        if isinstance(dims, list):
            detail["dimension_count"] = len(dims)
        if doc.get("space_id"):
            detail["space_id"] = doc.get("space_id")
    return _baseline_field(
        "configuration_ir_version", CAPTURED, reason="REAL_CONFIGURATION_IR_FILE_CONTENT",
        source=str(p), digest=_sha256_text(raw), detail=detail)


def _extract_vplan_items(vplan_doc: Any) -> Optional[List[Any]]:
    if isinstance(vplan_doc, dict):
        if isinstance(vplan_doc.get("requirements"), list):
            return vplan_doc["requirements"]
        if isinstance(vplan_doc.get("items"), list):
            return vplan_doc["items"]
        return None
    if isinstance(vplan_doc, list):
        return vplan_doc
    return None


def _capture_vplan_items(vplan_path: Optional[Any], vplan_doc: Any,
                         declared: Dict[str, Any]) -> Dict[str, Any]:
    if not vplan_path:
        return _baseline_field(
            "vplan_items", NOT_AVAILABLE, reason="NO_VPLAN_FILE_SUPPLIED",
            detail={"expected_shape":
                    ".dv-harness/vplan/vplan.schema.json ({'requirements':[...]}) "
                    "or a plain vplan_writer-shaped item list"})
    p = Path(vplan_path)
    if not p.is_file():
        return _baseline_field(
            "vplan_items", NOT_AVAILABLE, reason="VPLAN_FILE_NOT_FOUND",
            detail={"path": str(p)})
    if vplan_doc is None:
        return _baseline_field(
            "vplan_items", NOT_AVAILABLE, reason="VPLAN_FILE_MALFORMED", source=str(p))
    items = _extract_vplan_items(vplan_doc)
    if items is None:
        return _baseline_field(
            "vplan_items", NOT_AVAILABLE, reason="VPLAN_FILE_UNRECOGNIZED_SHAPE",
            source=str(p))
    if not items:
        return _baseline_field(
            "vplan_items", NOT_AVAILABLE, reason="VPLAN_FILE_HAS_ZERO_ITEMS", source=str(p))

    manifest: Dict[str, str] = {}
    for idx, item in enumerate(items):
        if isinstance(item, dict):
            key = str(item.get("req_id") or item.get("item_id") or f"__index_{idx}")
        else:
            key = f"__index_{idx}"
        if key in manifest:
            key = f"{key}__{idx}"
        manifest[key] = _sha256_text(_canonical_json(item))
    return _baseline_field(
        "vplan_items", CAPTURED, reason="REAL_VPLAN_ITEM_CONTENT", source=str(p),
        digest=_aggregate(manifest), detail={"item_count": len(items)})


@dataclass(frozen=True)
class _CaptureContext:
    vplan_doc: Any
    vplan_path: Optional[str]
    requirements_path: Optional[str]
    configuration_ir_path: Optional[str]
    declared: Dict[str, Any]


#: field -> capture function, held equal to VPLAN_BASELINE_FIELDS in both
#: directions by `assert_baseline_covers_declared_fields()` at import.
VPLAN_BASELINE_CAPTURES = {
    "spec_version": lambda ctx: _capture_spec_version(
        ctx.vplan_doc, ctx.vplan_path, ctx.declared),
    "requirement_ir_version": lambda ctx: _capture_requirement_ir_version(
        ctx.requirements_path, ctx.declared),
    "configuration_ir_version": lambda ctx: _capture_configuration_ir_version(
        ctx.configuration_ir_path, ctx.declared),
    "vplan_items": lambda ctx: _capture_vplan_items(
        ctx.vplan_path, ctx.vplan_doc, ctx.declared),
}


def assert_baseline_covers_declared_fields() -> None:
    """Both directions: a declared field with no capture function would be
    silently absent from every freeze record, and a capture function for an
    undeclared field would widen the baseline without anyone deciding to.
    Runs at import, mirroring signoff_export.assert_baseline_covers_section_238()."""
    declared_fields = set(VPLAN_BASELINE_FIELDS)
    implemented = set(VPLAN_BASELINE_CAPTURES)
    missing = sorted(declared_fields - implemented)
    extra = sorted(implemented - declared_fields)
    if missing or extra:
        raise AssertionError(
            f"vplan baseline drifted from its own declared fields: "
            f"no capture for {missing}; capture for undeclared field {extra}")


assert_baseline_covers_declared_fields()


def capture_vplan_baseline(root: Any, *, vplan_path: Optional[Any] = None,
                           requirements_path: Optional[Any] = None,
                           configuration_ir_path: Optional[Any] = None,
                           declared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """All four vPlan-specific baseline fields, each from a REAL producer or
    NOT_AVAILABLE with the reason. Reading is not a mutating act: nothing is
    written to answer any field, and nothing here runs a build, a
    regression, or an LSF submission."""
    root = Path(root).resolve()
    vplan_doc = _load_json_or_none(vplan_path)
    ctx = _CaptureContext(
        vplan_doc=vplan_doc,
        vplan_path=str(vplan_path) if vplan_path else None,
        requirements_path=str(requirements_path) if requirements_path else None,
        configuration_ir_path=str(configuration_ir_path) if configuration_ir_path else None,
        declared=declared or {},
    )
    fields = {name: VPLAN_BASELINE_CAPTURES[name](ctx) for name in VPLAN_BASELINE_FIELDS}

    # Lazy import, same reason as _aggregate()'s.
    from . import change_impact
    head_sha = change_impact.resolve_sha(root, "HEAD")

    captured = sum(1 for f in fields.values() if f["status"] == CAPTURED)
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": _now_iso(),
        "project_root": str(root),
        "vplan_path": ctx.vplan_path,
        "requirements_path": ctx.requirements_path,
        "configuration_ir_path": ctx.configuration_ir_path,
        "repo_head_sha": head_sha,
        "fields": fields,
        "captured_field_count": captured,
        "not_available_field_count": len(VPLAN_BASELINE_FIELDS) - captured,
    }


# --- freeze record: write, load, list ---------------------------------------


def freeze_dir(root: Any) -> Path:
    return Path(root).joinpath(*FREEZE_DIR_PARTS)


def _freeze_id(baseline: Dict[str, Any], frozen_at: str) -> str:
    material = [f"frozen_at:{frozen_at}"]
    material += [f"{name}:{baseline['fields'][name]['status']}:"
                 f"{baseline['fields'][name]['digest']}"
                 for name in VPLAN_BASELINE_FIELDS]
    return hashlib.sha256("\n".join(material).encode("utf-8")).hexdigest()[:16]


def freeze_vplan_baseline(root: Any, *, frozen_by: str,
                          vplan_path: Optional[Any] = None,
                          requirements_path: Optional[Any] = None,
                          configuration_ir_path: Optional[Any] = None,
                          declared: Optional[Dict[str, Any]] = None,
                          note: str = "") -> Dict[str, Any]:
    """Record one immutable frozen vPlan baseline. Requires `frozen_by`: an
    unattributable baseline is not a signoff-grade baseline, the same rule
    `signoff_export`'s CLI applies to its own `--frozen-by`.

    Writes `.dv-harness/vplan_baseline/freezes/<freeze_id>.json` plus one real
    `VPLAN_BASELINE_FROZEN` event. It approves nothing, runs no stage and
    grants no gate: a freeze is a RECORD of what a vPlan was produced
    against."""
    if not frozen_by:
        raise ValueError(
            "freeze_vplan_baseline requires frozen_by: an unattributable "
            "baseline is not a signoff-grade vPlan baseline")
    root = Path(root).resolve()
    baseline = capture_vplan_baseline(
        root, vplan_path=vplan_path, requirements_path=requirements_path,
        configuration_ir_path=configuration_ir_path, declared=declared)
    frozen_at = _now_iso()
    fid = _freeze_id(baseline, frozen_at)
    record = {
        "schema_version": SCHEMA_VERSION,
        "freeze_id": fid,
        "frozen_at": frozen_at,
        "frozen_by": frozen_by,
        "note": note,
        "project_root": str(root),
        "baseline": baseline,
    }

    fdir = freeze_dir(root)
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / (fid + ".json")).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # Best-effort audit trail -- a bookkeeping failure must never turn an
    # already-written freeze record into a failed freeze.
    try:
        from .storage import StateStore
        StateStore(root).event({
            "ts": frozen_at, "event": FREEZE_EVENT, "stage": "VPLAN",
            "freeze_id": fid, "frozen_by": frozen_by,
            "captured_fields": baseline["captured_field_count"],
            "not_available_fields": baseline["not_available_field_count"],
            "repo_head_sha": baseline["repo_head_sha"],
        })
    except Exception:
        pass
    return record


def list_freezes(root: Any) -> List[Dict[str, Any]]:
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


def load_freeze(root: Any, freeze_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One freeze record. With no `freeze_id`, the most recently frozen one --
    `frozen_at` order, not filesystem mtime, so copying the freeze tree does
    not reorder history."""
    records = list_freezes(root)
    if not records:
        return None
    if freeze_id is None:
        return records[-1]
    for r in records:
        if r.get("freeze_id") == freeze_id:
            return r
    return None


# --- post-freeze invalidation ------------------------------------------------


def _finding(code: str, severity: str, field: Optional[str],
            detail: Dict[str, Any]) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "field": field, "detail": detail}


def evaluate_vplan_freeze_invalidation(root: Any, frozen: Dict[str, Any], *,
                                       head: str = "HEAD",
                                       diff: Optional[Dict[str, Any]] = None,
                                       declared: Optional[Dict[str, Any]] = None,
                                       current_baseline: Optional[Dict[str, Any]] = None
                                       ) -> Dict[str, Any]:
    """VALID / INVALIDATED / UNKNOWN for one frozen vPlan baseline, from real
    evidence only -- the same three-part worst-wins design as
    `signoff_export.evaluate_freeze_invalidation()`:

    1. **Baseline field divergence.** All four fields are re-derived NOW,
       reading the SAME `vplan_path`/`requirements_path`/
       `configuration_ir_path` the freeze recorded (these files have no
       fixed conventional location, unlike signoff_export's project-wide
       fields), and compared by digest. A field CAPTURED at freeze that no
       longer matches, or that can no longer be captured at all,
       INVALIDATES. A field that was NOT_AVAILABLE at freeze and is CAPTURED
       now is INDETERMINATE, not invalidating -- evidence appearing after a
       freeze is a real change but not proof the frozen evidence was wrong.
    2. **Post-freeze impact analysis.** The REAL `change_impact.
       changed_files()` + `classify_risk()` over the freeze's recorded git
       HEAD. HIGH/MEDIUM changed files INVALIDATE and are named; LOW does
       not.

    `diff` and `current_baseline` are injectable so a test can drive the
    UNKNOWN branches without a real repository, mirroring
    `signoff_export.evaluate_freeze_invalidation()`'s own parameters.
    Nothing here writes, approves, revalidates or re-runs anything --
    REVALIDATION is a human act."""
    root = Path(root).resolve()
    frozen_baseline = (frozen or {}).get("baseline") or {}
    frozen_fields = frozen_baseline.get("fields") or {}
    if current_baseline is not None:
        current = current_baseline
    else:
        current = capture_vplan_baseline(
            root,
            vplan_path=frozen_baseline.get("vplan_path"),
            requirements_path=frozen_baseline.get("requirements_path"),
            configuration_ir_path=frozen_baseline.get("configuration_ir_path"),
            declared=declared)
    findings: List[Dict[str, Any]] = []

    for name in VPLAN_BASELINE_FIELDS:
        was = frozen_fields.get(name)
        now = current["fields"][name]
        if not isinstance(was, dict):
            findings.append(_finding(
                "FIELD_NOT_IN_FROZEN_BASELINE", SEV_INDETERMINATE, name,
                {"explanation": "the frozen record predates this baseline field, "
                                "so nothing about it can be compared",
                 "current_status": now["status"]}))
            continue
        if was.get("status") == CAPTURED and now["status"] == CAPTURED:
            if was.get("digest") != now.get("digest"):
                findings.append(_finding(
                    "BASELINE_FIELD_CHANGED", SEV_INVALIDATING, name,
                    {"frozen_digest": was.get("digest"),
                     "current_digest": now.get("digest"),
                     "source": now.get("source")}))
        elif was.get("status") == CAPTURED and now["status"] == NOT_AVAILABLE:
            findings.append(_finding(
                "BASELINE_EVIDENCE_DISAPPEARED", SEV_INVALIDATING, name,
                {"frozen_digest": was.get("digest"),
                 "frozen_source": was.get("source"),
                 "current_reason": now.get("reason")}))
        elif was.get("status") == NOT_AVAILABLE and now["status"] == CAPTURED:
            findings.append(_finding(
                "NEW_EVIDENCE_AFTER_FREEZE", SEV_INDETERMINATE, name,
                {"frozen_reason": was.get("reason"),
                 "current_digest": now.get("digest"),
                 "current_source": now.get("source")}))

    base_sha = frozen_baseline.get("repo_head_sha")
    impact: Dict[str, Any] = {"status": None, "changed_files": [],
                              "material_changes": [], "base_sha": base_sha,
                              "head": head}
    if not base_sha:
        impact["status"] = "NO_RECORDED_HEAD_SHA"
        findings.append(_finding(
            "POST_FREEZE_IMPACT_ANALYSIS_UNAVAILABLE", SEV_INDETERMINATE, None,
            {"reason": "the freeze recorded no git HEAD, so no change since it "
                      "can be computed"}))
    else:
        from . import change_impact
        d = diff if diff is not None else change_impact.changed_files(root, base_sha, head)
        impact["status"] = d.get("status")
        impact["detail"] = d.get("detail")
        impact["head_sha"] = d.get("head_sha")
        if d.get("status") != "REAL_DIFF":
            findings.append(_finding(
                "POST_FREEZE_IMPACT_ANALYSIS_UNAVAILABLE", SEV_INDETERMINATE, None,
                {"reason": "GIT_HISTORY_UNAVAILABLE: " + str(d.get("status")),
                 "detail": d.get("detail"), "base_sha": base_sha}))
        else:
            files = list(d.get("files") or [])
            impact["changed_files"] = files
            material = [{"path": f, "risk": change_impact.classify_risk(f)}
                       for f in files
                       if change_impact.classify_risk(f) in MATERIAL_CHANGE_RISKS]
            impact["material_changes"] = material
            if material:
                findings.append(_finding(
                    "POST_FREEZE_MATERIAL_CHANGE", SEV_INVALIDATING, None,
                    {"base_sha": base_sha, "head": head,
                     "changed_file_count": len(files),
                     "material_changes": material}))

    if any(f["severity"] == SEV_INVALIDATING for f in findings):
        status = FREEZE_INVALIDATED
    elif findings:
        status = FREEZE_UNKNOWN
    else:
        status = FREEZE_VALID

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "freeze_id": (frozen or {}).get("freeze_id"),
        "frozen_at": (frozen or {}).get("frozen_at"),
        "frozen_by": (frozen or {}).get("frozen_by"),
        "evaluated_at": _now_iso(),
        "findings": findings,
        "invalidating_count": sum(1 for f in findings if f["severity"] == SEV_INVALIDATING),
        "indeterminate_count": sum(1 for f in findings if f["severity"] == SEV_INDETERMINATE),
        "impact_analysis": impact,
        "current_baseline": current,
    }


def evaluate_all_vplan_freezes(root: Any, *, head: str = "HEAD",
                               declared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every recorded vPlan freeze, evaluated independently (unlike
    signoff_export's project-wide fields, each vPlan freeze may name
    different files, so there is no single shared "current baseline" to
    reuse across freezes). The report's own status is the WORST present --
    one invalidated freeze makes the report INVALIDATED."""
    root = Path(root).resolve()
    frozen = list_freezes(root)
    if not frozen:
        return {"schema_version": SCHEMA_VERSION, "status": "NOT_AVAILABLE",
                "reason": "NO_FROZEN_VPLAN_BASELINE",
                "freeze_dir": str(freeze_dir(root)), "freezes": []}
    results = [evaluate_vplan_freeze_invalidation(root, f, head=head, declared=declared)
               for f in frozen]
    worst = max(results, key=lambda r: _FREEZE_SEVERITY[r["status"]])["status"]
    return {"schema_version": SCHEMA_VERSION, "status": worst,
            "freeze_count": len(results),
            "counts": {s: sum(1 for r in results if r["status"] == s)
                       for s in (FREEZE_VALID, FREEZE_UNKNOWN, FREEZE_INVALIDATED)},
            "freezes": results, "evaluated_at": _now_iso()}


# --- front door --------------------------------------------------------------

def execute_verb(argv: Sequence[str]) -> int:
    """Shared implementation for `python -m dv_harness.vplan_baseline <verb>`.
    Exit 0 clear, 1 a real finding (a freeze is INVALIDATED), 2 nothing to
    report / usage refusal. A reporting signal, never an approval signal in
    either direction: no verb here approves, revalidates or runs anything."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="vplan-baseline",
        description="vPlan-scoped signoff freeze / baseline "
                    "(mirrors signoff_export.py's freeze/invalidation pattern).")
    ap.add_argument("verb", choices=["fields", "baseline", "freeze", "list", "status"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--vplan", default=None, help="path to a vPlan JSON document")
    ap.add_argument("--requirements", default=None,
                    help="path to a requirement-contract records JSON file")
    ap.add_argument("--configuration-ir", default=None,
                    help="path to a configuration-IR JSON document")
    ap.add_argument("--freeze-id", default=None)
    ap.add_argument("--frozen-by", default=None)
    ap.add_argument("--spec-version", default=None,
                    help="declare the spec version this vPlan is against "
                         "(recorded as attested, never as derived)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv))
    root = Path(args.root).resolve()
    declared = {"spec_version": args.spec_version} if args.spec_version else None

    if args.verb == "fields":
        print(json.dumps({"vplan_baseline_fields": list(VPLAN_BASELINE_FIELDS),
                          "field_statuses": [CAPTURED, NOT_AVAILABLE],
                          "freeze_statuses": [FREEZE_VALID, FREEZE_UNKNOWN,
                                              FREEZE_INVALIDATED]}, indent=2))
        return 0

    if args.verb == "baseline":
        b = capture_vplan_baseline(
            root, vplan_path=args.vplan, requirements_path=args.requirements,
            configuration_ir_path=args.configuration_ir, declared=declared)
        print(json.dumps(b, ensure_ascii=False, indent=2))
        return 0 if b["captured_field_count"] else 2

    if args.verb == "freeze":
        if not args.frozen_by:
            print(json.dumps({"status": "REFUSED", "reason": "FROZEN_BY_REQUIRED"}))
            return 2
        rec = freeze_vplan_baseline(
            root, frozen_by=args.frozen_by, vplan_path=args.vplan,
            requirements_path=args.requirements,
            configuration_ir_path=args.configuration_ir, declared=declared)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0

    if args.verb == "list":
        records = list_freezes(root)
        print(json.dumps(
            [{k: r[k] for k in ("freeze_id", "frozen_at", "frozen_by")}
             for r in records], indent=2))
        return 0 if records else 2

    if args.verb == "status":
        if args.freeze_id:
            rec = load_freeze(root, args.freeze_id)
            if rec is None:
                print(json.dumps({"status": "NOT_AVAILABLE",
                                  "reason": "FREEZE_ID_NOT_FOUND",
                                  "freeze_id": args.freeze_id}, indent=2))
                return 2
            result = evaluate_vplan_freeze_invalidation(root, rec, head=args.head,
                                                        declared=declared)
        else:
            result = evaluate_all_vplan_freezes(root, head=args.head, declared=declared)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] == "NOT_AVAILABLE":
            return 2
        return 1 if result["status"] == FREEZE_INVALIDATED else 0

    return 2  # pragma: no cover -- argparse `choices` makes this unreachable


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys
    return execute_verb(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    import sys
    sys.exit(main())
