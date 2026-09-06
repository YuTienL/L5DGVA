"""dv_harness/system_failure_taxonomy.py -- SYSTEM-INTEGRATION failure taxonomy,
root-cause BOUNDARY localization, and a system coverage-hole taxonomy.

Three related mechanisms, one module, because all three answer a question at the
SAME grain: not "why did this one command dispatch fail" (`command_error_taxonomy.py`,
eleven per-command categories) and not "why did this stage's RETRY exhaust"
(`loop_budget.FailureType`, ten per-retry categories) -- both of those are per-command
or per-stage-retry classifiers, deliberately narrower and finer-grained than this
module. This module classifies a SYSTEM/multi-subsystem-composition-level failure or
coverage hole: the grain at which a `soc_environment_composer`-composed environment,
or a `system_resource_inventory`/`system_topology_analysis`-analysed multi-subsystem
project, actually breaks. Neither `command_error_taxonomy.py` nor `loop_budget.py` is
imported here (both are claimed by a concurrently-running batch in this project); the
non-collision is instead asserted against a literal, hand-transcribed copy of each
module's own published vocabulary (see `assert_disjoint_from_command_error_taxonomy()`
/ `assert_disjoint_from_loop_budget_failure_type()` below), the same "state the
distinction, do not silently assume it" discipline this project's CLAUDE.md already
applies to every other pair of near-adjacent vocabularies (e.g.
`spec_vplan_readiness_gate.py` reimplementing rather than importing
`subsystem_maturity_gate.py`'s own guard for the identical reason).

EVIDENCE TRUTH RULE, applied throughout. (a) `classify_system_integration_failure()`
is a pure function of a real failure-text/evidence string a caller already has (a
system-build-proof merge report, a cross-subsystem gate's own rejection text, a
composed-environment's sim.log excerpt) -- it reads no file and runs no subprocess
itself, and an unmatched text is reported `UNCLASSIFIED`, never forced into one of
the fourteen named categories. (b) `localize_failure_boundary()` never claims a
SPECIFIC root cause -- only the NARROWEST subsystem boundary the caller's own
per-subsystem input/output correctness facts actually prove, reporting
`UNDETERMINED` (never guessing) whenever the evidence does not narrow to exactly one
subsystem. (c) `classify_system_coverage_hole()` classifies a caller-declared
coverage-hole record into one of six SYSTEM-level gap categories, again reporting an
honest `UNCLASSIFIED_COVERAGE_HOLE` rather than a forced guess when no recognised
basis is present in the input.

REUSE OVER REINVENT, and its stated boundary here. Per this batch's file-safety
scope this module accepts every input as a generic/duck-typed parameter and imports
no file from the concurrently-claimed batch list (which includes both
`command_error_taxonomy.py` and `loop_budget.py`, and also `coverage_analysis.py` --
see the coverage-hole-taxonomy scope note below). It DOES import
`dv_harness.models.Status` (a small, stable, unclaimed enum) purely to prove this
module's own vocabulary shares no token with the verification-verdict vocabulary,
the same disjointness discipline `command_error_taxonomy.py`,
`capability_evolution.py` and several other modules in this project already apply to
themselves.

WHAT THIS MODULE DOES NOT DO. It classifies and localizes; it never decides which
subsystem to fix, never arbitrates a resource-ownership conflict (that stays
`system_resource_inventory.py`'s SYS-11/SYS-12 territory, read-only, and never
imported here since it is not named by this task), never retries anything, never
spends a budget, never decides PASS/FAIL for a stage, and touches no human-approval
gate. It performs no file I/O and no subprocess call anywhere in this module.

Coverage-hole-taxonomy scope note, stated rather than left implicit: this is
DELIBERATELY a different, coarser-grained taxonomy from
`coverage_analysis.classify_coverage_hole()`'s four per-BIN root causes
(MISSING_TEST / INSUFFICIENT_CONSTRAINT / UNREACHABLE_STIMULUS /
INSUFFICIENT_SEED_ATTEMPTS, plus the twelve-value structural extension documented in
this project's own CLAUDE.md) -- that mechanism answers "why is ONE coverage bin
unhit", read off a real coverage-tool summary and a real seed-attempt count. This
module answers "what KIND of system-level gap does a coverage hole represent" (is it
scoped to one subsystem, does it span an integration path, does it concern a shared
resource, an error path, a whole missing scenario category, or a coverage MODEL that
was never even defined) -- a classification of the hole's STRUCTURAL SCOPE, not its
per-bin root cause. The six category names share no token with `coverage_analysis`'s
four, and `coverage_analysis.py` is on this batch's claimed-file list, so it is
never imported here; the two mechanisms compose at a caller (a per-bin root cause
and a system-level gap category are both true facts about the same hole) rather than
one subsuming the other.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# -----------------------------------------------------------------------------
# (a) SYSTEM-INTEGRATION failure taxonomy: 14 real values + UNCLASSIFIED.
# -----------------------------------------------------------------------------

#: The fourteen named categories, verbatim per the task, plus the honest fallback
#: (`UNCLASSIFIED`, defined separately below, exactly as `command_error_taxonomy.py`
#: keeps its own fallback out of its own `CATEGORIES` tuple). Order here is
#: documentation only -- `CLASSIFICATION_ORDER` below is the real, tested priority
#: a text is actually checked in.
FAILURE_CATEGORIES: Tuple[str, ...] = (
    "SUBSYSTEM_FAILURE",
    "INTEGRATION_FAILURE",
    "ROUTING_FAILURE",
    "RESOURCE_CONTENTION_FAILURE",
    "ADDRESS_MAP_FAILURE",
    "CLOCK_RESET_FAILURE",
    "COMMAND_COMPATIBILITY_FAILURE",
    "BUILD_COMPOSITION_FAILURE",
    "SCOREBOARD_COMPOSITION_FAILURE",
    "VIP_DEDUP_FAILURE",
    "ERROR_PROPAGATION_FAILURE",
    "TIMING_FAILURE",
    "CONFIGURATION_FAILURE",
    "RECOVERY_FAILURE",
)

#: Reported when no rule below matches. Never one of `FAILURE_CATEGORIES` -- a
#: classifier that could return this AS a named category would make "we could not
#: tell" indistinguishable from a real finding.
UNCLASSIFIED = "UNCLASSIFIED"

#: The real priority order a failure text is checked in, most structurally specific
#: first, mirroring `command_error_taxonomy.py`'s own documented ordering
#: discipline (kept as a hand-mutated literal here rather than imported, per this
#: module's own no-import-from-the-claimed-batch rule). Rationale, briefest form
#: (full reasoning lives beside each regex below): ADDRESS_MAP_FAILURE and
#: CLOCK_RESET_FAILURE are checked first because their evidence markers are the
#: most structurally specific (a named address region, a named clock/reset signal);
#: VIP_DEDUP_FAILURE and ROUTING_FAILURE next because "two active drivers on one
#: port" and "delivered to the wrong port" are both narrow, checkable claims;
#: RESOURCE_CONTENTION_FAILURE follows because arbitration/deadlock/livelock
#: language is a broader shared-resource claim that could otherwise absorb the two
#: more specific rules above it; COMMAND_COMPATIBILITY_FAILURE,
#: BUILD_COMPOSITION_FAILURE and SCOREBOARD_COMPOSITION_FAILURE are the three
#: system-BUILD/merge-shaped categories, checked together and in that order because
#: a command-name collision is checkable before a broader merge-collision claim,
#: which is checkable before an even broader composed-scoreboard claim;
#: ERROR_PROPAGATION_FAILURE and TIMING_FAILURE are specific claims about a single
#: reported defect and are checked next; CONFIGURATION_FAILURE and
#: RECOVERY_FAILURE follow as broader system-level claims; INTEGRATION_FAILURE is
#: the generic cross-subsystem catch-all, checked after every more specific
#: integration-shaped rule so it never pre-empts one of them; SUBSYSTEM_FAILURE is
#: checked last because its own marker (the word "subsystem") is the least
#: distinguishing token in the whole vocabulary, and it additionally requires an
#: explicit isolation marker ("standalone", "in isolation", "internal(ly)") so a
#: cross-subsystem failure that happens to mention one subsystem's name is never
#: misread as an isolated one.
CLASSIFICATION_ORDER: Tuple[str, ...] = (
    "ADDRESS_MAP_FAILURE",
    "CLOCK_RESET_FAILURE",
    "VIP_DEDUP_FAILURE",
    "ROUTING_FAILURE",
    "RESOURCE_CONTENTION_FAILURE",
    "COMMAND_COMPATIBILITY_FAILURE",
    "BUILD_COMPOSITION_FAILURE",
    "SCOREBOARD_COMPOSITION_FAILURE",
    "ERROR_PROPAGATION_FAILURE",
    "TIMING_FAILURE",
    "CONFIGURATION_FAILURE",
    "RECOVERY_FAILURE",
    "INTEGRATION_FAILURE",
    "SUBSYSTEM_FAILURE",
)
assert set(CLASSIFICATION_ORDER) == set(FAILURE_CATEGORIES), (
    "CLASSIFICATION_ORDER must name exactly the fourteen FAILURE_CATEGORIES, no "
    "more and no fewer -- a category missing from this order could never be "
    "reached, and an extra name here would not be a real category."
)


@dataclass
class SystemIntegrationFailureClassification:
    """One system-integration failure text's classification result.

    `category` is one of `FAILURE_CATEGORIES` or `UNCLASSIFIED` -- never anything
    else. `matched_evidence` is the exact substring of the input text the decision
    was made on (never a paraphrase or a fabricated example), empty only for
    `UNCLASSIFIED`. `matched_line` is the 1-indexed line number within the input
    text the evidence was found on, when the input carries more than a single line
    (None for a single-line input, or when no rule matched).
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
    """1-indexed line number containing character offset `index`, or None for a
    negative offset (no match)."""
    if index < 0:
        return None
    return text.count("\n", 0, index) + 1


