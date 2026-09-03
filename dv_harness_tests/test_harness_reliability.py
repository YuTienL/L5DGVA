"""Tests for the 2026-09-03 harness-reliability workstream:

  1. dry-run 模式      -- engine.DVHarness.run_stage(dry_run=True)
  2. checkpoint 與回滾 -- automatic stage-transition session snapshots with
                          bounded retention (session_snapshot.py)
  3. 降級路徑          -- DEGRADED mode (dv_harness/degradation.py)

Every license/queue fixture below is the REAL captured `lmutil lmstat`/
`bqueues` output dv_harness_tests/test_preflight.py already uses (gathered
2026-09-03 against the real project license server/queue) -- imported from
that module rather than re-typed, so the two suites cannot drift and no test
here ever contacts a live license server or scheduler.
"""
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import degradation, session_snapshot
from dv_harness.adapters.base import AgentResult
from dv_harness.engine import DVHarness
from dv_harness.models import Stage, Status

from .test_preflight import (
    REAL_BQUEUES_VCS_OPEN_ACTIVE,
    REAL_LMSTAT_VCS_HEADER,
    _ScriptedRunner,
    _result as _res,
)

ROOT = Path(__file__).resolve().parents[1]

# The same real lmstat text, mutated ONLY in the numbers that mean
# "starvation": every issued VCSRuntime license is checked out. This is the
# exact condition preflight.check_license() already reports as
# "fully checked out (starvation)" -- see its own `starved` branch.
REAL_LMSTAT_VCS_STARVED = REAL_LMSTAT_VCS_HEADER.replace(
    "Users of VCSRuntime:  (Total of 99 licenses issued;  Total of 0 licenses in use)",
    "Users of VCSRuntime:  (Total of 99 licenses issued;  Total of 99 licenses in use)")

# The same real bqueues text with the queue closed/inactive -- LSF's own
# representation of a queue that is not accepting/dispatching work.
REAL_BQUEUES_VCS_CONGESTED = REAL_BQUEUES_VCS_OPEN_ACTIVE.replace(
    "Open:Active", "Closed:Inact")


class _ExplodingAdapter:
    """Any call at all is a test failure. Used wherever the harness must be
    proven NOT to have made a judgment-requiring adapter call."""

    def __init__(self):
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        raise AssertionError("adapter.run() was called when it must not have been")


class _CountingAdapter:
    """Returns a fixed AgentResult and counts calls."""

    def __init__(self, ok=True, text="ok", stderr=""):
        self.ok, self.text, self.stderr = ok, text, stderr
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        return AgentResult(ok=self.ok, text=self.text,
                            raw={"stderr": self.stderr}, session_id=None)


def _fresh(with_graph=True):
    """A DVHarness on a fresh temp project, with the real project graph so
    stage nodes/routes/gates resolve exactly as they do in production.
    Caller must shutil.rmtree(tmp)."""
    tmp = Path(tempfile.mkdtemp())
    if with_graph:
        (tmp / ".dv-harness" / "graph").mkdir(parents=True)
        src = ROOT / ".dv-harness" / "graph" / "main_graph.json"
        (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
            src.read_text(encoding="utf-8"), encoding="utf-8")
    h = DVHarness(tmp)
    # Keep every test off the real farm/license server unless it explicitly
    # injects its own mock runner.
    h.cfg["degradation"]["probe_resources"] = False
    return tmp, h


# ===========================================================================
# 1. dry-run 模式
# ===========================================================================


