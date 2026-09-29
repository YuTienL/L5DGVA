"""dv_harness/design_intel_maturity_gates.py -- the 9.0 / 9.5 / 10.0 DESIGN
INTELLIGENCE MATURITY GATES: three composite qualification-gate definitions
over THIS family's own EXTRACTION-COMPLETENESS conditions.

WHAT THIS MODULE IS
--------------------
`dv_harness/subsystem_maturity_gate.py` already established the real 9.0 /
9.5 / 10.0 monotonic-ladder pattern for a project's VERIFICATION MATURITY
(golden-flow connectivity, system smoke-proof, VIP-API provability, bind-tier
cleanliness, regression evidence). This module mirrors that PATTERN --
strict monotonic requirement sets, worst-wins folding, a NOT_MEASURABLE
condition that is disclosed rather than invented, the same four-value
condition vocabulary and three-value gate verdict, both checked disjoint
from `models.Status` at import time -- over a DIFFERENT family entirely: the
"Design Intelligence" module family this project already has --
`design_source_inventory.py` (a caller-declared source registry with a real
CURRENT/STALE/SUPERSEDED/NOT_AVAILABLE/UNKNOWN freshness verdict),
`design_architecture_ir.py` (a real verible-derived multi-file module
registry, instance tree and FSM-candidate scan), `design_intent.py` (schema-
validated, citation-required DUT-intent and constraints transcription), and
`design_knowledge_correlation.py` (a general cross-source CONFLICT / GAP /
DOCUMENTED_VS_IMPLEMENTED correlation engine). Per this task's own
instruction, `subsystem_maturity_gate.py` is deliberately NEVER imported or
modified here -- this is a sibling, not an extension, so the two files'
change histories stay independent and neither can accidentally regress the
other's ladder.

WHY "EXTRACTION COMPLETENESS", NOT "VERIFICATION MATURITY"
------------------------------------------------------------
`subsystem_maturity_gate.py`'s six conditions ask whether a subsystem has
been PROVEN through simulation/regression (golden-flow spec-to-PASS, a
system smoke-proof, zero VIP-API hallucination, clean bind tiers, real
regression evidence, a false-PASS count). This family's own conditions ask a
DIFFERENT, earlier question: has the design's OWN static, declarative
knowledge actually been EXTRACTED, cited, and cross-checked -- is there a
real architecture IR (parsed RTL modules + instance tree), a real,
citation-backed intent/constraints transcription, a source registry whose
entries are confirmed CURRENT, and a knowledge correlation pass free of
unresolved conflicts/gaps/doc-vs-implementation mismatches. None of these
six conditions runs a simulator, submits a build, or reads a regression
verdict -- every one of them reads a real EXTRACTION artifact this family's
own modules already produce, or reports the caller supplied none.

Confirmed by direct search before writing a line of evaluation logic (this
module's own six conditions, one call per real function):
  * `design_architecture_ir.build_architecture_ir()` already folds every
    parsed RTL file's modules into one registry, resolves the full instance
    tree, and reports `status` (`BUILT` / `NOT_AVAILABLE`) plus a real
    `duplicate_modules` list -- a genuine architecture-extraction defect,
    never silently masked.
  * `design_source_inventory.build_source_registry()` already evaluates a
    caller-declared source list into CURRENT/STALE/SUPERSEDED/
    NOT_AVAILABLE/UNKNOWN rows. That module's own docstring is explicit that
    it "never writes or reads a snapshot store itself" and discovers no
    source on its own -- confirmed again here by a repo-wide grep for a
    design-source auto-discovery scanner (`design_source_discover|
    walk_project_sources|repo_walk`, case-insensitive) across `dv_harness/`,
    which found nothing beyond that module's own docstring and an unrelated
    VIP-source discoverer in `vip_capability_extraction.py`. That absence is
    condition 6 below, reported honestly NOT_MEASURABLE rather than
    fabricated.
  * `design_intent.validate_intent()` / `validate_constraints()` already
    schema-validate a transcribed DUT-intent / constraints document AND
    check the one cross-field rule the schema cannot express on its own
    (every state-machine transition names a declared state; every numeric
    timing/electrical bound carries a unit) -- raising
    `DesignIntentValidationError` rather than returning a silently-accepted
    partial document. Every legal-drop/backpressure condition in that schema
    already REQUIRES a `document`+`section` citation to validate at all, so
    a passing `validate_intent()` call is itself proof the extraction was
    cited, not merely present.
  * `design_knowledge_correlation.correlate()` already answers the
    cross-source completeness question this family cares about: given the
    real sources a caller extracted, are there any CONFLICT / GAP /
    DOCUMENTED_VS_IMPLEMENTED findings left unresolved. Its own CLI exit
    code already treats `conflict_count + gap_count +
    documented_vs_implemented_count > 0` as "not clean" -- condition 5 below
    reuses that exact definition rather than inventing a second one.

WHY THE VOCABULARY IS NOT `models.Status`
-------------------------------------------
A condition's own outcome (MET / UNMET / NOT_AVAILABLE / NOT_MEASURABLE) and
this gate's verdict (QUALIFIED / NOT_QUALIFIED / INCOMPLETE_EVIDENCE) share
no token with `dv_harness.models.Status` -- checked at import time by
`assert_no_verification_verdict_vocabulary()`, the same guard
`subsystem_maturity_gate.py` / `capability_evolution.py` /
`benchmark_dataset.py` / `dependency_supply_chain.py` already apply to their
own domain-specific vocabularies. A condition being "MET" is not a stage
reaching `Status.PASS`, and conflating the two would let this module's
verdict be misread as a graph-routing signal.

HOW A LEVEL'S REQUIREMENT SET IS BUILT
-----------------------------------------
`LEVEL_REQUIREMENTS` is a strictly monotonic ladder: 9.0's required
conditions are a subset of 9.5's, which are a subset of 10.0's
(`assert_levels_are_monotonic()`). A condition whose status is
`NOT_MEASURABLE` for a REQUIRED condition never blocks `QUALIFIED` -- there
is nothing this project could do today to make `source_discovery_
completeness` MET, so blocking on it would make 10.0 permanently
unreachable rather than honestly disclosed -- but it IS always carried on
the report's `disclosed_caveats` list, so a QUALIFIED verdict at 10.0 is
never silently read as "every extraction dimension was checked and clean".
An `UNMET` condition always makes the level `NOT_QUALIFIED`; a
`NOT_AVAILABLE` one (evidence genuinely missing, not structurally
unmeasurable) makes it `INCOMPLETE_EVIDENCE` -- a level this gate could not
evaluate is a different fact from one it evaluated and found wanting.

WHAT THIS MODULE DOES NOT DO
-----------------------------
It does not parse RTL, validate a document, or correlate sources itself --
every condition either calls a real function this family's own modules
already provide, or reports honestly that the caller supplied nothing to
check. It runs no build, submits no job, writes no state/control/approval
file, and authorizes no promotion/signoff. A QUALIFIED verdict is an input
to a human's qualification decision, never a substitute for one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"


class DesignIntelMaturityGateError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Vocabularies -- both deliberately disjoint from `models.Status`
# ===========================================================================

#: One condition's outcome. `NOT_AVAILABLE` (caller supplied no evidence to
#: check) is kept distinct from `NOT_MEASURABLE` (no producer for this fact
#: exists in this codebase at all) -- two different operator problems with
#: two different remedies, never collapsed into one "unknown".
MET = "MET"
UNMET = "UNMET"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_MEASURABLE = "NOT_MEASURABLE"
CONDITION_STATUSES: Tuple[str, ...] = (MET, UNMET, NOT_AVAILABLE, NOT_MEASURABLE)

#: This gate's own verdict over one maturity level's required conditions.
QUALIFIED = "QUALIFIED"
NOT_QUALIFIED = "NOT_QUALIFIED"
INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
GATE_VERDICTS: Tuple[str, ...] = (QUALIFIED, NOT_QUALIFIED, INCOMPLETE_EVIDENCE)

LEVEL_9_0 = "9.0"
LEVEL_9_5 = "9.5"
LEVEL_10_0 = "10.0"
MATURITY_LEVELS: Tuple[str, ...] = (LEVEL_9_0, LEVEL_9_5, LEVEL_10_0)


def assert_no_verification_verdict_vocabulary() -> None:
    """Import-time guard: neither vocabulary above shares a token with
    `models.Status`. The same discipline `subsystem_maturity_gate.py` /
    `capability_evolution.py` / `benchmark_dataset.py` /
    `dependency_supply_chain.py` already enforce on their own domain
    vocabularies, applied to this one."""
    from .models import Status
    known = {s.value for s in Status}
    clash = sorted((set(CONDITION_STATUSES) | set(GATE_VERDICTS)) & known)
    if clash:
        raise DesignIntelMaturityGateError("VERDICT_VOCABULARY_COLLIDES_WITH_MODELS_STATUS", {
            "clash": clash, "known_status_values": sorted(known)})


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Caller-supplied evidence bundle
# ===========================================================================

@dataclass
class GateInputs:
    """Every optional caller-supplied evidence artifact a condition may
    need. Nothing here is ever fabricated when absent -- a missing input
    makes its condition `NOT_AVAILABLE` naming exactly what would produce
    it, never a default value standing in for the fact.
    """
    cfg: Optional[Dict[str, Any]] = None
    # architecture_ir_built: real RTL files for design_architecture_ir.py to
    # parse. A pre-built IR may be supplied directly instead (skips the
    # parse), for a caller that already ran build_architecture_ir() once.
    rtl_files: Optional[Sequence[Any]] = None
    architecture_top_module: Optional[str] = None
    architecture_ir: Optional[Mapping[str, Any]] = None
    # source_registry_current: caller-declared design-source entries (the
    # exact duck-typed shape design_source_inventory.SourceEntry/
    # build_source_registry() already accepts).
    source_entries: Optional[Sequence[Any]] = None
    # intent_extracted_with_citations / constraints_extracted_with_units:
    # already-loaded, schema-shaped structured documents (never a raw path
    # this module would have to open -- design_intent.py's own load_intent()/
    # load_constraints() are the caller's route to producing one).
    intent_doc: Optional[Mapping[str, Any]] = None
    constraints_doc: Optional[Mapping[str, Any]] = None
    # knowledge_correlation_clean: the same sources/expected_facts shape
    # design_knowledge_correlation.correlate() already accepts.
    knowledge_sources: Optional[Any] = None
    knowledge_expected_facts: Optional[Any] = None


# ===========================================================================
# Condition result + declaration
# ===========================================================================

@dataclass
class ConditionResult:
    condition_id: str
    status: str
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    fact_source: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"condition_id": self.condition_id, "status": self.status,
                "reason": self.reason, "evidence": self.evidence,
                "fact_source": list(self.fact_source)}


@dataclass(frozen=True)
class ConditionSpec:
    condition_id: str
    description: str
    fact_source: Tuple[str, ...]
    evaluator: Callable[[Path, GateInputs], ConditionResult]


# ===========================================================================
# Condition 1: real architecture IR built (design_architecture_ir.py)
# ===========================================================================

COND_ARCHITECTURE_IR_BUILT = "architecture_ir_built"


def _evaluate_architecture_ir_built(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import design_architecture_ir as dair

    if inputs.architecture_ir is not None:
        ir = inputs.architecture_ir
    elif inputs.rtl_files:
        try:
            ir = dair.build_architecture_ir(
                inputs.rtl_files, top_module=inputs.architecture_top_module)
        except dair.DesignArchitectureIRError as e:
            return ConditionResult(COND_ARCHITECTURE_IR_BUILT, NOT_AVAILABLE,
                f"build_architecture_ir() could not run: {e}", {})
    else:
        return ConditionResult(COND_ARCHITECTURE_IR_BUILT, NOT_AVAILABLE,
            "no rtl_files (or a pre-built architecture_ir) supplied -- "
            "GateInputs.rtl_files, or GateInputs.architecture_ir naming a real "
            "design_architecture_ir.build_architecture_ir() result", {})

    if ir.get("status") != "BUILT":
        return ConditionResult(COND_ARCHITECTURE_IR_BUILT, NOT_AVAILABLE,
            f"design_architecture_ir reported {ir.get('status')}: {ir.get('reason')}",
            {"status": ir.get("status")})
    duplicates = ir.get("duplicate_modules") or []
    module_count = len(ir.get("modules") or {})
    evidence = {"module_count": module_count, "duplicate_modules": duplicates,
                "top_modules": (ir.get("instance_tree") or {}).get("top_modules")}
    if duplicates:
        return ConditionResult(COND_ARCHITECTURE_IR_BUILT, UNMET,
            f"{len(duplicates)} module name(s) declared in more than one parsed RTL file -- "
            "an unresolved architecture-extraction ambiguity: "
            f"{[d.get('module_name') for d in duplicates]}", evidence)
    if module_count == 0:
        return ConditionResult(COND_ARCHITECTURE_IR_BUILT, UNMET,
            "design_architecture_ir reported BUILT but resolved zero modules", evidence)
    return ConditionResult(COND_ARCHITECTURE_IR_BUILT, MET,
        f"design_architecture_ir resolved {module_count} module(s) with no duplicate-name "
        "collision", evidence)


# ===========================================================================
# Condition 2: source registry entries all confirmed CURRENT
# (design_source_inventory.py)
# ===========================================================================

COND_SOURCE_REGISTRY_CURRENT = "source_registry_current"


def _evaluate_source_registry_current(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import design_source_inventory as dsi

    if not inputs.source_entries:
        return ConditionResult(COND_SOURCE_REGISTRY_CURRENT, NOT_AVAILABLE,
            "no source_entries supplied -- GateInputs.source_entries naming the design "
            "sources this project's own extraction pipeline actually declared "
            "(design_source_inventory.SourceEntry-shaped)", {})
    try:
        registry = dsi.build_source_registry(inputs.source_entries)
    except dsi.DesignSourceInventoryError as e:
        return ConditionResult(COND_SOURCE_REGISTRY_CURRENT, NOT_AVAILABLE,
            f"design_source_inventory could not evaluate the supplied source_entries: {e}", {})

    summary = registry["summary"]
    evidence = {"summary": summary, "source_count": registry["source_count"]}
    if registry["source_count"] == 0:
        return ConditionResult(COND_SOURCE_REGISTRY_CURRENT, NOT_AVAILABLE,
            "the supplied source_entries set is empty -- nothing to evaluate", evidence)
    not_current = registry["source_count"] - summary.get(dsi.STATUS_CURRENT, 0)
    if not_current:
        return ConditionResult(COND_SOURCE_REGISTRY_CURRENT, UNMET,
            f"{not_current} of {registry['source_count']} design source(s) are not confirmed "
            f"CURRENT (STALE={summary.get(dsi.STATUS_STALE, 0)}, "
            f"SUPERSEDED={summary.get(dsi.STATUS_SUPERSEDED, 0)}, "
            f"NOT_AVAILABLE={summary.get(dsi.STATUS_NOT_AVAILABLE, 0)}, "
            f"UNKNOWN={summary.get(dsi.STATUS_UNKNOWN, 0)})", evidence)
    return ConditionResult(COND_SOURCE_REGISTRY_CURRENT, MET,
        f"all {registry['source_count']} declared design source(s) are confirmed CURRENT",
        evidence)


# ===========================================================================
# Condition 3: DUT intent transcribed, schema-valid and cited
# (design_intent.py -- validate_intent())
# ===========================================================================

COND_INTENT_EXTRACTED_WITH_CITATIONS = "intent_extracted_with_citations"


def _evaluate_intent_extracted_with_citations(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import design_intent as di

    if inputs.intent_doc is None:
        return ConditionResult(COND_INTENT_EXTRACTED_WITH_CITATIONS, NOT_AVAILABLE,
            "no intent_doc supplied -- GateInputs.intent_doc naming a real, "
            "structured DUT-intent document (design_intent.load_intent()'s own shape)", {})
    try:
        di.validate_intent(dict(inputs.intent_doc))
    except di.DesignIntentValidationError as e:
        return ConditionResult(COND_INTENT_EXTRACTED_WITH_CITATIONS, UNMET,
            f"the supplied intent_doc failed schema/citation validation: {e}", {})
    states = (inputs.intent_doc.get("state_machine") or {}).get("states") or []
    return ConditionResult(COND_INTENT_EXTRACTED_WITH_CITATIONS, MET,
        f"intent_doc validated against dut_intent.schema.json with {len(states)} declared "
        "state(s), every legal-drop/backpressure condition citing a real document+section",
        {"state_count": len(states)})


# ===========================================================================
# Condition 4: constraints transcribed, schema-valid and unit-bearing
# (design_intent.py -- validate_constraints())
# ===========================================================================

COND_CONSTRAINTS_EXTRACTED_WITH_UNITS = "constraints_extracted_with_units"


def _evaluate_constraints_extracted_with_units(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import design_intent as di

    if inputs.constraints_doc is None:
        return ConditionResult(COND_CONSTRAINTS_EXTRACTED_WITH_UNITS, NOT_AVAILABLE,
            "no constraints_doc supplied -- GateInputs.constraints_doc naming a real, "
            "structured constraints document (design_intent.load_constraints()'s own shape)", {})
    try:
        di.validate_constraints(dict(inputs.constraints_doc))
    except di.DesignIntentValidationError as e:
        return ConditionResult(COND_CONSTRAINTS_EXTRACTED_WITH_UNITS, UNMET,
            f"the supplied constraints_doc failed schema/unit validation: {e}", {})
    timing = inputs.constraints_doc.get("timing_constraints") or []
    electrical = inputs.constraints_doc.get("electrical_limits") or []
    return ConditionResult(COND_CONSTRAINTS_EXTRACTED_WITH_UNITS, MET,
        f"constraints_doc validated against constraints.schema.json with "
        f"{len(timing)} timing_constraint(s) and {len(electrical)} electrical_limit(s), "
        "every numeric bound carrying a unit", {"timing_count": len(timing),
                                                 "electrical_count": len(electrical)})


# ===========================================================================
# Condition 5: cross-source knowledge correlation clean
# (design_knowledge_correlation.py -- correlate())
# ===========================================================================

COND_KNOWLEDGE_CORRELATION_CLEAN = "knowledge_correlation_clean"


def _evaluate_knowledge_correlation_clean(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import design_knowledge_correlation as dkc

    if not inputs.knowledge_sources:
        return ConditionResult(COND_KNOWLEDGE_CORRELATION_CLEAN, NOT_AVAILABLE,
            "no knowledge_sources supplied -- GateInputs.knowledge_sources naming the real "
            "extracted-fact sources this project's design intelligence family already "
            "produced (design_knowledge_correlation.correlate()'s own `sources` shape)", {})
    try:
        report = dkc.correlate(inputs.knowledge_sources, inputs.knowledge_expected_facts)
    except dkc.DesignKnowledgeCorrelationError as e:
        return ConditionResult(COND_KNOWLEDGE_CORRELATION_CLEAN, NOT_AVAILABLE,
            f"design_knowledge_correlation could not evaluate the supplied sources: {e}", {})

    summary = report["summary"]
    bad = (summary["conflict_count"] + summary["gap_count"]
           + summary["documented_vs_implemented_count"])
    evidence = {"summary": summary}
    if bad:
        return ConditionResult(COND_KNOWLEDGE_CORRELATION_CLEAN, UNMET,
            f"{summary['conflict_count']} conflict(s), {summary['gap_count']} gap(s), "
            f"{summary['documented_vs_implemented_count']} documented-vs-implemented "
            "mismatch(es) remain unresolved across the correlated design sources", evidence)
    return ConditionResult(COND_KNOWLEDGE_CORRELATION_CLEAN, MET,
        f"design_knowledge_correlation found zero conflicts/gaps/documented-vs-implemented "
        f"mismatches across {summary['source_count']} source(s) and "
        f"{summary['fact_count']} fact(s)", evidence)


# ===========================================================================
# Condition 6: automatic design-source discovery completeness --
# NOT_MEASURABLE, honestly, always
# ===========================================================================

COND_SOURCE_DISCOVERY_COMPLETENESS = "source_discovery_completeness"

#: Recorded verbatim rather than paraphrased on every report, so the search
#: this condition rests on is checkable by a reader without re-running it.
#: Re-verify with a repo-wide, case-insensitive search for a design-source
#: auto-discovery scanner (`design_source_discover|walk_project_sources|
#: repo_walk`) across `dv_harness/*.py` before ever changing this to
#: something other than NOT_MEASURABLE.
SOURCE_DISCOVERY_SIGNAL_SEARCH_NOTE = (
    "Checked dv_harness.design_source_inventory (this family's own registry module, whose own "
    "docstring states outright that it 'never writes or reads a snapshot store itself' and "
    "evaluates only caller-declared entries), plus a repo-wide, case-insensitive grep for a "
    "design-source auto-discovery scanner (design_source_discover|walk_project_sources|"
    "repo_walk) across dv_harness/*.py: the only other hit is "
    "dv_harness.vip_capability_extraction, an unrelated VIP-source discoverer, not a "
    "general design-source (RTL/spec/register-file/etc.) walker for THIS family. No producer "
    "anywhere in this codebase automatically enumerates every real design source a project "
    "has on disk and confirms the source registry names all of them -- "
    "design_source_inventory.py can only ever tell you whether the sources a caller already "
    "DECLARED are current, never whether the declared set is COMPLETE. Inventing a completeness "
    "counter here would be exactly the fabrication the Evidence Truth Rule forbids."
)


def _evaluate_source_discovery_completeness(root: Path, inputs: GateInputs) -> ConditionResult:
    return ConditionResult(COND_SOURCE_DISCOVERY_COMPLETENESS, NOT_MEASURABLE,
        SOURCE_DISCOVERY_SIGNAL_SEARCH_NOTE,
        {"checked_modules": ["dv_harness.design_source_inventory"]})


# ===========================================================================
# The condition table + the maturity ladder
# ===========================================================================

CONDITIONS: Tuple[ConditionSpec, ...] = (
    ConditionSpec(
        COND_ARCHITECTURE_IR_BUILT,
        "A real architecture IR (parsed RTL module registry + instance tree) has been built "
        "with no unresolved duplicate-module-name collision (design_architecture_ir.py).",
        ("dv_harness.design_architecture_ir.build_architecture_ir",
         "dv_harness.design_architecture_ir.DesignArchitectureIRError"),
        _evaluate_architecture_ir_built),
    ConditionSpec(
        COND_SOURCE_REGISTRY_CURRENT,
        "Every declared design source is confirmed CURRENT in the source registry "
        "(design_source_inventory.py).",
        ("dv_harness.design_source_inventory.build_source_registry",
         "dv_harness.design_source_inventory.STATUS_CURRENT",
         "dv_harness.design_source_inventory.STATUS_STALE",
         "dv_harness.design_source_inventory.STATUS_SUPERSEDED",
         "dv_harness.design_source_inventory.STATUS_NOT_AVAILABLE",
         "dv_harness.design_source_inventory.STATUS_UNKNOWN"),
        _evaluate_source_registry_current),
    ConditionSpec(
        COND_INTENT_EXTRACTED_WITH_CITATIONS,
        "The DUT intent document (state machine, legal-drop/backpressure conditions) has been "
        "transcribed, schema-validated, and every condition carries a real citation "
        "(design_intent.py -- validate_intent()).",
        ("dv_harness.design_intent.validate_intent",
         "dv_harness.design_intent.DesignIntentValidationError"),
        _evaluate_intent_extracted_with_citations),
    ConditionSpec(
        COND_CONSTRAINTS_EXTRACTED_WITH_UNITS,
        "The constraints document (timing/electrical limits, untestable items) has been "
        "transcribed, schema-validated, and every numeric bound carries a unit "
        "(design_intent.py -- validate_constraints()).",
        ("dv_harness.design_intent.validate_constraints",
         "dv_harness.design_intent.DesignIntentValidationError"),
        _evaluate_constraints_extracted_with_units),
    ConditionSpec(
        COND_KNOWLEDGE_CORRELATION_CLEAN,
        "Cross-source knowledge correlation over this project's own extracted design facts "
        "reports zero conflicts, zero gaps and zero documented-vs-implemented mismatches "
        "(design_knowledge_correlation.py -- correlate()).",
        ("dv_harness.design_knowledge_correlation.correlate",
         "dv_harness.design_knowledge_correlation.DesignKnowledgeCorrelationError"),
        _evaluate_knowledge_correlation_clean),
    ConditionSpec(
        COND_SOURCE_DISCOVERY_COMPLETENESS,
        "Automatic design-source discovery completeness (every real design source on disk is "
        "known to be registered). NOT_MEASURABLE in this codebase today -- no automatic "
        "discovery scanner exists; see SOURCE_DISCOVERY_SIGNAL_SEARCH_NOTE.",
        ("dv_harness.design_source_inventory",),
        _evaluate_source_discovery_completeness),
)

CONDITIONS_BY_ID: Dict[str, ConditionSpec] = {c.condition_id: c for c in CONDITIONS}

#: A strictly monotonic ladder: every level's required set is a superset of
#: the level below it (`assert_levels_are_monotonic()`).
LEVEL_REQUIREMENTS: Dict[str, Tuple[str, ...]] = {
    LEVEL_9_0: (COND_ARCHITECTURE_IR_BUILT, COND_INTENT_EXTRACTED_WITH_CITATIONS),
    LEVEL_9_5: (COND_ARCHITECTURE_IR_BUILT, COND_INTENT_EXTRACTED_WITH_CITATIONS,
                COND_SOURCE_REGISTRY_CURRENT, COND_CONSTRAINTS_EXTRACTED_WITH_UNITS),
    LEVEL_10_0: (COND_ARCHITECTURE_IR_BUILT, COND_INTENT_EXTRACTED_WITH_CITATIONS,
                 COND_SOURCE_REGISTRY_CURRENT, COND_CONSTRAINTS_EXTRACTED_WITH_UNITS,
                 COND_KNOWLEDGE_CORRELATION_CLEAN, COND_SOURCE_DISCOVERY_COMPLETENESS),
}


def _assert_conditions_and_requirements_consistent() -> None:
    ids = [c.condition_id for c in CONDITIONS]
    if len(set(ids)) != len(ids):
        raise DesignIntelMaturityGateError("DUPLICATE_CONDITION_ID", {"condition_ids": ids})
    known = set(CONDITIONS_BY_ID)
    for level, required in LEVEL_REQUIREMENTS.items():
        unknown = [cid for cid in required if cid not in known]
        if unknown:
            raise DesignIntelMaturityGateError("LEVEL_REQUIRES_UNDECLARED_CONDITION", {
                "level": level, "unknown_condition_ids": unknown})


def assert_levels_are_monotonic() -> None:
    """9.0's required conditions are a subset of 9.5's, which are a subset of
    10.0's -- a maturity ladder that got EASIER at a higher level would not be
    one."""
    prior: set = set()
    for level in MATURITY_LEVELS:
        current = set(LEVEL_REQUIREMENTS[level])
        if not prior <= current:
            raise DesignIntelMaturityGateError("LEVEL_REQUIREMENTS_NOT_MONOTONIC", {
                "level": level, "missing_from_this_level": sorted(prior - current)})
        prior = current


_assert_conditions_and_requirements_consistent()
assert_levels_are_monotonic()


def assert_fact_sources_resolvable() -> List[str]:
    """Every declared `fact_source` still resolves through the import system.

    Mirrors `subsystem_maturity_gate.assert_fact_sources_resolvable()`: a
    condition citing a renamed/removed function must fail a test, not
    silently report a fabricated MET."""
    import importlib
    resolved: List[str] = []
    for spec in CONDITIONS:
        for dotted in spec.fact_source:
            parts = dotted.split(".")
            obj = None
            for cut in range(len(parts), 1, -1):
                try:
                    obj = importlib.import_module(".".join(parts[:cut]))
                except Exception:
                    continue
                rest = parts[cut:]
                break
            else:
                raise DesignIntelMaturityGateError("FACT_SOURCE_MODULE_UNIMPORTABLE", {
                    "fact_source": dotted, "condition_id": spec.condition_id})
            for name in rest:
                if not hasattr(obj, name):
                    raise DesignIntelMaturityGateError("FACT_SOURCE_ATTRIBUTE_MISSING", {
                        "fact_source": dotted, "condition_id": spec.condition_id,
                        "missing_attribute": name})
                obj = getattr(obj, name)
            resolved.append(dotted)
    return resolved


# ===========================================================================
# The gate
# ===========================================================================

def derive_maturity_gate(level: str, root: Any,
                         inputs: Optional[GateInputs] = None) -> Dict[str, Any]:
    """Evaluate every declared condition once, then fold the LEVEL's own
    required subset into one verdict.

    Every condition is evaluated (not only the ones this level requires) so a
    caller comparing 9.0/9.5/10.0 against one project gets one full report
    rather than re-deriving the shared facts three times.
    """
    if level not in MATURITY_LEVELS:
        raise DesignIntelMaturityGateError("UNKNOWN_MATURITY_LEVEL", {
            "level": level, "known_levels": list(MATURITY_LEVELS)})
    root = Path(root)
    inputs = inputs or GateInputs()

    results: Dict[str, ConditionResult] = {}
    for cid, spec in CONDITIONS_BY_ID.items():
        try:
            result = spec.evaluator(root, inputs)
        except Exception as e:  # an evaluator bug must read as NOT_AVAILABLE, never crash the gate
            result = ConditionResult(cid, NOT_AVAILABLE,
                f"condition evaluator raised {type(e).__name__}: {e}", {})
        if result.status not in CONDITION_STATUSES:
            raise DesignIntelMaturityGateError("CONDITION_RETURNED_UNKNOWN_STATUS", {
                "condition_id": cid, "status": result.status,
                "legal_values": list(CONDITION_STATUSES)})
        result.fact_source = spec.fact_source
        results[cid] = result

    required = LEVEL_REQUIREMENTS[level]
    required_results = {cid: results[cid] for cid in required}
    unmet = sorted(cid for cid, r in required_results.items() if r.status == UNMET)
    unavailable = sorted(cid for cid, r in required_results.items() if r.status == NOT_AVAILABLE)
    disclosed_caveats = sorted(cid for cid, r in required_results.items()
                               if r.status == NOT_MEASURABLE)

    if unmet:
        verdict = NOT_QUALIFIED
    elif unavailable:
        verdict = INCOMPLETE_EVIDENCE
    else:
        verdict = QUALIFIED

    return {
        "schema_version": SCHEMA_VERSION,
        "level": level,
        "root": str(root),
        "verdict": verdict,
        "required_conditions": list(required),
        "conditions": {cid: r.to_dict() for cid, r in results.items()},
        "unmet_conditions": unmet,
        "unavailable_conditions": unavailable,
        "disclosed_caveats": disclosed_caveats,
        "verdict_rule": (
            "QUALIFIED requires every REQUIRED condition to be MET or NOT_MEASURABLE (a "
            "condition this harness structurally cannot measure never blocks a level -- it is "
            "instead surfaced under disclosed_caveats, never silently cleared); one UNMET "
            "required condition -> NOT_QUALIFIED; otherwise, with no UNMET but at least one "
            "required condition NOT_AVAILABLE (evidence not supplied/found) -> "
            "INCOMPLETE_EVIDENCE."),
        "authorizes": (
            "nothing. This gate approves no promotion, no signoff and no production write -- "
            "it is a composite READ over this design-intelligence family's own real "
            "extraction-completeness artifacts, for a human to weigh."),
    }


# ===========================================================================
# Rendering + CLI
# ===========================================================================

MATURITY_GATE_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("condition_id", "Condition"),
    ("required", "Required"),
    ("status", "Status"),
    ("reason", "Reason"),
)


def render_maturity_gate_table(report: Mapping[str, Any]) -> str:
    from .connectivity import render_markdown_table
    required = set(report.get("required_conditions") or ())
    rows = []
    for cid, r in (report.get("conditions") or {}).items():
        rows.append({"condition_id": cid, "required": "yes" if cid in required else "no",
                     "status": r["status"], "reason": r["reason"]})
    rows.sort(key=lambda r: (r["required"] != "yes", r["condition_id"]))
    return render_markdown_table(list(MATURITY_GATE_COLUMNS), rows,
                                 empty_note="(no condition evaluated -- this is a bug)")


def format_maturity_gate_report(report: Mapping[str, Any]) -> str:
    out = [
        f"# DESIGN INTELLIGENCE MATURITY GATE {report['level']}",
        "",
        f"**{report['verdict']}**",
        "",
        f"Project root: `{report['root']}`",
        "",
        render_maturity_gate_table(report),
        "",
        report["verdict_rule"],
        "",
        f"This verdict authorizes: {report['authorizes']}",
    ]
    if report.get("disclosed_caveats"):
        out += ["", "## Disclosed caveats (never block QUALIFIED, never silently cleared)", ""]
        conds = report["conditions"]
        out += [f"- **{cid}** -- {conds[cid]['reason']}" for cid in report["disclosed_caveats"]]
    return "\n".join(out)


def execute_verb(level: str, root: Any, *, inputs: Optional[GateInputs] = None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.design_intel_maturity_gates
    evaluate`. Exit 0 QUALIFIED, 1 NOT_QUALIFIED, 2 INCOMPLETE_EVIDENCE."""
    report = derive_maturity_gate(level, root, inputs)
    text = json.dumps(report, indent=2) if as_json else format_maturity_gate_report(report)
    code = {QUALIFIED: 0, NOT_QUALIFIED: 1, INCOMPLETE_EVIDENCE: 2}[report["verdict"]]
    return text, code


