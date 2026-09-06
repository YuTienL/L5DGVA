"""dv_harness/pattern_fragment_ir.py -- convert a reusable PORTION of an
existing subsystem pattern (not a whole scenario) into a `PatternFragmentIR`:
a small, composable record carrying preconditions, postconditions,
resources_used, and produced/consumed events, so a later system-level
composition step has something concrete to reason about instead of having to
re-read raw pattern text, 2026-09-06.

WHAT THIS IS, AND WHAT IT IS EXPLICITLY NOT
--------------------------------------------
This module is deliberately narrower than two real, pre-existing modules it
is easy to confuse it with:

* `pattern_ir_assembly.py` assembles the FULL `PatternIR` for ONE scenario --
  its `global`/`dut`/`fw_policy`/`vip`/`check` command layers, built from a
  whole ScenarioIR-shaped item list. It answers "what does this ENTIRE
  scenario's pattern look like, laid out into its five fixed layers".

* `example_composition.py` composes multiple already-qualified WHOLE VIP
  EXAMPLES (host example + device example, etc.) into one scenario, gated by
  a 7-condition compatibility check over example-level metadata (VIP
  version, role, protocol mode, agent config, sequencer ownership, reset/
  clock assumptions).

This module answers a different, smaller question: given ONE existing
pattern's command list, and a caller-declared PORTION of it (an index range,
or a marker-delimited slice -- never the whole thing by default), extract
that portion as a self-describing FRAGMENT: what resources it touches, what
events it needs already asserted before it can run (`preconditions`), and
what events/state it leaves behind for whatever runs after it
(`postconditions`). It never assembles a scenario's five PatternIR layers,
never checks VIP-example-level compatibility, and never itself decides that
a composed multi-fragment pattern is functionally correct -- only whether
the produced/consumed EVENT GRAPH across a caller-declared fragment order is
self-consistent (`check_fragment_chain_readiness`), which is a purely
structural check, not a verdict on subsystem behaviour.

Per this batch's file-safety scope, this module imports NOTHING from
`pattern_ir_assembly.py`, `example_composition.py`, or any other claimed
batch file. `fragment_source` (the pattern a fragment is cut from) is
accepted as a plain, duck-typed object -- a dict or attribute-bearing object
carrying a `commands`-shaped list (aliases below) -- exactly the same
tolerant-alias, never-guess convention `pattern_ir_assembly.py` and
`example_composition.py` both already established for their own duck-typed
inputs, re-derived locally here rather than imported.

EVIDENCE TRUTH RULE, APPLIED HERE
------------------------------------
Every fact this module reports about a fragment is read directly off the
caller-supplied command entries -- a resource, a produced event, a consumed
event, is only ever recorded when some command in the fragment actually
declares it. Two distinct "nothing here" outcomes are kept separate and
never collapsed into one:

* the field was genuinely computed and turned out empty (e.g. a fragment
  whose commands declare resources but no events at all -- `produced_events`
  and `consumed_events` are legitimately `[]`), vs.
* NO command in the fragment declares that kind of fact at all, so nothing
  could be computed -- reported as `event_evidence_status` /
  `resource_evidence_status` of `NOT_AVAILABLE`, never silently folded into
  an empty list that would look identical to the first case.

Likewise, a fragment selection that could not be resolved at all (an
unrecognisable `fragment_source`, an out-of-range `fragment_range`, a marker
that is never found) is raised as `PatternFragmentIrError` -- never silently
treated as "select nothing" or "select everything".

PRECONDITION / POSTCONDITION DERIVATION
------------------------------------------
Given the fragment's own produced-event and consumed-event sets:

* a consumed event that is NOT also produced somewhere within the same
  fragment is reported as a derived `precondition`
  (`DERIVED_UNRESOLVED_CONSUMED_EVENT`) -- something the fragment assumes is
  already true when it starts, that this fragment alone cannot supply.
* a produced event that is NOT also consumed somewhere within the same
  fragment is reported as a derived `postcondition`
  (`DERIVED_UNCONSUMED_PRODUCED_EVENT`) -- something the fragment leaves
  behind for a later fragment (or the rest of the host pattern) to consume.

This is a plain set-difference over the fragment's own declared events --
it assumes no internal ordering guarantee beyond "declared inside this
fragment" (consistent with a fragment being a REUSABLE portion, not a fully
sequenced scenario), and it is never used to invent an event no command
actually declared. A caller may additionally pass `declared_preconditions`/
`declared_postconditions` (plain strings or small dicts) for facts a human
or an upstream tool already knows are true but that no event field in this
fragment's commands proves mechanically -- these are kept, tagged
`DECLARED`, distinct from the `DERIVED_*` ones.

FRAGMENT-CHAIN READINESS (COMPOSITION-FACING, STRUCTURAL ONLY)
-------------------------------------------------------------------
`check_fragment_chain_readiness()` takes an ordered list of
`PatternFragmentIR`-shaped fragments (the caller's declared composition
order for a candidate system-level pattern) and checks, per fragment, which
of its `DERIVED_UNRESOLVED_CONSUMED_EVENT` preconditions are covered by an
EARLIER fragment's postcondition/produced event in that same order. This is
a purely structural graph check over caller-declared event names -- it never
claims the resulting composed pattern is behaviourally correct, only that
its event graph is (or is not) self-consistent in the declared order, and it
reports `UNCOVERED` rather than guessing a precondition is satisfied.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _dataclass_field
from typing import Optional


# ===========================================================================
# Honest-status sentinels (Evidence Truth Rule)
# ===========================================================================

SELECTION_EXPLICIT_RANGE = "EXPLICIT_RANGE"
SELECTION_MARKER_RANGE = "MARKER_RANGE"
SELECTION_WHOLE_SOURCE = "WHOLE_SOURCE_USED_NO_RANGE_DECLARED"

STATUS_COMPLETE = "COMPLETE"
STATUS_PARTIAL_TEXT_EVIDENCE = "PARTIAL_TEXT_EVIDENCE"

EVIDENCE_DERIVED = "DERIVED"
EVIDENCE_NOT_AVAILABLE = "NOT_AVAILABLE"

COND_SOURCE_DECLARED = "DECLARED"
COND_SOURCE_DERIVED_UNRESOLVED_CONSUMED = "DERIVED_UNRESOLVED_CONSUMED_EVENT"
COND_SOURCE_DERIVED_UNCONSUMED_PRODUCED = "DERIVED_UNCONSUMED_PRODUCED_EVENT"

CHAIN_COVERED = "COVERED"
CHAIN_UNCOVERED = "UNCOVERED"
CHAIN_STATUS_ALL_COVERED = "ALL_COVERED"
CHAIN_STATUS_HAS_UNCOVERED = "HAS_UNCOVERED_PRECONDITIONS"
CHAIN_STATUS_NO_PRECONDITIONS = "NO_PRECONDITIONS"


class PatternFragmentIrError(ValueError):
    """`fragment_source` could not be read as a commands-bearing pattern at
    all, or the caller's fragment-selection request (`fragment_range`,
    `start_marker`/`end_marker`) could not be resolved against it. Raised
    rather than silently selecting zero or all commands, per the Evidence
    Truth Rule: "no such fragment could be located" and "the fragment is
    empty" are different facts."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        self.reason = reason
        self.detail = detail or {}
        super().__init__(f"{reason}: {self.detail}")


