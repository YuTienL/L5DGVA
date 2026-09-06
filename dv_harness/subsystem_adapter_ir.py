"""dv_harness/subsystem_adapter_ir.py -- SubsystemAdapterIR: a compatibility facade
over an EXISTING subsystem's real task/sequence names (2026-09-06).

THE GAP THIS CLOSES
-------------------
A subsystem-mode verification environment (see `.claude/skills/CORE/pattern-architecture/
SKILL.md`) already carries its own real, already-generated task/sequence names -- an
`init_seq.py`-style directed test step, a `branch_b*`-driven VIP sequence, a hand-authored
`command.txt` task. Nothing anywhere spoke a FIXED, cross-subsystem vocabulary of logical
operations against those real names: a caller wanting "start this subsystem" or "wait until
it is ready" had no single place to ask that question without first learning that
particular subsystem's own naming convention. Building a SECOND task/sequence catalog from
scratch, or guessing a plausible task name for an operation nobody actually declared, would
be exactly the "invent a stub implementation" the Evidence Truth Rule forbids.

This module is the facade only. It never authors a task/sequence body, never invents a
plausible-sounding name for an operation the caller did not map, and never imports any of
this batch's concurrently-claimed files (see this project's CLAUDE.md gap-closure header for
the full claimed-file list) -- a mapping is accepted as a generic, duck-typed
`{operation, existing_task_or_sequence_name}` record, exactly the shape the task specifies,
so this module stays usable regardless of which concurrently-built module eventually owns
producing that mapping for a real subsystem.

THE FIXED LOGICAL-OPERATION VOCABULARY
---------------------------------------
Exactly eight operations, never more, never fewer for a given build of this module:

    configure / start / stop / reset / wait_ready / execute / monitor / get_status

`assert_logical_operations_fixed()` runs at import time and pins this tuple's exact
membership -- a future edit that silently widens or narrows the vocabulary fails a test
rather than drifting unnoticed.

RESOLUTION, AND THE ONE HONESTY RULE THIS MODULE EXISTS TO ENFORCE
--------------------------------------------------------------------
`build_subsystem_adapter_ir()` takes the caller-supplied mapping list and, for each of the
eight fixed logical operations, resolves it to exactly one of two outcomes:

  * RESOLVED -- the caller supplied a real, non-empty task/sequence name for this logical
    operation. That name is carried through VERBATIM (whitespace-trimmed only); this module
    never rewrites, normalizes, or "corrects" it.
  * UNSUPPORTED_OPERATION -- no real mapped task/sequence exists for this logical operation,
    either because the caller's mapping list never mentioned it at all, or because it was
    mentioned with an empty/whitespace-only name (an explicit "we have nothing for this"
    marker some callers may prefer over omitting the entry). Both paths report the SAME
    honest status and never synthesize a fabricated task name to fill the gap -- this is
    the module's one hard rule, restated from the task's own instruction: "never synthesize
    or invent a stub implementation for a missing mapping."

A malformed mapping entry (not a mapping shape at all, missing the `operation` key, missing
the `existing_task_or_sequence_name` key entirely -- as opposed to supplying it as an empty
string, which is a legitimate "explicitly unmapped" declaration) is a hard input error
(`SubsystemAdapterIRError`), never silently skipped or defaulted, mirroring
`task_return_model.TaskReturnModelError`'s "never silently repaired" discipline for the
identical reason: repairing a malformed declaration on the caller's behalf would hide a real
authoring defect from the person who needs to see it.

A logical operation mapped MORE THAN ONCE in one caller-supplied list is likewise a hard
input error rather than a silent last-one-wins resolution -- two conflicting declarations
for the same operation is exactly the kind of ambiguity this module refuses to guess through.

An entry naming an operation OUTSIDE the fixed eight-operation vocabulary is never silently
dropped either: it is collected into `unrecognized_mappings` on the resulting IR so a caller
can see and correct it, and it never counts toward resolving (or leaving unsupported) any of
the eight real logical operations.

WHAT THIS MODULE DOES NOT DO
------------------------------
It performs no build, no simulation, no LSF submission, mints no approval, and holds no
stage gate of its own. It authors no task/sequence body and validates nothing about whether
a resolved task/sequence name is itself syntactically or semantically correct -- that is
this batch's other, separately-scoped modules' job (or a downstream generator's). It reads
and resolves a caller-supplied mapping and reports, honestly, which of the eight fixed
logical operations that mapping actually covers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# The fixed logical-operation vocabulary. Exactly these eight, in this order.
# ---------------------------------------------------------------------------

LOGICAL_OPERATIONS: Tuple[str, ...] = (
    "configure",
    "start",
    "stop",
    "reset",
    "wait_ready",
    "execute",
    "monitor",
    "get_status",
)


def assert_logical_operations_fixed() -> None:
    """Pin the exact membership of `LOGICAL_OPERATIONS`. A future edit that silently
    widens or narrows the vocabulary must fail this assertion rather than drift
    unnoticed -- the same "held total / checked at import" discipline several sibling
    modules in this codebase apply to their own fixed vocabularies."""
    expected = (
        "configure",
        "start",
        "stop",
        "reset",
        "wait_ready",
        "execute",
        "monitor",
        "get_status",
    )
    if LOGICAL_OPERATIONS != expected:
        raise AssertionError(
            f"LOGICAL_OPERATIONS drifted from its fixed vocabulary: "
            f"expected {expected!r}, got {LOGICAL_OPERATIONS!r}"
        )
    if len(set(LOGICAL_OPERATIONS)) != len(LOGICAL_OPERATIONS):
        raise AssertionError(
            f"LOGICAL_OPERATIONS carries a duplicate entry: {LOGICAL_OPERATIONS!r}"
        )


assert_logical_operations_fixed()

# ---------------------------------------------------------------------------
# Resolution status vocabulary.
# ---------------------------------------------------------------------------

STATUS_RESOLVED = "RESOLVED"
STATUS_UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"

ALL_RESOLUTION_STATUSES: Tuple[str, ...] = (
    STATUS_RESOLVED,
    STATUS_UNSUPPORTED_OPERATION,
)


class SubsystemAdapterIRError(ValueError):
    """Raised on a malformed or ambiguous caller-supplied mapping input -- never
    silently repaired, per the Evidence Truth Rule's "never silently default or
    guess". Mirrors `task_return_model.TaskReturnModelError`'s `code`/`detail`
    shape."""

    def __init__(self, code: str, detail: Optional[Dict[str, Any]] = None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


@dataclass(frozen=True)
class OperationResolution:
    """One fixed logical operation's real resolution outcome."""

    operation: str
    status: str
    resolved_task_or_sequence_name: Optional[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "resolved_task_or_sequence_name": self.resolved_task_or_sequence_name,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SubsystemAdapterIR:
    """A compatibility facade over one subsystem's real task/sequence names,
    resolved against the fixed `LOGICAL_OPERATIONS` vocabulary.

    `operations` always carries exactly one `OperationResolution` per entry in
    `LOGICAL_OPERATIONS` -- never more, never fewer, and never omitted for an
    operation the caller's mapping did not cover (that operation still gets a
    real `UNSUPPORTED_OPERATION` record rather than being absent from the IR).
    """

    subsystem_name: Optional[str]
    operations: Dict[str, OperationResolution]
    unrecognized_mappings: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)

    def resolve(self, operation: str) -> OperationResolution:
        """Look up one logical operation's real resolution. Raises
        `SubsystemAdapterIRError` for an operation outside the fixed vocabulary --
        asking this facade about an operation it does not define is a caller
        error, never a silent `UNSUPPORTED_OPERATION`."""
        if operation not in LOGICAL_OPERATIONS:
            raise SubsystemAdapterIRError(
                "UNKNOWN_LOGICAL_OPERATION",
                {
                    "requested_operation": operation,
                    "fixed_vocabulary": list(LOGICAL_OPERATIONS),
                },
            )
        return self.operations[operation]

    def is_supported(self, operation: str) -> bool:
        """True iff `operation` (a member of the fixed vocabulary) resolved to a
        real mapped task/sequence name. Raises for an operation outside the fixed
        vocabulary, same as `resolve()`."""
        return self.resolve(operation).status == STATUS_RESOLVED

    def resolved_operations(self) -> Tuple[str, ...]:
        """The fixed-vocabulary operations that have a real mapped task/sequence,
        in `LOGICAL_OPERATIONS` order."""
        return tuple(
            op for op in LOGICAL_OPERATIONS if self.operations[op].status == STATUS_RESOLVED
        )

    def unsupported_operations(self) -> Tuple[str, ...]:
        """The fixed-vocabulary operations with NO real mapped task/sequence, in
        `LOGICAL_OPERATIONS` order."""
        return tuple(
            op
            for op in LOGICAL_OPERATIONS
            if self.operations[op].status == STATUS_UNSUPPORTED_OPERATION
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem_name": self.subsystem_name,
            "operations": {
                op: self.operations[op].to_dict() for op in LOGICAL_OPERATIONS
            },
            "unrecognized_mappings": [dict(m) for m in self.unrecognized_mappings],
            "resolved_operations": list(self.resolved_operations()),
            "unsupported_operations": list(self.unsupported_operations()),
        }


