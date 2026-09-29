"""Coverage for the 2026-08-29 active_stages read-site audit.

HarnessState.active_stages / effective_active_stages() (models.py) already
existed and were already correctly POPULATED by engine.py's parallel
fan-out dispatch (see test_graph_parallel_dispatch.py) -- the gap this audit
closed was on the READ side: a fixed list of consumer call-sites
(DVHarness.summary(), cli.py's explain/evidence, dashboard.py's /api/state +
graph-highlight JS, session_snapshot.py's saved-session manifest, ...) still
read ONLY the single current_stage scalar, so a live concurrent fan-out
looked identical to an ordinary single-stage run everywhere except the
dashboard's dedicated "Parallel Fan-out" tile.

This file proves the fix with a REAL concurrent fan-out (same synthetic
3-branch graph / _SlowAdapter concurrency-proof shape as
test_graph_parallel_dispatch.py's test_engine_dispatches_all_three_branches_
concurrently_and_joins) plus targeted checks of each individually-fixed
read-site, at minimum covering items #1 (engine.py summary()), #2/#3 (cli.py
explain/evidence with no --stage during a fan-out), and #6 (dashboard graph
highlight) called out as highest-value in the audit.
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# --- shared synthetic fan-out graph fixture (same shape as
# test_graph_parallel_dispatch.py's _write_synthetic_fanout_graph /
# _fresh_harness -- kept as a self-contained copy here rather than a
# cross-test-module import, so this file has no import-order dependency on
# that one) --------------------------------------------------------------

def _write_synthetic_fanout_graph(tmp: Path):
    nodes = [
        {"id": "ENV_CHECK", "route": "analysis-route", "agent": "analysis-agent"},
        {"id": "INTAKE", "route": "analysis-route", "agent": "analysis-agent",
         "parallel_group": "TESTG1", "blackboard_write": ["bw_a"]},
        {"id": "DISCOVERY", "route": "analysis-route", "agent": "analysis-agent",
         "parallel_group": "TESTG1", "blackboard_write": ["bw_b"]},
        {"id": "COMMAND_PATTERN", "route": "analysis-route", "agent": "analysis-agent",
         "parallel_group": "TESTG1", "blackboard_write": ["bw_c"]},
        # Deliberately a SYNTHETIC join node id with no Stage enum member --
        # this fixture models the real graph's ANALYSIS_JOIN (also synthetic),
        # whose whole point is that _advance_with_fanout() passes THROUGH it
        # to the next real Stage. It used to borrow the real
        # DE_BASELINE_REPRODUCTION Stage id here purely for convenience,
        # which stopped modelling ANALYSIS_JOIN once RCA_JOIN made
        # "join node that IS a real executable Stage" a genuinely different,
        # separately-tested case (see test_rca_multi_agent_fanout.py).
        {"id": "TESTG1_JOIN", "route": "lead-route", "agent": "dv-lead",
         "join_group": "TESTG1"},
        {"id": "ARCH_DISCOVERY", "route": "analysis-route", "agent": "analysis-agent"},
    ]
    edges = [
        {"source": "ENV_CHECK", "target": "INTAKE", "condition": "PASS"},
        {"source": "ENV_CHECK", "target": "DISCOVERY", "condition": "PASS"},
        {"source": "ENV_CHECK", "target": "COMMAND_PATTERN", "condition": "PASS"},
        {"source": "INTAKE", "target": "TESTG1_JOIN", "condition": "PASS"},
        {"source": "DISCOVERY", "target": "TESTG1_JOIN", "condition": "PASS"},
        {"source": "COMMAND_PATTERN", "target": "TESTG1_JOIN", "condition": "PASS"},
        {"source": "TESTG1_JOIN", "target": "ARCH_DISCOVERY", "condition": "PASS"},
    ]
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2),
        encoding="utf-8")


_STAGE_RE = re.compile(r"Current Stage: (\S+)")
BRANCHES = {"INTAKE", "DISCOVERY", "COMMAND_PATTERN"}


def _stage_from_prompt(prompt: str) -> str:
    m = _STAGE_RE.search(prompt)
    assert m, f"prompt did not embed 'Current Stage: <id>': {prompt[:200]!r}"
    return m.group(1)


def _fresh_fanout_harness():
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    _write_synthetic_fanout_graph(tmp)
    h = DVHarness(tmp)
    h.cfg["policy"]["require_stage_gate_evidence"] = False
    return tmp, h


# --- item #1: DVHarness.summary() (CLI `status`) ---------------------------

def test_summary_includes_active_stages_and_effective_active_stages_during_real_fanout():
    """The single biggest gap: summary() previously emitted only
    current_stage, so `dv-harness status` mid-fan-out looked exactly like an
    idle/ordinary single-stage run. Captured via a REAL concurrent
    3-branch dispatch (adapter callback reads h.summary() from inside the
    fan-out, the same way test_graph_parallel_dispatch.py's own concurrency
    proof reads h.state.active_stages from inside the adapter)."""
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_fanout_harness()
    try:
        lock = threading.Lock()
        captured = []

        class _SlowAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                stage = _stage_from_prompt(prompt)
                with lock:
                    captured.append(json.loads(h.summary()))
                time.sleep(0.2)
                return AgentResult(ok=True, text=f"evidence for {stage}", raw={}, session_id=None)

        h.adapter = _SlowAdapter()
        h.set_stage("ENV_CHECK")
        h.run_stage("goal")
        captured.clear()

        n = h.advance("goal")
        assert n == "ARCH_DISCOVERY"

        # Every summary() snapshot taken from INSIDE the fan-out must show the
        # full 3-branch set in BOTH the raw field and the derived helper --
        # this is what was previously invisible.
        assert len(captured) == 3, captured
        for snap in captured:
            assert "active_stages" in snap
            assert "effective_active_stages" in snap
            assert set(snap["active_stages"]) == BRANCHES, snap
            assert set(snap["effective_active_stages"]) == BRANCHES, snap
            # current_stage itself is unchanged -- still parked on the
            # fan-out's source node throughout, exactly as before.
            assert snap["current_stage"] == "ENV_CHECK", snap

        # After the join resolves, summary() reverts to the ordinary
        # single-stage picture -- active_stages back to [], effective_
        # active_stages falls back to the new current_stage.
        after = json.loads(h.summary())
        assert after["active_stages"] == []
        assert after["effective_active_stages"] == ["ARCH_DISCOVERY"]
        assert after["current_stage"] == "ARCH_DISCOVERY"
    finally:
        shutil.rmtree(tmp)


def test_summary_active_stages_empty_for_ordinary_non_fanout_stage():
    """Backward-compat: outside any fan-out, summary() still reports an
    empty active_stages and effective_active_stages falls back to the
    single current_stage -- unchanged behavior for the other 34+ ordinary
    (non-fan-out) stages."""
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    try:
        h = DVHarness(tmp)
        snap = json.loads(h.summary())
        assert snap["active_stages"] == []
        assert snap["effective_active_stages"] == [snap["current_stage"]]
    finally:
        shutil.rmtree(tmp)


# --- items #2/#3: cli.py `explain` / `evidence` with no --stage ------------

def _run_cli(monkeypatch, capsys, argv):
    from dv_harness import cli
    monkeypatch.setattr(sys, "argv", ["dv-harness"] + argv)
    cli.main()
    return capsys.readouterr().out


def test_cli_explain_with_no_stage_shows_all_active_branches_during_fanout(monkeypatch, capsys):
    tmp, h = _fresh_fanout_harness()
    try:
        h.state.active_stages = sorted(BRANCHES)
        h.store.save(h.state)

        out = _run_cli(monkeypatch, capsys,
                        ["--project-root", str(tmp), "explain"])
        for b in BRANCHES:
            assert f"=== {b} ===" in out, out
            assert f'"stage": "{b}"' in out, out
        # The parked source node itself (current_stage) must NOT be the only
        # thing explained -- it isn't even one of the active branches here.
        assert "=== ENV_CHECK ===" not in out
    finally:
        shutil.rmtree(tmp)


def test_cli_explain_with_no_stage_and_no_fanout_is_unchanged_single_stage():
    """Backward-compat proof done via a direct harness (not the CLI process,
    to avoid a real subprocess for a single-stage check already covered
    elsewhere) -- effective_active_stages() degrades to [current_stage] when
    active_stages is empty, so no multi-branch header is ever printed for an
    ordinary run."""
    from dv_harness.models import HarnessState
    st = HarnessState()
    assert st.active_stages == []
    assert st.effective_active_stages() == [st.current_stage]


def test_cli_evidence_with_no_stage_returns_per_branch_dict_during_fanout(monkeypatch, capsys):
    tmp, h = _fresh_fanout_harness()
    try:
        h.state.active_stages = sorted(BRANCHES)
        h.store.save(h.state)

        out = _run_cli(monkeypatch, capsys,
                        ["--project-root", str(tmp), "evidence"])
        data = json.loads(out)
        # Multi-branch case: describe_stages() batch form, keyed by stage id.
        assert set(data.keys()) == BRANCHES, data
        for b in BRANCHES:
            assert data[b]["stage"] == b
    finally:
        shutil.rmtree(tmp)


def test_cli_evidence_explicit_stage_flag_still_targets_just_that_one_stage(monkeypatch, capsys):
    """--stage always wins and still returns the single-stage describe_stage()
    shape (not the batch dict), even during a live fan-out -- explicit user
    intent is never overridden by the new default-to-all-active behavior."""
    tmp, h = _fresh_fanout_harness()
    try:
        h.state.active_stages = sorted(BRANCHES)
        h.store.save(h.state)

        out = _run_cli(monkeypatch, capsys,
                        ["--project-root", str(tmp), "evidence", "--stage", "DISCOVERY"])
        data = json.loads(out)
        assert data["stage"] == "DISCOVERY"
        assert "INTAKE" not in data
    finally:
        shutil.rmtree(tmp)


# --- item #4: control_plane.describe_stages() batch form -------------------

def test_describe_stages_batch_form_matches_looping_describe_stage():
    from dv_harness.control_plane import describe_stage, describe_stages
    from dv_harness.engine import DVHarness
    tmp, h = _fresh_fanout_harness()
    try:
        batch = describe_stages(tmp, h.state, sorted(BRANCHES))
        assert set(batch.keys()) == BRANCHES
        for b in BRANCHES:
            assert batch[b] == describe_stage(tmp, h.state, b)
        # Existing single-stage callers are unaffected -- describe_stage()
        # itself takes the exact same (root, state, stage) signature as
        # before this batch form was added.
        single = describe_stage(tmp, h.state, "ENV_CHECK")
        assert single["stage"] == "ENV_CHECK"
    finally:
        shutil.rmtree(tmp)


# --- item #6: dashboard graph-highlight JS ----------------------------------

def test_dashboard_graph_highlight_js_uses_active_stages_not_just_current_stage():
    """JS execution isn't available in this test process, so this proves the
    SOURCE-level fix landed rather than the old single-node behavior: the
    served page must compute the highlighted node set from
    active_stages/current_stage together (falling back to current_stage only
    when active_stages is empty), not from `n.id===s.current_stage` alone."""
    from dv_harness import dashboard
    html = dashboard.HTML
    assert "n.id===s.current_stage" not in html, \
        "graph highlight must no longer key off current_stage alone"
    assert "activeIds" in html and "s.active_stages" in html
    assert "includes(n.id)" in html or "activeIds.includes" in html


# --- item #5: dashboard /api/state active_stages_detail ---------------------

def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_dashboard(tmp: Path):
    from dv_harness import dashboard
    t = threading.Thread(target=dashboard.serve, args=(tmp,), daemon=True)
    t.start()
    return t


def _wait_ready(base: str, timeout: float = 10) -> None:
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            _get(base, "/api/state")
            return
        except Exception as e:
            last_exc = e
            time.sleep(0.05)
    raise AssertionError(f"dashboard at {base} never became ready: {last_exc}")


def _get(base: str, path: str):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def test_dashboard_state_endpoint_includes_active_stages_detail_during_fanout():
    port = _free_port()
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
        cfg = {"dashboard": {"host": "127.0.0.1", "port": port},
               "policy": {"require_stage_gate_evidence": False, "max_stage_retries": 0}}
        (tmp / ".dv-harness" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        state = {"current_stage": "PROTOCOL_CAPABILITY", "active_stages": sorted(BRANCHES)}
        (tmp / ".dv-harness" / "state.json").write_text(json.dumps(state), encoding="utf-8")

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert status == 200
        assert data["active_stages"] == sorted(BRANCHES)
        assert "active_stages_detail" in data
        assert set(data["active_stages_detail"].keys()) == BRANCHES
        for b in BRANCHES:
            assert data["active_stages_detail"][b]["stage"] == b
        # current_stage_detail is still computed too -- additive, not a
        # replacement.
        assert data["current_stage_detail"]["stage"] == "PROTOCOL_CAPABILITY"
    finally:
        shutil.rmtree(tmp)


def test_dashboard_state_endpoint_omits_active_stages_detail_outside_fanout():
    port = _free_port()
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
        cfg = {"dashboard": {"host": "127.0.0.1", "port": port},
               "policy": {"require_stage_gate_evidence": False, "max_stage_retries": 0}}
        (tmp / ".dv-harness" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert status == 200
        assert data.get("active_stages", []) == []
        assert "active_stages_detail" not in data
    finally:
        shutil.rmtree(tmp)


# --- item #10: session_snapshot.py manifest ---------------------------------

def test_session_manifest_captures_active_stages():
    from dv_harness.session_snapshot import save_session
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
        state = {"current_stage": "PROTOCOL_CAPABILITY", "active_stages": sorted(BRANCHES),
                  "overall_status": "IN_PROGRESS"}
        (tmp / ".dv-harness" / "state.json").write_text(json.dumps(state), encoding="utf-8")

        manifest = save_session(tmp, name="midfanout")
        assert manifest["active_stages"] == sorted(BRANCHES)

        on_disk = json.loads(
            (tmp / ".dv-harness" / "sessions" / "midfanout" / "session_manifest.json")
            .read_text(encoding="utf-8"))
        assert on_disk["active_stages"] == sorted(BRANCHES)
    finally:
        shutil.rmtree(tmp)
