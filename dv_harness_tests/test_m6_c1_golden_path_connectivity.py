"""M6 GOLDEN-PATH CONNECTIVITY CLOSURE C1 (CAP-M6-C1-001) + GAP-V2-002
remediation (CAP-M6-GAPV2002-001).

Confirms, with real production code (never mock-only/unit-only paths, per
this task's own explicit instruction), that the two capability-island edges
the Integration Prime Directive adoption audit found are now genuinely
connected, for the real, derived field set (`protocol`, `role`,
`verification_level` -- CAP-M5M6-VLEVEL-001) rather than a single field:

  EDGE_A: production intake/field-controls -> ClarificationService
          (`generation_field_controls.py` projects `start_lifecycle()`'s
          own `protocols`/`role` arguments into real `FieldControl`s, only
          when a caller opts in via `generation_request`).
  EDGE_B: governed start_lifecycle path -> verification-environment-
          generation dispatch (`start_lifecycle()` calls
          `uvm_generator.create_environment.create_environment()` directly,
          never the reverse).

Required test families (C1's own dispatch section 12, plus GAP-V2-002's own
section 12), one section each below:
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
      with the governed protocol/role values substituted in)
  11. create_environment consumer direction (start_lifecycle calls it, it
      never calls back into start_lifecycle -- no lifecycle recursion)
  12. authorized low-level bypass preservation (--advanced still skips the
      new mechanism entirely, exactly like every other governed check)
  13. ordinary (non-generation) calls stay a byte-identical no-op
      (REGRESSION_CAUSED_BY_C1 = 0 for every existing caller)
  14. (GAP-V2-002) role field: same 7 families as protocol, independently
  15. (CAP-M5M6-VLEVEL-001) verification_level field: same 7 families as
      protocol/role, independently -- see test_m5m6_vlevel_001_production_
      connectivity.py for the dedicated per-level (IP/SUBSYSTEM/SYSTEM_LEVEL)
      production-path proofs this file's own PCIe fixtures cannot cover.
      Every HAPPY-PATH test below (one that expects `r.ok is True` or a
      specific protocol/role-only unresolved-question set) now also declares
      `level="subsystem"` (the real, established single-protocol-build
      precedent -- environment_mode_policy.json's own SUBSYSTEM_MODE
      examples list PCIe/USB/etc. as one-protocol builds), so the
      pre-existing protocol/role assertions stay exactly what they were
      testing before verification_level became a third required generation
      field. The two single-field-unresolved tests (`..._no_declared_
      protocol...`/`..._no_declared_role...`) deliberately leave `level`
      undeclared too and assert membership rather than an exact question
      set, so the incidental extra unresolved verification_level question
      does not change what they prove.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
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


def _wait_until_idle(dashboard_mod, root):
    for _ in range(200):
        if not dashboard_mod._is_running(root):
            return
        time.sleep(0.01)


# ---------------------------------------------------------------------------
# 1/2/3 -- field_controls propagation, auto-resolved, and unresolved paths
# (protocol AND role both declared -- the two-field happy path)
# ---------------------------------------------------------------------------

def test_declared_protocol_and_role_resolve_silently_no_question_filed(root):
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build PCIe env", protocols=["pcie"], role="ep", level="subsystem",
                          generation_request=_pcie_manifest(),
                          generation_out_dir=root / "out")
    assert r.ok is True, r.text
    assert QuestionQueueStore(root).list_questions() == []


def test_no_declared_protocol_and_no_prior_fact_files_a_real_unresolved_question(root):
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build a protocol env", role="ep", generation_request=_pcie_manifest())
    assert r.ok is False
    assert r.raw["blocked_by"] == "clarification"
    qs = QuestionQueueStore(root).list_questions()
    keys = {q["question_key"] for q in qs}
    assert f"intake:{generation_field_controls.PROTOCOL_FIELD_ID}" in keys
    assert h.adapter.calls == 0  # HumanGate blocking: ordinary dispatch never ran


def test_no_declared_role_and_no_prior_fact_files_a_real_unresolved_question(root):
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build a protocol env", protocols=["pcie"], generation_request=_pcie_manifest())
    assert r.ok is False
    assert r.raw["blocked_by"] == "clarification"
    qs = QuestionQueueStore(root).list_questions()
    keys = {q["question_key"] for q in qs}
    assert f"intake:{generation_field_controls.ROLE_FIELD_ID}" in keys
    assert h.adapter.calls == 0


def test_both_unresolved_files_two_real_questions_not_one(root):
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build a protocol env", level="subsystem",
                          generation_request=_pcie_manifest())
    assert r.ok is False
    qs = QuestionQueueStore(root).list_questions()
    keys = {q["question_key"] for q in qs}
    assert keys == {f"intake:{generation_field_controls.PROTOCOL_FIELD_ID}",
                    f"intake:{generation_field_controls.ROLE_FIELD_ID}"}


def test_all_three_unresolved_files_three_real_questions(root):
    """CAP-M5M6-VLEVEL-001: verification_level joins protocol/role as a
    third real generation FieldControl -- declaring none of the three files
    exactly three real unresolved questions, not two."""
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("build a protocol env", generation_request=_pcie_manifest())
    assert r.ok is False
    qs = QuestionQueueStore(root).list_questions()
    keys = {q["question_key"] for q in qs}
    assert keys == {f"intake:{generation_field_controls.PROTOCOL_FIELD_ID}",
                    f"intake:{generation_field_controls.ROLE_FIELD_ID}",
                    f"intake:{generation_field_controls.VERIFICATION_LEVEL_FIELD_ID}"}
    assert h.adapter.calls == 0


def test_previously_recorded_protocol_and_role_auto_resolve_a_later_generation_call(root):
    h1 = DVHarness(root)
    h1.adapter = _FakeAdapter()
    r1 = h1.start_lifecycle("declare protocol/role only", protocols=["usb"], role="device",
                            level="subsystem")
    assert r1 is not None

    h2 = DVHarness(root)
    h2.adapter = _FakeAdapter()
    r2 = h2.start_lifecycle("now generate", generation_request=_pcie_manifest(),
                            generation_out_dir=root / "out2")
    assert r2.ok is True, r2.text
    assert QuestionQueueStore(root).list_questions() == []
    assert r2.raw["environment_mode"] in ("SUBSYSTEM_MODE", "SYSTEM_LEVEL_MODE")


# ---------------------------------------------------------------------------
# 4 -- QuestionOwner propagation (both fields)
# ---------------------------------------------------------------------------

def test_protocol_and_role_question_owner_is_verification(root):
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    h.start_lifecycle("build env", generation_request=_pcie_manifest())
    qs = QuestionQueueStore(root).list_questions()
    by_key = {q["question_key"]: q for q in qs}
    for field_id in (generation_field_controls.PROTOCOL_FIELD_ID, generation_field_controls.ROLE_FIELD_ID,
                     generation_field_controls.VERIFICATION_LEVEL_FIELD_ID):
        q = by_key[f"intake:{field_id}"]
        assert q["authority_role"] == "VERIFICATION"
        assert q["domain"] == "env"


# ---------------------------------------------------------------------------
# 5/6/7 -- HumanGate blocking, Answer -> Field Resolution, EffectiveValue
# persisted as a lifecycle fact (both fields, answered independently)
# ---------------------------------------------------------------------------

def test_human_answers_unblock_generation_and_are_persisted_as_lifecycle_facts(root):
    h1 = DVHarness(root)
    h1.adapter = _FakeAdapter()
    r1 = h1.start_lifecycle("build env", generation_request=_pcie_manifest())
    assert r1.ok is False
    qs = QuestionQueueStore(root).list_questions()
    by_key = {q["question_key"]: q for q in qs}
    protocol_qid = by_key[f"intake:{generation_field_controls.PROTOCOL_FIELD_ID}"]["id"]
    role_qid = by_key[f"intake:{generation_field_controls.ROLE_FIELD_ID}"]["id"]
    level_qid = by_key[f"intake:{generation_field_controls.VERIFICATION_LEVEL_FIELD_ID}"]["id"]

    store = QuestionQueueStore(root)
    store.answer_question(protocol_qid, answer="pcie", basis="confirmed", decided_by="dv_engineer_1")
    store.answer_question(role_qid, answer="ep", basis="confirmed", decided_by="dv_engineer_1")
    store.answer_question(level_qid, answer="SUBSYSTEM", basis="confirmed", decided_by="dv_engineer_1")

    h2 = DVHarness(root)
    h2.adapter = _FakeAdapter()
    r2 = h2.start_lifecycle("build env", generation_request=_pcie_manifest(),
                            generation_out_dir=root / "out3")
    assert r2.ok is True, r2.text
    assert h2.adapter.calls == 0  # generation path, not the ordinary Stage graph

    data = LifecycleStore(root).load()
    assert data.get("protocols") == ["pcie"]
    assert data.get("role") == "ep"
    assert data.get("verification_level") == "SUBSYSTEM"
    assert data.get("level_source") == "field_resolution"


def test_only_one_field_answered_still_blocks_on_the_other(root):
    h1 = DVHarness(root)
    h1.adapter = _FakeAdapter()
    r1 = h1.start_lifecycle("build env", generation_request=_pcie_manifest())
    qs = QuestionQueueStore(root).list_questions()
    by_key = {q["question_key"]: q for q in qs}
    protocol_qid = by_key[f"intake:{generation_field_controls.PROTOCOL_FIELD_ID}"]["id"]
    QuestionQueueStore(root).answer_question(protocol_qid, answer="pcie", basis="confirmed",
                                             decided_by="dv_engineer_1")

    h2 = DVHarness(root)
    h2.adapter = _FakeAdapter()
    r2 = h2.start_lifecycle("build env", generation_request=_pcie_manifest())
    assert r2.ok is False
    assert r2.raw["blocked_by"] == "clarification"
    data = LifecycleStore(root).load()
    assert data.get("protocols") == ["pcie"]  # the resolved one persisted
    assert data.get("role") is None  # the unresolved one did not


# ---------------------------------------------------------------------------
# 8 -- CLI production path
# ---------------------------------------------------------------------------

def test_cli_start_generate_propagates_protocol_role_and_manifest_into_start_lifecycle(root, monkeypatch, tmp_path):
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
        "--protocols", "pcie", "--dut-role", "ep", "--level", "SUBSYSTEM", "--generate",
        "--generate-out", str(out_dir), "--generate-manifest", str(manifest_path),
    ])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 0
    kw = calls["kwargs"]
    assert kw["protocols"] == ("pcie",)
    assert kw["role"] == "ep"
    assert kw["level"] == "SUBSYSTEM"
    assert kw["generation_request"]["clocks"] == [{"name": "refclk"}]
    assert kw["generation_out_dir"] == out_dir


def test_cli_start_generate_prints_a_structured_json_envelope_matching_the_legacy_script(root, monkeypatch, tmp_path, capsys):
    """PRODUCTION_DATAFLOW_VALIDATED (GAP-V2-002): a migrated SKILL.md
    caller that used to parse `tools/generate_protocol_uvm_environment.py`'s
    own JSON stdout (status/environment_mode/generated_files/out/...) must
    keep getting an equivalent structured JSON envelope from `dv-harness
    start --generate`, not a human-readable sentence -- otherwise the
    migration would be a real capability loss for any caller that parses
    the output."""
    from dv_harness import cli as cli_mod

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_pcie_manifest()), encoding="utf-8")
    out_dir = tmp_path / "cli_out2"

    orig_init = DVHarness.__init__

    def _patched_init(self, r):
        orig_init(self, r)
        self.adapter = _FakeAdapter()

    monkeypatch.setattr(DVHarness, "__init__", _patched_init)
    monkeypatch.setattr(sys, "argv", [
        "dv-harness", "--project-root", str(root), "start", "--goal", "build PCIe env",
        "--protocols", "pcie", "--dut-role", "ep", "--level", "SUBSYSTEM", "--generate",
        "--generate-out", str(out_dir), "--generate-manifest", str(manifest_path),
    ])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == "OK"
    assert payload["environment_mode"] in ("SUBSYSTEM_MODE", "SYSTEM_LEVEL_MODE")
    assert "generated_files" in payload
    assert payload["out"] == str(out_dir)


def test_cli_start_generate_failure_prints_a_structured_json_envelope_with_status_and_detail(root, monkeypatch, tmp_path, capsys):
    from dv_harness import cli as cli_mod

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_pcie_manifest()), encoding="utf-8")

    orig_init = DVHarness.__init__

    def _patched_init(self, r):
        orig_init(self, r)
        self.adapter = _FakeAdapter()

    monkeypatch.setattr(DVHarness, "__init__", _patched_init)
    # No --generate-out for a SUBSYSTEM_MODE request -> MissingOutputDirectoryError.
    monkeypatch.setattr(sys, "argv", [
        "dv-harness", "--project-root", str(root), "start", "--goal", "build PCIe env",
        "--protocols", "pcie", "--dut-role", "ep", "--level", "SUBSYSTEM", "--generate",
        "--generate-manifest", str(manifest_path),
    ])
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SUBSYSTEM_MODE_REQUIRES_OUT_DIR"
    assert "detail" in payload


# ---------------------------------------------------------------------------
# 9 -- Dashboard production path
# ---------------------------------------------------------------------------

def test_dashboard_start_background_run_propagates_generation_fields(root):
    from dv_harness import dashboard as dashboard_mod

    assert not dashboard_mod._is_running(root)
    dashboard_mod._start_background_run(
        root, "build PCIe env", loop=False, adapter_factory=lambda: _FakeAdapter(),
        protocols=("pcie",), role="ep", level="subsystem", generation_request=_pcie_manifest(),
        generation_out_dir=root / "dash_out")
    _wait_until_idle(dashboard_mod, root)
    assert QuestionQueueStore(root).list_questions() == []
    data = LifecycleStore(root).load()
    assert data.get("protocols") == ["pcie"]
    assert data.get("role") == "ep"
    assert data.get("verification_level") == "subsystem"


def test_dashboard_start_background_run_with_no_generation_fields_is_unchanged(root):
    """Backward compatibility: the pre-C1 call shape (no protocols/role/
    generation_request/generation_out_dir) must behave exactly as before --
    no protocol/role question, ordinary dispatch reached."""
    from dv_harness import dashboard as dashboard_mod

    fake = _FakeAdapter()
    dashboard_mod._start_background_run(root, "ordinary run", loop=False,
                                        adapter_factory=lambda: fake)
    _wait_until_idle(dashboard_mod, root)
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
    r = h.start_lifecycle("build PCIe env", protocols=["pcie"], role="ep", level="subsystem",
                          generation_request=_pcie_manifest(),
                          generation_out_dir=root / "out")
    assert r.ok is True, r.text
    assert calls["n"] == 1
    assert calls["request"]["protocol"] == "pcie"
    assert calls["request"]["role"] == "ep"
    assert calls["request"]["verification_level"] == "subsystem"
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
    r = h.start_lifecycle("build PCIe env", protocols=["PCIe"], role="ep", level="subsystem",
                          generation_request=_pcie_manifest(**{TOPOLOGY_KEY: bad_topology}),
                          generation_out_dir=root / "out")
    assert r.ok is False
    assert r.raw["blocked_by"] == "generation"
    assert r.raw["error"] == "ProtocolModelLayerError"
    assert r.raw["status"] == "PROTOCOL_MODEL_TOPOLOGY_REJECTED"
    assert r.raw["detail"]["model_reason"] == "INVALID_LANE_WIDTH"
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
    r = h.start_lifecycle("build PCIe env", protocols=["pcie"], role="ep", level="subsystem",
                          generation_request=_pcie_manifest())
    assert r.ok is False
    assert r.raw["blocked_by"] == "generation"
    assert r.raw["error"] == "MissingOutputDirectoryError"
    assert r.raw["status"] == "SUBSYSTEM_MODE_REQUIRES_OUT_DIR"


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
    about protocol/role just because start_lifecycle() now knows how to."""
    h = DVHarness(root)
    h.adapter = _FakeAdapter()
    r = h.start_lifecycle("run a regression, not a generation")
    assert QuestionQueueStore(root).list_questions() == []
    assert h.adapter.calls >= 1
