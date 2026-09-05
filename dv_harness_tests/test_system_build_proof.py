"""Real tests for `dv_harness/system_build_proof.py` -- spec section 206's
SYSTEM BUILD & PROOF agent: the static system MERGE COLLISION check and the
smoke-proof ladder driver.

Discipline, matching `test_uvm_structural_lint.py`'s:

  * The merge check is proven by MUTATING one clean synthetic multi-subsystem
    fixture ONE defect at a time, so each assertion proves the check caught
    THAT injected defect rather than "some finding appeared".
  * It is also run over the REAL environments this project's own generator
    produced (`examples/generated_pcie_uvm_env`,
    `examples/generated_usb_real_evidence_v12`) -- a merge check that fires on
    genuine generator output would be unusable however many synthetic defects
    it catches, and the one thing it DOES find there (both generators emit
    `module tb_top`) is a real collision, asserted as such.
  * The ladder is driven end to end: through a REAL registered two-subsystem
    project whose REAL Track-B analysis really runs, a REAL
    `connectivity.run_gate1_elaboration_check()` subprocess against an
    injected fake tool, a REAL `fsdb_report.run_fsdbreport()` subprocess
    against a real fake `fsdbreport` binary on disk, and a REAL DuckDB
    `EvidenceStore` row -- to a real SYSTEM_READY, and to a real SMOKE_FAIL
    that halts the ladder.

Nothing here builds, submits, or dumps anything real: no VCS, no LSF, no
waveform is enabled, and the active-driver conflict case is asserted to STOP
rather than be arbitrated.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import connectivity as conn                      # noqa: E402
from dv_harness import env_manifest                              # noqa: E402
from dv_harness import system_build_proof as sbp                 # noqa: E402
from dv_harness import system_resource_inventory as sri          # noqa: E402
from dv_harness import uvm_structural_lint as usl                # noqa: E402
from dv_harness.uvm_structural_lint import SEVERITY_ERROR        # noqa: E402
from dv_harness.verible_parser import (                          # noqa: E402
    DEFAULT_VERIBLE_BIN,
    VeribleUnavailableError,
)

SHARED_CPU_BIND = "chip.soc.cpu_axi_m"

COMMANDS = """\
initial
begin
  `GMODEL.GLOBAL_INIT;
  `CPUWRITE4B(32'h1400_0000, 32'h1);
  $finish;
