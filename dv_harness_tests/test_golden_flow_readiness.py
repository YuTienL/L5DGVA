"""Section 47's GOLDEN FLOW READINESS MATRIX as an auto-generated artifact
(`dv_harness/golden_flow_readiness.py` + `dv-harness golden-flow-readiness`).

WHAT THESE TESTS ARE FOR. Not "the function returns twenty dicts". The five
things that can actually go wrong with an aggregating report are:

  1. **A row that silently disappears.** Section 47's table is mandatory and
     twenty rows long; a project with nothing on disk must still produce all
     twenty (UNKNOWN), because "this row is unknown" and "this row was omitted"
     read identically to an auditor once the table is printed. The declared
     labels are additionally held against a transcription of the specification's
     own list, and the negative control proves that check has teeth.
  2. **A cell that is not sourced from anything.** Every row names the real
     reader it consulted, and each of those names is resolved through the import
     system -- a row claiming to read `dashboard._coverage_credit` after that
     function was renamed away is a row whose provenance is fiction. Each
     evidence-bearing row here is additionally driven from a REAL artifact
     written by a REAL writer (`storage.StateStore`, `MemoryStore.add`, a real
     coverage `summary.json`, real `.dv-harness/lsf/jobs/*.json`), never a
     patched-in return value.
  3. **A report that flatters the project.** Given as its negative controls:
     an LSF job that reached DONE with no DV analysis must NOT read as passing,
     a FAILED stage must make the whole matrix BLOCKED rather than PARTIAL, and
     a malformed coverage summary must be BLOCKED rather than "no coverage yet".
  4. **A read that is secretly a write.** Producing a readiness report must not
     change the readiness it reports: no state.json is minted for a project that
     never ran, no gate subprocess is invoked, and an initialized project's
     governance files are byte-identical afterwards.
  5. **The front door drifting from the module.** The CLI subcommand is driven
     as a REAL subprocess against a REAL project directory, so the wiring, the
     exit-code contract and the rendered column headers are proven together
     rather than assumed from the library call.

Nothing here runs a stage, a gate script, a build, a regression or an LSF
submission: every artifact is written directly by the real writer that owns it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import gates, golden_flow_readiness as gfr  # noqa: E402
from dv_harness.models import HarnessState, Stage, Status  # noqa: E402
from dv_harness.storage import StateStore  # noqa: E402


# ---------------------------------------------------------------------------
# Real-artifact helpers. Each writes through the real writer that owns the
# artifact, so a row reading it is reading what a real run would have left.
# ---------------------------------------------------------------------------

@pytest.fixture()
def project(tmp_path: Path) -> Path:
    return tmp_path / "proj"


def write_state(root: Path, statuses: dict, *, current_stage: str = Stage.INTAKE.value,
                messages: dict | None = None) -> None:
    """A real state.json through the real StateStore/HarnessState writer."""
    store = StateStore(root)
    state = HarnessState(project=root.name, current_stage=current_stage)
    state.ensure_stages()
    for stage, status in statuses.items():
        state.stages[stage]["status"] = status
    for stage, message in (messages or {}).items():
        state.stages[stage]["last_message"] = message
    store.save(state)


def write_coverage_summary(root: Path, categories: list) -> None:
    path = root / ".dv-harness" / "coverage" / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"categories": categories}), encoding="utf-8")


def write_lsf_job(root: Path, job: dict) -> None:
    path = root / ".dv-harness" / "lsf" / "jobs" / f"{job['job_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job), encoding="utf-8")


def write_protocol_registry(root: Path, protocols: dict) -> None:
    path = root / ".dv-harness" / "qualification" / "protocol_capability_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"protocols": protocols}), encoding="utf-8")


def row_of(matrix: dict, row_id: str) -> dict:
    return next(r for r in matrix["rows"] if r["row_id"] == row_id)


def fingerprint(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------------
# 1. The row set is the specification's row set
# ---------------------------------------------------------------------------

def test_declared_rows_are_section_47s_twenty_rows_in_order():
    assert gfr.row_labels() == list(gfr.SECTION_47_ROW_LABELS)
    assert len(gfr.ROWS) == 20


def test_section_47_row_check_has_teeth(monkeypatch):
    """The negative control for the check above: dropping a row must fail it.

    A self-validating list that only compares against itself would pass here,
    which is exactly the mistake the audit preceding this module found in a
    hand-assembled matrix.
    """
    monkeypatch.setattr(gfr, "ROWS", tuple(gfr.ROWS[:-1]))
    with pytest.raises(gfr.GoldenFlowReadinessError) as e:
        gfr._assert_rows_match_section_47()
    assert e.value.reason == "SECTION_47_ROW_SET_CHANGED"
    assert "Five-Level Memory" in e.value.detail["missing"]


def test_every_row_declares_a_probe_and_every_probe_has_a_row():
    gfr._assert_every_row_has_a_probe()
    assert set(gfr.PROBES) == {r.row_id for r in gfr.ROWS}


def test_every_declared_fact_source_still_resolves():
    """The reuse claim is checkable, not asserted: each row's named reader is
    resolved through the real import system."""
    resolved = gfr.assert_fact_sources_resolvable()
    assert "dv_harness.dashboard._read_coverage_state" in resolved
    assert "dv_harness.signoff_export.read_signoff_stage_status" in resolved
    assert "dv_harness.adapters.cli.ClaudeCLIAdapter._resolve_command" in resolved


def test_a_renamed_fact_source_is_refused(monkeypatch):
    bad = gfr.GoldenFlowRowSpec("x", "Spec In", (), ("dv_harness.dashboard._no_such_reader",), "")
    monkeypatch.setattr(gfr, "ROWS", (bad,))
    with pytest.raises(gfr.GoldenFlowReadinessError) as e:
        gfr.assert_fact_sources_resolvable()
    assert e.value.reason == "FACT_SOURCE_ATTRIBUTE_MISSING"


def test_every_declared_harness_stage_is_a_real_stage():
    gfr._assert_declared_stages_are_real()
    known = {s.value for s in Stage}
    for spec in gfr.ROWS:
        assert set(spec.harness_stages) <= known


# ---------------------------------------------------------------------------
# 2. Vocabulary: borrowed, total, worst-wins
# ---------------------------------------------------------------------------

def test_status_to_readiness_is_total_over_models_status():
    gfr.assert_status_mapping_total()
    assert set(gfr.STATUS_TO_READINESS) == {s.value for s in Status}


def test_accepted_risk_floors_to_partial_not_ready():
    """A human accepting residual risk is a real decision, not evidence that the
    stage is connected end-to-end."""
    assert gfr.STATUS_TO_READINESS[Status.ACCEPTED_RISK.value] == gfr.PARTIAL


def test_combine_readiness_rules():
    assert gfr.combine_readiness([]) == gfr.UNKNOWN
    assert gfr.combine_readiness([gfr.READY, gfr.READY]) == gfr.READY
    assert gfr.combine_readiness([gfr.UNKNOWN, gfr.UNKNOWN]) == gfr.UNKNOWN
    # half-connected is PARTIAL, never UNKNOWN -- real progress must not vanish
    assert gfr.combine_readiness([gfr.READY, gfr.UNKNOWN]) == gfr.PARTIAL
    # BLOCKED is worse than UNKNOWN: a known break must not be averaged away
    assert gfr.combine_readiness([gfr.READY, gfr.UNKNOWN, gfr.BLOCKED]) == gfr.BLOCKED
    with pytest.raises(gfr.GoldenFlowReadinessError):
        gfr.combine_readiness(["MOSTLY_FINE"])


# ---------------------------------------------------------------------------
# 3. A project that has never run: every row present, nothing written
# ---------------------------------------------------------------------------

def test_uninitialized_project_reports_all_twenty_rows(project: Path):
    project.mkdir(parents=True)
    matrix = gfr.derive_golden_flow_readiness(project)
    assert [r["row"] for r in matrix["rows"]] == list(gfr.SECTION_47_ROW_LABELS)
    assert matrix["summary"]["rows_total"] == 20
    assert matrix["golden_flow_readiness"] != gfr.READY
    # every stage-backed row is honestly UNKNOWN, and says why
    spec_in = row_of(matrix, "spec_in")
    assert spec_in["status"] == gfr.UNKNOWN
    assert "INTAKE" in spec_in["gap"]


def test_producing_the_report_writes_nothing_for_a_project_that_never_ran(project: Path):
    """A readiness report must not change the readiness it reports.

    Concretely: no state.json (StateStore.load() would mint one), no default
    config.json (config.load_config() would write one), no .dv-harness tree.
    """
    project.mkdir(parents=True)
    gfr.derive_golden_flow_readiness(project)
    assert list(project.rglob("*")) == []


def test_producing_the_report_mutates_nothing_on_an_initialized_project(project: Path):
    project.mkdir(parents=True)
    write_state(project, {Stage.INTAKE.value: Status.PASS.value})
    write_coverage_summary(project, [{"name": "fsm", "percent": 80.0,
                                      "bins_total": 10, "bins_hit": 8}])
    before = fingerprint(project)
    gfr.derive_golden_flow_readiness(project)
    after = fingerprint(project)
    for path, content in before.items():
        assert after.get(path) == content, f"{path} was modified by a read-only report"


def test_producing_the_report_invokes_no_gate_subprocess(project: Path, monkeypatch):
    """`effective_stage_gates()` is consulted for gate COUNTS; `run_gate()` --
    the function that actually launches a gate script -- must never fire."""
    project.mkdir(parents=True)
    write_state(project, {Stage.INTAKE.value: Status.PASS.value})

    def _explode(*a, **k):
        raise AssertionError("golden_flow_readiness must never run a gate script")

    monkeypatch.setattr(gates, "run_gate", _explode)
    matrix = gfr.derive_golden_flow_readiness(project)
    assert matrix["summary"]["rows_total"] == 20


# ---------------------------------------------------------------------------
# 4. Rows move on real evidence
# ---------------------------------------------------------------------------

def test_a_real_stage_pass_plus_a_real_document_makes_spec_in_ready(project: Path):
    project.mkdir(parents=True)
    write_state(project, {Stage.INTAKE.value: Status.PASS.value})
    uploads = project / ".dv-harness" / "uploads" / "spec"
    uploads.mkdir(parents=True)
    (uploads / "usb32_spec.pdf").write_bytes(b"%PDF-1.4 real bytes")

    row = row_of(gfr.derive_golden_flow_readiness(project), "spec_in")
    assert row["status"] == gfr.READY
    assert "INTAKE=PASS" in row["evidence"]
    assert "1 uploaded document(s)" in row["evidence"]
    assert row["gap"] == gfr.NONE_CELL
    assert row["next_best_action"] == gfr.NONE_CELL


def test_a_stage_pass_without_any_document_is_not_ready(project: Path):
    """Negative control for the row above: the stage verdict alone is not the
    Spec In evidence -- a PASS with no spec on disk must not read as ready."""
    project.mkdir(parents=True)
    write_state(project, {Stage.INTAKE.value: Status.PASS.value})
    row = row_of(gfr.derive_golden_flow_readiness(project), "spec_in")
    assert row["status"] != gfr.READY
    assert "no spec/RTL/reference document has been supplied" in row["gap"]


def test_a_failed_stage_blocks_its_row_and_the_whole_matrix(project: Path):
    project.mkdir(parents=True)
    write_state(project, {Stage.VERIFICATION_ARCHITECTURE.value: Status.FAIL.value})
    matrix = gfr.derive_golden_flow_readiness(project)
    row = row_of(matrix, "verification_contract")
    assert row["status"] == gfr.BLOCKED
    assert matrix["golden_flow_readiness"] == gfr.BLOCKED
    assert matrix["summary"]["rows_blocked"] >= 1
    # the blocked row is called out by name in the rendered report
    assert "Verification Contract" in gfr.format_golden_flow_readiness_report(matrix)


def test_single_test_proof_needs_both_build_and_verify(project: Path):
    project.mkdir(parents=True)
    write_state(project, {Stage.BUILD.value: Status.PASS.value})
    row = row_of(gfr.derive_golden_flow_readiness(project), "single_test_proof")
    assert row["status"] == gfr.PARTIAL, "a build that compiles is not a single-test proof"
    assert "VERIFY" in row["gap"]

    write_state(project, {Stage.BUILD.value: Status.PASS.value,
                          Stage.VERIFY.value: Status.PASS.value})
    row = row_of(gfr.derive_golden_flow_readiness(project), "single_test_proof")
    assert row["status"] == gfr.READY


def test_verification_ir_row_reads_the_real_project_model_evidence_block(project: Path):
    """PROJECT_MODEL PASSING is not the same as the section-33 IR fields
    existing -- the row reads the real gate evidence block, not the status."""
    project.mkdir(parents=True)
    write_state(project, {Stage.PROJECT_MODEL.value: Status.PASS.value})
    row = row_of(gfr.derive_golden_flow_readiness(project), "verification_ir")
    assert row["status"] != gfr.READY, "a stage PASS is not the IR fields existing"
    assert "project_model_topology_completeness_gate" in row["gap"]

    block = json.dumps({
        "verification_boundary": "usb31_dev top", "vip_topology": [{"vip_id": "u0"}],
        "blocks": [{"block_id": "b0", "branch": "BLOCK"}],
        "model_confidence": "HIGH", "dv_readiness": "READY"})
    message = f"```dv-harness-evidence:project_model_topology_completeness_gate\n{block}\n```"
    write_state(project, {Stage.PROJECT_MODEL.value: Status.PASS.value},
                messages={Stage.PROJECT_MODEL.value: message})
    row = row_of(gfr.derive_golden_flow_readiness(project), "verification_ir")
    assert row["status"] == gfr.READY
    assert "verification_boundary" in row["evidence"]


def test_coverage_rows_come_from_a_real_coverage_summary(project: Path):
    project.mkdir(parents=True)
    write_coverage_summary(project, [
        {"name": "fsm_states", "percent": 62.5, "bins_total": 8, "bins_hit": 5},
        {"name": "lpm_entry", "percent": 100.0, "bins_total": 4, "bins_hit": 4},
    ])
    matrix = gfr.derive_golden_flow_readiness(project)
    assert row_of(matrix, "coverage_collection")["status"] == gfr.READY
    holes = row_of(matrix, "coverage_hole_analysis")
    assert holes["status"] == gfr.PARTIAL
    assert "fsm_states" in holes["evidence"], "the worst hole must be named"
    assert "3 bins missing" in holes["evidence"]


def test_complete_coverage_makes_hole_analysis_and_next_best_test_ready(project: Path):
    project.mkdir(parents=True)
    write_coverage_summary(project, [
        {"name": "fsm_states", "percent": 100.0, "bins_total": 8, "bins_hit": 8}])
    matrix = gfr.derive_golden_flow_readiness(project)
    assert row_of(matrix, "coverage_hole_analysis")["status"] == gfr.READY
    assert row_of(matrix, "next_best_test")["status"] == gfr.READY


def test_a_malformed_coverage_summary_is_blocked_not_reported_as_absent(project: Path):
    """Negative control: "the coverage tool wrote something unusable" and "no
    coverage has been produced yet" are different facts with different fixes."""
    project.mkdir(parents=True)
    write_coverage_summary(project, [
        {"name": "fsm_states", "percent": 50.0, "bins_total": 4, "bins_hit": 9}])
    row = row_of(gfr.derive_golden_flow_readiness(project), "coverage_collection")
    assert row["status"] == gfr.BLOCKED
    assert "BINS_HIT_EXCEEDS_TOTAL" in row["gap"]


