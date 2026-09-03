#!/usr/bin/env python
"""Find register writes that hand a bare literal value to a WRITE macro with
no read-modify-write protecting it.

GENERIC TEMPLATE: this checker's FRAMEWORK (find `<...>WRITE<n>B(<reg>, <value>)`
macro calls, decide whether <value> is a bare literal, decide whether an RMW
sequence protects that write, optionally cross-check against a register/
bit-field table) is protocol-agnostic and DUT-agnostic. Nothing below is tied
to USB; the macro-name pattern is a regex over "...WRITE<digits>B", matching
this template's original USB project's own CPUWRITE1B/CPUWRITE2B/CPUWRITE4B/
CPUREAD1B/CPUREAD2B/CPUREAD4B/HOSTWRITE4B-style macros as one illustrative
case, not the only one it recognizes:

    python reg_write_safety.py <UVM_ROOT_PATH>
    python reg_write_safety.py <UVM_ROOT_PATH> --reg-table regmap.json
    REG_WRITE_MACRO_PATTERN='[A-Za-z_]+WR[0-9]*'  python reg_write_safety.py <UVM_ROOT_PATH>

Usage:  reg_write_safety.py <ROOT> [--reg-table PATH.json] [-v]
        ROOT is walked recursively for .sv/.svh/.v/.vh/.txt files.
        --reg-table (or the REG_TABLE_JSON env var) is OPTIONAL -- see below.
        -v also prints INFO-severity findings (registers the table says are
           genuinely safe to overwrite blind).

WHY THIS EXISTS
----------------
A register write built as `\\`CPUWRITE4B(\\`REG(0), 32'h00000400)` puts EXACTLY
32'h00000400 into the register -- every bit not set in that literal becomes
ZERO, including any bit that was sitting at a non-zero RESET DEFAULT the
author never looked at. This template's original USB project hit exactly
this shape: `TCA_CTRLSYNCMODE` was written as the bare literal 0x00000400
instead of read-modify-write, and the write silently zeroed 4 other fields
that were non-zero at reset. Because the write "landed" (a readback showed
the intended bit set) and the symptom under investigation did not change,
the team spent several further debugging rounds on a wrong root-cause
conclusion ("the fix is ineffective") before recognising that other live
bits had been corrupted by the same write and that the readback proved
nothing about them.

"The write landed but the symptom didn't change" is not sound evidence when
a bare-literal write may have clobbered unrelated, unexamined bits in the
same register. This checker finds that shape statically, before elaboration,
so the corruption is caught before it produces a wrong conclusion instead of
after.

WHAT COUNTS AS A FINDING
-------------------------
A macro call matching the write-macro pattern (default: any macro whose name
matches `...WRITE<digits>B`, case-sensitive, e.g. CPUWRITE4B, CPUWRITE2B,
CPUWRITE1B, HOSTWRITE4B) whose VALUE argument, after stripping one level of
wrapping parens, is a bare literal (`32'h0000_0400`, `'h32`, `0x400`, `1024`
-- no identifier, no operator) is a candidate. It is EXCLUDED (not flagged)
when either:

  (a) the value argument is NOT a bare literal at all -- e.g.
      `(reg_val | 32'h00000400)` is an expression built from a variable, which
      is exactly what a correct read-modify-write's final write call looks
      like. A real RMW writes back a COMPUTED VARIABLE, never a bare literal,
      so this exclusion is really "this call is not the shape under test."
  (b) a read-modify-write sequence for the SAME register macro is found
      textually upstream of this write in the same file: a variable
      assigned from a `...READ<digits>B(<same register>...)` call, later
      combined with a literal via `|`, `|=`, `&`, or `&=` (the bitwise-OR /
      AND-NOT combining step of RMW). When present, the write is treated as
      RMW-protected even though its own call happens to spell out a literal.

A candidate that survives both exclusions is reported. Severity depends on
whether a register/bit-field table was supplied (see below):

  no table given            -> WARN "register semantics unknown -- verify
                                manually" (never silently passes; this is
                                the honest answer when nothing is known
                                about the register's field layout)
  table given, no entry     -> WARN, same message (table exists but doesn't
                                cover this register)
  table given, entry found,
    >=1 field's RESET value
    differs from what the
    literal would leave there -> ERROR, naming every clobbered field, its
                                reset value and what the literal leaves it at
                                -- this is the exact TCA_CTRLSYNCMODE shape
  table given, entry found,
    no field differs          -> INFO (shown only with -v): the table says
                                this specific literal happens to match reset
                                on every known field, so THIS write does not
                                clobber a known non-zero default -- still not
                                RMW-safe against an EARLIER write to the same
                                register, which the table cannot see

THE OPTIONAL REGISTER TABLE
----------------------------
A JSON file mapping register macro name -> {"width": <int>, "reset": "0x..",
"fields": [{"name": "...", "hi": <int>, "lo": <int>}, ...]}. This is
deliberately an OPTIONAL input, not a hardcoded map: a generated environment
supplies its own DUT's real register/bit-field definitions (from the
register spec, not invented). Passing --reg-table only sharpens WARN into a
concrete, named ERROR when the table proves a real clobber; omitting it
does not make the checker silently pass writes it cannot evaluate -- see
"no table given" above.
"""

