"""Genuine content-driven inner ReAct loop (dv_harness/react_loop.py).

Real callers verified before writing these tests: engine.DVHarness.run_stage()
(the elif branch guarded by node.react + policy.enable_inner_react_loop),
engine.DVHarness.loop()'s retry-exhaustion routing (the additive
react_reroute_target hint line), gates.py's GATE_FAILURE_REROUTE table and
_evaluate_stage_evidence_core() factoring.

The crux test (test_two_runs_with_different_gate_failures_pick_different_actions)
is the one this module exists to prove: two runs against the SAME real stage
(ARCH_CALIBRATION) and the SAME FakeAdapter policy produce genuinely DIFFERENT
observations (a different real gate script fails, with different real detail)
and the loop demonstrably picks a DIFFERENT next action as a result -- REROUTE
vs. CONVERGE_TERMINATE -- not merely a different pass/fail outcome.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from dv_harness.gates import GATE_FAILURE_REROUTE
from dv_harness.react_loop import (
    GateSignature, MenuOption, ReactDecision, InnerReactLoop,
    build_menu, reflect_and_decide, evaluate_stage_evidence_with_detail,
    _signatures_equal, attempt_hypothesis_refutation,
    compute_adaptive_react_budget, _distinct_subsystems,
)
from dv_harness.graph import GraphDefinition, Node, Edge
from dv_harness.adapters.base import AgentResult
from dv_harness.stage_profile import StageExecutionProfiler

ROOT = Path(__file__).resolve().parents[1]


def _mk_smoke_project():
    """Same fixture shape as test_engine_gates_and_routing.py's
    _mk_smoke_project -- a fresh temp project with the real main_graph.json,
    real .claude/agents, and real tools/verification_flow gate scripts, so
    ARCH_CALIBRATION's real gates actually subprocess-run."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


def _load_real_graph():
    return GraphDefinition.load(ROOT / ".dv-harness" / "graph" / "main_graph.json")


# --- Fixtures: ARCH_CALIBRATION's 3 mandatory gates (architecture_calibration_
# gate, architecture_calibration_conflict_gate, vip_api_drift_gate) -- see
# gates.STAGE_GATES["ARCH_CALIBRATION"] and each script's own PASS/FAIL
# branches (read directly from tools/verification_flow/ before writing these).

_ARCH_CALIBRATION_GATE = (
    '```dv-harness-evidence:architecture_calibration_gate\n'
    '{"architecture_before": {"a": 1}, "architecture_after": {"a": 1}}\n```\n'
)
_CONFLICT_GATE_PASS = (
    '```dv-harness-evidence:architecture_calibration_conflict_gate\n'
    '{"conflicts": []}\n```\n'
)
_CONFLICT_GATE_FAIL = (
    '```dv-harness-evidence:architecture_calibration_conflict_gate\n'
    '{"conflicts": [{"feature": "reset_domain", "resolved": false, '
    '"sources": ["spec.md", "rtl_top.v"]}]}\n```\n'
)
# architecture_calibration_gate itself failing (a real delta present, but no
# impact-analysis evidence) -- the ONE of ARCH_CALIBRATION's 3 gates that is
# NOT in gates.GATE_FAILURE_REROUTE (unlike vip_api_drift_gate and
# architecture_calibration_conflict_gate, both mapped to ARCH_DISCOVERY) and
# whose FAIL detail carries neither a "missing" list nor a "protocol" field --
# used as the "nothing actionable, must CONVERGE" contrast case below.
_CALIBRATION_GATE_FAIL_NO_IMPACT_ANALYSIS = (
    '```dv-harness-evidence:architecture_calibration_gate\n'
    '{"architecture_before": {"a": 1}, "architecture_after": {"a": 2}}\n```\n'
)
_VIP_DRIFT_GATE_PASS = (
    '```dv-harness-evidence:vip_api_drift_gate\n'
    '{"current_vip_version": "1.0", "qualified_vip_version": "1.0", '
    '"current_vip_source_or_manual_hash": "h1"}\n```\n'
)
_VIP_DRIFT_GATE_FAIL = (
    '```dv-harness-evidence:vip_api_drift_gate\n'
    '{"current_vip_version": "2.0", "qualified_vip_version": "1.0", '
    '"api_diff_analyzed": false}\n```\n'
)

_ARCH_CALIBRATION_ALL_PASS = _ARCH_CALIBRATION_GATE + _CONFLICT_GATE_PASS + _VIP_DRIFT_GATE_PASS
_ARCH_CALIBRATION_VIP_DRIFT_FAILS = _ARCH_CALIBRATION_GATE + _CONFLICT_GATE_PASS + _VIP_DRIFT_GATE_FAIL
_ARCH_CALIBRATION_CONFLICT_FAILS = _ARCH_CALIBRATION_GATE + _CONFLICT_GATE_FAIL + _VIP_DRIFT_GATE_PASS
_ARCH_CALIBRATION_GATE_FAILS_NO_REROUTE = (
    _CALIBRATION_GATE_FAIL_NO_IMPACT_ANALYSIS + _CONFLICT_GATE_PASS + _VIP_DRIFT_GATE_PASS
)


def test_evaluate_stage_evidence_with_detail_matches_plain_verdict_and_reasons():
    """Byte-identical verdict/reasons vs. gates.evaluate_stage_evidence() --
    both now share _evaluate_stage_evidence_core(), so this proves the
    refactor didn't change existing behavior."""
    from dv_harness.gates import evaluate_stage_evidence
    tmp = _mk_smoke_project()
    try:
        plain_verdict, plain_reasons = evaluate_stage_evidence(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_VIP_DRIFT_FAILS)
        detail_verdict, detail_reasons, signatures = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_VIP_DRIFT_FAILS)
        assert detail_verdict == plain_verdict == "GATE_FAIL"
        assert detail_reasons == plain_reasons
        assert any(s.gate_id == "vip_api_drift_gate" and not s.ok for s in signatures)
        assert any(s.gate_id == "architecture_calibration_gate" and s.ok for s in signatures)
        assert len(signatures) == 3  # one GateSignature per gate configured for this stage
    finally:
        shutil.rmtree(tmp)


def test_evaluate_stage_evidence_with_detail_pass_case():
    tmp = _mk_smoke_project()
    try:
        verdict, reasons, signatures = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_ALL_PASS)
        assert verdict == "PASS"
        assert all(s.ok for s in signatures)
    finally:
        shutil.rmtree(tmp)


def test_missing_evidence_block_yields_synthetic_signature_not_a_gap():
    """A gate the agent supplied no evidence block for still gets a real
    GateSignature entry (NO_EVIDENCE_BLOCK_SUPPLIED) -- build_menu() always
    has one signature per configured gate, never a silent hole."""
    tmp = _mk_smoke_project()
    try:
        verdict, reasons, signatures = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _CONFLICT_GATE_PASS + _VIP_DRIFT_GATE_PASS)
        assert verdict == "GATE_FAIL"
        by_id = {s.gate_id: s for s in signatures}
        assert by_id["architecture_calibration_gate"].ok is False
        assert by_id["architecture_calibration_gate"].detail["reason"] == "NO_EVIDENCE_BLOCK_SUPPLIED"
    finally:
        shutil.rmtree(tmp)


# --- build_menu(): real content -> real, differentiated options -------------

