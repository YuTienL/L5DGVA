"""Tests for dv_harness/subsystem_maturity_gate.py -- the composite 9.0 / 9.5
/ 10.0 subsystem maturity qualification gates.

Discipline:
  1. The condition/level TABLE is self-consistent: no duplicate condition id,
     every level's requirement set is a real subset of the level above it,
     and every declared `fact_source` resolves through the real import system
     -- with a negative control proving a renamed fact_source is refused
     rather than silently reported MET.
  2. Every condition is driven against REAL evidence, produced by the REAL
     writer that module already has:
       - golden_flow_spec_to_uvm_to_pass: a real `.dv-harness/state.json`
         (via `storage.StateStore`) plus a real uploaded document.
       - regression_evidence_exists: a real DuckDB `EvidenceStore` carrying a
         real `lsf_client.JobState` row and a real `vip_distill.distill_sim_log()`
         normalized-evidence envelope.
       - zero_vip_api_hallucination: the REAL `vip_api_card.validate_vip_api_usage()`
         over the REAL synthetic VIP index this repo already ships
         (examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv) and the
         REAL clean generated-sequence fixture
         (dv_harness_tests/fixtures/vip_api/demo_env_seq.sv), mutated one
         fabrication at a time for the negative control.
       - bind_validation_clean: the REAL, already-shipped
         examples/generated_usb_real_evidence_v1/manifest_inputs/usb_bind_topology.json
         for the positive control, and real T4/unconfirmed-T3 entries run
         through the real `connectivity.assert_bind_entry_tier_allows_emission()`
         for the negative ones.
       - system_smoke_proof_ready: a real `system_build_proof.SmokeProofReport`
         dataclass instance's own real `.to_dict()` (system_build_proof.py's
         own ladder mechanics are proven end-to-end by
         test_system_build_proof.py; this suite proves THIS gate's consumption
         of that real report shape, not the ladder itself).
       - false_pass_count_zero: always NOT_MEASURABLE, and asserted never to
         block QUALIFIED at 10.0 while still appearing under disclosed_caveats.
  3. The composed VERDICT rule (QUALIFIED / NOT_QUALIFIED / INCOMPLETE_EVIDENCE)
     is exercised end to end at all three levels over one evolving real
     project, plus its own negative controls: a real gate-shaped FAIL makes
     the level NOT_QUALIFIED (never merely INCOMPLETE_EVIDENCE), and a level
     with no evidence supplied at all is INCOMPLETE_EVIDENCE (never
     NOT_QUALIFIED, since nothing was proven wrong).
  4. Reading is never a mutating act: a full evaluate() run over a real
     initialized project changes no file on disk.
  5. Both real CLI entry points (`conditions`, `evaluate`) are driven as real
     subprocesses.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import subsystem_maturity_gate as smg  # noqa: E402
from dv_harness import connectivity as conn  # noqa: E402
from dv_harness import vip_api_card as vac  # noqa: E402
from dv_harness import vip_symbol_index as vsi  # noqa: E402
from dv_harness import system_build_proof as sbp  # noqa: E402
from dv_harness.evidence_db import EvidenceStore, default_db_path  # noqa: E402
from dv_harness.lsf_client import JobState  # noqa: E402
from dv_harness.vip_distill import distill_sim_log  # noqa: E402
from dv_harness.models import HarnessState, Stage, Status  # noqa: E402
from dv_harness.storage import StateStore  # noqa: E402

VIP_SRC_ROOT = ROOT / "examples" / "asset_processing" / "inputs" / "vip_src"
VIP_SRC_BASE = ROOT / "examples" / "asset_processing" / "inputs"
CLEAN_VIP_FIXTURE = ROOT / "dv_harness_tests" / "fixtures" / "vip_api" / "demo_env_seq.sv"
USB_BIND_TOPOLOGY = (ROOT / "examples" / "generated_usb_real_evidence_v1" /
                    "manifest_inputs" / "usb_bind_topology.json")

PASSING_SIM_LOG = """\
UVM_INFO @ 0 ns: reporter [RNTST] Running test usb3_lfps_basic...
FINAL CHECK @ 25000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0
VERDICT: PASSED
"""


# ---------------------------------------------------------------------------
# real-artifact helpers
# ---------------------------------------------------------------------------

def write_state(root: Path, statuses: dict) -> None:
    store = StateStore(root)
    state = HarnessState(project=root.name, current_stage=Stage.INTAKE.value)
    state.ensure_stages()
    for stage, status in statuses.items():
        state.stages[stage]["status"] = status
    store.save(state)


def write_uploaded_spec(root: Path) -> None:
    uploads = root / ".dv-harness" / "uploads" / "spec"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "usb32_spec.pdf").write_bytes(b"%PDF-1.4 real bytes")


def make_spec_to_uvm_pass_project(root: Path) -> None:
    """A real project on disk whose golden_flow_readiness `spec_in` /
    `requirement_extraction` / `vip_uvm_generation` / `single_test_proof`
    rows are all READY."""
    root.mkdir(parents=True, exist_ok=True)
    write_state(root, {
        Stage.INTAKE.value: Status.PASS.value,
        Stage.REQUIREMENTS_TRACEABILITY.value: Status.PASS.value,
        Stage.IMPLEMENT.value: Status.PASS.value,
        Stage.BUILD.value: Status.PASS.value,
        Stage.VERIFY.value: Status.PASS.value,
    })
    write_uploaded_spec(root)


def write_regression_evidence(root: Path, *, job_id: int = 424242) -> None:
    """A real evidence.duckdb carrying a real JobState row and a real
    vip_distill normalized-evidence envelope."""
    log_path = root / "run" / str(job_id) / "sim.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(PASSING_SIM_LOG, encoding="utf-8")
    envelope = distill_sim_log(log_path=log_path, job_id=job_id, pattern="usb3_lfps_basic",
                              protocol="USB3", run_dir=str(log_path.parent))
    db_path = default_db_path(root)
    with EvidenceStore(db_path) as store:
        store.insert_normalized_evidence(envelope)
        store.insert_job_state(JobState(
            job_id=job_id, regression_id="REG-SMG-1", pattern="usb3_lfps_basic",
            run_dir=str(log_path.parent), sim_log=str(log_path), seed="7",
            lsf_status="DONE", sim_status="PASS", uvm_error_count=0, uvm_fatal_count=0,
        ))


def fingerprint(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture()
def demo_index():
    return vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)


@pytest.fixture()
def clean_vip_source() -> str:
    return CLEAN_VIP_FIXTURE.read_text(encoding="utf-8")


def write_vip_env(tmp_path: Path, text: str, name: str = "generated_seq.sv") -> Path:
    d = tmp_path / "env"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return d


# ===========================================================================
# 1. The condition/level table is self-consistent
# ===========================================================================

def test_no_duplicate_condition_ids():
    smg._assert_conditions_and_requirements_consistent()
    ids = [c.condition_id for c in smg.CONDITIONS]
    assert len(set(ids)) == len(ids)


def test_levels_are_a_strictly_monotonic_ladder():
    smg.assert_levels_are_monotonic()
    a = set(smg.LEVEL_REQUIREMENTS[smg.LEVEL_9_0])
    b = set(smg.LEVEL_REQUIREMENTS[smg.LEVEL_9_5])
    c = set(smg.LEVEL_REQUIREMENTS[smg.LEVEL_10_0])
    assert a <= b <= c
    assert a and (b - a) and (c - b), "each level must add at least one real condition"


def test_a_non_monotonic_ladder_is_refused(monkeypatch):
    """Negative control: a level that DROPS a lower level's condition must be
    refused, not silently accepted as a looser ladder."""
    broken = dict(smg.LEVEL_REQUIREMENTS)
    broken[smg.LEVEL_9_5] = (smg.COND_ZERO_VIP_API_HALLUCINATION,)  # drops 9.0's conditions
    monkeypatch.setattr(smg, "LEVEL_REQUIREMENTS", broken)
    with pytest.raises(smg.SubsystemMaturityGateError) as e:
        smg.assert_levels_are_monotonic()
    assert e.value.reason == "LEVEL_REQUIREMENTS_NOT_MONOTONIC"


def test_every_declared_fact_source_still_resolves():
    resolved = smg.assert_fact_sources_resolvable()
    assert "dv_harness.golden_flow_readiness.derive_golden_flow_readiness" in resolved
    assert "dv_harness.evidence_db.EvidenceStore" in resolved
    assert "dv_harness.connectivity.assert_bind_entry_tier_allows_emission" in resolved
    assert "dv_harness.system_build_proof.SYSTEM_READY" in resolved


def test_a_renamed_fact_source_is_refused(monkeypatch):
    bad = smg.ConditionSpec(
        "bogus", "x", ("dv_harness.golden_flow_readiness._no_such_reader",),
        lambda root, inputs: smg.ConditionResult("bogus", smg.MET, "x"))
    monkeypatch.setattr(smg, "CONDITIONS", (bad,))
    with pytest.raises(smg.SubsystemMaturityGateError) as e:
        smg.assert_fact_sources_resolvable()
    assert e.value.reason == "FACT_SOURCE_ATTRIBUTE_MISSING"


def test_condition_vocabulary_never_collides_with_models_status():
    smg.assert_no_verification_verdict_vocabulary()


def test_a_vocabulary_collision_is_refused(monkeypatch):
    """Negative control: if a condition status vocabulary ever picked a token
    models.Status already owns, the guard must catch it rather than silently
    letting two unrelated meanings share one word."""
    monkeypatch.setattr(smg, "CONDITION_STATUSES", ("PASS", "UNMET", "NOT_AVAILABLE",
                                                    "NOT_MEASURABLE"))
    with pytest.raises(smg.SubsystemMaturityGateError) as e:
        smg.assert_no_verification_verdict_vocabulary()
    assert e.value.reason == "VERDICT_VOCABULARY_COLLIDES_WITH_MODELS_STATUS"
    assert "PASS" in e.value.detail["clash"]


def test_unknown_level_is_refused(tmp_path):
    with pytest.raises(smg.SubsystemMaturityGateError) as e:
        smg.derive_maturity_gate("11.0", tmp_path)
    assert e.value.reason == "UNKNOWN_MATURITY_LEVEL"


# ===========================================================================
# 2. Each condition, driven against real evidence
# ===========================================================================

def test_golden_flow_condition_met_on_a_real_connected_project(tmp_path):
    project = tmp_path / "proj"
    make_spec_to_uvm_pass_project(project)
    result = smg._evaluate_golden_flow_spec_to_pass(project, smg.GateInputs())
    assert result.status == smg.MET
    assert all(s == "READY" for s in result.evidence["row_statuses"].values())


def test_golden_flow_condition_unavailable_on_an_uninitialized_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    result = smg._evaluate_golden_flow_spec_to_pass(project, smg.GateInputs())
    assert result.status == smg.NOT_AVAILABLE


def test_golden_flow_condition_unmet_on_a_real_blocked_stage(tmp_path):
    project = tmp_path / "proj"
    make_spec_to_uvm_pass_project(project)
    # a real FAIL on VERIFY blocks single_test_proof
    write_state(project, {
        Stage.INTAKE.value: Status.PASS.value,
        Stage.REQUIREMENTS_TRACEABILITY.value: Status.PASS.value,
        Stage.IMPLEMENT.value: Status.PASS.value,
        Stage.BUILD.value: Status.PASS.value,
        Stage.VERIFY.value: Status.FAIL.value,
    })
    result = smg._evaluate_golden_flow_spec_to_pass(project, smg.GateInputs())
    assert result.status == smg.UNMET
    assert "single_test_proof" in result.evidence["row_statuses"]


def test_regression_evidence_condition_not_available_with_no_db(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    result = smg._evaluate_regression_evidence_exists(project, smg.GateInputs())
    assert result.status == smg.NOT_AVAILABLE


def test_regression_evidence_condition_met_with_real_job_and_evidence_rows(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    write_regression_evidence(project)
    result = smg._evaluate_regression_evidence_exists(project, smg.GateInputs())
    assert result.status == smg.MET
    assert result.evidence["job_rows"] >= 1
    assert result.evidence["normalized_evidence_rows"] >= 1


def test_regression_evidence_condition_not_available_when_db_holds_zero_rows(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    db_path = default_db_path(project)
    with EvidenceStore(db_path):
        pass  # schema created, no rows inserted
    result = smg._evaluate_regression_evidence_exists(project, smg.GateInputs())
    assert result.status == smg.NOT_AVAILABLE
    assert "zero" in result.reason


def test_vip_api_condition_met_on_the_real_clean_fixture(tmp_path, demo_index, clean_vip_source):
    d = write_vip_env(tmp_path, clean_vip_source)
    # vip_api_card.load_index() reads a real file path, so write the index
    # (the real vsi.build_symbol_index() document) to disk first.
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(demo_index), encoding="utf-8")
    result = smg._evaluate_zero_vip_api_hallucination(
        tmp_path, smg.GateInputs(vip_sources=[d], vip_index_path=index_path))
    assert result.status == smg.MET
    assert result.evidence["counts"].get(vac.BLOCKED, 0) == 0


def test_vip_api_condition_unmet_on_a_real_fabricated_method_call(tmp_path, demo_index,
                                                                 clean_vip_source):
    """The headline negative control: a call to a method that does not exist
    on an otherwise real, indexed VIP class must UNMET this condition."""
    mutated = clean_vip_source.replace("cfg.apply_preset(2);", "cfg.apply_prezet(2);")
    assert mutated != clean_vip_source
    d = write_vip_env(tmp_path, mutated)
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(demo_index), encoding="utf-8")
    result = smg._evaluate_zero_vip_api_hallucination(
        tmp_path, smg.GateInputs(vip_sources=[d], vip_index_path=index_path))
    assert result.status == smg.UNMET
    assert result.evidence["counts"][vac.BLOCKED] >= 1


def test_vip_api_condition_reads_a_real_already_written_artifact(tmp_path, demo_index,
                                                                 clean_vip_source):
    """The reuse path: an already-written vip_api_cards.json (the artifact
    create_environment() writes) is read directly, no re-validation."""
    d = write_vip_env(tmp_path, clean_vip_source)
    report = vac.validate_vip_api_usage([d], demo_index, relative_to=d)
    artifact = tmp_path / "vip_api_cards.json"
    artifact.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    result = smg._evaluate_zero_vip_api_hallucination(
        tmp_path, smg.GateInputs(vip_api_cards_path=artifact))
    assert result.status == smg.MET


def test_vip_api_condition_not_available_with_no_input(tmp_path):
    result = smg._evaluate_zero_vip_api_hallucination(tmp_path, smg.GateInputs())
    assert result.status == smg.NOT_AVAILABLE


def test_bind_condition_met_on_the_real_shipped_usb_bind_topology():
    assert USB_BIND_TOPOLOGY.exists()
    result = smg._evaluate_bind_validation_clean(
        ROOT, smg.GateInputs(bind_topology_path=USB_BIND_TOPOLOGY))
    assert result.status == smg.MET
    assert result.evidence["entry_count"] >= 1
    assert result.evidence["violations"] == []


def test_bind_condition_unmet_on_a_real_t4_entry(tmp_path):
    entries = [{"target_instance": "chip.core.mystery_block", "tier": "T4_UNDECIDABLE"}]
    result = smg._evaluate_bind_validation_clean(tmp_path, smg.GateInputs(bind_entries=entries))
    assert result.status == smg.UNMET
    assert result.evidence["violations"][0]["reason"] == "T4_BIND_MUST_GO_TO_QUESTION_QUEUE"


def test_bind_condition_unmet_on_an_unconfirmed_t3_entry(tmp_path):
    entries = [{"target_instance": "chip.core.u_usb3_top", "tier": "T3_NAMING_HEURISTIC"}]
    result = smg._evaluate_bind_validation_clean(tmp_path, smg.GateInputs(bind_entries=entries))
    assert result.status == smg.UNMET
    assert result.evidence["violations"][0]["reason"] == "T3_BIND_REQUIRES_HUMAN_CONFIRMATION"


def test_bind_condition_met_on_a_real_human_confirmed_t3_entry(tmp_path):
    entries = [{"target_instance": "chip.core.u_usb3_top", "tier": "T3_NAMING_HEURISTIC",
               "human_confirmation": {"source": "human_answer", "confirmed_by": "j.reviewer",
                                      "basis": "confirmed against the real hierarchy dump"}}]
    result = smg._evaluate_bind_validation_clean(tmp_path, smg.GateInputs(bind_entries=entries))
    assert result.status == smg.MET
    assert result.evidence["violations"] == []


def test_bind_condition_not_available_with_no_input(tmp_path):
    result = smg._evaluate_bind_validation_clean(tmp_path, smg.GateInputs())
    assert result.status == smg.NOT_AVAILABLE


def test_bind_condition_not_available_with_empty_entry_list(tmp_path):
    result = smg._evaluate_bind_validation_clean(tmp_path, smg.GateInputs(bind_entries=[]))
    assert result.status == smg.NOT_AVAILABLE


def test_smoke_proof_condition_met_on_a_real_system_ready_report(tmp_path):
    real_report = sbp.SmokeProofReport(verdict=sbp.SYSTEM_READY,
                                       evidence="every rung PASSED against real evidence")
    result = smg._evaluate_system_smoke_proof_ready(
        tmp_path, smg.GateInputs(smoke_proof_report=real_report.to_dict()))
    assert result.status == smg.MET


def test_smoke_proof_condition_unmet_on_a_real_smoke_fail_report(tmp_path):
    real_report = sbp.SmokeProofReport(verdict=sbp.SMOKE_FAIL,
                                       evidence="smoke proof FAILED at BUILD: duplicate package")
    result = smg._evaluate_system_smoke_proof_ready(
        tmp_path, smg.GateInputs(smoke_proof_report=real_report.to_dict()))
    assert result.status == smg.UNMET


def test_smoke_proof_condition_not_available_with_no_report(tmp_path):
    result = smg._evaluate_system_smoke_proof_ready(tmp_path, smg.GateInputs())
    assert result.status == smg.NOT_AVAILABLE


def test_smoke_proof_condition_refuses_an_unrecognized_verdict(tmp_path):
    result = smg._evaluate_system_smoke_proof_ready(
        tmp_path, smg.GateInputs(smoke_proof_report={"verdict": "TOTALLY_FINE", "evidence": "x"}))
    assert result.status == smg.NOT_AVAILABLE
    assert "unrecognized verdict" in result.reason


def test_false_pass_condition_is_always_not_measurable(tmp_path):
    result = smg._evaluate_false_pass_count_zero(tmp_path, smg.GateInputs())
    assert result.status == smg.NOT_MEASURABLE
    assert "golden_scenario" in result.reason
    assert "requirement_contract" in result.reason


# ===========================================================================
# 3. The composed verdict, at all three levels, over one real project
# ===========================================================================

def test_9_0_is_qualified_on_real_connected_evidence(tmp_path):
    project = tmp_path / "proj"
    make_spec_to_uvm_pass_project(project)
    write_regression_evidence(project)
    report = smg.derive_maturity_gate(smg.LEVEL_9_0, project)
    assert report["verdict"] == smg.QUALIFIED
    assert report["unmet_conditions"] == []
    assert report["unavailable_conditions"] == []


def test_9_0_is_incomplete_evidence_with_nothing_supplied(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    report = smg.derive_maturity_gate(smg.LEVEL_9_0, project)
    assert report["verdict"] == smg.INCOMPLETE_EVIDENCE
    assert report["unmet_conditions"] == []
    assert report["unavailable_conditions"]


def test_9_0_is_not_qualified_when_a_required_row_is_really_blocked(tmp_path):
    """The headline negative control for the verdict fold: a real gate-shaped
    FAIL must make the level NOT_QUALIFIED, never merely INCOMPLETE_EVIDENCE."""
    project = tmp_path / "proj"
    make_spec_to_uvm_pass_project(project)
    write_regression_evidence(project)
    write_state(project, {
        Stage.INTAKE.value: Status.PASS.value,
        Stage.REQUIREMENTS_TRACEABILITY.value: Status.PASS.value,
        Stage.IMPLEMENT.value: Status.PASS.value,
        Stage.BUILD.value: Status.PASS.value,
        Stage.VERIFY.value: Status.FAIL.value,
    })
    report = smg.derive_maturity_gate(smg.LEVEL_9_0, project)
    assert report["verdict"] == smg.NOT_QUALIFIED
    assert smg.COND_GOLDEN_FLOW_SPEC_TO_PASS in report["unmet_conditions"]


def test_9_5_requires_vip_api_and_bind_conditions_too(tmp_path, demo_index, clean_vip_source):
    project = tmp_path / "proj"
    make_spec_to_uvm_pass_project(project)
    write_regression_evidence(project)
    report = smg.derive_maturity_gate(smg.LEVEL_9_5, project)
    # 9.0's conditions are real and clean, but 9.5 also needs VIP-API/bind
    # evidence nobody supplied yet.
    assert report["verdict"] == smg.INCOMPLETE_EVIDENCE
    assert smg.COND_ZERO_VIP_API_HALLUCINATION in report["unavailable_conditions"]
    assert smg.COND_BIND_VALIDATION_CLEAN in report["unavailable_conditions"]

    d = write_vip_env(tmp_path, clean_vip_source)
    report_dict = vac.validate_vip_api_usage([d], demo_index, relative_to=d).to_dict()
    artifact = tmp_path / "vip_api_cards.json"
    artifact.write_text(json.dumps(report_dict), encoding="utf-8")
    inputs = smg.GateInputs(vip_api_cards_path=artifact, bind_topology_path=USB_BIND_TOPOLOGY)
    report = smg.derive_maturity_gate(smg.LEVEL_9_5, project, inputs)
    assert report["verdict"] == smg.QUALIFIED


def test_10_0_qualifies_with_false_pass_disclosed_as_a_caveat_not_a_blocker(
        tmp_path, demo_index, clean_vip_source):
    project = tmp_path / "proj"
    make_spec_to_uvm_pass_project(project)
    write_regression_evidence(project)
    d = write_vip_env(tmp_path, clean_vip_source)
    report_dict = vac.validate_vip_api_usage([d], demo_index, relative_to=d).to_dict()
    artifact = tmp_path / "vip_api_cards.json"
    artifact.write_text(json.dumps(report_dict), encoding="utf-8")
    real_smoke = sbp.SmokeProofReport(verdict=sbp.SYSTEM_READY,
                                      evidence="every rung PASSED against real evidence")
    inputs = smg.GateInputs(vip_api_cards_path=artifact, bind_topology_path=USB_BIND_TOPOLOGY,
                            smoke_proof_report=real_smoke.to_dict())
    report = smg.derive_maturity_gate(smg.LEVEL_10_0, project, inputs)
    assert report["verdict"] == smg.QUALIFIED
    assert smg.COND_FALSE_PASS_COUNT_ZERO in report["disclosed_caveats"]
    assert report["conditions"][smg.COND_FALSE_PASS_COUNT_ZERO]["status"] == smg.NOT_MEASURABLE


def test_10_0_is_not_qualified_when_the_smoke_proof_really_failed(
        tmp_path, demo_index, clean_vip_source):
    project = tmp_path / "proj"
    make_spec_to_uvm_pass_project(project)
    write_regression_evidence(project)
    d = write_vip_env(tmp_path, clean_vip_source)
    report_dict = vac.validate_vip_api_usage([d], demo_index, relative_to=d).to_dict()
    artifact = tmp_path / "vip_api_cards.json"
    artifact.write_text(json.dumps(report_dict), encoding="utf-8")
    real_smoke = sbp.SmokeProofReport(verdict=sbp.SMOKE_FAIL,
                                      evidence="smoke proof FAILED at BUILD")
    inputs = smg.GateInputs(vip_api_cards_path=artifact, bind_topology_path=USB_BIND_TOPOLOGY,
                            smoke_proof_report=real_smoke.to_dict())
    report = smg.derive_maturity_gate(smg.LEVEL_10_0, project, inputs)
    assert report["verdict"] == smg.NOT_QUALIFIED
    assert smg.COND_SYSTEM_SMOKE_PROOF_READY in report["unmet_conditions"]


# ===========================================================================
# 4. Reading is never a mutating act
# ===========================================================================

def test_evaluating_a_level_mutates_nothing_on_disk(tmp_path):
    """Every file this gate's own evaluators could have written stays
    byte-identical. (The same weaker-than-"no new file" invariant
    test_golden_flow_readiness.py's own
    test_producing_the_report_mutates_nothing_on_an_initialized_project
    already holds `derive_golden_flow_readiness()` to: its
    `five_level_memory` row calls `dashboard._read_memory_center_state()`,
    which materializes a default `config.json`/`control.json` for a project
    whose `.dv-harness` tree exists but has no config yet -- a real,
    pre-existing side effect of the module this gate composes, out of this
    module's own scope to change.)"""
    project = tmp_path / "proj"
    make_spec_to_uvm_pass_project(project)
    write_regression_evidence(project)
    before = fingerprint(project)
    smg.derive_maturity_gate(smg.LEVEL_9_0, project)
    after = fingerprint(project)
    for path, content in before.items():
        assert after.get(path) == content, f"{path} was modified by a read-only gate"


# ===========================================================================
# 5. Real CLI entry points
# ===========================================================================

def test_cli_conditions_verb_lists_all_six(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.subsystem_maturity_gate", "conditions", "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    ids = {c["condition_id"] for c in payload["conditions"]}
    assert ids == set(smg.CONDITIONS_BY_ID)


def test_cli_evaluate_verb_runs_a_real_qualified_9_0(tmp_path):
    project = tmp_path / "proj"
    make_spec_to_uvm_pass_project(project)
    write_regression_evidence(project)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.subsystem_maturity_gate", "evaluate",
         "--level", "9.0", "--root", str(project), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == smg.QUALIFIED


def test_cli_evaluate_verb_exits_2_on_incomplete_evidence(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.subsystem_maturity_gate", "evaluate",
         "--level", "10.0", "--root", str(project), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == smg.INCOMPLETE_EVIDENCE
