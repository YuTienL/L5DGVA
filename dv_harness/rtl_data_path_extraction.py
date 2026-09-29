"""dv_harness/rtl_data_path_extraction.py -- bounded, disclosed-scope
DATA-PATH fact extraction (which signals feed which combinational/sequential
logic) over verible-parsed continuous-assign and always-block sources.

THE GAP THIS CLOSES
--------------------
`dv_harness/verible_parser.py` already extracts, per module, real continuous
`assign` statements with their LHS/RHS base identifiers already resolved
from the real syntax tree (`ContinuousAssignInfo.lhs_nets`/`rhs_nets`). Two
real consumers already exist for that fact -- `amba_fabric_discovery.py`/
`amba_fabric_analysis.py` use it narrowly, to trace a bus signal through a
1:1 wire-rename alias while building a FABRIC ROUTE, and
`register_rtl_trace.py` uses it narrowly, to ask whether a specific
register-field NAME is referenced anywhere in a module's RTL. Neither
exposes the continuous-assign fact as a general "signal X feeds signal Y"
data-path record, and neither says anything at all about PROCEDURAL
(always-block) assignments -- `verible_parser.py`'s own docstring is
explicit that signals/statements declared or assigned INSIDE a procedural
block are deliberately not surfaced by that parser.

`dv_harness/design_architecture_ir.py` adds exactly one procedural-content
extraction on top of verible_parser.py: a best-effort literal scan for
`always @(posedge ...)` blocks containing a `case`, scoped narrowly to
FSM-candidate detection (state register, states, transitions). It never
asks the wider question this module answers: for an ORDINARY (not
FSM-shaped) always block -- combinational or sequential -- which signals on
the right-hand side of an assignment feed which signal on the left, and
which of those blocks is combinational vs. sequential vs. an explicit latch.
`dv_harness/rtl_control_flow_extraction.py` already answers THAT
classification question (block_kind, if/else-if shape, case shape) but
deliberately stops at structural SHAPE -- its own docstring: "this module
never re-derives design_architecture_ir.py's own FSM state/transition
extraction... a module's FSM candidates stay that module's own job" -- and
it carries no signal-level LHS/RHS fact at all.

THIS MODULE
-----------
Extends BOTH of those existing extractions rather than re-deriving either:

  1. CONTINUOUS-ASSIGN DATA PATH. `extract_continuous_assign_data_path()`
     reads verible_parser.py's OWN already-parsed `ContinuousAssignInfo`
     records (`lhs_nets`/`rhs_nets`, resolved from the real syntax tree, not
     a text regex) and reports each one as a single COMBINATIONAL
     source->target fact. No re-parsing, no re-derivation: this is the
     identical primitive `amba_fabric_discovery.py`/`amba_fabric_analysis.py`
     and `register_rtl_trace.py` already consume, exposed here as a general
     data-path fact instead of narrowed to fabric-route-tracing or
     register-name-lookup.
  2. PROCEDURAL (always-block) DATA PATH. `extract_always_block_data_path()`
     reuses `rtl_control_flow_extraction.py`'s own always-block HEADER scan
     and block_kind classifier (`_ALWAYS_HEADER_RE` / `_classify_block_kind`
     / the `BLOCK_KIND_*` vocabulary) verbatim -- imported, never
     reimplemented, so this module's own "combinational vs. sequential"
     answer can never disagree with that module's -- and adds the one piece
     this repo does not have anywhere else: a bounded literal scan for
     `<lvalue> (<=|=) <rvalue>;` assignment STATEMENTS inside each block's
     own body, reporting the base signal name(s) written (targets) and the
     base signal name(s) read on the right-hand side, plus any signal
     referenced inside the lvalue's OWN bit-select/part-select index (e.g.
     `mem[i] <= x;` reports `i` as an additional data-path source, since it
     selects WHICH bits are written, not merely what is written).

WHAT IT REPORTS, PER MODULE
-----------------------------
  * `continuous_assigns`: one COMBINATIONAL_CONTINUOUS_ASSIGN fact per real
    `assign` statement verible_parser.py parsed for this module.
  * `always_blocks`: one entry per `always`/`always_ff`/`always_comb`/
    `always_latch` header this scan finds, carrying the SAME `block_kind`/
    `block_kind_reason` `rtl_control_flow_extraction.py` would report for
    that identical block (never re-derived, always identical), plus every
    `<lvalue> op <rvalue>;` assignment statement this scan found inside that
    block's own bounded window -- or, honestly, none, when the block
    genuinely contains no assignment statement this scan's pattern
    recognises (a task/function call, a `$display`, a bare `disable`, ...).
  * `facts`: the same continuous-assign and procedural-assignment records
    flattened into ONE list, in a uniform shape (`kind`, `evidence_source`,
    `block_kind`, `operator`, `targets`, `sources`, `lhs_text`, `rhs_text`,
    `line`) -- the direct "which signals feed this target" query surface;
    `signals_feeding()`/`signals_fed_by()` below are thin reads over this
    list, not a second extraction.

BOUNDARY, stated rather than implied closed
--------------------------------------------
  * This is a literal/regex scan over SOURCE TEXT for the procedural half
    (the continuous-assign half is real syntax-tree evidence, and is
    reported with a different `evidence_source` value so a reader can tell
    the two apart) -- not a second SystemVerilog parser and not an
    elaborator. No expression is evaluated, no `generate`/`` `ifdef ``
    condition is resolved, no parameter value is resolved, and no proof is
    ever offered that a referenced identifier really IS a signal in scope
    (as opposed to a loop variable, a local `automatic` declaration, or a
    genuinely undeclared name) beyond an OPTIONAL cross-check against a
    caller-supplied `known_signal_names` set -- when that set is not
    supplied, every `*_unrecognized` field is `None`, never a guessed
    empty/full list, because "not checked" and "checked and found nothing
    unrecognized" are different facts.
  * Before scanning for assignment statements, this module blanks out
    (length- and newline-preserving, exactly like
    `design_architecture_ir._strip_noise_preserve_offsets()`, which is
    reused for comments/strings first) every `if (...)`/`else if (...)`/
    `while (...)`/`for (...)`/`case[xz]? (...)` HEADER's own parenthesised
    content, one level deep only (no nested parens inside the header, the
    same bound `design_architecture_ir.py`'s own `_CASE_OPEN_RE`/
    `_RESET_IF_RE` already accept). This is what keeps a comparison
    operator inside a condition (`if (a <= b) ...`) from being
    mis-recognised as an assignment statement's own `<=`; a genuinely
    NESTED-paren condition header is scanned only up to its first `)`, and
    an assignment inside a `for (...)` loop's own header (`for (i = 0; ...)`)
    is deliberately excluded (loop-index bookkeeping, not a signal data-path
    fact).
  * The assignment-statement pattern recognises a plain identifier lvalue,
    an indexed/bit-selected lvalue (`sig[3:0]`, `mem[idx]`), and a
    concatenation lvalue (`{a, b[3:0]}`) split on top-level commas only --
    it does NOT recognise a compound assignment operator (`+=`, `-=`, ...),
    which this scan simply does not match (a real but rare RTL shape).
  * Only ONE assignment statement's worth of text is matched at a time via
    a non-overlapping scan; a single statement spanning more than one
    `;`-terminated clause (impossible for a plain assignment, but a defensive
    statement) is not a concern this scan needs to handle.
  * A generate-block-guarded or `` `ifdef ``-guarded always block or assign
    is reported exactly as written -- its guard condition is not evaluated,
    matching `verible_parser.py`'s and `design_architecture_ir.py`'s own
    documented stance.
  * This module never claims elaboration-time proof of anything: it reports
    a PATTERN found in source text (or a real syntax-tree fact for the
    continuous-assign half), never a proof that the reported edge is
    actually exercised, actually correct, or the ONLY path by which a
    target is ever written.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple, Union

from . import verible_parser
from .verible_parser import (
    DEFAULT_VERIBLE_BIN,
    VeribleParseError,
    VeribleUnavailableError,
    find_all_nonoverlapping,
    node_span,
)
from .design_architecture_ir import (
    _line_in_slice,
    _strip_noise_preserve_offsets,
)
from .rtl_control_flow_extraction import (
    _ALWAYS_HEADER_RE,
    _classify_block_kind,
    BLOCK_KIND_SEQUENTIAL,
    BLOCK_KIND_COMBINATIONAL,
    BLOCK_KIND_LATCH_EXPLICIT,
    BLOCK_KIND_UNCLASSIFIED,
)

SCHEMA_VERSION = "1.0"

__all__ = [
    "SCHEMA_VERSION",
    "RtlDataPathExtractionError",
    "extract_continuous_assign_data_path",
    "extract_always_block_data_path",
    "signals_feeding",
    "signals_fed_by",
    "parse_rtl_file",
    "build_data_path_ir",
    "save_data_path_ir",
    "format_report",
    "execute_verb",
    "main",
]


class RtlDataPathExtractionError(Exception):
    """Raised only for a caller usage error. Never raised for an absent or
    unresolvable data-path fact -- those are reported as NOT_AVAILABLE
    fields on the extraction result itself, per the Evidence Truth Rule."""


# ---------------------------------------------------------------------------
# Condition-header blanking (see module docstring's boundary note)
# ---------------------------------------------------------------------------

_COND_HEADER_RE = re.compile(
    r"\b(?:if|else\s+if|while|for|case[xz]?)\s*\([^()]*\)"
)


def _blank_span(match: "re.Match") -> str:
    return "".join(ch if ch == "\n" else " " for ch in match.group(0))


def _strip_condition_headers_preserve_offsets(text: str) -> str:
    """Blanks the parenthesised header of every `if`/`else if`/`while`/
    `for`/`case[xz]?` (length- and newline-preserving, so line numbers
    computed against the result still line up with the real source) so a
    comparison operator or a loop-index assignment inside one of those
    headers can never be mistaken for a real assignment STATEMENT. See
    module docstring's boundary note for the one-level-deep-parens bound."""
    return _COND_HEADER_RE.sub(_blank_span, text)


