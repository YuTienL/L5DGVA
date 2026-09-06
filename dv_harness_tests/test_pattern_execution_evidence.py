"""Tests for dv_harness/pattern_execution_evidence.py -- per-command-line
(task/branch) execution evidence, finer granularity than evidence_db's
per-test rows.

Fixtures are built in the same real "UVM_INFO ... @ <time>: <reporter>
[<ID>] starting <name>" / "... complete" narration shape
`dv_harness_tests/test_sim_log_analysis.py`'s own fixtures already use --
not a fabricated marker format. Task/branch names follow the canonical
block/branch_a{i}/branch_fw/branch_b{i} vocabulary from
`.claude/skills/CORE/pattern-architecture/SKILL.md`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import pattern_execution_evidence as pee

ROOT = Path(__file__).resolve().parents[1]

# A full pattern run narrating all four canonical layers, one clean
# (branch_a0) and one carrying a real scoreboard mismatch inside its own
# window (branch_b1) -- mirrors enumeration/usb20_enumeration.txt's real
# fork/join shape cited in pattern-architecture/SKILL.md.
FULL_PATTERN_LOG = """\
UVM_INFO test_top.sv(10) @ 100: reporter [TASK] starting block
UVM_INFO test_top.sv(11) @ 500: reporter [TASK] block complete
UVM_INFO test_top.sv(20) @ 600: reporter [TASK] starting branch_a0
UVM_INFO test_top.sv(21) @ 900: reporter [TASK] branch_a0 complete
UVM_INFO test_top.sv(30) @ 650: reporter [TASK] starting branch_fw
UVM_INFO test_top.sv(40) @ 1000: reporter [TASK] starting branch_b0
UVM_INFO test_top.sv(41) @ 1500: reporter [TASK] starting branch_b1
UVM_ERROR test_top.sv(120) @ 1600: scoreboard [SB_MISMATCH] expected 0xdead1234 got 0xbeef0001
UVM_INFO test_top.sv(42) @ 1800: reporter [TASK] branch_b0 complete
UVM_INFO test_top.sv(43) @ 2000: reporter [TASK] branch_b1 complete
FINAL CHECK @ 2100 ns
UVM_FATAL = 0, UVM_ERROR = 1, UVM_WARNING = 0
VERDICT: FAILED
"""

# No task-level narration at all -- only whole-test level markers, the
# common real shape (per test_sim_log_analysis.py's CLEAN_PASS_LOG).
WHOLE_TEST_ONLY_LOG = """\
UVM_INFO test_top.sv(42) @ 100000: reporter [TEST] starting basic_ss_serial
UVM_INFO test_top.sv(88) @ 250000: reporter [TEST] all sequences complete
FINAL CHECK @ 300000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 2
VERDICT: PASSED
"""

# branch_a1 started but never reported completion -- e.g. a hung/truncated
# run. Must never fabricate an end_time.
HUNG_TASK_LOG = """\
UVM_INFO test_top.sv(10) @ 100: reporter [TASK] starting block
UVM_INFO test_top.sv(11) @ 300: reporter [TASK] block complete
UVM_INFO test_top.sv(20) @ 400: reporter [TASK] starting branch_a1
[alive] t=5000
RUN TRUNCATED
"""

# A task narrated on a line that carries no real "@ <time>" marker at all
# (e.g. a bare print, not a UVM_INFO line) -- start_time must read
# NOT_AVAILABLE rather than being interpolated from a neighboring line.
NO_TIMESTAMP_ON_NARRATION_LOG = """\
[stage] starting branch_b0
UVM_INFO test_top.sv(42) @ 5000: reporter [TASK] branch_b0 complete
"""


class TestExtractTaskLifecycleEvents:
    def test_finds_start_and_end_for_each_canonical_task(self):
        events = pee.extract_task_lifecycle_events(FULL_PATTERN_LOG)
        assert set(events.keys()) == {"block", "branch_a0", "branch_fw", "branch_b0", "branch_b1"}
        assert events["block"][0]["kind"] == pee.START
        assert events["block"][0]["time"] == 100.0
        assert events["block"][1]["kind"] == pee.END
        assert events["block"][1]["time"] == 500.0

    def test_no_canonical_task_name_yields_empty_map(self):
        assert pee.extract_task_lifecycle_events(WHOLE_TEST_ONLY_LOG) == {}


class TestClassifyBranchLayer:
    @pytest.mark.parametrize(
        "name,layer",
        [
            ("block", pee.GLOBAL_BLOCK),
            ("branch_a0", pee.DUT_PHY_INIT),
            ("branch_a12", pee.DUT_PHY_INIT),
            ("branch_fw", pee.FW_SERVICE_LOOP),
            ("branch_b3", pee.VIP_TEST_BODY),
        ],
    )
    def test_maps_canonical_names_to_layer(self, name, layer):
        assert pee.classify_branch_layer(name) == layer

    def test_unrecognized_name_raises(self):
        with pytest.raises(ValueError):
            pee.classify_branch_layer("branch_c0")


class TestBuildPatternExecutionRecords:
    def test_full_pattern_produces_one_record_per_task_with_real_evidence(self):
        report = pee.build_pattern_execution_records(FULL_PATTERN_LOG, command="usb20_enumeration")
        assert report.granularity_status == pee.GRANULARITY_FOUND
        assert report.command == "usb20_enumeration"
        by_task = {r.task for r in report.records}
        assert by_task == {"block", "branch_a0", "branch_fw", "branch_b0", "branch_b1"}

    def test_clean_branch_reports_completed_clean_with_real_times(self):
        report = pee.build_pattern_execution_records(FULL_PATTERN_LOG, command="usb20_enumeration")
        rec = next(r for r in report.records if r.task == "branch_a0")
        assert rec.branch == pee.DUT_PHY_INIT
        assert rec.start_time == 600.0
        assert rec.end_time == 900.0
        assert rec.result == pee.RESULT_COMPLETED_CLEAN
        assert rec.checker == pee.NOT_AVAILABLE
        assert rec.scoreboard == pee.NOT_AVAILABLE
        assert rec.events_observed == []

    def test_branch_with_real_scoreboard_mismatch_reports_it_with_completed_with_errors(self):
        report = pee.build_pattern_execution_records(FULL_PATTERN_LOG, command="usb20_enumeration")
        rec = next(r for r in report.records if r.task == "branch_b1")
        assert rec.result == pee.RESULT_COMPLETED_WITH_ERRORS
        assert rec.scoreboard != pee.NOT_AVAILABLE
        assert len(rec.scoreboard) == 1
        sb = rec.scoreboard[0]
        assert sb["category"] == "scoreboard_mismatch"
        # the real UVM_ERROR line is at file line 8 (1-indexed) -- the
        # window-offset arithmetic must land on the true original line, not
        # a window-relative one.
        assert sb["first_line_no"] == 8
        assert "0xdead1234" in sb["example_line"]

    def test_scoreboard_mismatch_inside_branch_b1_window_does_not_leak_into_branch_b0(self):
        report = pee.build_pattern_execution_records(FULL_PATTERN_LOG, command="usb20_enumeration")
        rec_b0 = next(r for r in report.records if r.task == "branch_b0")
        # branch_b0's own window (line 7 "starting branch_b0" .. line 9
        # "branch_b0 complete") does textually CONTAIN the error line 8, so
        # the scoreboard mismatch legitimately appears in both windows'
        # evidence (they overlap in the raw log) -- what must NOT happen is
        # branch_a0 or block (whose windows end well before line 8) ever
        # reporting it.
        rec_block = next(r for r in report.records if r.task == "block")
        rec_a0 = next(r for r in report.records if r.task == "branch_a0")
        assert rec_block.scoreboard == pee.NOT_AVAILABLE
        assert rec_a0.scoreboard == pee.NOT_AVAILABLE

    def test_no_task_level_narration_returns_empty_records_never_fabricated(self):
        report = pee.build_pattern_execution_records(WHOLE_TEST_ONLY_LOG, command="basic_ss_serial")
        assert report.granularity_status == pee.GRANULARITY_ABSENT
        assert report.records == []
        assert "whole-test-level" in report.granularity_reason

    def test_omitted_command_reports_not_available_rather_than_a_guess(self):
        report = pee.build_pattern_execution_records(FULL_PATTERN_LOG)
        assert report.command == pee.NOT_AVAILABLE
        for rec in report.records:
            assert rec.command == pee.NOT_AVAILABLE

    def test_hung_task_never_fabricates_an_end_time(self):
        report = pee.build_pattern_execution_records(HUNG_TASK_LOG, command="hung_case")
        rec = next(r for r in report.records if r.task == "branch_a1")
        assert rec.start_time == 400.0
        assert rec.end_time == pee.NOT_AVAILABLE
        assert rec.result == pee.RESULT_INCOMPLETE_NO_END_MARKER
        assert rec.end_line is None
        # block, which DID complete, is unaffected by branch_a1 hanging.
        rec_block = next(r for r in report.records if r.task == "block")
        assert rec_block.result == pee.RESULT_COMPLETED_CLEAN
        assert rec_block.end_time == 300.0

    def test_narration_line_without_a_real_timestamp_reports_not_available(self):
        report = pee.build_pattern_execution_records(
            NO_TIMESTAMP_ON_NARRATION_LOG, command="edge_case"
        )
        rec = next(r for r in report.records if r.task == "branch_b0")
        assert rec.start_time == pee.NOT_AVAILABLE
        assert rec.start_line == 1
        assert rec.end_time == 5000.0

    def test_total_lines_matches_real_line_count(self):
        report = pee.build_pattern_execution_records(FULL_PATTERN_LOG, command="x")
        assert report.total_lines == len(FULL_PATTERN_LOG.splitlines())


class TestParsePatternExecutionLogFileWrapper:
    def test_reads_a_real_file_from_disk(self, tmp_path):
        p = tmp_path / "sim.log"
        p.write_text(FULL_PATTERN_LOG, encoding="utf-8")
        report = pee.parse_pattern_execution_log(p, command="usb20_enumeration")
        assert report.granularity_status == pee.GRANULARITY_FOUND
        assert len(report.records) == 5

    def test_survives_a_stray_non_utf8_byte(self, tmp_path):
        p = tmp_path / "sim.log"
        with open(p, "wb") as f:
            f.write(FULL_PATTERN_LOG.encode("utf-8"))
            f.write(b"\xff\xfe garbage\n")
        report = pee.parse_pattern_execution_log(p, command="x")
        assert report.granularity_status == pee.GRANULARITY_FOUND


class TestRenderPatternExecutionMarkdown:
    def test_renders_a_markdown_table_with_real_rows(self):
        report = pee.build_pattern_execution_records(FULL_PATTERN_LOG, command="usb20_enumeration")
        md = pee.render_pattern_execution_markdown(report)
        assert "usb20_enumeration" in md
        assert "branch_b1" in md
        assert "| Command | Task | Branch |" in md

    def test_empty_records_renders_empty_note_not_a_blank_table(self):
        report = pee.build_pattern_execution_records(WHOLE_TEST_ONLY_LOG, command="x")
        md = pee.render_pattern_execution_markdown(report)
        assert "no task-level records" in md


class TestCliEntryPoint:
    def test_runs_as_a_real_subprocess_and_exits_0_on_found_granularity(self, tmp_path):
        p = tmp_path / "sim.log"
        p.write_text(FULL_PATTERN_LOG, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.pattern_execution_evidence", str(p), "--command", "x"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "branch_b1" in result.stdout

    def test_exits_1_when_log_has_no_task_level_granularity(self, tmp_path):
        p = tmp_path / "sim.log"
        p.write_text(WHOLE_TEST_ONLY_LOG, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.pattern_execution_evidence", str(p)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_json_output_is_valid_json_with_required_schema_fields(self, tmp_path):
        import json

        p = tmp_path / "sim.log"
        p.write_text(FULL_PATTERN_LOG, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.pattern_execution_evidence", str(p),
             "--command", "usb20_enumeration", "--json"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        rec = payload["records"][0]
        for key in ("command", "task", "branch", "start_time", "end_time",
                    "result", "events_observed", "checker", "scoreboard"):
            assert key in rec
