"""dv_harness/legal_param_combination_extraction.py -- real, cited proof (or
honest absence) of which COMBINATIONS of two-or-more RTL parameters are
legal/illegal, as stated by the RTL SOURCE TEXT itself (item id
legal_param_combination_extraction, CLAUDE.md "Open Item: Legal
Parameter-Combination Extraction from RTL", 2026-09-07, dut_discovery).

REUSE OVER REINVENT (checked before writing a line of this module, per
CLAUDE.md's own rule). A repo-wide grep for `legal_param_combination`/
`param_combination`/`parameter_combination`/"legal parameter combination"
matched nothing executable anywhere in `dv_harness/` and no CLAUDE.md
section named it either -- confirmed directly, not assumed. Two adjacent,
similarly-shaped modules were read in full and confirmed NOT to cover this
gap, and are deliberately not duplicated:

- `dv_harness/param_define_extraction.py` extracts each RTL parameter's own
  DECLARED default value and `` `define `` constant, ONE AT A TIME, via
  `verible_parser.py`. It has no notion of which COMBINATIONS of several
  parameters are jointly legal -- it never even reads two parameters
  together. This module reuses `param_define_extraction.py`'s real,
  already-tested parameter list INDIRECTLY: it takes each module's real
  `verible_parser.ParamInfo.name` list (via the SAME `verible_parser.py`
  front end, never a second parser) as the closed, real vocabulary of
  "things that are allowed to count as a parameter" a condition's
  identifiers are cross-checked against, so an ordinary signal or genvar
  name spelled inside an `if` condition is never mistaken for a tested
  parameter.
- `dv_harness/config_variant_coverage.py` generates a pairwise-covering
  test-CONFIGURATION plan over a CALLER-DECLARED dimension space -- that
  space's legal values are an INPUT the caller supplies, never derived from
  RTL. This module answers the opposite direction: given real RTL source,
  which parameter combinations does the SOURCE TEXT ITSELF prove legal or
  illegal. Deliberately NOT imported: nothing here builds a `ConfigSpace` or
  runs IPOG generation, and nothing in `config_variant_coverage.py` is
  touched.

WHAT THIS MODULE IS: a bounded, disclosed PARSER-LEVEL text scan (never a
second SystemVerilog parser, never verible's syntax tree for this part --
verible's tree already gives us the real per-module parameter NAMES via
`verible_parser.py`, reused verbatim; everything below scans the module's
own real SOURCE TEXT, sliced out via `verible_parser.node_span()` exactly
the way `design_architecture_ir.py`'s own FSM literal scan already slices a
module's text) for two explicit, structurally-recognizable construct
shapes that constrain legality across TWO OR MORE parameters together:

  (a) GENERATE_IF_COMBINATION_GUARD -- a `generate` block whose FIRST
      non-whitespace content (optionally through one `begin`) is an `if`
      (an `if`/`else if`/`else` chain), where the `if`/`else if` CONDITION
      references two or more of this module's own real declared parameter
      names. A branch whose body contains no `$error`/`$fatal` call is
      reported LEGAL_COMBINATION_PROVEN for that condition's tested
      parameters (the RTL generates real content for this combination); a
      branch whose body DOES contain `$error`/`$fatal` is reported
      ILLEGAL_COMBINATION_PROVEN (the RTL itself refuses to elaborate for
      this combination).
  (b) ELABORATION_ERROR_COMBINATION_GUARD -- an `initial` block whose FIRST
      non-whitespace content (optionally through one `begin`) is an `if`
      chain, scanned identically. This is the standalone elaboration-time
      guard shape (`initial if (WIDTH==64 && MODE!=2) $error(...);`), kept
      as a separately NAMED construct kind from (a) because a `generate`
      region and a plain `initial` region are different RTL constructs with
      different elaboration semantics, even though this scan's condition/
      body classification logic is shared between them (one real function,
      `_scan_if_chain()`, used by both -- not two copies).

EVIDENCE TRUTH RULE, made concrete for this module. The ONLY three
per-site verdicts this module ever emits are `LEGAL_COMBINATION_PROVEN`,
`ILLEGAL_COMBINATION_PROVEN`, and `NOT_AVAILABLE` -- exactly the vocabulary
this item was specified with. A module with NO recognizable construct of
either shape at all reports `NOT_AVAILABLE` at the MODULE level (never a
fabricated legal-combination fact synthesized from a parameter declaration
alone -- a parameter simply existing proves nothing about which of its
values combine legally with another parameter's values). A construct this
scan DID find the shape of but could not close/resolve cleanly -- an
unmatched `generate`/`endgenerate`, an unbalanced `if (...)` condition, an
unclosed `begin`/`end` or single-statement body -- reports `NOT_AVAILABLE`
for that ONE SITE, never a guessed LEGAL/ILLEGAL verdict; that site still
appears in the module's own `sites` list (so "we found something and could
not read it" stays a visible, distinct fact rather than disappearing into
"nothing was found at all" -- see `ModuleCombinationReport` docstring for
exactly how the module-level status distinguishes these two absence
shapes). A condition that references FEWER than two of this module's own
real declared parameters (a single-parameter guard, or a guard on plain
signals/genvars/`` `define `` constants with no parameter at all) is
OUT OF SCOPE for this module by definition and is not reported as a site at
all -- it is not this module's job to report every `if`, only ones that
constrain a COMBINATION of two-or-more parameters together.

THIS IS A DECLARATION-LEVEL / PARSER-LEVEL EXTRACTOR, NEVER AN ELABORATOR.
No `` `ifdef `` condition evaluation, no macro expansion, no generate-loop
unrolling, no live simulation, no formal proof, and no evaluation of the
condition expression's actual truth value for any parameter value --
`LEGAL_COMBINATION_PROVEN` means "the RTL's own source text takes this
branch's real content path for this combination", never "this module was
simulated/elaborated with these parameter values and it worked". A
condition spelled across an unusual continuation this scan's bounded
line/token walk does not anticipate (see boundary list below) can be
MISSED entirely -- this module never claims completeness, only that
whatever it DID report is a real, cited fact.

BOUNDARY, stated rather than implied closed.
  1. Both construct shapes require the qualifying `if` to be the FIRST
     non-whitespace token after `generate`/`initial` (optionally through
     exactly one intervening `begin`). A `generate`/`initial` block whose
     first real statement is something else (a comment -- already
     invisible, see below -- a declaration, an unrelated statement, THEN an
     if) is not recognized as a combination-guard by this scan; its `if`,
     if any, is simply never found, and no site is reported for it at all
     (this is a silent miss, not a NOT_AVAILABLE site, because this scan
     never even identifies a construct to try to close).
  2. Only ONE `if`/`else if`/`else` chain is scanned per anchor (per
     `generate` region, per `initial` block) -- a second, sibling if-chain
     later in the same region is not examined.
  3. A trailing bare `else` (no condition of its own) is never itself
     turned into a reported site, even when its body calls `$error`/
     `$fatal` -- naming WHICH combination that residual branch covers would
     require synthesizing the negation of every prior condition in the
     chain, which is elaboration-adjacent reasoning this parser-level scan
     deliberately does not take on (fabricating a "combination" no
     condition in the source text actually names is exactly what the
     Evidence Truth Rule forbids). Its PRIOR conditioned siblings (the real
     `if`/`else if` branches) are still reported normally.
  4. Comments (`//`, `/* */`) and string literals (`"..."`) are blanked to
     spaces (length/newline-preserving) before any regex or token scan
     runs -- the identical lexical-hygiene technique
     `design_architecture_ir.py`'s own FSM scan and
     `param_define_extraction.py`'s own `` `define `` scan already
     establish (independently re-implemented here at a few lines, matching
     this codebase's own established per-module convention rather than a
     shared helper). A construct spelled inside a comment or a
     `$display("...")` string is never mistaken for a real one.
  5. No cross-file constraint resolution: a combination guard that spans
     more than one file (an `` `include ``d generate body, a macro-defined
     condition) is invisible to this per-file scan.
  6. This module reads and reports only -- no build, simulation, job,
     approval, or stage gate of any kind is touched. Matching several other
     recent modules in this codebase, `dv_harness/cli.py`/`gates.py`/
     `dashboard.py` were not touched (all three are large files under
     concurrent edit pressure in this session) -- the front door is the
     standalone `python -m dv_harness.legal_param_combination_extraction`
     verb below.

WORST-WINS COMPOSITE (MANDATORY HOUSE RULE 4). `fold_combination_verdicts()`
folds a list of real site verdicts into ONE composite, never by averaging:
a single real `ILLEGAL_COMBINATION_PROVEN` outranks any number of clean
`LEGAL_COMBINATION_PROVEN` sites, and short of that a single real
`NOT_AVAILABLE` (an unresolved site -- a genuine unknown) still outranks any
number of clean `LEGAL_COMBINATION_PROVEN` sites. An empty site list folds
to `NOT_AVAILABLE` -- "no evidence" is never presented as "clean".
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

# ---- vocabulary, checked disjoint from a real verification verdict --------

COMBO_FILE_PARSED = "COMBO_FILE_PARSED"
COMBO_FILE_UNAVAILABLE = "COMBO_FILE_UNAVAILABLE"
COMBO_FILE_PARSE_ERROR = "COMBO_FILE_PARSE_ERROR"

COMBINATION_SITES_FOUND = "COMBINATION_SITES_FOUND"

LEGAL_COMBINATION_PROVEN = "LEGAL_COMBINATION_PROVEN"
ILLEGAL_COMBINATION_PROVEN = "ILLEGAL_COMBINATION_PROVEN"
NOT_AVAILABLE = "NOT_AVAILABLE"

GENERATE_IF_COMBINATION_GUARD = "GENERATE_IF_COMBINATION_GUARD"
ELABORATION_ERROR_COMBINATION_GUARD = "ELABORATION_ERROR_COMBINATION_GUARD"

BRANCH_IF = "IF"
BRANCH_ELSE_IF = "ELSE_IF"
BRANCH_UNRESOLVED = "UNRESOLVED"  # the whole if-chain/block could not be closed

_ALL_VOCAB = {
    COMBO_FILE_PARSED, COMBO_FILE_UNAVAILABLE, COMBO_FILE_PARSE_ERROR,
    COMBINATION_SITES_FOUND, LEGAL_COMBINATION_PROVEN,
    ILLEGAL_COMBINATION_PROVEN, NOT_AVAILABLE,
    GENERATE_IF_COMBINATION_GUARD, ELABORATION_ERROR_COMBINATION_GUARD,
    BRANCH_IF, BRANCH_ELSE_IF, BRANCH_UNRESOLVED,
}


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status vocabulary must never collide with a real
    stage-gate verdict (`dv_harness.models.Status`) -- the same guard
    `param_define_extraction.py` and several sibling domain-vocabulary
    modules in this repo already run on import."""
    from .models import Status
    collision = _ALL_VOCAB & {s.value for s in Status}
    if collision:
        raise AssertionError(
            "legal_param_combination_extraction vocabulary collides with "
            "dv_harness.models.Status: %r" % sorted(collision)
        )


