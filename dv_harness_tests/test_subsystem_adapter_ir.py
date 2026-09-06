"""Tests for dv_harness/subsystem_adapter_ir.py -- the SubsystemAdapterIR
compatibility facade over an existing subsystem's real task/sequence names."""
from __future__ import annotations

import pytest

from dv_harness.subsystem_adapter_ir import (
    LOGICAL_OPERATIONS,
    STATUS_RESOLVED,
    STATUS_UNSUPPORTED_OPERATION,
    SubsystemAdapterIR,
    SubsystemAdapterIRError,
    assert_logical_operations_fixed,
    build_subsystem_adapter_ir,
)


# ---------------------------------------------------------------------------
# Fixed-vocabulary sanity
# ---------------------------------------------------------------------------


def test_fixed_vocabulary_is_exactly_the_eight_named_operations():
    assert LOGICAL_OPERATIONS == (
        "configure",
        "start",
        "stop",
        "reset",
        "wait_ready",
        "execute",
        "monitor",
        "get_status",
    )


def test_assert_logical_operations_fixed_passes_on_the_real_module_state():
    # Should not raise against the module's own real, unmodified vocabulary.
    assert_logical_operations_fixed()


def test_assert_logical_operations_fixed_detects_drift(monkeypatch):
    import dv_harness.subsystem_adapter_ir as mod

    monkeypatch.setattr(mod, "LOGICAL_OPERATIONS", ("configure", "start"))
    with pytest.raises(AssertionError):
        mod.assert_logical_operations_fixed()


def test_assert_logical_operations_fixed_detects_duplicate(monkeypatch):
    import dv_harness.subsystem_adapter_ir as mod

    monkeypatch.setattr(
        mod,
        "LOGICAL_OPERATIONS",
        ("configure", "start", "start", "reset", "wait_ready", "execute", "monitor", "get_status"),
    )
    with pytest.raises(AssertionError):
        mod.assert_logical_operations_fixed()


# ---------------------------------------------------------------------------
# Core positive path: full real mapping resolves every operation
# ---------------------------------------------------------------------------


def _full_real_mapping():
    return [
        {"operation": "configure", "existing_task_or_sequence_name": "usb_cfg_task"},
        {"operation": "start", "existing_task_or_sequence_name": "usb_start_seq"},
        {"operation": "stop", "existing_task_or_sequence_name": "usb_stop_seq"},
        {"operation": "reset", "existing_task_or_sequence_name": "usb_soft_reset_task"},
        {"operation": "wait_ready", "existing_task_or_sequence_name": "usb_wait_link_up_task"},
        {"operation": "execute", "existing_task_or_sequence_name": "usb_run_transfer_seq"},
        {"operation": "monitor", "existing_task_or_sequence_name": "usb_monitor_seq"},
        {"operation": "get_status", "existing_task_or_sequence_name": "usb_read_status_task"},
    ]


def test_full_real_mapping_resolves_every_fixed_operation():
    ir = build_subsystem_adapter_ir(_full_real_mapping(), subsystem_name="usb31_dev")

    assert isinstance(ir, SubsystemAdapterIR)
    assert ir.subsystem_name == "usb31_dev"
    assert ir.resolved_operations() == LOGICAL_OPERATIONS
    assert ir.unsupported_operations() == ()
    assert ir.unrecognized_mappings == ()

    for op, expected_name in zip(
        LOGICAL_OPERATIONS,
        [
            "usb_cfg_task",
            "usb_start_seq",
            "usb_stop_seq",
            "usb_soft_reset_task",
            "usb_wait_link_up_task",
            "usb_run_transfer_seq",
            "usb_monitor_seq",
            "usb_read_status_task",
        ],
    ):
        res = ir.resolve(op)
        assert res.status == STATUS_RESOLVED
        assert res.resolved_task_or_sequence_name == expected_name
        assert ir.is_supported(op) is True


