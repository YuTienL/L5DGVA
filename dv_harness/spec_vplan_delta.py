"""dv_harness/spec_vplan_delta.py -- semantic diffing of a spec document's
CONTENT against a previously-recorded requirement-IR-shaped baseline
(2026-09-06, spec-vplan-delta gap close).

GAP THIS CLOSES. Nothing in this repo compared two requirement-IR snapshots
to say which individual requirements were ADDED, MODIFIED, REMOVED, or left
alone but need a human to re-check them anyway. `grep -rn
"spec_vplan_delta\\|requirement.*delta\\|semantic.*diff" --include=*.py .`
matched nothing executable before this module.

**THIS IS A DIFFERENT AXIS FROM `change_impact.py`, CONFIRMED BY READING IT.**
`change_impact.py`'s own docstring is explicit about what it computes: a real
`git diff --name-only <base>..<head>` over FILES, resolved to RTL modules via
the evidence DB and to REQ_ID/VPLAN_ID/PATTERN_ID/COVERAGE_ID via the real
`.dv-harness/requirements.csv` traceability registry (`load_trace_registry()`,
imported below, not re-implemented). It answers "which files changed on disk,
and which tests does that reach" -- it has no notion of a requirement
record's own CONTENT, and it never opens two spec/requirement documents to
compare them. This module answers a question `change_impact.py` cannot: given
two requirement-IR SNAPSHOTS (a previously-recorded baseline and a freshly
re-extracted current set -- however each was produced), which INDIVIDUAL
requirement changed, in WHAT WAY, independent of whether a single byte of
source code moved. A spec revision can rewrite a requirement's expected
behaviour with no git diff in this project at all (the source is the spec
document, which may live outside this repo's own git history), and
`change_impact.py`'s file-diff axis is structurally blind to that. The two
modules compose at a caller (file-diff selects regression scope;
content-diff selects which vPlan items need re-authoring) and neither
subsumes the other.

**ALSO DISTINCT FROM `vplan_baseline.py`.** That module freezes a vPlan
document's own IDENTITY as ONE aggregate hash and reports a single
VALID/REVALIDATION_REQUIRED/... verdict for the whole frozen set (did
ANYTHING move since signoff). This module reports a structured, PER
-REQUIREMENT classification of what moved and how -- the granularity
`vplan_baseline.py` explicitly leaves to "a project's own vPlan tooling"
(its own docstring: freezing counts and an aggregate hash, not per-item
diffs). Neither re-implements the other; `vplan_baseline.evaluate_vplan_
freeze_invalidation()`'s post-freeze impact analysis still goes through
`change_impact.py`, untouched here.

NO REQUIREMENT-IR PRODUCER IS GUARANTEED TO EXIST YET, so both `before` and
`after` are accepted as GENERIC, duck-typed parameters: a list of dicts, or a
dict carrying a top-level `requirements` list (the same shape
`requirement_contract.execute_verb()` already accepts, reused here rather
than inventing a second document convention). When a record happens to
declare `contract_schema_version` (`requirement_contract.declares_
contract_shape()`), this module additionally reuses `requirement_contract.
derive_status()` to report whether the requirement's own re-derived
COMPLETE/PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN status moved across the
delta -- extra evidence, never part of the ADDED/MODIFIED/REMOVED/
REVALIDATION_REQUIRED classification itself, which is shape-agnostic and
therefore works identically on a record that is not contract-shaped at all.

THE FOUR-PLUS-ONE STATUS VOCABULARY.
  - ADDED / REMOVED -- identity present in only one snapshot.
  - MODIFIED -- identity present in both, and at least one CONTENT field
    (the requirement's actual behavioural claim -- stimulus, expected
    result, checker, ...) differs.
  - REVALIDATION_REQUIRED -- identity present in both, CONTENT is
    byte-identical, but a PROVENANCE field differs (which spec citation it
    traces to, its confidence, its priority/criticality, a filed ambiguity
    or contradiction, its schema version). The behaviour nobody re-wrote,
    but something about the evidence backing it moved, so a human should
    re-confirm the extracted content still matches before trusting it
    again. Spelled identically to `waiver_store.py`'s own
    `WAIVER_STATUSES` entry of the same name -- this project's established
    word for "neither provably fine nor provably wrong" -- though it is a
    different axis here (requirement provenance drift, not a waiver
    trigger).
  - UNCHANGED -- present in both, nothing differs. Reported for complete
    accounting; never one of the four statuses this module is asked to
    report as a FINDING, but omitting it would make "nothing changed" look
    identical to "we didn't check".

VPLAN LINKAGE IS READ, NEVER INVENTED. When a caller supplies `root`, every
non-UNCHANGED requirement is cross-referenced against the REAL
`.dv-harness/requirements.csv` registry via `change_impact.load_trace_
registry()` (imported, not re-parsed) to attach the real VPLAN_ID/
PATTERN_ID/SCENARIO_ID/COMMAND_ID/COVERAGE_ID rows the traceability registry
already asserts for that REQ_ID -- never a fabricated linkage. No `root` ->
`vplan_linkage: NOT_REQUESTED`, an honest "the caller chose not to ask", kept
distinct from `NO_REGISTRY_ROW` (asked, and the registry has nothing for this
id) and `NOT_AVAILABLE` (asked, but no registry file exists at all).

DELIBERATELY BOUNDED, and stated rather than implied closed. (1) This module
does not parse a spec document into requirement-IR records -- that is a
separate extraction problem this repo has no canonical producer for yet
(the very reason `before`/`after` are generic parameters). It compares two
ALREADY-EXTRACTED snapshots. (2) It does not decide which snapshot is
"right" when both look equally complete -- there is no arbitration here, the
same boundary `requirement_contract.py`'s own docstring keeps for
CONTRADICTORY requirements. (3) It writes nothing and runs no gate: no
approval is minted, no stage advances, and there is deliberately no
`STAGE_GATES` entry -- a gate that passed because nobody supplied a baseline
yet would be worse than none. (4) A requirement identity is resolved from
`requirement_id` (section 184's field name), then `req_id` (the CSV
registry's / older shape's spelling), then `id`, in that order, or a caller
-declared `identity_field` -- an unresolvable identity is reported, never
silently dropped from the count.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import change_impact
from . import requirement_contract

SCHEMA_VERSION = "1.0"

# --- status vocabulary -----------------------------------------------------

STATUS_ADDED = "ADDED"
STATUS_MODIFIED = "MODIFIED"
STATUS_REMOVED = "REMOVED"
STATUS_REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
STATUS_UNCHANGED = "UNCHANGED"

#: The four this module is asked to report per requirement, in the task's
#: own order.
DELTA_STATUSES: Tuple[str, ...] = (
    STATUS_ADDED, STATUS_MODIFIED, STATUS_REMOVED, STATUS_REVALIDATION_REQUIRED,
)
#: All five, including the honest "nothing changed" bucket, for accounting.
ALL_STATUSES: Tuple[str, ...] = DELTA_STATUSES + (STATUS_UNCHANGED,)

#: Candidate identity fields, checked in this order. `requirement_id` is
#: section 184's canonical spelling (requirement_contract.CONTRACT_FIELDS[0]);
#: `req_id` is the traceability registry's / the older
#: spec_to_vplan_requirement_quality_gate.py shape's spelling; `id` is a
#: last-resort generic fallback for a caller's own IR shape.
IDENTITY_FIELD_CANDIDATES: Tuple[str, ...] = ("requirement_id", "req_id", "id")

#: Fields that describe PROVENANCE / classification / evidence-quality about
#: a requirement rather than the requirement's own behavioural CONTENT. A
#: change confined to these fields, with every other field byte-identical,
#: is REVALIDATION_REQUIRED rather than MODIFIED -- the behaviour nobody
#: rewrote, but the evidence backing it moved. Deliberately a superset large
#: enough to cover both requirement_contract.py's own carrier fields
#: (source/confidence/priority/criticality/status/ambiguities/
#: contradictions/support_status/design_evidence/contract_schema_version)
#: and common generic-IR provenance spellings (notes/revision/
#: extracted_at/extracted_by/confirmed_by), since no producer is guaranteed
#: to exist yet and a caller's own IR may spell these differently again --
#: which is exactly why `revalidation_fields=` lets a caller replace this set
#: entirely for their own shape.
REVALIDATION_ONLY_FIELD_NAMES: frozenset = frozenset({
    "source", "confidence", "status", "priority", "criticality",
    "ambiguities", "contradictions", "support_status", "design_evidence",
    "contract_schema_version", "notes", "revision", "spec_revision",
    "extracted_at", "extracted_by", "confirmed_by",
})

LINKAGE_NOT_REQUESTED = "NOT_REQUESTED"
LINKAGE_NO_REGISTRY_ROW = "NO_REGISTRY_ROW"
LINKAGE_NOT_AVAILABLE = "NOT_AVAILABLE"


# --------------------------------------------------------------------------
# document / record normalization
# --------------------------------------------------------------------------

def _extract_records(doc: Any) -> List[Any]:
    """Same convention `requirement_contract.execute_verb()` already uses:
    a bare list IS the record set; a dict's top-level `requirements` list is
    the record set; anything else is empty rather than guessed at."""
    if isinstance(doc, dict):
        recs = doc.get("requirements", [])
        return recs if isinstance(recs, list) else []
    if isinstance(doc, list):
        return doc
    return []


def _record_identity(record: Any, identity_field: Optional[str] = None) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    if identity_field:
        v = record.get(identity_field)
        return str(v) if v not in (None, "") else None
    for f in IDENTITY_FIELD_CANDIDATES:
        v = record.get(f)
        if v not in (None, ""):
            return str(v)
    return None


def index_by_identity(records: Sequence[Any],
                       identity_field: Optional[str] = None) -> Dict[str, Any]:
    """(index, duplicate_ids, unidentified_count). `duplicate_ids` is a list
    of ids that appeared more than once -- the FIRST occurrence wins the
    index slot (so a lookup never crashes), but the duplicate is reported
    rather than silently overwritten, mirroring requirement_contract.py's
    own DUPLICATE_REQUIREMENT_ID check."""
    index: Dict[str, Any] = {}
    duplicates: List[str] = []
    unidentified = 0
    for rec in records:
        ident = _record_identity(rec, identity_field)
        if ident is None:
            unidentified += 1
            continue
        if ident in index:
            duplicates.append(ident)
            continue
        index[ident] = rec
    return index, duplicates, unidentified


def _normalize_value(v: Any) -> Any:
    """None and an all-whitespace string both mean "nothing was written
    here" for diff purposes -- a record re-serialized with an empty-string
    default must not read as MODIFIED against one that simply omitted the
    key. Anything else is compared by its real (structurally normalized)
    value."""
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, default=str)
    return v


def _diff_fields(before: Dict[str, Any], after: Dict[str, Any],
                 fields: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Only the fields that actually differ, each carrying its real raw
    before/after value (not the normalized comparison form) so a reader sees
    what was actually written."""
    out: Dict[str, Dict[str, Any]] = {}
    for f in fields:
        b_raw, a_raw = before.get(f), after.get(f)
        if _normalize_value(b_raw) != _normalize_value(a_raw):
            out[f] = {"before": b_raw, "after": a_raw}
    return out


