"""dv_harness/vip_callback_hook_extraction.py -- the SIXTH VIP capability IR,
`VIPCallbackHookIR`, classifying a REAL `vip_symbol_index` document's indexed
classes as VIP CALLBACK / EXTENSION-POINT shaped -- a class whose real
inheritance chain terminates at a real UVM base-class-library callback marker
(`uvm_callback` / `uvm_callback_iter`), or one whose own declared surface is
structurally an abstract extension point (a `virtual class` declaring at
least one `virtual function`/`virtual task` that is not one of UVM's own
closed set of real PHASE methods -- excluding phase overrides is what keeps
an ordinary virtual UVM component such as a driver or monitor from being
mistaken for a callback/hook).

THIS IS A SIBLING MODULE TO `vip_capability_extraction.py`, NOT AN EDIT TO IT
-------------------------------------------------------------------------------
`vip_capability_extraction.py` already classifies a symbol index into five
capability IRs (VIPConfigIR/VIPTransactionIR/VIPScenarioPatternIR/
VIPCheckerCapabilityIR/VIPCoverageCapabilityIR) via a NAMING heuristic (a
small, disjoint suffix table, asserted disjoint at import) + an INHERITANCE
heuristic (`vip_api_card.inheritance_chain()`, reused, not reimplemented) +
the SAME 5-level qualification vocabulary
(PROJECT_PROVEN/VIP_DOCUMENTED/VIP_EXAMPLE_MATCHED/INFERRED_FROM_NAMING/
UNKNOWN) this module imports and reuses verbatim rather than re-declaring a
second, incompatible one. This module is the SIXTH capability that repeats
that exact two-heuristic + qualification-tag pattern for callback/hook
classification, kept in a sibling file rather than folded into the original
one: `vip_capability_extraction.py` is a single, large, already-shipped
module and callback/hook classification is a genuinely separate concept
(neither a data-shape capability like config/transaction, nor a
behaviour-shape capability like scenario/checker/coverage) -- growing that
file for a sixth, structurally different capability risks exactly the kind
of unrelated-concern coupling this codebase avoids elsewhere. Every
mechanism this module needs from that file (`vip_symbol_index.
validate_symbol_index()`, `vip_api_card.index_classes_by_name()` /
`inheritance_chain()`, the qualification constants, the corroborating-
evidence helpers `_read_sources()` / `_citation_evidence()` /
`_user_guide_evidence()`, and the other five capabilities' own naming-suffix
table and inheritance-marker table used ONLY to detect a real disagreement
against them) is IMPORTED and CALLED, never reimplemented.

THE NAMING HEURISTIC, CHECKED DISJOINT AT IMPORT (exactly like the original)
------------------------------------------------------------------------------
`_CALLBACK_NAME_SUFFIXES = ("cb", "callback", "hook")` -- a small suffix
table over the class name's final underscore-delimited token, checked
disjoint from `vip_capability_extraction.py`'s OWN already-disjoint suffix
table at import time via `assert_callback_suffix_disjoint_from_existing()`:
a future edit that let one of these three suffixes collide with the other
five capabilities' own tokens (`cfg`/`config`/`configuration`, `item`/`txn`/
`transaction`/`packet`/`frame`, `seq`/`sequence`/`vseq`, `monitor`/`mon`/
`checker`/`scoreboard`/`sb`, `cov`/`coverage`/`cg`) fails loudly at import
rather than silently letting one suffix claim two capabilities.

THE INHERITANCE HEURISTIC, GROUNDED IN REAL UVM BASE-CLASS TERMINOLOGY
--------------------------------------------------------------------------
A class's real inheritance chain (`vip_api_card.inheritance_chain()`, walked
over the SAME index) is checked against two small, genuinely unambiguous
signals, never a fictional one:

  1. UVM_CALLBACK_BASE_CLASS_MARKER -- the chain's terminal base is a real
     UVM base-class-library callback type: `uvm_callback` (the base every
     real project-defined callback class extends) or `uvm_callback_iter`
     (the real UVM utility class used to walk a `uvm_callbacks#(T,CB)` pool).
  2. STRUCTURAL_EXTENSION_POINT_VIRTUAL_METHODS -- attempted only when the
     chain's terminal base did NOT already match one of the other five
     capabilities' own real inheritance markers (`uvm_sequence_item`/
     `uvm_transaction`/`uvm_sequence`/`uvm_virtual_sequence`/`uvm_monitor`/
     `uvm_scoreboard`, imported from `vip_capability_extraction.py`, never a
     second copy) -- a class this bounded, so a class whose base already
     proves it is one of the other five is never second-guessed by a weaker
     structural signal. The class must be declared `virtual class` (an
     extension point is meant to be subclassed, not instantiated directly)
     AND declare at least one `virtual`/`extern` `function`/`task` whose name
     is NOT one of the real, closed set of UVM base-class-library PHASE
     method names (`build_phase`, `run_phase`, `report_phase`, ...) --
     excluding phase overrides is what keeps an ordinary virtual UVM
     component (a driver, a monitor -- both routinely declare `virtual
     function build_phase(...)`/`virtual task run_phase(...)` as their ONLY
     virtual methods) from being misclassified as a callback/hook merely for
     using the `virtual` keyword UVM's own component base classes already
     require.

WHEN NAMING AND INHERITANCE DISAGREE, NEVER GUESSED INTO EITHER SIDE
--------------------------------------------------------------------
This module's own naming/inheritance signals are, by the disjointness
guarantees above, mutually exclusive with the OTHER FIVE capabilities' own
naming/inheritance signals on any single class -- so "disagreement" here
means this module's own heuristic affirmatively says CALLBACK_HOOK while the
OTHER five capabilities' own naming or inheritance heuristic (reused, not
reimplemented) affirmatively says something else. Both directions are
checked: a class named with a callback/hook suffix whose real inheritance
chain instead terminates at one of the other five's own markers (e.g.
`uvm_sequence`), or a class whose inheritance is callback/hook-shaped but
whose name matches one of the other five's own suffixes, is reported
separately as an ambiguous candidate (`qualification: UNKNOWN`,
`ir_type: AMBIGUOUS_CAPABILITY_CANDIDATE`, the SAME sentinel
`vip_capability_extraction.IR_AMBIGUOUS` already uses) naming both
conflicting signals -- never silently classified into either side. A class
that neither of THIS module's own two heuristics recognises at all is
counted in `unclassified_class_names`, never forced into
`VIPCallbackHookIR` on the strength of a bare name.

QUALIFICATION, PROMOTED ONLY ON REAL EVIDENCE (unchanged rule, reused tag)
---------------------------------------------------------------------------
Every classified item defaults to `INFERRED_FROM_NAMING` regardless of how
strongly naming and inheritance agree -- promotion to `PROJECT_PROVEN` /
`VIP_DOCUMENTED` / `VIP_EXAMPLE_MATCHED` always requires the SAME real cited
`file:line` (project usage / VIP example usage) or document+heading
(distilled VIP user-guide reference) evidence the original module already
requires, via its own `_citation_evidence()` / `_user_guide_evidence()`
helpers, called here unmodified.

DELIBERATELY BOUNDED, AND STATED RATHER THAN IMPLIED CLOSED
--------------------------------------------------------------
(1) This is a DECLARATION-LEVEL / PARSER-LEVEL extractor over a real
    `vip_symbol_index`, never an elaborator: no `generate`/`` `ifdef ``
    condition is evaluated, no method body is read (the index it reads
    already never retains one), no live simulation and no formal proof.
    `is_virtual`/`is_extern`/method `kind` are exactly the declaration-level
    facts `vip_symbol_index.py` already records -- nothing here infers a
    fact that module's own parser did not already capture.
(2) The structural signal is intentionally conservative: it fires only when
    a class's own declared methods clear the phase-name exclusion, and only
    when no stronger, already-established inheritance marker from the other
    five capabilities already explains the class. A VIP class using an
    entirely different, project-specific naming/inheritance convention for
    its own callback base is honestly left unclassified rather than guessed.
(3) It decides nothing beyond classification: no build, job, approval, or
    stage gate, and it weakens no human-approval gate anywhere.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import vip_api_card
from . import vip_capability_extraction as vce
from . import vip_symbol_index as vsi

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# vocabulary -- REUSED, not re-declared, from vip_capability_extraction.py
# ---------------------------------------------------------------------------

PROJECT_PROVEN = vce.PROJECT_PROVEN
VIP_DOCUMENTED = vce.VIP_DOCUMENTED
VIP_EXAMPLE_MATCHED = vce.VIP_EXAMPLE_MATCHED
INFERRED_FROM_NAMING = vce.INFERRED_FROM_NAMING
UNKNOWN = vce.UNKNOWN
QUALIFICATION_LEVELS: Tuple[str, ...] = vce.QUALIFICATION_LEVELS

#: The one capability this sixth-IR module classifies.
IR_VIP_CALLBACK_HOOK = "VIPCallbackHookIR"
IR_TYPES: Tuple[str, ...] = (IR_VIP_CALLBACK_HOOK,)
#: Not a real IR -- reused verbatim from vip_capability_extraction.py so a
#: single sentinel means "naming/inheritance disagreed" across every
#: capability module in this repo, never a second spelling of the same idea.
IR_AMBIGUOUS = vce.IR_AMBIGUOUS

DEFAULT_BASE_LIBRARY_PREFIXES = vce.DEFAULT_BASE_LIBRARY_PREFIXES

# ---------------------------------------------------------------------------
# the naming heuristic, disjoint-checked against the other five capabilities
# ---------------------------------------------------------------------------

_CALLBACK_NAME_SUFFIXES: Tuple[str, ...] = ("cb", "callback", "hook")


def assert_callback_suffix_disjoint_from_existing(
    callback_suffixes: Sequence[str] = _CALLBACK_NAME_SUFFIXES,
    *, existing_table: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Build (and assert the disjointness of) this module's own naming-suffix
    table against `vip_capability_extraction.py`'s already-disjoint one --
    called at import, so a future edit that lets a callback/hook suffix
    collide with one of the other five capabilities' own suffixes fails
    immediately rather than silently misclassifying. `existing_table` is
    overridable purely so a test can inject a deliberate collision and prove
    this check has real detection power."""
    existing = existing_table if existing_table is not None else vce._NAME_SUFFIX_TO_CATEGORY
    table: Dict[str, str] = dict(existing)
    for suf in callback_suffixes:
        if suf in existing:
            raise RuntimeError(
                f"vip_callback_hook_extraction naming-suffix table collision: "
                f"{suf!r} already claimed by {existing[suf]!r} in "
                "vip_capability_extraction's own disjoint suffix table"
            )
        table[suf] = IR_VIP_CALLBACK_HOOK
    return table


