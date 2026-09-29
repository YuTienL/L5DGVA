"""Tests for dv_harness/vplan_item_executability_score.py."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from dv_harness import vplan_item_executability_score as vies


PY = sys.executable


# ---------------------------------------------------------------------------
# Core positive path: the five fixed checkpoints, one real item per level.
# ---------------------------------------------------------------------------

def test_no_evidence_when_item_has_no_identity_and_no_facts():
    report = vies.score_item_executability({})
    assert report.score == vies.SCORE_NO_EVIDENCE
    assert report.level_label == "NO_EVIDENCE"
    assert report.item_id is None
    assert report.mapping_facts_total == 0
    assert report.critical_blockers == ()


def test_identified_unmapped_when_item_known_but_zero_facts_declared():
    report = vies.score_item_executability({"item_id": "VP-1", "title": "Link training"})
    assert report.score == vies.SCORE_IDENTIFIED_UNMAPPED
    assert report.item_id == "VP-1"
    assert report.reason == "ITEM_IDENTIFIED_BUT_ZERO_MAPPING_FACTS_DECLARED"


def test_identified_unmapped_when_facts_declared_but_all_absent():
    report = vies.score_item_executability(
        {
            "item_id": "VP-2",
            "mapping_facts": {"sequence_mapped": False, "checker_mapped": False},
        }
    )
    assert report.score == vies.SCORE_IDENTIFIED_UNMAPPED
    assert report.mapping_facts_present == 0
    assert report.mapping_facts_total == 2


def test_partially_mapped_when_some_facts_present():
    report = vies.score_item_executability(
        {
            "item_id": "VP-3",
            "mapping_facts": {
                "sequence_mapped": True,
                "checker_mapped": False,
                "coverage_mapped": False,
            },
        }
    )
    assert report.score == vies.SCORE_PARTIALLY_MAPPED
    assert report.mapping_facts_present == 1
    assert report.mapping_facts_total == 3
    assert report.missing_fact_names == ("checker_mapped", "coverage_mapped")


def test_mapped_with_open_questions_when_all_facts_present_but_question_unresolved():
    report = vies.score_item_executability(
        {
            "item_id": "VP-4",
            "mapping_facts": {"sequence_mapped": True, "checker_mapped": True},
            "open_questions": [{"text": "which clock domain?", "resolved": False}],
        }
    )
    assert report.score == vies.SCORE_MAPPED_OPEN_QUESTIONS
    assert report.unresolved_open_questions == 1
    assert report.open_questions_total == 1


def test_fully_ready_when_all_facts_present_and_all_questions_resolved():
    report = vies.score_item_executability(
        {
            "item_id": "VP-5",
            "mapping_facts": {"sequence_mapped": True, "checker_mapped": True},
            "open_questions": [{"text": "resolved earlier", "resolved": True}],
        }
    )
    assert report.score == vies.SCORE_FULLY_READY
    assert report.level_label == "FULLY_READY"
    assert report.unresolved_open_questions == 0


def test_fully_ready_with_no_open_questions_field_at_all():
    report = vies.score_item_executability(
        {"item_id": "VP-6", "mapping_facts": ["sequence_mapped", "checker_mapped"]}
    )
    assert report.score == vies.SCORE_FULLY_READY
    assert report.mapping_facts_present == 2
    assert report.mapping_facts_total == 2


# ---------------------------------------------------------------------------
# THE central rule of this module: score and CRITICAL blocker never merge.
# ---------------------------------------------------------------------------

def test_fully_ready_score_never_hides_a_critical_blocker():
    report = vies.score_item_executability(
        {
            "item_id": "VP-7",
            "mapping_facts": {"sequence_mapped": True, "checker_mapped": True},
            "blockers": [
                {"text": "RTL evidence contradicts this sequence's register write", "severity": "CRITICAL"}
            ],
        }
    )
    # The high score is reported...
    assert report.score == vies.SCORE_FULLY_READY
    # ...and the CRITICAL blocker is reported RIGHT BESIDE it, never dropped.
    assert len(report.critical_blockers) == 1
    assert "RTL evidence" in report.critical_blockers[0]["text"]
    # The structural proof helper agrees.
    vies.assert_score_never_hides_a_critical_blocker(report)
    # And a serialized form still carries both facts side by side.
    payload = report.to_dict()
    assert payload["score"] == 100
    assert payload["has_critical_blocker"] is True


def test_critical_blocker_never_drags_a_low_score_further_down_either():
    # A score of 20 with a critical blocker attached must still read 20 --
    # not some third, blended value invented by this module.
    report = vies.score_item_executability(
        {
            "item_id": "VP-8",
            "blockers": [{"text": "spec ambiguity", "severity": "CRITICAL"}],
        }
    )
    assert report.score == vies.SCORE_IDENTIFIED_UNMAPPED
    assert len(report.critical_blockers) == 1


def test_non_critical_blocker_severity_is_reported_separately_from_critical():
    report = vies.score_item_executability(
        {
            "item_id": "VP-9",
            "mapping_facts": {"sequence_mapped": True},
            "blockers": [
                {"text": "minor style nit", "severity": "MINOR"},
                {"text": "real showstopper", "severity": "critical"},  # case-insensitive
            ],
        }
    )
    assert len(report.critical_blockers) == 1
    assert report.critical_blockers[0]["text"] == "real showstopper"
    assert len(report.other_blockers) == 1
    assert report.other_blockers[0]["text"] == "minor style nit"


def test_blocker_with_no_severity_field_is_reported_as_other_not_dropped():
    report = vies.score_item_executability(
        {"item_id": "VP-10", "blockers": [{"text": "unclassified issue"}]}
    )
    assert report.critical_blockers == ()
    assert len(report.other_blockers) == 1
    assert report.other_blockers[0]["severity"] == "UNSPECIFIED"


# ---------------------------------------------------------------------------
# Negative controls: malformed/duck-typed-but-unrecognized input never
# silently defaults or guesses.
# ---------------------------------------------------------------------------

def test_item_not_a_mapping_raises():
    with pytest.raises(vies.VPlanItemExecutabilityError) as exc:
        vies.score_item_executability(["not", "a", "mapping"])  # type: ignore[arg-type]
    assert exc.value.reason == "ITEM_NOT_A_MAPPING"


def test_mapping_facts_of_unrecognized_shape_raises():
    with pytest.raises(vies.VPlanItemExecutabilityError) as exc:
        vies.score_item_executability({"item_id": "VP-11", "mapping_facts": 42})
    assert exc.value.reason == "MAPPING_FACTS_UNRECOGNIZED_SHAPE"


def test_open_questions_of_unrecognized_shape_raises():
    with pytest.raises(vies.VPlanItemExecutabilityError) as exc:
        vies.score_item_executability({"item_id": "VP-12", "open_questions": "not a list"})
    assert exc.value.reason == "OPEN_QUESTIONS_UNRECOGNIZED_SHAPE"


def test_blockers_of_unrecognized_shape_raises():
    with pytest.raises(vies.VPlanItemExecutabilityError) as exc:
        vies.score_item_executability({"item_id": "VP-13", "blockers": {"not": "a list"}})
    assert exc.value.reason == "BLOCKERS_UNRECOGNIZED_SHAPE"


def test_unrecognized_mapping_fact_record_is_reported_as_unknown_not_dropped_silently():
    report = vies.score_item_executability(
        {
            "item_id": "VP-14",
            "mapping_facts": [{"weird": "shape", "no_name_or_present_key": True}],
        }
    )
    assert any("UNRECOGNIZED_MAPPING_FACT_RECORD" in u for u in report.unknowns)
    # No usable fact was extracted from that malformed record, so the item
    # still reads as identified-but-unmapped rather than silently PASSING.
    assert report.mapping_facts_total == 0
    assert report.score == vies.SCORE_IDENTIFIED_UNMAPPED


def test_required_mapping_facts_surfaces_a_declared_but_never_mentioned_fact():
    # Bare-string mapping_facts list only names what was actually asserted;
    # required_mapping_facts fills in the honest "declared but absent" gap.
    report = vies.score_item_executability(
        {"item_id": "VP-15", "mapping_facts": ["sequence_mapped"]},
        required_mapping_facts=["sequence_mapped", "checker_mapped", "coverage_mapped"],
    )
    assert report.mapping_facts_total == 3
    assert report.mapping_facts_present == 1
    assert report.score == vies.SCORE_PARTIALLY_MAPPED
    assert "checker_mapped" in report.missing_fact_names
    assert "coverage_mapped" in report.missing_fact_names


def test_score_vplan_items_batch_reraises_with_item_index():
    items = [
        {"item_id": "VP-16", "mapping_facts": {"sequence_mapped": True}},
        {"item_id": "VP-17", "mapping_facts": "bad-shape"},
    ]
    with pytest.raises(vies.VPlanItemExecutabilityError) as exc:
        vies.score_vplan_items(items)
    assert exc.value.detail["item_index"] == 1


def test_score_vplan_items_batch_scores_every_item_on_success():
    items = [
        {"item_id": "VP-18", "mapping_facts": {"sequence_mapped": True}},
        {"item_id": "VP-19"},
    ]
    reports = vies.score_vplan_items(items)
    assert [r.item_id for r in reports] == ["VP-18", "VP-19"]
    assert reports[0].score == vies.SCORE_FULLY_READY
    # VP-19 has an item_id (so it IS identified) but declares zero mapping
    # facts at all -> IDENTIFIED_UNMAPPED, never NO_EVIDENCE.
    assert reports[1].score == vies.SCORE_IDENTIFIED_UNMAPPED


def test_score_vplan_items_batch_item_with_only_id_is_identified_unmapped():
    reports = vies.score_vplan_items([{"item_id": "VP-20"}])
    assert reports[0].score == vies.SCORE_IDENTIFIED_UNMAPPED


def test_scale_is_exactly_the_five_fixed_points():
    assert vies.EXECUTABILITY_SCALE == (0, 20, 50, 80, 100)


def test_render_executability_matrix_shows_score_and_blocker_columns_side_by_side():
    reports = vies.score_vplan_items(
        [
            {
                "item_id": "VP-21",
                "mapping_facts": {"sequence_mapped": True},
                "blockers": [{"text": "wrong RTL address", "severity": "CRITICAL"}],
            }
        ]
    )
    table = vies.render_executability_matrix(reports)
    assert "VP-21" in table
    assert "FULLY_READY" in table
    assert "wrong RTL address" in table
    # Score column and blocker column both present, distinct.
    assert "Score" in table
    assert "CRITICAL Blocker" in table


def test_render_executability_matrix_empty_note_on_no_items():
    table = vies.render_executability_matrix([])
    assert "no vPlan items scored" in table


# ---------------------------------------------------------------------------
# CLI: real subprocess invocations.
# ---------------------------------------------------------------------------

def test_cli_all_ready_exits_zero(tmp_path):
    items_file = tmp_path / "items.json"
    items_file.write_text(
        json.dumps(
            [
                {
                    "item_id": "VP-30",
                    "mapping_facts": {"sequence_mapped": True, "checker_mapped": True},
                }
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [PY, "-m", "dv_harness.vplan_item_executability_score", "--items", str(items_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "FULLY_READY" in result.stdout


def test_cli_not_ready_exits_one(tmp_path):
    items_file = tmp_path / "items.json"
    items_file.write_text(json.dumps([{"item_id": "VP-31"}]), encoding="utf-8")
    result = subprocess.run(
        [PY, "-m", "dv_harness.vplan_item_executability_score", "--items", str(items_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stderr
    assert "IDENTIFIED_UNMAPPED" in result.stdout


def test_cli_critical_blocker_forces_nonzero_exit_even_at_full_score(tmp_path):
    items_file = tmp_path / "items.json"
    items_file.write_text(
        json.dumps(
            [
                {
                    "item_id": "VP-32",
                    "mapping_facts": {"sequence_mapped": True},
                    "blockers": [{"text": "showstopper", "severity": "CRITICAL"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            PY,
            "-m",
            "dv_harness.vplan_item_executability_score",
            "--items",
            str(items_file),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload[0]["score"] == 100
    assert payload[0]["has_critical_blocker"] is True


def test_cli_malformed_items_file_exits_two(tmp_path):
    items_file = tmp_path / "items.json"
    items_file.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    result = subprocess.run(
        [PY, "-m", "dv_harness.vplan_item_executability_score", "--items", str(items_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "NOT_AVAILABLE" in result.stderr


def test_cli_missing_items_file_exits_two():
    result = subprocess.run(
        [PY, "-m", "dv_harness.vplan_item_executability_score", "--items", "/does/not/exist.json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "NOT_AVAILABLE" in result.stderr


def test_cli_required_facts_flag(tmp_path):
    items_file = tmp_path / "items.json"
    items_file.write_text(
        json.dumps([{"item_id": "VP-33", "mapping_facts": ["sequence_mapped"]}]),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            PY,
            "-m",
            "dv_harness.vplan_item_executability_score",
            "--items",
            str(items_file),
            "--required-facts",
            "sequence_mapped,checker_mapped",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload[0]["score"] == 50
    assert payload[0]["mapping_facts_total"] == 2