def test_next_best_test_classifies_real_holes_through_the_real_classifier(project: Path):
    project.mkdir(parents=True)
    write_coverage_summary(project, [
        {"name": "fsm_states", "percent": 62.5, "bins_total": 8, "bins_hit": 5}])
    row = row_of(gfr.derive_golden_flow_readiness(project), "next_best_test")
    # No pattern is traced to this bin, which classify_coverage_hole() computes
    # as MISSING_TEST -> a real recommended action, not an absence.
    assert row["status"] == gfr.READY
    assert "1/1 hole(s) have a recommended action" in row["evidence"]


def test_lsf_row_reads_dv_analysis_status_never_lsf_status(project: Path):
    """LSF DONE is not DV PASS -- the harness's own first-order rule, as a
    negative control on this row."""
    project.mkdir(parents=True)
    write_state(project, {Stage.REGRESSION.value: Status.PASS.value})
    write_lsf_job(project, {"job_id": "1001", "lsf_status": "DONE"})
    row = row_of(gfr.derive_golden_flow_readiness(project), "lsf_regression")
    assert row["status"] == gfr.PARTIAL
    assert "1 job(s) have no dv_analysis_status" in row["gap"]

    write_lsf_job(project, {"job_id": "1001", "lsf_status": "DONE",
                            "dv_analysis_status": "PASS"})
    row = row_of(gfr.derive_golden_flow_readiness(project), "lsf_regression")
    assert row["status"] == gfr.READY
    assert "1 DV-PASS" in row["evidence"]


