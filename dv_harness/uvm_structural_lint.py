"""dv_harness/uvm_structural_lint.py -- deterministic, pre-simulation
STRUCTURAL LINT of the UVM source this harness's own generator produces
(CLAUDE_L5_SPEC_TO_SYSTEM_UVM_TARGETED_HARDENING.md section 220 "UVM
STRUCTURAL LINT": "Prefer deterministic parser/lint evidence before LLM
reasoning. Structural lint runs before expensive simulation where possible.").

WHAT WAS ACTUALLY MISSING (re-verified by grep before this module was
written, not restated from an audit):

  - dv_harness/verible_parser.py parses RTL only -- its extraction is
    kModuleDeclaration/kPortDeclaration/kInstantiationBase shaped. Grepping
    the whole repo for `uvm_component_utils`/`uvm_object_utils` returned only
    GENERATOR EMIT sites (uvm_generator/generator.py, amba_fabric_generator.py,
    tools/observability/generate_observability_plan.py) -- nothing that READS
    a generated .sv back and checks the macro is there.
  - dv_harness/uvm_generator/bind_verification_lint.py lints elaboration/
    simulation REPORT TEXT (log lines), not UVM source.
  - So nothing in this repo ever parsed generated UVM code. A generated
    environment's first structural feedback was a VCS compile -- i.e. the
    expensive path section 220 exists to run in front of.

HOW IT PARSES. It reuses the REAL verible front end this repo already has --
`verible_parser.run_export_json()` plus that module's now-public tree-walk
helpers (`walk_tree`/`find_all_nonoverlapping`/`node_text`/...) -- rather than
hand-rolling a second SystemVerilog parser. Confirmed live against this
machine's verible (v0.0-4150-gfe58e708) that class-based UVM source produces
the nodes these checks need: kClassDeclaration/kClassHeader/kExtendsList,
kClassItems, kMacroCall(MacroCallId + kMacroArgList), kFunctionDeclaration/
kFunctionHeader (return kDataType, name kUnqualifiedId, kPortList), kTaskDeclaration/
kTaskHeader, kDataDeclaration member declarations, and kFunctionCall
(kReferenceCallBase = callee kReference + kParenGroup = kArgumentList). Every
call site's BOUNDARY comes from verible, never from a regex over raw file
text; only the callee's already-isolated identifier path (e.g.
`uvm_config_db#(T)::set`, `phase.raise_objection`, `env.mon.ap.connect`) is
matched as a string, because that string is the source slice of one parsed
kReference node.

WHAT IT CHECKS (the bounded, genuinely-checkable subset -- section 220 lists
twelve concerns; these five are the ones a per-file/per-environment parse can
decide without elaboration):

  FACTORY_REGISTRATION_*   every class whose base chain terminates in a UVM
                           component/object root carries the matching
                           `uvm_component_utils`/`uvm_object_utils` family
                           macro, naming ITSELF.
  PHASE_METHOD_*           a method named after a real UVM phase is declared
                           with that phase's real signature (void function vs.
                           task; exactly one uvm_phase argument).
  CONFIG_DB_*              every statically-resolvable uvm_config_db field key
                           `get`-ed somewhere is `set` somewhere, and vice versa.
  TLM_PORT_NEVER_CONNECTED a declared TLM `*_port` member is `.connect()`-ed
                           somewhere in the environment (exports/imps: appear
                           as a connect() ARGUMENT).
  OBJECTION_*              raise_objection/drop_objection balance per method,
                           reconciled per class.

HONEST LIMITS, stated rather than implied closed:

  - This is a PARSER-level check, not an elaborator. Generate/`ifdef
    conditions are not evaluated, parameter values are not resolved, and a
    class extending a base this parse never saw (a VIP class such as
    `svt_usb_agent`, or a base in a file outside the analysed set) is reported
    as UNCLASSIFIED and deliberately NOT flagged -- an unknown base cannot
    prove a missing registration.
  - A config_db key built at run time (`$sformatf("usb%0d_if", p)`, a string
    variable) is not statically resolvable, and is reported as its own INFO
    finding rather than silently dropped from the matching.
  - BOTH config_db findings are WARNING, never ERROR. Unlike the other four
    checks, an unmatched key is an absence this analysis cannot PROVE: the
    missing half may live in VIP code, in a project's own top test, or behind
    a run-time-built key. The ERROR level is reserved for defects provable
    from the analysed sources alone.
  - status is NOT_AVAILABLE, never PASS, when verible itself cannot be run.
    A lint that cannot parse must never report a clean environment.
"""
from __future__ import annotations

import bisect
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import verible_parser
from .verible_parser import (
    DEFAULT_VERIBLE_BIN,
    VeribleParseError,
    VeribleUnavailableError,
    direct_children_tagged,
    direct_child_tagged,
    find_all_nonoverlapping,
    find_first_tagged,
    first_leaf_text,
    node_span,
    node_text,
    walk_tree,
)

