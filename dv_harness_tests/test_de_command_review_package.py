"""dv_harness_tests/test_de_command_review_package.py -- real tests for
dv_harness/de_command_review_package.py: the DE Command Review Package
markdown-table renderer.

Core positive path renders a real multi-row package with the fixed column
order; negative controls cover every hard-validation error the module
documents (non-list input, a non-dict-like row, a row missing its identity
field, and one or more rows with a branch owner outside the
block/branch_a*/branch_fw/branch_b* vocabulary), plus the honest
empty-package and missing-optional-column behaviors inherited from
`connectivity.render_markdown_table`."""

from __future__ import annotations

import pytest

from dv_harness.de_command_review_package import (
    BRANCH_OWNER_PATTERN,
    REVIEW_PACKAGE_COLUMNS,
    DECommandReviewPackageError,
    render_de_command_review_package,
    validate_de_command_review_rows,
)


# ---------------------------------------------------------------------------
# positive path
# ---------------------------------------------------------------------------

def test_renders_headers_in_fixed_order_and_real_row_values():
    rows = [
        {
            "existing_command": "USB_FORK_PORT_BRINGUP",
            "recovered_meaning": "launches per-port DUT+PHY bring-up non-blocking",
            "branch_owner": "branch_a0",
            "task": "bringup_task",
            "preconditions": "block STAGE 3 clock-domain check complete",
            "expected_effect": "port 0 trained to its negotiated speed",
            "compatibility": "compatible with join (not join_any)",
            "open_ambiguity": "",
        },
        {
            "existing_command": "USB_FORK_FW_SERVICE",
            "recovered_meaning": "launches the per-port firmware/event-service loop",
            "branch_owner": "branch_fw",
            "task": "fw_service_loop",
            "preconditions": "guarded against double-launch by internal flag",
            "expected_effect": "port becomes able to service interrupts/events",
            "compatibility": "idempotent -- safe if invoked more than once",
            "open_ambiguity": "exact ARM/WAIT/WAKE/DECODE/CLEAR timing not in this evidence",
        },
    ]
    text = render_de_command_review_package(rows)

    header_line = text.splitlines()[0]
    assert header_line == (
        "| Existing Command | Recovered Meaning | Branch Owner | Task | "
        "Preconditions | Expected Effect | Compatibility | Open Ambiguity |")
    assert "USB_FORK_PORT_BRINGUP" in text
    assert "branch_a0" in text
    assert "branch_fw" in text
    assert "exact ARM/WAIT/WAKE/DECODE/CLEAR timing not in this evidence" in text
    # 2 rows + header + separator = 4 lines, nothing fabricated in between
    assert len(text.splitlines()) == 4


def test_column_list_matches_the_task_spec_exactly():
    assert [header for _, header in REVIEW_PACKAGE_COLUMNS] == [
        "Existing Command", "Recovered Meaning", "Branch Owner", "Task",
        "Preconditions", "Expected Effect", "Compatibility", "Open Ambiguity",
    ]


def test_duck_typed_row_object_with_to_dict_is_accepted():
    class Recovered:
        def __init__(self, command, owner):
            self._command = command
            self._owner = owner

        def to_dict(self):
            return {"existing_command": self._command, "branch_owner": self._owner}

    text = render_de_command_review_package([Recovered("USB_PORT_EN", "branch_b1")])
    assert "USB_PORT_EN" in text
    assert "branch_b1" in text


def test_missing_optional_column_renders_empty_not_fabricated():
    # A row from before "compatibility" existed on it must still render --
    # blank, not a guessed value -- exactly like render_markdown_table's own
    # documented tolerance for a row missing a column.
    text = render_de_command_review_package([
        {"existing_command": "LEGACY_CMD", "recovered_meaning": "unknown yet"}])
    row_line = [ln for ln in text.splitlines() if "LEGACY_CMD" in ln][0]
    cells = [c.strip() for c in row_line.strip("|").split("|")]
    # Existing Command, Recovered Meaning filled in; the rest genuinely blank.
    assert cells[0] == "LEGACY_CMD"
    assert cells[1] == "unknown yet"
    assert cells[2:] == ["", "", "", "", "", ""]


