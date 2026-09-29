"""dv_harness/syoscb_result_taxonomy.py -- SYOSCB-21 (REQUIRED SCOREBOARD
RESULT TAXONOMY) and SYOSCB-22 (SCOREBOARD BY PORT VISIBILITY).

Two things, and only two:

  1. SYOSCB-21's fourteen per-transaction verdicts as a real `str` Enum, plus
     the table that routes each one into the EXISTING L5 failure-triage
     vocabulary (`sim_log_analysis`'s categories and severities) -- which is
     what "Feed these into existing L5 failure-triage" asks for.
  2. SYOSCB-22's thirteen per-port counters as a real SHAPE hung off the
     AMBA_PORT_REGISTRY row, joined on that registry's own `port_id`, with
     every counter's feasibility DERIVED from the row rather than assumed.

WHY THIS IS NOT `connectivity.GateStatus`
------------------------------------------
`GateStatus` (PASS/FAIL/NOT_AVAILABLE/PENDING/NOT_YET_RUN) answers "did a
machine GATE run, and what did it conclude" -- one verdict per gate per build.
A `ScoreboardResult` answers "what happened when ONE transaction was compared"
-- one verdict per transaction. They share no member, no domain and no
consumer, and `assert_result_taxonomy_is_disjoint_from_gate_status()` keeps it
that way in code rather than in a comment: a taxonomy that grew a `PASS` would
be the first step toward a scoreboard reporting only PASS/FAIL again, which is
the exact thing SYOSCB-21 opens by forbidding.

WHY THE COUNTERS DO NOT START AT ZERO
--------------------------------------
No real transaction has run, and none can before SYOSCB-34's approval gate.
A counter reading `0` is a CLAIM -- "this port was observed and nothing
happened" -- and it is a false one here. Every counter therefore starts at
`COUNTER_NOT_OBSERVED`, a string, so a consumer that sums counters gets a type
error instead of a plausible-looking zero total.
`assert_counters_unobserved()` is the Phase-1 gate that holds that.

WHERE FEASIBILITY COMES FROM (nothing is re-derived here)
----------------------------------------------------------
SYOSCB-22 says "expose where feasible", so feasibility must be a derived fact,
not a blanket yes. Three real inputs decide it, all read off artifacts that
already exist:

  * Per-protocol applicability -- `amba_transaction_ir.ir_field_applicability()`,
    which derives it from `connectivity.py`'s spec-fixed AMBA signal sets. No
    AMBA signal name is typed in this file. That is what makes `burst_count`
    NOT_APPLICABLE on APB4 (no burst-length signal) and `response_count`
    NOT_APPLICABLE on AXI4-Stream (no response channel) without this module
    holding a second opinion about either bus.
  * Whether anything observes the port at all -- the registry's `vip_mode`.
    `amba_port_registry.VIP_MODE_NOT_PLANNED` means no monitor is planned
    there, so every counter at that port is NOT_FEASIBLE, monitor-derived and
    scoreboard-derived alike.
  * Whether the port feeds a scoreboard -- the registry's `scoreboard_channel`.
    A port whose channel is `REQUIRED_HUMAN_INPUT` can still be observed by its
    own monitor (transaction/read/write/burst/response/error/latency counts are
    monitor-local), but nothing can produce a MATCH or a MISMATCH for it,
    because no comparison exists. That split is the whole reason
    `COUNTER_SOURCE` exists as a column.

THE INFORMATION LOSS IS NAMED, NOT HIDDEN
------------------------------------------
Both mappings are lossy, and each loss is data rather than a footnote:

  * SYOSCB-21 has fourteen values; the existing L5 triage vocabulary has seven
    categories and no protocol-violation category at all. So BURST_ERROR and
    PROTOCOL_TRANSFORM_ERROR are mapped `COARSER` onto `scoreboard_mismatch`
    (severity HIGH) rather than onto `other` (severity LOW) -- routing a real
    fabric transform bug into the LOW bucket is how it would be buried.
  * SYOSCB-22's counter list carries no duplicate-specific counter, so
    DUPLICATE_TRANSACTION increments `unexpected_transaction_count` and is
    marked `COARSER`: the per-port view genuinely cannot tell a duplicate from
    a first-time unexpected transaction, and that is a stated limitation of the
    doc's own counter list, not a modelling choice made here.
  * UNKNOWN is mapped to NOTHING on both sides -- `REQUIRED_HUMAN_INPUT` for
    the triage category and for the counter. Folding an unclassified result
    into `other`/LOW, or into any counter, would let an unexplained comparison
    failure disappear into an aggregate.
    `assert_unknown_is_never_silently_triaged()` proves it.

PHASE-1 ONLY (SYOSCB-33 / SYOSCB-34)
-------------------------------------
No SystemVerilog is emitted, no transaction is compared, no counter is ever
incremented by anything in this repo, and nothing is copied out of
`D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`. `classify_result_counts()` takes counts
a caller supplies and aggregates them; it produces none.
"""
from __future__ import annotations

