"""dv_harness/perf_function_extraction.py -- DOCUMENTED performance-related
function facts (e.g. "this block computes throughput as X"), extracted as
plain text citations only, from real RTL comments and/or real spec/
programming-guide TEXT a caller supplies.

WHAT THIS CLOSES. `amba_performance_calculator.py` (this same session) is
pure ARITHMETIC over caller-supplied NUMBERS -- it computes bandwidth,
throughput, latency percentiles, utilization, etc. from real observed
samples, and its own CLAUDE.md section is explicit that it "never reads an
FSDB/waveform file, never monitors a live signal, never generates traffic,
and never runs a simulation". Nothing in this repository ever asked the
DIFFERENT, prior question: does the DUT's own RTL or spec/programming-guide
DOCUMENTATION already SAY how a block computes a performance-related
quantity -- "this block computes throughput as (bytes_transferred /
cycles_elapsed)", "Latency is defined as the number of cycles from request
issue to first response beat" -- as a plain, human-authored FACT about the
design, not a measurement? `verification_intent_ir.py`'s own `performance`
domain states this precisely: this harness has no producer anywhere that
derives a throughput/latency/bandwidth TARGET or FORMULA from any real
source, and reports `PERFORMANCE_TARGET_UNKNOWN` for that reason on every
call, "proven (by mutation, not by inspection) to stay that way even when
every OTHER domain's real evidence is supplied in the same call". This
module is that missing, narrowly-scoped extractor -- and only that.

EXPLICITLY, DELIBERATELY OUT OF SCOPE: computing, measuring or estimating a
single performance NUMBER. That is, and stays, `amba_performance_calculator.
py`'s job -- this module imports nothing from it, from
`amba_performance_requirement_checker.py`, `amba_performance_classification.
py`, `amba_performance_readiness_gates.py`, `fsdb_report.py`, or
`sim_log_analysis.py`, and never evaluates any extracted formula text (no
`eval`/`exec`/arithmetic of any kind is performed on a matched expression
anywhere in this module -- proven directly by
`dv_harness_tests/test_perf_function_extraction.py`'s own AST-based negative
control). Performance Verification (any numeric latency/bandwidth/
throughput TARGET or live measurement) remains entirely out of scope for
this whole gap-closure session, per that session's own stated exclusion;
this module reads text, cites text, and computes nothing.

WHY A LINE-SCAN, MIRRORING `interrupt_dma_clock_reset_extraction.py` RATHER
THAN A DOCUMENT DISTILLER. This fact can legitimately appear in either an
RTL comment (`// throughput_mbps = (num_beats * DATA_WIDTH_BYTES) /
cycles_elapsed;`) or spec/programming-guide prose ("This block computes
throughput as the number of bytes transferred divided by the number of
elapsed cycles."), so this module takes the SAME real-file, declaration-
level line-scan approach `interrupt_dma_clock_reset_extraction.py` already
established for the identical "may live in RTL OR in prose" shape, rather
than requiring a `vip_user_guide_distill.py` PDF-distillation step first
(which that module's own docstring reserves for a genuinely PDF-only
source). A construct or sentence this scan does not recognise contributes
NOTHING -- never a guessed fact, exactly the "graceful degradation, never an
invented fact" discipline every sibling extraction module in this codebase
already applies.

WHAT COUNTS AS A "FACT" HERE, and why it cannot be a guess. Every item this
module reports is a LITERAL (possibly truncated) line of the real source's
own text, plus a real `<path>:<line>` citation a reader can open and check.
A statement is recognised ONLY in one of three EXPLICIT, disclosed forms:
(a) an ASSIGNMENT-shaped line whose left-hand identifier itself names a
recognised performance metric (`throughput_mbps = ...`); (b) a VERB-FIRST
sentence naming a compute/derive/measure/define verb, then a metric
keyword, then an explicit `as`/`by`/`via` introducing the definition/
formula text ("computes throughput as ..."); (c) the symmetric METRIC-FIRST
sentence form ("Throughput is computed as ..."). Nothing here infers a
performance function from a bare metric-keyword mention with no verb and no
`as`/`by`/`via`/`=` tail (a line that merely says "// TODO: add a throughput
counter" contributes nothing), and nothing here infers ANY fact from a
register/signal NAME alone -- only from the recognised statement SHAPE. A
source carrying none of these three shapes reports NOT_AVAILABLE, honestly,
never a fabricated empty-but-successful LOADED status.

METRIC VOCABULARY is a small, fixed, disclosed set (THROUGHPUT, BANDWIDTH,
LATENCY, UTILIZATION -- covering "utilization"/"occupancy" -- and IOPS), the
same "small, fixed, generic vocabulary rather than an invented protocol-
specific one" discipline `phy_model_behavior_ir.py`'s own structural
section-marker set already uses. A statement naming a performance concept
outside this vocabulary is honestly not recognised rather than guessed into
the nearest-sounding bucket.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "1.0"

RTL_SUFFIXES = (".v", ".sv", ".vh", ".svh")
TEXT_SUFFIXES = (".txt", ".md", ".rst", ".pgv", ".spec")

DEFAULT_MAX_FACTS_PER_SOURCE = 50
DEFAULT_MAX_TEXT_CHARS = 240

#: Carried verbatim onto every document this module produces -- the same
#: fixed-disclosure convention `phy_model_behavior_ir.PHY_NOT_SILICON_
#: DISCLOSURE` already establishes for its own domain.
PERF_FUNCTION_DISCLOSURE = (
    "PERFORMANCE FUNCTION FACTS ARE DOCUMENTED KNOWLEDGE, NEVER A MEASUREMENT: every fact in "
    "this document is a literal, cited statement already present in a real RTL comment or a real "
    "spec/programming-guide document's own text describing how a block COMPUTES a performance-"
    "related quantity. Nothing here evaluates, measures, or estimates a single performance "
    "NUMBER -- that stays dv_harness.amba_performance_calculator.py's job, and remains deferred "
    "per this session's own Performance Verification exclusion. This is a read-only knowledge-"
    "extraction artifact, not a performance report."
)

# --------------------------------------------------------------------------
# Metric vocabulary -- small, fixed, disclosed. Never inferred from a
# register/signal NAME alone; only ever matched against real statement TEXT.
# --------------------------------------------------------------------------
_METRIC_PATTERNS = {
    "THROUGHPUT": re.compile(r"throughput", re.IGNORECASE),
    "BANDWIDTH": re.compile(r"bandwidth", re.IGNORECASE),
    "LATENCY": re.compile(r"latency", re.IGNORECASE),
    "UTILIZATION": re.compile(r"utili[sz]ation|occupancy", re.IGNORECASE),
    "IOPS": re.compile(r"\biops\b|i/?o\s*operations\s*per\s*second", re.IGNORECASE),
}
# Fixed evaluation order so a line naming more than one metric keyword (rare,
# but a line like "the throughput/bandwidth pair is computed as ..." is
# possible) always resolves to the SAME metric deterministically rather than
# depending on dict iteration order.
_METRIC_ORDER = ("THROUGHPUT", "BANDWIDTH", "LATENCY", "UTILIZATION", "IOPS")

_COMPUTE_VERB = r"comput\w*|calculat\w*|deriv\w*|measur\w*|defin\w*"

# (a) Assignment-shaped: an identifier itself naming a metric, then `=`,
# then the formula/expression text. Optional leading comment marker
# (`//`, `#`, `*`) and an optional array/bit-select suffix on the name.
_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:/{2,}|#|\*)?\s*"
    r"(?P<name>[A-Za-z][A-Za-z0-9_]{0,60})\s*(?:\[[^\]]{0,40}\])?\s*"
    r"=\s*(?P<expr>.+?)\s*;?\s*$"
)

# (b) verb-first: "... computes throughput as/by/via <expr>"
_VERB_METRIC_RE = re.compile(
    r"\b(?:%s)\b.{0,60}?\b(?P<metric>throughput|bandwidth|latency|"
    r"utili[sz]ation|occupancy|iops)\b.{0,20}?\b(?:as|by|via)\b\s*"
    r"(?P<expr>.+?)\s*[;.]?\s*$" % _COMPUTE_VERB,
    re.IGNORECASE,
)

# (c) metric-first: "Throughput is computed as/by/via <expr>"
_METRIC_VERB_RE = re.compile(
    r"\b(?P<metric>throughput|bandwidth|latency|utili[sz]ation|occupancy|iops)\b"
    r".{0,40}?\b(?:%s)\b.{0,20}?\b(?:as|by|via)\b\s*"
    r"(?P<expr>.+?)\s*[;.]?\s*$" % _COMPUTE_VERB,
    re.IGNORECASE,
)


def _canonical_metric(text: str) -> Optional[str]:
    """Resolve `text` against the fixed, disclosed metric vocabulary, in a
    fixed deterministic order. Returns the canonical metric name, or None
    when no recognised keyword appears -- never a guessed metric."""
    for name in _METRIC_ORDER:
        if _METRIC_PATTERNS[name].search(text):
            return name
    return None


def _truncate(text: str, limit: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def classify_source(path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in RTL_SUFFIXES:
        return "rtl"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "unknown"


def scan_perf_function_facts(lines: list, path: str,
                              max_facts: int = DEFAULT_MAX_FACTS_PER_SOURCE) -> list:
    """Scan real, already-read source LINES for a recognised performance-
    function statement shape. Every returned fact carries a real
    `<path>:<line>` citation and the exact (truncated) statement text --
    never a paraphrase, never an evaluated value."""
    facts = []
    for lineno, raw_line in enumerate(lines, start=1):
        if len(facts) >= max_facts:
            break
        stripped = raw_line.strip()
        if not stripped:
            continue

        m = _ASSIGNMENT_RE.match(stripped)
        if m:
            metric = _canonical_metric(m.group("name"))
            if metric is not None:
                facts.append({
                    "metric": metric,
                    "match_rule": "ASSIGNMENT",
                    "statement_text": _truncate(stripped),
                    "formula_expression": _truncate(m.group("expr")),
                    "evidence": f"{path}:{lineno}",
                })
                continue

        m = _VERB_METRIC_RE.search(stripped)
        if m:
            facts.append({
                "metric": _canonical_metric(m.group("metric")),
                "match_rule": "VERB_METRIC",
                "statement_text": _truncate(stripped),
                "formula_expression": _truncate(m.group("expr")),
                "evidence": f"{path}:{lineno}",
            })
            continue

        m = _METRIC_VERB_RE.search(stripped)
        if m:
            facts.append({
                "metric": _canonical_metric(m.group("metric")),
                "match_rule": "METRIC_VERB",
                "statement_text": _truncate(stripped),
                "formula_expression": _truncate(m.group("expr")),
                "evidence": f"{path}:{lineno}",
            })
            continue

    return facts


def extract_performance_function_facts(source_paths) -> dict:
    """Extract DOCUMENTED performance-related function facts -- text
    citations only -- from real RTL and/or spec/programming-guide TEXT
    files a caller supplies. `source_paths` is a list of str/Path; every
    file is read (never fabricated), and a missing/unreadable file is
    recorded as an honest per-source failure rather than silently skipped
    or raised past the caller. This function performs NO arithmetic on any
    extracted formula text -- it only locates and cites where the source
    already states one."""
    source_paths = list(source_paths or [])
    read_sources = []
    missing_sources = []
    unrecognized_sources = []
    facts = []

    for raw_path in source_paths:
        p = Path(raw_path)
        if not p.is_file():
            missing_sources.append(str(raw_path))
            continue
        kind = classify_source(p)
        if kind == "unknown":
            unrecognized_sources.append(str(raw_path))
            # Still read: a supplied file with no/an unlisted suffix may
            # still be real prose or RTL text, and refusing to scan it
            # would silently under-report -- the same convention
            # interrupt_dma_clock_reset_extraction.py already uses.
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            missing_sources.append(f"{raw_path} ({exc})")
            continue
        path_str = str(raw_path)
        read_sources.append(path_str)
        facts.extend(scan_perf_function_facts(text.splitlines(), path_str))

    if not source_paths:
        status, reason = "NOT_AVAILABLE", "no source files were supplied"
    elif not read_sources:
        status = "NOT_AVAILABLE"
        reason = (f"none of the {len(source_paths)} supplied source path(s) could be read: "
                  f"{missing_sources}")
    elif facts:
        status, reason = "LOADED", None
    else:
        status = "NOT_AVAILABLE"
        reason = ("supplied sources were read but no documented performance-related function "
                  "statement (an assignment naming a recognised metric, or an explicit "
                  "'computes/calculates/defines <metric> as/by/via ...' statement) was found in "
                  "them -- a performance function fact is never invented from a bare metric-name "
                  "mention or a register/signal name alone")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "disclosure": PERF_FUNCTION_DISCLOSURE,
        "source": {
            "kind": "perf_function_source_text",
            "paths": read_sources,
            "missing": missing_sources,
            "unrecognized": unrecognized_sources,
        },
        "facts": facts,
    }


# ---------------------------------------------------------------------------
# CLI front door -- same shared `execute_verb()` convention as
# `power-intent`/`golden-scenario`/`interrupt-dma-clock-reset`. Not wired
# into cli.py (this task's file-safety scope forbids editing it); the
# integrator may add a
# `dv-harness perf-function-extraction extract --sources <f> [<f> ...] [--json]`
# verb calling `execute_verb(argv)` below.
# ---------------------------------------------------------------------------
def execute_verb(argv: list) -> int:
    import json as _json
    import sys as _sys

    if not argv or argv[0] not in ("extract",):
        print("usage: perf_function_extraction extract --sources <f> [<f> ...] [--json]",
              file=_sys.stderr)
        return 2
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if "--sources" in args:
        idx = args.index("--sources")
        sources = args[idx + 1:]
    else:
        sources = args
    report = extract_performance_function_facts(sources)
    if as_json:
        print(_json.dumps(report, indent=2))
    else:
        print(f"status: {report['status']}" + (f" ({report['reason']})" if report["reason"] else ""))
        print(f"  facts found: {len(report['facts'])}")
        for fact in report["facts"]:
            print(f"    [{fact['metric']}] {fact['evidence']}: {fact['statement_text']}")
    return 0 if report["status"] == "LOADED" else 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(execute_verb(sys.argv[1:]))
