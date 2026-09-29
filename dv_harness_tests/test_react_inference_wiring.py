"""Plan-and-Execute / ReAct engine <-> dv_harness.inference wiring (2026-09-04).

Two real, confirmed gaps this module exists to prove closed -- both about the
REAL production path (engine.DVHarness.run_stage() driving a real graph node
with real gate scripts), not about the underlying functions working in
isolation, which they always did:

  1. build_menu() only ever offered ONE option (CONVERGE_TERMINATE) for the
     failure shape that actually occurs in practice. Every reflect_*.json
     this harness had persisted from a real run showed
     `{"reason": "NO_EVIDENCE_BLOCK_SUPPLIED"}` failing gates and a
     1-option menu, because build_menu()'s four original sources all require
     the failing gate's OWN detail to already enumerate a missing field --
     which a gate that never ran cannot do. RETRY_TARGETED / REQUEST_EVIDENCE
     / REROUTE therefore had zero real production occurrences.
  2. The per-attempt `react_reasoning_step` Working Memory record's
     `confidence`/`next_action` were hardcoded string maps on ss["status"]
     and it had no `gap` field at all, despite CLAUDE.md's Engineering Memory
     Policy naming inference.score_confidence()/identify_gap()/
     next_best_action() as the mechanism for exactly this record kind.

The engine-driven tests below assert against the REAL persisted artifacts
(.dv-harness/react/<node>/attempt_NNN/reflect_NNN.json and
.dv-harness/memory/working/WM-REACT-*.json), which is the same evidence the
audit read to confirm the gap.
"""
import json
import re
import shutil
import tempfile
from pathlib import Path

from dv_harness.adapters.base import AgentResult
from dv_harness.gates import evaluate_stage_evidence, effective_stage_gates
from dv_harness.graph import GraphDefinition
from dv_harness.react_loop import GateSignature, build_menu, evaluate_stage_evidence_with_detail

ROOT = Path(__file__).resolve().parents[1]


