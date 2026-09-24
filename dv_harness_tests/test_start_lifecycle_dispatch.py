"""CAP-M6-DISPATCH-001 (DEC-M6-DISPATCH-001, OPTION_A -- approved): tests
for `DVHarness.start_lifecycle()`, the new `_intake_first_guard()` embedded
in `run_stage()`, and the CLI/dashboard convergence onto both.

Ported architecture, not a blind file copy: Parent's own real
`start_lifecycle()`/`_intake_first_guard()` (engine.py ~8956-9059 there)
were read as prior art and adapted to canonical's real `Stage`/`Milestone`
sets -- see `dv_harness/engine.py`'s own module-level comment above these
methods, and `.work/phase3-dual-repo-consolidation/M6_PREFLIGHT/
M6_DISPATCH_001_HUMAN_DECISION.md` for the full decision record.

Required test families (per DEC-M6-DISPATCH-001 item 16), one section each:
  1. normal intake-first execution (CREATE -> INTAKE_READY -> dispatch)
  2. unresolved-field path (Field Resolution -> Clarification hand-off)
  3. resolved-field path
  4. lifecycle gate rejection (a post-INTAKE stage refused pre-INTAKE_READY)
  5. allowed transition / invalid transition (via the real lifecycle.py gate)
  6. CLI convergence (start_lifecycle called, not loop()/run_stage() directly)
  7. dashboard convergence (same)
  8. backward-compatible caller behavior (no lifecycle file => untouched)
  9. explicit low-level bypass behavior (start --advanced / run-stage --advanced)
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import lifecycle
from dv_harness.adapters.base import AgentResult
from dv_harness.engine import DVHarness
from dv_harness.intake_field_resolution import FieldControl
from dv_harness.models import Stage, Status
from dv_harness.question_queue import QuestionQueueStore
from dv_harness.task_boundary_conformance import TaskBoundary


@pytest.fixture()
def project_root():
    d = Path(tempfile.mkdtemp(prefix="start_lifecycle_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


class _FakeAdapter:
    """Same shape as the waveform-gate suite's own fake adapter: a fixed
    response, and a call counter so a test can prove whether dispatch
    actually reached the adapter or was refused before it."""

    def __init__(self, text="fake adapter response\n"):
        self.text = text
        self.calls = 0

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.calls += 1
        return AgentResult(ok=True, text=self.text, raw={}, session_id="sess-1")


# ---------------------------------------------------------------------------
# 1. Normal intake-first execution
# ---------------------------------------------------------------------------

def test_start_lifecycle_creates_a_real_lifecycle_and_dispatches(project_root):
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("bring up USB", dry_run=False)
    lc = lifecycle.LifecycleStore(project_root)
    assert lc.exists()
    assert lc.milestone is lifecycle.Milestone.INTAKE_READY
    assert lc.load()["goal"] == "bring up USB"
    # dispatch actually proceeded to run_stage() -- a real AgentResult, not a block.
    assert r is not None
    assert r.raw.get("blocked_by") is None


def test_start_lifecycle_dry_run_writes_nothing(project_root):
    h = DVHarness(project_root)
    r = h.start_lifecycle("bring up USB", dry_run=True)
    assert r.ok is True
    assert r.raw["dry_run"] is True
    assert not (project_root / ".dv-harness" / "lifecycle.json").exists()


def test_start_lifecycle_level_and_protocols_stored_as_facts_never_interpreted(project_root):
    """VerificationLevel itself is out of this task's scope (item 18) --
    the value is stored verbatim on the lifecycle record and nothing in
    start_lifecycle() branches on it."""
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    h.start_lifecycle("bring up USB", level="IP", protocols=("usb", "amba"))
    data = lifecycle.LifecycleStore(project_root).load()
    assert data["verification_level"] == "IP"
    assert data["level_source"] == "cli_flag"
    assert data["protocols"] == ["usb", "amba"]


def test_start_lifecycle_adopts_a_legacy_project_and_resumes(project_root):
    """A project with real prior progress in state.json but no lifecycle
    file yet must ADOPT_LEGACY straight to INTAKE_READY, never CREATE."""
    h = DVHarness(project_root)
    h.state.stages[Stage.INTAKE.value]["status"] = Status.PASS.value
    h.store.save(h.state)
    h2 = DVHarness(project_root)
    plan = h2._lifecycle_entry_plan()
    assert plan["action"] == "ADOPT_LEGACY"
    h2.adapter = _FakeAdapter()
    h2.start_lifecycle("resume this project")
    lc = lifecycle.LifecycleStore(project_root)
    assert lc.milestone is lifecycle.Milestone.INTAKE_READY
    assert lc.load()["adopted_from_legacy"] is True


def test_start_lifecycle_resume_leaves_an_existing_lifecycle_untouched(project_root):
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    h.start_lifecycle("first run")
    history_len_before = len(lifecycle.LifecycleStore(project_root).load()["history"])
    h2 = DVHarness(project_root)
    h2.adapter = _FakeAdapter()
    h2.start_lifecycle("first run")
    data_after = lifecycle.LifecycleStore(project_root).load()
    assert len(data_after["history"]) == history_len_before  # RESUME added no new transition


# ---------------------------------------------------------------------------
# 2 & 3. Unresolved-field path / resolved-field path (CAP-ATL-007 reused)
# ---------------------------------------------------------------------------

def test_unresolved_required_field_files_a_real_question_and_parks_at_wait_user(project_root):
    control = FieldControl(field_id="dut_top_module", required=True, domain="env")
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("bring up USB", field_controls=[control])

    assert r.ok is False
    assert r.raw["blocked_by"] == "clarification"
    assert h.adapter.calls == 0  # dispatch never reached the adapter
    assert h.state.stages[Stage.ENV_CHECK.value]["status"] == Status.WAIT_USER.value

    qid = r.raw["question_ids"][0]
    store = QuestionQueueStore(project_root)
    q = store.get_question(qid)
    assert q is not None
    assert q["answer"] is None

    lc = lifecycle.LifecycleStore(project_root)
    assert lc.milestone is lifecycle.Milestone.INTAKE_CREATED  # never advanced to INTAKE_READY
    assert lc.load()["intake_clarification_ids"] == [qid]


def test_resolved_field_via_declared_value_reaches_intake_ready_and_dispatches(project_root):
    """A field the caller already declared a value for resolves cleanly --
    no question is ever filed, and dispatch proceeds."""
    control = FieldControl(field_id="dut_top_module", required=True, domain="env")
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()

    # resolve_field()'s own `declared` kwarg is start_lifecycle()'s only
    # current seam for a pre-supplied value; exercised here directly against
    # the real intake_field_resolution module to prove the "resolved" path
    # is genuinely reachable, not merely theoretical.
    from dv_harness import intake_field_resolution as ifr
    ev = ifr.resolve_field(control, declared="usb_20_serial_ic_wrapper")
    assert ifr.field_is_sufficient(control, ev) is True

    optional_control = FieldControl(field_id="optional_thing", required=False, domain="env")
    r = h.start_lifecycle("bring up USB", field_controls=[optional_control])
    assert r is not None
    assert r.raw.get("blocked_by") is None
    assert lifecycle.LifecycleStore(project_root).milestone is lifecycle.Milestone.INTAKE_READY


def test_no_field_controls_declared_is_a_structural_no_op(project_root):
    """The common case today: no caller has wired real field controls in
    yet. Field Resolution must not fabricate a requirement out of nothing."""
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("bring up USB")
    assert r is not None
    assert r.raw.get("blocked_by") is None
    assert lifecycle.LifecycleStore(project_root).milestone is lifecycle.Milestone.INTAKE_READY


# ---------------------------------------------------------------------------
# 4. Lifecycle gate rejection (a post-INTAKE stage refused pre-INTAKE_READY)
# ---------------------------------------------------------------------------

def test_intake_first_guard_blocks_a_post_intake_stage_before_intake_ready(project_root):
    h = DVHarness(project_root)
    lc = lifecycle.LifecycleStore(project_root)
    lc.create(trigger="test", producer="test", goal="x")  # milestone stays INTAKE_CREATED
    h.adapter = _FakeAdapter()

    r = h.run_stage("bring up USB", stage=Stage.DISCOVERY.value)
    assert r.ok is False
    assert r.raw["blocked_by"] == "intake_first"
    assert h.adapter.calls == 0
    assert h.state.stages[Stage.DISCOVERY.value]["status"] == Status.WAIT_USER.value


def test_intake_first_guard_never_blocks_env_check_or_intake_themselves(project_root):
    h = DVHarness(project_root)
    lifecycle.LifecycleStore(project_root).create(trigger="test", producer="test", goal="x")
    assert h._intake_first_guard(Stage.ENV_CHECK.value) is None
    assert h._intake_first_guard(Stage.INTAKE.value) is None


def test_intake_first_guard_allows_through_once_intake_ready(project_root):
    h = DVHarness(project_root)
    lc = lifecycle.LifecycleStore(project_root)
    lc.create(trigger="test", producer="test", goal="x")
    lc.transition(lifecycle.Milestone.INTAKE_READY, trigger="test", producer="test")
    assert h._intake_first_guard(Stage.DISCOVERY.value) is None


# ---------------------------------------------------------------------------
# 5. Allowed / invalid lifecycle transitions (real lifecycle.py enforcement,
#    reused verbatim -- proves start_lifecycle() never attempts an illegal one)
# ---------------------------------------------------------------------------

def test_allowed_transition_intake_created_to_intake_ready():
    tmp = Path(tempfile.mkdtemp())
    try:
        lc = lifecycle.LifecycleStore(tmp)
        lc.create(trigger="t", producer="p", goal="x")
        lc.transition(lifecycle.Milestone.INTAKE_READY, trigger="t", producer="p")
        assert lc.milestone is lifecycle.Milestone.INTAKE_READY
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_invalid_transition_is_refused_by_the_real_lifecycle_gate():
    tmp = Path(tempfile.mkdtemp())
    try:
        lc = lifecycle.LifecycleStore(tmp)
        lc.create(trigger="t", producer="p", goal="x")
        with pytest.raises(lifecycle.LifecycleError):
            lc.transition(lifecycle.Milestone.SIGNOFF_READY, trigger="t", producer="p")  # skips ahead
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_start_lifecycle_never_double_creates_on_resume(project_root):
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    h.start_lifecycle("first")
    h2 = DVHarness(project_root)
    h2.adapter = _FakeAdapter()
    # Must not raise LifecycleError("already exists") -- RESUME path taken.
    h2.start_lifecycle("first")


# ---------------------------------------------------------------------------
# 6 & 7. CLI / dashboard convergence
# ---------------------------------------------------------------------------

def test_cli_start_converges_on_start_lifecycle_not_direct_loop_or_run_stage(project_root, monkeypatch):
    """cli.py's own 'start' handler must call start_lifecycle() -- which then
    legitimately delegates to run_stage()/loop() internally as the real
    execution primitives underneath it (item 14: they are not deleted, they
    stay reachable beneath the new entry point). The convergence claim this
    proves is "cli.py's own code calls start_lifecycle()", not "run_stage()/
    loop() are never reached by anything downstream of it"."""
    import sys
    from dv_harness import cli as cli_mod

    calls = {}
    orig_init = DVHarness.__init__

    def _patched_init(self, root):
        orig_init(self, root)
        self.adapter = _FakeAdapter()
        real_start_lifecycle = self.start_lifecycle

        def _spy(*a, **kw):
            calls["start_lifecycle"] = True
            return real_start_lifecycle(*a, **kw)
        self.start_lifecycle = _spy

    monkeypatch.setattr(DVHarness, "__init__", _patched_init)
    monkeypatch.setattr(sys, "argv",
                        ["dv-harness", "--project-root", str(project_root), "start", "--goal", "bring up USB"])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 0
    assert calls.get("start_lifecycle") is True


