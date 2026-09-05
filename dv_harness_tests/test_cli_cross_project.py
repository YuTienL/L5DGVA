"""Tests for the `dv-harness cross-project ...` subcommand group (VI-2).

Runs `dv_harness.cli.main()` in-process against fresh --project-root tmp
directories, the same monkeypatched-sys.argv pattern
dv_harness_tests/test_cli_question_queue.py and test_cli_memory_commands.py
already use. Every project the CLI mines here is a real memory store populated
through the real `memory_router.route_and_store()`.
"""
from __future__ import annotations

import json
import shutil
import sys

import dv_harness.cli as cli_mod
from dv_harness import cross_project_mining as cpm
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import route_and_store
from dv_harness.memory_vault import build_failure_signature

SYMPTOM = "AXI write response never returns on slave port 2"
CAUSE = "wready deasserted while the interconnect held wvalid"


def _run_cli(monkeypatch, root, args, capsys):
    monkeypatch.setattr(sys, "argv", ["dv-harness", "--project-root", str(root)] + args)
    try:
        rc = cli_mod.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    return (rc if rc is not None else 0), out


def _project(base, name):
    root = base / name
    root.mkdir(parents=True, exist_ok=True)
    MemoryStore(root)
    return root


def _job_failure(root, *, git_sha):
    sig = build_failure_signature(protocol="AMBA4", symptom=SYMPTOM, root_cause_hint=CAUSE)
    routed = route_and_store(root, {
        "kind": "job_failure", "scope": "debug", "title": "RE_AUDIT did not close",
        "stage": "RE_AUDIT", "attempt": 1, "status": "PARTIAL",
        "blocking_reason": "GATE_FAIL: root_cause_evidence_gate",
        "failure_signature": sig, "protocol": "AMBA4", "git_sha": git_sha,
    }, cfg={})
    assert routed["destination"] == "JOB_MEMORY", routed
    return sig


def _verified_fix(root):
    routed = route_and_store(root, {
        "kind": "verified_fix", "verified": True, "scope": "engineering",
        "title": f"Verified fix: {CAUSE}", "symptoms": [SYMPTOM], "root_cause": CAUSE,
        "fix": "rtl commit 5e1f00d", "evidence": ["sim.log:9120"], "reusable": True,
        "verification": {"targeted_reproducer_passed": True,
                         "broader_regression_passed": True,
                         "new_failures_introduced": False},
        "confidence": "HIGH", "protocol": "AMBA4",
    }, cfg={})
    assert routed["destination"] == "ENGINEERING_MEMORY", routed
    return routed


def test_status_and_list_start_honest_and_empty(monkeypatch, tmp_path, capsys):
    host = _project(tmp_path, "host")
    rc, out = _run_cli(monkeypatch, host, ["cross-project", "status"], capsys)
    assert rc == 0
    status = json.loads(out)
    assert status["registered_project_count"] == 0
    assert status["can_produce_cross_project_result"] is False

    rc, out = _run_cli(monkeypatch, host, ["cross-project", "list"], capsys)
    assert rc == 0 and json.loads(out)["projects"] == []


def test_register_list_unregister_round_trip(monkeypatch, tmp_path, capsys):
    host = _project(tmp_path, "host")
    a = _project(tmp_path, "proj_a")
    _job_failure(a, git_sha="a-1")

    rc, out = _run_cli(monkeypatch, host, ["cross-project", "register", str(a), "--id", "A"], capsys)
    assert rc == 0 and json.loads(out)["registered"]["project_id"] == "A"

    rc, out = _run_cli(monkeypatch, host, ["cross-project", "list"], capsys)
    assert [p["project_id"] for p in json.loads(out)["projects"]] == ["A"]

    rc, out = _run_cli(monkeypatch, host, ["cross-project", "unregister", "A"], capsys)
    assert rc == 0 and json.loads(out)["ok"] is True
    rc, out = _run_cli(monkeypatch, host, ["cross-project", "unregister", "A"], capsys)
    assert rc == 1 and json.loads(out)["ok"] is False


