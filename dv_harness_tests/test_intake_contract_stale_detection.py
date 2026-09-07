"""Tests for dv_harness/intake_contract_stale_detection.py -- section 18's
real STALE detector for `verification_intake_contract.py`'s own 13-state
lifecycle (2026-09-06), mirroring `loop_stale_detection.py`'s own proven
pattern for `LoopState.STALE`.

Everything here runs against REAL machinery: a REAL throwaway git repository
with real commits (so environment-moved staleness is derived from a real
`git diff` between two real SHAs, exactly the primitive `loop_stale_
detection.py`/`golden_scenario.py`/`signoff_export.py` already reuse for the
identical question at other layers), real plain JSON files on disk for
`config.json`, and real `VerificationIntakeContract` objects driven through
the real, unmodified `create_contract()`/`transition_contract()` -- never a
hand-shaped stand-in for either.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from dv_harness import intake_contract_stale_detection as icsd
from dv_harness import verification_intake_contract as vic

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")


def _git(root, *args, check=True):
    r = subprocess.run([GIT, *args], cwd=str(root), capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture()
def git_project(tmp_path):
    """A throwaway project: a real git repo holding a small RTL tree and a
    doc, with one initial commit."""
    root = tmp_path / "proj"
    (root / "rtl").mkdir(parents=True)
    (root / "doc").mkdir(parents=True)
    (root / "rtl" / "core.v").write_text(
        "module core(input clk, output reg q);\nalways @(posedge clk) q <= 1;\nendmodule\n",
        encoding="utf-8")
    (root / "doc" / "notes.md").write_text("# notes\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=T", "add", "-A")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=T",
         "commit", "-qm", "initial")
    return root


def _head_sha(root):
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _write_config(root, **policy):
    d = root / ".dv-harness"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"policy": policy}), encoding="utf-8")


def _iso(dt):
    return dt.isoformat()


def _baselined_contract(baselined_at=None, sub_domain_data=None, contract_id="c1"):
    """A real contract driven CREATED -> ... -> BASELINED through the real
    `create_contract()`/`transition_contract()` machinery -- never a
    hand-assembled `state_history`."""
    c = vic.create_contract(contract_id, now=_iso(datetime.now(timezone.utc) - timedelta(days=30)))
    c = vic.transition_contract(c, "DISCOVERING", reason="start discovery",
                                now=_iso(datetime.now(timezone.utc) - timedelta(days=29)))
    c = vic.transition_contract(c, "CORRELATING", reason="correlate",
                                now=_iso(datetime.now(timezone.utc) - timedelta(days=28)))
    c = vic.transition_contract(c, "VALIDATING", reason="validate",
                                now=_iso(datetime.now(timezone.utc) - timedelta(days=27)))
    c = vic.transition_contract(c, "READY_FOR_REVIEW", reason="ready",
                                now=_iso(datetime.now(timezone.utc) - timedelta(days=26)))
    at = _iso(baselined_at) if baselined_at else _iso(datetime.now(timezone.utc) - timedelta(days=25))
    c = vic.transition_contract(c, "BASELINED", reason="approved", by="reviewer1", now=at,
                                sub_domain_data=sub_domain_data)
    return c


# --------------------------------------------------------------------------
# declared_intake_stale_window_seconds(): never mints a file
# --------------------------------------------------------------------------
def test_read_json_file_absent_returns_none_and_creates_nothing(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    assert icsd._read_json_file(root / ".dv-harness" / "config.json") is None
    assert not (root / ".dv-harness").exists(), (
        "reading a bare project's absent config.json must never mint a .dv-harness/ tree")


def test_declared_window_falls_back_to_default_when_undeclared(tmp_path):
    seconds, source = icsd.declared_intake_stale_window_seconds(tmp_path)
    assert seconds == icsd.DEFAULT_INTAKE_STALE_AFTER_SECONDS
    assert "DEFAULT_INTAKE_STALE_AFTER_SECONDS" in source


def test_declared_window_reads_real_config(tmp_path):
    _write_config(tmp_path, intake_stale_after_seconds=90)
    seconds, source = icsd.declared_intake_stale_window_seconds(tmp_path)
    assert seconds == 90.0
    assert "policy.intake_stale_after_seconds" in source


def test_declared_window_ignores_a_non_positive_or_bool_declaration(tmp_path):
    _write_config(tmp_path, intake_stale_after_seconds=-5)
    seconds, _ = icsd.declared_intake_stale_window_seconds(tmp_path)
    assert seconds == icsd.DEFAULT_INTAKE_STALE_AFTER_SECONDS
    _write_config(tmp_path, intake_stale_after_seconds=True)
    seconds, _ = icsd.declared_intake_stale_window_seconds(tmp_path)
    assert seconds == icsd.DEFAULT_INTAKE_STALE_AFTER_SECONDS


# --------------------------------------------------------------------------
# last_baselined_event(): real state_history, never invented
# --------------------------------------------------------------------------
def test_last_baselined_event_reports_no_evidence_for_a_never_baselined_contract():
    c = vic.create_contract("c0")
    ev = icsd.last_baselined_event(c)
    assert ev.timestamp is None
    assert ev.source == "NO_REAL_BASELINE_EVENT_EVIDENCE"


def test_last_baselined_event_reads_the_real_transition():
    at = datetime.now(timezone.utc) - timedelta(hours=1)
    ts = _iso(at)
    c = _baselined_contract(baselined_at=at)
    ev = icsd.last_baselined_event(c)
    assert ev.timestamp == ts
    assert ev.source == "state_history_baselined_transition"
    assert ev.detail["by"] == "reviewer1"


def test_last_baselined_event_prefers_the_most_recent_of_two_real_baselinings():
    older = datetime.now(timezone.utc) - timedelta(days=10)
    c = _baselined_contract(baselined_at=older)
    # A real re-baseline cycle: BASELINED -> STALE -> REVALIDATING -> BASELINED again.
    c = vic.transition_contract(c, "STALE", reason="env moved",
                                now=_iso(datetime.now(timezone.utc) - timedelta(days=5)))
    c = vic.transition_contract(c, "REVALIDATING", reason="revalidate",
                                now=_iso(datetime.now(timezone.utc) - timedelta(days=4)))
    newer = datetime.now(timezone.utc) - timedelta(hours=2)
    c = vic.transition_contract(c, "BASELINED", reason="re-approved", now=_iso(newer))
    ev = icsd.last_baselined_event(c)
    assert ev.timestamp == _iso(newer)
    assert ev.detail["reason"] == "re-approved"


# --------------------------------------------------------------------------
# detect_time_based_staleness(): the honest three-way split
# --------------------------------------------------------------------------
def test_time_based_staleness_unknown_for_a_never_baselined_contract(tmp_path):
    c = vic.create_contract("c0")
    report = icsd.detect_time_based_staleness(c, tmp_path)
    assert report["status"] == icsd.UNKNOWN
    assert "NO_REAL_BASELINE_EVENT_EVIDENCE" in report["reason"]


def test_time_based_staleness_not_stale_when_recently_baselined(tmp_path):
    c = _baselined_contract(baselined_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    report = icsd.detect_time_based_staleness(c, tmp_path, staleness_window_seconds=3600)
    assert report["status"] == icsd.NOT_STALE
    assert report["window_seconds"] == 3600


def test_time_based_staleness_stale_when_older_than_declared_window(tmp_path):
    c = _baselined_contract(baselined_at=datetime.now(timezone.utc) - timedelta(hours=2))
    report = icsd.detect_time_based_staleness(c, tmp_path, staleness_window_seconds=3600)
    assert report["status"] == icsd.STALE
    assert "exceeding the declared" in report["reason"]


# --------------------------------------------------------------------------
# detect_environment_moved_staleness(): the real git-diff signal
# --------------------------------------------------------------------------
def test_environment_moved_unknown_with_no_recorded_sha(git_project):
    c = _baselined_contract()
    report = icsd.detect_environment_moved_staleness(c, git_project)
    assert report["status"] == icsd.UNKNOWN
    assert "NO_RECORDED_SHA" in report["reason"]


@requires_git
def test_environment_moved_reads_sha_from_sub_domains_convention(git_project):
    base = _head_sha(git_project)
    c = _baselined_contract(sub_domain_data={"baseline_git_sha": base})
    report = icsd.detect_environment_moved_staleness(c, git_project)
    assert report["status"] == icsd.NOT_STALE
    assert report["recorded_sha_source"] == "sub_domains.baseline_git_sha"
    assert "NO_CHANGE_SINCE_RECORDED_SHA" in report["reason"]


@requires_git
def test_environment_moved_caller_supplied_sha_wins_over_sub_domains(git_project):
    base = _head_sha(git_project)
    c = _baselined_contract(sub_domain_data={"baseline_git_sha": "deadbeef"})
    report = icsd.detect_environment_moved_staleness(c, git_project, recorded_sha=base)
    assert report["recorded_sha_source"] == "caller-supplied"
    assert report["recorded_sha"] == base


@requires_git
def test_environment_moved_stale_after_a_real_high_risk_rtl_commit(git_project):
    base = _head_sha(git_project)
    c = _baselined_contract(sub_domain_data={"baseline_git_sha": base})
    (git_project / "rtl" / "core.v").write_text(
        "module core(input clk, output reg q);\nalways @(posedge clk) q <= 0;\nendmodule\n",
        encoding="utf-8")
    _commit(git_project, "change reset polarity")
    report = icsd.detect_environment_moved_staleness(c, git_project)
    assert report["status"] == icsd.STALE
    assert "rtl/core.v" in report["changed_files"]
    assert report["risk_by_file"]["rtl/core.v"] == "HIGH"


@requires_git
def test_environment_moved_not_stale_when_only_low_risk_files_changed(git_project):
    base = _head_sha(git_project)
    c = _baselined_contract(sub_domain_data={"baseline_git_sha": base})
    (git_project / "doc" / "notes.md").write_text("# notes v2\n", encoding="utf-8")
    _commit(git_project, "update notes")
    report = icsd.detect_environment_moved_staleness(c, git_project)
    assert report["status"] == icsd.NOT_STALE
    assert "LOW risk" in report["reason"]


def test_environment_moved_unknown_when_git_itself_is_unavailable(tmp_path):
    # A recorded SHA exists but this is not a git repository at all --
    # change_impact.changed_files() reports NO_GIT, which must propagate as
    # UNKNOWN, never be silently read as "nothing moved".
    c = _baselined_contract(sub_domain_data={"baseline_git_sha": "deadbeef"})
    report = icsd.detect_environment_moved_staleness(c, tmp_path)
    assert report["status"] == icsd.UNKNOWN
    assert report["diff_status"] in ("NO_GIT", "UNKNOWN_BASE")


# --------------------------------------------------------------------------
# detect_intake_contract_staleness(): worst-wins over the two real signals
# --------------------------------------------------------------------------
@requires_git
def test_combined_stale_wins_when_either_signal_is_stale(git_project):
    base = _head_sha(git_project)
    c = _baselined_contract(baselined_at=datetime.now(timezone.utc),
                            sub_domain_data={"baseline_git_sha": base})
    (git_project / "rtl" / "core.v").write_text("module core(); endmodule\n", encoding="utf-8")
    _commit(git_project, "gut the module")
    report = icsd.detect_intake_contract_staleness(c, git_project, staleness_window_seconds=999999)
    assert report["status"] == icsd.STALE
    assert report["is_stale"] is True
    kinds = {s["signal"] for s in report["signals"] if s["status"] == icsd.STALE}
    assert kinds == {icsd.SIGNAL_ENVIRONMENT_MOVED}


@requires_git
def test_combined_not_stale_when_both_signals_are_clean(git_project):
    base = _head_sha(git_project)
    c = _baselined_contract(baselined_at=datetime.now(timezone.utc),
                            sub_domain_data={"baseline_git_sha": base})
    report = icsd.detect_intake_contract_staleness(c, git_project, staleness_window_seconds=999999)
    assert report["status"] == icsd.NOT_STALE
    assert report["is_stale"] is False


def test_combined_unknown_never_fabricated_as_not_stale_on_a_never_baselined_contract(tmp_path):
    """The mandated negative control: a fresh, never-baselined contract in a
    bare project with no git repository at all -- BOTH real signals
    genuinely have nothing to measure against. The combined verdict must be
    UNKNOWN, never a fabricated NOT_STALE -- "we could not check" is not "we
    checked and it is fine"."""
    root = tmp_path / "bare_project"
    root.mkdir()
    c = vic.create_contract("never_baselined")
    report = icsd.detect_intake_contract_staleness(c, root)
    assert report["status"] == icsd.UNKNOWN
    assert report["is_stale"] is False
    assert {s["status"] for s in report["signals"]} == {icsd.UNKNOWN}
    # And, per the module's own read-only contract, nothing was minted.
    assert not (root / ".dv-harness").exists()