import json
import os
import re
import sys

SRC_EXT = (".sv", ".svh", ".v", ".vh", ".txt")

# Macro-name pattern, overridable so a project whose register-access macros
# don't follow the CPUWRITE4B/HOSTWRITE4B shape can still use this checker
# without editing it. Defaults match this template's original USB project's
# real macros (CPUWRITE1B/2B/4B, HOSTWRITE4B) as one illustrative case.
WRITE_MACRO_PATTERN = os.environ.get(
    "REG_WRITE_MACRO_PATTERN", r"[A-Za-z_][A-Za-z0-9_]*WRITE[0-9]*B")
READ_MACRO_PATTERN = os.environ.get(
    "REG_READ_MACRO_PATTERN", r"[A-Za-z_][A-Za-z0-9_]*READ[0-9]*B")

WRITE_CALL = re.compile(r"`(" + WRITE_MACRO_PATTERN + r")\s*\(")
READ_ASSIGN = re.compile(
    r"([A-Za-z_]\w*)\s*=\s*`(" + READ_MACRO_PATTERN + r")\s*\(\s*`?\s*([A-Za-z_]\w*)")

LINE_COMMENT = re.compile(r"//.*?$", re.M)
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)

_SIZED_LIT = re.compile(r"^(\d+)?'([sS]?[bBoOdDhH])([0-9a-fA-FxzXZ_]+)$")
_HEX_C_LIT = re.compile(r"^0[xX][0-9a-fA-F_]+$")
_DEC_LIT = re.compile(r"^\d[\d_]*$")


def strip_comments(text):
    """Remove comments but preserve line count so reported lines stay correct."""
    def _blank(m):
        return "\n" * m.group(0).count("\n")
    text = BLOCK_COMMENT.sub(_blank, text)
    text = LINE_COMMENT.sub("", text)
    return text


def _split_args(arglist):
    """Split a macro argument list at top-level commas only (depth-aware over
    (), [], {} and quote-aware), same convention as usb_static_check.py's
    _split_args -- so `FILLMEM("a,b", 4, 40'h2000_1000)` is not miscounted."""
    args, depth, cur, in_str = [], 0, [], False
    for ch in arglist:
        if in_str:
            cur.append(ch)
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        args.append(tail)
    return args


def _match_paren(text, open_idx):
    """Index of the ')' matching the '(' at open_idx, or -1."""
    depth, i, n, in_str = 0, open_idx, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _strip_wrapping_parens(tok):
    tok = tok.strip()
    while tok.startswith("(") and tok.endswith(")"):
        depth, balanced = 0, True
        for i, ch in enumerate(tok):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(tok) - 1:
                    balanced = False
                    break
        if not balanced:
            break
        tok = tok[1:-1].strip()
    return tok


def parse_literal(tok):
    """Return the integer value of a bare Verilog/C-style literal token, or
    None if tok is not (purely) a literal -- an identifier, an operator
    expression, a function call, all return None."""
    tok = tok.strip()
    m = _SIZED_LIT.match(tok)
    if m:
        base = m.group(2).lower().lstrip("s")
        digits = m.group(3).replace("_", "")
        digits = re.sub(r"[xXzZ]", "0", digits)
        try:
            return int(digits, {"h": 16, "d": 10, "o": 8, "b": 2}[base])
        except ValueError:
            return None
    if _HEX_C_LIT.match(tok):
        return int(tok.replace("_", ""), 16)
    if _DEC_LIT.match(tok):
        return int(tok.replace("_", ""), 10)
    return None


def is_bare_literal(value_arg):
    """(is_literal, int_value) for a WRITE macro's value argument."""
    inner = _strip_wrapping_parens(value_arg)
    v = parse_literal(inner)
    return v is not None, v


def reg_name_of(reg_arg):
    """Best-effort register name from a WRITE/READ macro's first argument,
    e.g. "`TCA_CTRLSYNCMODE(0)" -> "TCA_CTRLSYNCMODE"."""
    m = re.match(r"`?\s*([A-Za-z_]\w*)", reg_arg.strip())
    return m.group(1) if m else None


def bits(v, hi, lo):
    return (v >> lo) & ((1 << (hi - lo + 1)) - 1)


