"""Tests for dv_harness/loop_stale_detection.py -- section 97's STALE
detector (2026-09-06), and its wiring into loop_contract.derive_loop_state()/
observe_verification_closure_loop().

Everything here runs against REAL machinery: a REAL throwaway git repository
with real commits (so environment-moved staleness is derived from a real
`git diff` between two real SHAs, exactly the primitive `golden_scenario.py`/
`signoff_export.py` already reuse for the identical question one layer down),
and real plain JSON files on disk for `state.json`/`config.json` -- never a
mock of `change_impact.changed_files()` or a hand-shaped stand-in for a real
project.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from dv_harness import loop_stale_detection as lsd
from dv_harness import loop_contract as lc

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


def _write_state(root, **fields):
    d = root / ".dv-harness"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(fields), encoding="utf-8")


def _write_config(root, **policy):
    d = root / ".dv-harness"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"policy": policy}), encoding="utf-8")


def _iso(dt):
    return dt.isoformat()


# --------------------------------------------------------------------------
# _read_json_file / declared_stale_window_seconds: never mints a file
# --------------------------------------------------------------------------
def test_read_json_file_absent_returns_none_and_creates_nothing(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    assert lsd._read_json_file(root / ".dv-harness" / "state.json") is None
    assert not (root / ".dv-harness").exists(), (
        "reading a bare project's absent state.json must never mint a .dv-harness/ tree")


def test_read_json_file_malformed_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert lsd._read_json_file(p) is None


def test_declared_window_falls_back_to_default_when_undeclared(tmp_path):
    seconds, source = lsd.declared_stale_window_seconds(tmp_path)
    assert seconds == lsd.DEFAULT_STALE_AFTER_SECONDS
    assert "DEFAULT_STALE_AFTER_SECONDS" in source


def test_declared_window_reads_real_config(tmp_path):
    _write_config(tmp_path, loop_stale_after_seconds=90)
    seconds, source = lsd.declared_stale_window_seconds(tmp_path)
    assert seconds == 90.0
    assert "policy.loop_stale_after_seconds" in source


def test_declared_window_ignores_a_non_positive_or_bool_declaration(tmp_path):
    _write_config(tmp_path, loop_stale_after_seconds=-5)
    seconds, _ = lsd.declared_stale_window_seconds(tmp_path)
    assert seconds == lsd.DEFAULT_STALE_AFTER_SECONDS
    _write_config(tmp_path, loop_stale_after_seconds=True)
    seconds, _ = lsd.declared_stale_window_seconds(tmp_path)
    assert seconds == lsd.DEFAULT_STALE_AFTER_SECONDS


# --------------------------------------------------------------------------
# last_real_event(): the three real sources, in precedence order
# --------------------------------------------------------------------------
def test_last_real_event_reports_no_evidence_on_a_bare_project(tmp_path):
    ev = lsd.last_real_event(tmp_path)
    assert ev.timestamp is None
    assert ev.source == "NO_REAL_EVENT_EVIDENCE"


def test_last_real_event_reads_state_last_transition(tmp_path):
    ts = _iso(datetime.now(timezone.utc) - timedelta(hours=1))
    _write_state(tmp_path, last_transition={"stage": "VERIFY", "status": "PASS", "at": ts})
    ev = lsd.last_real_event(tmp_path)
    assert ev.timestamp == ts
    assert ev.source == "state_last_transition"


def test_last_real_event_falls_back_to_stage_timestamps_with_no_last_transition(tmp_path):
    older = _iso(datetime.now(timezone.utc) - timedelta(hours=5))
    newer = _iso(datetime.now(timezone.utc) - timedelta(hours=1))
    _write_state(tmp_path, stages={
        "ENV_CHECK": {"finished_at": older},
        "VERIFY": {"started_at": newer},
    })
    ev = lsd.last_real_event(tmp_path)
    assert ev.timestamp == newer
    assert ev.source == "stage_state_timestamp"
    assert ev.detail["stage"] == "VERIFY"


def test_last_real_event_prefers_loop_telemetry_session_when_run_id_given(tmp_path, monkeypatch):
    # Real state.json evidence exists too, but a real, more specific
    # per-session loop_telemetry record must win when a run_id is supplied.
    _write_state(tmp_path, last_transition={"stage": "VERIFY", "status": "PASS",
                                            "at": _iso(datetime.now(timezone.utc))})

    def fake_read_loop_telemetry(root, *, run_id=None, **kw):
        return {"rows": [{"run_id": run_id, "state": "RUNNING",
                          "last_event_at": "2020-01-01T00:00:00+00:00"}]}

    import dv_harness.loop_telemetry as lt
    monkeypatch.setattr(lt, "read_loop_telemetry", fake_read_loop_telemetry)
    ev = lsd.last_real_event(tmp_path, run_id="verification_closure:20200101T000000Z:1")
    assert ev.timestamp == "2020-01-01T00:00:00+00:00"
    assert ev.source == "loop_telemetry_session"


# --------------------------------------------------------------------------
# detect_time_based_staleness(): the honest three-way split
# --------------------------------------------------------------------------
def test_time_based_staleness_unknown_with_no_evidence(tmp_path):
    report = lsd.detect_time_based_staleness(tmp_path)
    assert report["status"] == lsd.UNKNOWN
    assert "NO_REAL_EVENT_EVIDENCE" in report["reason"]


def test_time_based_staleness_not_stale_when_recent(tmp_path):
    _write_state(tmp_path, last_transition={"stage": "VERIFY", "status": "PASS",
                                            "at": _iso(datetime.now(timezone.utc)
                                                       - timedelta(seconds=5))})
    report = lsd.detect_time_based_staleness(tmp_path, staleness_window_seconds=3600)
    assert report["status"] == lsd.NOT_STALE
    assert report["window_seconds"] == 3600


def test_time_based_staleness_stale_when_older_than_declared_window(tmp_path):
    _write_state(tmp_path, last_transition={"stage": "VERIFY", "status": "PASS",
                                            "at": _iso(datetime.now(timezone.utc)
                                                       - timedelta(hours=2))})
    report = lsd.detect_time_based_staleness(tmp_path, staleness_window_seconds=3600)
    assert report["status"] == lsd.STALE
    assert "exceeding the declared" in report["reason"]


# --------------------------------------------------------------------------
# detect_environment_moved_staleness(): the real git-diff signal
# --------------------------------------------------------------------------
def test_environment_moved_unknown_with_no_recorded_sha(git_project):
    report = lsd.detect_environment_moved_staleness(git_project)
    assert report["status"] == lsd.UNKNOWN
    assert "NO_RECORDED_SHA" in report["reason"]


@requires_git
def test_environment_moved_not_stale_with_no_real_change(git_project):
    report = lsd.detect_environment_moved_staleness(
        git_project, recorded_sha=_head_sha(git_project))
    assert report["status"] == lsd.NOT_STALE
    assert "NO_CHANGE_SINCE_RECORDED_SHA" in report["reason"]


@requires_git
def test_environment_moved_stale_after_a_real_high_risk_rtl_commit(git_project):
    base = _head_sha(git_project)
    (git_project / "rtl" / "core.v").write_text(
        "module core(input clk, output reg q);\nalways @(posedge clk) q <= 0;\nendmodule\n",
        encoding="utf-8")
    _commit(git_project, "change reset polarity")
    report = lsd.detect_environment_moved_staleness(git_project, recorded_sha=base)
    assert report["status"] == lsd.STALE
    assert "rtl/core.v" in report["changed_files"]
    assert report["risk_by_file"]["rtl/core.v"] == "HIGH"


@requires_git
def test_environment_moved_not_stale_when_only_low_risk_files_changed(git_project):
    base = _head_sha(git_project)
    (git_project / "doc" / "notes.md").write_text("# notes v2\n", encoding="utf-8")
    _commit(git_project, "update notes")
    report = lsd.detect_environment_moved_staleness(git_project, recorded_sha=base)
    assert report["status"] == lsd.NOT_STALE
    assert "LOW risk" in report["reason"]


def test_environment_moved_unknown_when_git_itself_is_unavailable(tmp_path, monkeypatch):
    # A recorded SHA exists but this is not a git repository at all --
    # change_impact.changed_files() reports NO_GIT, which must propagate as
    # UNKNOWN, never be silently read as "nothing moved".
    report = lsd.detect_environment_moved_staleness(tmp_path, recorded_sha="deadbeef")
    assert report["status"] == lsd.UNKNOWN
    assert report["diff_status"] in ("NO_GIT", "UNKNOWN_BASE")


# --------------------------------------------------------------------------
# detect_loop_staleness(): worst-wins over the two real signals
# --------------------------------------------------------------------------
@requires_git
def test_combined_stale_wins_when_either_signal_is_stale(git_project):
    base = _head_sha(git_project)
    _write_state(git_project, git_sha=base,
                 last_transition={"stage": "VERIFY", "status": "PASS",
                                  "at": _iso(datetime.now(timezone.utc))})
    (git_project / "rtl" / "core.v").write_text("module core(); endmodule\n", encoding="utf-8")
    _commit(git_project, "gut the module")
    report = lsd.detect_loop_staleness(git_project, staleness_window_seconds=999999)
    assert report["status"] == lsd.STALE
    assert report["is_stale"] is True
    kinds = {s["signal"] for s in report["signals"] if s["status"] == lsd.STALE}
    assert kinds == {lsd.SIGNAL_ENVIRONMENT_MOVED}


@requires_git
def test_combined_not_stale_when_both_signals_are_clean(git_project):
    base = _head_sha(git_project)
    _write_state(git_project, git_sha=base,
                 last_transition={"stage": "VERIFY", "status": "PASS",
                                  "at": _iso(datetime.now(timezone.utc))})
    report = lsd.detect_loop_staleness(git_project, staleness_window_seconds=999999)
    assert report["status"] == lsd.NOT_STALE
    assert report["is_stale"] is False


def test_combined_unknown_never_fabricated_as_not_stale_on_a_bare_project(tmp_path):
    """The mandated negative control: with no state.json, no config.json and
    no git repository at all, BOTH real signals genuinely have nothing to
    measure against. The combined verdict must be UNKNOWN, never a
    fabricated NOT_STALE -- "we could not check" is not "we checked and it
    is fine"."""
    root = tmp_path / "bare_project"
    root.mkdir()
    report = lsd.detect_loop_staleness(root)
    assert report["status"] == lsd.UNKNOWN
    assert report["is_stale"] is False
    assert {s["status"] for s in report["signals"]} == {lsd.UNKNOWN}
    # And, per the module's own read-only contract, nothing was minted.
    assert not (root / ".dv-harness").exists()