def render_conditions_report(*, as_json: bool = False) -> str:
    rows = [{
        "condition_id": c.condition_id,
        "description": c.description,
        "fact_source": list(c.fact_source),
        "required_at_levels": [lvl for lvl in MATURITY_LEVELS
                               if c.condition_id in LEVEL_REQUIREMENTS[lvl]],
    } for c in CONDITIONS]
    if as_json:
        return json.dumps({"schema_version": SCHEMA_VERSION, "conditions": rows,
                           "level_requirements": {lvl: list(LEVEL_REQUIREMENTS[lvl])
                                                  for lvl in MATURITY_LEVELS}}, indent=2)
    lines = ["# Design Intelligence maturity gate conditions", ""]
    for r in rows:
        lines.append(f"- **{r['condition_id']}** (required at: "
                     f"{', '.join(r['required_at_levels']) or 'none'})")
        lines.append(f"  {r['description']}")
        lines.append(f"  fact_source: {', '.join(r['fact_source']) or '(none)'}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.design_intel_maturity_gates",
        description="Composite 9.0/9.5/10.0 Design Intelligence maturity qualification gates "
                    "over this family's own extraction-completeness artifacts. Reads only; "
                    "runs no stage, gate script, build, regression or LSF job.")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_conditions = sub.add_parser("conditions", help="list the declared conditions")
    p_conditions.add_argument("--json", action="store_true", dest="as_json")

    p_eval = sub.add_parser("evaluate", help="evaluate one maturity level")
    p_eval.add_argument("--level", required=True, choices=list(MATURITY_LEVELS))
    p_eval.add_argument("--root", default=".")
    p_eval.add_argument("--json", action="store_true", dest="as_json")
    p_eval.add_argument("--rtl-file", action="append", default=None, dest="rtl_files",
                        help="RTL source file for design_architecture_ir.py to parse (repeatable)")
    p_eval.add_argument("--architecture-top-module", default=None)
    p_eval.add_argument("--source-entries", default=None,
                        help="a JSON file holding a list of design_source_inventory "
                             "SourceEntry-shaped dicts")
    p_eval.add_argument("--intent-doc", default=None,
                        help="a JSON file holding a real design_intent dut_intent document")
    p_eval.add_argument("--constraints-doc", default=None,
                        help="a JSON file holding a real design_intent constraints document")
    p_eval.add_argument("--knowledge-sources", default=None,
                        help="a JSON file holding design_knowledge_correlation's `sources` list")
    p_eval.add_argument("--knowledge-expected-facts", default=None,
                        help="a JSON file holding design_knowledge_correlation's "
                             "`expected_facts` list")
    args = parser.parse_args(argv)

    if args.verb == "conditions":
        print(render_conditions_report(as_json=args.as_json))
        return 0

    def _load(path):
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else None

    inputs = GateInputs(
        rtl_files=args.rtl_files,
        architecture_top_module=args.architecture_top_module,
        source_entries=_load(args.source_entries),
        intent_doc=_load(args.intent_doc),
        constraints_doc=_load(args.constraints_doc),
        knowledge_sources=_load(args.knowledge_sources),
        knowledge_expected_facts=_load(args.knowledge_expected_facts),
    )
    text, code = execute_verb(args.level, Path(args.root), inputs=inputs, as_json=args.as_json)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
