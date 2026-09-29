"""dv_harness/build_remote_lsf_intake.py -- Build/Remote/LSF Intake resolution.

Section 31 asks for intake facts specific to build/remote-execution/LSF
readiness -- "is a build environment reachable, is LSF configured" -- to be
resolved as additional `intake_state.py`-shaped field records.

REUSE OVER REINVENT, checked before writing a line of this module. A
repo-wide grep for `build_remote_lsf`/`BuildRemoteLsf`/`remote_lsf_intake`
matched nothing, and neither `intake_state.py`, `intake_baseline.py`, nor
`verification_intake_contract.py` reference `preflight.py` at all --
confirmed real gap.

`intake_state.py`'s own `build_env` category is a DIFFERENT fact: it reads a
`connectivity.run_gate1_elaboration_check()` result (did the generated
testbench actually ELABORATE). This module answers the earlier, narrower
question section 31 names -- before any elaboration is attempted, is the
BUILD/SUBMISSION environment itself even usable: is the target host
reachable, is a real transport (local or the persistent remote relay)
actually confirmed, is the LSF queue Open:Active, is the EDA license server
up with headroom, is the workdir there and writable, is there enough disk,
are the required EDA env vars set. These are two structurally different
questions -- "can I compile" vs. "can I even submit a job" -- and this module
deliberately does not touch `intake_state.py`'s `build_env` field or its
`BLOCKING_CATEGORIES` list; see "Deliberately bounded" below.

No new probe is invented anywhere in this module. Every fact is read
straight off `preflight.py`'s own REAL, already-tested checks
(`preflight.run_preflight()`'s six `CheckOutcome`s: `eda_license`,
`lsf_queue_health`, `host_reachability`, `disk_space`, `workdir`,
`eda_env_vars`) and `preflight.resolve_transport()`'s own real,
evidence-based `TransportDecision` (a READY persistent relay for the
configured VCHOST/VCHOP hop, or `lmutil`/`bqueues` actually on PATH -- never
a guess). This module performs zero subprocess calls, zero network I/O, and
zero license/queue/relay probing of its own; it only maps an ALREADY-PRODUCED
`preflight.PreflightResult` / `preflight.TransportDecision` onto
`intake_state.IntakeFieldRecord`s in a new `"build_remote_lsf"` category, and
composes those records into an existing `intake_state.IntakeState` --
`intake_state.IntakeFieldRecord`/`IntakeFieldStatus`/`IntakeState` are
imported and used verbatim, never re-typed.

Status mapping, per real `CheckOutcome.status`:
  - PASS -> AUTO_RESOLVED (confidence HIGH): a real check ran and passed.
  - FAIL -> BLOCKED (confidence HIGH): real evidence says this field cannot
    proceed, mirroring `preflight.py`'s own "沒過就 BLOCKED" rule.
  - SKIP -> MISSING (confidence UNKNOWN): the check genuinely did not run
    (e.g. no workdir configured). Per the Evidence Truth Rule this is never
    promoted to NOT_APPLICABLE here -- `intake_state.py`'s own module
    docstring is explicit that NOT_APPLICABLE is reserved for a caller's
    OWN explicit "this does not apply to this project" declaration, and
    "inferring 'not applicable' from mere absence is exactly the
    silent-default the Evidence Truth Rule forbids". A SKIP is absence of a
    result, not a caller's declared exemption, so it stays MISSING.
  - an unrecognized status string -> UNKNOWN (confidence UNKNOWN): evidence
    was supplied but is inconclusive.
  - no `CheckOutcome` supplied for that field at all -> MISSING.

`remote_transport_available` is the one field NOT sourced from a
`CheckOutcome` -- it reads `preflight.TransportDecision` instead (the real
answer to "is there a way to reach the build/submission host at all", which
sits one layer BELOW `host_reachability`'s own check, since that check itself
runs THROUGH whichever transport `resolve_transport()` picked). A resolved
`local`/`remote_relay` transport that is `available` maps to AUTO_RESOLVED.
An EXPLICIT `off` request (a caller's own real "transport is out of scope for
this deployment" declaration -- the exact shape `intake_state.py`'s own
NOT_APPLICABLE exception describes) maps to NOT_APPLICABLE. A malformed
transport REQUEST (an unrecognized transport string in config/CLI -- real
evidence of a broken configuration, distinguishable via the decision's own
`evidence["unknown_transport"]` key) maps to BLOCKED. Anything else -- `auto`
probed and found nothing usable -- maps to MISSING (we could not confirm a
transport; per `resolve_transport()`'s own docstring this is deliberately
never read as a confirmed absence, exactly as `preflight.py`'s degradation
reasoning already argues for "command not found" never becoming a
fabricated DEGRADED verdict).

Deliberately bounded, and stated rather than implied closed. This module
JOINS and REPORTS, exactly like `intake_state.py` itself: it runs no probe,
files no question, writes no state/blackboard/approval record, and holds no
stage gate of its own. It also does NOT edit `intake_state.py` --
`BLOCKING_CATEGORIES`/`evaluate_uvm_generation_ready()` are left untouched, so
the new `"build_remote_lsf"` category does not (yet) block UVM_GENERATION_READY
by itself; a caller who wants that composes `merge_into_intake_state()`'s
result into whatever gate ultimately runs `evaluate_uvm_generation_ready()`
and reads this category separately via `evaluate_build_remote_lsf_readiness()`
/ `IntakeState.category_status("build_remote_lsf")`. This mirrors the
"REACHED, not WIRED" disclosure many sibling modules in this codebase already
carry for the identical reason: `intake_state.py` is a live, extensively-used
core file, and adding a category to its own hard-coded blocking list is a
separate, deliberate policy decision this task's own scope does not include.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from . import intake_state
from . import preflight
from . import question_queue

SCHEMA_VERSION = "1.0"

#: The category every field this module produces is recorded under.
CATEGORY = "build_remote_lsf"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- field <-> real preflight.py check name mapping -------------------------

#: `intake_state` field name -> the real `preflight.CheckOutcome.name` it is
#: read from. Every one of these six names is a real check
#: `preflight._ALL_CHECKS` already runs; nothing here invents a seventh.
FIELD_TO_CHECK_NAME: Dict[str, str] = {
    "eda_license_available": "eda_license",
    "lsf_configured": "lsf_queue_health",
    "build_environment_reachable": "host_reachability",
    "disk_space_sufficient": "disk_space",
    "workdir_ready": "workdir",
    "eda_env_vars_configured": "eda_env_vars",
}

#: The one field sourced from `preflight.TransportDecision` rather than a
#: `CheckOutcome`.
TRANSPORT_FIELD_NAME = "remote_transport_available"

#: Every field name this module can produce, in a fixed, stable order.
FIELD_NAMES = tuple(FIELD_TO_CHECK_NAME) + (TRANSPORT_FIELD_NAME,)


# ---- CheckOutcome -> IntakeFieldRecord ---------------------------------------

def _reason_from_outcome(outcome: preflight.CheckOutcome) -> str:
    reason = outcome.detail or ""
    if outcome.command:
        reason = f"{reason} (command: {outcome.command})" if reason else f"command: {outcome.command}"
    return reason


def _field_from_check_outcome(
    field_name: str,
    outcome: Optional[preflight.CheckOutcome],
    *,
    owner: Optional[str] = None,
) -> intake_state.IntakeFieldRecord:
    check_name = FIELD_TO_CHECK_NAME[field_name]
    source = f"preflight:{check_name}"
    if outcome is None:
        return intake_state.IntakeFieldRecord(
            field=field_name, category=CATEGORY, value=None, source=source,
            confidence="UNKNOWN", status=intake_state.IntakeFieldStatus.MISSING.value, owner=owner,
            reason=f"no preflight.CheckOutcome named {check_name!r} supplied "
                   f"(real source: preflight.run_preflight())",
        )
    status_raw = (outcome.status or "").strip().upper()
    reason = _reason_from_outcome(outcome)
    if status_raw == "PASS":
        return intake_state.IntakeFieldRecord(
            field=field_name, category=CATEGORY, value=outcome.status, source=source,
            confidence="HIGH", status=intake_state.IntakeFieldStatus.AUTO_RESOLVED.value,
            owner=owner, reason=reason,
        )
    if status_raw == "FAIL":
        return intake_state.IntakeFieldRecord(
            field=field_name, category=CATEGORY, value=outcome.status, source=source,
            confidence="HIGH", status=intake_state.IntakeFieldStatus.BLOCKED.value,
            owner=owner, reason=reason,
        )
    if status_raw == "SKIP":
        # A real, deliberate "this check did not run" -- absence of a
        # result, never a caller's own declared exemption. See module
        # docstring: never silently promoted to NOT_APPLICABLE.
        return intake_state.IntakeFieldRecord(
            field=field_name, category=CATEGORY, value=outcome.status, source=source,
            confidence="UNKNOWN", status=intake_state.IntakeFieldStatus.MISSING.value,
            owner=owner, reason=reason or "preflight check skipped",
        )
    # An unrecognized status string is real evidence, just inconclusive.
    return intake_state.IntakeFieldRecord(
        field=field_name, category=CATEGORY, value=outcome.status, source=source,
        confidence="UNKNOWN", status=intake_state.IntakeFieldStatus.UNKNOWN.value,
        owner=owner, reason=f"unrecognized preflight check status {outcome.status!r}",
    )


# ---- TransportDecision -> IntakeFieldRecord ----------------------------------

def _field_from_transport_decision(
    decision: Optional[preflight.TransportDecision],
    *,
    owner: Optional[str] = None,
) -> intake_state.IntakeFieldRecord:
    source = "preflight:resolve_transport"
    field_name = TRANSPORT_FIELD_NAME
    if decision is None:
        return intake_state.IntakeFieldRecord(
            field=field_name, category=CATEGORY, value=None, source=source,
            confidence="UNKNOWN", status=intake_state.IntakeFieldStatus.MISSING.value, owner=owner,
            reason="no preflight.TransportDecision supplied "
                   "(real source: preflight.resolve_transport())",
        )
    if decision.resolved == preflight.TRANSPORT_OFF:
        # A caller's own explicit "transport is out of scope for this
        # deployment" -- the real exception intake_state.py's own
        # NOT_APPLICABLE docstring describes.
        return intake_state.IntakeFieldRecord(
            field=field_name, category=CATEGORY, value=decision.resolved, source=source,
            confidence="HIGH", status=intake_state.IntakeFieldStatus.NOT_APPLICABLE.value,
            owner=owner, reason=decision.reason,
        )
    if isinstance(decision.evidence, dict) and "unknown_transport" in decision.evidence:
        # A real config defect (a typo'd transport name), not a mere probe
        # miss -- real evidence this field cannot proceed as configured.
        return intake_state.IntakeFieldRecord(
            field=field_name, category=CATEGORY, value=decision.resolved, source=source,
            confidence="HIGH", status=intake_state.IntakeFieldStatus.BLOCKED.value,
            owner=owner, reason=decision.reason,
        )
    if decision.resolved in (preflight.TRANSPORT_LOCAL, preflight.TRANSPORT_REMOTE_RELAY) and decision.available:
        return intake_state.IntakeFieldRecord(
            field=field_name, category=CATEGORY, value=decision.resolved, source=source,
            confidence="HIGH", status=intake_state.IntakeFieldStatus.AUTO_RESOLVED.value,
            owner=owner, reason=decision.reason,
        )
    # resolved == TRANSPORT_NONE (auto probed, nothing usable confirmed): an
    # absence of confirmation, never read as a confirmed negative.
    return intake_state.IntakeFieldRecord(
        field=field_name, category=CATEGORY, value=decision.resolved, source=source,
        confidence="UNKNOWN", status=intake_state.IntakeFieldStatus.MISSING.value,
        owner=owner, reason=decision.reason,
    )


# ---- normalization: accept a real PreflightResult, or its .to_dict() --------

def _checks_by_name(preflight_result: Any) -> Dict[str, preflight.CheckOutcome]:
    """Normalizes `preflight_result` (a real `preflight.PreflightResult`, or a
    plain dict shaped like its own `to_dict()`) into a `{check_name:
    CheckOutcome}` map. Never invents a check: an unrecognized shape raises
    rather than silently producing an empty map."""
    if preflight_result is None:
        return {}
    if isinstance(preflight_result, preflight.PreflightResult):
        checks = preflight_result.checks
    elif isinstance(preflight_result, dict):
        raw_checks = preflight_result.get("checks")
        if raw_checks is None:
            raise TypeError(
                "preflight_result dict carries no 'checks' key -- expected the shape "
                "produced by preflight.PreflightResult.to_dict()")
        checks = []
        for c in raw_checks:
            if isinstance(c, preflight.CheckOutcome):
                checks.append(c)
            elif isinstance(c, dict):
                checks.append(preflight.CheckOutcome(
                    name=c.get("name"), status=c.get("status"), detail=c.get("detail") or "",
                    command=c.get("command"), evidence=c.get("evidence"),
                ))
            else:
                raise TypeError(f"unrecognized check entry shape: {type(c).__name__}")
    else:
        raise TypeError(
            f"preflight_result must be a preflight.PreflightResult, a dict shaped like "
            f"its to_dict(), or None -- got {type(preflight_result).__name__}")
    return {c.name: c for c in checks}


# ---- top-level builder --------------------------------------------------------

def fields_from_preflight(
    preflight_result: Any = None,
    transport_decision: Optional[preflight.TransportDecision] = None,
    *,
    owner: Optional[str] = None,
) -> List[intake_state.IntakeFieldRecord]:
    """Builds every `"build_remote_lsf"`-category `IntakeFieldRecord` this
    module produces, joining a real `preflight.run_preflight()` result and a
    real `preflight.resolve_transport()` decision. Both are optional and
    independently absent-able: a caller with only one, or neither, still gets
    a real, honest set of records (every field MISSING, never fabricated).

    `owner` defaults to `question_queue.route_owner("env")` -- the same
    DV-owner routing `intake_state.py` itself already uses for its
    `build_env`/`critical_bind` fields, since build/remote/LSF readiness is
    infrastructure, not a DUT/VIP content question."""
    resolved_owner = owner if owner is not None else question_queue.route_owner("env")
    by_name = _checks_by_name(preflight_result)
    records: List[intake_state.IntakeFieldRecord] = []
    for field_name in FIELD_TO_CHECK_NAME:
        check_name = FIELD_TO_CHECK_NAME[field_name]
        records.append(_field_from_check_outcome(field_name, by_name.get(check_name), owner=resolved_owner))
    records.append(_field_from_transport_decision(transport_decision, owner=resolved_owner))
    return records


def merge_into_intake_state(
    state: intake_state.IntakeState,
    preflight_result: Any = None,
    transport_decision: Optional[preflight.TransportDecision] = None,
    *,
    owner: Optional[str] = None,
) -> intake_state.IntakeState:
    """Returns a NEW `IntakeState` carrying every field `state` already had
    PLUS this module's own `"build_remote_lsf"` fields -- `state` itself is
    never mutated. A field-name collision (this module re-run against a
    state that already carries one of its own field names) raises via
    `IntakeState`'s own real duplicate-field check, exactly as any other
    caller collision would."""
    new_records = fields_from_preflight(preflight_result, transport_decision, owner=owner)
    return intake_state.IntakeState(list(state.records) + new_records, generated_at=state.generated_at)


# ---- category-scoped readiness (deliberately NOT UVM_GENERATION_READY) ------

@dataclass
class BuildRemoteLsfReadiness:
    """The `"build_remote_lsf"` category's own worst-wins verdict -- scoped
    to exactly the fields this module produces, computed via
    `intake_state.IntakeState.category_status()` (reused, never
    re-implemented). This is deliberately NOT
    `intake_state.evaluate_uvm_generation_ready()`: that gate's
    `BLOCKING_CATEGORIES` list is untouched by this module (see module
    docstring's "Deliberately bounded")."""
    ready: bool
    status: str
    fields: List[dict]
    checked_at: str

    def to_dict(self) -> dict:
        return {"ready": self.ready, "status": self.status, "fields": self.fields, "checked_at": self.checked_at}


def evaluate_build_remote_lsf_readiness(
    records: Sequence[intake_state.IntakeFieldRecord],
    *,
    now: Optional[str] = None,
) -> BuildRemoteLsfReadiness:
    """`ready` is True iff every field's status is in
    `intake_state.NON_BLOCKING_STATUSES` (AUTO_RESOLVED / USER_CONFIRMED /
    NOT_APPLICABLE) -- the identical non-blocking vocabulary
    `evaluate_uvm_generation_ready()` uses one layer up, reused rather than
    re-derived. Records not in `CATEGORY` are ignored (a caller may pass a
    whole `IntakeState.records` list; only this module's own fields are
    folded)."""
    scoped = [r for r in records if r.category == CATEGORY]
    state = intake_state.IntakeState(scoped, generated_at=now)
    status = state.category_status(CATEGORY)
    ready = status in intake_state.NON_BLOCKING_STATUSES
    return BuildRemoteLsfReadiness(
        ready=ready, status=status, fields=[r.to_dict() for r in scoped],
        checked_at=now or _utcnow_iso(),
    )
