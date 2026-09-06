"""dv_harness/intake_state.py -- one IntakeState per-field record joining
env.manifest.json facts, question_queue decisions and connectivity bind
tiers, plus a UVM_GENERATION_READY refusal gate and a do-not-ask helper.

Reuse, not reinvention. Every fact this module folds together already has a
real producer elsewhere in this codebase; this module never re-derives a
fact, it only reads three existing sources and joins them field-by-field:

  - `env_manifest.py`'s 3-layer env.manifest.json (`dut_facts`/`vip_config`/
    `env_topology`) -- each layer's own `status`/`reason` is read verbatim,
    exactly as the `env_manifest` Blackboard topic already does (see
    CLAUDE.md's "Blackboard Topics Written Outside the Graph"). A layer's
    self-reported `disagreement_count` (`dut_facts.address_map`) or
    `summary.broken_count` (`env_topology.testplan_correspondence`) is read
    as a real CONTRADICTED signal rather than re-computed here.
  - `question_queue.py`'s `QuestionQueueStore.find_decision()` (the ONLY
    public read this module calls on that store -- it never writes a
    question or a decision, per this task's own scope) plus its two real
    decision-source constants, `HUMAN_DECISION_SOURCE` ("human_answer") and
    `TIER2_AUTO_ASSUMPTION_SOURCE`, which map directly onto this module's
    USER_CONFIRMED / AUTO_RESOLVED status split -- a human answer always
    outranks the harness's own Tier-2 guess, and a Tier-2 guess never
    downgrades a fact this module already computed from a real source.
  - `connectivity.py`'s `BindTier` / `AUTO_EMITTABLE_TIERS` vocabulary for
    per-bind-entry status: T1/T2 (auto-emittable) resolve; T3 resolves only
    with a real human confirmation carrying `question_queue.
    HUMAN_DECISION_SOURCE` (the same check `connectivity.
    assert_bind_entry_tier_allows_emission()` performs before emission,
    re-read here rather than re-implemented since this module only REPORTS,
    it never emits a `bind` statement); T4 is always BLOCKED.

Duck-typed inputs for the rest, and why (Rule 3 of this batch's scope: never
import from another module created in this or the concurrently-running
batch). Three of the six UVM_GENERATION_READY blocking categories have a
real, richer producer elsewhere in this codebase that this module
deliberately does NOT import, because doing so would either violate that
scope rule or reach into a module concurrently being edited by the other
batch:
  - `dut_boundary` accepts the exact dict shape `phy_boundary.
    extract_phy_boundary()` / `load_phy_boundary()` already produces
    (`status`, `bind_decision.bindable`, `bind_decision.mount_layer`,
    `bind_decision.rationale`) -- shape-compatible so a caller can hand this
    module that real function's output directly, without this module
    importing `phy_boundary` itself.
  - `active_driver_conflicts` accepts a generic list of
    `{"resource", "status", "reason"}` dicts. The real producer would be
    `system_resource_inventory.real_cross_subsystem_findings()`'s
    cross-subsystem ownership analysis (CLAUDE.md's "SYSTEM_LEVEL verdict
    now stands on the REAL cross-subsystem analysis"); a caller who has run
    that analysis flattens its findings into this shape.
  - `known_pass_tests` accepts a generic list of `{"test_name", "verdict",
    "reason"}` dicts. The real producer would be `golden_scenario.py`'s
    recorded capsules -- NOT imported here because `golden_scenario.py` is
    one of the four files a separate, concurrently-running 12-agent batch is
    editing right now (this task's own instructions name it explicitly).

`build_env` accepts either a real `connectivity.GateResult` (from
`run_gate1_elaboration_check()`) or an equivalent dict -- `connectivity.py`
itself is NOT one of the concurrently-edited files, so it is imported
directly for its `GateStatus`/`BindTier` vocabulary.

Status vocabulary (per this task): AUTO_RESOLVED (a real, non-human source
resolved it -- an env.manifest.json fact, a T1/T2 bind, a Tier-2
auto-assumption, an empty conflict/known-pass list a caller explicitly
checked), USER_CONFIRMED (a real human decision on file, via
`question_queue.HUMAN_DECISION_SOURCE` or a T3 bind's
`human_confirmation`), PARTIAL (some but not all sub-evidence resolved),
CONTRADICTED (two real sources disagree -- a `disagreement_count`/
`broken_count` the layer itself reports, or a question_queue answer that
disagrees with a computed value), MISSING (no evidence was supplied at
all), BLOCKED (real evidence says this field cannot proceed -- a T3-without-
confirmation or T4 bind, a FAILed Gate-1, a reported active-driver
conflict), UNKNOWN (evidence was supplied but is inconclusive -- an
unrecognized tier, a NOT_AVAILABLE/PENDING/NOT_YET_RUN gate), NOT_APPLICABLE
(reserved for a caller-declared "this field does not apply to this
project"; nothing in this module infers it automatically -- inferring
"not applicable" from mere absence is exactly the silent-default the
Evidence Truth Rule forbids).

Deliberately bounded, and stated rather than implied closed: this module
JOINS and REPORTS. It files no question (`already_resolved()` is a
do-not-ask lookup a caller consults BEFORE calling `question_queue.
QuestionQueueStore.add_question()` -- it never calls that method itself),
runs no gate script, writes no state/blackboard/approval record, and holds
no stage gate of its own. `evaluate_uvm_generation_ready()` only refuses or
allows continuing to the next human/agent action; it starts no generation
and approves nothing.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field as _dc_field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from . import connectivity
from . import question_queue
from .inference import CONFIDENCE_LEVELS

SCHEMA_VERSION = "1.0"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- status vocabulary -----------------------------------------------------

class IntakeFieldStatus(str, Enum):
    AUTO_RESOLVED = "AUTO_RESOLVED"
    USER_CONFIRMED = "USER_CONFIRMED"
    PARTIAL = "PARTIAL"
    CONTRADICTED = "CONTRADICTED"
    MISSING = "MISSING"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: Statuses that do NOT block `evaluate_uvm_generation_ready()` and that DO
#: count as "already resolved, do not ask again" for `already_resolved()`.
RESOLVED_STATUSES = frozenset({
    IntakeFieldStatus.AUTO_RESOLVED.value,
    IntakeFieldStatus.USER_CONFIRMED.value,
})

#: NOT_APPLICABLE additionally never blocks generation (a caller declared the
#: field out of scope for this project) but is deliberately NOT a "do not
#: ask again" status for already_resolved() -- "does not apply" and
#: "resolved" are different claims and only the second licenses skipping a
#: future ask about the SAME field in a DIFFERENT context.
NON_BLOCKING_STATUSES = RESOLVED_STATUSES | {IntakeFieldStatus.NOT_APPLICABLE.value}

#: Worst-wins fold order for `IntakeState.category_status()`, most severe
#: first -- the same "worst wins" convention `signoff_export.py`'s freeze
#: invalidation and `golden_flow_readiness.py`'s status fold already use in
#: this codebase.
STATUS_SEVERITY = [
    IntakeFieldStatus.BLOCKED.value,
    IntakeFieldStatus.CONTRADICTED.value,
    IntakeFieldStatus.MISSING.value,
    IntakeFieldStatus.UNKNOWN.value,
    IntakeFieldStatus.PARTIAL.value,
    IntakeFieldStatus.AUTO_RESOLVED.value,
    IntakeFieldStatus.USER_CONFIRMED.value,
    IntakeFieldStatus.NOT_APPLICABLE.value,
]
_SEVERITY_RANK = {s: i for i, s in enumerate(STATUS_SEVERITY)}

#: confidence vocabulary: `inference.CONFIDENCE_LEVELS` (HIGH/MEDIUM/LOW),
#: imported rather than re-typed, plus UNKNOWN for "no basis to judge" --
#: the same "CONFIDENCE_LEVELS plus UNKNOWN" convention
#: `requirement_contract.py` already established.
CONFIDENCE_VOCAB = frozenset(CONFIDENCE_LEVELS) | {"UNKNOWN"}

#: The six blocking categories this task names, in the order named:
#: "DUT boundary, VIP unresolved, active-driver conflict, critical bind,
#: build env, known-PASS test".
BLOCKING_CATEGORIES = (
    "dut_boundary",
    "vip_resolution",
    "active_driver_conflict",
    "critical_bind",
    "build_env",
    "known_pass_test",
)


@dataclass
class IntakeFieldRecord:
    """One per-field intake record: `{value, source, confidence, status,
    last_validated, owner}` plus the `field`/`category` keys that name it
    and a `reason` carrying the real evidence text."""
    field: str
    category: str
    value: Any
    source: str
    confidence: str
    status: str
    last_validated: Optional[str] = None
    owner: Optional[str] = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in {s.value for s in IntakeFieldStatus}:
            raise ValueError(f"unknown IntakeFieldStatus {self.status!r} for field {self.field!r}")
        if self.confidence not in CONFIDENCE_VOCAB:
            raise ValueError(f"unknown confidence {self.confidence!r} for field {self.field!r}; "
                              f"must be one of {sorted(CONFIDENCE_VOCAB)}")

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "category": self.category,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "status": self.status,
            "last_validated": self.last_validated,
            "owner": self.owner,
            "reason": self.reason,
        }


class IntakeState:
    """One project's joined intake: every `IntakeFieldRecord` this run
    produced, keyed by field name."""

    def __init__(self, records: Sequence[IntakeFieldRecord], *, generated_at: Optional[str] = None):
        self.records: List[IntakeFieldRecord] = list(records)
        self.generated_at = generated_at or _utcnow_iso()
        self._by_field: Dict[str, IntakeFieldRecord] = {}
        for r in self.records:
            # Field names are constructed by this module's own builders and
            # are unique by construction (bind/conflict entries are suffixed
            # by their real target/resource name); a collision is a defect
            # in the caller's input, not something to silently overwrite.
            if r.field in self._by_field:
                raise ValueError(f"duplicate IntakeFieldRecord field name {r.field!r}")
            self._by_field[r.field] = r

    def get(self, field_name: str) -> Optional[IntakeFieldRecord]:
        return self._by_field.get(field_name)

    def fields_in_category(self, category: str) -> List[IntakeFieldRecord]:
        return [r for r in self.records if r.category == category]

    def category_status(self, category: str) -> str:
        """Worst-wins fold of every field recorded under `category`. A
        category with NO fields recorded at all reports MISSING -- never
        "ready by omission"; a category this run never evaluated must read
        the same as a category it evaluated and found nothing for."""
        rows = self.fields_in_category(category)
        if not rows:
            return IntakeFieldStatus.MISSING.value
        worst = rows[0].status
        for r in rows[1:]:
            if _SEVERITY_RANK[r.status] < _SEVERITY_RANK[worst]:
                worst = r.status
        return worst

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "fields": [r.to_dict() for r in self.records],
        }


def already_resolved(intake_state: IntakeState, field_name: str) -> bool:
    """Do-not-ask helper. A caller about to file a NEW question through
    `question_queue.QuestionQueueStore.add_question()` should call this
    FIRST -- this module never files a question itself (see module
    docstring), it only reports whether `IntakeState` already carries a
    resolution good enough to skip asking again.

    Returns True only for AUTO_RESOLVED / USER_CONFIRMED. A field this state
    never saw at all, or one recorded MISSING/UNKNOWN/PARTIAL/CONTRADICTED/
    BLOCKED/NOT_APPLICABLE, all return False -- "we do not know" and
    "not applicable here" must never read as "already asked and answered"."""
    rec = intake_state.get(field_name)
    return rec is not None and rec.status in RESOLVED_STATUSES


@dataclass
class UvmGenerationReadiness:
    ready: bool
    blocking: Dict[str, dict]
    checked_at: str

    def to_dict(self) -> dict:
        return {"ready": self.ready, "blocking": self.blocking, "checked_at": self.checked_at}


def evaluate_uvm_generation_ready(intake_state: IntakeState, *, now: Optional[str] = None) -> UvmGenerationReadiness:
    """UVM_GENERATION_READY: refuses (never silently proceeds) while ANY of
    `BLOCKING_CATEGORIES` -- DUT boundary, VIP unresolved, active-driver
    conflict, critical bind, build env, known-PASS test -- is unresolved.

    A category with no fields recorded at all is folded to MISSING by
    `IntakeState.category_status()` and therefore blocks here too: a
    category this run never evaluated must never read as ready."""
    blocking: Dict[str, dict] = {}
    for category in BLOCKING_CATEGORIES:
        status = intake_state.category_status(category)
        if status not in NON_BLOCKING_STATUSES:
            blocking[category] = {
                "status": status,
                "fields": [r.to_dict() for r in intake_state.fields_in_category(category)],
            }
    return UvmGenerationReadiness(ready=not blocking, blocking=blocking, checked_at=now or _utcnow_iso())


# ---- env_manifest joining ----------------------------------------------------

def _get_layer(env_manifest: Optional[dict], path: Sequence[str]) -> Optional[dict]:
    node: Any = env_manifest
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, dict) else None


def _dig(doc: dict, dotted_key: str) -> Any:
    node: Any = doc
    for part in dotted_key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _field_from_env_manifest_layer(
    field_name: str, category: str, layer: Optional[dict], *,
    source_path: str, owner: Optional[str] = None, contradiction_key: Optional[str] = None,
) -> IntakeFieldRecord:
    source = f"env_manifest:{source_path}"
    if layer is None:
        return IntakeFieldRecord(
            field=field_name, category=category, value=None, source=source,
            confidence="UNKNOWN", status=IntakeFieldStatus.MISSING.value, owner=owner,
            reason=f"{source_path} layer not present in the supplied env.manifest.json",
        )
    status_raw = layer.get("status")
    reason = layer.get("reason") or ""
    if status_raw is None or status_raw == "NOT_AVAILABLE":
        return IntakeFieldRecord(
            field=field_name, category=category, value=None, source=source,
            confidence="UNKNOWN", status=IntakeFieldStatus.MISSING.value, owner=owner,
            reason=reason or f"{source_path} reports NOT_AVAILABLE",
        )
    if contradiction_key:
        count = _dig(layer, contradiction_key)
        if isinstance(count, int) and count > 0:
            return IntakeFieldRecord(
                field=field_name, category=category, value=status_raw, source=source,
                confidence="HIGH", status=IntakeFieldStatus.CONTRADICTED.value, owner=owner,
                reason=f"{source_path}.{contradiction_key}={count} disagreement(s) recorded by "
                       f"the real producer",
            )
    return IntakeFieldRecord(
        field=field_name, category=category, value=status_raw, source=source,
        confidence="HIGH", status=IntakeFieldStatus.AUTO_RESOLVED.value, owner=owner, reason=reason,
    )


# ---- connectivity bind-tier joining (critical_bind) -------------------------

def _field_from_bind_entry(entry: dict) -> IntakeFieldRecord:
    target = entry.get("target_instance") or entry.get("target") or "?"
    field_name = f"bind:{target}"
    source = "connectivity:bind_entries"
    raw_tier = entry.get("tier")
    if raw_tier is None or raw_tier == "":
        return IntakeFieldRecord(
            field=field_name, category="critical_bind", value=None, source=source,
            confidence="UNKNOWN", status=IntakeFieldStatus.UNKNOWN.value,
            reason="bind entry carries no tier -- never run through connectivity.classify_bind_tier()",
        )
    value = raw_tier.value if isinstance(raw_tier, connectivity.BindTier) else str(raw_tier)
    try:
        tier = connectivity.BindTier(value)
    except ValueError:
        return IntakeFieldRecord(
            field=field_name, category="critical_bind", value=value, source=source,
            confidence="UNKNOWN", status=IntakeFieldStatus.UNKNOWN.value,
            reason=f"unrecognized bind tier {value!r}",
        )
    if tier in connectivity.AUTO_EMITTABLE_TIERS:
        return IntakeFieldRecord(
            field=field_name, category="critical_bind", value=tier.value, source=source,
            confidence="HIGH", status=IntakeFieldStatus.AUTO_RESOLVED.value,
            reason="auto-emittable tier (T1 already-decided / T2 structural match)",
        )
    if tier is connectivity.BindTier.T3_NAMING_HEURISTIC:
        conf = entry.get("human_confirmation")
        confirmed = (
            isinstance(conf, dict)
            and conf.get("source") == question_queue.HUMAN_DECISION_SOURCE
            and bool(conf.get("confirmed_by"))
            and bool(conf.get("basis"))
        )
        if confirmed:
            return IntakeFieldRecord(
                field=field_name, category="critical_bind", value=tier.value, source=source,
                confidence="HIGH", status=IntakeFieldStatus.USER_CONFIRMED.value,
                owner=conf.get("confirmed_by"),
                reason=f"T3 naming-heuristic bind with a real human confirmation on file: {conf.get('basis')}",
            )
        return IntakeFieldRecord(
            field=field_name, category="critical_bind", value=tier.value, source=source,
            confidence="LOW", status=IntakeFieldStatus.BLOCKED.value,
            reason="T3 naming-heuristic bind ALWAYS requires human confirmation -- none on file",
        )
    # T4_UNDECIDABLE
    return IntakeFieldRecord(
        field=field_name, category="critical_bind", value=tier.value, source=source,
        confidence="LOW", status=IntakeFieldStatus.BLOCKED.value,
        reason="T4 undecidable -- belongs in the question queue, never emitted",
    )


def _fields_from_bind_entries(bind_entries: Optional[List[dict]]) -> List[IntakeFieldRecord]:
    if bind_entries is None:
        return [IntakeFieldRecord(
            field="critical_bind", category="critical_bind", value=None,
            source="connectivity:bind_entries", confidence="UNKNOWN",
            status=IntakeFieldStatus.MISSING.value,
            reason="no bind entries supplied -- nothing run through connectivity.classify_bind_tier()",
        )]
    if not bind_entries:
        return [IntakeFieldRecord(
            field="critical_bind", category="critical_bind", value=[],
            source="connectivity:bind_entries", confidence="UNKNOWN",
            status=IntakeFieldStatus.MISSING.value,
            reason="bind entries list supplied but empty -- no bind target classified yet",
        )]
    return [_field_from_bind_entry(e) for e in bind_entries]


# ---- DUT boundary (phy_boundary.py-shaped, not imported) --------------------

def _field_from_dut_boundary(doc: Optional[dict]) -> IntakeFieldRecord:
    field_name = "dut_boundary"
    source = "phy_boundary"
    if doc is None:
        return IntakeFieldRecord(
            field=field_name, category="dut_boundary", value=None, source=source,
            confidence="UNKNOWN", status=IntakeFieldStatus.MISSING.value,
            reason="no phy_boundary.json-shaped decision supplied",
        )
    status = doc.get("status")
    bind_decision = doc.get("bind_decision") or {}
    bindable = bind_decision.get("bindable")
    mount_layer = bind_decision.get("mount_layer")
    reason = bind_decision.get("rationale") or doc.get("reason") or ""
    if status == "NOT_AVAILABLE" or bindable is None:
        return IntakeFieldRecord(
            field=field_name, category="dut_boundary", value=mount_layer, source=source,
            confidence="UNKNOWN", status=IntakeFieldStatus.MISSING.value,
            reason=reason or "NOT_AVAILABLE",
        )
    if bindable:
        return IntakeFieldRecord(
            field=field_name, category="dut_boundary", value=mount_layer, source=source,
            confidence="HIGH", status=IntakeFieldStatus.AUTO_RESOLVED.value, reason=reason,
        )
    return IntakeFieldRecord(
        field=field_name, category="dut_boundary", value=mount_layer, source=source,
        confidence="LOW", status=IntakeFieldStatus.BLOCKED.value, reason=reason,
    )


# ---- active-driver conflicts (generic duck-typed list) ----------------------

_ACTIVE_CONFLICT_STATUSES = frozenset({
    "BLOCKED", "CONFLICT", "ACTIVE_DRIVER_CONFLICT", "UNRESOLVED",
})


def _fields_from_active_driver_conflicts(conflicts: Optional[List[dict]]) -> List[IntakeFieldRecord]:
    source = "caller:active_driver_conflicts"
    real_source_note = (
        " (intended real source: system_resource_inventory.real_cross_subsystem_findings(), "
        "not imported here -- see module docstring)"
    )
    if conflicts is None:
        return [IntakeFieldRecord(
            field="active_driver_conflicts", category="active_driver_conflict", value=None,
            source=source, confidence="UNKNOWN", status=IntakeFieldStatus.MISSING.value,
            reason="no cross-subsystem driver-ownership findings supplied" + real_source_note,
        )]
    if not conflicts:
        return [IntakeFieldRecord(
            field="active_driver_conflicts", category="active_driver_conflict", value=[],
            source=source, confidence="HIGH", status=IntakeFieldStatus.AUTO_RESOLVED.value,
            reason="cross-subsystem findings supplied and empty -- no active-driver conflict reported",
        )]
    records = []
    for i, c in enumerate(conflicts):
        resource = c.get("resource") or f"resource_{i}"
        status_raw = str(c.get("status") or "").strip().upper()
        blocked = status_raw in _ACTIVE_CONFLICT_STATUSES
        if not status_raw:
            status = IntakeFieldStatus.UNKNOWN.value
            confidence = "UNKNOWN"
        elif blocked:
            status = IntakeFieldStatus.BLOCKED.value
            confidence = "HIGH"
        else:
            status = IntakeFieldStatus.AUTO_RESOLVED.value
            confidence = "HIGH"
        records.append(IntakeFieldRecord(
            field=f"active_driver_conflict:{resource}", category="active_driver_conflict",
            value=status_raw or None, source=source, confidence=confidence, status=status,
            reason=c.get("reason") or "",
        ))
    return records


# ---- build env (connectivity Gate 1 elaboration) -----------------------------

def _field_from_build_env_gate(gate_result: Any) -> IntakeFieldRecord:
    field_name = "build_env"
    source = "connectivity:gate1_elaboration"
    if gate_result is None:
        return IntakeFieldRecord(
            field=field_name, category="build_env", value=None, source=source,
            confidence="UNKNOWN", status=IntakeFieldStatus.MISSING.value,
            reason="no Gate-1 elaboration result supplied "
                   "(real source: connectivity.run_gate1_elaboration_check())",
        )
    if isinstance(gate_result, connectivity.GateResult):
        status_raw = gate_result.status
        detail = gate_result.detail or {}
    elif isinstance(gate_result, dict):
        status_raw = gate_result.get("status")
        detail = gate_result.get("detail") or {}
    else:
        return IntakeFieldRecord(
            field=field_name, category="build_env", value=None, source=source,
            confidence="UNKNOWN", status=IntakeFieldStatus.UNKNOWN.value,
            reason=f"unrecognized gate-1 result shape {type(gate_result).__name__}",
        )
    status_val = status_raw.value if isinstance(status_raw, connectivity.GateStatus) else str(status_raw)
    reason = (detail.get("reason") if isinstance(detail, dict) else None) or ""
    if status_val == connectivity.GateStatus.PASS.value:
        return IntakeFieldRecord(
            field=field_name, category="build_env", value=status_val, source=source,
            confidence="HIGH", status=IntakeFieldStatus.AUTO_RESOLVED.value, reason=reason,
        )
    if status_val == connectivity.GateStatus.FAIL.value:
        return IntakeFieldRecord(
            field=field_name, category="build_env", value=status_val, source=source,
            confidence="HIGH", status=IntakeFieldStatus.BLOCKED.value, reason=reason,
        )
    # NOT_AVAILABLE / PENDING / NOT_YET_RUN / any unrecognized string
    return IntakeFieldRecord(
        field=field_name, category="build_env", value=status_val, source=source,
        confidence="UNKNOWN", status=IntakeFieldStatus.UNKNOWN.value,
        reason=reason or f"gate-1 status is {status_val} -- not yet a PASS/FAIL verdict",
    )


# ---- known-PASS test (generic duck-typed list; golden_scenario not imported) -

_PASS_LIKE_VERDICTS = frozenset({"PASS", "PASSED"})


def _field_from_known_pass_tests(tests: Optional[List[dict]]) -> IntakeFieldRecord:
    field_name = "known_pass_tests"
    source = "caller:known_pass_tests"
    real_source_note = (
        " (intended real source: golden_scenario.py's recorded capsules -- NOT imported here "
        "because golden_scenario.py is concurrently edited by a separate batch; see module docstring)"
    )
    if tests is None:
        return IntakeFieldRecord(
            field=field_name, category="known_pass_test", value=None, source=source,
            confidence="UNKNOWN", status=IntakeFieldStatus.MISSING.value,
            reason="no known-PASS test evidence supplied" + real_source_note,
        )
    if not tests:
        return IntakeFieldRecord(
            field=field_name, category="known_pass_test", value=[], source=source,
            confidence="HIGH", status=IntakeFieldStatus.MISSING.value,
            reason="known-PASS test list supplied but empty -- no test has ever reached PASS "
                   "for this environment",
        )
    passing = [t.get("test_name") for t in tests if str(t.get("verdict") or "").strip().upper()
               in _PASS_LIKE_VERDICTS]
    if passing:
        return IntakeFieldRecord(
            field=field_name, category="known_pass_test", value=passing, source=source,
            confidence="HIGH", status=IntakeFieldStatus.AUTO_RESOLVED.value,
            reason=f"{len(passing)} of {len(tests)} supplied test(s) recorded a real PASS verdict",
        )
    any_verdict = any(str(t.get("verdict") or "").strip() for t in tests)
    return IntakeFieldRecord(
        field=field_name, category="known_pass_test", value=None, source=source,
        confidence="HIGH" if any_verdict else "UNKNOWN",
        status=IntakeFieldStatus.PARTIAL.value if any_verdict else IntakeFieldStatus.UNKNOWN.value,
        reason="no supplied test reached a PASS verdict",
    )


# ---- question_queue decision overlay -----------------------------------------

def _apply_decision_overlay(record: IntakeFieldRecord, decision: Optional[dict]) -> IntakeFieldRecord:
    """Overlays one `question_queue.QuestionQueueStore.find_decision()`
    result onto an already-computed field record. Never called by this
    module for a field the caller did not name a `question_key` for (see
    `build_intake_state()`'s `field_question_keys`), and never itself calls
    `add_question()`/`answer_question()` -- purely a read overlay."""
    if not decision:
        return record
    current = decision.get("current") or {}
    source = current.get("source")
    if source not in (question_queue.HUMAN_DECISION_SOURCE, question_queue.TIER2_AUTO_ASSUMPTION_SOURCE):
        # An unrecognized decision source is not trusted to override anything
        # this module already computed from a real fact.
        return record

    answer = current.get("answer")
    decided_by = current.get("decided_by")
    decided_at = current.get("decided_at")
    is_human = source == question_queue.HUMAN_DECISION_SOURCE
    has_value = record.value not in (None, "", [])
    conflicts = has_value and answer is not None and str(answer).strip().lower() != str(record.value).strip().lower()

    if conflicts:
        return dataclasses.replace(
            record,
            status=IntakeFieldStatus.CONTRADICTED.value,
            confidence="HIGH" if is_human else record.confidence,
            last_validated=decided_at or record.last_validated,
            owner=decided_by or record.owner,
            reason=(f"question_queue decision ({source}) answered {answer!r}, disagreeing with "
                     f"the computed value {record.value!r}: {record.reason}").strip(": "),
        )

    if is_human:
        return dataclasses.replace(
            record,
            value=answer if answer is not None else record.value,
            status=IntakeFieldStatus.USER_CONFIRMED.value,
            confidence="HIGH",
            last_validated=decided_at or record.last_validated,
            owner=decided_by or record.owner,
            reason=(record.reason + "; " if record.reason else "")
                   + f"human-confirmed via question_queue ({decided_by})",
        )

    # Tier-2 auto-assumption: only strengthens a field this module could not
    # otherwise resolve. It never overrides a real fact already computed at
    # AUTO_RESOLVED/USER_CONFIRMED/BLOCKED/CONTRADICTED/PARTIAL from a higher-
    # authority source -- a harness guess is not entitled to that.
    if record.status in (IntakeFieldStatus.MISSING.value, IntakeFieldStatus.UNKNOWN.value):
        return dataclasses.replace(
            record,
            value=answer if answer is not None else record.value,
            status=IntakeFieldStatus.AUTO_RESOLVED.value,
            confidence="MEDIUM",
            last_validated=decided_at or record.last_validated,
            owner=decided_by or record.owner,
            reason=(record.reason + "; " if record.reason else "")
                   + "tier-2 auto-assumption on file (not a human answer)",
        )
    return record


# ---- top-level builder --------------------------------------------------------

def build_intake_state(
    *,
    env_manifest: Optional[dict] = None,
    question_store: Optional["question_queue.QuestionQueueStore"] = None,
    field_question_keys: Optional[Dict[str, str]] = None,
    bind_entries: Optional[List[dict]] = None,
    dut_boundary: Optional[dict] = None,
    active_driver_conflicts: Optional[List[dict]] = None,
    build_env_gate: Any = None,
    known_pass_tests: Optional[List[dict]] = None,
    now: Optional[str] = None,
) -> IntakeState:
    """Build one `IntakeState` joining:
      - `env_manifest` -- an `env_manifest.load_env_manifest()`-shaped dict
        (or `None`/`{}` for "no manifest").
      - `question_store` + `field_question_keys` -- a real
        `question_queue.QuestionQueueStore` and a `{field_name:
        question_key}` map naming which already-filed question, if any,
        answers each field. Only `find_decision()` (a read) is called.
      - `bind_entries` -- a list of connectivity bind-entry dicts (the same
        `target_instance`/`tier`/`human_confirmation` shape
        `connectivity.enforce_bind_tier_policy()` consumes).
      - `dut_boundary`, `active_driver_conflicts`, `known_pass_tests`,
        `build_env_gate` -- see module docstring for their shapes and why
        each is duck-typed rather than imported.

    Every argument is optional and independently absent-able: a caller with
    only an env.manifest.json and nothing else still gets a real, honest
    IntakeState (every other category reads MISSING, and
    `evaluate_uvm_generation_ready()` refuses naming them)."""
    records: List[IntakeFieldRecord] = []
    em = env_manifest or {}

    dut_owner = question_queue.route_owner("dut")
    vip_owner = question_queue.route_owner("vip")
    env_owner = question_queue.route_owner("env")

    records.append(_field_from_env_manifest_layer(
        "dut_rtl", "general", _get_layer(em, ("dut_facts", "rtl")),
        source_path="dut_facts.rtl", owner=dut_owner))
    records.append(_field_from_env_manifest_layer(
        "dut_registers", "general", _get_layer(em, ("dut_facts", "registers")),
        source_path="dut_facts.registers", owner=dut_owner))
    records.append(_field_from_env_manifest_layer(
        "dut_address_map", "general", _get_layer(em, ("dut_facts", "address_map")),
        source_path="dut_facts.address_map", owner=dut_owner, contradiction_key="disagreement_count"))
    records.append(_field_from_env_manifest_layer(
        "dut_clock_reset", "general", _get_layer(em, ("dut_facts", "clock_reset")),
        source_path="dut_facts.clock_reset", owner=dut_owner))
    records.append(_field_from_env_manifest_layer(
        "vip_release", "vip_resolution", _get_layer(em, ("vip_config", "vip_release")),
        source_path="vip_config.vip_release", owner=vip_owner))
    records.append(_field_from_env_manifest_layer(
        "vip_user_guide_refs", "general", _get_layer(em, ("vip_config", "user_guide_refs")),
        source_path="vip_config.user_guide_refs", owner=vip_owner))
    records.append(_field_from_env_manifest_layer(
        "component_hierarchy", "general", _get_layer(em, ("env_topology", "component_hierarchy")),
        source_path="env_topology.component_hierarchy", owner=env_owner))
    records.append(_field_from_env_manifest_layer(
        "config_db_trace", "general", _get_layer(em, ("env_topology", "config_db_trace")),
        source_path="env_topology.config_db_trace", owner=env_owner))
    records.append(_field_from_env_manifest_layer(
        "testplan_correspondence", "general", _get_layer(em, ("env_topology", "testplan_correspondence")),
        source_path="env_topology.testplan_correspondence", owner=env_owner,
        contradiction_key="summary.broken_count"))

    for r in _fields_from_bind_entries(bind_entries):
        records.append(r if r.owner else dataclasses.replace(r, owner=env_owner))

    db = _field_from_dut_boundary(dut_boundary)
    records.append(db if db.owner else dataclasses.replace(db, owner=dut_owner))

    for r in _fields_from_active_driver_conflicts(active_driver_conflicts):
        records.append(r if r.owner else dataclasses.replace(r, owner=env_owner))

    beg = _field_from_build_env_gate(build_env_gate)
    records.append(beg if beg.owner else dataclasses.replace(beg, owner=env_owner))

    kpt = _field_from_known_pass_tests(known_pass_tests)
    records.append(kpt if kpt.owner else dataclasses.replace(kpt, owner=env_owner))

    if question_store is not None and field_question_keys:
        overlaid = []
        for r in records:
            key = field_question_keys.get(r.field)
            decision = question_store.find_decision(key) if key else None
            overlaid.append(_apply_decision_overlay(r, decision))
        records = overlaid

    return IntakeState(records, generated_at=now)