def test_build_menu_offers_reroute_from_gate_failure_table_when_target_is_real():
    graph = _load_real_graph()
    assert "ARCH_DISCOVERY" in graph.nodes  # sanity: the real target node exists
    sig = GateSignature(gate_id="vip_api_drift_gate", ok=False,
                         detail={"status": "FAIL", "reason": "VIP_VERSION_DRIFT_WITHOUT_API_DIFF"})
    menu = build_menu(ROOT, "ARCH_CALIBRATION", node=None, signatures=[sig], graph=graph)
    reroute_ids = [m.option_id for m in menu if m.kind == "REROUTE"]
    assert reroute_ids == ["REROUTE:ARCH_DISCOVERY"]
    assert GATE_FAILURE_REROUTE["vip_api_drift_gate"] == "ARCH_DISCOVERY"
    # CONVERGE_TERMINATE is always present alongside a real action.
    assert any(m.option_id == "CONVERGE_TERMINATE" for m in menu)


def test_build_menu_drops_reroute_target_not_present_in_graph():
    """A gate_id mapped in GATE_FAILURE_REROUTE to a node that does NOT exist
    in the real graph must never be offered -- same discipline as a
    hallucinated stage name."""
    fake_graph = GraphDefinition(
        nodes=[Node(id="ARCH_CALIBRATION", route="r", agent="a")],  # ARCH_DISCOVERY absent
        edges=[],
    )
    sig = GateSignature(gate_id="vip_api_drift_gate", ok=False, detail={"reason": "X"})
    menu = build_menu(ROOT, "ARCH_CALIBRATION", node=None, signatures=[sig], graph=fake_graph)
    assert not any(m.kind == "REROUTE" for m in menu)
    assert [m.option_id for m in menu] == ["CONVERGE_TERMINATE"]


def test_build_menu_offers_retry_targeted_naming_exact_missing_field():
    sig = GateSignature(gate_id="mechanism_readiness_gate", ok=False,
                         detail={"status": "FAIL", "reason": "MISSING_FIELDS",
                                 "missing": ["architecture_nodes", "planned_testcases"]})
    menu = build_menu(ROOT, "VERIFICATION_ARCHITECTURE", node=None, signatures=[sig], graph=None)
    retry_opts = [m for m in menu if m.kind == "RETRY_TARGETED"]
    assert len(retry_opts) == 1
    assert retry_opts[0].target == "mechanism_readiness_gate"
    assert "architecture_nodes" in retry_opts[0].rationale
    # No REROUTE possible with graph=None.
    assert not any(m.kind == "REROUTE" for m in menu)


def test_build_menu_offers_request_evidence_citing_real_registry_item():
    """Source #4: a gate whose detail names a real 'protocol' plus a concrete
    'missing' list gets a REQUEST_EVIDENCE option citing an actual
    protocol_builder_registry.json item (USB's real 'discover' list)."""
    sig = GateSignature(gate_id="protocol_structural_completeness_gate", ok=False,
                         detail={"status": "FAIL", "protocol": "usb", "missing": ["port topology"]})
    menu = build_menu(ROOT, "VERIFICATION_ARCHITECTURE", node=None, signatures=[sig], graph=None)
    req_opts = [m for m in menu if m.kind == "REQUEST_EVIDENCE"]
    assert len(req_opts) == 1
    assert "port topology" in req_opts[0].rationale
    assert "usb" in req_opts[0].rationale


def test_build_menu_no_new_information_suppresses_retry_but_offers_reroute_and_no_new_info():
    graph = _load_real_graph()
    sig = GateSignature(gate_id="vip_api_drift_gate", ok=False,
                         detail={"status": "FAIL", "reason": "X", "missing": ["some_field"]})
    prior = [GateSignature(gate_id="vip_api_drift_gate", ok=False,
                            detail={"status": "FAIL", "reason": "X", "missing": ["some_field"]})]
    menu = build_menu(ROOT, "ARCH_CALIBRATION", node=None, signatures=[sig],
                       prior_signatures=prior, graph=graph)
    kinds = {m.kind for m in menu}
    assert "RETRY_TARGETED" not in kinds  # a repeat of a demonstrably no-op retry is suppressed
    assert "REROUTE" in kinds            # a genuinely different action stays available
    assert "CONVERGE_NO_NEW_INFORMATION" in kinds


def test_build_menu_empty_failure_set_is_converge_only():
    menu = build_menu(ROOT, "ARCH_CALIBRATION", node=None, signatures=[], graph=None)
    assert [m.option_id for m in menu] == ["CONVERGE_TERMINATE"]


def test_signatures_equal_helper():
    a = [GateSignature("g1", False, {"x": 1})]
    b = [GateSignature("g1", False, {"x": 1})]
    c = [GateSignature("g1", False, {"x": 2})]
    assert _signatures_equal(a, b) is True
    assert _signatures_equal(a, c) is False
    assert _signatures_equal(a, None) is False


# --- reflect_and_decide(): guardrail against a hallucinated option_id -------

def test_reflect_and_decide_accepts_a_real_menu_choice():
    menu = [
        MenuOption("REROUTE:ARCH_DISCOVERY", "REROUTE", "ARCH_DISCOVERY", "r", "gate_failure_route"),
        MenuOption("CONVERGE_TERMINATE", "CONVERGE_TERMINATE", None, "r", "control"),
    ]

    class FakeAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            return AgentResult(ok=True, text=(
                '```dv-harness-react-decision\n'
                '{"chosen_option_id": "REROUTE:ARCH_DISCOVERY", '
                '"conclusion": "vip_api_drift_gate failed; reroute upstream.", "params": {}}\n```'
            ), raw={})

    decision = reflect_and_decide(FakeAdapter(), ROOT, "ARCH_CALIBRATION", {}, menu)
    assert decision.chosen_option_id == "REROUTE:ARCH_DISCOVERY"
    assert decision.converged is False


def test_reflect_and_decide_forces_convergence_on_hallucinated_option_after_one_reask():
    menu = [MenuOption("CONVERGE_TERMINATE", "CONVERGE_TERMINATE", None, "r", "control")]
    calls = []

    class HallucinatingAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            calls.append(prompt)
            return AgentResult(ok=True, text=(
                '```dv-harness-react-decision\n'
                '{"chosen_option_id": "REROUTE:SOME_STAGE_NEVER_OFFERED", '
                '"conclusion": "invented", "params": {}}\n```'
            ), raw={})

    decision = reflect_and_decide(HallucinatingAdapter(), ROOT, "ARCH_CALIBRATION", {}, menu)
    assert decision.chosen_option_id == "CONVERGE_TERMINATE"
    assert decision.converged is True
    assert len(calls) == 2  # asked once, re-asked once, then forced -- never actioned


def test_reflect_and_decide_handles_unparseable_reply():
    menu = [MenuOption("CONVERGE_TERMINATE", "CONVERGE_TERMINATE", None, "r", "control")]

    class GarbageAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            return AgentResult(ok=True, text="I have thought about it deeply.", raw={})

    decision = reflect_and_decide(GarbageAdapter(), ROOT, "ARCH_CALIBRATION", {}, menu)
    assert decision.chosen_option_id == "CONVERGE_TERMINATE"
    assert decision.converged is True


# --- THE CRUX TEST: two runs, two different real observations, two --------
# --- genuinely different chosen actions -------------------------------------

