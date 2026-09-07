"""dv_harness/mode_extraction.py -- spec section 286 (MODE EXTRACTION,
CLAUDE_L5_SUBSYSTEM_DESIGN_INTELLIGENCE.md), narrowed to this item's own
assigned scope: "extract real declared operating-MODE facts (a mode-select
register field and its documented legal values), reusing
register_rtl_trace.py's and sys_regmap.py's existing mode-bit machinery
rather than a parallel extractor."

REUSE OVER REINVENT -- checked before writing a line of this module
---------------------------------------------------------------------
A repo-wide grep for `ModeIR`/`DeclaredMode`/`mode_legal`/`OperatingModeFact`/
`extract_declared_modes`/`mode_entry`/`mode_exit` matched nothing executable.
Three real, similar-sounding mechanisms already exist and were read first,
per this house's "REUSE OVER REINVENT" rule:

  - `sys_regmap.py` already classifies every MODE-DETERMINING bit in a real
    sys_regmap.json document (`iter_mode_determining_bits()` /
    `mode_determining_bits()`), including a `control_kind` vocabulary that
    already distinguishes `*_select` kinds (`mux_select`/`phy_select`/
    `pinmux_select` -- a field that picks ONE of several alternative
    configurations) from plain enable/release kinds (`clock_enable`/
    `reset_release`/`power_enable` -- a binary on/off, never a multi-valued
    "mode"). This module calls that machinery directly (imported, never
    re-implemented) and narrows its result to the `*_select` subset -- the
    literal "mode-select register field" this item names. `sys_regmap.py`
    itself is NOT edited: extending its schema (a shared artifact several
    other concurrently-running extraction modules also read this same
    session) for one narrow item would be a wider-blast-radius change than
    this item needs, and everything this item asks for is reachable by
    calling the existing machinery and adding a caller-supplied fact
    alongside it (see below).
  - `register_rtl_trace.py` already traces one register field's declared
    name to real RTL signal/control-logic evidence via the real verible
    parse. This module calls it directly (`trace_register_field()` /
    `collect_rtl_sites()` / `parse_rtl_sources()`), reusing its own
    four-status honesty vocabulary (`TRACE_CONFIRMED`/`TRACE_PARTIAL`/
    `TRACE_NOT_FOUND`/`BLOCKED`) verbatim rather than inventing a second one.
  - `design_intent.py` (asset-processing row 9) already carries a NAMED,
    cited `modes` list (`{"name","description","basis"}`) transcribed from a
    controller document's own narrative prose -- a genuinely different fact
    from this item's own: a NAME-level operating mode ("HOST"/"DEVICE") is
    not a register-FIELD-level fact, carries no bit offset/width, no
    documented legal VALUE encoding, and is never traced to RTL. This module
    does not import `design_intent.py` and does not duplicate it -- the two
    are complementary artifacts (one narrative, one register-level) a
    caller may cross-reference by name; they are never merged into one
    record here.
  - `verification_intent_ir.py`'s `register_csr` domain also reuses
    `sys_regmap.required_preconditions()`/`unverifiable_bits()`, but for a
    different question entirely -- what a REQUIREMENT needs verified about a
    register PRECONDITION for Gate-2. It carries no notion of a documented
    legal-VALUE enumeration and never traces anything to RTL. No overlap.

WHAT "DOCUMENTED LEGAL VALUES" MEANS HERE, AND WHY IT IS A CALLER-SUPPLIED,
CITED DECLARATION RATHER THAN A SCHEMA EDIT
------------------------------------------------------------------------------
`sys_regmap.schema.json`'s own `field` definition carries exactly ONE
documented value per mode-determining bit -- `required_value`, "the value
this field must hold for the interface... to be operational" -- which is a
Gate-2 PRECONDITION fact, not an enumeration of every legally-documented mode
a multi-bit `*_select` field can carry (e.g. a real `PHY_MODE_SEL[1:0]`
field whose programming guide documents `0x0=USB2_ONLY`, `0x1=USB3_ONLY`,
`0x2=DUAL_ROLE`, `0x3=RESERVED`). No field in that schema, or anywhere else
in this repository, carries that enumeration. Per the Evidence Truth Rule
this module never invents one: `ModeValueDeclaration` is a plain,
duck-typed, CITATION-REQUIRED caller declaration (the same "transcribed from
a real programming guide, never invented" input-contract discipline
`sys_regmap.schema.json` and `register_map.schema.json` already state of
themselves) rather than a schema change to a shared file. Construction
refuses (`ModeExtractionError`) without a real, non-empty citation and at
least one real value/label pair -- an uncited "documented" value is exactly
the unsupported claim this rule forbids.

A mode-select bit for which NO declaration was supplied reports
`NOT_DOCUMENTED`, never a fabricated value; two declarations naming the SAME
(block, register, field) triple report `CONFLICTING_DECLARATIONS`, citing
both, and this module never arbitrates which one is correct -- the same
ARBITRATION boundary `requirement_contract.py`/`design_knowledge_correlation.py`
already keep for their own conflicting-claim findings.

WHAT THIS MODULE DOES NOT DO
------------------------------
Section 286 additionally lists entry/exit/configuration/valid
interfaces/restricted operations as things to extract per mode. This item's
own assigned scope is narrower ("a mode-select register field and its
documented legal values"), and this module stays inside that scope
honestly rather than fabricating the rest: `governs_interfaces` /
`applies_to_all_interfaces` (already real facts `sys_regmap.py` produces) are
carried through as a PARTIAL, disclosed answer to "valid interfaces" -- never
presented as a full answer to section 286's wider list. Entry/exit sequencing,
restricted-operation lists and "configuration" beyond the mode-select field's
own bit pattern are NOT extracted here; they would need a real controller-doc
narrative extractor (closer to `design_intent.py`'s own `modes` list) or a
real programming-sequence extractor (`programming_sequence_ir.py`), neither
of which this item names or this module reaches into.

This module decides nothing beyond reporting a per-bit mode-extraction
record: no build, no job, no approval, no memory write, and there is
deliberately no stage gate -- a gate that passed on a trace/declaration this
module itself says is ambiguous, conflicting or undocumented would be worse
than none. There is no `dv-harness` CLI verb: `cli.py`/`gates.py` are both
large files under heavy concurrent edit in this same multi-agent session (a
direct mtime check moments before this module was written showed `cli.py`
being actively rewritten), matching this project's own house convention of
preferring a standalone `python -m dv_harness.<module>` front door in that
circumstance.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import sys_regmap
from . import register_rtl_trace
from .register_rtl_trace import DEFAULT_VERIBLE_BIN

SCHEMA_VERSION = "1.0"

_HEX_RE = re.compile(r"^0x[0-9A-Fa-f]+$")

# --- mode-select scoping -----------------------------------------------------

#: The subset of sys_regmap.schema.json's own `control_kind` enum that
#: literally SELECTS among several alternative configurations, as opposed to
#: a binary enable/release kind. Chosen from the schema's own real vocabulary
#: -- never a guessed superset -- and cross-checked against that live schema
#: at import time by `_assert_mode_select_kinds_known()` below, so a future
#: rename/removal of one of these enum values in sys_regmap.schema.json fails
#: loudly here rather than silently narrowing (or widening) this module's
#: scope.
MODE_SELECT_CONTROL_KINDS: Tuple[str, ...] = ("mux_select", "phy_select", "pinmux_select")


class ModeExtractionError(ValueError):
    """Raised for a malformed/uncited mode-value declaration, or an
    internally-inconsistent scoping table -- the same `reason`/`detail`
    convention several sibling modules in this codebase already use, rather
    than a bare string exception."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _assert_mode_select_kinds_known() -> None:
    schema = json.loads(sys_regmap.SCHEMA_PATH.read_text(encoding="utf-8"))
    real_enum = set(schema["$defs"]["field"]["properties"]["control_kind"]["enum"])
    unknown = [k for k in MODE_SELECT_CONTROL_KINDS if k not in real_enum]
    if unknown:
        raise ModeExtractionError("MODE_SELECT_KIND_NOT_IN_SCHEMA", {
            "unknown_kinds": unknown, "schema_control_kind_enum": sorted(real_enum)})
    if sys_regmap.NOT_MODE_DETERMINING in MODE_SELECT_CONTROL_KINDS:
        raise ModeExtractionError("NOT_MODE_DETERMINING_CANNOT_BE_A_MODE_SELECT_KIND", {})


