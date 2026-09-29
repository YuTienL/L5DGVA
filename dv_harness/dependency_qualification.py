"""dv_harness/dependency_qualification.py -- the QUALIFICATION record for a
dependency/VIP/third-party component: has it been VETTED, by WHOM, against
WHAT CRITERIA -- as a distinct artifact from `dependency_supply_chain.py`'s
inventory/pinning/advisory checks.

THE GAP (re-verified by direct search before anything was written): the real
`dependency_supply_chain.py` (2026-09-06) answers three purely MECHANICAL
questions about a declared Python/VIP dependency -- is its version pinned, does
the installed version satisfy what was declared, is there a known
vulnerability against it. None of those three checks is, or could be, a human
GOVERNANCE decision: no code anywhere in this repository records that a human
reviewer actually looked at a specific component, what criteria they checked
it against (license terms, a security review, functional validation, export-
control clearance, maintenance status), and what they decided. A repo-wide
grep for `vetted`/`qualification_record`/`reviewer`/`dependency_qualification`
before this module returned nothing. `dv_harness/qualification.py` is a
DIFFERENT, already-real mechanism this module does not duplicate or extend --
it is the 8-tier PROTOCOL-QUALIFICATION-STATUS ladder for a generated
verification ENVIRONMENT's own maturity (BUILDER_AVAILABLE .. PRODUCTION_
QUALIFIED); it has no notion of a third-party component at all, and this
module's `QUALIFICATION_STATUSES` are a deliberately separate vocabulary
(never a member of `qualification.QualificationTier`, checked disjoint at
import). `knowledge_center.py`'s SYOSCB-3 `THIRD_PARTY_COMPONENT_FIELDS`
(COMPONENT/VERSION/SOURCE_REFERENCE/ROLE/INTEGRATION_POLICY/L5_DESTINATION/
BUILD_STATUS/KNOWN_LIMITATIONS/PROVENANCE/UPSTREAM_DEPENDENCIES/EVIDENCE) is
also a different, already-real mechanism, read but not extended: it is a
REGISTRATION record for a shared, cross-project knowledge shard (what a
component IS, where it lives, what it needs to build) -- it carries no
reviewer identity, no criteria checklist, and no APPROVED/CONDITIONAL/REJECTED
decision, and publishing to it is a REMOTE_EXECUTION act this module never
performs.

WHAT IS REUSED RATHER THAN REBUILT. `dependency_supply_chain.py`'s real
inventory (`build_inventory()`) is the INPUT this module qualifies against --
there is no second dependency scanner, no second VIP-release reader, and no
second `packaging`-based version parser here. A qualification record names a
real `(ecosystem, component)` pair, and when a caller supplies the real
inventory this module REFUSES to record a qualification for a component that
inventory does not contain (`VETTING_TARGET_NOT_IN_INVENTORY`) -- qualifying a
component nobody has shown this project actually depends on would be recording
a governance decision about a phantom fact. `evaluate_qualification_coverage()`
then joins the real inventory against this module's own ledger, per component,
so "does our supply chain include anything nobody has ever vetted" has one
real, computed answer instead of a spreadsheet a human maintains by hand.

`status` (has this component's qualification actually held up) is DERIVED by
`derive_status()` on every read and REFUSED as a stored field by
`record_qualification()` -- the same reason `waiver_store.derive_status()` is
never trusted from the record: a stored status is wrong the instant the
component's pinned version moves, an expiry passes, or a human revokes the
decision. "We could not check" is never VETTED: a record missing a required
field, an unparseable timestamp, or a qualified version this project's real
inventory no longer matches all derive UNKNOWN/REVALIDATION_REQUIRED with a
real, named reason -- never a silent pass.

This module ARBITRATES nothing and RUNS nothing: no build, job, or approval is
touched, and there is deliberately no `STAGE_GATES` entry -- a gate that passed
because a component was qualified nobody ever re-checked against the moving
inventory would be worse than none. Recording a qualification, and revoking
one, are human acts (`record_qualification()` / `revoke_qualification()`),
never something this module infers on its own.

DISCLOSED, not implied closed: there is no `dv-harness` CLI verb -- `cli.py`
(4,100+ lines) is under concurrent edit by other parallel work in this same
batch, the same disclosed choice several very recent same-day additions in
this repository have already made. The front door is
`python -m dv_harness.dependency_qualification`.
"""
from __future__ import annotations

