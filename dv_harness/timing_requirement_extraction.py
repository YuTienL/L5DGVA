"""dv_harness/timing_requirement_extraction.py -- extract DOCUMENTED timing
requirements (a stated setup/hold/latency bound written down somewhere in a
spec/programming-guide/RTL comment) as structural facts with real citations,
section 289 (2026-09-06).

THIS IS KNOWLEDGE EXTRACTION FROM TEXT, NEVER A MEASUREMENT.
-----------------------------------------------------------------------------
Section 289 is explicit that this is "knowledge extraction from text,
explicitly distinct from and never conflated with the live-simulator-
dependent Performance Verification item this session already deferred". That
boundary is enforced STRUCTURALLY here, not only stated:

  * This module has no parameter, field, or code path anywhere that accepts
    an "observed"/"measured"/"actual" value. `TimingRequirementFact` carries
    exactly one number, `value`, and it is always the DOCUMENTED bound a
    spec/comment states -- there is no sibling field for a simulated result
    to be compared against, because comparing against a live measurement is
    exactly the job this module refuses to do.
  * Every line-scan additionally runs `_MEASURED_VALUE_EXCLUSION_RE` before
    any requirement pattern is even tried: a line naming "observed",
    "measured", "simulation"/"simulated", "waveform", "sim.log" or "actual"
    is skipped OUTRIGHT, on the theory that a sentence reporting what a run
    produced is a measurement claim, never a documented requirement, even
    when it happens to use the words "setup"/"hold"/"latency" too. See
    `test_measured_or_observed_language_is_never_extracted_as_a_requirement`
    for the direct proof.
  * `amba_performance_calculator.py` / `amba_performance_classification.py` /
    `amba_performance_requirement_checker.py` are this repo's real
    live-numbers-dependent performance stack (their own docstrings: "over
    real, CALLER-SUPPLIED numbers only", meaning numbers a simulation or a
    caller's own measurement already produced). This module imports NOTHING
    from any of the three, and produces no value any of the three could
    consume as a measured sample -- a `TimingRequirementFact.value` is a
    spec-declared bound, and feeding one into
    `amba_performance_requirement_checker.check_against_requirement()` as a
    MEASURED value would be exactly the conflation section 289 forbids. (A
    caller who legitimately wants to check a real measured latency against a
    documented bound extracted here may build a
    `amba_performance_requirement_checker.PerformanceRequirementIR` from one
    of THIS module's facts as the REQUIREMENT side of that comparison --
    that direction is fine and is exactly what the two modules are for
    together; this module just never performs the comparison itself.)

REUSE OVER REINVENT -- WHAT WAS CHECKED FIRST.
-----------------------------------------------------------------------------
A repo-wide grep for `timing_requirement`, `setup_time`, `hold_time`,
`tsu`/`thold`, `TimingRequirement` and "section 289" before writing anything
matched nothing executable (`prompts.py`'s `max_transaction_latency`/
`max_ack_latency_cycles` evidence blocks are MEASURED-vs-bound gate prompts
for already-running dynamic gates, not a spec-text extractor, and carry no
citation/provenance concept at all). Two real siblings were read in full and
are deliberately NOT extended or duplicated:

  * `dv_harness/system_failure_taxonomy.py`'s `TIMING_FAILURE` classifies
    ALREADY-REPORTED violation TEXT from a log/report -- "a setup/hold
    violation citation, a race condition, a glitch" that SOMETHING ELSE
    (a simulator, a linter) already found and wrote down. It answers "did a
    timing failure get reported", never "what bound did the spec state
    before any run happened". This module answers the second question, which
    that module's own docstring explicitly disclaims answering ("measures
    nothing and runs no timing analysis of its own").
  * `dv_harness/interrupt_dma_clock_reset_extraction.py` is the closest real
    architectural sibling in MECHANISM, not domain: a declaration-level,
    caller-supplied-text line-scan over RTL and prose, bounded to EXPLICIT
    statement forms, with an honest per-facet NOT_AVAILABLE when nothing
    explicit is found. This module reuses that same discipline (and the same
    `RTL_SUFFIXES`/`TEXT_SUFFIXES`/`classify_source()` shape, independently
    re-declared here rather than imported, because importing a sibling
    extractor module for three constants would be a heavier coupling than
    the three lines saved) but extracts a structurally different fact
    (a numeric timing bound with a comparison direction and unit, not an
    interrupt/DMA/clock-reset topology fact) and is therefore its own
    module, not an extension of that one.

WHAT IS DELIBERATELY NOT ATTEMPTED. This is a regex line-scan, not a timing
analyzer or a natural-language understander: a bound is extracted ONLY when
one line states, together, (1) a recognized timing-requirement keyword
(setup time/tSU, hold time/tHOLD, or latency), (2) a real number with a
recognized unit (ps/ns/us/ms, or a cycle count), AND (3) an explicit
directional cue spelling out which way the bound goes (at least/minimum/>=,
or shall-not-exceed/maximum/<=, or exactly/==). A line naming a timing
keyword with no number ("the setup time is TBD"), a number with no
directional cue ("latency is 50 ns" -- ambiguous whether that is a ceiling,
a floor, or a typical value), or a directional cue with no timing keyword,
contributes NOTHING -- never a guessed comparison, unit, or value. A subject
(the signal pair or path a bound applies to, e.g. "DATA relative to CLK") is
extracted only from two explicit textual forms ("between X and Y", "for X
relative to Y") and is honestly `None` -- not omitted, not guessed --
whenever the line does not use one of those forms. Numbers are never
unit-converted (a "20 ns" fact and a "16 cycles" fact are reported in their
own stated units, side by side, exactly as written) because converting
cycles to time requires a clock period this module has no evidence for and
would otherwise have to invent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

SCHEMA_VERSION = "1.0"

RTL_SUFFIXES = (".v", ".sv", ".vh", ".svh")
TEXT_SUFFIXES = (".txt", ".md", ".rst", ".pgv", ".spec")

TIMING_REQUIREMENT_KINDS = ("SETUP", "HOLD", "LATENCY")
_COMPARISONS = (">=", "<=", "==")

STATUS_LOADED = "LOADED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"


class TimingRequirementExtractionError(ValueError):
    """A caller-USAGE error: an attempt to construct a `TimingRequirementFact`
    missing one of its mandatory fields (kind/comparison/value/unit/text/
    evidence), or carrying a value/kind/comparison this module does not
    recognize. Every one of these fields is mandatory precisely because a
    timing requirement fact with no citation, no stated direction, or no
    real number is exactly the fabricated-looking fact the Evidence Truth
    Rule forbids -- this is enforced in `__post_init__`, not only documented,
    so no code path (including a future caller building a fact by hand
    instead of through the scanner) can construct one that skips it."""


# ---------------------------------------------------------------------------
# The fact: every field mandatory, checked in code.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TimingRequirementFact:
    """One DOCUMENTED timing requirement, transcribed -- never computed or
    measured -- from a real line of caller-supplied text. `value`/`unit` are
    exactly what that line states; `evidence` is a mandatory `path:line`
    citation, because a timing bound with no citation back to the text that
    stated it is not a fact this module will construct."""

    kind: str            # one of TIMING_REQUIREMENT_KINDS
    comparison: str      # one of _COMPARISONS
    value: float
    unit: str            # normalized: ps/ns/us/ms/cycles
    unit_raw: str         # exactly as written in the source line
    subject: Optional[str]
    text: str
    evidence: str

    def __post_init__(self) -> None:
        if self.kind not in TIMING_REQUIREMENT_KINDS:
            raise TimingRequirementExtractionError(
                f"TimingRequirementFact.kind must be one of "
                f"{TIMING_REQUIREMENT_KINDS}, got {self.kind!r}"
            )
        if self.comparison not in _COMPARISONS:
            raise TimingRequirementExtractionError(
                f"TimingRequirementFact.comparison must be one of "
                f"{_COMPARISONS}, got {self.comparison!r}"
            )
        if self.value is None or isinstance(self.value, bool) or not isinstance(
            self.value, (int, float)
        ):
            raise TimingRequirementExtractionError(
                "TimingRequirementFact.value is required and must be a real "
                "number -- a documented timing bound is never invented or "
                "defaulted by this module, only ever transcribed from a real "
                "cited statement"
            )
        if not self.unit:
            raise TimingRequirementExtractionError(
                "TimingRequirementFact.unit is required -- always transcribed "
                "from the source text, never invented"
            )
        if not self.text:
            raise TimingRequirementExtractionError(
                "TimingRequirementFact.text (the raw source sentence/line) is "
                "required -- a fact with no recorded source text cannot be "
                "checked by a human reviewer"
            )
        if not self.evidence:
            raise TimingRequirementExtractionError(
                "TimingRequirementFact.evidence (a 'path:line' citation) is "
                "required -- a timing requirement fact with no citation back "
                "to the text that stated it is exactly the unsupported claim "
                "the Evidence Truth Rule forbids"
            )


# ---------------------------------------------------------------------------
# Pattern vocabulary. Every regex below matches only real, explicit language
# a spec/programming-guide/RTL comment would carry -- never a bare protocol
# name, and never inferred from the mere presence of a timing-sounding word.
# ---------------------------------------------------------------------------
_SETUP_KEYWORD_RE = re.compile(r"\bsetup\s*time\b|\bt_?su\b", re.IGNORECASE)
_HOLD_KEYWORD_RE = re.compile(r"\bhold\s*time\b|\bt_?hold\b|\bt_?hd\b", re.IGNORECASE)
_LATENCY_KEYWORD_RE = re.compile(r"\blatency\b", re.IGNORECASE)

_KIND_KEYWORDS = (
    ("SETUP", _SETUP_KEYWORD_RE),
    ("HOLD", _HOLD_KEYWORD_RE),
    ("LATENCY", _LATENCY_KEYWORD_RE),
)

# A number with a recognized timing unit -- ps/ns/us/ms (time) or a cycle
# count. Deliberately requires the unit to be spelled out; a bare number
# ("the bound is 5") is never treated as a timing value.
_NUM_UNIT_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>ps|ns|[uµ]s|ms|clock\s*cycles|clk\s*cycles|cycles)\b",
    re.IGNORECASE,
)
_UNIT_NORMALIZE = {
    "ps": "ps", "ns": "ns", "us": "us", "µs": "us", "ms": "ms",
    "clock cycles": "cycles", "clk cycles": "cycles", "cycles": "cycles",
}

# Directional cues -- the ONLY way a comparison is decided. No cue, no fact.
_MIN_CUE_RE = re.compile(
    r"\b(at\s+least|no\s+less\s+than|minimum|min\.?)\b|>=", re.IGNORECASE
)
_MAX_CUE_RE = re.compile(
    r"\b(at\s+most|no\s+more\s+than|shall\s+not\s+exceed|must\s+not\s+exceed|"
    r"maximum|max\.?)\b|<=",
    re.IGNORECASE,
)
_EXACT_CUE_RE = re.compile(r"\b(exactly|fixed\s+at)\b|==", re.IGNORECASE)

# A line reporting what a run actually produced is a MEASUREMENT claim, never
# a documented requirement -- excluded outright, even when it also uses a
# timing keyword and a directional-looking word. This is the structural
# enforcement of "never a measured timing value".
_MEASURED_VALUE_EXCLUSION_RE = re.compile(
    r"\b(observed|measured|simulat\w*|waveform|sim\.log|actual)\b",
    re.IGNORECASE,
)

_SUBJECT_BETWEEN_RE = re.compile(
    r"\bbetween\s+(?P<a>[A-Za-z_]\w*)\s+and\s+(?P<b>[A-Za-z_]\w*)", re.IGNORECASE
)
_SUBJECT_FOR_RE = re.compile(
    r"\bfor\s+(?P<a>[A-Za-z_]\w*)\s+relative\s+to\s+(?P<b>[A-Za-z_]\w*)",
    re.IGNORECASE,
)


def _extract_subject(line: str) -> Optional[str]:
    """Only the two explicit textual forms this module recognizes ever
    populate `subject`; anything else is honestly `None` rather than a
    best-effort guess at which signal a bound concerns."""
    m = _SUBJECT_BETWEEN_RE.search(line) or _SUBJECT_FOR_RE.search(line)
    if not m:
        return None
    return f"{m.group('a')}-{m.group('b')}"


def _decide_comparison(line: str) -> Optional[str]:
    """Returns the one comparison this line explicitly states, or `None` if
    the line states no direction at all -- never a default. `_MIN_CUE_RE` and
    `_MAX_CUE_RE` are checked before `_EXACT_CUE_RE` because a real sentence
    stating a minimum or maximum bound is the overwhelmingly common documented
    form; a bare '=' with neither a min nor a max cue nearby is the rarer
    exact-value statement."""
    if _MIN_CUE_RE.search(line):
        return ">="
    if _MAX_CUE_RE.search(line):
        return "<="
    if _EXACT_CUE_RE.search(line):
        return "=="
    return None


def _scan_timing_requirements(lines: List[str], path: str) -> List[TimingRequirementFact]:
    facts: List[TimingRequirementFact] = []
    for lineno, raw_line in enumerate(lines, start=1):
        if _MEASURED_VALUE_EXCLUSION_RE.search(raw_line):
            continue  # a reported measurement, never a documented requirement
        for kind, keyword_re in _KIND_KEYWORDS:
            if not keyword_re.search(raw_line):
                continue
            num_m = _NUM_UNIT_RE.search(raw_line)
            if not num_m:
                continue  # keyword present, no real number -- nothing to extract
            comparison = _decide_comparison(raw_line)
            if comparison is None:
                continue  # a magnitude with no stated direction is never guessed
            unit_raw = num_m.group("unit")
            unit = _UNIT_NORMALIZE.get(re.sub(r"\s+", " ", unit_raw.lower()), unit_raw.lower())
            facts.append(
                TimingRequirementFact(
                    kind=kind,
                    comparison=comparison,
                    value=float(num_m.group("value")),
                    unit=unit,
                    unit_raw=unit_raw,
                    subject=_extract_subject(raw_line),
                    text=raw_line.strip(),
                    evidence=f"{path}:{lineno}",
                )
            )
    return facts


# ---------------------------------------------------------------------------
# Top-level extraction, mirroring interrupt_dma_clock_reset_extraction.py's
# own source-handling/status shape so a caller already familiar with that
# module reads this one for free.
# ---------------------------------------------------------------------------
def classify_source(path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in RTL_SUFFIXES:
        return "rtl"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "unknown"


def extract_timing_requirements(source_paths) -> dict:
    """Extract DOCUMENTED setup/hold/latency timing requirements from real
    spec/programming-guide/RTL-comment TEXT a caller supplies. `source_paths`
    is a list of str/Path; every file is read (never fabricated), and a
    missing/unreadable file is recorded as an honest per-source failure
    rather than silently skipped or raised past the caller. Never runs a
    simulator, reads a waveform, or otherwise measures anything -- pure text
    extraction, see the module docstring."""
    source_paths = list(source_paths or [])
    read_sources: List[str] = []
    missing_sources: List[str] = []
    unrecognized_sources: List[str] = []

    all_facts: List[TimingRequirementFact] = []

    for raw_path in source_paths:
        p = Path(raw_path)
        if not p.is_file():
            missing_sources.append(str(raw_path))
            continue
        kind = classify_source(p)
        if kind == "unknown":
            unrecognized_sources.append(str(raw_path))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            missing_sources.append(f"{raw_path} ({exc})")
            continue
        path_str = str(raw_path)
        read_sources.append(path_str)
        all_facts.extend(_scan_timing_requirements(text.splitlines(), path_str))

    by_kind = {kind: [] for kind in TIMING_REQUIREMENT_KINDS}
    for f in all_facts:
        by_kind[f.kind].append(f)

    def _serialize(fact: TimingRequirementFact) -> dict:
        return {
            "kind": fact.kind,
            "comparison": fact.comparison,
            "value": fact.value,
            "unit": fact.unit,
            "unit_raw": fact.unit_raw,
            "subject": fact.subject,
            "text": fact.text,
            "evidence": fact.evidence,
        }

    by_kind_serialized = {
        kind: {
            "status": STATUS_LOADED if facts_of_kind else STATUS_NOT_AVAILABLE,
            "reason": None if facts_of_kind else (
                f"no explicit, cited {kind.lower()} statement (a recognized keyword, a "
                "real number with a recognized unit, and an explicit min/max/exact "
                "directional cue, all on the same line) was found in the supplied "
                "sources -- never inferred from a bare keyword or a bare number"
            ),
            "requirements": [_serialize(f) for f in facts_of_kind],
        }
        for kind, facts_of_kind in by_kind.items()
    }

    if all_facts:
        req_status, req_reason = STATUS_LOADED, None
    else:
        req_status = STATUS_NOT_AVAILABLE
        req_reason = (
            "no documented setup/hold/latency timing requirement was found in the "
            "supplied sources -- a bound is never fabricated in its absence"
        )

    timing_requirements = {
        "status": req_status,
        "reason": req_reason,
        "requirements": [_serialize(f) for f in all_facts],
        "by_kind": by_kind_serialized,
    }

    if not source_paths:
        top_status, top_reason = STATUS_NOT_AVAILABLE, "no source files were supplied"
    elif not read_sources:
        top_status = STATUS_NOT_AVAILABLE
        top_reason = (
            f"none of the {len(source_paths)} supplied source path(s) could be read: "
            f"{missing_sources}"
        )
    elif all_facts:
        top_status, top_reason = STATUS_LOADED, None
    else:
        top_status = STATUS_NOT_AVAILABLE
        top_reason = (
            "supplied sources were read but no documented timing requirement could be "
            "extracted from them"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": top_status,
        "source": {
            "kind": "timing_requirement_source_text",
            "paths": read_sources,
            "missing": missing_sources,
            "unrecognized": unrecognized_sources,
        },
        "reason": top_reason,
        "timing_requirements": timing_requirements,
    }


# ---------------------------------------------------------------------------
# CLI front door -- same shared convention `interrupt_dma_clock_reset_
# extraction.py`/`power-intent`/`golden-scenario` follow. Wired into cli.py
# as `dv-harness timing-requirements --sources <f> [<f> ...] [--json]`,
# which builds an `["extract", "--sources", ...]`-shaped argv and calls
# `execute_verb(argv)` below unmodified -- the identical pattern
# `interrupt-dma-clock-reset` already uses for this same argv(list) shape.
# ---------------------------------------------------------------------------
def execute_verb(argv: list) -> int:
    import json as _json
    import sys as _sys

    if not argv or argv[0] not in ("extract",):
        print(
            "usage: timing_requirement_extraction extract --sources <f> [<f> ...] [--json]",
            file=_sys.stderr,
        )
        return 2
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if "--sources" in args:
        idx = args.index("--sources")
        sources = args[idx + 1:]
    else:
        sources = args
    report = extract_timing_requirements(sources)
    if as_json:
        print(_json.dumps(report, indent=2))
    else:
        print(
            f"status: {report['status']}"
            + (f" ({report['reason']})" if report["reason"] else "")
        )
        tr = report["timing_requirements"]
        for kind in TIMING_REQUIREMENT_KINDS:
            block = tr["by_kind"][kind]
            print(f"  {kind:8s}: {block['status']} ({len(block['requirements'])} found)")
    return 0 if report["status"] == STATUS_LOADED else 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(execute_verb(sys.argv[1:]))