class _ContentDrivenFakeAdapter:
    """Models a real reflection call's essential property -- the decision is
    DERIVED FROM the real menu content handed to it, not scripted per test
    scenario. Parses the option_id list out of the prompt exactly as an LLM
    reading the same instructions would have to, and applies one fixed,
    scenario-agnostic preference order (REROUTE > RETRY_TARGETED >
    REQUEST_EVIDENCE > CONVERGE). Because this same fixed policy is reused
    unmodified across both runs below, any difference in its output is
    attributable ONLY to a real difference in the menu it was given -- which
    is itself produced from a real difference in gate script output."""

    def __init__(self):
        self.prompts_seen = []

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.prompts_seen.append(prompt)
        option_ids = re.findall(r"option_id=(\S+)", prompt)
        for prefix in ("REROUTE:", "RETRY_TARGETED:", "REQUEST_EVIDENCE:"):
            for oid in option_ids:
                if oid.startswith(prefix):
                    return AgentResult(ok=True, text=(
                        '```dv-harness-react-decision\n'
                        + json.dumps({
                            "chosen_option_id": oid,
                            "conclusion": f"Real menu offered {oid}; no better option present.",
                            "params": {},
                        }) + '\n```'
                    ), raw={})
        return AgentResult(ok=True, text=(
            '```dv-harness-react-decision\n'
            '{"chosen_option_id": "CONVERGE_TERMINATE", '
            '"conclusion": "No actionable option in the real menu.", "params": {}}\n```'
        ), raw={})


def test_two_runs_with_different_gate_failures_pick_different_actions():
    """Run A: vip_api_drift_gate fails (GATE_FAILURE_REROUTE-mapped) ->
    the SAME content-driven adapter policy picks REROUTE:ARCH_DISCOVERY.
    Run B: architecture_calibration_gate itself fails instead (a real
    architecture delta present, but no impact-analysis evidence) -- the ONE
    of ARCH_CALIBRATION's 3 gates that carries no GATE_FAILURE_REROUTE
    mapping, no matching graph edge, and no 'missing'/'protocol' structured
    field -> the SAME adapter policy has nothing actionable and picks
    CONVERGE_TERMINATE instead. Same stage, same fixed decision policy,
    genuinely different real gate output -> genuinely different real
    decision -- this is the crux of "real ReAct" this design exists to prove."""
    tmp = _mk_smoke_project()
    try:
        graph = _load_real_graph()
        node = graph.nodes["ARCH_CALIBRATION"]

        # --- Run A: vip_api_drift_gate fails -----------------------------
        verdict_a, reasons_a, sigs_a = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_VIP_DRIFT_FAILS)
        assert verdict_a == "GATE_FAIL"
        first_result_a = AgentResult(ok=True, text=_ARCH_CALIBRATION_VIP_DRIFT_FAILS, raw={},
                                      session_id="s-a")
        adapter_a = _ContentDrivenFakeAdapter()
        outcome_a = InnerReactLoop(tmp, adapter_a, react_recorder=None,
                                    cfg={"policy": {"inner_react_max_iterations": 3,
                                                     "inner_react_max_adapter_calls": 2}},
                                    graph=graph).run(
            "ARCH_CALIBRATION", node, 1, first_result_a, verdict_a, reasons_a, sigs_a,
            base_prompt="stage prompt A",
        )

        # --- Run B: architecture_calibration_gate fails (no reroute mapping) --
        verdict_b, reasons_b, sigs_b = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_GATE_FAILS_NO_REROUTE)
        assert verdict_b == "GATE_FAIL"
        first_result_b = AgentResult(ok=True, text=_ARCH_CALIBRATION_GATE_FAILS_NO_REROUTE, raw={},
                                      session_id="s-b")
        adapter_b = _ContentDrivenFakeAdapter()
        outcome_b = InnerReactLoop(tmp, adapter_b, react_recorder=None,
                                    cfg={"policy": {"inner_react_max_iterations": 3,
                                                     "inner_react_max_adapter_calls": 2}},
                                    graph=graph).run(
            "ARCH_CALIBRATION", node, 1, first_result_b, verdict_b, reasons_b, sigs_b,
            base_prompt="stage prompt B",
        )

        # The two real observations genuinely differed (different failing gate_id).
        failing_a = {s.gate_id for s in sigs_a if not s.ok}
        failing_b = {s.gate_id for s in sigs_b if not s.ok}
        assert failing_a == {"vip_api_drift_gate"}
        assert failing_b == {"architecture_calibration_gate"}
        assert failing_a != failing_b

        # The SAME adapter policy genuinely picked DIFFERENT actions.
        assert outcome_a.reroute_target == "ARCH_DISCOVERY"
        assert outcome_b.reroute_target is None

        # Zero extra adapter.run() calls for Run A's REROUTE (per the taxonomy:
        # REROUTE/CONVERGE cost zero adapter calls beyond the one reflection call).
        assert len(adapter_a.prompts_seen) == 1
        assert len(adapter_b.prompts_seen) == 1

        # Final verdict is unchanged by either action (neither re-ran the gate).
        assert outcome_a.verdict == "GATE_FAIL"
        assert outcome_b.verdict == "GATE_FAIL"
    finally:
        shutil.rmtree(tmp)


def test_retry_targeted_action_genuinely_re_invokes_adapter_with_targeted_prompt_and_can_converge_to_pass():
    """A gate failure with a structured 'missing' field (mechanism_readiness_
    gate's real MISSING_FIELDS shape) drives RETRY_TARGETED: the loop issues
    a real second adapter.run() call naming the exact gate_id, and when that
    second call supplies corrected evidence, the loop converges to PASS --
    demonstrating the retry is genuinely CONTENT-TARGETED (the fake adapter
    only supplies correct evidence when asked about the SPECIFIC gate named
    in the prompt), not a bare repeat of the original prompt."""
    tmp = _mk_smoke_project()
    try:
        stage = "SOC_SCENARIO_PLANNER"
        # corner_risk_rank always exits 0 (see gates.py's own caveat comment)
        # -- reset_power_cdc_corner_gate is the one real gate here whose FAIL
        # branch supplies a 'missing'-shaped detail we can drive RETRY_TARGETED
        # from without needing VERIFICATION_ARCHITECTURE's much larger mandatory
        # gate set.
        first_text = (
            '```dv-harness-evidence:corner_risk_rank\n'
            '{"cases": [{"corner_id": "c1", "risk_factors": ["x"]}]}\n```\n'
            '```dv-harness-evidence:reset_power_cdc_corner_gate\n'
            '{"corner_items": []}\n```\n'
        )
        verdict1, reasons1, sigs1 = evaluate_stage_evidence_with_detail(tmp, stage, first_text)
        assert verdict1 == "GATE_FAIL"
        by_id = {s.gate_id: s for s in sigs1}
        assert by_id["reset_power_cdc_corner_gate"].detail.get("missing") \
            or "missing" in json.dumps(by_id["reset_power_cdc_corner_gate"].detail)

        class TargetedRetryAdapter:
            def __init__(self):
                self.calls = 0

            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                self.calls += 1
                if "option_id=" in prompt:
                    # reflection call: pick the RETRY_TARGETED option if offered
                    m = re.search(r"option_id=(RETRY_TARGETED:\S+)", prompt)
                    chosen = m.group(1) if m else "CONVERGE_TERMINATE"
                    return AgentResult(ok=True, text=(
                        '```dv-harness-react-decision\n'
                        + json.dumps({"chosen_option_id": chosen, "conclusion": "retry targeted",
                                      "params": {}}) + '\n```'
                    ), raw={})
                # targeted re-attempt call: only supply correct evidence if the
                # EXACT failing gate_id was actually named in this prompt.
                assert "reset_power_cdc_corner_gate" in prompt
                return AgentResult(ok=True, text=(
                    '```dv-harness-evidence:corner_risk_rank\n'
                    '{"cases": [{"corner_id": "c1", "risk_factors": ["x"]}]}\n```\n'
                    '```dv-harness-evidence:reset_power_cdc_corner_gate\n'
                    '{"corner_items": ['
                    '{"corner_id": "c1", "domain": "RESET", "requirement_ids": ["R1"], '
                    '"mechanism_ids": ["M1"], "testcase_ids": ["T1"], '
                    '"async_or_partial_reset_covered": true}, '
                    '{"corner_id": "c2", "domain": "CLOCK", "requirement_ids": ["R2"], '
                    '"mechanism_ids": ["M2"], "testcase_ids": ["T2"]}, '
                    '{"corner_id": "c3", "domain": "CDC", "requirement_ids": ["R3"], '
                    '"mechanism_ids": ["M3"], "testcase_ids": ["T3"], '
                    '"cdc_observation_or_assertion": true}'
                    ']}\n```\n'
                ), raw={}, session_id="s-retry")

        adapter = TargetedRetryAdapter()
        first_result = AgentResult(ok=True, text=first_text, raw={}, session_id="s0")
        outcome = InnerReactLoop(tmp, adapter, react_recorder=None,
                                  cfg={"policy": {"inner_react_max_iterations": 3,
                                                   "inner_react_max_adapter_calls": 2}},
                                  graph=None).run(
            stage, node=None, attempt=1, first_result=first_result,
            first_verdict=verdict1, first_reasons=reasons1, first_signatures=sigs1,
            base_prompt="original stage prompt",
        )
        assert outcome.verdict == "PASS"
        assert adapter.calls == 2  # one reflection call + one targeted retry call
    finally:
        shutil.rmtree(tmp)


