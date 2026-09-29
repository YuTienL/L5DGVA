"""dv_harness/system_scoreboard_ir.py -- SystemScoreboardIR: a SYSTEM-SCOPE
record of how per-subsystem scoreboards COMPOSE across a multi-subsystem
project. Answers, per declared cross-subsystem interaction: does this
interaction need a cross-subsystem/end-to-end scoreboard at all, and if so
does one already exist that actually covers it -- never generating any
scoreboard content itself.

REUSE SEARCH PERFORMED FIRST (this task's own rule 4)
------------------------------------------------------
Grepped `dv_harness/` for `SystemScoreboardIR`/`system_scoreboard_ir` and for
`end_to_end_scoreboard`/`cross_subsystem_scenarios`/`system_coverage`/
`probe_composer_boundary` before writing a line here.

Two real, closely-adjacent mechanisms exist and are DELIBERATELY not what
this module is:
- `verification_architecture.ScoreboardIR` is PER-SUBSYSTEM: it extends
  `connectivity.generate_scoreboard_entry()`'s own `data_integrity_scoreboard`
  shape with structural comparability evidence for ONE scoreboard inside ONE
  subsystem's own environment. It has no notion of a SET of subsystems, no
  notion of an interaction crossing a subsystem boundary, and no notion of
  "does an end-to-end scoreboard exist for this system at all". This module
  answers exactly that different, higher-altitude question, and never
  imports `verification_architecture.py` -- a per-subsystem `ScoreboardIR`'s
  own `.to_dict()` output, if a caller has one, is accepted here only as a
  generic, duck-typed `existing_scoreboards` entry (see below), never as a
  typed dependency.
- `uvm_generator/soc_environment_composer.end_to_end_scoreboard()` is a
  GENERATION stub that deliberately raises `NotImplementedError` on purpose
  (see that module's own docstring and `system_scheduling_plan.
  probe_composer_boundary()`, which calls it to keep that boundary a checked
  fact rather than a comment): cross-subsystem scoreboard COMPARE LOGIC is
  genuine protocol-behaviour content this harness has no primary source to
  generate from generically. This module never crosses that boundary either
  -- it never emits a scoreboard, a compare-key schema, or any UVM/SV
  content. It only ANALYSES whether such content is architecturally NEEDED
  and, if so, whether something claiming to be it has already been declared
  -- the analysis `soc_environment_composer.py`'s own stub explicitly leaves
  for "a future per-composition-session agent... to supply from real
  per-subsystem VIP/DUT evidence".

WHAT THIS MODULE REUSES, LITERALLY
------------------------------------
`scoreboard_placement_scope.py`'s 8-value placement-scope taxonomy
(`SCOPE_VALUES`/`SCOPE_PRECEDENCE`/`SCOPE_DEFINITIONS`) and its evidence-
gated classifier `classify_scoreboard_scope()` are IMPORTED and CALLED here,
never re-typed. That module is a stable, standalone, already-completed
mechanism (no imports of its own, and untouched for the duration of this
task's own build) -- reusing it directly, rather than re-deriving a second
copy of the same 8 constants, is what "reusing scoreboard_placement_scope.py's
8-value taxonomy at the system level" means literally: this module applies
the identical scope classifier to TWO different kinds of caller-declared
fact -- (1) a cross-subsystem INTERACTION's own required compare scope, and
(2) an ALREADY-DECLARED scoreboard's own actual compare scope -- and then
asks whether (2) satisfies (1).

THE COMPOSITION QUESTION, PRECISELY
--------------------------------------
A caller declares `system_interactions`: real, cited facts about where two
(or more) subsystems' own transaction streams actually interact (a shared
DMA engine, a shared memory controller, a shared interrupt chain, an
explicit end-to-end stimulus-to-system-effect claim, or a direct
`declared_scope`) -- the SAME fact vocabulary `scoreboard_placement_scope.
classify_scoreboard_scope()`'s own `compare_description` already recognises,
because "what scope of compare does this NEED" and "what scope of compare
does THIS scoreboard perform" are the same question asked of two different
subjects. A caller separately declares `existing_scoreboards`: real, cited
facts about scoreboards that already exist somewhere in the composed system
(per-subsystem OR genuinely cross-subsystem), each naming which subsystems
it actually covers (`owning_subsystems`).

For each interaction, `build_system_scoreboard_ir()`:
1. Classifies the interaction's own REQUIRED scope via
   `classify_scoreboard_scope()` -- never guessed from a subsystem name or
   protocol family, exactly as that module's own Evidence Truth Rule
   discipline requires.
2. Refuses (as a reported `SCOPE_CONTRADICTION` finding, never silently
   accepted) an interaction whose own declared facts resolve to a
   PORT_LOCAL/FUNCTION_LOCAL/BLOCK_LOCAL scope -- a genuinely
   multi-subsystem interaction cannot, by the taxonomy's own definitions,
   be one of the three single-block-local scopes; a caller's facts saying
   otherwise are a real data-quality defect worth surfacing, not a fact to
   trust blindly.
3. Searches `existing_scoreboards` for one whose `owning_subsystems` is a
   real superset of the interaction's own subsystem set AND whose own
   classified scope either matches the required scope EXACTLY or is
   `SCOPE_END_TO_END` -- the ONE legitimate subsumption this module
   recognises, because `SCOPE_END_TO_END` is defined (see
   `scoreboard_placement_scope.SCOPE_DEFINITIONS`) as comparing "from
   stimulus injection through to the final observed system-level effect",
   which by that definition already spans any narrower named path. No
   other scope is ever treated as covering a different one -- a
   DMA_PATH-scoped scoreboard never counts as covering an
   INTERRUPT_PATH-scoped requirement, and vice versa.
4. Reports one of four honest, never-collapsed composition statuses per
   interaction: `COVERED` (a real covering scoreboard was found),
   `GAP_NO_COVERING_SCOREBOARD` (a real requirement exists and nothing
   covers it), `REQUIREMENT_UNVERIFIABLE` (the interaction's own facts
   carry no recognised placement-scope signal at all -- honestly unknown
   what is even needed, never assumed covered), `SCOPE_CONTRADICTION`
   (point 2 above).

A project declaring NO cross-subsystem interactions at all (a single-
subsystem project, or a multi-subsystem one for which nobody has yet
supplied interaction evidence) reports the whole IR `NOT_APPLICABLE` --
never a vacuous `COMPLETE` over zero interactions, and never a fabricated
`INCOMPLETE` either.

DELIBERATELY BOUNDED, STATED RATHER THAN IMPLIED CLOSED
-----------------------------------------------------------
(1) This module DISCOVERS no interaction, no scoreboard, and no subsystem
    of its own -- `system_interactions`/`existing_scoreboards` are entirely
    caller-declared, generic, duck-typed facts (a plain dict), the same
    "accept the fact rather than invent one" discipline several sibling
    modules built alongside this one already apply to a fact their own real
    evidence store cannot supply on its own. A real project's own
    `system_topology_analysis.py` (shared-memory windows, DMA-implying
    address paths, interrupt-line sharing) or `system_resource_inventory.py`
    output is the natural real source for `system_interactions`, and a
    project's own `env.manifest.json`/generated scoreboard plan the natural
    real source for `existing_scoreboards` -- neither is imported here, so
    this module stays usable regardless of which of those a caller already
    has reduced to this shape.
(2) It never arbitrates a genuinely conflicting fact (two existing-
    scoreboard declarations disagreeing about their own scope, say) -- that
    stays each caller's own evidence-gathering problem;
    `classify_scoreboard_scope()`'s own `ScoreboardPlacementScopeError` is
    allowed to propagate rather than being silently swallowed.
(3) It never emits a scoreboard, a compare-key schema, or any SV/UVM
    content -- `soc_environment_composer.end_to_end_scoreboard()`'s own
    stub boundary is untouched and uncrossed. It decides, approves and
    arbitrates nothing beyond its own four-status-per-interaction report:
    no build, no job, no approval, and there is deliberately no stage gate
    -- a `SystemScoreboardIR` is an input to a human's system-composition
    review, never a substitute for one.
(4) There is no `dv-harness` CLI verb and `gates.py`/`cli.py`/`CLAUDE.md`
    were not touched, per this task's own file-safety scope (rule 8: avoid
    editing either file when it is under heavy edit pressure from many
    concurrent items in this same batch). Front door is
    `python -m dv_harness.system_scoreboard_ir scopes|build`.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dv_harness.scoreboard_placement_scope import (
    SCOPE_VALUES,
    SCOPE_PRECEDENCE,
    SCOPE_DEFINITIONS,
    SCOPE_PORT_LOCAL,
    SCOPE_FUNCTION_LOCAL,
    SCOPE_BLOCK_LOCAL,
    SCOPE_END_TO_END,
    STATUS_CLASSIFIED,
    STATUS_DEFAULTED,
    STATUS_UNVERIFIABLE,
    classify_scoreboard_scope,
    ScopeClassification,
    ScoreboardPlacementScopeError,
)


class SystemScoreboardIRError(ValueError):
    """A malformed `system_interactions`/`existing_scoreboards` declaration
    -- a missing identity, fewer than two subsystems on an interaction, or
    a missing evidence citation. Raised rather than silently dropped or
    defaulted, per the Evidence Truth Rule."""


# ===========================================================================
# This module's OWN vocabulary -- distinct from `dv_harness.models.Status`,
# checked at call time by `assert_no_verification_verdict_vocabulary()`
# rather than merely claimed.
# ===========================================================================

COMPOSITION_COVERED = "COVERED"
COMPOSITION_GAP = "GAP_NO_COVERING_SCOREBOARD"
COMPOSITION_UNVERIFIABLE = "REQUIREMENT_UNVERIFIABLE"
COMPOSITION_CONTRADICTION = "SCOPE_CONTRADICTION"

COMPOSITION_STATUSES: Tuple[str, ...] = (
    COMPOSITION_COVERED, COMPOSITION_GAP, COMPOSITION_UNVERIFIABLE, COMPOSITION_CONTRADICTION,
)

#: A `NON_COVERING` entry-level status is anything that is not COVERED --
#: used to fold the whole-IR overall status.
_NON_COVERING_STATUSES = frozenset({COMPOSITION_GAP, COMPOSITION_UNVERIFIABLE, COMPOSITION_CONTRADICTION})

OVERALL_COMPLETE = "SYSTEM_SCOREBOARD_COMPOSITION_COMPLETE"
OVERALL_INCOMPLETE = "SYSTEM_SCOREBOARD_COMPOSITION_INCOMPLETE"
OVERALL_NOT_APPLICABLE = "NOT_APPLICABLE"

OVERALL_STATUSES: Tuple[str, ...] = (OVERALL_COMPLETE, OVERALL_INCOMPLETE, OVERALL_NOT_APPLICABLE)

#: The three single-block-local scopes -- a genuinely multi-subsystem
#: interaction resolving to one of these is a data-quality contradiction,
#: never a legitimate requirement.
_LOCAL_ONLY_SCOPES = frozenset({SCOPE_PORT_LOCAL, SCOPE_FUNCTION_LOCAL, SCOPE_BLOCK_LOCAL})


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status tokens must share no token with
    `dv_harness.models.Status` -- the same collision guard several sibling
    modules in this project already run against their own vocabularies.
    Imported lazily so a caller that only wants the pure classification
    functions never pays for pulling in the engine's stage-verdict model."""
    from dv_harness.models import Status
    verdict_tokens = {member.value for member in Status}
    own_tokens = set(COMPOSITION_STATUSES) | set(OVERALL_STATUSES)
    collided = verdict_tokens & own_tokens
    if collided:
        raise SystemScoreboardIRError(
            f"system_scoreboard_ir vocabulary collides with dv_harness.models.Status: {sorted(collided)}"
        )


