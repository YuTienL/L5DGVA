"""dv_harness/de_command_runtime_readiness_gate.py -- the composite
DE_COMMAND_RUNTIME_READY verdict: aggregates real runtime_event_registry
state, real command_precondition_gate results, and a caller-supplied,
duck-typed branch/grammar-side result set into ONE PASS/BLOCKED verdict
naming every specific blocker.

GAP THIS CLOSES. `runtime_event_registry.py` answers "what is this EVENT's
status" (with REQUIRES/WAITS_FOR/TRIGGERS/UNBLOCKS stop-on-failure
propagation) and `command_precondition_gate.py` answers "may THIS COMMAND be
dispatched right now, given the registry's real event state" -- both real,
both tested, both real gap-closures from this same workflow run. Neither
answers the question a runtime dispatcher actually needs before it starts
issuing an entire generated pattern's worth of `block`/`branch_a*`/
`branch_fw`/`branch_b*` commands
(`.claude/skills/CORE/pattern-architecture/SKILL.md`'s five-layer shape,
`.claude/skills/CORE/branch-mapper/SKILL.md`'s AMBA M x N arbitration prose):
"given the registry's current state, every declared command's dispatch
readiness, AND whatever the branch/grammar-authoring side of the pipeline
independently concluded about this same pattern (its own ownership/style/
grammar validation -- a DIFFERENT, sibling batch of this same workflow run,
which may or may not have finished), is this pattern's runtime execution
actually READY, or is it BLOCKED, and by what, specifically?" Nothing in this
repo joined those three real sources into one verdict.

WHAT THIS IS. A thin AGGREGATOR over three already-real inputs, reusing each
one's own vocabulary and computation rather than re-deriving any of them:
  1. `runtime_event_registry.RuntimeEventRegistry.propagate()` -- called
     EXACTLY ONCE here (never re-run per command), producing the real
     `PropagationReport` this module reads for BOTH its own event-level
     blockers (an event that is itself FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY,
     whether or not any command happens to declare it as a precondition) AND
     the shared basis every command's precondition check is evaluated
     against (`command_precondition_gate.evaluate_command_preconditions()`,
     called directly with that one shared report -- the exact pattern that
     module's own docstring recommends for evaluating several commands
     against one registry state, and the reason this module does not call
     `evaluate_dispatch_readiness()` itself, which would silently re-run
     `propagate()` a second time).
  2. `command_precondition_gate.evaluate_command_preconditions()`'s real
     per-command `CommandDispatchStatus` (READY/BLOCKED/UNKNOWN_PRECONDITION)
     -- read verbatim; a command not READY is a blocker, named with that
     command's own real reason text.
  3. A caller-supplied, DUCK-TYPED `branch_grammar_results` value -- the
     branch/grammar-authoring side's own conclusion about this same pattern
     (e.g. `branch_ownership_resolver.validate_branch_assignment()`'s
     VALID/INVALID/AMBIGUOUS, or `command_generation_gate.py`'s own
     PASS/BLOCKED-shaped payload -- this module never imports either, or any
     other module from that sibling "DE Command / Branch Architecture"
     batch, precisely because that batch may or may not have finished when
     this one runs; it accepts whatever shape arrives as generic,
     alias-tolerant records: any of `command_id`/`command_name`/`name`/`id`/
     `identifier` for who the finding is about, any of `status`/`verdict`/
     `result`/`branch_status`/`ownership_status` for the finding itself, any
     of `reason`/`detail`/`message`/`rationale` for why. A record whose
     status string is not one of a small, explicit, case-insensitive
     recognized-PASS vocabulary (`BRANCH_GRAMMAR_PASS_STATUSES`) is a
     blocker, quoting the real status string verbatim -- an unrecognized or
     absent status is never assumed passing, the same Evidence Truth Rule
     discipline `runtime_event_registry`'s own "an event absent from the
     registry is UNRESOLVED, never assumed satisfied" already applies one
     layer down.

The composite verdict is BLOCKED iff ANY of the three sources reports a real
blocker; it is PASS only when the registry's propagated event state has no
blocking event, every declared command is READY, and every supplied
branch/grammar-side result (if any were supplied at all -- supplying none is
legal, since the sibling batch may not have run yet) reports a recognized
pass status. Every blocker is named individually and by its real source, so
a reader never has to guess which of the three layers is the reason.

WHAT THIS IS NOT. It invents no interrupt-priority scheme, no arbitration
policy, and no timing value; it parses no sim.log and observes nothing
itself -- every event's real status is `runtime_event_registry`'s own
caller-supplied, evidence-cited fact, and every command's real dispatch
status is `command_precondition_gate`'s own computation over that same
fact. It does not decide which commands exist, does not run any of them, and
there is deliberately no separate "runtime" concept invented here beyond
what those two modules already track. It does not know or enforce the
branch/grammar-side batch's own internal vocabulary -- a project whose
sibling batch spells "pass" some other way declares its own pass-vocabulary
extension by pre-normalizing its records before calling this module, since
guessing a new synonym here risks silently accepting a real failure.

CLI: `python -m dv_harness.de_command_runtime_readiness_gate check --registry
<events.json> [--commands <commands.json>] [--branch-grammar <results.json>]
[--out <path>] [--json]`. Exit 0 PASS, 1 BLOCKED, 2 NOT_AVAILABLE or a usage/
declaration error.

LIMITS, disclosed rather than implied closed:
  1. It DECIDES nothing beyond reporting: no dispatch is performed, no
     build/job/approval, and there is deliberately no stage gate of its own
     beyond the STAGE_GATES entry an integrator wires (this module itself
     never edits `gates.py`).
  2. `evaluate_de_command_runtime_readiness()` takes an ALREADY-CONSTRUCTED
     `RuntimeEventRegistry`; it is not a subscription or a re-poller, and it
     reports no history across calls.
  3. The branch/grammar-side vocabulary check is intentionally SHALLOW: it
     recognizes a small, fixed set of pass-like tokens and treats everything
     else (including a genuinely-fine but oddly-spelled status) as a
     blocker. That is a deliberate false-positive-tolerant, false-negative-
     intolerant bias -- silently accepting an unrecognized status as passing
     is the more expensive mistake for a runtime-readiness gate to make.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dv_harness.connectivity import render_markdown_table
from dv_harness.runtime_event_registry import (
    EventRegistryError,
    PropagationReport,
    RuntimeEventRegistry,
    load_registry,
    registry_from_dict,
)
from dv_harness.command_precondition_gate import (
    CommandDispatchStatus,
    CommandPreconditionDeclaration,
    CommandPreconditionGateError,
    commands_from_dict,
    evaluate_command_preconditions,
    load_commands,
)

SCHEMA_VERSION = "1.0"

REPORT_PARTS = (".dv-harness", "de_command_runtime_readiness", "readiness_report.json")

#: The two-value outer verdict this module produces. Deliberately reuses the
#: same PASS/BLOCKED words `models.Status` and every STAGE_GATES script
#: already use for a stage-level verdict (see `waiver_revalidation_gate.py`,
#: which prints `{"status": "PASS"|"FAIL", ...}` for the identical reason):
#: this IS the stage-level conclusion, not a new orthogonal per-item
#: vocabulary like `EventStatus`/`CommandDispatchStatus` (which this module
#: reads, never redefines) -- there is nothing to disambiguate it from.
DE_COMMAND_RUNTIME_PASS = "PASS"
DE_COMMAND_RUNTIME_BLOCKED = "BLOCKED"
DE_COMMAND_RUNTIME_STATUSES: Tuple[str, ...] = (DE_COMMAND_RUNTIME_PASS, DE_COMMAND_RUNTIME_BLOCKED)

#: A branch/grammar-side result's status is recognized as a genuine PASS only
#: when its (case-insensitive, stripped) value is one of these. Anything else
#: -- including an entirely unrecognized word -- is a blocker, per the module
#: docstring's "never assumed passing" rule.
BRANCH_GRAMMAR_PASS_STATUSES: frozenset = frozenset({
    "VALID", "PASS", "PASSED", "READY", "OK", "RESOLVED", "GOOD", "CLEAR", "TRUE",
})

_IDENTIFIER_KEYS: Tuple[str, ...] = ("command_id", "command_name", "name", "id", "identifier")
_STATUS_KEYS: Tuple[str, ...] = ("status", "verdict", "result", "branch_status", "ownership_status")
_REASON_KEYS: Tuple[str, ...] = ("reason", "detail", "message", "rationale")


def _now() -> str:
    """Same UTC-ISO stamp `runtime_event_registry._now()` /
    `command_precondition_gate._now()` use, duplicated as a 2-line local
    helper for the same reason both state: this module stays importable by a
    gate subprocess without pulling anything heavier in."""
    return datetime.now(timezone.utc).isoformat()


class DECommandRuntimeReadinessError(ValueError):
    """A declared `branch_grammar_results` value that cannot be honoured as
    written -- something other than a list, a mapping, or None. Every other
    declaration problem (a malformed registry, a malformed command set) is
    surfaced by the module that owns that declaration
    (`runtime_event_registry.EventRegistryError` /
    `command_precondition_gate.CommandPreconditionGateError`), never
    re-wrapped or swallowed here."""


def _first_present(record: Mapping[str, Any], keys: Sequence[str]) -> Optional[Any]:
    for k in keys:
        if k in record and record[k] not in (None, ""):
            return record[k]
    return None


@dataclass(frozen=True)
class BranchGrammarCheck:
    """One duck-typed branch/grammar-side record's real evaluation result.
    `raw_record` is the original record (as a plain dict) so a reader can see
    exactly what arrived, independent of which alias key this module matched
    on."""

    identifier: str
    raw_record: Mapping[str, Any]
    status_value: Optional[str]
    blocking: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "status_value": self.status_value,
            "blocking": self.blocking,
            "reason": self.reason,
            "raw_record": dict(self.raw_record),
        }


def _normalize_branch_grammar_results(data: Any) -> Tuple[Any, ...]:
    """Accepts the caller's `branch_grammar_results` in any of three legal
    shapes -- a list/tuple of records, a mapping carrying a `results` list,
    or a bare mapping of `identifier -> status_or_record` -- and returns a
    plain tuple of records ready for `_evaluate_branch_grammar_record()`.
    `None` (nothing supplied yet -- the sibling batch may not have run) is
    legal and returns an empty tuple; anything else is refused rather than
    silently coerced, since a caller passing e.g. a bare string almost
    certainly made a mistake this module should not paper over."""
    if data is None:
        return ()
    if isinstance(data, Mapping):
        results = data.get("results")
        if isinstance(results, (list, tuple)):
            return tuple(results)
        if "results" in data:
            raise DECommandRuntimeReadinessError(
                f"branch_grammar_results['results'] must be a list, got {type(results).__name__}")
        out: List[Any] = []
        for key, value in data.items():
            if isinstance(value, Mapping):
                rec = dict(value)
                rec.setdefault("identifier", key)
                rec.setdefault("command_id", key)
            else:
                rec = {"identifier": key, "command_id": key, "status": value}
            out.append(rec)
        return tuple(out)
    if isinstance(data, (list, tuple)):
        return tuple(data)
    raise DECommandRuntimeReadinessError(
        "branch_grammar_results must be a list, a mapping, or None -- "
        f"got {type(data).__name__}")


def _evaluate_branch_grammar_record(record: Any, index: int) -> BranchGrammarCheck:
    if not isinstance(record, Mapping):
        return BranchGrammarCheck(
            identifier=f"branch_grammar_results[{index}]", raw_record={}, status_value=None,
            blocking=True,
            reason=(f"branch_grammar_results[{index}] is not a JSON object (duck-typed record "
                    f"expected, got {type(record).__name__}) -- cannot be evaluated, never "
                    "assumed passing"))

    identifier_value = _first_present(record, _IDENTIFIER_KEYS)
    identifier = str(identifier_value) if identifier_value is not None else f"branch_grammar_results[{index}]"

    raw_status = _first_present(record, _STATUS_KEYS)
    reason_text = _first_present(record, _REASON_KEYS)

    if raw_status is None:
        return BranchGrammarCheck(
            identifier=identifier, raw_record=dict(record), status_value=None, blocking=True,
            reason=(f"{identifier}: no status field found among {_STATUS_KEYS} -- an unstated "
                    "branch/grammar-side result is never assumed passing"))

    status_str = str(raw_status)
    if status_str.strip().upper() in BRANCH_GRAMMAR_PASS_STATUSES:
        return BranchGrammarCheck(
            identifier=identifier, raw_record=dict(record), status_value=status_str, blocking=False,
            reason=f"{identifier}: reports {status_str!r}")

    detail = f" ({reason_text})" if reason_text else ""
    return BranchGrammarCheck(
        identifier=identifier, raw_record=dict(record), status_value=status_str, blocking=True,
        reason=(f"{identifier}: reports status {status_str!r}{detail} -- not one of the "
                f"recognized pass values {sorted(BRANCH_GRAMMAR_PASS_STATUSES)}"))


@dataclass
class DECommandRuntimeReadinessReport:
    """The composite verdict plus every real input it was derived from, so a
    reader never has to re-run this module's own computation to see why."""

    registry_id: str
    generated_at: str
    status: str
    event_registry_blockers: Tuple[Dict[str, Any], ...]
    event_registry_findings: Tuple[Dict[str, Any], ...]
    command_precondition_results: Tuple[Dict[str, Any], ...]
    command_precondition_blockers: Tuple[Dict[str, Any], ...]
    branch_grammar_supplied: bool
    branch_grammar_checks: Tuple[Dict[str, Any], ...]
    branch_grammar_blockers: Tuple[Dict[str, Any], ...]
    reason: str

    def has_blocking_outcome(self) -> bool:
        return self.status == DE_COMMAND_RUNTIME_BLOCKED

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "registry_id": self.registry_id,
            "generated_at": self.generated_at,
            "status": self.status,
            "event_registry_blockers": list(self.event_registry_blockers),
            "event_registry_findings": list(self.event_registry_findings),
            "command_precondition_results": list(self.command_precondition_results),
            "command_precondition_blockers": list(self.command_precondition_blockers),
            "branch_grammar_supplied": self.branch_grammar_supplied,
            "branch_grammar_checks": list(self.branch_grammar_checks),
            "branch_grammar_blockers": list(self.branch_grammar_blockers),
            "reason": self.reason,
        }


