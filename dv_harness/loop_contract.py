"""LoopContract schema + the canonical loop state machine (LOOP_ENGINEERING
sections 85/86).

WHAT WAS ACTUALLY MISSING, RE-VERIFIED BEFORE THIS FILE WAS WRITTEN
-------------------------------------------------------------------
A repo-wide grep on 2026-09-05 returned ZERO hits for `LoopContract`,
`loop_contract`, `LoopState`, `BUDGET_EXHAUSTED`, `PLATEAU` and `OSCILLAT*`
(outside an unrelated ring-oscillator RTL comment). Three real loop drivers
exist and run -- `engine.DVHarness.loop()`/`run_stage()` (the Verification
Closure Loop), `memory_router.route_and_store()`/`promote_to_organizational()`
(the Project Learning Loop) and `capability_evolution.py`'s 11 promotion states
(the Capability Evolution Loop) -- and not one of them could state its own
budgets, convergence criteria, plateau/oscillation policy or termination
conditions as a machine-readable contract, nor name its own current state in a
vocabulary that covers PLATEAU / OSCILLATING / BUDGET_EXHAUSTED / CANCELLED /
RESUMING / STALE.

WHY A SECOND ENUM RATHER THAN EXTENDING models.Status
------------------------------------------------------
`models.Status` (NOT_STARTED/RUNNING/PASS/FAIL/PARTIAL/BLOCKED/RETRY/WAIT_USER/
CLOSED/ACCEPTED_RISK) is a STAGE-GATE VERDICT vocabulary: it answers "what did
this graph node's gate evaluation conclude", it is persisted in every
`state.json` ever written, it is the value `policy.graph_next()` routes on, and
`gates.py`/`engine.py`/`dashboard.py`/`commands.py` all branch on its exact
members. `LoopState` answers a different question -- "where is this LOOP, as a
control process, right now" -- and several of its members (PLATEAU, OSCILLATING,
BUDGET_EXHAUSTED, RESUMING, STALE, CANCELLED, CREATED, VERIFYING) are not
verdicts at all and would be meaningless on a `StageState`. Adding them to
`Status` would put values into `state.json` that every existing consumer's
`if status in (...)` chain silently falls through, which is the failure mode
`engine.loop()`'s own 2026-08-28 PARTIAL bug fix documents.

So: a SEPARATE enum, plus one REAL, TOTAL, tested mapping in this file
(`STATUS_TO_LOOP_STATE` / `derive_loop_state()`) rather than two independent
vocabularies drifting apart. `assert_status_mapping_total()` fails a test the
moment a new `Status` member is added without deciding what it means for a
loop -- the same "hold the two in agreement mechanically" technique
`mcp/claude_md_index.py` and `source_authority.assert_doc_matches_code()`
already use.

WHAT THIS MODULE DOES NOT DO
-----------------------------
  * It does not DETECT plateau or oscillation. `observe_*` reports
    `PLATEAU_NOT_EVALUATED` / an oscillation verdict derived ONLY from evidence
    already persisted on disk (the Blackboard `debug_loop_history` topic
    `engine._record_debug_loop_round()` writes). A progress-metric series
    (coverage over iterations) has a real producer -- `trend_analysis.py` and
    `coverage_analysis.py` -- and wiring one in is a separate change; inventing
    a series here would be the fabricated-evidence failure the Evidence Truth
    Rule forbids.
  * It has no verification authority and mints no verdict. Nothing here
    returns, accepts or persists a `models.Status` member as a loop outcome;
    `derive_loop_state()` READS a Status and translates it.
  * It weakens no human-approval gate. `HUMAN_GATE` is an OBSERVATION that a
    human decision is owed; producing it authorizes nothing. The real gates
    (`ControlPlane.approve()`, `policy.can_signoff()`, `HumanApprovalRequired
    Error`, `ProductionWriteNotAuthorizedError`) are untouched and uncalled
    from here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Status

_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
LOOP_CONTRACT_SCHEMA_PATH = _SCHEMA_DIR / "loop_contract.schema.json"

CONTRACT_SCHEMA_VERSION = "1.0"

#: The default oscillation repeat threshold: the same "2 INDEPENDENT
#: observations" bar `capability_evolution.REPEAT_FAILURE_MIN_OCCURRENCES` and
#: `memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS` already use, so this
#: codebase has ONE notion of "enough repetitions to mean something", not three.
DEFAULT_OSCILLATION_REPEAT_THRESHOLD = 2


# --------------------------------------------------------------------------
# Section 86: the canonical loop state machine
# --------------------------------------------------------------------------
class LoopState(str, Enum):
    """Section 86's canonical states, verbatim and complete, plus the two the
    section names separately for persistent sessions (RESUMING, STALE)."""
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    CONVERGING = "CONVERGING"
    PLATEAU = "PLATEAU"
    OSCILLATING = "OSCILLATING"
    RETRY_WAIT = "RETRY_WAIT"
    BLOCKED = "BLOCKED"
    HUMAN_GATE = "HUMAN_GATE"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    STOPPED = "STOPPED"
    CANCELLED = "CANCELLED"
    RESUMING = "RESUMING"
    STALE = "STALE"


#: States from which no further transition is legal. STOPPED and STALE are
#: deliberately NOT here: section 86 requires RESUMING "where persistent
#: sessions exist", and both of this harness's real stop conditions are
#: resumable by a real command (`dv-harness resume`, `dv-harness
#: release-takeover`, a fresh `dv-harness start --loop`).
TERMINAL_LOOP_STATES = (
    LoopState.SUCCESS, LoopState.FAILED, LoopState.CANCELLED,
)

#: Loop-scoped stop states a human or a resume path can leave.
RESUMABLE_LOOP_STATES = (
    LoopState.STOPPED, LoopState.STALE, LoopState.HUMAN_GATE,
    LoopState.BLOCKED, LoopState.BUDGET_EXHAUSTED,
)

#: Every legal edge, explicitly, derived from section 86's own chain
#: (`CREATED -> READY -> RUNNING -> VERIFYING -> CONVERGING/PLATEAU/
#: OSCILLATING/RETRY_WAIT/BLOCKED/HUMAN_GATE -> SUCCESS/FAILED/
#: BUDGET_EXHAUSTED/STOPPED/CANCELLED`) plus its RESUMING/STALE clause.
#:
#: BUDGET_EXHAUSTED -> RUNNING is a REAL edge in this harness, not a
#: convenience: `policy.max_stage_retries` is a STAGE-scoped attempt budget,
#: and `engine.loop()`'s retry-exhaustion branch (engine.py, the
#: `ss["attempts"] <= max_retry` test) spends it and then routes the run onto
#: the graph's FAIL edge, so the loop genuinely continues at another node with
#: a fresh attempt budget. Calling that terminal would misdescribe the engine.
LEGAL_LOOP_TRANSITIONS: Dict[Optional[str], tuple] = {
    None: (LoopState.CREATED.value,),
    LoopState.CREATED.value: (
        LoopState.READY.value, LoopState.CANCELLED.value, LoopState.BLOCKED.value),
    LoopState.READY.value: (
        LoopState.RUNNING.value, LoopState.BLOCKED.value, LoopState.HUMAN_GATE.value,
        LoopState.STOPPED.value, LoopState.CANCELLED.value, LoopState.STALE.value),
    LoopState.RUNNING.value: (
        LoopState.VERIFYING.value, LoopState.RETRY_WAIT.value, LoopState.BLOCKED.value,
        LoopState.HUMAN_GATE.value, LoopState.BUDGET_EXHAUSTED.value,
        LoopState.FAILED.value, LoopState.STOPPED.value, LoopState.CANCELLED.value,
        LoopState.STALE.value),
    LoopState.VERIFYING.value: (
        LoopState.CONVERGING.value, LoopState.PLATEAU.value, LoopState.OSCILLATING.value,
        LoopState.RETRY_WAIT.value, LoopState.BLOCKED.value, LoopState.HUMAN_GATE.value,
        LoopState.SUCCESS.value, LoopState.FAILED.value,
        LoopState.BUDGET_EXHAUSTED.value, LoopState.STOPPED.value,
        LoopState.CANCELLED.value, LoopState.STALE.value),
    LoopState.CONVERGING.value: (
        LoopState.RUNNING.value, LoopState.VERIFYING.value, LoopState.SUCCESS.value,
        LoopState.PLATEAU.value, LoopState.OSCILLATING.value, LoopState.BLOCKED.value,
        LoopState.HUMAN_GATE.value, LoopState.RETRY_WAIT.value,
        LoopState.BUDGET_EXHAUSTED.value, LoopState.FAILED.value,
        LoopState.STOPPED.value, LoopState.CANCELLED.value, LoopState.STALE.value),
    LoopState.PLATEAU.value: (
        LoopState.RUNNING.value, LoopState.HUMAN_GATE.value, LoopState.BLOCKED.value,
        LoopState.OSCILLATING.value, LoopState.FAILED.value,
        LoopState.BUDGET_EXHAUSTED.value, LoopState.STOPPED.value,
        LoopState.CANCELLED.value),
    LoopState.OSCILLATING.value: (
        LoopState.RUNNING.value, LoopState.HUMAN_GATE.value, LoopState.BLOCKED.value,
        LoopState.PLATEAU.value, LoopState.FAILED.value,
        LoopState.BUDGET_EXHAUSTED.value, LoopState.STOPPED.value,
        LoopState.CANCELLED.value),
    LoopState.RETRY_WAIT.value: (
        LoopState.RUNNING.value, LoopState.BUDGET_EXHAUSTED.value,
        LoopState.BLOCKED.value, LoopState.HUMAN_GATE.value, LoopState.FAILED.value,
        LoopState.STOPPED.value, LoopState.CANCELLED.value),
    LoopState.BLOCKED.value: (
        LoopState.HUMAN_GATE.value, LoopState.RUNNING.value, LoopState.FAILED.value,
        LoopState.STOPPED.value, LoopState.CANCELLED.value),
    LoopState.HUMAN_GATE.value: (
        LoopState.RUNNING.value, LoopState.RESUMING.value, LoopState.BLOCKED.value,
        LoopState.SUCCESS.value, LoopState.FAILED.value, LoopState.STOPPED.value,
        LoopState.CANCELLED.value),
    LoopState.BUDGET_EXHAUSTED.value: (
        LoopState.RUNNING.value, LoopState.HUMAN_GATE.value, LoopState.FAILED.value,
        LoopState.STOPPED.value, LoopState.CANCELLED.value),
    LoopState.STOPPED.value: (
        LoopState.RESUMING.value, LoopState.CANCELLED.value, LoopState.STALE.value),
    LoopState.STALE.value: (
        LoopState.RESUMING.value, LoopState.FAILED.value, LoopState.CANCELLED.value),
    LoopState.RESUMING.value: (
        LoopState.READY.value, LoopState.RUNNING.value, LoopState.FAILED.value,
        LoopState.BLOCKED.value, LoopState.CANCELLED.value),
    LoopState.SUCCESS.value: (),
    LoopState.FAILED.value: (),
    LoopState.CANCELLED.value: (),
}


class IllegalLoopTransitionError(ValueError):
    """Raised by assert_legal_loop_transition() on an edge section 86's state
    machine does not contain."""


def assert_legal_loop_transition(from_state: Optional[str], to_state: str) -> None:
    """`from_state=None` means "the loop does not exist yet"; the only legal
    first state is CREATED."""
    if to_state not in LOOP_STATE_VALUES:
        raise IllegalLoopTransitionError(
            f"unknown loop state {to_state!r}; must be one of {list(LOOP_STATE_VALUES)}")
    if from_state is not None and from_state not in LOOP_STATE_VALUES:
        raise IllegalLoopTransitionError(
            f"unknown loop state {from_state!r}; must be one of {list(LOOP_STATE_VALUES)}")
    allowed = LEGAL_LOOP_TRANSITIONS.get(from_state, ())
    if to_state not in allowed:
        raise IllegalLoopTransitionError(
            f"illegal loop transition {from_state} -> {to_state}; "
            f"legal next states from {from_state}: {list(allowed)}")


LOOP_STATE_VALUES = tuple(s.value for s in LoopState)

#: The base `LoopState`s section 86's own `LEGAL_LOOP_TRANSITIONS` allows a
#: STALE transition FROM -- derived from that table itself (never hand-typed
#: a second time) so this set can never drift from the one real transition
#: graph. `derive_loop_state()`'s `stale` override only ever applies to one of
#: these five: overriding a HUMAN_GATE/BLOCKED/RETRY_WAIT/BUDGET_EXHAUSTED/
#: PLATEAU/OSCILLATING/terminal state to STALE would both misdescribe what
#: actually happened AND violate the state machine
#: `assert_legal_loop_transition()` enforces everywhere else.
STALE_ELIGIBLE_BASE_STATES = tuple(
    LoopState(k) for k, v in LEGAL_LOOP_TRANSITIONS.items()
    if k is not None and LoopState.STALE.value in v)


# --------------------------------------------------------------------------
# The one real Status <-> LoopState bridge
# --------------------------------------------------------------------------
#: Every `models.Status` member's loop-control meaning. TOTAL by construction
#: (`assert_status_mapping_total()`), so a future Status member cannot silently
#: fall through to "no loop state".
#:
#: Two mappings worth their reasoning:
#:   * PASS -> CONVERGING, not SUCCESS. A gate-verified stage PASS is real
#:     forward progress on ONE node; the LOOP succeeds only when its own
#:     machine-checkable done holds (for the verification closure loop that is
#:     `overall_status == CLOSED`, i.e. `loop()` ran out of graph). Reporting
#:     SUCCESS per stage PASS would claim a closed project ~40 times per run.
#:   * ACCEPTED_RISK -> STOPPED, not SUCCESS. A recorded human acceptance of
#:     residual risk means the loop's machine-checkable done was NOT met and a
#:     human ended it anyway. SUCCESS would be a false claim; STOPPED is what
#:     actually happened, and it stays resumable.
STATUS_TO_LOOP_STATE: Dict[str, LoopState] = {
    Status.NOT_STARTED.value: LoopState.READY,
    Status.RUNNING.value: LoopState.RUNNING,
    Status.PASS.value: LoopState.CONVERGING,
    Status.FAIL.value: LoopState.RETRY_WAIT,
    Status.PARTIAL.value: LoopState.RETRY_WAIT,
    Status.BLOCKED.value: LoopState.BLOCKED,
    Status.RETRY.value: LoopState.RETRY_WAIT,
    Status.WAIT_USER.value: LoopState.HUMAN_GATE,
    Status.CLOSED.value: LoopState.SUCCESS,
    Status.ACCEPTED_RISK.value: LoopState.STOPPED,
}

#: The loop-control states no `models.Status` member expresses -- i.e. exactly
#: what this vocabulary adds. Kept as data so a test can assert it rather than
#: a docstring claiming it.
LOOP_STATES_WITHOUT_STATUS_EQUIVALENT = tuple(
    s for s in LoopState if s not in set(STATUS_TO_LOOP_STATE.values())
)


def assert_status_mapping_total() -> None:
    """Every `models.Status` member must have a decided loop meaning, and the
    mapping must name no state outside `LoopState`. Called by the tests; a new
    Status member added without a decision here fails them."""
    missing = [s.value for s in Status if s.value not in STATUS_TO_LOOP_STATE]
    if missing:
        raise AssertionError(
            f"models.Status members with no LoopState meaning decided: {missing}. "
            f"Add them to STATUS_TO_LOOP_STATE (and say why in its comment).")
    unknown = [k for k in STATUS_TO_LOOP_STATE
               if k not in {s.value for s in Status}]
    if unknown:
        raise AssertionError(
            f"STATUS_TO_LOOP_STATE names non-Status keys: {unknown}")
    bad = [f"{k}->{v}" for k, v in STATUS_TO_LOOP_STATE.items()
           if not isinstance(v, LoopState)]
    if bad:
        raise AssertionError(f"STATUS_TO_LOOP_STATE values must be LoopState: {bad}")


def derive_loop_state(status: str, *,
                      attempts: Optional[int] = None,
                      max_attempts: Optional[int] = None,
                      paused: bool = False,
                      takeover_active: bool = False,
                      loop_done: bool = False,
                      oscillating: bool = False,
                      plateau: bool = False,
                      progress_oscillating: bool = False,
                      stale: bool = False) -> LoopState:
    """The one function that turns real backend facts into a LoopState.

    Section 86: "State transitions must derive from backend evidence, not
    Agent prose." Every argument here is a fact read off a real store --
    `state.json`'s stage status/attempts, `config.json`'s
    `policy.max_stage_retries`, `control.json`'s paused/takeover flags, and
    (for `oscillating`) the Blackboard `debug_loop_history` topic. None of
    them is an agent's self-report.

    Precedence, highest first, and it matters:
      1. TAKEOVER  -> HUMAN_GATE. Human Override is checked before anything
         else, exactly as `engine.loop()` itself checks it first.
      2. PAUSED    -> STOPPED.
      3. A retry-family status whose ATTEMPT BUDGET is spent ->
         BUDGET_EXHAUSTED. This is the same condition `engine.loop()` branches
         on (`ss["attempts"] <= max_retry`), read from the same two fields.
      4. `oscillating` -> OSCILLATING, but only over a retry-family status: an
         oscillation fingerprint says nothing about a stage that passed.
      5. `loop_done` -> SUCCESS.
      6. `progress_oscillating` / `plateau` -> OSCILLATING / PLATEAU, but only
         over CONVERGING and only when the loop is NOT done. Both are computed
         by `loop_convergence.classify_loop_convergence()`; nothing here
         re-derives either.

         They apply over CONVERGING precisely where `oscillating` above does
         not, and the difference is which evidence each reads. `oscillating` is
         the Blackboard `debug_loop_history` repeat-FAILURE fingerprint -- a
         record of retry exhaustions -- so it says nothing about a stage that
         has since passed, and stays confined to the retry family. These two
         read CURRENT cross-run evidence (the coverage series, and
         `regression_verdict_history`'s repeat-fix-revert cycles), and a loop
         whose stages keep PASSING while its own progress metric has stopped
         moving, or keeps being undone, is exactly what PLATEAU and OSCILLATING
         are for. A failing stage is already better described by RETRY_WAIT /
         BUDGET_EXHAUSTED, and a CLOSED project is finished, not stalled.

         `progress_oscillating` wins over `plateau`: "the loop is undoing its
         own work" is the more specific fact, and it points at a different
         remedy than "this stimulus has reached its ceiling".
      7. Otherwise the STATUS_TO_LOOP_STATE table.
      8. `stale` -- checked LAST, and only overrides a `base` that is one of
         `STALE_ELIGIBLE_BASE_STATES` (READY/RUNNING/VERIFYING/CONVERGING/
         STOPPED -- exactly the five states section 86's own
         `LEGAL_LOOP_TRANSITIONS` allows a STALE edge FROM). `stale` is a
         real fact from `loop_stale_detection.detect_loop_staleness()` --
         the loop session's last real event is older than a declared
         staleness window, or the project's own source moved (a real git
         diff at HIGH/MEDIUM risk) since the state this session is about to
         resume against -- never a guess from an agent's prose. Placed last
         and scoped this narrowly so it can never re-route a genuine
         TAKEOVER/PAUSE/RETRY_WAIT/BUDGET_EXHAUSTED/BLOCKED/HUMAN_GATE/
         PLATEAU/OSCILLATING finding, or a terminal SUCCESS/FAILED/CANCELLED
         one: those are real facts about what already happened and staleness
         says nothing that would make any of them less true.
    """
    if takeover_active:
        return LoopState.HUMAN_GATE
    if paused:
        return LoopState.STOPPED
    if status not in STATUS_TO_LOOP_STATE:
        raise ValueError(
            f"unknown status {status!r}; not a member of models.Status "
            f"({[s.value for s in Status]})")
    base = STATUS_TO_LOOP_STATE[status]
    if base is LoopState.RETRY_WAIT:
        if (attempts is not None and max_attempts is not None
                and attempts > max_attempts):
            return LoopState.BUDGET_EXHAUSTED
        if oscillating:
            return LoopState.OSCILLATING
        return base
    if loop_done and base in (LoopState.CONVERGING, LoopState.SUCCESS):
        return LoopState.SUCCESS
    if base is LoopState.CONVERGING:
        if progress_oscillating:
            return LoopState.OSCILLATING
        if plateau:
            return LoopState.PLATEAU
    if stale and base in STALE_ELIGIBLE_BASE_STATES:
        return LoopState.STALE
    return base


# --------------------------------------------------------------------------
# Section 85: the LoopContract schema
# --------------------------------------------------------------------------
#: The sentinel a budget/metric carries when this harness genuinely has no such
#: limit today. Section 85 lists eight budgets; this engine really implements
#: three of them, and `budget_sources` below names the real config key for each
#: implemented one and the honest reason for each absent one. A fabricated
#: number here would make a loop look bounded when nothing bounds it.
NOT_ENFORCED = None


@dataclass
class LoopBudgets:
    """Section 85's `budgets:` block. Every field Optional: `None` means NOT
    ENFORCED by any code in this harness, and `LoopContract.budget_sources`
    must then carry the reason."""
    max_iterations: Optional[int] = None
    max_wall_time_seconds: Optional[float] = None
    max_jobs: Optional[int] = None
    max_compute: Optional[float] = None
    max_license_cost: Optional[float] = None
    max_token_cost: Optional[float] = None
    max_failed_attempts: Optional[int] = None
    max_change_scope: Optional[str] = None


@dataclass
class LoopRetryPolicy:
    """Section 85's `retry:` block."""
    max_retries: Optional[int] = None
    backoff: str = "NONE"
    retryable_failures: List[str] = field(default_factory=list)
    non_retryable_failures: List[str] = field(default_factory=list)


