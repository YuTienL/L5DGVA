"""dv_harness/amba_command_txt_extension.py -- AMBA-specific semantic
compilation of a DE command.txt command (2026-09-06).

WHAT THIS CLOSES. This session's `de_command_style_learning.py` already
answers the GENERIC question "what DE command is this line, and who
(GLOBAL/DUT/FW/VIP) probably owns it" from a real command.txt-style file's
own formatting. `pattern_ir_assembly.py` (another concurrent module in this
same batch) assembles generic pattern fragments from a command registry.
Neither one knows, or is meant to know, anything about AMBA fabric
semantics specifically: which AMBA MASTER issued a given transaction, which
ADDRESS REGION the transaction's address falls in, whether the statement is
a WRITE, a READ, or neither, and whether the statement executes inside a
`fork`/`join` PARALLEL GROUP alongside other masters' traffic. A full-repo
grep for `amba_command_txt_extension`/`AmbaCommandTxtEntry`/a per-command
master+region+parallel-group compilation matched nothing before this file --
that four-facet AMBA reading of a command.txt entry is the gap this module
closes.

WHY THE INPUT IS DUCK-TYPED, NOT IMPORTED. Per this batch's own file-safety
scope, `de_command_style_learning.py` and `pattern_ir_assembly.py` are
neither imported nor touched here. Every "command record" this module reads
is therefore accepted as a plain dict (or any object `getattr` can read
attributes off), resolved through small alias tables rather than one fixed
key name, exactly as `command_txt_change_impact.py` (a sibling module in
this same batch, scoped the same way against `de_command_style_learning.py`)
already does. A record can supply an explicit `master`/`operation`/
`command_name` field, or nothing but a raw source line -- this module
extracts what it can from whichever fields are actually present and never
assumes a producer's schema has stabilized.

REUSE OVER REINVENT. Address-region and master lookups are always resolved
against a `region_map`/`master_registry` the CALLER supplies (real facts
from wherever the caller's own project keeps them -- e.g. a fabric
discovery/port-registry artifact reduced to plain dicts before being passed
in here); this module is never the source of what masters or regions exist,
only the compiler that reads a command against that data. Markdown rendering
reuses `connectivity.render_markdown_table`, the repo's one parameterized
table renderer, rather than a fifth hand-rolled `"| " + " | ".join(...)`
loop. `assert_no_verification_verdict_vocabulary()` below checks this
module's own status vocabulary shares no token with `dv_harness.models
.Status`, the harness's stage-gate verdict vocabulary, the same discipline
several sibling modules in this batch already apply to their own
classification vocabularies.

EVIDENCE TRUTH RULE, applied to each of the four facets independently:

* **operation** -- WRITE/READ are reported only when a real macro-shaped
  token in the record's own text (or an explicit `operation` field) names
  one; a recognized-but-neither macro is OTHER_RECOGNIZED_MACRO; a
  structural, non-transaction line (a delay, a `$display`, a bare `force`,
  a comment, a `fork`/`join` keyword) is NOT_APPLICABLE; anything this
  module cannot classify at all is OPERATION_UNKNOWN. Never defaulted to
  WRITE or READ on a guess.
* **master** -- a candidate token is split off the macro name by its own
  textual WRITE/READ suffix (`CPUWRITE4B` -> candidate `CPU`); it is only
  ever reported RESOLVED when that candidate matches an entry the caller's
  own `master_registry` names. No registry supplied, a candidate not in the
  registry, and no candidate token found at all are three DIFFERENT honest
  UNKNOWN reasons -- never collapsed into one another and never defaulted
  to a guessed master name.
* **region** -- an address is parsed only from a real Verilog-style sized
  literal (`32'h0002_0100`) or explicit `address` field; matched only
  against the caller's own `region_map`. No map, no parseable address, no
  matching entry, and an address the map itself leaves ambiguous (more than
  one configured region claims it) are four different honest outcomes.
* **parallel-group** -- membership is derived only from literal `fork`/
  `join`/`join_any`/`join_none` keyword text found in the records' own
  raw source, tracked as a real nesting stack across the record sequence,
  never inferred from naming convention or guessed from record order alone.

WHAT THIS MODULE DOES NOT DO. It does not discover a project's masters,
slaves or address map itself -- see `amba_fabric_discovery.py`/
`amba_port_registry.py` for that real, pre-existing machinery, which this
module never imports and never re-derives. It decides no VIP API, no RTL
content and no arbitration/security/QoS policy, and it fabricates no
address-map entry or master name to fill an unresolved slot. It performs no
performance/timing analysis of any kind (explicitly out of scope for this
whole batch)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# -- operation vocabulary ----------------------------------------------------

OP_WRITE = "WRITE"
OP_READ = "READ"
OP_OTHER = "OTHER_RECOGNIZED_MACRO"
OP_NOT_APPLICABLE = "NOT_APPLICABLE"
OP_UNKNOWN = "OPERATION_UNKNOWN"

OPERATION_STATUSES = frozenset({OP_WRITE, OP_READ, OP_OTHER, OP_NOT_APPLICABLE, OP_UNKNOWN})

# -- master-resolution status vocabulary -------------------------------------

MASTER_RESOLVED = "MASTER_RESOLVED"
MASTER_UNKNOWN_NO_TOKEN = "MASTER_UNKNOWN_NO_TOKEN"
MASTER_UNKNOWN_NO_REGISTRY_SUPPLIED = "MASTER_UNKNOWN_NO_REGISTRY_SUPPLIED"
MASTER_UNKNOWN_NOT_IN_REGISTRY = "MASTER_UNKNOWN_NOT_IN_REGISTRY"

MASTER_STATUSES = frozenset({
    MASTER_RESOLVED, MASTER_UNKNOWN_NO_TOKEN,
    MASTER_UNKNOWN_NO_REGISTRY_SUPPLIED, MASTER_UNKNOWN_NOT_IN_REGISTRY,
})

# -- region-resolution status vocabulary --------------------------------------

REGION_RESOLVED = "REGION_RESOLVED"
REGION_UNKNOWN_NO_ADDRESS = "REGION_UNKNOWN_NO_ADDRESS"
REGION_UNKNOWN_NO_MAP_SUPPLIED = "REGION_UNKNOWN_NO_MAP_SUPPLIED"
REGION_UNKNOWN_NOT_IN_MAP = "REGION_UNKNOWN_NOT_IN_MAP"
REGION_AMBIGUOUS_MULTIPLE_MATCH = "REGION_AMBIGUOUS_MULTIPLE_MATCH"

REGION_STATUSES = frozenset({
    REGION_RESOLVED, REGION_UNKNOWN_NO_ADDRESS, REGION_UNKNOWN_NO_MAP_SUPPLIED,
    REGION_UNKNOWN_NOT_IN_MAP, REGION_AMBIGUOUS_MULTIPLE_MATCH,
})

# -- parallel-group status vocabulary -----------------------------------------

PARALLEL_GROUP_MEMBER = "PARALLEL_GROUP_MEMBER"
PARALLEL_GROUP_NONE = "PARALLEL_GROUP_NONE"

PARALLEL_GROUP_STATUSES = frozenset({PARALLEL_GROUP_MEMBER, PARALLEL_GROUP_NONE})


class AmbaCommandTxtExtensionError(Exception):
    """Raised only for an input this module cannot honestly interpret at
    all (e.g. `records` is not a sequence) -- never raised merely because a
    record's AMBA facets are legitimately unresolvable; those report an
    UNKNOWN-family status instead."""


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's four status vocabularies must share no token with
    `dv_harness.models.Status`, the harness's stage-gate verification
    verdict vocabulary -- the same check-not-just-claim discipline several
    sibling modules in this batch already apply to their own
    classification vocabularies."""
    from . import models
    verdict_tokens = {s.value for s in models.Status}
    all_tokens = (OPERATION_STATUSES | MASTER_STATUSES | REGION_STATUSES
                  | PARALLEL_GROUP_STATUSES)
    overlap = all_tokens & verdict_tokens
    if overlap:
        raise AmbaCommandTxtExtensionError(
            "AMBA_COMMAND_TXT_STATUS_COLLIDES_WITH_VERDICT_VOCABULARY: "
            f"{sorted(overlap)}")


