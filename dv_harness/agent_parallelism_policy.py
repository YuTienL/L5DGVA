"""Agent Parallelism Policy: which task CLASSES get priority, and how many
agents/jobs may run concurrently against one shared resource (2026-09-06,
targeted_hardening, section 244).

WHAT WAS ALREADY REAL
----------------------
`resource_orchestrator.py` (VI-5) already turns ONE measured license/queue
capacity into a bounded GRANT/QUEUE/DEFER plan over N contenders, and its own
`RANKING_RULE` already gives PROCEED_CRITICAL work (the graph-Stage members in
`loop_budget.DEFAULT_CRITICAL_STAGES`) priority over ordinary PROCEED work
under measured pressure. That is real and this module never re-derives it:
every capacity number, every PROCEED/PROCEED_CRITICAL/DEFER verdict, and the
anti-monopoly (fewest-held-slots) / FIFO / deterministic tie-break rules
inside one arbitration round are all reused verbatim by calling
`resource_orchestrator.arbitrate()`, never re-implemented here.

WHAT WAS MISSING
-----------------
Two things `resource_orchestrator.py` deliberately does not do, confirmed by
reading its own docstring and `RANKING_RULE` before writing a line of this:

  1. A DECLARED cap on how many agents/jobs may run concurrently against a
     shared resource, independent of what license/queue MEASUREMENT says.
     `resource_orchestrator.capacity_from_checks()` derives `slots_available`
     only from a real `lmstat`/`bqueues` reading; a project that wants a
     tighter administrative ceiling than the license pool happens to allow
     right now (or, notably, a ceiling that still applies even when NOTHING
     was measured -- `resource_orchestrator`'s own rule is "with no measured
     capacity, every eligible contender is GRANTED", which is correct for
     that module but leaves no way to say "cap at N regardless") has nowhere
     to declare that.
  2. A TASK-CLASS priority scheme wider than `prioritize_stage()`'s own
     two-tier PROCEED_CRITICAL/PROCEED split, itself keyed on a fixed
     `models.Stage` name list (`loop_budget.DEFAULT_CRITICAL_STAGES`). A
     contender that is not a verification-closure graph Stage at all -- a
     `dv-harness research` run, a documentation pass, some future task
     family this harness's own graph never names -- has no stage to be
     "critical" or not, and cannot be ranked by that mechanism no matter how
     the caller configures `critical_stages`.

This module adds exactly those two things as a POLICY LAYER on top of
`resource_orchestrator.py`, and nothing else. It is data-driven
(`agent_parallelism_policy.json`, the same "policy lives as data, never
hardcoded Python" convention `context_budget.policy.json` and
`doc_extraction_categories.json` already use), and every one of its own
DERIVED task-class facts is grounded in real, already-established evidence
this codebase already computes (`loop_budget.DEFAULT_CRITICAL_STAGES` for
SIGNOFF_FAMILY, the caller's own `consumes_scarce_resource` -- itself derived
by the caller from `engine.DVHarness.EXECUTION_PREFLIGHT_SKILLS`, exactly as
`resource_orchestrator.ResourceRequest`'s own docstring already requires --
for EXECUTION vs ANALYSIS). A task class outside that derivable set (e.g. a
future `RESEARCH` class for `dv-harness research` work, which section
"Research Front Door" in CLAUDE.md states plainly has no graph node and
cannot be derived from a Stage) must be explicitly DECLARED by the caller,
never guessed.

WHAT THIS MODULE IS NOT
------------------------
  * It is not a second capacity probe or a second measurement of anything --
    every capacity number still comes from `resource_orchestrator`'s own
    `FarmCapacity`, built from real `preflight.CheckOutcome`s exactly as
    before. A declared `max_concurrent` cap can only NARROW a measured
    capacity, never widen it past what was actually measured (see
    `apply_concurrency_cap()`).
  * It is not a second grant/arbitration algorithm. Every GRANT/QUEUE/DEFER
    decision this module reports comes from a real call to
    `resource_orchestrator.arbitrate()` -- one call per declared task-class
    tier, in priority order, each call seeing only the capacity left over
    after the tier(s) ranked above it were granted theirs. Within one tier,
    `resource_orchestrator`'s own anti-monopoly/FIFO/tie-break rules apply
    completely unchanged.
  * It never overturns a `loop_budget.prioritize_stage()` DEFER. A stage
    under measured resource pressure that is not on the (possibly
    project-configured) critical-stage list is still DEFERRED by
    `resource_orchestrator.arbitrate()`'s own internal call to that function,
    exactly as it would be with no policy layer at all -- this module's tier
    ordering decides WHICH of the non-deferred contenders gets capacity
    first, never whether a stage is deferred in the first place.
  * It is not a submitter and not a gate. Exactly like `resource_orchestrator`
    itself, a GRANT here authorizes nothing: every existing preflight/
    approval gate still stands in front of any real work, and nothing in
    this module submits, kills, or reserves a job.

Reading is never a mutating act: no state, control, approval or memory record
is written, and loading the policy JSON never writes one either.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import loop_budget, resource_orchestrator

# ==========================================================================
# Errors
# ==========================================================================
class AgentParallelismPolicyError(ValueError):
    """A malformed policy file or a malformed contender. Raised rather than
    silently defaulted -- a policy this module could not read is a policy it
    would otherwise have silently NOT enforced, which is worse than refusing
    to run."""


# ==========================================================================
# Task-class vocabulary
# ==========================================================================
#: The only three task classes this module can DERIVE from real evidence
#: without a caller's explicit declaration -- see this module's own
#: docstring for the exact real facts each one is grounded in. A caller may
#: declare ANY other class name explicitly (task_class=...); it is then
#: trusted as the caller's own stated fact, the same "consumes_scarce_resource
#: must be declared explicitly, never guessed" discipline
#: `resource_orchestrator.ResourceRequest` already applies one field over.
TASK_CLASS_SIGNOFF_FAMILY = "SIGNOFF_FAMILY"
TASK_CLASS_EXECUTION = "EXECUTION"
TASK_CLASS_ANALYSIS = "ANALYSIS"

DERIVABLE_TASK_CLASSES: Tuple[str, ...] = (
    TASK_CLASS_SIGNOFF_FAMILY, TASK_CLASS_EXECUTION, TASK_CLASS_ANALYSIS,
)

#: Whether a contender's task_class was stated by the caller, or derived here
#: from `consumes_scarce_resource` / critical-stage membership. Kept apart so
#: an override is always distinguishable from this module's own guess, the
#: same DECLARED-vs-DERIVED split `requirement_risk_ir.py` and
#: `verification_intent_ir.py` already use for their own per-field facts.
RESOLUTION_DECLARED = "DECLARED"
RESOLUTION_DERIVED = "DERIVED"


def resolve_task_class(stage: str, consumes_scarce_resource: bool, *,
                       declared: Optional[str] = None,
                       critical_stages: Optional[Tuple[str, ...]] = None
                       ) -> Tuple[str, str]:
    """One contender's task class, and whether it was DECLARED or DERIVED.

    An explicit `declared` value always wins and is never second-guessed
    against the stage/consumes_scarce_resource facts -- a caller who knows
    this is `dv-harness research` work, or any other class this module has
    no derivation rule for, must be free to say so. Absent one, the class is
    DERIVED from the same two real facts `resource_orchestrator.arbitrate()`
    itself already reads: stage membership in `critical_stages` (default
    `loop_budget.DEFAULT_CRITICAL_STAGES`) -> SIGNOFF_FAMILY; otherwise
    `consumes_scarce_resource` -> EXECUTION; otherwise ANALYSIS.
    """
    if declared is not None:
        if not isinstance(declared, str) or not declared.strip():
            raise AgentParallelismPolicyError(
                "a declared task_class must be a non-empty string, not "
                f"{declared!r}")
        return declared, RESOLUTION_DECLARED
    crit = tuple(critical_stages or loop_budget.DEFAULT_CRITICAL_STAGES)
    if stage and stage in crit:
        return TASK_CLASS_SIGNOFF_FAMILY, RESOLUTION_DERIVED
    if consumes_scarce_resource:
        return TASK_CLASS_EXECUTION, RESOLUTION_DERIVED
    return TASK_CLASS_ANALYSIS, RESOLUTION_DERIVED


# ==========================================================================
# The declared policy itself (data, validated -- never hand-trusted JSON)
# ==========================================================================
DEFAULT_POLICY_PATH = Path(__file__).with_name("agent_parallelism_policy.json")

_SCHEMA_VERSION = 1


@dataclass
class ResourceConcurrencyCap:
    """A declared, cited administrative ceiling on how many agents/jobs may
    run concurrently against ONE named shared resource -- independent of,
    and only ever able to NARROW, whatever `resource_orchestrator`'s own
    real capacity measurement says. `reason` is required for the same
    reason `resource_orchestrator.FarmCapacity`'s every `None` carries a
    real reason in `sources`: an uncited cap would be a number a reader has
    no way to check."""
    resource: str
    max_concurrent: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskClassPriorityPolicy:
    """The loaded, validated policy: an ordered task-class priority list
    (highest first) plus zero or more per-resource concurrency caps. Both
    halves are data a project edits in `agent_parallelism_policy.json`,
    never Python -- the same convention `context_budget.policy.json`
    already established for this codebase's other policy-as-data modules."""
    schema_version: int
    priority_order: Tuple[str, ...]
    resource_caps: Dict[str, ResourceConcurrencyCap]
    source_path: Optional[str] = None
    default_reason: str = ""

    def class_rank(self, task_class: str) -> Optional[int]:
        """Lower is higher priority. `None` means this class was never
        declared in `priority_order` at all -- it is neither an error nor a
        guessed rank; such a contender is grouped into one final,
        lowest-priority tier (see `arbitrate_with_policy()`), never silently
        dropped and never silently assumed top priority."""
        try:
            return self.priority_order.index(task_class)
        except ValueError:
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "priority_order": list(self.priority_order),
            "resource_caps": {k: v.to_dict() for k, v in self.resource_caps.items()},
            "source_path": self.source_path,
            "default_reason": self.default_reason,
        }


