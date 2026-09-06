"""dv_harness/command_error_taxonomy.py -- per-command-dispatch error classifier.

WHAT THIS ANSWERS: given the real failure text produced by ONE command/task
dispatch (an exception message, a sim.log excerpt around the failing task,
whatever text a caller already has -- this module reads no file and runs no
subprocess itself), classify it into exactly one of eleven granular
categories with the matched evidence cited, or report ``UNCLASSIFIED`` when
nothing matches. Per the Evidence Truth Rule, an unmatchable message is never
forced into one of the eleven named categories -- ``UNCLASSIFIED`` is the
honest answer, not a missing feature.

TASK LAYER VOCABULARY IS READ, NOT INVENTED. ``.claude/skills/CORE/
pattern-architecture/SKILL.md`` and ``.claude/skills/CORE/branch-mapper/
SKILL.md`` already establish the real ``block`` / ``branch_a0,branch_a1,...``
/ ``branch_fw`` / ``branch_b0,branch_b1,...`` task-composition vocabulary this
module operationalizes:
  * ``branch_fw`` is the per-port FW/event-service loop (pattern-architecture
    section 1) -- a dispatch stuck inside it is ``FW_TIMEOUT``.
  * ``branch_b*`` is the per-port VIP-driven test body -- a dispatch stuck
    inside it (or naming a Synopsys ``svt_``-prefixed VIP component, the same
    prefix convention ``loop_budget.FailureType.VIP`` already documents as
    this repo's real VIP-vendor marker) is ``VIP_TIMEOUT``.
  * ``branch_a*`` is the per-port DUT+PHY init task -- a dispatch stuck inside
    it (or naming the DUT/PHY generically, when no branch label is present)
    is ``DUT_TIMEOUT``.
  * ``BRANCH_OWNERSHIP_ERROR`` is pattern-architecture section 3.1's own named
    trap class -- "two independent task groups can hold conflicting locks on
    a shared bus sequencer" -- made checkable from dispatch-failure text: two
    distinct task-layer families (any two of branch_a*/branch_fw/branch_b*)
    named together with a lock/ownership/arbitration keyword.
This module invents no interrupt-priority scheme, no arbitration policy and
no timing value -- it only recognizes when dispatch-failure TEXT already
names these real, pre-established architecture terms.

REUSE OVER REINVENT. ``CHECK_FAILURE`` and part of ``TASK_ERROR`` are decided
by calling `sim_log_analysis.parse_sim_log()` / `classify_signatures()` --
the existing, real triage engine, whose own docstring invites exactly this
("a caller that classifies something OTHER than a log line can route its own
findings into this triage vocabulary instead of inventing a second one").
This module never re-derives a scoreboard/assertion/UVM_FATAL keyword list of
its own; it asks the one that already exists.

A DIFFERENT, MORE GRANULAR VOCABULARY THAN loop_budget.FailureType --
DELIBERATELY NOT MERGED. `loop_budget.FailureType` answers "why did this
STAGE'S RETRY exhaust" (ten classes, feeding a retry-vs-stop decision across
many dispatches at the stage-retry grain). This module answers a finer-grained,
different question: why did THIS ONE command/task dispatch fail, at the grain
a single command.txt task call fails at. Neither module imports the other,
and `assert_disjoint_from_loop_budget_failure_type()` below keeps the two
string vocabularies from silently colliding as this module or that one grows.
Likewise `assert_disjoint_from_verification_verdict_vocabulary()` keeps this
module's eleven categories (plus UNCLASSIFIED) from colliding with
`dv_harness.models.Status` -- a dispatch-error classification is never
confusable with a stage verdict.

WHAT THIS MODULE DOES NOT DO. It classifies; it does not retry, does not stop
a loop, does not spend a budget, does not decide PASS/FAIL for a stage, and
touches no human-approval gate. It is a pure function of the text it is
given -- no file I/O of its own (beyond what `sim_log_analysis` already does
internally when handed raw text) and no subprocess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .sim_log_analysis import classify_signatures, parse_sim_log

#: The eleven named categories, verbatim per the task, plus the honest
#: fallback. Order here is documentation only -- `CLASSIFICATION_ORDER` below
#: is the real, tested priority a message is actually checked in.
CATEGORIES: Tuple[str, ...] = (
    "SYNTAX_ERROR",
    "UNKNOWN_COMMAND",
    "INVALID_ARGUMENT",
    "PRECONDITION_ERROR",
    "BRANCH_OWNERSHIP_ERROR",
    "TASK_ERROR",
    "FW_TIMEOUT",
    "VIP_TIMEOUT",
    "DUT_TIMEOUT",
    "CHECK_FAILURE",
    "ENVIRONMENT_ERROR",
)

#: Reported when no rule below matches. Never one of `CATEGORIES` -- a
#: classifier that could return this AS a named category would make "we could
#: not tell" indistinguishable from a real finding.
UNCLASSIFIED = "UNCLASSIFIED"

#: The real priority order a message is checked in, most structurally
#: specific first. Exported (not just followed in code) so a test -- or a
#: caller deciding whether a category it did not get was even reachable --
#: can hold this list against `CATEGORIES` rather than trust prose.
#:
#: Rationale for the ordering, briefest form (full reasoning in each rule's
#: own docstring below): an ownership conflict and a missing command are the
#: most decisive facts a dispatch-failure text can carry, so they are checked
#: first; a command that was never found cannot also have a "syntax error" in
#: its own call, so UNKNOWN_COMMAND precedes SYNTAX_ERROR; PRECONDITION_ERROR
#: is checked before the three TIMEOUT rules because a precondition failure is
#: reported as such (`PRECONDITION_NOT_MET`, the real marker
#: `dv_harness/init_seq.py` already uses) rather than as a generic hang, even
#: though a caller waiting on an unmet precondition can look like one; among
#: the three TIMEOUT rules, FW_TIMEOUT is checked first because `branch_fw` is
#: a single, unambiguous layer name, VIP_TIMEOUT next because its markers
#: (`branch_b*`, `svt_...`, literal `VIP`) are still a specific naming
#: convention, and DUT_TIMEOUT last because its markers (`branch_a*`, generic
#: `DUT`/`PHY`) are the broadest; CHECK_FAILURE and the sim-log-analysis half
#: of TASK_ERROR are checked last because they run the real triage engine over
#: the whole text rather than matching one fixed phrase.
CLASSIFICATION_ORDER: Tuple[str, ...] = (
    "BRANCH_OWNERSHIP_ERROR",
    "UNKNOWN_COMMAND",
    "SYNTAX_ERROR",
    "INVALID_ARGUMENT",
    "PRECONDITION_ERROR",
    "FW_TIMEOUT",
    "VIP_TIMEOUT",
    "DUT_TIMEOUT",
    "CHECK_FAILURE",
    "ENVIRONMENT_ERROR",
    "TASK_ERROR",
)
assert set(CLASSIFICATION_ORDER) == set(CATEGORIES), (
    "CLASSIFICATION_ORDER must name exactly the eleven CATEGORIES, no more "
    "and no fewer -- a category missing from this order could never be "
    "reached, and an extra name here would not be a real category."
)


@dataclass
class DispatchFailureClassification:
    """One dispatch-failure text's classification result.

    `category` is one of `CATEGORIES` or `UNCLASSIFIED` -- never anything
    else. `matched_evidence` is the exact substring of the input text the
    decision was made on (never a paraphrase or a fabricated example), empty
    only for `UNCLASSIFIED`. `matched_line` is the 1-indexed line number
    within the input text the evidence was found on, when the input carries
    more than a single line worth of text to locate it against (None for a
    single-line input, or when no rule matched).
    """
    category: str
    matched_evidence: str
    rule_id: str
    matched_line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "matched_evidence": self.matched_evidence,
            "rule_id": self.rule_id,
            "matched_line": self.matched_line,
        }


def _line_of(text: str, index: int) -> Optional[int]:
    """1-indexed line number containing character offset `index`, or None for
    a negative offset (no match)."""
    if index < 0:
        return None
    return text.count("\n", 0, index) + 1


# ---------------------------------------------------------------------------
# Task-layer vocabulary (pattern-architecture / branch-mapper's real terms,
# read verbatim -- see module docstring). `branch_a*`/`branch_b*` require the
# underscore form the Engineering Discipline Rules' "Architecture-conformance
# audit" already names as canonical; a non-underscore legacy form is out of
# scope for this classifier, matching that rule's own migration posture.
# ---------------------------------------------------------------------------
_BRANCH_A_RE = re.compile(r"\bbranch_a\d*\b")
_BRANCH_FW_RE = re.compile(r"\bbranch_fw\b")
_BRANCH_B_RE = re.compile(r"\bbranch_b\d*\b")
#: Generic VIP/DUT naming, used only as a fallback when no explicit branch
#: label is present. `svt_` is the real Synopsys VIP component prefix
#: `loop_budget.FailureType.VIP`'s own docstring already documents as this
#: repo's declared VIP-vendor marker -- reused, not re-derived.
_VIP_GENERIC_RE = re.compile(r"\bsvt_[A-Za-z0-9_]*\b|\bVIP\b")
_DUT_GENERIC_RE = re.compile(r"\bDUT\b|\bPHY\b")

_TIMEOUT_KEYWORD_RE = re.compile(
    r"\btimeout\b|\btimed\s+out\b|\bdeadlock\b|\bhang(?:ing|s)?\b|"
    r"\bdid\s+not\s+complete\b|\bnever\s+completed\b|\bno\s+response\b",
    re.IGNORECASE,
)
#: pattern-architecture section 3.1's own words for the ownership trap class:
#: "conflicting locks", "arbitration ... interleaves them". Kept close to
#: that section's real prose rather than a generic word list of our own.
_OWNERSHIP_KEYWORD_RE = re.compile(
    r"\b(lock|semaphore|ownership|owns|arbitrat\w*|interleav\w*|conflicting)\b",
    re.IGNORECASE,
)

_UNKNOWN_COMMAND_RE = re.compile(
    r"\bunknown\s+command\b|\bunrecognized\s+command\b|\bno\s+such\s+command\b|"
    r"\bcommand\s+['\"]?[\w./-]+['\"]?\s+not\s+found\b|"
    r"\bnot\s+found\s+in\s+(?:the\s+)?dispatch\s+table\b|"
    r"\bnot\s+registered\s+in\s+(?:the\s+)?(?:command\s+)?dispatch\b",
    re.IGNORECASE,
)
_SYNTAX_ERROR_RE = re.compile(
    r"\bsyntax\s+error\b|\bparse\s+error\b|\bunexpected\s+token\b|Error-\[SV-",
    re.IGNORECASE,
)
_INVALID_ARGUMENT_RE = re.compile(
    r"\binvalid\s+argument\b|\bmissing\s+(?:a\s+)?required\s+argument\b|"
    r"\bwrong\s+number\s+of\s+arguments\b|\bunexpected\s+argument\b|"
    r"\bmissing\s+parameter\b|\bargument\s+[\w.\"'-]+\s+expected\b",
    re.IGNORECASE,
)
#: `PRECONDITION_NOT_MET` is the real marker `dv_harness/init_seq.py` already
#: emits (a mode-bit/precondition-check interpretation), reused rather than
#: re-typed.
_PRECONDITION_ERROR_RE = re.compile(
    r"\bPRECONDITION_NOT_MET\b|\bprecondition\s+(?:not\s+met|failed|violat\w*)\b",
    re.IGNORECASE,
)
_ENVIRONMENT_ERROR_RE = re.compile(
    r"\blicense\b|\bLM_LICENSE\b|\bDESIGNWARE_HOME\b|"
    r"\bqueue\s+(?:closed|unavailable|down)\b|\bcore\s+dump(?:ed)?\b|"
    r"\bsegmentation\s+fault\b|\bout\s+of\s+memory\b|\bconnection\s+refused\b|"
    r"\bno\s+space\s+left\b|\bpermission\s+denied\b|\bcannot\s+connect\b",
    re.IGNORECASE,
)
_TASK_ERROR_RE = re.compile(
    r"\btask\s+\S+\s+(?:failed|aborted|did not complete|returned an? error)\b|"
    r"\bfork/join\b.{0,40}\b(?:fail\w*|error\w*)\b",
    re.IGNORECASE,
)

#: `sim_log_analysis.classify_signatures()`'s own category enum
#: (uvm_fatal/uvm_error/bare_error/assertion/timeout/scoreboard_mismatch/
#: other). Split here into the two buckets this module routes to: a checker
#: actually caught something (CHECK_FAILURE) vs. a generic
#: fatal/error/bare-error signal with no more specific cause (TASK_ERROR).
#: `timeout`/`other` are deliberately not claimed by either -- a bare
#: "timeout" with no task-layer marker cannot be attributed to FW/VIP/DUT and
#: must stay UNCLASSIFIED rather than a forced guess (see module docstring).
_CHECK_FAILURE_SIM_LOG_CATEGORIES = ("scoreboard_mismatch", "assertion")
_TASK_ERROR_SIM_LOG_CATEGORIES = ("uvm_fatal", "uvm_error", "bare_error")


def _branch_family_hits(text: str) -> List[Tuple[str, re.Match]]:
    """Every distinct task-layer family (branch_a/branch_fw/branch_b) with a
    real match in `text`, each carrying its own first match. Order follows
    which family's regex is listed, not position in `text`."""
    hits: List[Tuple[str, re.Match]] = []
    for name, rgx in (
        ("branch_a", _BRANCH_A_RE),
        ("branch_fw", _BRANCH_FW_RE),
        ("branch_b", _BRANCH_B_RE),
    ):
        m = rgx.search(text)
        if m:
            hits.append((name, m))
    return hits