# --- UVM taxonomy -----------------------------------------------------------
# Base classes whose descendants MUST carry a component-family factory macro.
UVM_COMPONENT_ROOTS = frozenset({
    "uvm_component", "uvm_env", "uvm_agent", "uvm_test", "uvm_driver",
    "uvm_monitor", "uvm_scoreboard", "uvm_subscriber", "uvm_sequencer",
    "uvm_sequencer_base", "uvm_push_sequencer", "uvm_reg_predictor",
    "uvm_random_stimulus", "uvm_in_order_comparator",
    "uvm_algorithmic_comparator", "uvm_analysis_imp",
})
# Base classes whose descendants MUST carry an object-family factory macro.
UVM_OBJECT_ROOTS = frozenset({
    "uvm_object", "uvm_transaction", "uvm_sequence_item", "uvm_sequence",
    "uvm_sequence_base", "uvm_reg", "uvm_reg_block", "uvm_reg_field",
    "uvm_mem", "uvm_reg_adapter", "uvm_reg_item", "uvm_callback",
})

COMPONENT_UTILS_MACROS = frozenset({
    "uvm_component_utils", "uvm_component_utils_begin",
    "uvm_component_param_utils", "uvm_component_param_utils_begin",
})
OBJECT_UTILS_MACROS = frozenset({
    "uvm_object_utils", "uvm_object_utils_begin",
    "uvm_object_param_utils", "uvm_object_param_utils_begin",
})
_PARAM_UTILS_MACROS = frozenset({
    "uvm_component_param_utils", "uvm_component_param_utils_begin",
    "uvm_object_param_utils", "uvm_object_param_utils_begin",
})

# UVM phase methods that are `function void <name>(uvm_phase phase)`.
UVM_FUNCTION_PHASES = frozenset({
    "build_phase", "connect_phase", "end_of_elaboration_phase",
    "start_of_simulation_phase", "extract_phase", "check_phase",
    "report_phase", "final_phase",
})
# UVM phase methods that are `task <name>(uvm_phase phase)`.
UVM_TASK_PHASES = frozenset({
    "run_phase", "reset_phase", "configure_phase", "main_phase",
    "shutdown_phase", "pre_reset_phase", "post_reset_phase",
    "pre_configure_phase", "post_configure_phase", "pre_main_phase",
    "post_main_phase", "pre_shutdown_phase", "post_shutdown_phase",
})

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

_UVM_TLM_PORT_RE = re.compile(r"^uvm_[a-z0-9_]*_port$")
_UVM_TLM_TARGET_RE = re.compile(r"^uvm_[a-z0-9_]*_(export|imp)(_[a-zA-Z0-9_]+)?$")
_UVM_TLM_FIFO_RE = re.compile(r"^uvm_tlm_(analysis_)?fifo$")
_CONFIG_DB_CALL_RE = re.compile(
    r"^uvm_config_db\s*#\s*\((?P<type>.*)\)\s*::\s*(?P<op>set|get)$", re.DOTALL)
_STRING_LITERAL_RE = re.compile(r'^"(?P<body>[^"]*)"$')
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


# --- data model -------------------------------------------------------------

@dataclass
class LintFinding:
    rule: str
    severity: str
    file_path: str
    line: int
    subject: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "file_path": self.file_path,
            "line": self.line,
            "subject": self.subject,
            "message": self.message,
        }


@dataclass
class MethodArg:
    name: Optional[str]
    type_text: Optional[str]


@dataclass
class CallSite:
    """One parsed call. `callee` is the source slice of the call's own callee
    kReference node -- e.g. "phase.raise_objection", "uvm_config_db#(T)::get",
    "env.mon.ap.connect" -- never a regex hit on raw file text."""
    callee: str
    args: List[str]
    line: int
    file_path: str
    guarded_by_if: bool = False


@dataclass
class MethodInfo:
    name: Optional[str]
    kind: str                       # "function" | "task"
    return_type: Optional[str]      # functions only
    args: List[MethodArg] = field(default_factory=list)
    line: int = 0
    calls: List[CallSite] = field(default_factory=list)


@dataclass
class MemberInfo:
    name: Optional[str]
    type_text: Optional[str]
    type_base: Optional[str]        # leading identifier of type_text
    line: int = 0


@dataclass
class UvmClassInfo:
    name: Optional[str]
    base_name: Optional[str]
    is_virtual: bool
    file_path: str
    line: int
    factory_macros: List[Dict[str, Any]] = field(default_factory=list)
    methods: List[MethodInfo] = field(default_factory=list)
    members: List[MemberInfo] = field(default_factory=list)
    calls: List[CallSite] = field(default_factory=list)


@dataclass
class UvmFileInfo:
    file_path: str
    source_sha256: str
    classes: List[UvmClassInfo] = field(default_factory=list)


@dataclass
class UvmLintReport:
    status: str                     # PASS | FAIL | NOT_AVAILABLE
    reason: Optional[str] = None    # only for NOT_AVAILABLE
    verible_version: Optional[str] = None
    files: List[Dict[str, str]] = field(default_factory=list)
    classes_analyzed: int = 0
    unclassified_bases: List[Dict[str, str]] = field(default_factory=list)
    findings: List[LintFinding] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_INFO)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "verible_version": self.verible_version,
            "files": list(self.files),
            "classes_analyzed": self.classes_analyzed,
            "unclassified_bases": list(self.unclassified_bases),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "findings": [f.to_dict() for f in self.findings],
        }


