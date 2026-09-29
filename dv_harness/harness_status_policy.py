"""dv_harness/harness_status_policy.py -- UNKNOWN / STALE / change-only-notification /
freshness policies applied to HarnessStatusIR TRANSITIONS (Global Status Bar theme,
CLAUDE_L5_GLOBAL_STATUS_BAR_MASTER.md sections 422-423, 433-434).

THE GAP THIS CLOSES
--------------------
This batch's own two core aggregator items already exist and were read in full before writing
this module:

  * `harness_status_ir.py` -- section 405's `HarnessStatusIR` SCHEMA (evidence-cited
    `StatusField`/`EvidenceField` leaves, the governed `HarnessStatus` enum, and a generic
    `notify_status_change()` primitive reusing `escalation_notify.py`).
  * `harness_status.py` -- section 409's real, WIRED `GlobalStateAggregator` +
    `HarnessStatusService`, which actually READS the many real subsystems this project has
    (golden_flow_readiness, platform_health, loop_telemetry, signoff_export, ...) and produces a
    real `HarnessStatusIR` snapshot every time `serve()`/`publish()` is called.

Both modules do real, section-405/406/408/409/410 work. Neither implements sections 422-423
(UNKNOWN/STALE policy) or the FULL scope of 433-434 (change-only notification / freshness) as
their own dedicated, testable policy layer:

  * `harness_status.py`'s `HarnessStatusService.validate()` enforces GF-AT-28 only at the single
    coarse `harness.state`/`dimension_states` level (all-UNKNOWN dimensions can never resolve to
    READY/SIGNOFF_READY) -- it never asks "how many, and WHICH, individual status fields are
    UNKNOWN right now" (section 422's "Critical UNKNOWN count shall be visible... Selecting/
    expanding UNKNOWN shall reveal affected items and evidence gaps").
  * Neither module has any notion of section 423's STALE policy ("STALE artifacts cannot satisfy
    current signoff unless explicitly revalidated").
  * `harness_status.py`'s own `HarnessStatusService.publish()` implements change-only
    notification for exactly ONE dimension (`signoff_state`, and only for the single
    "newly BLOCKED" transition) via a bespoke, one-off call into
    `escalation_notify.EscalationNotifier.signoff_blocked()`. Section 433 names a WIDER rule with
    THREE outcomes, not two -- "PASS -> PASS: no notification", "RUNNING -> FAIL: notify",
    "UNKNOWN 3 -> UNKNOWN 2: update" (a silent refresh, distinct from both no-op AND a real
    notification), "GATE 0 -> GATE 1: notify" -- and `harness_status_ir.py`'s own
    `notify_status_change()` is a general two-outcome (fire/no-fire) primitive that has no caller
    anywhere in this repo for any dimension other than that one signoff-only path.
  * Section 434's freshness rule ("never preserve the last READY state indefinitely without
    freshness indication") is not enforced anywhere: `HarnessStatusService.serve()` reports
    `harness.state` and `freshness.state` as two independent fields with no fold between them, so
    a genuinely stale project could keep showing a READY `harness.state` forever.

This module is that missing policy layer, and it is a THIN layer on purpose: every mechanism it
needs already exists in this batch's own two sibling modules, and this module's job is to APPLY
them to `HarnessStatusIR` transitions, never to re-derive a competing implementation of any of
them.

REUSE OVER REINVENT, verified line by line before writing anything here:
  * Notification itself is `harness_status_ir.notify_status_change()`, called verbatim -- this
    module adds no second `EscalationNotifier`/`EscalationEvent`/transport-touching code path.
    That function's own "condition = previous != current; fire only when different" discipline is
    the exact primitive section 433's three-outcome rule below is built on top of.
  * The GF-AT-28 worst-wins fold used for the freshness policy is `harness_status.
    worst_harness_state()` -- the SAME severity table (`HARNESS_STATE_SEVERITY`) section 409's own
    aggregator already uses to compute `harness.state` itself, called verbatim rather than a
    second severity ranking invented here. Reusing it is what makes the freshness gate correct
    "for free": `STALE`/`UNKNOWN` already outrank `READY`/`SIGNOFF_READY` in that table (the same
    GF-AT-28 precedent `golden_flow_readiness.combine_readiness()` already establishes one domain
    over -- "an empty input is UNKNOWN, never READY" -- reused here as "a STALE/UNKNOWN freshness
    signal folds the effective state at least that severe, never READY").
  * `harness_status.py`'s own `unknowns: List[Dict[str, str]]` field (already populated, field by
    field, by every real gatherer in `GlobalStateAggregator.assemble()`) IS the evidence-gap
    citation trail section 422 asks the status bar to "reveal" on expansion -- this module never
    invents a second citation mechanism; `unknown_evidence_gaps()` below only cross-references it.

GF-AT-28, APPLIED ONE LEVEL DOWN FROM THE COARSE `harness.state` FOLD
-----------------------------------------------------------------------
`HarnessStatusService.validate()` already refuses a `harness.state` of READY/SIGNOFF_READY when
EVERY `dimension_states` value is UNKNOWN. This module enforces the identical rule at the
PER-FIELD grain section 422 actually asks for: `critical_unknown_count()` counts every
individually-UNKNOWN field among a fixed, real set of status-bearing leaves
(`CRITICAL_STATUS_LEAF_PATHS`, self-checked against the real `HarnessStatusIR` shape at import --
see `_assert_critical_paths_resolvable()`), and `find_unknown_status_fields()`/
`unknown_evidence_gaps()` name exactly which fields those are and why, so "UNKNOWN != 0" (section
422's own hard invariant) is never a claim this module could get wrong by silent omission -- the
count is derived directly from the real snapshot, never cached, defaulted, or suppressed.

STALE POLICY (section 423)
----------------------------
`find_stale_artifacts()`/`assert_stale_artifacts_never_satisfy_signoff()`/
`derive_stale_gated_signoff_state()` apply section 423's rule to the section-405 leaves that stand
in for its own worked examples (Tests -> `execution.regression_state`/`execution.simulation_state`,
Coverage Results -> `closure.functional_coverage`, Performance Baselines -> `closure.performance`,
SubsystemVerificationContract -> `closure.subsystem`, SystemIntegrationProof /
SystemVerificationContract -> `closure.system`, Signoff Evidence -> `harness.signoff_state`
itself). "Unless explicitly revalidated" is enforced literally: a caller may pass `revalidated={
path: reason, ...}`, and an entry with no real, non-empty reason string is refused
(`HarnessStatusPolicyError`) exactly like `harness_status_ir.unknown_field()`'s own "a reason is
required" discipline -- a bare `True`/empty-string revalidation is not an explicit revalidation.

CHANGE-ONLY NOTIFICATION (section 433) -- three outcomes, not two
---------------------------------------------------------------------
`classify_transition()` recovers all four of section 433's own worked examples from one small
rule, rather than hand-coding four special cases:

    equal                                  -> NO_CHANGE  (PASS -> PASS)
    both numeric, current < previous       -> UPDATE     (UNKNOWN 3 -> UNKNOWN 2: an improving
                                                            blocker-shaped count -- silent refresh)
    both numeric, current > previous       -> NOTIFY     (GATE 0 -> GATE 1: a worsening
                                                            blocker-shaped count -- alert)
    anything else (a real status change)   -> NOTIFY     (RUNNING -> FAIL, PARTIAL -> READY)

This is a real, disclosed, bounded assumption: every numeric dimension this module is actually
applied to (`blockers.critical_failures`/`blockers.critical_unknown`/`blockers.human_gates`, and
this module's own `critical_unknown_count()`) is a "how many things are currently wrong" count,
where an INCREASE is a regression worth an alert and a DECREASE is quiet progress -- the module
docstring on `classify_transition()` states this rather than leaving it implicit, since a
dimension where lower is worse (this repo has none among the ones wired here) would need the
opposite rule. `previous=None` (section 433 says nothing about it, but `notify_status_change()`
already establishes "unobserved" is itself worth reporting) is NOTIFY -- the very first observation
of a dimension is a real, reportable fact, matching `harness_status_ir.notify_status_change()`'s
own documented `UNOBSERVED -> current` convention.

`evaluate_status_bar_change()` walks a fixed, real set of status-bar-relevant dimensions
(`DEFAULT_NOTIFICATION_DIMENSIONS`, matching section 421's own Blocker Region plus the primary
Harness/Signoff/Freshness fields) across two real `HarnessStatusService` snapshots, classifying
each and firing `notify_status_change()` ONLY for the NOTIFY-classified ones -- a NOTIFY-worthy
transition is never silently dropped, and an UPDATE-classified one never reaches the transport,
matching section 433's own "status may refresh silently while notification follows change-only
policy" sentence literally.

FRESHNESS (section 434)
--------------------------
`apply_freshness_gate()` folds `harness.state` and `freshness.state` through the reused
`worst_harness_state()` -- so a STALE/UNKNOWN freshness signal can never be silently outranked by
a stale-but-still-recorded READY `harness.state`; the effective value can never read better than
the freshness signal permits. `freshness_gated_snapshot()` NEVER mutates the raw snapshot's own
`harness.state` (the raw, as-computed value stays inspectable, matching section 433's "status
rendering and notification are distinct" principle one level over -- raw computation and
freshness-gated presentation are also kept distinct) -- it only ADDS an `effective_harness_state`
key a renderer should prefer to display.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import escalation_notify
from . import harness_status as hs
from . import harness_status_ir as hir

__all__ = [
    "HarnessStatusPolicyError",
    "CRITICAL_STATUS_LEAF_PATHS",
    "STALE_ARTIFACT_LEAF_PATHS",
    "DEFAULT_NOTIFICATION_DIMENSIONS",
    "NO_CHANGE", "UPDATE", "NOTIFY",
    "fresh_unknown_snapshot",
    "find_unknown_status_fields",
    "critical_unknown_count",
    "unknown_evidence_gaps",
    "find_stale_artifacts",
    "assert_stale_artifacts_never_satisfy_signoff",
    "derive_stale_gated_signoff_state",
    "apply_freshness_gate",
    "freshness_gated_snapshot",
    "classify_transition",
    "evaluate_status_transition",
    "evaluate_status_bar_change",
]


class HarnessStatusPolicyError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


_MISSING = object()


def _as_snapshot(ir_or_dict: Any) -> Dict[str, Any]:
    """Accept either a real `harness_status.HarnessStatusIR` instance or an already-produced
    snapshot dict (the shape `HarnessStatusService.snapshot()`/`serve()` returns) -- every
    function in this module works on the dict shape internally, since that is the REAL,
    persistable/comparable shape two successive status-bar refreshes are naturally expressed in
    (state.json-shaped, JSON-round-trippable), and it lets this module stay correct whether a
    caller hands it a live dataclass or a snapshot read back off disk/a Blackboard topic."""
    if hasattr(ir_or_dict, "to_dict"):
        return ir_or_dict.to_dict()
    if isinstance(ir_or_dict, dict):
        return ir_or_dict
    raise HarnessStatusPolicyError("UNRECOGNIZED_HARNESS_STATUS_IR_SHAPE", {
        "type": type(ir_or_dict).__name__,
        "reason": "expected a harness_status.HarnessStatusIR instance (with .to_dict()) or an "
                  "already-produced snapshot dict"})


def _dget(snapshot: Dict[str, Any], path: str) -> Any:
    node: Any = snapshot
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def fresh_unknown_snapshot() -> Dict[str, Any]:
    """The reference "absence of evidence" snapshot, reusing `harness_status.HarnessStatusIR()`'s
    own default constructor verbatim (every status-bearing field of that dataclass already
    defaults to `"UNKNOWN"` -- this module invents no second all-unknown fixture). This is what a
    project this harness has read nothing about yet looks like, and it is the negative-control
    fixture this module's own tests build every UNKNOWN-honesty proof from."""
    return hs.HarnessStatusIR().to_dict()


