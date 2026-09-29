"""dv_harness/rtl_control_flow_extraction.py -- bounded, disclosed-scope
control-flow / combinational-vs-sequential logic-intent extraction over
always-block bodies.

THE GAP THIS CLOSES
--------------------
`dv_harness/verible_parser.py` is explicitly declaration-level only (its own
docstring: "Signals declared inside a procedural block ... are deliberately
NOT surfaced" -- and it never exposes an always block's own sensitivity list
or body text at all, only that the block exists somewhere inside the source
text it slices for other purposes). `dv_harness/design_architecture_ir.py`
adds exactly ONE procedural-content extraction on top of that: a best-effort
literal scan for `always @(posedge ...)` blocks that contain a `case`
statement, scoped narrowly to FSM-candidate detection (state register name,
states, transitions -- see that module's own `extract_fsm_candidates()`).
Nothing in this repo extracts the WIDER, more basic control-flow/logic-
intent fact set a design reviewer or a downstream generator needs about an
always block that is not trying to be (or is not recognisably) an FSM: is
this block combinational or sequential (clocked)? does it contain an
if/else-if priority chain, and does that chain terminate with an `else`
(or a `case` with a `default`)? does a combinational block's own missing
`else`/`default` look, structurally, like it risks latch inference?

THIS MODULE
-----------
Extends `design_architecture_ir.py`'s own FSM-literal-scan PATTERN --
comment/string blanking for lexical hygiene (its `_strip_noise_preserve_
offsets`), depth-counted `case`/`endcase` matching (its `_CASE_OPEN_RE` /
`_find_case_block`), one-always-block-at-a-time bounded windows, and an
honest, closed status vocabulary -- to the wider always-block family
(`always`, `always_ff`, `always_comb`, `always_latch`) and to CONTROL-FLOW
SHAPE rather than FSM state-machine shape specifically. Those four helpers
are imported and reused verbatim, never re-implemented; this module never
re-derives design_architecture_ir.py's own FSM state/transition extraction
-- a module's FSM candidates stay that module's own job. This module adds
one genuinely new piece of scanning machinery design_architecture_ir.py
does not have at all: a depth-tracked if/else-if/else CHAIN walk (see
`_scan_control_tokens()` / `_extract_if_chain()`), because an FSM's own
`case` block never needed one.

WHAT IT REPORTS, PER ALWAYS BLOCK
----------------------------------
  * `block_kind`: `SEQUENTIAL` (a real clock-edge sensitivity -- an
    `always_ff` keyword, or a literal `posedge`/`negedge` in a plain
    `always`'s own sensitivity list -- is present), `COMBINATIONAL`
    (`always_comb`, or a plain `always` with a `@*`/`@(*)` sensitivity, or a
    plain `always` whose explicit signal-name sensitivity list contains no
    edge keyword), `LATCH_EXPLICIT` (the `always_latch` keyword itself), or
    `UNCLASSIFIED_SENSITIVITY` (no `@(...)`/`@*` clause this scan's fixed
    patterns can find at all after a plain `always` keyword -- never
    guessed).
  * `if_chain`: whether a top-level if/else-if chain was found in this
    scan's own bounded window, its branch count, and whether it ends in a
    terminal `else` -- via a depth counter over `begin`/`end`/`case.../
    endcase` tokens that starts at 0 at the always block's own opening and
    treats the FIRST `if` this scan finds as defining the chain's own
    nesting depth; only `else if`/`else` tokens later found at that SAME
    depth are treated as continuing that chain (see boundary notes below).
  * `case_shape`: whether a top-level `case`/`casex`/`casez` was found (via
    design_architecture_ir.py's own `_CASE_OPEN_RE`/`_find_case_block`,
    reused unchanged) and whether it carries a `default` item -- this module
    never re-resolves the case-key against a declared register the way
    design_architecture_ir.py's FSM scan does; it only asks whether one
    exists and whether it looks complete.
  * `findings`: zero or more named, cited structural findings --
    `LATCH_INFERENCE_RISK_CANDIDATE` (a `COMBINATIONAL` block whose own
    if-chain lacks a terminal `else`, or whose own case lacks a `default`)
    and `PRIORITY_STRUCTURE_NO_TERMINAL_ELSE` (a `SEQUENTIAL` block's own
    if-chain with no terminal `else` -- informational, not a risk: a
    clocked register legitimately retains its value on the untaken path).
    Never a "this WILL infer a latch" claim: a literal scan proves a
    STRUCTURAL absence (no terminal else/default this scan could find), it
    never proves no OTHER assignment elsewhere in the block covers the
    signal on every path -- the finding name says "candidate", not
    "confirmed", and every finding's own `reason` text says so again.

BOUNDARY, stated rather than implied closed
--------------------------------------------
  * This is a literal/regex scan over SOURCE TEXT, not a second SystemVerilog
    parser and not an elaborator: no expression is evaluated, no `generate`/
    `` `ifdef `` condition is resolved, and no data-flow/assignment-coverage
    proof is attempted (see the LATCH_INFERENCE_RISK_CANDIDATE finding's own
    disclosed limit above).
  * Only the FIRST if/else-if/else chain and the FIRST top-level `case` this
    scan finds in one always block's own bounded window are examined -- a
    second, sibling if-chain or case in the same always block is not
    examined, mirroring design_architecture_ir.py's own "only the first
    case/casex/casez statement... is scanned" bound.
  * Chain continuation is judged purely from a `begin`/`end`/`case.../
    endcase` TOKEN-COUNT depth, never from real brace/statement-block
    parsing -- an unusual construct this depth counter cannot represent
    correctly (e.g. a `begin`/`end` pair spanning a macro expansion this
    scan cannot see through) can under- or over-extend a chain. This is the
    same class of honest limitation `design_architecture_ir.py`'s own
    case/endcase depth counter already carries for its narrower job.
  * `//` and `/* */` comments and `"..."` string literals inside the scanned
    module text are blanked out before any regex runs -- reusing
    design_architecture_ir.py's own `_strip_noise_preserve_offsets()`
    unchanged, for the identical reason that module's docstring gives.
  * A generate-block-guarded or `` `ifdef ``-guarded always block is
    reported exactly as written -- its guard condition is not evaluated,
    matching verible_parser.py's and design_architecture_ir.py's own
    documented stance.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from . import verible_parser
from .verible_parser import (
    DEFAULT_VERIBLE_BIN,
    VeribleParseError,
    VeribleUnavailableError,
    find_all_nonoverlapping,
    node_span,
)
from .design_architecture_ir import (
    _CASE_OPEN_RE,
    _find_case_block,
    _line_in_slice,
    _strip_noise_preserve_offsets,
)

SCHEMA_VERSION = "1.0"

__all__ = [
    "SCHEMA_VERSION",
    "RtlControlFlowExtractionError",
    "extract_control_flow_facts",
    "parse_rtl_file",
    "build_control_flow_ir",
    "save_control_flow_ir",
    "format_report",
    "execute_verb",
    "main",
]


class RtlControlFlowExtractionError(Exception):
    """Raised only for a caller usage error. Never raised for an absent/
    unresolvable RTL fact -- those are reported as NOT_AVAILABLE/
    UNCLASSIFIED_SENSITIVITY fields on the extraction result itself, per
    the Evidence Truth Rule."""


# ---------------------------------------------------------------------------
# Always-block header + block-kind classification
# ---------------------------------------------------------------------------

_ALWAYS_HEADER_RE = re.compile(
    r"\balways(?P<variant>_ff|_comb|_latch)?\b"
    r"(?:\s*@\s*(?:(?P<star>\*)|\((?P<sens>[^)]*)\)))?"
)

_EDGE_RE = re.compile(r"\b(?:posedge|negedge)\b")

BLOCK_KIND_SEQUENTIAL = "SEQUENTIAL"
BLOCK_KIND_COMBINATIONAL = "COMBINATIONAL"
BLOCK_KIND_LATCH_EXPLICIT = "LATCH_EXPLICIT"
BLOCK_KIND_UNCLASSIFIED = "UNCLASSIFIED_SENSITIVITY"


def _classify_block_kind(variant: Optional[str], star: Optional[str],
                          sens: Optional[str]) -> Tuple[str, Optional[str]]:
    """Returns (block_kind, reason). `reason` is non-None only when the
    keyword and the sensitivity evidence this scan found disagree, or when
    nothing could be classified at all -- never when classification is
    clean."""
    if variant == "_comb":
        return BLOCK_KIND_COMBINATIONAL, None
    if variant == "_latch":
        return BLOCK_KIND_LATCH_EXPLICIT, None

    if star is not None:
        found_kind: Optional[str] = BLOCK_KIND_COMBINATIONAL
    elif sens is not None:
        stripped = sens.strip()
        if stripped in ("", "*"):
            found_kind = BLOCK_KIND_COMBINATIONAL
        elif _EDGE_RE.search(stripped):
            found_kind = BLOCK_KIND_SEQUENTIAL
        else:
            found_kind = BLOCK_KIND_COMBINATIONAL
    else:
        found_kind = None

    if variant == "_ff":
        if found_kind == BLOCK_KIND_SEQUENTIAL:
            return BLOCK_KIND_SEQUENTIAL, None
        return (
            BLOCK_KIND_SEQUENTIAL,
            "always_ff keyword present but this scan could not find an "
            "explicit posedge/negedge in its own sensitivity clause -- "
            "trusting the always_ff keyword (SystemVerilog requires it be "
            "edge-triggered) rather than reporting UNCLASSIFIED",
        )

    if found_kind is None:
        return (
            BLOCK_KIND_UNCLASSIFIED,
            "no @(...) or @* sensitivity clause was found by this scan "
            "after this 'always' keyword -- this may be a testbench-only "
            "delay-driven always block (e.g. 'always #5 clk = ~clk;'), a "
            "construct this scan's fixed patterns do not recognise, or a "
            "genuine parse boundary this window truncated early",
        )
    return found_kind, None


# ---------------------------------------------------------------------------
# Depth-tracked if/else-if/else chain scan (genuinely new machinery --
# design_architecture_ir.py's FSM scan never needed one, since it only ever
# depth-counts case/endcase)
# ---------------------------------------------------------------------------

_DEPTH_TOKEN_RE = re.compile(
    r"\b(?P<open>begin|case[xz]?)\b"
    r"|\b(?P<close>end|endcase)\b"
    r"|\b(?P<elseif>else\s+if)\b"
    r"|\b(?P<elsekw>else)\b"
    r"|\b(?P<ifkw>if)\b"
)


def _scan_control_tokens(clean_text: str, start: int, end: int) -> List[Tuple[str, int, int]]:
    """Depth-tracked scan of `if`/`else if`/`else` tokens between `start`
    and `end` of `clean_text` (already noise-stripped). Depth is a plain
    running count of `begin`/`case[xz]?` (open) vs `end`/`endcase` (close)
    tokens seen so far -- see module docstring's "Chain continuation"
    boundary note. Returns a list of (kind, depth, position) tuples for
    every `if`/`else if`/`else` token found, in text order; `depth` is the
    value BEFORE that token (an if/else keyword never itself opens or
    closes a begin/end/case scope)."""
    depth = 0
    records: List[Tuple[str, int, int]] = []
    for m in _DEPTH_TOKEN_RE.finditer(clean_text, start, end):
        if m.group("open") is not None:
            depth += 1
        elif m.group("close") is not None:
            depth = max(0, depth - 1)
        elif m.group("elseif") is not None:
            records.append(("elseif", depth, m.start()))
        elif m.group("elsekw") is not None:
            records.append(("elsekw", depth, m.start()))
        elif m.group("ifkw") is not None:
            records.append(("ifkw", depth, m.start()))
    return records


def _extract_if_chain(records: Sequence[Tuple[str, int, int]]) -> Optional[dict]:
    """From the token records `_scan_control_tokens()` produced, extracts
    only the FIRST if/else-if/else chain (see module docstring's "Only the
    FIRST... chain" boundary). Returns None if no `if` token was found at
    all."""
    if_records = [r for r in records if r[0] == "ifkw"]
    if not if_records:
        return None
    first = min(if_records, key=lambda r: r[2])
    chain_depth = first[1]
    chain: List[Tuple[str, int, int]] = [first]
    later = sorted((r for r in records if r[2] > first[2]), key=lambda r: r[2])
    for kind, depth, pos in later:
        if depth < chain_depth:
            break
        if depth > chain_depth:
            continue
        if kind in ("elseif", "elsekw"):
            chain.append((kind, depth, pos))
            if kind == "elsekw":
                break
        elif kind == "ifkw":
            break
    branch_count = sum(1 for r in chain if r[0] in ("ifkw", "elseif"))
    has_terminal_else = chain[-1][0] == "elsekw"
    return {
        "branch_count": branch_count,
        "has_terminal_else": has_terminal_else,
        "if_start": first[2],
    }


# ---------------------------------------------------------------------------
# Per-module-text extraction
# ---------------------------------------------------------------------------

def extract_control_flow_facts(module_text: str, module_name: str, *,
                                base_line: int = 1) -> List[dict]:
    """Best-effort literal scan of ONE module's own source text for
    `always`/`always_ff`/`always_comb`/`always_latch` blocks, reporting
    each one's block_kind, if-chain shape and case shape. Never raises for
    malformed input text. See module docstring for the full boundary."""
    clean = _strip_noise_preserve_offsets(module_text)
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
        records = _scan_control_tokens(clean, body_start, window_end)
        if_chain = _extract_if_chain(records)
        if_chain_line = (
            _line_in_slice(base_line, clean, if_chain["if_start"])
            if if_chain else None
        )

        case_open = _CASE_OPEN_RE.search(clean, body_start, window_end)
        if case_open is None:
            case_shape = {"present": False, "has_default": None,
                          "status": "NOT_APPLICABLE",
                          "reason": "no case/casex/casez statement found in "
                                    "this block's own scanned window",
                          "line": None}
        else:
            case_block = _find_case_block(clean, case_open.start())
            case_line = _line_in_slice(base_line, clean, case_open.start())
            if case_block is None:
                case_shape = {"present": True, "has_default": None,
                              "status": "UNPARSEABLE",
                              "reason": "found 'case(...)' but no matching "
                                        "'endcase' before this scan's "
                                        "window ended",
                              "line": case_line}
            else:
                has_default = any(
                    it["label"] == "default" for it in case_block["items"])
                case_shape = {"present": True, "has_default": has_default,
                              "status": "RESOLVED", "reason": None,
                              "line": case_line}

        findings: List[dict] = []
        if block_kind == BLOCK_KIND_COMBINATIONAL:
            if if_chain is not None and not if_chain["has_terminal_else"]:
                findings.append({
                    "finding": "LATCH_INFERENCE_RISK_CANDIDATE",
                    "reason": "this combinational always block's own "
                              "if/else-if chain has no terminal 'else' "
                              "this scan could find -- a synthesis tool "
                              "MAY infer a latch for whatever signal is "
                              "only assigned on the taken paths; this "
                              "scan proves only the structural absence of "
                              "a terminal else, never that the block is "
                              "actually incomplete (an unconditional "
                              "assignment to the same signal elsewhere in "
                              "this block, which this scan does not "
                              "track, could still make it complete)",
                    "line": if_chain_line,
                })
            if case_shape["status"] == "RESOLVED" and case_shape["has_default"] is False:
                findings.append({
                    "finding": "LATCH_INFERENCE_RISK_CANDIDATE",
                    "reason": "this combinational always block's own "
                              "case/casex/casez statement has no 'default' "
                              "item this scan could find -- the same "
                              "structural-absence caveat as the if-chain "
                              "finding above applies",
                    "line": case_shape["line"],
                })
        elif block_kind == BLOCK_KIND_SEQUENTIAL:
            if if_chain is not None and not if_chain["has_terminal_else"]:
                findings.append({
                    "finding": "PRIORITY_STRUCTURE_NO_TERMINAL_ELSE",
                    "reason": "this sequential (clocked) always block's "
                              "own if/else-if chain has no terminal "
                              "'else' this scan could find -- normal for "
                              "a register that legitimately retains its "
                              "value on the untaken path; reported as an "
                              "informational priority-structure fact, "
                              "never a latch-inference risk",
                    "line": if_chain_line,
                })

        blocks.append({
            "keyword": keyword,
            "block_kind": block_kind,
            "block_kind_reason": kind_reason,
            "always_line": always_line,
            "if_chain": if_chain,
            "if_chain_line": if_chain_line,
            "case_shape": case_shape,
            "findings": findings,
        })
    return blocks


def _module_control_flow_summary(blocks: List[dict]) -> dict:
    if not blocks:
        return {
            "status": "NOT_AVAILABLE",
            "reason": "no 'always'/'always_ff'/'always_comb'/'always_latch' "
                      "block was found in this module's source text",
            "blocks": [],
        }
    return {"status": "CONTROL_FLOW_EXTRACTED", "reason": None, "blocks": blocks}


# ---------------------------------------------------------------------------
# Per-file parse -- wraps verible_parser.py's own output directly (same
# primitives design_architecture_ir.py uses; not that module's own
# orchestration, since this module needs no ports/params/signals/instances,
# only each module's own source span)
# ---------------------------------------------------------------------------

def parse_rtl_file(path: Union[str, Path], *, verible_bin: str = DEFAULT_VERIBLE_BIN) -> dict:
    """Runs verible over ONE file and attaches `control_flow_extraction`
    (see `extract_control_flow_facts()`) to each real parsed module.
    Never raises for a file this scan cannot fully process: an unreadable
    file, an unrunnable verible binary, or a file with real syntax errors
    all report a distinct `status` (`NOT_AVAILABLE` / `PARSE_ERROR`) with a
    real reason and an empty `modules` list."""
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
                "source_sha256": source_sha256, "verible_version": None,
                "modules": []}
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
        if span is None or minfo.name is None:
            modules_out.append({
                "name": minfo.name,
                "control_flow_extraction": {
                    "status": "NOT_AVAILABLE",
                    "reason": "could not determine this module's own source span",
                    "blocks": [],
                },
            })
            continue
        module_text = source[span[0]:span[1]]
        base_line = source.count("\n", 0, span[0]) + 1
        blocks = extract_control_flow_facts(module_text, minfo.name, base_line=base_line)
        modules_out.append({
            "name": minfo.name,
            "control_flow_extraction": _module_control_flow_summary(blocks),
        })

    return {
        "file_path": str(p), "status": "PARSED", "reason": None,
        "source_sha256": source_sha256,
        "verible_version": verible_parser.get_verible_version(verible_bin),
        "modules": modules_out,
    }


def build_control_flow_ir(rtl_files: Sequence[Union[str, Path]], *,
                           verible_bin: str = DEFAULT_VERIBLE_BIN) -> dict:
    """The one real entry point over several files. Parses every file in
    `rtl_files` (each file's own status isolated -- one real syntax error
    never sinks the whole build) and attaches control-flow extraction per
    module. No caller-usage error is possible here (an empty `rtl_files`
    is reported NOT_AVAILABLE, not raised)."""
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


def save_control_flow_ir(ir: dict, path: Union[str, Path]) -> None:
    Path(path).write_text(json.dumps(ir, indent=2, sort_keys=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Reporting / CLI (standalone front door -- see this task's own disclosed
# choice not to edit cli.py/gates.py while they are under concurrent-batch
# edit pressure, matching several very recent same-day modules in this repo)
# ---------------------------------------------------------------------------

def format_report(ir: dict) -> str:
    if ir["status"] != "BUILT":
        return "%s: %s" % (ir["status"], ir.get("reason"))
    lines = ["rtl_control_flow_extraction schema %s" % SCHEMA_VERSION]
    for pf in ir["files"]:
        if pf["status"] != "PARSED":
            lines.append("  %s: %s -- %s" % (pf["file_path"], pf["status"], pf["reason"]))
            continue
        for mod in pf["modules"]:
            cf = mod["control_flow_extraction"]
            lines.append("  %s :: %s -- %s" % (pf["file_path"], mod["name"], cf["status"]))
            for blk in cf.get("blocks", []):
                lines.append(
                    "    line %s: %s block_kind=%s%s"
                    % (blk["always_line"], blk["keyword"], blk["block_kind"],
                       (" (%s)" % blk["block_kind_reason"]) if blk["block_kind_reason"] else "")
                )
                if blk["if_chain"]:
                    lines.append(
                        "      if-chain: branches=%d terminal_else=%s"
                        % (blk["if_chain"]["branch_count"], blk["if_chain"]["has_terminal_else"])
                    )
                if blk["case_shape"]["present"]:
                    lines.append(
                        "      case: status=%s has_default=%s"
                        % (blk["case_shape"]["status"], blk["case_shape"]["has_default"])
                    )
                for f in blk["findings"]:
                    lines.append("      FINDING %s (line %s)" % (f["finding"], f["line"]))
    return "\n".join(lines)


def execute_verb(rtl_files: Sequence[Union[str, Path]], *,
                  verible_bin: str = DEFAULT_VERIBLE_BIN,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m
    dv_harness.rtl_control_flow_extraction`. Returns (text, exit_code): 0
    the IR was built (at least one module parsed from at least one supplied
    file), 2 NOT_AVAILABLE. Reads and reports only; runs, builds, submits
    and approves nothing."""
    ir = build_control_flow_ir(rtl_files, verible_bin=verible_bin)
    text = json.dumps(ir, indent=2) if as_json else format_report(ir)
    code = 0 if ir["status"] == "BUILT" else 2
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.rtl_control_flow_extraction",
        description="Bounded, disclosed-scope control-flow / combinational-vs-sequential "
                    "logic-intent extraction over always-block bodies. Reads and reports "
                    "only; runs nothing.")
    ap.add_argument("--rtl", action="append", required=True, dest="rtl_files",
                    help="An RTL file to include in this build (repeatable).")
    ap.add_argument("--verible-bin", default=DEFAULT_VERIBLE_BIN)
    ap.add_argument("--out", default=None, help="Also write the full JSON IR to this path.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    ir = build_control_flow_ir(a.rtl_files, verible_bin=a.verible_bin)
    text = json.dumps(ir, indent=2) if (a.json or a.out) else format_report(ir)
    code = 0 if ir["status"] == "BUILT" else 2
    if a.out:
        save_control_flow_ir(ir, a.out)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