def test_empty_package_reports_empty_note_not_a_bare_header():
    text = render_de_command_review_package([], empty_note="(no commands recovered yet)")
    assert "(no commands recovered yet)" in text
    assert len(text.splitlines()) == 3  # header, separator, the empty_note row


# ---------------------------------------------------------------------------
# negative controls
# ---------------------------------------------------------------------------

def test_rows_not_a_list_is_rejected():
    with pytest.raises(DECommandReviewPackageError) as excinfo:
        validate_de_command_review_rows({"existing_command": "X"})
    assert excinfo.value.reason == "REVIEW_PACKAGE_ROWS_NOT_A_LIST"
    assert excinfo.value.detail["got_type"] == "dict"


def test_row_that_is_not_dict_like_is_rejected():
    with pytest.raises(DECommandReviewPackageError) as excinfo:
        validate_de_command_review_rows(["not a dict"])
    assert excinfo.value.reason == "REVIEW_PACKAGE_ROW_NOT_DICT_LIKE"
    assert excinfo.value.detail["index"] == 0


def test_row_missing_existing_command_is_rejected():
    with pytest.raises(DECommandReviewPackageError) as excinfo:
        validate_de_command_review_rows([{"recovered_meaning": "does something"}])
    assert excinfo.value.reason == "REVIEW_PACKAGE_ROW_MISSING_EXISTING_COMMAND"
    assert excinfo.value.detail["index"] == 0


def test_row_with_blank_existing_command_is_rejected():
    with pytest.raises(DECommandReviewPackageError) as excinfo:
        validate_de_command_review_rows([{"existing_command": "   "}])
    assert excinfo.value.reason == "REVIEW_PACKAGE_ROW_MISSING_EXISTING_COMMAND"


def test_row_with_unknown_branch_owner_vocabulary_is_rejected():
    with pytest.raises(DECommandReviewPackageError) as excinfo:
        validate_de_command_review_rows([
            {"existing_command": "MYSTERY_CMD", "branch_owner": "branch_c0"}])
    assert excinfo.value.reason == "REVIEW_PACKAGE_ROW_UNKNOWN_BRANCH_OWNER"
    problems = excinfo.value.detail["problems"]
    assert problems[0]["existing_command"] == "MYSTERY_CMD"
    assert problems[0]["branch_owner"] == "branch_c0"


def test_multiple_bad_branch_owners_are_all_reported_together():
    with pytest.raises(DECommandReviewPackageError) as excinfo:
        validate_de_command_review_rows([
            {"existing_command": "CMD_A", "branch_owner": "top_level"},
            {"existing_command": "CMD_B", "branch_owner": "branch_a0"},  # valid, not reported
            {"existing_command": "CMD_C", "branch_owner": "global"},
        ])
    problems = excinfo.value.detail["problems"]
    assert {p["existing_command"] for p in problems} == {"CMD_A", "CMD_C"}


def test_missing_or_blank_branch_owner_is_not_an_error_by_itself():
    # An unattributed owner is an honest "not yet resolved" -- exactly what
    # Open Ambiguity exists to carry, not a vocabulary violation.
    assert validate_de_command_review_rows([{"existing_command": "CMD_X"}]) is True
    assert validate_de_command_review_rows(
        [{"existing_command": "CMD_Y", "branch_owner": ""}]) is True


def test_branch_owner_pattern_matches_the_four_layer_vocabulary():
    for legal in ("block", "branch_fw", "branch_a0", "branch_a12", "branch_b0", "branch_b3"):
        assert BRANCH_OWNER_PATTERN.match(legal), legal
    for illegal in ("branch_c0", "Block", "branch_a", "branch", "fw", ""):
        assert not BRANCH_OWNER_PATTERN.match(illegal), illegal