def test_a_dv_confirmed_failure_blocks_the_lsf_row(project: Path):
    project.mkdir(parents=True)
    write_state(project, {Stage.REGRESSION.value: Status.PASS.value})
    write_lsf_job(project, {"job_id": "2001", "lsf_status": "EXIT",
                            "dv_analysis_status": "FAIL",
                            "last_change_time": "2026-09-05T00:00:00"})
    row = row_of(gfr.derive_golden_flow_readiness(project), "lsf_regression")
    assert row["status"] == gfr.BLOCKED
    assert "confirmed FAIL by DV analysis" in row["gap"]


def test_protocol_rows_read_the_real_capability_registry(project: Path):
    project.mkdir(parents=True)
    write_state(project, {Stage.PROTOCOL_CAPABILITY.value: Status.PASS.value,
                          Stage.ARCH_DISCOVERY.value: Status.PASS.value,
                          Stage.IMPLEMENT.value: Status.PASS.value})
    write_protocol_registry(project, {
        "PCIe": {"qualification_status": "BUILDER_AVAILABLE",
                 "capability_status": "PROTOCOL_MODEL_PARTIAL"},
        "Ethernet": {"qualification_status": "BUILDER_AVAILABLE",
                     "capability_status": "GENERIC_SKELETON_ONLY"},
    })
    matrix = gfr.derive_golden_flow_readiness(project)
    discovery = row_of(matrix, "protocol_topology_discovery")
    assert discovery["status"] == gfr.READY
    assert "2 protocol(s) registered" in discovery["evidence"]

    generation = row_of(matrix, "vip_uvm_generation")
    assert generation["status"] == gfr.PARTIAL
    assert "Ethernet" in generation["gap"]
    assert "PCIe" not in generation["gap"]


