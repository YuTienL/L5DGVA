"""Tests for dv_harness/uvm_generator/regression_list_manager.py (9-policy
audit, 2026-08-29): executable form of CLAUDE.md's "LSF DONE is not equal
to DV PASS" rule."""
from __future__ import annotations

import itertools

import pytest

from dv_harness.uvm_generator.regression_list_manager import (
    record_verdict, record_suite, emit_makefile_fragment,
)


def test_record_verdict_adds_new_passing_pattern():
    assert record_verdict([], "usb2_enum", True) == ["usb2_enum"]


def test_record_verdict_does_not_add_failing_pattern():
    assert record_verdict([], "usb2_enum", False) == []


def test_record_verdict_evicts_stale_pass_on_new_fail():
    # The exact "LSF DONE != DV PASS" regression this module exists for: a
    # pattern that previously PASSed must NOT still be credited after a rerun
    # FAILs.
    existing = ["usb2_enum", "usb3_gen1_enum"]
    assert record_verdict(existing, "usb2_enum", False) == ["usb3_gen1_enum"]


def test_record_verdict_is_idempotent():
    existing = ["usb2_enum"]
    once = record_verdict(existing, "usb2_enum", True)
    twice = record_verdict(once, "usb2_enum", True)
    assert once == twice == ["usb2_enum"]

    existing = ["usb2_enum"]
    once = record_verdict(existing, "usb2_enum", False)
    twice = record_verdict(once, "usb2_enum", False)
    assert once == twice == []


def test_record_verdict_rejects_empty_pattern():
    with pytest.raises(ValueError):
        record_verdict([], "", True)


def test_record_suite_matches_sequential_record_verdict_calls():
    existing = ["usb2_enum", "usb3_gen1_enum", "usb_dual_port"]
    verdicts = [("usb2_enum", False), ("usb3_gen1_enum", True), ("smoke", True)]

    sequential = list(existing)
    for pattern, passed in verdicts:
        sequential = record_verdict(sequential, pattern, passed)

    assert record_suite(existing, verdicts) == sequential


def test_record_suite_last_verdict_wins_for_duplicate_pattern_in_one_suite():
    existing = []
    verdicts = [("usb2_enum", True), ("usb2_enum", False), ("usb2_enum", True)]

    sequential = list(existing)
    for pattern, passed in verdicts:
        sequential = record_verdict(sequential, pattern, passed)

    assert record_suite(existing, verdicts) == sequential == ["usb2_enum"]


def test_record_suite_matches_sequential_calls_across_many_random_shapes():
    # Broader equivalence sweep: several existing/verdict shapes, all must
    # match the sequential (ground-truth) simulation exactly.
    patterns = ["a", "b", "c", "d"]
    cases = [
        (["a", "b"], [("a", True), ("c", True), ("b", False)]),
        ([], [("a", False), ("b", False)]),
        (["a", "b", "c", "d"], [(p, i % 2 == 0) for i, p in itertools.islice(enumerate(itertools.cycle(patterns)), 8)]),
    ]
    for existing, verdicts in cases:
        sequential = list(existing)
        for pattern, passed in verdicts:
            sequential = record_verdict(sequential, pattern, passed)
        assert record_suite(existing, verdicts) == sequential


def test_record_suite_rejects_empty_pattern():
    with pytest.raises(ValueError):
        record_suite([], [("", True)])


def test_emit_makefile_fragment_references_real_path_and_targets():
    frag = emit_makefile_fragment("sim/scripts/regression.list")
    assert "REGRESSION_LIST_PATH := sim/scripts/regression.list" in frag
    assert "regression-list-show:" in frag
    assert "regression-list-clean:" in frag
