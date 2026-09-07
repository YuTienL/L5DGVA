"""dv_harness/protocol_compliance_oracle.py -- Protocol Compliance ORACLE
(2026-09-06, section 222).

SCOPE, stated up front because it is what separates this module from its
similarly-named sibling: **this module checks whether a GENERATED sequence/
pattern's own declared STIMULUS is itself protocol-legal, BEFORE anything is
ever simulated.** It is a static, evidence-grounded lint over a list of
transaction records a generator produced -- never a runtime result.

`dv_harness/protocol_compliance_aggregation.py` answers a completely
different question, and is never imported here: it aggregates an
ALREADY-COMPUTED scoreboard/checker verdict that came out of a real
simulation run. This module never reads a scoreboard verdict, a sim.log, or
any evidence database at all -- it reads a plain, caller-supplied list of
GENERATED transaction dicts (the stimulus a pattern/sequence generator is
ABOUT to drive, or already drove, onto the bus) and decides, from first
principles grounded in real protocol facts, whether each declared field
value is one the protocol permits.

REUSE OVER REINVENT -- THE WHOLE POINT OF THIS MODULE
-------------------------------------------------------
This module invents NO protocol rule of its own. Every legality fact it
checks a stimulus value against is read from two existing, real modules:

  - `amba_transaction_ir.ir_field_applicability(protocol)` -- SYOSCB-10's
    real, connectivity-signal-witnessed answer to "does this AMBA-4 protocol
    even HAVE this field". Reused directly for EVERY one of the 22 real
    `AMBA_TRANSACTION_IR_FIELDS`, not only the six burst/security dimensions
    `amba_master_slave_constraint_ir.py` models -- so a stimulus that forces
    a value onto a field the protocol does not carry at all (an address on
    AXI4-Stream, say) is caught by the identical rule
    `amba_transaction_ir.assert_no_inapplicable_field_forced()` already
    enforces one layer up, applied here to GENERATED stimulus rather than to
    an IR template.
  - `amba_master_slave_constraint_ir.build_protocol_legal_constraint_ir(
    protocol)` -- Layer 1 of the three-layer constraint model, i.e. what
    AMBA-4 permits IN GENERAL for `burst_type`/`burst_len`/`burst_size`/
    `outstanding`/`ordering`/`security`. This module reads that layer's own
    `legal_value` per dimension and checks a stimulus's DECLARED value
    against it -- never the DUT-capability layer, and never the
    scenario-constraint layer. Whether the DUT actually IMPLEMENTS a
    protocol-legal value is `amba_master_slave_constraint_ir.py`'s own
    separate, deliberately different question (its "one hard rule": never
    infer a DUT capability from VIP capability alone) -- this oracle asks
    only "is this generated value protocol-legal", never "does this DUT
    support it". A stimulus this oracle certifies LEGAL may still be
    something the real DUT cannot do; that is exactly why the DUT-capability
    layer exists as a SEPARATE object this module does not read.

Neither `amba_transaction_ir.py` nor `amba_master_slave_constraint_ir.py` is
extended or modified here -- both are imported read-only, exactly as their
own public functions already return them.

THREE-LEVEL VERDICT, NEVER COLLAPSED
--------------------------------------
Per FIELD, per TRANSACTION, per PATTERN -- a worst-wins fold at each level,
the same no-averaging discipline this project applies everywhere a composite
verdict is derived. A single ILLEGAL field makes its whole transaction
ILLEGAL regardless of how many of that transaction's other fields are legal;
a single ILLEGAL transaction makes the whole pattern ILLEGAL regardless of
how many other transactions in it are clean.

WHAT THIS MODULE DOES NOT CHECK
----------------------------------
`address`/`data`/`byte_enable` VALUES are never range-checked here (address-
map legality is a different, address-map-specific domain --
`address_map_integrity_checker.py`'s job, not this one's, and not imported
here since this module's scope is protocol-field legality, not address-map
legality). `outstanding` and `ordering` are inherently STREAM-level facts,
not single-transaction ones -- this module checks them across the WHOLE
supplied transaction list (see `check_pattern_outstanding()` /
`check_pattern_ordering()`), and only when the caller supplies the temporal
evidence (`sequence_number` for issue order, and this module's own
`completion_sequence` field for completion order) needed to judge them;
absent that evidence the honest answer is `FIELD_NOT_CHECKED_INSUFFICIENT_
EVIDENCE`, never an assumed-legal pass. This module runs no build, no
simulation, and mints no approval; there is deliberately no stage gate.

`stimulus_id` vs. `transaction_id`, deliberately never conflated
-------------------------------------------------------------------
A caller's own free-text display LABEL for one generated stimulus record
(`stimulus_id`) is a DIFFERENT key from `transaction_id`, the real
`AMBA_TRANSACTION_IR_FIELDS` field carrying the transaction's actual
bus-level ID (AWID/ARID/BID/RID/TID). Reports and violation citations always
use `stimulus_id`; per-ID ordering grouping (`check_pattern_ordering()`)
always uses `transaction_id`. Neither ever silently stands in for the other.

DISCLOSED RESIDUAL -- FIELD_LEGAL is a narrow ceiling on purpose
--------------------------------------------------------------------
Because `FIELD_APPLICABILITY_ONLY_NO_VALUE_RULE` outranks `FIELD_LEGAL` in
the worst-wins fold (an unchecked field must never be silently read as a
verified-clean one, the Evidence Truth Rule applied to this fold), a
realistic transaction that also declares `address`/`data`/`transaction_id`/
etc. -- fields this module has no per-value rule for -- correctly reports
`FIELD_APPLICABILITY_ONLY_NO_VALUE_RULE` as its overall status rather than a
fabricated `FIELD_LEGAL`. `FIELD_LEGAL` is reserved for a transaction (or
pattern) whose every declared field was BOTH applicable AND actually
value-checked. This is intentional, not an oversight: an overall verdict
must never claim more certainty than what was actually verified.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from dv_harness.amba_transaction_ir import (
    AMBA_TRANSACTION_IR_FIELDS,
    IR_FIELD_APPLICABILITY_UNKNOWN,
    IR_FIELD_NOT_APPLICABLE,
    ir_field_applicability,
)
from dv_harness.amba_master_slave_constraint_ir import (
    DIMENSIONS,
    build_protocol_legal_constraint_ir,
)
from dv_harness.connectivity import render_markdown_table


class ProtocolComplianceOracleError(Exception):
    """A caller-usage error this module refuses rather than guesses past: a
    malformed transaction record, an unrecognized dimension, or a value of
    the wrong shape for the dimension it claims to be."""

    def __init__(self, code: str, detail: Optional[dict] = None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


# ===========================================================================
# Vocabulary -- deliberately distinct from protocol_compliance_aggregation.py
# ===========================================================================

#: The four DIMENSIONS `amba_master_slave_constraint_ir.py`'s protocol-legal
#: layer carries a real legal VALUE for, and this module additionally
#: value-checks a declared per-transaction stimulus field against. Read from
#: that module's own `DIMENSIONS` tuple minus the two stream-level ones
#: (`outstanding`, `ordering`), which are checked at the PATTERN level below,
#: never per-transaction.
PER_TRANSACTION_VALUE_CHECKED_DIMENSIONS: tuple = tuple(
    d for d in DIMENSIONS if d not in ("outstanding", "ordering"))

FIELD_LEGAL = "FIELD_LEGAL"
FIELD_ILLEGAL = "FIELD_ILLEGAL"
FIELD_NOT_APPLICABLE = IR_FIELD_NOT_APPLICABLE
FIELD_PROTOCOL_UNRESOLVED = IR_FIELD_APPLICABILITY_UNKNOWN
#: The field was applicable and a value was declared, but this module has no
#: rule for that specific dimension's VALUE (every `AMBA_TRANSACTION_IR_
#: FIELDS` entry outside `PER_TRANSACTION_VALUE_CHECKED_DIMENSIONS`), so only
#: the applicability half of the check (forced-inapplicable-field) applies.
FIELD_APPLICABILITY_ONLY = "FIELD_APPLICABILITY_ONLY_NO_VALUE_RULE"
#: A dimension this module DOES have a value rule for, but the evidence
#: needed to apply it (a temporal ordering fact, a comparison bound) was not
#: supplied -- honestly distinct from a fabricated pass.
FIELD_NOT_CHECKED = "FIELD_NOT_CHECKED_INSUFFICIENT_EVIDENCE"

FIELD_STATUSES = (FIELD_LEGAL, FIELD_ILLEGAL, FIELD_NOT_APPLICABLE,
                  FIELD_PROTOCOL_UNRESOLVED, FIELD_APPLICABILITY_ONLY, FIELD_NOT_CHECKED)

#: Keys a stimulus record may legally carry that are NOT one of the 22 real
#: `AMBA_TRANSACTION_IR_FIELDS`. Three different reasons:
#: - `stimulus_id` is a caller's own free-text LABEL for this record, used
#:   only for reporting/violation citations -- deliberately NOT the same key
#:   as the real `transaction_id` field (SYOSCB-10's own AWID/ARID/BID/RID/
#:   TID value), so a report's own display label can never be silently
#:   checked as if it were a real bus-level transaction ID and vice versa.
#: - `completion_sequence` is this module's OWN required temporal evidence
#:   for the pattern-level ordering check (`check_pattern_ordering()`), not a
#:   stimulus-content field -- no prior IR in this repo models a
#:   transaction's completion order.
#: - `security` is one of `amba_master_slave_constraint_ir.DIMENSIONS`, but
#:   `amba_transaction_ir.AMBA_TRANSACTION_IR_FIELDS` (SYOSCB-10's own field
#:   list) never modeled a security/protection dimension at all -- it is
#:   checked directly against the protocol-legal layer's own applicability
#:   for `security` (see `check_transaction_stimulus()` below), never
#:   through `ir_field_applicability()`, which has no entry for it.
ALLOWED_NON_IR_KEYS: frozenset = frozenset({"stimulus_id", "completion_sequence", "security"})

#: Worst-first fold order for both the per-transaction and per-pattern
#: rollups -- never an average, a single worse finding always wins.
#: `FIELD_NOT_APPLICABLE` is deliberately EXCLUDED from this order: it means
#: "this dimension does not exist for this protocol, so nothing needed
#: checking" (e.g. AXI4's own protocol-legal `outstanding` fact imposes no
#: numeric ceiling at all) -- a clean, benign fact that must never outrank a
#: real `FIELD_LEGAL` verdict, the way a NOT_APPLICABLE-only row elsewhere in
#: this project's readiness rollups never blocks a clean READY. `_fold()`
#: below strips it out before applying this order, and only reports it
#: honestly when NOTHING else was present to fold at all.
_FOLD_ORDER = (FIELD_ILLEGAL, FIELD_PROTOCOL_UNRESOLVED, FIELD_NOT_CHECKED,
              FIELD_APPLICABILITY_ONLY, FIELD_LEGAL)


def _fold(statuses: Sequence[str]) -> str:
    present = set(statuses)
    non_not_applicable = present - {FIELD_NOT_APPLICABLE}
    if non_not_applicable:
        for candidate in _FOLD_ORDER:
            if candidate in non_not_applicable:
                return candidate
        return FIELD_LEGAL
    if FIELD_NOT_APPLICABLE in present:
        return FIELD_NOT_APPLICABLE
    return FIELD_LEGAL


# ===========================================================================
# Per-transaction, per-field checking
# ===========================================================================


def _check_burst_type(legal_value, value):
    if not isinstance(legal_value, (set, frozenset)):
        raise ProtocolComplianceOracleError(
            "PROTOCOL_LEGAL_VALUE_SHAPE_UNEXPECTED", {"dimension": "burst_type", "legal_value": legal_value})
    if value in legal_value:
        return FIELD_LEGAL, f"{value!r} is a protocol-legal burst type"
    return FIELD_ILLEGAL, (f"{value!r} is not one of this protocol's legal burst types "
                           f"{sorted(legal_value)}")


def _check_burst_len(legal_value, value, burst_type):
    if not isinstance(legal_value, dict):
        raise ProtocolComplianceOracleError(
            "PROTOCOL_LEGAL_VALUE_SHAPE_UNEXPECTED", {"dimension": "burst_len", "legal_value": legal_value})
    if burst_type is None:
        return FIELD_NOT_CHECKED, "burst_len legality depends on the declared burst_type, which this stimulus did not declare"
    if burst_type not in legal_value:
        # burst_type itself is illegal for this protocol -- already reported
        # as its own FIELD_ILLEGAL finding; burst_len cannot be judged
        # against a range that does not exist.
        return FIELD_NOT_CHECKED, f"burst_type {burst_type!r} is not protocol-legal, so no legal burst_len range applies"
    min_beats, max_beats = legal_value[burst_type]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolComplianceOracleError(
            "STIMULUS_VALUE_NOT_AN_INT", {"dimension": "burst_len", "value": value})
    if value < min_beats:
        return FIELD_ILLEGAL, f"burst_len {value} is below this protocol's legal minimum {min_beats} beats for {burst_type!r}"
    if max_beats is not None and value > max_beats:
        return FIELD_ILLEGAL, f"burst_len {value} exceeds this protocol's legal maximum {max_beats} beats for {burst_type!r}"
    return FIELD_LEGAL, f"burst_len {value} is within this protocol's legal range for {burst_type!r}"


def _check_burst_size(legal_value, value, data_width_bytes):
    # `legal_value` is always the descriptive string
    # "power_of_two_bytes_up_to_bus_data_width" in this repo's own
    # `PROTOCOL_LEGAL_FACTS` -- the protocol imposes power-of-two alignment;
    # the upper bound is a DUT/bus fact, not a protocol fact, so it is only
    # checked when the caller supplies one.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProtocolComplianceOracleError(
            "STIMULUS_VALUE_NOT_A_POSITIVE_INT", {"dimension": "burst_size", "value": value})
    if value & (value - 1) != 0:
        return FIELD_ILLEGAL, f"burst_size {value} is not a power-of-two byte count"
    if data_width_bytes is not None and value > data_width_bytes:
        return FIELD_ILLEGAL, (f"burst_size {value} exceeds the declared bus data width "
                               f"{data_width_bytes} bytes")
    return FIELD_LEGAL, f"burst_size {value} is a legal power-of-two transfer size"


def _check_security(legal_value, value):
    # The protocol-legal layer only guarantees the security/protection
    # SIGNAL's existence and meaning (e.g. "AxPROT[1]"); it does not restrict
    # which of secure/non-secure a stimulus may declare -- any declared
    # value is legal once the field itself is applicable.
    return FIELD_LEGAL, f"security field is protocol-applicable ({legal_value}); any declared value is legal"


def check_transaction_field(protocol: str, dimension: str, value: Any, *,
                            burst_type: Optional[str] = None,
                            data_width_bytes: Optional[int] = None) -> Dict[str, Any]:
    """Check ONE declared stimulus field against `amba_master_slave_
    constraint_ir.py`'s real protocol-legal layer for `protocol`. Only the
    four `PER_TRANSACTION_VALUE_CHECKED_DIMENSIONS` (burst_type/burst_len/
    burst_size/security) are recognized here; call `check_transaction_
    stimulus()` for the full-record, all-fields check (applicability +
    value)."""
    if dimension not in PER_TRANSACTION_VALUE_CHECKED_DIMENSIONS:
        raise ProtocolComplianceOracleError("UNRECOGNIZED_VALUE_CHECKED_DIMENSION", {
            "dimension": dimension, "known": list(PER_TRANSACTION_VALUE_CHECKED_DIMENSIONS)})
    protocol_legal_ir = build_protocol_legal_constraint_ir(protocol)
    entry = protocol_legal_ir["fields"][dimension]
    if entry["status"] == IR_FIELD_NOT_APPLICABLE:
        return {"status": FIELD_NOT_APPLICABLE, "reason": (entry["basis"][0] if entry["basis"] else "not applicable")}
    if entry["status"] == IR_FIELD_APPLICABILITY_UNKNOWN:
        return {"status": FIELD_PROTOCOL_UNRESOLVED,
               "reason": (entry["basis"][0] if entry["basis"] else "protocol unresolved")}
    legal_value = entry["legal_value"]
    if dimension == "burst_type":
        status, reason = _check_burst_type(legal_value, value)
    elif dimension == "burst_len":
        status, reason = _check_burst_len(legal_value, value, burst_type)
    elif dimension == "burst_size":
        status, reason = _check_burst_size(legal_value, value, data_width_bytes)
    elif dimension == "security":
        status, reason = _check_security(legal_value, value)
    else:  # pragma: no cover - guarded above
        raise ProtocolComplianceOracleError("UNRECOGNIZED_VALUE_CHECKED_DIMENSION", {"dimension": dimension})
    return {"status": status, "reason": reason}


def check_transaction_stimulus(protocol: str, transaction: dict, *,
                               data_width_bytes: Optional[int] = None) -> Dict[str, Any]:
    """The full per-transaction check: every key in `transaction` that names
    a real `AMBA_TRANSACTION_IR_FIELDS` field is checked for applicability
    (via `amba_transaction_ir.ir_field_applicability()`), and every one of
    the four value-checked dimensions additionally has its VALUE checked
    against the real protocol-legal layer. A field this module does not
    recognize as an IR field (or one of the two `ALLOWED_NON_IR_KEYS`) is
    refused (a caller typo must not silently pass unclassified)."""
    if not isinstance(transaction, dict):
        raise ProtocolComplianceOracleError("TRANSACTION_NOT_A_DICT", {"transaction": transaction})
    declared_fields = [k for k in transaction if k in AMBA_TRANSACTION_IR_FIELDS]
    unknown_keys = [k for k in transaction
                    if k not in AMBA_TRANSACTION_IR_FIELDS and k not in ALLOWED_NON_IR_KEYS]
    if unknown_keys:
        raise ProtocolComplianceOracleError("TRANSACTION_HAS_UNRECOGNIZED_KEYS", {
            "unknown_keys": unknown_keys, "known_ir_fields": list(AMBA_TRANSACTION_IR_FIELDS)})

    applicability = ir_field_applicability(protocol)
    burst_type_value = transaction.get("burst_type")
    fields: Dict[str, Dict[str, Any]] = {}
    for field in declared_fields:
        applies = applicability[field]
        if applies["status"] == IR_FIELD_NOT_APPLICABLE:
            fields[field] = {
                "status": FIELD_ILLEGAL,
                "reason": (f"stimulus declares a value for {field!r}, but this protocol does not "
                          f"carry it ({applies['reason']}) -- a generated pattern must never force "
                          f"a protocol-inapplicable field")}
            continue
        if applies["status"] == IR_FIELD_APPLICABILITY_UNKNOWN:
            fields[field] = {"status": FIELD_PROTOCOL_UNRESOLVED, "reason": applies["reason"]}
            continue
        if field in PER_TRANSACTION_VALUE_CHECKED_DIMENSIONS:
            fields[field] = check_transaction_field(
                protocol, field, transaction[field], burst_type=burst_type_value,
                data_width_bytes=data_width_bytes)
        else:
            fields[field] = {"status": FIELD_APPLICABILITY_ONLY,
                             "reason": f"{field!r} is protocol-applicable; this module has no "
                                      f"value-legality rule for it"}

    # `security` is NOT one of `AMBA_TRANSACTION_IR_FIELDS` (see
    # `ALLOWED_NON_IR_KEYS`'s own docstring), so its applicability is read
    # directly off the protocol-legal layer rather than through
    # `ir_field_applicability()`, which has no entry for it at all. The
    # SAME forced-inapplicable-field rule the loop above applies to every
    # real IR field is applied here too, for consistency: a security value
    # declared on a protocol that carries no security/protection signal at
    # all is a real, illegal forced field -- never merely FIELD_NOT_APPLICABLE
    # (that status is `check_transaction_field()`'s own standalone-primitive
    # meaning, used when a caller checks one dimension's VALUE in isolation
    # with no "was this even declared" context; it is not reused here).
    if "security" in transaction:
        sec_entry = build_protocol_legal_constraint_ir(protocol)["fields"]["security"]
        if sec_entry["status"] == IR_FIELD_NOT_APPLICABLE:
            fields["security"] = {
                "status": FIELD_ILLEGAL,
                "reason": (f"stimulus declares a value for 'security', but this protocol carries "
                          f"no security/protection signal ("
                          f"{sec_entry['basis'][0] if sec_entry['basis'] else 'not applicable'}) -- "
                          f"a generated pattern must never force a protocol-inapplicable field")}
        elif sec_entry["status"] == IR_FIELD_APPLICABILITY_UNKNOWN:
            fields["security"] = {
                "status": FIELD_PROTOCOL_UNRESOLVED,
                "reason": sec_entry["basis"][0] if sec_entry["basis"] else "protocol unresolved"}
        else:
            fields["security"] = check_transaction_field(protocol, "security", transaction["security"])

    overall = _fold([f["status"] for f in fields.values()])
    return {"stimulus_id": transaction.get("stimulus_id"), "protocol": protocol,
           "status": overall, "fields": fields}


# ===========================================================================
# Pattern-level (stream) checks: outstanding, ordering
# ===========================================================================


def check_pattern_outstanding(protocol: str, transactions: Sequence[dict],
                              concurrent_groups: Optional[Sequence[Sequence[Any]]] = None) -> Dict[str, Any]:
    """Whether the pattern's declared concurrency ever exceeds this
    protocol's real HARD outstanding-transaction cap.

    The protocol-legal layer's `outstanding` legal_value is a plain `int`
    ONLY for the AHB/APB family (a real, protocol-mandated hard cap); for an
    ID-bearing AXI-family protocol it is a dict naming that the protocol
    itself mandates no numeric ceiling (the real bound is a DUT ID-width
    fact this module never invents). So this check can only ever find a
    violation on a hard-capped protocol, and reports `FIELD_NOT_APPLICABLE`
    (nothing to violate) for an uncapped one.

    `concurrent_groups` is the caller's own declared evidence -- each entry
    a list of `stimulus_id`s the caller asserts were genuinely in flight at
    the same time. Absent it, this module invents no concurrency assumption
    of its own and reports `FIELD_NOT_CHECKED`."""
    protocol_legal_ir = build_protocol_legal_constraint_ir(protocol)
    entry = protocol_legal_ir["fields"]["outstanding"]
    if entry["status"] == IR_FIELD_NOT_APPLICABLE:
        return {"status": FIELD_NOT_APPLICABLE, "reason": (entry["basis"][0] if entry["basis"] else "not applicable")}
    if entry["status"] == IR_FIELD_APPLICABILITY_UNKNOWN:
        return {"status": FIELD_PROTOCOL_UNRESOLVED, "reason": (entry["basis"][0] if entry["basis"] else "protocol unresolved")}
    legal_value = entry["legal_value"]
    if not isinstance(legal_value, int):
        return {"status": FIELD_NOT_APPLICABLE,
               "reason": "this protocol imposes no numeric outstanding-transaction ceiling; "
                        "a real cap is a DUT ID-width/channel-capacity fact this module never invents"}
    if not concurrent_groups:
        return {"status": FIELD_NOT_CHECKED,
               "reason": "no caller-declared concurrent_groups evidence was supplied; a "
                        "concurrency assumption is never invented"}
    violations = []
    for group in concurrent_groups:
        if len(group) > legal_value:
            violations.append({"group": list(group), "size": len(group), "legal_max": legal_value})
    if violations:
        return {"status": FIELD_ILLEGAL,
               "reason": f"at least one declared concurrent group exceeds this protocol's legal "
                        f"maximum of {legal_value} outstanding transaction(s)",
               "violations": violations}
    return {"status": FIELD_LEGAL,
           "reason": f"every declared concurrent group stays within the legal maximum of "
                    f"{legal_value} outstanding transaction(s)"}


def check_pattern_ordering(protocol: str, transactions: Sequence[dict]) -> Dict[str, Any]:
    """Whether the pattern's own declared issue/completion order respects
    this protocol's real ordering requirement, reusing `amba_master_slave_
    constraint_ir.py`'s own real ordering-token vocabulary
    (`ORDERING_STRICT_PROGRAM_ORDER` / `ORDERING_PER_ID` / the AXI4-Stream
    in-order-within-TID token) for what "respects" means per required token.

    Requires each transaction to carry `sequence_number` (its real issue
    order, an `AMBA_TRANSACTION_IR_FIELDS` field) AND this module's own
    `completion_sequence` key (its completion order -- not an IR field,
    since no prior IR in this repo models one; this module's own required
    temporal evidence). A transaction missing either is excluded from the
    comparison and reported, never silently treated as compliant.

    For a PER-ID ordering requirement (AXI's `ordering: same ID -> in order,
    different ID -> unordered permitted`), grouping is by the transaction's
    own real `transaction_id` field (SYOSCB-10's AWID/ARID/BID/RID/TID
    value) -- NEVER by `stimulus_id`, a caller's own display label. A pair
    where either side declares no `transaction_id` cannot be judged same-ID
    or different-ID, so it is excluded from comparison and reported under
    `insufficient_id_evidence`, never assumed to share one implicit ID.

    Fewer than TWO transactions in the whole pattern is `FIELD_NOT_APPLICABLE`
    -- there is nothing to order among fewer than two items, the same
    single-element-is-vacuous discipline this project applies elsewhere
    (e.g. a fairness index over one requester). Fewer than two transactions
    carrying the TEMPORAL EVIDENCE needed to compare them, when two or more
    transactions genuinely exist, is the honestly different `FIELD_NOT_
    CHECKED` -- real transactions exist to compare, the evidence to do so
    does not."""
    transactions = list(transactions or ())
    for txn in transactions:
        if not isinstance(txn, dict):
            raise ProtocolComplianceOracleError("TRANSACTION_NOT_A_DICT", {"transaction": txn})
    if len(transactions) < 2:
        return {"status": FIELD_NOT_APPLICABLE,
               "reason": "fewer than two transactions in this pattern; ordering has nothing "
                        "to order among"}

    protocol_legal_ir = build_protocol_legal_constraint_ir(protocol)
    entry = protocol_legal_ir["fields"]["ordering"]
    if entry["status"] == IR_FIELD_NOT_APPLICABLE:
        return {"status": FIELD_NOT_APPLICABLE, "reason": (entry["basis"][0] if entry["basis"] else "not applicable")}
    if entry["status"] == IR_FIELD_APPLICABILITY_UNKNOWN:
        return {"status": FIELD_PROTOCOL_UNRESOLVED, "reason": (entry["basis"][0] if entry["basis"] else "protocol unresolved")}
    required_ordering = entry["legal_value"]

    checkable = []
    skipped = []
    for txn in transactions:
        if not isinstance(txn, dict):
            raise ProtocolComplianceOracleError("TRANSACTION_NOT_A_DICT", {"transaction": txn})
        seq = txn.get("sequence_number")
        comp = txn.get("completion_sequence")
        if seq is None or comp is None:
            skipped.append(txn.get("stimulus_id"))
            continue
        checkable.append(txn)

    if len(checkable) < 2:
        return {"status": FIELD_NOT_CHECKED,
               "reason": "fewer than two transactions carry both sequence_number and "
                        "completion_sequence evidence; no temporal ordering could be checked",
               "skipped_transactions": skipped}

    per_id_only = (required_ordering == "PER_ID_ORDERED_CROSS_ID_UNORDERED_PERMITTED"
                  or required_ordering ==
                  "IN_ORDER_WITHIN_STREAM_TID_INTERLEAVE_PERMITTED_IF_TID_PRESENT")
    violations = []
    insufficient_id_evidence = []
    for i, a in enumerate(checkable):
        for b in checkable[i + 1:]:
            if per_id_only:
                id_a, id_b = a.get("transaction_id"), b.get("transaction_id")
                if id_a is None or id_b is None:
                    insufficient_id_evidence.append(
                        {"a": a.get("stimulus_id"), "b": b.get("stimulus_id"),
                         "reason": "at least one side declares no transaction_id; same-ID/"
                                  "different-ID grouping cannot be determined"})
                    continue
                if id_a != id_b:
                    continue
            issue_a, issue_b = a["sequence_number"], b["sequence_number"]
            if issue_a == issue_b:
                continue
            issued_first, issued_second = (a, b) if issue_a < issue_b else (b, a)
            if issued_first["completion_sequence"] > issued_second["completion_sequence"]:
                violations.append({
                    "issued_first": issued_first.get("stimulus_id"),
                    "issued_second": issued_second.get("stimulus_id"),
                    "reason": "issued first but completed after the transaction issued after it"})
    if violations:
        return {"status": FIELD_ILLEGAL,
               "reason": f"this protocol requires {required_ordering!r} ordering, which the "
                        f"declared issue/completion sequence violates",
               "violations": violations, "skipped_transactions": skipped,
               "insufficient_id_evidence": insufficient_id_evidence}
    return {"status": FIELD_LEGAL,
           "reason": f"the declared issue/completion sequence respects this protocol's required "
                    f"{required_ordering!r} ordering", "skipped_transactions": skipped,
           "insufficient_id_evidence": insufficient_id_evidence}


# ===========================================================================
# The pattern-level oracle
# ===========================================================================


def check_pattern_protocol_compliance(
    protocol: str, transactions: Sequence[dict], *,
    data_width_bytes: Optional[int] = None,
    concurrent_groups: Optional[Sequence[Sequence[Any]]] = None,
) -> Dict[str, Any]:
    """The oracle's one entry point: is a GENERATED pattern's whole declared
    stimulus protocol-legal. Never runs anything, never reads a scoreboard
    verdict -- every finding is derived from `amba_transaction_ir.py`'s real
    applicability facts and `amba_master_slave_constraint_ir.py`'s real
    protocol-legal layer alone."""
    transactions = list(transactions or ())
    txn_reports = [check_transaction_stimulus(protocol, t, data_width_bytes=data_width_bytes)
                  for t in transactions]
    outstanding_report = check_pattern_outstanding(protocol, transactions, concurrent_groups)
    ordering_report = check_pattern_ordering(protocol, transactions)

    overall = _fold([t["status"] for t in txn_reports]
                    + [outstanding_report["status"], ordering_report["status"]])
    return {
        "protocol": protocol,
        "status": overall,
        "transaction_count": len(transactions),
        "transactions": txn_reports,
        "outstanding": outstanding_report,
        "ordering": ordering_report,
        "rule": "generated_stimulus_checked_against_amba_transaction_ir_applicability_and_"
               "amba_master_slave_constraint_ir_protocol_legal_layer_only",
    }


# ===========================================================================
# Reporting
# ===========================================================================


def render_pattern_compliance_report(report: dict) -> str:
    """One review table over the per-transaction verdicts, plus the two
    pattern-level (outstanding/ordering) findings, using `connectivity.
    render_markdown_table()` -- this repo's one parameterized table renderer,
    not a second one."""
    protocol = report.get("protocol")
    rows = [{"stimulus_id": t.get("stimulus_id"), "status": t.get("status"),
            "illegal_fields": ", ".join(
                f for f, e in (t.get("fields") or {}).items() if e.get("status") == FIELD_ILLEGAL) or "(none)"}
           for t in report.get("transactions") or ()]
    columns = [("stimulus_id", "Transaction"), ("status", "Status"),
              ("illegal_fields", "Illegal Field(s)")]
    lines = [f"# Protocol Compliance Oracle -- {protocol}", "",
            f"Overall: **{report.get('status')}** over {report.get('transaction_count')} "
            f"declared transaction(s).", "",
            "## Per-transaction stimulus legality", "",
            render_markdown_table(columns, rows, empty_note="(no transactions declared)"), "",
            "## Pattern-level: outstanding", "",
            f"- status: {report.get('outstanding', {}).get('status')}",
            f"- {report.get('outstanding', {}).get('reason')}", "",
            "## Pattern-level: ordering", "",
            f"- status: {report.get('ordering', {}).get('status')}",
            f"- {report.get('ordering', {}).get('reason')}", ""]
    return "\n".join(lines)


# ===========================================================================
# Ad hoc front door -- no `dv-harness` CLI verb was registered
# (`dv_harness/gates.py` / `dv_harness/cli.py` are not touched by this
# module), matching several recent same-day modules' own disclosed choice.
# ===========================================================================


def execute_verb(argv=None):
    """`python -m dv_harness.protocol_compliance_oracle --pattern <file.json>
    [--json]`. The pattern file is `{"protocol": ..., "transactions": [...],
    "concurrent_groups": [...]?, "data_width_bytes": ...?}`. Exit 0
    FIELD_LEGAL, 1 FIELD_ILLEGAL, 2 anything else (UNRESOLVED/NOT_CHECKED/
    NOT_APPLICABLE/APPLICABILITY_ONLY, or a usage error) -- never a clean
    exit for a verdict this module did not actually earn."""
    import argparse
    import json as _json
    import sys as _sys

    parser = argparse.ArgumentParser(prog="protocol_compliance_oracle")
    parser.add_argument("--pattern", required=True,
                        help="path to a JSON file: {protocol, transactions, "
                             "concurrent_groups?, data_width_bytes?}")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        with open(args.pattern, "r", encoding="utf-8") as fh:
            payload = _json.load(fh)
    except Exception as exc:
        print(f"NOT_AVAILABLE: could not read/parse {args.pattern!r}: {exc}")
        return 2
    if not isinstance(payload, dict) or "protocol" not in payload:
        print("NOT_AVAILABLE: pattern file must be a JSON object carrying a 'protocol' key")
        return 2

    try:
        report = check_pattern_protocol_compliance(
            payload["protocol"], payload.get("transactions") or (),
            data_width_bytes=payload.get("data_width_bytes"),
            concurrent_groups=payload.get("concurrent_groups"))
    except ProtocolComplianceOracleError as exc:
        print(f"NOT_AVAILABLE: {exc}")
        return 2

    if args.json:
        print(_json.dumps(report, indent=2, default=str))
    else:
        print(render_pattern_compliance_report(report))

    if report["status"] == FIELD_LEGAL:
        return 0
    if report["status"] == FIELD_ILLEGAL:
        return 1
    return 2


def main(argv=None):  # pragma: no cover - thin process entry point
    return execute_verb(argv)


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys
    _sys.exit(main())
