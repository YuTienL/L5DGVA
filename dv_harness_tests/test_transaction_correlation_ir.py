"""Tests for dv_harness/transaction_correlation_ir.py.

Covers the four correlation/bookkeeping mechanisms: response correlation (matching a response back
to its originating request), write/read data-beat association, burst split/merge linkage built on
top of `amba_route_transform_predictor.detect_burst_split_merge()`'s real output shape, and
(SYOSCB-11, added 2026-09-06) logical AXI transaction reconstruction -- joining the first two (and,
where applicable, the third) into one full record per transaction. Every test uses real
evidence-shaped fixtures (never a mocked correlation decision) and includes, per the Evidence Truth
Rule, dedicated negative controls proving the module refuses to claim a match/linkage/association/
reconstruction when the required evidence is genuinely absent or ambiguous.
"""
import json
import subprocess
import sys

import pytest

from dv_harness.amba_route_transform_predictor import (
    TRANSFORM_NOT_IMPLIED,
    TRANSFORM_PREDICTED_FROM_TOPOLOGY,
    detect_burst_split_merge,
    detect_width_conversion,
)
from dv_harness.transaction_correlation_ir import (
    BEAT_ASSOCIATED,
    BEAT_ORPHAN,
    BEAT_UNKNOWN_LENGTH,
    BeatAssociationEntry,
    DataAssociationReport,
    TransactionDataAssociation,
    DATA_ASSOCIATION_COMPLETE,
    DATA_ASSOCIATION_EXCESS,
    DATA_ASSOCIATION_NO_BEATS,
    DATA_ASSOCIATION_PARTIAL,
    DATA_ASSOCIATION_UNKNOWN_LENGTH,
    LINKAGE_CONFIRMED,
    LINKAGE_CONFLICT,
    LINKAGE_INSUFFICIENT_EVIDENCE,
    LINKAGE_NOT_APPLICABLE,
    LINKAGE_PARTIAL,
    LOGICAL_TXN_BURST_LINKAGE_UNCONFIRMED,
    LOGICAL_TXN_COMPLETE,
    LOGICAL_TXN_EXCESS_DATA,
    LOGICAL_TXN_INSUFFICIENT_EVIDENCE,
    LOGICAL_TXN_PARTIAL_DATA,
    LOGICAL_TXN_PENDING,
    LOGICAL_TXN_RESPONSE_AMBIGUOUS,
    LOGICAL_TXN_UNKNOWN_DATA_LENGTH,
    REQUEST_PENDING,
    RESPONSE_AMBIGUOUS_ORDER,
    RESPONSE_MATCHED,
    RESPONSE_UNMATCHED,
    TransactionCorrelationIRError,
    associate_data_beats,
    correlate_responses,
    link_burst_split_merge,
    reconstruct_logical_transactions,
    render_logical_transaction_report,
)


def _req(ref, scope="P0", tid=1, seq=None, evidence=("sim.log:10",)):
    return {"request_ref": ref, "scope": scope, "transaction_id": tid,
            "sequence_number": seq, "evidence": list(evidence)}


def _resp(ref, scope="P0", tid=1, seq=None, evidence=("sim.log:20",)):
    return {"response_ref": ref, "scope": scope, "transaction_id": tid,
            "sequence_number": seq, "evidence": list(evidence)}


# ===========================================================================
# 1. Response correlation
# ===========================================================================