# -- duck-typed field aliasing ------------------------------------------------

_TEXT_FIELDS = ("raw_text", "text", "source_text", "line", "statement", "raw")
_MACRO_FIELDS = ("command_name", "macro", "name", "command", "statement_name")
_OPERATION_FIELDS = ("operation", "semantic_operation", "op")
_MASTER_FIELDS = ("master", "master_name")
_ADDRESS_FIELDS = ("address", "addr", "base_address")
_ARGUMENT_FIELDS = ("arguments", "args")
_ORDER_FIELDS = ("line_no", "line_number", "order", "index")


def _get(record: Any, keys: Sequence[str]) -> Optional[Any]:
    """First non-None value for `keys`, read off a dict via `.get` or off
    any other object via `getattr` -- the record shape is never assumed."""
    for key in keys:
        if isinstance(record, Mapping):
            value = record.get(key)
        else:
            value = getattr(record, key, None)
        if value is not None:
            return value
    return None


# -- literal / macro parsing ---------------------------------------------------

#: A Verilog-style sized literal: `32'h0002_0100`, `8'b0000_0001`, `16'd42`.
_SIZED_LITERAL_RE = re.compile(
    r"(\d+)\s*'\s*[sS]?([hHdDbBoO])\s*([0-9a-fA-F_xXzZ]+)")

