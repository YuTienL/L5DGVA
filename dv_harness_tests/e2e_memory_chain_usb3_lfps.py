"""The Phase 23 synthetic USB3 Polling.LFPS end-to-end memory chain, as ONE
reusable driver both the narrated demo and the regression suite call.

Execution Mode declaration (CLAUDE.md's Execution Mode Gate):
    LOCAL_ANALYSIS -- 「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」

This drives the REAL `dv_harness.memory_vault` / `memory_router` / `inference`
/ `session_snapshot` code end to end against a real (isolated) project
directory with real git integration -- it is NOT a unit test with mocked
internals. What is synthetic is only the INPUT DATA: a fabricated "USB3
Polling.LFPS timeout" failure whose symptom/waveform/RTL evidence is
realistic USB3 LTSSM prose rather than the output of an actual VCS run.
Per the Execution Mode Gate this is LOCAL_ANALYSIS, not REMOTE_EXECUTION:
no LSF job was submitted and no simulator ran, so `STEP_7_REAL_EXECUTION_
STATUS` records that step's real-execution half as PARTIAL_NOT_PERFORMED
instead of silently presenting synthetic verification values as a real
regression result.

Chain driven (all real function calls):
    failure -> search memory -> hypothesis -> evidence -> confidence -> gap /
    next-best-action -> root cause -> verified fix -> Job Memory -> failed-
    attempt Job Memory -> Engineering Memory -> promotion evaluation ->
    wiki links -> git traceability -> session save/restore

`run_memory_chain()` makes no assertions of its own: it returns every fact
each step really produced, and the callers decide what to do with them.
`dv_harness_tests/test_e2e_memory_chain_usb3_lfps.py` asserts on them as a
permanent regression net (CLAUDE.md's Methodology Consolidation Rule -- a
process proven once in a session becomes an automatically-run Harness asset,
not a one-off script); `.work/e2e_usb3_lfps_demo.py` narrates them for a
human reading the chain.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dv_harness import memory_router, memory_vault as mv, session_snapshot as snap
from dv_harness.inference import score_confidence, identify_gap, next_best_action
from dv_harness.memory import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]

EXECUTION_MODE = "LOCAL_ANALYSIS"
STEP_7_REAL_EXECUTION_STATUS = "PARTIAL_NOT_PERFORMED"
SESSION_NAME = "e2e-usb3-lfps-demo"

FAILURE_SYMPTOM = "USB3 Polling.LFPS timeout"
SIM_LOG_EXCERPT = (
    "UVM_ERROR @ 184203 ns: usb3_scoreboard.sv(212) "
    "[POLLING_LFPS_TIMEOUT] Polling.LFPS substate did not observe "
    "4 consecutive LFPS burst/gap cycles within tPollingLFPSTimeout "
    "(360us) -- link stuck in Polling.LFPS, never reached Polling.RxEQ"
)
PATTERN = "usb3_polling_lfps_timeout_test"
TERMINAL_SIGNATURE = "POLLING_LFPS_TIMEOUT"

HYPOTHESIS = (
    "lfps_detect (PHY analog LFPS receiver output) crosses from the PHY "
    "reference clock domain into the LTSSM core-clock domain with no "
    "synchronizer, so a burst/gap edge landing near a core-clock edge "
    "is intermittently dropped or double-counted by the Polling.LFPS "
    "burst-counter FSM, which then never reaches its required count of "
    "4 within the 360us timeout window."
)

# Path/offset references only, per the Waveform Dump User Gate and the
# Simulation Observability Default -- never raw log or FSDB content.
EVIDENCE: List[str] = [
    "waveform (synthetic reference): usb3_phy_tb.dut.phy_lfps_rx.lfps_detect "
    "toggles at t=184198.7ns, 3.3ns before the next core_clk posedge (setup "
    "violation window) -- FSDB path/offset cited, not embedded",
    "RTL (synthetic reference): usb3_ltssm_polling_fsm.v, lfps_burst_counter "
    "process block reads lfps_detect directly with no 2-flop synchronizer "
    "in the core_clk domain (grep-cited path/line, not embedded)",
    "sim.log: repeats across all 3 seeds of the targeted reproducer, "
    "0/3 PASS pre-fix",
]

ROOT_CAUSE = (
    "lfps_detect PHY->core clock-domain crossing has no synchronizer, "
    "causing intermittent burst/gap edge loss in the Polling.LFPS "
    "counter FSM"
)
FIX = "add a 2-flop synchronizer on lfps_detect at the PHY->core_clk domain crossing"

# The same verification vocabulary engine.py's real fix_effectiveness_gate /
# fix_regression_non_regression_gate produce. Synthetic VALUES, real SHAPE --
# see STEP_7_REAL_EXECUTION_STATUS above for why they are not a real verdict.
VERIFICATION: Dict[str, Any] = {
    "targeted_reproducer_passed": True, "broader_regression_passed": True,
    "new_failures_introduced": False, "target_pre_fix_result": "FAIL",
    "target_post_fix_result": "PASS", "replay_equivalent": True,
}

CONFIDENCE_INPUTS_PRE_FIX: Dict[str, Any] = dict(
    independent_sources_count=2,      # waveform + RTL source inspection
    evidence_refs_verified=True,      # both refs point at real, cited locations
    counter_evidence_count=0,
    multi_agent_consensus_count=1,    # single debug-agent pass so far, pre-fix
)
CONFIDENCE_INPUTS_POST_FIX: Dict[str, Any] = dict(
    independent_sources_count=3,      # + the (synthetic) post-fix reproducer result
    evidence_refs_verified=True,
    counter_evidence_count=0,
    multi_agent_consensus_count=2,    # debug-agent + review-agent independent sign-off
)

REQUIRED_EVIDENCE_CATEGORIES = ["waveform_evidence", "rtl_evidence",
                                "targeted_reproducer_result",
                                "USB3 LTSSM/LFPS/TS patterns"]
SUPPLIED_EVIDENCE_CATEGORIES = ["waveform_evidence", "rtl_evidence",
                                "targeted_reproducer_result"]


def default_cfg(vault_path: str = "") -> Dict[str, Any]:
    """Real hybrid provider with real git commits; no network share.

    `knowledge_center.enabled` is False because a local synthetic example must
    never push fabricated knowledge to the shared, cross-user tier.
    """
    return {
        "memory": {"provider": "hybrid", "vault_path": vault_path,
                   "obsidian_cli": "auto", "git_enabled": True},
        "knowledge_center": {"enabled": False},
    }


def run_memory_chain(project_root: Path, cfg: Optional[Dict[str, Any]] = None,
                     echo: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Drive the whole chain against `project_root` and return what it produced.

    Raises nothing on a healthy run and asserts nothing: every fact each step
    really produced is returned, so a caller can assert on it (the regression
    test) or print it (the demo) without this driver deciding which failures
    matter.
    """
    cfg = cfg if cfg is not None else default_cfg()
    say = echo if echo is not None else (lambda _msg: None)
    (project_root / ".dv-harness").mkdir(parents=True, exist_ok=True)

    out: Dict[str, Any] = {"execution_mode": EXECUTION_MODE, "chain": []}

    def step(title: str) -> None:
        say(f"\n{'=' * 78}\n{title}\n{'=' * 78}")

    # -- STEP 1: FAILURE (synthetic, realistic USB3 LTSSM sim.log excerpt) ---
    step("STEP 1 -- FAILURE (synthetic)")
    say(f"Symptom          : {FAILURE_SYMPTOM}")
    say(f"sim.log excerpt  : {SIM_LOG_EXCERPT}")
    say("Note             : SYNTHETIC data -- no real VCS/LSF job was run for this demo.")
    out["failure_symptom"] = FAILURE_SYMPTOM
    out["sim_log_excerpt"] = SIM_LOG_EXCERPT
    out["chain"].append({"step": "failure", "symptom": FAILURE_SYMPTOM, "synthetic": True})

    # -- STEP 2: SEARCH MEMORY (real call against a real, still-empty vault) -
    step("STEP 2 -- SEARCH MEMORY (real dv_harness.memory_vault call)")
    failure_signature = mv.build_failure_signature(
        protocol="USB", pattern=PATTERN, symptom=FAILURE_SYMPTOM,
        uvm_error_count=1, uvm_fatal_count=0,
        terminal_signature=TERMINAL_SIGNATURE, lsf_status="DONE",
        extra_text=SIM_LOG_EXCERPT,
    )
    search_result = mv.search_related_memory_for_debug(project_root, cfg, failure_signature)
    say(f"failure_signature: {failure_signature}")
    say(f"search result    : ok={search_result['ok']} "
        f"related_cases_found={search_result['count']}")
    say("-> Honest result: 0 related cases (fresh vault, no prior knowledge of this failure yet).")
    out["failure_signature"] = failure_signature
    out["search_result"] = search_result
    out["chain"].append({"step": "search_memory", "result": search_result})

    # -- STEP 3: HYPOTHESIS ------------------------------------------------
    step("STEP 3 -- HYPOTHESIS")
    say(HYPOTHESIS)
    out["hypothesis"] = HYPOTHESIS
    out["chain"].append({"step": "hypothesis", "text": HYPOTHESIS})

    # -- STEP 4: EVIDENCE --------------------------------------------------
    step("STEP 4 -- EVIDENCE")
    for item in EVIDENCE:
        say(f"  - {item}")
    out["evidence"] = list(EVIDENCE)
    out["chain"].append({"step": "evidence", "items": list(EVIDENCE)})

    # -- STEP 5: CONFIDENCE / GAP / NEXT-BEST-ACTION (real inference calls) --
    step("STEP 5 -- CONFIDENCE (real inference.score_confidence())")
    confidence_pre_fix = score_confidence(**CONFIDENCE_INPUTS_PRE_FIX)
    say(f"confidence_inputs: {CONFIDENCE_INPUTS_PRE_FIX}")
    say(f"confidence_result: {confidence_pre_fix}")
    out["confidence_inputs_pre_fix"] = dict(CONFIDENCE_INPUTS_PRE_FIX)
    out["confidence_pre_fix"] = confidence_pre_fix
    out["chain"].append({"step": "confidence_pre_fix", "inputs": dict(CONFIDENCE_INPUTS_PRE_FIX),
                         "result": confidence_pre_fix})

    gaps = identify_gap(required_evidence_categories=list(REQUIRED_EVIDENCE_CATEGORIES),
                        supplied_evidence_categories=list(SUPPLIED_EVIDENCE_CATEGORIES))
    nba = next_best_action("USB", gaps, REPO_ROOT)  # real per-protocol registry lookup (read-only)
    say(f"gap identified   : {gaps}")
    say(f"next_best_action : {nba}")
    out["gaps"] = gaps
    out["next_best_action"] = nba
    out["chain"].append({"step": "gap_and_next_best_action", "gaps": gaps,
                         "next_best_action": nba})

    # -- STEP 6: ROOT CAUSE ------------------------------------------------
    step("STEP 6 -- ROOT CAUSE")
    say(ROOT_CAUSE)
    out["root_cause"] = ROOT_CAUSE
    out["chain"].append({"step": "root_cause", "text": ROOT_CAUSE})

    # -- STEP 7: VERIFIED FIX  [real-execution half PARTIAL, see module doc] -
    step("STEP 7 -- VERIFIED FIX  [PARTIAL -- would require REMOTE_EXECUTION for a real run]")
    say(f"fix              : {FIX}")
    say(f"verification     : {VERIFICATION}  (synthetic values matching the real RE_AUDIT gate shape)")
    say("REAL-EXECUTION GAP (honestly marked PARTIAL): a genuine PASS/FAIL verdict here "
        "would require submitting a real LSF job and running VCS on the actual DUT/TB "
        "on the Linux server -- not performed in this local synthetic run.")
    out["fix"] = FIX
    out["verification"] = dict(VERIFICATION)
    out["real_execution_status"] = STEP_7_REAL_EXECUTION_STATUS
    out["chain"].append({"step": "verified_fix", "fix": FIX, "verification": dict(VERIFICATION),
                         "real_execution_status": STEP_7_REAL_EXECUTION_STATUS})

    confidence_post_fix = score_confidence(**CONFIDENCE_INPUTS_POST_FIX)
    say(f"post-fix confidence_result: {confidence_post_fix}")
    out["confidence_inputs_post_fix"] = dict(CONFIDENCE_INPUTS_POST_FIX)
    out["confidence_post_fix"] = confidence_post_fix

    # -- STEP 8: JOB MEMORY (real route_and_store, kind="job_result") -------
    step("STEP 8 -- JOB MEMORY (real memory_router.route_and_store())")
    job_result = memory_router.route_and_store(project_root, {
        "kind": "job_result", "protocol": "USB", "job_id": "DEMO-USB3-LFPS-001",
        "pattern": PATTERN, "lsf_status": "DONE", "sim_status": "PASS",
        "uvm_error_count": 0, "uvm_fatal_count": 0,
        "failure_signature": failure_signature, "git_sha": "0000000synthetic",
    }, cfg=cfg)
    say(str(job_result))
    out["job_result"] = job_result
    out["job_memory_id"] = job_result.get("memory_id")
    out["job_vault_note_id"] = (job_result.get("vault_write") or {}).get("note_id")
    out["chain"].append({"step": "job_memory", "result": job_result})

    # -- STEP 9: the FAILED-attempt path, real and distinct: a debug attempt
    # that does NOT yet pass writes to Job Memory ONLY, never promotes (see
    # engine.py's step 3c FAIL/PARTIAL hook).
    step("STEP 9 -- JOB MEMORY on a FAILED attempt (real, no promotion possible by construction)")
    failed_result = memory_router.route_and_store(project_root, {
        "kind": "job_failure", "protocol": "USB", "job_id": "DEMO-USB3-LFPS-000-preattempt",
        "pattern": PATTERN, "lsf_status": "DONE", "sim_status": "FAIL",
        "uvm_error_count": 1, "uvm_fatal_count": 0, "failure_signature": failure_signature,
        "blocking_reason": TERMINAL_SIGNATURE,
    }, cfg=cfg)
    say(str(failed_result))
    out["failed_attempt_result"] = failed_result
    out["chain"].append({"step": "job_memory_failed_attempt", "result": failed_result})

    # -- STEP 10: ENGINEERING MEMORY ---------------------------------------
    # `source_finding_id` links back to the Job Memory record, which is what
    # produces the real [[WikiLink]]. `confidence` carries STEP 7's real
    # score_confidence() level onto the record: CLAUDE.md's Engineering Memory
    # Policy requires root cause, evidence, fix, verification AND confidence to
    # land as ONE record, and leaving it off lets MemoryStore.add()'s "UNKNOWN"
    # setdefault stand, surfacing as `confidence: UNKNOWN` in the vault note
    # while the chain had just measured HIGH.
    step("STEP 10 -- ENGINEERING MEMORY (real write, auto-linked to Job Memory via [[WikiLink]])")
    eng_result = memory_router.route_and_store(project_root, {
        "kind": "root_cause", "verified": True, "protocol": "USB", "scope": "LTSSM.Polling.LFPS",
        "title": "USB3 Polling.LFPS timeout -- lfps_detect CDC missing synchronizer",
        "root_cause": ROOT_CAUSE, "fix": FIX,
        "symptoms": [FAILURE_SYMPTOM, SIM_LOG_EXCERPT],
        "evidence": list(EVIDENCE), "verification": dict(VERIFICATION),
        "confidence": confidence_post_fix["level"],
        "source_finding_id": out["job_memory_id"],
    }, cfg=cfg)
    say(str(eng_result))
    out["engineering_result"] = eng_result
    out["engineering_memory_id"] = eng_result.get("memory_id")
    out["engineering_vault_note_id"] = (eng_result.get("vault_write") or {}).get("note_id")
    out["chain"].append({"step": "engineering_memory", "result": eng_result})

    # -- STEP 11: PROMOTION EVALUATION (real promote_to_organizational) -----
    step("STEP 11 -- PROMOTION EVALUATION (real memory_router.promote_to_organizational())")
    promotion = memory_router.promote_to_organizational(
        project_root, out["engineering_memory_id"], CONFIDENCE_INPUTS_POST_FIX, cfg=cfg)
    say(str(promotion))
    say("-> Correct, honest real-gate outcome for a single verified fix "
        "(confirmation_count=0 does not clear ORGANIZATIONAL_MIN_CONFIRMATIONS=2): the record "
        "correctly remains at Engineering tier. This IS the real 3-gate promotion boundary "
        "firing, not a bug.")
    out["promotion"] = promotion
    out["chain"].append({"step": "promotion_evaluation", "result": promotion})

    # -- STEP 12: WIKI LINKS (real forward-link + backlink traversal) -------
    step("STEP 12 -- WIKI LINKS (real provider.list_links())")
    provider = mv.get_active_provider(project_root, cfg)
    eng_note = provider.read(out["engineering_vault_note_id"])
    wiki_lines = [ln for ln in eng_note["body"].splitlines() if "[[" in ln]
    note_confidence = (eng_note.get("frontmatter") or {}).get("confidence")
    links = provider.list_links(out["engineering_vault_note_id"])
    back = provider.list_links(out["job_vault_note_id"])
    say(f"Engineering note body 'Related Knowledge' section contains: {wiki_lines}")
    say(f"Engineering note frontmatter confidence: {note_confidence}")
    say(f"forward_links (Engineering note -> Job note): {links['forward_links']}")
    say(f"backlinks (Job note <- Engineering note)    : {back['backlinks']}")
    out["engineering_note_wiki_lines"] = wiki_lines
    out["engineering_note_confidence"] = note_confidence
    out["forward_links"] = links["forward_links"]
    out["backlinks"] = back["backlinks"]
    out["chain"].append({"step": "wiki_links", "forward_links": links["forward_links"],
                         "backlinks": back["backlinks"]})

    # -- STEP 13: GIT TRACEABILITY -----------------------------------------
    step("STEP 13 -- GIT TRACEABILITY (real git log in the demo vault)")
    vault_path = mv.resolve_vault_path(project_root, cfg)
    log_out = subprocess.run(["git", "log", "--oneline"], cwd=str(vault_path),
                             capture_output=True, text=True)
    knowledge_commit_sha = (MemoryStore(project_root).get(out["engineering_memory_id"]) or {}
                            ).get("knowledge_commit_sha")
    say(log_out.stdout)
    say(f"Engineering Memory JSON record's knowledge_commit_sha: {knowledge_commit_sha}")
    out["vault_path"] = str(vault_path)
    out["vault_git_log"] = log_out.stdout
    out["knowledge_commit_sha"] = knowledge_commit_sha
    out["chain"].append({"step": "git_traceability", "git_log": log_out.stdout,
                         "knowledge_commit_sha": knowledge_commit_sha})

    # -- STEP 14: session save/restore over this run's state (Phase 14) -----
    step("STEP 14 -- SESSION SAVE/RESTORE over this run's state")
    react_dir = project_root / ".dv-harness" / "react" / "RE_AUDIT"
    react_dir.mkdir(parents=True, exist_ok=True)
    import json as _json
    (project_root / ".dv-harness" / "state.json").write_text(_json.dumps({
        "current_stage": "RE_AUDIT", "project": "USB3_Polling_LFPS_Demo",
        "overall_status": "PASS",
    }), encoding="utf-8")
    (react_dir / "iteration_001.json").write_text(_json.dumps({
        "reason_summary": HYPOTHESIS, "evidence": list(EVIDENCE),
        "confidence": confidence_post_fix["level"],
        "next_action": "promote_to_organizational() pending a second independent confirmation",
    }), encoding="utf-8")
    out["session_manifest"] = snap.save_session(project_root, name=SESSION_NAME,
                                                note="Phase 23 synthetic E2E")
    restored = snap.restore_session(project_root, SESSION_NAME, backup_current=False)
    say(f"resume_summary: {restored['resume_summary']}")
    out["resume_summary"] = restored["resume_summary"]
    out["chain"].append({"step": "session_save_restore",
                         "resume_summary": restored["resume_summary"]})

    return out