def test_register_reports_a_refusal_instead_of_crashing(monkeypatch, tmp_path, capsys):
    """A copied project store is one project under two names. The CLI reports
    the refusal as data and exits 1 -- it does not traceback, and it does not
    quietly succeed."""
    host = _project(tmp_path, "host")
    a = _project(tmp_path, "proj_a")
    _job_failure(a, git_sha="a-1")
    clone = tmp_path / "proj_a_copy"
    shutil.copytree(a, clone)

    assert _run_cli(monkeypatch, host, ["cross-project", "register", str(a), "--id", "A"], capsys)[0] == 0
    rc, out = _run_cli(monkeypatch, host,
                       ["cross-project", "register", str(clone), "--id", "B"], capsys)
    assert rc == 1
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"] == "ProjectIdentityCollisionError"
    assert "one store under two names" in payload["message"]


def test_mine_finds_a_transferable_fix_across_two_registered_projects(monkeypatch, tmp_path, capsys):
    host = _project(tmp_path, "host")
    a, b = _project(tmp_path, "proj_a"), _project(tmp_path, "proj_b")
    _job_failure(a, git_sha="a-1")
    fix = _verified_fix(a)          # A closed it, gate-verified
    _job_failure(b, git_sha="b-1")  # B still has it open

    for pid, root in (("A", a), ("B", b)):
        assert _run_cli(monkeypatch, host,
                        ["cross-project", "register", str(root), "--id", pid], capsys)[0] == 0

    rc, out = _run_cli(monkeypatch, host, ["cross-project", "mine"], capsys)
    assert rc == 0
    report = json.loads(out)
    assert report["status"] == cpm.STATUS_OK
    assert len(report["cross_project_patterns"]) == 1
    pattern = report["cross_project_patterns"][0]
    assert pattern["project_ids"] == ["A", "B"]
    assert pattern["transferable_fix"]["fixed_in"] == ["A"]
    assert pattern["transferable_fix"]["open_in"] == ["B"]
    assert [f["memory_id"] for f in pattern["transferable_fix"]["fix_records"]] == [fix["memory_id"]]

    # And status now agrees that a real result is producible here.
    rc, out = _run_cli(monkeypatch, host, ["cross-project", "status"], capsys)
    assert json.loads(out)["can_produce_cross_project_result"] is True


def test_mine_with_one_project_exits_zero_and_says_why(monkeypatch, tmp_path, capsys):
    """A completed pass that found nothing is not a command failure -- the
    honest answer is about the sample, so it exits 0 and says so."""
    host = _project(tmp_path, "host")
    a = _project(tmp_path, "proj_a")
    _job_failure(a, git_sha="a-1")
    _run_cli(monkeypatch, host, ["cross-project", "register", str(a), "--id", "A"], capsys)

    rc, out = _run_cli(monkeypatch, host, ["cross-project", "mine"], capsys)
    assert rc == 0
    report = json.loads(out)
    assert report["status"] == cpm.STATUS_INSUFFICIENT_PROJECTS
    assert report["cross_project_patterns"] == []
    assert "NO cross-project pattern is reported" in report["disclosure"]


def test_mine_rejects_a_min_projects_below_two(monkeypatch, tmp_path, capsys):
    host = _project(tmp_path, "host")
    rc, out = _run_cli(monkeypatch, host, ["cross-project", "mine", "--min-projects", "1"], capsys)
    assert rc == 1
    assert "must be at least 2" in json.loads(out)["message"]


def test_the_cli_promotes_nothing(monkeypatch, tmp_path, capsys):
    """The whole command group is a read. After a mine that found a pattern
    eligible for promotion REVIEW, no organizational record exists anywhere."""
    host = _project(tmp_path, "host")
    a, b = _project(tmp_path, "proj_a"), _project(tmp_path, "proj_b")
    _job_failure(a, git_sha="a-1")
    _verified_fix(a)
    _job_failure(b, git_sha="b-1")
    for pid, root in (("A", a), ("B", b)):
        _run_cli(monkeypatch, host, ["cross-project", "register", str(root), "--id", pid], capsys)

    _, out = _run_cli(monkeypatch, host, ["cross-project", "mine"], capsys)
    pattern = json.loads(out)["cross_project_patterns"][0]
    assert pattern["promotion_readiness"]["eligible_for_promotion_review"] is True
    for root in (host, a, b):
        assert MemoryStore(root).find("organizational") == []