assert_no_verification_verdict_vocabulary()

# ---- lexical hygiene (independently re-implemented at a few lines, matching
# this codebase's own established per-module convention -- see module
# docstring point 4) ----------------------------------------------------------

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LIT_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _blank_out(match: "re.Match") -> str:
    return "".join(ch if ch == "\n" else " " for ch in match.group(0))


def _strip_noise_preserve_offsets(text: str) -> str:
    """Blanks //, /* */ and "..." content with spaces (newlines kept), so
    every OFFSET/LINE computed against the result still lines up with the
    real source -- a combination-guard construct spelled inside a comment
    or a `$display` string is a real false-positive class for a text scan
    and must never be reported as a real one."""
    text = _BLOCK_COMMENT_RE.sub(_blank_out, text)
    text = _LINE_COMMENT_RE.sub(_blank_out, text)
    text = _STRING_LIT_RE.sub(_blank_out, text)
    return text


def _line_in_slice(base_line: int, slice_text: str, pos: int) -> int:
    return base_line + slice_text.count("\n", 0, pos)


# ---- typed result shapes ---------------------------------------------------

@dataclass
class CombinationSite:
    """One real, cited construct site. `condition_text` is the raw
    (noise-blanked-source) text between the `if`'s own parentheses, VERBATIM
    -- never resolved, never evaluated. `tested_params` is the sorted,
    de-duplicated set of this module's own REAL declared parameter names
    (per `verible_parser.ParamInfo.name`, never guessed) found as whole-word
    identifiers inside `condition_text`; a site is only ever emitted when
    this set has two-or-more members (see module docstring's scope note)."""
    module_name: Optional[str]
    file_path: str
    construct_kind: str  # GENERATE_IF_COMBINATION_GUARD / ELABORATION_ERROR_COMBINATION_GUARD
    branch_kind: str      # IF / ELSE_IF / UNRESOLVED
    condition_text: Optional[str]
    tested_params: list = field(default_factory=list)
    line: Optional[int] = None
    status: str = NOT_AVAILABLE
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModuleCombinationReport:
    """`status` is `COMBINATION_SITES_FOUND` whenever `sites` is non-empty
    -- INCLUDING when every entry in it is itself `NOT_AVAILABLE` (a
    construct was found and could not be resolved; see module docstring's
    Evidence Truth Rule paragraph). `status` is `NOT_AVAILABLE` only when
    `sites` is EMPTY -- this scan found no combination-guard construct of
    either recognized shape anywhere in this module's source text at all.
    These are two deliberately distinct, never-collapsed absence shapes."""
    module_name: Optional[str]
    file_path: str
    status: str  # COMBINATION_SITES_FOUND / NOT_AVAILABLE
    reason: Optional[str] = None
    sites: list = field(default_factory=list)  # list[CombinationSite]

    def to_dict(self) -> dict:
        return {
            "module_name": self.module_name,
            "file_path": self.file_path,
            "status": self.status,
            "reason": self.reason,
            "sites": [s.to_dict() for s in self.sites],
        }


