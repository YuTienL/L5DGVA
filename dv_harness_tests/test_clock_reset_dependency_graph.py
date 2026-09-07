"""Tests for dv_harness/clock_reset_dependency_graph.py.

Real evidence throughout: power intent is either the repo's own real
`dv_harness_tests/fixtures/power_intent/synthetic_lp_soc.upf` (explicitly
labelled a test fixture, not any real DUT's power intent, per that file's own
header) parsed by the real `power_intent.extract_power_intent()`, or small
inline synthetic UPF text built the same documented way. Clock/reset facts
are plain dicts in `env_manifest.build_dut_facts_clock_reset()`'s own real,
documented shape. Nothing here is a mock of either producer -- matching
`test_holistic_clock_reset_power_consistency.py`'s own established
convention for this same pair of real evidence sources.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import clock_reset_dependency_graph as m
from dv_harness import power_intent as pi

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_UPF = REPO_ROOT / "dv_harness_tests" / "fixtures" / "power_intent" / "synthetic_lp_soc.upf"


def _cr_facts(clocks, resets, status="LOADED", reason=None):
    return {"status": status, "reason": reason, "clocks": clocks, "resets": resets}


def _real_power_intent():
    assert SYNTHETIC_UPF.exists(), "the repo's own synthetic UPF fixture must exist"
    return pi.extract_power_intent([str(SYNTHETIC_UPF)])


# ---------------------------------------------------------------------------
# Evidence Truth Rule: absence-of-evidence honesty (required negative controls)
# ---------------------------------------------------------------------------
class TestAbsenceOfEvidence:
    def test_no_clock_reset_facts_reports_not_available_never_fabricated_clean(self):
        g = m.build_clock_reset_dependency_graph(None)
        assert g.clock_reset_topology_available is False
        assert "no clock/reset facts supplied" in g.clock_reset_topology_reason
        assert g.nodes == {}
        assert g.edges == []
        urd = g.unresolved_dependency_report()
        assert urd["status"] == m.STATUS_NOT_AVAILABLE
        assert urd["unknown_clock"] == [] and urd["not_specified"] == []

    def test_malformed_clock_reset_facts_type_reports_not_available(self):
        g = m.build_clock_reset_dependency_graph("not-a-dict")
        assert g.clock_reset_topology_available is False
        assert "not a mapping" in g.clock_reset_topology_reason

    def test_clock_reset_facts_not_loaded_status_reports_not_available(self):
        facts = _cr_facts([], [], status="NOT_AVAILABLE", reason="no soc_arch_map.json supplied")
        g = m.build_clock_reset_dependency_graph(facts)
        assert g.clock_reset_topology_available is False
        assert g.clock_reset_topology_reason == "no soc_arch_map.json supplied"

    def test_no_power_intent_reports_not_available_distinct_from_clock_reset_axis(self):
        facts = _cr_facts([{"name": "clk"}], [])
        g = m.build_clock_reset_dependency_graph(facts)
        assert g.clock_reset_topology_available is True
        assert g.power_intent_available is False
        assert "no power intent supplied" in g.power_intent_reason
        assert g.power_domain_names() == []

    def test_hand_shaped_power_intent_dict_is_refused_never_silently_accepted(self):
        facts = _cr_facts([], [])
        with pytest.raises(m.ClockResetDependencyGraphError) as ei:
            m.build_clock_reset_dependency_graph(facts, power_intent={"domains": []})
        assert ei.value.reason == "POWER_INTENT_NOT_A_REAL_POWERINTENT_INSTANCE"

    def test_no_partition_data_reports_no_partition_data_available_never_empty_clean(self):
        """The headline negative control this module exists to prove: with no
        partition/die assignment supplied, cross-partition queries must never
        return an empty-but-clean result -- that would read as 'checked, found
        none' when in fact nothing was ever checked."""
        facts = _cr_facts(
            [{"name": "clk_a"}, {"name": "clk_b"}],
            [{"name": "rst_a", "clock": "clk_a", "clock_resolved": "RESOLVED"},
             {"name": "rst_b", "clock": "clk_b", "clock_resolved": "RESOLVED"}],
        )
        g = m.build_clock_reset_dependency_graph(facts)
        assert g.partition_data_available is False
        cpd = g.cross_partition_dependencies()
        assert cpd["status"] == m.CROSS_PARTITION_STATUS_NOT_AVAILABLE
        assert cpd["cross_partition_findings"] == []
        assert "no partition/die assignment" in cpd["reason"]

        q = g.resets_in_partition_depending_on_clock_in_partition("die0", "die1")
        assert q["status"] == m.CROSS_PARTITION_STATUS_NOT_AVAILABLE
        assert q["resets"] == []

    def test_malformed_partition_assignment_type_is_refused(self):
        with pytest.raises(m.ClockResetDependencyGraphError) as ei:
            m.build_clock_reset_dependency_graph(None, partition_assignment="not-a-dict")
        assert ei.value.reason == "PARTITION_ASSIGNMENT_NOT_A_MAPPING"

    def test_malformed_domain_power_scope_type_is_refused(self):
        with pytest.raises(m.ClockResetDependencyGraphError) as ei:
            m.build_clock_reset_dependency_graph(None, domain_power_scope=["not", "a", "dict"])
        assert ei.value.reason == "DOMAIN_POWER_SCOPE_NOT_A_MAPPING"