@requires_git
def test_combined_unknown_when_one_signal_unresolved_and_neither_stale(git_project):
    # No recorded git_sha at all (ENVIRONMENT_MOVED -> UNKNOWN), but a real,
    # recent BASELINED transition (TIME_BASED -> NOT_STALE). Neither is
    # STALE, so the honest overall verdict is UNKNOWN, not NOT_STALE.
    c = _baselined_contract(baselined_at=datetime.now(timezone.utc))
    report = icsd.detect_intake_contract_staleness(c, git_project, staleness_window_seconds=999999)
    assert report["status"] == icsd.UNKNOWN
    assert report["is_stale"] is False


# --------------------------------------------------------------------------
# apply_stale_transition() / detect_and_maybe_transition(): the real,
# enforced move into STALE -- never a fabricated state mutation
# --------------------------------------------------------------------------
def test_apply_stale_transition_refuses_a_non_stale_report():
    c = _baselined_contract()
    clean = {"status": icsd.NOT_STALE, "is_stale": False, "signals": []}
    with pytest.raises(vic.IntakeContractError) as ei:
        icsd.apply_stale_transition(c, clean)
    assert ei.value.reason == "STALENESS_REPORT_DOES_NOT_SAY_STALE"
    # Never mutated the contract it refused to act on.
    assert c.state == "BASELINED"