_BASE_RADIX = {"h": 16, "d": 10, "b": 2, "o": 8}

#: The first `` `NAME(`` or `NAME(` call-shaped token in a raw source line.
_MACRO_CALL_RE = re.compile(r"`?([A-Za-z_][A-Za-z0-9_]*)\s*\(")

#: Splits a macro name into a leading MASTER token and its WRITE/READ suffix,
#: e.g. `CPUWRITE4B` -> master `CPU`, op `WRITE`, width `4B`.
_MASTER_OP_RE = re.compile(
    r"^(?P<master>[A-Za-z][A-Za-z0-9]*?)(?P<op>WRITE|READ)(?P<width>[0-9]*B)?$",
    re.IGNORECASE)

#: Literal keywords that make a line structural rather than a transaction --
#: matched as whole words so a variable named e.g. `forklift` never matches.
_STRUCTURAL_RE = re.compile(
    r"^\s*(//|#\d|\$display|\$write|force\b|release\b|fork\b|join\b|"
    r"join_any\b|join_none\b|`ifdef|`else|`endif|`include|`define)")

#: Fork/join keywords tracked, in textual order, to build the parallel-group
#: nesting stack. `join`/`join_any`/`join_none` are treated identically here
#: (all three close the innermost open `fork` in real Verilog).
_FORK_JOIN_RE = re.compile(r"\b(fork|join_any|join_none|join)\b")


def _parse_int_literal(value: Any) -> Tuple[Optional[int], str]:
    """Parses a real address value: an int as-is, a Verilog sized literal,
    or a plain `0x...`/decimal string. Returns `(None, reason)` rather than
    guessing when the value contains don't-care (`x`/`z`) bits or matches
    nothing this module recognizes -- never silently truncated or zeroed."""
    if value is None:
        return None, "no address value present"
    if isinstance(value, bool):
        return None, f"address value {value!r} is a bool, not an address"
    if isinstance(value, int):
        return value, "given as a literal int"
    text = str(value).strip()
    m = _SIZED_LITERAL_RE.search(text)
    if m:
        radix_char = m.group(2).lower()
        digits = m.group(3).replace("_", "")
        if re.search(r"[xXzZ]", digits):
            return None, (
                f"literal {text!r} contains X/Z don't-care bits; cannot "
                "resolve to a concrete address")
        try:
            return int(digits, _BASE_RADIX[radix_char]), f"parsed sized literal {text!r}"
        except ValueError:
            return None, f"literal {text!r} could not be parsed as base-{_BASE_RADIX[radix_char]}"
    try:
        return int(text, 0), f"parsed plain integer literal {text!r}"
    except ValueError:
        return None, f"no recognizable address literal in {text!r}"


def _extract_macro_and_args(raw_text: str) -> Tuple[Optional[str], Optional[str]]:
    """The first call-shaped macro token in `raw_text`, plus the raw text
    inside its parentheses (used as a fallback address source when a record
    carries no explicit `arguments`)."""
    if not raw_text:
        return None, None
    m = _MACRO_CALL_RE.search(raw_text)
    if not m:
        return None, None
    name = m.group(1)
    start = m.end()
    depth = 1
    i = start
    while i < len(raw_text) and depth > 0:
        if raw_text[i] == "(":
            depth += 1
        elif raw_text[i] == ")":
            depth -= 1
        i += 1
    inner = raw_text[start:i - 1] if depth == 0 else raw_text[start:]
    return name, inner


