from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

class Stage(str, Enum):
    # Mechanism-first canonical order (per project direction, 2026-08-27):
    # Intake -> five-source discovery (spec/RTL/command.txt/USB reference/DE
    # local sim) -> DE baseline reproduction (-> BASELINE_LOCKED) -> RTL-first
    # DUT architecture discovery -> project model -> protocol capability
    # discovery -> requirements/waiver -> vPlan -> verification architecture
    # (+ observability) -> implement (monitors/checkers/tests) -> build/verify
    # (command.txt<->sim.log semantic check, false-pass defense, TRUE_PASS) ->
    # LSF regression -> coverage closure -> failure recovery (RCA/replay/fix/
    # non-regression) -> system-level -> expert feedback closed loop ->
    # requirement closure -> promotion readiness -> signoff.
    ENV_CHECK = "ENV_CHECK"
    INTAKE = "INTAKE"
    DISCOVERY = "DISCOVERY"
    COMMAND_PATTERN = "COMMAND_PATTERN"
    DE_BASELINE_REPRODUCTION = "DE_BASELINE_REPRODUCTION"
    ARCH_DISCOVERY = "ARCH_DISCOVERY"
    ARCH_CALIBRATION = "ARCH_CALIBRATION"
    PROJECT_MODEL = "PROJECT_MODEL"
    PROTOCOL_CAPABILITY = "PROTOCOL_CAPABILITY"
    REQUIREMENTS_TRACEABILITY = "REQUIREMENTS_TRACEABILITY"
    SOC_SCENARIO_PLANNER = "SOC_SCENARIO_PLANNER"
    INFRASTRUCTURE_AUDIT = "INFRASTRUCTURE_AUDIT"
    VPLAN = "VPLAN"
    VERIFICATION_ARCHITECTURE = "VERIFICATION_ARCHITECTURE"
    IMPLEMENT = "IMPLEMENT"
    CHANGE_IMPACT = "CHANGE_IMPACT"
    GIT_SYNC = "GIT_SYNC"
    GIT_PUSH = "GIT_PUSH"
    SERVER_SYNC = "SERVER_SYNC"
    BUILD = "BUILD"
    BUILD_DEBUG = "BUILD_DEBUG"
    VERIFY = "VERIFY"
    WAVE_ANALYSIS = "WAVE_ANALYSIS"
    REGRESSION_SELECT = "REGRESSION_SELECT"
    REGRESSION = "REGRESSION"
    REGRESSION_MONITOR = "REGRESSION_MONITOR"
    COVERAGE_CLOSURE = "COVERAGE_CLOSURE"
    INFRA_RECOVERY = "INFRA_RECOVERY"
    FAILURE_RECOVERY = "FAILURE_RECOVERY"
    RE_AUDIT = "RE_AUDIT"
    SYSTEM_LEVEL = "SYSTEM_LEVEL"
    EXPERT_FEEDBACK_LOOP = "EXPERT_FEEDBACK_LOOP"
    REQUIREMENT_CLOSURE = "REQUIREMENT_CLOSURE"
    PROMOTION_READINESS = "PROMOTION_READINESS"
    SIGNOFF = "SIGNOFF"