# ---------------------------------------------------------------------------
# Assignment-statement literal scan
# ---------------------------------------------------------------------------

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_INDEX_CONTENT_RE = re.compile(r"\[([^\[\]]*)\]")
_SIZED_LITERAL_RE = re.compile(r"\d*'[sS]?[bBoOdDhH][0-9a-fA-Fxz_]+")
_SYSTEM_TASK_RE = re.compile(r"\$[A-Za-z_]\w*")

_RHS_NOISE_WORDS = frozenset({
    "begin", "end", "if", "else", "case", "casex", "casez", "endcase",
    "default", "posedge", "negedge", "always", "always_ff", "always_comb",
    "always_latch", "wire", "reg", "logic", "integer", "genvar",
})

_IDENT = r"[A-Za-z_]\w*"
_INDEX = r"\[[^\[\]]*\]"
_LVALUE_ATOM = _IDENT + r"(?:\s*" + _INDEX + r")*"
_LVALUE_RE = (
    r"(?:\{\s*" + _LVALUE_ATOM + r"(?:\s*,\s*" + _LVALUE_ATOM + r")*\s*\}|" + _LVALUE_ATOM + r")"
)
_ASSIGN_STMT_RE = re.compile(
    r"(?P<lhs>" + _LVALUE_RE + r")\s*(?P<op><=|=)(?!=)\s*(?P<rhs>[^;]+?);"
)


