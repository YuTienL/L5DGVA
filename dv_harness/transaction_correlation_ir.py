"""dv_harness/transaction_correlation_ir.py -- the Transaction Correlation IR: a real, evidence-based
bookkeeping layer that answers four questions no existing module in this repo answers -- (1) which
observed RESPONSE goes with which observed REQUEST, from real ID/tag evidence rather than a guessed
ordering; (2) which observed WRITE/READ DATA BEAT belongs to which observed transaction; (3) which
observed SUB-TRANSACTIONS at one end of a route are the real children of a single LOGICAL PARENT
transaction a caller has already detected was split or merged along that route; and (4) -- SYOSCB-11,
added 2026-09-06 -- reassembling ONE full LOGICAL AXI TRANSACTION record for a caller-declared
transaction by JOINING the already-computed outputs of (1) and (2) (and, when applicable, (3)) into a
single record, rather than leaving a caller to manually cross-reference three separate result lists.

SYOSCB-11'S VERIFY-FIRST FINDING, RECORDED HONESTLY. Mechanisms (1) and (2) above already do the real
correlation WORK a "logical transaction reconstruction" needs -- matching a response to its request,
and associating every data beat to its transaction -- and mechanism (3) already reconstructs a burst
split/merge PARENT out of its real observed CHILDREN. What none of the three ever produced is a single
combined record answering "what do we currently know about THIS ONE logical transaction, end to end" --
a caller had to run all three separately and cross-reference their outputs by hand. `reconstruct_
logical_transactions()` below closes exactly that composition gap and nothing more: it is a pure JOIN
over records the caller has already correlated with `correlate_responses()`/`associate_data_beats()`/
`link_burst_split_merge()`, performs no correlation logic of its own, and never claims a transaction is
complete on any dimension it was not handed real, already-computed evidence for.

THE GAP THIS CLOSES, AND WHAT IT DELIBERATELY IS NOT. `dv_harness/amba_transaction_ir.py` (SYOSCB-10)
already gives one AMBA transaction a typed shape -- `transaction_id`, `original_id`, `fabric_id`,
`sequence_number`, `route_id`, `expected_actual` -- and `dv_harness/amba_route_transform_predictor.py`
(SYOSCB-12) already DETECTS, per route, whether the topology implies a burst split or merge
(`detect_burst_split_merge()`) from a width-conversion/protocol-applicability comparison of the two
ends. Read before writing a line of this module: neither one tracks a CROSS-TRANSACTION link. The IR
gives one transaction fields to CARRY an id; it never says which OTHER transaction record shares that
id, or which response record answers which request record. The predictor says a route implies a
split/merge EVENT; it never says which of the real sub-transactions later observed on that route are
that event's actual children. This module is the correlation/bookkeeping layer that sits on top of
both, and reuses rather than reimplements either: `BURST_SPLIT` / `BURST_MERGE` /
`BURST_SPLIT_TO_SINGLE_TRANSFERS` / `TRANSFORM_PREDICTED_FROM_TOPOLOGY` are imported directly from
`amba_route_transform_predictor.py` (an established, pre-existing module -- not a sibling of this
module in the current batch) so there is exactly one spelling of "what kind of split/merge event this
is" in this repo. Detection logic itself is never duplicated here: this module never re-derives
whether a split/merge is implied, it only accepts a caller-supplied detected event (typically
`detect_burst_split_merge()`'s own return shape) and correlates real, already-observed sub-transactions
against it.

THE EVIDENCE TRUTH RULE, APPLIED TO CORRELATION SPECIFICALLY: every request/response/data-beat/
sub-transaction record a caller hands in must carry a non-empty `evidence` citation -- a real sim.log
line, a waveform offset, a monitor-captured beat -- or this module refuses to build a record from it at
all (`TransactionCorrelationIRError`). A correlation decision is never made from a component/port NAME
or a plausible-looking default. Three honest failure modes recur across all three mechanisms rather
than a silent guess: (1) genuinely ambiguous evidence (two candidates equally plausible, most often a
missing `sequence_number` inside a group sharing one real ID) is reported AMBIGUOUS, never resolved by
picking one; (2) evidence that is simply absent (no response yet, no beat yet, no detected event at
all) is reported as a real, distinctly-named PENDING/UNKNOWN status, never silently treated as a match
or a non-match; (3) evidence that actively CONTRADICTS a would-be match (an extra beat past a
transaction's own declared length, a child set that overlaps or overruns its declared parent's address
range, a response whose id matches no outstanding request) is reported as a real, distinctly-named
conflict finding, never dropped.

RESPONSE CORRELATION IS ORDER-AWARE, NOT A BARE ID LOOKUP. Real AMBA protocols with a transaction id
(AXI's AWID/ARID/BID/RID) permit MULTIPLE outstanding transactions to share one id, and the spec's own
ordering rule for a shared id is FIFO completion -- the first request issued on that id is the first
response answered on it. `correlate_responses()` therefore groups by `(scope, transaction_id)` --
`scope` is a caller-declared channel/route key so two unrelated ports sharing one bare id value (or two
protocols carrying no id at all, where every item's `transaction_id` is `None`) are never cross-matched
-- and, within a group holding more than one still-open request, matches strictly by ascending
`sequence_number`. A group missing a `sequence_number` on more than one still-open member cannot be
safely ordered, so it is reported AMBIGUOUS rather than matched by list position, which would be exactly
the guess this rule forbids.

WRITE/READ DATA ASSOCIATION NEVER GUESSES PAST AN UNKNOWN BURST LENGTH. `associate_data_beats()` joins
beats to a transaction by a real per-beat id when the caller supplies one (AXI3's WID, or any response
channel's RID/BID-carrying id), and by strict issue-order FIFO within a `scope` when beats carry no id
at all (AXI4's W channel has none). A transaction's own declared `expected_beat_count` (the real
burst_len-derived beat count evidence already exists for) decides when it stops accepting beats; a
transaction with no declared `expected_beat_count` can never be safely closed by counting alone, so
every beat that would otherwise queue behind it in the same scope is honestly reported
`BEAT_UNKNOWN_TRANSACTION_LENGTH` rather than guessed onto the next transaction in program order.

BURST SPLIT/MERGE LINKAGE IS ADDRESS-TILING ARITHMETIC, NEVER A SHARED-KEY GUESS.
`link_burst_split_merge()` takes ONE caller-supplied detected event (the `detect_burst_split_merge()`
return shape, or anything sharing it), one parent transaction record (address + total byte count) and
a list of real observed child sub-transaction records (address + byte count each), and checks -- by
plain arithmetic over real, already-observed addresses, never a shared correlation-key string this
module would otherwise have to trust blindly -- whether the children tile the parent's address range
exactly (contiguous, no gap, no overlap), and whether their count matches the event's own
`beat_count_factor` when the predictor supplied one. An event whose own `status` is not
`TRANSFORM_PREDICTED_FROM_TOPOLOGY`, or whose `kind` is none of the three split/merge kinds this repo
recognizes, is honestly `LINKAGE_NOT_APPLICABLE` -- this module never attempts to link children to an
event that never claimed a split/merge in the first place.

WHAT THIS MODULE DELIBERATELY DOES NOT DO: it does not discover fabric topology, ports, or protocols
(`amba_fabric_discovery.py`/`amba_port_registry.py`'s job); it does not decide whether a route implies a
split/merge at all (`amba_route_transform_predictor.py`'s job, called by the caller before this module
ever runs); it does not read RTL, a waveform, or a sim.log itself -- every record is a plain,
caller-supplied fact; it writes nothing, gates nothing, and approves nothing, and there is deliberately
no stage gate here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from dv_harness.amba_route_transform_predictor import (
    BURST_MERGE,
    BURST_SPLIT,
    BURST_SPLIT_TO_SINGLE_TRANSFERS,
    TRANSFORM_PREDICTED_FROM_TOPOLOGY,
)

#: The three split/merge event kinds this module knows how to link children against. Reused verbatim
#: from `amba_route_transform_predictor.py` -- never a second spelling of the same three words.
LINKABLE_EVENT_KINDS: Sequence[str] = (BURST_SPLIT, BURST_MERGE, BURST_SPLIT_TO_SINGLE_TRANSFERS)


class TransactionCorrelationIRError(Exception):
    """Raised only for a genuinely malformed caller input (a record missing its required identity or
    evidence citation, an invalid numeric field) -- never for an honest absence or ambiguity of
    evidence, which is always a reported PENDING/AMBIGUOUS/UNKNOWN-family result."""


# ===========================================================================
# Shared duck-typed field reader
# ===========================================================================

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Duck-typed read of one field from `obj`: a Mapping (via `.get`) or any attribute-bearing object.
    Never raises on an object with neither -- returns `default`, same as a missing key."""
    if obj is None:
        return default
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            value = getter(key, default)
        except TypeError:
            value = getter(key)
        return value if value is not None else default
    return getattr(obj, key, default)


