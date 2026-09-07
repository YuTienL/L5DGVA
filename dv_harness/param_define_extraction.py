"""dv_harness/param_define_extraction.py -- real RTL parameter and
preprocessor `` `define `` constant fact extraction (item id:
param_define_extraction, spec section 284, category design_intelligence):
every module's real declared parameters and every file's real object-like
`` `define `` constants, each reported with its own real file:line citation.

REUSE OVER REINVENT (checked before writing a line of this module, per
CLAUDE.md's own rule). A repo-wide grep for `param_define`/`ParamDefine`/
`define_extraction`/`ParameterFact`/`DefineFact` returned nothing executable.
Several similarly-shaped things exist and are deliberately NOT duplicated,
because none of them already covers this item:

- `dv_harness/verible_parser.py` already extracts, per module, the real
  parameter list (name/type-text/default-text) via its own real syntax-tree
  walk -- but until this task, `ParamInfo` carried no line number at all
  (confirmed by reading its dataclass and `_extract_params()` before writing
  a line of this module), so no consumer of it could cite a real file:line
  for one specific parameter without re-scanning the source text itself.
  This module does NOT re-implement that extraction: it makes one small,
  additive, backward-compatible change to `verible_parser.py` itself (a new
  `ParamInfo.line` field, appended last with a default so every existing
  positional-construction call site -- verified by grep,
  `dv_harness_tests/test_memory_buffer_arch_extraction.py`'s three -- stays
  valid) and then consumes that real field. Still exactly one SystemVerilog
  front end in this package.
- `dv_harness/env_manifest.py`'s `dut_facts.rtl` layer and
  `dv_harness/evidence_db.py`'s `rtl_parameters` table already carry
  parameters through as a flat traceability pass-through -- but neither adds
  a line number either (evidence_db's `rtl_parameters` table has no line
  column; confirmed by reading its `CREATE TABLE` before writing this
  module), and neither touches `` `define `` at all. Not duplicated or
  edited here; this module is a sibling reader of the same real parser.
- `dv_harness/memory_buffer_arch_extraction.py` (spec section 274) reads
  `ModuleInfo.parameters` too, but only as an INGREDIENT to resolve a memory
  array's depth/width -- it interprets a parameter's default as an integer
  bound, never lists "every parameter this module declares" as its own fact,
  and never touches `` `define ``. This module deliberately does NOT
  re-implement that numeric resolution (a parameter's `default_text` is
  reported here VERBATIM, exactly as declared -- resolving it to a number is
  section 274's own, already-real, job) and is not a rename of it.
- `dv_harness/command_task_trace.py` / `dv_harness/cpuread_byte_shift_
  checker.py` already regex-match `` `define NAME TARGET `` -- but ONLY to
  resolve one SPECIFIC command name's macro-redirect target for the command/
  task trace pipeline, never as a general "list every `` `define `` constant
  in this file" extraction. Not duplicated here; this module's define scan
  is general-purpose and does not know what a "command" is.

WHAT COUNTS AS A REAL PARAMETER FACT. Every `ParamInfo` verible_parser.py's
own real syntax-tree walk already produced for a module -- name, type text,
default text, all reused verbatim, never re-derived -- plus that same node's
own real `line` (see above). A module that declares no parameters honestly
reports `PARAMETERS_NOT_AVAILABLE`, never a fabricated parameter.

WHAT COUNTS AS A REAL `` `DEFINE `` CONSTANT FACT, AND WHY A LINE-SCAN RATHER
THAN `verible_parser.py`. `` `define `` is a PREPROCESSOR directive verible's
own syntax tree (a POST-preprocess-shaped grammar) does not model as a
first-class node -- confirmed by grep over this repo's own verible tree-shape
notes and `verible_parser.py`'s module docstring, which never mentions
`` `define `` at all. This mirrors the exact rationale
`interrupt_dma_clock_reset_extraction.py`'s own docstring already states for
why IT is a line-scan rather than a verible_parser.py consumer: a
preprocessor-level fact has no home in a post-lex syntax tree, so this module
reads the RAW FILE TEXT directly (never verible, never a second SystemVerilog
parser) and regex-matches lines of the shape
`` `define NAME[(params)] [VALUE] `` after blanking `//`/`/* */` comments and
`"..."` string literals (length- and newline-preserving, the identical
lexical-hygiene technique `design_architecture_ir.py`'s FSM scan already
uses, independently re-implemented here at a few lines rather than imported,
matching this codebase's own established convention of each extraction
module owning its own small bounded regex/literal helper --
`memory_buffer_arch_extraction.py`, `rtl_data_path_extraction.py`, and
`amba_command_txt_extension.py` each already do the same rather than share
one). A `` `define `` is classified into a small, closed, honest vocabulary,
never silently defaulted:

- `DEFINE_CONSTANT_FOUND` -- an object-like macro (no `(...)` parameter
  list) with real, non-empty replacement text on its own line. `value_text`
  is that text VERBATIM -- never resolved to a number, never evaluated.
- `DEFINE_FUNCTION_LIKE_SKIPPED` -- the macro name is immediately followed
  by `(...)` (a function-like macro). This is not a constant; its name and
  real citation are still reported, but `value_text` is `None` rather than
  a misleading "the parameter list is the value".
- `DEFINE_GUARD_NO_VALUE` -- an object-like macro with no replacement text
  at all on its own line (a bare include-guard/feature-flag style
  `` `define FOO ``). Honestly distinct from a constant with an empty string
  value, which this scan cannot produce (whitespace-only text is
  indistinguishable from "no value" at this lexical level and is reported
  this way rather than guessed to be an empty string).
- `DEFINE_MULTILINE_NOT_CAPTURED` -- the directive's own line ends in a
  backslash continuation. This scan does not join continuation lines (a
  correctness-sensitive re-implementation of the preprocessor's own line-
  splicing rule this module deliberately does not take on); the name and its
  real citation are still reported, `value_text` is `None` rather than a
  wrongly-truncated or wrongly-joined guess.

Deliberately bounded, and stated rather than implied closed. (1) No
`` `ifdef ``/`` `ifndef ``/`` `undef `` resolution of any kind: a `` `define ``
inside an `` `ifdef ``-guarded region, or one later `` `undef ``'d, is
reported exactly as textually present -- unconditionally, matching
`design_architecture_ir.py`'s and every sibling extraction module's own
disclosed scope. (2) No cross-file or same-file redefinition tracking: a
name defined more than once (or once per file, across multiple files) is
reported as multiple independent `DefineFact`s, each with its own real
citation, never merged or "last one wins"-deduplicated. (3) A parameter's
`default_text` is reported verbatim, never resolved to a number here (see
above -- that is `memory_buffer_arch_extraction.py`'s own, different,
already-real job for the one case it needs it: memory depth/width). (4) No
generate/`` `ifdef `` elaboration for parameters either, matching
verible_parser.py's own documented declaration-level scope. (5) It reads and
reports only -- no build, simulation, job, approval, or stage gate of any
kind is touched. Matching several other recent modules in this codebase
(`design_architecture_ir.py`, `memory_buffer_arch_extraction.py`),
`dv_harness/cli.py` and `dv_harness/gates.py` were not touched (both are
large files under concurrent edit pressure in this session) -- the front
door is the standalone `python -m dv_harness.param_define_extraction` verb
below.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import verible_parser
from .verible_parser import ModuleInfo

# ---- vocabulary, checked disjoint from a real verification verdict --------

PARAMS_FILE_PARSED = "PARAMS_FILE_PARSED"
PARAMS_FILE_UNAVAILABLE = "PARAMS_FILE_UNAVAILABLE"
PARAMS_FILE_PARSE_ERROR = "PARAMS_FILE_PARSE_ERROR"

PARAMETERS_FOUND = "PARAMETERS_FOUND"
PARAMETERS_NOT_AVAILABLE = "PARAMETERS_NOT_AVAILABLE"

PARAM_LINE_RESOLVED = "PARAM_LINE_RESOLVED"
PARAM_LINE_NOT_AVAILABLE = "PARAM_LINE_NOT_AVAILABLE"

DEFINES_FILE_READ = "DEFINES_FILE_READ"
DEFINES_FILE_UNAVAILABLE = "DEFINES_FILE_UNAVAILABLE"

DEFINES_FOUND = "DEFINES_FOUND"
DEFINES_NOT_AVAILABLE = "DEFINES_NOT_AVAILABLE"

DEFINE_CONSTANT_FOUND = "DEFINE_CONSTANT_FOUND"
DEFINE_FUNCTION_LIKE_SKIPPED = "DEFINE_FUNCTION_LIKE_SKIPPED"
DEFINE_GUARD_NO_VALUE = "DEFINE_GUARD_NO_VALUE"
DEFINE_MULTILINE_NOT_CAPTURED = "DEFINE_MULTILINE_NOT_CAPTURED"

_ALL_VOCAB = {
    PARAMS_FILE_PARSED, PARAMS_FILE_UNAVAILABLE, PARAMS_FILE_PARSE_ERROR,
    PARAMETERS_FOUND, PARAMETERS_NOT_AVAILABLE,
    PARAM_LINE_RESOLVED, PARAM_LINE_NOT_AVAILABLE,
    DEFINES_FILE_READ, DEFINES_FILE_UNAVAILABLE,
    DEFINES_FOUND, DEFINES_NOT_AVAILABLE,
    DEFINE_CONSTANT_FOUND, DEFINE_FUNCTION_LIKE_SKIPPED,
    DEFINE_GUARD_NO_VALUE, DEFINE_MULTILINE_NOT_CAPTURED,
}


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status vocabulary must never collide with a real
    stage-gate verdict (`dv_harness.models.Status`) -- the same guard several
    sibling domain-vocabulary modules in this repo already run on import."""
    from .models import Status
    collision = _ALL_VOCAB & {s.value for s in Status}
    if collision:
        raise AssertionError(
            "param_define_extraction vocabulary collides with "
            "dv_harness.models.Status: %r" % sorted(collision)
        )


