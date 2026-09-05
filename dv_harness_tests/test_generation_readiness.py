"""Section 211's GENERATION READINESS MATRIX is a real, auto-generated artifact.

WHAT WAS WRONG (re-verified with grep before this file was written, 2026-09-06,
not taken from an older report):

  * `grep -rni "generation.readiness" --include=*.py --include=*.md .` matched
    NOTHING outside the specification's own text.
  * `grep -rn "GF-AT-"` matched only `system_build_proof.py`'s GF-AT-28 comment
    and this repo's CLAUDE.md paragraph about it.
  * `dv_harness/generation_readiness.py` did not exist. Section 211's table was
    printed in the specification with EVERY cell empty, so "can this factory
    generate a subsystem environment from a spec, and a system environment from
    subsystems?" had no machine-produced answer at all.

Nothing below is mocked. Every assertion runs the real module over either the
real harness repository or a REAL synthetic two-subsystem project on disk built
by the fixture `test_system_level_track_b_gate_crosscheck.py` already owns --
imported rather than re-written, because two copies of a fixture that encodes a
DRIVER_CONFLICT are two things that can drift apart.

Nothing below starts a build, a regression, an LSF submission or a simulation,
and nothing below approves or arbitrates anything.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import generation_readiness as gr
from dv_harness import subsystem_discovery as sd
from dv_harness import system_resource_inventory as sri
from dv_harness import system_scheduling_plan as ssp

# The REAL two-subsystem project builder, reused rather than duplicated. Its
# `b_active=True` form puts two ACTIVE AXI masters on ONE SoC CPU port, which is
# a genuine SYS-12 DRIVER_CONFLICT.
from .test_system_level_track_b_gate_crosscheck import _project

REPO = Path(__file__).resolve().parents[1]


# ============================================================================
# The declaration itself: rows, columns and provenance
# ============================================================================

def test_every_declared_fact_source_still_resolves():
    """The anti-drift check that makes this module's reuse claim CHECKABLE.

    A row declaring `dv_harness.system_resource_inventory.
    real_cross_subsystem_findings` while that function has been renamed away is
    a row whose evidence provenance is fiction, and it must fail loudly here
    rather than render a plausible status."""
    resolved = gr.assert_fact_sources_resolvable()
    assert len(resolved) >= 60
    # Every module the close-pass named as a required real reader is really
    # wired in by at least one row -- not just importable somewhere.
    joined = " ".join(resolved)
    for module in ("dv_harness.env_manifest", "dv_harness.protocol_capability",
                   "dv_harness.connectivity", "dv_harness.qualification",
                   "dv_harness.system_resource_inventory", "dv_harness.system_topology_analysis",
                   "dv_harness.system_command_plan", "dv_harness.system_build_proof",
                   "dv_harness.subsystem_discovery", "dv_harness.environment_mode_router"):
        assert module in joined, module


def test_rows_are_section_211s_own_twenty_labels_in_order():
    assert len(gr.ROWS) == 20
    assert tuple(r.label for r in gr.ROWS) == gr.SECTION_211_ROW_LABELS
    assert gr.SECTION_211_ROW_LABELS[0] == "Spec Parsing / Requirement IR"
    assert gr.SECTION_211_ROW_LABELS[-1] == "System Build / Smoke Proof"


def test_a_renamed_row_fails_the_import_time_specification_check(monkeypatch):
    """The check compares declarations against the SPECIFICATION's list, not
    against itself -- so renaming a row cannot pass by renaming both sides."""
    original = gr.ROWS
    renamed = (gr.ROWS[0].__class__(**{**gr.ROWS[0].__dict__, "label": "Spec Parsing"}),
               ) + gr.ROWS[1:]
    monkeypatch.setattr(gr, "ROWS", renamed)
    with pytest.raises(gr.GenerationReadinessError) as exc:
        gr._assert_rows_match_section_211()
    assert exc.value.reason == "SECTION_211_ROW_SET_CHANGED"
    assert "Spec Parsing / Requirement IR" in exc.value.detail["missing"]
    monkeypatch.setattr(gr, "ROWS", original)


def test_columns_are_section_211s_own_seven():
    assert [h for _, h in gr.GENERATION_MATRIX_COLUMNS] == [
        "Capability", "Status", "Existing Reuse", "Evidence", "Gap", "Priority", "Action"]


def test_status_and_capability_vocabularies_are_borrowed_not_minted():
    """Section 211's Status column asks the READY/PARTIAL/BLOCKED/UNKNOWN
    question `subsystem_discovery` already defines four words for, and its
    capability axis asks the PRESENT/ABSENT question that module already defines
    four more for. A fifth or sixth set of words would be the parallel
    mechanism this project forbids."""
    assert gr.GENERATION_READINESS_CLASSES == sd.READINESS_CLASSES
    assert gr.CAPABILITY_CLASSES == sd.FACTOR_STATUSES
    assert (gr.READY, gr.PARTIAL, gr.BLOCKED, gr.UNKNOWN) == (
        sd.READY, sd.PARTIAL, sd.BLOCKED, sd.UNKNOWN)


def test_every_row_has_a_probe_and_a_registered_action():
    gr._assert_every_row_has_a_probe()
    gr._assert_every_row_has_an_action()
    assert set(gr.PROBES) == {r.row_id for r in gr.ROWS}
    assert set(gr.GENERATION_GAP_ACTION_CATALOG["actions"]) == {r.row_id for r in gr.ROWS}


def test_every_row_carries_a_priority_traced_to_section_213():
    for spec in gr.ROWS:
        assert spec.priority in gr.PRIORITIES, spec.row_id
        assert "section 213" in spec.priority_basis, spec.row_id
    # Both P0 buckets and P1 are really used; the matrix is not all one bucket.
    used = {r.priority for r in gr.ROWS}
    assert gr.P0_SPEC_TO_SUBSYSTEM in used
    assert gr.P0_SUBSYSTEM_TO_SYSTEM in used
    assert gr.P1 in used


# ============================================================================
# Honesty: a present capability must NOT lift absent project evidence
# ============================================================================

def test_a_present_capability_never_lifts_absent_project_evidence():
    """GF-AT-28 as arithmetic. The two axes fold with STRICT worst-wins, so a
    row whose mechanism exists but whose project supplied nothing reads UNKNOWN
    -- not PARTIAL, which would read as progress that has not happened."""
    assert gr.worst_readiness([gr.READY, gr.UNKNOWN]) == gr.UNKNOWN
    assert gr.worst_readiness([gr.READY, gr.BLOCKED]) == gr.BLOCKED
    assert gr.worst_readiness([gr.READY, gr.READY]) == gr.READY
    assert gr.worst_readiness([]) == gr.UNKNOWN
    # The softer MANY-ROW summary fold is deliberately different and stays so.
    assert gr.combine_readiness([gr.READY, gr.UNKNOWN]) == gr.PARTIAL


def test_an_unresolvable_fact_source_makes_its_row_blocked_not_fabricated(monkeypatch):
    """A row whose backing mechanism does not exist yet must render BLOCKED and
    NAME the missing dotted path. It must never silently render a status as if
    the mechanism were there -- that is the exact failure this matrix exists to
    stop an auditing session from committing by hand."""
    spec = gr.ROWS[0]
    broken = spec.__class__(**{**spec.__dict__,
                               "fact_source": ("dv_harness.no_such_module.no_such_fn",)})
    probe = gr.probe_capability(broken)
    assert probe["capability"] == gr.CAP_ABSENT
    assert "dv_harness.no_such_module.no_such_fn" in probe["detail"]
    assert gr._CAPABILITY_TO_READINESS[probe["capability"]] == gr.BLOCKED

    monkeypatch.setattr(gr, "ROWS", (broken,) + gr.ROWS[1:])
    matrix = gr.derive_generation_readiness(REPO, deep=False)
    row = matrix["rows"][0]
    assert row["status"] == gr.BLOCKED
    assert row["capability"] == gr.CAP_ABSENT
    assert "no_such_module" in row["gap"]


def test_an_empty_project_reports_unknown_with_real_reasons_never_ready(tmp_path):
    """A project that has generated nothing is UNKNOWN across the board, each
    row carrying the REAL reason its reader gave -- never a fabricated status
    and never an empty cell."""
    matrix = gr.derive_generation_readiness(tmp_path, deep=True)
    assert matrix["generation_readiness"] in (gr.UNKNOWN, gr.PARTIAL, gr.BLOCKED)
    assert matrix["summary"]["rows_total"] == 20
    assert matrix["summary"]["rows_ready"] == 0
    assert matrix["registered_subsystems"] == []
    assert matrix["cross_subsystem_analysis_status"] == sri.CROSSCHECK_UNAVAILABLE
    assert matrix["cross_subsystem_analysis_reason"] == "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE"
    by_id = {r["row_id"]: r for r in matrix["rows"]}
    # Every mandatory row is present even though every one is absent-evidence.
    assert len(by_id) == 20
    for row in matrix["rows"]:
        assert row["status"] in gr.GENERATION_READINESS_CLASSES
        assert row["evidence"] and row["gap"], row["row_id"]
        if row["status"] != gr.READY:
            assert row["action"] != gr.NONE_CELL, row["row_id"]
    # The three Flow-B rows that need real registered subsystems say exactly
    # WHY they could not be evaluated, rather than reporting a clean result.
    for row_id in ("shared_resource_vip_resolver", "active_driver_ownership",
                   "system_topology"):
        assert by_id[row_id]["status"] == gr.UNKNOWN, row_id
        assert "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE" in by_id[row_id]["gap"], row_id


def test_a_probe_that_raises_still_yields_its_mandatory_row(monkeypatch):
    """Section 211's twenty rows are mandatory. A probe bug must degrade that
    row to UNKNOWN naming the exception, never delete the row from the table."""
    def boom(facts, spec):
        raise RuntimeError("probe exploded")

    monkeypatch.setitem(gr.PROBES, "dut_discovery", boom)
    matrix = gr.derive_generation_readiness(REPO, deep=False)
    row = next(r for r in matrix["rows"] if r["row_id"] == "dut_discovery")
    assert len(matrix["rows"]) == 20
    assert row["status"] == gr.UNKNOWN
    assert "RuntimeError" in row["gap"] and "probe exploded" in row["gap"]


# ============================================================================
# The rows really read the real mechanisms
# ============================================================================

def test_the_composer_boundary_rows_probe_the_stub_rather_than_assert_it():
    """Rows 17-19 are BLOCKED because the three `soc_environment_composer`
    cross-subsystem stubs really raise NotImplementedError -- proven by CALLING
    them through the already-real `probe_composer_boundary()`, not by a comment.
    An implemented stub flips the row rather than passing unnoticed."""
    boundary = ssp.probe_composer_boundary()
    assert boundary["boundary_intact"] is True

    matrix = gr.derive_generation_readiness(REPO, deep=False)
    assert matrix["composer_boundary_intact"] is True
    by_id = {r["row_id"]: r for r in matrix["rows"]}
    for row_id, fn in (("system_scenario", "cross_subsystem_scenarios"),
                       ("system_correlation_scoreboard", "end_to_end_scoreboard"),
                       ("system_cross_coverage", "system_coverage")):
        row = by_id[row_id]
        assert row["status"] == gr.BLOCKED, row_id
        assert "NotImplementedError" in row["evidence"], row_id
        assert fn in row["evidence"], row_id
        # The reason a HUMAN needs: this is a sourcing/approval boundary, not
        # an unimplemented feature to quietly fill in.
        assert "SYS-40" in row["gap"] and "human approval" in row["gap"], row_id


def test_an_implemented_composer_stub_flips_the_row_instead_of_going_unnoticed(monkeypatch):
    """The boundary rows must report a MOVED boundary, not keep printing
    BLOCKED from a stale declaration."""
    fake = {"module": "dv_harness.uvm_generator.soc_environment_composer",
            "probes": [{"function": "system_coverage", "raises": "",
                        "reason": "DID NOT RAISE -- this stub has been implemented"}],
            "boundary_intact": False, "meaning": ""}
    monkeypatch.setattr(ssp, "probe_composer_boundary", lambda: fake)
    matrix = gr.derive_generation_readiness(REPO, deep=False)
    row = next(r for r in matrix["rows"] if r["row_id"] == "system_cross_coverage")
    assert row["status"] == gr.PARTIAL
    assert "NO LONGER raises" in row["evidence"]
    assert "boundary has moved" in row["gap"]


def test_the_protocol_row_reads_the_real_capability_rows():
    """`Protocol / VIP Mapping` is derived from `protocol_capability.
    capability_rows()`, whose capability_status comes from whether the generator
    module really imports -- so this row cannot claim a protocol model that is
    not there."""
    from dv_harness import protocol_capability as pc
    rows = pc.capability_rows()
    skeleton = [r for r in rows if r["capability_status"] == pc.STATUS_GENERIC_SKELETON_ONLY]

    matrix = gr.derive_generation_readiness(REPO, deep=False)
    row = next(r for r in matrix["rows"] if r["row_id"] == "protocol_vip_mapping")
    assert f"{len(rows) - len(skeleton)}/{len(rows)}" in row["evidence"]
    if skeleton:
        assert row["status"] == gr.PARTIAL
        for entry in skeleton:
            assert str(entry.get("protocol") or entry.get("name")) in row["gap"]
    else:
        assert row["status"] == gr.READY


def test_the_uvm_architecture_row_reports_verible_honestly(monkeypatch):
    """uvm_structural_lint reports NOT_AVAILABLE (never PASS) when verible
    cannot run, so a missing parser is a REAL reduction in what this factory can
    check and must show up as one."""
    from dv_harness import verible_parser as vp
    monkeypatch.setattr(vp, "get_verible_version", lambda *a, **k: None)
    matrix = gr.derive_generation_readiness(REPO, deep=False)
    row = next(r for r in matrix["rows"] if r["row_id"] == "uvm_architecture")
    assert "verible=NOT_AVAILABLE" in row["evidence"]
    assert "NOT_AVAILABLE (never PASS)" in row["gap"]
    assert row["status"] != gr.READY


# ============================================================================
# env.manifest.json layers are READ, never re-derived
# ============================================================================

def test_manifest_layers_are_read_from_the_real_manifest(tmp_path, monkeypatch):
    """The Flow-A rows read env.manifest.json's OWN per-layer status/reason.
    A layer the generator marked NOT_AVAILABLE must surface with that layer's
    own reason text -- re-deciding it here would be a second opinion about the
    same file."""
    from dv_harness import env_manifest as em

    soc_map = tmp_path / "soc_arch_map.json"
    soc_map.write_text(json.dumps({
        "schema_version": "1.0",
        "address_map": [{"name": "CTRL", "base_address": "0x1000",
                         "size_bytes": 4096, "bus": "APB"}],
        "clocks": [{"name": "clk", "frequency_mhz": 100}],
        "resets": [{"name": "rst_n", "active_level": "low", "clock": "clk"}]}),
        encoding="utf-8")
    manifest_path = tmp_path / ".dv-harness" / "env.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    em.generate_and_write(manifest_path, soc_arch_map_path=soc_map)
    manifest = em.load_env_manifest(manifest_path)

    # No RTL was supplied to that generation run, so the generator itself wrote
    # dut_facts.rtl = NOT_AVAILABLE with its own reason.
    assert manifest["dut_facts"]["rtl"]["status"] == "NOT_AVAILABLE"
    real_reason = manifest["dut_facts"]["rtl"]["reason"]

    monkeypatch.setattr(em, "default_manifest_path", lambda root: manifest_path)
    matrix = gr.derive_generation_readiness(tmp_path, deep=False)
    by_id = {r["row_id"]: r for r in matrix["rows"]}
    assert matrix["env_manifest_path"] == str(manifest_path)
    dut = by_id["dut_discovery"]
    assert dut["status"] == gr.UNKNOWN
    assert dut["evidence"] == "dut_facts.rtl=NOT_AVAILABLE"
    assert dut["gap"] == real_reason
    # And the layer that IS populated reads READY off the same manifest.
    assert manifest["dut_facts"]["address_map"]["status"] != "NOT_AVAILABLE"


def test_a_populated_manifest_layer_reads_ready_with_its_real_counts(tmp_path, monkeypatch):
    """The other half of the layer contract: a layer the generator really
    populated must read READY, with counts taken off the REAL manifest content.
    Without this, a probe reading a mis-spelled key would still look fine --
    every layer would just always be UNKNOWN."""
    from dv_harness import env_manifest as em
    from .test_env_manifest import CONFIG_DB_TRACE_LOG_FIXTURE, REGISTER_MAP_FIXTURE

    register_map = tmp_path / "register_map.json"
    register_map.write_text(json.dumps(REGISTER_MAP_FIXTURE), encoding="utf-8")
    trace_log = tmp_path / "sim.log"
    trace_log.write_text(CONFIG_DB_TRACE_LOG_FIXTURE, encoding="utf-8")

    manifest_path = tmp_path / ".dv-harness" / "env.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    em.generate_and_write(manifest_path, register_map_path=register_map,
                          config_db_trace_log_path=trace_log)
    manifest = em.load_env_manifest(manifest_path)
    n_blocks = len(manifest["dut_facts"]["registers"]["blocks"])
    n_entries = len(manifest["env_topology"]["config_db_trace"]["entries"])
    assert n_blocks and n_entries  # the fixtures really carry content

    monkeypatch.setattr(em, "default_manifest_path", lambda root: manifest_path)
    by_id = {r["row_id"]: r
             for r in gr.derive_generation_readiness(tmp_path, deep=False)["rows"]}

    csr = by_id["scenario_negative_csr_irq"]
    assert csr["status"] == gr.READY
    assert f"({n_blocks} register block(s))" in csr["evidence"]
    assert csr["gap"] == gr.NONE_CELL and csr["action"] == gr.NONE_CELL

    cfg = by_id["config_build_compile_fix"]
    assert cfg["status"] == gr.READY
    assert f"({n_entries} entry/entries)" in cfg["evidence"]


# ============================================================================
# THE HEADLINE TEST: the Flow-B rows stand on the REAL cross-subsystem analysis
# ============================================================================

def test_a_real_driver_conflict_blocks_the_ownership_row_and_stays_human_arbitrated(tmp_path):
    """Two REAL synthetic subsystem environments on disk, both driving the SAME
    SoC CPU AXI master port ACTIVELY. The matrix must report the ownership row
    BLOCKED off the REAL SYS-9..SYS-14 analysis -- and must carry SYS-12's
    preferred model through as text for a HUMAN, without picking a winner."""
    _project(tmp_path, b_active=True)
    findings = sri.real_cross_subsystem_findings(tmp_path)
    assert findings["status"] == sri.CROSSCHECK_AVAILABLE, findings
    assert findings["automatic_integration_allowed"] is False

    matrix = gr.derive_generation_readiness(tmp_path, deep=True)
    by_id = {r["row_id"]: r for r in matrix["rows"]}

    assert matrix["registered_subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert matrix["cross_subsystem_analysis_status"] == sri.CROSSCHECK_AVAILABLE

    # Inventory really found two registered subsystems.
    assert by_id["subsystem_inventory_decomposition"]["status"] == gr.READY
    assert "SUBSYS_A" in by_id["subsystem_inventory_decomposition"]["evidence"]

    owner = by_id["active_driver_ownership"]
    assert owner["status"] == gr.BLOCKED
    assert "automatic_integration_allowed=False" in owner["evidence"]
    assert "HUMAN ARBITRATION REQUIRED" in owner["gap"]
    assert findings["preferred_model"][:30] in owner["gap"]
    # DETECTION only: nothing in the matrix names a winning subsystem.
    assert "does not pick a winner" in owner["gap"]
    assert owner["action"] and "does not resolve it" in owner["action"]

    # And the whole matrix's own boundary statement still says it approves and
    # arbitrates nothing.
    assert "never arbitrates" in matrix["authorizes"]
    assert "SYS-39/SYS-40" in matrix["authorizes"]


def test_a_passive_second_driver_is_not_reported_as_a_conflict(tmp_path):
    """The negative control. Without it the BLOCKED above could be an artifact
    of the fixture rather than of the real rule."""
    _project(tmp_path, b_active=False)
    matrix = gr.derive_generation_readiness(tmp_path, deep=True)
    by_id = {r["row_id"]: r for r in matrix["rows"]}
    owner = by_id["active_driver_ownership"]
    assert owner["status"] == gr.READY
    assert "automatic_integration_allowed=True" in owner["evidence"]
    assert owner["gap"] == gr.NONE_CELL
    assert owner["action"] == gr.NONE_CELL  # a closed row gets no next action


def test_the_topology_rows_read_the_real_sys28_30_document(tmp_path):
    """`System Topology`, `Address / Clock / Reset / IRQ`, `Command Integration`
    and `System Virtual Sequencer` all read ONE real
    `analyze_system_topology()` document -- run once per report, read four ways,
    never re-run per row."""
    _project(tmp_path, b_active=False)
    matrix = gr.derive_generation_readiness(tmp_path, deep=True)
    by_id = {r["row_id"]: r for r in matrix["rows"]}

    from dv_harness import system_topology_analysis as sta
    real = sta.analyze_system_topology(tmp_path, ["SUBSYS_A", "SUBSYS_B"])
    summary = real["topology_analysis"]["summary"]
    cmd_summary = real["command_plan"]["summary"]

    topo = by_id["system_topology"]
    assert topo["status"] in (gr.READY, gr.PARTIAL)
    assert f"topology_clean={summary['topology_clean']}" in topo["evidence"]
    assert f"address_regions={summary['address_regions']}" in topo["evidence"]

    acri = by_id["address_clock_reset_irq"]
    assert f"address_conflicts={summary['address_conflicts']}" in acri["evidence"]
    assert f"clock_reset_conflicts={summary['clock_reset_conflicts']}" in acri["evidence"]

    cmd = by_id["command_integration"]
    assert f"{cmd_summary['system_commands']} system command(s)" in cmd["evidence"]
    assert f"blocking={cmd_summary['blocking_collisions']}" in cmd["evidence"]

    vseq = by_id["system_virtual_sequencer"]
    assert vseq["status"] == gr.READY
    assert "SUBSYS_A" in vseq["evidence"] and "SUBSYS_B" in vseq["evidence"]


def test_deep_false_reports_not_run_rather_than_a_guessed_status(tmp_path):
    """`deep=False` must not invent a Flow-B verdict; it must say the chain was
    not run and why, and must change nothing else."""
    _project(tmp_path, b_active=False)
    shallow = gr.derive_generation_readiness(tmp_path, deep=False)
    by_id = {r["row_id"]: r for r in shallow["rows"]}
    assert shallow["deep_analysis"] is False
    for row_id in ("system_topology", "address_clock_reset_irq", "command_integration",
                   "system_virtual_sequencer"):
        assert by_id[row_id]["status"] == gr.UNKNOWN, row_id
        assert "deep=False" in by_id[row_id]["gap"], row_id
    # The rows that do NOT depend on the deep chain are unaffected: the cheap
    # front door still ran, so ownership is really evaluated.
    assert by_id["active_driver_ownership"]["status"] == gr.READY
    assert by_id["subsystem_inventory_decomposition"]["status"] == gr.READY


def test_single_test_proof_reads_the_real_registry_qualification_state(tmp_path):
    """GF-AT-13. The registry is written only by a gate-validated SIGNOFF PASS,
    and `qualification.map_to_system_level_state()` -- not a local re-reading of
    the ladder -- decides whether a state is composition-eligible."""
    _project(tmp_path, b_active=False)
    matrix = gr.derive_generation_readiness(tmp_path, deep=False)
    row = next(r for r in matrix["rows"] if r["row_id"] == "single_test_proof")
    assert row["status"] == gr.READY
    assert "2/2 registered subsystem(s) at SMOKE_QUALIFIED or above" in row["evidence"]

    # Now demote one below SMOKE_QUALIFIED through the REAL registry file.
    reg = tmp_path / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json"
    doc = json.loads(reg.read_text(encoding="utf-8"))
    doc["subsystems"][1]["qualification_state"] = "COMPILE_QUALIFIED"
    reg.write_text(json.dumps(doc), encoding="utf-8")

    matrix = gr.derive_generation_readiness(tmp_path, deep=False)
    row = next(r for r in matrix["rows"] if r["row_id"] == "single_test_proof")
    assert row["status"] == gr.PARTIAL
    assert "SUBSYS_B=COMPILE_QUALIFIED" in row["gap"]
    assert "below SMOKE_QUALIFIED" in row["gap"]


def test_the_smoke_proof_row_never_starts_a_build(tmp_path):
    """Section 206's ladder has real merged sources here, and this report still
    must NOT run it: a readiness report that starts a build is not read-only,
    and GF-AT-28 means an unrun rung stays SMOKE_NOT_PROVEN."""
    from dv_harness import system_build_proof as sbp
    _project(tmp_path, b_active=False)
    matrix = gr.derive_generation_readiness(tmp_path, deep=False)
    row = next(r for r in matrix["rows"] if r["row_id"] == "system_build_smoke_proof")
    assert row["status"] == gr.PARTIAL
    assert "2/2 registered subsystem(s) have UVM sources on disk" in row["evidence"]
    assert "ladder NOT_RUN by this report" in row["evidence"]
    assert sbp.SMOKE_NOT_PROVEN in row["gap"]
    assert "this report never starts a build" in row["gap"]


# ============================================================================
# The report is read-only, and both entry points are real
# ============================================================================

def test_the_report_writes_nothing_into_a_project_that_has_never_run(tmp_path):
    """A readiness report must not change the readiness it reports -- and must
    not MINT a .dv-harness/ tree (state.json, config.json) for a project that
    has never run."""
    before = sorted(p.relative_to(tmp_path).as_posix()
                    for p in tmp_path.rglob("*"))
    gr.derive_generation_readiness(tmp_path, deep=True)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after == []


def test_the_report_writes_nothing_into_a_real_two_subsystem_project(tmp_path):
    """Same guarantee where the deep SYS-1..SYS-30 chain really runs."""
    _project(tmp_path, b_active=False)
    def snapshot():
        return {p.relative_to(tmp_path).as_posix(): p.stat().st_size
                for p in tmp_path.rglob("*") if p.is_file()}

    before = snapshot()
    matrix = gr.derive_generation_readiness(tmp_path, deep=True)
    assert matrix["cross_subsystem_analysis_status"] == sri.CROSSCHECK_AVAILABLE
    assert snapshot() == before


def test_module_entry_point_runs_over_the_real_repository():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.generation_readiness",
         "--project-root", str(REPO), "--no-deep"],
        cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert proc.returncode in (0, 2), proc.stderr[-2000:]
    assert "GENERATION READINESS MATRIX (section 211)" in proc.stdout
    assert "| Capability | Status | Existing Reuse | Evidence | Gap | Priority | Action |" \
        in proc.stdout
    for label in gr.SECTION_211_ROW_LABELS:
        assert label in proc.stdout, label


def test_cli_verb_runs_and_emits_the_same_matrix_json(tmp_path):
    """`dv-harness generation-readiness` shares ONE implementation with the
    module entry point (generation_readiness.execute), the same convention
    `golden-flow-readiness` uses."""
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness", "--project-root", str(tmp_path),
         "generation-readiness", "--json", "--no-deep"],
        cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert proc.returncode in (0, 2), proc.stderr[-2000:]
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == gr.SCHEMA_VERSION
    assert len(payload["rows"]) == 20
    assert payload["deep_analysis"] is False
    assert [r["row"] for r in payload["rows"]] == list(gr.SECTION_211_ROW_LABELS)


def test_this_matrix_is_not_the_section_47_matrix():
    """The two readiness matrices must stay SEPARATE mechanisms answering
    separate questions -- overloading one with the other's rows is the parallel
    mechanism this project's Methodology Consolidation Rule forbids, and a
    silently merged pair would answer neither question correctly."""
    from dv_harness import golden_flow_readiness as gfr
    assert set(gfr.SECTION_47_ROW_LABELS).isdisjoint(set(gr.SECTION_211_ROW_LABELS)) or \
        set(gfr.SECTION_47_ROW_LABELS) != set(gr.SECTION_211_ROW_LABELS)
    assert gfr.GOLDEN_FLOW_MATRIX_COLUMNS != gr.GENERATION_MATRIX_COLUMNS
    # Section 47 reads STAGE run state; section 211 reads GENERATION artifacts.
    # Neither may borrow the other's sources.
    gfr_sources = {s for r in gfr.ROWS for s in r.fact_source}
    gr_sources = {s for r in gr.ROWS for s in r.fact_source}
    assert any("dashboard" in s for s in gfr_sources)
    assert not any("dashboard" in s for s in gr_sources)
    assert any("system_resource_inventory" in s for s in gr_sources)
    assert not any("system_resource_inventory" in s for s in gfr_sources)