# ---------------------------------------------------------------------------
# Node/edge construction from real facts
# ---------------------------------------------------------------------------
class TestGraphConstruction:
    def test_resolved_reset_gets_a_real_synchronizes_to_edge(self):
        facts = _cr_facts(
            [{"name": "usb_clk", "frequency_mhz": 125}],
            [{"name": "usb_rst_n", "active_level": "LOW", "clock": "usb_clk",
              "clock_resolved": "RESOLVED"}],
        )
        g = m.build_clock_reset_dependency_graph(facts)
        assert g.clock_names() == ["usb_clk"]
        assert g.reset_names() == ["usb_rst_n"]
        assert len(g.edges) == 1
        e = g.edges[0]
        assert e.kind == m.EDGE_KIND_SYNCHRONIZES_TO
        assert e.source == "usb_rst_n" and e.target == "usb_clk"

    def test_unresolved_reset_gets_no_edge(self):
        facts = _cr_facts(
            [{"name": "clk_a"}],
            [{"name": "rst_unknown", "clock": "clk_ghost", "clock_resolved": "UNKNOWN_CLOCK"},
             {"name": "rst_none", "clock": None, "clock_resolved": "NOT_SPECIFIED"}],
        )
        g = m.build_clock_reset_dependency_graph(facts)
        assert g.edges == []
        assert g.reset_names() == ["rst_none", "rst_unknown"]

    def test_malformed_clock_and_reset_entries_are_skipped_and_reported(self):
        facts = _cr_facts(
            [{"frequency_mhz": 100}, {"name": "clk_ok"}],  # first missing name
            [{"active_level": "LOW"}, {"name": "rst_ok", "clock_resolved": "NOT_SPECIFIED"}],
        )
        g = m.build_clock_reset_dependency_graph(facts)
        assert g.clock_names() == ["clk_ok"]
        assert g.reset_names() == ["rst_ok"]
        kinds = {f["kind"] for f in g.findings}
        assert "MALFORMED_CLOCK_ENTRY_SKIPPED" in kinds
        assert "MALFORMED_RESET_ENTRY_SKIPPED" in kinds

    def test_power_domain_nodes_built_from_real_power_intent(self):
        power_intent = _real_power_intent()
        g = m.build_clock_reset_dependency_graph(None, power_intent=power_intent)
        assert g.power_intent_available is True
        names = g.power_domain_names()
        assert "PD_TOP" in names and "PD_PERIPH" in names
        # PD_PERIPH is switchable (a real power switch drives it); PD_TOP is not.
        assert g.switchable_domain_ids() == ["PD_PERIPH"]
        periph = g.nodes["PD_PERIPH"]
        assert periph.attrs["elements"] == ["u_periph"]
        top = g.nodes["PD_TOP"]
        assert top.attrs["include_scope"] is True

    def test_interrupt_dma_clock_reset_extraction_shaped_dict_is_equally_real_evidence(self):
        """The module docstring's own claim: this graph is built identically
        from either of the two real producers of this shape."""
        shaped_like_extension = {
            "status": "LOADED", "reason": None,
            "clocks": [{"name": "sys_clk", "evidence": "rtl.sv:12", "description": None}],
            "resets": [{"name": "sys_rst_n", "active_level": "LOW", "synchronous": True,
                        "clock": "sys_clk", "clock_resolved": "RESOLVED",
                        "evidence": "rtl.sv:15", "description": None}],
        }
        g = m.build_clock_reset_dependency_graph(shaped_like_extension)
        assert g.clock_reset_topology_available is True
        assert g.resets_depending_on_clock("sys_clk") == ["sys_rst_n"]