def test_signoff_row_uses_the_real_signoff_export_reader(project: Path):
    project.mkdir(parents=True)
    row = row_of(gfr.derive_golden_flow_readiness(project), "signoff_evidence")
    assert row["status"] == gfr.UNKNOWN
    assert "never recorded a verdict" in row["gap"]

    write_state(project, {Stage.SIGNOFF.value: Status.PASS.value})
    row = row_of(gfr.derive_golden_flow_readiness(project), "signoff_evidence")
    assert row["status"] == gfr.READY
    assert "gate_verified=True" in row["evidence"]


def test_five_level_memory_row_counts_real_memory_records(project: Path):
    from dv_harness.memory import MEMORY_LEVELS, MemoryStore
    project.mkdir(parents=True)
    store = MemoryStore(project)
    store.add("working", {"kind": "react_reasoning_step",
                          "summary": "hypothesis recorded"})
    row = row_of(gfr.derive_golden_flow_readiness(project), "five_level_memory")
    assert row["status"] == gfr.PARTIAL
    assert f"1/{len(MEMORY_LEVELS)} level(s)" in row["evidence"]
    assert "job" in row["gap"] and "engineering" in row["gap"]


def test_vplan_row_reports_an_unreadable_manifest_rather_than_passing_it(project: Path):
    """Negative control: a manifest that exists but is not schema-valid must
    surface as a gap, never be quietly treated as no manifest at all."""
    project.mkdir(parents=True)
    write_state(project, {Stage.VPLAN.value: Status.PASS.value})
    manifest = project / ".dv-harness" / "env.manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"env_topology": {}}), encoding="utf-8")
    row = row_of(gfr.derive_golden_flow_readiness(project), "vplan_traceability")
    assert row["status"] != gfr.READY
    assert "env.manifest.json unreadable" in row["gap"]


