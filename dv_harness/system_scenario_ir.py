"""dv_harness/system_scenario_ir.py -- SystemScenarioIR + SystemScenarioGraph: a
typed, per-scenario record over SYS-30's already-planned system-scope scenario
shapes (`system_topology_analysis.plan_system_scenario_model()`), plus a
dependency graph among cross-subsystem scenarios, 2026-09-07.

WHAT THIS IS, AND WHAT IT IS EXPLICITLY NOT
--------------------------------------------
`system_topology_analysis.py`'s SYS-30 half already answers "what SHAPE would a
multi-subsystem scenario have" -- one scenario record per SYS-27-supported flow
or SYS-25-coupled subsystem pair, complete with a PARALLEL/SEQUENTIAL block plan
derived from the SYS-25 pair-safety model and a syntax-derivation record proving
every planned command traces to a real subsystem contract. That module's own
closing paragraph says what it deliberately never becomes: no scenario BODY, no
System command.txt, no parallel-block text, no System Virtual Sequencer. This
module inherits that exact boundary rather than restating a weaker one --
`build_system_scenario_ir()` REFUSES to construct a `SystemScenarioIR` from a
scenario record whose `scenario_body_status` has drifted off
`NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL`, or that carries any
body-shaped key (`scenario_body`, `command_txt`, ...).

What this module adds is exactly the two things SYS-30's own scenario list does
NOT have: (1) a validated, typed wrapper over one scenario record -- so a
consumer reasons about a `SystemScenarioIR`, not a bag of dict keys it has to
re-discover the shape of -- and (2) a DEPENDENCY GRAPH among the scenarios in
one selection: which of them structurally COUPLE (share a participating
subsystem -- a fact SYS-30 already computes and this module only reads back)
and, for a caller-declared execution ORDER plus caller-declared cross-scenario
precondition/postcondition facts, whether that order's dependency chain is
self-consistent.

WHY A NEW MODULE RATHER THAN AN EXTENSION
------------------------------------------
`system_topology_analysis.py` is SYS-28..30 ANALYSIS over one already-planned
selection; it builds the scenario SHAPES and stops there by design (its own
"WHAT THIS MODULE IS NOT" paragraph). Turning those shapes into a typed record a
generator or a human can iterate over, and asking whether a caller-declared
scenario ORDER is dependency-consistent, is a different, later question -- and
answering it needs no new fact about address maps, clock/reset domains or
command routing, only the scenario shapes that module already produced. Adding
it there would blur a module whose entire value is a narrow, three-numbered
(SYS-28/29/30) scope. A repo-wide search before writing this module found no
`SystemScenarioIR`/`SystemScenarioGraph`/`scenario_dependency` anywhere, and
confirmed `pattern_ir_assembly.py`'s own "ScenarioIR" is an unrelated, narrower
per-SUBSYSTEM shape (one scenario's own five `PatternIR` layers), never a
system-scope multi-subsystem scenario record.

REUSE, NOT REINVENTION
-----------------------
* Every `SystemScenarioIR` field not added by this module (participating
  subsystems, the PARALLEL/SEQUENTIAL block plan, the syntax-derivation record,
  the pinned `scenario_body_status`) is READ VERBATIM from a
  `system_topology_analysis.plan_system_scenario_model()` scenario record --
  this module re-derives none of SYS-30's own arithmetic.
* The structural coupling edges are the SAME "do these two scenarios' own
  `participating_subsystems` lists intersect" fact SYS-27's own
  `coupled_subsystem_pairs` summary already surfaces one layer down (see
  `system_scheduling_plan.py`) -- recomputed here directly over the SCENARIO
  records because two scenarios sharing a subsystem is a fact about the
  scenarios in a caller's chosen selection, not only about the underlying
  subsystem pairs SYS-27 examined.
* The dependency-CHAIN check is `pattern_fragment_ir.check_fragment_chain_
  readiness()`, CALLED -- never reimplemented. That function already answers
  exactly this module's question ("given a declared order of fragment-shaped
  items, is each item's unresolved precondition covered by an earlier item's
  postcondition/produced event") for pattern fragments; a `SystemScenarioIR` is
  adapted into that same fragment shape (`_as_fragment_shaped()`) rather than a
  second, scenario-specific graph-walk being written. See that function's own
  docstring: "a purely structural event-graph check... never asserts the
  resulting composed pattern is behaviourally correct" -- the identical
  disclaimer applies here, one level up: this module never claims a
  dependency-consistent scenario ORDER is behaviourally correct, only that its
  declared precondition/postcondition graph is (or is not) self-consistent in
  that order.

EVIDENCE TRUTH RULE, APPLIED HERE
------------------------------------
Nothing in `system_topology_analysis.py`'s SYS-30 scenario shape carries a
produced/consumed EVENT of any kind -- SYS-21's `system_command_ir` entries
have no such field, confirmed by direct search before writing this module. So
a cross-scenario dependency ("scenario B needs subsystem A's own bring-up,
established by scenario A, to have already run") is, honestly, ALWAYS a caller
declaration here, never a mechanical derivation this module performs on its
own -- exactly the same status `pattern_fragment_ir.py`'s own
`declared_preconditions`/`declared_postconditions` parameters already have for
a fact "a human or an upstream tool already knows... but that no event field
in this fragment's commands proves mechanically". Every declared
precondition/postcondition REQUIRES a real, non-empty `reason` citation;
`build_system_scenario_ir()` refuses to construct an IR from one that lacks
it, per the Evidence Truth Rule this whole module otherwise has no
"mechanically derived" half to fall back on.

Those declared preconditions/postconditions are retagged, before being handed
to the reused `check_fragment_chain_readiness()`, with that function's own
`DERIVED_UNRESOLVED_CONSUMED_EVENT` / `DERIVED_UNCONSUMED_PRODUCED_EVENT`
source tags rather than its `DECLARED` tag -- deliberately, because that
function only chain-checks preconditions carrying the former tag (a
`DECLARED` precondition is treated as an already-known-true fact needing no
earlier supplier, which is the wrong reading for a real cross-scenario
ordering dependency). This is not a fabricated derivation claim: it is using
the tag for exactly the meaning its own docstring gives it ("something the
fragment assumes is already true when it starts, that this fragment alone
cannot supply") over a fact this module's own caller declared instead of one
`pattern_fragment_ir.py` derived from a produced/consumed event-set
difference.

The one derivation this module DOES perform on its own -- the subsystem-
coupling edge -- is intentionally NOT read as an ordering dependency: two
scenarios sharing a subsystem does not by itself say which must run first, or
whether they may run concurrently at all (that is SYS-24's shared-resource
scheduling question, already `system_resource_registry.py`'s/
`system_scheduling_plan.py`'s job, not re-derived here). It is reported as its
own, separately-labelled fact (`SHARES_SUBSYSTEMS`) precisely so a reader
never mistakes "these two are related" for "this module decided an order
between them".
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field as _dataclass_field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import pattern_fragment_ir as pfir
from . import system_topology_analysis as sta
from .connectivity import render_markdown_table

SCHEMA_VERSION = "1.0"

#: The pinned scenario-body status every `SystemScenarioIR` must carry,
#: imported rather than re-spelled so this module and
#: `system_topology_analysis.py` can never silently disagree about the one
#: string that proves no scenario body was emitted.
SCENARIO_BODY_STATUS_PINNED = sta.SCENARIO_BODY_NOT_GENERATED

#: The one relationship this module derives on its own (never a human
#: declaration): two scenarios in the same selection name a shared
#: participating subsystem. Deliberately not an ordering verdict -- see the
#: module docstring's closing paragraph.
COUPLING_SHARES_SUBSYSTEMS = "SHARES_SUBSYSTEMS"

#: Reused verbatim from `pattern_fragment_ir.py` -- there is exactly one
#: definition of "is this scenario order's dependency chain self-consistent"
#: in this repository.
CHAIN_STATUSES: tuple = (
    pfir.CHAIN_STATUS_ALL_COVERED,
    pfir.CHAIN_STATUS_HAS_UNCOVERED,
    pfir.CHAIN_STATUS_NO_PRECONDITIONS,
)

#: Keys `assert_no_emitted_artifacts()`-style guards in this repo already treat
#: as proof a scenario BODY was emitted somewhere it should never have been.
_FORBIDDEN_BODY_KEYS: tuple = (
    "scenario_body", "command_txt", "generated_source", "emitted_text", "sequence_body",
)

#: A raw SYS-30 scenario record (see `system_topology_analysis.
#: plan_system_scenario_model()`) must carry all of these before this module
#: will build a typed `SystemScenarioIR` from it.
_REQUIRED_SCENARIO_KEYS: tuple = (
    "scenario_id", "derived_from", "description", "participating_subsystems",
    "cross_subsystem", "command_count", "block_plan", "scenario_body_status",
)


class SystemScenarioIrError(ValueError):
    """Raised on a malformed scenario record, an uncited declared precondition/
    postcondition, a scenario whose body status has drifted off its pinned
    value, or a `PatternFragmentIrError` the reused chain-readiness check
    raised (re-wrapped so this module's own callers see exactly one exception
    type at its boundary, carrying the original `reason`/`detail` verbatim)."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        self.reason = reason
        self.detail = detail or {}
        super().__init__(f"{reason}: {self.detail}")


