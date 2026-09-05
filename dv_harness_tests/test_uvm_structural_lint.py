"""Tests for dv_harness/uvm_structural_lint.py -- the deterministic
pre-simulation structural lint of GENERATED UVM code (spec section 220).

Discipline, same as dv_harness_tests/test_verible_parser.py's: every test runs
the REAL `verible-verilog-syntax` subprocess and is SKIPPED, never mocked, on a
machine without it -- a missing real tool is a reported gap, never a reason to
fabricate what its output would have been.

Two kinds of evidence are asserted, because either alone would be weak:

  1. Against a REAL generated environment already in this repo
     (examples/generated_pcie_uvm_env/, examples/generated_usb_real_evidence_v12/,
     both produced by this project's own uvm_generator) the lint reports NO
     ERROR findings. A lint that fires on genuine generator output is useless
     no matter how many synthetic defects it catches.
  2. Against a synthetic-but-realistic clean UVM environment, EVERY rule is
     driven by MUTATING that same clean source one defect at a time -- so each
     assertion proves "the lint caught this specific injected defect", not
     merely "a function returned a list". The clean baseline is asserted to
     have zero findings first, so a mutation's finding cannot be a pre-existing
     one.

Plus the wiring: create_environment() -- the one real CREATE ENVIRONMENT entry
point -- runs this lint on what it just generated, writes the report next to
the environment, and (only on explicit opt-in) refuses.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from dv_harness import uvm_structural_lint as usl
from dv_harness.uvm_generator.create_environment import (
    STRUCTURAL_LINT_REPORT_NAME,
    StructuralLintFailedError,
    create_environment,
)

ROOT = Path(__file__).resolve().parents[1]
VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

# A structurally COMPLETE, clean UVM environment: a sequence_item (object
# family), a monitor with a real TLM analysis port, a scoreboard with the
# matching export, an env that builds and CONNECTS them, a config object, and a
# test that sets the config the env gets and raises/drops one objection in
# run_phase. Every rule this module implements has something correct to see
# here, which is what makes the mutations below meaningful.
CLEAN_ENV_SV = textwrap.dedent("""\
    class demo_item extends uvm_sequence_item;
      `uvm_object_utils(demo_item)
      function new(string name="demo_item"); super.new(name); endfunction
    endclass

    class demo_config extends uvm_object;
      `uvm_object_utils(demo_config)
      function new(string name="demo_config"); super.new(name); endfunction
    endclass

    class demo_monitor extends uvm_monitor;
      `uvm_component_utils(demo_monitor)
      uvm_analysis_port #(demo_item) item_collected_port;
      function new(string name="demo_monitor", uvm_component parent=null);
        super.new(name,parent);
      endfunction
      function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        item_collected_port = new("item_collected_port", this);
      endfunction
    endclass

    class demo_scoreboard extends uvm_scoreboard;
      `uvm_component_utils(demo_scoreboard)
      uvm_analysis_export #(demo_item) item_export;
      function new(string name="demo_scoreboard", uvm_component parent=null);
        super.new(name,parent);
      endfunction
    endclass

    class demo_env extends uvm_env;
      `uvm_component_utils(demo_env)
      demo_monitor mon;
      demo_scoreboard sb;
      demo_config cfg;
      function new(string name="demo_env", uvm_component parent=null);
        super.new(name,parent);
      endfunction
      function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        mon = demo_monitor::type_id::create("mon", this);
        sb  = demo_scoreboard::type_id::create("sb", this);
        void'(uvm_config_db#(demo_config)::get(this, "", "cfg", cfg));
      endfunction
      function void connect_phase(uvm_phase phase);
        super.connect_phase(phase);
        mon.item_collected_port.connect(sb.item_export);
      endfunction
    endclass

    class demo_base_test extends uvm_test;
      `uvm_component_utils(demo_base_test)
      demo_env env;
      function new(string name="demo_base_test", uvm_component parent=null);
        super.new(name,parent);
      endfunction
      function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        uvm_config_db#(demo_config)::set(this, "env", "cfg", demo_config::type_id::create("cfg"));
        env = demo_env::type_id::create("env", this);
      endfunction
      task run_phase(uvm_phase phase);
        phase.raise_objection(this);
        #100ns;
        phase.drop_objection(this);
      endtask
    endclass
    """)


def _env_dir(source: str) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "demo_env_pkg.sv").write_text(source, encoding="utf-8")
    return d


def _lint(source: str) -> usl.UvmLintReport:
    return usl.lint_uvm_environment(_env_dir(source))


def _mutate(old: str, new: str) -> usl.UvmLintReport:
    """Lint the clean environment with exactly ONE textual defect injected.
    Asserts the anchor really exists so a silently-stale mutation cannot pass
    by leaving the source clean."""
    assert old in CLEAN_ENV_SV, f"mutation anchor not found in fixture: {old!r}"
    return _lint(CLEAN_ENV_SV.replace(old, new, 1))


def _rules(report: usl.UvmLintReport, severity=None):
    return [f.rule for f in report.findings
            if severity is None or f.severity == severity]


# --- 1. the clean baseline ---------------------------------------------------


@requires_verible
def test_clean_environment_reports_pass_with_no_findings():
    """The baseline every mutation below is measured against. If this ever
    starts reporting a finding, the mutation tests stop proving anything."""
    report = _lint(CLEAN_ENV_SV)
    assert report.status == "PASS", usl.format_report(report)
    assert report.findings == [], usl.format_report(report)
    assert report.classes_analyzed == 6
    assert report.verible_version, "the real verible version must be recorded"


# --- 2. real generated environments ------------------------------------------


@requires_verible
@pytest.mark.parametrize("env_rel", [
    "examples/generated_pcie_uvm_env",
    "examples/generated_usb_real_evidence_v12",
])
def test_real_generated_environments_have_no_error_findings(env_rel):
    """Against environments this project's OWN generator really produced. A
    lint that fires on genuine generator output would be unusable, so this is
    as load-bearing as the mutation tests."""
    env_dir = ROOT / env_rel
    assert env_dir.is_dir(), f"missing real fixture environment: {env_dir}"
    report = usl.lint_uvm_environment(env_dir)
    assert report.status == "PASS", usl.format_report(report)
    assert report.error_count == 0, usl.format_report(report)
    assert report.classes_analyzed > 0


@requires_verible
def test_real_usb_environment_surfaces_its_runtime_built_config_db_key():
    """The real usb_env gets its virtual interface with a `$sformatf`-built
    key. That key genuinely cannot be matched statically, and the lint says so
    as an INFO finding instead of silently dropping it from the analysis or
    inventing a missing-set error for it."""
    report = usl.lint_uvm_environment(ROOT / "examples/generated_usb_real_evidence_v12")
    unresolved = [f for f in report.findings
                  if f.rule == "CONFIG_DB_KEY_NOT_STATICALLY_RESOLVABLE"]
    assert unresolved, usl.format_report(report)
    assert all(f.severity == "INFO" for f in unresolved)
    assert any("$sformatf" in f.message for f in unresolved)


# --- 3. factory registration -------------------------------------------------


@requires_verible
def test_missing_component_factory_registration_is_caught():
    report = _mutate("  `uvm_component_utils(demo_monitor)\n", "")
    assert report.status == "FAIL"
    hits = [f for f in report.findings if f.rule == "FACTORY_REGISTRATION_MISSING"]
    assert [f.subject for f in hits] == ["demo_monitor"]
    assert hits[0].severity == "ERROR"


@requires_verible
def test_missing_object_factory_registration_is_caught():
    report = _mutate("  `uvm_object_utils(demo_item)\n", "")
    hits = [f for f in report.findings if f.rule == "FACTORY_REGISTRATION_MISSING"]
    assert [f.subject for f in hits] == ["demo_item"]


@requires_verible
def test_object_macro_on_a_component_class_is_caught():
    """`uvm_object_utils on a uvm_monitor descendant compiles but registers the
    wrong factory family."""
    report = _mutate("`uvm_component_utils(demo_monitor)",
                     "`uvm_object_utils(demo_monitor)")
    assert "FACTORY_REGISTRATION_WRONG_KIND" in _rules(report, "ERROR")


