"""dv_harness/harness_status.py -- HarnessStatusIR + Global State Aggregator +
HarnessStatusService (2026-09-06, Global Status Bar theme, master-prompt
sections 403-411).

CORE CONCEPT (section 404/409): ONE canonical `HarnessStatusIR` record, read
by CLI / GUI / Web from ONE `HarnessStatusService`, assembled by ONE
`GlobalStateAggregator` that NORMALIZES already-real canonical state -- it is
explicitly forbidden from becoming "an independent verification oracle"
(section 409's own words). Every field below is READ from an existing real
module's output; nothing here re-derives a verdict a sibling module already
owns:

  - `golden_flow_readiness.derive_golden_flow_readiness()` -> closure rows
    (requirement/vplan/protocol/coverage/single-test-proof/signoff) and the
    section-47 overall READY/PARTIAL/BLOCKED/UNKNOWN verdict.
  - `platform_health.platform_health_report()` -> per-subsystem HEALTHY/
    DEGRADED/CRITICAL/UNKNOWN (license, LSF queue, execution environment,
    connectivity gates, agent adapter, regression quality).
  - `loop_telemetry.read_loop_telemetry()` -> the most recent verification-
    closure loop SESSION's own LoopState, iteration, run_id.
  - `loop_stale_detection.detect_loop_staleness()` -> STALE/NOT_STALE/UNKNOWN
    over this project's real recorded evidence (time-based + RTL-moved).
  - `question_queue.QuestionQueueStore.list_questions()` -> real open/
    blocking Tier-3 questions (HUMAN_GATE evidence).
  - `signoff_export.read_signoff_stage_status()` / `capture_baseline()` ->
    the real SIGNOFF stage verdict and the real DUT/TB SHA + spec-version +
    VIP-tool-version baseline identity.
  - `regression_reporter.load_jobs()` + `dashboard._lsf_summary()` -> the
    real per-job LSF status counts (queued/running/pass/fail/killed).
  - `subsystem_maturity_gate.derive_maturity_gate()` -> the real 9.0/9.5/10.0
    composite qualification verdict (integration.proof_level_*).
  - `system_closure_aggregator.aggregate_system_closure()` -> the real
    twelve-dimension worst-wins closure fold, fed from the dimensions this
    module already gathered above (never a second, competing fold).
  - `amba_readiness_gates.evaluate_amba_readiness_gates()` -> the real
    9-gate AMBA M x N readiness fold, when a caller supplies AMBA condition
    evidence (this module discovers none of that evidence itself).
  - `escalation_notify.EscalationNotifier` -> the real "escalation only,
    never routine PASS" mobile-notification discipline, reused rather than
    re-invented for this module's own change-only publish notification.

EVIDENCE TRUTH RULE / GF-AT-28 (mandatory house rule, already enforced by
`golden_flow_readiness.py`, `platform_health.py`, `subsystem_maturity_gate.py`
and every other composite-gate module in this project): UNKNOWN must never
silently become READY/PASS/HEALTHY. `worst_harness_state()` below enforces
this the same way `platform_health.worst()` does -- an empty or all-
NOT_APPLICABLE candidate set folds to UNKNOWN, never to READY, and UNKNOWN
outranks READY in the severity order so one real UNKNOWN input can never be
averaged away by many clean ones.

WORST-WINS AGGREGATION (section 408): a single BLOCKED/UNKNOWN dimension
outranks many clean ones. `worst_harness_state()` is the one fold function
this whole module uses for `harness.state`; every OTHER dimension
(workflow/execution/closure/blockers/resources) is reported as its own,
independently-preserved value and is NEVER collapsed into `harness.state`.

HARNESS-vs-SUBSYSTEM STATE DISTINCTION (section 407) -- the rule this whole
item exists to enforce structurally, not just narrate: `harness.state` is
computed from a `dimension_states` mapping that is ALSO carried on the IR
verbatim (`harness.dimension_states`), so a reader can always see that
e.g. `agent: IDLE` does not, by itself, mean `harness: READY` -- exactly
section 407's own worked example. `assert_harness_state_never_conflates_
subsystem()` (run by every publish) checks this structurally: `harness.state`
must equal `worst_harness_state(dimension_states.values())`, never a value a
caller could have silently substituted from one subsystem's own state.

REUSE OVER REINVENT is enforced, not merely claimed: every gatherer function
below is a thin READ over one real producer, wrapped so that a producer
raising (or being absent) degrades that ONE field to UNKNOWN/None with a
real, named reason recorded in `HarnessStatusIR.unknowns` -- never a crash,
and never a silently-invented value standing in for the fact. `evidence.
source_refs` accumulates the real dotted-path of every producer this
aggregation actually consulted, mirroring `golden_flow_readiness.py`'s own
per-row `fact_source` convention one level up (a whole-IR fact_source list
rather than one per cell).

CHANGE-ONLY NOTIFICATION (mandatory house rule 4): `HarnessStatusService.
publish()` never invents a second notification mechanism. It reuses
`escalation_notify.EscalationNotifier.signoff_blocked()` verbatim -- the
same real, existing, structurally-cannot-fire-on-routine-PASS transport --
and fires it ONLY when a previously-published snapshot is supplied AND the
harness's own `signoff_state` genuinely transitioned INTO a blocked-shaped
value this call (never on every publish while stuck there, and never on a
transition OUT of it or between two non-blocked values).

READ-ONLY, END TO END. No `.dv-harness/` tree is minted to answer any field:
`state.json`/`config.json` are read with a plain, tolerant `json.loads()`
(never `storage.StateStore.load()`/`config.load_config()`, both of which
CREATE their file when absent -- the same discipline `golden_flow_readiness.
py`'s own module docstring already states and this module inherits).
`HarnessStatusService.snapshot()` is the only explicit WRITE path, and it is
never called implicitly by `aggregate()`/`serve()`.

NON-RESPONSIBILITIES (section 410, enforced by `assert_service_authorizes_
nothing()` against this module's own source, the same technique `platform_
health.assert_authorizes_nothing()` already uses): this module never invents
a verification result, never overrides a sibling module's own evidence,
never recomputes an independent signoff policy, never guesses a missing
state, and never hides an UNKNOWN behind a friendlier-looking value.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class HarnessStatusError(ValueError):
    """Base for every refusal in this module -- a real defect (a vocabulary
    that stopped being total, a caller usage error), never a silently
    repaired input."""


# ===========================================================================
# Status vocabulary (section 406) -- REUSED from loop_contract.LoopState
# ===========================================================================

def _loop_state_values() -> Tuple[str, ...]:
    from .loop_contract import LoopState
    return tuple(m.value for m in LoopState)


#: Section 406's core+supporting status vocabulary, built by EXTENDING
#: `loop_contract.LoopState` rather than re-typing it -- that module already
#: models READY/RUNNING/VERIFYING/BLOCKED/HUMAN_GATE/STALE/FAILED/CONVERGING/
#: PLATEAU/OSCILLATING/RETRY_WAIT/BUDGET_EXHAUSTED/CANCELLED, eleven of
#: section 406's own seventeen names, verbatim (search the existing L5 schema
#: registry first, per section 405's own instruction -- LoopState is exactly
#: that existing compatible schema for the STATE half of this one; STOPPED
#: is LoopState's own twelfth reused name, carried through even though
#: section 406 does not name it, because omitting one real LoopState value
#: from this superset would make it not actually be an extension). Only the
#: names LoopState has no reason to carry are added here: PARTIAL and
#: SIGNOFF_READY (section 406's own two remaining core names), UNKNOWN
#: (section 406's tenth core name -- LoopState never needs it because a loop
#: that cannot be observed is reported `PLATEAU_NOT_EVALUATED`-style rather
#: than as a loop STATE), IDLE/WAITING (section 406's two remaining
#: supporting names), and NOT_APPLICABLE (the same "clears without counting
#: as missing evidence" token `system_closure_aggregator.DIMENSION_NOT_
#: APPLICABLE` already establishes one domain over).
_EXTRA_HARNESS_STATES: Tuple[str, ...] = (
    "PARTIAL", "SIGNOFF_READY", "UNKNOWN", "IDLE", "WAITING", "NOT_APPLICABLE",
)


def harness_status_values() -> Tuple[str, ...]:
    return _loop_state_values() + _EXTRA_HARNESS_STATES


HARNESS_STATUS_VALUES: Tuple[str, ...] = harness_status_values()

#: Worst-wins severity (section 408). Higher = more severe = wins the fold.
#: NOT_APPLICABLE is deliberately absent -- it never enters the fold at all
#: (see `worst_harness_state()`), the same "clears without counting" rule
#: `system_closure_aggregator.py` already applies to its own dimension fold.
#:
#: UNKNOWN sits ABOVE READY/SIGNOFF_READY/IDLE on purpose -- GF-AT-28 ("UNKNOWN
#: must never silently become READY"), the same rule `platform_health.
#: HEALTH_SEVERITY` already enforces by ranking UNKNOWN above HEALTHY. It
#: sits BELOW PARTIAL: a partially-measured project is a stronger statement
#: than an unmeasured one, exactly `platform_health.py`'s own reasoning for
#: ranking DEGRADED above UNKNOWN.
HARNESS_STATE_SEVERITY: Dict[str, int] = {
    "SIGNOFF_READY": 0,
    "SUCCESS": 0,
    "READY": 1,
    "IDLE": 1,
    "CREATED": 2,
    "RESUMING": 2,
    "WAITING": 2,
    "CONVERGING": 3,
    "RUNNING": 3,
    "VERIFYING": 3,
    "PARTIAL": 4,
    "UNKNOWN": 5,
    "RETRY_WAIT": 6,
    "PLATEAU": 6,
    "OSCILLATING": 6,
    "BUDGET_EXHAUSTED": 7,
    "STALE": 8,
    "CANCELLED": 8,
    "HUMAN_GATE": 9,
    "BLOCKED": 10,
    "STOPPED": 10,
    "FAILED": 11,
}


def assert_harness_state_vocabulary_total() -> None:
    """Every value `harness_status_values()` declares must have a real
    severity assignment (or be the one deliberate NOT_APPLICABLE exception) --
    the same "a new enum member fails a test rather than silently rendering
    UNKNOWN" discipline `golden_flow_readiness.assert_status_mapping_total()`
    and `loop_contract.assert_status_mapping_total()` already apply to their
    own vocabularies. Run at import."""
    declared = set(HARNESS_STATUS_VALUES)
    covered = set(HARNESS_STATE_SEVERITY) | {"NOT_APPLICABLE"}
    missing = declared - covered
    extra = covered - declared
    if missing or extra:
        raise HarnessStatusError(
            "HARNESS_STATE_SEVERITY_NOT_TOTAL",
        ) from None


assert_harness_state_vocabulary_total()


def worst_harness_state(candidates: Sequence[Optional[str]]) -> str:
    """The worst-wins fold this whole module's `harness.state` computation
    goes through -- and ONLY `harness.state`; every other IR dimension is
    reported independently and never folded here (section 407).

    Mirrors `platform_health.worst()`/`golden_flow_readiness.combine_
    readiness()`: an empty set, an all-`None` set, or an all-`NOT_APPLICABLE`
    set is UNKNOWN -- never READY. `NOT_APPLICABLE` and any value this
    module does not recognize are excluded from the fold rather than
    silently treated as READY."""
    known = [c for c in candidates if c in HARNESS_STATE_SEVERITY]
    if not known:
        return "UNKNOWN"
    return max(known, key=lambda s: HARNESS_STATE_SEVERITY[s])


# ===========================================================================
# HarnessStatusIR (section 405)
# ===========================================================================

@dataclass
class IdentityIR:
    project_id: str = ""
    project_name: str = ""
    mode: Optional[str] = None
    subsystem: Optional[str] = None
    system: Optional[str] = None
    environment: Optional[str] = None


@dataclass
class BaselineIR:
    dut: Optional[str] = None
    dut_version: Optional[str] = None
    rtl_sha: Optional[str] = None
    tb_sha: Optional[str] = None
    spec_version: Optional[str] = None
    register_version: Optional[str] = None
    vip_version: Optional[str] = None
    harness_version: Optional[str] = None


@dataclass
class HarnessBlockIR:
    state: str = "UNKNOWN"
    readiness: str = "UNKNOWN"
    signoff_state: str = "UNKNOWN"
    #: Section 407's own worked example, preserved as real data rather than
    #: only prose: Harness / Workflow / Agent / Loop / Regression / Remote /
    #: Evidence / Signoff, each independently. `state` above is DERIVED from
    #: this mapping via `worst_harness_state()` and is asserted to equal that
    #: derivation on every publish (`assert_harness_state_never_conflates_
    #: subsystem()`) -- it can never silently be one subsystem's own value.
    dimension_states: Dict[str, str] = field(default_factory=dict)


@dataclass
class WorkflowIR:
    current_agent: Optional[str] = None
    current_node: Optional[str] = None
    current_loop: Optional[str] = None
    current_operation: Optional[str] = None
    iteration: Optional[int] = None
    convergence_state: str = "UNKNOWN"


@dataclass
class ExecutionIR:
    queued_jobs: Optional[int] = None
    running_jobs: Optional[int] = None
    passed_jobs: Optional[int] = None
    failed_jobs: Optional[int] = None
    killed_jobs: Optional[int] = None
    wait_license_jobs: Optional[int] = None
    timeout_jobs: Optional[int] = None
    regression_state: str = "UNKNOWN"
    simulation_state: str = "UNKNOWN"


@dataclass
class ClosureIR:
    requirement: str = "UNKNOWN"
    vplan: str = "UNKNOWN"
    functional_coverage: str = "UNKNOWN"
    code_coverage: str = "UNKNOWN"
    assertion: str = "UNKNOWN"
    protocol: str = "UNKNOWN"
    connectivity: str = "UNKNOWN"
    performance: str = "UNKNOWN"
    subsystem: str = "UNKNOWN"
    system: str = "UNKNOWN"


@dataclass
class IntegrationIR:
    proof_level_current: Optional[str] = None
    proof_level_required: Optional[str] = None
    compatibility_state: str = "UNKNOWN"
    resource_conflicts: List[str] = field(default_factory=list)


@dataclass
class BlockersIR:
    critical_failures: int = 0
    critical_unknown: int = 0
    stale_evidence: bool = False
    human_gates: int = 0
    blocked_items: List[str] = field(default_factory=list)


@dataclass
class ResourcesIR:
    remote_execution: str = "UNKNOWN"
    lsf: str = "UNKNOWN"
    license: str = "UNKNOWN"
    vcs: str = "UNKNOWN"
    verdi: str = "UNKNOWN"
    fsdb: str = "UNKNOWN"


@dataclass
class FreshnessIR:
    status_timestamp: Optional[str] = None
    source_timestamp: Optional[str] = None
    stale_after_policy: Optional[float] = None
    state: str = "UNKNOWN"


@dataclass
class EvidenceIR:
    source_refs: List[str] = field(default_factory=list)
    run_id: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class HarnessStatusIR:
    """One canonical record, per master-prompt section 405. `unknowns` is the
    honesty surface this project's other capstone aggregators already
    establish (`subsystem_contract.py`'s own field of the same name): every
    field this aggregation could not resolve lands here as
    `{"field", "reason"}`, never silently dropped or defaulted."""
    identity: IdentityIR = field(default_factory=IdentityIR)
    baseline: BaselineIR = field(default_factory=BaselineIR)
    harness: HarnessBlockIR = field(default_factory=HarnessBlockIR)
    workflow: WorkflowIR = field(default_factory=WorkflowIR)
    execution: ExecutionIR = field(default_factory=ExecutionIR)
    closure: ClosureIR = field(default_factory=ClosureIR)
    integration: IntegrationIR = field(default_factory=IntegrationIR)
    blockers: BlockersIR = field(default_factory=BlockersIR)
    resources: ResourcesIR = field(default_factory=ResourcesIR)
    freshness: FreshnessIR = field(default_factory=FreshnessIR)
    evidence: EvidenceIR = field(default_factory=EvidenceIR)
    unknowns: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": asdict(self.identity),
            "baseline": asdict(self.baseline),
            "harness": asdict(self.harness),
            "workflow": asdict(self.workflow),
            "execution": asdict(self.execution),
            "closure": asdict(self.closure),
            "integration": asdict(self.integration),
            "blockers": asdict(self.blockers),
            "resources": asdict(self.resources),
            "freshness": asdict(self.freshness),
            "evidence": asdict(self.evidence),
            "unknowns": list(self.unknowns),
        }


def assert_harness_state_never_conflates_subsystem(ir: HarnessStatusIR) -> None:
    """Section 407's rule, checked structurally rather than only narrated:
    `harness.state` must equal the worst-wins fold of `harness.
    dimension_states`'s own values -- it can never be silently substituted
    from one subsystem's own reported state (e.g. `agent: IDLE` alone must
    never make `harness.state` read READY)."""
    expected = worst_harness_state(list(ir.harness.dimension_states.values()))
    if ir.harness.state != expected:
        raise HarnessStatusError(
            "HARNESS_STATE_CONFLATES_SUBSYSTEM_STATE",
        ) from None


def unknown_harness_status_ir() -> HarnessStatusIR:
    """The reference "absence of evidence" instance for THIS module's own
    `HarnessStatusIR` shape (plain-string status fields, not `harness_status_
    ir.py`'s separate `StatusField`-based dataclass of the identical name --
    see this project's own CLAUDE.md note on the two independent
    implementations sharing one name). A bare `HarnessStatusIR()` already IS
    this instance: every status-bearing field's own dataclass default is the
    literal string `"UNKNOWN"` (see `HarnessBlockIR`/`WorkflowIR`/`ClosureIR`/
    etc. above), so this is a named convenience for "a project nothing has
    been read about yet" rather than a second construction path -- calling it
    is exactly equivalent to `HarnessStatusIR()`, never a different value."""
    return HarnessStatusIR()


# ===========================================================================
# Reading helpers -- plain, tolerant, NEVER mint a `.dv-harness/` tree
# ===========================================================================

def _read_json_file(path: Path) -> Optional[Dict[str, Any]]:
    """`json.loads(path.read_text())`, tolerant of an absent or malformed
    file -- returns `None` rather than raising. Deliberately NOT `storage.
    StateStore.load()`/`config.load_config()`: both of those CREATE their
    file (and the whole `.dv-harness/` tree) when absent, which would turn
    merely asking "what is this project's status" into a mutation of the
    project's own governance state -- the same reasoning `golden_flow_
    readiness.py`'s own module docstring and `signoff_export.read_signoff_
    stage_status()` already state for the identical file."""
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _default_config(root: Path) -> Dict[str, Any]:
    """The same "materialize DEFAULT_CONFIG in memory, never on disk, unless
    a real config.json already exists" trick `golden_flow_readiness.
    _gather_facts()` already uses -- avoided here by simply reading whatever
    is on disk (or an empty dict), since this module never needs `config.
    load_config()`'s own merge/validation logic."""
    cfg = _read_json_file(root / ".dv-harness" / "config.json")
    return cfg or {}


def _safe(source_refs: List[str], unknowns: List[Dict[str, str]],
          fact_source: str, fn, *args, **kwargs) -> Any:
    """Call `fn(*args, **kwargs)`, always recording `fact_source` as
    consulted. On any exception the failure is recorded as an honest,
    named unknown and `None` is returned -- the same "a probe bug must not
    delete a mandatory row" discipline `golden_flow_readiness.derive_golden_
    flow_readiness()` and `subsystem_maturity_gate.derive_maturity_gate()`
    already apply to their own per-row/per-condition evaluators. A real,
    reproduced example of exactly the failure this guards against:
    `signoff_export._capture_evidence_hashes()`'s documented `TypeError` the
    first time a project's `normalized_evidence` table actually holds rows
    (see this repo's CLAUDE.md `subsystem_contract.py` section)."""
    source_refs.append(fact_source)
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 -- one producer's bug must not
        # crash the whole aggregation; see docstring above.
        unknowns.append({"field": fact_source,
                          "reason": f"{type(e).__name__}: {e}"})
        return None


# ===========================================================================
# Global State Aggregator (section 409)
# ===========================================================================

#: `platform_health.SubsystemHealth.state` -> HARNESS_STATUS_VALUES.
_HEALTH_TO_HARNESS_STATE: Dict[str, str] = {
    "HEALTHY": "READY", "DEGRADED": "PARTIAL", "CRITICAL": "BLOCKED",
    "UNKNOWN": "UNKNOWN",
}
#: `models.Status` (a stage/gate verdict) -> HARNESS_STATUS_VALUES, for the
#: SIGNOFF stage's own recorded status specifically -- deliberately NOT
#: `golden_flow_readiness.STATUS_TO_READINESS` (which floors everything to
#: READY/PARTIAL/BLOCKED/UNKNOWN): the signoff dimension additionally needs
#: to say SIGNOFF_READY, section 405's own distinct name for "the SIGNOFF
#: stage genuinely passed", not merely "connected with evidence".
_SIGNOFF_STATUS_TO_STATE: Dict[str, str] = {
    "PASS": "SIGNOFF_READY", "CLOSED": "SIGNOFF_READY",
    "ACCEPTED_RISK": "PARTIAL", "PARTIAL": "PARTIAL", "RUNNING": "RUNNING",
    "RETRY": "RETRY_WAIT", "WAIT_USER": "HUMAN_GATE",
    "FAIL": "BLOCKED", "BLOCKED": "BLOCKED", "NOT_STARTED": "UNKNOWN",
}
#: `subsystem_maturity_gate` verdict -> HARNESS_STATUS_VALUES.
_MATURITY_VERDICT_TO_STATE: Dict[str, str] = {
    "QUALIFIED": "READY", "NOT_QUALIFIED": "BLOCKED",
    "INCOMPLETE_EVIDENCE": "UNKNOWN",
}
#: `system_closure_aggregator` verdict -> HARNESS_STATUS_VALUES.
_CLOSURE_VERDICT_TO_STATE: Dict[str, str] = {
    "CLOSED": "READY", "NOT_CLOSED": "BLOCKED", "INCOMPLETE_EVIDENCE": "UNKNOWN",
}
#: `loop_stale_detection` verdict -> HARNESS_STATUS_VALUES (already shares
#: STALE/UNKNOWN literally; NOT_STALE is this module's own extra mapping).
_STALENESS_TO_STATE: Dict[str, str] = {
    "STALE": "STALE", "NOT_STALE": "READY", "UNKNOWN": "UNKNOWN",
}

def _gather_identity(root: Path, state: Optional[dict], cfg: Dict[str, Any]
                     ) -> IdentityIR:
    """`identity.mode`/`subsystem`/`system`/`environment` have no code
    producer anywhere in this harness -- the Execution Mode Gate (LOCAL_
    ANALYSIS vs REMOTE_EXECUTION) is declared per-message agent prose, never
    persisted to a file, and no module records which subsystem/system a
    project root represents. They read from `config.json`'s own declared
    fields when a project has chosen to record one there, else stay `None` --
    deliberately NOT added to `unknowns`: an absent field with no real
    producer is a structural fact about this harness, not a producer that
    failed to answer."""
    project = None
    if isinstance(state, dict):
        project = state.get("project")
    name = str(project or root.name)
    return IdentityIR(
        project_id=name,
        project_name=name,
        mode=cfg.get("execution_mode") or cfg.get("mode"),
        subsystem=cfg.get("subsystem"),
        system=cfg.get("system"),
        environment=cfg.get("environment"),
    )


def _gather_baseline(root: Path, source_refs: List[str],
                     unknowns: List[Dict[str, str]]) -> BaselineIR:
    from . import __version__ as _harness_version
    doc = _safe(source_refs, unknowns,
                "dv_harness.signoff_export.capture_baseline",
                lambda: __import__("dv_harness.signoff_export",
                                    fromlist=["capture_baseline"])
                        .capture_baseline(root))
    fields = (doc or {}).get("fields") or {}

    def field_value(name: str, extract):
        rec = fields.get(name)
        if not rec or rec.get("status") != "CAPTURED":
            if rec is not None:
                unknowns.append({
                    "field": f"baseline.{name}",
                    "reason": rec.get("reason") or "NOT_CAPTURED",
                })
            return None
        try:
            return extract(rec)
        except Exception:
            return None

    rtl_sha = field_value("dut_sha", lambda r: r.get("digest"))
    tb_sha = field_value("tb_sha", lambda r: r.get("digest"))
    spec_version = field_value(
        "spec_version", lambda r: (r.get("detail") or {}).get("value"))
    vip_version = field_value(
        "vip_tool_versions",
        lambda r: (r.get("detail") or {}).get("summary")
        or (r.get("digest") and f"digest:{r['digest'][:12]}"))

    return BaselineIR(
        dut=None,
        dut_version=None,
        rtl_sha=rtl_sha,
        tb_sha=tb_sha,
        spec_version=spec_version,
        register_version=None,
        vip_version=vip_version,
        harness_version=_harness_version,
    )


def _gather_platform_health(root: Path, source_refs: List[str],
                            unknowns: List[Dict[str, str]]) -> Optional[dict]:
    return _safe(source_refs, unknowns,
                 "dv_harness.platform_health.platform_health_report",
                 lambda: __import__("dv_harness.platform_health",
                                     fromlist=["platform_health_report"])
                         .platform_health_report(root))


def _subsystem_state(health_report: Optional[dict], subsystem: str) -> str:
    if not health_report:
        return "UNKNOWN"
    for s in health_report.get("subsystems") or []:
        if s.get("subsystem") == subsystem:
            return _HEALTH_TO_HARNESS_STATE.get(s.get("state"), "UNKNOWN")
    return "UNKNOWN"


def _gather_loop(root: Path, source_refs: List[str],
                 unknowns: List[Dict[str, str]]) -> WorkflowIR:
    payload = _safe(source_refs, unknowns,
                     "dv_harness.loop_telemetry.read_loop_telemetry",
                     lambda: __import__("dv_harness.loop_telemetry",
                                         fromlist=["read_loop_telemetry"])
                             .read_loop_telemetry(root))
    if not payload or not payload.get("available"):
        if payload is not None:
            unknowns.append({"field": "workflow", "reason": payload.get(
                "reason") or "no loop telemetry recorded"})
        return WorkflowIR()
    rows = payload.get("rows") or []
    if not rows:
        return WorkflowIR()
    latest = rows[0]  # newest session first, per read_loop_telemetry()
    return WorkflowIR(
        current_agent=None,
        current_node=None,
        current_loop=latest.get("loop"),
        current_operation=latest.get("next_action") or None,
        iteration=latest.get("iteration"),
        convergence_state=str(latest.get("state") or "UNKNOWN"),
    )


def _gather_current_stage(state: Optional[dict]) -> Tuple[Optional[str], Optional[str]]:
    """(current_node, stage_status) straight off `state.json`'s own real
    `current_stage`/`stages[...]`."""
    if not isinstance(state, dict):
        return None, None
    node = state.get("current_stage")
    status = None
    if node:
        rec = (state.get("stages") or {}).get(node)
        if isinstance(rec, dict):
            status = rec.get("status")
    return node, status


def _gather_execution(root: Path, source_refs: List[str],
                      unknowns: List[Dict[str, str]]) -> ExecutionIR:
    jobs = _safe(source_refs, unknowns,
                 "dv_harness.regression_reporter.load_jobs",
                 lambda: __import__("dv_harness.regression_reporter",
                                     fromlist=["load_jobs"]).load_jobs(root))
    if jobs is None:
        return ExecutionIR()
    summary = _safe(source_refs, unknowns,
                     "dv_harness.dashboard._lsf_summary",
                     lambda: __import__("dv_harness.dashboard",
                                         fromlist=["_lsf_summary"])
                             ._lsf_summary(jobs))
    if not summary:
        return ExecutionIR()
    if not jobs:
        return ExecutionIR(queued_jobs=0, running_jobs=0, passed_jobs=0,
                            failed_jobs=0, killed_jobs=0,
                            regression_state="IDLE", simulation_state="IDLE")
    running = int(summary.get("RUN") or 0)
    regression_state = "RUNNING" if running > 0 else (
        "BLOCKED" if summary.get("fail_confirmed") else "READY")
    # wait_license/timeout are not tracked per-job by any real producer in
    # this harness (see regression_reporter.py/lsf_client.py -- no
    # per-job "waiting on license"/"timed out" flag exists) -- reported
    # honestly absent rather than a fabricated zero.
    unknowns.append({"field": "execution.wait_license_jobs",
                      "reason": "no per-job wait-on-license counter is "
                                "recorded by lsf_client.py/regression_"
                                "reporter.py"})
    unknowns.append({"field": "execution.timeout_jobs",
                      "reason": "no per-job timeout counter is recorded by "
                                "lsf_client.py/regression_reporter.py"})
    return ExecutionIR(
        queued_jobs=int(summary.get("PEND") or 0),
        running_jobs=running,
        passed_jobs=int(summary.get("pass_confirmed") or 0),
        failed_jobs=int(summary.get("fail_confirmed") or 0),
        killed_jobs=int(summary.get("early_kill") or 0),
        wait_license_jobs=None,
        timeout_jobs=None,
        regression_state=regression_state,
        simulation_state=("RUNNING" if running > 0 else "IDLE"),
    )


def _gather_closure(root: Path, cfg: Dict[str, Any], source_refs: List[str],
                    unknowns: List[Dict[str, str]],
                    health_report: Optional[dict]) -> Tuple[ClosureIR, str]:
    """Returns `(ClosureIR, golden_flow_overall_status)`."""
    matrix = _safe(source_refs, unknowns,
                    "dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
                    lambda: __import__("dv_harness.golden_flow_readiness",
                                        fromlist=["derive_golden_flow_readiness"])
                            .derive_golden_flow_readiness(root, cfg))
    rows_by_id = {r["row_id"]: r for r in (matrix or {}).get("rows") or []}
    overall = (matrix or {}).get("golden_flow_readiness") or "UNKNOWN"

    def row_status(row_id: str) -> str:
        r = rows_by_id.get(row_id)
        if not r:
            unknowns.append({"field": f"closure(<-{row_id})",
                              "reason": "golden_flow_readiness row not "
                                        "available"})
            return "UNKNOWN"
        return r.get("status") or "UNKNOWN"

    coverage_collection = row_status("coverage_collection")
    coverage_holes = row_status("coverage_hole_analysis")
    functional_coverage = worst_harness_state(
        [coverage_collection, coverage_holes])

    connectivity = _subsystem_state(health_report, "connectivity_gates")
    if connectivity == "UNKNOWN":
        unknowns.append({"field": "closure.connectivity",
                          "reason": "platform_health connectivity_gates "
                                    "subsystem UNKNOWN (never run, or "
                                    "not configured)"})
    unknowns.append({"field": "closure.code_coverage",
                      "reason": "no distinct code-coverage row exists in "
                                "golden_flow_readiness -- only functional "
                                "coverage is tracked"})
    unknowns.append({"field": "closure.performance",
                      "reason": "no performance-requirement evidence was "
                                "supplied to this aggregation (see amba_"
                                "performance_readiness_gates.py, "
                                "caller-declared only)"})

    closure = ClosureIR(
        requirement=row_status("requirement_extraction"),
        vplan=row_status("vplan_traceability"),
        functional_coverage=functional_coverage,
        code_coverage="UNKNOWN",
        assertion=row_status("verification_contract"),
        protocol=row_status("protocol_topology_discovery"),
        connectivity=connectivity,
        performance="UNKNOWN",
        subsystem="UNKNOWN",
        system="UNKNOWN",
    )
    return closure, overall


def _gather_maturity(root: Path, source_refs: List[str],
                     unknowns: List[Dict[str, str]]) -> IntegrationIR:
    report = _safe(source_refs, unknowns,
                    "dv_harness.subsystem_maturity_gate.derive_maturity_gate",
                    lambda: __import__("dv_harness.subsystem_maturity_gate",
                                        fromlist=["derive_maturity_gate"])
                            .derive_maturity_gate("9.0", root))
    if not report:
        return IntegrationIR()
    verdict = report.get("verdict") or "INCOMPLETE_EVIDENCE"
    return IntegrationIR(
        proof_level_current=("9.0" if verdict == "QUALIFIED" else None),
        proof_level_required="9.0",
        compatibility_state=_MATURITY_VERDICT_TO_STATE.get(verdict, "UNKNOWN"),
        resource_conflicts=[],
    )


def _gather_blockers(root: Path, source_refs: List[str],
                     unknowns: List[Dict[str, str]],
                     health_report: Optional[dict],
                     staleness: Optional[dict]) -> BlockersIR:
    from . import question_queue as qq
    store = qq.QuestionQueueStore(root)
    open_blocking = _safe(source_refs, unknowns,
                           "dv_harness.question_queue.QuestionQueueStore.list_questions",
                           lambda: store.list_questions(status="OPEN",
                                                        blocking=True))
    open_blocking = open_blocking or []
    blocked_items = [str(q.get("question") or q.get("id"))
                      for q in open_blocking][:20]

    critical_failures = 0
    critical_unknown = 0
    if health_report:
        for s in health_report.get("subsystems") or []:
            if s.get("state") == "CRITICAL":
                critical_failures += 1
            elif s.get("state") == "UNKNOWN":
                critical_unknown += 1
    else:
        unknowns.append({"field": "blockers.critical_failures",
                          "reason": "platform_health report unavailable"})

    stale_evidence = bool(staleness and staleness.get("status") == "STALE")

    return BlockersIR(
        critical_failures=critical_failures,
        critical_unknown=critical_unknown,
        stale_evidence=stale_evidence,
        human_gates=len(open_blocking),
        blocked_items=blocked_items,
    )


def _gather_resources(health_report: Optional[dict]) -> ResourcesIR:
    return ResourcesIR(
        remote_execution="UNKNOWN",  # see docstring: no local artifact
        lsf=_subsystem_state(health_report, "lsf_queue"),
        license=_subsystem_state(health_report, "eda_license"),
        vcs=_subsystem_state(health_report, "execution_environment"),
        verdi="UNKNOWN",
        fsdb="UNKNOWN",
    )


def _gather_freshness(root: Path, source_refs: List[str],
                      unknowns: List[Dict[str, str]]
                      ) -> Tuple[FreshnessIR, Optional[dict]]:
    try:
        from . import loop_stale_detection as lsd
    except Exception as e:
        unknowns.append({"field": "freshness",
                          "reason": f"loop_stale_detection import failed: "
                                    f"{type(e).__name__}: {e}"})
        return FreshnessIR(state="UNKNOWN"), None
    staleness = _safe(source_refs, unknowns,
                       "dv_harness.loop_stale_detection.detect_loop_staleness",
                       lsd.detect_loop_staleness, root)
    window = _safe(source_refs, unknowns,
                    "dv_harness.loop_stale_detection.declared_stale_window_seconds",
                    lsd.declared_stale_window_seconds, root)
    status = (staleness or {}).get("status") or "UNKNOWN"
    return FreshnessIR(
        status_timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        source_timestamp=None,
        stale_after_policy=window,
        state=_STALENESS_TO_STATE.get(status, "UNKNOWN"),
    ), staleness


def _gather_evidence(source_refs: List[str], workflow: WorkflowIR
                     ) -> EvidenceIR:
    return EvidenceIR(
        source_refs=list(dict.fromkeys(source_refs)),
        run_id=workflow.current_loop,
        session_id=workflow.current_loop,
    )


class GlobalStateAggregator:
    """Section 409's assembler: normalizes already-real canonical state into
    ONE `HarnessStatusIR`. It is deliberately NOT an independent
    verification oracle -- every gatherer above is a thin read over one
    real producer, and `assemble()` performs no analysis of its own beyond
    the documented worst-wins folds."""

    @staticmethod
    def assemble(root: Path | str, *, cfg: Optional[Dict[str, Any]] = None
                 ) -> HarnessStatusIR:
        root = Path(root)
        source_refs: List[str] = []
        unknowns: List[Dict[str, str]] = []

        state = _read_json_file(root / ".dv-harness" / "state.json")
        source_refs.append("dv_harness.harness_status._read_json_file(state.json)")
        effective_cfg = cfg if cfg is not None else _default_config(root)
        source_refs.append("dv_harness.harness_status._default_config(config.json)")

        identity = _gather_identity(root, state, effective_cfg)
        baseline = _gather_baseline(root, source_refs, unknowns)
        health_report = _gather_platform_health(root, source_refs, unknowns)
        workflow = _gather_loop(root, source_refs, unknowns)
        current_node, stage_status = _gather_current_stage(state)
        if current_node and not workflow.current_node:
            workflow.current_node = current_node
        execution = _gather_execution(root, source_refs, unknowns)
        closure, gfr_overall = _gather_closure(
            root, effective_cfg, source_refs, unknowns, health_report)
        integration = _gather_maturity(root, source_refs, unknowns)
        freshness, staleness = _gather_freshness(root, source_refs, unknowns)
        blockers = _gather_blockers(root, source_refs, unknowns,
                                     health_report, staleness)
        resources = _gather_resources(health_report)

        # -- system_closure_aggregator: reuse its own worst-wins fold rather
        # than re-deriving one, fed from whichever of the twelve dimensions
        # this pass genuinely has evidence for. Dimensions with no real
        # feed here report NOT_SUPPLIED honestly (that module's own
        # vocabulary) and fold into its INCOMPLETE_EVIDENCE verdict, never
        # a fabricated CLOSED.
        from . import system_closure_aggregator as sca
        dimension_records = [
            {"dimension_name": "functional_coverage",
             "status": closure.functional_coverage},
            {"dimension_name": "protocol_coverage", "status": closure.protocol},
            {"dimension_name": "requirement_closure", "status": closure.requirement},
            {"dimension_name": "regression_status", "status": execution.regression_state},
        ]
        closure_report = sca.aggregate_system_closure(dimension_records)
        closure.system = _CLOSURE_VERDICT_TO_STATE.get(
            closure_report.get("overall_status"), "UNKNOWN")
        source_refs.append("dv_harness.system_closure_aggregator.aggregate_system_closure")

        # -- signoff dimension, from signoff_export's own real reader
        signoff_status_doc = _safe(
            source_refs, unknowns,
            "dv_harness.signoff_export.read_signoff_stage_status",
            lambda: __import__("dv_harness.signoff_export",
                                fromlist=["read_signoff_stage_status"])
                    .read_signoff_stage_status(root))
        stage_status_from_signoff = (signoff_status_doc or {}).get("stage_status")
        signoff_state = _SIGNOFF_STATUS_TO_STATE.get(
            stage_status_from_signoff or stage_status or "", "UNKNOWN")

        # -- section 407: preserve every dimension independently, never
        # fold one into another.
        agent_state = _subsystem_state(health_report, "agent_adapter")
        dimension_states: Dict[str, str] = {
            "workflow": workflow.convergence_state,
            "agent": agent_state,
            "loop": workflow.convergence_state,
            "regression": execution.regression_state,
            "remote": resources.remote_execution,
            "evidence": freshness.state,
            "signoff": signoff_state,
            "closure": gfr_overall,
        }
        harness_state = worst_harness_state(list(dimension_states.values()))
        dimension_states["harness"] = harness_state

        harness = HarnessBlockIR(
            state=harness_state,
            readiness=gfr_overall,
            signoff_state=signoff_state,
            dimension_states=dimension_states,
        )

        evidence = _gather_evidence(source_refs, workflow)

        ir = HarnessStatusIR(
            identity=identity, baseline=baseline, harness=harness,
            workflow=workflow, execution=execution, closure=closure,
            integration=integration, blockers=blockers, resources=resources,
            freshness=freshness, evidence=evidence, unknowns=unknowns,
        )
        assert_harness_state_never_conflates_subsystem(ir)
        return ir


# ===========================================================================
# HarnessStatusService (section 410) -- the callable read-only front-end
# ===========================================================================

#: Identifiers this module must never reference. Serving a status must not
#: become a way to grant, satisfy or bypass a human decision -- the same
#: technique `platform_health.assert_authorizes_nothing()` already applies
#: to itself, restated here for this module's own source.
_FORBIDDEN_AUTHORIZATION_SYMBOLS: Tuple[str, ...] = (
    "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError",
    "ControlPlane", "can_signoff", "assert_human_approval", "approve(",
)


def assert_service_authorizes_nothing(source_path: Optional[Path] = None) -> None:
    """This file's source may not mention any approval/authorization
    symbol -- a status report observes, it never authorizes. Mirrors
    `platform_health.assert_authorizes_nothing()`."""
    path = Path(source_path) if source_path else Path(__file__)
    text = path.read_text(encoding="utf-8")
    body = text.split('_FORBIDDEN_AUTHORIZATION_SYMBOLS: Tuple[str, ...] = (', 1)
    haystack = body[0].split('"""', 2)[-1] if len(body) > 1 else text
    hits = [s for s in _FORBIDDEN_AUTHORIZATION_SYMBOLS if s in haystack]
    if hits:
        raise HarnessStatusError(
            f"{path.name} references authorization machinery {hits}; a "
            f"status service must observe, never authorize.")


assert_service_authorizes_nothing()


# ===========================================================================
# Status History Audit (section 435) -- persist snapshots via the real
# StateStore.event() trail, never a second audit file
# ===========================================================================

#: The one events.jsonl event name this module ever writes for a persisted
#: `HarnessStatusIR` snapshot. Reuses the SAME real `.dv-harness/events.jsonl`
#: trail `loop_telemetry.emit()`, `engine.py`'s own `*_DECISION`/`*_FAILED`
#: events and every other audit mechanism in this project already write
#: through `storage.StateStore.event()` -- section 435's own "never a second
#: audit file" rule, enforced by construction rather than only narrated:
#: this module has no writer of its own, only a caller of the one real
#: `StateStore.event()`.
HARNESS_STATUS_SNAPSHOT_EVENT = "HARNESS_STATUS_SNAPSHOT"

#: The honest empty-history reason, naming the real producer -- mirrors
#: `loop_telemetry.NO_LOOP_TELEMETRY`'s own convention for the identical
#: "nothing was ever recorded" fact. GF-AT-28 applied to history: an absent
#: trail must read as "no history recorded" and NEVER as a silently-fabricated
#: clean/empty/good state.
NO_HARNESS_STATUS_HISTORY = "NO_HARNESS_STATUS_SNAPSHOT_EVENTS_RECORDED"

#: Same default trailing-window size `loop_telemetry.DEFAULT_EVENT_SCAN_LINES`
#: already uses for the identical "this runs on a dashboard HTTP thread, cap
#: the read" reason -- restated here rather than imported so this module's
#: own default does not silently drift if that constant's value is retuned
#: for loop-telemetry-specific reasons unrelated to status history.
DEFAULT_HISTORY_SCAN_LINES = 20000


def record_harness_status_snapshot(store: Any, ir: HarnessStatusIR, *,
                                   trigger: str = "manual",
                                   user_agent_action: Optional[str] = None,
                                   ) -> Dict[str, Any]:
    """Write ONE `HarnessStatusIR` snapshot through the real `StateStore.
    event()` -- the identical write path `loop_telemetry.emit()` already uses
    for section 108's own events, reused rather than re-implemented (this
    function has no writer of its own; it calls `store.event(...)` exactly
    once). `store` is a real `storage.StateStore` (duck-typed: any object
    exposing a real `.event(dict)` method), always a caller-supplied,
    EXPLICIT argument -- never constructed here -- so persisting a snapshot
    is always a deliberate act, matching every other explicit-write function
    in this project (`signoff_export.freeze_signoff_baseline()`,
    `subsystem_contract.write_subsystem_contract()`, ...): a project asking
    only `aggregate()`/`serve()`/`publish()` for its current status must
    never gain a `.dv-harness/` tree or a history entry it did not ask for.

    The full snapshot (`ir.to_dict()`) is carried on the event so a later
    reader can reconstruct the exact historical `HarnessStatusIR` this
    session observed -- not merely its top-line `harness.state` -- while the
    handful of fields a human/GUI most often filters on (`harness_state`,
    `readiness`, `signoff_state`, `unknown_count`, `run_id`) are ALSO
    promoted to the event's own top level, mirroring `loop_telemetry.emit()`'s
    own `loop_id`/`run_id`/`iteration`/`stage` promotion of its own most
    frequently-filtered fields.

    Section 435's own named transition fields are carried alongside those,
    additive over this record's pre-existing shape and never a second audit
    file: `previous_state` is THIS SAME project's own most recently recorded
    `harness_state`, read back through `read_harness_status_history()` off
    `store.root` -- never a second, separately-tracked "last state" cache,
    and never assumed from an in-memory value that would not survive a fresh
    CLI invocation. A store with no real `.root` attribute (an ad hoc
    duck-typed store, per this function's own documented contract), a
    project with no prior recorded snapshot, or a failed history read all
    degrade `previous_state` honestly to `None` -- never a guessed prior
    state. `transitioned` is `previous_state != harness_state` and is itself
    `None` (never `False`) whenever `previous_state` is `None`: "there was no
    prior snapshot to compare against" must never read the same as "compared,
    and nothing changed" -- the identical GF-AT-28 "two different kinds of
    unknown must never collapse into one value" discipline this whole
    project already applies everywhere else, applied here to a transition
    rather than a status. `trigger` and `user_agent_action` are section 435's
    own "Trigger" / "User/Agent Action" fields -- plain, caller-declared
    context this function never infers on its own (it has no way to know WHY
    a caller invoked it), mirroring `question_queue.build_digest(trigger=...)`
    's identical caller-declared-trigger convention including its own
    `"manual"` default for an explicit ad hoc call; `user_agent_action`
    defaults to `None` (nothing attributed) rather than a fabricated actor."""
    from .engine import now  # the one timestamp format every event here uses
    previous_state: Optional[str] = None
    root = getattr(store, "root", None)
    if root is not None:
        try:
            prior = read_harness_status_history(root)
        except Exception:
            prior = None
        if prior and prior.get("available"):
            previous_state = prior["latest"].get("harness_state")
    transitioned: Optional[bool] = (
        None if previous_state is None else (previous_state != ir.harness.state))
    record: Dict[str, Any] = {
        "ts": now(),
        "event": HARNESS_STATUS_SNAPSHOT_EVENT,
        "harness_state": ir.harness.state,
        "previous_state": previous_state,
        "transitioned": transitioned,
        "trigger": trigger,
        "user_agent_action": user_agent_action,
        "readiness": ir.harness.readiness,
        "signoff_state": ir.harness.signoff_state,
        "unknown_count": len(ir.unknowns),
        "run_id": ir.evidence.run_id,
        "snapshot": ir.to_dict(),
    }
    store.event(record)
    return record


def read_harness_status_history(root: Path | str, *,
                                scan_lines: int = DEFAULT_HISTORY_SCAN_LINES
                                ) -> Dict[str, Any]:
    """The real recorded `HarnessStatusIR` snapshot history for `root`, oldest
    first -- read through `loop_telemetry.read_events()` (reused verbatim,
    never a second `events.jsonl` parser: this project already has one real
    reader for the trailing window of that file -- `loop_telemetry.
    _read_events()`, whose public `read_events` alias `platform_health.py`
    already reuses instead of adding a third -- and this module adds no
    fourth). A project with no recorded snapshot reports `available: False`
    naming the real reason (`NO_HARNESS_STATUS_HISTORY`) rather than an empty
    list a caller could misread as "checked, and the history really is empty
    in a good way" -- the identical honesty `loop_telemetry.
    previous_session_summary()` already applies to a loop that has never
    run, and the identical GF-AT-28 rule `worst_harness_state()` above
    already enforces one level down: absence of evidence must never silently
    become a good answer, including "there is nothing to worry about"."""
    from .loop_telemetry import read_events
    entries, scanned, truncated = read_events(Path(root), scan_lines=scan_lines)
    history = [e for e in entries if e.get("event") == HARNESS_STATUS_SNAPSHOT_EVENT]
    if not history:
        return {
            "available": False,
            "reason": NO_HARNESS_STATUS_HISTORY,
            "history": [],
            "count": 0,
            "lines_scanned": scanned,
            "scan_truncated": truncated,
        }
    return {
        "available": True,
        "history": history,
        "count": len(history),
        "latest": history[-1],
        "lines_scanned": scanned,
        "scan_truncated": truncated,
    }


class HarnessStatusService:
    """Section 410's callable read-only front-end. Every other consumer
    (Claude CLI's persistent status bar, a GUI/Web control-plane page)
    should call THIS class, never `GlobalStateAggregator` directly and
    never re-derive its own copy of `harness.state` -- section 411's
    forbidden architecture ("CLI calculates one state, GUI calculates
    another") is exactly what routing every renderer through one service
    instance prevents.

    Responsibilities (section 410): aggregate, normalize, validate,
    publish, snapshot, serve. Non-responsibilities, enforced by
    `assert_service_authorizes_nothing()` above and by this class never
    importing a verification-verdict-producing engine of its own: invent
    verification results, override evidence, recompute independent signoff
    policy, guess missing state, hide UNKNOWN.
    """

    def __init__(self, root: Path | str, *,
                 notifier: Optional[Any] = None):
        self.root = Path(root)
        self.notifier = notifier
        self._last_published: Optional[HarnessStatusIR] = None

    # -- aggregate ----------------------------------------------------------
    def aggregate(self, *, cfg: Optional[Dict[str, Any]] = None
                 ) -> HarnessStatusIR:
        return GlobalStateAggregator.assemble(self.root, cfg=cfg)

    # -- normalize ------------------------------------------------------
    def normalize(self, ir: HarnessStatusIR) -> HarnessStatusIR:
        """Coerce every reported status-shaped string onto the canonical
        `HARNESS_STATUS_VALUES` vocabulary (section 406: "CLI, GUI, and Web
        shall use the same canonical status vocabulary"). A value this
        module does not recognize is normalized to `UNKNOWN` rather than
        rendered verbatim -- an unrecognized status string must never reach
        a renderer looking like a legitimate one."""
        def norm(value: str) -> str:
            return value if value in HARNESS_STATUS_VALUES else "UNKNOWN"

        ir.harness.state = norm(ir.harness.state)
        ir.harness.readiness = norm(ir.harness.readiness)
        ir.harness.signoff_state = norm(ir.harness.signoff_state)
        ir.harness.dimension_states = {
            k: norm(v) for k, v in ir.harness.dimension_states.items()}
        ir.workflow.convergence_state = norm(ir.workflow.convergence_state)
        ir.execution.regression_state = norm(ir.execution.regression_state)
        ir.execution.simulation_state = norm(ir.execution.simulation_state)
        ir.freshness.state = norm(ir.freshness.state)
        return ir

    # -- validate ---------------------------------------------------------
    def validate(self, ir: HarnessStatusIR) -> HarnessStatusIR:
        """Structural checks a caller can trust before publishing:
        `harness.state` never conflates a subsystem's own state (section
        407), and GF-AT-28 holds (an all-UNKNOWN dimension set never reads
        as READY/SIGNOFF_READY)."""
        assert_harness_state_never_conflates_subsystem(ir)
        if all(v == "UNKNOWN" for v in ir.harness.dimension_states.values()):
            if ir.harness.state in ("READY", "SIGNOFF_READY"):
                raise HarnessStatusError(
                    "GF_AT_28_VIOLATION: all dimensions UNKNOWN but "
                    "harness.state resolved to a ready-shaped value")
        return ir

    # -- snapshot -----------------------------------------------------------
    def snapshot(self, ir: HarnessStatusIR) -> Dict[str, Any]:
        """The JSON-serializable record. A pure transform -- no I/O."""
        return ir.to_dict()

    # -- serve --------------------------------------------------------------
    def serve(self, *, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """aggregate -> normalize -> validate -> snapshot, in one call --
        the shape a CLI status-bar renderer or a GUI/Web endpoint actually
        wants. Read-only end to end."""
        ir = self.aggregate(cfg=cfg)
        ir = self.normalize(ir)
        ir = self.validate(ir)
        return self.snapshot(ir)

    # -- publish (change-only notification, house rule 4) -------------
    def publish(self, *, cfg: Optional[Dict[str, Any]] = None
               ) -> Tuple[Dict[str, Any], Optional[Any]]:
        """aggregate/normalize/validate, then -- CHANGE-ONLY -- reuse
        `escalation_notify.EscalationNotifier`'s own real, existing
        discipline (never a routine-PASS notification, never a second
        transport mechanism) to fire on a genuine transition of `harness.
        signoff_state` INTO a blocked-shaped value.

        Returns `(snapshot_dict, escalation_event_or_None)`. `notifier`
        (an `escalation_notify.EscalationNotifier`) is only ever consulted
        when it was supplied at construction AND a PREVIOUS `publish()`
        call on this same service instance recorded a different signoff
        state -- the first `publish()` in a session's life can never fire
        (there is nothing to compare against), matching escalation_notify.
        py's own "never on a state nobody has seen change" posture.
        """
        ir = self.validate(self.normalize(self.aggregate(cfg=cfg)))
        event = None
        if self.notifier is not None and self._last_published is not None:
            prev_signoff = self._last_published.harness.signoff_state
            curr_signoff = ir.harness.signoff_state
            newly_blocked = (curr_signoff == "BLOCKED"
                             and prev_signoff != "BLOCKED")
            if newly_blocked:
                event = self.notifier.signoff_blocked(
                    stage=ir.workflow.current_node or "SIGNOFF",
                    reasons=f"harness signoff_state transitioned "
                            f"{prev_signoff} -> {curr_signoff}",
                )
        self._last_published = ir
        return self.snapshot(ir), event

    # -- record (status history audit, section 435) ---------------------
    def record(self, store: Any, *, cfg: Optional[Dict[str, Any]] = None,
              trigger: str = "manual", user_agent_action: Optional[str] = None
              ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """aggregate -> normalize -> validate, then PERSIST through the real
        `store.event()` trail via `record_harness_status_snapshot()` -- the
        one explicit write path this class exposes for a durable HISTORY of
        `HarnessStatusIR` snapshots, distinct from `publish()`'s change-only
        NOTIFICATION above (which fires a transport on a genuine signoff
        transition but writes no audit record of its own -- the two are
        independent mechanisms for independent house rules, 3 and 5, and a
        caller may use either, both, or neither).

        `store` is always required and always caller-supplied -- never
        defaulted or constructed here -- so `aggregate()`/`normalize()`/
        `validate()`/`snapshot()`/`serve()`/`publish()` all stay exactly as
        read-only as before this method existed; calling `record()` itself,
        with a real `storage.StateStore`, is the one deliberate opt-in that
        mints `.dv-harness/events.jsonl` if it does not already exist.

        `trigger`/`user_agent_action` pass straight through to
        `record_harness_status_snapshot()` -- section 435's own "Trigger" /
        "User/Agent Action" fields, plain caller-declared context this
        method never infers (a stage-boundary caller might pass
        `trigger="stage_boundary", user_agent_action="SIGNOFF PASS
        (engine.run_stage)"`; a human-run CLI call keeps the honest
        `"manual"`/`None` defaults)."""
        ir = self.validate(self.normalize(self.aggregate(cfg=cfg)))
        event_record = record_harness_status_snapshot(
            store, ir, trigger=trigger, user_agent_action=user_agent_action)
        return self.snapshot(ir), event_record

    def history(self, *, scan_lines: int = DEFAULT_HISTORY_SCAN_LINES
               ) -> Dict[str, Any]:
        """The real recorded `HarnessStatusIR` snapshot history for
        `self.root` -- a thin, read-only call into
        `read_harness_status_history()`. Never mints `.dv-harness/`: reading
        history that was never recorded is exactly as read-only as
        `serve()`."""
        return read_harness_status_history(self.root, scan_lines=scan_lines)


# ===========================================================================
# CLI front door
# ===========================================================================

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m dv_harness.harness_status --root <dir> [--json] [--record]
    [--history]`.

    Default behavior (no `--record`/`--history`) is byte-for-byte what it
    always was: `serve()` a read-only snapshot. Exit 0 when `harness.state`
    is READY/SIGNOFF_READY, 1 for any other (non-UNKNOWN) state, 2 for
    UNKNOWN -- a CI-visible "status unresolved", never an approval signal in
    either direction.

    `--history` (read-only, mints nothing) prints the real recorded
    `HarnessStatusIR` snapshot history and exits 0 when at least one snapshot
    was ever recorded, 2 when none was (`NO_HARNESS_STATUS_HISTORY`) --
    section 435's own honest-absence rule as a CLI-visible exit code, mirroring
    every other capstone module's `NOT_AVAILABLE -> exit 2` convention in this
    project.

    `--record` is the one explicit opt-in that PERSISTS this snapshot to
    `.dv-harness/events.jsonl` via a real `storage.StateStore` (which mints
    `.dv-harness/` if it does not already exist -- exactly as constructing a
    `StateStore` for any other real write in this project already does); it
    is never implied by `--json` or by any other flag."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="harness-status")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--record", action="store_true",
                        help="persist this snapshot to "
                             ".dv-harness/events.jsonl (section 435)")
    parser.add_argument("--history", action="store_true",
                        help="print the real recorded HarnessStatusIR "
                             "snapshot history and exit (read-only)")
    parser.add_argument("--trigger", default="manual",
                        help="section 435's Trigger field for --record "
                             "(e.g. manual, stage_boundary); default: manual")
    parser.add_argument("--by", default=None, dest="user_agent_action",
                        help="section 435's User/Agent Action field for "
                             "--record (who/what performed this record); "
                             "default: not attributed")
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve()

    if args.history:
        hist = read_harness_status_history(root)
        if args.json:
            print(json.dumps(hist, indent=2))
        elif not hist["available"]:
            print(f"NO HARNESS STATUS HISTORY: {hist['reason']}")
        else:
            print(f"{hist['count']} recorded HarnessStatusIR snapshot(s):")
            for rec in hist["history"]:
                prev = rec.get("previous_state")
                state_str = (f"{prev} -> {rec.get('harness_state')}"
                             if prev is not None else str(rec.get("harness_state")))
                print(f"  {rec.get('ts')}  state={state_str}"
                      f"  readiness={rec.get('readiness')}"
                      f"  signoff_state={rec.get('signoff_state')}"
                      f"  unknowns={rec.get('unknown_count')}"
                      f"  trigger={rec.get('trigger')}")
        return 0 if hist["available"] else 2

    service = HarnessStatusService(root)
    if args.record:
        from .storage import StateStore
        store = StateStore(root)
        snapshot, event_record = service.record(
            store, trigger=args.trigger, user_agent_action=args.user_agent_action)
        if not args.json:
            prev = event_record.get("previous_state")
            state_str = (f"{prev} -> {event_record['harness_state']}"
                         if prev is not None else str(event_record["harness_state"]))
            print(f"RECORDED snapshot @ {event_record['ts']} "
                  f"(state={state_str}) -> "
                  f"{store.events_file}")
    else:
        snapshot = service.serve()
    if args.json:
        print(json.dumps(snapshot, indent=2))
    else:
        h = snapshot["harness"]
        print(f"HARNESS STATE: {h['state']}  (readiness={h['readiness']}, "
              f"signoff_state={h['signoff_state']})")
        for dim, val in sorted(h["dimension_states"].items()):
            print(f"  {dim:<12} {val}")
        if snapshot["unknowns"]:
            print(f"\n{len(snapshot['unknowns'])} unresolved field(s):")
            for u in snapshot["unknowns"][:10]:
                print(f"  - {u['field']}: {u['reason']}")

    state = snapshot["harness"]["state"]
    if state == "UNKNOWN":
        return 2
    if state in ("READY", "SIGNOFF_READY"):
        return 0
    return 1


def main(argv: Optional[Sequence[str]] = None) -> None:
    import sys
    sys.exit(execute_verb(argv))


if __name__ == "__main__":
    main()