_assert_mode_select_kinds_known()


def mode_select_bits(doc: dict, interface: Optional[str] = None) -> List[dict]:
    """The subset of `sys_regmap.mode_determining_bits(doc, interface=...)`
    whose `control_kind` is a real `*_select` kind -- reused verbatim
    (imported, called, never re-implemented), just narrowed to the literal
    "mode-select register field" this item names. Sorted exactly as
    `sys_regmap.mode_determining_bits()` already sorts (by absolute address
    then bit offset), so this list stays diffable the same way that one is."""
    return [b for b in sys_regmap.mode_determining_bits(doc, interface=interface)
            if b.get("control_kind") in MODE_SELECT_CONTROL_KINDS]


def bit_qualified_name(bit: dict) -> str:
    return f"{bit.get('block')}.{bit.get('register')}.{bit.get('field')}"


# --- documented legal values: a cited, caller-supplied declaration ----------

LEGAL_VALUES_DOCUMENTED = "DOCUMENTED"
LEGAL_VALUES_NOT_DOCUMENTED = "NOT_DOCUMENTED"
LEGAL_VALUES_CONFLICTING = "CONFLICTING_DECLARATIONS"

LEGAL_VALUES_STATUSES = (
    LEGAL_VALUES_DOCUMENTED, LEGAL_VALUES_NOT_DOCUMENTED, LEGAL_VALUES_CONFLICTING,
)


