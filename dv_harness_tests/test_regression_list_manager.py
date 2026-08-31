"""Tests for dv_harness/uvm_generator/regression_list_manager.py (9-policy
audit, 2026-08-29): executable form of CLAUDE.md's "LSF DONE is not equal
to DV PASS" rule."""
from __future__ import annotations

import itertools

import pytest

from pathlib import Path

from dv_harness.uvm_generator.regression_list_manager import (
    record_verdict, record_suite, emit_makefile_fragment, apply_verdict_to_file,
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


class TestApplyVerdictToFile:
    def test_creates_file_on_first_pass(self, tmp_path):
        path = tmp_path / "regression.list"
        apply_verdict_to_file(path, "usb2_enum", True)
        assert path.read_text().splitlines() == ["usb2_enum"]

    def test_fail_does_not_create_file_with_pattern_present(self, tmp_path):
        path = tmp_path / "regression.list"
        apply_verdict_to_file(path, "usb2_enum", False)
        assert path.read_text().splitlines() == []

    def test_fail_evicts_existing_pass(self, tmp_path):
        path = tmp_path / "regression.list"
        path.write_text("usb2_enum\nusb3_gen1_enum\n")
        apply_verdict_to_file(path, "usb2_enum", False)
        assert path.read_text().splitlines() == ["usb3_gen1_enum"]

    def test_calling_twice_with_same_verdict_is_idempotent(self, tmp_path):
        path = tmp_path / "regression.list"
        apply_verdict_to_file(path, "usb2_enum", True)
        first = path.read_text()
        apply_verdict_to_file(path, "usb2_enum", True)
        second = path.read_text()
        assert first == second == "usb2_enum\n"

    def test_missing_file_treated_as_empty(self, tmp_path):
        path = tmp_path / "nested" / "regression.list"
        apply_verdict_to_file(path, "usb2_enum", True)
        assert path.read_text().splitlines() == ["usb2_enum"]