def _validate_and_build_policy(data: Any, source_path: Optional[Path]) -> TaskClassPriorityPolicy:
    if not isinstance(data, dict):
        raise AgentParallelismPolicyError(
            f"agent parallelism policy must be a JSON object, got {type(data).__name__}")
    schema_version = data.get("schema_version")
    if schema_version != _SCHEMA_VERSION:
        raise AgentParallelismPolicyError(
            f"unsupported agent_parallelism_policy schema_version {schema_version!r}; "
            f"expected {_SCHEMA_VERSION}")

    priority_order_raw = data.get("task_class_priority")
    if not isinstance(priority_order_raw, list) or not priority_order_raw:
        raise AgentParallelismPolicyError(
            "task_class_priority must be a non-empty JSON list of task-class names, "
            "highest priority first")
    seen: set = set()
    priority_order: List[str] = []
    for entry in priority_order_raw:
        if not isinstance(entry, str) or not entry.strip():
            raise AgentParallelismPolicyError(
                f"task_class_priority entries must be non-empty strings, got {entry!r}")
        if entry in seen:
            raise AgentParallelismPolicyError(
                f"task_class_priority declares {entry!r} more than once")
        seen.add(entry)
        priority_order.append(entry)

    resources_raw = data.get("resources") or {}
    if not isinstance(resources_raw, dict):
        raise AgentParallelismPolicyError("resources must be a JSON object keyed by resource name")
    resource_caps: Dict[str, ResourceConcurrencyCap] = {}
    for name, entry in resources_raw.items():
        if not isinstance(entry, dict):
            raise AgentParallelismPolicyError(f"resources[{name!r}] must be a JSON object")
        max_concurrent = entry.get("max_concurrent")
        reason = entry.get("reason")
        # bool is an int subclass in Python -- excluded explicitly so a
        # declared `true` can never silently read as max_concurrent=1.
        if not isinstance(max_concurrent, int) or isinstance(max_concurrent, bool) or max_concurrent < 1:
            raise AgentParallelismPolicyError(
                f"resources[{name!r}].max_concurrent must be a positive integer, "
                f"got {max_concurrent!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise AgentParallelismPolicyError(
                f"resources[{name!r}] declares a max_concurrent cap with no real reason -- "
                "an uncited concurrency cap is exactly the kind of unsupported number the "
                "Evidence Truth Rule forbids")
        resource_caps[str(name)] = ResourceConcurrencyCap(
            resource=str(name), max_concurrent=int(max_concurrent), reason=str(reason))

    default_reason = data.get("default_reason") or ""
    return TaskClassPriorityPolicy(
        schema_version=schema_version, priority_order=tuple(priority_order),
        resource_caps=resource_caps,
        source_path=str(source_path) if source_path is not None else None,
        default_reason=str(default_reason))


