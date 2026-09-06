"""Tests for dv_harness/existing_command_reuse_score.py.

Runs against a REAL `evidence_db.EvidenceStore` (DuckDB) with real
`insert_regression_verdict()` rows -- never a hand-written history dict --
plus real, alias-shaped `existing_commands` dicts covering the two shapes
this module is designed to read: `subsystem_command_contract.py`-style
(lowercase) and `.dv-workflow/command_inventory.csv`-style (uppercase CSV
column names turned into a dict).
"""
from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import existing_command_reuse_score as reuse
from dv_harness.evidence_db import EvidenceStore


@pytest.fixture()
def store(tmp_path):
    s = EvidenceStore(tmp_path / ".dv-harness" / "evidence" / "evidence.duckdb")
    yield s
    s.close()


def _seed_history(store, pattern, verdicts, git_shas=None):
    for i, passed in enumerate(verdicts):
        sha = (git_shas[i] if git_shas else None)
        store.insert_regression_verdict(pattern, passed, job_id=1000 + i, git_sha=sha)


# --- semantic_name_match ------------------------------------------------------


def test_semantic_name_match_real_overlap():
    need = {"description": "read the usb link status register after reset"}
    candidate = {"command_name": "usb_link_status_read", "command_category": "REGISTER_ACCESS"}
    result = reuse.semantic_name_match(need, candidate)
    assert result["status"] == "LEXICAL_OVERLAP"
    assert result["score"] > 0.0
    assert "usb" in result["overlap"] and "link" in result["overlap"]


def test_semantic_name_match_no_overlap():
    need = {"description": "drain the dma completion queue"}
    candidate = {"command_name": "phy_calibration_start"}
    result = reuse.semantic_name_match(need, candidate)
    assert result["status"] == "NO_LEXICAL_OVERLAP"
    assert result["score"] == 0.0


def test_semantic_name_match_no_text_at_all_is_distinct_from_zero_overlap():
    result = reuse.semantic_name_match({}, {})
    assert result["status"] == "NO_TEXT_TO_COMPARE"
    assert result["score"] == 0.0


def test_semantic_name_match_uses_keywords_too():
    need = {"keywords": ["lfps", "handshake"]}
    candidate = {"command_name": "generic_task", "description": "lfps handshake responder"}
    result = reuse.semantic_name_match(need, candidate)
    assert result["score"] > 0.0
    assert "lfps" in result["overlap"]


# --- argument_shape_compatibility ---------------------------------------------


def test_argument_shape_structured_full_match():
    need_args = ["ADDRESS", "VALUE"]
    cand_args = [{"position": 0, "role": "ADDRESS"}, {"position": 1, "role": "VALUE"}]
    result = reuse.argument_shape_compatibility(need_args, cand_args)
    assert result["status"] == "COMPARED"
    assert result["score"] == 1.0


def test_argument_shape_structured_partial_match():
    need_args = ["ADDRESS", "VALUE"]
    cand_args = [{"position": 0, "role": "ADDRESS"}, {"position": 1, "role": "DESTINATION"}]
    result = reuse.argument_shape_compatibility(need_args, cand_args)
    assert result["status"] == "COMPARED"
    assert result["score"] == 0.5


def test_argument_shape_flat_csv_parameters_string():
    # command_inventory.csv-style PARAMETERS is a flat string, not structured
    # roles -- still a real, if weaker, comparison.
    result = reuse.argument_shape_compatibility("addr, value", "addr, value")
    assert result["status"] == "COMPARED"
    assert result["score"] == 1.0


def test_argument_shape_unknown_when_either_side_absent():
    assert reuse.argument_shape_compatibility(None, None)["status"] == "UNKNOWN_BOTH"
    assert reuse.argument_shape_compatibility(["ADDRESS"], None)["status"] == "UNKNOWN_CANDIDATE_ARGS"
    assert reuse.argument_shape_compatibility(None, ["ADDRESS"])["status"] == "UNKNOWN_NEED_ARGS"
    for r in (reuse.argument_shape_compatibility(None, None),
              reuse.argument_shape_compatibility(["ADDRESS"], None),
              reuse.argument_shape_compatibility(None, ["ADDRESS"])):
        assert r["score"] == 0.0


def test_argument_shape_both_declared_empty_is_a_real_match():
    result = reuse.argument_shape_compatibility([], [])
    assert result["status"] == "COMPARED"
    assert result["score"] == 1.0


# --- branch_compatibility / normalize_branch_label ----------------------------


def test_branch_compat_canonical_match():
    result = reuse.branch_compatibility("branch_b0", "branch_b1")
    assert result["result"] == "MATCH"
    assert result["need_family"] == result["candidate_family"] == "branch_b"
    assert result["flags"] == []