def _rule_branch_ownership(text: str) -> Optional[Tuple[str, Optional[int]]]:
    """pattern-architecture section 3.1: two distinct task-layer families
    named together with a lock/ownership/arbitration keyword. Requires BOTH
    -- two branch families alone (e.g. a clean hand-off mentioned in passing)
    is not evidence of a conflict, and an ownership keyword alone with no
    second layer named is not evidence it was a CROSS-layer conflict."""
    families = _branch_family_hits(text)
    if len(families) < 2:
        return None
    kw = _OWNERSHIP_KEYWORD_RE.search(text)
    if not kw:
        return None
    layer_tokens = ", ".join(m.group(0) for _, m in families)
    evidence = f"{kw.group(0)!r} co-occurring with {layer_tokens}"
    return evidence, _line_of(text, kw.start())


def _rule_layer_timeout(
    text: str, layer_regexes: List[re.Pattern],
) -> Optional[Tuple[str, Optional[int]]]:
    """Shared shape for FW_TIMEOUT/VIP_TIMEOUT/DUT_TIMEOUT: a layer marker AND
    a timeout/deadlock keyword must both be present -- a bare layer mention or
    a bare timeout word alone proves nothing about WHICH layer hung."""
    layer_match = None
    for rgx in layer_regexes:
        layer_match = rgx.search(text)
        if layer_match:
            break
    if not layer_match:
        return None
    kw = _TIMEOUT_KEYWORD_RE.search(text)
    if not kw:
        return None
    evidence = f"{layer_match.group(0)!r} + {kw.group(0)!r}"
    return evidence, _line_of(text, kw.start())


