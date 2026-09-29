"""Connection tests for the Planner -> Execution Layer edge
(2026-09-03, governance-architecture routing pass).

WHAT THIS PROVES, and why it is a wiring test rather than another unit
test: dv_harness/preflight.py's six real checks were already covered in
isolation (test_preflight.py) and at the submission boundary
(test_preflight_lsf_wiring.py, `dv-harness lsf-submit`), but
engine.DVHarness.run_stage() had NO call site into run_preflight() at all
-- the architecture diagram's "L5 Harness Graph/Planner -> Execution Layer
-> Preflight Agent" arrow was satisfied only by _degraded_gate()'s narrow
license+queue slice, and the full suite was reachable exclusively from two
separate CLI subcommands a stage transition never reaches.

Every assertion below is therefore about the EDGE: that run_stage() itself
really reaches dv_harness/preflight.py's own code (proven by the real
`lmutil lmstat`/`bqueues`/`hostname` command strings the injected transport
is asked to run -- no check is reimplemented or stubbed out here), that a
BLOCKED verdict really stops the stage BEFORE adapter.run() spawns a
`claude` subprocess, and that the gate is scoped by the REAL project graph's
own `vcs-build`/`devops-pipeline` skill declarations rather than a
hardcoded stage list.

Every license/queue/env fixture is the REAL captured output
test_preflight.py already uses (gathered 2026-09-03 against this project's
real license server and LSF queue) -- imported from that module so the
suites cannot drift, and no test here ever contacts a live license server,
scheduler, or host.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dv_harness import preflight as pf
from dv_harness.models import Stage, Status

from .test_harness_reliability import (
    REAL_LMSTAT_VCS_STARVED,
    _CountingAdapter,
    _ExplodingAdapter,
    _fresh,
)
from .test_preflight import (
    REAL_BQUEUES_VCS_OPEN_ACTIVE,
    REAL_LMSTAT_VCS_HEADER,
    _ScriptedRunner,
    _result as _res,
)

ROOT = Path(__file__).resolve().parents[1]

# The real tcsh `$?VAR`-presence output shape check_env_vars() parses, with
# every required var present. `check_env_vars` looks for "<VAR>_SET".
ENV_ALL_SET = "VCS_HOME_SET\nUVM_HOME_SET\nVERDI_HOME_SET\n"
ENV_VCS_HOME_UNSET = "VCS_HOME_UNSET\nUVM_HOME_SET\nVERDI_HOME_SET\n"

# A real `hostname` reply from the project's confirmed remote DV server.
REAL_HOSTNAME = "host-c\n"


def _armed(with_graph=True):
    """A DVHarness whose Planner->Execution-Layer gate is armed against a
    pure mock transport. `license_server` is set so the license check runs
    its REAL lmstat probe rather than short-circuiting on an unconfigured
    field -- i.e. the BLOCK/PASS verdicts below come from real parsed
    evidence, never from an empty config."""
    tmp, h = _fresh(with_graph=with_graph)
    h.cfg["preflight"]["license_server"] = "2900@host-a"
    h.cfg["execution_preflight"]["probe_resources"] = True
    return tmp, h


def _healthy_runner():
    return _ScriptedRunner([
        _res(stdout=REAL_LMSTAT_VCS_HEADER),        # eda_license
        _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),  # lsf_queue_health
        _res(stdout=REAL_HOSTNAME),                 # host_reachability
        _res(stdout=ENV_ALL_SET),                   # eda_env_vars
    ])
    # disk_space / workdir SKIP -- config.py ships `preflight.workdir` empty
    # ("never guessed or hardcoded"), which is preflight's own SKIP branch.


def _events(tmp: Path):
    p = tmp / ".dv-harness" / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ===========================================================================
# The edge itself: run_stage() reaches preflight.py's real checks
# ===========================================================================


class TestPlannerReachesPreflight:

    def test_run_stage_on_a_build_stage_runs_the_real_preflight_commands(self):
        """The connection, stated as directly as it can be: calling
        run_stage() on a BUILD-family stage causes dv_harness/preflight.py's
        OWN command strings to be issued over the injected transport. These
        are the real binaries the Preflight Agent box in the diagram names
        (lmstat / bqueues / hostname / EDA env probe), not a harness-local
        reimplementation."""
        tmp, h = _armed()
        try:
            runner = _healthy_runner()
            h.execution_preflight_runner = runner
            h.adapter = _CountingAdapter(ok=True, text="built")

            h.run_stage("goal", stage=Stage.BUILD.value)

            issued = [cmd for cmd, _timeout in runner.calls]
            assert any("lmstat" in c and "2900@host-a" in c for c in issued), issued
            assert any(c.startswith("bqueues vcs") for c in issued), issued
            assert any(c == "hostname" for c in issued), issued
            assert any("VCS_HOME" in c for c in issued), issued
            # Same count preflight.run_preflight() itself would make for this
            # config (4 probing checks; disk/workdir SKIP without a workdir)
            # -- so run_stage() is calling the aggregate gate, not a subset.
            assert len(runner.calls) == 4, issued
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_gate_calls_run_preflight_and_honours_the_shared_preflight_config(self):
        """The gate reuses the SAME `preflight` config block
        `dv-harness preflight` and `dv-harness lsf-submit` read -- there is no
        second place to configure the checks. Proven by changing only that
        block and observing the real probe change."""
        tmp, h = _armed()
        try:
            h.cfg["preflight"]["queue"] = "regress_q"
            h.cfg["preflight"]["license_features"] = ["VCSRuntime"]
            runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_HEADER),
                _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE.replace("vcs ", "regress_q ")),
                _res(stdout=REAL_HOSTNAME),
                _res(stdout=ENV_ALL_SET),
            ])
            h.execution_preflight_runner = runner
            h.adapter = _CountingAdapter(ok=True, text="ok")

            h.run_stage("goal", stage=Stage.REGRESSION.value)

            issued = [cmd for cmd, _t in runner.calls]
            assert any(c.startswith("bqueues regress_q") for c in issued), issued
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# A BLOCKED verdict really gates the stage (before any agent dispatch)
# ===========================================================================


class TestBlockedVerdictGatesTheStage:

    def test_starved_license_blocks_before_adapter_run(self):
        """The whole point of the edge: a real BLOCKED preflight stops the
        Planner from spending a full agent dispatch (a real `claude`
        subprocess with --dangerously-skip-permissions tool access) on a
        stage whose farm resources are not there. _ExplodingAdapter makes any
        dispatch a hard test failure."""
        tmp, h = _armed()
        try:
            h.execution_preflight_runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_STARVED),       # every license in use
                _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),
                _res(stdout=REAL_HOSTNAME),
                _res(stdout=ENV_ALL_SET),
            ])
            h.adapter = _ExplodingAdapter()

            res = h.run_stage("goal", stage=Stage.BUILD.value)

            assert h.adapter.calls == 0, "no agent may be dispatched past a BLOCKED preflight"
            assert res.ok is False
            assert res.raw["preflight_blocked"] is True
            assert res.raw["preflight"]["overall"] == "BLOCKED"
            assert res.raw["preflight"]["blocked_on"] == ["eda_license"]
            assert "EXECUTION_PREFLIGHT_BLOCKED" in res.text
            # The reason is real parsed evidence from preflight's own branch.
            detail = [c["detail"] for c in res.raw["preflight"]["checks"]
                      if c["name"] == "eda_license"][0]
            assert "fully checked out" in detail
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_blocked_stage_parks_in_wait_user_and_consumes_no_retry_budget(self):
        """Parks on the status loop()'s fallthrough already stops cleanly on
        (_degraded_gate()'s own stated reason), and -- because the gate sits
        before the attempts++ -- burns none of policy.max_stage_retries."""
        tmp, h = _armed()
        try:
            h.execution_preflight_runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_HEADER),
                _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),
                _res(stdout=REAL_HOSTNAME),
                _res(stdout=ENV_VCS_HOME_UNSET),            # eda_env_vars FAIL
            ])
            h.adapter = _ExplodingAdapter()
            before = dict(h.state.stages[Stage.BUILD.value])

            res = h.run_stage("goal", stage=Stage.BUILD.value)

            ss = h.state.stages[Stage.BUILD.value]
            assert res.raw["preflight"]["blocked_on"] == ["eda_env_vars"]
            assert ss["status"] == Status.WAIT_USER.value
            assert ss["attempts"] == before["attempts"], "a blocked stage must not spend a retry"
            assert "eda_env_vars" in ss["blocking_reason"]
            assert h.state.overall_status == Status.WAIT_USER.value
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_block_is_recorded_in_the_shared_audit_trail(self):
        """The decision lands in the same real .dv-harness/events.jsonl
        `dv-harness audit` reads back -- the same substrate
        GIT_GUARD_DECISION uses -- carrying the full real check evidence."""
        tmp, h = _armed()
        try:
            h.execution_preflight_runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_STARVED),
                _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),
                _res(stdout=REAL_HOSTNAME),
                _res(stdout=ENV_ALL_SET),
            ])
            h.adapter = _ExplodingAdapter()

            h.run_stage("goal", stage=Stage.BUILD.value)

            blocked = [e for e in _events(tmp)
                       if e.get("event") == "EXECUTION_PREFLIGHT_BLOCKED"]
            assert len(blocked) == 1, _events(tmp)
            ev = blocked[0]
            assert ev["stage"] == Stage.BUILD.value
            assert ev["execution_skills"] == ["vcs-build"]
            assert ev["blocked_on"] == ["eda_license"]
            assert ev["preflight"]["overall"] == "BLOCKED"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_loop_does_not_advance_past_a_preflight_blocked_stage(self):
        """Regression guard mirroring test_harness_reliability's own
        DEGRADED equivalent: loop()'s final fallthrough is an unconditional
        advance(), so a gate that set only overall_status would silently
        route a stage that never ran along the graph's PASS edge."""
        tmp, h = _armed()
        try:
            h.state.current_stage = Stage.BUILD.value
            h.store.save(h.state)
            h.execution_preflight_runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_STARVED),
                _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),
                _res(stdout=REAL_HOSTNAME),
                _res(stdout=ENV_ALL_SET),
            ])
            h.adapter = _ExplodingAdapter()

            h.loop("goal")

            assert h.state.current_stage == Stage.BUILD.value, \
                "loop() must not advance past a preflight-blocked stage"
            assert h.adapter.calls == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# A PASS verdict does not stand in the way