def evaluate_de_command_runtime_readiness(
    registry: RuntimeEventRegistry,
    commands: Sequence[CommandPreconditionDeclaration] = (),
    branch_grammar_results: Any = None,
) -> DECommandRuntimeReadinessReport:
    """The one real aggregation. `registry.propagate()` runs EXACTLY ONCE;
    every command's precondition check reuses that same
    `PropagationReport` via `evaluate_command_preconditions()` directly
    (never `evaluate_dispatch_readiness()`, which would re-run
    `propagate()` a second time on an identical registry)."""
    event_report: PropagationReport = registry.propagate()

    event_blockers: List[Dict[str, Any]] = []
    findings_by_event: Dict[str, Dict[str, Any]] = {}
    for f in event_report.findings:
        findings_by_event.setdefault(f["event"], f)

    for name in event_report.blocked_events():
        finding = findings_by_event.get(name)
        event_blockers.append({
            "event_name": name,
            "effective_status": event_report.effective_status[name],
            "reason": finding["reason"] if finding else
                      f"event {name!r} is BLOCKED_BY_DEPENDENCY",
        })
    for name in event_report.failed_or_timeout_events():
        event_blockers.append({
            "event_name": name,
            "effective_status": event_report.raw_status[name],
            "reason": (f"event {name!r} is observed {event_report.raw_status[name]} "
                       "(a caller-supplied, evidence-cited observation)"),
        })

    command_results = tuple(evaluate_command_preconditions(cmd, event_report) for cmd in commands)
    command_blockers: List[Dict[str, Any]] = []
    for r in command_results:
        if r.status != CommandDispatchStatus.READY.value:
            command_blockers.append({
                "command_id": r.command_id,
                "status": r.status,
                "reason": r.reason,
            })

    branch_grammar_supplied = branch_grammar_results is not None
    normalized_branch_grammar = _normalize_branch_grammar_results(branch_grammar_results)
    branch_checks = tuple(
        _evaluate_branch_grammar_record(rec, i) for i, rec in enumerate(normalized_branch_grammar)
    )
    branch_blockers = [c.to_dict() for c in branch_checks if c.blocking]

    blocking = bool(event_blockers or command_blockers or branch_blockers)
    status = DE_COMMAND_RUNTIME_BLOCKED if blocking else DE_COMMAND_RUNTIME_PASS

    reason_parts: List[str] = []
    if event_blockers:
        reason_parts.append(
            f"{len(event_blockers)} runtime event(s) blocking: " +
            "; ".join(b["reason"] for b in event_blockers))
    if command_blockers:
        reason_parts.append(
            f"{len(command_blockers)} command(s) not READY: " +
            "; ".join(f"{b['command_id']} ({b['status']}): {b['reason']}" for b in command_blockers))
    if branch_blockers:
        reason_parts.append(
            f"{len(branch_blockers)} branch/grammar-side result(s) blocking: " +
            "; ".join(b["reason"] for b in branch_blockers))

    if reason_parts:
        reason = "DE_COMMAND_RUNTIME_READY: BLOCKED -- " + " | ".join(reason_parts)
    else:
        branch_grammar_clause = (
            "no branch/grammar-side results were supplied" if not branch_grammar_supplied else
            f"all {len(branch_checks)} supplied branch/grammar-side result(s) report a "
            "recognized pass status"
        )
        reason = (f"DE_COMMAND_RUNTIME_READY: PASS -- registry {registry.registry_id!r}'s "
                  f"propagated event state has no blocking event, all {len(command_results)} "
                  f"declared command(s) are READY, and {branch_grammar_clause}")

    return DECommandRuntimeReadinessReport(
        registry_id=registry.registry_id,
        generated_at=_now(),
        status=status,
        event_registry_blockers=tuple(event_blockers),
        event_registry_findings=tuple(event_report.findings),
        command_precondition_results=tuple(r.to_dict() for r in command_results),
        command_precondition_blockers=tuple(command_blockers),
        branch_grammar_supplied=branch_grammar_supplied,
        branch_grammar_checks=tuple(c.to_dict() for c in branch_checks),
        branch_grammar_blockers=tuple(branch_blockers),
        reason=reason,
    )