def _rhs_signal_refs(text: str) -> List[str]:
    """Base identifier references in an expression's own text -- a sized
    literal's radix/digit run (`8'hFF`) and a system function/task name
    (`$clog2`) are blanked out first so neither is mis-read as a signal
    reference; a handful of structural keywords are excluded defensively
    (condition headers are normally already blanked before this runs, but
    this stays correct even called on unblanked text)."""
    cleaned = _SIZED_LITERAL_RE.sub(" ", text)
    cleaned = _SYSTEM_TASK_RE.sub(" ", cleaned)
    refs = set()
    for m in _IDENT_RE.finditer(cleaned):
        name = m.group(0)
        if name in _RHS_NOISE_WORDS:
            continue
        refs.add(name)
    return sorted(refs)


def _lvalue_targets_and_index_sources(lhs_text: str) -> Tuple[List[str], List[str]]:
    """Splits a matched lvalue (a single atom, or a `{...}` concatenation
    split on top-level commas -- a comma nested inside one atom's own
    bit-select is not expected and is not specially handled, a disclosed
    bound) into its base TARGET name(s), plus any signal referenced inside
    an atom's own bit-select/part-select index (e.g. the `i` in `mem[i]`) --
    that index expression SELECTS which bits are written, so it is reported
    as an additional data-path SOURCE for this assignment, never as a
    target."""
    inner = lhs_text.strip()
    if inner.startswith("{") and inner.endswith("}"):
        atoms = [a.strip() for a in inner[1:-1].split(",")]
    else:
        atoms = [inner]
    targets: List[str] = []
    index_sources: set = set()
    for atom in atoms:
        m = _IDENT_RE.match(atom)
        if not m:
            continue
        targets.append(m.group(0))
        for idx_m in _INDEX_CONTENT_RE.finditer(atom):
            index_sources.update(_rhs_signal_refs(idx_m.group(1)))
    return sorted(set(targets)), sorted(index_sources)