# ===========================================================================


class TestPassVerdictProceeds:

    def test_healthy_preflight_lets_the_stage_dispatch_its_agent(self):
        tmp, h = _armed()
        try:
            h.execution_preflight_runner = _healthy_runner()
            h.adapter = _CountingAdapter(ok=True, text="built cleanly")

            res = h.run_stage("goal", stage=Stage.BUILD.value)

            # >= 1, not == 1: on a gate miss the inner ReAct loop legitimately
            # makes further real adapter calls. What matters is the adapter was
            # reached at all, which a BLOCK prevents.
            assert h.adapter.calls >= 1
            assert res.raw.get("preflight_blocked") is not True
            assert h.state.stages[Stage.BUILD.value]["attempts"] == 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pass_is_also_recorded_as_real_evidence(self):
        """A PASS is audit evidence too -- "the farm really was checked
        before this build was dispatched" is exactly the claim a signoff
        needs to be able to substantiate later."""
        tmp, h = _armed()
        try:
            h.execution_preflight_runner = _healthy_runner()
            h.adapter = _CountingAdapter(ok=True, text="ok")

            h.run_stage("goal", stage=Stage.BUILD.value)

            passes = [e for e in _events(tmp)
                      if e.get("event") == "EXECUTION_PREFLIGHT_PASS"]
            assert len(passes) == 1
            assert passes[0]["preflight"]["overall"] == "PASS"
            assert passes[0]["execution_skills"] == ["vcs-build"]
            assert sorted(c["name"] for c in passes[0]["preflight"]["checks"]) == sorted(
                [c.name for c in pf.run_preflight(
                    pf.config_from_dict(h.cfg["preflight"]), runner=_healthy_runner()).checks]), \
                "the event must carry preflight.py's own full check set"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# Scoping: driven by the REAL graph's skill declarations