def _require_evidence(record: Any, *, kind: str, ref_field: str) -> str:
    """Every record this module builds a correlation decision from must carry a non-empty `evidence`
    citation. A record with none is a caller-usage defect, not an honest absence of evidence -- it is
    refused outright rather than silently accepted as uncited."""
    ref = _get(record, ref_field)
    if not ref:
        raise TransactionCorrelationIRError(
            f"{kind} record is missing its required '{ref_field}' identity")
    ev = _get(record, "evidence")
    if not ev or (isinstance(ev, (list, tuple)) and not any(ev)):
        raise TransactionCorrelationIRError(
            f"{kind} record {ref!r} carries no 'evidence' citation -- a correlation decision may "
            f"not be built from an uncited record")
    return ref


def _evidence_list(record: Any) -> List[str]:
    ev = _get(record, "evidence")
    if ev is None:
        return []
    if isinstance(ev, (list, tuple)):
        return [str(e) for e in ev]
    return [str(ev)]


# ===========================================================================
# 1. Response correlation -- matching a response back to its originating request
# ===========================================================================

RESPONSE_MATCHED = "RESPONSE_MATCHED"
RESPONSE_UNMATCHED = "RESPONSE_UNMATCHED_NO_OUTSTANDING_REQUEST"
RESPONSE_AMBIGUOUS_ORDER = "RESPONSE_AMBIGUOUS_ORDER_WITHIN_ID_GROUP"
REQUEST_PENDING = "REQUEST_PENDING_NO_RESPONSE_YET"

RESPONSE_CORRELATION_STATUSES: Sequence[str] = (
    RESPONSE_MATCHED, RESPONSE_UNMATCHED, RESPONSE_AMBIGUOUS_ORDER, REQUEST_PENDING,
)


@dataclass
class ResponseCorrelationEntry:
    """One correlation outcome: either a response matched to the request it answers, an unmatched
    response with no outstanding request sharing its (scope, transaction_id), an ambiguous-order group
    this module refused to resolve by guessing, or a still-pending request with no response observed
    yet."""
    status: str  # one of RESPONSE_CORRELATION_STATUSES
    request_ref: Optional[str]
    response_ref: Optional[str]
    scope: Any
    transaction_id: Any
    reason: str
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _group_key(record: Any) -> Any:
    return (_get(record, "scope"), _get(record, "transaction_id"))


