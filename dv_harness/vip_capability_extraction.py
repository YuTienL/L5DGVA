"""dv_harness/vip_capability_extraction.py -- classify a REAL `vip_symbol_index`
into the five capability-IR shapes a downstream generator/gap-analysis would
need (VIPConfigIR / VIPTransactionIR / VIPScenarioPatternIR /
VIPCheckerCapabilityIR / VIPCoverageCapabilityIR), each carrying a 5-level
qualification tag (2026-09-06).

THE GAP THIS CLOSES
-------------------
`vip_symbol_index.py` already turns a VIP source tree into real class/method/
config-field/analysis-port DECLARATIONS with a real `file:line` each, but by
its own docstring's insistence it is a NAVIGATION aid: `find_symbol()` answers
"where do I read about this name". Nothing in this repo ever asked the next
question a generator or a gap-analysis actually needs answered: "of everything
this VIP declares, which classes are its CONFIG objects, which are
TRANSACTIONS, which are reusable SCENARIO PATTERNS (sequences a pattern author
could build on), which are CHECKING capability (monitors/scoreboards) and
which are COVERAGE capability" -- and, for each answer, HOW SURE are we, and
on what real evidence.

THE FABRICATION RISK, AND HOW THIS MODULE IS BUILT TO REFUSE IT
----------------------------------------------------------------
A VIP class name and its `extends` clause are heuristics, not proof. A class
whose name ends `_seq` is USUALLY a sequence; a class extending
`uvm_sequence_item` USUALLY is a transaction. "Usually" is exactly the word
CLAUDE.md's Evidence Truth Rule refuses to launder into a confident label, so
every classification this module makes is qualified, never asserted bare, and
the qualification vocabulary is a CLOSED, 5-level scale re-used from the same
discipline `vip_api_card.py` already established for VIP API citations
(PROVEN/BLOCKED/UNPROVABLE/OUT_OF_SCOPE/NOT_AVAILABLE) -- not a second,
incompatible confidence vocabulary invented here:

  PROJECT_PROVEN        The class is really CITED (declared as a handle type,
                         called on, or scope-resolved) in project source the
                         caller supplied -- a real `file:line` in THIS
                         project, not the VIP.
  VIP_DOCUMENTED         The class name appears as a real section heading in a
                         VIP user-guide reference distilled by
                         `vip_user_guide_distill.py` -- a real citable
                         document + heading, never prose this module invented.
  VIP_EXAMPLE_MATCHED    The class is really cited in VIP `Examples/` source
                         the caller supplied -- a real `file:line` in the
                         VIP's own reference testbenches.
  INFERRED_FROM_NAMING   The default for every classified item with NO
                         external corroboration: naming and/or inheritance
                         heuristics over the symbol index alone. This is the
                         honest floor for a heuristic match -- even a class
                         whose name AND inheritance chain both agree stays
                         here unless one of the three stronger sources above
                         actually corroborates it. Reaching PROJECT_PROVEN/
                         VIP_DOCUMENTED/VIP_EXAMPLE_MATCHED always requires a
                         real cited `file:line` (or document+heading);
                         nothing here promotes on the strength of the
                         heuristic alone.
  UNKNOWN                Naming and inheritance heuristics DISAGREE (one
                         suggests one capability, the other a different one).
                         Classification is withheld rather than guessed: the
                         item is reported separately as an ambiguous
                         candidate, in neither of the two disagreeing
                         categories, and can never be promoted past UNKNOWN --
                         corroborating evidence cannot resolve which of two
                         disagreeing categories is correct.

REUSE, NOT REINVENTION
-----------------------
There is no second indexer, no second inheritance walker and no second
citation scanner here. `vip_symbol_index.build_symbol_index()` /
`load_symbol_index()` / `validate_symbol_index()` are the only way a symbol
index is ever produced or read, called READ-ONLY. `vip_api_card`'s own
`index_classes_by_name()`, `inheritance_chain()` and `extract_api_citations()`
are imported and called directly rather than re-derived: this module asks the
same "which real declaration proves this" question `vip_api_card` already
answers for generated-sequence citations, aimed instead at the VIP's OWN
indexed classes and at project/example source that might cite them.

WHAT MAKES A CLASSIFICATION "NAMING" VS. "INHERITANCE", AND WHY BOTH
----------------------------------------------------------------------
Naming: the class name's final underscore-delimited token against five
disjoint suffix sets (`_cfg`/`_config` -> config, `_item`/`_txn`/
`_transaction`/`_packet`/`_frame` -> transaction, `_seq`/`_sequence`/`_vseq`
-> scenario pattern, `_monitor`/`_mon`/`_checker`/`_scoreboard`/`_sb` ->
checker, `_cov`/`_coverage`/`_cg` -> coverage). Disjointness is asserted at
import (`assert_naming_categories_disjoint()`), so a single suffix can never
silently claim two categories.

Inheritance: the class's REAL inheritance chain (`vip_api_card.
inheritance_chain()`, walked over the SAME index) against a small, genuinely
unambiguous set of UVM base-class-library markers -- `uvm_sequence_item`/
`uvm_transaction` (transaction), `uvm_sequence`/`uvm_virtual_sequence`
(scenario pattern, "a class extending a known svt_*_sequence base is a
scenario-pattern candidate" generalizes to: a class whose chain terminates at
`uvm_sequence` is one, whether that happens directly or through an
intermediate VIP-declared base sequence the chain walks through first), and
`uvm_monitor`/`uvm_scoreboard` (checker). Config and coverage have NO
inheritance marker: `uvm_object` is far too generic a base to distinguish a
config object from a callback, a coverage wrapper, or a transaction VIPs that
(unusually) build on `uvm_object` directly, and asserting one would be exactly
the invented specificity this module exists to refuse. Those two categories
are naming-only by design, and every record says so in its `basis` field.

When naming and inheritance both fire and AGREE, the item classifies with
`basis: NAME_AND_INHERITANCE_AGREE`. When only one fires, `NAME_ONLY` or
`INHERITANCE_ONLY`. When both fire and DISAGREE, the item is never silently
assigned to either side -- it is reported as an ambiguous candidate with
`qualification: UNKNOWN`, naming both signals so a human can resolve it. A
class neither heuristic recognises (e.g. a driver or agent class -- neither
is one of the five tracked capabilities) is simply not classified into any of
the five IRs, and is counted, never fabricated into one.

DELIBERATELY BOUNDED, AND STATED RATHER THAN IMPLIED CLOSED
--------------------------------------------------------------
(1) This is a HEURISTIC classifier over DECLARATIONS. It proves nothing about
    behaviour -- a class matching every naming and inheritance signal for
    "checker" is not asserted to actually check anything; the qualification
    tag says exactly how that classification was reached, never more.
(2) Coverage classification is naming-only and structurally weak: the
    underlying `vip_symbol_index` does not index covergroups at all (only
    classes/methods/fields/analysis ports), so a real coverage WRAPPER class
    is the only thing naming can find here; a bare `covergroup` block with no
    enclosing class is invisible to this module exactly as it is to the
    indexer it reads.
(3) `PROJECT_PROVEN`/`VIP_EXAMPLE_MATCHED` reuse `vip_api_card.
    extract_api_citations()`'s declaration-level citation scan, with the same
    honest limits that module documents (an unresolvable receiver is never a
    citation; property access is never a citation).
(4) `VIP_DOCUMENTED` reads a real `<stem>.reference.md` file
    `vip_user_guide_distill.distill_user_guide()` already produces -- its
    real heading table only, never the full-text extract or any prose, so
    this module never pulls a VIP user-guide PDF's body into context.
(5) It decides nothing beyond classification: no build, no job, no approval,
    no stage gate, and it weakens no human-approval gate anywhere.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import vip_api_card
from . import vip_symbol_index

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# vocabularies
# ---------------------------------------------------------------------------

#: The 5-level qualification tag, reusing vip_api_card's confidence
#: discipline (a real cited source line or nothing) rather than inventing a
#: second, incompatible vocabulary.
PROJECT_PROVEN = "PROJECT_PROVEN"
VIP_DOCUMENTED = "VIP_DOCUMENTED"
VIP_EXAMPLE_MATCHED = "VIP_EXAMPLE_MATCHED"
INFERRED_FROM_NAMING = "INFERRED_FROM_NAMING"
UNKNOWN = "UNKNOWN"
QUALIFICATION_LEVELS: Tuple[str, ...] = (
    PROJECT_PROVEN, VIP_DOCUMENTED, VIP_EXAMPLE_MATCHED, INFERRED_FROM_NAMING, UNKNOWN,
)

#: The five capability-IR shapes this module classifies indexed classes into.
IR_VIP_CONFIG = "VIPConfigIR"
IR_VIP_TRANSACTION = "VIPTransactionIR"
IR_VIP_SCENARIO_PATTERN = "VIPScenarioPatternIR"
IR_VIP_CHECKER_CAPABILITY = "VIPCheckerCapabilityIR"
IR_VIP_COVERAGE_CAPABILITY = "VIPCoverageCapabilityIR"
IR_TYPES: Tuple[str, ...] = (
    IR_VIP_CONFIG, IR_VIP_TRANSACTION, IR_VIP_SCENARIO_PATTERN,
    IR_VIP_CHECKER_CAPABILITY, IR_VIP_COVERAGE_CAPABILITY,
)
#: Not a real IR -- a candidate whose naming and inheritance signals
#: disagreed. Never emitted in `report.items`, only in `report.ambiguous`.
IR_AMBIGUOUS = "AMBIGUOUS_CAPABILITY_CANDIDATE"

#: Reused directly from vip_api_card: which non-indexed bases close an
#: inheritance chain (never a second definition of "the world is closed").
DEFAULT_BASE_LIBRARY_PREFIXES = vip_api_card.DEFAULT_BASE_LIBRARY_PREFIXES

# naming: last underscore-token -> IR type. Disjoint by construction, and
# asserted so at import.
_NAME_SUFFIX_CATEGORY_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (IR_VIP_CONFIG, ("cfg", "config", "configuration")),
    (IR_VIP_TRANSACTION, ("item", "txn", "transaction", "packet", "frame")),
    (IR_VIP_SCENARIO_PATTERN, ("seq", "sequence", "vseq")),
    (IR_VIP_CHECKER_CAPABILITY, ("monitor", "mon", "checker", "scoreboard", "sb")),
    (IR_VIP_COVERAGE_CAPABILITY, ("cov", "coverage", "cg")),
)

# inheritance: a REAL, unambiguous UVM base-class-library marker -> IR type.
# Deliberately small: `uvm_object`/`uvm_component` are too generic to decide
# config/coverage/anything else, so they carry no entry here (see module
# docstring point on why config/coverage are naming-only).
_INHERITANCE_MARKER_TO_CATEGORY: Dict[str, str] = {
    "uvm_sequence_item": IR_VIP_TRANSACTION,
    "uvm_transaction": IR_VIP_TRANSACTION,
    "uvm_sequence": IR_VIP_SCENARIO_PATTERN,
    "uvm_virtual_sequence": IR_VIP_SCENARIO_PATTERN,
    "uvm_monitor": IR_VIP_CHECKER_CAPABILITY,
    "uvm_scoreboard": IR_VIP_CHECKER_CAPABILITY,
}


def assert_naming_categories_disjoint() -> Dict[str, str]:
    """Build (and assert the disjointness of) the naming-suffix table. Called
    at import so a future edit that lets one suffix claim two categories
    fails immediately rather than silently misclassifying."""
    table: Dict[str, str] = {}
    for category, suffixes in _NAME_SUFFIX_CATEGORY_GROUPS:
        for suf in suffixes:
            if suf in table:
                raise RuntimeError(
                    f"vip_capability_extraction naming-suffix table collision: "
                    f"{suf!r} claimed by both {table[suf]!r} and {category!r}"
                )
            table[suf] = category
    return table


_NAME_SUFFIX_TO_CATEGORY: Dict[str, str] = assert_naming_categories_disjoint()


class VipCapabilityExtractionError(ValueError):
    """Extraction cannot be performed at all -- a missing/invalid index, or a
    source root that does not exist. Raised rather than returning an empty
    report, for the same reason `vip_symbol_index.iter_source_files()` raises
    on a missing root: a mistyped path must never look like "nothing there"."""


# ---------------------------------------------------------------------------
# classification heuristics
# ---------------------------------------------------------------------------

def classify_by_name(class_name: str) -> Optional[str]:
    """The naming heuristic: the class name's final underscore-delimited
    token against the disjoint suffix table. Returns an IR type or None."""
    token = class_name.rsplit("_", 1)[-1].lower()
    return _NAME_SUFFIX_TO_CATEGORY.get(token)


def classify_by_inheritance(
    by_name: Dict[str, Dict[str, Any]], class_name: str,
    *, base_library_prefixes: Sequence[str] = DEFAULT_BASE_LIBRARY_PREFIXES,
) -> Tuple[Optional[str], List[str], bool, Optional[str]]:
    """The inheritance heuristic: walk the REAL chain (`vip_api_card.
    inheritance_chain()`, over the SAME index) and check whether it
    terminates at one of the small set of unambiguous UVM base-class-library
    markers. Returns `(ir_type_or_None, chain, chain_closed, terminal_base)`.

    `terminal_base` is the base of the last class in `chain` -- None for a
    real root (no `extends` at all), otherwise the identifier the chain
    leaves the index on (a UVM marker, an unindexed non-UVM class, or a
    cyclic index)."""
    chain, closed = vip_api_card.inheritance_chain(
        by_name, class_name, base_library_prefixes=base_library_prefixes)
    terminal_base = by_name[chain[-1]].get("base_class") if chain else None
    category = _INHERITANCE_MARKER_TO_CATEGORY.get(terminal_base) if terminal_base else None
    return category, chain, closed, terminal_base


# ---------------------------------------------------------------------------
# corroborating evidence: project usage / VIP examples / VIP user guide
# ---------------------------------------------------------------------------

def _read_sources(sources: Optional[Iterable], relative_to=None) -> List[Tuple[str, str]]:
    """Read `sources` (files/dirs) into `[(relativized label, text), ...]`,
    reusing `vip_symbol_index.iter_source_files()`/`_relativize()` -- the same
    file-discovery and labelling `vip_api_card.validate_vip_api_usage()`
    already uses for the sources it scans, not a second implementation."""
    if not sources:
        return []
    try:
        files = vip_symbol_index.iter_source_files(list(sources))
    except vip_symbol_index.VipSymbolIndexError as exc:
        raise VipCapabilityExtractionError(str(exc)) from exc
    base = Path(relative_to) if relative_to else None
    out: List[Tuple[str, str]] = []
    for f in files:
        text = Path(f).read_text(encoding="utf-8", errors="replace")
        out.append((vip_symbol_index._relativize(f, base), text))
    return out


def _citation_evidence(class_name: str, texts: Sequence[Tuple[str, str]], *,
                       kind: str, max_evidence: int = 3) -> List[Dict[str, Any]]:
    """Real citations of `class_name` in `texts`, via `vip_api_card.
    extract_api_citations()` -- the same declaration-level citation scanner
    used to validate a generated sequence's VIP API calls, aimed here at
    "does anything real cite this VIP class at all". Bounded to
    `max_evidence` so one heavily-reused class does not bloat the report."""
    out: List[Dict[str, Any]] = []
    for label, text in texts:
        for cit in vip_api_card.extract_api_citations(text):
            if cit.vip_class != class_name:
                continue
            out.append({
                "kind": kind, "source": label, "location": f"{label}:{cit.line}",
                "detail": cit.text,
            })
            if len(out) >= max_evidence:
                return out
    return out


_SECTION_INDEX_HEADER = "## Section index"
_SECTION_ROW_RE = re.compile(r"^\|\s*(?P<heading>.+?)\s*\|\s*[^|]*\|\s*[^|]*\|\s*$")


def parse_reference_md_headings(path) -> List[str]:
    """The real section headings out of a `<stem>.reference.md` file
    `vip_user_guide_distill.distill_user_guide()` already produces -- its
    "## Section index" table only. Every heading returned here is a literal
    heading string from the real document, per that module's own guarantee
    ("every line below is a heading that literally appears in the source
    document"); no prose, no full-text extract, is ever read by this
    function."""
    p = Path(path)
    if not p.exists():
        raise VipCapabilityExtractionError(
            f"VIP user-guide reference markdown does not exist: {path} -- build one with "
            "dv_harness.vip_user_guide_distill.distill_user_guide() first")
    headings: List[str] = []
    in_table = False
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.rstrip()
        if line.strip() == _SECTION_INDEX_HEADER:
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            if headings:
                break
            continue
        m = _SECTION_ROW_RE.match(line)
        if not m:
            continue
        heading = m.group("heading").strip()
        if heading in ("Section", "") or set(heading) <= {"-"}:
            continue
        headings.append(heading)
    return headings


def _user_guide_evidence(class_name: str, reference_md_paths: Sequence,
                         *, max_evidence: int = 3) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    needles = {class_name.lower(), class_name.lower().replace("_", " ")}
    for path in reference_md_paths:
        for heading in parse_reference_md_headings(path):
            low = heading.lower()
            if any(n in low for n in needles):
                out.append({
                    "kind": "VIP_USER_GUIDE_SECTION", "source": str(path),
                    "location": str(path), "detail": heading,
                })
                if len(out) >= max_evidence:
                    return out
    return out


# ---------------------------------------------------------------------------
# the artifact
# ---------------------------------------------------------------------------

@dataclass
class VIPCapabilityRecord:
    """One indexed VIP class, classified into one of the five capability IRs
    (or `IR_AMBIGUOUS`), with the real evidence behind that classification and
    a qualification tag from the closed 5-level vocabulary above."""

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
    # Category-specific payload -- populated only for the relevant ir_type,
    # left at its empty/None default otherwise. Never fabricated: every value
    # here is copied verbatim from the real vip_symbol_index class entry.
    config_fields: List[Dict[str, Any]] = field(default_factory=list)     # CONFIG, TRANSACTION
    analysis_ports: List[Dict[str, Any]] = field(default_factory=list)    # CHECKER
    pattern_kind: Optional[str] = None                                    # SCENARIO_PATTERN
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VIPCapabilityExtractionReport:
    status: str
    reason: Optional[str] = None
    protocol: Optional[str] = None
    index_roots: List[str] = field(default_factory=list)
    items: List[VIPCapabilityRecord] = field(default_factory=list)
    ambiguous: List[VIPCapabilityRecord] = field(default_factory=list)
    unclassified_class_names: List[str] = field(default_factory=list)
    counts_by_ir_type: Dict[str, int] = field(default_factory=dict)
    counts_by_qualification: Dict[str, int] = field(default_factory=dict)
    project_sources_scanned: int = 0
    example_sources_scanned: int = 0
    user_guide_references_scanned: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    def by_ir_type(self, ir_type: str) -> List[VIPCapabilityRecord]:
        return [r for r in self.items if r.ir_type == ir_type]


# ---------------------------------------------------------------------------
# the classifier
# ---------------------------------------------------------------------------

def extract_vip_capabilities(
    index: Dict[str, Any], *,
    base_library_prefixes: Sequence[str] = DEFAULT_BASE_LIBRARY_PREFIXES,
    project_sources: Optional[Iterable] = None, project_relative_to=None,
    example_sources: Optional[Iterable] = None, example_relative_to=None,
    user_guide_reference_md: Optional[Sequence] = None,
) -> VIPCapabilityExtractionReport:
    """Classify every class in a REAL `vip_symbol_index` document into one of
    the five capability IRs, or report it ambiguous/unclassified.

    `index` is schema-validated here (`vip_symbol_index.validate_symbol_index`)
    so a hand-made dict cannot slip past as a real index -- the same guard
    `vip_api_card.validate_vip_api_usage()` applies to its own index argument.

    `project_sources`/`example_sources`/`user_guide_reference_md` are all
    OPTIONAL corroborating evidence. Supplying none of them is legitimate: every
    classified item then honestly stays at `INFERRED_FROM_NAMING`, and the
    report's `*_scanned` counters make that fact visible rather than silent."""
    vip_symbol_index.validate_symbol_index(index)
    by_name = vip_api_card.index_classes_by_name(index)

    report = VIPCapabilityExtractionReport(
        status="PENDING", protocol=index.get("protocol"),
        index_roots=list(index.get("roots", [])),
    )
    if not by_name:
        report.status = "NOT_AVAILABLE"
        report.reason = "VIP_SYMBOL_INDEX_CONTAINS_NO_CLASSES"
        return report

    project_texts = _read_sources(project_sources, project_relative_to)
    example_texts = _read_sources(example_sources, example_relative_to)
    guide_paths = list(user_guide_reference_md or [])
    report.project_sources_scanned = len(project_texts)
    report.example_sources_scanned = len(example_texts)
    report.user_guide_references_scanned = len(guide_paths)

    for cls in index.get("classes", []):
        name = str(cls["name"])
        name_cat = classify_by_name(name)
        inherit_cat, chain, closed, terminal_base = classify_by_inheritance(
            by_name, name, base_library_prefixes=base_library_prefixes)

        base_evidence = [{
            "kind": "VIP_SYMBOL_INDEX_DECLARATION",
            "source": cls["file"], "location": f"{cls['file']}:{cls['line']}",
            "detail": f"class {name}" + (f" extends {cls['base_class']}" if cls.get("base_class") else ""),
        }]

        if name_cat and inherit_cat and name_cat != inherit_cat:
            report.ambiguous.append(VIPCapabilityRecord(
                ir_type=IR_AMBIGUOUS, class_name=name, file=cls["file"], line=cls["line"],
                base_class=cls.get("base_class"), qualification=UNKNOWN,
                basis="NAME_AND_INHERITANCE_DISAGREE", evidence=base_evidence,
                inheritance_chain=chain, chain_closed=closed,
                name_category=name_cat, inheritance_category=inherit_cat,
                reason=(f"naming suggests {name_cat!r} but the inheritance chain "
                        f"(terminal base {terminal_base!r}) suggests {inherit_cat!r}; "
                        "classification withheld rather than guessed"),
            ))
            continue

        category = name_cat or inherit_cat
        if category is None:
            report.unclassified_class_names.append(name)
            continue

        basis = ("NAME_AND_INHERITANCE_AGREE" if (name_cat and inherit_cat)
                 else "NAME_ONLY" if name_cat else "INHERITANCE_ONLY")

        rec = VIPCapabilityRecord(
            ir_type=category, class_name=name, file=cls["file"], line=cls["line"],
            base_class=cls.get("base_class"), qualification=INFERRED_FROM_NAMING,
            basis=basis, evidence=list(base_evidence),
            inheritance_chain=chain, chain_closed=closed,
            name_category=name_cat, inheritance_category=inherit_cat,
        )

        if category in (IR_VIP_CONFIG, IR_VIP_TRANSACTION):
            rec.config_fields = list(cls.get("config_fields") or [])
        if category == IR_VIP_CHECKER_CAPABILITY:
            rec.analysis_ports = list(cls.get("analysis_ports") or [])
        if category == IR_VIP_SCENARIO_PATTERN:
            rec.pattern_kind = (
                "VIRTUAL_SEQUENCE"
                if terminal_base == "uvm_virtual_sequence" or name.lower().rsplit("_", 1)[-1] == "vseq"
                else "SEQUENCE"
            )

        # Promotion: the strongest REAL evidence found wins, in the priority
        # order the qualification vocabulary itself declares. Never promoted
        # on the strength of the naming/inheritance match alone.
        proj_ev = _citation_evidence(name, project_texts, kind="PROJECT_USAGE")
        if proj_ev:
            rec.qualification = PROJECT_PROVEN
            rec.evidence += proj_ev
        else:
            guide_ev = _user_guide_evidence(name, guide_paths)
            if guide_ev:
                rec.qualification = VIP_DOCUMENTED
                rec.evidence += guide_ev
            else:
                ex_ev = _citation_evidence(name, example_texts, kind="VIP_EXAMPLE_USAGE")
                if ex_ev:
                    rec.qualification = VIP_EXAMPLE_MATCHED
                    rec.evidence += ex_ev

        report.items.append(rec)

    counts_ir: Dict[str, int] = {}
    counts_qual: Dict[str, int] = {}
    for rec in report.items:
        counts_ir[rec.ir_type] = counts_ir.get(rec.ir_type, 0) + 1
        counts_qual[rec.qualification] = counts_qual.get(rec.qualification, 0) + 1
    report.counts_by_ir_type = counts_ir
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
    roots: Iterable, protocol: str, *,
    suffixes: Iterable[str] = vip_symbol_index.DEFAULT_SOURCE_SUFFIXES,
    relative_to=None, **kwargs,
) -> VIPCapabilityExtractionReport:
    """Build a REAL symbol index over `roots` with the REAL indexer
    (`vip_symbol_index.build_symbol_index()`, read-only) and classify it in
    one call. `**kwargs` forwards to `extract_vip_capabilities()`."""
    index = vip_symbol_index.build_symbol_index(roots, protocol, suffixes=suffixes,
                                                 relative_to=relative_to)
    return extract_vip_capabilities(index, **kwargs)


