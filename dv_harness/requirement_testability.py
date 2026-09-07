"""dv_harness/requirement_testability.py -- spec section 218's REQUIREMENT
TESTABILITY classification: whether a requirement_contract.py record actually
has an observable signal / checkable condition (TESTABLE), or is untestable
prose that merely SOUNDS resolved (UNTESTABLE_PROSE), or cannot honestly be
determined from what the record contains (INDETERMINATE) -- purely additive
on top of `dv_harness/requirement_contract.py`, and deliberately a DIFFERENT
vocabulary from that module's own.

WHY THIS IS A SEPARATE MODULE RATHER THAN A REQUIREMENT_CONTRACT.PY CHANGE.
`requirement_contract.py` already answers "is this requirement's CONTRACT
internally coherent and honestly statused" -- its five-value status
(COMPLETE / PARTIAL / AMBIGUOUS / CONTRADICTORY / UNKNOWN) is about whether
the fifteen fields are RESOLVED (present, non-placeholder) and whether a
filed ambiguity/contradiction is being stepped over. It is silent on a
different, real defect: a requirement can be schema-COMPLETE, every field
resolved with real prose, `derive_status()` genuinely returning COMPLETE --
and still be UNTESTABLE, because its `expected_result`/`checker`/
`observability` text never names anything a checker/monitor could actually
compare against ("the system shall behave correctly", "performance shall be
acceptable"). `unresolved_fields()`/`is_resolved()` treat that prose as fully
RESOLVED -- it is not a placeholder, not TBD, not empty -- so nothing in that
module ever flags it. Section 218 names this as its own question, and this
module answers it without touching requirement_contract.py's own status
field, its own five values, or its own `derive_status()` precedence in any
way.

VOCABULARY -- deliberately DISJOINT from both `requirement_contract.py`'s
five status values and `dv_harness.models.Status`'s ten verdict values
(checked at import by `assert_no_status_vocabulary_collision()`, the same
discipline several sibling modules in this project already apply to their
own domain vocabularies):

  * TESTABLE          -- the record's own text names a checkable condition
                         (a comparison, a concrete value, an explicit
                         checker/assertion/scoreboard mechanism) AND an
                         observable signal (a named register/signal, or an
                         explicit observation mechanism -- a waveform, a
                         monitor, a status bit). Both, not either: an
                         expected result nobody can OBSERVE is exactly as
                         untestable as an observation nobody has a
                         CONDITION to check.
  * UNTESTABLE_PROSE  -- the record's checker/expected_result/observability
                         text is present and resolved, but reads as purely
                         qualitative/subjective prose ("shall work
                         correctly", "shall be robust", "in a timely
                         manner") with no checkable condition and no
                         observable signal detected anywhere.
  * INDETERMINATE     -- neither of the above could be honestly concluded:
                         every relevant field is unresolved (nothing to
                         evaluate at all), or the record's evidence is a
                         genuine MIX (a checkable condition with no named
                         observable, or the reverse) that this module
                         refuses to force into either TESTABLE or
                         UNTESTABLE_PROSE. Per the Evidence Truth Rule, an
                         absent or inconclusive signal must produce an
                         honest, distinctly-named status, never a guessed
                         one -- INDETERMINATE is that status, not a fourth
                         severity level and never silently defaulted to
                         TESTABLE.

DETECTION IS HEURISTIC, STATED AS SUCH. `detect_checkable_condition()` /
`detect_observable_signal()` / `detect_untestable_prose_phrases()` are
pattern scans (comparison operators, concrete numeric/hex/timing literals,
named SIGNAL_LIKE tokens, explicit checker/observation-mechanism keywords,
and a fixed list of subjective quality phrases) -- not a semantic parse of
the requirement's meaning. A requirement using different, equally concrete
wording this module's patterns do not recognise reports INDETERMINATE rather
than a wrong classification in either direction; a false TESTABLE (missing a
real defect) is a worse failure mode than an honest INDETERMINATE, so the
patterns are written narrow rather than broad.

REUSE OVER REINVENT. `is_resolved()` and `declares_contract_shape()` are
imported from `requirement_contract.py`, never re-typed: whether a field
counts as "there is text here to evaluate" must answer identically in both
modules, or a requirement could read RESOLVED in one and UNRESOLVED in the
other for the same content. `detect_ambiguous_language()` is imported too --
its hedging-phrase hits ("should generally", "as appropriate", ...) are one
additional signal fed into the untestable-prose determination when neither
this module's own checkable-condition nor observable-signal patterns matched
that same text, rather than a second, disagreeing hedge-detector being
written here.

ARBITRATION IS NOT HERE. This module classifies; it never edits a record,
never resolves an ambiguity/contradiction, and never changes
`requirement_contract.py`'s own `status` field or `derive_status()` output.
A CONTRADICTORY or AMBIGUOUS requirement (per requirement_contract.py's own
derivation) is still independently scored for testability here -- the two
questions ("is this requirement internally coherent" and "is this
requirement's content actually checkable") are orthogonal, and this module
answers only the second.

DELIBERATELY BOUNDED. This module reads a requirement RECORD's own text; it
does not parse a specification, does not consult RTL/VIP/simulation
evidence, and does not decide whether a *named* observable signal genuinely
exists in a real design (that is `dut_evidence_correlation.py`'s job, not
imported here to keep this module's own dependency surface small and this
task's file-safety scope narrow). It also decides nothing on its own: it has
no stage gate, and no existing gate script or CLI verb was edited to reach
it -- the standalone `python -m dv_harness.requirement_testability` front
door is deliberately how it is reached, mirroring the disclosed choice
several very recent same-day additions in this project have already made
when `cli.py`/`gates.py` are under concurrent edit pressure from many other
items in the same batch.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .requirement_contract import (
    declares_contract_shape,
    detect_ambiguous_language,
    is_resolved,
)

SCHEMA_VERSION = "1.0"

#: Section 218's three-value testability vocabulary. Deliberately disjoint
#: from requirement_contract.REQUIREMENT_STATUSES and from
#: dv_harness.models.Status -- checked at import, not merely asserted in
#: prose, by assert_no_status_vocabulary_collision() below.
TESTABILITY_TESTABLE = "TESTABLE"
TESTABILITY_UNTESTABLE_PROSE = "UNTESTABLE_PROSE"
TESTABILITY_INDETERMINATE = "INDETERMINATE"
TESTABILITY_VALUES: Tuple[str, ...] = (
    TESTABILITY_TESTABLE, TESTABILITY_UNTESTABLE_PROSE, TESTABILITY_INDETERMINATE,
)

TESTABILITY_DEFINITIONS: Dict[str, str] = {
    TESTABILITY_TESTABLE: "the record names both a checkable condition and an "
                          "observable signal -- a generator could build a real "
                          "checker/monitor from it",
    TESTABILITY_UNTESTABLE_PROSE: "the record's text is resolved but reads as "
                                  "purely qualitative prose with no checkable "
                                  "condition and no observable signal",
    TESTABILITY_INDETERMINATE: "not enough evidence either way -- fields are "
                               "unresolved, or the evidence is a genuine mix -- "
                               "never guessed toward TESTABLE or UNTESTABLE_PROSE",
}

SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

#: The three fields section 218's testability question is actually about:
#: what mechanism decides pass/fail, what the pass/fail condition itself is,
#: and where it is visible. Deliberately excludes `stimulus` -- a stimulus
#: describes what is DRIVEN, not what is CHECKED or OBSERVED, and this
#: module is about the latter two.
TESTABILITY_SOURCE_FIELDS: Tuple[str, ...] = ("checker", "expected_result", "observability")

# --------------------------------------------------------------------------
# Detection patterns -- heuristic, narrow by design (see module docstring).
# --------------------------------------------------------------------------

#: A CHECKABLE CONDITION: a real comparison, a concrete value/timing literal,
#: or an explicit checker/assertion mechanism named in the text.
_CHECKABLE_CONDITION_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("comparison_operator", re.compile(r"(==|!=|<=|>=|(?<![<>=!])[<>](?!=))")),
    ("comparison_phrase", re.compile(
        r"\b(shall|must|will)\s+(be\s+)?(equal|not\s+equal|greater\s+than|less\s+than|"
        r"at\s+least|at\s+most|exceed|match(?:es)?)\b", re.IGNORECASE)),
    ("assignment_phrase", re.compile(
        r"\b(shall|must)\s+be\s+(set|cleared|asserted|deasserted|driven)\b", re.IGNORECASE)),
    ("hex_literal", re.compile(r"\b0x[0-9A-Fa-f]+\b")),
    ("verilog_literal", re.compile(r"\b\d+'[bBhHdDoO][0-9A-Fa-fxXzZ_]+\b")),
    ("timing_value", re.compile(
        r"\b\d+(\.\d+)?\s*(ns|us|ms|ps|s|cycles?|clk|MHz|GHz|kHz|bytes?|KB|MB)\b",
        re.IGNORECASE)),
    ("bounded_value", re.compile(
        r"\bwithin\s+\d+\b|\bno\s+more\s+than\s+\d+\b|\bno\s+less\s+than\s+\d+\b",
        re.IGNORECASE)),
    ("checker_mechanism", re.compile(
        r"\b(assert(?:ion)?|scoreboard|self-check|self-checking|cross-check|"
        r"compar(?:e|ison|ed)|mismatch)\b", re.IGNORECASE)),
)

#: An OBSERVABLE SIGNAL: a concrete SIGNAL_LIKE identifier, or an explicit
#: observation mechanism named in the text.
_OBSERVABLE_SIGNAL_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("signal_like_token", re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")),
    ("observation_mechanism", re.compile(
        r"\b(waveform|monitor(?:ed)?|probe[ds]?|trace[ds]?|signal|register|"
        r"status\s+bit|interrupt\s+line|gpio|readback|coverage\s+point|"
        r"sampled\s+(?:on|via|at)|observed\s+(?:on|via|at)|log\s+message|"
        r"log\s+pattern)\b", re.IGNORECASE)),
)

#: UNTESTABLE-PROSE phrases: subjective/qualitative claims with no measurable
#: condition. Longest phrase first, matched case-insensitively -- the same
#: "cite the whole phrase, not a shorter substring it contains" convention
#: requirement_contract.detect_ambiguous_language() already uses.
UNTESTABLE_PROSE_PHRASES: Tuple[str, ...] = (
    "shall function correctly", "shall function properly",
    "shall behave as expected", "shall behave correctly", "shall behave properly",
    "shall work correctly", "shall work properly", "shall operate correctly",
    "shall operate properly", "function correctly", "function properly",
    "functions correctly", "functions properly", "behave correctly",
    "behave properly", "behave as expected", "behaves correctly",
    "behaves properly", "operate correctly", "operate properly",
    "work correctly", "work properly", "works correctly", "works properly",
    "gracefully handle", "gracefully handles", "in a timely manner",
    "as quickly as possible", "properly handled", "good performance",
    "acceptable performance", "reasonable time", "appropriate manner",
    "user-friendly", "user friendly", "be robust", "be reliable",
    "be efficient", "be intuitive", "run smoothly", "smoothly",
    "satisfactory", "adequate", "sufficient",
)


def _dedup_longest_first(matched: Sequence[str]) -> List[str]:
    """Sort by length descending and drop any shorter entry wholly contained
    in an already-kept longer one -- the same de-dup rule
    requirement_contract.detect_ambiguous_language() applies, reused here so
    two different phrase scans in this project behave identically."""
    ordered = sorted(set(matched), key=len, reverse=True)
    out: List[str] = []
    for phrase in ordered:
        if not any(phrase != longer and phrase in longer for longer in out):
            out.append(phrase)
    return out


def detect_checkable_condition(text: Any) -> List[str]:
    """Every CHECKABLE_CONDITION pattern label found in `text`. Non-string or
    unresolved input returns [] -- a missing field is the already-covered
    UNRESOLVED_FIELD defect, not evidence about testability either way."""
    if not isinstance(text, str) or not text.strip():
        return []
    return sorted({label for label, pattern in _CHECKABLE_CONDITION_PATTERNS
                   if pattern.search(text)})


def detect_observable_signal(text: Any) -> List[str]:
    """Every OBSERVABLE_SIGNAL pattern label found in `text`, plus the actual
    matched SIGNAL_LIKE tokens (deduplicated) so a finding can cite the real
    name rather than only the generic label. Non-string/unresolved -> []."""
    if not isinstance(text, str) or not text.strip():
        return []
    hits: List[str] = []
    for label, pattern in _OBSERVABLE_SIGNAL_PATTERNS:
        found = pattern.findall(text)
        if not found:
            continue
        if label == "signal_like_token":
            hits.extend(sorted(set(found)))
        else:
            hits.append(label)
    return sorted(set(hits))


def detect_untestable_prose_phrases(text: Any) -> List[str]:
    """Every UNTESTABLE_PROSE_PHRASES entry found in `text` (case-insensitive
    substring match), longest phrase first with shorter contained matches
    dropped. Non-string/unresolved input returns []."""
    if not isinstance(text, str) or not text.strip():
        return []
    lowered = text.lower()
    matched = [p for p in UNTESTABLE_PROSE_PHRASES if p in lowered]
    return _dedup_longest_first(matched)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

@dataclass
class TestabilityResult:
    status: str
    reason: str
    checkable_evidence: List[str] = field(default_factory=list)
    observable_evidence: List[str] = field(default_factory=list)
    untestable_phrases: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "checkable_evidence": self.checkable_evidence,
            "observable_evidence": self.observable_evidence,
            "untestable_phrases": self.untestable_phrases,
        }


def classify_requirement_testability(record: dict) -> TestabilityResult:
    """Classify ONE requirement record's testability from its own
    checker/expected_result/observability text. Never consults `status`,
    `confidence`, `priority` or `criticality` -- testability is a content
    question, independent of requirement_contract.py's own derived status."""
    field_texts = {name: record.get(name) for name in TESTABILITY_SOURCE_FIELDS}
    resolved_fields = {name: text for name, text in field_texts.items()
                       if is_resolved(text, name)}

    if not resolved_fields:
        return TestabilityResult(
            TESTABILITY_INDETERMINATE,
            "checker, expected_result and observability are all unresolved: "
            "there is no content to evaluate for testability")

    checkable_evidence: List[str] = []
    for name in ("checker", "expected_result"):
        text = resolved_fields.get(name)
        if text is not None:
            checkable_evidence.extend(detect_checkable_condition(text))
    checkable_evidence = sorted(set(checkable_evidence))

    observable_evidence: List[str] = []
    for name in ("observability", "checker"):
        text = resolved_fields.get(name)
        if text is not None:
            observable_evidence.extend(detect_observable_signal(text))
    observable_evidence = sorted(set(observable_evidence))

    untestable_phrases: List[Dict[str, str]] = []
    for name, text in resolved_fields.items():
        for phrase in detect_untestable_prose_phrases(text):
            untestable_phrases.append({"field": name, "phrase": phrase, "basis": "prose_scan"})
        # Reuse requirement_contract's own hedging-language scan as ADDITIONAL
        # signal -- a hedge that reads as resolved without committing to one
        # behavior is exactly the shape of prose this module also cares about.
        for phrase in detect_ambiguous_language(text):
            untestable_phrases.append({"field": name, "phrase": phrase, "basis": "hedging_scan"})

    if checkable_evidence and observable_evidence:
        return TestabilityResult(
            TESTABILITY_TESTABLE,
            "a checkable condition (%s) and an observable signal (%s) were both found"
            % (", ".join(checkable_evidence), ", ".join(observable_evidence)),
            checkable_evidence, observable_evidence, untestable_phrases)

    if untestable_phrases and not checkable_evidence and not observable_evidence:
        cited = ", ".join(sorted({f"{h['field']}:{h['phrase']!r}" for h in untestable_phrases}))
        return TestabilityResult(
            TESTABILITY_UNTESTABLE_PROSE,
            f"resolved text carries no checkable condition and no observable "
            f"signal, only qualitative prose: {cited}",
            checkable_evidence, observable_evidence, untestable_phrases)

    missing = []
    if not checkable_evidence:
        missing.append("no checkable condition detected")
    if not observable_evidence:
        missing.append("no observable signal detected")
    return TestabilityResult(
        TESTABILITY_INDETERMINATE,
        "inconclusive: " + "; ".join(missing) +
        (f" (checkable evidence present: {', '.join(checkable_evidence)})" if checkable_evidence else "") +
        (f" (observable evidence present: {', '.join(observable_evidence)})" if observable_evidence else ""),
        checkable_evidence, observable_evidence, untestable_phrases)


