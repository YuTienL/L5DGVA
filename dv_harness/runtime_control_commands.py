"""dv_harness/runtime_control_commands.py -- CONTROL-command closed-vocabulary
enforcement for command.txt / pattern files (RUNTIME COMMAND EXECUTION batch,
2026-09-06).

GAP THIS CLOSES, RE-VERIFIED BEFORE THIS FILE WAS WRITTEN. `pattern-architecture/
SKILL.md` and `branch-mapper/SKILL.md` (read first, per this batch's own
instructions) both operationalize the `block`/`branch_a*`/`branch_fw`/`branch_b*`
task-composition shape and its `join`-not-`join_any` discipline, but neither
enforces WHICH literal control-dispatch commands a command.txt/pattern file may
invoke -- the underlying spec rule this batch closes is the explicit
"do not create unrestricted scripting behavior in command.txt" instruction. A
repo-wide grep for `BOUNDED_LOOP`, `ILLEGAL_CONTROL_COMMAND` and
`ILLEGAL_UNBOUNDED_LOOP` returned zero hits anywhere in this project before this
file existed -- there was no closed vocabulary and no unbounded-loop check.

WHAT THIS IS NOT, and why it is not an extension of what already exists.
`loop_budget.py`'s `FailureType` taxonomy (STOP: contrast only, per this
task's own instruction, never merge) classifies WHY a *harness stage* failed
(TRANSIENT/LICENSE/DUT_BUG/...) so `engine.loop()` can decide retry-vs-stop --
a completely different axis from this module's "is this ONE command.txt
command a legal control-dispatch command". `reference_pattern_audit.py`
already parses command.txt into classified `CommandStatement`s and already
carries two categories that read as "control" (`C_CONTROL_FLOW` for native
`repeat`/`while`/`for`/`forever`/`if`/`fork`/`join`/`disable`;
`C_SYNCHRONIZATION` for native `wait(...)`/`@(...)`/`#...`), and this module
REUSES that parser and those two categories rather than re-parsing command.txt
text. What that module's own `_categorize()` deliberately does NOT do is
classify a BACKTICK MACRO CALL (`` `WAIT ``, `` `POLL ``, `` `MY_CUSTOM_RETRY ``)
as control at all -- a bare `K_MACRO_CALL`/`K_MODEL_TASK_CALL` falls through
every branch of `_categorize()` to `C_UNCLASSIFIED`, because that module has no
way to know a macro's semantic PURPOSE from its name and, per the Evidence
Truth Rule, correctly refuses to guess. Real command.txt control-flow is
overwhelmingly expressed exactly that way -- backtick macros, per
`pattern-architecture/SKILL.md`'s own USB illustrations (`` `WAIT_SEQ_ALL_OK ``,
`` `USB_PORT_EN ``) -- so a check that only looked at the two existing native
categories would miss almost every real control command. This module supplies
the missing half: a disclosed, NAME-EVIDENCE classification of backtick macro
calls as control-intended, in the exact convention
`reference_pattern_audit.classify_wait()` already established for its own
INTERRUPT_NAME_TOKENS ("the matched token is real evidence, never proof, and is
always cited") -- never a silent guess, and this module's classification NEVER
overwrites or feeds back into `reference_pattern_audit`'s own `.category` field.

THE RULE, OPERATIONALIZED. Any statement this module classifies as a CONTROL
command (native SV control/sync construct, or a macro/model-task call whose
bare name is evidence of control intent) whose bare dispatched name is not
EXACTLY one of the six closed-vocabulary words is `ILLEGAL_CONTROL_COMMAND` --
this is what keeps a command.txt author from reaching for raw `while`/`for`/
`forever`/`fork`/`if`/`disable`/`@`/`#` or an ad hoc `` `RETRY_UNTIL_DONE ``
macro instead of the sanctioned, reviewed six. Independently, and even for a
command whose name IS in the closed set, `REPEAT` and `BOUNDED_LOOP` (the two
vocabulary words that name an iteration count) are `ILLEGAL_UNBOUNDED_LOOP`
when no iteration-count argument was declared -- a `` `BOUNDED_LOOP `` whose
own argument list is empty is not actually bounded, and the label on the
command must never be trusted over its own argument.

EVIDENCE TRUTH RULE, APPLIED. A statement this module does not recognize as
control-shaped (a register write, a VIP task call with no control-intent name
token, a plain `$display`) is simply ABSENT from the report -- never silently
"PASSed" and never fabricated as compliant. A source file this module cannot
read or parse is `NOT_AVAILABLE`, never a fabricated CLEAN. WAIT/POLL/SYNC/
BARRIER carry no iteration count in this project's real command.txt idiom, so
this module does not invent an unbounded-loop rule for them -- see DISCLOSED
RESIDUALS below.

DISCLOSED RESIDUALS.
  (1) The NAME-TOKEN classification of a non-exact-match macro as
      control-intended is a heuristic, exactly like
      `reference_pattern_audit.classify_wait()`'s own -- it can under- or
      over-match a macro whose name happens to contain (or omit) one of
      `CONTROL_INTENT_NAME_TOKENS`. It can only ever ADD a finding (a real
      illegal-name command it correctly caught), never remove a legitimate one
      from scrutiny, because an EXACT vocabulary match is always checked first
      and independently of the heuristic.
  (2) The iteration-count "declared" check asks only whether a non-empty
      argument token exists in the count position; it cannot prove that
      argument resolves, at elaboration, to a genuinely finite value (a
      `` `define ``d constant is accepted as declared -- resolving `` `define ``s
      is a preprocessor concern this module does not perform). A project whose
      own convention marks a literal (e.g. `-1`) as meaning "unbounded" must
      declare it via `unbounded_sentinels`; this module never invents that
      mapping since no such convention has been observed in this project's own
      evidence.
  (3) It decides nothing beyond reporting: no build, no job, no approval, and
      deliberately no stage gate -- a gate that passed on a control-command
      scan nobody ran would be worse than none.

Proven by `dv_harness_tests/test_runtime_control_commands.py` against REAL
command.txt-shaped synthetic fixture files parsed by the REAL
`reference_pattern_audit.extract_command_statements()` -- nothing here
re-parses command.txt text of its own.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

from dv_harness.reference_pattern_audit import (
    CommandStatement,
    C_CONTROL_FLOW,
    C_SYNCHRONIZATION,
    K_MACRO_CALL,
    K_MODEL_TASK_CALL,
    extract_command_statements,
)
from dv_harness.connectivity import render_markdown_table

# ---------------------------------------------------------------------------
# The closed vocabulary (the whole point of this module)
# ---------------------------------------------------------------------------

#: The ONLY legal names for a CONTROL-classified command.txt command. Closed,
#: not extensible from within this module -- extending it is a project
#: decision (a real spec/skill change), never a per-call parameter, or "closed"
#: would mean nothing.
CONTROL_VOCABULARY: Tuple[str, ...] = (
    "WAIT", "POLL", "REPEAT", "BOUNDED_LOOP", "SYNC", "BARRIER",
)

#: Of the six, the two that NAME an iteration count. Only these are subject to
#: the "no declared iteration limit" check -- WAIT/POLL/SYNC/BARRIER are
#: single blocking dispatch points in this project's real command.txt idiom,
#: not counted repetitions, and this module does not invent a bound
#: requirement for them beyond what the task asks.
LOOP_SHAPED_CONTROL_COMMANDS = frozenset({"REPEAT", "BOUNDED_LOOP"})

#: NAME-EVIDENCE tokens for classifying a macro/model-task call as
#: control-intended when its bare name is not an exact vocabulary match --
#: same convention as `reference_pattern_audit.classify_wait()`'s
#: `INTERRUPT_NAME_TOKENS`: evidence, cited on every classification, never
#: proof.
CONTROL_INTENT_NAME_TOKENS: Tuple[str, ...] = (
    "WAIT", "POLL", "REPEAT", "LOOP", "SYNC", "BARRIER",
    "RETRY", "UNTIL", "SPIN", "STALL",
)

#: The two `reference_pattern_audit` categories that already mean "native SV
#: control/sync construct" (`repeat`/`while`/`for`/`forever`/`if`/`fork`/
#: `join`/`disable`, and `wait(...)`/`@(...)`/`#...` respectively). A
#: statement landing in either is control-classified unconditionally -- raw SV
#: control syntax used directly in a command.txt IS the "unrestricted
#: scripting" this rule exists to catch, by construction.
NATIVE_CONTROL_CATEGORIES = frozenset({C_CONTROL_FLOW, C_SYNCHRONIZATION})

BASIS_EXACT_VOCABULARY_MATCH = "MACRO_NAME_EXACT_VOCABULARY_MATCH"
BASIS_NAME_TOKEN_MATCH = "MACRO_NAME_TOKEN_MATCH"
BASIS_NATIVE_SV_CONSTRUCT = "NATIVE_SV_CONTROL_CONSTRUCT"

FINDING_ILLEGAL_CONTROL_COMMAND = "ILLEGAL_CONTROL_COMMAND"
FINDING_ILLEGAL_UNBOUNDED_LOOP = "ILLEGAL_UNBOUNDED_LOOP"

STATUS_CLEAN = "CLEAN"
STATUS_VIOLATIONS_FOUND = "VIOLATIONS_FOUND"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"

_STATUS_EXIT_CODE = {STATUS_CLEAN: 0, STATUS_VIOLATIONS_FOUND: 1, STATUS_NOT_AVAILABLE: 2}

#: Recovers a NATIVE `repeat(N)` construct's own count argument.
#: `reference_pattern_audit._classify_statement()`'s `K_LOOP` branch always
#: returns `arguments=[]` (that layer never needed a native loop's bound), so
#: this is recovered here from the statement's own preserved `text` instead of
#: re-deriving that module's full call-argument splitter for one integer.
_NATIVE_REPEAT_BOUND_RE = re.compile(r"^\s*repeat\s*\(([^()]*)\)", re.IGNORECASE)

#: The leading identifier run of a `CommandStatement.name`. Needed because
#: `reference_pattern_audit._classify_statement()`'s K_LOOP/K_CONDITIONAL
#: branch (`body.split()[0]`) only strips on WHITESPACE, so a native
#: `repeat(3)`/`while(cond)` (no space before the paren) carries its whole
#: `"repeat(3)"`/`"while(cond)"` call text as `.name`, not the bare keyword --
#: that module never needed just the keyword for its own purposes, this one
#: does.
_LEADING_IDENTIFIER_RE = re.compile(r"^`?[A-Za-z_][A-Za-z0-9_]*")


def _matched_tokens(name: str, tokens: Sequence[str]) -> list:
    lowered = (name or "").lower()
    return [t for t in tokens if t.lower() in lowered]


def _bare_command_name(stmt: CommandStatement) -> str:
    """The dispatched command name with any backtick, any `.task` suffix (a
    `K_MODEL_TASK_CALL`'s `` `INST.task``` form -- same convention
    `reference_pattern_audit.classify_command_roles()` uses for its own
    `target_vip` field), and any trailing call-argument text stripped down
    to the leading identifier (see `_LEADING_IDENTIFIER_RE` above)."""
    name = (stmt.name or "").split(".")[0]
    m = _LEADING_IDENTIFIER_RE.match(name)
    bare = m.group(0) if m else name
    return bare.lstrip("`")


def _declared_loop_bound(stmt: CommandStatement) -> Optional[str]:
    """The text of the declared iteration-count argument, or None when none
    was declared. A macro-shaped command's arguments were already split by
    the real parser (`stmt.arguments`); a NATIVE `repeat(N)` is recovered from
    `stmt.text` via `_NATIVE_REPEAT_BOUND_RE` (see its comment above)."""
    if stmt.arguments:
        arg = stmt.arguments[0].strip()
        return arg or None
    m = _NATIVE_REPEAT_BOUND_RE.match(stmt.text or "")
    if not m:
        return None
    arg = m.group(1).strip()
    return arg or None


@dataclass
class ControlCommandRecord:
    """One CONTROL-classified command.txt command and its verdict against
    the closed vocabulary / unbounded-loop rule."""
    command_name: str
    classification_basis: str
    matched_token: str
    in_vocabulary: bool
    loop_bound_declared: Optional[bool]
    declared_bound_argument: str
    file: str
    line: int
    text: str
    findings: list = field(default_factory=list)

    @property
    def evidence(self) -> str:
        return f"{self.file}:{self.line}"

    def to_dict(self) -> dict:
        return {
            "command_name": self.command_name,
            "classification_basis": self.classification_basis,
            "matched_token": self.matched_token,
            "in_vocabulary": self.in_vocabulary,
            "loop_bound_declared": self.loop_bound_declared,
            "declared_bound_argument": self.declared_bound_argument,
            "findings": list(self.findings),
            "evidence": self.evidence,
            "text": self.text,
        }


def classify_control_commands(statements: Sequence[CommandStatement]) -> list:
    """One `ControlCommandRecord` per statement classified as a CONTROL
    command, out of real `CommandStatement`s (from
    `reference_pattern_audit.extract_command_statements()`). A statement this
    function does not classify as CONTROL is absent from the result -- it is
    out of this check's scope, never silently treated as compliant."""
    records: list = []
    for stmt in statements:
        bare = _bare_command_name(stmt)
        upper = bare.upper()
        basis = None
        matched_token = ""

        if stmt.category in NATIVE_CONTROL_CATEGORIES:
            basis = BASIS_NATIVE_SV_CONSTRUCT
            matched_token = bare
        elif stmt.kind in (K_MACRO_CALL, K_MODEL_TASK_CALL):
            if upper in CONTROL_VOCABULARY:
                basis = BASIS_EXACT_VOCABULARY_MATCH
                matched_token = upper
            else:
                tokens = _matched_tokens(bare, CONTROL_INTENT_NAME_TOKENS)
                if tokens:
                    basis = BASIS_NAME_TOKEN_MATCH
                    matched_token = tokens[0]

        if basis is None:
            continue

        in_vocab = upper in CONTROL_VOCABULARY
        findings: list = []
        if not in_vocab:
            findings.append(FINDING_ILLEGAL_CONTROL_COMMAND)

        bound_declared: Optional[bool] = None
        bound_arg = ""
        if upper in LOOP_SHAPED_CONTROL_COMMANDS:
            arg = _declared_loop_bound(stmt)
            bound_declared = arg is not None
            bound_arg = arg or ""
            if not bound_declared:
                findings.append(FINDING_ILLEGAL_UNBOUNDED_LOOP)

        records.append(ControlCommandRecord(
            command_name=upper, classification_basis=basis,
            matched_token=matched_token, in_vocabulary=in_vocab,
            loop_bound_declared=bound_declared,
            declared_bound_argument=bound_arg,
            file=stmt.file, line=stmt.line, text=stmt.text,
            findings=findings,
        ))
    return records