def correlate_responses(requests: Sequence[Any], responses: Sequence[Any]) -> List[ResponseCorrelationEntry]:
    """Correlate every observed response to the request it answers, grouped by `(scope,
    transaction_id)` and matched by strictly ascending `sequence_number` within a group -- never by
    list position, and never by picking a plausible match when the group's own ordering evidence is
    incomplete.

    Every request/response must carry `request_ref`/`response_ref` and a non-empty `evidence` list;
    `transaction_id` may legitimately be `None` (a protocol that carries no id at all groups its
    requests/responses under one `(scope, None)` bucket and is still correlated by strict FIFO order).
    """
    req_refs = set()
    grouped_requests: Dict[Any, List[Any]] = {}
    for r in requests:
        ref = _require_evidence(r, kind="request", ref_field="request_ref")
        if ref in req_refs:
            raise TransactionCorrelationIRError(f"duplicate request_ref {ref!r}")
        req_refs.add(ref)
        grouped_requests.setdefault(_group_key(r), []).append(r)

    resp_refs = set()
    grouped_responses: Dict[Any, List[Any]] = {}
    for r in responses:
        ref = _require_evidence(r, kind="response", ref_field="response_ref")
        if ref in resp_refs:
            raise TransactionCorrelationIRError(f"duplicate response_ref {ref!r}")
        resp_refs.add(ref)
        grouped_responses.setdefault(_group_key(r), []).append(r)

    entries: List[ResponseCorrelationEntry] = []
    all_keys = sorted(set(grouped_requests) | set(grouped_responses), key=lambda k: repr(k))

    for key in all_keys:
        scope, txn_id = key
        reqs = list(grouped_requests.get(key, ()))
        resps = list(grouped_responses.get(key, ()))

        # Responses with no request at all in this group are unmatched, whatever the ordering
        # situation is -- there is nothing to be ambiguous about.
        if not reqs:
            for r in resps:
                entries.append(ResponseCorrelationEntry(
                    status=RESPONSE_UNMATCHED, request_ref=None,
                    response_ref=_get(r, "response_ref"), scope=scope, transaction_id=txn_id,
                    reason="no outstanding request shares this (scope, transaction_id)",
                    evidence=_evidence_list(r)))
            continue

        if not resps:
            for q in reqs:
                entries.append(ResponseCorrelationEntry(
                    status=REQUEST_PENDING, request_ref=_get(q, "request_ref"),
                    response_ref=None, scope=scope, transaction_id=txn_id,
                    reason="request is still outstanding -- no response observed yet",
                    evidence=_evidence_list(q)))
            continue

        # More than one item on either side sharing this id needs a real, complete ordering to match
        # correctly (FIFO completion per id is the real AMBA ordering rule). Missing sequence_number
        # on more than one item on the busier side makes that ordering undecidable.
        if max(len(reqs), len(resps)) > 1:
            missing_seq = [x for x in (reqs + resps) if _get(x, "sequence_number") is None]
            if len(missing_seq) > 1:
                for q in reqs:
                    entries.append(ResponseCorrelationEntry(
                        status=RESPONSE_AMBIGUOUS_ORDER, request_ref=_get(q, "request_ref"),
                        response_ref=None, scope=scope, transaction_id=txn_id,
                        reason=("more than one request/response shares this (scope, transaction_id) "
                                "and more than one is missing a sequence_number -- FIFO completion "
                                "order cannot be established"),
                        evidence=_evidence_list(q)))
                for r in resps:
                    entries.append(ResponseCorrelationEntry(
                        status=RESPONSE_AMBIGUOUS_ORDER, request_ref=None,
                        response_ref=_get(r, "response_ref"), scope=scope, transaction_id=txn_id,
                        reason=("more than one request/response shares this (scope, transaction_id) "
                                "and more than one is missing a sequence_number -- FIFO completion "
                                "order cannot be established"),
                        evidence=_evidence_list(r)))
                continue

        reqs_sorted = sorted(reqs, key=lambda x: (_get(x, "sequence_number") is None,
                                                   _get(x, "sequence_number")))
        resps_sorted = sorted(resps, key=lambda x: (_get(x, "sequence_number") is None,
                                                     _get(x, "sequence_number")))

        n = min(len(reqs_sorted), len(resps_sorted))
        for i in range(n):
            q, r = reqs_sorted[i], resps_sorted[i]
            entries.append(ResponseCorrelationEntry(
                status=RESPONSE_MATCHED, request_ref=_get(q, "request_ref"),
                response_ref=_get(r, "response_ref"), scope=scope, transaction_id=txn_id,
                reason="matched by FIFO completion order within (scope, transaction_id)",
                evidence=sorted(set(_evidence_list(q) + _evidence_list(r)))))

        for q in reqs_sorted[n:]:
            entries.append(ResponseCorrelationEntry(
                status=REQUEST_PENDING, request_ref=_get(q, "request_ref"), response_ref=None,
                scope=scope, transaction_id=txn_id,
                reason="request is still outstanding -- no response observed yet",
                evidence=_evidence_list(q)))
        for r in resps_sorted[n:]:
            entries.append(ResponseCorrelationEntry(
                status=RESPONSE_UNMATCHED, request_ref=None, response_ref=_get(r, "response_ref"),
                scope=scope, transaction_id=txn_id,
                reason="more responses observed than outstanding requests in this (scope, "
                       "transaction_id) group",
                evidence=_evidence_list(r)))

    return entries


# ===========================================================================
# 2. Write/read data association -- which data beat belongs to which transaction
# ===========================================================================

BEAT_ASSOCIATED = "BEAT_ASSOCIATED"
BEAT_ORPHAN = "BEAT_ORPHAN_NO_MATCHING_TRANSACTION"
BEAT_UNKNOWN_LENGTH = "BEAT_UNKNOWN_TRANSACTION_LENGTH"

BEAT_STATUSES: Sequence[str] = (BEAT_ASSOCIATED, BEAT_ORPHAN, BEAT_UNKNOWN_LENGTH)

DATA_ASSOCIATION_COMPLETE = "DATA_ASSOCIATION_COMPLETE"
DATA_ASSOCIATION_PARTIAL = "DATA_ASSOCIATION_PARTIAL"
DATA_ASSOCIATION_EXCESS = "DATA_ASSOCIATION_EXCESS_BEATS"
DATA_ASSOCIATION_UNKNOWN_LENGTH = "DATA_ASSOCIATION_UNKNOWN_LENGTH"
DATA_ASSOCIATION_NO_BEATS = "DATA_ASSOCIATION_NO_BEATS_OBSERVED"

TRANSACTION_DATA_STATUSES: Sequence[str] = (
    DATA_ASSOCIATION_COMPLETE, DATA_ASSOCIATION_PARTIAL, DATA_ASSOCIATION_EXCESS,
    DATA_ASSOCIATION_UNKNOWN_LENGTH, DATA_ASSOCIATION_NO_BEATS,
)


