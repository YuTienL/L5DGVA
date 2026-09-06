"""dv_harness/programming_sequence_ir.py -- a canonical Programming Sequence
IR (Init -> Configure -> Enable -> ... -> Reset) and a step-ordering
validator that checks it against real register facts.

WHAT THIS IS
------------
A "programming sequence" is the ordered list of register writes/reads/waits a
bring-up or test sequence performs (the same kind of artifact `init_seq.py`
already models for the Gate-2 precondition layer, at a coarser
block/register/value grain). This module adds the piece `init_seq.py` does
NOT have: a canonical PHASE vocabulary (INIT/CONFIGURE/ENABLE/.../RESET) the
steps are checked against, plus a real dependency-ordering check driven by a
register's own declared `depends_on` list -- e.g. "the DMA enable bit cannot
be written before the DMA base-address register", expressed as
`{"name": "dma_ctrl", "depends_on": ["dma_base_addr"]}` in the register
facts rather than hand-reviewed.

WHY NOT init_seq.py's OWN VALIDATOR. `init_seq.validate_init_seq()` checks
schema shape and kind-conditional required fields (a `wait_condition` needs a
`timeout_us`, etc.) -- it has no phase concept and no register-dependency
concept at all. `directed_test_steps()` resolves a step's register NAME
against `sys_regmap.json` to get an absolute address; it never asks whether
writing that register at that point in the sequence is itself legal. Nothing
in `init_seq.py` is duplicated here: this module is imported by nothing in
that file and imports nothing from it beyond the read-only vocabulary review
that produced this design (see the module docstring's own note below).

WHY A DUCK-TYPED REGISTER INPUT, NOT `register_excel_extract.py`. That module
is owned by a separate concurrent task in this batch. Per this batch's file-
safety scope, this module never imports it and never waits on it. Instead it
accepts the same SHAPE that module's real output already carries --
`register_excel_extract.RegisterIR.to_dict()` emits (among other keys)
`"name"`/`"offset"` (via `register_name`/`offset`) and
`"access_type"` (via `normalize_access_type()`'s canonical short tokens: RW,
RO, WO, W1C, RW1C, RC, WC, W1S, RS, or an unrecognized-but-plausible short
mnemonic). This module's own `RegisterFact` duck-types exactly that plus one
field neither `register_excel_extract.py` nor `init_seq.py` carries today,
`depends_on` (a list of register names). Once the two modules are wired
together (a future integration step, not this task), a caller can pass
`register_excel_extract.extract_register_map(...)`'s registers straight
through -- as a list of `{"name": ..., "offset": ..., "access_type": ...,
"depends_on": [...]}` dicts, `depends_on` defaulting to `[]` for any register
whose Excel source carries no such column -- with zero translation code
needed here. `register_facts_from_dicts()` is that acceptance boundary and is
the only place this module knows about the shape at all.

EVIDENCE TRUTH RULE, applied to this module specifically. A sequence with no
register facts supplied cannot be validated for access-type legality or
dependency ordering -- reporting ORDER_VALID in that case would silently claim
a check that never ran. `validate_step_ordering()` returns `NOT_AVAILABLE`
naming exactly that when `register_facts` is empty/None, and `NOT_APPLICABLE`
when the IR itself carries zero steps (nothing to validate). Only when real
facts and real steps are both present does a genuine ORDER_VALID/
ORDER_INVALID verdict become possible, mirroring `power_intent.py`'s and
`golden_scenario.py`'s own
"absent evidence is an honest distinct status, never a default" contract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Canonical phase vocabulary: Init -> Configure -> Enable -> {RUN-family,
# any order among themselves} -> Reset.
#
# Ranks are deliberately non-contiguous in the middle (RUN/WAIT/VERIFY/
# DISABLE all share rank 3) because the task's own "..." between Enable and
# Reset says those interior phases are not mutually ordered -- only that
# every one of them comes after ENABLE and before RESET. INIT/CONFIGURE/
# ENABLE/RESET are the four phases the task names explicitly and each gets
# its own strict rank.
# ---------------------------------------------------------------------------

PHASE_INIT = "INIT"
PHASE_CONFIGURE = "CONFIGURE"
PHASE_ENABLE = "ENABLE"
PHASE_RUN = "RUN"
PHASE_WAIT = "WAIT"
PHASE_VERIFY = "VERIFY"
PHASE_DISABLE = "DISABLE"
PHASE_RESET = "RESET"

PHASE_RANK: Dict[str, int] = {
    PHASE_INIT: 0,
    PHASE_CONFIGURE: 1,
    PHASE_ENABLE: 2,
    PHASE_RUN: 3,
    PHASE_WAIT: 3,
    PHASE_VERIFY: 3,
    PHASE_DISABLE: 3,
    PHASE_RESET: 4,
}

CANONICAL_PHASES = tuple(PHASE_RANK.keys())

# Actions a step may perform against its register. "wait" steps carry no
# register at all (a pure delay/poll-until-condition), matching
# `init_seq.py`'s own `wait_us`/`wait_condition` step kinds.
ACTION_WRITE = "write"
ACTION_READ = "read"
ACTION_WAIT = "wait"
STEP_ACTIONS = (ACTION_WRITE, ACTION_READ, ACTION_WAIT)

# Access-type tokens this module treats as write-legal / read-legal.
# Deliberately a SMALL, LOCAL classification (not imported from
# `register_excel_extract.normalize_access_type()`'s `_ACCESS_ALIASES`,
# which this batch does not import per the file-safety scope) covering only
# the canonical short tokens that module's own docstring says
# `normalize_access_type()` folds spelling variants onto -- RW, RO, WO, W1C,
# RW1C, RC, WC, W1S, RS. An access_type this module has never seen is
# reported UNKNOWN_ACCESS_TYPE rather than silently assumed legal for either
# direction.
_WRITE_LEGAL_ACCESS = frozenset({"RW", "WO", "W1C", "RW1C", "WC", "W1S"})
_READ_LEGAL_ACCESS = frozenset({"RW", "RO", "W1C", "RW1C", "RC", "RS"})
_KNOWN_ACCESS_TYPES = _WRITE_LEGAL_ACCESS | _READ_LEGAL_ACCESS

# Finding codes. Deliberately share no token with `models.Status` -- see
# `assert_no_verification_verdict_vocabulary()` below.
FINDING_UNKNOWN_PHASE = "UNKNOWN_PHASE"
FINDING_PHASE_ORDER_VIOLATION = "PHASE_ORDER_VIOLATION"
FINDING_UNKNOWN_REGISTER = "UNKNOWN_REGISTER"
FINDING_ACCESS_TYPE_MISMATCH = "ACCESS_TYPE_MISMATCH"
FINDING_UNKNOWN_ACCESS_TYPE = "UNKNOWN_ACCESS_TYPE"
FINDING_DANGLING_DEPENDENCY = "DANGLING_DEPENDENCY"
FINDING_DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
FINDING_DEPENDENCY_NOT_YET_SATISFIED = "DEPENDENCY_NOT_YET_SATISFIED"

_SEVERITY_ERROR = "ERROR"
_SEVERITY_WARNING = "WARNING"

# This module's own status vocabulary -- deliberately NOT `PASS`/`FAIL`
# (both are real `models.Status` members; see
# `assert_no_verification_verdict_vocabulary()` below), following the same
# naming discipline `dependency_supply_chain.py`'s `POLICY_CLEAN`/
# `POLICY_FINDINGS` already established for this exact reason.
STATUS_ORDER_VALID = "ORDER_VALID"
STATUS_ORDER_INVALID = "ORDER_INVALID"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"


class ProgrammingSequenceIRError(ValueError):
    """A ProgrammingSequenceIR or register-facts input is malformed -- raised
    rather than silently coerced, so a caller cannot validate step ordering
    against a sequence or a fact list that was never actually well-formed."""


@dataclass
class RegisterFact:
    """One entry of the duck-typed register-facts input. Mirrors the shape
    `register_excel_extract.RegisterIR.to_dict()` already emits
    (`name`/`offset`/`access_type`), plus `depends_on` -- see the module
    docstring's wiring note. `access_type` and `depends_on` are OPTIONAL:
    a fact carrying neither is still a real fact (its name exists), it is
    just unusable for the access-type and dependency checks specifically,
    which is reported per-finding rather than assumed clean."""
    name: str
    offset: Optional[str] = None
    access_type: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)


@dataclass
class ProgrammingSequenceStep:
    """One step of the IR. `register` is None only for a `wait` action (a
    pure delay/poll step with nothing to program)."""
    index: int
    phase: str
    action: str
    register: Optional[str] = None
    value: Optional[str] = None
    description: Optional[str] = None


@dataclass
class ProgrammingSequenceIR:
    """The ordered sequence itself. `name` identifies which programming
    sequence this is (e.g. the DUT/protocol bring-up it models) purely for
    reporting -- it is never interpreted."""
    name: str
    steps: List[ProgrammingSequenceStep] = field(default_factory=list)


@dataclass
class Finding:
    code: str
    severity: str
    step_index: Optional[int]
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity,
                "step_index": self.step_index, "message": self.message}


# ---------------------------------------------------------------------------
# Construction / parsing
# ---------------------------------------------------------------------------

def programming_sequence_ir_from_dict(doc: dict) -> ProgrammingSequenceIR:
    """Build a ProgrammingSequenceIR from a plain dict (e.g. loaded JSON):
    `{"name": ..., "steps": [{"index", "phase", "action", "register",
    "value", "description"}, ...]}`. Raises `ProgrammingSequenceIRError` on
    a structurally invalid document rather than silently dropping a
    malformed step -- a caller must never validate ordering over a sequence
    that was silently truncated."""
    if not isinstance(doc, dict):
        raise ProgrammingSequenceIRError(f"expected a dict document, got {type(doc).__name__}")
    name = doc.get("name")
    if not name or not isinstance(name, str):
        raise ProgrammingSequenceIRError("programming sequence document requires a non-empty 'name'")
    raw_steps = doc.get("steps")
    if raw_steps is None:
        raise ProgrammingSequenceIRError("programming sequence document requires a 'steps' list")
    if not isinstance(raw_steps, list):
        raise ProgrammingSequenceIRError(f"'steps' must be a list, got {type(raw_steps).__name__}")

    steps: List[ProgrammingSequenceStep] = []
    for i, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise ProgrammingSequenceIRError(f"step {i} is not a dict: {raw!r}")
        idx = raw.get("index", i)
        phase = raw.get("phase")
        action = raw.get("action")
        if not phase or not isinstance(phase, str):
            raise ProgrammingSequenceIRError(f"step {idx} requires a non-empty 'phase'")
        if action not in STEP_ACTIONS:
            raise ProgrammingSequenceIRError(
                f"step {idx} has action {action!r}, must be one of {STEP_ACTIONS}")
        register = raw.get("register")
        if action != ACTION_WAIT and not register:
            raise ProgrammingSequenceIRError(
                f"step {idx} has action {action!r} but no 'register' -- only 'wait' steps "
                "may omit a register")
        steps.append(ProgrammingSequenceStep(
            index=idx, phase=phase.upper(), action=action, register=register,
            value=raw.get("value"), description=raw.get("description"),
        ))

    expected_indices = list(range(len(steps)))
    actual_indices = [s.index for s in steps]
    if actual_indices != expected_indices:
        raise ProgrammingSequenceIRError(
            f"step indices must be contiguous and ascending from 0; got {actual_indices}, "
            f"expected {expected_indices} -- a gap usually means a step was dropped while "
            "editing; fix the sequence rather than renumbering around the gap")

    return ProgrammingSequenceIR(name=name, steps=steps)


def load_programming_sequence(path) -> ProgrammingSequenceIR:
    """Load a ProgrammingSequenceIR from a real .json file on disk."""
    text = Path(path).read_text(encoding="utf-8")
    return programming_sequence_ir_from_dict(json.loads(text))


def register_facts_from_dicts(facts: Optional[Sequence[dict]]) -> List[RegisterFact]:
    """Build the duck-typed register-facts list from plain dicts -- the
    acceptance boundary described in the module docstring. `None` and `[]`
    both come back as `[]`; the caller of `validate_step_ordering()` is what
    turns an empty facts list into the honest NOT_AVAILABLE status, not this
    function, so this stays usable standalone (e.g. by a test asserting a
    single fact's shape) without that status baked in.

    Raises on a fact with no `name` (an unnamed register fact cannot be
    joined against anything a step could reference) but is otherwise
    permissive -- `offset`/`access_type`/`depends_on` are each independently
    optional, per `RegisterFact`'s own docstring."""
    if not facts:
        return []
    out: List[RegisterFact] = []
    for i, raw in enumerate(facts):
        if not isinstance(raw, dict):
            raise ProgrammingSequenceIRError(f"register fact {i} is not a dict: {raw!r}")
        name = raw.get("name")
        if not name or not isinstance(name, str):
            raise ProgrammingSequenceIRError(f"register fact {i} requires a non-empty 'name'")
        depends_on = raw.get("depends_on") or []
        if not isinstance(depends_on, list):
            raise ProgrammingSequenceIRError(
                f"register fact {name!r} has 'depends_on' that is not a list: {depends_on!r}")
        access_type = raw.get("access_type")
        out.append(RegisterFact(
            name=name, offset=raw.get("offset"),
            access_type=(access_type.upper() if isinstance(access_type, str) else access_type),
            depends_on=list(depends_on),
        ))
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _detect_dependency_cycle(facts_by_name: Dict[str, RegisterFact]) -> Optional[List[str]]:
    """Real DFS cycle detection over the register facts' own `depends_on`
    graph (a register's dependency claims are checked against EACH OTHER,
    independent of any particular sequence) -- a cyclic dependency claim in
    the facts themselves ("A depends on B depends on A") can never be
    satisfied by any ordering, so it is reported once rather than as a
    per-step ordering violation that would recur for every step touching the
    cycle. Returns the cycle as a list of register names (closing back on
    the first), or None if the graph is acyclic. Only edges whose target
    register actually exists in `facts_by_name` are walked -- a dangling
    dependency is a separate finding (`FINDING_DANGLING_DEPENDENCY`), not a
    cycle."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {n: WHITE for n in facts_by_name}
    path: List[str] = []

    def visit(name: str) -> Optional[List[str]]:
        color[name] = GRAY
        path.append(name)
        for dep in facts_by_name[name].depends_on:
            if dep not in facts_by_name:
                continue
            if color.get(dep) == GRAY:
                cycle_start = path.index(dep)
                return path[cycle_start:] + [dep]
            if color.get(dep, WHITE) == WHITE:
                found = visit(dep)
                if found is not None:
                    return found
        path.pop()
        color[name] = BLACK
        return None

    for name in facts_by_name:
        if color[name] == WHITE:
            found = visit(name)
            if found is not None:
                return found
    return None


def validate_step_ordering(ir: ProgrammingSequenceIR,
                            register_facts: Optional[Sequence[RegisterFact]]) -> dict:
    """Validate `ir`'s step ordering against `register_facts`. Returns a
    report dict:

        {"schema_version", "status", "sequence_name", "step_count",
         "register_fact_count", "findings": [...], "reason" (only set for
         NOT_AVAILABLE/NOT_APPLICABLE)}

    `status` is one of STATUS_ORDER_VALID/STATUS_ORDER_INVALID/STATUS_NOT_AVAILABLE/
    STATUS_NOT_APPLICABLE (this module's own vocabulary -- see
    `assert_no_verification_verdict_vocabulary()`).

    Three independent checks, each producing its own finding code:

      1. PHASE ORDERING -- `PHASE_RANK`'s canonical Init->Configure->
         Enable->{RUN-family}->Reset order must be non-decreasing across the
         sequence. A step whose phase's rank is LOWER than the highest rank
         already seen is `PHASE_ORDER_VIOLATION`; a step naming a phase this
         module does not know is `UNKNOWN_PHASE` (never silently ranked).
      2. ACCESS-TYPE LEGALITY -- a `write` step against a register whose
         `access_type` is not in `_WRITE_LEGAL_ACCESS` (or a `read` step
         against one not in `_READ_LEGAL_ACCESS`) is
         `ACCESS_TYPE_MISMATCH`. A register the facts do not name at all is
         `UNKNOWN_REGISTER` (this check, and dependency ordering below, are
         both then skipped for that step -- there is nothing to check an
         unknown register's access against). A register whose access_type is
         a token this module has never seen is `UNKNOWN_ACCESS_TYPE`
         (WARNING: a real but unrecognized mnemonic per
         `register_excel_extract.normalize_access_type()`'s own docstring,
         not necessarily wrong).
      3. DEPENDENCY ORDERING -- a register's declared `depends_on` names
         other registers that must be WRITTEN earlier in the same sequence.
         A dependency naming a register absent from `register_facts`
         entirely is `DANGLING_DEPENDENCY` (a data-quality issue in the
         facts themselves). A circular `depends_on` claim among the facts is
         `DEPENDENCY_CYCLE`, reported once. Otherwise, a step writing a
         register whose depends_on has not yet been written earlier in THIS
         sequence is `DEPENDENCY_NOT_YET_SATISFIED`.

    All three checks are ERROR-severity except `UNKNOWN_ACCESS_TYPE`
    (WARNING). `status` is ORDER_INVALID iff at least one ERROR finding
    exists."""
    facts_list = list(register_facts) if register_facts else []

    if not ir.steps:
        return {"schema_version": SCHEMA_VERSION, "status": STATUS_NOT_APPLICABLE,
                "sequence_name": ir.name, "step_count": 0,
                "register_fact_count": len(facts_list), "findings": [],
                "reason": "the programming sequence carries zero steps -- nothing to validate"}

    if not facts_list:
        return {"schema_version": SCHEMA_VERSION, "status": STATUS_NOT_AVAILABLE,
                "sequence_name": ir.name, "step_count": len(ir.steps),
                "register_fact_count": 0, "findings": [],
                "reason": ("no register facts supplied -- cannot check access-type legality or "
                           "dependency ordering against real register facts. Supply a real "
                           "register-facts list (e.g. register_excel_extract's extracted "
                           "registers, once wired) rather than assuming the sequence is clean")}

    facts_by_name = {f.name: f for f in facts_list}
    findings: List[Finding] = []

    cycle = _detect_dependency_cycle(facts_by_name)
    if cycle is not None:
        findings.append(Finding(
            code=FINDING_DEPENDENCY_CYCLE, severity=_SEVERITY_ERROR, step_index=None,
            message=f"circular depends_on claim in register facts: {' -> '.join(cycle)}"))

    written_registers: set = set()
    highest_rank_seen = -1
    highest_rank_phase_seen: Optional[str] = None

    for step in ir.steps:
        rank = PHASE_RANK.get(step.phase)
        if rank is None:
            findings.append(Finding(
                code=FINDING_UNKNOWN_PHASE, severity=_SEVERITY_ERROR, step_index=step.index,
                message=(f"step {step.index} declares phase {step.phase!r}, which is not one "
                         f"of the known phases {CANONICAL_PHASES}")))
        elif rank < highest_rank_seen:
            findings.append(Finding(
                code=FINDING_PHASE_ORDER_VIOLATION, severity=_SEVERITY_ERROR, step_index=step.index,
                message=(f"step {step.index} is phase {step.phase!r} (rank {rank}), which comes "
                         f"after phase {highest_rank_phase_seen!r} (rank {highest_rank_seen}) "
                         f"already seen at an earlier step -- canonical order is "
                         f"{CANONICAL_PHASES}")))
        else:
            highest_rank_seen = rank
            highest_rank_phase_seen = step.phase

        if step.action == ACTION_WAIT or not step.register:
            continue

        fact = facts_by_name.get(step.register)
        if fact is None:
            findings.append(Finding(
                code=FINDING_UNKNOWN_REGISTER, severity=_SEVERITY_ERROR, step_index=step.index,
                message=(f"step {step.index} references register {step.register!r}, which does "
                         "not appear in the supplied register facts")))
            continue

        if fact.access_type is None:
            pass  # no access_type at all is reported nowhere here -- unknowable, not wrong
        elif fact.access_type not in _KNOWN_ACCESS_TYPES:
            findings.append(Finding(
                code=FINDING_UNKNOWN_ACCESS_TYPE, severity=_SEVERITY_WARNING, step_index=step.index,
                message=(f"step {step.index} references register {step.register!r} whose "
                         f"access_type {fact.access_type!r} is not a recognized mnemonic -- "
                         "cannot judge read/write legality")))
        elif step.action == ACTION_WRITE and fact.access_type not in _WRITE_LEGAL_ACCESS:
            findings.append(Finding(
                code=FINDING_ACCESS_TYPE_MISMATCH, severity=_SEVERITY_ERROR, step_index=step.index,
                message=(f"step {step.index} WRITEs register {step.register!r}, whose "
                         f"access_type is {fact.access_type!r} (not write-legal)")))
        elif step.action == ACTION_READ and fact.access_type not in _READ_LEGAL_ACCESS:
            findings.append(Finding(
                code=FINDING_ACCESS_TYPE_MISMATCH, severity=_SEVERITY_ERROR, step_index=step.index,
                message=(f"step {step.index} READs register {step.register!r}, whose "
                         f"access_type is {fact.access_type!r} (not read-legal)")))

        for dep_name in fact.depends_on:
            if dep_name not in facts_by_name:
                findings.append(Finding(
                    code=FINDING_DANGLING_DEPENDENCY, severity=_SEVERITY_ERROR, step_index=step.index,
                    message=(f"register {step.register!r} (used at step {step.index}) declares "
                             f"depends_on {dep_name!r}, which does not appear in the supplied "
                             "register facts at all")))
            elif dep_name not in written_registers:
                findings.append(Finding(
                    code=FINDING_DEPENDENCY_NOT_YET_SATISFIED, severity=_SEVERITY_ERROR,
                    step_index=step.index,
                    message=(f"step {step.index} writes register {step.register!r}, which "
                             f"depends_on {dep_name!r}, but {dep_name!r} has not been written "
                             "earlier in this sequence")))

        if step.action == ACTION_WRITE:
            written_registers.add(step.register)

    status = STATUS_ORDER_INVALID if any(f.severity == _SEVERITY_ERROR for f in findings) else STATUS_ORDER_VALID
    return {"schema_version": SCHEMA_VERSION, "status": status, "sequence_name": ir.name,
            "step_count": len(ir.steps), "register_fact_count": len(facts_list),
            "findings": [f.to_dict() for f in findings]}


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's status/finding vocabularies must share no token with
    `models.Status` -- the same guarantee `dependency_supply_chain.py` /
    `capability_evolution.py` / `benchmark_dataset.py` /
    `verification_strategy.py` / `subsystem_maturity_gate.py` each hold for
    their own vocabularies, so a reader can never mistake a step-ordering
    finding for a stage-gate verdict."""
    from .models import Status

    verdicts = {s.value for s in Status}
    own = {STATUS_ORDER_VALID, STATUS_ORDER_INVALID, STATUS_NOT_AVAILABLE, STATUS_NOT_APPLICABLE,
           FINDING_UNKNOWN_PHASE, FINDING_PHASE_ORDER_VIOLATION, FINDING_UNKNOWN_REGISTER,
           FINDING_ACCESS_TYPE_MISMATCH, FINDING_UNKNOWN_ACCESS_TYPE,
           FINDING_DANGLING_DEPENDENCY, FINDING_DEPENDENCY_CYCLE,
           FINDING_DEPENDENCY_NOT_YET_SATISFIED}
    overlap = own & verdicts
    if overlap:
        raise AssertionError(
            f"programming_sequence_ir vocabulary collides with models.Status: {sorted(overlap)}")


assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# Ad hoc entry point
# ---------------------------------------------------------------------------

def execute_verb(verb: str, *, sequence_json: str, facts_json: Optional[str] = None,
                  as_json: bool = False) -> "tuple[str, int]":
    """Shared implementation for `python -m dv_harness.programming_sequence_ir
    validate --sequence <file> [--facts <file>]`. Returns (text, exit_code):
    0 ORDER_VALID, 1 ORDER_INVALID, 2 NOT_AVAILABLE/NOT_APPLICABLE/malformed
    input. Runs nothing, submits nothing, approves nothing."""
    if verb != "validate":
        return f"unknown programming-sequence-ir verb {verb!r}", 2
    try:
        ir = load_programming_sequence(sequence_json)
        facts_raw = json.loads(Path(facts_json).read_text(encoding="utf-8")) if facts_json else []
        facts = register_facts_from_dicts(facts_raw)
    except ProgrammingSequenceIRError as e:
        return f"ProgrammingSequenceIRError: {e}", 2
    except (OSError, json.JSONDecodeError) as e:
        return f"failed to load input: {e}", 2

    report = validate_step_ordering(ir, facts)
    if as_json:
        return json.dumps(report, indent=2), _EXIT_CODE_BY_STATUS[report["status"]]

    lines = [f"programming sequence {report['sequence_name']!r}: {report['status']}",
             f"  steps={report['step_count']} register_facts={report['register_fact_count']}"]
    if report.get("reason"):
        lines.append(f"  reason: {report['reason']}")
    for f in report["findings"]:
        lines.append(f"  [{f['severity']}] {f['code']} (step {f['step_index']}): {f['message']}")
    return "\n".join(lines), _EXIT_CODE_BY_STATUS[report["status"]]


_EXIT_CODE_BY_STATUS = {
    STATUS_ORDER_VALID: 0, STATUS_ORDER_INVALID: 1, STATUS_NOT_AVAILABLE: 2, STATUS_NOT_APPLICABLE: 2,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.programming_sequence_ir",
        description="Validate a ProgrammingSequenceIR's step ordering (Init->Configure->"
                    "Enable->...->Reset phase ordering, register access-type legality, and "
                    "depends_on ordering) against a duck-typed register-facts list. Reads "
                    "only; runs/submits/approves nothing.")
    ap.add_argument("verb", choices=("validate",))
    ap.add_argument("--sequence", required=True, dest="sequence_json",
                    help="ProgrammingSequenceIR JSON document.")
    ap.add_argument("--facts", default=None, dest="facts_json",
                    help="Register facts JSON: a list of {name, offset, access_type, "
                         "depends_on} dicts.")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.verb, sequence_json=a.sequence_json,
                              facts_json=a.facts_json, as_json=a.as_json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