# ---------------------------------------------------------------------------
# 5. Aggregation, the Next-Best-Action column, and the rendered table
# ---------------------------------------------------------------------------

def test_next_best_action_comes_from_the_real_inference_catalog(project: Path):
    project.mkdir(parents=True)
    matrix = gfr.derive_golden_flow_readiness(project)
    catalog = gfr.GOLDEN_FLOW_GAP_ACTION_CATALOG["actions"]
    for row in matrix["rows"]:
        if row["status"] == gfr.READY:
            assert row["next_best_action"] == gfr.NONE_CELL, \
                "a closed row must not carry a next action"
        else:
            assert row["next_best_action"] == catalog[row["row_id"]]


def test_next_best_action_is_produced_by_inference_next_best_action(monkeypatch, project: Path):
    """The column is not hand-rolled: it goes through the real, shared
    Gap -> Next-Best-Action engine, with this module's catalog."""
    seen = {}
    import dv_harness.inference as inference
    real = inference.next_best_action

    def _spy(protocol, gaps, root, *, gap_action_catalog=None):
        seen["catalog"] = gap_action_catalog
        seen["gaps"] = list(gaps)
        return real(protocol, gaps, root, gap_action_catalog=gap_action_catalog)

    monkeypatch.setattr(inference, "next_best_action", _spy)
    project.mkdir(parents=True)
    gfr.derive_golden_flow_readiness(project)
    assert seen["catalog"] is gfr.GOLDEN_FLOW_GAP_ACTION_CATALOG
    assert "spec_in" in seen["gaps"]