# --------------------------------------------------------------------------
# Findings / analysis (mirrors requirement_contract.py's own shape)
# --------------------------------------------------------------------------

def _finding(severity: str, code: str, requirement_id: Any, detail: str, **extra) -> dict:
    out = {"severity": severity, "code": code, "requirement_id": requirement_id, "detail": detail}
    out.update(extra)
    return out


def analyze_requirement_testability(record: dict) -> List[dict]:
    """Testability findings for ONE contract-shaped requirement record.
    Returns [] both when the record is TESTABLE and when it does not declare
    the contract shape at all (this module only judges contract-shaped
    records, the same discriminator requirement_contract.py's own gate uses)."""
    if not declares_contract_shape(record):
        return []
    rid = record.get("requirement_id")
    result = classify_requirement_testability(record)
    if result.status == TESTABILITY_UNTESTABLE_PROSE:
        return [_finding(
            SEVERITY_WARNING, "REQUIREMENT_UNTESTABLE_PROSE", rid,
            f"requirement reads as untestable prose: {result.reason}",
            testability_status=result.status,
            checkable_evidence=result.checkable_evidence,
            observable_evidence=result.observable_evidence)]
    if result.status == TESTABILITY_INDETERMINATE:
        return [_finding(
            SEVERITY_INFO, "REQUIREMENT_TESTABILITY_INDETERMINATE", rid,
            f"testability could not be determined: {result.reason}",
            testability_status=result.status,
            checkable_evidence=result.checkable_evidence,
            observable_evidence=result.observable_evidence)]
    return []