def test_apply_stale_transition_drives_a_real_legal_move_into_stale():
    c = _baselined_contract()
    stale_report = {
        "status": icsd.STALE, "is_stale": True,
        "signals": [{"signal": icsd.SIGNAL_TIME_BASED, "status": icsd.STALE,
                    "reason": "old baseline"}],
    }
    new_c = icsd.apply_stale_transition(c, stale_report, by="auto-detector")
    assert new_c.state == "STALE"
    # The original contract, per transition_contract()'s own immutability
    # contract, is untouched.
    assert c.state == "BASELINED"
    last = new_c.state_history[-1]
    assert last["from"] == "BASELINED"
    assert last["to"] == "STALE"
    assert last["by"] == "auto-detector"
    assert "TIME_BASED: old baseline" in last["reason"]
    # STALE has a real, legal way out too -- section 18's own "every state
    # has a real outgoing edge" guarantee, exercised here.
    revalidating = vic.transition_contract(new_c, "REVALIDATING", reason="begin revalidation")
    assert revalidating.state == "REVALIDATING"


def test_apply_stale_transition_refuses_when_the_contract_is_not_baselined():
    # assert_legal_transition() is never bypassed by this module: a contract
    # that never reached BASELINED (e.g. still CREATED) has no legal STALE
    # edge, and this module must not invent one.
    c = vic.create_contract("not_baselined_yet")
    stale_report = {"status": icsd.STALE, "is_stale": True, "signals": []}
    with pytest.raises(vic.IntakeContractError) as ei:
        icsd.apply_stale_transition(c, stale_report)
    assert ei.value.reason == "ILLEGAL_STATE_TRANSITION"


