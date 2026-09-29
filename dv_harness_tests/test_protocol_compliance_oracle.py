"""Tests for dv_harness/protocol_compliance_oracle.py.

Every check exercises the REAL `amba_transaction_ir.py` applicability facts
and the REAL `amba_master_slave_constraint_ir.py` protocol-legal layer --
nothing here is mocked or hand-shaped to look like those modules' output.
Several tests are deliberately NEGATIVE CONTROLS proving the oracle refuses
to fabricate a clean verdict when the evidence needed to reach one is
absent (no concurrency evidence, no temporal ordering evidence, an
unresolved protocol) -- per this project's Evidence Truth Rule.
"""
import json
import subprocess
import sys

import pytest

from dv_harness import protocol_compliance_oracle as pco


# ===========================================================================
# Per-transaction, per-field: burst_type
# ===========================================================================


def test_burst_type_legal_value_is_field_legal():
    result = pco.check_transaction_field("AXI4", "burst_type", "INCR")
    assert result["status"] == pco.FIELD_LEGAL


def test_burst_type_illegal_value_is_field_illegal():
    result = pco.check_transaction_field("AXI4", "burst_type", "NOT_A_REAL_BURST_TYPE")
    assert result["status"] == pco.FIELD_ILLEGAL
    assert "NOT_A_REAL_BURST_TYPE" in result["reason"]


def test_burst_type_ahb_specific_values_legal_and_illegal():
    # AHB carries WRAP4/INCR4/etc that AXI4 does not.
    assert pco.check_transaction_field("AHB", "burst_type", "WRAP4")["status"] == pco.FIELD_LEGAL
    # AXI4's FIXED/INCR/WRAP tokens are not AHB's own burst-type vocabulary.
    assert pco.check_transaction_field("AHB", "burst_type", "FIXED")["status"] == pco.FIELD_ILLEGAL


# ===========================================================================
# Per-transaction, per-field: burst_len (depends on burst_type)
# ===========================================================================


def test_burst_len_within_axi4_incr_range_is_legal():
    result = pco.check_transaction_field("AXI4", "burst_len", 256, burst_type="INCR")
    assert result["status"] == pco.FIELD_LEGAL


def test_burst_len_exceeding_axi4_incr_max_is_illegal():
    result = pco.check_transaction_field("AXI4", "burst_len", 300, burst_type="INCR")
    assert result["status"] == pco.FIELD_ILLEGAL
    assert "256" in result["reason"]


def test_burst_len_exceeding_axi4_fixed_max_is_illegal():
    # FIXED/WRAP stay capped at 16 beats on AXI4 even though INCR reaches 256.
    result = pco.check_transaction_field("AXI4", "burst_len", 20, burst_type="FIXED")
    assert result["status"] == pco.FIELD_ILLEGAL
    assert "16" in result["reason"]


def test_burst_len_ahb_wrap4_must_be_exactly_four():
    assert pco.check_transaction_field("AHB", "burst_len", 4, burst_type="WRAP4")["status"] == pco.FIELD_LEGAL
    result = pco.check_transaction_field("AHB", "burst_len", 8, burst_type="WRAP4")
    assert result["status"] == pco.FIELD_ILLEGAL


def test_burst_len_with_no_burst_type_is_not_checked():
    """Negative control: burst_len legality is inherently burst_type-scoped.
    With no burst_type supplied, the oracle refuses to fabricate a verdict."""
    result = pco.check_transaction_field("AXI4", "burst_len", 4, burst_type=None)
    assert result["status"] == pco.FIELD_NOT_CHECKED


def test_burst_len_with_illegal_burst_type_is_not_checked_not_silently_legal():
    """Negative control: an illegal burst_type has no legal range to compare
    against; burst_len must not be reported as LEGAL just because the number
    happens to look reasonable."""
    result = pco.check_transaction_field("AXI4", "burst_len", 4, burst_type="NOT_A_REAL_BURST_TYPE")
    assert result["status"] == pco.FIELD_NOT_CHECKED


# ===========================================================================
# Per-transaction, per-field: burst_size
# ===========================================================================


def test_burst_size_power_of_two_is_legal():
    assert pco.check_transaction_field("AXI4", "burst_size", 4)["status"] == pco.FIELD_LEGAL
    assert pco.check_transaction_field("AXI4", "burst_size", 64)["status"] == pco.FIELD_LEGAL