def content_fields_for(before: Dict[str, Any], after: Dict[str, Any], *,
                       identity_field_used: Optional[str] = None,
                       revalidation_fields: Optional[Sequence[str]] = None) -> Tuple[str, ...]:
    """Every field present in EITHER record except the identity field itself
    and the (default or caller-declared) provenance-only set. Deliberately
    shape-agnostic: a contract-shaped record's nine `CONTRACT_TEXT_FIELDS`
    (feature/protocol/configuration/precondition/stimulus/expected_result/
    observability/checker/coverage_intent) fall out of this naturally,
    because none of them is in `REVALIDATION_ONLY_FIELD_NAMES` -- there is no
    separate contract-shaped code path to keep in sync."""
    reval = frozenset(revalidation_fields) if revalidation_fields is not None \
        else REVALIDATION_ONLY_FIELD_NAMES
    keys = (set(before) | set(after)) - reval
    if identity_field_used:
        keys.discard(identity_field_used)
    for cand in IDENTITY_FIELD_CANDIDATES:
        keys.discard(cand)
    return tuple(sorted(keys))


def classify_requirement_delta(before: Dict[str, Any], after: Dict[str, Any], *,
                               identity_field_used: Optional[str] = None,
                               content_fields: Optional[Sequence[str]] = None,
                               revalidation_fields: Optional[Sequence[str]] = None
                               ) -> Tuple[str, Dict[str, Any]]:
    """Classify a requirement present in BOTH snapshots. Never called for a
    pure ADDED/REMOVED id -- those are decided at the set level, since there
    is no "before" or "after" record to compare against.

    Worst-wins: MODIFIED (a real behavioural change) beats
    REVALIDATION_REQUIRED (only provenance moved) beats UNCHANGED."""
    c_fields = tuple(content_fields) if content_fields is not None else \
        content_fields_for(before, after, identity_field_used=identity_field_used,
                            revalidation_fields=revalidation_fields)
    content_diff = _diff_fields(before, after, c_fields)
    if content_diff:
        return STATUS_MODIFIED, {"changed_content_fields": content_diff}

    reval_fields = tuple(revalidation_fields) if revalidation_fields is not None \
        else tuple(sorted(REVALIDATION_ONLY_FIELD_NAMES))
    reval_diff = _diff_fields(before, after, reval_fields)
    if reval_diff:
        return STATUS_REVALIDATION_REQUIRED, {"changed_revalidation_fields": reval_diff}

    return STATUS_UNCHANGED, {}


