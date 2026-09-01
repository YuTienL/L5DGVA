from __future__ import annotations
import json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from .models import HarnessState, Stage, Status
from .storage import StateStore
from .config import load_config
from .prompts import build_stage_prompt
from .policy import next_stage, graph_next, can_signoff
from .gates import evaluate_stage_evidence, extract_evidence_blocks, STAGE_GATES, JUDGMENT_FIELDS
from .react_loop import InnerReactLoop, evaluate_stage_evidence_with_detail
from .memory_router import route_and_store
from .inference import score_confidence, identify_gap, next_best_action, promote_if_high_confidence
from .qualified_conclusion import build_qualified_conclusion
from .knowledge_center import KnowledgeCenterClient
from .adapters.cli import ClaudeCLIAdapter
from .adapters.sdk import ClaudeCodeSDKAdapter
from .adapters.base import AgentResult
from .stage_profile import StageExecutionProfiler, extract_provider_usage
from .control_plane import ControlPlane, replan_stage, _find_latest_plan
from .agent_profile import load_agent_profile

# --- Plan-and-Execute / Multi-Agent / Blackboard / ReAct wiring -------------
# planner.py, react.py, router.py, multi_agent.py, skill_resolver.py were all
# confirmed (2026-08-28 architecture audit) to be correct but never imported
# by any executing code path -- graph_runtime.py already wired all of them
# together (prepare_node/complete_node) but graph_runtime.py itself was never
# imported by engine.py or cli.py either. Rather than importing
# graph_runtime.GraphRuntime wholesale (its prepare_node/complete_node shape
# doesn't line up 1:1 with run_stage()'s single-call-per-attempt model, e.g.
# it would create a brand new plan/task on every retry with no reuse
# concept), this reuses the same underlying modules directly inside
# run_stage(), and reuses control_plane.py's already-real REPLAN call site
# (replan_stage/_find_latest_plan, wired in by a parallel pass on this same
# file) for plan lookup/replanning instead of re-deriving that logic here.
# graph.py's GraphDefinition (node-by-id lookup) is reused as-is -- it
# already does this correctly; see _load_graph() below.
from .graph import GraphDefinition
from .parallel_frontier import ParallelFrontierStore
from .blackboard import Blackboard
from .router import RouteResolver
from .planner import PlanStore, default_plan
from .multi_agent import MultiAgentOrchestrator
from .react import ReactRecorder
from .skill_resolver import SkillResolver
# --- Real, input-driven protocol/environment-mode resolution (2026-09-01,
# route-skill-resolver-dynamic-implementation task): RouteResolver.resolve()/
# SkillResolver.resolve() above are real callers but only ever do a STATIC
# dict lookup on the graph node's own pre-declared route/agent/skills fields
# (see router.py's own NOTICE) -- the same route/agent/skills come back
# regardless of protocol/failure/evidence. These two resolvers apply the
# genuinely input-driven rules documented in .claude/skills/CORE/
# protocol-router/SKILL.md and CLAUDE.md's "Environment Generation Mode"
# gate (previously prose-only -- see each module's own docstring for the
# full gap/ruling this closes). Their real output is folded into route_info
# in run_stage() below, alongside the two calls above.
from .protocol_router import resolve_protocol
from .environment_mode_router import resolve_environment_mode, read_registered_subsystem_names
from .uvm_generator.generator import sv_id
from .uvm_generator.soc_environment_composer import (
    compose_soc_environment, EmptySubsystemRegistryError, MissingSubsystemNameEvidenceError,
)

def now():
    return datetime.now(timezone.utc).isoformat()


# --- Cross-cycle debug-loop counter / Health Monitor dispatch (2026-09-01,
# ai-debug-closed-loop-counter-implementation task) -------------------------
# Architecture audit finding this closes: state.stages[stage]['attempts']
# (ss['attempts'] in run_stage()/loop() below, capped by
# policy.max_stage_retries) is real, but it is node-scoped RETRY bookkeeping
# for ONE graph node's own attempts, not a purpose-built counter for "how
# many full Fix->Push->Build->Verify passes has this failure gone through" --
# a single logical debug-loop round can span several different graph nodes
# (e.g. BUILD fails -> FAILURE_RECOVERY -> CHANGE_IMPACT -> ... -> BUILD
# again), and ss['attempts'] resets to 0 the moment current_stage moves on,
# so it cannot answer a whole-run question. DVHarness._record_debug_loop_round()
# below appends one real, persisted entry to the Blackboard "debug_loop_history"
# topic (see blackboard.py's own docstring for the entry shape and the two
# real call sites) every time loop()/_advance_with_fanout() actually calls
# policy.graph_next(stage, Status.FAIL.value, ...) to route a stage whose
# retries are exhausted onto its graph FAIL edge -- a real query
# (Blackboard.debug_loop_round_count()) can then answer that whole-run
# question directly from persisted history, not by re-deriving it from a
# per-node counter that was never designed to answer it.
#
# Second finding this closes: CLAUDE.md's own "Background Job/Log Monitor
# Auto-Start" section is explicit that "there is no Python code path that
# fires automatically" for Health Monitor dispatch -- starting the watcher
# is a protocol instruction the agent must remember to follow, not an
# engine event. DVHarness._health_monitor_check() below makes the STATUS
# CHECK half of that real and engine-triggered: on a FAIL-edge route for a
# stage whose graph node.route implies remote/LSF execution was involved,
# the engine itself invokes `dv-harness lsf-watch-status` (a real
# subprocess call, same convention as gates.py's run_gate()) and records
# the real result into that same debug_loop_history entry. It deliberately
# never starts a watcher and never touches the SSH/Telnet remote hop or
# tools/remote/remote_relay.py's invocation restrictions -- both remain the
# deliberate, policy-mandated human/agent steps CLAUDE.md documents; see
# _health_monitor_check()'s own docstring for the full ruling.
#
# RULING: node.route (graph.py's Node dataclass -- the only real categorical
# field main_graph.json's nodes carry) is the evidence used to decide
# "remote/LSF execution was involved", not a guess: "build-route" nodes
# (DE_BASELINE_REPRODUCTION, SERVER_SYNC, BUILD, BUILD_DEBUG, VERIFY) and
# "regression-route" nodes (REGRESSION_SELECT, REGRESSION,
# REGRESSION_MONITOR, COVERAGE_CLOSURE, INFRA_RECOVERY) are the ones whose
# real `skills` (vcs-build/devops-pipeline/verification-signoff) and
# templates (dv_harness/uvm_generator/templates/sim_scripts/lsf_*.sh)
# actually submit/poll a VCS build or LSF regression job -- confirmed by
# reading main_graph.json itself. analysis-route/implementation-route/
# review-route/debug-route/lead-route nodes never submit one themselves
# (e.g. WAVE_ANALYSIS/FAILURE_RECOVERY read evidence a remote run already
# produced; they do not submit one).
REMOTE_LSF_ROUTES = {"build-route", "regression-route"}

# The directory containing the dv_harness package itself (parent of this
# file's own parent), used only to extend PYTHONPATH for the
# `-m dv_harness.cli` subprocess call in _health_monitor_check() below --
# self.root (the DV project being verified) is an arbitrary, unrelated
# directory that may not have dv_harness importable from it at all.
_ENGINE_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


# --- Blackboard write mapping: evidence field -> blackboard topic ----------
# Per node.blackboard_write in main_graph.json, run_stage() writes one
# Blackboard entry per declared topic, sourced from the stage's OWN
# extracted evidence block(s) -- never a placeholder. Only stages with a
# mapped STAGE_GATES entry (dv_harness/gates.py) have machine-checkable
# evidence blocks to draw from; four concrete worked examples below cover
# an early stage, the central hard-gated stage, a regression stage, and
# INTAKE's project-identity record. Every other blackboard_write-declaring
# node falls back to _bb_generic_fallback (still real: the node's own
# PASS'd response text and whatever evidence block(s) it happened to emit --
# not a fabricated value), so no node silently writes nothing.
#
# "findings" topic reconciliation (2026-08-29): INFRASTRUCTURE_AUDIT and
# FAILURE_RECOVERY both declare blackboard_write:["findings"]. Prior to this
# pass each write went through _bb_generic_fallback like any other topic --
# a full overwrite of the topic with that one stage's narrative blob, and
# state.findings_total/open/closed (models.py) were a SEPARATE dataclass
# field never assigned by any code path (always stuck at their 0 default).
# The two could never have agreed. Fixed by making the blackboard "findings"
# topic (Blackboard.read_findings()/upsert_finding()/findings_counts() in
# blackboard.py) the one real structured registry, and state.findings_* a
# read-only mirror _sync_findings_state() recomputes from it on every write
# (see _write_blackboard_from_evidence below) and on every DVHarness load --
# there is no longer any other place the counts can come from.
#
# "project" reconciliation (2026-08-29): state.project, blackboard "project"
# (written by INTAKE from intake_readiness evidence), and blackboard
# "project_model" (written by PROJECT_MODEL from project_model_topology_
# completeness_gate evidence) are NOT three copies of the same data -- they
# are legitimately different shapes: "project" is INTAKE's identity/scope
# record (mode/target_name/protocols/required_artifacts, gates.py's
# "intake_readiness"), "project_model" is a later stage's discovered
# verification-boundary/VIP-topology/block-classification model (gates.py's
# "project_model_topology_completeness_gate") built FROM architecture
# evidence, not from intake answers -- confirmed by reading both gate
# scripts' required fields, which do not overlap. state.project, however,
# WAS a pure duplicate: a bare display-name string bootstrapped once to the
# project directory name (storage.py's StateStore.load()) and never
# refreshed after INTAKE actually determined the real target_name -- fixed
# by making it a read-only derived view of blackboard "project".target_name
# (_sync_project_from_blackboard below), not an independently-written copy.

def _bb_env_check(evidence: dict, stage: str, result) -> Dict[str, Any]:
    ev = evidence.get("execution_mode_validator", {})
    return {"environment": {
        "execution_mode": ev.get("execution_mode"),
        "actions": ev.get("actions", []),
        "session_id": result.session_id,
    }}

def _bb_verify(evidence: dict, stage: str, result) -> Dict[str, Any]:
    sim = evidence.get("simulation_semantic_validation_gate", {})
    prov = evidence.get("test_result_provenance_gate", {})
    fpr = evidence.get("false_pass_resistance_gate", {})
    return {"verification_state": {
        "simulation_passed": sim.get("simulation_passed"),
        "results": prov.get("results", []),
        "oracle_independent": fpr.get("oracle_independent"),
        "negative_test_detects_fault": fpr.get("negative_test_detects_fault"),
    }}

def _bb_regression_monitor(evidence: dict, stage: str, result) -> Dict[str, Any]:
    lsf = evidence.get("lsf_per_job_monitor_gate", {})
    uniq = evidence.get("regression_result_uniqueness_gate", {})
    return {"regression_state": {
        "jobs": lsf.get("jobs", []),
        "results": uniq.get("results", []),
    }}

def _bb_intake(evidence: dict, stage: str, result) -> Dict[str, Any]:
    # INTAKE's own identity/scope record (gates.py's "intake_readiness"
    # evidence block) -- deliberately NOT the same shape as PROJECT_MODEL's
    # "project_model" topic (verification_boundary/vip_topology/blocks, built
    # later from architecture evidence); see the reconciliation note above
    # this function group for why the two stay separate topics.
    intake = evidence.get("intake_readiness", {})
    return {"project": {
        "mode": intake.get("mode"),
        "target_name": intake.get("target_name"),
        "protocols": intake.get("protocols", []),
        "selected_subsystems": intake.get("selected_subsystems", []),
        "required_artifacts": intake.get("required_artifacts", {}),
    }}