from enum import Enum

from dv_harness.amba_fabric_discovery import assert_no_bind_statement
from dv_harness.amba_port_registry import (
    AMBA_PORT_REGISTRY_FIELDS,
    VIP_MODE_NOT_PLANNED,
    PortRegistryError,
)
from dv_harness.amba_transaction_ir import (
    IR_FIELD_APPLICABILITY_UNKNOWN,
    IR_FIELD_NOT_APPLICABLE,
    ir_field_applicability,
)
from dv_harness.connectivity import REQUIRED_HUMAN_INPUT, GateStatus, render_markdown_table
from dv_harness.sim_log_analysis import TRIAGE_CATEGORIES, severity_for_category
from dv_harness.syoscb_source_audit import assert_no_emittable_sv


class ScoreboardResultTaxonomyError(PortRegistryError):
    """A result value outside SYOSCB-21's fourteen, a counter block that
    disagrees with the AMBA_PORT_REGISTRY row it hangs off, or a Phase-1
    artifact carrying an observed counter value. Subclasses
    `PortRegistryError` so a caller already handling the AMBA_PORT_REGISTRY
    pipeline's errors handles these too."""


#: The master prompt this module transcribes. Every table entry cites a real
#: line in it, and the tests hold the tables against those lines.
TAXONOMY_DOC = ("DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_"
                "SystemLevel_AMBA4_SyoSil_CCE_Research.md")


# ===========================================================================
# SYOSCB-21: the fourteen per-transaction verdicts
# ===========================================================================

class ScoreboardResult(str, Enum):
    """SYOSCB-21's classification, verbatim and in the doc's own order
    (`{TAXONOMY_DOC}:5049-5062`).

    A `str` Enum for the same reason `connectivity.GateStatus` is one: a
    value round-trips through JSON and a markdown table as itself, so a
    result re-loaded from a persisted artifact compares equal to the member
    without a lookup table in between.

    Each member is a verdict about ONE compared transaction:

    - MATCH: the expected and actual transaction agreed on every axis the
      SYOSCB-18 match key names. The only non-failure member.
    - DATA_MISMATCH / ADDRESS_MISMATCH / RESPONSE_MISMATCH: the pair matched
      as a pair, and one named field disagreed. Three members rather than one
      because "the data was wrong" and "it went to the wrong address" have
      different root causes and different owners.
    - ROUTE_ERROR: the transaction arrived at a port the SYOSCB-12 route
      prediction says it should not have reached at all -- a decode/routing
      fault, not a field comparison.
    - ORDERING_ERROR: the pair matched but arrived outside the ordering
      tolerance `connectivity.SCOREBOARD_PLAN_FIELDS`' `ordering` /
      `ordering_tolerance_depth` declare for this scoreboard.
    - MISSING_TRANSACTION: an expected transaction that never arrived.
    - UNEXPECTED_TRANSACTION: an observed transaction nothing expected.
    - DUPLICATE_TRANSACTION: a second copy of an already-matched transaction.
      Distinct from UNEXPECTED because the fabric behavior behind it
      (a replayed or double-issued beat) is different from a spurious one.
    - ID_MAPPING_ERROR: the transaction matched, but the fabric-side id did
      not follow the SYOSCB-12 `id_remap` prediction.
    - BURST_ERROR: the burst shape (length/size/type, or a split/merge) did
      not follow the predicted `burst_split_merge` transform.
    - PROTOCOL_TRANSFORM_ERROR: a predicted protocol/width transform
      (SYOSCB-12's `width_conversion` / `bridge_behavior`) did not happen as
      predicted.
    - TIMEOUT: an expected transaction was still unmatched when
      `SCOREBOARD_PLAN_FIELDS`' `orphan_unmatched_timeout` elapsed. Kept
      separate from MISSING_TRANSACTION because a timeout is detected by a
      timer mid-test and a missing transaction at end-of-test drain, which
      are different pieces of evidence about a possibly identical fault.
    - UNKNOWN: a comparison produced a verdict this taxonomy cannot classify.
      Never a synonym for MATCH and never triaged automatically -- see
      `assert_unknown_is_never_silently_triaged()`.
    """
    MATCH = "MATCH"
    DATA_MISMATCH = "DATA_MISMATCH"
    ADDRESS_MISMATCH = "ADDRESS_MISMATCH"
    RESPONSE_MISMATCH = "RESPONSE_MISMATCH"
    ROUTE_ERROR = "ROUTE_ERROR"
    ORDERING_ERROR = "ORDERING_ERROR"
    MISSING_TRANSACTION = "MISSING_TRANSACTION"
    UNEXPECTED_TRANSACTION = "UNEXPECTED_TRANSACTION"
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"
    ID_MAPPING_ERROR = "ID_MAPPING_ERROR"
    BURST_ERROR = "BURST_ERROR"
    PROTOCOL_TRANSFORM_ERROR = "PROTOCOL_TRANSFORM_ERROR"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


