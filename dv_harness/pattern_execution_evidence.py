"""pattern_execution_evidence.py -- per-command-line (task/branch) execution
evidence record.

`dv_harness/evidence_db.py`'s `normalized_evidence` table (and
`golden_scenario.py` on top of it) records evidence at PER-TEST granularity:
one row per (job, pattern) with one overall verdict. This module is a finer
granularity underneath that: one record per DISPATCHED TASK inside a single
command.txt/pattern run -- the `block` / `branch_a{i}` / `branch_fw` /
`branch_b{i}` task-composition layers `.claude/skills/CORE/pattern-
architecture/SKILL.md` and `.claude/skills/CORE/branch-mapper/SKILL.md`
already define (reused verbatim here, never re-derived or renamed).

Per the task's own instruction, this is a DIFFERENT, more granular
per-dispatch vocabulary than `loop_budget.FailureType`'s ten-class retry
taxonomy -- that module classifies why a whole STAGE failed for a
retry-vs-stop decision; this module records what one TASK inside one
pattern run actually did, and the two are never merged.

EVIDENCE TRUTH RULE, applied literally: every `start_time`/`end_time` this
module reports is a REAL `@ <time>` value lifted off a REAL log line that
genuinely mentions that task's name next to a lifecycle verb (the same
"UVM_INFO ... @ <time>: <reporter> [<ID>] starting <name>" / "... complete"
narration convention `sim_log_analysis.py`'s own tested fixtures already use
-- see `dv_harness_tests/test_sim_log_analysis.py`'s `CLEAR_PASS_LOG` /
`UVM_ERROR_HEAVY_LOG`). A sim.log that never narrates a task by name at this
granularity yields NO records for it, never a guessed or interpolated
timestamp -- `granularity_status` says so explicitly at the report level, and
every per-field absence carries `NOT_AVAILABLE` plus a real reason rather
than a default.

REUSE OVER REINVENT: the actual marker scan, signature normalization and
severity/category classification is 100% `sim_log_analysis.parse_sim_log()` /
`classify_signatures()`, called (read-only) over the TEXT SLICE between a
task's own start/end line -- there is no second log-marker scanner in this
module. `connectivity.render_markdown_table()` renders the report; there is
no second table renderer either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dv_harness import sim_log_analysis

#: Honest-absence token used throughout this module, matching the project-wide
#: convention (`power_intent.py`, `golden_scenario.py`, `waiver_store.py`, ...):
#: never a default value, never a guess -- a real reason always accompanies it.
NOT_AVAILABLE = "NOT_AVAILABLE"

# ---------------------------------------------------------------------------
# Canonical task/branch vocabulary -- reused verbatim from
# pattern-architecture/SKILL.md section 1 and branch-mapper/SKILL.md's
# Initialization Task Hierarchy, never re-derived or renamed here:
#   block        -- one-shot, chip/SoC-global prologue (BLOCKING)
#   branch_a{i}  -- per-port DUT+PHY bring-up task, non-blocking
#   branch_fw    -- per-port FW/event-service loop, launched once, non-blocking
#   branch_b{i}  -- per-port VIP-driven test body, forked+joined
# ---------------------------------------------------------------------------

_TASK_NAME_RE = re.compile(r"\b(block|branch_a\d+|branch_fw|branch_b\d+)\b")

#: task literal name -> its layer classification in the 5-layer shape. Kept
#: as a SEPARATE field from the literal task name (`branch`, alongside
#: `task`) because two different `branch_a{i}` instances are two different
#: tasks that share one layer -- collapsing them would lose per-port identity,
#: and reporting only the literal name would lose the "which layer" fact a
#: reader needs to reason about fork/join/arbitration scope.
GLOBAL_BLOCK = "GLOBAL_BLOCK"
DUT_PHY_INIT = "DUT_PHY_INIT"
FW_SERVICE_LOOP = "FW_SERVICE_LOOP"
VIP_TEST_BODY = "VIP_TEST_BODY"

_BRANCH_A_RE = re.compile(r"^branch_a\d+$")
_BRANCH_B_RE = re.compile(r"^branch_b\d+$")


def classify_branch_layer(task_name: str) -> str:
    """Map a literal task name to its pattern-architecture layer. Raises on a
    name outside the canonical vocabulary -- this module never guesses a
    layer for a name it does not recognize."""
    if task_name == "block":
        return GLOBAL_BLOCK
    if _BRANCH_A_RE.match(task_name):
        return DUT_PHY_INIT
    if task_name == "branch_fw":
        return FW_SERVICE_LOOP
    if _BRANCH_B_RE.match(task_name):
        return VIP_TEST_BODY
    raise ValueError(
        f"classify_branch_layer: {task_name!r} is not one of the canonical "
        f"block/branch_a{{i}}/branch_fw/branch_b{{i}} task names"
    )


# Lifecycle verbs a real narration line uses next to a task name. Chosen to
# match the vocabulary this repo's own real fixtures already use ("starting
# <name>", "... complete") rather than inventing a marker format (e.g. a
# "[TASK_START]" tag) no real sim.log in this project has ever emitted.
_START_VERBS_RE = re.compile(
    r"\b(start(?:ing|ed)?|launch(?:ing|ed)?|begin(?:ning)?|fork(?:ing|ed)?)\b",
    re.IGNORECASE,
)
_END_VERBS_RE = re.compile(
    r"\b(complet(?:e|ed|ing)|done|finish(?:ed|ing)?|join(?:ed|ing)?|end(?:ed|ing)?)\b",
    re.IGNORECASE,
)

#: A real simulation-time marker on a narration line, the same "@ <number>"
#: shape `sim_log_analysis._EPILOGUE_HEADER_RE` already looks for in the
#: FINAL CHECK line -- reused as a pattern shape, not a second definition of
#: what a sim-time stamp looks like in this project's logs.
_TIME_RE = re.compile(r"@\s*(\d+(?:\.\d+)?)")

START = "START"
END = "END"

#: This module's own result vocabulary -- deliberately distinct tokens from
#: both `models.Status` and `loop_budget.FailureType`/`sim_log_analysis`'s
#: category names, per the task's instruction that this is a different,
#: more granular per-dispatch taxonomy that must not be merged with either.
RESULT_COMPLETED_CLEAN = "COMPLETED_CLEAN"
RESULT_COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
RESULT_INCOMPLETE_NO_END_MARKER = "INCOMPLETE_NO_END_MARKER"
RESULT_INCOMPLETE_NO_START_MARKER = "INCOMPLETE_NO_START_MARKER"

#: severities (from sim_log_analysis.SEVERITY_ORDER) that mark a task window
#: as containing a real failure rather than a clean run.
_FAILING_SEVERITIES = frozenset({"CRITICAL", "HIGH"})

GRANULARITY_FOUND = "TASK_LEVEL_EVIDENCE_FOUND"
GRANULARITY_ABSENT = "NO_TASK_LEVEL_GRANULARITY_IN_LOG"


class PatternExecutionEvidenceError(Exception):
    def __init__(self, code: str, detail: Optional[dict] = None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


@dataclass
class PatternExecutionRecord:
    """One per-command-line (task/branch) execution record. Schema fixed by
    the task: {command, task, branch, start_time, end_time, result,
    events_observed, checker, scoreboard}."""

    command: Any
    task: str
    branch: str
    start_time: Any
    end_time: Any
    result: str
    events_observed: List[Dict[str, Any]]
    checker: Any
    scoreboard: Any
    # Evidence trail (not part of the required schema itself, but load-bearing
    # for anyone auditing WHY a field reads NOT_AVAILABLE or which real log
    # lines produced a value) -- always present, never fabricated.
    start_line: Optional[int]
    end_line: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PatternExecutionReport:
    command: Any
    granularity_status: str
    granularity_reason: str
    total_lines: int
    records: List[PatternExecutionRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "granularity_status": self.granularity_status,
            "granularity_reason": self.granularity_reason,
            "total_lines": self.total_lines,
            "records": [r.to_dict() for r in self.records],
        }


def _extract_time(line: str) -> Optional[float]:
    m = _TIME_RE.search(line)
    if not m:
        return None
    return float(m.group(1))


def extract_task_lifecycle_events(log_text: str) -> Dict[str, List[Dict[str, Any]]]:
    """Scan `log_text` line-by-line for real narration of a canonical task
    name (block/branch_a{i}/branch_fw/branch_b{i}) next to a START or END
    lifecycle verb. Returns {task_name: [ {"line_no", "time", "kind"}, ... ]}
    in line order. `time` is a real value lifted off that exact line's own
    "@ <n>" marker, or None when that specific line carries no such marker --
    never interpolated from a neighboring line."""
    events: Dict[str, List[Dict[str, Any]]] = {}
    for idx, line in enumerate(log_text.splitlines(), start=1):
        names = set(_TASK_NAME_RE.findall(line))
        if not names:
            continue
        is_start = bool(_START_VERBS_RE.search(line))
        is_end = bool(_END_VERBS_RE.search(line))
        if not (is_start or is_end):
            continue
        t = _extract_time(line)
        for name in names:
            kind = START if is_start and not is_end else (END if is_end else None)
            # A line matching both verb classes (rare, e.g. "join complete
            # starting cleanup") is ambiguous for THIS name's lifecycle --
            # record it under whichever verb actually appears closest to the
            # name would require positional analysis this scan does not do;
            # honestly skip rather than guess which one it means.
            if is_start and is_end:
                continue
            events.setdefault(name, []).append(
                {"line_no": idx, "time": t, "kind": kind}
            )
    return events


def _window_events(
    lines: List[str], start_line: Optional[int], end_line: Optional[int]
) -> List[Dict[str, Any]]:
    """Classify sim_log_analysis markers found strictly inside
    [start_line, end_line] (both 1-indexed, inclusive), by re-running the
    real parser over that line slice and offsetting the reported line
    numbers back to the original file's numbering. Never invents an event."""
    lo = start_line if start_line is not None else 1
    hi = end_line if end_line is not None else len(lines)
    if lo > hi:
        return []
    window_text = "\n".join(lines[lo - 1 : hi])
    parsed = sim_log_analysis.parse_sim_log(window_text)
    classified = sim_log_analysis.classify_signatures(parsed["signatures"])
    offset = lo - 1
    out = []
    for c in classified:
        c = dict(c)
        c["first_line_no"] = c["first_line_no"] + offset
        c["last_line_no"] = c["last_line_no"] + offset
        out.append(c)
    return out


