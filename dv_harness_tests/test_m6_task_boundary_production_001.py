"""M6-TASK-BOUNDARY-PRODUCTION-001: production-connects the existing
CAP-ATL-004 Task Boundary foundation (`dv_harness/task_boundary_
conformance.py`) into the real, supported M6 Golden Workflow.

Before this task, `task_boundary_conformance.check_working_tree_
conformance()` was already wired INSIDE `start_lifecycle()` (CAP-ATL-004,
item 6/8) and already correctly blocked/passed a call given a real
Python-API-supplied `TaskBoundary` (`test_start_lifecycle_dispatch.py`'s
own `test_task_boundary_violation_blocks_dispatch`/`test_task_boundary_
none_declared_is_a_structural_no_op`). What was MISSING was a real,
supported PRODUCTION entry point: no CLI flag and no dashboard JSON field
could ever construct a real `TaskBoundary` and pass it through -- every
real caller (CLI, dashboard, all 11 PROTOCOL_BUILDERS skills) always got
`task_boundary=None`, a structural no-op, never a real gate.

This file proves the closed edge: CLI `--task-boundary-*` flags / dashboard
`task_boundary` JSON field -> real `TaskBoundary.from_dict()` (CAP-ATL-004,
reused verbatim, never re-implemented) -> `start_lifecycle(task_boundary=
...)`'s own, already-real check -> the boundary RESULT genuinely governs
whether VerificationLevel routing / `create_environment()` ever runs, for
all three levels (IP/SUBSYSTEM/SYSTEM_LEVEL).

IMPORTANT DESIGN FACT, disclosed rather than assumed: unlike `protocol`/
`role`/`verification_level`, TaskBoundary is NOT a required generation
field. CAP-ATL-004's own module docstring is explicit that a `TaskBoundary`
is "a plain, caller-declared input... never derived" -- so omitting it
(the pre-existing default, still true after this task) is not an
UNCONTROLLED_BYPASS, it is the module's own documented, correct
"nothing declared, nothing checked" behavior. Production connectivity for
this task means: WHEN a real caller supplies one through a real supported
entry point, the result genuinely gates the downstream path -- proven
below for CLI, dashboard, and the PROTOCOL_BUILDERS invocation shape, for
both the PASS and the FAIL (blocking) case.

Every test below that needs a real boundary verdict (not just the
structural no-op) runs against a REAL git repo in a temp dir -- the same
real-git-over-tmp_path discipline `test_task_boundary_conformance.py`/
`test_start_lifecycle_dispatch.py` already established, never a synthetic
git-status fixture.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness.adapters.base import AgentResult
from dv_harness.engine import DVHarness
from dv_harness.lifecycle import LifecycleStore
from dv_harness.models import Status
from dv_harness.question_queue import QuestionQueueStore
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


@pytest.fixture()
def repo():
    """A real, throwaway, git-initialized project root with one committed
    file -- the SAME fixture shape `test_task_boundary_conformance.py`/
    `test_start_lifecycle_dispatch.py` already use, so the boundary check
    is exercised against real git evidence, never a mock."""
    d = Path(tempfile.mkdtemp(prefix="tb_prod_"))
    try:
        _run(d, "init", "-q")
        _run(d, "config", "user.email", "test@example.com")
        _run(d, "config", "user.name", "Test")
        (d / "README.md").write_text("seed\n", encoding="utf-8")
        _run(d, "add", "-A")
        _run(d, "commit", "-q", "-m", "initial")
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


class _FakeAdapter:
    def __init__(self):
        self.calls = 0

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.calls += 1
        return AgentResult(ok=True, text="fake\n", raw={}, session_id="s1")


def _pcie_manifest(**extra):
    m = {"clocks": [{"name": "refclk"}], "resets": [{"name": "perst_n"}],
         "smoke_tests": [{"name": "link_training"}]}
    m.update(extra)
    return m


# ---------------------------------------------------------------------------
# A0. exempt_path_prefixes -- the real, current-scope defect found and fixed
#     during this task's own re-verification (P5 FIND->FIX->VERIFY): a real
#     caller's declared boundary would ALWAYS spuriously VIOLATE on
#     .dv-harness/'s own required-every-call bookkeeping writes, since no
#     prior test ever exercised a real PASS path through start_lifecycle()'s
#     own state-writing flow (only the trivial FAIL path was tested before
#     this task). Unit-level proof of the fix at task_boundary_
#     conformance.py's own new, additive parameter.
# ---------------------------------------------------------------------------

def test_exempt_path_prefixes_removes_matching_entries_from_evidence_before_classification(repo):
    from dv_harness import task_boundary_conformance as tbc

    (repo / "scratch").mkdir()
    (repo / "scratch" / "internal.json").write_text("{}", encoding="utf-8")
    (repo / "unrelated.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="EXEMPT-1", allowed_path_prefixes=())
    # Without the exemption: both files are OUTSIDE_DECLARED_BOUNDARY -> VIOLATION.
    before = tbc.check_working_tree_conformance(repo, boundary)
    assert before["verdict"] == tbc.VERDICT_VIOLATION
    assert {f["path"] for f in before["findings"]} == {"scratch/internal.json", "unrelated.txt"}
    # With "scratch" exempt: only unrelated.txt remains, still a VIOLATION
    # (exempt is not the same as allowed), but the exempt path is genuinely
    # invisible -- confirmed by its absence from findings entirely.
    after = tbc.check_working_tree_conformance(repo, boundary, exempt_path_prefixes=("scratch",))
    assert after["verdict"] == tbc.VERDICT_VIOLATION
    assert {f["path"] for f in after["findings"]} == {"unrelated.txt"}


def test_exempt_path_prefixes_default_is_a_true_no_op(repo):
    from dv_harness import task_boundary_conformance as tbc

    (repo / "x.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="NOEXEMPT", allowed_path_prefixes=())
    a = tbc.check_working_tree_conformance(repo, boundary)
    b = tbc.check_working_tree_conformance(repo, boundary, exempt_path_prefixes=())
    assert a == b


def test_exempt_path_prefixes_is_not_the_same_as_allowed_forbidden_still_wins_elsewhere(repo):
    """An exempt path is invisible; a merely-allowed path is still subject
    to forbidden_paths/require_new_file. Confirms the two are genuinely
    distinct mechanisms, not aliases."""
    from dv_harness import task_boundary_conformance as tbc

    (repo / "out").mkdir()
    (repo / "out" / "keep.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="DISTINCT", allowed_path_prefixes=("out",),
                            forbidden_paths=("out/keep.txt",))
    result = tbc.check_working_tree_conformance(repo, boundary, exempt_path_prefixes=())
    assert result["verdict"] == tbc.VERDICT_VIOLATION  # forbidden wins over allowed
    result_exempt = tbc.check_working_tree_conformance(repo, boundary, exempt_path_prefixes=("out/keep.txt",))
    assert result_exempt["verdict"] == tbc.VERDICT_NO_CHANGES  # exempt beats forbidden: invisible


def test_dv_harness_bookkeeping_is_exempt_by_default_inside_start_lifecycle(repo):
    """The actual production fix: start_lifecycle()'s own real Task
    Boundary call site passes exempt_path_prefixes=(".dv-harness",) -- a
    caller's declared boundary genuinely never has to know about the
    harness's own control-plane directory."""
    boundary = TaskBoundary(task_id="DVH-EXEMPT", allowed_path_prefixes=())
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("ordinary run, no generation", task_boundary=boundary)
    # .dv-harness/ was written by this very call (lc.create()/state.save())
    # yet the boundary -- which allows NOTHING -- still held, proving those
    # writes never reached classification at all.
    assert r is not None
    assert r.raw.get("blocked_by") != "task_boundary"


