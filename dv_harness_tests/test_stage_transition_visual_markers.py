"""Tests for the stage-start/stage-completed visual-marker pass (2026-09-01,
runtime-progress-visibility workflow): an earlier audit found no distinct
"just happened" signal anywhere -- dashboard.py's status tiles update
silently on a 3s poll, and cli.py printed nothing but the agent's own
free-text reply after a stage already finished.

This closes two gaps:
  1. engine.run_stage() itself (not cli.py) prints a plain, greppable,
     bracket-delimited marker to stdout at stage entry and a matching one at
     stage exit carrying the real gate_verdict/stage_completion_percent --
     see engine.STAGE_MARKER_PREFIX's RULING comment for why plain print()
     over `logging` (no module in dv_harness/ uses `logging` today).
  2. HarnessState.last_transition is a real, persisted {"stage", "status",
     "at"} record, written every time run_stage() reaches a terminal status
     -- the dashboard's GET /api/state forwards it verbatim (state.json is
     read and re-served as-is) for the frontend's always-visible "Last
     transition" banner.
"""
import json
import shutil
import tempfile
from pathlib import Path

from dv_harness.engine import DVHarness, STAGE_MARKER_PREFIX
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


class _PassAdapter:
    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        return AgentResult(ok=True, text="ok", raw={}, session_id="s1")


class _AdapterFailAdapter:
    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        return AgentResult(ok=False, text="", raw={"stderr": "boom"}, session_id=None)


# --- 1. run_stage() actually emits the markers (stdout capture) ------------

def test_run_stage_emits_start_and_done_markers_on_stdout(capsys):
    tmp, h = _fresh_harness()
    try:
        # policy.require_stage_gate_evidence=False lets ss["status"] promote
        # to PASS without real gate evidence (this test's own concern is
        # "does run_stage() print the markers", not gate mechanics). The DONE
        # marker's own [verdict] (percent%) still comes from
        # control_plane.describe_stage()'s INDEPENDENT, unconditional
        # recomputation over STAGE_GATES -- DISCOVERY has two real mapped
        # gates (evidence_source_priority_gate/input_source_contract_gate,
        # see gates.STAGE_GATES) and this attempt supplied neither, so that
        # recompute genuinely reports MISSING_EVIDENCE at 0%, even though the
        # policy flag let the STAGE itself close as PASS. This divergence is
        # pre-existing describe_stage() behavior (identical to what
        # `dv-harness explain`/`evidence` already show for this same
        # scenario) -- not something this pass changes -- so the marker
        # faithfully reports it rather than asserting a fabricated "clean"
        # PASS/100% this attempt never actually earned.
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("DISCOVERY")
        h.adapter = _PassAdapter()
        h.run_stage("goal")

        out = capsys.readouterr().out
        assert h.state.stages["DISCOVERY"]["status"] == Status.PASS.value
        start_line = f"{STAGE_MARKER_PREFIX} ===== STAGE START: DISCOVERY ====="
        assert start_line in out, out
        done_line = f"{STAGE_MARKER_PREFIX} ===== STAGE DONE: DISCOVERY [MISSING_EVIDENCE] (0% gates satisfied) ====="
        assert done_line in out, out
        # START must print strictly before DONE, not just both be present.
        assert out.index(start_line) < out.index(done_line)
    finally:
        shutil.rmtree(tmp)


def test_run_stage_start_marker_is_suppressed_under_active_takeover(capsys):
    # A takeover'd call never actually starts the stage (engine.py returns
    # BLOCKED_BY_TAKEOVER before any state mutation) -- it must not print a
    # START it never earns.
    tmp, h = _fresh_harness()
    try:
        from dv_harness import commands
        h.set_stage("DISCOVERY")
        commands.cmd_takeover(h, "human driving this one")
        capsys.readouterr()  # discard anything printed by setup above
        result = h.run_stage("goal")

        out = capsys.readouterr().out
        assert STAGE_MARKER_PREFIX not in out
        assert "BLOCKED_BY_TAKEOVER" in result.text
    finally:
        shutil.rmtree(tmp)


