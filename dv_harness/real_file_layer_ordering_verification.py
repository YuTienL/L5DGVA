"""dv_harness/real_file_layer_ordering_verification.py -- confirms that a
REAL, already-generated command.txt/pattern file genuinely places `block`
before `branch_a*` before `branch_fw` IN THE ACTUAL FILE TEXT, not merely in
some caller-typed declaration of intent.

WHAT THIS CLOSES
------------------------------------------------------------------------
`dv_harness/pattern_ir_assembly.py`'s `validate_layer_ordering()` validates a
caller-SUPPLIED `declared_order` list against
`pattern_ir_assembly.DEFAULT_LAYER_ORDER` -- it never opens a real generated
file. `dv_harness/branch_ownership_resolver.py`'s own module docstring says
so outright: "Neither function reads RTL, a VIP index, or a command.txt
file... this module reasons over that declaration, it does not derive it."
`tools/verification_flow/branch_topology_gate.py` (cited by
`branch_ownership_resolver.py` as "the single source of truth for the
canonical form") likewise reads only a caller-declared JSON `topology`
document's `branches` list, never a real file's own text. So nothing in this
repository has ever confirmed that a real generated pattern file's own
statements are actually laid out in the required order, as opposed to merely
being DECLARED that way in some separate, possibly-stale manifest.

This module is that missing check, scoped exactly to the three layers the
assigned task names -- `block`, `branch_a*`, `branch_fw`
(`pattern_ir_assembly.LAYER_GLOBAL` / `LAYER_DUT` / `LAYER_FW_POLICY`). It
never re-derives a verdict about `branch_b*`/verdict placement (`LAYER_VIP` /
`LAYER_CHECK`) -- that stays `validate_layer_ordering()`'s own job over a
DECLARED order, a different question from this module's over an OBSERVED
one, and this module imports `pattern_ir_assembly`'s layer-name constants and
`DEFAULT_LAYER_ORDER` directly rather than re-typing a second ordering
vocabulary.

REUSE, NOT A SECOND NAMING CONVENTION
------------------------------------------------------------------------
Canonical branch-label spelling (`block`, `branch_a{i}`, `branch_fw`,
underscore-separated, 0-indexed) is imported verbatim from
`dv_harness/amba_discovery_report.py`'s `L5_BRANCH_BLOCK` / `L5_BRANCH_FW` /
`l5_branch_a` -- the exact source `branch_ownership_resolver.py` already
cites as this repo's single source of truth for the canonical form, after
three-to-four incompatible naming conventions were once found coexisting
here (see `tools/verification_flow/branch_topology_gate.py`'s own header).
This module never spells the canonical labels a second way.

EVIDENCE, NOT A BARE WORD SEARCH
------------------------------------------------------------------------
A canonical label is recognised only in a real STRUCTURAL position this
project's own command.txt-shaped fixtures already establish as evidence of
an actual launch/declaration site (see
`dv_harness_tests/test_branch_ownership_resolver.py`'s own
`CANONICAL_PATTERN_TXT`: `` `SOC_GLOBAL_INIT(block)``,
`` `USB_FORK_PORT_BRINGUP(branch_a0, branch_a1)``,
`` `USB_FORK_FW_SERVICE(branch_fw)``, `branch_b0: ...`): a whole-token
argument inside a backtick-macro call's parentheses, a label immediately
followed by `:` at the start of a line, a SystemVerilog named-block form
(`begin : branch_fw`), or a `task <label>(...)` declaration. A bare
occurrence of the English word "block" in prose, or any canonical label
spelled inside a `//`/`/* */` comment or a `"..."` string literal, is never
counted -- comments and string literals are blanked out (length- and
newline-preserving, so line numbers stay real) before any regex runs, the
same discipline `design_architecture_ir.py`'s own FSM literal scan already
applies for the identical false-positive reason.

Only the FIRST real occurrence of each canonical label counts as that
layer's "genesis line" -- the point the file first actually launches/
declares that layer. `branch_fw` is documented
(`pattern-architecture/SKILL.md` section 1) as legitimately idempotent
against being invoked more than once (guarded against a second launch by its
own internal flag); a second real occurrence later in the file is not itself
a defect this module reports -- only the first genuinely counts toward
ordering.

STATUS VOCABULARY (deliberately distinct from `dv_harness.models.Status`,
checked at import time)
------------------------------------------------------------------------
`FILE_ORDER_CONFIRMED`  -- `block`, at least one `branch_a*`, and `branch_fw`
                           were all found, and their real genesis lines are
                           strictly increasing in that order.
`FILE_ORDER_VIOLATION`  -- all three were found, but the real genesis lines
                           are NOT in the required order -- names the exact
                           offending pair and both real cited line numbers.
`LAYER_NOT_FOUND`       -- one or more of the three layers has no real,
                           structurally-recognised occurrence anywhere in
                           the file -- never silently treated as "in order"
                           and never guessed at.

Deliberately bounded, and stated rather than implied closed: this is a
declaration-level line/regex scan, not a SystemVerilog parser and not an
elaborator -- a construct spanning an unusual continuation, or a project
using an entirely different macro-authoring convention than the one this
repo's own fixtures establish, contributes no citation rather than a wrong
one, and reports `LAYER_NOT_FOUND` honestly. It decides, approves and
arbitrates nothing beyond reporting: no build, job, or approval is touched,
and there is deliberately no stage gate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dv_harness.amba_discovery_report import L5_BRANCH_BLOCK, L5_BRANCH_FW, l5_branch_a
from dv_harness.pattern_ir_assembly import (
    DEFAULT_LAYER_ORDER,
    LAYER_DUT,
    LAYER_FW_POLICY,
    LAYER_GLOBAL,
)

# ===========================================================================
# Status vocabulary -- checked disjoint from dv_harness.models.Status at
# import time, the same discipline several sibling modules already apply to
# their own domain vocabularies.
# ===========================================================================

STATUS_CONFIRMED = "FILE_ORDER_CONFIRMED"
STATUS_VIOLATION = "FILE_ORDER_VIOLATION"
STATUS_LAYER_NOT_FOUND = "LAYER_NOT_FOUND"

_ALL_STATUSES = (STATUS_CONFIRMED, STATUS_VIOLATION, STATUS_LAYER_NOT_FOUND)

#: The three layers this module checks, in the required order -- the first
#: three entries of `pattern_ir_assembly.DEFAULT_LAYER_ORDER`, reused
#: verbatim (never re-typed) as the required subsequence a real file's own
#: text must respect.
REQUIRED_LAYER_SUBSEQUENCE: tuple = (LAYER_GLOBAL, LAYER_DUT, LAYER_FW_POLICY)


def _assert_reused_vocabulary_consistent() -> None:
    if tuple(DEFAULT_LAYER_ORDER[:3]) != REQUIRED_LAYER_SUBSEQUENCE:
        raise AssertionError(
            "pattern_ir_assembly.DEFAULT_LAYER_ORDER's first three entries "
            f"no longer match REQUIRED_LAYER_SUBSEQUENCE "
            f"({DEFAULT_LAYER_ORDER[:3]!r} != {REQUIRED_LAYER_SUBSEQUENCE!r}) "
            "-- this module must be re-derived from the real, current "
            "ordering vocabulary, never left silently stale."
        )
    from dv_harness import models  # local import: keep this module cheap

    verdicts = {member.value for member in models.Status}
    collisions = verdicts & set(_ALL_STATUSES)
    if collisions:
        raise AssertionError(
            "real_file_layer_ordering_verification status vocabulary "
            f"collides with dv_harness.models.Status: {sorted(collisions)}"
        )


_assert_reused_vocabulary_consistent()


# ===========================================================================
# Evidence extraction -- comment/string-stripped, structural-position-only.
# ===========================================================================

_MACRO_CALL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")
_LABEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:")
#: `begin : <label>` -- searched anywhere on the line (not anchored to line
#: start), since a real file routinely writes `initial begin : block` with
#: a keyword ahead of `begin`.
_BEGIN_LABEL_RE = re.compile(r"\bbegin\s*:\s*([A-Za-z_][A-Za-z0-9_]*)")
_TASK_DECL_RE = re.compile(r"^task\s+(?:automatic\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[(;]")
_BRANCH_A_TOKEN_RE = re.compile(r"^branch_a\d+$")

#: Human-readable label used ONLY by `render_text()` -- the internal layer
#: constants (`LAYER_GLOBAL == "global"`, etc.) are reused verbatim
#: everywhere else; this mapping never feeds back into classification.
_LAYER_DISPLAY_LABEL = {
    LAYER_GLOBAL: "block",
    LAYER_DUT: "branch_a*",
    LAYER_FW_POLICY: "branch_fw",
}


def _strip_comments_and_strings(text: str) -> list:
    """Per-line, string-aware `//`/`/* */` comment stripper, length- and
    newline-preserving (blanked chars become spaces) so real line numbers
    never shift. Deliberately re-derived locally rather than imported from
    `reference_pattern_audit._strip_comments()` or
    `design_architecture_ir._strip_noise_preserve_offsets()` -- both are
    private, module-owned helpers, and this project's own established
    convention (stated in `design_architecture_ir.py`, `rtl_data_path_
    extraction.py`, `amba_command_txt_extension.py`, among others) is that
    each extraction module owns its own small bounded regex/comment helper
    rather than import a sibling's private implementation detail."""
    out_lines: list = []
    in_block = False
    for raw in text.splitlines():
        out: list = []
        i = 0
        in_string = False
        n = len(raw)
        while i < n:
            ch = raw[i]
            if in_block:
                if raw.startswith("*/", i):
                    in_block = False
                    out.append("  ")
                    i += 2
                    continue
                out.append(" ")
                i += 1
                continue
            if in_string:
                out.append(" " if ch != '"' else '"')
                if ch == "\\" and i + 1 < n:
                    out.append(" ")
                    i += 2
                    continue
                if ch == '"':
                    in_string = False
                i += 1
                continue
            if ch == '"':
                in_string = True
                out.append('"')
                i += 1
                continue
            if raw.startswith("//", i):
                out.append(" " * (n - i))
                i = n
                continue
            if raw.startswith("/*", i):
                in_block = True
                out.append("  ")
                i += 2
                continue
            out.append(ch)
            i += 1
        out_lines.append("".join(out))
    return out_lines


