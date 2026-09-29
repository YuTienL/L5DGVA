"""Tests for dv_harness/dut_power_state_transition_graph.py.

Every fixture is small synthetic text built directly in this file, never
mined from any real vendor spec or the vendored USB_UVM_Handoff/uvm_syoscb/
ATB reference trees (per this project's No Golden-Reference Content Mining
rule) -- matching this codebase's own established convention for its sibling
extraction modules' tests.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import dut_power_state_transition_graph as psg


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


ARROW_DOC = """\
# DUT Power Management

## Power States and Transitions

D0 -> D1 (software request)
D1 -> D2: PME_TurnOff received
D2 <-> D3 on wake event

The default power state is D0.

## Unrelated Section

FOO -> BAR (this must never be extracted)
"""

FROM_TO_DOC = """\
## Power Mode Transitions

1. From ACTIVE to IDLE, triggered by idle timeout.
2. From IDLE to ACTIVE: wake event received.
"""

TABLE_DOC = """\
## Power Mode Transition Table

| From | To | Trigger |
|------|----|---------|
| D0 | D1 | Idle timeout |
| D1 | D0 | Wake event |
"""

NO_EDGE_DOC = """\
## Power State Overview

This chapter describes power management concepts at a high level.
It does not enumerate any specific state transitions here.
"""

NO_HEADING_DOC = """\
## Interrupt Handling

IRQ_A -> IRQ_B is not a power transition and must never be extracted.

## Register Map

Some register content here.
"""

CYCLE_DOC = """\
## Power States

