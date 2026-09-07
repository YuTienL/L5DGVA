"""dv_harness/vip_config_field_usage_coverage.py -- cross-reference `vip_capability_extraction.py`'s
VIPConfigIR (declared config knobs) against a project's real command.txt/pattern set, to report which
declared config FIELDS are actually EXERCISED (a real, cited textual reference found in a real
command.txt/pattern statement) versus DEAD_OR_UNUSED (real files were scanned, and the field genuinely
never appears) -- 2026-09-07.

THE GAP THIS CLOSES
-------------------
`vip_capability_extraction.py` classifies WHICH VIP-indexed classes are shaped like config objects
(`VIPConfigIR`), and carries each config class's own declared `config_fields` -- name/data_type/
file/line, taken straight from `vip_symbol_index.py`'s real declaration scan. It answers a purely
STATIC question: "is this class a config object, and how sure are we". It never asks whether any of
the individual FIELDS that class declares are ever actually touched anywhere in a real project's own
command.txt/pattern files -- a real usage-COVERAGE gap on a completely different axis, never re-run
by, and never re-running, that module's own classification. A config class can be a rock-solid
PROJECT_PROVEN `VIPConfigIR` and still declare a field nobody ever sets -- a dead knob this project's
own generators/reviewers had no way to see before this module.

REUSE, NOT REINVENTION
-----------------------
This module builds no second VIP indexer and no second command.txt parser.
- `vip_capability_extraction.IR_VIP_CONFIG` / `VIPCapabilityExtractionReport.by_ir_type()` are the
  ONLY way this module ever obtains the config-class/field list -- called read-only, never
  re-derived. A caller who already has a real classification report (from
  `vip_capability_extraction.extract_vip_capabilities()`/`classify_vip_source()`/
  `load_index_and_classify()`, or its own written `vip_capability_extraction.json`) hands it here
  directly.
- `reference_pattern_audit.extract_command_statements()` is the ONLY way this module ever reads a
  command.txt/pattern file -- the same real, comment-aware, bracket-depth-tracking statement parser
  SYS-7's own command-inventory machinery already uses. This module never re-implements comment
  stripping or statement splitting.

WHAT "EXERCISED" MEANS, AND ITS HONEST LIMIT
----------------------------------------------
A field is EXERCISED when its literal declared NAME appears, as a whole identifier (word-boundary
matched, so a field named `en` is never mistaken for a hit inside `wr_en_field`), inside a real
command STATEMENT's own comment-stripped CODE text -- never inside that statement's trailing comment,
since a comment mention is materially weaker evidence than a real code reference and this module never
presents the two as if they carried the same weight. Exactly like `reference_pattern_audit.
classify_wait()`'s own `matched_tokens` classification, this is NAME-EVIDENCE: a real, cited textual
co-occurrence, never a claim that this project's own VIP config object is actually instantiated,
configured, or driven by that exact statement -- VIP config fields are usually set from SystemVerilog
UVM code this module never reads, not from command.txt, so a field this module marks DEAD_OR_UNUSED
may still be legitimately set elsewhere; this module's own scope is strictly "does the field's name
appear anywhere in the real command.txt/pattern set supplied", stated as narrowly as that.

THE FABRICATION RISK, AND HOW THIS MODULE IS BUILT TO REFUSE IT
------------------------------------------------------------------
DEAD_OR_UNUSED is never asserted from silence. A field is reported DEAD_OR_UNUSED only after this
module has REALLY scanned at least one real command.txt/pattern file and found no match -- the
report's own `command_files_scanned` count and each field's own `reason` text name exactly how many
real files were checked, so "we looked and found nothing" is never presented the same way as "we never
looked". Supplying zero config records, zero command files, or command files that all fail to read
(the real path does not exist, a real permission error, a real decode error -- named per-file in
`unreadable_command_files`, never silently swallowed) makes the WHOLE report `NOT_AVAILABLE` with a
real, distinct reason -- never a report that quietly claims every field is dead because nothing was
actually checked.

WHAT MAKES THIS DIFFERENT FROM vip_capability_extraction.py'S OWN QUALIFICATION VOCABULARY
----------------------------------------------------------------------------------------------
That module's 5-level qualification (PROJECT_PROVEN/VIP_DOCUMENTED/VIP_EXAMPLE_MATCHED/
INFERRED_FROM_NAMING/UNKNOWN) answers "how sure are we this CLASS really is a config object". This
module's own, deliberately separate 2-value vocabulary (EXERCISED/DEAD_OR_UNUSED) answers a completely
different question about each individual FIELD: "does a real command.txt/pattern statement anywhere
in this project's own real command set actually name this field". A class can be PROJECT_PROVEN and
still declare ten DEAD_OR_UNUSED fields; the two vocabularies are never merged, and this module never
assigns qualification to anything.

DELIBERATELY BOUNDED, AND STATED RATHER THAN IMPLIED CLOSED
--------------------------------------------------------------
(1) This is a NAME-EVIDENCE textual scan over declaration-stripped statement CODE, never a semantic
    proof that the matched statement is the thing that actually configures the field, and never a
    claim the field is unused elsewhere (SystemVerilog UVM test code, a `.f` filelist macro define,
    or any source this module does not read).
(2) A generic/short field name (`id`, `en`, `mode`) can genuinely co-occur with an unrelated
    identifier of the same name elsewhere in a command.txt -- this module reports the real match it
    found; it never judges whether that match is semantically meaningful.
(3) It decides nothing beyond reporting: no build, no job, no approval, no stage gate, and it weakens
    no human-approval gate anywhere.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import reference_pattern_audit
from . import vip_capability_extraction

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# vocabulary -- deliberately disjoint from vip_capability_extraction.py's own
# 5-level qualification scale (a different question, over a different axis).
# ---------------------------------------------------------------------------

FIELD_EXERCISED = "EXERCISED"
FIELD_DEAD_OR_UNUSED = "DEAD_OR_UNUSED"
FIELD_STATUSES: Tuple[str, ...] = (FIELD_EXERCISED, FIELD_DEAD_OR_UNUSED)

REPORT_ANALYZED = "ANALYZED"
REPORT_NOT_AVAILABLE = "NOT_AVAILABLE"

DEFAULT_MAX_EVIDENCE = 5


class VipConfigFieldUsageCoverageError(ValueError):
    """A malformed input this module refuses to guess past -- e.g. a config record with no
    resolvable class name."""


# ---------------------------------------------------------------------------
# reuse: pulling VIPConfigIR records out of a real vip_capability_extraction
# report, never re-classifying anything.
# ---------------------------------------------------------------------------

def config_records_from_capability_report(
    report: "vip_capability_extraction.VIPCapabilityExtractionReport",
) -> List["vip_capability_extraction.VIPCapabilityRecord"]:
    """The real config-class records out of an already-built capability-extraction report -- calls
    that module's own `by_ir_type()`, never a second filter over `report.items`."""
    return report.by_ir_type(vip_capability_extraction.IR_VIP_CONFIG)