def build_pattern_execution_records(
    log_text: str, command: Any = None
) -> PatternExecutionReport:
    """Build the finer-granularity per-task execution records for one
    command.txt/pattern's sim.log text.

    `command` is the real command.txt/pattern identifier this log belongs to
    (e.g. `evidence_db.normalized_evidence.pattern`, or a
    `golden_scenario.GoldenScenario.test_name`) -- it is a CALLER-SUPPLIED
    fact, never guessed from the log text, because attributing a log to a
    command by pattern-matching its own narration would be exactly the kind
    of inference the Evidence Truth Rule forbids. Omitting it reports
    `command: NOT_AVAILABLE` rather than a best-effort guess.

    Returns a `PatternExecutionReport` whose `records` is empty (with
    `granularity_status == NO_TASK_LEVEL_GRANULARITY_IN_LOG`) when the log
    never narrates a task name at this granularity at all -- this is the
    honest, expected outcome for the large majority of real sim.log files,
    which only narrate at the whole-test level.
    """
    lines = log_text.splitlines()
    events_by_task = extract_task_lifecycle_events(log_text)
    command_value = command if command is not None else NOT_AVAILABLE

    if not events_by_task:
        return PatternExecutionReport(
            command=command_value,
            granularity_status=GRANULARITY_ABSENT,
            granularity_reason=(
                "no line in this log narrates a block/branch_a{i}/branch_fw/"
                "branch_b{i} task name next to a start/end lifecycle verb -- "
                "this log only carries whole-test-level evidence"
            ),
            total_lines=len(lines),
            records=[],
        )

    records: List[PatternExecutionRecord] = []
    for task_name in sorted(events_by_task):
        occurrences = events_by_task[task_name]
        starts = [e for e in occurrences if e["kind"] == START]
        ends = [e for e in occurrences if e["kind"] == END]

        start_ev = starts[0] if starts else None
        # The LAST end occurrence at or after the (first) start line is the
        # one that genuinely closes this task's window; an end occurrence
        # before any start is not this task's closure.
        end_candidates = ends
        if start_ev is not None:
            end_candidates = [e for e in ends if e["line_no"] >= start_ev["line_no"]]
        end_ev = end_candidates[-1] if end_candidates else None

        start_line = start_ev["line_no"] if start_ev else None
        end_line = end_ev["line_no"] if end_ev else None
        start_time = start_ev["time"] if start_ev and start_ev["time"] is not None else NOT_AVAILABLE
        end_time = end_ev["time"] if end_ev and end_ev["time"] is not None else NOT_AVAILABLE

        if start_ev and end_ev:
            window_events = _window_events(lines, start_line, end_line)
            has_failure = any(c["severity"] in _FAILING_SEVERITIES for c in window_events)
            result = RESULT_COMPLETED_WITH_ERRORS if has_failure else RESULT_COMPLETED_CLEAN
        elif start_ev and not end_ev:
            window_events = _window_events(lines, start_line, len(lines))
            result = RESULT_INCOMPLETE_NO_END_MARKER
        elif end_ev and not start_ev:
            window_events = _window_events(lines, 1, end_line)
            result = RESULT_INCOMPLETE_NO_START_MARKER
        else:  # pragma: no cover -- unreachable, task_name only added with >=1 occurrence
            window_events = []
            result = NOT_AVAILABLE

        checker_events = [c for c in window_events if c["category"] == "assertion"]
        scoreboard_events = [c for c in window_events if c["category"] == "scoreboard_mismatch"]

        records.append(
            PatternExecutionRecord(
                command=command_value,
                task=task_name,
                branch=classify_branch_layer(task_name),
                start_time=start_time,
                end_time=end_time,
                result=result,
                events_observed=window_events,
                checker=checker_events if checker_events else NOT_AVAILABLE,
                scoreboard=scoreboard_events if scoreboard_events else NOT_AVAILABLE,
                start_line=start_line,
                end_line=end_line,
            )
        )

    return PatternExecutionReport(
        command=command_value,
        granularity_status=GRANULARITY_FOUND,
        granularity_reason=(
            f"{len(records)} task(s) narrated by name with a start/end "
            "lifecycle verb in this log"
        ),
        total_lines=len(lines),
        records=records,
    )