def test_to_dict_shape_is_stable_and_complete():
    ir = build_subsystem_adapter_ir(_full_real_mapping(), subsystem_name="usb31_dev")
    d = ir.to_dict()
    assert d["subsystem_name"] == "usb31_dev"
    assert set(d["operations"].keys()) == set(LOGICAL_OPERATIONS)
    assert d["resolved_operations"] == list(LOGICAL_OPERATIONS)
    assert d["unsupported_operations"] == []
    assert d["unrecognized_mappings"] == []


# ---------------------------------------------------------------------------
# Partial mapping: an operation with no real mapped task -> UNSUPPORTED_OPERATION,
# never a synthesized stub.
# ---------------------------------------------------------------------------


def test_operation_never_mentioned_reports_unsupported_never_a_stub():
    entries = [
        {"operation": "configure", "existing_task_or_sequence_name": "usb_cfg_task"},
        {"operation": "start", "existing_task_or_sequence_name": "usb_start_seq"},
        # stop/reset/wait_ready/execute/monitor/get_status never mentioned at all.
    ]
    ir = build_subsystem_adapter_ir(entries)

    assert ir.resolved_operations() == ("configure", "start")
    assert ir.unsupported_operations() == (
        "stop",
        "reset",
        "wait_ready",
        "execute",
        "monitor",
        "get_status",
    )
    for op in ir.unsupported_operations():
        res = ir.resolve(op)
        assert res.status == STATUS_UNSUPPORTED_OPERATION
        assert res.resolved_task_or_sequence_name is None
        assert "no mapping was supplied" in res.reason
        assert ir.is_supported(op) is False


def test_operation_declared_with_empty_name_reports_unsupported_not_stubbed():
    entries = [
        {"operation": "configure", "existing_task_or_sequence_name": "usb_cfg_task"},
        {"operation": "reset", "existing_task_or_sequence_name": ""},
        {"operation": "monitor", "existing_task_or_sequence_name": "   "},
    ]
    ir = build_subsystem_adapter_ir(entries)

    assert ir.resolve("configure").status == STATUS_RESOLVED

    for op in ("reset", "monitor"):
        res = ir.resolve(op)
        assert res.status == STATUS_UNSUPPORTED_OPERATION
        assert res.resolved_task_or_sequence_name is None
        assert "supplied no real" in res.reason

    # Untouched operations are unsupported for the ordinary "never mentioned" reason.
    assert "no mapping was supplied" in ir.resolve("start").reason


def test_mapped_name_is_trimmed_but_never_otherwise_rewritten():
    entries = [
        {"operation": "start", "existing_task_or_sequence_name": "  usb_start_seq  "},
    ]
    ir = build_subsystem_adapter_ir(entries)
    assert ir.resolve("start").resolved_task_or_sequence_name == "usb_start_seq"


def test_empty_mapping_list_reports_every_operation_unsupported():
    ir = build_subsystem_adapter_ir([])
    assert ir.resolved_operations() == ()
    assert ir.unsupported_operations() == LOGICAL_OPERATIONS
    assert ir.unrecognized_mappings == ()


# ---------------------------------------------------------------------------
# Unrecognized operation names: reported, never silently dropped, never
# resolving a real fixed-vocabulary operation.
# ---------------------------------------------------------------------------


def test_operation_outside_fixed_vocabulary_is_reported_not_dropped():
    entries = [
        {"operation": "start", "existing_task_or_sequence_name": "usb_start_seq"},
        {"operation": "calibrate_phy", "existing_task_or_sequence_name": "usb_phy_cal_task"},
    ]
    ir = build_subsystem_adapter_ir(entries)

    assert ir.resolve("start").status == STATUS_RESOLVED
    assert len(ir.unrecognized_mappings) == 1
    entry = ir.unrecognized_mappings[0]
    assert entry["operation"] == "calibrate_phy"
    assert entry["existing_task_or_sequence_name"] == "usb_phy_cal_task"
    assert "not part of this module's fixed logical-operation vocabulary" in entry["reason"]

    # It must never have been silently treated as one of the real 8.
    for op in LOGICAL_OPERATIONS:
        if op != "start":
            assert ir.resolve(op).status == STATUS_UNSUPPORTED_OPERATION


