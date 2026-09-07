"""Tests for dv_harness/integration_adapter_gen.py -- generating adapter glue
code from an already-resolved SubsystemAdapterIR mapping."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.integration_adapter_gen import (
    AdapterGlueOperationRecord,
    IntegrationAdapterGenError,
    assert_resolved_name_is_callable_identifier,
    build_adapter_glue_records,
    build_and_generate_adapter_glue,
    execute_verb,
    facade_macro_name,
    generate_adapter_glue_svh,
    unsupported_operation_task_name,
    write_adapter_glue_svh,
)
from dv_harness.subsystem_adapter_ir import (
    LOGICAL_OPERATIONS,
    SubsystemAdapterIRError,
    build_subsystem_adapter_ir,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


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


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------


def test_facade_macro_name_is_deterministic_from_operation_alone():
    assert facade_macro_name("configure") == "DV_ADAPTER_CONFIGURE"
    assert facade_macro_name("wait_ready") == "DV_ADAPTER_WAIT_READY"


def test_unsupported_operation_task_name_uses_real_subsystem_and_operation_only():
    assert (
        unsupported_operation_task_name("usb31_dev", "stop")
        == "dv_adapter_unsupported_operation_usb31_dev_stop"
    )
    # No subsystem name supplied -> still deterministic, never invented.
    assert (
        unsupported_operation_task_name(None, "stop")
        == "dv_adapter_unsupported_operation_stop"
    )


def test_assert_resolved_name_accepts_simple_and_dotted_identifiers():
    assert_resolved_name_is_callable_identifier("start", "usb_start_seq")
    assert_resolved_name_is_callable_identifier("execute", "env.vseqr.start_seq")


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        None,
        "usb start seq",  # whitespace
        "usb-start-seq",  # illegal punctuation
        "env..vseqr",  # empty dotted segment
        ".leading_dot",
        "trailing_dot.",
    ],
)
def test_assert_resolved_name_rejects_implausible_sv_callables(bad_name):
    with pytest.raises(IntegrationAdapterGenError):
        assert_resolved_name_is_callable_identifier("start", bad_name)


# ---------------------------------------------------------------------------
# build_adapter_glue_records: core positive path
# ---------------------------------------------------------------------------


def test_records_built_from_a_real_ir_requires_the_real_ir_type():
    with pytest.raises(IntegrationAdapterGenError) as exc_info:
        build_adapter_glue_records({"not": "a real IR"})
    assert exc_info.value.code == "NOT_A_SUBSYSTEM_ADAPTER_IR"


def test_full_mapping_yields_one_resolved_record_per_operation_verbatim():
    ir = build_subsystem_adapter_ir(_full_real_mapping(), subsystem_name="usb31_dev")
    records = build_adapter_glue_records(ir)

    assert [r.operation for r in records] == list(LOGICAL_OPERATIONS)
    assert all(isinstance(r, AdapterGlueOperationRecord) for r in records)
    assert all(not r.generated_stub for r in records)

    by_op = {r.operation: r for r in records}
    assert by_op["configure"].forwards_to == "usb_cfg_task"
    assert by_op["start"].forwards_to == "usb_start_seq"
    assert by_op["get_status"].forwards_to == "usb_read_status_task"
    for r in records:
        assert r.macro_name == facade_macro_name(r.operation)


# ---------------------------------------------------------------------------
# Partial mapping: unsupported operations get an honest failure stub, never
# a fabricated call.
# ---------------------------------------------------------------------------


def _partial_mapping():
    return [
        {"operation": "configure", "existing_task_or_sequence_name": "usb_cfg_task"},
        {"operation": "start", "existing_task_or_sequence_name": "usb_start_seq"},
        # stop/reset/wait_ready/execute/monitor/get_status never mentioned.
    ]


def test_unsupported_operations_forward_to_a_deterministic_honest_stub_never_a_guess():
    ir = build_subsystem_adapter_ir(_partial_mapping(), subsystem_name="usb31_dev")
    records = build_adapter_glue_records(ir)
    by_op = {r.operation: r for r in records}

    for op in ("configure", "start"):
        assert by_op[op].generated_stub is False

    for op in ("stop", "reset", "wait_ready", "execute", "monitor", "get_status"):
        rec = by_op[op]
        assert rec.generated_stub is True
        assert rec.forwards_to == unsupported_operation_task_name("usb31_dev", op)
        # The honest reason is the IR's own real reason text, never invented here.
        assert "no mapping was supplied" in rec.reason


def test_operation_declared_with_empty_name_also_gets_an_honest_stub():
    entries = [
        {"operation": "configure", "existing_task_or_sequence_name": "usb_cfg_task"},
        {"operation": "reset", "existing_task_or_sequence_name": "   "},
    ]
    ir = build_subsystem_adapter_ir(entries, subsystem_name="usb31_dev")
    records = build_adapter_glue_records(ir)
    reset_rec = next(r for r in records if r.operation == "reset")
    assert reset_rec.generated_stub is True
    assert "supplied no real" in reset_rec.reason


# ---------------------------------------------------------------------------
# SV emission: content shape, and the negative control this project's house
# style specifically requires -- unsupported operations never produce a
# fabricated call, only a cited, traceable failure task.
# ---------------------------------------------------------------------------


def test_generated_svh_for_full_mapping_forwards_every_macro_to_the_real_name():
    ir = build_subsystem_adapter_ir(_full_real_mapping(), subsystem_name="usb31_dev")
    svh = generate_adapter_glue_svh(ir)

    assert "GENERATED by dv_harness/integration_adapter_gen.py" in svh
    assert "`ifndef DV_ADAPTER_USB31_DEV_SVH" in svh
    assert "`endif" in svh
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
        assert f"`define {facade_macro_name(op)} {expected_name}" in svh
    # No unsupported-operation failure tasks are emitted when everything resolved.
    assert "uvm_fatal" not in svh
    assert "dv_adapter_unsupported_operation" not in svh


def test_negative_control_unsupported_operation_never_produces_a_fabricated_call():
    """The house-style-mandated negative control: prove the generator
    REFUSES to fabricate an answer when evidence (a real mapped task name)
    is absent. The generated glue must forward an unsupported operation's
    macro to its own honest, deterministic failure task -- and that task's
    body must cite the real reason and raise `uvm_fatal`, never silently
    calling some plausible-sounding invented name."""
    ir = build_subsystem_adapter_ir(_partial_mapping(), subsystem_name="usb31_dev")
    svh = generate_adapter_glue_svh(ir)

    for op in ("stop", "reset", "wait_ready", "execute", "monitor", "get_status"):
        stub = unsupported_operation_task_name("usb31_dev", op)
        macro = facade_macro_name(op)
        assert f"`define {macro} {stub}" in svh
        assert f"task {stub}();" in svh
        assert "endtask" in svh

    # There is no world in which this file invents a plausible task name
    # (e.g. "usb_stop_seq") for an operation nobody mapped.
    assert "usb_stop_seq" not in svh
    assert "usb_soft_reset_task" not in svh
    assert "usb_wait_link_up_task" not in svh
    assert "usb_run_transfer_seq" not in svh
    assert "usb_monitor_seq" not in svh
    assert "usb_read_status_task" not in svh

    # Every failure task really raises, citing DV_ADAPTER_UNSUPPORTED_OPERATION.
    assert svh.count("`uvm_fatal(\"DV_ADAPTER_UNSUPPORTED_OPERATION\"") == 6
    assert "no mapping was supplied" in svh


def test_resolved_operations_and_unsupported_operations_coexist_correctly():
    ir = build_subsystem_adapter_ir(_partial_mapping(), subsystem_name="usb31_dev")
    svh = generate_adapter_glue_svh(ir)
    # Resolved ones forward to the real name...
    assert f"`define {facade_macro_name('configure')} usb_cfg_task" in svh
    assert f"`define {facade_macro_name('start')} usb_start_seq" in svh
    # ...and are never accompanied by a spurious failure task of their own.
    assert "dv_adapter_unsupported_operation_usb31_dev_configure" not in svh
    assert "dv_adapter_unsupported_operation_usb31_dev_start" not in svh


def test_empty_mapping_generates_six_honest_failure_stubs_and_two_resolved_are_absent():
    ir = build_subsystem_adapter_ir([])
    svh = generate_adapter_glue_svh(ir)
    for op in LOGICAL_OPERATIONS:
        stub = unsupported_operation_task_name(None, op)
        assert f"task {stub}();" in svh
    assert svh.count("`uvm_fatal(") == len(LOGICAL_OPERATIONS)


def test_generated_svh_names_are_syntactically_stable_regardless_of_subsystem_name():
    ir_unnamed = build_subsystem_adapter_ir([])
    svh = generate_adapter_glue_svh(ir_unnamed)
    assert "`ifndef DV_ADAPTER_UNNAMED_SVH" in svh
    assert "Subsystem: UNNAMED_SUBSYSTEM" in svh


def test_generation_refuses_an_implausible_resolved_name():
    entries = [{"operation": "start", "existing_task_or_sequence_name": "usb start seq"}]
    ir = build_subsystem_adapter_ir(entries)
    with pytest.raises(IntegrationAdapterGenError) as exc_info:
        generate_adapter_glue_svh(ir)
    assert exc_info.value.code == "RESOLVED_NAME_NOT_A_VALID_SV_IDENTIFIER"


# ---------------------------------------------------------------------------
# write_adapter_glue_svh: real file I/O
# ---------------------------------------------------------------------------


def test_write_adapter_glue_svh_writes_the_generated_text_to_disk(tmp_path):
    ir = build_subsystem_adapter_ir(_full_real_mapping(), subsystem_name="usb31_dev")
    out_path = tmp_path / "generated" / "usb31_dev_adapter.svh"
    written = write_adapter_glue_svh(ir, out_path)
    assert Path(written) == out_path
    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == generate_adapter_glue_svh(ir)


# ---------------------------------------------------------------------------
# End-to-end: mapping entries -> resolution (untouched module) -> glue
# ---------------------------------------------------------------------------


def test_build_and_generate_end_to_end_from_raw_mapping_entries(tmp_path):
    out_path = tmp_path / "adapter.svh"
    result = build_and_generate_adapter_glue(
        _full_real_mapping(), subsystem_name="usb31_dev", out_path=out_path
    )
    assert result["ir"]["subsystem_name"] == "usb31_dev"
    assert len(result["operations"]) == len(LOGICAL_OPERATIONS)
    assert result["written_to"] == str(out_path)
    assert out_path.read_text(encoding="utf-8") == result["svh"]


def test_end_to_end_propagates_real_resolution_errors_unmodified():
    # A duplicate operation mapping is a hard SubsystemAdapterIRError from
    # the untouched resolution module -- this generator must never swallow
    # or reinterpret it.
    entries = [
        {"operation": "start", "existing_task_or_sequence_name": "usb_start_seq_v1"},
        {"operation": "start", "existing_task_or_sequence_name": "usb_start_seq_v2"},
    ]
    with pytest.raises(SubsystemAdapterIRError) as exc_info:
        build_and_generate_adapter_glue(entries)
    assert exc_info.value.code == "DUPLICATE_OPERATION_MAPPING"


def test_no_out_path_means_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = build_and_generate_adapter_glue(_full_real_mapping(), subsystem_name="usb31_dev")
    assert "written_to" not in result
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# CLI: execute_verb() and the real `python -m` subprocess entry point.
# ---------------------------------------------------------------------------


def test_execute_verb_reports_every_operation_and_exits_zero(tmp_path):
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(
        json.dumps(
            {"subsystem_name": "usb31_dev", "mapping_entries": _full_real_mapping()}
        ),
        encoding="utf-8",
    )
    text, code = execute_verb(str(mapping_file))
    assert code == 0
    assert "subsystem: usb31_dev" in text
    assert "configure" in text


def test_execute_verb_writes_out_file_when_requested(tmp_path):
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps(_full_real_mapping()), encoding="utf-8")
    out_path = tmp_path / "out.svh"
    text, code = execute_verb(str(mapping_file), subsystem_name="usb31_dev", out_path=str(out_path))
    assert code == 0
    assert out_path.exists()
    assert "written:" in text


def test_execute_verb_reports_a_resolution_error_as_exit_one(tmp_path):
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(
        json.dumps([{"operation": "start"}]),  # missing task-name key -> hard error
        encoding="utf-8",
    )
    text, code = execute_verb(str(mapping_file))
    assert code == 1
    assert "MAPPING_ENTRY_MISSING_TASK_NAME" in text


def test_execute_verb_reports_a_usage_error_for_bad_json(tmp_path):
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text("{not valid json", encoding="utf-8")
    text, code = execute_verb(str(mapping_file))
    assert code == 2


def test_execute_verb_reports_a_usage_error_for_missing_file(tmp_path):
    text, code = execute_verb(str(tmp_path / "does_not_exist.json"))
    assert code == 2


def test_real_cli_subprocess_generates_and_writes(tmp_path):
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(
        json.dumps(
            {"subsystem_name": "usb31_dev", "mapping_entries": _full_real_mapping()}
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "usb31_dev_adapter.svh"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dv_harness.integration_adapter_gen",
            str(mapping_file),
            "--out",
            str(out_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert out_path.exists()
    assert "DV_ADAPTER_CONFIGURE usb_cfg_task" in out_path.read_text(encoding="utf-8")
