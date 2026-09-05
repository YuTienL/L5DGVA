"""dv_harness/verible_parser.py -- structured RTL/SystemVerilog parsing via
verible's real `--export_json --printtree` mode (2026-09-03, verible+DuckDB
evidence-store task; user's own spec: "verible --export_json ... 讓 RTL/
Verilog 結構化，不必全部靠 regex").

This module invokes the REAL `verible-verilog-syntax` binary as a
subprocess and walks its REAL syntax-tree JSON shape (confirmed against a
live install this session -- see .work/governance-evidence-report.md for
the exact `--version` output and sample JSON fragments this parser's node-
shape assumptions were verified against, both the success shape
(`{"<path>": {"tree": {...}}}`) and the real syntax-error shape
(`{"<path>": {"errors": [{"line","column","phase","text"}, ...]}}`, no
"tree" key at all, nonzero exit code). Never guessed from documentation
alone.

Tree shape (verible's own convention, confirmed live): every node is a
dict. An INTERNAL node has a "children" key (a list, holding `None` in
elided grammar-slot positions) and a "tag" naming the grammar production
(e.g. "kModuleDeclaration", "kPortDeclaration", "kDataType"). A LEAF node
has no "children" key, only "start"/"end" (byte offsets into the source
text) and a "tag" -- for a fixed keyword/punctuation token the tag IS the
literal text (e.g. tag=="input"); for a variable token (identifiers,
numbers) a separate "text" field holds the actual text and "tag" names the
token category (e.g. "SymbolIdentifier", "TK_DecNumber").

Scope (matches the task's own scope note: "module/port/signal hierarchy",
not a full elaboration/semantic model): per module, this extracts the
module name, its parameter list (name/type-text/default-text), its port
list (name/direction/data-type-text), and its module-level signal
declarations (name/data-type-text/unpacked-dimension-text, e.g. a memory
array's `[0:DEPTH-1]`). Signals declared inside a procedural block
(always_ff/always_comb/initial) are deliberately NOT surfaced -- this walks
`kModuleItemList`'s own DIRECT children only, which is exactly the
module-level declaration scope "signal hierarchy" means here.

Since 2026-09-04 it ALSO extracts, per module, the STRUCTURAL WIRING that a
declaration-only view cannot express: every module instantiation (instance
name + instantiated module name), each instantiation's port connections
(named `.p(net)` and positional alike, with the connected expression's base
identifiers), and every continuous `assign` (its lhs/rhs base identifiers).
That is the raw data a port-level connectivity graph is built from -- "this
instance's port P connects to net N, which also connects to that instance's
port Q" -- and it was the single missing prerequisite for AMBA-7..14's
endpoint tracing (`dv_harness/amba_fabric_discovery.py`), which consumes it.
verible's tree already carried these nodes (`kInstantiationBase` /
`kGateInstance` / `kPortActualList` / `kActualNamedPort` /
`kActualPositionalPort` / `kContinuousAssignmentStatement`, every tag
confirmed live against this install, not read from documentation); nothing
walked them.

Instantiations are collected from anywhere inside the module body,
generate blocks included (AMBA-7 lists "generate blocks" among the
structures a trace must cross), stopping only at a NESTED module
declaration so its contents are not mis-scoped into the enclosing module.
Generate-block CONDITIONS are not evaluated -- this is a parser, not an
elaborator -- so a generate-conditional instance is reported as present;
a consumer that needs elaboration-time truth must say so rather than
assume this settled it. Expression
text (parameter defaults, packed/unpacked dimension bounds) is recovered by
slicing the ORIGINAL SOURCE TEXT at a subtree's own min-start/max-end span,
never by re-deriving it from the parse tree's operator/operand structure --
robust to any expression shape verible's grammar allows, without this
module having to model SystemVerilog expression syntax itself.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

DEFAULT_VERIBLE_BIN = "verible-verilog-syntax"
_DIRECTIONS = {"input", "output", "inout", "ref"}


class VeribleUnavailableError(RuntimeError):
    """The verible-verilog-syntax binary could not be run at all (not on
    PATH, or timed out) -- distinct from VeribleParseError below, which
    means verible ran fine but the SOURCE FILE itself has real syntax
    errors."""


class VeribleParseError(RuntimeError):
    """verible ran and reported real syntax errors for this file (its own
    "errors" list, no "tree" key) -- e.g. a genuinely-malformed .sv file.
    Carries the raw error dicts verible itself reported on `.errors`."""

    def __init__(self, file_path: str, errors: list):
        self.file_path = file_path
        self.errors = errors
        detail = "; ".join(
            f"{e.get('phase', '?')}:{e.get('line', '?')}:{e.get('column', '?')}: {e.get('text', '?')}"
            for e in errors
        )
        super().__init__(f"verible reported syntax error(s) in {file_path}: {detail}")


@dataclass
class PortInfo:
    name: Optional[str]
    direction: Optional[str]
    data_type: Optional[str]


@dataclass
class ParamInfo:
    name: Optional[str]
    type_text: Optional[str]
    default_text: Optional[str]


@dataclass
class SignalInfo:
    name: Optional[str]
    data_type: Optional[str]
    unpacked_dims: Optional[str]


@dataclass
class PortConnectionInfo:
    """One `.port(expr)` or positional connection on one instantiation.

    `port_name` is None for a POSITIONAL connection -- resolving which formal
    port that position names requires the instantiated module's own port list,
    which is a different file's fact and therefore a consumer's job, not this
    per-file parser's. `position` is the 0-based slot in the port-actual list
    for exactly that resolution. `nets` holds the BASE identifiers the
    connected expression references (e.g. `bus[7:0]` -> ["bus"], `{a, b}` ->
    ["a", "b"], `1'b0` -> []), which is what a net-level graph joins on;
    `expr_text` keeps the original source slice so nothing is lost."""
    port_name: Optional[str]
    position: int
    expr_text: Optional[str]
    nets: list = field(default_factory=list)


@dataclass
class InstanceInfo:
    """One module instantiation inside a module body."""
    instance_name: Optional[str]
    module_name: Optional[str]
    connections: list = field(default_factory=list)   # list[PortConnectionInfo]


@dataclass
class ContinuousAssignInfo:
    """One continuous `assign lhs = rhs;`. AMBA-7 requires a trace to cross
    "wire assignments / aliases", and a net renamed by an assign is exactly
    that: `lhs_nets`/`rhs_nets` are the base identifiers on each side."""
    lhs_text: Optional[str]
    rhs_text: Optional[str]
    lhs_nets: list = field(default_factory=list)
    rhs_nets: list = field(default_factory=list)


@dataclass
class ModuleInfo:
    name: Optional[str]
    parameters: list = field(default_factory=list)   # list[ParamInfo]
    ports: list = field(default_factory=list)         # list[PortInfo]
    signals: list = field(default_factory=list)       # list[SignalInfo]
    instances: list = field(default_factory=list)     # list[InstanceInfo]
    continuous_assigns: list = field(default_factory=list)  # list[ContinuousAssignInfo]


@dataclass
class FileParseResult:
    file_path: str
    source_sha256: str
    verible_version: Optional[str]
    modules: list          # list[ModuleInfo]


def get_verible_version(verible_bin: str = DEFAULT_VERIBLE_BIN) -> Optional[str]:
    try:
        proc = subprocess.run([verible_bin, "--version"], capture_output=True,
                               text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("Version"):
            return line.split("\t", 1)[-1].strip()
    return (proc.stdout or "").strip() or None


def run_export_json(file_path, verible_bin: str = DEFAULT_VERIBLE_BIN) -> dict:
    """Invokes `verible-verilog-syntax --export_json --printtree <file>` for
    real and returns the parsed JSON dict for exactly that one file's entry
    (`{"tree": {...}}` on success). Raises VeribleUnavailableError if the
    binary itself cannot be run, or VeribleParseError if verible ran but
    reported real syntax errors for this file (see module docstring for
    both real, confirmed shapes)."""
    path_str = str(file_path)
    argv = [verible_bin, "--export_json", "--printtree", path_str]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as e:
        raise VeribleUnavailableError(
            f"{verible_bin!r} not found on PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise VeribleUnavailableError(f"{verible_bin!r} timed out: {e}") from e
    try:
        parsed = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise VeribleUnavailableError(
            f"failed to parse verible --export_json output: {e}; "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}") from e
    entry = parsed.get(path_str)
    if entry is None:
        raise VeribleUnavailableError(
            f"verible output did not contain an entry for {path_str!r}: {parsed!r}")
    if "errors" in entry and entry.get("errors"):
        raise VeribleParseError(path_str, entry["errors"])
    tree = entry.get("tree")
    if tree is None:
        raise VeribleParseError(path_str, entry.get("errors") or [])
    return tree


# ---- generic tree-walk helpers (operate on verible's real node shape) -----

def _walk(node):
    """Pre-order traversal over every dict node in the subtree (leaf and
    internal), skipping the `None` placeholders verible emits for elided
    grammar slots."""
    if node is None or not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []) or []:
        yield from _walk(child)


def _find_first(node, tag: str) -> Optional[dict]:
    """First internal (non-leaf) descendant anywhere in the subtree whose
    tag matches, pre-order. Used for the (at most one expected) container
    nodes like kModuleHeader/kPortDeclarationList/kFormalParameterList."""
    for n in _walk(node):
        if n.get("tag") == tag and "children" in n:
            return n
    return None


def _find_all_nonoverlapping(node, tag: str) -> list:
    """DFS collection of every node whose tag matches; once a match is
    found, its own subtree is NOT descended into further -- this keeps a
    nested occurrence of the same tag (e.g. a module declared inside
    another) from being mis-scoped into its enclosing match."""
    results: list = []

    def _rec(n):
        if n is None or not isinstance(n, dict):
            return
        if n.get("tag") == tag and "children" in n:
            results.append(n)
            return
        for c in n.get("children", []) or []:
            _rec(c)

    _rec(node)
    return results


def _direct_children_tagged(node, tag: str) -> list:
    if not node or "children" not in node:
        return []
    return [c for c in node["children"] if isinstance(c, dict) and c.get("tag") == tag]


def _direct_child_tagged(node, tag: str) -> Optional[dict]:
    matches = _direct_children_tagged(node, tag)
    return matches[0] if matches else None


def _span(node):
    """Recursive (min start, max end) over every leaf token in the subtree
    -- the real byte-offset range of this construct in the ORIGINAL source
    text, regardless of how deeply the grammar nested it."""
    starts, ends = [], []
    for n in _walk(node):
        if "start" in n and "end" in n:
            starts.append(n["start"])
            ends.append(n["end"])
    if not starts:
        return None
    return min(starts), max(ends)


def _text_of(node, source: str) -> Optional[str]:
    span = _span(node)
    if span is None:
        return None
    a, b = span
    return source[a:b]


def _first_leaf_text(node, tag: str) -> Optional[str]:
    """First leaf descendant (pre-order) whose tag matches; returns its
    "text" field, or the tag itself for a fixed-keyword leaf that has no
    separate "text" (verible's own convention -- see module docstring)."""
    if node is None:
        return None
    for n in _walk(node):
        if n.get("tag") == tag and "children" not in n:
            return n.get("text", n.get("tag"))
    return None


def _direct_direction(port_node) -> Optional[str]:
    for c in port_node.get("children", []) or []:
        if isinstance(c, dict) and c.get("tag") in _DIRECTIONS:
            return c["tag"]
    return None


# ---- module/port/param/signal extraction ----------------------------------

def _extract_params(header, source: str) -> list:
    param_list = _find_first(header, "kFormalParameterList")
    if param_list is None:
        return []
    out = []
    for pd in _direct_children_tagged(param_list, "kParamDeclaration"):
        param_type = _direct_child_tagged(pd, "kParamType")
        name = _first_leaf_text(param_type, "SymbolIdentifier")
        type_text = _text_of(_direct_child_tagged(param_type, "kTypeInfo"), source) if param_type else None
        trailing = _direct_child_tagged(pd, "kTrailingAssign")
        default_text = _text_of(_direct_child_tagged(trailing, "kExpression"), source) if trailing else None
        out.append(ParamInfo(name=name, type_text=type_text, default_text=default_text))
    return out


def _extract_ports(header, source: str) -> list:
    port_list = _find_first(header, "kPortDeclarationList")
    if port_list is None:
        return []
    out = []
    for p in _direct_children_tagged(port_list, "kPortDeclaration"):
        direction = _direct_direction(p)
        data_type_node = _direct_child_tagged(p, "kDataType")
        data_type = _text_of(data_type_node, source)
        id_node = _direct_child_tagged(p, "kUnqualifiedId")
        name = _first_leaf_text(id_node, "SymbolIdentifier")
        out.append(PortInfo(name=name, direction=direction, data_type=data_type))
    return out


def _extract_signals(module_node, source: str) -> list:
    item_list = _direct_child_tagged(module_node, "kModuleItemList")
    if item_list is None:
        return []
    out = []
    for dd in _direct_children_tagged(item_list, "kDataDeclaration"):
        data_type_node = _find_first(dd, "kDataType")
        data_type = _text_of(data_type_node, source)
        for rv in _find_all_nonoverlapping(dd, "kRegisterVariable"):
            name = _first_leaf_text(rv, "SymbolIdentifier")
            unpacked_node = _direct_child_tagged(rv, "kUnpackedDimensions")
            unpacked_text = _text_of(unpacked_node, source) if unpacked_node else None
            out.append(SignalInfo(name=name, data_type=data_type, unpacked_dims=unpacked_text))
    return out


def _collect_in_module_body(module_node, tag: str) -> list:
    """Every node with `tag` anywhere inside this module's body, INCLUDING
    inside generate blocks, but never descending into a nested
    `kModuleDeclaration` (whose contents belong to that inner module, not
    this one -- the same mis-scoping `_find_all_nonoverlapping()` guards
    against for module declarations themselves)."""
    results: list = []

    def _rec(n, is_root: bool):
        if n is None or not isinstance(n, dict):
            return
        if not is_root and n.get("tag") == "kModuleDeclaration":
            return
        if n.get("tag") == tag and "children" in n:
            results.append(n)
            return
        for c in n.get("children", []) or []:
            _rec(c, False)

    _rec(module_node, True)
    return results


def _reference_base_names(node) -> list:
    """The BASE identifier of every reference in an expression subtree, in
    source order and de-duplicated.

    Uses `_find_all_nonoverlapping(..., "kReference")` deliberately: it stops
    at each outermost reference, so an INDEX expression nested inside one
    (`bus[IDX]`, whose `IDX` is its own inner `kReference`) does not leak in
    as if it were a second connected net. `{a, b}` still yields both, because
    a concatenation's elements are sibling references, not nested ones."""
    out: list = []
    for ref in _find_all_nonoverlapping(node, "kReference"):
        name = _first_leaf_text(ref, "SymbolIdentifier")
        if name and name not in out:
            out.append(name)
    return out


def _extract_port_connections(gate_instance, source: str) -> list:
    """The port-actual list of one `kGateInstance`. Named and positional
    connections are both real and both kept; an explicitly-unconnected port
    (`.p()`) yields an entry with no nets rather than being dropped, since
    "this port is deliberately left open" is itself a connectivity fact.

    `position` is counted from the COMMA SEPARATORS, not from how many port
    nodes have been seen (confirmed against live verible output, 2026-09-04):
    an OMITTED positional slot -- `leaf u (a, , c)`, meaning "leave port 1
    open" -- is elided from the tree entirely, only its commas survive. A
    node-counting index would therefore call `c` position 1 and silently wire
    it to the wrong formal port of every module instantiated that way."""
    actual_list = _find_first(gate_instance, "kPortActualList")
    if actual_list is None:
        return []
    out: list = []
    position = 0
    for child in actual_list.get("children", []) or []:
        if not isinstance(child, dict):
            continue
        tag = child.get("tag")
        if tag == ",":
            position += 1
            continue
        if tag == "kActualNamedPort":
            port_name = _first_leaf_text(child, "SymbolIdentifier")
            paren = _direct_child_tagged(child, "kParenGroup")
            expr = _find_first(paren, "kExpression") if paren is not None else None
            out.append(PortConnectionInfo(
                port_name=port_name,
                position=position,
                expr_text=_text_of(expr, source) if expr is not None else None,
                nets=_reference_base_names(expr) if expr is not None else [],
            ))
        elif tag == "kActualPositionalPort":
            expr = _find_first(child, "kExpression")
            out.append(PortConnectionInfo(
                port_name=None,
                position=position,
                expr_text=_text_of(expr, source) if expr is not None else None,
                nets=_reference_base_names(expr) if expr is not None else [],
            ))
    return out


def _extract_instances(module_node, source: str) -> list:
    """Every module instantiation in this module's body.

    verible reuses `kDataDeclaration` for both a signal declaration and an
    instantiation; the discriminator is the `kInstantiationBase` child, which
    only an instantiation has. One declaration may instantiate several
    instances (`sub u0(...), u1(...);`), so every `kGateInstance` under it is
    emitted separately."""
    out: list = []
    for decl in _collect_in_module_body(module_node, "kDataDeclaration"):
        base = _find_first(decl, "kInstantiationBase")
        if base is None:
            continue
        inst_type = _direct_child_tagged(base, "kInstantiationType")
        module_name = _first_leaf_text(inst_type, "SymbolIdentifier")
        for gate in _find_all_nonoverlapping(base, "kGateInstance"):
            out.append(InstanceInfo(
                instance_name=_first_leaf_text(gate, "SymbolIdentifier"),
                module_name=module_name,
                connections=_extract_port_connections(gate, source),
            ))
    return out


def _extract_continuous_assigns(module_node, source: str) -> list:
    """Every continuous `assign` in this module's body, one entry per
    assignment (`assign a = b, c = d;` is two)."""
    out: list = []
    for stmt in _collect_in_module_body(module_node, "kContinuousAssignmentStatement"):
        for nva in _find_all_nonoverlapping(stmt, "kNetVariableAssignment"):
            lhs = _direct_child_tagged(nva, "kLPValue")
            rhs = _direct_child_tagged(nva, "kExpression")
            out.append(ContinuousAssignInfo(
                lhs_text=_text_of(lhs, source) if lhs is not None else None,
                rhs_text=_text_of(rhs, source) if rhs is not None else None,
                lhs_nets=_reference_base_names(lhs) if lhs is not None else [],
                rhs_nets=_reference_base_names(rhs) if rhs is not None else [],
            ))
    return out


def extract_modules(tree: dict, source: str) -> list:
    """The real module/port/signal extraction over an already-parsed
    verible syntax tree (see run_export_json()) plus the ORIGINAL source
    text (needed to slice out type/expression text -- see module
    docstring). Returns a list[ModuleInfo]; an empty list for a file with
    no module declaration (e.g. a package-only file) is a legitimate,
    correct result, not an error."""
    modules = []
    for m in _find_all_nonoverlapping(tree, "kModuleDeclaration"):
        header = _find_first(m, "kModuleHeader")
        name = _first_leaf_text(header, "SymbolIdentifier") if header is not None else None
        modules.append(ModuleInfo(
            name=name,
            parameters=_extract_params(header, source) if header is not None else [],
            ports=_extract_ports(header, source) if header is not None else [],
            signals=_extract_signals(m, source),
            instances=_extract_instances(m, source),
            continuous_assigns=_extract_continuous_assigns(m, source),
        ))
    return modules


def parse_file(file_path, verible_bin: str = DEFAULT_VERIBLE_BIN) -> FileParseResult:
    """The one real end-to-end entry point: reads `file_path`, runs real
    verible `--export_json --printtree` against it, and returns a
    structured FileParseResult (module/port/param/signal hierarchy).
    Raises VeribleUnavailableError/VeribleParseError -- see their own
    docstrings -- never silently returns an empty/fabricated result for a
    file verible could not actually parse."""
    path = Path(file_path)
    # `newline=""` (BUG FIX, 2026-09-03, confirmed via a real failing test on
    # this Windows machine): verible's own start/end offsets are byte offsets
    # into the file EXACTLY AS IT SITS ON DISK, `\r\n` included. Python's
    # default text-mode read applies universal-newline translation
    # (`\r\n` -> `\n`), which silently shortens the in-memory string by one
    # character per line -- every `_span()`-based slice after the first
    # affected line then drifts by that same growing offset (confirmed
    # failure mode: `_text_of()` returning garbage like "c    " instead of
    # "logic" for a CRLF-saved fixture). Reading with newline="" disables
    # that translation so this string's offsets stay byte-for-byte aligned
    # with verible's, regardless of which line-ending convention the file
    # was saved with.
    source = path.read_text(encoding="utf-8", newline="")
    tree = run_export_json(path, verible_bin=verible_bin)
    modules = extract_modules(tree, source)
    return FileParseResult(
        file_path=str(path),
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        verible_version=get_verible_version(verible_bin),
        modules=modules,
    )


# ---- public aliases for the tree-walk helpers above ------------------------
# The helpers above are named with a leading underscore because they were
# private to this module's own RTL extraction. dv_harness/uvm_structural_lint.py
# walks the SAME verible `--export_json --printtree` tree shape for CLASS-based
# UVM source, and the alternative to reusing them is a second SystemVerilog
# tree walker in this package -- exactly what CLAUDE.md's Methodology
# Consolidation Rule forbids. These aliases make that reuse a supported,
# named contract instead of a cross-module private import. They are aliases,
# not wrappers: there is one implementation, and it is the one this module's
# own extraction already exercises.
walk_tree = _walk
find_first_tagged = _find_first
find_all_nonoverlapping = _find_all_nonoverlapping
direct_children_tagged = _direct_children_tagged
direct_child_tagged = _direct_child_tagged
node_span = _span
node_text = _text_of
first_leaf_text = _first_leaf_text


def to_dict(result: FileParseResult) -> dict:
    """Plain-dict form of a FileParseResult, suitable for JSON serialization
    or direct hand-off to evidence_db.insert_rtl_parse()."""
    return {
        "file_path": result.file_path,
        "source_sha256": result.source_sha256,
        "verible_version": result.verible_version,
        "modules": [
            {
                "name": mod.name,
                "parameters": [vars(p) for p in mod.parameters],
                "ports": [vars(p) for p in mod.ports],
                "signals": [vars(s) for s in mod.signals],
                "instances": [
                    {
                        "instance_name": inst.instance_name,
                        "module_name": inst.module_name,
                        "connections": [vars(c) for c in inst.connections],
                    }
                    for inst in mod.instances
                ],
                "continuous_assigns": [vars(a) for a in mod.continuous_assigns],
            }
            for mod in result.modules
        ],
    }