def test_burst_size_not_power_of_two_is_illegal():
    result = pco.check_transaction_field("AXI4", "burst_size", 3)
    assert result["status"] == pco.FIELD_ILLEGAL


def test_burst_size_exceeding_declared_data_width_is_illegal():
    result = pco.check_transaction_field("AXI4", "burst_size", 64, data_width_bytes=32)
    assert result["status"] == pco.FIELD_ILLEGAL
    assert "32" in result["reason"]


def test_burst_size_within_declared_data_width_is_legal():
    result = pco.check_transaction_field("AXI4", "burst_size", 16, data_width_bytes=32)
    assert result["status"] == pco.FIELD_LEGAL


def test_burst_size_with_no_declared_data_width_only_checks_power_of_two():
    # No DUT bus-width fact supplied -- the protocol layer alone cannot
    # bound the upper end, so a large power-of-two is not flagged.
    result = pco.check_transaction_field("AXI4", "burst_size", 4096)
    assert result["status"] == pco.FIELD_LEGAL


# ===========================================================================
# Per-transaction, per-field: security
# ===========================================================================


def test_security_legal_when_protocol_carries_the_witness_signal():
    result = pco.check_transaction_field("AXI4", "security", True)
    assert result["status"] == pco.FIELD_LEGAL
    result_false = pco.check_transaction_field("AXI4", "security", False)
    assert result_false["status"] == pco.FIELD_LEGAL


def test_security_not_applicable_on_ahb():
    # AHB's HPROT is deliberately excluded from SECURITY_WITNESS_SIGNALS by
    # amba_master_slave_constraint_ir.py itself -- reused here verbatim.
    result = pco.check_transaction_field("AHB", "security", True)
    assert result["status"] == pco.FIELD_NOT_APPLICABLE


# ===========================================================================
# check_transaction_field: refusals
# ===========================================================================


def test_check_transaction_field_rejects_unrecognized_dimension():
    with pytest.raises(pco.ProtocolComplianceOracleError):
        pco.check_transaction_field("AXI4", "not_a_real_dimension", 1)


def test_check_transaction_field_rejects_bad_shape_burst_len():
    with pytest.raises(pco.ProtocolComplianceOracleError):
        pco.check_transaction_field("AXI4", "burst_len", "not-an-int", burst_type="INCR")


def test_check_transaction_field_rejects_bad_shape_burst_size():
    with pytest.raises(pco.ProtocolComplianceOracleError):
        pco.check_transaction_field("AXI4", "burst_size", -4)


# ===========================================================================
# check_transaction_stimulus: the full-record check
# ===========================================================================


def test_transaction_stimulus_all_dimensions_legal_reaches_field_legal():
    """A transaction declaring ONLY the four value-checked dimensions --
    nothing this oracle has no rule for -- reaches a real, fully-earned
    FIELD_LEGAL overall verdict."""
    txn = {"stimulus_id": "t1", "burst_type": "INCR", "burst_len": 8,
          "burst_size": 4, "security": False}
    result = pco.check_transaction_stimulus("AXI4", txn)
    assert result["status"] == pco.FIELD_LEGAL
    assert result["stimulus_id"] == "t1"
    assert all(f["status"] == pco.FIELD_LEGAL for f in result["fields"].values())


def test_transaction_stimulus_one_illegal_field_makes_whole_transaction_illegal():
    txn = {"stimulus_id": "t1", "burst_type": "INCR", "burst_len": 300,
          "burst_size": 4, "security": False}
    result = pco.check_transaction_stimulus("AXI4", txn)
    assert result["status"] == pco.FIELD_ILLEGAL
    assert result["fields"]["burst_len"]["status"] == pco.FIELD_ILLEGAL
    # The other three legal fields did not get swept into the failure.
    assert result["fields"]["burst_type"]["status"] == pco.FIELD_LEGAL
    assert result["fields"]["burst_size"]["status"] == pco.FIELD_LEGAL