@dataclass
class FileCombinationReport:
    file_path: str
    parse_status: str  # COMBO_FILE_PARSED / COMBO_FILE_UNAVAILABLE / COMBO_FILE_PARSE_ERROR
    parse_reason: Optional[str] = None
    verible_version: Optional[str] = None
    modules: list = field(default_factory=list)  # list[ModuleCombinationReport]

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "parse_status": self.parse_status,
            "parse_reason": self.parse_reason,
            "verible_version": self.verible_version,
            "modules": [m.to_dict() for m in self.modules],
        }


# ---- bounded token/paren/block scanning helpers ----------------------------

_IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*")
_GENERATE_TOKEN_RE = re.compile(r"\bgenerate\b|\bendgenerate\b")
_GENERATE_KW_RE = re.compile(r"\bgenerate\b")
_INITIAL_KW_RE = re.compile(r"\binitial\b")
_ERROR_FATAL_RE = re.compile(r"\$(?:error|fatal)\s*\(")


def _skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i].isspace():
        i += 1
    return i


def _match_word(text: str, i: int, word: str) -> Optional[int]:
    """If `text[i:]` starts with the exact keyword `word` at a real word
    boundary (not a prefix of a longer identifier, e.g. `ifdef` must never
    match as `if`), returns the index right after it; else None."""
    n = len(text)
    end = i + len(word)
    if text[i:end] != word:
        return None
    if end < n and (text[end].isalnum() or text[end] == "_"):
        return None
    return end