def _mk_smoke_project():
    """Same fixture shape test_react_loop.py uses: a fresh temp project with
    the REAL main_graph.json, real .claude/agents and real
    tools/verification_flow gate scripts, so the gates genuinely subprocess-run."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    shutil.copytree(ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


# ARCH_CALIBRATION's real gates, with a block supplied for exactly ONE of the
# three -- so the other two produce the real NO_EVIDENCE_BLOCK_SUPPLIED
# signature shape gates._evaluate_stage_evidence_core() synthesizes.
_ONLY_CALIBRATION_GATE_SUPPLIED = (
    '```dv-harness-evidence:architecture_calibration_gate\n'
    '{"architecture_before": {"a": 1}, "architecture_after": {"a": 1}}\n```\n'
)


# --- build_menu(): the NO_EVIDENCE_BLOCK_SUPPLIED source --------------------

def test_real_stage_with_a_missing_evidence_block_produces_the_degenerate_signature_shape():
    """Grounding assertion for everything below: this is the REAL failure
    shape (from the real gate-evaluation core, not a hand-written dict) that
    used to yield a 1-option menu."""
    tmp = _mk_smoke_project()
    try:
        verdict, _reasons, sigs = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _ONLY_CALIBRATION_GATE_SUPPLIED)
        assert verdict == "GATE_FAIL"
        no_block = {s.gate_id for s in sigs
                    if s.detail.get("reason") == "NO_EVIDENCE_BLOCK_SUPPLIED"}
        assert no_block == {"architecture_calibration_conflict_gate", "vip_api_drift_gate"}
        # Neither carries any of the four structured detail keys build_menu()'s
        # original sources needed.
        for s in sigs:
            if s.gate_id in no_block:
                assert set(s.detail) == {"status", "reason"}
    finally:
        shutil.rmtree(tmp)


def test_build_menu_offers_request_evidence_for_a_gate_with_no_evidence_block():
    tmp = _mk_smoke_project()
    try:
        _verdict, _reasons, sigs = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _ONLY_CALIBRATION_GATE_SUPPLIED)
        menu = build_menu(tmp, "ARCH_CALIBRATION", node=None, signatures=sigs, graph=None)

        # The gap this closes: the menu is no longer CONVERGE-only.
        assert len(menu) > 1
        req = [m for m in menu if m.kind == "REQUEST_EVIDENCE"]
        assert {m.target for m in req} == {"architecture_calibration_conflict_gate",
                                           "vip_api_drift_gate"}
        assert all(m.source == "stage_gate_missing_evidence_block" for m in req)
        # The rationale names the exact fence the agent must produce, and the
        # real identify_gap() output over the stage's real configured gates.
        one = next(m for m in req if m.target == "vip_api_drift_gate")
        assert "dv-harness-evidence:vip_api_drift_gate" in one.rationale
        assert "architecture_calibration_conflict_gate" in one.rationale
        # CONVERGE_TERMINATE stays available alongside the real actions.
        assert any(m.option_id == "CONVERGE_TERMINATE" for m in menu)
    finally:
        shutil.rmtree(tmp)


def test_build_menu_missing_evidence_block_gap_matches_the_real_configured_gate_list():
    """The option set is a real set difference over gates.effective_stage_gates(),
    not a fixed list -- a gate the project's own overlay configures is included
    and one it does not is never invented."""
    tmp = _mk_smoke_project()
    try:
        configured = [gid for gid, _s, _f in effective_stage_gates("ARCH_CALIBRATION", tmp)]
        _verdict, _reasons, sigs = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _ONLY_CALIBRATION_GATE_SUPPLIED)
        assert [s.gate_id for s in sigs] == configured
        menu = build_menu(tmp, "ARCH_CALIBRATION", node=None, signatures=sigs, graph=None)
        req_targets = {m.target for m in menu if m.source == "stage_gate_missing_evidence_block"}
        assert req_targets == set(configured) - {"architecture_calibration_gate"}
    finally:
        shutil.rmtree(tmp)


def test_build_menu_missing_evidence_block_option_is_suppressed_when_no_new_information():
    """Same discipline the pre-existing RETRY_TARGETED sources follow: if the
    previous inner iteration produced byte-identical signatures, re-asking for
    the same block is not a genuinely different action."""
    tmp = _mk_smoke_project()
    try:
        _verdict, _reasons, sigs = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _ONLY_CALIBRATION_GATE_SUPPLIED)
        menu = build_menu(tmp, "ARCH_CALIBRATION", node=None, signatures=sigs,
                          prior_signatures=sigs, graph=None)
        assert not any(m.kind == "REQUEST_EVIDENCE" for m in menu)
        assert any(m.option_id == "CONVERGE_NO_NEW_INFORMATION" for m in menu)
    finally:
        shutil.rmtree(tmp)


def test_build_menu_cites_a_real_registry_item_when_the_resolved_protocol_has_one():
    """`protocol` is the real RouteResolver-resolved protocol threaded in from
    run_stage(); when protocol_builder_registry.json really covers the gap the
    rationale carries that registry item, and when it does not the option is
    still offered (a missing block is actionable regardless).

    The gate_id here is deliberately spelled to match USB's real `discover`
    entry in protocol_builder_registry.json, because next_best_action()
    matches the gap string against those entries -- this exercises the
    citation path. Most real gate ids will NOT match one, which is exactly
    the second half of this test."""
    tmp = _mk_smoke_project()
    try:
        sig = GateSignature(gate_id="port topology", ok=False,
                            detail={"status": "FAIL", "reason": "NO_EVIDENCE_BLOCK_SUPPLIED"})
        with_protocol = build_menu(ROOT, "VERIFICATION_ARCHITECTURE", node=None,
                                   signatures=[sig], graph=None, protocol="usb")
        hit = next(m for m in with_protocol if m.kind == "REQUEST_EVIDENCE")
        assert "registry item" in hit.rationale and "usb" in hit.rationale

        without_protocol = build_menu(ROOT, "VERIFICATION_ARCHITECTURE", node=None,
                                      signatures=[sig], graph=None)
        still_offered = next(m for m in without_protocol if m.kind == "REQUEST_EVIDENCE")
        assert "registry item" not in still_offered.rationale
    finally:
        shutil.rmtree(tmp)


# --- The real production path: run_stage() end to end -----------------------

class _RequestEvidenceFakeAdapter:
    """Supplies only one of ARCH_CALIBRATION's three evidence blocks on the
    first call, then picks whatever REQUEST_EVIDENCE option the REAL menu
    offers -- so if build_menu() still returned a CONVERGE-only menu, this
    adapter could not choose a REQUEST_EVIDENCE option at all and the test
    below would fail."""

    def __init__(self):
        self.prompts = []

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.prompts.append(prompt)
        if "dv-harness-react-decision" not in prompt:
            return AgentResult(ok=True, text=_ONLY_CALIBRATION_GATE_SUPPLIED,
                               raw={}, session_id="s1")
        m = re.search(r"option_id=(REQUEST_EVIDENCE:\S+)", prompt)
        chosen = m.group(1) if m else "CONVERGE_TERMINATE"
        return AgentResult(ok=True, text=(
            '```dv-harness-react-decision\n'
            + json.dumps({"chosen_option_id": chosen,
                          "conclusion": "Two configured gates received no evidence block.",
                          "params": {}}) + '\n```'
        ), raw={}, session_id="s2")


def test_run_stage_reflection_record_now_offers_a_real_non_converge_option():
    """The audit's own stated verification method: re-drive a stage that fails
    with NO_EVIDENCE_BLOCK_SUPPLIED and confirm the persisted reflect_NNN.json
    now has len(menu) > 1 with a real non-CONVERGE option chosen."""
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        h = DVHarness(tmp)
        h.adapter = _RequestEvidenceFakeAdapter()
        # Keep the inner loop to a single targeted retry so the assertion below
        # is about the FIRST reflection record, not a converged later one.
        h.cfg["policy"]["inner_react_max_adapter_calls"] = 1
        h.set_stage("ARCH_CALIBRATION")
        h.run_stage("calibrate architecture")

        reflect = json.loads(
            (tmp / ".dv-harness" / "react" / "ARCH_CALIBRATION" / "attempt_001"
             / "reflect_001.json").read_text(encoding="utf-8"))
        assert len(reflect["menu"]) > 1, reflect["menu"]
        assert reflect["decision"]["chosen_option_id"].startswith("REQUEST_EVIDENCE:")
        assert reflect["decision"]["converged"] is False
        # The chosen option really came from the new source, over real signatures.
        chosen = next(m for m in reflect["menu"]
                      if m["option_id"] == reflect["decision"]["chosen_option_id"])
        assert chosen["source"] == "stage_gate_missing_evidence_block"
        assert any(s["detail"].get("reason") == "NO_EVIDENCE_BLOCK_SUPPLIED"
                   for s in reflect["signatures"])
        # And it really cost a targeted adapter re-invocation naming that gate.
        assert any("[Inner ReAct targeted re-attempt]" in p and chosen["target"] in p
                   for p in h.adapter.prompts)
    finally:
        shutil.rmtree(tmp)


def _read_working_memory_react_record(tmp, node, iteration):
    p = (tmp / ".dv-harness" / "memory" / "working"
         / f"WM-REACT-{node}-{iteration:03d}.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_run_stage_react_reasoning_step_record_carries_real_inference_output():
    """The persisted react_reasoning_step record's confidence/gap/next_action
    are now traceable to real score_confidence()/identify_gap()/
    next_best_action() calls over this attempt's own gate evidence -- not the
    old status-keyed string literals ("HIGH"/"MEDIUM"/"LOW" by status,
    "advance"/"retry_or_reroute")."""
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        h = DVHarness(tmp)
        h.adapter = _RequestEvidenceFakeAdapter()
        h.cfg["policy"]["inner_react_max_adapter_calls"] = 1
        h.set_stage("ARCH_CALIBRATION")
        h.run_stage("calibrate architecture")

        ss = h.state.stages["ARCH_CALIBRATION"]
        assert ss["status"] == "PARTIAL"

        rec = _read_working_memory_react_record(tmp, "ARCH_CALIBRATION", 1)
        assert rec["kind"] == "react_reasoning_step"

        # 1. `gap` exists at all (it had no field before) and is the REAL
        #    identify_gap() set difference over the stage's configured gates.
        configured = [gid for gid, _s, _f in effective_stage_gates("ARCH_CALIBRATION", tmp)]
        assert rec["gap"] == [g for g in configured if g != "architecture_calibration_gate"]

        # 2. `confidence` is traceable to a real score_confidence() result,
        #    not a status string map: PARTIAL used to hardcode "MEDIUM".
        detail = rec["confidence_detail"]
        assert set(detail) == {"level", "score", "capped_by_counter_evidence"}
        assert detail["level"] == rec["confidence"]
        assert rec["confidence"] == "LOW"          # 1 source, 2 real counter-evidence gates
        assert detail["score"] == 1 * 2 - 2 * 3    # the real formula, on real counts

        # 3. `next_action` is a real next_best_action() suggestion for the
        #    first gap, never the old literal "retry_or_reroute".
        from dv_harness.inference import next_best_action
        expected = next_best_action("_general", rec["gap"], tmp)
        assert rec["next_action"] == expected[0]["suggested_action"]
        assert rec["next_action"] != "retry_or_reroute"

        # The same values are on the react/ iteration file, one write path.
        it = json.loads((tmp / ".dv-harness" / "react" / "ARCH_CALIBRATION"
                         / "iteration_001.json").read_text(encoding="utf-8"))
        assert it["gap"] == rec["gap"]
        assert it["confidence_detail"] == detail
    finally:
        shutil.rmtree(tmp)


def test_react_reasoning_step_confidence_really_tracks_the_evidence_not_the_status():
    """Contrast case proving the number is evidence-driven: the SAME stage,
    the SAME PARTIAL status, but every configured gate supplied a block (one
    of them failing on content rather than absence) -> a different real
    confidence/score/gap than the missing-block run above, where the old
    hardcoded map would have reported an identical "MEDIUM"/"retry_or_reroute"
    for both."""
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        all_blocks_one_fails = (
            _ONLY_CALIBRATION_GATE_SUPPLIED
            + '```dv-harness-evidence:architecture_calibration_conflict_gate\n'
              '{"conflicts": []}\n```\n'
            + '```dv-harness-evidence:vip_api_drift_gate\n'
              '{"current_vip_version": "2.0", "qualified_vip_version": "1.0", '
              '"api_diff_analyzed": false}\n```\n'
        )
        assert evaluate_stage_evidence(tmp, "ARCH_CALIBRATION",
                                       all_blocks_one_fails)[0] == "GATE_FAIL"

        class FakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                if "dv-harness-react-decision" not in prompt:
                    return AgentResult(ok=True, text=all_blocks_one_fails, raw={},
                                       session_id="s1")
                m = re.search(r"option_id=(REROUTE:\S+)", prompt)
                chosen = m.group(1) if m else "CONVERGE_TERMINATE"
                return AgentResult(ok=True, text=(
                    '```dv-harness-react-decision\n'
                    + json.dumps({"chosen_option_id": chosen,
                                  "conclusion": "vip_api_drift_gate failed on content.",
                                  "params": {}}) + '\n```'
                ), raw={}, session_id="s2")

        h = DVHarness(tmp)
        h.adapter = FakeAdapter()
        h.set_stage("ARCH_CALIBRATION")
        h.run_stage("calibrate architecture")

        ss = h.state.stages["ARCH_CALIBRATION"]
        assert ss["status"] == "PARTIAL"          # same status as the run above
        rec = _read_working_memory_react_record(tmp, "ARCH_CALIBRATION", 1)
        assert rec["gap"] == []                   # every gate DID get a block
        # 3 real sources, 1 real failing gate -> a different real score.
        assert rec["confidence_detail"]["score"] == 3 * 2 - 1 * 3
        assert rec["confidence"] == "MEDIUM"
        # A real REROUTE was chosen, so next_action names the real target.
        assert ss["react_reroute_target"] == "ARCH_DISCOVERY"
        assert rec["next_action"] == "reroute:ARCH_DISCOVERY"
    finally:
        shutil.rmtree(tmp)


def test_react_reasoning_step_record_on_adapter_failure_stays_honest():
    """An ADAPTER_FAIL never reaches gate evaluation (a separate code path by
    design), so there are no signatures to score: the record must still carry
    a real, computed LOW rather than crash or invent counter-evidence."""
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        class DeadAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=False, text="", raw={"stderr": "transport down"},
                                   session_id=None)

        h = DVHarness(tmp)
        h.adapter = DeadAdapter()
        h.set_stage("ARCH_CALIBRATION")
        h.run_stage("calibrate architecture")

        assert h.state.stages["ARCH_CALIBRATION"]["status"] == "FAIL"
        rec = _read_working_memory_react_record(tmp, "ARCH_CALIBRATION", 1)
        # No block was supplied for any configured gate -> the whole gate list
        # is the real gap, and score_confidence() is fed zeros, not guesses.
        assert rec["gap"] == [gid for gid, _s, _f in effective_stage_gates("ARCH_CALIBRATION", tmp)]
        assert rec["confidence"] == "LOW"
        assert rec["confidence_detail"]["score"] == 0
        assert rec["confidence_detail"]["capped_by_counter_evidence"] is False
    finally:
        shutil.rmtree(tmp)


def test_graph_node_react_default_and_policy_default_keep_this_wiring_live():
    """Regression guard for the two flags that decide whether any of the above
    runs in production at all -- both default ON, in the real graph file."""
    graph = GraphDefinition.load(ROOT / ".dv-harness" / "graph" / "main_graph.json")
    assert graph.nodes["ARCH_CALIBRATION"].react is True
    doc = json.loads((ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"))
    assert not any(n.get("react") is False for n in doc["nodes"])


# --- The memory a stage attempt really consulted (2026-09-04, gap-close-
#     obsidian-memory phase 13+14) --------------------------------------------

def test_run_stage_persists_the_memory_context_it_really_consulted():
    """Third gap of the same shape as the two above: `relevant_memory` /
    `kc_search_results` / `vault_related_cases` were built fresh inside
    _gather_stage_context(), folded into the prompt, and then discarded --
    so nothing could later answer which prior knowledge was in play when a
    hypothesis was formed, and session_snapshot.save_session() had to re-run
    its own search at save time and label the guess `related_memory`.

    Asserted on the REAL persisted iteration_NNN.json produced by a real
    run_stage(), against a memory record seeded before the run."""
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness
        from dv_harness.memory import MemoryStore

        seeded = MemoryStore(tmp).add("engineering", {
            "title": "architecture calibration drift after wrapper swap",
            "protocol": "USB3", "root_cause": "calibrate step read a stale hierarchy path",
            "confidence": "HIGH", "evidence": ["rtl: wrapper depth changed"],
        })

        h = DVHarness(tmp)
        h.adapter = _RequestEvidenceFakeAdapter()
        h.cfg["policy"]["inner_react_max_adapter_calls"] = 1
        h.set_stage("ARCH_CALIBRATION")
        h.run_stage("calibrate architecture")

        iteration = json.loads(
            (tmp / ".dv-harness" / "react" / "ARCH_CALIBRATION"
             / "iteration_001.json").read_text(encoding="utf-8"))
        related = iteration["memory_context"]["related_memory"]
        assert seeded["memory_id"] in [r["memory_id"] for r in related]
        # References only -- the same five keys session_snapshot's own
        # related_memory shape uses, never the record body.
        assert set(related[0]) == {"memory_id", "level", "title", "root_cause", "confidence"}
        assert "evidence" not in related[0]

        # And it reached the Working Memory projection of the same step, so a
        # MemoryRetriever reader sees it too, not just the react/ file.
        rec = _read_working_memory_react_record(tmp, "ARCH_CALIBRATION", 1)
        assert rec["memory_context"]["related_memory"] == related
    finally:
        shutil.rmtree(tmp)