def _evidence_tokens_on_line(stripped_line: str) -> list:
    """Every candidate token this line offers as a real structural
    launch/declaration site -- never a bare word anywhere in the line."""
    tokens: list = []
    for m in _MACRO_CALL_RE.finditer(stripped_line):
        for raw_arg in m.group(2).split(","):
            arg = raw_arg.strip()
            if arg:
                tokens.append(arg)
    trimmed = stripped_line.strip()
    m = _BEGIN_LABEL_RE.search(trimmed)
    if m:
        tokens.append(m.group(1))
    m = _LABEL_RE.match(trimmed)
    if m:
        tokens.append(m.group(1))
    m = _TASK_DECL_RE.match(trimmed)
    if m:
        tokens.append(m.group(1))
    return tokens


def _classify_token(token: str) -> Optional[str]:
    """Map a real, structurally-evidenced token onto one of this module's
    three tracked layers, using ONLY the reused canonical spellings -- never
    a guessed/fuzzy match."""
    if token == L5_BRANCH_BLOCK:
        return LAYER_GLOBAL
    if token == L5_BRANCH_FW:
        return LAYER_FW_POLICY
    if _BRANCH_A_TOKEN_RE.match(token):
        return LAYER_DUT
    return None


def extract_layer_genesis_lines(source_text: str) -> dict:
    """Return `{layer_name: {"line": int, "token": str}}` for each of the
    three tracked layers, restricted to the FIRST real, structurally-
    recognised occurrence of a canonical label for that layer. A layer with
    no real occurrence anywhere in the text is simply absent from the
    returned dict -- never guessed, defaulted, or silently treated as
    present."""
    genesis: dict = {}
    for line_no, stripped in enumerate(_strip_comments_and_strings(source_text), start=1):
        for token in _evidence_tokens_on_line(stripped):
            layer = _classify_token(token)
            if layer is None or layer in genesis:
                continue
            genesis[layer] = {"line": line_no, "token": token}
    return genesis


