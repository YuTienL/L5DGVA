"""dv_harness/vip_api_card.py -- spec section 187's VIPApiCard artifact and the
coded "if the API cannot be proven -> UNKNOWN / BLOCKED" enforcement
(2026-09-06).

THE GAP THIS CLOSES
-------------------
Section 187 states a VIP API flow and a stop condition:

    Need Operation -> Search VIP Example -> Manual / Source / Class Reference
    -> Extract Exact API -> Validate Signature -> VIPApiCard -> Generate Sequence

    If API cannot be proven:  UNKNOWN / BLOCKED

Before this module, that flow existed in this repo ONLY as prose instruction to
an LLM. `.claude/skills/CORE/vip-scenario-branch/SKILL.md` says
"禁止憑猜測 invent VIP API/class/sequence" and lists the same
example->manual->source->class-reference ladder; `pcie-environment-builder`
repeats it. Grepping the whole tree for `VIPApiCard`, `vip_api_card`,
`validate_vip_api_usage` or `UNPROVABLE` matched NOTHING executable. There was
no artifact, and -- more seriously -- no code path anywhere rejected or even
flagged a VIP API call the harness could not prove exists. A generated sequence
citing a hallucinated `svt_usb_agent.reconfigur()` went out of the generator
byte-identically to one citing the real method, and the first thing that would
notice was a VCS compile.

The closest real cousin, and what this reuses rather than rebuilds:
`dv_harness/vip_symbol_index.py` already indexes a VIP source tree into real
class/method/field DECLARATIONS with a real `file:line` for each. But it is a
NAVIGATION aid by its own docstring's insistence -- `find_symbol()` answers
"where do I read about this name", and nothing ever asked it the validation
question "is this call I just emitted actually declared anywhere in what you
indexed". This module asks exactly that question, of that same index. There is
no second indexer here: `index_source_text()` is imported and used, both to
read the index and to discover the LOCALLY declared classes of the sources
under validation.

WHAT A VIPApiCard IS
--------------------
One record per VIP API citation found in generated source: which VIP
class/method was cited, where the generated code cites it, the real
`file:line` in the VIP source that the index resolved it to (or nothing, when
it resolved to nothing), which class in the inheritance chain actually declares
it, and a validation status. It is the evidence artifact section 187 names, and
it is derived entirely from a real index over real VIP source -- never from the
model's prior knowledge of what a VIP "usually" provides.

THE FOUR STATUSES, and why BLOCKED is narrow on purpose
-------------------------------------------------------
  PROVEN       Resolved to a real declaration at a real file:line in the index.

  BLOCKED      Provably absent. This is the strong claim, so it requires ALL
               of: (1) the receiver's declared type is a class the index really
               contains, (2) the member is absent from that class's entire
               indexed inheritance chain, (3) every base in that chain that is
               NOT indexed is a declared BASE LIBRARY class (`uvm_*` by
               default) rather than an unknown VIP class -- i.e. the world is
               closed for VIP purposes -- and (4) the member is not one of the
               documented SystemVerilog/UVM base-library methods below. A
               fabricated VIP CLASS name (in VIP scope, absent from the index,
               and not declared locally by the sources themselves) is likewise
               BLOCKED.

  UNPROVABLE   Cannot be decided from this index: the inheritance chain leaves
               the index into an unknown non-library base, or the citation is a
               kind the index does not model. Section 187's "UNKNOWN" -- it is
               NOT a pass, and it is never silently dropped.

  OUT_OF_SCOPE Not a VIP API citation at all: a class the validated sources
               declare themselves, a SystemVerilog/UVM base-library method, a
               receiver whose type this scan could not resolve. Counted, not
               reported as a finding, and NEVER blocked -- an unresolved
               receiver is our ignorance, not the generator's error.

HONESTY RULES, enforced in code
-------------------------------
  * "We could not check" is never PROVEN. An empty index, no sources, or a
    citation this module cannot decide reports NOT_AVAILABLE / UNPROVABLE with
    a concrete reason.
  * PROPERTY access (`cfg.some_field`) is deliberately NOT checked.
    `vip_symbol_index._FIELD_RE` indexes only a restricted set of data types,
    so a field's ABSENCE from the index does not prove the field does not
    exist, and blocking on it would manufacture false failures. Only method
    CALLS, class TYPE citations and `Class::` scope citations are decided.
  * `Class::MEMBER` decides the CLASS only. The index models no enum
    constants, parameters or typedefs, so the member half is not judged.
  * The base-library method allowlist below can only make this module MORE
    permissive (it converts a would-be BLOCKED into OUT_OF_SCOPE). An
    incomplete allowlist is the one false-positive risk here, which is why the
    generation-path wiring is non-blocking unless a caller opts in with
    `strict_vip_api`, exactly as `uvm_structural_lint` is.
  * Nothing here approves, waives, builds, runs or submits anything, and
    nothing here weakens any human-approval gate. It reports.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import vip_symbol_index

SCHEMA_VERSION = "1.0"

#: Report/card statuses. Section 187's own vocabulary: proven, or
#: "UNKNOWN / BLOCKED".
PROVEN = "PROVEN"
BLOCKED = "BLOCKED"
UNPROVABLE = "UNPROVABLE"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
NOT_AVAILABLE = "NOT_AVAILABLE"

#: Bases that are not VIP classes: reaching one CLOSES the inheritance chain
#: for VIP purposes (a method absent from the whole VIP chain below it either
#: belongs to the base library -- see BASE_LIBRARY_METHODS -- or does not
#: exist). Everything else that leaves the index leaves it OPEN, and an open
#: chain can only ever yield UNPROVABLE.
DEFAULT_BASE_LIBRARY_PREFIXES: Tuple[str, ...] = ("uvm_",)

#: SystemVerilog LRM / UVM base-class-library methods. A call to one of these
#: on a VIP handle is not a VIP API citation: it is the base library's own API,
#: which this index does not (and should not) contain. Listing them here can
#: only DOWNGRADE a finding -- BLOCKED becomes OUT_OF_SCOPE -- so an omission
#: from this list produces a false BLOCKED, never a false PROVEN. That is the
#: documented residual risk of this module, and the reason the generation-path
#: wiring is non-blocking by default.
BASE_LIBRARY_METHODS: frozenset = frozenset({
    # SystemVerilog built-ins on any class handle
    "new", "randomize", "pre_randomize", "post_randomize", "srandom",
    "get_randstate", "set_randstate", "rand_mode", "constraint_mode",
    # uvm_object
    "create", "clone", "copy", "compare", "print", "sprint", "record",
    "pack", "pack_bytes", "pack_ints", "unpack", "unpack_bytes", "unpack_ints",
    "do_copy", "do_compare", "do_print", "do_record", "do_pack", "do_unpack",
    "convert2string", "get_name", "get_full_name", "set_name", "get_type",
    "get_type_name", "get_object_type", "get_inst_id", "get_inst_count",
    "get_uvm_seeding", "set_uvm_seeding", "reseed",
    # uvm_component / uvm_report_object
    "build_phase", "connect_phase", "end_of_elaboration_phase",
    "start_of_simulation_phase", "run_phase", "extract_phase", "check_phase",
    "report_phase", "final_phase", "phase_started", "phase_ready_to_end",
    "phase_ended", "get_parent", "get_children", "get_child", "get_depth",
    "set_report_verbosity_level", "set_report_verbosity_level_hier",
    "set_report_id_action", "set_report_severity_action", "get_report_verbosity_level",
    "uvm_report_info", "uvm_report_warning", "uvm_report_error", "uvm_report_fatal",
    # uvm_sequence_item / uvm_sequence / uvm_sequencer
    "start", "start_item", "finish_item", "body", "pre_body", "post_body",
    "pre_start", "post_start", "pre_do", "mid_do", "post_do",
    "set_item_context", "set_sequencer", "get_sequencer", "set_parent_sequence",
    "get_parent_sequence", "get_sequence_id", "set_id_info", "wait_for_grant",
    "send_request", "wait_for_item_done", "get_response", "use_response_handler",
    "set_priority", "get_priority", "kill", "do_kill", "is_item", "is_blocked",
    "has_lock", "lock", "unlock", "grab", "ungrab",
    # uvm_phase / objections
    "raise_objection", "drop_objection", "get_objection", "get_name_of_phase",
    # TLM ports
    "connect", "write", "put", "get", "peek", "try_put", "try_get", "try_peek",
    "get_next_item", "try_next_item", "item_done", "size", "is_empty", "used",
})

#: Reasons carried on a non-PROVEN card. SCREAMING_SNAKE_CASE, the same
#: convention every typed error/finding in this package uses.
R_CLASS_NOT_INDEXED = "VIP_CLASS_NOT_IN_SYMBOL_INDEX"
R_METHOD_NOT_INDEXED = "METHOD_NOT_DECLARED_IN_INDEXED_VIP_CHAIN"
R_CHAIN_OPEN = "INHERITANCE_CHAIN_LEAVES_INDEX"
R_LOCAL_CLASS = "CLASS_DECLARED_BY_THE_VALIDATED_SOURCES"
R_BASE_LIBRARY = "SYSTEMVERILOG_OR_UVM_BASE_LIBRARY_MEMBER"
R_RECEIVER_UNRESOLVED = "RECEIVER_TYPE_NOT_RESOLVABLE_BY_THIS_SCAN"
R_NOT_VIP_SCOPE = "IDENTIFIER_NOT_IN_VIP_NAMING_SCOPE"


class VipApiValidationError(ValueError):
    """A validation cannot be performed at all -- a missing index file, an
    index that fails its own schema, a source root that does not exist. Raised
    rather than reported as a clean report, for the same reason
    `vip_symbol_index.iter_source_files()` raises on a missing root: a mistyped
    path must never be indistinguishable from "nothing to check"."""


# ---------------------------------------------------------------------------
# the artifact
# ---------------------------------------------------------------------------

@dataclass
class VipApiCard:
    """Section 187's VIPApiCard: one VIP API citation, and whether the real VIP
    symbol index can prove it.

    `resolved_file`/`resolved_line` are the REAL location in the VIP source
    that `vip_symbol_index` recorded -- the "Manual / Source / Class Reference"
    leg of section 187's ladder, present as a citable location rather than as a
    claim that a human once looked something up."""

    citation: str                                   # "svt_demo_cfg.apply_preset"
    kind: str                                       # CLASS | METHOD | SCOPE_CLASS
    vip_class: str
    member: Optional[str]
    status: str                                     # PROVEN|BLOCKED|UNPROVABLE|OUT_OF_SCOPE
    usage_file: str
    usage_line: int
    usage_text: str
    resolved_file: Optional[str] = None
    resolved_line: Optional[int] = None
    resolved_signature: Optional[str] = None
    resolved_kind: Optional[str] = None             # function | task | class
    declared_by: Optional[str] = None               # class in the chain that declares it
    inheritance_chain: List[str] = field(default_factory=list)
    chain_closed: Optional[bool] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def location(self) -> Optional[str]:
        """`file:line` of the real declaration, the form section 187's
        "Class Reference" leg is cited in everywhere else in this repo."""
        if self.resolved_file is None or self.resolved_line is None:
            return None
        return f"{self.resolved_file}:{self.resolved_line}"


@dataclass
class VipApiValidationReport:
    status: str
    reason: Optional[str] = None
    protocol: Optional[str] = None
    index_roots: List[str] = field(default_factory=list)
    vip_scope_prefixes: List[str] = field(default_factory=list)
    local_classes: List[str] = field(default_factory=list)
    files_scanned: int = 0
    counts: Dict[str, int] = field(default_factory=dict)
    cards: List[VipApiCard] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["cards"] = [c.to_dict() for c in self.cards]
        return d

    def blocked(self) -> List[VipApiCard]:
        return [c for c in self.cards if c.status == BLOCKED]

    def unprovable(self) -> List[VipApiCard]:
        return [c for c in self.cards if c.status == UNPROVABLE]


# ---------------------------------------------------------------------------
# scope: which identifiers are VIP identifiers at all
# ---------------------------------------------------------------------------

def derive_vip_scope_prefixes(index: Dict[str, Any], *, min_classes: int = 2) -> List[str]:
    """The VIP naming scope, DERIVED from the real index rather than hardcoded.

    A VIP tree names its classes with a shared vendor/protocol token
    (`svt_usb_transfer`, `svt_usb_agent`, ...). The first underscore-delimited
    token of every indexed class, where at least `min_classes` classes share
    it, is that scope. Nothing here knows the string "svt" -- point this at an
    index of `cust_*` classes and the scope is `cust_`.

    Scope matters in exactly one direction: an identifier OUTSIDE it is never
    blocked, because a class this VIP index was never meant to contain must not
    look like a fabrication. An identifier INSIDE it that the index does not
    contain is a fabricated VIP name."""
    counts: Dict[str, int] = {}
    for cls in index.get("classes", []):
        name = str(cls.get("name", ""))
        head, sep, _rest = name.partition("_")
        if not sep or not head:
            continue
        counts[head + "_"] = counts.get(head + "_", 0) + 1
    return sorted(p for p, n in counts.items() if n >= min_classes)


def _in_vip_scope(name: str, prefixes: Sequence[str]) -> bool:
    return any(name.startswith(p) for p in prefixes)


# ---------------------------------------------------------------------------
# resolution against the real vip_symbol_index
# ---------------------------------------------------------------------------

def index_classes_by_name(index: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """`{class name -> class entry}` over a real `vip_symbol_index` document.
    The first declaration wins on a duplicate name, matching the index's own
    file/line sort order, so resolution is deterministic."""
    out: Dict[str, Dict[str, Any]] = {}
    for cls in index.get("classes", []):
        out.setdefault(str(cls["name"]), cls)
    return out


def inheritance_chain(by_name: Dict[str, Dict[str, Any]], class_name: str,
                      *, base_library_prefixes: Sequence[str] = DEFAULT_BASE_LIBRARY_PREFIXES
                      ) -> Tuple[List[str], bool]:
    """`(chain, closed)` for one indexed class.

    `chain` is the indexed classes walked, most-derived first. `closed` says
    whether the walk ended somewhere that makes ABSENCE provable: a class with
    no base at all, or a base that is a declared BASE LIBRARY class (`uvm_*`).
    A base that is neither indexed nor a library class leaves the chain OPEN --
    the index simply does not cover that part of the hierarchy, and no absence
    below it can be claimed.

    A cycle (a corrupt index claiming `A extends B extends A`) terminates the
    walk and reports the chain OPEN rather than looping."""
    chain: List[str] = []
    seen: Set[str] = set()
    current = class_name
    while current and current in by_name and current not in seen:
        seen.add(current)
        chain.append(current)
        base = by_name[current].get("base_class")
        if not base:
            return chain, True                       # a real root: closed
        if base in seen:
            return chain, False                      # cyclic index: undecidable
        if base not in by_name:
            return chain, any(base.startswith(p) for p in base_library_prefixes)
        current = base
    return chain, False


def lookup_member(by_name: Dict[str, Dict[str, Any]], chain: Sequence[str],
                  member: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """`(declaring class, method entry)` for `member` anywhere in `chain`, or
    None. Methods only -- see the module docstring on why properties are not
    decided here."""
    for cls_name in chain:
        for method in by_name[cls_name].get("methods", []) or []:
            if method.get("name") == member:
                return cls_name, method
    return None


# ---------------------------------------------------------------------------
# extraction: the VIP API citations a generated source actually makes
# ---------------------------------------------------------------------------

#: Type names that are never a class handle. Kept small and literal: anything
#: not listed here is simply looked up in the index, and an identifier the
#: index does not contain and the VIP scope does not cover is OUT_OF_SCOPE
#: anyway -- so this set is an optimisation and a noise filter, never a
#: correctness boundary.
_NON_CLASS_TYPES: frozenset = frozenset({
    "bit", "logic", "reg", "wire", "int", "integer", "byte", "shortint",
    "longint", "string", "real", "shortreal", "time", "realtime", "void",
    "chandle", "event", "genvar", "signed", "unsigned", "const", "static",
    "automatic", "typedef", "return", "class", "endclass", "function", "task",
    "endfunction", "endtask", "module", "endmodule", "package", "endpackage",
    "begin", "end", "if", "else", "for", "while", "repeat", "forever", "case",
    "endcase", "assign", "virtual", "extern", "local", "protected", "rand",
    "randc", "input", "output", "inout", "ref", "parameter", "localparam",
    "import", "export", "extends", "implements", "interface", "endinterface",
    "covergroup", "endgroup", "property", "sequence", "endsequence", "assert",
    "super", "this", "null", "new", "enum", "struct", "union", "with", "do",
})

_LINE_COMMENT_RE = re.compile(r"//.*$")
_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
_MACRO_RE = re.compile(r"^\s*`")
_DECL_RE = re.compile(
    r"^\s*(?:(?:automatic|static|const|rand|randc|local|protected|virtual)\s+)*"
    r"(?P<type>[A-Za-z_]\w*)"
    r"(?:\s*#\s*\([^)]*\))?"
    r"\s+(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])*\s*(?:=[^;]*)?;\s*$")
_CALL_RE = re.compile(
    r"(?P<recv>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*\.\s*(?P<member>[A-Za-z_]\w*)\s*\(")
_SCOPE_RE = re.compile(r"(?P<cls>[A-Za-z_]\w*)\s*::\s*(?P<member>[A-Za-z_]\w*)")


def _strip_noise(text: str) -> List[str]:
    """Line comments, block comments and string literals removed, line numbering
    preserved. A citation inside a comment is not a citation -- the generated
    environments in `examples/` carry `// evidence: ...(svt_configuration
    get_cfg;)` provenance comments that would otherwise be scanned as code."""
    out: List[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw
        if in_block:
            end = line.find("*/")
            if end < 0:
                out.append("")
                continue
            line = line[end + 2:]
            in_block = False
        while True:
            start = line.find("/*")
            if start < 0:
                break
            end = line.find("*/", start + 2)
            if end < 0:
                line = line[:start]
                in_block = True
                break
            line = line[:start] + " " + line[end + 2:]
        line = _LINE_COMMENT_RE.sub("", line)
        line = _STRING_RE.sub('""', line)
        out.append(line)
    return out


@dataclass
class ApiCitation:
    kind: str                  # CLASS | METHOD | SCOPE_CLASS
    vip_class: str
    member: Optional[str]
    line: int
    text: str


def extract_api_citations(text: str) -> List[ApiCitation]:
    """Every VIP-API-shaped citation in one generated source file.

    Three kinds are extracted, because those are the three the symbol index can
    actually decide:

      CLASS        a handle/variable DECLARATION whose type is a class name
                   (`svt_usb_transfer xfer;`)
      METHOD       a call on a handle whose declared type this scan resolved
                   (`l_agent.reconfigure(cfg);` where `l_agent` was declared
                   `svt_usb_agent`)
      SCOPE_CLASS  the class half of a scope resolution
                   (`svt_usb_types::GET_DESCRIPTOR`)

    Property access is deliberately not extracted (module docstring). A call on
    a receiver whose type this scan could not resolve is deliberately not
    extracted either: unresolved is our ignorance, and inventing a finding out
    of it is exactly the fabrication this module exists to prevent.

    This is a declaration-level line scan, the same technique -- and for the
    same graceful-degradation reason -- `vip_symbol_index.index_source_text()`
    uses: a construct it cannot understand contributes no citation, never an
    exception and never a guess."""
    handles: Dict[str, str] = {}
    citations: List[ApiCitation] = []
    for lineno, line in enumerate(_strip_noise(text), start=1):
        if not line.strip():
            continue
        stripped = line.strip()

        # A backtick macro line is never scanned for DECLARATIONS (a macro
        # expansion's shape is unknown to this scan, and mis-reading one as a
        # declaration would bind a handle to a type it does not have), but IS
        # still scanned for calls and scope citations below -- a real VIP call
        # inside `uvm_info(..., xfer.get_status(), ...) is a real citation.
        m = None if _MACRO_RE.match(line) else _DECL_RE.match(line)
        if m:
            type_name, handle = m.group("type"), m.group("name")
            if type_name not in _NON_CLASS_TYPES and handle not in _NON_CLASS_TYPES:
                handles[handle] = type_name
                citations.append(ApiCitation("CLASS", type_name, None, lineno, stripped))
                continue

        for cm in _SCOPE_RE.finditer(line):
            cls = cm.group("cls")
            if cls in _NON_CLASS_TYPES:
                continue
            citations.append(ApiCitation("SCOPE_CLASS", cls, cm.group("member"),
                                         lineno, stripped))

        for cm in _CALL_RE.finditer(line):
            recv, member = cm.group("recv"), cm.group("member")
            # `Class::static_call(...)` is handled by _SCOPE_RE above; a
            # preceding '.' means this is a chained hop whose receiver type is
            # not resolvable from a declaration.
            if cm.start() > 0 and line[cm.start() - 1] in ".:":
                continue
            declared = handles.get(recv)
            if declared is None or declared in _NON_CLASS_TYPES:
                continue
            citations.append(ApiCitation("METHOD", declared, member, lineno, stripped))
    return citations


# ---------------------------------------------------------------------------
# the check
# ---------------------------------------------------------------------------

def _card_for(cit: ApiCitation, usage_file: str, *, by_name, scope_prefixes,
              local_classes: Set[str], base_library_prefixes,
              known_base_methods: frozenset) -> VipApiCard:
    citation = f"{cit.vip_class}.{cit.member}" if cit.member and cit.kind == "METHOD" else (
        f"{cit.vip_class}::{cit.member}" if cit.member else cit.vip_class)
    card = VipApiCard(
        citation=citation, kind=cit.kind, vip_class=cit.vip_class, member=cit.member,
        status=OUT_OF_SCOPE, usage_file=usage_file, usage_line=cit.line,
        usage_text=cit.text)

    # A class the validated sources declare THEMSELVES is not a VIP citation,
    # whatever its name looks like. Generated environments legitimately name
    # their own classes with the protocol token the VIP scope is derived from
    # (`usb_base_vseq` under a `usb_`-prefixed VIP index), and blocking those
    # would be a pure false positive.
    if cit.vip_class in local_classes:
        card.reason = R_LOCAL_CLASS
        return card

    entry = by_name.get(cit.vip_class)
    if entry is None:
        if not _in_vip_scope(cit.vip_class, scope_prefixes):
            card.reason = R_NOT_VIP_SCOPE
            return card
        # In the VIP naming scope, absent from the real index, not declared
        # locally: a VIP class name nothing can prove exists.
        card.status = BLOCKED
        card.reason = R_CLASS_NOT_INDEXED
        return card

    chain, closed = inheritance_chain(by_name, cit.vip_class,
                                      base_library_prefixes=base_library_prefixes)
    card.inheritance_chain = list(chain)
    card.chain_closed = closed

    if cit.kind in ("CLASS", "SCOPE_CLASS"):
        # The class itself is proven at its real declaration site. For a scope
        # citation the MEMBER half stays undecided on purpose: this index
        # models no enum constants, parameters or typedefs.
        card.status = PROVEN
        card.resolved_file = entry.get("file")
        card.resolved_line = entry.get("line")
        card.resolved_kind = "class"
        card.declared_by = cit.vip_class
        return card

    # The real index is consulted FIRST, before the base-library allowlist: a
    # VIP class that really does declare its own `build_phase` deserves the
    # PROVEN card with its real file:line, not an OUT_OF_SCOPE shrug because
    # the name happens to also exist in the UVM base library.
    hit = lookup_member(by_name, chain, cit.member or "")
    if hit is not None:
        declaring, method = hit
        card.status = PROVEN
        card.resolved_file = method.get("file")
        card.resolved_line = method.get("line")
        card.resolved_signature = method.get("arguments")
        card.resolved_kind = method.get("kind")
        card.declared_by = declaring
        return card

    if cit.member in known_base_methods:
        card.reason = R_BASE_LIBRARY
        return card

    if not closed:
        card.status = UNPROVABLE
        card.reason = R_CHAIN_OPEN
        return card

    card.status = BLOCKED
    card.reason = R_METHOD_NOT_INDEXED
    return card


def validate_vip_api_usage(sources: Iterable, index: Dict[str, Any], *,
                           relative_to=None,
                           vip_class_prefixes: Optional[Sequence[str]] = None,
                           base_library_prefixes: Sequence[str] = DEFAULT_BASE_LIBRARY_PREFIXES,
                           extra_known_base_methods: Sequence[str] = (),
                           ) -> VipApiValidationReport:
    """Section 187's `Validate Signature -> VIPApiCard` step, over real sources
    and the REAL `vip_symbol_index` document.

    Args:
      sources: files and/or directories of generated SystemVerilog to validate.
      index: a `vip_symbol_index.build_symbol_index()` document (or one loaded
        by `load_symbol_index()`); it is schema-validated here, so a hand-made
        dict cannot slip past as an index.
      relative_to: make `usage_file` paths relative to this root, for the same
        diffability reason `vip_symbol_index` relativizes its own file labels.
      vip_class_prefixes: override the naming scope instead of deriving it from
        the index (`derive_vip_scope_prefixes()`).
      base_library_prefixes: which non-indexed bases CLOSE an inheritance chain.
      extra_known_base_methods: project-specific base-library methods to treat
        as out of scope. Can only downgrade a finding, never create one.

    Returns a report whose `status` is BLOCKED if any card is BLOCKED,
    UNPROVABLE if any is UNPROVABLE, PROVEN if there is at least one decided
    citation and none of those, and NOT_AVAILABLE (with a reason) when there
    was nothing real to check. NOT_AVAILABLE is never PROVEN."""
    vip_symbol_index.validate_symbol_index(index)
    by_name = index_classes_by_name(index)
    scope = list(vip_class_prefixes) if vip_class_prefixes is not None else \
        derive_vip_scope_prefixes(index)
    known = BASE_LIBRARY_METHODS | frozenset(extra_known_base_methods)

    try:
        files = vip_symbol_index.iter_source_files(list(sources))
    except vip_symbol_index.VipSymbolIndexError as exc:
        raise VipApiValidationError(str(exc)) from exc

    base = Path(relative_to) if relative_to else None
    texts: List[Tuple[str, str]] = []
    local_classes: Set[str] = set()
    for path in files:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        label = vip_symbol_index._relativize(path, base)
        texts.append((label, text))
        # Reuse of the real indexer, not a second one: the classes the
        # validated sources declare themselves come from the SAME declaration
        # scanner that produced the VIP index being validated against.
        for cls in vip_symbol_index.index_source_text(text, label):
            local_classes.add(cls["name"])

    report = VipApiValidationReport(
        status=NOT_AVAILABLE,
        protocol=index.get("protocol"),
        index_roots=list(index.get("roots", [])),
        vip_scope_prefixes=scope,
        local_classes=sorted(local_classes),
        files_scanned=len(files),
    )

    if not files:
        report.reason = "NO_SOURCE_FILES_TO_VALIDATE"
        return report
    if not by_name:
        report.reason = "VIP_SYMBOL_INDEX_CONTAINS_NO_CLASSES"
        return report
    if not scope:
        # Without a naming scope, a fabricated VIP class cannot be told apart
        # from a project class -- an honest NOT_AVAILABLE, never a PROVEN.
        report.reason = "NO_VIP_NAMING_SCOPE_DERIVABLE_FROM_INDEX"
        return report

    seen: Set[Tuple[str, str, int]] = set()
    for label, text in texts:
        for cit in extract_api_citations(text):
            card = _card_for(cit, label, by_name=by_name, scope_prefixes=scope,
                             local_classes=local_classes,
                             base_library_prefixes=base_library_prefixes,
                             known_base_methods=known)
            key = (label, card.citation, card.usage_line)
            if key in seen:
                continue
            seen.add(key)
            report.cards.append(card)

    counts: Dict[str, int] = {PROVEN: 0, BLOCKED: 0, UNPROVABLE: 0, OUT_OF_SCOPE: 0}
    for c in report.cards:
        counts[c.status] = counts.get(c.status, 0) + 1
    report.counts = counts

    if counts[BLOCKED]:
        report.status = BLOCKED
    elif counts[UNPROVABLE]:
        report.status = UNPROVABLE
    elif counts[PROVEN]:
        report.status = PROVEN
    else:
        report.status = NOT_AVAILABLE
        report.reason = "NO_VIP_API_CITATIONS_FOUND"
    return report


def format_report(report: VipApiValidationReport) -> str:
    """Human-readable rendering. Every non-PROVEN card names its own reason and
    its own generated-source location, so the finding is actionable without
    opening the JSON."""
    lines = [f"VIP API validation: {report.status}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    if report.protocol:
        lines.append(f"  protocol: {report.protocol}")
    lines.append(f"  files scanned: {report.files_scanned}")
    if report.vip_scope_prefixes:
        lines.append(f"  VIP naming scope: {', '.join(report.vip_scope_prefixes)}")
    if report.counts:
        lines.append("  cards: " + ", ".join(
            f"{k}={report.counts.get(k, 0)}"
            for k in (PROVEN, BLOCKED, UNPROVABLE, OUT_OF_SCOPE)))
    for status, header in ((BLOCKED, "BLOCKED -- cannot be proven, must not be generated"),
                           (UNPROVABLE, "UNPROVABLE -- UNKNOWN per spec 187")):
        rows = [c for c in report.cards if c.status == status]
        if not rows:
            continue
        lines += ["", f"  {header}:"]
        for c in rows:
            lines.append(f"    {c.citation}  [{c.reason}]")
            lines.append(f"      cited at {c.usage_file}:{c.usage_line}: {c.usage_text}")
    proven = [c for c in report.cards if c.status == PROVEN]
    if proven:
        lines += ["", "  PROVEN (VIPApiCard -> real VIP source location):"]
        for c in proven:
            loc = c.location or "(no location)"
            via = f" via {c.declared_by}" if c.declared_by and c.declared_by != c.vip_class else ""
            lines.append(f"    {c.citation} -> {loc}{via}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# artifact I/O and CLI
# ---------------------------------------------------------------------------

VIP_API_CARDS_REPORT_NAME = "vip_api_cards.json"


def write_vip_api_cards(report: VipApiValidationReport, out_dir) -> Path:
    """Write the VIPApiCard artifact next to the generated environment. No
    timestamp anywhere, so an unchanged environment + unchanged index
    regenerates byte-identically (env_manifest.py's Diffability contract)."""
    path = Path(out_dir) / VIP_API_CARDS_REPORT_NAME
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_index(index_path) -> Dict[str, Any]:
    p = Path(index_path)
    if not p.exists():
        raise VipApiValidationError(
            f"VIP symbol index does not exist: {index_path} -- build one with "
            "dv_harness.vip_symbol_index.build_symbol_index() first; this check "
            "must never run against an index that is not there")
    try:
        return vip_symbol_index.load_symbol_index(p)
    except vip_symbol_index.VipSymbolIndexError as exc:
        raise VipApiValidationError(str(exc)) from exc


def execute_verb(sources: Sequence, index_path, *, relative_to=None,
                 as_json: bool = False, out_dir=None) -> Tuple[str, int]:
    """Shared implementation for `dv-harness vip-api-check` and
    `python -m dv_harness.vip_api_card`. Returns (text, exit_code):
    0 PROVEN, 1 BLOCKED, 2 NOT_AVAILABLE, 3 UNPROVABLE."""
    index = load_index(index_path)
    report = validate_vip_api_usage(sources, index, relative_to=relative_to)
    if out_dir:
        write_vip_api_cards(report, out_dir)
    text = json.dumps(report.to_dict(), indent=2) if as_json else format_report(report)
    return text, {PROVEN: 0, BLOCKED: 1, NOT_AVAILABLE: 2, UNPROVABLE: 3}[report.status]


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.vip_api_card",
        description="Spec section 187: validate the VIP API calls a generated sequence makes "
                    "against a REAL vip_symbol_index, and emit VIPApiCards. A call to a VIP "
                    "class/method the index cannot prove exists is BLOCKED, never silently "
                    "generated.")
    ap.add_argument("--source", action="append", required=True, dest="sources",
                    help="Generated .sv/.svh file or directory to validate (repeatable).")
    ap.add_argument("--index", required=True, help="vip_symbol_index JSON document.")
    ap.add_argument("--relative-to", default=None, help="Root for reported usage paths.")
    ap.add_argument("--out-dir", default=None,
                    help="Also write the VIPApiCard artifact (vip_api_cards.json) here.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    ap.add_argument("--strict-unprovable", action="store_true",
                    help="Exit non-zero on UNPROVABLE citations too, not just BLOCKED ones.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(a.sources, a.index, relative_to=a.relative_to,
                                  as_json=a.json, out_dir=a.out_dir)
    except VipApiValidationError as exc:
        print(f"VipApiValidationError: {exc}")
        return 2
    print(text)
    if code == 3 and not a.strict_unprovable:
        return 0
    return code


if __name__ == "__main__":
    raise SystemExit(main())