@dataclass(frozen=True)
class ModeValueEntry:
    """One documented legal encoding of a mode-select field -- e.g.
    `value="0x1"`, `label="USB3_ONLY"`. Same hex-string convention as
    `sys_regmap.schema.json`'s own `required_value` (`^0x[0-9A-Fa-f]+$`),
    deliberately identical so the two can be compared without a translation
    layer (see `cross_check_required_value()` below)."""
    value: str
    label: str
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.value or not _HEX_RE.match(self.value):
            raise ModeExtractionError("MODE_VALUE_ENTRY_BAD_VALUE", {
                "value": self.value, "hint": "expected a hex string like '0x1'"})
        if not self.label or not str(self.label).strip():
            raise ModeExtractionError("MODE_VALUE_ENTRY_MISSING_LABEL", {"value": self.value})

    def to_dict(self) -> dict:
        return {"value": self.value, "label": self.label, "description": self.description}


@dataclass(frozen=True)
class ModeValueDeclaration:
    """One caller-supplied, CITED declaration of every documented legal value
    for one mode-select field, identified by the same (block, register,
    field) triple `sys_regmap.py`'s own bit records already carry. Refuses
    to construct (`ModeExtractionError`) without a real citation and at
    least one real, non-duplicate value/label pair -- an uncited
    "documented" legal value is exactly the unsupported claim the Evidence
    Truth Rule forbids."""
    block: str
    register: str
    field: str
    values: Tuple[ModeValueEntry, ...]
    citation: str
    source_kind: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("block", "register", "field"):
            if not getattr(self, name) or not str(getattr(self, name)).strip():
                raise ModeExtractionError("MODE_VALUE_DECLARATION_MISSING_IDENTITY", {
                    "field": name, "declaration": self.qualified_name()})
        if not self.citation or not str(self.citation).strip():
            raise ModeExtractionError("MODE_VALUE_DECLARATION_NO_CITATION", {
                "declaration": self.qualified_name(),
                "hint": "a documented legal value requires a real citation "
                        "(programming guide section, RTL file:line, register "
                        "spec reference) -- never an uncited claim"})
        if not self.values:
            raise ModeExtractionError("MODE_VALUE_DECLARATION_NO_VALUES", {
                "declaration": self.qualified_name()})
        seen = set()
        dupes = set()
        for v in self.values:
            norm = v.value.lower()
            if norm in seen:
                dupes.add(v.value)
            seen.add(norm)
        if dupes:
            raise ModeExtractionError("MODE_VALUE_DECLARATION_DUPLICATE_VALUE", {
                "declaration": self.qualified_name(), "duplicate_values": sorted(dupes)})

    def qualified_name(self) -> str:
        return f"{self.block}.{self.register}.{self.field}"

    def matches_bit(self, bit: dict) -> bool:
        return (self.block == bit.get("block")
                and self.register == bit.get("register")
                and self.field == bit.get("field"))

    def to_dict(self) -> dict:
        return {
            "block": self.block, "register": self.register, "field": self.field,
            "values": [v.to_dict() for v in self.values],
            "citation": self.citation, "source_kind": self.source_kind,
        }