assert_no_verification_verdict_vocabulary()

# ---- lexical hygiene for the `define scan (independently re-implemented at
# a few lines, matching this codebase's own established per-module
# convention -- see module docstring) ---------------------------------------

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LIT_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _blank_out(match: "re.Match") -> str:
    return "".join(ch if ch == "\n" else " " for ch in match.group(0))


def _strip_noise_preserve_offsets(text: str) -> str:
    """Blanks //, /* */ and "..." content with spaces (newlines kept), so
    every OFFSET/LINE computed against the result still lines up with the
    real source -- a `` `define `` spelled inside a comment or string
    literal is a real false-positive class for a line-scan and must never be
    reported as a real directive."""
    text = _BLOCK_COMMENT_RE.sub(_blank_out, text)
    text = _LINE_COMMENT_RE.sub(_blank_out, text)
    text = _STRING_LIT_RE.sub(_blank_out, text)
    return text


_DEFINE_RE = re.compile(
    r"(?m)^[ \t]*`define[ \t]+(?P<name>[A-Za-z_]\w*)(?P<params>\([^)\n]*\))?(?P<rest>[^\n]*)$"
)


# ---- typed result shapes ---------------------------------------------------

@dataclass
class ParameterFact:
    module_name: Optional[str]
    param_name: Optional[str]
    type_text: Optional[str]
    default_text: Optional[str]
    file_path: str
    line: Optional[int]
    line_status: str  # PARAM_LINE_RESOLVED / PARAM_LINE_NOT_AVAILABLE

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModuleParameterReport:
    module_name: Optional[str]
    file_path: str
    status: str  # PARAMETERS_FOUND / PARAMETERS_NOT_AVAILABLE
    parameters: list = field(default_factory=list)  # list[ParameterFact]

    def to_dict(self) -> dict:
        return {
            "module_name": self.module_name,
            "file_path": self.file_path,
            "status": self.status,
            "parameters": [p.to_dict() for p in self.parameters],
        }


