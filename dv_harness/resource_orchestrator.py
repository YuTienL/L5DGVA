"""Global cross-job / cross-project EDA resource orchestration (VI-5).

WHAT WAS MISSING, AND WHAT WAS ALREADY REAL
-------------------------------------------
Re-verified by direct search on 2026-09-06 before any of this was written.
Three real mechanisms already existed, and none of them was -- or structurally
could be -- a cross-job arbiter:

  * `preflight.check_license()` / `check_queue_health()` are real probes (a
    real `lmutil lmstat -a -c <server>` parse and a real `bqueues <queue>`
    parse). They answer "may THIS submission proceed" and nothing about who
    else is asking.
  * `lsf_client.bsub_submit_with_preflight()` runs those checks in front of ONE
    `bsub` and blocks that one submission on a FAIL.
  * `loop_budget.prioritize_stage()` (LOOP-3, section 92) added the deferral
    half for ONE loop: under measured pressure, a non-critical stage that
    consumes the scarce resource is DEFERRED. It takes one stage and one
    pressure reading and has no argument through which a second job could ever
    be visible to it.

A repo-wide grep for `cross_job` / `arbitrat` / `global_resource` /
`resource_orchestr` / `multi_job` / `concurrent_jobs` over `dv_harness/` and
`tools/` returned only AMBA bus-arbitration text, SoC shared-VIP ownership
(`system_resource_inventory.py` / `system_resource_registry.py` /
`system_scheduling_plan.py` -- a different domain entirely: VIP/agent/BFM
composition, not license seats or farm slots) and gate names. Nothing ranked
two jobs against one measured pool.

So the missing decision is exactly this: given N concurrent contenders and ONE
measured license/queue capacity, WHICH of them proceeds now and which waits.
`prioritize_stage()` structurally cannot answer it -- under `PRESSURE_NONE` it
returns PROCEED for every contender, so ten jobs and two free license seats is
ten PROCEEDs. Turning a measured capacity into a BOUNDED grant set is the
cross-job half, and it is all this module adds.

WHAT THIS MODULE IS NOT
-----------------------
  * It is not a second license or queue probe. Every resource fact arrives as
    a real `preflight.CheckOutcome` -- supplied by the caller, or obtained
    through `degradation.probe_resources()` when a transport is explicitly
    injected. Nothing here shells out to `lmutil` or `bqueues`.
  * It is not a second pressure classifier. `loop_budget.pressure_from_checks()`
    is CALLED, so this module and the engine's own section-92 deferral can
    never disagree about whether the farm is under pressure.
  * It is not a second single-loop priority rule. `loop_budget.prioritize_stage()`
    is CALLED per contender; its PROCEED / PROCEED_CRITICAL / DEFER verdict is
    carried through verbatim, reason included.
  * It is not a submitter and not a gate. A GRANT authorizes nothing: it says
    only "of the contenders asking, this one is next", and every existing gate
    -- `preflight.run_preflight()`, `bsub_submit_with_preflight()`'s
    `PreflightBlockedError`, `policy.can_signoff()`, `ControlPlane.approve()`,
    the PR-only main/master governance -- still stands in front of any real
    work exactly as before. Nothing in this module submits, kills or modifies a
    job, and it holds no lock: a GRANT is advice a caller may act on, not a
    reservation.
  * It is not a second project registry. Cross-project contenders are built
    from `cross_project_mining.ProjectRegistry`, the registry this codebase
    already has, including its `ProjectIdentityCollisionError` guard against
    one store registered twice manufacturing a two-project consensus.

Reading is never a mutating act: no state, control, approval or memory record
is written, no `MemoryStore`/`StateStore` is constructed, and a project with no
`state.json` is reported as having none rather than having one minted for it.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import loop_budget, preflight

# ==========================================================================
# Vocabulary
# ==========================================================================
#: The three cross-job outcomes. Deliberately distinct tokens from
#: `models.Status` (a stage-gate VERDICT vocabulary) and from
#: `loop_budget.PRIORITY_*` (a single-loop decision this module CONSUMES) --
#: an allocation is a third kind of fact and collapsing it into either would
#: make an "is this granted" test read a stage verdict.
ALLOCATION_GRANTED = "GRANTED"
#: Eligible, and out-ranked. This is the value that exists ONLY at this level:
#: no per-job check can produce it, because it is a statement about the other
#: contenders.
ALLOCATION_QUEUED = "QUEUED"
#: `loop_budget.prioritize_stage()` itself said DEFER. Carried through
#: unchanged; this module never overturns it in either direction.
ALLOCATION_DEFERRED = "DEFERRED"

ALLOCATION_DECISIONS = (ALLOCATION_GRANTED, ALLOCATION_QUEUED, ALLOCATION_DEFERRED)

#: Ranking tiers, best first. Derived from `prioritize_stage()`'s verdict, not
#: re-decided here.
_TIER_BY_PRIORITY = {
    loop_budget.PRIORITY_PROCEED_CRITICAL: 0,
    loop_budget.PRIORITY_PROCEED: 1,
}

#: An LSF `STAT` that still occupies a farm slot. Resolved through
#: `lsf_client.map_bjobs_stat_to_lsf_status()` rather than matched here, so
#: there is one mapping from a raw bjobs STAT to a status in this codebase.
_OCCUPYING_STATUSES = ("PEND", "RUN")

#: Printed on every plan. A grant is a ranking statement, never permission --
#: see this module's own "WHAT THIS MODULE IS NOT".
PLAN_DISCLOSURE = (
    "An allocation ranks contenders against ONE measured capacity. It "
    "authorizes nothing: every existing preflight/approval gate still stands "
    "in front of any real work, a GRANTED contender whose own preflight is "
    "BLOCKED stays blocked, and nothing here submits, kills or reserves a job."
)


class ResourceOrchestratorError(ValueError):
    """A malformed request set. Raised rather than silently arbitrated, since
    a request this module could not read is a contender it would have left out
    of a plan that looks complete."""


# ==========================================================================
# Contenders
# ==========================================================================
@dataclass
class ResourceRequest:
    """One unit of work asking for scarce EDA resource, from some project.

    `consumes_scarce_resource` is the caller's fact, decided the same way
    `loop_budget.prioritize_stage()`'s own caller decides it -- from the graph
    node's declared execution-layer skills
    (`engine.DVHarness.EXECUTION_PREFLIGHT_SKILLS`) -- never from a stage-name
    guess here. `requested_at` is an ISO-8601 timestamp used only for FIFO
    tie-breaking; a request that declares none can never jump ahead of one that
    does."""
    project_id: str
    stage: str
    consumes_scarce_resource: bool
    root: str = ""
    requested_at: str = ""
    slots_requested: int = 1
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _coerce_request(obj: Any) -> ResourceRequest:
    if isinstance(obj, ResourceRequest):
        req = obj
    elif isinstance(obj, dict):
        missing = [k for k in ("project_id", "stage") if not obj.get(k)]
        if missing:
            raise ResourceOrchestratorError(
                f"resource request is missing required field(s) {missing}: {obj!r}")
        if "consumes_scarce_resource" not in obj:
            raise ResourceOrchestratorError(
                "resource request must state consumes_scarce_resource explicitly -- "
                "defaulting it either way would either defer analysis work that frees "
                f"nothing, or grant execution work no capacity was checked for: {obj!r}")
        req = ResourceRequest(
            project_id=str(obj["project_id"]),
            stage=str(obj["stage"]),
            consumes_scarce_resource=bool(obj["consumes_scarce_resource"]),
            root=str(obj.get("root") or ""),
            requested_at=str(obj.get("requested_at") or ""),
            # `or 1` would silently turn a declared 0 into a 1 and let the
            # refusal below never fire, so an absent key and a declared 0 are
            # kept apart here.
            slots_requested=int(1 if obj.get("slots_requested") is None
                                else obj["slots_requested"]),
            note=str(obj.get("note") or ""))
    else:
        raise ResourceOrchestratorError(
            f"resource request must be a ResourceRequest or a dict, got {type(obj).__name__}")
    if req.slots_requested < 1:
        raise ResourceOrchestratorError(
            f"slots_requested must be >= 1 (got {req.slots_requested}) for "
            f"{req.project_id}/{req.stage}: a zero-slot request would be granted "
            "unconditionally while still consuming the scarce resource.")
    return req


# ==========================================================================
# Measured farm capacity
# ==========================================================================
@dataclass
class FarmCapacity:
    """How much scarce resource is measurably free RIGHT NOW, and from which
    real check each number came.

    Every field is Optional and every None carries a reason in `sources`. A
    capacity nobody measured must never read as zero -- that would defer every
    job on the farm on the strength of a missing binary, the mirror image of
    the "do not invent availability" rule `loop_budget.pressure_from_checks()`
    already applies in the other direction."""
    queue: str = ""
    queue_status: Optional[str] = None
    license_feature: Optional[str] = None
    license_issued: Optional[int] = None
    license_in_use: Optional[int] = None
    license_free_seats: Optional[int] = None
    queue_max_jobs: Optional[int] = None
    queue_jobs_on_queue: Optional[int] = None
    queue_slots_free: Optional[int] = None
    per_user_job_limit: Optional[int] = None
    live_jobs_observed: Optional[int] = None
    slots_available: Optional[int] = None
    binding_constraint: Optional[str] = None
    sources: Dict[str, Any] = field(default_factory=dict)

    @property
    def measured(self) -> bool:
        return self.slots_available is not None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["measured"] = self.measured
        return d


def _scarcest_license_feature(raw_lmstat: str) -> Tuple[Optional[str], Optional[Dict[str, int]]]:
    """The configured feature with the FEWEST free seats, parsed by preflight's
    own `parse_license_availability()`.

    Scarcest, not summed: a run needs every feature it uses, so the pool that
    bounds how many more jobs can start is the tightest one. This mirrors
    `loop_budget._license_headroom()`'s `min()` over the same parse, kept
    consistent on purpose -- headroom and free seats disagreeing about which
    feature is the binding one would be two answers to one question."""
    if not raw_lmstat:
        return None, None
    try:
        parsed = preflight.parse_license_availability(raw_lmstat)
    except Exception:
        return None, None
    features = (parsed or {}).get("features") or {}
    best_name, best_val, best_free = None, None, None
    for name, val in features.items():
        if not isinstance(val, dict) or val.get("issued") is None:
            continue
        free = int(val["issued"]) - int(val.get("in_use") or 0)
        if best_free is None or free < best_free:
            best_name, best_val, best_free = name, val, free
    return best_name, best_val


def capacity_from_checks(checks: Sequence[Any], *,
                         queue: str = "",
                         live_jobs: Optional[Sequence[Dict[str, Any]]] = None
                         ) -> FarmCapacity:
    """Derive the measured capacity from REAL `preflight.CheckOutcome`s.

    The same evidence-based arming rule the rest of this codebase uses: a check
    that FAILed, SKIPped, or was never run contributes NO capacity number and
    says why. A FAIL is deliberately not "zero seats" either -- a jammed queue
    or a starved license pool is `PRESSURE_CRITICAL`, which
    `loop_budget.pressure_from_checks()` already reports and every contender
    then reads through `prioritize_stage()`; restating it as a capacity of 0
    would double-count one fact.

    `live_jobs` is `lsf_client.discover_live_jobs()`'s real output when a
    caller has it. It is recorded as an OBSERVATION and never subtracted from
    the license or queue numbers: lmstat's `in_use` and bqueues' `NJOBS`
    already count those same running jobs, so subtracting them again would
    manufacture scarcity."""
    cap = FarmCapacity(queue=queue or "")
    sources: Dict[str, Any] = {}
    saw_license = False
    saw_queue = False

    for outcome in checks or []:
        name = getattr(outcome, "name", None)
        status = getattr(outcome, "status", None)
        detail = getattr(outcome, "detail", "") or ""
        raw = getattr(outcome, "evidence", None) or ""
        if name == "eda_license":
            saw_license = True
            sources["license"] = {"check": name, "status": status, "detail": detail[:300]}
            if status != "PASS":
                sources["license"]["free_seats_reason"] = (
                    f"eda_license did not PASS (status={status}), so no free-seat count is "
                    "claimed. Pressure, not capacity, is how a FAIL reaches a contender.")
                continue
            feat, val = _scarcest_license_feature(raw)
            if val is None:
                sources["license"]["free_seats_reason"] = (
                    "eda_license PASSed but carried no parseable issued/in-use counts, so the "
                    "real free-seat count is unknown.")
                continue
            cap.license_feature = feat
            cap.license_issued = int(val["issued"])
            cap.license_in_use = int(val.get("in_use") or 0)
            cap.license_free_seats = max(0, cap.license_issued - cap.license_in_use)
            sources["license"]["scarcest_feature"] = feat
        elif name == "lsf_queue_health":
            saw_queue = True
            sources["queue"] = {"check": name, "status": status, "detail": detail[:300]}
            if status != "PASS":
                sources["queue"]["slots_free_reason"] = (
                    f"lsf_queue_health did not PASS (status={status}), so no queue-slot count "
                    "is claimed.")
                continue
            qname = queue or _queue_name_from_detail(detail)
            row = preflight.parse_queue_capacity(raw, qname) if (raw and qname) else None
            if row is None:
                sources["queue"]["slots_free_reason"] = (
                    "lsf_queue_health PASSed but carried no parseable bqueues row for queue "
                    f"{qname!r}, so the real queue capacity is unknown.")
                continue
            cap.queue = qname
            cap.queue_status = row.get("status")
            cap.queue_max_jobs = row.get("MAX")
            cap.queue_jobs_on_queue = row.get("NJOBS")
            cap.per_user_job_limit = row.get("JL/U")
            if cap.queue_max_jobs is None:
                sources["queue"]["slots_free_reason"] = (
                    "bqueues reports no MAX for this queue (LSF '-' means no limit), so the "
                    "queue imposes no measurable bound. Reading '-' as 0 would defer every "
                    "job on the farm.")
            else:
                cap.queue_slots_free = max(
                    0, int(cap.queue_max_jobs) - int(cap.queue_jobs_on_queue or 0))

    if not saw_license:
        sources["license"] = {"free_seats_reason":
                              "no eda_license outcome was supplied -- nothing was measured."}
    if not saw_queue:
        sources["queue"] = {"slots_free_reason":
                            "no lsf_queue_health outcome was supplied -- nothing was measured."}

    if live_jobs is not None:
        cap.live_jobs_observed = sum(
            1 for j in live_jobs if _occupies_slot(j))
        sources["live_jobs"] = {
            "producer": "lsf_client.discover_live_jobs()",
            "records": len(list(live_jobs)),
            "occupying": cap.live_jobs_observed,
            "note": ("observed only, never subtracted -- lmstat in_use and bqueues NJOBS "
                     "already count these same jobs."),
        }
    else:
        sources["live_jobs"] = {"note": "no live LSF listing supplied; per-project held-slot "
                                        "fairness ranking is inert on this plan."}

    bounds = [(n, v) for n, v in (("license_free_seats", cap.license_free_seats),
                                  ("queue_slots_free", cap.queue_slots_free))
              if v is not None]
    if bounds:
        cap.binding_constraint, cap.slots_available = min(bounds, key=lambda kv: kv[1])
    else:
        sources["slots_available_reason"] = (
            "neither a license free-seat count nor a queue slot count was measured, so no "
            "capacity bound is claimed. Section 92's rule applied in the scarcity direction: "
            "do not invent scarcity either.")
    cap.sources = sources
    return cap


_QUEUE_IN_DETAIL_RE = re.compile(r"queue '([^']+)'")


def _queue_name_from_detail(detail: str) -> str:
    """The queue name out of `check_queue_health()`'s own detail string, for a
    caller that supplied outcomes without also naming the queue. The check
    formats it as `queue '<name>' status=...`, so this reads the check's own
    word rather than guessing a default."""
    m = _QUEUE_IN_DETAIL_RE.search(detail or "")
    return m.group(1) if m else ""


def _occupies_slot(job: Dict[str, Any]) -> bool:
    """Whether this live record still holds a farm slot.

    The raw bjobs STAT is mapped through `lsf_client`'s OWN
    `map_bjobs_stat_to_lsf_status()`, so there is one translation from a STAT
    to a status in this codebase and a DONE/EXIT job is never counted as
    occupying. Imported lazily to keep this module's import graph free of the
    submission path it must never reach."""
    from .lsf_client import map_bjobs_stat_to_lsf_status
    return map_bjobs_stat_to_lsf_status(job.get("stat")) in _OCCUPYING_STATUSES


# ==========================================================================
# Per-project farm occupancy (the anti-monopoly signal)
# ==========================================================================
def registered_job_ids(root) -> List[int]:
    """The LSF job ids THIS project has registered on disk.

    Read straight off `lsf_client.JOBS_DIR_NAME` (the directory
    `bsub_submit()` / `register_external_job()` really write into), by
    filename, so no `JobState` is loaded and nothing is created in a project
    that has never submitted anything."""
    from .lsf_client import JOBS_DIR_NAME
    d = Path(root).joinpath(*JOBS_DIR_NAME)
    if not d.is_dir():
        return []
    out: List[int] = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(int(p.stem))
        except ValueError:
            continue
    return out


def held_slots_by_project(requests: Sequence[ResourceRequest],
                          live_jobs: Optional[Sequence[Dict[str, Any]]]
                          ) -> Dict[str, Optional[int]]:
    """How many farm slots each contending project is ALREADY holding.

    The intersection of that project's own registered job ids with the real
    `bjobs` listing, counting only PEND/RUN. This is the fact that exists only
    at this level: a project already running eight jobs and one running none
    are not equally entitled to the next free seat, and no per-job check can
    see the difference.

    Every value is None when no live listing was supplied -- "nobody looked" is
    not "this project holds nothing", and the ranking treats a None as inert
    rather than as a zero that would win ties."""
    if live_jobs is None:
        return {r.project_id: None for r in requests}
    live_ids = {j.get("job_id") for j in live_jobs if _occupies_slot(j)}
    held: Dict[str, Optional[int]] = {}
    for r in requests:
        # A project whose request names no root has no jobs directory to
        # intersect, so its count stays None. A count already computed from a
        # sibling request's root is never overwritten by that None -- otherwise
        # the answer would depend on request order.
        if not r.root:
            held.setdefault(r.project_id, None)
            continue
        held[r.project_id] = len(set(registered_job_ids(r.root)) & live_ids)
    return held


# ==========================================================================
# Arbitration
# ==========================================================================
@dataclass
class Allocation:
    """One contender's cross-job outcome, with every input that produced it."""
    project_id: str
    stage: str
    decision: str
    rank: Optional[int]
    reason: str
    priority: str
    priority_reason: str
    slots_requested: int
    held_slots: Optional[int] = None
    requested_at: str = ""
    consumes_scarce_resource: bool = True

    @property
    def granted(self) -> bool:
        return self.decision == ALLOCATION_GRANTED

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["granted"] = self.granted
        return d