def load_policy(path: Optional[Any] = None) -> TaskClassPriorityPolicy:
    """Load and validate `agent_parallelism_policy.json` (or a caller-named
    file of the same shape). Raises `AgentParallelismPolicyError` on
    anything malformed rather than silently falling back to an empty/
    permissive policy -- a policy this module could not parse must never be
    read as "no policy, allow everything"."""
    p = Path(path) if path else DEFAULT_POLICY_PATH
    if not p.is_file():
        raise AgentParallelismPolicyError(
            f"no agent parallelism policy file at {p} -- a policy must be declared, never assumed")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AgentParallelismPolicyError(
            f"agent parallelism policy at {p} is not valid JSON: {exc}") from exc
    return _validate_and_build_policy(data, p)


# ==========================================================================
# The declared max_concurrent cap: narrows measured capacity, never widens it
# ==========================================================================
def apply_concurrency_cap(capacity: resource_orchestrator.FarmCapacity,
                          policy: TaskClassPriorityPolicy,
                          resource_name: str
                          ) -> Tuple[resource_orchestrator.FarmCapacity, Dict[str, Any]]:
    """Cap `capacity.slots_available` at the policy's declared
    `max_concurrent` for `resource_name`, if one exists.

    Three cases, each with a real reason recorded:
      * No cap declared for this resource -> the measured capacity (or its
        absence -- `slots_available` stays `None`) is returned UNCHANGED.
        This is the case `resource_orchestrator.py` already handles on its
        own; this module adds nothing when a project has declared nothing.
      * A cap IS declared and measured capacity is either unmeasured
        (`None`) or genuinely looser than the cap -> capacity is narrowed to
        the declared cap. This is the one genuinely new capability: an
        administrative ceiling that holds even when nothing was measured,
        which `resource_orchestrator.capacity_from_checks()` alone cannot
        express (its own rule is "do not invent scarcity" from a MEASURED
        absence -- a DECLARED policy ceiling is a different kind of fact,
        not an invented measurement).
      * A cap is declared but measured capacity is already tighter -> the
        measured capacity remains binding; the declared cap is recorded but
        never used to WIDEN a real measurement past what was actually
        checked.
    """
    cap = policy.resource_caps.get(resource_name)
    if cap is None:
        return capacity, {
            "applied": False, "resource": resource_name, "declared_max_concurrent": None,
            "measured_slots_available": capacity.slots_available,
            "reason": (f"no max_concurrent declared in policy for resource {resource_name!r} -- "
                       "measured capacity (or its real absence) remains the sole bound; a cap is "
                       "never invented."),
        }
    measured = capacity.slots_available
    if measured is not None and cap.max_concurrent >= measured:
        return capacity, {
            "applied": False, "resource": resource_name,
            "declared_max_concurrent": cap.max_concurrent, "measured_slots_available": measured,
            "reason": (f"declared max_concurrent ({cap.max_concurrent}) is >= measured capacity "
                       f"({measured}); measured capacity remains binding, never widened."),
        }
    capped = replace(capacity, slots_available=cap.max_concurrent,
                     binding_constraint=f"agent_parallelism_policy:{resource_name}")
    return capped, {
        "applied": True, "resource": resource_name,
        "declared_max_concurrent": cap.max_concurrent, "measured_slots_available": measured,
        "reason": cap.reason,
    }