end
"""


def _verible_available() -> bool:
    try:
        from dv_harness import verible_parser
        return bool(verible_parser.get_verible_version(DEFAULT_VERIBLE_BIN))
    except Exception:
        return False


requires_verible = pytest.mark.skipif(
    not _verible_available(),
    reason="verible-verilog-syntax is not installed in this environment")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ===========================================================================
# The synthetic multi-subsystem fixture
# ===========================================================================

def _uvm_sources(env: Path, proto: str, *,
                 vif_type: str,
                 vif_field: str,
                 pkg_name: str = None) -> None:
    """Three real, verible-parseable UVM files for one subsystem: its package,
    its env class, and a test that publishes its virtual interface into the
    GLOBAL config space -- the exact shape a cross-subsystem config_db /
    virtual-interface conflict takes."""
    pkg = pkg_name or f"{proto}_env_pkg"
    _write(env / "env" / f"{proto}_env_pkg.sv",
           f"package {pkg};\n"
           "  import uvm_pkg::*;\n"
           "  `include \"uvm_macros.svh\"\n"
           f"  `include \"{proto}_env.sv\"\n"
           "endpackage\n")
    _write(env / "env" / f"{proto}_env.sv",
           f"class {proto}_env extends uvm_env;\n"
           f"  `uvm_component_utils({proto}_env)\n"
           f"  function new(string name, uvm_component parent);\n"
           "    super.new(name, parent);\n"
           "  endfunction\n"
           "endclass\n")
    _write(env / "tests" / f"{proto}_base_test.sv",
           f"class {proto}_base_test extends uvm_test;\n"
           f"  `uvm_component_utils({proto}_base_test)\n"
           f"  virtual {vif_type} vif;\n"
           f"  function new(string name, uvm_component parent);\n"
           "    super.new(name, parent);\n"
           "  endfunction\n"
           "  function void build_phase(uvm_phase phase);\n"
           "    super.build_phase(phase);\n"
           f"    uvm_config_db#(virtual {vif_type})::set(null, \"*\", "
           f"\"{vif_field}\", vif);\n"
           "  endfunction\n"
           "endclass\n")


def _matrix_row(active_passive: str) -> dict:
    return {
        "dut_instance": SHARED_CPU_BIND, "interface": "axi_m", "direction": "input",
        "role": conn.determine_role_from_port_direction("output"),
        "vip_type": "svt_axi_master_agent", "count": 1,
        "active_passive": active_passive, "bind_target": SHARED_CPU_BIND,
        "tier": conn.BindTier.T1_ALREADY_DECIDED.value, "protocol": "AXI4",
        "fabric_side_role": conn.FABRIC_SIDE_MASTER_INTERFACE,
    }


def _subsystem_env(tmp_path: Path, name: str, proto: str, *, active: bool,
                   vif_type: str, vif_field: str, pkg_name: str = None) -> Path:
    """A synthetic subsystem environment complete enough for SYS-1 to classify
    EXISTS_READY and SYS-9 to inventory -- the same artifact set
    `test_system_level_track_b_gate_crosscheck.py`'s fixture builds -- PLUS
    real, parseable UVM sources, which the merge check needs."""
    env = tmp_path / "generated" / name.lower()
    (env / ".dv-harness").mkdir(parents=True, exist_ok=True)
    _write(env / "command.txt", COMMANDS)
    for rel in ("rtl/dut_core.sv", "Makefile", "filelist.f", "seq/synth_seq.sv",
                "cfg/synth_config.sv", "cfg/clock_reset_map.json", "logs/sim.log",
                "regression.list", "docs/readme.md"):
        _write(env / rel, "// synthetic fixture, empty on purpose\n")
    _uvm_sources(env, proto, vif_type=vif_type, vif_field=vif_field, pkg_name=pkg_name)
    # subsystem_discovery's `scoreboard`/`vip`/`tb` readiness probes
    _write(env / "env" / f"{proto}_scoreboard.sv",
           f"class {proto}_scoreboard extends uvm_scoreboard;\n"
           f"  `uvm_component_utils({proto}_scoreboard)\n"
           "endclass\n")
    _write(env / "vip" / f"svt_{proto}_vip.sv", "// VIP placeholder\n")
    _write(env / "tb" / f"{proto}_tb_top.sv",
           f"module {proto}_tb_top;\n  initial run_test();\nendmodule\n")

    vip_dump = _write(env / "vip_dump.json", json.dumps({
        "schema_version": "1.0",
        "vip_instances": [{"instance_path": SHARED_CPU_BIND,
                           "vip_type": "svt_axi_master_agent",
                           "config_fields": {"data_width": "64"}}]}))
    soc_map = _write(env / "soc_arch_map.json", json.dumps({
        "schema_version": "1.0",
        "address_map": [{"name": "CTRL_BLOCK", "base_address": "0x14000000",
                         "size_bytes": 4096, "bus": "AXI4"}],
        "clocks": [{"name": "core_clk", "frequency_mhz": 100}],
        "resets": [{"name": "core_rst_n", "active_level": "low",
                    "clock": "core_clk"}]}))
    env_manifest.generate_and_write(
        env / ".dv-harness" / "env.manifest.json",
        vip_config_dump_path=vip_dump, soc_arch_map_path=soc_map)
    _write(env / ".dv-harness" / "connectivity_matrix.json", json.dumps({
        "columns": conn.MATRIX_COLUMNS,
        "rows": [_matrix_row("active" if active else "passive")]}))
    return env


def _registry_entry(name: str, env: Path, sha: str) -> dict:
    return {"name": name,
            "environment_manifest": str(env / ".dv-harness" / "env.manifest.json"),
            "release_sha": sha, "qualification_state": "REGRESSION_QUALIFIED",
            "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}


def _project(tmp_path: Path, *, b_active: bool = False,
             b_vif_type: str = "usb_if", b_vif_field: str = "usb_vif",
             b_pkg_name: str = None) -> dict:
    """Two REGISTERED, discoverable subsystems with real UVM sources.

    Defaults produce a CLEAN composition: distinct package/class names,
    distinct global config_db keys, and the second subsystem's AXI agent
    PASSIVE so there is no active-driver ownership conflict. Every mutation
    test below flips exactly one of those."""
    from dv_harness import subsystem_discovery as sd

    a = _subsystem_env(tmp_path, "SUBSYS_A", "pcie", active=True,
                       vif_type="pcie_if", vif_field="pcie_vif")
    b = _subsystem_env(tmp_path, "SUBSYS_B", "usb", active=b_active,
                       vif_type=b_vif_type, vif_field=b_vif_field,
                       pkg_name=b_pkg_name)
    entries = [_registry_entry("SUBSYS_A", a, "aaa111"),
               _registry_entry("SUBSYS_B", b, "bbb222")]
    _write(tmp_path / ".dv-harness" / "soc-composer" /
           "subsystem_environment_registry.json", json.dumps({"subsystems": entries}))
    _write(sd.candidate_sources_path(tmp_path), json.dumps({"candidates": [
        {"name": "SUBSYS_A", "protocol": "PCIE", "environment_path": str(a)},
        {"name": "SUBSYS_B", "protocol": "USB", "environment_path": str(b)}]}))
    return {"root": tmp_path, "SUBSYS_A": a, "SUBSYS_B": b, "entries": entries}


def _sources(project: dict) -> dict:
    return sbp.subsystem_source_sets(project["root"])


# ===========================================================================
# subsystem_source_sets: the real registry is what is read
# ===========================================================================

def test_subsystem_source_sets_reads_the_real_registry(tmp_path):
    project = _project(tmp_path)
    sources = _sources(project)
    assert sorted(sources) == ["SUBSYS_A", "SUBSYS_B"]
    names = {s: sorted(p.name for p in files) for s, files in sources.items()}
    assert "pcie_env.sv" in names["SUBSYS_A"]
    assert "usb_env.sv" in names["SUBSYS_B"]


def test_an_unregistered_subsystem_is_not_composed(tmp_path):
    """The registry -- harness evidence -- is the only source of subsystems, so
    a caller naming a subsystem nobody registered gets nothing for it."""
    project = _project(tmp_path)
    sources = sbp.subsystem_source_sets(project["root"], ["SUBSYS_A", "SUBSYS_NOPE"])
    assert sorted(sources) == ["SUBSYS_A"]


# ===========================================================================
# The merge check: clean fixture, then ONE injected defect at a time
# ===========================================================================

@requires_verible
def test_a_clean_two_subsystem_merge_reports_no_findings(tmp_path):
    project = _project(tmp_path)
    report = sbp.analyze_system_merge(_sources(project))
    assert report.status == sbp.STATUS_PASS, sbp.format_merge_report(report)
    assert report.error_count == 0
    assert report.declarations_analyzed > 0
    # both subsystems really did publish a global virtual interface -- the
    # clean case is "they used different keys", not "there was nothing to check"
    assert report.config_db_sets_analyzed == 2


@requires_verible
def test_duplicate_package_across_two_subsystems_is_an_error(tmp_path):
    """ONE mutation from the clean fixture: the second subsystem's package is
    renamed to the first's."""
    project = _project(tmp_path, b_pkg_name="pcie_env_pkg")
    report = sbp.analyze_system_merge(_sources(project))
    assert report.status == sbp.STATUS_FAIL
    dupes = [f for f in report.findings if f.rule == sbp.RULE_DUPLICATE_PACKAGE]
    assert len(dupes) == 1, sbp.format_merge_report(report)
    assert dupes[0].subject == "pcie_env_pkg"
    assert dupes[0].subsystems == ["SUBSYS_A", "SUBSYS_B"]
    assert dupes[0].severity == SEVERITY_ERROR