def test_run_stage_done_marker_reflects_a_real_fail_verdict(capsys):
    tmp, h = _fresh_harness()
    try:
        h.set_stage("DISCOVERY")
        h.adapter = _AdapterFailAdapter()
        h.run_stage("goal")

        out = capsys.readouterr().out
        assert h.state.stages["DISCOVERY"]["status"] == Status.FAIL.value
        # An ADAPTER_FAIL never assigns the local `verdict` variable inside
        # run_stage() -- the DONE marker must still fire, sourced from
        # describe_stage()'s own independent recomputation.
        assert f"{STAGE_MARKER_PREFIX} ===== STAGE DONE: DISCOVERY [" in out
        assert "gates satisfied) =====" in out
    finally:
        shutil.rmtree(tmp)


# --- 2. last_transition is persisted into state.json correctly -------------

def test_last_transition_persisted_into_state_json_after_a_pass():
    tmp, h = _fresh_harness()
    try:
        assert h.state.last_transition is None  # honest default, nothing has run yet
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("DISCOVERY")
        h.adapter = _PassAdapter()
        h.run_stage("goal")

        assert h.state.last_transition == {
            "stage": "DISCOVERY", "status": Status.PASS.value,
            "at": h.state.last_transition["at"],  # exact iso timestamp asserted for presence/shape below
        }
        assert h.state.last_transition["at"]  # non-empty real timestamp

        on_disk = json.loads((tmp / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
        assert on_disk["last_transition"] == {
            "stage": "DISCOVERY", "status": "PASS", "at": on_disk["last_transition"]["at"],
        }
        assert on_disk["last_transition"]["at"]
    finally:
        shutil.rmtree(tmp)


def test_last_transition_persisted_after_an_adapter_fail_and_reloads_via_state_store():
    tmp, h = _fresh_harness()
    try:
        h.set_stage("DISCOVERY")
        h.adapter = _AdapterFailAdapter()
        h.run_stage("goal")

        # Reload through StateStore (not the in-memory h.state) to prove this
        # is real on-disk persistence, not just an in-process attribute.
        from dv_harness.storage import StateStore
        reloaded = StateStore(tmp).load()
        assert reloaded.last_transition["stage"] == "DISCOVERY"
        assert reloaded.last_transition["status"] == Status.FAIL.value
        assert reloaded.last_transition["at"]
    finally:
        shutil.rmtree(tmp)


def test_last_transition_updates_across_successive_stage_runs():
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("DISCOVERY")
        h.adapter = _PassAdapter()
        h.run_stage("goal")
        first_at = h.state.last_transition["at"]
        assert h.state.last_transition["stage"] == "DISCOVERY"

        h.set_stage("ARCH_DISCOVERY")
        h.adapter = _AdapterFailAdapter()
        h.run_stage("goal")
        assert h.state.last_transition["stage"] == "ARCH_DISCOVERY"
        assert h.state.last_transition["status"] == Status.FAIL.value
        # A later transition's timestamp must not silently reuse the first.
        assert h.state.last_transition["at"] != first_at
    finally:
        shutil.rmtree(tmp)


def test_dashboard_get_state_forwards_last_transition_verbatim():
    # dashboard.py's GET /api/state reads state.json and re-serves it
    # (plus a bunch of computed additions) as-is -- last_transition needs no
    # dedicated backend wiring there, just HarnessState/StateStore carrying
    # it. This proves that pipe end-to-end via _read_json_file, the same
    # helper the real GET handler uses.
    from dv_harness.dashboard import _read_json_file
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("DISCOVERY")
        h.adapter = _PassAdapter()
        h.run_stage("goal")

        state = _read_json_file(tmp / ".dv-harness" / "state.json", default={})
        assert state["last_transition"]["stage"] == "DISCOVERY"
        assert state["last_transition"]["status"] == Status.PASS.value
    finally:
        shutil.rmtree(tmp)