# ---------------------------------------------------------------------------
# Query methods: dependency direction, reachability
# ---------------------------------------------------------------------------
class TestQueries:
    def _graph(self):
        facts = _cr_facts(
            [{"name": "clk_a"}, {"name": "clk_b"}],
            [{"name": "rst_a1", "clock": "clk_a", "clock_resolved": "RESOLVED"},
             {"name": "rst_a2", "clock": "clk_a", "clock_resolved": "RESOLVED"},
             {"name": "rst_b1", "clock": "clk_b", "clock_resolved": "RESOLVED"},
             {"name": "rst_orphan", "clock": None, "clock_resolved": "NOT_SPECIFIED"}],
        )
        return m.build_clock_reset_dependency_graph(facts)

    def test_resets_depending_on_clock(self):
        g = self._graph()
        assert g.resets_depending_on_clock("clk_a") == ["rst_a1", "rst_a2"]
        assert g.resets_depending_on_clock("clk_b") == ["rst_b1"]
        assert g.resets_depending_on_clock("clk_nonexistent") == []

    def test_clock_for_reset_resolved(self):
        g = self._graph()
        assert g.clock_for_reset("rst_a1") == {"status": "RESOLVED", "clock": "clk_a"}

    def test_clock_for_reset_not_specified_never_fabricates_a_clock(self):
        g = self._graph()
        r = g.clock_for_reset("rst_orphan")
        assert r["status"] == "NOT_SPECIFIED"
        assert r["clock"] is None

    def test_clock_for_reset_unknown_reset_name(self):
        g = self._graph()
        assert g.clock_for_reset("no_such_reset") == {"status": "RESET_NOT_FOUND", "clock": None}

    def test_traverse_backward_from_clock_reaches_its_resets(self):
        g = self._graph()
        assert g.traverse("clk_a", direction="backward") == ["rst_a1", "rst_a2"]

    def test_traverse_forward_from_reset_reaches_its_clock(self):
        g = self._graph()
        assert g.traverse("rst_a1", direction="forward") == ["clk_a"]

    def test_traverse_unknown_node_returns_empty_not_an_error(self):
        g = self._graph()
        assert g.traverse("ghost_node") == []

    def test_traverse_rejects_unknown_direction(self):
        g = self._graph()
        with pytest.raises(m.ClockResetDependencyGraphError):
            g.traverse("clk_a", direction="sideways")

    def test_traverse_through_power_domain_powers_edge(self):
        facts = _cr_facts([{"name": "clk_a"}], [])
        power_intent = _real_power_intent()
        g = m.build_clock_reset_dependency_graph(
            facts, power_intent=power_intent,
            domain_power_scope={"PD_PERIPH": ["clk_a"]},
        )
        assert g.domains_powering("clk_a") == ["PD_PERIPH"]
        assert g.traverse("PD_PERIPH", direction="forward") == ["clk_a"]
        assert g.traverse("clk_a", direction="backward") == ["PD_PERIPH"]

    def test_domain_power_scope_referencing_unknown_domain_or_node_is_reported(self):
        facts = _cr_facts([{"name": "clk_a"}], [])
        power_intent = _real_power_intent()
        g = m.build_clock_reset_dependency_graph(
            facts, power_intent=power_intent,
            domain_power_scope={"PD_GHOST": ["clk_a"], "PD_PERIPH": ["clk_ghost"]},
        )
        kinds = {f["kind"] for f in g.findings}
        assert "DOMAIN_POWER_SCOPE_REFERENCES_UNKNOWN_DOMAIN" in kinds
        assert "DOMAIN_POWER_SCOPE_REFERENCES_UNKNOWN_NODE" in kinds
        assert g.edges == []