@requires_verible
def test_duplicate_class_across_two_subsystems_is_an_error(tmp_path):
    project = _project(tmp_path)
    # ONE mutation: give SUBSYS_B a class SUBSYS_A already defines.
    _write(project["SUBSYS_B"] / "env" / "clash.sv",
           "class pcie_env extends uvm_env;\n"
           "  `uvm_component_utils(pcie_env)\n"
           "endclass\n")
    report = sbp.analyze_system_merge(_sources(project))
    assert report.status == sbp.STATUS_FAIL
    dupes = [f for f in report.findings
             if f.rule == sbp.RULE_DUPLICATE_TYPE and f.subject == "pcie_env"]
    assert len(dupes) == 1, sbp.format_merge_report(report)
    assert dupes[0].subsystems == ["SUBSYS_A", "SUBSYS_B"]
    # the factory-collision rule must NOT also fire for the same name: it is
    # the same defect seen from the other side and would inflate the count.
    assert not [f for f in report.findings if f.rule == sbp.RULE_FACTORY_COLLISION]


@requires_verible
def test_factory_type_name_collision_between_differently_named_classes(tmp_path):
    """Two DIFFERENTLY-named classes registering the SAME factory string. The
    UVM factory keys on that string, so this collides even though no duplicate
    definition exists -- a defect the duplicate-name rule cannot see."""
    project = _project(tmp_path)
    _write(project["SUBSYS_A"] / "env" / "a_shared.sv",
           "class a_shared_agent extends uvm_agent;\n"
           "  `uvm_component_utils(shared_axi_agent)\n"
           "endclass\n")
    _write(project["SUBSYS_B"] / "env" / "b_shared.sv",
           "class b_shared_agent extends uvm_agent;\n"
           "  `uvm_component_utils(shared_axi_agent)\n"
           "endclass\n")
    report = sbp.analyze_system_merge(_sources(project))
    assert report.status == sbp.STATUS_FAIL
    hits = [f for f in report.findings if f.rule == sbp.RULE_FACTORY_COLLISION]
    assert len(hits) == 1, sbp.format_merge_report(report)
    assert hits[0].subject == "shared_axi_agent"
    assert hits[0].subsystems == ["SUBSYS_A", "SUBSYS_B"]


@requires_verible
def test_a_real_injected_duplicate_config_db_path_is_caught(tmp_path):
    """THE headline case: both subsystems `set` the SAME field name at the SAME
    global scope with DIFFERENT virtual interface types. Whichever runs last
    hands the other subsystem the wrong interface handle."""
    project = _project(tmp_path, b_vif_field="pcie_vif")
    report = sbp.analyze_system_merge(_sources(project))
    assert report.status == sbp.STATUS_FAIL, sbp.format_merge_report(report)
    hits = [f for f in report.findings
            if f.rule == sbp.RULE_VIRTUAL_INTERFACE_CONFLICT]
    assert len(hits) == 1, sbp.format_merge_report(report)
    assert hits[0].subject == "*::pcie_vif"
    assert hits[0].subsystems == ["SUBSYS_A", "SUBSYS_B"]
    assert "virtual pcie_if" in hits[0].message
    assert "virtual usb_if" in hits[0].message


@requires_verible
def test_a_wildcard_scope_overlapping_a_literal_one_is_caught(tmp_path):
    """The scope patterns need not be identical: UVM's config_db matcher is
    glob-shaped, so `*` really does cover `uvm_test_top.env`."""
    project = _project(tmp_path)
    _write(project["SUBSYS_B"] / "tests" / "usb_scoped_test.sv",
           "class usb_scoped_test extends uvm_test;\n"
           "  `uvm_component_utils(usb_scoped_test)\n"
           "  virtual usb_if vif;\n"
           "  function void build_phase(uvm_phase phase);\n"
           "    uvm_config_db#(virtual usb_if)::set(null, \"uvm_test_top.env\", "
           "\"pcie_vif\", vif);\n"
           "  endfunction\n"
           "endclass\n")
    report = sbp.analyze_system_merge(_sources(project))
    hits = [f for f in report.findings
            if f.rule == sbp.RULE_VIRTUAL_INTERFACE_CONFLICT]
    assert len(hits) == 1, sbp.format_merge_report(report)
    assert hits[0].subject == "uvm_test_top.env::pcie_vif"


@requires_verible
def test_a_component_relative_config_db_set_is_never_reported(tmp_path):
    """`set(this, "", "cfg", cfg)` resolves to wherever that component ends up.
    A parse cannot prove two of those collide, and ERROR is reserved for what
    the sources DO prove -- so this must produce no collision finding, even
    though both subsystems use the same field name."""
    project = _project(tmp_path)
    for subsystem, proto in (("SUBSYS_A", "pcie"), ("SUBSYS_B", "usb")):
        _write(project[subsystem] / "env" / f"{proto}_cfg_setter.sv",
               f"class {proto}_cfg_setter extends uvm_component;\n"
               f"  `uvm_component_utils({proto}_cfg_setter)\n"
               "  function void build_phase(uvm_phase phase);\n"
               f"    uvm_config_db#({proto}_config)::set(this, \"*\", \"cfg\", null);\n"
               "  endfunction\n"
               "endclass\n")
    report = sbp.analyze_system_merge(_sources(project))
    assert not [f for f in report.findings
                if f.rule in (sbp.RULE_CONFIG_DB_SCOPE_COLLISION,
                              sbp.RULE_VIRTUAL_INTERFACE_CONFLICT)], \
        sbp.format_merge_report(report)


