"""dv_harness/design_completeness_gate.py -- a completeness rollup over the
Design Intelligence extraction family's own outputs: which of the real
extraction categories this project has (register maps, PHY boundary/behavior,
architecture IR, interrupt/DMA/clock-reset, programming sequences,
verification intent, DUT<->requirement correlation, cross-source design
knowledge correlation, the design source registry, spec structural maps,
power intent) actually produced REAL FACTS for THIS project, versus
NOT_AVAILABLE -- worst-wins folded into one completeness verdict + gate.

THE GAP THIS CLOSES
--------------------
This project session built thirteen separate "Design Intelligence" real
extractors (register_excel_extract.py, register_rtl_trace.py, phy_boundary.py,
phy_model_behavior_ir.py, design_architecture_ir.py,
interrupt_dma_clock_reset_extraction.py, programming_sequence_ir.py,
verification_intent_ir.py, dut_evidence_correlation.py,
design_knowledge_correlation.py, design_source_inventory.py, spec_doc_map.py,
power_intent.py). Each answers its own narrow extraction question honestly --
but nothing rolled them into ONE picture of "how complete is this project's
design-intelligence intake, right now, and which categories are missing
real facts". A human wanting that answer had to run all thirteen tools by
hand and mentally combine thirteen different status vocabularies. Two audits
of the same project could therefore disagree about the same underlying facts.

REUSE OVER REINVENT -- mirroring `golden_flow_readiness.py`'s own pattern one
domain over, not merely inspired by it:

  * The READY/PARTIAL/BLOCKED/UNKNOWN readiness vocabulary and its worst-wins
    `combine_readiness()` fold are IMPORTED from `golden_flow_readiness.py`
    verbatim -- not re-derived. Section 47's own precedent for "the fold BLOCKED
    is worse than UNKNOWN, an empty input is UNKNOWN never READY, a mix of
    READY and UNKNOWN is PARTIAL" is reused exactly, so this module and
    `golden_flow_readiness.py` can never silently disagree about what
    "worst-wins" means.
  * `connectivity.render_markdown_table()` -- this repo's one parameterized
    table renderer -- renders the matrix; no second hand-rolled table loop.
  * Every row's `fact_source` names the REAL extractor entry point it calls,
    and `assert_fact_sources_resolvable()` (the identical anti-drift check
    `golden_flow_readiness.py` runs on its own twenty rows) resolves every one
    through the import system at test time -- a row claiming to call a
    function that has since been renamed away fails loudly rather than
    silently reporting a fabricated status.

WHAT THIS MODULE IS NOT
------------------------
It DERIVES NOTHING an existing extractor already computes. Every row's
`_probe_*` function calls that category's own real top-level function with
whatever real project-specific inputs a caller supplies for it (there is no
canonical on-disk path for a register-map spreadsheet, a PHY spec PDF, a set
of RTL files, etc. the way there is for `.dv-harness/state.json` -- these are
project-declared inputs, exactly the same "accepted as a caller-supplied
input because this repo has no fixed producer path" discipline several
sibling extractors already state for their own inputs). A category the
caller never supplies inputs for is UNKNOWN ("never even attempted"), never
silently read as NOT_AVAILABLE-because-we-tried-and-found-nothing -- those
are different facts, and this module keeps them distinct in each row's own
`gap` text even though both fold to the same UNKNOWN readiness class.

It WRITES NO STATE, RUNS NOTHING and APPROVES NOTHING. Every probe is a pure
read over caller-supplied inputs; a probe's own exception is caught and
reported as BLOCKED with the real exception text rather than crashing the
whole matrix (the same "one bad row must never delete the row" discipline
`golden_flow_readiness.py`'s `derive_golden_flow_readiness()` already
applies). There is deliberately no `STAGE_GATES` entry and no `dv-harness`
CLI verb -- per the house rule against editing `gates.py`/`cli.py` while they
are under heavy edit pressure from concurrent work, the front door is a
standalone `python -m dv_harness.design_completeness_gate` script, matching
several very recent same-day additions' own disclosed choice.

PER-ROW READINESS MAPPING
--------------------------
Each row maps its own real extractor's status vocabulary onto READY/PARTIAL/
BLOCKED/UNKNOWN by one consistent rule, documented per probe: READY = a real,
usable, complete set of facts was produced; PARTIAL = some real facts were
produced but incompletely, or a real facts set flagged a genuine defect
(a broken register-map row, an invalid step ordering); BLOCKED = the
extractor was genuinely unable to produce facts from what it was given (a
parse error, zero registers survived, a self-consistency contradiction);
UNKNOWN = no evidence exists at all for this project (no input supplied, or
the extractor ran and confirmed nothing is there).
"""
from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .golden_flow_readiness import READY, PARTIAL, BLOCKED, UNKNOWN, combine_readiness