def _assignment_fact(match: "re.Match", *, operator: str, line: int,
                      always_line: Optional[int], block_kind: Optional[str],
                      known: Optional[set]) -> dict:
    lhs_text = match.group("lhs").strip()
    rhs_text = match.group("rhs").strip()
    targets, index_sources = _lvalue_targets_and_index_sources(lhs_text)
    rhs_sources = _rhs_signal_refs(rhs_text)
    sources = sorted(set(rhs_sources) | set(index_sources))
    fact = {
        "kind": "PROCEDURAL_ASSIGNMENT",
        "evidence_source": "LITERAL_SCAN",
        "block_kind": block_kind,
        "operator": operator,
        "targets": targets,
        "sources": sources,
        "rhs_sources": rhs_sources,
        "lvalue_index_sources": index_sources,
        "lhs_text": lhs_text,
        "rhs_text": rhs_text,
        "line": line,
        "always_line": always_line,
    }
    if known is not None:
        fact["targets_unrecognized"] = sorted(t for t in targets if t not in known)
        fact["sources_unrecognized"] = sorted(s for s in sources if s not in known)
    else:
        fact["targets_unrecognized"] = None
        fact["sources_unrecognized"] = None
    return fact


def extract_always_block_data_path(module_text: str, module_name: str, *,
                                    base_line: int = 1,
                                    known_signal_names: Optional[Iterable[str]] = None
                                    ) -> List[dict]:
    """Best-effort literal scan of ONE module's own source text for
    `always`/`always_ff`/`always_comb`/`always_latch` blocks, reporting each
    one's `block_kind` (reusing `rtl_control_flow_extraction.py`'s own
    classifier verbatim, never re-derived) plus every `<lvalue> op
    <rvalue>;` assignment statement this scan found inside it. Never raises
    for malformed input text; a block with no recognisable assignment
    statement in this scan's window reports an empty `assignments` list
    rather than being silently omitted -- "this block was examined and
    contains no assignment this scan recognises" stays a distinct, visible
    fact. `known_signal_names`, when supplied, is used ONLY to annotate
    each fact's `*_unrecognized` fields (never to filter/exclude a
    reference) -- see module docstring's boundary note."""
    clean = _strip_noise_preserve_offsets(module_text)
    known = set(known_signal_names) if known_signal_names is not None else None
    always_matches = list(_ALWAYS_HEADER_RE.finditer(clean))
    blocks: List[dict] = []
    for i, am in enumerate(always_matches):
        window_end = (
            always_matches[i + 1].start()
            if i + 1 < len(always_matches) else len(clean)
        )
        always_line = _line_in_slice(base_line, clean, am.start())
        variant = am.group("variant")
        keyword = "always" + (variant or "")
        block_kind, kind_reason = _classify_block_kind(
            variant, am.group("star"), am.group("sens"))

        body_start = am.end()
        window_text = clean[body_start:window_end]
        scan_text = _strip_condition_headers_preserve_offsets(window_text)

        assignments: List[dict] = []
        for m in _ASSIGN_STMT_RE.finditer(scan_text):
            operator = "NONBLOCKING" if m.group("op") == "<=" else "BLOCKING"
            abs_pos = body_start + m.start()
            line = _line_in_slice(base_line, clean, abs_pos)
            assignments.append(_assignment_fact(
                m, operator=operator, line=line, always_line=always_line,
                block_kind=block_kind, known=known))

        blocks.append({
            "keyword": keyword,
            "block_kind": block_kind,
            "block_kind_reason": kind_reason,
            "always_line": always_line,
            "status": "ASSIGNMENTS_FOUND" if assignments else
                      "NO_ASSIGNMENTS_FOUND_IN_SCAN_WINDOW",
            "assignments": assignments,
        })
    return blocks


