"""dv_harness/scenario_pattern_command_txt_correspondence.py -- audit-first closure of a real gap:
cross-reference `vip_capability_extraction.py`'s real, classified `VIPScenarioPatternIR` entries
(VIP-declared sequence/vseq classes) against a project's real command.txt/pattern `branch_b*`
(VIP-owned) sequence USAGES, so "VIP declares this sequence pattern exists" and "command.txt
actually uses it correctly" become one checkable fact instead of two things nobody ever compared
-- 2026-09-07.

AUDIT-FIRST FINDING (confirmed by direct search of this repo before writing a line of analysis
logic here, per this item's own instruction)
------------------------------------------------------------------------------------------------
No existing mechanism performs this cross-check. Confirmed by reading, not assumed:

- `vip_capability_extraction.py` classifies VIP-indexed classes into `VIPScenarioPatternIR`
  (`IR_VIP_SCENARIO_PATTERN`) -- a purely STATIC classification over the VIP's OWN declared
  classes. It never opens a command.txt/pattern file, and a repo-wide grep for
  `IR_VIP_SCENARIO_PATTERN` / `VIPScenarioPatternIR` before this module was written found exactly
  one file using that IR type: `vip_capability_extraction.py` itself.
- `command_task_trace.py`'s VIP_API leg finds a `// VIP:` citation comment (or a declared
  `vip_prefixes` identifier) inside ONE already-generated environment directory's own `.sv`/`.svh`
  files -- it never reads a `command.txt`/pattern file's own text, and it never has a
  `VIPScenarioPatternIR` record set to check a citation against; it reports the citation exists,
  never whether it corresponds to a real, classified VIP sequence class.
- `de_command_style_learning.py` already guesses a per-statement `branch_owner` (GLOBAL/DUT/FW/VIP)
  from a command.txt's own text, including a real, name-evidence-only VIP-sequence guess for a
  `MODEL_TASK_CALL` statement whose name matches `VIP_TASK_NAME_TOKENS` -- but it never cross-checks
  that guessed VIP usage against `vip_capability_extraction.py`'s real classification at all; its
  own module docstring states its scope stops at "what does this file's OWN text say", never "does
  this correspond to a real VIP artifact".
- `vip_config_field_usage_coverage.py` is the real, existing PRECEDENT for exactly this SHAPE of
  cross-check (`vip_capability_extraction.py`'s `VIPConfigIR` declared config FIELDS vs. real
  command.txt usage), but over a completely different IR type and a completely different fact
  (field usage, not sequence-pattern correspondence) -- it never touches `IR_VIP_SCENARIO_PATTERN`
  at all. This module follows that same precedent's shape (the same two-directional
  used/unused-plus-fabrication-risk report, the same honest `NOT_AVAILABLE` discipline, the same
  word-boundary name-evidence matching) applied to the missing ScenarioPatternIR axis, rather than
  inventing a fourth report shape for a fourth kind of cross-check.

So the gap named by this item -- "does a generated command.txt's `branch_b*` sequence usage
actually correspond to a real, classified VIP scenario pattern" -- was genuinely open, and this
module closes it.

WHAT "BRANCH_B* USAGE" MEANS HERE, AND WHY -- REUSE, NEVER A SECOND BRANCH-LABEL SCANNER
------------------------------------------------------------------------------------------
This module does not scan a command.txt for literal `fork ... : branch_b0` block labels -- doing
so would be a SECOND, competing branch-ownership heuristic sitting beside
`de_command_style_learning.py`'s own real one, and this project's own house rule (REUSE OVER
REINVENT) forbids exactly that. "A `branch_b*` sequence usage" is defined here, honestly and
narrowly, as: a real command.txt/pattern statement `de_command_style_learning.build_de_command_
registry()` itself classified as `kind == K_MODEL_TASK_CALL` AND `branch_owner ==
BRANCH_OWNER_VIP` -- that module's OWN real, cited, name-evidence guess that a model-task-call
statement is VIP-sequence-shaped (`.claude/skills/CORE/branch-mapper/SKILL.md`'s `branch_b*` =
VIP-driven parallel tasks). A statement that module could not confidently classify as VIP-owned
(branch_owner UNKNOWN/GLOBAL/DUT/FW) is never treated as a `branch_b*` usage by this module either
-- inheriting that module's own honesty rather than re-deriving a stronger (or weaker) one. This
bound is disclosed, not hidden: a real `branch_b*` sequence dispatch shaped in a way `de_command_
style_learning.py`'s own heuristic does not recognise (e.g. a bare macro call with the sequence
name only in an argument, never a dotted `MODEL_TASK_CALL`) is invisible to this module too.

WHAT "CORRESPONDS" MEANS, AND ITS HONEST LIMIT
-------------------------------------------------
A `branch_b*` usage CORRESPONDS to a declared `VIPScenarioPatternIR` class when a real, cited
textual match is found between the usage and the class's own real `class_name`:
  - `PRIMARY_TASK_SEGMENT_EXACT` -- the usage's own dotted MODEL_TASK_CALL name (e.g.
    `` `HOST_SEQ.svt_demo_base_sequence ``) has a task segment (the text after the last `.`) that
    is EXACTLY the declared class name -- the strongest evidence this module can produce, since
    that segment is the real name the command.txt statement itself invokes.
  - `TEXT_OR_ARGUMENT_REFERENCE` -- the class name appears, word-boundary matched, in the usage's
    own raw statement text or one of its arguments (e.g. the class name is passed as an argument
    to a dispatcher task) -- weaker evidence, carried and labeled as such, never presented as if it
    were the same strength as an exact task-segment match.
A usage matching NEITHER is `CORRESPONDENCE_NOT_FOUND` -- the real fabrication-risk finding this
module exists to surface: a command.txt statement this project's own heuristic believes is a
VIP-sequence dispatch, naming something no real, classified `VIPScenarioPatternIR` class in the
supplied classification set corresponds to. This is NEVER proof the named VIP sequence does not
exist anywhere in the real VIP -- only that it does not correspond to anything the SUPPLIED
`vip_capability_extraction` classification (built over whatever VIP source that caller actually
indexed) found. A narrower/incomplete VIP index supplied to `vip_capability_extraction.py` will
under-classify, and this module inherits that honestly rather than silently assuming a wider index
than was actually built.

THE REVERSE DIRECTION: A DECLARED PATTERN NEVER REFERENCED AT ALL
---------------------------------------------------------------------
Symmetrically, a real, classified `VIPScenarioPatternIR` class that no `branch_b*` usage in the
scanned command.txt/pattern set ever names (by either match kind) is `NOT_USED_IN_COMMAND_TXT` --
an honest "declared, never dispatched" finding, mirroring `vip_config_field_usage_coverage.py`'s
own DEAD_OR_UNUSED discipline for fields rather than classes. A project scanning real command.txt
files that genuinely contain ZERO `branch_b*` usage at all is not silently reported `NOT_AVAILABLE`
for that reason alone -- real files WERE scanned, and "this VIP declares scenario patterns nobody's
command.txt ever dispatches" is itself a real, actionable, ANALYZED finding, never hidden behind an
absence-of-evidence status that would apply only when nothing could be checked at all.

REUSE, NOT REINVENTION
-----------------------
This module builds no second VIP indexer, no second command.txt statement parser, and no second
branch-ownership heuristic:
- `vip_capability_extraction.IR_VIP_SCENARIO_PATTERN` / `VIPCapabilityExtractionReport.by_ir_type()`
  are the ONLY way this module ever obtains the declared scenario-pattern class list -- called
  read-only, never re-derived. A caller with a real, already-built report (or its own written
  `vip_capability_extraction.json`) hands it here directly, exactly as `vip_config_field_usage_
  coverage.py` already does for `IR_VIP_CONFIG`.
- `de_command_style_learning.build_de_command_registry()` (and, transitively,
  `reference_pattern_audit.extract_command_statements()`) is the ONLY way this module ever reads a
  command.txt/pattern file or decides a statement's `branch_owner` -- never a second parser, never a
  second guess.

THE FABRICATION RISK, AND HOW THIS MODULE IS BUILT TO REFUSE IT
------------------------------------------------------------------
`CORRESPONDENCE_NOT_FOUND` and `NOT_USED_IN_COMMAND_TXT` are never asserted from silence. Both are
reported only after this module has REALLY built at least one real `DECommandRegistryIR` from a
real, readable command.txt/pattern file -- the report's own `command_files_scanned` count, and each
finding's own `reason` text, name exactly how many real files were checked. Supplying zero
scenario-pattern records, zero command files, or command files that all fail to read (a real path
that does not exist, a real permission error, a real decode error -- named per-file in
`unreadable_command_files`, never silently swallowed) makes the WHOLE report `NOT_AVAILABLE` with a
real, distinct reason -- never a report that quietly claims every usage is a fabrication, or every
declared pattern is dead, because nothing was actually checked.

DELIBERATELY BOUNDED, AND STATED RATHER THAN IMPLIED CLOSED
--------------------------------------------------------------
(1) This is a NAME-EVIDENCE textual cross-reference over `de_command_style_learning.py`'s own
    already-classified statements, never a semantic proof that the matched statement actually
    dispatches an instance of that VIP sequence class at elaboration/run time.
(2) `branch_b*` usage scope is exactly `de_command_style_learning.py`'s own real `MODEL_TASK_CALL` +
    `branch_owner == VIP` heuristic -- a real VIP-sequence dispatch shaped differently (a bare macro
    call whose sequence name lives only in an argument with no dotted MODEL_TASK_CALL shape, for
    example) is invisible to this module, exactly as it is invisible to the module it reuses.
(3) `CORRESPONDENCE_NOT_FOUND` proves absence from the SUPPLIED classification set only -- never
    absence from the real VIP itself, which depends entirely on how completely the caller's own
    `vip_capability_extraction` run indexed the real VIP source.
(4) It decides nothing beyond reporting: no build, no job, no approval, no stage gate, and it
    weakens no human-approval gate anywhere.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import de_command_style_learning as dcsl
from . import vip_capability_extraction

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# vocabulary -- deliberately disjoint from both reused modules' own vocabularies
# (vip_capability_extraction.py's 5-level qualification scale, and
# de_command_style_learning.py's KNOWN/PARTIAL/AMBIGUOUS/UNSUPPORTED/DEPRECATED/UNKNOWN).
# ---------------------------------------------------------------------------

USAGE_CORRESPONDENCE_CONFIRMED = "CORRESPONDENCE_CONFIRMED"
USAGE_CORRESPONDENCE_NOT_FOUND = "CORRESPONDENCE_NOT_FOUND"
USAGE_STATUSES: Tuple[str, ...] = (USAGE_CORRESPONDENCE_CONFIRMED, USAGE_CORRESPONDENCE_NOT_FOUND)

PATTERN_USED = "USED_IN_COMMAND_TXT"
PATTERN_NOT_USED = "NOT_USED_IN_COMMAND_TXT"
PATTERN_STATUSES: Tuple[str, ...] = (PATTERN_USED, PATTERN_NOT_USED)

MATCH_PRIMARY_TASK_SEGMENT_EXACT = "PRIMARY_TASK_SEGMENT_EXACT"
MATCH_TEXT_OR_ARGUMENT_REFERENCE = "TEXT_OR_ARGUMENT_REFERENCE"

REPORT_ANALYZED = "ANALYZED"
REPORT_NOT_AVAILABLE = "NOT_AVAILABLE"


class ScenarioPatternCommandTxtCorrespondenceError(ValueError):
    """A malformed input this module refuses to guess past -- e.g. a
    VIPScenarioPatternIR record with no resolvable class name."""


# ---------------------------------------------------------------------------
# reuse: pulling VIPScenarioPatternIR records out of a real
# vip_capability_extraction report, never re-classifying anything.
# ---------------------------------------------------------------------------

def scenario_pattern_records_from_capability_report(
    report: "vip_capability_extraction.VIPCapabilityExtractionReport",
) -> List["vip_capability_extraction.VIPCapabilityRecord"]:
    """The real VIP-declared scenario-pattern class records out of an already-built
    capability-extraction report -- calls that module's own `by_ir_type()`, never a second
    filter over `report.items`."""
    return report.by_ir_type(vip_capability_extraction.IR_VIP_SCENARIO_PATTERN)


def scenario_pattern_records_from_capability_report_dict(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The same real records, read from an on-disk `vip_capability_extraction.json` document
    (`write_capability_extraction_report()`'s own output) rather than an in-memory report object --
    filters `items` by the SAME real `ir_type` constant, never a re-typed string literal."""
    return [item for item in (data.get("items") or [])
            if item.get("ir_type") == vip_capability_extraction.IR_VIP_SCENARIO_PATTERN]


