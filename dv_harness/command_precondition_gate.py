"""dv_harness/command_precondition_gate.py -- validates a command's DECLARED
preconditions against `runtime_event_registry`'s CURRENT event state, before
dispatch.

GAP THIS CLOSES. `runtime_event_registry.py` tracks NAMED RUNTIME EVENTS
(GLOBAL_READY/DUT_READY/.../CHECK_DONE -- illustrative, caller-declared, never
hardcoded) with REQUIRES/WAITS_FOR/TRIGGERS/UNBLOCKS dependency propagation,
and answers "what is this EVENT's status". Nothing in this repo answered the
adjacent, real question a command dispatcher must ask before launching a
`block`/`branch_a*`/`branch_fw`/`branch_b*` task
(`.claude/skills/CORE/branch-mapper/SKILL.md`'s Initialization Task Hierarchy,
`.claude/skills/CORE/pattern-architecture/SKILL.md`'s five-layer shape): "does
THIS COMMAND's own declared precondition SET currently hold, given the
registry's real event state?" A repo-wide search for "precondition gate" /
"dispatch gate" over `dv_harness/` found no code joining a command's own
declared prerequisite names to the registry's real event states --
`command_error_taxonomy.py` classifies a dispatch's FAILURE text after the
fact, and `init_seq.py`'s `evaluate_gate2_preconditions()` is a
DIFFERENT, narrower mode-bit/register precondition check for connectivity
Gate 2, not a general per-command runtime-event precondition gate.

WHAT THIS IS. A command DECLARES a set of precondition NAMES (GLOBAL_READY,
DUT_READY, FW_READY, VIP_READY, MODE_VALID, RESET_DEASSERTED, PHY_READY below
are illustrative examples only, matching this repo's own `block`(GLOBAL_READY)/
`branch_a*`(DUT_READY per port)/`branch_fw`(FW_READY/RESET_DEASSERTED)/
`branch_b*`(VIP_READY) vocabulary -- a project's real precondition names are
declared by its caller, exactly as `runtime_event_registry`'s own event set is
never hardcoded, and exactly as `config_variant_coverage.py`'s dimensions are
declared rather than guessed). Each declared precondition name is checked
against a real `runtime_event_registry.RuntimeEventRegistry`'s current
PROPAGATED event state (`registry.propagate()` -- the same fixed-point that
already turns a genuinely failed prerequisite into an honest
`BLOCKED_BY_DEPENDENCY` rather than leaving a dependent event silently PENDING
forever). This module invents no interrupt-priority scheme, no arbitration
policy and no timing value, and parses no sim.log itself -- whether an event
"really" FIRED is `runtime_event_registry`'s own caller-supplied,
evidence-cited fact, read here and never re-derived.

REPORTED VOCABULARY: exactly three per-command dispatch statuses --
READY / BLOCKED / UNKNOWN_PRECONDITION -- deliberately distinct from BOTH
`runtime_event_registry.EventStatus` (a per-EVENT outcome:
PENDING/FIRED/FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY) and
`command_error_taxonomy`'s eleven-value per-DISPATCH-FAILURE classification --
this module answers a third, different question again: given a command's own
declared precondition SET, may it be dispatched AT ALL, before any dispatch is
attempted. `assert_no_dispatch_status_vocabulary_collision()` below checks this
module's three tokens never collide with `EventStatus`'s five, the same
discipline `runtime_event_registry.assert_no_status_vocabulary_collision()`
already applies one level down (against `loop_budget.FailureType`).

STATUS DERIVATION, precisely, worst-first (the same "worst-first fold" several
sibling status rollups in this project already use --
`requirement_contract.derive_status()`, `platform_health`'s UNKNOWN-outranks-
HEALTHY rule):
  - Per declared precondition name, the registry's `propagate()` report is
    consulted for its EFFECTIVE (post-propagation) status:
      * FIRED               -> that one precondition is SATISFIED.
      * FAILED / TIMEOUT /
        BLOCKED_BY_DEPENDENCY (`runtime_event_registry.BLOCKING_STATUSES`)
                              -> that one precondition is BLOCKING: real,
                                 cited evidence says it cannot (yet, or ever
                                 without recovery) proceed.
      * PENDING               -> that one precondition is AWAITING: declared,
                                 known, simply not yet observed to have fired.
                                 "Blocked" is used here in the classic
                                 process-scheduling sense -- a task waiting on
                                 a condition that has not yet occurred is
                                 BLOCKED, whether or not that condition will
                                 ever occur.
      * (name absent from the registry entirely) -> UNRESOLVED: the
        precondition names an event this registry does not declare at all.
        Never assumed satisfied -- Evidence Truth Rule.
  - Per-COMMAND status folds those per-precondition outcomes worst-first:
      1. Any BLOCKING precondition -> command is BLOCKED. This wins even over
         an UNRESOLVED sibling precondition on the same command: real,
         evidenced failure of one precondition is stronger, more actionable
         information than mere absence of information about another, and
         reporting BLOCKED never loses that unresolved finding -- it is still
         named in the per-precondition detail.
      2. Else, any UNRESOLVED precondition (and no BLOCKING one) -> command is
         UNKNOWN_PRECONDITION. We cannot say the command is ready when one of
         its own declared prerequisites cannot even be evaluated -- the
         Evidence Truth Rule's "never assume satisfied when unknown" made
         literal.
      3. Else, any AWAITING precondition (known, not yet FIRED) -> command is
         BLOCKED: not ready to dispatch NOW, though it may become ready once
         that event fires.
      4. Else (every declared precondition, if any, is SATISFIED) -> READY.
  - Zero declared preconditions is legal and reports READY (vacuously true,
    the same "nothing declared, so nothing gates it" reading
    `runtime_event_registry`'s own empty-relations-list case uses) -- this is
    stated explicitly in the result rather than silently defaulted.

WHAT THIS IS NOT. It does not decide WHICH commands exist, does not run any
of them, and does not gate a build/regression/LSF submission -- there is
deliberately no stage gate. It does not invent a precondition name universe:
GLOBAL_READY/DUT_READY/FW_READY/VIP_READY/MODE_VALID/RESET_DEASSERTED/
PHY_READY in this docstring and in the tests are illustrative examples only,
never a hardcoded list this module checks a command's preconditions against
-- a command may declare ANY name, and this module's only judgment is whether
that name resolves to a real event in the SUPPLIED registry and what that
event's real propagated status is.

CLI: `python -m dv_harness.command_precondition_gate list|check --commands
<commands.json> [--registry <events.json>] [--out <path>] [--json]` -- one
shared `execute_verb()`. `list` prints the declared commands (no registry
needed). `check` requires both files, runs `registry.propagate()` once and
evaluates every declared command against it. Exit 0 every command READY,
1 at least one BLOCKED or UNKNOWN_PRECONDITION, 2 NOT_AVAILABLE or a usage/
declaration error.

LIMITS, disclosed rather than implied closed:
  1. It DECIDES nothing beyond reporting: no dispatch is actually performed,
     no build/job/approval, and there is deliberately no stage gate.
  2. It does not observe anything itself -- every event's real status is
     `runtime_event_registry`'s own caller-supplied, evidence-cited fact.
  3. A precondition name is matched EXACTLY against a declared event name;
     there is no fuzzy/prefix matching and no alias table -- a project whose
     command declarations spell a precondition differently from its own event
     names must reconcile the spelling, since silently aliasing them risks
     matching the wrong event.
  4. It evaluates one registry's current state at one point in time (one
     `propagate()` call per `check`/`evaluate_dispatch_readiness()` call) --
     it is not a subscription or a re-poller, and reports no history.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dv_harness.connectivity import render_markdown_table
from dv_harness.runtime_event_registry import (
    BLOCKING_STATUSES,
    EventStatus,
    PropagationReport,
    RuntimeEventRegistry,
    EventRegistryError,
    load_registry,
)

SCHEMA_VERSION = "1.0"

REPORT_PARTS = (".dv-harness", "command_precondition_gate", "dispatch_report.json")

_FIRED_VALUE = EventStatus.FIRED.value
_PENDING_VALUE = EventStatus.PENDING.value
_BLOCKING_VALUES = frozenset(s.value for s in BLOCKING_STATUSES)


def _now() -> str:
    """Same UTC-ISO stamp `runtime_event_registry._now()` uses -- duplicated
    as a 2-line local helper for the same reason that module states: this
    module stays importable by a gate subprocess without pulling anything
    heavier in."""
    return datetime.now(timezone.utc).isoformat()


class CommandPreconditionGateError(ValueError):
    """A declared command/precondition set that cannot be honoured as
    written: a blank command_id, a blank precondition name, or a duplicate
    precondition name declared twice on the same command. Every one of these
    is a contradiction in the caller's own declaration, surfaced rather than
    silently resolved."""


class CommandDispatchStatus(str, Enum):
    """Exactly three values -- see module docstring's "STATUS DERIVATION".
    READY: every declared precondition resolved to a known event whose
    propagated status is FIRED (or none were declared at all). BLOCKED: at
    least one declared precondition resolved to a known event that is not
    (yet, or ever without recovery) FIRED -- FAILED/TIMEOUT/
    BLOCKED_BY_DEPENDENCY or still PENDING. UNKNOWN_PRECONDITION: at least one
    declared precondition names no event this registry declares at all, and
    no OTHER declared precondition is BLOCKING (BLOCKING always outranks
    UNKNOWN_PRECONDITION -- see module docstring)."""

    READY = "READY"
    BLOCKED = "BLOCKED"
    UNKNOWN_PRECONDITION = "UNKNOWN_PRECONDITION"


def assert_no_dispatch_status_vocabulary_collision() -> None:
    """`runtime_event_registry.EventStatus` answers "what happened to one
    RUNTIME EVENT" (PENDING/FIRED/FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY);
    `CommandDispatchStatus` answers "may THIS COMMAND be dispatched right
    now" -- a deliberately different, coarser, per-command vocabulary built
    ON TOP of the first. A shared token between the two would let a reader
    mistake a command's dispatch readiness for one event's raw status, the
    same reasoning `runtime_event_registry.assert_no_status_vocabulary_
    collision()` applies one level down against `loop_budget.FailureType`."""
    event_values = {s.value for s in EventStatus}
    dispatch_values = {s.value for s in CommandDispatchStatus}
    overlap = event_values & dispatch_values
    if overlap:
        raise AssertionError(
            f"CommandDispatchStatus shares token(s) {sorted(overlap)!r} with "
            "runtime_event_registry.EventStatus -- these are two deliberately "
            "separate vocabularies (see module docstring); a shared token means "
            "a reader could mistake a command's dispatch readiness for one "
            "event's raw status.")


assert_no_dispatch_status_vocabulary_collision()


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class CommandPreconditionDeclaration:
    """One command's own declared precondition set. `preconditions` is a
    caller-declared tuple of precondition NAMES -- never a hardcoded
    universal list; a project's real names (GLOBAL_READY/DUT_READY/FW_READY/
    VIP_READY/MODE_VALID/RESET_DEASSERTED/PHY_READY are illustrative examples
    only) are whatever that project's own command.txt/pattern declares.
    `source` is the real evidence citation for why these preconditions are
    declared (a command.txt line, a pattern-architecture section reference) --
    carried through, never enforced non-empty (a command's existence claim is
    weaker than an event OBSERVATION's, which runtime_event_registry does
    enforce)."""

    command_id: str
    preconditions: Tuple[str, ...] = ()
    source: str = ""

    def __post_init__(self) -> None:
        if not _is_nonempty_str(self.command_id):
            raise CommandPreconditionGateError("a command needs a non-empty command_id")
        for name in self.preconditions:
            if not _is_nonempty_str(name):
                raise CommandPreconditionGateError(
                    f"command {self.command_id!r} declares a blank precondition name")
        if len(set(self.preconditions)) != len(self.preconditions):
            dupes = sorted({n for n in self.preconditions if self.preconditions.count(n) > 1})
            raise CommandPreconditionGateError(
                f"command {self.command_id!r} declares duplicate precondition name(s): {dupes}")

    def to_dict(self) -> dict:
        return {"command_id": self.command_id, "preconditions": list(self.preconditions),
                "source": self.source}


@dataclass(frozen=True)
class PreconditionCheck:
    """One precondition's real check result against the registry's current
    propagated state. `known` is False when `precondition_name` names no
    event the registry declares at all -- `effective_status`/`raw_status`
    stay None in that case (there is nothing to report), never a guessed
    value."""

    precondition_name: str
    known: bool
    effective_status: Optional[str]
    raw_status: Optional[str]
    reason: str

    def to_dict(self) -> dict:
        return {"precondition_name": self.precondition_name, "known": self.known,
                "effective_status": self.effective_status, "raw_status": self.raw_status,
                "reason": self.reason}


@dataclass(frozen=True)
class CommandPreconditionResult:
    """One command's dispatch-readiness verdict plus the full per-precondition
    evidence it was derived from."""

    command_id: str
    registry_id: str
    status: str
    checks: Tuple[PreconditionCheck, ...]
    blocking_preconditions: Tuple[str, ...]
    awaiting_preconditions: Tuple[str, ...]
    unresolved_preconditions: Tuple[str, ...]
    reason: str

    def to_dict(self) -> dict:
        return {
            "command_id": self.command_id, "registry_id": self.registry_id,
            "status": self.status, "checks": [c.to_dict() for c in self.checks],
            "blocking_preconditions": list(self.blocking_preconditions),
            "awaiting_preconditions": list(self.awaiting_preconditions),
            "unresolved_preconditions": list(self.unresolved_preconditions),
            "reason": self.reason,
        }


def _reason_for_check(name: str, status_value: Optional[str]) -> str:
    if status_value is None:
        return f"no runtime event named {name!r} is declared in this registry -- cannot determine readiness"
    if status_value == _FIRED_VALUE:
        return f"event {name!r} is FIRED"
    if status_value in _BLOCKING_VALUES:
        return f"event {name!r} is {status_value} -- this precondition cannot proceed without recovery"
    return f"event {name!r} is PENDING -- declared, not yet observed to have fired"


def evaluate_command_preconditions(
    command: CommandPreconditionDeclaration,
    report: PropagationReport,
) -> CommandPreconditionResult:
    """Evaluate ONE command's declared preconditions against an ALREADY
    computed `runtime_event_registry.PropagationReport`. Callers evaluating
    many commands against the same registry should compute the report once
    (`registry.propagate()`) and pass it to each call -- see
    `evaluate_dispatch_readiness()` below, which does exactly that."""
    checks: List[PreconditionCheck] = []
    blocking: List[str] = []
    awaiting: List[str] = []
    unresolved: List[str] = []

    for name in command.preconditions:
        if name not in report.effective_status:
            checks.append(PreconditionCheck(name, known=False, effective_status=None,
                                             raw_status=None, reason=_reason_for_check(name, None)))
            unresolved.append(name)
            continue
        eff = report.effective_status[name]
        raw = report.raw_status.get(name)
        checks.append(PreconditionCheck(name, known=True, effective_status=eff, raw_status=raw,
                                         reason=_reason_for_check(name, eff)))
        if eff == _FIRED_VALUE:
            continue
        if eff in _BLOCKING_VALUES:
            blocking.append(name)
        else:
            awaiting.append(name)

    if blocking:
        status = CommandDispatchStatus.BLOCKED
        reason = (f"BLOCKED: {', '.join(blocking)} "
                  f"{'is' if len(blocking) == 1 else 'are'} FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY")
        if unresolved:
            reason += f" (also unresolved: {', '.join(unresolved)})"
        if awaiting:
            reason += f" (also still PENDING: {', '.join(awaiting)})"
    elif unresolved:
        status = CommandDispatchStatus.UNKNOWN_PRECONDITION
        reason = (f"UNKNOWN_PRECONDITION: {', '.join(unresolved)} "
                  f"{'names' if len(unresolved) == 1 else 'name'} no event declared in registry "
                  f"{report.registry_id!r} -- never assumed satisfied")
        if awaiting:
            reason += f" (also still PENDING: {', '.join(awaiting)})"
    elif awaiting:
        status = CommandDispatchStatus.BLOCKED
        reason = (f"BLOCKED: {', '.join(awaiting)} "
                  f"{'is' if len(awaiting) == 1 else 'are'} declared but not yet FIRED")
    else:
        status = CommandDispatchStatus.READY
        reason = (f"READY: all {len(command.preconditions)} declared precondition(s) FIRED"
                  if command.preconditions else
                  "READY: no preconditions declared for this command")

    return CommandPreconditionResult(
        command_id=command.command_id, registry_id=report.registry_id, status=status.value,
        checks=tuple(checks), blocking_preconditions=tuple(blocking),
        awaiting_preconditions=tuple(awaiting), unresolved_preconditions=tuple(unresolved),
        reason=reason,
    )


@dataclass
class DispatchGateReport:
    registry_id: str
    generated_at: str
    results: Tuple[CommandPreconditionResult, ...]

    def ready_commands(self) -> Tuple[str, ...]:
        return tuple(r.command_id for r in self.results if r.status == CommandDispatchStatus.READY.value)

    def blocked_commands(self) -> Tuple[str, ...]:
        return tuple(r.command_id for r in self.results if r.status == CommandDispatchStatus.BLOCKED.value)

    def unknown_precondition_commands(self) -> Tuple[str, ...]:
        return tuple(r.command_id for r in self.results
                     if r.status == CommandDispatchStatus.UNKNOWN_PRECONDITION.value)

    def has_any_blocking_outcome(self) -> bool:
        return bool(self.blocked_commands() or self.unknown_precondition_commands())

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION, "registry_id": self.registry_id,
            "generated_at": self.generated_at, "results": [r.to_dict() for r in self.results],
        }


def evaluate_dispatch_readiness(
    commands: Sequence[CommandPreconditionDeclaration],
    registry: RuntimeEventRegistry,
) -> DispatchGateReport:
    """Evaluate EVERY declared command's preconditions against ONE real
    `registry.propagate()` call -- computed exactly once here, so every
    command in the same report is judged against the identical propagated
    event state (never a slightly-later, slightly-different re-computation
    per command)."""
    report = registry.propagate()
    results = tuple(evaluate_command_preconditions(cmd, report) for cmd in commands)
    return DispatchGateReport(registry_id=registry.registry_id, generated_at=_now(), results=results)


# ------------------------------------------------------------------------
# loading commands from a declared JSON shape
# ------------------------------------------------------------------------

def commands_from_dict(data: Mapping[str, Any]) -> Tuple[CommandPreconditionDeclaration, ...]:
    """Load a declared command set from its JSON shape:
    `{"commands": [{"command_id", "preconditions": [...], "source"}, ...]}`.
    Every structural problem raises `CommandPreconditionGateError` naming the
    offending declaration -- nothing is silently defaulted, because a
    mistyped precondition name that quietly became a different event's name
    would evaluate readiness against the wrong prerequisite."""
    if not isinstance(data, Mapping):
        raise CommandPreconditionGateError("command declaration must be a JSON object")
    raw_commands = data.get("commands")
    if not isinstance(raw_commands, list) or not raw_commands:
        raise CommandPreconditionGateError("declaration carries no non-empty 'commands' list")
    out = []
    for i, c in enumerate(raw_commands):
        if not isinstance(c, Mapping):
            raise CommandPreconditionGateError(f"commands[{i}] must be a JSON object")
        preconditions = c.get("preconditions", [])
        if isinstance(preconditions, str):
            preconditions = [preconditions]
        out.append(CommandPreconditionDeclaration(
            command_id=c.get("command_id", ""),
            preconditions=tuple(preconditions),
            source=c.get("source", ""),
        ))
    return tuple(out)


def load_commands(path: Any) -> Tuple[CommandPreconditionDeclaration, ...]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CommandPreconditionGateError(f"commands file not found: {p}") from None
    except json.JSONDecodeError as e:
        raise CommandPreconditionGateError(f"commands file {p} is not valid JSON: {e}") from None
    return commands_from_dict(data)


# ------------------------------------------------------------------------
# rendering (reuses connectivity.render_markdown_table -- the repo's one
# parameterized table renderer -- rather than a second hand-rolled one)
# ------------------------------------------------------------------------

def render_commands(commands: Sequence[CommandPreconditionDeclaration]) -> str:
    rows = [{"command_id": c.command_id, "preconditions": ", ".join(c.preconditions) or "(none)",
             "source": c.source} for c in commands]
    table = render_markdown_table(
        [("command_id", "Command"), ("preconditions", "Declared Preconditions"), ("source", "Source")],
        rows, empty_note="(no commands declared)")
    return f"# Declared Commands\n\n{table}\n"


def render_dispatch_gate(report: DispatchGateReport) -> str:
    summary_rows = [{
        "command_id": r.command_id, "status": r.status,
        "blocking": ", ".join(r.blocking_preconditions) or "-",
        "awaiting": ", ".join(r.awaiting_preconditions) or "-",
        "unresolved": ", ".join(r.unresolved_preconditions) or "-",
    } for r in report.results]
    summary_table = render_markdown_table(
        [("command_id", "Command"), ("status", "Dispatch Status"), ("blocking", "Blocking"),
         ("awaiting", "Awaiting"), ("unresolved", "Unresolved")],
        summary_rows, empty_note="(no commands evaluated)")

    detail_rows = []
    for r in report.results:
        for c in r.checks:
            detail_rows.append({
                "command_id": r.command_id, "precondition_name": c.precondition_name,
                "known": "yes" if c.known else "no",
                "effective_status": c.effective_status or "-", "reason": c.reason,
            })
    detail_table = render_markdown_table(
        [("command_id", "Command"), ("precondition_name", "Precondition"), ("known", "Known Event"),
         ("effective_status", "Effective Status"), ("reason", "Reason")],
        detail_rows, empty_note="(no preconditions declared by any evaluated command)")

    return (f"# Command Precondition Gate: {report.registry_id}\n\n"
            f"generated_at: {report.generated_at}\n\n## Commands\n\n{summary_table}\n\n"
            f"## Precondition Checks\n\n{detail_table}\n\n"
            "NOTE: this report is a computed readiness check over a declared command/precondition "
            "set and a declared event registry. It dispatches nothing, runs no build, submits no "
            "job, and gates nothing.\n")


def report_path(root: Any) -> Path:
    return Path(root).joinpath(*REPORT_PARTS)


def _atomic_write_json(path: Path, data: Any) -> None:
    """Same write-temp-then-replace convention `runtime_event_registry.
    _atomic_write_json()` (and, one level further, `change_impact.
    _atomic_write_json()`/`config_variant_coverage._atomic_write_json()`) use,
    so a crashed run never leaves a half-written report on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_report(root: Any, report: DispatchGateReport, *, path: Any = None) -> Path:
    out = Path(path) if path else report_path(root)
    _atomic_write_json(out, report.to_dict())
    return out