def mode_value_declaration_from_dict(d: dict) -> ModeValueDeclaration:
    """Builds a `ModeValueDeclaration` from a plain dict -- the shape a
    caller transcribing a real programming guide/register spec would
    naturally assemble by hand. Duck-typed rather than requiring a
    `ModeValueEntry`/`ModeValueDeclaration` instance for every value."""
    if not isinstance(d, dict):
        raise ModeExtractionError("MODE_VALUE_DECLARATION_NOT_A_DICT", {"got": type(d).__name__})
    raw_values = d.get("values")
    if not isinstance(raw_values, list):
        raise ModeExtractionError("MODE_VALUE_DECLARATION_VALUES_NOT_A_LIST", {
            "declaration": f"{d.get('block')}.{d.get('register')}.{d.get('field')}"})
    values = []
    for rv in raw_values:
        if not isinstance(rv, dict):
            raise ModeExtractionError("MODE_VALUE_ENTRY_NOT_A_DICT", {"got": type(rv).__name__})
        values.append(ModeValueEntry(
            value=rv.get("value"), label=rv.get("label"), description=rv.get("description")))
    return ModeValueDeclaration(
        block=d.get("block"), register=d.get("register"), field=d.get("field"),
        values=tuple(values), citation=d.get("citation"), source_kind=d.get("source_kind"),
    )


def mode_value_declarations_from_list(items: Optional[Sequence[dict]]) -> List[ModeValueDeclaration]:
    return [mode_value_declaration_from_dict(d) for d in (items or [])]


def _match_declarations(bit: dict, declarations: Sequence[ModeValueDeclaration]) -> List[ModeValueDeclaration]:
    return [d for d in declarations if d.matches_bit(bit)]


def cross_check_required_value(bit: dict, declaration: Optional[ModeValueDeclaration]) -> Optional[dict]:
    """A mode-select bit may separately carry a Gate-2 `required_value` --
    `sys_regmap.py`'s own real, already-extracted precondition fact -- and a
    caller may separately declare the field's full documented legal-value
    enumeration. Both are real facts about the same field; when both are
    present this checks they AGREE (the required value is one of the
    documented legal ones) rather than silently trusting them to. A real
    disagreement is returned as a finding, never resolved by picking one --
    the same ARBITRATION boundary this module keeps everywhere else. Returns
    `None` when there is nothing to cross-check (no required_value, or no
    documented declaration to check it against)."""
    required = bit.get("required_value")
    if not required or declaration is None:
        return None
    documented = {v.value.lower() for v in declaration.values}
    if required.lower() in documented:
        return None
    return {
        "finding": "REQUIRED_VALUE_NOT_IN_DOCUMENTED_LEGAL_VALUES",
        "bit": bit_qualified_name(bit),
        "required_value": required,
        "documented_values": sorted(v.value for v in declaration.values),
        "reason": (
            f"sys_regmap.json declares required_value={required!r} for "
            f"{bit_qualified_name(bit)}, but the supplied documented legal-value "
            f"declaration (citation: {declaration.citation!r}) does not list that "
            "value -- the two documented facts disagree and this module does not "
            "arbitrate which one is correct."
        ),
    }


# --- the composed per-bit record ---------------------------------------------

MODE_FACT_CONFIRMED = "MODE_FACT_CONFIRMED"
MODE_FACT_RTL_UNCONFIRMED = "MODE_FACT_RTL_UNCONFIRMED"
MODE_FACT_VALUES_NOT_DOCUMENTED = "MODE_FACT_VALUES_NOT_DOCUMENTED"
MODE_FACT_RTL_NOT_FOUND = "MODE_FACT_RTL_NOT_FOUND"
MODE_FACT_RTL_BLOCKED = "MODE_FACT_RTL_BLOCKED"
MODE_FACT_CONFLICTING_DECLARATIONS = "MODE_FACT_CONFLICTING_DECLARATIONS"