import datetime as _dt
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .storage import _atomic_replace

SCHEMA_VERSION = "1.0"

STORE_RELATIVE_PATH = ".dv-harness/qualification/dependency_qualifications.json"


class DependencyQualificationError(ValueError):
    """A qualification record refused by `record_qualification()`, or a
    malformed request to any other write path in this module. Never raised on
    a read."""


# --------------------------------------------------------------------------
# Vocabularies. Deliberately disjoint from `models.Status` (a qualification
# finding is not a stage-gate verdict) AND from `qualification.
# QualificationTier` (a component vetting decision is not an environment
# maturity tier) -- held by `assert_no_vocabulary_collision()`, the same rule
# and the same reason `dependency_supply_chain.py`'s own guard applies to its
# three vocabularies.
# --------------------------------------------------------------------------

#: The human decision recorded on a qualification. Never derived -- a human
#: made this call.
DECISION_APPROVED = "APPROVED"
DECISION_CONDITIONAL = "CONDITIONAL"
DECISION_REJECTED = "REJECTED"
DECISIONS = (DECISION_APPROVED, DECISION_CONDITIONAL, DECISION_REJECTED)

#: The fixed criteria vocabulary a qualification may be checked against. A
#: record's `criteria` dict may name any subset of these (never an unknown
#: key -- `record_qualification()` refuses one by name), each carrying a
#: PASS/FAIL/NOT_APPLICABLE result plus (for PASS/FAIL) a real, non-empty
#: evidence citation.
CRITERION_LICENSE_REVIEW = "LICENSE_REVIEW"
CRITERION_SECURITY_REVIEW = "SECURITY_REVIEW"
CRITERION_FUNCTIONAL_VALIDATION = "FUNCTIONAL_VALIDATION"
CRITERION_EXPORT_CONTROL_REVIEW = "EXPORT_CONTROL_REVIEW"
CRITERION_MAINTENANCE_STATUS_REVIEW = "MAINTENANCE_STATUS_REVIEW"
QUALIFICATION_CRITERIA = (
    CRITERION_LICENSE_REVIEW, CRITERION_SECURITY_REVIEW,
    CRITERION_FUNCTIONAL_VALIDATION, CRITERION_EXPORT_CONTROL_REVIEW,
    CRITERION_MAINTENANCE_STATUS_REVIEW,
)

#: Deliberately MET/UNMET (never PASS/FAIL, which collide with
#: `dv_harness.models.Status`) -- a qualification criterion's result is a
#: governance check, not a stage-gate verdict, the same MET/UNMET vocabulary
#: `spec_vplan_readiness_gate.py`'s own condition statuses already use.
CRITERION_RESULT_MET = "MET"
CRITERION_RESULT_UNMET = "UNMET"
CRITERION_RESULT_NOT_APPLICABLE = "NOT_APPLICABLE"
CRITERION_RESULTS = (CRITERION_RESULT_MET, CRITERION_RESULT_UNMET, CRITERION_RESULT_NOT_APPLICABLE)

#: `status` (this module's own derived vocabulary): whether a recorded
#: qualification decision still holds, computed fresh on every read.
STATUS_VETTED = "VETTED"
STATUS_CONDITIONALLY_VETTED = "CONDITIONALLY_VETTED"
STATUS_REJECTED = "REJECTED"
STATUS_EXPIRED = "EXPIRED"
STATUS_REVOKED = "REVOKED"
STATUS_REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
STATUS_UNKNOWN = "UNKNOWN"
QUALIFICATION_STATUSES = (
    STATUS_VETTED, STATUS_CONDITIONALLY_VETTED, STATUS_REJECTED, STATUS_EXPIRED,
    STATUS_REVOKED, STATUS_REVALIDATION_REQUIRED, STATUS_UNKNOWN,
)

#: A component this project's real inventory carries with no vetted coverage
#: at all -- the honest common state before this module has ever been used.
COVERAGE_NOT_QUALIFIED = "NOT_QUALIFIED"