def test_transaction_stimulus_forces_protocol_inapplicable_field_is_illegal():
    """AXI4-Stream carries no address signal at all -- a stimulus declaring
    one is exactly the 'forced protocol-inapplicable field' this module
    exists to catch, reusing amba_transaction_ir's own applicability fact."""
    txn = {"stimulus_id": "t1", "address": "0x1000"}
    result = pco.check_transaction_stimulus("AXI4_STREAM", txn)
    assert result["status"] == pco.FIELD_ILLEGAL
    assert result["fields"]["address"]["status"] == pco.FIELD_ILLEGAL
    assert "does not carry it" in result["fields"]["address"]["reason"]


def test_transaction_stimulus_forces_inapplicable_burst_type_on_apb():
    """APB has no burst signal at all -- declaring burst_type on an APB
    stimulus forces a field the protocol does not carry."""
    txn = {"stimulus_id": "t1", "burst_type": "INCR"}
    result = pco.check_transaction_stimulus("APB", txn)
    assert result["status"] == pco.FIELD_ILLEGAL
    assert result["fields"]["burst_type"]["status"] == pco.FIELD_ILLEGAL


def test_transaction_stimulus_unresolved_protocol_reports_protocol_unresolved():
    txn = {"stimulus_id": "t1", "burst_type": "INCR"}
    result = pco.check_transaction_stimulus("NOT_A_REAL_PROTOCOL", txn)
    assert result["status"] == pco.FIELD_PROTOCOL_UNRESOLVED
    assert result["fields"]["burst_type"]["status"] == pco.FIELD_PROTOCOL_UNRESOLVED


def test_transaction_stimulus_field_with_no_value_rule_is_applicability_only():
    """A realistic transaction carrying transaction_id (a real IR field this
    module has no per-value rule for) never claims full legality -- the
    disclosed residual in the module's own docstring."""
    txn = {"stimulus_id": "t1", "transaction_id": "0xA", "burst_type": "INCR",
          "burst_len": 8, "burst_size": 4}
    result = pco.check_transaction_stimulus("AXI4", txn)
    assert result["fields"]["transaction_id"]["status"] == pco.FIELD_APPLICABILITY_ONLY
    assert result["status"] == pco.FIELD_APPLICABILITY_ONLY


def test_transaction_stimulus_stimulus_id_and_completion_sequence_are_never_field_checked():
    txn = {"stimulus_id": "t1", "completion_sequence": 5, "burst_type": "INCR",
          "burst_len": 8, "burst_size": 4}
    result = pco.check_transaction_stimulus("AXI4", txn)
    assert "stimulus_id" not in result["fields"]
    assert "completion_sequence" not in result["fields"]
    assert result["status"] == pco.FIELD_LEGAL


def test_transaction_stimulus_rejects_unrecognized_key():
    with pytest.raises(pco.ProtocolComplianceOracleError):
        pco.check_transaction_stimulus("AXI4", {"totally_made_up_field": 1})


def test_transaction_stimulus_rejects_non_dict():
    with pytest.raises(pco.ProtocolComplianceOracleError):
        pco.check_transaction_stimulus("AXI4", ["not", "a", "dict"])


# ===========================================================================
# Pattern-level: outstanding
# ===========================================================================


def test_pattern_outstanding_hard_cap_violation_on_ahb():
    txns = [{"stimulus_id": "A"}, {"stimulus_id": "B"}]
    result = pco.check_pattern_outstanding("AHB", txns, concurrent_groups=[["A", "B"]])
    assert result["status"] == pco.FIELD_ILLEGAL
    assert result["violations"][0]["legal_max"] == 1


def test_pattern_outstanding_within_hard_cap_is_legal():
    txns = [{"stimulus_id": "A"}]
    result = pco.check_pattern_outstanding("AHB", txns, concurrent_groups=[["A"]])
    assert result["status"] == pco.FIELD_LEGAL


def test_pattern_outstanding_uncapped_axi_protocol_is_not_applicable():
    """AXI4's own protocol-legal 'outstanding' fact is a dict (no numeric
    ceiling mandated by the protocol) -- never a fabricated cap."""
    txns = [{"stimulus_id": "A"}, {"stimulus_id": "B"}, {"stimulus_id": "C"}]
    result = pco.check_pattern_outstanding("AXI4", txns, concurrent_groups=[["A", "B", "C"]])
    assert result["status"] == pco.FIELD_NOT_APPLICABLE