@dataclass
class LoopConvergence:
    """Section 85's `convergence:` block."""
    metrics: List[str] = field(default_factory=list)
    minimum_progress: Optional[float] = None
    window: Optional[int] = None


@dataclass
class LoopPlateau:
    """Section 85's `plateau:` block."""
    detection_window: Optional[int] = None
    minimum_gain: Optional[float] = None


@dataclass
class LoopOscillation:
    """Section 85's `oscillation:` block. `fingerprint_fields` names the REAL
    persisted fields an oscillation verdict is computed over -- for the
    verification closure loop those are the Blackboard `debug_loop_history`
    entry's own keys, written by `engine._record_debug_loop_round()`."""
    fingerprint_fields: List[str] = field(default_factory=list)
    repeat_threshold: Optional[int] = None
    evidence_source: str = ""


@dataclass
class LoopTermination:
    """Section 85's `termination:` block. Each field states the real condition
    in this harness, naming the code that decides it."""
    success: str = ""
    failure: str = ""
    budget: str = ""
    no_progress: str = ""
    human_stop: str = ""


@dataclass
class LoopContract:
    """Section 85's schema, complete. One contract per important loop.

    `driver_module` / `driver_entry_point` are load-bearing, not decoration:
    they are what makes a contract checkable against the code it describes
    (`assert_driver_resolvable()`), so a contract cannot outlive or misname the
    loop it claims to describe.
    """
    loop_id: str
    loop_type: str
    owner: str
    version: str
    trigger: str
    goal: str
    machine_checkable_done: str
    driver_module: str
    driver_entry_point: str
    inputs: List[str] = field(default_factory=list)
    state: List[str] = field(default_factory=list)
    allowed_actions: List[str] = field(default_factory=list)
    forbidden_actions: List[str] = field(default_factory=list)
    verifier: str = ""
    evidence_sources: List[str] = field(default_factory=list)
    progress_metrics: List[str] = field(default_factory=list)
    utility_metrics: List[str] = field(default_factory=list)
    budgets: LoopBudgets = field(default_factory=LoopBudgets)
    budget_sources: Dict[str, str] = field(default_factory=dict)
    retry: LoopRetryPolicy = field(default_factory=LoopRetryPolicy)
    convergence: LoopConvergence = field(default_factory=LoopConvergence)
    plateau: LoopPlateau = field(default_factory=LoopPlateau)
    oscillation: LoopOscillation = field(default_factory=LoopOscillation)
    termination: LoopTermination = field(default_factory=LoopTermination)
    escalation: str = ""
    human_gate: str = ""
    rollback: str = ""
    resume: str = ""
    audit: str = ""
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_yaml(self) -> str:
        """Section 85's own YAML rendering. Imported lazily, matching
        `design_intent.py`/`init_seq.py`'s convention -- PyYAML is not a hard
        dependency of the engine's import path."""
        import yaml
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoopContract":
        data = dict(data)
        nested = {
            "budgets": LoopBudgets, "retry": LoopRetryPolicy,
            "convergence": LoopConvergence, "plateau": LoopPlateau,
            "oscillation": LoopOscillation, "termination": LoopTermination,
        }
        for key, klass in nested.items():
            value = data.get(key)
            if isinstance(value, dict):
                data[key] = klass(**value)
            elif value is None:
                data[key] = klass()
        return cls(**data)

    @classmethod
    def from_yaml(cls, text: str) -> "LoopContract":
        import yaml
        return cls.from_dict(yaml.safe_load(text) or {})