# ------------------------------------------------------------------------
# loading from declared JSON shapes (reuses the two owning modules' own
# loaders/parsers -- there is no second parser for either shape here)
# ------------------------------------------------------------------------

def load_branch_grammar_results(path: Any) -> Any:
    """Parses a `branch_grammar_results` JSON file and returns its raw
    structure (a list or a mapping) for `evaluate_de_command_runtime_readiness()`
    -- no shape is imposed beyond valid JSON; `_normalize_branch_grammar_results()`
    does the real acceptance/refusal at evaluation time."""
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DECommandRuntimeReadinessError(f"branch/grammar results file not found: {p}") from None
    except json.JSONDecodeError as e:
        raise DECommandRuntimeReadinessError(f"branch/grammar results file {p} is not valid JSON: {e}") from None


# ------------------------------------------------------------------------
# rendering (reuses connectivity.render_markdown_table -- the repo's one
# parameterized table renderer -- rather than a second hand-rolled one)
# ------------------------------------------------------------------------

def render_readiness(report: DECommandRuntimeReadinessReport) -> str:
    event_rows = [{"event_name": b["event_name"], "effective_status": b["effective_status"],
                   "reason": b["reason"]} for b in report.event_registry_blockers]
    event_table = render_markdown_table(
        [("event_name", "Event"), ("effective_status", "Status"), ("reason", "Reason")],
        event_rows, empty_note="(no blocking runtime events)")

    command_rows = [{"command_id": r["command_id"], "status": r["status"], "reason": r["reason"]}
                     for r in report.command_precondition_results]
    command_table = render_markdown_table(
        [("command_id", "Command"), ("status", "Dispatch Status"), ("reason", "Reason")],
        command_rows, empty_note="(no commands declared)")

    branch_rows = [{"identifier": c["identifier"], "status_value": c["status_value"] or "-",
                     "blocking": "yes" if c["blocking"] else "no", "reason": c["reason"]}
                    for c in report.branch_grammar_checks]
    branch_table = render_markdown_table(
        [("identifier", "Identifier"), ("status_value", "Status"), ("blocking", "Blocking"),
         ("reason", "Reason")],
        branch_rows,
        empty_note=("(no branch/grammar-side results supplied)" if not report.branch_grammar_supplied
                     else "(no branch/grammar-side results)"))

    return (f"# DE Command Runtime Readiness: {report.registry_id}\n\n"
            f"generated_at: {report.generated_at}\n\n"
            f"## DE_COMMAND_RUNTIME_READY: {report.status}\n\n{report.reason}\n\n"
            f"## Runtime Event Blockers\n\n{event_table}\n\n"
            f"## Command Precondition Results\n\n{command_table}\n\n"
            f"## Branch/Grammar-Side Results\n\n{branch_table}\n\n"
            "NOTE: this report is a computed aggregation over a declared runtime event registry, "
            "a declared command/precondition set, and a caller-supplied branch/grammar-side result "
            "set. It dispatches nothing, runs no build, submits no job, and gates nothing beyond "
            "naming its own PASS/BLOCKED verdict.\n")