class TestResponseCorrelation:
    def test_single_request_single_response_matches(self):
        entries = correlate_responses([_req("Q1")], [_resp("R1")])
        assert len(entries) == 1
        e = entries[0]
        assert e.status == RESPONSE_MATCHED
        assert e.request_ref == "Q1" and e.response_ref == "R1"
        assert "sim.log:10" in e.evidence and "sim.log:20" in e.evidence

    def test_multiple_outstanding_same_id_matched_by_sequence_number(self):
        # Two writes on the same AWID, same route -- real AXI ordering requires FIFO completion.
        reqs = [_req("Q1", seq=1), _req("Q2", seq=2)]
        resps = [_resp("R2", seq=2), _resp("R1", seq=1)]  # arrival order need not match issue order
        entries = correlate_responses(reqs, resps)
        matched = {e.request_ref: e.response_ref for e in entries if e.status == RESPONSE_MATCHED}
        assert matched == {"Q1": "R1", "Q2": "R2"}

    def test_no_id_protocol_correlates_by_strict_fifo(self):
        # transaction_id=None on both sides (e.g. APB/AHB carry no id at all).
        reqs = [_req("Q1", tid=None, seq=1), _req("Q2", tid=None, seq=2)]
        resps = [_resp("R1", tid=None, seq=1), _resp("R2", tid=None, seq=2)]
        entries = correlate_responses(reqs, resps)
        matched = {e.request_ref: e.response_ref for e in entries if e.status == RESPONSE_MATCHED}
        assert matched == {"Q1": "R1", "Q2": "R2"}

    def test_response_with_no_outstanding_request_is_unmatched(self):
        entries = correlate_responses([], [_resp("R1")])
        assert len(entries) == 1
        assert entries[0].status == RESPONSE_UNMATCHED
        assert entries[0].request_ref is None

    def test_request_with_no_response_is_pending(self):
        entries = correlate_responses([_req("Q1")], [])
        assert len(entries) == 1
        assert entries[0].status == REQUEST_PENDING
        assert entries[0].response_ref is None

    def test_two_scopes_never_cross_matched(self):
        reqs = [_req("Q1", scope="M0_S0"), _req("Q2", scope="M1_S0")]
        resps = [_resp("R1", scope="M1_S0")]
        entries = correlate_responses(reqs, resps)
        by_ref = {e.request_ref: e for e in entries if e.request_ref}
        assert by_ref["Q1"].status == REQUEST_PENDING
        assert by_ref["Q2"].status == RESPONSE_MATCHED

    def test_ambiguous_order_when_two_or_more_missing_sequence_number(self):
        # Two requests share one id and neither declares a sequence_number -- FIFO order is
        # genuinely undecidable and must NOT be resolved by list position.
        reqs = [_req("Q1", seq=None), _req("Q2", seq=None)]
        resps = [_resp("R1", seq=None), _resp("R2", seq=None)]
        entries = correlate_responses(reqs, resps)
        assert all(e.status == RESPONSE_AMBIGUOUS_ORDER for e in entries)
        req_side = {e.request_ref for e in entries if e.request_ref is not None}
        resp_side = {e.response_ref for e in entries if e.response_ref is not None}
        assert req_side == {"Q1", "Q2"}
        assert resp_side == {"R1", "R2"}

    def test_one_missing_sequence_number_among_many_is_still_orderable(self):
        # Only ONE item overall is missing a sequence_number -- the group is still safely orderable
        # because there is no genuine tie to resolve.
        entries = correlate_responses([_req("Q1", seq=1)], [_resp("R1", seq=None)])
        assert entries[0].status == RESPONSE_MATCHED

    def test_request_missing_evidence_is_refused(self):
        bad = {"request_ref": "Q1", "scope": "P0", "transaction_id": 1, "evidence": []}
        with pytest.raises(TransactionCorrelationIRError):
            correlate_responses([bad], [])

    def test_request_missing_ref_is_refused(self):
        bad = {"scope": "P0", "transaction_id": 1, "evidence": ["sim.log:1"]}
        with pytest.raises(TransactionCorrelationIRError):
            correlate_responses([bad], [])

    def test_duplicate_request_ref_is_refused(self):
        with pytest.raises(TransactionCorrelationIRError):
            correlate_responses([_req("Q1"), _req("Q1")], [])


# ===========================================================================
# 2. Write/read data association
# ===========================================================================

def _txn(ref, scope="P0", tid=None, seq=None, expected=None, evidence=("sim.log:1",)):
    return {"transaction_ref": ref, "scope": scope, "transaction_id": tid,
            "sequence_number": seq, "expected_beat_count": expected, "evidence": list(evidence)}


def _beat(ref, scope="P0", bid=None, evidence=("sim.log:2",)):
    return {"beat_ref": ref, "scope": scope, "beat_id": bid, "evidence": list(evidence)}