def known_scope_values() -> Tuple[str, ...]:
    """The reused 8-value taxonomy, verbatim, for a caller/report that wants
    to state which scopes this module recognises without re-deriving them."""
    return SCOPE_VALUES


# ===========================================================================
# Records
# ===========================================================================

@dataclass
class SystemScoreboardEntry:
    """One cross-subsystem interaction's composition verdict."""

    interaction_id: str
    subsystems: List[str]
    needs_cross_subsystem_scoreboard: bool
    required_scope: Optional[str]
    required_scope_status: str
    required_scope_reason: str
    covering_scoreboard_ids: List[str]
    composition_status: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "subsystems": list(self.subsystems),
            "needs_cross_subsystem_scoreboard": self.needs_cross_subsystem_scoreboard,
            "required_scope": self.required_scope,
            "required_scope_status": self.required_scope_status,
            "required_scope_reason": self.required_scope_reason,
            "covering_scoreboard_ids": list(self.covering_scoreboard_ids),
            "composition_status": self.composition_status,
            "reason": self.reason,
        }

    def to_row(self) -> Dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "subsystems": ", ".join(self.subsystems),
            "needs_cross_subsystem_scoreboard": "yes" if self.needs_cross_subsystem_scoreboard else "no",
            "required_scope": self.required_scope or "(unresolved)",
            "composition_status": self.composition_status,
            "covering_scoreboard_ids": ", ".join(self.covering_scoreboard_ids) or "(none)",
            "reason": self.reason,
        }