D0 -> D1
D1 -> D2
D2 -> D0
"""


# ---------------------------------------------------------------------------
# Positive extraction paths
# ---------------------------------------------------------------------------
def test_arrow_chain_extraction_with_citations_and_default_state(tmp_path):
    src = _write(tmp_path, "power.txt", ARROW_DOC)
    report = psg.extract_power_state_transition_graph([str(src)])

    assert report["status"] == psg.STATUS_LOADED
    assert report["reason"] is None
    assert psg.GRAPH_NOT_SIMULATION_DISCLOSURE in report["disclosure"]

    edges = report["edges"]
    pairs = {(e["from_state"], e["to_state"]) for e in edges}
    assert ("D0", "D1") in pairs
    assert ("D1", "D2") in pairs
    assert ("D2", "D3") in pairs
    assert ("D3", "D2") in pairs  # bidirectional D2 <-> D3

    d0_d1 = next(e for e in edges if e["from_state"] == "D0" and e["to_state"] == "D1")
    assert d0_d1["trigger"] == "software request"
    assert d0_d1["evidence"].endswith(f"{src}:5") or "power.txt:5" in d0_d1["evidence"]

    d1_d2 = next(e for e in edges if e["from_state"] == "D1" and e["to_state"] == "D2")
    assert d1_d2["trigger"] == "PME_TurnOff received"

    d2_d3 = next(e for e in edges if e["from_state"] == "D2" and e["to_state"] == "D3")
    assert d2_d3["bidirectional_pair"] is True
    d3_d2 = next(e for e in edges if e["from_state"] == "D3" and e["to_state"] == "D2")
    assert d3_d2["bidirectional_pair"] is True
    assert d2_d3["trigger"] == "on wake event"

    # The default power-state sentence lives INSIDE the same power-state
    # section, so it must be found and cited.
    assert report["default_state"] == "D0"
    assert report["default_state_status"] == psg.DEFAULT_STATE_STATUS_DOCUMENTED
    assert report["default_state_evidence"] is not None

    # Nothing from the "Unrelated Section" heading leaks in.
    assert not any(e["from_state"] == "FOO" for e in edges)
    names = {n["name"] for n in report["nodes"]}
    assert "FOO" not in names and "BAR" not in names


def test_from_to_sentence_extraction(tmp_path):
    src = _write(tmp_path, "power.md", FROM_TO_DOC)
    report = psg.extract_power_state_transition_graph([str(src)])

    assert report["status"] == psg.STATUS_LOADED
    pairs = {(e["from_state"], e["to_state"], e["trigger"]) for e in report["edges"]}
    assert ("ACTIVE", "IDLE", "triggered by idle timeout") in pairs
    assert ("IDLE", "ACTIVE", "wake event received") in pairs


def test_table_row_extraction(tmp_path):
    src = _write(tmp_path, "power.md", TABLE_DOC)
    report = psg.extract_power_state_transition_graph([str(src)])

    assert report["status"] == psg.STATUS_LOADED
    pairs = {(e["from_state"], e["to_state"], e["trigger"]) for e in report["edges"]}
    assert ("D0", "D1", "Idle timeout") in pairs
    assert ("D1", "D0", "Wake event") in pairs


def test_multiple_sources_merge_edges(tmp_path):
    a = _write(tmp_path, "a.txt", ARROW_DOC)
    b = _write(tmp_path, "b.md", TABLE_DOC)
    report = psg.extract_power_state_transition_graph([str(a), str(b)])
    assert report["status"] == psg.STATUS_LOADED
    pairs = {(e["from_state"], e["to_state"]) for e in report["edges"]}
    assert ("D0", "D1") in pairs  # from a.txt's table-shaped edge and arrow doc both name D0->D1
    assert set(report["source"]["paths"]) == {str(a), str(b)}


# ---------------------------------------------------------------------------
# Graph facts: nodes, degree, cycle detection
# ---------------------------------------------------------------------------
def test_nodes_are_the_union_of_edge_endpoints_only(tmp_path):
    src = _write(tmp_path, "power.txt", ARROW_DOC)
    report = psg.extract_power_state_transition_graph([str(src)])
    names = {n["name"] for n in report["nodes"]}
    assert names == {"D0", "D1", "D2", "D3"}


def test_terminal_and_source_states(tmp_path):
    src = _write(tmp_path, "power.txt", ARROW_DOC)
    report = psg.extract_power_state_transition_graph([str(src)])
    # D0 has no incoming edge -> a real source state.
    assert "D0" in report["source_states"]
    # D1 has both an incoming (D0->D1) and outgoing (D1->D2) edge -> neither.
    assert "D1" not in report["source_states"]
    assert "D1" not in report["terminal_states"]


def test_cycle_detected(tmp_path):
    src = _write(tmp_path, "power.txt", CYCLE_DOC)
    report = psg.extract_power_state_transition_graph([str(src)])
    assert report["has_cycle"] is True
    assert report["example_cycle"] is not None
    assert set(report["example_cycle"][:-1]) <= {"D0", "D1", "D2"}
    # A closed cycle: first and last entries are the same state.
    assert report["example_cycle"][0] == report["example_cycle"][-1]


def test_acyclic_graph_reports_no_cycle(tmp_path):
    src = _write(tmp_path, "power.md", FROM_TO_DOC)
    report = psg.extract_power_state_transition_graph([str(src)])
    # ACTIVE <-> IDLE via two directed edges IS a real cycle (A->I->A) --
    # use the table doc instead, which is a true 2-cycle too. Build a
    # genuinely acyclic doc inline instead.
    acyclic_doc = "## Power States\n\nD0 -> D1\nD1 -> D2\n"
    src2 = _write(tmp_path, "acyclic.txt", acyclic_doc)
    report2 = psg.extract_power_state_transition_graph([str(src2)])
    assert report2["has_cycle"] is False
    assert report2["example_cycle"] is None


# ---------------------------------------------------------------------------
# Evidence Truth Rule: honest NOT_AVAILABLE at every layer, never a guess
# ---------------------------------------------------------------------------
def test_no_sources_supplied_is_not_available():
    report = psg.extract_power_state_transition_graph([])
    assert report["status"] == psg.STATUS_NOT_AVAILABLE
    assert "no source files" in report["reason"]
    assert report["edges"] == []
    assert report["nodes"] == []


def test_missing_source_file_reports_honest_reason(tmp_path):
    ghost = tmp_path / "does_not_exist.txt"
    report = psg.extract_power_state_transition_graph([str(ghost)])
    assert report["status"] == psg.STATUS_NOT_AVAILABLE
    assert ghost.name in report["reason"]


def test_no_power_heading_at_all_is_not_available_and_never_a_guessed_edge(tmp_path):
    src = _write(tmp_path, "irq.txt", NO_HEADING_DOC)
    report = psg.extract_power_state_transition_graph([str(src)])
    assert report["status"] == psg.STATUS_NOT_AVAILABLE
    assert "no heading naming a power-state" in report["reason"]
    assert report["edges"] == []
    # The negative control: IRQ_A -> IRQ_B lives under an unrelated heading
    # and must never surface as a power-state transition.
    assert not any(n["name"] in ("IRQ_A", "IRQ_B") for n in report["nodes"])


def test_heading_found_but_no_edge_shape_is_a_distinct_honest_reason(tmp_path):
    src = _write(tmp_path, "power.txt", NO_EDGE_DOC)
    report = psg.extract_power_state_transition_graph([str(src)])
    assert report["status"] == psg.STATUS_NOT_AVAILABLE
    assert "heading was found but no recognizable transition edge" in report["reason"]
    assert report["edges"] == []


def test_default_state_not_documented_is_honest(tmp_path):
    doc = "## Power States\n\nD0 -> D1\nD1 -> D0\n"
    src = _write(tmp_path, "power.txt", doc)
    report = psg.extract_power_state_transition_graph([str(src)])
    assert report["status"] == psg.STATUS_LOADED
    assert report["default_state"] is None
    assert report["default_state_status"] == psg.DEFAULT_STATE_STATUS_NOT_DOCUMENTED
    assert report["default_state_evidence"] is None


def test_disclosure_is_present_on_both_loaded_and_not_available_reports(tmp_path):
    src = _write(tmp_path, "power.txt", ARROW_DOC)
    loaded = psg.extract_power_state_transition_graph([str(src)])
    not_available = psg.extract_power_state_transition_graph([])
    assert loaded["disclosure"] == psg.GRAPH_NOT_SIMULATION_DISCLOSURE
    assert not_available["disclosure"] == psg.GRAPH_NOT_SIMULATION_DISCLOSURE
    assert "never" in psg.GRAPH_NOT_SIMULATION_DISCLOSURE.lower()
    assert "simulat" in psg.GRAPH_NOT_SIMULATION_DISCLOSURE.lower()


# ---------------------------------------------------------------------------
# Vocabulary hygiene
# ---------------------------------------------------------------------------
def test_no_verification_verdict_vocabulary_collision():
    # Re-runs the same assertion the module already performs at import time,
    # proving it is a real, currently-passing check.
    psg.assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------
def test_execute_verb_json_and_exit_code(tmp_path):
    src = _write(tmp_path, "power.txt", ARROW_DOC)
    code = psg.execute_verb(["extract", "--sources", str(src), "--json"])
    assert code == 0


def test_execute_verb_not_available_exit_code():
    code = psg.execute_verb(["extract", "--sources"])
    assert code == 2


def test_execute_verb_usage_error():
    code = psg.execute_verb([])
    assert code == 2


def test_cli_subprocess_real_run(tmp_path):
    src = _write(tmp_path, "power.txt", ARROW_DOC)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.dut_power_state_transition_graph",
         "extract", "--sources", str(src), "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert '"status": "LOADED"' in result.stdout
    assert '"has_cycle"' in result.stdout