@requires_verible
def test_two_sets_inside_ONE_subsystem_are_not_a_merge_collision(tmp_path):
    """That environment already worked as a standalone subsystem; this check is
    about what the MERGE breaks, and reporting its internal scoping would be
    noise a system integrator cannot act on."""
    project = _project(tmp_path)
    _write(project["SUBSYS_A"] / "tests" / "pcie_second_test.sv",
           "class pcie_second_test extends uvm_test;\n"
           "  `uvm_component_utils(pcie_second_test)\n"
           "  virtual pcie_if vif;\n"
           "  function void build_phase(uvm_phase phase);\n"
           "    uvm_config_db#(virtual pcie_if)::set(null, \"*\", \"pcie_vif\", vif);\n"
           "  endfunction\n"
           "endclass\n")
    report = sbp.analyze_system_merge(_sources(project))
    assert report.status == sbp.STATUS_PASS, sbp.format_merge_report(report)


@requires_verible
def test_a_runtime_built_config_db_scope_is_disclosed_not_dropped(tmp_path):
    project = _project(tmp_path)
    _write(project["SUBSYS_A"] / "tests" / "pcie_dynamic_test.sv",
           "class pcie_dynamic_test extends uvm_test;\n"
           "  `uvm_component_utils(pcie_dynamic_test)\n"
           "  virtual pcie_if vif;\n"
           "  function void build_phase(uvm_phase phase);\n"
           "    uvm_config_db#(virtual pcie_if)::set(null, $sformatf(\"lane%0d\", i), "
           "\"pcie_vif\", vif);\n"
           "  endfunction\n"
           "endclass\n")
    report = sbp.analyze_system_merge(_sources(project))
    infos = [f for f in report.findings
             if f.rule == sbp.RULE_CONFIG_DB_SCOPE_NOT_RESOLVABLE]
    assert len(infos) == 1, sbp.format_merge_report(report)
    # disclosed, and it did not turn into an ERROR
    assert report.status == sbp.STATUS_PASS


def test_nothing_to_merge_is_NOT_AVAILABLE_never_PASS(tmp_path):
    """This repo's own subsystem registry is legitimately EMPTY. Without this
    guard the headline verb would report a clean merge of nothing -- the same
    trap `uvm_structural_lint.lint_uvm_environment()` closes for an empty
    environment directory."""
    empty = sbp.analyze_system_merge({})
    assert empty.status == sbp.STATUS_NOT_AVAILABLE
    assert "FEWER_THAN_TWO_SOURCE_SETS_TO_MERGE" in empty.reason

    one = sbp.analyze_system_merge({"only": []})
    assert one.status == sbp.STATUS_NOT_AVAILABLE

    none_on_disk = sbp.analyze_system_merge({"a": [], "b": []})
    assert none_on_disk.status == sbp.STATUS_NOT_AVAILABLE
    assert "NO_SOURCES_ON_DISK" in none_on_disk.reason


def test_a_project_with_no_registered_subsystems_never_reports_SYSTEM_READY(tmp_path):
    """The end-to-end version of the guard above, through the real verb."""
    (tmp_path / ".dv-harness").mkdir(parents=True, exist_ok=True)
    text, code = sbp.execute_verb(tmp_path, merge_only=True)
    assert code == 2, text
    assert "NOT_AVAILABLE" in text


@requires_verible
def test_verible_unavailable_is_NOT_AVAILABLE_never_PASS(tmp_path):
    project = _project(tmp_path)
    report = sbp.analyze_system_merge(_sources(project),
                                      verible_bin="definitely-not-a-real-binary")
    assert report.status == sbp.STATUS_NOT_AVAILABLE
    assert report.error_count == 0
    assert "could not be run" in (report.reason or "")


# ===========================================================================
# The merge check over environments this project's generator really produced
# ===========================================================================

@requires_verible
def test_real_generated_environments_collide_only_on_their_own_tb_tops():
    """Composing the two REAL generated environments finds exactly one real
    collision: both generators emit `module tb_top`. That is a genuine
    system-merge defect (and exactly why Track A's composer emits
    `soc_tb_top.sv` instead), not a false positive."""
    pcie = usl.discover_uvm_sources(ROOT / "examples" / "generated_pcie_uvm_env")
    usb = usl.discover_uvm_sources(
        ROOT / "examples" / "generated_usb_real_evidence_v12")
    assert pcie and usb
    report = sbp.analyze_system_merge({"pcie": pcie, "usb": usb})
    errors = [f for f in report.findings if f.severity == SEVERITY_ERROR]
    assert [f.subject for f in errors] == ["tb_top"], sbp.format_merge_report(report)
    assert errors[0].rule == sbp.RULE_DUPLICATE_TYPE
    assert errors[0].subsystems == ["pcie", "usb"]


@requires_verible
def test_real_generated_environments_merge_clean_without_their_tb_tops():
    """The composition Track A actually performs -- each subsystem's env/tests
    plus ONE composed system top -- is clean. A check that fired here would be
    unusable on real generator output."""
    def env(directory):
        return [p for p in usl.discover_uvm_sources(directory) if p.name != "tb_top.sv"]

    report = sbp.analyze_system_merge({
        "pcie": env(ROOT / "examples" / "generated_pcie_uvm_env"),
        "usb": env(ROOT / "examples" / "generated_usb_real_evidence_v12")})
    assert report.status == sbp.STATUS_PASS, sbp.format_merge_report(report)