def _load_schema() -> Dict[str, Any]:
    return json.loads(LOOP_CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))


class LoopContractValidationError(ValueError):
    """Raised by validate_contract() on a contract the schema rejects, or on a
    budget that is None with no honest reason recorded."""


def validate_contract(contract) -> None:
    """Schema-validates a contract AND enforces the honesty rule the schema
    cannot express: every budget field left `None` must carry a real reason in
    `budget_sources`, so "unbounded" is always a stated decision rather than an
    omission a reader would mistake for a bound."""
    payload = contract.to_dict() if isinstance(contract, LoopContract) else dict(contract)
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - jsonschema is a declared dependency
        jsonschema = None
    if jsonschema is not None:
        try:
            jsonschema.validate(payload, _load_schema())
        except jsonschema.ValidationError as exc:
            raise LoopContractValidationError(
                f"{payload.get('loop_id', '<no loop_id>')}: {exc.message} "
                f"(at {'/'.join(str(p) for p in exc.absolute_path) or '<root>'})") from exc
    budgets = payload.get("budgets") or {}
    sources = payload.get("budget_sources") or {}
    undocumented = sorted(k for k in budgets if k not in sources)
    if undocumented:
        raise LoopContractValidationError(
            f"{payload.get('loop_id', '<no loop_id>')}: budget fields with no entry in "
            f"budget_sources: {undocumented}. Every budget must name either the real "
            f"config key that enforces it or the honest reason nothing does.")


