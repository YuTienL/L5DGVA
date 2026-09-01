# Regression tests for the multi-agent-timing-reconciliation pass
# (2026-09-01): AgentTaskStore.create_task() previously produced a task dict
# with ZERO timing fields and there was no complete_task()-style method at
# all, even though engine.py's run_stage() delegates a real task here before
# every LLM call -- this store was completely disconnected from
# stage_profile.py's real timing/token machinery. These tests exercise the
# real create_task()/start_task()/complete_task() round trip directly
# against AgentTaskStore, AND run_stage()'s real call path end-to-end (not a
# stub/mock check) to prove complete_task() is genuinely invoked with a real,
# measured duration that reconciles into stage_profile.py's own record.
import json
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from dv_harness.multi_agent import AgentTaskStore
from dv_harness_tests.test_engine_gates_and_routing import _mk_smoke_project, _DISCOVERY_EXTRA_GATES


def test_create_task_defaults_timing_fields_to_null():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = AgentTaskStore(tmp)
        t = store.create_task("analysis-agent", "route1", ["skillA"], "PLAN-1")
        assert t["status"] == "NOT_STARTED"
        assert t["started_at"] is None
        assert t["completed_at"] is None
        assert t["duration_sec"] is None
    finally:
        shutil.rmtree(tmp)


def test_start_task_then_complete_task_round_trip_with_real_duration():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = AgentTaskStore(tmp)
        t = store.create_task("analysis-agent", "route1", [], "PLAN-1")

        started = store.start_task(t["task_id"])
        assert started["status"] == "RUNNING"
        assert isinstance(started["started_at"], float)

        time.sleep(0.03)
        completed = store.complete_task(t["task_id"], status="COMPLETED")

        assert completed["status"] == "COMPLETED"
        assert isinstance(completed["completed_at"], float)
        assert completed["completed_at"] >= completed["started_at"]
        assert completed["duration_sec"] == pytest.approx(
            completed["completed_at"] - completed["started_at"], abs=1e-6)
        # Real measured sleep(0.03), not a fabricated/stubbed value.
        assert completed["duration_sec"] >= 0.02

        # Real JSON file persistence (same atomic-write convention
        # create_task() already used), not just an in-memory mutation: a
        # freshly-constructed store pointed at the same root must see the
        # completion that was just written.
        reloaded = AgentTaskStore(tmp)
        on_disk = json.loads(reloaded.tasks.read_text(encoding="utf-8"))
        on_disk_task = next(x for x in on_disk if x["task_id"] == t["task_id"])
        assert on_disk_task["status"] == "COMPLETED"
        assert on_disk_task["duration_sec"] == completed["duration_sec"]
    finally:
        shutil.rmtree(tmp)


def test_complete_task_without_start_backfills_started_at_and_zero_duration():
    # Defensive path, not the real engine.py call order (which always calls
    # start_task() first) -- a task completed without ever starting still
    # gets a real (not None/negative/fabricated) duration_sec of 0.0.
    tmp = Path(tempfile.mkdtemp())
    try:
        store = AgentTaskStore(tmp)
        t = store.create_task("analysis-agent", "route1", [], "PLAN-1")
        completed = store.complete_task(t["task_id"], status="FAILED")
        assert completed["started_at"] == completed["completed_at"]
        assert completed["duration_sec"] == 0.0
        assert completed["status"] == "FAILED"
    finally:
        shutil.rmtree(tmp)


def test_start_task_unknown_id_raises_keyerror():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = AgentTaskStore(tmp)
        with pytest.raises(KeyError):
            store.start_task("TASK-DOESNOTEXIST")
    finally:
        shutil.rmtree(tmp)


def test_complete_task_unknown_id_raises_keyerror():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = AgentTaskStore(tmp)
        with pytest.raises(KeyError):
            store.complete_task("TASK-DOESNOTEXIST", status="COMPLETED")
    finally:
        shutil.rmtree(tmp)


def test_run_stage_real_call_path_invokes_complete_task_with_real_duration():
    """End-to-end regression test: exercises run_stage()'s REAL call path
    (DVHarness.run_stage() -> self.agents.delegate() ->
    self.agents.store.start_task()/complete_task() ->
    self.profiler.add_agent_run()) -- not a stub/mock assertion that
    complete_task() was merely called. Asserts a real, measured,
    non-trivial duration reaches BOTH AgentTaskStore's own tasks.json AND
    stage_profile.py's per-agent record, and that the two values are
    genuinely reconciled (the same number), not two independently
    fabricated timers."""
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness
        from dv_harness.adapters.base import AgentResult

        class SlowFakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                time.sleep(0.05)
                return AgentResult(
                    ok=True, text="analysis done.\n" + _DISCOVERY_EXTRA_GATES,
                    raw={"response": {"model": "claude-x",
                                      "usage": {"input_tokens": 1, "output_tokens": 1}}},
                    session_id="sess-1")

        h = DVHarness(tmp)
        h.adapter = SlowFakeAdapter()
        h.blackboard.write("project", {"target_name": "usb_dev"}, source="INTAKE")
        h.set_stage("DISCOVERY")
        h.run_stage("verify the USB device controller")

        assert h.state.stages["DISCOVERY"]["status"] == "PASS"

        tasks = json.loads(h.agents.store.tasks.read_text(encoding="utf-8"))
        assert len(tasks) == 1
        task = tasks[0]
        assert task["agent"] == "analysis-agent"
        assert task["parent_plan"]
        assert task["status"] == "COMPLETED"
        assert task["started_at"] is not None
        assert task["completed_at"] is not None
        assert task["completed_at"] >= task["started_at"]
        # Real measured sleep(0.05) in the fake adapter, not a stub 0/None.
        assert task["duration_sec"] >= 0.03

        recs = h.profiler.all_stages()
        assert len(recs) == 1
        agents = recs[0]["agents"]
        assert len(agents) == 1
        # Reconciliation: the SAME AgentTaskStore duration_sec was fed into
        # profiler.add_agent_run() (see engine.py's RULING comment at the
        # adapter.run() call site), not a second independently-computed
        # number for the same span.
        assert agents[0]["runtime_sec"] == task["duration_sec"]
    finally:
        shutil.rmtree(tmp)


def test_run_stage_marks_task_failed_on_adapter_failure():
    # The task's own status tracks whether the delegated agent CALL
    # completed (COMPLETED/FAILED) -- deliberately narrower than the
    # stage's gate-verified business status. An adapter failure must still
    # reach a real complete_task() call (status=FAILED), not leave the task
    # stuck at NOT_STARTED/RUNNING forever.
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness
        from dv_harness.adapters.base import AgentResult

        class FailingFakeAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=False, text="", raw={"stderr": "boom"}, session_id=None)

        h = DVHarness(tmp)
        h.adapter = FailingFakeAdapter()
        h.blackboard.write("project", {"target_name": "usb_dev"}, source="INTAKE")
        h.set_stage("DISCOVERY")
        h.run_stage("verify the USB device controller")

        assert h.state.stages["DISCOVERY"]["status"] == "FAIL"
        tasks = json.loads(h.agents.store.tasks.read_text(encoding="utf-8"))
        assert len(tasks) == 1
        assert tasks[0]["status"] == "FAILED"
        assert tasks[0]["duration_sec"] is not None
    finally:
        shutil.rmtree(tmp)