# --- InnerReactLoop <-> StageExecutionProfiler wiring (per-agent-attribution
# audit fix, 2026-09-01): before this fix, profiler/profile_id/agent_name
# were never threaded into InnerReactLoop at all -- every real adapter.run()
# call the inner loop made (reflection + RETRY_TARGETED retries) was
# completely invisible to the stage profile's total_tokens/aggregate
# runtime. -----------------------------------------------------------------

class _TwoStepRetryAdapter:
    """Drives InnerReactLoop through exactly 2 inner iterations against the
    real reset_power_cdc_corner_gate script (tools/verification_flow/
    reset_power_cdc_corner_gate.py, read before writing this): retry #1
    supplies RESET+CLOCK domains only (still missing CDC -- genuinely NEW
    information vs. the original all-3-domains-missing failure, so
    RETRY_TARGETED is offered again rather than suppressed by the
    no-new-information rule), retry #2 supplies all 3 domains -> PASS. Each
    real adapter.run() call also carries real token usage so the profiler's
    total_tokens genuinely grows call-to-call, not just its agents count."""

    def __init__(self):
        self.calls = 0
        self.retry_n = 0

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.calls += 1
        if "option_id=" in prompt:
            m = re.search(r"option_id=(RETRY_TARGETED:\S+)", prompt)
            chosen = m.group(1) if m else "CONVERGE_TERMINATE"
            return AgentResult(ok=True, text=(
                '```dv-harness-react-decision\n'
                + json.dumps({"chosen_option_id": chosen, "conclusion": "retry targeted",
                              "params": {}}) + '\n```'
            ), raw={"response": {"usage": {"input_tokens": 5, "output_tokens": 2}}})
        assert "reset_power_cdc_corner_gate" in prompt
        self.retry_n += 1
        corner_items = (
            '{"corner_id": "c1", "domain": "RESET", "requirement_ids": ["R1"], '
            '"mechanism_ids": ["M1"], "testcase_ids": ["T1"], '
            '"async_or_partial_reset_covered": true}, '
            '{"corner_id": "c2", "domain": "CLOCK", "requirement_ids": ["R2"], '
            '"mechanism_ids": ["M2"], "testcase_ids": ["T2"]}'
        )
        if self.retry_n >= 2:
            corner_items += (
                ', {"corner_id": "c3", "domain": "CDC", "requirement_ids": ["R3"], '
                '"mechanism_ids": ["M3"], "testcase_ids": ["T3"], '
                '"cdc_observation_or_assertion": true}'
            )
        text = (
            '```dv-harness-evidence:corner_risk_rank\n'
            '{"cases": [{"corner_id": "c1", "risk_factors": ["x"]}]}\n```\n'
            '```dv-harness-evidence:reset_power_cdc_corner_gate\n'
            f'{{"corner_items": [{corner_items}]}}\n```\n'
        )
        return AgentResult(ok=True, text=text, session_id="s-retry",
                            raw={"response": {"usage": {"input_tokens": 20, "output_tokens": 10}}})


class _SingleConvergeAdapter:
    """One reflection call, immediately CONVERGE_TERMINATE -- the ONE of
    ARCH_CALIBRATION's 3 gates with no GATE_FAILURE_REROUTE mapping, no
    matching graph edge, and no 'missing'/'protocol' structured field (see
    _ARCH_CALIBRATION_GATE_FAILS_NO_REROUTE above), so the menu offers
    nothing but CONVERGE_TERMINATE and this always fires in exactly 1 inner
    iteration / 1 adapter call."""

    def __init__(self):
        self.calls = 0

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.calls += 1
        assert "option_id=" in prompt
        return AgentResult(ok=True, text=(
            '```dv-harness-react-decision\n'
            '{"chosen_option_id": "CONVERGE_TERMINATE", '
            '"conclusion": "no actionable option in the real menu.", "params": {}}\n```'
        ), raw={"response": {"usage": {"input_tokens": 5, "output_tokens": 2}}})