# ===========================================================================
# Duck-typed field access (re-derived locally; imports nothing)
# ===========================================================================

def _field(item, *names):
    """Return the first non-empty value found under any of `names`, trying
    dict-style `.get` first, then attribute access -- so a plain dict, a
    dataclass, or a SimpleNamespace-shaped source/command are all accepted.
    Returns `None` (never `""`) when nothing is found."""
    use_get = hasattr(item, "get") and hasattr(item, "__contains__")
    for name in names:
        if use_get:
            try:
                value = item.get(name)
            except TypeError:
                value = None
        else:
            value = getattr(item, name, None)
        if value not in (None, ""):
            return value
    return None


def _as_list(value):
    """Normalize a scalar-or-collection field value to a plain list of
    strings. `None` becomes `[]` (absence, not a fabricated entry)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)]


#: Aliases this module accepts for the commands list carried by a pattern
#: `fragment_source`. Deliberately narrow -- an unrecognized shape is
#: reported as an error, never guessed at.
SOURCE_COMMANDS_ALIASES = ("commands", "pattern_commands", "command_list")

#: Per-command field aliases. `text` is descriptive/traceability content;
#: `resources`, `produces`, `consumes` are the mechanical facts this module
#: derives resources_used/produced_events/consumed_events from.
CMD_TEXT_ALIASES = ("text", "command", "cmd", "instruction")
CMD_RESOURCE_ALIASES = ("resource", "resources", "uses_resource", "driver", "agent")
CMD_PRODUCES_ALIASES = ("produces_event", "produced_event", "emits_event", "emits", "produces")
CMD_CONSUMES_ALIASES = (
    "consumes_event", "required_event", "requires_event", "waits_for_event", "consumes",
)


def _cmd_text(cmd):
    return _field(cmd, *CMD_TEXT_ALIASES)


def _cmd_resources(cmd):
    return _as_list(_field(cmd, *CMD_RESOURCE_ALIASES))


def _cmd_produces(cmd):
    return _as_list(_field(cmd, *CMD_PRODUCES_ALIASES))


def _cmd_consumes(cmd):
    return _as_list(_field(cmd, *CMD_CONSUMES_ALIASES))


def _dedupe_sorted(items):
    return sorted(set(items))


# ===========================================================================
# The fragment record
# ===========================================================================

@dataclass
class PatternFragmentIR:
    fragment_id: str
    source_pattern_id: Optional[str]
    selection_status: str
    covers_entire_source: bool
    source_command_count: int
    fragment_command_count: int
    fragment_commands: list = _dataclass_field(default_factory=list)
    unclassified_commands: list = _dataclass_field(default_factory=list)
    resources_used: list = _dataclass_field(default_factory=list)
    resource_evidence_status: str = EVIDENCE_NOT_AVAILABLE
    produced_events: list = _dataclass_field(default_factory=list)
    consumed_events: list = _dataclass_field(default_factory=list)
    event_evidence_status: str = EVIDENCE_NOT_AVAILABLE
    preconditions: list = _dataclass_field(default_factory=list)
    postconditions: list = _dataclass_field(default_factory=list)
    status: str = STATUS_COMPLETE


# ===========================================================================
# Fragment selection
# ===========================================================================

def _resolve_commands(fragment_source):
    commands = _field(fragment_source, *SOURCE_COMMANDS_ALIASES)
    if not isinstance(commands, list):
        raise PatternFragmentIrError(
            "SOURCE_COMMANDS_NOT_LIST",
            {"aliases_tried": SOURCE_COMMANDS_ALIASES, "found_type": type(commands).__name__},
        )
    return commands


def _select_by_range(commands, fragment_range):
    total = len(commands)
    if (
        not isinstance(fragment_range, (list, tuple))
        or len(fragment_range) != 2
        or not all(isinstance(v, int) for v in fragment_range)
    ):
        raise PatternFragmentIrError("INVALID_FRAGMENT_RANGE", {"fragment_range": fragment_range})
    start, end = fragment_range
    if not (0 <= start < end <= total):
        raise PatternFragmentIrError(
            "INVALID_FRAGMENT_RANGE",
            {"fragment_range": fragment_range, "source_command_count": total},
        )
    return start, end - 1, SELECTION_EXPLICIT_RANGE


def _select_by_markers(commands, start_marker, end_marker):
    if bool(start_marker) != bool(end_marker):
        raise PatternFragmentIrError(
            "MARKER_PAIR_INCOMPLETE",
            {"start_marker": start_marker, "end_marker": end_marker},
        )
    start_idx = next(
        (i for i, c in enumerate(commands) if start_marker in (_cmd_text(c) or "")), None
    )
    if start_idx is None:
        raise PatternFragmentIrError("START_MARKER_NOT_FOUND", {"start_marker": start_marker})
    end_idx = next(
        (
            i
            for i in range(start_idx, len(commands))
            if end_marker in (_cmd_text(commands[i]) or "")
        ),
        None,
    )
    if end_idx is None:
        raise PatternFragmentIrError(
            "END_MARKER_NOT_FOUND",
            {"end_marker": end_marker, "searched_from_index": start_idx},
        )
    return start_idx, end_idx, SELECTION_MARKER_RANGE


def _merge_declared(existing, declared, source_tag):
    """Append caller-declared precondition/postcondition entries (plain
    strings or small dicts) to `existing`, tagged `DECLARED`. Never
    deduplicates against derived entries -- a declared fact and a
    mechanically-derived one naming the same event are different pieces of
    evidence and both are kept."""
    for entry in declared or []:
        if isinstance(entry, dict):
            event = _field(entry, "event", "name", "text")
        else:
            event = entry
        if event in (None, ""):
            continue
        existing.append({"event": str(event), "source": source_tag})


def extract_pattern_fragment(
    fragment_source,
    *,
    fragment_range=None,
    start_marker=None,
    end_marker=None,
    declared_preconditions=None,
    declared_postconditions=None,
    fragment_id=None,
):
    """Extract a `PatternFragmentIR` covering a caller-declared PORTION of
    `fragment_source`'s command list.

    Exactly one selection mechanism should be supplied: `fragment_range`
    (a `(start, end)` half-open index pair) OR `start_marker`/`end_marker`
    (an inclusive, text-matched slice). If neither is supplied, the entire
    source command list is used as the fragment -- honestly flagged via
    `selection_status=SELECTION_WHOLE_SOURCE` and `covers_entire_source=True`
    rather than silently treated as if a portion had been declared.
    """
    commands = _resolve_commands(fragment_source)
    total = len(commands)

    if fragment_range is not None:
        start_idx, end_idx, selection_status = _select_by_range(commands, fragment_range)
    elif start_marker is not None or end_marker is not None:
        start_idx, end_idx, selection_status = _select_by_markers(commands, start_marker, end_marker)
    else:
        if total == 0:
            raise PatternFragmentIrError("EMPTY_FRAGMENT_SELECTION", {"source_command_count": 0})
        start_idx, end_idx, selection_status = 0, total - 1, SELECTION_WHOLE_SOURCE

    selected = commands[start_idx : end_idx + 1]
    if not selected:
        raise PatternFragmentIrError(
            "EMPTY_FRAGMENT_SELECTION",
            {"start_idx": start_idx, "end_idx": end_idx},
        )

    source_pattern_id = _field(fragment_source, "pattern_id", "id", "name", "source_id")

    resources, produced, consumed = [], [], []
    unclassified = []
    any_resource_field = False
    any_event_field = False
    for cmd in selected:
        text = _cmd_text(cmd)
        if text is None:
            unclassified.append(cmd)
        cmd_resources = _cmd_resources(cmd)
        cmd_produces = _cmd_produces(cmd)
        cmd_consumes = _cmd_consumes(cmd)
        if cmd_resources:
            any_resource_field = True
        if cmd_produces or cmd_consumes:
            any_event_field = True
        resources.extend(cmd_resources)
        produced.extend(cmd_produces)
        consumed.extend(cmd_consumes)

    resources_used = _dedupe_sorted(resources)
    produced_events = _dedupe_sorted(produced)
    consumed_events = _dedupe_sorted(consumed)

    produced_set = set(produced_events)
    consumed_set = set(consumed_events)

    preconditions = [
        {"event": ev, "source": COND_SOURCE_DERIVED_UNRESOLVED_CONSUMED}
        for ev in sorted(consumed_set - produced_set)
    ]
    postconditions = [
        {"event": ev, "source": COND_SOURCE_DERIVED_UNCONSUMED_PRODUCED}
        for ev in sorted(produced_set - consumed_set)
    ]
    _merge_declared(preconditions, declared_preconditions, COND_SOURCE_DECLARED)
    _merge_declared(postconditions, declared_postconditions, COND_SOURCE_DECLARED)

    frag_id = fragment_id or f"FRAG::{source_pattern_id or 'UNKNOWN_SOURCE'}::{start_idx}-{end_idx}"

    return PatternFragmentIR(
        fragment_id=str(frag_id),
        source_pattern_id=source_pattern_id,
        selection_status=selection_status,
        covers_entire_source=(len(selected) == total),
        source_command_count=total,
        fragment_command_count=len(selected),
        fragment_commands=list(selected),
        unclassified_commands=unclassified,
        resources_used=resources_used,
        resource_evidence_status=EVIDENCE_DERIVED if any_resource_field else EVIDENCE_NOT_AVAILABLE,
        produced_events=produced_events,
        consumed_events=consumed_events,
        event_evidence_status=EVIDENCE_DERIVED if any_event_field else EVIDENCE_NOT_AVAILABLE,
        preconditions=preconditions,
        postconditions=postconditions,
        status=STATUS_PARTIAL_TEXT_EVIDENCE if unclassified else STATUS_COMPLETE,
    )


# ===========================================================================
# Composition-facing: structural event-chain readiness across a declared
# fragment order
# ===========================================================================

def _fragment_field(fragment, name):
    return _field(fragment, name)


def check_fragment_chain_readiness(fragments, *, order=None):
    """Check, for a caller-declared ORDER of `PatternFragmentIR`-shaped
    fragments, whether each fragment's `DERIVED_UNRESOLVED_CONSUMED_EVENT`
    preconditions are covered by an earlier fragment's postcondition or
    produced event in that same order.

    `fragments`: a non-empty list of fragment-shaped items (dict or
    `PatternFragmentIR`), each readable for `fragment_id`, `preconditions`,
    `postconditions`, `produced_events`.
    `order`: an optional explicit list of `fragment_id` values giving the
    declared composition order; when omitted, `fragments`' own list order is
    used. When supplied, it must name exactly the same set of fragment ids
    present in `fragments` -- a mismatch is reported as an error rather than
    silently reordering or dropping fragments.

    Returns a list of per-fragment dicts (in the resolved order):
    `{fragment_id, position, precondition_status: [...], chain_status}`.
    This is a purely structural event-graph check -- it never asserts the
    resulting composed pattern is behaviourally correct.
    """
    if not fragments:
        raise PatternFragmentIrError("EMPTY_FRAGMENT_LIST", {})

    by_id = {}
    for f in fragments:
        fid = _fragment_field(f, "fragment_id")
        by_id[fid] = f

    if order is not None:
        if set(order) != set(by_id.keys()):
            raise PatternFragmentIrError(
                "ORDER_MISMATCH",
                {"declared_order": list(order), "fragment_ids": sorted(by_id.keys())},
            )
        resolved_order = list(order)
    else:
        resolved_order = [_fragment_field(f, "fragment_id") for f in fragments]

    results = []
    available_events = set()
    for position, fid in enumerate(resolved_order):
        frag = by_id[fid]
        preconditions = _fragment_field(frag, "preconditions") or []
        unresolved = [
            p for p in preconditions
            if (p.get("source") if isinstance(p, dict) else None)
            == COND_SOURCE_DERIVED_UNRESOLVED_CONSUMED
        ]

        precondition_status = []
        for p in unresolved:
            event = p.get("event") if isinstance(p, dict) else p
            covered = event in available_events
            precondition_status.append(
                {"event": event, "status": CHAIN_COVERED if covered else CHAIN_UNCOVERED}
            )

        if not unresolved:
            chain_status = CHAIN_STATUS_NO_PRECONDITIONS
        elif all(s["status"] == CHAIN_COVERED for s in precondition_status):
            chain_status = CHAIN_STATUS_ALL_COVERED
        else:
            chain_status = CHAIN_STATUS_HAS_UNCOVERED

        results.append(
            {
                "fragment_id": fid,
                "position": position,
                "precondition_status": precondition_status,
                "chain_status": chain_status,
            }
        )

        postconditions = _fragment_field(frag, "postconditions") or []
        for p in postconditions:
            event = p.get("event") if isinstance(p, dict) else p
            if event:
                available_events.add(event)
        for event in (_fragment_field(frag, "produced_events") or []):
            available_events.add(event)

    return results