@dataclass
class ArbitrationPlan:
    pressure: Dict[str, Any]
    capacity: Dict[str, Any]
    allocations: List[Allocation]
    slots_committed: int
    ranking_rule: List[str]
    disclosure: str = PLAN_DISCLOSURE

    def by_decision(self, decision: str) -> List[Allocation]:
        return [a for a in self.allocations if a.decision == decision]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pressure": self.pressure,
            "capacity": self.capacity,
            "allocations": [a.to_dict() for a in self.allocations],
            "slots_committed": self.slots_committed,
            "ranking_rule": list(self.ranking_rule),
            "granted": len(self.by_decision(ALLOCATION_GRANTED)),
            "queued": len(self.by_decision(ALLOCATION_QUEUED)),
            "deferred": len(self.by_decision(ALLOCATION_DEFERRED)),
            "disclosure": self.disclosure,
        }


#: The ranking rule, in order, stated as data so a plan can print the rule it
#: applied rather than a reader having to trust this docstring.
RANKING_RULE = (
    "1. loop_budget.prioritize_stage() verdict: PROCEED_CRITICAL before PROCEED "
    "(section 92's own 'critical signoff work may receive higher priority under policy').",
    "2. Fewest farm slots already held by that project, from the real bjobs listing "
    "intersected with each project's own registered job ids -- so one project cannot "
    "monopolise a pool by asking repeatedly. Inert when no live listing was supplied.",
    "3. Oldest requested_at first (FIFO). A request declaring no timestamp sorts last "
    "and can never jump ahead of one that does.",
    "4. project_id then stage, purely so the order is deterministic and two runs over "
    "the same inputs produce the same plan.",
)