def test_rendered_table_uses_the_documents_own_five_columns(project: Path):
    project.mkdir(parents=True)
    matrix = gfr.derive_golden_flow_readiness(project)
    table = gfr.render_golden_flow_matrix(matrix)
    header = table.splitlines()[0]
    for _, label in gfr.GOLDEN_FLOW_MATRIX_COLUMNS:
        assert f"| {label} " in header or header.endswith(f"| {label} |")
    for label in gfr.SECTION_47_ROW_LABELS:
        assert f"| {label} |" in table


def test_a_pipe_in_real_evidence_cannot_break_the_table(project: Path):
    """A `blocking_reason` read off a real state.json may legitimately contain a
    `|`; the rendered row must still have exactly five cells."""
    project.mkdir(parents=True)
    store = StateStore(project)
    state = HarnessState(project=project.name)
    state.ensure_stages()
    state.stages[Stage.VPLAN.value]["status"] = Status.BLOCKED.value
    state.stages[Stage.VPLAN.value]["blocking_reason"] = "gate a|b failed\nsecond line"
    store.save(state)

    table = gfr.render_golden_flow_matrix(gfr.derive_golden_flow_readiness(project))
    line = next(l for l in table.splitlines() if l.startswith("| vPlan / Traceability |"))
    assert len(line.split(" | ")) == len(gfr.GOLDEN_FLOW_MATRIX_COLUMNS)
    assert "a\\|b" in line and "\n" not in line


