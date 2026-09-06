"""dv_harness/command_task_trace.py -- DE-command-name traceability, by real
grep-based cross-reference over a generated environment's own files (a
directory this module never mines content from -- see below).

WHAT THIS ANSWERS. `command-generator/SKILL.md` already declares the
traceability chain this repo is supposed to keep:
    REQ -> VP_ID -> SCENARIO -> COMMAND_ID -> HANDLER -> VIP_SEQUENCE ->
    CHECKER -> COVERAGE -> TEST/REGRESSION
and the CSV shape (`COMMAND_ID,COMMAND,HANDLER,VIP_SEQUENCE,CHECKER,
COVERAGE,SOURCE,STATUS`) that is supposed to carry it. Nothing in this repo
answered "for THIS DE command, where in the real generated files does that
chain actually land" -- `command_migration_integrity_gate.py` checks a
declared mapping's own JSON shape and command-catalog identity, never opens
the generated `.sv`/`.svh`/pattern-text files a HANDLER/CHECKER cell names.
This module does exactly that lookup, for one real generated environment at
a time (`env_dir`), and reports what it actually found -- never what the
mapping CLAIMS.

FOUR LEGS, matching this project's own real generated shapes (confirmed
against `examples/generated_usb_real_evidence_v1/` -- `patterns_registry/
dv_uvm_pattern_pool.svh`'s case-dispatch, `patterns_registry/
pattern_list.txt`'s `NAME SUITE FILE` registry rows, and `bind/
dv_uvm_hook.svh`'s real `` `define CPUWRITE1B dv_uvm_cpuwrite1b `` bridge
macro redirect -- not invented here):

  1. TASK_MACRO   the command resolves to a real Verilog `task`/`` `define ``
                  -- directly (the command IS the task/macro name), through a
                  case-dispatch statement (`"CMD": handler();`, the real
                  `dv_uvm_pattern_pool.svh` shape), or through a
                  `patterns_registry`-shaped text mapping (`CMD SUITE FILE`).
  2. UVM_BRIDGE   a real UVM API call (`uvm_config_db#(...)`, `p_sequencer.`,
                  `.start_item(`, an `` `uvm_do* `` macro, ...) or a reference
                  to this project's own established `dv_uvm_*` bridge-task
                  naming convention (`bind_mechanism_generator.py`'s real
                  generated `dv_uvm_hook.svh`), reached either directly in the
                  resolved body or through ONE level of `` `define `` macro
                  redirection followed from that body.
  3. VIP_API      a `// VIP:` citation comment (the real convention this
                  project's own hand-converted patterns use, e.g.
                  `tb/patterns/common/USB2_con_vip.txt`), or -- when the
                  caller declares `vip_prefixes` (e.g. `["svt_"]`, a project
                  fact this module never guesses) -- an identifier carrying
                  that prefix.
  4. CHECKER      a `` `*CHECK*(...) `` macro call citing this command or its
                  resolved handler name, or a scoreboard/checker/assertion-
                  named file referencing either.

STATUS is per-command: TRACE_COMPLETE (all four legs resolved, unambiguously),
TRACE_PARTIAL (at least one leg absent, OR any leg's textual match was
AMBIGUOUS), BLOCKED (env_dir/command_name itself unusable), NOT_FOUND (leg 1
found nothing at all -- there is no command to trace).

THE ONE RULE THAT MATTERS MOST: this is a DECLARATION-LEVEL TEXTUAL
CROSS-REFERENCE ONLY, exactly the bound `uvm_structural_lint.py` already
states for its own parser-level checks -- it CANNOT prove elaboration-time
behavior. `` `ifdef ``/generate conditions are not evaluated, a macro
redirect is followed exactly one level, and two textually-conflicting
declarations of the same name (two `task <cmd>` in two different files, two
case-dispatch entries resolving the same command string to two different
handler names) are a genuine ambiguity this analysis cannot resolve --
`_overall_status()` therefore NEVER reports TRACE_COMPLETE while any leg is
ambiguous, whatever the other three legs found. A leg with no evidence is
NOT_FOUND, never silently upgraded to a guess.

REUSE, not reinvention. The real UVM/VIP-body parsing engine in this repo is
`verible_parser.py`'s subprocess wrapper around `verible-verilog-syntax`, and
this module imports ONLY that (read-only) -- never `vip_symbol_index.py`,
`vip_api_card.py`, or `uvm_structural_lint.py`, none of which this task is
authorized to import. Verible is used for exactly one thing: OPTIONAL
enrichment of a single, unambiguous direct `task <cmd>` citation with its
real, parsed argument-list signature (`verible_parser`'s already-public
tree-walk aliases -- `find_all_nonoverlapping`/`direct_child_tagged`/
`node_text`/... -- the same "supported, named contract" that module's own
docstring establishes so a second SystemVerilog tree walker is never written
in this package). Verible being absent, or the file not parsing standalone,
never fails or blocks the grep-based trace itself -- it only means the
signature enrichment is NOT_AVAILABLE with a real reason, exactly the
graceful-degradation discipline `uvm_structural_lint.py` and
`vip_symbol_index.py` already apply to a construct they cannot understand.

WHAT THIS DOES NOT DO. It never invents a VIP API name, RTL content, or
command.txt semantics -- every citation is a real file:line this module
actually read. It never asserts a command COMPILES, RUNS, or behaves
correctly; it never touches a stage gate, a build, a regression, or any
human-approval mechanism. It reads files and reports what a textual scan
found, nothing else.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence

from . import verible_parser
from .verible_parser import (
    DEFAULT_VERIBLE_BIN,
    VeribleParseError,
    VeribleUnavailableError,
    direct_child_tagged,
    direct_children_tagged,
    find_all_nonoverlapping,
    first_leaf_text,
    node_span,
    node_text,
)

# --- vocabulary --------------------------------------------------------------

STATUS_TRACE_COMPLETE = "TRACE_COMPLETE"
STATUS_TRACE_PARTIAL = "TRACE_PARTIAL"
STATUS_BLOCKED = "BLOCKED"
STATUS_NOT_FOUND = "NOT_FOUND"

LEG_RESOLVED = "RESOLVED"
LEG_NOT_FOUND = "NOT_FOUND"
LEG_AMBIGUOUS = "AMBIGUOUS"

LEG_TASK_MACRO = "task_macro"
LEG_UVM_BRIDGE = "uvm_bridge"
LEG_VIP_API = "vip_api"
LEG_CHECKER = "checker"
LEG_ORDER = (LEG_TASK_MACRO, LEG_UVM_BRIDGE, LEG_VIP_API, LEG_CHECKER)

SOURCE_EXTENSIONS = frozenset({".sv", ".svh", ".v", ".vh", ".txt"})

# UVM bridge markers: real UVM API call shapes a task/pattern body can carry.
_UVM_BRIDGE_MARKER_PATTERNS = [
    re.compile(r"\buvm_config_db\s*#"),
    re.compile(r"\bp_sequencer\s*\."),
    re.compile(r"\buvm_top\b"),
    re.compile(r"`uvm_do\w*\b"),
    re.compile(r"`uvm_send\w*\b"),
    re.compile(r"\.start_item\s*\("),
    re.compile(r"\.start\s*\(\s*\w*sequencer"),
    re.compile(r"\bget_sequencer\s*\("),
]
# This project's own established bridge-task naming convention -- real
# generated evidence: bind_mechanism_generator.py's dv_uvm_hook.svh redirects
# `` `CPUWRITE1B `` to `dv_uvm_cpuwrite1b`.
_DV_UVM_BRIDGE_RE = re.compile(r"\bdv_uvm_[A-Za-z0-9_]*\b")
_MACRO_INVOKE_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_VIP_COMMENT_RE = re.compile(r"//\s*VIP\s*:\s*(.*)", re.IGNORECASE)
_CHECKER_FILE_NAME_RE = re.compile(r"(?i)(scoreboard|checker|assertion|_sva)")
_CHECKER_MACRO_CALL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")
_TASK_BODY_RE_TMPL = r"\btask\s+(?:automatic\s+)?{0}\b.*?\bendtask\b"
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class CommandTaskTraceError(ValueError):
    """Programmer misuse (e.g. an empty command-name list), never a
    could-not-trace outcome -- those are reported as BLOCKED/NOT_FOUND
    CommandTraceReport values, not raised."""


# --- data model --------------------------------------------------------------

@dataclass
class Citation:
    file_path: str
    line: int
    snippet: str
    kind: str
    detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line": self.line,
            "snippet": self.snippet,
            "kind": self.kind,
            "detail": self.detail,
        }


@dataclass
class LegResult:
    leg: str
    status: str
    citations: List[Citation] = field(default_factory=list)
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "leg": self.leg,
            "status": self.status,
            "reason": self.reason,
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass
class CommandTraceReport:
    command_name: str
    env_dir: str
    status: str
    reason: Optional[str] = None
    legs: Dict[str, LegResult] = field(default_factory=dict)
    verible_status: str = "NOT_ATTEMPTED"
    verible_reason: Optional[str] = None
    verible_signature: Optional[Dict[str, Any]] = None
    files_scanned: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_name": self.command_name,
            "env_dir": self.env_dir,
            "status": self.status,
            "reason": self.reason,
            "legs": {name: leg.to_dict() for name, leg in self.legs.items()},
            "verible_status": self.verible_status,
            "verible_reason": self.verible_reason,
            "verible_signature": self.verible_signature,
            "files_scanned": self.files_scanned,
        }


# --- generic text helpers ----------------------------------------------------

def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _snippet(text: str, offset: int, width: int = 140) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return text[start:end].strip()[:width]


def _dedup(citations: Sequence[Citation]) -> List[Citation]:
    seen = set()
    out: List[Citation] = []
    for c in citations:
        key = (c.file_path, c.line, c.kind, c.detail, c.snippet)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _iter_source_files(env_dir: Path) -> List[Path]:
    return sorted(
        p for p in env_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS
    )


def _read_all(env_dir: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in _iter_source_files(env_dir):
        try:
            out[str(p)] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return out


def _task_body(name: str, files_text: Dict[str, str]):
    """First `task ... <name> ... endtask` span found anywhere (declaration-
    level substring match, not a parse) -- used only to look one level deep
    when following a macro redirect target, never to resolve leg 1 itself."""
    pat = re.compile(_TASK_BODY_RE_TMPL.format(re.escape(name)), re.DOTALL)
    for path, text in files_text.items():
        m = pat.search(text)
        if m:
            return path, m.group(0)
    return None, None


def _body_has_uvm_marker(body_text: str) -> bool:
    if _DV_UVM_BRIDGE_RE.search(body_text):
        return True
    return any(p.search(body_text) for p in _UVM_BRIDGE_MARKER_PATTERNS)


# --- leg 1: task / macro resolution ------------------------------------------

def _resolve_task_macro(command: str, files_text: Dict[str, str], env_dir: Path):
    task_re = re.compile(r"\btask\s+(?:automatic\s+)?" + re.escape(command) + r"\s*[(;]")
    macro_re = re.compile(r"`define\s+" + re.escape(command) + r"\b")
    case_re = re.compile(r'"' + re.escape(command) + r'"\s*:\s*([A-Za-z_]\w*)\s*\(\s*\)\s*;')
    registry_re = re.compile(r"(?m)^\s*" + re.escape(command) + r"\s+(\S+)\s+(\S+)\s*$")

    citations: List[Citation] = []
    body_sources: Dict[str, str] = {}
    ambiguous_reasons: List[str] = []
    handler_name: Optional[str] = None

    # direct task declaration
    direct_task_locs = set()
    for path, text in files_text.items():
        for m in task_re.finditer(text):
            line = _line_of(text, m.start())
            citations.append(Citation(path, line, _snippet(text, m.start()), "task_declaration"))
            direct_task_locs.add((path, line))
            body_sources[path] = text
    if len(direct_task_locs) > 1:
        ambiguous_reasons.append(
            f"{len(direct_task_locs)} distinct 'task {command}' declarations found: "
            + ", ".join(f"{p}:{l}" for p, l in sorted(direct_task_locs)))

    # direct macro definition
    direct_macro_locs = set()
    for path, text in files_text.items():
        for m in macro_re.finditer(text):
            line = _line_of(text, m.start())
            citations.append(Citation(path, line, _snippet(text, m.start()), "macro_definition"))
            direct_macro_locs.add((path, line))
            body_sources[path] = text
    if len(direct_macro_locs) > 1:
        ambiguous_reasons.append(
            f"{len(direct_macro_locs)} distinct '`define {command}' definitions found: "
            + ", ".join(f"{p}:{l}" for p, l in sorted(direct_macro_locs)))

    # case-dispatch (the real dv_uvm_pattern_pool.svh shape)
    handlers = set()
    for path, text in files_text.items():
        for m in case_re.finditer(text):
            h = m.group(1)
            handlers.add(h)
            citations.append(Citation(path, _line_of(text, m.start()),
                                       _snippet(text, m.start()), "case_dispatch", detail=h))
    if len(handlers) > 1:
        ambiguous_reasons.append(
            f"case-dispatch resolves '{command}' to different handlers: {sorted(handlers)}")
    elif handlers:
        handler_name = next(iter(handlers))
        handler_task_re = re.compile(r"\btask\s+(?:automatic\s+)?" + re.escape(handler_name) + r"\s*[(;]")
        handler_locs = set()
        for path, text in files_text.items():
            for m in handler_task_re.finditer(text):
                line = _line_of(text, m.start())
                handler_locs.add((path, line))
                citations.append(Citation(path, line, _snippet(text, m.start()),
                                           "handler_task_declaration", detail=handler_name))
                body_sources[path] = text
        if len(handler_locs) > 1:
            ambiguous_reasons.append(
                f"handler task '{handler_name}' declared in {len(handler_locs)} places: "
                + ", ".join(f"{p}:{l}" for p, l in sorted(handler_locs)))

    # patterns_registry-shaped text mapping ("CMD SUITE FILE")
    registry_targets = set()
    for path, text in files_text.items():
        for m in registry_re.finditer(text):
            suite, relpath = m.group(1), m.group(2)
            registry_targets.add(relpath)
            citations.append(Citation(path, _line_of(text, m.start()), _snippet(text, m.start()),
                                       "registry_mapping", detail=f"{suite}:{relpath}"))
    if len(registry_targets) > 1:
        ambiguous_reasons.append(
            f"registry maps '{command}' to different files: {sorted(registry_targets)}")
    elif registry_targets:
        relpath = next(iter(registry_targets))
        try:
            candidate = (env_dir / PurePosixPath(relpath)).resolve()
            candidate.relative_to(env_dir.resolve())
        except (ValueError, OSError):
            candidate = None
        if candidate is not None and candidate.is_file():
            key = str(candidate)
            text = files_text.get(key)
            if text is None:
                try:
                    text = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = None
            if text is not None:
                body_sources[key] = text
                citations.append(Citation(key, 1, _snippet(text, 0), "registry_mapped_file",
                                           detail=relpath))

    citations = _dedup(citations)
    if not citations:
        return (LegResult(LEG_TASK_MACRO, LEG_NOT_FOUND, [], reason=(
            f"no task/macro declaration, case-dispatch entry, or registry mapping "
            f"found for {command!r} anywhere under {env_dir}")), {}, None)

    if ambiguous_reasons:
        return (LegResult(LEG_TASK_MACRO, LEG_AMBIGUOUS, citations,
                           reason="; ".join(ambiguous_reasons)), body_sources, handler_name)

    return (LegResult(LEG_TASK_MACRO, LEG_RESOLVED, citations, reason=None),
            body_sources, handler_name)


# --- leg 2: UVM bridge --------------------------------------------------------

def _resolve_uvm_bridge(body_sources: Dict[str, str], all_files_text: Dict[str, str]) -> LegResult:
    if not body_sources:
        return LegResult(LEG_UVM_BRIDGE, LEG_NOT_FOUND, [], reason=(
            "no resolved command body to search (task/macro leg was not resolved)"))

    citations: List[Citation] = []
    for path, text in body_sources.items():
        for pat in _UVM_BRIDGE_MARKER_PATTERNS:
            for m in pat.finditer(text):
                citations.append(Citation(path, _line_of(text, m.start()),
                                           _snippet(text, m.start()), "uvm_api_call"))
        for m in _DV_UVM_BRIDGE_RE.finditer(text):
            citations.append(Citation(path, _line_of(text, m.start()),
                                       _snippet(text, m.start()), "dv_uvm_bridge_reference"))

        # one level of macro-redirect closure: does a macro this body invokes
        # redirect (anywhere in the environment) to a bridge-shaped target?
        macro_names = {mo.group(1) for mo in _MACRO_INVOKE_RE.finditer(text)}
        for macro_name in sorted(macro_names):
            redirect_re = re.compile(r"`define\s+" + re.escape(macro_name) + r"\s+([A-Za-z_][A-Za-z0-9_]*)\b")
            for path2, text2 in all_files_text.items():
                for m2 in redirect_re.finditer(text2):
                    target = m2.group(1)
                    is_bridge = bool(_DV_UVM_BRIDGE_RE.fullmatch(target))
                    if not is_bridge:
                        _, body = _task_body(target, all_files_text)
                        is_bridge = bool(body) and _body_has_uvm_marker(body)
                    if is_bridge:
                        citations.append(Citation(
                            path2, _line_of(text2, m2.start()), _snippet(text2, m2.start()),
                            "macro_redirect_bridge", detail=f"`{macro_name} -> {target}"))

    citations = _dedup(citations)
    if citations:
        return LegResult(LEG_UVM_BRIDGE, LEG_RESOLVED, citations)
    return LegResult(LEG_UVM_BRIDGE, LEG_NOT_FOUND, [], reason=(
        "no direct UVM API call, no dv_uvm_* bridge reference, and no macro "
        "redirected to a bridge-shaped target was found in the resolved command body"))


# --- leg 3: VIP API reference -------------------------------------------------

def _resolve_vip_api(body_sources: Dict[str, str], vip_prefixes: Optional[Sequence[str]]) -> LegResult:
    if not body_sources:
        return LegResult(LEG_VIP_API, LEG_NOT_FOUND, [], reason=(
            "no resolved command body to search (task/macro leg was not resolved)"))

    citations: List[Citation] = []
    for path, text in body_sources.items():
        for m in _VIP_COMMENT_RE.finditer(text):
            detail = m.group(1).strip()
            first_ident = _IDENT_RE.search(detail)
            citations.append(Citation(path, _line_of(text, m.start()), _snippet(text, m.start()),
                                       "vip_comment_citation",
                                       detail=(first_ident.group(0) if first_ident else detail[:80])))
        for prefix in (vip_prefixes or []):
            if not prefix:
                continue
            pat = re.compile(r"\b" + re.escape(prefix) + r"[A-Za-z0-9_]*\b")
            for m in pat.finditer(text):
                citations.append(Citation(path, _line_of(text, m.start()), _snippet(text, m.start()),
                                           "vip_prefix_reference", detail=m.group(0)))

    citations = _dedup(citations)
    if citations:
        return LegResult(LEG_VIP_API, LEG_RESOLVED, citations)
    reason = "no '// VIP:' citation comment found in the resolved command body"
    if vip_prefixes:
        reason += f", and no identifier matching declared vip_prefixes={list(vip_prefixes)} was found either"
    else:
        reason += " (no vip_prefixes were supplied to widen the search)"
    return LegResult(LEG_VIP_API, LEG_NOT_FOUND, [], reason=reason)


# --- leg 4: checker reference --------------------------------------------------

def _resolve_checker(command: str, handler_name: Optional[str],
                      all_files_text: Dict[str, str]) -> LegResult:
    needles = {command}
    if handler_name:
        needles.add(handler_name)

    citations: List[Citation] = []
    for path, text in all_files_text.items():
        for m in _CHECKER_MACRO_CALL_RE.finditer(text):
            macro_name, args = m.group(1), m.group(2)
            if "CHECK" in macro_name.upper() and any(n in args for n in needles):
                citations.append(Citation(path, _line_of(text, m.start()), _snippet(text, m.start()),
                                           "checker_macro_call", detail=macro_name))
        if _CHECKER_FILE_NAME_RE.search(Path(path).name):
            for n in needles:
                idx = text.find(n)
                if idx != -1:
                    citations.append(Citation(path, _line_of(text, idx), _snippet(text, idx),
                                               "checker_file_reference", detail=n))

    citations = _dedup(citations)
    if citations:
        return LegResult(LEG_CHECKER, LEG_RESOLVED, citations)
    return LegResult(LEG_CHECKER, LEG_NOT_FOUND, [], reason=(
        f"no scoreboard/checker/assertion-named file referencing {sorted(needles)!r}, and no "
        f"'*CHECK*(...)' macro call citing it, found anywhere under env_dir"))


# --- overall status ----------------------------------------------------------

def _overall_status(legs: Dict[str, LegResult]):
    task_leg = legs[LEG_TASK_MACRO]
    if task_leg.status == LEG_NOT_FOUND:
        return STATUS_NOT_FOUND, task_leg.reason

    ambiguous = [name for name in LEG_ORDER if legs[name].status == LEG_AMBIGUOUS]
    if ambiguous:
        # Never upgraded to TRACE_COMPLETE: an ambiguous textual match means
        # this declaration-level scan cannot tell which definition actually
        # governs at elaboration time.
        detail = "; ".join(f"{name}: {legs[name].reason}" for name in ambiguous)
        return STATUS_TRACE_PARTIAL, (
            f"ambiguous textual match on leg(s) {ambiguous} -- {detail}")

    unresolved = [name for name in LEG_ORDER if legs[name].status == LEG_NOT_FOUND]
    if unresolved:
        return STATUS_TRACE_PARTIAL, f"leg(s) {unresolved} found no evidence"

    return STATUS_TRACE_COMPLETE, None


# --- verible enrichment (optional, read-only import) --------------------------

def _confirm_task_signature(tree: dict, source: str, name: str) -> Optional[Dict[str, Any]]:
    for decl in find_all_nonoverlapping(tree, "kTaskDeclaration"):
        header = direct_child_tagged(decl, "kTaskHeader")
        if header is None:
            continue
        name_node = direct_child_tagged(header, "kUnqualifiedId")
        found_name = first_leaf_text(name_node, "SymbolIdentifier") if name_node else None
        if found_name != name:
            continue
        args: List[Optional[str]] = []
        paren = direct_child_tagged(header, "kParenGroup")
        if paren is not None:
            port_list = direct_child_tagged(paren, "kPortList")
            if port_list is not None:
                for item in direct_children_tagged(port_list, "kPortItem"):
                    txt = node_text(item, source)
                    args.append(" ".join(txt.split()) if txt else None)
        span = node_span(decl)
        return {"name": found_name, "args": args, "line": _line_of(source, span[0]) if span else None}
    return None


def _enrich_with_verible(leg1: LegResult, files_text: Dict[str, str], command: str,
                          verible_bin: str):
    task_citations = [c for c in leg1.citations if c.kind == "task_declaration"]
    if len(task_citations) != 1:
        return (None, "NOT_ATTEMPTED", (
            "no single direct task declaration citation to confirm (command resolves "
            "via macro/dispatch/registry, or multiple direct declarations were found)"))
    citation = task_citations[0]
    source = files_text.get(citation.file_path)
    if source is None:
        return (None, "NOT_ATTEMPTED", "resolved citation's source text is no longer available")
    try:
        tree = verible_parser.run_export_json(citation.file_path, verible_bin=verible_bin)
    except VeribleUnavailableError as e:
        return (None, "NOT_AVAILABLE", str(e))
    except VeribleParseError as e:
        return (None, "PARSE_ERROR", str(e))
    sig = _confirm_task_signature(tree, source, command)
    if sig is None:
        return (None, "PARSE_OK_NO_MATCH", (
            "verible parsed the file but no kTaskDeclaration named this command "
            "was found in its tree"))
    return (sig, "CONFIRMED", None)


# --- public entry points ------------------------------------------------------

def trace_command(command_name: str, env_dir, *, vip_prefixes: Optional[Sequence[str]] = None,
                   use_verible: bool = True, verible_bin: str = DEFAULT_VERIBLE_BIN) -> CommandTraceReport:
    """Trace one DE command name through TASK_MACRO -> UVM_BRIDGE -> VIP_API ->
    CHECKER by real grep-based cross-reference over the files under
    `env_dir`. See module docstring for the bound this stays inside."""
    env_path = Path(env_dir)
    cmd = (command_name or "").strip()

    if not cmd:
        return CommandTraceReport(command_name=command_name or "", env_dir=str(env_path),
                                   status=STATUS_BLOCKED,
                                   reason="command_name is empty/whitespace-only")
    if not env_path.is_dir():
        return CommandTraceReport(command_name=cmd, env_dir=str(env_path), status=STATUS_BLOCKED,
                                   reason=f"env_dir {env_path} does not exist or is not a directory")

    files_text = _read_all(env_path)
    if not files_text:
        return CommandTraceReport(command_name=cmd, env_dir=str(env_path), status=STATUS_BLOCKED,
                                   reason=(f"no readable source files "
                                           f"({sorted(SOURCE_EXTENSIONS)}) found under {env_path}"))

    leg1, body_sources, handler_name = _resolve_task_macro(cmd, files_text, env_path)
    leg2 = _resolve_uvm_bridge(body_sources, files_text)
    leg3 = _resolve_vip_api(body_sources, vip_prefixes)
    leg4 = _resolve_checker(cmd, handler_name, files_text)
    legs = {LEG_TASK_MACRO: leg1, LEG_UVM_BRIDGE: leg2, LEG_VIP_API: leg3, LEG_CHECKER: leg4}
    status, reason = _overall_status(legs)

    if not use_verible:
        verible_signature, verible_status, verible_reason = None, "SKIPPED", "use_verible=False"
    elif leg1.status == LEG_NOT_FOUND:
        verible_signature, verible_status, verible_reason = None, "NOT_ATTEMPTED", (
            "task/macro leg was not resolved; nothing to confirm")
    else:
        verible_signature, verible_status, verible_reason = _enrich_with_verible(
            leg1, files_text, cmd, verible_bin)

    return CommandTraceReport(
        command_name=cmd, env_dir=str(env_path), status=status, reason=reason, legs=legs,
        verible_status=verible_status, verible_reason=verible_reason,
        verible_signature=verible_signature, files_scanned=len(files_text))


def trace_commands(command_names: Sequence[str], env_dir, *,
                    vip_prefixes: Optional[Sequence[str]] = None, use_verible: bool = True,
                    verible_bin: str = DEFAULT_VERIBLE_BIN) -> List[CommandTraceReport]:
    if not command_names:
        raise CommandTaskTraceError("command_names must be a non-empty sequence")
    return [trace_command(c, env_dir, vip_prefixes=vip_prefixes, use_verible=use_verible,
                           verible_bin=verible_bin) for c in command_names]


def overall_exit_code(reports: Sequence[CommandTraceReport]) -> int:
    if any(r.status == STATUS_BLOCKED for r in reports):
        return 2
    if any(r.status in (STATUS_TRACE_PARTIAL, STATUS_NOT_FOUND) for r in reports):
        return 1
    return 0


def format_report(report: CommandTraceReport) -> str:
    lines = [f"COMMAND {report.command_name!r} -> {report.status}"
             + (f" ({report.reason})" if report.reason else "")]
    if report.status == STATUS_BLOCKED:
        return "\n".join(lines)
    for leg_name in LEG_ORDER:
        leg = report.legs.get(leg_name)
        if leg is None:
            continue
        lines.append(f"  [{leg_name}] {leg.status}" + (f" -- {leg.reason}" if leg.reason else ""))
        for c in leg.citations:
            extra = f" ({c.detail})" if c.detail else ""
            lines.append(f"      {c.kind}: {c.file_path}:{c.line}: {c.snippet}{extra}")
    if report.verible_status != "NOT_ATTEMPTED":
        lines.append(f"  [verible_signature] {report.verible_status}"
                     + (f" -- {report.verible_reason}" if report.verible_reason else ""))
        if report.verible_signature:
            lines.append(f"      {report.verible_signature}")
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------------

def _parse_args(argv: Optional[Sequence[str]]):
    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.command_task_trace",
        description=("Trace a DE command name through task/macro -> UVM bridge -> "
                     "VIP API -> checker via real grep-based cross-reference over a "
                     "generated environment's own files."))
    parser.add_argument("--env-dir", required=True, help="generated environment directory")
    parser.add_argument("--command", action="append", dest="commands", required=True,
                         help="DE command name to trace; may be repeated")
    parser.add_argument("--vip-prefix", action="append", dest="vip_prefixes", default=None,
                         help="identifier prefix marking a VIP API reference (e.g. svt_); may be repeated")
    parser.add_argument("--no-verible", action="store_true",
                         help="skip the optional verible task-signature enrichment")
    parser.add_argument("--verible-bin", default=DEFAULT_VERIBLE_BIN)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    reports = trace_commands(args.commands, args.env_dir, vip_prefixes=args.vip_prefixes,
                              use_verible=not args.no_verible, verible_bin=args.verible_bin)
    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        for r in reports:
            print(format_report(r))
    return overall_exit_code(reports)


execute_verb = main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