def analyze_control_commands(
        source: Union[str, Path, Sequence[CommandStatement]]) -> dict:
    """Full report over one command.txt-like file (a path, parsed by the
    REAL `reference_pattern_audit.extract_command_statements()`) or an
    already-parsed `CommandStatement` list. NOT_AVAILABLE, never a fabricated
    CLEAN, when the source cannot be read or parsed."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            return {
                "status": STATUS_NOT_AVAILABLE,
                "reason": f"NO_SUCH_FILE:{path}",
                "source": str(path), "statements_scanned": 0,
                "control_classified_count": 0,
                "illegal_control_command_count": 0,
                "illegal_unbounded_loop_count": 0,
                "records": [],
            }
        try:
            statements = extract_command_statements(path)
        except OSError as exc:
            return {
                "status": STATUS_NOT_AVAILABLE,
                "reason": f"UNREADABLE_FILE:{exc}",
                "source": str(path), "statements_scanned": 0,
                "control_classified_count": 0,
                "illegal_control_command_count": 0,
                "illegal_unbounded_loop_count": 0,
                "records": [],
            }
        source_label = str(path)
    else:
        statements = list(source)
        source_label = "<supplied-statements>"

    records = classify_control_commands(statements)
    illegal_command = [r for r in records if FINDING_ILLEGAL_CONTROL_COMMAND in r.findings]
    illegal_unbounded = [r for r in records if FINDING_ILLEGAL_UNBOUNDED_LOOP in r.findings]
    status = STATUS_VIOLATIONS_FOUND if (illegal_command or illegal_unbounded) else STATUS_CLEAN

    return {
        "status": status,
        "source": source_label,
        "statements_scanned": len(statements),
        "control_classified_count": len(records),
        "illegal_control_command_count": len(illegal_command),
        "illegal_unbounded_loop_count": len(illegal_unbounded),
        "records": [r.to_dict() for r in records],
    }


def render_control_commands_markdown(report: dict) -> str:
    """Markdown report, via the repo's one parameterized table renderer
    (`connectivity.render_markdown_table`) -- never a hand-rolled table."""
    if report.get("status") == STATUS_NOT_AVAILABLE:
        return (f"CONTROL command vocabulary check: NOT_AVAILABLE "
                f"({report.get('reason', 'unknown reason')})")
    rows = []
    for rec in report.get("records", []):
        if rec["loop_bound_declared"] is None:
            loop_bound = "N/A"
        elif rec["loop_bound_declared"]:
            loop_bound = f"DECLARED:{rec['declared_bound_argument']}"
        else:
            loop_bound = "UNDECLARED"
        rows.append({
            "command": rec["command_name"],
            "basis": rec["classification_basis"],
            "matched_token": rec["matched_token"],
            "in_vocabulary": "YES" if rec["in_vocabulary"] else "NO",
            "loop_bound": loop_bound,
            "findings": ", ".join(rec["findings"]) or "-",
            "evidence": rec["evidence"],
        })
    table = render_markdown_table(
        [("command", "Command"), ("basis", "Classification Basis"),
         ("matched_token", "Matched Token"), ("in_vocabulary", "In Vocabulary"),
         ("loop_bound", "Loop Bound"), ("findings", "Findings"),
         ("evidence", "Evidence")],
        rows, empty_note="(no CONTROL-classified commands found)")
    header = (f"CONTROL command vocabulary check: {report['status']} "
              f"(scanned {report['statements_scanned']} statement(s), "
              f"{report['control_classified_count']} CONTROL-classified, "
              f"{report['illegal_control_command_count']} illegal command(s), "
              f"{report['illegal_unbounded_loop_count']} unbounded loop(s))")
    return header + "\n\n" + table


def execute_verb(command_file: str, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `dv-harness runtime-control-commands` and
    `python -m dv_harness.runtime_control_commands`. Returns (text, exit_code)."""
    report = analyze_control_commands(command_file)
    text = json.dumps(report, indent=2) if as_json else render_control_commands_markdown(report)
    return text, _STATUS_EXIT_CODE[report["status"]]


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.runtime_control_commands",
        description="Validate that every CONTROL-classified command.txt/pattern "
                    "command belongs to the closed vocabulary WAIT/POLL/REPEAT/"
                    "BOUNDED_LOOP/SYNC/BARRIER, and that REPEAT/BOUNDED_LOOP declare "
                    "a real iteration limit. Reads one file; verifies no behavior.")
    ap.add_argument("--command-file", required=True,
                     help="A command.txt/pattern file to parse and check.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.command_file, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