# ===========================================================================
# The ladder
# ===========================================================================

def test_the_ladder_is_section_206s_own_ladder_in_its_own_order():
    assert sbp.SMOKE_PROOF_LADDER == (
        "BUILD", "ELABORATE", "BOOT_RESET_INIT", "SHARED_RESOURCE_ACCESS",
        "ONE_SUBSYSTEM", "TWO_SUBSYSTEM_INTERACTION", "END_TO_END_SCENARIO",
        "WAVE_FSDBREPORT", "SCOREBOARD_ASSERTION")


@requires_verible
def test_a_clean_composition_with_no_tooling_is_NOT_PROVEN_never_READY(tmp_path):
    """GF-AT-28: UNKNOWN never becomes PASS/READY automatically. The BUILD and
    SHARED_RESOURCE_ACCESS rungs really run and really pass here; every rung
    that needs a tool this environment does not have reports NOT_AVAILABLE, and
    the aggregate is NOT_PROVEN, not SYSTEM_READY."""
    project = _project(tmp_path)
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"])
    assert report.verdict == sbp.SMOKE_NOT_PROVEN, sbp.format_smoke_proof_report(report)
    assert not report.triage_required
    assert report.rung("BUILD").status == conn.GateStatus.PASS.value
    assert report.rung("SHARED_RESOURCE_ACCESS").status == conn.GateStatus.PASS.value
    assert report.rung("ELABORATE").status == conn.GateStatus.NOT_AVAILABLE.value
    assert "SYS-40" in report.rung("ELABORATE").reason
    assert (report.rung("END_TO_END_SCENARIO").detail.get("boundary")
            == "SYS-40_REQUIRES_HUMAN_APPROVAL")


@requires_verible
def test_a_merge_collision_fails_the_ladder_and_halts_it(tmp_path):
    """Spec section 209's `SMOKE_FAIL -> TRIAGE` edge: the rungs after the
    failure are NOT_YET_RUN, which is a different fact from checked-and-clean."""
    project = _project(tmp_path, b_vif_field="pcie_vif")
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"])
    assert report.verdict == sbp.SMOKE_FAIL
    assert report.triage_required
    assert report.rung("BUILD").status == conn.GateStatus.FAIL.value
    for rung in sbp.SMOKE_PROOF_LADDER[1:]:
        result = report.rung(rung)
        assert result.status == conn.GateStatus.NOT_YET_RUN.value, rung
        assert result.detail["halted_at"] == "BUILD"


@requires_verible
def test_an_unresolved_active_driver_conflict_stops_the_ladder_and_is_not_arbitrated(tmp_path):
    """Both subsystems' AXI agents ACTIVE on the SAME SoC CPU port. The REAL
    Track-B analysis stops automatic integration; this rung carries that stop
    through and NOTHING picks a winner -- SYS-12's preferred model is carried
    as text for the human who must."""
    project = _project(tmp_path, b_active=True)
    # precondition: the real analysis really does find it
    findings = sri.real_cross_subsystem_findings(project["root"])
    assert findings["status"] == sri.CROSSCHECK_AVAILABLE
    assert findings["automatic_integration_allowed"] is False

    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"])
    assert report.verdict == sbp.SMOKE_FAIL
    rung = report.rung("SHARED_RESOURCE_ACCESS")
    assert rung.status == conn.GateStatus.FAIL.value
    assert rung.detail["human_arbitration_required"] is True
    assert "SYSTEM SHARED AGENT" in rung.detail["preferred_model"]
    # no winner was chosen anywhere in the report
    assert "owner_selected" not in json.dumps(report.to_dict())
    # and the ladder halted here, not earlier and not later
    assert report.rung("BUILD").status == conn.GateStatus.PASS.value
    assert report.rung("ONE_SUBSYSTEM").status == conn.GateStatus.NOT_YET_RUN.value


@requires_verible
def test_track_b_unavailable_is_NOT_AVAILABLE_never_a_silent_clear(tmp_path):
    """One registered subsystem: the real analysis has nothing to compare, and
    that must read as "not checked", never as "no conflict"."""
    project = _project(tmp_path)
    _write(project["root"] / ".dv-harness" / "soc-composer" /
           "subsystem_environment_registry.json",
           json.dumps({"subsystems": project["entries"][:1]}))
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"])
    rung = report.rung("SHARED_RESOURCE_ACCESS")
    assert rung.status == conn.GateStatus.NOT_AVAILABLE.value
    assert "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE" in rung.reason
    assert report.verdict == sbp.SMOKE_NOT_PROVEN


@requires_verible
def test_two_subsystem_interaction_is_not_proven_by_one_subsystems_traffic(tmp_path):
    project = _project(tmp_path)
    report = sbp.run_system_smoke_proof(
        sources=_sources(project), root=project["root"],
        monitor_transaction_counts={"SUBSYS_A": {"uvm_test_top.env.pcie_mon": 7}},
        pattern_completed=True)
    assert report.rung("ONE_SUBSYSTEM").status == conn.GateStatus.PASS.value
    two = report.rung("TWO_SUBSYSTEM_INTERACTION")
    assert two.status == conn.GateStatus.NOT_AVAILABLE.value
    assert "at least 2 subsystems" in two.reason


@requires_verible
def test_a_silent_monitor_fails_the_one_subsystem_rung(tmp_path):
    project = _project(tmp_path)
    report = sbp.run_system_smoke_proof(
        sources=_sources(project), root=project["root"],
        monitor_transaction_counts={"SUBSYS_A": {"uvm_test_top.env.pcie_mon": 0}},
        pattern_completed=True)
    rung = report.rung("ONE_SUBSYSTEM")
    assert rung.status == conn.GateStatus.FAIL.value
    assert "SUBSYS_A:uvm_test_top.env.pcie_mon" in rung.reason


