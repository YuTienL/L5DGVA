"""GET /api/agent-activity -- the GUI Agent Activity / Observability card
(ULTIMATE_COMPLETE_GUI.md section 64, "GUI-06").

Before this, dashboard.py's only per-agent surface was the Workflow Graph's
`node.agent` label (which agent a STATIC graph node is *assigned* to) -- there
was no card showing which real, delegated task is RUNNING right now, what it
is currently claiming, or how long it has been at it, even though
`multi_agent.AgentTaskStore` is a real, production-wired ledger:
`engine.DVHarness.run_stage()` calls `MultiAgentOrchestrator.delegate()`
before every LLM call and `start_task()`/`complete_task()` around the adapter
run (see that module's own header NOTICE).

Every fixture here is produced by a REAL `DVHarness.loop()` over the REAL
shipped `main_graph.json` -- never by writing tasks.json/ownership.json lines
by hand for the endpoint-level tests, and by the REAL
`multi_agent.AgentTaskStore` class (never a hand-shaped dict) for the
resource-ownership-join tests, which need a fan-out claim `COMMAND_PATTERN`
(this repo's own single-gate, non-fan-out fixture stage) never produces on its
own. The real dashboard server is started on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers,
the same convention test_dashboard_loop_card.py and test_dashboard_amba_card.py
follow.

Nothing here runs a build, a regression or an LSF submission.
"""
from __future__ import annotations

import json
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _post,
    _start_dashboard,
    _wait_ready,
)
from dv_harness_tests.controlled_experiment_fixture import (
    FIXTURE_STAGE,
    harness_factory,
    make_fixture_project,
)


def _dashboard_project(tmp: Path, port: int) -> Path:
    project = make_fixture_project(tmp)
    (project / ".dv-harness").mkdir(parents=True, exist_ok=True)
    (project / ".dv-harness" / "config.json").write_text(
        json.dumps({"dashboard": {"host": "127.0.0.1", "port": port}}),
        encoding="utf-8")
    return project


def _run_real_stage(project: Path):
    """A real, single, PASSing stage attempt -- real MultiAgentOrchestrator
    delegation + start_task()/complete_task() timing, no retry/fan-out noise."""
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    (project / "command_migration.json").write_text(
        json.dumps({
            "commands": [
                {"command_id": "cmd_lfps_polling", "source_hash": "a1b2c3", "destination_hash": "a1b2c3"},
                {"command_id": "cmd_u1_entry", "source_hash": "d4e5f6", "destination_hash": "d4e5f6"},
            ]
        }),
        encoding="utf-8")
    h.run_stage("verify the command pattern migration")
    return h


def _serve(project: Path, port: int) -> str:
    base = f"http://127.0.0.1:{port}"
    _start_dashboard(project)
    _wait_ready(base)
    return base


def test_the_endpoint_reports_an_honest_empty_state_before_any_task_delegated(tmp_path):
    """A project that has never delegated a real task must say so -- the
    AgentTaskStore ledger has never been written at all -- never render a
    fabricated agent row, and it must never be constructed from a GET (which
    would mint `.dv-harness/agents/` merely because a browser asked)."""
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    base = _serve(project, port)

    assert not (project / ".dv-harness" / "agents").exists()
    code, body = _get(base, "/api/agent-activity")
    assert code == 200
    assert body["available"] is False
    assert body["rows"] == []
    assert body["summary"]["task_count"] == 0
    # Reading it must not have minted the ledger directory either.
    assert not (project / ".dv-harness" / "agents").exists()