def test_pattern_outstanding_without_concurrency_evidence_is_not_checked():
    """NEGATIVE CONTROL: with no caller-declared concurrency evidence at
    all, the oracle refuses to guess whether the pattern's real concurrency
    ever exceeded the protocol's hard cap -- it reports FIELD_NOT_CHECKED,
    never a fabricated FIELD_LEGAL."""
    txns = [{"stimulus_id": "A"}, {"stimulus_id": "B"}]
    result = pco.check_pattern_outstanding("AHB", txns, concurrent_groups=None)
    assert result["status"] == pco.FIELD_NOT_CHECKED


def test_pattern_outstanding_stream_protocol_is_not_applicable():
    result = pco.check_pattern_outstanding("AXI4_STREAM", [], concurrent_groups=[["A", "B"]])
    assert result["status"] == pco.FIELD_NOT_APPLICABLE


# ===========================================================================
# Pattern-level: ordering
# ===========================================================================


def test_pattern_ordering_strict_program_order_violation_on_ahb():
    txns = [
        {"stimulus_id": "A", "sequence_number": 1, "completion_sequence": 2},
        {"stimulus_id": "B", "sequence_number": 2, "completion_sequence": 1},
    ]
    result = pco.check_pattern_ordering("AHB", txns)
    assert result["status"] == pco.FIELD_ILLEGAL
    assert result["violations"][0]["issued_first"] == "A"
    assert result["violations"][0]["issued_second"] == "B"


def test_pattern_ordering_strict_program_order_respected_is_legal():
    txns = [
        {"stimulus_id": "A", "sequence_number": 1, "completion_sequence": 1},
        {"stimulus_id": "B", "sequence_number": 2, "completion_sequence": 2},
    ]
    result = pco.check_pattern_ordering("AHB", txns)
    assert result["status"] == pco.FIELD_LEGAL


def test_pattern_ordering_per_id_same_id_violation_on_axi4():
    txns = [
        {"stimulus_id": "A", "transaction_id": "0x0", "sequence_number": 1, "completion_sequence": 2},
        {"stimulus_id": "B", "transaction_id": "0x0", "sequence_number": 2, "completion_sequence": 1},
    ]
    result = pco.check_pattern_ordering("AXI4", txns)
    assert result["status"] == pco.FIELD_ILLEGAL


def test_pattern_ordering_per_id_different_ids_may_complete_out_of_order_on_axi4():
    """AXI4's real PER_ID ordering token permits cross-ID reordering -- two
    transactions with DIFFERENT ids completing out of issue order must
    never be flagged."""
    txns = [
        {"stimulus_id": "A", "transaction_id": "0x0", "sequence_number": 1, "completion_sequence": 2},
        {"stimulus_id": "B", "transaction_id": "0x1", "sequence_number": 2, "completion_sequence": 1},
    ]
    result = pco.check_pattern_ordering("AXI4", txns)
    assert result["status"] == pco.FIELD_LEGAL


def test_pattern_ordering_per_id_missing_transaction_id_is_insufficient_evidence_not_a_pass_or_fail():
    """NEGATIVE CONTROL: without a declared transaction_id, this oracle
    cannot tell whether two transactions share one real bus ID -- it must
    never assume they do (which would over-flag) or that they do not
    (which would silently skip a real violation)."""
    txns = [
        {"stimulus_id": "A", "sequence_number": 1, "completion_sequence": 2},
        {"stimulus_id": "B", "sequence_number": 2, "completion_sequence": 1},
    ]
    result = pco.check_pattern_ordering("AXI4", txns)
    assert result["status"] == pco.FIELD_LEGAL
    assert len(result["insufficient_id_evidence"]) == 1
    assert result["insufficient_id_evidence"][0]["a"] == "A"


def test_pattern_ordering_without_temporal_evidence_is_not_checked():
    """NEGATIVE CONTROL: fewer than two transactions carry both
    sequence_number and completion_sequence -- the oracle refuses to
    fabricate an ordering verdict from insufficient temporal evidence."""
    txns = [{"stimulus_id": "A"}, {"stimulus_id": "B", "sequence_number": 1, "completion_sequence": 1}]
    result = pco.check_pattern_ordering("AHB", txns)
    assert result["status"] == pco.FIELD_NOT_CHECKED
    assert result["skipped_transactions"] == ["A"]