# Real check, run at import.
_NAME_SUFFIX_TO_CATEGORY_WITH_CALLBACK: Dict[str, str] = assert_callback_suffix_disjoint_from_existing()


def classify_by_name(class_name: str) -> Optional[str]:
    """The naming heuristic: the class name's final underscore-delimited
    token against the small, disjoint callback/hook suffix table only.
    Returns `IR_VIP_CALLBACK_HOOK` or None -- never one of the other five
    capabilities' own IR types (use `vip_capability_extraction.
    classify_by_name()` for those, reused directly for the disagreement
    check below rather than duplicated here)."""
    token = class_name.rsplit("_", 1)[-1].lower()
    return IR_VIP_CALLBACK_HOOK if token in _CALLBACK_NAME_SUFFIXES else None


# ---------------------------------------------------------------------------
# the inheritance heuristic: a real UVM callback base-class marker, or a
# structurally bounded extension-point fallback
# ---------------------------------------------------------------------------

#: Real, closed set of UVM base-class-library callback markers. Deliberately
#: small: these are the only two real UVM base classes whose whole purpose is
#: to BE a callback/hook object or iterator, per the real UVM base class
#: library -- never a fictional or guessed base name.
_CALLBACK_INHERITANCE_MARKERS: Tuple[str, ...] = ("uvm_callback", "uvm_callback_iter")

