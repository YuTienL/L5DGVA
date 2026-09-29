"""Engine-integration proof that dv_harness/protocol_router.py and
dv_harness/environment_mode_router.py are genuinely wired into
dv_harness.engine.DVHarness.run_stage() -- not disconnected modules.

Mirrors dv_harness_tests/test_react_loop.py's own crux-test shape
(test_two_runs_with_different_gate_failures_pick_different_actions): the
SAME real run_stage() call path, given two genuinely different real inputs,
must produce two genuinely different real resolver outputs that reach the
prompt actually sent to the adapter -- proving route_info['protocol_decision']/
['environment_mode_decision'] are load-bearing, not write-only metadata.

test_project_model_stage_passes_and_dashboard_now_reads_a_real_environment_mode_selection
additionally closes the exact gap dashboard.py's own
_environment_mode_selected() docstring documented as its "HONEST STATUS"
(2026-08-31): before this task, that function always returned None because
no stage ever emitted a real environment_mode_selection evidence block.
"""
import json
import shutil
import tempfile
from pathlib import Path

from dv_harness.adapters.base import AgentResult

ROOT = Path(__file__).resolve().parents[1]


def _mk_project_with_graph_and_agents() -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
    return tmp


def _add_real_registry_and_protocol_skills(tmp: Path) -> None:
    """Gives the temp project the two real inputs RouteResolver's protocol
    fold-in reads: the REAL protocol_builder_registry.json (copied verbatim,
    so profile_skill/vip_lookup_skill are the production values, not invented
    ones) and SKILL.md stubs at the skill paths that registry names, so
    SkillResolver can report found=True for them."""
    reg_src = ROOT / ".dv-harness" / "builder" / "protocol_builder_registry.json"
    reg_dst = tmp / ".dv-harness" / "builder" / "protocol_builder_registry.json"
    reg_dst.parent.mkdir(parents=True, exist_ok=True)
    reg_dst.write_text(reg_src.read_text(encoding="utf-8"), encoding="utf-8")
    for rel in ("CORE/protocol-router", "USB/usb-profile", "USB/usb-vip-lookup", "PCIe/pcie-profile"):
        d = tmp / ".claude" / "skills" / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text("# stub skill\n", encoding="utf-8")


class _CapturingAdapter:
    """Records the exact prompt run_stage() sends, never runs a real gate --
    text is deliberately gate-agnostic; these tests only care about what the
    harness decided BEFORE the LLM call, not the resulting stage verdict."""

    def __init__(self):
        self.prompts = []

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.prompts.append(prompt)
        return AgentResult(ok=True, text="noted.", raw={}, session_id=None)


def test_two_different_user_goals_pick_two_different_real_protocol_decisions():
    from dv_harness.engine import DVHarness

    seen = {}
    for goal, expected_protocol, expected_route in [
        ("investigate a USB3 link training failure", "usb", "USB/usb-profile"),
        ("investigate a PCIe LTSSM link training failure", "pcie", "PCIe/pcie-profile"),
    ]:
        tmp = _mk_project_with_graph_and_agents()
        try:
            h = DVHarness(tmp)
            adapter = _CapturingAdapter()
            h.adapter = adapter
            h.set_stage("DISCOVERY")
            h.run_stage(goal)
            # The FIRST adapter call is always the one carrying the real
            # stage prompt (route_info folded in before any LLM call, per
            # run_stage()'s own step 1); DISCOVERY's real mandatory gates
            # aren't satisfied by this test's minimal "noted." response, so
            # the inner ReAct loop may issue further reflection calls after
            # it -- irrelevant here, only the first prompt is under test.
            assert len(adapter.prompts) >= 1
            prompt = adapter.prompts[0]
            assert "Resolved protocol/profile" in prompt
            assert f'"protocol": "{expected_protocol}"' in prompt, prompt
            assert f'"route": "{expected_route}"' in prompt, prompt
            seen[expected_protocol] = prompt
        finally:
            shutil.rmtree(tmp)

    # The two real prompts genuinely differ in their resolved protocol.
    assert seen["usb"] != seen["pcie"]
    assert '"protocol": "pcie"' not in seen["usb"]
    assert '"protocol": "usb"' not in seen["pcie"]


