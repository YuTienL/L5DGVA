"""dv_harness/orphaned_fork_detection.py -- branch_b*-internal orphaned/leaked
non-blocking VIP-sequence dispatch detection over REAL generated pattern text.

WHAT THIS CLOSES
-----------------
`.claude/skills/CORE/pattern-architecture/SKILL.md` section 3.5 names a real,
recurring trap class, restated here verbatim from that section (see
`TRAP_CITATION` below): a `branch_b*`-internal non-blocking VIP-sequence
DISPATCH needs a paired, explicit WAIT for that specific dispatch's
completion before the branch that dispatched it is allowed to report a
result -- "the pairing is a property of the dispatch call itself... and it
recurs inside `branch_b*` bodies themselves, not just at the top-level fork."

Nothing in this repo checked that BEFORE this module. `command_task_trace.py`'s
own module docstring says so directly: its VIP_API/UVM_BRIDGE legs are
"DECLARATION-LEVEL TEXTUAL CROSS-REFERENCE ONLY" -- they answer "does a VIP
API get cited somewhere in this command's resolved body", never "does this
specific non-blocking dispatch have a paired wait before the branch
concludes". The one existing check anywhere near this question,
`uvm_generator/templates/sim_scripts/check/pattern_rules.py`'s R7 rule, is a
WHOLE-FILE COUNT check: "if `FORK_SEQ appears anywhere and `WAIT_SEQ_ALL
appears nowhere, fail" -- it cannot see the partial-pairing case this module
exists to catch (three `FORK_SEQ dispatches, one `WAIT_SEQ_ALL, so the last
two dispatches are still orphaned) because it never scopes to a branch_b*
region or walks dispatches in program order. `shared_bus_resource_
registry.py` is INTRA-subsystem bus-arbitration RACE detection (branch_fw
vs. branch_a*, over CALLER-DECLARED resource facts, explicitly because "there
is no SystemVerilog pattern-body parser anywhere in dv_harness/"); it is a
different question (WHO writes a shared register concurrently, never
guessed) at a different scope (branch_a*/branch_fw, never branch_b*'s own
dispatch/wait pairing) and is not extended here.

REUSE, NOT REINVENTION. This module writes NO second command.txt statement
parser. `reference_pattern_audit.extract_command_statements()` is the real,
already-tested SYS-7 statement-level parse this codebase already has --
comment-stripped, classified (K_MACRO_CALL / K_BLOCK_BEGIN / K_BLOCK_END /
K_FORK / K_JOIN, among others), with a real per-statement `line`/`file`
citation and a real per-statement `block_depth` (the nesting depth AT that
statement, already computed by that module's own begin/end/fork/join
depth-tracking). This module imports and calls that function, and that
function alone, to get the statement stream -- it never re-derives comment
stripping, bracket-depth tracking, or macro-call classification.

WHAT COUNTS AS "DISPATCH" AND "WAIT", GROUNDED NOT GUESSED. The one real,
evidence-cited non-blocking-dispatch / explicit-wait macro PAIR this codebase
already documents is `` `FORK_SEQ(...) `` / `` `WAIT_SEQ_ALL ``["_OK"] --
`pattern_rules.py`'s own R7 rule text says so directly ("AXI and the target
IP share <ip>_seq_launcher's capacity-1 semaphore... real concurrency needs
`FORK_SEQ, and every `FORK_SEQ needs a `WAIT_SEQ_ALL"). That pair is this
module's DEFAULT dispatch/wait pattern; a project whose own real convention
differs may override `dispatch_pattern`/`wait_pattern` with its own compiled
regex over the macro's backtick-prefixed name -- never guessed or widened
past the one real, cited default on this module's own initiative.
`` `RUN_SEQ ``-shaped macros are deliberately NOT treated as a dispatch here:
this codebase's own real evidence (`pattern_rules.py`'s `USB_EVIDENCE`
pattern) uses `FORK_SEQ`/`RUN_SEQ\\w*` interchangeably only as "this pattern
touches the target IP" evidence, never as proof RUN_SEQ is non-blocking --
inventing that semantic distinction here would be a guess this module
refuses to make.

PAIRING SEMANTICS. `` `WAIT_SEQ_ALL `` joins EVERY currently-outstanding
forked sequence at once (the macro's own name says so), so ONE wait call
legitimately pairs with SEVERAL preceding dispatches. A dispatch is therefore
PAIRED iff at least one wait statement occurs LATER (by real line number, in
program order) within the SAME branch_b* region -- never a naive 1:1 count
match, which would falsely flag a clean N-dispatches-one-wait-after-all-of-
them pattern. The region's own closing statement (the first `end`/`join` that
returns to the begin's own nesting depth, found from the REAL per-statement
`block_depth` this module reuses rather than re-derives) is the boundary for
"before that branch reports a result" -- a wait appearing after the region
has already closed does not count, and a region with no discoverable close
before end-of-file is reported as its own honest, more severe finding
(REGION_NEVER_CLOSED) rather than silently treated as spanning to EOF, which
could hide a real trap behind a wait call that was never actually reachable
from inside that branch.

DECLARATION-LEVEL BOUND, STATED RATHER THAN IMPLIED CLOSED. This is a textual
program-order scan, not an elaborator: no `` `ifdef ``/generate condition is
evaluated, and a wait sitting inside an `if`/`case` branch that can never
actually execute is still counted as pairing evidence -- the same bound
`command_task_trace.py`/`uvm_structural_lint.py` already state for their own
declaration-level checks. A `begin : branch_b<N>` label combined with a
dispatch macro call on the exact same physical line (never the convention
this codebase's own real templates use -- a begin/label always sits alone on
its own line) is a known limitation of the reused parser's single-line-
flush behaviour and is not special-cased here.

SCOPE BOUNDARY. This module DETECTS and REPORTS only: it never edits a
pattern file, never invents a wait call, never picks which dispatch a
missing wait "should" pair with, and never touches a build/regression/LSF
job or any human-approval/governance mechanism. There is deliberately no
stage gate and no `dv-harness` CLI verb (`cli.py`/`gates.py` untouched, per
this project's own disclosed convention for a standalone module built while
those two files are under concurrent edit pressure) -- the front door is
`python -m dv_harness.orphaned_fork_detection`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Sequence

from . import reference_pattern_audit as rpa
from .models import Status

# ---------------------------------------------------------------------------
# The trap this module operationalizes, cited verbatim (trimmed) rather than
# paraphrased, so a reader can check the citation against the real skill file.
# ---------------------------------------------------------------------------

TRAP_CITATION = (
    "pattern-architecture SKILL.md section 3.5: 'A forked background sequence "
    "without its own explicit join is a silent early pass... every "
    "non-blocking dispatch of concurrent stimulus needs a paired, explicit "
    "\"wait for this dispatch\" call before the branch that dispatched it is "
    "allowed to report a result -- the pairing is a property of the dispatch "
    "call itself, not something the surrounding fork/join at a higher layer "
    "can substitute for... and it recurs inside `branch_b*` bodies "
    "themselves, not just at the top-level fork.'"
)

# ---------------------------------------------------------------------------
# The one real, cited dispatch/wait macro convention this codebase already
# documents (uvm_generator/templates/sim_scripts/check/pattern_rules.py's own
# R7 rule text). Matched against a CommandStatement's own backtick-prefixed
# `.name` field (e.g. "`FORK_SEQ"), never against free text.
# ---------------------------------------------------------------------------

DEFAULT_DISPATCH_PATTERN: Pattern[str] = re.compile(r"^`FORK_SEQ$")
DEFAULT_WAIT_PATTERN: Pattern[str] = re.compile(r"^`WAIT_SEQ_ALL(_OK)?$")

# branch_b* label: canonical 0-indexed `branch_b{i}` (branch_ownership_
# resolver.py's own naming rule) plus the real legacy bare `branch_b` shape
# pattern_rules.py's own docstring documents for the older two-branch shape.
# Naming CONFORMANCE is branch_ownership_resolver.py's job, not this module's
# -- a legacy label is still scoped and checked, never skipped.
_BRANCH_B_BEGIN_RE = re.compile(r"^begin\s*:\s*(branch_b\d*)\b")

# ---------------------------------------------------------------------------
# Vocabulary -- checked disjoint from the real stage-verdict vocabulary at
# import time, the same discipline several sibling analysis modules in this
# codebase already apply to their own domain vocabularies.
# ---------------------------------------------------------------------------

REGION_NO_DISPATCH_FOUND = "NO_DISPATCH_FOUND"
REGION_ALL_DISPATCHES_PAIRED = "ALL_DISPATCHES_PAIRED"
REGION_ORPHANED_DISPATCH_FOUND = "ORPHANED_DISPATCH_FOUND"
REGION_NEVER_CLOSED = "REGION_NEVER_CLOSED"
REGION_STATUSES = (
    REGION_NO_DISPATCH_FOUND, REGION_ALL_DISPATCHES_PAIRED,
    REGION_ORPHANED_DISPATCH_FOUND, REGION_NEVER_CLOSED,
)

FILE_CLEAN = "CLEAN"
FILE_FINDINGS_FOUND = "FINDINGS_FOUND"
FILE_NOT_APPLICABLE = "NOT_APPLICABLE"
FILE_UNREADABLE = "UNREADABLE"
FILE_STATUSES = (FILE_CLEAN, FILE_FINDINGS_FOUND, FILE_NOT_APPLICABLE, FILE_UNREADABLE)

_FILE_SEVERITY = {FILE_NOT_APPLICABLE: 0, FILE_CLEAN: 1, FILE_UNREADABLE: 2, FILE_FINDINGS_FOUND: 3}


def assert_no_verification_verdict_vocabulary() -> None:
    """`REGION_STATUSES`/`FILE_STATUSES` must share no token with
    `dv_harness.models.Status` -- this module's own detection vocabulary is
    not a stage-gate verdict and must never be read as one."""
    verdict_tokens = {s.value for s in Status}
    collision = (set(REGION_STATUSES) | set(FILE_STATUSES)) & verdict_tokens
    if collision:
        raise AssertionError(
            f"orphaned_fork_detection vocabulary collides with models.Status: {sorted(collision)}")


assert_no_verification_verdict_vocabulary()


class OrphanedForkDetectionError(ValueError):
    """Programmer misuse (e.g. an empty file list), never a could-not-check
    outcome -- those are reported as BLOCKED PatternFileReport values."""


# --- data model --------------------------------------------------------------

@dataclass
class DispatchCitation:
    line: int
    text: str
    macro: str

    def evidence(self, file_name: str) -> str:
        return f"{file_name}:{self.line}"

    def to_dict(self) -> Dict[str, Any]:
        return {"line": self.line, "text": self.text, "macro": self.macro}


@dataclass
class OrphanedDispatchFinding:
    branch_label: str
    dispatch: DispatchCitation
    reason: str
    trap_citation: str = TRAP_CITATION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branch_label": self.branch_label,
            "dispatch": self.dispatch.to_dict(),
            "reason": self.reason,
            "trap_citation": self.trap_citation,
        }


@dataclass
class BranchBRegionReport:
    branch_label: str
    begin_line: int
    end_line: Optional[int]
    close_kind: Optional[str]
    status: str
    dispatch_count: int
    wait_count: int
    dispatches: List[DispatchCitation] = field(default_factory=list)
    waits: List[DispatchCitation] = field(default_factory=list)
    findings: List[OrphanedDispatchFinding] = field(default_factory=list)
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branch_label": self.branch_label,
            "begin_line": self.begin_line,
            "end_line": self.end_line,
            "close_kind": self.close_kind,
            "status": self.status,
            "dispatch_count": self.dispatch_count,
            "wait_count": self.wait_count,
            "dispatches": [d.to_dict() for d in self.dispatches],
            "waits": [w.to_dict() for w in self.waits],
            "findings": [f.to_dict() for f in self.findings],
            "reason": self.reason,
        }


@dataclass
class PatternFileReport:
    file: str
    status: str
    regions: List[BranchBRegionReport] = field(default_factory=list)
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "status": self.status,
            "regions": [r.to_dict() for r in self.regions],
            "reason": self.reason,
        }


# --- region location -----------------------------------------------------------

def find_branch_b_regions(statements: Sequence) -> List[Dict[str, Any]]:
    """Locate every `begin : branch_b*` region in ONE file's already-parsed
    statement stream, using the REAL `block_depth` `reference_pattern_audit.
    extract_command_statements()` already computed per statement -- no depth
    counter is re-derived here.

    Returns a list of `{"branch_label", "begin_index", "begin_line",
    "close_index", "end_line", "close_kind"}` -- `close_index`/`end_line`/
    `close_kind` are `None` when no matching close was found before
    end-of-file (a real, honestly-reported structural defect, see
    `REGION_NEVER_CLOSED`).
    """
    regions: List[Dict[str, Any]] = []
    for idx, stmt in enumerate(statements):
        if stmt.kind != rpa.K_BLOCK_BEGIN:
            continue
        m = _BRANCH_B_BEGIN_RE.match(stmt.text)
        if not m:
            continue
        label = m.group(1)
        depth = stmt.block_depth
        close_index = None
        end_line = None
        close_kind = None
        for j in range(idx + 1, len(statements)):
            nxt = statements[j]
            if nxt.kind in (rpa.K_BLOCK_END, rpa.K_JOIN) and nxt.block_depth == depth:
                close_index = j
                end_line = nxt.line
                close_kind = "end" if nxt.kind == rpa.K_BLOCK_END else "join"
                break
        regions.append({
            "branch_label": label,
            "begin_index": idx,
            "begin_line": stmt.line,
            "close_index": close_index,
            "end_line": end_line,
            "close_kind": close_kind,
        })
    return regions


# --- per-region pairing check ---------------------------------------------------

def detect_orphaned_dispatches(
    statements: Sequence,
    region: Dict[str, Any],
    file_name: str,
    *,
    dispatch_pattern: Pattern[str] = DEFAULT_DISPATCH_PATTERN,
    wait_pattern: Pattern[str] = DEFAULT_WAIT_PATTERN,
) -> BranchBRegionReport:
    """The dispatch-then-wait pairing check for ONE located region, from the
    same statement stream `find_branch_b_regions()` was called over."""
    label = region["branch_label"]
    begin_line = region["begin_line"]
    close_index = region["close_index"]

    if close_index is None:
        # Best-effort visibility into what the (unbounded) rest of the file
        # contains, but the pairing conclusion is deliberately NOT computed --
        # see module docstring: a wait after an unproven boundary must never
        # be presented as evidence the trap does not apply here.
        tail = statements[region["begin_index"] + 1:]
        dispatches = [DispatchCitation(s.line, s.text, s.name) for s in tail
                      if s.kind == rpa.K_MACRO_CALL and dispatch_pattern.match(s.name)]
        waits = [DispatchCitation(s.line, s.text, s.name) for s in tail
                 if s.kind == rpa.K_MACRO_CALL and wait_pattern.match(s.name)]
        return BranchBRegionReport(
            branch_label=label, begin_line=begin_line, end_line=None, close_kind=None,
            status=REGION_NEVER_CLOSED, dispatch_count=len(dispatches), wait_count=len(waits),
            dispatches=dispatches, waits=waits, findings=[],
            reason=(f"no matching 'end'/'join' found for 'begin : {label}' at "
                    f"{file_name}:{begin_line} before end-of-file -- dispatch/wait "
                    f"pairing cannot be honestly bounded, so it was not evaluated"))

    body = statements[region["begin_index"] + 1:close_index]
    dispatches = [DispatchCitation(s.line, s.text, s.name) for s in body
                  if s.kind == rpa.K_MACRO_CALL and dispatch_pattern.match(s.name)]
    waits = [DispatchCitation(s.line, s.text, s.name) for s in body
             if s.kind == rpa.K_MACRO_CALL and wait_pattern.match(s.name)]
    wait_lines = sorted(w.line for w in waits)

    findings: List[OrphanedDispatchFinding] = []
    for d in dispatches:
        # A wait joins ALL outstanding dispatches at once, so any wait later
        # in program order satisfies this dispatch -- never a positional 1:1
        # count match (see module docstring).
        if not any(wl > d.line for wl in wait_lines):
            findings.append(OrphanedDispatchFinding(
                branch_label=label, dispatch=d,
                reason=(f"`{d.macro.lstrip('`')} dispatched at {file_name}:{d.line} inside "
                        f"'begin : {label}' has no `WAIT_SEQ_ALL(_OK)? statement anywhere "
                        f"after it before the branch's own close at "
                        f"{file_name}:{region['end_line']} -- {label} can report a result "
                        f"while this dispatch is still mid-flight")))

    if not dispatches:
        status = REGION_NO_DISPATCH_FOUND
    elif findings:
        status = REGION_ORPHANED_DISPATCH_FOUND
    else:
        status = REGION_ALL_DISPATCHES_PAIRED

    return BranchBRegionReport(
        branch_label=label, begin_line=begin_line, end_line=region["end_line"],
        close_kind=region["close_kind"], status=status, dispatch_count=len(dispatches),
        wait_count=len(waits), dispatches=dispatches, waits=waits, findings=findings,
        reason=None)


# --- per-file / per-directory entry points --------------------------------------

def analyze_pattern_text(
    text: str,
    file_name: str = "<text>",
    *,
    dispatch_pattern: Pattern[str] = DEFAULT_DISPATCH_PATTERN,
    wait_pattern: Pattern[str] = DEFAULT_WAIT_PATTERN,
) -> PatternFileReport:
    """Run the dispatch-then-wait pairing check over already-in-memory
    pattern text (used by the file/directory entry points below, and
    directly testable without touching a real filesystem path)."""
    import tempfile
    import os
    fd, tmp_path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        statements = rpa.extract_command_statements(Path(tmp_path))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    for s in statements:
        s.file = file_name

    regions = find_branch_b_regions(statements)
    if not regions:
        return PatternFileReport(
            file=file_name, status=FILE_NOT_APPLICABLE, regions=[],
            reason="no 'begin : branch_b*' region found in this file")

    region_reports = [
        detect_orphaned_dispatches(statements, r, file_name,
                                    dispatch_pattern=dispatch_pattern, wait_pattern=wait_pattern)
        for r in regions
    ]
    findings_present = any(
        r.status in (REGION_ORPHANED_DISPATCH_FOUND, REGION_NEVER_CLOSED)
        for r in region_reports)
    status = FILE_FINDINGS_FOUND if findings_present else FILE_CLEAN
    return PatternFileReport(file=file_name, status=status, regions=region_reports, reason=None)


def analyze_pattern_file(
    path,
    *,
    dispatch_pattern: Pattern[str] = DEFAULT_DISPATCH_PATTERN,
    wait_pattern: Pattern[str] = DEFAULT_WAIT_PATTERN,
) -> PatternFileReport:
    """Run the dispatch-then-wait pairing check over ONE real generated
    pattern file. Read-only -- never writes to `path`."""
    p = Path(path)
    if not p.is_file():
        return PatternFileReport(file=str(p), status=FILE_UNREADABLE, regions=[],
                                  reason=f"{p} does not exist or is not a file")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return PatternFileReport(file=str(p), status=FILE_UNREADABLE, regions=[],
                                  reason=f"could not read {p}: {e}")
    report = analyze_pattern_text(text, file_name=p.name, dispatch_pattern=dispatch_pattern,
                                   wait_pattern=wait_pattern)
    report.file = str(p)
    return report


def analyze_pattern_directory(
    pattern_dir,
    glob: str = "*.txt",
    *,
    dispatch_pattern: Pattern[str] = DEFAULT_DISPATCH_PATTERN,
    wait_pattern: Pattern[str] = DEFAULT_WAIT_PATTERN,
) -> Dict[str, Any]:
    """Run the pairing check over every file matching `glob` under
    `pattern_dir`, in sorted filename order. Read-only."""
    pattern_dir = Path(pattern_dir)
    paths = sorted(p for p in pattern_dir.glob(glob) if p.is_file())
    reports = [analyze_pattern_file(p, dispatch_pattern=dispatch_pattern, wait_pattern=wait_pattern)
               for p in paths]
    if reports:
        overall = max((r.status for r in reports), key=lambda s: _FILE_SEVERITY[s])
    else:
        overall = FILE_NOT_APPLICABLE
    total_findings = sum(
        1 for r in reports for reg in r.regions for _ in reg.findings)
    unclosed = sum(
        1 for r in reports for reg in r.regions if reg.status == REGION_NEVER_CLOSED)
    return {
        "pattern_dir": str(pattern_dir),
        "glob": glob,
        "files_scanned": [str(p) for p in paths],
        "reports": [r.to_dict() for r in reports],
        "overall_status": overall,
        "orphaned_dispatch_count": total_findings,
        "unclosed_region_count": unclosed,
    }


# --- rendering / CLI -------------------------------------------------------------

def format_report(report: PatternFileReport) -> str:
    lines = [f"FILE {report.file} -> {report.status}"
             + (f" ({report.reason})" if report.reason else "")]
    for region in report.regions:
        lines.append(f"  [{region.branch_label} @ line {region.begin_line}] {region.status}"
                     + (f" -- {region.reason}" if region.reason else ""))
        lines.append(f"      dispatches={region.dispatch_count} waits={region.wait_count}"
                     + (f" close={region.close_kind}@{region.end_line}" if region.end_line else ""))
        for f in region.findings:
            lines.append(f"      ORPHANED: {f.reason}")
    return "\n".join(lines)


def overall_exit_code(reports: Sequence[PatternFileReport]) -> int:
    if any(r.status == FILE_UNREADABLE for r in reports):
        return 2
    if any(r.status == FILE_FINDINGS_FOUND for r in reports):
        return 1
    return 0


def _parse_args(argv: Optional[Sequence[str]]):
    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.orphaned_fork_detection",
        description=("Detect a branch_b*-internal non-blocking VIP-sequence dispatch with "
                     "no paired explicit wait before that branch reports a result "
                     "(pattern-architecture SKILL.md section 3.5)."))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", action="append", dest="files", default=None,
                       help="a real generated pattern file to check; may be repeated")
    group.add_argument("--dir", dest="pattern_dir", default=None,
                       help="a directory of pattern files to check (glob-matched)")
    parser.add_argument("--glob", default="*.txt", help="glob used with --dir (default: *.txt)")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    if args.files:
        reports = [analyze_pattern_file(f) for f in args.files]
        if args.json:
            print(json.dumps([r.to_dict() for r in reports], indent=2))
        else:
            for r in reports:
                print(format_report(r))
        return overall_exit_code(reports)

    result = analyze_pattern_directory(args.pattern_dir, glob=args.glob)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for r in result["reports"]:
            print(format_report(PatternFileReport(
                file=r["file"], status=r["status"], reason=r["reason"],
                regions=[BranchBRegionReport(
                    branch_label=reg["branch_label"], begin_line=reg["begin_line"],
                    end_line=reg["end_line"], close_kind=reg["close_kind"],
                    status=reg["status"], dispatch_count=reg["dispatch_count"],
                    wait_count=reg["wait_count"],
                    dispatches=[DispatchCitation(**d) for d in reg["dispatches"]],
                    waits=[DispatchCitation(**w) for w in reg["waits"]],
                    findings=[OrphanedDispatchFinding(
                        branch_label=f["branch_label"],
                        dispatch=DispatchCitation(**f["dispatch"]),
                        reason=f["reason"], trap_citation=f["trap_citation"])
                        for f in reg["findings"]],
                    reason=reg["reason"]) for reg in r["regions"]])))
        print(f"\nOVERALL: {result['overall_status']} "
              f"(orphaned_dispatches={result['orphaned_dispatch_count']}, "
              f"unclosed_regions={result['unclosed_region_count']})")
    return 0 if result["overall_status"] in (FILE_CLEAN, FILE_NOT_APPLICABLE) else (
        2 if result["overall_status"] == FILE_UNREADABLE else 1)


execute_verb = main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