def test_a_real_delegated_task_fills_the_real_columns(tmp_path):
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    h = _run_real_stage(project)
    base = _serve(project, port)

    code, body = _get(base, "/api/agent-activity")
    assert code == 200 and body["available"] is True
    assert len(body["rows"]) == 1
    row = body["rows"][0]

    # Cross-checked against the REAL AgentTaskStore file this same run wrote,
    # not merely asserted self-consistent with the endpoint's own output.
    real_tasks = json.loads((project / ".dv-harness" / "agents" / "tasks.json").read_text())
    assert len(real_tasks) == 1
    real = real_tasks[0]

    assert row["task_id"] == real["task_id"]
    assert row["agent"] == real["agent"] == "implementation-agent"
    assert row["route"] == real["route"] == "implementation-route"
    assert row["status"] == real["status"] == "COMPLETED"
    assert row["started_at"] == real["started_at"]
    assert row["completed_at"] == real["completed_at"]
    assert row["duration_sec"] == real["duration_sec"]
    assert row["duration_sec"] is not None and row["duration_sec"] >= 0.0
    assert row["parallel_group"] == real["parallel_group"]
    assert row["skills"] == real["skills"]
    # COMMAND_PATTERN is not a parallel_group/fan-out node, so this real run
    # claimed no shared blackboard-topic resource -- an honestly empty list,
    # never a guessed claim.
    assert row["owned_resources"] == []
    assert body["summary"]["task_count"] == 1
    assert body["summary"]["status_counts"] == {"COMPLETED": 1}
    # Task completion tracks adapter transport success (result.ok), not the
    # stage's own gate verdict -- deliberately not asserted here, since
    # whether COMMAND_PATTERN's *stage* reaches PASS depends on every gate
    # STAGE_GATES currently lists for it (a fact outside this card's own
    # scope) and h is kept only for the tasks.json cross-check above.
    assert h.state.stages[FIXTURE_STAGE]["attempts"] >= 1


def test_owned_resources_joins_by_task_id_only_never_a_name_guess(tmp_path):
    """Two real tasks delegated to the SAME agent; only one of them actually
    holds a real AgentTaskStore claim. The join must attribute that claim to
    the task that really holds it and to no other -- proving this is a real
    task_id equality join, not "the most recent task" or "any task by this
    agent"."""
    from dv_harness import multi_agent
    from dv_harness.dashboard import _read_agent_activity_state

    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    store = multi_agent.AgentTaskStore(project)

    task_a = store.create_task("analysis-agent", "analysis-route", ["skill-a"], "PLAN-1")
    task_b = store.create_task("analysis-agent", "analysis-route", ["skill-a"], "PLAN-1")
    store.start_task(task_a["task_id"])
    store.start_task(task_b["task_id"])

    ok, rec = store.acquire("findings", task_a["task_id"], "analysis-agent")
    assert ok is True
    assert rec["task_id"] == task_a["task_id"]

    state = _read_agent_activity_state(project)
    assert state["available"] is True
    by_id = {r["task_id"]: r for r in state["rows"]}
    assert by_id[task_a["task_id"]]["owned_resources"] == ["findings"]
    assert by_id[task_b["task_id"]]["owned_resources"] == []
    assert state["summary"]["claimed_resource_count"] == 1
    assert state["summary"]["task_count"] == 2
    assert state["summary"]["status_counts"] == {"RUNNING": 2}


def test_a_present_but_empty_ledger_is_distinct_from_never_written(tmp_path):
    """A ledger that EXISTS but records zero tasks (real AgentTaskStore
    construction, no create_task() call) is a different, real fact from one
    that was never written -- both must be reported honestly, never
    conflated."""
    from dv_harness import multi_agent
    from dv_harness.dashboard import _read_agent_activity_state

    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    multi_agent.AgentTaskStore(project)  # constructs and writes empty [] / {}

    state = _read_agent_activity_state(project)
    assert state["available"] is True
    assert state["rows"] == []
    assert state["summary"]["task_count"] == 0


def test_polling_the_card_writes_nothing_and_approves_nothing(tmp_path):
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    _run_real_stage(project)
    base = _serve(project, port)

    before = {p: p.stat().st_mtime_ns
              for p in (project / ".dv-harness").rglob("*") if p.is_file()}
    for _ in range(5):
        _get(base, "/api/agent-activity")
    after = {p: p.stat().st_mtime_ns
             for p in (project / ".dv-harness").rglob("*") if p.is_file()}
    assert before == after

    from dv_harness.control_plane import ControlPlane
    assert not ControlPlane(project).load().get("approvals")


def test_the_card_offers_no_write_endpoint_of_its_own(tmp_path):
    """Delegating/claiming/releasing a task already happens exclusively inside
    engine.py's own run_stage()/_advance_with_fanout() -- this card only
    observes that ledger. A POST here must be refused, not silently accepted."""
    port = _free_port()
    project = _dashboard_project(tmp_path / "p", port)
    base = _serve(project, port)

    code, body = _post(base, "/api/agent-activity", {"agent": "x"})
    assert code == 404
    assert body["error"] == "NOT_FOUND"