# ---------------------------------------------------------------------------
# Rule regexes. Every one matches only real, explicit language a caller's own
# evidence text would carry -- never a bare protocol/subsystem name alone, and
# never a guess at silicon behaviour. TIMING_FAILURE in particular classifies
# already-REPORTED timing/race-relationship violation TEXT (a setup/hold
# violation citation, a race condition, a glitch) -- it measures nothing and
# runs no timing analysis of its own; Performance Verification (throughput/
# latency/bandwidth measurement) is out of scope for this entire batch and
# nothing here approaches it.
# ---------------------------------------------------------------------------
_ADDRESS_MAP_RE = re.compile(
    r"\baddress\s+map\b.{0,60}\b(disagree\w*|overlap\w*|conflict\w*|mismatch\w*|"
    r"decode\s+error)\b|\boverlapping\s+address\s+region\b|"
    r"\bbase\s+address\b.{0,40}\bdisagrees?\b|"
    r"\baddress\s+decode\s+(error|failure)\b",
    re.IGNORECASE,
)
_CLOCK_RESET_RE = re.compile(
    r"\bclock\s+domain\s+cross(?:ing)?\b|\bCDC\s+(violation|failure)\b|"
    r"\breset\s+domain\b.{0,40}\b(mismatch|conflict)\b|"
    r"\basync(?:hronous)?\s+reset\b.{0,40}\b(fail\w*|violat\w*)\b|"
    r"\bclock\s+not\s+toggling\b|\breset\s+never\s+released\b|"
    r"\breset\s+polarity\s+mismatch\b",
    re.IGNORECASE,
)
_VIP_DEDUP_RE = re.compile(
    r"\btwo\s+active\s+(vip|drivers?|agents?)\b.{0,40}\b(same|one)\s+"
    r"(port|interface)\b|\bduplicate\s+(active\s+)?vip\s+(instance|driver|agent)\b|"
    r"\bactive[_\s]driver[_\s]conflict\b|"
    r"\bboth\s+.{0,20}drive\b.{0,20}(port|interface)\b",
    re.IGNORECASE,
)
_ROUTING_RE = re.compile(
    r"\bmisrouted\b|\brouted\s+to\s+(the\s+)?wrong\b|"
    r"\bwrong\s+destination\s+port\b|\brouting\s+(error|failure|mismatch)\b|"
    r"\btransaction\s+(arrived|delivered)\s+at\s+(the\s+)?wrong\b",
    re.IGNORECASE,
)
_RESOURCE_CONTENTION_RE = re.compile(
    r"\barbitration\s+(failure|error|conflict)\b|\bdeadlock\b|\blivelock\b|"
    r"\bresource\s+contention\b|\bstarvation\b|"
    r"\bshared\s+resource\b.{0,40}\bconflict\b",
    re.IGNORECASE,
)
_COMMAND_COMPAT_RE = re.compile(
    r"\bcommand\s+name\s+collision\b|"
    r"\bincompatible\s+command\b.{0,40}\b(merge|composition|dispatch)\b|"
    r"\btwo\s+subsystems?\b.{0,60}\bsame\s+command\s+name\b|"
    r"\bcommand\.txt\b.{0,40}\b(incompatib\w*|conflict\w*)\b",
    re.IGNORECASE,
)
_BUILD_COMPOSITION_RE = re.compile(
    r"\bduplicate\s+(package|module)\s+declaration\b|\bmerge\s+collision\b|"
    r"\bsystem\s+merge\b.{0,40}\b(fail\w*|collision)\b|"
    r"\bfactory\s+type\s+name\s+collision\b|"
    r"\bconfig_db\s+set\s+scope\s+collision\b|"
    r"\bvirtual\s+interface\s+conflict\b",
    re.IGNORECASE,
)
_SCOREBOARD_COMPOSITION_RE = re.compile(
    r"\b(composed|system[- ]level|end[- ]to[- ]end)\s+scoreboard\b.{0,60}\b"
    r"(mismatch\w*|fail\w*)\b|"
    r"\bcross[- ]subsystem\s+scoreboard\b.{0,40}\bmismatch\w*\b",
    re.IGNORECASE,
)
_ERROR_PROPAGATION_RE = re.compile(
    r"\berror\s+(was\s+)?(not\s+propagated|swallowed|masked|suppressed)\b|"
    r"\bfault\s+not\s+escalated\b|\bexception\s+lost\s+across\b|"
    r"\berror\s+never\s+reached\b",
    re.IGNORECASE,
)
_TIMING_RE = re.compile(
    r"\bsetup\s+violation\b|\bhold\s+violation\b|\brace\s+condition\b|\bglitch\b|"
    r"\bunexpected\s+skew\b|\btiming\s+(relationship\s+)?violation\b",
    re.IGNORECASE,
)
_CONFIGURATION_RE = re.compile(
    r"\bconfiguration\s+mismatch\b.{0,40}\b(subsystem|cross)\b|"
    r"\bincompatible\s+configuration\b|\bfeature\s+mode\s+(mismatch|conflict)\b|"
    r"\billegal\s+configuration\s+combination\b",
    re.IGNORECASE,
)
_RECOVERY_RE = re.compile(
    r"\bfailed\s+to\s+recover\b|\brecovery\s+(path\s+)?(failed|did\s+not\s+"
    r"complete)\b|\bsystem\s+did\s+not\s+recover\b|"
    r"\bnever\s+returned\s+to\s+(a\s+)?known[- ]good\s+state\b",
    re.IGNORECASE,
)
_INTEGRATION_GENERIC_RE = re.compile(
    r"\bintegration\s+(test\s+)?(failure|failed|error)\b|"
    r"\bcross[- ]subsystem\b.{0,40}\b(fail\w*|mismatch|inconsisten\w*)\b|"
    r"\bsubsystems?\s+disagree\b",
    re.IGNORECASE,
)
_SUBSYSTEM_GENERIC_RE = re.compile(
    r"\bsubsystem\s+\S+\s+(failed|failure)\b.{0,60}\b(isolat\w*|standalone|"
    r"internal(?:ly)?|on\s+its\s+own)\b|"
    r"\binternal\s+failure\s+within\s+(the\s+)?subsystem\b",
    re.IGNORECASE,
)