def _rec_get(rec: Any, attr: str, default: Any = None) -> Any:
    """Duck-typed field access over either a real `VIPCapabilityRecord` dataclass instance or a
    plain dict (e.g. one read back from a written `vip_capability_extraction.json`)."""
    if isinstance(rec, dict):
        return rec.get(attr, default)
    return getattr(rec, attr, default)


# ---------------------------------------------------------------------------
# reuse: scanning real command.txt/pattern files through de_command_style_learning.py's
# own real parser + branch_owner heuristic, never a second implementation of either.
# ---------------------------------------------------------------------------

def scan_command_registries(
    paths: Iterable,
) -> Tuple[List["dcsl.DECommandRegistryIR"], int, List[Dict[str, str]]]:
    """Read every supplied command.txt/pattern path with the REAL
    `de_command_style_learning.build_de_command_registry()` -- read-only, never a second
    statement-parsing or branch-ownership implementation.

    Returns `(registries, files_scanned, unreadable_files)`. A path this module cannot read
    (missing, a real permission error, a real decode error) is recorded in `unreadable_files` and
    never crashes the scan of the remaining paths -- a bad path must never silently look like
    "nothing to check" for the other, real ones."""
    registries: List["dcsl.DECommandRegistryIR"] = []
    scanned = 0
    unreadable: List[Dict[str, str]] = []
    for raw in paths or []:
        p = Path(raw)
        try:
            registry = dcsl.build_de_command_registry(p)
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append({"path": str(p), "reason": f"{type(exc).__name__}: {exc}"})
            continue
        scanned += 1
        registries.append(registry)
    return registries, scanned, unreadable