def _sort_key(alloc_input: Tuple[ResourceRequest, Any, Optional[int]],
              *, use_held: bool):
    """Rule 1 -> 4 of `RANKING_RULE`, as one comparable tuple.

    `use_held` is False whenever ANY contender's held-slot count is unknown.
    The fairness term is then inert for EVERYONE and rule 3 (FIFO) decides.
    The two alternatives are both wrong: reading an unknown as 0 would let a
    project nobody measured beat one measured at three, and sorting an unknown
    last would penalise a project for a measurement this harness failed to
    take. A partially-measured signal cannot rank fairly, so it ranks nothing.
    """
    req, decision, held = alloc_input
    tier = _TIER_BY_PRIORITY.get(decision.decision, 2)
    held_key = (held or 0) if use_held else 0
    # A request that declares no arrival time sorts last within its tier rather
    # than being given a fabricated one.
    at_key = (1, "") if not req.requested_at else (0, req.requested_at)
    return (tier, held_key, at_key, req.project_id, req.stage)


def arbitrate(requests: Sequence[Any],
              *,
              pressure: loop_budget.ResourcePressure,
              capacity: FarmCapacity,
              critical_stages: Optional[Tuple[str, ...]] = None,
              live_jobs: Optional[Sequence[Dict[str, Any]]] = None
              ) -> ArbitrationPlan:
    """Rank N contenders against ONE measured capacity.

    The single-loop verdict is `loop_budget.prioritize_stage()`'s, called once
    per contender and carried through verbatim -- this function never overturns
    a DEFER into a GRANT, and never turns a PROCEED into a DEFER. What it adds
    is the bounded grant set:

      * A contender consuming NONE of the scarce resource is GRANTED and
        charged NO slot. Making a pure analysis stage wait behind a build would
        delay the project and free nothing -- the same reasoning
        `prioritize_stage()` rule 2 already applies one level down.
      * With no measured capacity, every eligible contender is GRANTED and the
        plan says the capacity was unmeasured. Deferring real work because
        nothing was measured would be inventing scarcity.
      * With a measured capacity, contenders are granted in rank order until
        the next one does not fit, and everything from there on is QUEUED.
        Granting a smaller lower-ranked contender that happens to fit would
        invert the ranking and let a large job starve indefinitely, so the
        head-of-line request holds its place.
    """
    reqs = [_coerce_request(r) for r in requests]
    crit = tuple(critical_stages or loop_budget.DEFAULT_CRITICAL_STAGES)
    held = held_slots_by_project(reqs, live_jobs)

    scored = []
    for r in reqs:
        decision = loop_budget.prioritize_stage(
            r.stage, pressure,
            consumes_scarce_resource=r.consumes_scarce_resource,
            critical_stages=crit)
        scored.append((r, decision, held.get(r.project_id)))

    use_held = bool(scored) and all(h is not None for _r, _d, h in scored)
    scored.sort(key=lambda item: _sort_key(item, use_held=use_held))

    allocations: List[Allocation] = []
    remaining = capacity.slots_available
    committed = 0
    rank = 0
    head_of_line_blocked_by: Optional[str] = None

    for req, decision, held_n in scored:
        base = dict(project_id=req.project_id, stage=req.stage,
                    priority=decision.decision, priority_reason=decision.reason,
                    slots_requested=req.slots_requested, held_slots=held_n,
                    requested_at=req.requested_at,
                    consumes_scarce_resource=req.consumes_scarce_resource)
        if decision.decision == loop_budget.PRIORITY_DEFER:
            allocations.append(Allocation(
                decision=ALLOCATION_DEFERRED, rank=None,
                reason=("deferred by loop_budget.prioritize_stage() before any cross-job "
                        "ranking; this orchestrator never overturns that decision."),
                **base))
            continue

        rank += 1
        if not req.consumes_scarce_resource:
            allocations.append(Allocation(
                decision=ALLOCATION_GRANTED, rank=rank,
                reason=("granted and charged no slot: this contender declares no "
                        "execution-layer skill, so it consumes none of the arbitrated "
                        "resource and waiting behind one that does would free nothing."),
                **base))
            continue

        if remaining is None:
            allocations.append(Allocation(
                decision=ALLOCATION_GRANTED, rank=rank,
                reason=("granted: no license free-seat count and no queue slot count were "
                        "measured, so no capacity bound is claimed and none is invented. "
                        + str(capacity.sources.get("slots_available_reason") or "")).strip(),
                **base))
            continue

        if head_of_line_blocked_by is None and req.slots_requested <= remaining:
            remaining -= req.slots_requested
            committed += req.slots_requested
            allocations.append(Allocation(
                decision=ALLOCATION_GRANTED, rank=rank,
                reason=(f"granted {req.slots_requested} of the measured "
                        f"{capacity.slots_available} available slot(s) "
                        f"(binding constraint: {capacity.binding_constraint}); "
                        f"{remaining} remain after this grant."),
                **base))
            continue

        if head_of_line_blocked_by is None:
            head_of_line_blocked_by = f"{req.project_id}/{req.stage}"
            held_note = ("This contender is itself the head of the line: nothing "
                         "lower-ranked is granted ahead of it, so a smaller request "
                         "cannot jump the queue and starve it.")
        else:
            held_note = f"Head of the line is {head_of_line_blocked_by}."
        allocations.append(Allocation(
            decision=ALLOCATION_QUEUED, rank=rank,
            reason=(f"queued: {req.slots_requested} slot(s) requested, {remaining} of the "
                    f"measured {capacity.slots_available} left after higher-ranked "
                    f"contenders (binding constraint: {capacity.binding_constraint}). "
                    + held_note),
            **base))

    return ArbitrationPlan(
        pressure=pressure.to_dict(),
        capacity=capacity.to_dict(),
        allocations=allocations,
        slots_committed=committed,
        ranking_rule=list(RANKING_RULE))