# --------------------------------------------------------------------------
# real vPlan traceability linkage (change_impact.py's registry, read-only)
# --------------------------------------------------------------------------

def _vplan_linkage_for(req_id: str, root: Optional[Any]) -> Dict[str, Any]:
    """Real rows from `.dv-harness/requirements.csv`, resolved through
    `change_impact.load_trace_registry()` -- never a second CSV reader, and
    never a fabricated VPLAN_ID. `root is None` means the caller chose not
    to ask; that is a different fact from asking and finding nothing."""
    if root is None:
        return {"status": LINKAGE_NOT_REQUESTED, "rows": []}
    try:
        registry = change_impact.load_trace_registry(Path(root))
    except Exception as exc:  # pragma: no cover - defensive, mirrors sibling modules
        return {"status": LINKAGE_NOT_AVAILABLE, "reason": str(exc), "rows": []}
    matches = [r for r in registry if r.get("REQ_ID", "") == req_id]
    if not matches:
        return {"status": LINKAGE_NO_REGISTRY_ROW, "rows": []}
    rows = [{
        "vplan_id": r.get("VPLAN_ID", ""),
        "scenario_id": r.get("SCENARIO_ID", ""),
        "command_id": r.get("COMMAND_ID", ""),
        "pattern_id": r.get("PATTERN_ID", ""),
        "coverage_id": r.get("COVERAGE_ID", ""),
    } for r in matches]
    return {"status": "LINKED", "rows": rows}


