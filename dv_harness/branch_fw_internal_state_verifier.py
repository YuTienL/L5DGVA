"""dv_harness/branch_fw_internal_state_verifier.py -- verifies `branch_fw`'s
OWN internal ARM/WAIT/WAKE/DECODE/CLEAR interrupt-service loop against real
generated `command.txt`/pattern text.

GAP THIS CLOSES. `pattern_runtime_state_machine.py` tracks a whole PATTERN's
own top-level execution phase (CREATED..RUNNING..PASS/FAIL) and says, in its
own module docstring, exactly what it deliberately does NOT do: "this module
tracks one pattern's OWN execution phase, not `branch_fw`'s internal
ARM/WAIT/WAKE/DECODE/CLEAR cycling (a separate, already-generalized loop
`interrupt-event-dispatch/SKILL.md` owns)". `runtime_event_registry.py`
likewise only carries a CALLER-DECLARED event set with no notion of the
five-state shape at all, and says so in its own docstring ("this module does
not ... decide whether an event 'really' occurred"). Nothing in this repo
ever opened a real generated pattern's own text and checked that the five
states `.claude/skills/CORE/interrupt-event-dispatch/SKILL.md`'s worked
example names (ARM -> WAIT -> WAKE -> DECODE -> CLEAR) are genuinely present,
in that order -- a repo-wide grep for `ARM.*WAIT.*WAKE.*DECODE.*CLEAR`
confirms every existing hit is either that SKILL.md's own prose, a citation
of it inside `pattern_runtime_state_machine.py`'s "why this loop is out of
scope here" paragraph, or a routing citation in
`de_command_style_learning.py`'s FW-ownership guess -- never a verifier.

THE FIVE STATES, grounded in the SKILL's own worked example (section "Real
worked example (USB, DWC_usb31 wrapper)"), never invented here:
  1. ARM    -- an ordinary CPU-write task writes the wrapper's interrupt-
     enable register.
  2. WAIT   -- a per-instance task does a true event-driven `wait` directly
     on real RTL signals.
  3. WAKE   -- the per-instance service loop's outer `forever` wakes via a
     bounded `fork { wait(pending) } / { #WATCHDOG } join_any` race.
  4. DECODE -- on wake, read the status/count registers.
  5. CLEAR  -- clear only the bit(s) actually serviced, via a write-1-to-
     clear write (never the "blanket-clear an aggregated W1C register" trap
     that same SKILL names).

REUSE OVER REINVENT, exactly as this item instructs ("reuse
command_task_trace.py's declaration-level trace machinery"). This module
re-derives NOTHING that `command_task_trace.py` or `reference_pattern_audit.py`
already do:
  * `command_task_trace.trace_command()`'s TASK_MACRO leg is the ONLY thing
    that decides how a branch_fw command/task NAME resolves inside a real
    generated environment (`env_dir`) -- direct declaration, case-dispatch
    handler, `` `define `` macro redirect, or `patterns_registry`-shaped file
    mapping. A leg reported AMBIGUOUS or NOT_FOUND is reported as exactly
    that here too, never guessed past -- the identical discipline
    `cpuread_byte_shift_checker.py` already established for reusing this same
    leg, and this module's own `_locate_task_body()` is that module's
    `_locate_task_body()`/`_find_task_body_by_name()` shape, reusing
    `command_task_trace._TASK_BODY_RE_TMPL` directly rather than a second
    "what does a task declaration look like" regex.
  * Statement extraction and classification over the located body is entirely
    `reference_pattern_audit.extract_command_statements()`/`classify_wait()`
    -- this module's WAIT-state evidence IS that function's own
    `INTERRUPT_EVENT_WAIT` verdict (name-token-cited, per that module's own
    `INTERRUPT_NAME_TOKENS`), never a second interrupt-vs-plain-wait
    classifier. `de_command_style_learning.py`'s own FW-ownership rule
    ("branch_fw owns the ARM/WAIT/WAKE/DECODE/CLEAR event loop") is exactly
    this same real fact reused one more time: requiring the WAIT state's own
    evidence to be a real `classify_wait()` INTERRUPT_EVENT_WAIT is what
    grounds "this is genuinely branch_fw's own loop", not a bare textual
    resemblance to five arbitrary words.

EVIDENCE TRUTH RULE, applied per state, never averaged into a fabricated
"mostly correct" verdict:
  * ARM -- a real `REGISTER_WRITE` statement occurring before the WAIT
    state's own line, whose comment/arguments cite an arm/enable/trigger/
    mask token (`ARM_NAME_TOKENS`, matched and cited the same
    `_matched_tokens()`-style evidence `reference_pattern_audit.classify_wait()`
    already uses for its own token match). No token match anywhere before
    WAIT -> `UNKNOWN`, never a guessed "the nearest write must be it".
  * WAIT -- the first statement `reference_pattern_audit.classify_wait()`
    itself classifies `INTERRUPT_EVENT_WAIT`. No such wait anywhere in the
    body -> `UNKNOWN`, and every state defined relative to WAIT (WAKE,
    DECODE, CLEAR) is `UNKNOWN` too -- there is no anchor to place them
    against.
  * WAKE -- the worked example's own specific shape: a `fork`/`join_any`
    pair genuinely ENCLOSING the WAIT statement (a real bracket-matched
    fork/join pair over the body's own statement stream, never assumed from
    program order). A `fork`/plain-`join`/`join_none` pair, or no enclosing
    fork at all, is `UNKNOWN` -- this module never claims a plain `wait(...)`
    statement's own textual completion IS a documented "WAKE" event; the
    SKILL's own worked example ties WAKE specifically to the bounded
    `join_any` race, and nothing else is credited.
  * DECODE -- the first `REGISTER_READ` statement after the WAKE anchor
    (falling back to the WAIT anchor when WAKE is `UNKNOWN`, since DECODE's
    own SKILL wording -- "on wake, read the status/count registers" -- still
    has to happen somewhere after the event fired even when this module
    cannot see the specific WAKE mechanism). None found -> `UNKNOWN`.
  * CLEAR -- a `REGISTER_WRITE` after DECODE, evidenced either by targeting
    the SAME register address DECODE just read (the real W1C "clear what
    was just read" shape) or by an arm/clear/ack/w1c token citation in its
    own comment. Neither -> `UNKNOWN`. `reference_pattern_audit.
    build_ordering_constraints()` deliberately never emits this relation
    ("read-then-anything carries no ordering obligation" -- its own comment)
    precisely because a read-then-write pair is not always a clear; this
    module is the first thing in this repo that decides that question, for
    this one specific, cited purpose.

ORDER VERIFICATION, worst-wins per this project's own house style: a genuine
order violation among the states this module COULD determine (two states
found but in the wrong relative line order) always outranks an honest
"incomplete" report -- a defect that was actually found is reported as a
defect, never diluted by also being partial. Only when every determinable
state's own line is strictly ascending in ARM/WAIT/WAKE/DECODE/CLEAR order,
AND all five states were determined, is the loop reported genuinely verified.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from . import command_task_trace
from . import reference_pattern_audit as rpa

# --- the five states -----------------------------------------------------------

STATE_ARM = "ARM"
STATE_WAIT = "WAIT"
STATE_WAKE = "WAKE"
STATE_DECODE = "DECODE"
STATE_CLEAR = "CLEAR"
STATE_ORDER: tuple = (STATE_ARM, STATE_WAIT, STATE_WAKE, STATE_DECODE, STATE_CLEAR)

FINDING_REACHED = "REACHED"
FINDING_UNKNOWN = "UNKNOWN"

# Small, disclosed, cited-when-matched token vocabularies -- the same
# "matched token is the actual evidence, cited on every classification"
# discipline `reference_pattern_audit.INTERRUPT_NAME_TOKENS` already uses.
# Deliberately narrow (never a bare "en", which "event"/"when"/"listen" would
# all falsely contain) so a match is real, cited evidence, not a coincidence.
ARM_NAME_TOKENS: tuple = ("arm", "_en_", "_en=", "enable", "trigger", "trig_", "unmask")
CLEAR_NAME_TOKENS: tuple = ("clear", "_clr", "clr_", "ack", "w1c")

# Overall verification statuses.
STATUS_VERIFIED_IN_ORDER = "ALL_STATES_VERIFIED_IN_ORDER"
STATUS_OUT_OF_ORDER = "STATES_OUT_OF_ORDER"
STATUS_INCOMPLETE = "STATES_INCOMPLETE"
STATUS_COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
STATUS_AMBIGUOUS_TASK_RESOLUTION = "AMBIGUOUS_TASK_RESOLUTION"
STATUS_TASK_BODY_NOT_LOCATED = "TASK_BODY_NOT_LOCATED"
STATUS_BLOCKED = "BLOCKED"

# Statuses that represent a real, decided verdict (as opposed to "this module
# could not determine an answer at all").
DECIDED_STATUSES = (STATUS_VERIFIED_IN_ORDER, STATUS_OUT_OF_ORDER, STATUS_INCOMPLETE)


class BranchFwStateVerifierError(ValueError):
    """Programmer misuse (e.g. an empty statement list handed to the core
    verifier with no way to even attempt WAIT detection), never a could-not-
    decide outcome -- those are reported as findings with one of the
    non-decided statuses above, not raised."""


@dataclass
class StateFinding:
    state: str
    status: str  # REACHED | UNKNOWN
    line: Optional[int] = None
    statement_kind: Optional[str] = None
    statement_text: Optional[str] = None
    matched_tokens: list = field(default_factory=list)
    basis: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BranchFwLoopVerification:
    command_name: str
    status: str
    task_body_source: Optional[str] = None
    task_name: Optional[str] = None
    states: List[StateFinding] = field(default_factory=list)
    order_violations: list = field(default_factory=list)
    reason: Optional[str] = None
    task_macro_citations: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def state(self, name: str) -> Optional[StateFinding]:
        for s in self.states:
            if s.state == name:
                return s
        return None


# --- reused task-resolution machinery (mirrors cpuread_byte_shift_checker.py) --

def _read_source_files(env_path: Path) -> dict:
    """Read every real source file under `env_dir` this repo's own resolver
    already scans (`command_task_trace.SOURCE_EXTENSIONS`) -- a plain,
    read-only file read, not a second resolution pass."""
    out: dict = {}
    for p in sorted(env_path.rglob("*")):
        if p.is_file() and p.suffix.lower() in command_task_trace.SOURCE_EXTENSIONS:
            try:
                out[str(p)] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return out


def _find_task_body_by_name(name: str, files_text: dict):
    """First `task ... <name> ... endtask` span found -- reuses
    `command_task_trace._TASK_BODY_RE_TMPL` verbatim (the exact regex that
    module's own leg-2 macro-redirect follow-through already uses), rather
    than a second "what does a task declaration look like" regex. Returns
    (file_path, match_object) or (None, None)."""
    pat = re.compile(command_task_trace._TASK_BODY_RE_TMPL.format(re.escape(name)), re.DOTALL)
    for path, text in files_text.items():
        m = pat.search(text)
        if m:
            return path, m
    return None, None


_MACRO_TARGET_RE_TMPL = r"`define\s+{0}\s+(\S+)"


def _macro_redirect_target(command_name: str, define_snippet: str) -> Optional[str]:
    m = re.search(_MACRO_TARGET_RE_TMPL.format(re.escape(command_name)), define_snippet)
    return m.group(1) if m else None


def _task_name_from_target(target: str) -> str:
    return target.rsplit(".", 1)[-1]


def _line_span(text: str, start: int, end: int) -> tuple:
    """1-indexed (start_line, end_line) for a byte-offset span in `text`."""
    start_line = text.count("\n", 0, start) + 1
    end_line = text.count("\n", 0, end) + 1
    return start_line, end_line


def _locate_task_body(command_name: str, citations, files_text: dict):
    """The ONE new step this module adds on top of `trace_command()`'s
    TASK_MACRO leg: given that leg's own real citations, follow AT MOST one
    more hop to locate the real task body's LINE SPAN (never its full text
    alone -- `reference_pattern_audit.extract_command_statements()` needs to
    be run over the whole file, and statements are then filtered to this
    span, so this module never re-parses a substring independently).

    Returns (file_path, resolved_task_name, start_line, end_line) or None.
    """
    by_kind: dict = {}
    for c in citations:
        by_kind.setdefault(c.kind, []).append(c)

    if "task_declaration" in by_kind:
        c = by_kind["task_declaration"][0]
        text = files_text.get(c.file_path, "")
        _, m = _find_task_body_by_name(command_name, {c.file_path: text})
        if m:
            start_line, end_line = _line_span(text, m.start(), m.end())
            return c.file_path, command_name, start_line, end_line

    if "handler_task_declaration" in by_kind:
        c = by_kind["handler_task_declaration"][0]
        handler_name = c.detail or command_name
        path, m = _find_task_body_by_name(handler_name, files_text)
        if m:
            start_line, end_line = _line_span(files_text[path], m.start(), m.end())
            return path, handler_name, start_line, end_line

    if "macro_definition" in by_kind:
        c = by_kind["macro_definition"][0]
        target = _macro_redirect_target(command_name, c.snippet)
        if target:
            task_name = _task_name_from_target(target)
            path, m = _find_task_body_by_name(task_name, files_text)
            if m:
                start_line, end_line = _line_span(files_text[path], m.start(), m.end())
                return path, task_name, start_line, end_line

    if "registry_mapped_file" in by_kind:
        c = by_kind["registry_mapped_file"][0]
        text = files_text.get(c.file_path)
        if text:
            _, m = _find_task_body_by_name(command_name, {c.file_path: text})
            if m:
                start_line, end_line = _line_span(text, m.start(), m.end())
                return c.file_path, command_name, start_line, end_line
            # A `patterns_registry`-mapped file's own content IS the pattern
            # body -- no `task ... endtask` wrapper is guaranteed. The whole
            # file is the body.
            end_line = text.count("\n") + 1
            return c.file_path, command_name, 1, end_line

    return None


# --- per-state detection over an already-extracted statement stream -----------

def _matched(text: str, tokens: tuple) -> list:
    lowered = (text or "").lower()
    return [t for t in tokens if t in lowered]


def _find_wait(statements: list):
    """First statement `reference_pattern_audit.classify_wait()` itself
    classifies INTERRUPT_EVENT_WAIT. Returns (statement, classify_wait_result)
    or (None, None)."""
    for idx, s in enumerate(statements):
        if s.kind in (rpa.K_WAIT_CONDITION, rpa.K_EVENT_WAIT):
            result = rpa.classify_wait(s)
            if result["wait_class"] == "INTERRUPT_EVENT_WAIT":
                return idx, s, result
    return None, None, None


def _find_arm(statements: list, wait_line: Optional[int]):
    candidates = [s for s in statements
                  if s.kind == rpa.K_REGISTER_WRITE
                  and (wait_line is None or s.line < wait_line)]
    best = None
    best_tokens: list = []
    for s in candidates:
        haystack = (s.comment or "") + " " + " ".join(s.arguments)
        tokens = _matched(haystack, ARM_NAME_TOKENS)
        if tokens and (best is None or s.line > best.line):
            best, best_tokens = s, tokens
    if best is None:
        scope = (f"before the WAIT state's own line (line {wait_line})"
                  if wait_line is not None else "in this body (no WAIT state "
                  "was found to anchor the search)")
        reason = (f"no REGISTER_WRITE statement {scope} cites an "
                   f"arm/enable/trigger/mask token in its comment or arguments")
        return StateFinding(state=STATE_ARM, status=FINDING_UNKNOWN, reason=reason)
    return StateFinding(
        state=STATE_ARM, status=FINDING_REACHED, line=best.line,
        statement_kind=best.kind, statement_text=best.text,
        matched_tokens=best_tokens,
        basis="SIGNAL_NAME_TOKEN_MATCH",
        reason=f"{best.file}:{best.line} cites {best_tokens}")


def _enclosing_fork_join(statements: list, idx: int):
    """(fork_stmt, join_stmt) genuinely bracketing `statements[idx]`, found
    by a real bracket match over the body's own FORK/JOIN statement stream
    -- never assumed from mere program order. (None, None) when no enclosing
    fork exists in this body at all."""
    depth = 0
    fork = None
    for i in range(idx - 1, -1, -1):
        s = statements[i]
        if s.kind == rpa.K_JOIN:
            depth += 1
        elif s.kind == rpa.K_FORK:
            if depth == 0:
                fork = s
                break
            depth -= 1
    if fork is None:
        return None, None
    depth = 0
    join = None
    for i in range(idx + 1, len(statements)):
        s = statements[i]
        if s.kind == rpa.K_FORK:
            depth += 1
        elif s.kind == rpa.K_JOIN:
            if depth == 0:
                join = s
                break
            depth -= 1
    return fork, join


def _find_wake(statements: list, wait_idx: Optional[int]):
    if wait_idx is None:
        return StateFinding(state=STATE_WAKE, status=FINDING_UNKNOWN,
                             reason="no WAIT state was found to anchor a WAKE search against")
    fork, join = _enclosing_fork_join(statements, wait_idx)
    if fork is None:
        return StateFinding(
            state=STATE_WAKE, status=FINDING_UNKNOWN,
            reason=("the WAIT statement is not enclosed by any fork/join "
                    "block in this pattern text; this module credits WAKE "
                    "only to the worked example's own bounded "
                    "fork{...}join_any race, never to a plain wait's own "
                    "textual completion"))
    if join is None or join.name != "join_any":
        found = join.name if join is not None else "<no matching join found>"
        return StateFinding(
            state=STATE_WAKE, status=FINDING_UNKNOWN,
            line=fork.line, statement_kind=fork.kind, statement_text=fork.text,
            reason=(f"a fork block encloses the WAIT statement, but its "
                    f"closing construct is {found!r}, not the documented "
                    f"'join_any' race the worked example requires"))
    return StateFinding(
        state=STATE_WAKE, status=FINDING_REACHED, line=join.line,
        statement_kind=join.kind, statement_text=join.text,
        basis="FORK_JOIN_ANY_ENCLOSES_WAIT",
        reason=(f"fork at {fork.file}:{fork.line} closes with 'join_any' at "
                f"{join.file}:{join.line}, enclosing the WAIT statement"))


def _find_decode(statements: list, anchor_line: Optional[int]):
    if anchor_line is None:
        return StateFinding(state=STATE_DECODE, status=FINDING_UNKNOWN,
                             reason="no WAIT/WAKE anchor was found to search for DECODE after")
    for s in statements:
        if s.kind == rpa.K_REGISTER_READ and s.line > anchor_line:
            return StateFinding(
                state=STATE_DECODE, status=FINDING_REACHED, line=s.line,
                statement_kind=s.kind, statement_text=s.text,
                basis="FIRST_REGISTER_READ_AFTER_WAIT_OR_WAKE",
                reason=f"{s.file}:{s.line}")
    return StateFinding(
        state=STATE_DECODE, status=FINDING_UNKNOWN,
        reason="no REGISTER_READ statement found after the WAIT/WAKE anchor")


def _find_clear(statements: list, decode_stmt):
    if decode_stmt is None:
        return StateFinding(state=STATE_CLEAR, status=FINDING_UNKNOWN,
                             reason="no DECODE state was found to search for CLEAR after")
    for s in statements:
        if s.kind != rpa.K_REGISTER_WRITE or s.line <= decode_stmt.line:
            continue
        if decode_stmt.address and s.address and s.address == decode_stmt.address:
            return StateFinding(
                state=STATE_CLEAR, status=FINDING_REACHED, line=s.line,
                statement_kind=s.kind, statement_text=s.text,
                basis="SAME_ADDRESS_AS_DECODE_READ",
                reason=(f"{s.file}:{s.line} writes the same address "
                        f"({s.address}) DECODE read at "
                        f"{decode_stmt.file}:{decode_stmt.line}"))
        haystack = (s.comment or "") + " " + " ".join(s.arguments)
        tokens = _matched(haystack, CLEAR_NAME_TOKENS)
        if tokens:
            return StateFinding(
                state=STATE_CLEAR, status=FINDING_REACHED, line=s.line,
                statement_kind=s.kind, statement_text=s.text,
                matched_tokens=tokens, basis="SIGNAL_NAME_TOKEN_MATCH",
                reason=f"{s.file}:{s.line} cites {tokens}")
    return StateFinding(
        state=STATE_CLEAR, status=FINDING_UNKNOWN,
        reason=("no REGISTER_WRITE statement after DECODE targets the same "
                "address DECODE read, and none cites a clear/ack/w1c token"))


def _order_violations(states: List[StateFinding]) -> list:
    """Every consecutive pair of REACHED states (in STATE_ORDER) whose lines
    are not strictly ascending -- a real, cited defect, never averaged away."""
    reached = {s.state: s for s in states if s.status == FINDING_REACHED and s.line is not None}
    violations = []
    ordered = [s for s in STATE_ORDER if s in reached]
    for prev_name, next_name in zip(ordered, ordered[1:]):
        prev, nxt = reached[prev_name], reached[next_name]
        if not (prev.line < nxt.line):
            violations.append(
                f"{prev_name} (line {prev.line}) does not precede "
                f"{next_name} (line {nxt.line})")
    return violations


def verify_branch_fw_loop_in_statements(statements: list, *,
                                         command_name: str = "") -> BranchFwLoopVerification:
    """Core verifier over an already-extracted, already-filtered statement
    stream (typically one branch_fw task body's own statements, in line
    order). Never touches a file itself -- callers with a whole pattern file
    dedicated to one branch_fw loop may pass
    `reference_pattern_audit.extract_command_statements(path)` directly."""
    wait_idx, wait_stmt, wait_result = _find_wait(statements)
    wait_finding = (
        StateFinding(state=STATE_WAIT, status=FINDING_UNKNOWN,
                     reason=("no wait/event-wait statement in this body was "
                             "classified INTERRUPT_EVENT_WAIT by "
                             "reference_pattern_audit.classify_wait() -- "
                             "without a real interrupt-classified wait, this "
                             "is not provably branch_fw's own event loop"))
        if wait_stmt is None else
        StateFinding(state=STATE_WAIT, status=FINDING_REACHED, line=wait_stmt.line,
                     statement_kind=wait_stmt.kind, statement_text=wait_stmt.text,
                     matched_tokens=wait_result["matched_tokens"],
                     basis=wait_result["basis"],
                     reason=f"{wait_stmt.file}:{wait_stmt.line} cites "
                            f"{wait_result['matched_tokens']}")
    )

    arm_finding = _find_arm(statements, wait_stmt.line if wait_stmt else None)
    wake_finding = _find_wake(statements, wait_idx)
    decode_anchor = wake_finding.line if wake_finding.status == FINDING_REACHED else (
        wait_stmt.line if wait_stmt else None)
    decode_finding = _find_decode(statements, decode_anchor)
    decode_stmt = None
    if decode_finding.status == FINDING_REACHED:
        decode_stmt = next((s for s in statements if s.line == decode_finding.line
                             and s.kind == rpa.K_REGISTER_READ), None)
    clear_finding = _find_clear(statements, decode_stmt)

    states = [arm_finding, wait_finding, wake_finding, decode_finding, clear_finding]
    violations = _order_violations(states)
    all_reached = all(s.status == FINDING_REACHED for s in states)

    if violations:
        status = STATUS_OUT_OF_ORDER
        reason = "; ".join(violations)
    elif all_reached:
        status = STATUS_VERIFIED_IN_ORDER
        reason = None
    else:
        missing = [s.state for s in states if s.status == FINDING_UNKNOWN]
        status = STATUS_INCOMPLETE
        reason = f"state(s) {missing} could not be determined from this pattern text"

    return BranchFwLoopVerification(
        command_name=command_name, status=status, states=states,
        order_violations=violations, reason=reason)


def verify_branch_fw_loop_in_file(path) -> BranchFwLoopVerification:
    """Convenience: the whole file IS the branch_fw body (a dedicated pattern
    file, or a `patterns_registry`-mapped body already resolved elsewhere)."""
    path = Path(path)
    statements = rpa.extract_command_statements(path)
    return verify_branch_fw_loop_in_statements(statements, command_name=path.name)


def verify_branch_fw_loop_from_env(env_dir, command_name: str, *,
                                    use_verible: bool = False) -> BranchFwLoopVerification:
    """Resolve `command_name` inside a real generated environment via
    `command_task_trace.trace_command()`'s TASK_MACRO leg, locate its real
    task body, and verify the ARM/WAIT/WAKE/DECODE/CLEAR loop within it."""
    env_path = Path(env_dir)
    files_text = _read_source_files(env_path)
    trace = command_task_trace.trace_command(command_name, env_path, use_verible=use_verible)

    if trace.status == command_task_trace.STATUS_BLOCKED:
        return BranchFwLoopVerification(
            command_name=command_name, status=STATUS_BLOCKED, reason=trace.reason)

    leg1 = trace.legs.get(command_task_trace.LEG_TASK_MACRO)
    if leg1 is None or leg1.status == command_task_trace.LEG_NOT_FOUND:
        return BranchFwLoopVerification(
            command_name=command_name, status=STATUS_COMMAND_NOT_FOUND,
            reason=(leg1.reason if leg1 is not None else trace.reason))

    if leg1.status == command_task_trace.LEG_AMBIGUOUS:
        return BranchFwLoopVerification(
            command_name=command_name, status=STATUS_AMBIGUOUS_TASK_RESOLUTION,
            reason=leg1.reason,
            task_macro_citations=[c.to_dict() for c in leg1.citations])

    located = _locate_task_body(command_name, leg1.citations, files_text)
    if located is None:
        return BranchFwLoopVerification(
            command_name=command_name, status=STATUS_TASK_BODY_NOT_LOCATED,
            reason=("the task-macro leg resolved, but no real task body "
                    "could be located by following its citation(s) one "
                    "level further (direct declaration, case-dispatch "
                    "handler, macro-redirect target, or registry-mapped "
                    "file)"),
            task_macro_citations=[c.to_dict() for c in leg1.citations])

    task_file, task_name, start_line, end_line = located
    all_statements = rpa.extract_command_statements(Path(task_file))
    body_statements = [s for s in all_statements if start_line <= s.line <= end_line]

    result = verify_branch_fw_loop_in_statements(body_statements, command_name=command_name)
    result.task_body_source = task_file
    result.task_name = task_name
    result.task_macro_citations = [c.to_dict() for c in leg1.citations]
    return result


# --- rendering / exit-code plumbing --------------------------------------------

def format_verification(v: BranchFwLoopVerification) -> str:
    lines = [f"{v.command_name} -> {v.status}" + (f" ({v.reason})" if v.reason else "")]
    if v.task_body_source:
        lines.append(f"  task_body_source: {v.task_body_source} "
                      f"(resolved task name: {v.task_name})")
    for s in v.states:
        line = f"  [{s.state}] {s.status}"
        if s.line is not None:
            line += f" @line {s.line}"
        if s.reason:
            line += f" -- {s.reason}"
        lines.append(line)
    return "\n".join(lines)


def overall_exit_code(verifications) -> int:
    if any(v.status == STATUS_OUT_OF_ORDER for v in verifications):
        return 1
    if any(v.status != STATUS_VERIFIED_IN_ORDER for v in verifications):
        return 2
    return 0


# --- standalone front door (no `dv-harness` CLI verb; `cli.py`/`gates.py` are
# out of this task's own scope) --------------------------------------------

def main(argv: Optional[list] = None) -> int:
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.branch_fw_internal_state_verifier",
        description=("Verify branch_fw's own internal ARM/WAIT/WAKE/DECODE/CLEAR "
                     "interrupt-service loop against real generated command.txt/"
                     "pattern text. Runs nothing; reads only."))
    ap.add_argument("--env-dir", help="a real generated environment directory "
                     "(used with --command)")
    ap.add_argument("--command", action="append", dest="commands", default=None,
                     help="branch_fw command/task name to resolve inside --env-dir; "
                          "may be repeated")
    ap.add_argument("--file", action="append", dest="files", default=None,
                     help="a whole command.txt/pattern file that IS one branch_fw "
                          "body; may be repeated")
    ap.add_argument("--no-verible", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not args.commands and not args.files:
        ap.error("supply --env-dir/--command, and/or --file")

    verifications: list = []
    if args.commands:
        if not args.env_dir:
            ap.error("--command requires --env-dir")
        for name in args.commands:
            verifications.append(verify_branch_fw_loop_from_env(
                args.env_dir, name, use_verible=not args.no_verible))
    for f in (args.files or []):
        verifications.append(verify_branch_fw_loop_in_file(f))

    if args.json:
        print(_json.dumps([v.to_dict() for v in verifications], indent=2))
    else:
        for v in verifications:
            print(format_verification(v))
    return overall_exit_code(verifications)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