def test_inner_react_loop_with_2plus_iterations_records_more_agent_runs_than_single_iteration():
    """The crux test for the profiler-wiring fix: a run that genuinely takes
    2 inner ReAct iterations (2 reflections + 2 targeted retries = 4 real
    adapter.run() calls) must leave 4 agent-run entries (and a correspondingly
    larger total_tokens) on its stage profile, strictly more than a run that
    converges in a single iteration (1 reflection = 1 real adapter.run() call
    -> 1 agent-run entry) against the SAME profiler/agent_name plumbing."""
    tmp = _mk_smoke_project()
    try:
        graph = _load_real_graph()
        node = graph.nodes["ARCH_CALIBRATION"]
        profiler = StageExecutionProfiler(tmp)

        # --- multi-iteration run (2 inner iterations, 4 real adapter calls) --
        stage_multi = "SOC_SCENARIO_PLANNER"
        first_text_multi = (
            '```dv-harness-evidence:corner_risk_rank\n'
            '{"cases": [{"corner_id": "c1", "risk_factors": ["x"]}]}\n```\n'
            '```dv-harness-evidence:reset_power_cdc_corner_gate\n'
            '{"corner_items": []}\n```\n'
        )
        v1, r1, s1 = evaluate_stage_evidence_with_detail(tmp, stage_multi, first_text_multi)
        assert v1 == "GATE_FAIL"
        first_result_multi = AgentResult(ok=True, text=first_text_multi, raw={}, session_id="s0")
        profile_multi = profiler.begin_stage(stage_multi, stage_multi)
        adapter_multi = _TwoStepRetryAdapter()
        outcome_multi = InnerReactLoop(
            tmp, adapter_multi, react_recorder=None,
            cfg={"policy": {"inner_react_max_iterations": 5, "inner_react_max_adapter_calls": 5}},
            graph=None, profiler=profiler, profile_id=profile_multi["profile_id"],
            agent_name="soc-scenario-agent",
        ).run(
            stage_multi, node=None, attempt=1, first_result=first_result_multi,
            first_verdict=v1, first_reasons=r1, first_signatures=s1,
            base_prompt="original stage prompt",
        )
        assert outcome_multi.verdict == "PASS"
        assert outcome_multi.iterations >= 2
        assert adapter_multi.calls == 4  # 2 reflections + 2 targeted retries

        # --- single-iteration run (1 inner iteration, 1 real adapter call) --
        stage_single = "ARCH_CALIBRATION"
        v2, r2, s2 = evaluate_stage_evidence_with_detail(
            tmp, stage_single, _ARCH_CALIBRATION_GATE_FAILS_NO_REROUTE)
        assert v2 == "GATE_FAIL"
        first_result_single = AgentResult(ok=True, text=_ARCH_CALIBRATION_GATE_FAILS_NO_REROUTE,
                                           raw={}, session_id="s0")
        profile_single = profiler.begin_stage(stage_single, stage_single)
        adapter_single = _SingleConvergeAdapter()
        outcome_single = InnerReactLoop(
            tmp, adapter_single, react_recorder=None,
            cfg={"policy": {"inner_react_max_iterations": 5, "inner_react_max_adapter_calls": 5}},
            graph=graph, profiler=profiler, profile_id=profile_single["profile_id"],
            agent_name="soc-scenario-agent",
        ).run(
            stage_single, node, attempt=1, first_result=first_result_single,
            first_verdict=v2, first_reasons=r2, first_signatures=s2,
            base_prompt="original stage prompt",
        )
        assert outcome_single.iterations == 1
        assert adapter_single.calls == 1

        # --- the actual profiler-wiring assertion ---------------------------
        rec_multi = profiler._load(profile_multi["profile_id"])
        rec_single = profiler._load(profile_single["profile_id"])
        assert len(rec_multi["agents"]) == 4
        assert len(rec_single["agents"]) == 1
        assert len(rec_multi["agents"]) > len(rec_single["agents"])
        assert all(a["agent"] == "soc-scenario-agent" for a in rec_multi["agents"])
        assert all(a["agent"] == "soc-scenario-agent" for a in rec_single["agents"])
        assert rec_multi["total_tokens"] > rec_single["total_tokens"]
        assert rec_multi["aggregate_agent_runtime_sec"] > 0
    finally:
        shutil.rmtree(tmp)


def test_inner_react_loop_omits_profiler_calls_as_a_genuine_no_op_by_default():
    """profiler/profile_id default to None, None -- every pre-existing caller
    of InnerReactLoop that never threads them through (every other test in
    this module) must be completely unaffected; this asserts that explicitly
    rather than only implicitly via the rest of the suite still passing."""
    menu = [MenuOption("CONVERGE_TERMINATE", "CONVERGE_TERMINATE", None, "r", "control")]

    class FakeAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            return AgentResult(ok=True, text=(
                '```dv-harness-react-decision\n'
                '{"chosen_option_id": "CONVERGE_TERMINATE", "conclusion": "x", "params": {}}\n```'
            ), raw={"response": {"usage": {"input_tokens": 1, "output_tokens": 1}}})

    # No exception, no profiler/profile_id required -- a pure no-op.
    decision = reflect_and_decide(FakeAdapter(), ROOT, "ARCH_CALIBRATION", {}, menu)
    assert decision.chosen_option_id == "CONVERGE_TERMINATE"


# --- attempt_hypothesis_refutation(): the adversarial self-critique step ---
# --- (adversarial_refutation_pass task, brand-new standalone function, ----
# --- nothing above this section is affected) --------------------------------

def test_attempt_hypothesis_refutation_reports_a_confirmed_survival():
    class SurvivesAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            assert "Hypothesis under review: ep0 FIFO underrun" in prompt
            assert "sim.log:4021" in prompt
            return AgentResult(ok=True, text=(
                '```dv-harness-refutation\n'
                '{"refuted": false, "counter_evidence": [], '
                '"rationale": "no contradicting evidence found"}\n```'
            ), raw={})

    outcome = attempt_hypothesis_refutation(
        SurvivesAdapter(), ROOT, "ep0 FIFO underrun due to missing prefetch",
        evidence_refs=["sim.log:4021"],
    )
    assert outcome == {
        "attempted": True, "refuted": False, "counter_evidence": [],
        "rationale": "no contradicting evidence found",
    }


def test_attempt_hypothesis_refutation_reports_a_confirmed_refutation_with_citations():
    class RefutesAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            return AgentResult(ok=True, text=(
                '```dv-harness-refutation\n'
                '{"refuted": true, "counter_evidence": ["rtl_top.sv:99: prefetch guard present"], '
                '"rationale": "the cited RTL line contradicts the claimed missing guard"}\n```'
            ), raw={})

    outcome = attempt_hypothesis_refutation(RefutesAdapter(), ROOT, "some hypothesis")
    assert outcome["attempted"] is True
    assert outcome["refuted"] is True
    assert outcome["counter_evidence"] == ["rtl_top.sv:99: prefetch guard present"]


def test_attempt_hypothesis_refutation_reasks_once_then_honestly_reports_not_attempted():
    calls = []

    class GarbageAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            calls.append(prompt)
            return AgentResult(ok=True, text="I have thought about it deeply.", raw={})

    outcome = attempt_hypothesis_refutation(GarbageAdapter(), ROOT, "some hypothesis")
    assert outcome["attempted"] is False
    assert outcome["refuted"] is False  # never guessed True either
    assert len(calls) == 2  # asked once, re-asked once, then honestly gave up


def test_attempt_hypothesis_refutation_transport_failure_reports_not_attempted():
    class FailingAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            return AgentResult(ok=False, text="", raw={})

    outcome = attempt_hypothesis_refutation(FailingAdapter(), ROOT, "some hypothesis")
    assert outcome["attempted"] is False
    assert outcome["refuted"] is False


def test_attempt_hypothesis_refutation_composes_directly_into_build_qualified_conclusion():
    """End-to-end proof this is a real, callable mechanism -- not just a
    function that returns a plausible-looking dict -- by feeding its real
    output straight into qualified_conclusion.build_qualified_conclusion()
    with require_refutation_pass=True."""
    from dv_harness.qualified_conclusion import build_qualified_conclusion
    from dv_harness.inference import score_confidence

    class SurvivesAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            return AgentResult(ok=True, text=(
                '```dv-harness-refutation\n'
                '{"refuted": false, "counter_evidence": [], "rationale": "withstands scrutiny"}\n```'
            ), raw={})

    refutation = attempt_hypothesis_refutation(
        SurvivesAdapter(), ROOT, "ep0 FIFO underrun", evidence_refs=["sim.log:4021"])
    confidence = score_confidence(independent_sources_count=3, evidence_refs_verified=True,
                                   counter_evidence_count=0, multi_agent_consensus_count=2)
    assert confidence["level"] == "HIGH"

    qc = build_qualified_conclusion("PASS", confidence, {"root_cause": "ep0 FIFO underrun"},
                                     refutation_result=refutation, require_refutation_pass=True)
    assert qc.is_qualified is True
    assert qc.refutation["attempted"] is True


