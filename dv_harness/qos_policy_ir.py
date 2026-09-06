"""dv_harness/qos_policy_ir.py -- QoS Policy IR + Ordering Contention Verification.

Two things, and only two, matching this task's own scope:

  1. `QoSPolicyIR` -- a per-master QoS-level/priority/weight mapping, built from real
     caller-supplied spec/RTL evidence. Every entry MUST carry a real evidence citation
     (a spec/RTL line reference, a register field name, whatever the caller actually read
     this fact from) -- an entry with a master id and no evidence is refused, never
     silently accepted as if a number had a source. This module never invents a QoS
     level/priority/weight itself: it is a shape + validation layer over facts the
     caller already extracted, exactly the same "transcribe, never author" boundary
     several sibling extraction modules in this codebase already draw for their own
     domains.
  2. `verify_qos_contention()` -- a contention-verification helper that checks whether a
     DECLARED QoS ordering (a total order over masters, ties permitted) was actually
     OBSERVED in a caller-supplied transaction-order record. It reports one of three
     honest verdicts -- VERIFIED / VIOLATED / UNKNOWN -- and never collapses "we could
     not tell" into either of the other two.

WHY THIS IS A PURELY ORDINAL CHECK, NEVER A PERFORMANCE ONE
-------------------------------------------------------------
Per this batch's own explicit instruction, Performance Verification (any numeric
latency/bandwidth/throughput target) is OUT OF SCOPE for this entire session -- an
earlier user decision deferred that whole domain. This module computes and claims
NOTHING about how fast a transaction was serviced, how much bandwidth a master got, or
what an acceptable latency bound is. The only question `verify_qos_contention()` answers
is ORDINAL: among transactions that genuinely contended for one resource at one point in
time (grouped by the caller's own declared `window_id`), did a higher-declared-priority
master's transaction get serviced no later, in RELATIVE POSITION, than a
lower-declared-priority master's transaction. `position` is an caller-supplied ordinal
index (a grant order, a scoreboard sequence number) -- never a timestamp, a cycle count,
or anything this module could mistake for a latency measurement.

WHY EVIDENCE IS MANDATORY ON EVERY ENTRY
------------------------------------------
A QoS policy fact (a master's priority level, its arbitration weight) is exactly the
kind of claim the Evidence Truth Rule guards against fabricating. `build_qos_policy_ir()`
therefore REFUSES any entry that carries a master id with no `evidence` citation --
raising `QoSPolicyIRError`, never silently dropping the entry or accepting it with a
blank citation. An entry that legitimately carries no priority/weight/level fact at all
(the caller looked and found nothing to report) is NOT an error -- it is recorded with
`status = NO_QOS_FACTS_DECLARED`, an honest absence distinct from a malformed record.

WHY THE PRIORITY ORDERING IS NEVER GUESSED FROM A BARE NUMBER
-----------------------------------------------------------------
A numeric QoS/priority field's meaning ("does a bigger number mean higher priority, or
lower?") is a real protocol/RTL convention this module has no basis to assume -- AMBA's
own AXI QoS field and a hand-rolled arbitration priority register do not agree with each
other, and guessing wrong would silently invert every ordering-contention verdict below
it. `derive_priority_ordering()` therefore requires the caller to DECLARE
`priority_convention` explicitly (`HIGHER_IS_HIGHER_PRIORITY` /
`LOWER_IS_HIGHER_PRIORITY`); with no declared convention (or fewer than two masters
carrying a real declared `priority` value) it reports `ORDERING_NOT_AVAILABLE` with the
real reason, never a guessed ordering. A caller who already holds a directly-declared
ordering (a spec table, a register default) may skip this derivation entirely and hand
`verify_qos_contention()` that ordering straight away -- this module has no opinion about
which of the two the caller should use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union


class QoSPolicyIRError(Exception):
    """A malformed QoS-policy input or ordering declaration. Always carries a real
    `code` and a `detail` dict naming exactly what was wrong -- never a bare message,
    so a caller can branch on the failure kind."""

    def __init__(self, code: str, detail: Optional[dict] = None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


#: The two fields no QoS-policy entry may omit. `evidence` is the citation (a real
#: spec/RTL line reference, register field name, or equivalent) proving this fact was
#: read from a real source rather than assumed.
REQUIRED_ENTRY_FIELDS = ("master_id", "evidence")

#: The three QoS facts a caller MAY declare per master. At least one is expected for a
#: genuinely useful entry, but zero is not an error -- see `ENTRY_STATUS_NO_QOS_FACTS`.
QOS_FACT_FIELDS = ("qos_level", "priority", "weight")

#: The entry carries at least one real QoS fact (qos_level/priority/weight).
ENTRY_STATUS_DECLARED = "DECLARED"
#: The entry has a master_id and real evidence, but declares no QoS fact at all -- an
#: honest absence, never conflated with a malformed record.
ENTRY_STATUS_NO_QOS_FACTS = "NO_QOS_FACTS_DECLARED"

#: The two priority-number conventions this module can resolve into an ordering.
#: A bare numeric priority means nothing without one of these -- see the module
#: docstring's "WHY THE PRIORITY ORDERING IS NEVER GUESSED FROM A BARE NUMBER".
PRIORITY_CONVENTION_HIGHER_IS_HIGHER = "HIGHER_IS_HIGHER_PRIORITY"
PRIORITY_CONVENTION_LOWER_IS_HIGHER = "LOWER_IS_HIGHER_PRIORITY"
PRIORITY_CONVENTIONS = (PRIORITY_CONVENTION_HIGHER_IS_HIGHER, PRIORITY_CONVENTION_LOWER_IS_HIGHER)

#: `derive_priority_ordering()` status vocabulary.
ORDERING_STATUS_DERIVED = "ORDERING_DERIVED"
ORDERING_STATUS_NOT_AVAILABLE = "ORDERING_NOT_AVAILABLE"

#: `verify_qos_contention()`'s three honest verdicts. Never a fourth silently-invented
#: value, and never collapsed into just two -- "we could not tell" (UNKNOWN) must never
#: read as either a pass or a confirmed violation.
CONTENTION_VERIFIED = "VERIFIED"
CONTENTION_VIOLATED = "VIOLATED"
CONTENTION_UNKNOWN = "UNKNOWN"
CONTENTION_VERDICTS = (CONTENTION_VERIFIED, CONTENTION_VIOLATED, CONTENTION_UNKNOWN)

#: The bucket a transaction record lands in when the caller declares no `window_id` --
#: every un-windowed record is then treated as one single contention scenario. A caller
#: who genuinely wants no contention checked at all should simply pass no records.
DEFAULT_WINDOW_ID = "_default_window"


def _get(entry: Any, key: str, default: Any = None) -> Any:
    """Duck-typed field access: a plain dict, or any object exposing `.get()`."""
    if entry is None:
        return default
    getter = getattr(entry, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
    return getattr(entry, key, default)


@dataclass
class QoSMasterEntry:
    """One master's real, evidence-cited QoS facts."""
    master_id: str
    qos_level: Optional[str]
    priority: Optional[int]
    weight: Optional[float]
    evidence: str
    source: Optional[str] = None
    status: str = ENTRY_STATUS_DECLARED

    def to_dict(self) -> dict:
        return {
            "master_id": self.master_id, "qos_level": self.qos_level,
            "priority": self.priority, "weight": self.weight,
            "evidence": self.evidence, "source": self.source, "status": self.status,
        }