#: The fourteen values as plain strings, in the doc's order. The tuple is the
#: contract that keeps the enum and every table below iterating the same list.
SCOREBOARD_RESULT_VALUES: tuple = tuple(r.value for r in ScoreboardResult)

#: MATCH's triage category. Not `"other"`: a match is not a low-severity
#: failure, it is not a failure, and feeding it into a failure-triage bucket
#: at all would put successful comparisons in the failure report.
TRIAGE_NOT_A_FAILURE = "NOT_A_FAILURE"

#: The mapping named the same thing on both sides.
MAP_EXACT = "EXACT"
#: The target is a strict superset of the result -- the distinction is really
#: lost, and this string is where that loss is recorded instead of implied.
MAP_COARSER = "COARSER_THAN_RESULT"
#: Deliberately unmapped. MATCH (not a failure) and UNKNOWN (unclassified).
MAP_NONE = "NO_MAPPING"


def _triage(category, precision, counter, counter_precision, doc_line, reason):
    return {"triage_category": category, "triage_precision": precision,
            "port_counter": counter, "counter_precision": counter_precision,
            "doc_line": doc_line, "reason": reason}


#: SYOSCB-21's "Feed these into existing L5 failure-triage", as the real
#: routing table. `triage_category` is one of `sim_log_analysis`'s own
#: categories (checked at import by `_assert_triage_categories_are_real()`),
#: never a new vocabulary; SEVERITY is deliberately absent because it is
#: derived from that category at call time by `sim_log_analysis.
#: severity_for_category()`, so this table cannot hold a severity that
#: disagrees with the one the log triage path assigns.
RESULT_TRIAGE: dict = {
    ScoreboardResult.MATCH: _triage(
        TRIAGE_NOT_A_FAILURE, MAP_NONE, "match_count", MAP_EXACT, 5049,
        "a match is not a failure and is never routed into failure triage"),
    ScoreboardResult.DATA_MISMATCH: _triage(
        "scoreboard_mismatch", MAP_EXACT, "mismatch_count", MAP_EXACT, 5050,
        "the L5 triage category names exactly this: a scoreboard compare that "
        "found differing payload"),
    ScoreboardResult.ADDRESS_MISMATCH: _triage(
        "scoreboard_mismatch", MAP_EXACT, "mismatch_count", MAP_COARSER, 5051,
        "SYOSCB-22's counter list has one 'mismatches' counter, so the address "
        "axis is not separable in the per-port view"),
    ScoreboardResult.RESPONSE_MISMATCH: _triage(
        "scoreboard_mismatch", MAP_EXACT, "mismatch_count", MAP_COARSER, 5052,
        "same single 'mismatches' counter; the response axis is not separable "
        "per port"),
    ScoreboardResult.ROUTE_ERROR: _triage(
        "scoreboard_mismatch", MAP_COARSER, "route_error_count", MAP_EXACT, 5053,
        "the L5 triage vocabulary has no routing category, so this lands in the "
        "HIGH-severity scoreboard bucket rather than the LOW-severity 'other'"),
    ScoreboardResult.ORDERING_ERROR: _triage(
        "scoreboard_mismatch", MAP_COARSER, "ordering_error_count", MAP_EXACT, 5054,
        "no ordering category exists in L5 triage; SYOSCB-22 does carry its own "
        "per-port ordering counter"),
    ScoreboardResult.MISSING_TRANSACTION: _triage(
        "scoreboard_mismatch", MAP_COARSER, "missing_transaction_count", MAP_EXACT, 5055,
        "L5 triage has no 'missing' category; the per-port counter list does"),
    ScoreboardResult.UNEXPECTED_TRANSACTION: _triage(
        "scoreboard_mismatch", MAP_COARSER, "unexpected_transaction_count", MAP_EXACT, 5056,
        "L5 triage has no 'unexpected' category; the per-port counter list does"),
    ScoreboardResult.DUPLICATE_TRANSACTION: _triage(
        "scoreboard_mismatch", MAP_COARSER, "unexpected_transaction_count", MAP_COARSER, 5057,
        "SYOSCB-22's counter list carries no duplicate-specific counter, so the "
        "per-port view cannot distinguish a duplicate from a first-time "
        "unexpected transaction"),
    ScoreboardResult.ID_MAPPING_ERROR: _triage(
        "scoreboard_mismatch", MAP_COARSER, "mismatch_count", MAP_COARSER, 5058,
        "an id-remap fault is a mismatch on the id axis; neither L5 triage nor "
        "the per-port counter list names the axis"),
    ScoreboardResult.BURST_ERROR: _triage(
        "scoreboard_mismatch", MAP_COARSER, "mismatch_count", MAP_COARSER, 5059,
        "L5 triage has no protocol-violation category; routing this to 'other' "
        "would drop a real burst-transform bug to LOW severity"),
    ScoreboardResult.PROTOCOL_TRANSFORM_ERROR: _triage(
        "scoreboard_mismatch", MAP_COARSER, "mismatch_count", MAP_COARSER, 5060,
        "same missing protocol-violation category; a predicted width/bridge "
        "transform that did not happen is a HIGH finding, not an 'other'"),
    ScoreboardResult.TIMEOUT: _triage(
        "timeout", MAP_EXACT, "missing_transaction_count", MAP_COARSER, 5061,
        "L5 triage names timeout exactly; the per-port list has no timeout "
        "counter, and an orphan that timed out is an expected transaction that "
        "did not arrive"),
    ScoreboardResult.UNKNOWN: _triage(
        REQUIRED_HUMAN_INPUT, MAP_NONE, REQUIRED_HUMAN_INPUT, MAP_NONE, 5062,
        "an unclassified comparison result must be classified by a human; "
        "folding it into 'other'/LOW or into any counter would hide it"),
}