def _extract_parenthesized(text: str, open_idx: int):
    """`text[open_idx]` must be `(`. Depth-counts to find the matching `)`.
    Returns `(inner_text, index_after_close)`, or None if the parens never
    balanced before the text ran out -- an honest 'this scan could not
    close what it found', never a guessed condition."""
    if open_idx >= len(text) or text[open_idx] != "(":
        return None
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i], i + 1
        i += 1
    return None


_BEGIN_END_RE = re.compile(r"\bbegin\b|\bend\b")


def _extract_begin_end_body(text: str, begin_idx: int):
    """`text[begin_idx:]` must start with the already-matched `begin`
    keyword. Depth-counts nested `begin`/`end` pairs (a branch body may
    itself contain further nested blocks) to find THIS block's own matching
    `end`. Returns `(body_text, index_after_end)`, or None if unclosed."""
    depth = 0
    for m in _BEGIN_END_RE.finditer(text, begin_idx):
        if m.group() == "begin":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return text[begin_idx:m.end()], m.end()
    return None


def _extract_single_stmt_body(text: str, start_idx: int):
    """A body with no `begin`: scan to the next top-level `;` (paren-depth
    aware, so a `$error("msg", (a+b))`-style call's own semicolon-free
    interior never terminates the statement early). Returns
    `(body_text_incl_semicolon, index_after)`, or None if unclosed."""
    depth = 0
    i = start_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth <= 0:
            return text[start_idx:i + 1], i + 1
        i += 1
    return None