# --------------------------------------------------------------------------
# contract-shaped enrichment (reuse, not re-derivation)
# --------------------------------------------------------------------------

def _derived_status_delta(before: Any, after: Any) -> Optional[Dict[str, Any]]:
    """When BOTH sides declare the section-184 contract shape, report
    whether requirement_contract.derive_status()'s own re-derived status
    moved across the delta. This is extra evidence surfaced from an EXISTING
    function -- never a second status-derivation implementation, and it
    never feeds back into ADDED/MODIFIED/REMOVED/REVALIDATION_REQUIRED."""
    if not (requirement_contract.declares_contract_shape(before)
            and requirement_contract.declares_contract_shape(after)):
        return None
    try:
        b_status, b_reason = requirement_contract.derive_status(before)
        a_status, a_reason = requirement_contract.derive_status(after)
    except Exception:  # pragma: no cover - defensive
        return None
    if b_status == a_status:
        return None
    return {"before": b_status, "before_reason": b_reason,
            "after": a_status, "after_reason": a_reason}


# --------------------------------------------------------------------------
# the set-level diff
# --------------------------------------------------------------------------

def diff_requirement_sets(before: Any, after: Any, *,
                          identity_field: Optional[str] = None,
                          content_fields: Optional[Sequence[str]] = None,
                          revalidation_fields: Optional[Sequence[str]] = None,
                          root: Optional[Any] = None) -> Dict[str, Any]:
    """The core comparison. `before`/`after` are each either a bare list of
    requirement-IR-shaped dicts, or a dict carrying a top-level
    `requirements` list -- generic/duck-typed, per this module's own no
    -guaranteed-producer disclosure. `root`, if given, grounds affected
    vPlan/pattern/coverage references in the REAL traceability registry;
    omit it to get an honest NOT_REQUESTED on every linkage instead."""
    before_records = _extract_records(before)
    after_records = _extract_records(after)

    before_index, before_dups, before_unident = index_by_identity(before_records, identity_field)
    after_index, after_dups, after_unident = index_by_identity(after_records, identity_field)

    before_ids = set(before_index)
    after_ids = set(after_index)

    items: List[Dict[str, Any]] = []
    status_counts: Dict[str, int] = {s: 0 for s in ALL_STATUSES}

    for req_id in sorted(after_ids - before_ids):
        status_counts[STATUS_ADDED] += 1
        items.append({
            "requirement_id": req_id,
            "status": STATUS_ADDED,
            "vplan_linkage": _vplan_linkage_for(req_id, root),
        })

    for req_id in sorted(before_ids - after_ids):
        status_counts[STATUS_REMOVED] += 1
        items.append({
            "requirement_id": req_id,
            "status": STATUS_REMOVED,
            "vplan_linkage": _vplan_linkage_for(req_id, root),
        })

    for req_id in sorted(before_ids & after_ids):
        b_rec, a_rec = before_index[req_id], after_index[req_id]
        status, detail = classify_requirement_delta(
            b_rec, a_rec, identity_field_used=identity_field,
            content_fields=content_fields, revalidation_fields=revalidation_fields)
        status_counts[status] += 1
        item: Dict[str, Any] = {"requirement_id": req_id, "status": status, **detail}
        if status != STATUS_UNCHANGED:
            item["vplan_linkage"] = _vplan_linkage_for(req_id, root)
        derived = _derived_status_delta(b_rec, a_rec)
        if derived is not None:
            item["derived_status_delta"] = derived
        items.append(item)

    items.sort(key=lambda it: (DELTA_STATUSES.index(it["status"])
                               if it["status"] in DELTA_STATUSES else len(DELTA_STATUSES),
                               it["requirement_id"]))

    delta_found = any(status_counts[s] for s in DELTA_STATUSES)
    if not before_records and not after_records:
        overall = "NOT_AVAILABLE"
    elif delta_found:
        overall = "DELTA_FOUND"
    else:
        overall = "NO_DELTA"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall,
        "before_count": len(before_records),
        "after_count": len(after_records),
        "status_counts": status_counts,
        "items": items,
        "duplicate_identities": {"before": sorted(set(before_dups)),
                                 "after": sorted(set(after_dups))},
        "unidentified_records": {"before": before_unident, "after": after_unident},
        "vplan_linkage_requested": root is not None,
    }