def _assert_triage_categories_are_real() -> None:
    """Every routed category must be one `sim_log_analysis` really defines.

    Runs at import, because a category string this repo's one triage
    vocabulary does not carry would silently take
    `severity_for_category()`'s "LOW" fallback -- turning a routing typo into
    a quietly de-prioritized real failure."""
    unknown = sorted({e["triage_category"] for e in RESULT_TRIAGE.values()}
                     - set(TRIAGE_CATEGORIES)
                     - {TRIAGE_NOT_A_FAILURE, REQUIRED_HUMAN_INPUT})
    if unknown:
        raise ScoreboardResultTaxonomyError("SYOSCB21_TRIAGE_CATEGORY_NOT_IN_L5_VOCABULARY", {
            "categories": unknown, "known": list(TRIAGE_CATEGORIES),
            "hint": "route into sim_log_analysis's existing categories; a new category "
                    "belongs in that module, not in a second private table here"})


def _assert_every_result_is_routed() -> None:
    missing = [r.value for r in ScoreboardResult if r not in RESULT_TRIAGE]
    if missing:
        raise ScoreboardResultTaxonomyError("SYOSCB21_RESULT_NOT_ROUTED", {
            "results": missing,
            "hint": "every one of SYOSCB-21's fourteen values needs a triage route and a "
                    "port counter, even if that route is REQUIRED_HUMAN_INPUT"})


def coerce_result(result) -> ScoreboardResult:
    """A `ScoreboardResult`, or the member a string names.

    Rejects anything else loudly rather than defaulting to UNKNOWN: UNKNOWN
    means "a real comparison produced an unclassifiable verdict", and reusing
    it for "the caller passed a typo" would make the one member that demands
    human attention indistinguishable from a bug in the caller."""
    if isinstance(result, ScoreboardResult):
        return result
    try:
        return ScoreboardResult(result)
    except ValueError as exc:
        raise ScoreboardResultTaxonomyError("SYOSCB21_RESULT_NOT_IN_TAXONOMY", {
            "result": result, "taxonomy": list(SCOREBOARD_RESULT_VALUES),
            "hint": "SYOSCB-21's taxonomy is closed; UNKNOWN is for an unclassifiable "
                    "comparison, not for a value outside the list"}) from exc


def triage_for_result(result) -> dict:
    """One result's full triage routing, severity included.

    Severity is read from `sim_log_analysis.severity_for_category()` at call
    time rather than stored, so this module can never carry a severity the
    log-triage path disagrees with."""
    member = coerce_result(result)
    entry = RESULT_TRIAGE[member]
    category = entry["triage_category"]
    if category == TRIAGE_NOT_A_FAILURE:
        severity = TRIAGE_NOT_A_FAILURE
    elif category == REQUIRED_HUMAN_INPUT:
        severity = REQUIRED_HUMAN_INPUT
    else:
        severity = severity_for_category(category)
    return {"result": member.value, "triage_category": category, "severity": severity,
            "triage_precision": entry["triage_precision"],
            "port_counter": entry["port_counter"],
            "counter_precision": entry["counter_precision"],
            "reason": entry["reason"],
            "evidence": f"{TAXONOMY_DOC}:{entry['doc_line']}"}


def port_counter_for_result(result) -> str:
    """Which SYOSCB-22 per-port counter this result increments, or
    `REQUIRED_HUMAN_INPUT` when the doc's counter list carries none."""
    return RESULT_TRIAGE[coerce_result(result)]["port_counter"]


def assert_unknown_is_never_silently_triaged() -> None:
    """UNKNOWN must route to `REQUIRED_HUMAN_INPUT` on BOTH sides.

    The failure this guards is specific and cheap to introduce: mapping
    UNKNOWN to `other` looks tidy, and it sends every unclassifiable
    comparison result to LOW severity, where it stops being read."""
    entry = RESULT_TRIAGE[ScoreboardResult.UNKNOWN]
    if (entry["triage_category"] != REQUIRED_HUMAN_INPUT
            or entry["port_counter"] != REQUIRED_HUMAN_INPUT):
        raise ScoreboardResultTaxonomyError("SYOSCB21_UNKNOWN_SILENTLY_TRIAGED", {
            "entry": entry,
            "hint": "an unclassified result must reach a human, not a severity bucket or "
                    "an aggregate counter"})