@requires_verible
def test_no_completed_pattern_is_PENDING_not_FAIL(tmp_path):
    """`connectivity.evaluate_transaction_activity_status()`'s own distinction,
    carried through: nothing has failed when nothing has run yet."""
    project = _project(tmp_path)
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"],
                                        pattern_completed=False)
    assert report.rung("ONE_SUBSYSTEM").status == conn.GateStatus.PENDING.value
    assert report.verdict == sbp.SMOKE_NOT_PROVEN


# ---- a real elaboration subprocess against an injected fake tool -----------

@requires_verible
def test_elaborate_runs_the_real_connectivity_gate1(tmp_path):
    """The ladder does not re-implement elaboration: it calls the existing
    `connectivity.run_gate1_elaboration_check()`, whose real argv reaches the
    injected runner."""
    project = _project(tmp_path)
    seen = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _run(argv, **kwargs):
        seen["argv"] = argv
        return _Proc()

    filelist = _write(tmp_path / "soc_filelist.f", "// composed system filelist\n")
    report = sbp.run_system_smoke_proof(
        sources=_sources(project), root=project["root"],
        filelist_paths=[filelist], top_module="soc_tb_top",
        which_fn=lambda name: "/usr/bin/slang" if name == "slang" else None,
        run_fn=_run)
    rung = report.rung("ELABORATE")
    assert rung.status == conn.GateStatus.PASS.value
    assert rung.detail["connectivity_gate"] == "gate1_elaboration"
    assert seen["argv"][0] == "slang"
    assert "soc_tb_top" in seen["argv"]


@requires_verible
def test_a_real_elaboration_error_fails_and_halts_the_ladder(tmp_path):
    project = _project(tmp_path)

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "error: unknown module 'usb_env'"

    filelist = _write(tmp_path / "soc_filelist.f", "// composed system filelist\n")
    report = sbp.run_system_smoke_proof(
        sources=_sources(project), root=project["root"], filelist_paths=[filelist],
        which_fn=lambda name: "/usr/bin/slang" if name == "slang" else None,
        run_fn=lambda argv, **kw: _Proc())
    assert report.verdict == sbp.SMOKE_FAIL
    assert report.rung("ELABORATE").status == conn.GateStatus.FAIL.value
    assert (report.rung("SHARED_RESOURCE_ACCESS").status
            == conn.GateStatus.NOT_YET_RUN.value)


# ---- boot/reset/init over a real SignalTrace ------------------------------

def _good_trace() -> conn.SignalTrace:
    return conn.SignalTrace(samples={
        "clk": [(0, "0"), (5, "1"), (10, "0")],
        "rst_n": [(0, "0"), (100, "1")],
        "soc_tb_top.pcie_env_inst.enable": [(0, "1")],
    })


@requires_verible
def test_boot_reset_init_runs_the_real_zero_time_connectivity_check(tmp_path):
    project = _project(tmp_path)
    report = sbp.run_system_smoke_proof(
        sources=_sources(project), root=project["root"],
        signal_trace=_good_trace(),
        required_nonx_signals=["soc_tb_top.pcie_env_inst.enable"])
    rung = report.rung("BOOT_RESET_INIT")
    assert rung.status == conn.GateStatus.PASS.value
    assert rung.detail["connectivity_gate"] == "gate2_zero_time_connectivity"


@requires_verible
def test_a_reset_that_never_deasserts_fails_boot_reset_init(tmp_path):
    project = _project(tmp_path)
    trace = conn.SignalTrace(samples={"clk": [(0, "0"), (5, "1")],
                                      "rst_n": [(0, "0"), (100, "0")]})
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"], signal_trace=trace)
    rung = report.rung("BOOT_RESET_INIT")
    assert rung.status == conn.GateStatus.FAIL.value
    assert any("never transitions" in p for p in rung.detail["problems"])


# ---- WAVE=1/fsdbreport against a real fake binary --------------------------

FAKE_FSDBREPORT_PY = """\
import sys
argv = sys.argv[1:]
out = argv[argv.index("-o") + 1]
with open(out, "w", encoding="utf-8") as handle:
    handle.write("signal,time,value\\n")
    handle.write("soc_tb_top.clk,0,0\\n")
    handle.write("soc_tb_top.clk,5,1\\n")
"""


def _fake_fsdbreport(tmp_path: Path) -> str:
    script = _write(tmp_path / "fake_fsdbreport.py", FAKE_FSDBREPORT_PY)
    if os.name == "nt":
        launcher = tmp_path / "fsdbreport.bat"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
                            encoding="utf-8")
    else:
        launcher = tmp_path / "fsdbreport"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
                            encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)
    return str(launcher)


@requires_verible
def test_wave_rung_reads_a_real_fsdb_through_the_existing_fsdb_report_module(tmp_path):
    """The REAL `fsdb_report.run_fsdbreport()` subprocess plus the REAL
    `parse_fsdbreport_output()` CSV parse. Nothing here enables a dump."""
    project = _project(tmp_path)
    fsdb = _write(tmp_path / "system.fsdb", "not really an fsdb, the fake tool "
                                            "does not read it\n")
    report = sbp.run_system_smoke_proof(
        sources=_sources(project), root=project["root"],
        fsdb_path=str(fsdb), fsdbreport_bin=_fake_fsdbreport(tmp_path))
    rung = report.rung("WAVE_FSDBREPORT")
    assert rung.status == conn.GateStatus.PASS.value, rung
    assert rung.detail["record_count"] == 2
    assert rung.detail["fieldnames"] == ["signal", "time", "value"]


@requires_verible
def test_no_fsdb_is_NOT_AVAILABLE_and_names_the_waveform_gate(tmp_path):
    project = _project(tmp_path)
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"])
    rung = report.rung("WAVE_FSDBREPORT")
    assert rung.status == conn.GateStatus.NOT_AVAILABLE.value
    assert "Waveform Dump User Gate" in rung.reason


