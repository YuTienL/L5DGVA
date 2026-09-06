"""Tests for dv_harness/amba_command_txt_extension.py -- AMBA-specific
semantic compilation (master / region / operation / parallel-group) of a DE
command.txt command.

Every command record here is a hand-built dict standing in for what a
generic command.txt parser (e.g. this session's `de_command_style_learning`)
would emit -- there is no import of that module, or of `pattern_ir_assembly`,
anywhere in this file. The synthetic `CPUWRITE4B(addr, data)` / `CPUREAD4B`
macro shape mirrors the REAL naming convention observed (read-only) in
`ATB/soc/bench/command.txt` and `ATB/coretop/tests/command.txt`, but no text
is copied from those files -- only the naming convention is reused, the way
`de_command_style_learning.py`'s own test fixtures already do for the same
convention.
"""
from __future__ import annotations

import subprocess
import sys

from dv_harness import amba_command_txt_extension as ace


MASTER_REGISTRY = {"CPU": "CPU", "DMA": "DMA"}
REGION_MAP = [
    {"name": "REGION_A", "start": "32'h0000_0000", "end": "32'h0000_FFFF"},
    {"name": "REGION_B", "start": "32'h0002_0000", "size": "32'h0000_1000"},
]


def _rec(text, **extra):
    row = {"raw_text": text}
    row.update(extra)
    return row


# -- vocabulary hygiene -------------------------------------------------------

def test_vocabulary_does_not_collide_with_models_status():
    ace.assert_no_verification_verdict_vocabulary()


def test_status_vocabularies_are_exactly_as_documented():
    assert ace.OPERATION_STATUSES == {
        "WRITE", "READ", "OTHER_RECOGNIZED_MACRO", "NOT_APPLICABLE",
        "OPERATION_UNKNOWN",
    }
    assert ace.MASTER_STATUSES == {
        "MASTER_RESOLVED", "MASTER_UNKNOWN_NO_TOKEN",
        "MASTER_UNKNOWN_NO_REGISTRY_SUPPLIED", "MASTER_UNKNOWN_NOT_IN_REGISTRY",
    }
    assert ace.REGION_STATUSES == {
        "REGION_RESOLVED", "REGION_UNKNOWN_NO_ADDRESS",
        "REGION_UNKNOWN_NO_MAP_SUPPLIED", "REGION_UNKNOWN_NOT_IN_MAP",
        "REGION_AMBIGUOUS_MULTIPLE_MATCH",
    }


# -- core positive path --------------------------------------------------------