# ---------------------------------------------------------------------------
# A. start_lifecycle() production PASS/FAIL, real git evidence, real
#    generation dispatch downstream (the core mechanism, Python-API level)
# ---------------------------------------------------------------------------

def test_task_boundary_pass_with_real_in_boundary_evidence_still_reaches_generation(repo):
    """Not just the trivial empty-tree case: a real, in-boundary uncommitted
    change is present, the boundary genuinely HOLDS (not NO_CHANGES), and
    generation still runs."""
    (repo / "notes.md").write_text("scratch\n", encoding="utf-8")
    boundary = TaskBoundary(task_id="T-PASS", allowed_path_prefixes=("notes.md",))
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build PCIe env", protocols=["pcie"], role="ep", level="subsystem",
                          task_boundary=boundary,
                          generation_request=_pcie_manifest(), generation_out_dir=repo / "out")
    assert r.ok is True, r.text
    assert r.raw["environment_mode"] == "SUBSYSTEM_MODE"
    assert (repo / "out" / "environment_manifest.json").exists()


def test_task_boundary_violation_blocks_generation_before_verification_level_routing(repo):
    """Ordering proof (dispatch section 13): a rejected Task Boundary must
    prevent generation entirely -- VerificationLevel routing/create_
    environment() must never run, even though protocol/role/level all
    resolve cleanly."""
    (repo / "out_of_scope.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="T-FAIL", allowed_path_prefixes=("only_this_dir/",))
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build PCIe env", protocols=["pcie"], role="ep", level="subsystem",
                          task_boundary=boundary,
                          generation_request=_pcie_manifest(), generation_out_dir=repo / "out")
    assert r.ok is False
    assert r.raw["blocked_by"] == "task_boundary"
    assert r.raw["task_id"] == "T-FAIL"
    assert not (repo / "out").exists()
    assert h.adapter.calls == 0