def _bb_generic_fallback(node, evidence: dict, stage: str, result) -> Dict[str, Any]:
    # Honest degrade for the majority of blackboard_write-declaring nodes with
    # no per-stage mapping written yet: records the real evidence blocks the
    # stage actually emitted (empty dict if the stage has no mapped gate at
    # all, e.g. DISCOVERY/PROJECT_MODEL) plus a truncated raw-text summary --
    # never a made-up value. Extend STAGE_BLACKBOARD_WRITERS with a precise
    # mapping (like the three above) as each stage's evidence shape is
    # confirmed worth pulling apart field-by-field.
    summary = {"evidence": evidence, "summary": (result.text or "")[:2000]}
    return {topic: summary for topic in node.blackboard_write}

STAGE_BLACKBOARD_WRITERS = {
    "ENV_CHECK": _bb_env_check,
    "INTAKE": _bb_intake,
    "VERIFY": _bb_verify,
    "REGRESSION_MONITOR": _bb_regression_monitor,
}


def _build_plan_section(route_info: dict, resolved_skills: list, plan: dict,
                         bb_snapshot: dict, task: dict) -> str:
    """Folds the resolved route/agent/skills/plan/blackboard-snapshot into the
    prompt so the agent's response is genuinely informed by an explicit plan,
    rather than the plan being write-only (Core Operating Rule: 'Graph is the
    global workflow authority')."""
    return (
        "\n---\n"
        "[Harness Plan-and-Execute / Multi-Agent / Blackboard context -- "
        "resolved by the harness BEFORE this call; this is the plan you are "
        "executing, not decorative]\n"
        f"Resolved route: {route_info['route']} -> agent: {route_info['agent']}\n"
        f"Resolved skills: {json.dumps(resolved_skills, ensure_ascii=False)}\n"
        f"Resolved protocol/profile (protocol_router.resolve_protocol): "
        f"{json.dumps(route_info.get('protocol_decision'), ensure_ascii=False)}\n"
        f"Resolved environment mode (environment_mode_router.resolve_environment_mode): "
        f"{json.dumps(route_info.get('environment_mode_decision'), ensure_ascii=False)}\n"
        f"Plan {plan['plan_id']} (revision {plan['revision']}), steps:\n"
        f"{json.dumps(plan['steps'], ensure_ascii=False, indent=2)}\n"
        f"Delegated multi-agent task: {task['task_id']} "
        f"(agent={task['agent']}, parallel_group={task['parallel_group']})\n"
        "Blackboard snapshot (prior-stage shared state -- treat as already-"
        "established prior evidence, do not re-derive it from scratch):\n"
        f"{json.dumps(bb_snapshot, ensure_ascii=False, indent=2)}\n"
        "---\n"
    )


def _reason_summary(route_info: Optional[dict], plan: Optional[dict], bb_snapshot: dict) -> str:
    if route_info is None or plan is None:
        return "no graph node resolved for this stage id; ran legacy prompt-only flow"
    return (
        f"Resolved via RouteResolver to agent={route_info['agent']} on "
        f"route={route_info['route']}; executing plan {plan['plan_id']} "
        f"rev {plan['revision']} ({len(plan['steps'])} step(s)); "
        f"blackboard priors read: {list(bb_snapshot.keys())}"
    )