def test_resolves_master_region_and_operation_for_a_known_write():
    records = [_rec("`CPUWRITE4B(32'h0002_0100, 32'h0000_0007);")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.operation == ace.OP_WRITE
    assert e.master == "CPU"
    assert e.master_status == ace.MASTER_RESOLVED
    assert e.address == 0x0002_0100
    assert e.region == "REGION_B"
    assert e.region_status == ace.REGION_RESOLVED
    assert e.parallel_group is None
    assert e.parallel_group_status == ace.PARALLEL_GROUP_NONE


def test_resolves_read_and_a_different_region():
    records = [_rec("`CPUREAD4B(32'h0000_0010, i);")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.operation == ace.OP_READ
    assert e.region == "REGION_A"


def test_parallel_group_membership_inside_fork_join():
    records = [
        _rec("fork"),
        _rec("`CPUWRITE4B(32'h0002_0100, 32'h1);"),
        _rec("`DMAWRITE4B(32'h0002_0104, 32'h2);"),
        _rec("join"),
        _rec("`CPUWRITE4B(32'h0002_0108, 32'h3);"),
    ]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    fork_line, cpu_in, dma_in, join_line, cpu_after = report.entries
    assert fork_line.parallel_group_status == ace.PARALLEL_GROUP_NONE
    assert cpu_in.parallel_group == "GROUP_1"
    assert cpu_in.parallel_group_status == ace.PARALLEL_GROUP_MEMBER
    assert dma_in.parallel_group == "GROUP_1"
    assert join_line.parallel_group == "GROUP_1"  # join itself still inside, closes after
    assert cpu_after.parallel_group is None
    assert cpu_after.parallel_group_status == ace.PARALLEL_GROUP_NONE
    assert report.warnings == []


# -- negative controls ---------------------------------------------------------

def test_unknown_master_when_no_registry_supplied():
    records = [_rec("`CPUWRITE4B(32'h0002_0100, 32'h1);")]
    report = ace.compile_command_txt_extension(records, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.master is None
    assert e.master_status == ace.MASTER_UNKNOWN_NO_REGISTRY_SUPPLIED


def test_unknown_master_when_token_not_in_registry():
    records = [_rec("`GPUWRITE4B(32'h0002_0100, 32'h1);")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.master is None
    assert e.master_status == ace.MASTER_UNKNOWN_NOT_IN_REGISTRY


def test_unknown_master_when_no_token_extractable_at_all():
    records = [_rec("`GLOBAL_INIT();")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.master is None
    assert e.master_status == ace.MASTER_UNKNOWN_NO_TOKEN
    assert e.operation == ace.OP_OTHER


def test_unknown_region_when_address_outside_every_configured_region():
    records = [_rec("`CPUWRITE4B(32'hFFFF_0000, 32'h1);")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.address == 0xFFFF_0000
    assert e.region is None
    assert e.region_status == ace.REGION_UNKNOWN_NOT_IN_MAP


def test_unknown_region_when_no_map_supplied():
    records = [_rec("`CPUWRITE4B(32'h0002_0100, 32'h1);")]
    report = ace.compile_command_txt_extension(records, master_registry=MASTER_REGISTRY)
    e = report.entries[0]
    assert e.region_status == ace.REGION_UNKNOWN_NO_MAP_SUPPLIED


def test_region_ambiguous_when_two_regions_overlap_the_same_address():
    overlapping = [
        {"name": "REGION_X", "start": "32'h0000_0000", "end": "32'h0000_FFFF"},
        {"name": "REGION_Y", "start": "32'h0000_0100", "end": "32'h0000_2000"},
    ]
    records = [_rec("`CPUWRITE4B(32'h0000_0200, 32'h1);")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=overlapping)
    e = report.entries[0]
    assert e.region is None
    assert e.region_status == ace.REGION_AMBIGUOUS_MULTIPLE_MATCH


def test_operation_not_applicable_for_a_structural_line_and_no_address():
    records = [_rec("#100; //Wait Token change")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.operation == ace.OP_NOT_APPLICABLE
    assert e.region_status == ace.REGION_UNKNOWN_NO_ADDRESS


def test_operation_unknown_for_an_unrecognizable_line():
    records = [_rec("some_random_free_text_with_no_call_or_keyword")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.operation == ace.OP_UNKNOWN


def test_address_with_dont_care_bits_is_not_resolved():
    records = [_rec("`CPUWRITE4B(32'h0002_01xx, 32'h1);")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.address is None
    assert e.region_status == ace.REGION_UNKNOWN_NO_ADDRESS


def test_unbalanced_join_is_reported_as_a_warning_not_a_crash():
    records = [_rec("join"), _rec("`CPUWRITE4B(32'h0002_0100, 32'h1);")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    assert any("no open fork" in w for w in report.warnings)
    assert report.entries[1].parallel_group is None


def test_unclosed_fork_at_end_of_records_is_reported_as_a_warning():
    records = [_rec("fork"), _rec("`CPUWRITE4B(32'h0002_0100, 32'h1);")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    assert any("unclosed" in w for w in report.warnings)


def test_explicit_master_and_operation_fields_take_precedence_over_text():
    records = [_rec("some ambiguous free text", master="DMA", operation="READ",
                     address="32'h0000_0010")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    e = report.entries[0]
    assert e.master == "DMA"
    assert e.operation == ace.OP_READ
    assert e.region == "REGION_A"


def test_malformed_region_map_entry_is_skipped_with_a_warning_not_silently_dropped():
    bad_map = [{"name": "NO_START"}, {"name": "OK", "start": "32'h0", "end": "32'hFF"}]
    records = [_rec("`CPUWRITE4B(32'h0000_0010, 32'h1);")]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=bad_map)
    assert any("NO_START" in w for w in report.warnings)
    assert report.entries[0].region == "OK"


def test_records_not_a_sequence_raises():
    import pytest
    with pytest.raises(ace.AmbaCommandTxtExtensionError):
        ace.compile_command_txt_extension(object(), master_registry=MASTER_REGISTRY)


def test_report_to_dict_and_render_markdown_do_not_crash_and_summarize_counts():
    records = [
        _rec("`CPUWRITE4B(32'h0002_0100, 32'h1);"),
        _rec("`CPUREAD4B(32'h0000_0010, i);"),
    ]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    as_dict = report.to_dict()
    assert as_dict["summary"]["operation"] == {"WRITE": 1, "READ": 1}
    md = report.render_markdown()
    assert "REGION_B" in md
    assert "REGION_A" in md


def test_reorders_records_by_explicit_line_no_when_every_record_has_one():
    records = [
        _rec("`CPUREAD4B(32'h0000_0010, i);", line_no=2),
        _rec("`CPUWRITE4B(32'h0002_0100, 32'h1);", line_no=1),
    ]
    report = ace.compile_command_txt_extension(
        records, master_registry=MASTER_REGISTRY, region_map=REGION_MAP)
    assert report.entries[0].operation == ace.OP_WRITE
    assert report.entries[1].operation == ace.OP_READ


def test_module_importable_as_a_script_module_via_subprocess():
    result = subprocess.run(
        [sys.executable, "-c", "from dv_harness import amba_command_txt_extension"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