def config_records_from_capability_report_dict(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The same real config-class records, read from an on-disk
    `vip_capability_extraction.json` document (`write_capability_extraction_report()`'s own output)
    rather than an in-memory report object -- filters `items` by the SAME real `ir_type` constant,
    never a re-typed string literal."""
    return [item for item in (data.get("items") or [])
            if item.get("ir_type") == vip_capability_extraction.IR_VIP_CONFIG]


def _rec_get(rec: Any, attr: str, default: Any = None) -> Any:
    """Duck-typed field access over either a real `VIPCapabilityRecord` dataclass instance or a
    plain dict (e.g. one read back from a written `vip_capability_extraction.json`)."""
    if isinstance(rec, dict):
        return rec.get(attr, default)
    return getattr(rec, attr, default)


def _record_config_fields(rec: Any) -> List[Dict[str, Any]]:
    return list(_rec_get(rec, "config_fields", default=[]) or [])


# ---------------------------------------------------------------------------
# reuse: scanning real command.txt/pattern files, never a second parser.
# ---------------------------------------------------------------------------

def scan_command_statements(
    paths: Iterable,
) -> Tuple[List[Tuple[str, "reference_pattern_audit.CommandStatement"]], int, List[Dict[str, str]]]:
    """Read every supplied command.txt/pattern path with the REAL
    `reference_pattern_audit.extract_command_statements()` parser -- read-only, never a second
    comment-stripping/statement-splitting implementation.

    Returns `([(path_str, statement), ...], files_scanned, unreadable_files)`. A path this module
    cannot read (missing, a real permission error, a real decode error) is recorded in
    `unreadable_files` and never crashes the scan of the remaining paths -- a bad path must never
    silently look like "nothing to check" for the other, real ones."""
    entries: List[Tuple[str, "reference_pattern_audit.CommandStatement"]] = []
    scanned = 0
    unreadable: List[Dict[str, str]] = []
    for raw in paths or []:
        p = Path(raw)
        try:
            statements = reference_pattern_audit.extract_command_statements(p)
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append({"path": str(p), "reason": f"{type(exc).__name__}: {exc}"})
            continue
        scanned += 1
        for stmt in statements:
            entries.append((str(p), stmt))
    return entries, scanned, unreadable


def find_field_usage_evidence(
    field_name: str,
    entries: Sequence[Tuple[str, "reference_pattern_audit.CommandStatement"]],
    *, max_evidence: int = DEFAULT_MAX_EVIDENCE,
) -> List[Dict[str, Any]]:
    """A real, word-boundary, name-evidence textual scan for `field_name` across an already-parsed
    `(path, CommandStatement)` set. Matches only a statement's own comment-stripped CODE text
    (`stmt.text`) -- a trailing comment mention is deliberately never counted, since it is weaker
    evidence than a real code reference. Bounded to `max_evidence` citations so one heavily-
    referenced field does not bloat the report."""
    if not field_name:
        return []
    pattern = re.compile(r"\b" + re.escape(field_name) + r"\b")
    out: List[Dict[str, Any]] = []
    for path_str, stmt in entries:
        text = stmt.text or ""
        if pattern.search(text):
            out.append({"file": path_str, "line": stmt.line, "detail": text})
            if len(out) >= max_evidence:
                break
    return out


# ---------------------------------------------------------------------------
# the artifact
# ---------------------------------------------------------------------------

@dataclass
class ConfigFieldUsageRecord:
    field_name: str
    data_type: Optional[str]
    declared_file: str
    declared_line: int
    class_name: str
    status: str
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConfigClassUsage:
    class_name: str
    class_file: str
    class_line: int
    ir_qualification: Optional[str] = None
    fields: List[ConfigFieldUsageRecord] = field(default_factory=list)

    @property
    def exercised_count(self) -> int:
        return sum(1 for f in self.fields if f.status == FIELD_EXERCISED)

    @property
    def dead_or_unused_count(self) -> int:
        return sum(1 for f in self.fields if f.status == FIELD_DEAD_OR_UNUSED)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["exercised_count"] = self.exercised_count
        d["dead_or_unused_count"] = self.dead_or_unused_count
        return d


@dataclass
class VipConfigFieldUsageCoverageReport:
    status: str
    reason: Optional[str] = None
    classes: List[ConfigClassUsage] = field(default_factory=list)
    command_files_scanned: int = 0
    unreadable_command_files: List[Dict[str, str]] = field(default_factory=list)
    total_fields: int = 0
    total_exercised: int = 0
    total_dead_or_unused: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["classes"] = [c.to_dict() for c in self.classes]
        return d

    def dead_or_unused_fields(self) -> List[ConfigFieldUsageRecord]:
        return [f for c in self.classes for f in c.fields if f.status == FIELD_DEAD_OR_UNUSED]


# ---------------------------------------------------------------------------
# the analyzer
# ---------------------------------------------------------------------------

def analyze_config_field_usage(
    config_records: Optional[Iterable[Any]],
    command_file_paths: Optional[Iterable],
    *, max_evidence: int = DEFAULT_MAX_EVIDENCE,
) -> VipConfigFieldUsageCoverageReport:
    """Cross-reference every real declared config field in `config_records` (a real
    `vip_capability_extraction` VIPConfigIR record list -- see `config_records_from_capability_
    report()`/`config_records_from_capability_report_dict()`) against every real statement found in
    `command_file_paths`, and report EXERCISED vs. DEAD_OR_UNUSED per field.

    Supplying no config records, no command files, or command files that all fail to read honestly
    reports the WHOLE thing `NOT_AVAILABLE` rather than a report that fabricates DEAD_OR_UNUSED
    findings from evidence that was never actually gathered."""
    records = list(config_records or [])
    report = VipConfigFieldUsageCoverageReport(status="PENDING")

    if not records:
        report.status = REPORT_NOT_AVAILABLE
        report.reason = "NO_VIP_CONFIG_IR_RECORDS_SUPPLIED"
        return report

    paths = list(command_file_paths or [])
    if not paths:
        report.status = REPORT_NOT_AVAILABLE
        report.reason = "NO_COMMAND_TXT_PATTERN_FILES_SUPPLIED"
        return report

    entries, scanned, unreadable = scan_command_statements(paths)
    report.command_files_scanned = scanned
    report.unreadable_command_files = unreadable

    if scanned == 0:
        report.status = REPORT_NOT_AVAILABLE
        report.reason = "NO_COMMAND_TXT_PATTERN_FILE_COULD_BE_READ"
        return report

    for rec in records:
        cls_name = _rec_get(rec, "class_name")
        if not cls_name:
            raise VipConfigFieldUsageCoverageError(
                "a VIPConfigIR record with no resolvable class_name cannot be reported against -- "
                f"record was: {rec!r}")
        cls_usage = ConfigClassUsage(
            class_name=str(cls_name),
            class_file=str(_rec_get(rec, "file", default="") or ""),
            class_line=int(_rec_get(rec, "line", default=0) or 0),
            ir_qualification=_rec_get(rec, "qualification"),
        )
        for fdecl in _record_config_fields(rec):
            fname = fdecl.get("name")
            if not fname:
                continue
            evidence = find_field_usage_evidence(fname, entries, max_evidence=max_evidence)
            status = FIELD_EXERCISED if evidence else FIELD_DEAD_OR_UNUSED
            reason = None
            if not evidence:
                reason = (
                    f"scanned {scanned} real command.txt/pattern file(s); no literal, "
                    f"word-boundary reference to {fname!r} was found in any real command "
                    "statement's own code text"
                )
            cls_usage.fields.append(ConfigFieldUsageRecord(
                field_name=str(fname),
                data_type=fdecl.get("data_type"),
                declared_file=str(fdecl.get("file", "") or ""),
                declared_line=int(fdecl.get("line", 0) or 0),
                class_name=str(cls_name),
                status=status,
                evidence=evidence,
                reason=reason,
            ))
        report.classes.append(cls_usage)

    report.total_fields = sum(len(c.fields) for c in report.classes)
    if report.total_fields == 0:
        report.status = REPORT_NOT_AVAILABLE
        report.reason = "VIP_CONFIG_IR_RECORDS_DECLARE_NO_CONFIG_FIELDS"
        return report

    report.total_exercised = sum(c.exercised_count for c in report.classes)
    report.total_dead_or_unused = report.total_fields - report.total_exercised
    report.status = REPORT_ANALYZED
    return report


# ---------------------------------------------------------------------------
# rendering / artifact I/O / CLI
# ---------------------------------------------------------------------------

CONFIG_FIELD_USAGE_REPORT_NAME = "vip_config_field_usage_coverage.json"


def format_report(report: VipConfigFieldUsageCoverageReport) -> str:
    lines = [f"VIP config-field usage coverage: {report.status}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    lines.append(f"  command.txt/pattern files scanned: {report.command_files_scanned}")
    if report.unreadable_command_files:
        lines.append(f"  unreadable files ({len(report.unreadable_command_files)}):")
        for u in report.unreadable_command_files:
            lines.append(f"    {u['path']}: {u['reason']}")
    if report.status == REPORT_ANALYZED:
        lines.append(
            f"  fields: total={report.total_fields}, exercised={report.total_exercised}, "
            f"dead_or_unused={report.total_dead_or_unused}")
        for c in report.classes:
            if not c.fields:
                continue
            lines += ["", f"  {c.class_name} ({c.exercised_count} exercised, "
                          f"{c.dead_or_unused_count} dead/unused) at {c.class_file}:{c.class_line}"]
            for f in c.fields:
                if f.status == FIELD_EXERCISED:
                    first = f.evidence[0]
                    lines.append(
                        f"    [EXERCISED]      {f.field_name} -- e.g. {first['file']}:{first['line']}")
                else:
                    lines.append(f"    [DEAD_OR_UNUSED] {f.field_name} at {f.declared_file}:{f.declared_line}")
    return "\n".join(lines)


def write_config_field_usage_report(report: VipConfigFieldUsageCoverageReport, out_dir) -> Path:
    """Write the usage-coverage artifact. No timestamp anywhere, so an unchanged input regenerates
    byte-identically."""
    path = Path(out_dir) / CONFIG_FIELD_USAGE_REPORT_NAME
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


_STATUS_EXIT = {REPORT_NOT_AVAILABLE: 2}


def execute_verb(
    capability_report_path, command_files: Sequence, *,
    max_evidence: int = DEFAULT_MAX_EVIDENCE, as_json: bool = False, out_dir=None,
) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.vip_config_field_usage_coverage`. Returns
    `(text, exit_code)`: 0 every declared field is EXERCISED, 1 at least one real DEAD_OR_UNUSED
    finding, 2 NOT_AVAILABLE."""
    cap_path = Path(capability_report_path)
    if not cap_path.exists():
        raise VipConfigFieldUsageCoverageError(
            f"capability-extraction report does not exist: {capability_report_path} -- build one "
            "with dv_harness.vip_capability_extraction first")
    data = json.loads(cap_path.read_text(encoding="utf-8"))
    records = config_records_from_capability_report_dict(data)

    report = analyze_config_field_usage(records, command_files, max_evidence=max_evidence)
    if out_dir:
        write_config_field_usage_report(report, out_dir)
    text = json.dumps(report.to_dict(), indent=2) if as_json else format_report(report)
    code = _STATUS_EXIT.get(report.status, 0)
    if report.status == REPORT_ANALYZED and report.total_dead_or_unused:
        code = 1
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.vip_config_field_usage_coverage",
        description="Cross-reference vip_capability_extraction.py's VIPConfigIR declared config "
                    "fields against a project's real command.txt/pattern set, reporting EXERCISED "
                    "vs. DEAD_OR_UNUSED fields.")
    ap.add_argument("--capability-report", required=True,
                    help="A vip_capability_extraction.json document (write_capability_extraction_"
                         "report()'s own output).")
    ap.add_argument("--command-file", action="append", default=None, dest="command_files",
                    help="A real command.txt/pattern file to scan (repeatable).")
    ap.add_argument("--max-evidence", type=int, default=DEFAULT_MAX_EVIDENCE,
                    help="Cap on citations kept per EXERCISED field (default: %(default)s).")
    ap.add_argument("--out-dir", default=None,
                    help="Also write vip_config_field_usage_coverage.json here.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(
            a.capability_report, a.command_files or [], max_evidence=a.max_evidence,
            as_json=a.json, out_dir=a.out_dir)
    except (VipConfigFieldUsageCoverageError, json.JSONDecodeError) as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