SCHEMA_VERSION = "1.0"

#: Reused verbatim from golden_flow_readiness.py -- see module docstring.
READINESS_CLASSES: tuple = (READY, PARTIAL, BLOCKED, UNKNOWN)

NONE_CELL = "-"


class DesignCompletenessError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Row declarations -- the thirteen real Design Intelligence extraction
# categories, in the order this project session built them
# ===========================================================================

@dataclass(frozen=True)
class CompletenessRowSpec:
    row_id: str
    label: str
    fact_source: Tuple[str, ...]
    basis: str


ROWS: Tuple[CompletenessRowSpec, ...] = (
    CompletenessRowSpec(
        "register_map", "Register Map (Excel/CSV extraction)",
        ("dv_harness.register_excel_extract.extract_register_map",),
        "register_excel_extract.py's real .xlsx/.csv transcription into a schema-conformant "
        "RegisterIR -- section 184's canonical register-facts input, produced from a real "
        "spreadsheet rather than hand-authored."),
    CompletenessRowSpec(
        "register_rtl_trace", "Register-to-RTL Trace",
        ("dv_harness.register_rtl_trace.trace_register_fields",
         "dv_harness.register_rtl_trace.parse_rtl_sources"),
        "register_rtl_trace.py's declaration-level cross-reference of a register field's "
        "declared name against the real verible-parsed RTL this project has."),
    CompletenessRowSpec(
        "phy_boundary", "PHY Boundary (serial/parallel bind-location decision)",
        ("dv_harness.phy_boundary.extract_phy_boundary",),
        "phy_boundary.py's real bind-location decision, derived from the same verible-parsed "
        "RTL port table env_manifest.py produces -- Bind-Location Rule 5's own gating fact."),
    CompletenessRowSpec(
        "phy_model_behavior", "PHY Model Behavior (documented training/TX/RX/power facts)",
        ("dv_harness.phy_model_behavior_ir.extract_phy_model_behavior_ir",),
        "phy_model_behavior_ir.py's real structural scan of a distilled PHY spec/model "
        "document -- never silicon, never invented from protocol knowledge alone."),
    CompletenessRowSpec(
        "architecture_ir", "Architecture IR (instance tree + FSM candidates)",
        ("dv_harness.design_architecture_ir.build_architecture_ir",),
        "design_architecture_ir.py's real multi-file module registry, recursive instance "
        "tree, and best-effort literal FSM scan over the project's own verible-parsed RTL."),
    CompletenessRowSpec(
        "interrupt_dma_clock_reset", "Interrupt / DMA / Clock-Reset Extraction",
        ("dv_harness.interrupt_dma_clock_reset_extraction.extract_interrupt_dma_clock_reset",),
        "interrupt_dma_clock_reset_extraction.py's real line-scan of supplied RTL/spec text "
        "for interrupt sources, DMA channel/descriptor facts, and clock/reset idioms."),
    CompletenessRowSpec(
        "programming_sequence", "Programming Sequence IR (phase/dependency ordering)",
        ("dv_harness.programming_sequence_ir.validate_step_ordering",
         "dv_harness.programming_sequence_ir.programming_sequence_ir_from_dict"),
        "programming_sequence_ir.py's real phase-ordering, access-type-legality and "
        "register-dependency validation over a project's own declared bring-up sequence."),
    CompletenessRowSpec(
        "verification_intent", "Verification Intent IR (7-domain DUT-evidence bridge)",
        ("dv_harness.verification_intent_ir.build_verification_intent_ir",),
        "verification_intent_ir.py's per-domain (state-machine/register-csr/interrupt/"
        "reset-clock/error-recovery/low-power/performance) real-evidence reading for one "
        "requirement."),
    CompletenessRowSpec(
        "dut_evidence_correlation", "Requirement-to-RTL Evidence Correlation",
        ("dv_harness.dut_evidence_correlation.correlate",),
        "dut_evidence_correlation.py's real name-based join of a declared DUT-facing fact "
        "against env.manifest.json's dut_facts layers."),
    CompletenessRowSpec(
        "design_knowledge_correlation", "Cross-Source Design Knowledge Correlation",
        ("dv_harness.design_knowledge_correlation.correlate",),
        "design_knowledge_correlation.py's real conflict/gap/documented-vs-implemented "
        "correlation across caller-declared design-knowledge sources."),
    CompletenessRowSpec(
        "design_source_inventory", "Design Source Inventory (registry table)",
        ("dv_harness.design_source_inventory.build_source_registry",),
        "design_source_inventory.py's real per-source content-hash/freshness registry over "
        "the project's own declared design sources."),
    CompletenessRowSpec(
        "spec_doc_map", "Spec/Datasheet Structural Map",
        ("dv_harness.spec_doc_map.extract_spec_doc_map",),
        "spec_doc_map.py's real pypdf-based section/table/register-chapter structural index "
        "over a project's own spec/datasheet PDF."),
    CompletenessRowSpec(
        "power_intent", "Power Intent (UPF)",
        ("dv_harness.power_intent.extract_power_intent",
         "dv_harness.power_intent.analyze_power_intent"),
        "power_intent.py's real Tcl-subset UPF parse and self-consistency analysis over the "
        "project's own power-intent file(s)."),
)


