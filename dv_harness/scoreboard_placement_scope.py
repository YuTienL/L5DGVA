"""dv_harness/scoreboard_placement_scope.py -- a fixed taxonomy for WHERE a
scoreboard compares transactions (its placement SCOPE), plus one explicit,
narrow default rule for a SyoSil/similar VIP-adjacent compare-engine
component whose own description carries no placement signal.

REUSE SEARCH PERFORMED FIRST (this task's own rule 2)
------------------------------------------------------
Grepped `dv_harness/` for `PORT_LOCAL`/`FUNCTION_LOCAL`/`BLOCK_LOCAL`/
`CROSS_PORT`/`DMA_PATH`/`MEMORY_PATH`/`INTERRUPT_PATH`/`END_TO_END` and for
`scoreboard_placement_scope`/`ScoreboardPlacementScope` before writing a line
here: the only hits were `preflight.py`'s unrelated `TRANSPORT_LOCAL` and one
Chinese-language `CROSS_PORT_GLOBAL_LOCK_FORBIDDEN` token inside
`prompts.py`'s pattern-architecture prose (an arbitration rule for
`branch_fw`, not a scoreboard-scope taxonomy). No scoreboard placement-scope
vocabulary exists anywhere in this repo. `amba_scoreboard_env.py` carries an
adjacent but DIFFERENT vocabulary (`ENV_ROLE_SCOREBOARD` /
`ENV_ROLE_SUBSCRIBER` / `ENV_ROLE_PREDICTOR` / ...) that answers "what UVM
CLASS ROLE does this component play", never "where does its compare
operation sit relative to the DUT's ports/paths" -- a different question,
answered here.

WHY THIS MODULE IS DELIBERATELY STANDALONE
-------------------------------------------
This task's own file-safety scope authorizes a brand-new file only and
explicitly instructs accepting related project facts (what a scoreboard
compares; what project evidence says about a VIP-adjacent component) as
GENERIC, DUCK-TYPED parameters rather than importing `connectivity.py`,
`amba_scoreboard_env.py`, `syoscb_topology_plan.py`/`syoscb_compare_policy.py`
or any other module concurrently owned by other work in this same batch.
Every function below therefore takes plain `dict` inputs with documented
keys and imports nothing from elsewhere in this package.

THE TAXONOMY: 8 SCOPE VALUES, ONE FIXED PRECEDENCE ORDER
----------------------------------------------------------
`SCOPE_VALUES` is exactly the 8 values this task names, in the task's own
listed order. Classification precedence (most architecturally specific
first, so a compare that is BOTH e.g. cross-port AND on a DMA path is named
DMA_PATH rather than the less informative CROSS_PORT) is
`SCOPE_PRECEDENCE`:

    END_TO_END > INTERRUPT_PATH > DMA_PATH > MEMORY_PATH > CROSS_PORT >
    PORT_LOCAL > FUNCTION_LOCAL > BLOCK_LOCAL

EVIDENCE TRUTH RULE, APPLIED TO A TAXONOMY CLASSIFIER
-------------------------------------------------------
A scope is asserted ONLY from an explicit, caller-declared FACT (a boolean
"does this compare span the DMA engine", an integer port count, or a direct
`declared_scope` tag already validated against `SCOPE_VALUES`) -- never from
free-text guessing over a prose description, which would be exactly the
"confident guess" this project's Evidence Truth Rule forbids. A
`compare_description` (or `project_evidence`) dict carrying none of the
recognised fact keys, or carrying only explicitly-False/absent facts, yields
`STATUS_UNVERIFIABLE` naming the absence -- never a defaulted or inferred
scope. A malformed fact (wrong type, an unrecognised `declared_scope` value)
is a caller error and raises `ScoreboardPlacementScopeError` rather than
being silently coerced or dropped.

THE SYOSIL/SIMILAR DEFAULT RULE, STATED EXPLICITLY RATHER THAN ASSUMED
------------------------------------------------------------------------
A SyoSil-originated (or declared-similar) VIP scoreboard component -- the
real-world SYOSCB family -- is architecturally a generic, reusable,
protocol-agnostic QUEUE-BASED compare engine: a VIP plugs its own
transaction streams into a SYOSCB queue instance, and the queue instance
itself carries no inherent knowledge of where in the DUT's topology that
comparison sits. So when such a component is DECLARED present
(`vip_adjacent_compare_engine_declared: true`, or a `component_vendor`/
`component_kind`/`component_name` string naming it) and the compare
description carries NO placement fact of its own, reporting UNVERIFIABLE
would be technically honest but practically unhelpful -- the harness DOES
know one true thing about it (it is a queue/compare-engine), even without
knowing its placement. `classify_scoreboard_scope()` therefore reports
`STATUS_DEFAULTED`: `scope` stays `None` (no fabricated PORT_LOCAL/
BLOCK_LOCAL/etc. guess), `role` is set to `ROLE_QUEUE_COMPARE_ENGINE_DEFAULT`,
and `default_rule_applied=True` so the default is a stated fact of the
result, never a silent assumption a caller would have to notice was made.

`project_evidence` is the stated escape hatch: real project evidence citing
WHERE this component actually sits (its own scope-placement facts, or a
direct `declared_scope`, always alongside a non-empty `source` citation --
an uncited override is refused as not being real evidence) is consulted
BEFORE the default rule fires, and wins. `default_rule_overridden_by_evidence`
records that this happened.

DELIBERATELY BOUNDED, STATED RATHER THAN IMPLIED CLOSED
---------------------------------------------------------
(1) This module DECIDES a scope from DECLARED facts; it never parses a
    generated environment, a bind topology, or a real scoreboard's source to
    discover those facts itself -- that is a different concern belonging to
    (and explicitly out of scope for) `connectivity.py`/`amba_scoreboard_env.py`/
    the `syoscb_*` family. (2) The SyoSil-likeness detector is a fixed,
    explicit keyword/flag check, never fuzzy vendor-name inference -- an
    undeclared or unrecognised vendor never triggers the default rule.
    (3) There is no stage gate, no CLI wired into `cli.py` (this task's own
    rule forbids editing it), and no write of any kind: this module reads its
    two input dicts and returns a classification, nothing else. Front door is
    `python -m dv_harness.scoreboard_placement_scope classify|scopes`.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple


class ScoreboardPlacementScopeError(ValueError):
    """A malformed/self-contradictory input -- an unrecognised type on a
    known fact key, an unrecognised `declared_scope` value, or `project_
    evidence` supplied with no non-empty `source` citation. Raised rather
    than silently coerced or dropped, per the Evidence Truth Rule."""


# ===========================================================================
# The 8-value scope taxonomy
# ===========================================================================

SCOPE_PORT_LOCAL = "PORT_LOCAL"
SCOPE_FUNCTION_LOCAL = "FUNCTION_LOCAL"
SCOPE_BLOCK_LOCAL = "BLOCK_LOCAL"
SCOPE_CROSS_PORT = "CROSS_PORT"
SCOPE_DMA_PATH = "DMA_PATH"
SCOPE_MEMORY_PATH = "MEMORY_PATH"
SCOPE_INTERRUPT_PATH = "INTERRUPT_PATH"
SCOPE_END_TO_END = "END_TO_END"

#: Every legal scope value, in this task's own stated order (documentation
#: order -- classification precedence is the separate `SCOPE_PRECEDENCE`).
SCOPE_VALUES: Tuple[str, ...] = (
    SCOPE_PORT_LOCAL, SCOPE_FUNCTION_LOCAL, SCOPE_BLOCK_LOCAL, SCOPE_CROSS_PORT,
    SCOPE_DMA_PATH, SCOPE_MEMORY_PATH, SCOPE_INTERRUPT_PATH, SCOPE_END_TO_END,
)

#: One-line definitions, so a reader of a rendered report does not have to
#: come back to this docstring to know what a value means.
SCOPE_DEFINITIONS: Dict[str, str] = {
    SCOPE_PORT_LOCAL: "Compares transactions observed at a single physical port/interface only.",
    SCOPE_FUNCTION_LOCAL: "Compares within one internal functional unit (e.g. one queue/engine), independent of any specific port.",
    SCOPE_BLOCK_LOCAL: "Compares within one IP block/subsystem boundary, potentially spanning several of that block's own ports/functions.",
    SCOPE_CROSS_PORT: "Compares transactions that cross between two or more distinct physical ports/interfaces.",
    SCOPE_DMA_PATH: "Compares along a DMA transfer path (source, DMA engine, destination), which may itself cross multiple physical interfaces.",
    SCOPE_MEMORY_PATH: "Compares along a memory-access path (master -> memory controller -> memory).",
    SCOPE_INTERRUPT_PATH: "Compares a register-write / configuration event against its resulting interrupt assertion.",
    SCOPE_END_TO_END: "Compares from stimulus injection through to the final observed system-level effect.",
}

#: Classification precedence, most architecturally specific first. A compare
#: description whose facts satisfy more than one scope is named by whichever
#: comes FIRST here, never the least-specific match.
SCOPE_PRECEDENCE: Tuple[str, ...] = (
    SCOPE_END_TO_END, SCOPE_INTERRUPT_PATH, SCOPE_DMA_PATH, SCOPE_MEMORY_PATH,
    SCOPE_CROSS_PORT, SCOPE_PORT_LOCAL, SCOPE_FUNCTION_LOCAL, SCOPE_BLOCK_LOCAL,
)

# ===========================================================================
# Statuses and the SyoSil-default role
# ===========================================================================

#: A real placement fact (or an evidence-cited override) decided the scope.
STATUS_CLASSIFIED = "CLASSIFIED"
#: No placement fact was found anywhere, but the explicit SyoSil/similar
#: VIP-adjacent default rule fired instead of reporting UNVERIFIABLE.
STATUS_DEFAULTED = "DEFAULTED"
#: No placement fact was found and no default rule applies -- honestly
#: unknown, never a guess.
STATUS_UNVERIFIABLE = "UNVERIFIABLE"

STATUS_VALUES: Tuple[str, ...] = (STATUS_CLASSIFIED, STATUS_DEFAULTED, STATUS_UNVERIFIABLE)

#: The role a SyoSil/similar component is defaulted to when its own
#: description carries no placement signal. Deliberately NOT a member of
#: `SCOPE_VALUES` -- it is a statement about the component's ARCHITECTURAL
#: ROLE (a reusable queue/compare engine), not an asserted placement.
ROLE_QUEUE_COMPARE_ENGINE_DEFAULT = "QUEUE_COMPARE_ENGINE_DEFAULT"

#: Fixed, explicit markers for "SyoSil/similar VIP-adjacent compare engine".
#: Matched case-insensitively against caller-declared vendor/kind/name
#: strings only -- never inferred from a free-text description.
SYOSIL_NAME_MARKERS: Tuple[str, ...] = ("syosil", "syoscb")

#: Fact keys read from a `compare_description` / `project_evidence` dict, in
#: `SCOPE_PRECEDENCE` order (the port-count pair is handled separately since
#: it carries an integer rather than a bool).
_BOOL_FACT_PRECEDENCE: Tuple[Tuple[str, str], ...] = (
    ("spans_end_to_end_stimulus_to_system_effect", SCOPE_END_TO_END),
    ("spans_interrupt_chain", SCOPE_INTERRUPT_PATH),
    ("spans_dma_engine", SCOPE_DMA_PATH),
    ("spans_memory_controller", SCOPE_MEMORY_PATH),
)
_BOOL_FACT_PRECEDENCE_AFTER_PORT_COUNT: Tuple[Tuple[str, str], ...] = (
    ("single_function_unit", SCOPE_FUNCTION_LOCAL),
    ("block_local", SCOPE_BLOCK_LOCAL),
)


@dataclass
class ScopeClassification:
    """The result of `classify_scoreboard_scope()`. Every field is present
    on every result, including the honest-negative case, so a caller never
    has to guess which fields apply."""

    status: str
    scope: Optional[str]
    role: Optional[str]
    matched_fact: Optional[str]
    source: str
    is_vip_adjacent_compare_engine: bool
    vip_adjacent_reason: str
    default_rule_applicable: bool
    default_rule_applied: bool
    default_rule_overridden_by_evidence: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ===========================================================================
# Fact extraction (shared by compare_description and project_evidence)
# ===========================================================================

def _require_bool_or_none(value: Any, key: str) -> Optional[bool]:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ScoreboardPlacementScopeError(
            f"'{key}' must be a bool or None, got {type(value).__name__!r}"
        )
    return value


def extract_scope_signal(data: Optional[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """Return `(scope, matched_fact_key)` for the first fact in `data` that
    resolves a scope, in `SCOPE_PRECEDENCE` order, or `None` if `data`
    carries no recognised, truthy placement fact. Raises
    `ScoreboardPlacementScopeError` on a malformed fact rather than
    silently ignoring it. A direct `declared_scope` key, if present and
    non-None, wins over every derived fact and must be one of
    `SCOPE_VALUES`.
    """
    if not data:
        return None
    if not isinstance(data, dict):
        raise ScoreboardPlacementScopeError(
            f"expected a dict of duck-typed facts, got {type(data).__name__!r}"
        )

    declared = data.get("declared_scope")
    if declared is not None:
        if declared not in SCOPE_VALUES:
            raise ScoreboardPlacementScopeError(
                f"'declared_scope' {declared!r} is not a recognised scope value; "
                f"must be one of {SCOPE_VALUES}"
            )
        return (declared, "declared_scope")

    for key, scope in _BOOL_FACT_PRECEDENCE:
        v = _require_bool_or_none(data.get(key), key)
        if v:
            return (scope, key)

    port_count = data.get("port_count")
    if port_count is not None:
        if not isinstance(port_count, int) or isinstance(port_count, bool):
            raise ScoreboardPlacementScopeError(
                f"'port_count' must be an int or None, got {type(port_count).__name__!r}"
            )
        if port_count < 0:
            raise ScoreboardPlacementScopeError("'port_count' must be >= 0")
        if port_count >= 2:
            return (SCOPE_CROSS_PORT, "port_count")
        if port_count == 1:
            return (SCOPE_PORT_LOCAL, "port_count")
        # port_count == 0 carries no placement signal; fall through.

    for key, scope in _BOOL_FACT_PRECEDENCE_AFTER_PORT_COUNT:
        v = _require_bool_or_none(data.get(key), key)
        if v:
            return (scope, key)

    return None


def detect_vip_adjacent_compare_engine(compare_description: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Is `compare_description` a declared SyoSil/similar VIP-adjacent
    compare-engine component? Fixed, explicit checks only -- an explicit
    `vip_adjacent_compare_engine_declared: true` flag (the "similar"
    escape hatch for a component not literally named SyoSil), or a
    `component_vendor`/`component_kind`/`component_name` string containing
    one of `SYOSIL_NAME_MARKERS` case-insensitively. Never inferred from
    prose in any other field.
    """
    if not compare_description:
        return False, "no compare_description supplied"
    if not isinstance(compare_description, dict):
        raise ScoreboardPlacementScopeError(
            f"expected a dict of duck-typed facts, got {type(compare_description).__name__!r}"
        )

    if compare_description.get("vip_adjacent_compare_engine_declared") is True:
        return True, "caller explicitly declared vip_adjacent_compare_engine_declared=True"

    for key in ("component_vendor", "component_kind", "component_name"):
        value = compare_description.get(key)
        if isinstance(value, str):
            lowered = value.lower()
            for marker in SYOSIL_NAME_MARKERS:
                if marker in lowered:
                    return True, f"'{key}' contains marker '{marker}' ({value!r})"

    return False, "no SyoSil/similar VIP-adjacent marker declared"


