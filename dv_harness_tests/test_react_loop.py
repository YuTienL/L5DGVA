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
import re
import shutil
import tempfile
from pathlib import Path

from dv_harness.gates import GATE_FAILURE_REROUTE
from dv_harness.react_loop import (
    GateSignature, MenuOption, ReactDecision, InnerReactLoop,
    build_menu, reflect_and_decide, evaluate_stage_evidence_with_detail,
    _signatures_equal,
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