def test_two_different_intake_subsystem_counts_pick_two_different_real_environment_modes():
    from dv_harness.engine import DVHarness

    seen = {}
    for subsystems, expected_mode in [
        (["usb"], "SUBSYSTEM_MODE"),
        (["usb", "pcie"], "SYSTEM_LEVEL_MODE"),
    ]:
        tmp = _mk_project_with_graph_and_agents()
        try:
            h = DVHarness(tmp)
            # Real INTAKE-shaped "project" Blackboard record (same shape
            # engine._bb_intake() writes) -- the genuine per-run source
            # _environment_mode_router_evidence() reads.
            h.blackboard.write("project", {"protocols": subsystems, "selected_subsystems": subsystems},
                                source="INTAKE")
            adapter = _CapturingAdapter()
            h.adapter = adapter
            h.set_stage("DISCOVERY")
            h.run_stage("continue verification")
            assert len(adapter.prompts) >= 1
            prompt = adapter.prompts[0]
            assert "Resolved environment mode" in prompt
            assert f'"environment_mode": "{expected_mode}"' in prompt, prompt
            seen[expected_mode] = prompt
        finally:
            shutil.rmtree(tmp)

    assert seen["SUBSYSTEM_MODE"] != seen["SYSTEM_LEVEL_MODE"]


def test_protocol_and_environment_mode_decisions_are_persisted_to_the_real_react_record():
    # Gap-close-engine cleanup (2026-09-03, .work/gap-close-engine-
    # investigation.md item 2): before this fix, route_info["protocol_decision"]/
    # ["environment_mode_decision"] existed ONLY as local Python variables
    # folded into the ephemeral adapter prompt string -- zero hits in any
    # on-disk .json/state file. This proves both decisions now land in the
    # SAME real, already-existing on-disk audit record every other resolver
    # decision (route_info["agent"]) already uses:
    # .dv-harness/react/<node>/iteration_NNN.json -- via ReactRecorder.record()'s
    # `action` dict, at the SAME call site, no new persistence mechanism.
    from dv_harness.engine import DVHarness

    tmp = _mk_project_with_graph_and_agents()
    try:
        h = DVHarness(tmp)
        # Same real INTAKE-shaped "project" Blackboard record the sibling
        # environment-mode test above writes -- without it,
        # resolve_environment_mode() has no requested_subsystems and
        # legitimately returns environment_mode=None (a different, already
        # separately-tested real decision), which would make this
        # persistence assertion ambiguous.
        h.blackboard.write("project", {"protocols": ["usb"], "selected_subsystems": ["usb"]},
                            source="INTAKE")
        adapter = _CapturingAdapter()
        h.adapter = adapter
        h.set_stage("DISCOVERY")
        h.run_stage("investigate a USB3 link training failure")

        react_file = tmp / ".dv-harness" / "react" / "DISCOVERY" / "iteration_001.json"
        assert react_file.exists(), "run_stage() must persist a ReactRecorder record for this attempt"
        record = json.loads(react_file.read_text(encoding="utf-8"))
        action = record["action"]

        # The pre-existing, already-real field this fix sits alongside.
        assert action["agent"], action
        # NEWLY persisted: route (the comparable half-persisted decision the
        # investigation found) and both fully-unpersisted resolver decisions.
        assert action["route"] == "analysis-route"  # DISCOVERY node's real route, main_graph.json
        assert action["protocol_decision"]["protocol"] == "usb"
        assert action["environment_mode_decision"]["environment_mode"] == "SUBSYSTEM_MODE"

        # And it is genuinely auditable after the fact -- not just present at
        # write time -- by re-reading the file independently of `h`.
        reread = json.loads(react_file.read_text(encoding="utf-8"))
        assert reread["action"]["protocol_decision"]["protocol"] == "usb"
    finally:
        shutil.rmtree(tmp)