@requires_verible
def test_factory_macro_naming_a_different_type_is_caught():
    """A copy-paste registration naming another class -- the factory key then
    silently does not match this class."""
    report = _mutate("`uvm_component_utils(demo_scoreboard)",
                     "`uvm_component_utils(demo_scoreboad)")
    hits = [f for f in report.findings if f.rule == "FACTORY_REGISTRATION_NAME_MISMATCH"]
    assert [f.subject for f in hits] == ["demo_scoreboard"]


@requires_verible
def test_class_with_an_out_of_scope_base_is_recorded_not_flagged():
    """A class extending a VIP base this analysis never saw cannot be proven to
    need a registration, so it is recorded as UNCLASSIFIED and NOT flagged."""
    report = _mutate("class demo_scoreboard extends uvm_scoreboard;\n"
                     "  `uvm_component_utils(demo_scoreboard)\n",
                     "class demo_scoreboard extends svt_vendor_scoreboard;\n")
    assert "FACTORY_REGISTRATION_MISSING" not in _rules(report)
    assert {"class": "demo_scoreboard", "base": "svt_vendor_scoreboard"}.items() <= \
        next(u for u in report.unclassified_bases
             if u["class"] == "demo_scoreboard").items()


# --- 4. phase-method signatures ----------------------------------------------