def assert_result_taxonomy_is_disjoint_from_gate_status() -> None:
    """SYOSCB-21's taxonomy and `connectivity.GateStatus` must share no value.

    They answer different questions -- one verdict per COMPARED TRANSACTION
    versus one status per MACHINE GATE RUN -- and the moment a token appears
    in both, a report cannot say which question it answered."""
    overlap = sorted(set(SCOREBOARD_RESULT_VALUES) & {g.value for g in GateStatus})
    if overlap:
        raise ScoreboardResultTaxonomyError("SYOSCB21_TAXONOMY_COLLIDES_WITH_GATE_STATUS", {
            "overlap": overlap,
            "hint": "a per-transaction verdict and a per-gate-run status must stay two "
                    "separate vocabularies"})


# ===========================================================================
# SYOSCB-22: the thirteen per-port counters
# ===========================================================================

#: SYOSCB-22's list, verbatim and in the doc's own order
#: (`{TAXONOMY_DOC}:5074-5086`), as field names. `responses`/`errors` become
#: `response_count`/`error_response_count` so a reader cannot mistake them for
#: the response OBJECTS; every other name is the doc's own noun.
AMBA_PORT_VISIBILITY_COUNTER_FIELDS: tuple = (
    "transaction_count",
    "read_count",
    "write_count",
    "burst_count",
    "response_count",
    "error_response_count",
    "match_count",
    "mismatch_count",
    "missing_transaction_count",
    "unexpected_transaction_count",
    "ordering_error_count",
    "route_error_count",
    "latency",
)

#: The doc line each counter transcribes, so the table is checkable against
#: the requirement rather than merely similar to it.
COUNTER_DOC_LINE: dict = dict(zip(AMBA_PORT_VISIBILITY_COUNTER_FIELDS, range(5074, 5087)))

#: Observable by the port's OWN VIP monitor, with no scoreboard involved.
COUNTER_SOURCE_PORT_MONITOR = "PORT_MONITOR"
#: Only exists once this port's monitor feeds a scoreboard comparison. A port
#: with a monitor but no scoreboard channel has real monitor counters and no
#: match/mismatch counters at all -- these are not the same feasibility
#: question, which is why this column exists.
COUNTER_SOURCE_SCOREBOARD = "SCOREBOARD_COMPARE"

COUNTER_SOURCE: dict = {
    "transaction_count": COUNTER_SOURCE_PORT_MONITOR,
    "read_count": COUNTER_SOURCE_PORT_MONITOR,
    "write_count": COUNTER_SOURCE_PORT_MONITOR,
    "burst_count": COUNTER_SOURCE_PORT_MONITOR,
    "response_count": COUNTER_SOURCE_PORT_MONITOR,
    "error_response_count": COUNTER_SOURCE_PORT_MONITOR,
    "match_count": COUNTER_SOURCE_SCOREBOARD,
    "mismatch_count": COUNTER_SOURCE_SCOREBOARD,
    "missing_transaction_count": COUNTER_SOURCE_SCOREBOARD,
    "unexpected_transaction_count": COUNTER_SOURCE_SCOREBOARD,
    "ordering_error_count": COUNTER_SOURCE_SCOREBOARD,
    "route_error_count": COUNTER_SOURCE_SCOREBOARD,
    "latency": COUNTER_SOURCE_PORT_MONITOR,
}

#: Which AMBA Transaction IR field's per-protocol applicability decides whether
#: a counter means anything on this bus. `None` means the counter is
#: protocol-independent (a transfer either happened or it did not, on every
#: AMBA protocol).
#:
#: `read_count`/`write_count` witness on `transaction_type`, which
#: `amba_transaction_ir` documents as protocol-independent ON PURPOSE --
#: AXI4-Stream's single direction counts as its own transaction type there.
#: This module follows that module's decision rather than holding a second
#: opinion about the same bus; a change belongs in `IR_FIELD_WITNESS_SIGNALS`,
#: where the AMBA signal names actually live.
COUNTER_IR_WITNESS_FIELD: dict = {
    "transaction_count": None,
    "read_count": "transaction_type",
    "write_count": "transaction_type",
    "burst_count": "burst_len",
    "response_count": "response",
    "error_response_count": "response",
    "match_count": None,
    "mismatch_count": None,
    "missing_transaction_count": None,
    "unexpected_transaction_count": None,
    "ordering_error_count": None,
    "route_error_count": None,
    "latency": "timestamp",
}