def row_ids() -> List[str]:
    return [r.row_id for r in ROWS]


def _assert_no_duplicate_row_ids() -> None:
    ids = [r.row_id for r in ROWS]
    if len(set(ids)) != len(ids):
        raise DesignCompletenessError("DUPLICATE_ROW_ID", {"row_ids": ids})


_assert_no_duplicate_row_ids()


def assert_fact_sources_resolvable() -> List[str]:
    """Every declared `fact_source` still resolves through the import
    system -- the identical anti-drift check `golden_flow_readiness.py` runs
    on its own twenty rows, applied here to these thirteen."""
    resolved: List[str] = []
    for spec in ROWS:
        for dotted in spec.fact_source:
            parts = dotted.split(".")
            obj = None
            rest: List[str] = []
            for cut in range(len(parts), 1, -1):
                try:
                    obj = importlib.import_module(".".join(parts[:cut]))
                except Exception:
                    continue
                rest = parts[cut:]
                break
            else:
                raise DesignCompletenessError("FACT_SOURCE_MODULE_UNIMPORTABLE", {
                    "fact_source": dotted, "row": spec.row_id})
            for name in rest:
                if not hasattr(obj, name):
                    raise DesignCompletenessError("FACT_SOURCE_ATTRIBUTE_MISSING", {
                        "fact_source": dotted, "row": spec.row_id, "missing_attribute": name})
                obj = getattr(obj, name)
            resolved.append(dotted)
    return resolved


# ===========================================================================
# Per-row probes
# ===========================================================================
#
# Contract, held by every probe below (mirroring golden_flow_readiness.py's
# own probe contract):
#   * takes `inputs`: the caller's per-category kwargs dict for this project,
#     or None/empty when the category was never attempted;
#   * returns {"status", "evidence", "gap"};
#   * NEVER raises -- an extractor failure is reported in the gap cell as
#     BLOCKED, never propagated past this module.

def _no_input(category_label: str) -> Dict[str, str]:
    return {
        "status": UNKNOWN,
        "evidence": "no input supplied for this category",
        "gap": f"{category_label} was never attempted for this project -- no real input "
               "was ever handed to this extractor",
    }


