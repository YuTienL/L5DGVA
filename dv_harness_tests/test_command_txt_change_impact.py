"""Tests for dv_harness/command_txt_change_impact.py -- semantic diff between
two DECommandRegistryIR-shaped DE command registry snapshots (2026-09-06).

Every snapshot here is a plain dict/list built inline in the test, exactly
the duck-typed shape the module accepts -- there is no import of
`de_command_style_learning` anywhere in this file (a different, concurrently
running batch owns that module), and every record is a hand-built dict
standing in for what such a producer *would* emit, never a real command.txt
parse. The point under test is the CLASSIFIER's own logic over that shape,
not any particular producer.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from dv_harness import command_txt_change_impact as cti


# -- vocabulary hygiene -------------------------------------------------------

def test_vocabulary_does_not_collide_with_models_status_or_loop_budget_failuretype():
    cti.assert_no_verification_verdict_vocabulary()


def test_seven_statuses_are_exactly_the_ones_named_in_the_task():
    assert cti.COMMAND_DIFF_STATUSES == {
        "UNCHANGED", "ARGUMENT_CHANGE", "SEMANTIC_CHANGE", "NEW_COMMAND",
        "REMOVED_COMMAND", "DEPRECATED", "AMBIGUOUS",
    }


# -- helpers ------------------------------------------------------------------

def _entry(report, command_id):
    for e in report["entries"]:
        if e["command_id"] == command_id:
            return e
    raise AssertionError(f"no entry for {command_id!r} in report: {report['entries']}")


def _base_command(**overrides):
    rec = {
        "command_id": "usb_link_train",
        "protocol": "USB",
        "semantic_role": "branch_b",
        "handler": "usb_link_train_task",
        "vip_sequence": "usb_link_train_seq",
        "effects": "trains the link to the negotiated speed",
        "parameters": [
            {"name": "port", "type": "int", "default": "0", "required": True},
            {"name": "timeout_us", "type": "int", "default": "1000", "required": False},
        ],
        "source": "link/usb_link_train.txt",
    }
    rec.update(overrides)
    return rec


# -- core positive path: an identical snapshot is all UNCHANGED --------------

def test_identical_snapshots_are_all_unchanged():
    old = {"commands": [_base_command()]}
    new = {"commands": [_base_command()]}
    report = cti.diff_command_registries(old, new)
    assert report["summary"]["UNCHANGED"] == 1
    assert report["concerning_count"] == 0
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "UNCHANGED"
    assert e["old_present"] and e["new_present"]


# -- NEW_COMMAND / REMOVED_COMMAND -------------------------------------------

def test_new_command_and_removed_command():
    old = {"commands": [_base_command()]}
    new = {"commands": [_base_command(command_id="usb_link_train"),
                        _base_command(command_id="usb_link_recover",
                                      handler="usb_link_recover_task")]}
    report = cti.diff_command_registries(old, new)
    assert report["summary"]["NEW_COMMAND"] == 1
    assert _entry(report, "usb_link_recover")["verdict"] == "NEW_COMMAND"

    old2 = {"commands": [_base_command(), _base_command(command_id="usb_link_recover")]}
    new2 = {"commands": [_base_command()]}
    report2 = cti.diff_command_registries(old2, new2)
    assert report2["summary"]["REMOVED_COMMAND"] == 1
    assert _entry(report2, "usb_link_recover")["verdict"] == "REMOVED_COMMAND"
    assert report2["concerning_count"] == 1


def test_a_command_is_never_reported_as_a_guessed_rename():
    """A removed id and a differently-spelled new id must NEVER be linked --
    fabricating that linkage would be exactly the invented rename the
    Evidence Truth Rule forbids."""
    old = {"commands": [_base_command(command_id="usb_link_train_v1")]}
    new = {"commands": [_base_command(command_id="usb_link_train_v2")]}
    report = cti.diff_command_registries(old, new)
    assert _entry(report, "usb_link_train_v1")["verdict"] == "REMOVED_COMMAND"
    assert _entry(report, "usb_link_train_v2")["verdict"] == "NEW_COMMAND"
    assert report["summary"]["REMOVED_COMMAND"] == 1
    assert report["summary"]["NEW_COMMAND"] == 1


# -- ARGUMENT_CHANGE ----------------------------------------------------------

def test_parameter_added_is_argument_change_not_semantic_change():
    old = {"commands": [_base_command()]}
    new_params = [
        {"name": "port", "type": "int", "default": "0", "required": True},
        {"name": "timeout_us", "type": "int", "default": "1000", "required": False},
        {"name": "retries", "type": "int", "default": "3", "required": False},
    ]
    new = {"commands": [_base_command(parameters=new_params)]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "ARGUMENT_CHANGE"
    assert any("added at position 2" in f and "retries" in f for f in e["findings"])


def test_parameter_reordered_is_argument_change():
    old = {"commands": [_base_command()]}
    reordered = [
        {"name": "timeout_us", "type": "int", "default": "1000", "required": False},
        {"name": "port", "type": "int", "default": "0", "required": True},
    ]
    new = {"commands": [_base_command(parameters=reordered)]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "ARGUMENT_CHANGE"
    assert any("position 0" in f for f in e["findings"])
    assert any("position 1" in f for f in e["findings"])


def test_parameter_type_change_is_argument_change():
    old = {"commands": [_base_command()]}
    new_params = [
        {"name": "port", "type": "string", "default": "0", "required": True},
        {"name": "timeout_us", "type": "int", "default": "1000", "required": False},
    ]
    new = {"commands": [_base_command(parameters=new_params)]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "ARGUMENT_CHANGE"
    assert any("type" in f and "'int'" in f and "'string'" in f for f in e["findings"])


# -- SEMANTIC_CHANGE ----------------------------------------------------------

def test_handler_change_is_semantic_change():
    old = {"commands": [_base_command()]}
    new = {"commands": [_base_command(handler="usb_link_train_task_v2")]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "SEMANTIC_CHANGE"
    assert any("handler changed" in f for f in e["findings"])


def test_vip_sequence_change_is_semantic_change():
    old = {"commands": [_base_command()]}
    new = {"commands": [_base_command(vip_sequence="usb_link_train_seq_v2")]}
    report = cti.diff_command_registries(old, new)
    assert _entry(report, "usb_link_train")["verdict"] == "SEMANTIC_CHANGE"


def test_semantic_role_change_outranks_a_simultaneous_argument_change():
    """A command whose semantic role AND its parameter list both changed is
    SEMANTIC_CHANGE, not ARGUMENT_CHANGE -- the more consequential facet
    wins, and the argument diff still shows up in the findings."""
    old = {"commands": [_base_command()]}
    new_params = [
        {"name": "port", "type": "int", "default": "0", "required": True},
        {"name": "timeout_us", "type": "int", "default": "1000", "required": False},
        {"name": "extra", "type": "int", "default": "0", "required": False},
    ]
    new = {"commands": [_base_command(semantic_role="branch_a", parameters=new_params)]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "SEMANTIC_CHANGE"
    assert any("semantic_role changed" in f for f in e["findings"])
    assert any("added at position 2" in f for f in e["findings"])


def test_whitespace_only_effects_reformat_is_not_a_false_semantic_change():
    old = {"commands": [_base_command(effects="trains the link  to the\nnegotiated speed")]}
    new = {"commands": [_base_command(effects="trains the link to the negotiated speed")]}
    report = cti.diff_command_registries(old, new)
    assert _entry(report, "usb_link_train")["verdict"] == "UNCHANGED"


# -- DEPRECATED ---------------------------------------------------------------

def test_newly_deprecated_command():
    old = {"commands": [_base_command()]}
    new = {"commands": [_base_command(status="DEPRECATED")]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "DEPRECATED"
    assert any("newly marked deprecated" in f for f in e["findings"])


def test_deprecated_flag_true_also_triggers_deprecated():
    old = {"commands": [_base_command()]}
    new = {"commands": [_base_command(deprecated=True)]}
    report = cti.diff_command_registries(old, new)
    assert _entry(report, "usb_link_train")["verdict"] == "DEPRECATED"


def test_still_deprecated_in_both_stays_deprecated():
    old = {"commands": [_base_command(status="deprecated")]}
    new = {"commands": [_base_command(status="deprecated", handler="usb_link_train_task_v2")]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "DEPRECATED"
    assert any("remains marked deprecated" in f for f in e["findings"])
    # the underlying handler change is still visible in the findings
    assert any("handler changed" in f for f in e["findings"])


def test_reinstated_from_deprecated_is_semantic_change_not_deprecated():
    old = {"commands": [_base_command(status="deprecated")]}
    new = {"commands": [_base_command(status="active")]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "SEMANTIC_CHANGE"
    assert any("reinstated" in f for f in e["findings"])


# -- AMBIGUOUS: negative controls for honesty over guessing ------------------

def test_field_present_on_one_side_only_is_ambiguous_not_unchanged():
    old_rec = _base_command()
    del old_rec["handler"]
    old = {"commands": [old_rec]}
    new = {"commands": [_base_command()]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "AMBIGUOUS"
    assert any("handler" in f and "schema gap" in f for f in e["findings"])


def test_missing_parameters_field_on_one_side_is_ambiguous():
    old_rec = _base_command()
    del old_rec["parameters"]
    old = {"commands": [old_rec]}
    new = {"commands": [_base_command()]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "AMBIGUOUS"
    assert any("parameters" in f and "schema gap" in f for f in e["findings"])


def test_duplicate_command_id_in_one_snapshot_is_ambiguous():
    old = {"commands": [_base_command(), _base_command()]}
    new = {"commands": [_base_command()]}
    report = cti.diff_command_registries(old, new)
    e = _entry(report, "usb_link_train")
    assert e["verdict"] == "AMBIGUOUS"
    assert any("duplicate" in f for f in e["findings"])


def test_ambiguous_field_alongside_no_confirmed_diff_is_ambiguous_not_unchanged():
    """Every SEMANTIC/ARGUMENT facet agrees except one that this module could
    not even check on both sides -- the report must not claim UNCHANGED for
    something it never actually compared."""
    old_rec = _base_command()
    del old_rec["effects"]
    old = {"commands": [old_rec]}
    new = {"commands": [_base_command()]}
    report = cti.diff_command_registries(old, new)
    assert _entry(report, "usb_link_train")["verdict"] == "AMBIGUOUS"


# -- unindexable / malformed records, never silently dropped -----------------

def test_a_record_with_no_resolvable_id_is_reported_not_dropped():
    old = {"commands": [_base_command(), {"handler": "orphan_task", "no_id_field": True}]}
    new = {"commands": [_base_command()]}
    report = cti.diff_command_registries(old, new)
    assert report["old_command_count"] == 1
    assert len(report["old_unindexed_records"]) == 1
    assert "no command identifier resolvable" in report["old_unindexed_records"][0]["reason"]


def test_a_non_dict_record_in_the_list_is_reported_not_dropped():
    old = {"commands": [_base_command(), "not-a-dict"]}
    new = {"commands": [_base_command()]}
    report = cti.diff_command_registries(old, new)
    assert len(report["old_unindexed_records"]) == 1
    assert report["old_unindexed_records"][0]["reason"] == "record is not a dict"


def test_completely_unparseable_snapshot_raises_rather_than_reads_as_empty():
    with pytest.raises(cti.CommandTxtChangeImpactError):
        cti.diff_command_registries("not a registry at all", {"commands": []})
    with pytest.raises(cti.CommandTxtChangeImpactError):
        cti.diff_command_registries({"unrelated_key": 123}, {"commands": []})


def test_a_genuinely_empty_registry_is_not_an_error():
    report = cti.diff_command_registries({"commands": []}, {"commands": []})
    assert report["old_command_count"] == 0
    assert report["new_command_count"] == 0
    assert report["entries"] == []


# -- accepted container shapes ------------------------------------------------

def test_bare_list_snapshot_shape():
    old = [_base_command()]
    new = [_base_command(handler="usb_link_train_task_v2")]
    report = cti.diff_command_registries(old, new)
    assert _entry(report, "usb_link_train")["verdict"] == "SEMANTIC_CHANGE"


def test_id_to_record_mapping_snapshot_shape():
    rec = _base_command()
    del rec["command_id"]
    old = {"usb_link_train": dict(rec)}
    new_rec = dict(rec)
    new_rec["handler"] = "usb_link_train_task_v2"
    new = {"usb_link_train": new_rec}
    report = cti.diff_command_registries(old, new)
    assert _entry(report, "usb_link_train")["verdict"] == "SEMANTIC_CHANGE"


def test_alternate_id_alias_is_resolved():
    rec = _base_command()
    del rec["command_id"]
    rec["name"] = "usb_link_train"
    old = {"commands": [rec]}
    new = {"commands": [_base_command()]}
    report = cti.diff_command_registries(old, new)
    assert _entry(report, "usb_link_train")["verdict"] == "UNCHANGED"


# -- markdown rendering, reusing connectivity.render_markdown_table ----------

def test_markdown_render_uses_connectivity_render_markdown_table():
    old = {"commands": [_base_command()]}
    new = {"commands": [_base_command(handler="usb_link_train_task_v2"),
                        _base_command(command_id="usb_link_recover")]}
    report = cti.diff_command_registries(old, new)
    md = cti.render_command_impact_markdown(report)
    assert "| Command ID | Verdict | Findings |" in md
    assert "usb_link_train" in md
    assert "usb_link_recover" in md
    assert "**Summary**" in md
    assert "SEMANTIC_CHANGE: 1" in md
    assert "NEW_COMMAND: 1" in md


def test_markdown_render_reports_unindexed_records_never_silently():
    old = {"commands": [_base_command(), {"no_id": True}]}
    new = {"commands": [_base_command()]}
    report = cti.diff_command_registries(old, new)
    md = cti.render_command_impact_markdown(report)
    assert "unindexed record" in md
    assert "no command identifier resolvable" in md


# -- module-level execute_verb / CLI, driven as a real subprocess -----------

def test_execute_verb_returns_zero_when_nothing_concerning(tmp_path):
    old_file = tmp_path / "old.json"
    new_file = tmp_path / "new.json"
    old_file.write_text(json.dumps({"commands": [_base_command()]}), encoding="utf-8")
    new_file.write_text(json.dumps({"commands": [_base_command()]}), encoding="utf-8")
    text, code = cti.execute_verb(str(old_file), str(new_file), as_json=True)
    assert code == 0
    report = json.loads(text)
    assert report["summary"]["UNCHANGED"] == 1


def test_execute_verb_returns_one_when_something_is_concerning(tmp_path):
    old_file = tmp_path / "old.json"
    new_file = tmp_path / "new.json"
    old_file.write_text(json.dumps({"commands": [_base_command()]}), encoding="utf-8")
    new_file.write_text(json.dumps({"commands": [_base_command(handler="v2_task")]}),
                        encoding="utf-8")
    text, code = cti.execute_verb(str(old_file), str(new_file), as_json=True)
    assert code == 1


def test_execute_verb_returns_two_on_missing_file(tmp_path):
    text, code = cti.execute_verb(str(tmp_path / "missing_old.json"),
                                  str(tmp_path / "missing_new.json"))
    assert code == 2
    assert "NOT_AVAILABLE" in text


def test_execute_verb_returns_two_on_malformed_json(tmp_path):
    old_file = tmp_path / "old.json"
    new_file = tmp_path / "new.json"
    old_file.write_text("{not valid json", encoding="utf-8")
    new_file.write_text(json.dumps({"commands": []}), encoding="utf-8")
    text, code = cti.execute_verb(str(old_file), str(new_file))
    assert code == 2
    assert "NOT_AVAILABLE" in text


def test_real_subprocess_cli_entry_point(tmp_path):
    old_file = tmp_path / "old.json"
    new_file = tmp_path / "new.json"
    old_file.write_text(json.dumps({"commands": [_base_command()]}), encoding="utf-8")
    new_file.write_text(json.dumps({"commands": [
        _base_command(handler="usb_link_train_task_v2"),
        _base_command(command_id="usb_link_recover"),
    ]}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.command_txt_change_impact",
         "--old", str(old_file), "--new", str(new_file), "--json"],
        capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    assert proc.returncode == 1, proc.stderr
    report = json.loads(proc.stdout)
    assert report["summary"]["SEMANTIC_CHANGE"] == 1
    assert report["summary"]["NEW_COMMAND"] == 1