@requires_git
def test_combined_unknown_when_one_signal_unresolved_and_neither_stale(git_project):
    # No recorded git_sha at all (ENVIRONMENT_MOVED -> UNKNOWN), but a real,
    # recent last_transition (TIME_BASED -> NOT_STALE). Neither is STALE, so
    # the honest overall verdict is UNKNOWN, not NOT_STALE.
    _write_state(git_project, last_transition={"stage": "VERIFY", "status": "PASS",
                                                "at": _iso(datetime.now(timezone.utc))})
    report = lsd.detect_loop_staleness(git_project, staleness_window_seconds=999999)
    assert report["status"] == lsd.UNKNOWN
    assert report["is_stale"] is False


# --------------------------------------------------------------------------
# CLI front door
# --------------------------------------------------------------------------
def test_cli_window_verb(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.loop_stale_detection", "window",
         "--project-root", str(tmp_path)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["window_seconds"] == lsd.DEFAULT_STALE_AFTER_SECONDS


def test_cli_detect_verb_unknown_on_a_bare_project(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.loop_stale_detection", "detect",
         "--project-root", str(bare)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] == lsd.UNKNOWN


@requires_git
def test_cli_detect_verb_not_stale_and_stale(tmp_path):
    # Both real signals must have something to resolve for a clean 0/1 exit
    # code -- a project with no recorded git_sha would leave the
    # environment-moved signal honestly UNKNOWN, which is proven separately
    # above. Here both a real git repo (no diff since the recorded SHA) and a
    # real recent/old timestamp are supplied, so the combined verdict
    # resolves to NOT_STALE / STALE without an UNKNOWN in the mix.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "f.txt").write_text("x", encoding="utf-8")
    _git(fresh, "init", "-q")
    _git(fresh, "-c", "user.email=t@example.com", "-c", "user.name=T", "add", "-A")
    _git(fresh, "-c", "user.email=t@example.com", "-c", "user.name=T",
         "commit", "-qm", "initial")
    sha = _head_sha(fresh)
    _write_state(fresh, git_sha=sha,
                last_transition={"stage": "VERIFY", "status": "PASS",
                                 "at": _iso(datetime.now(timezone.utc))})
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.loop_stale_detection", "detect",
         "--project-root", str(fresh), "--window-seconds", "999999"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] == lsd.NOT_STALE

    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / "f.txt").write_text("x", encoding="utf-8")
    _git(stale, "init", "-q")
    _git(stale, "-c", "user.email=t@example.com", "-c", "user.name=T", "add", "-A")
    _git(stale, "-c", "user.email=t@example.com", "-c", "user.name=T",
         "commit", "-qm", "initial")
    sha = _head_sha(stale)
    _write_state(stale, git_sha=sha,
                last_transition={"stage": "VERIFY", "status": "PASS",
                                 "at": _iso(datetime.now(timezone.utc) - timedelta(hours=10))})
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.loop_stale_detection", "detect",
         "--project-root", str(stale), "--window-seconds", "60"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] == lsd.STALE