#: The counter is feasible and nothing has been observed, because no real
#: transaction has run and none can before SYOSCB-34's approval. Deliberately
#: NOT `0`: zero is a measurement, and reporting one here would be a false
#: claim about a run that never happened.
COUNTER_NOT_OBSERVED = "NOT_OBSERVED_NO_RUN_HAS_HAPPENED"
#: No VIP is planned at this port, so nothing will ever observe it. A planning
#: fact a reviewer must see, distinct from "observed nothing".
COUNTER_NOT_FEASIBLE_NO_VIP = "NOT_FEASIBLE_NO_VIP_PLANNED"
#: The bus itself has no such thing (APB4 has no burst length; AXI4-Stream has
#: no response channel). Reuses `amba_transaction_ir`'s vocabulary rather than
#: minting a second not-applicable string.
COUNTER_NOT_APPLICABLE = IR_FIELD_NOT_APPLICABLE
#: Nobody established what this bus is, so the counter's applicability is
#: undecided. Kept distinct from NOT_APPLICABLE for the same reason
#: `amba_transaction_ir` keeps them distinct: only this one is a closable
#: discovery gap.
COUNTER_PROTOCOL_UNRESOLVED = IR_FIELD_APPLICABILITY_UNKNOWN

COUNTER_STATUS_VALUES: frozenset = frozenset({
    COUNTER_NOT_OBSERVED, COUNTER_NOT_FEASIBLE_NO_VIP, COUNTER_NOT_APPLICABLE,
    COUNTER_PROTOCOL_UNRESOLVED, REQUIRED_HUMAN_INPUT,
})

#: Where the counter block hangs on an AMBA_PORT_REGISTRY row.
PORT_VISIBILITY_BLOCK_FIELD = "visibility_counters"


def _assert_counter_tables_agree() -> None:
    """Every counter needs a source, a witness entry and a doc line.

    Runs at import: a counter added to the field tuple without a source would
    silently default nowhere, and a counter whose witness entry is missing
    would read as protocol-independent when it is not."""
    for table, name in ((COUNTER_SOURCE, "COUNTER_SOURCE"),
                        (COUNTER_IR_WITNESS_FIELD, "COUNTER_IR_WITNESS_FIELD"),
                        (COUNTER_DOC_LINE, "COUNTER_DOC_LINE")):
        missing = [f for f in AMBA_PORT_VISIBILITY_COUNTER_FIELDS if f not in table]
        extra = [f for f in table if f not in AMBA_PORT_VISIBILITY_COUNTER_FIELDS]
        if missing or extra:
            raise ScoreboardResultTaxonomyError("SYOSCB22_COUNTER_TABLE_DISAGREES", {
                "table": name, "missing": missing, "unknown": extra})


def _assert_counters_do_not_shadow_registry_columns() -> None:
    """No counter may reuse one of AMBA-22's nineteen column names.

    The counters hang off the SAME row, so a collision would overwrite a real
    registry fact (a width, a clock) with a counter and
    `assert_registry_complete()` would keep passing on the wreckage."""
    clash = sorted(set(AMBA_PORT_VISIBILITY_COUNTER_FIELDS) & set(AMBA_PORT_REGISTRY_FIELDS))
    if clash:
        raise ScoreboardResultTaxonomyError("SYOSCB22_COUNTER_SHADOWS_REGISTRY_COLUMN", {
            "fields": clash})


def _assert_every_result_counter_exists() -> None:
    """Every counter a result routes to must be a real SYOSCB-22 counter."""
    targets = {e["port_counter"] for e in RESULT_TRIAGE.values()} - {REQUIRED_HUMAN_INPUT}
    unknown = sorted(targets - set(AMBA_PORT_VISIBILITY_COUNTER_FIELDS))
    if unknown:
        raise ScoreboardResultTaxonomyError("SYOSCB21_RESULT_ROUTES_TO_ABSENT_COUNTER", {
            "counters": unknown, "known": list(AMBA_PORT_VISIBILITY_COUNTER_FIELDS)})


def _counter_status(field: str, row: dict, applicability: dict) -> tuple:
    """`(status, reason)` for one counter on one registry row.

    Precedence, worst-to-best and deliberately ordered:
      1. the bus has no such thing (definitive, true with or without a VIP),
      2. nothing observes this port at all (blocks every counter),
      3. the bus was never classified (applicability undecided),
      4. the port feeds no scoreboard (blocks the compare-derived counters
         only -- the monitor-derived ones are still feasible),
      5. feasible, and no run has happened.
    """
    witness = COUNTER_IR_WITNESS_FIELD[field]
    witness_status = applicability.get(witness, {}).get("status") if witness else None
    witness_reason = applicability.get(witness, {}).get("reason", "") if witness else ""
    if witness_status == IR_FIELD_NOT_APPLICABLE:
        return COUNTER_NOT_APPLICABLE, (
            f"AMBA Transaction IR field {witness!r} is not applicable here: {witness_reason}")
    if row.get("vip_mode") == VIP_MODE_NOT_PLANNED:
        return COUNTER_NOT_FEASIBLE_NO_VIP, (
            "the AMBA-20 VIP plan proposes no VIP instance at this port, so no monitor "
            "will ever observe it")
    if witness_status == IR_FIELD_APPLICABILITY_UNKNOWN:
        return COUNTER_PROTOCOL_UNRESOLVED, (
            f"AMBA Transaction IR field {witness!r} has undecided applicability: "
            f"{witness_reason}")
    if (COUNTER_SOURCE[field] == COUNTER_SOURCE_SCOREBOARD
            and row.get("scoreboard_channel") == REQUIRED_HUMAN_INPUT):
        return REQUIRED_HUMAN_INPUT, (
            "the AMBA-21 ingress map established no scoreboard channel for this port, so "
            "no comparison exists to produce this counter")
    return COUNTER_NOT_OBSERVED, (
        "feasible; no real transaction has run, and none can before SYOSCB-34 approval")


