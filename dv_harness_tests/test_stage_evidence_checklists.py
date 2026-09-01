"""Tests for the expected-evidence-checklist design pass (2026-09-01):
graph.Node.expected_evidence/expected_outputs, engine.build_stage_entry_checklist/
build_stage_exit_checklist, and their persistence into the same
StageExecutionProfiler telemetry record run_stage() already writes.

Per the audit this closes: main_graph.json's node schema previously had no
field declaring what evidence/files a stage requires at entry or should
produce at exit; STAGE_INSTRUCTIONS described "required_artifacts" only as
prose the agent self-reports, never a harness-computed, presence-checked
checklist. These tests verify the checklist is real (actually checks
Blackboard/filesystem/evidence-dict presence, never just echoes the
declaration back) and informational-only (never blocks/fails a stage).
"""
import json
import shutil
import tempfile
from pathlib import Path

from dv_harness.blackboard import Blackboard
from dv_harness.graph import GraphDefinition, Node
from dv_harness.engine import (
    DVHarness, build_stage_entry_checklist, build_stage_exit_checklist,
)
from dv_harness.stage_profile import StageExecutionProfiler
from dv_harness.models import Status
from dv_harness.adapters.base import AgentResult

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH = ROOT / ".dv-harness" / "graph" / "main_graph.json"