def branch_b_sequence_usages(
    registries: Sequence["dcsl.DECommandRegistryIR"],
) -> List[Tuple[str, "dcsl.DECommandEntry"]]:
    """Every real `(source_file, DECommandEntry)` pair `de_command_style_learning.py`'s own real
    heuristic classified as a `MODEL_TASK_CALL` statement with `branch_owner == BRANCH_OWNER_VIP`
    -- this module's own honest, disclosed definition of "a branch_b* sequence usage" (see module
    docstring). Never re-derived from a second branch-label scan."""
    out: List[Tuple[str, "dcsl.DECommandEntry"]] = []
    for registry in registries:
        for entry in registry.entries:
            if entry.kind == dcsl.K_MODEL_TASK_CALL and entry.branch_owner == dcsl.BRANCH_OWNER_VIP:
                out.append((registry.source_file, entry))
    return out


# ---------------------------------------------------------------------------
# name-evidence matching -- real, cited textual co-occurrence only.
# ---------------------------------------------------------------------------

def extract_primary_task_segment(command_name: str) -> Optional[str]:
    """The real invoked task NAME out of a `de_command_style_learning.py`-shaped dotted
    MODEL_TASK_CALL name (e.g. `` `HOST_SEQ.svt_demo_base_sequence `` -> `svt_demo_base_sequence`).
    `None` when the command name carries no dotted task segment at all (a bare macro-root call)."""
    name = (command_name or "").lstrip("`")
    if "." not in name:
        return None
    return name.rsplit(".", 1)[-1]