def assert_driver_resolvable(contract: LoopContract) -> None:
    """A contract must describe a loop that really exists: its `driver_module`
    must import and its `driver_entry_point` must resolve on it (dotted
    attribute path, so `DVHarness.loop` works). This is what stops a contract
    from surviving the removal or rename of the loop it documents."""
    import importlib
    module = importlib.import_module(contract.driver_module)
    obj: Any = module
    for part in contract.driver_entry_point.split("."):
        if not hasattr(obj, part):
            raise LoopContractValidationError(
                f"{contract.loop_id}: driver_entry_point "
                f"{contract.driver_module}.{contract.driver_entry_point} does not resolve "
                f"({part!r} missing on {obj!r})")
        obj = getattr(obj, part)


# --------------------------------------------------------------------------
# The three real loops, populated from their own drivers' real state
# --------------------------------------------------------------------------
VERIFICATION_CLOSURE_LOOP = "verification_closure"
PROJECT_LEARNING_LOOP = "project_learning"
CAPABILITY_EVOLUTION_LOOP = "capability_evolution"


def verification_closure_contract(cfg: Optional[Dict[str, Any]] = None) -> LoopContract:
    """The Verification Closure Loop: `engine.DVHarness.loop()` walking
    `main_graph.json` node by node, each node's evidence judged by
    `gates.evaluate_stage_evidence()`.

    Every number below is READ from the harness's own real configuration
    (`config.DEFAULT_CONFIG` merged with the project's `config.json`), never
    retyped here -- change `policy.max_stage_retries` and this contract
    changes with it."""
    # Lazily imported: loop_convergence imports LoopState from THIS module, so a
    # module-level import here would be circular. The convergence/plateau
    # thresholds below are read from it rather than retyped, exactly as
    # max_stage_retries is read from the config -- change the detector's
    # thresholds and this contract changes with them.
    from . import loop_convergence as _lcv
    if cfg is None:
        from .config import DEFAULT_CONFIG
        cfg = DEFAULT_CONFIG
    policy = cfg.get("policy", {}) or {}
    claude = cfg.get("claude", {}) or {}
    max_stage_retries = policy.get("max_stage_retries")
    return LoopContract(
        loop_id=VERIFICATION_CLOSURE_LOOP,
        loop_type="STAGE_GATE_CLOSURE",
        owner="dv_harness/engine.py (DVHarness)",
        version=CONTRACT_SCHEMA_VERSION,
        driver_module="dv_harness.engine",
        driver_entry_point="DVHarness.loop",
        trigger="`dv-harness start --loop`, or DVHarness.loop() called directly.",
        goal=("Drive the project from its current graph node to SIGNOFF, with every "
              "node's evidence accepted by its own hard gates."),
        machine_checkable_done=(
            "state.overall_status == Status.CLOSED, set by loop() only when advance() "
            "returns no next node -- i.e. the graph itself ran out, never an agent's claim."),
        inputs=[".dv-harness/graph/main_graph.json", ".dv-harness/state.json",
                ".dv-harness/config.json", ".dv-harness/blackboard/*",
                "the agent adapter's response text"],
        state=["models.HarnessState.current_stage", "models.HarnessState.active_stages",
               "models.HarnessState.overall_status", "models.StageState.status",
               "models.StageState.attempts", "models.HarnessState.last_transition"],
        allowed_actions=["run_stage", "advance", "graph_next(FAIL edge)", "replan_stage",
                         "react reroute hint (preference over, never instead of, the graph)"],
        forbidden_actions=[
            "dispatching SIGNOFF while policy.can_signoff() refuses",
            "advancing a PARTIAL/FAIL stage along the graph's PASS edge",
            "answering its own question-queue Tier-3 escalation",
            "merging or pushing to main/master (gh CLI + PR-Only Governance Policy)"],
        verifier="dv_harness.gates.evaluate_stage_evidence() + the real STAGE_GATES subprocesses",
        evidence_sources=["tools/verification_flow/*.py gate subprocesses",
                          "Blackboard topics named by each node's blackboard_write",
                          ".dv-harness/events.jsonl"],
        progress_metrics=["stage_completion_percent (fraction of a node's gates satisfied)",
                          "findings_closed / findings_total",
                          "Blackboard.debug_loop_round_count()"],
        utility_metrics=["stages reaching PASS per run", "attempts spent per stage"],
        budgets=LoopBudgets(
            max_failed_attempts=max_stage_retries,
            max_iterations=NOT_ENFORCED,
            max_wall_time_seconds=NOT_ENFORCED,
            max_jobs=NOT_ENFORCED,
            max_compute=NOT_ENFORCED,
            max_license_cost=NOT_ENFORCED,
            max_token_cost=NOT_ENFORCED,
            max_change_scope=NOT_ENFORCED,
        ),
        budget_sources={
            "max_failed_attempts": "config policy.max_stage_retries (per graph node, "
                                    "spent in engine.loop()'s retry-exhaustion branch)",
            "max_iterations": "NOT ENFORCED: loop() is an unbounded `while True` over the "
                              "graph; only per-node attempts are capped.",
            "max_wall_time_seconds": "NOT ENFORCED: no wall-clock deadline exists anywhere "
                                      "in engine.py.",
            "max_jobs": "NOT ENFORCED here: LSF job caps are the farm's own, not this loop's.",
            "max_compute": "NOT ENFORCED: no compute accounting exists in this loop.",
            "max_license_cost": "NOT ENFORCED by the loop: preflight.py CHECKS license "
                                 "availability before a build but caps no spend.",
            "max_token_cost": f"NOT ENFORCED as a loop budget: claude.max_turns "
                               f"({claude.get('max_turns')}) caps ONE adapter call's turns, "
                               f"not the run's token spend.",
            "max_change_scope": "NOT ENFORCED numerically: change scope is governed by the "
                                 "PR-only main/master policy and change_impact.py, not a cap.",
        },
        retry=LoopRetryPolicy(
            max_retries=max_stage_retries,
            backoff="NONE (immediate re-dispatch; engine.loop() `continue`s straight into "
                    "the next run_stage() attempt)",
            retryable_failures=[Status.FAIL.value, Status.PARTIAL.value,
                                "GATE_FAIL", "MISSING_EVIDENCE", "ADAPTER_FAIL"],
            non_retryable_failures=[Status.BLOCKED.value, Status.WAIT_USER.value,
                                    "NEEDS_USER_INPUT"],
        ),
        convergence=LoopConvergence(
            metrics=["stage_completion_percent", "findings_open",
                     f"{_lcv.COVERAGE_PERCENT_METRIC} (trend_analysis.daily_rollup(), "
                     f"classified by loop_convergence.classify_convergence())"],
            minimum_progress=_lcv.DEFAULT_MIN_GAIN_PERCENT,
            window=_lcv.DEFAULT_CONVERGENCE_WINDOW,
        ),
        plateau=LoopPlateau(detection_window=_lcv.DEFAULT_PLATEAU_WINDOW,
                            minimum_gain=_lcv.DEFAULT_PLATEAU_MIN_GAIN_PERCENT),
        oscillation=LoopOscillation(
            fingerprint_fields=["failing_stage", "target_fail_edge", "pattern"],
            repeat_threshold=DEFAULT_OSCILLATION_REPEAT_THRESHOLD,
            evidence_source="Blackboard topic 'debug_loop_history' "
                            "(engine._record_debug_loop_round()) for the repeat-failure "
                            "fingerprint, plus the evidence DB's regression_verdict_history "
                            "(trend_analysis.detect_verdict_oscillation()) for the "
                            "repeat-fix-revert one",
        ),
        termination=LoopTermination(
            success="advance() returns no next node -> overall_status = CLOSED.",
            failure="graph_next(stage, FAIL) has no FAIL edge for the failing node -> "
                    "loop() returns.",
            budget="ss['attempts'] > policy.max_stage_retries -> the node's FAIL edge is "
                    "taken (a node-scoped budget, not the run's).",
            no_progress=("DETECTED, not terminated on: loop_convergence."
                         "classify_loop_convergence() classifies the real coverage series as "
                         "CONVERGING/SLOW_CONVERGENCE/NO_PROGRESS/PLATEAU/REGRESSION/"
                         "OSCILLATING/UNKNOWN and PLATEAU/OSCILLATING reach the observation's "
                         "own LoopState. engine.loop() still routes a retry-exhausted stage "
                         "onto its graph FAIL edge; nothing terminates the run on a plateau."),
            human_stop="ControlPlane pause/takeover, checked FIRST in loop()'s body; "
                        "Status.WAIT_USER/BLOCKED also return.",
        ),
        escalation="question_queue.QuestionQueueStore (Tier-3 blocking question), plus the "
                    "stage-boundary digest engine._emit_question_digest_at_stage_boundary() emits.",
        human_gate="Status.WAIT_USER parks the loop; policy.can_signoff() hard-stops SIGNOFF; "
                    "ControlPlane.approve()/takeover are the human's own controls.",
        rollback="git revert of the branch the change landed on; no engine-level rollback "
                  "of a stage exists.",
        resume="`dv-harness start --loop` re-enters at state.current_stage; "
                "`dv-harness resume` / `release-takeover` clear a human stop.",
        audit=".dv-harness/events.jsonl via StateStore.event(), read back by `dv-harness audit`.",
    )