# ===========================================================================
# Verification
# ===========================================================================

@dataclass
class RealFileOrderResult:
    status: str
    path: Optional[str]
    genesis: dict
    missing_layers: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "path": self.path,
            "genesis": dict(self.genesis),
            "missing_layers": list(self.missing_layers),
            "violations": list(self.violations),
            "reason": self.reason,
            "required_layer_subsequence": list(REQUIRED_LAYER_SUBSEQUENCE),
        }


def verify_actual_layer_order(source_text: str, *, path: Optional[str] = None) -> RealFileOrderResult:
    """Confirm that a real file's own TEXT places `block` before
    `branch_a*` before `branch_fw`, by real, cited genesis line -- never by
    trusting a caller's declared intent. See module docstring for the
    evidence rules and status vocabulary."""
    genesis = extract_layer_genesis_lines(source_text)
    missing = [layer for layer in REQUIRED_LAYER_SUBSEQUENCE if layer not in genesis]
    if missing:
        return RealFileOrderResult(
            status=STATUS_LAYER_NOT_FOUND,
            path=path,
            genesis=genesis,
            missing_layers=missing,
            reason=(
                "no real, structurally-recognised occurrence of "
                f"{', '.join(missing)} was found anywhere in the file's own "
                "text -- never guessed; the actual order cannot be "
                "confirmed against evidence this module does not have"
            ),
        )

    violations: list = []
    for earlier, later in zip(REQUIRED_LAYER_SUBSEQUENCE, REQUIRED_LAYER_SUBSEQUENCE[1:]):
        earlier_entry = genesis[earlier]
        later_entry = genesis[later]
        if not (earlier_entry["line"] < later_entry["line"]):
            violations.append({
                "earlier_layer": earlier,
                "earlier_token": earlier_entry["token"],
                "earlier_line": earlier_entry["line"],
                "later_layer": later,
                "later_token": later_entry["token"],
                "later_line": later_entry["line"],
            })

    if violations:
        return RealFileOrderResult(
            status=STATUS_VIOLATION,
            path=path,
            genesis=genesis,
            violations=violations,
            reason=(
                "the file's own real statement order contradicts the "
                "required block -> branch_a* -> branch_fw sequence "
                "(pattern_ir_assembly.DEFAULT_LAYER_ORDER's first three "
                "layers)"
            ),
        )

    return RealFileOrderResult(
        status=STATUS_CONFIRMED,
        path=path,
        genesis=genesis,
        reason=(
            "block, branch_a*, and branch_fw each have a real, cited "
            "genesis line in the file's own text, in the required order"
        ),
    )


