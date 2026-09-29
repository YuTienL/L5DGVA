"""dv_harness/register_reset_value_correlation.py -- cross-checks a
register's DOCUMENTED reset VALUE (register_excel_extract.py's transcribed
spreadsheet reset_value) against REAL RTL reset logic (a literal assignment
inside a real always/always_ff block's own reset-testing if-branch), reusing
register_rtl_trace.py to decide which real RTL site a register/field's name
resolves to. Reports MATCH / MISMATCH / UNKNOWN, honestly, per register (and
per field).

THE GAP THIS CLOSES
-------------------
register_excel_extract.py transcribes a spreadsheet's documented reset value
per register/field -- real cells, never invented. register_rtl_trace.py
proves a register field's NAME exists and is REFERENCED somewhere in the
parsed RTL (TRACE_CONFIRMED is that module's own explicit ceiling: existence
+ reference, never elaboration-time behavior -- it carries no notion of a
VALUE at all). A repo-wide grep for `register_reset_value_correlation` /
`RegisterResetCorrelation` / `reset_value_correlation` matched nothing
executable before this module: both modules exist, and nothing joins them on
this specific axis -- does the RTL's own reset-branch assignment to that same
signal carry the SAME literal value the spreadsheet documents.

REUSE OVER REINVENT
--------------------
- `register_rtl_trace.trace_register_field()` / `parse_rtl_sources()` /
  `collect_rtl_sites()` are called directly, unmodified, to decide whether a
  real, unambiguous RTL site exists for a register/field's name. This module
  never re-derives that existence/ambiguity decision and never runs its own
  "does this name exist" search -- only TRACE_CONFIRMED (one exact,
  referenced site) is ever handed to the reset-value scan below; a
  TRACE_PARTIAL/TRACE_NOT_FOUND/BLOCKED result is reported straight through
  as UNKNOWN, citing register_rtl_trace's own reason text.
- `verible_parser.run_export_json()` / `find_all_nonoverlapping()` /
  `node_span()` are the SAME real verible front end + module-span primitives
  `design_architecture_ir.py`'s own FSM literal scan already uses -- there is
  no second SystemVerilog parser in this package. This module needs the raw
  module TEXT to scan for a reset-branch assignment, which neither
  `register_rtl_trace.RtlSite` nor `verible_parser.ModuleInfo` ever carries
  (confirmed by reading both: no source line, no span, anywhere upstream --
  `dut_evidence_correlation.py`'s own docstring already states this same
  absence for register/field entries). So this module independently
  re-derives `design_architecture_ir.parse_rtl_file()`'s small "verible-
  parsed module -> its own source span -> module_text" primitive (the same
  "re-derive a small primitive rather than import a sibling module's private
  shape" discipline several modules in this repo already follow) rather than
  importing that module wholesale for an unrelated FSM-extraction feature.

THE PARSER-VS-ELABORATION BOUNDARY, restated here because it drives every
status this module can report, exactly as register_rtl_trace.py's own module
docstring already states it for its own ceiling: a literal reset-branch scan
can prove that SOURCE TEXT assigns a signal a specific literal value inside
what looks like a reset-testing `if`; it can never prove that assignment
actually executes as the design's real reset value (a `generate`/`` `ifdef ``
condition is never evaluated, a parameter reference is never resolved, and
no clock edge is ever simulated). MATCH/MISMATCH is this module's honest
reading of two DOCUMENTED/DECLARED facts against each other, never a claim
about verified silicon behavior.

FOUR INTERNAL FACTS, THREE REPORTED STATUSES.
  MATCH      the RTL trace is TRACE_CONFIRMED for exactly one site, this
             module's own reset-branch literal scan of that site's own
             module resolves to exactly one unambiguous literal value, the
             spreadsheet documents a reset value, and the two integers
             agree.
  MISMATCH   all of the above resolved, and the two integers DISAGREE. This
             module reports the disagreement; it never decides which side is
             right (Source Authority Order / Evidence Truth Rule -- the same
             ARBITRATION boundary `dut_evidence_correlation.py`'s own
             docstring keeps for an RTL_CONTRADICTS_SPEC finding).
  UNKNOWN    any one of the four real facts this comparison needs (a
             documented reset value, a TRACE_CONFIRMED RTL site, a real
             module source span for that site, an unambiguous literal
             reset-branch assignment inside it) is missing, ambiguous,
             unparseable, or could not be determined -- including the case
             where the RTL trace itself could not be ATTEMPTED at all
             (register_rtl_trace's own BLOCKED). Every UNKNOWN carries the
             real, specific reason (`reason`, plus the finer-grained
             `trace_status`/`rtl_finding` sub-fields) -- never a shared
             "unknown" a reader would have to guess the cause of.

WHAT IS DELIBERATELY NOT ATTEMPTED. This is a regex line-scan bounded to one
already-verified module's own source span, never a compiler: a
`generate`/`` `ifdef ``-guarded assignment is scanned exactly as written; an
X/Z/?-valued literal (`'bx`, `'hz`), a non-literal RHS (an expression, a
parameter reference, a macro), or a reset branch this scan cannot close (no
matching `begin`/`end` or terminating `;` before the module text runs out)
all report UNKNOWN rather than a guessed integer. A reset-branch assignment
appearing in MORE THAN ONE always block for the same target signal,
disagreeing on the literal value, is UNKNOWN naming the ambiguity -- never
resolved by picking the first one found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import register_excel_extract
from . import register_rtl_trace
from . import verible_parser

# --- status vocabulary -------------------------------------------------------

STATUS_MATCH = "MATCH"
STATUS_MISMATCH = "MISMATCH"
STATUS_UNKNOWN = "UNKNOWN"
CORRELATION_STATUSES: Tuple[str, ...] = (STATUS_MATCH, STATUS_MISMATCH, STATUS_UNKNOWN)


# ---------------------------------------------------------------------------
# Verilog literal parsing -- never a guess; an X/Z bit or an unrecognised
# shape is an honest parse failure, not a silently-assumed value.
# ---------------------------------------------------------------------------

_SIZED_LITERAL_RE = re.compile(
    r"^\s*(?:\d+\s*)?'(?P<signed>[sS])?(?P<base>[bBoOdDhH])(?P<digits>[0-9a-fA-Fxz_XZ?]+)\s*$"
)
_HEX_PREFIX_RE = re.compile(r"^\s*0[xX][0-9a-fA-F_]+\s*$")
_PLAIN_DECIMAL_RE = re.compile(r"^\s*\d+\s*$")
_BASE_RADIX = {"b": 2, "o": 8, "d": 10, "h": 16}


def parse_verilog_literal(text: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """Parses a Verilog RHS literal -- a sized literal (`8'h00`, `1'b0`,
    `32'd10`), a bare `0x`-prefixed hex string, or a plain decimal string --
    into (value, error). Returns (None, reason) for an X/Z/`?`-valued
    literal, a non-literal expression (a parameter reference, an operator, a
    macro), or any other shape this parser does not recognise -- never a
    guessed integer."""
    if text is None:
        return None, "no text supplied"
    stripped = text.strip()
    if not stripped:
        return None, "empty text"
    m = _SIZED_LITERAL_RE.match(stripped)
    if m:
        digits = m.group("digits")
        if re.search(r"[xXzZ?]", digits):
            return None, f"reset value {text!r} contains an X/Z/? bit -- not a determinate literal"
        base_char = m.group("base").lower()
        base = _BASE_RADIX[base_char]
        digits_clean = digits.replace("_", "")
        try:
            return int(digits_clean, base), None
        except ValueError:
            return None, f"could not parse {digits_clean!r} as base-{base} digits"
    if _HEX_PREFIX_RE.match(stripped):
        try:
            return int(stripped.replace("_", ""), 16), None
        except ValueError:
            return None, f"could not parse {text!r} as 0x-hex"
    if _PLAIN_DECIMAL_RE.match(stripped):
        return int(stripped), None
    return None, (
        f"unrecognized reset-value literal shape: {text!r} "
        f"(expected a sized Verilog literal, 0x-hex, or plain decimal)"
    )


# ---------------------------------------------------------------------------
# Lexical hygiene -- comments/strings blanked, offsets preserved, matching
# design_architecture_ir.py's own discipline (re-derived locally rather than
# imported, per this module's own REUSE-vs-coupling note above).
# ---------------------------------------------------------------------------

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LIT_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _blank_out(m: "re.Match") -> str:
    return "".join(ch if ch == "\n" else " " for ch in m.group(0))


def _strip_noise_preserve_offsets(text: str) -> str:
    text = _BLOCK_COMMENT_RE.sub(_blank_out, text)
    text = _LINE_COMMENT_RE.sub(_blank_out, text)
    text = _STRING_LIT_RE.sub(_blank_out, text)
    return text


# ---------------------------------------------------------------------------
# Reset-branch literal scan -- bounded to one sequential always block's own
# window, and to that block's own reset-testing first `if`'s THEN-branch.
# ---------------------------------------------------------------------------

_ALWAYS_SEQ_RE = re.compile(r"\balways(?:_ff)?\s*@\s*\(([^)]*)\)", re.IGNORECASE)
_RESET_NAME_RE = re.compile(r"(?:^|_)(rst|reset)(?:_|$)", re.IGNORECASE)
_IF_COND_RE = re.compile(
    r"\bif\s*\(\s*(?P<neg>!\s*)?(?P<name>[A-Za-z_]\w*)\s*(?:==\s*1'b[01]\s*)?\)"
)
_BEGIN_END_TOKEN_RE = re.compile(r"\bbegin\b|\bend\b")
_LEADING_WS_RE = re.compile(r"\s*")


@dataclass
class RtlResetAssignment:
    value: Optional[int]
    raw_text: str
    evidence: str
    parse_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "value": (f"0x{self.value:x}" if self.value is not None else None),
            "raw_text": self.raw_text,
            "evidence": self.evidence,
            "parse_error": self.parse_error,
        }


@dataclass
class RtlResetValueFinding:
    status: str  # FOUND | NOT_FOUND | AMBIGUOUS | UNPARSEABLE
    value: Optional[int]
    raw_text: Optional[str]
    evidence: Optional[str]
    reason: str
    assignments: List[RtlResetAssignment] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "value": (f"0x{self.value:x}" if self.value is not None else None),
            "raw_text": self.raw_text,
            "evidence": self.evidence,
            "reason": self.reason,
            "assignments": [a.to_dict() for a in self.assignments],
        }


def _find_reset_branch_body(text: str, if_match: "re.Match", window_end: int) -> Optional[Tuple[int, int]]:
    """Given a match for `_IF_COND_RE` (the reset-testing `if`), returns
    (body_start, body_end) offsets into `text` for its THEN-branch body -- a
    real `begin ... end` block, depth-tracked so a nested begin/end pair is
    never mistaken for the closing one, or (absent a `begin`) the single
    statement up to its own terminating `;`. Returns None if this scan
    cannot find a real close before `window_end` (the next always block's
    own header, or the end of the module) -- an honestly UNCLOSED branch,
    never guessed shut."""
    pos = if_match.end()
    pos = _LEADING_WS_RE.match(text, pos).end()
    if text[pos:pos + 5] == "begin" and (pos + 5 >= len(text) or not text[pos + 5].isalnum()):
        depth = 1
        cursor = pos + 5
        for tok in _BEGIN_END_TOKEN_RE.finditer(text, cursor, window_end):
            if tok.group() == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return (pos + 5, tok.start())
        return None
    semi = text.find(";", pos, window_end)
    if semi == -1:
        return None
    return (pos, semi + 1)


def find_rtl_reset_assignments(
    module_text: str, target_name: str, *, path: Optional[str] = None, base_line: int = 1,
) -> List[RtlResetAssignment]:
    """Scans ONE module's own source text for every sequential
    `always`/`always_ff` block whose own reset-testing first `if` (per
    `interrupt_dma_clock_reset_extraction.py`'s identical "the block's own
    first real conditional" convention) sits over its THEN-branch and
    assigns `target_name` a literal value there. Never raises on malformed
    text -- an unclosed reset branch simply contributes nothing."""
    clean = _strip_noise_preserve_offsets(module_text)
    assign_re = re.compile(
        r"\b" + re.escape(target_name) + r"\b\s*(?:\[[^\]]*\])?\s*(?:<=|=)\s*(?P<rhs>[^;]+);"
    )
    always_matches = list(_ALWAYS_SEQ_RE.finditer(clean))
    assignments: List[RtlResetAssignment] = []
    for i, am in enumerate(always_matches):
        window_end = always_matches[i + 1].start() if i + 1 < len(always_matches) else len(clean)
        if_m = _IF_COND_RE.search(clean, am.end(), window_end)
        if not if_m or not _RESET_NAME_RE.search(if_m.group("name")):
            continue
        body_span = _find_reset_branch_body(clean, if_m, window_end)
        if body_span is None:
            continue
        body_start, body_end = body_span
        body_text = clean[body_start:body_end]
        for m in assign_re.finditer(body_text):
            abs_offset = body_start + m.start()
            line = base_line + clean.count("\n", 0, abs_offset)
            raw_text = m.group("rhs").strip()
            value, err = parse_verilog_literal(raw_text)
            evidence = f"{path}:{line}" if path else f"line {line}"
            assignments.append(RtlResetAssignment(value=value, raw_text=raw_text, evidence=evidence, parse_error=err))
    return assignments


def resolve_rtl_reset_value(assignments: Sequence[RtlResetAssignment], *, target_name: str) -> RtlResetValueFinding:
    """Folds a (possibly empty) list of real reset-branch assignments into
    one honest finding. Never picks a value out of disagreeing evidence --
    see module docstring."""
    assignments = list(assignments)
    if not assignments:
        return RtlResetValueFinding(
            status="NOT_FOUND", value=None, raw_text=None, evidence=None,
            reason=(
                f"no assignment to {target_name!r} was found inside any always/always_ff block's "
                f"own reset-testing if-branch in this module's source text"
            ),
            assignments=[],
        )
    parseable = [a for a in assignments if a.value is not None]
    if not parseable:
        first = assignments[0]
        return RtlResetValueFinding(
            status="UNPARSEABLE", value=None, raw_text=first.raw_text, evidence=first.evidence,
            reason=(
                f"a reset-branch assignment to {target_name!r} was found ({first.raw_text!r} at "
                f"{first.evidence}) but its value could not be parsed as a determinate literal: "
                f"{first.parse_error}"
            ),
            assignments=assignments,
        )
    distinct_values = sorted(set(a.value for a in parseable))
    if len(distinct_values) > 1:
        return RtlResetValueFinding(
            status="AMBIGUOUS", value=None, raw_text=None, evidence=None,
            reason=(
                f"{len(parseable)} reset-branch assignment(s) to {target_name!r} were found with "
                f"disagreeing literal values {[hex(v) for v in distinct_values]!r} -- never resolved "
                f"by picking one"
            ),
            assignments=assignments,
        )
    chosen = parseable[0]
    return RtlResetValueFinding(
        status="FOUND", value=chosen.value, raw_text=chosen.raw_text, evidence=chosen.evidence,
        reason=f"unambiguous reset-branch assignment {target_name} <= {chosen.raw_text!r} at {chosen.evidence}",
        assignments=assignments,
    )


# ---------------------------------------------------------------------------
# Module source spans -- verible_parser.py's real front end, re-derived
# locally (see module docstring's REUSE note): the "module -> its own
# source span -> module_text" primitive design_architecture_ir.py's FSM scan
# already established, needed here because neither register_rtl_trace.py nor
# verible_parser.py's own ModuleInfo/RtlSite shapes carry a source span.
# ---------------------------------------------------------------------------

@dataclass
class ModuleSpan:
    module_name: str
    file_path: str
    text: str
    base_line: int


def module_source_spans(
    file_path: Any, *, verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN,
) -> Tuple[List[ModuleSpan], Optional[str]]:
    """Runs the REAL verible front end over `file_path` and returns
    (spans, error). `error` is set, and `spans` is empty, when the file
    could not be read, verible could not be run, or verible reported a real
    syntax error -- never a partial/guessed span list."""
    p = Path(file_path)
    try:
        source = p.read_text(encoding="utf-8", newline="")
    except OSError as exc:
        return [], f"could not read file: {exc}"
    try:
        tree = verible_parser.run_export_json(p, verible_bin=verible_bin)
    except verible_parser.VeribleUnavailableError as exc:
        return [], f"verible could not be run: {exc}"
    except verible_parser.VeribleParseError as exc:
        return [], f"verible reported a real syntax error: {exc}"
    module_nodes = verible_parser.find_all_nonoverlapping(tree, "kModuleDeclaration")
    module_infos = verible_parser.extract_modules(tree, source)
    spans: List[ModuleSpan] = []
    for node, minfo in zip(module_nodes, module_infos):
        if minfo.name is None:
            continue
        span = verible_parser.node_span(node)
        if span is None:
            continue
        text = source[span[0]:span[1]]
        base_line = source.count("\n", 0, span[0]) + 1
        spans.append(ModuleSpan(module_name=minfo.name, file_path=str(p), text=text, base_line=base_line))
    return spans, None


def build_module_span_index(
    rtl_paths: Sequence[Any], *, verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN,
) -> Tuple[Dict[Tuple[str, str], ModuleSpan], List[dict]]:
    """Builds a `(file_path, module_name) -> ModuleSpan` index across many
    real files, once, for reuse across many registers -- mirroring
    `register_rtl_trace.collect_rtl_sites()`'s own "build the index once"
    convention. One bad file never blocks the rest; its reason lands in the
    returned warnings list."""
    index: Dict[Tuple[str, str], ModuleSpan] = {}
    warnings: List[dict] = []
    for raw_path in rtl_paths or []:
        spans, err = module_source_spans(raw_path, verible_bin=verible_bin)
        if err:
            warnings.append({"file_path": str(raw_path), "reason": err})
            continue
        for s in spans:
            index[(s.file_path, s.module_name)] = s
    return index, warnings


# ---------------------------------------------------------------------------
# The comparison itself
# ---------------------------------------------------------------------------

def _hex_or_none(value: Optional[int]) -> Optional[str]:
    return f"0x{value:x}" if isinstance(value, int) and not isinstance(value, bool) else None


def compare_reset_values(
    documented_value: Optional[int],
    documented_raw: Optional[str],
    rtl_finding: Optional[RtlResetValueFinding],
    trace_status: str,
    trace_reason: str,
) -> Tuple[str, str]:
    """Pure comparison logic, isolated from the I/O it is normally fed by --
    the one function that actually decides MATCH/MISMATCH/UNKNOWN. Every
    branch names the real fact it is missing; nothing here is ever silently
    defaulted."""
    if documented_value is None:
        return STATUS_UNKNOWN, (
            "no documented reset value was transcribed for this register/field "
            "(register_excel_extract.py recorded none)"
        )
    if trace_status == register_rtl_trace.TRACE_BLOCKED:
        return STATUS_UNKNOWN, f"the RTL trace could not be attempted: {trace_reason}"
    if trace_status != register_rtl_trace.TRACE_CONFIRMED:
        return STATUS_UNKNOWN, (
            f"the RTL trace did not resolve to a single unambiguous, referenced site "
            f"(status={trace_status}): {trace_reason}"
        )
    if rtl_finding is None:
        return STATUS_UNKNOWN, (
            "no module source span was available to scan for a reset-branch assignment, even "
            "though the RTL trace confirmed a site for this name"
        )
    if rtl_finding.status != "FOUND":
        return STATUS_UNKNOWN, (
            f"the RTL reset-value scan did not resolve to a single unambiguous literal "
            f"(status={rtl_finding.status}): {rtl_finding.reason}"
        )
    documented_label = documented_raw or _hex_or_none(documented_value)
    rtl_label = f"{rtl_finding.raw_text!r} = {_hex_or_none(rtl_finding.value)}"
    if documented_value == rtl_finding.value:
        return STATUS_MATCH, (
            f"documented reset value {documented_label} agrees with RTL's own reset-branch "
            f"assignment ({rtl_label}) at {rtl_finding.evidence}"
        )
    return STATUS_MISMATCH, (
        f"documented reset value {documented_label} disagrees with RTL's own reset-branch "
        f"assignment ({rtl_label}) at {rtl_finding.evidence}"
    )


@dataclass
class RegisterResetComparison:
    register_name: str
    block_name: Optional[str]
    field_name: Optional[str]
    documented_reset_value: Optional[int]
    documented_reset_value_raw: Optional[str]
    trace_status: str
    trace_reason: str
    rtl_finding: Optional[RtlResetValueFinding]
    status: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "register_name": self.register_name,
            "block_name": self.block_name,
            "field_name": self.field_name,
            "documented_reset_value": _hex_or_none(self.documented_reset_value),
            "documented_reset_value_raw": self.documented_reset_value_raw,
            "trace_status": self.trace_status,
            "trace_reason": self.trace_reason,
            "rtl_finding": (self.rtl_finding.to_dict() if self.rtl_finding else None),
            "status": self.status,
            "reason": self.reason,
        }


def correlate_register_reset_value(
    name: str,
    documented_value: Optional[int],
    documented_raw: Optional[str],
    *,
    register_name: Optional[str] = None,
    block_name: Optional[str] = None,
    field_name: Optional[str] = None,
    sites: List["register_rtl_trace.RtlSite"],
    span_index: Dict[Tuple[str, str], ModuleSpan],
    parse_warnings: Optional[List[dict]] = None,
) -> RegisterResetComparison:
    """Correlates ONE register or field: real-traces `name` against `sites`
    (built once by a caller via `register_rtl_trace.collect_rtl_sites()`),
    then, only on a real TRACE_CONFIRMED, scans that ONE confirmed site's own
    module span (from `span_index`) for a real reset-branch literal
    assignment. Never re-derives the trace decision and never scans a module
    the trace did not itself confirm."""
    field_ref = register_rtl_trace.RegisterFieldRef(
        name=name, register_name=register_name, block_name=block_name,
    )
    trace = register_rtl_trace.trace_register_field(field_ref, sites=sites, parse_warnings=parse_warnings)

    rtl_finding: Optional[RtlResetValueFinding] = None
    if trace.status == register_rtl_trace.TRACE_CONFIRMED and trace.candidates:
        site = trace.candidates[0].site
        span = span_index.get((site.file_path, site.module_name))
        if span is not None:
            assignments = find_rtl_reset_assignments(
                span.text, site.raw_name, path=site.file_path, base_line=span.base_line,
            )
            rtl_finding = resolve_rtl_reset_value(assignments, target_name=site.raw_name)

    status, reason = compare_reset_values(
        documented_value, documented_raw, rtl_finding, trace.status, trace.reason,
    )
    return RegisterResetComparison(
        register_name=register_name or name,
        block_name=block_name,
        field_name=field_name,
        documented_reset_value=documented_value,
        documented_reset_value_raw=documented_raw,
        trace_status=trace.status,
        trace_reason=trace.reason,
        rtl_finding=rtl_finding,
        status=status,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Whole register-map orchestration
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def correlate_register_map_reset_values(
    registers: Sequence[Any],
    rtl_paths: Sequence[Any],
    *,
    verible_bin: str = register_rtl_trace.DEFAULT_VERIBLE_BIN,
    include_fields: bool = True,
) -> Dict[str, Any]:
    """The whole-register-map front door: `registers` is a sequence of
    `register_excel_extract.RegisterIR` objects (or duck-typed dicts of the
    same shape -- `register_name`/`block`/`reset_value`/`fields`); `fields`
    entries are `RegisterFieldIR`-shaped (`name`/`reset_value`). Builds the
    RTL site index and the module-span index ONCE (mirroring
    `register_rtl_trace.trace_register_fields()`'s own "build once, trace
    many" convention) and correlates every register (and, unless
    `include_fields=False`, every field) against it."""
    parsed, parse_warnings = register_rtl_trace.parse_rtl_sources(rtl_paths, verible_bin=verible_bin)
    sites = register_rtl_trace.collect_rtl_sites(parsed)
    span_index, span_warnings = build_module_span_index(rtl_paths, verible_bin=verible_bin)

    results: List[RegisterResetComparison] = []
    for reg in registers:
        reg_name = _get(reg, "register_name")
        block = _get(reg, "block")
        reset_value = _get(reg, "reset_value")
        results.append(correlate_register_reset_value(
            reg_name, reset_value, _hex_or_none(reset_value),
            register_name=reg_name, block_name=block, field_name=None,
            sites=sites, span_index=span_index, parse_warnings=parse_warnings,
        ))
        if include_fields:
            for fld in _get(reg, "fields") or []:
                fld_name = _get(fld, "name")
                fld_reset = _get(fld, "reset_value")
                results.append(correlate_register_reset_value(
                    fld_name, fld_reset, _hex_or_none(fld_reset),
                    register_name=reg_name, block_name=block, field_name=fld_name,
                    sites=sites, span_index=span_index, parse_warnings=parse_warnings,
                ))

    summary = {s: 0 for s in CORRELATION_STATUSES}
    for r in results:
        summary[r.status] += 1
    return {
        "results": [r.to_dict() for r in results],
        "summary": summary,
        "rtl_parse_warnings": parse_warnings,
        "module_span_warnings": span_warnings,
    }


# ---------------------------------------------------------------------------
# CLI front door -- `python -m dv_harness.register_reset_value_correlation`.
# No `dv-harness` verb: cli.py is out of this task's file-safety scope, the
# same convention register_excel_extract.py and register_rtl_trace.py
# themselves already follow.
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.register_reset_value_correlation",
        description=(
            "Cross-check a register-map spreadsheet's documented reset value "
            "(register_excel_extract.py) against real RTL reset-branch logic "
            "(register_rtl_trace.py) and report MATCH/MISMATCH/UNKNOWN per "
            "register and field."
        ),
    )
    parser.add_argument("--register-source", required=True, help="register-map .xlsx/.csv file")
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--rtl", action="append", required=True, dest="rtl_paths",
                         help="an RTL source file to scan (repeatable)")
    parser.add_argument("--verible-bin", default=register_rtl_trace.DEFAULT_VERIBLE_BIN)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    extraction = register_excel_extract.extract_register_map(args.register_source, sheet_name=args.sheet)
    if extraction.status == register_excel_extract.STATUS_NOT_AVAILABLE:
        print(f"register source not available: {extraction.reason}", file=sys.stderr)
        return 2
    if not extraction.registers:
        print(f"no registers extracted from {args.register_source!r}: {extraction.reason}", file=sys.stderr)
        return 2

    report = correlate_register_map_reset_values(
        extraction.registers, args.rtl_paths, verible_bin=args.verible_bin,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in report["results"]:
            label = f"{r['register_name']}.{r['field_name']}" if r["field_name"] else r["register_name"]
            print(f"{label:32s} {r['status']:10s} {r['reason']}")
        print(f"\nsummary: {report['summary']}")
        if report["rtl_parse_warnings"]:
            print(f"rtl parse warnings: {report['rtl_parse_warnings']}")
        if report["module_span_warnings"]:
            print(f"module span warnings: {report['module_span_warnings']}")

    return 1 if report["summary"][STATUS_MISMATCH] else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(argv)


if __name__ == "__main__":
    sys.exit(main())
