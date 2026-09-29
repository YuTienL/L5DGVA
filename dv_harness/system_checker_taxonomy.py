"""dv_harness/system_checker_taxonomy.py -- a 9-value SYSTEM-scope checker-type taxonomy.

WHAT THIS ANSWERS. Given a duck-typed description of what ONE system-level checker
verifies (a plain string, or a dict/object carrying `checker_name`/`description`/
`verifies`/`notes` text, or an explicit `declared_checker_type`), classify it into
exactly one of nine named SYSTEM-scope checker categories, or the honest
`UNCLASSIFIED_SYSTEM_CHECKER` fallback when nothing matches. This module performs
no file I/O, no subprocess, and no simulation of any kind -- it is a pure
classification function of whatever description a caller already has.

THE NINE CATEGORIES, matching a system-level (cross-subsystem / SoC-composition)
checkers scope:
  * DATA_FLOW_CHECKER -- a compare/check over data payload/transaction content as
    it moves across a system-level data path (data integrity, not merely presence).
  * RESOURCE_ARBITRATION_CHECKER -- a check that a shared system-level resource
    (a bus, a fabric port, a VIP-driven interface) is arbitrated/owned correctly
    across subsystems, never driven by two ACTIVE agents at once.
  * ADDRESS_ROUTING_CHECKER -- a check that an address is decoded/routed to the
    correct system-level destination (address-map/decoder correctness).
  * CLOCK_RESET_SEQUENCING_CHECKER -- a check that clock/reset sequencing across
    subsystem boundaries (power-up ordering, cross-domain reset release order)
    happened in the required order.
  * COMMAND_COMPATIBILITY_CHECKER -- a check that a command/task sequence remains
    compatible/legal across the subsystems it spans (e.g. a cross-subsystem
    command.txt-level compatibility check, distinct from a single subsystem's own
    task semantics).
  * BUILD_INTEGRITY_CHECKER -- a check over the SYSTEM MERGE itself: duplicate
    package/module/class declarations, factory-type-name collisions, or other
    build-time integrity defects introduced by composing multiple subsystem
    source sets into one system build.
  * SCOREBOARD_COMPOSITION_CHECKER -- a check over how multiple subsystems'
    scoreboards are COMPOSED/aggregated at system level (a system-level rollup or
    cross-subsystem scoreboard wiring check, not one subsystem's own compare).
  * RECOVERY_CHECKER -- a check that the system recovers correctly from a fault/
    error/link-down condition (a real recovery PATH being exercised and verified),
    as opposed to merely detecting that an error occurred.
  * ERROR_PROPAGATION_CHECKER -- a check that an error/fault injected or observed
    in one subsystem is correctly OBSERVED/PROPAGATED to the system-level status
    a downstream subsystem or the system top is expected to reflect.

EXPLICITLY A DIFFERENT, SYSTEM-SCOPE TAXONOMY FROM `verification_architecture.py`'s
`CheckerIR`. That module's `CheckerIR` extends ONE PER-SUBSYSTEM protocol check
entry (`connectivity.generate_protocol_check_entry()`'s own shape) with a
target-instance/mount-side/status/confidence record -- it answers "is this ONE
checker correctly bound and linked within ITS OWN subsystem". This module answers
a different, higher-altitude question: "of the checkers that exist at SYSTEM
(cross-subsystem/SoC-composition) scope, what KIND of system-level property is
this one checking" -- a pure name/kind classification with no bind-target, no
mount-side, and no per-subsystem linkage concept at all. Per this task's own
scope, this module never imports `verification_architecture.py` (nor any other
claimed/concurrent-batch file) and never re-derives that module's CheckerIR
shape; the two classify genuinely different things and are not meant to merge.

REUSE OVER REINVENT, stated as a boundary rather than an import: several REAL,
pre-existing modules already implement SYSTEM-scope mechanisms this taxonomy's
nine categories describe in prose -- `system_resource_inventory.py`'s
ACTIVE_DRIVER_CONFLICT detection is a real RESOURCE_ARBITRATION_CHECKER concern;
`system_build_proof.py`'s `analyze_system_merge()` duplicate-package/duplicate-
type/factory-collision checks are a real BUILD_INTEGRITY_CHECKER concern;
`system_topology_analysis.py` carries real ADDRESS_ROUTING_CHECKER-shaped
address-region facts. None of those modules is imported here (per this task's
own file-safety scope: read-only precedent, not an import target) -- this module
never re-implements or duplicates their logic. It only names the KIND of checker
a caller's description describes; deciding whether a real project's checker
actually behaves that way stays those modules' job, not this one's.

CLASSIFICATION IS EVIDENCE-BASED, NEVER GUESSED. A caller may declare
`declared_checker_type` explicitly (validated against the nine-value vocabulary;
an unrecognized value raises rather than being silently coerced or dropped --
the same "an explicit declaration wins, and a bad one is refused rather than
guessed past" discipline `scoreboard_placement_scope.py` already applies to its
own `declared_scope` field). Absent an explicit declaration, this module falls
back to a real, cited KEYWORD match over the description's own free text --
never a semantic/ML classifier, since none exists in this codebase and inventing
one would be exactly the unverifiable machinery the Evidence Truth Rule forbids.
A description matching none of the nine categories' keyword sets is reported
`UNCLASSIFIED_SYSTEM_CHECKER` with no matched evidence -- never forced into one
of the nine categories on a weak guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

#: The nine named SYSTEM-scope checker categories, verbatim per the task. Order
#: here is documentation only -- `CLASSIFICATION_ORDER` below is the real,
#: tested priority a description is actually checked in.
SYSTEM_CHECKER_TYPES: Tuple[str, ...] = (
    "DATA_FLOW_CHECKER",
    "RESOURCE_ARBITRATION_CHECKER",
    "ADDRESS_ROUTING_CHECKER",
    "CLOCK_RESET_SEQUENCING_CHECKER",
    "COMMAND_COMPATIBILITY_CHECKER",
    "BUILD_INTEGRITY_CHECKER",
    "SCOREBOARD_COMPOSITION_CHECKER",
    "RECOVERY_CHECKER",
    "ERROR_PROPAGATION_CHECKER",
)

#: Reported when neither an explicit declaration nor any keyword rule matches.
#: Never one of `SYSTEM_CHECKER_TYPES` -- a classifier that could return this AS
#: a named category would make "we could not tell" indistinguishable from a real
#: finding.
UNCLASSIFIED_SYSTEM_CHECKER = "UNCLASSIFIED_SYSTEM_CHECKER"

#: The real priority order a description is checked in when no explicit
#: declaration is present, most structurally specific first. Exported so a test
#: (or a caller deciding whether a category it did not get was even reachable)
#: can hold this list against `SYSTEM_CHECKER_TYPES` rather than trust prose.
#:
#: Rationale, briefest form: BUILD_INTEGRITY_CHECKER and RESOURCE_ARBITRATION_
#: CHECKER are checked first because their keyword vocabularies name the most
#: structurally distinctive real terms (duplicate/collision/merge; arbitration/
#: contention/ownership) and are least likely to appear as an incidental word in
#: a description of something else. ADDRESS_ROUTING_CHECKER and CLOCK_RESET_
#: SEQUENCING_CHECKER follow, each keyed to their own distinctive vocabulary
#: (decode/route/address-map; clock/reset + sequencing/ordering). RECOVERY_
#: CHECKER is checked before ERROR_PROPAGATION_CHECKER because a description
#: naming an actual recovery PATH ("recover", "recovery") is a more decisive,
#: narrower claim than one merely naming propagation of an error/fault signal;
#: the two keyword sets are kept deliberately disjoint (recover* vs propagat*)
#: so a description naming both is resolved by this order, not by accident.
#: COMMAND_COMPATIBILITY_CHECKER and SCOREBOARD_COMPOSITION_CHECKER are checked
#: next, each keyed to their own compound phrase ("command compatibility"/
#: "command.txt"; "scoreboard composition"/"composed scoreboard"). DATA_FLOW_
#: CHECKER is checked last among the nine because its vocabulary ("data flow",
#: "data integrity", "data path") is the broadest and most likely to appear
#: incidentally inside a description that is really naming one of the other
#: eight, more specific concerns.
CLASSIFICATION_ORDER: Tuple[str, ...] = (
    "BUILD_INTEGRITY_CHECKER",
    "RESOURCE_ARBITRATION_CHECKER",
    "ADDRESS_ROUTING_CHECKER",
    "CLOCK_RESET_SEQUENCING_CHECKER",
    "RECOVERY_CHECKER",
    "ERROR_PROPAGATION_CHECKER",
    "COMMAND_COMPATIBILITY_CHECKER",
    "SCOREBOARD_COMPOSITION_CHECKER",
    "DATA_FLOW_CHECKER",
)
assert set(CLASSIFICATION_ORDER) == set(SYSTEM_CHECKER_TYPES), (
    "CLASSIFICATION_ORDER must name exactly the nine SYSTEM_CHECKER_TYPES, no "
    "more and no fewer -- a category missing from this order could never be "
    "reached, and an extra name here would not be a real category."
)


class SystemCheckerTaxonomyError(ValueError):
    """Raised on a caller-usage error: a malformed description, or an explicit
    `declared_checker_type` that names something outside the nine-value
    vocabulary. Never raised for an honestly-unclassifiable description --
    that is the normal `UNCLASSIFIED_SYSTEM_CHECKER` result, not an error."""


@dataclass
class SystemCheckerClassification:
    """One system-level checker's classification result.

    `checker_type` is one of `SYSTEM_CHECKER_TYPES` or
    `UNCLASSIFIED_SYSTEM_CHECKER` -- never anything else. `declared` is True
    only when the result came from a caller's own explicit
    `declared_checker_type` (never from keyword inference). `matched_evidence`
    is the real matched phrase (or, for a declaration, the declared value
    itself) the decision was made on -- never a paraphrase or a fabricated
    example -- empty only for `UNCLASSIFIED_SYSTEM_CHECKER`. `rule_id` names
    which rule decided it, for a human or a test to trace the decision back to
    this module's own `CLASSIFICATION_ORDER`/keyword tables.
    """
    checker_type: str
    matched_evidence: str
    rule_id: str
    declared: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checker_type": self.checker_type,
            "matched_evidence": self.matched_evidence,
            "rule_id": self.rule_id,
            "declared": self.declared,
        }


# ---------------------------------------------------------------------------
# Keyword vocabulary. Each category's regex names the real, distinctive terms
# a description of that KIND of system-level checker would plausibly use.
# Nothing here is a guess at a specific project's naming convention -- these
# are generic English phrases describing the checker's own PURPOSE, matched
# case-insensitively.
# ---------------------------------------------------------------------------
_BUILD_INTEGRITY_RE = re.compile(
    r"\bbuild\s+integrity\b|\bsystem\s+merge\b|\bmerge\s+collision\b|"
    r"\bduplicate\s+(?:package|module|class|type|declaration)\b|"
    r"\bfactory[\s-]type[\s-]name\s+collision\b|\bcompile\s+integrity\b",
    re.IGNORECASE,
)
_RESOURCE_ARBITRATION_RE = re.compile(
    r"\barbitration\b|\barbiter\b|\bshared\s+resource\b|\bresource\s+ownership\b|"
    r"\bactive\s+driver\s+conflict\b|\bbus\s+contention\b|\bcontention\b|"
    r"\bownership\s+conflict\b",
    re.IGNORECASE,
)
_ADDRESS_ROUTING_RE = re.compile(
    r"\baddress\s+(?:decode|decoding|routing|map|region)\b|\baddress\s+decoder\b|"
    r"\brout(?:e|ed|ing)\s+to\s+the\s+correct\b|\bdecoder\s+correctness\b",
    re.IGNORECASE,
)
_CLOCK_RESET_SEQUENCING_RE = re.compile(
    r"(?:\bclock\b|\breset\b)[^.]{0,40}\b(?:sequenc\w*|order(?:ing)?)\b|"
    r"\bpower[\s-]up\s+sequenc\w*\b|\bcross[\s-]domain\s+reset\b|"
    r"\breset\s+release\s+order\b",
    re.IGNORECASE,
)
_RECOVERY_RE = re.compile(
    r"\brecover(?:y|ed|ing|s)?\b|\blink[\s-]down\s+recovery\b|\bfault\s+recovery\b",
    re.IGNORECASE,
)
_ERROR_PROPAGATION_RE = re.compile(
    r"\bpropagat(?:e|es|ed|ion)\b",
    re.IGNORECASE,
)
_COMMAND_COMPATIBILITY_RE = re.compile(
    r"\bcommand\s+compatibilit\w*\b|\bcommand\.txt\b|\btask\s+compatibilit\w*\b|"
    r"\bcommand\s+sequence\s+compatibilit\w*\b|\bcross[\s-]subsystem\s+command\b",
    re.IGNORECASE,
)
_SCOREBOARD_COMPOSITION_RE = re.compile(
    r"\bscoreboard\s+composition\b|\bcompos(?:ed|ition)\s+scoreboard\b|"
    r"\bsystem[\s-]level\s+scoreboard\b|\baggregat\w*\s+scoreboard\b|"
    r"\bcross[\s-]subsystem\s+scoreboard\b",
    re.IGNORECASE,
)
_DATA_FLOW_RE = re.compile(
    r"\bdata\s+flow\b|\bdata\s+integrity\b|\bdata\s+path\b|\bdata\s+corruption\b|"
    r"\bpayload\s+(?:integrity|correctness)\b|\btransaction\s+data\b",
    re.IGNORECASE,
)

_KEYWORD_RULES: Tuple[Tuple[str, re.Pattern, str], ...] = (
    ("BUILD_INTEGRITY_CHECKER", _BUILD_INTEGRITY_RE, "build_integrity_keyword"),
    ("RESOURCE_ARBITRATION_CHECKER", _RESOURCE_ARBITRATION_RE, "resource_arbitration_keyword"),
    ("ADDRESS_ROUTING_CHECKER", _ADDRESS_ROUTING_RE, "address_routing_keyword"),
    ("CLOCK_RESET_SEQUENCING_CHECKER", _CLOCK_RESET_SEQUENCING_RE, "clock_reset_sequencing_keyword"),
    ("RECOVERY_CHECKER", _RECOVERY_RE, "recovery_keyword"),
    ("ERROR_PROPAGATION_CHECKER", _ERROR_PROPAGATION_RE, "error_propagation_keyword"),
    ("COMMAND_COMPATIBILITY_CHECKER", _COMMAND_COMPATIBILITY_RE, "command_compatibility_keyword"),
    ("SCOREBOARD_COMPOSITION_CHECKER", _SCOREBOARD_COMPOSITION_RE, "scoreboard_composition_keyword"),
    ("DATA_FLOW_CHECKER", _DATA_FLOW_RE, "data_flow_keyword"),
)
assert tuple(name for name, _, _ in _KEYWORD_RULES) == CLASSIFICATION_ORDER, (
    "_KEYWORD_RULES must be listed in exactly CLASSIFICATION_ORDER's order -- "
    "the two are meant to stay in lockstep, not merely equal as sets."
)

#: Text fields this module will read off a dict/object-shaped description, in
#: the order their content is concatenated for keyword matching. A caller may
#: use any subset; an absent field simply contributes nothing.
_TEXT_FIELDS: Tuple[str, ...] = ("checker_name", "description", "verifies", "notes", "text")


def _coerce_verifies_field(value: Any) -> str:
    """`verifies` may be a single string or a list of short phrases (the
    natural shape for "what this checker verifies": several distinct claims).
    Both are folded into one text blob for keyword matching; anything else
    contributes nothing rather than raising, since it is not this field's job
    to validate a caller's whole description shape."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value if isinstance(v, str))
    return ""