def test_project_model_stage_passes_and_dashboard_now_reads_a_real_environment_mode_selection():
    from dv_harness.engine import DVHarness
    from dv_harness.dashboard import _environment_mode_selected

    tmp = _mk_project_with_graph_and_agents()
    try:
        gate_dir = tmp / "tools" / "verification_flow"
        gate_dir.mkdir(parents=True)
        shutil.copy(ROOT / "tools" / "verification_flow" / "project_model_topology_completeness_gate.py",
                    gate_dir / "project_model_topology_completeness_gate.py")
        shutil.copy(ROOT / "tools" / "verification_flow" / "environment_mode_selection_gate.py",
                    gate_dir / "environment_mode_selection_gate.py")

        h = DVHarness(tmp)
        h.blackboard.write("project", {"protocols": ["usb"], "selected_subsystems": []}, source="INTAKE")
        h.set_stage("PROJECT_MODEL")

        # Before this task: dashboard._environment_mode_selected() always
        # returned None on a real project -- confirmed here BEFORE the stage
        # runs, so the assertion below is a genuine before/after proof, not
        # a tautology.
        assert _environment_mode_selected(tmp) is None

        topology = {"verification_boundary": "top.usb_dev",
                    "vip_topology": [{"vip_id": "usb_vip", "bound_interface": "usb_if0"}],
                    "blocks": [{"block_id": "b1", "branch": "BLOCK"}],
                    "model_confidence": "HIGH", "confidence_basis": "x",
                    "dv_readiness": "READY", "dv_readiness_basis": "x",
                    "architecture_evidence_db_ref": "db1"}
        env_mode = {"environment_mode": "SUBSYSTEM_MODE", "requested_subsystems": ["usb"]}
        text = (
            f"```dv-harness-evidence:project_model_topology_completeness_gate\n{json.dumps(topology)}\n```\n"
            f"```dv-harness-evidence:environment_mode_selection\n{json.dumps(env_mode)}\n```\n"
        )

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PassAdapter()
        h.run_stage("build the USB subsystem environment")

        ss = h.state.stages["PROJECT_MODEL"]
        assert ss["status"] == "PASS"

        # THE GAP CLOSED: a real stage now emits a real environment_mode_
        # selection block that a real gate verified -- dashboard.py's scan
        # finds it.
        assert _environment_mode_selected(tmp) == "SUBSYSTEM_MODE"
    finally:
        shutil.rmtree(tmp)


# ---------------------------------------------------------------------------
# AI-mechanism re-audit gap #4 ("Route & Skill Resolver"), closed 2026-09-04.
#
# The gap the audit named precisely: resolve_protocol() fired on real per-run
# evidence and its answer was faithfully persisted, but route_info["skills"] /
# resolved_skills / the delegated task's skills were computed from node.skills
# alone and came back BYTE-FOR-BYTE IDENTICAL for two different evidence sets
# against the same graph node. Every assertion below fails on the pre-fix code
# -- that is what makes them a regression test for the wiring rather than yet
# another test that resolve_protocol() works in isolation.
# ---------------------------------------------------------------------------

def _seed_failing_test(h, testcase_id: str) -> None:
    """Writes the REAL blackboard record engine._protocol_router_evidence()
    reads for failing_test_name: the "verification_state" topic's results[]
    (same shape engine._bb_verify() writes). Deliberately used instead of the
    user_goal so the evidence under test is a genuine mid-run signal, not the
    prompt text -- this is the audit's own proposed crux case."""
    h.blackboard.write("verification_state",
                       {"simulation_passed": False,
                        "results": [{"testcase_id": testcase_id, "result": "FAIL"}]},
                       source="VERIFY")


def _tasks(tmp: Path):
    return json.loads((tmp / ".dv-harness" / "agents" / "tasks.json").read_text(encoding="utf-8"))


def test_same_node_two_evidence_sets_produce_different_delegated_skills():
    from dv_harness.engine import DVHarness

    observed = {}
    for testcase_id, protocol in [("test_usb3_enum", "usb"), ("test_pcie_link_train", "pcie")]:
        tmp = _mk_project_with_graph_and_agents()
        _add_real_registry_and_protocol_skills(tmp)
        try:
            h = DVHarness(tmp)
            _seed_failing_test(h, testcase_id)
            h.adapter = _CapturingAdapter()
            h.set_stage("DISCOVERY")
            # Deliberately protocol-free user_goal: the ONLY protocol signal
            # in this run is the failing test name seeded above.
            h.run_stage("continue the current investigation")

            tasks = _tasks(tmp)
            assert tasks, "run_stage() must delegate a real AgentTaskStore task"
            task = tasks[0]
            react = json.loads((tmp / ".dv-harness" / "react" / "DISCOVERY"
                                / "iteration_001.json").read_text(encoding="utf-8"))
            observed[protocol] = {
                "task_skills": task["skills"],
                "react_skills": react["action"]["skills"],
                "static_skills": react["action"]["static_skills"],
                "protocol_routes": react["action"]["protocol_skill_routes"],
                "decided": react["action"]["protocol_decision"]["protocol"],
                "prompt": h.adapter.prompts[0],
            }
        finally:
            shutil.rmtree(tmp)

    usb, pcie = observed["usb"], observed["pcie"]

    # The dynamic decision itself differs (this part already worked pre-fix).
    assert usb["decided"] == "usb" and pcie["decided"] == "pcie"

    # THE GAP: the SAME graph node's static skills are identical...
    assert usb["static_skills"] == pcie["static_skills"] == [
        "subsystem-to-soc-verification", "protocol-router"]
    # ...but the skills actually DELEGATED are now genuinely different.
    assert usb["task_skills"] != pcie["task_skills"]
    assert usb["react_skills"] == usb["task_skills"]
    assert pcie["react_skills"] == pcie["task_skills"]

    # And different in the specific, registry-backed way SKILL.md's
    # "Profile/VIP-Lookup Binding" section prescribes -- USB has both a
    # profile_skill and a vip_lookup_skill in the real registry, PCIe only a
    # profile_skill, so USB legitimately gains one more skill than PCIe.
    assert usb["task_skills"] == usb["static_skills"] + ["usb-profile", "usb-vip-lookup"]
    assert pcie["task_skills"] == pcie["static_skills"] + ["pcie-profile"]
    assert usb["protocol_routes"] == ["USB/usb-profile", "USB/usb-vip-lookup"]
    assert pcie["protocol_routes"] == ["PCIe/pcie-profile"]

    # The prompt the adapter actually received carries the resolved paths --
    # so the agent is handed the skills, not merely told a protocol name.
    assert "usb-profile" in usb["prompt"] and "usb-vip-lookup" in usb["prompt"]
    assert "usb-profile" not in pcie["prompt"]
    assert "pcie-profile" in pcie["prompt"]