def project_learning_contract() -> LoopContract:
    """The Project Learning Loop: a record climbing the 5 memory tiers through
    `memory_router`'s real admission gates.

    `ORGANIZATIONAL_MIN_CONFIRMATIONS` is imported, never retyped."""
    from .memory_router import (ORGANIZATIONAL_MIN_CONFIRMATIONS,
                                ENGINEERING_ADMISSION_CONFIDENCE_LEVELS,
                                ENGINEERING_REUSABLE_CLAIM_FIELDS)
    return LoopContract(
        loop_id=PROJECT_LEARNING_LOOP,
        loop_type="KNOWLEDGE_TIER_PROMOTION",
        owner="dv_harness/memory_router.py",
        version=CONTRACT_SCHEMA_VERSION,
        driver_module="dv_harness.memory_router",
        driver_entry_point="route_and_store",
        trigger="Any real engine write of a new knowledge record (engine.py's "
                "_record_debug_attempt_job_memory / _promote_verified_fix_knowledge, "
                "lsf_client's terminal-reconcile job memory write).",
        goal="Carry a verified, reusable engineering claim from Working Memory up to "
             "Organizational Memory, without ever admitting an unverified hypothesis.",
        machine_checkable_done=(
            "promote_to_organizational() returns promoted=True, which requires the "
            "qualitative CLOSED/VERIFIED gate, a HIGH inference.score_confidence() result, "
            f"and an EARNED on-disk confirmation_count >= {ORGANIZATIONAL_MIN_CONFIRMATIONS}."),
        inputs=["the record dict handed to route_and_store()",
                ".dv-harness/memory/* (the real per-tier stores)",
                ".dv-harness/config.json (knowledge_center settings)"],
        state=["the record's routed destination", "MemoryStore record `level`",
               "record `status` (ACTIVE/...)", "record `confirmation_count`"],
        allowed_actions=["route_and_store", "promote_to_organizational",
                         "MemoryGC.confirm (confirm-on-re-derivation)",
                         "vault note create / fold recurrence line"],
        forbidden_actions=[
            "writing ORGANIZATIONAL_MEMORY directly, bypassing promote_to_organizational()",
            "storing credentials/secrets (route_memory() hard-REJECTs those kinds)",
            "storing raw logs or FSDB content",
            "promoting an unverified hypothesis past Working Memory"],
        verifier=("memory_router.engineering_admission_gate() -- which requires confidence "
                  f"in {list(ENGINEERING_ADMISSION_CONFIDENCE_LEVELS)} plus a reusable claim "
                  f"in one of {list(ENGINEERING_REUSABLE_CLAIM_FIELDS)} -- and "
                  "memory_router.organizational_admission_gate(), which re-reads the "
                  "promotion provenance off the durable store rather than trusting the caller"),
        evidence_sources=["the record's own `evidence` / gate-validated `verification` block",
                          "dv_harness.inference.score_confidence()",
                          "the on-disk source record's provenance "
                          "(source_engineering_memory_id)"],
        progress_metrics=["confirmation_count", "tier reached"],
        utility_metrics=["records reaching ENGINEERING_MEMORY", "records reaching "
                         "ORGANIZATIONAL_MEMORY", "admission rejections by reason"],
        budgets=LoopBudgets(
            max_iterations=NOT_ENFORCED, max_wall_time_seconds=NOT_ENFORCED,
            max_jobs=NOT_ENFORCED, max_compute=NOT_ENFORCED,
            max_license_cost=NOT_ENFORCED, max_token_cost=NOT_ENFORCED,
            max_failed_attempts=NOT_ENFORCED, max_change_scope=NOT_ENFORCED,
        ),
        budget_sources={k: "NOT ENFORCED: promotion is gated on EVIDENCE, not on a spend or "
                            "attempt cap -- a record simply stays at its tier until the gate "
                            "is genuinely cleared."
                        for k in ("max_iterations", "max_wall_time_seconds", "max_jobs",
                                  "max_compute", "max_license_cost", "max_token_cost",
                                  "max_failed_attempts", "max_change_scope")},
        retry=LoopRetryPolicy(
            max_retries=None,
            backoff="NONE (a rejected record is demoted and simply re-evaluated the next "
                    "time real new evidence arrives)",
            retryable_failures=["engineering_admission_rejected",
                                "organizational_admission_rejected"],
            non_retryable_failures=["REJECT (credential/secret-like kind)"],
        ),
        convergence=LoopConvergence(
            metrics=["confirmation_count"],
            minimum_progress=1.0,
            window=ORGANIZATIONAL_MIN_CONFIRMATIONS,
        ),
        plateau=LoopPlateau(detection_window=None, minimum_gain=None),
        oscillation=LoopOscillation(
            fingerprint_fields=["protocol", "root_cause"],
            repeat_threshold=None,
            evidence_source="the (protocol, root_cause) dedup key MemoryGC.confirm() uses; "
                            "a re-derivation CONFIRMS rather than oscillates, by design.",
        ),
        termination=LoopTermination(
            success="ORGANIZATIONAL_MEMORY reached through promote_to_organizational().",
            failure="route_memory() returns REJECT -> ValueError, nothing persisted.",
            budget="NOT APPLICABLE: no budget bounds this loop.",
            no_progress="A record that never clears its admission gate stays at its tier "
                        "indefinitely; that is the intended resting state, not a failure.",
            human_stop="Human Override may demote or revoke; MemoryGC handles expiry.",
        ),
        escalation="A rejected admission is recorded on the record itself "
                    "(engineering_admission_rejected / organizational_admission_rejected) "
                    "with its reasons, readable via `dv-harness memory`.",
        human_gate="None on the automatic path by design -- promotion is evidence-gated, not "
                    "approval-gated. Knowledge Center sharing is opt-in configuration.",
        rollback="MemoryGC status transitions (ACTIVE -> superseded/expired); the vault's own "
                  "git history for note content.",
        resume="Stateless: the next real record simply re-enters the same gates.",
        audit="The per-tier MemoryStore JSON records themselves, plus vault git commits "
              "(`memory(<protocol>): ...`) where memory.git_enabled is on.",
    )