def test_branch_compat_mismatch_across_layers():
    result = reuse.branch_compatibility("branch_a0", "branch_b0")
    assert result["result"] == "MISMATCH"
    assert result["score"] == 0.0


def test_branch_compat_unknown_when_absent():
    result = reuse.branch_compatibility(None, "branch_b0")
    assert result["result"] == "UNKNOWN"
    result2 = reuse.branch_compatibility("branch_b0", None)
    assert result2["result"] == "UNKNOWN"


def test_branch_label_legacy_naming_flagged_but_resolved():
    family, flag = reuse.normalize_branch_label("BranchA0")
    assert family == "branch_a"
    assert flag == "LEGACY_NON_CANONICAL_NAMING"

    family2, flag2 = reuse.normalize_branch_label("branch-b2")
    assert family2 == "branch_b"
    assert flag2 == "LEGACY_NON_CANONICAL_NAMING"


def test_branch_label_unrecognized_is_distinct_from_absent():
    family, flag = reuse.normalize_branch_label("totally_made_up_layer")
    assert family is None
    assert flag == "UNRECOGNIZED_BRANCH_LABEL"

    family2, flag2 = reuse.normalize_branch_label(None)
    assert family2 is None
    assert flag2 is None


def test_branch_compat_block_and_branch_fw_have_no_index():
    result = reuse.branch_compatibility("block", "block")
    assert result["result"] == "MATCH"
    result2 = reuse.branch_compatibility("branch_fw", "branch_fw")
    assert result2["result"] == "MATCH"


# --- query_command_history (real evidence_db, read-only) ---------------------