def test_resolved_protocol_skills_are_real_resolvable_paths_not_just_names():
    """SkillResolver runs over the WIDENED list, so the folded-in protocol
    skills come back with real found=True paths -- proving the fold-in happens
    before path resolution, not after it."""
    from dv_harness.engine import DVHarness

    tmp = _mk_project_with_graph_and_agents()
    _add_real_registry_and_protocol_skills(tmp)
    try:
        h = DVHarness(tmp)
        _seed_failing_test(h, "test_usb3_enum")
        h.adapter = _CapturingAdapter()
        h.set_stage("DISCOVERY")
        h.run_stage("continue the current investigation")
        prompt = h.adapter.prompts[0]
        assert '{"skill": "usb-profile", "path": ' in prompt, prompt
        assert '"found": true' in prompt
        # The path is the real on-disk location, not a fabricated string.
        assert (tmp / ".claude" / "skills" / "USB" / "usb-profile" / "SKILL.md").exists()
    finally:
        shutil.rmtree(tmp)


def test_non_protocol_sensitive_node_keeps_its_static_skills_unchanged():
    """The fold-in is scoped to nodes that declared the `protocol-router`
    skill. A node that did not (GIT_SYNC) must be untouched even when the
    run's protocol resolves -- otherwise this would be noise injection, not
    routing."""
    from dv_harness.engine import DVHarness

    tmp = _mk_project_with_graph_and_agents()
    _add_real_registry_and_protocol_skills(tmp)
    try:
        h = DVHarness(tmp)
        h.adapter = _CapturingAdapter()
        h.set_stage("GIT_SYNC")
        h.run_stage("investigate a USB3 link training failure")
        react = json.loads((tmp / ".dv-harness" / "react" / "GIT_SYNC"
                            / "iteration_001.json").read_text(encoding="utf-8"))
        action = react["action"]
        assert action["protocol_decision"]["protocol"] == "usb"   # decision still fires
        assert action["skills"] == action["static_skills"] == ["git-pull-sync", "git-workflow"]
        assert action["protocol_skill_routes"] == []
        assert _tasks(tmp)[0]["skills"] == ["git-pull-sync", "git-workflow"]
    finally:
        shutil.rmtree(tmp)


def test_unresolved_protocol_leaves_the_static_skill_list_untouched():
    """No fabricated widening when resolve_protocol() finds nothing -- an
    unresolved decision must leave the graph's own answer exactly as-is."""
    from dv_harness.engine import DVHarness

    tmp = _mk_project_with_graph_and_agents()
    _add_real_registry_and_protocol_skills(tmp)
    try:
        h = DVHarness(tmp)
        h.adapter = _CapturingAdapter()
        h.set_stage("DISCOVERY")
        h.run_stage("continue the current investigation")
        react = json.loads((tmp / ".dv-harness" / "react" / "DISCOVERY"
                            / "iteration_001.json").read_text(encoding="utf-8"))
        action = react["action"]
        assert action["protocol_decision"]["resolved"] is False
        assert action["skills"] == action["static_skills"]
        assert action["protocol_skill_routes"] == []
    finally:
        shutil.rmtree(tmp)