@requires_git
def test_detect_and_maybe_transition_applies_only_when_evidence_says_stale(git_project):
    base = _head_sha(git_project)
    c = _baselined_contract(baselined_at=datetime.now(timezone.utc),
                            sub_domain_data={"baseline_git_sha": base})
    (git_project / "rtl" / "core.v").write_text("module core(); endmodule\n", encoding="utf-8")
    _commit(git_project, "gut the module")
    report, new_c = icsd.detect_and_maybe_transition(
        c, git_project, staleness_window_seconds=999999)
    assert report["status"] == icsd.STALE
    assert new_c is not None
    assert new_c.state == "STALE"


@requires_git
def test_detect_and_maybe_transition_makes_no_move_when_not_stale(git_project):
    base = _head_sha(git_project)
    c = _baselined_contract(baselined_at=datetime.now(timezone.utc),
                            sub_domain_data={"baseline_git_sha": base})
    report, new_c = icsd.detect_and_maybe_transition(
        c, git_project, staleness_window_seconds=999999)
    assert report["status"] == icsd.NOT_STALE
    assert new_c is None


@requires_git
def test_detect_and_maybe_transition_never_moves_a_contract_already_past_baselined(git_project):
    # STALE evidence exists, but the contract already left BASELINED (a
    # human already moved it on) -- detect_and_maybe_transition() must
    # never drag it back into STALE from underneath that decision.
    base = _head_sha(git_project)
    c = _baselined_contract(baselined_at=datetime.now(timezone.utc) - timedelta(days=100),
                            sub_domain_data={"baseline_git_sha": base})
    c = vic.transition_contract(c, "STALE", reason="already handled by a human")
    report, new_c = icsd.detect_and_maybe_transition(c, git_project, staleness_window_seconds=1)
    assert report["status"] == icsd.STALE
    assert new_c is None