def _extract_text(description: Any) -> str:
    """Concatenate every recognized text field out of a duck-typed
    description into one blob for keyword matching. Accepts a bare string, a
    dict, or any object exposing the recognized fields as attributes -- never
    raises on an unrecognized shape, since a description this module cannot
    read any text out of is simply unclassifiable (`UNCLASSIFIED_SYSTEM_
    CHECKER`), not a caller error."""
    if isinstance(description, str):
        return description
    parts: List[str] = []
    if isinstance(description, dict):
        for field_name in _TEXT_FIELDS:
            if field_name not in description:
                continue
            value = description[field_name]
            if field_name == "verifies":
                parts.append(_coerce_verifies_field(value))
            elif isinstance(value, str):
                parts.append(value)
        return " ".join(p for p in parts if p)
    # Generic object: read the same fields as attributes when present.
    for field_name in _TEXT_FIELDS:
        value = getattr(description, field_name, None)
        if value is None:
            continue
        if field_name == "verifies":
            parts.append(_coerce_verifies_field(value))
        elif isinstance(value, str):
            parts.append(value)
    return " ".join(p for p in parts if p)


def _extract_declared_type(description: Any) -> Optional[str]:
    """Read an explicit `declared_checker_type` off a dict or object-shaped
    description, if present. Returns None when absent (a bare string
    description can never carry one). Validation against the nine-value
    vocabulary happens in `classify_system_checker()`, not here, so the
    caller-usage error is raised in one place with full context."""
    if isinstance(description, dict):
        value = description.get("declared_checker_type")
    else:
        value = getattr(description, "declared_checker_type", None)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SystemCheckerTaxonomyError(
            "system_checker_taxonomy: declared_checker_type must be a non-empty "
            f"string naming one of {SYSTEM_CHECKER_TYPES}; got {value!r}"
        )
    return value.strip()