class TestDataAssociation:
    def test_beats_matched_by_shared_beat_id(self):
        txns = [_txn("W1", tid="AWID0", expected=2)]
        beats = [_beat("B1", bid="AWID0"), _beat("B2", bid="AWID0")]
        report = associate_data_beats(txns, beats)
        assert all(b.status == BEAT_ASSOCIATED for b in report.beats)
        txn_result = report.transactions[0]
        assert txn_result.status == DATA_ASSOCIATION_COMPLETE
        assert txn_result.associated_beat_count == 2

    def test_unlabelled_beats_associated_by_strict_fifo_across_open_transactions(self):
        # AXI4-shaped: W channel carries no per-beat id at all. Two writes, each expecting 2 beats.
        txns = [_txn("W1", seq=1, expected=2), _txn("W2", seq=2, expected=2)]
        beats = [_beat("B1"), _beat("B2"), _beat("B3"), _beat("B4")]
        report = associate_data_beats(txns, beats)
        by_ref = {t.transaction_ref: t for t in report.transactions}
        assert by_ref["W1"].associated_beat_refs == ["B1", "B2"]
        assert by_ref["W2"].associated_beat_refs == ["B3", "B4"]
        assert by_ref["W1"].status == DATA_ASSOCIATION_COMPLETE
        assert by_ref["W2"].status == DATA_ASSOCIATION_COMPLETE

    def test_unknown_expected_length_blocks_further_unlabelled_beats(self):
        # W1 declares no expected_beat_count: nothing past it in this scope can be safely
        # assigned, because W1's own completion point is undecidable.
        txns = [_txn("W1", seq=1, expected=None), _txn("W2", seq=2, expected=1)]
        beats = [_beat("B1"), _beat("B2")]
        report = associate_data_beats(txns, beats)
        assert report.beats[0].status == BEAT_UNKNOWN_LENGTH
        assert report.beats[0].transaction_ref == "W1"
        assert report.beats[1].status == BEAT_UNKNOWN_LENGTH
        by_ref = {t.transaction_ref: t for t in report.transactions}
        assert by_ref["W1"].status == DATA_ASSOCIATION_UNKNOWN_LENGTH
        assert by_ref["W2"].status == DATA_ASSOCIATION_NO_BEATS

    def test_partial_association_when_fewer_beats_than_expected(self):
        txns = [_txn("W1", expected=3)]
        beats = [_beat("B1")]
        report = associate_data_beats(txns, beats)
        assert report.transactions[0].status == DATA_ASSOCIATION_PARTIAL
        assert report.transactions[0].associated_beat_count == 1

    def test_excess_beats_reported_never_silently_accepted(self):
        # beat_id-keyed: more beats observed than the transaction declared expecting.
        txns = [_txn("W1", tid="AWID0", expected=1)]
        beats = [_beat("B1", bid="AWID0"), _beat("B2", bid="AWID0")]
        report = associate_data_beats(txns, beats)
        assert report.beats[0].status == BEAT_ASSOCIATED
        # The second beat cannot be associated to W1 (already full) and there is no other
        # transaction sharing AWID0, so it is an orphan -- never silently over-counted onto W1.
        assert report.beats[1].status == BEAT_ORPHAN
        assert report.transactions[0].status == DATA_ASSOCIATION_COMPLETE

    def test_orphan_beat_with_no_matching_transaction(self):
        report = associate_data_beats([], [_beat("B1", bid="AWID_UNKNOWN")])
        assert report.beats[0].status == BEAT_ORPHAN

    def test_no_beats_observed_transaction_reported_honestly(self):
        report = associate_data_beats([_txn("W1", expected=2)], [])
        assert report.transactions[0].status == DATA_ASSOCIATION_NO_BEATS

    def test_invalid_expected_beat_count_is_refused(self):
        with pytest.raises(TransactionCorrelationIRError):
            associate_data_beats([_txn("W1", expected=-1)], [])

    def test_beat_missing_evidence_is_refused(self):
        bad = {"beat_ref": "B1", "scope": "P0", "beat_id": None, "evidence": []}
        with pytest.raises(TransactionCorrelationIRError):
            associate_data_beats([], [bad])


# ===========================================================================
# 3. Burst split/merge linkage
# ===========================================================================

def _master_row(protocol="AXI4", width=128, port_id="M0"):
    return {"protocol": protocol, "data_width": width, "port_id": port_id}