#: Coverage-report overall status. Only VETTED/CONDITIONALLY_VETTED coverage
#: on EVERY inventory component earns ALL_QUALIFIED -- worst-wins, never
#: averaged: a single component left NOT_QUALIFIED/REJECTED/EXPIRED/REVOKED/
#: UNKNOWN/REVALIDATION_REQUIRED blocks the whole report regardless of how
#: many other components are cleanly vetted.
REPORT_ALL_QUALIFIED = "ALL_QUALIFIED"
REPORT_GAPS_FOUND = "QUALIFICATION_GAPS_FOUND"
REPORT_NOT_AVAILABLE = "NOT_AVAILABLE"
REPORT_STATUSES = (REPORT_ALL_QUALIFIED, REPORT_GAPS_FOUND, REPORT_NOT_AVAILABLE)

#: Coverage states that count as a real gap in `evaluate_qualification_
#: coverage()`'s worst-wins fold -- everything a component's derived status
#: can be EXCEPT the two human-approved-and-still-valid outcomes.
_BLOCKING_COVERAGE_STATUSES = frozenset({
    COVERAGE_NOT_QUALIFIED, STATUS_REJECTED, STATUS_EXPIRED, STATUS_REVOKED,
    STATUS_REVALIDATION_REQUIRED, STATUS_UNKNOWN,
})

#: The one revalidation trigger this module currently measures: has the
#: project's real inventory pinned/installed a DIFFERENT version than the one
#: a human actually reviewed. Restricted to a fact this module can really
#: check (mirrors `waiver_store.SUPPORTED_TRIGGER_KEYS`'s own "never declare a
#: trigger nothing checks" discipline) -- declaring an unsupported key is
#: refused by name.
SUPPORTED_TRIGGER_KEYS = ("version",)

CANONICAL_REQUIRED_FIELDS = (
    "qualification_id", "component", "ecosystem", "version_qualified",
    "vetted_by", "vetted_at", "criteria", "decision", "evidence",
)


def assert_no_vocabulary_collision() -> None:
    """This module's own vocabularies must share no token with
    `dv_harness.models.Status` (a qualification finding is not a stage-gate
    verdict) or with `dv_harness.qualification.CANONICAL_LADDER` (a component
    vetting decision is not an environment-maturity tier). Checkable here
    rather than asserted in prose, the same reason
    `dependency_supply_chain.assert_no_verification_verdict_vocabulary()`
    exists."""
    from .models import Status
    from . import qualification as _env_qualification

    verdicts = {s.value for s in Status}
    ladder = set(_env_qualification.CANONICAL_LADDER)
    for name, vocabulary in (
        ("DECISIONS", DECISIONS),
        ("CRITERION_RESULTS", CRITERION_RESULTS),
        ("QUALIFICATION_STATUSES", QUALIFICATION_STATUSES),
        ("REPORT_STATUSES", REPORT_STATUSES),
    ):
        collision = verdicts.intersection(vocabulary)
        if collision:
            raise DependencyQualificationError(
                f"{name} collides with dv_harness.models.Status on {sorted(collision)}; "
                "a dependency-qualification token must never be readable as a stage verdict")
        collision = ladder.intersection(vocabulary)
        if collision:
            raise DependencyQualificationError(
                f"{name} collides with dv_harness.qualification.CANONICAL_LADDER on "
                f"{sorted(collision)}; a component vetting decision is not an environment "
                "maturity tier")


assert_no_vocabulary_collision()


# --------------------------------------------------------------------------
# Store I/O -- same atomic-replace convention `waiver_store.py` already uses.
# --------------------------------------------------------------------------

def _store_path(root) -> Path:
    return Path(root) / STORE_RELATIVE_PATH


def store_exists(root) -> bool:
    return _store_path(root).is_file()


def read_qualifications(root) -> List[Dict[str, Any]]:
    path = _store_path(root)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_qualifications(root, records: List[Dict[str, Any]]) -> None:
    path = _store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, dir=str(path.parent), encoding="utf-8")
    try:
        json.dump(records, tmp, indent=2)
        tmp.close()
        _atomic_replace(tmp.name, path)
    except Exception:
        tmp.close()
        try:
            Path(tmp.name).unlink()
        except FileNotFoundError:
            pass
        raise


