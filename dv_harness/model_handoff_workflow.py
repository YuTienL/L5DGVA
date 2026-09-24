"""dv_harness/model_handoff_workflow.py -- the real Human Transport
workflow (export/import) and Canonical Consumer wiring for
`L5DGVA_MODEL_HANDOFF_V1`/`L5DGVA_MODEL_RESULT_V1` (M7 V1,
`docs/architecture/L5DGVA_M7_STRUCTURED_MULTI_MODEL_MD_HANDOFF_
ARCHITECTURE.md`).

STATE MACHINE (dispatch section 10): `HANDOFF_READY` ->
`WAITING_FOR_HUMAN_TRANSPORT` -> `RESULT_RETURNED` -> `RESULT_VALIDATING`
-> `RESULT_ACCEPTED` | `RESULT_REJECTED` -> `RESULT_CONSUMED`. Persisted
as a real, on-disk JSON record per task
(`.dv-harness/model_handoffs/<task_id>/state.json`) so a caller can
resume across process invocations -- the system "must be resumable and
must not busy-wait for the human" (dispatch section 9). This module makes
NO claim of cross-session durability beyond "a real file on disk, read
back correctly" -- it is not wrapped in `lifecycle.py`'s own richer
milestone/transition-history model, and does not claim that model's own
guarantees.

CANONICAL CONSUMER (dispatch section 12/section 17 "Result Consumption"):
every ACCEPTED result reaches a real consumer, never merely a printed
line -- `.dv-harness/model_handoffs/registry.csv` (a real, structural,
append-only record every consumed result gets, the "evidence store" /
"capability-status update" consumer the architecture doc names), and,
when the result itself declares `human_decisions_required` or
`result_status == "HUMAN_DECISION_REQUIRED"`, a REAL question filed
through `question_queue.QuestionQueueStore.add_question()` -- the SAME
production HITL mechanism the M6 Golden Workflow itself uses, never a
second, parallel human-decision channel (dispatch section 18: "Multi-
model consensus is not signoff").

SCOPE ENFORCEMENT (dispatch section 19): `import_result()` never
consumes a result carrying an out-of-scope `files_referenced` entry --
`model_result.validate_result()`'s own `scope_validated` check (reusing
`task_boundary_conformance.classify_path()` verbatim) already computed
this; a scope violation forces `RESULT_REJECTED`, never a silent partial
consumption.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import model_handoff as _handoff_mod
from . import model_result as _result_mod
from .model_handoff import ModelHandoffV1, HandoffParseError
from .model_result import ModelResultV1, ResultParseError, ValidationOutcome
from .question_queue import QuestionQueueStore
from .task_boundary_conformance import TaskBoundary

# --- State vocabulary --------------------------------------------------------
STATE_HANDOFF_READY = "HANDOFF_READY"
STATE_WAITING_FOR_HUMAN_TRANSPORT = "WAITING_FOR_HUMAN_TRANSPORT"
STATE_RESULT_RETURNED = "RESULT_RETURNED"
STATE_RESULT_VALIDATING = "RESULT_VALIDATING"
STATE_RESULT_ACCEPTED = "RESULT_ACCEPTED"
STATE_RESULT_REJECTED = "RESULT_REJECTED"
STATE_RESULT_CONSUMED = "RESULT_CONSUMED"

_STATES = (
    STATE_HANDOFF_READY, STATE_WAITING_FOR_HUMAN_TRANSPORT, STATE_RESULT_RETURNED,
    STATE_RESULT_VALIDATING, STATE_RESULT_ACCEPTED, STATE_RESULT_REJECTED,
    STATE_RESULT_CONSUMED,
)

_HANDOFF_DIR = ".dv-harness/model_handoffs"
_REGISTRY_CSV = "registry.csv"
_REGISTRY_FIELDS = [
    "task_id", "target_model", "task_type", "state", "result_status",
    "handoff_path", "result_path", "consumed_at_head", "question_id",
]


def _task_dir(root: Path, task_id: str) -> Path:
    return Path(root) / _HANDOFF_DIR / task_id


def _state_path(root: Path, task_id: str) -> Path:
    return _task_dir(root, task_id) / "state.json"


def _registry_path(root: Path) -> Path:
    return Path(root) / _HANDOFF_DIR / _REGISTRY_CSV


def _load_state(root: Path, task_id: str) -> Optional[Dict[str, Any]]:
    p = _state_path(root, task_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_state(root: Path, task_id: str, state: Dict[str, Any]) -> None:
    assert state.get("state") in _STATES, f"unknown state {state.get('state')!r}, must be one of {_STATES}"
    p = _state_path(root, task_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def current_state(root: Path, task_id: str) -> Optional[str]:
    """Read-only status check -- what a resuming caller polls, never a
    busy-wait: this reads one real file, returns immediately, and makes
    no assumption about WHEN the human returns."""
    rec = _load_state(root, task_id)
    return rec.get("state") if rec else None


# --- Export (HANDOFF_READY -> WAITING_FOR_HUMAN_TRANSPORT) ------------------

def export_handoff(root: Path, handoff: ModelHandoffV1) -> Path:
    """Writes the real HANDOFF_V1.md artifact, transitions
    HANDOFF_READY -> WAITING_FOR_HUMAN_TRANSPORT, and returns the real
    path a human copies from. This is the ONLY function that produces the
    file a human actually transports -- `build_handoff()` itself never
    touches disk."""
    task_dir = _task_dir(root, handoff.task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = task_dir / "HANDOFF_V1.md"
    handoff_path.write_text(_handoff_mod.to_markdown(handoff), encoding="utf-8")
    (task_dir / "handoff.json").write_text(
        json.dumps(handoff.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    _save_state(root, handoff.task_id, {
        "task_id": handoff.task_id, "target_model": handoff.target_model,
        "task_type": handoff.task_type, "state": STATE_HANDOFF_READY,
        "handoff_path": str(handoff_path),
    })
    state = _load_state(root, handoff.task_id)
    state["state"] = STATE_WAITING_FOR_HUMAN_TRANSPORT
    _save_state(root, handoff.task_id, state)
    return handoff_path


def _load_handoff(root: Path, task_id: str) -> Optional[ModelHandoffV1]:
    task_dir = _task_dir(root, task_id)
    md_path = task_dir / "HANDOFF_V1.md"
    if not md_path.exists():
        return None
    return _handoff_mod.from_markdown(md_path.read_text(encoding="utf-8"))


# --- Import (RESULT_RETURNED -> ... -> RESULT_CONSUMED) ---------------------

class ImportOutcome:
    def __init__(self, *, task_id: str, state: str, validation: Optional[ValidationOutcome] = None,
                 parse_error: Optional[str] = None, question_id: Optional[str] = None,
                 result: Optional[ModelResultV1] = None):
        self.task_id = task_id
        self.state = state
        self.validation = validation
        self.parse_error = parse_error
        self.question_id = question_id
        self.result = result

    @property
    def consumed(self) -> bool:
        return self.state == STATE_RESULT_CONSUMED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id, "state": self.state,
            "validation": self.validation.to_dict() if self.validation else None,
            "parse_error": self.parse_error, "question_id": self.question_id,
        }


def _import_result_inner(root: Path, task_id: str, result_md_path: Path) -> ImportOutcome:
    """The full Result Ingestion pipeline (architecture doc): RESULT_
    RETURNED -> PARSED -> {TASK_ID,PRODUCER,TASK_TYPE,SCOPE,SCHEMA,
    EVIDENCE,GOVERNANCE}_VALIDATED -> RESULT_CLASSIFIED ->
    CANONICAL_CONSUMER. A parse failure or a failed validation
    transitions to RESULT_REJECTED and STOPS -- it never reaches
    consumption. `root`'s own current working tree is never mutated by a
    rejected result.

    GAP-V2-011 fix, replay safety (dispatch's own required properties:
    "DUPLICATE IMPORT -> ZERO duplicate semantic consumption",
    "REPLAY -> deterministic result"): if this exact `task_id` is
    ALREADY at `RESULT_CONSUMED`, a further call is a real, detected
    no-op -- it returns the SAME, already-recorded outcome without
    re-invoking `_consume_result()`/`_append_registry()` a second time,
    regardless of what the newly-supplied `result_md_path` contains (a
    consumed task is a closed transaction; re-importing a DIFFERENT
    result for the same task_id is not a supported use of this function
    -- callers needing to correct a bad import must use a new task_id,
    matching HANDOFF_V1's own "same TASK_ID" round-trip identity
    contract rather than inventing a silent mutation path for it)."""
    root = Path(root)
    prior_state = _load_state(root, task_id)
    if prior_state is not None and prior_state.get("state") == STATE_RESULT_CONSUMED:
        return ImportOutcome(task_id=task_id, state=STATE_RESULT_CONSUMED,
                             question_id=prior_state.get("question_id"))

    # GAP-V2-011 fix: a damaged/malformed stored HANDOFF_V1.md must
    # produce a real, structured RESULT_REJECTED outcome, never an
    # uncaught exception escaping this function.
    try:
        handoff = _load_handoff(root, task_id)
    except (OSError, HandoffParseError) as exc:
        reason = exc.reason if isinstance(exc, HandoffParseError) else "STORED_HANDOFF_UNREADABLE"
        return ImportOutcome(task_id=task_id, state=STATE_RESULT_REJECTED,
                             parse_error=f"MALFORMED_STORED_HANDOFF:{reason}")
    if handoff is None:
        return ImportOutcome(task_id=task_id, state=STATE_RESULT_REJECTED,
                             parse_error="NO_MATCHING_HANDOFF")

    state = prior_state or {"task_id": task_id, "state": STATE_HANDOFF_READY}
    state["state"] = STATE_RESULT_RETURNED
    _save_state(root, task_id, state)

    result_md_path = Path(result_md_path)
    try:
        text = result_md_path.read_text(encoding="utf-8")
        result = _result_mod.from_markdown(text)
    except (OSError, ResultParseError) as exc:
        reason = exc.reason if isinstance(exc, ResultParseError) else "RESULT_FILE_UNREADABLE"
        state["state"] = STATE_RESULT_REJECTED
        state["result_status"] = None
        _save_state(root, task_id, state)
        return ImportOutcome(task_id=task_id, state=STATE_RESULT_REJECTED, parse_error=reason)

    state["state"] = STATE_RESULT_VALIDATING
    _save_state(root, task_id, state)
    # own_result_path: the real on-disk path the human actually pointed at,
    # root-relative/POSIX-normalized -- a caller-derived fact, never a
    # model-declared one, letting validate_result() exempt a self-
    # referential RETURNED_ARTIFACTS entry (the result citing its own
    # storage location) from scope enforcement without weakening the
    # GAP-V2-010/F2 fix for any other path. Left None (no exemption) if
    # result_md_path is not actually under root.
    try:
        own_result_path = str(result_md_path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        own_result_path = None
    validation = _result_mod.validate_result(handoff, result, root=root, own_result_path=own_result_path)

    if not validation.accepted:
        state["state"] = STATE_RESULT_REJECTED
        state["result_status"] = result.result_status
        _save_state(root, task_id, state)
        return ImportOutcome(task_id=task_id, state=STATE_RESULT_REJECTED,
                             validation=validation, result=result)

    state["state"] = STATE_RESULT_ACCEPTED
    state["result_status"] = result.result_status
    _save_state(root, task_id, state)

    # GAP-V2-011 (R5), retry-safe consumption. Every side effect below is
    # idempotent for one task_id, so a retry after ANY partial failure
    # (question filed but registry append failed; registry appended but the
    # final state save failed) converges on exactly one question and exactly
    # one registry row:
    #   * a conflicting registry row (same task, different result) is a real
    #     CONSUMPTION_CONFLICT rejection, never silently adopted;
    #   * the question is looked up by its stable question_key before filing;
    #   * the registry row is appended only if none exists for the task.
    existing_row = _registry_row(root, task_id)
    if existing_row is not None and (existing_row.get("result_status") != result.result_status
                                     or Path(existing_row.get("result_path", "")).resolve() != Path(result_md_path).resolve()):
        return ImportOutcome(task_id=task_id, state=STATE_RESULT_REJECTED,
                             parse_error="CONSUMPTION_CONFLICT", validation=validation, result=result)

    question_id = _consume_result(root, handoff, result, str(result_md_path))
    state["question_id"] = question_id
    _save_state(root, task_id, state)

    # GAP-V2-011 fix, ordering (dispatch: "append the registry before
    # asserting RESULT_CONSUMED"): the real, always-fires evidence-store
    # consumer runs BEFORE the state file claims RESULT_CONSUMED, so a
    # crash between the two leaves state at RESULT_ACCEPTED (a real,
    # inspectable "consumption did not finish" fact) rather than a false
    # RESULT_CONSUMED with no matching registry row.
    _append_registry(root, handoff, result, str(result_md_path), question_id)

    state["state"] = STATE_RESULT_CONSUMED
    state["question_id"] = question_id
    _save_state(root, task_id, state)

    return ImportOutcome(task_id=task_id, state=STATE_RESULT_CONSUMED,
                         validation=validation, question_id=question_id, result=result)


def import_result(root: Path, task_id: str, result_md_path: Path) -> ImportOutcome:
    """Public entry point. Runs the full ingestion pipeline
    (`_import_result_inner`) and then persists the resolved NEXT_ACTION for
    every state-changing outcome (Human Non-Scheduler Execution Contract:
    "after every state-changing operation persist NEXT_ACTION") -- a
    REJECTED or CONSUMED result never leaves the workflow waiting for
    someone to decide what happens next. An idempotent replay of an
    already-CONSUMED task re-persists the same record."""
    outcome = _import_result_inner(root, task_id, result_md_path)
    if _task_dir(Path(root), task_id).is_dir():
        from . import execution_contract as _ec
        findings = list(outcome.validation.findings) if outcome.validation is not None else []
        if outcome.parse_error == "CONSUMPTION_CONFLICT":
            event = "RESULT_REJECTED_VALIDATION"
        else:
            event = _ec.event_for_import_outcome(
                outcome.state,
                result_status=(outcome.result.result_status if outcome.result is not None
                               else (_load_state(Path(root), task_id) or {}).get("result_status")),
                findings=findings, parse_error=outcome.parse_error)
        _ec.persist_next_action(Path(root), task_id, _ec.resolve_next_action(event))
    return outcome


def _consume_result(root: Path, handoff: ModelHandoffV1, result: ModelResultV1,
                    result_path: str) -> Optional[str]:
    """The real Canonical Consumer (dispatch section 12/17). A result
    with no consumer is a capability island -- this function is what
    makes `MODEL_OUTPUT_CONSUMED = YES` a real, not merely claimed, fact.

    HUMAN_DECISION_REQUIRED (either the result's own declared field, or a
    result_status of that same name) routes to the SAME real
    `QuestionQueueStore.add_question()` mechanism the M6 Golden Workflow's
    own HumanGate stage already uses -- never a second, parallel
    human-decision channel."""
    needs_human = bool(result.human_decisions_required) or result.result_status == "HUMAN_DECISION_REQUIRED"
    if not needs_human:
        return None
    store = QuestionQueueStore(root)
    question_key = f"model_handoff:{handoff.task_id}"
    for existing in store.list_questions():
        if existing.get("question_key") == question_key:
            return existing["id"]
    decisions = list(result.human_decisions_required) or [
        f"Model result for {handoff.task_id} ({handoff.target_model}) requires a human decision "
        f"(status={result.result_status})."]
    # normalize_grounding_evidence() only accepts the real
    # {"summary": str, "evidence_path": str} shape, both required
    # together -- never a caller-invented key.
    grounding_evidence = None
    if result.evidence_refs:
        grounding_evidence = {"summary": "; ".join(decisions), "evidence_path": result.evidence_refs[0]}
    question = store.add_question(
        domain="env",
        question="; ".join(decisions),
        context_path=result_path,
        options=["accept", "reject", "request_correction"],
        recommendation="accept" if result.result_status == "PASS" else "request_correction",
        assumption_if_unanswered="request_correction",
        question_key=question_key,
        grounding_evidence=grounding_evidence,
        context={"task_id": handoff.task_id, "target_model": handoff.target_model,
                 "task_type": handoff.task_type, "result_status": result.result_status},
    )
    return question["id"]


def _registry_row(root: Path, task_id: str) -> Optional[Dict[str, str]]:
    path = _registry_path(root)
    if not path.is_file():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("task_id") == task_id:
                return row
    return None


def _append_registry(root: Path, handoff: ModelHandoffV1, result: ModelResultV1,
                     result_path: str, question_id: Optional[str]) -> None:
    """The second, always-fires Canonical Consumer: a real, structural,
    append-only registry row for EVERY consumed result, regardless of
    whether it also needed a human decision -- the "evidence store" /
    "capability-status update" consumer path the architecture doc names."""
    from .change_impact import _git
    if _registry_row(root, handoff.task_id) is not None:
        return  # idempotent: one consumed result -> exactly one registry row
    path = _registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    rc, head, _ = _git(Path(root), ["rev-parse", "HEAD"])
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_REGISTRY_FIELDS)
        if is_new:
            w.writeheader()
        w.writerow({
            "task_id": handoff.task_id, "target_model": handoff.target_model,
            "task_type": handoff.task_type, "state": STATE_RESULT_CONSUMED,
            "result_status": result.result_status, "handoff_path": str(_task_dir(root, handoff.task_id) / "HANDOFF_V1.md"),
            "result_path": result_path,
            "consumed_at_head": head.strip() if rc == 0 else "",
            "question_id": question_id or "",
        })


# --- Human Transport UX (dispatch section 9) ---------------------------------
# A standalone `python -m` front door, matching `model_agent_tool_router.py`'s
# own established precedent in this repo (its own docstring: cli.py/gates.py
# are large files under heavy concurrent-edit pressure; adding a verb there
# is deliberately deferred rather than pre-empting that choice a second time).
#
# Human responsibility is transport only (architecture doc): `export`
# prints the real path to copy FROM; `import` takes the real path a human
# saved the target model's own reply TO. Neither verb waits/polls for the
# human -- both return immediately, matching "must not busy-wait."

def execute_verb(argv: Optional[List[str]] = None) -> int:
    """Verbs: status --task-id <id> --root <dir> |
    export --task-id <id> --task-type <t> --target-model codex|chatgpt
      --project-id <p> --objective <o> --root <dir>
      [--allowed-files a,b] [--forbidden-files c,d]
      [--input-evidence-refs e,f] [--governance-trigger <phrase>]
      [--known-facts g,h] [--expected-output-type <t>] [--json] |
    import --task-id <id> --result-file <path> --root <dir> [--json]"""
    import argparse

    parser = argparse.ArgumentParser(prog="model_handoff_workflow")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_status = sub.add_parser("status")
    p_status.add_argument("--task-id", required=True)
    p_status.add_argument("--root", default=".")
    p_status.add_argument("--json", action="store_true")

    p_export = sub.add_parser("export")
    p_export.add_argument("--task-id", required=True)
    p_export.add_argument("--task-type", required=True)
    p_export.add_argument("--target-model", required=True, choices=_handoff_mod.TARGET_MODELS)
    p_export.add_argument("--project-id", required=True)
    p_export.add_argument("--objective", required=True)
    p_export.add_argument("--root", default=".")
    p_export.add_argument("--allowed-files", default="")
    p_export.add_argument("--forbidden-files", default="")
    p_export.add_argument("--input-evidence-refs", default="")
    p_export.add_argument("--governance-trigger", default=None)
    p_export.add_argument("--known-facts", default="")
    p_export.add_argument("--open-questions", default="")
    p_export.add_argument("--independence-requirement", default=None)
    p_export.add_argument("--expected-output-type", default="review_findings",
                          choices=_handoff_mod.EXPECTED_OUTPUT_TYPES)
    p_export.add_argument("--human-decision-required", action="store_true")
    p_export.add_argument("--json", action="store_true")

    p_import = sub.add_parser("import")
    p_import.add_argument("--task-id", required=True)
    p_import.add_argument("--result-file", required=True)
    p_import.add_argument("--root", default=".")
    p_import.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    def _split(s: str) -> List[str]:
        return [x.strip() for x in s.split(",") if x.strip()]

    if args.verb == "status":
        state = current_state(args.root, args.task_id)
        if args.json:
            print(json.dumps({"task_id": args.task_id, "state": state}))
        else:
            print(f"task_id={args.task_id} state={state}")
        return 0 if state is not None else 1

    if args.verb == "export":
        scope = TaskBoundary(
            task_id=args.task_id,
            allowed_path_prefixes=tuple(_split(args.allowed_files)),
            forbidden_paths=tuple(_split(args.forbidden_files)),
        )
        handoff = _handoff_mod.build_handoff(
            args.root, task_id=args.task_id, task_type=args.task_type,
            target_model=args.target_model, project_id=args.project_id,
            objective=args.objective, scope=scope,
            input_evidence_refs=_split(args.input_evidence_refs),
            governance_trigger=args.governance_trigger,
            known_facts=_split(args.known_facts), open_questions=_split(args.open_questions),
            independence_requirement=args.independence_requirement,
            expected_output_type=args.expected_output_type,
            human_decision_required=args.human_decision_required,
        )
        path = export_handoff(args.root, handoff)
        metrics = _handoff_mod.context_size_bytes(handoff)
        if args.json:
            print(json.dumps({"handoff_path": str(path), "state": STATE_WAITING_FOR_HUMAN_TRANSPORT,
                              **metrics}))
        else:
            print(f"HANDOFF_GENERATED: {path}")
            print(f"state={STATE_WAITING_FOR_HUMAN_TRANSPORT}")
            print(f"handoff_bytes={metrics['handoff_bytes']} (proxy, not a token count)")
        return 0

    if args.verb == "import":
        outcome = import_result(args.root, args.task_id, args.result_file)
        if args.json:
            print(json.dumps(outcome.to_dict()))
        else:
            print(f"task_id={outcome.task_id} state={outcome.state}")
            if outcome.parse_error:
                print(f"parse_error={outcome.parse_error}")
            if outcome.validation:
                print(f"validation={outcome.validation.to_dict()}")
        return 0 if outcome.consumed else 1

    return 1


if __name__ == "__main__":
    import sys
    sys.exit(execute_verb())