def _assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status vocabulary (the coupling relationship and the
    reused chain-status values) must never collide with a real stage verdict
    -- the same guard several sibling modules in this repo already run on
    their own domain vocabularies."""
    from . import models

    verdict_values = {s.value for s in models.Status}
    tokens = {COUPLING_SHARES_SUBSYSTEMS, *CHAIN_STATUSES}
    collision = tokens & verdict_values
    if collision:
        raise AssertionError(
            f"system_scenario_ir vocabulary collides with models.Status: {sorted(collision)}")


_assert_no_verification_verdict_vocabulary()


# ===========================================================================
# SystemScenarioIR
# ===========================================================================

@dataclass
class SystemScenarioIR:
    """A validated, typed wrapper over one SYS-30 scenario record. Every field
    not documented below is read VERBATIM from that record; this dataclass
    re-derives none of it."""

    scenario_id: str
    derived_from: str
    description: str
    participating_subsystems: List[str] = _dataclass_field(default_factory=list)
    cross_subsystem: bool = False
    composition_gate_note: str = ""
    command_count: int = 0
    block_plan: list = _dataclass_field(default_factory=list)
    parallel_block_count: int = 0
    sequential_block_count: int = 0
    syntax_derivation: dict = _dataclass_field(default_factory=dict)
    scenario_body_status: str = SCENARIO_BODY_STATUS_PINNED
    #: Caller-declared cross-scenario dependency facts this module never
    #: derives itself -- see the module docstring's Evidence Truth Rule
    #: section. Each entry is `{"event": str, "reason": str, ...}`.
    declared_preconditions: list = _dataclass_field(default_factory=list)
    declared_postconditions: list = _dataclass_field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "derived_from": self.derived_from,
            "description": self.description,
            "participating_subsystems": list(self.participating_subsystems),
            "cross_subsystem": self.cross_subsystem,
            "composition_gate_note": self.composition_gate_note,
            "command_count": self.command_count,
            "block_plan": list(self.block_plan),
            "parallel_block_count": self.parallel_block_count,
            "sequential_block_count": self.sequential_block_count,
            "syntax_derivation": dict(self.syntax_derivation),
            "scenario_body_status": self.scenario_body_status,
            "declared_preconditions": list(self.declared_preconditions),
            "declared_postconditions": list(self.declared_postconditions),
        }


def _validate_condition_entry(entry: Any, kind: str) -> Dict[str, Any]:
    """One caller-declared precondition/postcondition entry. Requires a real,
    non-empty `event` name AND a real, non-empty `reason` citation -- the
    Evidence Truth Rule enforced at construction, not merely documented. Every
    other key on the entry (e.g. a `requires_subsystem` hint) is preserved
    verbatim, never invented."""
    if not isinstance(entry, Mapping):
        raise SystemScenarioIrError(f"{kind}_NOT_A_MAPPING", {"entry": entry})
    event = str(entry.get("event") or "").strip()
    if not event:
        raise SystemScenarioIrError(f"{kind}_MISSING_EVENT", {"entry": dict(entry)})
    reason = str(entry.get("reason") or "").strip()
    if not reason:
        raise SystemScenarioIrError(f"{kind}_MISSING_REASON",
                                     {"entry": dict(entry), "event": event})
    out = dict(entry)
    out["event"] = event
    out["reason"] = reason
    return out


def build_system_scenario_ir(scenario: Mapping[str, Any], *,
                              declared_preconditions: Optional[Sequence[Mapping[str, Any]]] = None,
                              declared_postconditions: Optional[Sequence[Mapping[str, Any]]] = None,
                              ) -> SystemScenarioIR:
    """Build one `SystemScenarioIR` from one raw SYS-30 scenario record.

    Refuses (`SystemScenarioIrError`) rather than silently accepting: a
    non-mapping `scenario`, a scenario missing a required field, a scenario
    whose `scenario_body_status` is not the pinned
    `NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL` value, a scenario carrying
    any body-shaped key, or a declared precondition/postcondition with no
    `event` or no `reason` citation.
    """
    if not isinstance(scenario, Mapping):
        raise SystemScenarioIrError("MALFORMED_SCENARIO_RECORD",
                                     {"type": type(scenario).__name__})
    missing = [k for k in _REQUIRED_SCENARIO_KEYS if k not in scenario]
    if missing:
        raise SystemScenarioIrError("SCENARIO_RECORD_MISSING_FIELDS", {"missing": missing})

    body_status = scenario.get("scenario_body_status")
    if body_status != SCENARIO_BODY_STATUS_PINNED:
        raise SystemScenarioIrError("SCENARIO_BODY_STATUS_NOT_PINNED", {
            "scenario_id": scenario.get("scenario_id"),
            "status": body_status,
            "expected": SCENARIO_BODY_STATUS_PINNED,
        })
    for forbidden in _FORBIDDEN_BODY_KEYS:
        if forbidden in scenario:
            raise SystemScenarioIrError("SCENARIO_BODY_EMITTED", {
                "scenario_id": scenario.get("scenario_id"), "key": forbidden,
            })

    preconditions = [_validate_condition_entry(e, "PRECONDITION")
                      for e in (declared_preconditions or [])]
    postconditions = [_validate_condition_entry(e, "POSTCONDITION")
                       for e in (declared_postconditions or [])]

    return SystemScenarioIR(
        scenario_id=str(scenario["scenario_id"]),
        derived_from=str(scenario["derived_from"]),
        description=str(scenario["description"]),
        participating_subsystems=list(scenario.get("participating_subsystems") or []),
        cross_subsystem=bool(scenario.get("cross_subsystem")),
        composition_gate_note=str(scenario.get("composition_gate_note") or ""),
        command_count=int(scenario.get("command_count") or 0),
        block_plan=list(scenario.get("block_plan") or []),
        parallel_block_count=int(scenario.get("parallel_block_count") or 0),
        sequential_block_count=int(scenario.get("sequential_block_count") or 0),
        syntax_derivation=dict(scenario.get("syntax_derivation") or {}),
        scenario_body_status=body_status,
        declared_preconditions=preconditions,
        declared_postconditions=postconditions,
    )


def build_system_scenario_irs(scenario_model: Any, *,
                               dependency_declarations: Optional[
                                   Mapping[str, Mapping[str, Any]]] = None,
                               ) -> List[SystemScenarioIR]:
    """Build every `SystemScenarioIR` in one SYS-30 scenario model.

    `scenario_model` is either the whole document `plan_system_scenario_model()`
    returns (read via its `scenarios` key) or a bare list of scenario records.
    `dependency_declarations` is an optional `{scenario_id: {"preconditions":
    [...], "postconditions": [...]}}` mapping of real caller-declared
    cross-scenario dependency facts -- a scenario_id absent from it simply
    gets no declared preconditions/postconditions, an honest absence, never an
    error.
    """
    if isinstance(scenario_model, Mapping) and "scenarios" in scenario_model:
        raw_scenarios = list(scenario_model.get("scenarios") or [])
    elif isinstance(scenario_model, (list, tuple)):
        raw_scenarios = list(scenario_model)
    else:
        raise SystemScenarioIrError("UNRECOGNIZED_SCENARIO_MODEL_SHAPE",
                                     {"type": type(scenario_model).__name__})

    declarations = dependency_declarations or {}
    seen_ids: set = set()
    irs: List[SystemScenarioIR] = []
    for raw in raw_scenarios:
        sid = raw.get("scenario_id") if isinstance(raw, Mapping) else None
        decl = declarations.get(sid) or {}
        ir = build_system_scenario_ir(
            raw,
            declared_preconditions=decl.get("preconditions"),
            declared_postconditions=decl.get("postconditions"),
        )
        if ir.scenario_id in seen_ids:
            raise SystemScenarioIrError("DUPLICATE_SCENARIO_ID", {"scenario_id": ir.scenario_id})
        seen_ids.add(ir.scenario_id)
        irs.append(ir)

    irs.sort(key=lambda s: s.scenario_id)
    return irs


# ===========================================================================
# Structural coupling -- derived, never a human declaration
# ===========================================================================

def derive_subsystem_coupling_edges(
        scenarios: Sequence[SystemScenarioIR]) -> List[Dict[str, Any]]:
    """Every pair of distinct scenarios in `scenarios` whose own
    `participating_subsystems` lists intersect, as a `SHARES_SUBSYSTEMS` edge
    naming the shared subsystem(s). Purely structural and derived here from
    facts SYS-30 already computed -- never a human declaration, and never read
    as an ordering decision (see the module docstring)."""
    ordered = sorted(scenarios, key=lambda s: s.scenario_id)
    edges: List[Dict[str, Any]] = []
    for i, a in enumerate(ordered):
        subs_a = set(a.participating_subsystems)
        for b in ordered[i + 1:]:
            shared = sorted(subs_a & set(b.participating_subsystems))
            if not shared:
                continue
            edges.append({
                "scenario_a": a.scenario_id,
                "scenario_b": b.scenario_id,
                "relationship": COUPLING_SHARES_SUBSYSTEMS,
                "shared_subsystems": shared,
                "basis": (f"both scenarios name {', '.join(shared)} among their own "
                          "participating_subsystems (system_topology_analysis's SYS-30 "
                          "scenario record) -- a structural relatedness fact, not an "
                          "ordering decision"),
            })
    return edges


# ===========================================================================
# Dependency-chain readiness -- reuses pattern_fragment_ir.py, never reimplements
# ===========================================================================

def _as_fragment_shaped(scenario: SystemScenarioIR) -> Dict[str, Any]:
    """Adapt one `SystemScenarioIR` into the fragment shape
    `pattern_fragment_ir.check_fragment_chain_readiness()` already consumes.
    See the module docstring for why the declared conditions are retagged
    onto that function's DERIVED_* source values rather than its DECLARED
    one."""
    return {
        "fragment_id": scenario.scenario_id,
        "preconditions": [
            {"event": p["event"], "source": pfir.COND_SOURCE_DERIVED_UNRESOLVED_CONSUMED}
            for p in scenario.declared_preconditions
        ],
        "postconditions": [
            {"event": p["event"], "source": pfir.COND_SOURCE_DERIVED_UNCONSUMED_PRODUCED}
            for p in scenario.declared_postconditions
        ],
        "produced_events": [],
    }


def check_system_scenario_dependency_readiness(
        scenarios: Sequence[SystemScenarioIR], *,
        order: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Given the declared preconditions/postconditions on `scenarios` and a
    caller-declared execution `order` (defaulting to `scenarios`' own list
    order), is every scenario's declared precondition covered by an earlier
    scenario's declared postcondition?

    This CALLS `pattern_fragment_ir.check_fragment_chain_readiness()` --
    never reimplements it. Raises `SystemScenarioIrError` (re-wrapping a
    `PatternFragmentIrError` verbatim) on an empty `scenarios` list or an
    `order` naming a different scenario_id set than `scenarios` actually
    holds.
    """
    if not scenarios:
        raise SystemScenarioIrError("EMPTY_SCENARIO_LIST", {})
    fragments = [_as_fragment_shaped(s) for s in scenarios]
    try:
        results = pfir.check_fragment_chain_readiness(fragments, order=order)
    except pfir.PatternFragmentIrError as exc:
        raise SystemScenarioIrError(exc.reason, exc.detail) from exc

    by_status = {status: sum(1 for r in results if r["chain_status"] == status)
                 for status in CHAIN_STATUSES}
    return {
        "schema_version": SCHEMA_VERSION,
        "order_used": [r["fragment_id"] for r in results],
        "per_scenario": results,
        "by_chain_status": by_status,
        "all_covered": by_status[pfir.CHAIN_STATUS_HAS_UNCOVERED] == 0,
    }


