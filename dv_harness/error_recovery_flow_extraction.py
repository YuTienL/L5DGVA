"""dv_harness/error_recovery_flow_extraction.py -- error/recovery BEHAVIOR
FACT EXTRACTION from whatever real spec/programming-guide/RTL text a caller
actually supplies, combining `spec_doc_map.py`'s structural document index
with `interrupt_dma_clock_reset_extraction.py`'s existing declaration-level
line-scan pattern, applied to error/recovery vocabulary instead of that
module's interrupt/DMA/clock-reset vocabulary.

REUSE OVER REINVENT: grepped first, before writing anything here. Nothing
already extracts error/recovery FACTS from real spec/programming-guide text.
The closest existing mechanisms answer different questions:
`dv_harness/verification_intent_ir.py`'s `plan_error_recovery()` states
outright, in its own docstring and constant names, that "this harness has no
evidence producer for either [performance or error_recovery]" and always
returns `ERROR_TARGET_UNKNOWN` -- this module is that missing producer.
`dv_harness/potential_spec_gap_detector.py` classifies already-EXTRACTED
requirement RECORDS for a missing error<->recovery PAIRING (a gap-analysis
over structured requirements, never a raw-text extractor).
`dv_harness/system_checker_taxonomy.py`'s `RECOVERY_CHECKER` classifies a
caller-supplied CHECKER description, not spec/RTL prose. None of them reads
real source text for error/recovery facts, which is exactly this module's
job -- the same gap `interrupt_dma_clock_reset_extraction.py`'s own docstring
describes for interrupt/DMA/clock-reset facts, restated here for a different
vocabulary rather than re-solved by duplicating that module wholesale.

TWO REAL MECHANISMS, KEPT DELIBERATELY SEPARATE, NEVER MERGED INTO ONE SCAN.
(1) STRUCTURAL: `spec_doc_map.extract_spec_doc_map()` (imported, called
    through its real public API, never its private helpers) turns a
    spec/programming-guide document into a real, mechanically-detected
    section index. This module filters that index's own `sections` list for
    a heading whose TITLE names an error/fault/exception/recovery keyword,
    and reports each match's real heading/number/level/page as
    `error_recovery_chapters` -- WHERE in the document an error/recovery
    discussion structurally lives, never what it says. Because
    `extract_spec_doc_map()` requires a real `out_dir` to write its two
    structure-only artifacts into (by that module's own contract), this
    facet is attempted only when a caller supplies `structural_index_dir` --
    omitting it is an honest `NOT_AVAILABLE` on this ONE facet, never a
    silent skip disguised as "nothing found", and never a `mkdir()` a caller
    did not ask for.
(2) DECLARATION-LEVEL LINE SCAN: exactly `interrupt_dma_clock_reset_
    extraction.py`'s own graceful-degradation discipline -- RTL port
    declarations and plain prose sentences a caller supplies are scanned
    line by line for EXPLICIT statement forms; a construct or sentence this
    scan does not recognise contributes NOTHING, never a guessed fact. This
    half never touches `spec_doc_map.py`: that module's own contract forbids
    it from ever extracting or persisting body prose (its docstring's "WHAT
    LANDS WHERE, and why prose lands nowhere"), so the concrete error-
    condition/recovery-statement/error-to-recovery-link facts this task asks
    for can only come from a direct read of the caller's own supplied text,
    the same reasoning the sibling module already gives for reading RTL/spec
    text itself rather than routing through a distiller.
`RTL_SUFFIXES`/`TEXT_SUFFIXES`/`classify_source()`/the port-declaration regex
are independently RE-DERIVED here (a handful of lines) rather than imported
from `interrupt_dma_clock_reset_extraction.py` -- the same "re-derive a small
primitive rather than import a sibling module's private shape" discipline
several modules in this codebase already follow (e.g. `spec_doc_map.py` re-
deriving `vip_user_guide_distill.py`'s own pypdf call), so this module has no
import-time coupling to a sibling that may itself be under concurrent edit.

WHAT IS DELIBERATELY NOT ATTEMPTED, stated rather than implied closed.
(1) A recovery MECHANISM is never inferred from the mere presence of an
    error condition, or from an error condition's own name -- `recovery_
    statements` requires an EXPLICIT sentence naming both a real recovery
    trigger word ("recover"/"recovery"/"recoverable"/...) and a real
    recovery-mechanism keyword (reset/retry/reinitialize/clear/power-cycle/
    resend/resynchronize) in the same line. (2) Whether a stated recovery is
    AUTOMATIC or MANUAL is classified ONLY from an explicit word in that same
    sentence ("automatic(ally)"/"self-clear(s)"/"internally" for automatic;
    "software"/"firmware"/"manual(ly)"/"host must"/"cpu must"/"driver must"
    for manual); a recovery statement naming neither is honestly
    `RECOVERY_MECHANISM_STATED` -- who performs it is never guessed.
    (3) `error_recovery_links` -- an explicit statement tying ONE named error
    condition to ITS OWN recovery action -- is bounded to two literal
    statement forms ("<X> error requires <Y>" and "on a/an <X> error, ...
    shall/will/automatically <Y>"); a general recoverability statement that
    does not fit either form contributes to `recovery_statements` only, never
    a guessed link. (4) This is a regex line-scan, not a compiler or an NLP
    model: multi-sentence/multi-paragraph recovery flows, `` `ifdef ``
    conditionals, and any statement form these patterns do not anticipate
    contribute no citation rather than a wrong one. (5) This module decides
    nothing beyond reporting: no build, job, approval, or stage gate is
    touched, and there is deliberately no stage gate, matching several
    sibling pure-extractor modules (`golden_scenario.py`, `power_intent.py`,
    `interrupt_dma_clock_reset_extraction.py`) that already state the same
    boundary for themselves.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from dv_harness import spec_doc_map

SCHEMA_VERSION = "1.0"

RTL_SUFFIXES = (".v", ".sv", ".vh", ".svh")
TEXT_SUFFIXES = (".txt", ".md", ".rst", ".pgv", ".spec")


def classify_source(path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in RTL_SUFFIXES:
        return "rtl"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "unknown"


# ---------------------------------------------------------------------------
# Error conditions -- RTL port declarations whose NAME matches an error/fault
# naming convention. This records the NAME the RTL actually declares; it
# makes no claim about severity, recoverability, or a corresponding recovery
# action, which are separate facets below and independently gated on their
# own explicit evidence.
# ---------------------------------------------------------------------------
_PORT_LINE_RE = re.compile(
    r"^\s*(?P<dir>input|output|inout)\s+"
    r"(?:wire\s+|reg\s+|logic\s+)?(?:signed\s+)?"
    r"(?:\[(?P<width>[^\]]+)\]\s*)?"
    r"(?P<name>[A-Za-z_]\w*)\s*[,;)]"
    r"(?:\s*//\s*(?P<comment>.*))?"
)
_ERR_NAME_RE = re.compile(r"(?:^|_)(err|error|fault|alarm|excp|exception)(?:_|$)", re.IGNORECASE)


def _scan_error_sources(lines: list, path: str) -> list:
    found = []
    for lineno, line in enumerate(lines, start=1):
        m = _PORT_LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        if not _ERR_NAME_RE.search(name):
            continue
        found.append({
            "name": name,
            "direction": m.group("dir").lower(),
            "width": m.group("width"),
            "description": (m.group("comment") or "").strip() or None,
            "evidence": f"{path}:{lineno}",
        })
    return found


# ---------------------------------------------------------------------------
# Recovery statements -- EXPLICIT sentences naming both a real recovery
# trigger word and a real recovery-mechanism keyword. Never a sentence merely
# mentioning "error" near a mechanism word with no stated recovery relation.
# ---------------------------------------------------------------------------
_RECOVERY_TRIGGER_RE = re.compile(r"\brecover\w*\b", re.IGNORECASE)
_MECHANISM_KEYWORD_RE = re.compile(
    r"\b(reset|retry|retries|retried|retrying|re-?initiali[sz]e|clear|cleared|clears|"
    r"power[- ]cycle|resend|resent|resynchroni[sz]e)\b",
    re.IGNORECASE,
)
_AUTOMATIC_KEYWORD_RE = re.compile(
    r"\b(automatic|automatically|self-clear|self-clears|internally)\b", re.IGNORECASE)
_MANUAL_KEYWORD_RE = re.compile(
    r"\b(software|firmware|manual(?:ly)?|host must|cpu must|driver must)\b", re.IGNORECASE)


def _classify_recovery_mechanism(line: str) -> str:
    if _AUTOMATIC_KEYWORD_RE.search(line):
        return "AUTOMATIC_RECOVERY"
    if _MANUAL_KEYWORD_RE.search(line):
        return "MANUAL_RECOVERY"
    return "RECOVERY_MECHANISM_STATED"


def _scan_recovery_statements(lines: list, path: str) -> list:
    statements = []
    for lineno, line in enumerate(lines, start=1):
        if not _RECOVERY_TRIGGER_RE.search(line):
            continue
        if not _MECHANISM_KEYWORD_RE.search(line):
            continue
        statements.append({
            "type": _classify_recovery_mechanism(line),
            "text": line.strip(),
            "evidence": f"{path}:{lineno}",
        })
    return statements


# ---------------------------------------------------------------------------
# Error-to-recovery links -- an EXPLICIT statement tying one named error
# condition to its own recovery action, bounded to two literal statement
# forms. Never inferred from an error condition and a recovery statement
# merely appearing near each other.
# ---------------------------------------------------------------------------
_ERROR_REQUIRES_RE = re.compile(
    r"(?P<error>[A-Za-z][A-Za-z0-9_\- ]{0,40}?\berror)\b\s*,?\s*requires?\s+"
    r"(?:that\s+)?(?P<recovery>[^\n.;]+)",
    re.IGNORECASE,
)
_ON_ERROR_ACTION_RE = re.compile(
    r"\bon\s+an?\s+(?P<error>[A-Za-z][A-Za-z0-9_\- ]{0,40}?\berror)\b[^.\n]*?"
    r"\b(?:shall|will|automatically)\b\s+(?P<recovery>[^\n.;]+)",
    re.IGNORECASE,
)


def _scan_error_recovery_links(lines: list, path: str) -> list:
    links = []
    for lineno, line in enumerate(lines, start=1):
        m = _ERROR_REQUIRES_RE.search(line)
        if m:
            links.append({
                "type": "REQUIRES",
                "error": m.group("error").strip(),
                "recovery": m.group("recovery").strip(),
                "text": line.strip(),
                "evidence": f"{path}:{lineno}",
            })
            continue
        m = _ON_ERROR_ACTION_RE.search(line)
        if m:
            links.append({
                "type": "ON_ERROR_ACTION",
                "error": m.group("error").strip(),
                "recovery": m.group("recovery").strip(),
                "text": line.strip(),
                "evidence": f"{path}:{lineno}",
            })
    return links


# ---------------------------------------------------------------------------
# Structural error/recovery chapter index -- via spec_doc_map.py's own real,
# public structural extractor. Locates WHERE a chapter/section discussing
# error/fault/exception/recovery lives (heading/number/level/page); never
# opens or reports one word of that chapter's body prose, per spec_doc_map's
# own contract.
# ---------------------------------------------------------------------------
_CHAPTER_KEYWORD_RE = re.compile(r"\b(errors?|faults?|exceptions?|recovery)\b", re.IGNORECASE)


def _scan_error_recovery_chapters(record: dict, path_str: str) -> list:
    chapters = []
    for section in record.get("sections", []):
        title = section.get("title") or ""
        if not _CHAPTER_KEYWORD_RE.search(title):
            continue
        chapters.append({
            "heading": section.get("heading"),
            "number": section.get("number"),
            "level": section.get("level"),
            "page": section.get("page"),
            "source_document": path_str,
            "evidence": f"{path_str}#section:{section.get('number')}",
        })
    return chapters


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------
def extract_error_recovery_flow(source_paths, *, structural_index_dir=None) -> dict:
    """Extract error/recovery flow facts from real RTL and/or
    spec/programming-guide TEXT files a caller supplies. `source_paths` is a
    list of str/Path; every file is read (never fabricated), and a missing/
    unreadable file is recorded as an honest per-source failure rather than
    silently skipped or raised past the caller. `structural_index_dir`, when
    supplied, is a real directory `spec_doc_map.extract_spec_doc_map()` may
    write its structure-only artifacts into for every qualifying text
    source; omitting it makes `error_recovery_chapters` an honest
    `NOT_AVAILABLE` rather than silently attempting a write the caller did
    not ask for. Every facet below carries its OWN status/reason -- absence
    of one fact never masks the presence of another."""
    source_paths = list(source_paths or [])
    read_sources = []
    missing_sources = []
    unrecognized_sources = []

    error_sources = []
    recovery_statements = []
    error_recovery_links = []
    error_recovery_chapters = []
    structural_index_errors = []
    structural_index_attempted = False

    for raw_path in source_paths:
        p = Path(raw_path)
        if not p.is_file():
            missing_sources.append(str(raw_path))
            continue
        kind = classify_source(p)
        if kind == "unknown":
            unrecognized_sources.append(str(raw_path))
            # An unrecognised extension is still read: a supplied file with
            # no suffix (or an unlisted one) may still be real prose or RTL
            # text, and refusing to scan it would silently under-report.
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            missing_sources.append(f"{raw_path} ({exc})")
            continue
        lines = text.splitlines()
        path_str = str(raw_path)
        read_sources.append(path_str)

        error_sources.extend(_scan_error_sources(lines, path_str))
        recovery_statements.extend(_scan_recovery_statements(lines, path_str))
        error_recovery_links.extend(_scan_error_recovery_links(lines, path_str))

        if structural_index_dir is not None and p.suffix.lower() in spec_doc_map.SUPPORTED_SUFFIXES:
            structural_index_attempted = True
            try:
                record = spec_doc_map.extract_spec_doc_map(
                    p, structural_index_dir, doc_kind="dut_spec_or_programming_guide")
            except spec_doc_map.SpecDocMapError as exc:
                structural_index_errors.append(f"{raw_path}: {exc}")
            else:
                error_recovery_chapters.extend(_scan_error_recovery_chapters(record, path_str))

    # --- error conditions ---
    if error_sources:
        error_conditions_status, error_conditions_reason = "LOADED", None
    else:
        error_conditions_status = "NOT_AVAILABLE"
        error_conditions_reason = (
            "no port declaration in the supplied sources matches an error/fault naming "
            "convention (err/error/fault/alarm/exception) -- nothing was found to list, and "
            "none is assumed")
    error_conditions = {
        "status": error_conditions_status,
        "reason": error_conditions_reason,
        "sources": error_sources,
    }

    # --- recovery statements ---
    if recovery_statements:
        recovery_status, recovery_reason = "LOADED", None
    else:
        recovery_status = "NOT_AVAILABLE"
        recovery_reason = (
            "no explicit recovery statement (a sentence naming both a real recovery trigger "
            "word and a real recovery-mechanism keyword) was found in the supplied sources -- "
            "a recovery mechanism is never inferred from the presence of an error condition "
            "alone")
    recovery_statements_block = {
        "status": recovery_status,
        "reason": recovery_reason,
        "statements": recovery_statements,
    }

    # --- error-to-recovery links ---
    if error_recovery_links:
        links_status, links_reason = "LOADED", None
    else:
        links_status = "NOT_AVAILABLE"
        links_reason = (
            "no explicit statement linking a specific named error condition to its own "
            "recovery action ('<X> error requires <Y>' or 'on a/an <X> error, ... shall/will/"
            "automatically <Y>') was found in the supplied sources -- a link is never inferred "
            "from an error condition and a recovery statement merely appearing near each other")
    error_recovery_links_block = {
        "status": links_status,
        "reason": links_reason,
        "links": error_recovery_links,
    }

    # --- structural error/recovery chapters ---
    if not structural_index_attempted:
        chapters_status = "NOT_AVAILABLE"
        chapters_reason = (
            "no structural_index_dir was supplied, so spec_doc_map's structural chapter/"
            "section index was never attempted for these sources")
    elif error_recovery_chapters:
        chapters_status, chapters_reason = "LOADED", None
    else:
        chapters_status = "NOT_AVAILABLE"
        chapters_reason = (
            "spec_doc_map's structural index was attempted but no section/chapter heading in "
            "the supplied sources matched an error/fault/exception/recovery keyword")
    error_recovery_chapters_block = {
        "status": chapters_status,
        "reason": chapters_reason,
        "chapters": error_recovery_chapters,
        "structural_index_attempted": structural_index_attempted,
        "index_errors": structural_index_errors,
    }

    facets_loaded = any(block["status"] == "LOADED" for block in
                         (error_conditions, recovery_statements_block, error_recovery_links_block,
                          error_recovery_chapters_block))
    if not source_paths:
        top_status, top_reason = "NOT_AVAILABLE", "no source files were supplied"
    elif not read_sources:
        top_status = "NOT_AVAILABLE"
        top_reason = f"none of the {len(source_paths)} supplied source path(s) could be read: " \
                     f"{missing_sources}"
    elif facets_loaded:
        top_status, top_reason = "LOADED", None
    else:
        top_status = "NOT_AVAILABLE"
        top_reason = ("supplied sources were read but none of error conditions, recovery "
                      "statements, error-to-recovery links, or error/recovery chapters could be "
                      "extracted from them")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": top_status,
        "source": {
            "kind": "error_recovery_flow_source_text",
            "paths": read_sources,
            "missing": missing_sources,
            "unrecognized": unrecognized_sources,
        },
        "reason": top_reason,
        "error_conditions": error_conditions,
        "recovery_statements": recovery_statements_block,
        "error_recovery_links": error_recovery_links_block,
        "error_recovery_chapters": error_recovery_chapters_block,
    }


# ---------------------------------------------------------------------------
# CLI front door -- same shared `execute_verb()` convention as
# `interrupt-dma-clock-reset`/`power-intent`/`golden-scenario`. Not wired
# into cli.py (this task's file-safety scope forbids editing it, per this
# batch's own house style); the integrator may add a
# `dv-harness error-recovery-flow --sources <f> [<f> ...] [--structural-index-dir <d>] [--json]`
# verb calling `execute_verb(argv)` below.
# ---------------------------------------------------------------------------
def execute_verb(argv: list) -> int:
    import json as _json
    import sys as _sys

    if not argv or argv[0] not in ("extract",):
        print("usage: error_recovery_flow_extraction extract --sources <f> [<f> ...] "
              "[--structural-index-dir <d>] [--json]", file=_sys.stderr)
        return 2
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    structural_index_dir = None
    if "--structural-index-dir" in args:
        idx = args.index("--structural-index-dir")
        structural_index_dir = args[idx + 1]
        args = args[:idx] + args[idx + 2:]
    if "--sources" in args:
        idx = args.index("--sources")
        sources = args[idx + 1:]
    else:
        sources = args
    report = extract_error_recovery_flow(sources, structural_index_dir=structural_index_dir)
    if as_json:
        print(_json.dumps(report, indent=2))
    else:
        print(f"status: {report['status']}" + (f" ({report['reason']})" if report["reason"] else ""))
        print(f"  error conditions:        {report['error_conditions']['status']} "
              f"({len(report['error_conditions']['sources'])} found)")
        print(f"  recovery statements:     {report['recovery_statements']['status']} "
              f"({len(report['recovery_statements']['statements'])} found)")
        print(f"  error-to-recovery links: {report['error_recovery_links']['status']} "
              f"({len(report['error_recovery_links']['links'])} found)")
        print(f"  error/recovery chapters: {report['error_recovery_chapters']['status']} "
              f"({len(report['error_recovery_chapters']['chapters'])} found)")
    return 0 if report["status"] == "LOADED" else 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(execute_verb(sys.argv[1:]))