def test_report_states_the_rule_and_that_it_authorizes_nothing(project: Path):
    project.mkdir(parents=True)
    text = gfr.format_golden_flow_readiness_report(gfr.derive_golden_flow_readiness(project))
    assert "GOLDEN FLOW READINESS MATRIX (section 47)" in text
    assert "READY only when required stages are connected end-to-end" in text
    assert "This verdict authorizes: nothing" in text


def test_execute_exit_code_contract(project: Path):
    project.mkdir(parents=True)
    code, matrix, text = gfr.execute(project)
    assert matrix["golden_flow_readiness"] != gfr.READY
    assert code == 2
    assert "Golden Flow Stage" in text
    # and the rule the code implements, stated independently of any project
    assert (0 if gfr.combine_readiness([gfr.READY, gfr.READY]) == gfr.READY else 2) == 0


# ---------------------------------------------------------------------------
# 6. The CLI front door, driven as a real subprocess
# ---------------------------------------------------------------------------

def _run_cli(project: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(project),
         "golden-flow-readiness", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)


def test_cli_subcommand_renders_the_document_table(project: Path):
    project.mkdir(parents=True)
    write_state(project, {Stage.INTAKE.value: Status.PASS.value})
    proc = _run_cli(project)
    assert proc.returncode == 2, proc.stderr
    assert "GOLDEN FLOW READINESS MATRIX (section 47)" in proc.stdout
    for label in gfr.SECTION_47_ROW_LABELS:
        assert f"| {label} |" in proc.stdout


def test_cli_json_flag_emits_the_full_machine_readable_matrix(project: Path):
    project.mkdir(parents=True)
    proc = _run_cli(project, "--json")
    assert proc.returncode == 2, proc.stderr
    matrix = json.loads(proc.stdout)
    assert matrix["schema_version"] == gfr.SCHEMA_VERSION
    assert [r["row"] for r in matrix["rows"]] == list(gfr.SECTION_47_ROW_LABELS)
    # provenance travels with the data, not only with the prose
    assert all(r["fact_source"] for r in matrix["rows"])


def test_module_entry_point_leaves_an_uninitialized_project_untouched(project: Path):
    """The untouched-tree guarantee the module docstring claims, proven through
    a real subprocess rather than an in-process call."""
    project.mkdir(parents=True)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.golden_flow_readiness",
         "--project-root", str(project)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 2, proc.stderr
    assert list(project.rglob("*")) == []


def test_module_entry_point_and_cli_agree(project: Path):
    """One shared implementation, the same convention loop-contract uses."""
    project.mkdir(parents=True)
    cli = _run_cli(project, "--json")
    mod = subprocess.run(
        [sys.executable, "-m", "dv_harness.golden_flow_readiness",
         "--project-root", str(project), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    assert cli.returncode == mod.returncode == 2, mod.stderr
    a, b = json.loads(cli.stdout), json.loads(mod.stdout)
    assert [(r["row_id"], r["status"], r["gap"]) for r in a["rows"]] == \
           [(r["row_id"], r["status"], r["gap"]) for r in b["rows"]]


def test_cli_does_not_mutate_governance_state(project: Path):
    """The CLI wrapper constructs a `DVHarness` before dispatching ANY
    subcommand -- which bootstraps `.dv-harness/` and appends the usual
    `CLI_ACCESS` audit event, exactly as `status` or `explain` does. What this
    subcommand must never do is change state: the recorded stage verdicts must
    be byte-identical afterwards. (The read-only guarantee of the module itself,
    with no CLI bootstrap in front of it, is proven above.)"""
    project.mkdir(parents=True)
    write_state(project, {Stage.INTAKE.value: Status.PASS.value,
                          Stage.BUILD.value: Status.FAIL.value})
    state_file = project / ".dv-harness" / "state.json"
    before = state_file.read_bytes()
    proc = _run_cli(project)
    assert proc.returncode == 2, proc.stderr
    assert state_file.read_bytes() == before