def _rule_regex(text: str, rgx: re.Pattern) -> Optional[Tuple[str, Optional[int]]]:
    m = rgx.search(text)
    if not m:
        return None
    return m.group(0), _line_of(text, m.start())


def classify_dispatch_failure(text: str) -> DispatchFailureClassification:
    """Classify one command/task dispatch's real failure text.

    `text` is whatever failure text the caller already has -- an exception
    message, a sim.log excerpt around the failing task, a dispatch-runner's
    captured stderr. This function performs no file I/O and no subprocess
    call; it is a pure function of `text`.

    Returns a `DispatchFailureClassification` whose `category` is exactly one
    of `CATEGORIES` or `UNCLASSIFIED` -- never a forced guess when no rule's
    evidence is present.
    """
    if text is None:
        raise ValueError("command_error_taxonomy.classify_dispatch_failure: text must not be None")
    if not text.strip():
        return DispatchFailureClassification(UNCLASSIFIED, "", "empty_text", None)

    r = _rule_branch_ownership(text)
    if r:
        evidence, line = r
        return DispatchFailureClassification("BRANCH_OWNERSHIP_ERROR", evidence, "branch_ownership_conflicting_lock", line)

    r = _rule_regex(text, _UNKNOWN_COMMAND_RE)
    if r:
        evidence, line = r
        return DispatchFailureClassification("UNKNOWN_COMMAND", evidence, "unknown_command_marker", line)

    r = _rule_regex(text, _SYNTAX_ERROR_RE)
    if r:
        evidence, line = r
        return DispatchFailureClassification("SYNTAX_ERROR", evidence, "syntax_error_marker", line)

    r = _rule_regex(text, _INVALID_ARGUMENT_RE)
    if r:
        evidence, line = r
        return DispatchFailureClassification("INVALID_ARGUMENT", evidence, "invalid_argument_marker", line)

    r = _rule_regex(text, _PRECONDITION_ERROR_RE)
    if r:
        evidence, line = r
        return DispatchFailureClassification("PRECONDITION_ERROR", evidence, "precondition_not_met_marker", line)

    r = _rule_layer_timeout(text, [_BRANCH_FW_RE])
    if r:
        evidence, line = r
        return DispatchFailureClassification("FW_TIMEOUT", evidence, "branch_fw_timeout", line)

    r = _rule_layer_timeout(text, [_BRANCH_B_RE, _VIP_GENERIC_RE])
    if r:
        evidence, line = r
        return DispatchFailureClassification("VIP_TIMEOUT", evidence, "branch_b_or_vip_timeout", line)

    r = _rule_layer_timeout(text, [_BRANCH_A_RE, _DUT_GENERIC_RE])
    if r:
        evidence, line = r
        return DispatchFailureClassification("DUT_TIMEOUT", evidence, "branch_a_or_dut_timeout", line)

    parsed = parse_sim_log(text)
    classified = classify_signatures(parsed["signatures"])

    check_hit = next((e for e in classified if e["category"] in _CHECK_FAILURE_SIM_LOG_CATEGORIES), None)
    if check_hit is not None:
        return DispatchFailureClassification(
            "CHECK_FAILURE", check_hit["example_line"],
            f"sim_log_analysis:{check_hit['category']}", check_hit["first_line_no"],
        )

    r = _rule_regex(text, _ENVIRONMENT_ERROR_RE)
    if r:
        evidence, line = r
        return DispatchFailureClassification("ENVIRONMENT_ERROR", evidence, "environment_error_marker", line)

    r = _rule_regex(text, _TASK_ERROR_RE)
    if r:
        evidence, line = r
        return DispatchFailureClassification("TASK_ERROR", evidence, "task_error_phrase", line)

    task_hit = next((e for e in classified if e["category"] in _TASK_ERROR_SIM_LOG_CATEGORIES), None)
    if task_hit is not None:
        return DispatchFailureClassification(
            "TASK_ERROR", task_hit["example_line"],
            f"sim_log_analysis:{task_hit['category']}", task_hit["first_line_no"],
        )

    return DispatchFailureClassification(UNCLASSIFIED, "", "no_rule_matched", None)


