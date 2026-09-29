"""Tests for dv_harness/intake_plain_summary.py -- the plain-language,
one-shot-confirmation renderer over intake_baseline.py's own
capture_intake_baseline()/freeze_intake_baseline() records.

Every record fed to the renderer is produced by the REAL, unmodified
intake_baseline.py functions -- never a hand-typed stand-in for its output
shape -- so a future change to that module's own field/detail shape would
break these tests rather than silently going unnoticed here.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import intake_baseline as ib  # noqa: E402
from dv_harness import intake_plain_summary as ips  # noqa: E402


def _complete_facts():
    """Every one of the twelve fields populated with a real, distinct
    value -- mirrors test_intake_baseline.py's own fixture so both suites
    exercise the identical real shape."""
    return {
        "dut_top_boundary": {"top_module": "usb3_link_top",
                             "boundary": "phy_serdes_if"},
        "dut_sha": {"rtl/usb3_link_ctrl.v": "a" * 32,
                    "rtl/usb3_phy_wrap.v": "b" * 32},
        "tb_sha": "c" * 40,
        "source_file_hashes": {"tb/usb3_env.sv": "hashme content one",
                               "tb/usb3_seq.sv": "hashme content two"},
        "vip_declaration": {"vip": "svt_usb3", "version": "R-2023.06"},
        "bind_topology_hash": "bind topology raw content",
        "reference_uvm_hash": "d" * 64,
        "de_command_txt_hash": "command.txt raw content here",
        "known_test_list": ["usb3_smoke_test", "usb3_link_train_test",
                            "usb3_lpm_test"],
        "unresolved_critical_unknowns_count": 2,
        "unresolved_conflicts_count": 0,
        "recorded_user_decisions_count": 5,
    }


def _empty_facts():
    return {}


class TestCategoryIntegrity:
    def test_field_categories_partition_intake_fields_exactly(self):
        grouped = set()
        for _label, names in ips.FIELD_CATEGORIES:
            grouped.update(names)
        assert grouped == set(ib.INTAKE_FIELDS)

    def test_every_intake_field_has_a_human_label(self):
        for name in ib.INTAKE_FIELDS:
            assert name in ips.FIELD_LABELS
            assert ips.FIELD_LABELS[name]

    def test_shape_classification_covers_every_real_captor(self):
        for name in ib.INTAKE_FIELDS:
            shape = ips._field_shape(name)
            assert shape != "unknown", f"{name} has no known captor shape"


class TestRenderFromRawCapture:
    def test_complete_capture_shows_every_field_captured_and_no_open_items(self):
        baseline = ib.capture_intake_baseline(_complete_facts())
        text = ips.render_intake_plain_summary(baseline)
        assert "12 of 12 facts captured, 0 not available" in text
        assert "No open items" in text
        assert "NOT been frozen yet" in text
        # Every real label appears somewhere.
        for label in ips.FIELD_LABELS.values():
            assert label in text

    def test_empty_capture_reports_every_field_honestly_not_available(self):
        baseline = ib.capture_intake_baseline(_empty_facts())
        text = ips.render_intake_plain_summary(baseline)
        assert "0 of 12 facts captured, 12 not available" in text
        assert "Open items needing your confirmation or correction" in text
        # Every field's own real NOT_AVAILABLE reason surfaces.
        assert "no value was supplied for this fact" in text
        assert "no count was supplied" in text
        # Never a fabricated positive claim over unresolved facts.
        assert "captured, 0 not available" not in text

    def test_captured_declared_fact_shows_the_real_value_never_a_placeholder(self):
        baseline = ib.capture_intake_baseline(_complete_facts())
        text = ips.render_intake_plain_summary(baseline)
        assert "usb3_link_top" in text
        assert "phy_serdes_if" in text

    def test_captured_hash_or_files_multi_file_shows_real_file_count(self):
        baseline = ib.capture_intake_baseline(_complete_facts())
        text = ips.render_intake_plain_summary(baseline)
        assert "2 file(s) hashed and combined into one digest" in text

    def test_captured_single_content_string_is_described_honestly(self):
        baseline = ib.capture_intake_baseline(_complete_facts())
        text = ips.render_intake_plain_summary(baseline)
        assert "a single piece of raw content was hashed" in text

    def test_captured_list_field_shows_real_count(self):
        baseline = ib.capture_intake_baseline(_complete_facts())
        text = ips.render_intake_plain_summary(baseline)
        assert "3 test name(s) recorded" in text

    def test_captured_count_field_shows_real_number(self):
        baseline = ib.capture_intake_baseline(_complete_facts())
        text = ips.render_intake_plain_summary(baseline)
        assert "Unresolved critical unknowns: 2" in text
        assert "Recorded user decisions: 5" in text

    def test_digest_is_shown_for_every_captured_field(self):
        baseline = ib.capture_intake_baseline(_complete_facts())
        text = ips.render_intake_plain_summary(baseline)
        assert text.count("[digest ") == 12

    def test_precomputed_hash_shape_is_described_honestly(self):
        facts = _complete_facts()
        facts["reference_uvm_hash"] = "e" * 40  # looks like a precomputed hex digest
        baseline = ib.capture_intake_baseline(facts)
        text = ips.render_intake_plain_summary(baseline)
        assert "an already-computed hash was accepted as-is" in text


class TestTruncationHonesty:
    def test_large_declared_value_is_reported_truncated_not_guessed(self):
        facts = _complete_facts()
        facts["vip_declaration"] = {"blob": "x" * 5000}
        baseline = ib.capture_intake_baseline(facts)
        text = ips.render_intake_plain_summary(baseline)
        assert "too large to show inline" in text
        assert "5000" in text or "characters)" in text

    def test_large_file_map_is_reported_truncated_not_guessed(self):
        facts = _complete_facts()
        facts["source_file_hashes"] = {
            f"tb/file_{i}.sv": ("h" * 60) for i in range(200)
        }
        baseline = ib.capture_intake_baseline(facts)
        text = ips.render_intake_plain_summary(baseline)
        assert "the file list itself is too large to show inline" in text

    def test_large_test_list_is_reported_truncated_not_guessed(self):
        facts = _complete_facts()
        facts["known_test_list"] = [f"usb3_generated_test_{i}" for i in range(300)]
        baseline = ib.capture_intake_baseline(facts)
        text = ips.render_intake_plain_summary(baseline)
        assert "list too large to show inline" in text


class TestRenderFromFreezeRecord:
    def test_frozen_record_shows_freeze_metadata(self, tmp_path):
        record = ib.freeze_intake_baseline(
            tmp_path, _complete_facts(), frozen_by="qa.engineer",
            note="reviewed against usb3 spec rev 4")
        text = ips.render_intake_plain_summary(record)
        assert "FROZEN as" in text
        assert record["freeze_id"] in text
        assert "qa.engineer" in text
        assert "reviewed against usb3 spec rev 4" in text
        assert "NOT been frozen" not in text

    def test_frozen_record_with_no_note_omits_note_text(self, tmp_path):
        record = ib.freeze_intake_baseline(
            tmp_path, _complete_facts(), frozen_by="qa.engineer")
        text = ips.render_intake_plain_summary(record)
        assert "Note:" not in text

    def test_partially_captured_freeze_still_lists_open_items(self, tmp_path):
        facts = _complete_facts()
        del facts["known_test_list"]
        record = ib.freeze_intake_baseline(tmp_path, facts, frozen_by="qa.engineer")
        text = ips.render_intake_plain_summary(record)
        assert "Known test list: NOT CAPTURED" in text
        assert "Open items needing your confirmation or correction" in text


class TestOpenFieldNames:
    def test_complete_capture_has_no_open_fields(self):
        baseline = ib.capture_intake_baseline(_complete_facts())
        assert ips.open_field_names(baseline) == []

    def test_empty_capture_lists_all_twelve_fields_in_canonical_order(self):
        baseline = ib.capture_intake_baseline(_empty_facts())
        assert ips.open_field_names(baseline) == list(ib.INTAKE_FIELDS)

    def test_partial_capture_lists_only_the_uncaptured_fields(self):
        facts = _complete_facts()
        del facts["dut_sha"]
        del facts["recorded_user_decisions_count"]
        baseline = ib.capture_intake_baseline(facts)
        assert ips.open_field_names(baseline) == ["dut_sha", "recorded_user_decisions_count"]


class TestMalformedRecordRefusal:
    def test_non_dict_record_is_refused(self):
        with pytest.raises(ips.IntakeSummaryError):
            ips.render_intake_plain_summary(["not", "a", "dict"])

    def test_dict_with_no_fields_key_is_refused(self):
        with pytest.raises(ips.IntakeSummaryError):
            ips.render_intake_plain_summary({"unrelated": "shape"})

    def test_baseline_key_present_but_not_dict_shaped_is_refused(self):
        with pytest.raises(ips.IntakeSummaryError):
            ips.render_intake_plain_summary({"baseline": "not a dict"})

    def test_open_field_names_also_refuses_a_malformed_record(self):
        with pytest.raises(ips.IntakeSummaryError):
            ips.open_field_names({"nope": True})

    def test_missing_field_entry_renders_as_honest_malformed_open_item(self):
        baseline = ib.capture_intake_baseline(_complete_facts())
        del baseline["fields"]["dut_sha"]
        text = ips.render_intake_plain_summary(baseline)
        assert "DUT source SHA: NO DATA RECORDED FOR THIS FIELD (malformed record)" in text


class TestCLI:
    def _write_baseline(self, tmp_path, facts=None):
        baseline = ib.capture_intake_baseline(facts if facts is not None else _complete_facts())
        p = tmp_path / "baseline.json"
        p.write_text(json.dumps(baseline), encoding="utf-8")
        return p

    def test_execute_verb_complete_baseline_exits_zero(self, tmp_path):
        p = self._write_baseline(tmp_path)
        rc = ips.execute_verb(["render", "--file", str(p)])
        assert rc == 0

    def test_execute_verb_incomplete_baseline_exits_one(self, tmp_path):
        p = self._write_baseline(tmp_path, facts={})
        rc = ips.execute_verb(["render", "--file", str(p)])
        assert rc == 1

    def test_execute_verb_missing_file_exits_two(self, tmp_path):
        rc = ips.execute_verb(["render", "--file", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_execute_verb_malformed_json_exits_two(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        rc = ips.execute_verb(["render", "--file", str(p)])
        assert rc == 2

    def test_execute_verb_malformed_shape_exits_two(self, tmp_path):
        p = tmp_path / "weird.json"
        p.write_text(json.dumps({"unrelated": True}), encoding="utf-8")
        rc = ips.execute_verb(["render", "--file", str(p)])
        assert rc == 2

    def test_real_subprocess_round_trip(self, tmp_path):
        p = self._write_baseline(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.intake_plain_summary", "render",
             "--file", str(p)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        assert result.returncode == 0
        assert "12 of 12 facts captured" in result.stdout