# ---- scoreboard/assertion evidence out of the real EvidenceStore -----------

def _evidence_db(tmp_path: Path, *, job_id: int, verdict: str,
                 uvm_error: int = 0, assertion_failure=None) -> Path:
    from dv_harness.evidence_db import EvidenceStore

    db = tmp_path / "evidence.duckdb"
    with EvidenceStore(db) as store:
        store.insert_normalized_evidence({
            "evidence_id": f"EV-{job_id}", "schema_version": "1.0",
            "source_kind": "sim_log", "job_id": job_id,
            "pattern": "soc_smoke", "protocol": "SOC", "run_dir": str(tmp_path),
            "verdict": verdict,
            "counts": {"uvm_fatal": 0, "uvm_error": uvm_error, "uvm_warning": 0},
            "detail": {"assertion_failure": assertion_failure},
            "provenance": {"parser": "test fixture"},
            "distilled_at": 0.0, "distiller": "test",
        })
    return db


@requires_verible
def test_scoreboard_rung_passes_on_a_real_clean_evidence_row(tmp_path):
    project = _project(tmp_path)
    db = _evidence_db(tmp_path, job_id=4242, verdict="PASSED")
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"],
                                        evidence_db_path=db, system_job_id=4242)
    rung = report.rung("SCOREBOARD_ASSERTION")
    assert rung.status == conn.GateStatus.PASS.value, rung
    assert rung.detail["row_count"] == 1


@requires_verible
def test_scoreboard_rung_fails_on_a_real_uvm_error_row(tmp_path):
    project = _project(tmp_path)
    db = _evidence_db(tmp_path, job_id=99, verdict="FAILED", uvm_error=3)
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"],
                                        evidence_db_path=db, system_job_id=99)
    rung = report.rung("SCOREBOARD_ASSERTION")
    assert rung.status == conn.GateStatus.FAIL.value
    assert rung.detail["failing_rows"][0]["counts"] == {"uvm_error": 3}
    assert report.verdict == sbp.SMOKE_FAIL


@requires_verible
def test_scoreboard_rung_fails_on_a_real_assertion_failure_despite_a_pass_verdict(tmp_path):
    project = _project(tmp_path)
    db = _evidence_db(tmp_path, job_id=7, verdict="PASSED",
                      assertion_failure="soc_tb_top.axi_sva.a_no_overlap")
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"],
                                        evidence_db_path=db, system_job_id=7)
    rung = report.rung("SCOREBOARD_ASSERTION")
    assert rung.status == conn.GateStatus.FAIL.value
    assert (rung.detail["failing_rows"][0]["assertion_failure"]
            == "soc_tb_top.axi_sva.a_no_overlap")


@requires_verible
def test_no_evidence_for_the_job_is_NOT_AVAILABLE(tmp_path):
    project = _project(tmp_path)
    db = _evidence_db(tmp_path, job_id=1, verdict="PASSED")
    report = sbp.run_system_smoke_proof(sources=_sources(project),
                                        root=project["root"],
                                        evidence_db_path=db, system_job_id=555)
    rung = report.rung("SCOREBOARD_ASSERTION")
    assert rung.status == conn.GateStatus.NOT_AVAILABLE.value
    assert "no normalized evidence recorded" in rung.reason


# ---- the whole ladder, all the way to SYSTEM_READY -------------------------

@requires_verible
def test_the_full_ladder_reaches_SYSTEM_READY_only_when_every_rung_really_passes(tmp_path):
    """End to end over one project: a real clean merge, a real elaboration
    subprocess, a real zero-time connectivity check, the real Track-B analysis,
    real monitor counts in two subsystems, a real completed cross-subsystem
    scenario, a real fsdbreport subprocess, and a real EvidenceStore row."""
    project = _project(tmp_path)

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    filelist = _write(tmp_path / "soc_filelist.f", "// composed system filelist\n")
    fsdb = _write(tmp_path / "system.fsdb", "opaque\n")
    db = _evidence_db(tmp_path, job_id=8080, verdict="PASSED")

    report = sbp.run_system_smoke_proof(
        sources=_sources(project), root=project["root"],
        filelist_paths=[filelist], top_module="soc_tb_top",
        which_fn=lambda name: "/usr/bin/slang" if name == "slang" else None,
        run_fn=lambda argv, **kw: _Proc(),
        signal_trace=_good_trace(),
        required_nonx_signals=["soc_tb_top.pcie_env_inst.enable"],
        monitor_transaction_counts={"SUBSYS_A": {"env.pcie_mon": 12},
                                    "SUBSYS_B": {"env.usb_mon": 4}},
        pattern_completed=True,
        end_to_end_scenario={"scenario": "pcie_dma_during_usb_bulk",
                             "subsystems": ["SUBSYS_A", "SUBSYS_B"],
                             "verdict": "PASSED"},
        fsdb_path=str(fsdb), fsdbreport_bin=_fake_fsdbreport(tmp_path),
        evidence_db_path=db, system_job_id=8080)

    assert report.verdict == sbp.SYSTEM_READY, sbp.format_smoke_proof_report(report)
    assert all(r.status == conn.GateStatus.PASS.value for r in report.rungs), \
        sbp.format_smoke_proof_report(report)
    # SYSTEM_READY authorizes nothing: it is the precondition for large LSF
    # system regression, not permission to launch one.
    assert "authorizes" in report.to_dict()
    assert "SYS-39" in report.to_dict()["authorizes"]