def build_port_visibility_counters(row: dict) -> dict:
    """SYOSCB-22's counter block for ONE AMBA_PORT_REGISTRY row.

    Keyed back to the registry by `port_id`, so a block can never be silently
    read against the wrong port. Every counter carries a `value`, a `status`,
    its `source` and a `reason` -- never a bare number, and never a blank."""
    port_id = row.get("port_id")
    if not port_id:
        raise ScoreboardResultTaxonomyError("SYOSCB22_COUNTER_BLOCK_WITHOUT_PORT_ID", {
            "row_id": row.get("row_id"),
            "hint": "the counter block joins the registry on port_id; a row without one "
                    "cannot be attributed to a port"})
    applicability = ir_field_applicability(row.get("protocol"))
    counters: dict = {}
    for field in AMBA_PORT_VISIBILITY_COUNTER_FIELDS:
        status, reason = _counter_status(field, row, applicability)
        counters[field] = {"value": status, "status": status,
                           "source": COUNTER_SOURCE[field], "reason": reason,
                           "evidence": f"{TAXONOMY_DOC}:{COUNTER_DOC_LINE[field]}"}
    return {"port_id": port_id, "protocol": row.get("protocol"), "counters": counters}


def attach_port_visibility_counters(rows) -> list:
    """Every registry row, plus its SYOSCB-22 counter block.

    Returns NEW row dicts rather than mutating the caller's: the registry a
    human reviewed at AMBA-22 must stay exactly what they reviewed, and a
    consumer holding the original list must not find counters appearing in it."""
    return [{**row, PORT_VISIBILITY_BLOCK_FIELD: build_port_visibility_counters(row)}
            for row in rows or ()]


def assert_counters_unobserved(rows) -> None:
    """No counter on any row may carry an observed value.

    This is SYOSCB-33/34's gate expressed as a check on the artifact: Phase-1
    has no vendored scoreboard, no build and no run, so any real number here
    came from somewhere that does not exist and would be read as measured
    evidence."""
    for row in rows or ():
        block = row.get(PORT_VISIBILITY_BLOCK_FIELD)
        if not block:
            continue
        for field, entry in (block.get("counters") or {}).items():
            if entry.get("status") not in COUNTER_STATUS_VALUES:
                raise ScoreboardResultTaxonomyError("SYOSCB22_COUNTER_UNKNOWN_STATUS", {
                    "port_id": block.get("port_id"), "counter": field,
                    "status": entry.get("status"), "allowed": sorted(COUNTER_STATUS_VALUES)})
            if isinstance(entry.get("value"), (int, float)) and not isinstance(
                    entry.get("value"), bool):
                raise ScoreboardResultTaxonomyError("SYOSCB22_COUNTER_ALREADY_OBSERVED", {
                    "port_id": block.get("port_id"), "counter": field,
                    "value": entry.get("value"),
                    "hint": "no transaction has run in Phase-1; a numeric counter here would "
                            "present an unrun scoreboard's output as measured evidence"})


def unresolved_port_visibility_counters(rows) -> list:
    """Every counter a human must still make possible, as citable rows.

    A counter blocked by a missing scoreboard channel or an unresolved
    protocol is a real, closable gap; one that is NOT_APPLICABLE for the bus
    is not, and one that is merely unobserved is expected. Only the first kind
    is reported here, so this list is a work item rather than a census."""
    out: list = []
    for row in rows or ():
        block = row.get(PORT_VISIBILITY_BLOCK_FIELD) or {}
        for field, entry in (block.get("counters") or {}).items():
            if entry.get("status") in (REQUIRED_HUMAN_INPUT, COUNTER_PROTOCOL_UNRESOLVED,
                                       COUNTER_NOT_FEASIBLE_NO_VIP):
                out.append({"port_id": block.get("port_id"), "counter": field,
                            "status": entry["status"], "reason": entry["reason"]})
    return out