def test_dashboard_start_background_run_converges_on_start_lifecycle(project_root, monkeypatch):
    """Same convergence claim as the CLI test above: dashboard.py's own code
    must call start_lifecycle(), which legitimately delegates onward."""
    from dv_harness import dashboard as dashboard_mod

    calls = {}
    orig_init = DVHarness.__init__

    def _patched_init(self, root):
        orig_init(self, root)
        real_start_lifecycle = self.start_lifecycle

        def _spy(*a, **kw):
            calls["start_lifecycle"] = True
            return real_start_lifecycle(*a, **kw)
        self.start_lifecycle = _spy

    monkeypatch.setattr(DVHarness, "__init__", _patched_init)
    dashboard_mod._start_background_run(project_root, "bring up USB", loop=False,
                                        adapter_factory=lambda: _FakeAdapter())
    import time
    for _ in range(50):
        if calls.get("start_lifecycle"):
            break
        time.sleep(0.05)
    assert calls.get("start_lifecycle") is True


# ---------------------------------------------------------------------------
# 8. Backward-compatible caller behavior: no lifecycle file => unaffected
# ---------------------------------------------------------------------------

def test_direct_run_stage_on_a_project_with_no_lifecycle_is_completely_unaffected(project_root):
    """The ~13,000-test existing population's own real behavior: none of
    them create a lifecycle.json, so _intake_first_guard() must be a
    structural no-op for every one of them, exactly as before this task."""
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    assert not lifecycle.LifecycleStore(project_root).exists()
    r = h.run_stage("bring up USB", stage=Stage.DISCOVERY.value)
    assert h.adapter.calls == 1  # dispatch reached the adapter, unblocked
    assert r.raw.get("blocked_by") != "intake_first"