# ==========================================================================
# Contenders
# ==========================================================================
@dataclass
class PolicyContender:
    """One `resource_orchestrator.ResourceRequest`'s worth of facts, plus an
    OPTIONAL explicit `task_class` declaration. `consumes_scarce_resource`
    keeps the exact same "must be stated explicitly, never defaulted"
    discipline `ResourceRequest` itself already requires -- see
    `_coerce_contender()`."""
    project_id: str
    stage: str
    consumes_scarce_resource: bool
    root: str = ""
    requested_at: str = ""
    slots_requested: int = 1
    note: str = ""
    task_class: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _coerce_contender(obj: Any) -> PolicyContender:
    if isinstance(obj, PolicyContender):
        c = obj
    elif isinstance(obj, dict):
        missing = [k for k in ("project_id", "stage") if not obj.get(k)]
        if missing:
            raise AgentParallelismPolicyError(
                f"contender is missing required field(s) {missing}: {obj!r}")
        if "consumes_scarce_resource" not in obj:
            raise AgentParallelismPolicyError(
                "contender must state consumes_scarce_resource explicitly -- defaulting it "
                "either way would either defer analysis work that frees nothing, or grant "
                f"execution work no capacity was checked for: {obj!r}")
        declared_task_class = obj.get("task_class")
        c = PolicyContender(
            project_id=str(obj["project_id"]), stage=str(obj["stage"]),
            consumes_scarce_resource=bool(obj["consumes_scarce_resource"]),
            root=str(obj.get("root") or ""), requested_at=str(obj.get("requested_at") or ""),
            slots_requested=int(1 if obj.get("slots_requested") is None else obj["slots_requested"]),
            note=str(obj.get("note") or ""),
            task_class=(str(declared_task_class) if declared_task_class else None))
    else:
        raise AgentParallelismPolicyError(
            f"contender must be a PolicyContender or a dict, got {type(obj).__name__}")
    if not c.project_id or not c.stage:
        raise AgentParallelismPolicyError(
            f"contender must declare a non-empty project_id and stage: {c!r}")
    if c.slots_requested < 1:
        raise AgentParallelismPolicyError(
            f"slots_requested must be >= 1 (got {c.slots_requested}) for "
            f"{c.project_id}/{c.stage}")
    if c.task_class is not None and not c.task_class.strip():
        raise AgentParallelismPolicyError(
            f"declared task_class must be non-empty if given, for {c.project_id}/{c.stage}")
    return c


