"""dv_harness/harness_status_ir.py -- HarnessStatusIR data model + Status Enum
Governance (Global Status Bar theme, CLAUDE_L5_GLOBAL_STATUS_BAR_MASTER.md
sections 404-406).

THE GAP THIS CLOSES
-------------------
Sections 403-433 require ONE canonical Global Status Bar, backed by one
canonical `HarnessStatusIR` data model, rendered identically by Claude CLI,
GUI and Web. A repo-wide grep for `HarnessStatusIR`/`HarnessStatusService`/
`GlobalStateAggregator` returned nothing before this file: the schema and its
governed status vocabulary did not exist anywhere, so no two of CLI/GUI/Web
could even in principle agree on what "the current Harness state" means.

WHAT THIS MODULE IS
--------------------
Exactly sections 404-406, nothing past them:

  * `HarnessStatusIR` -- the canonical dataclass, structured identically to
    section 405's own YAML (identity/baseline/harness/workflow/execution/
    closure/integration/blockers/resources/freshness/evidence), where every
    leaf carries a real citation of which existing module it must be READ
    from (never re-derived here).
  * `HarnessStatus` -- section 406's governed, closed status-enum vocabulary,
    shared across every status-bearing field in the IR, plus TOTAL bridges to
    every status vocabulary this project already has an opinion about
    (`models.Status`, `loop_contract.LoopState`, `subsystem_discovery`'s
    READY/PARTIAL/BLOCKED/UNKNOWN) so a future reader never has to invent a
    conversion of its own.

WHAT THIS MODULE IS NOT
------------------------
It is not the Global State Aggregator (section 409) and not the
HarnessStatusService (section 410) -- those assemble a REAL `HarnessStatusIR`
by reading the many real subsystems this file's own `FACT_SOURCE_CATALOG`
names, and neither is built here. This module reads no state.json, runs no
gate, submits no job, and mints no approval; it defines the shape evidence
must be poured into, and the vocabulary that shape is expressed in. Building
the aggregator here would duplicate section 409's own job and would let this
schema drift out of agreement with whatever the aggregator actually produces
-- the exact parallel-mechanism failure this project's Methodology
Consolidation Rule forbids.

WHY THE STATUS VOCABULARY IS BORROWED, NOT MINTED
---------------------------------------------------
Section 406 literally lists ten "core" states (READY/PARTIAL/RUNNING/
VERIFYING/BLOCKED/HUMAN_GATE/STALE/FAILED/SIGNOFF_READY/UNKNOWN) plus nine
"supporting" ones (IDLE/WAITING/CONVERGING/PLATEAU/OSCILLATING/RETRY_WAIT/
BUDGET_EXHAUSTED/CANCELLED/NOT_APPLICABLE) and says "do not invent
surface-specific synonyms". Thirteen of those nineteen words are, verbatim,
`loop_contract.LoopState` members (CREATED/READY/RUNNING/VERIFYING/
CONVERGING/PLATEAU/OSCILLATING/RETRY_WAIT/BLOCKED/HUMAN_GATE/FAILED/
BUDGET_EXHAUSTED/CANCELLED/STALE -- fourteen counting STALE) -- the Loop
Engineering canonical loop state machine this project already built and
tested (`dv_harness/loop_contract.py`). Rather than re-declaring a
fourteen-word-overlapping enum from scratch, `HarnessStatus` is declared once
here as the closed nineteen-word union section 406 itself names, and
`LOOP_STATE_TO_HARNESS_STATUS` is the one real, TOTAL bridge from
`LoopState` onto it -- the same "a second enum needs one total bridge, never
a silent guess" discipline `loop_contract.STATUS_TO_LOOP_STATE` already
established for `models.Status` vs `LoopState`. `golden_flow_readiness.py`'s
own READY/PARTIAL/BLOCKED/UNKNOWN four words (borrowed in turn from
`subsystem_discovery`) are reused as the IDENTICAL four `HarnessStatus`
spellings rather than re-declared, and `models.Status`'s ten stage-verdict
members get their own TOTAL bridge (`VERDICT_STATUS_TO_HARNESS_STATUS`,
mirroring `golden_flow_readiness.STATUS_TO_READINESS` including its own
ACCEPTED_RISK -> PARTIAL "a human accepted risk is not evidence of READY"
precedent, reused verbatim here).

GF-AT-28, ENFORCED AT THE TYPE LEVEL
--------------------------------------
`golden_flow_readiness.py` and `platform_health.py` both enforce, in code,
that UNKNOWN must never silently become READY/PASS/HEALTHY. This module
enforces the identical rule ONE LEVEL DOWN, at every single field
construction: `StatusField.__post_init__` REFUSES to construct a non-UNKNOWN,
non-NOT_APPLICABLE status field with no `fact_source` citation
(`HarnessStatusIRError`) -- so a future aggregator CANNOT accidentally claim
READY/SIGNOFF_READY/etc for a field it never actually read evidence for; the
type itself blocks it. `EvidenceField` (used for the schema's plain,
non-status facts -- project id, a git SHA, a job count) applies the identical
rule to its own `value`: a real value with no `fact_source` is refused the
same way. `derive_overall_status()` then folds every status-bearing field
worst-wins (`worst_status()`, modelled on `platform_health.worst()`: an empty
or all-NOT_APPLICABLE fold is UNKNOWN, never READY) -- so a fresh
`unknown_harness_status_ir()` (every field genuinely unknown) derives an
overall status of UNKNOWN, never a fabricated READY. This is what the
`test_negative_control_absence_of_evidence_is_honestly_unknown` test in this
module's test file proves end to end.

CHANGE-ONLY NOTIFICATION (section 433), REUSING escalation_notify.py
-----------------------------------------------------------------------
`notify_status_change()` is a thin funnel reusing `escalation_notify.py`'s
own `EscalationEvent`/`EscalationNotifier`/transport machinery rather than
building a second one: the SAME `EscalationNotifier` object a caller already
constructed (so there remains exactly one place in this harness that decides
whether a project is using a Null or Apprise transport) is used to fire only
when a status genuinely transitioned (`previous != current`), following
`EscalationNotifier._fire()`'s own documented discipline byte for byte (the
transport is touched only when the condition holds; a transport failure is
caught and folded into `reason`, never raised into the caller). It does not
reach into that private method or duplicate its body-writing logic -- it
reuses the transport object that method's own constructor already resolved.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field, fields as dc_fields, is_dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import escalation_notify
from . import subsystem_discovery as sd
from .models import Status as VerdictStatus

try:  # pragma: no cover - defensive; loop_contract has no heavy deps normally
    from . import loop_contract
except Exception:  # pragma: no cover
    loop_contract = None  # type: ignore[assignment]

SCHEMA_VERSION = "1.0"


class HarnessStatusIRError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Section 406: STATUS ENUM GOVERNANCE -- the one closed vocabulary
# ===========================================================================

class HarnessStatus(str, Enum):
    """The governed, closed status-enum vocabulary. CLI, GUI and Web must all
    render these exact nineteen words -- section 406: "do not invent
    surface-specific synonyms that alter semantics." Every status-bearing
    field of `HarnessStatusIR` is typed to this one enum; there is no second
    status vocabulary anywhere in this schema."""

    # --- Core Harness states (section 406, first block) -------------------
    READY = "READY"
    PARTIAL = "PARTIAL"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    BLOCKED = "BLOCKED"
    HUMAN_GATE = "HUMAN_GATE"
    STALE = "STALE"
    FAILED = "FAILED"
    SIGNOFF_READY = "SIGNOFF_READY"
    UNKNOWN = "UNKNOWN"
    # --- Supporting states (section 406, second block) ---------------------
    IDLE = "IDLE"
    WAITING = "WAITING"
    CONVERGING = "CONVERGING"
    PLATEAU = "PLATEAU"
    OSCILLATING = "OSCILLATING"
    RETRY_WAIT = "RETRY_WAIT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CANCELLED = "CANCELLED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: Section 406's own two blocks, transcribed verbatim (never re-derived from
#: `HarnessStatus` itself) so `assert_matches_section_406()` below is a real
#: check against the specification's own words, the same discipline
#: `golden_flow_readiness._assert_rows_match_section_47()` already applies to
#: its twenty rows.
SECTION_406_CORE_STATES: Tuple[str, ...] = (
    "READY", "PARTIAL", "RUNNING", "VERIFYING", "BLOCKED", "HUMAN_GATE",
    "STALE", "FAILED", "SIGNOFF_READY", "UNKNOWN",
)
SECTION_406_SUPPORTING_STATES: Tuple[str, ...] = (
    "IDLE", "WAITING", "CONVERGING", "PLATEAU", "OSCILLATING", "RETRY_WAIT",
    "BUDGET_EXHAUSTED", "CANCELLED", "NOT_APPLICABLE",
)

HARNESS_STATUS_VALUES: Tuple[str, ...] = tuple(s.value for s in HarnessStatus)


def assert_matches_section_406() -> None:
    """`HarnessStatus` must be exactly section 406's core+supporting union --
    no extra word, no missing one. A future edit that adds a surface-specific
    synonym (the thing section 406 explicitly forbids) fails this rather than
    silently widening the governed vocabulary."""
    declared = set(SECTION_406_CORE_STATES) | set(SECTION_406_SUPPORTING_STATES)
    actual = set(HARNESS_STATUS_VALUES)
    missing = sorted(declared - actual)
    extra = sorted(actual - declared)
    if missing or extra:
        raise HarnessStatusIRError("HARNESS_STATUS_DOES_NOT_MATCH_SECTION_406", {
            "missing_from_enum": missing, "not_in_section_406": extra})
    overlap = sorted(set(SECTION_406_CORE_STATES) & set(SECTION_406_SUPPORTING_STATES))
    if overlap:
        raise HarnessStatusIRError("SECTION_406_CORE_AND_SUPPORTING_OVERLAP", {
            "overlap": overlap})


#: Worst-wins severity, modelled directly on `platform_health.HEALTH_SEVERITY`
#: (higher = worse). Grounded in section 408's own "Possible severity/order
#: considerations" list for the eight words it names explicitly (worst to
#: best: FAILED, BLOCKED, HUMAN_GATE, STALE, RUNNING/VERIFYING, PARTIAL,
#: READY, SIGNOFF_READY) -- every other word is placed relative to that
#: spine with its own one-line reason:
#:   * UNKNOWN sits just above the "clean" band (worse than PARTIAL/READY/
#:     RUNNING/VERIFYING/CONVERGING/WAITING/IDLE) and below every CONFIRMED
#:     problem state -- the identical "a measured problem is a stronger
#:     statement than an unmeasured one" reasoning `platform_health.py`
#:     already gives for ranking its own UNKNOWN below DEGRADED/CRITICAL but
#:     above HEALTHY. This is GF-AT-28 made numeric: UNKNOWN can never fold
#:     to something at or better than READY.
#:   * NOT_APPLICABLE carries NO severity at all -- `worst_status()` excludes
#:     it from the fold entirely (see below), the same "does not apply, so it
#:     neither helps nor hurts" treatment `system_readiness_gates.py` already
#:     gives its own NOT_APPLICABLE conditions.
#:   * RETRY_WAIT/PLATEAU/OSCILLATING/BUDGET_EXHAUSTED are real, evidenced
#:     LOOP problems (`loop_budget.py`/`loop_convergence.py`'s own
#:     vocabulary) -- ranked worse than UNKNOWN for the same reason, and in
#:     the loop-engineering order those two modules already imply
#:     (retry < plateau < oscillation < budget exhaustion, each a
#:     successively stronger statement that something is genuinely stuck).
#:   * CANCELLED sits between BLOCKED and FAILED: an operator-terminated run
#:     is not a FAIL verdict, but it is not resolved either.
HARNESS_STATUS_SEVERITY: Dict[str, int] = {
    HarnessStatus.SIGNOFF_READY.value: 0,
    HarnessStatus.READY.value: 1,
    HarnessStatus.IDLE.value: 2,
    HarnessStatus.CONVERGING.value: 3,
    HarnessStatus.WAITING.value: 4,
    HarnessStatus.PARTIAL.value: 5,
    # Section 408's own list places "RUNNING / VERIFYING" (tied) between
    # PARTIAL and STALE, worse than PARTIAL -- an actively running/verifying
    # stage is more attention-worthy on a status BAR than a merely-partial
    # one, per the document's own ordering; honored verbatim rather than the
    # "quality" ordering an outcome-only ranking would otherwise suggest.
    HarnessStatus.RUNNING.value: 6,
    HarnessStatus.VERIFYING.value: 6,
    HarnessStatus.UNKNOWN.value: 7,
    HarnessStatus.RETRY_WAIT.value: 8,
    HarnessStatus.PLATEAU.value: 9,
    HarnessStatus.OSCILLATING.value: 10,
    HarnessStatus.BUDGET_EXHAUSTED.value: 11,
    HarnessStatus.STALE.value: 12,
    HarnessStatus.HUMAN_GATE.value: 13,
    HarnessStatus.BLOCKED.value: 14,
    HarnessStatus.CANCELLED.value: 15,
    HarnessStatus.FAILED.value: 16,
    # NOT_APPLICABLE deliberately absent -- see docstring above.
}


def assert_severity_covers_every_foldable_state() -> None:
    """Every `HarnessStatus` member except NOT_APPLICABLE must carry a
    severity, or `worst_status()` could silently drop a real status from the
    fold (treating it as if it were NOT_APPLICABLE)."""
    missing = [v for v in HARNESS_STATUS_VALUES
               if v != HarnessStatus.NOT_APPLICABLE.value and v not in HARNESS_STATUS_SEVERITY]
    if missing:
        raise HarnessStatusIRError("HARNESS_STATUS_SEVERITY_INCOMPLETE", {"missing": missing})


def worst_status(statuses: Iterable[str]) -> str:
    """The worst-wins roll-up of several `HarnessStatus` values (rule 2: "a
    single BLOCKED/UNKNOWN dimension outranks many clean ones"). NOT_APPLICABLE
    values are excluded from the fold -- they neither help nor hurt. An empty
    fold (nothing to fold, or everything was NOT_APPLICABLE) is UNKNOWN, never
    READY -- the same "empty set of subsystems is UNKNOWN, never HEALTHY"
    rule `platform_health.worst()` already enforces."""
    known = [s for s in statuses if s in HARNESS_STATUS_SEVERITY]
    if not known:
        return HarnessStatus.UNKNOWN.value
    return max(known, key=lambda s: HARNESS_STATUS_SEVERITY[s])


# ---------------------------------------------------------------------------
# Bridges: TOTAL maps from every status vocabulary this project already has
# an opinion about, onto HarnessStatus. Each is asserted total at import so a
# future member added to the SOURCE vocabulary fails loudly here instead of
# silently rendering the wrong Harness status.
# ---------------------------------------------------------------------------

#: subsystem_discovery's four words (already reused verbatim by
#: golden_flow_readiness.py) are an identity map onto their own HarnessStatus
#: spellings -- included as a real, asserted-total bridge (not "obviously
#: fine") so a caller feeding a golden_flow_readiness/system_readiness READY/
#: PARTIAL/BLOCKED/UNKNOWN value into this schema never has to hand-roll the
#: conversion.
READINESS_TO_HARNESS_STATUS: Dict[str, str] = {
    sd.READY: HarnessStatus.READY.value,
    sd.PARTIAL: HarnessStatus.PARTIAL.value,
    sd.BLOCKED: HarnessStatus.BLOCKED.value,
    sd.UNKNOWN: HarnessStatus.UNKNOWN.value,
}


def assert_readiness_bridge_total() -> None:
    missing = [r for r in sd.READINESS_CLASSES if r not in READINESS_TO_HARNESS_STATUS]
    if missing:
        raise HarnessStatusIRError("READINESS_BRIDGE_INCOMPLETE", {"missing": missing})


#: `models.Status` -- the per-stage VERDICT vocabulary -- onto HarnessStatus.
#: Mirrors `golden_flow_readiness.STATUS_TO_READINESS` field for field where
#: that mapping already answers the question (PASS/CLOSED -> a "done" state,
#: ACCEPTED_RISK -> PARTIAL, the identical "a human accepted a known risk is
#: not evidence of READY" reasoning reused verbatim), and is deliberately
#: MORE PRECISE where HarnessStatus's wider vocabulary allows it: CLOSED
#: (the whole project's own terminal, signed-off state) maps to
#: SIGNOFF_READY rather than merely READY, since HarnessStatusIR's `harness`
#: block already carries a separate `signoff_state` field this distinction is
#: meant to feed.
VERDICT_STATUS_TO_HARNESS_STATUS: Dict[str, str] = {
    VerdictStatus.NOT_STARTED.value: HarnessStatus.IDLE.value,
    VerdictStatus.RUNNING.value: HarnessStatus.RUNNING.value,
    VerdictStatus.PASS.value: HarnessStatus.READY.value,
    VerdictStatus.FAIL.value: HarnessStatus.FAILED.value,
    VerdictStatus.PARTIAL.value: HarnessStatus.PARTIAL.value,
    VerdictStatus.BLOCKED.value: HarnessStatus.BLOCKED.value,
    VerdictStatus.RETRY.value: HarnessStatus.RETRY_WAIT.value,
    VerdictStatus.WAIT_USER.value: HarnessStatus.HUMAN_GATE.value,
    VerdictStatus.CLOSED.value: HarnessStatus.SIGNOFF_READY.value,
    VerdictStatus.ACCEPTED_RISK.value: HarnessStatus.PARTIAL.value,
}


def assert_verdict_status_bridge_total() -> None:
    missing = [s.value for s in VerdictStatus if s.value not in VERDICT_STATUS_TO_HARNESS_STATUS]
    if missing:
        raise HarnessStatusIRError("VERDICT_STATUS_BRIDGE_INCOMPLETE", {"missing": missing})


#: `loop_contract.LoopState` onto HarnessStatus. Every value with an identical
#: spelling in both enums maps to itself (fourteen of seventeen); the three
#: that do not (CREATED/SUCCESS/STOPPED/RESUMING) each carry a one-line
#: reason at the mapping site below.
if loop_contract is not None:
    LOOP_STATE_TO_HARNESS_STATUS: Dict[str, str] = {
        # No harness-vocabulary "just created" word beyond IDLE -- a loop
        # that has not started yet is, from the Global Status Bar's point of
        # view, indistinguishable from an idle one.
        loop_contract.LoopState.CREATED.value: HarnessStatus.IDLE.value,
        loop_contract.LoopState.READY.value: HarnessStatus.READY.value,
        loop_contract.LoopState.RUNNING.value: HarnessStatus.RUNNING.value,
        loop_contract.LoopState.VERIFYING.value: HarnessStatus.VERIFYING.value,
        loop_contract.LoopState.CONVERGING.value: HarnessStatus.CONVERGING.value,
        loop_contract.LoopState.PLATEAU.value: HarnessStatus.PLATEAU.value,
        loop_contract.LoopState.OSCILLATING.value: HarnessStatus.OSCILLATING.value,
        loop_contract.LoopState.RETRY_WAIT.value: HarnessStatus.RETRY_WAIT.value,
        loop_contract.LoopState.BLOCKED.value: HarnessStatus.BLOCKED.value,
        loop_contract.LoopState.HUMAN_GATE.value: HarnessStatus.HUMAN_GATE.value,
        # loop_contract.py's own rule: SUCCESS is the LOOP's machine-checkable
        # done (overall_status == CLOSED would be SIGNOFF_READY one level up;
        # a single loop session finishing is READY, not yet a project-wide
        # signoff claim).
        loop_contract.LoopState.SUCCESS.value: HarnessStatus.READY.value,
        loop_contract.LoopState.FAILED.value: HarnessStatus.FAILED.value,
        loop_contract.LoopState.BUDGET_EXHAUSTED.value: HarnessStatus.BUDGET_EXHAUSTED.value,
        # STOPPED is loop_contract.py's own "a human accepted residual risk"
        # state -- the identical case models.Status.ACCEPTED_RISK already
        # floors to PARTIAL for, reused here for the same reason.
        loop_contract.LoopState.STOPPED.value: HarnessStatus.PARTIAL.value,
        loop_contract.LoopState.CANCELLED.value: HarnessStatus.CANCELLED.value,
        # RESUMING is, per loop_stale_detection.py's own docstring, "confirming
        # a resumed session's SHA/environment/tool versions still match before
        # trusting its earlier evidence" -- that is a VERIFYING act.
        loop_contract.LoopState.RESUMING.value: HarnessStatus.VERIFYING.value,
        loop_contract.LoopState.STALE.value: HarnessStatus.STALE.value,
    }
else:  # pragma: no cover - loop_contract always importable in this repo
    LOOP_STATE_TO_HARNESS_STATUS = {}


def assert_loop_state_bridge_total() -> None:
    if loop_contract is None:  # pragma: no cover
        raise HarnessStatusIRError("LOOP_CONTRACT_UNAVAILABLE", {})
    missing = [s.value for s in loop_contract.LoopState
               if s.value not in LOOP_STATE_TO_HARNESS_STATUS]
    if missing:
        raise HarnessStatusIRError("LOOP_STATE_BRIDGE_INCOMPLETE", {"missing": missing})


def assert_all_status_governance() -> None:
    """The one call a test (or a future importer) makes to hold every piece
    of this module's status governance at once."""
    assert_matches_section_406()
    assert_severity_covers_every_foldable_state()
    assert_readiness_bridge_total()
    assert_verdict_status_bridge_total()
    assert_loop_state_bridge_total()


# ===========================================================================
# Evidence-cited field primitives -- GF-AT-28 enforced at construction
# ===========================================================================

@dataclass
class StatusField:
    """One HarnessStatusIR status-bearing leaf. `status` is always a real
    `HarnessStatus` value; `fact_source` names the real module.callable a
    future aggregator must read this from (never invented -- see
    `FACT_SOURCE_CATALOG`). Construction ITSELF enforces GF-AT-28: a
    non-UNKNOWN, non-NOT_APPLICABLE status with no `fact_source` is refused,
    so "UNKNOWN silently becomes READY" cannot happen even by a caller's
    mistake -- the type refuses to hold that shape."""
    status: str
    value: Any = None
    fact_source: Optional[str] = None
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in HARNESS_STATUS_VALUES:
            raise HarnessStatusIRError("STATUS_FIELD_UNRECOGNIZED_STATUS", {
                "status": self.status, "allowed": HARNESS_STATUS_VALUES})
        needs_evidence = self.status not in (
            HarnessStatus.UNKNOWN.value, HarnessStatus.NOT_APPLICABLE.value)
        if needs_evidence and not self.fact_source:
            raise HarnessStatusIRError("STATUS_FIELD_MISSING_FACT_SOURCE", {
                "status": self.status,
                "reason": ("a non-UNKNOWN, non-NOT_APPLICABLE status must cite the "
                           "real module/function it was read from -- GF-AT-28: "
                           "absence of evidence must never silently become a good "
                           "status")})

    def to_dict(self) -> dict:
        return {"status": self.status, "value": self.value,
                "fact_source": self.fact_source, "detail": self.detail}


@dataclass
class EvidenceField:
    """One HarnessStatusIR plain (non-status) leaf -- an identity string, a
    SHA, a job count, a timestamp. The identical Evidence Truth Rule applies
    one level down from `StatusField`: a real `value` with no `fact_source`
    is refused. The honest default (nothing read yet) is `value=None,
    fact_source=None`, which needs no reason string -- a bare `None` cannot
    be misread as a resolved claim the way a `HarnessStatus` member could."""
    value: Any = None
    fact_source: Optional[str] = None

    def __post_init__(self) -> None:
        if self.value is not None and not self.fact_source:
            raise HarnessStatusIRError("EVIDENCE_FIELD_MISSING_FACT_SOURCE", {
                "value": self.value,
                "reason": "a real value must cite the real module/function it came from"})

    @property
    def available(self) -> bool:
        return self.fact_source is not None and self.fact_source != ""

    def to_dict(self) -> dict:
        return {"value": self.value, "fact_source": self.fact_source,
                "available": self.available}


def unknown_field(reason: str) -> StatusField:
    """The one sanctioned way to construct a genuinely-unknown status field.
    `reason` is required and becomes the field's own `fact_source` -- "we do
    not know" is still a citable fact (which absence, checked when) rather
    than a silent gap, the same discipline `platform_health.py`'s
    `NO_RECORDED_CHECK`/`NEVER_RUN` reasons already carry."""
    if not reason:
        raise HarnessStatusIRError("UNKNOWN_FIELD_REQUIRES_A_REASON", {})
    return StatusField(status=HarnessStatus.UNKNOWN.value, fact_source=reason)


def known_field(status: str, *, value: Any = None, fact_source: str,
                detail: Optional[str] = None) -> StatusField:
    """The one sanctioned way to construct a resolved (non-UNKNOWN) status
    field -- `fact_source` is a required keyword precisely so a caller cannot
    accidentally omit it positionally."""
    return StatusField(status=status, value=value, fact_source=fact_source, detail=detail)


def not_applicable_field(reason: str) -> StatusField:
    """A dimension that genuinely does not apply to this project (e.g. no
    remote execution configured) -- excluded from `worst_status()`'s fold
    entirely, never counted as a clean READY and never counted as a problem."""
    if not reason:
        raise HarnessStatusIRError("NOT_APPLICABLE_FIELD_REQUIRES_A_REASON", {})
    return StatusField(status=HarnessStatus.NOT_APPLICABLE.value, fact_source=reason)


# ===========================================================================
# Section 405: HarnessStatusIR -- the eleven blocks, verbatim field order
# ===========================================================================

def _unknown() -> StatusField:
    return unknown_field("no producer read yet")


def _absent() -> EvidenceField:
    return EvidenceField()


@dataclass
class IdentityIR:
    project_id: EvidenceField = field(default_factory=_absent)
    project_name: EvidenceField = field(default_factory=_absent)
    mode: EvidenceField = field(default_factory=_absent)
    subsystem: EvidenceField = field(default_factory=_absent)
    system: EvidenceField = field(default_factory=_absent)
    environment: EvidenceField = field(default_factory=_absent)


@dataclass
class BaselineIR:
    dut: EvidenceField = field(default_factory=_absent)
    dut_version: EvidenceField = field(default_factory=_absent)
    rtl_sha: EvidenceField = field(default_factory=_absent)
    tb_sha: EvidenceField = field(default_factory=_absent)
    spec_version: EvidenceField = field(default_factory=_absent)
    register_version: EvidenceField = field(default_factory=_absent)
    vip_version: EvidenceField = field(default_factory=_absent)
    harness_version: EvidenceField = field(default_factory=_absent)


@dataclass
class HarnessCoreIR:
    """Section 405's `harness:` block. Named `HarnessCoreIR` rather than
    `HarnessIR` to avoid reading as a synonym for the top-level
    `HarnessStatusIR` itself."""
    state: StatusField = field(default_factory=_unknown)
    readiness: StatusField = field(default_factory=_unknown)
    signoff_state: StatusField = field(default_factory=_unknown)


@dataclass
class WorkflowIR:
    current_agent: EvidenceField = field(default_factory=_absent)
    current_node: EvidenceField = field(default_factory=_absent)
    current_loop: EvidenceField = field(default_factory=_absent)
    current_operation: EvidenceField = field(default_factory=_absent)
    iteration: EvidenceField = field(default_factory=_absent)
    convergence_state: StatusField = field(default_factory=_unknown)


@dataclass
class ExecutionIR:
    queued_jobs: EvidenceField = field(default_factory=_absent)
    running_jobs: EvidenceField = field(default_factory=_absent)
    passed_jobs: EvidenceField = field(default_factory=_absent)
    failed_jobs: EvidenceField = field(default_factory=_absent)
    killed_jobs: EvidenceField = field(default_factory=_absent)
    wait_license_jobs: EvidenceField = field(default_factory=_absent)
    timeout_jobs: EvidenceField = field(default_factory=_absent)
    regression_state: StatusField = field(default_factory=_unknown)
    simulation_state: StatusField = field(default_factory=_unknown)


@dataclass
class ClosureIR:
    """Every leaf here is itself a closure-domain readiness state -- section
    405 names ten closure dimensions, and every one of them is exactly the
    READY/PARTIAL/BLOCKED/UNKNOWN-shaped question its own already-real
    reader answers (never re-derived here)."""
    requirement: StatusField = field(default_factory=_unknown)
    vplan: StatusField = field(default_factory=_unknown)
    functional_coverage: StatusField = field(default_factory=_unknown)
    code_coverage: StatusField = field(default_factory=_unknown)
    assertion: StatusField = field(default_factory=_unknown)
    protocol: StatusField = field(default_factory=_unknown)
    connectivity: StatusField = field(default_factory=_unknown)
    performance: StatusField = field(default_factory=_unknown)
    subsystem: StatusField = field(default_factory=_unknown)
    system: StatusField = field(default_factory=_unknown)


@dataclass
class IntegrationIR:
    proof_level_current: EvidenceField = field(default_factory=_absent)
    proof_level_required: EvidenceField = field(default_factory=_absent)
    compatibility_state: StatusField = field(default_factory=_unknown)
    resource_conflicts: EvidenceField = field(default_factory=_absent)


@dataclass
class BlockersIR:
    critical_failures: EvidenceField = field(default_factory=_absent)
    critical_unknown: EvidenceField = field(default_factory=_absent)
    stale_evidence: EvidenceField = field(default_factory=_absent)
    human_gates: EvidenceField = field(default_factory=_absent)
    blocked_items: EvidenceField = field(default_factory=_absent)


@dataclass
class ResourcesIR:
    remote_execution: StatusField = field(default_factory=_unknown)
    lsf: StatusField = field(default_factory=_unknown)
    license: StatusField = field(default_factory=_unknown)
    vcs: StatusField = field(default_factory=_unknown)
    verdi: StatusField = field(default_factory=_unknown)
    fsdb: StatusField = field(default_factory=_unknown)


@dataclass
class FreshnessIR:
    status_timestamp: EvidenceField = field(default_factory=_absent)
    source_timestamp: EvidenceField = field(default_factory=_absent)
    stale_after_policy: EvidenceField = field(default_factory=_absent)
    state: StatusField = field(default_factory=_unknown)


@dataclass
class EvidenceRefsIR:
    """Section 405's `evidence:` block -- named `EvidenceRefsIR` to avoid
    colliding with the generic `EvidenceField` primitive above."""
    source_refs: EvidenceField = field(default_factory=_absent)
    run_id: EvidenceField = field(default_factory=_absent)
    session_id: EvidenceField = field(default_factory=_absent)


@dataclass
class HarnessStatusIR:
    """The canonical section-405 data model. `schema_version` lets a future
    breaking change to this shape be detected the way `env_manifest.py`'s own
    `SCHEMA_VERSION` bump already is in this repo -- a stale-shaped record
    fails loudly rather than being silently misread."""
    identity: IdentityIR = field(default_factory=IdentityIR)
    baseline: BaselineIR = field(default_factory=BaselineIR)
    harness: HarnessCoreIR = field(default_factory=HarnessCoreIR)
    workflow: WorkflowIR = field(default_factory=WorkflowIR)
    execution: ExecutionIR = field(default_factory=ExecutionIR)
    closure: ClosureIR = field(default_factory=ClosureIR)
    integration: IntegrationIR = field(default_factory=IntegrationIR)
    blockers: BlockersIR = field(default_factory=BlockersIR)
    resources: ResourcesIR = field(default_factory=ResourcesIR)
    freshness: FreshnessIR = field(default_factory=FreshnessIR)
    evidence: EvidenceRefsIR = field(default_factory=EvidenceRefsIR)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        out: Dict[str, Any] = {"schema_version": self.schema_version}
        for f in dc_fields(self):
            if f.name == "schema_version":
                continue
            section = getattr(self, f.name)
            out[f.name] = {
                leaf.name: getattr(section, leaf.name).to_dict()
                for leaf in dc_fields(section)
            }
        return out


#: The eleven section names, in section 405's own order -- used by both the
#: leaf-walker below and `assert_ir_matches_section_405()`.
HARNESS_STATUS_IR_SECTIONS: Tuple[str, ...] = tuple(
    f.name for f in dc_fields(HarnessStatusIR) if f.name != "schema_version")


def iter_leaf_fields(ir: HarnessStatusIR) -> Iterable[Tuple[str, Any]]:
    """Yield `("section.leaf", field_instance)` for every leaf of the IR, in
    section 405's own declared order -- the one walker every helper below
    (and a future aggregator) should use rather than re-deriving its own."""
    for section_name in HARNESS_STATUS_IR_SECTIONS:
        section_obj = getattr(ir, section_name)
        for leaf in dc_fields(section_obj):
            yield f"{section_name}.{leaf.name}", getattr(section_obj, leaf.name)


def all_status_fields(ir: HarnessStatusIR) -> List[Tuple[str, StatusField]]:
    return [(p, v) for p, v in iter_leaf_fields(ir) if isinstance(v, StatusField)]


def all_evidence_fields(ir: HarnessStatusIR) -> List[Tuple[str, EvidenceField]]:
    return [(p, v) for p, v in iter_leaf_fields(ir) if isinstance(v, EvidenceField)]


def unknown_harness_status_ir(reason: str = "fresh project -- no subsystem read yet"
                              ) -> HarnessStatusIR:
    """The reference "absence of evidence" instance: every status-bearing
    field is genuinely UNKNOWN (never a fabricated READY), every plain field
    is genuinely absent. This is what a Global State Aggregator should
    produce for a project it has read nothing about yet, and it is the
    negative-control fixture this module's own tests build
    `derive_overall_status()`'s honesty proof from."""
    ir = HarnessStatusIR()
    for _, f in all_status_fields(ir):
        f.status = HarnessStatus.UNKNOWN.value
        f.fact_source = reason
    return ir


def derive_overall_status(ir: HarnessStatusIR) -> StatusField:
    """Rule 2 (worst-wins aggregation), applied over the IR's own status
    fields: NOT_APPLICABLE fields never participate, a single BLOCKED/UNKNOWN
    field outranks any number of READY ones, and an IR carrying no
    resolvable status field at all folds to UNKNOWN -- never READY. This is a
    reusable HELPER a future Global State Aggregator may call; it is not
    itself the aggregator (it derives nothing from outside the IR it is
    handed)."""
    pairs = [(p, f) for p, f in all_status_fields(ir)
             if f.status != HarnessStatus.NOT_APPLICABLE.value]
    if not pairs:
        return StatusField(
            status=HarnessStatus.UNKNOWN.value,
            fact_source=("derive_overall_status(): no status-bearing field carried "
                         "anything but NOT_APPLICABLE (or the IR is empty)"))
    worst_value = worst_status(f.status for _, f in pairs)
    driver_path, driver_field = next((p, f) for p, f in pairs if f.status == worst_value)
    return StatusField(
        status=worst_value,
        value=driver_path,
        fact_source=(f"worst-wins fold over {len(pairs)} status field(s); driven by "
                     f"{driver_path} ({driver_field.fact_source or 'no fact_source recorded'})"))


# ===========================================================================
# Rule 3 (REUSE OVER REINVENT): every leaf's declared, checkable fact source
# ===========================================================================

#: Every leaf path in `HarnessStatusIR`, mapped to the real
#: `module.attribute` a Global State Aggregator MUST read it from. This is
#: the schema half of REUSE OVER REINVENT: it never calls any of these
#: (calling them is section 409's job), it only DECLARES, per field, which
#: existing real subsystem owns that fact -- and `assert_fact_source_catalog_
#: resolvable()` below proves every citation still resolves through the
#: import system, the same guard `subsystem_maturity_gate.
#: assert_fact_sources_resolvable()`/`generation_readiness.
#: assert_fact_sources_resolvable()` already run for their own row tables.
FACT_SOURCE_CATALOG: Dict[str, str] = {
    # identity
    "identity.project_id": "dv_harness.storage.StateStore.load",
    "identity.project_name": "dv_harness.storage.StateStore.load",
    "identity.mode": "dv_harness.environment_mode_router.resolve_environment_mode",
    "identity.subsystem": "dv_harness.environment_mode_router.read_registered_subsystem_entries",
    "identity.system": "dv_harness.system_verification_contract.assemble_system_verification_contract",
    "identity.environment": "dv_harness.config.load_config",
    # baseline
    "baseline.dut": "dv_harness.env_manifest.build_dut_facts_rtl",
    "baseline.dut_version": "dv_harness.storage.StateStore.load",
    "baseline.rtl_sha": "dv_harness.connectivity_check.compute_rtl_fingerprint",
    "baseline.tb_sha": "dv_harness.signoff_export._capture_tb_sha",
    "baseline.spec_version": "dv_harness.signoff_export._capture_spec_version",
    "baseline.register_version": "dv_harness.env_manifest.build_dut_facts_registers",
    "baseline.vip_version": "dv_harness.env_manifest.build_vip_release",
    "baseline.harness_version": "dv_harness.__version__",
    # harness
    "harness.state": "dv_harness.storage.StateStore.load",
    "harness.readiness": "dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
    "harness.signoff_state": "dv_harness.signoff_export.read_signoff_stage_status",
    # workflow
    "workflow.current_agent": "dv_harness.control_plane.describe_stage",
    "workflow.current_node": "dv_harness.storage.StateStore.load",
    "workflow.current_loop": "dv_harness.loop_telemetry.read_loop_telemetry",
    "workflow.current_operation": "dv_harness.react_loop.InnerReactLoop",
    "workflow.iteration": "dv_harness.loop_telemetry.gate_verified_stage_count",
    "workflow.convergence_state": "dv_harness.loop_convergence.classify_loop_convergence",
    # execution
    "execution.queued_jobs": "dv_harness.lsf_client.discover_live_jobs",
    "execution.running_jobs": "dv_harness.lsf_client.discover_live_jobs",
    "execution.passed_jobs": "dv_harness.evidence_db.EvidenceStore",
    "execution.failed_jobs": "dv_harness.evidence_db.EvidenceStore",
    "execution.killed_jobs": "dv_harness.lsf_client.map_bjobs_stat_to_lsf_status",
    "execution.wait_license_jobs": "dv_harness.preflight.check_license",
    "execution.timeout_jobs": "dv_harness.lsf_client.evaluate_auto_kill",
    "execution.regression_state": "dv_harness.trend_analysis.trend_report",
    "execution.simulation_state": "dv_harness.connectivity.evaluate_transaction_activity_status",
    # closure
    "closure.requirement": "dv_harness.requirement_contract.analyze_requirement_contract_set",
    "closure.vplan": "dv_harness.vplan_artifact.analyze_vplan_completeness",
    "closure.functional_coverage": "dv_harness.functional_coverage_signoff.analyze_functional_coverage_signoff",
    "closure.code_coverage": "dv_harness.coverage_analysis.identify_holes",
    "closure.assertion": "dv_harness.evidence_provenance.summarize_evidence_blocks",
    "closure.protocol": "dv_harness.protocol_compliance_aggregation.aggregate_protocol_compliance",
    "closure.connectivity": "dv_harness.connectivity_check.run_connectivity_check",
    "closure.performance": "dv_harness.amba_performance_readiness_gates.evaluate_amba_performance_readiness_gates",
    "closure.subsystem": "dv_harness.subsystem_maturity_gate.derive_maturity_gate",
    "closure.system": "dv_harness.system_readiness_gates.derive_system_readiness_gates",
    # integration
    "integration.proof_level_current": "dv_harness.qualification.map_to_system_level_state",
    "integration.proof_level_required": "dv_harness.qualification.map_to_system_level_state",
    "integration.compatibility_state": "dv_harness.system_resource_inventory.real_cross_subsystem_findings",
    "integration.resource_conflicts": "dv_harness.system_resource_inventory.real_cross_subsystem_findings",
    # blockers
    "blockers.critical_failures": "dv_harness.trend_analysis.detect_pattern_regressions",
    "blockers.critical_unknown": "dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
    "blockers.stale_evidence": "dv_harness.golden_scenario.evaluate_freshness",
    "blockers.human_gates": "dv_harness.question_queue.QuestionQueueStore",
    "blockers.blocked_items": "dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
    # resources
    "resources.remote_execution": "dv_harness.preflight.check_host_reachability",
    "resources.lsf": "dv_harness.preflight.check_queue_health",
    "resources.license": "dv_harness.preflight.check_license",
    "resources.vcs": "dv_harness.connectivity.run_gate1_elaboration_check",
    "resources.verdi": "dv_harness.connectivity.run_gate2_against_live_simv",
    "resources.fsdb": "dv_harness.fsdb_report.run_fsdbreport",
    # freshness
    "freshness.status_timestamp": "dv_harness.storage.StateStore.load",
    "freshness.source_timestamp": "dv_harness.connectivity_check.evaluate_staleness",
    "freshness.stale_after_policy": "dv_harness.loop_stale_detection.detect_loop_staleness",
    "freshness.state": "dv_harness.loop_stale_detection.detect_loop_staleness",
    # evidence
    "evidence.source_refs": "dv_harness.evidence_db.EvidenceStore",
    "evidence.run_id": "dv_harness.loop_telemetry.new_run_id",
    "evidence.session_id": "dv_harness.dashboard_auth.session_file",
}


def assert_fact_source_catalog_matches_ir() -> None:
    """`FACT_SOURCE_CATALOG` must name exactly the IR's own leaf paths -- no
    stale entry for a field that no longer exists, no leaf left uncited."""
    declared = set(FACT_SOURCE_CATALOG)
    actual = {p for p, _ in iter_leaf_fields(unknown_harness_status_ir())}
    missing = sorted(actual - declared)
    extra = sorted(declared - actual)
    if missing or extra:
        raise HarnessStatusIRError("FACT_SOURCE_CATALOG_MISMATCH", {
            "leaves_with_no_catalog_entry": missing,
            "catalog_entries_for_nonexistent_leaves": extra})


def _resolve_dotted(dotted: str) -> Any:
    """Import `dotted` progressively (longest importable module prefix
    first, per-attribute `getattr` for the rest) -- the same algorithm
    `subsystem_maturity_gate.assert_fact_sources_resolvable()` already uses
    for the identical purpose, reapplied here rather than imported (it is a
    five-line generic algorithm, not a second analysis engine)."""
    parts = dotted.split(".")
    obj = None
    rest: List[str] = []
    for cut in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except Exception:
            continue
        rest = parts[cut:]
        break
    if obj is None:
        raise HarnessStatusIRError("FACT_SOURCE_MODULE_UNIMPORTABLE", {"fact_source": dotted})
    for name in rest:
        if not hasattr(obj, name):
            raise HarnessStatusIRError("FACT_SOURCE_ATTRIBUTE_MISSING", {
                "fact_source": dotted, "missing_attribute": name})
        obj = getattr(obj, name)
    return obj


def assert_fact_source_catalog_resolvable() -> List[str]:
    """Every declared `FACT_SOURCE_CATALOG` citation still resolves through
    the import system -- a row citing a renamed/removed function fails this
    test rather than silently pointing a future aggregator at nothing."""
    resolved: List[str] = []
    for leaf_path, dotted in FACT_SOURCE_CATALOG.items():
        try:
            _resolve_dotted(dotted)
        except HarnessStatusIRError as e:
            e.detail["leaf_path"] = leaf_path
            raise
        resolved.append(dotted)
    return resolved


# ===========================================================================
# Rule 4: change-only notification, reusing escalation_notify.py's discipline
# ===========================================================================

def notify_status_change(notifier: "escalation_notify.EscalationNotifier", *,
                         dimension: str, previous: Optional[str], current: str,
                         title: str, body: str) -> "escalation_notify.EscalationEvent":
    """Section 433's rule -- "status may refresh silently while notification
    follows change-only policy" -- implemented by reusing
    `escalation_notify.EscalationNotifier`'s own transport object and
    `EscalationEvent` record, rather than building a second notifier. `fired`
    is True only when `previous != current` (never on a PASS -> PASS-shaped
    no-op, exactly section 433's own worked example); the transport is
    touched only in that case, and a transport failure is caught and folded
    into `reason` rather than raised -- the identical discipline
    `EscalationNotifier._fire()` already implements for every other
    escalation kind in this project. `previous=None` (nothing observed yet)
    is treated as "already different from any real current value", so the
    very first observation of a field is itself a change worth reporting."""
    condition = previous != current
    reason = f"{previous if previous is not None else 'UNOBSERVED'} -> {current}"
    if not condition:
        return escalation_notify.EscalationEvent(
            kind=dimension, fired=False, delivered=False, title=title, body=body, reason=reason)
    delivered = False
    try:
        delivered = bool(notifier.transport.send(title, body, tags=[dimension]))
    except Exception as e:  # noqa: BLE001 -- a notify failure must never abort the caller
        reason = f"{reason} (transport error: {e})"
    return escalation_notify.EscalationEvent(
        kind=dimension, fired=True, delivered=delivered, title=title, body=body, reason=reason)


# ---------------------------------------------------------------------------
# Import-time governance
# ---------------------------------------------------------------------------

assert_all_status_governance()
assert_fact_source_catalog_matches_ir()