@dataclass
class QoSPolicyIR:
    """The whole project's per-master QoS mapping, plus the (optional) declared
    priority-number convention needed to turn numeric `priority` values into an
    ordering."""
    entries: Dict[str, QoSMasterEntry] = field(default_factory=dict)
    priority_convention: Optional[str] = None

    def masters_without_qos_facts(self) -> List[str]:
        return sorted(m for m, e in self.entries.items() if e.status == ENTRY_STATUS_NO_QOS_FACTS)

    def to_dict(self) -> dict:
        return {
            "priority_convention": self.priority_convention,
            "entries": {m: e.to_dict() for m, e in sorted(self.entries.items())},
        }


def build_qos_policy_ir(master_entries: Sequence[Any],
                         priority_convention: Optional[str] = None) -> QoSPolicyIR:
    """Build a `QoSPolicyIR` from a real, caller-supplied, duck-typed list of per-master
    QoS facts. Every entry must carry a non-empty `master_id` and a non-empty `evidence`
    citation; a `priority`, when declared, must be a real (non-bool) int, and a `weight`,
    when declared, a real (non-bool) number -- each violation is a hard,
    `QoSPolicyIRError`-raising refusal, never a silently coerced or dropped fact."""
    if priority_convention is not None and priority_convention not in PRIORITY_CONVENTIONS:
        raise QoSPolicyIRError("UNRECOGNIZED_PRIORITY_CONVENTION", {
            "priority_convention": priority_convention, "known": list(PRIORITY_CONVENTIONS)})
    entries: Dict[str, QoSMasterEntry] = {}
    for index, raw in enumerate(master_entries or ()):
        master_id = _get(raw, "master_id")
        if not isinstance(master_id, str) or not master_id.strip():
            raise QoSPolicyIRError("QOS_ENTRY_MISSING_MASTER_ID", {
                "index": index,
                "hint": "every QoS-policy entry must name a real master_id"})
        master_id = master_id.strip()
        if master_id in entries:
            raise QoSPolicyIRError("DUPLICATE_MASTER_ID", {
                "master_id": master_id,
                "hint": "each master may appear at most once in a QoS policy"})
        evidence = _get(raw, "evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise QoSPolicyIRError("QOS_ENTRY_MISSING_EVIDENCE", {
                "master_id": master_id,
                "hint": "a QoS-policy entry with no cited spec/RTL evidence is an "
                        "unsupported claim, not a fact -- see the Evidence Truth Rule"})
        qos_level = _get(raw, "qos_level")
        if qos_level is not None and not isinstance(qos_level, str):
            raise QoSPolicyIRError("INVALID_QOS_LEVEL_TYPE", {
                "master_id": master_id, "qos_level": qos_level})
        priority = _get(raw, "priority")
        if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int)):
            raise QoSPolicyIRError("INVALID_PRIORITY_TYPE", {
                "master_id": master_id, "priority": priority,
                "hint": "priority must be a real integer, not a bool or a guessed string"})
        weight = _get(raw, "weight")
        if weight is not None and (isinstance(weight, bool) or not isinstance(weight, (int, float))):
            raise QoSPolicyIRError("INVALID_WEIGHT_TYPE", {
                "master_id": master_id, "weight": weight})
        source = _get(raw, "source")
        status = ENTRY_STATUS_DECLARED if any(
            v is not None for v in (qos_level, priority, weight)) else ENTRY_STATUS_NO_QOS_FACTS
        entries[master_id] = QoSMasterEntry(
            master_id=master_id, qos_level=qos_level, priority=priority, weight=weight,
            evidence=evidence.strip(), source=source, status=status)
    return QoSPolicyIR(entries=entries, priority_convention=priority_convention)