def classify_system_checker(description: Union[str, Dict[str, Any], Any]) -> SystemCheckerClassification:
    """Classify one system-level checker's description into one of the nine
    `SYSTEM_CHECKER_TYPES`, or `UNCLASSIFIED_SYSTEM_CHECKER` when nothing
    matches.

    `description` is duck-typed: a bare string, a dict, or any object exposing
    `checker_name`/`description`/`verifies`/`notes`/`text` fields and/or an
    explicit `declared_checker_type`. This function performs no file I/O and
    no subprocess call; it is a pure function of `description`.

    An explicit `declared_checker_type` (validated against `SYSTEM_CHECKER_
    TYPES`) always wins over keyword inference -- a caller who already knows
    what kind of checker this is need not have that knowledge second-guessed,
    and a caller who declares something outside the nine-value vocabulary gets
    a raised `SystemCheckerTaxonomyError` naming the real accepted values,
    never a silent fallback to keyword matching.
    """
    declared = _extract_declared_type(description)
    if declared is not None:
        if declared not in SYSTEM_CHECKER_TYPES:
            raise SystemCheckerTaxonomyError(
                "system_checker_taxonomy: declared_checker_type "
                f"{declared!r} is not one of the nine recognized "
                f"SYSTEM_CHECKER_TYPES: {SYSTEM_CHECKER_TYPES}"
            )
        return SystemCheckerClassification(
            checker_type=declared,
            matched_evidence=declared,
            rule_id="explicit_declaration",
            declared=True,
        )

    text = _extract_text(description)
    if not text or not text.strip():
        return SystemCheckerClassification(UNCLASSIFIED_SYSTEM_CHECKER, "", "no_text_to_classify")

    for checker_type, rgx, rule_id in _KEYWORD_RULES:
        m = rgx.search(text)
        if m:
            return SystemCheckerClassification(checker_type, m.group(0), rule_id)

    return SystemCheckerClassification(UNCLASSIFIED_SYSTEM_CHECKER, "", "no_rule_matched")