# ---------------------------------------------------------------------------
# Unresolved-dependency report
# ---------------------------------------------------------------------------
class TestUnresolvedDependencyReport:
    def test_unknown_clock_and_not_specified_are_kept_in_separate_lists(self):
        facts = _cr_facts(
            [{"name": "clk_real"}],
            [{"name": "rst_ghost", "clock": "clk_ghost", "clock_resolved": "UNKNOWN_CLOCK"},
             {"name": "rst_none", "clock": None, "clock_resolved": "NOT_SPECIFIED"},
             {"name": "rst_ok", "clock": "clk_real", "clock_resolved": "RESOLVED"}],
        )
        g = m.build_clock_reset_dependency_graph(facts)
        urd = g.unresolved_dependency_report()
        assert urd["status"] == m.STATUS_EVALUATED
        assert urd["unknown_clock"] == ["rst_ghost"]
        assert urd["not_specified"] == ["rst_none"]
        assert urd["resolved_count"] == 1
        # never collapsed into one bucket:
        assert "rst_ghost" not in urd["not_specified"]
        assert "rst_none" not in urd["unknown_clock"]

    def test_all_resolved_reports_zero_unresolved_but_still_evaluated(self):
        facts = _cr_facts(
            [{"name": "clk_a"}],
            [{"name": "rst_a", "clock": "clk_a", "clock_resolved": "RESOLVED"}],
        )
        g = m.build_clock_reset_dependency_graph(facts)
        urd = g.unresolved_dependency_report()
        assert urd["status"] == m.STATUS_EVALUATED
        assert urd["unknown_clock"] == [] and urd["not_specified"] == []
        assert urd["resolved_count"] == 1

    def test_unrecognized_clock_resolved_value_is_never_silently_dropped(self):
        facts = _cr_facts(
            [], [{"name": "rst_weird", "clock": "x", "clock_resolved": "SOMETHING_NEW"}],
        )
        g = m.build_clock_reset_dependency_graph(facts)
        urd = g.unresolved_dependency_report()
        assert urd["other_unrecognized_status"] == [
            {"reset": "rst_weird", "clock_resolved": "SOMETHING_NEW"}]