def match_usage_to_pattern(
    entry: "dcsl.DECommandEntry", class_name: str,
) -> Optional[Dict[str, Any]]:
    """Real, cited evidence that `entry` corresponds to `class_name`, or `None`. Tries the
    strongest evidence (an exact match on the entry's own primary task segment) before the weaker
    one (a word-boundary reference anywhere in the entry's raw text or arguments) -- the two are
    never conflated, and this function never returns a match with no real citation."""
    task_segment = extract_primary_task_segment(entry.command_name)
    if task_segment is not None and task_segment == class_name:
        return {
            "match_kind": MATCH_PRIMARY_TASK_SEGMENT_EXACT,
            "detail": entry.command_name,
            "evidence": entry.first_evidence,
        }
    pattern = re.compile(r"\b" + re.escape(class_name) + r"\b")
    haystacks: List[str] = [entry.raw_text] + list(entry.arguments)
    for h in haystacks:
        if h and pattern.search(h):
            return {
                "match_kind": MATCH_TEXT_OR_ARGUMENT_REFERENCE,
                "detail": h,
                "evidence": entry.first_evidence,
            }
    return None


# ---------------------------------------------------------------------------
# the artifact
# ---------------------------------------------------------------------------

@dataclass
class BranchBUsageRecord:
    command_name: str
    source_file: str
    status: str
    de_command_status: str
    de_command_basis: str
    matched_class_name: Optional[str] = None
    match_kind: Optional[str] = None
    evidence: Optional[str] = None
    detail: Optional[str] = None
    reason: Optional[str] = None
    occurrence_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DeclaredPatternUsage:
    class_name: str
    class_file: str
    class_line: int
    pattern_kind: Optional[str] = None
    ir_qualification: Optional[str] = None
    status: str = PATTERN_NOT_USED
    used_by: List[Dict[str, Any]] = field(default_factory=list)
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioPatternCorrespondenceReport:
    status: str
    reason: Optional[str] = None
    declared_patterns: List[DeclaredPatternUsage] = field(default_factory=list)
    branch_b_usages: List[BranchBUsageRecord] = field(default_factory=list)
    command_files_scanned: int = 0
    unreadable_command_files: List[Dict[str, str]] = field(default_factory=list)
    total_declared_patterns: int = 0
    total_used_patterns: int = 0
    total_unused_patterns: int = 0
    total_branch_b_usages: int = 0
    total_confirmed_usages: int = 0
    total_unresolved_usages: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["declared_patterns"] = [p.to_dict() for p in self.declared_patterns]
        d["branch_b_usages"] = [u.to_dict() for u in self.branch_b_usages]
        return d

    def unresolved_usages(self) -> List[BranchBUsageRecord]:
        return [u for u in self.branch_b_usages if u.status == USAGE_CORRESPONDENCE_NOT_FOUND]

    def unused_patterns(self) -> List[DeclaredPatternUsage]:
        return [p for p in self.declared_patterns if p.status == PATTERN_NOT_USED]


