"""Real end-to-end tests for the standing connectivity-check recipe
(`dv_harness/connectivity_check.py`, 2026-09-04 gap closure).

These exercise the actual gap that was closed: Gate 3 (and Gates 1/2) being
manually-invocable-only, with no mechanism that re-runs them when the RTL
changes. Every test below drives the real `main()`/`run_connectivity_check()`
against a real temp project tree with real files on disk -- no mocking of
the gate logic itself; only Gate 1's `which`/`subprocess` seam uses
`connectivity.py`'s own established dependency-injection pattern so a fake
elaboration tool never reaches a real invocation.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dv_harness import connectivity_check as cc
from dv_harness.connectivity import GateStatus
from dv_harness.uvm_generator.bind_verification_lint import lint_status_report_file


def _make_project(tmp_path: Path, rtl_text: str = "module dut(input clk); endmodule\n") -> Path:
    root = tmp_path / "proj"
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "dut.sv").write_text(rtl_text, encoding="utf-8")
    (root / ".dv-harness").mkdir(parents=True, exist_ok=True)
    return root


def _write_config(root: Path, **overrides) -> Path:
    cfg = {
        "rtl_sources": ["rtl/**/*.sv"],
        "filelists": [],
        "top_module": "tb_top",
    }
    cfg.update(overrides)
    p = root / cc.DEFAULT_CONFIG_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return p


# ---- RTL fingerprint --------------------------------------------------------

def test_fingerprint_is_deterministic_and_content_based(tmp_path):
    root = _make_project(tmp_path)
    a = cc.compute_rtl_fingerprint(root, ["rtl/**/*.sv"])
    b = cc.compute_rtl_fingerprint(root, ["rtl/**/*.sv"])
    assert a["fingerprint"] == b["fingerprint"]
    assert a["file_count"] == 1

    # A pure touch (same content) must NOT change the fingerprint -- the gate
    # asks "is this the same RTL", not "was the file rewritten".
    (root / "rtl" / "dut.sv").write_text("module dut(input clk); endmodule\n", encoding="utf-8")
    assert cc.compute_rtl_fingerprint(root, ["rtl/**/*.sv"])["fingerprint"] == a["fingerprint"]


def test_fingerprint_changes_on_content_edit_and_on_new_file(tmp_path):
    root = _make_project(tmp_path)
    base = cc.compute_rtl_fingerprint(root, ["rtl/**/*.sv"])["fingerprint"]

    (root / "rtl" / "dut.sv").write_text("module dut(input clk, input rst_n); endmodule\n",
                                         encoding="utf-8")
    edited = cc.compute_rtl_fingerprint(root, ["rtl/**/*.sv"])["fingerprint"]
    assert edited != base

    (root / "rtl" / "phy.sv").write_text("module phy(); endmodule\n", encoding="utf-8")
    added = cc.compute_rtl_fingerprint(root, ["rtl/**/*.sv"])
    assert added["fingerprint"] != edited
    assert added["file_count"] == 2


# ---- Staleness (the standing trigger) --------------------------------------

def test_staleness_never_run_is_stale():
    assert cc.evaluate_staleness(None, "abc")["stale"] is True
    assert cc.evaluate_staleness(None, "abc")["reason"] == "NEVER_RUN"


def test_staleness_up_to_date_vs_rtl_changed():
    state = {"rtl_fingerprint": "abc"}
    assert cc.evaluate_staleness(state, "abc")["stale"] is False
    changed = cc.evaluate_staleness(state, "def")
    assert changed["stale"] is True and changed["reason"] == "RTL_CHANGED"


# ---- End-to-end: run, then RTL edit makes --check-only fail -----------------

def test_run_then_rtl_edit_makes_check_only_exit_stale(tmp_path, capsys):
    root = _make_project(tmp_path)
    _write_config(root, monitor_transaction_counts={"env.usb_agent.monitor": 42},
                  pattern_completed=True)

    assert cc.main(["--project-root", str(root)]) == cc.EXIT_OK
    state = json.loads((root / cc.DEFAULT_STATE_RELPATH).read_text(encoding="utf-8"))
    assert state["bind_verification_status"]["gate3_transaction_activity"] == "PASS"
    assert state["rtl_file_count"] == 1

    # Immediately after a real run, the standing check is clean.
    assert cc.main(["--project-root", str(root), "--check-only"]) == cc.EXIT_OK
    assert "UP_TO_DATE" in capsys.readouterr().out

    # Now the RTL moves. Nobody re-ran the gates -> the recorded verdicts
    # describe different RTL -> the standing check must fail, automatically.
    (root / "rtl" / "dut.sv").write_text("module dut(input clk, input rst_n); endmodule\n",
                                         encoding="utf-8")
    assert cc.main(["--project-root", str(root), "--check-only"]) == cc.EXIT_STALE
    out = capsys.readouterr().out
    assert "STALE (RTL_CHANGED)" in out
    assert "just connectivity-check" in out

    # Re-running the gates clears it.
    assert cc.main(["--project-root", str(root)]) == cc.EXIT_OK
    assert cc.main(["--project-root", str(root), "--check-only"]) == cc.EXIT_OK


def test_check_only_before_any_run_is_stale(tmp_path, capsys):
    root = _make_project(tmp_path)
    _write_config(root)
    assert cc.main(["--project-root", str(root), "--check-only"]) == cc.EXIT_STALE
    assert "NEVER_RUN" in capsys.readouterr().out


# ---- Gate 3 verdicts flowing through the runner -----------------------------

def test_gate3_fail_on_silent_monitor_makes_the_recipe_exit_nonzero(tmp_path, capsys):
    root = _make_project(tmp_path)
    _write_config(root,
                  monitor_transaction_counts={"env.a.monitor": 7, "env.b.monitor": 0},
                  pattern_completed=True)
    assert cc.main(["--project-root", str(root)]) == cc.EXIT_GATE_FAIL
    out = capsys.readouterr().out
    assert "gate3_transaction_activity: FAIL" in out
    assert "gate3_transaction_activity" in out


def test_gate3_pending_when_no_pattern_completed_is_not_a_failure(tmp_path):
    root = _make_project(tmp_path)
    _write_config(root, pattern_completed=False)
    result = cc.run_connectivity_check(root, cc.load_config(root / cc.DEFAULT_CONFIG_RELPATH))
    assert result.gate_report.gate3.status == GateStatus.PENDING
    assert result.exit_code == cc.EXIT_OK
    assert "gate3_transaction_activity" in result.gate_report.pending_gates()


def test_monitor_counts_read_from_a_real_file(tmp_path):
    root = _make_project(tmp_path)
    (root / "sim").mkdir()
    (root / "sim" / "counts.json").write_text(
        json.dumps({"monitor_transaction_counts": {"env.a.monitor": 3}}), encoding="utf-8")
    _write_config(root, monitor_transaction_counts_path="sim/counts.json", pattern_completed=True)
    result = cc.run_connectivity_check(root, cc.load_config(root / cc.DEFAULT_CONFIG_RELPATH))
    assert result.gate_report.gate3.status == GateStatus.PASS
    assert result.gate_report.gate3.detail["monitor_count"] == 1


# ---- Gate 2 through a real trace file ---------------------------------------

def test_gate2_reads_a_real_signal_trace_file_and_fails_a_dead_clock(tmp_path):
    root = _make_project(tmp_path)
    (root / "sim").mkdir()
    (root / "sim" / "trace.json").write_text(json.dumps({"samples": {
        "clk": [[0, "0"], [5, "0"]],            # never toggles -> real FAIL
        "rst_n": [[0, "0"], [10, "1"]],
        "data": [[0, "01"]],
    }}), encoding="utf-8")
    _write_config(root, signal_trace_path="sim/trace.json",
                  required_nonx_signals=["data"], pattern_completed=False)
    result = cc.run_connectivity_check(root, cc.load_config(root / cc.DEFAULT_CONFIG_RELPATH))
    assert result.gate_report.gate2.status == GateStatus.FAIL
    assert result.exit_code == cc.EXIT_GATE_FAIL


def test_gate2_passes_a_healthy_trace(tmp_path):
    root = _make_project(tmp_path)
    (root / "sim").mkdir()
    (root / "sim" / "trace.json").write_text(json.dumps({"samples": {
        "clk": [[0, "0"], [5, "1"], [10, "0"]],
        "rst_n": [[0, "0"], [10, "1"]],
        "data": [[0, "01"]],
    }}), encoding="utf-8")
    _write_config(root, signal_trace_path="sim/trace.json",
                  required_nonx_signals=["data"], pattern_completed=False)
    result = cc.run_connectivity_check(root, cc.load_config(root / cc.DEFAULT_CONFIG_RELPATH))
    assert result.gate_report.gate2.status == GateStatus.PASS


# ---- Gate 1 through the injected which/run seam -----------------------------

def test_gate1_runs_a_real_elaboration_invocation_through_the_injected_seam(tmp_path):
    root = _make_project(tmp_path)
    (root / "sim").mkdir()
    (root / "sim" / "files.f").write_text("rtl/dut.sv\n", encoding="utf-8")
    _write_config(root, filelists=["sim/files.f"], top_module="tb_top", pattern_completed=False)

    seen = {}

    def fake_which(name):
        return "/usr/bin/slang" if name == "slang" else None

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="bind target not found")

    result = cc.run_connectivity_check(
        root, cc.load_config(root / cc.DEFAULT_CONFIG_RELPATH),
        which_fn=fake_which, run_fn=fake_run)
    assert result.gate_report.gate1.status == GateStatus.FAIL
    assert seen["argv"][0] == "slang"
    assert "--top" in seen["argv"] and "tb_top" in seen["argv"]
    assert result.exit_code == cc.EXIT_GATE_FAIL


def test_gate1_not_available_without_a_tool_is_not_a_failure(tmp_path):
    root = _make_project(tmp_path)
    _write_config(root, pattern_completed=False)
    result = cc.run_connectivity_check(
        root, cc.load_config(root / cc.DEFAULT_CONFIG_RELPATH), which_fn=lambda _n: None)
    assert result.gate_report.gate1.status == GateStatus.NOT_AVAILABLE
    assert result.exit_code == cc.EXIT_OK
    assert "gate1_elaboration" in result.gate_report.not_available_gates()


# ---- The written report is lint-clean under the existing lint ---------------

def test_written_report_is_clean_under_bind_verification_lint(tmp_path):
    root = _make_project(tmp_path)
    _write_config(root, monitor_transaction_counts={"env.a.monitor": 1}, pattern_completed=True)
    assert cc.main(["--project-root", str(root)]) == cc.EXIT_OK
    report = root / cc.DEFAULT_REPORT_RELPATH
    text = report.read_text(encoding="utf-8")
    assert "## Bind Verification Status" in text
    assert lint_status_report_file(report) == []


def test_written_state_json_is_clean_under_bind_verification_lint(tmp_path):
    root = _make_project(tmp_path)
    _write_config(root, monitor_transaction_counts={"env.a.monitor": 1}, pattern_completed=True)
    assert cc.main(["--project-root", str(root)]) == cc.EXIT_OK
    # The state file embeds the block under "bind_verification_status", the
    # exact nesting extract_status_block_from_json() already understands.
    assert lint_status_report_file(root / cc.DEFAULT_STATE_RELPATH) == []


# ---- Config error handling --------------------------------------------------

def test_not_configured_is_an_honest_noop_for_check_only_but_an_error_for_a_run(tmp_path, capsys):
    root = _make_project(tmp_path)
    assert cc.main(["--project-root", str(root), "--check-only"]) == cc.EXIT_OK
    assert "NOT_CONFIGURED" in capsys.readouterr().out
    assert cc.main(["--project-root", str(root)]) == cc.EXIT_CONFIG_ERROR
    assert "CONFIG ERROR" in capsys.readouterr().out


def test_rtl_sources_matching_nothing_is_a_config_error_not_a_vacuous_pass(tmp_path, capsys):
    root = _make_project(tmp_path)
    _write_config(root, rtl_sources=["rtl/**/*.vhd"])
    assert cc.main(["--project-root", str(root), "--check-only"]) == cc.EXIT_CONFIG_ERROR
    assert "MATCHED_NOTHING" in capsys.readouterr().out
    assert cc.main(["--project-root", str(root)]) == cc.EXIT_CONFIG_ERROR


def test_config_without_rtl_sources_is_rejected(tmp_path):
    root = _make_project(tmp_path)
    p = root / cc.DEFAULT_CONFIG_RELPATH
    p.write_text(json.dumps({"top_module": "tb_top"}), encoding="utf-8")
    with pytest.raises(cc.ConnectivityCheckConfigError) as exc:
        cc.load_config(p)
    assert exc.value.reason == "CONNECTIVITY_CHECK_CONFIG_HAS_NO_RTL_SOURCES"


def test_unparseable_config_is_reported_not_crashed(tmp_path, capsys):
    root = _make_project(tmp_path)
    (root / cc.DEFAULT_CONFIG_RELPATH).write_text("{not json", encoding="utf-8")
    assert cc.main(["--project-root", str(root), "--check-only"]) == cc.EXIT_CONFIG_ERROR
    assert "UNPARSEABLE" in capsys.readouterr().out


# ---- The module is invocable exactly the way the justfile/CI invoke it ------

def test_module_is_runnable_as_python_m_and_reports_not_configured(tmp_path):
    """The justfile recipe and the CI step both shell out to
    `python -m dv_harness.connectivity_check`; this asserts that real
    invocation path works (not just the importable `main()`)."""
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["python", "-m", "dv_harness.connectivity_check",
         "--project-root", str(tmp_path), "--check-only"],
        cwd=str(repo_root), capture_output=True, text=True, timeout=120)
    assert proc.returncode == cc.EXIT_OK, proc.stderr
    assert "NOT_CONFIGURED" in proc.stdout
