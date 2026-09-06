"""Five structural-absence patterns over a requirement set, each reported POTENTIAL_SPEC_GAP.

A specification can be internally self-consistent in every individual sentence and still be
STRUCTURALLY incomplete: it defines what happens when a transfer completes, but never says what
happens when it errors; it defines an enable bit, but never a disable path; it defines an
interrupt being asserted, but never how it is cleared; it defines a reset, but never what happens
to whatever was already in flight when that reset lands; it defines an error condition, but never
a recovery path back out of it. None of this repo's existing spec/requirement machinery asks that
question. `requirement_contract.py` (section 184) checks whether a SINGLE requirement RECORD is
internally coherent (its own fifteen fields present, its own declared status honestly derived) --
it never compares one requirement against another to ask whether a structural COUNTERPART is
missing. `spec_vplan_delta.py` and the `spec_to_vplan_*` gates compare a spec against a vPlan, not
a requirement set against itself. Nothing in this repo detects "you defined half of a pair and
never the other half."

This module is that detector, and it is deliberately narrow: it flags candidates for a HUMAN to
review, never a verdict of its own. Per the Evidence Truth Rule and this task's own explicit
instruction, a detected gap is reported `POTENTIAL_SPEC_GAP` and is NEVER auto-promoted to an
approved requirement, a PASS/FAIL verdict, or anything a downstream stage could mistake for one --
`SpecGapFinding.status` is structurally pinned to that one string by its own `__post_init__`, and
this module offers no function that could construct a finding with any other status.

**Duck-typed input, no import of any other module in this batch (or of `dv_harness.models`,
so this module stays completely decoupled from whichever concurrently-running file eventually
owns the canonical requirement-set shape).** A "requirement" is any `Mapping` carrying a free-text
description under one of `text`/`description`/`expected_behavior`/`condition`/`behavior`/
`spec_text`/`requirement_text`, optionally an id under `id`/`req_id`/`requirement_id`/`name`, and
optionally an explicit correlation key under `subject`/`signal`/`feature`/`operation`/
`condition_name` (preferred when present, since a human-declared subject is a stronger signal than
anything this module could derive from prose). A requirement with no usable text contributes
nothing and is recorded as skipped, never guessed at.

**Classification is a lexical keyword scan over each requirement's own text -- a heuristic, stated
as one, never a certainty.** Nine fixed-vocabulary flags (normal-condition, error-condition,
enable, disable, interrupt-assert, interrupt-clear, reset, in-flight-operation-behavior,
error-recovery) are each derived from a small, explicit phrase list matched with word-boundary
regex for single tokens (so "incomplete" is never mistaken for "complete", and "unable" never for
"enable") and substring matching for multi-word phrases. Every flag that fires carries the EXACT
matched phrase(s) as its evidence, so a finding is always inspectable against the real text it was
raised from, never a bare assertion.

**Pairing runs on a "same subject" test, not merely "does the counterpart word appear anywhere in
the requirement set".** A requirement's subject is either its own declared `subject`/`signal`/
`feature`/`operation`/`condition_name` field, tokenized, or -- absent one -- the significant
(non-stopword, non-classification-keyword) tokens of its own text. Two requirements are judged to
concern the same subject when their significant-token sets meet a Jaccard-overlap bar
(`SUBJECT_MATCH_THRESHOLD`), deliberately conservative so two unrelated requirements sharing only
common spec-prose vocabulary are not manufactured into a false pairing. A requirement that already
states BOTH halves of a pair in its own text (e.g. "a soft reset while a transfer is already in
progress shall abort it and reinitialize registers") is self-satisfying and raises no finding --
this module never demands that a well-written single requirement be artificially split in two to
avoid a false gap.

**Deliberately bounded, and stated rather than implied closed.** (1) This is NOT a spec parser: it
takes an ALREADY-EXTRACTED requirement set as input and never reads a raw specification document,
RTL, or a register map itself. (2) It cannot prove a gap is real -- a requirement set genuinely
covering a case in prose this module's keyword lists do not recognize will not be flagged, and a
requirement set using unrelated vocabulary that happens to overlap two keyword lists can produce a
spurious pairing; every finding is `POTENTIAL_SPEC_GAP` for exactly this reason, never `MISSING` or
any word that would read as a proven absence. (3) It decides, approves, and arbitrates nothing: no
build, job, or approval is touched, there is deliberately no stage gate, and it authors no fix --
closing a real gap is a human authoring a new requirement, never this module writing one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

# --- Finding-level status: pinned to one value, never a verdict vocabulary -----------------

POTENTIAL_SPEC_GAP = "POTENTIAL_SPEC_GAP"

# --- Report-level status vocabulary (deliberately distinct from any stage-gate verdict) ------

NOT_AVAILABLE = "NOT_AVAILABLE"
GAPS_DETECTED = "GAPS_DETECTED"
NO_GAPS_DETECTED = "NO_GAPS_DETECTED"
_REPORT_STATUSES = frozenset({NOT_AVAILABLE, GAPS_DETECTED, NO_GAPS_DETECTED})

# --- The five gap types this module detects, and nothing else -------------------------------

GAP_MISSING_ERROR_CONDITION = "MISSING_ERROR_CONDITION"
GAP_MISSING_DISABLE = "MISSING_DISABLE"
GAP_MISSING_INTERRUPT_CLEAR = "MISSING_INTERRUPT_CLEAR"
GAP_MISSING_INFLIGHT_RESET_BEHAVIOR = "MISSING_INFLIGHT_RESET_BEHAVIOR"
GAP_MISSING_ERROR_RECOVERY = "MISSING_ERROR_RECOVERY"
_GAP_TYPES = frozenset({
    GAP_MISSING_ERROR_CONDITION,
    GAP_MISSING_DISABLE,
    GAP_MISSING_INTERRUPT_CLEAR,
    GAP_MISSING_INFLIGHT_RESET_BEHAVIOR,
    GAP_MISSING_ERROR_RECOVERY,
})

# --- Classification flags (also doubles as the "missing counterpart" label in a finding) -----

FLAG_NORMAL = "NORMAL_CONDITION"
FLAG_ERROR = "ERROR_CONDITION"
FLAG_ENABLE = "ENABLE"
FLAG_DISABLE = "DISABLE"
FLAG_INTERRUPT_ASSERT = "INTERRUPT_ASSERT"
FLAG_INTERRUPT_CLEAR = "INTERRUPT_CLEAR"
FLAG_RESET = "RESET"
FLAG_INFLIGHT = "INFLIGHT_OPERATION_BEHAVIOR"
FLAG_RECOVERY = "ERROR_RECOVERY"

# (gap_type, "defines this flag", "must also define this flag for the same subject")
GAP_SPECS: Tuple[Tuple[str, str, str], ...] = (
    (GAP_MISSING_ERROR_CONDITION, FLAG_NORMAL, FLAG_ERROR),
    (GAP_MISSING_DISABLE, FLAG_ENABLE, FLAG_DISABLE),
    (GAP_MISSING_INTERRUPT_CLEAR, FLAG_INTERRUPT_ASSERT, FLAG_INTERRUPT_CLEAR),
    (GAP_MISSING_INFLIGHT_RESET_BEHAVIOR, FLAG_RESET, FLAG_INFLIGHT),
    (GAP_MISSING_ERROR_RECOVERY, FLAG_ERROR, FLAG_RECOVERY),
)

# --- Keyword phrase lists: the ONLY evidence a flag is ever raised from -----------------------
# Single-token phrases are matched with \b word boundaries (so "complete" never matches inside
# "incomplete", and "enable" never inside "enabled" -- each inflection is its own listed phrase).
# Multi-word phrases (containing a space or hyphen) are matched by substring, which is safe for
# phrases this specific.

NORMAL_CONDITION_KEYWORDS: Tuple[str, ...] = (
    "success", "successful", "successfully", "complete", "completes", "completed",
    "completion", "nominal", "valid response", "on success", "normal operation",
)

ERROR_KEYWORDS: Tuple[str, ...] = (
    "error", "errors", "erroneous", "fail", "fails", "failed", "failure", "failures",
    "fault", "faulty", "invalid", "incomplete", "timeout", "timeouts", "abort", "aborts",
    "aborted", "corrupt", "corrupted", "corruption",
)

ENABLE_KEYWORDS: Tuple[str, ...] = (
    "enable", "enabled", "enables", "enabling", "turn on", "activate", "activated", "activation",
)

DISABLE_KEYWORDS: Tuple[str, ...] = (
    "disable", "disabled", "disables", "disabling", "turn off", "deactivate", "deactivated",
    "deactivation",
)

INTERRUPT_KEYWORDS: Tuple[str, ...] = ("interrupt", "interrupts", "irq", "isr")

ASSERT_VERBS: Tuple[str, ...] = (
    "assert", "asserted", "asserts", "asserting", "raise", "raised", "raises", "raising",
    "trigger", "triggered", "triggers", "triggering", "generate", "generated", "generates",
    "fire", "fired", "fires",
)

CLEAR_VERBS: Tuple[str, ...] = (
    "clear", "cleared", "clears", "clearing", "deassert", "deasserted", "deasserts",
    "acknowledge", "acknowledged", "acknowledges", "acknowledgment", "acknowledgement",
    "service the interrupt", "servicing the interrupt",
)

RESET_KEYWORDS: Tuple[str, ...] = ("reset", "resets", "resetting")

INFLIGHT_KEYWORDS: Tuple[str, ...] = (
    "in-flight", "in flight", "inflight", "ongoing", "in progress", "outstanding",
    "mid-transfer", "mid transfer", "midtransfer", "already in progress",
    "currently executing", "active transaction", "active transfer", "partially completed",
)

RECOVERY_KEYWORDS: Tuple[str, ...] = (
    "recover", "recovers", "recovered", "recovery", "retry", "retries", "retried",
    "resume", "resumes", "resumed", "re-arm", "rearm", "reinitialize", "reinitialise",
    "reinitialized", "error handling",
)

_ALL_KEYWORD_LISTS: Tuple[Tuple[str, ...], ...] = (
    NORMAL_CONDITION_KEYWORDS, ERROR_KEYWORDS, ENABLE_KEYWORDS, DISABLE_KEYWORDS,
    INTERRUPT_KEYWORDS, ASSERT_VERBS, CLEAR_VERBS, RESET_KEYWORDS, INFLIGHT_KEYWORDS,
    RECOVERY_KEYWORDS,
)

# --- Subject-token stopwords: common spec-prose filler plus every classification keyword -----
# Filtering these out of a requirement's own "subject signature" keeps subject matching about
# the SIGNAL/FEATURE a requirement concerns, not about the vocabulary used to classify it.

_PROSE_STOPWORDS: FrozenSet[str] = frozenset({
    "the", "a", "an", "this", "that", "these", "those", "is", "are", "was", "were", "be", "been",
    "being", "shall", "must", "should", "will", "would", "can", "could", "may", "might",
    "to", "of", "for", "and", "or", "on", "in", "during", "after", "before", "when", "if",
    "while", "then", "system", "device", "dut", "register", "bit", "field", "behavior",
    "behaviour", "defined", "specified", "condition", "conditions", "requirement",
    "requirements", "spec", "specification", "operation", "operations", "not", "no", "with",
    "without", "from", "into", "by", "as", "at", "it", "its", "their", "there", "state",
    "states", "signal", "signals", "value", "values", "case", "cases", "upon", "once", "each",
    "any", "all", "occurs", "occur", "occurring", "present", "provide", "provided", "support",
    "supported", "supports", "set", "shall",
})


def _tokenize(text: str) -> List[str]:
    normalized = text.lower().replace("_", " ").replace("-", " ")
    return re.findall(r"[a-z0-9]+", normalized)


def _keyword_tokens() -> FrozenSet[str]:
    tokens: set = set()
    for phrase_list in _ALL_KEYWORD_LISTS:
        for phrase in phrase_list:
            tokens.update(_tokenize(phrase))
    return frozenset(tokens)


_SUBJECT_STOPWORDS: FrozenSet[str] = _PROSE_STOPWORDS | _keyword_tokens()

SUBJECT_MATCH_THRESHOLD = 0.34


def _phrase_present(text_lower: str, phrase: str) -> bool:
    if " " in phrase or "-" in phrase:
        return phrase in text_lower
    return re.search(rf"\b{re.escape(phrase)}\b", text_lower) is not None


def _phrase_hits(text_lower: str, phrases: Sequence[str]) -> List[str]:
    return [p for p in phrases if _phrase_present(text_lower, p)]


def _jaccard(a: FrozenSet[str], b: FrozenSet[str]) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _same_subject(a: FrozenSet[str], b: FrozenSet[str]) -> bool:
    return _jaccard(a, b) >= SUBJECT_MATCH_THRESHOLD


# --- Duck-typed field access on a caller-supplied requirement dict ---------------------------

_TEXT_FIELD_ALIASES: Tuple[str, ...] = (
    "text", "description", "expected_behavior", "condition", "behavior", "spec_text",
    "requirement_text",
)
_ID_FIELD_ALIASES: Tuple[str, ...] = ("id", "req_id", "requirement_id", "name")
_SUBJECT_FIELD_ALIASES: Tuple[str, ...] = (
    "subject", "signal", "feature", "operation", "condition_name",
)


def _requirement_text(req: Any) -> Optional[str]:
    if not isinstance(req, Mapping):
        return None
    for key in _TEXT_FIELD_ALIASES:
        val = req.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _requirement_id(req: Any, idx: int) -> str:
    if isinstance(req, Mapping):
        for key in _ID_FIELD_ALIASES:
            val = req.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, int):
                return str(val)
    return f"REQ_{idx}"


def _explicit_subject(req: Any) -> Optional[str]:
    if isinstance(req, Mapping):
        for key in _SUBJECT_FIELD_ALIASES:
            val = req.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _subject_tokens(req: Any, text: str) -> FrozenSet[str]:
    explicit = _explicit_subject(req)
    basis = explicit if explicit else text
    tokens = _tokenize(basis)
    return frozenset(t for t in tokens if t not in _SUBJECT_STOPWORDS and len(t) > 1)


# --- Internal classified-requirement record ---------------------------------------------------

@dataclass
class _ClassifiedRequirement:
    req_id: str
    text: str
    subject_tokens: FrozenSet[str]
    subject_display: str
    flags: Dict[str, Tuple[bool, Tuple[str, ...]]]


def _classify(idx: int, req: Any) -> Optional[_ClassifiedRequirement]:
    text = _requirement_text(req)
    if not text:
        return None
    text_lower = text.lower()

    normal_hits = _phrase_hits(text_lower, NORMAL_CONDITION_KEYWORDS)
    error_hits = _phrase_hits(text_lower, ERROR_KEYWORDS)
    enable_hits = _phrase_hits(text_lower, ENABLE_KEYWORDS)
    disable_hits = _phrase_hits(text_lower, DISABLE_KEYWORDS)
    interrupt_hits = _phrase_hits(text_lower, INTERRUPT_KEYWORDS)
    assert_hits = _phrase_hits(text_lower, ASSERT_VERBS)
    clear_hits = _phrase_hits(text_lower, CLEAR_VERBS)
    reset_hits = _phrase_hits(text_lower, RESET_KEYWORDS)
    inflight_hits = _phrase_hits(text_lower, INFLIGHT_KEYWORDS)
    recovery_hits = _phrase_hits(text_lower, RECOVERY_KEYWORDS)

    interrupt_assert_evidence = tuple(interrupt_hits + assert_hits) if (interrupt_hits and assert_hits) else ()
    interrupt_clear_evidence = tuple(interrupt_hits + clear_hits) if (interrupt_hits and clear_hits) else ()

    flags: Dict[str, Tuple[bool, Tuple[str, ...]]] = {
        FLAG_NORMAL: (bool(normal_hits), tuple(normal_hits)),
        FLAG_ERROR: (bool(error_hits), tuple(error_hits)),
        FLAG_ENABLE: (bool(enable_hits), tuple(enable_hits)),
        FLAG_DISABLE: (bool(disable_hits), tuple(disable_hits)),
        FLAG_INTERRUPT_ASSERT: (bool(interrupt_assert_evidence), interrupt_assert_evidence),
        FLAG_INTERRUPT_CLEAR: (bool(interrupt_clear_evidence), interrupt_clear_evidence),
        FLAG_RESET: (bool(reset_hits), tuple(reset_hits)),
        FLAG_INFLIGHT: (bool(inflight_hits), tuple(inflight_hits)),
        FLAG_RECOVERY: (bool(recovery_hits), tuple(recovery_hits)),
    }

    subject_tokens = _subject_tokens(req, text)
    explicit_subj = _explicit_subject(req)
    if explicit_subj:
        subject_display = explicit_subj
    elif subject_tokens:
        subject_display = ", ".join(sorted(subject_tokens))
    else:
        subject_display = "(unspecified)"

    return _ClassifiedRequirement(
        req_id=_requirement_id(req, idx),
        text=text,
        subject_tokens=subject_tokens,
        subject_display=subject_display,
        flags=flags,
    )


# --- Public result types ----------------------------------------------------------------------

@dataclass(frozen=True)
class SpecGapFinding:
    status: str
    gap_type: str
    requirement_id: str
    requirement_text: str
    matched_keywords: Tuple[str, ...]
    missing_counterpart: str
    subject_display: str
    reason: str

    def __post_init__(self) -> None:
        if self.status != POTENTIAL_SPEC_GAP:
            raise ValueError(
                f"SpecGapFinding.status must be {POTENTIAL_SPEC_GAP!r} (a detected gap is a flag "
                f"for human review, never an approved requirement or verdict); got {self.status!r}"
            )
        if self.gap_type not in _GAP_TYPES:
            raise ValueError(f"unrecognized gap_type: {self.gap_type!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "gap_type": self.gap_type,
            "requirement_id": self.requirement_id,
            "requirement_text": self.requirement_text,
            "matched_keywords": list(self.matched_keywords),
            "missing_counterpart": self.missing_counterpart,
            "subject_display": self.subject_display,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SpecGapAnalysisReport:
    status: str
    requirements_analyzed: int
    requirements_skipped_no_text: Tuple[str, ...] = field(default_factory=tuple)
    findings: Tuple[SpecGapFinding, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in _REPORT_STATUSES:
            raise ValueError(f"unrecognized report status: {self.status!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "requirements_analyzed": self.requirements_analyzed,
            "requirements_skipped_no_text": list(self.requirements_skipped_no_text),
            "findings": [f.to_dict() for f in self.findings],
        }


# --- Detection ----------------------------------------------------------------------------------

def detect_spec_gaps(requirements: Optional[Sequence[Any]]) -> SpecGapAnalysisReport:
    """Detect the 5 structural-absence patterns over `requirements` (a generic duck-typed list of
    dicts -- see the module docstring for accepted field names). Every finding is
    `POTENTIAL_SPEC_GAP`: a candidate for a human to review, never an approved requirement.
    """
    if not requirements:
        return SpecGapAnalysisReport(
            status=NOT_AVAILABLE, requirements_analyzed=0, requirements_skipped_no_text=()
        )

    classified: List[_ClassifiedRequirement] = []
    skipped: List[str] = []
    for idx, req in enumerate(requirements):
        c = _classify(idx, req)
        if c is None:
            skipped.append(_requirement_id(req, idx))
        else:
            classified.append(c)

    if not classified:
        return SpecGapAnalysisReport(
            status=NOT_AVAILABLE,
            requirements_analyzed=0,
            requirements_skipped_no_text=tuple(skipped),
        )

    findings: List[SpecGapFinding] = []
    for gap_type, flag_a, flag_b in GAP_SPECS:
        for r in classified:
            has_a, evidence_a = r.flags[flag_a]
            if not has_a:
                continue
            has_b_self, _ = r.flags[flag_b]
            if has_b_self:
                continue  # this requirement already states its own counterpart

            satisfied = False
            for other in classified:
                if other is r:
                    continue
                has_b_other, _ = other.flags[flag_b]
                if has_b_other and _same_subject(r.subject_tokens, other.subject_tokens):
                    satisfied = True
                    break
            if satisfied:
                continue

            reason = (
                f"requirement {r.req_id!r} defines {flag_a} (matched: {', '.join(evidence_a)}) "
                f"but no requirement in this set defines {flag_b} for the same subject "
                f"({r.subject_display!r}); flagged for human review only, never auto-approved."
            )
            findings.append(SpecGapFinding(
                status=POTENTIAL_SPEC_GAP,
                gap_type=gap_type,
                requirement_id=r.req_id,
                requirement_text=r.text[:240],
                matched_keywords=evidence_a,
                missing_counterpart=flag_b,
                subject_display=r.subject_display,
                reason=reason,
            ))

    status = GAPS_DETECTED if findings else NO_GAPS_DETECTED
    return SpecGapAnalysisReport(
        status=status,
        requirements_analyzed=len(classified),
        requirements_skipped_no_text=tuple(skipped),
        findings=tuple(findings),
    )


def render_report_text(report: SpecGapAnalysisReport) -> str:
    lines = [
        f"status: {report.status}  requirements_analyzed: {report.requirements_analyzed}"
    ]
    if report.requirements_skipped_no_text:
        lines.append(
            f"  skipped (no usable text): {', '.join(report.requirements_skipped_no_text)}"
        )
    for f in report.findings:
        lines.append(
            f"  [{f.status}] {f.gap_type}: requirement {f.requirement_id!r} -- "
            f"missing {f.missing_counterpart} for subject {f.subject_display!r}"
        )
        lines.append(f"      evidence: {', '.join(f.matched_keywords)}")
        lines.append(f"      text: {f.requirement_text}")
    return "\n".join(lines)


# --- Vocabulary-collision self-check (run at import) -------------------------------------------
# This module's own status/gap-type vocabulary must never collide with a verification-verdict
# token (PASS/FAIL/BLOCKED/...) -- the same discipline several sibling modules apply against
# `dv_harness.models.Status`, checked here against a literal list since this module deliberately
# imports nothing from dv_harness to stay decoupled from concurrently-changing files.

_ALL_MODULE_TOKENS: FrozenSet[str] = frozenset({
    NOT_AVAILABLE, GAPS_DETECTED, NO_GAPS_DETECTED, POTENTIAL_SPEC_GAP,
    GAP_MISSING_ERROR_CONDITION, GAP_MISSING_DISABLE, GAP_MISSING_INTERRUPT_CLEAR,
    GAP_MISSING_INFLIGHT_RESET_BEHAVIOR, GAP_MISSING_ERROR_RECOVERY,
})
_RESERVED_VERDICT_TOKENS: FrozenSet[str] = frozenset({
    "PASS", "FAIL", "BLOCKED", "ACCEPTED_RISK", "WAIT_USER", "RETRY", "NEEDS_USER_INPUT",
})


def assert_no_verification_verdict_vocabulary() -> None:
    collision = _ALL_MODULE_TOKENS & _RESERVED_VERDICT_TOKENS
    if collision:
        raise AssertionError(
            f"potential_spec_gap_detector vocabulary collides with a verification verdict "
            f"token: {sorted(collision)}"
        )


assert_no_verification_verdict_vocabulary()


# --- Minimal ad hoc front door ------------------------------------------------------------------
# No dv-harness CLI verb: cli.py must not be touched by this task. `python -m
# dv_harness.potential_spec_gap_detector <requirements.json> [--json]` is the only entry point,
# following the "python -m only" convention several recent gap-closure additions use.

def execute_verb(argv: Optional[Sequence[str]] = None) -> Tuple[int, Optional[SpecGapAnalysisReport], str]:
    import json
    import sys as _sys

    args = list(_sys.argv[1:] if argv is None else argv)
    if not args:
        return (
            2,
            None,
            "usage: potential_spec_gap_detector <requirements.json> [--json]\n"
            "  requirements.json: a JSON list of requirement objects, or {\"requirements\": [...]}",
        )

    path = args[0]
    as_json = "--json" in args[1:]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return 2, None, f"could not read requirements file {path!r}: {exc}"

    if isinstance(data, Mapping) and "requirements" in data:
        requirements = data["requirements"]
    else:
        requirements = data
    if not isinstance(requirements, list):
        return (
            2,
            None,
            "requirements file must contain a JSON list of requirement objects "
            "(or {\"requirements\": [...]})",
        )

    report = detect_spec_gaps(requirements)
    text = json.dumps(report.to_dict(), indent=2) if as_json else render_report_text(report)

    if report.status == NOT_AVAILABLE:
        code = 2
    elif report.status == GAPS_DETECTED:
        code = 1
    else:
        code = 0
    return code, report, text


def main(argv: Optional[Sequence[str]] = None) -> int:
    code, _report, text = execute_verb(argv)
    print(text)
    return code


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(main(_sys.argv[1:]))