# ---------------------------------------------------------------------------
# the analyzer
# ---------------------------------------------------------------------------

def analyze_scenario_pattern_command_txt_correspondence(
    scenario_pattern_records: Optional[Iterable[Any]],
    command_file_paths: Optional[Iterable],
) -> ScenarioPatternCorrespondenceReport:
    """Cross-reference every real declared `VIPScenarioPatternIR` class in
    `scenario_pattern_records` (a real `vip_capability_extraction` record list -- see
    `scenario_pattern_records_from_capability_report()`/`..._dict()`) against every real
    `branch_b*` (VIP-owned MODEL_TASK_CALL) statement found in `command_file_paths`, reporting
    CORRESPONDENCE_CONFIRMED/CORRESPONDENCE_NOT_FOUND per usage and USED_IN_COMMAND_TXT/
    NOT_USED_IN_COMMAND_TXT per declared pattern.

    Supplying no scenario-pattern records, no command files, or command files that all fail to
    read honestly reports the WHOLE thing NOT_AVAILABLE rather than a report that fabricates a
    fabrication-risk or dead-pattern finding from evidence that was never actually gathered."""
    records = list(scenario_pattern_records or [])
    report = ScenarioPatternCorrespondenceReport(status="PENDING")

    if not records:
        report.status = REPORT_NOT_AVAILABLE
        report.reason = "NO_VIP_SCENARIO_PATTERN_IR_RECORDS_SUPPLIED"
        return report

    paths = list(command_file_paths or [])
    if not paths:
        report.status = REPORT_NOT_AVAILABLE
        report.reason = "NO_COMMAND_TXT_PATTERN_FILES_SUPPLIED"
        return report

    registries, scanned, unreadable = scan_command_registries(paths)
    report.command_files_scanned = scanned
    report.unreadable_command_files = unreadable

    if scanned == 0:
        report.status = REPORT_NOT_AVAILABLE
        report.reason = "NO_COMMAND_TXT_PATTERN_FILE_COULD_BE_READ"
        return report

    usages = branch_b_sequence_usages(registries)

    # Build the declared-pattern side first so class identity is validated up front.
    class_entries: List[Tuple[str, Any]] = []
    for rec in records:
        cls_name = _rec_get(rec, "class_name")
        if not cls_name:
            raise ScenarioPatternCommandTxtCorrespondenceError(
                "a VIPScenarioPatternIR record with no resolvable class_name cannot be reported "
                f"against -- record was: {rec!r}")
        class_entries.append((str(cls_name), rec))

    patterns_by_name: Dict[str, DeclaredPatternUsage] = {}
    for cls_name, rec in class_entries:
        patterns_by_name[cls_name] = DeclaredPatternUsage(
            class_name=cls_name,
            class_file=str(_rec_get(rec, "file", default="") or ""),
            class_line=int(_rec_get(rec, "line", default=0) or 0),
            pattern_kind=_rec_get(rec, "pattern_kind"),
            ir_qualification=_rec_get(rec, "qualification"),
        )

    usage_records: List[BranchBUsageRecord] = []
    for source_file, entry in usages:
        best: Optional[Dict[str, Any]] = None
        best_class: Optional[str] = None
        for cls_name, _rec in class_entries:
            m = match_usage_to_pattern(entry, cls_name)
            if m is None:
                continue
            if m["match_kind"] == MATCH_PRIMARY_TASK_SEGMENT_EXACT:
                best, best_class = m, cls_name
                break
            if best is None:
                best, best_class = m, cls_name

        if best is not None:
            status = USAGE_CORRESPONDENCE_CONFIRMED
            reason = None
            patterns_by_name[best_class].status = PATTERN_USED
            patterns_by_name[best_class].used_by.append({
                "command_name": entry.command_name, "source_file": source_file,
                "match_kind": best["match_kind"], "evidence": best["evidence"],
            })
        else:
            status = USAGE_CORRESPONDENCE_NOT_FOUND
            reason = (
                f"scanned {scanned} real command.txt/pattern file(s) against "
                f"{len(class_entries)} real declared VIPScenarioPatternIR class(es); no exact "
                f"primary-task-segment match and no word-boundary text/argument reference to "
                f"{entry.command_name!r} corresponds to any of them"
            )

        usage_records.append(BranchBUsageRecord(
            command_name=entry.command_name, source_file=source_file, status=status,
            de_command_status=entry.status, de_command_basis=entry.basis,
            matched_class_name=best_class, match_kind=(best["match_kind"] if best else None),
            evidence=(best["evidence"] if best else entry.first_evidence),
            detail=(best["detail"] if best else None),
            reason=reason, occurrence_count=entry.occurrence_count,
        ))

    for pattern in patterns_by_name.values():
        if pattern.status == PATTERN_NOT_USED:
            pattern.reason = (
                f"scanned {scanned} real command.txt/pattern file(s) containing "
                f"{len(usages)} real branch_b* (VIP-owned MODEL_TASK_CALL) usage(s); none named "
                f"{pattern.class_name!r} by an exact primary-task-segment match or a "
                f"word-boundary text/argument reference"
            )

    report.declared_patterns = [patterns_by_name[name] for name, _ in class_entries]
    report.branch_b_usages = usage_records
    report.total_declared_patterns = len(report.declared_patterns)
    report.total_used_patterns = sum(1 for p in report.declared_patterns if p.status == PATTERN_USED)
    report.total_unused_patterns = report.total_declared_patterns - report.total_used_patterns
    report.total_branch_b_usages = len(usage_records)
    report.total_confirmed_usages = sum(
        1 for u in usage_records if u.status == USAGE_CORRESPONDENCE_CONFIRMED)
    report.total_unresolved_usages = report.total_branch_b_usages - report.total_confirmed_usages
    report.status = REPORT_ANALYZED
    return report