def extract_continuous_assign_data_path(continuous_assigns: Sequence[dict]) -> List[dict]:
    """Turns verible_parser.py's OWN already-parsed continuous-assign
    records (`ContinuousAssignInfo.lhs_nets`/`rhs_nets`, resolved from the
    real syntax tree -- accepted here as plain dicts, the exact shape
    `verible_parser.to_dict()` already produces) into general data-path
    facts. No re-parsing and no re-derivation: `lhs_nets`/`rhs_nets` are
    used verbatim."""
    facts: List[dict] = []
    for ca in continuous_assigns:
        targets = sorted(set(ca.get("lhs_nets") or []))
        sources = sorted(set(ca.get("rhs_nets") or []))
        facts.append({
            "kind": "CONTINUOUS_ASSIGN",
            "evidence_source": "VERIBLE_PARSED_TREE",
            "block_kind": BLOCK_KIND_COMBINATIONAL,
            "operator": "CONTINUOUS",
            "targets": targets,
            "sources": sources,
            "rhs_sources": sources,
            "lvalue_index_sources": [],
            "lhs_text": ca.get("lhs_text"),
            "rhs_text": ca.get("rhs_text"),
            "line": None,
            "always_line": None,
            "targets_unrecognized": None,
            "sources_unrecognized": None,
        })
    return facts


def _module_data_path_summary(continuous_facts: List[dict], always_blocks: List[dict]) -> dict:
    has_any_assignment = any(b["assignments"] for b in always_blocks)
    facts = list(continuous_facts) + [
        a for b in always_blocks for a in b["assignments"]
    ]
    if not continuous_facts and not has_any_assignment:
        if always_blocks:
            reason = (
                "%d always block(s) found; none contain an assignment statement this "
                "scan's fixed pattern recognises, and no continuous 'assign' was found "
                "either" % len(always_blocks))
        else:
            reason = (
                "no continuous 'assign' statement and no 'always'/'always_ff'/"
                "'always_comb'/'always_latch' block was found in this module's source text")
        return {
            "status": "NOT_AVAILABLE", "reason": reason,
            "continuous_assigns": continuous_facts, "always_blocks": always_blocks,
            "facts": facts,
        }
    return {
        "status": "DATA_PATH_EXTRACTED", "reason": None,
        "continuous_assigns": continuous_facts, "always_blocks": always_blocks,
        "facts": facts,
    }