#: Worst-first priority used by `_derive_overall_status()` -- a real
#: contradiction between two documented sources outranks everything, an
#: evidence gap on the RTL side outranks an evidence gap on the
#: documentation side only because "we never looked" (BLOCKED) is a
#: stronger absence than "we looked and it is not there" (NOT_FOUND), and
#: both outrank a merely-undocumented value set, which itself outranks a
#: real but ambiguous RTL match. Never averaged -- one bad fact anywhere
#: keeps the whole record from reading MODE_FACT_CONFIRMED.
_STATUS_PRIORITY = (
    MODE_FACT_CONFLICTING_DECLARATIONS,
    MODE_FACT_RTL_BLOCKED,
    MODE_FACT_RTL_NOT_FOUND,
    MODE_FACT_VALUES_NOT_DOCUMENTED,
    MODE_FACT_RTL_UNCONFIRMED,
    MODE_FACT_CONFIRMED,
)


def _derive_overall_status(legal_values_status: str, rtl_status: str) -> str:
    if legal_values_status == LEGAL_VALUES_CONFLICTING:
        return MODE_FACT_CONFLICTING_DECLARATIONS
    if rtl_status == register_rtl_trace.TRACE_BLOCKED:
        return MODE_FACT_RTL_BLOCKED
    if rtl_status == register_rtl_trace.TRACE_NOT_FOUND:
        return MODE_FACT_RTL_NOT_FOUND
    if legal_values_status == LEGAL_VALUES_NOT_DOCUMENTED:
        return MODE_FACT_VALUES_NOT_DOCUMENTED
    if rtl_status == register_rtl_trace.TRACE_PARTIAL:
        return MODE_FACT_RTL_UNCONFIRMED
    return MODE_FACT_CONFIRMED


@dataclass
class ModeExtractionRecord:
    """One mode-select register field's fully-assembled operating-mode fact:
    the real sys_regmap bit, whichever documented legal-value declaration
    (if any) names it, and the real RTL trace `register_rtl_trace.py`
    produced for it -- three independently-sourced facts, never merged into
    one guessed answer."""
    bit: dict
    legal_values_status: str
    legal_values: List[ModeValueEntry]
    legal_value_citation: Optional[str]
    conflicting_citations: List[str]
    required_value_conflict: Optional[dict]
    rtl_trace: "register_rtl_trace.RegisterTraceResult"
    status: str

    @property
    def qualified_name(self) -> str:
        return bit_qualified_name(self.bit)

    def to_dict(self) -> dict:
        return {
            "field": self.qualified_name,
            "control_kind": self.bit.get("control_kind"),
            "absolute_address": self.bit.get("absolute_address"),
            "bit_offset": self.bit.get("bit_offset"),
            "bit_width": self.bit.get("bit_width"),
            "declared_required_value": self.bit.get("required_value"),
            "declared_valid_interfaces": {
                "governs_interfaces": list(self.bit.get("governs_interfaces") or []),
                "applies_to_all_interfaces": self.bit.get("applies_to_all_interfaces"),
                "disclosure": (
                    "a PARTIAL fact only -- which interfaces this bit governs, "
                    "not entry/exit sequencing, restricted operations, or a "
                    "per-value interface list; see module docstring's bounds."
                ),
            },
            "legal_values_status": self.legal_values_status,
            "legal_values": [v.to_dict() for v in self.legal_values],
            "legal_value_citation": self.legal_value_citation,
            "conflicting_citations": list(self.conflicting_citations),
            "required_value_conflict": self.required_value_conflict,
            "rtl_trace": self.rtl_trace.to_dict(),
            "status": self.status,
        }


@dataclass
class ModeExtractionReport:
    records: List[ModeExtractionRecord]
    interface: Optional[str]
    unmatched_declarations: List[ModeValueDeclaration] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "interface": self.interface,
            "mode_select_control_kinds": list(MODE_SELECT_CONTROL_KINDS),
            "records": [r.to_dict() for r in self.records],
            "unmatched_declarations": [
                {"declaration": d.qualified_name(), "citation": d.citation}
                for d in self.unmatched_declarations
            ],
        }

    def summary(self) -> dict:
        counts: Dict[str, int] = {s: 0 for s in _STATUS_PRIORITY}
        for r in self.records:
            counts[r.status] = counts.get(r.status, 0) + 1
        return {"total": len(self.records), "counts": counts}