def test_task_boundary_forbidden_path_blocks_even_when_nested_under_an_allowed_prefix(repo):
    (repo / "out").mkdir()
    (repo / "out" / "secret.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="T-FORBID", allowed_path_prefixes=("out",),
                            forbidden_paths=("out/secret.txt",))
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build PCIe env", protocols=["pcie"], role="ep", level="subsystem",
                          task_boundary=boundary,
                          generation_request=_pcie_manifest(), generation_out_dir=repo / "out2")
    assert r.ok is False
    assert r.raw["blocked_by"] == "task_boundary"
    findings = {f["path"]: f["classification"] for f in r.raw["findings"]}
    assert findings["out/secret.txt"] == "FORBIDDEN_PATH_TOUCHED"


# ---------------------------------------------------------------------------
# B. CLI production path -- real argv, real TaskBoundary.from_dict(), real
#    downstream consumption
# ---------------------------------------------------------------------------

def test_cli_task_boundary_flags_propagate_a_real_taskboundary_into_start_lifecycle(repo, monkeypatch, tmp_path):
    from dv_harness import cli as cli_mod

    (repo / "notes.md").write_text("scratch\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_pcie_manifest()), encoding="utf-8")
    out_dir = repo / "cli_out"

    calls = {}
    orig_init = DVHarness.__init__

    def _patched_init(self, r):
        orig_init(self, r)
        self.adapter = _FakeAdapter()
        real = self.start_lifecycle

        def _spy(*a, **kw):
            calls["kwargs"] = kw
            return real(*a, **kw)
        self.start_lifecycle = _spy
    monkeypatch.setattr(DVHarness, "__init__", _patched_init)
    monkeypatch.setattr(sys, "argv", [
        "dv-harness", "--project-root", str(repo), "start", "--goal", "build PCIe env",
        "--protocols", "pcie", "--dut-role", "ep", "--level", "SUBSYSTEM",
        "--task-boundary-id", "CLI-TB-1", "--task-boundary-allow", "notes.md,cli_out",
        "--generate", "--generate-out", str(out_dir), "--generate-manifest", str(manifest_path),
    ])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 0

    kw = calls["kwargs"]
    tb = kw["task_boundary"]
    assert tb is not None
    assert tb.task_id == "CLI-TB-1"
    assert set(tb.allowed_path_prefixes) == {"notes.md", "cli_out"}
    assert out_dir.exists()


def test_cli_task_boundary_violation_blocks_generation_and_exits_1(repo, monkeypatch, tmp_path):
    from dv_harness import cli as cli_mod

    (repo / "forbidden.txt").write_text("x", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_pcie_manifest()), encoding="utf-8")
    out_dir = repo / "cli_out2"

    orig_init = DVHarness.__init__

    def _patched_init(self, r):
        orig_init(self, r)
        self.adapter = _FakeAdapter()
    monkeypatch.setattr(DVHarness, "__init__", _patched_init)
    monkeypatch.setattr(sys, "argv", [
        "dv-harness", "--project-root", str(repo), "start", "--goal", "build PCIe env",
        "--protocols", "pcie", "--dut-role", "ep", "--level", "SUBSYSTEM",
        "--task-boundary-id", "CLI-TB-2", "--task-boundary-allow", "cli_out2",
        "--generate", "--generate-out", str(out_dir), "--generate-manifest", str(manifest_path),
    ])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 1
    assert not out_dir.exists()