# --- source/offset helpers --------------------------------------------------

def _line_starts(source: str) -> List[int]:
    starts = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _line_of(starts: Sequence[int], offset: Optional[int]) -> int:
    if offset is None:
        return 0
    return bisect.bisect_right(starts, offset)


def _collect_scoped(node: dict, tag: str, stop_tags: Iterable[str] = ()) -> List[dict]:
    """Every node with `tag` inside this subtree, WITHOUT descending into a
    nested `stop_tags` node (a class declared inside a class, a method whose
    body must not leak its own inner declarations into the enclosing scope).
    Same mis-scoping guard verible_parser._collect_in_module_body() applies for
    modules -- reused in shape, not copied wholesale, because the stop set here
    is a parameter rather than the single hardcoded kModuleDeclaration."""
    stop = set(stop_tags)
    out: List[dict] = []

    def _rec(n, is_root: bool):
        if not isinstance(n, dict):
            return
        t = n.get("tag")
        if not is_root and t in stop:
            return
        if t == tag and "children" in n:
            out.append(n)
            return
        for c in n.get("children", []) or []:
            _rec(c, False)

    _rec(node, True)
    return out


# --- call-site extraction ---------------------------------------------------

def _split_top_level_args(arg_list_node: Optional[dict], source: str) -> List[str]:
    """The argument expressions of one kParenGroup>kArgumentList, split at the
    list's OWN comma children (verible already separated them, so no
    paren/bracket balancing of raw text is needed here)."""
    if arg_list_node is None:
        return []
    out: List[str] = []
    for child in arg_list_node.get("children", []) or []:
        if not isinstance(child, dict):
            continue
        if child.get("tag") == ",":
            continue
        text = node_text(child, source)
        out.append(text.strip() if text else "")
    return out


def _extract_call(node: dict, source: str, file_path: str,
                  starts: Sequence[int], if_spans: Sequence[tuple]) -> Optional[CallSite]:
    """One kFunctionCall -> CallSite, or None when the node carries no
    argument list (a bare identifier reference, which verible also tags
    kFunctionCall -- e.g. `this`, `cfg` as an actual argument)."""
    base = direct_child_tagged(node, "kReferenceCallBase")
    container = base if base is not None else node
    ref = direct_child_tagged(container, "kReference")
    paren = direct_child_tagged(container, "kParenGroup")
    if ref is None or paren is None:
        return None
    callee = node_text(ref, source)
    if not callee:
        return None
    callee = " ".join(callee.split())
    arg_list = direct_child_tagged(paren, "kArgumentList")
    span = node_span(node)
    start = span[0] if span else None
    guarded = any(a <= (start or -1) < b for a, b in if_spans)
    return CallSite(
        callee=callee,
        args=_split_top_level_args(arg_list, source),
        line=_line_of(starts, start),
        file_path=file_path,
        guarded_by_if=guarded,
    )


def _extract_calls(scope_node: dict, source: str, file_path: str,
                   starts: Sequence[int], if_spans: Sequence[tuple]) -> List[CallSite]:
    """Every call in this subtree. A full walk (not `find_all_nonoverlapping`)
    is deliberate: a call that MATTERS to these checks is routinely nested
    inside another expression -- `if(!uvm_config_db#(T)::get(...))` is the
    generator's own idiom -- so stopping at the outermost call would drop
    exactly the sites this lint exists to see. Nested type-parameter noise
    (the `pcie_config` in `uvm_config_db#(pcie_config)::get`) is filtered out
    downstream by callee matching, never by guessing here."""
    out: List[CallSite] = []
    for n in walk_tree(scope_node):
        if n.get("tag") != "kFunctionCall":
            continue
        call = _extract_call(n, source, file_path, starts, if_spans)
        if call is not None:
            out.append(call)
    return out


# --- class/member/method extraction ----------------------------------------

def _macro_id(macro_node: dict) -> Optional[str]:
    for c in macro_node.get("children", []) or []:
        if isinstance(c, dict) and c.get("tag") == "MacroCallId":
            return (c.get("text") or "").lstrip("`")
    return None


def _macro_args(macro_node: dict, source: str) -> List[str]:
    paren = direct_child_tagged(macro_node, "kParenGroup")
    if paren is None:
        return []
    arg_list = direct_child_tagged(paren, "kMacroArgList")
    return _split_top_level_args(arg_list, source)


def _method_args(header: dict, source: str) -> List[MethodArg]:
    paren = direct_child_tagged(header, "kParenGroup")
    if paren is None:
        return []
    port_list = direct_child_tagged(paren, "kPortList")
    if port_list is None:
        return []
    out: List[MethodArg] = []
    for item in direct_children_tagged(port_list, "kPortItem"):
        holder = find_first_tagged(item, "kDataTypeImplicitBasicIdDimensions")
        if holder is None:
            out.append(MethodArg(name=None, type_text=node_text(item, source)))
            continue
        dt = direct_child_tagged(holder, "kDataType")
        name_node = direct_child_tagged(holder, "kUnqualifiedId")
        type_text = node_text(dt, source) if dt is not None else None
        out.append(MethodArg(
            name=first_leaf_text(name_node, "SymbolIdentifier") if name_node else None,
            type_text=" ".join(type_text.split()) if type_text else None,
        ))
    return out