def extract_declared_modes(
    sys_regmap_doc: dict,
    *,
    interface: Optional[str] = None,
    mode_value_declarations: Optional[Sequence[ModeValueDeclaration]] = None,
    rtl_corpus: Optional[Sequence] = None,
    rtl_paths: Optional[Sequence] = None,
    verible_bin: str = DEFAULT_VERIBLE_BIN,
) -> ModeExtractionReport:
    """The one entry point this module exists to provide. Reuses
    `sys_regmap.validate_sys_regmap()` (fail-closed -- a mode fact must never
    be computed from a sys_regmap document that did not actually validate,
    the same discipline that module's own docstring states of itself),
    `mode_select_bits()` above, and `register_rtl_trace`'s own tracing
    machinery, over one already-parsed RTL corpus (`rtl_corpus`, in any of
    the shapes `register_rtl_trace.collect_rtl_sites()` accepts) or a set of
    real source paths to parse fresh (`rtl_paths`, via
    `register_rtl_trace.parse_rtl_sources()`) -- pass at most one of the
    two; passing neither is legal and yields an honest `BLOCKED` RTL trace
    for every record, exactly as `register_rtl_trace.py` itself reports for
    an empty corpus."""
    sys_regmap.validate_sys_regmap(sys_regmap_doc)
    bits = mode_select_bits(sys_regmap_doc, interface=interface)
    declarations = list(mode_value_declarations or [])

    parse_warnings: List[dict] = []
    corpus = rtl_corpus
    if rtl_paths is not None:
        parsed, parse_warnings = register_rtl_trace.parse_rtl_sources(rtl_paths, verible_bin=verible_bin)
        corpus = parsed
    sites = register_rtl_trace.collect_rtl_sites(corpus)

    matched_declaration_ids = set()
    records: List[ModeExtractionRecord] = []
    for bit in bits:
        matches = _match_declarations(bit, declarations)
        if len(matches) > 1:
            legal_values_status = LEGAL_VALUES_CONFLICTING
            legal_values: List[ModeValueEntry] = []
            legal_value_citation = None
            conflicting_citations = [d.citation for d in matches]
            required_value_conflict = None
            for d in matches:
                matched_declaration_ids.add(id(d))
        elif len(matches) == 1:
            decl = matches[0]
            matched_declaration_ids.add(id(decl))
            legal_values_status = LEGAL_VALUES_DOCUMENTED
            legal_values = list(decl.values)
            legal_value_citation = decl.citation
            conflicting_citations = []
            required_value_conflict = cross_check_required_value(bit, decl)
        else:
            legal_values_status = LEGAL_VALUES_NOT_DOCUMENTED
            legal_values = []
            legal_value_citation = None
            conflicting_citations = []
            required_value_conflict = cross_check_required_value(bit, None)

        field_ref = register_rtl_trace.RegisterFieldRef(
            name=bit["field"], register_name=bit.get("register"), block_name=bit.get("block"),
        )
        trace = register_rtl_trace.trace_register_field(
            field_ref, sites=sites, parse_warnings=parse_warnings)

        overall = _derive_overall_status(legal_values_status, trace.status)
        records.append(ModeExtractionRecord(
            bit=bit, legal_values_status=legal_values_status, legal_values=legal_values,
            legal_value_citation=legal_value_citation, conflicting_citations=conflicting_citations,
            required_value_conflict=required_value_conflict, rtl_trace=trace, status=overall,
        ))

    unmatched = [d for d in declarations if id(d) not in matched_declaration_ids]
    return ModeExtractionReport(records=records, interface=interface, unmatched_declarations=unmatched)


# --- rendering / CLI ---------------------------------------------------------