def capability_evolution_contract() -> LoopContract:
    """The Capability Evolution Loop: `capability_evolution.py`'s 11 promotion
    states from DISCOVERED to PRODUCTION.

    `PROMOTION_STATES`, `TERMINAL_STATES`, `HUMAN_APPROVAL_STAGE` and
    `REPEAT_FAILURE_MIN_OCCURRENCES` are imported from that module, never
    retyped, so this contract cannot drift from the state machine it
    describes."""
    from . import capability_evolution as ce
    repeat_min = getattr(ce, "REPEAT_FAILURE_MIN_OCCURRENCES", None)
    return LoopContract(
        loop_id=CAPABILITY_EVOLUTION_LOOP,
        loop_type="GOVERNED_CAPABILITY_PROMOTION",
        owner="dv_harness/capability_evolution.py",
        version=CONTRACT_SCHEMA_VERSION,
        driver_module="dv_harness.capability_evolution",
        driver_entry_point="transition",
        trigger=("`dv-harness research <doc>`, or engine.DVHarness."
                 "_file_capability_evolution_candidates_from_repeated_failures() firing on "
                 f"{repeat_min} INDEPENDENT runs of the same failure signature."),
        goal="Turn a repeated real failure or an external research finding into an approved, "
             "benchmarked change to this harness's own capability.",
        machine_checkable_done=(
            "current_status == PRODUCTION, reachable only through HUMAN_APPROVED, which "
            "assert_human_approval() verifies against a real ControlPlane approval on disk "
            f"for stage {ce.HUMAN_APPROVAL_STAGE}."),
        inputs=["Job Memory job_failure records (via evidence_db.signature_key groups)",
                "ResearchEvidenceCards from research-ingestion",
                ".dv-harness/blackboard/capability_evolution_candidates"],
        state=list(ce.PROMOTION_STATES),
        allowed_actions=["build_candidate", "persist_candidate", "transition",
                         "run_controlled_experiment", "file_repeated_failure_candidate"],
        forbidden_actions=[
            "skipping a governance state (assert_legal_transition())",
            "reaching HUMAN_APPROVED without a real ControlPlane approval",
            "writing a production file from any state outside "
            f"{list(ce.PRODUCTION_WRITE_AUTHORIZED_STATES)}",
            "persisting any member of models.Status as a candidate outcome",
            "promoting a candidate to Organizational Memory"],
        verifier="run_controlled_experiment() -- two real DVHarness.run_stage() arms over an "
                 "isolated fixture copy, measured through control_plane.describe_stage(); "
                 "assert_benchmark_measured() re-reads the record off disk.",
        evidence_sources=[".dv-harness/experiments/<candidate_id>/<run_id>/",
                          "Working Memory candidate audit records",
                          "dv_harness.inference.score_confidence()"],
        progress_metrics=["promotion state index within PROMOTION_STATES",
                          "answered_l5_check_questions() count (of 10)",
                          "conclusive search slots (of 6)"],
        utility_metrics=["benchmark outcome (IMPROVED/UNCHANGED/DEGRADED/INCONCLUSIVE)"],
        budgets=LoopBudgets(
            max_iterations=NOT_ENFORCED, max_wall_time_seconds=NOT_ENFORCED,
            max_jobs=NOT_ENFORCED, max_compute=NOT_ENFORCED,
            max_license_cost=NOT_ENFORCED, max_token_cost=NOT_ENFORCED,
            max_failed_attempts=NOT_ENFORCED,
            max_change_scope="the candidate's own declared `mutation` list, every path "
                              "verified to resolve inside the treatment workspace",
        ),
        budget_sources={
            "max_change_scope": "run_controlled_experiment()'s mutation path containment "
                                 "check (before AND after the write).",
            "max_iterations": "NOT ENFORCED: the state machine is human-paced, not iterated.",
            "max_wall_time_seconds": "NOT ENFORCED: no deadline exists on a candidate.",
            "max_jobs": "NOT APPLICABLE: an execution-layer stage is REFUSED by default in "
                         "run_controlled_experiment(), so this loop submits no farm jobs.",
            "max_compute": "NOT ENFORCED: no compute accounting exists here.",
            "max_license_cost": "NOT APPLICABLE: no licensed tool is invoked by this loop.",
            "max_token_cost": "NOT ENFORCED: no token accounting exists here.",
            "max_failed_attempts": "NOT ENFORCED: REJECTED is a human decision, not an "
                                    "attempt-count outcome.",
        },
        retry=LoopRetryPolicy(
            max_retries=None,
            backoff="NONE",
            retryable_failures=["a candidate re-derived from fresh evidence lands on the "
                                "same content-derived candidate_id and accumulates evidence"],
            non_retryable_failures=list(ce.TERMINAL_STATES),
        ),
        convergence=LoopConvergence(
            metrics=["answered_l5_check_questions", "search_conclusive slots"],
            minimum_progress=None,
            window=None,
        ),
        plateau=LoopPlateau(
            detection_window=None,
            minimum_gain=None,
        ),
        oscillation=LoopOscillation(
            fingerprint_fields=["candidate_id"],
            repeat_threshold=repeat_min,
            evidence_source="the content-derived candidate_id: a recurrence lands on the SAME "
                            "record, and one already past DISCOVERED reports "
                            "ALREADY_BEYOND_DISCOVERED and writes nothing.",
        ),
        termination=LoopTermination(
            success="PRODUCTION.",
            failure="ROLLED_BACK (a production change reverted).",
            budget="NOT APPLICABLE: no budget bounds this loop.",
            no_progress="A candidate parks at DISCOVERED with UNKNOWN overlap until a real "
                        "research-architect pass performs the six searches; nothing in the "
                        "engine performs them.",
            human_stop="REJECTED, from any non-terminal state.",
        ),
        escalation="The candidate itself, on the capability_evolution_candidates Blackboard "
                    "topic, plus its Working Memory audit record.",
        human_gate=f"ControlPlane.approve('{ce.HUMAN_APPROVAL_STAGE}'), enforced by "
                    "assert_human_approval(); production writes additionally gated by "
                    "assert_no_production_write_authorized().",
        rollback="PRODUCTION -> ROLLED_BACK, the only legal edge out of PRODUCTION.",
        resume="Stateless: a candidate is re-read from the Blackboard topic by candidate_id.",
        audit="Working Memory candidate audit records (candidate_audit_records()) plus the "
              "Blackboard topic's own write history.",
    )


CONTRACT_BUILDERS = {
    VERIFICATION_CLOSURE_LOOP: verification_closure_contract,
    PROJECT_LEARNING_LOOP: project_learning_contract,
    CAPABILITY_EVOLUTION_LOOP: capability_evolution_contract,
}


def loop_ids() -> List[str]:
    return list(CONTRACT_BUILDERS)


def build_contract(loop_id: str, **kwargs: Any) -> LoopContract:
    if loop_id not in CONTRACT_BUILDERS:
        raise KeyError(f"unknown loop_id {loop_id!r}; known loops: {loop_ids()}")
    return CONTRACT_BUILDERS[loop_id](**kwargs)


def build_all_contracts(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, LoopContract]:
    """Every contract, with `cfg` reaching only the loop that has config-driven
    budgets."""
    return {
        VERIFICATION_CLOSURE_LOOP: verification_closure_contract(cfg),
        PROJECT_LEARNING_LOOP: project_learning_contract(),
        CAPABILITY_EVOLUTION_LOOP: capability_evolution_contract(),
    }


# --------------------------------------------------------------------------
# Observations: a loop's current state, derived from real backend evidence
# --------------------------------------------------------------------------
#: Recorded in an observation's `plateau` field when no progress-metric series
#: was supplied. Deliberately NOT "no plateau": a detector that never ran and a
#: detector that ran and found nothing are different facts, and collapsing them
#: is how "we checked" becomes an unearned claim.
PLATEAU_NOT_EVALUATED = "PLATEAU_NOT_EVALUATED"


@dataclass
class LoopObservation:
    """One loop's current state plus the real facts it was derived from.

    `evidence` is the point of this dataclass: section 86 requires state to
    derive from backend evidence, so every observation carries the actual field
    values it read. A reader can re-derive the verdict without trusting it."""
    loop_id: str
    state: str
    derived_from: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    plateau: str = PLATEAU_NOT_EVALUATED
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_oscillation_from_debug_loop_history(entries: List[Dict[str, Any]], *,
                                               fingerprint_fields=("failing_stage",
                                                                   "target_fail_edge"),
                                               repeat_threshold: int =
                                               DEFAULT_OSCILLATION_REPEAT_THRESHOLD
                                               ) -> Dict[str, Any]:
    """Oscillation over evidence THIS HARNESS ALREADY PERSISTS.

    `engine._record_debug_loop_round()` appends one real entry to the
    Blackboard `debug_loop_history` topic every time a stage's retries are
    exhausted and `graph_next(stage, FAIL)` routes it onward. A
    (failing_stage, target_fail_edge) pair seen `repeat_threshold` times is the
    literal "alternating/repeated action/result fingerprint" section 90 names,
    computed from records nobody wrote for this purpose and nobody can fake by
    prose.

    Exact-tuple matching, never fuzzy: both fields are graph node ids written
    by the engine itself. Returns the verdict plus the counts it was computed
    from, so the caller can show its work."""
    counts: Dict[tuple, int] = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        key = tuple(entry.get(f) for f in fingerprint_fields)
        if all(v is None for v in key):
            continue
        counts[key] = counts.get(key, 0) + 1
    repeated = {"|".join(str(p) for p in k): v
                for k, v in counts.items() if v >= repeat_threshold}
    return {
        "oscillating": bool(repeated),
        "repeat_threshold": repeat_threshold,
        "fingerprint_fields": list(fingerprint_fields),
        "repeated_fingerprints": repeated,
        "rounds_examined": len([e for e in (entries or []) if isinstance(e, dict)]),
    }