def _to_resource_request(c: PolicyContender) -> resource_orchestrator.ResourceRequest:
    return resource_orchestrator.ResourceRequest(
        project_id=c.project_id, stage=c.stage,
        consumes_scarce_resource=c.consumes_scarce_resource, root=c.root,
        requested_at=c.requested_at, slots_requested=c.slots_requested, note=c.note)


# ==========================================================================
# Policy-tiered arbitration
# ==========================================================================
@dataclass
class PolicyAllocation:
    """One contender's cross-job outcome, carrying `resource_orchestrator.
    Allocation`'s own fields verbatim plus the task-class facts this module
    adds."""
    project_id: str
    stage: str
    task_class: str
    task_class_resolution: str
    policy_tier_rank: Optional[int]
    decision: str
    rank: Optional[int]
    reason: str
    priority: str
    priority_reason: str
    slots_requested: int
    held_slots: Optional[int]
    requested_at: str
    consumes_scarce_resource: bool

    @property
    def granted(self) -> bool:
        return self.decision == resource_orchestrator.ALLOCATION_GRANTED

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["granted"] = self.granted
        return d


PLAN_DISCLOSURE = (
    "A policy plan orders GRANT/QUEUE/DEFER decisions by declared task-class priority tier, "
    "then reuses resource_orchestrator.arbitrate() VERBATIM within (and across, via "
    "remaining-capacity carryover) each tier for the real capacity/grant bookkeeping and its "
    "own anti-monopoly/FIFO/tie-break rules -- see resource_orchestrator.PLAN_DISCLOSURE, which "
    "applies unchanged to every allocation here. This module authorizes nothing beyond what "
    "resource_orchestrator's own GRANT already authorizes, and a declared max_concurrent cap "
    "only ever NARROWS measured capacity, never widens it past what was actually measured."
)