def classify_system_checkers(
    descriptions: List[Union[str, Dict[str, Any], Any]],
) -> List[SystemCheckerClassification]:
    """Classify several system-level checker descriptions at once, preserving
    input order. A pure convenience wrapper over `classify_system_checker()` --
    no aggregation, no deduplication, no ranking."""
    return [classify_system_checker(d) for d in descriptions]


def assert_disjoint_from_verification_verdict_vocabulary() -> None:
    """This module's checker-type vocabulary must share no token with
    `dv_harness.models.Status`, the harness's verification-verdict vocabulary
    -- a checker-KIND classification must never be confusable with a stage
    verdict."""
    from .models import Status

    verdicts = {s.value for s in Status}
    vocabulary = set(SYSTEM_CHECKER_TYPES) | {UNCLASSIFIED_SYSTEM_CHECKER}
    collision = verdicts.intersection(vocabulary)
    if collision:
        raise AssertionError(
            f"system_checker_taxonomy vocabulary collides with dv_harness.models.Status "
            f"on {sorted(collision)} -- a checker-type classification must never be "
            "confusable with a verification verdict"
        )


# ---------------------------------------------------------------------------
# Ad hoc front door, mirroring this project's `python -m dv_harness.<module>`
# convention. No `dv-harness` CLI verb is registered here -- `cli.py` is out of
# this task's file-safety scope.
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[List[str]] = None) -> int:
    """`checkers <file.json>` -- classify a list of duck-typed checker
    descriptions read from a JSON file (a bare list, or `{"checkers": [...]}`),
    print each result, and exit 0 if every one classified (declared or
    keyword-matched), 1 if at least one is `UNCLASSIFIED_SYSTEM_CHECKER`, 2 on
    a usage error or malformed input."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="system_checker_taxonomy")
    sub = parser.add_subparsers(dest="cmd")
    types_p = sub.add_parser("types")
    classify_p = sub.add_parser("classify")
    classify_p.add_argument("path")
    classify_p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "types" or args.cmd is None:
        print(json.dumps(list(SYSTEM_CHECKER_TYPES), indent=2))
        return 0

    if args.cmd == "classify":
        try:
            with open(args.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"system_checker_taxonomy: could not read {args.path}: {exc}", file=sys.stderr)
            return 2
        if isinstance(raw, dict) and "checkers" in raw:
            raw = raw["checkers"]
        if not isinstance(raw, list):
            print("system_checker_taxonomy: input must be a list, or {\"checkers\": [...]}", file=sys.stderr)
            return 2

        try:
            results = classify_system_checkers(raw)
        except SystemCheckerTaxonomyError as exc:
            print(f"system_checker_taxonomy: {exc}", file=sys.stderr)
            return 2

        payload = [r.to_dict() for r in results]
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for r in payload:
                print(f"{r['checker_type']:35s} rule={r['rule_id']:30s} evidence={r['matched_evidence']!r}")

        if any(r["checker_type"] == UNCLASSIFIED_SYSTEM_CHECKER for r in payload):
            return 1
        return 0

    parser.print_help()
    return 2


def main() -> None:
    import sys
    sys.exit(execute_verb(sys.argv[1:]))


if __name__ == "__main__":
    main()