def report_path(root: Any) -> Path:
    return Path(root).joinpath(*REPORT_PARTS)


def _atomic_write_json(path: Path, data: Any) -> None:
    """Same write-temp-then-replace convention `runtime_event_registry.
    _atomic_write_json()` / `command_precondition_gate._atomic_write_json()`
    use, so a crashed run never leaves a half-written report on disk."""
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


def write_report(root: Any, report: DECommandRuntimeReadinessReport, *, path: Any = None) -> Path:
    out = Path(path) if path else report_path(root)
    _atomic_write_json(out, report.to_dict())
    return out


# ------------------------------------------------------------------------
# CLI (shared by `python -m dv_harness.de_command_runtime_readiness_gate`)
# ------------------------------------------------------------------------

def execute_verb(verb: str, *, root: Any = ".", registry_path: Optional[str] = None,
                 commands_path: Optional[str] = None, branch_grammar_path: Optional[str] = None,
                 out_path: Optional[str] = None, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `dv-harness de-command-runtime-readiness
    check` and `python -m dv_harness.de_command_runtime_readiness_gate check`.
    Returns (text, exit_code): 0 PASS, 1 BLOCKED, 2 NOT_AVAILABLE or a usage/
    declaration error."""
    if verb != "check":
        return (f"unknown de-command-runtime-readiness verb {verb!r}", 2)
    if not registry_path:
        return ("de-command-runtime-readiness check requires --registry <events.json>", 2)

    try:
        registry = load_registry(registry_path)
    except EventRegistryError as e:
        return (f"EventRegistryError: {e}", 2)

    commands: Tuple[CommandPreconditionDeclaration, ...] = ()
    if commands_path:
        try:
            commands = load_commands(commands_path)
        except CommandPreconditionGateError as e:
            return (f"CommandPreconditionGateError: {e}", 2)

    branch_grammar_results: Any = None
    if branch_grammar_path:
        try:
            branch_grammar_results = load_branch_grammar_results(branch_grammar_path)
        except DECommandRuntimeReadinessError as e:
            return (f"DECommandRuntimeReadinessError: {e}", 2)

    try:
        report = evaluate_de_command_runtime_readiness(registry, commands, branch_grammar_results)
    except DECommandRuntimeReadinessError as e:
        return (f"DECommandRuntimeReadinessError: {e}", 2)

    written = None
    if out_path:
        written = write_report(root, report, path=out_path)
    text = json.dumps(report.to_dict(), indent=2) if as_json else render_readiness(report)
    if written is not None and not as_json:
        text += f"\n  written to: {written}"
    return text, (1 if report.has_blocking_outcome() else 0)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.de_command_runtime_readiness_gate",
        description="Composite DE_COMMAND_RUNTIME_READY verdict: aggregates runtime_event_registry "
                    "state, command_precondition_gate results, and a caller-supplied branch/"
                    "grammar-side result set into one PASS/BLOCKED verdict naming every specific "
                    "blocker. Reports only -- dispatches nothing, runs no build, submits no job, "
                    "gates nothing.")
    ap.add_argument("verb", choices=("check",))
    ap.add_argument("--registry", required=True, help="Runtime event registry JSON file.")
    ap.add_argument("--commands", default=None, help="Declared command/precondition JSON file (optional).")
    ap.add_argument("--branch-grammar", default=None,
                     help="Duck-typed branch/grammar-side result set JSON file (optional).")
    ap.add_argument("--out", default=None, help="Also write the readiness report JSON here.")
    ap.add_argument("--root", default=".", help="Project root (used for the default report path).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.verb, root=a.root, registry_path=a.registry, commands_path=a.commands,
        branch_grammar_path=a.branch_grammar, out_path=a.out, as_json=a.json,
    )
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