# ---------------------------------------------------------------------------
# Query helpers -- reads over an already-built module summary, never a
# second extraction
# ---------------------------------------------------------------------------

def signals_feeding(module_data_path: dict, target_name: str) -> List[dict]:
    """Every fact in an already-built module `data_path_extraction` summary
    (see `parse_rtl_file()`) whose own `targets` include `target_name` --
    i.e. every data-path fact that FEEDS this target. A pure read over
    already-extracted facts; performs no extraction of its own."""
    return [f for f in module_data_path.get("facts", []) if target_name in f.get("targets", [])]


def signals_fed_by(module_data_path: dict, source_name: str) -> List[dict]:
    """Every fact whose own `sources` include `source_name` -- i.e. every
    data-path fact this signal FEEDS INTO. See `signals_feeding()`."""
    return [f for f in module_data_path.get("facts", []) if source_name in f.get("sources", [])]


# ---------------------------------------------------------------------------
# Per-file parse -- wraps verible_parser.py's own output directly
# ---------------------------------------------------------------------------

def parse_rtl_file(path: Union[str, Path], *, verible_bin: str = DEFAULT_VERIBLE_BIN) -> dict:
    """Runs verible over ONE file and attaches `data_path_extraction` (see
    `_module_data_path_summary()`) to each real parsed module. Never raises
    for a file this scan cannot fully process: an unreadable file, an
    unrunnable verible binary, or a file with real syntax errors all report
    a distinct `status` (`NOT_AVAILABLE` / `PARSE_ERROR`) with a real reason
    and an empty `modules` list."""
    p = Path(path)
    try:
        source = p.read_text(encoding="utf-8", newline="")
    except OSError as exc:
        return {"file_path": str(p), "status": "NOT_AVAILABLE",
                "reason": "could not read file: %s" % exc,
                "source_sha256": None, "verible_version": None, "modules": []}
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    try:
        tree = verible_parser.run_export_json(p, verible_bin=verible_bin)
    except VeribleUnavailableError as exc:
        return {"file_path": str(p), "status": "NOT_AVAILABLE",
                "reason": "verible could not be run: %s" % exc,
                "source_sha256": source_sha256, "verible_version": None, "modules": []}
    except VeribleParseError as exc:
        return {"file_path": str(p), "status": "PARSE_ERROR", "reason": str(exc),
                "source_sha256": source_sha256,
                "verible_version": verible_parser.get_verible_version(verible_bin),
                "modules": []}

    module_nodes = find_all_nonoverlapping(tree, "kModuleDeclaration")
    module_infos = verible_parser.extract_modules(tree, source)
    modules_out: List[dict] = []
    for node, minfo in zip(module_nodes, module_infos):
        span = node_span(node)
        continuous_facts = extract_continuous_assign_data_path(
            [vars(a) for a in minfo.continuous_assigns])
        if span is None or minfo.name is None:
            modules_out.append({
                "name": minfo.name,
                "data_path_extraction": {
                    "status": "NOT_AVAILABLE",
                    "reason": "could not determine this module's own source span",
                    "continuous_assigns": continuous_facts, "always_blocks": [],
                    "facts": list(continuous_facts),
                },
            })
            continue
        module_text = source[span[0]:span[1]]
        base_line = source.count("\n", 0, span[0]) + 1
        known_names = frozenset(
            [p.name for p in minfo.ports if p.name] +
            [s.name for s in minfo.signals if s.name]
        )
        always_blocks = extract_always_block_data_path(
            module_text, minfo.name, base_line=base_line,
            known_signal_names=known_names)
        modules_out.append({
            "name": minfo.name,
            "data_path_extraction": _module_data_path_summary(continuous_facts, always_blocks),
        })

    return {
        "file_path": str(p), "status": "PARSED", "reason": None,
        "source_sha256": source_sha256,
        "verible_version": verible_parser.get_verible_version(verible_bin),
        "modules": modules_out,
    }