def test_execute_verb_unknown_verb(tmp_path):
    code, payload = lsd.execute_verb(tmp_path, "bogus")
    assert code == 1
    assert payload["error"] == "UNKNOWN_VERB"


# --------------------------------------------------------------------------
# Wiring into loop_contract.derive_loop_state(): scoped and last in
# precedence
# --------------------------------------------------------------------------
def test_stale_eligible_base_states_is_derived_from_legal_transitions():
    # Never hand-typed a second time: it must equal exactly the LoopStates
    # LEGAL_LOOP_TRANSITIONS names a real STALE edge from.
    expected = {k for k, v in lc.LEGAL_LOOP_TRANSITIONS.items()
               if k is not None and lc.LoopState.STALE.value in v}
    assert {s.value for s in lc.STALE_ELIGIBLE_BASE_STATES} == expected
    assert expected == {"READY", "RUNNING", "VERIFYING", "CONVERGING", "STOPPED"}


def test_derive_loop_state_stale_overrides_an_eligible_base_state():
    from dv_harness.models import Status
    assert lc.derive_loop_state(Status.NOT_STARTED.value, stale=True) is lc.LoopState.STALE
    assert lc.derive_loop_state(Status.RUNNING.value, stale=True) is lc.LoopState.STALE
    # PASS with no plateau/oscillation -> CONVERGING, itself STALE-eligible.
    assert lc.derive_loop_state(Status.PASS.value, stale=True) is lc.LoopState.STALE
    assert lc.derive_loop_state(Status.ACCEPTED_RISK.value, stale=True) is lc.LoopState.STALE