def orchestrate(requests: Sequence[Any],
                *,
                checks: Optional[Sequence[Any]] = None,
                cfg: Optional[Dict[str, Any]] = None,
                runner: Optional[Any] = None,
                queue: str = "",
                live_jobs: Optional[Sequence[Dict[str, Any]]] = None,
                job_lister: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
                vcuser: str = "",
                critical_stages: Optional[Tuple[str, ...]] = None
                ) -> ArbitrationPlan:
    """Front door: measure once, arbitrate once.

    ONE license/queue reading is taken and shared by every contender. That is
    the point of the front door, not an optimisation: N jobs each running their
    own `lmstat` would each see a different instant and could each conclude
    they were the one with room.

    `checks` -- already-run `preflight.CheckOutcome`s -- is preferred and costs
    nothing. Otherwise, and ONLY when a `runner` is explicitly injected, the
    probe goes through `degradation.probe_resources()`, i.e.
    `preflight.check_license()` / `check_queue_health()` themselves. With
    neither, pressure is UNKNOWN and capacity is unmeasured, and the plan says
    so rather than reading a missing binary as either a full farm or an empty
    one.

    `live_jobs` is preferred over `job_lister`/`vcuser` for the same reason. A
    `job_lister` (defaulting to `lsf_client.discover_live_jobs`) is called only
    when a `vcuser` is explicitly supplied, and a failure to list is recorded
    as "not observed" rather than as an empty farm."""
    conf = loop_budget.resolve_config(cfg)
    if checks is None and runner is not None:
        from . import degradation
        checks = degradation.probe_resources(cfg, runner=runner)
    checks = list(checks or [])

    pressure = loop_budget.pressure_from_checks(
        checks, license_pressure_fraction=float(conf.get("license_pressure_fraction") or 0.0))

    if live_jobs is None and vcuser:
        lister = job_lister or _default_job_lister
        try:
            live_jobs = lister(vcuser)
        except Exception:
            live_jobs = None

    capacity = capacity_from_checks(checks, queue=queue, live_jobs=live_jobs)
    # An explicit argument wins over the project's configured list, which wins
    # over loop_budget's default -- the same precedence `preflight.
    # config_from_dict()` gives an explicit override over a config.json block.
    crit = critical_stages or tuple(conf.get("critical_stages") or ()) or None
    return arbitrate(requests, pressure=pressure, capacity=capacity,
                     critical_stages=crit, live_jobs=live_jobs)