def _slave_row(protocol="AXI4", width=32, port_id="S0"):
    return {"protocol": protocol, "data_width": width, "port_id": port_id}


def _real_split_event():
    """A genuine `detect_burst_split_merge()` result: AXI4 downsized 128->32 (4x), which the real
    predictor classifies as a BURST_SPLIT with beat_count_factor=4 -- never a hand-typed stand-in."""
    m, s = _master_row(), _slave_row()
    width = detect_width_conversion(m, s)
    event = detect_burst_split_merge(m, s, width)
    assert event["status"] == TRANSFORM_PREDICTED_FROM_TOPOLOGY
    assert event["value"]["beat_count_factor"] == 4
    return event


def _parent(ref="PARENT", addr=0x1000, size=128, evidence=("sim.log:100",)):
    return {"transaction_ref": ref, "address": addr, "total_bytes": size, "evidence": list(evidence)}


def _child(ref, addr, size, evidence=("sim.log:101",)):
    return {"transaction_ref": ref, "address": addr, "total_bytes": size, "evidence": list(evidence)}


class TestBurstSplitMergeLinkage:
    def test_confirmed_linkage_against_a_real_detected_split_event(self):
        event = _real_split_event()
        parent = _parent()
        children = [_child("C1", 0x1000, 32), _child("C2", 0x1020, 32),
                    _child("C3", 0x1040, 32), _child("C4", 0x1060, 32)]
        entry = link_burst_split_merge(event, parent, children)
        assert entry.status == LINKAGE_CONFIRMED
        assert entry.observed_child_count == 4
        assert entry.beat_count_factor == 4
        assert entry.child_refs == ["C1", "C2", "C3", "C4"]

    def test_partial_linkage_when_a_gap_exists_in_address_range(self):
        event = _real_split_event()
        parent = _parent()
        children = [_child("C1", 0x1000, 32), _child("C2", 0x1040, 32),
                    _child("C3", 0x1060, 32)]  # 3 children, matches factor=4? no: factor check first
        # Use a parent/event combo with no factor requirement so the gap itself is what's tested:
        event_no_factor = {"status": TRANSFORM_PREDICTED_FROM_TOPOLOGY,
                           "value": {"kind": event["value"]["kind"]}, "evidence": ["e1"]}
        entry = link_burst_split_merge(event_no_factor, parent, children)
        assert entry.status == LINKAGE_PARTIAL
        assert "gap" in entry.reason

    def test_conflict_when_children_overlap(self):
        event_no_factor = {"status": TRANSFORM_PREDICTED_FROM_TOPOLOGY,
                           "value": {"kind": "SPLIT"}, "evidence": ["e1"]}
        parent = _parent()
        children = [_child("C1", 0x1000, 32), _child("C2", 0x1010, 32)]  # overlaps C1
        entry = link_burst_split_merge(event_no_factor, parent, children)
        assert entry.status == LINKAGE_CONFLICT
        assert "overlaps" in entry.reason

    def test_conflict_when_a_child_falls_outside_the_parent_range(self):
        event_no_factor = {"status": TRANSFORM_PREDICTED_FROM_TOPOLOGY,
                           "value": {"kind": "SPLIT"}, "evidence": ["e1"]}
        parent = _parent(addr=0x1000, size=32)
        children = [_child("C1", 0x1000, 32), _child("C2", 0x2000, 32)]
        entry = link_burst_split_merge(event_no_factor, parent, children)
        assert entry.status == LINKAGE_CONFLICT
        assert "falls outside" in entry.reason

    def test_conflict_when_observed_count_disagrees_with_declared_factor(self):
        event = _real_split_event()  # factor=4
        parent = _parent()
        children = [_child("C1", 0x1000, 32), _child("C2", 0x1020, 32)]  # only 2 observed
        entry = link_burst_split_merge(event, parent, children)
        assert entry.status == LINKAGE_CONFLICT
        assert "beat_count_factor" in entry.reason

    def test_insufficient_evidence_when_parent_address_is_missing(self):
        event = _real_split_event()
        parent = {"transaction_ref": "PARENT", "evidence": ["e1"]}  # no address/total_bytes
        children = [_child("C1", 0x1000, 32)]
        entry = link_burst_split_merge(event, parent, children)
        assert entry.status == LINKAGE_INSUFFICIENT_EVIDENCE

    def test_insufficient_evidence_when_a_child_is_missing_address(self):
        event = _real_split_event()
        parent = _parent()
        children = [{"transaction_ref": "C1", "evidence": ["e1"]}, _child("C2", 0x1020, 32),
                    _child("C3", 0x1040, 32), _child("C4", 0x1060, 32)]
        entry = link_burst_split_merge(event, parent, children)
        assert entry.status == LINKAGE_INSUFFICIENT_EVIDENCE

    def test_not_applicable_when_event_never_claimed_a_split_or_merge(self):
        # Both ends the same width -> the real predictor says NO_TRANSFORM_IMPLIED, never a split.
        m, s = _master_row(width=64), _slave_row(width=64)
        width = detect_width_conversion(m, s)
        event = detect_burst_split_merge(m, s, width)
        assert event["status"] == TRANSFORM_NOT_IMPLIED
        entry = link_burst_split_merge(event, _parent(), [_child("C1", 0x1000, 32)])
        assert entry.status == LINKAGE_NOT_APPLICABLE

    def test_not_applicable_for_an_unrecognized_kind(self):
        event = {"status": TRANSFORM_PREDICTED_FROM_TOPOLOGY,
                "value": {"kind": "SOME_OTHER_TRANSFORM"}, "evidence": ["e1"]}
        entry = link_burst_split_merge(event, _parent(), [_child("C1", 0x1000, 32)])
        assert entry.status == LINKAGE_NOT_APPLICABLE

    def test_child_missing_evidence_is_refused(self):
        event_no_factor = {"status": TRANSFORM_PREDICTED_FROM_TOPOLOGY,
                           "value": {"kind": "SPLIT"}, "evidence": ["e1"]}
        bad_child = {"transaction_ref": "C1", "address": 0x1000, "total_bytes": 32, "evidence": []}
        with pytest.raises(TransactionCorrelationIRError):
            link_burst_split_merge(event_no_factor, _parent(), [bad_child])