# ===========================================================================
# Section 422: UNKNOWN POLICY
# ===========================================================================

#: Every leaf path here is one of `harness_status.HARNESS_STATUS_VALUES`-typed field in the real
#: `HarnessStatusIR` -- section 406's governed status vocabulary, as opposed to a plain identity/
#: baseline/count fact. Self-checked against the real shape at import
#: (`_assert_critical_paths_resolvable()`), so a future rename in `harness_status.py` fails this
#: module's own import loudly rather than silently under-counting critical UNKNOWNs.
CRITICAL_STATUS_LEAF_PATHS: Tuple[str, ...] = (
    "harness.state",
    "harness.readiness",
    "harness.signoff_state",
    "workflow.convergence_state",
    "execution.regression_state",
    "execution.simulation_state",
    "closure.requirement",
    "closure.vplan",
    "closure.functional_coverage",
    "closure.code_coverage",
    "closure.assertion",
    "closure.protocol",
    "closure.connectivity",
    "closure.performance",
    "closure.subsystem",
    "closure.system",
    "integration.compatibility_state",
    "resources.remote_execution",
    "resources.lsf",
    "resources.license",
    "resources.vcs",
    "resources.verdi",
    "resources.fsdb",
    "freshness.state",
)


def _assert_critical_paths_resolvable() -> None:
    fresh = fresh_unknown_snapshot()
    for path in CRITICAL_STATUS_LEAF_PATHS:
        value = _dget(fresh, path)
        if value is _MISSING:
            raise HarnessStatusPolicyError("CRITICAL_STATUS_PATH_UNRESOLVABLE", {
                "path": path,
                "reason": "harness_status.HarnessStatusIR no longer carries this field -- "
                          "CRITICAL_STATUS_LEAF_PATHS has drifted from the real IR shape"})
        if value not in hs.HARNESS_STATUS_VALUES:
            raise HarnessStatusPolicyError("CRITICAL_STATUS_PATH_NOT_STATUS_VALUED", {
                "path": path, "value": value,
                "reason": "this field's default value is not one of harness_status."
                          "HARNESS_STATUS_VALUES -- it is not a governed status field and does "
                          "not belong in CRITICAL_STATUS_LEAF_PATHS"})