# ===========================================================================
# Classification
# ===========================================================================

def classify_scoreboard_scope(
    compare_description: Optional[Dict[str, Any]],
    project_evidence: Optional[Dict[str, Any]] = None,
) -> ScopeClassification:
    """Classify a scoreboard's placement scope from `compare_description`
    (generic, duck-typed facts about what it compares -- see module
    docstring for the recognised keys), falling back to `project_evidence`
    (same fact shape, PLUS a required non-empty `source` citation) when the
    description itself carries no placement signal, and finally to the
    explicit SyoSil/similar-VIP-adjacent default rule.

    Precedence: `compare_description`'s own facts always win when present.
    Only when the description carries NO placement fact is `project_
    evidence` consulted; only when NEITHER carries one AND the component is
    a declared SyoSil/similar VIP-adjacent compare engine does the default
    rule fire. Anything else is `STATUS_UNVERIFIABLE`.
    """
    if compare_description is not None and not isinstance(compare_description, dict):
        raise ScoreboardPlacementScopeError(
            f"compare_description must be a dict or None, got {type(compare_description).__name__!r}"
        )
    if project_evidence is not None and not isinstance(project_evidence, dict):
        raise ScoreboardPlacementScopeError(
            f"project_evidence must be a dict or None, got {type(project_evidence).__name__!r}"
        )

    is_vip_adjacent, vip_adjacent_reason = detect_vip_adjacent_compare_engine(compare_description)

    desc_signal = extract_scope_signal(compare_description)
    if desc_signal is not None:
        scope, matched = desc_signal
        return ScopeClassification(
            status=STATUS_CLASSIFIED,
            scope=scope,
            role=(ROLE_QUEUE_COMPARE_ENGINE_DEFAULT if is_vip_adjacent else None),
            matched_fact=matched,
            source="compare_description",
            is_vip_adjacent_compare_engine=is_vip_adjacent,
            vip_adjacent_reason=vip_adjacent_reason,
            default_rule_applicable=is_vip_adjacent,
            default_rule_applied=False,
            default_rule_overridden_by_evidence=False,
            reason=(
                f"classified {scope} from compare_description field '{matched}'"
                + (" (component is also a declared VIP-adjacent compare engine, "
                   "but its own placement fact takes precedence over the default rule)"
                   if is_vip_adjacent else "")
            ),
        )

    ev_signal = None
    if project_evidence:
        cited_source = project_evidence.get("source")
        if not isinstance(cited_source, str) or not cited_source.strip():
            raise ScoreboardPlacementScopeError(
                "project_evidence was supplied but carries no non-empty 'source' citation -- "
                "an uncited override is not real project evidence"
            )
        ev_signal = extract_scope_signal(project_evidence)

    if ev_signal is not None:
        scope, matched = ev_signal
        cited_source = project_evidence.get("source")
        return ScopeClassification(
            status=STATUS_CLASSIFIED,
            scope=scope,
            role=(ROLE_QUEUE_COMPARE_ENGINE_DEFAULT if is_vip_adjacent else None),
            matched_fact=matched,
            source="project_evidence",
            is_vip_adjacent_compare_engine=is_vip_adjacent,
            vip_adjacent_reason=vip_adjacent_reason,
            default_rule_applicable=is_vip_adjacent,
            default_rule_applied=False,
            default_rule_overridden_by_evidence=is_vip_adjacent,
            reason=(
                f"compare_description carried no placement fact; classified {scope} from "
                f"project_evidence field '{matched}' (cited: {cited_source!r})"
                + (" -- this overrides the SyoSil/similar default rule" if is_vip_adjacent else "")
            ),
        )

    if is_vip_adjacent:
        return ScopeClassification(
            status=STATUS_DEFAULTED,
            scope=None,
            role=ROLE_QUEUE_COMPARE_ENGINE_DEFAULT,
            matched_fact=None,
            source="syosil_default_rule",
            is_vip_adjacent_compare_engine=True,
            vip_adjacent_reason=vip_adjacent_reason,
            default_rule_applicable=True,
            default_rule_applied=True,
            default_rule_overridden_by_evidence=False,
            reason=(
                "compare_description carried no scope-placement fact and no project_evidence "
                f"was supplied to show otherwise, so the explicit SyoSil/similar-VIP-adjacent "
                f"default rule fired ({vip_adjacent_reason}): defaulting to a generic "
                f"{ROLE_QUEUE_COMPARE_ENGINE_DEFAULT} role with no committed placement scope, "
                "rather than guessing one of the 8 scope values."
            ),
        )

    return ScopeClassification(
        status=STATUS_UNVERIFIABLE,
        scope=None,
        role=None,
        matched_fact=None,
        source="none",
        is_vip_adjacent_compare_engine=False,
        vip_adjacent_reason=vip_adjacent_reason,
        default_rule_applicable=False,
        default_rule_applied=False,
        default_rule_overridden_by_evidence=False,
        reason=(
            "no scope-placement fact was found in compare_description, no project_evidence was "
            "supplied, and no SyoSil/similar-VIP-adjacent default rule applies (component is not "
            "declared VIP-adjacent) -- reporting UNVERIFIABLE rather than guessing a scope."
        ),
    )


