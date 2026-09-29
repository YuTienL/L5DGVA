"""dv_harness/de_command_review_package.py -- renders the DE (Design/
Verification Engineer) Command Review Package: a markdown table pairing each
EXISTING command token recovered from a legacy command.txt-style pattern file
against what this repo's own recovery evidence says about it, so a human DE
can confirm or correct that recovered meaning before it becomes
machine-trusted anywhere downstream.

This module is a RENDERER ONLY. It never recovers a command's meaning, never
infers a branch owner, and never invents a compatibility verdict or a timing
value -- it takes a generic, duck-typed list of dict-like rows already
produced by whatever upstream recovery step ran (elsewhere in this batch, or
by hand), validates the two fields a review package cannot honestly omit,
and defers all table shape/style to
`dv_harness.connectivity.render_markdown_table()` -- this repo's ONLY
parameterized table renderer (see that function's own docstring, added
2026-09-04). No other new module from this batch is imported, per this
task's file-safety scope.

Columns (fixed order):
    Existing Command   -- the literal token from the source file, verbatim.
    Recovered Meaning  -- what upstream recovery believes the command does.
    Branch Owner       -- which of the four fixed task-composition layers
                          this command's effect belongs to: `block`,
                          `branch_a{i}`, `branch_fw`, or `branch_b{i}` --
                          the exact vocabulary defined by
                          `.claude/skills/CORE/branch-mapper/SKILL.md` and
                          `.claude/skills/CORE/pattern-architecture/SKILL.md`
                          (block = one-shot chip-global prologue; branch_a* =
                          per-port DUT+PHY bring-up; branch_fw = per-port
                          firmware/event-service loop; branch_b* = per-port
                          VIP-driven test body). This is a DIFFERENT, more
                          granular per-dispatch vocabulary from
                          `loop_budget.FailureType` and is never merged with
                          it. A Branch Owner value outside this vocabulary is
                          rejected loudly (see `validate_de_command_review_rows`)
                          rather than rendered, because a wrong owner routes
                          review to nobody.
    Task               -- the task/macro name (if recovery evidence names one).
    Preconditions      -- what recovery evidence says must already hold.
    Expected Effect    -- what recovery evidence says the command changes.
    Compatibility      -- upstream recovery's compatibility verdict for this
                          command against current pattern-architecture rules
                          (e.g. join vs join_any implications) -- rendered
                          verbatim, never computed here.
    Open Ambiguity     -- whatever upstream recovery could NOT resolve;
                          left blank only when the input row genuinely has
                          nothing there, never defaulted to a fabricated
                          "none".

Evidence Truth Rule: a row missing its `existing_command` identity, or
carrying a `branch_owner` string outside the four-layer vocabulary above, is
a hard validation error (`DECommandReviewPackageError`), never silently
dropped or coerced. Every other field renders exactly what the row already
holds -- missing optional fields render as an empty cell (the same
missing-column-renders-empty behavior `render_markdown_table` already
provides for a dict reloaded from before a column existed), which is an
honest "not stated" rather than a fabricated value.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from dv_harness.connectivity import render_markdown_table

__all__ = [
    "DECommandReviewPackageError",
    "REVIEW_PACKAGE_COLUMNS",
    "BRANCH_OWNER_PATTERN",
    "validate_de_command_review_rows",
    "render_de_command_review_package",
]


class DECommandReviewPackageError(ValueError):
    """Base class for every hard-fail error this module raises. Matches the
    house convention established by `connectivity.ConnectivityError`:
    `.reason` is a short machine-matchable code, `.detail` is a dict of the
    exact evidence that triggered it."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# Fixed column order for the DE Command Review Package table. `key` is the
# dict field a row is read from; `header` is the exact printed column title
# from this task's spec.
REVIEW_PACKAGE_COLUMNS = [
    ("existing_command", "Existing Command"),
    ("recovered_meaning", "Recovered Meaning"),
    ("branch_owner", "Branch Owner"),
    ("task", "Task"),
    ("preconditions", "Preconditions"),
    ("expected_effect", "Expected Effect"),
    ("compatibility", "Compatibility"),
    ("open_ambiguity", "Open Ambiguity"),
]

# block/branch_a*/branch_fw/branch_b* -- the exact four-layer vocabulary from
# branch-mapper/SKILL.md and pattern-architecture/SKILL.md. Anything outside
# this pattern is not a real branch owner in this repo's vocabulary.
BRANCH_OWNER_PATTERN = re.compile(r"^(block|branch_fw|branch_a\d+|branch_b\d+)$")