#: Real, closed set of UVM base-class-library PHASE method names. A virtual/
#: extern method carrying one of these names is an ordinary UVM component
#: phase override (every `uvm_component` subclass may declare any of these),
#: never evidence of a project-specific callback/hook extension point --
#: excluding them is what keeps an ordinary virtual driver/monitor/agent
#: class from being misclassified as callback/hook-shaped merely because UVM
#: itself requires `virtual function`/`virtual task` for a phase override.
_UVM_PHASE_METHOD_NAMES: frozenset = frozenset({
    "build_phase", "connect_phase", "end_of_elaboration_phase",
    "start_of_simulation_phase", "run_phase", "extract_phase", "check_phase",
    "report_phase", "final_phase", "reset_phase", "configure_phase",
    "main_phase", "shutdown_phase", "pre_reset_phase", "post_reset_phase",
    "pre_configure_phase", "post_configure_phase", "pre_main_phase",
    "post_main_phase", "pre_shutdown_phase", "post_shutdown_phase",
    "phase_ready_to_end", "phase_started", "phase_ended",
})

#: The maximum number of real declared hook-method citations recorded as
#: evidence per structurally-classified class -- bounded so one class with an
#: unusually large virtual interface does not bloat the report.
MAX_HOOK_METHOD_EVIDENCE = 5