def _fresh_harness(with_graph=True):
    tmp = Path(tempfile.mkdtemp())
    if with_graph:
        (tmp / ".dv-harness" / "graph").mkdir(parents=True)
        (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
            REAL_GRAPH.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp, DVHarness(tmp)


# --- graph.Node schema: additive, backward-compatible --------------------

def test_node_without_expected_fields_defaults_to_empty_lists():
    n = Node(id="X", route="analysis-route", agent="analysis-agent")
    assert n.expected_evidence == []
    assert n.expected_outputs == []


def test_real_main_graph_declares_expected_fields_on_the_six_representative_stages():
    gd = GraphDefinition.load(REAL_GRAPH)
    for sid in ("INTAKE", "BUILD", "VERIFY", "REGRESSION", "COVERAGE_CLOSURE", "SIGNOFF"):
        node = gd.nodes[sid]
        assert node.expected_evidence, f"{sid} should declare expected_evidence"
        assert node.expected_outputs, f"{sid} should declare expected_outputs"
        for item in node.expected_evidence + node.expected_outputs:
            assert set(item.keys()) == {"item_id", "description", "kind"}
            assert item["kind"] in ("file_path", "blackboard_key", "evidence_field")
    # A node that never opted in stays completely untouched (backward compat).
    assert gd.nodes["DISCOVERY"].expected_evidence == []
    assert gd.nodes["DISCOVERY"].expected_outputs == []


# --- build_stage_entry_checklist / build_stage_exit_checklist: unit level -

def test_entry_checklist_zero_items_declared_is_100_percent_and_empty():
    tmp = Path(tempfile.mkdtemp())
    try:
        bb = Blackboard(tmp)
        node = Node(id="X", route="analysis-route", agent="analysis-agent")
        report = build_stage_entry_checklist(node, bb, tmp)
        assert report == {
            "items": [], "present_count": 0, "total_count": 0,
            "completeness_percent": 100.0, "missing_item_ids": [],
        }
    finally:
        shutil.rmtree(tmp)


def test_entry_checklist_none_node_is_also_zero_items():
    # run_stage() calls this with node=None whenever the current stage has no
    # graph node resolved (e.g. no main_graph.json) -- must never raise.
    tmp = Path(tempfile.mkdtemp())
    try:
        bb = Blackboard(tmp)
        report = build_stage_entry_checklist(None, bb, tmp)
        assert report["total_count"] == 0
        assert report["completeness_percent"] == 100.0
    finally:
        shutil.rmtree(tmp)


def test_entry_checklist_detects_blackboard_key_and_file_path_presence():
    tmp = Path(tempfile.mkdtemp())
    try:
        bb = Blackboard(tmp)
        bb.write("environment", {"execution_mode": "PURE_LOCAL_READ_ANALYSIS"}, source="ENV_CHECK")
        (tmp / "command.txt").write_text("some scenario", encoding="utf-8")
        node = Node(id="X", route="analysis-route", agent="analysis-agent", expected_evidence=[
            {"item_id": "environment", "description": "written", "kind": "blackboard_key"},
            {"item_id": "missing_topic", "description": "never written", "kind": "blackboard_key"},
            {"item_id": "command.txt", "description": "exists", "kind": "file_path"},
            {"item_id": "no_such_file.txt", "description": "absent", "kind": "file_path"},
        ])
        report = build_stage_entry_checklist(node, bb, tmp)
        by_id = {it["item_id"]: it["present"] for it in report["items"]}
        assert by_id == {
            "environment": True, "missing_topic": False,
            "command.txt": True, "no_such_file.txt": False,
        }
        assert report["present_count"] == 2
        assert report["total_count"] == 4
        assert report["completeness_percent"] == 50.0
        assert sorted(report["missing_item_ids"]) == ["missing_topic", "no_such_file.txt"]
    finally:
        shutil.rmtree(tmp)


def test_entry_checklist_evidence_field_reads_prior_attempt_and_supports_cross_stage_prefix():
    tmp = Path(tempfile.mkdtemp())
    try:
        bb = Blackboard(tmp)
        node = Node(id="REGRESSION", route="regression-route", agent="regression-agent", expected_evidence=[
            {"item_id": "regression_submission_policy_gate.jobs", "description": "own last attempt",
             "kind": "evidence_field"},
            {"item_id": "REGRESSION_SELECT:regression_selection_completeness_gate.targeted_tests",
             "description": "upstream stage's last submission", "kind": "evidence_field"},
            {"item_id": "REGRESSION_SELECT:regression_selection_completeness_gate.missing_field",
             "description": "field never supplied", "kind": "evidence_field"},
            {"item_id": "UNKNOWN_STAGE:whatever.field", "description": "a stage that never ran",
             "kind": "evidence_field"},
        ])
        stage_history = {
            "REGRESSION": {"last_evidence_blocks": {}},
            "REGRESSION_SELECT": {"last_evidence_blocks": {
                "regression_selection_completeness_gate": {"targeted_tests": ["t1", "t2"]},
            }},
        }
        report = build_stage_entry_checklist(node, bb, tmp, stage_history=stage_history)
        by_id = {it["item_id"]: it["present"] for it in report["items"]}
        assert by_id["regression_submission_policy_gate.jobs"] is False  # this stage never submitted yet
        assert by_id["REGRESSION_SELECT:regression_selection_completeness_gate.targeted_tests"] is True
        assert by_id["REGRESSION_SELECT:regression_selection_completeness_gate.missing_field"] is False
        assert by_id["UNKNOWN_STAGE:whatever.field"] is False  # stage never ran -- no KeyError
    finally:
        shutil.rmtree(tmp)


def test_exit_checklist_reads_this_attempts_own_evidence_blocks_and_ignores_stage_prefix():
    tmp = Path(tempfile.mkdtemp())
    try:
        bb = Blackboard(tmp)
        node = Node(id="VERIFY", route="build-route", agent="build-agent", expected_outputs=[
            {"item_id": "simulation_semantic_validation_gate", "description": "block present",
             "kind": "evidence_field"},
            {"item_id": "simulation_semantic_validation_gate.simulation_passed",
             "description": "field true", "kind": "evidence_field"},
            {"item_id": "false_pass_resistance_gate.oracle_independent",
             "description": "not produced this attempt", "kind": "evidence_field"},
            # A "STAGE_ID:" prefix on an expected_outputs item is documented
            # to be ignored -- only the dotted field path after it matters,
            # resolved against THIS attempt's own evidence_blocks.
            {"item_id": "SOME_OTHER_STAGE:simulation_semantic_validation_gate.simulation_passed",
             "description": "prefix ignored at exit", "kind": "evidence_field"},
        ])
        evidence_blocks = {
            "simulation_semantic_validation_gate": {"simulation_passed": True, "sim_log": "..."},
        }
        report = build_stage_exit_checklist(node, bb, tmp, evidence_blocks=evidence_blocks)
        by_id = {it["item_id"]: it["present"] for it in report["items"]}
        assert by_id["simulation_semantic_validation_gate"] is True
        assert by_id["simulation_semantic_validation_gate.simulation_passed"] is True
        assert by_id["false_pass_resistance_gate.oracle_independent"] is False
        assert by_id["SOME_OTHER_STAGE:simulation_semantic_validation_gate.simulation_passed"] is True
        assert report["present_count"] == 3
        assert report["total_count"] == 4
        assert report["completeness_percent"] == 75.0
    finally:
        shutil.rmtree(tmp)


def test_checklist_treats_falsy_required_artifact_value_as_absent_not_present():
    # A required_artifacts.<x>: false means the agent itself reported that
    # artifact as NOT confirmed present -- the checklist must report the item
    # absent, not "present because the key exists".
    tmp = Path(tempfile.mkdtemp())
    try:
        bb = Blackboard(tmp)
        node = Node(id="INTAKE", route="analysis-route", agent="analysis-agent", expected_outputs=[
            {"item_id": "intake_readiness.required_artifacts.dut_design_spec",
             "description": "confirmed present", "kind": "evidence_field"},
        ])
        evidence_blocks = {"intake_readiness": {"required_artifacts": {"dut_design_spec": False}}}
        report = build_stage_exit_checklist(node, bb, tmp, evidence_blocks=evidence_blocks)
        assert report["items"][0]["present"] is False
        assert report["missing_item_ids"] == ["intake_readiness.required_artifacts.dut_design_spec"]
    finally:
        shutil.rmtree(tmp)


def test_unknown_kind_reports_absent_and_never_raises():
    tmp = Path(tempfile.mkdtemp())
    try:
        bb = Blackboard(tmp)
        node = Node(id="X", route="analysis-route", agent="analysis-agent", expected_evidence=[
            {"item_id": "whatever", "description": "unsupported kind", "kind": "carrier_pigeon"},
        ])
        report = build_stage_entry_checklist(node, bb, tmp)
        assert report["items"][0]["present"] is False
        assert report["completeness_percent"] == 0.0
    finally:
        shutil.rmtree(tmp)


# --- StageExecutionProfiler: entry_checklist/exit_checklist round-trip ----

def test_profiler_begin_end_stage_round_trips_checklists_into_the_persisted_file():
    tmp = Path(tempfile.mkdtemp())
    try:
        profiler = StageExecutionProfiler(tmp)
        entry = {"items": [{"item_id": "a", "description": "d", "present": True}],
                 "present_count": 1, "total_count": 1, "completeness_percent": 100.0,
                 "missing_item_ids": []}
        rec = profiler.begin_stage("S1", "S1", entry_checklist=entry)
        assert rec["entry_checklist"] == entry
        assert rec["exit_checklist"] is None

        on_disk_mid = json.loads((tmp / ".dv-harness" / "telemetry" / "stages" /
                                   f"{rec['profile_id']}.json").read_text(encoding="utf-8"))
        assert on_disk_mid["entry_checklist"] == entry

        exit_report = {"items": [{"item_id": "b", "description": "d2", "present": False}],
                       "present_count": 0, "total_count": 1, "completeness_percent": 0.0,
                       "missing_item_ids": ["b"]}
        ended = profiler.end_stage(rec["profile_id"], status="PASS", exit_checklist=exit_report)
        assert ended["entry_checklist"] == entry
        assert ended["exit_checklist"] == exit_report

        on_disk_final = json.loads((tmp / ".dv-harness" / "telemetry" / "stages" /
                                     f"{rec['profile_id']}.json").read_text(encoding="utf-8"))
        assert on_disk_final["entry_checklist"] == entry
        assert on_disk_final["exit_checklist"] == exit_report
    finally:
        shutil.rmtree(tmp)


def test_profiler_omitting_checklists_stays_byte_compatible_with_pre_existing_callers():
    tmp = Path(tempfile.mkdtemp())
    try:
        profiler = StageExecutionProfiler(tmp)
        rec = profiler.begin_stage("S1", "S1")
        assert rec["entry_checklist"] is None
        ended = profiler.end_stage(rec["profile_id"], status="PASS")
        assert ended["exit_checklist"] is None
    finally:
        shutil.rmtree(tmp)


# --- Integration: run_stage() wires both checklists into the SAME record --

def test_run_stage_persists_entry_and_exit_checklists_into_the_same_stage_telemetry_record():
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False  # NO_GATE_REQUIRED -> PASS
        h.set_stage("INTAKE")
        payload = {
            "mode": "SUBSYSTEM", "target_name": "usb", "protocols": ["USB"],
            "required_artifacts": {
                "protocol_spec": True, "dut_design_spec": False,
                "rtl_top_or_interface_files": True,
            },
        }
        text = f"```dv-harness-evidence:intake_readiness\n{json.dumps(payload)}\n```"

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id="s1")

        h.adapter = _PassAdapter()
        h.run_stage("goal")
        assert h.state.stages["INTAKE"]["status"] == Status.PASS.value

        stage_dir = tmp / ".dv-harness" / "telemetry" / "stages"
        files = list(stage_dir.glob("STAGE-*.json"))
        assert len(files) == 1
        rec = json.loads(files[0].read_text(encoding="utf-8"))

        entry = rec["entry_checklist"]
        assert entry is not None
        assert entry["total_count"] == 1  # INTAKE's one expected_evidence item ("environment")
        assert entry["present_count"] == 0  # ENV_CHECK never ran in this test -- genuinely absent
        assert entry["missing_item_ids"] == ["environment"]

        exit_ck = rec["exit_checklist"]
        assert exit_ck is not None
        assert exit_ck["total_count"] == 7  # INTAKE's expected_outputs item count
        missing = set(exit_ck["missing_item_ids"])
        assert missing == {"intake_readiness.required_artifacts.dut_design_spec"}
        assert exit_ck["present_count"] == 6

        # The stage's own last-submitted evidence is persisted for a future
        # entry checklist (e.g. a retry, or a downstream stage referencing it
        # via "INTAKE:...").
        assert h.state.stages["INTAKE"]["last_evidence_blocks"]["intake_readiness"]["target_name"] == "usb"
    finally:
        shutil.rmtree(tmp)


