"""Tests for dv_harness/verification_intent_ir.py -- the per-requirement
Verification Intent IR.

Discipline mirrors test_requirement_contract.py / test_power_intent.py: a
core positive path is asserted against REAL producers (power_intent.py's own
UPF parser and synthetic fixture, protocol_capability.py's real registry,
interrupt_dma_clock_reset_extraction.py's real RTL line-scan, sys_regmap.py's
real mode-determining-bit classifier), and every honest-absence branch is
driven by a real negative control (absent input, malformed input, a protocol/
interface this harness genuinely cannot model) so an absence of evidence is
never mistaken for a clean pass. Nothing here is mocked.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWER_INTENT_FIXTURE = ROOT / "dv_harness_tests" / "fixtures" / "power_intent" / "synthetic_lp_soc.upf"

from dv_harness import verification_intent_ir as vir  # noqa: E402
from dv_harness import power_intent  # noqa: E402
from dv_harness import sys_regmap  # noqa: E402
from dv_harness import requirement_contract as rc  # noqa: E402
from dv_harness.evidence_provenance import AGENT_SELF_ATTESTED, SELF_ATTESTED_CAVEAT  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def contract_record(**over) -> dict:
    """A fully-populated, internally coherent COMPLETE requirement record,
    the same shape test_requirement_contract.py's own clean_record() uses.
    Synthetic -- describes no real DUT."""
    r = {
        "contract_schema_version": "1.0",
        "requirement_id": "REQ-PCIE-LTSSM-001",
        "source": {"document": "pcie_base_spec.pdf", "locator": "section 4.2",
                   "quote": "The LTSSM shall transition to Recovery on receiver error."},
        "feature": "LTSSM Recovery entry",
        "protocol": "PCIe",
        "configuration": "Gen3 x4",
        "precondition": "link in L0",
        "stimulus": "inject a receiver error on lane 2",
        "expected_result": "LTSSM transitions to Recovery.RcvrLock within 1 symbol time",
        "observability": "ltssm_state bus; VIP LTSSM callback",
        "checker": "scoreboard compares observed LTSSM transition against the state graph",
        "coverage_intent": "cover every declared LTSSM state crossed with lane count",
        "priority": "P0",
        "criticality": "BLOCKER",
        "confidence": "HIGH",
        "status": "COMPLETE",
    }
    r.update(over)
    return r


def plain_record(**over) -> dict:
    """A plain, non-contract-shaped requirement dict -- the duck-typed input
    shape this module also accepts."""
    r = {"feature": "some feature", "protocol": "PCIe",
         "stimulus": "drive X", "expected_result": "Y happens",
         "checker": "scoreboard checks Y", "coverage_intent": "cover X x Y"}
    r.update(over)
    return r


def rtl_fixture(tmp_path: Path, with_irq: bool = True) -> Path:
    irq_port = "    input  wire        irq_uart,\n" if with_irq else ""
    text = (
        "module dummy_irq_ctrl (\n"
        "    input  wire        clk,\n"
        "    input  wire        rst_n,\n"
        f"{irq_port}"
        "    output reg         irq_out\n"
        ");\n"
        "    always_ff @(posedge clk or negedge rst_n) begin\n"
        "        if (!rst_n) begin\n"
        "            irq_out <= 1'b0;\n"
        "        end\n"
        "    end\n"
        "endmodule\n"
    )
    p = tmp_path / "dummy_irq_ctrl.sv"
    p.write_text(text, encoding="utf-8")
    return p


def clean_sys_regmap_doc(required_value: str = "0x1") -> dict:
    return {
        "schema_version": "1.0",
        "blocks": [{
            "name": "CRU", "base_address": "0x40000000", "kind": "clock_control",
            "registers": [{
                "name": "PCIE_CLK_EN", "address_offset": "0x0010", "width": 32, "access": "RW",
                "fields": [{
                    "name": "clk_en", "bit_offset": 0, "bit_width": 1, "access": "RW",
                    "control_kind": "clock_enable",
                    "required_value": required_value,
                    "governs_interfaces": ["PCIe"],
                }],
            }],
        }],
    }


# --------------------------------------------------------------------------
# Core semantic-bridge fields
# --------------------------------------------------------------------------

class TestCoreFields:
    def test_positive_objective_stimulus_checker_coverage_resolved(self):
        ir = vir.build_verification_intent_ir(contract_record())
        assert ir.objective.startswith("Verify LTSSM Recovery entry")
        assert "such that" in ir.objective
        assert ir.stimulus_intent == "inject a receiver error on lane 2"
        assert ir.checker_intent.startswith("scoreboard compares")
        assert ir.coverage_intent.startswith("cover every declared LTSSM state")

    def test_negative_objective_unknown_when_feature_and_expected_result_absent(self):
        rec = plain_record(feature="TBD", expected_result="unknown")
        ir = vir.build_verification_intent_ir(rec)
        assert ir.objective.startswith("OBJECTIVE_UNKNOWN")

    def test_negative_stimulus_checker_coverage_unknown_on_sentinel(self):
        rec = plain_record(stimulus="N/A", checker="?", coverage_intent="")
        ir = vir.build_verification_intent_ir(rec)
        assert ir.stimulus_intent.startswith("STIMULUS_INTENT_UNKNOWN")
        assert ir.checker_intent.startswith("CHECKER_INTENT_UNKNOWN")
        assert ir.coverage_intent.startswith("COVERAGE_INTENT_UNKNOWN")

    def test_evidence_provenance_is_always_agent_self_attested(self):
        ir = vir.build_verification_intent_ir(plain_record())
        assert ir.evidence_provenance == AGENT_SELF_ATTESTED
        assert ir.evidence_provenance_caveat == SELF_ATTESTED_CAVEAT
        # Not a caller option -- passing a bogus kwarg has no field to land on.
        d = ir.to_dict()
        assert d["evidence_provenance"] == AGENT_SELF_ATTESTED


# --------------------------------------------------------------------------
# requirement_contract.py reuse
# --------------------------------------------------------------------------

class TestRequirementContractStatusReuse:
    def test_positive_contract_shaped_complete_record_is_downstream_consumable(self):
        ir = vir.build_verification_intent_ir(contract_record())
        st = ir.requirement_contract_status
        assert st["contract_shaped"] is True
        assert st["downstream_consumable"] is True

    def test_negative_plain_dict_is_not_contract_shaped(self):
        ir = vir.build_verification_intent_ir(plain_record())
        st = ir.requirement_contract_status
        assert st["contract_shaped"] is False
        assert st["downstream_consumable"] is None

    def test_negative_overclaimed_status_is_not_downstream_consumable(self):
        """Mirrors CLAUDE.md's own headline requirement_contract test: COMPLETE
        declared while checker is TBD must be rejected, real detection reused
        here rather than re-implemented."""
        rec = contract_record(checker="TBD")
        ir = vir.build_verification_intent_ir(rec)
        st = ir.requirement_contract_status
        assert st["contract_shaped"] is True
        assert st["downstream_consumable"] is False


# --------------------------------------------------------------------------
# state_machine domain -- protocol_capability.py reuse
# --------------------------------------------------------------------------

class TestStateMachineDomain:
    def test_positive_pcie_has_a_real_state_graph_model(self):
        ir = vir.build_verification_intent_ir(plain_record(protocol="PCIe"))
        plan = ir.domain_plans[vir.DOMAIN_STATE_MACHINE]
        assert plan.applicable is True
        assert plan.dut_evidence_status == vir.DUT_EVIDENCE_FOUND
        assert "ltssm_top_level_state_graph" in plan.dut_evidence["state_models"]
        assert plan.dut_evidence_source == "dv_harness.protocol_capability.capability_for"

    def test_negative_usb_has_no_state_model_module(self):
        """USB_2_3x's capability entry declares model=None (dut_proof only) --
        a real, deliberate NOT_AVAILABLE case, not a fabricated one."""
        ir = vir.build_verification_intent_ir(plain_record(protocol="USB_2_3x"))
        plan = ir.domain_plans[vir.DOMAIN_STATE_MACHINE]
        assert plan.dut_evidence_status == vir.NOT_AVAILABLE
        assert "generic skeleton only" in plan.dut_evidence_reason

    def test_negative_unresolved_protocol_is_not_applicable(self):
        ir = vir.build_verification_intent_ir(plain_record(protocol="TBD"))
        plan = ir.domain_plans[vir.DOMAIN_STATE_MACHINE]
        assert plan.applicable is False
        assert plan.dut_evidence_status == vir.NOT_APPLICABLE

    def test_negative_unknown_protocol_name_is_not_available(self):
        ir = vir.build_verification_intent_ir(plain_record(protocol="NotARealProtocol"))
        plan = ir.domain_plans[vir.DOMAIN_STATE_MACHINE]
        assert plan.dut_evidence_status == vir.NOT_AVAILABLE
        assert "no registered capability entry" in plan.dut_evidence_reason


# --------------------------------------------------------------------------
# register_csr domain -- sys_regmap.py reuse
# --------------------------------------------------------------------------

class TestRegisterCsrDomain:
    def test_positive_verifiable_mode_determining_bit_found(self):
        doc = clean_sys_regmap_doc(required_value="0x1")
        ir = vir.build_verification_intent_ir(plain_record(protocol="PCIe"),
                                               sys_regmap_doc=doc)
        plan = ir.domain_plans[vir.DOMAIN_REGISTER_CSR]
        assert plan.dut_evidence_status == vir.DUT_EVIDENCE_FOUND
        assert len(plan.dut_evidence["required_preconditions"]) == 1
        assert plan.dut_evidence["required_preconditions"][0]["field"] == "clk_en"

    def test_negative_undocumented_required_value_is_partial(self):
        doc = clean_sys_regmap_doc(required_value=None)
        ir = vir.build_verification_intent_ir(plain_record(protocol="PCIe"),
                                               sys_regmap_doc=doc)
        plan = ir.domain_plans[vir.DOMAIN_REGISTER_CSR]
        assert plan.dut_evidence_status == vir.DUT_EVIDENCE_PARTIAL
        assert len(plan.dut_evidence["unverifiable_bits"]) == 1

    def test_negative_no_doc_supplied_is_not_available(self):
        ir = vir.build_verification_intent_ir(plain_record(protocol="PCIe"))
        plan = ir.domain_plans[vir.DOMAIN_REGISTER_CSR]
        assert plan.dut_evidence_status == vir.NOT_AVAILABLE
        assert "no sys_regmap document" in plan.dut_evidence_reason

    def test_negative_no_interface_named_is_not_applicable(self):
        doc = clean_sys_regmap_doc()
        ir = vir.build_verification_intent_ir(plain_record(protocol="TBD", feature="unknown"),
                                               sys_regmap_doc=doc)
        plan = ir.domain_plans[vir.DOMAIN_REGISTER_CSR]
        assert plan.applicable is False
        assert plan.dut_evidence_status == vir.NOT_APPLICABLE

    def test_negative_no_bit_governs_this_interface(self):
        doc = clean_sys_regmap_doc()
        ir = vir.build_verification_intent_ir(plain_record(protocol="SomeOtherIface"),
                                               sys_regmap_doc=doc)
        plan = ir.domain_plans[vir.DOMAIN_REGISTER_CSR]
        assert plan.dut_evidence_status == vir.NOT_AVAILABLE
        assert "no mode-determining bit" in plan.dut_evidence_reason

    def test_negative_malformed_doc_fails_schema_validation(self):
        doc = {"schema_version": "1.0"}  # missing required "blocks"
        ir = vir.build_verification_intent_ir(plain_record(protocol="PCIe"),
                                               sys_regmap_doc=doc)
        plan = ir.domain_plans[vir.DOMAIN_REGISTER_CSR]
        assert plan.dut_evidence_status == vir.NOT_AVAILABLE
        assert "schema validation" in plan.dut_evidence_reason


# --------------------------------------------------------------------------
# interrupt / reset_clock domains -- interrupt_dma_clock_reset_extraction.py reuse
# --------------------------------------------------------------------------

class TestInterruptResetClockDomains:
    def test_positive_both_domains_found_from_real_rtl_scan(self, tmp_path):
        rtl = rtl_fixture(tmp_path, with_irq=True)
        ir = vir.build_verification_intent_ir(plain_record(), source_paths=[str(rtl)])
        irq_plan = ir.domain_plans[vir.DOMAIN_INTERRUPT]
        rc_plan = ir.domain_plans[vir.DOMAIN_RESET_CLOCK]
        assert irq_plan.dut_evidence_status == vir.DUT_EVIDENCE_FOUND
        assert any(s["name"] == "irq_uart" for s in irq_plan.dut_evidence["sources"])
        assert rc_plan.dut_evidence_status == vir.DUT_EVIDENCE_FOUND
        resets = rc_plan.dut_evidence["resets"]
        assert any(r["name"] == "rst_n" and r["active_level"] == "LOW" for r in resets)

    def test_negative_no_source_paths_both_not_available(self):
        ir = vir.build_verification_intent_ir(plain_record())
        assert ir.domain_plans[vir.DOMAIN_INTERRUPT].dut_evidence_status == vir.NOT_AVAILABLE
        assert ir.domain_plans[vir.DOMAIN_RESET_CLOCK].dut_evidence_status == vir.NOT_AVAILABLE

    def test_negative_per_facet_independence_no_irq_ports(self, tmp_path):
        """RTL with clock/reset but no interrupt-named port: interrupt domain
        stays honestly NOT_AVAILABLE while reset_clock still finds real
        evidence -- one facet's absence must never mask another's presence."""
        rtl = rtl_fixture(tmp_path, with_irq=False)
        ir = vir.build_verification_intent_ir(plain_record(), source_paths=[str(rtl)])
        assert ir.domain_plans[vir.DOMAIN_INTERRUPT].dut_evidence_status == vir.NOT_AVAILABLE
        assert ir.domain_plans[vir.DOMAIN_RESET_CLOCK].dut_evidence_status == vir.DUT_EVIDENCE_FOUND


# --------------------------------------------------------------------------
# low_power domain -- power_intent.py reuse, verbatim status preservation
# --------------------------------------------------------------------------

class TestLowPowerDomain:
    def test_positive_status_preserved_verbatim_from_power_intent(self):
        assert POWER_INTENT_FIXTURE.is_file()
        ir = vir.build_verification_intent_ir(plain_record(), upf_paths=[str(POWER_INTENT_FIXTURE)])
        plan = ir.domain_plans[vir.DOMAIN_LOW_POWER]
        intent = power_intent.extract_power_intent([str(POWER_INTENT_FIXTURE)])
        real_report = power_intent.analyze_power_intent(intent)
        assert plan.dut_evidence_status == real_report.status
        assert plan.dut_evidence_status in ("PASS", "FAIL")  # real fixture parses to a verdict
        assert plan.status_vocabulary_source is not None
        assert "PowerIntentReport.status" in plan.status_vocabulary_source

    def test_positive_caller_supplied_report_reused_directly(self):
        """Reuses an already-computed report rather than re-parsing UPF."""
        intent = power_intent.extract_power_intent([str(POWER_INTENT_FIXTURE)])
        real_report = power_intent.analyze_power_intent(intent)
        ir = vir.build_verification_intent_ir(plain_record(), power_intent_report=real_report)
        plan = ir.domain_plans[vir.DOMAIN_LOW_POWER]
        assert plan.dut_evidence_status == real_report.status
        assert "caller-supplied report" in plan.dut_evidence_source

    def test_negative_no_input_is_not_available_never_asked(self):
        ir = vir.build_verification_intent_ir(plain_record())
        plan = ir.domain_plans[vir.DOMAIN_LOW_POWER]
        assert plan.dut_evidence_status == vir.NOT_AVAILABLE
        assert "never asked for" in plan.dut_evidence_reason

    def test_negative_empty_upf_preserves_power_intents_own_not_available(self, tmp_path):
        """An empty UPF's real report.status is NOT_AVAILABLE (no power-intent
        constructs) -- this module must PRESERVE that, never upgrade it."""
        empty_upf = tmp_path / "empty.upf"
        empty_upf.write_text("upf_version 2.1\n", encoding="utf-8")
        ir = vir.build_verification_intent_ir(plain_record(), upf_paths=[str(empty_upf)])
        plan = ir.domain_plans[vir.DOMAIN_LOW_POWER]
        assert plan.dut_evidence_status == "NOT_AVAILABLE"
        assert "no power-intent constructs" in plan.dut_evidence_reason

    def test_negative_unparseable_upf_surfaces_the_real_parse_issue(self, tmp_path):
        """extract_power_intent() catches its own UpfParseError internally and
        records it as a real UPF_FILE_UNPARSEABLE issue rather than raising --
        this module must surface that issue (never invent a second failure
        path), and analyze_power_intent()'s own NOT_AVAILABLE (no domains
        parsed) is what this module preserves as the domain's status."""
        bad_upf = tmp_path / "bad.upf"
        bad_upf.write_text("create_power_domain PD_TOP {unterminated brace\n", encoding="utf-8")
        ir = vir.build_verification_intent_ir(plain_record(), upf_paths=[str(bad_upf)])
        plan = ir.domain_plans[vir.DOMAIN_LOW_POWER]
        assert plan.dut_evidence_status == vir.NOT_AVAILABLE
        issues = plan.dut_evidence["power_intent"]["issues"]
        assert any(i["code"] == "UPF_FILE_UNPARSEABLE" for i in issues)