def analyze_requirement_testability_set(records: Sequence[dict]) -> dict:
    """Analyze every contract-shaped record in `records`. Returns
    {"analyzed": n, "testability_counts": {...}, "findings": [...]}."""
    findings: List[dict] = []
    counts = {v: 0 for v in TESTABILITY_VALUES}
    analyzed = 0
    for record in records:
        if not isinstance(record, dict) or not declares_contract_shape(record):
            continue
        analyzed += 1
        result = classify_requirement_testability(record)
        counts[result.status] += 1
        findings.extend(analyze_requirement_testability(record))
    return {"analyzed": analyzed, "testability_counts": counts, "findings": findings}


# --------------------------------------------------------------------------
# Vocabulary-collision guard
# --------------------------------------------------------------------------

def assert_no_status_vocabulary_collision() -> None:
    """This module's own three-value vocabulary must share no token with
    requirement_contract.py's five status values or with
    dv_harness.models.Status's ten verdict values -- run at import, the same
    discipline several sibling modules in this project already apply to
    their own domain vocabularies, so a future edit that reaches for one of
    those tokens fails loudly rather than silently colliding."""
    from . import requirement_contract as _rc
    from . import models as _models

    other_tokens = set(_rc.REQUIREMENT_STATUSES) | {s.value for s in _models.Status}
    collision = set(TESTABILITY_VALUES) & other_tokens
    if collision:
        raise AssertionError(
            f"requirement_testability vocabulary collides with an existing "
            f"status vocabulary: {sorted(collision)}")