def test_run_stage_checklist_is_informational_only_and_does_not_block_a_partial_stage():
    # Missing expected_outputs items must never themselves cause a PARTIAL/
    # FAIL -- only the real gate verdict (or its absence) governs ss["status"].
    # Here the gate evidence is genuinely incomplete (missing required
    # fences), so VERIFY legitimately goes PARTIAL -- the checklist just
    # reports the same gap descriptively, it does not additionally block.
    tmp, h = _fresh_harness()
    try:
        h.set_stage("VERIFY")

        class _IncompleteAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="no evidence fences at all", raw={}, session_id="s1")

        h.adapter = _IncompleteAdapter()
        h.run_stage("goal")
        assert h.state.stages["VERIFY"]["status"] in (Status.PARTIAL.value, Status.FAIL.value)

        stage_dir = tmp / ".dv-harness" / "telemetry" / "stages"
        rec = json.loads(next(stage_dir.glob("STAGE-*.json")).read_text(encoding="utf-8"))
        exit_ck = rec["exit_checklist"]
        assert exit_ck is not None
        assert exit_ck["present_count"] == 0
        assert exit_ck["total_count"] == 5
    finally:
        shutil.rmtree(tmp)


def test_node_without_expected_evidence_produces_null_checklists_in_telemetry():
    # DISCOVERY never opted in -- run_stage() must still call both checklist
    # functions (they always run), just get back the trivial zero-item shape,
    # never a crash and never a non-empty fabricated report.
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("DISCOVERY")

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="ok", raw={}, session_id="s1")

        h.adapter = _PassAdapter()
        h.run_stage("goal")

        stage_dir = tmp / ".dv-harness" / "telemetry" / "stages"
        rec = json.loads(next(stage_dir.glob("STAGE-*.json")).read_text(encoding="utf-8"))
        assert rec["entry_checklist"] == {
            "items": [], "present_count": 0, "total_count": 0,
            "completeness_percent": 100.0, "missing_item_ids": [],
        }
        assert rec["exit_checklist"] == rec["entry_checklist"]
    finally:
        shutil.rmtree(tmp)