def _first_argument(args_field: Any, inner_text: Optional[str]) -> Optional[str]:
    if isinstance(args_field, (list, tuple)) and args_field:
        return str(args_field[0])
    if isinstance(args_field, str) and args_field.strip():
        return args_field.split(",")[0]
    if inner_text is not None:
        first = inner_text.split(",")[0]
        return first if first.strip() else None
    return None


# -- master registry normalization ---------------------------------------------

def _normalize_master_registry(master_registry: Any) -> Dict[str, str]:
    """Builds an `{ALIAS_UPPER: canonical_name}` map from whatever shape the
    caller supplied: `None`, a `{alias: canonical}` dict, a flat iterable of
    canonical names, or an iterable of `{"name": ..., "aliases": [...]}`
    dicts. An unrecognized shape yields an empty map (honest "no usable
    registry"), never a guessed entry."""
    out: Dict[str, str] = {}
    if not master_registry:
        return out
    if isinstance(master_registry, Mapping):
        for alias, canonical in master_registry.items():
            out[str(alias).upper()] = str(canonical)
        return out
    if isinstance(master_registry, Iterable):
        for item in master_registry:
            if isinstance(item, str):
                out[item.upper()] = item
            elif isinstance(item, Mapping):
                name = _get(item, ("name", "master", "canonical"))
                if name is None:
                    continue
                out[str(name).upper()] = str(name)
                for alias in item.get("aliases", []) or []:
                    out[str(alias).upper()] = str(name)
    return out


def _resolve_master(master_token: Optional[str],
                     registry: Dict[str, str]) -> Tuple[Optional[str], str, str]:
    if not master_token:
        return None, MASTER_UNKNOWN_NO_TOKEN, (
            "no master-identifying token could be extracted from this "
            "record's macro name / raw text")
    if not registry:
        return None, MASTER_UNKNOWN_NO_REGISTRY_SUPPLIED, (
            f"candidate master token {master_token!r} found, but no "
            "master_registry was supplied to confirm it against")
    canonical = registry.get(master_token.upper())
    if canonical is None:
        return None, MASTER_UNKNOWN_NOT_IN_REGISTRY, (
            f"candidate master token {master_token!r} does not match any "
            "name in the supplied master_registry")
    return canonical, MASTER_RESOLVED, f"token {master_token!r} matched registry entry {canonical!r}"


# -- region map normalization ---------------------------------------------------

@dataclass
class _Region:
    name: str
    start: int
    end: int


def _normalize_region_map(region_map: Any, warnings: List[str]) -> List[_Region]:
    """Builds a list of `(name, start, end)` regions from whatever shape the
    caller supplied. A malformed entry (no resolvable name, or no
    resolvable start/end-or-size) is skipped and recorded in `warnings`
    rather than silently dropped or guessed at."""
    out: List[_Region] = []
    if not region_map:
        return out
    for item in region_map:
        if not isinstance(item, Mapping):
            warnings.append(f"region_map entry {item!r} is not a mapping; skipped")
            continue
        name = _get(item, ("name", "region", "label"))
        start_raw = _get(item, ("start", "base", "base_address", "addr_start"))
        end_raw = _get(item, ("end", "limit", "addr_end"))
        size_raw = _get(item, ("size", "length"))
        if name is None:
            warnings.append(f"region_map entry {item!r} has no resolvable name; skipped")
            continue
        start, start_reason = _parse_int_literal(start_raw)
        if start is None:
            warnings.append(
                f"region_map entry {name!r} has no resolvable start address "
                f"({start_reason}); skipped")
            continue
        if end_raw is not None:
            end, end_reason = _parse_int_literal(end_raw)
            if end is None:
                warnings.append(
                    f"region_map entry {name!r} has an unresolvable end "
                    f"address ({end_reason}); skipped")
                continue
        elif size_raw is not None:
            size, size_reason = _parse_int_literal(size_raw)
            if size is None or size <= 0:
                warnings.append(
                    f"region_map entry {name!r} has an unresolvable/non-positive "
                    f"size ({size_reason}); skipped")
                continue
            end = start + size - 1
        else:
            warnings.append(
                f"region_map entry {name!r} has neither an end nor a size; skipped")
            continue
        out.append(_Region(name=str(name), start=start, end=end))
    return out