def rmw_protects(text, reg, write_start, window=4000):
    """True if, within `window` characters before write_start, a variable was
    assigned from a READ macro on the SAME register and later combined with
    `|`, `|=`, `&` or `&=` before reaching write_start -- the textual
    signature of a read-modify-write sequence for this register."""
    lo = max(0, write_start - window)
    span = text[lo:write_start]
    last = None
    for m in READ_ASSIGN.finditer(span):
        var, _macro, read_reg = m.group(1), m.group(2), m.group(3)
        if read_reg == reg:
            last = (var, m.end())
    if not last:
        return False
    var, after = last
    combine = re.compile(
        r"\b" + re.escape(var) + r"\s*(?:\|=|&=|=\s*" + re.escape(var) + r"\s*[|&])")
    return bool(combine.search(span[after:]))


class Finding(object):
    def __init__(self, severity, path, line, message):
        self.severity = severity  # "ERROR" | "WARN" | "INFO"
        self.path = path
        self.line = line
        self.message = message

    def __str__(self):
        return "[%-5s] %s:%d\n            %s" % (
            self.severity, self.path, self.line, self.message)


def load_reg_table(path):
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    table = {}
    for name, entry in raw.items():
        reset = entry.get("reset", "0x0")
        reset_val = int(reset, 16) if isinstance(reset, str) else int(reset)
        table[name] = {
            "width": entry.get("width", 32),
            "reset": reset_val,
            "fields": entry.get("fields", []),
        }
    return table


def line_of(text, idx):
    return text.count("\n", 0, idx) + 1


def scan_file(path, raw, reg_table, findings):
    text = strip_comments(raw)
    for m in WRITE_CALL.finditer(text):
        close = _match_paren(text, m.end() - 1)
        if close < 0:
            continue
        args = _split_args(text[m.end():close])
        if len(args) < 2:
            continue
        reg_arg, val_arg = args[0], args[-1]
        literal, value = is_bare_literal(val_arg)
        if not literal:
            continue  # exclusion (a): a real RMW write hands over an expression
        reg = reg_name_of(reg_arg)
        if reg and rmw_protects(text, reg, m.start()):
            continue  # exclusion (b): RMW sequence for this register found upstream
        line = line_of(text, m.start())
        entry = reg_table.get(reg) if reg else None
        if entry is None:
            findings.append(Finding(
                "WARN", path, line,
                "`%s(%s, %s)`: bare literal value, no read-modify-write "
                "protecting it, register semantics unknown -- verify manually"
                % (m.group(1), reg_arg.strip(), val_arg.strip())))
            continue
        clobbered = []
        for f in entry["fields"]:
            hi, lo = f["hi"], f["lo"]
            reset_field = bits(entry["reset"], hi, lo)
            new_field = bits(value, hi, lo)
            if reset_field != 0 and reset_field != new_field:
                clobbered.append((f["name"], reset_field, new_field))
        if clobbered:
            detail = ", ".join(
                "%s: reset=0x%x -> 0x%x" % c for c in clobbered)
            findings.append(Finding(
                "ERROR", path, line,
                "`%s(%s, %s)`: blind literal write with no RMW clobbers "
                "%d field(s) at their non-zero reset default -- %s"
                % (m.group(1), reg_arg.strip(), val_arg.strip(),
                   len(clobbered), detail)))
        else:
            findings.append(Finding(
                "INFO", path, line,
                "`%s(%s, %s)`: table entry for '%s' found; no known field "
                "differs from reset under this literal, but this write is "
                "still not RMW -- an earlier write's change to another "
                "field would be silently lost" % (
                    m.group(1), reg_arg.strip(), val_arg.strip(), reg)))


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    root = argv[1]
    rest = argv[2:]
    verbose = "-v" in rest
    table_path = os.environ.get("REG_TABLE_JSON")
    if "--reg-table" in rest:
        table_path = rest[rest.index("--reg-table") + 1]

    reg_table = load_reg_table(table_path) if table_path else {}

    files = []
    for base, _dirs, names in os.walk(root):
        for n in names:
            if n.endswith(SRC_EXT):
                files.append(os.path.join(base, n))

    findings = []
    for f in sorted(files):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError:
            continue
        scan_file(os.path.relpath(f, root), raw, reg_table, findings)

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    shown = [x for x in findings if order[x.severity] < 2 or verbose]
    shown.sort(key=lambda x: (order[x.severity], x.path, x.line))
    for x in shown:
        print(x)

    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for x in findings:
        counts[x.severity] += 1
    print("-" * 78)
    print("%d write(s) with a bare-literal value and no RMW protection: "
          "ERROR=%d WARN=%d INFO=%d%s"
          % (len(findings), counts["ERROR"], counts["WARN"], counts["INFO"],
             "" if verbose else "  (-v to also show INFO)"))
    if not reg_table:
        print("NOTE: no --reg-table supplied -- every finding above is a "
              "WARN because register semantics are unknown, not because the "
              "writes are known-safe. Supply a register/bit-field table to "
              "sharpen real clobbers into ERROR.")
    return 1 if counts["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