class TestDryRun:

    def test_dry_run_produces_a_real_plan_without_executing_anything(self):
        """The core spec: "agent 產出完整計畫但不執行, 人可事前檢視."

        Asserts BOTH halves -- a real, reviewable plan artifact IS produced,
        AND none of run_stage()'s real side-effect call sites fired.
        """
        tmp, h = _fresh()
        try:
            stage = Stage.INTAKE.value
            h.adapter = _ExplodingAdapter()

            # Pre-state, captured so "nothing mutated" is a real comparison
            # against this run rather than an assumption about defaults.
            before_state = (tmp / ".dv-harness" / "state.json").read_text(encoding="utf-8")
            plans_before = sorted(p.name for p in (tmp / ".dv-harness" / "plans").glob("*.json"))
            events_path = tmp / ".dv-harness" / "events.jsonl"
            events_before = events_path.read_text(encoding="utf-8") if events_path.exists() else ""

            result = h.run_stage("verify the USB LFPS handshake", stage=stage, dry_run=True)

            # --- the plan artifact is real -------------------------------
            assert result.ok is True
            assert "DRY_RUN" in result.text
            reports = sorted((tmp / ".dv-harness" / "dry_run").glob(f"{stage}-*.json"))
            assert len(reports) == 1, "exactly one dry-run report should be written"
            report = json.loads(reports[0].read_text(encoding="utf-8"))

            assert report["dry_run"] is True
            assert report["stage"] == stage
            assert report["user_goal"] == "verify the USB LFPS handshake"
            # A real resolved route/agent, not a placeholder.
            assert report["would_execute"]["agent"]
            assert report["would_execute"]["route"]
            assert report["would_execute"]["protocol_decision"]["protocol"]
            # environment_mode is honestly None on a fresh project with nothing
            # registered yet -- assert the real decision/evidence shape rather
            # than a mode the router never actually claims.
            assert "environment_mode" in report["would_execute"]["environment_mode_decision"]
            assert report["would_execute"]["environment_mode_decision"]["evidence"]
            # Real plan steps, and honestly flagged as not persisted.
            assert report["plan"]["steps"], "plan must carry real steps"
            assert report["plan"]["persisted"] is False
            assert report["plan"]["plan_id"] == "DRY-RUN-NOT-PERSISTED"
            # The evidence-request half: which gates would have to accept
            # this stage's output. INTAKE has real mapped gates.
            assert report["required_gates"], "stage's real required gates must be reported"
            assert isinstance(report["entry_checklist"], dict)
            # The actual prompt that would have been sent.
            assert stage in report["prompt"]
            assert len(report["prompt"]) > 200

            # --- and nothing executed ------------------------------------
            assert h.adapter.calls == 0, "no adapter call may happen in dry-run"
            # No plan file created (the real path would have created one).
            plans_after = sorted(p.name for p in (tmp / ".dv-harness" / "plans").glob("*.json"))
            assert plans_after == plans_before
            # No state mutation at all: attempts/status/started_at untouched.
            assert (tmp / ".dv-harness" / "state.json").read_text(encoding="utf-8") == before_state
            assert h.state.stages[stage]["attempts"] == 0
            assert h.state.stages[stage]["status"] == Status.NOT_STARTED.value
            # No events appended.
            events_after = events_path.read_text(encoding="utf-8") if events_path.exists() else ""
            assert events_after == events_before
            # No telemetry record, no delegated agent task, no react record.
            assert not list((tmp / ".dv-harness" / "telemetry").rglob("*.json")) or \
                   not any("stage" in p.name for p in (tmp / ".dv-harness" / "telemetry").rglob("*.json"))
            assert not (tmp / ".dv-harness" / "react" / stage).exists()
            # No auto-checkpoint: nothing transitioned, so there is nothing
            # to checkpoint.
            assert session_snapshot.list_auto_checkpoints(tmp) == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dry_run_submits_no_lsf_job(self):
        """run_stage() has no bsub call site at all -- every real submission
        goes through `dv-harness lsf-submit` -> lsf_client.bsub_submit*().
        This asserts that invariant rather than trusting it, so a future
        change that wires a submission into the stage path cannot silently
        make dry-run start dispatching real farm jobs."""
        tmp, h = _fresh()
        try:
            from dv_harness import lsf_client
            submitted = []

            def _boom(*a, **kw):
                submitted.append((a, kw))
                raise AssertionError("an LSF job was submitted during a dry-run")

            orig_submit = lsf_client.bsub_submit
            orig_preflight = lsf_client.bsub_submit_with_preflight
            lsf_client.bsub_submit = _boom
            lsf_client.bsub_submit_with_preflight = _boom
            try:
                h.adapter = _ExplodingAdapter()
                h.run_stage("run the regression", stage=Stage.VERIFY.value, dry_run=True)
            finally:
                lsf_client.bsub_submit = orig_submit
                lsf_client.bsub_submit_with_preflight = orig_preflight
            assert submitted == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_config_toggle_enables_dry_run_without_the_cli_flag(self):
        """config.json's dry_run.enabled is the "導入初期與大改動前必用" switch:
        every stage becomes plan-only until it is turned back off."""
        tmp, h = _fresh()
        try:
            h.cfg["dry_run"]["enabled"] = True
            h.adapter = _ExplodingAdapter()
            result = h.run_stage("goal", stage=Stage.INTAKE.value)  # NO dry_run= argument
            assert result.ok and "DRY_RUN" in result.text
            assert h.adapter.calls == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_takeover_still_outranks_dry_run(self):
        """Human Override is always valid: a TAKEOVER blocks even a dry-run,
        because the takeover check runs first by design."""
        tmp, h = _fresh()
        try:
            from dv_harness.control_plane import ControlPlane
            ControlPlane(tmp).takeover(Stage.INTAKE.value, "hands off, I'm debugging")
            h.adapter = _ExplodingAdapter()
            result = h.run_stage("goal", stage=Stage.INTAKE.value, dry_run=True)
            assert result.ok is False
            assert "BLOCKED_BY_TAKEOVER" in result.text
            assert not (tmp / ".dv-harness" / "dry_run").exists()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dry_run_plan_matches_the_prompt_a_real_run_would_send(self):
        """The equivalence that makes a dry-run worth reviewing: the reported
        prompt is the same one the real path builds, because both call
        _gather_stage_context(). Compared against the real run's own captured
        prompt, not against a hand-written expectation."""
        tmp, h = _fresh()
        try:
            stage = Stage.INTAKE.value
            dry = h.run_stage("shared goal text", stage=stage, dry_run=True)
            dry_prompt = dry.raw["prompt"]

            captured = {}

            class _CaptureAdapter:
                """Captures only the FIRST prompt: a gate miss legitimately
                sends the inner ReAct loop back to the adapter with its own
                reflection prompts, which are not the stage prompt under
                comparison here."""
                def run(self, **kwargs):
                    captured.setdefault("prompt", kwargs["prompt"])
                    return AgentResult(ok=True, text="no evidence", raw={}, session_id=None)

            h.adapter = _CaptureAdapter()
            h.run_stage("shared goal text", stage=stage)
            real_prompt = captured["prompt"]

            # The plan section is the part a human actually reviews in a
            # dry-run -- resolved route/agent, protocol and environment-mode
            # decisions, the plan steps, and the Blackboard snapshot. It must
            # match the real run's byte for byte, modulo exactly TWO
            # identifiers the dry-run deliberately does not allocate: the
            # real run persists a PLAN-XXXXXXXX and delegates a
            # TASK-XXXXXXXX, where a dry-run must do neither (a persisted
            # plan would look "already in flight" to a later real run, and a
            # real task would take a blackboard-topic lock nothing releases).
            marker = "[Harness Plan-and-Execute"
            assert marker in dry_prompt and marker in real_prompt

            def _plan_section(text):
                return "\n".join(
                    l for l in text[text.index(marker):].splitlines()
                    if not any(m in l for m in
                               ("PLAN-", "TASK-", "DRY-RUN-NOT-PERSISTED", "DRY-RUN-NOT-DELEGATED")))

            assert _plan_section(dry_prompt) == _plan_section(real_prompt)
            # ...and within the plan section, ONLY those two id lines differ.
            dry_sec = dry_prompt[dry_prompt.index(marker):].splitlines()
            real_sec = real_prompt[real_prompt.index(marker):].splitlines()
            assert len(dry_sec) == len(real_sec)
            differing = [(a, b) for a, b in zip(dry_sec, real_sec) if a != b]
            assert len(differing) == 2, differing

            # The stage-instruction preamble also matches, EXCEPT for the
            # embedded `dv-harness status` snapshot. That difference is real
            # and correct, not drift: at plan time the stage genuinely has
            # not started (NOT_STARTED), and at execution time it genuinely
            # is RUNNING. A dry-run that claimed RUNNING would be reporting a
            # state that never existed.
            head_marker = '{\n  "project"'
            assert dry_prompt[:dry_prompt.index(head_marker)] == \
                   real_prompt[:real_prompt.index(head_marker)]
            assert '"overall_status": "NOT_STARTED"' in dry_prompt
            assert '"overall_status": "RUNNING"' in real_prompt
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 2. checkpoint 與回滾 -- automatic snapshots + bounded retention
# ===========================================================================


