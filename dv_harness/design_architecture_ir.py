"""dv_harness/design_architecture_ir.py -- a fuller ArchitectureIR built on
TOP of verible_parser.py's existing per-file output (a read-only import;
this module never re-parses SystemVerilog itself and never re-implements
verible_parser's own tree-walk).

THE GAP THIS CLOSES
-------------------
`dv_harness/verible_parser.py` already extracts, per RTL FILE, each module's
ports/parameters/module-level signals plus its instantiations and
continuous assigns (its own docstring: "module/port/signal hierarchy, not a
full elaboration/semantic model"). Nothing in this repo turns that
per-FILE fact set into one architecture-wide picture: a MULTI-FILE module
registry, a full recursive INSTANCE TREE (not merely one module's own flat
instance list), and any notion of a module's internal FSM/control-flow
shape. `env_manifest.py`'s `build_dut_facts_rtl()` is the closest existing
consumer and deliberately stops at "fold each file's parse into a list,
sorted by file_path" -- it never resolves one module's instance against
another file's declaration, and it carries no FSM concept at all.

WHAT THIS MODULE IS
--------------------
Two real, tractable extensions over the SAME verible-parsed facts:

  1. FULL INSTANCE TREE. `build_module_registry()` folds every parsed
     file's modules into one name-keyed registry (first occurrence wins,
     deterministically, by sorted file_path; a name declared in more than
     one file is reported as a real `duplicate_modules` finding, never
     silently overwritten). `build_instance_tree()` then recursively
     resolves every instantiation's `module_name` against that registry --
     not just the top module's OWN flat instance list (which
     verible_parser.py already gives you), but every instance's own
     instances, all the way down, carrying each instance's real port
     connections at every level. A module instantiated but never supplied
     to this build (an external module, a VIP BFM, a std cell) is an
     honest, common, EXPECTED fact -- reported as an unresolved leaf, never
     an error and never silently dropped. A genuine instantiation CYCLE
     (A instantiates B, B instantiates A -- writable, if unusual, RTL) is
     detected by tracking the ancestor path and stopped rather than
     recursed forever.
  2. FSM/CONTROL-FLOW CANDIDATE SCAN -- deliberately NOT elaboration.
     `extract_fsm_candidates()` is a best-effort LITERAL scan (regex /
     light-parse) over the raw SOURCE TEXT of one module -- text
     verible_parser.py already isolated as that module's own byte span via
     its public `node_span()` -- looking for `always @(posedge <clk>...)`
     blocks that contain a `case` statement. It is NOT a second
     SystemVerilog parser and it does NOT walk verible's syntax tree for
     this part: no generate/`ifdef resolution, no expression evaluation, no
     proof that the case-keyed identifier is really a register (only that
     it is, or is not, among this module's own verible-extracted
     module-level signal declarations). Every candidate this scan produces
     carries an explicit status from a closed, honest vocabulary --
     FSM_EXTRACTION_RESOLVED / FSM_EXTRACTION_PARTIAL /
     FSM_EXTRACTION_UNPARSEABLE / NOT_APPLICABLE -- and a module with no
     always-posedge/case shape at all reports NOT_AVAILABLE with a real
     reason. A guessed state machine is never presented as a confirmed
     one: RESOLVED requires the case-key to be a single plain identifier
     that IS among the module's own declared signals, every non-default
     case item to have exactly one distinct resolvable self-assignment
     target, and the case block to have actually closed with a real
     `endcase` this scan could find. Anything short of that is PARTIAL (an
     ambiguity/registration problem) or UNPARSEABLE (this scan could not
     even close the block it found) -- never silently upgraded.

BOUNDARY, stated rather than implied closed
--------------------------------------------
  * This is DECLARATION/PATTERN-LEVEL extraction, not elaboration-time
    proof. It never runs a simulator, never resolves a parameter value,
    never evaluates a generate/`ifdef condition, and never proves a
    case-keyed identifier is actually a state register beyond "it is
    declared as a module-level signal here" -- a signal declared inside a
    procedural block is invisible to this check for the same reason
    verible_parser.py's own signal extraction deliberately does not surface
    it (see that module's docstring).
  * Only the FIRST `case`/`casex`/`casez` statement found inside each
    `always @(posedge ...)` block's own best-effort window (bounded by the
    next `always` header or the module's end) is scanned. A second,
    sibling (non-nested) case in the same always block is not examined.
  * Case-item labels are matched at the START of a line
    (`^\\s*<label>\\s*:`), for both named identifiers/`default` and
    Verilog-style sized literals (`2'b01:`). A label spelled any other way
    (e.g. two labels comma-joined on one line, `IDLE, WAIT_A:`) is
    captured as one combined label text rather than split.
  * `//` and `/* */` comments and `"..."` string literals inside the
    scanned module text are blanked out (length- and newline-preserving,
    so every reported offset/line stays correct) before any regex runs --
    otherwise a stray `case`/`endcase`/`always` spelled inside a comment or
    a string would corrupt the depth-counted case/endcase matching. This
    is the one piece of lexical hygiene a literal regex scan needs to be
    honest about its own false-positive class.
  * A generate-block-guarded or `ifdef-guarded case/always is reported
    exactly as written -- its guard condition is not evaluated, matching
    verible_parser.py's own documented stance on generate-block
    instantiations.
  * `duplicate_modules` reports only that two parsed files declare the
    same module name; it does not attempt `system_build_proof.py`'s real
    system-MERGE collision analysis (duplicate packages/types/factory-name
    collisions/config_db scope collisions across a composed multi-subsystem
    build) -- that is a different, already-real mechanism this module does
    not duplicate or extend.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from . import verible_parser
from .verible_parser import (
    DEFAULT_VERIBLE_BIN,
    VeribleParseError,
    VeribleUnavailableError,
    find_all_nonoverlapping,
    node_span,
)

SCHEMA_VERSION = "1.0"

__all__ = [
    "SCHEMA_VERSION",
    "DesignArchitectureIRError",
    "parse_rtl_file",
    "build_module_registry",
    "build_instance_tree",
    "extract_fsm_candidates",
    "build_architecture_ir",
    "save_architecture_ir",
    "format_report",
    "execute_verb",
    "main",
]


class DesignArchitectureIRError(Exception):
    """Raised only for a caller usage error (an explicitly-named
    `top_module` that does not exist among the parsed modules). Never
    raised for an absent/unresolvable RTL fact -- those are reported as
    NOT_AVAILABLE/PARTIAL fields on the IR itself, per the Evidence Truth
    Rule."""


# ---------------------------------------------------------------------------
# Lexical hygiene for the FSM literal scan (see module docstring)
# ---------------------------------------------------------------------------

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LIT_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _blank_out(match: "re.Match") -> str:
    return "".join(ch if ch == "\n" else " " for ch in match.group(0))


def _strip_noise_preserve_offsets(text: str) -> str:
    """Blanks //, /* */ and "..." content with spaces (newlines kept), so
    every character OFFSET and LINE NUMBER computed against the result
    still lines up with the real source -- this never reports an offset
    into a shortened copy that would disagree with the file on disk."""
    text = _BLOCK_COMMENT_RE.sub(_blank_out, text)
    text = _LINE_COMMENT_RE.sub(_blank_out, text)
    text = _STRING_LIT_RE.sub(_blank_out, text)
    return text


def _line_in_slice(base_line: int, slice_text: str, pos: int) -> int:
    return base_line + slice_text.count("\n", 0, pos)


# ---------------------------------------------------------------------------
# FSM/control-flow literal scan
# ---------------------------------------------------------------------------

_ALWAYS_POSEDGE_RE = re.compile(
    r"\balways(?:_ff)?\s*@\s*\(\s*posedge\s+(?P<clk>[A-Za-z_]\w*)"
    r"(?:\s*(?:,|or)\s*(?P<edge2>posedge|negedge)\s+(?P<rst>[A-Za-z_]\w*))?"
    r"\s*\)"
)
_CASE_OPEN_RE = re.compile(r"\bcase[xz]?\b\s*\(\s*(?P<expr>[^)]*?)\s*\)")
_RESET_IF_RE = re.compile(r"\bif\s*\(\s*(?P<cond>[^)]*?)\s*\)")

_LABEL_TEXT = r"(?:[A-Za-z_]\w*|default|\d*'[sS]?[bBoOdDhH][0-9a-fA-Fxz_]+|\d+)"
_BODY_SCAN_RE = re.compile(
    r"(?P<tok>\bcase[xz]?\b|\bendcase\b)"
    r"|(?P<lbl>^[ \t]*(?P<labeltext>" + _LABEL_TEXT + r")\s*:(?!=))",
    re.MULTILINE,
)
_ASSIGN_TARGET_RE_CACHE: Dict[str, "re.Pattern"] = {}


def _self_assignment_re(register_name: str) -> "re.Pattern":
    pat = _ASSIGN_TARGET_RE_CACHE.get(register_name)
    if pat is None:
        pat = re.compile(
            r"\b" + re.escape(register_name) + r"\b\s*(?:<=|=)\s*"
            r"(" + _LABEL_TEXT + r")\s*;"
        )
        _ASSIGN_TARGET_RE_CACHE[register_name] = pat
    return pat


def _find_self_assignments(item_text: str, register_name: str) -> List[str]:
    return [m.group(1) for m in _self_assignment_re(register_name).finditer(item_text)]


def _has_conditional(item_text: str) -> bool:
    return bool(re.search(r"\bif\b", item_text))


def _find_case_block(text: str, case_start: int) -> Optional[dict]:
    """From `case_start` (the index of the `case`/`casex`/`casez` keyword
    itself), depth-counts nested case/endcase pairs to find THIS case's own
    matching `endcase`, and collects its DIRECT (depth==1) item labels --
    a label inside a NESTED case (depth>1) is excluded, so a nested
    case-within-a-case-item does not leak its own labels in as if they were
    states of the outer FSM. Returns None if no matching `endcase` was
    found before the text ran out -- an UNPARSEABLE candidate: this scan
    could not close the block it found."""
    depth = 0
    items: List[dict] = []
    endcase_start: Optional[int] = None
    for m in _BODY_SCAN_RE.finditer(text, case_start):
        tok = m.group("tok")
        if tok is not None:
            if tok == "endcase":
                depth -= 1
                if depth == 0:
                    endcase_start = m.start()
                    break
            else:
                depth += 1
        else:
            if depth == 1:
                items.append({
                    "label": m.group("labeltext").strip(),
                    "start": m.start(),
                    "end": m.end(),
                })
    if endcase_start is None:
        return None
    return {"items": items, "endcase_start": endcase_start}


def extract_fsm_candidates(module_text: str, module_name: str,
                            declared_signal_names: Iterable[str], *,
                            base_line: int = 1) -> List[dict]:
    """Best-effort LITERAL scan of ONE module's own source text for
    `always @(posedge ...)` blocks containing a `case` statement keyed on
    an apparent state register. See module docstring for the full
    boundary. `declared_signal_names` should be that SAME module's own
    verible-extracted module-level signal names (never re-derived here).

    Returns a list of candidate dicts, one per `always @(posedge ...)`
    block found -- including a NOT_APPLICABLE entry for a posedge block
    that contains no case statement in this scan's window, so "this block
    exists and was examined and is not FSM-shaped" stays a distinct,
    visible fact rather than silent absence. Never raises for malformed
    input text; a block this scan cannot close is FSM_EXTRACTION_UNPARSEABLE,
    never a guessed FSM_EXTRACTION_RESOLVED."""
    clean = _strip_noise_preserve_offsets(module_text)
    declared = set(n for n in declared_signal_names if n)
    always_matches = list(_ALWAYS_POSEDGE_RE.finditer(clean))
    candidates: List[dict] = []
    for i, am in enumerate(always_matches):
        window_end = always_matches[i + 1].start() if i + 1 < len(always_matches) else len(clean)
        clock_signal = am.group("clk")
        reset_signal = am.group("rst")
        always_line = _line_in_slice(base_line, clean, am.start())

        case_open = _CASE_OPEN_RE.search(clean, am.end(), window_end)
        if case_open is None:
            candidates.append({
                "status": "NOT_APPLICABLE",
                "reason": "this always @(posedge ...) block contains no case statement in this "
                          "scan's window (may be a non-FSM sequential block, e.g. a plain "
                          "register or counter update)",
                "register_name": None, "register_expr": None,
                "clock_signal": clock_signal, "reset_signal": reset_signal,
                "reset_condition_text": None,
                "always_line": always_line, "case_line": None,
                "states": [], "has_default": False, "transitions": [],
                "unresolved_states": [], "ambiguous_states": [],
            })
            continue

        case_start = case_open.start()
        register_expr = case_open.group("expr").strip()
        case_line = _line_in_slice(base_line, clean, case_start)
        reset_if = _RESET_IF_RE.search(clean, am.end(), case_start)
        reset_condition_text = reset_if.group("cond").strip() if reset_if else None
        block = _find_case_block(clean, case_start)

        if block is None:
            candidates.append({
                "status": "FSM_EXTRACTION_UNPARSEABLE",
                "reason": "found 'case (%s)' after this always block's header but no matching "
                          "'endcase' before the module text ended -- this light scan could not "
                          "close the block, so no state/transition is reported" % register_expr,
                "register_name": None, "register_expr": register_expr,
                "clock_signal": clock_signal, "reset_signal": reset_signal,
                "reset_condition_text": reset_condition_text,
                "always_line": always_line, "case_line": case_line,
                "states": [], "has_default": False, "transitions": [],
                "unresolved_states": [], "ambiguous_states": [],
            })
            continue

        register_is_simple_identifier = bool(re.fullmatch(r"[A-Za-z_]\w*", register_expr))
        register_name = register_expr if register_is_simple_identifier else None
        reasons: List[str] = []
        if not register_is_simple_identifier:
            reasons.append(
                "case expression %r is not a single simple identifier -- this scan only "
                "resolves a case keyed directly on one register name" % register_expr)
        elif register_name not in declared:
            reasons.append(
                "register %r is not among %r's own declared module-level signals "
                "(verible-extracted) -- it may be a port, a genuinely undeclared name, or "
                "declared inside a procedural block this scan cannot see"
                % (register_name, module_name))

        states: List[str] = []
        has_default = False
        transitions: List[dict] = []
        unresolved_states: List[str] = []
        ambiguous_states: List[dict] = []
        items = block["items"]
        endcase_start = block["endcase_start"]
        for idx, item in enumerate(items):
            label = item["label"]
            body_start = item["end"]
            body_end = items[idx + 1]["start"] if idx + 1 < len(items) else endcase_start
            item_text = clean[body_start:body_end]
            if label == "default":
                has_default = True
            else:
                states.append(label)
            if register_name is None:
                continue
            targets = sorted(set(_find_self_assignments(item_text, register_name)))
            if not targets:
                unresolved_states.append(label)
            elif len(targets) == 1:
                transitions.append({
                    "from_state": label,
                    "to_state": targets[0],
                    "conditional": _has_conditional(item_text),
                })
            else:
                ambiguous_states.append({"state": label, "candidate_next_states": targets})

        if not items:
            reasons.append("case block closed with a real 'endcase' but no item label was "
                           "found at this scan's top-level nesting depth")
        for s in unresolved_states:
            reasons.append("state %r has no resolvable self-assignment to %r in this scan"
                           % (s, register_name))
        for a in ambiguous_states:
            reasons.append("state %r has multiple distinct candidate next states in this "
                           "scan: %s" % (a["state"], a["candidate_next_states"]))

        if register_name is not None and not reasons and states:
            status = "FSM_EXTRACTION_RESOLVED"
        else:
            status = "FSM_EXTRACTION_PARTIAL"

        candidates.append({
            "status": status,
            "reason": "; ".join(reasons) if reasons else None,
            "register_name": register_name,
            "register_expr": register_expr,
            "clock_signal": clock_signal,
            "reset_signal": reset_signal,
            "reset_condition_text": reset_condition_text,
            "always_line": always_line,
            "case_line": case_line,
            "states": states,
            "has_default": has_default,
            "transitions": transitions,
            "unresolved_states": unresolved_states,
            "ambiguous_states": ambiguous_states,
        })
    return candidates


def _module_fsm_summary(candidates: List[dict]) -> dict:
    if not candidates:
        return {
            "status": "NOT_AVAILABLE",
            "reason": "no 'always @(posedge ...)' block was found in this module's source text "
                      "(best-effort literal scan; an FSM written in a different shape -- "
                      "combinational next-state logic, an if/else chain instead of a case, a "
                      "different always-block form -- is not detected by this scan)",
            "candidates": [],
        }
    if all(c["status"] == "NOT_APPLICABLE" for c in candidates):
        return {
            "status": "NOT_AVAILABLE",
            "reason": "%d posedge always block(s) found; none contain a case statement in this "
                      "scan's window" % len(candidates),
            "candidates": candidates,
        }
    return {"status": "CANDIDATES_FOUND", "reason": None, "candidates": candidates}


# ---------------------------------------------------------------------------
# Per-file parse -- wraps verible_parser.py's own output; adds fsm_extraction
# ---------------------------------------------------------------------------

def parse_rtl_file(path: Union[str, Path], *, verible_bin: str = DEFAULT_VERIBLE_BIN) -> dict:
    """Wraps `verible_parser.parse_file()`'s real output for ONE file into
    the exact same dict shape `verible_parser.to_dict()` already produces
    (byte-identical ports/parameters/signals/instances/continuous_assigns
    per module -- nothing here re-derives any of that), and adds one new
    key per module: `fsm_extraction` (see `extract_fsm_candidates()`).

    Never raises for a file this scan cannot fully process: an unreadable
    file, an unrunnable verible binary, or a file with real syntax errors
    all report a distinct `status` (`NOT_AVAILABLE` / `PARSE_ERROR`) with a
    real reason and an empty `modules` list, so one bad file in a multi-file
    build never sinks the whole extraction."""
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
    # module_infos is built by extract_modules() walking the SAME
    # find_all_nonoverlapping(tree, "kModuleDeclaration") list, in the same
    # order (see verible_parser.py) -- zipping the independent re-walk above
    # against it is safe and gives each ModuleInfo its own raw declaration
    # node without a second, divergent tree traversal.
    result = verible_parser.FileParseResult(
        file_path=str(p), source_sha256=source_sha256,
        verible_version=verible_parser.get_verible_version(verible_bin),
        modules=module_infos,
    )
    out = verible_parser.to_dict(result)
    out["status"] = "PARSED"
    out["reason"] = None
    for node, module_dict, minfo in zip(module_nodes, out["modules"], module_infos):
        span = node_span(node)
        if span is None or minfo.name is None:
            module_dict["fsm_extraction"] = {
                "status": "NOT_AVAILABLE",
                "reason": "could not determine this module's own source span",
                "candidates": [],
            }
            continue
        module_text = source[span[0]:span[1]]
        base_line = source.count("\n", 0, span[0]) + 1
        signal_names = [s.name for s in minfo.signals]
        candidates = extract_fsm_candidates(module_text, minfo.name, signal_names, base_line=base_line)
        module_dict["fsm_extraction"] = _module_fsm_summary(candidates)
    return out


# ---------------------------------------------------------------------------
# Multi-file module registry + full instance tree
# ---------------------------------------------------------------------------

def build_module_registry(parsed_files: Sequence[dict]) -> Tuple[Dict[str, dict], List[dict]]:
    """Folds every real PARSED module across `parsed_files` (each a
    `parse_rtl_file()` result, in whatever order the caller passed them --
    pass them pre-sorted by file_path for a deterministic registry) into
    one name-keyed registry. The FIRST occurrence of a module name wins;
    every name seen in more than one file is reported in the returned
    `duplicate_modules` list, never silently overwritten."""
    registry: Dict[str, dict] = {}
    seen_files: Dict[str, List[str]] = {}
    for pf in parsed_files:
        if pf.get("status") != "PARSED":
            continue
        for mod in pf.get("modules", []):
            name = mod.get("name")
            if not name:
                continue
            seen_files.setdefault(name, []).append(pf["file_path"])
            if name not in registry:
                registry[name] = {
                    "module": mod,
                    "file_path": pf["file_path"],
                    "source_sha256": pf.get("source_sha256"),
                }
    duplicates = [
        {"module_name": name, "file_paths": paths}
        for name, paths in seen_files.items() if len(paths) > 1
    ]
    return registry, duplicates


def _instance_node(inst: dict, registry: Dict[str, dict], ancestors: Tuple[str, ...],
                    depth: int, max_depth: int) -> dict:
    module_name = inst.get("module_name")
    node = {
        "instance_name": inst.get("instance_name"),
        "module_name": module_name,
        "connections": inst.get("connections", []),
        "depth": depth,
        "resolved": False,
        "cycle_detected": False,
        "reason": None,
        "file_path": None,
        "ports": [],
        "parameters": [],
        "children": [],
    }
    if not module_name:
        node["reason"] = "instantiation carries no resolvable module (instance type) name"
        return node
    entry = registry.get(module_name)
    if entry is None:
        node["reason"] = (
            "module %r not found among the parsed RTL files -- an external/black-box module "
            "(a std cell, a VIP BFM, an interface module) or simply not included in this "
            "build's file list" % module_name)
        return node
    node["resolved"] = True
    node["file_path"] = entry["file_path"]
    node["ports"] = entry["module"].get("ports", [])
    node["parameters"] = entry["module"].get("parameters", [])
    if module_name in ancestors:
        node["cycle_detected"] = True
        node["reason"] = (
            "instance cycle: module %r already appears earlier on this same instantiation "
            "path (%s) -- stopping recursion here rather than looping forever"
            % (module_name, " -> ".join(ancestors + (module_name,))))
        return node
    if depth >= max_depth:
        node["reason"] = "max instance-tree depth (%d) reached -- stopping recursion here" % max_depth
        return node
    child_ancestors = ancestors + (module_name,)
    for child_inst in entry["module"].get("instances", []):
        node["children"].append(_instance_node(child_inst, registry, child_ancestors, depth + 1, max_depth))
    return node


def build_instance_tree(registry: Dict[str, dict], *, top_module: Optional[str] = None,
                         max_depth: int = 64) -> dict:
    """Builds the FULL, recursive instance tree over an already-built
    module registry (`build_module_registry()`) -- every resolved
    instance's own instances are followed all the way down, carrying each
    level's real port list/parameters and this instantiation's real
    connections; not merely the flat one-module instance list
    `verible_parser.py` already gives per module.

    A module never instantiated by any other parsed module is a real root
    of this parsed set's hierarchy. If none exists (e.g. a pure cycle among
    the parsed modules) every parsed module is reported as its own root
    rather than an empty forest, which would silently drop the whole
    hierarchy. `top_module`, if given, forces a single explicit root and
    raises DesignArchitectureIRError if that name was not actually parsed."""
    if top_module is not None:
        if top_module not in registry:
            raise DesignArchitectureIRError(
                "top_module %r was not found among the parsed modules (%s)"
                % (top_module, sorted(registry)))
        roots = [top_module]
    else:
        instantiated = {
            inst.get("module_name")
            for entry in registry.values()
            for inst in entry["module"].get("instances", [])
        }
        roots = [name for name in registry if name not in instantiated]
        if not roots and registry:
            roots = sorted(registry)
    trees = []
    for root in roots:
        entry = registry[root]
        root_node = {
            "instance_name": None, "module_name": root, "depth": 0,
            "resolved": True, "cycle_detected": False, "reason": None,
            "file_path": entry["file_path"],
            "ports": entry["module"].get("ports", []),
            "parameters": entry["module"].get("parameters", []),
            "connections": [], "children": [],
        }
        for child_inst in entry["module"].get("instances", []):
            root_node["children"].append(_instance_node(child_inst, registry, (root,), 1, max_depth))
        trees.append(root_node)
    return {"top_modules": roots, "trees": trees}


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def build_architecture_ir(rtl_files: Iterable[Union[str, Path]], *,
                           verible_bin: str = DEFAULT_VERIBLE_BIN,
                           top_module: Optional[str] = None,
                           max_instance_depth: int = 64) -> dict:
    """The one real entry point. Parses every file in `rtl_files` (each
    file's own status isolated -- one real syntax error, or one temporarily
    unrunnable verible invocation, never sinks the whole build), folds the
    real modules into one registry, builds the full instance tree, and
    attaches each module's best-effort FSM-candidate scan. Raises
    DesignArchitectureIRError only for a caller usage error (an explicit
    `top_module` that was never parsed); every RTL-fact absence is reported
    on the IR itself."""
    files = sorted(str(p) for p in rtl_files)
    if not files:
        return {
            "schema_version": SCHEMA_VERSION, "status": "NOT_AVAILABLE",
            "reason": "no rtl_files supplied", "files": [], "modules": {},
            "duplicate_modules": [], "instance_tree": {"top_modules": [], "trees": []},
            "warnings": [],
        }
    parsed = [parse_rtl_file(p, verible_bin=verible_bin) for p in files]
    registry, duplicates = build_module_registry(parsed)
    warnings: List[str] = []
    for pf in parsed:
        if pf["status"] != "PARSED":
            warnings.append("%s: %s -- %s" % (pf["file_path"], pf["status"], pf["reason"]))
    for dup in duplicates:
        warnings.append(
            "module %r declared in more than one parsed file: %s -- kept the first "
            "(deterministic sorted-file-path order)" % (dup["module_name"], dup["file_paths"]))
    if not registry:
        return {
            "schema_version": SCHEMA_VERSION, "status": "NOT_AVAILABLE",
            "reason": "no module could be parsed from any supplied rtl_files",
            "files": parsed, "modules": {}, "duplicate_modules": duplicates,
            "instance_tree": {"top_modules": [], "trees": []}, "warnings": warnings,
        }
    instance_tree = build_instance_tree(registry, top_module=top_module, max_depth=max_instance_depth)
    modules_out = {name: entry["module"] for name, entry in registry.items()}
    return {
        "schema_version": SCHEMA_VERSION, "status": "BUILT", "reason": None,
        "files": parsed, "modules": modules_out, "duplicate_modules": duplicates,
        "instance_tree": instance_tree, "warnings": warnings,
    }


def save_architecture_ir(ir: dict, path: Union[str, Path]) -> None:
    Path(path).write_text(json.dumps(ir, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _render_instance_tree(node: dict, lines: List[str], prefix: str = "") -> None:
    if node.get("instance_name"):
        label = "%s (%s)" % (node["instance_name"], node["module_name"])
    else:
        label = str(node["module_name"])
    if node.get("cycle_detected"):
        label += "  [CYCLE: %s]" % node["reason"]
    elif not node.get("resolved", True):
        label += "  [UNRESOLVED: %s]" % node["reason"]
    lines.append(prefix + label)
    for child in node.get("children", []):
        _render_instance_tree(child, lines, prefix + "  ")


def format_report(ir: dict) -> str:
    if ir["status"] != "BUILT":
        return "%s: %s" % (ir["status"], ir["reason"])
    lines = [
        "design_architecture_ir schema %s: %d module(s) parsed, %d top-level module(s)"
        % (ir["schema_version"], len(ir["modules"]), len(ir["instance_tree"]["top_modules"]))
    ]
    for w in ir["warnings"]:
        lines.append("  WARNING: %s" % w)
    for tree in ir["instance_tree"]["trees"]:
        _render_instance_tree(tree, lines, "  ")
    for name, mod in ir["modules"].items():
        fsm = mod.get("fsm_extraction", {})
        for c in fsm.get("candidates", []):
            if c["status"] in ("FSM_EXTRACTION_RESOLVED", "FSM_EXTRACTION_PARTIAL",
                               "FSM_EXTRACTION_UNPARSEABLE"):
                lines.append(
                    "  FSM candidate in %s (line %s): register=%r status=%s states=%s"
                    % (name, c.get("always_line"), c.get("register_name"), c["status"], c.get("states")))
    return "\n".join(lines)


def execute_verb(rtl_files: Sequence[Union[str, Path]], *,
                  verible_bin: str = DEFAULT_VERIBLE_BIN,
                  top_module: Optional[str] = None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.design_architecture_ir`
    (there is no `dv-harness` CLI verb for this yet -- see module docstring's
    disclosed residual in CLAUDE.md). Returns (text, exit_code): 0 the IR
    was built (at least one module parsed from at least one supplied file),
    2 NOT_AVAILABLE (no files supplied, or nothing could be parsed from any
    of them). Reads and reports only; runs, builds, submits and approves
    nothing."""
    ir = build_architecture_ir(rtl_files, verible_bin=verible_bin, top_module=top_module)
    text = json.dumps(ir, indent=2) if as_json else format_report(ir)
    code = 0 if ir["status"] == "BUILT" else 2
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.design_architecture_ir",
        description="Wrap verible_parser.py's per-file RTL facts into a full multi-file "
                    "ArchitectureIR: a complete recursive instance tree plus a best-effort, "
                    "explicitly-bounded FSM-candidate literal scan. Reads and reports only; "
                    "runs nothing.")
    ap.add_argument("--rtl", action="append", required=True, dest="rtl_files",
                    help="An RTL file to include in this build (repeatable).")
    ap.add_argument("--top-module", default=None,
                    help="Force this module as the sole instance-tree root.")
    ap.add_argument("--verible-bin", default=DEFAULT_VERIBLE_BIN)
    ap.add_argument("--out", default=None, help="Also write the full JSON IR to this path.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        ir = build_architecture_ir(a.rtl_files, verible_bin=a.verible_bin, top_module=a.top_module)
    except DesignArchitectureIRError as exc:
        print(str(exc))
        return 2
    text = json.dumps(ir, indent=2) if (a.json or a.out) else format_report(ir)
    code = 0 if ir["status"] == "BUILT" else 2
    if a.out:
        save_architecture_ir(ir, a.out)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