@dataclass
class DefineFact:
    define_name: Optional[str]
    value_text: Optional[str]
    file_path: str
    line: int
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FileParamDefineReport:
    file_path: str
    param_status: str
    param_reason: Optional[str] = None
    verible_version: Optional[str] = None
    modules: list = field(default_factory=list)  # list[ModuleParameterReport]
    define_read_status: str = DEFINES_FILE_UNAVAILABLE
    define_read_reason: Optional[str] = None
    defines_status: str = DEFINES_NOT_AVAILABLE
    defines: list = field(default_factory=list)  # list[DefineFact]

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "param_status": self.param_status,
            "param_reason": self.param_reason,
            "verible_version": self.verible_version,
            "modules": [m.to_dict() for m in self.modules],
            "define_read_status": self.define_read_status,
            "define_read_reason": self.define_read_reason,
            "defines_status": self.defines_status,
            "defines": [d.to_dict() for d in self.defines],
        }


# ---- parameter extraction (verible_parser.py's real parse, plus its now-
# real per-param `line`) -----------------------------------------------------

def extract_module_parameters(module: ModuleInfo, file_path: str) -> ModuleParameterReport:
    """One `ParameterFact` per real declared parameter of `module`, each
    citing its own real `verible_parser.py`-derived line -- honestly
    `PARAMETERS_NOT_AVAILABLE` for a module that declares none."""
    facts = []
    for p in module.parameters:
        line = p.line
        line_status = PARAM_LINE_RESOLVED if line is not None else PARAM_LINE_NOT_AVAILABLE
        facts.append(ParameterFact(
            module_name=module.name,
            param_name=p.name,
            type_text=p.type_text,
            default_text=p.default_text,
            file_path=file_path,
            line=line,
            line_status=line_status,
        ))
    status = PARAMETERS_FOUND if facts else PARAMETERS_NOT_AVAILABLE
    return ModuleParameterReport(
        module_name=module.name, file_path=file_path, status=status, parameters=facts,
    )