def load_index_and_classify(index_path, **kwargs) -> VIPCapabilityExtractionReport:
    """Load an already-built symbol index (`vip_symbol_index.
    load_symbol_index()`, read-only) and classify it. `**kwargs` forwards to
    `extract_vip_capabilities()`."""
    p = Path(index_path)
    if not p.exists():
        raise VipCapabilityExtractionError(
            f"VIP symbol index does not exist: {index_path} -- build one with "
            "dv_harness.vip_symbol_index.build_symbol_index() first; this classifier "
            "must never run against an index that is not there")
    try:
        index = vip_symbol_index.load_symbol_index(p)
    except vip_symbol_index.VipSymbolIndexError as exc:
        raise VipCapabilityExtractionError(str(exc)) from exc
    return extract_vip_capabilities(index, **kwargs)


# ---------------------------------------------------------------------------
# rendering / artifact I/O / CLI
# ---------------------------------------------------------------------------

CAPABILITY_EXTRACTION_REPORT_NAME = "vip_capability_extraction.json"


def format_report(report: VIPCapabilityExtractionReport) -> str:
    lines = [f"VIP capability extraction: {report.status}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    if report.protocol:
        lines.append(f"  protocol: {report.protocol}")
    lines.append(
        f"  corroboration sources scanned: project={report.project_sources_scanned}, "
        f"vip_examples={report.example_sources_scanned}, "
        f"user_guide_refs={report.user_guide_references_scanned}"
    )
    if report.counts_by_ir_type:
        lines.append("  by IR type: " + ", ".join(
            f"{k}={v}" for k, v in sorted(report.counts_by_ir_type.items())))
    if report.counts_by_qualification:
        lines.append("  by qualification: " + ", ".join(
            f"{k}={report.counts_by_qualification.get(k, 0)}" for k in QUALIFICATION_LEVELS
            if report.counts_by_qualification.get(k, 0)))
    if report.unclassified_class_names:
        lines.append(f"  unclassified (neither heuristic matched): "
                     f"{len(report.unclassified_class_names)} "
                     f"({', '.join(report.unclassified_class_names)})")

    for ir_type in IR_TYPES:
        rows = report.by_ir_type(ir_type)
        if not rows:
            continue
        lines += ["", f"  {ir_type}:"]
        for r in rows:
            lines.append(f"    {r.class_name} [{r.qualification}, {r.basis}] "
                        f"at {r.file}:{r.line}")

    if report.ambiguous:
        lines += ["", "  AMBIGUOUS (naming/inheritance disagree -- not classified):"]
        for r in report.ambiguous:
            lines.append(f"    {r.class_name} at {r.file}:{r.line}: {r.reason}")
    return "\n".join(lines)


def write_capability_extraction_report(report: VIPCapabilityExtractionReport, out_dir) -> Path:
    """Write the capability-extraction artifact. No timestamp anywhere, so an
    unchanged index regenerates byte-identically."""
    path = Path(out_dir) / CAPABILITY_EXTRACTION_REPORT_NAME
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


_STATUS_EXIT = {"CLASSIFIED": 0, "ONLY_AMBIGUOUS": 1, "NOTHING_CLASSIFIED": 2, "NOT_AVAILABLE": 2}


def execute_verb(index_path, *, project_sources=None, example_sources=None,
                 user_guide_reference_md=None, as_json: bool = False,
                 out_dir=None) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.vip_capability_extraction`.
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
        prog="python -m dv_harness.vip_capability_extraction",
        description="Classify a real vip_symbol_index into VIPConfigIR/VIPTransactionIR/"
                    "VIPScenarioPatternIR/VIPCheckerCapabilityIR/VIPCoverageCapabilityIR, "
                    "each carrying a 5-level qualification tag.")
    ap.add_argument("--index", required=True, help="vip_symbol_index JSON document.")
    ap.add_argument("--project-source", action="append", default=None, dest="project_sources",
                    help="Generated project .sv/.svh file or directory (repeatable).")
    ap.add_argument("--example-source", action="append", default=None, dest="example_sources",
                    help="VIP Examples/ .sv/.svh file or directory (repeatable).")
    ap.add_argument("--user-guide-reference-md", action="append", default=None,
                    dest="user_guide_reference_md",
                    help="A <stem>.reference.md produced by vip_user_guide_distill (repeatable).")
    ap.add_argument("--out-dir", default=None, help="Also write vip_capability_extraction.json here.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(
            a.index, project_sources=a.project_sources, example_sources=a.example_sources,
            user_guide_reference_md=a.user_guide_reference_md, as_json=a.json, out_dir=a.out_dir)
    except (VipCapabilityExtractionError, vip_symbol_index.VipSymbolIndexError) as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