# ---------------------------------------------------------------------------
# rendering / artifact I/O / CLI
# ---------------------------------------------------------------------------

CORRESPONDENCE_REPORT_NAME = "scenario_pattern_command_txt_correspondence.json"


def format_report(report: ScenarioPatternCorrespondenceReport) -> str:
    lines = [f"VIP ScenarioPatternIR <-> command.txt branch_b* correspondence: {report.status}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    lines.append(f"  command.txt/pattern files scanned: {report.command_files_scanned}")
    if report.unreadable_command_files:
        lines.append(f"  unreadable files ({len(report.unreadable_command_files)}):")
        for u in report.unreadable_command_files:
            lines.append(f"    {u['path']}: {u['reason']}")
    if report.status != REPORT_ANALYZED:
        return "\n".join(lines)

    lines.append(
        f"  declared patterns: total={report.total_declared_patterns}, "
        f"used={report.total_used_patterns}, unused={report.total_unused_patterns}")
    lines.append(
        f"  branch_b* usages: total={report.total_branch_b_usages}, "
        f"confirmed={report.total_confirmed_usages}, unresolved={report.total_unresolved_usages}")

    if report.branch_b_usages:
        lines.append("")
        lines.append("  branch_b* usages:")
        for u in report.branch_b_usages:
            if u.status == USAGE_CORRESPONDENCE_CONFIRMED:
                lines.append(
                    f"    [CONFIRMED]  {u.command_name} -> {u.matched_class_name} "
                    f"({u.match_kind}) at {u.evidence}")
            else:
                lines.append(f"    [NOT_FOUND]  {u.command_name} at {u.evidence}")

    if report.declared_patterns:
        lines.append("")
        lines.append("  declared VIPScenarioPatternIR classes:")
        for p in report.declared_patterns:
            if p.status == PATTERN_USED:
                lines.append(
                    f"    [USED]       {p.class_name} ({len(p.used_by)} usage(s)) "
                    f"at {p.class_file}:{p.class_line}")
            else:
                lines.append(f"    [NOT_USED]   {p.class_name} at {p.class_file}:{p.class_line}")
    return "\n".join(lines)


def write_correspondence_report(report: ScenarioPatternCorrespondenceReport, out_dir) -> Path:
    """Write the correspondence artifact. No timestamp anywhere, so an unchanged input regenerates
    byte-identically."""
    path = Path(out_dir) / CORRESPONDENCE_REPORT_NAME
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


_STATUS_EXIT = {REPORT_NOT_AVAILABLE: 2}


def execute_verb(
    capability_report_path, command_files: Sequence, *, as_json: bool = False, out_dir=None,
) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.scenario_pattern_command_txt_correspondence`.
    Returns `(text, exit_code)`: 0 every branch_b* usage corresponds and every declared pattern is
    used, 1 at least one real CORRESPONDENCE_NOT_FOUND or NOT_USED_IN_COMMAND_TXT finding, 2
    NOT_AVAILABLE."""
    cap_path = Path(capability_report_path)
    if not cap_path.exists():
        raise ScenarioPatternCommandTxtCorrespondenceError(
            f"capability-extraction report does not exist: {capability_report_path} -- build one "
            "with dv_harness.vip_capability_extraction first")
    data = json.loads(cap_path.read_text(encoding="utf-8"))
    records = scenario_pattern_records_from_capability_report_dict(data)

    report = analyze_scenario_pattern_command_txt_correspondence(records, command_files)
    if out_dir:
        write_correspondence_report(report, out_dir)
    text = json.dumps(report.to_dict(), indent=2) if as_json else format_report(report)
    code = _STATUS_EXIT.get(report.status, 0)
    if report.status == REPORT_ANALYZED and (
            report.total_unresolved_usages or report.total_unused_patterns):
        code = 1
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.scenario_pattern_command_txt_correspondence",
        description="Cross-reference vip_capability_extraction.py's VIPScenarioPatternIR declared "
                    "sequence-pattern classes against a project's real command.txt/pattern "
                    "branch_b* (VIP-owned) sequence usages, reporting CORRESPONDENCE_CONFIRMED/"
                    "CORRESPONDENCE_NOT_FOUND per usage and USED/NOT_USED per declared pattern.")
    ap.add_argument("--capability-report", required=True,
                    help="A vip_capability_extraction.json document (write_capability_extraction_"
                         "report()'s own output).")
    ap.add_argument("--command-file", action="append", default=None, dest="command_files",
                    help="A real command.txt/pattern file to scan (repeatable).")
    ap.add_argument("--out-dir", default=None,
                    help="Also write scenario_pattern_command_txt_correspondence.json here.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(
            a.capability_report, a.command_files or [], as_json=a.json, out_dir=a.out_dir)
    except (ScenarioPatternCommandTxtCorrespondenceError, json.JSONDecodeError) as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