def _default_job_lister(vcuser: str) -> List[Dict[str, Any]]:
    from .lsf_client import discover_live_jobs
    return discover_live_jobs(vcuser)


# ==========================================================================
# Cross-PROJECT contenders, from the registry this codebase already has
# ==========================================================================
def execution_preflight_skills() -> Tuple[str, ...]:
    """The skills that make a graph node execution-layer work, i.e. work that
    really consumes a license seat and a farm slot.

    IMPORTED, not a second list: `engine.DVHarness.EXECUTION_PREFLIGHT_SKILLS`
    is the discriminator that arms the execution preflight gate, and it is what
    `loop_budget.prioritize_stage()`'s own caller already uses to decide
    `consumes_scarce_resource`. A copy here would be a second answer to "does
    this stage cost a license".
    """
    from .engine import DVHarness
    return tuple(DVHarness.EXECUTION_PREFLIGHT_SKILLS)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def contenders_from_registry(host_root) -> Tuple[List[ResourceRequest], List[Dict[str, Any]]]:
    """Build one contender per REGISTERED project from what is really on disk.

    The registry is `cross_project_mining.ProjectRegistry` -- this codebase's
    existing cross-project registry, including its identity-collision guard, so
    one memory store registered twice cannot appear as two contenders. Each
    project's current stage is read from its own `.dv-harness/state.json` with
    a plain `read_text()`; no `StateStore` is constructed, because that would
    MINT a state.json in a project that has never run.

    Whether that stage consumes the scarce resource is decided from the
    project's OWN graph node skills against `execution_preflight_skills()` --
    never from the stage name. A project whose graph or state cannot be read
    contributes no contender and a real skipped-reason instead, because
    inventing a contender for it would put a project into an arbitration it
    never asked to join."""
    from .cross_project_mining import ProjectRegistry
    reg = ProjectRegistry(host_root)
    exec_skills = set(execution_preflight_skills())
    out: List[ResourceRequest] = []
    skipped: List[Dict[str, Any]] = []
    for entry in reg.entries():
        root = Path(str(entry.get("root") or ""))
        pid = str(entry.get("project_id") or root.name)
        state = _read_json(root / ".dv-harness" / "state.json")
        if not isinstance(state, dict) or not state.get("current_stage"):
            skipped.append({"project_id": pid, "root": str(root),
                            "reason": "NO_STATE_JSON_OR_NO_CURRENT_STAGE"})
            continue
        stage = str(state["current_stage"])
        graph = _read_json(root / ".dv-harness" / "graph" / "main_graph.json")
        node = None
        if isinstance(graph, dict):
            for n in graph.get("nodes") or []:
                if isinstance(n, dict) and n.get("id") == stage:
                    node = n
                    break
        if node is None:
            skipped.append({"project_id": pid, "root": str(root), "stage": stage,
                            "reason": "STAGE_NOT_FOUND_IN_PROJECT_GRAPH"})
            continue
        consumes = bool(exec_skills & set(node.get("skills") or []))
        # The moment this project ENTERED the stage that is now contending --
        # `run_stage()`'s own `started_at` on that stage's state record, which
        # is what FIFO fairness is actually about. A stage the project has not
        # started carries none, and the request then sorts last rather than
        # being given a fabricated arrival time.
        stage_state = (state.get("stages") or {}).get(stage) or {}
        out.append(ResourceRequest(
            project_id=pid, stage=stage, consumes_scarce_resource=consumes,
            root=str(root),
            requested_at=str(stage_state.get("started_at") or ""),
            note=f"current_stage from {root / '.dv-harness' / 'state.json'}"))
    return out, skipped