@dataclass
class SystemScoreboardIR:
    """The system-scope record: how every declared cross-subsystem
    interaction's own scoreboard-composition question resolved, plus one
    worst-wins overall verdict."""

    entries: List[SystemScoreboardEntry] = field(default_factory=list)
    overall_status: str = OVERALL_NOT_APPLICABLE
    overall_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "overall_status": self.overall_status,
            "overall_reason": self.overall_reason,
            "scope_taxonomy": list(SCOPE_VALUES),
        }


# ===========================================================================
# Per-fact helpers
# ===========================================================================

def _require_str(value: Any, field_name: str, item_desc: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemScoreboardIRError(
            f"{item_desc}: '{field_name}' must be a non-empty string, got {value!r}"
        )
    return value


def _require_subsystem_list(value: Any, item_desc: str, *, minimum: int = 2) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise SystemScoreboardIRError(
            f"{item_desc}: 'subsystems'/'owning_subsystems' must be a list of non-empty strings, got {value!r}"
        )
    deduped = list(dict.fromkeys(value))
    if len(deduped) < minimum:
        raise SystemScoreboardIRError(
            f"{item_desc}: requires at least {minimum} distinct subsystems, got {deduped!r}"
        )
    return deduped


def _classify(compare_description: Dict[str, Any], item_desc: str) -> ScopeClassification:
    try:
        return classify_scoreboard_scope(compare_description, project_evidence=None)
    except ScoreboardPlacementScopeError as exc:
        raise SystemScoreboardIRError(f"{item_desc}: {exc}") from exc


def classify_system_interaction_requirement(interaction: Dict[str, Any]) -> Tuple[List[str], ScopeClassification]:
    """Validate one `system_interactions` entry and classify its own
    REQUIRED compare scope via the reused `classify_scoreboard_scope()`.
    Returns `(subsystems, classification)`. Raises `SystemScoreboardIRError`
    on a malformed entry (no identity, fewer than 2 subsystems, or no
    evidence that these subsystems actually interact -- distinct from, and
    checked before, whether that interaction's own SCOPE facts are
    present)."""
    if not isinstance(interaction, dict):
        raise SystemScoreboardIRError(
            f"expected a dict describing a system interaction, got {type(interaction).__name__!r}"
        )
    interaction_id = _require_str(interaction.get("interaction_id"), "interaction_id", "system_interactions entry")
    item_desc = f"system_interactions[{interaction_id!r}]"
    subsystems = _require_subsystem_list(interaction.get("subsystems"), item_desc)
    _require_str(interaction.get("evidence"), "evidence", item_desc)
    classification = _classify(interaction, item_desc)
    return subsystems, classification


def classify_existing_scoreboard(scoreboard: Dict[str, Any]) -> Tuple[str, List[str], ScopeClassification]:
    """Validate one `existing_scoreboards` entry and classify its own
    ACTUAL compare scope. Returns `(scoreboard_id, owning_subsystems,
    classification)`. Raises `SystemScoreboardIRError` on a malformed entry."""
    if not isinstance(scoreboard, dict):
        raise SystemScoreboardIRError(
            f"expected a dict describing an existing scoreboard, got {type(scoreboard).__name__!r}"
        )
    scoreboard_id = _require_str(scoreboard.get("scoreboard_id"), "scoreboard_id", "existing_scoreboards entry")
    item_desc = f"existing_scoreboards[{scoreboard_id!r}]"
    owning_subsystems = _require_subsystem_list(
        scoreboard.get("owning_subsystems"), item_desc, minimum=1
    )
    _require_str(scoreboard.get("evidence"), "evidence", item_desc)
    classification = _classify(scoreboard, item_desc)
    return scoreboard_id, owning_subsystems, classification


def _existing_scope_satisfies(existing_scope: Optional[str], required_scope: Optional[str]) -> bool:
    """The ONE legitimate subsumption this module recognises: an
    END_TO_END-scoped scoreboard (defined as comparing from stimulus
    injection through to the final observed system-level effect) always
    satisfies a narrower or unresolved requirement. Every other pairing
    must match EXACTLY -- a DMA_PATH-scoped scoreboard never covers an
    INTERRUPT_PATH-scoped requirement, and an existing scoreboard whose own
    scope this module could not classify (`None`) never covers anything."""
    if existing_scope is None:
        return False
    if existing_scope == SCOPE_END_TO_END:
        return True
    return required_scope is not None and existing_scope == required_scope


# ===========================================================================
# Composition
# ===========================================================================

def build_system_scoreboard_ir(
    system_interactions: Optional[List[Dict[str, Any]]],
    existing_scoreboards: Optional[List[Dict[str, Any]]] = None,
) -> SystemScoreboardIR:
    """Build the whole-system `SystemScoreboardIR`.

    `system_interactions` and `existing_scoreboards` are both plain lists
    of dicts -- see the module docstring for the recognised fields. Neither
    is discovered here; both are entirely caller-declared, cited facts.
    """
    if system_interactions is None:
        system_interactions = []
    if existing_scoreboards is None:
        existing_scoreboards = []
    if not isinstance(system_interactions, list):
        raise SystemScoreboardIRError(
            f"system_interactions must be a list, got {type(system_interactions).__name__!r}"
        )
    if not isinstance(existing_scoreboards, list):
        raise SystemScoreboardIRError(
            f"existing_scoreboards must be a list, got {type(existing_scoreboards).__name__!r}"
        )

    if not system_interactions:
        return SystemScoreboardIR(
            entries=[],
            overall_status=OVERALL_NOT_APPLICABLE,
            overall_reason=(
                "no system_interactions were declared -- either this is a single-subsystem "
                "project with no cross-subsystem scoreboard-composition question to ask, or "
                "no interaction evidence has been supplied yet. Reporting NOT_APPLICABLE rather "
                "than a vacuous COMPLETE or a fabricated INCOMPLETE."
            ),
        )

    # Classify every existing scoreboard once, up front, so many
    # interactions can reuse the same classification without re-deriving it.
    classified_scoreboards: List[Tuple[str, List[str], ScopeClassification]] = [
        classify_existing_scoreboard(sb) for sb in existing_scoreboards
    ]

    entries: List[SystemScoreboardEntry] = []
    seen_ids: set = set()
    for interaction in system_interactions:
        subsystems, req = classify_system_interaction_requirement(interaction)
        interaction_id = interaction["interaction_id"]
        if interaction_id in seen_ids:
            raise SystemScoreboardIRError(
                f"duplicate interaction_id {interaction_id!r} in system_interactions"
            )
        seen_ids.add(interaction_id)

        if req.status == STATUS_UNVERIFIABLE:
            entries.append(SystemScoreboardEntry(
                interaction_id=interaction_id,
                subsystems=subsystems,
                needs_cross_subsystem_scoreboard=True,
                required_scope=None,
                required_scope_status=req.status,
                required_scope_reason=req.reason,
                covering_scoreboard_ids=[],
                composition_status=COMPOSITION_UNVERIFIABLE,
                reason=(
                    "this interaction is real (evidenced) but carries no recognised "
                    "placement-scope fact of its own, so what scope of scoreboard it would "
                    "need cannot be determined -- honestly unresolved, never assumed covered."
                ),
            ))
            continue

        if req.scope is not None and req.scope in _LOCAL_ONLY_SCOPES:
            entries.append(SystemScoreboardEntry(
                interaction_id=interaction_id,
                subsystems=subsystems,
                needs_cross_subsystem_scoreboard=False,
                required_scope=req.scope,
                required_scope_status=req.status,
                required_scope_reason=req.reason,
                covering_scoreboard_ids=[],
                composition_status=COMPOSITION_CONTRADICTION,
                reason=(
                    f"this interaction declares {len(subsystems)} distinct subsystems "
                    f"({', '.join(subsystems)}) but its own scope facts classify as "
                    f"{req.scope!r}, one of the single-block-local scopes -- a genuinely "
                    "multi-subsystem interaction cannot legitimately be block/function/"
                    "port-local; this is a data-quality contradiction to resolve, not a "
                    "trustworthy requirement."
                ),
            ))
            continue

        # DEFAULTED (a declared SyoSil/similar compare engine with no
        # resolved scope of its own) or CLASSIFIED into a cross-capable
        # scope -- both genuinely need SOME cross-subsystem scoreboard.
        required_scope = req.scope  # may be None on DEFAULTED
        subsystems_set = set(subsystems)
        covering_ids = [
            sb_id for sb_id, owning, existing_cls in classified_scoreboards
            if subsystems_set.issubset(set(owning))
            and _existing_scope_satisfies(existing_cls.scope, required_scope)
        ]

        if covering_ids:
            reason = (
                f"a real declared scoreboard ({', '.join(covering_ids)}) covers subsystems "
                f"{', '.join(subsystems)} at a scope satisfying this interaction's own "
                f"{required_scope or 'DEFAULTED (unresolved-scope compare engine)'} requirement."
            )
            status = COMPOSITION_COVERED
        else:
            reason = (
                f"this interaction needs a cross-subsystem scoreboard covering subsystems "
                f"{', '.join(subsystems)} at scope {required_scope or 'DEFAULTED (unresolved)'}, "
                "and no declared existing_scoreboards entry covers it -- a real composition "
                "gap, per soc_environment_composer.end_to_end_scoreboard()'s own boundary: "
                "this module reports the gap; it never fabricates the scoreboard."
            )
            status = COMPOSITION_GAP

        entries.append(SystemScoreboardEntry(
            interaction_id=interaction_id,
            subsystems=subsystems,
            needs_cross_subsystem_scoreboard=True,
            required_scope=required_scope,
            required_scope_status=req.status,
            required_scope_reason=req.reason,
            covering_scoreboard_ids=covering_ids,
            composition_status=status,
            reason=reason,
        ))

    non_covering = [e for e in entries if e.composition_status in _NON_COVERING_STATUSES]
    if non_covering:
        overall_status = OVERALL_INCOMPLETE
        overall_reason = (
            f"{len(non_covering)} of {len(entries)} declared interaction(s) are not COVERED "
            f"({', '.join(sorted({e.composition_status for e in non_covering}))}) -- worst-wins: "
            "a single unresolved interaction blocks the whole system's scoreboard-composition "
            "verdict regardless of how many others are COVERED."
        )
    else:
        overall_status = OVERALL_COMPLETE
        overall_reason = (
            f"all {len(entries)} declared cross-subsystem interaction(s) are covered by a real, "
            "cited existing scoreboard at a satisfying scope."
        )

    return SystemScoreboardIR(entries=entries, overall_status=overall_status, overall_reason=overall_reason)


# ===========================================================================
# Rendering
# ===========================================================================

def render_system_scoreboard_markdown(ir: SystemScoreboardIR) -> str:
    """Reuses `connectivity.render_markdown_table()` -- this repo's one
    parameterized table renderer -- rather than a second hand-rolled table
    loop. Imported lazily so a caller wanting only the pure classification
    functions above never needs `connectivity.py` on the import path."""
    from dv_harness.connectivity import render_markdown_table
    columns = [
        ("interaction_id", "Interaction"),
        ("subsystems", "Subsystems"),
        ("needs_cross_subsystem_scoreboard", "Needs Cross-Subsystem SB?"),
        ("required_scope", "Required Scope"),
        ("composition_status", "Status"),
        ("covering_scoreboard_ids", "Covering Scoreboard(s)"),
        ("reason", "Reason"),
    ]
    rows = [e.to_row() for e in ir.entries]
    table = render_markdown_table(columns, rows, empty_note="(no system interactions declared)")
    return (
        f"**Overall: {ir.overall_status}** -- {ir.overall_reason}\n\n"
        f"Reused 8-value scope taxonomy: {', '.join(SCOPE_VALUES)}\n\n"
        f"{table}"
    )


# ===========================================================================
# CLI front door -- no dv-harness verb (cli.py/gates.py are out of scope)
# ===========================================================================

def execute_verb(argv: Optional[list] = None) -> Tuple[int, Dict[str, Any], str]:
    assert_no_verification_verdict_vocabulary()
    parser = argparse.ArgumentParser(prog="system_scoreboard_ir")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("scopes", help="list the reused 8 scope values and their definitions")

    p_build = sub.add_parser("build", help="build the SystemScoreboardIR from declared facts")
    p_build.add_argument("--interactions", required=True,
                          help="path to a JSON file: a list of system_interactions entries")
    p_build.add_argument("--scoreboards",
                          help="path to a JSON file: a list of existing_scoreboards entries")
    p_build.add_argument("--json", action="store_true", help="print machine-readable JSON only")

    args = parser.parse_args(argv)

    if args.verb == "scopes":
        result = {
            "scope_values": list(SCOPE_VALUES),
            "precedence": list(SCOPE_PRECEDENCE),
            "definitions": SCOPE_DEFINITIONS,
        }
        return 0, result, json.dumps(result, indent=2)

    with open(args.interactions, "r", encoding="utf-8") as f:
        system_interactions = json.load(f)
    existing_scoreboards = None
    if args.scoreboards:
        with open(args.scoreboards, "r", encoding="utf-8") as f:
            existing_scoreboards = json.load(f)

    try:
        ir = build_system_scoreboard_ir(system_interactions, existing_scoreboards)
    except SystemScoreboardIRError as exc:
        result = {"error": str(exc)}
        return 2, result, json.dumps(result, indent=2)

    result = ir.to_dict()
    if args.json:
        text = json.dumps(result, indent=2)
    else:
        text = render_system_scoreboard_markdown(ir)

    if ir.overall_status == OVERALL_COMPLETE:
        exit_code = 0
    elif ir.overall_status == OVERALL_NOT_APPLICABLE:
        exit_code = 0
    else:
        exit_code = 1
    return exit_code, result, text


def main(argv: Optional[list] = None) -> int:
    exit_code, _result, text = execute_verb(argv)
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