def verify_file(path) -> RealFileOrderResult:
    """`verify_actual_layer_order()` over a real file read from disk."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return verify_actual_layer_order(text, path=str(p))


# ===========================================================================
# Rendering + CLI
# ===========================================================================

def render_text(result: RealFileOrderResult) -> str:
    lines = [f"status: {result.status}", f"path: {result.path}", f"reason: {result.reason}"]
    if result.genesis:
        lines.append("genesis lines:")
        for layer in REQUIRED_LAYER_SUBSEQUENCE:
            display = _LAYER_DISPLAY_LABEL[layer]
            entry = result.genesis.get(layer)
            if entry:
                lines.append(f"  {display}: line {entry['line']} ({entry['token']})")
            else:
                lines.append(f"  {display}: NOT_FOUND")
    if result.violations:
        lines.append("violations:")
        for v in result.violations:
            lines.append(
                f"  {_LAYER_DISPLAY_LABEL[v['earlier_layer']]} (line {v['earlier_line']}, "
                f"{v['earlier_token']}) does not precede "
                f"{_LAYER_DISPLAY_LABEL[v['later_layer']]} (line {v['later_line']}, "
                f"{v['later_token']})"
            )
    return "\n".join(lines)


def execute_verb(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="real_file_layer_ordering_verification")
    parser.add_argument("path", help="real command.txt/pattern file to check")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    p = Path(args.path)
    if not p.is_file():
        payload = {"status": "NOT_AVAILABLE", "path": str(p), "reason": f"no such file: {p}"}
        print(json.dumps(payload, indent=2) if args.json else f"status: NOT_AVAILABLE\nreason: no such file: {p}")
        return 2

    result = verify_file(p)
    print(json.dumps(result.to_dict(), indent=2) if args.json else render_text(result))

    if result.status == STATUS_CONFIRMED:
        return 0
    if result.status == STATUS_VIOLATION:
        return 1
    return 2


def main(argv=None) -> int:
    return execute_verb(argv)


if __name__ == "__main__":
    sys.exit(main())