def test_pattern_ordering_not_applicable_for_axi4_lite_when_protocol_field_says_so():
    # AXI4-Lite's own protocol-legal ordering fact is still APPLICABLE (it
    # requires strict order); sanity-check it resolves to a real token
    # rather than raising.
    result = pco.check_pattern_ordering("AXI4_LITE", [
        {"stimulus_id": "A", "sequence_number": 1, "completion_sequence": 1},
        {"stimulus_id": "B", "sequence_number": 2, "completion_sequence": 2},
    ])
    assert result["status"] == pco.FIELD_LEGAL


def test_pattern_ordering_unresolved_protocol_reports_protocol_unresolved():
    result = pco.check_pattern_ordering("NOT_A_REAL_PROTOCOL", [
        {"stimulus_id": "A", "sequence_number": 1, "completion_sequence": 1},
        {"stimulus_id": "B", "sequence_number": 2, "completion_sequence": 2},
    ])
    assert result["status"] == pco.FIELD_PROTOCOL_UNRESOLVED


def test_pattern_ordering_rejects_non_dict_transaction():
    with pytest.raises(pco.ProtocolComplianceOracleError):
        pco.check_pattern_ordering("AHB", ["not-a-dict"])


# ===========================================================================
# check_pattern_protocol_compliance: the whole-pattern oracle
# ===========================================================================


def test_pattern_protocol_compliance_single_transaction_pattern_reaches_field_legal():
    """A single-transaction pattern on an ID-width-bounded (uncapped)
    protocol: outstanding is NOT_APPLICABLE (no numeric ceiling), ordering
    is NOT_APPLICABLE (nothing to order among fewer than two items), and the
    one transaction declares only the four value-checked dimensions -- a
    genuinely, fully-earned pattern-level FIELD_LEGAL."""
    txns = [{"stimulus_id": "A", "burst_type": "INCR", "burst_len": 4,
            "burst_size": 4, "security": False}]
    report = pco.check_pattern_protocol_compliance("AXI4", txns)
    assert report["status"] == pco.FIELD_LEGAL
    assert report["transaction_count"] == 1
    assert report["outstanding"]["status"] == pco.FIELD_NOT_APPLICABLE
    assert report["ordering"]["status"] == pco.FIELD_NOT_APPLICABLE


def test_pattern_protocol_compliance_sequence_number_evidence_downgrades_to_applicability_only():
    """A real, disclosed design property: declaring sequence_number/
    completion_sequence evidence (needed to actually VERIFY ordering) also
    makes the per-transaction verdict FIELD_APPLICABILITY_ONLY, since
    sequence_number is a real IR field this module has no value rule for --
    the oracle never claims a pattern is fully FIELD_LEGAL while a real
    declared field went unchecked, even when outstanding and ordering both
    resolve cleanly LEGAL on their own."""
    txns = [
        {"stimulus_id": "A", "burst_type": "INCR", "burst_len": 4, "burst_size": 4,
         "sequence_number": 1, "completion_sequence": 1},
        {"stimulus_id": "B", "burst_type": "INCR", "burst_len": 4, "burst_size": 4,
         "sequence_number": 2, "completion_sequence": 2},
    ]
    report = pco.check_pattern_protocol_compliance("AXI4", txns,
                                                    concurrent_groups=[["A"], ["B"]])
    assert report["ordering"]["status"] == pco.FIELD_LEGAL
    # AXI4's own protocol-legal `outstanding` fact is uncapped (a dict, not
    # an int) -- concurrent_groups evidence is irrelevant to a protocol that
    # imposes no numeric ceiling in the first place.
    assert report["outstanding"]["status"] == pco.FIELD_NOT_APPLICABLE
    assert report["status"] == pco.FIELD_APPLICABILITY_ONLY
    for txn_report in report["transactions"]:
        assert txn_report["fields"]["sequence_number"]["status"] == pco.FIELD_APPLICABILITY_ONLY
        assert txn_report["fields"]["burst_type"]["status"] == pco.FIELD_LEGAL