def _extract_method(decl: dict, kind: str, source: str, file_path: str,
                    starts: Sequence[int], if_spans: Sequence[tuple]) -> MethodInfo:
    header_tag = "kFunctionHeader" if kind == "function" else "kTaskHeader"
    header = direct_child_tagged(decl, header_tag)
    name = None
    return_type = None
    args: List[MethodArg] = []
    if header is not None:
        name_node = direct_child_tagged(header, "kUnqualifiedId")
        name = first_leaf_text(name_node, "SymbolIdentifier") if name_node else None
        if kind == "function":
            dt = direct_child_tagged(header, "kDataType")
            rt = node_text(dt, source) if dt is not None else None
            return_type = " ".join(rt.split()) if rt else None
        args = _method_args(header, source)
    span = node_span(decl)
    return MethodInfo(
        name=name,
        kind=kind,
        return_type=return_type,
        args=args,
        line=_line_of(starts, span[0] if span else None),
        calls=_extract_calls(decl, source, file_path, starts, if_spans),
    )


def _extract_members(items_node: dict, source: str, starts: Sequence[int]) -> List[MemberInfo]:
    """Class-scope variable declarations. Deliberately excludes anything
    declared inside a method body: `_collect_scoped` stops at
    kFunctionDeclaration/kTaskDeclaration/kClassConstructor, so a local
    `pcie_base_vseq vseq;` inside run_phase is never mistaken for a class
    member (which would make a local handle look like an unconnected TLM
    port)."""
    out: List[MemberInfo] = []
    stop = ("kFunctionDeclaration", "kTaskDeclaration", "kClassConstructor",
            "kClassDeclaration")
    for decl in _collect_scoped(items_node, "kDataDeclaration", stop):
        base = find_first_tagged(decl, "kInstantiationBase")
        if base is None:
            continue
        inst_type = direct_child_tagged(base, "kInstantiationType")
        type_text = node_text(inst_type, source) if inst_type is not None else None
        type_text = " ".join(type_text.split()) if type_text else None
        type_base = None
        if type_text:
            m = _IDENT_RE.search(type_text)
            type_base = m.group(0) if m else None
        for holder_tag in ("kVariableDeclarationAssignment", "kRegisterVariable"):
            for var in find_all_nonoverlapping(base, holder_tag):
                name = first_leaf_text(var, "SymbolIdentifier")
                if not name:
                    continue
                span = node_span(var)
                out.append(MemberInfo(
                    name=name,
                    type_text=type_text,
                    type_base=type_base,
                    line=_line_of(starts, span[0] if span else None),
                ))
    return out


def _extract_class(class_node: dict, source: str, file_path: str,
                   starts: Sequence[int], if_spans: Sequence[tuple]) -> UvmClassInfo:
    header = direct_child_tagged(class_node, "kClassHeader")
    name = None
    base_name = None
    is_virtual = False
    if header is not None:
        for c in header.get("children", []) or []:
            if isinstance(c, dict) and c.get("tag") == "virtual":
                is_virtual = True
            if isinstance(c, dict) and c.get("tag") == "SymbolIdentifier" and name is None:
                name = c.get("text")
        extends = find_first_tagged(header, "kExtendsList")
        if extends is not None:
            base_name = first_leaf_text(extends, "SymbolIdentifier")
    items = direct_child_tagged(class_node, "kClassItems")
    span = node_span(class_node)
    info = UvmClassInfo(
        name=name,
        base_name=base_name,
        is_virtual=is_virtual,
        file_path=file_path,
        line=_line_of(starts, span[0] if span else None),
        calls=_extract_calls(class_node, source, file_path, starts, if_spans),
    )
    if items is None:
        return info
    stop = ("kClassDeclaration",)
    for macro in _collect_scoped(items, "kMacroCall", stop):
        mid = _macro_id(macro)
        if mid is None:
            continue
        if mid in COMPONENT_UTILS_MACROS or mid in OBJECT_UTILS_MACROS:
            mspan = node_span(macro)
            info.factory_macros.append({
                "macro": mid,
                "args": _macro_args(macro, source),
                "line": _line_of(starts, mspan[0] if mspan else None),
            })
    method_stop = ("kClassDeclaration",)
    for decl in _collect_scoped(items, "kFunctionDeclaration", method_stop):
        info.methods.append(_extract_method(decl, "function", source, file_path,
                                            starts, if_spans))
    for decl in _collect_scoped(items, "kTaskDeclaration", method_stop):
        info.methods.append(_extract_method(decl, "task", source, file_path,
                                            starts, if_spans))
    info.members = _extract_members(items, source, starts)
    return info