# --------------------------------------------------------------------------
# CLI front door
# --------------------------------------------------------------------------
def test_cli_window_verb(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_contract_stale_detection", "window",
         "--project-root", str(tmp_path)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["window_seconds"] == icsd.DEFAULT_INTAKE_STALE_AFTER_SECONDS


def test_cli_detect_verb_requires_a_contract(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_contract_stale_detection", "detect",
         "--project-root", str(tmp_path)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["error"] == "MISSING_CONTRACT"


@requires_git
def test_cli_detect_verb_not_stale_and_stale(tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "f.txt").write_text("x", encoding="utf-8")
    _git(fresh, "init", "-q")
    _git(fresh, "-c", "user.email=t@example.com", "-c", "user.name=T", "add", "-A")
    _git(fresh, "-c", "user.email=t@example.com", "-c", "user.name=T",
         "commit", "-qm", "initial")
    sha = _head_sha(fresh)
    c = _baselined_contract(baselined_at=datetime.now(timezone.utc),
                            sub_domain_data={"baseline_git_sha": sha})
    contract_file = tmp_path / "contract.json"
    contract_file.write_text(json.dumps(c.to_dict()), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_contract_stale_detection", "detect",
         "--project-root", str(fresh), "--contract", str(contract_file),
         "--window-seconds", "999999"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] == icsd.NOT_STALE

    old_contract = _baselined_contract(baselined_at=datetime.now(timezone.utc) - timedelta(hours=10),
                                       sub_domain_data={"baseline_git_sha": sha})
    old_file = tmp_path / "old_contract.json"
    old_file.write_text(json.dumps(old_contract.to_dict()), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_contract_stale_detection", "detect",
         "--project-root", str(fresh), "--contract", str(old_file), "--window-seconds", "60"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] == icsd.STALE


def test_cli_detect_verb_bad_contract_file(tmp_path):
    bad = tmp_path / "notjson.json"
    bad.write_text("{not json", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_contract_stale_detection", "detect",
         "--project-root", str(tmp_path), "--contract", str(bad)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["error"] == "CONTRACT_LOAD_FAILED"


def test_execute_verb_unknown_verb(tmp_path):
    code, payload = icsd.execute_verb(tmp_path, "bogus")
    assert code == 1
    assert payload["error"] == "UNKNOWN_VERB"


def test_load_contract_json_round_trips(tmp_path):
    c = _baselined_contract()
    p = tmp_path / "c.json"
    p.write_text(json.dumps(c.to_dict()), encoding="utf-8")
    loaded = icsd.load_contract_json(p)
    assert loaded.contract_id == c.contract_id
    assert loaded.state == c.state
    assert loaded.sub_domains == c.sub_domains
    assert len(loaded.state_history) == len(c.state_history)