def _extract_branch_body(text: str, start_idx: int):
    i = _skip_ws(text, start_idx)
    if i >= len(text):
        return None
    b = _match_word(text, i, "begin")
    if b is not None:
        return _extract_begin_end_body(text, i)
    return _extract_single_stmt_body(text, i)


def _scan_if_chain(text: str, if_start: int):
    """Starting at one real `if` keyword's own index, extracts this
    `if`/`else if`/(trailing bare `else`) chain's own real branches.

    Returns a list of branch dicts `{"condition": str|None, "body": str,
    "start": int, "kind": "IF"|"ELSE_IF"|"ELSE"}`, or None if ANY step
    (the opening paren, its balancing, or a branch body) could not be
    resolved -- the whole chain is then an honest 'could not close what
    was found', never a partially-guessed chain."""
    branches = []
    cursor = if_start
    kind = BRANCH_IF
    while True:
        after_if = _match_word(text, cursor, "if")
        if after_if is None:
            return None
        j = _skip_ws(text, after_if)
        if j >= len(text) or text[j] != "(":
            return None
        paren = _extract_parenthesized(text, j)
        if paren is None:
            return None
        cond_text, after_paren = paren
        body = _extract_branch_body(text, after_paren)
        if body is None:
            return None
        body_text, after_body = body
        branches.append({
            "condition": cond_text.strip(), "body": body_text,
            "start": cursor, "kind": kind,
        })
        k = _skip_ws(text, after_body)
        after_else = _match_word(text, k, "else")
        if after_else is None:
            return branches
        k2 = _skip_ws(text, after_else)
        after_if2 = _match_word(text, k2, "if")
        if after_if2 is not None:
            cursor = k2
            kind = BRANCH_ELSE_IF
            continue
        # a trailing bare `else` -- its own body must still close cleanly
        # for the CHAIN to be considered resolved (an unclosed else body
        # means this whole construct could not be read), but per module
        # docstring point 3 it is never itself turned into a reported site.
        else_body = _extract_branch_body(text, k2)
        if else_body is None:
            return None
        else_body_text, _after_else_body = else_body
        branches.append({
            "condition": None, "body": else_body_text, "start": k, "kind": "ELSE",
        })
        return branches


def _tested_params(condition_text: str, declared: set) -> list:
    found = []
    for m in _IDENTIFIER_RE.finditer(condition_text):
        name = m.group()
        if name in declared and name not in found:
            found.append(name)
    return sorted(found)


def _first_if_after(text: str, start: int, limit: int) -> Optional[int]:
    """The index of an `if` keyword iff it is the FIRST non-whitespace
    token after `start` (optionally through exactly one `begin`), before
    `limit` -- see module docstring boundary point 1. Returns None
    (a silent miss, not a site) if the first real token is anything else."""
    i = _skip_ws(text, start)
    if i >= limit:
        return None
    b = _match_word(text, i, "begin")
    if b is not None:
        i = _skip_ws(text, b)
        if i >= limit:
            return None
    j = _match_word(text, i, "if")
    if j is not None:
        return i
    return None


def _iter_generate_blocks(text: str):
    """Non-overlapping `(generate_start, generate_kw_end, endgenerate_end)`
    spans, left to right. `endgenerate_end` is None when no matching
    `endgenerate` could be found before the text ran out -- an honest
    'could not close', never silently dropped; scanning stops at that point
    (a real generate block that never closes makes anything textually
    "after" it unreliable to scope)."""
    spans = []
    idx = 0
    n = len(text)
    while idx < n:
        gm = _GENERATE_KW_RE.search(text, idx)
        if gm is None:
            break
        depth = 0
        end_idx = None
        for m in _GENERATE_TOKEN_RE.finditer(text, gm.start()):
            if m.group() == "generate":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    end_idx = m.end()
                    break
        spans.append((gm.start(), gm.end(), end_idx))
        if end_idx is None:
            break
        idx = end_idx
    return spans