@requires_verible
def test_run_phase_declared_as_a_function_is_caught():
    report = _mutate(
        "  task run_phase(uvm_phase phase);\n"
        "    phase.raise_objection(this);\n"
        "    #100ns;\n"
        "    phase.drop_objection(this);\n"
        "  endtask",
        "  function void run_phase(uvm_phase phase);\n"
        "    phase.raise_objection(this);\n"
        "    phase.drop_objection(this);\n"
        "  endfunction")
    hits = [f for f in report.findings if f.rule == "PHASE_METHOD_WRONG_KIND"]
    assert [f.subject for f in hits] == ["demo_base_test.run_phase"]
    assert "must be declared as a task" in hits[0].message


@requires_verible
def test_connect_phase_declared_as_a_task_is_caught():
    report = _mutate(
        "  function void connect_phase(uvm_phase phase);\n"
        "    super.connect_phase(phase);\n"
        "    mon.item_collected_port.connect(sb.item_export);\n"
        "  endfunction",
        "  task connect_phase(uvm_phase phase);\n"
        "    super.connect_phase(phase);\n"
        "    mon.item_collected_port.connect(sb.item_export);\n"
        "  endtask")
    hits = [f for f in report.findings if f.rule == "PHASE_METHOD_WRONG_KIND"]
    assert [f.subject for f in hits] == ["demo_env.connect_phase"]


@requires_verible
def test_non_void_phase_function_return_type_is_caught():
    report = _mutate("function void build_phase(uvm_phase phase);\n"
                     "    super.build_phase(phase);\n"
                     "    item_collected_port",
                     "function bit build_phase(uvm_phase phase);\n"
                     "    super.build_phase(phase);\n"
                     "    item_collected_port")
    hits = [f for f in report.findings
            if f.rule == "PHASE_METHOD_RETURN_TYPE_NOT_VOID"]
    assert [f.subject for f in hits] == ["demo_monitor.build_phase"]


@requires_verible
def test_phase_method_with_a_wrong_argument_type_is_caught():
    report = _mutate("function void connect_phase(uvm_phase phase);",
                     "function void connect_phase(int phase);")
    hits = [f for f in report.findings if f.rule == "PHASE_METHOD_ARG_TYPE"]
    assert [f.subject for f in hits] == ["demo_env.connect_phase"]