# ===========================================================================


class TestGateScoping:

    def test_non_execution_stage_never_probes_the_farm(self):
        """INTAKE routes an analysis agent; probing a license server for it
        would be pure waste. Scope comes from the graph node's own skills."""
        tmp, h = _armed()
        try:
            runner = _ScriptedRunner([])   # any call at all raises
            h.execution_preflight_runner = runner
            h.adapter = _CountingAdapter(ok=True, text="ok")

            h.run_stage("goal", stage=Stage.INTAKE.value)

            assert runner.calls == [], "a non-execution stage must not run preflight"
            assert not [e for e in _events(tmp)
                        if str(e.get("event", "")).startswith("EXECUTION_PREFLIGHT")]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_scope_matches_the_real_project_graph_build_regression_family(self):
        """Asserted against the REAL .dv-harness/graph/main_graph.json (copied
        into the temp project by _fresh()), not a fixture invented here: the
        stages that resolve as execution-layer are exactly the ones whose real
        nodes declare `vcs-build`/`devops-pipeline`."""
        tmp, h = _armed()
        try:
            assert h.graph is not None
            expected = sorted(n.id for n in h.graph.nodes.values()
                              if set(n.skills) & set(h.EXECUTION_PREFLIGHT_SKILLS))
            resolved = sorted(n for n in h.graph.nodes
                              if h._execution_preflight_skills(n))
            assert resolved == expected
            # The real BUILD/REGRESSION family, spelled out so a graph edit
            # that silently drops a build node from the gate fails here.
            assert set(expected) == {
                "DE_BASELINE_REPRODUCTION", "BUILD", "BUILD_DEBUG",
                "SERVER_SYNC", "REGRESSION", "INFRA_RECOVERY",
            }, expected
            assert h._execution_preflight_skills(Stage.INTAKE.value) == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_node_less_stage_is_a_no_op(self):
        """No graph -> no skill declaration -> no gate, rather than a crash
        or a fabricated block."""
        tmp, h = _armed(with_graph=False)
        try:
            runner = _ScriptedRunner([])
            h.execution_preflight_runner = runner
            assert h._execution_preflight_skills(Stage.BUILD.value) == []
            assert h._execution_preflight_gate(Stage.BUILD.value) is None
            assert runner.calls == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# Config discipline: never a fabricated block, never a silent bypass