# --------------------------------------------------------------------------
# Reusing dependency_supply_chain.py's inventory as the qualification target
# universe.
# --------------------------------------------------------------------------

def known_component_key(ecosystem: str, component: str) -> Tuple[str, str]:
    return (str(ecosystem or "").strip().lower(), str(component or "").strip().lower())


def known_components_from_inventory(inventory: Mapping[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """The real `(ecosystem, component)` -> component-record map off a
    `dependency_supply_chain.build_inventory()` result. This module reads that
    result's own `ecosystem`/`name` fields verbatim -- there is no second
    inventory scan here."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for component in (inventory or {}).get("components") or []:
        name = component.get("name")
        if not name:
            continue
        out[known_component_key(component.get("ecosystem"), name)] = component
    return out


# --------------------------------------------------------------------------
# Recording and revoking a qualification decision. Both are human acts.
# --------------------------------------------------------------------------

def record_qualification(root, record: Dict[str, Any],
                         known_components: Optional[Mapping[Tuple[str, str], Any]] = None
                         ) -> Dict[str, Any]:
    """Record one qualification decision. Refuses:
      - a missing canonical field,
      - a caller-supplied `status` (derived on every read, never stored --
        the same reason `waiver_store.record_waiver()` refuses one),
      - a `criteria` dict naming an unrecognized criterion, an unrecognized
        result, or a PASS/FAIL result with no evidence citation,
      - an empty `criteria` dict ("against what criteria" cannot be answered
        by an empty set),
      - `decision` outside DECISIONS,
      - decision=APPROVED while any criterion result is FAIL (a self-
        contradictory record -- an approval that itself names a failed
        check is not a shape-valid approval),
      - decision=CONDITIONAL with no non-empty `conditions` text,
      - a revalidation trigger key outside SUPPORTED_TRIGGER_KEYS,
      - a duplicate `qualification_id`,
      - (when `known_components` is supplied) a `(ecosystem, component)` pair
        this project's real inventory does not contain --
        `VETTING_TARGET_NOT_IN_INVENTORY`, never a qualification recorded
        against a phantom dependency.
    """
    if not isinstance(record, dict):
        raise DependencyQualificationError("qualification record must be a mapping")
    record = dict(record)
    if "status" in record:
        raise DependencyQualificationError(
            "qualification `status` is derived from the record's own content on every "
            "read (derive_status()) and must not be stored -- a stored status is wrong "
            "the instant the component's pinned version moves or the record is revoked")
    missing = [f for f in CANONICAL_REQUIRED_FIELDS if not record.get(f)]
    if missing:
        raise DependencyQualificationError(f"qualification record missing required fields: {missing}")

    decision = record.get("decision")
    if decision not in DECISIONS:
        raise DependencyQualificationError(f"decision {decision!r} is not one of {DECISIONS}")

    criteria = record.get("criteria")
    if not isinstance(criteria, dict) or not criteria:
        raise DependencyQualificationError(
            "qualification `criteria` must be a non-empty mapping -- \"against what "
            "criteria\" cannot be answered by an empty set")
    unsupported = sorted(set(criteria) - set(QUALIFICATION_CRITERIA))
    if unsupported:
        raise DependencyQualificationError(
            f"criteria key(s) {unsupported} are not in the recognized vocabulary: "
            f"{list(QUALIFICATION_CRITERIA)}")
    any_fail = False
    for key, entry in criteria.items():
        if not isinstance(entry, dict):
            raise DependencyQualificationError(f"criteria[{key!r}] must be a mapping")
        result = entry.get("result")
        if result not in CRITERION_RESULTS:
            raise DependencyQualificationError(
                f"criteria[{key!r}].result {result!r} is not one of {CRITERION_RESULTS}")
        if result in (CRITERION_RESULT_MET, CRITERION_RESULT_UNMET) and not entry.get("evidence"):
            raise DependencyQualificationError(
                f"criteria[{key!r}] declares result={result!r} with no evidence citation -- "
                "an unsupported criterion claim is exactly what this module refuses to record")
        if result == CRITERION_RESULT_UNMET:
            any_fail = True

    if decision == DECISION_APPROVED and any_fail:
        raise DependencyQualificationError(
            "decision=APPROVED but at least one criterion result is FAIL -- a "
            "self-contradictory record; reject or condition it instead")
    if decision == DECISION_CONDITIONAL and not str(record.get("conditions") or "").strip():
        raise DependencyQualificationError(
            "decision=CONDITIONAL requires non-empty `conditions` text naming what the "
            "conditional approval depends on")

    trigger = record.get("revalidation_trigger") or {}
    if not isinstance(trigger, dict):
        raise DependencyQualificationError("qualification `revalidation_trigger` must be a mapping")
    unsupported_trigger = sorted(set(trigger) - set(SUPPORTED_TRIGGER_KEYS))
    if unsupported_trigger:
        raise DependencyQualificationError(
            f"revalidation_trigger key(s) {unsupported_trigger} are not measured by this "
            f"module; supported: {list(SUPPORTED_TRIGGER_KEYS)}")

    if known_components is not None:
        key = known_component_key(record.get("ecosystem"), record.get("component"))
        if key not in known_components:
            raise DependencyQualificationError(
                f"VETTING_TARGET_NOT_IN_INVENTORY: {record.get('ecosystem')}/"
                f"{record.get('component')} does not appear in the supplied real "
                "dependency_supply_chain inventory -- qualifying a component nobody has "
                "shown this project depends on would record a decision about a phantom fact")

    records = read_qualifications(root)
    if any(r.get("qualification_id") == record["qualification_id"] for r in records):
        raise DependencyQualificationError(
            f"qualification_id already recorded: {record['qualification_id']}")
    record["schema_version"] = SCHEMA_VERSION
    record["recorded_at"] = time.time()
    records.append(record)
    _write_qualifications(root, records)
    return record


def revoke_qualification(root, qualification_id: str, revoked_by: str, reason: str) -> Dict[str, Any]:
    """Mark one recorded qualification REVOKED. A revocation is a human act
    and is recorded as one -- `revoked_by` and `reason` are required, the same
    discipline `waiver_store.revoke_waiver()` and `loop_budget.reset()` apply
    to clearing a prior decision/spend."""
    if not revoked_by or not reason:
        raise DependencyQualificationError("revoking a qualification requires both revoked_by and a reason")
    records = read_qualifications(root)
    for r in records:
        if r.get("qualification_id") == qualification_id:
            r["revoked"] = True
            r["revoked_by"] = revoked_by
            r["revoked_reason"] = reason
            r["revoked_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
            _write_qualifications(root, records)
            return r
    raise DependencyQualificationError(f"no qualification recorded with qualification_id={qualification_id!r}")


# --------------------------------------------------------------------------
# Status derivation. Never stored; always recomputed.
# --------------------------------------------------------------------------

def parse_timestamp(value: Any) -> Optional[_dt.datetime]:
    """Same ISO-8601 handling as `waiver_store.parse_timestamp()`, restated
    here rather than imported -- this module deliberately shares no state with
    the waiver ledger, a different governance domain recorded under a
    different store path."""
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def derive_status(record: Mapping[str, Any], *, now: Any = None,
                  current_version: Any = None) -> Tuple[str, str]:
    """This module's five-plus-two-value status, DERIVED from the record's own
    content plus the caller's real current facts (the version this project's
    inventory currently pins/installs for this component). Never trusted from
    a stored field.

    Worst-first, mirroring `waiver_store.derive_status()`'s own precedence
    reasoning (a human revocation outranks the clock; an uncheckable record is
    never presented as a good one):
      REVOKED -> UNKNOWN (uncheckable) -> REJECTED -> EXPIRED ->
      REVALIDATION_REQUIRED -> CONDITIONALLY_VETTED -> VETTED
    """
    if not isinstance(record, Mapping):
        return STATUS_UNKNOWN, "QUALIFICATION_RECORD_NOT_A_MAPPING"
    if record.get("revoked") is True:
        return STATUS_REVOKED, "REVOKED_BY:" + str(record.get("revoked_by") or "UNRECORDED")
    missing = [f for f in CANONICAL_REQUIRED_FIELDS if not record.get(f)]
    if missing:
        return STATUS_UNKNOWN, "MISSING_REQUIRED_FIELDS:" + ",".join(missing)
    decision = record.get("decision")
    if decision not in DECISIONS:
        return STATUS_UNKNOWN, f"UNRECOGNIZED_DECISION:{decision}"
    if decision == DECISION_REJECTED:
        return STATUS_REJECTED, "DECISION_REJECTED"

    expires_at = record.get("expires_at")
    if expires_at:
        expiry = parse_timestamp(expires_at)
        if expiry is None:
            return STATUS_UNKNOWN, f"UNPARSEABLE_EXPIRES_AT:{expires_at}"
        reference = parse_timestamp(now)
        if now is not None and reference is None:
            return STATUS_UNKNOWN, f"UNPARSEABLE_CURRENT_TIME:{now}"
        if reference is not None and reference > expiry:
            return STATUS_EXPIRED, f"EXPIRED_AT:{expires_at}"

    trigger = record.get("revalidation_trigger") or {}
    revalidated_for = record.get("revalidated_for") or {}
    if "version" in trigger and current_version not in (None, ""):
        qualified_version = record.get("version_qualified")
        if str(current_version) != str(qualified_version) and \
           str(revalidated_for.get("version", "")) != str(current_version):
            return STATUS_REVALIDATION_REQUIRED, (
                f"VERSION_CHANGED:{qualified_version}->{current_version}")

    if decision == DECISION_CONDITIONAL:
        return STATUS_CONDITIONALLY_VETTED, "DECISION_CONDITIONAL"
    return STATUS_VETTED, "DECISION_APPROVED_AND_CURRENT"


# --------------------------------------------------------------------------
# Reading: per-component lookup and the whole-inventory coverage rollup.
# --------------------------------------------------------------------------

def qualifications_for_component(root, ecosystem: str, component: str) -> List[Dict[str, Any]]:
    key = known_component_key(ecosystem, component)
    return [r for r in read_qualifications(root)
            if known_component_key(r.get("ecosystem"), r.get("component")) == key]


def _latest_qualification(records: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """When more than one qualification record targets one component, the
    most recently VETTED-BY-A-HUMAN record is the one that speaks for it -- a
    later re-vetting supersedes an earlier decision, the same "current human
    decision wins" reasoning `waiver_store`'s revalidation already applies.
    Ties (or an unparseable `vetted_at`) fall back to recording order."""
    if not records:
        return None
    def sort_key(r):
        parsed = parse_timestamp(r.get("vetted_at"))
        return (parsed or _dt.datetime.min.replace(tzinfo=_dt.timezone.utc),)
    return sorted(records, key=sort_key)[-1]


def evaluate_qualification_coverage(root, inventory: Mapping[str, Any],
                                    now: Any = None) -> Dict[str, Any]:
    """The join between `dependency_supply_chain.py`'s real inventory and this
    module's own ledger: for every real declared component, is there a
    qualification decision on file, and does it still hold. Reading is not a
    mutating act -- nothing here writes, and a project with no ledger reports
    every component NOT_QUALIFIED rather than having a ledger created for it.

    Worst-wins over the whole inventory: a single component left
    NOT_QUALIFIED/REJECTED/EXPIRED/REVOKED/UNKNOWN/REVALIDATION_REQUIRED makes
    the WHOLE report QUALIFICATION_GAPS_FOUND, never averaged against however
    many other components are cleanly vetted.
    """
    components = (inventory or {}).get("components")
    if not components:
        return {"status": REPORT_NOT_AVAILABLE,
                "reason": "EMPTY_OR_MISSING_INVENTORY", "rows": []}
    all_records = read_qualifications(root)
    rows: List[Dict[str, Any]] = []
    for component in components:
        ecosystem = component.get("ecosystem")
        name = component.get("name")
        if not name:
            continue
        matches = [r for r in all_records
                   if known_component_key(r.get("ecosystem"), r.get("component")) ==
                   known_component_key(ecosystem, name)]
        latest = _latest_qualification(matches)
        current_version = (component.get("installed") or {}).get("installed_version") \
            or component.get("specifier")
        if latest is None:
            rows.append({
                "ecosystem": ecosystem, "component": name,
                "current_version": current_version,
                "status": COVERAGE_NOT_QUALIFIED,
                "reason": "NO_QUALIFICATION_RECORD_ON_FILE",
                "qualification_id": None,
            })
            continue
        status, reason = derive_status(latest, now=now, current_version=current_version)
        rows.append({
            "ecosystem": ecosystem, "component": name,
            "current_version": current_version,
            "status": status, "reason": reason,
            "qualification_id": latest.get("qualification_id"),
            "vetted_by": latest.get("vetted_by"),
            "vetted_at": latest.get("vetted_at"),
            "decision": latest.get("decision"),
        })
    blocking = [r for r in rows if r["status"] in _BLOCKING_COVERAGE_STATUSES]
    return {
        "status": REPORT_ALL_QUALIFIED if not blocking else REPORT_GAPS_FOUND,
        "component_count": len(rows),
        "gap_count": len(blocking),
        "rows": rows,
    }


# --------------------------------------------------------------------------
# Front door.
# --------------------------------------------------------------------------

_EXIT_BY_REPORT_STATUS = {
    REPORT_ALL_QUALIFIED: 0,
    REPORT_GAPS_FOUND: 1,
    REPORT_NOT_AVAILABLE: 2,
}


def execute_verb(argv: Sequence[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.dependency_qualification",
        description="The QUALIFICATION record for a dependency/VIP/third-party component: "
                    "has it been vetted, by whom, against what criteria -- distinct from "
                    "dependency_supply_chain.py's inventory/pinning/advisory checks. "
                    "Reads only unless `record`/`revoke` is invoked.")
    ap.add_argument("verb", choices=("statuses", "list", "coverage", "record", "revoke"))
    ap.add_argument("--root", default=".")
    ap.add_argument("--inventory", default=None,
                    help="Path to a JSON dump of dependency_supply_chain.build_inventory() "
                         "(required for `coverage`).")
    ap.add_argument("--record-file", default=None,
                    help="Path to a JSON qualification record (required for `record`).")
    ap.add_argument("--qualification-id", default=None, help="Required for `revoke`.")
    ap.add_argument("--revoked-by", default=None, help="Required for `revoke`.")
    ap.add_argument("--reason", default=None, help="Required for `revoke`.")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(list(argv))
    root = Path(a.root).resolve()

    if a.verb == "statuses":
        payload = {"statuses": list(QUALIFICATION_STATUSES), "decisions": list(DECISIONS),
                   "criteria": list(QUALIFICATION_CRITERIA),
                   "supported_trigger_keys": list(SUPPORTED_TRIGGER_KEYS)}
        print(json.dumps(payload, indent=2))
        return 0

    if a.verb == "list":
        print(json.dumps(read_qualifications(root), indent=2))
        return 0

    if a.verb == "record":
        if not a.record_file:
            print("record requires --record-file")
            return 2
        record = json.loads(Path(a.record_file).read_text(encoding="utf-8"))
        known = None
        if a.inventory:
            inventory = json.loads(Path(a.inventory).read_text(encoding="utf-8"))
            known = known_components_from_inventory(inventory)
        try:
            saved = record_qualification(root, record, known_components=known)
        except DependencyQualificationError as e:
            print(f"{type(e).__name__}: {e}")
            return 2
        print(json.dumps(saved, indent=2))
        return 0

    if a.verb == "revoke":
        if not (a.qualification_id and a.revoked_by and a.reason):
            print("revoke requires --qualification-id, --revoked-by, and --reason")
            return 2
        try:
            revoked = revoke_qualification(root, a.qualification_id, a.revoked_by, a.reason)
        except DependencyQualificationError as e:
            print(f"{type(e).__name__}: {e}")
            return 2
        print(json.dumps(revoked, indent=2))
        return 0

    # coverage
    if not a.inventory:
        print("coverage requires --inventory <dependency_supply_chain build_inventory() JSON>")
        return 2
    inventory = json.loads(Path(a.inventory).read_text(encoding="utf-8"))
    report = evaluate_qualification_coverage(root, inventory)
    print(json.dumps(report, indent=2))
    return _EXIT_BY_REPORT_STATUS.get(report["status"], 2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys
    return execute_verb(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