def build_data_path_ir(rtl_files: Sequence[Union[str, Path]], *,
                        verible_bin: str = DEFAULT_VERIBLE_BIN) -> dict:
    """The one real entry point over several files. Parses every file in
    `rtl_files` (each file's own status isolated -- one real syntax error
    never sinks the whole build) and attaches data-path extraction per
    module. No caller-usage error is possible here (an empty `rtl_files` is
    reported NOT_AVAILABLE, not raised)."""
    files = sorted(str(p) for p in rtl_files)
    if not files:
        return {"schema_version": SCHEMA_VERSION, "status": "NOT_AVAILABLE",
                "reason": "no rtl_files supplied", "files": []}
    parsed = [parse_rtl_file(p, verible_bin=verible_bin) for p in files]
    any_parsed = any(pf["status"] == "PARSED" for pf in parsed)
    status = "BUILT" if any_parsed else "NOT_AVAILABLE"
    reason = None if any_parsed else "no module could be parsed from any supplied rtl_files"
    return {"schema_version": SCHEMA_VERSION, "status": status, "reason": reason,
            "files": parsed}


def save_data_path_ir(ir: dict, path: Union[str, Path]) -> None:
    Path(path).write_text(json.dumps(ir, indent=2, sort_keys=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Reporting / CLI (standalone front door -- see this task's own disclosed
# choice not to edit cli.py/gates.py while they are under concurrent-batch
# edit pressure, matching several very recent same-day modules in this repo)
# ---------------------------------------------------------------------------

def format_report(ir: dict) -> str:
    if ir["status"] != "BUILT":
        return "%s: %s" % (ir["status"], ir.get("reason"))
    lines = ["rtl_data_path_extraction schema %s" % SCHEMA_VERSION]
    for pf in ir["files"]:
        if pf["status"] != "PARSED":
            lines.append("  %s: %s -- %s" % (pf["file_path"], pf["status"], pf["reason"]))
            continue
        for mod in pf["modules"]:
            dp = mod["data_path_extraction"]
            lines.append("  %s :: %s -- %s" % (pf["file_path"], mod["name"], dp["status"]))
            for f in dp.get("facts", []):
                lines.append(
                    "    %s (%s/%s) line=%s: %s <- %s"
                    % (f["kind"], f.get("block_kind"), f["operator"], f.get("line"),
                       f["targets"], f["sources"])
                )
    return "\n".join(lines)


def execute_verb(rtl_files: Sequence[Union[str, Path]], *,
                  verible_bin: str = DEFAULT_VERIBLE_BIN,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m
    dv_harness.rtl_data_path_extraction`. Returns (text, exit_code): 0 the
    IR was built (at least one module parsed from at least one supplied
    file), 2 NOT_AVAILABLE. Reads and reports only; runs, builds, submits
    and approves nothing."""
    ir = build_data_path_ir(rtl_files, verible_bin=verible_bin)
    text = json.dumps(ir, indent=2) if as_json else format_report(ir)
    code = 0 if ir["status"] == "BUILT" else 2
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.rtl_data_path_extraction",
        description="Bounded, disclosed-scope data-path extraction (which signals feed which "
                    "combinational/sequential logic) over verible-parsed continuous-assign and "
                    "always-block sources. Reads and reports only; runs nothing.")
    ap.add_argument("--rtl", action="append", required=True, dest="rtl_files",
                    help="An RTL file to include in this build (repeatable).")
    ap.add_argument("--verible-bin", default=DEFAULT_VERIBLE_BIN)
    ap.add_argument("--out", default=None, help="Also write the full JSON IR to this path.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    ir = build_data_path_ir(a.rtl_files, verible_bin=a.verible_bin)
    text = json.dumps(ir, indent=2) if (a.json or a.out) else format_report(ir)
    code = 0 if ir["status"] == "BUILT" else 2
    if a.out:
        save_data_path_ir(ir, a.out)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