_RULE_TABLE: Dict[str, Tuple[re.Pattern, str]] = {
    "ADDRESS_MAP_FAILURE": (_ADDRESS_MAP_RE, "address_map_disagreement_marker"),
    "CLOCK_RESET_FAILURE": (_CLOCK_RESET_RE, "clock_reset_domain_marker"),
    "VIP_DEDUP_FAILURE": (_VIP_DEDUP_RE, "duplicate_active_vip_marker"),
    "ROUTING_FAILURE": (_ROUTING_RE, "misrouted_transaction_marker"),
    "RESOURCE_CONTENTION_FAILURE": (_RESOURCE_CONTENTION_RE, "arbitration_contention_marker"),
    "COMMAND_COMPATIBILITY_FAILURE": (_COMMAND_COMPAT_RE, "command_name_collision_marker"),
    "BUILD_COMPOSITION_FAILURE": (_BUILD_COMPOSITION_RE, "system_merge_collision_marker"),
    "SCOREBOARD_COMPOSITION_FAILURE": (_SCOREBOARD_COMPOSITION_RE, "composed_scoreboard_mismatch_marker"),
    "ERROR_PROPAGATION_FAILURE": (_ERROR_PROPAGATION_RE, "error_not_propagated_marker"),
    "TIMING_FAILURE": (_TIMING_RE, "reported_timing_violation_marker"),
    "CONFIGURATION_FAILURE": (_CONFIGURATION_RE, "cross_subsystem_configuration_mismatch_marker"),
    "RECOVERY_FAILURE": (_RECOVERY_RE, "system_recovery_failed_marker"),
    "INTEGRATION_FAILURE": (_INTEGRATION_GENERIC_RE, "generic_cross_subsystem_integration_marker"),
    "SUBSYSTEM_FAILURE": (_SUBSYSTEM_GENERIC_RE, "isolated_subsystem_failure_marker"),
}
assert set(_RULE_TABLE) == set(FAILURE_CATEGORIES), (
    "_RULE_TABLE must carry exactly one regex per FAILURE_CATEGORIES entry"
)


