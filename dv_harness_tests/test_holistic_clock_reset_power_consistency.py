"""Tests for dv_harness/holistic_clock_reset_power_consistency.py.

Real evidence throughout: `power_intent` fixtures are either the repo's own
real `dv_harness_tests/fixtures/power_intent/synthetic_lp_soc.upf` (explicitly
labelled a test fixture, not any real DUT's power intent, per that file's own
header) or small inline synthetic UPF text built the same way that fixture
was -- ordinary IEEE-1801 UPF constructs, parsed by the real
`power_intent.parse_upf_text()`. Clock/reset topology facts are plain dicts in
`env_manifest.build_dut_facts_clock_reset()`'s own real, documented shape.
Nothing here is a mock of either producer.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import holistic_clock_reset_power_consistency as m
from dv_harness import power_intent as pi

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_UPF = REPO_ROOT / "dv_harness_tests" / "fixtures" / "power_intent" / "synthetic_lp_soc.upf"


def _cr_facts(clocks, resets):
    return {
        "status": "LOADED",
        "source": {"kind": "test"},
        "reason": None,
        "clocks": clocks,
        "resets": resets,
    }


# ---------------------------------------------------------------------------
# Absence-of-evidence honesty (the required negative controls)
# ---------------------------------------------------------------------------
class TestAbsenceOfEvidence:
    def test_no_bind_entries_reports_not_available(self):
        r = m.build_holistic_consistency_report([])
        assert r["status"] == m.STATUS_NOT_AVAILABLE
        assert r["clock_reset_topology_available"] is False
        assert r["power_intent_available"] is False
        assert r["findings"] == []

    def test_no_bind_entries_none_reports_not_available(self):
        r = m.build_holistic_consistency_report(None)
        assert r["status"] == m.STATUS_NOT_AVAILABLE

    def test_no_topology_evidence_never_fabricates_topology_or_power_findings(self):
        """The headline negative control: with neither clock/reset facts nor a
        real PowerIntent supplied, every check that NEEDS that evidence must
        be silently absent from the findings list -- never a guessed answer."""
        binds = [
            {"target_instance": "u_top.blk", "ports": ["usb_clk", "usb_rst_n", "data"],
             "reason": "r1"},
        ]
        r = m.build_holistic_consistency_report(binds)
        assert r["clock_reset_topology_available"] is False
        assert r["power_intent_available"] is False
        codes = {f["code"] for f in r["findings"]}
        forbidden = {
            m.CODE_POWER_DOMAIN_RESET_SET_INCONSISTENT,
            m.CODE_SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION,
            m.CODE_BIND_TARGET_NOT_IN_ANY_DECLARED_POWER_DOMAIN,
            m.CODE_CLOCK_DOMAIN_NOT_EXERCISED_BY_ANY_BIND,
            m.CODE_RESET_CLOCK_UNRESOLVED_REFERENCED_BY_BIND,
            m.CODE_BIND_PORT_NOT_IN_DECLARED_TOPOLOGY,
        }
        assert not (codes & forbidden)
        assert r["status"] == m.STATUS_CONSISTENT
        assert r["reason"] is not None and "only the bind entries" in r["reason"]
        assert r["power_domain_membership"] == {}
        assert r["clock_domain_coverage"] == {}


# ---------------------------------------------------------------------------
# Per-bind structural checks (no topology required)
# ---------------------------------------------------------------------------
class TestBindStructuralChecks:
    def test_bind_with_recognizable_clock_and_reset_is_consistent(self):
        binds = [{"target_instance": "u_top.blk", "ports": ["clk", "rst_n", "data"],
                  "reason": "r"}]
        r = m.build_holistic_consistency_report(binds)
        assert r["status"] == m.STATUS_CONSISTENT
        assert r["bind_resolution"][0]["clock"]["status"] == "RESOLVED"
        assert r["bind_resolution"][0]["reset"]["status"] == "RESOLVED"

    def test_bind_missing_clock_and_reset_flags_warning(self):
        binds = [{"target_instance": "u_top.blk", "ports": ["data", "valid"], "reason": "r"}]
        r = m.build_holistic_consistency_report(binds)
        codes = [f["code"] for f in r["findings"]]
        assert m.CODE_BIND_MISSING_CLOCK_OR_RESET_PORT in codes
        assert r["status"] == m.STATUS_INCONSISTENCIES_FOUND
        finding = next(f for f in r["findings"]
                       if f["code"] == m.CODE_BIND_MISSING_CLOCK_OR_RESET_PORT)
        assert set(finding["evidence"]["missing"]) == {"clock", "reset"}

    def test_malformed_bind_entry_is_skipped_and_reported_not_crashed(self):
        binds = [
            {"target_instance": "u_top.a"},  # missing ports
            {"ports": ["clk", "rst_n"]},      # missing target_instance
            {"target_instance": "u_top.b", "ports": ["clk", "rst_n"], "reason": "ok"},
        ]
        r = m.build_holistic_consistency_report(binds)
        malformed = [f for f in r["findings"] if f["code"] == m.CODE_BIND_ENTRY_MALFORMED]
        assert len(malformed) == 2
        assert len(r["bind_resolution"]) == 1
        assert r["bind_resolution"][0]["target_instance"] == "u_top.b"

    def test_non_mapping_bind_entry_is_skipped_and_reported_not_crashed(self):
        binds = ["not-a-dict", {"target_instance": "u.b", "ports": ["clk", "rst_n"], "reason": "r"}]
        r = m.build_holistic_consistency_report(binds)
        assert len(r["bind_resolution"]) == 1
        assert any(f["code"] == m.CODE_BIND_ENTRY_MALFORMED for f in r["findings"])


# ---------------------------------------------------------------------------
# Clock/reset topology cross-checks
# ---------------------------------------------------------------------------
class TestClockResetTopologyChecks:
    def test_bind_port_not_in_declared_topology_is_info(self):
        facts = _cr_facts(
            clocks=[{"name": "sys_clk", "frequency_mhz": 100, "domain": None, "evidence": "e"}],
            resets=[{"name": "sys_rst_n", "active_level": "LOW", "synchronous": False,
                     "clock": "sys_clk", "clock_resolved": "RESOLVED", "evidence": "e"}],
        )
        binds = [{"target_instance": "u_top.blk", "ports": ["local_clk", "local_rst_n", "d"],
                  "reason": "r"}]
        r = m.build_holistic_consistency_report(binds, clock_reset_facts=facts)
        codes = [f["code"] for f in r["findings"]]
        assert codes.count(m.CODE_BIND_PORT_NOT_IN_DECLARED_TOPOLOGY) == 2  # clock + reset
        # INFO-only findings never flip the overall verdict -- this is a
        # disclosed heuristic observation, not an asserted defect.
        assert r["status"] == m.STATUS_CONSISTENT
        assert all(f["severity"] == m.SEVERITY_INFO for f in r["findings"])

    def test_clock_domain_not_exercised_by_any_bind(self):
        facts = _cr_facts(
            clocks=[{"name": "sys_clk", "frequency_mhz": 100, "domain": None, "evidence": "e"},
                    {"name": "unused_clk", "frequency_mhz": 50, "domain": None, "evidence": "e"}],
            resets=[{"name": "sys_rst_n", "active_level": "LOW", "synchronous": False,
                     "clock": "sys_clk", "clock_resolved": "RESOLVED", "evidence": "e"}],
        )
        binds = [{"target_instance": "u_top.blk", "ports": ["sys_clk", "sys_rst_n", "d"],
                  "reason": "r"}]
        r = m.build_holistic_consistency_report(binds, clock_reset_facts=facts)
        gap = [f for f in r["findings"] if f["code"] == m.CODE_CLOCK_DOMAIN_NOT_EXERCISED_BY_ANY_BIND]
        assert len(gap) == 1
        assert gap[0]["evidence"]["clock"] == "unused_clk"
        assert r["clock_domain_coverage"]["sys_clk"]["exercised_by_any_bind"] is True
        assert r["clock_domain_coverage"]["unused_clk"]["exercised_by_any_bind"] is False

    def test_clock_exercised_through_dependent_reset_not_direct_reference(self):
        """A bind whose CLOCK port is unrecognisable but whose RESET is a real
        declared reset still counts as exercising that reset's own clock --
        the dependency-graph edge (reset -> clock) is followed, not just a
        direct clock-port match."""
        facts = _cr_facts(
            clocks=[{"name": "sys_clk", "frequency_mhz": 100, "domain": None, "evidence": "e"}],
            resets=[{"name": "sys_rst_n", "active_level": "LOW", "synchronous": False,
                     "clock": "sys_clk", "clock_resolved": "RESOLVED", "evidence": "e"}],
        )
        binds = [{"target_instance": "u_top.blk", "ports": ["opaque_clk_name", "sys_rst_n", "d"],
                  "reason": "r"}]
        r = m.build_holistic_consistency_report(binds, clock_reset_facts=facts)
        assert r["clock_domain_coverage"]["sys_clk"]["exercised_by_any_bind"] is True

    def test_reset_clock_unresolved_referenced_by_bind(self):
        facts = _cr_facts(
            clocks=[{"name": "sys_clk", "frequency_mhz": 100, "domain": None, "evidence": "e"}],
            resets=[{"name": "orphan_rst_n", "active_level": "LOW", "synchronous": False,
                     "clock": None, "clock_resolved": "NOT_SPECIFIED", "evidence": "e:9"}],
        )
        binds = [{"target_instance": "u_top.blk", "ports": ["sys_clk", "orphan_rst_n", "d"],
                  "reason": "r"}]
        r = m.build_holistic_consistency_report(binds, clock_reset_facts=facts)
        found = [f for f in r["findings"]
                if f["code"] == m.CODE_RESET_CLOCK_UNRESOLVED_REFERENCED_BY_BIND]
        assert len(found) == 1
        assert found[0]["evidence"]["reset"] == "orphan_rst_n"
        assert found[0]["evidence"]["clock_resolved"] == "NOT_SPECIFIED"


# ---------------------------------------------------------------------------
# Whole-power-domain group checks (never pairwise)
# ---------------------------------------------------------------------------
class TestPowerDomainGroupChecks:
    def test_switchable_domain_with_isolation_never_flags_error(self):
        intent = pi.extract_power_intent([str(SYNTHETIC_UPF)])
        facts = _cr_facts(
            clocks=[{"name": "sys_clk", "frequency_mhz": 100, "domain": None, "evidence": "e"}],
            resets=[{"name": "periph_rst_n", "active_level": "LOW", "synchronous": False,
                     "clock": "sys_clk", "clock_resolved": "RESOLVED", "evidence": "e"}],
        )
        binds = [{"target_instance": "u_periph.blk_a",
                  "ports": ["sys_clk", "periph_rst_n", "d"], "reason": "r"}]
        r = m.build_holistic_consistency_report(binds, clock_reset_facts=facts, power_intent=intent)
        assert m.CODE_SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION not in [f["code"] for f in r["findings"]]
        assert r["power_domain_membership"]["PD_PERIPH"]["switchable"] is True
        assert r["power_domain_membership"]["PD_PERIPH"]["isolated"] is True
        assert r["power_domain_membership"]["PD_PERIPH"]["bind_targets"] == ["u_periph.blk_a"]

    def test_switchable_domain_without_isolation_flags_error_for_every_member(self):
        upf_text = """