def test_cli_omitting_all_task_boundary_flags_is_byte_identical_to_before(repo, monkeypatch, tmp_path):
    """Regression guard: a caller that supplies none of the 4 new flags
    gets task_boundary=None, exactly as every pre-existing caller does."""
    from dv_harness import cli as cli_mod

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_pcie_manifest()), encoding="utf-8")
    out_dir = repo / "cli_out3"

    calls = {}
    orig_init = DVHarness.__init__

    def _patched_init(self, r):
        orig_init(self, r)
        self.adapter = _FakeAdapter()
        real = self.start_lifecycle

        def _spy(*a, **kw):
            calls["kwargs"] = kw
            return real(*a, **kw)
        self.start_lifecycle = _spy
    monkeypatch.setattr(DVHarness, "__init__", _patched_init)
    monkeypatch.setattr(sys, "argv", [
        "dv-harness", "--project-root", str(repo), "start", "--goal", "build PCIe env",
        "--protocols", "pcie", "--dut-role", "ep", "--level", "SUBSYSTEM",
        "--generate", "--generate-out", str(out_dir), "--generate-manifest", str(manifest_path),
    ])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 0
    assert calls["kwargs"]["task_boundary"] is None


# ---------------------------------------------------------------------------
# C. Dashboard production path -- _start_background_run() is the real
#    function _handle_start() calls with an already-parsed body (the SAME
#    evidence bar test_m6_c1_golden_path_connectivity.py's own dashboard
#    tests already established for protocol/role/level).
# ---------------------------------------------------------------------------

def _wait_until_idle(dashboard_mod, root):
    import time
    for _ in range(200):
        if not dashboard_mod._is_running(root):
            return
        time.sleep(0.01)


def test_dashboard_task_boundary_pass_reaches_generation(repo):
    from dv_harness import dashboard as dashboard_mod

    (repo / "notes.md").write_text("scratch\n", encoding="utf-8")
    boundary = TaskBoundary(task_id="DASH-TB-PASS", allowed_path_prefixes=("notes.md", "dash_out"))
    dashboard_mod._start_background_run(
        repo, "build PCIe env", loop=False, adapter_factory=lambda: _FakeAdapter(),
        protocols=("pcie",), role="ep", level="subsystem", task_boundary=boundary,
        generation_request=_pcie_manifest(), generation_out_dir=repo / "dash_out")
    _wait_until_idle(dashboard_mod, repo)
    assert (repo / "dash_out" / "environment_manifest.json").exists()