# --------------------------------------------------------------------------
# CLI (same execute_verb convention as power_intent / golden_scenario)
# --------------------------------------------------------------------------

def _load_doc(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute_verb(before_path: str, after_path: str, *, root: Optional[str] = None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Exit codes: 0 NO_DELTA, 1 DELTA_FOUND (a real ADDED/MODIFIED/REMOVED/
    REVALIDATION_REQUIRED item exists), 2 NOT_AVAILABLE (a file could not be
    read, or both snapshots are empty)."""
    try:
        before_doc = _load_doc(before_path)
        after_doc = _load_doc(after_path)
    except (OSError, ValueError) as exc:
        result = {"status": "NOT_AVAILABLE", "reason": str(exc)}
        return (json.dumps(result, indent=2) if as_json
                else f"NOT_AVAILABLE: {exc}"), 2

    result = diff_requirement_sets(before_doc, after_doc, root=root)
    result["before_source"] = str(before_path)
    result["after_source"] = str(after_path)

    code = 2 if result["status"] == "NOT_AVAILABLE" else (1 if result["status"] == "DELTA_FOUND" else 0)

    if as_json:
        return json.dumps(result, indent=2), code

    lines = [f"spec-vplan-delta: {result['status']} "
             f"(before={result['before_count']}, after={result['after_count']})"]
    for s in ALL_STATUSES:
        if result["status_counts"].get(s):
            lines.append(f"  {s}: {result['status_counts'][s]}")
    if result["duplicate_identities"]["before"] or result["duplicate_identities"]["after"]:
        lines.append(f"  duplicate identities: before={result['duplicate_identities']['before']} "
                     f"after={result['duplicate_identities']['after']}")
    if result["unidentified_records"]["before"] or result["unidentified_records"]["after"]:
        lines.append(f"  unidentified records: before={result['unidentified_records']['before']} "
                     f"after={result['unidentified_records']['after']}")
    for it in result["items"]:
        if it["status"] == STATUS_UNCHANGED:
            continue
        lines.append(f"  [{it['status']}] {it['requirement_id']}")
        if it.get("changed_content_fields"):
            lines.append(f"      content: {sorted(it['changed_content_fields'])}")
        if it.get("changed_revalidation_fields"):
            lines.append(f"      revalidation: {sorted(it['changed_revalidation_fields'])}")
        if it.get("derived_status_delta"):
            dd = it["derived_status_delta"]
            lines.append(f"      derived status: {dd['before']} -> {dd['after']}")
    return "\n".join(lines), code


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin shell
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.spec_vplan_delta",
        description="Semantic diff of two requirement-IR-shaped snapshots: "
                    "ADDED/MODIFIED/REMOVED/REVALIDATION_REQUIRED per requirement.")
    ap.add_argument("--before", required=True, help="Baseline requirement-IR JSON file.")
    ap.add_argument("--after", required=True, help="Current requirement-IR JSON file.")
    ap.add_argument("--root", default=None,
                    help="Project root whose .dv-harness/requirements.csv grounds "
                        "vPlan/pattern/coverage linkage for changed requirements.")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.before, a.after, root=a.root, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