def test_attempt_hypothesis_refutation_no_op_profiler_args_never_required():
    # Same "genuine no-op by default" contract as reflect_and_decide()'s
    # equivalent test above -- profiler/profile_id/agent_name are optional.
    class SurvivesAdapter:
        def run(self, prompt, cwd, resume_session=None, agent_profile=None):
            return AgentResult(ok=True, text=(
                '```dv-harness-refutation\n{"refuted": false}\n```'
            ), raw={"response": {"usage": {"input_tokens": 1, "output_tokens": 1}}})

    outcome = attempt_hypothesis_refutation(SurvivesAdapter(), ROOT, "x")
    assert outcome["attempted"] is True
    assert outcome["counter_evidence"] == []  # absent field normalizes to empty list


def test_attempt_hypothesis_refutation_wires_real_stage_execution_profiler():
    """Same profiler-wiring guarantee as InnerReactLoop's own reflection/retry
    calls (see the SECOND DEVIATION note) -- this new function's real
    adapter.run() call must not be invisible to StageExecutionProfiler when a
    caller does thread profiler/profile_id/agent_name through."""
    tmp = Path(tempfile.mkdtemp())
    try:
        profiler = StageExecutionProfiler(tmp)
        profile = profiler.begin_stage("RE_AUDIT", "RE_AUDIT")

        class SurvivesAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=(
                    '```dv-harness-refutation\n{"refuted": false}\n```'
                ), raw={"response": {"usage": {"input_tokens": 7, "output_tokens": 3}}})

        attempt_hypothesis_refutation(
            SurvivesAdapter(), tmp, "x",
            profiler=profiler, profile_id=profile["profile_id"], agent_name="rca-agent",
        )
        rec = profiler._load(profile["profile_id"])
        assert len(rec["agents"]) == 1
        assert rec["agents"][0]["agent"] == "rca-agent"
        assert rec["total_tokens"] > 0
    finally:
        shutil.rmtree(tmp)


# --- Engine integration: run_stage() wiring ---------------------------------

def test_run_stage_sets_react_reroute_target_on_vip_api_drift_failure():
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        class FakeAdapter:
            def __init__(self):
                self.n = 0

            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                self.n += 1
                if self.n == 1:
                    return AgentResult(ok=True, text=_ARCH_CALIBRATION_VIP_DRIFT_FAILS,
                                       raw={}, session_id="s1")
                # reflection call -- always pick the REROUTE option if present.
                m = re.search(r"option_id=(REROUTE:\S+)", prompt)
                chosen = m.group(1) if m else "CONVERGE_TERMINATE"
                return AgentResult(ok=True, text=(
                    '```dv-harness-react-decision\n'
                    + json.dumps({"chosen_option_id": chosen,
                                  "conclusion": "vip_api_drift_gate failed; reroute upstream.",
                                  "params": {}}) + '\n```'
                ), raw={}, session_id="s2")

        h = DVHarness(tmp)
        h.adapter = FakeAdapter()
        h.set_stage("ARCH_CALIBRATION")

        h.run_stage("calibrate architecture")
        ss = h.state.stages["ARCH_CALIBRATION"]
        assert ss["status"] == "PARTIAL"
        assert ss["react_reroute_target"] == "ARCH_DISCOVERY"

        reflect_files = list((tmp / ".dv-harness" / "react" / "ARCH_CALIBRATION" / "attempt_001").glob("reflect_*.json"))
        assert len(reflect_files) == 1
        doc = json.loads(reflect_files[0].read_text())
        assert doc["decision"]["chosen_option_id"] == "REROUTE:ARCH_DISCOVERY"
        assert any(m["kind"] == "REROUTE" for m in doc["menu"])
    finally:
        shutil.rmtree(tmp)


def test_run_stage_react_false_node_keeps_byte_identical_partial_path():
    """A stage whose graph node declares react:false must never enter the
    inner loop -- byte-identical PARTIAL+replan_stage() fallback."""
    tmp = _mk_smoke_project()
    try:
        graph_path = tmp / ".dv-harness" / "graph" / "main_graph.json"
        doc = json.loads(graph_path.read_text(encoding="utf-8"))
        for n in doc["nodes"]:
            if n["id"] == "ARCH_CALIBRATION":
                n["react"] = False
        graph_path.write_text(json.dumps(doc), encoding="utf-8")

        from dv_harness.engine import DVHarness

        calls = []

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                calls.append(prompt)
                return AgentResult(ok=True, text=_ARCH_CALIBRATION_VIP_DRIFT_FAILS, raw={}, session_id="s1")

        h = DVHarness(tmp)
        h.adapter = FakeAdapter()
        h.set_stage("ARCH_CALIBRATION")
        h.run_stage("calibrate architecture")

        ss = h.state.stages["ARCH_CALIBRATION"]
        assert ss["status"] == "PARTIAL"
        assert ss.get("react_reroute_target") is None
        assert len(calls) == 1  # no reflection call at all -- inner loop never entered
        assert not (tmp / ".dv-harness" / "react" / "ARCH_CALIBRATION" / "attempt_001").exists()
    finally:
        shutil.rmtree(tmp)


def test_run_stage_enable_inner_react_loop_false_keeps_byte_identical_partial_path():
    """The global escape hatch: policy.enable_inner_react_loop=False must
    behave exactly like react:false, even on a node that never set react:false
    itself."""
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        calls = []

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                calls.append(prompt)
                return AgentResult(ok=True, text=_ARCH_CALIBRATION_VIP_DRIFT_FAILS, raw={}, session_id="s1")

        h = DVHarness(tmp)
        h.adapter = FakeAdapter()
        h.cfg["policy"]["enable_inner_react_loop"] = False
        h.set_stage("ARCH_CALIBRATION")
        h.run_stage("calibrate architecture")

        ss = h.state.stages["ARCH_CALIBRATION"]
        assert ss["status"] == "PARTIAL"
        assert len(calls) == 1
    finally:
        shutil.rmtree(tmp)


def test_loop_routes_via_react_reroute_hint_when_graph_has_no_fail_edge():
    """ARCH_CALIBRATION has no FAIL edge in the real main_graph.json (only a
    PASS edge to PROJECT_MODEL) -- before this feature, exhausting retries
    here would just stall (graph_next(..., FAIL, ...) returns None). With the
    react_reroute_target hint set by a real REROUTE decision, loop() now
    routes to ARCH_DISCOVERY instead."""
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness
        from dv_harness.policy import graph_next

        # Sanity: confirm the real graph genuinely has no FAIL edge here.
        assert graph_next("ARCH_CALIBRATION", "FAIL", tmp) is None

        class FakeAdapter:
            def __init__(self):
                self.n = 0

            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                self.n += 1
                if "option_id=" not in prompt:
                    return AgentResult(ok=True, text=_ARCH_CALIBRATION_VIP_DRIFT_FAILS,
                                        raw={}, session_id=f"s{self.n}")
                m = re.search(r"option_id=(REROUTE:\S+)", prompt)
                chosen = m.group(1) if m else "CONVERGE_TERMINATE"
                return AgentResult(ok=True, text=(
                    '```dv-harness-react-decision\n'
                    + json.dumps({"chosen_option_id": chosen, "conclusion": "reroute upstream",
                                  "params": {}}) + '\n```'
                ), raw={}, session_id=f"s{self.n}")

        h = DVHarness(tmp)
        h.adapter = FakeAdapter()
        h.cfg["policy"]["max_stage_retries"] = 1
        h.set_stage("ARCH_CALIBRATION")
        h.loop("calibrate architecture")

        assert h.state.current_stage == "ARCH_DISCOVERY"
    finally:
        shutil.rmtree(tmp)