def _resolve_region(address: Optional[int], address_reason: str,
                     regions: List[_Region],
                     region_map_supplied: bool) -> Tuple[Optional[str], str, str]:
    if address is None:
        return None, REGION_UNKNOWN_NO_ADDRESS, (
            f"no address could be resolved for this record ({address_reason})")
    if not region_map_supplied or not regions:
        return None, REGION_UNKNOWN_NO_MAP_SUPPLIED, (
            f"address 0x{address:X} resolved, but no usable region_map was supplied")
    matches = [r for r in regions if r.start <= address <= r.end]
    if not matches:
        return None, REGION_UNKNOWN_NOT_IN_MAP, (
            f"address 0x{address:X} matched no configured region_map entry")
    if len(matches) > 1:
        names = ", ".join(sorted(m.name for m in matches))
        return None, REGION_AMBIGUOUS_MULTIPLE_MATCH, (
            f"address 0x{address:X} is claimed by more than one region_map "
            f"entry ({names}); cannot resolve without guessing")
    only = matches[0]
    return only.name, REGION_RESOLVED, (
        f"address 0x{address:X} falls within {only.name!r} "
        f"[0x{only.start:X}, 0x{only.end:X}]")


# -- operation classification ---------------------------------------------------

def _classify_operation(raw_text: Optional[str], macro_name: Optional[str],
                         explicit_operation: Optional[str]) -> Tuple[Optional[str], str]:
    if explicit_operation:
        text = str(explicit_operation).upper()
        if "WRITE" in text:
            return None, OP_WRITE
        if "READ" in text:
            return None, OP_READ
        return None, OP_OTHER
    if macro_name:
        m = _MASTER_OP_RE.match(macro_name)
        if m:
            return m.group("master"), (OP_WRITE if m.group("op").upper() == "WRITE" else OP_READ)
        return None, OP_OTHER
    if raw_text and _STRUCTURAL_RE.match(raw_text.strip()):
        return None, OP_NOT_APPLICABLE
    return None, OP_UNKNOWN


# -- the compiled entry / report -------------------------------------------------

@dataclass
class AmbaCommandTxtEntry:
    order: int
    raw_text: str
    resolved_macro: Optional[str] = None
    operation: str = OP_UNKNOWN
    operation_evidence: str = ""
    master: Optional[str] = None
    master_status: str = MASTER_UNKNOWN_NO_TOKEN
    master_evidence: str = ""
    address: Optional[int] = None
    region: Optional[str] = None
    region_status: str = REGION_UNKNOWN_NO_ADDRESS
    region_evidence: str = ""
    parallel_group: Optional[str] = None
    parallel_group_status: str = PARALLEL_GROUP_NONE

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AmbaCommandTxtExtensionReport:
    entries: List[AmbaCommandTxtEntry] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def summary(self) -> Dict[str, Dict[str, int]]:
        def _count(getter):
            out: Dict[str, int] = {}
            for e in self.entries:
                key = getter(e)
                out[key] = out.get(key, 0) + 1
            return out
        return {
            "operation": _count(lambda e: e.operation),
            "master_status": _count(lambda e: e.master_status),
            "region_status": _count(lambda e: e.region_status),
            "parallel_group_status": _count(lambda e: e.parallel_group_status),
        }

    def to_dict(self) -> dict:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "warnings": list(self.warnings),
            "summary": self.summary,
        }

    def render_markdown(self) -> str:
        from dv_harness.connectivity import render_markdown_table
        columns = [
            ("order", "#"), ("operation", "operation"), ("master", "master"),
            ("master_status", "master_status"), ("region", "region"),
            ("region_status", "region_status"),
            ("parallel_group", "parallel_group"),
            ("parallel_group_status", "parallel_group_status"),
        ]
        rows = [asdict(e) for e in self.entries]
        return render_markdown_table(columns, rows, empty_note="(no commands compiled)")