# --------------------------------------------------------------------------
# performance / error_recovery -- no evidence producer, never fabricated
# --------------------------------------------------------------------------

class TestNoProducerDomains:
    def test_performance_always_target_unknown(self):
        ir = vir.build_verification_intent_ir(plain_record())
        plan = ir.domain_plans[vir.DOMAIN_PERFORMANCE]
        assert plan.dut_evidence_status == vir.PERFORMANCE_TARGET_UNKNOWN
        assert plan.dut_evidence == {}
        assert plan.dut_evidence_source is None

    def test_error_recovery_always_target_unknown(self):
        ir = vir.build_verification_intent_ir(plain_record())
        plan = ir.domain_plans[vir.DOMAIN_ERROR_RECOVERY]
        assert plan.dut_evidence_status == vir.ERROR_TARGET_UNKNOWN
        assert plan.dut_evidence == {}
        assert plan.dut_evidence_source is None

    def test_never_flips_to_found_no_matter_what_is_supplied(self, tmp_path):
        """Even with every other domain's real evidence supplied, performance
        and error_recovery must stay TARGET_UNKNOWN -- there is genuinely no
        producer, so no combination of inputs may fabricate one."""
        rtl = rtl_fixture(tmp_path, with_irq=True)
        doc = clean_sys_regmap_doc()
        ir = vir.build_verification_intent_ir(
            contract_record(), source_paths=[str(rtl)], sys_regmap_doc=doc,
            upf_paths=[str(POWER_INTENT_FIXTURE)],
        )
        assert ir.domain_plans[vir.DOMAIN_PERFORMANCE].dut_evidence_status == \
            vir.PERFORMANCE_TARGET_UNKNOWN
        assert ir.domain_plans[vir.DOMAIN_ERROR_RECOVERY].dut_evidence_status == \
            vir.ERROR_TARGET_UNKNOWN