def derive_priority_ordering(policy: QoSPolicyIR) -> dict:
    """Turn `policy`'s per-master numeric `priority` values into an ordering (a list of
    rank-groups, highest precedence first), IFF a `priority_convention` was declared and
    at least two masters carry a real `priority` value. Otherwise reports
    `ORDERING_NOT_AVAILABLE` with the real reason -- never a guessed ordering."""
    if policy.priority_convention is None:
        return {"status": ORDERING_STATUS_NOT_AVAILABLE, "ordering": None,
                "reason": "no priority_convention was declared on this QoSPolicyIR; a "
                          "bare numeric priority value has no fixed meaning without one"}
    prioritized = {m: e.priority for m, e in policy.entries.items() if e.priority is not None}
    if len(prioritized) < 2:
        return {"status": ORDERING_STATUS_NOT_AVAILABLE, "ordering": None,
                "reason": f"only {len(prioritized)} master(s) declare a real priority "
                          "value; at least 2 are needed to derive a relative ordering",
                "excluded_no_priority": sorted(set(policy.entries) - set(prioritized))}
    reverse = policy.priority_convention == PRIORITY_CONVENTION_HIGHER_IS_HIGHER
    distinct_values = sorted(set(prioritized.values()), reverse=reverse)
    ordering: List[List[str]] = []
    for value in distinct_values:
        group = sorted(m for m, p in prioritized.items() if p == value)
        ordering.append(group)
    return {"status": ORDERING_STATUS_DERIVED, "ordering": ordering,
            "reason": f"derived from {len(prioritized)} declared priority value(s) under "
                      f"convention {policy.priority_convention!r}",
            "excluded_no_priority": sorted(set(policy.entries) - set(prioritized))}


def _build_rank_map(ordering: Sequence[Union[str, Sequence[str]]]) -> Dict[str, int]:
    """`ordering` is highest-precedence first: a bare master_id string is a singleton
    rank group; a nested list/tuple is a group of masters with EQUAL declared priority
    (no relative order is asserted between them). Every master name may appear at most
    once across the whole ordering."""
    if not ordering:
        raise QoSPolicyIRError("EMPTY_ORDERING", {
            "hint": "a QoS ordering must name at least one master"})
    rank_map: Dict[str, int] = {}
    for rank, item in enumerate(ordering):
        group = [item] if isinstance(item, str) else list(item)
        if not group:
            raise QoSPolicyIRError("EMPTY_ORDERING_GROUP", {"rank": rank})
        for master_id in group:
            if not isinstance(master_id, str) or not master_id.strip():
                raise QoSPolicyIRError("INVALID_ORDERING_ENTRY", {"rank": rank, "entry": master_id})
            master_id = master_id.strip()
            if master_id in rank_map:
                raise QoSPolicyIRError("DUPLICATE_MASTER_IN_ORDERING", {"master_id": master_id})
            rank_map[master_id] = rank
    return rank_map


