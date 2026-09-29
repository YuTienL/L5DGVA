"""Tests for tools/observability/generate_observability_plan.py's ASSERTION
branch wiring to the state_machine_checks DSL (checker-sva-generator task,
2026-09-01, see .work/checker-sva-generator-design-report.md).

Confirmed gap before this task (this script's own original source): the
ASSERTION branch emitted a literal, unconditional
`1'b1; // TODO: replace with evidence-backed temporal property` for EVERY
target, regardless of content -- zero generation mechanics.

Groups:
  - backward compatibility: a plan with no "state_machine_check" opt-in on
    any ASSERTION mechanism produces the exact original TODO-placeholder SV
    text, byte-identical to before this task, plus a "placeholder"
    generation_method/assertion_entries row
  - opt-in: an ASSERTION mechanism carrying "state_machine_check" compiles
    to a real property/assert via state_machine_checks.emit_check(),
    recorded with a "state_machine_checks_dsl:<kind>" generation_method
  - classification propagation: the mechanism's own "classification" field
    is carried through verbatim into implementation_manifest.json
  - clocks/resets plan-level fields are honored the same way
    generator.py's tb_top() honors them
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "observability" / "generate_observability_plan.py"


def _run_plan(plan: dict):
    tmp = Path(tempfile.mkdtemp())
    plan_path = tmp / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    out_dir = tmp / "out"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--plan", str(plan_path), "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assertions_text = (out_dir / "generated_assertions.sv").read_text(encoding="utf-8")
    manifest = json.loads((out_dir / "implementation_manifest.json").read_text(encoding="utf-8"))
    return assertions_text, manifest


def _placeholder_only_plan():
    return {
        "targets": [
            {"target_id": "OBS-001", "recommended_mechanisms": [
                {"type": "ASSERTION", "purpose": "local handshake invariant",
                 "placement": "boundary X"},
            ]},
        ],
    }


def test_placeholder_only_plan_produces_byte_identical_todo_text():
    assertions_text, manifest = _run_plan(_placeholder_only_plan())
    assert (
        "// obs_001: local handshake invariant\n"
        "// Placement: boundary X\n"
        "property obs_001_property;\n"
        "  @(posedge clk) disable iff (!rst_n)\n"
        "    1'b1; // TODO: replace with evidence-backed temporal property\n"
        "endproperty\n"
        "obs_001_assert: assert property (obs_001_property);\n"
    ) in assertions_text
    assert manifest["assertions"] == 1
    assert manifest["assertion_entries"] == [
        {"target_id": "obs_001", "generation_method": "placeholder", "classification": None},
    ]


def _state_machine_check_plan():
    return {
        "targets": [
            {"target_id": "OBS-002", "recommended_mechanisms": [
                {"type": "ASSERTION", "purpose": "LTSSM transition legality",
                 "placement": "PCIe LTSSM boundary",
                 "classification": "PROTOCOL_STATE_MACHINE_LEGALITY",
                 "state_machine_check": {
                     "kind": "valid_transition_table",
                     "evidence": "illustrative, generalized from pcie_ltssm_generator.py",
                     "state_signal": "ltssm_state",
                     "states": ["DETECT", "POLLING"],
                     "transitions": {"DETECT": ["POLLING"], "POLLING": ["DETECT"]},
                 }},
            ]},
        ],
    }


def test_state_machine_check_opt_in_compiles_real_property():
    assertions_text, manifest = _run_plan(_state_machine_check_plan())
    assert "1'b1; // TODO" not in assertions_text
    assert "obs_002_a: assert property (obs_002_p)" in assertions_text
    assert "function automatic bit obs_002_transition_legal(" in assertions_text
    assert manifest["assertion_entries"] == [
        {"target_id": "obs_002", "generation_method": "state_machine_checks_dsl:valid_transition_table",
         "classification": "PROTOCOL_STATE_MACHINE_LEGALITY"},
    ]


def test_state_machine_check_reuses_plan_level_clocks_and_resets():
    plan = _state_machine_check_plan()
    plan["clocks"] = [{"name": "pclk"}]
    plan["resets"] = [{"name": "presetn"}]
    assertions_text, _ = _run_plan(plan)
    assert "@(posedge pclk) disable iff (!presetn)" in assertions_text


def test_mixed_plan_keeps_placeholder_entry_untouched_and_adds_real_one():
    plan = _placeholder_only_plan()
    plan["targets"].append(_state_machine_check_plan()["targets"][0])
    assertions_text, manifest = _run_plan(plan)
    assert "obs_001_assert: assert property (obs_001_property);" in assertions_text
    assert "obs_002_a: assert property (obs_002_p)" in assertions_text
    methods = {e["target_id"]: e["generation_method"] for e in manifest["assertion_entries"]}
    assert methods == {
        "obs_001": "placeholder",
        "obs_002": "state_machine_checks_dsl:valid_transition_table",
    }