# ===========================================================================


class TestConfigDiscipline:

    def test_probe_is_off_by_default_with_no_injected_transport(self):
        """config.py ships probe_resources False for degradation's own stated
        reason -- a PC-side session has no lmutil/bqueues, and treating
        "command not found" as a jammed farm would be a fabricated BLOCK. With
        neither the flag nor an injected runner, the gate is a no-op and the
        stage runs normally."""
        tmp, h = _fresh()
        try:
            assert h.cfg["execution_preflight"]["probe_resources"] is False
            h.adapter = _CountingAdapter(ok=True, text="ok")

            res = h.run_stage("goal", stage=Stage.BUILD.value)

            assert res.raw.get("preflight_blocked") is not True
            assert h.adapter.calls >= 1
            assert not [e for e in _events(tmp)
                        if str(e.get("event", "")).startswith("EXECUTION_PREFLIGHT")]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_an_injected_transport_alone_arms_the_gate(self):
        """The seam a REMOTE_EXECUTION deployment (and every test above) uses:
        assigning a real transport is itself the statement that a real probe
        is possible here, so it arms the gate without a config edit."""
        tmp, h = _fresh()
        try:
            h.cfg["preflight"]["license_server"] = "2900@host-a"
            assert h.cfg["execution_preflight"]["probe_resources"] is False
            h.execution_preflight_runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_STARVED),
                _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),
                _res(stdout=REAL_HOSTNAME),
                _res(stdout=ENV_ALL_SET),
            ])
            h.adapter = _ExplodingAdapter()

            res = h.run_stage("goal", stage=Stage.BUILD.value)

            assert res.raw["preflight_blocked"] is True
            assert h.adapter.calls == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_enabled_false_is_an_explicit_full_bypass(self):
        tmp, h = _armed()
        try:
            h.cfg["execution_preflight"]["enabled"] = False
            runner = _ScriptedRunner([])
            h.execution_preflight_runner = runner
            h.adapter = _CountingAdapter(ok=True, text="ok")

            h.run_stage("goal", stage=Stage.BUILD.value)

            assert runner.calls == []
            assert h.adapter.calls >= 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_crashing_probe_never_becomes_an_unbreakable_block(self):
        """Best-effort, like every other real side effect in engine.py: an
        unreachable transport leaves the stage running normally rather than
        stranding the harness in a state a human must dig it out of."""
        tmp, h = _armed()
        try:
            def _boom(cmd, timeout=60):
                raise RuntimeError("relay down")

            h.execution_preflight_runner = _boom
            h.adapter = _CountingAdapter(ok=True, text="ok")

            res = h.run_stage("goal", stage=Stage.BUILD.value)

            assert res.raw.get("preflight_blocked") is not True
            assert h.adapter.calls >= 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_takeover_and_dry_run_still_outrank_the_gate(self):
        """Ordering guard: the gate sits AFTER the human-override and dry-run
        short-circuits, so neither one starts probing a farm. A human holding
        the stage, and a read-only planning pass, both stay possible while the
        farm is unavailable."""
        tmp, h = _armed()
        try:
            runner = _ScriptedRunner([])
            h.execution_preflight_runner = runner
            h.adapter = _ExplodingAdapter()

            res = h.run_stage("goal", stage=Stage.BUILD.value, dry_run=True)

            assert runner.calls == [], "a dry-run must not probe the farm"
            assert "DRY_RUN" in res.text
            assert h.adapter.calls == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# This gate does not weaken the submission-time gate
# ===========================================================================


def test_submission_time_gate_remains_the_authoritative_one():
    """The new stage gate is earlier and cheaper, NOT a replacement:
    lsf_client.bsub_submit_with_preflight() still runs the same suite
    immediately before a real `bsub`, and `preflight.require_license_configured`
    still defaults True (an unconfigured license server FAILs rather than
    silently passing) for that path."""
    assert pf.PreflightConfig().require_license_configured is True
    from dv_harness import lsf_client
    assert hasattr(lsf_client, "bsub_submit_with_preflight")
    assert hasattr(lsf_client, "PreflightBlockedError")
