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
module-level declaration scope "signal hierarchy" means here. Expression
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
class ModuleInfo:
    name: Optional[str]
    parameters: list = field(default_factory=list)   # list[ParamInfo]
    ports: list = field(default_factory=list)         # list[PortInfo]
    signals: list = field(default_factory=list)       # list[SignalInfo]


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
            }
            for mod in result.modules
        ],
    }