# ---------------------------------------------------------------------------
# Multi-die / partition topology -- the genuinely new dimension
# ---------------------------------------------------------------------------
class TestPartitionTopology:
    def _cross_die_facts(self):
        return _cr_facts(
            [{"name": "clk_die0"}, {"name": "clk_die1"}],
            [{"name": "rst_die0_local", "clock": "clk_die0", "clock_resolved": "RESOLVED"},
             {"name": "rst_die1_to_die0_clk", "clock": "clk_die0", "clock_resolved": "RESOLVED"},
             {"name": "rst_die1_local", "clock": "clk_die1", "clock_resolved": "RESOLVED"}],
        )

    def _partitions(self):
        return {
            "clk_die0": "die0", "clk_die1": "die1",
            "rst_die0_local": "die0",
            "rst_die1_to_die0_clk": "die1",   # cross-die: reset lives in die1, its clock in die0
            "rst_die1_local": "die1",
        }

    def test_real_cross_partition_finding_when_partition_data_supplied(self):
        g = m.build_clock_reset_dependency_graph(
            self._cross_die_facts(), partition_assignment=self._partitions())
        assert g.partition_data_available is True
        cpd = g.cross_partition_dependencies()
        assert cpd["status"] == m.CROSS_PARTITION_STATUS_EVALUATED
        assert cpd["cross_partition_findings"] == [
            {"reset": "rst_die1_to_die0_clk", "reset_partition": "die1",
             "clock": "clk_die0", "clock_partition": "die0"}
        ]
        assert cpd["same_partition_edge_count"] == 2

    def test_named_worked_query_resets_in_partition_depending_on_clock_in_partition(self):
        g = m.build_clock_reset_dependency_graph(
            self._cross_die_facts(), partition_assignment=self._partitions())
        q = g.resets_in_partition_depending_on_clock_in_partition("die1", "die0")
        assert q["status"] == m.CROSS_PARTITION_STATUS_EVALUATED
        assert q["resets"] == ["rst_die1_to_die0_clk"]
        # the converse direction genuinely finds nothing -- not a fabricated symmetric result:
        q2 = g.resets_in_partition_depending_on_clock_in_partition("die0", "die1")
        assert q2["resets"] == []

    def test_no_cross_partition_finding_when_all_dependencies_stay_within_one_partition(self):
        facts = _cr_facts(
            [{"name": "clk_a"}],
            [{"name": "rst_a1", "clock": "clk_a", "clock_resolved": "RESOLVED"},
             {"name": "rst_a2", "clock": "clk_a", "clock_resolved": "RESOLVED"}],
        )
        g = m.build_clock_reset_dependency_graph(
            facts, partition_assignment={"clk_a": "die0", "rst_a1": "die0", "rst_a2": "die0"})
        cpd = g.cross_partition_dependencies()
        assert cpd["status"] == m.CROSS_PARTITION_STATUS_EVALUATED
        assert cpd["cross_partition_findings"] == []
        assert cpd["same_partition_edge_count"] == 2

    def test_edge_touching_a_node_with_no_declared_partition_is_reported_not_dropped(self):
        facts = _cr_facts(
            [{"name": "clk_a"}],
            [{"name": "rst_a", "clock": "clk_a", "clock_resolved": "RESOLVED"}],
        )
        # only the clock's partition is declared -- the reset's is not.
        g = m.build_clock_reset_dependency_graph(facts, partition_assignment={"clk_a": "die0"})
        cpd = g.cross_partition_dependencies()
        assert cpd["cross_partition_findings"] == []
        assert cpd["same_partition_edge_count"] == 0
        assert cpd["edges_with_unknown_partition"] == [
            {"reset": "rst_a", "clock": "clk_a", "missing_partition_for": ["reset"]}]

    def test_partition_assignment_referencing_unknown_node_is_reported(self):
        g = m.build_clock_reset_dependency_graph(
            None, partition_assignment={"clk_ghost": "die0"})
        kinds = {f["kind"] for f in g.findings}
        assert "PARTITION_ASSIGNMENT_REFERENCES_UNKNOWN_NODE" in kinds

    def test_empty_partition_assignment_dict_is_still_supplied_data_not_absence(self):
        """An explicitly-supplied empty dict is a real (if uninformative)
        caller choice, distinct from `partition_assignment=None` (never
        supplied at all) -- queries still run, they simply find every edge's
        partition unknown rather than reporting NO_PARTITION_DATA_AVAILABLE."""
        facts = _cr_facts(
            [{"name": "clk_a"}], [{"name": "rst_a", "clock": "clk_a", "clock_resolved": "RESOLVED"}])
        g = m.build_clock_reset_dependency_graph(facts, partition_assignment={})
        assert g.partition_data_available is True
        cpd = g.cross_partition_dependencies()
        assert cpd["status"] == m.CROSS_PARTITION_STATUS_EVALUATED
        assert cpd["edges_with_unknown_partition"] == [
            {"reset": "rst_a", "clock": "clk_a", "missing_partition_for": ["reset", "clock"]}]