class TestAutoCheckpoint:

    def test_stage_transition_writes_an_auto_checkpoint(self):
        """The gap this closes: save_session() was real but fired ONLY on an
        explicit `dv-harness save-session`, so an agent that went off the
        rails had a recovery point only by luck."""
        tmp, h = _fresh()
        try:
            assert session_snapshot.list_auto_checkpoints(tmp) == []
            h.adapter = _CountingAdapter(ok=True, text="no gate evidence here")
            h.run_stage("goal", stage=Stage.INTAKE.value)

            checkpoints = session_snapshot.list_auto_checkpoints(tmp)
            assert len(checkpoints) == 1
            cp = checkpoints[0]
            assert cp["name"].startswith(session_snapshot.AUTO_CHECKPOINT_PREFIX)
            assert Stage.INTAKE.value in cp["name"]
            # It is a REAL snapshot, not an empty marker directory: the same
            # manifest a hand-made save-session produces.
            assert "state.json" in cp["files"]
            assert cp["current_stage"]
            snap_dir = tmp / ".dv-harness" / "sessions" / cp["name"]
            assert (snap_dir / "state.json").exists()
            assert (snap_dir / "session_manifest.json").exists()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_checkpoint_is_taken_on_a_failed_attempt_too(self):
        """"agent 走偏時不必從頭" -- the non-PASS case is exactly the one a
        human most needs to roll back from, so a FAIL must checkpoint too."""
        tmp, h = _fresh()
        try:
            h.adapter = _CountingAdapter(ok=False, text="", stderr="adapter blew up")
            h.run_stage("goal", stage=Stage.INTAKE.value)
            assert h.state.stages[Stage.INTAKE.value]["status"] == Status.FAIL.value
            assert len(session_snapshot.list_auto_checkpoints(tmp)) == 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_auto_checkpoint_can_be_disabled(self):
        tmp, h = _fresh()
        try:
            h.cfg["auto_checkpoint"]["enabled"] = False
            h.adapter = _CountingAdapter(ok=True, text="nothing")
            h.run_stage("goal", stage=Stage.INTAKE.value)
            assert session_snapshot.list_auto_checkpoints(tmp) == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_retention_keeps_only_the_newest_n_auto_checkpoints(self):
        tmp, _h = _fresh(with_graph=False)
        try:
            for i in range(5):
                session_snapshot.save_auto_checkpoint(
                    tmp, stage="VERIFY", attempt=i, keep=3)
            names = [m["name"] for m in session_snapshot.list_auto_checkpoints(tmp)]
            assert len(names) == 3, f"retention should have bounded this to 3, got {names}"
            # The three kept are the NEWEST three, i.e. attempts 2/3/4.
            assert all(("_2_" in n or "_3_" in n or "_4_" in n) for n in names), names
            # And they really are gone from disk, not just from the listing.
            on_disk = sorted(p.name for p in (tmp / ".dv-harness" / "sessions").iterdir())
            assert sorted(names) == on_disk
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_retention_never_deletes_human_named_or_pre_restore_snapshots(self):
        """The safety property that makes automatic pruning acceptable at
        all: a human's deliberately-named snapshot is a stable label, and a
        _pre_restore_ backup is the undo of a destructive restore. Neither
        may ever be swept away by auto-checkpoint retention."""
        tmp, _h = _fresh(with_graph=False)
        try:
            session_snapshot.save_session(tmp, name="golden-baseline",
                                           note="hand-made, must survive")
            session_snapshot.save_session(tmp, name="_pre_restore_1700000000",
                                           note="restore undo backup, must survive")
            for i in range(4):
                session_snapshot.save_auto_checkpoint(tmp, stage="VERIFY", attempt=i, keep=1)

            surviving = sorted(p.name for p in (tmp / ".dv-harness" / "sessions").iterdir())
            assert "golden-baseline" in surviving
            assert "_pre_restore_1700000000" in surviving
            assert len(session_snapshot.list_auto_checkpoints(tmp)) == 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_keep_zero_disables_pruning_rather_than_deleting_everything(self):
        """A misconfigured keep must fail toward preserving recovery points,
        never toward destroying them."""
        tmp, _h = _fresh(with_graph=False)
        try:
            for i in range(3):
                session_snapshot.save_auto_checkpoint(tmp, stage="BUILD", attempt=i, keep=0)
            assert len(session_snapshot.list_auto_checkpoints(tmp)) == 3
            assert session_snapshot.prune_auto_checkpoints(tmp, keep=0) == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_auto_checkpoint_is_restorable_by_the_existing_restore_path(self):
        """A checkpoint is only worth taking if it actually rolls back. Uses
        session_snapshot.restore_session() unchanged -- the auto-checkpoint
        feature adds no second restore path."""
        tmp, h = _fresh(with_graph=False)
        try:
            h.state.current_stage = Stage.BUILD.value
            h.store.save(h.state)
            manifest = session_snapshot.save_auto_checkpoint(tmp, stage="BUILD", attempt=1)

            h.state.current_stage = Stage.SIGNOFF.value
            h.store.save(h.state)

            result = session_snapshot.restore_session(tmp, manifest["name"])
            assert result["restored"] == manifest["name"]
            reloaded = DVHarness(tmp)
            assert reloaded.state.current_stage == Stage.BUILD.value
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 3. 降級路徑 -- DEGRADED mode
# ===========================================================================