@requires_verible
def test_removing_one_rungs_evidence_drops_the_verdict_out_of_SYSTEM_READY(tmp_path):
    """The aggregate is not decorative: withdrawing exactly one rung's real
    evidence from the passing run above stops it being SYSTEM_READY."""
    project = _project(tmp_path)

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    filelist = _write(tmp_path / "soc_filelist.f", "// f\n")
    fsdb = _write(tmp_path / "system.fsdb", "opaque\n")
    db = _evidence_db(tmp_path, job_id=8080, verdict="PASSED")
    kwargs = dict(
        sources=_sources(project), root=project["root"],
        filelist_paths=[filelist],
        which_fn=lambda name: "/usr/bin/slang" if name == "slang" else None,
        run_fn=lambda argv, **kw: _Proc(),
        signal_trace=_good_trace(),
        monitor_transaction_counts={"SUBSYS_A": {"env.pcie_mon": 12},
                                    "SUBSYS_B": {"env.usb_mon": 4}},
        pattern_completed=True,
        end_to_end_scenario={"scenario": "s", "subsystems": ["SUBSYS_A", "SUBSYS_B"],
                             "verdict": "PASSED"},
        fsdb_path=str(fsdb), fsdbreport_bin=_fake_fsdbreport(tmp_path),
        evidence_db_path=db, system_job_id=8080)
    assert sbp.run_system_smoke_proof(**kwargs).verdict == sbp.SYSTEM_READY

    kwargs.pop("end_to_end_scenario")
    dropped = sbp.run_system_smoke_proof(**kwargs)
    assert dropped.verdict == sbp.SMOKE_NOT_PROVEN
    assert (dropped.rung("END_TO_END_SCENARIO").status
            == conn.GateStatus.NOT_AVAILABLE.value)


@requires_verible
def test_a_single_subsystem_end_to_end_scenario_is_not_an_end_to_end_scenario(tmp_path):
    project = _project(tmp_path)
    report = sbp.run_system_smoke_proof(
        sources=_sources(project), root=project["root"],
        end_to_end_scenario={"scenario": "pcie_only", "subsystems": ["SUBSYS_A"],
                             "verdict": "PASSED"})
    rung = report.rung("END_TO_END_SCENARIO")
    assert rung.status == conn.GateStatus.NOT_AVAILABLE.value
    assert "at least two subsystems" in rung.reason


# ===========================================================================
# CLI / module entry point
# ===========================================================================

@requires_verible
def test_execute_verb_merge_only_exit_codes(tmp_path):
    clean = _project(tmp_path / "clean")
    text, code = sbp.execute_verb(clean["root"], merge_only=True)
    assert code == 0, text
    assert "System merge check: PASS" in text

    broken = _project(tmp_path / "broken", b_vif_field="pcie_vif")
    text, code = sbp.execute_verb(broken["root"], merge_only=True, as_json=True)
    assert code == 1
    payload = json.loads(text)
    assert payload["status"] == "FAIL"
    assert any(f["rule"] == sbp.RULE_VIRTUAL_INTERFACE_CONFLICT
               for f in payload["findings"])


@requires_verible
def test_execute_verb_never_exits_zero_short_of_proven(tmp_path):
    project = _project(tmp_path)
    text, code = sbp.execute_verb(project["root"])
    assert code == 2, text
    assert "SMOKE_NOT_PROVEN" in text


@requires_verible
def test_the_real_module_entry_point_runs_as_a_subprocess(tmp_path):
    project = _project(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_build_proof",
         "--root", str(project["root"]), "--merge-only", "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "PASS"
    assert sorted(payload["subsystems"]) == ["SUBSYS_A", "SUBSYS_B"]


# ===========================================================================
# Boundaries this module must not cross
# ===========================================================================

def _called_names() -> set:
    """Every name this module actually CALLS, from a real AST parse -- so a
    boundary assertion is about code, not about a docstring that happens to
    name the boundary it respects."""
    import ast

    tree = ast.parse((ROOT / "dv_harness" / "system_build_proof.py")
                     .read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
                names.add(ast.unparse(func))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
    return names


def test_this_module_generates_no_system_artifacts():
    """SYS-39/40's stop-before-generating-real-system-artifacts boundary. The
    module must not call the composer's generation entry points, must not write
    any file, and must not submit an LSF job."""
    called = _called_names()
    for forbidden in ("compose_soc_environment", "write_text", "open", "mkdir",
                      "lsf_client", "submit_job", "cross_subsystem_scenarios",
                      "end_to_end_scoreboard", "system_coverage"):
        assert forbidden not in called, forbidden


def test_this_module_never_arbitrates_a_driver_conflict():
    body = (ROOT / "dv_harness" / "system_build_proof.py").read_text(encoding="utf-8")
    assert "human_arbitration_required" in body
    called = _called_names()
    for forbidden in ("resolve_conflict", "choose_owner", "select_owner",
                      "set_owner", "arbitrate"):
        assert forbidden not in called, forbidden
    # and it never WRITES the field the real analysis computed
    assert "automatic_integration_allowed\"] =" not in body
    assert "automatic_integration_allowed'] =" not in body


def test_it_reuses_the_existing_gates_rather_than_reimplementing_them():
    """The whole point of this module is that each rung CALLS an existing real
    mechanism. If these call sites ever disappear, a rung has silently grown a
    parallel implementation."""
    body = (ROOT / "dv_harness" / "system_build_proof.py").read_text(encoding="utf-8")
    for call in ("conn.run_gate1_elaboration_check(",
                 "conn.evaluate_zero_time_connectivity(",
                 "conn.run_gate2_against_live_simv(",
                 "conn.evaluate_transaction_activity_status(",
                 "sri.real_cross_subsystem_findings(",
                 "fr.run_fsdbreport(",
                 "fr.parse_fsdbreport_output(",
                 "usl.parse_uvm_file(",
                 "usl.config_db_call_sites("):
        assert call in body, call