@requires_verible
def test_phase_method_with_no_arguments_is_caught():
    report = _mutate("function void connect_phase(uvm_phase phase);",
                     "function void connect_phase();")
    hits = [f for f in report.findings if f.rule == "PHASE_METHOD_ARG_COUNT"]
    assert [f.subject for f in hits] == ["demo_env.connect_phase"]


# --- 5. config_db set/get matching -------------------------------------------


@requires_verible
def test_get_with_no_matching_set_anywhere_is_reported():
    report = _mutate(
        '    uvm_config_db#(demo_config)::set(this, "env", "cfg", '
        'demo_config::type_id::create("cfg"));\n', "")
    hits = [f for f in report.findings if f.rule == "CONFIG_DB_GET_WITHOUT_SET"]
    assert [f.subject for f in hits] == ["cfg"]
    # WARNING, not ERROR, and deliberately so: a `set` may live outside the
    # analysed set. See the module docstring's stated limits.
    assert hits[0].severity == "WARNING"
    assert report.status == "PASS"


@requires_verible
def test_set_with_no_matching_get_anywhere_is_reported():
    report = _mutate(
        '    void\'(uvm_config_db#(demo_config)::get(this, "", "cfg", cfg));\n', "")
    hits = [f for f in report.findings if f.rule == "CONFIG_DB_SET_WITHOUT_GET"]
    assert [f.subject for f in hits] == ["cfg"]
    assert hits[0].severity == "WARNING"


@requires_verible
def test_matched_set_and_get_produce_no_config_db_finding():
    """The clean fixture sets and gets the same "cfg" key; renaming BOTH sides
    together must stay clean, proving the match is on the real key rather than
    on the string "cfg" happening to be common."""
    renamed = (CLEAN_ENV_SV
               .replace('"cfg", cfg', '"env_cfg", cfg')
               .replace('"env", "cfg",', '"env", "env_cfg",'))
    report = _lint(renamed)
    assert [f for f in report.findings if f.rule.startswith("CONFIG_DB_")] == []


# --- 6. TLM port/export connection completeness ------------------------------


@requires_verible
def test_declared_analysis_port_never_connected_is_caught():
    report = _mutate("    mon.item_collected_port.connect(sb.item_export);\n", "")
    hits = [f for f in report.findings if f.rule == "TLM_PORT_NEVER_CONNECTED"]
    assert [f.subject for f in hits] == ["demo_monitor.item_collected_port"]
    assert hits[0].severity == "ERROR"
    assert report.status == "FAIL"
    # The far end is reported too, at the weaker severity its weaker evidence
    # deserves (an export may legitimately be connected from outside the set).
    exports = [f for f in report.findings if f.rule == "TLM_EXPORT_NEVER_CONNECTED"]
    assert [f.subject for f in exports] == ["demo_scoreboard.item_export"]
    assert exports[0].severity == "WARNING"


@requires_verible
def test_connecting_a_similarly_named_port_does_not_count_as_connected():
    """Guards the path-tail matching: `.connect()` on a DIFFERENT member whose
    name merely contains the declared one must not mark it connected."""
    report = _mutate("    mon.item_collected_port.connect(sb.item_export);",
                     "    mon.item_collected_port_alt.connect(sb.item_export);")
    assert "TLM_PORT_NEVER_CONNECTED" in _rules(report, "ERROR")


@requires_verible
def test_a_local_handle_inside_a_method_is_not_treated_as_a_member():
    """Method-local declarations must not be scanned as class members --
    otherwise a local TLM handle would be reported as an unconnected port."""
    report = _mutate("  function void build_phase(uvm_phase phase);\n"
                     "    super.build_phase(phase);\n"
                     "    mon = demo_monitor",
                     "  function void build_phase(uvm_phase phase);\n"
                     "    uvm_analysis_port #(demo_item) local_ap;\n"
                     "    super.build_phase(phase);\n"
                     "    mon = demo_monitor")
    assert report.findings == [], usl.format_report(report)