class Status(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    RETRY = "RETRY"
    WAIT_USER = "WAIT_USER"
    CLOSED = "CLOSED"
    ACCEPTED_RISK = "ACCEPTED_RISK"

@dataclass
class StageState:
    stage: str
    status: str = Status.NOT_STARTED.value
    attempts: int = 0
    session_id: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_message: str = ""
    evidence: List[str] = field(default_factory=list)
    blocking_reason: str = ""
    # Set only by engine.py's inner ReAct loop (dv_harness/react_loop.py) when
    # its chosen action is REROUTE -- consulted (never required) by loop()'s
    # retry-exhaustion branch as a preference over the static graph FAIL edge,
    # never instead of it. None means "no content-driven reroute hint for
    # this attempt", the byte-identical default for every stage that never
    # runs the inner loop (react:false nodes, or verdict never reached
    # GATE_FAIL/DV_REVIEW_PENDING in the first place).
    react_reroute_target: Optional[str] = None
    # This stage's own most recent submitted evidence blocks (2026-09-01,
    # expected-evidence-checklist design pass) -- engine.run_stage() sets
    # this from gates.extract_evidence_blocks()'s output on any attempt that
    # produced at least one block (never cleared to {} by an attempt that
    # produced none, e.g. ADAPTER_FAIL). Consumed by
    # engine.build_stage_entry_checklist()'s "evidence_field" item
    # resolution on a LATER attempt/stage -- see that function's docstring.
    # Additive/optional: a stage state loaded from a state.json saved before
    # this field existed simply has no key here, and every reader uses
    # dict.get(..., {}) so that degrades to "nothing submitted yet", never a
    # KeyError.
    last_evidence_blocks: Dict[str, Any] = field(default_factory=dict)

@dataclass
class HarnessState:
    version: str = "15.0.0"
    # project / findings_total / findings_closed / findings_open (2026-08-29
    # reconciliation): read-only mirrors DVHarness keeps synced FROM the
    # blackboard (engine.py's _sync_project_from_blackboard/
    # _sync_findings_state) -- never assign these directly from anywhere
    # else, or they will drift out of agreement with the real records
    # (blackboard "project" topic's target_name; blackboard "findings"
    # topic's items registry) again.
    project: str = ""
    scope: str = "unknown"
    current_stage: str = Stage.ENV_CHECK.value
    overall_status: str = Status.NOT_STARTED.value
    git_sha: Optional[str] = None
    server_sha: Optional[str] = None
    # dut_version / tb_version (session-snapshot-extension, 2026-09-01):
    # project-wide DUT RTL / testbench build identity, alongside git_sha/
    # server_sha above -- same CLAUDE.md "same regression batch must use the
    # same source/build/config identity" rule, but naming the DUT/TB
    # revision specifically rather than this harness repo's own git SHA
    # (a DUT/TB revision is generally a separate identity from the harness
    # engine's source tree). Real writer:
    # DVHarness._sync_dut_tb_version_from_blackboard() (engine.py) -- a
    # read-only derived mirror of the blackboard "verification_state"
    # topic's results[], populated only from VERIFY stage's real,
    # gate-enforced test_result_provenance_gate evidence (rtl_revision/
    # tb_revision are REQUIRED non-empty per result by that gate script --
    # see tools/verification_flow/test_result_provenance_gate.py -- so any
    # real VERIFY PASS already carries real identity strings here, never
    # fabricated). None until a real VERIFY result has reported one -- the
    # honest bootstrap default, not a placeholder value.
    dut_version: Optional[str] = None
    tb_version: Optional[str] = None
    closure_iteration: int = 0
    findings_total: int = 0
    findings_closed: int = 0
    findings_open: int = 0
    last_session_id: Optional[str] = None
    stages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Graph-level parallel fan-out/join (2026-08-29, extended 2026-08-29 by
    # the active_stages read-site audit): current_stage stays a scalar
    # string, exactly as before, and is never itself restructured --
    # active_stages is purely additive: empty ([]) means "no fan-out in
    # flight, current_stage alone is authoritative"; engine.py's
    # _advance_with_fanout() populates it with the real branch ids for the
    # duration of a live fan-out (current_stage itself stays parked on the
    # fan-out's source node throughout) and clears it back to [] once the
    # join resolves and current_stage advances past it.
    #
    # Consumers that deliberately still read current_stage alone (assessed,
    # not oversights): engine.py's run_stage()/loop() internal stage-walk,
    # mark()/commands.cmd_mark()/cmd_takeover() (no way yet for a caller to
    # name one specific branch -- see their own NOTEs), and
    # commands.cmd_set_stage()/cmd_advance()'s from_stage audit field (they
    # operate on current_stage by design). Consumers upgraded by that audit
    # to also read active_stages/effective_active_stages() so a live
    # fan-out is visible, not just its parked source node: engine.py's
    # summary(), cli.py's explain/evidence (no --stage given), dashboard.py's
    # /api/state active_stages_detail, graph-highlight, and showExplain(),
    # and session_snapshot.py's saved-session manifest.
    active_stages: List[str] = field(default_factory=list)
    # "Just transitioned" signal (2026-09-01, runtime-progress-visibility
    # pass): a real, persisted "this stage just reached a terminal status"
    # record, written by engine.run_stage() every time it sets ss["status"]
    # to a terminal value (PASS/FAIL/PARTIAL/WAIT_USER/BLOCKED -- i.e.
    # whenever the stage stops RUNNING). Distinct from current_stage/
    # overall_status (a snapshot of WHERE things are now, silently
    # overwritten every stage) -- this is WHEN the last change actually
    # happened and WHAT it changed to, so a dashboard viewer polling every
    # 3s can render a "Last transition" banner instead of a status tile that
    # updates with no visible signal. None until the first stage completes
    # in a project's history. Shape: {"stage": str, "status": str,
    # "at": iso8601 str}. Additive/optional: a state.json saved before this
    # field existed simply has no key here, degrading to None (no banner),
    # never a KeyError -- same convention as last_evidence_blocks above.
    last_transition: Optional[Dict[str, Any]] = None

    def effective_active_stages(self) -> List[str]:
        return self.active_stages or [self.current_stage]

    def ensure_stages(self):
        for s in Stage:
            self.stages.setdefault(s.value, asdict(StageState(stage=s.value)))