# --------------------------------------------------------------------------
# Vocabulary discipline
# --------------------------------------------------------------------------

class TestVocabularyDiscipline:
    def test_module_vocabulary_does_not_collide_with_models_status(self):
        vir.assert_no_verification_verdict_vocabulary()  # must not raise

    def test_negative_guard_actually_detects_a_collision(self, monkeypatch):
        monkeypatch.setattr(vir, "DUT_EVIDENCE_FOUND", "PASS")
        with pytest.raises(AssertionError):
            vir.assert_no_verification_verdict_vocabulary()


# --------------------------------------------------------------------------
# Set builder + serialization
# --------------------------------------------------------------------------

class TestSetBuilderAndSerialization:
    def test_set_builder_shares_dut_evidence_across_requirements(self, tmp_path):
        rtl = rtl_fixture(tmp_path, with_irq=True)
        recs = [plain_record(requirement_id="R1"), plain_record(requirement_id="R2")]
        irs = vir.build_verification_intent_ir_set(recs, source_paths=[str(rtl)])
        assert len(irs) == 2
        for ir in irs:
            plan = ir.domain_plans[vir.DOMAIN_INTERRUPT]
            assert plan.dut_evidence_status == vir.DUT_EVIDENCE_FOUND

    def test_to_dict_json_roundtrip_and_domain_order(self):
        ir = vir.build_verification_intent_ir(contract_record())
        d = ir.to_dict()
        encoded = json.dumps(d)
        decoded = json.loads(encoded)
        assert list(decoded["domain_plans"].keys()) == list(vir.DOMAINS)
        assert decoded["requirement_id"] == "REQ-PCIE-LTSSM-001"

    def test_format_ir_renders_all_domains(self):
        ir = vir.build_verification_intent_ir(contract_record())
        text = vir.format_ir(ir)
        for name in vir.DOMAINS:
            assert name in text