@dataclass
class PolicyArbitrationPlan:
    resource_name: str
    capacity: Dict[str, Any]
    capacity_cap: Dict[str, Any]
    tiers: List[Dict[str, Any]]
    allocations: List[PolicyAllocation]
    ranking_rule: List[str]
    disclosure: str = PLAN_DISCLOSURE

    def by_decision(self, decision: str) -> List[PolicyAllocation]:
        return [a for a in self.allocations if a.decision == decision]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_name": self.resource_name,
            "capacity": self.capacity,
            "capacity_cap": self.capacity_cap,
            "tiers": self.tiers,
            "allocations": [a.to_dict() for a in self.allocations],
            "granted": len(self.by_decision(resource_orchestrator.ALLOCATION_GRANTED)),
            "queued": len(self.by_decision(resource_orchestrator.ALLOCATION_QUEUED)),
            "deferred": len(self.by_decision(resource_orchestrator.ALLOCATION_DEFERRED)),
            "ranking_rule": list(self.ranking_rule),
            "disclosure": self.disclosure,
        }


def arbitrate_with_policy(contenders: Sequence[Any],
                          *,
                          pressure: "loop_budget.ResourcePressure",
                          capacity: resource_orchestrator.FarmCapacity,
                          resource_name: str,
                          policy: Optional[TaskClassPriorityPolicy] = None,
                          critical_stages: Optional[Tuple[str, ...]] = None,
                          live_jobs: Optional[Sequence[Dict[str, Any]]] = None
                          ) -> PolicyArbitrationPlan:
    """Rank N contenders by declared task-class tier, then hand each tier to
    the REAL `resource_orchestrator.arbitrate()` in priority order, carrying
    forward whatever capacity the higher tiers left over.

    Every tier is one real `arbitrate()` call: within it, that function's
    own PROCEED_CRITICAL/PROCEED/DEFER, anti-monopoly and FIFO rules apply
    completely unchanged. This function decides only WHICH tier goes first
    and HOW MUCH capacity survives into the next one -- it never re-decides
    an individual GRANT/QUEUE/DEFER verdict `arbitrate()` already made.
    """
    if not resource_name:
        raise AgentParallelismPolicyError("resource_name must be a non-empty string")
    policy = policy or load_policy()
    coerced = [_coerce_contender(c) for c in contenders]

    capped_capacity, cap_info = apply_concurrency_cap(capacity, policy, resource_name)

    resolved: List[Tuple[PolicyContender, str, str, Optional[int]]] = []
    for c in coerced:
        task_class, resolution = resolve_task_class(
            c.stage, c.consumes_scarce_resource, declared=c.task_class,
            critical_stages=critical_stages)
        resolved.append((c, task_class, resolution, policy.class_rank(task_class)))

    # One tier per RANKED class that actually has a member, in policy order,
    # plus one final tier for every contender whose class was never declared
    # in priority_order -- grouped, never dropped, never guessed to the top.
    tiers: List[Tuple[Optional[int], str, List[Tuple[PolicyContender, str, str, Optional[int]]]]] = []
    for idx, cls in enumerate(policy.priority_order):
        members = [r for r in resolved if r[3] == idx]
        if members:
            tiers.append((idx, cls, members))
    unranked = [r for r in resolved if r[3] is None]
    if unranked:
        tiers.append((None, "UNRANKED", unranked))

    remaining = capped_capacity
    all_allocs: List[PolicyAllocation] = []
    tier_reports: List[Dict[str, Any]] = []
    for rank, cls, members in tiers:
        reqs = [_to_resource_request(m[0]) for m in members]
        sub_plan = resource_orchestrator.arbitrate(
            reqs, pressure=pressure, capacity=remaining,
            critical_stages=critical_stages, live_jobs=live_jobs)
        for alloc, (c, task_class, resolution, r) in zip(sub_plan.allocations, members):
            all_allocs.append(PolicyAllocation(
                project_id=alloc.project_id, stage=alloc.stage, task_class=task_class,
                task_class_resolution=resolution, policy_tier_rank=rank,
                decision=alloc.decision, rank=alloc.rank, reason=alloc.reason,
                priority=alloc.priority, priority_reason=alloc.priority_reason,
                slots_requested=alloc.slots_requested, held_slots=alloc.held_slots,
                requested_at=alloc.requested_at,
                consumes_scarce_resource=alloc.consumes_scarce_resource))
        tier_reports.append({
            "task_class": cls, "policy_tier_rank": rank, "contenders": len(members),
            "granted": len(sub_plan.by_decision(resource_orchestrator.ALLOCATION_GRANTED)),
            "queued": len(sub_plan.by_decision(resource_orchestrator.ALLOCATION_QUEUED)),
            "deferred": len(sub_plan.by_decision(resource_orchestrator.ALLOCATION_DEFERRED)),
            "slots_committed": sub_plan.slots_committed,
        })
        if remaining.slots_available is not None:
            remaining = replace(
                remaining, slots_available=max(0, remaining.slots_available - sub_plan.slots_committed))

    return PolicyArbitrationPlan(
        resource_name=resource_name, capacity=capacity.to_dict(), capacity_cap=cap_info,
        tiers=tier_reports, allocations=all_allocs,
        ranking_rule=[
            "0. Declared task-class priority tier (agent_parallelism_policy.json's own "
            f"task_class_priority: {list(policy.priority_order)}; a contender whose task_class "
            "was never declared there sorts into one final, lowest-priority tier, never guessed "
            "to the top).",
        ] + list(resource_orchestrator.RANKING_RULE))