def _row_dict(row: Any, index: int) -> dict:
    """Duck-type one input row into a plain dict, the same conversion
    `render_markdown_table` itself applies (`.to_dict()` if present, else
    `dict(row)`), so validation sees exactly what rendering will see."""
    try:
        return row.to_dict() if hasattr(row, "to_dict") else dict(row)
    except (TypeError, ValueError) as exc:
        raise DECommandReviewPackageError("REVIEW_PACKAGE_ROW_NOT_DICT_LIKE", {
            "index": index,
            "row_repr": repr(row)[:200],
            "error": str(exc),
            "hint": ("each row must be a dict, or an object exposing "
                     "to_dict(), or otherwise accept dict(row)")}) from exc


def validate_de_command_review_rows(rows: Iterable[Any]) -> bool:
    """Hard-validate a DE Command Review Package input before it is rendered.

    Raises `DECommandReviewPackageError` (never returns False) when:
      - `rows` is not a list/tuple of rows at all
        (REVIEW_PACKAGE_ROWS_NOT_A_LIST);
      - a row cannot be duck-typed into a dict
        (REVIEW_PACKAGE_ROW_NOT_DICT_LIKE);
      - a row has no (or a blank) `existing_command` -- the one field a
        review package cannot honestly omit, since it is the row's whole
        identity (REVIEW_PACKAGE_ROW_MISSING_EXISTING_COMMAND);
      - a row's `branch_owner`, when present and non-blank, is not one of
        `block` / `branch_fw` / `branch_a{i}` / `branch_b{i}`
        (REVIEW_PACKAGE_ROW_UNKNOWN_BRANCH_OWNER) -- collected across all
        rows and raised once, so one bad batch reports every offending row
        instead of stopping at the first.

    A `branch_owner` that is simply absent or blank is NOT an error here --
    that is upstream recovery honestly reporting "not yet attributed", which
    is exactly what the Open Ambiguity column exists to carry forward; only
    a value that claims to be a branch owner but isn't a real one is
    rejected."""
    if not isinstance(rows, (list, tuple)):
        raise DECommandReviewPackageError("REVIEW_PACKAGE_ROWS_NOT_A_LIST", {
            "hint": "de command review package input must be a list (or tuple) of dict-like rows",
            "got_type": type(rows).__name__})

    unknown_owner_problems = []
    for index, row in enumerate(rows):
        d = _row_dict(row, index)

        existing_command = d.get("existing_command")
        if existing_command is None or not str(existing_command).strip():
            raise DECommandReviewPackageError(
                "REVIEW_PACKAGE_ROW_MISSING_EXISTING_COMMAND", {
                    "index": index,
                    "row": {k: d.get(k) for k, _ in REVIEW_PACKAGE_COLUMNS},
                    "hint": "every row must name the real Existing Command token it reviews"})

        branch_owner = d.get("branch_owner")
        if branch_owner is not None and str(branch_owner).strip():
            owner_str = str(branch_owner).strip()
            if not BRANCH_OWNER_PATTERN.match(owner_str):
                unknown_owner_problems.append({
                    "index": index,
                    "existing_command": existing_command,
                    "branch_owner": branch_owner})

    if unknown_owner_problems:
        raise DECommandReviewPackageError(
            "REVIEW_PACKAGE_ROW_UNKNOWN_BRANCH_OWNER", {
                "problems": unknown_owner_problems,
                "legal_pattern": BRANCH_OWNER_PATTERN.pattern,
                "hint": ("Branch Owner must be one of block / branch_fw / "
                         "branch_a{i} / branch_b{i} per branch-mapper/SKILL.md "
                         "and pattern-architecture/SKILL.md -- an unrecognized "
                         "owner routes DE review to nobody")})
    return True


def render_de_command_review_package(
    rows: Iterable[Any],
    *,
    empty_note: str = "(no recovered commands to review)",
) -> str:
    """Render the DE Command Review Package as a markdown pipe table over
    `rows` (a generic, duck-typed list of dict-like entries -- plain dicts,
    or objects exposing `.to_dict()`).

    Validates `rows` first via `validate_de_command_review_rows` (raising
    `DECommandReviewPackageError` on any hard violation), then renders with
    `connectivity.render_markdown_table()` under the fixed
    `REVIEW_PACKAGE_COLUMNS` order -- this function adds no rendering logic
    of its own beyond that column list and `empty_note`, so the table's
    shape/style stays identical to every other AMBA-16/17/20-derived table
    in this repo.

    An empty `rows` list is NOT an error: it renders `empty_note` in place of
    a body row, distinguishing "recovery found nothing left to review" from
    "this package was never produced" -- the same distinction
    `render_markdown_table` already draws for its other callers."""
    validate_de_command_review_rows(rows)
    return render_markdown_table(REVIEW_PACKAGE_COLUMNS, rows, empty_note=empty_note)