# ==========================================================================
# Front door
# ==========================================================================
def execute_verb(root, verb: str, *,
                 requests_path: str = "",
                 checks: Optional[Sequence[Any]] = None,
                 queue: str = "",
                 live_jobs: Optional[Sequence[Dict[str, Any]]] = None,
                 cfg: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    """Returns (exit_code, payload). One implementation, shared by
    `python -m dv_harness.resource_orchestrator` and any future CLI verb --
    two handlers over the same behaviour is the parallel-mechanism defect this
    project forbids, at CLI scale."""
    root = Path(root)

    if verb == "ranking-rule":
        return 0, {"ranking_rule": list(RANKING_RULE),
                   "decisions": list(ALLOCATION_DECISIONS),
                   "disclosure": PLAN_DISCLOSURE}

    if verb == "contenders":
        reqs, skipped = contenders_from_registry(root)
        return 0, {"contenders": [r.to_dict() for r in reqs], "skipped": skipped,
                   "registry": "cross_project_mining.ProjectRegistry"}

    if verb == "capacity":
        cap = capacity_from_checks(checks or [], queue=queue, live_jobs=live_jobs)
        return (0 if cap.measured else 2), cap.to_dict()

    if verb == "plan":
        if requests_path:
            data = _read_json(Path(requests_path))
            if not isinstance(data, list):
                return 1, {"ok": False, "error": "REQUESTS_FILE_MUST_BE_A_JSON_LIST",
                           "path": requests_path}
            reqs: List[Any] = list(data)
            skipped: List[Dict[str, Any]] = []
        else:
            built, skipped = contenders_from_registry(root)
            reqs = list(built)
        if not reqs:
            return 2, {"ok": False, "error": "NO_CONTENDERS",
                       "detail": ("no resource requests were supplied and no registered "
                                  "project carries a readable current stage -- there is "
                                  "nothing to arbitrate."),
                       "skipped": skipped}
        try:
            plan = orchestrate(reqs, checks=checks or [], cfg=cfg, queue=queue,
                               live_jobs=live_jobs)
        except ResourceOrchestratorError as exc:
            return 1, {"ok": False, "error": "MALFORMED_REQUEST", "detail": str(exc)}
        payload = plan.to_dict()
        payload["skipped"] = skipped
        # Exit 2 when a contender is held back -- a CI-visible "someone is
        # waiting on capacity", never an approval signal in either direction.
        held = payload["queued"] + payload["deferred"]
        return (2 if held else 0), payload

    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["ranking-rule", "contenders", "capacity", "plan"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.resource_orchestrator",
        description=(__doc__ or "").split("\n")[0])
    ap.add_argument("verb", choices=["ranking-rule", "contenders", "capacity", "plan"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--requests", default="",
                    help="JSON list of resource requests; omit to build them from the "
                         "cross-project registry")
    ap.add_argument("--queue", default="")
    args = ap.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 requests_path=args.requests, queue=args.queue)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