# --- 7. objection balance ----------------------------------------------------


@requires_verible
def test_unbalanced_objection_in_run_phase_is_caught():
    report = _mutate("    phase.drop_objection(this);\n", "")
    hits = [f for f in report.findings if f.rule == "OBJECTION_RAISE_DROP_IMBALANCE"]
    assert [f.subject for f in hits] == ["demo_base_test.run_phase"]
    assert hits[0].severity == "ERROR"
    assert report.status == "FAIL"


@requires_verible
def test_test_run_phase_with_no_objection_at_all_is_warned():
    report = _mutate("    phase.raise_objection(this);\n    #100ns;\n"
                     "    phase.drop_objection(this);\n", "    #100ns;\n")
    hits = [f for f in report.findings
            if f.rule == "OBJECTION_NEVER_RAISED_IN_TEST_RUN_PHASE"]
    assert [f.subject for f in hits] == ["demo_base_test.run_phase"]
    assert hits[0].severity == "WARNING"
    assert report.status == "PASS"


@requires_verible
def test_objection_pair_split_across_two_phase_methods_is_only_a_warning():
    """raise in pre_main_phase / drop in post_main_phase is legal UVM. Per
    method it looks unbalanced; per class it balances, so it must not be an
    ERROR."""
    report = _mutate(
        "  task run_phase(uvm_phase phase);\n"
        "    phase.raise_objection(this);\n"
        "    #100ns;\n"
        "    phase.drop_objection(this);\n"
        "  endtask",
        "  task pre_main_phase(uvm_phase phase);\n"
        "    phase.raise_objection(this);\n"
        "  endtask\n"
        "  task post_main_phase(uvm_phase phase);\n"
        "    phase.drop_objection(this);\n"
        "  endtask")
    rules = _rules(report)
    assert "OBJECTION_RAISE_DROP_IMBALANCE" not in rules
    assert rules.count("OBJECTION_RAISE_DROP_SPLIT_ACROSS_METHODS") == 2
    assert report.error_count == 0


# --- 8. honest degradation ---------------------------------------------------


def test_missing_verible_reports_not_available_never_pass():
    """A lint that could not parse must never report a clean environment."""
    report = usl.lint_uvm_environment(
        _env_dir(CLEAN_ENV_SV), verible_bin="verible-verilog-syntax-does-not-exist")
    assert report.status == "NOT_AVAILABLE"
    assert "could not be run" in (report.reason or "")
    assert report.findings == []


def test_empty_directory_reports_not_available_never_pass():
    report = usl.lint_uvm_environment(Path(tempfile.mkdtemp()))
    assert report.status == "NOT_AVAILABLE"
    assert "no .sv/.svh" in (report.reason or "")


@requires_verible
def test_malformed_sv_compilation_unit_is_an_error():
    report = _lint("class broken extends uvm_env;\n  function void build_phase(;\n")
    assert report.status == "FAIL"
    assert "SOURCE_PARSE_ERROR" in _rules(report, "ERROR")


@requires_verible
def test_non_standalone_include_fragment_is_a_warning_not_an_error():
    """The real bind_mechanism_generator.py emits dv_uvm_hook.svh as
    top-module-scope text that is not a standalone compilation unit. Reporting
    that as a defect would be wrong; hiding it would overstate what a PASS
    covers."""
    d = _env_dir(CLEAN_ENV_SV)
    (d / "dv_uvm_hook.svh").write_text("`define CPUWRITE1B dv_uvm_cpuwrite1b\n"
                                        "initial run_test();\n", encoding="utf-8")
    report = usl.lint_uvm_environment(d)
    hits = [f for f in report.findings if f.rule == "SOURCE_NOT_STANDALONE_PARSEABLE"]
    assert [f.subject for f in hits] == ["dv_uvm_hook.svh"]
    assert hits[0].severity == "WARNING"
    assert report.status == "PASS"