# ===========================================================================
# 4. Logical transaction reconstruction (SYOSCB-11)
# ===========================================================================

def _logical_txn(ref, request_ref, scope="P0", evidence=("sim.log:5",)):
    return {"transaction_ref": ref, "request_ref": request_ref, "scope": scope,
            "evidence": list(evidence)}


class TestLogicalTransactionReconstruction:
    def test_complete_transaction_joins_matched_response_and_complete_data(self):
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W1", tid="AWID0", expected=2)],
                                    [_beat("B1", bid="AWID0"), _beat("B2", bid="AWID0")])
        results = reconstruct_logical_transactions(
            [_logical_txn("W1", "Q1")], responses, data)
        assert len(results) == 1
        r = results[0]
        assert r.status == LOGICAL_TXN_COMPLETE
        assert r.request_ref == "Q1"
        assert r.response_ref == "R1"
        assert r.response_status == RESPONSE_MATCHED
        assert r.data_status == DATA_ASSOCIATION_COMPLETE
        assert r.associated_beat_refs == ["B1", "B2"]
        # Evidence is the real union of the transaction's own citation, the response
        # correlation's, and every associated beat's -- never a subset silently dropped.
        assert "sim.log:5" in r.evidence
        assert "sim.log:10" in r.evidence  # from the request
        assert "sim.log:20" in r.evidence  # from the response
        assert "sim.log:2" in r.evidence   # from the beats

    def test_pending_response_outranks_a_fully_complete_data_status(self):
        # No response observed at all -- the request is still pending. Even though the data
        # side is fully complete, the composed status must never claim COMPLETE without a
        # real matched response: pending outranks a clean data status.
        responses = correlate_responses([_req("Q1")], [])
        data = associate_data_beats([_txn("W1", tid="AWID0", expected=1)],
                                    [_beat("B1", bid="AWID0")])
        r = reconstruct_logical_transactions([_logical_txn("W1", "Q1")], responses, data)[0]
        assert r.status == LOGICAL_TXN_PENDING
        assert r.response_ref is None

    def test_ambiguous_response_order_is_surfaced_not_resolved(self):
        reqs = [_req("Q1", tid="ID0"), _req("Q2", tid="ID0")]  # both missing sequence_number
        resps = [_resp("R1", tid="ID0")]
        responses = correlate_responses(reqs, resps)
        data = associate_data_beats([_txn("W1", tid="ID0", expected=0)], [])
        r = reconstruct_logical_transactions([_logical_txn("W1", "Q1")], responses, data)[0]
        assert r.status == LOGICAL_TXN_RESPONSE_AMBIGUOUS
        assert r.response_status == RESPONSE_AMBIGUOUS_ORDER

    def test_partial_data_reported_even_with_a_matched_response(self):
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W1", expected=3)], [_beat("B1")])
        r = reconstruct_logical_transactions([_logical_txn("W1", "Q1")], responses, data)[0]
        assert r.status == LOGICAL_TXN_PARTIAL_DATA
        assert r.data_status == DATA_ASSOCIATION_PARTIAL

    def test_unknown_data_length_reported_never_guessed_complete(self):
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W1", expected=None)], [_beat("B1")])
        r = reconstruct_logical_transactions([_logical_txn("W1", "Q1")], responses, data)[0]
        assert r.status == LOGICAL_TXN_UNKNOWN_DATA_LENGTH

    def test_excess_data_beats_reported(self):
        # associate_data_beats()'s own FIFO cursor advances past a transaction the instant it
        # reaches its declared expected_beat_count, so a genuine excess-beat rollup is not
        # reachable through that function on this fixture shape (confirmed by section 2's own
        # `test_excess_beats_reported_never_silently_accepted`, which asserts the transaction
        # stays DATA_ASSOCIATION_COMPLETE). reconstruct_logical_transactions() is a pure join
        # over an ALREADY-COMPUTED DataAssociationReport, so its own EXCESS-status handling is
        # exercised directly against a synthetic report -- exactly the report shape
        # associate_data_beats() would itself emit if it ever did.
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = DataAssociationReport(
            beats=[BeatAssociationEntry(status=BEAT_ASSOCIATED, beat_ref="B1",
                                        transaction_ref="W1", scope="P0", reason="matched",
                                        evidence=["sim.log:2"])],
            transactions=[TransactionDataAssociation(
                status=DATA_ASSOCIATION_EXCESS, transaction_ref="W1", scope="P0",
                expected_beat_count=1, associated_beat_count=2,
                associated_beat_refs=["B1", "B2"],
                reason="associated 2 beat(s), exceeding the declared expected 1")])
        r = reconstruct_logical_transactions([_logical_txn("W1", "Q1")], responses, data)[0]
        assert r.status == LOGICAL_TXN_EXCESS_DATA

    def test_confirmed_burst_linkage_included_in_a_complete_record(self):
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W1", expected=0)], [])
        event = _real_split_event()
        parent = _parent(ref="W1")
        children = [_child("C1", 0x1000, 32), _child("C2", 0x1020, 32),
                    _child("C3", 0x1040, 32), _child("C4", 0x1060, 32)]
        linkage = link_burst_split_merge(event, parent, children)
        assert linkage.status == LINKAGE_CONFIRMED
        r = reconstruct_logical_transactions(
            [_logical_txn("W1", "Q1")], responses, data, burst_linkage_by_ref={"W1": linkage})[0]
        assert r.status == LOGICAL_TXN_COMPLETE
        assert r.burst_linkage_status == LINKAGE_CONFIRMED
        assert "confirmed" in r.reason

    def test_unconfirmed_burst_linkage_blocks_completeness(self):
        # Response matched and data complete, but the caller's own burst-split-merge linkage for
        # this same parent transaction never confirmed -- the composed record must not read
        # COMPLETE while a real linkage question is still open.
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W1", expected=0)], [])
        event_no_factor = {"status": TRANSFORM_PREDICTED_FROM_TOPOLOGY,
                           "value": {"kind": "SPLIT"}, "evidence": ["e1"]}
        parent = _parent(ref="W1")
        children = [_child("C1", 0x1000, 32), _child("C2", 0x1040, 32),
                    _child("C3", 0x1060, 32)]  # leaves a real gap -> LINKAGE_PARTIAL
        linkage = link_burst_split_merge(event_no_factor, parent, children)
        assert linkage.status == LINKAGE_PARTIAL
        r = reconstruct_logical_transactions(
            [_logical_txn("W1", "Q1")], responses, data, burst_linkage_by_ref={"W1": linkage})[0]
        assert r.status == LOGICAL_TXN_BURST_LINKAGE_UNCONFIRMED
        assert r.burst_linkage_status == LINKAGE_PARTIAL

    def test_burst_linkage_parent_ref_mismatch_is_refused(self):
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W1", expected=0)], [])
        event = _real_split_event()
        linkage = link_burst_split_merge(
            event, _parent(ref="OTHER_PARENT"),
            [_child("C1", 0x1000, 32), _child("C2", 0x1020, 32),
             _child("C3", 0x1040, 32), _child("C4", 0x1060, 32)])
        with pytest.raises(TransactionCorrelationIRError):
            reconstruct_logical_transactions(
                [_logical_txn("W1", "Q1")], responses, data,
                burst_linkage_by_ref={"W1": linkage})

    def test_insufficient_evidence_when_no_response_correlation_entry_exists(self):
        # correlate_responses() was run over a request set that never included this
        # transaction's own request_ref -- the join has genuinely nothing to find, and the
        # module must say so honestly rather than silently treat it as complete or drop it.
        responses = correlate_responses([_req("Q_OTHER")], [_resp("R_OTHER")])
        data = associate_data_beats([_txn("W1", expected=0)], [])
        r = reconstruct_logical_transactions([_logical_txn("W1", "Q1")], responses, data)[0]
        assert r.status == LOGICAL_TXN_INSUFFICIENT_EVIDENCE
        assert "response-correlation" in r.reason

    def test_insufficient_evidence_when_no_data_association_entry_exists(self):
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W_OTHER", expected=0)], [])
        r = reconstruct_logical_transactions([_logical_txn("W1", "Q1")], responses, data)[0]
        assert r.status == LOGICAL_TXN_INSUFFICIENT_EVIDENCE
        assert "data-association" in r.reason

    def test_duplicate_transaction_ref_is_refused(self):
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W1", expected=0)], [])
        with pytest.raises(TransactionCorrelationIRError):
            reconstruct_logical_transactions(
                [_logical_txn("W1", "Q1"), _logical_txn("W1", "Q1")], responses, data)

    def test_transaction_record_missing_evidence_is_refused(self):
        bad = {"transaction_ref": "W1", "request_ref": "Q1", "scope": "P0", "evidence": []}
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W1", expected=0)], [])
        with pytest.raises(TransactionCorrelationIRError):
            reconstruct_logical_transactions([bad], responses, data)

    def test_render_report_covers_every_entry_and_the_empty_case(self):
        responses = correlate_responses([_req("Q1")], [_resp("R1")])
        data = associate_data_beats([_txn("W1", expected=0)], [])
        results = reconstruct_logical_transactions([_logical_txn("W1", "Q1")], responses, data)
        text = render_logical_transaction_report(results)
        assert "LOGICAL_TXN_COMPLETE" in text
        assert "W1" in text
        assert "no transactions supplied" in render_logical_transaction_report([])

    def test_cli_reconstruct_subcommand_end_to_end(self, tmp_path):
        import pathlib
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        (tmp_path / "requests.json").write_text(json.dumps([_req("Q1")]))
        (tmp_path / "responses.json").write_text(json.dumps([_resp("R1")]))
        (tmp_path / "data_transactions.json").write_text(
            json.dumps([_txn("W1", tid="AWID0", expected=2)]))
        (tmp_path / "beats.json").write_text(
            json.dumps([_beat("B1", bid="AWID0"), _beat("B2", bid="AWID0")]))
        (tmp_path / "transactions.json").write_text(
            json.dumps([_logical_txn("W1", "Q1")]))

        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.transaction_correlation_ir", "reconstruct",
             "--transactions", str(tmp_path / "transactions.json"),
             "--requests", str(tmp_path / "requests.json"),
             "--responses", str(tmp_path / "responses.json"),
             "--data-transactions", str(tmp_path / "data_transactions.json"),
             "--beats", str(tmp_path / "beats.json"),
             "--json"],
            cwd=str(repo_root),
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert len(payload) == 1
        assert payload[0]["status"] == LOGICAL_TXN_COMPLETE