def observe_verification_closure_loop(state, cfg: Dict[str, Any], *,
                                      control_plane_state: Optional[Dict[str, Any]] = None,
                                      debug_loop_entries: Optional[List[Dict[str, Any]]] = None,
                                      stage: Optional[str] = None,
                                      convergence: Optional[Dict[str, Any]] = None,
                                      staleness: Optional[Dict[str, Any]] = None
                                      ) -> LoopObservation:
    """Derive the Verification Closure Loop's state from a REAL
    `models.HarnessState` plus the real ControlPlane payload and the real
    Blackboard `debug_loop_history` entries.

    Nothing here is asked of an agent: `state` comes off `state.json`,
    `control_plane_state` off `control.json`, `debug_loop_entries` off the
    Blackboard topic.

    `convergence` is one `loop_convergence.LoopConvergenceReport.to_dict()`,
    computed from the project's own evidence database (sections 88-90). When it
    is absent -- a project with no evidence database, or a caller that did not
    ask for one -- `plateau` stays `PLATEAU_NOT_EVALUATED`: a detector that
    never ran and a detector that ran and found nothing are different facts,
    and this is the one place that distinction is recorded.

    `staleness` is one `loop_stale_detection.detect_loop_staleness()` report
    (section 97): whether this session's last real event is older than a
    declared staleness window, or the project's own source moved (a real git
    diff at HIGH/MEDIUM risk) since the state being resumed. Absent -- a
    caller that did not ask, or a staleness check that itself failed -- the
    loop state is derived exactly as it always was (`stale=False`); a real
    `status: "STALE"` verdict from that report is the only thing that can move
    this observation's state to STALE, and only when the base state it would
    otherwise report is one of `STALE_ELIGIBLE_BASE_STATES`."""
    cp = control_plane_state or {}
    stage = stage or getattr(state, "current_stage", "")
    stages = getattr(state, "stages", {}) or {}
    ss = stages.get(stage, {}) if isinstance(stages, dict) else {}
    status = ss.get("status") or getattr(state, "overall_status", Status.NOT_STARTED.value)
    attempts = ss.get("attempts")
    max_attempts = (cfg.get("policy", {}) or {}).get("max_stage_retries")
    takeover = bool((cp.get("takeover") or {}).get("active"))
    paused = bool(cp.get("paused"))
    osc = detect_oscillation_from_debug_loop_history(debug_loop_entries or [])
    loop_done = getattr(state, "overall_status", None) == Status.CLOSED.value

    # Sections 88-90's verdict, when a real one was computed for this project.
    conv = convergence if isinstance(convergence, dict) else None
    conv_verdict = (conv or {}).get("verdict")
    plateau_field = PLATEAU_NOT_EVALUATED
    note = ("plateau is NOT evaluated here: it needs a progress-metric series over "
            "iterations, whose real producers are trend_analysis.py / coverage_analysis.py. "
            "Reporting 'no plateau' without one would be an unearned claim.")
    # A verdict of UNKNOWN is NOT a plateau result: the classifier ran and
    # could not conclude (no database, no coverage sample, a single sample).
    # Recording it as the plateau field would present "we could not tell" as a
    # finding, which is the same unearned claim PLATEAU_NOT_EVALUATED prevents.
    if conv and conv_verdict and conv_verdict != "UNKNOWN":
        plateau_field = conv_verdict
        note = (f"plateau/convergence evaluated by loop_convergence."
                f"classify_loop_convergence() over "
                f"{(conv.get('sources') or {}).get('series_points')} real "
                f"{conv.get('metric')} samples: "
                f"{(conv.get('convergence') or {}).get('reason')}")
    elif conv:
        note = (f"plateau is NOT evaluated: {conv.get('reason')} -- "
                f"trend_analysis.py / coverage_analysis.py produced no usable series for "
                f"this project, and 'no plateau' without one would be an unearned claim.")

    # Section 97: a real staleness verdict, when one was computed for this
    # project -- never re-derived here. `is_stale` defaults False so an
    # absent/failed staleness check changes nothing about the state this
    # function would otherwise report.
    stale_report = staleness if isinstance(staleness, dict) else None
    is_stale = bool(stale_report.get("is_stale")) if stale_report else False
    if stale_report:
        note = (note + " | " if note else "") + (
            f"staleness ({stale_report.get('status')}): "
            f"{'; '.join(s.get('reason', '') for s in (stale_report.get('signals') or []))}")

    loop_state = derive_loop_state(
        status, attempts=attempts, max_attempts=max_attempts,
        paused=paused, takeover_active=takeover, loop_done=loop_done,
        oscillating=bool(osc["oscillating"]),
        plateau=(conv_verdict == LoopState.PLATEAU.value),
        progress_oscillating=(conv_verdict == LoopState.OSCILLATING.value),
        stale=is_stale)
    return LoopObservation(
        loop_id=VERIFICATION_CLOSURE_LOOP,
        state=loop_state.value,
        derived_from=("models.HarnessState + ControlPlane state + Blackboard "
                      "debug_loop_history"
                      + (" + loop_convergence over the evidence database" if conv else "")
                      + (" + loop_stale_detection over state.json/events.jsonl/git"
                         if stale_report else "")),
        evidence={
            "stage": stage,
            "stage_status": status,
            "attempts": attempts,
            "max_stage_retries": max_attempts,
            "overall_status": getattr(state, "overall_status", None),
            "paused": paused,
            "takeover_active": takeover,
            "oscillation": osc,
            "convergence": conv,
            "staleness": stale_report,
        },
        plateau=plateau_field,
        note=note,
    )


#: Every one of `capability_evolution.PROMOTION_STATES`, mapped to its
#: loop-control meaning. TOTAL by construction
#: (`assert_capability_state_mapping_total()`).
#:
#: PROPOSED / BENCHMARKED / PROMOTION_CANDIDATE all map to HUMAN_GATE because
#: every legal edge out of them is a human's move -- that is the governance
#: boundary, restated in loop vocabulary, not weakened by it. REJECTED is
#: CANCELLED (a deliberate human decision) rather than FAILED (a machine-
#: checkable done that was not met); ROLLED_BACK is FAILED.
CAPABILITY_STATE_TO_LOOP_STATE: Dict[str, LoopState] = {
    "DISCOVERED": LoopState.CREATED,
    "EVIDENCE_GATHERING": LoopState.RUNNING,
    "PROPOSED": LoopState.HUMAN_GATE,
    "EXPERIMENT_APPROVED": LoopState.READY,
    "EXPERIMENTING": LoopState.RUNNING,
    "BENCHMARKED": LoopState.HUMAN_GATE,
    "PROMOTION_CANDIDATE": LoopState.HUMAN_GATE,
    "HUMAN_APPROVED": LoopState.READY,
    "PRODUCTION": LoopState.SUCCESS,
    "REJECTED": LoopState.CANCELLED,
    "ROLLED_BACK": LoopState.FAILED,
}


def assert_capability_state_mapping_total() -> None:
    from . import capability_evolution as ce
    missing = [s for s in ce.PROMOTION_STATES
               if s not in CAPABILITY_STATE_TO_LOOP_STATE]
    if missing:
        raise AssertionError(
            f"capability_evolution.PROMOTION_STATES members with no LoopState meaning "
            f"decided: {missing}")
    unknown = [k for k in CAPABILITY_STATE_TO_LOOP_STATE
               if k not in ce.PROMOTION_STATES]
    if unknown:
        raise AssertionError(
            f"CAPABILITY_STATE_TO_LOOP_STATE names non-promotion states: {unknown}")


def observe_capability_evolution_loop(candidate: Dict[str, Any]) -> LoopObservation:
    """Derive the Capability Evolution Loop's state from a REAL candidate dict
    as `capability_evolution.read_candidate()` returns it."""
    current = (candidate or {}).get("current_status")
    if current not in CAPABILITY_STATE_TO_LOOP_STATE:
        raise ValueError(
            f"candidate {(candidate or {}).get('candidate_id')!r} carries "
            f"current_status {current!r}, which is not a capability_evolution "
            f"promotion state")
    loop_state = CAPABILITY_STATE_TO_LOOP_STATE[current]
    return LoopObservation(
        loop_id=CAPABILITY_EVOLUTION_LOOP,
        state=loop_state.value,
        derived_from="capability_evolution candidate.current_status (Blackboard topic "
                     "'capability_evolution_candidates')",
        evidence={
            "candidate_id": candidate.get("candidate_id"),
            "current_status": current,
            "overlap_status": candidate.get("overlap_status"),
            "recommendation": (candidate.get("recommendation") or {}).get("value")
                              if isinstance(candidate.get("recommendation"), dict)
                              else candidate.get("recommendation"),
            "experiment_required": candidate.get("experiment_required"),
            "has_benchmark_result": bool(candidate.get("benchmark_result")),
        },
        note=("HUMAN_GATE here is an OBSERVATION that a human decision is owed. It "
              "authorizes nothing: assert_human_approval() still requires a real "
              "ControlPlane approval on disk."),
    )


#: A routed memory destination's loop-control meaning. WORKING/JOB/PROJECT are
#: RUNNING (the record is in the loop but has cleared no promotion gate);
#: ENGINEERING is CONVERGING (a real gate cleared, confirmations accumulating);
#: ORGANIZATIONAL is SUCCESS. REJECT never reaches an observation -- it raises
#: in route_and_store() and nothing is persisted.
MEMORY_DESTINATION_TO_LOOP_STATE: Dict[str, LoopState] = {
    "WORKING_MEMORY": LoopState.RUNNING,
    "JOB_MEMORY": LoopState.RUNNING,
    "PROJECT_MEMORY": LoopState.RUNNING,
    "ENGINEERING_MEMORY": LoopState.CONVERGING,
    "ORGANIZATIONAL_MEMORY": LoopState.SUCCESS,
    "CORNER_CASE_LIBRARY": LoopState.CONVERGING,
    "BLACKBOARD": LoopState.RUNNING,
    "CLAUDE_PROJECT_MEMORY": LoopState.HUMAN_GATE,
}