# --- 9. wiring into the real CREATE ENVIRONMENT entry point ------------------


@requires_verible
def test_create_environment_lints_what_it_generated_and_records_the_report():
    """The whole point of section 220: the real generation entry point runs
    this check on its OWN output, before anything expensive happens to it."""
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "out"
    result = create_environment(tmp, {
        "protocol": "PCIe",
        "clocks": [{"name": "refclk"}],
        "resets": [{"name": "perst_n"}],
        "smoke_tests": [{"name": "link_training"}],
    }, out_dir=out)
    lint = result["structural_lint"]
    assert lint["status"] == "PASS", json.dumps(lint, indent=2)
    assert lint["error_count"] == 0
    assert lint["classes_analyzed"] > 0
    on_disk = json.loads((out / STRUCTURAL_LINT_REPORT_NAME).read_text(encoding="utf-8"))
    assert on_disk == lint
    # The report must cite the real files it actually read, by real hash.
    assert on_disk["files"], on_disk
    assert all(len(f["source_sha256"]) == 64 for f in on_disk["files"])


@requires_verible
def test_strict_structural_lint_refuses_a_defective_environment():
    """Opt-in only, and it must really refuse. Driven through the same
    _run_structural_lint() the entry point calls, against a real defective
    environment on disk."""
    from dv_harness.uvm_generator import create_environment as ce
    d = _env_dir(CLEAN_ENV_SV.replace("  `uvm_component_utils(demo_monitor)\n", "", 1))
    # Default (no opt-in): records the failure, does not raise.
    payload = ce._run_structural_lint(d, {})
    assert payload["status"] == "FAIL"
    assert (d / STRUCTURAL_LINT_REPORT_NAME).is_file()
    with pytest.raises(StructuralLintFailedError) as exc:
        ce._run_structural_lint(d, {"strict_structural_lint": True})
    assert exc.value.reason == "UVM_STRUCTURAL_LINT_FAILED"
    assert exc.value.detail["report"]["error_count"] >= 1


# --- 10. the CLI verb --------------------------------------------------------


@requires_verible
def test_cli_verb_reports_and_exits_zero_on_a_clean_environment():
    d = _env_dir(CLEAN_ENV_SV)
    proc = subprocess.run([sys.executable, "-m", "dv_harness", "uvm-lint",
                           "--env-dir", str(d), "--fail-on-error"],
                          capture_output=True, text=True, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "UVM structural lint: PASS" in proc.stdout


@requires_verible
def test_cli_verb_exits_nonzero_on_error_findings_only_with_the_flag():
    d = _env_dir(CLEAN_ENV_SV.replace("  `uvm_component_utils(demo_monitor)\n", "", 1))
    argv = [sys.executable, "-m", "dv_harness", "uvm-lint", "--env-dir", str(d)]
    lenient = subprocess.run(argv, capture_output=True, text=True, cwd=str(ROOT))
    assert lenient.returncode == 0, lenient.stdout + lenient.stderr
    assert "FACTORY_REGISTRATION_MISSING" in lenient.stdout
    strict = subprocess.run(argv + ["--fail-on-error"], capture_output=True,
                            text=True, cwd=str(ROOT))
    assert strict.returncode == 1, strict.stdout + strict.stderr


@requires_verible
def test_cli_verb_json_output_is_the_full_machine_readable_report():
    d = _env_dir(CLEAN_ENV_SV)
    proc = subprocess.run([sys.executable, "-m", "dv_harness", "uvm-lint",
                           "--env-dir", str(d), "--json"],
                          capture_output=True, text=True, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "PASS"
    assert payload["classes_analyzed"] == 6
    assert payload["verible_version"]
