"""Tests for dv_harness/address_map_integrity_checker.py -- pure arithmetic
over a caller-declared address region list: overlap detection, unmapped-hole
detection, and illegal 4KB/protocol-region burst-crossing detection."""
from __future__ import annotations

import pytest

from dv_harness.address_map_integrity_checker import (
    AddressMapIntegrityError,
    analyze_address_map,
    check_overlaps,
    check_transfer_legality,
    check_unmapped_holes,
    normalize_regions,
)

CLEAN_MAP = [
    {"owner": "apb_slave0", "base": "0x0000", "size": "0x1000", "protocol_region": "APB_BUS"},
    {"owner": "ahb_slave1", "base": "0x1000", "size": "0x1000", "protocol_region": "AHB_BUS"},
    {"owner": "mem_bank0", "base": "0x2000", "size": "0x800", "protocol_region": "MEM"},
    {"owner": "mem_bank1", "base": "0x2800", "size": "0x800", "protocol_region": "MEM"},
]


# ---------------------------------------------------------------------------
# (a) Overlap detection
# ---------------------------------------------------------------------------

def test_no_overlaps_on_a_clean_map():
    regions = normalize_regions(CLEAN_MAP)
    assert check_overlaps(regions) == []


def test_overlap_finding_cites_the_real_offending_region_pair_and_range():
    regions = normalize_regions(
        [
            {"owner": "slave_a", "base": "0x0000", "size": "0x2000"},
            {"owner": "slave_b", "base": "0x1000", "size": "0x2000"},
        ]
    )
    findings = check_overlaps(regions)
    assert len(findings) == 1
    f = findings[0]
    assert f["type"] == "OVERLAP"
    owners = {f["region_a"]["owner"], f["region_b"]["owner"]}
    assert owners == {"slave_a", "slave_b"}
    assert f["overlap_start"] == 0x1000
    assert f["overlap_end"] == 0x2000
    assert f["overlap_size"] == 0x1000


def test_a_region_fully_containing_a_smaller_one_is_reported_as_overlap():
    regions = normalize_regions(
        [
            {"owner": "big", "base": "0x0000", "size": "0x10000"},
            {"owner": "small", "base": "0x4000", "size": "0x1000"},
        ]
    )
    findings = check_overlaps(regions)
    assert len(findings) == 1
    assert findings[0]["overlap_start"] == 0x4000
    assert findings[0]["overlap_end"] == 0x5000


# ---------------------------------------------------------------------------
# (b) Unmapped hole detection
# ---------------------------------------------------------------------------

def test_no_holes_reported_between_adjacent_regions_without_a_bounds_declaration():
    regions = normalize_regions(CLEAN_MAP[:2])  # 0x0000-0x1000, 0x1000-0x2000: contiguous
    assert check_unmapped_holes(regions) == []


def test_real_gap_between_two_regions_cites_both_bounding_owners():
    regions = normalize_regions(
        [
            {"owner": "slave_a", "base": "0x0000", "size": "0x1000"},
            {"owner": "slave_b", "base": "0x2000", "size": "0x1000"},
        ]
    )
    findings = check_unmapped_holes(regions)
    assert len(findings) == 1
    f = findings[0]
    assert f["type"] == "UNMAPPED_HOLE"
    assert f["start"] == 0x1000
    assert f["end"] == 0x2000
    assert f["size"] == 0x1000
    assert f["region_before"]["owner"] == "slave_a"
    assert f["region_after"]["owner"] == "slave_b"


def test_a_large_containing_region_never_manufactures_a_phantom_hole():
    regions = normalize_regions(
        [
            {"owner": "big", "base": "0x0000", "size": "0x10000"},
            {"owner": "small", "base": "0x4000", "size": "0x1000"},
        ]
    )
    # small is fully inside big's coverage -- no hole should be reported
    # between them even though small's own end (0x5000) is well short of
    # big's end (0x10000).
    assert check_unmapped_holes(regions) == []


def test_leading_and_trailing_holes_against_a_declared_address_space():
    regions = normalize_regions([{"owner": "slave_a", "base": "0x1000", "size": "0x1000"}])
    findings = check_unmapped_holes(regions, address_space_bits=16)  # [0, 0x10000)
    types_by_range = {(f["start"], f["end"]) for f in findings}
    assert (0, 0x1000) in types_by_range  # leading hole
    assert (0x2000, 0x10000) in types_by_range  # trailing hole
    leading = next(f for f in findings if f["start"] == 0)
    assert leading["region_before"] is None
    assert leading["region_after"]["owner"] == "slave_a"
    trailing = next(f for f in findings if f["end"] == 0x10000)
    assert trailing["region_before"]["owner"] == "slave_a"
    assert trailing["region_after"] is None