def _extract_file_parameters(file_path: Any, verible_bin: str):
    """`(param_status, param_reason, verible_version, [ModuleParameterReport])`
    for one file -- a real verible failure is reported honestly, never
    silently treated as "no parameters were found"."""
    path_str = str(file_path)
    try:
        result = verible_parser.parse_file(file_path, verible_bin=verible_bin)
    except verible_parser.VeribleUnavailableError as e:
        return PARAMS_FILE_UNAVAILABLE, str(e), None, []
    except verible_parser.VeribleParseError as e:
        return PARAMS_FILE_PARSE_ERROR, str(e), None, []
    modules = [extract_module_parameters(m, path_str) for m in result.modules]
    return PARAMS_FILE_PARSED, None, result.verible_version, modules


# ---- `define constant extraction (raw text line-scan, no verible) --------

def extract_defines_from_text(text: str, file_path: str) -> list:
    """Every real object-like `` `define `` constant found in `text`, each
    with its own real 1-based `line`. `text` is scanned AFTER comments/
    string literals are blanked out (offset-preserving), so a `` `define ``
    spelled inside a comment or string is never reported as a real one."""
    clean = _strip_noise_preserve_offsets(text)
    out = []
    for m in _DEFINE_RE.finditer(clean):
        line = clean.count("\n", 0, m.start()) + 1
        name = m.group("name")
        if m.group("params") is not None:
            out.append(DefineFact(
                define_name=name, value_text=None, file_path=file_path,
                line=line, status=DEFINE_FUNCTION_LIKE_SKIPPED,
            ))
            continue
        rest = (m.group("rest") or "")
        rest_stripped = rest.strip()
        if rest_stripped.endswith("\\"):
            out.append(DefineFact(
                define_name=name, value_text=None, file_path=file_path,
                line=line, status=DEFINE_MULTILINE_NOT_CAPTURED,
            ))
            continue
        if not rest_stripped:
            out.append(DefineFact(
                define_name=name, value_text=None, file_path=file_path,
                line=line, status=DEFINE_GUARD_NO_VALUE,
            ))
            continue
        out.append(DefineFact(
            define_name=name, value_text=rest_stripped, file_path=file_path,
            line=line, status=DEFINE_CONSTANT_FOUND,
        ))
    return out


def _extract_file_defines(file_path: Any):
    """`(define_read_status, reason, defines_status, [DefineFact])` for one
    file, read directly (never via verible -- `` `define `` is a
    preprocessor artifact verible_parser.py's real syntax tree does not
    model; see module docstring). A file that cannot be read at all is
    reported honestly, never silently treated as "no defines"."""
    path_str = str(file_path)
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return DEFINES_FILE_UNAVAILABLE, str(e), DEFINES_NOT_AVAILABLE, []
    defines = extract_defines_from_text(text, path_str)
    defines_status = DEFINES_FOUND if defines else DEFINES_NOT_AVAILABLE
    return DEFINES_FILE_READ, None, defines_status, defines


# ---- combined per-file extraction ------------------------------------------