def orchestrate_with_policy(contenders: Sequence[Any],
                            *,
                            resource_name: str,
                            checks: Optional[Sequence[Any]] = None,
                            cfg: Optional[Dict[str, Any]] = None,
                            queue: str = "",
                            live_jobs: Optional[Sequence[Dict[str, Any]]] = None,
                            policy: Optional[TaskClassPriorityPolicy] = None,
                            critical_stages: Optional[Tuple[str, ...]] = None
                            ) -> PolicyArbitrationPlan:
    """Front door mirroring `resource_orchestrator.orchestrate()`: measure
    once (via that module's own real `capacity_from_checks()` /
    `pressure_from_checks()`), then arbitrate once through the policy layer
    above."""
    conf = loop_budget.resolve_config(cfg)
    checks = list(checks or [])
    pressure = loop_budget.pressure_from_checks(
        checks, license_pressure_fraction=float(conf.get("license_pressure_fraction") or 0.0))
    capacity = resource_orchestrator.capacity_from_checks(checks, queue=queue, live_jobs=live_jobs)
    crit = critical_stages or tuple(conf.get("critical_stages") or ()) or None
    return arbitrate_with_policy(
        contenders, pressure=pressure, capacity=capacity, resource_name=resource_name,
        policy=policy, critical_stages=crit, live_jobs=live_jobs)