_assert_critical_paths_resolvable()


def find_unknown_status_fields(
        ir_or_dict: Any,
        paths: Sequence[str] = CRITICAL_STATUS_LEAF_PATHS) -> List[Tuple[str, str]]:
    """Every one of `paths` whose CURRENT value is genuinely `"UNKNOWN"` in this snapshot --
    never cached, never defaulted, always re-derived from the real snapshot handed in."""
    snapshot = _as_snapshot(ir_or_dict)
    found: List[Tuple[str, str]] = []
    for path in paths:
        value = _dget(snapshot, path)
        if value == "UNKNOWN":
            found.append((path, value))
    return found


def critical_unknown_count(
        ir_or_dict: Any,
        paths: Sequence[str] = CRITICAL_STATUS_LEAF_PATHS) -> int:
    """Section 422's own hard invariant made a real, always-recomputed number: `UNKNOWN != 0`
    unless it genuinely is zero. Never a bare `blockers.critical_unknown` EvidenceField read back
    (that field is populated by a real subsystem read the aggregator performs elsewhere, per
    `harness_status_ir.FACT_SOURCE_CATALOG`'s own citation for it) -- this is the LIVE count over
    the snapshot actually in front of the caller right now."""
    return len(find_unknown_status_fields(ir_or_dict, paths))