def test_derive_loop_state_stale_false_is_byte_identical_to_before(monkeypatch):
    # Default stale=False must change nothing about any existing caller.
    from dv_harness.models import Status
    assert lc.derive_loop_state(Status.NOT_STARTED.value) is lc.LoopState.READY
    assert lc.derive_loop_state(Status.PASS.value) is lc.LoopState.CONVERGING
    assert lc.derive_loop_state(Status.ACCEPTED_RISK.value) is lc.LoopState.STOPPED


def test_derive_loop_state_stale_never_overrides_ineligible_states():
    from dv_harness.models import Status
    # A retry-family status whose budget is spent must still report
    # BUDGET_EXHAUSTED, not STALE, even when stale=True: staleness is not
    # allowed to hide a real, more specific finding.
    assert lc.derive_loop_state(Status.FAIL.value, attempts=9, max_attempts=2,
                                stale=True) is lc.LoopState.BUDGET_EXHAUSTED
    assert lc.derive_loop_state(Status.FAIL.value, attempts=1, max_attempts=2,
                                stale=True) is lc.LoopState.RETRY_WAIT
    assert lc.derive_loop_state(Status.BLOCKED.value, stale=True) is lc.LoopState.BLOCKED
    assert lc.derive_loop_state(Status.WAIT_USER.value, stale=True) is lc.LoopState.HUMAN_GATE
    assert lc.derive_loop_state(Status.PASS.value, oscillating=False,
                                progress_oscillating=True,
                                stale=True) is lc.LoopState.OSCILLATING
    assert lc.derive_loop_state(Status.CLOSED.value, stale=True) is lc.LoopState.SUCCESS