# ---------------------------------------------------------------------------
# resolve()/is_supported() reject a request outside the fixed vocabulary.
# ---------------------------------------------------------------------------


def test_resolve_rejects_unknown_operation_name():
    ir = build_subsystem_adapter_ir(_full_real_mapping())
    with pytest.raises(SubsystemAdapterIRError) as exc_info:
        ir.resolve("teardown")
    assert exc_info.value.code == "UNKNOWN_LOGICAL_OPERATION"


def test_is_supported_rejects_unknown_operation_name():
    ir = build_subsystem_adapter_ir(_full_real_mapping())
    with pytest.raises(SubsystemAdapterIRError):
        ir.is_supported("teardown")


# ---------------------------------------------------------------------------
# Negative controls: malformed / ambiguous input is a hard error, never
# silently repaired or defaulted.
# ---------------------------------------------------------------------------


def test_mapping_entries_must_be_a_sequence():
    with pytest.raises(SubsystemAdapterIRError) as exc_info:
        build_subsystem_adapter_ir({"operation": "start", "existing_task_or_sequence_name": "x"})
    assert exc_info.value.code == "MAPPING_ENTRIES_NOT_A_SEQUENCE"


def test_entry_missing_operation_key_is_a_hard_error():
    with pytest.raises(SubsystemAdapterIRError) as exc_info:
        build_subsystem_adapter_ir([{"existing_task_or_sequence_name": "usb_start_seq"}])
    assert exc_info.value.code == "MAPPING_ENTRY_MISSING_OPERATION"


def test_entry_with_blank_operation_is_a_hard_error():
    with pytest.raises(SubsystemAdapterIRError) as exc_info:
        build_subsystem_adapter_ir(
            [{"operation": "   ", "existing_task_or_sequence_name": "usb_start_seq"}]
        )
    assert exc_info.value.code == "MAPPING_ENTRY_MISSING_OPERATION"


def test_entry_missing_task_name_key_entirely_is_a_hard_error():
    # Distinct from supplying an empty string value, which is a legitimate
    # "explicitly unmapped" declaration handled elsewhere.
    with pytest.raises(SubsystemAdapterIRError) as exc_info:
        build_subsystem_adapter_ir([{"operation": "start"}])
    assert exc_info.value.code == "MAPPING_ENTRY_MISSING_TASK_NAME"


def test_duplicate_operation_mapping_is_a_hard_error_not_last_one_wins():
    entries = [
        {"operation": "start", "existing_task_or_sequence_name": "usb_start_seq_v1"},
        {"operation": "start", "existing_task_or_sequence_name": "usb_start_seq_v2"},
    ]
    with pytest.raises(SubsystemAdapterIRError) as exc_info:
        build_subsystem_adapter_ir(entries)
    assert exc_info.value.code == "DUPLICATE_OPERATION_MAPPING"
    assert exc_info.value.detail["operation"] == "start"


def test_entry_that_is_not_mapping_shaped_is_a_hard_error():
    with pytest.raises(SubsystemAdapterIRError) as exc_info:
        build_subsystem_adapter_ir(["start"])
    assert exc_info.value.code == "MAPPING_ENTRY_NOT_MAPPING_SHAPED"


# ---------------------------------------------------------------------------
# Duck-typed input: works over a plain dict-like object with .get(), not only
# a literal dict.
# ---------------------------------------------------------------------------


class _DuckMapping:
    """A minimal duck-typed stand-in for a caller's own mapping-record class,
    exposing only `.get()` -- never a dict subclass and never a
    `collections.abc.Mapping` registrant."""

    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


def test_duck_typed_entry_objects_are_accepted():
    entries = [
        _DuckMapping({"operation": "get_status", "existing_task_or_sequence_name": "usb_read_status_task"}),
    ]
    ir = build_subsystem_adapter_ir(entries)
    res = ir.resolve("get_status")
    assert res.status == STATUS_RESOLVED
    assert res.resolved_task_or_sequence_name == "usb_read_status_task"