def test_zero_regions_with_declared_space_reports_the_whole_space_as_one_hole():
    findings = check_unmapped_holes([], address_space_bits=12)  # [0, 0x1000)
    assert len(findings) == 1
    assert findings[0]["start"] == 0
    assert findings[0]["end"] == 0x1000
    assert findings[0]["region_before"] is None
    assert findings[0]["region_after"] is None


# ---------------------------------------------------------------------------
# (c) Illegal burst/transfer detection
# ---------------------------------------------------------------------------

def test_a_transaction_fully_inside_one_region_and_one_4kb_page_is_clean():
    regions = normalize_regions(CLEAN_MAP)
    txns = [{"id": "T0", "address": "0x0100", "length": "0x40"}]
    assert check_transfer_legality(txns, regions) == []


def test_transfer_crossing_a_4kb_boundary_cites_the_real_boundary_and_transaction():
    regions = normalize_regions(CLEAN_MAP)
    txns = [{"id": "T1", "address": "0x0FF8", "length": "0x10"}]  # 0xFF8..0x1008
    findings = check_transfer_legality(txns, regions)
    boundary_findings = [f for f in findings if f["type"] == "CROSSES_4KB_BOUNDARY"]
    assert len(boundary_findings) == 1
    f = boundary_findings[0]
    assert f["transaction_id"] == "T1"
    assert f["address"] == 0x0FF8
    assert f["end"] == 0x1008
    assert f["boundary_crossed"] == 0x1000


def test_transfer_crossing_a_declared_protocol_region_boundary_cites_both_regions():
    regions = normalize_regions(CLEAN_MAP)
    # apb_slave0 (APB_BUS) ends at 0x1000; ahb_slave1 (AHB_BUS) starts there.
    txns = [{"id": "T2", "address": "0x0FE0", "length": "0x40"}]  # 0xFE0..0x1020
    findings = check_transfer_legality(txns, regions)
    cross = [f for f in findings if f["type"] == "CROSSES_PROTOCOL_REGION_BOUNDARY"]
    assert len(cross) == 1
    f = cross[0]
    assert f["transaction_id"] == "T2"
    assert set(f["protocol_regions_crossed"]) == {"APB_BUS", "AHB_BUS"}
    owners_touched = {r["owner"] for r in f["regions_touched"]}
    assert owners_touched == {"apb_slave0", "ahb_slave1"}


def test_transfer_crossing_two_owners_of_one_declared_protocol_region_is_not_flagged():
    regions = normalize_regions(CLEAN_MAP)
    # mem_bank0/mem_bank1 both declare protocol_region="MEM" and are
    # contiguous (0x2000-0x2800, 0x2800-0x3000); crossing between them must
    # never be reported as a protocol-region-boundary crossing.
    txns = [{"id": "T3", "address": "0x27F0", "length": "0x20"}]  # 0x27F0..0x2810
    findings = check_transfer_legality(txns, regions)
    assert [f["type"] for f in findings] == []


def test_transfer_via_burst_len_and_beat_size_is_resolved_the_same_way_as_length():
    regions = normalize_regions(CLEAN_MAP)
    explicit = check_transfer_legality(
        [{"id": "T4a", "address": "0x0FF8", "length": "0x10"}], regions
    )
    via_burst = check_transfer_legality(
        [{"id": "T4b", "address": "0x0FF8", "burst_len": 4, "beat_size": 4}], regions
    )
    assert [f["type"] for f in explicit] == [f["type"] for f in via_burst]


# ---------------------------------------------------------------------------
# Honest "we cannot claim this is legal" reporting -- the module's analogue
# of an UNKNOWN/NOT_AVAILABLE status for pure region/transfer arithmetic.
# ---------------------------------------------------------------------------

def test_transfer_targeting_a_wholly_unmapped_address_is_never_silently_legal():
    regions = normalize_regions(CLEAN_MAP)  # declared up to 0x3000 only
    txns = [{"id": "T5", "address": "0x9000", "length": "0x10"}]
    findings = check_transfer_legality(txns, regions)
    assert len(findings) == 1
    assert findings[0]["type"] == "TRANSFER_TARGETS_UNMAPPED_ADDRESS"
    assert findings[0]["transaction_id"] == "T5"


def test_transfer_partially_outside_declared_regions_is_reported_not_assumed_legal():
    regions = normalize_regions(CLEAN_MAP)
    # mem_bank1 ends at 0x3000; this transfer runs 0x2F00..0x3100, spilling
    # 0x100 bytes past every declared region -- must not be silently passed.
    txns = [{"id": "T6", "address": "0x2F00", "length": "0x200"}]
    findings = check_transfer_legality(txns, regions)
    partial = [f for f in findings if f["type"] == "TRANSFER_PARTIALLY_UNMAPPED"]
    assert len(partial) == 1
    assert partial[0]["transaction_id"] == "T6"