def test_pattern_protocol_compliance_worst_wins_single_illegal_transaction_fails_whole_pattern():
    txns = [
        {"stimulus_id": "A", "burst_type": "INCR", "burst_len": 4, "burst_size": 4},
        {"stimulus_id": "B", "burst_type": "TOTALLY_MADE_UP", "burst_len": 4, "burst_size": 4},
    ]
    report = pco.check_pattern_protocol_compliance("AXI4", txns)
    assert report["status"] == pco.FIELD_ILLEGAL
    statuses = [t["status"] for t in report["transactions"]]
    assert pco.FIELD_LEGAL in statuses or pco.FIELD_APPLICABILITY_ONLY not in statuses
    assert pco.FIELD_ILLEGAL in statuses


def test_pattern_protocol_compliance_empty_pattern_reports_not_applicable_never_a_fabricated_legal():
    report = pco.check_pattern_protocol_compliance("AXI4", [])
    assert report["transaction_count"] == 0
    assert report["transactions"] == []
    # Fewer than two transactions -> nothing to order among -> NOT_APPLICABLE,
    # never a fabricated LEGAL for a pattern that never declared any stimulus.
    assert report["ordering"]["status"] == pco.FIELD_NOT_APPLICABLE
    assert report["outstanding"]["status"] == pco.FIELD_NOT_APPLICABLE


# ===========================================================================
# Rendering
# ===========================================================================


def test_render_pattern_compliance_report_smoke():
    txns = [{"stimulus_id": "A", "burst_type": "INCR", "burst_len": 4, "burst_size": 4}]
    report = pco.check_pattern_protocol_compliance("AXI4", txns)
    text = pco.render_pattern_compliance_report(report)
    assert "Protocol Compliance Oracle" in text
    assert "AXI4" in text
    assert "A" in text


def test_render_pattern_compliance_report_names_illegal_fields():
    txns = [{"stimulus_id": "A", "burst_type": "NOT_REAL"}]
    report = pco.check_pattern_protocol_compliance("AXI4", txns)
    text = pco.render_pattern_compliance_report(report)
    assert "burst_type" in text


# ===========================================================================
# CLI front door
# ===========================================================================


def _run_cli(args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.protocol_compliance_oracle"] + args,
        capture_output=True, text=True)


def test_cli_exits_zero_on_field_legal(tmp_path):
    pattern_file = tmp_path / "pattern.json"
    pattern_file.write_text(json.dumps({
        "protocol": "AXI4",
        "transactions": [{"stimulus_id": "A", "burst_type": "INCR", "burst_len": 4,
                          "burst_size": 4, "security": False}],
    }), encoding="utf-8")
    result = _run_cli(["--pattern", str(pattern_file)])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FIELD_LEGAL" in result.stdout


def test_cli_exits_one_on_field_illegal(tmp_path):
    pattern_file = tmp_path / "pattern.json"
    pattern_file.write_text(json.dumps({
        "protocol": "AXI4",
        "transactions": [{"stimulus_id": "A", "burst_type": "NOT_A_REAL_BURST_TYPE"}],
    }), encoding="utf-8")
    result = _run_cli(["--pattern", str(pattern_file)])
    assert result.returncode == 1, result.stdout + result.stderr


def test_cli_json_output_is_the_real_report(tmp_path):
    pattern_file = tmp_path / "pattern.json"
    pattern_file.write_text(json.dumps({
        "protocol": "AXI4",
        "transactions": [{"stimulus_id": "A", "burst_type": "INCR", "burst_len": 4,
                          "burst_size": 4, "security": False}],
    }), encoding="utf-8")
    result = _run_cli(["--pattern", str(pattern_file), "--json"])
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["status"] == "FIELD_LEGAL"
    assert parsed["protocol"] == "AXI4"


def test_cli_exits_two_on_unreadable_pattern_file(tmp_path):
    """NEGATIVE CONTROL: a missing/unreadable pattern file must never be
    read as a clean exit -- the CLI refuses honestly with NOT_AVAILABLE."""
    result = _run_cli(["--pattern", str(tmp_path / "does_not_exist.json")])
    assert result.returncode == 2
    assert "NOT_AVAILABLE" in result.stdout


def test_cli_exits_two_on_malformed_pattern_payload(tmp_path):
    pattern_file = tmp_path / "pattern.json"
    pattern_file.write_text(json.dumps({"transactions": []}), encoding="utf-8")
    result = _run_cli(["--pattern", str(pattern_file)])
    assert result.returncode == 2
    assert "NOT_AVAILABLE" in result.stdout