def assert_disjoint_from_verification_verdict_vocabulary() -> None:
    """This module's category vocabulary must share no token with
    `dv_harness.models.Status`, the harness's verification-verdict
    vocabulary -- a dispatch-error classification must never be confusable
    with a stage verdict."""
    from .models import Status

    verdicts = {s.value for s in Status}
    vocabulary = set(CATEGORIES) | {UNCLASSIFIED}
    collision = verdicts.intersection(vocabulary)
    if collision:
        raise AssertionError(
            f"command_error_taxonomy vocabulary collides with dv_harness.models.Status "
            f"on {sorted(collision)} -- a dispatch-error classification must never be "
            "confusable with a verification verdict"
        )


def assert_disjoint_from_loop_budget_failure_type() -> None:
    """This module's vocabulary is DELIBERATELY a different, more granular
    taxonomy from `loop_budget.FailureType` (per-command-dispatch
    classification vs. per-stage-retry classification -- see module
    docstring). Neither module imports the other; this only guards against
    the two string vocabularies silently colliding as either grows."""
    from .loop_budget import FAILURE_TYPE_VALUES

    vocabulary = set(CATEGORIES) | {UNCLASSIFIED}
    collision = set(FAILURE_TYPE_VALUES).intersection(vocabulary)
    if collision:
        raise AssertionError(
            f"command_error_taxonomy vocabulary collides with loop_budget.FailureType "
            f"on {sorted(collision)} -- these are two deliberately separate taxonomies "
            "and must not merge"
        )