# --------------------------------------------------------------------------
# CLI (real subprocess, same convention as power_intent/requirement_contract)
# --------------------------------------------------------------------------

class TestCli:
    def test_positive_cli_builds_ir_over_real_fixtures(self, tmp_path):
        req_path = tmp_path / "requirements.json"
        req_path.write_text(json.dumps([contract_record()]), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.verification_intent_ir",
             "--requirements", str(req_path), "--json"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["requirements"][0]["requirement_id"] == "REQ-PCIE-LTSSM-001"
        assert out["requirements"][0]["domain_plans"]["state_machine"]["dut_evidence_status"] \
            == vir.DUT_EVIDENCE_FOUND

    def test_negative_cli_empty_requirements_file_exits_2(self, tmp_path):
        req_path = tmp_path / "empty.json"
        req_path.write_text("[]", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.verification_intent_ir",
             "--requirements", str(req_path)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        assert proc.returncode == 2

    def test_negative_cli_unreadable_requirements_file_exits_2(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.verification_intent_ir",
             "--requirements", str(tmp_path / "does_not_exist.json")],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        assert proc.returncode == 2

    def test_negative_cli_malformed_sys_regmap_exits_2(self, tmp_path):
        req_path = tmp_path / "requirements.json"
        req_path.write_text(json.dumps([contract_record()]), encoding="utf-8")
        bad_regmap = tmp_path / "sys_regmap.json"
        bad_regmap.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.verification_intent_ir",
             "--requirements", str(req_path), "--sys-regmap", str(bad_regmap)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        assert proc.returncode == 2