def extract_param_define_facts_for_file(
    file_path: Any, verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN
) -> FileParamDefineReport:
    """The real, combined per-file report: verible-parsed parameters (each
    with its real line) plus a raw-text `` `define `` constant scan (also
    each with its real line). The two halves fail independently -- a
    verible failure never suppresses the real `` `define `` scan (it does
    not need verible at all), and an unreadable file never suppresses the
    parameter half's own honest failure report."""
    path_str = str(file_path)
    param_status, param_reason, verible_version, modules = _extract_file_parameters(
        file_path, verible_bin
    )
    define_read_status, define_read_reason, defines_status, defines = _extract_file_defines(
        file_path
    )
    return FileParamDefineReport(
        file_path=path_str,
        param_status=param_status,
        param_reason=param_reason,
        verible_version=verible_version,
        modules=modules,
        define_read_status=define_read_status,
        define_read_reason=define_read_reason,
        defines_status=defines_status,
        defines=defines,
    )


def extract_param_define_facts(
    file_paths: list, verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN
) -> list:
    """One `FileParamDefineReport` per file. A bad file (missing binary,
    real syntax error, unreadable path) never sinks the batch -- every other
    file's own report is unaffected."""
    return [
        extract_param_define_facts_for_file(fp, verible_bin=verible_bin)
        for fp in file_paths
    ]


# ---- rendering (reuses the repo's one parameterized table renderer) ------

def render_param_define_markdown(file_reports: list) -> str:
    from .connectivity import render_markdown_table

    rows: list = []
    for fr in file_reports:
        if fr.param_status != PARAMS_FILE_PARSED:
            rows.append({
                "file": fr.file_path, "kind": "PARAMETER", "module": "", "name": "",
                "value": "", "citation": "", "status": fr.param_status,
            })
        else:
            for mr in fr.modules:
                if mr.status != PARAMETERS_FOUND:
                    rows.append({
                        "file": fr.file_path, "kind": "PARAMETER",
                        "module": mr.module_name or "", "name": "", "value": "",
                        "citation": "", "status": PARAMETERS_NOT_AVAILABLE,
                    })
                    continue
                for p in mr.parameters:
                    citation = f"{p.file_path}:{p.line}" if p.line is not None else "?"
                    rows.append({
                        "file": fr.file_path, "kind": "PARAMETER",
                        "module": p.module_name or "", "name": p.param_name or "",
                        "value": p.default_text if p.default_text is not None else "-",
                        "citation": citation, "status": p.line_status,
                    })
        if fr.define_read_status != DEFINES_FILE_READ:
            rows.append({
                "file": fr.file_path, "kind": "DEFINE", "module": "", "name": "",
                "value": "", "citation": "", "status": fr.define_read_status,
            })
        elif fr.defines_status != DEFINES_FOUND:
            rows.append({
                "file": fr.file_path, "kind": "DEFINE", "module": "", "name": "",
                "value": "", "citation": "", "status": DEFINES_NOT_AVAILABLE,
            })
        else:
            for d in fr.defines:
                rows.append({
                    "file": fr.file_path, "kind": "DEFINE", "module": "",
                    "name": d.define_name or "",
                    "value": d.value_text if d.value_text is not None else "-",
                    "citation": f"{d.file_path}:{d.line}", "status": d.status,
                })
    columns = [
        ("file", "File"), ("kind", "Kind"), ("module", "Module"), ("name", "Name"),
        ("value", "Value/Default"), ("citation", "Citation"), ("status", "Status"),
    ]
    return render_markdown_table(columns, rows, empty_note="(no RTL files supplied)")


# ---- CLI front door (standalone -- cli.py/gates.py not touched, see the
# module docstring's disclosed residual) -------------------------------------

def execute_verb(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.param_define_extraction",
        description="Extract real RTL parameter facts (via verible_parser.py, "
                    "each with its real file:line citation) and real "
                    "preprocessor `define constant facts (via a raw-text "
                    "line-scan) from RTL/SystemVerilog files.",
    )
    parser.add_argument("rtl_files", nargs="+", help="one or more .sv/.v files")
    parser.add_argument("--verible-bin", default=verible_parser.DEFAULT_VERIBLE_BIN)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports = extract_param_define_facts(args.rtl_files, verible_bin=args.verible_bin)
    any_param = any(
        mr.status == PARAMETERS_FOUND
        for fr in reports if fr.param_status == PARAMS_FILE_PARSED
        for mr in fr.modules
    )
    any_define = any(fr.defines_status == DEFINES_FOUND for fr in reports)
    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        print(render_param_define_markdown(reports))
    return 0 if (any_param or any_define) else 2


def main(argv: Optional[list] = None) -> None:
    sys.exit(execute_verb(argv))


if __name__ == "__main__":
    main()