def test_dashboard_task_boundary_violation_blocks_generation(repo):
    from dv_harness import dashboard as dashboard_mod

    (repo / "forbidden.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="DASH-TB-FAIL", allowed_path_prefixes=("dash_out2",))
    dashboard_mod._start_background_run(
        repo, "build PCIe env", loop=False, adapter_factory=lambda: _FakeAdapter(),
        protocols=("pcie",), role="ep", level="subsystem", task_boundary=boundary,
        generation_request=_pcie_manifest(), generation_out_dir=repo / "dash_out2")
    _wait_until_idle(dashboard_mod, repo)
    assert not (repo / "dash_out2").exists()


def test_dashboard_handle_start_json_body_shape_converts_via_taskboundary_from_dict():
    """Proves the exact dict shape `_handle_start()` reads from a real HTTP
    POST body round-trips through `TaskBoundary.from_dict()` (CAP-ATL-004,
    reused verbatim) into the identical object `_start_background_run()`
    receives above -- the same conversion dashboard.py's own source now
    performs (see dashboard.py's `_handle_start`, `task_boundary_raw =
    body.get("task_boundary")`)."""
    body_task_boundary = {"task_id": "HTTP-TB-1", "allowed_path_prefixes": ["a/", "b/"],
                          "forbidden_paths": ["a/secret.txt"], "require_new_file": True}
    tb = TaskBoundary.from_dict(body_task_boundary)
    assert tb.task_id == "HTTP-TB-1"
    assert tb.allowed_path_prefixes == ("a", "b")
    assert tb.forbidden_paths == ("a/secret.txt",)
    assert tb.require_new_file is True


def test_dashboard_omitting_task_boundary_json_field_is_byte_identical_to_before(repo):
    from dv_harness import dashboard as dashboard_mod

    fake = _FakeAdapter()
    dashboard_mod._start_background_run(repo, "ordinary run", loop=False,
                                        adapter_factory=lambda: fake)
    _wait_until_idle(dashboard_mod, repo)
    assert QuestionQueueStore(repo).list_questions() == []


# ---------------------------------------------------------------------------
# D. PROTOCOL_BUILDERS invocation shape (the same CLI shape all 11 skills
#    use, per GAP-V2-002 -- proves the governance closure is not regressed
#    and that the SAME entry point reaches Task Boundary when a caller adds
#    the new flags).
# ---------------------------------------------------------------------------

def test_protocol_builder_invocation_shape_reaches_task_boundary_and_generation(repo, monkeypatch, tmp_path, capsys):
    from dv_harness import cli as cli_mod

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_pcie_manifest()), encoding="utf-8")
    out_dir = repo / "pb_out"

    orig_init = DVHarness.__init__

    def _patched_init(self, r):
        orig_init(self, r)
        self.adapter = _FakeAdapter()
    monkeypatch.setattr(DVHarness, "__init__", _patched_init)
    # Exactly the shape `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` use
    # (GAP-V2-002), plus the new --task-boundary-* flags.
    monkeypatch.setattr(sys, "argv", [
        "dv-harness", "--project-root", str(repo), "start", "--goal", "build PCIe env",
        "--protocols", "pcie", "--dut-role", "ep", "--level", "SUBSYSTEM",
        "--task-boundary-id", "PB-TB-1", "--task-boundary-allow", "pb_out",
        "--generate", "--generate-out", str(out_dir), "--generate-manifest", str(manifest_path),
    ])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "OK"
    assert (out_dir / "environment_manifest.json").exists()


# ---------------------------------------------------------------------------
# E. All 3 levels re-proven WITH Task Boundary in the loop (IP/SUBSYSTEM/
#    SYSTEM_LEVEL), plus one Task Boundary FAIL path per the dispatch's own
#    explicit "at least one Task Boundary FAIL path prevents generation"
#    requirement, run against a real, distinct level each time.
# ---------------------------------------------------------------------------

def test_ip_level_with_task_boundary_pass(repo):
    boundary = TaskBoundary(task_id="IP-TB", allowed_path_prefixes=("out_ip",))
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build a standalone PCIe IP env", protocols=["pcie"], role="ep",
                          level="IP", task_boundary=boundary,
                          generation_request=_pcie_manifest(), generation_out_dir=repo / "out_ip")
    assert r.ok is True, r.text
    assert r.raw["environment_mode"] == "IP_MODE"


def test_ip_level_with_task_boundary_fail_blocks_generation(repo):
    (repo / "elsewhere.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="IP-TB-FAIL", allowed_path_prefixes=("out_ip2",))
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build a standalone PCIe IP env", protocols=["pcie"], role="ep",
                          level="IP", task_boundary=boundary,
                          generation_request=_pcie_manifest(), generation_out_dir=repo / "out_ip2")
    assert r.ok is False
    assert r.raw["blocked_by"] == "task_boundary"
    assert not (repo / "out_ip2").exists()


def test_subsystem_level_with_task_boundary_pass(repo):
    boundary = TaskBoundary(task_id="SUB-TB", allowed_path_prefixes=("out_sub",))
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build a PCIe subsystem env", protocols=["pcie"], role="ep",
                          level="SUBSYSTEM", task_boundary=boundary,
                          generation_request=_pcie_manifest(), generation_out_dir=repo / "out_sub")
    assert r.ok is True, r.text
    assert r.raw["environment_mode"] == "SUBSYSTEM_MODE"