def classify_result_counts(result_counts: dict) -> dict:
    """Aggregate per-result counts into SYOSCB-22's per-port counters.

    The caller supplies the counts -- this module never produces one, and
    cannot: no comparison runs anywhere in this repo. It exists so the
    SYOSCB-21 -> SYOSCB-22 mapping is EXECUTABLE rather than only declared,
    and so the information the mapping loses is reported alongside the totals
    instead of vanishing into them.

    `unclassified` carries UNKNOWN's count separately: UNKNOWN routes to no
    counter, and adding it to any total would assert a classification nobody
    made."""
    counters = {f: 0 for f in AMBA_PORT_VISIBILITY_COUNTER_FIELDS}
    coarse: list = []
    unclassified = 0
    for result, count in (result_counts or {}).items():
        member = coerce_result(result)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ScoreboardResultTaxonomyError("SYOSCB21_RESULT_COUNT_NOT_A_COUNT", {
                "result": member.value, "count": count,
                "hint": "a result count is a non-negative integer"})
        entry = RESULT_TRIAGE[member]
        target = entry["port_counter"]
        if target == REQUIRED_HUMAN_INPUT:
            unclassified += count
            continue
        counters[target] += count
        if count and entry["counter_precision"] == MAP_COARSER:
            coarse.append({"result": member.value, "counter": target, "count": count,
                           "reason": entry["reason"]})
    return {"counters": counters, "unclassified": unclassified,
            "unclassified_result": ScoreboardResult.UNKNOWN.value,
            "coarse_mappings": coarse}


# ===========================================================================
# Reporting
# ===========================================================================

SYOSCB21_TAXONOMY_COLUMNS: tuple = (
    ("result", "Result"),
    ("triage_category", "L5 Triage Category"),
    ("severity", "Severity"),
    ("triage_precision", "Triage Precision"),
    ("port_counter", "SYOSCB-22 Counter"),
    ("counter_precision", "Counter Precision"),
    ("evidence", "Doc Evidence"),
)

SYOSCB22_COUNTER_COLUMNS: tuple = (
    ("port_id", "port_id"),
    ("protocol", "protocol"),
    ("counter", "Counter"),
    ("source", "Source"),
    ("status", "Status"),
    ("reason", "Reason"),
)


def render_result_taxonomy_table() -> str:
    return render_markdown_table(
        list(SYOSCB21_TAXONOMY_COLUMNS),
        [triage_for_result(r) for r in ScoreboardResult])


def render_port_visibility_table(rows) -> str:
    flat: list = []
    for row in rows or ():
        block = row.get(PORT_VISIBILITY_BLOCK_FIELD) or {}
        for field, entry in (block.get("counters") or {}).items():
            flat.append({"port_id": block.get("port_id"), "protocol": block.get("protocol"),
                         "counter": field, "source": entry["source"],
                         "status": entry["status"], "reason": entry["reason"]})
    return render_markdown_table(
        list(SYOSCB22_COUNTER_COLUMNS), flat,
        empty_note="(no AMBA_PORT_REGISTRY row carried a visibility counter block)")


def render_result_taxonomy_report(rows=None) -> str:
    """The SYOSCB-21/22 review artifact.

    Self-checked with `assert_no_bind_statement()` and
    `assert_no_emittable_sv()` for the same reason every AMBA/SYOSCB planning
    artifact is: a planning document that accidentally rendered emittable
    SystemVerilog would be a way past SYOSCB-33's gate."""
    unresolved = unresolved_port_visibility_counters(rows)
    lines = [
        "# SYOSCB-21 scoreboard result taxonomy and SYOSCB-22 per-port visibility", "",
        f"{len(SCOREBOARD_RESULT_VALUES)} per-transaction result values, routed into "
        "this harness's existing failure-triage categories. Severity is read from "
        "`sim_log_analysis.severity_for_category()`, never stored here.", "",
        render_result_taxonomy_table(), "",
        "## Per-port visibility counters", "",
        f"{len(AMBA_PORT_VISIBILITY_COUNTER_FIELDS)} counters per AMBA_PORT_REGISTRY row, "
        "joined on `port_id`. Every counter reads a real status, never `0`: no transaction "
        "has run, and a zero would claim an observation nobody made.", "",
        render_port_visibility_table(rows), "",
    ]
    if unresolved:
        lines += ["## Counters a human must still make possible", "",
                  render_markdown_table(
                      [("port_id", "port_id"), ("counter", "Counter"),
                       ("status", "Status"), ("reason", "Reason")], unresolved), ""]
    lines.append(
        "Nothing here compares a transaction or increments a counter. The taxonomy is a "
        "vocabulary and the counters are a SHAPE; both are populated only by a Phase-2 "
        "implementation a human approves at SYOSCB-33/34.")
    text = "\n".join(lines)
    assert_no_bind_statement(text)
    assert_no_emittable_sv(text, label="SYOSCB-21/22 result taxonomy report")
    return text


_assert_every_result_is_routed()
_assert_triage_categories_are_real()
_assert_counter_tables_agree()
_assert_counters_do_not_shadow_registry_columns()
_assert_every_result_counter_exists()
assert_unknown_is_never_silently_triaged()
assert_result_taxonomy_is_disjoint_from_gate_status()