def observe_project_learning_loop(routing_result: Dict[str, Any], *,
                                  confirmation_count: Optional[int] = None
                                  ) -> LoopObservation:
    """Derive the Project Learning Loop's state from a REAL
    `memory_router.route_and_store()` result dict.

    An admission REJECTION (the `engineering_admission_rejected` /
    `organizational_admission_rejected` key the router writes onto a demoted
    record) is BLOCKED, not RUNNING: the record really did fail a gate, and
    reporting it as merely "in the loop" would hide that."""
    from .memory_router import ORGANIZATIONAL_MIN_CONFIRMATIONS
    result = routing_result or {}
    destination = result.get("destination")
    rejected = [k for k in ("engineering_admission_rejected",
                            "organizational_admission_rejected")
                if result.get(k) or (isinstance(result.get("record"), dict)
                                     and result["record"].get(k))]
    if rejected:
        loop_state = LoopState.BLOCKED
    elif destination in MEMORY_DESTINATION_TO_LOOP_STATE:
        loop_state = MEMORY_DESTINATION_TO_LOOP_STATE[destination]
    else:
        raise ValueError(
            f"routing result carries destination {destination!r}, which is not a known "
            f"memory_router destination ({sorted(MEMORY_DESTINATION_TO_LOOP_STATE)})")
    return LoopObservation(
        loop_id=PROJECT_LEARNING_LOOP,
        state=loop_state.value,
        derived_from="memory_router.route_and_store() result destination",
        evidence={
            "destination": destination,
            "admission_rejections": rejected,
            "confirmation_count": confirmation_count,
            "organizational_min_confirmations": ORGANIZATIONAL_MIN_CONFIRMATIONS,
            "confirmations_remaining": (
                None if confirmation_count is None
                else max(0, ORGANIZATIONAL_MIN_CONFIRMATIONS - confirmation_count)),
        },
    )


# --------------------------------------------------------------------------
# CLI-facing verb implementation (shared by cli.py and __main__ below)
# --------------------------------------------------------------------------
def execute_verb(root: Path, verb: str, *,
                 loop_id: Optional[str] = None,
                 cfg: Optional[Dict[str, Any]] = None,
                 fmt: str = "json") -> tuple:
    """Returns (exit_code, payload). One implementation, reused by
    `dv-harness loop-contract` and `python -m dv_harness.loop_contract` --
    two handlers over the same behaviour is the parallel-mechanism defect
    this project forbids, at CLI scale."""
    root = Path(root)
    if cfg is None:
        from .config import load_config
        cfg = load_config(root)

    if verb == "states":
        return 0, {
            "loop_states": list(LOOP_STATE_VALUES),
            "terminal": [s.value for s in TERMINAL_LOOP_STATES],
            "resumable": [s.value for s in RESUMABLE_LOOP_STATES],
            "legal_transitions": {str(k): list(v) for k, v in LEGAL_LOOP_TRANSITIONS.items()},
            "status_to_loop_state": {k: v.value for k, v in STATUS_TO_LOOP_STATE.items()},
            "loop_states_without_status_equivalent":
                [s.value for s in LOOP_STATES_WITHOUT_STATUS_EQUIVALENT],
        }

    if verb == "list":
        contracts = build_all_contracts(cfg)
        return 0, {"loops": [
            {"loop_id": c.loop_id, "loop_type": c.loop_type, "owner": c.owner,
             "driver": f"{c.driver_module}.{c.driver_entry_point}",
             "machine_checkable_done": c.machine_checkable_done}
            for c in contracts.values()]}

    if verb == "show":
        if not loop_id:
            return 1, {"ok": False, "error": "LOOP_ID_REQUIRED", "known": loop_ids()}
        if loop_id not in CONTRACT_BUILDERS:
            return 1, {"ok": False, "error": "UNKNOWN_LOOP_ID", "loop_id": loop_id,
                       "known": loop_ids()}
        contract = (verification_closure_contract(cfg)
                    if loop_id == VERIFICATION_CLOSURE_LOOP
                    else CONTRACT_BUILDERS[loop_id]())
        validate_contract(contract)
        assert_driver_resolvable(contract)
        if fmt == "yaml":
            return 0, {"loop_id": loop_id, "yaml": contract.to_yaml()}
        return 0, contract.to_dict()

    if verb == "observe":
        payload = observe_all(root, cfg)
        return 0, payload

    if verb == "convergence":
        # Sections 88-90 on their own, for a caller that wants the series
        # verdict and the plateau investigation without the whole observation.
        from . import loop_convergence as _lcv
        from .blackboard import Blackboard
        try:
            history = (Blackboard(root).read_debug_loop_history() or {}).get("entries") or []
        except Exception:
            history = []
        report = _lcv.classify_loop_convergence(root, cfg=cfg,
                                                debug_loop_entries=history).to_dict()
        # Exit 2 on UNKNOWN, not merely on an absent series: a one-sample
        # project reached the classifier and still has no usable verdict, and
        # exiting 0 there would report "we could not tell" as a result.
        return (2 if report.get("verdict") == _lcv.UNKNOWN else 0), report

    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["states", "list", "show", "observe", "convergence"]}


def observe_all(root: Path, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Observe every loop that has real state on disk for this project.

    Best-effort per loop and honest about absence: a loop with no persisted
    state yet reports `NOT_OBSERVABLE` plus the reason, never a fabricated
    CREATED."""
    from .blackboard import Blackboard
    from .control_plane import ControlPlane
    from .storage import StateStore

    root = Path(root)
    if cfg is None:
        from .config import load_config
        cfg = load_config(root)
    out: Dict[str, Any] = {"root": str(root), "observations": {}}

    # Sections 88-90, best-effort and READ-ONLY: a project with no evidence
    # database simply has no series, which observe_verification_closure_loop()
    # then reports as PLATEAU_NOT_EVALUATED rather than as "no plateau".
    convergence = None
    try:
        from . import loop_convergence as _lcv
        bb_for_conv = Blackboard(root)
        conv_history = bb_for_conv.read_debug_loop_history() or {}
        convergence = _lcv.classify_loop_convergence(
            root, cfg=cfg,
            debug_loop_entries=conv_history.get("entries") or []).to_dict()
        out["convergence"] = convergence
    except Exception as exc:
        out["convergence"] = {"available": False,
                              "reason": f"{type(exc).__name__}: {exc}"}

    # Section 97, best-effort and READ-ONLY: a staleness check that itself
    # fails to run (no git, an unresolvable recorded SHA) must never crash
    # this observation -- observe_verification_closure_loop() treats an
    # absent report exactly as it always has (stale=False), never guessing.
    staleness = None
    try:
        from . import loop_stale_detection as _lsd
        staleness = _lsd.detect_loop_staleness(root, cfg)
        out["staleness"] = staleness
    except Exception as exc:
        out["staleness"] = {"status": "UNKNOWN", "is_stale": False,
                            "reason": f"{type(exc).__name__}: {exc}"}

    try:
        state = StateStore(root).load()
        bb = Blackboard(root)
        history = bb.read_debug_loop_history() or {}
        obs = observe_verification_closure_loop(
            state, cfg,
            control_plane_state=ControlPlane(root).load(),
            debug_loop_entries=history.get("entries") or [],
            convergence=convergence,
            staleness=staleness)
        out["observations"][VERIFICATION_CLOSURE_LOOP] = obs.to_dict()
    except Exception as exc:  # observability must never crash a caller
        out["observations"][VERIFICATION_CLOSURE_LOOP] = {
            "loop_id": VERIFICATION_CLOSURE_LOOP, "state": "NOT_OBSERVABLE",
            "reason": f"{type(exc).__name__}: {exc}"}

    try:
        from . import capability_evolution as ce
        candidates = (ce.read_candidates(root) or {}).get("candidates") or []
        if not candidates:
            out["observations"][CAPABILITY_EVOLUTION_LOOP] = {
                "loop_id": CAPABILITY_EVOLUTION_LOOP, "state": "NOT_OBSERVABLE",
                "reason": "NO_CANDIDATES_ON_FILE"}
        else:
            out["observations"][CAPABILITY_EVOLUTION_LOOP] = [
                observe_capability_evolution_loop(c).to_dict() for c in candidates]
    except Exception as exc:
        out["observations"][CAPABILITY_EVOLUTION_LOOP] = {
            "loop_id": CAPABILITY_EVOLUTION_LOOP, "state": "NOT_OBSERVABLE",
            "reason": f"{type(exc).__name__}: {exc}"}

    # The Project Learning Loop is observed PER RECORD at its write site
    # (observe_project_learning_loop() takes a route_and_store() result), so
    # there is no single project-wide state to report here. Saying so is the
    # honest answer; inventing an aggregate would be a metric nothing produces.
    out["observations"][PROJECT_LEARNING_LOOP] = {
        "loop_id": PROJECT_LEARNING_LOOP, "state": "NOT_OBSERVABLE",
        "reason": "PER_RECORD_LOOP: observe_project_learning_loop() takes one "
                  "memory_router.route_and_store() result; this loop has no project-wide "
                  "current state to report."}
    return out


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    ap = argparse.ArgumentParser(prog="python -m dv_harness.loop_contract",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("verb", choices=["states", "list", "show", "observe", "convergence"])
    ap.add_argument("--loop-id", default=None)
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--format", default="json", choices=["json", "yaml"], dest="fmt")
    args = ap.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 loop_id=args.loop_id, fmt=args.fmt)
    if args.fmt == "yaml" and "yaml" in payload:
        print(payload["yaml"])
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