def _iter_initial_blocks(text: str):
    """Every `(initial_start, initial_kw_end)` occurrence -- unlike
    `generate`/`endgenerate`, a plain `initial` block has no distinguishing
    closing keyword of its own to depth-count (`_extract_branch_body()`
    below is what actually closes its `begin`/`end` or single statement)."""
    return [(m.start(), m.end()) for m in _INITIAL_KW_RE.finditer(text)]


def _classify_branch(body_text: str) -> str:
    return ILLEGAL_COMBINATION_PROVEN if _ERROR_FATAL_RE.search(body_text) else LEGAL_COMBINATION_PROVEN


def _emit_sites_from_chain(
    branches: list, declared: set, construct_kind: str,
    module_name: Optional[str], file_path: str, base_line: int, clean: str,
) -> list:
    out = []
    for b in branches:
        if b["condition"] is None:
            continue  # trailing bare else -- never its own site, see docstring point 3
        tested = _tested_params(b["condition"], declared)
        if len(tested) < 2:
            continue  # out of scope: not a two-or-more-parameter combination guard
        out.append(CombinationSite(
            module_name=module_name, file_path=file_path,
            construct_kind=construct_kind,
            branch_kind=BRANCH_IF if b["kind"] == BRANCH_IF else BRANCH_ELSE_IF,
            condition_text=b["condition"], tested_params=tested,
            line=_line_in_slice(base_line, clean, b["start"]),
            status=_classify_branch(b["body"]), reason=None,
        ))
    return out


def find_combination_sites(
    module_text: str, module_name: Optional[str], param_names: list, *,
    file_path: str = "", base_line: int = 1,
) -> list:
    """The real, bounded parser-level scan of ONE module's own source text
    for both construct shapes (see module docstring). `param_names` must be
    that SAME module's own real `verible_parser.ParamInfo.name` list (never
    re-derived here) -- the closed vocabulary a condition's identifiers are
    cross-checked against. Never raises for malformed input text: an
    unclosed construct becomes its own `NOT_AVAILABLE` site (see
    `ModuleCombinationReport` docstring), never a guessed verdict."""
    clean = _strip_noise_preserve_offsets(module_text)
    declared = set(n for n in param_names if n)
    sites: list = []

    for gen_start, gen_kw_end, endgen_end in _iter_generate_blocks(clean):
        if endgen_end is None:
            sites.append(CombinationSite(
                module_name=module_name, file_path=file_path,
                construct_kind=GENERATE_IF_COMBINATION_GUARD,
                branch_kind=BRANCH_UNRESOLVED, condition_text=None, tested_params=[],
                line=_line_in_slice(base_line, clean, gen_start),
                status=NOT_AVAILABLE,
                reason="found 'generate' with no matching 'endgenerate' before the module "
                       "text ended -- this scan could not close the block it found",
            ))
            continue
        if_start = _first_if_after(clean, gen_kw_end, endgen_end)
        if if_start is None:
            continue  # not a combination-guard shape -- see boundary point 1
        branches = _scan_if_chain(clean, if_start)
        if branches is None:
            sites.append(CombinationSite(
                module_name=module_name, file_path=file_path,
                construct_kind=GENERATE_IF_COMBINATION_GUARD,
                branch_kind=BRANCH_UNRESOLVED, condition_text=None, tested_params=[],
                line=_line_in_slice(base_line, clean, if_start),
                status=NOT_AVAILABLE,
                reason="found 'generate if (...)' but this scan could not close its "
                       "condition parentheses or one of its branch bodies (unbalanced "
                       "parens, or an unclosed begin/end or statement)",
            ))
            continue
        sites.extend(_emit_sites_from_chain(
            branches, declared, GENERATE_IF_COMBINATION_GUARD,
            module_name, file_path, base_line, clean,
        ))

    for init_start, init_kw_end in _iter_initial_blocks(clean):
        if_start = _first_if_after(clean, init_kw_end, len(clean))
        if if_start is None:
            continue  # not a combination-guard shape -- see boundary point 1
        branches = _scan_if_chain(clean, if_start)
        if branches is None:
            sites.append(CombinationSite(
                module_name=module_name, file_path=file_path,
                construct_kind=ELABORATION_ERROR_COMBINATION_GUARD,
                branch_kind=BRANCH_UNRESOLVED, condition_text=None, tested_params=[],
                line=_line_in_slice(base_line, clean, if_start),
                status=NOT_AVAILABLE,
                reason="found 'initial if (...)' but this scan could not close its "
                       "condition parentheses or one of its branch bodies (unbalanced "
                       "parens, or an unclosed begin/end or statement)",
            ))
            continue
        sites.extend(_emit_sites_from_chain(
            branches, declared, ELABORATION_ERROR_COMBINATION_GUARD,
            module_name, file_path, base_line, clean,
        ))

    return sites