def parse_uvm_file(file_path, verible_bin: str = DEFAULT_VERIBLE_BIN) -> UvmFileInfo:
    """Parse ONE SystemVerilog file into the class-level structure these checks
    need. Raises VeribleUnavailableError / VeribleParseError exactly as
    verible_parser.parse_file() does -- a file that could not be parsed is
    never silently reported as having no classes."""
    path = Path(file_path)
    # newline="" for the same reason verible_parser.parse_file() uses it: the
    # tree's start/end are offsets into the file EXACTLY as it sits on disk,
    # so universal-newline translation would drift every slice after line 1.
    source = path.read_text(encoding="utf-8", newline="")
    tree = verible_parser.run_export_json(path, verible_bin=verible_bin)
    starts = _line_starts(source)
    if_spans = []
    for hdr in walk_tree(tree):
        if hdr.get("tag") == "kIfHeader" and "children" in hdr:
            sp = node_span(hdr)
            if sp:
                if_spans.append(sp)
    classes = [
        _extract_class(c, source, str(path), starts, if_spans)
        for c in find_all_nonoverlapping(tree, "kClassDeclaration")
    ]
    return UvmFileInfo(
        file_path=str(path),
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        classes=classes,
    )


# --- checks -----------------------------------------------------------------

def _classify_base(cls: UvmClassInfo, by_name: Dict[str, UvmClassInfo]) -> str:
    """COMPONENT / OBJECT / UNCLASSIFIED, following `extends` through classes
    present in the ANALYSED SET only. A chain that leaves the analysed set (a
    VIP base such as svt_usb_agent, or a base declared in a file the caller did
    not include) is UNCLASSIFIED -- an unknown base cannot prove a missing
    factory registration, so those classes are recorded and skipped rather than
    guessed at."""
    seen = set()
    cur: Optional[UvmClassInfo] = cls
    while cur is not None and cur.name not in seen:
        seen.add(cur.name)
        base = cur.base_name
        if base is None:
            return "UNCLASSIFIED"
        if base in UVM_COMPONENT_ROOTS:
            return "COMPONENT"
        if base in UVM_OBJECT_ROOTS:
            return "OBJECT"
        cur = by_name.get(base)
    return "UNCLASSIFIED"


def _check_factory_registration(cls: UvmClassInfo, kind: str) -> List[LintFinding]:
    findings: List[LintFinding] = []
    if cls.is_virtual:
        # An abstract base is legitimately unregistered: the factory cannot
        # construct it, and UVM's own uvm_object/uvm_component are the same shape.
        return findings
    expected = COMPONENT_UTILS_MACROS if kind == "COMPONENT" else OBJECT_UTILS_MACROS
    other = OBJECT_UTILS_MACROS if kind == "COMPONENT" else COMPONENT_UTILS_MACROS
    matching = [m for m in cls.factory_macros if m["macro"] in expected]
    wrong = [m for m in cls.factory_macros if m["macro"] in other]
    if not matching:
        if wrong:
            findings.append(LintFinding(
                rule="FACTORY_REGISTRATION_WRONG_KIND",
                severity=SEVERITY_ERROR,
                file_path=cls.file_path, line=wrong[0]["line"], subject=cls.name or "?",
                message=(f"class {cls.name} resolves to a UVM {kind.lower()} "
                         f"(base chain via {cls.base_name}) but is registered with "
                         f"`{wrong[0]['macro']}; the factory will not construct it "
                         f"through {kind.lower()} creation"),
            ))
        else:
            findings.append(LintFinding(
                rule="FACTORY_REGISTRATION_MISSING",
                severity=SEVERITY_ERROR,
                file_path=cls.file_path, line=cls.line, subject=cls.name or "?",
                message=(f"class {cls.name} extends {cls.base_name} (a UVM "
                         f"{kind.lower()}) but declares no "
                         f"`{'uvm_component_utils' if kind == 'COMPONENT' else 'uvm_object_utils'} "
                         f"registration; ::type_id::create() cannot build it"),
            ))
        return findings
    for m in matching:
        if m["macro"] in _PARAM_UTILS_MACROS:
            # A parameterized registration's argument is the full specialization
            # (`my_seq#(T)`); comparing it to the bare class name would be a
            # false positive, so only the leading identifier is compared.
            declared = _IDENT_RE.search(m["args"][0]) if m["args"] else None
            declared_name = declared.group(0) if declared else None
        else:
            declared_name = m["args"][0].strip() if m["args"] else None
        if declared_name and cls.name and declared_name != cls.name:
            findings.append(LintFinding(
                rule="FACTORY_REGISTRATION_NAME_MISMATCH",
                severity=SEVERITY_ERROR,
                file_path=cls.file_path, line=m["line"], subject=cls.name,
                message=(f"class {cls.name} registers `{m['macro']}({declared_name}) "
                         f"-- the macro names a different type, so the factory "
                         f"override/creation key will not match this class"),
            ))
    return findings