def classify_system_integration_failure(text: str) -> SystemIntegrationFailureClassification:
    """Classify one real system-integration failure text.

    `text` is whatever failure text the caller already has -- a system-build-proof
    merge report line, a cross-subsystem gate's own rejection text, a composed
    environment's sim.log excerpt. This function performs no file I/O and no
    subprocess call; it is a pure function of `text`.

    Returns a classification whose `category` is exactly one of
    `FAILURE_CATEGORIES` or `UNCLASSIFIED` -- never a forced guess when no rule's
    evidence is present.
    """
    if text is None:
        raise ValueError(
            "system_failure_taxonomy.classify_system_integration_failure: text must not be None"
        )
    if not isinstance(text, str):
        raise ValueError(
            "system_failure_taxonomy.classify_system_integration_failure: text must be a str, "
            f"got {type(text)}"
        )
    if not text.strip():
        return SystemIntegrationFailureClassification(UNCLASSIFIED, "", "empty_text", None)

    for category in CLASSIFICATION_ORDER:
        rgx, rule_id = _RULE_TABLE[category]
        m = rgx.search(text)
        if m:
            return SystemIntegrationFailureClassification(
                category, m.group(0), rule_id, _line_of(text, m.start())
            )

    return SystemIntegrationFailureClassification(UNCLASSIFIED, "", "no_rule_matched", None)


# ---------------------------------------------------------------------------
# Cross-vocabulary disjointness guards. Neither `command_error_taxonomy.py` nor
# `loop_budget.py` is imported here -- both are claimed by a concurrently-running
# batch -- so each guard checks this module's vocabulary against a literal,
# hand-transcribed copy of the other module's own published values (verified
# against that module's source at the time this file was written). A future drift
# in either source module would not be caught automatically by these two guards;
# what they DO catch is this module ever choosing a name that collides with either
# vocabulary AS IT STOOD when this module was built.
# ---------------------------------------------------------------------------