# ---- worst-wins composite (MANDATORY HOUSE RULE 4) -------------------------

_SEVERITY_ORDER = {ILLEGAL_COMBINATION_PROVEN: 2, NOT_AVAILABLE: 1, LEGAL_COMBINATION_PROVEN: 0}


def fold_combination_verdicts(statuses) -> str:
    """Worst-wins composite over a list of real site statuses -- NEVER
    averaged (MANDATORY HOUSE RULE 4): a single real
    `ILLEGAL_COMBINATION_PROVEN` outranks any number of clean
    `LEGAL_COMBINATION_PROVEN` sites; short of that a single real
    `NOT_AVAILABLE` (a genuine unresolved unknown) still outranks any
    number of clean sites. An empty input folds to `NOT_AVAILABLE` --
    'no evidence at all' is never presented as if it were a clean pass."""
    statuses = list(statuses)
    if not statuses:
        return NOT_AVAILABLE
    return max(statuses, key=lambda s: _SEVERITY_ORDER.get(s, 1))


# ---- per-file extraction (verible_parser.py's real parse + real module text
# span, mirroring design_architecture_ir.py's own parse_rtl_file() pattern of
# reusing verible_parser's public tree-walk aliases rather than re-parsing) --

def _parse_modules_with_text(file_path: Any, verible_bin: str) -> list:
    """`[(ModuleInfo, module_text_or_None, base_line_or_None), ...]` for one
    file -- the real verible-parsed `ModuleInfo` (parameters included) PLUS
    that same module's own real source-text slice, sliced via
    `verible_parser.node_span()` off the SAME `kModuleDeclaration` node
    `verible_parser.extract_modules()` itself already walked (never a second,
    divergent tree traversal -- see `design_architecture_ir.py`'s identical,
    already-established zip pattern). Raises `VeribleUnavailableError`/
    `VeribleParseError`/`OSError` -- never silently returns an empty result
    for a file that could not really be read/parsed."""
    path = Path(file_path)
    source = path.read_text(encoding="utf-8", newline="")
    tree = verible_parser.run_export_json(path, verible_bin=verible_bin)
    module_nodes = verible_parser.find_all_nonoverlapping(tree, "kModuleDeclaration")
    module_infos = verible_parser.extract_modules(tree, source)
    out = []
    for node, minfo in zip(module_nodes, module_infos):
        span = verible_parser.node_span(node)
        if span is None:
            out.append((minfo, None, None))
            continue
        out.append((minfo, source[span[0]:span[1]], source.count("\n", 0, span[0]) + 1))
    return out


def extract_combination_facts_for_file(
    file_path: Any, verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN,
) -> FileCombinationReport:
    """The real, combined per-file report: for every real verible-parsed
    module, its own real combination-guard site scan (see
    `find_combination_sites()`). A real verible failure (binary missing,
    genuine syntax error) or an unreadable file is reported honestly on
    `parse_status`, with an empty `modules` list -- never silently treated
    as 'this file has no combination guards'."""
    path_str = str(file_path)
    try:
        parsed = _parse_modules_with_text(file_path, verible_bin)
    except verible_parser.VeribleUnavailableError as e:
        return FileCombinationReport(
            file_path=path_str, parse_status=COMBO_FILE_UNAVAILABLE, parse_reason=str(e),
        )
    except verible_parser.VeribleParseError as e:
        return FileCombinationReport(
            file_path=path_str, parse_status=COMBO_FILE_PARSE_ERROR, parse_reason=str(e),
            verible_version=verible_parser.get_verible_version(verible_bin),
        )
    except OSError as e:
        return FileCombinationReport(
            file_path=path_str, parse_status=COMBO_FILE_UNAVAILABLE, parse_reason=str(e),
        )

    modules = []
    for minfo, module_text, base_line in parsed:
        if module_text is None:
            modules.append(ModuleCombinationReport(
                module_name=minfo.name, file_path=path_str, status=NOT_AVAILABLE,
                reason="could not determine this module's own source span", sites=[],
            ))
            continue
        param_names = [p.name for p in minfo.parameters]
        sites = find_combination_sites(
            module_text, minfo.name, param_names, file_path=path_str, base_line=base_line,
        )
        if sites:
            modules.append(ModuleCombinationReport(
                module_name=minfo.name, file_path=path_str,
                status=COMBINATION_SITES_FOUND, reason=None, sites=sites,
            ))
        else:
            modules.append(ModuleCombinationReport(
                module_name=minfo.name, file_path=path_str, status=NOT_AVAILABLE,
                reason="no generate-if or initial-if construct testing two or more of this "
                       "module's own declared parameters was found in this module's source "
                       "text (parser-level scan; see module docstring for its disclosed "
                       "construct-shape boundary)",
                sites=[],
            ))
    return FileCombinationReport(
        file_path=path_str, parse_status=COMBO_FILE_PARSED, parse_reason=None,
        verible_version=verible_parser.get_verible_version(verible_bin), modules=modules,
    )