class DVHarness:
    def __init__(self, project_root: Path):
        self.root = project_root.resolve()
        self.cfg = load_config(self.root)
        self.store = StateStore(self.root)
        self.state = self.store.load()
        self.adapter = self._adapter()
        self.profiler = StageExecutionProfiler(self.root)

        # Plan-and-Execute / Multi-Agent / Blackboard / ReAct (see module
        # docstring above): constructed unconditionally -- all four are
        # cheap, file-based, and create their own directories lazily.
        self.graph = self._load_graph()
        self.blackboard = Blackboard(self.root)
        self.router = RouteResolver()
        self.plans = PlanStore(self.root)
        self.agents = MultiAgentOrchestrator(self.root)
        self.react = ReactRecorder(self.root)
        self.skills = SkillResolver(self.root)
        # Reconcile state.findings_* against the blackboard "findings"
        # registry on every load -- see _sync_findings_state()'s own
        # docstring; keeps a state.json saved before this fix (or edited by
        # hand) from staying stuck disagreeing with the real registry.
        self._sync_findings_state()

    def _adapter(self):
        if self.cfg.get("adapter") == "sdk":
            return ClaudeCodeSDKAdapter(self.cfg)
        return ClaudeCLIAdapter(self.cfg)

    def _load_graph(self) -> Optional[GraphDefinition]:
        # Mirrors policy.py's own defensive _load_graph_edges: returns None
        # (not an exception) when main_graph.json is absent/unparsable, so a
        # project root without a graph file degrades to the pre-existing
        # prompt-only behavior instead of crashing run_stage().
        p = self.root / ".dv-harness" / "graph" / "main_graph.json"
        if not p.exists():
            return None
        try:
            return GraphDefinition.load(p)
        except Exception:
            return None

    def _git_sha(self) -> Optional[str]:
        try:
            return subprocess.check_output(
                ["git","rev-parse","HEAD"], cwd=self.root, text=True,
                stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            return None

    def _git_modified_files(self) -> List[str]:
        """Real, best-effort `git diff --name-only HEAD` against the current
        worktree -- the "modified files" tie-break source protocol-router/
        SKILL.md documents. Mirrors _git_sha()'s own defensive try/except
        (no git repo, no HEAD yet, git not on PATH, etc. all degrade to an
        empty list, never a fabricated guess)."""
        try:
            out = subprocess.check_output(
                ["git", "diff", "--name-only", "HEAD"], cwd=self.root, text=True,
                stderr=subprocess.DEVNULL,
            )
            return [line.strip() for line in out.splitlines() if line.strip()]
        except Exception:
            return []

    def _health_monitor_check(self, node) -> Optional[Dict[str, Any]]:
        """Real, engine-triggered Health Monitor status check (see the
        module-level ruling comment above REMOTE_LSF_ROUTES for the full
        gap this closes). Called only for a stage whose node.route is in
        REMOTE_LSF_ROUTES -- returns None otherwise (never fabricates a
        check that didn't apply).

        RULING: this only CHECKS status (`dv-harness lsf-watch-status`,
        i.e. regression_reporter.watcher_status() under the hood) -- it
        never starts a watcher (`lsf-watch-start`) and never touches the
        SSH/Telnet remote hop or tools/remote/remote_relay.py's invocation
        restrictions. Both remain the deliberate, policy-mandated human/
        agent steps CLAUDE.md's SSH/Remote Transport Connection Intake gate
        and Background Job/Log Monitor Auto-Start section document;
        automating either from inside FAIL-edge routing would silently
        bypass that gate. A missing/unreachable watcher, or any subprocess
        failure, is recorded here as real (negative) evidence -- never
        fabricated as a pass -- and never blocks the FAIL-edge routing
        decision itself (best-effort, same as every other side effect in
        this file, e.g. _promote_experience_knowledge).

        Real subprocess invocation, the same convention gates.py's
        run_gate() already uses ([sys.executable, ...], capture_output=True,
        text=True, a bounded timeout). Uses `-m dv_harness.cli` (matching
        the existing `-m dv_harness.regression_reporter` convention
        regression_reporter.ensure_watcher_running() already uses, and the
        same invocation shape this project's own CLI subprocess tests use)
        rather than the `dv-harness` console-script name, so it works
        whether or not this package is pip-installed with its entry_points
        wired up. cwd is the real project root (self.root, matching
        run_gate()'s own cwd=str(root)); PYTHONPATH is EXTENDED (not
        replaced) with _ENGINE_PACKAGE_ROOT so `-m dv_harness.cli` resolves
        regardless of self.root's location or install state.
        """
        argv = [sys.executable, "-m", "dv_harness.cli",
                "--project-root", str(self.root), "lsf-watch-status"]
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(_ENGINE_PACKAGE_ROOT) + (os.pathsep + existing if existing else "")
        try:
            proc = subprocess.run(
                argv, cwd=str(self.root), capture_output=True, text=True,
                timeout=30, env=env,
            )
        except Exception as exc:  # never let a health-check failure block FAIL routing
            return {"command": argv, "ok": False, "error": str(exc)}
        try:
            parsed = json.loads((proc.stdout or "").strip() or "{}")
        except Exception:
            parsed = {"raw_stdout": (proc.stdout or "")[-500:]}
        return {
            "command": argv,
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "result": parsed,
            "stderr": (proc.stderr or "")[-500:] if proc.returncode != 0 else "",
        }

    def _record_debug_loop_round(self, failing_stage: str, target: Optional[str]) -> Dict[str, Any]:
        """Appends one real "debug_loop_history" entry (Blackboard.
        append_debug_loop_round()) every time this engine actually calls
        policy.graph_next(failing_stage, Status.FAIL.value, ...) to route a
        stage whose retries are exhausted onto its graph FAIL edge -- see
        the module-level ruling comment above REMOTE_LSF_ROUTES and
        blackboard.py's own docstring for why this is a genuinely
        different, additional signal from state.stages[stage]['attempts'].

        Called from exactly the two real call sites in this file that
        compute graph_next(..., Status.FAIL.value, ...): loop()'s
        retry-exhaustion branch, and _advance_with_fanout()'s
        parallel-branch-failure branch. Folds in the real Health Monitor
        check (_health_monitor_check() above) for a remote/LSF-route stage
        -- None for a stage whose route never submits a build/regression
        job, never a fabricated placeholder."""
        node = self.graph.nodes.get(failing_stage) if self.graph is not None else None
        health_check = (self._health_monitor_check(node)
                         if node is not None and node.route in REMOTE_LSF_ROUTES else None)
        ss = self.state.stages.get(failing_stage, {})
        entry = {
            "timestamp": now(),
            "failing_stage": failing_stage,
            "target_fail_edge": target,
            "attempt_number": ss.get("attempts", 0),
            "node_route": node.route if node is not None else None,
            "health_monitor_check": health_check,
        }
        return self.blackboard.append_debug_loop_round(entry, source=failing_stage)

    def _project_blackboard_value(self) -> Dict[str, Any]:
        """Reads the real "project" Blackboard topic (written by INTAKE's
        _bb_intake -- mode/target_name/protocols/selected_subsystems/
        required_artifacts, see that function's own docstring) and returns
        its value dict, or {} if the topic has never been written yet or was
        written with an unexpected shape (e.g. a test/caller that writes a
        partial stub directly). Shared by _protocol_router_evidence() and
        _environment_mode_router_evidence() below so both draw from the
        exact same real record."""
        payload = self.blackboard.read("project")
        value = payload.get("value") if isinstance(payload, dict) else None
        return value if isinstance(value, dict) else {}

    def _protocol_router_evidence(self, user_goal: str) -> Dict[str, Any]:
        """Real per-run evidence for protocol_router.resolve_protocol(),
        built only from genuinely available current-run sources -- see that
        module's own docstring for the full scope ruling. `active_config`
        has no real backing source anywhere in this engine today (no
        config.json/state.json field records a per-run "active build
        config") and is left explicitly None rather than invented -- a
        future stage that introduces one should populate it here, not
        fabricate a placeholder now."""
        project = self._project_blackboard_value()
        subsystem_terms = list(project.get("protocols") or []) + list(project.get("selected_subsystems") or [])
        # BUG FIX (session-snapshot-extension, 2026-09-01): this used to read
        # blackboard topic "verify", which nothing in this engine ever writes
        # -- VERIFY's own node.blackboard_write names "verification_state"
        # (see _bb_verify()/STAGE_BLACKBOARD_WRITERS above, and
        # .dv-harness/graph/main_graph.json's VERIFY node), and that write
        # already puts {simulation_passed, results, ...} directly at the
        # topic's value (not nested one level deeper under a
        # "verification_state" key). Reading the never-written "verify"
        # topic made failing_test_name below silently always None regardless
        # of real VERIFY results -- no test exercised this path end-to-end
        # (test_protocol_router.py only calls resolve_protocol() directly
        # with a synthetic evidence dict), so it went uncaught until this
        # audit. Fixed to read the topic that is actually written, with the
        # correct (non-nested) shape.
        verify = self.blackboard.read("verification_state")
        verify_value = verify.get("value") if isinstance(verify, dict) else None
        verify_value = verify_value if isinstance(verify_value, dict) else {}
        results = verify_value.get("results") or []
        failing_test_name = next(
            (r.get("testcase_id") for r in results
             if isinstance(r, dict) and r.get("result") not in (None, "PASS")),
            None,
        )
        return {
            "protocol_hint": user_goal,
            "failing_test_name": failing_test_name,
            "active_config": None,
            "modified_files": self._git_modified_files(),
            "subsystem_boundary": " ".join(str(s) for s in subsystem_terms) or None,
        }

    def _environment_mode_router_evidence(self) -> Dict[str, Any]:
        """Real per-run evidence for environment_mode_router.
        resolve_environment_mode(): requested_subsystems from the same real
        INTAKE-written "project" Blackboard topic _protocol_router_evidence()
        reads (selected_subsystems for a SYSTEM_LEVEL intake, else
        protocols), existing_registered_subsystems from the real subsystem
        registry file on disk (never fabricated -- see
        read_registered_subsystem_names()'s own docstring)."""
        project = self._project_blackboard_value()
        requested = project.get("selected_subsystems") or project.get("protocols") or []
        return {
            "requested_subsystems": list(requested),
            "existing_registered_subsystems": read_registered_subsystem_names(self.root),
        }

    def summary(self) -> str:
        # ADDITIVE fields (2026-08-28, multi-persona interaction review):
        # DV Engineer/Project Lead/DE Manager independently found `status`
        # alone never shows whether PAUSE/TAKEOVER is active or an active
        # constraint count -- a paused/taken-over session looked identical
        # to an idle one, always requiring a second `explain`/`evidence`
        # call to find out why nothing is progressing. Project Lead/DE
        # Manager/DV Manager independently found the DV-review co-sign
        # policy's on/off state is invisible wherever a "pending review"
        # count is shown, so a 0-count reads as "clean" even when it only
        # means "not enforced". Both closed here in one place rather than
        # forcing every caller (CLI/dashboard) to re-derive them.
        cp_state = ControlPlane(self.root).load()
        takeover = cp_state.get("takeover", {})
        return json.dumps({
            "project": self.state.project,
            "scope": self.state.scope,
            "current_stage": self.state.current_stage,
            "active_stages": self.state.active_stages,
            "effective_active_stages": self.state.effective_active_stages(),
            "overall_status": self.state.overall_status,
            "git_sha": self.state.git_sha,
            "server_sha": self.state.server_sha,
            "findings_total": self.state.findings_total,
            "findings_closed": self.state.findings_closed,
            "findings_open": self.state.findings_open,
            "closure_iteration": self.state.closure_iteration,
            "paused": bool(cp_state.get("paused")),
            "paused_reason": cp_state.get("paused_reason", "") if cp_state.get("paused") else "",
            "takeover_active": bool(takeover.get("active")),
            "takeover_stage": takeover.get("stage") if takeover.get("active") else None,
            "active_constraint_count": len(cp_state.get("constraints", [])),
            "dv_review_cosign_enforced": bool(self.cfg["policy"].get("require_dv_review_cosign", False)),
        }, ensure_ascii=False, indent=2)

    def set_stage(self, stage: str):
        if stage not in [s.value for s in Stage]:
            raise ValueError(f"Unknown stage: {stage}")
        self.state.current_stage = stage
        self.store.save(self.state)

    def human_redirect(self, target_stage: str, reason: str = ""):
        """REDIRECT: an explicit human decision to force the NEXT stage,
        distinct from the graph's own FAIL-edge auto-redirect in loop()
        (which is internal/automatic and never sets human_redirect). Refuses
        while TAKEOVER is active on a *different* stage than the target --
        the strongest override must not be silently overridden by a lesser
        one; release it first (or redirect to that same stage). On success,
        clears the FROM stage's blocking_reason (a human moving the pipeline
        past it is itself the resolution) and records a tagged audit event."""
        if target_stage not in [s.value for s in Stage]:
            raise ValueError(f"Unknown stage: {target_stage}")
        cp = ControlPlane(self.root)
        tk = cp.takeover_status()
        if tk.get("active") and tk.get("stage") != target_stage:
            raise RuntimeError(
                f"REDIRECT refused: TAKEOVER is active on stage {tk.get('stage')} "
                f"(since {tk.get('taken_at')}, by {tk.get('taken_by')}) -- release it "
                f"with `dv-harness release-takeover` first, or redirect to that same stage."
            )
        from_stage = self.state.current_stage
        from_ss = self.state.stages.get(from_stage)
        if from_ss is not None:
            from_ss["blocking_reason"] = ""
        self.set_stage(target_stage)
        self.store.event({
            "ts": now(), "cmd": "redirect", "human_redirect": True,
            "from_stage": from_stage, "to_stage": target_stage, "reason": reason,
        })
        return target_stage

    def _promote_experience_knowledge(self, stage: str, evidence_blocks: dict) -> None:
        """Closed-loop wiring (2026-08-28, w4qxjh0iq design + adversarial
        verify): a PASS verdict on a stage whose STAGE_GATES include
        experience_knowledge_gate means that gate script already confirmed
        expert_approved=True plus real evidence/applicability_constraints
        (subprocess, unchanged -- gate scripts stay argparse/json/pathlib/sys
        only). That is genuinely-verified, reusable engineering knowledge --
        persist it here, in-process, since engine.py (unlike the gate
        script) may import dv_harness.memory_router. Takes the SAME
        evidence_blocks dict run_stage() already computed via
        extract_evidence_blocks(result.text) -- does not re-parse the text a
        second time (must-fix #1 from adversarial verify)."""
        gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
        if "experience_knowledge_gate" not in gate_ids:
            return
        block = evidence_blocks.get("experience_knowledge_gate")
        if not isinstance(block, dict):
            return
        block = dict(block)  # local copy; never mutate the parsed evidence
        # Tier 5 (DV-review co-sign) wraps judged fields as
        # {"value":...,"reviewer_id":...,"reviewer_confidence":...} only when
        # policy.require_dv_review_cosign is on -- gates.run_gate() only
        # unwraps under that same condition, so mirror it exactly here
        # (must-fix #2 from adversarial verify) rather than unwrapping
        # unconditionally, which would silently truncate a legitimate
        # freeform evidence object that happens to contain a "value" key.
        if self.cfg["policy"].get("require_dv_review_cosign", False):
            for f in JUDGMENT_FIELDS.get("experience_knowledge_gate", []):
                if isinstance(f, str) and isinstance(block.get(f), dict) and "value" in block[f]:
                    block[f] = block[f]["value"]
        kind = block.get("kind")
        if kind not in ("root_cause", "verified_fix", "debug_lesson"):
            # Default fit for this gate's actual schema: it captures "what
            # this class of problem looks like / why / when it applies", not
            # a single closed finding's fix -- a debug lesson, not a
            # verified_fix. All three kinds route to the same
            # ENGINEERING_MEMORY destination in route_memory(), so getting
            # this wrong only affects the descriptive tag, never storage
            # location.
            kind = "debug_lesson"
        record = {
            "kind": kind,
            "verified": True,  # gate already required expert_approved==True
            "title": block.get("title"),
            "pattern": block.get("pattern"),
            "root_cause": block.get("root_cause"),
            "evidence": block.get("evidence"),
            "applicability_constraints": block.get("applicability_constraints"),
            "confidence": "HIGH",  # reserve CONFIRMED for
                                   # MemoryConsolidator.from_closed_finding's
                                   # stricter single_sim+regression+reaudit bar
            "source_knowledge_id": block.get("knowledge_id"),
            "protocol": block.get("protocol"),
        }
        # Deliberately do NOT set record["memory_id"] from knowledge_id:
        # MemoryStore.add() uses it verbatim as a filename component with no
        # path-traversal sanitization -- passing agent-influenced text there
        # would be a new injection surface. Accepted tradeoff: a stage
        # retried after a PARTIAL elsewhere can promote the same
        # knowledge_id twice as two memory_ids.
        try:
            promotion = route_and_store(self.root, record, cfg=self.cfg)
        except Exception as exc:
            promotion = {"destination": "PROMOTION_FAILED", "error": str(exc)}
        self.store.event({
            "ts": now(), "stage": stage, "event": "EXPERIENCE_KNOWLEDGE_PROMOTED",
            "record_kind": kind, "promotion": promotion,
        })

    def _persist_subsystem_registry_entry(self, stage: str, evidence_blocks: dict) -> None:
        """Closed-loop wiring (2026-08-28, plan-subsystem-registry design
        pass): a PASS verdict on SIGNOFF whose STAGE_GATES include
        subsystem_environment_registration_gate means that gate script
        already validated the entry's required fields, qualification_state
        enum membership, and interface/clock-reset compatibility -- persist
        it here into the REAL runtime registry file
        (.dv-harness/soc-composer/subsystem_environment_registry.json,
        deliberately separate from the empty
        subsystem_environment_registry_template.json example). Same pattern
        as _promote_experience_knowledge: reads the SAME evidence_blocks
        dict run_stage() already computed, never re-parses agent text, and a
        persistence failure never downgrades an already-earned SIGNOFF PASS.

        Insert-or-replace-by-name (not append-only): a later SIGNOFF for the
        same subsystem name supersedes an earlier registration outright --
        the registry always reflects the most recently signed-off state for
        each name, matching how a single subsystem's environment evolves
        across projects/re-signoffs. The gate's own validation is what
        proves this entry PASSED before we ever get here; this method does
        not re-validate, only persists."""
        gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
        if "subsystem_environment_registration_gate" not in gate_ids:
            return
        block = evidence_blocks.get("subsystem_environment_registration_gate")
        if not isinstance(block, dict) or block.get("registration_applicable") is False:
            return  # SKIPPED_NOT_APPLICABLE case, or no block at all -- nothing to persist
        path = self.root / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json"
        try:
            registry = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"subsystems": []}
        except (json.JSONDecodeError, OSError):
            registry = {"subsystems": []}
        entry = dict(block)
        entry.pop("registration_applicable", None)
        entry.pop("registration_not_applicable_reason", None)
        entry["registered_at"] = now()
        entry["registered_from_git_sha"] = self.state.git_sha
        subs = [s for s in registry.get("subsystems", []) if s.get("name") != entry.get("name")]
        subs.append(entry)
        registry["subsystems"] = subs
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self.store.event({"ts": now(), "stage": stage, "event": "SUBSYSTEM_REGISTRY_WRITE_FAILED",
                               "name": entry.get("name"), "error": str(exc)})
            return
        self.blackboard.write("subsystem_registry", {"entry": entry}, source=stage)
        self.store.event({"ts": now(), "stage": stage, "event": "SUBSYSTEM_ENVIRONMENT_REGISTERED",
                           "name": entry.get("name"), "qualification_state": entry.get("qualification_state")})

    def _compose_soc_environment_files(self, stage: str, evidence_blocks: dict) -> None:
        """Real call site for
        dv_harness/uvm_generator/soc_environment_composer.compose_soc_environment()
        (2026-09-01, SYSTEM_LEVEL_MODE composer-implementation task -- closes
        the "zero generator code behind SYSTEM_LEVEL_MODE" gap the
        protocol-genericity audit found: WORKFLOW_MANIFEST.json's
        system_level_scoreboard_composer/coverage_composer claims were
        unbacked string literals, and generator.py had zero occurrences of
        system_level/soc_tb_top/cross_subsystem before this).

        SYSTEM_LEVEL stage's own `system_level_validator` gate
        (tools/real_env/system_level_validator.py, wired in gates.py's
        STAGE_GATES["SYSTEM_LEVEL"]) is a MULTI-flag gate
        (EvidenceFlag("--registry","registry") + a harness-supplied
        ContextFlag("--registered", ...)) -- the agent's raw evidence block
        for it is therefore {"registry": {"subsystems": [...]}} (see
        gates.py's _materialize_flag: an EvidenceFlag's CLI value is
        `payload[spec.key]`, so the ONE ```dv-harness-evidence:
        system_level_validator``` fence body is a dict-of-sub-payloads keyed
        "registry"). That "registry" sub-payload's "subsystems" list is
        exactly this module's `subsystem_registry_entries` shape (same
        name/environment_manifest/release_sha/qualification_state/
        interface_compatibility/clock_reset_compatibility fields
        subsystem_environment_registration_gate.py itself validates
        per-entry). system_level_validator.py only ever reads
        d.get("subsystems")/d.get("system_level_applicable") and silently
        ignores any other key, so an agent may additionally carry
        soc_composition_manifest_template.json's own richer top-level keys
        (soc_name/shared_clocks/shared_resets/cross_subsystem_scenarios/...)
        in that SAME "registry" dict without the gate script rejecting it --
        this method therefore reuses the "registry" dict itself as BOTH
        subsystem_registry_entries's source AND compose_soc_environment's
        `manifest` argument, rather than inventing a second fence/schema.

        Same defensive pattern as _persist_subsystem_registry_entry
        immediately above: reads the SAME evidence_blocks dict run_stage()
        already computed, never re-parses agent text; a composition failure
        (including the deliberately-unimplemented
        cross_subsystem_scenarios/end_to_end_scoreboard/system_coverage
        stubs -- see soc_environment_composer.py's module docstring) is
        logged and skipped, never downgrades an already-earned SYSTEM_LEVEL
        stage PASS."""
        gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
        if "system_level_validator" not in gate_ids:
            return
        block = evidence_blocks.get("system_level_validator")
        if not isinstance(block, dict):
            return
        registry = block.get("registry")
        if not isinstance(registry, dict) or registry.get("system_level_applicable") is False:
            return  # escape hatch, or no registry sub-payload at all -- nothing to compose
        subsystems = registry.get("subsystems") or []
        if not subsystems:
            return
        try:
            files = compose_soc_environment(subsystems, registry)
        except NotImplementedError as exc:
            self.store.event({"ts": now(), "stage": stage, "event": "SOC_COMPOSITION_NOT_IMPLEMENTED",
                               "error": str(exc)})
            return
        except (EmptySubsystemRegistryError, MissingSubsystemNameEvidenceError) as exc:
            self.store.event({"ts": now(), "stage": stage, "event": "SOC_COMPOSITION_INPUT_INVALID",
                               "reason": getattr(exc, "reason", str(exc)),
                               "detail": getattr(exc, "detail", {})})
            return
        soc_name = sv_id(registry.get("soc_name") or "soc")
        out_dir = self.root / "generated" / "soc_composition" / soc_name
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            for name, content in files.items():
                (out_dir / name).write_text(content, encoding="utf-8")
        except OSError as exc:
            self.store.event({"ts": now(), "stage": stage, "event": "SOC_COMPOSITION_WRITE_FAILED",
                               "error": str(exc)})
            return
        self.blackboard.write("soc_composition",
                               {"soc_name": soc_name, "generated_files": sorted(files.keys())}, source=stage)
        self.store.event({"ts": now(), "stage": stage, "event": "SOC_ENVIRONMENT_COMPOSED",
                           "soc_name": soc_name, "files": sorted(files.keys())})

    # Real evidence categories root_cause_evidence_gate.py itself structurally
    # requires (see tools/verification_flow/root_cause_evidence_gate.py's own
    # `required` list) -- the subset actually usable as identify_gap()'s
    # required/supplied vocabulary (symptom/root_cause/confidence are always
    # present by construction on a PASS verdict, so they carry no gap signal;
    # these four are the ones whose presence/non-emptiness genuinely varies).
    ROOT_CAUSE_EVIDENCE_CATEGORIES = [
        "first_bad_event", "causal_chain", "supporting_evidence", "counter_evidence",
    ]

    def _score_root_cause_confidence(self, stage: str, evidence_blocks: dict,
                                      verdict: str = "PASS") -> None:
        """Wires dv_harness/inference.py's score_confidence/identify_gap/
        next_best_action/promote_if_high_confidence into the ONE real stage
        that produces a root-cause hypothesis with cited supporting/counter
        evidence: RE_AUDIT's root_cause_evidence_gate (inference.py itself had
        zero callers before this -- confirmed by the 2026-08-28 architecture
        audit). Only runs on an actual gate-verified PASS (mirrors
        _promote_experience_knowledge/_persist_subsystem_registry_entry
        exactly) -- best-effort side effect, never downgrades an already-
        earned stage PASS.

        `verdict` (qualified-conclusion-implementation task, 2026-09-01):
        the SAME per-stage gate verdict string run_stage() already computed
        via evaluate_stage_evidence_with_detail() before calling this method
        -- defaults to "PASS" because that is the only verdict value the one
        real call site below ever calls this with today (see the
        `if verdict == "PASS":` guard around that call site), but is taken
        as an explicit parameter rather than hardcoded so this method stays
        correct if a future caller ever invokes it from a different verdict
        context. Passed straight through to build_qualified_conclusion() --
        see that function's own docstring for why GATE_FAIL must disqualify
        a conclusion regardless of confidence.

        Per CLAUDE.md's 'Any current root cause must be revalidated with
        current evidence': the agent's own self-reported `confidence` field
        in the evidence block is NEVER trusted directly here -- it is
        independently recomputed from real counts pulled out of the SAME
        evidence block the gate script already validated:
          - independent_sources_count: real citation count in the selected
            root_cause's own `supporting_evidence` (list/dict length, or 1/0
            for a bare truthy/falsy scalar).
          - evidence_refs_verified: real bool -- first_bad_event AND
            causal_chain AND supporting_evidence are all genuinely non-empty
            in this exact block (not assumed just because the gate passed).
          - counter_evidence_count: real citation count in the selected
            root_cause's own `counter_evidence` (same counting rule).
          - multi_agent_consensus_count: this harness runs ONE agent per
            stage attempt (no concurrent multi-agent branch exists for
            RE_AUDIT, unlike e.g. the ANALYSIS_G1 fan-out) -- the real,
            structurally-guaranteed independent-corroboration signal
            available here is root_cause_evidence_gate.py's own
            NO_ALTERNATIVE_HYPOTHESIS_REFUTED requirement: how many OTHER
            candidate hypotheses in the agent's `hypotheses` array were
            independently evaluated and carry their own recorded
            counter_evidence ruling them out. Each is a genuinely distinct,
            gate-verified line of reasoning that converged on the same
            selected root_cause by elimination -- a real count from real
            data, not a fabricated stand-in for concurrent agents.

        identify_gap() then reports which of ROOT_CAUSE_EVIDENCE_CATEGORIES
        the selected root_cause is still missing (e.g. a MEDIUM-confidence
        finding may legitimately omit counter_evidence, which HIGH/CONFIRMED
        may not per the gate's own high_tier check) and next_best_action()
        cross-references the real protocol_builder_registry.json for a
        concrete next step per gap -- reusing block['protocol'] when the
        agent supplied one (same optional field experience_knowledge_gate's
        block already carries, see _promote_experience_knowledge above).

        promote_if_high_confidence() only ever fires on the INDEPENDENTLY
        recomputed level, never on the agent's own self-reported one -- a
        finding the agent called HIGH but that recomputes to MEDIUM/LOW here
        (e.g. too few real citations) is never pushed to the shared
        Knowledge Center."""
        gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
        if "root_cause_evidence_gate" not in gate_ids:
            return
        block = evidence_blocks.get("root_cause_evidence_gate")
        if not isinstance(block, dict):
            return

        def _cite_count(v):
            if isinstance(v, list):
                return len(v)
            if isinstance(v, dict):
                return len(v)
            return 1 if v else 0

        independent_sources_count = _cite_count(block.get("supporting_evidence"))
        counter_evidence_count = _cite_count(block.get("counter_evidence"))
        evidence_refs_verified = bool(
            block.get("first_bad_event") and block.get("causal_chain") and block.get("supporting_evidence")
        )

        hyps = block.get("hypotheses")
        multi_agent_consensus_count = 0
        if isinstance(hyps, list):
            selected_claim = block.get("root_cause")
            multi_agent_consensus_count = sum(
                1 for h in hyps
                if isinstance(h, dict) and h.get("claim") != selected_claim and h.get("counter_evidence")
            )

        confidence_result = score_confidence(
            independent_sources_count=independent_sources_count,
            evidence_refs_verified=evidence_refs_verified,
            counter_evidence_count=counter_evidence_count,
            multi_agent_consensus_count=multi_agent_consensus_count,
        )

        supplied = [c for c in self.ROOT_CAUSE_EVIDENCE_CATEGORIES if block.get(c)]
        gap = identify_gap(self.ROOT_CAUSE_EVIDENCE_CATEGORIES, supplied)
        protocol = block.get("protocol") or "_general"
        next_actions = next_best_action(protocol, gap, self.root) if gap else []

        promotion = None
        if confidence_result["level"] == "HIGH":
            finding = {
                "root_cause": block.get("root_cause"),
                "symptom": block.get("symptom"),
                "supporting_evidence": block.get("supporting_evidence"),
                "counter_evidence": block.get("counter_evidence"),
                "confidence_result": confidence_result,
            }
            try:
                kc_client = KnowledgeCenterClient(self.cfg, self.root)
                promotion = promote_if_high_confidence(kc_client, "root_cause", protocol, finding, confidence_result)
            except Exception as exc:  # best-effort, must never break an already-earned PASS
                promotion = {"promoted": False, "reason": "PROMOTION_EXCEPTION", "error": str(exc)}

        self.blackboard.write("root_cause_confidence", {
            "stage": stage,
            "recomputed_confidence": confidence_result,
            "agent_reported_confidence": block.get("confidence"),
            "gap": gap,
            "next_best_action": next_actions,
            "promotion": promotion,
        }, source=stage)
        self.store.event({
            "ts": now(), "stage": stage, "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
            "recomputed_confidence": confidence_result,
            "agent_reported_confidence": block.get("confidence"),
            "gap": gap, "next_best_action": next_actions, "promotion": promotion,
        })

        # Qualified Conclusion (qualified-conclusion-implementation task,
        # 2026-09-01): composes the gate verdict this method was called with
        # and the confidence_result just computed above -- both already-real
        # facts -- into the one first-class QualifiedConclusion object this
        # harness previously had no type for at all (see
        # dv_harness/qualified_conclusion.py's module docstring). Persisted
        # to its own "qualified_conclusion" Blackboard topic so
        # dv_harness/dashboard.py can render it distinctly from the
        # "root_cause_confidence" topic above (that topic is the raw
        # confidence-scoring record; this one is the composed is_qualified
        # verdict a consumer should actually gate trust on). Best-effort,
        # same as every other side effect in this method -- a persistence
        # failure must never downgrade an already-earned stage PASS.
        try:
            qc = build_qualified_conclusion(verdict, confidence_result, block)
            self.blackboard.write("qualified_conclusion", qc.as_dict(), source=stage)
            self.store.event({
                "ts": now(), "stage": stage, "event": "QUALIFIED_CONCLUSION_BUILT",
                "gate_verdict": qc.gate_verdict,
                "inference_confidence": qc.inference_confidence,
                "is_qualified": qc.is_qualified,
            })
        except (ValueError, TypeError) as exc:  # best-effort, mirrors the
            # promotion try/except above -- a malformed input here must
            # never break an already-earned stage PASS.
            self.store.event({"ts": now(), "stage": stage, "event": "QUALIFIED_CONCLUSION_BUILD_FAILED",
                               "error": str(exc)})

    def _append_coverage_history_sample(self, stage: str, evidence_blocks: dict) -> None:
        """Closed-loop wiring (Task 6, 2026-08-31 poster-gap-closing round 2):
        dashboard.append_coverage_history_sample() was real, tested
        rendering/storage logic whose own docstring admitted "not currently
        called by any engine stage yet" -- nothing in a real stage run
        produced the multi-timestamp history the coverage-trend chart
        (compute_coverage_trend()/render_coverage_trend_svg()) needs. Same
        pattern as _promote_experience_knowledge/_persist_subsystem_registry_entry/
        _score_root_cause_confidence: reads the SAME evidence_blocks dict
        run_stage() already computed, only fires on an actual gate-verified
        PASS whose STAGE_GATES include the one COVERAGE_CLOSURE gate that
        reports a real coverage percent -- coverage_signoff_verdict_gate.py's
        own `coverage_credit_percent` field (see gates.py's STAGE_GATES
        mapping and the gate script's own signoff_requested/coverage_credit_percent
        check) -- never a placeholder, and a persistence failure never
        downgrades an already-earned stage PASS.

        Local import (not a module-level one) because dashboard.py itself
        does lazy `from .engine import DVHarness` imports inside its own
        functions (e.g. its background-run worker and control-plane
        dispatcher) precisely to keep this engine<->dashboard boundary from
        ever becoming a real circular import -- mirroring that existing
        precedent here rather than adding a fresh module-level coupling."""
        gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
        if "coverage_signoff_verdict_gate" not in gate_ids:
            return
        block = evidence_blocks.get("coverage_signoff_verdict_gate")
        if not isinstance(block, dict):
            return
        percent = block.get("coverage_credit_percent")
        if not isinstance(percent, (int, float)) or isinstance(percent, bool):
            return
        from . import dashboard
        try:
            dashboard.append_coverage_history_sample(self.root, float(percent))
        except Exception as exc:  # best-effort, must never break an already-earned PASS
            self.store.event({"ts": now(), "stage": stage, "event": "COVERAGE_HISTORY_WRITE_FAILED",
                               "percent": percent, "error": str(exc)})
            return
        self.store.event({"ts": now(), "stage": stage, "event": "COVERAGE_HISTORY_SAMPLE_APPENDED",
                           "percent": percent})

    def _promote_project_topology_knowledge(self, stage: str, evidence_blocks: dict) -> None:
        """Closed-loop wiring (Task 9, 2026-08-31 poster-gap-closing round 2):
        a PASS verdict on PROJECT_MODEL's project_model_topology_completeness_gate
        means that gate script (tools/verification_flow/project_model_topology_
        completeness_gate.py) already structurally verified a complete
        verification-boundary/VIP-topology/block-classification model (real
        subprocess-verified evidence, not a placeholder) -- persist that
        model as a Project-tier memory record so a later run_stage() call
        (see the MemoryRetriever.search() read wired into run_stage() below)
        can retrieve this project's own topology facts instead of
        re-discovering them from scratch every stage. Same pattern as
        _promote_experience_knowledge: reads the SAME evidence_blocks dict
        run_stage() already computed via extract_evidence_blocks(result.text),
        does not re-parse the text a second time, only fires on an actual
        gate-verified PASS, and a persistence failure never downgrades an
        already-earned stage PASS."""
        gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
        if "project_model_topology_completeness_gate" not in gate_ids:
            return
        block = evidence_blocks.get("project_model_topology_completeness_gate")
        if not isinstance(block, dict):
            return
        record = {
            "kind": "project_topology",
            "verified": True,  # gate already required topology completeness
            "title": f"Project verification-boundary/topology model ({block.get('dv_readiness')})",
            "scope": "project",
            "verification_boundary": block.get("verification_boundary"),
            "vip_topology": block.get("vip_topology"),
            "blocks": block.get("blocks"),
            "model_confidence": block.get("model_confidence"),
            "confidence_basis": block.get("confidence_basis"),
            "dv_readiness": block.get("dv_readiness"),
            "dv_readiness_basis": block.get("dv_readiness_basis"),
            "architecture_evidence_db_ref": block.get("architecture_evidence_db_ref"),
        }
        try:
            promotion = route_and_store(self.root, record, cfg=self.cfg)
        except Exception as exc:
            promotion = {"destination": "PROMOTION_FAILED", "error": str(exc)}
        self.store.event({
            "ts": now(), "stage": stage, "event": "PROJECT_TOPOLOGY_PROMOTED",
            "promotion": promotion,
        })

    def _promote_vplan_summary_knowledge(self, stage: str, evidence_blocks: dict) -> None:
        """Closed-loop wiring (memory-engine-schema-completion audit,
        2026-09-01): the audit found Project Memory populated by exactly ONE
        gate (_promote_project_topology_knowledge above, keyed on
        project_model_topology_completeness_gate) -- vPlan content itself
        (feature areas, req_ids, item count) was never separately captured
        as project-tier memory, even though STAGE_GATES["VPLAN"]'s
        vplan_writer_validation_gate (gates.py, added in the
        vplan-doc-and-wiring-fix session) already requires and validates a
        real vPlan item list (req_id/feature_area/pattern_name/task_name/
        suite/... per dv_harness.vplan_writer.VPlanItem) against real
        on-disk pattern-dir/dispatcher-file/task-declaration evidence before
        it can PASS -- see tools/vplan/vplan_writer_validation_gate.py.

        A PASS verdict on the VPLAN stage therefore means
        evidence_blocks["vplan_writer_validation_gate"] (the SAME
        agent-supplied payload run_gate() already fed to that gate script --
        read here without re-parsing agent text a second time, same pattern
        as every other _promote_* method in this class) genuinely holds a
        gate-validated vPlan item list. This summarizes and persists it as
        Project-tier memory (kind="project_fact", the same kind
        _promote_project_topology_knowledge could have used but didn't need
        to, since "project_topology" already existed for its case) so a
        later stage's MemoryRetriever.search() read (see run_stage() below)
        can retrieve this project's own vPlan facts instead of never having
        them available at all. Same best-effort/never-downgrade-an-earned-
        PASS discipline as every sibling method here."""
        gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
        if "vplan_writer_validation_gate" not in gate_ids:
            return
        block = evidence_blocks.get("vplan_writer_validation_gate")
        if not isinstance(block, dict):
            return
        items = block.get("items")
        if not isinstance(items, list) or not items:
            return
        feature_areas = sorted({
            i.get("feature_area") for i in items if isinstance(i, dict) and i.get("feature_area")
        })
        req_ids = sorted({
            i.get("req_id") for i in items if isinstance(i, dict) and i.get("req_id")
        })
        suites = sorted({
            i.get("suite") for i in items if isinstance(i, dict) and i.get("suite")
        })
        record = {
            "kind": "project_fact",
            "verified": True,  # vplan_writer_validation_gate already validated every item
                                # against real pattern-dir/dispatcher-file/task-declaration evidence
            "title": f"vPlan finalized: {len(items)} item(s) across {len(feature_areas)} feature area(s)",
            "scope": "project",
            "vplan_item_count": len(items),
            "vplan_feature_areas": feature_areas,
            "vplan_req_ids": req_ids,
            "vplan_suites": suites,
            "vplan_pattern_dir": block.get("pattern_dir"),
            "vplan_dispatcher_file": block.get("dispatcher_file"),
        }
        try:
            promotion = route_and_store(self.root, record, cfg=self.cfg)
        except Exception as exc:
            promotion = {"destination": "PROMOTION_FAILED", "error": str(exc)}
        self.store.event({
            "ts": now(), "stage": stage, "event": "VPLAN_SUMMARY_PROMOTED",
            "promotion": promotion,
        })

    def _sync_findings_state(self) -> None:
        """The blackboard "findings" topic (Blackboard.findings_counts()) is
        the one real source of truth for finding counts -- this recomputes
        state.findings_total/open/closed from it and persists, so the two
        can never disagree. Called on every DVHarness load (__init__) and
        after every write to the "findings" topic below; never assigned any
        other way."""
        counts = self.blackboard.findings_counts()
        self.state.findings_total = counts["total"]
        self.state.findings_open = counts["open"]
        self.state.findings_closed = counts["closed"]
        self.store.save(self.state)

    def record_finding(self, finding_id: str, title: str = "", meta: Optional[dict] = None,
                        source: str = "engine") -> None:
        """Opens (or reopens) one finding in the blackboard registry and
        syncs state.findings_* from it -- the only way a finding is ever
        added; there is no separate state-side write path any more."""
        self.blackboard.upsert_finding(finding_id, "open", dict(meta or {}, title=title), source=source)
        self._sync_findings_state()

    def close_finding(self, finding_id: str, resolution: str = "", source: str = "engine") -> None:
        """Closes one finding in the blackboard registry and syncs
        state.findings_* from it -- policy.py's require_all_actionable_
        findings_closed reads state.findings_open, which this keeps in
        lockstep with the blackboard registry it is actually derived from."""
        self.blackboard.upsert_finding(finding_id, "closed", {"resolution": resolution}, source=source)
        self._sync_findings_state()

    def _sync_project_from_blackboard(self) -> None:
        """state.project is a read-only derived view of blackboard
        "project".target_name (INTAKE's identity record) -- see the
        reconciliation note above the STAGE_BLACKBOARD_WRITERS group for why
        "project_model" stays a separate topic rather than folding in here."""
        payload = self.blackboard.read("project")
        value = payload.get("value") if isinstance(payload, dict) else None
        target_name = value.get("target_name") if isinstance(value, dict) else None
        if target_name:
            self.state.project = target_name
            self.store.save(self.state)

    def _sync_dut_tb_version_from_blackboard(self) -> None:
        """state.dut_version/state.tb_version (models.py) are read-only
        derived views of the blackboard "verification_state" topic's
        results[] -- see models.py's HarnessState.dut_version docstring for
        the full ruling. VERIFY's test_result_provenance_gate REQUIRES
        rtl_revision/tb_revision to be non-empty on every result it accepts
        (tools/verification_flow/test_result_provenance_gate.py's REQ list),
        so any results[] this reads is already gate-validated, real evidence
        -- this function never invents a value itself. Takes the LAST
        (most recently reported) result and only overwrites a field when
        that result actually carries a non-empty value for it, mirroring
        _sync_project_from_blackboard()'s own "never blank out a known
        value with an unknown one" behavior above."""
        payload = self.blackboard.read("verification_state")
        value = payload.get("value") if isinstance(payload, dict) else None
        results = value.get("results") if isinstance(value, dict) else None
        if not isinstance(results, list) or not results:
            return
        last = results[-1]
        if not isinstance(last, dict):
            return
        changed = False
        rtl_revision = last.get("rtl_revision")
        if rtl_revision:
            self.state.dut_version = rtl_revision
            changed = True
        tb_revision = last.get("tb_revision")
        if tb_revision:
            self.state.tb_version = tb_revision
            changed = True
        if changed:
            self.store.save(self.state)

    def _write_blackboard_from_evidence(self, node, stage: str, evidence: dict, result) -> None:
        writer = STAGE_BLACKBOARD_WRITERS.get(stage)
        values = writer(evidence, stage, result) if writer else _bb_generic_fallback(node, evidence, stage, result)
        for topic in node.blackboard_write:
            value = values.get(topic, {"evidence": evidence, "summary": (result.text or "")[:2000]})
            if topic == "findings":
                # Never let this stage's narrative blob overwrite the real
                # items registry (Blackboard.upsert_finding's callers) --
                # merge it in as contextual last_report only, then re-derive
                # state.findings_* from the (unclobbered) registry.
                registry = self.blackboard.read_findings()
                registry["last_report"] = dict(value, stage=stage)
                self.blackboard.write(topic, registry, source=stage)
                self._sync_findings_state()
            else:
                self.blackboard.write(topic, value, source=stage)
        if "project" in node.blackboard_write:
            self._sync_project_from_blackboard()
        if "verification_state" in node.blackboard_write:
            self._sync_dut_tb_version_from_blackboard()

    def run_stage(self, user_goal: str, stage: Optional[str] = None):
        stage = stage or self.state.current_stage

        # Human Override, strongest form: TAKEOVER must be honored even when
        # run_stage() is called directly (CLI `run-stage`, bypassing loop()'s
        # own check below) -- no adapter/LLM call happens at all while a
        # human holds ANY stage, regardless of how misconfigured anything
        # else is. Checked before any state mutation (attempts/status/etc.).
        #
        # BUG FIX (2026-08-28, wq5whmpdv adversarial verify): this previously
        # also required tk.get("stage") == stage. Since the harness only ever
        # tracks one current_stage at a time (no real parallel-stage
        # execution), that exact-name match made TAKEOVER a silent no-op the
        # moment current_stage moved past the name it was issued against --
        # a human takes over stage X while reading a status that's since
        # advanced to Y, and the "strongest override" (CLAUDE.md: "Human
        # Override is always valid") enforces nothing. Any active takeover
        # now halts every stage until released, matching an e-stop, not a
        # per-stage lock. `tk["stage"]`/`tk["message"]` are kept and reported
        # below purely as informational context (which stage the human meant
        # to drive), not as part of the blocking condition.
        cp = ControlPlane(self.root)
        cp_state = cp.load()
        tk = cp_state.get("takeover", {})
        if tk.get("active"):
            return AgentResult(
                ok=False,
                text=(f"BLOCKED_BY_TAKEOVER: stage {stage} is under human takeover "
                      f"(taken on stage {tk.get('stage')}, since {tk.get('taken_at')}, "
                      f"by {tk.get('taken_by')}): {tk.get('message', '')}. "
                      f"Run `dv-harness release-takeover` to return control to the harness."),
                raw={"blocked_by": "takeover", "stage": stage, "takeover_stage": tk.get("stage")},
                session_id=None,
            )

        ss = self.state.stages[stage]
        ss["status"] = Status.RUNNING.value
        ss["attempts"] += 1
        ss["started_at"] = now()
        self.state.overall_status = Status.RUNNING.value
        self.state.git_sha = self._git_sha() or self.state.git_sha
        self.store.save(self.state)

        # ---- 1. Plan-and-Execute + Blackboard read + Multi-Agent delegate,
        #         all BEFORE the LLM call, so the agent's response is
        #         genuinely informed by an explicit plan/route/prior-state
        #         instead of the plan being write-only metadata. A plan
        #         already in flight for this node (an earlier attempt of the
        #         same stage) is reused rather than creating a fresh
        #         plan_id every retry -- control_plane._find_latest_plan is
        #         the same lookup replan_stage() already uses below and in
        #         loop(), so a stage's plan history stays one coherent
        #         PLAN-XXXXXXXX.json with an incrementing revision, not N
        #         unrelated plans for N attempts. ------------------------
        node = self.graph.nodes.get(stage) if self.graph else None
        route_info: Optional[dict] = None
        plan: Optional[dict] = None
        bb_snapshot: Dict[str, Any] = {}
        agent_profile = None
        plan_section = ""
        if node is not None:
            route_info = self.router.resolve(node)
            resolved_skills = self.skills.resolve(node.skills)
            # --- Real, input-driven protocol/environment-mode resolution --
            # (2026-09-01, route-skill-resolver-dynamic-implementation task):
            # unlike self.router.resolve(node) above (a static per-node dict
            # lookup, see router.py's own NOTICE), these two calls genuinely
            # depend on THIS run's own evidence (user_goal text, blackboard
            # "project"/"verification_state" topics, real git diff, real subsystem
            # registry) and can pick a different real decision run-to-run.
            # Folded into route_info (and therefore into _build_plan_section's
            # prompt text below) so this is load-bearing, not a disconnected
            # module -- see protocol_router.py/environment_mode_router.py for
            # the full ruling on evidence sourcing.
            route_info["protocol_decision"] = resolve_protocol(self._protocol_router_evidence(user_goal))
            route_info["environment_mode_decision"] = resolve_environment_mode(
                self._environment_mode_router_evidence())
            plan = _find_latest_plan(self.plans.dir, stage)
            if plan is None:
                plan = self.plans.create(stage, f"{user_goal} :: stage={stage}", default_plan(node))
            task = self.agents.delegate(node, plan)
            bb_snapshot = self.blackboard.snapshot(node.blackboard_read) if node.blackboard_read else {}
            agent_profile = load_agent_profile(self.root, route_info["agent"])
            plan_section = _build_plan_section(route_info, resolved_skills, plan, bb_snapshot, task)

        # ---- 1b. Memory-tier read (Task 9, 2026-08-31 poster-gap-closing
        #          round 2): MemoryRetriever.search() had zero callers
        #          anywhere in the real engine flow before this -- every
        #          stage's prompt was informed by the Blackboard snapshot
        #          above (this run's OWN current-run state) but never by
        #          Memory (prior knowledge from past runs/stages, per
        #          CLAUDE.md's "Memory is prior knowledge, not current
        #          evidence"). Best-effort and a true no-op when nothing is
        #          relevant: an empty/failed search yields relevant_memory=[]
        #          (falsy), and build_stage_prompt's own additive-kwargs
        #          contract guarantees a falsy relevant_memory reproduces the
        #          exact prompt as if this kwarg were never threaded in at
        #          all (see prompts.build_stage_prompt's docstring). -------
        relevant_memory: List[Dict[str, Any]] = []
        try:
            from .memory import MemoryStore, MemoryRetriever
            memory_hits = MemoryRetriever(MemoryStore(self.root)).search({"text": f"{stage} {user_goal}"})
            relevant_memory = [hit["memory"] for hit in memory_hits]
        except Exception:
            relevant_memory = []

        profile = self.profiler.begin_stage(stage, stage, graph_node=stage, metadata={"git_sha": self.state.git_sha})
        # CONSTRAINT / CORRECT / APPROVE integration: fold the persisted
        # control-plane state into this stage's prompt (prompts.build_stage_prompt
        # is purely additive on these kwargs -- omitting them reproduces the
        # pre-control-plane prompt exactly).
        constraints = [c["text"] for c in cp_state.get("constraints", [])]
        correction = cp_state.get("corrections", {}).get(stage)
        correction_note = correction["note"] if correction and not correction.get("consumed") else None
        approval = cp_state.get("approvals", {}).get(stage)
        prompt = build_stage_prompt(stage, self.summary(), user_goal,
                                     constraints=constraints,
                                     correction_note=correction_note,
                                     human_approval=approval,
                                     relevant_memory=relevant_memory or None)
        if plan_section:
            prompt = prompt + plan_section
        resume = ss.get("session_id") or None
        _t0 = time.perf_counter()

        # ---- 2. Multi-Agent dispatch: the resolved agent is threaded all
        #         the way into the adapter call, not just appended as a
        #         string in the prompt. See adapters/cli.py's NOTICE for the
        #         exact --agent/--allowedTools/--disallowedTools mechanism
        #         and its honestly-documented limitation. ------------------
        result = self.adapter.run(prompt=prompt, cwd=str(self.root), resume_session=resume,
                                   agent_profile=agent_profile)
        _agent_runtime = time.perf_counter() - _t0
        _usage = extract_provider_usage(result.raw or {})
        _model = ((result.raw or {}).get("response") or {}).get("model", "")
        self.profiler.add_agent_run(profile["profile_id"], "stage-agent", _agent_runtime,
            usage=_usage, model=str(_model),
            status=("PASS" if result.ok else "FAIL"))

        if result.session_id:
            ss["session_id"] = result.session_id
            self.state.last_session_id = result.session_id
        ss["last_message"] = result.text[-6000:] if result.text else ""
        ss["finished_at"] = now()

        evidence_blocks: Dict[str, Any] = {}
        if result.ok:
            # Transport success (the Claude subprocess call returning ok) is
            # NOT the same as DV PASS -- same principle as "LSF DONE != DV
            # PASS" one level up. For stages with a mapped gate in
            # gates.STAGE_GATES, promotion to PASS additionally requires the
            # agent's own response to carry a machine-checkable evidence
            # block that the corresponding tools/verification_flow/*.py gate
            # accepts. Stages with no mapped gate keep the prior behavior.
            gate_require = self.cfg["policy"].get("require_stage_gate_evidence", True)
            if gate_require:
                # evaluate_stage_evidence_with_detail() is the SAME
                # run_gate() loop evaluate_stage_evidence() uses (factored
                # through gates._evaluate_stage_evidence_core -- see its
                # docstring), just also returning the structured
                # GateSignature list the inner ReAct loop below reflects
                # over. verdict/reasons are byte-identical to what plain
                # evaluate_stage_evidence() would have returned.
                verdict, reasons, structured_signatures = evaluate_stage_evidence_with_detail(
                    self.root, stage, result.text)
            else:
                verdict, reasons, structured_signatures = "NO_GATE_REQUIRED", [], []
            evidence_blocks = extract_evidence_blocks(result.text) if result.text else {}
            if verdict in ("NO_GATE_REQUIRED", "PASS"):
                ss["status"] = Status.PASS.value
                self.state.overall_status = Status.PASS.value
                if correction_note:
                    # The human's correction has been addressed (the stage's
                    # own gate now accepts the evidence) -- stop folding it
                    # into future prompts. A fresh `dv-harness correct` call
                    # re-arms it if the human disagrees again later.
                    cp.consume_correction(stage)
                # APPROVE gate: the most concrete, honest target for this
                # verb. PROMOTION_READINESS/SIGNOFF passing their own
                # automated gates is not the same thing as a human sign-off
                # (same "LSF DONE != DV PASS" principle, one level up) -- a
                # human must have run `dv-harness approve <stage>` for this
                # stage before it is allowed to actually close, regardless of
                # gate verdict.
                if stage in (Stage.PROMOTION_READINESS.value, Stage.SIGNOFF.value):
                    if not approval:
                        ss["status"] = Status.WAIT_USER.value
                        self.state.overall_status = Status.WAIT_USER.value
                        ss["blocking_reason"] = (
                            f"HUMAN_APPROVAL_REQUIRED: gate evidence passed, but {stage} "
                            f"still needs `dv-harness approve {stage}` before it can close."
                        )
                    else:
                        # BUG FIX (2026-08-28, wq5whmpdv adversarial verify):
                        # an approval previously never expired -- approve
                        # once, and every future PASS at this stage (even
                        # against completely different, never-reviewed
                        # evidence from a later re-run) closed automatically.
                        # Consuming it here (same idiom as consume_correction
                        # above) makes each APPROVE authorize exactly the one
                        # PASS it was granted for; a subsequent re-run of this
                        # stage requires a fresh `dv-harness approve` again --
                        # consistent with CLAUDE.md "Any current root cause
                        # must be revalidated with current evidence."
                        cp.clear_approval(stage)
                # ---- 3. Blackboard write: only on PASS, sourced from the
                #         stage's own evidence -- never a placeholder. -----
                if node is not None and node.blackboard_write:
                    self._write_blackboard_from_evidence(node, stage, evidence_blocks, result)
                # ---- 3b. Closed-loop Experience promotion: only on an
                #          actual gate-verified PASS (not NO_GATE_REQUIRED,
                #          which means no STAGE_GATES mapping exists to have
                #          verified anything) -- best-effort side effect, a
                #          persistence failure must never downgrade an
                #          already-earned stage PASS. ----------------------
                if verdict == "PASS":
                    self._promote_experience_knowledge(stage, evidence_blocks)
                    self._persist_subsystem_registry_entry(stage, evidence_blocks)
                    self._compose_soc_environment_files(stage, evidence_blocks)
                    self._score_root_cause_confidence(stage, evidence_blocks, verdict)
                    self._append_coverage_history_sample(stage, evidence_blocks)
                    self._promote_project_topology_knowledge(stage, evidence_blocks)
                    self._promote_vplan_summary_knowledge(stage, evidence_blocks)
            elif verdict == "NEEDS_USER_INPUT":
                # BUG FIX (2026-08-28, plan-interactive-intake-completeness
                # design pass): previously this was indistinguishable from
                # any other GATE_FAIL -- a genuine "the agent needs an answer
                # from you before it can continue" moment (today, only
                # INTAKE's intake_readiness gate produces this; see gates.py)
                # looked identical to "the agent supplied invalid evidence".
                # WAIT_USER already exists for the analogous
                # PROMOTION_READINESS/SIGNOFF human-approval-required case
                # above; this is its first use for a genuine question rather
                # than an approval gate. `reasons` here are already
                # human-readable questions (gates.py's INTAKE_FIELD_QUESTIONS),
                # not raw gate-reason strings -- deliberately NOT replan_stage()'d
                # like PARTIAL below, since this isn't a retry-worthy failure,
                # it is a stop-and-wait-for-a-human state (same reasoning
                # policy.py's graph_next() already applies to WAIT_USER).
                ss["status"] = Status.WAIT_USER.value
                self.state.overall_status = Status.WAIT_USER.value
                ss["blocking_reason"] = ("NEEDS_USER_INPUT: " + "; ".join(str(r) for r in reasons))[:2000]
            elif (node is not None and node.react
                  and self.cfg["policy"].get("enable_inner_react_loop", True)):
                # ---- Content-driven inner ReAct loop (2026-08-29): turns
                #      what this branch used to treat as one opaque
                #      GATE_FAIL/DV_REVIEW_PENDING/MISSING_EVIDENCE result
                #      into real intermediate Reason->Act->Observe->Reflect
                #      turns before committing to the one status this method
                #      already knows how to assign below. Opt-in per stage
                #      (node.react, default True) and globally
                #      (policy.enable_inner_react_loop, default True) --
                #      react:false or the flag off falls through to the
                #      byte-identical PARTIAL+replan_stage() path in the
                #      `else` branch beneath this one. See
                #      dv_harness/react_loop.py's module docstring for the
                #      one deviation from the design spec's illustrative
                #      signatures (an additive `graph=self.graph` -- REROUTE
                #      validation needs real graph.nodes data that the
                #      spec's own snippets never actually threaded through).
                outcome = InnerReactLoop(
                    self.root, self.adapter, self.react, self.cfg, graph=self.graph
                ).run(
                    stage, node, ss["attempts"], result, verdict, reasons,
                    structured_signatures, base_prompt=prompt,
                )
                result, verdict, reasons = outcome.result, outcome.verdict, outcome.reasons
                evidence_blocks = outcome.evidence_blocks
                if result.session_id:
                    ss["session_id"] = result.session_id
                    self.state.last_session_id = result.session_id
                ss["last_message"] = result.text[-6000:] if result.text else ""
                if outcome.reroute_target:
                    ss["react_reroute_target"] = outcome.reroute_target
                else:
                    ss["react_reroute_target"] = None

                ss["status"] = Status.PARTIAL.value
                self.state.overall_status = Status.PARTIAL.value
                ss["blocking_reason"] = (f"{verdict}: " + "; ".join(str(r) for r in reasons))[:2000]
                replan_stage(
                    self.root, stage,
                    reason=f"{verdict} on stage {stage} attempt {ss['attempts']} "
                           f"(after {outcome.iterations} inner ReAct iteration(s))",
                    evidence={"gate_reasons": reasons, "attempt": ss["attempts"],
                              "inner_react_iterations": outcome.iterations,
                              "react_reroute_target": outcome.reroute_target},
                    new_steps=[dict(s, status="RETRY_PENDING") for s in plan["steps"]],
                )
            else:
                ss["status"] = Status.PARTIAL.value
                self.state.overall_status = Status.PARTIAL.value
                ss["blocking_reason"] = (f"{verdict}: " + "; ".join(str(r) for r in reasons))[:2000]
                if node is not None:
                    replan_stage(
                        self.root, stage,
                        reason=f"{verdict} on stage {stage} attempt {ss['attempts']}",
                        evidence={"gate_reasons": reasons, "attempt": ss["attempts"]},
                        new_steps=[dict(s, status="RETRY_PENDING") for s in plan["steps"]],
                    )
        else:
            ss["status"] = Status.FAIL.value
            self.state.overall_status = Status.FAIL.value
            ss["blocking_reason"] = result.raw.get("stderr","")[:2000]
            if node is not None:
                replan_stage(
                    self.root, stage,
                    reason=f"ADAPTER_FAIL on stage {stage} attempt {ss['attempts']}",
                    evidence={"stderr": ss["blocking_reason"], "attempt": ss["attempts"]},
                    new_steps=[dict(s, status="FAILED_ADAPTER_CALL") for s in plan["steps"]],
                )

        # ---- 4. ReAct record: this call itself is one Reason/Act/Observe
        #         record per run_stage() attempt (iteration number is this
        #         stage's own attempt counter, so retries of the same stage
        #         produce iteration 2, 3, ... under the same node/
        #         directory). The GATE_FAIL/DV_REVIEW_PENDING/MISSING_EVIDENCE
        #         branch above additionally runs InnerReactLoop, a genuine
        #         harness-driven multi-iteration content-driven loop with its
        #         own per-iteration record_reflection() calls -- so the outer
        #         iteration-per-attempt bookkeeping here and the inner
        #         multi-iteration loop above are two different, both-real
        #         things, not a contradiction. --------------------------
        if node is not None:
            self.react.record(
                node=stage,
                iteration=ss["attempts"],
                reason_summary=_reason_summary(route_info, plan, bb_snapshot),
                action={"adapter": type(self.adapter).__name__,
                        "agent": route_info["agent"] if route_info else None,
                        "resume_session": resume},
                tool="ClaudeAdapter.run",
                observation={"ok": result.ok, "status": ss["status"], "session_id": result.session_id},
                evidence=evidence_blocks,
                confidence=("HIGH" if ss["status"] == Status.PASS.value
                            else "LOW" if ss["status"] == Status.FAIL.value else "MEDIUM"),
                next_action=("advance" if ss["status"] == Status.PASS.value else "retry_or_reroute"),
            )

        self.store.event({
            "ts": now(), "stage": stage, "ok": result.ok,
            "session_id": result.session_id, "summary": ss["last_message"][-1000:]
        })
        self.store.save(self.state)
        self.profiler.end_stage(profile["profile_id"], status=ss["status"],
            finding_count=self.state.findings_total, closed_finding_count=self.state.findings_closed)
        return result

    def advance(self, user_goal: str = ""):
        # Graph-level parallel fan-out/join (2026-08-29): main_graph.json's
        # parallel_group/join_group metadata (ANALYSIS_G1: REQUIREMENTS_
        # TRACEABILITY/SOC_SCENARIO_PLANNER/INFRASTRUCTURE_AUDIT fanning out
        # from PROTOCOL_CAPABILITY, joining at ANALYSIS_JOIN) previously had
        # no execution-side effect -- graph.py's GraphDefinition.next_for()
        # only ever returns ONE target, so the engine only ever advanced one
        # stage at a time regardless of what the metadata declared.
        # next_frontier() (graph.py) is a strict superset of next_for(): for
        # every OTHER node in this graph (single PASS edge) it returns a
        # single-element list carrying the exact same target next_for()
        # already returned -- so the fallback path below (unchanged from
        # before this feature) is taken whenever len(frontier) <= 1, which is
        # every node except PROTOCOL_CAPABILITY today. Only when it returns
        # more than one target does _advance_with_fanout() run at all.
        if self.graph is not None:
            frontier = self.graph.next_frontier(self.state.current_stage, Status.PASS.value)
            if len(frontier) > 1:
                return self._advance_with_fanout(self.state.current_stage, frontier, user_goal)
        n = graph_next(self.state.current_stage, Status.PASS.value, self.root) \
            or next_stage(self.state.current_stage)
        if not n:
            return None
        self.state.current_stage = n
        self.store.save(self.state)
        return n

    def _run_branch_to_terminal(self, user_goal: str, branch: str) -> str:
        """Runs one parallel_group branch stage to a terminal status,
        mirroring loop()'s own single-stage retry/exhaustion handling exactly
        (same max_stage_retries policy, same replan_stage() call on
        exhaustion) but scoped to just this one branch -- current_stage is
        never touched here, so concurrent callers (one per branch, from
        _advance_with_fanout's ThreadPoolExecutor) never race on it."""
        max_retry = self.cfg["policy"].get("max_stage_retries", 2)
        while True:
            self.run_stage(user_goal, stage=branch)
            ss = self.state.stages[branch]
            status = ss["status"]
            if status in (Status.BLOCKED.value, Status.WAIT_USER.value):
                return status
            if status in (Status.FAIL.value, Status.PARTIAL.value):
                if ss["attempts"] <= max_retry:
                    ss["status"] = Status.RETRY.value
                    self.store.save(self.state)
                    continue
                replan_stage(
                    self.root, branch,
                    reason=f"stage {branch} exhausted retries ({ss['attempts']} attempts)",
                    evidence={"stage": branch, "attempts": ss["attempts"],
                              "status": ss["status"], "blocking_reason": ss.get("blocking_reason", "")},
                )
                return status
            return status

    def _advance_with_fanout(self, source_node: str, targets: List[str], user_goal: str):
        """Real concurrent dispatch for a parallel_group fan-out: source_node
        (e.g. PROTOCOL_CAPABILITY) just PASSed and next_frontier() returned
        more than one target (e.g. the 3 ANALYSIS_G1 branches) -- each is a
        genuine I/O-bound adapter call, so ThreadPoolExecutor gives real
        concurrency benefit. current_stage is left on source_node for the
        duration (nothing needs to read it as "the" active stage while
        branches run) and only moves once this fan-out resolves."""
        nodes = {t: self.graph.nodes[t] for t in targets}
        groups = {n.parallel_group for n in nodes.values()}
        if len(groups) != 1 or None in groups:
            raise RuntimeError(
                f"advance(): {source_node} fans out to {targets} with inconsistent or "
                f"missing parallel_group metadata {groups} -- refusing to guess a join point"
            )
        group = groups.pop()
        join_candidates = [n.id for n in self.graph.nodes.values() if n.join_group == group]
        if len(join_candidates) != 1:
            raise RuntimeError(
                f"advance(): parallel_group {group} has {len(join_candidates)} join node(s) "
                f"(expected exactly 1): {join_candidates}"
            )
        join_node = join_candidates[0]

        # Future-proof safety (not load-bearing for THIS graph -- the 3 real
        # ANALYSIS_G1 branches each write a distinct blackboard topic today --
        # but a later parallel_group whose branches share a write topic must
        # not silently race): claim every topic a branch declares via the
        # same AgentTaskStore.acquire() ownership registry run_stage()'s own
        # MultiAgentOrchestrator.delegate() already uses, before any branch
        # actually runs.
        for branch, node_b in nodes.items():
            for topic in node_b.blackboard_write:
                task_id = f"FANOUT-{group}-{branch}"
                ok, owner = self.agents.store.acquire(topic, task_id, node_b.agent)
                if not ok:
                    raise RuntimeError(
                        f"parallel_group {group}: blackboard topic '{topic}' for branch "
                        f"{branch} is already claimed by task {owner['task_id']}"
                    )

        frontier = ParallelFrontierStore(self.root)
        frontier.start(group, source_node, targets)
        # HarnessState.active_stages (2026-08-29): the simple public-facing
        # answer for dashboard/CLI/status consumers who don't need to know
        # parallel_frontier.json exists -- ParallelFrontierStore stays the
        # source of truth for the join_group/source_node bookkeeping the
        # join mechanics themselves rely on. current_stage deliberately
        # stays on source_node throughout (see HarnessState's own
        # active_stages docstring).
        self.state.active_stages = list(targets)
        self.store.save(self.state)

        results: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(targets)) as ex:
            future_map = {ex.submit(self._run_branch_to_terminal, user_goal, b): b for b in targets}
            for fut in as_completed(future_map):
                b = future_map[fut]
                status = fut.result()
                results[b] = status
                frontier.set_branch_status(group, b, status)

        failed = [b for b in targets if results[b] not in (Status.PASS.value, Status.CLOSED.value)]
        if failed:
            # Do NOT proceed to the join -- mirror the sequential path's
            # existing single-stage failure handling, scoped to the first
            # non-PASS branch. Every branch's own result stays recorded in
            # self.state.stages[branch] (never discarded), regardless of
            # which one drives the routing decision below.
            b = failed[0]
            status = results[b]
            if status in (Status.BLOCKED.value, Status.WAIT_USER.value):
                self.state.current_stage = b
                self.store.save(self.state)
                return b
            n = graph_next(b, Status.FAIL.value, self.root)
            self._record_debug_loop_round(b, n)
            if n and n != b:
                self.state.current_stage = n
            else:
                self.state.current_stage = b
                n = b
            self.store.save(self.state)
            return n

        # All branches PASSed: reuse graph_next()'s existing synthetic-node
        # passthrough (it already knows how to skip a non-Stage node like
        # ANALYSIS_JOIN through to the real next Stage, e.g. VPLAN) by
        # starting the lookup FROM the join node, not from the last branch.
        n = graph_next(join_node, Status.PASS.value, self.root) or next_stage(join_node)
        if not n:
            return None
        # The fan-out is fully resolved -- clear active_stages back to []
        # now that current_stage is about to advance past the join. Left
        # populated (not cleared) on the failed/blocked return above: a
        # human looking at a parked, blocked fan-out should still be able to
        # see which branches were concurrently active when it stopped,
        # mirroring parallel_frontier.json's own persistent (never
        # auto-cleared) record of the same thing.
        self.state.active_stages = []
        self.state.current_stage = n
        self.store.save(self.state)
        return n

    def mark(self, status: str, message: str = ""):
        # Assessed 2026-08-29 (active_stages read-site audit): left targeting
        # current_stage only, by design, not a gap forced open here. mark()'s
        # only caller is commands.cmd_mark(), which already carries an
        # in-file NOTE documenting this exact limitation (no stage argument,
        # so a live fan-out branch can't be targeted by name) as a real,
        # pre-existing gap deliberately deferred pending a separate design
        # pass on adding a stage argument to the command itself -- not
        # something to half-fix by having mark() guess at a branch with no
        # way for a caller to actually name one yet.
        ss = self.state.stages[self.state.current_stage]
        ss["status"] = status
        ss["last_message"] = message or ss.get("last_message","")
        self.state.overall_status = status
        self.store.save(self.state)

    def loop(self, user_goal: str):
        while True:
            stage = self.state.current_stage

            # Human Override principle: checked FIRST, before anything else
            # in the loop body (before the SIGNOFF gate check, before
            # run_stage()) -- so a human can always stop/reroute regardless
            # of what state the automatic pipeline is in. TAKEOVER (the
            # strongest override) is checked before PAUSE. Both stop the
            # loop cleanly with a single `return` -- no crash, no busy-wait,
            # no partial state mutation beyond recording why we stopped.
            #
            # BUG FIX (2026-08-28, wq5whmpdv adversarial verify): dropped the
            # tk.get("stage") == stage requirement -- see the matching fix
            # (and its full rationale) in run_stage() above. Any active
            # takeover halts the loop regardless of which stage it was
            # issued against or which stage the loop has since reached.
            cp = ControlPlane(self.root)
            cp_state = cp.load()
            tk = cp_state.get("takeover", {})
            if tk.get("active"):
                ss = self.state.stages[stage]
                ss["status"] = Status.WAIT_USER.value
                ss["blocking_reason"] = (f"TAKEOVER active (taken on stage {tk.get('stage')}): "
                                          f"{tk.get('message', '')}")
                self.state.overall_status = Status.WAIT_USER.value
                self.store.save(self.state)
                print(f"[dv-harness] TAKEOVER active on stage {stage} -- loop stopped "
                      f"cleanly. Run `dv-harness release-takeover` to return control.")
                return
            if cp_state.get("paused"):
                reason = cp_state.get("paused_reason", "")
                print(f"[dv-harness] PAUSED" + (f" ({reason})" if reason else "")
                      + " -- loop stopped cleanly before running the next stage. "
                        "Run `dv-harness resume` to continue.")
                return

            if stage == Stage.SIGNOFF.value:
                ok, why, redirect_stage = can_signoff(self.state, self.cfg)
                if not ok:
                    if redirect_stage:
                        # Auto-recoverable (e.g. SHA drift -> re-sync,
                        # open findings -> back to IMPLEMENT): this is not a
                        # human decision, route there and keep looping.
                        ss = self.state.stages[stage]
                        ss["blocking_reason"] = why
                        self.state.current_stage = redirect_stage
                        self.store.save(self.state)
                        continue
                    self.mark(Status.BLOCKED.value, why)
                    return

            result = self.run_stage(user_goal)
            ss = self.state.stages[stage]
            status = ss["status"]

            if status in (Status.BLOCKED.value, Status.WAIT_USER.value):
                return
            if status in (Status.FAIL.value, Status.PARTIAL.value):
                # BUG FIX (2026-08-28, confirmed by architecture audit): this
                # branch previously only matched Status.FAIL.value. A PARTIAL
                # result (result.ok was True but evaluate_stage_evidence()
                # rejected the evidence -- GATE_FAIL/MISSING_EVIDENCE/
                # DV_REVIEW_PENDING) fell through to the unconditional
                # `self.advance()` below, which calls graph_next(...,
                # Status.PASS.value, ...) -- i.e. a stage that FAILED its
                # hard gate was silently routed along the graph's PASS edge
                # as if it had actually passed. Treating PARTIAL the same as
                # FAIL here (retry, then follow the graph's FAIL edge once
                # retries are exhausted) is what makes the Hard Gate
                # mechanism's rejection actually stop forward progress in the
                # automatic loop() driver, not just in the one-shot
                # run_stage()/CLI-return-code path.
                max_retry = self.cfg["policy"].get("max_stage_retries", 2)
                if ss["attempts"] <= max_retry:
                    ss["status"] = Status.RETRY.value
                    self.store.save(self.state)
                    continue
                # Retries exhausted: Graph is the workflow authority
                # (CLAUDE.md) -- route to whatever main_graph.json's FAIL
                # edge says (e.g. BUILD/VERIFY/REGRESSION_MONITOR ->
                # FAILURE_RECOVERY) instead of just stopping. Only stop if
                # the graph has no FAIL edge for this stage. A PARTIAL that
                # exhausts retries is routed via the same FAIL edge -- the
                # graph model only has PASS/FAIL/BLOCKED conditions, and a
                # stage whose gate never accepted evidence is a failure from
                # the workflow's perspective, not a silent pass-through.
                #
                # REPLAN, coarse call site (run_stage() above already fires a
                # finer-grained per-attempt replan on every individual
                # GATE_FAIL/PARTIAL/ADAPTER_FAIL): this one specifically
                # records the retry-exhaustion routing decision itself, with
                # its actual attempts count and blocking_reason as evidence.
                replan_stage(
                    self.root, stage,
                    reason=f"stage {stage} exhausted retries ({ss['attempts']} attempts)",
                    evidence={"stage": stage, "attempts": ss["attempts"],
                              "status": ss["status"], "blocking_reason": ss.get("blocking_reason", "")},
                )
                n = graph_next(stage, Status.FAIL.value, self.root)

                # Cross-cycle debug-loop-round counter + Health Monitor
                # dispatch (2026-09-01, ai-debug-closed-loop-counter-
                # implementation task): recorded here, BEFORE the react
                # reroute hint below can override `n` -- target_fail_edge
                # reflects the graph's own actual FAIL edge target (Graph
                # remains the workflow authority), not a content-driven
                # override. See _record_debug_loop_round()'s own docstring.
                self._record_debug_loop_round(stage, n)

                # Content-driven reroute hint (2026-08-29, inner ReAct loop):
                # ss["react_reroute_target"] is set only by run_stage()'s
                # InnerReactLoop wiring above, and only when its chosen
                # action was REROUTE to a real graph node -- consulted here
                # as a PREFERENCE over the static graph FAIL edge, never
                # instead of it (Graph remains the workflow authority; a
                # stage with no FAIL edge at all, e.g. ARCH_CALIBRATION in
                # main_graph.json, previously just stalled here -- the hint
                # gives it somewhere real to go instead of silently
                # returning below).
                hint = ss.get("react_reroute_target")
                if hint and self.graph is not None and hint in self.graph.nodes:
                    n = hint
                if n and n != stage:
                    self.state.current_stage = n
                    self.store.save(self.state)
                    continue
                return

            n = self.advance(user_goal)
            if not n:
                self.state.overall_status = Status.CLOSED.value
                self.store.save(self.state)
                return
