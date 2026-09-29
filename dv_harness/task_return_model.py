"""dv_harness/task_return_model.py -- "no silent command failure": every
DISPATCHED task must resolve to a real, evidence-grounded outcome, never an
assumed one (2026-09-06).

THE GAP THIS CLOSES
-------------------
This harness's `command.txt`/pattern architecture (`.claude/skills/CORE/
pattern-architecture/SKILL.md`) dispatches multiple concurrent tasks per
pattern -- one per `block`/`branch_a*`/`branch_fw`/`branch_b*` branch (see
`branch-mapper/SKILL.md`'s Initialization Task Hierarchy and the AMBA M x N
arbitration prose it operationalizes). Nothing in this repo checked that a
dispatched task's outcome was actually RECORDED anywhere before being
treated as done. `loop_budget.FailureType` classifies WHY a STAGE-level
retry failed (TRANSIENT/DETERMINISTIC/RESOURCE/...) -- a different, coarser
question about the harness's own retry loop. This module is a DIFFERENT,
more granular vocabulary: the resolved outcome of one individual dispatched
task inside one sim.log, and the two are deliberately not merged (do not
route a `FailureType` through this module or vice versa).

Grepping this repo for `SILENT_FAILURE`/`UNSUPPORTED`/`INVALID_ARGUMENT`/
`ENVIRONMENT_ERROR` before writing this found no per-dispatch outcome
vocabulary anywhere, and no code path anywhere cross-checked a declared list
of dispatched tasks against what a sim.log actually recorded.

WHAT THIS MODULE IS
--------------------
Given (1) a DECLARED list of tasks that were supposed to be dispatched (a
`task_id` per entry, optionally the `block`/`branch_a*`/`branch_fw`/
`branch_b*` layer it belongs to and the dispatch command), and (2) a real
sim.log, this module determines -- from real log content only, never from
assumption -- which one of seven outcomes each declared task resolved to:

    PASS / FAIL / TIMEOUT / UNSUPPORTED / INVALID_ARGUMENT /
    ENVIRONMENT_ERROR / SILENT_FAILURE_SUSPECTED

The first six are the CANONICAL outcomes this batch's per-dispatch taxonomy
requires every task to resolve to. `SILENT_FAILURE_SUSPECTED` is not a
seventh normal outcome -- it is what this module reports when the sim.log
gives it NO WAY to determine one of the six, which is the whole point:
"no silent command failure" means a task that produced no recorded outcome
must be FLAGGED as suspect, never silently treated as PASS (the harness
moving on as if nothing happened) and never silently treated as FAIL (which
would be just as fabricated -- the log genuinely does not say).

THE RECOGNIZED LOG CONVENTION, stated rather than implied
-----------------------------------------------------------
No project in this repo has ever emitted a per-task dispatch-outcome line
into a sim.log -- there was nothing to reuse. This module therefore defines
ITS OWN recognized convention, the same way `sim_log_analysis.SEVERITY_ORDER`
states of itself that it is "this module's own severity enum ... not a
pre-existing project-wide enum found elsewhere in the codebase":

    TASK_RESULT: <task_id> => <OUTCOME>

matched case-insensitively, tolerant of `->`/`:`/`,` as the separator and of
a `UVM_INFO`/timestamp prefix before it on the same line, and of the common
PASSED/FAILED/TIMED_OUT/NOT_SUPPORTED/ENV_ERROR spellings (see
`_OUTCOME_ALIASES`). A real task-dispatch layer (a `branch_fw` service loop,
a BFM wrapper, a command.txt driver task) must be made to emit a line in
this shape for its tasks to be recognized here -- until a project's own
dispatch code does, EVERY declared task in that project's sim.log honestly
resolves to SILENT_FAILURE_SUSPECTED, which is the correct, non-fabricated
answer, not a bug in this module.

HONESTY RULES, enforced in code
--------------------------------
  * No occurrence for a task_id in the whole log -> SILENT_FAILURE_SUSPECTED,
    "no recorded outcome at all".
  * An occurrence exists but its outcome token is not one this module
    recognizes -> SILENT_FAILURE_SUSPECTED (an unrecognized token is not
    evidence of any SPECIFIC one of the six canonical outcomes).
  * Two or more occurrences for the same task_id disagree on the outcome ->
    SILENT_FAILURE_SUSPECTED naming the conflicting values found -- which one
    is correct cannot be determined from the log alone, and guessing either
    would be exactly the fabrication this module exists to prevent.
  * A task_id declared twice, or a declared task with no task_id, is a hard
    input error (`TaskReturnModelError`), never silently deduplicated or
    defaulted.
  * This module reads a sim.log and reports; it runs no build, no
    regression, no LSF submission, mints no approval and has no stage gate
    of its own.

`sim_log_analysis.py` is imported READ-ONLY, for `parse_epilogue()` (the
job-level FINAL CHECK summary carried alongside the per-task report as
supplementary context, never used to override a per-task verdict) -- no
function in this module writes into or otherwise touches that module.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from dv_harness import sim_log_analysis

# ---------------------------------------------------------------------------
# Canonical per-dispatch outcome vocabulary.
# ---------------------------------------------------------------------------

TASK_RESULT_PASS = "PASS"
TASK_RESULT_FAIL = "FAIL"
TASK_RESULT_TIMEOUT = "TIMEOUT"
TASK_RESULT_UNSUPPORTED = "UNSUPPORTED"
TASK_RESULT_INVALID_ARGUMENT = "INVALID_ARGUMENT"
TASK_RESULT_ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
TASK_RESULT_SILENT_FAILURE_SUSPECTED = "SILENT_FAILURE_SUSPECTED"

#: The six outcomes a dispatched task must resolve to when the log gives
#: real, unambiguous evidence of one.
CANONICAL_TASK_OUTCOMES: Tuple[str, ...] = (
    TASK_RESULT_PASS,
    TASK_RESULT_FAIL,
    TASK_RESULT_TIMEOUT,
    TASK_RESULT_UNSUPPORTED,
    TASK_RESULT_INVALID_ARGUMENT,
    TASK_RESULT_ENVIRONMENT_ERROR,
)

#: The full set of values `resolved_outcome` may carry, including the
#: honest "could not be determined" catch-all.
ALL_TASK_OUTCOMES: Tuple[str, ...] = CANONICAL_TASK_OUTCOMES + (
    TASK_RESULT_SILENT_FAILURE_SUSPECTED,
)

#: Real-world spellings a dispatch layer might use for each canonical
#: outcome, mapped to the canonical token. Matching is case-insensitive
#: (keys here are upper-case; lookups upper-case the raw token first).
_OUTCOME_ALIASES: Dict[str, str] = {
    "PASS": TASK_RESULT_PASS,
    "PASSED": TASK_RESULT_PASS,
    "FAIL": TASK_RESULT_FAIL,
    "FAILED": TASK_RESULT_FAIL,
    "TIMEOUT": TASK_RESULT_TIMEOUT,
    "TIMED_OUT": TASK_RESULT_TIMEOUT,
    "TIMEDOUT": TASK_RESULT_TIMEOUT,
    "UNSUPPORTED": TASK_RESULT_UNSUPPORTED,
    "NOT_SUPPORTED": TASK_RESULT_UNSUPPORTED,
    "NOTSUPPORTED": TASK_RESULT_UNSUPPORTED,
    "INVALID_ARGUMENT": TASK_RESULT_INVALID_ARGUMENT,
    "INVALID_ARG": TASK_RESULT_INVALID_ARGUMENT,
    "INVALIDARGUMENT": TASK_RESULT_INVALID_ARGUMENT,
    "ENVIRONMENT_ERROR": TASK_RESULT_ENVIRONMENT_ERROR,
    "ENV_ERROR": TASK_RESULT_ENVIRONMENT_ERROR,
    "ENVIRONMENTERROR": TASK_RESULT_ENVIRONMENT_ERROR,
}

# ---------------------------------------------------------------------------
# This module's own recognized dispatch-report line convention:
#   TASK_RESULT: <task_id> => <OUTCOME>
# tolerant of ->/:/, as the separator and of a leading UVM_INFO/timestamp
# prefix on the same line (the regex is not anchored to line start).
# ---------------------------------------------------------------------------

_TASK_RESULT_RE = re.compile(
    r"TASK_RESULT\s*:\s*(?P<task_id>[A-Za-z0-9_./\-]+)\s*(?:=>|->|:|,)\s*"
    r"(?P<outcome>[A-Za-z_]+)",
    re.IGNORECASE,
)


class TaskReturnModelError(ValueError):
    """Raised on a malformed declared-task input -- never silently repaired,
    per the Evidence Truth Rule's "never silently default or guess"."""

    def __init__(self, code: str, detail: Optional[Dict[str, Any]] = None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


def find_task_result_occurrences(log_text: str) -> Dict[str, List[Dict[str, Any]]]:
    """Scan `log_text` line-by-line for this module's `TASK_RESULT: <id> =>
    <OUTCOME>` convention and group every match by `task_id`.

    Returns `{task_id: [ {"line_no", "line_text", "raw_outcome_token",
    "canonical_outcome"}, ... ]}`. `canonical_outcome` is None when the
    matched token is not one of `_OUTCOME_ALIASES`' recognized spellings --
    the occurrence is still recorded (it is real evidence that SOMETHING was
    reported) but it is not treated as evidence of any specific one of the
    six canonical outcomes. A `task_id` with no matching line anywhere is
    simply absent from the returned dict, never present with an empty list
    padded in -- absence here IS the "no recorded outcome" fact."""
    occurrences: Dict[str, List[Dict[str, Any]]] = {}
    for idx, line in enumerate(log_text.splitlines(), start=1):
        for m in _TASK_RESULT_RE.finditer(line):
            task_id = m.group("task_id")
            raw_outcome = m.group("outcome").upper()
            occurrences.setdefault(task_id, []).append({
                "line_no": idx,
                "line_text": line.strip(),
                "raw_outcome_token": raw_outcome,
                "canonical_outcome": _OUTCOME_ALIASES.get(raw_outcome),
            })
    return occurrences


def _resolve_task_outcome(
    task_id: str, occurrences: List[Dict[str, Any]]
) -> Tuple[str, str]:
    """Decide one task's `(resolved_outcome, reason)` from its own real
    occurrences only. Never guesses between disagreeing evidence."""
    if not occurrences:
        return (
            TASK_RESULT_SILENT_FAILURE_SUSPECTED,
            f"no TASK_RESULT line found anywhere in the sim.log for "
            f"task_id={task_id!r}; the dispatch produced no recorded outcome "
            f"and none may be assumed",
        )

    canonical_tokens = sorted({
        o["canonical_outcome"] for o in occurrences if o["canonical_outcome"]
    })

    if not canonical_tokens:
        raw_tokens = sorted({o["raw_outcome_token"] for o in occurrences})
        return (
            TASK_RESULT_SILENT_FAILURE_SUSPECTED,
            f"TASK_RESULT line(s) found for task_id={task_id!r} but none "
            f"carried a recognized outcome token (saw: {raw_tokens}); an "
            f"unrecognized token is not evidence of any specific outcome",
        )

    if len(canonical_tokens) > 1:
        return (
            TASK_RESULT_SILENT_FAILURE_SUSPECTED,
            f"conflicting TASK_RESULT outcomes found for task_id={task_id!r} "
            f"({canonical_tokens}); which one is correct cannot be "
            f"determined from the log alone",
        )

    outcome = canonical_tokens[0]
    return (
        outcome,
        f"resolved from {len(occurrences)} matching TASK_RESULT line(s) in "
        f"the sim.log, all agreeing on {outcome}",
    )


def _normalize_declared_task(entry: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """A declared task is a bare `task_id` string, or a dict carrying at
    least `task_id` (plus optionally `layer` -- the block/branch_a*/
    branch_fw/branch_b* this task belongs to, per branch-mapper's
    Initialization Task Hierarchy -- and `command`, the dispatch command
    text). Anything else is a hard input error."""
    if isinstance(entry, str):
        task_id = entry.strip()
        rest: Dict[str, Any] = {}
    elif isinstance(entry, dict):
        task_id = str(entry.get("task_id", "")).strip()
        rest = {k: v for k, v in entry.items() if k != "task_id"}
    else:
        raise TaskReturnModelError("DECLARED_TASK_INVALID_SHAPE", {
            "entry": repr(entry),
            "hint": "a declared task must be a task_id string, or a dict "
                    "carrying a task_id key",
        })
    if not task_id:
        raise TaskReturnModelError("DECLARED_TASK_MISSING_TASK_ID", {
            "entry": repr(entry),
        })
    normalized: Dict[str, Any] = {"task_id": task_id}
    normalized.update(rest)
    return normalized


def cross_check_task_outcomes(
    declared_tasks: Sequence[Union[str, Dict[str, Any]]], log_text: str
) -> Dict[str, Any]:
    """The core check: for every declared task, resolve its real outcome
    from `log_text` alone.

    Returns:
        {
          "declared_task_count": int,
          "tasks": [
              {"task_id", "layer", "command", "resolved_outcome", "reason",
               "evidence": [{"line_no", "line_text", "raw_outcome_token"}, ...]},
              ...
          ],
          "counts": {outcome: count for outcome in ALL_TASK_OUTCOMES},
          "silent_failure_suspected_count": int,
          "all_tasks_resolved": bool,   # True iff silent_failure_suspected_count == 0
          "job_epilogue": sim_log_analysis.parse_epilogue(log_text) result (or None),
        }

    Raises `TaskReturnModelError` on an empty/malformed/duplicate declared
    task list -- a malformed request is a defect in the CALLER, not
    something this function should silently repair and check anyway."""
    if not declared_tasks:
        raise TaskReturnModelError("NO_DECLARED_TASKS", {
            "hint": "cross-checking requires at least one declared task",
        })

    normalized_tasks = [_normalize_declared_task(t) for t in declared_tasks]

    seen_ids: set = set()
    for t in normalized_tasks:
        if t["task_id"] in seen_ids:
            raise TaskReturnModelError("DUPLICATE_DECLARED_TASK_ID", {
                "task_id": t["task_id"],
            })
        seen_ids.add(t["task_id"])

    occurrences_by_task = find_task_result_occurrences(log_text)

    counts: Dict[str, int] = {outcome: 0 for outcome in ALL_TASK_OUTCOMES}
    task_reports: List[Dict[str, Any]] = []
    for t in normalized_tasks:
        task_id = t["task_id"]
        occurrences = occurrences_by_task.get(task_id, [])
        outcome, reason = _resolve_task_outcome(task_id, occurrences)
        counts[outcome] += 1
        task_reports.append({
            "task_id": task_id,
            "layer": t.get("layer"),
            "command": t.get("command"),
            "resolved_outcome": outcome,
            "reason": reason,
            "evidence": [
                {
                    "line_no": o["line_no"],
                    "line_text": o["line_text"],
                    "raw_outcome_token": o["raw_outcome_token"],
                }
                for o in occurrences
            ],
        })

    silent_count = counts[TASK_RESULT_SILENT_FAILURE_SUSPECTED]
    return {
        "declared_task_count": len(normalized_tasks),
        "tasks": task_reports,
        "counts": counts,
        "silent_failure_suspected_count": silent_count,
        "all_tasks_resolved": silent_count == 0,
        "job_epilogue": sim_log_analysis.parse_epilogue(log_text),
    }


def cross_check_task_outcomes_file(
    declared_tasks: Sequence[Union[str, Dict[str, Any]]],
    log_path: Union[str, Path],
) -> Dict[str, Any]:
    """File wrapper around `cross_check_task_outcomes()`. Reads with
    `errors="replace"`, matching `sim_log_analysis.parse_sim_log_file()`'s
    own "never crash on real log content" posture -- there is no second
    definition of how this project reads a sim.log."""
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    return cross_check_task_outcomes(declared_tasks, text)


def render_task_outcome_table(report: Dict[str, Any]) -> str:
    """Render `cross_check_task_outcomes()`'s per-task report as a markdown
    table, reusing `connectivity.render_markdown_table()` -- this repo's
    only parameterized table renderer -- rather than a fifth hand-rolled
    `"| " + " | ".join(...)` loop."""
    from dv_harness import connectivity

    columns = [
        ("task_id", "Task ID"),
        ("layer", "Layer"),
        ("resolved_outcome", "Resolved Outcome"),
        ("reason", "Reason"),
        ("evidence_lines", "Evidence Line(s)"),
    ]
    rows = []
    for t in report["tasks"]:
        evidence_lines = ", ".join(str(e["line_no"]) for e in t["evidence"])
        rows.append({
            "task_id": t["task_id"],
            "layer": t.get("layer") or "",
            "resolved_outcome": t["resolved_outcome"],
            "reason": t["reason"],
            "evidence_lines": evidence_lines or "(none)",
        })
    return connectivity.render_markdown_table(
        columns, rows, empty_note="(no declared tasks)"
    )


# ---------------------------------------------------------------------------
# Ad hoc CLI (no `dv-harness` verb -- `cli.py` is out of scope for this
# change; use `python -m dv_harness.task_return_model` directly).
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.task_return_model",
        description="Cross-check a declared task list against a real sim.log "
                    "and report each task's resolved outcome ('no silent "
                    "command failure').",
    )
    ap.add_argument("--tasks", required=True,
                     help="Path to a JSON file: a list of task_id strings, "
                          "or a list of {task_id, layer, command} dicts.")
    ap.add_argument("--log", required=True, help="Path to the real sim.log.")
    ap.add_argument("--json", action="store_true",
                     help="Emit the machine-readable report instead of the "
                          "markdown table.")
    args = ap.parse_args(argv)

    declared_tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    try:
        report = cross_check_task_outcomes_file(declared_tasks, args.log)
    except TaskReturnModelError as exc:
        print(f"{exc.code}: {exc.detail}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_task_outcome_table(report))
        print()
        print(f"declared_task_count={report['declared_task_count']} "
              f"silent_failure_suspected_count="
              f"{report['silent_failure_suspected_count']} "
              f"all_tasks_resolved={report['all_tasks_resolved']}")

    return 0 if report["all_tasks_resolved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
