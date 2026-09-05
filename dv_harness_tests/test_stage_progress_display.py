"""Tests for the stage-progress display (2026-09-04, stage-progress-display
gap-close): the ASCII-art banner, the required-input / produced-output
checklists with a real completeness %, the "please provide more detail on X"
reminder, the time+token summary including every sub-agent run, and the
persisted markdown reports -- plus the real run_stage() wiring that emits and
saves both at every real stage boundary.

The bar these tests hold the feature to, per the spec they close:
  - the checklists must come from REAL declarations (gates.STAGE_GATES, the
    graph node's own blackboard_read/blackboard_write/expected_evidence/
    expected_outputs), never an invented parallel list -- so a test asserts
    the item ids really do equal those sources' own contents;
  - the completeness % must be internally consistent with the checklist's own
    item count (a percentage that does not match the [x]/[ ] lines beside it
    is worse than no percentage);
  - the saved report's content must match what was printed;
  - the display must be informational only -- it can never fail a stage.
"""
import json
import re
import shutil
import tempfile
from pathlib import Path

from dv_harness import stage_progress_display as spd
from dv_harness.adapters.base import AgentResult
from dv_harness.blackboard import Blackboard
from dv_harness.engine import DVHarness
from dv_harness.gates import INTAKE_FIELD_QUESTIONS, STAGE_GATES
from dv_harness.graph import GraphDefinition, Node
from dv_harness.models import Status
from dv_harness.stage_profile import StageExecutionProfiler
from dv_harness.stage_profile_report import (
    render_stage_time_and_tokens, stage_time_and_token_summary,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH = ROOT / ".dv-harness" / "graph" / "main_graph.json"

# The report's own fences are FOUR backticks, because the checklist text it
# embeds names the three-backtick evidence fences it is asking the agent for.
# These readers deliberately match that exact contract, so a regression back
# to three-backtick fences fails a test rather than silently producing a
# report whose JSON block cannot be parsed.
_DISPLAY_RE = re.compile(r"````text\n(.*?)\n````", re.S)
_PAYLOAD_RE = re.compile(r"````json\n(.*?)````", re.S)


def _display_of(path: Path) -> str:
    return _DISPLAY_RE.search(path.read_text(encoding="utf-8")).group(1)


def _payload_of(path: Path) -> dict:
    return json.loads(_PAYLOAD_RE.search(path.read_text(encoding="utf-8")).group(1))


def _ids_by_source(report):
    """Item ids contributed by one declaration source. An item named by more
    than one real declaration is merged into a single checklist line carrying
    every source that asked for it (see spd._dedupe), so membership is tested
    against that `sources` list, not against a single source string."""
    def _for(source):
        return {it["item_id"] for it in report["items"] if source in it["sources"]}
    return _for


def _fresh_harness():
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        REAL_GRAPH.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp, DVHarness(tmp)


# --- the banner ------------------------------------------------------------

def test_banner_is_real_ascii_art_not_a_text_line():
    banner = spd.render_banner("INTAKE", "START", timestamp="2026-09-04T00:00:00+00:00")
    lines = banner.splitlines()
    # Multi-line, framed, and carrying a genuine block-letter wordmark -- the
    # user's clarification was "Logo 指的是文字/ASCII art", so a one-line
    # string would not satisfy this requirement no matter what it said.
    assert len(lines) >= 8
    assert lines[0] == spd.BANNER_FILL * spd.WIDTH
    assert lines[-1] == spd.BANNER_FILL * spd.WIDTH
    # Every framed row is exactly the same width -- misaligned ASCII art
    # reads as broken output rather than as a deliberate banner.
    assert {len(ln) for ln in lines} == {spd.WIDTH}
    # The wordmark really is drawn from block glyphs, not spelled in letters.
    art_rows = spd._wordmark_rows()
    assert len({len(r) for r in art_rows}) == 1
    assert all(set(r) <= {"#", " "} for r in art_rows)
    assert any(row.strip() in banner for row in art_rows)
    assert "STAGE START" in banner and "INTAKE" in banner


def test_banner_is_pure_ascii_so_a_windows_console_can_print_it():
    # A box-drawing banner raises UnicodeEncodeError on a cp950/cp437 console,
    # which would turn an observability feature into a crash on this
    # project's primary platform.
    for phase in ("START", "DONE"):
        banner = spd.render_banner("REQUIREMENTS_TRACEABILITY", phase)
        banner.encode("ascii")
        banner.encode("cp950")


def test_banner_is_parameterized_by_stage_and_phase():
    a = spd.render_banner("INTAKE", "START", timestamp="T")
    b = spd.render_banner("SIGNOFF", "DONE", timestamp="T")
    assert a != b
    assert "SIGNOFF" in b and "STAGE DONE" in b
    assert "INTAKE" not in b


# --- checklists come from real declarations --------------------------------

def test_input_checklist_items_are_exactly_the_real_declared_sources():
    tmp, h = _fresh_harness()
    try:
        gd = GraphDefinition.load(REAL_GRAPH)
        node = gd.nodes["INTAKE"]
        report = spd.build_stage_input_checklist(tmp, "INTAKE", node, h.blackboard,
                                                  stage_history={})
        ids_for = _ids_by_source(report)
        # Sourced from the graph node's own real fields...
        assert ids_for(spd.SOURCE_BLACKBOARD_READ) == set(node.blackboard_read)
        assert ids_for(spd.SOURCE_EXPECTED_EVIDENCE) == \
            {d["item_id"] for d in node.expected_evidence}
        # ...and from gates.py's own real STAGE_GATES registry, not a copy.
        assert ids_for(spd.SOURCE_STAGE_GATES) == {g[0] for g in STAGE_GATES["INTAKE"]}
        # Nothing appears that no real declaration asked for.
        declared = (set(node.blackboard_read)
                    | {d["item_id"] for d in node.expected_evidence}
                    | {g[0] for g in STAGE_GATES["INTAKE"]})
        assert {it["item_id"] for it in report["items"]} == declared
    finally:
        shutil.rmtree(tmp)


def test_output_checklist_items_are_exactly_the_real_declared_sources():
    tmp, h = _fresh_harness()
    try:
        gd = GraphDefinition.load(REAL_GRAPH)
        node = gd.nodes["INTAKE"]
        report = spd.build_stage_output_checklist(tmp, "INTAKE", node, h.blackboard,
                                                   evidence_blocks={})
        ids_for = _ids_by_source(report)
        assert ids_for(spd.SOURCE_BLACKBOARD_WRITE) == set(node.blackboard_write)
        assert ids_for(spd.SOURCE_EXPECTED_OUTPUTS) == \
            {d["item_id"] for d in node.expected_outputs}
        assert ids_for(spd.SOURCE_STAGE_GATES) == {g[0] for g in STAGE_GATES["INTAKE"]}
    finally:
        shutil.rmtree(tmp)


def test_checklist_presence_is_really_checked_not_echoed_back():
    tmp, h = _fresh_harness()
    try:
        node = Node(id="X", route="analysis-route", agent="a",
                    blackboard_read=["written_topic", "never_written_topic"])
        h.blackboard.write("written_topic", {"v": 1}, source="test")
        report = spd.build_stage_input_checklist(tmp, "X", node, h.blackboard, stage_history={})
        present = {it["item_id"]: it["present"] for it in report["items"]}
        assert present == {"written_topic": True, "never_written_topic": False}
        assert report["present_count"] == 1 and report["total_count"] == 2
        assert report["completeness_percent"] == 50.0
        assert report["missing_item_ids"] == ["never_written_topic"]
    finally:
        shutil.rmtree(tmp)


def test_gate_evidence_items_track_what_was_actually_submitted():
    tmp, h = _fresh_harness()
    try:
        gd = GraphDefinition.load(REAL_GRAPH)
        node = gd.nodes["ARCH_CALIBRATION"]  # 3 real gates
        gate_ids = [g[0] for g in STAGE_GATES["ARCH_CALIBRATION"]]
        assert len(gate_ids) == 3
        history = {"ARCH_CALIBRATION": {"last_evidence_blocks": {gate_ids[0]: {"a": 1}}}}
        report = spd.build_stage_input_checklist(tmp, "ARCH_CALIBRATION", node,
                                                  h.blackboard, stage_history=history)
        gate_items = [it for it in report["items"] if it["source"] == spd.SOURCE_STAGE_GATES]
        assert [it["present"] for it in gate_items] == [True, False, False]
    finally:
        shutil.rmtree(tmp)


def test_one_artifact_named_by_two_declarations_is_counted_once():
    # REGRESSION (found by a real end-to-end run, 2026-09-04): INTAKE's
    # expected_evidence entry IS its blackboard_read topic 'environment'
    # restated, and its expected_outputs entry 'intake_readiness' IS the
    # STAGE_GATES gate id. Counting each twice inflated the denominator (a
    # 6-item INTAKE input checklist that really has 5 distinct requirements)
    # and printed the same "please provide more detail" line twice.
    tmp, h = _fresh_harness()
    try:
        gd = GraphDefinition.load(REAL_GRAPH)
        node = gd.nodes["INTAKE"]
        assert "environment" in node.blackboard_read
        assert "environment" in [d["item_id"] for d in node.expected_evidence]

        report = spd.build_stage_input_checklist(tmp, "INTAKE", node, h.blackboard,
                                                  stage_history={})
        ids = [it["item_id"] for it in report["items"]]
        assert len(ids) == len(set(ids))
        env = next(it for it in report["items"] if it["item_id"] == "environment")
        # Nothing is lost by merging -- both declarations are recorded.
        assert env["sources"] == [spd.SOURCE_BLACKBOARD_READ, spd.SOURCE_EXPECTED_EVIDENCE]

        # ...and the reminder therefore asks for it exactly once.
        requests = spd.build_detail_requests(tmp, "INTAKE", report, graph=gd)
        assert sum(1 for ln in requests if ln.startswith("environment:")) == 1
    finally:
        shutil.rmtree(tmp)


def test_merged_item_is_present_when_any_declaration_finds_it():
    tmp, h = _fresh_harness()
    try:
        gd = GraphDefinition.load(REAL_GRAPH)
        node = gd.nodes["INTAKE"]
        h.blackboard.write("environment", {"ok": True}, source="test")
        report = spd.build_stage_input_checklist(tmp, "INTAKE", node, h.blackboard,
                                                  stage_history={})
        env = next(it for it in report["items"] if it["item_id"] == "environment")
        assert env["present"] is True
    finally:
        shutil.rmtree(tmp)


def test_completeness_percent_always_matches_the_checklists_own_item_count():
    # Requirement: the number printed beside the [x]/[ ] lines must be
    # derivable from those exact lines, for every checklist the real graph
    # can produce -- not an independently-tracked counter that can drift.
    tmp, h = _fresh_harness()
    try:
        gd = GraphDefinition.load(REAL_GRAPH)
        h.blackboard.write("environment", {"ok": True}, source="test")
        for stage, node in gd.nodes.items():
            for report in (
                spd.build_stage_input_checklist(tmp, stage, node, h.blackboard,
                                                 stage_history=h.state.stages),
                spd.build_stage_output_checklist(tmp, stage, node, h.blackboard,
                                                  evidence_blocks={}),
            ):
                items = report["items"]
                assert report["total_count"] == len(items)
                assert report["present_count"] == sum(1 for it in items if it["present"])
                assert report["missing_item_ids"] == \
                    [it["item_id"] for it in items if not it["present"]]
                expected = (100.0 * report["present_count"] / len(items)) if items else 100.0
                assert abs(report["completeness_percent"] - expected) < 1e-9
    finally:
        shutil.rmtree(tmp)


def test_zero_item_checklist_reports_100_percent_not_zero():
    tmp, h = _fresh_harness()
    try:
        node = Node(id="DISCOVERY", route="analysis-route", agent="a")  # no gates, no decls
        report = spd.build_stage_input_checklist(tmp, "NO_SUCH_STAGE", node, h.blackboard,
                                                  stage_history={})
        assert report["total_count"] == 0
        assert report["completeness_percent"] == 100.0
    finally:
        shutil.rmtree(tmp)


# --- the "please provide more detail on X" reminder ------------------------

def test_detail_requests_name_every_missing_item_and_reuse_the_real_questions():
    tmp, h = _fresh_harness()
    try:
        gd = GraphDefinition.load(REAL_GRAPH)
        node = gd.nodes["INTAKE"]
        report = spd.build_stage_input_checklist(tmp, "INTAKE", node, h.blackboard,
                                                  stage_history={})
        requests = spd.build_detail_requests(tmp, "INTAKE", report, graph=gd)
        # One line per missing item, each naming that item.
        assert len(requests) == len(report["missing_item_ids"])
        for item_id in report["missing_item_ids"]:
            assert any(str(item_id) in line for line in requests)
        # A missing blackboard input names the upstream stage that really
        # produces it, read off the graph's own blackboard_write.
        env_line = next(ln for ln in requests if ln.startswith("environment:"))
        assert "ENV_CHECK" in env_line
    finally:
        shutil.rmtree(tmp)


def test_detail_requests_promote_gate_reported_fields_to_their_real_questions():
    tmp, h = _fresh_harness()
    try:
        empty = {"items": [], "present_count": 0, "total_count": 0,
                 "completeness_percent": 100.0, "missing_item_ids": []}
        reasons = ["intake_readiness: missing required fields: dut_design_spec, clock_reset_spec"]
        requests = spd.build_detail_requests(tmp, "INTAKE", empty, gate_reasons=reasons)
        # The wording is gates.INTAKE_FIELD_QUESTIONS verbatim -- reused, not
        # a second paraphrase of the same ask.
        assert f"dut_design_spec: {INTAKE_FIELD_QUESTIONS['dut_design_spec']}" in requests
        assert f"clock_reset_spec: {INTAKE_FIELD_QUESTIONS['clock_reset_spec']}" in requests
        # A field nobody mentioned is not invented into the reminder.
        assert not any(ln.startswith("phy_interface_spec:") for ln in requests)
    finally:
        shutil.rmtree(tmp)


# --- time + tokens, including sub-agents -----------------------------------

def test_time_and_token_summary_includes_every_sub_agent_run():
    tmp = Path(tempfile.mkdtemp())
    try:
        p = StageExecutionProfiler(tmp)
        rec = p.begin_stage("VERIFY", "VERIFY")
        # One main stage agent run, plus two sub-agent runs of the kind
        # react_loop._record_agent_run() makes for real.
        p.add_agent_run(rec["profile_id"], "verification-agent", 12.0,
                        usage={"input_tokens": 1000, "output_tokens": 200})
        p.add_agent_run(rec["profile_id"], "react-reflection", 3.0,
                        usage={"input_tokens": 300, "output_tokens": 50})
        p.add_agent_run(rec["profile_id"], "react-targeted-retry", 5.0,
                        usage={"input_tokens": 400, "output_tokens": 60})
        p.end_stage(rec["profile_id"], status="PASS")

        s = stage_time_and_token_summary(tmp, "VERIFY")
        assert s["attempts"] == 1
        latest = s["latest"]
        assert latest["agent_run_count"] == 3
        assert [a["agent"] for a in latest["agents"]] == \
            ["verification-agent", "react-reflection", "react-targeted-retry"]
        # Totals really are the sum over ALL agent runs, sub-agents included.
        assert latest["aggregate_agent_runtime_sec"] == 20.0
        assert latest["input_tokens"] == 1700
        assert latest["output_tokens"] == 310
        assert latest["total_tokens"] == 2010
        assert s["stage_totals"]["total_tokens"] == 2010
        assert s["stage_totals"]["agent_run_count"] == 3
        assert s["token_data_available"] is True

        text = render_stage_time_and_tokens(s)
        for agent in ("verification-agent", "react-reflection", "react-targeted-retry"):
            assert agent in text
        assert "ALL AGENTS RUNTIME (incl. sub-agents)" in text
        assert "STAGE TOKENS" in text
    finally:
        shutil.rmtree(tmp)


def test_every_section_rule_is_the_same_width_as_the_banner():
    # REGRESSION (2026-09-04): the time/token block lived in
    # stage_profile_report.py and built its own rule as
    # '-- EXECUTION TIME AND TOKENS ' + '-' * 50 == 79 chars, while every
    # checklist rule came from spd._rule() at 80 -- so the one section
    # rendered by the other module sat a character short of the banner above
    # it. Both now share section_rule(); this asserts they cannot drift again.
    tmp, h = _fresh_harness()
    try:
        p = StageExecutionProfiler(tmp)
        rec = p.begin_stage("INTAKE", "INTAKE")
        p.add_agent_run(rec["profile_id"], "analysis-agent", 2.0,
                        usage={"input_tokens": 10, "output_tokens": 5})
        p.end_stage(rec["profile_id"], status="PASS")

        gd = GraphDefinition.load(REAL_GRAPH)
        node = gd.nodes["INTAKE"]
        display = spd.render_stage_done_display(
            "INTAKE", "PASS", 100.0,
            spd.build_stage_output_checklist(tmp, "INTAKE", node, h.blackboard,
                                             evidence_blocks={}),
            stage_time_and_token_summary(tmp, "INTAKE"), outstanding=[])
        rules = [ln for ln in display.splitlines() if ln.startswith("-- ")]
        assert len(rules) == 3  # outputs, still-outstanding, time+tokens
        assert {len(ln) for ln in rules} == {spd.WIDTH}
        assert any("EXECUTION TIME AND TOKENS" in ln for ln in rules)
    finally:
        shutil.rmtree(tmp)


def test_time_and_token_summary_distinguishes_no_usage_from_zero_usage():
    tmp = Path(tempfile.mkdtemp())
    try:
        p = StageExecutionProfiler(tmp)
        rec = p.begin_stage("BUILD", "BUILD")
        p.add_agent_run(rec["profile_id"], "build-agent", 4.0, usage={})  # SDK adapter shape
        p.end_stage(rec["profile_id"], status="PASS")
        s = stage_time_and_token_summary(tmp, "BUILD")
        assert s["token_data_available"] is False
        assert s["latest"]["total_tokens"] is None
        assert "N/A" in render_stage_time_and_tokens(s)
    finally:
        shutil.rmtree(tmp)


def test_time_and_token_summary_handles_a_stage_that_never_ran():
    tmp = Path(tempfile.mkdtemp())
    try:
        s = stage_time_and_token_summary(tmp, "SIGNOFF")
        assert s["attempts"] == 0 and s["latest"] is None
        assert "no telemetry record" in render_stage_time_and_tokens(s)
    finally:
        shutil.rmtree(tmp)


# --- persisted reports -----------------------------------------------------

def test_saved_report_content_matches_what_was_displayed():
    tmp = Path(tempfile.mkdtemp())
    try:
        text = spd.render_banner("INTAKE", "START", timestamp="T") + "\n  [x] a\n  [ ] b"
        path = spd.save_stage_report(tmp, "INTAKE", "start", text,
                                     payload={"n": 1}, timestamp="2026-09-04T01:02:03+00:00")
        assert path.parent == tmp / ".dv-harness" / "stage_reports"
        assert path.name.startswith("INTAKE_start_")
        content = path.read_text(encoding="utf-8")
        # The exact displayed text is embedded verbatim -- the file and the
        # terminal cannot disagree, because there is only one rendered string.
        assert text in content
        assert content.startswith("# DV Agent Harness L5 -- stage START report: INTAKE")
        assert _payload_of(path) == {"n": 1}
        assert _display_of(path) == text
    finally:
        shutil.rmtree(tmp)


def test_report_fences_survive_the_evidence_fences_the_display_itself_names():
    # REGRESSION (found by a real test run, 2026-09-04): the checklist text
    # names the evidence fences it wants (```dv-harness-evidence:<gate_id>```),
    # so a three-backtick wrapper around it is closed early by its own
    # content -- the report renders as broken markdown and its JSON block is
    # unparseable. The wrapper must stay longer than anything it can contain.
    tmp, h = _fresh_harness()
    try:
        gd = GraphDefinition.load(REAL_GRAPH)
        checklist = spd.build_stage_input_checklist(tmp, "INTAKE", gd.nodes["INTAKE"],
                                                     h.blackboard, stage_history={})
        display = spd.render_stage_start_display("INTAKE", checklist, [])
        assert "```dv-harness-evidence:" in display  # the condition that broke it
        path = spd.save_stage_report(tmp, "INTAKE", "start", display, payload=checklist)
        assert _display_of(path) == display
        assert _payload_of(path) == json.loads(json.dumps(checklist))
        # No fence in the body is as long as the wrapper.
        body = path.read_text(encoding="utf-8")
        assert body.count("````") == 4
        assert "`````" not in body
    finally:
        shutil.rmtree(tmp)


def test_report_listing_filters_by_stage_and_phase():
    tmp = Path(tempfile.mkdtemp())
    try:
        spd.save_stage_report(tmp, "INTAKE", "start", "x", timestamp="2026-09-04T00:00:01+00:00")
        spd.save_stage_report(tmp, "INTAKE", "done", "y", timestamp="2026-09-04T00:00:02+00:00")
        spd.save_stage_report(tmp, "VERIFY", "start", "z", timestamp="2026-09-04T00:00:03+00:00")
        assert len(spd.list_stage_reports(tmp)) == 3
        assert len(spd.list_stage_reports(tmp, stage="INTAKE")) == 2
        assert len(spd.list_stage_reports(tmp, stage="INTAKE", phase="done")) == 1
        assert spd.latest_stage_report(tmp, stage="INTAKE", phase="done").read_text(
            encoding="utf-8").count("y") >= 1
        assert spd.list_stage_reports(tmp / "nope") == []
    finally:
        shutil.rmtree(tmp)


def test_reports_are_ordered_by_timestamp_not_by_filename():
    # REGRESSION (2026-09-04): the listing sorted raw filenames, and "done"
    # sorts before "start", so every DONE report was reported as older than
    # every START report no matter when either was written. The visible
    # consequence was latest_stage_report(stage=...) with no phase filter
    # handing back the START report while a strictly newer DONE report sat
    # beside it -- i.e. `dv-harness stage-report INTAKE` printing the banner
    # for the beginning of a stage that had already finished.
    tmp = Path(tempfile.mkdtemp())
    try:
        spd.save_stage_report(tmp, "INTAKE", "start", "first",
                              timestamp="2026-09-04T00:00:01+00:00")
        spd.save_stage_report(tmp, "INTAKE", "done", "second",
                              timestamp="2026-09-04T00:00:02+00:00")
        names = [p.name for p in spd.list_stage_reports(tmp, stage="INTAKE")]
        assert "_start_" in names[0] and "_done_" in names[1]
        latest = spd.latest_stage_report(tmp, stage="INTAKE")
        assert "second" in latest.read_text(encoding="utf-8")
        # A start/done pair written within the same second still reads in the
        # order the stage really passed through them.
        spd.save_stage_report(tmp, "VERIFY", "done", "d", timestamp="2026-09-04T09:00:00+00:00")
        spd.save_stage_report(tmp, "VERIFY", "start", "s", timestamp="2026-09-04T09:00:00+00:00")
        assert [p.name.split("_")[1] for p in spd.list_stage_reports(tmp, stage="VERIFY")] == \
            ["start", "done"]
    finally:
        shutil.rmtree(tmp)


def test_stage_filter_is_exact_not_a_name_prefix():
    # REGRESSION (2026-09-04): the filter was name.startswith(stage + "_"),
    # and the REAL workflow order contains BUILD alongside BUILD_DEBUG and
    # REGRESSION alongside REGRESSION_SELECT/REGRESSION_MONITOR -- so asking
    # for one stage's reports returned another stage's reports under its name.
    from dv_harness.policy import ORDER
    assert {"BUILD", "BUILD_DEBUG"} <= set(ORDER)  # the collision is real
    tmp = Path(tempfile.mkdtemp())
    try:
        spd.save_stage_report(tmp, "BUILD", "start", "b", timestamp="2026-09-04T00:00:01+00:00")
        spd.save_stage_report(tmp, "BUILD_DEBUG", "start", "bd",
                              timestamp="2026-09-04T00:00:02+00:00")
        assert [p.name for p in spd.list_stage_reports(tmp, stage="BUILD")] == \
            [p.name for p in spd.list_stage_reports(tmp, stage="BUILD")
             if p.name.startswith("BUILD_start_")]
        assert len(spd.list_stage_reports(tmp, stage="BUILD")) == 1
        assert len(spd.list_stage_reports(tmp, stage="BUILD_DEBUG")) == 1
        # A stage whose name really does carry underscores round-trips.
        assert spd._parse_report_name("BUILD_DEBUG_start_20260904T0000020000") == {
            "stage": "BUILD_DEBUG", "phase": "start", "timestamp": "20260904T0000020000"}
        # A hand-dropped file that is not one of ours is skipped, not
        # reported as a stage report with a garbage stage name.
        (tmp / ".dv-harness" / "stage_reports" / "notes.md").write_text("x", encoding="utf-8")
        assert spd._parse_report_name("notes") is None
        assert len(spd.list_stage_reports(tmp)) == 2
    finally:
        shutil.rmtree(tmp)


# --- real run_stage() integration ------------------------------------------

_INTAKE_PAYLOAD = {
    "mode": "SUBSYSTEM", "target_name": "usb", "protocols": ["USB"],
    "required_artifacts": {"protocol_spec": True, "dut_design_spec": False,
                           "rtl_top_or_interface_files": True},
}
_INTAKE_TEXT = ("```dv-harness-evidence:intake_readiness\n"
                + json.dumps(_INTAKE_PAYLOAD) + "\n```")


class _PassAdapter:
    def __init__(self, text):
        self.text = text

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        return AgentResult(ok=True, text=self.text, raw={
            "response": {"model": "test-model",
                         "usage": {"input_tokens": 900, "output_tokens": 120}}},
            session_id="s1")


def test_run_stage_prints_and_saves_both_displays_at_the_real_stage_boundaries(capsys):
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("INTAKE")
        h.adapter = _PassAdapter(_INTAKE_TEXT)
        h.run_stage("goal")
        assert h.state.stages["INTAKE"]["status"] == Status.PASS.value

        out = capsys.readouterr().out
        # Both banners really reached the terminal, at both boundaries.
        assert "STAGE START" in out and "STAGE DONE" in out
        assert out.index("STAGE START") < out.index("STAGE DONE")
        assert "REQUIRED INPUTS (documents / files / data)" in out
        assert "OUTPUT FILES / DATA PRODUCED" in out
        assert "ACTION REQUIRED: please provide more detail on" in out
        assert "EXECUTION TIME AND TOKENS" in out
        assert "COMPLETENESS:" in out
        # The pre-existing one-line greppable markers are untouched.
        assert "[DV-HARNESS-STAGE] ===== STAGE START: INTAKE =====" in out
        assert "[DV-HARNESS-STAGE] ===== STAGE DONE: INTAKE" in out

        # Both reports were persisted, and each one's embedded display is
        # exactly the text that was printed.
        start = spd.latest_stage_report(tmp, stage="INTAKE", phase="start")
        done = spd.latest_stage_report(tmp, stage="INTAKE", phase="done")
        assert start is not None and done is not None
        for report in (start, done):
            display = _display_of(report)
            assert display in out
            payload = _payload_of(report)
            # The percentage in the saved report is consistent with the
            # checklist items saved beside it.
            key = "input_checklist" if report is start else "output_checklist"
            ck = payload[key]
            assert ck["present_count"] == sum(1 for it in ck["items"] if it["present"])
            expected = (100.0 * ck["present_count"] / ck["total_count"]) if ck["total_count"] else 100.0
            assert abs(ck["completeness_percent"] - expected) < 1e-9
            assert f"({ck['present_count']}/{ck['total_count']} present)" in display

        # The DONE report's time/token block carries the real agent run this
        # attempt made, with the real usage the adapter reported.
        summary = _payload_of(done)["time_token_summary"]
        assert summary["latest"]["agent_run_count"] >= 1
        assert summary["latest"]["total_tokens"] == 1020
        assert summary["latest"]["stage_wall_clock_sec"] >= 0
    finally:
        shutil.rmtree(tmp)


def test_run_stage_start_display_reports_gate_evidence_as_absent_on_the_first_attempt(capsys):
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("INTAKE")
        h.adapter = _PassAdapter(_INTAKE_TEXT)
        h.run_stage("goal")
        capsys.readouterr()

        start = spd.latest_stage_report(tmp, stage="INTAKE", phase="start")
        payload = _payload_of(start)
        gate_items = [it for it in payload["input_checklist"]["items"]
                      if spd.SOURCE_STAGE_GATES in it["sources"]]
        assert gate_items and all(it["present"] is False for it in gate_items)
        # ...and the reminder names each of them explicitly.
        for it in gate_items:
            assert any(ln.startswith(f"{it['item_id']}:") for ln in payload["detail_requests"])

        # The DONE report then shows those same gate blocks as produced or
        # not, from THIS attempt's own evidence -- intake_readiness was
        # submitted, the other three were not.
        done = spd.latest_stage_report(tmp, stage="INTAKE", phase="done")
        dpayload = _payload_of(done)
        produced = {it["item_id"]: it["present"] for it in dpayload["output_checklist"]["items"]
                    if spd.SOURCE_STAGE_GATES in it["sources"]}
        assert produced["intake_readiness"] is True
        assert produced["generated_artifact_boundary_gate"] is False
    finally:
        shutil.rmtree(tmp)


def test_display_failure_never_fails_a_real_stage(capsys, monkeypatch):
    # Observability must never turn a stage that really ran into a failed one.
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("INTAKE")
        h.adapter = _PassAdapter(_INTAKE_TEXT)

        def _boom(*a, **k):
            raise RuntimeError("synthetic display failure")

        monkeypatch.setattr(spd, "build_stage_input_checklist", _boom)
        monkeypatch.setattr(spd, "build_stage_output_checklist", _boom)
        h.run_stage("goal")

        assert h.state.stages["INTAKE"]["status"] == Status.PASS.value
        out = capsys.readouterr().out
        assert "stage start display unavailable: synthetic display failure" in out
        assert "stage done display unavailable: synthetic display failure" in out
    finally:
        shutil.rmtree(tmp)


def test_takeover_and_dry_run_never_emit_a_stage_start_display(capsys):
    # Same rule the existing start MARKER already follows: a stage that never
    # actually starts must not print a START it did not earn, and must not
    # leave a report file claiming it did.
    tmp, h = _fresh_harness()
    try:
        h.set_stage("INTAKE")
        h.run_stage("goal", dry_run=True)
        out = capsys.readouterr().out
        assert "STAGE START" not in out
        assert spd.list_stage_reports(tmp) == []
    finally:
        shutil.rmtree(tmp)