# --- compute_adaptive_react_budget(): opt-in complexity-scaled ReAct budget -
# --- (adaptive_react_budget gap-close, 2026-09-07). Nothing above this -----
# --- section is affected -- these are additive tests over an additive -----
# --- change. -----------------------------------------------------------------

def _rmtree_tolerant(path):
    """shutil.rmtree() that survives a real .git tree's read-only object
    files on Windows (WinError 5) -- the exact, already-documented failure
    class CLAUDE.md's own Engineering Memory Policy section names ("a plain
    shutil.rmtree() of a directory containing a real .git tree fails with
    PermissionError on git's read-only object files"). Only the two new
    git-backed InnerReactLoop integration tests below use this -- every
    pre-existing test's own bare `shutil.rmtree(tmp)` (no git repo involved)
    is left untouched."""
    def _onexc(func, path_, exc):
        try:
            os.chmod(path_, stat.S_IWRITE)
            func(path_)
        except Exception:
            pass
    shutil.rmtree(path, onexc=_onexc)


def _run_git(cmd, cwd):
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_git_repo(root: Path):
    """Same real-git-repo convention test_safety_sandbox.py's own _init_repo()
    already established -- reused here rather than a second helper with the
    same shape."""
    _run_git(["git", "init"], root)
    _run_git(["git", "config", "user.email", "test@example.com"], root)
    _run_git(["git", "config", "user.name", "Test"], root)


def _git_commit_baseline(root: Path, relative_paths):
    for rel in relative_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("baseline\n", encoding="utf-8")
    _run_git(["git", "add", "-A"], root)
    _run_git(["git", "commit", "-m", "base"], root)


def _git_touch_and_stage(root: Path, relative_paths):
    """Real, evidence-grounded worktree changes `git diff --name-only HEAD`
    will report: modifies each already-committed path (or creates + stages a
    brand-new one, since `git diff --name-only HEAD` never reports a genuinely
    untracked file -- confirmed directly against the real git binary before
    writing this fixture)."""
    for rel in relative_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("touched\n", encoding="utf-8")
    _run_git(["git", "add", "-A"], root)


def test_distinct_subsystems_is_a_real_deduplicated_top_level_grouping():
    assert _distinct_subsystems([
        "dv_harness/a.py", "dv_harness/b.py", "tools/remote/x.py", "README.md",
    ]) == ["dv_harness", "tools"]
    assert _distinct_subsystems([]) == []


def test_compute_adaptive_react_budget_default_disabled_is_byte_identical_to_the_old_fixed_reads(tmp_path, monkeypatch):
    """No adaptive_react_budget block at all -- the exact two-.get() default
    behavior InnerReactLoop.run() used before this function existed. No git
    subprocess may be invoked in this branch (proven, not merely asserted)."""
    def _forbidden(*a, **kw):
        raise AssertionError("must not invoke git in fixed mode")
    monkeypatch.setattr(subprocess, "check_output", _forbidden)

    cfg = {"policy": {"inner_react_max_iterations": 7, "inner_react_max_adapter_calls": 9}}
    result = compute_adaptive_react_budget(cfg, tmp_path)
    assert result == {"mode": "fixed", "max_iterations": 7, "max_adapter_calls": 9}


def test_compute_adaptive_react_budget_empty_or_none_cfg_uses_the_same_3_and_2_defaults(tmp_path):
    assert compute_adaptive_react_budget(None, tmp_path) == {
        "mode": "fixed", "max_iterations": 3, "max_adapter_calls": 2,
    }
    assert compute_adaptive_react_budget({}, tmp_path) == {
        "mode": "fixed", "max_iterations": 3, "max_adapter_calls": 2,
    }


def test_compute_adaptive_react_budget_explicit_enabled_false_still_fixed(tmp_path):
    """A project that declares the block but leaves it off must behave
    exactly like a project that never declared it at all -- the presence of
    adaptive_react_budget.min_iterations=99 here must never leak into the
    fixed-mode result."""
    cfg = {"policy": {"adaptive_react_budget": {"enabled": False, "min_iterations": 99}}}
    assert compute_adaptive_react_budget(cfg, tmp_path) == {
        "mode": "fixed", "max_iterations": 3, "max_adapter_calls": 2,
    }


def test_compute_adaptive_react_budget_enabled_no_git_repo_floors_at_the_declared_minimums(tmp_path):
    """The required negative control: with real evidence unavailable (no git
    repo at all), the module must never crash and must never treat absence of
    evidence as 'unlimited complexity' -- it floors both budgets at their
    declared min_* values, honestly."""
    cfg = {"policy": {"adaptive_react_budget": {
        "enabled": True, "min_iterations": 2, "max_iterations": 6,
        "min_adapter_calls": 1, "max_adapter_calls": 4,
    }}}
    result = compute_adaptive_react_budget(cfg, tmp_path)
    assert result["mode"] == "complexity_scaled"
    assert result["distinct_file_count"] == 0
    assert result["distinct_subsystem_count"] == 0
    assert result["max_iterations"] == 2
    assert result["max_adapter_calls"] == 1


def test_compute_adaptive_react_budget_enabled_real_git_diff_scales_both_budgets(tmp_path):
    """A real git repo with real modified files spanning 4 distinct top-level
    subsystem directories -- the exact 'number of distinct files/subsystems
    touched by the current investigation' signal this item names -- drives
    the scaled formula, checked against hand-computed expected values."""
    _init_git_repo(tmp_path)
    _git_commit_baseline(tmp_path, [
        "dv_harness/a.py", "tools/b.py", "tests/c.py",
    ])
    _git_touch_and_stage(tmp_path, [
        "dv_harness/a.py", "tools/b.py", "tests/c.py", "docs/d.py",
    ])
    cfg = {"policy": {"adaptive_react_budget": {
        "enabled": True,
        "min_iterations": 2, "max_iterations": 6, "files_per_iteration_step": 2,
        "min_adapter_calls": 1, "max_adapter_calls": 4, "subsystems_per_iteration_step": 2,
    }}}
    result = compute_adaptive_react_budget(cfg, tmp_path)
    assert result["mode"] == "complexity_scaled"
    assert result["distinct_file_count"] == 4
    assert sorted(result["subsystems"]) == ["docs", "dv_harness", "tests", "tools"]
    assert result["distinct_subsystem_count"] == 4
    # min_iterations(2) + floor(4 files / 2 per step) = 4
    assert result["max_iterations"] == 4
    # min_adapter_calls(1) + floor(4 subsystems / 2 per step) = 3
    assert result["max_adapter_calls"] == 3


def test_compute_adaptive_react_budget_enabled_clamps_at_the_declared_ceiling(tmp_path):
    """A large real investigation must never scale past the declared
    ceilings -- the linear formula is clamped, never unbounded."""
    _init_git_repo(tmp_path)
    many_files = [f"subsys_{i}/f.py" for i in range(20)]
    _git_commit_baseline(tmp_path, many_files)
    _git_touch_and_stage(tmp_path, many_files)
    cfg = {"policy": {"adaptive_react_budget": {
        "enabled": True,
        "min_iterations": 2, "max_iterations": 6, "files_per_iteration_step": 1,
        "min_adapter_calls": 1, "max_adapter_calls": 4, "subsystems_per_iteration_step": 1,
    }}}
    result = compute_adaptive_react_budget(cfg, tmp_path)
    assert result["distinct_file_count"] == 20
    assert result["distinct_subsystem_count"] == 20
    assert result["max_iterations"] == 6     # ceiling, not 2 + 20
    assert result["max_adapter_calls"] == 4  # ceiling, not 1 + 20


