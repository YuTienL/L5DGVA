"""Tests for dv_harness/system_scoreboard_ir.py.

Real, no-mock unit tests over the module's own public functions, plus the
real `python -m dv_harness.system_scoreboard_ir` CLI driven as an actual
subprocess for the front-door tests. No filesystem/network dependency in
the core classifier -- everything is built from plain in-memory dicts, the
same shape a real caller would hand in from its own evidence.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.scoreboard_placement_scope import (
    SCOPE_BLOCK_LOCAL,
    SCOPE_CROSS_PORT,
    SCOPE_DMA_PATH,
    SCOPE_END_TO_END,
    SCOPE_INTERRUPT_PATH,
    SCOPE_MEMORY_PATH,
    SCOPE_PORT_LOCAL,
    SCOPE_VALUES,
    STATUS_CLASSIFIED,
    STATUS_DEFAULTED,
    STATUS_UNVERIFIABLE,
)
from dv_harness.system_scoreboard_ir import (
    COMPOSITION_CONTRADICTION,
    COMPOSITION_COVERED,
    COMPOSITION_GAP,
    COMPOSITION_UNVERIFIABLE,
    OVERALL_COMPLETE,
    OVERALL_INCOMPLETE,
    OVERALL_NOT_APPLICABLE,
    SystemScoreboardIRError,
    assert_no_verification_verdict_vocabulary,
    build_system_scoreboard_ir,
    classify_existing_scoreboard,
    classify_system_interaction_requirement,
    known_scope_values,
    render_system_scoreboard_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ===========================================================================
# Reuse of scoreboard_placement_scope.py's taxonomy
# ===========================================================================

def test_known_scope_values_is_the_real_8_value_taxonomy():
    assert known_scope_values() == SCOPE_VALUES
    assert len(known_scope_values()) == 8


def test_vocabulary_collision_guard_passes_for_real_models_status():
    # Must not raise -- this module's own tokens genuinely do not collide
    # with dv_harness.models.Status today.
    assert_no_verification_verdict_vocabulary() is None


# ===========================================================================
# classify_system_interaction_requirement() / classify_existing_scoreboard()
# ===========================================================================

def test_classify_interaction_requirement_dma_path():
    subsystems, cls = classify_system_interaction_requirement({
        "interaction_id": "usb0_pcie0_dma",
        "subsystems": ["usb0", "pcie0"],
        "evidence": "shared DMA engine per SoC integration doc section 4.2",
        "spans_dma_engine": True,
    })
    assert subsystems == ["usb0", "pcie0"]
    assert cls.status == STATUS_CLASSIFIED
    assert cls.scope == SCOPE_DMA_PATH


def test_classify_interaction_requirement_no_scope_fact_is_unverifiable():
    subsystems, cls = classify_system_interaction_requirement({
        "interaction_id": "usb0_pcie0_unknown",
        "subsystems": ["usb0", "pcie0"],
        "evidence": "the two subsystems are known to interact but nothing about the compare scope is on file",
    })
    assert subsystems == ["usb0", "pcie0"]
    assert cls.status == STATUS_UNVERIFIABLE
    assert cls.scope is None


def test_classify_interaction_requires_interaction_id():
    with pytest.raises(SystemScoreboardIRError, match="interaction_id"):
        classify_system_interaction_requirement({
            "subsystems": ["usb0", "pcie0"],
            "evidence": "x",
        })


def test_classify_interaction_requires_at_least_two_subsystems():
    with pytest.raises(SystemScoreboardIRError, match="at least 2"):
        classify_system_interaction_requirement({
            "interaction_id": "solo",
            "subsystems": ["usb0"],
            "evidence": "x",
        })


def test_classify_interaction_requires_evidence():
    with pytest.raises(SystemScoreboardIRError, match="evidence"):
        classify_system_interaction_requirement({
            "interaction_id": "usb0_pcie0",
            "subsystems": ["usb0", "pcie0"],
            "spans_dma_engine": True,
        })


def test_classify_interaction_rejects_non_dict():
    with pytest.raises(SystemScoreboardIRError, match="dict"):
        classify_system_interaction_requirement("not-a-dict")  # type: ignore[arg-type]


def test_classify_interaction_propagates_malformed_scope_facts():
    # port_count as a string is a real ScoreboardPlacementScopeError,
    # propagated (wrapped) rather than silently coerced or swallowed.
    with pytest.raises(SystemScoreboardIRError, match="port_count"):
        classify_system_interaction_requirement({
            "interaction_id": "usb0_pcie0",
            "subsystems": ["usb0", "pcie0"],
            "evidence": "x",
            "port_count": "two",
        })


def test_classify_existing_scoreboard_end_to_end():
    sb_id, owning, cls = classify_existing_scoreboard({
        "scoreboard_id": "sb_soc_e2e",
        "owning_subsystems": ["usb0", "pcie0", "ddr0"],
        "evidence": "generated at examples/generated_soc_env/tb/sb_soc_e2e.sv",
        "spans_end_to_end_stimulus_to_system_effect": True,
    })
    assert sb_id == "sb_soc_e2e"
    assert owning == ["usb0", "pcie0", "ddr0"]
    assert cls.scope == SCOPE_END_TO_END


def test_classify_existing_scoreboard_allows_a_single_owning_subsystem():
    # A per-subsystem-local scoreboard is a legal existing_scoreboards
    # entry too (it just will not cover a genuine cross-subsystem gap).
    sb_id, owning, cls = classify_existing_scoreboard({
        "scoreboard_id": "sb_usb0_local",
        "owning_subsystems": ["usb0"],
        "evidence": "per-subsystem scoreboard from the USB0 environment",
        "block_local": True,
    })
    assert owning == ["usb0"]
    assert cls.scope == SCOPE_BLOCK_LOCAL


def test_classify_existing_scoreboard_requires_scoreboard_id():
    with pytest.raises(SystemScoreboardIRError, match="scoreboard_id"):
        classify_existing_scoreboard({
            "owning_subsystems": ["usb0"],
            "evidence": "x",
        })


def test_classify_existing_scoreboard_requires_evidence():
    with pytest.raises(SystemScoreboardIRError, match="evidence"):
        classify_existing_scoreboard({
            "scoreboard_id": "sb1",
            "owning_subsystems": ["usb0"],
            "declared_scope": SCOPE_BLOCK_LOCAL,
        })


# ===========================================================================
# build_system_scoreboard_ir() -- the composition question
# ===========================================================================

def test_no_interactions_declared_is_not_applicable():
    ir = build_system_scoreboard_ir([])
    assert ir.overall_status == OVERALL_NOT_APPLICABLE
    assert ir.entries == []
    assert "no system_interactions" in ir.overall_reason


def test_none_interactions_is_also_not_applicable():
    ir = build_system_scoreboard_ir(None)
    assert ir.overall_status == OVERALL_NOT_APPLICABLE


def test_single_interaction_covered_by_end_to_end_scoreboard():
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "usb0_pcie0_dma",
            "subsystems": ["usb0", "pcie0"],
            "evidence": "shared DMA engine",
            "spans_dma_engine": True,
        }],
        existing_scoreboards=[{
            "scoreboard_id": "sb_soc_e2e",
            "owning_subsystems": ["usb0", "pcie0", "ddr0"],
            "evidence": "generated SoC-level scoreboard",
            "spans_end_to_end_stimulus_to_system_effect": True,
        }],
    )
    assert ir.overall_status == OVERALL_COMPLETE
    assert len(ir.entries) == 1
    entry = ir.entries[0]
    assert entry.composition_status == COMPOSITION_COVERED
    assert entry.needs_cross_subsystem_scoreboard is True
    assert entry.required_scope == SCOPE_DMA_PATH
    assert entry.covering_scoreboard_ids == ["sb_soc_e2e"]


def test_single_interaction_covered_by_exact_scope_match():
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "usb0_pcie0_dma",
            "subsystems": ["usb0", "pcie0"],
            "evidence": "shared DMA engine",
            "spans_dma_engine": True,
        }],
        existing_scoreboards=[{
            "scoreboard_id": "sb_dma_path",
            "owning_subsystems": ["usb0", "pcie0"],
            "evidence": "generated DMA-path scoreboard",
            "declared_scope": SCOPE_DMA_PATH,
        }],
    )
    assert ir.overall_status == OVERALL_COMPLETE
    assert ir.entries[0].composition_status == COMPOSITION_COVERED
    assert ir.entries[0].covering_scoreboard_ids == ["sb_dma_path"]


def test_mismatched_narrow_scope_never_covers_a_different_narrow_requirement():
    # A DMA_PATH-scoped scoreboard must never be read as covering an
    # INTERRUPT_PATH-scoped requirement -- the one subsumption rule is
    # exclusive to END_TO_END.
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "usb0_pcie0_irq",
            "subsystems": ["usb0", "pcie0"],
            "evidence": "shared interrupt controller",
            "spans_interrupt_chain": True,
        }],
        existing_scoreboards=[{
            "scoreboard_id": "sb_dma_only",
            "owning_subsystems": ["usb0", "pcie0"],
            "evidence": "generated DMA-path scoreboard, unrelated to interrupts",
            "declared_scope": SCOPE_DMA_PATH,
        }],
    )
    assert ir.overall_status == OVERALL_INCOMPLETE
    entry = ir.entries[0]
    assert entry.required_scope == SCOPE_INTERRUPT_PATH
    assert entry.composition_status == COMPOSITION_GAP
    assert entry.covering_scoreboard_ids == []


def test_gap_when_no_existing_scoreboard_covers_the_required_subsystems():
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "usb0_pcie0_mem",
            "subsystems": ["usb0", "pcie0"],
            "evidence": "shared memory controller",
            "spans_memory_controller": True,
        }],
        existing_scoreboards=[{
            "scoreboard_id": "sb_usb0_local",
            "owning_subsystems": ["usb0"],
            "evidence": "per-subsystem USB0 scoreboard only",
            "block_local": True,
        }],
    )
    assert ir.overall_status == OVERALL_INCOMPLETE
    entry = ir.entries[0]
    assert entry.required_scope == SCOPE_MEMORY_PATH
    assert entry.composition_status == COMPOSITION_GAP


def test_gap_when_no_existing_scoreboards_supplied_at_all():
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "usb0_pcie0_dma",
            "subsystems": ["usb0", "pcie0"],
            "evidence": "shared DMA engine",
            "spans_dma_engine": True,
        }],
    )
    assert ir.overall_status == OVERALL_INCOMPLETE
    assert ir.entries[0].composition_status == COMPOSITION_GAP
    assert ir.entries[0].covering_scoreboard_ids == []


def test_requirement_unverifiable_is_never_treated_as_covered():
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "usb0_pcie0_mystery",
            "subsystems": ["usb0", "pcie0"],
            "evidence": "these two subsystems are known to interact somehow",
        }],
        existing_scoreboards=[{
            "scoreboard_id": "sb_soc_e2e",
            "owning_subsystems": ["usb0", "pcie0"],
            "evidence": "generated SoC-level scoreboard",
            "spans_end_to_end_stimulus_to_system_effect": True,
        }],
    )
    assert ir.overall_status == OVERALL_INCOMPLETE
    entry = ir.entries[0]
    assert entry.composition_status == COMPOSITION_UNVERIFIABLE
    assert entry.required_scope is None
    # Never silently defaulted to COVERED just because an END_TO_END
    # scoreboard happens to exist -- the requirement itself is unresolved.
    assert entry.covering_scoreboard_ids == []


def test_scope_contradiction_never_silently_accepted():
    # port_count=1 resolves PORT_LOCAL, contradicting a declared 2-subsystem
    # interaction -- this is a data-quality defect, reported, not trusted.
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "usb0_pcie0_bad_facts",
            "subsystems": ["usb0", "pcie0"],
            "evidence": "declared as an interaction, but the scope facts contradict that",
            "port_count": 1,
        }],
    )
    assert ir.overall_status == OVERALL_INCOMPLETE
    entry = ir.entries[0]
    assert entry.composition_status == COMPOSITION_CONTRADICTION
    assert entry.required_scope == SCOPE_PORT_LOCAL
    assert entry.needs_cross_subsystem_scoreboard is False


def test_defaulted_syosil_adjacent_requirement_only_satisfied_by_end_to_end():
    # A SyoSil/similar compare-engine interaction with no placement fact of
    # its own DEFAULTS to a known role but an unresolved scope -- only an
    # END_TO_END-scoped existing scoreboard can be trusted to cover it.
    interaction = {
        "interaction_id": "usb0_pcie0_syoscb",
        "subsystems": ["usb0", "pcie0"],
        "evidence": "a shared SYOSCB-based compare engine sits between the two subsystems",
        "vip_adjacent_compare_engine_declared": True,
    }
    ir_gap = build_system_scoreboard_ir(
        system_interactions=[interaction],
        existing_scoreboards=[{
            "scoreboard_id": "sb_dma_only",
            "owning_subsystems": ["usb0", "pcie0"],
            "evidence": "a DMA_PATH-scoped scoreboard -- not broad enough to trust for an unresolved requirement",
            "declared_scope": SCOPE_DMA_PATH,
        }],
    )
    assert ir_gap.entries[0].required_scope_status == STATUS_DEFAULTED
    assert ir_gap.entries[0].composition_status == COMPOSITION_GAP

    ir_covered = build_system_scoreboard_ir(
        system_interactions=[interaction],
        existing_scoreboards=[{
            "scoreboard_id": "sb_soc_e2e",
            "owning_subsystems": ["usb0", "pcie0"],
            "evidence": "generated SoC-level end-to-end scoreboard",
            "spans_end_to_end_stimulus_to_system_effect": True,
        }],
    )
    assert ir_covered.entries[0].composition_status == COMPOSITION_COVERED


def test_worst_wins_a_single_uncovered_interaction_blocks_overall_complete():
    ir = build_system_scoreboard_ir(
        system_interactions=[
            {
                "interaction_id": "usb0_pcie0_dma",
                "subsystems": ["usb0", "pcie0"],
                "evidence": "shared DMA engine",
                "spans_dma_engine": True,
            },
            {
                "interaction_id": "usb0_ddr0_mem",
                "subsystems": ["usb0", "ddr0"],
                "evidence": "shared memory controller, no scoreboard exists for this pair yet",
                "spans_memory_controller": True,
            },
        ],
        existing_scoreboards=[{
            "scoreboard_id": "sb_dma_path",
            "owning_subsystems": ["usb0", "pcie0"],
            "evidence": "generated DMA-path scoreboard",
            "declared_scope": SCOPE_DMA_PATH,
        }],
    )
    assert ir.overall_status == OVERALL_INCOMPLETE
    statuses = {e.interaction_id: e.composition_status for e in ir.entries}
    assert statuses["usb0_pcie0_dma"] == COMPOSITION_COVERED
    assert statuses["usb0_ddr0_mem"] == COMPOSITION_GAP


def test_covering_scoreboard_must_cover_every_declared_subsystem_not_a_subset():
    # A 3-way interaction is only covered by a scoreboard whose own
    # owning_subsystems is a real superset of all 3, not just 2 of them.
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "three_way",
            "subsystems": ["usb0", "pcie0", "ddr0"],
            "evidence": "a three-subsystem shared DMA path",
            "spans_dma_engine": True,
        }],
        existing_scoreboards=[{
            "scoreboard_id": "sb_two_only",
            "owning_subsystems": ["usb0", "pcie0"],
            "evidence": "only covers two of the three subsystems",
            "declared_scope": SCOPE_DMA_PATH,
        }],
    )
    assert ir.entries[0].composition_status == COMPOSITION_GAP


def test_duplicate_interaction_id_is_refused():
    with pytest.raises(SystemScoreboardIRError, match="duplicate"):
        build_system_scoreboard_ir(
            system_interactions=[
                {"interaction_id": "dup", "subsystems": ["a", "b"], "evidence": "x", "spans_dma_engine": True},
                {"interaction_id": "dup", "subsystems": ["a", "c"], "evidence": "y", "spans_dma_engine": True},
            ],
        )


def test_malformed_system_interactions_type_is_refused():
    with pytest.raises(SystemScoreboardIRError, match="list"):
        build_system_scoreboard_ir(system_interactions={"not": "a list"})  # type: ignore[arg-type]


def test_malformed_existing_scoreboards_type_is_refused():
    with pytest.raises(SystemScoreboardIRError, match="list"):
        build_system_scoreboard_ir(
            system_interactions=[{
                "interaction_id": "x", "subsystems": ["a", "b"], "evidence": "e", "spans_dma_engine": True,
            }],
            existing_scoreboards="not-a-list",  # type: ignore[arg-type]
        )


def test_cross_port_and_direct_declared_scope_are_both_reused_correctly():
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "declared_cross_port",
            "subsystems": ["p0", "p1"],
            "evidence": "human-confirmed CROSS_PORT interaction",
            "declared_scope": SCOPE_CROSS_PORT,
        }],
        existing_scoreboards=[{
            "scoreboard_id": "sb_cp",
            "owning_subsystems": ["p0", "p1"],
            "evidence": "generated cross-port scoreboard",
            "declared_scope": SCOPE_CROSS_PORT,
        }],
    )
    assert ir.entries[0].required_scope == SCOPE_CROSS_PORT
    assert ir.entries[0].composition_status == COMPOSITION_COVERED


# ===========================================================================
# Rendering
# ===========================================================================

def test_render_markdown_reuses_connectivity_render_markdown_table():
    ir = build_system_scoreboard_ir(
        system_interactions=[{
            "interaction_id": "usb0_pcie0_dma",
            "subsystems": ["usb0", "pcie0"],
            "evidence": "shared DMA engine",
            "spans_dma_engine": True,
        }],
    )
    text = render_system_scoreboard_markdown(ir)
    assert "usb0_pcie0_dma" in text
    assert "SYSTEM_SCOREBOARD_COMPOSITION_INCOMPLETE" in text
    assert "|" in text  # a real markdown table was rendered


def test_render_markdown_on_not_applicable_ir_carries_the_empty_note():
    ir = build_system_scoreboard_ir([])
    text = render_system_scoreboard_markdown(ir)
    assert "no system interactions declared" in text


# ===========================================================================
# CLI front door (real subprocess)
# ===========================================================================

def _run_cli(args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.system_scoreboard_ir", *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


def test_cli_scopes_verb():
    result = _run_cli(["scopes"])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert set(payload["scope_values"]) == set(SCOPE_VALUES)


def test_cli_build_verb_complete_exits_0(tmp_path):
    interactions = tmp_path / "interactions.json"
    interactions.write_text(json.dumps([{
        "interaction_id": "usb0_pcie0_dma",
        "subsystems": ["usb0", "pcie0"],
        "evidence": "shared DMA engine",
        "spans_dma_engine": True,
    }]), encoding="utf-8")
    scoreboards = tmp_path / "scoreboards.json"
    scoreboards.write_text(json.dumps([{
        "scoreboard_id": "sb_soc_e2e",
        "owning_subsystems": ["usb0", "pcie0"],
        "evidence": "generated SoC-level scoreboard",
        "spans_end_to_end_stimulus_to_system_effect": True,
    }]), encoding="utf-8")
    result = _run_cli(["build", "--interactions", str(interactions),
                        "--scoreboards", str(scoreboards), "--json"])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == OVERALL_COMPLETE


def test_cli_build_verb_incomplete_exits_1(tmp_path):
    interactions = tmp_path / "interactions.json"
    interactions.write_text(json.dumps([{
        "interaction_id": "usb0_pcie0_dma",
        "subsystems": ["usb0", "pcie0"],
        "evidence": "shared DMA engine",
        "spans_dma_engine": True,
    }]), encoding="utf-8")
    result = _run_cli(["build", "--interactions", str(interactions), "--json"])
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == OVERALL_INCOMPLETE


def test_cli_build_verb_not_applicable_exits_0(tmp_path):
    interactions = tmp_path / "interactions.json"
    interactions.write_text("[]", encoding="utf-8")
    result = _run_cli(["build", "--interactions", str(interactions), "--json"])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == OVERALL_NOT_APPLICABLE


def test_cli_build_verb_malformed_exits_2(tmp_path):
    interactions = tmp_path / "interactions.json"
    interactions.write_text(json.dumps([{
        "interaction_id": "no_evidence",
        "subsystems": ["a", "b"],
    }]), encoding="utf-8")
    result = _run_cli(["build", "--interactions", str(interactions), "--json"])
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert "error" in payload