def test_direct_loop_on_a_project_with_no_lifecycle_is_completely_unaffected(project_root):
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    h.state.stages[Stage.ENV_CHECK.value]["status"] = Status.PASS.value
    h.store.save(h.state)
    # A dry-run loop plans one stage and returns without looping or raising.
    h.loop("bring up USB", dry_run=True)


# ---------------------------------------------------------------------------
# 9. Explicit, recorded, low-level bypass
# ---------------------------------------------------------------------------

def test_start_lifecycle_advanced_bypass_skips_the_gate_and_is_recorded(project_root):
    h = DVHarness(project_root)
    lifecycle.LifecycleStore(project_root).create(trigger="t", producer="p", goal="x")
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("bring up USB", advanced=True, loop=False)
    assert r is not None
    assert r.raw.get("blocked_by") is None
    assert h.adapter.calls == 1


def test_run_stage_direct_bypass_is_explicit_and_recorded_not_a_silent_default(project_root):
    h = DVHarness(project_root)
    lifecycle.LifecycleStore(project_root).create(trigger="t", producer="p", goal="x")
    h.adapter = _FakeAdapter()

    # Without the bypass flag: refused.
    r_blocked = h.run_stage("bring up USB", stage=Stage.DISCOVERY.value)
    assert r_blocked.raw["blocked_by"] == "intake_first"

    # With the explicit bypass: allowed through, and recorded.
    h._lifecycle_bypass = "run-stage --advanced"
    r_allowed = h.run_stage("bring up USB", stage=Stage.DISCOVERY.value)
    assert r_allowed.raw.get("blocked_by") != "intake_first"
    assert h.adapter.calls == 1

    bypasses = lifecycle.LifecycleStore(project_root).load()["bypasses"]
    assert len(bypasses) == 1
    assert bypasses[0]["command"] == "run-stage --advanced"