#: `command_error_taxonomy.CATEGORIES` (11 real, named values), transcribed
#: literally -- never imported, per this module's own no-import-from-the-claimed-
#: batch rule. Deliberately excludes that module's own `UNCLASSIFIED` fallback:
#: both modules share the identical word for the same honest "no rule matched"
#: convention (mirroring how `NOT_AVAILABLE`/`UNKNOWN` are shared honest-status
#: conventions elsewhere in this project rather than a vocabulary collision), so
#: comparing named categories against named categories is the real check.
_COMMAND_ERROR_TAXONOMY_VOCABULARY: Tuple[str, ...] = (
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

#: `loop_budget.FAILURE_TYPE_VALUES` (10 values), transcribed literally -- never
#: imported, per this module's own no-import-from-the-claimed-batch rule.
_LOOP_BUDGET_FAILURE_TYPE_VOCABULARY: Tuple[str, ...] = (
    "TRANSIENT",
    "DETERMINISTIC",
    "RESOURCE",
    "LICENSE",
    "ENVIRONMENT",
    "TEST",
    "DUT",
    "VIP",
    "INFRASTRUCTURE",
    "UNKNOWN",
)


def assert_disjoint_from_command_error_taxonomy() -> None:
    """This module's SYSTEM-INTEGRATION vocabulary must share no token with
    `command_error_taxonomy.py`'s per-command-dispatch vocabulary -- deliberately
    different, coarser scope (see module docstring). Checked against a literal
    transcription rather than an import, since that module is claimed by a
    concurrently-running batch. The shared `UNCLASSIFIED` fallback word is
    deliberately excluded from this check -- see
    `_COMMAND_ERROR_TAXONOMY_VOCABULARY`'s own docstring."""
    collision = set(FAILURE_CATEGORIES).intersection(_COMMAND_ERROR_TAXONOMY_VOCABULARY)
    if collision:
        raise AssertionError(
            f"system_failure_taxonomy vocabulary collides with command_error_taxonomy's "
            f"per-command-dispatch vocabulary on {sorted(collision)} -- these are two "
            "deliberately separate, different-grain taxonomies and must not merge"
        )


def assert_disjoint_from_loop_budget_failure_type() -> None:
    """This module's SYSTEM-INTEGRATION vocabulary must share no token with
    `loop_budget.FailureType`'s per-retry vocabulary -- deliberately different,
    coarser scope (see module docstring). Checked against a literal transcription
    rather than an import, since that module is claimed by a concurrently-running
    batch."""
    vocabulary = set(FAILURE_CATEGORIES) | {UNCLASSIFIED}
    collision = vocabulary.intersection(_LOOP_BUDGET_FAILURE_TYPE_VOCABULARY)
    if collision:
        raise AssertionError(
            f"system_failure_taxonomy vocabulary collides with loop_budget.FailureType's "
            f"per-retry vocabulary on {sorted(collision)} -- these are two deliberately "
            "separate, different-grain taxonomies and must not merge"
        )


def assert_disjoint_from_verification_verdict_vocabulary() -> None:
    """This module's vocabulary (failure categories, coverage-hole categories, and
    the boundary-localization status words) must share no token with
    `dv_harness.models.Status`, the harness's verification-verdict vocabulary -- a
    failure/gap classification must never be confusable with a stage verdict.
    `models.py` is not on this batch's claimed-file list, so it is imported
    directly rather than transcribed."""
    from .models import Status

    verdicts = {s.value for s in Status}
    vocabulary = (
        set(FAILURE_CATEGORIES)
        | {UNCLASSIFIED}
        | set(COVERAGE_HOLE_CATEGORIES)
        | {UNCLASSIFIED_COVERAGE_HOLE}
        | {"NARROWED", "UNDETERMINED"}
    )
    collision = verdicts.intersection(vocabulary)
    if collision:
        raise AssertionError(
            f"system_failure_taxonomy vocabulary collides with dv_harness.models.Status "
            f"on {sorted(collision)} -- a classification must never be confusable with a "
            "verification verdict"
        )


# -----------------------------------------------------------------------------
# (b) Root-cause BOUNDARY localization from a per-subsystem I/O correctness map.
# -----------------------------------------------------------------------------

_VALID_IO_STATUS: Tuple[str, ...] = ("CORRECT", "INCORRECT", "UNKNOWN")


def _normalize_status_value(value: Any, *, subsystem_id: str, side: str) -> str:
    """Normalize one declared input/output correctness fact to CORRECT / INCORRECT
    / UNKNOWN. `None` is UNKNOWN (an honestly absent fact, never a guess); a bool
    is CORRECT/INCORRECT; a string must already be one of the three real values.
    Anything else is a caller error."""
    if value is None:
        return "UNKNOWN"
    if isinstance(value, bool):
        return "CORRECT" if value else "INCORRECT"
    if isinstance(value, str):
        v = value.strip().upper()
        if v in _VALID_IO_STATUS:
            return v
        raise ValueError(
            f"localize_failure_boundary: subsystem {subsystem_id!r} {side} status "
            f"{value!r} is not one of {_VALID_IO_STATUS}"
        )
    raise ValueError(
        f"localize_failure_boundary: subsystem {subsystem_id!r} {side} status must be a "
        f"bool, str, or None, got {type(value)}"
    )


def _normalize_io_entry(subsystem_id: str, raw: Any) -> Dict[str, str]:
    """Normalize one subsystem's raw I/O record into {'input': ..., 'output': ...},
    both in {'CORRECT','INCORRECT','UNKNOWN'}. Accepts either 'input_status'/
    'output_status' (string-valued) or 'input_correct'/'output_correct' (bool or
    None) -- whichever the caller's own producer already uses; never both silently
    merged if they disagree (an entry declaring both shapes is a caller error)."""
    if not isinstance(raw, dict):
        raise ValueError(
            f"localize_failure_boundary: subsystem {subsystem_id!r} io record must be a "
            f"dict, got {type(raw)}"
        )
    has_status_shape = "input_status" in raw or "output_status" in raw
    has_bool_shape = "input_correct" in raw or "output_correct" in raw
    if has_status_shape and has_bool_shape:
        raise ValueError(
            f"localize_failure_boundary: subsystem {subsystem_id!r} declares both the "
            "'input_status'/'output_status' shape and the 'input_correct'/'output_correct' "
            "shape -- ambiguous which is authoritative"
        )
    if has_status_shape:
        input_raw, output_raw = raw.get("input_status"), raw.get("output_status")
    elif has_bool_shape:
        input_raw, output_raw = raw.get("input_correct"), raw.get("output_correct")
    else:
        raise ValueError(
            f"localize_failure_boundary: subsystem {subsystem_id!r} io record must declare "
            "input/output correctness via 'input_status'/'output_status' or "
            "'input_correct'/'output_correct'"
        )
    return {
        "input": _normalize_status_value(input_raw, subsystem_id=subsystem_id, side="input"),
        "output": _normalize_status_value(output_raw, subsystem_id=subsystem_id, side="output"),
    }


def _normalize_connection_edge(edge: Any) -> Tuple[str, str]:
    """Normalize one declared connection into (upstream_id, downstream_id). Accepts
    a dict with 'upstream'/'downstream' keys, or a 2-element tuple/list
    (upstream, downstream)."""
    if isinstance(edge, dict):
        if "upstream" not in edge or "downstream" not in edge:
            raise ValueError(
                f"localize_failure_boundary: connection dict {edge!r} must carry both "
                "'upstream' and 'downstream'"
            )
        return edge["upstream"], edge["downstream"]
    if isinstance(edge, (tuple, list)) and len(edge) == 2:
        return edge[0], edge[1]
    raise ValueError(
        f"localize_failure_boundary: connection entry must be a dict with "
        f"'upstream'/'downstream' or a 2-element (upstream, downstream) tuple/list, "
        f"got {edge!r}"
    )


@dataclass
class BoundaryLocalization:
    """One boundary-localization result over a per-subsystem I/O correctness map.

    `status` is `"NARROWED"` (evidence proves exactly one subsystem boundary) or
    `"UNDETERMINED"` (it does not -- zero, multiple, or contradictory candidates).
    `boundary` is the single narrowed subsystem id, or `None` when `UNDETERMINED`.
    `candidates` lists every subsystem the evidence could not rule out (empty when
    the evidence gives no candidate at all, or when narrowed to exactly one and
    `candidates == [boundary]`). `reason` is a real, human-readable explanation
    citing the evidence that produced this result. `evidence` is the normalized
    per-subsystem I/O status map this result was computed from, so a reader can
    verify the conclusion without re-deriving it.
    """
    status: str
    boundary: Optional[str]
    candidates: List[str]
    reason: str
    evidence: Dict[str, Dict[str, str]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "boundary": self.boundary,
            "candidates": list(self.candidates),
            "reason": self.reason,
            "evidence": self.evidence,
        }


def localize_failure_boundary(
    subsystem_io_map: Dict[str, Any],
    connections: Optional[Sequence[Union[Dict[str, str], Tuple[str, str]]]] = None,
) -> BoundaryLocalization:
    """Name the NARROWEST subsystem boundary consistent with a per-subsystem
    input/output correctness map.

    `subsystem_io_map` maps a subsystem id to a duck-typed record declaring whether
    that subsystem's own input and output were confirmed CORRECT, confirmed
    INCORRECT, or are UNKNOWN (unconfirmed either way). `connections` is an
    optional list of directly-wired (upstream_id, downstream_id) pairs -- pairs
    where the caller asserts downstream's input IS upstream's output with no
    intervening logic -- used only to detect a real CONTRADICTION in the supplied
    evidence (an upstream CORRECT output paired with a downstream INCORRECT input
    on the same wire, or the reverse), never to infer a fact nobody declared.

    This never claims a specific root cause the input data does not prove. Exactly
    one subsystem whose input is CORRECT and whose output is INCORRECT is the
    narrowest boundary the evidence can prove (the fault lives between that
    subsystem's own input and output). Zero such subsystems, more than one, or any
    contradictory pair across a declared connection, all report `UNDETERMINED`
    rather than a guess.
    """
    if not subsystem_io_map:
        raise ValueError(
            "localize_failure_boundary: subsystem_io_map must be a non-empty mapping"
        )
    if not isinstance(subsystem_io_map, dict):
        raise ValueError(
            f"localize_failure_boundary: subsystem_io_map must be a dict, got "
            f"{type(subsystem_io_map)}"
        )

    normalized: Dict[str, Dict[str, str]] = {
        sid: _normalize_io_entry(sid, raw) for sid, raw in subsystem_io_map.items()
    }

    contradictions: List[Tuple[str, str, str, str]] = []
    if connections:
        for edge in connections:
            up, down = _normalize_connection_edge(edge)
            if up not in normalized or down not in normalized:
                # A connection naming a subsystem this map has no facts for cannot
                # be cross-checked -- it is not evidence of anything, and it is
                # never silently assumed consistent.
                continue
            up_out = normalized[up]["output"]
            down_in = normalized[down]["input"]
            if up_out in ("CORRECT", "INCORRECT") and down_in in ("CORRECT", "INCORRECT") and up_out != down_in:
                contradictions.append((up, down, up_out, down_in))

    if contradictions:
        detail = "; ".join(
            f"{up!r}.output={up_out} but {down!r}.input={down_in} on a declared direct connection"
            for up, down, up_out, down_in in contradictions
        )
        return BoundaryLocalization(
            status="UNDETERMINED",
            boundary=None,
            candidates=sorted({sid for pair in contradictions for sid in pair[:2]}),
            reason=f"contradictory evidence across declared connection(s): {detail}",
            evidence=normalized,
        )

    candidates = sorted(
        sid for sid, v in normalized.items() if v["input"] == "CORRECT" and v["output"] == "INCORRECT"
    )

    if len(candidates) == 1:
        boundary = candidates[0]
        return BoundaryLocalization(
            status="NARROWED",
            boundary=boundary,
            candidates=candidates,
            reason=(
                f"subsystem {boundary!r} is the only one whose input is confirmed CORRECT "
                "and whose output is confirmed INCORRECT"
            ),
            evidence=normalized,
        )

    if len(candidates) == 0:
        unknown_blocking = sorted(
            sid for sid, v in normalized.items() if "UNKNOWN" in (v["input"], v["output"])
        )
        if unknown_blocking:
            reason = (
                "no subsystem shows a confirmed CORRECT-input/INCORRECT-output pattern, and "
                f"{unknown_blocking} carry an UNKNOWN input or output that could be hiding one"
            )
        else:
            reason = (
                "no subsystem shows a confirmed CORRECT-input/INCORRECT-output pattern; the "
                "supplied evidence does not localize a failure boundary"
            )
        return BoundaryLocalization(
            status="UNDETERMINED",
            boundary=None,
            candidates=[],
            reason=reason,
            evidence=normalized,
        )

    # len(candidates) > 1: more than one subsystem independently shows the
    # CORRECT-input/INCORRECT-output pattern. Never picked between arbitrarily.
    return BoundaryLocalization(
        status="UNDETERMINED",
        boundary=None,
        candidates=candidates,
        reason=(
            f"multiple subsystems {candidates} each show a confirmed CORRECT-input/"
            "INCORRECT-output pattern; the supplied evidence does not narrow the boundary "
            "to a single one"
        ),
        evidence=normalized,
    )


# -----------------------------------------------------------------------------
# (c) System coverage-hole taxonomy: 6 real values + UNCLASSIFIED_COVERAGE_HOLE.
# -----------------------------------------------------------------------------

#: The six named categories, verbatim per the task, plus the honest fallback
#: (defined separately, exactly as `FAILURE_CATEGORIES` keeps `UNCLASSIFIED` out
#: of its own tuple).
COVERAGE_HOLE_CATEGORIES: Tuple[str, ...] = (
    "SUBSYSTEM_GAP",
    "INTEGRATION_GAP",
    "RESOURCE_GAP",
    "SCENARIO_GAP",
    "ERROR_PATH_GAP",
    "COVERAGE_MODEL_GAP",
)

#: Reported when no declared field in the hole record gives a real basis for one
#: of the six categories above.
UNCLASSIFIED_COVERAGE_HOLE = "UNCLASSIFIED_COVERAGE_HOLE"

#: Priority order, most structurally certain first: a hole whose coverage MODEL
#: was never defined at all (`coverage_model_missing`) is the most fundamental
#: fact and is checked first; a declared shared-resource or error-path concern is
#: checked next because both are specific, narrow claims; whether the hole spans
#: more than one subsystem (INTEGRATION_GAP) is checked before whether it is
#: scoped to exactly one (SUBSYSTEM_GAP), since a hole declaring both a cross-
#: subsystem scope and a single subsystem id is a caller inconsistency this
#: ordering resolves toward the broader, safer (INTEGRATION_GAP) reading rather
#: than silently picking the narrower one; SCENARIO_GAP (a whole system-level
#: scenario category never attempted) is checked last among the six because it is
#: the broadest, least structurally specific claim.
COVERAGE_HOLE_CLASSIFICATION_ORDER: Tuple[str, ...] = (
    "COVERAGE_MODEL_GAP",
    "RESOURCE_GAP",
    "ERROR_PATH_GAP",
    "INTEGRATION_GAP",
    "SUBSYSTEM_GAP",
    "SCENARIO_GAP",
)
assert set(COVERAGE_HOLE_CLASSIFICATION_ORDER) == set(COVERAGE_HOLE_CATEGORIES), (
    "COVERAGE_HOLE_CLASSIFICATION_ORDER must name exactly the six "
    "COVERAGE_HOLE_CATEGORIES, no more and no fewer"
)


@dataclass
class CoverageHoleClassification:
    """One system coverage-hole record's classification result.

    `category` is one of `COVERAGE_HOLE_CATEGORIES` or
    `UNCLASSIFIED_COVERAGE_HOLE` -- never anything else. `matched_field` names the
    real input field this decision was made on (`None` only for
    `UNCLASSIFIED_COVERAGE_HOLE`). `reason` is a real, human-readable explanation
    citing the declared fact.
    """
    category: str
    matched_field: Optional[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "matched_field": self.matched_field,
            "reason": self.reason,
        }


def classify_system_coverage_hole(hole: Dict[str, Any]) -> CoverageHoleClassification:
    """Classify one caller-declared system coverage-hole record.

    `hole` is a duck-typed dict that MAY declare any of: `coverage_model_missing`
    (bool -- no covergroup/bin exists yet for the relevant system-level event),
    `involves_shared_resource` (bool), `involves_error_path` (bool), `scope`
    (`"cross_subsystem"` or `"single_subsystem"`), `subsystem_ids` (a list -- two
    or more implies cross-subsystem, exactly one implies single-subsystem),
    `subsystem_id` (a single id, implies single-subsystem), and
    `scenario_category_missing` (bool).

    Never a forced guess: a `hole` record naming none of these recognised fields
    (or naming only falsy/absent values) reports `UNCLASSIFIED_COVERAGE_HOLE`
    rather than being assigned one of the six categories on no real basis.
    """
    if hole is None:
        raise ValueError("classify_system_coverage_hole: hole must not be None")
    if not isinstance(hole, dict):
        raise ValueError(
            f"classify_system_coverage_hole: hole must be a dict, got {type(hole)}"
        )

    if hole.get("coverage_model_missing"):
        return CoverageHoleClassification(
            "COVERAGE_MODEL_GAP",
            "coverage_model_missing",
            "declared: no covergroup/bin exists yet for this system-level event",
        )

    if hole.get("involves_shared_resource"):
        return CoverageHoleClassification(
            "RESOURCE_GAP",
            "involves_shared_resource",
            "declared: the hole concerns a shared-resource contention scenario",
        )

    if hole.get("involves_error_path"):
        return CoverageHoleClassification(
            "ERROR_PATH_GAP",
            "involves_error_path",
            "declared: the hole concerns an error/fault-handling path",
        )

    scope = hole.get("scope")
    subsystem_ids = hole.get("subsystem_ids")
    is_list = isinstance(subsystem_ids, (list, tuple))

    is_cross = scope == "cross_subsystem" or (is_list and len(subsystem_ids) >= 2)
    if is_cross:
        return CoverageHoleClassification(
            "INTEGRATION_GAP",
            "scope" if scope == "cross_subsystem" else "subsystem_ids",
            "declared: the hole spans two or more subsystems",
        )

    is_single = (
        scope == "single_subsystem"
        or (is_list and len(subsystem_ids) == 1)
        or bool(hole.get("subsystem_id"))
    )
    if is_single:
        matched = (
            "scope" if scope == "single_subsystem"
            else "subsystem_ids" if is_list
            else "subsystem_id"
        )
        return CoverageHoleClassification(
            "SUBSYSTEM_GAP",
            matched,
            "declared: the hole is scoped to one subsystem's own coverage",
        )

    if hole.get("scenario_category_missing"):
        return CoverageHoleClassification(
            "SCENARIO_GAP",
            "scenario_category_missing",
            "declared: a whole system-level scenario category was never attempted",
        )

    return CoverageHoleClassification(
        UNCLASSIFIED_COVERAGE_HOLE,
        None,
        "no recognised field in the hole record gave a real basis for classification",
    )


# Run the two literal cross-vocabulary guards, and the models.Status guard, at
# import time -- the same "held total/disjoint at import" discipline several
# sibling modules in this project already apply to their own vocabularies, so a
# future edit that reintroduces a collision fails immediately rather than being
# discovered only by a test someone remembered to run.
assert_disjoint_from_command_error_taxonomy()
assert_disjoint_from_loop_budget_failure_type()
assert_disjoint_from_verification_verdict_vocabulary()
