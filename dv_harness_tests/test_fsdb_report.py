"""Tests for dv_harness/fsdb_report.py -- the fsdbreport CLI wrapper.

This dev machine has no Verdi/fsdbreport install (Windows box; the real
tool runs on the Linux DV server), so the binary-missing path below is a
REAL, not mocked, end-to-end exercise of run_fsdbreport()'s graceful
degradation (fsdbreport genuinely is not on PATH here). The nonzero-exit
and timeout cases cannot be triggered for real without the binary, so
those mock subprocess.run, matching test_lsf_client.py's established style
for the same kind of gap.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from dv_harness import fsdb_report

ROOT = Path(__file__).resolve().parents[1]


def _completed(stdout="", stderr="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestRunFsdbreport:
    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fsdb = self.tmp / "dump.fsdb"
        self.fsdb.write_bytes(b"")  # plausible-looking 0-byte fake .fsdb

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_arg_raises_fsdbreporterror(self):
        with pytest.raises(fsdb_report.FsdbReportError):
            fsdb_report.run_fsdbreport("")

    def test_fsdb_file_not_found(self):
        result = fsdb_report.run_fsdbreport(str(self.tmp / "does_not_exist.fsdb"))
        assert result == {"ok": False, "error": "FSDB_FILE_NOT_FOUND"}

    def test_binary_not_found_is_real_not_mocked(self):
        # No mocking here: fsdbreport really is not on PATH on this machine.
        result = fsdb_report.run_fsdbreport(str(self.fsdb), fsdbreport_bin="fsdbreport")
        assert result["ok"] is False
        assert result["error"] == "FSDBREPORT_BINARY_NOT_FOUND"
        assert "detail" in result

    def test_nonzero_exit_reported(self):
        with patch("dv_harness.fsdb_report.subprocess.run",
                   return_value=_completed(returncode=1, stderr="bad option")):
            result = fsdb_report.run_fsdbreport(str(self.fsdb))
        assert result == {"ok": False, "error": "FSDBREPORT_NONZERO_EXIT",
                            "returncode": 1, "stderr": "bad option"}

    def test_timeout_reported(self):
        with patch("dv_harness.fsdb_report.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="fsdbreport", timeout=60)):
            result = fsdb_report.run_fsdbreport(str(self.fsdb), timeout=60)
        assert result == {"ok": False, "error": "FSDBREPORT_TIMEOUT"}

    def test_success_returns_report_text(self):
        with patch("dv_harness.fsdb_report.subprocess.run",
                   return_value=_completed(stdout="signal report here", stderr="")):
            result = fsdb_report.run_fsdbreport(str(self.fsdb))
        assert result == {"ok": True, "report_text": "signal report here", "stderr": ""}

    def test_extra_args_placed_after_file_matching_confirmed_invocation_order(self):
        # Confirmed-real invocation (dv-workflow/SKILL.md's 2026-08-29
        # "Confirmed drift" entry): `fsdbreport f.fsdb -period <T> -level 1
        # -csv` -- file path BEFORE the flags. Asserts the actual argv
        # built by run_fsdbreport() matches that real order, not the
        # flags-before-file order this had prior to that confirmed usage.
        with patch("dv_harness.fsdb_report.subprocess.run",
                   return_value=_completed(stdout="", stderr="")) as m:
            fsdb_report.run_fsdbreport(str(self.fsdb), extra_args=["-period", "100ns", "-level", "1", "-csv"])
        argv = m.call_args[0][0]
        assert argv == ["fsdbreport", str(self.fsdb), "-period", "100ns", "-level", "1", "-csv"]


class TestParseFsdbreportOutput:
    def test_honest_pass_through(self):
        result = fsdb_report.parse_fsdbreport_output("some report text")
        assert result["raw_text"] == "some report text"
        assert result["parsed"] is False
        assert "not verified" in result["note"]

    def test_parse_fsdbreport_csv_output_produces_structured_records(self):
        # Real-shaped CSV sample matching the confirmed `fsdbreport f.fsdb
        # -period <T> -level 1 -csv` invocation from dv-workflow/SKILL.md's
        # 2026-08-29 confirmed-drift entry -- that entry confirms the
        # invocation and that -csv output is CSV-shaped, but does not
        # record fsdbreport's real column header names, so this fixture's
        # header (signal,timestamp,value) is this test's own illustrative
        # choice, not a claim about the real tool's exact header text.
        # parse_fsdbreport_output() must parse it structurally -- via
        # whatever header the CSV actually declares -- not by hardcoding
        # these particular names, so a real run with different real column
        # names would still parse correctly.
        csv_text = (
            "signal,timestamp,value\n"
            "top.dut.clk,0,0\n"
            "top.dut.clk,5,1\n"
            "top.dut.rst_n,0,0\n"
            "top.dut.rst_n,12,1\n"
        )
        result = fsdb_report.parse_fsdbreport_output(csv_text)
        assert result["parsed"] is True
        assert result["fieldnames"] == ["signal", "timestamp", "value"]
        assert len(result["records"]) == 4
        assert result["records"][0] == {"signal": "top.dut.clk", "timestamp": "0", "value": "0"}
        assert result["records"][3] == {"signal": "top.dut.rst_n", "timestamp": "12", "value": "1"}

    def test_parse_fsdbreport_csv_output_is_header_agnostic(self):
        # Proves the parser doesn't hardcode signal/timestamp/value --
        # different real column names still parse into real records, since
        # the exact real header text is unconfirmed (see module docstring).
        csv_text = "hier_path,time_ns,val\nA.B,1,X\nA.C,2,Z\n"
        result = fsdb_report.parse_fsdbreport_output(csv_text)
        assert result["parsed"] is True
        assert result["fieldnames"] == ["hier_path", "time_ns", "val"]
        assert result["records"] == [
            {"hier_path": "A.B", "time_ns": "1", "val": "X"},
            {"hier_path": "A.C", "time_ns": "2", "val": "Z"},
        ]

    def test_parse_fsdbreport_output_still_handles_unparseable_input_honestly(self):
        result = fsdb_report.parse_fsdbreport_output("not csv at all, garbage text")
        assert result["parsed"] is False
        assert "raw_text" in result

    def test_parse_fsdbreport_output_header_only_is_honestly_unparsed(self):
        # A header line with no data rows below it isn't real evidence yet.
        result = fsdb_report.parse_fsdbreport_output("signal,timestamp,value\n")
        assert result["parsed"] is False

    def test_parse_fsdbreport_output_ragged_rows_are_honestly_unparsed(self):
        # A row with a different column count than the header doesn't look
        # like real, well-formed fsdbreport -csv output.
        csv_text = "signal,timestamp,value\ntop.dut.clk,0,0\ntop.dut.clk,5\n"
        result = fsdb_report.parse_fsdbreport_output(csv_text)
        assert result["parsed"] is False

    def test_parse_fsdbreport_output_empty_string_is_honestly_unparsed(self):
        result = fsdb_report.parse_fsdbreport_output("")
        assert result["parsed"] is False


class TestCliFsdbReport:
    def _run_cli(self, tmp, *args):
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), "fsdb-report", *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        return r

    def test_binary_missing_exits_nonzero_with_clear_message(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            fsdb = tmp / "dump.fsdb"
            fsdb.write_bytes(b"")
            r = self._run_cli(tmp, "--fsdb", str(fsdb))
            assert r.returncode != 0
            assert "FSDBREPORT_BINARY_NOT_FOUND" in r.stdout
            assert "fsdb-report FAILED" in r.stderr
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_fsdb_file_exits_nonzero(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            r = self._run_cli(tmp, "--fsdb", str(tmp / "nope.fsdb"))
            assert r.returncode != 0
            assert "FSDB_FILE_NOT_FOUND" in r.stdout
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