def test_compute_adaptive_react_budget_malformed_adaptive_block_falls_back_to_fixed_never_raises(tmp_path):
    """A human-editable config.json is exactly the kind of input that can be
    malformed -- this must degrade to the safe fixed-mode default rather than
    ever raising out of InnerReactLoop.run() and failing a real stage."""
    cfg = {"policy": {
        "inner_react_max_iterations": 3, "inner_react_max_adapter_calls": 2,
        "adaptive_react_budget": {"enabled": True, "min_iterations": "not-a-number"},
    }}
    result = compute_adaptive_react_budget(cfg, tmp_path)
    assert result["mode"] == "fixed"
    assert result["max_iterations"] == 3
    assert result["max_adapter_calls"] == 2
    assert "adaptive_react_budget_error" in result


# --- InnerReactLoop.run() wiring: the budget genuinely governs the loop -----

def test_inner_react_loop_default_cfg_reports_fixed_mode_in_budget_info():
    """Every pre-existing caller's cfg (no adaptive_react_budget key) must
    still report mode='fixed' on the outcome, and the fixed values it already
    passed unchanged -- an observability-only additive field, never a
    behavior change for a project that has not opted in."""
    tmp = _mk_smoke_project()
    try:
        graph = _load_real_graph()
        node = graph.nodes["ARCH_CALIBRATION"]
        stage = "ARCH_CALIBRATION"
        verdict, reasons, sigs = evaluate_stage_evidence_with_detail(
            tmp, stage, _ARCH_CALIBRATION_GATE_FAILS_NO_REROUTE)
        first_result = AgentResult(ok=True, text=_ARCH_CALIBRATION_GATE_FAILS_NO_REROUTE,
                                    raw={}, session_id="s0")
        outcome = InnerReactLoop(
            tmp, _SingleConvergeAdapter(), react_recorder=None,
            cfg={"policy": {"inner_react_max_iterations": 5, "inner_react_max_adapter_calls": 5}},
            graph=graph,
        ).run(stage, node, attempt=1, first_result=first_result, first_verdict=verdict,
              first_reasons=reasons, first_signatures=sigs, base_prompt="original stage prompt")
        assert outcome.budget_info == {"mode": "fixed", "max_iterations": 5, "max_adapter_calls": 5}
    finally:
        shutil.rmtree(tmp)


def test_inner_react_loop_adaptive_budget_genuinely_constrains_the_real_loop(tmp_path):
    """A real, small investigation (1 file, 1 subsystem) scales
    max_adapter_calls down to 1 -- one below what _TwoStepRetryAdapter needs
    to reach PASS (2 targeted retries) -- so the loop must genuinely stop
    short of PASS: iteration 1 does 1 reflection + 1 targeted retry (real
    adapter calls 1-2, spending the whole budget of 1 retry), and iteration 2
    reflects once more (real adapter call 3) but the safety-backstop check
    then refuses the second targeted retry before ever issuing it -- for a
    real total of 3 adapter.run() calls, one fewer than the 4 the SAME
    adapter/gate/cfg-shape needs to reach PASS in the unconstrained (fixed,
    max_adapter_calls=5) test above. This is the real proof the new budget
    mode actually governs InnerReactLoop.run(), not merely computes a number
    nothing reads."""
    tmp = _mk_smoke_project()
    try:
        _init_git_repo(tmp)
        _git_commit_baseline(tmp, ["dv_harness/only.py"])
        _git_touch_and_stage(tmp, ["dv_harness/only.py"])

        stage = "SOC_SCENARIO_PLANNER"
        first_text = (
            '```dv-harness-evidence:corner_risk_rank\n'
            '{"cases": [{"corner_id": "c1", "risk_factors": ["x"]}]}\n```\n'
            '```dv-harness-evidence:reset_power_cdc_corner_gate\n'
            '{"corner_items": []}\n```\n'
        )
        v1, r1, s1 = evaluate_stage_evidence_with_detail(tmp, stage, first_text)
        assert v1 == "GATE_FAIL"
        first_result = AgentResult(ok=True, text=first_text, raw={}, session_id="s0")
        adapter = _TwoStepRetryAdapter()
        cfg = {"policy": {"adaptive_react_budget": {
            "enabled": True,
            "min_iterations": 5, "max_iterations": 5, "files_per_iteration_step": 1,
            "min_adapter_calls": 1, "max_adapter_calls": 1, "subsystems_per_iteration_step": 1,
        }}}
        outcome = InnerReactLoop(tmp, adapter, react_recorder=None, cfg=cfg, graph=None).run(
            stage, node=None, attempt=1, first_result=first_result,
            first_verdict=v1, first_reasons=r1, first_signatures=s1,
            base_prompt="original stage prompt",
        )
        assert outcome.budget_info["mode"] == "complexity_scaled"
        assert outcome.budget_info["max_adapter_calls"] == 1
        assert outcome.verdict == "GATE_FAIL"  # never reached PASS -- the CDC domain retry was cut off
        assert adapter.calls == 3  # 1 reflect + 1 retry, then 1 more reflect before the budget refuses the 2nd retry
    finally:
        _rmtree_tolerant(tmp)


def test_inner_react_loop_adaptive_budget_scaled_up_still_reaches_pass(tmp_path):
    """The converse of the constraining test above: a real investigation
    touching enough distinct subsystems earns a large-enough
    max_adapter_calls that the SAME _TwoStepRetryAdapter genuinely reaches
    PASS -- proving the scaling formula grants MORE budget for a more
    complex real investigation, not merely less."""
    tmp = _mk_smoke_project()
    try:
        _init_git_repo(tmp)
        _git_commit_baseline(tmp, [
            "dv_harness/a.py", "tools/b.py", "tests/c.py", "docs/d.py",
        ])
        _git_touch_and_stage(tmp, [
            "dv_harness/a.py", "tools/b.py", "tests/c.py", "docs/d.py",
        ])

        stage = "SOC_SCENARIO_PLANNER"
        first_text = (
            '```dv-harness-evidence:corner_risk_rank\n'
            '{"cases": [{"corner_id": "c1", "risk_factors": ["x"]}]}\n```\n'
            '```dv-harness-evidence:reset_power_cdc_corner_gate\n'
            '{"corner_items": []}\n```\n'
        )
        v1, r1, s1 = evaluate_stage_evidence_with_detail(tmp, stage, first_text)
        first_result = AgentResult(ok=True, text=first_text, raw={}, session_id="s0")
        adapter = _TwoStepRetryAdapter()
        cfg = {"policy": {"adaptive_react_budget": {
            "enabled": True,
            "min_iterations": 2, "max_iterations": 6, "files_per_iteration_step": 4,
            "min_adapter_calls": 1, "max_adapter_calls": 4, "subsystems_per_iteration_step": 2,
        }}}
        outcome = InnerReactLoop(tmp, adapter, react_recorder=None, cfg=cfg, graph=None).run(
            stage, node=None, attempt=1, first_result=first_result,
            first_verdict=v1, first_reasons=r1, first_signatures=s1,
            base_prompt="original stage prompt",
        )
        # min_adapter_calls(1) + floor(4 subsystems / 2 per step) = 3 >= 2 needed
        assert outcome.budget_info["max_adapter_calls"] == 3
        assert outcome.verdict == "PASS"
        assert adapter.calls == 4  # 2 reflections + 2 targeted retries, exactly as the fixed-budget test
    finally:
        _rmtree_tolerant(tmp)