# ==========================================================================
# Front door
# ==========================================================================
def execute_verb(root: Any, verb: str, *,
                 policy_path: Optional[str] = None,
                 requests_path: str = "",
                 resource_name: str = "",
                 checks: Optional[Sequence[Any]] = None,
                 queue: str = "",
                 live_jobs: Optional[Sequence[Dict[str, Any]]] = None,
                 cfg: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    """Returns (exit_code, payload). One implementation shared by
    `python -m dv_harness.agent_parallelism_policy` and any future CLI verb.

    No `dv-harness` CLI verb is wired here -- `cli.py` is a large,
    heavily-edited file in this batch and this module deliberately follows
    the same disclosed-choice convention several very recent sibling modules
    in this codebase already state for exactly that reason."""
    if verb == "policy":
        try:
            policy = load_policy(policy_path)
        except AgentParallelismPolicyError as exc:
            return 2, {"ok": False, "error": "POLICY_INVALID", "detail": str(exc)}
        return 0, {"policy": policy.to_dict(),
                   "derivable_task_classes": list(DERIVABLE_TASK_CLASSES)}

    if verb == "plan":
        if not resource_name:
            return 1, {"ok": False, "error": "RESOURCE_NAME_REQUIRED"}
        try:
            policy = load_policy(policy_path)
        except AgentParallelismPolicyError as exc:
            return 2, {"ok": False, "error": "POLICY_INVALID", "detail": str(exc)}
        if not requests_path:
            return 1, {"ok": False, "error": "REQUESTS_FILE_REQUIRED"}
        try:
            data = json.loads(Path(requests_path).read_text(encoding="utf-8"))
        except Exception as exc:
            return 1, {"ok": False, "error": "REQUESTS_FILE_UNREADABLE", "detail": str(exc)}
        if not isinstance(data, list):
            return 1, {"ok": False, "error": "REQUESTS_FILE_MUST_BE_A_JSON_LIST",
                       "path": requests_path}
        try:
            plan = orchestrate_with_policy(
                data, resource_name=resource_name, checks=checks or [], cfg=cfg,
                queue=queue, live_jobs=live_jobs, policy=policy)
        except AgentParallelismPolicyError as exc:
            return 1, {"ok": False, "error": "MALFORMED_CONTENDER", "detail": str(exc)}
        except resource_orchestrator.ResourceOrchestratorError as exc:
            return 1, {"ok": False, "error": "MALFORMED_REQUEST", "detail": str(exc)}
        payload = plan.to_dict()
        held = payload["queued"] + payload["deferred"]
        return (2 if held else 0), payload

    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb, "known": ["policy", "plan"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.agent_parallelism_policy",
        description=(__doc__ or "").split("\n")[0])
    ap.add_argument("verb", choices=["policy", "plan"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--policy-path", default="",
                    help="path to an agent_parallelism_policy.json-shaped file; "
                         "defaults to dv_harness/agent_parallelism_policy.json")
    ap.add_argument("--requests", default="",
                    help="JSON list of contenders (project_id/stage/"
                         "consumes_scarce_resource/[task_class]/...)")
    ap.add_argument("--resource-name", default="",
                    help="the resource name to look up in the policy's per-resource caps, "
                         "e.g. 'eda_license' or 'lsf_queue:regression'")
    ap.add_argument("--queue", default="")
    args = ap.parse_args(argv)
    code, payload = execute_verb(
        args.project_root, args.verb,
        policy_path=(args.policy_path or None), requests_path=args.requests,
        resource_name=args.resource_name, queue=args.queue)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
