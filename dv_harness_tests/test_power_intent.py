"""Tests for dv_harness/power_intent.py -- the real UPF (IEEE 1801) parser,
the structured power-intent model, and the self-consistency analysis of it
(spec section 224 "LOW-POWER INTEGRATION").

Discipline, the same one dv_harness_tests/test_uvm_structural_lint.py uses:

  1. A CLEAN, realistic synthetic UPF fixture
     (fixtures/power_intent/synthetic_lp_soc.upf -- clearly labelled in its own
     header as a fixture, not a real DUT's power intent, because this project
     owns no low-power DUT) parses into a fully-asserted structured model and
     reports ZERO findings. An analysis that fires on correct power intent is
     useless no matter how many defects it catches.
  2. EVERY analysis rule is then driven by MUTATING that same clean source one
     defect at a time, so each assertion proves "this rule caught this specific
     injected defect", not merely "a function returned a list". The clean
     baseline having zero findings is what makes that inference valid.
  3. The Tcl-subset tokenizer is tested on the syntax a real UPF file actually
     uses -- comments, `;` separation, backslash continuation, nested braces,
     quoting, and `set`/`$var` substitution including the Tcl rule that braces
     suppress substitution.
  4. The integration is exercised through the REAL entry points: the real
     `tools/dut_architecture/build_architecture_model.py` subprocess (whose
     `power_domains` field was hardcoded `[]` before this change) and the real
     `dv-harness power-intent` CLI subprocess.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import power_intent as pi

FIXTURE = Path(__file__).parent / "fixtures" / "power_intent" / "synthetic_lp_soc.upf"
REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _clean_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _analyze(text: str, label: str = "mutated.upf") -> pi.PowerIntentReport:
    return pi.analyze_power_intent(pi.parse_upf_text(text, file_label=label))


def _codes(report: pi.PowerIntentReport) -> set:
    return {f.code for f in report.findings}


def _mutate(old: str, new: str) -> pi.PowerIntentReport:
    """Replace exactly one substring of the clean fixture. Asserts the target
    really is present and unique, so a fixture edit can never silently turn a
    mutation test into a no-op that still 'passes'."""
    text = _clean_text()
    assert text.count(old) == 1, f"mutation target not unique in fixture: {old!r}"
    return _analyze(text.replace(old, new))


# ---------------------------------------------------------------------------
# 1. tokenizer
# ---------------------------------------------------------------------------

def test_tokenizer_handles_comments_semicolons_and_continuation():
    src = textwrap.dedent("""\
        # a whole-line comment
        create_power_domain PD_A -include_scope ; create_power_domain PD_B
        create_supply_port VDD \\
            -domain PD_A \\
            -direction in
        set X 5  ;# trailing comment after a semicolon
    """)
    cmds = pi.tokenize_upf(src, "t.upf")
    assert [c.name for c in cmds] == [
        "create_power_domain", "create_power_domain", "create_supply_port", "set"]
    # the continued command is ONE command with all its options, and its line
    # number is where the command STARTED
    port = cmds[2]
    assert port.line == 3
    assert [w.text for w in port.words] == ["VDD", "-domain", "PD_A", "-direction", "in"]


def test_tokenizer_handles_nested_braces_and_quotes():
    src = 'create_power_switch sw -on_state {on_state vin {!sleep && ok}} -x "a b"\n'
    cmd = pi.tokenize_upf(src, "t.upf")[0]
    on_state = cmd.words[2]
    assert on_state.braced is True
    assert on_state.text == "on_state vin {!sleep && ok}"
    quoted = cmd.words[4]
    assert quoted.quoted is True and quoted.text == "a b"


def test_unbalanced_brace_raises_rather_than_silently_truncating():
    with pytest.raises(pi.UpfParseError):
        pi.tokenize_upf("create_power_domain PD_A -elements {u_a u_b\n", "t.upf")


def test_variable_substitution_follows_tcl_brace_rule():
    """`$V` substitutes in a bare word; inside `{}` Tcl performs NO
    substitution, so a braced `$V` must stay literal -- getting this backwards
    would silently invent signal names that are not in the design."""
    src = textwrap.dedent("""\
        set V pmu_iso_en
        create_power_domain PD_A -include_scope
        set_isolation iso -domain PD_A -isolation_power_net VDD \\
            -isolation_signal $V -clamp_value 0
        set_retention ret -domain PD_A -retention_power_net VDD \\
            -save_signal {$V posedge} -restore_signal {r posedge}
    """)
    intent = pi.parse_upf_text(src, "t.upf")
    assert intent.variables == {"V": "pmu_iso_en"}
    assert intent.isolation[0].isolation_signal == "pmu_iso_en"
    assert intent.retention[0].save_signal == "$V"


def test_unresolved_variable_is_reported_not_silently_kept():
    intent = pi.parse_upf_text(
        "create_power_domain PD_A -include_scope\n"
        "set_isolation iso -domain PD_A -isolation_signal $NOPE\n", "t.upf")
    assert intent.isolation[0].isolation_signal == "$NOPE"
    assert "UNRESOLVED_UPF_VARIABLE" in {i.code for i in intent.issues}


# ---------------------------------------------------------------------------
# 2. the clean fixture: full structured model, zero findings
# ---------------------------------------------------------------------------

def test_clean_fixture_extracts_the_full_structured_model():
    intent = pi.extract_power_intent([FIXTURE])

    assert intent.upf_version == "2.1"
    assert intent.design_top == "synthetic_lp_soc"
    assert intent.domain_names == ["PD_TOP", "PD_PERIPH"]

    top = intent.domain("PD_TOP")
    assert top.include_scope is True
    assert top.primary_power_net == "VDD" and top.primary_ground_net == "VSS"

    periph = intent.domain("PD_PERIPH")
    assert periph.elements == ["u_periph"]
    assert periph.primary_power_net == "VDD_SW"

    assert sorted(p.name for p in intent.supply_ports) == ["VDD", "VSS"]
    assert sorted(n.name for n in intent.supply_nets) == ["VDD", "VDD_SW", "VSS"]
    # connect_supply_net really attached the port to the net
    vdd_net = next(n for n in intent.supply_nets if n.name == "VDD")
    assert vdd_net.connected_ports == ["VDD"]

    assert len(intent.switches) == 1
    sw = intent.switches[0]
    assert sw.name == "sw_periph" and sw.domain == "PD_PERIPH"
    assert sw.output_supply_ports == ["vout VDD_SW"]
    assert sw.control_ports == ["sleep pmu_periph_sleep"]

    # UPF-1.0 style: set_isolation + a SEPARATE set_isolation_control, merged
    # into one strategy record with one answer to "does it have a control".
    iso = intent.isolation[0]
    assert iso.name == "iso_periph" and iso.domain == "PD_PERIPH"
    assert iso.isolation_power_net == "VDD" and iso.clamp_value == "0"
    assert iso.applies_to == "outputs" and iso.location == "parent"
    assert iso.isolation_signal == "pmu_iso_en"   # substituted from $ISO_CTRL
    assert iso.isolation_sense == "high"
    assert iso.has_control is True
    assert iso.line < iso.control_line          # both real source sites recorded

    ret = intent.retention[0]
    assert ret.name == "ret_periph" and ret.domain == "PD_PERIPH"
    assert (ret.save_signal, ret.save_sense) == ("pmu_save", "posedge")
    assert (ret.restore_signal, ret.restore_sense) == ("pmu_restore", "posedge")
    assert ret.retention_power_net == "VDD"

    assert intent.switchable_domains() == ["PD_PERIPH"]
    assert intent.unsupported_commands == []
    assert intent.issues == []


def test_clean_fixture_analysis_is_pass_with_zero_findings():
    report = pi.analyze_power_intent(pi.extract_power_intent([FIXTURE]))
    assert report.status == "PASS"
    assert report.findings == [], [f.to_dict() for f in report.findings]


def test_line_numbers_point_at_the_real_source_lines():
    intent = pi.extract_power_intent([FIXTURE])
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    for obj, token in [(intent.domain("PD_PERIPH"), "create_power_domain PD_PERIPH"),
                       (intent.switches[0], "create_power_switch sw_periph"),
                       (intent.isolation[0], "set_isolation iso_periph"),
                       (intent.retention[0], "set_retention ret_periph")]:
        assert lines[obj.line - 1].startswith(token), (obj.line, lines[obj.line - 1])


# ---------------------------------------------------------------------------
# 3. one mutation per analysis rule
# ---------------------------------------------------------------------------

def test_switchable_domain_without_isolation_is_an_error():
    """The rule that carries real low-power meaning: a domain a power switch
    can turn off, whose outputs nothing clamps."""
    text = _clean_text()
    start = text.index("set_isolation iso_periph")
    end = text.index("# ---- retention")
    report = _analyze(text[:start] + text[end:])
    assert "SWITCHABLE_DOMAIN_WITHOUT_ISOLATION" in _codes(report)
    assert report.status == "FAIL"


def test_isolation_without_control_signal_is_an_error():
    text = _clean_text()
    start = text.index("set_isolation_control iso_periph")
    end = text.index("# ---- retention")
    report = _analyze(text[:start] + text[end:])
    assert "ISOLATION_WITHOUT_CONTROL_SIGNAL" in _codes(report)
    assert "SWITCHABLE_DOMAIN_WITHOUT_ISOLATION" not in _codes(report)


def test_isolation_control_naming_no_strategy_is_an_error():
    report = _mutate("set_isolation_control iso_periph", "set_isolation_control iso_typo")
    assert "ISOLATION_CONTROL_WITHOUT_STRATEGY" in _codes(report)
    # and the real strategy is then correctly reported as uncontrolled
    assert "ISOLATION_WITHOUT_CONTROL_SIGNAL" in _codes(report)


def test_isolation_supply_net_that_was_never_declared_is_an_error():
    report = _mutate("-isolation_power_net VDD ", "-isolation_power_net VDD_TYPO ")
    assert "SUPPLY_NET_UNDECLARED" in _codes(report)
    bad = [f for f in report.findings if f.code == "SUPPLY_NET_UNDECLARED"]
    assert "VDD_TYPO" in bad[0].message


def test_isolation_without_clamp_value_is_a_warning_not_an_error():
    report = _mutate("-clamp_value 0 -applies_to outputs", "-applies_to outputs")
    assert "ISOLATION_WITHOUT_CLAMP_VALUE" in _codes(report)
    assert report.status == "PASS"   # WARNING only -- a missing clamp is not provably wrong
    assert [f.severity for f in report.findings
            if f.code == "ISOLATION_WITHOUT_CLAMP_VALUE"] == ["WARNING"]


def test_isolation_control_without_sense_is_a_warning():
    report = _mutate("-isolation_sense high ", "")
    assert "ISOLATION_CONTROL_WITHOUT_SENSE" in _codes(report)
    assert report.status == "PASS"


def test_isolation_on_an_undeclared_domain_is_an_error():
    report = _mutate("set_isolation iso_periph -domain PD_PERIPH",
                     "set_isolation iso_periph -domain PD_GHOST")
    assert "ISOLATION_DOMAIN_UNDECLARED" in _codes(report)


def test_retention_on_an_undeclared_domain_is_an_error():
    report = _mutate("set_retention ret_periph -domain PD_PERIPH",
                     "set_retention ret_periph -domain PD_GHOST")
    assert "RETENTION_DOMAIN_UNDECLARED" in _codes(report)


def test_retention_with_no_save_or_restore_at_all_is_an_error():
    text = _clean_text()
    report = _analyze(text[:text.index("set_retention_control ret_periph")])
    assert "RETENTION_WITHOUT_SAVE_RESTORE" in _codes(report)


def test_retention_with_save_but_no_restore_is_an_error():
    report = _mutate("    -restore_signal {pmu_restore posedge}\n", "")
    assert "RETENTION_CONTROL_INCOMPLETE" in _codes(report)
    bad = [f for f in report.findings if f.code == "RETENTION_CONTROL_INCOMPLETE"]
    assert "-restore_signal" in bad[0].message


def test_retention_without_an_always_on_supply_is_an_error():
    report = _mutate("-retention_power_net VDD -retention_ground_net VSS", "")
    assert "RETENTION_WITHOUT_SUPPLY" in _codes(report)


def test_switchable_domain_without_retention_is_info_only():
    """Losing state across a power-down is a legitimate design choice, so this
    must NOT fail the analysis -- it is surfaced for a human to confirm."""
    text = _clean_text()
    report = _analyze(text[:text.index("# ---- retention")])
    assert "SWITCHABLE_DOMAIN_WITHOUT_RETENTION" in _codes(report)
    assert [f.severity for f in report.findings
            if f.code == "SWITCHABLE_DOMAIN_WITHOUT_RETENTION"] == ["INFO"]
    assert report.status == "PASS"


def test_power_switch_without_a_control_port_is_an_error():
    report = _mutate("    -control_port       {sleep pmu_periph_sleep} \\\n", "")
    assert "SWITCH_WITHOUT_CONTROL_PORT" in _codes(report)


def test_power_switch_on_an_undeclared_domain_is_an_error():
    report = _mutate("    -domain             PD_PERIPH \\",
                     "    -domain             PD_GHOST \\")
    assert "SWITCH_DOMAIN_UNDECLARED" in _codes(report)


def test_duplicate_power_domain_without_update_is_an_error():
    report = _mutate("create_power_domain PD_PERIPH -elements {u_periph}",
                     "create_power_domain PD_PERIPH -elements {u_periph}\n"
                     "create_power_domain PD_PERIPH -elements {u_other}")
    assert "DUPLICATE_POWER_DOMAIN" in _codes(report)


def test_duplicate_domain_with_update_is_accepted_and_merges_elements():
    text = _clean_text().replace(
        "create_power_domain PD_PERIPH -elements {u_periph}",
        "create_power_domain PD_PERIPH -elements {u_periph}\n"
        "create_power_domain PD_PERIPH -update -elements {u_periph_dma}")
    intent = pi.parse_upf_text(text, "m.upf")
    assert intent.domain("PD_PERIPH").elements == ["u_periph", "u_periph_dma"]
    assert pi.analyze_power_intent(intent).status == "PASS"


def test_domain_with_no_elements_and_no_include_scope_is_a_warning():
    report = _mutate("create_power_domain PD_PERIPH -elements {u_periph}",
                     "create_power_domain PD_PERIPH")
    assert "DOMAIN_WITHOUT_ELEMENTS" in _codes(report)


def test_domain_with_no_primary_supply_is_a_warning():
    report = _mutate(
        "set_domain_supply_net PD_PERIPH -primary_power_net VDD_SW -primary_ground_net VSS", "")
    assert "DOMAIN_WITHOUT_PRIMARY_SUPPLY" in _codes(report)


def test_supply_port_in_an_undeclared_domain_is_an_error():
    report = _mutate("create_supply_port VDD -domain PD_TOP",
                     "create_supply_port VDD -domain PD_GHOST")
    assert "SUPPLY_PORT_DOMAIN_UNDECLARED" in _codes(report)


def test_connect_supply_net_to_an_undeclared_net_is_an_error():
    report = _mutate("connect_supply_net VSS -ports {VSS}",
                     "connect_supply_net VSS_TYPO -ports {VSS}")
    assert "CONNECT_SUPPLY_NET_UNDECLARED_NET" in _codes(report)


def test_unmodelled_command_is_recorded_as_info_never_silently_dropped():
    """An honest parser must say what it skipped. A power-state table is real
    UPF this module deliberately does not model."""
    report = _mutate("# ---- retention",
                     "add_power_state PD_PERIPH -state {OFF -logic_expr {sleep}}\n"
                     "# ---- retention")
    infos = [f for f in report.findings if f.code == "UNMODELLED_UPF_COMMAND"]
    assert len(infos) == 1
    assert infos[0].severity == "INFO" and "add_power_state" in infos[0].message
    assert report.status == "PASS"   # unmodelled != defective


def test_switchability_is_also_derived_through_the_supply_net_not_only_domain():
    """A power switch does not have to name `-domain`: driving the net a domain
    uses as its primary power net makes that domain switchable just the same.
    Only tracking `-domain` would miss the whole net-driven form."""
    src = textwrap.dedent("""\
        create_power_domain PD_TOP -include_scope
        create_power_domain PD_X -elements {u_x}
        create_supply_net VDD    -domain PD_TOP
        create_supply_net VDD_SW -domain PD_X
        set_domain_supply_net PD_TOP -primary_power_net VDD
        set_domain_supply_net PD_X   -primary_power_net VDD_SW
        create_power_switch sw \\
            -input_supply_port  {vin  VDD} \\
            -output_supply_port {vout VDD_SW} \\
            -control_port       {sleep pmu_sleep} \\
            -on_state           {on vin {!sleep}}
    """)
    intent = pi.parse_upf_text(src, "netsw.upf")
    assert intent.switchable_domains() == ["PD_X"]
    assert "SWITCHABLE_DOMAIN_WITHOUT_ISOLATION" in _codes(pi.analyze_power_intent(intent))


def test_supply_set_satisfies_the_isolation_and_retention_supply_requirement():
    """UPF 2.x expresses always-on supply as a supply SET, not a net pair. A
    strategy using one must not be reported as having no supply."""
    src = textwrap.dedent("""\
        create_power_domain PD_TOP -include_scope
        create_supply_net VDD -domain PD_TOP
        set_domain_supply_net PD_TOP -primary_power_net VDD
        create_supply_set AON -function {power VDD} -function {ground VSS}
        set_isolation iso -domain PD_TOP -isolation_supply_set AON \\
            -isolation_signal iso_en -isolation_sense high -clamp_value 0
        set_retention ret -domain PD_TOP -retention_supply_set AON \\
            -save_signal {s posedge} -restore_signal {r posedge}
    """)
    report = _analyze(src, "ss.upf")
    assert "ISOLATION_WITHOUT_SUPPLY" not in _codes(report)
    assert "RETENTION_WITHOUT_SUPPLY" not in _codes(report)
    assert report.status == "PASS"
    # and an UNDECLARED supply set is still caught
    bad = _analyze(src.replace("-isolation_supply_set AON", "-isolation_supply_set NOPE"), "ss.upf")
    assert "SUPPLY_NET_UNDECLARED" in _codes(bad)


def test_findings_are_sorted_errors_first():
    report = _mutate("-isolation_power_net VDD ", "-isolation_power_net VDD_TYPO ")
    severities = [f.severity for f in report.findings]
    assert severities == sorted(severities, key=lambda s: {"ERROR": 0, "WARNING": 1, "INFO": 2}[s])


# ---------------------------------------------------------------------------
# 4. the UNSUPPORTED / UNKNOWN outcome (spec section 224's explicit rule)
# ---------------------------------------------------------------------------

def test_sources_without_power_intent_report_not_available_never_pass():
    report = _analyze("# just a Tcl file\nset FOO bar\nputs hello\n", "nolp.upf")
    assert report.status == "NOT_AVAILABLE"
    assert report.findings == []
    assert "no power-intent constructs" in report.reason


def test_missing_file_is_reported_not_crashed(tmp_path):
    intent = pi.extract_power_intent([tmp_path / "does_not_exist.upf"])
    assert "UPF_FILE_UNREADABLE" in {i.code for i in intent.issues}
    assert pi.analyze_power_intent(intent).status == "NOT_AVAILABLE"


def test_multiple_files_accumulate_into_one_model(tmp_path):
    """A real design splits power intent across files, and a control command in
    the second file must attach to the strategy declared in the first."""
    a = tmp_path / "a.upf"
    b = tmp_path / "b.upf"
    a.write_text("create_power_domain PD_A -include_scope\n"
                 "create_supply_net VDD -domain PD_A\n"
                 "set_domain_supply_net PD_A -primary_power_net VDD\n"
                 "set_isolation iso -domain PD_A -isolation_power_net VDD -clamp_value 0\n")
    b.write_text("set_isolation_control iso -domain PD_A "
                 "-isolation_signal iso_en -isolation_sense high\n")
    intent = pi.extract_power_intent([a, b])
    assert len(intent.source_files) == 2
    assert intent.isolation[0].isolation_signal == "iso_en"
    assert pi.analyze_power_intent(intent).status == "PASS"


# ---------------------------------------------------------------------------
# 5. real integration: the architecture model and the CLI
# ---------------------------------------------------------------------------

def test_power_domains_for_architecture_model_rows():
    rows = pi.power_domains_for_architecture_model(pi.extract_power_intent([FIXTURE]))
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"PD_TOP", "PD_PERIPH"}
    periph = by_name["PD_PERIPH"]
    assert periph["switchable"] is True
    assert periph["isolation_strategies"] == ["iso_periph"]
    assert periph["retention_strategies"] == ["ret_periph"]
    assert periph["primary_power_net"] == "VDD_SW"
    assert periph["source"] == "UPF"
    # the evidence string is a real file:line a reader can open
    ev_file, ev_line = periph["evidence"].rsplit(":", 1)
    assert Path(ev_file) == FIXTURE
    assert FIXTURE.read_text(encoding="utf-8").splitlines()[int(ev_line) - 1].startswith(
        "create_power_domain PD_PERIPH")
    assert by_name["PD_TOP"]["switchable"] is False


def test_real_build_architecture_model_populates_power_domains(tmp_path):
    """Through the REAL tools/dut_architecture/build_architecture_model.py
    subprocess -- the field it fills was hardcoded [] before this change."""
    extract = tmp_path / "dut_extract.json"
    extract.write_text(json.dumps({
        "modules": [{"module": "synthetic_lp_soc"}],
        "ports": [{"name": "clk"}, {"name": "rst_n"}],
    }))
    out = tmp_path / "arch.json"
    script = REPO_ROOT / "tools" / "dut_architecture" / "build_architecture_model.py"
    r = subprocess.run([sys.executable, str(script),
                        "--dut-extract", str(extract), "--out", str(out),
                        "--upf", str(FIXTURE)],
                       capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stderr
    model = json.loads(out.read_text())
    assert [d["name"] for d in model["power_domains"]] == ["PD_TOP", "PD_PERIPH"]
    assert any(e["type"] == "UPF_POWER_INTENT" for e in model["evidence"])
    # the pre-existing fields are untouched by this addition
    assert [c["name"] for c in model["clock_domains"]] == ["clk"]
    assert [c["name"] for c in model["reset_domains"]] == ["rst_n"]


def test_real_build_architecture_model_without_upf_says_unknown(tmp_path):
    """Section 224: absent low-power evidence is UNSUPPORTED/UNKNOWN, and must
    not look like a design that simply has no power domains."""
    extract = tmp_path / "dut_extract.json"
    extract.write_text(json.dumps({"modules": [{"module": "m"}], "ports": [{"name": "clk"}]}))
    out = tmp_path / "arch.json"
    script = REPO_ROOT / "tools" / "dut_architecture" / "build_architecture_model.py"
    r = subprocess.run([sys.executable, str(script),
                        "--dut-extract", str(extract), "--out", str(out)],
                       capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stderr
    model = json.loads(out.read_text())
    assert model["power_domains"] == []
    assert any("UNSUPPORTED/UNKNOWN" in u for u in model["unknowns"])


def _cli(*args, expect: int):
    r = subprocess.run([sys.executable, "-m", "dv_harness", "--project-root", str(REPO_ROOT),
                        "power-intent", *args],
                       capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert r.returncode == expect, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def test_cli_reports_the_clean_fixture_as_pass():
    out = _cli("--upf", str(FIXTURE), expect=0)
    assert "power-intent: PASS" in out
    assert "no low-power BEHAVIOR has been verified" in out


def test_cli_json_carries_both_findings_and_the_model():
    out = _cli("--upf", str(FIXTURE), "--json", expect=0)
    doc = json.loads(out)
    assert doc["status"] == "PASS" and doc["findings"] == []
    assert [d["name"] for d in doc["power_intent"]["domains"]] == ["PD_TOP", "PD_PERIPH"]


def test_cli_fail_on_error_exits_one_and_plain_run_does_not(tmp_path):
    bad = tmp_path / "bad.upf"
    bad.write_text("create_power_domain PD_A -include_scope\n"
                   "create_supply_net VDD -domain PD_A\n"
                   "set_domain_supply_net PD_A -primary_power_net VDD\n"
                   "set_isolation iso -domain PD_GHOST -isolation_power_net VDD\n")
    assert "ISOLATION_DOMAIN_UNDECLARED" in _cli("--upf", str(bad), expect=0)
    _cli("--upf", str(bad), "--fail-on-error", expect=1)


def test_cli_exits_two_on_sources_with_no_power_intent(tmp_path):
    nolp = tmp_path / "nolp.upf"
    nolp.write_text("set FOO bar\n")
    # exit 2 with AND without --fail-on-error: NOT_AVAILABLE is never a PASS
    assert "NOT_AVAILABLE" in _cli("--upf", str(nolp), expect=2)
    _cli("--upf", str(nolp), "--fail-on-error", expect=2)