def _get_field(entry: Any, key: str) -> Any:
    """Duck-typed field access: works against a plain dict OR any mapping-like
    object exposing `.get`/`__getitem__`. Returns a private sentinel-free
    distinction between "the key is absent" and "the key is present with value
    None/empty" by raising `KeyError`/returning via a marker -- callers below
    handle both explicitly."""
    if isinstance(entry, Mapping):
        return entry.get(key, _MISSING)
    getter = getattr(entry, "get", None)
    if callable(getter):
        try:
            return getter(key, _MISSING)
        except TypeError:
            pass
    try:
        return entry[key]
    except (KeyError, IndexError, TypeError):
        return _MISSING


class _Missing:
    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "<MISSING>"


_MISSING = _Missing()


def build_subsystem_adapter_ir(
    mapping_entries: Sequence[Any],
    subsystem_name: Optional[str] = None,
) -> SubsystemAdapterIR:
    """Build a `SubsystemAdapterIR` from a caller-supplied list of
    `{operation, existing_task_or_sequence_name}` mapping records (duck-typed --
    plain dicts, or any mapping-like object exposing the same two keys).

    Every entry in `mapping_entries` is validated:
      * the entry itself must be mapping-shaped (dict-like); anything else is a
        hard `SubsystemAdapterIRError` (`MAPPING_ENTRY_NOT_MAPPING_SHAPED`).
      * `operation` must be present and a non-empty string
        (`MAPPING_ENTRY_MISSING_OPERATION`).
      * `existing_task_or_sequence_name` must be PRESENT as a key -- its VALUE
        may legitimately be an empty/whitespace-only string (an explicit "no
        real mapping for this operation" declaration) or a non-empty string (a
        real mapped name), but the key's outright ABSENCE is a malformed entry
        (`MAPPING_ENTRY_MISSING_TASK_NAME`) rather than an implicit empty value.
      * an operation named MORE THAN ONCE across the whole list is a hard error
        (`DUPLICATE_OPERATION_MAPPING`) -- never a silent last-one-wins pick.

    An operation named in `mapping_entries` that is NOT one of the fixed
    `LOGICAL_OPERATIONS` is never silently dropped: it is recorded on the
    resulting IR's `unrecognized_mappings`, and it never resolves (or leaves
    unsupported) any of the eight real logical operations.

    Every one of the eight fixed logical operations then resolves to exactly
    one `OperationResolution`: `RESOLVED` when the caller supplied a real,
    non-empty (after stripping) task/sequence name for it, `UNSUPPORTED_OPERATION`
    otherwise -- whether because the operation was never mentioned at all, or
    because it was mentioned with an empty/whitespace-only name.
    """
    if not isinstance(mapping_entries, (list, tuple)):
        raise SubsystemAdapterIRError(
            "MAPPING_ENTRIES_NOT_A_SEQUENCE",
            {"mapping_entries": repr(mapping_entries)},
        )

    resolved_names: Dict[str, str] = {}
    declared_but_empty: Dict[str, str] = {}
    unrecognized: List[Dict[str, Any]] = []
    seen_operations: Dict[str, int] = {}

    for idx, entry in enumerate(mapping_entries):
        if not isinstance(entry, Mapping) and not hasattr(entry, "get"):
            raise SubsystemAdapterIRError(
                "MAPPING_ENTRY_NOT_MAPPING_SHAPED",
                {"index": idx, "entry": repr(entry)},
            )

        raw_operation = _get_field(entry, "operation")
        if raw_operation is _MISSING or not isinstance(raw_operation, str) or not raw_operation.strip():
            raise SubsystemAdapterIRError(
                "MAPPING_ENTRY_MISSING_OPERATION",
                {"index": idx, "entry": repr(entry)},
            )
        operation = raw_operation.strip()

        raw_name = _get_field(entry, "existing_task_or_sequence_name")
        if raw_name is _MISSING:
            raise SubsystemAdapterIRError(
                "MAPPING_ENTRY_MISSING_TASK_NAME",
                {"index": idx, "operation": operation, "entry": repr(entry)},
            )

        if operation in LOGICAL_OPERATIONS:
            if operation in seen_operations:
                raise SubsystemAdapterIRError(
                    "DUPLICATE_OPERATION_MAPPING",
                    {
                        "operation": operation,
                        "first_index": seen_operations[operation],
                        "duplicate_index": idx,
                    },
                )
            seen_operations[operation] = idx

            name_str = raw_name.strip() if isinstance(raw_name, str) else ""
            if name_str:
                resolved_names[operation] = name_str
            else:
                declared_but_empty[operation] = operation
        else:
            unrecognized.append(
                {
                    "operation": operation,
                    "existing_task_or_sequence_name": raw_name,
                    "reason": (
                        f"{operation!r} is not part of this module's fixed "
                        f"logical-operation vocabulary "
                        f"({', '.join(LOGICAL_OPERATIONS)})"
                    ),
                }
            )

    operations: Dict[str, OperationResolution] = {}
    for op in LOGICAL_OPERATIONS:
        if op in resolved_names:
            operations[op] = OperationResolution(
                operation=op,
                status=STATUS_RESOLVED,
                resolved_task_or_sequence_name=resolved_names[op],
                reason=(
                    f"resolved from caller-supplied mapping to real task/sequence "
                    f"{resolved_names[op]!r}"
                ),
            )
        elif op in declared_but_empty:
            operations[op] = OperationResolution(
                operation=op,
                status=STATUS_UNSUPPORTED_OPERATION,
                resolved_task_or_sequence_name=None,
                reason=(
                    "caller's mapping declared this operation but supplied no "
                    "real (non-empty) task/sequence name for it; no stub was "
                    "synthesized"
                ),
            )
        else:
            operations[op] = OperationResolution(
                operation=op,
                status=STATUS_UNSUPPORTED_OPERATION,
                resolved_task_or_sequence_name=None,
                reason=(
                    "no mapping was supplied for this operation; no stub was "
                    "synthesized"
                ),
            )

    return SubsystemAdapterIR(
        subsystem_name=subsystem_name,
        operations=operations,
        unrecognized_mappings=tuple(unrecognized),
    )