def parse_pattern_execution_log(
    path: Union[str, Path], command: Any = None
) -> PatternExecutionReport:
    """File wrapper around `build_pattern_execution_records()`, reading with
    `errors='replace'` -- same convention as
    `sim_log_analysis.parse_sim_log_file()`, for the same reason (a stray
    non-UTF-8 byte in a real multi-GB sim.log must never abort analysis)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return build_pattern_execution_records(text, command=command)


# ---------------------------------------------------------------------------
# Markdown rendering -- reuses connectivity.render_markdown_table() rather
# than a second hand-rolled table renderer.
# ---------------------------------------------------------------------------

_TABLE_COLUMNS = [
    ("command", "Command"),
    ("task", "Task"),
    ("branch", "Branch"),
    ("start_time", "Start"),
    ("end_time", "End"),
    ("result", "Result"),
    ("checker", "Checker"),
    ("scoreboard", "Scoreboard"),
]


def _summarize_for_table(record: PatternExecutionRecord) -> Dict[str, Any]:
    d = record.to_dict()

    def _brief(v):
        if v == NOT_AVAILABLE or v is None:
            return NOT_AVAILABLE
        if isinstance(v, list):
            return f"{len(v)} finding(s)"
        return v

    d["checker"] = _brief(d["checker"])
    d["scoreboard"] = _brief(d["scoreboard"])
    return d


def render_pattern_execution_markdown(report: PatternExecutionReport) -> str:
    from dv_harness import connectivity

    rows = [_summarize_for_table(r) for r in report.records]
    header = (
        f"Command: {report.command} -- granularity: {report.granularity_status} "
        f"({report.granularity_reason})\n\n"
    )
    return header + connectivity.render_markdown_table(
        _TABLE_COLUMNS, rows, empty_note="(no task-level records)"
    )


# ---------------------------------------------------------------------------
# Ad hoc entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="python -m dv_harness.pattern_execution_evidence")
    parser.add_argument("log_path", help="path to a sim.log")
    parser.add_argument("--command", default=None, help="real command.txt/pattern name this log belongs to")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    report = parse_pattern_execution_log(args.log_path, command=args.command)
    if args.as_json:
        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(render_pattern_execution_markdown(report))
    return 0 if report.granularity_status == GRANULARITY_FOUND else 1


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    raise SystemExit(main(_sys.argv[1:]))