def test_transfer_with_no_resolvable_length_refuses_rather_than_guesses():
    regions = normalize_regions(CLEAN_MAP)
    with pytest.raises(AddressMapIntegrityError) as exc:
        check_transfer_legality([{"id": "T7", "address": "0x0100"}], regions)
    assert exc.value.reason == "TRANSFER_MISSING_LENGTH"


# ---------------------------------------------------------------------------
# Negative controls: malformed region/transaction input is refused, never
# silently repaired or defaulted.
# ---------------------------------------------------------------------------

def test_region_missing_owner_is_refused():
    with pytest.raises(AddressMapIntegrityError) as exc:
        normalize_regions([{"base": "0x0", "size": "0x1000"}])
    assert exc.value.reason == "REGION_MISSING_OWNER"


def test_region_missing_base_or_size_is_refused():
    with pytest.raises(AddressMapIntegrityError) as exc:
        normalize_regions([{"owner": "slave0", "base": "0x0"}])
    assert exc.value.reason == "REGION_MISSING_BASE_OR_SIZE"


def test_region_with_non_positive_size_is_refused():
    with pytest.raises(AddressMapIntegrityError) as exc:
        normalize_regions([{"owner": "slave0", "base": "0x0", "size": 0}])
    assert exc.value.reason == "REGION_SIZE_NOT_POSITIVE"


def test_region_with_unparseable_address_is_refused():
    with pytest.raises(AddressMapIntegrityError) as exc:
        normalize_regions([{"owner": "slave0", "base": "not_an_address", "size": "0x1000"}])
    assert exc.value.reason == "REGION_ADDRESS_UNPARSEABLE"


def test_no_regions_supplied_at_all_is_refused():
    with pytest.raises(AddressMapIntegrityError) as exc:
        normalize_regions(None)
    assert exc.value.reason == "NO_REGIONS_SUPPLIED"


def test_an_empty_declared_region_list_is_valid_not_an_error():
    # Explicitly zero declared regions is a legitimate, reportable state
    # (an entirely undeclared address map), distinct from `None`.
    assert normalize_regions([]) == []


def test_transaction_missing_address_is_refused():
    regions = normalize_regions(CLEAN_MAP)
    with pytest.raises(AddressMapIntegrityError) as exc:
        check_transfer_legality([{"id": "T8", "length": "0x10"}], regions)
    assert exc.value.reason == "TRANSFER_MISSING_ADDRESS"


# ---------------------------------------------------------------------------
# The combined entry point
# ---------------------------------------------------------------------------

def test_analyze_address_map_status_pass_on_a_clean_map_with_no_transactions():
    report = analyze_address_map(CLEAN_MAP)
    assert report.status == "PASS"
    assert report.overlaps == []
    assert report.illegal_transfers == []


def test_analyze_address_map_status_fail_when_a_real_overlap_exists():
    report = analyze_address_map(
        [
            {"owner": "slave_a", "base": "0x0000", "size": "0x2000"},
            {"owner": "slave_b", "base": "0x1000", "size": "0x2000"},
        ]
    )
    assert report.status == "FAIL"
    assert len(report.overlaps) == 1


def test_analyze_address_map_status_fail_when_a_real_illegal_transfer_exists():
    report = analyze_address_map(
        CLEAN_MAP,
        transactions=[{"id": "T1", "address": "0x0FF8", "length": "0x10"}],
    )
    assert report.status == "FAIL"
    types = {f["type"] for f in report.illegal_transfers}
    # 0x0FF8..0x1008 both crosses the 4KB boundary AND crosses from
    # apb_slave0's protocol region into ahb_slave1's -- both are real,
    # independently-true findings about the same transaction.
    assert "CROSSES_4KB_BOUNDARY" in types


def test_analyze_address_map_reports_holes_without_forcing_a_fail_status():
    report = analyze_address_map(
        [
            {"owner": "slave_a", "base": "0x0000", "size": "0x1000"},
            {"owner": "slave_b", "base": "0x2000", "size": "0x1000"},
        ]
    )
    # A declared gap (reserved space) is a normal, reportable engineering
    # fact, not a defect that should fail the whole map on its own.
    assert report.status == "PASS"
    assert len(report.holes) == 1


def test_analyze_address_map_render_text_includes_every_finding_kind():
    report = analyze_address_map(
        [
            {"owner": "slave_a", "base": "0x0000", "size": "0x2000"},
            {"owner": "slave_b", "base": "0x1000", "size": "0x2000"},
        ],
        transactions=[{"id": "T1", "address": "0x0FF8", "length": "0x10"}],
    )
    text = report.render_text()
    assert "OVERLAP" in text
    assert "slave_a" in text and "slave_b" in text
    assert "CROSSES_4KB_BOUNDARY" in text