@dataclass
class BeatAssociationEntry:
    status: str  # one of BEAT_STATUSES
    beat_ref: str
    transaction_ref: Optional[str]
    scope: Any
    reason: str
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransactionDataAssociation:
    status: str  # one of TRANSACTION_DATA_STATUSES
    transaction_ref: str
    scope: Any
    expected_beat_count: Optional[int]
    associated_beat_count: int
    associated_beat_refs: List[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DataAssociationReport:
    beats: List[BeatAssociationEntry]
    transactions: List[TransactionDataAssociation]

    def to_dict(self) -> Dict[str, Any]:
        return {"beats": [b.to_dict() for b in self.beats],
                "transactions": [t.to_dict() for t in self.transactions]}


def _validate_expected_beat_count(txn_ref: str, value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TransactionCorrelationIRError(
            f"transaction {txn_ref!r} declares an invalid expected_beat_count {value!r}")
    return value


def associate_data_beats(transactions: Sequence[Any], data_beats: Sequence[Any]) -> DataAssociationReport:
    """Associate every observed data beat with the transaction it belongs to.

    A beat carrying a real per-beat `beat_id` is matched against the transaction sharing the same
    `(scope, transaction_id)` -- the oldest such transaction (by `sequence_number`) that has not yet
    reached its own declared `expected_beat_count`. A beat with no `beat_id` at all is matched by strict
    issue-order FIFO within its `scope` against the oldest transaction in that scope still open.
    `expected_beat_count` is REQUIRED to safely close a transaction and move on to the next one in
    program order -- a transaction declaring none can never be judged "full" by counting alone, so
    every subsequent beat that would otherwise queue behind it in the same scope is honestly
    `BEAT_UNKNOWN_TRANSACTION_LENGTH` rather than guessed onto the next transaction.
    """
    txn_refs = set()
    txns_by_scope: Dict[Any, List[Dict[str, Any]]] = {}
    for t in transactions:
        ref = _require_evidence(t, kind="transaction", ref_field="transaction_ref")
        if ref in txn_refs:
            raise TransactionCorrelationIRError(f"duplicate transaction_ref {ref!r}")
        txn_refs.add(ref)
        scope = _get(t, "scope")
        expected = _validate_expected_beat_count(ref, _get(t, "expected_beat_count"))
        seq = _get(t, "sequence_number")
        txns_by_scope.setdefault(scope, []).append({
            "ref": ref, "transaction_id": _get(t, "transaction_id"),
            "sequence_number": seq, "expected_beat_count": expected,
            "associated": [], "length_unknown_blocked": False,
        })

    for scope in txns_by_scope:
        txns_by_scope[scope].sort(key=lambda d: (d["sequence_number"] is None, d["sequence_number"]))

    # `cursor` tracks, per FIFO queue key, how far the queue has been consumed. A queue key is
    # `scope` for unlabelled (no per-beat id) beats, or `(scope, beat_id)` for id-matched beats --
    # each is its own independent, monotonically-advancing FIFO. The cursor only ever advances past
    # a transaction once it is genuinely FULL (associated == its own declared expected_beat_count);
    # it never advances past a transaction whose length is unknown, because there is no evidence
    # that would justify believing it has finished.
    cursor: Dict[Any, int] = {}

    def _queue_for(scope: Any, beat_id: Any) -> List[Dict[str, Any]]:
        all_in_scope = txns_by_scope.get(scope, [])
        if beat_id is None:
            return all_in_scope
        return [c for c in all_in_scope if c["transaction_id"] == beat_id]

    def _advance_to_target(queue: List[Dict[str, Any]], key: Any) -> int:
        idx = cursor.get(key, 0)
        while idx < len(queue):
            c = queue[idx]
            if c["length_unknown_blocked"]:
                break
            if c["expected_beat_count"] is not None and len(c["associated"]) >= c["expected_beat_count"]:
                idx += 1
                continue
            break
        cursor[key] = idx
        return idx

    beat_entries: List[BeatAssociationEntry] = []
    beat_refs_seen = set()

    for b in data_beats:
        bref = _require_evidence(b, kind="data beat", ref_field="beat_ref")
        if bref in beat_refs_seen:
            raise TransactionCorrelationIRError(f"duplicate beat_ref {bref!r}")
        beat_refs_seen.add(bref)
        scope = _get(b, "scope")
        beat_id = _get(b, "beat_id")
        ev = _evidence_list(b)

        queue = _queue_for(scope, beat_id)
        key = scope if beat_id is None else (scope, beat_id)
        idx = _advance_to_target(queue, key)

        if idx >= len(queue):
            reason = (f"no open transaction in this scope shares transaction_id {beat_id!r}"
                      if beat_id is not None else
                      "no open (unblocked, not-yet-full) transaction exists in this scope")
            beat_entries.append(BeatAssociationEntry(
                status=BEAT_ORPHAN, beat_ref=bref, transaction_ref=None, scope=scope,
                reason=reason, evidence=ev))
            continue

        target = queue[idx]
        already_blocked = target["length_unknown_blocked"]
        target["associated"].append(bref)

        if already_blocked:
            beat_entries.append(BeatAssociationEntry(
                status=BEAT_UNKNOWN_LENGTH, beat_ref=bref, transaction_ref=target["ref"], scope=scope,
                reason=(f"transaction {target['ref']!r} declares no expected_beat_count and has "
                        f"already blocked this queue -- no beat past this point can be safely "
                        f"attributed to it or advanced past it"),
                evidence=ev))
            continue

        if target["expected_beat_count"] is None:
            target["length_unknown_blocked"] = True
            beat_entries.append(BeatAssociationEntry(
                status=BEAT_UNKNOWN_LENGTH, beat_ref=bref, transaction_ref=target["ref"], scope=scope,
                reason=(f"transaction {target['ref']!r} declares no expected_beat_count -- this beat "
                        f"cannot be safely counted toward or past its completion, and every "
                        f"subsequent beat in this queue is now blocked behind it"),
                evidence=ev))
            continue

        beat_entries.append(BeatAssociationEntry(
            status=BEAT_ASSOCIATED, beat_ref=bref, transaction_ref=target["ref"], scope=scope,
            reason=(f"matched by shared transaction_id {beat_id!r}" if beat_id is not None else
                    "matched by strict issue-order FIFO (no per-beat id present)"),
            evidence=ev))

    txn_entries: List[TransactionDataAssociation] = []
    for scope, lst in txns_by_scope.items():
        for c in lst:
            expected = c["expected_beat_count"]
            got = len(c["associated"])
            if expected is None:
                status = (DATA_ASSOCIATION_NO_BEATS if got == 0 else
                          DATA_ASSOCIATION_UNKNOWN_LENGTH)
                reason = ("no beats observed and no expected_beat_count declared" if got == 0 else
                          "no expected_beat_count declared -- completeness cannot be judged")
            elif got == 0 and expected > 0:
                status, reason = DATA_ASSOCIATION_NO_BEATS, \
                    f"expected {expected} beat(s), none observed"
            elif got == expected:
                status, reason = DATA_ASSOCIATION_COMPLETE, \
                    f"associated exactly the expected {expected} beat(s)"
            elif got < expected:
                status, reason = DATA_ASSOCIATION_PARTIAL, \
                    f"associated {got} of {expected} expected beat(s); no more observed"
            else:
                status, reason = DATA_ASSOCIATION_EXCESS, \
                    f"associated {got} beat(s), exceeding the declared expected {expected}"
            txn_entries.append(TransactionDataAssociation(
                status=status, transaction_ref=c["ref"], scope=scope,
                expected_beat_count=expected, associated_beat_count=got,
                associated_beat_refs=list(c["associated"]), reason=reason))

    return DataAssociationReport(beats=beat_entries, transactions=txn_entries)


# ===========================================================================
# 3. Burst split/merge linkage -- sub-transactions back to their logical parent
# ===========================================================================

LINKAGE_CONFIRMED = "LINKAGE_CONFIRMED"
LINKAGE_PARTIAL = "LINKAGE_PARTIAL_ADDRESS_RANGE_NOT_FULLY_COVERED"
LINKAGE_CONFLICT = "LINKAGE_CONFLICT"
LINKAGE_INSUFFICIENT_EVIDENCE = "LINKAGE_INSUFFICIENT_EVIDENCE"
LINKAGE_NOT_APPLICABLE = "LINKAGE_NOT_APPLICABLE"

LINKAGE_STATUSES: Sequence[str] = (
    LINKAGE_CONFIRMED, LINKAGE_PARTIAL, LINKAGE_CONFLICT, LINKAGE_INSUFFICIENT_EVIDENCE,
    LINKAGE_NOT_APPLICABLE,
)


@dataclass
class BurstLinkageEntry:
    status: str  # one of LINKAGE_STATUSES
    event_kind: Optional[str]
    parent_ref: Optional[str]
    child_refs: List[str]
    beat_count_factor: Optional[int]
    observed_child_count: int
    reason: str
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _event_kind_and_factor(detected_event: Any):
    """Read `{"status", "value": {"kind", "beat_count_factor"?}, "evidence"}` off the caller-supplied
    detected event -- the exact shape `amba_route_transform_predictor.detect_burst_split_merge()`
    already returns. Never re-derives whether a split/merge is implied; only reads what was already
    decided."""
    status = _get(detected_event, "status")
    value = _get(detected_event, "value") or {}
    kind = _get(value, "kind")
    factor = _get(value, "beat_count_factor")
    ev = _evidence_list(detected_event)
    return status, kind, factor, ev


def link_burst_split_merge(detected_event: Any, parent_transaction: Any,
                            child_transactions: Sequence[Any]) -> BurstLinkageEntry:
    """Correlate real observed `child_transactions` back to `parent_transaction` for one caller-supplied
    `detected_event` (typically one route's `detect_burst_split_merge()` result).

    Linkage is decided by address-tiling arithmetic over each record's real `address` and
    `total_bytes`/`size_bytes` fields -- never by trusting a shared correlation-key string blindly, and
    never attempted at all against an event that never actually claimed a split/merge (a `status` other
    than `TRANSFORM_PREDICTED_FROM_TOPOLOGY`, or a `kind` outside the three this module recognizes,
    reports `LINKAGE_NOT_APPLICABLE`).
    """
    status, kind, factor, event_evidence = _event_kind_and_factor(detected_event)

    if status != TRANSFORM_PREDICTED_FROM_TOPOLOGY or kind not in LINKABLE_EVENT_KINDS:
        return BurstLinkageEntry(
            status=LINKAGE_NOT_APPLICABLE, event_kind=kind, parent_ref=_get(parent_transaction, "transaction_ref"),
            child_refs=[], beat_count_factor=factor, observed_child_count=len(child_transactions),
            reason=(f"detected event does not claim a real split/merge on this route "
                    f"(status={status!r}, kind={kind!r})"),
            evidence=event_evidence)

    parent_ref = _require_evidence(parent_transaction, kind="parent transaction",
                                    ref_field="transaction_ref")
    parent_addr = _get(parent_transaction, "address")
    parent_size = _get(parent_transaction, "total_bytes")

    child_refs: List[str] = []
    children: List[Dict[str, Any]] = []
    ev_pool = list(event_evidence) + _evidence_list(parent_transaction)
    for c in child_transactions:
        cref = _require_evidence(c, kind="child transaction", ref_field="transaction_ref")
        child_refs.append(cref)
        addr = _get(c, "address")
        size = _get(c, "total_bytes")
        children.append({"ref": cref, "address": addr, "size": size})
        ev_pool.extend(_evidence_list(c))
    ev_pool = sorted(set(ev_pool))

    if parent_addr is None or parent_size is None or not children:
        return BurstLinkageEntry(
            status=LINKAGE_INSUFFICIENT_EVIDENCE, event_kind=kind, parent_ref=parent_ref,
            child_refs=child_refs, beat_count_factor=factor, observed_child_count=len(children),
            reason=("parent transaction is missing its declared address/total_bytes, or no child "
                    "sub-transactions were observed -- linkage cannot be checked"),
            evidence=ev_pool)

    missing_fields = [c["ref"] for c in children if c["address"] is None or c["size"] is None]
    if missing_fields:
        return BurstLinkageEntry(
            status=LINKAGE_INSUFFICIENT_EVIDENCE, event_kind=kind, parent_ref=parent_ref,
            child_refs=child_refs, beat_count_factor=factor, observed_child_count=len(children),
            reason=(f"child transaction(s) {sorted(missing_fields)} are missing a declared "
                    f"address/total_bytes -- linkage cannot be checked"),
            evidence=ev_pool)

    if factor is not None and len(children) != factor:
        return BurstLinkageEntry(
            status=LINKAGE_CONFLICT, event_kind=kind, parent_ref=parent_ref, child_refs=child_refs,
            beat_count_factor=factor, observed_child_count=len(children),
            reason=(f"observed {len(children)} child sub-transaction(s) but the detected event "
                    f"declares a beat_count_factor of {factor}"),
            evidence=ev_pool)

    ordered = sorted(children, key=lambda c: c["address"])
    parent_end = parent_addr + parent_size
    cursor = parent_addr
    for c in ordered:
        if c["address"] < parent_addr or (c["address"] + c["size"]) > parent_end:
            return BurstLinkageEntry(
                status=LINKAGE_CONFLICT, event_kind=kind, parent_ref=parent_ref, child_refs=child_refs,
                beat_count_factor=factor, observed_child_count=len(children),
                reason=(f"child {c['ref']!r} at [{c['address']}, {c['address'] + c['size']}) falls "
                        f"outside the parent's declared range [{parent_addr}, {parent_end})"),
                evidence=ev_pool)
        if c["address"] < cursor:
            return BurstLinkageEntry(
                status=LINKAGE_CONFLICT, event_kind=kind, parent_ref=parent_ref, child_refs=child_refs,
                beat_count_factor=factor, observed_child_count=len(children),
                reason=(f"child {c['ref']!r} at address {c['address']} overlaps a preceding child "
                        f"ending at {cursor}"),
                evidence=ev_pool)
        if c["address"] > cursor:
            return BurstLinkageEntry(
                status=LINKAGE_PARTIAL, event_kind=kind, parent_ref=parent_ref, child_refs=child_refs,
                beat_count_factor=factor, observed_child_count=len(children),
                reason=(f"a gap exists in the parent's address range: nothing observed covering "
                        f"[{cursor}, {c['address']})"),
                evidence=ev_pool)
        cursor = c["address"] + c["size"]

    if cursor < parent_end:
        return BurstLinkageEntry(
            status=LINKAGE_PARTIAL, event_kind=kind, parent_ref=parent_ref, child_refs=child_refs,
            beat_count_factor=factor, observed_child_count=len(children),
            reason=f"observed children cover only [{parent_addr}, {cursor}) of the parent's declared "
                   f"range [{parent_addr}, {parent_end})",
            evidence=ev_pool)

    return BurstLinkageEntry(
        status=LINKAGE_CONFIRMED, event_kind=kind, parent_ref=parent_ref, child_refs=child_refs,
        beat_count_factor=factor, observed_child_count=len(children),
        reason=(f"observed {len(children)} child sub-transaction(s) tile the parent's declared "
                f"address range [{parent_addr}, {parent_end}) exactly, with no gap or overlap"
                + (f" and match the event's declared beat_count_factor of {factor}" if factor is not None
                   else "")),
        evidence=ev_pool)


# ===========================================================================
# 4. Logical transaction reconstruction -- one full record per logical AXI transaction
# ===========================================================================

LOGICAL_TXN_COMPLETE = "LOGICAL_TXN_COMPLETE"
LOGICAL_TXN_PENDING = "LOGICAL_TXN_PENDING_NO_RESPONSE_YET"
LOGICAL_TXN_RESPONSE_AMBIGUOUS = "LOGICAL_TXN_RESPONSE_AMBIGUOUS_ORDER"
LOGICAL_TXN_PARTIAL_DATA = "LOGICAL_TXN_PARTIAL_DATA"
LOGICAL_TXN_UNKNOWN_DATA_LENGTH = "LOGICAL_TXN_UNKNOWN_DATA_LENGTH"
LOGICAL_TXN_EXCESS_DATA = "LOGICAL_TXN_EXCESS_DATA_BEATS"
LOGICAL_TXN_BURST_LINKAGE_UNCONFIRMED = "LOGICAL_TXN_BURST_LINKAGE_UNCONFIRMED"
LOGICAL_TXN_INSUFFICIENT_EVIDENCE = "LOGICAL_TXN_INSUFFICIENT_EVIDENCE"

LOGICAL_TXN_STATUSES: Sequence[str] = (
    LOGICAL_TXN_COMPLETE, LOGICAL_TXN_PENDING, LOGICAL_TXN_RESPONSE_AMBIGUOUS,
    LOGICAL_TXN_PARTIAL_DATA, LOGICAL_TXN_UNKNOWN_DATA_LENGTH, LOGICAL_TXN_EXCESS_DATA,
    LOGICAL_TXN_BURST_LINKAGE_UNCONFIRMED, LOGICAL_TXN_INSUFFICIENT_EVIDENCE,
)

_BURST_LINKAGE_CLEAN_STATUSES = (LINKAGE_CONFIRMED, LINKAGE_NOT_APPLICABLE)


@dataclass
class LogicalAxiTransactionIR:
    """One fully-reassembled logical AXI transaction: the real response-correlation outcome, the
    real data-beat-association outcome, and (when the caller supplies one) the real burst
    split/merge linkage outcome for this transaction, joined into a single record. `status` is
    never a guess -- it is the worst (least-complete) of the real, already-computed statuses this
    record was actually built from, exactly like every other worst-wins rollup in this module."""
    status: str  # one of LOGICAL_TXN_STATUSES
    transaction_ref: str
    scope: Any
    request_ref: Optional[str]
    response_ref: Optional[str]
    response_status: Optional[str]
    data_status: Optional[str]
    associated_beat_refs: List[str]
    burst_linkage_status: Optional[str]
    reason: str
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _beat_evidence_for_transaction(data_report: "DataAssociationReport", transaction_ref: str) -> List[str]:
    ev: List[str] = []
    for b in data_report.beats:
        if b.transaction_ref == transaction_ref:
            ev.extend(b.evidence)
    return ev


def reconstruct_logical_transactions(
        transaction_records: Sequence[Any],
        response_entries: Sequence[ResponseCorrelationEntry],
        data_report: "DataAssociationReport",
        burst_linkage_by_ref: Optional[Mapping[Any, "BurstLinkageEntry"]] = None,
) -> List[LogicalAxiTransactionIR]:
    """Assemble ONE `LogicalAxiTransactionIR` per caller-declared transaction by JOINING the
    already-computed outputs of `correlate_responses()` and `associate_data_beats()` -- reused, never
    re-derived -- plus, when the caller supplies one, an already-computed `link_burst_split_merge()`
    verdict for a transaction that is itself the parent of a detected burst split/merge.

    Each `transaction_records` entry must carry a `transaction_ref` (matching a
    `TransactionDataAssociation.transaction_ref` already present in `data_report`, i.e. the same
    ref used in the `transactions` list handed to `associate_data_beats()`) and a `request_ref`
    (matching a `ResponseCorrelationEntry.request_ref` already present in `response_entries`), plus
    a non-empty `evidence` citation like every other record this module builds a decision from. A
    transaction whose declared refs resolve to NEITHER a real response-correlation entry NOR a real
    data-association entry is honestly `LOGICAL_TXN_INSUFFICIENT_EVIDENCE`, naming exactly which
    half is missing, rather than silently reported as complete or dropped.

    `burst_linkage_by_ref`, when supplied, maps a `transaction_ref` to the `BurstLinkageEntry` this
    transaction is the PARENT of (typically `link_burst_split_merge()`'s own return value, whose
    `parent_ref` must equal that same `transaction_ref` -- a mismatch is a caller data-integrity
    defect and is refused, not silently accepted). Only `LINKAGE_CONFIRMED` and
    `LINKAGE_NOT_APPLICABLE` (this transaction was never claimed to be a split/merge parent at all)
    count as "clean" for the composed status; every other linkage outcome is reported as its own
    honest `LOGICAL_TXN_BURST_LINKAGE_UNCONFIRMED` finding rather than silently ignored.
    """
    resp_by_request_ref: Dict[Any, ResponseCorrelationEntry] = {
        e.request_ref: e for e in response_entries if e.request_ref is not None
    }
    data_by_ref: Dict[Any, "TransactionDataAssociation"] = {
        t.transaction_ref: t for t in data_report.transactions
    }
    burst_map: Mapping[Any, "BurstLinkageEntry"] = burst_linkage_by_ref or {}

    results: List[LogicalAxiTransactionIR] = []
    seen_refs = set()
    for t in transaction_records:
        tref = _require_evidence(t, kind="logical transaction", ref_field="transaction_ref")
        if tref in seen_refs:
            raise TransactionCorrelationIRError(f"duplicate transaction_ref {tref!r}")
        seen_refs.add(tref)
        req_ref = _get(t, "request_ref")
        scope = _get(t, "scope")
        own_evidence = _evidence_list(t)

        resp_entry = resp_by_request_ref.get(req_ref) if req_ref is not None else None
        data_entry = data_by_ref.get(tref)
        burst_entry = burst_map.get(tref)
        if burst_entry is not None and burst_entry.parent_ref != tref:
            raise TransactionCorrelationIRError(
                f"burst_linkage_by_ref entry for {tref!r} carries a mismatched parent_ref "
                f"{burst_entry.parent_ref!r} -- the linkage supplied for a transaction must be that "
                f"transaction's own parent linkage")

        beat_evidence = _beat_evidence_for_transaction(data_report, tref)
        combined_evidence = sorted(set(
            own_evidence
            + (resp_entry.evidence if resp_entry is not None else [])
            + beat_evidence
            + (burst_entry.evidence if burst_entry is not None else [])))

        if resp_entry is None or data_entry is None:
            missing = []
            if resp_entry is None:
                missing.append(f"no response-correlation entry for request_ref {req_ref!r}")
            if data_entry is None:
                missing.append(f"no data-association entry for transaction_ref {tref!r}")
            results.append(LogicalAxiTransactionIR(
                status=LOGICAL_TXN_INSUFFICIENT_EVIDENCE, transaction_ref=tref, scope=scope,
                request_ref=req_ref,
                response_ref=(resp_entry.response_ref if resp_entry is not None else None),
                response_status=(resp_entry.status if resp_entry is not None else None),
                data_status=(data_entry.status if data_entry is not None else None),
                associated_beat_refs=(list(data_entry.associated_beat_refs) if data_entry is not None else []),
                burst_linkage_status=(burst_entry.status if burst_entry is not None else None),
                reason="; ".join(missing),
                evidence=combined_evidence))
            continue

        burst_clean = burst_entry is None or burst_entry.status in _BURST_LINKAGE_CLEAN_STATUSES

        if resp_entry.status == RESPONSE_AMBIGUOUS_ORDER:
            status = LOGICAL_TXN_RESPONSE_AMBIGUOUS
            reason = ("response correlation could not establish FIFO completion order for this "
                      "transaction's request -- see response_status")
        elif resp_entry.status == REQUEST_PENDING:
            status = LOGICAL_TXN_PENDING
            reason = "request is still outstanding -- no response observed yet"
        elif data_entry.status == DATA_ASSOCIATION_UNKNOWN_LENGTH:
            status = LOGICAL_TXN_UNKNOWN_DATA_LENGTH
            reason = ("this transaction declares no expected_beat_count -- data completeness "
                      "cannot be judged")
        elif data_entry.status == DATA_ASSOCIATION_EXCESS:
            status = LOGICAL_TXN_EXCESS_DATA
            reason = "more data beats were associated than this transaction's own declared length"
        elif data_entry.status in (DATA_ASSOCIATION_PARTIAL, DATA_ASSOCIATION_NO_BEATS):
            status = LOGICAL_TXN_PARTIAL_DATA
            reason = f"data association is incomplete for this transaction ({data_entry.reason})"
        elif not burst_clean:
            status = LOGICAL_TXN_BURST_LINKAGE_UNCONFIRMED
            reason = (f"this transaction is a declared burst split/merge parent whose linkage is "
                      f"{burst_entry.status} -- see burst_linkage_status")
        else:
            status = LOGICAL_TXN_COMPLETE
            reason = ("response matched and all expected data beats associated"
                      + (" and burst split/merge linkage confirmed"
                         if burst_entry is not None and burst_entry.status == LINKAGE_CONFIRMED
                         else ""))

        results.append(LogicalAxiTransactionIR(
            status=status, transaction_ref=tref, scope=scope, request_ref=req_ref,
            response_ref=resp_entry.response_ref, response_status=resp_entry.status,
            data_status=data_entry.status, associated_beat_refs=list(data_entry.associated_beat_refs),
            burst_linkage_status=(burst_entry.status if burst_entry is not None else None),
            reason=reason, evidence=combined_evidence))

    return results


# ===========================================================================
# Reporting
# ===========================================================================

def render_response_correlation_report(entries: Sequence[ResponseCorrelationEntry]) -> str:
    lines = ["Response Correlation", ""]
    for e in entries:
        lines.append(f"  [{e.status}] request={e.request_ref!r} response={e.response_ref!r} "
                     f"scope={e.scope!r} transaction_id={e.transaction_id!r}")
        lines.append(f"    {e.reason}")
    if not entries:
        lines.append("  (no requests or responses supplied)")
    return "\n".join(lines)


def render_data_association_report(report: DataAssociationReport) -> str:
    lines = ["Data Association", "", "  Beats:"]
    for b in report.beats:
        lines.append(f"    [{b.status}] beat={b.beat_ref!r} -> transaction={b.transaction_ref!r}  "
                     f"({b.reason})")
    lines.append("  Transactions:")
    for t in report.transactions:
        lines.append(f"    [{t.status}] transaction={t.transaction_ref!r} "
                     f"{t.associated_beat_count}/{t.expected_beat_count} beat(s)  ({t.reason})")
    return "\n".join(lines)


def render_logical_transaction_report(entries: Sequence[LogicalAxiTransactionIR]) -> str:
    lines = ["Logical AXI Transaction Reconstruction", ""]
    for e in entries:
        lines.append(f"  [{e.status}] transaction={e.transaction_ref!r} scope={e.scope!r} "
                     f"request={e.request_ref!r} response={e.response_ref!r}")
        lines.append(f"    response_status={e.response_status!r} data_status={e.data_status!r} "
                     f"burst_linkage_status={e.burst_linkage_status!r}")
        lines.append(f"    beats: {e.associated_beat_refs}")
        lines.append(f"    {e.reason}")
    if not entries:
        lines.append("  (no transactions supplied)")
    return "\n".join(lines)


def render_burst_linkage_report(entry: BurstLinkageEntry) -> str:
    lines = [f"Burst Split/Merge Linkage: {entry.event_kind or '(no event)'}",
             f"  status: {entry.status}",
             f"  parent: {entry.parent_ref!r}",
             f"  children ({entry.observed_child_count}): {entry.child_refs}",
             f"  {entry.reason}"]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.transaction_correlation_ir",
        description="Correlate observed AMBA request/response/data-beat/sub-transaction records into "
                    "the Transaction Correlation IR. Reads and reports only -- writes nothing, gates "
                    "nothing.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_resp = sub.add_parser("responses", help="Correlate responses to requests.")
    p_resp.add_argument("--requests", required=True, help="JSON file: a list of request records.")
    p_resp.add_argument("--responses", required=True, help="JSON file: a list of response records.")

    p_data = sub.add_parser("data", help="Associate data beats with transactions.")
    p_data.add_argument("--transactions", required=True, help="JSON file: a list of transaction records.")
    p_data.add_argument("--beats", required=True, help="JSON file: a list of data-beat records.")

    p_link = sub.add_parser("linkage", help="Link burst split/merge sub-transactions to their parent.")
    p_link.add_argument("--event", required=True, help="JSON file: one detected split/merge event.")
    p_link.add_argument("--parent", required=True, help="JSON file: one parent transaction record.")
    p_link.add_argument("--children", required=True, help="JSON file: a list of child transaction records.")

    p_recon = sub.add_parser(
        "reconstruct",
        help="Reassemble one full logical AXI transaction record per declared transaction by joining "
             "already-computed response-correlation and data-association results.")
    p_recon.add_argument("--transactions", required=True,
                          help="JSON file: a list of {transaction_ref, request_ref, scope, evidence} records.")
    p_recon.add_argument("--requests", required=True, help="JSON file: a list of request records.")
    p_recon.add_argument("--responses", required=True, help="JSON file: a list of response records.")
    p_recon.add_argument("--data-transactions", required=True,
                          help="JSON file: the transaction records for data-beat association "
                               "(the `transactions` input to associate_data_beats()).")
    p_recon.add_argument("--beats", required=True, help="JSON file: a list of data-beat records.")

    for p in (p_resp, p_data, p_link, p_recon):
        p.add_argument("--json", action="store_true", help="Emit the machine-readable IR.")

    a = ap.parse_args(argv)

    def _load(path: str) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    if a.cmd == "responses":
        entries = correlate_responses(_load(a.requests), _load(a.responses))
        if a.json:
            print(json.dumps([e.to_dict() for e in entries], indent=2, default=str))
        else:
            print(render_response_correlation_report(entries))
        return 0

    if a.cmd == "data":
        report = associate_data_beats(_load(a.transactions), _load(a.beats))
        if a.json:
            print(json.dumps(report.to_dict(), indent=2, default=str))
        else:
            print(render_data_association_report(report))
        return 0

    if a.cmd == "linkage":
        entry = link_burst_split_merge(_load(a.event), _load(a.parent), _load(a.children))
        if a.json:
            print(json.dumps(entry.to_dict(), indent=2, default=str))
        else:
            print(render_burst_linkage_report(entry))
        return 0 if entry.status == LINKAGE_CONFIRMED else 1

    if a.cmd == "reconstruct":
        response_entries = correlate_responses(_load(a.requests), _load(a.responses))
        data_report = associate_data_beats(_load(a.data_transactions), _load(a.beats))
        entries = reconstruct_logical_transactions(
            _load(a.transactions), response_entries, data_report)
        if a.json:
            print(json.dumps([e.to_dict() for e in entries], indent=2, default=str))
        else:
            print(render_logical_transaction_report(entries))
        return 0 if all(e.status == LOGICAL_TXN_COMPLETE for e in entries) else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
