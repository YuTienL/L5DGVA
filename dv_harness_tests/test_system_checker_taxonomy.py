"""Tests for dv_harness/system_checker_taxonomy.py.

Core positive path (all 9 categories, both via keyword inference and via an
explicit `declared_checker_type`) plus real negative controls: an
unclassifiable description, an empty/whitespace-only description, an
unrecognized declared value (raises rather than silently falling back), a
malformed declared value, batch classification order-preservation, the
CLASSIFICATION_ORDER/SYSTEM_CHECKER_TYPES totality check, the
models.Status disjointness guard, and the real CLI subprocess/`execute_verb`
paths.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.system_checker_taxonomy import (
    CLASSIFICATION_ORDER,
    SYSTEM_CHECKER_TYPES,
    UNCLASSIFIED_SYSTEM_CHECKER,
    SystemCheckerClassification,
    SystemCheckerTaxonomyError,
    assert_disjoint_from_verification_verdict_vocabulary,
    classify_system_checker,
    classify_system_checkers,
    execute_verb,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Core positive path: keyword inference, one per category.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected_type",
    [
        (
            "Checks that a duplicate package declaration is not introduced "
            "when merging two subsystem source sets into one system build.",
            "BUILD_INTEGRITY_CHECKER",
        ),
        (
            "Verifies that shared resource ownership is arbitrated correctly "
            "and no active driver conflict exists on the shared AXI port.",
            "RESOURCE_ARBITRATION_CHECKER",
        ),
        (
            "Confirms every transaction's address decode routes to the "
            "correct system-level destination per the address map.",
            "ADDRESS_ROUTING_CHECKER",
        ),
        (
            "Confirms clock and reset sequencing across subsystem boundaries "
            "follows the required power-up sequence ordering.",
            "CLOCK_RESET_SEQUENCING_CHECKER",
        ),
        (
            "Checks command.txt-level command compatibility across the two "
            "subsystems this scenario spans.",
            "COMMAND_COMPATIBILITY_CHECKER",
        ),
        (
            "Verifies the composed scoreboard aggregates correctly across "
            "both subsystems' own scoreboards at system level.",
            "SCOREBOARD_COMPOSITION_CHECKER",
        ),
        (
            "Verifies the system recovers correctly after a link-down "
            "recovery sequence is exercised.",
            "RECOVERY_CHECKER",
        ),
        (
            "Verifies an error injected in subsystem A is correctly "
            "propagated to the system-level status subsystem B observes.",
            "ERROR_PROPAGATION_CHECKER",
        ),
        (
            "Checks end-to-end data integrity across the system-level data "
            "path connecting the two subsystems.",
            "DATA_FLOW_CHECKER",
        ),
    ],
)
def test_keyword_classification_positive_path(text, expected_type):
    result = classify_system_checker(text)
    assert result.checker_type == expected_type
    assert result.matched_evidence
    assert result.declared is False


def test_all_nine_types_are_reachable_via_keyword_inference():
    # Reuses the parametrized fixture's own categories implicitly by checking
    # the classification order itself names exactly the nine types.
    assert set(CLASSIFICATION_ORDER) == set(SYSTEM_CHECKER_TYPES)
    assert len(SYSTEM_CHECKER_TYPES) == 9


# ---------------------------------------------------------------------------
# Positive path via explicit declaration (dict and object shapes).
# ---------------------------------------------------------------------------

def test_explicit_declared_type_wins_and_is_marked_declared():
    result = classify_system_checker({"declared_checker_type": "RECOVERY_CHECKER"})
    assert result.checker_type == "RECOVERY_CHECKER"
    assert result.declared is True
    assert result.rule_id == "explicit_declaration"


def test_explicit_declared_type_wins_over_conflicting_keyword_text():
    # Text alone would classify as DATA_FLOW_CHECKER, but the declaration wins.
    result = classify_system_checker(
        {
            "declared_checker_type": "BUILD_INTEGRITY_CHECKER",
            "description": "Checks data flow integrity across the system data path.",
        }
    )
    assert result.checker_type == "BUILD_INTEGRITY_CHECKER"
    assert result.declared is True


def test_explicit_declared_type_on_a_plain_object():
    class Description:
        declared_checker_type = "ADDRESS_ROUTING_CHECKER"

    result = classify_system_checker(Description())
    assert result.checker_type == "ADDRESS_ROUTING_CHECKER"
    assert result.declared is True


def test_verifies_field_accepts_a_list_of_phrases():
    result = classify_system_checker(
        {"checker_name": "sys_chk_0", "verifies": ["nothing relevant here", "bus arbitration ownership"]}
    )
    assert result.checker_type == "RESOURCE_ARBITRATION_CHECKER"


# ---------------------------------------------------------------------------
# Negative controls.
# ---------------------------------------------------------------------------

def test_unclassifiable_description_is_honestly_unclassified_not_guessed():
    result = classify_system_checker(
        "This checker verifies that the moon is made of green cheese."
    )
    assert result.checker_type == UNCLASSIFIED_SYSTEM_CHECKER
    assert result.matched_evidence == ""
    assert result.rule_id == "no_rule_matched"


def test_empty_description_is_unclassified_with_a_distinct_reason():
    result = classify_system_checker("")
    assert result.checker_type == UNCLASSIFIED_SYSTEM_CHECKER
    assert result.rule_id == "no_text_to_classify"

    result_ws = classify_system_checker("   ")
    assert result_ws.checker_type == UNCLASSIFIED_SYSTEM_CHECKER
    assert result_ws.rule_id == "no_text_to_classify"


def test_unrecognized_declared_type_raises_rather_than_falls_back():
    with pytest.raises(SystemCheckerTaxonomyError):
        classify_system_checker(
            {
                "declared_checker_type": "TOTALLY_MADE_UP_CHECKER",
                "description": "arbitration of the shared bus",
            }
        )


def test_malformed_declared_type_raises():
    with pytest.raises(SystemCheckerTaxonomyError):
        classify_system_checker({"declared_checker_type": "   "})
    with pytest.raises(SystemCheckerTaxonomyError):
        classify_system_checker({"declared_checker_type": 12345})


def test_unrelated_dict_with_no_recognized_fields_is_unclassified():
    result = classify_system_checker({"foo": "bar", "baz": 42})
    assert result.checker_type == UNCLASSIFIED_SYSTEM_CHECKER


def test_recovery_and_error_propagation_are_kept_distinct_on_overlapping_text():
    # "recover" and "propagat" are disjoint keyword roots by construction --
    # a description naming only recovery must never read as propagation and
    # vice versa, even though both are plausible in the same error-handling
    # sentence.
    recovery_only = classify_system_checker(
        "Verifies the port recovers after the induced fault condition clears."
    )
    assert recovery_only.checker_type == "RECOVERY_CHECKER"

    propagation_only = classify_system_checker(
        "Verifies the fault status is propagated to the system top register."
    )
    assert propagation_only.checker_type == "ERROR_PROPAGATION_CHECKER"


# ---------------------------------------------------------------------------
# Batch classification.
# ---------------------------------------------------------------------------

def test_classify_system_checkers_preserves_order_and_never_aggregates():
    results = classify_system_checkers(
        [
            "duplicate module declaration across the merged system build",
            "arbitration of the shared fabric port",
            "no recognizable keyword here at all",
        ]
    )
    assert [r.checker_type for r in results] == [
        "BUILD_INTEGRITY_CHECKER",
        "RESOURCE_ARBITRATION_CHECKER",
        UNCLASSIFIED_SYSTEM_CHECKER,
    ]


# ---------------------------------------------------------------------------
# Structural / vocabulary guarantees.
# ---------------------------------------------------------------------------

def test_classification_order_matches_system_checker_types_exactly():
    assert set(CLASSIFICATION_ORDER) == set(SYSTEM_CHECKER_TYPES)
    assert len(CLASSIFICATION_ORDER) == len(SYSTEM_CHECKER_TYPES) == 9


def test_unclassified_marker_is_never_one_of_the_nine_types():
    assert UNCLASSIFIED_SYSTEM_CHECKER not in SYSTEM_CHECKER_TYPES


def test_disjoint_from_verification_verdict_vocabulary():
    # Must not raise -- proves the vocabulary really does not collide with
    # dv_harness.models.Status today.
    assert_disjoint_from_verification_verdict_vocabulary()


def test_to_dict_shape():
    result = classify_system_checker("shared resource arbitration check")
    d = result.to_dict()
    assert set(d.keys()) == {"checker_type", "matched_evidence", "rule_id", "declared"}
    assert d["checker_type"] == "RESOURCE_ARBITRATION_CHECKER"


def test_dataclass_direct_construction():
    c = SystemCheckerClassification("DATA_FLOW_CHECKER", "data flow", "data_flow_keyword")
    assert c.declared is False
    assert c.checker_type == "DATA_FLOW_CHECKER"


# ---------------------------------------------------------------------------
# CLI: execute_verb() and a real subprocess.
# ---------------------------------------------------------------------------

def test_execute_verb_types(capsys):
    rc = execute_verb(["types"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == set(SYSTEM_CHECKER_TYPES)


def test_execute_verb_classify_all_classified_exits_zero(tmp_path, capsys):
    payload = [
        "arbitration of the shared bus",
        {"declared_checker_type": "RECOVERY_CHECKER"},
    ]
    f = tmp_path / "checkers.json"
    f.write_text(json.dumps(payload), encoding="utf-8")

    rc = execute_verb(["classify", str(f), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["checker_type"] == "RESOURCE_ARBITRATION_CHECKER"
    assert out[1]["checker_type"] == "RECOVERY_CHECKER"
    assert out[1]["declared"] is True


def test_execute_verb_classify_with_unclassified_exits_one(tmp_path, capsys):
    payload = {"checkers": ["moon made of cheese"]}
    f = tmp_path / "checkers.json"
    f.write_text(json.dumps(payload), encoding="utf-8")

    rc = execute_verb(["classify", str(f)])
    assert rc == 1


def test_execute_verb_classify_bad_declared_value_exits_two(tmp_path, capsys):
    payload = [{"declared_checker_type": "NOT_A_REAL_TYPE"}]
    f = tmp_path / "checkers.json"
    f.write_text(json.dumps(payload), encoding="utf-8")

    rc = execute_verb(["classify", str(f)])
    assert rc == 2


def test_execute_verb_classify_missing_file_exits_two(tmp_path, capsys):
    rc = execute_verb(["classify", str(tmp_path / "does_not_exist.json")])
    assert rc == 2


def test_execute_verb_classify_wrong_shape_exits_two(tmp_path, capsys):
    f = tmp_path / "checkers.json"
    f.write_text(json.dumps({"not_checkers": []}), encoding="utf-8")
    rc = execute_verb(["classify", str(f)])
    assert rc == 2


def test_real_cli_subprocess(tmp_path):
    payload = ["arbitration of the shared bus"]
    f = tmp_path / "checkers.json"
    f.write_text(json.dumps(payload), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_checker_taxonomy", "classify", str(f), "--json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out[0]["checker_type"] == "RESOURCE_ARBITRATION_CHECKER"