def render_markdown(report: ModeExtractionReport) -> str:
    from .connectivity import render_markdown_table

    rows = []
    for r in report.records:
        values_text = (
            ", ".join(f"{v.value}={v.label}" for v in r.legal_values)
            if r.legal_values else "(none documented)"
        )
        rows.append({
            "field": r.qualified_name,
            "control_kind": r.bit.get("control_kind"),
            "legal_values_status": r.legal_values_status,
            "legal_values": values_text,
            "rtl_trace_status": r.rtl_trace.status,
            "status": r.status,
        })
    columns = [
        ("field", "Mode-Select Field"), ("control_kind", "Control Kind"),
        ("legal_values_status", "Legal Values"), ("legal_values", "Documented Values"),
        ("rtl_trace_status", "RTL Trace"), ("status", "Overall"),
    ]
    lines = [
        f"Mode extraction ({MODE_SELECT_CONTROL_KINDS}): {len(report.records)} "
        f"mode-select field(s)" + (f" for interface {report.interface!r}" if report.interface else ""),
        "",
        render_markdown_table(columns, rows),
    ]
    if report.unmatched_declarations:
        lines.append("")
        lines.append(
            f"WARNING: {len(report.unmatched_declarations)} supplied mode-value "
            "declaration(s) named a (block, register, field) triple that is not "
            "a mode-select bit in the supplied sys_regmap document:")
        for d in report.unmatched_declarations:
            lines.append(f"  - {d.qualified_name()} (citation: {d.citation!r})")
    return "\n".join(lines)


def execute_verb(
    sys_regmap_path: str,
    *,
    interface: Optional[str] = None,
    mode_values_path: Optional[str] = None,
    rtl_paths: Optional[Sequence[str]] = None,
    as_json: bool = False,
    verible_bin: str = DEFAULT_VERIBLE_BIN,
) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.mode_extraction`.
    Returns (text, exit_code): 0 every mode-select field MODE_FACT_CONFIRMED,
    1 at least one is not, 2 nothing could be extracted / a usage or
    validation error."""
    try:
        doc = sys_regmap.load_sys_regmap(sys_regmap_path)
    except sys_regmap.SysRegmapValidationError as exc:
        return f"sys_regmap at {sys_regmap_path!r} failed validation: {exc}", 2
    except (OSError, json.JSONDecodeError) as exc:
        return f"could not read sys_regmap at {sys_regmap_path!r}: {exc}", 2

    declarations: List[ModeValueDeclaration] = []
    if mode_values_path:
        try:
            with open(mode_values_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            declarations = mode_value_declarations_from_list(raw)
        except (OSError, json.JSONDecodeError) as exc:
            return f"could not read mode-value declarations at {mode_values_path!r}: {exc}", 2
        except ModeExtractionError as exc:
            return f"{exc.reason}: {json.dumps(exc.detail)}", 2

    report = extract_declared_modes(
        doc, interface=interface, mode_value_declarations=declarations,
        rtl_paths=rtl_paths, verible_bin=verible_bin,
    )

    if not report.records:
        text = (
            "no mode-select register field found in the supplied sys_regmap "
            f"document (control_kind in {MODE_SELECT_CONTROL_KINDS})"
            + (f" for interface {interface!r}" if interface else "")
        )
        return (json.dumps({"records": []}, indent=2) if as_json else text), 2

    text = (
        json.dumps(report.to_dict(), indent=2) if as_json else render_markdown(report)
    )
    exit_code = 0 if all(r.status == MODE_FACT_CONFIRMED for r in report.records) else 1
    return text, exit_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.mode_extraction",
        description=(
            "Extract declared operating-MODE facts (mode-select register "
            "fields and their documented legal values) by reusing "
            "sys_regmap.py's mode-bit classification and register_rtl_trace.py's "
            "RTL tracing."))
    ap.add_argument("--sys-regmap", required=True, help="Path to a sys_regmap.json document.")
    ap.add_argument("--interface", default=None, help="Restrict to bits governing this interface.")
    ap.add_argument("--mode-values", dest="mode_values_path", default=None,
                     help="Path to a JSON list of mode-value declarations "
                          "(see mode_value_declaration_from_dict()).")
    ap.add_argument("--rtl", action="append", dest="rtl_paths", default=None,
                     help="An RTL source file to parse and trace against (repeatable).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.sys_regmap, interface=a.interface, mode_values_path=a.mode_values_path,
        rtl_paths=a.rtl_paths, as_json=a.json,
    )
    print(text)
    return code


if __name__ == "__main__":
    import sys
    sys.exit(main())