def test_subsystem_level_with_task_boundary_fail_blocks_generation(repo):
    (repo / "elsewhere2.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="SUB-TB-FAIL", allowed_path_prefixes=("out_sub2",))
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build a PCIe subsystem env", protocols=["pcie"], role="ep",
                          level="SUBSYSTEM", task_boundary=boundary,
                          generation_request=_pcie_manifest(), generation_out_dir=repo / "out_sub2")
    assert r.ok is False
    assert r.raw["blocked_by"] == "task_boundary"
    assert not (repo / "out_sub2").exists()


_USB_ENTRY = {"name": "USB", "environment_manifest": "generated/usb/environment_manifest.json",
             "release_sha": "sha-usb-1", "qualification_state": "PRODUCTION_QUALIFIED",
             "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}
_PCIE_ENTRY = {"name": "PCIE", "environment_manifest": "generated/pcie/environment_manifest.json",
              "release_sha": "sha-pcie-1", "qualification_state": "REGRESSION_QUALIFIED",
              "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}


def _register_two_subsystems(h: DVHarness) -> None:
    h.state.stages["SIGNOFF"]["status"] = Status.PASS.value
    for entry in (_USB_ENTRY, _PCIE_ENTRY):
        h._persist_subsystem_registry_entry(
            "SIGNOFF", {"subsystem_environment_registration_gate": dict(entry)})


def test_system_level_with_task_boundary_pass(repo):
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    _register_two_subsystems(h)
    boundary = TaskBoundary(task_id="SYS-TB", allowed_path_prefixes=("out_soc",))
    r = h.start_lifecycle(
        "compose the USB+PCIe SoC env", protocols=["usb", "pcie"], role="system",
        level="SYSTEM_LEVEL", task_boundary=boundary,
        generation_request={"requested_subsystems": ["USB", "PCIE"], "soc_name": "tb_soc"},
        generation_out_dir=repo / "out_soc")
    assert r.ok is True, r.text
    assert r.raw["environment_mode"] == "SYSTEM_LEVEL_MODE"


def test_system_level_with_task_boundary_fail_blocks_generation(repo):
    h = DVHarness(repo)
    h.adapter = _FakeAdapter()
    _register_two_subsystems(h)
    (repo / "elsewhere3.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="SYS-TB-FAIL", allowed_path_prefixes=("out_soc2",))
    r = h.start_lifecycle(
        "compose the USB+PCIe SoC env", protocols=["usb", "pcie"], role="system",
        level="SYSTEM_LEVEL", task_boundary=boundary,
        generation_request={"requested_subsystems": ["USB", "PCIE"], "soc_name": "tb_soc2"},
        generation_out_dir=repo / "out_soc2")
    assert r.ok is False
    assert r.raw["blocked_by"] == "task_boundary"
    assert not (repo / "out_soc2").exists()


# ---------------------------------------------------------------------------
# F. Bypass classification (dispatch section 12): --advanced remains the
#    ONE authorized low-level bypass; a declared TaskBoundary is ignored
#    under it, exactly like every other governed field -- never a NEW,
#    uncontrolled bypass invented for this task.
# ---------------------------------------------------------------------------

def test_advanced_bypass_also_skips_a_declared_task_boundary(repo, monkeypatch):
    from dv_harness import engine as engine_mod

    calls = {"n": 0}
    monkeypatch.setattr(engine_mod._create_environment_module, "create_environment",
                        lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1) or {})
    (repo / "forbidden.txt").write_text("x", encoding="utf-8")
    boundary = TaskBoundary(task_id="ADV-TB", allowed_path_prefixes=("nowhere/",))
    h = DVHarness(repo)
    fake = _FakeAdapter()
    h.adapter = fake
    r = h.start_lifecycle("bypass run", task_boundary=boundary,
                          generation_request=_pcie_manifest(), advanced=True)
    assert calls["n"] == 0  # generation_request is ignored under --advanced, same as before
    assert fake.calls >= 1  # went straight to the ordinary dispatch primitive
    assert QuestionQueueStore(repo).list_questions() == []