# ===========================================================================
# SystemScenarioGraph -- composition
# ===========================================================================

def build_system_scenario_graph(scenario_model: Any, *,
                                 dependency_declarations: Optional[
                                     Mapping[str, Mapping[str, Any]]] = None,
                                 order: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The full `SystemScenarioGraph`: every `SystemScenarioIR` in
    `scenario_model`, the structural subsystem-coupling edges among them, and
    the dependency-chain readiness of `order` (or, absent one, the scenarios'
    own list order) over any caller-declared preconditions/postconditions.

    A `scenario_model` planning zero scenarios (an honest, real SYS-30 state --
    "no supported cross-subsystem flow in this selection") builds a graph with
    an empty scenario list and a trivially-covered dependency report, never an
    error: an empty selection is not a malformed one.
    """
    scenarios = build_system_scenario_irs(
        scenario_model, dependency_declarations=dependency_declarations)
    coupling = derive_subsystem_coupling_edges(scenarios)
    if scenarios:
        readiness = check_system_scenario_dependency_readiness(scenarios, order=order)
    else:
        readiness = {
            "schema_version": SCHEMA_VERSION,
            "order_used": [],
            "per_scenario": [],
            "by_chain_status": {status: 0 for status in CHAIN_STATUSES},
            "all_covered": True,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "scenarios": [s.to_dict() for s in scenarios],
        "subsystem_coupling_edges": coupling,
        "dependency_readiness": readiness,
        "summary": {
            "scenario_count": len(scenarios),
            "cross_subsystem_scenario_count": sum(1 for s in scenarios if s.cross_subsystem),
            "coupling_edge_count": len(coupling),
            "declared_dependency_count": sum(
                len(s.declared_preconditions) for s in scenarios),
            "dependency_chain_all_covered": readiness["all_covered"],
        },
    }


def build_system_scenario_graph_from_plans(command_plan: Mapping[str, Any],
                                            scheduling_plan: Mapping[str, Any], *,
                                            dependency_declarations: Optional[
                                                Mapping[str, Mapping[str, Any]]] = None,
                                            order: Optional[Sequence[str]] = None,
                                            ) -> Dict[str, Any]:
    """Front door reusing `system_topology_analysis.plan_system_scenario_model()`
    directly, for a caller already holding a real SYS-18..22 command plan and a
    real SYS-23..27 scheduling plan rather than an already-built scenario
    model."""
    scenario_model = sta.plan_system_scenario_model(command_plan, scheduling_plan)
    return build_system_scenario_graph(
        scenario_model, dependency_declarations=dependency_declarations, order=order)


def assert_no_scenario_body_emitted(graph: Mapping[str, Any]) -> None:
    """Runtime check of this module's own boundary, mirroring
    `system_topology_analysis.assert_no_emitted_artifacts()` one level up:
    every scenario in a built graph must still carry the pinned
    `NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL` status and none of the
    forbidden body-shaped keys. `build_system_scenario_ir()` already refuses
    to construct an IR that violates this, so a caller passing only IRs this
    module built could never fail this check -- it exists for a caller who
    serialized a graph to JSON (or otherwise mutated one) and is
    re-validating it before trusting it further."""
    for scenario in graph.get("scenarios") or []:
        if scenario.get("scenario_body_status") != SCENARIO_BODY_STATUS_PINNED:
            raise SystemScenarioIrError("SCENARIO_BODY_STATUS_NOT_PINNED", {
                "scenario_id": scenario.get("scenario_id"),
                "status": scenario.get("scenario_body_status"),
            })
        for forbidden in _FORBIDDEN_BODY_KEYS:
            if forbidden in scenario:
                raise SystemScenarioIrError("SCENARIO_BODY_EMITTED", {
                    "scenario_id": scenario.get("scenario_id"), "key": forbidden,
                })


# ===========================================================================
# Rendering -- reuses connectivity.render_markdown_table(), no second renderer
# ===========================================================================

def render_system_scenario_markdown(graph: Mapping[str, Any]) -> str:
    scenario_rows = [
        {**row, "participating_subsystems": ", ".join(row.get("participating_subsystems") or [])}
        for row in (graph.get("scenarios") or [])
    ]
    scenario_table = render_markdown_table(
        [("scenario_id", "Scenario"), ("derived_from", "Derived from"),
         ("participating_subsystems", "Subsystems"), ("cross_subsystem", "Cross-subsystem"),
         ("command_count", "Commands"), ("parallel_block_count", "Parallel blocks"),
         ("sequential_block_count", "Sequential blocks"), ("scenario_body_status", "Body")],
        scenario_rows,
        empty_note="(no scenario planned for this selection)")

    coupling_rows = [
        {**row, "shared_subsystems": ", ".join(row.get("shared_subsystems") or [])}
        for row in (graph.get("subsystem_coupling_edges") or [])
    ]
    coupling_table = render_markdown_table(
        [("scenario_a", "Scenario A"), ("scenario_b", "Scenario B"),
         ("relationship", "Relationship"), ("shared_subsystems", "Shared subsystems")],
        coupling_rows,
        empty_note="(no two scenarios in this selection share a participating subsystem)")

    readiness = graph.get("dependency_readiness") or {}
    summary = graph.get("summary") or {}
    return "\n".join([
        "# SYSTEM SCENARIO IR + DEPENDENCY GRAPH",
        "",
        f"{summary.get('scenario_count', 0)} scenario(s); "
        f"{summary.get('coupling_edge_count', 0)} subsystem-coupling edge(s); "
        f"dependency chain all covered: {summary.get('dependency_chain_all_covered')}.",
        "",
        "## Scenarios",
        "",
        scenario_table,
        "",
        "## Subsystem coupling (structural, never an ordering decision)",
        "",
        coupling_table,
        "",
        "## Dependency chain readiness (declared preconditions/postconditions only)",
        "",
        f"Order used: {', '.join(readiness.get('order_used') or []) or '(none)'}",
    ])


# ===========================================================================
# Ad hoc front door -- no dv-harness/gates.py wiring, per this batch's own
# file-safety scope
# ===========================================================================

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.system_scenario_ir")
    parser.add_argument(
        "--scenario-model", required=True,
        help="path to a system_topology_analysis.plan_system_scenario_model() "
             "document (or a bare JSON list of scenario records)")
    parser.add_argument(
        "--dependency-declarations",
        help="path to a JSON {scenario_id: {preconditions: [...], "
             "postconditions: [...]}} document of real caller-declared "
             "cross-scenario dependency facts")
    parser.add_argument("--order", nargs="*", help="explicit scenario_id execution order")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    with open(args.scenario_model, "r", encoding="utf-8") as fh:
        scenario_model = json.load(fh)
    declarations = None
    if args.dependency_declarations:
        with open(args.dependency_declarations, "r", encoding="utf-8") as fh:
            declarations = json.load(fh)

    try:
        graph = build_system_scenario_graph(
            scenario_model, dependency_declarations=declarations, order=args.order or None)
    except SystemScenarioIrError as exc:
        print(f"NOT_AVAILABLE: {exc.reason}: {exc.detail}")
        return 2

    if args.json:
        print(json.dumps(graph, indent=2, sort_keys=True))
    else:
        print(render_system_scenario_markdown(graph))
    return 0 if graph["summary"]["dependency_chain_all_covered"] else 1


def main(argv: Optional[Sequence[str]] = None) -> None:
    sys.exit(execute_verb(argv))


if __name__ == "__main__":
    main()
