"""Tests for dv_harness/uvm_generator/address_map_verifier.py -- the
three-independent-source register-base-address verification method from
CORE/ip-uvm-dv-gen/SKILL.md (gap-comparison prioritized-gap #1, 2026-08-29)."""
from __future__ import annotations

import pytest

from dv_harness.uvm_generator.address_map_verifier import (
    verify_address_map, emit_verified_base_addr_defines,
    AddressMapVerificationError,
)

DECODER_ENTRY = {
    "instance": "usb_ep0",
    "base": "0x4000_0000",
    "evidence": "DUT/RTLCAT/soc_decoder.v:142 addr[27:16]==12'h400",
}
HISTOGRAM = [
    {"base": "0x4000_0000", "access_count": 37, "source": "command.txt, sanity/ep0_init.txt"},
]
DOC_ENTRY_AGREES = [
    {"instance": "usb_ep0", "base": "0x4000_0000", "doc_ref": "Doc/register_map.pdf p.12"},
]
DOC_ENTRY_DISAGREES = [
    {"instance": "usb_ep0", "base": "0x4000_1000", "doc_ref": "Doc/register_map.pdf p.12"},
]


def test_verify_address_map_all_three_sources_agree():
    result = verify_address_map([DECODER_ENTRY], HISTOGRAM, DOC_ENTRY_AGREES)
    assert len(result) == 1
    entry = result[0]
    assert entry["instance"] == "usb_ep0"
    assert entry["base"] == 0x40000000
    assert entry["base_hex"] == "0x40000000"
    assert entry["histogram_access_count"] == 37
    assert entry["doc_status"] == "AGREES"
    assert entry["doc_ref"] == "Doc/register_map.pdf p.12"


def test_verify_address_map_doc_not_available_is_allowed_not_an_error():
    result = verify_address_map([DECODER_ENTRY], HISTOGRAM, None)
    assert result[0]["doc_status"] == "NOT_AVAILABLE"
    assert result[0]["doc_ref"] is None


def test_verify_address_map_doc_disagreement_is_recorded_not_raised():
    # The document corroborates, it never decides -- a disagreement must not
    # block committal (SKILL.md: "a register document listing two instances
    # at the same address is not necessarily a typo").
    result = verify_address_map([DECODER_ENTRY], HISTOGRAM, DOC_ENTRY_DISAGREES)
    assert result[0]["doc_status"] == "DISAGREES"
    assert result[0]["base"] == 0x40000000  # decoder+histogram still win
    assert result[0]["doc_ref"] == "Doc/register_map.pdf p.12"


def test_verify_address_map_rejects_zero_access_histogram_without_override():
    zero_hist = [{"base": "0x4000_0000", "access_count": 0, "source": "command.txt"}]
    with pytest.raises(AddressMapVerificationError) as exc:
        verify_address_map([DECODER_ENTRY], zero_hist, None)
    assert exc.value.reason == "ZERO_ACCESS_HISTOGRAM"
    assert exc.value.detail["instance"] == "usb_ep0"


def test_verify_address_map_rejects_base_with_no_histogram_entry_at_all():
    with pytest.raises(AddressMapVerificationError) as exc:
        verify_address_map([DECODER_ENTRY], [], None)
    assert exc.value.reason == "ZERO_ACCESS_HISTOGRAM"


def test_verify_address_map_allows_zero_access_with_explicit_override_reason():
    entry = dict(DECODER_ENTRY, zero_access_override_reason="feature not yet under test")
    result = verify_address_map([entry], [], None)
    assert result[0]["histogram_access_count"] == 0
    assert result[0]["zero_access_override_reason"] == "feature not yet under test"


def test_verify_address_map_rejects_missing_decoder_evidence():
    with pytest.raises(AddressMapVerificationError) as exc:
        verify_address_map([{"instance": "usb_ep0", "base": "0x4000_0000"}], HISTOGRAM, None)
    assert exc.value.reason == "MISSING_DECODER_EVIDENCE"
    assert exc.value.detail["field"] == "evidence"