def test_query_command_history_recorded(store):
    _seed_history(store, "usb3_lfps_basic", [True, True, False])
    result = reuse.query_command_history(store, ["usb3_lfps_basic"])
    assert result["status"] == "RECORDED"
    assert result["total_runs"] == 3
    assert result["pass_count"] == 2
    assert result["fail_count"] == 1
    assert result["pass_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert result["matched_key"] == "usb3_lfps_basic"


def test_query_command_history_no_recorded_history_never_invents_a_pass_rate(store):
    result = reuse.query_command_history(store, ["never_run_pattern"])
    assert result["status"] == "NO_RECORDED_HISTORY"
    assert "pass_rate" not in result


def test_query_command_history_no_keys_to_check(store):
    result = reuse.query_command_history(store, [])
    assert result["status"] == "NO_RECORDED_HISTORY"
    assert result["keys_checked"] == []


def test_query_command_history_no_store_is_not_available():
    result = reuse.query_command_history(None, ["anything"])
    assert result["status"] == "NOT_AVAILABLE"
    assert "pass_rate" not in result


def test_query_command_history_tries_keys_in_priority_order(store):
    # Only the fallback (source_command_file stem) key has real history --
    # the earlier, higher-priority keys must not shadow it with a false
    # NO_RECORDED_HISTORY.
    _seed_history(store, "usb20_enumeration", [True])
    keys = reuse._candidate_history_keys({
        "command_name": "some_other_name",
        "source_command_file": "patterns/usb20_enumeration.txt",
    })
    result = reuse.query_command_history(store, keys)
    assert result["status"] == "RECORDED"
    assert result["matched_key"] == "usb20_enumeration"


# --- evaluate_reuse: end to end ------------------------------------------------


def test_end_to_end_reuse_candidate_found_with_real_history(store):
    _seed_history(store, "usb_link_status_read", [True, True, True])
    need = {
        "description": "read the usb link status register",
        "branch_layer": "branch_b0",
        "arguments": ["ADDRESS"],
    }
    existing_commands = [{
        "command_name": "usb_link_status_read",
        "command_category": "REGISTER_ACCESS",
        "branch_layer": "branch_b1",
        "arguments": [{"position": 0, "role": "ADDRESS"}],
        "source_command_file": "patterns/usb_link_status_read.txt",
    }]
    report = reuse.evaluate_reuse(need, existing_commands, store=store)
    assert report["status"] == reuse.REUSE_CANDIDATES_FOUND
    top = report["top_candidate"]
    assert top["command_name"] == "usb_link_status_read"
    assert top["confidence"] == "HIGH"
    assert top["historical_pass_evidence"]["status"] == "RECORDED"
    assert top["historical_pass_evidence"]["pass_rate"] == 1.0
    assert report["candidates"][0] is top
    assert report["excluded_branch_mismatch"] == []


def test_end_to_end_no_evidence_db_never_invents_history(tmp_path):
    need = {"description": "read the usb link status register", "branch_layer": "branch_b0"}
    existing_commands = [{
        "command_name": "usb_link_status_read",
        "branch_layer": "branch_b1",
    }]
    report = reuse.evaluate_reuse(need, existing_commands, root=tmp_path)
    assert report["status"] == reuse.REUSE_CANDIDATES_FOUND
    top = report["top_candidate"]
    assert top["historical_pass_evidence"]["status"] == "NOT_AVAILABLE"
    assert "pass_rate" not in top["historical_pass_evidence"]


def test_end_to_end_failing_history_scores_lower_than_passing_history(store):
    need = {"description": "read the usb link status register", "branch_layer": "branch_b0"}
    _seed_history(store, "good_cmd", [True, True, True])
    _seed_history(store, "bad_cmd", [False, False, False])
    existing_commands = [
        {"command_name": "usb_link_status_read_good", "pattern": "good_cmd",
         "branch_layer": "branch_b0", "description": "read the usb link status register"},
        {"command_name": "usb_link_status_read_bad", "pattern": "bad_cmd",
         "branch_layer": "branch_b0", "description": "read the usb link status register"},
    ]
    report = reuse.evaluate_reuse(need, existing_commands, store=store)
    assert report["status"] == reuse.REUSE_CANDIDATES_FOUND
    by_name = {c["command_name"]: c for c in report["candidates"]}
    good = by_name["usb_link_status_read_good"]
    bad = by_name["usb_link_status_read_bad"]
    assert good["historical_pass_evidence"]["pass_rate"] == 1.0
    assert bad["historical_pass_evidence"]["pass_rate"] == 0.0
    assert good["composite_score"] > bad["composite_score"]
    assert report["candidates"][0]["command_name"] == "usb_link_status_read_good"


# --- NO_REUSE_CANDIDATE negative controls (rule 4: never a confident guess) ---


def test_no_reuse_candidate_empty_existing_commands():
    report = reuse.evaluate_reuse({"description": "do the thing"}, [])
    assert report["status"] == reuse.NO_REUSE_CANDIDATE
    assert "NO_EXISTING_COMMANDS_SUPPLIED" in report["reason"]


def test_no_reuse_candidate_insufficient_need_description():
    report = reuse.evaluate_reuse({}, [{"command_name": "anything"}])
    assert report["status"] == reuse.NO_REUSE_CANDIDATE
    assert "INSUFFICIENT_NEED_DESCRIPTION" in report["reason"]


def test_no_reuse_candidate_all_branch_mismatched():
    need = {"description": "read the usb link status register", "branch_layer": "branch_a0"}
    existing_commands = [{"command_name": "usb_link_status_read", "branch_layer": "branch_b0"}]
    report = reuse.evaluate_reuse(need, existing_commands)
    assert report["status"] == reuse.NO_REUSE_CANDIDATE
    assert len(report["excluded_branch_mismatch"]) == 1
    assert report["excluded_branch_mismatch"][0]["reason"] == "BRANCH_OWNERSHIP_MISMATCH"


def test_no_reuse_candidate_below_plausibility_floor_branch_match_alone_is_not_enough():
    # Same branch family, but zero name overlap and zero argument evidence --
    # branch agreement alone must not manufacture a "finding".
    need = {"description": "drain the dma completion queue", "branch_layer": "branch_b0"}
    existing_commands = [{"command_name": "phy_calibration_start", "branch_layer": "branch_b3"}]
    report = reuse.evaluate_reuse(need, existing_commands)
    assert report["status"] == reuse.NO_REUSE_CANDIDATE
    assert "NO_PLAUSIBLE_MATCH" in report["reason"]
    assert len(report["below_floor_candidates"]) == 1


def test_malformed_candidate_entries_are_excluded_not_crashed():
    need = {"description": "read the usb link status register", "branch_layer": "branch_b0"}
    existing_commands = ["not_a_dict", 42, None,
                          {"command_name": "usb_link_status_read", "branch_layer": "branch_b0"}]
    report = reuse.evaluate_reuse(need, existing_commands)
    # the three malformed entries are excluded, never crash the evaluation
    malformed = [e for e in report["excluded_branch_mismatch"] if e.get("reason") == "CANDIDATE_NOT_A_DICT"]
    assert len(malformed) == 3


def test_evaluate_reuse_rejects_non_dict_need():
    with pytest.raises(reuse.NeedValidationError):
        reuse.evaluate_reuse("not a dict", [{"command_name": "x"}])


# --- field-alias robustness: command_inventory.csv-shaped dicts ---------------


def test_command_inventory_csv_style_uppercase_fields():
    need = {"description": "write the usb endpoint config register", "branch_layer": "branch_a0"}
    existing_commands = [{
        "COMMAND_ID": "C-042",
        "PROTOCOL": "USB3",
        "COMMAND": "usb_endpoint_config_write",
        "PARAMETERS": "addr, value",
        "SOURCE": "patterns/usb_ep_cfg.txt",
        "USER_SCOPE": "DE_DV",
        "HANDLER": "host_agent",
        "VIP_SEQUENCE": "usb_ep_cfg_seq",
        "STATUS": "ACTIVE",
        "CONFIDENCE": "HIGH",
        "BRANCH_LAYER": "branch_a1",
    }]
    report = reuse.evaluate_reuse(need, existing_commands)
    assert report["status"] == reuse.REUSE_CANDIDATES_FOUND
    top = report["top_candidate"]
    assert top["command_name"] == "usb_endpoint_config_write"
    assert top["declared_status"] == "ACTIVE"
    assert top["declared_confidence"] == "HIGH"


def test_declared_status_and_confidence_are_informational_never_scored():
    # A candidate self-declaring STATUS/CONFIDENCE must not receive credit for
    # it -- only real evidence_db history counts toward the composite score.
    need = {"description": "totally unrelated need with no overlap at all"}
    existing_commands = [{
        "COMMAND": "phy_calibration_start", "STATUS": "ACTIVE", "CONFIDENCE": "HIGH",
    }]
    report = reuse.evaluate_reuse(need, existing_commands)
    assert report["status"] == reuse.NO_REUSE_CANDIDATE


def test_ranking_prefers_higher_composite_score_over_declaration_order():
    need = {"description": "read the usb link status register", "branch_layer": "branch_b0",
            "arguments": ["ADDRESS"]}
    existing_commands = [
        {"command_name": "unrelated_but_same_branch", "branch_layer": "branch_b0",
         "description": "drain queue", "arguments": ["ADDRESS"]},
        {"command_name": "usb_link_status_read", "branch_layer": "branch_b0",
         "description": "read the usb link status register",
         "arguments": [{"position": 0, "role": "ADDRESS"}]},
    ]
    report = reuse.evaluate_reuse(need, existing_commands)
    assert report["status"] == reuse.REUSE_CANDIDATES_FOUND
    assert report["candidates"][0]["command_name"] == "usb_link_status_read"


def test_format_reuse_report_renders_no_reuse_candidate():
    report = reuse.evaluate_reuse({"description": "x"}, [])
    text = reuse.format_reuse_report(report)
    assert "NO_REUSE_CANDIDATE" in text
    assert "NO_EXISTING_COMMANDS_SUPPLIED" in text


def test_format_reuse_report_renders_candidates(store):
    _seed_history(store, "usb_link_status_read", [True])
    need = {"description": "read the usb link status register", "branch_layer": "branch_b0"}
    existing_commands = [{"command_name": "usb_link_status_read", "branch_layer": "branch_b0"}]
    report = reuse.evaluate_reuse(need, existing_commands, store=store)
    text = reuse.format_reuse_report(report)
    assert "usb_link_status_read" in text
    assert "HIGH" in text or "MEDIUM" in text or "LOW" in text


# --- CLI entry point -----------------------------------------------------------


def test_execute_verb_exit_codes(tmp_path):
    need_file = tmp_path / "need.json"
    commands_file = tmp_path / "commands.json"
    need_file.write_text('{"description": "read the usb link status register", '
                         '"branch_layer": "branch_b0"}', encoding="utf-8")
    commands_file.write_text('[{"command_name": "usb_link_status_read", '
                             '"branch_layer": "branch_b0"}]', encoding="utf-8")
    import json
    text, code = reuse.execute_verb(
        need=json.loads(need_file.read_text(encoding="utf-8")),
        existing_commands=json.loads(commands_file.read_text(encoding="utf-8")),
    )
    assert code == 0
    assert "REUSE_CANDIDATES_FOUND" in text

    text2, code2 = reuse.execute_verb(need={}, existing_commands=[])
    assert code2 == 1
    assert "NO_REUSE_CANDIDATE" in text2


def test_main_cli_subprocess(tmp_path):
    import json
    import subprocess
    import sys

    need_file = tmp_path / "need.json"
    commands_file = tmp_path / "commands.json"
    need_file.write_text(json.dumps({"description": "read the usb link status register",
                                     "branch_layer": "branch_b0"}), encoding="utf-8")
    commands_file.write_text(json.dumps([{"command_name": "usb_link_status_read",
                                          "branch_layer": "branch_b0"}]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.existing_command_reuse_score",
         "--need-file", str(need_file), "--commands-file", str(commands_file), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "REUSE_CANDIDATES_FOUND"


def test_weights_sum_to_one_and_thresholds_are_ordered():
    assert abs((reuse.WEIGHT_NAME + reuse.WEIGHT_ARGS + reuse.WEIGHT_BRANCH
                + reuse.WEIGHT_HISTORY) - 1.0) < 1e-9
    assert reuse.HIGH_THRESHOLD > reuse.MEDIUM_THRESHOLD > 0.0
