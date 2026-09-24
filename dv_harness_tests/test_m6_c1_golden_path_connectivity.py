"""M6 GOLDEN-PATH CONNECTIVITY CLOSURE C1 (CAP-M6-C1-001).

Confirms, with real production code (never mock-only/unit-only paths, per
this task's own explicit instruction), that the two capability-island edges
the Integration Prime Directive adoption audit found are now genuinely
connected:

  EDGE_A: production intake/field-controls -> ClarificationService
          (`generation_field_controls.py` projects `start_lifecycle()`'s
          own pre-existing `protocols` argument into a real `FieldControl`,
          only when a caller opts in via `generation_request`).
  EDGE_B: governed start_lifecycle path -> verification-environment-
          generation dispatch (`start_lifecycle()` calls
          `uvm_generator.create_environment.create_environment()` directly,
          never the reverse).

Required test families (dispatch section 12), one section each below:
  1. real field_controls propagation (declared value resolves silently)
  2. auto-resolved no-question path (a prior run's lifecycle fact resolves it)
  3. real unresolved clarification path (a real question is filed)
  4. QuestionOwner propagation (authority_role persisted correctly)
  5. HumanGate blocking (ok=False, blocked_by="clarification", generation
     does not run)
  6. answer -> Field Resolution (a real answer re-enters resolve_field())
  7. EffectiveValue after answer (persisted back as a lifecycle fact)
  8. CLI production path (cli.py's `start --generate` propagates real data)
  9. Dashboard production path (the HTTP /api/start handler propagates it)
  10. governed generation dispatch (create_environment() actually runs,
      with the governed protocol value substituted in)
  11. create_environment consumer direction (start_lifecycle calls it, it
      never calls back into start_lifecycle -- no lifecycle recursion)
  12. authorized low-level bypass preservation (--advanced still skips the
      new mechanism entirely, exactly like every other governed check)
  13. ordinary (non-generation) calls stay a byte-identical no-op
      (REGRESSION_CAUSED_BY_C1 = 0 for every existing caller)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import generation_field_controls
from dv_harness.adapters.base import AgentResult
from dv_harness.engine import DVHarness
from dv_harness.lifecycle import LifecycleStore
from dv_harness.question_queue import QuestionQueueStore
from dv_harness.uvm_generator.protocol_model_layer import STATE_SIGNAL_KEY, TOPOLOGY_KEY


@pytest.fixture()
def root():
    d = Path(tempfile.mkdtemp(prefix="m6_c1_"))
    try:
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
# 1/2/3 -- field_controls propagation, auto-resolved, and unresolved paths
# ---------------------------------------------------------------------------

def test_declared_protocol_resolves_silently_no_question_filed(root):
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build PCIe env", protocols=["pcie"],
                          generation_request=_pcie_manifest(),
                          generation_out_dir=root / "out")
    assert r.ok is True, r.text
    assert QuestionQueueStore(root).list_questions() == []


def test_no_declared_protocol_and_no_prior_fact_files_a_real_unresolved_question(root):
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build a protocol env", generation_request=_pcie_manifest())
    assert r.ok is False
    assert r.raw["blocked_by"] == "clarification"
    qs = QuestionQueueStore(root).list_questions()
    assert len(qs) == 1
    assert qs[0]["question_key"] == f"intake:{generation_field_controls.PROTOCOL_FIELD_ID}"
    assert h.adapter.calls == 0  # HumanGate blocking: ordinary dispatch never ran


def test_previously_recorded_protocol_auto_resolves_a_later_generation_call(root):
    h1 = DVHarness(root)
    h1.adapter = _FakeAdapter()
    r1 = h1.start_lifecycle("declare protocol only", protocols=["usb"])
    assert r1 is not None

    h2 = DVHarness(root)
    h2.adapter = _FakeAdapter()
    r2 = h2.start_lifecycle("now generate", generation_request=_pcie_manifest(),
                            generation_out_dir=root / "out2")
    assert r2.ok is True, r2.text
    assert QuestionQueueStore(root).list_questions() == []
    assert r2.raw["environment_mode"] in ("SUBSYSTEM_MODE", "SYSTEM_LEVEL_MODE")


# ---------------------------------------------------------------------------
# 4 -- QuestionOwner propagation
# ---------------------------------------------------------------------------

def test_protocol_question_owner_is_verification(root):
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    h.start_lifecycle("build env", generation_request=_pcie_manifest())
    q = QuestionQueueStore(root).list_questions()[0]
    assert q["authority_role"] == "VERIFICATION"
    assert q["domain"] == "env"


# ---------------------------------------------------------------------------
# 5/6/7 -- HumanGate blocking, Answer -> Field Resolution, EffectiveValue
# persisted as a lifecycle fact
# ---------------------------------------------------------------------------

def test_human_answer_unblocks_generation_and_is_persisted_as_a_lifecycle_fact(root):
    h1 = DVHarness(root)
    h1.adapter = _FakeAdapter()
    r1 = h1.start_lifecycle("build env", generation_request=_pcie_manifest())
    assert r1.ok is False
    qid = r1.raw["question_ids"][0]

    QuestionQueueStore(root).answer_question(qid, answer="pcie", basis="confirmed",
                                             decided_by="dv_engineer_1")

    h2 = DVHarness(root)
    h2.adapter = _FakeAdapter()
    r2 = h2.start_lifecycle("build env", generation_request=_pcie_manifest(),
                            generation_out_dir=root / "out3")
    assert r2.ok is True, r2.text
    assert h2.adapter.calls == 0  # generation path, not the ordinary Stage graph

    data = LifecycleStore(root).load()
    assert data.get("protocols") == ["pcie"]


# ---------------------------------------------------------------------------
# 8 -- CLI production path
# ---------------------------------------------------------------------------

def test_cli_start_generate_propagates_protocol_and_manifest_into_start_lifecycle(root, monkeypatch, tmp_path):
    from dv_harness import cli as cli_mod

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_pcie_manifest()), encoding="utf-8")
    out_dir = tmp_path / "cli_out"

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
        "dv-harness", "--project-root", str(root), "start", "--goal", "build PCIe env",
        "--protocols", "pcie", "--generate", "--generate-out", str(out_dir),
        "--generate-manifest", str(manifest_path),
    ])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 0
    kw = calls["kwargs"]
    assert kw["protocols"] == ("pcie",)
    assert kw["generation_request"]["clocks"] == [{"name": "refclk"}]
    assert kw["generation_out_dir"] == out_dir


# ---------------------------------------------------------------------------
# 9 -- Dashboard production path
# ---------------------------------------------------------------------------

def test_dashboard_start_background_run_propagates_generation_fields(root):
    from dv_harness import dashboard as dashboard_mod

    r = dashboard_mod._run_key(root)
    assert not dashboard_mod._is_running(root)
    dashboard_mod._start_background_run(
        root, "build PCIe env", loop=False, adapter_factory=lambda: _FakeAdapter(),
        protocols=("pcie",), generation_request=_pcie_manifest(),
        generation_out_dir=root / "dash_out")
    import time
    for _ in range(200):
        if not dashboard_mod._is_running(root):
            break
        time.sleep(0.01)
    assert not dashboard_mod._is_running(root)
    assert QuestionQueueStore(root).list_questions() == []
    data = LifecycleStore(root).load()
    assert data.get("protocols") == ["pcie"]


def test_dashboard_start_background_run_with_no_generation_fields_is_unchanged(root):
    """Backward compatibility: the pre-C1 call shape (no protocols/
    generation_request/generation_out_dir) must behave exactly as before --
    no protocol question, ordinary dispatch reached."""
    from dv_harness import dashboard as dashboard_mod

    fake = _FakeAdapter()
    dashboard_mod._start_background_run(root, "ordinary run", loop=False,
                                        adapter_factory=lambda: fake)
    import time
    for _ in range(200):
        if not dashboard_mod._is_running(root):
            break
        time.sleep(0.01)
    assert QuestionQueueStore(root).list_questions() == []


# ---------------------------------------------------------------------------
# 10/11 -- governed generation dispatch, and no lifecycle recursion
# ---------------------------------------------------------------------------

def test_generation_dispatch_calls_create_environment_directly_never_recurses(root, monkeypatch):
    from dv_harness import engine as engine_mod

    calls = {"n": 0}
    real_create = engine_mod._create_environment_module.create_environment

    def _spy(root_arg, request, out_dir=None):
        calls["n"] += 1
        calls["request"] = dict(request)
        calls["out_dir"] = out_dir
        return real_create(root_arg, request, out_dir=out_dir)

    monkeypatch.setattr(engine_mod._create_environment_module, "create_environment", _spy)

    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build PCIe env", protocols=["pcie"],
                          generation_request=_pcie_manifest(),
                          generation_out_dir=root / "out")
    assert r.ok is True, r.text
    assert calls["n"] == 1
    assert calls["request"]["protocol"] == "pcie"
    # No lifecycle recursion: the ordinary Stage-graph adapter (what
    # loop()/run_stage() would call) was never invoked by the generation path.
    assert h.adapter.calls == 0


# ---------------------------------------------------------------------------
# V2 P5 FIND -> FIX -> VERIFY (CAP-M6-C1-002): a real current-scope defect
# found during the V2 re-verification pass -- start_lifecycle()'s generation
# branch caught only 6 of create_environment()'s own documented exceptions.
# ProtocolModelLayerError (and soc_environment_composer.py's three own
# exceptions) were NOT in the except tuple, so a real, documented
# create_environment() failure mode would have propagated UNCAUGHT out of
# start_lifecycle() instead of returning an ordinary AgentResult(ok=False),
# breaking FAILURE_PATH_CORRECTNESS -- found by direct source inspection
# (grep for every real "class ...Error" in create_environment.py's own
# imports), not assumed absent.
# ---------------------------------------------------------------------------

def test_a_rejected_protocol_model_topology_returns_a_real_agent_result_not_an_uncaught_exception(root):
    """Before the fix: ProtocolModelLayerError propagated uncaught out of
    start_lifecycle(), crashing the caller (CLI/dashboard) instead of
    returning the same kind of AgentResult(ok=False) every other
    create_environment() failure mode already returns."""
    bad_topology = {"name": "pcie_ep", "lane_width": 3, "gen_speed": "Gen3",
                    "role": "EP", STATE_SIGNAL_KEY: "u_pcie_ctrl.ltssm_state_q"}
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build PCIe env", protocols=["PCIe"],
                          generation_request=_pcie_manifest(**{TOPOLOGY_KEY: bad_topology}),
                          generation_out_dir=root / "out")
    assert r.ok is False
    assert r.raw["blocked_by"] == "generation"
    assert r.raw["error"] == "ProtocolModelLayerError"
    # The model runs before the skeleton -- a refusal must leave nothing
    # written, exactly as create_environment()'s own direct-call contract
    # already guarantees (test_protocol_model_layer_wiring.py).
    assert not (root / "out" / "tb").exists()


def test_generation_request_none_takes_the_ordinary_dispatch_path(root, monkeypatch):
    from dv_harness import engine as engine_mod

    calls = {"n": 0}
    monkeypatch.setattr(engine_mod._create_environment_module, "create_environment",
                        lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1) or {})

    h = DVHarness(root)
    fake = _FakeAdapter()
    h.adapter = fake
    h.start_lifecycle("ordinary run, no generation")
    assert calls["n"] == 0
    assert fake.calls >= 1  # ordinary Stage-graph dispatch actually ran


def test_generation_failure_is_a_real_agent_result_not_an_uncaught_exception(root):
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    # No out_dir supplied for a SUBSYSTEM_MODE request -> create_environment()'s
    # own documented MissingOutputDirectoryError.
    r = h.start_lifecycle("build PCIe env", protocols=["pcie"],
                          generation_request=_pcie_manifest())
    assert r.ok is False
    assert r.raw["blocked_by"] == "generation"
    assert r.raw["error"] == "MissingOutputDirectoryError"


# ---------------------------------------------------------------------------
# 12 -- authorized low-level bypass preservation
# ---------------------------------------------------------------------------

def test_advanced_bypass_skips_the_new_generation_mechanism_entirely(root, monkeypatch):
    from dv_harness import engine as engine_mod

    calls = {"n": 0}
    monkeypatch.setattr(engine_mod._create_environment_module, "create_environment",
                        lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1) or {})
    h = DVHarness(root)
    fake = _FakeAdapter()
    h.adapter = fake
    h.start_lifecycle("bypass run", generation_request=_pcie_manifest(), advanced=True)
    assert calls["n"] == 0  # generation_request is ignored under --advanced
    assert fake.calls >= 1  # went straight to the ordinary dispatch primitive
    assert QuestionQueueStore(root).list_questions() == []


# ---------------------------------------------------------------------------
# 13 -- ordinary (non-generation) calls stay a byte-identical no-op
# ---------------------------------------------------------------------------

def test_ordinary_call_with_no_field_controls_or_generation_request_asks_nothing(root):
    """The exact pre-C1 shape every existing caller uses -- must not ask
    about protocol just because start_lifecycle() now knows how to."""
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("run a regression, not a generation")
    assert QuestionQueueStore(root).list_questions() == []
    assert h.adapter.calls >= 1