def _check_phase_signatures(cls: UvmClassInfo) -> List[LintFinding]:
    findings: List[LintFinding] = []
    for meth in cls.methods:
        name = meth.name
        if name is None:
            continue
        is_func_phase = name in UVM_FUNCTION_PHASES
        is_task_phase = name in UVM_TASK_PHASES
        if not (is_func_phase or is_task_phase):
            continue
        subject = f"{cls.name}.{name}"
        want_kind = "function" if is_func_phase else "task"
        if meth.kind != want_kind:
            findings.append(LintFinding(
                rule="PHASE_METHOD_WRONG_KIND",
                severity=SEVERITY_ERROR,
                file_path=cls.file_path, line=meth.line, subject=subject,
                message=(f"UVM phase {name} must be declared as a {want_kind}, "
                         f"not a {meth.kind}"),
            ))
        elif is_func_phase and (meth.return_type or "").strip() != "void":
            findings.append(LintFinding(
                rule="PHASE_METHOD_RETURN_TYPE_NOT_VOID",
                severity=SEVERITY_ERROR,
                file_path=cls.file_path, line=meth.line, subject=subject,
                message=(f"UVM phase {name} must be `function void {name}"
                         f"(uvm_phase phase)`; declared return type is "
                         f"{meth.return_type!r}"),
            ))
        if len(meth.args) != 1:
            findings.append(LintFinding(
                rule="PHASE_METHOD_ARG_COUNT",
                severity=SEVERITY_ERROR,
                file_path=cls.file_path, line=meth.line, subject=subject,
                message=(f"UVM phase {name} must take exactly one uvm_phase "
                         f"argument; found {len(meth.args)}"),
            ))
        else:
            arg_type = (meth.args[0].type_text or "").strip()
            if arg_type != "uvm_phase":
                findings.append(LintFinding(
                    rule="PHASE_METHOD_ARG_TYPE",
                    severity=SEVERITY_ERROR,
                    file_path=cls.file_path, line=meth.line, subject=subject,
                    message=(f"UVM phase {name}'s single argument must be of type "
                             f"uvm_phase; declared as {arg_type!r}"),
                ))
    return findings


def _config_db_sites(classes: Sequence[UvmClassInfo]):
    """Every uvm_config_db set/get call in the analysed set, split into the
    statically-resolvable field keys and the run-time-built ones."""
    sets: Dict[str, List[CallSite]] = {}
    gets: Dict[str, List[CallSite]] = {}
    unresolved: List[tuple] = []   # (op, CallSite)
    for cls in classes:
        calls = list(cls.calls)
        for meth in cls.methods:
            calls.extend(meth.calls)
        seen = set()
        for call in calls:
            key = (call.file_path, call.line, call.callee, tuple(call.args))
            if key in seen:
                continue
            seen.add(key)
            m = _CONFIG_DB_CALL_RE.match(call.callee)
            if not m:
                continue
            op = m.group("op")
            # uvm_config_db#(T)::set(cntxt, inst_name, field_name, value)
            # uvm_config_db#(T)::get(cntxt, inst_name, field_name, value)
            field_arg = call.args[2] if len(call.args) >= 3 else None
            lit = _STRING_LITERAL_RE.match(field_arg.strip()) if field_arg else None
            if lit is None:
                unresolved.append((op, call))
                continue
            (sets if op == "set" else gets).setdefault(lit.group("body"), []).append(call)
    return sets, gets, unresolved


def _check_config_db(classes: Sequence[UvmClassInfo]) -> List[LintFinding]:
    sets, gets, unresolved = _config_db_sites(classes)
    findings: List[LintFinding] = []
    unresolved_sets = [c for op, c in unresolved if op == "set"]
    for op, call in unresolved:
        findings.append(LintFinding(
            rule="CONFIG_DB_KEY_NOT_STATICALLY_RESOLVABLE",
            severity=SEVERITY_INFO,
            file_path=call.file_path, line=call.line, subject=call.callee,
            message=(f"uvm_config_db {op} field name is built at run time "
                     f"({(call.args[2] if len(call.args) >= 3 else '<missing>')}); "
                     f"this key is excluded from set/get matching"),
        ))
    for key, calls in sorted(gets.items()):
        if key in sets:
            continue
        for call in calls:
            # WARNING, never ERROR, and deliberately so: config_db matching is
            # the one check here that cannot be PROVEN closed by a parse of the
            # environment's own sources. A `set` may legitimately live outside
            # the analysed set (a project's own top test, VIP code, a plusarg-
            # driven path), the guarded `if(!...::get(...)) <fallback>` form is
            # UVM's own optional-configuration idiom, and a run-time-built key
            # this parse cannot read could supply it. Reporting an unprovable
            # absence at ERROR would make the lint's ERROR level untrustworthy
            # on exactly the real generated environments it exists for -- the
            # real usb_base_vseq's `device_address`/`configuration_value`
            # optional overrides are that case. Same reasoning as
            # CONFIG_DB_SET_WITHOUT_GET below; the two are symmetric.
            findings.append(LintFinding(
                rule="CONFIG_DB_GET_WITHOUT_SET",
                severity=SEVERITY_WARNING,
                file_path=call.file_path, line=call.line, subject=key,
                message=(f"uvm_config_db field {key!r} is read here but never set "
                         f"anywhere in the analysed environment"
                         + (" (guarded get with a fallback)" if call.guarded_by_if else "")
                         + (f"; {len(unresolved_sets)} run-time-built set key(s) "
                            f"were not statically resolvable" if unresolved_sets else "")),
            ))
    for key, calls in sorted(sets.items()):
        if key in gets:
            continue
        for call in calls:
            findings.append(LintFinding(
                rule="CONFIG_DB_SET_WITHOUT_GET",
                severity=SEVERITY_WARNING,
                file_path=call.file_path, line=call.line, subject=key,
                message=(f"uvm_config_db field {key!r} is set here but never read "
                         f"in the analysed environment (its consumer may be VIP "
                         f"code outside this set)"),
            ))
    return findings