def _probe_register_map(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("register map extraction")
    from .register_excel_extract import (
        extract_register_map, STATUS_OK, STATUS_PARTIAL, STATUS_NOT_AVAILABLE, STATUS_PARSE_ERROR,
    )
    try:
        result = extract_register_map(**inputs)
    except Exception as e:
        return {"status": BLOCKED, "evidence": "extract_register_map() raised",
                "gap": f"{type(e).__name__}: {e}"}
    n = len(result.registers)
    evidence = f"status={result.status}; {n} register(s) extracted"
    mapping = {STATUS_OK: READY, STATUS_PARTIAL: PARTIAL,
               STATUS_NOT_AVAILABLE: UNKNOWN, STATUS_PARSE_ERROR: BLOCKED}
    status = mapping.get(result.status, UNKNOWN)
    gap = "" if status == READY else (result.reason or f"status={result.status}")
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_register_rtl_trace(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("register-to-RTL trace")
    from .register_rtl_trace import (
        RegisterFieldRef, parse_rtl_sources, trace_register_fields,
        TRACE_CONFIRMED, TRACE_PARTIAL, TRACE_NOT_FOUND,
    )
    try:
        field_dicts = inputs.get("fields") or []
        rtl_paths = inputs.get("rtl_paths") or []
        field_refs = [RegisterFieldRef(**f) for f in field_dicts]
        parsed, warnings = parse_rtl_sources(rtl_paths)
        results = trace_register_fields(field_refs, parsed)
    except Exception as e:
        return {"status": BLOCKED, "evidence": "register-to-RTL trace raised",
                "gap": f"{type(e).__name__}: {e}"}
    if not results:
        return {"status": UNKNOWN, "evidence": "no register field(s) supplied to trace",
                "gap": "no fields were declared for this project"}
    statuses = {r.status for r in results}
    evidence = f"{len(results)} field(s) traced: " + ", ".join(sorted(statuses))
    if TRACE_CONFIRMED in statuses:
        status = READY
    elif (TRACE_PARTIAL in statuses) or (TRACE_NOT_FOUND in statuses):
        status = PARTIAL
    else:
        status = UNKNOWN
    gap = "" if status == READY else (
        f"no field traced to TRACE_CONFIRMED (statuses: {sorted(statuses)})")
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_phy_boundary(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("PHY boundary extraction")
    from .phy_boundary import extract_phy_boundary
    try:
        doc = extract_phy_boundary(**inputs)
    except Exception as e:
        return {"status": BLOCKED, "evidence": "extract_phy_boundary() raised",
                "gap": f"{type(e).__name__}: {e}"}
    status = READY if doc.get("status") == "EXTRACTED" else UNKNOWN
    evidence = f"status={doc.get('status')}"
    gap = "" if status == READY else (doc.get("reason") or "")
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_phy_model_behavior(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("PHY model behavior extraction")
    from .phy_model_behavior_ir import extract_phy_model_behavior_ir
    try:
        doc = extract_phy_model_behavior_ir(**inputs)
    except Exception as e:
        return {"status": BLOCKED, "evidence": "extract_phy_model_behavior_ir() raised",
                "gap": f"{type(e).__name__}: {e}"}
    status = READY if doc.get("status") == "EXTRACTED" else UNKNOWN
    evidence = f"status={doc.get('status')}"
    gap = "" if status == READY else (doc.get("reason") or "")
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_architecture_ir(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("architecture IR")
    from .design_architecture_ir import build_architecture_ir
    try:
        ir = build_architecture_ir(**inputs)
    except Exception as e:
        return {"status": BLOCKED, "evidence": "build_architecture_ir() raised",
                "gap": f"{type(e).__name__}: {e}"}
    warnings = ir.get("warnings") or []
    evidence = f"status={ir.get('status')}; {len(ir.get('modules') or {})} module(s); " \
               f"{len(warnings)} warning(s)"
    if ir.get("status") != "BUILT":
        return {"status": UNKNOWN, "evidence": evidence, "gap": ir.get("reason") or ""}
    status = PARTIAL if warnings else READY
    gap = "; ".join(warnings) if warnings else ""
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_interrupt_dma_clock_reset(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("interrupt/DMA/clock-reset extraction")
    from .interrupt_dma_clock_reset_extraction import extract_interrupt_dma_clock_reset
    try:
        doc = extract_interrupt_dma_clock_reset(**inputs)
    except Exception as e:
        return {"status": BLOCKED, "evidence": "extract_interrupt_dma_clock_reset() raised",
                "gap": f"{type(e).__name__}: {e}"}
    if doc.get("status") != "LOADED":
        return {"status": UNKNOWN, "evidence": f"status={doc.get('status')}",
                "gap": doc.get("reason") or ""}
    facets = ("interrupt_architecture", "dma_architecture", "clock_reset_extension")
    loaded = [f for f in facets if (doc.get(f) or {}).get("status") == "LOADED"]
    evidence = f"{len(loaded)}/{len(facets)} facet(s) loaded: {loaded}"
    if len(loaded) == len(facets):
        status = READY
    else:
        status = PARTIAL
    missing = [f for f in facets if f not in loaded]
    gap = "" if status == READY else f"facet(s) not loaded: {missing}"
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_programming_sequence(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("programming sequence validation")
    from .programming_sequence_ir import (
        programming_sequence_ir_from_dict, register_facts_from_dicts, validate_step_ordering,
        STATUS_ORDER_VALID, STATUS_ORDER_INVALID, STATUS_NOT_AVAILABLE, STATUS_NOT_APPLICABLE,
        ProgrammingSequenceIRError,
    )
    try:
        ir = programming_sequence_ir_from_dict(inputs["sequence"])
        facts = register_facts_from_dicts(inputs.get("facts"))
        report = validate_step_ordering(ir, facts)
    except ProgrammingSequenceIRError as e:
        return {"status": BLOCKED, "evidence": "programming sequence document is malformed",
                "gap": str(e)}
    except Exception as e:
        return {"status": BLOCKED, "evidence": "programming-sequence validation raised",
                "gap": f"{type(e).__name__}: {e}"}
    status_val = report.get("status")
    evidence = (f"status={status_val}; steps={report.get('step_count')}; "
                f"register_facts={report.get('register_fact_count')}")
    if status_val == STATUS_ORDER_VALID:
        status, gap = READY, ""
    elif status_val == STATUS_ORDER_INVALID:
        status = PARTIAL
        gap = "; ".join(f"{f['code']} (step {f['step_index']})" for f in report.get("findings") or [])
    else:
        status = UNKNOWN
        gap = report.get("reason") or f"status={status_val}"
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_verification_intent(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("verification intent IR")
    from .verification_intent_ir import build_verification_intent_ir, DUT_EVIDENCE_FOUND, DUT_EVIDENCE_PARTIAL
    try:
        ir = build_verification_intent_ir(**inputs)
    except Exception as e:
        return {"status": BLOCKED, "evidence": "build_verification_intent_ir() raised",
                "gap": f"{type(e).__name__}: {e}"}
    plans = ir.domain_plans
    found = [d for d, p in plans.items() if p.dut_evidence_status == DUT_EVIDENCE_FOUND]
    partial = [d for d, p in plans.items() if p.dut_evidence_status == DUT_EVIDENCE_PARTIAL]
    evidence = f"{len(found)}/{len(plans)} domain(s) with DUT_EVIDENCE_FOUND, " \
               f"{len(partial)} with DUT_EVIDENCE_PARTIAL"
    if found:
        status = READY
    elif partial:
        status = PARTIAL
    else:
        status = UNKNOWN
    gap = "" if status == READY else "no domain reached DUT_EVIDENCE_FOUND for this requirement"
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_dut_evidence_correlation(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("requirement-to-RTL evidence correlation")
    from .dut_evidence_correlation import (
        correlate, STATUS_RTL_CONFIRMED, STATUS_RTL_PARTIAL, STATUS_RTL_NOT_FOUND,
        STATUS_RTL_CONTRADICTS_SPEC, STATUS_NOT_AVAILABLE,
    )
    try:
        report = correlate(**inputs)
    except Exception as e:
        return {"status": BLOCKED, "evidence": "correlate() raised",
                "gap": f"{type(e).__name__}: {e}"}
    summary = report.get("summary") or {}
    evidence = f"manifest_status={report.get('manifest_status')}; " + \
               ", ".join(f"{k}={v}" for k, v in sorted(summary.items()) if v)
    if summary.get(STATUS_RTL_CONTRADICTS_SPEC):
        return {"status": BLOCKED, "evidence": evidence,
                "gap": f"{summary[STATUS_RTL_CONTRADICTS_SPEC]} item(s) contradict recorded RTL evidence"}
    if summary.get(STATUS_RTL_CONFIRMED):
        return {"status": READY, "evidence": evidence, "gap": ""}
    if summary.get(STATUS_RTL_PARTIAL) or summary.get(STATUS_RTL_NOT_FOUND):
        return {"status": PARTIAL, "evidence": evidence,
                "gap": "no item reached RTL_CONFIRMED"}
    return {"status": UNKNOWN, "evidence": evidence,
            "gap": report.get("manifest_reason") or "no env.manifest.json evidence available"}


def _probe_design_knowledge_correlation(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("cross-source design knowledge correlation")
    from .design_knowledge_correlation import correlate, DesignKnowledgeCorrelationError
    try:
        report = correlate(**inputs)
    except DesignKnowledgeCorrelationError as e:
        return {"status": BLOCKED, "evidence": "sources are malformed", "gap": str(e)}
    except Exception as e:
        return {"status": BLOCKED, "evidence": "correlate() raised",
                "gap": f"{type(e).__name__}: {e}"}
    s = report["summary"]
    evidence = (f"sources={s['source_count']} facts={s['fact_count']} "
                f"conflicts={s['conflict_count']} gaps={s['gap_count']} "
                f"documented_vs_implemented={s['documented_vs_implemented_count']}")
    if s["source_count"] == 0:
        return {"status": UNKNOWN, "evidence": evidence, "gap": "no sources were supplied"}
    if s["conflict_count"]:
        return {"status": BLOCKED, "evidence": evidence,
                "gap": f"{s['conflict_count']} real cross-source conflict(s)"}
    if s["gap_count"] or s["documented_vs_implemented_count"]:
        return {"status": PARTIAL, "evidence": evidence,
                "gap": f"{s['gap_count']} gap(s), {s['documented_vs_implemented_count']} "
                       "documented-vs-implemented finding(s)"}
    return {"status": READY, "evidence": evidence, "gap": ""}


def _probe_design_source_inventory(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("design source inventory")
    from .design_source_inventory import build_source_registry, STATUS_NOT_AVAILABLE
    try:
        entries = inputs.get("entries") or []
        registry = build_source_registry(entries)
        rows = registry["sources"]
    except Exception as e:
        return {"status": BLOCKED, "evidence": "build_source_registry() raised",
                "gap": f"{type(e).__name__}: {e}"}
    if not rows:
        return {"status": UNKNOWN, "evidence": "no source(s) declared",
                "gap": "no source entries were supplied for this project"}
    unavailable = [r["source_id"] for r in rows if r["status"] == STATUS_NOT_AVAILABLE]
    evidence = f"{len(rows)} source(s) registered; {len(unavailable)} NOT_AVAILABLE"
    status = BLOCKED if unavailable else READY
    gap = f"declared source(s) not found on disk: {unavailable}" if unavailable else ""
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_spec_doc_map(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("spec/datasheet structural map")
    from .spec_doc_map import extract_spec_doc_map, SpecDocMapError
    try:
        doc = extract_spec_doc_map(**inputs)
    except SpecDocMapError as e:
        # A real, named "this extractor genuinely could not produce a
        # structure map" outcome (missing file, unsupported suffix, no
        # pypdf) -- extract_spec_doc_map() has no NOT_AVAILABLE status of
        # its own, it raises instead, so this IS this category's honest
        # absence, never a defect worth BLOCKING the whole rollup on.
        return {"status": UNKNOWN, "evidence": "SpecDocMapError", "gap": str(e)}
    except Exception as e:
        return {"status": BLOCKED, "evidence": "extract_spec_doc_map() raised",
                "gap": f"{type(e).__name__}: {e}"}
    n_sections = doc.get("section_count") or 0
    n_tables = doc.get("table_count") or 0
    evidence = f"{n_sections} section(s), {n_tables} table(s), " \
               f"{doc.get('register_chapter_count') or 0} register chapter(s)"
    if n_sections or n_tables:
        return {"status": READY, "evidence": evidence, "gap": ""}
    return {"status": PARTIAL, "evidence": evidence,
            "gap": "document was read but no section/table structure was found in it"}


def _probe_power_intent(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not inputs:
        return _no_input("power intent (UPF)")
    from .power_intent import extract_power_intent, analyze_power_intent
    try:
        intent = extract_power_intent(inputs.get("upf_paths") or [])
        report = analyze_power_intent(intent)
    except Exception as e:
        return {"status": BLOCKED, "evidence": "power-intent analysis raised",
                "gap": f"{type(e).__name__}: {e}"}
    evidence = f"status={report.status}; {len(intent.domains)} power domain(s)"
    mapping = {"PASS": READY, "FAIL": BLOCKED, "NOT_AVAILABLE": UNKNOWN}
    status = mapping.get(report.status, UNKNOWN)
    gap = "" if status == READY else (report.reason or "")
    return {"status": status, "evidence": evidence, "gap": gap}


#: row_id -> probe. Declared separately from ROWS so a row can never be added
#: without a probe (asserted below), mirroring golden_flow_readiness.py.
PROBES: Dict[str, Callable[[Optional[Dict[str, Any]]], Dict[str, str]]] = {
    "register_map": _probe_register_map,
    "register_rtl_trace": _probe_register_rtl_trace,
    "phy_boundary": _probe_phy_boundary,
    "phy_model_behavior": _probe_phy_model_behavior,
    "architecture_ir": _probe_architecture_ir,
    "interrupt_dma_clock_reset": _probe_interrupt_dma_clock_reset,
    "programming_sequence": _probe_programming_sequence,
    "verification_intent": _probe_verification_intent,
    "dut_evidence_correlation": _probe_dut_evidence_correlation,
    "design_knowledge_correlation": _probe_design_knowledge_correlation,
    "design_source_inventory": _probe_design_source_inventory,
    "spec_doc_map": _probe_spec_doc_map,
    "power_intent": _probe_power_intent,
}


def _assert_every_row_has_a_probe() -> None:
    missing = [r.row_id for r in ROWS if r.row_id not in PROBES]
    orphan = [k for k in PROBES if k not in {r.row_id for r in ROWS}]
    if missing or orphan:
        raise DesignCompletenessError("ROW_PROBE_SET_MISMATCH", {
            "rows_without_probe": missing, "probes_without_row": orphan})


_assert_every_row_has_a_probe()


# ===========================================================================
# The matrix
# ===========================================================================

MATRIX_COLUMNS: tuple = (
    ("row", "Extraction Category"),
    ("status", "Status"),
    ("evidence", "Evidence"),
    ("gap", "Gap"),
)


def derive_design_intelligence_completeness(
    inputs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """The completeness rollup. `inputs` is `{row_id: {kwarg: value, ...}}` --
    a project's own real per-category inputs (a register-map spreadsheet
    path, a set of RTL files, a UPF path, ...). A row whose `row_id` is
    absent from `inputs` (or maps to an empty dict) is UNKNOWN: this category
    was never attempted for this project.

    Read-only and total: every declared row appears in the output, including
    rows that never had an input supplied -- "this row is UNKNOWN" and "this
    row was omitted" must not look alike, the same rule
    `golden_flow_readiness.py`'s own matrix already states for itself.
    """
    inputs = inputs or {}
    rows: List[Dict[str, Any]] = []
    for spec in ROWS:
        try:
            probed = PROBES[spec.row_id](inputs.get(spec.row_id))
        except Exception as e:  # a probe bug must not delete a mandatory row
            probed = {"status": UNKNOWN, "evidence": NONE_CELL,
                      "gap": f"probe raised {type(e).__name__}: {e}"}
        status = probed.get("status") or UNKNOWN
        if status not in READINESS_CLASSES:
            raise DesignCompletenessError("PROBE_RETURNED_UNKNOWN_READINESS_CLASS", {
                "row": spec.row_id, "status": status, "legal_values": list(READINESS_CLASSES)})
        rows.append({
            "row_id": spec.row_id,
            "row": spec.label,
            "status": status,
            "evidence": (probed.get("evidence") or "").strip() or NONE_CELL,
            "gap": (probed.get("gap") or "").strip() or NONE_CELL,
            "fact_source": list(spec.fact_source),
            "basis": spec.basis,
        })

    counts = {cls: sum(1 for r in rows if r["status"] == cls) for cls in READINESS_CLASSES}
    verdict = combine_readiness([r["status"] for r in rows])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rows": rows,
        "summary": {
            "rows_total": len(rows),
            **{f"rows_{cls.lower()}": counts[cls] for cls in READINESS_CLASSES},
        },
        "design_intelligence_completeness": verdict,
        "completeness_rule": (
            "Worst-wins over the whole Design Intelligence extraction family: this project's "
            "completeness is READY only when every extraction category above produced real, "
            "usable facts -- one category that never got real input, or whose extractor could "
            "not produce facts at all, is never averaged away by the categories that did."),
        "authorizes": (
            "nothing. This matrix is an input to a human's intake-review decision; it approves "
            "no promotion, no generation, and no production write."),
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_design_completeness_matrix(matrix: Mapping[str, Any]) -> str:
    from .connectivity import render_markdown_table
    keys = [k for k, _ in MATRIX_COLUMNS]
    rows = [{k: _cell(r.get(k, NONE_CELL)) for k in keys} for r in (matrix.get("rows") or ())]
    return render_markdown_table(
        list(MATRIX_COLUMNS), rows,
        empty_note="(no row was produced -- this is a bug: every extraction category is "
                   "mandatory even when every one is UNKNOWN)")


def format_design_completeness_report(matrix: Mapping[str, Any]) -> str:
    summary = matrix["summary"]
    out = [
        "# DESIGN INTELLIGENCE COMPLETENESS MATRIX",
        "",
        f"**{matrix['design_intelligence_completeness']}** -- {summary['rows_ready']} ready / "
        f"{summary['rows_partial']} partial / {summary['rows_blocked']} blocked / "
        f"{summary['rows_unknown']} unknown, of {summary['rows_total']} categories.",
        "",
        f"(generated {matrix['generated_at']})",
        "",
        render_design_completeness_matrix(matrix),
        "",
        matrix["completeness_rule"],
        "",
        f"This verdict authorizes: {matrix['authorizes']}",
    ]
    blocked = [r for r in matrix.get("rows") or () if r["status"] == BLOCKED]
    if blocked:
        out += ["", "## Blocked categories", ""]
        for r in blocked:
            out.append(f"- **{r['row']}**: {r['gap']}")
    return "\n".join(out)


# ===========================================================================
# Standalone front door -- python -m dv_harness.design_completeness_gate
# (no `dv-harness` CLI verb: cli.py/gates.py are left untouched per this
# item's own scope, matching several very recent same-day modules' own
# disclosed choice to expose only a standalone `python -m` entry point.)
# ===========================================================================

def execute(inputs_path: Optional[str], as_json: bool = False) -> Tuple[str, int]:
    """Returns (text, exit_code). exit 0 every category READY, 2 otherwise --
    the same binary "unless every row is READY" contract
    `golden_flow_readiness.py`'s own CLI already uses."""
    inputs: Dict[str, Dict[str, Any]] = {}
    if inputs_path:
        with open(inputs_path, "r", encoding="utf-8") as f:
            inputs = json.load(f)
    matrix = derive_design_intelligence_completeness(inputs)
    text = json.dumps(matrix, indent=2) if as_json else format_design_completeness_report(matrix)
    code = 0 if matrix["design_intelligence_completeness"] == READY else 2
    return text, code


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.design_completeness_gate",
        description="Worst-wins completeness rollup over the Design Intelligence extraction "
                    "family's own real outputs for one project. Reads and reports only.")
    ap.add_argument("--inputs", default=None,
                     help="path to a JSON file: {row_id: {kwarg: value, ...}} per-category "
                          "real inputs for this project.")
    ap.add_argument("--json", action="store_true", help="print the full matrix as JSON")
    args = ap.parse_args(argv)
    text, code = execute(args.inputs, as_json=args.json)
    print(text)
    return code


if __name__ == "__main__":
    import sys
    sys.exit(main())