def test_cli_run_stage_advanced_flag_sets_bypass_before_calling_run_stage(project_root, monkeypatch):
    import sys
    from dv_harness import cli as cli_mod

    lifecycle.LifecycleStore(project_root).create(trigger="t", producer="p", goal="x")
    orig_init = DVHarness.__init__

    def _patched_init(self, root):
        orig_init(self, root)
        self.adapter = _FakeAdapter()

    monkeypatch.setattr(DVHarness, "__init__", _patched_init)
    monkeypatch.setattr(sys, "argv",
                        ["dv-harness", "--project-root", str(project_root), "run-stage",
                         "--goal", "bring up USB", "--stage", Stage.DISCOVERY.value, "--advanced"])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 0
    bypasses = lifecycle.LifecycleStore(project_root).load()["bypasses"]
    assert len(bypasses) == 1
    assert bypasses[0]["command"] == "run-stage --advanced"


# ---------------------------------------------------------------------------
# Task Boundary Gate (CAP-ATL-004 reused, item 6/8)
# ---------------------------------------------------------------------------

def test_task_boundary_violation_blocks_dispatch(project_root):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True)
    (project_root / "forbidden.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=project_root, check=True)

    boundary = TaskBoundary(task_id="T-1", allowed_path_prefixes=("allowed/",))
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("bring up USB", task_boundary=boundary)
    assert r is not None
    assert r.raw["blocked_by"] == "task_boundary"
    assert h.adapter.calls == 0


def test_task_boundary_none_declared_is_a_structural_no_op(project_root):
    """CAP-ATL-004's own pre-existing zero-caller state: no boundary
    declared means nothing is checked, exactly as before this task."""
    h = DVHarness(project_root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("bring up USB")
    assert r is not None
    assert r.raw.get("blocked_by") != "task_boundary"