def _connect_receivers_and_arguments(classes: Sequence[UvmClassInfo]):
    receivers: List[str] = []
    arguments: List[str] = []
    for cls in classes:
        calls = list(cls.calls)
        for meth in cls.methods:
            calls.extend(meth.calls)
        for call in calls:
            if not call.callee.endswith(".connect"):
                continue
            receivers.append(call.callee[: -len(".connect")])
            arguments.extend(call.args)
    return receivers, arguments


def _path_tail_matches(path_text: str, member: str) -> bool:
    """True when `member` is the LAST path element of `path_text`, ignoring any
    index expression -- `dma_env.master[p].monitor.item_observed_port` matches
    "item_observed_port", `xfer_sb[p]` matches "xfer_sb", and `ap_other` does
    not match "ap"."""
    tail = path_text.strip().rstrip()
    tail = re.sub(r"\s+", "", tail)
    tail = re.sub(r"\[[^\]]*\]\s*$", "", tail)
    last = tail.split(".")[-1]
    last = re.sub(r"\[[^\]]*\]$", "", last)
    return last == member


def _check_tlm_connections(classes: Sequence[UvmClassInfo]) -> List[LintFinding]:
    receivers, arguments = _connect_receivers_and_arguments(classes)
    findings: List[LintFinding] = []
    for cls in classes:
        for member in cls.members:
            base = member.type_base or ""
            name = member.name
            if not name:
                continue
            if _UVM_TLM_PORT_RE.match(base):
                if not any(_path_tail_matches(r, name) for r in receivers):
                    findings.append(LintFinding(
                        rule="TLM_PORT_NEVER_CONNECTED",
                        severity=SEVERITY_ERROR,
                        file_path=cls.file_path, line=member.line,
                        subject=f"{cls.name}.{name}",
                        message=(f"TLM port {name} ({member.type_text}) is declared "
                                 f"but .connect() is never called on it anywhere in "
                                 f"the analysed environment; nothing will receive "
                                 f"what it writes"),
                    ))
            elif _UVM_TLM_TARGET_RE.match(base) or _UVM_TLM_FIFO_RE.match(base):
                if not any(_path_tail_matches(a, name) for a in arguments):
                    findings.append(LintFinding(
                        rule="TLM_EXPORT_NEVER_CONNECTED",
                        severity=SEVERITY_WARNING,
                        file_path=cls.file_path, line=member.line,
                        subject=f"{cls.name}.{name}",
                        message=(f"TLM export/imp {name} ({member.type_text}) never "
                                 f"appears as a .connect() argument in the analysed "
                                 f"environment; it may be connected from code outside "
                                 f"this set"),
                    ))
    return findings


def _check_objections(cls: UvmClassInfo) -> List[LintFinding]:
    findings: List[LintFinding] = []
    per_method = []
    total_raise = total_drop = 0
    for meth in cls.methods:
        raises = sum(1 for c in meth.calls if c.callee.endswith(".raise_objection"))
        drops = sum(1 for c in meth.calls if c.callee.endswith(".drop_objection"))
        total_raise += raises
        total_drop += drops
        if raises or drops:
            per_method.append((meth, raises, drops))
    class_balanced = total_raise == total_drop
    for meth, raises, drops in per_method:
        if raises == drops:
            continue
        # A raise in one phase method paired with a drop in another (e.g.
        # pre_main_phase / post_main_phase) is legal UVM, so a class whose
        # TOTALS balance is a WARNING about a split pair, not an error.
        severity = SEVERITY_WARNING if class_balanced else SEVERITY_ERROR
        rule = ("OBJECTION_RAISE_DROP_SPLIT_ACROSS_METHODS" if class_balanced
                else "OBJECTION_RAISE_DROP_IMBALANCE")
        findings.append(LintFinding(
            rule=rule,
            severity=severity,
            file_path=cls.file_path, line=meth.line,
            subject=f"{cls.name}.{meth.name}",
            message=(f"{meth.name} raises {raises} objection(s) and drops {drops}; "
                     + ("the class totals balance, so the pair is split across "
                        "methods -- confirm that is intentional"
                        if class_balanced else
                        "an unbalanced objection either hangs the phase forever "
                        "or ends it early")),
        ))
    return findings


# --- entry points -----------------------------------------------------------

def _is_test_class(cls: UvmClassInfo, by_name: Dict[str, UvmClassInfo]) -> bool:
    seen = set()
    cur: Optional[UvmClassInfo] = cls
    while cur is not None and cur.name not in seen:
        seen.add(cur.name)
        if cur.base_name == "uvm_test":
            return True
        cur = by_name.get(cur.base_name or "")
    return False