upf_version 2.1
set_design_top test_top
create_power_domain PD_A -elements {u_blk}
create_supply_port VDD -domain PD_A -direction in
create_supply_net VDD -domain PD_A
set_domain_supply_net PD_A -primary_power_net VDD
create_power_switch sw_a -domain PD_A \\
    -input_supply_port {vin VDD} -output_supply_port {vout VDD_SW} \\
    -control_port {en en_sig} -on_state {on_state vin {en}}
"""
        intent = pi.parse_upf_text(upf_text, file_label="<inline_test_fixture>")
        assert "PD_A" in intent.switchable_domains()
        binds = [
            {"target_instance": "u_blk.sub1", "ports": ["clk", "rst_n", "d"], "reason": "r1"},
            {"target_instance": "u_blk.sub2", "ports": ["clk", "rst_n", "d"], "reason": "r2"},
        ]
        r = m.build_holistic_consistency_report(binds, power_intent=intent)
        found = [f for f in r["findings"]
                if f["code"] == m.CODE_SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION]
        assert len(found) == 1  # ONE finding for the whole GROUP, not one per bind
        assert set(found[0]["evidence"]["bind_targets"]) == {"u_blk.sub1", "u_blk.sub2"}
        assert r["status"] == m.STATUS_INCONSISTENCIES_FOUND

    def test_reset_set_inconsistent_within_one_power_domain_group(self):
        intent = pi.extract_power_intent([str(SYNTHETIC_UPF)])
        facts = _cr_facts(
            clocks=[{"name": "sys_clk", "frequency_mhz": 100, "domain": None, "evidence": "e"}],
            resets=[
                {"name": "sys_rst_n", "active_level": "LOW", "synchronous": False,
                 "clock": "sys_clk", "clock_resolved": "RESOLVED", "evidence": "e"},
                {"name": "periph_rst_n", "active_level": "LOW", "synchronous": False,
                 "clock": "sys_clk", "clock_resolved": "RESOLVED", "evidence": "e"},
            ],
        )
        binds = [
            {"target_instance": "u_periph.blk_a", "ports": ["sys_clk", "sys_rst_n", "d"],
             "reason": "r1"},
            {"target_instance": "u_periph.blk_b", "ports": ["sys_clk", "periph_rst_n", "d"],
             "reason": "r2"},
        ]
        r = m.build_holistic_consistency_report(binds, clock_reset_facts=facts, power_intent=intent)
        found = [f for f in r["findings"]
                if f["code"] == m.CODE_POWER_DOMAIN_RESET_SET_INCONSISTENT]
        assert len(found) == 1
        assert set(found[0]["evidence"]["reset_names"]) == {"sys_rst_n", "periph_rst_n"}
        assert sorted(r["power_domain_membership"]["PD_PERIPH"]["reset_names_used"]) == \
            ["periph_rst_n", "sys_rst_n"]

    def test_single_reset_name_within_domain_group_never_flags(self):
        intent = pi.extract_power_intent([str(SYNTHETIC_UPF)])
        facts = _cr_facts(
            clocks=[{"name": "sys_clk", "frequency_mhz": 100, "domain": None, "evidence": "e"}],
            resets=[{"name": "periph_rst_n", "active_level": "LOW", "synchronous": False,
                     "clock": "sys_clk", "clock_resolved": "RESOLVED", "evidence": "e"}],
        )
        binds = [
            {"target_instance": "u_periph.blk_a", "ports": ["sys_clk", "periph_rst_n", "d"],
             "reason": "r1"},
            {"target_instance": "u_periph.blk_b", "ports": ["sys_clk", "periph_rst_n", "d"],
             "reason": "r2"},
        ]
        r = m.build_holistic_consistency_report(binds, clock_reset_facts=facts, power_intent=intent)
        assert m.CODE_POWER_DOMAIN_RESET_SET_INCONSISTENT not in [f["code"] for f in r["findings"]]

    def test_domain_with_no_bind_members_produces_no_group_findings(self):
        intent = pi.extract_power_intent([str(SYNTHETIC_UPF)])
        binds = [{"target_instance": "somewhere_else.blk", "ports": ["clk", "rst_n", "d"],
                  "reason": "r"}]
        r = m.build_holistic_consistency_report(binds, power_intent=intent)
        assert r["power_domain_membership"]["PD_PERIPH"]["bind_targets"] == []
        assert m.CODE_SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION not in [f["code"] for f in r["findings"]]

    def test_include_scope_domain_without_elements_never_matched(self):
        """PD_TOP is declared with -include_scope and no explicit -elements in
        the real fixture -- this module must never guess broad coverage from
        an absent element list (Evidence Truth Rule)."""
        intent = pi.extract_power_intent([str(SYNTHETIC_UPF)])
        pd_top = intent.domain("PD_TOP")
        assert pd_top.include_scope is True
        assert pd_top.elements == []
        assert m.domains_for_instance("anything.at.all", intent.domains) == []

    def test_bind_target_not_in_any_declared_power_domain_is_info(self):
        intent = pi.extract_power_intent([str(SYNTHETIC_UPF)])
        binds = [{"target_instance": "unrelated_top.other_blk",
                  "ports": ["clk", "rst_n", "d"], "reason": "r"}]
        r = m.build_holistic_consistency_report(binds, power_intent=intent)
        found = [f for f in r["findings"]
                if f["code"] == m.CODE_BIND_TARGET_NOT_IN_ANY_DECLARED_POWER_DOMAIN]
        assert len(found) == 1
        assert found[0]["evidence"]["target_instance"] == "unrelated_top.other_blk"

    def test_power_intent_with_no_domains_never_flags_membership(self):
        intent = pi.PowerIntent()  # a real, empty PowerIntent -- no domains declared
        binds = [{"target_instance": "u_top.blk", "ports": ["clk", "rst_n", "d"], "reason": "r"}]
        r = m.build_holistic_consistency_report(binds, power_intent=intent)
        assert m.CODE_BIND_TARGET_NOT_IN_ANY_DECLARED_POWER_DOMAIN not in \
            [f["code"] for f in r["findings"]]
        assert r["power_domain_membership"] == {}


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
class TestInputValidation:
    def test_power_intent_must_be_a_real_powerintent_instance(self):
        with pytest.raises(m.HolisticClockResetPowerConsistencyError) as exc:
            m.build_holistic_consistency_report(
                [{"target_instance": "u.blk", "ports": ["clk", "rst_n"], "reason": "r"}],
                power_intent={"domains": []},
            )
        assert exc.value.reason == "POWER_INTENT_NOT_A_REAL_POWERINTENT_INSTANCE"


# ---------------------------------------------------------------------------
# Vocabulary hygiene
# ---------------------------------------------------------------------------
class TestVocabulary:
    def test_import_time_guard_does_not_raise_on_the_real_vocabulary(self):
        m.assert_no_verification_verdict_vocabulary()  # must not raise

    def test_guard_has_real_detection_power(self, monkeypatch):
        monkeypatch.setattr(m, "OVERALL_STATUSES", ("PASS",))  # a real Status member
        with pytest.raises(AssertionError):
            m.assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
class TestRendering:
    def test_render_report_markdown_smoke(self):
        binds = [{"target_instance": "u.blk", "ports": ["data"], "reason": "r"}]
        r = m.build_holistic_consistency_report(binds)
        text = m.render_report_markdown(r)
        assert "Holistic Clock/Reset/Power Consistency" in text
        assert m.CODE_BIND_MISSING_CLOCK_OR_RESET_PORT in text

    def test_render_report_markdown_empty_findings_note(self):
        r = m.build_holistic_consistency_report([])
        text = m.render_report_markdown(r)
        assert "no findings" in text or "NOT_AVAILABLE" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _run_cli(args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.holistic_clock_reset_power_consistency", *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )


class TestCli:
    def test_cli_consistent_exit_zero(self, tmp_path):
        binds = tmp_path / "binds.json"
        binds.write_text(json.dumps(
            [{"target_instance": "u.blk", "ports": ["clk", "rst_n", "d"], "reason": "r"}]))
        proc = _run_cli(["--bind-entries", str(binds), "--json"])
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["status"] == "CONSISTENT"

    def test_cli_inconsistencies_found_exit_one(self, tmp_path):
        binds = tmp_path / "binds.json"
        binds.write_text(json.dumps(
            [{"target_instance": "u.blk", "ports": ["data"], "reason": "r"}]))
        proc = _run_cli(["--bind-entries", str(binds), "--json"])
        assert proc.returncode == 1, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["status"] == "INCONSISTENCIES_FOUND"

    def test_cli_not_available_exit_two(self, tmp_path):
        binds = tmp_path / "binds.json"
        binds.write_text(json.dumps([]))
        proc = _run_cli(["--bind-entries", str(binds), "--json"])
        assert proc.returncode == 2, proc.stderr

    def test_cli_reads_real_upf_and_clock_reset_facts_end_to_end(self, tmp_path):
        binds = tmp_path / "binds.json"
        binds.write_text(json.dumps([
            {"target_instance": "u_blk.sub1", "ports": ["clk", "rst_n", "d"], "reason": "r1"},
        ]))
        cr = tmp_path / "cr.json"
        cr.write_text(json.dumps(_cr_facts(
            clocks=[{"name": "clk", "frequency_mhz": 100, "domain": None, "evidence": "e"}],
            resets=[{"name": "rst_n", "active_level": "LOW", "synchronous": False,
                     "clock": "clk", "clock_resolved": "RESOLVED", "evidence": "e"}],
        )))
        upf = tmp_path / "no_iso.upf"
        upf.write_text(
            "upf_version 2.1\n"
            "set_design_top test_top\n"
            "create_power_domain PD_A -elements {u_blk}\n"
            "create_supply_port VDD -domain PD_A -direction in\n"
            "create_supply_net VDD -domain PD_A\n"
            "set_domain_supply_net PD_A -primary_power_net VDD\n"
            "create_power_switch sw_a -domain PD_A "
            "-input_supply_port {vin VDD} -output_supply_port {vout VDD_SW} "
            "-control_port {en en_sig} -on_state {on_state vin {en}}\n"
        )
        proc = _run_cli([
            "--bind-entries", str(binds), "--clock-reset-facts", str(cr),
            "--upf", str(upf), "--json",
        ])
        assert proc.returncode == 1, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["power_intent_available"] is True
        codes = [f["code"] for f in payload["findings"]]
        assert m.CODE_SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION in codes

    def test_cli_missing_bind_entries_file_exits_two(self, tmp_path):
        proc = _run_cli(["--bind-entries", str(tmp_path / "nope.json")])
        assert proc.returncode == 2