def classify_by_structural_extension_point(cls: Dict[str, Any]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """The bounded structural fallback: a `virtual class` declaring at least
    one `virtual`/`extern` `function`/`task` that is NOT one of the real UVM
    phase method names. Returns `(IR_VIP_CALLBACK_HOOK, hook_methods)` or
    `(None, [])` -- every `hook_methods` entry is a real declared method
    dict copied verbatim from the symbol index, never fabricated."""
    if not cls.get("is_virtual"):
        return None, []
    hook_methods: List[Dict[str, Any]] = []
    for m in cls.get("methods", []):
        if m.get("kind") not in ("function", "task"):
            continue
        if not (m.get("is_virtual") or m.get("is_extern")):
            continue
        if m.get("name") in _UVM_PHASE_METHOD_NAMES:
            continue
        hook_methods.append(m)
    if hook_methods:
        return IR_VIP_CALLBACK_HOOK, hook_methods
    return None, []


def classify_by_inheritance(
    by_name: Dict[str, Dict[str, Any]], cls: Dict[str, Any], class_name: str,
    *, base_library_prefixes: Sequence[str] = DEFAULT_BASE_LIBRARY_PREFIXES,
) -> Tuple[Optional[str], List[str], bool, Optional[str], Optional[str], List[Dict[str, Any]], Optional[str]]:
    """The inheritance heuristic. Returns `(category, chain, chain_closed,
    terminal_base, structural_reason, hook_methods, other_category)`:

      category          IR_VIP_CALLBACK_HOOK or None -- this module's own
                         verdict.
      structural_reason  "UVM_CALLBACK_BASE_CLASS_MARKER" (a real base-class
                         marker matched) or "STRUCTURAL_EXTENSION_POINT_
                         VIRTUAL_METHODS" (the bounded fallback fired) or
                         None.
      other_category     what vip_capability_extraction's OWN real
                         inheritance-marker table would say the terminal
                         base means for one of the OTHER FIVE capabilities
                         -- populated only when `category` is None, used
                         solely to detect a real disagreement, never
                         reimplemented from scratch."""
    chain, closed = vip_api_card.inheritance_chain(
        by_name, class_name, base_library_prefixes=base_library_prefixes)
    terminal_base = by_name[chain[-1]].get("base_class") if chain else None

    if terminal_base in _CALLBACK_INHERITANCE_MARKERS:
        return IR_VIP_CALLBACK_HOOK, chain, closed, terminal_base, "UVM_CALLBACK_BASE_CLASS_MARKER", [], None

    other_category = vce._INHERITANCE_MARKER_TO_CATEGORY.get(terminal_base) if terminal_base else None
    if other_category is None:
        struct_cat, hook_methods = classify_by_structural_extension_point(cls)
        if struct_cat:
            return (struct_cat, chain, closed, terminal_base,
                    "STRUCTURAL_EXTENSION_POINT_VIRTUAL_METHODS", hook_methods, None)

    return None, chain, closed, terminal_base, None, [], other_category


class VipCallbackHookExtractionError(ValueError):
    """Extraction cannot be performed at all -- a missing/invalid index.
    Raised rather than returning an empty report, for the same reason
    `vip_capability_extraction.VipCapabilityExtractionError` is: a mistyped
    path must never look like "nothing there"."""


# ---------------------------------------------------------------------------
# the artifact
# ---------------------------------------------------------------------------

@dataclass
class VIPCallbackHookRecord:
    """One indexed VIP class, classified as VIPCallbackHookIR (or
    IR_AMBIGUOUS), with the real evidence behind that classification and a
    qualification tag from the SAME closed 5-level vocabulary the other five
    capabilities already use."""

    ir_type: str
    class_name: str
    file: str
    line: int
    base_class: Optional[str]
    qualification: str
    basis: str                                       # NAME_AND_INHERITANCE_AGREE | NAME_ONLY |
                                                       # INHERITANCE_ONLY | NAME_AND_INHERITANCE_DISAGREE
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    inheritance_chain: List[str] = field(default_factory=list)
    chain_closed: Optional[bool] = None
    name_category: Optional[str] = None               # what naming ALONE suggested, if anything
    inheritance_category: Optional[str] = None         # what inheritance ALONE suggested, if anything
    hook_methods: List[Dict[str, Any]] = field(default_factory=list)  # real declared extension-point methods
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VIPCallbackHookExtractionReport:
    status: str
    reason: Optional[str] = None
    protocol: Optional[str] = None
    index_roots: List[str] = field(default_factory=list)
    items: List[VIPCallbackHookRecord] = field(default_factory=list)
    ambiguous: List[VIPCallbackHookRecord] = field(default_factory=list)
    unclassified_class_names: List[str] = field(default_factory=list)
    counts_by_qualification: Dict[str, int] = field(default_factory=dict)
    project_sources_scanned: int = 0
    example_sources_scanned: int = 0
    user_guide_references_scanned: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# the classifier
# ---------------------------------------------------------------------------

def extract_vip_callback_hooks(
    index: Dict[str, Any], *,
    base_library_prefixes: Sequence[str] = DEFAULT_BASE_LIBRARY_PREFIXES,
    project_sources: Optional[Any] = None, project_relative_to=None,
    example_sources: Optional[Any] = None, example_relative_to=None,
    user_guide_reference_md: Optional[Sequence] = None,
) -> VIPCallbackHookExtractionReport:
    """Classify every class in a REAL `vip_symbol_index` document as
    VIPCallbackHookIR, or report it ambiguous/unclassified.

    `index` is schema-validated here (`vip_symbol_index.validate_symbol_index`),
    the same guard the original five-capability module applies to its own
    `index` argument. `project_sources`/`example_sources`/
    `user_guide_reference_md` are all OPTIONAL corroborating evidence -- read
    via the original module's own `_read_sources()`, `_citation_evidence()`
    and `_user_guide_evidence()` helpers, never reimplemented."""
    vsi.validate_symbol_index(index)
    by_name = vip_api_card.index_classes_by_name(index)

    report = VIPCallbackHookExtractionReport(
        status="PENDING", protocol=index.get("protocol"),
        index_roots=list(index.get("roots", [])),
    )
    if not by_name:
        report.status = "NOT_AVAILABLE"
        report.reason = "VIP_SYMBOL_INDEX_CONTAINS_NO_CLASSES"
        return report

    project_texts = vce._read_sources(project_sources, project_relative_to)
    example_texts = vce._read_sources(example_sources, example_relative_to)
    guide_paths = list(user_guide_reference_md or [])
    report.project_sources_scanned = len(project_texts)
    report.example_sources_scanned = len(example_texts)
    report.user_guide_references_scanned = len(guide_paths)

    for cls in index.get("classes", []):
        name = str(cls["name"])
        name_cat = classify_by_name(name)
        other_name_cat = vce.classify_by_name(name)

        (inh_cat, chain, closed, terminal_base, structural_reason,
         hook_methods, other_inh_cat) = classify_by_inheritance(
            by_name, cls, name, base_library_prefixes=base_library_prefixes)

        base_evidence: List[Dict[str, Any]] = [{
            "kind": "VIP_SYMBOL_INDEX_DECLARATION",
            "source": cls["file"], "location": f"{cls['file']}:{cls['line']}",
            "detail": f"class {name}" + (f" extends {cls['base_class']}" if cls.get("base_class") else ""),
        }]
        if structural_reason == "STRUCTURAL_EXTENSION_POINT_VIRTUAL_METHODS":
            for m in hook_methods[:MAX_HOOK_METHOD_EVIDENCE]:
                base_evidence.append({
                    "kind": "VIP_SYMBOL_INDEX_METHOD_DECLARATION",
                    "source": m["file"], "location": f"{m['file']}:{m['line']}",
                    "detail": f"{m['kind']} {m['name']}" +
                              (" (extern)" if m.get("is_extern") else " (virtual)"),
                })

        # Disagreement, checked in both directions. Mutually exclusive by
        # construction (the suffix tables and the inheritance-marker tables
        # are disjoint, so name_cat/other_name_cat and inh_cat/other_inh_cat
        # can never both be truthy on the same class at once).
        disagreement: Optional[str] = None
        amb_name_cat = amb_inh_cat = None
        if name_cat and other_inh_cat:
            disagreement = (
                f"naming suggests {name_cat!r} but the inheritance chain "
                f"(terminal base {terminal_base!r}) suggests {other_inh_cat!r}; "
                "classification withheld rather than guessed"
            )
            amb_name_cat, amb_inh_cat = name_cat, other_inh_cat
        elif inh_cat and other_name_cat:
            via = ("a UVM callback base class" if structural_reason == "UVM_CALLBACK_BASE_CLASS_MARKER"
                   else "declared virtual/extern extension-point methods")
            disagreement = (
                f"the inheritance chain (via {via}) suggests {inh_cat!r} but naming "
                f"suggests {other_name_cat!r}; classification withheld rather than guessed"
            )
            amb_name_cat, amb_inh_cat = other_name_cat, inh_cat

        if disagreement:
            report.ambiguous.append(VIPCallbackHookRecord(
                ir_type=IR_AMBIGUOUS, class_name=name, file=cls["file"], line=cls["line"],
                base_class=cls.get("base_class"), qualification=UNKNOWN,
                basis="NAME_AND_INHERITANCE_DISAGREE", evidence=base_evidence,
                inheritance_chain=chain, chain_closed=closed,
                name_category=amb_name_cat, inheritance_category=amb_inh_cat,
                reason=disagreement,
            ))
            continue

        category = name_cat or inh_cat
        if category is None:
            report.unclassified_class_names.append(name)
            continue

        basis = ("NAME_AND_INHERITANCE_AGREE" if (name_cat and inh_cat)
                 else "NAME_ONLY" if name_cat else "INHERITANCE_ONLY")

        rec = VIPCallbackHookRecord(
            ir_type=category, class_name=name, file=cls["file"], line=cls["line"],
            base_class=cls.get("base_class"), qualification=INFERRED_FROM_NAMING,
            basis=basis, evidence=list(base_evidence),
            inheritance_chain=chain, chain_closed=closed,
            name_category=name_cat, inheritance_category=inh_cat,
            hook_methods=([dict(m) for m in hook_methods]
                          if structural_reason == "STRUCTURAL_EXTENSION_POINT_VIRTUAL_METHODS" else []),
        )

        # Promotion: the same priority order (project > documented > example)
        # the original module uses, via its own real citation scanners.
        # Never promoted on the strength of the naming/inheritance match
        # alone.
        proj_ev = vce._citation_evidence(name, project_texts, kind="PROJECT_USAGE")
        if proj_ev:
            rec.qualification = PROJECT_PROVEN
            rec.evidence += proj_ev
        else:
            guide_ev = vce._user_guide_evidence(name, guide_paths)
            if guide_ev:
                rec.qualification = VIP_DOCUMENTED
                rec.evidence += guide_ev
            else:
                ex_ev = vce._citation_evidence(name, example_texts, kind="VIP_EXAMPLE_USAGE")
                if ex_ev:
                    rec.qualification = VIP_EXAMPLE_MATCHED
                    rec.evidence += ex_ev

        report.items.append(rec)

    counts_qual: Dict[str, int] = {}
    for rec in report.items:
        counts_qual[rec.qualification] = counts_qual.get(rec.qualification, 0) + 1
    report.counts_by_qualification = counts_qual

    if report.items:
        report.status = "CLASSIFIED"
    elif report.ambiguous:
        report.status = "ONLY_AMBIGUOUS"
    else:
        report.status = "NOTHING_CLASSIFIED"
        report.reason = "NO_CLASS_MATCHED_ANY_NAMING_OR_INHERITANCE_HEURISTIC"
    return report


def classify_vip_source(
    roots, protocol: str, *,
    suffixes=vsi.DEFAULT_SOURCE_SUFFIXES, relative_to=None, **kwargs,
) -> VIPCallbackHookExtractionReport:
    """Build a REAL symbol index over `roots` with the REAL indexer
    (`vip_symbol_index.build_symbol_index()`, read-only) and classify it in
    one call. `**kwargs` forwards to `extract_vip_callback_hooks()`."""
    index = vsi.build_symbol_index(roots, protocol, suffixes=suffixes, relative_to=relative_to)
    return extract_vip_callback_hooks(index, **kwargs)


def load_index_and_classify(index_path, **kwargs) -> VIPCallbackHookExtractionReport:
    """Load an already-built symbol index (`vip_symbol_index.
    load_symbol_index()`, read-only) and classify it. `**kwargs` forwards to
    `extract_vip_callback_hooks()`."""
    p = Path(index_path)
    if not p.exists():
        raise VipCallbackHookExtractionError(
            f"VIP symbol index does not exist: {index_path} -- build one with "
            "dv_harness.vip_symbol_index.build_symbol_index() first; this classifier "
            "must never run against an index that is not there")
    try:
        index = vsi.load_symbol_index(p)
    except vsi.VipSymbolIndexError as exc:
        raise VipCallbackHookExtractionError(str(exc)) from exc
    return extract_vip_callback_hooks(index, **kwargs)


# ---------------------------------------------------------------------------
# rendering / artifact I/O / CLI
# ---------------------------------------------------------------------------

CAPABILITY_EXTRACTION_REPORT_NAME = "vip_callback_hook_extraction.json"


def format_report(report: VIPCallbackHookExtractionReport) -> str:
    lines = [f"VIP callback/hook extraction: {report.status}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    if report.protocol:
        lines.append(f"  protocol: {report.protocol}")
    lines.append(
        f"  corroboration sources scanned: project={report.project_sources_scanned}, "
        f"vip_examples={report.example_sources_scanned}, "
        f"user_guide_refs={report.user_guide_references_scanned}"
    )
    if report.counts_by_qualification:
        lines.append("  by qualification: " + ", ".join(
            f"{k}={report.counts_by_qualification.get(k, 0)}" for k in QUALIFICATION_LEVELS
            if report.counts_by_qualification.get(k, 0)))
    if report.unclassified_class_names:
        lines.append(f"  unclassified (neither heuristic matched): "
                     f"{len(report.unclassified_class_names)} "
                     f"({', '.join(report.unclassified_class_names)})")

    if report.items:
        lines += ["", f"  {IR_VIP_CALLBACK_HOOK}:"]
        for r in report.items:
            lines.append(f"    {r.class_name} [{r.qualification}, {r.basis}] at {r.file}:{r.line}")

    if report.ambiguous:
        lines += ["", "  AMBIGUOUS (naming/inheritance disagree -- not classified):"]
        for r in report.ambiguous:
            lines.append(f"    {r.class_name} at {r.file}:{r.line}: {r.reason}")
    return "\n".join(lines)


def write_capability_extraction_report(report: VIPCallbackHookExtractionReport, out_dir) -> Path:
    """Write the capability-extraction artifact. No timestamp anywhere, so an
    unchanged index regenerates byte-identically."""
    path = Path(out_dir) / CAPABILITY_EXTRACTION_REPORT_NAME
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


_STATUS_EXIT = {"CLASSIFIED": 0, "ONLY_AMBIGUOUS": 1, "NOTHING_CLASSIFIED": 2, "NOT_AVAILABLE": 2}


def execute_verb(index_path, *, project_sources=None, example_sources=None,
                 user_guide_reference_md=None, as_json: bool = False,
                 out_dir=None) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.vip_callback_hook_extraction`.
    Returns (text, exit_code): 0 classified with no ambiguity, 1 ambiguous
    candidates present, 2 NOT_AVAILABLE/nothing classified."""
    report = load_index_and_classify(
        index_path, project_sources=project_sources, example_sources=example_sources,
        user_guide_reference_md=user_guide_reference_md)
    if out_dir:
        write_capability_extraction_report(report, out_dir)
    text = json.dumps(report.to_dict(), indent=2) if as_json else format_report(report)
    code = _STATUS_EXIT.get(report.status, 2)
    if report.status == "CLASSIFIED" and report.ambiguous:
        code = 1
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.vip_callback_hook_extraction",
        description="Classify a real vip_symbol_index into VIPCallbackHookIR "
                    "(VIP callback/hook/extension-point classification), carrying the "
                    "SAME 5-level qualification tag the other five capability IRs use.")
    ap.add_argument("--index", required=True, help="vip_symbol_index JSON document.")
    ap.add_argument("--project-source", action="append", default=None, dest="project_sources",
                    help="Generated project .sv/.svh file or directory (repeatable).")
    ap.add_argument("--example-source", action="append", default=None, dest="example_sources",
                    help="VIP Examples/ .sv/.svh file or directory (repeatable).")
    ap.add_argument("--user-guide-reference-md", action="append", default=None,
                    dest="user_guide_reference_md",
                    help="A <stem>.reference.md produced by vip_user_guide_distill (repeatable).")
    ap.add_argument("--out-dir", default=None, help="Also write vip_callback_hook_extraction.json here.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(
            a.index, project_sources=a.project_sources, example_sources=a.example_sources,
            user_guide_reference_md=a.user_guide_reference_md, as_json=a.json, out_dir=a.out_dir)
    except (VipCallbackHookExtractionError, vsi.VipSymbolIndexError) as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