def extract_combination_facts(
    file_paths: list, verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN,
) -> list:
    """One `FileCombinationReport` per file. A bad file (missing binary,
    real syntax error, unreadable path) never sinks the batch -- every
    other file's own report is unaffected."""
    return [extract_combination_facts_for_file(fp, verible_bin=verible_bin) for fp in file_paths]


# ---- rendering (reuses the repo's one parameterized table renderer) -------

def render_combination_markdown(file_reports: list) -> str:
    from .connectivity import render_markdown_table

    rows: list = []
    for fr in file_reports:
        if fr.parse_status != COMBO_FILE_PARSED:
            rows.append({
                "file": fr.file_path, "module": "", "construct": "", "condition": "",
                "tested_params": "", "citation": "", "status": fr.parse_status,
            })
            continue
        for mr in fr.modules:
            if mr.status != COMBINATION_SITES_FOUND:
                rows.append({
                    "file": fr.file_path, "module": mr.module_name or "", "construct": "",
                    "condition": "", "tested_params": "", "citation": "", "status": NOT_AVAILABLE,
                })
                continue
            for s in mr.sites:
                citation = f"{s.file_path}:{s.line}" if s.line is not None else "?"
                rows.append({
                    "file": fr.file_path, "module": s.module_name or "",
                    "construct": s.construct_kind,
                    "condition": s.condition_text if s.condition_text is not None else "-",
                    "tested_params": ",".join(s.tested_params),
                    "citation": citation, "status": s.status,
                })
    columns = [
        ("file", "File"), ("module", "Module"), ("construct", "Construct"),
        ("condition", "Condition"), ("tested_params", "Tested Params"),
        ("citation", "Citation"), ("status", "Status"),
    ]
    return render_markdown_table(columns, rows, empty_note="(no RTL files supplied)")


# ---- CLI front door (standalone -- cli.py/gates.py/dashboard.py not
# touched, see module docstring's disclosed residual) -----------------------

def execute_verb(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.legal_param_combination_extraction",
        description="Scan real RTL/SystemVerilog files for generate-if / "
                    "initial-if constructs that constrain the legality of "
                    "TWO OR MORE parameters together, reporting each real, "
                    "cited site as LEGAL_COMBINATION_PROVEN / "
                    "ILLEGAL_COMBINATION_PROVEN / NOT_AVAILABLE. "
                    "Parser-level only -- never elaborates, never evaluates.",
    )
    parser.add_argument("rtl_files", nargs="+", help="one or more .sv/.v files")
    parser.add_argument("--verible-bin", default=verible_parser.DEFAULT_VERIBLE_BIN)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports = extract_combination_facts(args.rtl_files, verible_bin=args.verible_bin)
    any_site = any(
        mr.status == COMBINATION_SITES_FOUND
        for fr in reports if fr.parse_status == COMBO_FILE_PARSED
        for mr in fr.modules
    )
    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        print(render_combination_markdown(reports))
    return 0 if any_site else 2


def main(argv: Optional[list] = None) -> None:
    sys.exit(execute_verb(argv))


if __name__ == "__main__":
    main()