def compile_command_txt_extension(
    records: Sequence[Any],
    *,
    master_registry: Any = None,
    region_map: Any = None,
) -> AmbaCommandTxtExtensionReport:
    """Compiles the AMBA-specific master/region/operation/parallel-group
    facets of each duck-typed command record in `records`, IN THE ORDER
    GIVEN (re-sorted only when every record carries a resolvable
    `line_no`/`line_number`/`order`/`index` field, so a caller's own file
    order is never silently reshuffled by a guess). `master_registry` and
    `region_map` are the caller's own real facts (e.g. reduced from a
    fabric-discovery/port-registry artifact) -- this module never invents
    either."""
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise AmbaCommandTxtExtensionError(
            "AMBA_COMMAND_TXT_RECORDS_NOT_A_SEQUENCE: expected a list/tuple "
            f"of command records, got {type(records)!r}")

    warnings: List[str] = []
    registry = _normalize_master_registry(master_registry)
    regions = _normalize_region_map(region_map, warnings)
    region_map_supplied = bool(region_map)

    ordered = list(enumerate(records))
    if records and all(_get(r, _ORDER_FIELDS) is not None for r in records):
        ordered.sort(key=lambda pair: _get(pair[1], _ORDER_FIELDS))

    entries: List[AmbaCommandTxtEntry] = []
    fork_stack: List[str] = []
    group_counter = 0

    for position, record in ordered:
        raw_text = _get(record, _TEXT_FIELDS)
        raw_text = str(raw_text) if raw_text is not None else ""

        explicit_macro = _get(record, _MACRO_FIELDS)
        explicit_operation = _get(record, _OPERATION_FIELDS)
        explicit_master = _get(record, _MASTER_FIELDS)
        explicit_address = _get(record, _ADDRESS_FIELDS)
        args_field = _get(record, _ARGUMENT_FIELDS)

        parsed_macro, inner_args = _extract_macro_and_args(raw_text)
        macro_name = str(explicit_macro) if explicit_macro else parsed_macro

        derived_master, operation = _classify_operation(raw_text, macro_name, explicit_operation)
        operation_evidence = (
            f"explicit operation field {explicit_operation!r}" if explicit_operation
            else f"macro {macro_name!r} classified as {operation}" if macro_name
            else f"structural/non-transaction text matched" if operation == OP_NOT_APPLICABLE
            else "no macro-call token or structural keyword recognized in raw text")

        master_token = str(explicit_master) if explicit_master else derived_master
        master, master_status, master_evidence = _resolve_master(master_token, registry)

        address_source = explicit_address if explicit_address is not None else _first_argument(args_field, inner_args)
        address, address_reason = _parse_int_literal(address_source)
        region, region_status, region_evidence = _resolve_region(
            address, address_reason, regions, region_map_supplied)

        # parallel-group membership reflects state BEFORE this line's own
        # fork/join keywords are applied -- a `fork` line itself opens a
        # new group for the statements that follow it, it is not itself a
        # member of the group it opens.
        if fork_stack:
            parallel_group = fork_stack[-1]
            parallel_group_status = PARALLEL_GROUP_MEMBER
        else:
            parallel_group = None
            parallel_group_status = PARALLEL_GROUP_NONE

        for token in _FORK_JOIN_RE.finditer(raw_text):
            word = token.group(1)
            if word == "fork":
                group_counter += 1
                fork_stack.append(f"GROUP_{group_counter}")
            else:  # join / join_any / join_none
                if fork_stack:
                    fork_stack.pop()
                else:
                    warnings.append(
                        f"record #{position}: {word!r} encountered with no open "
                        "fork block; parallel-group nesting left unchanged")

        entries.append(AmbaCommandTxtEntry(
            order=position,
            raw_text=raw_text,
            resolved_macro=macro_name,
            operation=operation,
            operation_evidence=operation_evidence,
            master=master,
            master_status=master_status,
            master_evidence=master_evidence,
            address=address,
            region=region,
            region_status=region_status,
            region_evidence=region_evidence,
            parallel_group=parallel_group,
            parallel_group_status=parallel_group_status,
        ))

    if fork_stack:
        warnings.append(
            f"{len(fork_stack)} fork block(s) left unclosed at end of records: {fork_stack}")

    return AmbaCommandTxtExtensionReport(entries=entries, warnings=warnings)