def unknown_evidence_gaps(
        ir_or_dict: Any,
        paths: Sequence[str] = CRITICAL_STATUS_LEAF_PATHS) -> List[Dict[str, str]]:
    """Section 422: "Selecting/expanding UNKNOWN shall reveal affected items and evidence gaps."
    Reuses the real snapshot's own `unknowns` list (already populated, field by field, by every
    real gatherer in `GlobalStateAggregator.assemble()`) as the citation trail -- never a second,
    invented evidence-gap mechanism. Matching is deliberately tolerant of that list's own several
    real field-naming conventions (a bare section name, a full dotted path, a
    `"closure(<-row_id)"`-shaped citation) rather than requiring an exact string match, since this
    module must not silently drop a real gap merely because of a spelling difference between two
    sibling modules. A field with no matching entry at all is reported with an honest
    `"no recorded reason -- no aggregator gap citation found for this field"` rather than a
    fabricated one; that absence is itself real information about the aggregator's own
    bookkeeping."""
    snapshot = _as_snapshot(ir_or_dict)
    raw_unknowns = snapshot.get("unknowns") or []
    unknown_fields = [f.strip() for entry in raw_unknowns
                       if isinstance(entry, dict) for f in [str(entry.get("field") or "")] if f]
    reason_by_field: Dict[str, str] = {}
    for entry in raw_unknowns:
        if not isinstance(entry, dict):
            continue
        field = str(entry.get("field") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        if field:
            reason_by_field[field] = reason

    gaps: List[Dict[str, str]] = []
    for path, value in find_unknown_status_fields(ir_or_dict, paths):
        leaf = path.rsplit(".", 1)[-1]
        matched_reason = None
        for field, reason in reason_by_field.items():
            if field == path or path.endswith(field) or field.endswith(path) or leaf in field:
                matched_reason = reason
                break
        gaps.append({
            "field": path,
            "status": value,
            "reason": matched_reason or "no recorded reason -- no aggregator gap citation "
                      "found for this field",
        })
    return gaps


# ===========================================================================
# Section 423: STALE POLICY
# ===========================================================================

#: Section 423's own worked examples of "stale artifacts", mapped onto the real section-405
#: leaves that stand in for each one.
STALE_ARTIFACT_LEAF_PATHS: Tuple[str, ...] = (
    "execution.regression_state",     # "Tests"
    "execution.simulation_state",     # "Tests"
    "closure.functional_coverage",    # "Coverage Results"
    "closure.performance",            # "Performance Baselines"
    "closure.subsystem",              # "SubsystemVerificationContract"
    "closure.system",                 # "SystemIntegrationProof" / "SystemVerificationContract"
    "harness.signoff_state",          # "Signoff Evidence"
)


def find_stale_artifacts(
        ir_or_dict: Any,
        paths: Sequence[str] = STALE_ARTIFACT_LEAF_PATHS) -> List[str]:
    snapshot = _as_snapshot(ir_or_dict)
    return [path for path in paths if _dget(snapshot, path) == "STALE"]


def _validate_revalidated(revalidated: Optional[Dict[str, str]]) -> Dict[str, str]:
    """A revalidation must be EXPLICIT: a real, non-empty reason per path, mirroring
    `harness_status_ir.unknown_field()`'s own "a reason is required" discipline. A bare `True`,
    `None`, or empty-string entry is refused rather than silently treated as "not revalidated"
    (which would be a quiet, easy-to-miss failure mode for a caller who thought they had
    revalidated something) or as "revalidated" (which would defeat the whole policy)."""
    if not revalidated:
        return {}
    cleaned: Dict[str, str] = {}
    for path, reason in revalidated.items():
        if not isinstance(reason, str) or not reason.strip():
            raise HarnessStatusPolicyError("REVALIDATION_REQUIRES_A_REAL_REASON", {
                "path": path,
                "reason": "a revalidation entry must carry a real, non-empty reason string -- "
                          "section 423 requires staleness to be EXPLICITLY revalidated, never "
                          "implicitly cleared"})
        cleaned[path] = reason.strip()
    return cleaned


def assert_stale_artifacts_never_satisfy_signoff(
        ir_or_dict: Any,
        revalidated: Optional[Dict[str, str]] = None) -> None:
    """Section 423's hard rule, enforced: "STALE artifacts cannot satisfy current signoff unless
    explicitly revalidated." Raises `HarnessStatusPolicyError` when `harness.signoff_state` reads
    `SIGNOFF_READY` while at least one of the real STALE-artifact leaves is `STALE` and was not
    named, with a real reason, in `revalidated`."""
    snapshot = _as_snapshot(ir_or_dict)
    signoff_state = _dget(snapshot, "harness.signoff_state")
    if signoff_state != "SIGNOFF_READY":
        return
    cleaned = _validate_revalidated(revalidated)
    stale = find_stale_artifacts(snapshot)
    unrevalidated = [p for p in stale if p not in cleaned]
    if unrevalidated:
        raise HarnessStatusPolicyError("STALE_ARTIFACTS_BLOCK_SIGNOFF", {
            "signoff_state": signoff_state,
            "unrevalidated_stale_artifacts": unrevalidated,
            "reason": "one or more artifacts backing this signoff claim are STALE and have not "
                      "been explicitly revalidated (section 423)"})


def derive_stale_gated_signoff_state(
        ir_or_dict: Any,
        revalidated: Optional[Dict[str, str]] = None) -> str:
    """The non-raising counterpart of `assert_stale_artifacts_never_satisfy_signoff()`: returns
    the EFFECTIVE `harness.signoff_state` after applying section 423's gate -- `"STALE"` (never
    the raw `SIGNOFF_READY`) when at least one unrevalidated stale artifact exists, else the raw
    recorded value unchanged. Never mutates the snapshot it was handed."""
    snapshot = _as_snapshot(ir_or_dict)
    signoff_state = _dget(snapshot, "harness.signoff_state")
    if signoff_state != "SIGNOFF_READY":
        return signoff_state
    cleaned = _validate_revalidated(revalidated)
    stale = find_stale_artifacts(snapshot)
    unrevalidated = [p for p in stale if p not in cleaned]
    return "STALE" if unrevalidated else signoff_state


# ===========================================================================
# Section 434: STATUS FRESHNESS
# ===========================================================================

def apply_freshness_gate(ir_or_dict: Any) -> str:
    """Section 434: "Never preserve the last READY state indefinitely without freshness
    indication." Reuses `harness_status.worst_harness_state()` -- the SAME worst-wins fold and
    severity table section 409's own aggregator already uses for `harness.state` itself -- over
    `[harness.state, freshness.state]`. `STALE`/`UNKNOWN` already outrank `READY`/`SIGNOFF_READY`
    in that table, so a stale/unmeasured freshness signal folds the EFFECTIVE state at least that
    severe, never letting a stale-but-still-recorded READY surface unqualified."""
    snapshot = _as_snapshot(ir_or_dict)
    return hs.worst_harness_state([
        _dget(snapshot, "harness.state") if _dget(snapshot, "harness.state") is not _MISSING
        else None,
        _dget(snapshot, "freshness.state") if _dget(snapshot, "freshness.state") is not _MISSING
        else None,
    ])


def freshness_gated_snapshot(ir_or_dict: Any) -> Dict[str, Any]:
    """A COPY of the snapshot with one field added, `effective_harness_state`
    (`apply_freshness_gate()`'s own result) -- the raw `harness.state` is left completely
    untouched (raw computation and freshness-gated presentation stay independently inspectable,
    per section 433's own "status rendering and notification are distinct" principle applied one
    layer over). A renderer building the status bar should prefer `effective_harness_state`;
    anything reading the raw computed value for its own audit purposes still can."""
    snapshot = dict(_as_snapshot(ir_or_dict))
    snapshot["effective_harness_state"] = apply_freshness_gate(snapshot)
    return snapshot


# ===========================================================================
# Section 433: CHANGE-ONLY STATUS NOTIFICATION
# ===========================================================================

NO_CHANGE = "NO_CHANGE"
UPDATE = "UPDATE"
NOTIFY = "NOTIFY"

#: Section 421's Blocker Region plus the primary Harness/Signoff/Freshness fields -- the real,
#: fixed dimension set `evaluate_status_bar_change()` classifies by default. A caller may pass a
#: narrower or wider set; this is only the documented default.
DEFAULT_NOTIFICATION_DIMENSIONS: Tuple[str, ...] = (
    "harness.state",
    "harness.signoff_state",
    "freshness.state",
    "blockers.critical_failures",
    "blockers.critical_unknown",
    "blockers.human_gates",
)


def classify_transition(previous: Any, current: Any) -> str:
    """Section 433's own worked example table, recovered from one small, disclosed rule rather
    than four hand-coded special cases:

        previous == current                          -> NO_CHANGE  (PASS -> PASS)
        both numeric, current < previous              -> UPDATE     (UNKNOWN 3 -> UNKNOWN 2)
        both numeric, current > previous               -> NOTIFY     (GATE 0 -> GATE 1)
        anything else (a real categorical change)      -> NOTIFY     (RUNNING -> FAIL,
                                                                       PARTIAL -> READY)

    The numeric direction rule is a stated, bounded assumption: it treats every numeric dimension
    as a "how many things are currently wrong" count, where an INCREASE is a regression worth an
    alert and a DECREASE is quiet progress worth a silent refresh -- exactly true for every
    numeric dimension this module actually applies it to
    (`blockers.critical_failures`/`blockers.critical_unknown`/`blockers.human_gates`,
    `critical_unknown_count()`). A caller applying this to a numeric dimension where LOWER is
    worse would need the opposite rule; none of this module's own dimensions are that shape.
    `previous=None` (no prior observation on record at all) is always NOTIFY -- the same "the
    very first observation of a field is itself a change worth reporting" convention
    `harness_status_ir.notify_status_change()` already documents, reused here rather than
    re-decided -- except when `current` is also `None`, which is a genuine no-op."""
    if previous == current:
        return NO_CHANGE
    if previous is None:
        return NOTIFY
    is_prev_num = isinstance(previous, (int, float)) and not isinstance(previous, bool)
    is_curr_num = isinstance(current, (int, float)) and not isinstance(current, bool)
    if is_prev_num and is_curr_num:
        return UPDATE if current < previous else NOTIFY
    return NOTIFY


def evaluate_status_transition(
        dimension: str, previous: Any, current: Any,
        notifier: Optional[escalation_notify.EscalationNotifier] = None,
        title: Optional[str] = None, body: Optional[str] = None) -> Dict[str, Any]:
    """Classify one dimension's transition and, ONLY when it classifies NOTIFY and a real
    `notifier` was supplied, fire through `harness_status_ir.notify_status_change()` verbatim --
    no second notification code path. An UPDATE-classified transition never touches the notifier
    (section 433: "status may refresh silently") and is recorded with `notification: None` so a
    caller can see the refresh happened without a notification having been attempted."""
    classification = classify_transition(previous, current)
    result: Dict[str, Any] = {
        "dimension": dimension, "previous": previous, "current": current,
        "classification": classification,
    }
    if classification == NOTIFY and notifier is not None:
        event = hir.notify_status_change(
            notifier, dimension=dimension,
            previous=(str(previous) if previous is not None else None),
            current=str(current),
            title=title or f"DV Harness: {dimension} changed",
            body=body or f"{dimension}: {previous!r} -> {current!r}")
        result["notification"] = event.to_dict()
    else:
        result["notification"] = None
    return result


def evaluate_status_bar_change(
        previous_snapshot: Any, current_snapshot: Any,
        dimensions: Sequence[str] = DEFAULT_NOTIFICATION_DIMENSIONS,
        notifier: Optional[escalation_notify.EscalationNotifier] = None,
        critical_unknown_paths: Sequence[str] = CRITICAL_STATUS_LEAF_PATHS) -> List[Dict[str, Any]]:
    """Walk `dimensions` (default: section 421's Blocker Region plus the primary Harness/Signoff/
    Freshness fields) across two real `HarnessStatusService` snapshots (or `HarnessStatusIR`
    instances) and classify/notify each one via `evaluate_status_transition()`. Also always adds
    one synthetic `"critical_unknown_count"` dimension -- `critical_unknown_count()` recomputed
    on both snapshots -- so section 422's own "count shall be visible" and section 433's
    change-only rule are wired together rather than left as two separately-checked policies. A
    dimension absent from either snapshot is skipped with `classification: "UNRESOLVED"` rather
    than raising or silently treated as `NO_CHANGE`."""
    prev = _as_snapshot(previous_snapshot)
    curr = _as_snapshot(current_snapshot)
    results: List[Dict[str, Any]] = []
    for dimension in dimensions:
        prev_value = _dget(prev, dimension)
        curr_value = _dget(curr, dimension)
        if prev_value is _MISSING or curr_value is _MISSING:
            results.append({
                "dimension": dimension, "previous": None if prev_value is _MISSING else prev_value,
                "current": None if curr_value is _MISSING else curr_value,
                "classification": "UNRESOLVED", "notification": None,
            })
            continue
        results.append(evaluate_status_transition(dimension, prev_value, curr_value, notifier))

    results.append(evaluate_status_transition(
        "critical_unknown_count",
        critical_unknown_count(prev, critical_unknown_paths),
        critical_unknown_count(curr, critical_unknown_paths),
        notifier))
    return results