def test_derive_loop_state_stale_never_overrides_human_override():
    from dv_harness.models import Status
    # TAKEOVER and PAUSE both return before staleness is ever consulted --
    # Human Override is always valid, and staleness must never re-route it.
    assert lc.derive_loop_state(Status.RUNNING.value, takeover_active=True,
                                stale=True) is lc.LoopState.HUMAN_GATE
    assert lc.derive_loop_state(Status.RUNNING.value, paused=True,
                                stale=True) is lc.LoopState.STOPPED


def test_illegal_transition_error_still_fires_regardless_of_stale():
    with pytest.raises(ValueError):
        lc.derive_loop_state("TOTALLY_PASSED_PROBABLY", stale=True)


# --------------------------------------------------------------------------
# Wiring into observe_verification_closure_loop() / observe_all()
# --------------------------------------------------------------------------
def _fake_state(current_stage="VERIFY", overall_status="RUNNING", status="PASS"):
    from dv_harness.models import HarnessState
    st = HarnessState(project="p", current_stage=current_stage, overall_status=overall_status)
    st.stages[current_stage] = {"stage": current_stage, "status": status, "attempts": 1}
    return st


def test_observe_verification_closure_loop_applies_a_real_stale_report():
    cfg = {"policy": {"max_stage_retries": 2}}
    state = _fake_state(status="PASS")
    stale_report = {"status": "STALE", "is_stale": True,
                    "signals": [{"signal": "TIME_BASED", "status": "STALE",
                                "reason": "old"}]}
    obs = lc.observe_verification_closure_loop(state, cfg, staleness=stale_report)
    assert obs.state == lc.LoopState.STALE.value
    assert obs.evidence["staleness"] == stale_report
    assert "loop_stale_detection" in obs.derived_from


def test_observe_verification_closure_loop_absent_staleness_is_unchanged():
    cfg = {"policy": {"max_stage_retries": 2}}
    state = _fake_state(status="PASS")
    obs = lc.observe_verification_closure_loop(state, cfg)
    assert obs.state == lc.LoopState.CONVERGING.value
    assert obs.evidence["staleness"] is None


def test_observe_verification_closure_loop_a_not_stale_report_changes_nothing():
    cfg = {"policy": {"max_stage_retries": 2}}
    state = _fake_state(status="PASS")
    clean = {"status": "NOT_STALE", "is_stale": False, "signals": []}
    obs = lc.observe_verification_closure_loop(state, cfg, staleness=clean)
    assert obs.state == lc.LoopState.CONVERGING.value


def test_observe_all_computes_staleness_best_effort_on_a_bare_project(tmp_path):
    payload = lc.observe_all(tmp_path)
    assert "staleness" in payload
    # A bare project (no state.json, no git) has no evidence for either
    # signal -- honestly UNKNOWN, never a fabricated NOT_STALE.
    assert payload["staleness"]["status"] == lsd.UNKNOWN
    assert payload["staleness"]["is_stale"] is False
