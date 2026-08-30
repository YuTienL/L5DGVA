"""Tests for dv_harness/sim_log_analysis.py -- the generic sim.log marker
parser/classifier/epilogue-extractor.

Fixtures below are built from the documented real format evidence cited in
this module's own docstring and in .claude/skills/USB/usb-regression/
SKILL.md ("FINAL CHECK @ <time> ns" / "UVM_FATAL = N, UVM_ERROR = N,
UVM_WARNING = N" / "VERDICT: PASSED|FAILED" epilogue; the real PLL-model
bare-ERROR incident; usbrun.sh-style tag vocabulary) -- not fabricated
formats.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import sim_log_analysis as sla

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CLEAN_PASS_LOG = """\
[stage] GLOBAL_INIT done
[alive] t=100000
UVM_INFO test_top.sv(42) @ 100000: reporter [TEST] starting basic_ss_serial
UVM_INFO test_top.sv(88) @ 250000: reporter [TEST] all sequences complete
FINAL CHECK @ 300000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 2
VERDICT: PASSED
"""

# Real-shaped UVM_ERROR-heavy failure log with repeated signatures that must
# collapse -- the same scoreboard mismatch fires 3 times at 3 different sim
# times/hex addresses, and must normalize to ONE signature with count=3.
UVM_ERROR_HEAVY_LOG = """\
[stage] GLOBAL_INIT done
UVM_INFO test_top.sv(10) @ 1000: reporter [TEST] starting arb1
UVM_ERROR test_top.sv(120) @ 15000: scoreboard [SB_MISMATCH] expected 0xdead1234 got 0xbeef0001
UVM_INFO test_top.sv(130) @ 20000: reporter [TEST] continuing
UVM_ERROR test_top.sv(120) @ 45000: scoreboard [SB_MISMATCH] expected 0xdead5678 got 0xbeef0002
UVM_ERROR test_top.sv(120) @ 99000: scoreboard [SB_MISMATCH] expected 0xdead9999 got 0xbeef0003
UVM_FATAL test_top.sv(200) @ 100000: env [ENV_FATAL] unrecoverable protocol violation
FINAL CHECK @ 100050 ns
UVM_FATAL = 1, UVM_ERROR = 3, UVM_WARNING = 0
VERDICT: FAILED
"""

# The real documented trap: a bare, non-UVM_-prefixed "ERROR in PLL model"
# line that a UVM_ERROR-only filter missed for an hour in the real project's
# history (per usbrun.sh evidence cited in sim_log_analysis.py's docstring).
BARE_ERROR_LOG = """\
[stage] GLOBAL_INIT done
[alive] t=5000
ERROR in PLL model: lock never asserted after 5000 ns
[alive] t=10000
UVM_INFO test_top.sv(1) @ 10000: reporter [TEST] test still running
"""

# No epilogue at all -- must degrade gracefully (parse_epilogue -> None),
# e.g. a job killed mid-run before it could print its FINAL CHECK block.
NO_EPILOGUE_LOG = """\
[stage] GLOBAL_INIT done
UVM_INFO test_top.sv(1) @ 1000: reporter [TEST] starting hs1
[alive] t=20000
RUN TRUNCATED
"""


class TestParseSimLog:
    def test_clean_pass_has_no_error_signatures(self):
        result = sla.parse_sim_log(CLEAN_PASS_LOG)
        classified = sla.classify_signatures(result["signatures"])
        assert all(c["category"] not in ("uvm_fatal", "uvm_error", "bare_error")
                    for c in classified)
        assert result["epilogue"]["verdict"] == "PASSED"
        assert result["epilogue"]["uvm_fatal"] == 0
        assert result["epilogue"]["uvm_error"] == 0

    def test_repeated_signatures_collapse_with_correct_count(self):
        result = sla.parse_sim_log(UVM_ERROR_HEAVY_LOG)
        classified = sla.classify_signatures(result["signatures"])
        sb_sigs = [c for c in classified if c["category"] == "scoreboard_mismatch"]
        # all 3 UVM_ERROR scoreboard-mismatch lines differ only in sim time
        # and hex payload -> must normalize to exactly one signature.
        assert len(sb_sigs) == 1
        assert sb_sigs[0]["count"] == 3
        assert sb_sigs[0]["first_line_no"] == 3
        assert sb_sigs[0]["last_line_no"] == 6

    def test_uvm_fatal_present_and_classified_critical(self):
        result = sla.parse_sim_log(UVM_ERROR_HEAVY_LOG)
        classified = sla.classify_signatures(result["signatures"])
        fatal_sigs = [c for c in classified if c["category"] == "uvm_fatal"]
        assert len(fatal_sigs) == 1
        assert fatal_sigs[0]["severity"] == "CRITICAL"
        # worst-first sort: uvm_fatal (CRITICAL) must sort before
        # scoreboard_mismatch (HIGH).
        assert classified[0]["category"] == "uvm_fatal"

    def test_bare_error_trap_is_caught_not_missed(self):
        """The documented real trap: a plain 'ERROR in PLL model' line with
        no UVM_ prefix must be caught, not silently missed by a UVM_-only
        filter."""
        result = sla.parse_sim_log(BARE_ERROR_LOG)
        classified = sla.classify_signatures(result["signatures"])
        bare = [c for c in classified if c["category"] == "bare_error"]
        assert len(bare) == 1
        assert "PLL model" in bare[0]["example_line"]
        assert bare[0]["first_line_no"] == 3
        # must not be misclassified as a UVM_ERROR (there is no UVM_ prefix)
        assert bare[0]["category"] != "uvm_error"

    def test_no_epilogue_degrades_gracefully(self):
        result = sla.parse_sim_log(NO_EPILOGUE_LOG)
        assert result["epilogue"] is None
        # log still has no error markers, so classify_signatures must not
        # blow up on an epilogue-free, error-free log either.
        classified = sla.classify_signatures(result["signatures"])
        assert isinstance(classified, list)

    def test_parse_sim_log_file_wrapper(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            log_path = tmp / "sim.log"
            log_path.write_text(UVM_ERROR_HEAVY_LOG, encoding="utf-8")
            result = sla.parse_sim_log_file(log_path)
            assert result["total_lines"] == len(UVM_ERROR_HEAVY_LOG.splitlines())
            assert result["epilogue"]["verdict"] == "FAILED"
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestParseEpilogue:
    def test_full_epilogue_parsed(self):
        epi = sla.parse_epilogue(UVM_ERROR_HEAVY_LOG)
        assert epi == {
            "final_check_time_ns": 100050.0,
            "uvm_fatal": 1,
            "uvm_error": 3,
            "uvm_warning": 0,
            "verdict": "FAILED",
        }

    def test_absent_epilogue_returns_none(self):
        assert sla.parse_epilogue(NO_EPILOGUE_LOG) is None


class TestClassifySignatures:
    def test_sorted_worst_first(self):
        result = sla.parse_sim_log(UVM_ERROR_HEAVY_LOG)
        classified = sla.classify_signatures(result["signatures"])
        severities = [sla._severity_sort_key(c["severity"]) for c in classified]
        assert severities == sorted(severities)

    def test_empty_signatures_returns_empty_list(self):
        assert sla.classify_signatures({}) == []


class TestDetectUnderreporting:
    def test_underreported_uvm_error_flagged(self):
        parsed = sla.parse_sim_log(UVM_ERROR_HEAVY_LOG)
        # job_state under-declares: it claims clean, but the real log has
        # UVM_FATAL/UVM_ERROR -- this is exactly the "LSF DONE != DV PASS"
        # scenario CLAUDE.md and lsf_per_job_monitor_gate.py describe.
        job_state = {
            "job_id": 12345,
            "uvm_error_detected": False,
            "fatal_detected": False,
        }
        discrepancies = sla.detect_underreporting(job_state, parsed)
        assert any("UNDER_REPORTED_UVM_FATAL" in d for d in discrepancies)
        assert any("UNDER_REPORTED_UVM_ERROR" in d for d in discrepancies)

    def test_correctly_reported_produces_no_discrepancy(self):
        parsed = sla.parse_sim_log(UVM_ERROR_HEAVY_LOG)
        job_state = {
            "job_id": 12345,
            "uvm_error_detected": True,
            "fatal_detected": True,
        }
        discrepancies = sla.detect_underreporting(job_state, parsed)
        assert discrepancies == []

    def test_clean_pass_has_no_discrepancy(self):
        parsed = sla.parse_sim_log(CLEAN_PASS_LOG)
        job_state = {"job_id": 1, "uvm_error_detected": False, "fatal_detected": False}
        assert sla.detect_underreporting(job_state, parsed) == []

    def test_jobstate_count_field_naming_also_supported(self):
        """lsf_client.JobState uses uvm_error_count/uvm_fatal_count (ints),
        not uvm_error_detected/fatal_detected (bools) -- both namings must
        be accepted since both are real call sites (JobState.asdict() dumps
        vs. lsf_per_job_monitor_gate.py's own jobs.json schema)."""
        parsed = sla.parse_sim_log(UVM_ERROR_HEAVY_LOG)
        job_state = {"job_id": 1, "uvm_error_count": 3, "uvm_fatal_count": 1}
        assert sla.detect_underreporting(job_state, parsed) == []


class TestCliSimLogAnalyze:
    def _run_cli(self, tmp, *args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "sim-log-analyze", *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
        )

    def test_log_text_flag_prints_json(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            r = self._run_cli(tmp, "--log-text", BARE_ERROR_LOG)
            assert r.returncode == 0
            payload = json.loads(r.stdout)
            assert payload["total_lines"] == len(BARE_ERROR_LOG.splitlines())
            cats = [s["category"] for s in payload["signatures"]]
            assert "bare_error" in cats
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_log_file_flag_prints_json(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            log_path = tmp / "sim.log"
            log_path.write_text(UVM_ERROR_HEAVY_LOG, encoding="utf-8")
            r = self._run_cli(tmp, "--log", str(log_path))
            assert r.returncode == 0
            payload = json.loads(r.stdout)
            assert payload["epilogue"]["verdict"] == "FAILED"
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_mutually_exclusive_flags_required(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            r = self._run_cli(tmp)
            assert r.returncode != 0
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