# ===========================================================================
# CLI front door -- no dv-harness verb (cli.py is out of this task's scope)
# ===========================================================================

def execute_verb(argv: Optional[list] = None) -> Tuple[int, Dict[str, Any], str]:
    parser = argparse.ArgumentParser(prog="scoreboard_placement_scope")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("scopes", help="list the 8 scope values and their definitions")

    p_classify = sub.add_parser("classify", help="classify a scoreboard's placement scope")
    p_classify.add_argument("--description", required=True, help="path to a JSON file of compare_description facts")
    p_classify.add_argument("--evidence", help="path to a JSON file of project_evidence facts (requires a 'source' key)")
    p_classify.add_argument("--json", action="store_true", help="print machine-readable JSON only")

    args = parser.parse_args(argv)

    if args.verb == "scopes":
        result = {
            "scope_values": list(SCOPE_VALUES),
            "precedence": list(SCOPE_PRECEDENCE),
            "definitions": SCOPE_DEFINITIONS,
        }
        text = json.dumps(result, indent=2)
        return 0, result, text

    with open(args.description, "r", encoding="utf-8") as f:
        compare_description = json.load(f)
    project_evidence = None
    if args.evidence:
        with open(args.evidence, "r", encoding="utf-8") as f:
            project_evidence = json.load(f)

    try:
        classification = classify_scoreboard_scope(compare_description, project_evidence)
    except ScoreboardPlacementScopeError as exc:
        result = {"error": str(exc)}
        return 2, result, json.dumps(result, indent=2)

    result = classification.to_dict()
    if args.json:
        text = json.dumps(result, indent=2)
    else:
        lines = [
            f"status: {classification.status}",
            f"scope: {classification.scope}",
            f"role: {classification.role}",
            f"reason: {classification.reason}",
        ]
        text = "\n".join(lines)

    if classification.status == STATUS_CLASSIFIED:
        exit_code = 0
    elif classification.status == STATUS_DEFAULTED:
        exit_code = 1
    else:
        exit_code = 2
    return exit_code, result, text


def main(argv: Optional[list] = None) -> int:
    exit_code, _result, text = execute_verb(argv)
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