assert_no_status_vocabulary_collision()


# --------------------------------------------------------------------------
# CLI (same execute_verb convention as requirement_contract / power_intent)
# --------------------------------------------------------------------------

def execute_verb(requirements_path: str, as_json: bool = False,
                 fail_on_indeterminate: bool = False) -> Tuple[str, int]:
    """Analyze a requirements document for testability. Exit codes: 0 clean
    (no UNTESTABLE_PROSE, and no INDETERMINATE unless --fail-on-indeterminate),
    1 a real finding present, 2 nothing in the contract shape to analyze."""
    try:
        doc = json.loads(Path(requirements_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return (json.dumps({"status": "NOT_AVAILABLE", "reason": str(exc)})
                if as_json else f"NOT_AVAILABLE: {exc}"), 2

    records = doc.get("requirements", []) if isinstance(doc, dict) else doc
    result = analyze_requirement_testability_set(records)
    result["source"] = str(requirements_path)

    warnings = [f for f in result["findings"] if f["severity"] == SEVERITY_WARNING]
    if result["analyzed"] == 0:
        result["status"] = "NOT_AVAILABLE"
        result["reason"] = ("no requirement record declares contract_schema_version; "
                            "nothing to analyze for testability")
        code = 2
    elif warnings or (fail_on_indeterminate and result["findings"]):
        result["status"] = "FAIL"
        code = 1
    else:
        result["status"] = "PASS"
        code = 0

    if as_json:
        return json.dumps(result, indent=2), code
    lines = [f"requirement-testability: {result['status']} "
             f"({result['analyzed']} contract-shaped requirement(s) analyzed)"]
    if result.get("reason"):
        lines.append(f"  reason: {result['reason']}")
    for v in TESTABILITY_VALUES:
        if result["testability_counts"].get(v):
            lines.append(f"  {v}: {result['testability_counts'][v]}")
    for f in result["findings"]:
        lines.append(f"  [{f['severity']}] {f['code']} ({f['requirement_id']}): {f['detail']}")
    return "\n".join(lines), code


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin shell
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.requirement_testability",
        description="Classify spec section 184 requirement_contract.py records by "
                    "section 218's testability question: TESTABLE / UNTESTABLE_PROSE / "
                    "INDETERMINATE -- additive on top of the contract's own status.")
    ap.add_argument("--requirements", required=True,
                    help="JSON file with a top-level `requirements` list.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-indeterminate", action="store_true",
                    help="Also fail on INDETERMINATE findings, not only UNTESTABLE_PROSE.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.requirements, as_json=a.json,
                              fail_on_indeterminate=a.fail_on_indeterminate)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