# ---------------------------------------------------------------------------
# Serialisation / rendering
# ---------------------------------------------------------------------------
class TestSerialisationAndRendering:
    def test_to_dict_round_trips_json_serialisable(self):
        facts = _cr_facts(
            [{"name": "clk_a"}], [{"name": "rst_a", "clock": "clk_a", "clock_resolved": "RESOLVED"}])
        g = m.build_clock_reset_dependency_graph(facts, partition_assignment={"clk_a": "die0"})
        d = g.to_dict()
        json.dumps(d)  # must not raise
        assert d["clock_reset_topology_available"] is True
        assert len(d["nodes"]) == 2
        assert len(d["edges"]) == 1

    def test_render_report_markdown_never_raises_on_a_fully_absent_graph(self):
        g = m.build_clock_reset_dependency_graph(None)
        text = m.render_report_markdown(g)
        assert "NOT_AVAILABLE" in text
        assert "NO_PARTITION_DATA_AVAILABLE" in text

    def test_render_report_markdown_on_a_fully_present_graph(self):
        facts = _cr_facts(
            [{"name": "clk_a"}], [{"name": "rst_a", "clock": "clk_a", "clock_resolved": "RESOLVED"}])
        power_intent = _real_power_intent()
        g = m.build_clock_reset_dependency_graph(
            facts, power_intent=power_intent, partition_assignment={"clk_a": "die0", "rst_a": "die0"})
        text = m.render_report_markdown(g)
        assert "clk_a" in text and "rst_a" in text and "PD_PERIPH" in text


# ---------------------------------------------------------------------------
# Standalone CLI front door
# ---------------------------------------------------------------------------
class TestCli:
    def test_cli_reports_exit_2_with_no_inputs(self, tmp_path):
        empty_facts = tmp_path / "cr.json"
        empty_facts.write_text(json.dumps({"status": "NOT_AVAILABLE", "reason": "x",
                                            "clocks": [], "resets": []}))
        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.clock_reset_dependency_graph",
             "--clock-reset-facts", str(empty_facts)],
            cwd=REPO_ROOT, capture_output=True, text=True)
        assert result.returncode == 2
        assert "NOT_AVAILABLE" in result.stdout

    def test_cli_full_run_json(self, tmp_path):
        cr_path = tmp_path / "cr.json"
        cr_path.write_text(json.dumps(_cr_facts(
            [{"name": "clk_a"}], [{"name": "rst_a", "clock": "clk_a", "clock_resolved": "RESOLVED"}])))
        partition_path = tmp_path / "part.json"
        partition_path.write_text(json.dumps({"clk_a": "die0", "rst_a": "die0"}))

        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.clock_reset_dependency_graph",
             "--clock-reset-facts", str(cr_path),
             "--upf", str(SYNTHETIC_UPF),
             "--partition-assignment", str(partition_path),
             "--json"],
            cwd=REPO_ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["clock_reset_topology_available"] is True
        assert payload["power_intent_available"] is True
        assert payload["partition_data_available"] is True
        node_ids = {n["node_id"] for n in payload["nodes"]}
        assert {"clk_a", "rst_a", "PD_TOP", "PD_PERIPH"} <= node_ids

    def test_cli_malformed_upf_free_no_args_usage(self, tmp_path):
        # No clock-reset-facts and no upf supplied at all: honest NOT_AVAILABLE, exit 2.
        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.clock_reset_dependency_graph"],
            cwd=REPO_ROOT, capture_output=True, text=True)
        assert result.returncode == 2
