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
from .policy import ORDER, next_stage, graph_next, can_signoff
from .gates import evaluate_stage_evidence, extract_evidence_blocks, STAGE_GATES, JUDGMENT_FIELDS
from .react_loop import InnerReactLoop, evaluate_stage_evidence_with_detail
from .memory_router import route_and_store, promote_to_organizational
from .memory_vault import build_failure_signature, search_related_memory_for_debug
from .inference import (score_confidence, identify_gap, next_best_action, promote_if_high_confidence,
                        build_deeper_investigation_signal)
from .qualified_conclusion import build_qualified_conclusion
from .knowledge_center import KnowledgeCenterClient
from .adapters.cli import ClaudeCLIAdapter
from .adapters.sdk import ClaudeCodeSDKAdapter
from .adapters.base import AgentResult
from .stage_profile import StageExecutionProfiler, extract_provider_usage
from .control_plane import ControlPlane, replan_stage, _find_latest_plan, describe_stage
from .agent_profile import load_agent_profile
from . import self_tuning

# --- Plan-and-Execute / Multi-Agent / Blackboard / ReAct wiring -------------
# planner.py, react.py, router.py, multi_agent.py, skill_resolver.py were all
# confirmed (2026-08-28 architecture audit) to be correct but never imported
# by any executing code path -- the now-deleted dv_harness/graph_runtime.py
# (removed 2026-09-03, gap-close-engine cleanup: it was reachable only via
# DV_GRAPH_STATUS.ps1, which drove a permanently-stale standalone GraphState
# disconnected from the real HarnessState below, and has since been
# retargeted to read live state directly) had once wired all of them together
# (prepare_node/complete_node) but was itself never imported by engine.py or
# cli.py either. Rather than importing that GraphRuntime wholesale (its
# prepare_node/complete_node shape doesn't line up 1:1 with run_stage()'s
# single-call-per-attempt model, e.g. it would create a brand new plan/task
# on every retry with no reuse concept), this reuses the same underlying
# modules directly inside run_stage(), and reuses control_plane.py's already-
# real REPLAN call site (replan_stage/_find_latest_plan, wired in by a
# parallel pass on this same file) for plan lookup/replanning instead of
# re-deriving that logic here. graph.py's GraphDefinition (node-by-id lookup)
# is reused as-is -- it already does this correctly; see _load_graph() below.
from .graph import GraphDefinition
from .parallel_frontier import ParallelFrontierStore
from .blackboard import Blackboard
from .router import RouteResolver
from .planner import PlanStore, default_plan
from .multi_agent import MultiAgentOrchestrator
from .react import ReactRecorder, build_memory_context_references
from .skill_resolver import SkillResolver
# --- Real, input-driven protocol/environment-mode resolution (2026-09-01,
# route-skill-resolver-dynamic-implementation task; wiring completed
# 2026-09-04, AI-mechanism re-audit gap #4). These two resolvers apply the
# genuinely input-driven rules documented in .claude/skills/CORE/
# protocol-router/SKILL.md and CLAUDE.md's "Environment Generation Mode"
# gate (previously prose-only -- see each module's own docstring for the
# full gap/ruling this closes). resolve_protocol() is called BEFORE
# RouteResolver.resolve()/SkillResolver.resolve() in run_stage() below and
# passed into the former, so its evidence-driven answer actually widens the
# skills a protocol-sensitive stage resolves and delegates -- it is no
# longer a parallel audit-only field beside a purely static answer.
from .protocol_router import resolve_protocol
from .environment_mode_router import resolve_environment_mode, read_registered_subsystem_names
from .uvm_generator.generator import sv_id
from .uvm_generator.soc_environment_composer import (
    compose_soc_environment, CrossSubsystemIntegrationBlockedError,
    EmptySubsystemRegistryError, MissingSubsystemNameEvidenceError,
    soc_composition_out_dir,
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

# --- Stage transition markers (2026-09-01, runtime-progress-visibility pass)
# ------------------------------------------------------------------------
# RULING: no module anywhere in dv_harness/ uses Python's `logging` (grepped
# for `logging.getLogger`/`logging.basicConfig` project-wide -- zero hits);
# every existing CLI/engine output path is plain `print()`. Introducing
# `logging` here alone would be a second, inconsistent output convention for
# one feature -- these two markers use plain `print()` to stdout instead,
# with a real, greppable, unique prefix (`STAGE_MARKER_PREFIX` below) so a
# human or a log-scraping tool can isolate them from the surrounding agent
# free-text output unambiguously (`grep '\[DV-HARNESS-STAGE\]' run.log`).
# Emitted by run_stage() ITSELF (not cli.py) so both the CLI and any future
# direct caller of DVHarness.run_stage() (the dashboard's background runner,
# a future API server, a test harness) get the same visible "just happened"
# signal, rather than each consumer having to notice a silent status change.
STAGE_MARKER_PREFIX = "[DV-HARNESS-STAGE]"


def _emit_stage_start_marker(stage: str) -> None:
    print(f"{STAGE_MARKER_PREFIX} ===== STAGE START: {stage} =====", flush=True)


def _emit_stage_done_marker(stage: str, gate_verdict: str, stage_completion_percent) -> None:
    pct = f"{stage_completion_percent:.0f}" if isinstance(stage_completion_percent, (int, float)) else "-"
    print(f"{STAGE_MARKER_PREFIX} ===== STAGE DONE: {stage} [{gate_verdict}] "
          f"({pct}% gates satisfied) =====", flush=True)


# --- Stage-boundary progress DISPLAY + persisted report (2026-09-04,
# stage-progress-display gap-close) ----------------------------------------
# The two one-line markers above stay exactly as they were -- they are the
# greppable machine signal (STAGE_MARKER_PREFIX) a log scraper keys on, and
# a test/tool watching for them must not have to change. These two SIBLING
# functions run immediately alongside each marker and emit the human-facing
# display the user's spec asked for: an ASCII-art banner, the real
# required-input / produced-output checklist with a real completeness %, the
# explicit "please provide more detail on X" reminder, and (at DONE) the
# total execution time including every sub-agent run plus the tokens
# consumed. Both then PERSIST the exact text they printed as a markdown
# report under .dv-harness/stage_reports/.
#
# Every number and every checklist line comes from an existing real source --
# gates.STAGE_GATES, the graph node's own blackboard_read/blackboard_write/
# expected_evidence/expected_outputs, the live Blackboard, the filesystem,
# and StageExecutionProfiler's telemetry. See dv_harness/stage_progress_display.py.
#
# Both are wrapped in try/except at their call sites in run_stage(): this is
# observability, and a display or report-write failure must never turn a
# stage that really ran into a stage that failed.
def _emit_stage_start_display(root: Path, stage: str, node, blackboard,
                               stage_history, graph=None, attempt=None) -> Dict[str, Any]:
    from . import stage_progress_display as spd
    checklist = spd.build_stage_input_checklist(root, stage, node, blackboard,
                                                 stage_history=stage_history)
    requests = spd.build_detail_requests(root, stage, checklist, graph=graph)
    text = spd.render_stage_start_display(stage, checklist, requests, attempt=attempt)
    print(text, flush=True)
    path = spd.save_stage_report(root, stage, "start", text, payload={
        "stage": stage, "phase": "START", "attempt": attempt,
        "input_checklist": checklist, "detail_requests": requests,
    })
    print(f"{STAGE_MARKER_PREFIX} stage start report saved: {path}", flush=True)
    return {"input_checklist": checklist, "detail_requests": requests,
            "report_path": str(path), "display": text}


def _emit_stage_done_display(root: Path, stage: str, node, blackboard, evidence_blocks,
                              gate_verdict, stage_completion_percent,
                              gate_reasons=None, graph=None) -> Dict[str, Any]:
    from . import stage_progress_display as spd
    from .stage_profile_report import stage_time_and_token_summary
    checklist = spd.build_stage_output_checklist(root, stage, node, blackboard,
                                                  evidence_blocks=evidence_blocks)
    outstanding = spd.build_detail_requests(root, stage, checklist, graph=graph,
                                             gate_reasons=gate_reasons)
    summary = stage_time_and_token_summary(root, stage)
    text = spd.render_stage_done_display(stage, gate_verdict, stage_completion_percent,
                                          checklist, summary, outstanding=outstanding)
    print(text, flush=True)
    path = spd.save_stage_report(root, stage, "done", text, payload={
        "stage": stage, "phase": "DONE", "gate_verdict": gate_verdict,
        "stage_completion_percent": stage_completion_percent,
        "output_checklist": checklist, "outstanding": outstanding,
        "time_token_summary": summary,
    })
    print(f"{STAGE_MARKER_PREFIX} stage done report saved: {path}", flush=True)
    return {"output_checklist": checklist, "outstanding": outstanding,
            "time_token_summary": summary, "report_path": str(path), "display": text}


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

def _bb_rca_join(evidence: dict, stage: str, result) -> Dict[str, Any]:
    """RCA_JOIN's fused-evidence record, in the SAME "rca_evidence_fusion"
    Blackboard topic shape .claude/workflows/rca-multi-agent-fusion.js writes
    via `dv-harness blackboard write` -- deliberately one topic and one shape
    for the two real ways this harness can run a multi-agent RCA (the engine's
    own RCA_G1 graph fan-out, and that Workflow script when a coordinating
    session invokes it by name), so a later root_cause_evidence_gate block or
    audit reads one record regardless of which path produced it.

    Every field comes from RCA_JOIN's own gate-verified root_cause_evidence_
    gate block; nothing is synthesized. `contributing_agents` is deliberately
    NOT taken from the agent's text -- see _write_blackboard_from_evidence,
    which overlays the real branch agent ids from the graph itself."""
    rc = evidence.get("root_cause_evidence_gate", {})
    if not isinstance(rc, dict):
        rc = {}
    return {"rca_evidence_fusion": {
        "symptom": rc.get("symptom"),
        "root_cause": rc.get("root_cause"),
        "first_bad_event": rc.get("first_bad_event"),
        "causal_chain": rc.get("causal_chain", []),
        "fused_findings": rc.get("supporting_evidence", []),
        "disagreements": rc.get("counter_evidence", []),
        "hypotheses": rc.get("hypotheses", []),
        "fusion_confidence": rc.get("confidence"),
        "produced_by": "engine:RCA_G1_graph_fanout",
        "summary": (result.text or "")[:2000],
    }}

STAGE_BLACKBOARD_WRITERS = {
    "ENV_CHECK": _bb_env_check,
    "INTAKE": _bb_intake,
    "VERIFY": _bb_verify,
    "REGRESSION_MONITOR": _bb_regression_monitor,
    "RCA_JOIN": _bb_rca_join,
}


# --- Stage entry/exit evidence checklists (2026-09-01, expected-evidence-
# checklist design pass) ------------------------------------------------
# main_graph.json's node schema previously had no field declaring what
# evidence/files a stage requires at entry or should produce at exit --
# prompts.py's STAGE_INSTRUCTIONS described "required_artifacts"-style
# requirements only as prose the AGENT self-reports at turn-end, never a
# harness-computed, presence-checked list. Node.expected_evidence/
# expected_outputs (graph.py, additive/optional) now carry that as structured
# {item_id, description, kind} entries; the two functions below turn a
# node's list into a real presence-checked report. Both are INFORMATIONAL
# ONLY -- they never raise, never change ss["status"], and a node with no
# expected_evidence/expected_outputs list (the default) produces a trivial
# zero-item report, never an error, so every existing graph node stays
# byte-for-byte unaffected.
#
# `kind` resolution (identical between entry/exit; the only difference is
# which stage's evidence an "evidence_field" item can see, per each
# function's own docstring):
#   - "blackboard_key": item_id is a Blackboard topic name; present iff
#     Blackboard.read(item_id) is not None (the topic has been written at
#     least once -- content is not otherwise inspected).
#   - "file_path": item_id is a path (absolute, or relative to `root`);
#     present iff Path(...).exists().
#   - "evidence_field": item_id is a dotted field path into an evidence
#     block dict, optionally prefixed "STAGE_ID:" to name which stage's
#     evidence to dig into (see each function's docstring for the default
#     when no prefix is given). A bare item_id with no dot (e.g.
#     "intake_readiness") checks the whole block's presence; a dotted one
#     (e.g. "intake_readiness.mode") navigates into it. Present iff every
#     path segment resolves to a dict key AND the final value is truthy
#     (mirrors the gate scripts' own "field must be non-empty" convention --
#     a required_artifacts.<x>: false is correctly reported ABSENT, not
#     "present but false").
#   - any other/unknown kind: always reported absent, never raises -- a
#     future kind can be added to main_graph.json ahead of engine support
#     without crashing run_stage().
def _dig_evidence_field(source: Dict[str, Any], dotted_path: str) -> bool:
    cur: Any = source
    for part in dotted_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return bool(cur)


# GAP FIX (2026-09-02, RE_AUDIT/FAILURE_RECOVERY approval-gate audit): the
# PROMOTION_READINESS/SIGNOFF hard-stop below (dv-harness approve) had no
# counterpart at RE_AUDIT -- a fix's own "approved_for_modify" boolean was
# just JSON the SAME agent proposing the fix wrote in its own reply
# (tools/verification_flow/fix_risk_approval_gate.py only checked that the
# agent's self-declared boolean was True). This reads the SAME
# fix_risk_approval_gate evidence block that gate already validates and
# reuses its EXISTING "risk_level" field (HIGH/MEDIUM/LOW) plus
# tools/senior_dv/failure_attribution.py's EXISTING "classification"
# vocabulary (TB_BUG/DUT_BUG/UNKNOWN) -- no new field name invented.
# Deliberately narrow: a TB_BUG/low-or-medium-risk fix (the overwhelming
# majority of RE_AUDIT closures) is NOT gated here, so routine testbench
# fixes never require a human `dv-harness approve` call; only a HIGH risk_level
# or a DUT_BUG classification -- the DUT-RTL-risk case the audit flagged --
# does.
def _re_audit_requires_human_approval(evidence_blocks: Dict[str, Any]) -> bool:
    plan = evidence_blocks.get("fix_risk_approval_gate")
    if not isinstance(plan, dict):
        return False
    return plan.get("risk_level") == "HIGH" or plan.get("classification") == "DUT_BUG"


def _checklist_item_present(item: Dict[str, Any], root: Path, blackboard: Blackboard,
                             evidence_for) -> bool:
    kind = item.get("kind")
    item_id = str(item.get("item_id", ""))
    if kind == "blackboard_key":
        return blackboard.read(item_id) is not None
    if kind == "file_path":
        p = Path(item_id)
        if not p.is_absolute():
            p = root / item_id
        return p.exists()
    if kind == "evidence_field":
        stage_ref, sep, field_path = item_id.partition(":")
        if not sep:
            stage_ref, field_path = None, item_id
        return _dig_evidence_field(evidence_for(stage_ref), field_path)
    return False  # unknown kind -- informational report, never raises


def _run_checklist(items_decl: List[Dict[str, Any]], root: Path, blackboard: Blackboard,
                    evidence_for) -> Dict[str, Any]:
    items = [
        {"item_id": item.get("item_id"), "description": item.get("description", ""),
         "present": _checklist_item_present(item, root, blackboard, evidence_for)}
        for item in items_decl
    ]
    total = len(items)
    present_count = sum(1 for it in items if it["present"])
    return {
        "items": items,
        "present_count": present_count,
        "total_count": total,
        # RULING: zero items declared for a stage means no checklist applies
        # to it -- reported as 100% complete (nothing outstanding), not 0%
        # (which would misleadingly read as "totally missing evidence").
        "completeness_percent": (100.0 * present_count / total) if total else 100.0,
        "missing_item_ids": [it["item_id"] for it in items if not it["present"]],
    }


def build_stage_entry_checklist(node, blackboard: Blackboard, root: Path,
                                 stage_history: Optional[Dict[str, Dict[str, Any]]] = None
                                 ) -> Dict[str, Any]:
    """Reads `node.expected_evidence` (absent/empty -> zero-item report, never
    an error) and checks each item's REAL presence -- called at the very top
    of run_stage(), before build_stage_prompt()/adapter.run(), so this never
    reflects anything from the attempt about to run.

    "evidence_field" items resolve against `stage_history` (self.state.stages
    from the CURRENT HarnessState, i.e. run_stage()'s own self.state.stages)
    -- specifically each stage's `last_evidence_blocks` (the evidence blocks
    that stage's most recent PRIOR attempt, if any, actually submitted; see
    where run_stage() persists it below). A bare item_id (no "STAGE_ID:"
    prefix) defaults to node.id's own last_evidence_blocks -- e.g. on a
    retry, "did this stage already submit this field last attempt". A
    prefixed item_id (e.g. "REGRESSION_SELECT:...") looks at a DIFFERENT
    upstream stage's last submission -- the real mechanism for a stage like
    REGRESSION whose actual input (REGRESSION_SELECT's test selection) is
    never written to the Blackboard by that node (its blackboard_write is
    genuinely empty per main_graph.json), so a blackboard_key check cannot
    see it. Never raises: an unknown/never-run stage_ref, or one whose
    last_evidence_blocks is empty, simply resolves to {} (every item under it
    reports absent)."""
    items_decl = list(getattr(node, "expected_evidence", None) or [])
    history = stage_history or {}

    def evidence_for(stage_ref: Optional[str]) -> Dict[str, Any]:
        sid = stage_ref or (node.id if node is not None else None)
        entry = history.get(sid) if sid else None
        blocks = (entry or {}).get("last_evidence_blocks")
        return blocks if isinstance(blocks, dict) else {}

    return _run_checklist(items_decl, root, blackboard, evidence_for)


def build_stage_exit_checklist(node, blackboard: Blackboard, root: Path,
                                evidence_blocks: Optional[Dict[str, Any]] = None
                                ) -> Dict[str, Any]:
    """Reads `node.expected_outputs` (absent/empty -> zero-item report, never
    an error) and checks each item's REAL presence -- called near the end of
    run_stage(), after the gate verdict is known, alongside the existing
    profiler.end_stage() call.

    "evidence_field" items resolve against `evidence_blocks` -- THIS
    attempt's own freshly-extracted evidence (the same dict run_stage()
    already computed via gates.extract_evidence_blocks(), passed straight
    through with no re-parsing). Unlike the entry checklist, an exit
    checklist only ever has this one attempt's own output to inspect -- a
    "STAGE_ID:" prefix on an expected_outputs item_id is intentionally
    ignored (ONLY the dotted field-path part is used) rather than resolved
    against some other stage's data, since "what did THIS stage attempt just
    produce" is exactly what an exit check means."""
    items_decl = list(getattr(node, "expected_outputs", None) or [])
    blocks = evidence_blocks if isinstance(evidence_blocks, dict) else {}

    def evidence_for(_stage_ref: Optional[str]) -> Dict[str, Any]:
        return blocks

    return _run_checklist(items_decl, root, blackboard, evidence_for)


def _build_plan_section(route_info: dict, resolved_skills: list, plan: dict,
                         bb_snapshot: dict, task: dict) -> str:
    """Folds the resolved route/agent/skills/plan/blackboard-snapshot into the
    prompt so the agent's response is genuinely informed by an explicit plan,
    rather than the plan being write-only (Core Operating Rule: 'Graph is the
    global workflow authority').

    `resolved_skills` is SkillResolver's output for route_info["skills"] --
    the graph node's static skills PLUS whatever this run's real protocol
    decision added (2026-09-04). When something was added, the registry-path-
    prefixed routes are named explicitly, because those are the exact strings
    protocol_profile_binding_gate expects back in a PROTOCOL_CAPABILITY
    stage's `profile_skills_consulted` list."""
    protocol_routes = route_info.get("protocol_skill_routes") or []
    protocol_line = (
        "Skills added by the resolved protocol (consult these; they are the "
        "registry's own profile/vip-lookup routes, quote them verbatim in any "
        f"profile_skills_consulted evidence): {json.dumps(protocol_routes, ensure_ascii=False)}\n"
        if protocol_routes else ""
    )
    return (
        "\n---\n"
        "[Harness Plan-and-Execute / Multi-Agent / Blackboard context -- "
        "resolved by the harness BEFORE this call; this is the plan you are "
        "executing, not decorative]\n"
        f"Resolved route: {route_info['route']} -> agent: {route_info['agent']}\n"
        f"Resolved skills: {json.dumps(resolved_skills, ensure_ascii=False)}\n"
        + protocol_line +
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


# ---------------------------------------------------------------------------
# Subsystem-written Blackboard topics (2026-09-04)
#
# The three topics NOT written by any graph node's own PASS branch (i.e. not
# by _write_blackboard_from_evidence()), mapped to the REAL producer that can
# refresh each one on the automatic path. DVHarness.
# _refresh_declared_subsystem_topics() documents the gap this closes; each
# `ensure_blackboard_topic()` documents what its own refresher will and will
# not do. All three are best-effort, return a report dict rather than
# raising, and none fabricates a topic it has no real source for.
#
# A table rather than an if/elif chain so the coverage claim is CHECKABLE: a
# test compares it against every one of these topics the REAL
# main_graph.json declares in some node's `blackboard_read`, so a topic added
# to the graph with no producer here fails that test instead of silently
# staying absent -- which is the exact failure mode this mechanism exists to
# close. Each thunk imports lazily: engine.py must not pull env_manifest's
# verible/jsonschema stack or connectivity_check's gate machinery in at
# import time just to own this table.

def _refresh_env_manifest_topic(root, blackboard) -> Dict[str, Any]:
    from . import env_manifest as _env_manifest
    return _env_manifest.ensure_blackboard_topic(root, blackboard=blackboard)


def _refresh_open_questions_decisions_topic(root, blackboard) -> Dict[str, Any]:
    from .question_queue import QuestionQueueStore
    return QuestionQueueStore(root, blackboard=blackboard).ensure_blackboard_topic()


def _refresh_connectivity_gates_topic(root, blackboard) -> Dict[str, Any]:
    from . import connectivity_check as _connectivity_check
    return _connectivity_check.ensure_blackboard_topic(root, blackboard=blackboard)


SUBSYSTEM_TOPIC_REFRESHERS: Dict[str, Any] = {
    "env_manifest": _refresh_env_manifest_topic,
    "open_questions_decisions": _refresh_open_questions_decisions_topic,
    "connectivity_gates": _refresh_connectivity_gates_topic,
}


class DVHarness:
    def __init__(self, project_root: Path):
        self.root = project_root.resolve()
        self.cfg = load_config(self.root)
        self.store = StateStore(self.root)
        self.state = self.store.load()
        self.adapter = self._adapter()
        self.profiler = StageExecutionProfiler(self.root)
        # Transport for the DEGRADED mode's license/queue probes (2026-09-03).
        # None means preflight.LocalCommandRunner(), which per preflight.py's
        # own transport docstring is the correct default only when dv_harness
        # runs server-side on the Linux DV server (lmutil/bqueues natively on
        # PATH). A PC-side deployment in REMOTE_EXECUTION mode should assign
        # preflight.RemoteRelayCommandRunner() here to probe the REAL server
        # through the already-sanctioned credential-free relay -- the same
        # "fully injected, never assumed" principle preflight.py states, and
        # the seam dv_harness_tests/test_harness_reliability.py injects a
        # pure mock through so no test ever contacts a live license server.
        #
        # RESOLVED, not left at None (2026-09-04 harness-reliability gap
        # close). Leaving it None meant the sentence above described a
        # capability nobody could reach: no CLI flag, no config key, and no
        # code path anywhere in `dv-harness start`/`run`/`run-stage` ever
        # assigned this attribute, so on this project's own PC-side
        # REMOTE_EXECUTION deployment the license-full/farm-congested
        # triggers were correct, tested, and structurally dead. It is now
        # chosen from `degradation.transport` (default "auto") on REAL probe
        # evidence -- and stays None when no transport is confirmed, so a
        # machine without lmutil/bqueues and without a READY relay behaves
        # exactly as it did before rather than fabricating a verdict from a
        # missing binary. The attribute remains freely assignable afterwards
        # (tests do exactly that); _degraded_gate() arms on whatever runner
        # is present at call time, never on this initial decision.
        self.degradation_transport = self._resolve_degradation_transport()
        self.degradation_runner = self.degradation_transport.runner
        # Transport for the Planner->Execution-Layer preflight gate
        # (_execution_preflight_gate(), 2026-09-04). Same injected-transport
        # seam and same default as degradation_runner immediately above: None
        # means preflight.LocalCommandRunner() (correct only server-side),
        # and a PC-side REMOTE_EXECUTION deployment assigns
        # preflight.RemoteRelayCommandRunner() to probe the REAL server.
        # Assigning a runner here also ARMS the gate on its own -- see
        # _execution_preflight_gate()'s probe_resources branch: an explicitly
        # injected transport is itself the statement that a real probe is
        # possible here, which is what lets a test drive the whole
        # run_stage()->preflight edge through a pure mock.
        self.execution_preflight_runner = None

        # LOOP-4 (section 108): the CURRENT loop session's telemetry context,
        # or None when no loop() is in flight. `run_stage()` on its own is not
        # a loop, so a one-shot `dv-harness run-stage` leaves this None and
        # emits no loop telemetry at all -- which is why the Loop Engineering
        # Center never shows a row for a run that never iterated.
        self._loop_run: Optional[Dict[str, Any]] = None

        # Plan-and-Execute / Multi-Agent / Blackboard / ReAct (see module
        # docstring above): constructed unconditionally -- all four are
        # cheap, file-based, and create their own directories lazily.
        self.graph = self._load_graph()
        self.blackboard = Blackboard(self.root)
        self.router = RouteResolver(self.root)
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

    def _record_loop_state_observation(self, stage: str, occasion: str, *,
                                       convergence: Optional[Dict[str, Any]] = None
                                       ) -> Optional[Dict[str, Any]]:
        """Records ONE real `LOOP_STATE_OBSERVED` event naming this run's
        current `loop_contract.LoopState` (LOOP_ENGINEERING section 86).

        WHY HERE AND ONLY HERE. `models.Status` is a stage-gate VERDICT
        vocabulary and genuinely covers HUMAN_GATE (WAIT_USER) and BLOCKED, so
        most transitions say nothing new. Retry exhaustion is the exception:
        `loop()`'s `ss["attempts"] <= max_retry` branch is the one place this
        engine spends a real budget, and before this a repo-wide grep for
        `BUDGET_EXHAUSTED` returned zero hits anywhere -- the audit trail
        recorded the ROUTING decision (`_record_debug_loop_round()`, one line
        away) but never the fact that a budget was what ran out. The
        observation is derived entirely from state already on disk
        (`state.json`'s status/attempts, `config.json`'s
        policy.max_stage_retries, `control.json`, the Blackboard
        `debug_loop_history` topic) -- never from agent prose, per section 86.

        `convergence` is one `loop_convergence.classify_loop_convergence()`
        report (LOOP-4 wiring, 2026-09-05). LOOP-2 built that classifier and
        disclosed that nothing in the engine fired it -- so PLATEAU and the
        cross-run OSCILLATING verdict were REACHED but never produced on the
        real path, and every observation this method wrote carried
        `PLATEAU_NOT_EVALUATED` forever. Passing a real report here is what
        gives section 108's LOOP_PLATEAU_DETECTED / LOOP_OSCILLATION_DETECTED a
        real producer. Absent (a project with no evidence database), the
        observation still reports PLATEAU_NOT_EVALUATED with its reason: a
        detector that could not run must never read as "no plateau".

        Best-effort, mirroring every sibling `_record_*`/`_promote_*` method:
        an observability failure must never turn an already-computed routing
        decision into a crash."""
        try:
            from . import loop_contract as _lc
            history = self.blackboard.read_debug_loop_history() or {}
            obs = _lc.observe_verification_closure_loop(
                self.state, self.cfg, stage=stage,
                control_plane_state=ControlPlane(self.root).load(),
                debug_loop_entries=history.get("entries") or [],
                convergence=convergence)
            payload = obs.to_dict()
            self.store.event({"ts": now(), "event": "LOOP_STATE_OBSERVED",
                              "occasion": occasion, **payload})
            return payload
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "event": "LOOP_STATE_OBSERVE_FAILED",
                                  "occasion": occasion, "stage": stage,
                                  "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass
            return None

    # ---- LOOP-4: section 108's loop telemetry events -----------------------
    #
    # (LOOP_ENGINEERING section 108 -- see dv_harness/loop_telemetry.py's module
    # docstring for the pre-build verification that all nineteen names had zero
    # producers.) Everything below is BEST-EFFORT and OBSERVE-ONLY: not one of
    # these methods changes a status, a route, an attempt count or a gate
    # verdict, and none of them can fail a stage. They record what the loop
    # already decided, through the SAME `StateStore.event()` and the SAME
    # `.dv-harness/events.jsonl` `_record_debug_loop_round()`,
    # `_record_loop_state_observation()` and `_spend_retry_exhaustion_budget()`
    # write to -- no second audit file, no second serializer.
    #
    # The session dict lives on the harness for the duration of ONE `loop()`
    # invocation (`self._loop_run`), which is what makes a `run_id` mean "one
    # loop session" rather than "one process". It is deliberately absent
    # outside a loop: `run_stage()` on its own is not a loop, so a one-shot
    # `dv-harness run-stage` emits nothing and `_emit_loop_event()` is a no-op.

    def _emit_loop_event(self, event: str, **payload: Any) -> None:
        """One section-108 event for the CURRENT loop session, or nothing.

        Best-effort by construction: a telemetry failure records
        `LOOP_TELEMETRY_EMIT_FAILED` (deliberately NOT a section-108 name --
        `loop_telemetry.emit()` refuses anything outside the nineteen, and a
        failure to observe is not one of the things being observed) and never
        propagates."""
        sess = getattr(self, "_loop_run", None)
        if not sess:
            return
        try:
            from . import loop_telemetry as _lt
            _lt.emit(self.store, event, loop_id=sess["loop_id"],
                     run_id=sess["run_id"], iteration=sess["iteration"], **payload)
            if event in _lt.TERMINAL_LOOP_EVENTS:
                sess["terminated"] = event
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "event": "LOOP_TELEMETRY_EMIT_FAILED",
                                  "attempted_event": event,
                                  "run_id": sess.get("run_id"),
                                  "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass

    def _begin_loop_telemetry(self, user_goal: str) -> None:
        """Open one loop session: LOOP_CREATED (only the first time this loop
        has ever run in this project), then LOOP_RESUMED (only when a prior
        session really ended in something other than LOOP_SUCCESS), then
        LOOP_STARTED.

        Both the CREATED/RESUMED decisions are READ out of the append-only
        event log by `loop_telemetry.previous_session_summary()` -- they are
        facts about what this project has already recorded, never a flag
        anybody sets. `goal` and `machine_checkable_done` come off the REAL
        `loop_contract.verification_closure_contract(self.cfg)`, so the
        drill-down's Goal field cannot drift from the contract that defines it."""
        from . import loop_telemetry as _lt
        from . import loop_contract as _lc
        try:
            prior = _lt.previous_session_summary(self.root)
        except Exception:
            prior = {}
        done, _total = _lt.gate_verified_stage_count(self.state.stages)
        self._loop_run = {
            "loop_id": _lt.VERIFICATION_CLOSURE_LOOP,
            "run_id": _lt.new_run_id(),
            "iteration": 0,
            "gain": done,
            "terminated": None,
        }
        contract_goal = ""
        machine_done = ""
        try:
            contract = _lc.verification_closure_contract(self.cfg)
            contract_goal = contract.goal
            machine_done = contract.machine_checkable_done
        except Exception:
            pass
        if not prior.get("ever_created"):
            self._emit_loop_event(
                "LOOP_CREATED", loop_state=_lc.LoopState.CREATED.value,
                goal=contract_goal, machine_checkable_done=machine_done,
                driver="dv_harness.engine.DVHarness.loop")
        if (prior.get("prior_session_count")
                and prior.get("last_terminal_event") != "LOOP_SUCCESS"):
            self._emit_loop_event(
                "LOOP_RESUMED", loop_state=_lc.LoopState.RESUMING.value,
                prior_session_count=prior.get("prior_session_count"),
                last_terminal_event=prior.get("last_terminal_event"),
                last_terminal_reason=prior.get("last_terminal_reason"),
                resume_condition=("this loop session continues a prior one that did not "
                                  "reach LOOP_SUCCESS; its state.json is the durable state "
                                  "it resumes from"))
        self._emit_loop_event(
            "LOOP_STARTED", loop_state=_lc.LoopState.RUNNING.value,
            stage=self.state.current_stage,
            goal=(user_goal or "")[:1000],
            contract_goal=contract_goal,
            machine_checkable_done=machine_done,
            trigger="dv_harness.engine.DVHarness.loop()",
            verified_gain_at_start=done)

    def _end_loop_telemetry(self, event: str, **payload: Any) -> None:
        """Close the session with EXACTLY ONE terminal event
        (`loop_telemetry.TERMINAL_LOOP_EVENTS`) and forget it, so a second
        `loop()` on the same harness object is a second session with its own
        `run_id` rather than more rows on the first one."""
        self._emit_loop_event(event, **payload)
        self._loop_run = None

    def _emit_loop_iteration_started(self, stage: str) -> None:
        sess = getattr(self, "_loop_run", None)
        if not sess:
            return
        sess["iteration"] = int(sess.get("iteration") or 0) + 1
        from . import loop_contract as _lc
        ss = self.state.stages.get(stage, {}) or {}
        self._emit_loop_event(
            "LOOP_ITERATION_STARTED", stage=stage,
            loop_state=_lc.LoopState.RUNNING.value,
            attempts=ss.get("attempts"),
            status_before=ss.get("status"))

    def _emit_loop_action_selected(self, stage: str) -> None:
        """Which action this iteration selected: run THIS graph node.

        `route` and `skills` are read off the real `GraphDefinition` node --
        the same object `_record_debug_loop_round()` reads `node.route` from --
        so the recorded action is the graph's, never a description of it."""
        node = None
        try:
            node = self.graph.nodes.get(stage) if self.graph is not None else None
        except Exception:
            node = None
        ss = self.state.stages.get(stage, {}) or {}
        self._emit_loop_event(
            "LOOP_ACTION_SELECTED", stage=stage,
            action="run_stage",
            route=getattr(node, "route", None),
            skills=list(getattr(node, "skills", None) or []),
            attempts=ss.get("attempts"))

    def _emit_loop_verify_completed(self, stage: str) -> None:
        """Section 87's verifier separation, recorded: WHICH gates judged this
        stage and what they concluded.

        The gate ids come from the real `gates.effective_stage_gates()` (the
        self-tuning overlay included, so the recorded verifier is the one that
        actually ran), and the verdict from the status `run_stage()` just
        persisted -- never from the agent's own text."""
        from .gates import effective_stage_gates
        ss = self.state.stages.get(stage, {}) or {}
        try:
            gate_ids = [g[0] for g in (effective_stage_gates(stage, self.root) or [])]
        except Exception:
            gate_ids = []
        self._emit_loop_event(
            "LOOP_VERIFY_COMPLETED", stage=stage,
            status=ss.get("status"),
            verdict=ss.get("status"),
            gate_ids=gate_ids, gate_count=len(gate_ids),
            verifier=("dv_harness.gates.evaluate_stage_evidence() over "
                      "effective_stage_gates(); the producing agent does not judge "
                      "its own output"),
            blocking_reason=(ss.get("blocking_reason") or "")[:600],
            attempts=ss.get("attempts"))

    def _emit_loop_progress(self, stage: str) -> None:
        """Section 107's Verified Gain column, and section 110's LOOP-AT-26.

        The metric is `loop_telemetry.GATE_VERIFIED_STAGE_METRIC` -- stages
        whose gates accepted their evidence -- which is the only per-iteration
        progress signal this engine really verifies. An iteration that ran a
        stage and moved it by zero is LOOP_NO_PROGRESS: artifact churn without
        verified gain. The delta is against the previous iteration of THIS
        session, whose baseline was read at `_begin_loop_telemetry()`."""
        sess = getattr(self, "_loop_run", None)
        if not sess:
            return
        from . import loop_telemetry as _lt
        from . import loop_contract as _lc
        gain = _lt.verified_gain(self.state.stages, previous=sess.get("gain"))
        sess["gain"] = gain["value"]
        self._emit_loop_event("LOOP_PROGRESS_UPDATED", stage=stage, **gain)
        delta = gain.get("delta")
        if delta is None:
            return
        if delta > 0:
            self._emit_loop_event(
                "LOOP_CONVERGING", stage=stage,
                loop_state=_lc.LoopState.CONVERGING.value,
                metric=gain["metric"], delta=delta, value=gain["value"],
                total=gain["total"])
        elif delta == 0:
            self._emit_loop_event(
                "LOOP_NO_PROGRESS", stage=stage,
                metric=gain["metric"], delta=delta, value=gain["value"],
                reason=("this iteration ran a stage and no additional stage reached a "
                        "gate-verified status -- artifact churn without verified gain "
                        "(section 110, LOOP-AT-26)"))

    def _emit_loop_retry_scheduled(self, stage: str, max_retry: int,
                                   classification: Optional[Dict[str, Any]]) -> None:
        """LOOP_RETRY_SCHEDULED at the one place `loop()` schedules a retry,
        plus LOOP_BUDGET_WARNING when this is the LAST one the per-node budget
        allows -- the warning has to precede exhaustion to be worth anything,
        and `attempts_remaining == 0` is the real, checkable condition for it
        (the next failure takes the `attempts > max_retry` branch)."""
        ss = self.state.stages.get(stage, {}) or {}
        attempts = int(ss.get("attempts") or 0)
        remaining = int(max_retry) - attempts
        from . import loop_contract as _lc
        self._emit_loop_event(
            "LOOP_RETRY_SCHEDULED", stage=stage,
            loop_state=_lc.LoopState.RETRY_WAIT.value,
            attempts=attempts, max_stage_retries=max_retry,
            attempts_remaining=max(remaining, 0),
            failure_type=(classification or {}).get("failure_type"),
            failure_signature=(classification or {}).get("signature"),
            failure_signature_repeats=(classification or {}).get("repeats"),
            backoff=("none -- engine.loop() retries immediately; "
                     "policy.max_stage_retries is the only bound"))
        if remaining <= 0:
            self._emit_loop_event(
                "LOOP_BUDGET_WARNING", stage=stage,
                attempts=attempts, max_stage_retries=max_retry,
                attempts_remaining=0,
                reason=(f"stage {stage} has spent {attempts} of "
                        f"{max_retry} allowed retries: the next failure exhausts "
                        f"policy.max_stage_retries and routes onto the graph's FAIL edge"))

    def _classify_loop_convergence_for_telemetry(self, stage: str) -> Optional[Dict[str, Any]]:
        """Fire LOOP-2's convergence/plateau/oscillation classifier on the real
        engine path, at the one low-frequency point where it is worth the read.

        LOOP-2 built `loop_convergence.classify_loop_convergence()` and
        disclosed that no `run_stage()`/`advance()` call site invoked it. Called
        HERE -- once per retry exhaustion, not once per iteration -- because
        that is where the loop has just failed to make progress and where the
        question "is this a plateau, or an oscillation, or just a hard stage"
        is actually being asked. It opens the evidence database READ-ONLY (or
        not at all, when none exists) exactly as `trend_report()` does, writes
        nothing, escalates nothing, and returns None rather than a fabricated
        verdict on any failure."""
        try:
            from . import loop_convergence as _lcv
            history = (self.blackboard.read_debug_loop_history() or {}).get("entries") or []
            report = _lcv.classify_loop_convergence(
                self.root, cfg=self.cfg, debug_loop_entries=history)
            return report.to_dict()
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "stage": stage,
                                  "event": "LOOP_CONVERGENCE_CLASSIFY_FAILED",
                                  "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass
            return None

    def _classify_plan_quality_shape_for_telemetry(self, stage: str) -> Optional[Dict[str, Any]]:
        """plan_quality_feedback gap-close (2026-09-07, REACHED-not-WIRED
        closure): fires the real, read-only
        plan_quality_feedback.aggregate_stage_sequence_shapes() classifier
        on the real engine path, modeled byte-for-byte on
        _classify_loop_convergence_for_telemetry() immediately above --
        called at the SAME low-frequency point, retry exhaustion, where
        "does this run's graph-traversal SHAPE have a real history of
        thrashing" is genuinely worth asking. It reads only
        loop_telemetry.read_loop_telemetry()-backed data (no state.json,
        no StateStore.load(), no other file opened), writes a free-form
        PLAN_QUALITY_SHAPE_CLASSIFIED/PLAN_QUALITY_SHAPE_CLASSIFY_FAILED
        event via self.store.event() -- deliberately NOT routed through
        loop_telemetry.emit()'s closed nineteen-name section-108
        vocabulary, since a plan-quality shape classification is not one
        of those named event types and widening that vocabulary is a
        separate, larger change this hook does not make -- mints no
        verdict, touches no gate, and returns None rather than a
        fabricated result on any failure.

        Deliberately reads across the WHOLE recorded telemetry history
        (no run_id filter passed to aggregate_stage_sequence_shapes()):
        the question this module answers ("has a session taking THIS SAME
        graph-traversal shape thrashed before") is cross-session by
        construction -- filtering to only the current session's own
        run_id would leave nothing to compare it against. The emitted
        event still names the CURRENT session's own shape (and that
        shape's real classified status), when the current run_id is
        findable among the aggregated shapes, purely as a convenience for
        a reader of this one event -- the full per-shape breakdown is
        always available via the real CLI/API this module already ships."""
        try:
            from . import plan_quality_feedback as _pqf
            report = _pqf.aggregate_stage_sequence_shapes(self.root)
            payload = report.to_dict()
            sess = getattr(self, "_loop_run", None)
            current_run_id = sess.get("run_id") if sess else None
            current_shape = None
            if current_run_id:
                for shape_row in payload.get("shapes") or []:
                    if current_run_id in (shape_row.get("run_ids") or []):
                        current_shape = {"shape": shape_row.get("shape"),
                                         "status": shape_row.get("status"),
                                         "reason": shape_row.get("reason")}
                        break
            self.store.event({
                "ts": now(), "stage": stage, "event": "PLAN_QUALITY_SHAPE_CLASSIFIED",
                "available": payload.get("available"),
                "sessions_examined": payload.get("sessions_examined"),
                "status_counts": payload.get("status_counts"),
                "current_run_shape": current_shape,
            })
            return payload
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "stage": stage,
                                  "event": "PLAN_QUALITY_SHAPE_CLASSIFY_FAILED",
                                  "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass
            return None

    def _emit_loop_convergence_events(self, stage: str,
                                      report: Optional[Dict[str, Any]]) -> None:
        """Turn ONE real convergence report into its section-108 event.

        Every event carries `metric: coverage_percent`, which is what separates
        it from `_emit_loop_progress()`'s per-iteration gate-verified-stage
        verdict: two different real metrics, never one pretending to be the
        other. An UNKNOWN verdict emits NOTHING -- the classifier ran and could
        not conclude, and recording that as a finding is the unearned claim
        `PLATEAU_NOT_EVALUATED` exists to prevent."""
        if not report:
            return
        from . import loop_convergence as _lcv
        from . import loop_contract as _lc
        verdict = report.get("verdict")
        common = {"stage": stage, "metric": _lcv.COVERAGE_PERCENT_METRIC,
                  "verdict": verdict, "convergence": report}
        if verdict == _lcv.PLATEAU:
            self._emit_loop_event("LOOP_PLATEAU_DETECTED",
                                  loop_state=_lc.LoopState.PLATEAU.value, **common)
        elif verdict == _lcv.OSCILLATING:
            self._emit_loop_event("LOOP_OSCILLATION_DETECTED",
                                  loop_state=_lc.LoopState.OSCILLATING.value,
                                  oscillation=report.get("oscillation"), **common)
        elif verdict in (_lcv.NO_PROGRESS, _lcv.REGRESSION):
            # Section 108 names no regression event. A DECLINING series is
            # reported as LOOP_NO_PROGRESS rather than as LOOP_CONVERGING --
            # the nearest true statement of the two -- and the real verdict
            # travels on the payload, so nothing is collapsed or hidden.
            self._emit_loop_event(
                "LOOP_NO_PROGRESS",
                reason=("the cross-run coverage series did not advance over this window "
                        f"(loop_convergence verdict: {verdict})"),
                **common)
        elif verdict in (_lcv.CONVERGING, _lcv.SLOW_CONVERGENCE):
            self._emit_loop_event("LOOP_CONVERGING", **common)

    # ---- LOOP-3: unified loop budget + failure taxonomy + circuit breaker --
    #
    # (LOOP_ENGINEERING sections 91/92/93 -- see dv_harness/loop_budget.py's
    # module docstring for what was verified missing and why these three are
    # one mechanism.) Everything below is deliberately BEST-EFFORT and
    # RECORD-FIRST: the classification, the budget spend and the breaker trip
    # are computed and written on every real retry-exhaustion this engine
    # already reaches, while the two things that would CHANGE this engine's
    # existing behaviour -- refusing a retry the classifier calls useless, and
    # deferring low-value work under license pressure -- are opt-in config
    # (`loop_budget.enforce_retry_policy` / `.defer_low_value_under_pressure`),
    # for the same reason `require_tier` and `probe_resources` default off:
    # either would otherwise silently shorten every existing project's
    # policy.max_stage_retries on the strength of a classifier nobody asked for.

    def _loop_budget_engine(self):
        """The run's one `loop_budget.BudgetEngine`, built from THIS project's
        real config, so every limit and every "nothing bounds this, because..."
        reason is read from the keys that really decide them rather than
        retyped. Re-read from disk each time rather than cached: `dv-harness
        loop-budget reset` and `... breaker-reset` are real out-of-process
        actions, and a cached ledger would keep spending against a budget -- or
        keep blocking on a breaker -- a human already cleared."""
        from . import loop_budget as _lb
        return _lb.BudgetEngine(self.root, self.cfg)

    def _classify_stage_failure(self, stage: str) -> Optional[Dict[str, Any]]:
        """Classify THIS stage's current failure into section 93's taxonomy
        from evidence already on disk, and record the consecutive-repeat count
        of its normalized signature on the stage state.

        Reads `state.json`'s own `blocking_reason` (which run_stage() fills
        with either `"<verdict>: <gate reasons>"` or the adapter's stderr) plus
        the FAILURE_RECOVERY `failure_attribution` boundary trace when one
        exists -- never agent prose about what went wrong, only the fields the
        gates and the adapter themselves produced.

        `failure_signature_repeats` is what turns "this failed" into "this
        failed IDENTICALLY again", which is section 93's own example of a
        useless retry and the circuit breaker's REPEATED_IDENTICAL_FAILURE
        trigger."""
        from . import loop_budget as _lb
        ss = self.state.stages.get(stage, {})
        boundary_trace = None
        try:
            fr = self.state.stages.get(Stage.FAILURE_RECOVERY.value, {}) or {}
            blocks = extract_evidence_blocks(fr.get("last_message") or "")
            boundary_trace = (blocks.get("failure_attribution") or {}).get("boundary_trace")
        except Exception:
            boundary_trace = None
        conf = _lb.resolve_config(self.cfg)
        prefixes = tuple(conf.get("vip_component_prefixes")
                         or _lb.DEFAULT_VIP_COMPONENT_PREFIXES)
        cls = _lb.classify_failure(
            ss.get("blocking_reason") or "",
            adapter_ok=(ss.get("status") != Status.FAIL.value),
            boundary_trace=boundary_trace,
            vip_component_prefixes=prefixes)
        previous = ss.get("failure_signature")
        repeats = int(ss.get("failure_signature_repeats") or 0)
        repeats = repeats + 1 if previous == cls.signature else 1
        ss["failure_signature"] = cls.signature
        ss["failure_signature_repeats"] = repeats
        ss["failure_type"] = cls.failure_type
        payload = cls.to_dict()
        payload["repeats"] = repeats
        return payload

    def _spend_retry_exhaustion_budget(self, stage: str,
                                       classification: Optional[Dict[str, Any]]
                                       ) -> Optional[Dict[str, Any]]:
        """Record this retry exhaustion against the UNIFIED ledger and, when a
        declared budget has actually run out, trip section 93's circuit
        breaker.

        The per-node retry budget itself is unchanged: `policy.max_stage_retries`
        is still spent by loop()'s own `ss["attempts"] <= max_retry` test and
        still routes onto the graph's FAIL edge. What this adds is the RUN-WIDE
        view section 91 asks for -- `max_retries` and `max_iterations` are
        spent here so "what has this run spent, against which limit" becomes
        answerable -- plus the breaker, which can only trip on a limit a project
        DECLARED (`loop_budget.limits.*`, empty by default) or on an identical
        repeat past a threshold it declared. Nothing here fires on a default
        configuration, which is exactly why turning it on is a project's
        decision rather than this engine's.

        Best-effort, mirroring every sibling `_record_*`: a budget-bookkeeping
        failure must never turn an already-computed routing decision into a
        crash."""
        from . import loop_budget as _lb
        try:
            engine = self._loop_budget_engine()
            ss = self.state.stages.get(stage, {})
            engine.spend("max_retries", float(ss.get("attempts") or 1),
                         note=f"stage {stage} retry budget spent", save=False)
            engine.spend("max_iterations", 1.0, note=f"stage {stage}", save=False)
            engine.save()
            exhausted = engine.exhausted_dimensions()
            payload: Dict[str, Any] = {
                "exhausted": exhausted,
                "loop_state": engine.loop_state(),
                "dimensions": {n: s.to_dict() for n, s in engine.states.items()
                               if s.enforced},
            }
            conf = _lb.resolve_config(self.cfg)
            if exhausted:
                engine.trip_breaker(
                    "BUDGET_EXHAUSTION",
                    f"declared loop budget(s) exhausted at stage {stage}: {exhausted}",
                    evidence={"stage": stage, "dimensions": payload["dimensions"]})
                payload["breaker"] = engine.breaker_state()
            threshold = conf.get("repeated_identical_failure_threshold")
            repeats = int((classification or {}).get("repeats") or 0)
            if threshold is not None and repeats >= int(threshold):
                engine.trip_breaker(
                    "REPEATED_IDENTICAL_FAILURE",
                    f"stage {stage} produced the same normalized failure signature on "
                    f"{repeats} consecutive attempts (threshold {threshold})",
                    evidence={"stage": stage, "classification": classification})
                payload["breaker"] = engine.breaker_state()
            # OSCILLATION, computed by loop_contract's OWN detector over the
            # `debug_loop_history` entries _record_debug_loop_round() wrote one
            # line before this call -- CALLED, never re-derived, so there is one
            # definition of an oscillation fingerprint in this codebase.
            # Opt-in with a real reason: loop() currently routes an oscillating
            # stage onto its graph FAIL edge, and sections 88-90's RESPONSE half
            # is explicitly not built, so tripping here by default would change
            # routing this harness has not decided to change.
            if conf.get("trip_on_oscillation"):
                from . import loop_contract as _lc
                history = (self.blackboard.read_debug_loop_history() or {}).get("entries") or []
                verdict = _lc.detect_oscillation_from_debug_loop_history(history)
                payload["oscillation"] = verdict
                if verdict.get("oscillating"):
                    engine.trip_breaker(
                        "OSCILLATION",
                        f"repeated (failing_stage, target_fail_edge) fingerprint(s) in the "
                        f"Blackboard debug_loop_history: "
                        f"{sorted(verdict.get('repeated_fingerprints') or {})}",
                        evidence={"stage": stage, "oscillation": verdict})
                    payload["breaker"] = engine.breaker_state()
            self.store.event({"ts": now(), "stage": stage, "event": "LOOP_BUDGET_SPENT",
                              "classification": classification, **payload})
            return payload
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "stage": stage,
                                  "event": "LOOP_BUDGET_SPEND_FAILED",
                                  "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass
            return None

    def _retry_refused_by_failure_evidence(self, stage: str,
                                           classification: Optional[Dict[str, Any]]
                                           ) -> Optional[Dict[str, Any]]:
        """Section 93's "Retry only when evidence supports it".

        Returns the refusing `RetryDecision` payload when another attempt must
        NOT be spent, or None to leave loop()'s existing
        `ss["attempts"] <= max_retry` test as the only thing deciding -- which
        is what happens on every default configuration. It can only ever REFUSE
        an attempt, never grant one past the existing budget."""
        from . import loop_budget as _lb
        if not classification:
            return None
        try:
            cls = _lb.FailureClassification(
                failure_type=classification.get("failure_type", _lb.FailureType.UNKNOWN.value),
                retryable=bool(classification.get("retryable", True)),
                rule=classification.get("rule", ""),
                signature=classification.get("signature", ""),
                evidence=classification.get("evidence") or {})
            decision = _lb.decide_retry(cls,
                                        repeats=int(classification.get("repeats") or 1),
                                        cfg=self.cfg)
            if decision.retry:
                return None
            payload = decision.to_dict()
            self.store.event({"ts": now(), "stage": stage, "event": "LOOP_RETRY_REFUSED",
                              **payload})
            return payload
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "stage": stage,
                                  "event": "LOOP_RETRY_DECISION_FAILED",
                                  "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass
            return None

    def _circuit_breaker_gate(self, stage: str) -> bool:
        """Section 93's BLOCK half, checked at the top of every loop() cycle
        beside the Human Override checks.

        Returns True when the breaker is OPEN and this project has left
        `loop_budget.breaker_blocks_loop` on (the default), meaning no NEW loop
        action may be attempted. The stage is marked BLOCKED with the real trip
        evidence in `blocking_reason`, so the stop is never unexplained, and the
        only way back is a recorded recovery condition
        (`dv-harness loop-budget breaker-reset --reason ... --by ...`).

        It authorizes nothing and weakens nothing: a breaker can only STOP
        work. Every approval gate that stood before it still stands.
        Best-effort -- an unreadable ledger leaves the loop running normally
        rather than stranding it in a state it cannot get out of."""
        from . import loop_budget as _lb
        try:
            conf = _lb.resolve_config(self.cfg)
            if not conf.get("breaker_blocks_loop", True):
                return False
            engine = self._loop_budget_engine()
            if not engine.breaker_open():
                return False
            reason = engine.blocking_reason()
            ss = self.state.stages[stage]
            ss["status"] = Status.BLOCKED.value
            ss["blocking_reason"] = reason[:2000]
            self.state.overall_status = Status.BLOCKED.value
            self.store.save(self.state)
            self.store.event({"ts": now(), "stage": stage,
                              "event": "CIRCUIT_BREAKER_BLOCKED",
                              "breaker": engine.breaker_state(),
                              "exhausted": engine.exhausted_dimensions()})
            print(f"[dv-harness] {reason}")
            return True
        except Exception as e:
            print(f"[dv-harness] circuit-breaker check failed (continuing normally): {e}")
            return False

    def _resource_priority_decision(self, stage: str, skills: List[str],
                                    checks: List[Any]) -> Optional[Dict[str, Any]]:
        """Section 92's PROCEED / PROCEED_CRITICAL / DEFER decision for one
        stage, measured from the preflight `CheckOutcome`s this run just
        produced.

        `consumes_scarce_resource` is `bool(skills)` -- the execution-layer
        skills THIS stage's own graph node declares, the same
        `EXECUTION_PREFLIGHT_SKILLS` discriminator that armed this gate in the
        first place. A stage that consumes none of the scarce resource is never
        deferred for it, because deferring it would delay the project and free
        nothing.

        Returns None (never a fabricated decision) if anything goes wrong;
        measuring must never break a stage that already preflighted clean."""
        from . import loop_budget as _lb
        try:
            conf = _lb.resolve_config(self.cfg)
            pressure = _lb.measure_resource_pressure(self.cfg, checks=list(checks or []))
            decision = _lb.prioritize_stage(
                stage, pressure, consumes_scarce_resource=bool(skills),
                critical_stages=tuple(conf.get("critical_stages")
                                      or _lb.DEFAULT_CRITICAL_STAGES))
            payload = decision.to_dict()
            payload["pressure_detail"] = pressure.to_dict()
            return payload
        except Exception:
            return None

    def _defer_stage_under_resource_pressure(self, stage: str, skills: List[str],
                                             priority: Optional[Dict[str, Any]]
                                             ) -> Optional[AgentResult]:
        """Act on a DEFER decision, when and only when this project opted in.

        Parks on WAIT_USER for _degraded_gate()'s and
        _execution_preflight_gate()'s own stated reason: loop() reads
        ss["status"] and its fallthrough is an unconditional advance(), so a
        deferred stage must park on a status loop() already stops cleanly on
        rather than be advanced as though it had passed. The real measured
        pressure is carried in blocking_reason, so the park is never
        unexplained."""
        from . import loop_budget as _lb
        try:
            if not priority or priority.get("decision") != _lb.PRIORITY_DEFER:
                return None
            conf = _lb.resolve_config(self.cfg)
            if not conf.get("defer_low_value_under_pressure", False):
                return None
            reason = (f"EXECUTION_DEFERRED_UNDER_RESOURCE_PRESSURE: {priority.get('reason', '')} "
                      f"No agent dispatched. Re-run when the measured pressure clears, or set "
                      f"loop_budget.defer_low_value_under_pressure=false to proceed anyway.")
            ss = self.state.stages[stage]
            ss["status"] = Status.WAIT_USER.value
            ss["blocking_reason"] = reason[:2000]
            self.state.overall_status = Status.WAIT_USER.value
            self.store.save(self.state)
            self.store.event({"ts": now(), "stage": stage,
                              "event": "EXECUTION_DEFERRED_UNDER_RESOURCE_PRESSURE",
                              "execution_skills": skills, "resource_priority": priority})
            print(f"[dv-harness] {reason}")
            return AgentResult(ok=False, text=reason,
                               raw={"deferred": True, "stage": stage, **priority},
                               session_id=None)
        except Exception as e:
            print(f"[dv-harness] resource-priority deferral check failed "
                  f"(continuing normally): {e}")
            return None

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

    def _escalate_unreachable_coverage_holes(self, text: Optional[str]) -> List[Dict[str, Any]]:
        """Turn every UNREACHABLE_STIMULUS coverage hole in a COVERAGE_CLOSURE
        response into a REAL Tier-3 question-queue entry owned by the
        designer (2026-09-04, Section 3 item 3b -- see
        coverage_analysis.escalate_unreachable_holes()'s own docstring for
        the seed-attempt precedence rule and why the queue is the right
        destination).

        Best-effort and never raising, exactly like every other side effect
        around this call site: an escalation-store problem must not be the
        reason a stage cannot be judged. The gate that consumes this fails
        the hole honestly if the question really did not land."""
        if not text:
            return []
        try:
            from .coverage_analysis import escalate_unreachable_holes
            blocks = extract_evidence_blocks(text) or {}
            payload = blocks.get("coverage_hole_regeneration_gate")
            holes = payload.get("coverage_holes") if isinstance(payload, dict) else None
            if not holes:
                return []
            return escalate_unreachable_holes(self.root, holes, cfg=self.cfg)
        except Exception as e:  # noqa: BLE001
            print(f"[dv-harness] coverage-hole escalation failed (continuing): {e}")
            return []

    def _computed_regression_selection(self) -> Optional[Dict[str, Any]]:
        """REAL, harness-computed RTL-diff-driven regression selection for
        Stage.REGRESSION_SELECT (2026-09-04, Section 3 item 3a).

        Before this existed, REGRESSION_SELECT was pure agent self-report:
        prompts.py asked the agent to hand-fill targeted/dependency/safety/
        mandatory_signoff, and regression_selection_completeness_gate.py
        only checked that the resulting JSON had non-empty categories. No
        code anywhere computed an impact scope from a diff -- the one real
        `git diff` call in this engine (`_git_modified_files()`) fed only
        the protocol router. This method is the missing computation; see
        dv_harness/change_impact.py's module docstring for the full data
        lineage (real git diff -> real rtl_modules parse rows -> real
        .dv-harness/requirements.csv traceability registry).

        BASE SHA (never guessed silently): `config.json`'s
        `regression.change_impact_base_sha` when a project declares one,
        else `HEAD~1`. A repo with no HEAD~1 (a single-commit or non-git
        checkout) produces an honest UNKNOWN_BASE/NO_GIT diff status that
        change_impact.py itself converts into LOW confidence +
        expand_to_full_regression -- i.e. "we could not narrow, so do not
        narrow", never a fabricated narrow selection.

        Returns None (and the stage keeps its previous behavior exactly)
        only if the computation itself raises -- wrapped like every other
        best-effort side effect in this file, because a selection helper
        must never be the reason a stage cannot run at all.
        """
        try:
            from . import change_impact
            block = self.cfg.get(change_impact.CONFIG_KEY) or {}
            base = block.get("change_impact_base_sha") or "HEAD~1"
            head = block.get("change_impact_head_sha") or "HEAD"
            return change_impact.compute_and_write(
                self.root, base_sha=str(base), head_sha=str(head), cfg=self.cfg)
        except Exception:
            return None

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
        # DEGRADED must be an EXPLICIT, OBSERVABLE state, not a silent
        # internal branch (2026-09-03 user spec) -- folded in here so
        # `dv-harness status` shows it with no CLI change, exactly the way
        # paused/takeover_active above are surfaced. Best-effort: an
        # unreadable degradation.json degrades to "NORMAL, nothing recorded"
        # rather than making `status` itself fail.
        try:
            from . import degradation
            degraded_detail = degradation.describe(self.root)
        except Exception:
            degraded_detail = {"mode": "NORMAL", "degraded": False, "triggers": [],
                                "trigger_details": {}, "entered_at": None, "cleared_at": None,
                                "adapter_failure_streak": 0, "degraded_cycles": 0}
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
            # 降級路徑 (2026-09-03): DEGRADED means the harness is still
            # collecting/persisting real data but is deliberately making no
            # judgment-requiring stage transition until the named trigger(s)
            # clear. `degraded_triggers` names which of the three real
            # conditions is live; see dv_harness/degradation.py.
            "operation_mode": degraded_detail["mode"],
            "degraded": degraded_detail["degraded"],
            "degraded_triggers": degraded_detail["triggers"],
            "degraded_trigger_details": degraded_detail["trigger_details"],
            "degraded_since": degraded_detail["entered_at"],
            "degraded_cycles": degraded_detail["degraded_cycles"],
            "adapter_failure_streak": degraded_detail["adapter_failure_streak"],
            # WHICH of the three triggers can actually fire here (2026-09-04).
            # The adapter trigger is always live; the license-full and
            # farm-congested ones need a real probe transport, and this names
            # the one that was resolved plus the evidence for it. `available`
            # false with resolved "none" is the honest "those two triggers
            # cannot fire on this machine" answer -- previously that was the
            # silent, undiscoverable default everywhere.
            "degraded_probe_transport": self.degradation_transport.to_dict()
            if getattr(self, "degradation_transport", None) is not None else None,
            "degraded_resource_triggers_armed": bool(
                self._degradation_cfg().get("probe_resources", False)
                or self.degradation_runner is not None),
            "dry_run_mode": bool(self._dry_run_cfg().get("enabled", False)),
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

    @staticmethod
    def _engineering_record_protocol(resolved_protocol: Optional[str],
                                     block_protocol: Optional[str]) -> Optional[str]:
        """The `protocol` an Engineering-Memory-tier record is written with --
        the dedup/confirmation KEY, not a decorative label (2026-09-04,
        gap-close-obsidian-memory Phase 4+5).

        memory.find_confirming_engineering_match() keys "an
        independent later run re-derived the SAME conclusion" on
        (protocol, root_cause), and MemoryGC.confirm() -- the only authorized
        writer of confirmation_count, i.e. the only way
        promote_to_organizational()'s third gate can ever be cleared -- fires
        only on a match. Both of this class's Engineering-tier writers used to
        take `protocol` straight off the gate's evidence block, but neither
        experience_knowledge_gate's nor root_cause_evidence_gate's
        JUDGMENT_FIELDS list (gates.py) includes `protocol`, so no gate ever
        required or judged it: in the real on-disk store it landed None on 30
        of 31 engineering records, the match returned None every time, and
        every re-derivation minted a fresh record instead of a confirmation.
        The Organizational tier was therefore unreachable by its own intended
        organic route.

        resolve_protocol()'s value wins because it is the only one that is
        both real and STABLE: it is a canonical, normalized name
        (protocol_router.PRIMARY_ROUTES' key, e.g. "usb") derived from this
        run's own evidence, so two independent runs of the same investigation
        produce the same key. The evidence block's value is unjudged agent
        free text whose casing/spelling can drift between runs, which is
        exactly what an equality-matched dedup key must not do -- it stays
        only as the fallback for a run whose protocol genuinely did not
        resolve (resolve_protocol -> UNRESOLVED_NEEDS_ROUTING_QUESTION, or no
        graph node at all). Never a fabricated placeholder: both sources
        absent still yields None, and a None-protocol record simply does not
        participate in dedup, exactly as before.

        Keying on the canonical protocol cannot over-confirm unrelated
        findings: the match additionally requires an exact (case-insensitive)
        `root_cause` equality, so a hit means the same root cause was
        re-derived within the same protocol -- which is the definition of a
        confirmation."""
        for candidate in (resolved_protocol, block_protocol):
            if str(candidate or "").strip():
                return str(candidate).strip()
        return None

    def _promote_experience_knowledge(self, stage: str, evidence_blocks: dict,
                                       resolved_protocol: Optional[str] = None,
                                       producing_agent_profile: Optional[str] = None) -> None:
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
        second time (must-fix #1 from adversarial verify).

        `resolved_protocol` (2026-09-04, gap-close-obsidian-memory Phase 4+5)
        is THIS run's canonical protocol from
        protocol_router.resolve_protocol() -- the same value run_stage()
        already threads into InnerReactLoop -- and it takes precedence over
        the evidence block's own `protocol` when building the record. See
        _engineering_record_protocol() for why that precedence is what makes
        the Engineering -> Organizational confirmation path reachable at
        all.

        `producing_agent_profile` (2026-09-07, agent_profile_track_record
        gap-close) is the SAME `route_info["agent"]`/`_resolved_agent_name`
        value run_stage()'s own per-agent stage-profiler attribution already
        resolves for this exact attempt -- threaded through here verbatim,
        never re-derived, and stored on the record via memory.py's new
        optional `producing_agent_profile` field. Reporting only: nothing in
        this method (or anywhere else in this pass) consumes that field to
        change dispatch/routing/scoring."""
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
            "protocol": self._engineering_record_protocol(resolved_protocol,
                                                          block.get("protocol")),
            "producing_agent_profile": producing_agent_profile,
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

        # THE GAP THIS CLOSES (2026-09-04, gap-close-ai-engine #7 "5-Level
        # Memory Engine"), confirmed against the real on-disk store before it
        # was written: promote_to_organizational()'s third gate
        # (confirmation_count >= ORGANIZATIONAL_MIN_CONFIRMATIONS) can ONLY be
        # cleared by MemoryGC.confirm(), which _add_or_confirm_engineering()
        # fires when a write matches an ACTIVE engineering record on
        # (protocol, root_cause) -- route_and_store() reports that as
        # `confirmed_existing`. THIS method is one of the two real production
        # writers that can cause it, but only the OTHER one
        # (_promote_verified_fix_knowledge, RE_AUDIT/verified_fix) evaluated
        # promotion afterwards. So the exact moment gate 3 newly became
        # clearable on this path -- an EXPERT_FEEDBACK_LOOP PASS independently
        # re-deriving a root cause a previous RE_AUDIT already recorded, which
        # is precisely the "second independent run" CLAUDE.md's confirmation
        # rule is written around -- had nothing listening. The Organizational
        # tier was reachable from here only if a human remembered to run
        # `dv-harness memory promote` by hand. Reuses the existing
        # promote_to_organizational() mechanism verbatim; adds no second gate,
        # no second scoring system and no new store.
        #
        # Gated on `confirmed_existing` deliberately: a freshly-minted record
        # has confirmation_count 0 and could only ever produce an
        # INSUFFICIENT_CONFIRMATION event, so evaluating it would add noise,
        # not coverage.
        #
        # The confidence inputs are the ones REALLY persisted on the confirmed
        # record by the run that first established it (see
        # _promote_verified_fix_knowledge()), re-read here from the durable
        # store. They are not re-derived from THIS stage's evidence, because
        # experience_knowledge_gate is registered only on EXPERT_FEEDBACK_LOOP
        # (gates.STAGE_GATES) and that stage carries no root_cause_evidence_
        # gate, so this call site genuinely has no root_cause evidence block
        # to score. A record with none persisted is evaluated as
        # NO_CONFIDENCE_INPUTS rather than scored on invented counts.
        #
        # This cannot become a forgery surface on its own: gate 1 re-reads the
        # source record's verification block and gate 3 re-reads its
        # store-owned confirmation_count, both of which
        # organizational_admission_gate() independently re-checks at the write
        # boundary, so persisted confidence inputs alone promote nothing.
        if promotion.get("destination") == "ENGINEERING_MEMORY" and promotion.get("confirmed_existing"):
            confirmed = None
            try:
                from .memory import MemoryStore  # local import, same idiom as
                                                  # _gather_stage_context below
                confirmed = MemoryStore(self.root).get(promotion["memory_id"])
            except Exception:
                confirmed = None
            inputs = (confirmed or {}).get("confidence_inputs")
            self._evaluate_organizational_promotion(
                stage, promotion["memory_id"],
                inputs if isinstance(inputs, dict) else None)

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
        not re-validate, only persists.

        HUMAN-APPROVAL HARD-STOP (2026-09-04, mechanism #8 Qualification/
        Signoff Engine re-audit follow-up). run_stage()'s
        `if verdict == "PASS":` side-effect block runs on GATE VERDICT
        alone -- and it runs AFTER the branch that downgrades a fully
        gate-verified SIGNOFF to WAIT_USER when no `dv-harness approve
        SIGNOFF` is on record ("PROMOTION_READINESS/SIGNOFF passing their
        own automated gates is not the same thing as a human sign-off",
        same 'LSF DONE != DV PASS' principle one level up). So without the
        status re-check below, a signoff still waiting on a human already
        wrote its subsystem into the REAL runtime registry as
        PRODUCTION_QUALIFIED. _export_signoff_bundle() immediately below
        re-checks the recorded status for exactly this reason and says so
        in its own docstring; this method -- the ONLY writer of that
        registry file -- did not.

        That file is not a log, which is why the check belongs here rather
        than only at the call site: environment_mode_router.
        read_registered_subsystem_entries() feeds it to
        soc_environment_composer.compose_soc_environment(), STAGE_GATES
        ["SYSTEM_LEVEL"]'s system_level_validator cross-checks agent claims
        against it through its harness-supplied --registered ContextFlag,
        and signoff_export.read_signoff_stage_status() reports its mere
        presence as "independent corroboration" of a real SIGNOFF PASS --
        so an entry written past the approval hold is a false corroboration
        of the very approval it skipped. Reads self.state.stages (the same
        dict run_stage() just wrote `ss` into), not the on-disk state.json,
        because the final store.save() happens well after this block.
        """
        gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
        if "subsystem_environment_registration_gate" not in gate_ids:
            return
        if self.state.stages.get(stage, {}).get("status") != Status.PASS.value:
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

    def _refresh_requirement_vplan_center_snapshot(self, stage: str, evidence_blocks: dict) -> None:
        """Requirement/vPlan Center auto-population (2026-09-07, GUI/
        dashboard auto-population audit, tasks 1+2). dashboard.
        _read_requirement_vplan_center_state() already renders a real
        Requirement/vPlan Center card off two conventional files --
        .dv-harness/requirement_vplan/requirements.json and .../vplan.json
        -- but before this, nothing in the harness ever WROTE either one
        (a repo-wide grep for those two path strings found only
        dashboard.py, the reader). Both halves are closed here, mirroring
        _refresh_declared_subsystem_topics's own discipline exactly: never
        GENERATE a fact -- only mirror one a real gate-verified PASS
        already produced -- wrapped in try/except so a refresh can never
        turn an already-earned stage PASS into a failure, with one
        REQUIREMENT_VPLAN_CENTER_REFRESH* event recorded per attempt
        (success or failure) so the audit trail can answer "was this ever
        produced, and if not why" from real events rather than the file's
        mere absence.

        requirements.json (REQUIREMENTS_TRACEABILITY stage):
        evidence_blocks["spec_to_vplan_requirement_quality_gate"] is,
        byte-for-byte, the same `{"requirements": [...]}` dict
        gates.run_gate() already JSON-dumped verbatim to the temp file
        that gate script's own `d.get('requirements', [])` just read back
        and PASSED against (tools/verification_flow/
        spec_to_vplan_requirement_quality_gate.py:99-104) -- and it is
        EXACTLY the "bare list, or {'requirements': [...]}" shape
        dashboard.py's own reader already expects. A verbatim mirror; no
        reshaping needed.

        vplan.json (VPLAN stage): evidence_blocks["spec_to_vplan_quality_
        gate"] carries a real `vplan_items: [{"vplan_id", "traces_to"}]`
        array (tools/verification_flow/spec_to_vplan_quality_gate.py's own
        declared evidence shape). vplan_artifact.validate_vplan_row()
        requires only a non-empty `id` -- every other field is optional --
        so each item is rewritten with the minimal, non-fabricating field
        rename vplan_id -> id / traces_to -> requirement_refs; an item
        with no non-empty vplan_id is skipped rather than assigned a
        fabricated id. Every vplan_artifact dimension a rewritten row does
        not carry (owner/priority/verification_method/...) is left
        absent, so the Center honestly reports PARTIAL/UNKNOWN for it
        rather than inventing one."""
        try:
            if stage == "REQUIREMENTS_TRACEABILITY":
                gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
                if "spec_to_vplan_requirement_quality_gate" not in gate_ids:
                    return
                block = evidence_blocks.get("spec_to_vplan_requirement_quality_gate")
                if not isinstance(block, dict):
                    return
                self._write_requirement_vplan_center_file(stage, "requirements.json", block)
            elif stage == "VPLAN":
                gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
                if "spec_to_vplan_quality_gate" not in gate_ids:
                    return
                block = evidence_blocks.get("spec_to_vplan_quality_gate")
                if not isinstance(block, dict):
                    return
                items = block.get("vplan_items")
                if not isinstance(items, list):
                    return
                rows = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    vplan_id = item.get("vplan_id")
                    if not isinstance(vplan_id, str) or not vplan_id.strip():
                        continue
                    row: Dict[str, Any] = {"id": vplan_id}
                    traces_to = item.get("traces_to")
                    if isinstance(traces_to, list) and all(
                            isinstance(t, str) and t.strip() for t in traces_to):
                        row["requirement_refs"] = traces_to
                    rows.append(row)
                if not rows:
                    return
                self._write_requirement_vplan_center_file(stage, "vplan.json", {"vplan_rows": rows})
        except Exception as exc:  # a refresh must never fail a real stage
            self.store.event({"ts": now(), "stage": stage,
                               "event": "REQUIREMENT_VPLAN_CENTER_REFRESH_FAILED",
                               "error": f"{type(exc).__name__}: {exc}"})

    def _write_requirement_vplan_center_file(self, stage: str, filename: str, payload: dict) -> None:
        """Shared atomic-write + event-logging tail for
        _refresh_requirement_vplan_center_snapshot() above -- mirrors
        Blackboard.write()'s own tempfile.mkstemp() + storage.
        _atomic_replace() idiom (never a plain truncate-then-write), and
        _persist_subsystem_registry_entry's own best-effort
        event-on-failure discipline. A write failure is recorded and never
        allowed to turn an already-earned stage PASS into a crash."""
        import tempfile
        from .storage import _atomic_replace
        path = self.root / ".dv-harness" / "requirement_vplan" / filename
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".json", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                _atomic_replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except OSError as exc:
            self.store.event({"ts": now(), "stage": stage,
                               "event": "REQUIREMENT_VPLAN_CENTER_WRITE_FAILED",
                               "file": filename, "error": str(exc)})
            return
        self.store.event({"ts": now(), "stage": stage,
                           "event": "REQUIREMENT_VPLAN_CENTER_REFRESHED",
                           "file": filename})

    def _export_signoff_bundle(self, stage: str) -> None:
        """The real production-path caller for
        dv_harness/signoff_export.py's collect_signoff_bundle() (2026-09-04,
        mechanism #8 Qualification/Signoff Engine gap-close).

        Before this, that module's ONLY callers were `dv-harness
        signoff-export` and the dashboard's POST /api/signoff-export button --
        both of which bypass gates.STAGE_GATES["SIGNOFF"] entirely, so a
        complete-looking "signoff bundle" was produced for projects whose
        SIGNOFF stage had never started (confirmed against this repo's own
        .dv-harness/state.json). Nothing anywhere produced a bundle as a
        consequence of a real, gate-verified SIGNOFF PASS.

        Called from run_stage()'s `verdict == "PASS"` side-effect block, so
        it runs only after all 9 real SIGNOFF gates accepted this attempt's
        evidence.

        Two conditions are re-checked here rather than assumed from the call
        site, because that block runs on gate verdict alone:
        1. The stage's own in-memory status must really be PASS. SIGNOFF is
           one of the stages run_stage() downgrades to WAIT_USER when no
           `dv-harness approve SIGNOFF` is on record -- gates passing is not
           the same as the stage closing, and a bundle must not be exported
           for a signoff still waiting on a human.
        2. state.json must be flushed to disk FIRST. The final
           store.save(self.state) of run_stage() happens well after this
           side-effect block; without this flush, signoff_export's
           read_signoff_stage_status() would read the RUNNING status written
           at the START of this attempt and stamp a genuinely gate-verified
           bundle PRE_SIGNOFF_GATE_INPUT.

        Same best-effort contract as _persist_subsystem_registry_entry above:
        an export failure is recorded as a real event and never downgrades an
        already-earned SIGNOFF PASS.
        """
        if stage != Stage.SIGNOFF.value:
            return
        if self.state.stages.get(stage, {}).get("status") != Status.PASS.value:
            return
        from . import signoff_export
        out_dir = self.root / ".dv-harness" / "signoff_bundle"
        try:
            self.store.save(self.state)
            result = signoff_export.collect_signoff_bundle(self.root, out_dir)
        except Exception as exc:
            self.store.event({"ts": now(), "stage": stage, "event": "SIGNOFF_BUNDLE_EXPORT_FAILED",
                               "out_dir": str(out_dir), "error": str(exc)})
            return
        self.store.event({"ts": now(), "stage": stage, "event": "SIGNOFF_BUNDLE_EXPORTED",
                           "out_dir": result["out_dir"], "bundle_hash": result["bundle_hash"],
                           "bundle_kind": result["bundle_kind"],
                           "bundled_count": result["bundled_count"],
                           "missing_count": result["missing_count"]})

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
            # self.root is passed so the composition consults the REAL
            # cross-subsystem analysis (SYS-9..SYS-14) over these subsystems
            # before composing, rather than composing blind to it.
            files = compose_soc_environment(subsystems, registry, self.root)
        except NotImplementedError as exc:
            self.store.event({"ts": now(), "stage": stage, "event": "SOC_COMPOSITION_NOT_IMPLEMENTED",
                               "error": str(exc)})
            return
        except CrossSubsystemIntegrationBlockedError as exc:
            # A DRIVER_CONFLICT between two composed subsystems stops the
            # composition at BLOCKED and needs a HUMAN to arbitrate ownership.
            # Logged and skipped, same as every other composition failure here:
            # it never downgrades an already-earned SYSTEM_LEVEL stage PASS,
            # and it never resolves the conflict itself.
            self.store.event({"ts": now(), "stage": stage,
                               "event": "SOC_COMPOSITION_BLOCKED_PENDING_HUMAN_ARBITRATION",
                               "reason": exc.reason, "detail": exc.detail})
            return
        except (EmptySubsystemRegistryError, MissingSubsystemNameEvidenceError) as exc:
            self.store.event({"ts": now(), "stage": stage, "event": "SOC_COMPOSITION_INPUT_INVALID",
                               "reason": getattr(exc, "reason", str(exc)),
                               "detail": getattr(exc, "detail", {})})
            return
        soc_name = sv_id(registry.get("soc_name") or "soc")
        # Same helper the CREATE ENVIRONMENT entry point's SYSTEM_LEVEL_MODE
        # dispatch uses (uvm_generator/create_environment.py), so a
        # composition produced through either real path lands where the
        # other looks for it.
        out_dir = soc_composition_out_dir(self.root, soc_name)
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

    def _root_cause_confidence_inputs(self, block: dict,
                                       concurrent_agent_evidence_count: int = 0) -> Dict[str, Any]:
        """Real independent_sources_count/evidence_refs_verified/
        counter_evidence_count/multi_agent_consensus_count derivation from a
        root_cause_evidence_gate evidence block -- factored out of
        _score_root_cause_confidence() below (2026-09-03, obsidian-memory-
        debugflow task, Phase 10) so _promote_verified_fix_knowledge() can
        compose with the exact SAME real inference.score_confidence() inputs
        when it triggers memory_router.promote_to_organizational()'s
        evaluation, rather than inventing a second, parallel derivation of
        the same real evidence for a different call site. See
        _score_root_cause_confidence()'s own docstring for the full
        rationale behind each of these four counts.

        `concurrent_agent_evidence_count` (2026-09-03, RCA_G1 multi-agent gap
        closure): how many genuinely CONCURRENT specialist agents contributed
        their own independently-gathered evidence to this root cause, counted
        from real state by _rca_fanout_agent_evidence_count(). Zero (the
        default) for every caller and stage where no concurrent fan-out ran,
        which keeps the pre-existing single-agent behavior byte-identical.
        Added to -- never substituted for -- the refuted-alternative-
        hypothesis count below: at RCA_JOIN both signals are real and
        independent (three different agent profiles over three different
        evidence domains, AND the surviving hypothesis having survived
        recorded refutations), so both legitimately count toward
        score_confidence()'s multi_agent_consensus_count >= 2 bonus."""
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
        multi_agent_consensus_count = int(concurrent_agent_evidence_count)
        if isinstance(hyps, list):
            selected_claim = block.get("root_cause")
            multi_agent_consensus_count += sum(
                1 for h in hyps
                if isinstance(h, dict) and h.get("claim") != selected_claim and h.get("counter_evidence")
            )
        return {
            "independent_sources_count": independent_sources_count,
            "evidence_refs_verified": evidence_refs_verified,
            "counter_evidence_count": counter_evidence_count,
            "multi_agent_consensus_count": multi_agent_consensus_count,
        }

    def _root_cause_hypotheses_voi_ranking(
            self, block: Dict[str, Any],
            confidence_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """inference.rank_evidence_by_information_value() gap-close
        (2026-09-07, REACHED-not-WIRED closure): adapts
        root_cause_evidence_gate's own real `hypotheses` array -- the SAME
        list _root_cause_confidence_inputs() above already reads for its
        multi_agent_consensus_count signal -- into the {hypothesis_id,
        required_evidence_categories, supplied_evidence_categories,
        current_confidence_level} shape rank_evidence_by_information_value()
        expects, without inventing a per-hypothesis evidence vocabulary:
        every hypothesis is checked against the SAME
        self.ROOT_CAUSE_EVIDENCE_CATEGORIES this method's caller already
        uses for the selected root_cause. first_bad_event/causal_chain are
        structurally absent on every per-hypothesis dict (they are not in
        root_cause_evidence_gate.py's own per-hypothesis field list -- only
        the top-level block carries them), so both correctly discriminate
        to a 0 voi_score (every hypothesis missing them equally -- nothing
        to discriminate) rather than being silently narrowed to a
        different, invented vocabulary.

        Per this project's Evidence Truth Rule, the SELECTED hypothesis
        (the one whose own `claim` matches block["root_cause"]) uses the
        caller's own INDEPENDENTLY RECOMPUTED confidence_result["level"] --
        never its self-reported `confidence` field. Every OTHER
        (alternative, refuted) hypothesis has no independent recompute
        available at this call site, so its own self-declared `confidence`
        is used ONLY as an advisory urgency weight (this function never
        gates or scores anything, only ranks which MISSING evidence
        category would most help discriminate between hypotheses still
        standing), and only when it is a real, recognized
        inference.CONFIDENCE_LEVELS value -- an unrecognized/absent one
        (e.g. the gate's own "CONFIRMED", which is not a
        score_confidence()-producible level) is passed through as None,
        treated as MEDIUM by rank_evidence_by_information_value() itself,
        never guessed at here.

        Returns None when block["hypotheses"] is absent/empty/carries no
        usable hypothesis dict -- nothing to rank. Sits strictly downstream
        of confidence_result/gap; never feeds back into verdict, gate
        evaluation, or promotion."""
        hyps = block.get("hypotheses")
        if not isinstance(hyps, list) or not hyps:
            return None
        from .inference import rank_evidence_by_information_value, CONFIDENCE_LEVELS
        selected_claim = block.get("root_cause")
        adapted = []
        for i, h in enumerate(hyps):
            if not isinstance(h, dict):
                continue
            claim = h.get("claim")
            hypothesis_id = (claim if isinstance(claim, str) and claim.strip()
                             else f"hypothesis[{i}]")
            supplied = [c for c in self.ROOT_CAUSE_EVIDENCE_CATEGORIES if h.get(c)]
            if claim is not None and claim == selected_claim:
                level = confidence_result.get("level")
            else:
                declared = h.get("confidence")
                level = declared if declared in CONFIDENCE_LEVELS else None
            adapted.append({
                "hypothesis_id": hypothesis_id,
                "required_evidence_categories": list(self.ROOT_CAUSE_EVIDENCE_CATEGORIES),
                "supplied_evidence_categories": supplied,
                "current_confidence_level": level,
            })
        if not adapted:
            return None
        return rank_evidence_by_information_value(adapted)

    def _react_step_inference(self, stage: str, evidence_blocks: Dict[str, Any],
                               signatures: Optional[List[Any]] = None,
                               adapter_ok: bool = True,
                               reroute_target: Optional[str] = None,
                               protocol: Optional[str] = None) -> Dict[str, Any]:
        """Real inference.score_confidence()/identify_gap()/next_best_action()
        for the IN-FLIGHT stage attempt -- the values ReactRecorder.record()
        persists as this attempt's `react_reasoning_step` Working Memory
        record (kind routed to WORKING_MEMORY by memory_router.route_memory()).

        WHY THIS EXISTS (2026-09-04 gap closure): CLAUDE.md's Engineering
        Memory Policy names score_confidence()/identify_gap()/
        next_best_action() as the mechanism behind exactly this record kind,
        but the record's `confidence` and `next_action` were a hardcoded
        3-way/2-way string map on ss["status"] and there was no `gap` field
        at all. inference.py's real math was wired only into
        _score_root_cause_confidence() below, which runs solely on a RE_AUDIT/
        RCA_JOIN stage PASS -- so the per-attempt reasoning record, the one
        place a debug loop actually reads mid-run, carried none of it. This
        does NOT duplicate _root_cause_confidence_inputs(): that derives its
        four counts from a single root_cause_evidence_gate evidence BLOCK's
        cited sources, which only exists after a stage has already passed.
        The in-flight attempt has a different real evidence surface -- the
        stage's configured gate list and this attempt's own gate signatures --
        so the counts are derived from those, and both feed the same one
        score_confidence() implementation.

        Real inputs, all from data this attempt actually produced:
          - required: the gate ids really configured for this stage
            (gates.effective_stage_gates, i.e. STAGE_GATES plus any
            project-level override) -- the evidence vocabulary the agent was
            actually obliged to supply.
          - supplied: which of those the agent's response really carried a
            ```dv-harness-evidence:<gate_id>``` block for.
          - gap = identify_gap(required, supplied): the real set difference.
          - independent_sources_count = len(supplied): distinct gate-scoped
            evidence sources this attempt produced.
          - evidence_refs_verified: the adapter call succeeded AND no gate is
            missing its block AND every gate signature is ok -- a real bool
            about THIS attempt, never assumed from the status string.
          - counter_evidence_count = the number of gate signatures that
            really failed: concrete recorded evidence against "this attempt
            is complete", which is exactly what score_confidence()'s
            counter-evidence term (and its HIGH safety floor) is for.
          - multi_agent_consensus_count: reuses the SAME real
            _rca_fanout_agent_evidence_count() signal
            _root_cause_confidence_inputs() already uses, at the one stage
            (RCA_JOIN) where a concurrent fan-out really ran.

        next_action is likewise derived, never mapped from a status string:
        a real reroute target when the inner ReAct loop chose one, else the
        real next_best_action() suggestion for the first gap, else the real
        failing gate ids to retry against, else "advance".

        DELIBERATE, VISIBLE CONSEQUENCE: a stage with NO configured gate at
        all (verdict NO_GATE_REQUIRED) now scores LOW, where the old string
        map reported HIGH purely because ss["status"] read PASS. That is the
        honest answer under this project's own formula -- zero independent
        sources and nothing verified -- and it is the same principle
        run_stage() already applies one level up ("transport success is NOT
        the same as DV PASS"). A single-gate stage that really passes scores
        MEDIUM, and a multi-gate stage that really passes scores HIGH; the
        number now tracks how much real evidence backs the step."""
        from .gates import effective_stage_gates

        try:
            required = [gid for gid, _script, _flag in effective_stage_gates(stage, self.root)]
        except Exception:
            required = [gid for gid, _script, _flag in STAGE_GATES.get(stage, [])]
        blocks = evidence_blocks if isinstance(evidence_blocks, dict) else {}
        supplied = [gid for gid in required if blocks.get(gid) is not None]
        gap = identify_gap(required, supplied)

        sigs = list(signatures or [])
        failing = [getattr(s, "gate_id", "") for s in sigs if not getattr(s, "ok", False)]
        confidence_detail = score_confidence(
            independent_sources_count=len(supplied),
            evidence_refs_verified=bool(adapter_ok and required and not gap and not failing),
            counter_evidence_count=len(failing),
            multi_agent_consensus_count=(self._rca_fanout_agent_evidence_count()
                                          if stage == Stage.RCA_JOIN.value else 0),
        )

        next_actions = next_best_action(protocol or "_general", gap, self.root) if gap else []
        if reroute_target:
            next_action = f"reroute:{reroute_target}"
        elif next_actions:
            next_action = next_actions[0]["suggested_action"]
        elif failing:
            next_action = "retry_targeted:" + ",".join(str(g) for g in failing[:3])
        elif not adapter_ok:
            next_action = "retry_after_adapter_failure"
        else:
            next_action = "advance"

        return {
            "gap": gap,
            "confidence": confidence_detail["level"],
            "confidence_detail": confidence_detail,
            "next_action": next_action,
            "next_best_action": next_actions,
        }

    def _record_agent_escalation_signal(self, stage: str, step_inference: Dict[str, Any],
                                         context_path: Optional[str] = None
                                         ) -> Optional[Dict[str, Any]]:
        """Records a real, AGENT-FACING inference.build_deeper_investigation_
        signal() entry (agent_self_escalation gap-close, 2026-09-07) whenever
        THIS attempt's own real score_confidence() result --
        step_inference["confidence_detail"], the exact dict
        _react_step_inference() just computed one call above -- lands on LOW.

        Deliberately NOT a question_queue.py record, and this is a structural
        fact about this method, not merely a claim: it never imports or calls
        anything in question_queue.py, never files or answers a question,
        and never blocks a stage or changes ss["status"]/routing in any way.
        It is a fact about THIS agent's OWN mid-investigation confidence,
        appended to the real "agent_escalation_signals" Blackboard topic
        (Blackboard.append_agent_escalation_signal(), the same {"items": [...]}
        append-only shape debug_loop_history already uses) for a caller/graph
        orchestrator to read -- via a real node.blackboard_read declaration,
        exactly like every other topic there -- and decide, entirely on its
        own initiative, whether to fan out further agents. Recording it never
        itself dispatches anything; see inference.py's own module comment for
        this section and its ESCALATION_SIGNAL_DISCLOSURE, carried verbatim
        onto every recorded entry.

        Returns None (no signal recorded) whenever confidence_detail is
        missing/malformed or the real level is not LOW -- the identical
        "an absent finding is a real answer, not an error" convention this
        project already applies elsewhere, never a fabricated escalation.

        Best-effort, mirroring every sibling `_record_*` method in this file:
        a recording failure must never turn an already-computed, already-
        persisted react_reasoning_step into a crash."""
        try:
            confidence_detail = step_inference.get("confidence_detail") if isinstance(step_inference, dict) else None
            if not isinstance(confidence_detail, dict):
                return None
            signal = build_deeper_investigation_signal(
                confidence_detail, stage=stage, context_path=context_path,
                gap=step_inference.get("gap"))
            if signal is None:
                return None
            registry = self.blackboard.append_agent_escalation_signal(signal, source=stage)
            self.store.event({"ts": now(), "event": "AGENT_ESCALATION_SIGNAL_RECORDED",
                              "stage": stage, "signal": signal["signal"],
                              "sequence_number": registry["items"][-1]["sequence_number"]})
            return registry
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "event": "AGENT_ESCALATION_SIGNAL_RECORD_FAILED",
                                  "stage": stage, "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass
            return None

    def _file_low_confidence_human_checkpoint(self, stage: str, step_inference: Dict[str, Any],
                                                context_path: Optional[str] = None
                                                ) -> Optional[Dict[str, Any]]:
        """Files the real, HUMAN-FACING counterpart to
        `_record_agent_escalation_signal()` immediately above (gap-close
        2026-09-07, no-human-facing-preaction-low-confidence-checkpoint) --
        see `dv_harness.low_confidence_human_checkpoint` for the full
        design. Reuses the SAME `step_inference` this attempt already
        computed one call above; never recomputes confidence.

        Unlike the agent-facing signal, this files a real, persisted,
        Tier-3 BLOCKING `question_queue.py` record (only when this
        attempt's own real `score_confidence()` result lands LOW) carrying
        the full rendered Hypothesis -> Evidence -> Confidence -> Gap
        reasoning chain, so a human reviewing the queue sees WHY before
        answering "proceed?". Idempotent on question_key across retries of
        the same stage/evidence/gap -- see that module's own docstring.

        Best-effort, mirroring every sibling `_record_*`/`_file_*` method
        in this file: a filing failure must never turn an already-computed,
        already-persisted react_reasoning_step into a crash."""
        try:
            from . import low_confidence_human_checkpoint as _lchc
            from .question_queue import QuestionQueueStore
            store = QuestionQueueStore(self.root, blackboard=self.blackboard)
            record = _lchc.file_low_confidence_checkpoint(
                store, stage, step_inference, context_path=context_path)
            if record is not None:
                self.store.event({"ts": now(), "event": "LOW_CONFIDENCE_HUMAN_CHECKPOINT_FILED",
                                  "stage": stage, "question_id": record.get("id"),
                                  "status": record.get("status")})
            return record
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "event": "LOW_CONFIDENCE_HUMAN_CHECKPOINT_FILE_FAILED",
                                  "stage": stage, "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass
            return None

    def _attempt_root_cause_hypothesis_refutation(self, stage: str, block: dict,
                                                    profile_id=None, agent_name: str = "") -> Optional[Dict[str, Any]]:
        """Wires react_loop.attempt_hypothesis_refutation() into the same
        RE_AUDIT/RCA_JOIN root_cause_evidence_gate PASS
        _score_root_cause_confidence() below already scores -- closes the
        "Adversarial Refutation Pass" REACHED-not-WIRED disclosure
        qualified_conclusion.py's own module docstring names (its
        `require_refutation_pass` parameter had no engine call site before
        this).

        Gated behind the SAME policy.enable_adversarial_refutation_pass flag
        the caller below checks before invoking this method at all -- this
        method itself performs no gating of its own, and is never called
        when that flag is off. Turning it on issues one real, LIVE
        adapter.run() call per gate-verified PASS attempt at this stage, a
        materially different cost/behavior change from every other
        best-effort side effect in _score_root_cause_confidence(), which is
        why the whole pass stays off by default rather than joining those
        as an always-on write.

        Uses the SAME selected root_cause and its own real, already-cited
        supporting_evidence root_cause_evidence_gate.py already validated --
        never invents a hypothesis or evidence of its own. Returns None
        (never a fabricated attempted=True/False dict) on any exception or
        when the gate's own block carries no root_cause at all, so a
        transport failure here degrades to "no refutation pass ran" exactly
        like attempt_hypothesis_refutation()'s own honest attempted=False
        contract -- build_qualified_conclusion() already treats a None
        refutation_result identically to one carrying attempted=False."""
        try:
            from . import react_loop as _rl
            hypothesis = block.get("root_cause")
            if not hypothesis:
                return None
            supporting = block.get("supporting_evidence")
            if isinstance(supporting, dict):
                evidence_refs = [str(v) for v in supporting.values() if v]
            elif isinstance(supporting, (list, tuple)):
                evidence_refs = [str(v) for v in supporting if v]
            elif supporting:
                evidence_refs = [str(supporting)]
            else:
                evidence_refs = []
            return _rl.attempt_hypothesis_refutation(
                self.adapter, self.root, hypothesis, evidence_refs=evidence_refs,
                profiler=self.profiler, profile_id=profile_id, agent_name=agent_name)
        except Exception as exc:
            self.store.event({"ts": now(), "stage": stage,
                              "event": "ADVERSARIAL_REFUTATION_PASS_FAILED",
                              "error": f"{type(exc).__name__}: {exc}"})
            return None

    def _score_root_cause_confidence(self, stage: str, evidence_blocks: dict,
                                      verdict: str = "PASS",
                                      profile_id=None, agent_name: str = "") -> None:
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
          - multi_agent_consensus_count: the sum of two real, independent
            signals (UPDATED 2026-09-03, RCA_G1 multi-agent gap closure --
            this used to read "this harness runs ONE agent per stage attempt,
            no concurrent multi-agent branch exists", which is no longer
            true):
              (1) Genuinely concurrent specialist agents, when this stage IS
                  the RCA_G1 join. _rca_fanout_agent_evidence_count() counts
                  the RCA_*_EVIDENCE branches that really PASSed AND really
                  wrote their own Blackboard topic -- three different agent
                  profiles (rtl-evidence-agent / log-evidence-agent /
                  vip-spec-evidence-agent) dispatched concurrently by
                  _advance_with_fanout()'s ThreadPoolExecutor over three
                  different evidence domains. Zero at RE_AUDIT and every
                  other stage, where no fan-out ran.
              (2) root_cause_evidence_gate.py's own
                  NO_ALTERNATIVE_HYPOTHESIS_REFUTED requirement: how many
                  OTHER candidate hypotheses in the agent's `hypotheses`
                  array were independently evaluated and carry their own
                  recorded counter_evidence ruling them out. Each is a
                  genuinely distinct, gate-verified line of reasoning that
                  converged on the same selected root_cause by elimination --
                  a real count from real data, and the ONLY one of the two
                  available at a single-agent stage like RE_AUDIT.

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

        concurrent_agents = (self._rca_fanout_agent_evidence_count()
                             if stage == Stage.RCA_JOIN.value else 0)
        confidence_result = score_confidence(
            **self._root_cause_confidence_inputs(block, concurrent_agents))

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
            "concurrent_agent_evidence_count": concurrent_agents,
            "gap": gap,
            "next_best_action": next_actions,
            "promotion": promotion,
        }, source=stage)
        self.store.event({
            "ts": now(), "stage": stage, "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
            "recomputed_confidence": confidence_result,
            "agent_reported_confidence": block.get("confidence"),
            "concurrent_agent_evidence_count": concurrent_agents,
            "gap": gap, "next_best_action": next_actions, "promotion": promotion,
        })

        # inference.rank_evidence_by_information_value() gap-close
        # (2026-09-07): a real, cited advisory ranking of which MISSING
        # evidence category would most help discriminate between the
        # candidate hypotheses this gate already recorded, sitting beside
        # (never feeding back into) the confidence score/gap above.
        # Best-effort, mirrors every other side effect in this method.
        try:
            voi_ranking = self._root_cause_hypotheses_voi_ranking(block, confidence_result)
            if voi_ranking is not None:
                self.blackboard.write("root_cause_evidence_voi_ranking",
                                      voi_ranking, source=stage)
                self.store.event({
                    "ts": now(), "stage": stage, "event": "ROOT_CAUSE_EVIDENCE_VOI_RANKED",
                    "hypothesis_count": voi_ranking.get("hypothesis_count"),
                    "ranked_category_count": len(voi_ranking.get("ranked") or []),
                })
        except Exception as exc:
            self.store.event({"ts": now(), "stage": stage,
                              "event": "ROOT_CAUSE_EVIDENCE_VOI_RANKING_FAILED",
                              "error": f"{type(exc).__name__}: {exc}"})

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
        # Adversarial Refutation Pass (adversarial_refutation_pass
        # engine-wiring gap-close, 2026-09-07): opt-in, off by default
        # (policy.enable_adversarial_refutation_pass) -- see
        # _attempt_root_cause_hypothesis_refutation() above for why this one
        # side effect is gated separately from every other best-effort write
        # in this method (it dispatches a real, live adapter call). When on,
        # the SAME flag also makes a completed, non-refuting pass mandatory
        # for is_qualified via require_refutation_pass -- never silently
        # weaker than that.
        refutation_result = None
        require_refutation = bool(
            (self.cfg.get("policy") or {}).get("enable_adversarial_refutation_pass", False))
        if require_refutation:
            refutation_result = self._attempt_root_cause_hypothesis_refutation(
                stage, block, profile_id=profile_id, agent_name=agent_name)
            self.store.event({
                "ts": now(), "stage": stage, "event": "ADVERSARIAL_REFUTATION_PASS_RUN",
                "attempted": bool(refutation_result and refutation_result.get("attempted")),
                "refuted": bool(refutation_result and refutation_result.get("refuted")),
            })

        try:
            qc = build_qualified_conclusion(verdict, confidence_result, block,
                                            refutation_result=refutation_result,
                                            require_refutation_pass=require_refutation)
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

    def _file_waveform_dump_scope_question(self, stage: str,
                                             evidence_blocks: dict) -> Optional[Dict[str, Any]]:
        """Files the Waveform Dump User Gate's confirmation question into the
        REAL question queue at the exact moment run_stage() parks the loop at
        WAIT_USER for it, and returns the persisted record (or None when
        nothing was filed).

        The gap this closes (2026-09-04 re-audit of AI mechanism #12 "AI Debug
        Closed Loop"). Both halves of the ask/answer round-trip already
        existed -- `waveform_dump_gate.ask_dump_scope_confirmation()` files the
        question, `QuestionQueueStore.answer_question()` records the human
        answer -- but the ask half had exactly ONE caller in the whole repo:
        cli.py's human-typed `dv-harness waveform-dump-scope ask`. Nothing in
        engine.py called it. So on the autonomous path the sequence was:
        headless `claude -p` subprocess emits a focused_wave_debug_window_gate
        block whose `confirmed_by` cannot resolve to a human decision ->
        gates.py returns NEEDS_USER_INPUT -> run_stage() sets WAIT_USER ->
        loop() returns. Correct so far, and deliberately so. But the queue was
        still EMPTY: `dv-harness question-queue list --blocking-only` showed
        nothing, `build_digest()` had nothing to report, and the human who came
        back to the parked run had to read the Q-ID out of a blocking_reason
        string and hand-reconstruct the `waveform-dump-scope ask` invocation
        (scope AND level/depth) before the answer verb had anything to answer.
        The loop opened at WAIT_USER and left behind no artifact capable of
        closing it. CLAUDE.md's "Waveform Dump User Gate" already claimed such
        a run "parks at WAIT_USER with a real Q-ID for a human to answer" --
        that claim is what this method makes true on the autonomous path.

        The scope and the proposed level/depth are read from the SAME
        `evidence_blocks` dict run_stage() already computed via
        extract_evidence_blocks(result.text) -- the very block the gate just
        rejected -- so the filed question describes the dump the agent actually
        proposed, not a placeholder. Same convention as
        _arm_rca_evidence_fanout() / _score_root_cause_confidence() below and
        above: read the already-parsed blocks, never re-parse the text.

        This files a QUESTION; it never writes a DECISION. Only
        `QuestionQueueStore.answer_question()` -- i.e. a human running
        `dv-harness question-queue answer` -- can do that, and this method
        does not call it. The human checkpoint CLAUDE.md mandates is
        untouched; what changes is that the human is now handed a real,
        answerable Q-ID instead of an instruction to file one themselves.

        Not filed, deliberately, in three cases:
          * The stage produced no `focused_wave_debug_window_gate` block at
            all -- this NEEDS_USER_INPUT is INTAKE's, not the waveform gate's.
          * The block declares no scope or no level/depth
            (WAVEFORM_DUMP_SCOPE_NOT_CONFIRMED / _CONFIRMATION_INCOMPLETE).
            A question that cannot say what dump is being proposed cannot be
            answered yes/no, which is exactly why
            ask_dump_scope_confirmation() raises ValueError on it. That is
            agent error with its own remedy already in `reasons`, not a
            missing human decision.
          * A question for this scope's question_key is ALREADY on file
            (verify_dump_scope_confirmation()'s REASON_AWAITING_ANSWER case,
            tested with the identical `get_question(qid) is not None`
            predicate). add_question() APPENDS -- it does not dedupe on the
            derived id -- so re-filing on every park would grow duplicate
            records and re-arm `digest_batch_id` for a question already
            waiting.

        Best-effort, like every other post-verdict hook here: a question-queue
        failure must never convert an already-correct WAIT_USER park into a
        crash out of run_stage()."""
        block = evidence_blocks.get("focused_wave_debug_window_gate")
        confirm = block.get("dump_scope_confirmed") if isinstance(block, dict) else None
        if not isinstance(confirm, dict):
            return None
        scope = str(confirm.get("scope") or "").strip()
        level_or_depth = str(confirm.get("level_or_depth") or "").strip()
        if not scope or not level_or_depth:
            return None
        try:
            from . import question_queue as _qq
            from . import waveform_dump_gate
            from .question_queue import QuestionQueueStore
            store = QuestionQueueStore(self.root, blackboard=self.blackboard)
            key = waveform_dump_gate.dump_scope_question_key(scope)
            qid = _qq.make_question_id(waveform_dump_gate.WAVEFORM_DUMP_DOMAIN, key)
            if store.get_question(qid) is not None:
                return None
            record = waveform_dump_gate.ask_dump_scope_confirmation(
                self.root, scope=scope, proposed_level_or_depth=level_or_depth,
                # The failure this dump is meant to see. Optional in the ask
                # API and genuinely optional here: it only enriches the
                # APPROVE option's rationale so the human reads what the dump
                # is FOR, never part of the question_key.
                failure_cone=str(block.get("failure_cone") or "").strip(),
                store=store,
            )
        except Exception as exc:
            self.store.event({"ts": now(), "stage": stage,
                               "event": "WAVEFORM_DUMP_SCOPE_QUESTION_FILE_FAILED",
                               "scope": scope, "error": str(exc)})
            return None
        self.store.event({"ts": now(), "stage": stage,
                           "event": "WAVEFORM_DUMP_SCOPE_QUESTION_FILED",
                           "question_id": record["id"], "question_key": record["question_key"],
                           "tier": record["tier"], "status": record["status"],
                           "scope": scope, "level_or_depth": level_or_depth})
        return record

    def _arm_rca_evidence_fanout(self, stage: str, evidence_blocks: dict) -> None:
        """Decides, from FAILURE_RECOVERY's own gate-verified triage evidence,
        whether the next advance() takes the RCA_G1 multi-agent evidence
        fan-out (RCA_RTL_EVIDENCE / RCA_LOG_EVIDENCE / RCA_VIP_SPEC_EVIDENCE
        -> RCA_JOIN) or FAILURE_RECOVERY's original single CHANGE_IMPACT
        edge. This is the trigger half of CLAUDE.md's "Important DUT/PHY/
        Register/VIP changes require Multi-Agent evidence acquisition plus
        independent synthesis"; _resolve_conditional_fanout_frontier()/
        _advance_with_fanout() are the dispatch half.

        Trigger is REAL_ISSUE, and nothing weaker. That is not a proxy for
        "touches RTL/PHY/register/VIP" -- it is the same requirement stated
        in the harness's own vocabulary, because
        tools/verification_flow/issue_triage_classification_gate.py already
        FAILs (REAL_ISSUE_WITHOUT_DEEP_RCA) any REAL_ISSUE classification
        that did not also set deep_rca_triggered. So a REAL_ISSUE block that
        got this far is, structurally, a failure the harness has already
        ruled needs deep RCA, and the three RCA_G1 branches ARE the
        RTL / log / VIP+spec evidence domains that rule names. A
        MISCLASSIFIED / KNOWN / BLOCKED triage is left on the original single
        path, matching rca-multi-agent-fusion.js's own `whenToUse`.

        The agent's classification is never trusted on its own here: this
        method only ever runs from the `verdict == "PASS"` branch, i.e. after
        issue_triage_classification_gate.py itself already accepted the block
        (valid classification vocabulary, non-empty classification_reason AND
        evidence_hash, deep_rca_triggered set). The token stored on
        HarnessState carries that real evidence_hash so the state file
        records WHICH triage decision authorized the fan-out.

        Every other stage is a no-op, and a FAILURE_RECOVERY PASS that is not
        REAL_ISSUE actively CLEARS any stale arming rather than leaving an
        older failure's authorization live."""
        if stage != Stage.FAILURE_RECOVERY.value:
            return
        block = evidence_blocks.get("issue_triage_classification_gate")
        classification = block.get("classification") if isinstance(block, dict) else None
        if classification != "REAL_ISSUE":
            if self.state.rca_evidence_fanout_armed:
                self.state.rca_evidence_fanout_armed = None
                self.store.save(self.state)
            return
        token = f"REAL_ISSUE:{block.get('evidence_hash') or 'NO_EVIDENCE_HASH'}"
        self.state.rca_evidence_fanout_armed = token
        self.store.save(self.state)
        self.store.event({"ts": now(), "stage": stage, "event": "RCA_EVIDENCE_FANOUT_ARMED",
                           "parallel_group": self.RCA_EVIDENCE_FANOUT_GROUP,
                           "classification": classification, "armed_by": token})

    def _rca_fanout_agent_evidence_count(self) -> int:
        """How many of the RCA_G1 evidence branches genuinely produced their
        own independent evidence for the failure RCA_JOIN is now synthesizing
        -- a branch counts only if BOTH its stage reached PASS in this run's
        real HarnessState AND its own declared Blackboard topic was actually
        written (Blackboard.read() returns a value). Two independent real
        facts, neither of them the synthesizing agent's own say-so.

        This is what lets _score_root_cause_confidence()'s
        multi_agent_consensus_count stop being a single-agent proxy at
        RCA_JOIN: the branches really were dispatched concurrently by
        _advance_with_fanout()'s ThreadPoolExecutor, each running a different
        real agent profile over a different evidence domain."""
        if self.graph is None:
            return 0
        count = 0
        for node in self.graph.nodes.values():
            if node.parallel_group != self.RCA_EVIDENCE_FANOUT_GROUP:
                continue
            ss = self.state.stages.get(node.id) or {}
            if ss.get("status") != Status.PASS.value:
                continue
            if all(self.blackboard.read(topic) is not None for topic in node.blackboard_write):
                count += 1
        return count

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

    def _promote_project_topology_knowledge(self, stage: str, evidence_blocks: dict,
                                             producing_agent_profile: Optional[str] = None) -> None:
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
            # producing_agent_profile (2026-09-07, agent_profile_track_record
            # gap-close): same `_resolved_agent_name` value run_stage() already
            # threads through every sibling _promote_*/_record_* method below.
            "producing_agent_profile": producing_agent_profile,
        }
        try:
            promotion = route_and_store(self.root, record, cfg=self.cfg)
        except Exception as exc:
            promotion = {"destination": "PROMOTION_FAILED", "error": str(exc)}
        self.store.event({
            "ts": now(), "stage": stage, "event": "PROJECT_TOPOLOGY_PROMOTED",
            "promotion": promotion,
        })

    def _promote_vplan_summary_knowledge(self, stage: str, evidence_blocks: dict,
                                          producing_agent_profile: Optional[str] = None) -> None:
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
            "producing_agent_profile": producing_agent_profile,
        }
        try:
            promotion = route_and_store(self.root, record, cfg=self.cfg)
        except Exception as exc:
            promotion = {"destination": "PROMOTION_FAILED", "error": str(exc)}
        self.store.event({
            "ts": now(), "stage": stage, "event": "VPLAN_SUMMARY_PROMOTED",
            "promotion": promotion,
        })

    def _promote_verified_fix_knowledge(self, stage: str, evidence_blocks: dict,
                                        resolved_protocol: Optional[str] = None,
                                        producing_agent_profile: Optional[str] = None) -> None:
        """Closed-loop wiring (verified-fix-auto-promotion gap-closing pass,
        2026-09-02): DEBUG_WORKFLOW_GUIDE.md's Knowledge Center push
        previously only ever happened two ways -- _promote_experience_knowledge
        above (a bare "root_cause"/"debug_lesson" record, pushed on
        EXPERT_FEEDBACK_LOOP's experience_knowledge_gate PASS, BEFORE any fix
        is proven to work) and a separate manual .work/persist_*.py script a
        human/agent has to remember to run by hand. Neither path automatically
        records the actual VERIFIED FIX once RE_AUDIT itself proves it: a PASS
        verdict on RE_AUDIT whose STAGE_GATES include both fix_effectiveness_gate
        (tools/verification_flow/fix_effectiveness_gate.py -- structurally
        requires failure_signature_after != failure_signature_before,
        targeted_reproducer_passed, broader_regression_passed, and NOT
        new_failures_introduced) and fix_regression_non_regression_gate
        (tools/verification_flow/fix_regression_non_regression_gate.py --
        structurally requires target_pre_fix_result==FAIL,
        target_post_fix_result==PASS, replay_equivalent==True, no
        pre_fix_result==PASS test regressing post-fix, and cross-checks any
        supplied job_id against the real on-disk JobState record) both means
        those two gate scripts ALREADY independently verified the fix
        actually works AND did not regress anything -- exactly the
        "fix_effectiveness_gate/fix_regression_non_regression_gate (RE_AUDIT
        gates) have PASSed" precondition this project's own gap audit called
        for. This method closes that gap: it auto-builds and
        route_and_store()s a real kind="verified_fix" record here, in-process,
        the moment RE_AUDIT reaches that verdict -- no separate manual script
        required for this common case.

        Same guard idiom as every other _promote_*/_persist_* method in this
        class: `stage` reaching here already means run_stage()'s caller
        computed verdict=="PASS" for the WHOLE stage (see the one real call
        site below), and evaluate_stage_evidence_with_detail() only returns
        "PASS" when EVERY gate_id in STAGE_GATES[stage] passed -- so checking
        both gate ids are present in this stage's STAGE_GATES mapping is
        sufficient to know both individually PASSed; there is no separate
        per-gate detail this method needs to re-derive (run_stage() already
        has that in `structured_signatures`, but the coarse "did this stage
        reach PASS" signal already implies it for these two specific
        gate ids). A stage lacking either gate id (i.e. anything other than
        RE_AUDIT today) is a genuine no-op, same as every sibling method here.

        Reads the SAME evidence_blocks dict run_stage() already computed via
        extract_evidence_blocks(result.text) -- does not re-parse agent text
        a second time. Neither fix_effectiveness_gate nor
        fix_regression_non_regression_gate appears in JUDGMENT_FIELDS (gates.py)
        so, unlike _promote_experience_knowledge's experience_knowledge_gate
        handling, there is no Tier-5 DV-review co-sign {"value":...} wrapper
        to unwrap here regardless of policy.require_dv_review_cosign.
        root_cause_evidence_gate's block IS read for enrichment
        (root_cause/symptom text), unwrapped exactly the same way
        _score_root_cause_confidence above already reads that same gate's
        block -- following that existing precedent rather than inventing a
        third convention.

        This is ADDITIVE, not a replacement for EXPERT_FEEDBACK_LOOP's own
        experience_knowledge_gate path: that stage remains the higher-
        scrutiny, human-expert-approved route to a "debug_lesson"/pattern-
        level record (and, when EXPERT_FEEDBACK_LOOP's own
        experience_applicability_gate/route_memory() judge it a
        "cross_project_lesson", the cross-project ORGANIZATIONAL_MEMORY
        promotion route_and_store() already gives it). This new record is
        the project-local Engineering-Memory-tier record for THIS ONE fix,
        auto-pushed the moment its own regression-verified evidence exists --
        route_and_store() already shares any ENGINEERING_MEMORY record to the
        configured shared Knowledge Center via its own _maybe_share()/
        maybe_push_to_shared() logic (see memory_router.py's
        _SHAREABLE_DESTINATIONS), so this method never duplicates that call
        itself, exactly like every other route_and_store() call site in this
        class."""
        gate_ids = {gid for gid, _, _ in STAGE_GATES.get(stage, [])}
        if not {"fix_effectiveness_gate", "fix_regression_non_regression_gate"} <= gate_ids:
            return
        fix_block = evidence_blocks.get("fix_effectiveness_gate")
        closure_block = evidence_blocks.get("fix_regression_non_regression_gate")
        if not isinstance(fix_block, dict) or not isinstance(closure_block, dict):
            return  # both gates are required members of gate_ids above, so a
                     # PASS verdict guarantees both blocks exist and validated
                     # -- this is only a defensive belt-and-braces check.
        rc_block = evidence_blocks.get("root_cause_evidence_gate")
        rc_block = rc_block if isinstance(rc_block, dict) else {}

        root_cause_id = fix_block.get("root_cause_id")
        root_cause_text = rc_block.get("root_cause") or root_cause_id
        symptoms = [s for s in (
            rc_block.get("symptom"), fix_block.get("failure_signature_before"),
        ) if s]

        record = {
            "kind": "verified_fix",
            "verified": True,  # fix_effectiveness_gate + fix_regression_non_regression_gate
                                # already independently required this (targeted
                                # reproducer PASS, broader regression PASS, no new
                                # failures, target FAIL->PASS, replay-equivalent,
                                # no critical-test regression)
            "title": f"Verified fix: {root_cause_text}" if root_cause_text else "RE_AUDIT verified fix",
            "scope": "engineering",
            "symptoms": symptoms,
            "root_cause": root_cause_text,
            "fix": fix_block.get("fix_revision"),
            "verification": {
                "targeted_reproducer_passed": fix_block.get("targeted_reproducer_passed"),
                "broader_regression_passed": fix_block.get("broader_regression_passed"),
                "new_failures_introduced": fix_block.get("new_failures_introduced"),
                "rerun_evidence": fix_block.get("rerun_evidence"),
                "target_pre_fix_result": closure_block.get("target_pre_fix_result"),
                "target_post_fix_result": closure_block.get("target_post_fix_result"),
                "replay_equivalent": closure_block.get("replay_equivalent"),
                "critical_non_regression_tests": closure_block.get("critical_non_regression_tests"),
                "fix_commit_hash": closure_block.get("fix_commit_hash"),
                "rerun_bundle_hash": closure_block.get("rerun_bundle_hash"),
            },
            "confidence": "HIGH",  # independently gate-verified fix effectiveness AND
                                    # non-regression, not merely agent-self-reported
            "note": f"Auto-promoted from RE_AUDIT stage evidence (fix_effectiveness_gate + "
                    f"fix_regression_non_regression_gate both PASSed).",
            "provenance": f"RE_AUDIT auto-promotion, root_cause_id={root_cause_id}",
            # Dedup/confirmation key, not a label -- see
            # _engineering_record_protocol()'s docstring for why this run's
            # canonical resolve_protocol() value takes precedence over the
            # gate block's unjudged one.
            "protocol": self._engineering_record_protocol(resolved_protocol,
                                                          rc_block.get("protocol")),
            # Phase 10 (2026-09-03, obsidian-memory-debugflow task): "record
            # symptom/root_cause/evidence/fix/verification/confidence/git
            # SHA/test/result" -- symptom/root_cause/fix/verification/
            # confidence were already captured above; these three close the
            # remaining gap, each from real gate-verified evidence, never
            # guessed:
            #   git_sha: the fix's own commit hash when the closure gate
            #     captured one (fix_regression_non_regression_gate requires
            #     fix_commit_hash non-empty to PASS at all), else this
            #     harness's own current state.git_sha as an honest fallback.
            #   rtl_sha/tb_sha: state.dut_version/tb_version -- the SAME
            #     real, gate-validated VERIFY-stage identity fields
            #     models.py's HarnessState already carries (never a second,
            #     differently-sourced identity for this record).
            #   test/result: fix_regression_non_regression_gate's own
            #     target_testcase_id/target_post_fix_result -- the specific
            #     testcase this fix was proven against and its real recorded
            #     outcome (cross-checked against the real JobState registry
            #     by that gate itself when a job_id was supplied).
            "git_sha": closure_block.get("fix_commit_hash") or self.state.git_sha,
            "rtl_sha": self.state.dut_version,
            "tb_sha": self.state.tb_version,
            "test": closure_block.get("target_testcase_id"),
            "result": closure_block.get("target_post_fix_result"),
            # producing_agent_profile (2026-09-07, agent_profile_track_record
            # gap-close): same `_resolved_agent_name` value threaded through
            # every sibling _promote_*/_record_* method in this class.
            "producing_agent_profile": producing_agent_profile,
        }
        # The four real inference.score_confidence() inputs this run's own
        # gate-validated root_cause evidence produces. Computed ONCE and used
        # twice: passed to the promotion evaluation at the bottom of this
        # method (as it always was), and PERSISTED on the record itself
        # (2026-09-04, gap-close-ai-engine #7) so a LATER independent run that
        # re-derives this same finding on a stage carrying no
        # root_cause_evidence_gate of its own -- EXPERT_FEEDBACK_LOOP, the only
        # stage with experience_knowledge_gate -- can evaluate promotion
        # against these same real inputs instead of having none at all. See
        # _evaluate_organizational_promotion()'s docstring for why that call
        # site could not derive them itself, and organizational_admission_
        # gate()'s "HONEST LIMITATION" note for the limitation this narrows.
        _confidence_inputs = self._root_cause_confidence_inputs(rc_block)
        record["confidence_inputs"] = _confidence_inputs
        try:
            promotion = route_and_store(self.root, record, cfg=self.cfg)
        except Exception as exc:
            promotion = {"destination": "PROMOTION_FAILED", "error": str(exc)}
        self.store.event({
            "ts": now(), "stage": stage, "event": "VERIFIED_FIX_PROMOTED",
            "promotion": promotion,
        })
        # rca_ontology gap-close (2026-09-07): classify THIS same
        # already-gate-verified record's root-cause CATEGORY the moment its
        # promotion is complete -- best-effort, read-only, and strictly
        # downstream of the promotion above (never allowed to affect it).
        if promotion.get("destination") != "PROMOTION_FAILED":
            self._classify_rca_category_for_verified_fix(
                stage, record, promotion.get("memory_id"))

        # Phase 10 (2026-09-03): "on PASS ... trigger the Workstream-1
        # promotion evaluation" -- the moment a real ENGINEERING_MEMORY
        # record exists for this verified fix, ask
        # memory_router.promote_to_organizational() whether it ALSO now
        # qualifies for Organizational Memory. Composes with the exact same
        # real inference.score_confidence() inputs _score_root_cause_
        # confidence() already derives from this same rc_block (via
        # _root_cause_confidence_inputs()) -- never a second, parallel
        # scoring system, per the user's spec's own explicit instruction.
        # Whether this actually promotes depends entirely on
        # promote_to_organizational()'s three real gates -- most commonly
        # INSUFFICIENT_CONFIRMATION on a fix's first PASS here, since one
        # verified fix is not yet "repeated confirmation"; this call's job
        # is only to make sure that real evaluation runs on every verified
        # fix, not to force a promotion. Best-effort: never allowed to
        # affect the already-completed VERIFIED_FIX_PROMOTED event above.
        if promotion.get("destination") == "ENGINEERING_MEMORY" and promotion.get("memory_id"):
            self._evaluate_organizational_promotion(
                stage, promotion["memory_id"], _confidence_inputs)

    def _classify_rca_category_for_verified_fix(self, stage: str, record: Dict[str, Any],
                                                 memory_id: Optional[str]) -> None:
        """rca_ontology gap-close (2026-09-07, REACHED-not-WIRED closure):
        rca_ontology.py built a real, standalone ontology
        (classify_closed_root_cause_record()) with no engine call site
        ever invoking it. This is that call site -- deliberately the one
        the module's own audit-time review already named as safe: it fires
        immediately after `promotion = route_and_store(self.root, record,
        cfg=self.cfg)` succeeds, on the SAME `record` dict
        _promote_verified_fix_knowledge() already built and just persisted
        (with `memory_id` merged in from the real `route_and_store()`
        result -- never a re-derivation, and never a second, differently-
        shaped record).

        rca_ontology.py's own module docstring is explicit that it "never
        writes a memory record, never promotes a tier" and has no
        gates.py/cli.py/STAGE_GATES reference at all -- it answers a pure
        taxonomy question ("what kind of component owned this already-
        verified fix") over a record that has ALREADY been gate-verified
        and persisted by the two real RE_AUDIT gates one line earlier, so
        it cannot affect that already-completed PASS or promotion. Its own
        `closure_status()` re-derives eligibility from `record` itself
        (memory_router.route_memory()/engineering_admission_gate()) rather
        than trusting anything this method claims, so a record that somehow
        does not actually qualify is honestly reported NOT_YET_CLOSED
        rather than miscategorized.

        Best-effort, mirroring every sibling _promote_*/_record_* method in
        this class: a classification failure records
        RCA_CATEGORY_CLASSIFY_FAILED and never turns an already-completed
        promotion into a crash."""
        try:
            from . import rca_ontology as _rca
            classified = dict(record)
            if memory_id:
                classified["memory_id"] = memory_id
            result = _rca.classify_closed_root_cause_record(classified, root=self.root)
            self.store.event({
                "ts": now(), "stage": stage, "event": "RCA_CATEGORY_CLASSIFIED",
                "memory_id": memory_id, "category": result.category,
                "signature_key": result.signature_key,
                "closure_status": result.closure_status,
            })
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "stage": stage,
                                  "event": "RCA_CATEGORY_CLASSIFY_FAILED",
                                  "memory_id": memory_id,
                                  "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass

    def _evaluate_organizational_promotion(self, stage: str, memory_id: str,
                                            confidence_inputs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Run memory_router.promote_to_organizational() on `memory_id` and
        record the real ORGANIZATIONAL_PROMOTION_EVALUATED event, whatever the
        outcome. Factored out (2026-09-04, gap-close-ai-engine #7) so this
        class's TWO Engineering-tier writers report one event vocabulary
        rather than two -- the emitted payload is byte-identical to the one
        _promote_verified_fix_knowledge() emitted inline before this existed.

        Best-effort by contract: this is a side effect of an already-earned
        stage PASS whose own promotion event is already recorded, so a failure
        here becomes a recorded reason, never an exception that could
        retroactively downgrade that PASS.

        `confidence_inputs` may be None. That is not a bug and is never
        papered over with invented counts: inference.score_confidence()'s four
        inputs are only derivable from a real root_cause_evidence_gate
        evidence block, and the record being evaluated may have been created
        before those inputs were persisted, or by a write path that never had
        such a block. NO_CONFIDENCE_INPUTS is then recorded as the reason and
        no promotion is attempted -- an honest, visible non-evaluation instead
        of a fabricated HIGH score."""
        if not confidence_inputs:
            org_eval = {"promoted": False, "reason": "NO_CONFIDENCE_INPUTS"}
        else:
            try:
                org_eval = promote_to_organizational(
                    self.root, memory_id, confidence_inputs=confidence_inputs,
                    cfg=self.cfg, kind="methodology",
                )
            except Exception as exc:
                org_eval = {"promoted": False, "reason": "PROMOTION_EVAL_EXCEPTION", "error": str(exc)}
        self.store.event({
            "ts": now(), "stage": stage, "event": "ORGANIZATIONAL_PROMOTION_EVALUATED",
            "memory_id": memory_id, "result": org_eval,
        })
        # memory_lineage gap-close (2026-09-07): fire the real, read-only
        # lineage walker at the single rarest, lowest-frequency real moment
        # in this engine -- an ACTUAL Organizational-tier promotion, itself
        # already gated by the three independent real checks above. Best
        # effort and strictly downstream of the promotion decision: it can
        # never affect org_eval, which is already computed and returned.
        if org_eval.get("destination") == "ORGANIZATIONAL_MEMORY" and org_eval.get("memory_id"):
            self._trace_memory_lineage_for_promotion(stage, org_eval["memory_id"])
        return org_eval

    def _trace_memory_lineage_for_promotion(self, stage: str, org_memory_id: str) -> None:
        """memory_lineage gap-close (2026-09-07, REACHED-not-WIRED closure):
        memory_lineage.py built a real, standalone, read-only multi-hop
        lineage walker (Organizational -> Engineering -> Job tier, back
        through every recoverable MemoryGC.confirm()/corroborating_memory_ids
        back-pointer) with no engine call site invoking it. This is that
        call site -- deliberately the narrowest one available: it fires
        only once _evaluate_organizational_promotion() above has ALREADY
        confirmed a record genuinely crossed into ORGANIZATIONAL_MEMORY,
        exactly the "how did this conclusion get here" trace a human
        reviewing that promotion would want automatically, with zero
        ability to alter the promotion decision it is reacting to (this
        method is called strictly after org_eval is computed and its own
        ORGANIZATIONAL_PROMOTION_EVALUATED event is already recorded).

        org_record is intentionally omitted: this call site holds only the
        route_and_store()-shaped push result (destination/memory_id/...),
        not the full pushed record, so build_organizational_lineage() falls
        back to its own local DV-Knowledge Vault mirror resolution --
        exactly the path that function's own docstring documents for a
        caller in this position ("Omitted, this falls back to the local
        DV-Knowledge Vault mirror -- the only local trace of an
        Organizational-tier record, since that tier has no local per-tier
        JSON store by design").

        Mints nothing, arbitrates nothing (memory_router.organizational_
        admission_gate() -- already run above, via promote_to_organizational()
        -- remains the only real gate deciding whether a record SHOULD have
        promoted; this only reconstructs, honestly, what lineage already
        exists). Best-effort, mirroring every sibling _promote_*/_record_*
        method in this class: a lineage-walk failure records
        MEMORY_LINEAGE_TRACE_FAILED and never turns an already-completed
        promotion into a crash."""
        try:
            from . import memory_lineage as _ml
            result = _ml.build_organizational_lineage(self.root, org_memory_id)
            self.store.event({
                "ts": now(), "stage": stage, "event": "MEMORY_LINEAGE_TRACED",
                "org_memory_id": org_memory_id, "status": result.status,
                "unresolved_reference_count": result.unresolved_reference_count,
                "external_reference_count": result.external_reference_count,
                "chain_length": len(result.chain),
            })
        except Exception as exc:
            try:
                self.store.event({"ts": now(), "stage": stage,
                                  "event": "MEMORY_LINEAGE_TRACE_FAILED",
                                  "org_memory_id": org_memory_id,
                                  "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass

    def _record_debug_attempt_job_memory(self, stage: str, ss: Dict[str, Any],
                                          failure_signature: Optional[Dict[str, Any]],
                                          producing_agent_profile: Optional[str] = None) -> None:
        """Phase 10 AFTER-hook, FAIL/PARTIAL branch (2026-09-03,
        obsidian-memory-debugflow task): "on FAIL, update Job Memory only (no
        promotion)". A debug attempt (FAILURE_RECOVERY triage, or a RE_AUDIT
        fix-verification attempt) that does not close this attempt with PASS
        is real evidence about THIS run -- worth remembering for THIS job so
        a later attempt/agent doesn't re-derive it from zero -- but it is not
        yet reusable cross-run knowledge, so this deliberately calls
        route_and_store() with kind="job_failure" only, never
        kind="root_cause"/"verified_fix"/"debug_lesson" (which would route to
        ENGINEERING_MEMORY and could trigger promotion evaluation on an
        UNVERIFIED attempt -- exactly what the user's spec's "no promotion"
        forbids). `failure_signature` is the SAME real signature the BEFORE
        step (1b-3 above) built for this exact attempt, from the same
        real Blackboard findings/protocol-decision evidence, not a second,
        differently-derived one.

        Best-effort, mirrors every other _promote_*/_record_* method's
        try/except-wrapped route_and_store() call in this class -- a
        persistence failure here must never affect the already-computed real
        stage result run_stage() is about to return."""
        record = {
            "kind": "job_failure",
            "scope": "debug",
            "title": f"{stage} attempt {ss.get('attempts')} did not close ({ss.get('status')})",
            "stage": stage,
            "attempt": ss.get("attempts"),
            "status": ss.get("status"),
            "blocking_reason": ss.get("blocking_reason"),
            "failure_signature": failure_signature,
            "protocol": (failure_signature or {}).get("protocol"),
            "git_sha": self.state.git_sha,
            "producing_agent_profile": producing_agent_profile,
        }
        try:
            promotion = route_and_store(self.root, record, cfg=self.cfg)
        except Exception as exc:
            promotion = {"destination": "PROMOTION_FAILED", "error": str(exc)}
        self.store.event({
            "ts": now(), "stage": stage, "event": "DEBUG_ATTEMPT_JOB_MEMORY_RECORDED",
            "promotion": promotion,
        })

    def _file_capability_evolution_candidates_from_repeated_failures(
            self, stage: str) -> Optional[Dict[str, Any]]:
        """CROSS-LOOP COUPLING (2026-09-05): the Verification Closure Loop
        raising a candidate in the Capability Evolution Loop, automatically.

        Called immediately after _record_debug_attempt_job_memory() above,
        which is the one place a real `kind="job_failure"` record with a real
        `failure_signature` reaches Job Memory from this engine. That call site
        is the whole point: the evidence this reads was written one line
        earlier by the loop that produced it, so the coupling fires on the real
        autonomous path rather than waiting for a human to notice a pattern.

        THE GAP THIS CLOSES. All three loops were individually real and firing
        -- verification closure here, project learning through
        memory_router's tier promotions, capability evolution through
        capability_evolution.py's state machine -- and the EDGE between the
        first and the third did not exist. `router.resolve_intent()` (the
        research route) has no caller in this file, so capability_evolution.py
        was reachable only by a human typing `dv-harness research <doc>`. The
        same real failure could recur across independent runs forever, be
        recorded faithfully in Job Memory every time, and never once raise a
        question about the harness's own capability.

        WHAT IS AUTOMATED IS DISCOVERY, AND ONLY DISCOVERY. This files a
        candidate at DISCOVERED and can reach no further state.
        `file_repeated_failure_candidate()` never calls `transition()` and
        refuses to persist anything not at DISCOVERED; an auto-filed candidate
        performed no repository search and says so, which pins its
        overlap_status at UNKNOWN and (through the candidate schema's own
        allOf) its status at DISCOVERED/EVIDENCE_GATHERING/REJECTED; and every
        gate above that -- assert_legal_transition, assert_human_approval's
        real ControlPlane check, HumanApprovalRequiredError,
        ProductionWriteNotAuthorizedError -- is untouched. Nothing here can
        approve, experiment, or write a production file.

        Best-effort, exactly like the sibling _promote_*/_record_* methods and
        _emit_question_digest_at_stage_boundary(): a capability-evolution
        bookkeeping failure must never turn an already-computed stage result
        into a crash. Every outcome, including "no pattern qualified", is one
        CAPABILITY_EVOLUTION_AUTO_DISCOVERY event in .dv-harness/events.jsonl
        -- a run on which nothing qualified is itself citable evidence, and
        recording it only when something fired would make the trail unreadable
        as a series.
        """
        try:
            from .capability_evolution import file_candidates_for_repeated_failures
            results = file_candidates_for_repeated_failures(self.root, cfg=self.cfg)
        except Exception as exc:
            self.store.event({
                "ts": now(), "stage": stage,
                "event": "CAPABILITY_EVOLUTION_AUTO_DISCOVERY_FAILED",
                "error": str(exc),
            })
            return None
        self.store.event({
            "ts": now(), "stage": stage,
            "event": "CAPABILITY_EVOLUTION_AUTO_DISCOVERY",
            "patterns_detected": len(results),
            "filed": [
                {"candidate_id": r["candidate_id"],
                 "current_status": r["current_status"],
                 "signature_key": r["signature_key"],
                 "independent_run_count": r["independent_run_count"]}
                for r in results if r.get("filed")
            ],
            "not_filed": [
                {"candidate_id": r["candidate_id"], "reason": r["reason"]}
                for r in results if not r.get("filed")
            ],
        })
        return {"results": results}

    def _file_confidence_reweight_candidate_from_calibration(
            self, stage: str) -> Optional[Dict[str, Any]]:
        """CROSS-LOOP COUPLING (2026-09-07): the sibling of
        _file_capability_evolution_candidates_from_repeated_failures() above,
        for the SAME FAILURE_RECOVERY/RE_AUDIT FAIL/PARTIAL moment -- files a
        CapabilityEvolutionCandidate at DISCOVERED from
        confidence_calibration.py's own real, already-computed finding that
        this project's own recorded confirm/retract history CONTRADICTS the
        tier ordering (CONFIRMED > HIGH > MEDIUM > LOW) this harness actually
        acts on (Knowledge Center promotion, Engineering-tier admission,
        qualified-conclusion gating).

        Both draft_reweighted_confidence_proposal() (confidence_calibration.py)
        and build_confidence_reweight_candidate()/file_confidence_reweight_
        candidate() (capability_evolution.py) already existed, real and
        individually tested, with no engine call site -- this method is that
        wire, closing the exact gap those two modules' own CLAUDE.md sections
        disclosed as "REACHED, not WIRED".

        Never a live formula change. calibrate()/draft_reweighted_confidence_
        proposal() perform no write of any kind; file_confidence_reweight_
        candidate() only ever files a DISCOVERED-tier candidate (never calls
        transition(), refuses to persist anything not at DISCOVERED) whose
        every downstream step (a controlled experiment, a shadow-replication
        stability window, a human's HUMAN_APPROVED decision) is untouched and
        uncalled from here -- inference.py's live score_confidence() formula
        is never read, imported, or edited by this method.

        Best-effort, exactly like its sibling: a calibration/filing failure
        must never turn an already-computed stage result into a crash. Every
        outcome, including "no proposal drafted", is one
        CONFIDENCE_REWEIGHT_AUTO_DISCOVERY event in .dv-harness/events.jsonl.
        """
        try:
            from .confidence_calibration import calibrate, draft_reweighted_confidence_proposal
            from .capability_evolution import file_confidence_reweight_candidate
            report = calibrate(self.root, cfg=self.cfg)
            proposal = draft_reweighted_confidence_proposal(report)
            result = file_confidence_reweight_candidate(self.root, proposal, cfg=self.cfg)
        except Exception as exc:
            self.store.event({
                "ts": now(), "stage": stage,
                "event": "CONFIDENCE_REWEIGHT_AUTO_DISCOVERY_FAILED",
                "error": str(exc),
            })
            return None
        self.store.event({
            "ts": now(), "stage": stage,
            "event": "CONFIDENCE_REWEIGHT_AUTO_DISCOVERY",
            "proposal_status": proposal.get("status"),
            "filed": bool(result.get("filed")),
            "reason": result.get("reason"),
            "candidate_id": result.get("candidate_id"),
        })
        return {"proposal": proposal, "result": result}

    def _detect_hypothesis_generation_bias(self, stage: str) -> Optional[Dict[str, Any]]:
        """inference.py gap-close (2026-09-07, REACHED-not-WIRED closure):
        `inference.collect_hypothesis_shapes()` / `detect_hypothesis_
        generation_bias()` were built real, individually tested, with no
        engine call site -- the item's own worked example, "hypotheses
        citing only a symptom register and never a control register are
        wrong more often", surfaces here as a real, cited finding IF this
        project's own retracted-hypothesis history actually shows that
        pattern, never asserted a priori.

        Root-level, read-only, needs no per-stage `block` data -- called at
        the same FAILURE_RECOVERY/RE_AUDIT FAIL/PARTIAL moment as the two
        capability-evolution couplings above, purely for a real,
        already-relevant occasion to refresh it, never because it depends on
        anything either of those wrote. `collect_hypothesis_shapes()` is a
        pure read of this project's own real MemoryStore (constructing one
        only if it does not already exist, mirroring every other real
        MemoryStore call site in this class); `detect_hypothesis_generation_
        bias()` performs no I/O of its own at all.

        Advisory ONLY, per that function's own docstring: this never scores
        a hypothesis, never blocks a stage, and never touches `score_
        confidence()`'s own formula/weights -- a finding here is descriptive
        evidence a human (or a future, separately-approved production
        change) may act on, not a decision this method makes.

        Writes the real result to a new `"hypothesis_generation_bias"`
        Blackboard topic (never re-derived by a reader; the SAME dict this
        method computed) and records one HYPOTHESIS_GENERATION_BIAS_DETECTED
        event, mirroring _trace_memory_lineage_for_promotion()'s own
        event-naming convention -- "no pattern qualified" is itself citable
        evidence, so this fires on every real status, not only BIAS_DETECTED.
        Best-effort: a failure here must never turn an already-computed
        stage result into a crash."""
        try:
            from . import inference as _inf
            hypotheses = _inf.collect_hypothesis_shapes(self.root)
            result = _inf.detect_hypothesis_generation_bias(hypotheses)
            self.blackboard.write("hypothesis_generation_bias", result, source=stage)
            self.store.event({
                "ts": now(), "stage": stage,
                "event": "HYPOTHESIS_GENERATION_BIAS_DETECTED",
                "status": result.get("status"), "reason": result.get("reason"),
                "hypothesis_count": result.get("hypothesis_count"),
                "category_finding_count": len(result.get("category_findings") or []),
                "shape_finding_count": len(result.get("shape_findings") or []),
            })
            return result
        except Exception as exc:
            try:
                self.store.event({
                    "ts": now(), "stage": stage,
                    "event": "HYPOTHESIS_GENERATION_BIAS_DETECTED_FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                })
            except Exception:
                pass
            return None

    def _maybe_run_self_tuning_review(self) -> None:
        """Best-effort autonomous gate self-tuning review -- see
        docs/superpowers/specs/2026-09-02-autonomous-gate-self-tuning-design.md.
        Called once per real terminal run_stage() result (the single
        `return result` at the bottom of that method), regardless of
        stage/verdict -- self-tuning reviews accumulated cross-stage gate
        history, not any one stage's own evidence, so it is deliberately NOT
        gated on verdict == PASS the way the _promote_* methods above are.

        Any failure anywhere in this method must never propagate out and
        must never affect the real stage result run_stage() is about to
        return -- the entire body is one top-level try/except. Two different
        failure-recovery policies apply depending on WHERE the failure is,
        both implemented below rather than via a single blanket "reset on
        any exception" rule:
          - an adapter failure (result missing/not ok, or adapter.run()
            itself raising) does NOT reset the execution counter, so the
            same accumulated history is retried at the next real
            run_stage() call rather than being silently discarded;
          - any OTHER internal failure (malformed/missing evidence block,
            the proposal gate itself failing OR raising an exception, e.g.
            run_gate()'s own subprocess.TimeoutExpired) DOES reset the
            counter -- there is no point re-analyzing the exact same
            evidence again on the very next call when the evidence itself
            was the problem.

        Gate history read here is scoped to self_tuning.read_last_reviewed_index()
        (never the full cumulative gate_history.jsonl since project
        inception) -- a SUCCESSFUL cycle's completion advances that index to
        gate_history_length() via reset_execution_counter's optional
        last_reviewed_index kwarg; an internal-failure early reset
        deliberately omits it, so a failed cycle's un-consumed slice of
        history is still there for the next cycle to see.
        """
        try:
            from . import self_tuning
            from .gates import extract_evidence_blocks, run_gate

            st_cfg = (self.cfg or {}).get("self_tuning", {}) or {}
            if not st_cfg.get("enabled"):
                return
            n = int(st_cfg.get("review_every_n_executions", 20))
            state = self_tuning.read_execution_state(self.root)
            if state.get("executions_since_last_review", 0) < n:
                return

            history = self_tuning.read_gate_history_since(
                self.root, self_tuning.read_last_reviewed_index(self.root))

            # Finding I5 fix (2026-09-02 follow-up): the design spec's
            # "Evidence assembled for the review" section requires FOUR
            # sources, not just gate_history.jsonl (source 1, above) --
            # source 2 (human CORRECT records), source 3 (current tuned
            # state), and source 4 (adjustment history) were all missing
            # from the actual prompt text sent to the adapter. Each is
            # labeled separately below so the LLM can distinguish "raw
            # execution history" from "human corrections" from "already-
            # tuned state" from "past tuning decisions", per the finding's
            # own instruction.
            #
            # Source 2: active `dv-harness correct <stage> --note` records
            # (ControlPlane) -- ControlPlane has no "all corrections across
            # all stages" method (only get_active_correction(stage), a
            # per-stage lookup, and only for the CURRENT unconsumed
            # correction -- consumed/past corrections are not retrievable
            # through any existing ControlPlane API). Building that
            # cross-stage/history infrastructure is out of scope for this
            # fix (see the finding's own instruction to use "whatever
            # granular per-stage method exists" rather than build new
            # ControlPlane infrastructure) -- so this queries the one real
            # existing method, scoped to the distinct stages actually seen
            # in this cycle's gate_history slice (the stages this review is
            # actually about), in first-seen order.
            cp = ControlPlane(self.root)
            seen_stages: List[str] = []
            for entry in history:
                s = entry.get("stage")
                if s and s not in seen_stages:
                    seen_stages.append(s)
            corrections = []
            for s in seen_stages:
                active = cp.get_active_correction(s)
                if active:
                    corrections.append({"stage": s, "note": active.get("note"),
                                         "corrected_by": active.get("corrected_by"),
                                         "at": active.get("at")})

            # Source 3: current tuned state -- the full, current contents of
            # both JSON files self-tuning is ever allowed to write, so the
            # analysis knows what's already been tuned (avoiding redundant
            # re-proposals / detecting thrashing), per the spec.
            current_parameters = self_tuning.read_parameters(self.root)
            current_overrides = self_tuning.read_overrides(self.root)

            # Source 4: adjustment history -- ALL kind="self_tuning_adjustment"
            # records regardless of status (APPLIED/PENDING/BLOCKED_PROTECTED/
            # REJECTED/REVERTED), not just the REVERTED-only subset
            # recent_reverts already narrows to for classify_proposal()'s
            # pure classification rule further below. Capped at the 10 most
            # recent records (read_recent_adjustment_records' own default)
            # -- a project can accumulate an unbounded number of these over
            # its lifetime, and the review only needs recent decisions to
            # avoid re-proposing something just reverted/rejected, not the
            # complete lifetime ledger (which `self-tune list` already
            # exposes in full for a human). Only the fields relevant to
            # "what was decided and why" are kept per record, not the full
            # stored dict (prior_value/applied_by/etc. add prompt size
            # without helping this specific judgment).
            recent_adjustments = [
                {"gate_id": r.get("gate_id"), "stage": r.get("stage"), "change": r.get("change"),
                 "status": r.get("status"), "confidence": r.get("confidence"),
                 "risk_level": r.get("risk_level"), "rationale": r.get("rationale")}
                for r in self_tuning.read_recent_adjustment_records(self.root, limit=10)
            ]

            prompt = (
                "You are reviewing accumulated real gate-execution history to "
                "propose self-tuning adjustments. Four evidence sources follow, "
                "clearly labeled.\n\n"
                "SOURCE 1 -- raw gate-execution history (most recent "
                f"{len(history)} gate invocations since the last review):\n"
                + json.dumps(history) +
                "\n\nSOURCE 2 -- human corrections (active `dv-harness correct` "
                "records for stages seen in SOURCE 1; a human said a gate's "
                "verdict there was wrong):\n" + json.dumps(corrections) +
                "\n\nSOURCE 3 -- current tuned state (what's already been "
                "applied via parameters.json/stage_gate_overrides.json -- avoid "
                "redundant re-proposals of what's already in effect):\n"
                "parameters.json: " + json.dumps(current_parameters) +
                "\nstage_gate_overrides.json: " + json.dumps(current_overrides) +
                "\n\nSOURCE 4 -- adjustment history (up to 10 most recent past "
                "tuning decisions, any status -- do not identically re-propose "
                "one already REJECTED or REVERTED):\n" + json.dumps(recent_adjustments) +
                "\n\nRespond with a single fenced "
                "```dv-harness-evidence:self_tuning_proposal``` block containing "
                '{"proposals": [{"gate_id":..., "stage":... (only for add/remove '
                'changes), "change": {"param":...,"from":...,"to":...} OR '
                '{"action":"add"|"remove","gate_id":...}, "rationale":..., '
                '"confidence":"HIGH"|"MEDIUM"|"LOW", "risk_level":"LOW"|"HIGH"}]}. '
                "Propose zero or more adjustments; an empty list is a valid, "
                "honest answer when the evidence doesn't support any change."
            )

            try:
                result = self.adapter.run(prompt=prompt, cwd=str(self.root))
            except Exception as exc:
                # Finding I8 fix (2026-09-02 follow-up): an operator watching
                # only the event stream previously had no way to tell "a
                # review cycle silently never fired" apart from "a review
                # cycle ran and failed for a specific, nameable reason" --
                # this breadcrumb (and its sibling below) closes that gap.
                # Counter is still NOT reset here (see this method's own
                # docstring on the two failure-recovery policies) -- only
                # the observability is new, not the retry semantics.
                self.store.event({
                    "ts": now(), "stage": "SELF_TUNING", "event": "SELF_TUNING_REVIEW_SKIPPED",
                    "reason": "ADAPTER_EXCEPTION", "detail": str(exc),
                })
                return  # adapter failure -- counter NOT reset, retried next real run_stage()
            if not result or not getattr(result, "ok", False):
                self.store.event({
                    "ts": now(), "stage": "SELF_TUNING", "event": "SELF_TUNING_REVIEW_SKIPPED",
                    "reason": "ADAPTER_NOT_OK",
                })
                return  # same adapter-failure non-reset policy as above

            blocks = extract_evidence_blocks(result.text or "")
            evidence = blocks.get("self_tuning_proposal")
            if not evidence:
                self_tuning.reset_execution_counter(self.root)
                self.store.event({
                    "ts": now(), "stage": "SELF_TUNING", "event": "SELF_TUNING_REVIEW_SKIPPED",
                    "reason": "NO_EVIDENCE_BLOCK",
                })
                return

            try:
                gate_result = run_gate(self.root, "self_tuning_proposal_gate.py", "--proposal", evidence)
            except Exception:
                # The proposal gate script itself failing (e.g. a real
                # subprocess.TimeoutExpired from run_gate()'s own 30s
                # timeout, which run_gate() does not itself catch) is an
                # internal failure of the SAME kind as gate_result.ok being
                # False below -- it means this cycle's evidence could not be
                # mechanically validated, not that the LLM/adapter call
                # failed. Gets the same treatment: reset (not the
                # adapter-failure non-reset policy above), so the next cycle
                # re-derives a fresh proposal rather than retrying against
                # unusable evidence.
                self_tuning.reset_execution_counter(self.root)
                self.store.event({
                    "ts": now(), "stage": "SELF_TUNING", "event": "SELF_TUNING_REVIEW_SKIPPED",
                    "reason": "PROPOSAL_GATE_EXCEPTION",
                })
                return
            if not gate_result.ok:
                self_tuning.reset_execution_counter(self.root)
                self.store.event({
                    "ts": now(), "stage": "SELF_TUNING", "event": "SELF_TUNING_REVIEW_SKIPPED",
                    "reason": "PROPOSAL_GATE_FAILED", "detail": gate_result.detail,
                })
                return

            surviving = gate_result.detail.get("surviving_proposals", [])
            # Bundled fix alongside I3 (2026-09-02 final-review fix wave):
            # this used to hardcode recent_reverts=set(), so classify_
            # proposal()'s anti-thrashing "this gate/param was reverted
            # recently" defer rule could never actually fire. See
            # self_tuning.gate_ids_with_recent_reverts()'s own docstring for
            # the "recent" scoping judgment call (any REVERTED record
            # currently in project memory, no time window).
            recent_reverts = self_tuning.gate_ids_with_recent_reverts(self.root)
            applied_count = 0
            deferred_count = 0
            skipped_count = 0
            for proposal in surviving:
                try:
                    verdict = self_tuning.classify_proposal(proposal, surviving, recent_reverts=recent_reverts)
                    if verdict == "AUTO_APPLY":
                        # Finding I3 fix (2026-09-02 final-review fix wave):
                        # capture the REAL prior parameter state (what
                        # get_param() actually returns right now, including
                        # "no entry existed at all") BEFORE applying --
                        # never trust the proposal's own self-reported
                        # change["from"]. Every AUTO_APPLY proposal is
                        # guaranteed to be a param-change (classify_proposal
                        # now always DEFERs both "add" and "remove"
                        # membership changes -- Finding C1), so change["param"]
                        # is always present here once apply_proposal succeeds.
                        change = proposal.get("change") or {}
                        param = change.get("param")
                        prior_state = (
                            self_tuning.capture_prior_param_state(self.root, proposal.get("gate_id"), param)
                            if param is not None else {"prior_value": None, "prior_was_absent": None}
                        )
                        self_tuning.apply_proposal(self.root, proposal)
                        self_tuning.record_adjustment(
                            self.root, proposal, status="APPLIED",
                            prior_value=prior_state["prior_value"],
                            prior_was_absent=prior_state["prior_was_absent"],
                        )
                        applied_count += 1
                    else:
                        self_tuning.record_adjustment(self.root, proposal, status="PENDING")
                        deferred_count += 1
                except ValueError:
                    # One malformed proposal in the batch must not abort
                    # processing the rest -- skip it and move on. Also
                    # covers apply_proposal()'s defense-in-depth
                    # PROTECTED_PARAMETERS/PROTECTED_REMOVALS ValueErrors
                    # (Findings I1/I2): the proposal gate above should
                    # already have stripped these before they reach
                    # `surviving`, but if one somehow survives, no record is
                    # written for it rather than falsely claiming APPLIED.
                    skipped_count += 1
                    continue

            # Successful completion of a real review cycle -- unlike the
            # internal-failure resets above (which deliberately do NOT
            # advance last_reviewed_gate_history_index, since the evidence
            # they bailed on was never actually consumed), this cycle's
            # gate_history.jsonl slice genuinely was reviewed end to end, so
            # the next cycle's read_gate_history_since() call should only
            # see entries appended after this point, not the same
            # cumulative log again (see self_tuning.reset_execution_counter's
            # own docstring).
            self_tuning.reset_execution_counter(
                self.root, last_reviewed_index=self_tuning.gate_history_length(self.root))
            # Finding I8 fix (2026-09-02 follow-up): the one real "a review
            # cycle actually ran and completed" breadcrumb -- distinct from
            # the SELF_TUNING_REVIEW_SKIPPED events above, which all cover
            # early-return paths where a cycle did NOT reach this point.
            # Emitted even when `surviving` is empty (zero proposals is a
            # valid, complete outcome, not a skip) so an operator can tell
            # "the review ran and genuinely found nothing" apart from any
            # of the SKIPPED reasons above.
            self.store.event({
                "ts": now(), "stage": "SELF_TUNING", "event": "SELF_TUNING_REVIEW_COMPLETED",
                "proposals_found": len(surviving), "applied": applied_count,
                "deferred": deferred_count, "skipped_malformed": skipped_count,
            })
        except Exception:
            pass

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

    def _refresh_declared_subsystem_topics(self, stage: str, node) -> List[Dict[str, Any]]:
        """Refresh the three SUBSYSTEM-written Blackboard topics this stage
        declares in `blackboard_read`, before the stage's prompt snapshots
        them (2026-09-04).

        The gap this closes, from a 2026-09-04 audit: `env_manifest`,
        `open_questions_decisions` and `connectivity_gates` are the only
        topics in this harness NOT written by a graph node's own PASS branch
        (`_write_blackboard_from_evidence()` below). They are written by real
        CLI/runner entry points -- `dv-harness env-manifest generate`,
        `QuestionQueueStore._save_decisions()`, `just connectivity-check` --
        and this file referenced NONE of those modules, no node prompt
        instructed an agent to run either command, and CI ran only
        `connectivity-check --check-only`, which by contract refreshes
        nothing. Seven real graph nodes (ARCH_DISCOVERY, PROJECT_MODEL,
        IMPLEMENT, BUILD_DEBUG, VERIFY, FAILURE_RECOVERY, SIGNOFF) declare
        one or more of them in `blackboard_read`, so a fully autonomous
        `loop()` from INTAKE to SIGNOFF could run start to finish with all
        three permanently absent and nothing on the automatic path producing
        them.

        Driven by the node's OWN `blackboard_read` declaration, never by a
        hardcoded stage list: adding the topic to another node in
        main_graph.json is all it takes to have it refreshed there too, and
        a node that does not read a topic never pays for producing it.

        Each refresher is the REAL producer for its topic (see each
        `ensure_blackboard_topic`), returns a report dict instead of raising,
        and is additionally wrapped here -- same best-effort discipline the
        three sync functions already apply to their own writes. A refresh
        that cannot produce a topic (no manifest generated, no
        connectivity_check.json) leaves it honestly absent; the stage-entry
        checklist already renders a missing `blackboard_read` topic as a
        real unmet input (stage_progress_display.build_stage_entry_checklist),
        so the absence stays visible rather than being papered over.

        Returns one report per attempted topic, recorded as a
        BLACKBOARD_TOPIC_REFRESH event so an audit can answer "was this
        topic ever produced on this run, and if not why" from the real event
        trail instead of from the topic's mere absence."""
        declared = list(getattr(node, "blackboard_read", None) or []) if node is not None else []
        if not declared:
            return []
        reports: List[Dict[str, Any]] = []
        for topic in declared:
            refresher = SUBSYSTEM_TOPIC_REFRESHERS.get(topic)
            if refresher is None:
                continue
            try:
                reports.append(refresher(self.root, self.blackboard))
            except Exception as exc:  # a refresh must never fail a real stage
                reports.append({"topic": topic, "action": "REFRESHER_RAISED",
                                "error": f"{type(exc).__name__}: {exc}"})
        if reports:
            self.store.event({"ts": now(), "stage": stage,
                               "event": "BLACKBOARD_TOPIC_REFRESH",
                               "topics": reports})
        return reports

    def _detect_rca_branch_contradictions(self, contributing: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Genuine cross-branch CONTRADICTION detection at RCA_JOIN's real
        fan-out synthesis point (2026-09-07, fanout_contradiction_detection
        gap close). Additive only: this never changes
        multi_agent_consensus_count / _root_cause_confidence_inputs() above,
        which stay driven solely by RCA_JOIN's own gate-verified
        root_cause_evidence_gate block, and it never touches the existing
        consensus-count accumulation. It adds one new, distinct signal this
        harness never computed before -- do two (or more) of the REAL,
        independently-dispatched RCA_G1 branches, each blind to the others by
        the fan-out's own design (gates.py's own comment: "the fan-out's
        whole point is that they run blind to each other"), name two
        DIFFERENT root causes for the SAME finding? That is a genuinely
        different fact from a branch simply finding nothing (uncorroborated,
        never flagged here) -- CLAUDE.md's Evidence Truth Rule requires a
        real disagreement be surfaced, not silently folded into (or out of)
        a consensus count either way.

        `contributing` is the SAME real contributing_agents list computed
        immediately above from real graph + real state facts (branch really
        PASSed, branch's own topic really written) -- never recomputed a
        second, possibly-disagreeing way. Every claim compared here is read
        straight off that branch's OWN real Blackboard topic, never from
        RCA_JOIN's own agent text, the identical anti-fabrication discipline
        contributing_agents itself already applies. Specifically, it reads
        the root_cause_evidence_gate-shaped block a branch agent MAY have
        emitted even though RCA_RTL_EVIDENCE/RCA_LOG_EVIDENCE/
        RCA_VIP_SPEC_EVIDENCE are deliberately NOT gated on it (gates.py's
        own comment: gating a branch on this gate would push it to invent
        the very cross-domain conclusion RCA_JOIN exists to make -- reading
        it here, never requiring it, respects that boundary).

        Comparison is real-text-exact (case/whitespace-normalized), never
        fuzzy -- the same "never fuzzy" discipline this project's other
        evidence-matching code already applies throughout, so a flagged
        contradiction is always two REAL, textually distinct claims, never a
        guessed semantic difference."""
        branch_claims: List[Dict[str, Any]] = []
        for c in contributing:
            payload = self.blackboard.read(c["stage"])
            bb_value = payload.get("value") if isinstance(payload, dict) else None
            branch_evidence = bb_value.get("evidence") if isinstance(bb_value, dict) else None
            rc_block = (branch_evidence.get("root_cause_evidence_gate")
                        if isinstance(branch_evidence, dict) else None)
            claim = rc_block.get("root_cause") if isinstance(rc_block, dict) else None
            if isinstance(claim, str) and claim.strip():
                branch_claims.append({"stage": c["stage"], "agent": c["agent"],
                                       "root_cause": claim.strip()})
        distinct = {c["root_cause"].lower() for c in branch_claims}
        contradiction_detected = len(distinct) >= 2
        return {
            "contradiction_detected": contradiction_detected,
            "conflicting_claims": branch_claims if contradiction_detected else [],
            "basis": ("two or more RCA_G1 branches independently reported different "
                      "real root_cause claims for this finding" if contradiction_detected else
                      "no two distinct real root_cause claims found among the branches "
                      "that actually contributed evidence (uncorroborated, not contradictory)"),
        }

    def _write_blackboard_from_evidence(self, node, stage: str, evidence: dict, result) -> None:
        writer = STAGE_BLACKBOARD_WRITERS.get(stage)
        values = writer(evidence, stage, result) if writer else _bb_generic_fallback(node, evidence, stage, result)
        if stage == Stage.RCA_JOIN.value and "rca_evidence_fusion" in values:
            # contributing_agents comes from the REAL graph + REAL branch
            # results, never from RCA_JOIN's own agent text -- a synthesis
            # agent claiming three branches corroborated it is exactly the
            # kind of unverified claim CLAUDE.md's Evidence Truth Rule
            # forbids trusting. Same two-fact test _rca_fanout_agent_evidence
            # _count() uses (branch stage really PASSed, branch topic really
            # written).
            contributing = []
            for branch in sorted(self.graph.nodes.values(), key=lambda n: n.id) if self.graph else []:
                if branch.parallel_group != self.RCA_EVIDENCE_FANOUT_GROUP:
                    continue
                if (self.state.stages.get(branch.id) or {}).get("status") != Status.PASS.value:
                    continue
                if all(self.blackboard.read(t) is not None for t in branch.blackboard_write):
                    contributing.append({"stage": branch.id, "agent": branch.agent,
                                          "evidence_topics": list(branch.blackboard_write)})
            values["rca_evidence_fusion"]["contributing_agents"] = contributing
            values["rca_evidence_fusion"]["branch_contradiction_flag"] = (
                self._detect_rca_branch_contradictions(contributing))
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

    # ---- Reliability layer (2026-09-03 user spec: dry-run 模式 / checkpoint
    #      與回滾 / 降級路徑). The four helpers below are what run_stage()
    #      calls; see docs/ENGINE_STAGE_LIFECYCLE.md for the lifecycle view
    #      and dv_harness/degradation.py's module docstring for the DEGRADED
    #      design. ------------------------------------------------------

    def _gather_stage_context(self, user_goal: str, stage: str, cp_state: Dict[str, Any],
                               *, dry_run: bool = False) -> Dict[str, Any]:
        """Steps 1 / 1b / 1b-2 / 1b-3 / 1c of run_stage(), plus the prompt
        build: everything the harness does to decide WHAT to execute, all of
        it BEFORE any adapter call.

        EXTRACTED (2026-09-03, dry-run wiring) rather than duplicated. The
        whole value of a dry-run plan is that it is what the real run would
        actually have done -- if this context gathering existed twice, the
        two copies would drift the first time anyone touched (say) the
        Knowledge Center query, and the "plan" a human reviewed would quietly
        stop matching the run they were approving. One code path, one
        `dry_run` flag, guarantees the equivalence by construction. The
        statement order is unchanged from the original inline code with ONE
        deliberate exception, noted below.

        Everything here is read-only EXCEPT two calls, and those two are
        exactly what `dry_run=True` suppresses:
          - self.plans.create()  -- writes .dv-harness/plans/PLAN-XXXXXXXX.json
          - self.agents.delegate() -- writes an AgentTaskStore task AND
            acquires blackboard-topic ownership for it
        In dry-run, an EXISTING plan is still reused when one is in flight
        (a read), and only a never-persisted in-memory plan is synthesized
        when there is none -- so a dry-run never creates a plan a later real
        run would then treat as "already in flight", and never takes a topic
        lock a concurrent branch would then block on.

        The one deliberate reordering: the prompt is now built here, i.e.
        BEFORE profiler.begin_stage() instead of after it. build_stage_prompt()
        is pure and self.summary() only reads state that begin_stage() does
        not touch, so this is behaviorally inert -- it exists so the dry-run
        path can produce the real prompt without also writing a telemetry
        record for an attempt that never happens.
        """
        node = self.graph.nodes.get(stage) if self.graph else None
        route_info: Optional[dict] = None
        plan: Optional[dict] = None
        bb_snapshot: Dict[str, Any] = {}
        agent_profile = None
        plan_section = ""
        task: Optional[dict] = None
        if node is not None:
            # Order matters (2026-09-04, AI-mechanism re-audit gap #4): the
            # evidence-driven protocol decision is computed FIRST and passed
            # INTO RouteResolver.resolve(), which folds the resolved
            # protocol's real skills into route_info["skills"] for a
            # protocol-sensitive node. SkillResolver then resolves THAT list
            # (not node.skills), and delegate() below delegates THAT route
            # info (not the raw node) -- so the decision is a routing input,
            # not the audit-only telemetry field it used to be. Previously
            # these three ran in the opposite order and resolve_protocol()'s
            # result reached nothing but the prompt/ReAct record.
            protocol_decision = resolve_protocol(self._protocol_router_evidence(user_goal))
            route_info = self.router.resolve(node, protocol_decision=protocol_decision)
            route_info["protocol_decision"] = protocol_decision
            resolved_skills = self.skills.resolve(route_info["skills"])
            route_info["environment_mode_decision"] = resolve_environment_mode(
                self._environment_mode_router_evidence())
            plan = _find_latest_plan(self.plans.dir, stage)
            if plan is None:
                if dry_run:
                    # Never written to disk -- plan_id says so explicitly
                    # rather than carrying a PLAN-XXXXXXXX id that looks
                    # real but names no file.
                    plan = {"plan_id": "DRY-RUN-NOT-PERSISTED", "node_id": stage,
                            "goal": f"{user_goal} :: stage={stage}", "status": "DRY_RUN",
                            "steps": default_plan(node), "revision": 0}
                else:
                    plan = self.plans.create(stage, f"{user_goal} :: stage={stage}", default_plan(node))
            if dry_run:
                # A DESCRIPTION of the delegation that would happen, never a
                # real one: delegate() writes an AgentTaskStore record AND
                # takes blackboard-topic ownership, so a dry-run must not
                # call it (a stale lock would block a later real run). The
                # agent/parallel_group values are the node's real ones, so
                # _build_plan_section() below -- shared, heavily-tested, and
                # deliberately left untouched -- renders the same prompt
                # shape with only the task_id marked as not allocated.
                task = {"task_id": "DRY-RUN-NOT-DELEGATED", "agent": route_info["agent"],
                        "route": route_info["route"], "skills": route_info["skills"],
                        "parent_plan": plan.get("plan_id"),
                        "parallel_group": node.parallel_group, "depends_on": [],
                        "status": "DRY_RUN", "started_at": None,
                        "completed_at": None, "duration_sec": None}
            else:
                task = self.agents.delegate(node, plan, route_info=route_info)
            bb_snapshot = self.blackboard.snapshot(node.blackboard_read) if node.blackboard_read else {}
            agent_profile = load_agent_profile(self.root, route_info["agent"])
            plan_section = _build_plan_section(route_info, resolved_skills, plan, bb_snapshot, task)

        relevant_memory: List[Dict[str, Any]] = []
        try:
            from .memory import MemoryStore, MemoryRetriever
            memory_hits = MemoryRetriever(MemoryStore(self.root)).search({"text": f"{stage} {user_goal}"})
            relevant_memory = [hit["memory"] for hit in memory_hits]
        except Exception:
            relevant_memory = []

        kc_search_results: List[Dict[str, Any]] = []
        if stage in (Stage.FAILURE_RECOVERY.value, Stage.RE_AUDIT.value):
            try:
                kc_client = KnowledgeCenterClient(self.cfg, self.root)
                if kc_client.configured():
                    findings_payload = bb_snapshot.get("findings")
                    findings_value = findings_payload.get("value") if isinstance(findings_payload, dict) else None
                    last_report = findings_value.get("last_report") if isinstance(findings_value, dict) else None
                    query_bits = [user_goal]
                    if isinstance(last_report, dict):
                        for key in ("symptom", "failure_signature_before", "root_cause"):
                            v = last_report.get(key)
                            if v:
                                query_bits.append(str(v))
                    query_text = " ".join(query_bits)[:500]
                    kc_protocol = ((route_info or {}).get("protocol_decision") or {}).get("protocol") or ""
                    kc_result = kc_client.search(category="root_cause", protocol=kc_protocol, text=query_text)
                    if kc_result.get("ok"):
                        kc_search_results = kc_result.get("records") or []
            except Exception:
                kc_search_results = []

        vault_related_cases: List[Dict[str, Any]] = []
        debug_failure_signature: Optional[Dict[str, Any]] = None
        if stage in (Stage.FAILURE_RECOVERY.value, Stage.RE_AUDIT.value):
            try:
                findings_payload = bb_snapshot.get("findings")
                findings_value = findings_payload.get("value") if isinstance(findings_payload, dict) else None
                last_report = findings_value.get("last_report") if isinstance(findings_value, dict) else None
                symptom = last_report.get("symptom") if isinstance(last_report, dict) else None
                root_cause_hint = None
                if isinstance(last_report, dict):
                    root_cause_hint = last_report.get("root_cause") or last_report.get("failure_signature_before")
                debug_failure_signature = build_failure_signature(
                    protocol=((route_info or {}).get("protocol_decision") or {}).get("protocol"),
                    symptom=symptom, root_cause_hint=root_cause_hint, extra_text=user_goal,
                )
                vault_search = search_related_memory_for_debug(
                    self.root, self.cfg, debug_failure_signature, limit=5)
                vault_related_cases = vault_search.get("related_cases") or []
            except Exception:
                vault_related_cases = []

        entry_checklist = build_stage_entry_checklist(node, self.blackboard, self.root,
                                                        stage_history=self.state.stages)

        constraints = [c["text"] for c in cp_state.get("constraints", [])]
        correction = cp_state.get("corrections", {}).get(stage)
        correction_note = correction["note"] if correction and not correction.get("consumed") else None
        approval = cp_state.get("approvals", {}).get(stage)
        prompt = build_stage_prompt(stage, self.summary(), user_goal,
                                     constraints=constraints,
                                     correction_note=correction_note,
                                     human_approval=approval,
                                     relevant_memory=relevant_memory or None,
                                     kc_search_results=kc_search_results or None,
                                     vault_related_cases=vault_related_cases or None)
        if plan_section:
            prompt = prompt + plan_section

        # REGRESSION_SELECT only: compute the real RTL-diff impact scope and
        # show it to the agent BEFORE it writes its own selection (2026-09-04,
        # Section 3 item 3a). Placed after the plan section so it is the last
        # thing in the prompt, and gated on the stage so no other stage pays
        # for a git diff it has no use for. The same computation writes
        # .dv-harness/regression/computed_selection.json, which
        # regression_selection_completeness_gate.py then enforces the agent's
        # answer against (add-only, never drop) -- so this is a real
        # mechanism, not merely advisory prompt text.
        computed_selection: Optional[Dict[str, Any]] = None
        if stage == Stage.REGRESSION_SELECT.value:
            computed_selection = self._computed_regression_selection()
            if computed_selection:
                from .change_impact import render_selection_section
                prompt = prompt + render_selection_section(computed_selection)

        return {
            "computed_selection": computed_selection,
            "node": node, "route_info": route_info, "plan": plan, "bb_snapshot": bb_snapshot,
            "agent_profile": agent_profile, "plan_section": plan_section, "task": task,
            "relevant_memory": relevant_memory, "kc_search_results": kc_search_results,
            "vault_related_cases": vault_related_cases,
            "debug_failure_signature": debug_failure_signature,
            "entry_checklist": entry_checklist, "constraints": constraints,
            "correction_note": correction_note, "approval": approval, "prompt": prompt,
        }

    def _dry_run_stage(self, user_goal: str, stage: str, cp_state: Dict[str, Any]) -> AgentResult:
        """dry-run 模式: "agent 產出完整計畫但不執行, 人可事前檢視。導入初期與
        大改動前必用."

        Produces the FULL intended plan/evidence-request for this stage --
        the real resolved route/agent/protocol/environment-mode decisions,
        the real plan steps, the real Blackboard/Memory/Knowledge-Center/
        Vault context, the real entry checklist, and the byte-exact prompt
        that would have been sent -- and then stops. It reuses
        _gather_stage_context(dry_run=True), so this is genuinely "what the
        real run would have done", not a separate approximation.

        What is guaranteed NOT to happen (the precise side-effect call sites
        in the normal path, each verified against this file rather than
        assumed):
          - self.adapter.run()                  -- no LLM/adapter call at all
          - self.plans.create()                 -- no plan file written
          - self.agents.delegate()/start_task()/complete_task()
          - self.profiler.begin_stage()/add_agent_run()/end_stage()
          - self.store.save()/self.store.event() -- no state.json/events.jsonl write
          - ss["status"]/["attempts"]/["started_at"] mutation
          - self.react.record(), self._write_blackboard_from_evidence()
          - replan_stage(), cp.consume_correction(), cp.clear_approval()
          - every _promote_*/_persist_*/_score_*/_append_* knowledge write
          - self_tuning.increment_execution_counter()
          - session_snapshot auto-checkpointing (there is no transition to
            checkpoint -- nothing moved)
        No LSF submission is possible either: run_stage() has no bsub call
        site at all. Every real submission in this codebase goes through
        `dv-harness lsf-submit` -> lsf_client.bsub_submit_with_preflight()
        (cli.py), a separate command a dry-run never reaches. The dry-run
        test asserts this rather than trusting the claim.

        The ONE write is the explicit dry-run report the spec permits:
        `.dv-harness/dry_run/<stage>-<timestamp>.json`, which is the artifact
        a human reviews. It lives in its own directory precisely so it can
        never be confused with -- or restored as -- real run state; note that
        `dry_run` is not in session_snapshot.SESSION_DIRS, so these reports
        are deliberately never copied into a session snapshot either.
        """
        ctx = self._gather_stage_context(user_goal, stage, cp_state, dry_run=True)
        node = ctx["node"]
        route_info = ctx["route_info"] or {}
        plan = ctx["plan"] or {}
        ss = self.state.stages.get(stage, {})
        report = {
            "dry_run": True,
            "generated_at": now(),
            "stage": stage,
            "user_goal": user_goal,
            "project": self.state.project,
            "git_sha": self.state.git_sha,
            "would_execute": {
                "adapter": type(self.adapter).__name__,
                "agent": route_info.get("agent"),
                "route": route_info.get("route"),
                # The RESOLVED skill list (static graph skills plus whatever
                # this run's protocol decision added), and the static list it
                # was folded onto, so a human reviewing the dry-run can see
                # exactly what the evidence-driven decision changed.
                "skills": route_info.get("skills"),
                "static_skills": route_info.get("static_skills"),
                "protocol_skill_routes": route_info.get("protocol_skill_routes"),
                "protocol_decision": route_info.get("protocol_decision"),
                "environment_mode_decision": route_info.get("environment_mode_decision"),
                "resume_session": ss.get("session_id") or None,
                "agent_profile_found": bool(getattr(ctx["agent_profile"], "found", False)),
            },
            "plan": {
                "plan_id": plan.get("plan_id"),
                "persisted": plan.get("plan_id") != "DRY-RUN-NOT-PERSISTED",
                "revision": plan.get("revision"),
                "steps": plan.get("steps", []),
            },
            # The evidence the stage would be judged on: which gates must
            # accept this stage's output, and what the entry checklist says
            # is already present. This is the "evidence-request" half of the
            # plan a human reviews before authorizing a real run.
            "required_gates": [gid for gid, _, _ in STAGE_GATES.get(stage, [])],
            "entry_checklist": ctx["entry_checklist"],
            "expected_outputs": list(getattr(node, "expected_outputs", []) or []) if node else [],
            "blackboard_read": list(getattr(node, "blackboard_read", []) or []) if node else [],
            "blackboard_write": list(getattr(node, "blackboard_write", []) or []) if node else [],
            "context_counts": {
                "relevant_memory": len(ctx["relevant_memory"]),
                "kc_search_results": len(ctx["kc_search_results"]),
                "vault_related_cases": len(ctx["vault_related_cases"]),
                "constraints": len(ctx["constraints"]),
            },
            "human_controls": {
                "correction_note": ctx["correction_note"],
                "approval": ctx["approval"],
            },
            # The real prompt, in full. This is the point of a dry-run: a
            # human can read exactly what the agent would be asked.
            "prompt": ctx["prompt"],
        }
        out_dir = self.root / ".dv-harness" / "dry_run"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{stage}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(out_path)
        print(f"[dv-harness] DRY_RUN stage={stage}: plan written to {out_path} "
              f"(nothing executed, no state changed).")
        return AgentResult(
            ok=True,
            text=(f"DRY_RUN: produced the full intended plan for stage {stage} without executing it. "
                  f"Report: {out_path}"),
            raw=report,
            session_id=None,
        )

    def _degradation_cfg(self) -> Dict[str, Any]:
        block = self.cfg.get("degradation")
        return block if isinstance(block, dict) else {}

    def _dry_run_cfg(self) -> Dict[str, Any]:
        # Same isinstance guard as _degradation_cfg()/_auto_checkpoint()'s own
        # `auto_checkpoint` read: `self.cfg.get("dry_run") or {}` only covers
        # a FALSY misconfiguration (None, "", 0) -- a truthy-but-wrong-shaped
        # value (e.g. `"dry_run": true` or `"dry_run": ["enabled"]` from a
        # hand-edited config.json) would still reach `.get("enabled", ...)`
        # and raise AttributeError instead of failing toward "dry-run off".
        block = self.cfg.get("dry_run")
        return block if isinstance(block, dict) else {}

    def _resolve_degradation_transport(self, requested: Optional[str] = None):
        """Chooses the real transport for DEGRADED mode's license/queue
        probes. `requested` (from `dv-harness --degradation-transport`) wins
        over config.json's `degradation.transport`; both default to "auto",
        which arms a transport only when one is genuinely confirmed here.

        Best-effort like every other side effect in this class: if resolution
        itself blows up (a broken tools/remote/, an unreadable config), the
        harness runs with NO probe transport rather than failing to start --
        an unreachable probe must never become an unbootable harness.
        """
        try:
            from . import degradation
            return degradation.resolve_transport(self.cfg, requested=requested)
        except Exception as e:  # noqa: BLE001
            from .preflight import TransportDecision, TRANSPORT_NONE
            return TransportDecision(requested=str(requested or "auto"),
                                      resolved=TRANSPORT_NONE, available=False,
                                      reason=f"transport resolution failed: {type(e).__name__}: {e}",
                                      evidence={})

    def set_degradation_transport(self, requested: Optional[str]):
        """Re-resolves and installs the DEGRADED-mode probe transport for
        this process -- the call site behind `dv-harness
        --degradation-transport {auto,local,remote_relay,off}`. Returns the
        TransportDecision so a caller can report what it actually got (an
        explicitly requested transport is honoured, but the decision still
        carries the real probe evidence, so "you asked for local and lmutil
        is not on PATH" is visible rather than silent)."""
        self.degradation_transport = self._resolve_degradation_transport(requested)
        self.degradation_runner = self.degradation_transport.runner
        return self.degradation_transport

    def _degraded_gate(self, stage: str) -> Optional[AgentResult]:
        """降級路徑, enforced. Returns a DEGRADED AgentResult when this stage
        must NOT attempt a judgment-requiring transition, or None to proceed
        normally.

        Order of operations matters: the license/queue triggers are
        RE-EVALUATED against real current evidence first (degradation.
        evaluate(), rate-limited by probe_min_interval_sec), so a condition
        that has cleared lets this same call fall straight through to normal
        operation -- the harness resumes on its own rather than needing a
        human to un-stick it. Only if a trigger is still live do we degrade.

        While degraded the harness keeps doing real DATA COLLECTION -- it
        writes an auto-checkpoint session snapshot and appends a real
        DEGRADED_CYCLE event carrying the live trigger detail -- and refuses
        only the judgment call (no adapter.run() proposing a verdict/next
        action, no gate evaluation, no stage transition). Entirely
        best-effort: any failure inside this gate leaves the harness in
        NORMAL operation rather than stranding it in a state it cannot get
        out of, the same discipline regression_reporter.py's
        _escalate_uvm_fatal_burst_if_needed() applies to its own side effects.
        """
        conf = self._degradation_cfg()
        if not conf.get("enabled", True):
            return None
        try:
            from . import degradation
            degradation.evaluate(self.root, self.cfg, runner=self.degradation_runner)
            if not degradation.is_degraded(self.root):
                return None
            reason = degradation.blocking_reason(self.root)
            detail = degradation.describe(self.root)
            ss = self.state.stages[stage]
            # ss["status"] MUST be set, not just overall_status: loop() reads
            # ss["status"] to decide what to do next, and its final fallthrough
            # is an unconditional self.advance() -- i.e. a stage left at
            # NOT_STARTED here would be routed along the graph's PASS edge as
            # though a stage that never ran had passed. WAIT_USER is the
            # existing status loop() already stops cleanly on (the TAKEOVER
            # path above sets exactly the same one for the same reason), so a
            # degraded harness parks instead of advancing or tight-looping --
            # "只收集資料、不做判斷", never 胡亂重試. blocking_reason carries the
            # real trigger detail, so the WAIT_USER is never unexplained.
            ss["status"] = Status.WAIT_USER.value
            ss["blocking_reason"] = reason[:2000]
            self.state.overall_status = Status.WAIT_USER.value
            self.store.save(self.state)

            # Real, persisted data collection while degraded -- ordered AFTER
            # the store.save() above so the snapshot and the event both record
            # the degraded state itself, not the state as it was a moment
            # before it was marked.
            self.store.event({"ts": now(), "stage": stage, "event": "DEGRADED_CYCLE",
                               "triggers": detail["triggers"],
                               "trigger_details": detail["trigger_details"],
                               "degraded_cycles": detail["degraded_cycles"] + 1})
            degradation.note_cycle(self.root)
            self._auto_checkpoint(stage, note=f"degraded cycle: {reason[:300]}")

            print(f"[dv-harness] {reason}")
            return AgentResult(ok=False, text=reason,
                                raw={"degraded": True, "stage": stage, **detail},
                                session_id=None)
        except Exception as e:
            print(f"[dv-harness] degradation check failed (continuing normally): {e}")
            return None

    # ---- Planner -> Execution Layer -------------------------------------
    #
    # Which graph-node skills mark a stage as an EXECUTION-LAYER stage: one
    # whose routed agent's actual job is to build, submit, or drive real work
    # on the DV farm (`.dv-harness/graph/main_graph.json` gives `vcs-build` to
    # DE_BASELINE_REPRODUCTION / BUILD / BUILD_DEBUG and `devops-pipeline` to
    # SERVER_SYNC / REGRESSION / INFRA_RECOVERY -- exactly the BUILD/
    # REGRESSION family). Skills, not a hardcoded stage-name list, because the
    # graph is the single place stage->work-kind is already declared, so a
    # project that adds its own build node inherits this gate for free.
    EXECUTION_PREFLIGHT_SKILLS = ("devops-pipeline", "vcs-build")

    def _execution_preflight_cfg(self) -> Dict[str, Any]:
        block = self.cfg.get("execution_preflight")
        return block if isinstance(block, dict) else {}

    def _execution_preflight_skills(self, stage: str) -> List[str]:
        """The execution-layer skills THIS stage's real graph node declares
        (empty for every non-execution stage). Read from self.graph so a
        node-less/legacy stage simply never triggers the gate."""
        node = self.graph.nodes.get(stage) if self.graph is not None else None
        declared = list(getattr(node, "skills", None) or []) if node is not None else []
        want = self._execution_preflight_cfg().get("skills")
        want = [s for s in want if isinstance(s, str)] if isinstance(want, list) \
            else list(self.EXECUTION_PREFLIGHT_SKILLS)
        return [s for s in declared if s in want]

    def _execution_preflight_gate(self, stage: str) -> Optional[AgentResult]:
        """Planner -> Execution Layer, enforced. Returns a BLOCKED
        AgentResult when this stage must NOT dispatch its build/regression
        agent because the real farm resources it is about to consume are not
        there, or None to proceed normally.

        WHY THIS EXISTS: before this gate, run_stage() had no call site into
        dv_harness/preflight.py's full check suite at all -- the architecture
        diagram's "Planner -> Execution Layer -> Preflight Agent" arrow was
        satisfied only by _degraded_gate()'s narrow license+queue slice (2 of
        the 6 real checks, and only to decide whether to skip an LLM judgment
        call), while run_preflight()'s full suite -- disk, workdir, env, host
        included -- was reachable ONLY from `dv-harness preflight` and
        `dv-harness lsf-submit`, i.e. never from a stage transition. This
        closes that specific edge: the same real preflight code, the same
        `preflight` config block, now runs as part of the Planner's own flow
        for exactly the stages whose agent is about to build or submit.

        It does NOT replace lsf_client.bsub_submit_with_preflight() -- that
        remains the authoritative gate immediately before a real `bsub`. This
        one is earlier and cheaper: it stops the harness from spending a full
        agent dispatch (a real `claude` subprocess with full tool access) on a
        stage whose farm resources are already known to be unavailable.

        CONFIG, and why probe_resources is OFF by default: identical
        reasoning to degradation.probe_resources (config.py states it in
        full) -- run_preflight() shells out to real `lmutil`/`bqueues`/`df`/
        `test -d`/csh env probes, which per preflight.py's own transport
        docstring exist only where dv_harness runs server-side on the Linux DV
        server. On a PC-side session those binaries are simply absent, and
        reading "command not found" as evidence of a jammed farm would be a
        fabricated BLOCK. A server-side deployment turns this on; a PC-side
        one in REMOTE_EXECUTION mode assigns
        preflight.RemoteRelayCommandRunner() to execution_preflight_runner and
        probes the REAL server through the already-sanctioned relay, the same
        injected-transport seam degradation_runner uses.

        Unlike degradation's probe, this one does NOT force
        require_license_configured=False: it honours the project's `preflight`
        block verbatim, exactly as `dv-harness preflight` and `dv-harness
        lsf-submit` already do -- there is no second place to configure this,
        and a deployment that deliberately opted this gate on is a deployment
        whose preflight block carries its real values.

        WAIT_USER (not a retry) on BLOCKED, for _degraded_gate()'s own stated
        reason: loop() reads ss["status"], and its fallthrough is an
        unconditional advance(), so a blocked stage must park on a status
        loop() already stops cleanly on rather than be advanced as though it
        had passed. blocked_on carries the real failing check names, so the
        park is never unexplained. Best-effort like every other side effect in
        this file: a crash inside the gate leaves the stage running normally
        rather than stranding it -- an unreachable probe must never become an
        unbreakable block.
        """
        conf = self._execution_preflight_cfg()
        if not conf.get("enabled", True):
            return None
        skills = self._execution_preflight_skills(stage)
        if not skills:
            return None
        if not conf.get("probe_resources", False) and self.execution_preflight_runner is None:
            return None
        try:
            from . import preflight as _preflight
            pf_cfg = _preflight.config_from_dict(self.cfg.get("preflight"))
            result = _preflight.run_preflight(pf_cfg, runner=self.execution_preflight_runner)
            if result.overall == "PASS":
                # LOOP-3, section 92: the check-before-submit half is what just
                # PASSed; this is the PRIORITIZATION half. The same real
                # CheckOutcomes are re-read (never re-probed -- a second lmstat
                # round trip for a fact this run just measured would be exactly
                # the parallel mechanism this project forbids) for the band
                # BETWEEN "plenty" and "fully checked out", which a PASS verdict
                # alone cannot express and which degradation.py deliberately
                # says nothing about. The measurement is ALWAYS recorded in this
                # event; whether a low-value stage is actually deferred for it
                # is `loop_budget.defer_low_value_under_pressure` (off by
                # default). It can only ever DEFER -- it never lets a stage
                # preflight BLOCKED proceed.
                priority = self._resource_priority_decision(stage, skills, result.checks)
                self.store.event({"ts": now(), "stage": stage,
                                   "event": "EXECUTION_PREFLIGHT_PASS",
                                   "execution_skills": skills,
                                   "resource_priority": priority,
                                   "preflight": result.to_dict()})
                deferral = self._defer_stage_under_resource_pressure(stage, skills, priority)
                if deferral is not None:
                    return deferral
                return None
            reason = (f"EXECUTION_PREFLIGHT_BLOCKED: stage {stage} routes an execution-layer "
                      f"agent (skills={skills}) but dv_harness/preflight.py reports "
                      f"{result.overall} on {result.blocked_on}. No agent dispatched. "
                      f"Fix the farm/environment condition, or run `dv-harness preflight` "
                      f"for the full check detail.")
            ss = self.state.stages[stage]
            ss["status"] = Status.WAIT_USER.value
            ss["blocking_reason"] = reason[:2000]
            self.state.overall_status = Status.WAIT_USER.value
            self.store.save(self.state)
            self.store.event({"ts": now(), "stage": stage,
                               "event": "EXECUTION_PREFLIGHT_BLOCKED",
                               "execution_skills": skills,
                               "blocked_on": result.blocked_on,
                               "preflight": result.to_dict()})
            self._auto_checkpoint(stage, note=f"execution preflight blocked: {reason[:300]}")
            print(f"[dv-harness] {reason}")
            return AgentResult(ok=False, text=reason,
                                raw={"preflight_blocked": True, "stage": stage,
                                     "execution_skills": skills,
                                     "preflight": result.to_dict()},
                                session_id=None)
        except Exception as e:
            print(f"[dv-harness] execution preflight check failed (continuing normally): {e}")
            return None

    def _auto_checkpoint(self, stage: str, note: str = "") -> None:
        """Automatic stage-transition recovery point ("每個階段留可回復點,
        agent 走偏時不必從頭"). session_snapshot.save_session() already does
        all the real work including source-identity protection on restore --
        this only makes it fire automatically instead of only on an explicit
        `dv-harness save-session`, with the bounded retention that turning a
        manual action into an automatic one requires.

        Best-effort, wrapped exactly like every other real side effect in
        this file and like regression_reporter.py's
        _escalate_uvm_fatal_burst_if_needed(): a snapshot is a convenience
        for recovering from a bad run, and failing to take one must never
        itself break the real cycle. A full disk, a Windows file lock on a
        file being copied, or a permission error prints and continues.
        """
        conf = self.cfg.get("auto_checkpoint")
        conf = conf if isinstance(conf, dict) else {}
        if not conf.get("enabled", True):
            return
        try:
            from . import session_snapshot
            attempts = self.state.stages.get(stage, {}).get("attempts")
            session_snapshot.save_auto_checkpoint(
                self.root, stage=stage, attempt=attempts, note=note,
                keep=int(conf.get("keep_last", session_snapshot.DEFAULT_AUTO_CHECKPOINT_KEEP)))
        except Exception as e:
            print(f"[dv-harness] auto-checkpoint failed (stage {stage}, continuing): {e}")

    def run_stage(self, user_goal: str, stage: Optional[str] = None, dry_run: bool = False):
        stage = stage or self.state.current_stage
        # dry-run resolves from the explicit argument (CLI --dry-run) OR the
        # config toggle -- the flag can turn dry-run ON, never off. See
        # config.py's `dry_run` block for why a config that silently disabled
        # an explicitly-requested dry-run would be the dangerous direction.
        dry_run = bool(dry_run) or bool(self._dry_run_cfg().get("enabled", False))

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

        # dry-run, checked SECOND -- after TAKEOVER (a human holding the
        # stage outranks everything, including a request to plan it) and
        # before every state mutation below, including the stage-entry
        # marker: a dry-run never starts the stage, so it must not print a
        # START it never earns, exactly the reasoning the TAKEOVER
        # short-circuit above already applies to itself.
        #
        # Deliberately checked BEFORE the DEGRADED gate: a dry-run makes no
        # adapter call and no judgment at all, so it is precisely the kind
        # of read-only planning that stays safe (and useful) while the farm
        # or the API is unavailable. Refusing to plan while degraded would
        # deny the operator the one action that still works.
        if dry_run:
            return self._dry_run_stage(user_goal, stage, cp_state)

        # 降級路徑: enters/stays DEGRADED (collect data, make no judgment) or
        # falls through to normal operation once the condition clears. See
        # _degraded_gate() and dv_harness/degradation.py.
        degraded = self._degraded_gate(stage)
        if degraded is not None:
            return degraded

        # Planner -> Execution Layer: for a BUILD/REGRESSION-family stage
        # (graph node declaring `vcs-build`/`devops-pipeline`), run
        # dv_harness/preflight.py's REAL full check suite before spending an
        # agent dispatch on farm resources that are not there. Placed here,
        # beside the DEGRADED gate and before _emit_stage_start_marker() /
        # the attempts++ below, so a blocked stage consumes no retry budget
        # and adapter.run() is never reached. See
        # _execution_preflight_gate()'s docstring for why this does not
        # replace lsf_client.bsub_submit_with_preflight().
        blocked = self._execution_preflight_gate(stage)
        if blocked is not None:
            return blocked

        # Subsystem-written Blackboard topics (env_manifest /
        # open_questions_decisions / connectivity_gates) this node declares
        # in `blackboard_read`, produced by their REAL entry points before
        # anything reads them -- see _refresh_declared_subsystem_topics()
        # for why nothing on the autonomous path produced them before.
        # Placed here, after the DEGRADED/preflight gates (a run making no
        # judgment must not spend a connectivity gate run) and BEFORE the
        # stage-entry display and _gather_stage_context()'s
        # blackboard.snapshot(), so both the human-facing entry checklist
        # and the agent's own prompt see the refreshed topics.
        self._refresh_declared_subsystem_topics(
            stage, self.graph.nodes.get(stage) if self.graph else None)

        # Distinctive stage-entry marker (see STAGE_MARKER_PREFIX's RULING
        # comment above) -- emitted here, AFTER the TAKEOVER short-circuit
        # above (a takeover'd call never actually starts the stage, so it
        # must not print a START it never earns) and BEFORE any state
        # mutation, so it always fires exactly once per real attempt.
        _emit_stage_start_marker(stage)
        # The human-facing half of the same boundary (banner + required-input
        # checklist + completeness % + "needs your detail" reminder + saved
        # report). Deliberately BEFORE the attempts++ below so the ATTEMPT
        # number it shows is the attempt about to run, counted the same way
        # the checklist's own "what did the previous attempt supply" read is.
        try:
            _emit_stage_start_display(
                self.root, stage, self.graph.nodes.get(stage) if self.graph else None,
                self.blackboard, self.state.stages, graph=self.graph,
                attempt=self.state.stages[stage]["attempts"] + 1)
        except Exception as exc:  # observability must never fail a real stage
            print(f"{STAGE_MARKER_PREFIX} stage start display unavailable: {exc}", flush=True)

        ss = self.state.stages[stage]
        ss["status"] = Status.RUNNING.value
        ss["attempts"] += 1
        ss["started_at"] = now()
        self.state.overall_status = Status.RUNNING.value
        self.state.git_sha = self._git_sha() or self.state.git_sha
        self.store.save(self.state)

        # ---- 1. Plan / route / Blackboard / Memory / Knowledge-Center /
        #         Vault context + the stage prompt, all gathered BEFORE the
        #         LLM call so the agent's response is genuinely informed by
        #         an explicit plan/route/prior-state instead of the plan
        #         being write-only metadata.
        #
        #         EXTRACTED into _gather_stage_context() (2026-09-03, dry-run
        #         wiring) so `dv-harness run-stage --dry-run` produces the
        #         plan THIS path would really have executed, from this exact
        #         code, rather than a second implementation that would drift.
        #         See that method's docstring for the full step-by-step
        #         (former inline steps 1 / 1b / 1b-2 / 1b-3 / 1c) and for the
        #         only two calls dry-run suppresses (plans.create /
        #         agents.delegate).
        ctx = self._gather_stage_context(user_goal, stage, cp_state)
        node = ctx["node"]
        route_info = ctx["route_info"]
        plan = ctx["plan"]
        bb_snapshot = ctx["bb_snapshot"]
        agent_profile = ctx["agent_profile"]
        task = ctx["task"]
        debug_failure_signature = ctx["debug_failure_signature"]
        entry_checklist = ctx["entry_checklist"]
        correction_note = ctx["correction_note"]
        approval = ctx["approval"]
        prompt = ctx["prompt"]

        profile = self.profiler.begin_stage(stage, stage, graph_node=stage,
            metadata={"git_sha": self.state.git_sha}, entry_checklist=entry_checklist)
        resume = ss.get("session_id") or None

        # ---- Multi-agent task lifecycle start (2026-09-01,
        #      multi-agent-timing-reconciliation pass): AgentTaskStore.
        #      create_task() (step 1's `self.agents.delegate(node, plan, route_info=...)`
        #      above) previously produced a task dict with zero timing
        #      fields and nothing ever called a completion method -- the
        #      delegation/locking layer was completely disconnected from
        #      this same method's own perf_counter-based agent-runtime
        #      measurement below. start_task() is called here, immediately
        #      before the adapter.run() call this task was delegated for --
        #      the real point where the delegated unit of work actually
        #      begins executing. `task` is None for a node-less stage (no
        #      delegation happened in step 1), so there is nothing to start.
        if task is not None:
            self.agents.store.start_task(task["task_id"])
        _t0 = time.perf_counter()

        # ---- 2. Multi-Agent dispatch: the resolved agent is threaded all
        #         the way into the adapter call, not just appended as a
        #         string in the prompt. See adapters/cli.py's NOTICE for the
        #         exact --agent/--allowedTools/--disallowedTools mechanism
        #         and its honestly-documented limitation. ------------------
        result = self.adapter.run(prompt=prompt, cwd=str(self.root), resume_session=resume,
                                   agent_profile=agent_profile)
        _agent_runtime = time.perf_counter() - _t0
        # ---- Multi-agent task lifecycle end + stage_profile reconciliation
        #      (2026-09-01, multi-agent-timing-reconciliation pass): complete
        #      the SAME task started immediately above, right after this
        #      exact adapter.run() call returns -- the task's status here
        #      tracks whether the delegated agent CALL completed
        #      (COMPLETED/FAILED), which is deliberately narrower than the
        #      stage's own gate-verified business status (ss["status"],
        #      resolved further below and possibly refined by an inner
        #      ReAct loop this task's scope does not cover).
        #
        #      RULING: reconciliation is done by having engine.py read
        #      AgentTaskStore's own real duration_sec and feed it into
        #      profiler.add_agent_run() below, in place of a second,
        #      independently-computed number for the exact same span --
        #      this reuses the existing profiler sink instead of adding a
        #      parallel aggregation path or duplicating timing data across
        #      the two stores. The local perf_counter _agent_runtime above
        #      is kept only as the fallback for a node-less stage (no task
        #      was ever created, so there is no AgentTaskStore duration to
        #      read) -- every real graph-node stage now reports the
        #      MultiAgentOrchestrator/AgentTaskStore's own measured
        #      duration_sec through this same call, not a shadow timer.
        if task is not None:
            _completed_task = self.agents.store.complete_task(
                task["task_id"], status=("COMPLETED" if result.ok else "FAILED"))
            _agent_runtime = _completed_task["duration_sec"]
        _usage = extract_provider_usage(result.raw or {})
        _model = ((result.raw or {}).get("response") or {}).get("model", "")
        # Per-agent-attribution fix (2026-09-01 audit): this used to hardcode
        # the literal "stage-agent" regardless of which real agent actually
        # ran -- route_info["agent"] (from self.router.resolve(node, ...) above,
        # step 1) is the real resolved agent name for this stage and is
        # already in scope by the time this call runs. A node-less stage
        # (route_info is None -- no graph node at all, e.g. a legacy/no-graph
        # stage) has no resolved agent to name, so "stage-agent" remains the
        # honest fallback for exactly that case, not the default.
        _resolved_agent_name = route_info["agent"] if route_info else "stage-agent"
        self.profiler.add_agent_run(profile["profile_id"], _resolved_agent_name, _agent_runtime,
            usage=_usage, model=str(_model),
            status=("PASS" if result.ok else "FAIL"))

        if result.session_id:
            ss["session_id"] = result.session_id
            self.state.last_session_id = result.session_id
        ss["last_message"] = result.text[-6000:] if result.text else ""
        ss["finished_at"] = now()

        # 降級路徑, evidence collection point (2026-09-03): this adapter call
        # just succeeded or failed for real, and that outcome IS the evidence
        # for the TRIGGER_ADAPTER condition ("Claude API 不可用"). Recorded
        # here, at the one place run_stage() already knows the answer, rather
        # than by a separate poller that would have to guess. This only
        # COUNTS -- it never retries and never re-calls the adapter; stage
        # retry stays entirely in loop()'s existing max_stage_retries policy.
        # Best-effort on both sides: a degradation-bookkeeping failure must
        # never change the real stage result already in `result`.
        # Gated on the same `enabled` flag _degraded_gate() honours, so a
        # project that turned degradation off gets no degradation.json
        # written at all -- a disabled feature should leave no trace on disk.
        if self._degradation_cfg().get("enabled", True):
            try:
                from . import degradation
                if result.ok:
                    degradation.record_adapter_success(self.root, self.cfg)
                else:
                    degradation.record_adapter_failure(
                        self.root, self.cfg, stage=stage,
                        detail=(result.raw or {}).get("stderr", "") or (result.text or ""))
            except Exception as e:
                print(f"[dv-harness] degradation bookkeeping failed (continuing): {e}")

        if result.ok and stage == Stage.COVERAGE_CLOSURE.value:
            # Differentiated coverage-hole remediation (2026-09-04, Section 3
            # item 3b). Runs BEFORE gate evaluation, because the gate's
            # UNREACHABLE_STIMULUS branch verifies that a real question-queue
            # entry exists -- and this is what creates it. An agent that
            # honestly classifies a bin as structurally unreachable therefore
            # gets the correct action (ask the design owner) performed for it,
            # instead of being told to invent another testcase, which was the
            # old gate's only accepted answer for that class.
            self._escalate_unreachable_coverage_holes(result.text)

        evidence_blocks: Dict[str, Any] = {}
        # Initialized here rather than only inside the result.ok branch below:
        # step 4's _react_step_inference() call reads it on EVERY exit path,
        # including ADAPTER_FAIL (which never evaluates a gate and so never
        # assigns it there).
        structured_signatures: List[Any] = []
        # THIS attempt's own inner-ReAct reroute choice, deliberately a local
        # rather than a read of ss["react_reroute_target"]: that state key
        # survives across attempts and is only ever rewritten on the inner-
        # ReAct branch, so reading it back at step 4 would attribute a prior
        # attempt's reroute to an attempt that never made one.
        react_reroute_target: Optional[str] = None
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
                # gate verdict. RE_AUDIT joins this hard-stop, but ONLY when
                # this attempt's own fix_risk_approval_gate evidence is
                # HIGH-risk_level or DUT_BUG-classification (see
                # _re_audit_requires_human_approval's docstring above) -- a
                # routine TB_BUG/low-risk RE_AUDIT closure is unaffected.
                _re_audit_gated = (stage == Stage.RE_AUDIT.value
                                    and _re_audit_requires_human_approval(evidence_blocks))
                if stage in (Stage.PROMOTION_READINESS.value, Stage.SIGNOFF.value) or _re_audit_gated:
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
                    # This attempt's own canonical protocol decision, the same
                    # value already threaded into InnerReactLoop below. Both
                    # Engineering-tier writers need it as their record's dedup
                    # key -- see _engineering_record_protocol().
                    _promotion_protocol = (
                        ((route_info or {}).get("protocol_decision") or {}).get("protocol")
                    )
                    self._promote_experience_knowledge(stage, evidence_blocks,
                                                       resolved_protocol=_promotion_protocol,
                                                       producing_agent_profile=_resolved_agent_name)
                    self._persist_subsystem_registry_entry(stage, evidence_blocks)
                    self._refresh_requirement_vplan_center_snapshot(stage, evidence_blocks)
                    self._export_signoff_bundle(stage)
                    self._compose_soc_environment_files(stage, evidence_blocks)
                    self._score_root_cause_confidence(stage, evidence_blocks, verdict,
                                                       profile_id=profile["profile_id"],
                                                       agent_name=_resolved_agent_name)
                    self._append_coverage_history_sample(stage, evidence_blocks)
                    self._promote_project_topology_knowledge(
                        stage, evidence_blocks, producing_agent_profile=_resolved_agent_name)
                    self._promote_vplan_summary_knowledge(
                        stage, evidence_blocks, producing_agent_profile=_resolved_agent_name)
                    self._promote_verified_fix_knowledge(stage, evidence_blocks,
                                                         resolved_protocol=_promotion_protocol,
                                                         producing_agent_profile=_resolved_agent_name)
                    self._arm_rca_evidence_fanout(stage, evidence_blocks)
            elif verdict == "NEEDS_USER_INPUT":
                # BUG FIX (2026-08-28, plan-interactive-intake-completeness
                # design pass): previously this was indistinguishable from
                # any other GATE_FAIL -- a genuine "the agent needs an answer
                # from you before it can continue" moment (INTAKE's
                # intake_readiness gate, and since 2026-09-04
                # WAVE_ANALYSIS/FAILURE_RECOVERY's unconfirmed waveform dump
                # scope; see gates.py) looked identical to "the agent
                # supplied invalid evidence".
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
                blocking_reason = ("NEEDS_USER_INPUT: " + "; ".join(str(r) for r in reasons))[:2000]
                # The ask half of the Waveform Dump User Gate's round-trip,
                # on the AUTONOMOUS path. Parking at WAIT_USER is correct but
                # was not sufficient: the question the run is blocked on was
                # never actually filed unless the headless subprocess happened
                # to shell out to `dv-harness waveform-dump-scope ask` itself,
                # so the human returning to the parked run had an empty queue.
                # Appended AFTER the [:2000] truncation deliberately -- the
                # real Q-ID and the single command that unblocks the run must
                # never be the part that gets cut off.
                filed = self._file_waveform_dump_scope_question(stage, evidence_blocks)
                if filed is not None:
                    blocking_reason += (
                        f"\n[dv-harness] 已自動把這題送進 question queue（Q-ID {filed['id']}，"
                        f"tier {filed['tier']}，status {filed['status']}）。真人只要執行："
                        f"\n  dv-harness question-queue answer {filed['id']} "
                        f"--answer <APPROVE/NARROW/WIDEN ...> --basis <依據> --decided-by <你的名字>"
                        f"\n然後重跑 `dv-harness start --loop` 即可從這個 stage 續跑。")
                ss["blocking_reason"] = blocking_reason
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
                # profiler/profile_id/agent_name (2026-09-01 per-agent-
                # attribution fix): route_info is guaranteed non-None here
                # (this whole elif is nested under `node is not None`, and
                # route_info is only ever unset when node is None), so
                # route_info["agent"] is always the real resolved agent name
                # for every InnerReactLoop the real engine flow creates --
                # never the "" default this constructor otherwise falls back
                # to for the module's own unit tests. This is what lets
                # InnerReactLoop attribute its own real adapter.run() calls
                # (reflection + RETRY_TARGETED/REQUEST_EVIDENCE retries) to
                # this same stage profile instead of leaving them invisible.
                # protocol (2026-09-04): the SAME RouteResolver-resolved
                # protocol already folded into this attempt's route_info --
                # build_menu()'s NO_EVIDENCE_BLOCK_SUPPLIED source needs it to
                # cite a real protocol_builder_registry.json item, since a
                # gate that never ran cannot name a protocol in its own detail.
                outcome = InnerReactLoop(
                    self.root, self.adapter, self.react, self.cfg, graph=self.graph,
                    profiler=self.profiler, profile_id=profile["profile_id"],
                    agent_name=route_info["agent"],
                    protocol=((route_info or {}).get("protocol_decision") or {}).get("protocol"),
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
                react_reroute_target = outcome.reroute_target or None
                ss["react_reroute_target"] = react_reroute_target

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

        # ---- 3c. Debug-flow AFTER hook, FAIL/PARTIAL branch (Phase 10,
        #          2026-09-03, obsidian-memory-debugflow task): a debug
        #          attempt (FAILURE_RECOVERY triage, or a RE_AUDIT
        #          fix-verification attempt) that does NOT close this
        #          attempt with PASS updates Job Memory ONLY -- never
        #          Engineering/Organizational Memory, per the user's spec
        #          ("on FAIL, update Job Memory only (no promotion)"): a fix
        #          that has not yet been proven is not reusable knowledge.
        #          The PASS side of this same AFTER contract is handled
        #          entirely by the existing _promote_verified_fix_knowledge()
        #          call above (RE_AUDIT only, gated on verdict=="PASS") --
        #          FAILURE_RECOVERY's own STAGE_GATES never include
        #          fix_effectiveness_gate, so a FAILURE_RECOVERY PASS is
        #          "triage complete", not "debug succeeded", and correctly
        #          writes nothing here either way. WAIT_USER/NEEDS_USER_INPUT
        #          are deliberately excluded: those are "PASS pending a human
        #          action" or "need an answer to continue", neither a failed
        #          debug attempt.
        if (stage in (Stage.FAILURE_RECOVERY.value, Stage.RE_AUDIT.value)
                and ss["status"] in (Status.FAIL.value, Status.PARTIAL.value)):
            self._record_debug_attempt_job_memory(
                stage, ss, debug_failure_signature,
                producing_agent_profile=_resolved_agent_name)
            # ---- 3d. CROSS-LOOP COUPLING (2026-09-05): the record just
            #          written is the newest piece of the evidence this reads.
            #          Files a CapabilityEvolutionCandidate at DISCOVERED when
            #          >= 2 INDEPENDENT runs share one failure_signature that
            #          no gate-verified verified_fix record closes -- and can
            #          reach no state past DISCOVERED. See the method's own
            #          docstring for why every human-approval gate is
            #          untouched by it.
            self._file_capability_evolution_candidates_from_repeated_failures(stage)
            # ---- 3e. CROSS-LOOP COUPLING (2026-09-07): the sibling coupling
            #          above catches a REPEATED failure signature; this one
            #          catches this project's own recorded confirm/retract
            #          history CONTRADICTING the confidence-tier ordering the
            #          harness acts on, via confidence_calibration.py's own
            #          real calibrate() report. Same DISCOVERED-only, never a
            #          live formula change, best-effort discipline -- see the
            #          method's own docstring.
            self._file_confidence_reweight_candidate_from_calibration(stage)
            # ---- 3f. inference.py gap-close (2026-09-07): advisory-only
            #          hypothesis-generation-bias detection over this
            #          project's own real retracted-hypothesis history. See
            #          the method's own docstring for why this scores no
            #          hypothesis and blocks nothing.
            self._detect_hypothesis_generation_bias(stage)

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
            # Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action,
            # the full chain CLAUDE.md's Engineering Memory Policy specifies
            # for this exact record kind: `confidence`/`gap`/`next_action`
            # below are now real dv_harness.inference.score_confidence()/
            # identify_gap()/next_best_action() output over this attempt's own
            # gate signatures and evidence blocks, not the status-keyed string
            # literals they used to be. See _react_step_inference().
            step_inference = self._react_step_inference(
                stage, evidence_blocks, structured_signatures,
                adapter_ok=bool(result.ok),
                reroute_target=react_reroute_target,
                protocol=((route_info or {}).get("protocol_decision") or {}).get("protocol"),
            )
            # Agent self-escalation signal (2026-09-07, agent_self_escalation
            # gap-close): best-effort, over the SAME step_inference just
            # computed above -- see _record_agent_escalation_signal()'s own
            # docstring for why this is deliberately NOT a question_queue.py
            # record and never itself dispatches anything.
            self._record_agent_escalation_signal(
                stage, step_inference,
                context_path=f".dv-harness/react/{stage}/iteration_{ss['attempts']:03d}.json",
            )
            # Human-facing low-confidence checkpoint (gap-close 2026-09-07,
            # no-human-facing-preaction-low-confidence-checkpoint): the
            # missing HUMAN counterpart to the agent-facing signal recorded
            # one call above -- see dv_harness.low_confidence_human_
            # checkpoint's own module docstring for the full design and its
            # disclosed residual (filing a real Tier-3 blocking question
            # here does not, by itself, halt this stage mid-call).
            self._file_low_confidence_human_checkpoint(
                stage, step_inference,
                context_path=f".dv-harness/react/{stage}/iteration_{ss['attempts']:03d}.json",
            )
            # action carries route/protocol_decision/environment_mode_decision
            # (2026-09-03, gap-close-engine cleanup): these three resolver
            # decisions were previously folded ONLY into the ephemeral
            # _build_plan_section() prompt string sent to the adapter (step 1
            # above) and a transient local read for the KC search query --
            # never persisted anywhere, so none of them were inspectable
            # after the fact. This reuses this SAME already-real per-attempt
            # audit record (iteration_NNN.json under .dv-harness/react/<node>/,
            # plus its Working Memory tier projection) rather than inventing a
            # new persistence mechanism -- the established pattern this
            # codebase already uses to make a resolver decision auditable,
            # exactly like route_info["agent"] immediately below.
            self.react.record(
                node=stage,
                iteration=ss["attempts"],
                reason_summary=_reason_summary(route_info, plan, bb_snapshot),
                action={"adapter": type(self.adapter).__name__,
                        "agent": route_info["agent"] if route_info else None,
                        "route": route_info["route"] if route_info else None,
                        # The resolved skill list actually delegated this
                        # attempt, alongside the node's static one -- without
                        # both, an after-the-fact auditor cannot tell whether
                        # protocol_decision below changed anything.
                        "skills": (route_info or {}).get("skills"),
                        "static_skills": (route_info or {}).get("static_skills"),
                        "protocol_skill_routes": (route_info or {}).get("protocol_skill_routes"),
                        "protocol_decision": (route_info or {}).get("protocol_decision"),
                        "environment_mode_decision": (route_info or {}).get("environment_mode_decision"),
                        "resume_session": resume},
                tool="ClaudeAdapter.run",
                observation={"ok": result.ok, "status": ss["status"], "session_id": result.session_id},
                evidence=evidence_blocks,
                confidence=step_inference["confidence"],
                next_action=step_inference["next_action"],
                gap=step_inference["gap"],
                confidence_detail=step_inference["confidence_detail"],
                # The prior knowledge this attempt REALLY consulted (2026-09-04,
                # gap-close-obsidian-memory phase 13+14): the same three lists
                # _gather_stage_context() folded into the prompt above, projected
                # to references only. Until now they were transient -- built fresh
                # per run_stage() call and never persisted -- so
                # session_snapshot.save_session() had to re-run its own
                # MemoryRetriever.search() at save time and could report memory
                # this stage never saw. See react.build_memory_context_references().
                memory_context=build_memory_context_references(
                    relevant_memory=ctx.get("relevant_memory"),
                    kc_search_results=ctx.get("kc_search_results"),
                    vault_related_cases=ctx.get("vault_related_cases"),
                ),
            )

        # This attempt's own extracted evidence blocks, persisted onto the
        # stage's own state so a LATER attempt's build_stage_entry_checklist
        # (see its docstring) can see what was last actually submitted here
        # -- never cleared to {} on an attempt that produced none (e.g. an
        # ADAPTER_FAIL), so a checklist still reflects the last real
        # submission rather than "nothing was ever submitted".
        if evidence_blocks:
            ss["last_evidence_blocks"] = evidence_blocks

        self.store.event({
            "ts": now(), "stage": stage, "ok": result.ok,
            "session_id": result.session_id, "summary": ss["last_message"][-1000:]
        })
        self.store.save(self.state)
        # ---- 5. Stage exit evidence checklist: the symmetric counterpart to
        #         entry_checklist above, over node.expected_outputs, computed
        #         now that the gate verdict is known -- see
        #         build_stage_exit_checklist's own docstring for why it reads
        #         `evidence_blocks` (THIS attempt's own output) rather than
        #         the just-persisted last_evidence_blocks. Informational
        #         only: never alters ss["status"], persisted into the SAME
        #         per-attempt telemetry record profiler.end_stage() already
        #         writes. ------------------------------------------------
        exit_checklist = build_stage_exit_checklist(node, self.blackboard, self.root,
                                                      evidence_blocks=evidence_blocks)
        self.profiler.end_stage(profile["profile_id"], status=ss["status"],
            finding_count=self.state.findings_total, closed_finding_count=self.state.findings_closed,
            exit_checklist=exit_checklist)

        # ---- 6. "Just transitioned" persisted signal + distinctive stage-exit
        #         marker (2026-09-01, runtime-progress-visibility pass): ss["status"]
        #         is now the FINAL terminal status this attempt reached (PASS/FAIL/
        #         PARTIAL/WAIT_USER -- run_stage() never returns while still
        #         RUNNING). describe_stage() is called here rather than reusing the
        #         local `verdict` variable because `verdict` is only ever assigned on
        #         the `result.ok` branch above -- an ADAPTER_FAIL (the `else` branch)
        #         never sets it at all. describe_stage() recomputes gate_verdict/
        #         stage_completion_percent uniformly from ss["last_message"] for
        #         EVERY exit path, so this marker (and last_transition below) is
        #         byte-consistent with what `dv-harness explain`/`evidence` would
        #         already report for this exact stage/attempt.
        stage_detail = describe_stage(self.root, self.state, stage)
        self.state.last_transition = {
            "stage": stage, "status": ss["status"], "at": now(),
        }
        self.store.save(self.state)
        _emit_stage_done_marker(stage, stage_detail.get("gate_verdict"),
                                 stage_detail.get("stage_completion_percent"))
        # Human-facing stage-DONE half: banner + output checklist +
        # completeness % + total time (including every sub-agent run) and
        # tokens + saved report. Placed after profiler.end_stage() above so
        # the telemetry record it reads back is the COMPLETED one (wall clock
        # and per-agent totals are only final once end_stage() has run), and
        # it reuses stage_detail's already-computed verdict/percent rather
        # than re-evaluating the gates a second time.
        try:
            _emit_stage_done_display(
                self.root, stage, node, self.blackboard, evidence_blocks,
                stage_detail.get("gate_verdict"),
                stage_detail.get("stage_completion_percent"),
                gate_reasons=stage_detail.get("gate_reasons"), graph=self.graph)
        except Exception as exc:  # observability must never fail a real stage
            print(f"{STAGE_MARKER_PREFIX} stage done display unavailable: {exc}", flush=True)

        # ---- 6b. Automatic stage-transition checkpoint (2026-09-03, user
        #          spec: "checkpoint 與回滾：每個階段留可回復點, agent 走偏時不
        #          必從頭"). Fired HERE, immediately after last_transition and
        #          its store.save() above, for a specific reason: this is the
        #          point where the stage's FINAL terminal status is both
        #          decided AND already persisted, so the snapshot captures the
        #          completed transition rather than a half-written one. It is
        #          also on the single real terminal exit path every verdict
        #          branch falls through to (see step 7's own comment below for
        #          why that is true), so exactly one checkpoint is taken per
        #          real attempt -- PASS, FAIL, PARTIAL and WAIT_USER alike,
        #          since "agent 走偏" is precisely the non-PASS case a human
        #          most needs to roll back from.
        #
        #          session_snapshot.save_session() already does all the real
        #          work, including the git-SHA source-identity mismatch
        #          protection restore_session() enforces -- nothing about
        #          checkpointing is rebuilt here. Best-effort and bounded:
        #          see _auto_checkpoint() and session_snapshot.
        #          prune_auto_checkpoints().
        self._auto_checkpoint(stage, note=f"auto stage transition: {stage} -> {ss['status']}")

        # ---- 7. Autonomous gate self-tuning review (2026-09-02 design):
        #         this is the ONE real terminal exit point of run_stage() --
        #         every verdict branch above (PASS, WAIT_USER/approval-
        #         required, NEEDS_USER_INPUT, PARTIAL/GATE_FAIL,
        #         FAIL/ADAPTER_FAIL) falls through to here rather than
        #         returning early; the only earlier `return` in this method
        #         is the TAKEOVER short-circuit at the very top, which exits
        #         before any adapter call/state mutation happens at all and
        #         so is not a real completed execution attempt. The counter
        #         increments here unconditionally (once per real terminal
        #         verdict, regardless of which one), and the review itself
        #         is entirely best-effort (see _maybe_run_self_tuning_review's
        #         own docstring) -- neither call is allowed to affect
        #         `result`, already computed above. The increment itself is
        #         real file I/O (self_tuning._write_json_atomic) and must be
        #         wrapped the same way gates.py's run_gate()/_log_gate_history
        #         already wraps its own self_tuning.append_gate_history()
        #         call ("never allowed to change run_gate()'s own return
        #         value or raise") -- a disk-full/permission/transient
        #         Windows file-lock race here (documented real phenomena
        #         elsewhere in this codebase, e.g. config.py's save_config
        #         docstring and dashboard.py's PermissionError retry logic)
        #         must never destroy the already-computed real stage result
        #         about to be returned below. ----------------------------
        try:
            self_tuning.increment_execution_counter(self.root)
        except Exception:
            pass
        self._maybe_run_self_tuning_review()
        return result

    # main_graph.json's one CONDITIONAL parallel_group (2026-09-03,
    # multi-agent-orchestrator gap closure). ANALYSIS_G1 is unconditional:
    # PROTOCOL_CAPABILITY's PASS edges lead ONLY to its three branches, so
    # next_frontier() already resolves it with no state to consult.
    # FAILURE_RECOVERY is different -- its PASS frontier deliberately mixes
    # the three RCA_G1 evidence branches WITH the original CHANGE_IMPACT
    # edge, because CLAUDE.md scopes multi-agent evidence acquisition to
    # "important DUT/PHY/Register/VIP changes", not to every triaged failure
    # (rca-multi-agent-fusion.js's own `whenToUse` draws the same line: a
    # failure one evidence domain already explains should stay on the single
    # sequential path). The real, gate-verified discriminator is
    # FAILURE_RECOVERY's own issue_triage_classification_gate verdict --
    # see _arm_rca_evidence_fanout().
    RCA_EVIDENCE_FANOUT_GROUP = "RCA_G1"

    def _resolve_conditional_fanout_frontier(self, source_node: str, frontier: List[str]) -> List[str]:
        """Narrows a PASS frontier that mixes RCA_G1 fan-out branches with a
        non-fan-out sequential target down to whichever set this failure's
        real triage classification authorized, and CONSUMES the arming token
        when it hands back the fan-out.

        Byte-identical passthrough for every other frontier in the graph: a
        frontier of 0/1 targets, or one containing no RCA_G1 branch at all
        (ANALYSIS_G1's three branches included), is returned unchanged, so
        neither the existing unconditional fan-out nor any ordinary single-
        edge stage transition is affected by this method existing."""
        if len(frontier) <= 1 or self.graph is None:
            return frontier
        branches = [t for t in frontier
                    if (self.graph.nodes.get(t) is not None
                        and self.graph.nodes[t].parallel_group == self.RCA_EVIDENCE_FANOUT_GROUP)]
        if not branches:
            return frontier
        sequential = [t for t in frontier if t not in branches]
        armed = self.state.rca_evidence_fanout_armed
        if not armed:
            self.store.event({"ts": now(), "stage": source_node,
                               "event": "RCA_EVIDENCE_FANOUT_NOT_ARMED",
                               "parallel_group": self.RCA_EVIDENCE_FANOUT_GROUP,
                               "sequential_target": sequential[0] if sequential else None})
            return sequential or frontier
        # Single-use: one gate-verified REAL_ISSUE triage authorizes exactly
        # one fan-out. A later FAILURE_RECOVERY PASS must re-arm from its own
        # fresh triage evidence (CLAUDE.md: "Any current root cause must be
        # revalidated with current evidence") rather than inheriting this
        # one's authorization.
        self.state.rca_evidence_fanout_armed = None
        self.store.save(self.state)
        self.store.event({"ts": now(), "stage": source_node,
                           "event": "RCA_EVIDENCE_FANOUT_DISPATCHED",
                           "parallel_group": self.RCA_EVIDENCE_FANOUT_GROUP,
                           "branches": sorted(branches), "armed_by": armed})
        return branches

    def _emit_question_digest_at_stage_boundary(self, completed_stage: str) -> Optional[dict]:
        """Fire question_queue's batched digest + the 4 tracking metrics at a
        real regression-cycle boundary.

        `question_queue.build_digest()`'s own docstring named this exact call
        site and left it open: "A caller wires this in by calling
        build_digest(store, trigger='stage_boundary', stage=new_stage) right
        after its own stage-transition code runs (not wired into engine.py
        itself in this change -- engine.py's stage-transition path is owned by
        a concurrent workstream this session)". That workstream landed; this
        is the wiring. Until it existed, `build_digest()` and
        `compute_metrics()` each had exactly ONE caller in the whole repo --
        the hand-typed `dv-harness question-queue digest` / `... status` CLI
        verbs -- so an unattended `loop()` run batched nothing for a human to
        answer and recorded none of the 4 metrics, exactly the DORMANT shape
        the Methodology Consolidation Rule warns about.

        advance() is the single canonical "the current stage finished
        successfully, move on" path: loop() delegates to it on every PASS, and
        commands.cmd_advance() (`dv-harness next`) calls it directly. Hooking
        it here rather than in set_stage() is deliberate -- set_stage() and
        human_redirect() also fire on human reroutes and on loop()'s
        FAIL-edge routing, which are not "a stage completed" boundaries and
        would emit a digest in the middle of a failure recovery.

        Only DIGEST_BOUNDARY_STAGES (end of a regression run / coverage
        closure / re-audit cycle / signoff) do any work -- build_digest()
        enforces that itself, and it is re-checked here so an ordinary stage
        transition does not pay for loading the queue at all. Never
        real-time: an ordinary stage boundary emits nothing.

        Best-effort by design, mirroring _file_waveform_dump_scope_question():
        a question-queue failure must never turn a completed stage transition
        into a crash. Returns None when nothing was emitted.
        """
        try:
            from .question_queue import DIGEST_BOUNDARY_STAGES, QuestionQueueStore
            if completed_stage not in DIGEST_BOUNDARY_STAGES:
                return None
            store = QuestionQueueStore(self.root, blackboard=self.blackboard)
            digest = store.build_digest(trigger="stage_boundary", stage=completed_stage)
            metrics = store.compute_metrics()
        except Exception as exc:
            self.store.event({"ts": now(), "stage": completed_stage,
                               "event": "QUESTION_QUEUE_DIGEST_FAILED", "error": str(exc)})
            return None
        # Recorded on EVERY boundary crossing, including emitted=False. A
        # metrics series with datapoints only on the cycles that happened to
        # have pending questions is not a series -- and "this cycle had
        # nothing to escalate" is itself citable evidence.
        self.store.event({
            "ts": now(), "stage": completed_stage,
            "event": "QUESTION_QUEUE_DIGEST", "trigger": "stage_boundary",
            "emitted": digest["emitted"], "batch_id": digest["batch_id"],
            "question_count": len(digest["questions"]),
            "by_owner": {owner: len(qs) for owner, qs in digest["by_owner"].items()},
            "metrics": metrics,
        })
        return {"digest": digest, "metrics": metrics}

    def advance(self, user_goal: str = ""):
        # QUESTION-QUEUE DIGEST BOUNDARY (2026-09-05): the stage being advanced
        # PAST is the one that just completed, so it is captured here before
        # any of the fan-out/graph resolution below can move current_stage. A
        # no-op for every stage outside DIGEST_BOUNDARY_STAGES, and fail-soft.
        self._emit_question_digest_at_stage_boundary(self.state.current_stage)

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
        # every node except PROTOCOL_CAPABILITY and FAILURE_RECOVERY today.
        # Only when it returns more than one target does
        # _advance_with_fanout() run at all.
        #
        # FAILURE_RECOVERY (2026-09-03, RCA_G1 multi-agent gap closure) is the
        # second real fan-out source, and the first CONDITIONAL one:
        # _resolve_conditional_fanout_frontier() below decides between its
        # RCA_G1 evidence branches and its original single CHANGE_IMPACT edge
        # from FAILURE_RECOVERY's own gate-verified triage classification.
        resolved_single = None
        if self.graph is not None:
            raw_frontier = self.graph.next_frontier(self.state.current_stage, Status.PASS.value)
            frontier = self._resolve_conditional_fanout_frontier(self.state.current_stage, raw_frontier)
            if len(frontier) > 1:
                return self._advance_with_fanout(self.state.current_stage, frontier, user_goal)
            if len(frontier) == 1 and len(raw_frontier) > 1:
                # A conditional fan-out that was NOT armed this time: the one
                # surviving target (e.g. CHANGE_IMPACT) is the real sequential
                # edge. Named explicitly here rather than left to
                # graph_next(), whose next_for() picks the lowest-priority-
                # number matching edge -- correct for FAILURE_RECOVERY today
                # only because main_graph.json deliberately gives its
                # CHANGE_IMPACT edge priority 10 against the RCA_G1 branches'
                # 100. Every non-narrowed frontier (every other node in the
                # graph) still falls through to the unchanged graph_next()
                # path below, which is the ONLY thing that knows how to pass
                # THROUGH a synthetic non-Stage node like ANALYSIS_JOIN.
                resolved_single = frontier[0]
        if resolved_single is not None:
            n = resolved_single
        else:
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
            self._record_loop_state_observation(b, occasion="FANOUT_BRANCH_FAILED")
            if n and n != b:
                self.state.current_stage = n
            else:
                self.state.current_stage = b
                n = b
            self.store.save(self.state)
            return n

        # All branches PASSed. Two genuinely different kinds of join node
        # exist in main_graph.json and they must not be treated alike:
        #
        #   - A SYNTHETIC join node with no corresponding Stage enum member
        #     (ANALYSIS_JOIN) is pure graph bookkeeping -- there is no
        #     StageState for it, no STAGE_INSTRUCTIONS, and run_stage() could
        #     not execute it. graph_next()'s existing synthetic-node
        #     passthrough already knows how to skip through it to the real
        #     next Stage (VPLAN), so the lookup starts FROM the join node
        #     rather than from the last branch. Unchanged behavior.
        #   - A REAL executable join Stage (RCA_JOIN, 2026-09-03) is the
        #     independent-synthesis half of CLAUDE.md's "Multi-Agent evidence
        #     acquisition plus independent synthesis" rule: analysis_debug
        #     re-reads the three RCA_G1 branches' own Blackboard topics and
        #     rules on them under root_cause_evidence_gate. Passing THROUGH
        #     it would silently delete the synthesis half of the mechanism,
        #     so current_stage advances TO it and the next loop()/run-stage
        #     call executes it for real.
        if join_node in ORDER:
            n = join_node
        else:
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

    def loop(self, user_goal: str, dry_run: bool = False):
        """`dry_run=True` plans the CURRENT stage and returns immediately,
        without looping.

        This is a deliberate design decision, not a shortcut. loop()'s only
        way to reach a next stage is advance()/graph_next(), which route on a
        REAL terminal status produced by a real gate evaluation of a real
        adapter response. A dry-run produces none of those, so the only way
        to "keep looping" would be to invent a verdict for a stage that never
        ran and then plan the stage that fictional verdict pointed to --
        precisely the fabricated-evidence failure CLAUDE.md's Evidence Truth
        Rule forbids, and it would make the reviewed plan diverge further
        from reality at every step. Planning one real stage against real
        current state is honest; a speculative N-stage plan is not.

        Reviewing the whole pipeline is therefore an iterative, real loop:
        dry-run a stage, review it, run it for real, dry-run the next.
        """
        if dry_run or bool(self._dry_run_cfg().get("enabled", False)):
            return self.run_stage(user_goal, stage=self.state.current_stage, dry_run=True)
        # LOOP-4, section 108: open this loop SESSION's telemetry. Deliberately
        # after the dry-run early return -- a dry run dispatches one stage and
        # iterates nothing, so calling it a loop session would put a row in the
        # Loop Engineering Center for a loop that never ran. `_ls` is section
        # 86's state vocabulary, imported (never restated) so a telemetry event
        # can never name a state loop_contract does not have.
        from .loop_contract import LoopState as _ls
        self._begin_loop_telemetry(user_goal)
        while True:
            stage = self.state.current_stage
            self._emit_loop_iteration_started(stage)

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
                # LOOP-4: a takeover is BOTH "a human decision is owed" and
                # "this session ended", so both events are real and both are
                # emitted -- the human-gate one first, then exactly one
                # terminal event, which is the invariant a test holds loop() to.
                self._emit_loop_event(
                    "LOOP_HUMAN_GATE_REQUIRED", stage=stage,
                    loop_state=_ls.HUMAN_GATE.value, reason="TAKEOVER_ACTIVE",
                    blocking_reason=ss.get("blocking_reason", "")[:600],
                    resume_condition="dv-harness release-takeover")
                self._end_loop_telemetry(
                    "LOOP_STOPPED", stage=stage, loop_state=_ls.HUMAN_GATE.value,
                    reason="TAKEOVER_ACTIVE",
                    resume_condition="dv-harness release-takeover, then dv-harness start --loop")
                return
            if cp_state.get("paused"):
                reason = cp_state.get("paused_reason", "")
                print(f"[dv-harness] PAUSED" + (f" ({reason})" if reason else "")
                      + " -- loop stopped cleanly before running the next stage. "
                        "Run `dv-harness resume` to continue.")
                self._end_loop_telemetry(
                    "LOOP_STOPPED", stage=stage, loop_state=_ls.STOPPED.value,
                    reason=f"PAUSED: {reason}" if reason else "PAUSED",
                    resume_condition="dv-harness resume, then dv-harness start --loop")
                return

            # Section 93's circuit breaker (LOOP-3). Deliberately checked AFTER
            # both Human Override checks above, so a human's takeover/pause
            # always outranks it, and BEFORE the SIGNOFF gate and run_stage(),
            # because an OPEN breaker means "STOP NEW ACTIONS". It fires only on
            # a budget this project DECLARED (`loop_budget.limits.*`, empty by
            # default) or on a declared identical-repeat threshold, so a default
            # configuration never reaches it. It authorizes nothing -- see
            # _circuit_breaker_gate()'s docstring.
            if self._circuit_breaker_gate(stage):
                self._end_loop_telemetry(
                    "LOOP_BLOCKED", stage=stage, loop_state=_ls.BLOCKED.value,
                    reason="CIRCUIT_BREAKER_OPEN",
                    blocking_reason=(self.state.stages[stage].get("blocking_reason")
                                     or "")[:600],
                    resume_condition=("dv-harness loop-budget breaker-reset "
                                      "--reason ... --by ..."))
                return

            if stage == Stage.SIGNOFF.value:
                # self.blackboard (2026-09-04): can_signoff()'s qualified-
                # conclusion check needs the REAL Blackboard the RE_AUDIT PASS
                # wrote its QualifiedConclusion to. This is the one production
                # caller, so passing it here is what makes that check fire on
                # the real path rather than only when a test opts in.
                ok, why, redirect_stage = can_signoff(self.state, self.cfg, self.blackboard)
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
                    self._end_loop_telemetry(
                        "LOOP_BLOCKED", stage=stage, loop_state=_ls.BLOCKED.value,
                        reason="SIGNOFF_GATE_REFUSED", blocking_reason=str(why)[:600],
                        resume_condition=("close what policy.can_signoff() named, then "
                                          "dv-harness start --loop"))
                    return

            self._emit_loop_action_selected(stage)
            result = self.run_stage(user_goal)
            ss = self.state.stages[stage]
            status = ss["status"]
            # Section 87: the verifier is separate from the producer, and which
            # gates judged this stage is recorded rather than assumed. Emitted
            # for EVERY outcome, PASS included -- telemetry that only appeared
            # on failures could not answer "did this iteration achieve anything".
            self._emit_loop_verify_completed(stage)
            self._emit_loop_progress(stage)

            if status in (Status.BLOCKED.value, Status.WAIT_USER.value):
                if status == Status.WAIT_USER.value:
                    self._emit_loop_event(
                        "LOOP_HUMAN_GATE_REQUIRED", stage=stage,
                        loop_state=_ls.HUMAN_GATE.value, reason="STAGE_NEEDS_USER_INPUT",
                        blocking_reason=(ss.get("blocking_reason") or "")[:600],
                        resume_condition=("answer the real blocking question "
                                          "(dv-harness question-queue answer <Q-ID> ...), "
                                          "then dv-harness start --loop"))
                    self._end_loop_telemetry(
                        "LOOP_STOPPED", stage=stage, loop_state=_ls.HUMAN_GATE.value,
                        reason="HUMAN_GATE_REQUIRED",
                        blocking_reason=(ss.get("blocking_reason") or "")[:600],
                        resume_condition=("answer the blocking question, then "
                                          "dv-harness start --loop"))
                else:
                    self._end_loop_telemetry(
                        "LOOP_BLOCKED", stage=stage, loop_state=_ls.BLOCKED.value,
                        reason="STAGE_BLOCKED",
                        blocking_reason=(ss.get("blocking_reason") or "")[:600],
                        resume_condition=("clear the blocking_reason on this stage, then "
                                          "dv-harness start --loop"))
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
                # LOOP-3, section 93: classify WHY this attempt failed before
                # deciding whether repeating it can help. Always computed and
                # recorded (on ss["failure_type"]/["failure_signature"]/
                # ["failure_signature_repeats"], and in the LOOP_BUDGET_SPENT /
                # LOOP_RETRY_REFUSED events); it only CHANGES the decision when
                # this project opted in -- see _retry_refused_by_failure_evidence().
                classification = self._classify_stage_failure(stage)
                retry_refusal = self._retry_refused_by_failure_evidence(stage, classification)
                if retry_refusal is None and ss["attempts"] <= max_retry:
                    ss["status"] = Status.RETRY.value
                    self.store.save(self.state)
                    self._emit_loop_retry_scheduled(stage, max_retry, classification)
                    continue
                if retry_refusal is not None:
                    # The refusal is recorded on the stage itself, not only in
                    # the event log: a human reading `dv-harness status` must
                    # see that the run stopped retrying on EVIDENCE, not on a
                    # spent attempt count it can compare against max_retry.
                    ss["blocking_reason"] = (
                        f"{ss.get('blocking_reason', '')}\n"
                        f"RETRY_REFUSED: {retry_refusal.get('reason', '')}")[:2000]
                    self.store.save(self.state)
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

                # Loop-state observation (2026-09-05, LoopContract/LoopState
                # gap close): the one point in this engine where a real budget
                # (policy.max_stage_retries) has just been spent, and therefore
                # the one point Status cannot describe -- BUDGET_EXHAUSTED has
                # no Status equivalent. Best-effort; see the method's docstring.
                #
                # LOOP-4 wires LOOP-2's classifier in HERE, at the one
                # low-frequency point where "is this a plateau, an oscillation,
                # or just a hard stage" is genuinely being asked -- so the
                # observation's `plateau` field carries a real verdict instead
                # of PLATEAU_NOT_EVALUATED forever, and section 108's
                # LOOP_PLATEAU_DETECTED / LOOP_OSCILLATION_DETECTED get a real
                # producer. A project with no evidence database still reports
                # PLATEAU_NOT_EVALUATED and emits neither event.
                convergence = self._classify_loop_convergence_for_telemetry(stage)
                self._record_loop_state_observation(stage, occasion="RETRY_BUDGET_EXHAUSTED",
                                                    convergence=convergence)
                self._emit_loop_convergence_events(stage, convergence)

                # plan_quality_feedback gap-close (2026-09-07): a sibling
                # classifier at the SAME retry-exhaustion point, asking a
                # different real question -- has THIS SAME graph-traversal
                # shape thrashed across other real sessions -- best-effort
                # and never allowed to affect the routing decision above.
                self._classify_plan_quality_shape_for_telemetry(stage)

                # LOOP-3, section 91: the same spend, recorded against the ONE
                # unified ledger, so "what has this run spent on which
                # dimension against which limit" is answerable run-wide instead
                # of only per node. Trips the circuit breaker when a DECLARED
                # budget has genuinely run out. Best-effort; see the method.
                spend = self._spend_retry_exhaustion_budget(stage, classification)

                # LOOP-4, section 108: the budget that just ran out, named.
                # `_spend_retry_exhaustion_budget()`'s own LOOP_BUDGET_SPENT
                # event is the LEDGER record (which unified dimensions moved);
                # this is the section-108 LOOP event the Loop Engineering Center
                # reads, and it carries the ledger payload rather than
                # recomputing any of it.
                self._emit_loop_event(
                    "LOOP_BUDGET_EXHAUSTED", stage=stage,
                    loop_state=_ls.BUDGET_EXHAUSTED.value,
                    attempts=ss.get("attempts"), max_stage_retries=max_retry,
                    attempts_remaining=0,
                    failure_type=(classification or {}).get("failure_type"),
                    failure_signature_repeats=(classification or {}).get("repeats"),
                    dimensions=(spend or {}).get("dimensions"),
                    exhausted=(spend or {}).get("exhausted"),
                    reason=(f"stage {stage} spent policy.max_stage_retries "
                            f"({ss.get('attempts')} attempts, limit {max_retry}); routing "
                            f"onto the graph's FAIL edge"),
                    resume_condition=("fix what the stage's blocking_reason names, or raise "
                                      "policy.max_stage_retries, then dv-harness start --loop"))

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
                # No FAIL edge and no reroute hint: the loop has nowhere to go
                # and stops here. That is section 86's FAILED, and it is this
                # session's one terminal event.
                self._end_loop_telemetry(
                    "LOOP_FAILED", stage=stage, loop_state=_ls.FAILED.value,
                    reason="RETRIES_EXHAUSTED_AND_NO_FAIL_EDGE",
                    blocking_reason=(ss.get("blocking_reason") or "")[:600],
                    attempts=ss.get("attempts"), max_stage_retries=max_retry,
                    resume_condition=("give this stage a real FAIL edge in main_graph.json, "
                                      "or fix what its blocking_reason names, then "
                                      "dv-harness start --loop"))
                return

            n = self.advance(user_goal)
            if not n:
                self.state.overall_status = Status.CLOSED.value
                self.store.save(self.state)
                # The loop's own machine-checkable done: it ran out of graph
                # and closed. This is the ONLY place LOOP_SUCCESS is emitted --
                # a per-stage PASS is CONVERGING, never SUCCESS (see
                # loop_contract.STATUS_TO_LOOP_STATE's own reasoning).
                self._end_loop_telemetry(
                    "LOOP_SUCCESS", stage=stage, loop_state=_ls.SUCCESS.value,
                    reason="OVERALL_STATUS_CLOSED",
                    machine_checkable_done="state.overall_status == CLOSED")
                return