class TestDegradationTriggers:
    """Each of the three real conditions, simulated at the level it really
    occurs, then driven through run_stage()."""

    def test_repeated_adapter_failure_enters_degraded(self):
        """(a) Claude API 不可用. The counter is fed by run_stage()'s own
        existing ADAPTER_FAIL branch -- no parallel retry mechanism."""
        tmp, h = _fresh()
        try:
            h.cfg["degradation"]["adapter_failure_threshold"] = 2
            h.adapter = _CountingAdapter(ok=False, stderr="connection refused")

            h.run_stage("goal", stage=Stage.INTAKE.value)
            assert degradation.is_degraded(tmp) is False, "one failure must not degrade"
            assert degradation.load_state(tmp)["adapter_failure_streak"] == 1

            h.run_stage("goal", stage=Stage.INTAKE.value)
            assert degradation.is_degraded(tmp) is True
            assert degradation.TRIGGER_ADAPTER in degradation.describe(tmp)["triggers"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_successful_adapter_call_resets_the_streak(self):
        tmp, h = _fresh()
        try:
            h.cfg["degradation"]["adapter_failure_threshold"] = 3
            h.adapter = _CountingAdapter(ok=False, stderr="boom")
            h.run_stage("goal", stage=Stage.INTAKE.value)
            assert degradation.load_state(tmp)["adapter_failure_streak"] == 1

            h.adapter = _CountingAdapter(ok=True, text="fine")
            h.run_stage("goal", stage=Stage.INTAKE.value)
            assert degradation.load_state(tmp)["adapter_failure_streak"] == 0
            assert degradation.is_degraded(tmp) is False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_full_eda_license_enters_degraded(self):
        """(b) license 全滿, via preflight.check_license()'s OWN starvation
        branch against real captured lmstat output. No license check is
        reimplemented here or in degradation.py."""
        tmp, h = _fresh()
        try:
            runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_STARVED),          # lmstat
                _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),     # bqueues: healthy
            ])
            h.cfg["preflight"]["license_server"] = "2900@host-a"
            h.cfg["degradation"]["probe_resources"] = True
            h.cfg["degradation"]["probe_min_interval_sec"] = 0
            h.degradation_runner = runner

            degradation.evaluate(tmp, h.cfg, runner=runner)
            detail = degradation.describe(tmp)
            assert detail["degraded"] is True
            assert detail["triggers"] == [degradation.TRIGGER_LICENSE]
            assert "fully checked out" in detail["trigger_details"][degradation.TRIGGER_LICENSE]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_congested_farm_queue_enters_degraded(self):
        """(c) farm 塞車, via preflight.check_queue_health()'s own
        Open:Active criterion against real captured bqueues output."""
        tmp, h = _fresh()
        try:
            runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_HEADER),           # license: healthy
                _res(stdout=REAL_BQUEUES_VCS_CONGESTED),       # queue: not Open:Active
            ])
            h.cfg["preflight"]["license_server"] = "2900@host-a"
            h.cfg["degradation"]["probe_resources"] = True
            h.cfg["degradation"]["probe_min_interval_sec"] = 0

            degradation.evaluate(tmp, h.cfg, runner=runner)
            detail = degradation.describe(tmp)
            assert detail["degraded"] is True
            assert detail["triggers"] == [degradation.TRIGGER_QUEUE]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unconfigured_license_server_does_not_fabricate_a_degraded_state(self):
        """The GATE blocks on an unconfigured license ("沒過就 BLOCKED"); the
        MONITOR must not, because "nobody configured a license server" is not
        evidence that the license is full. degradation.probe_resources()
        forces require_license_configured=False so preflight reports its own
        SKIP, and SKIP never triggers."""
        tmp, h = _fresh()
        try:
            runner = _ScriptedRunner([_res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE)])
            h.cfg["preflight"]["license_server"] = ""     # the default
            h.cfg["degradation"]["probe_resources"] = True
            h.cfg["degradation"]["probe_min_interval_sec"] = 0

            outcomes = degradation.probe_resources(h.cfg, runner=runner)
            license_outcome = next(o for o in outcomes if o.name == "eda_license")
            assert license_outcome.status == "SKIP"

            degradation.evaluate(tmp, h.cfg, runner=_ScriptedRunner([
                _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE)]))
            assert degradation.is_degraded(tmp) is False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDegradedBehaviour:
    """What DEGRADED actually changes: 只收集資料、不做判斷."""

    def _degrade(self, tmp, h, trigger=degradation.TRIGGER_QUEUE, detail="farm jammed"):
        degradation.force_trigger(tmp, trigger, detail)
        assert degradation.is_degraded(tmp)

    def test_degraded_makes_no_judgment_call_but_keeps_collecting_data(self):
        tmp, h = _fresh()
        try:
            self._degrade(tmp, h)
            h.adapter = _ExplodingAdapter()

            checkpoints_before = len(session_snapshot.list_auto_checkpoints(tmp))
            result = h.run_stage("goal", stage=Stage.INTAKE.value)

            # --- 不做判斷 ------------------------------------------------
            assert result.ok is False
            assert result.raw["degraded"] is True
            assert "DEGRADED" in result.text
            assert h.adapter.calls == 0, "no judgment-requiring adapter call while degraded"
            # The stage never even started an attempt.
            assert h.state.stages[Stage.INTAKE.value]["attempts"] == 0
            assert not (tmp / ".dv-harness" / "react" / Stage.INTAKE.value).exists()

            # --- 只收集資料 ----------------------------------------------
            # A real snapshot was persisted...
            assert len(session_snapshot.list_auto_checkpoints(tmp)) == checkpoints_before + 1
            # ...and a real, inspectable event recorded WHY.
            events = [json.loads(l) for l in
                      (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            cycles = [e for e in events if e.get("event") == "DEGRADED_CYCLE"]
            assert len(cycles) == 1
            assert cycles[0]["triggers"] == [degradation.TRIGGER_QUEUE]
            assert "farm jammed" in cycles[0]["trigger_details"][degradation.TRIGGER_QUEUE]
            assert degradation.describe(tmp)["degraded_cycles"] == 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_degraded_is_observable_in_dv_harness_status(self):
        """Explicit and observable, not a silent internal branch: `dv-harness
        status` prints DVHarness.summary() verbatim."""
        tmp, h = _fresh()
        try:
            assert json.loads(h.summary())["operation_mode"] == "NORMAL"
            self._degrade(tmp, h, degradation.TRIGGER_LICENSE, "VCSRuntime fully checked out")

            status = json.loads(h.summary())
            assert status["operation_mode"] == "DEGRADED"
            assert status["degraded"] is True
            assert status["degraded_triggers"] == [degradation.TRIGGER_LICENSE]
            assert "fully checked out" in status["degraded_trigger_details"][degradation.TRIGGER_LICENSE]
            assert status["degraded_since"] is not None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_exits_degraded_and_resumes_normal_operation_once_cleared(self):
        """The condition clears -> the harness resumes on its own, in the
        very next run_stage(), with no human un-sticking it."""
        tmp, h = _fresh()
        try:
            h.cfg["preflight"]["license_server"] = "2900@host-a"
            h.cfg["degradation"]["probe_resources"] = True
            h.cfg["degradation"]["probe_min_interval_sec"] = 0

            # Round 1: the farm really is congested -> DEGRADED, no adapter call.
            h.degradation_runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_HEADER),
                _res(stdout=REAL_BQUEUES_VCS_CONGESTED),
            ])
            h.adapter = _ExplodingAdapter()
            first = h.run_stage("goal", stage=Stage.INTAKE.value)
            assert first.raw["degraded"] is True
            assert h.adapter.calls == 0

            # Round 2: the queue is Open:Active again -> the SAME call path
            # re-probes, clears, and proceeds to a real attempt.
            h.degradation_runner = _ScriptedRunner([
                _res(stdout=REAL_LMSTAT_VCS_HEADER),
                _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),
            ])
            h.adapter = _CountingAdapter(ok=True, text="back to work")
            second = h.run_stage("goal", stage=Stage.INTAKE.value)

            assert degradation.is_degraded(tmp) is False
            assert json.loads(h.summary())["operation_mode"] == "NORMAL"
            # >= 1, not == 1: on a gate miss the inner ReAct loop legitimately
            # makes further real adapter calls. What matters here is that the
            # adapter was reached at all, which DEGRADED had prevented.
            assert h.adapter.calls >= 1, "normal operation must resume with a real adapter call"
            assert h.state.stages[Stage.INTAKE.value]["attempts"] == 1
            assert second.raw.get("degraded") is not True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_loop_does_not_advance_past_a_degraded_stage(self):
        """Regression for a real bug found in review: _degraded_gate()
        originally set only overall_status, leaving ss["status"] at
        NOT_STARTED. loop()'s final fallthrough is an unconditional
        self.advance(), so a stage that never ran was routed along the
        graph's PASS edge -- a degraded harness silently walked forward
        through the pipeline. It must park on the stage instead."""
        tmp, h = _fresh()
        try:
            h.state.current_stage = Stage.INTAKE.value
            h.store.save(h.state)
            self._degrade(tmp, h)
            h.adapter = _ExplodingAdapter()

            h.loop("goal")

            assert h.state.current_stage == Stage.INTAKE.value, \
                "loop() must not advance while degraded"
            assert h.state.stages[Stage.INTAKE.value]["status"] == Status.WAIT_USER.value
            assert h.state.stages[Stage.INTAKE.value]["attempts"] == 0
            assert h.adapter.calls == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dry_run_still_works_while_degraded(self):
        """Planning is read-only and makes no judgment, so it stays available
        precisely when execution is not -- refusing it would deny the
        operator the one action that still works."""
        tmp, h = _fresh()
        try:
            self._degrade(tmp, h)
            h.adapter = _ExplodingAdapter()
            result = h.run_stage("goal", stage=Stage.INTAKE.value, dry_run=True)
            assert result.ok is True
            assert "DRY_RUN" in result.text
            assert h.adapter.calls == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_degradation_can_be_disabled_entirely(self):
        tmp, h = _fresh()
        try:
            self._degrade(tmp, h)
            h.cfg["degradation"]["enabled"] = False
            h.adapter = _CountingAdapter(ok=True, text="ran anyway")
            h.run_stage("goal", stage=Stage.INTAKE.value)
            assert h.adapter.calls >= 1, "a disabled degradation gate must not block the call"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_disabled_degradation_writes_no_state_file(self):
        """A feature that is switched off should leave no trace on disk --
        including the adapter-outcome bookkeeping, not just the gate."""
        tmp, h = _fresh()
        try:
            h.cfg["degradation"]["enabled"] = False
            h.adapter = _CountingAdapter(ok=False, stderr="boom")
            h.run_stage("goal", stage=Stage.INTAKE.value)
            assert not degradation.state_path(tmp).exists()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDegradationStateFile:
    """Unit-level behaviour of the persisted state itself."""

    def test_entered_at_is_stamped_once_and_survives_further_cycles(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            degradation.force_trigger(tmp, degradation.TRIGGER_QUEUE, "jam")
            first_entered = degradation.load_state(tmp)["entered_at"]
            assert first_entered is not None
            degradation.force_trigger(tmp, degradation.TRIGGER_QUEUE, "still jammed")
            degradation.note_cycle(tmp)
            assert degradation.load_state(tmp)["entered_at"] == first_entered
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_clearing_one_of_two_triggers_stays_degraded(self):
        """A successful adapter call must not promote a license-starved
        project back to NORMAL."""
        tmp = Path(tempfile.mkdtemp())
        try:
            degradation.force_trigger(tmp, degradation.TRIGGER_LICENSE, "full")
            degradation.record_adapter_failure(tmp, {"adapter_failure_threshold": 1})
            assert set(degradation.describe(tmp)["triggers"]) == {
                degradation.TRIGGER_LICENSE, degradation.TRIGGER_ADAPTER}

            degradation.record_adapter_success(tmp)
            detail = degradation.describe(tmp)
            assert detail["triggers"] == [degradation.TRIGGER_LICENSE]
            assert detail["degraded"] is True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_state_file_reads_as_normal(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            assert degradation.is_degraded(tmp) is False
            assert degradation.describe(tmp)["mode"] == degradation.NORMAL
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