def lint_uvm_sources(paths: Sequence, verible_bin: str = DEFAULT_VERIBLE_BIN) -> UvmLintReport:
    """Run every check over one explicit set of SystemVerilog files, which are
    analysed TOGETHER: config_db set/get matching, TLM connect matching and
    base-class resolution are all whole-environment properties that a per-file
    lint cannot decide."""
    report = UvmLintReport(status="PASS")
    files: List[UvmFileInfo] = []
    for p in paths:
        try:
            files.append(parse_uvm_file(p, verible_bin=verible_bin))
        except VeribleUnavailableError as exc:
            return UvmLintReport(
                status="NOT_AVAILABLE",
                reason=f"verible-verilog-syntax could not be run: {exc}",
            )
        except VeribleParseError as exc:
            # A `.svh` is an INCLUDE FRAGMENT by convention and is not required
            # to parse standalone -- the real bind_mechanism_generator.py emits
            # dv_uvm_hook.svh as top-module-scope text (`initial run_test();`
            # with no enclosing module), which verible correctly rejects as a
            # standalone compilation unit. Calling that an ERROR would report a
            # defect that is not one. It is still surfaced, at WARNING, because
            # the file's contents really were left out of the analysis and that
            # narrows what a PASS covers. A `.sv` IS a compilation unit, so a
            # parse failure there is a real defect.
            is_fragment = Path(p).suffix.lower() == ".svh"
            report.findings.append(LintFinding(
                rule=("SOURCE_NOT_STANDALONE_PARSEABLE" if is_fragment
                      else "SOURCE_PARSE_ERROR"),
                severity=(SEVERITY_WARNING if is_fragment else SEVERITY_ERROR),
                file_path=str(p), line=(exc.errors[0].get("line", 0) if exc.errors else 0),
                subject=Path(p).name,
                message=(
                    (f"include fragment did not parse as a standalone compilation "
                     f"unit and was NOT analysed by this lint: {exc}")
                    if is_fragment else
                    f"verible reported syntax error(s): {exc}"),
            ))
    report.verible_version = verible_parser.get_verible_version(verible_bin)
    report.files = [{"file_path": f.file_path, "source_sha256": f.source_sha256}
                    for f in files]
    classes = [c for f in files for c in f.classes]
    report.classes_analyzed = len(classes)
    by_name = {c.name: c for c in classes if c.name}

    for cls in classes:
        kind = _classify_base(cls, by_name)
        if kind == "UNCLASSIFIED":
            report.unclassified_bases.append({
                "class": cls.name or "?",
                "base": cls.base_name or "<none>",
                "file_path": cls.file_path,
            })
        else:
            report.findings.extend(_check_factory_registration(cls, kind))
        report.findings.extend(_check_phase_signatures(cls))
        report.findings.extend(_check_objections(cls))
        if _is_test_class(cls, by_name):
            for meth in cls.methods:
                if meth.name != "run_phase":
                    continue
                if not any(c.callee.endswith(".raise_objection") for c in meth.calls):
                    report.findings.append(LintFinding(
                        rule="OBJECTION_NEVER_RAISED_IN_TEST_RUN_PHASE",
                        severity=SEVERITY_WARNING,
                        file_path=cls.file_path, line=meth.line,
                        subject=f"{cls.name}.run_phase",
                        message=("a uvm_test run_phase that never raises an "
                                 "objection returns immediately; the stimulus it "
                                 "starts may never run to completion"),
                    ))

    report.findings.extend(_check_config_db(classes))
    report.findings.extend(_check_tlm_connections(classes))
    report.findings.sort(key=lambda f: (f.file_path, f.line, f.rule))
    report.status = "FAIL" if report.error_count else "PASS"
    return report


def discover_uvm_sources(env_dir) -> List[Path]:
    """Every .sv/.svh under a generated environment directory, in a stable
    sorted order so a report regenerated from unchanged inputs is identical."""
    root = Path(env_dir)
    return sorted(
        [p for p in root.rglob("*.sv") if p.is_file()]
        + [p for p in root.rglob("*.svh") if p.is_file()],
        key=lambda p: str(p).replace("\\", "/"),
    )


def lint_uvm_environment(env_dir, verible_bin: str = DEFAULT_VERIBLE_BIN) -> UvmLintReport:
    """Lint a whole generated environment directory. An empty directory is
    reported NOT_AVAILABLE rather than PASS -- "nothing to check" is not
    evidence that the environment is structurally sound."""
    sources = discover_uvm_sources(env_dir)
    if not sources:
        return UvmLintReport(
            status="NOT_AVAILABLE",
            reason=f"no .sv/.svh source files found under {env_dir}",
        )
    return lint_uvm_sources(sources, verible_bin=verible_bin)


def format_report(report: UvmLintReport) -> str:
    """Human-readable rendering for the CLI verb and the generator's own
    post-generation summary line."""
    lines = [f"UVM structural lint: {report.status}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    if report.status != "NOT_AVAILABLE":
        lines.append(f"  files={len(report.files)} classes={report.classes_analyzed} "
                     f"errors={report.error_count} warnings={report.warning_count} "
                     f"info={report.info_count}")
        if report.unclassified_bases:
            lines.append(f"  unclassified base classes (skipped, not flagged): "
                         + ", ".join(f"{u['class']} extends {u['base']}"
                                     for u in report.unclassified_bases))
    for f in report.findings:
        lines.append(f"  [{f.severity}] {f.rule} {f.file_path}:{f.line} "
                     f"({f.subject}): {f.message}")
    return "\n".join(lines)