def test_verify_address_map_rejects_missing_decoder_instance():
    with pytest.raises(AddressMapVerificationError) as exc:
        verify_address_map([{"base": "0x4000_0000", "evidence": "x:1"}], HISTOGRAM, None)
    assert exc.value.reason == "MISSING_DECODER_EVIDENCE"
    assert exc.value.detail["field"] == "instance"


def test_verify_address_map_rejects_empty_decoder_entries():
    with pytest.raises(AddressMapVerificationError) as exc:
        verify_address_map([], HISTOGRAM, None)
    assert exc.value.reason == "NO_DECODER_ENTRIES"


def test_verify_address_map_rejects_histogram_entry_missing_source():
    bad_hist = [{"base": "0x4000_0000", "access_count": 5}]
    with pytest.raises(AddressMapVerificationError) as exc:
        verify_address_map([DECODER_ENTRY], bad_hist, None)
    assert exc.value.reason == "MISSING_HISTOGRAM_EVIDENCE"
    assert exc.value.detail["field"] == "source"


def test_verify_address_map_rejects_histogram_entry_bad_access_count_type():
    bad_hist = [{"base": "0x4000_0000", "access_count": "37", "source": "command.txt"}]
    with pytest.raises(AddressMapVerificationError) as exc:
        verify_address_map([DECODER_ENTRY], bad_hist, None)
    assert exc.value.reason == "MISSING_HISTOGRAM_EVIDENCE"
    assert exc.value.detail["field"] == "access_count"


def test_verify_address_map_rejects_doc_entry_missing_doc_ref():
    bad_doc = [{"instance": "usb_ep0", "base": "0x4000_0000"}]
    with pytest.raises(AddressMapVerificationError) as exc:
        verify_address_map([DECODER_ENTRY], HISTOGRAM, bad_doc)
    assert exc.value.reason == "MISSING_DOC_EVIDENCE"
    assert exc.value.detail["field"] == "doc_ref"


def test_verify_address_map_rejects_unparseable_base_address():
    entry = dict(DECODER_ENTRY, base="not_an_address")
    with pytest.raises(AddressMapVerificationError) as exc:
        verify_address_map([entry], HISTOGRAM, None)
    assert exc.value.reason == "UNPARSEABLE_BASE_ADDRESS"


def test_verify_address_map_multiple_instances_independent_results():
    decoder = [
        DECODER_ENTRY,
        {"instance": "usb_ep1", "base": "0x4000_1000", "evidence": "DUT/RTLCAT/soc_decoder.v:150"},
    ]
    hist = HISTOGRAM + [{"base": "0x4000_1000", "access_count": 12, "source": "sanity/ep1_init.txt"}]
    result = verify_address_map(decoder, hist, None)
    assert [e["instance"] for e in result] == ["usb_ep0", "usb_ep1"]
    assert result[1]["base_hex"] == "0x40001000"


def test_emit_verified_base_addr_defines_emits_define_per_verified_entry():
    verified = verify_address_map([DECODER_ENTRY], HISTOGRAM, DOC_ENTRY_AGREES)
    svh = emit_verified_base_addr_defines(verified, "usb_")
    assert "`define USB_USB_EP0_BASE_ADDR 32'h40000000" in svh
    assert DECODER_ENTRY["evidence"] in svh
    assert "doc corroborates" in svh


def test_emit_verified_base_addr_defines_flags_doc_disagreement_visibly():
    verified = verify_address_map([DECODER_ENTRY], HISTOGRAM, DOC_ENTRY_DISAGREES)
    svh = emit_verified_base_addr_defines(verified, "usb_")
    assert "DOC DISAGREEMENT" in svh
    assert "32'h40000000" in svh  # decoder+histogram value still wins, not the doc's


def test_emit_verified_base_addr_defines_rejects_empty_list():
    with pytest.raises(AddressMapVerificationError) as exc:
        emit_verified_base_addr_defines([], "usb_")
    assert exc.value.reason == "NO_VERIFIED_ENTRIES"