def _validate_transaction_record(record: Any, index: int) -> dict:
    master_id = _get(record, "master_id")
    if not isinstance(master_id, str) or not master_id.strip():
        raise QoSPolicyIRError("TRANSACTION_RECORD_MISSING_MASTER_ID", {"index": index})
    position = _get(record, "position")
    if isinstance(position, bool) or not isinstance(position, int):
        raise QoSPolicyIRError("TRANSACTION_RECORD_INVALID_POSITION", {
            "index": index, "master_id": master_id, "position": position,
            "hint": "position must be a real integer ordinal (a grant order or "
                    "scoreboard sequence number), never a bool or a timestamp string"})
    window_id = _get(record, "window_id", DEFAULT_WINDOW_ID)
    if not isinstance(window_id, str) or not window_id.strip():
        raise QoSPolicyIRError("TRANSACTION_RECORD_INVALID_WINDOW_ID", {
            "index": index, "master_id": master_id, "window_id": window_id})
    return {"master_id": master_id.strip(), "position": position, "window_id": window_id.strip()}


def verify_qos_contention(ordering: Sequence[Union[str, Sequence[str]]],
                           transaction_order: Sequence[Any]) -> dict:
    """Check whether `ordering` (highest-precedence first; ties as nested groups) was
    actually observed in `transaction_order` -- a caller-supplied list of records, each
    `{"master_id", "position", "window_id"?}`. Records sharing one `window_id` are a
    single real contention scenario (transactions genuinely contending for one shared
    resource at one point in time); records with no declared `window_id` all share
    `DEFAULT_WINDOW_ID`.

    Reports one of `CONTENTION_VERDICTS`:
      - VIOLATED: within at least one window, a strictly-higher-ranked master's
        transaction was observed at a LATER position than a strictly-lower-ranked
        master's, in the same window -- a real QoS-ordering violation.
      - VERIFIED: no violation was found, AND at least one window genuinely compared two
        or more masters both present in `ordering` -- a real, checked, honest pass.
      - UNKNOWN: nothing was actually comparable -- no window contained two or more
        masters both known to `ordering` (every window was empty, single-master, or
        every master in it was absent from the declared ordering).

    Two masters sharing a rank (a declared tie) are never flagged against each other --
    no relative order was ever asserted between them."""
    rank_map = _build_rank_map(ordering)
    parsed = [_validate_transaction_record(r, i) for i, r in enumerate(transaction_order or ())]

    windows: Dict[str, List[dict]] = {}
    for rec in parsed:
        windows.setdefault(rec["window_id"], []).append(rec)

    per_window: List[dict] = []
    any_violation = False
    any_real_comparison = False

    for window_id in sorted(windows):
        records = windows[window_id]
        known = [r for r in records if r["master_id"] in rank_map]
        unknown_masters = sorted({r["master_id"] for r in records if r["master_id"] not in rank_map})
        violations = []
        if len(known) >= 2:
            any_real_comparison = True
            for i in range(len(known)):
                for j in range(len(known)):
                    if i == j:
                        continue
                    a, b = known[i], known[j]
                    rank_a = rank_map[a["master_id"]]
                    rank_b = rank_map[b["master_id"]]
                    if rank_a < rank_b and a["position"] > b["position"]:
                        # `a` is strictly higher priority than `b` but was serviced later.
                        violations.append({
                            "higher_priority_master": a["master_id"],
                            "higher_priority_master_position": a["position"],
                            "lower_priority_master": b["master_id"],
                            "lower_priority_master_position": b["position"],
                        })
        if violations:
            any_violation = True
        per_window.append({
            "window_id": window_id,
            "compared_masters": sorted({r["master_id"] for r in known}),
            "unknown_masters": unknown_masters,
            "violations": violations,
            "status": (CONTENTION_VIOLATED if violations
                       else (CONTENTION_VERIFIED if len(known) >= 2 else CONTENTION_UNKNOWN)),
        })

    if any_violation:
        verdict = CONTENTION_VIOLATED
        reason = "at least one contention window observed a higher-priority master " \
                 "serviced after a lower-priority one"
    elif any_real_comparison:
        verdict = CONTENTION_VERIFIED
        reason = "every contention window with two or more masters known to the " \
                 "declared ordering matched that ordering"
    else:
        verdict = CONTENTION_UNKNOWN
        reason = "no contention window contained two or more masters both present in " \
                 "the declared ordering; nothing was actually comparable"

    return {"verdict": verdict, "reason": reason, "windows": per_window,
            "ordering_rank_map": dict(sorted(rank_map.items()))}