# ------------------------------------------------------------------------
# CLI (shared by `python -m dv_harness.command_precondition_gate`)
# ------------------------------------------------------------------------

def execute_verb(verb: str, *, root: Any = ".", commands_path: Optional[str] = None,
                 registry_path: Optional[str] = None, out_path: Optional[str] = None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.command_precondition_gate
    <verb>`. Returns (text, exit_code): 0 every command READY, 1 at least one
    BLOCKED or UNKNOWN_PRECONDITION, 2 NOT_AVAILABLE or a usage/declaration
    error."""
    if not commands_path:
        return ("command-precondition-gate requires --commands <commands.json>", 2)
    try:
        commands = load_commands(commands_path)
    except CommandPreconditionGateError as e:
        return (f"CommandPreconditionGateError: {e}", 2)

    if verb == "list":
        text = (json.dumps([c.to_dict() for c in commands], indent=2) if as_json
                else render_commands(commands))
        return text, 0

    if verb == "check":
        if not registry_path:
            return ("command-precondition-gate check requires --registry <events.json>", 2)
        try:
            registry = load_registry(registry_path)
        except EventRegistryError as e:
            return (f"EventRegistryError: {e}", 2)
        report = evaluate_dispatch_readiness(commands, registry)
        written = None
        if out_path:
            written = write_report(root, report, path=out_path)
        text = json.dumps(report.to_dict(), indent=2) if as_json else render_dispatch_gate(report)
        if written is not None and not as_json:
            text += f"\n  written to: {written}"
        return text, (1 if report.has_any_blocking_outcome() else 0)

    return (f"unknown command-precondition-gate verb {verb!r}", 2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.command_precondition_gate",
        description="Validates a command's declared preconditions against runtime_event_registry's "
                    "current propagated event state before dispatch. Reports only -- dispatches "
                    "nothing, runs no build, submits no job, gates nothing.")
    ap.add_argument("verb", choices=("list", "check"))
    ap.add_argument("--commands", required=True, help="Declared command/precondition JSON file.")
    ap.add_argument("--registry", default=None, help="check: runtime event registry JSON file.")
    ap.add_argument("--out", default=None, help="check: also write the dispatch report JSON here.")
    ap.add_argument("--root", default=".", help="Project root (used for the default report path).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.verb, root=a.root, commands_path=a.commands,
                              registry_path=a.registry, out_path=a.out, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
