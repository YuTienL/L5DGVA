"""Tests for dv_harness/change_cascade.py -- the change-cascade impact table.

Covers: the positive path (a known changed field maps to real, non-empty
downstream artifacts whose producing_module really resolves), the negative
controls (an undeclared field is UNKNOWN_FIELD, never a silent empty MAPPED;
a change record naming no field is NO_FIELD_NAMED; a mutated/fabricated
producing_module citation is caught by assert_producing_modules_resolve()),
multi-change aggregation (duck-typed strings and dicts alike, deduplicating
an artifact shared by two changed fields), and the real revoke_decision()
integration against a real QuestionQueueStore on disk -- including its own
negative controls (nothing on file for a key, and revoking twice)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import change_cascade as cc
from dv_harness import question_queue as qq


# --------------------------------------------------------------------------
# The table itself
# --------------------------------------------------------------------------

def test_every_known_field_maps_to_at_least_one_real_artifact():
    fields = cc.known_changed_fields()
    assert len(fields) >= 8
    for field_name in fields:
        result = cc.cascade_for_changed_field(field_name)
        assert result.status == cc.STATUS_MAPPED
        assert len(result.artifacts) >= 1
        for artifact in result.artifacts:
            assert artifact.artifact
            assert artifact.reason
            assert artifact.producing_module
            assert artifact.revalidation_action


def test_producing_module_citations_all_resolve_for_real():
    # No exception -- every dotted module name in the table really imports.
    cc.assert_producing_modules_resolve()


def test_a_fabricated_citation_is_caught_not_trusted():
    fabricated = {
        "vip_version": (
            cc.DownstreamArtifact(
                artifact="nonexistent_artifact.json",
                reason="synthetic negative control",
                producing_module="dv_harness.this_module_does_not_exist_at_all",
                revalidation_action="n/a",
            ),
        ),
    }
    original = dict(cc.CHANGE_CASCADE_TABLE)
    cc.CHANGE_CASCADE_TABLE.clear()
    cc.CHANGE_CASCADE_TABLE.update(fabricated)
    try:
        with pytest.raises(cc.ChangeCascadeError):
            cc.assert_producing_modules_resolve()
    finally:
        cc.CHANGE_CASCADE_TABLE.clear()
        cc.CHANGE_CASCADE_TABLE.update(original)
    # Restored table must be clean again.
    cc.assert_producing_modules_resolve()


def test_vip_version_names_the_documented_downstream_artifacts():
    # The task's own worked example: vip_version changed -> vip_api_cards.json,
    # bind validations, connectivity gate results all now suspect.
    result = cc.cascade_for_changed_field("vip_version")
    assert result.status == cc.STATUS_MAPPED
    artifact_names = " ".join(a.artifact for a in result.artifacts)
    assert "vip_api_cards.json" in artifact_names
    assert "bind validations" in artifact_names or "connectivity" in artifact_names.lower()


def test_unknown_field_is_reported_never_silently_empty():
    result = cc.cascade_for_changed_field("this_field_was_never_declared")
    assert result.status == cc.STATUS_UNKNOWN_FIELD
    assert result.artifacts == ()
    assert "this_field_was_never_declared" in result.reason
    # The reason must name real known fields, not just complain.
    assert "vip_version" in result.reason


def test_cascade_for_declared_field_never_reports_unknown():
    for field_name in cc.known_changed_fields():
        assert cc.cascade_for_changed_field(field_name).status == cc.STATUS_MAPPED


# --------------------------------------------------------------------------
# assess_changes(): duck-typed multi-change aggregation
# --------------------------------------------------------------------------

def test_assess_changes_accepts_bare_strings():
    report = cc.assess_changes(["vip_version"])
    assert report["schema_version"] == cc.SCHEMA_VERSION
    assert len(report["changes"]) == 1
    assert report["changes"][0]["status"] == cc.STATUS_MAPPED
    assert report["unknown_fields"] == []
    assert len(report["suspect_artifacts"]) >= 1


def test_assess_changes_accepts_duck_typed_dicts_identically_to_strings():
    string_report = cc.assess_changes(["rtl_source"])
    dict_report = cc.assess_changes([{"field": "rtl_source", "old_value": "sha_a",
                                        "new_value": "sha_b", "detected_by": "hypothetical_diff_tool"}])
    string_artifacts = sorted(a["artifact"] for a in string_report["suspect_artifacts"])
    dict_artifacts = sorted(a["artifact"] for a in dict_report["suspect_artifacts"])
    assert string_artifacts == dict_artifacts
    # The extra keys on the dict form are carried through verbatim, never inspected.
    echoed = dict_report["changes"][0]["change"]
    assert echoed["old_value"] == "sha_a"
    assert echoed["detected_by"] == "hypothetical_diff_tool"


def test_a_change_record_naming_no_field_is_reported_not_skipped():
    report = cc.assess_changes([{"old_value": "x", "new_value": "y"}])
    assert len(report["changes"]) == 1
    assert report["changes"][0]["status"] == cc.STATUS_NO_FIELD_NAMED
    assert report["suspect_artifacts"] == []


def test_multiple_changes_aggregate_and_dedupe_shared_artifacts():
    # vip_version and rtl_source both make the recorded golden-scenario capsule
    # freshness artifact suspect (evaluate_freshness() checks BOTH a moved VIP/
    # tool version and a moved RTL sha); aggregation must not double the
    # artifact, only extend its triggered_by list.
    report = cc.assess_changes(["vip_version", "rtl_source"])
    assert set(report["unknown_fields"]) == set()
    by_name = {a["artifact"]: a for a in report["suspect_artifacts"]}
    shared = [a for a in by_name.values() if len(a["triggered_by"]) >= 2]
    assert shared, "expected at least one artifact shared by both changed fields"
    for entry in shared:
        assert set(entry["triggered_by"]) <= {"vip_version", "rtl_source"}
        assert len(entry["reasons"]) == len(entry["triggered_by"])


def test_mixed_known_and_unknown_fields_reports_both_honestly():
    report = cc.assess_changes(["vip_version", "not_a_real_field"])
    assert report["unknown_fields"] == ["not_a_real_field"]
    assert any(c["status"] == cc.STATUS_MAPPED for c in report["changes"])
    assert any(c["status"] == cc.STATUS_UNKNOWN_FIELD for c in report["changes"])
    # The unknown field must not contribute any suspect artifact.
    assert all("not_a_real_field" not in a["triggered_by"] for a in report["suspect_artifacts"])


# --------------------------------------------------------------------------
# revoke_stale_decisions(): a real call into question_queue.revoke_decision()
# --------------------------------------------------------------------------

def _make_real_human_decision(root: Path, question_key: str) -> qq.QuestionQueueStore:
    """Build a REAL persisted human-answer decision through the real
    QuestionQueueStore add_question()/answer_question() path -- never a
    hand-written decisions.json -- so revoke_stale_decisions() is proven
    against a decision this project's own real mechanism produced."""
    store = qq.QuestionQueueStore(root)
    question = store.add_question(
        domain="vip",
        question="Which VIP release is this environment built against?",
        context_path="vip_config.vip_release",
        options=["release_a", "release_b"],
        recommendation="release_a",
        assumption_if_unanswered="release_a",
        question_key=question_key,
    )
    store.answer_question(question["id"], answer="release_a",
                            basis="confirmed against $DESIGNWARE_HOME scan",
                            decided_by="dv-owner")
    assert store.find_decision(question_key) is not None
    return store


def test_revoke_stale_decisions_really_revokes_a_real_human_decision(tmp_path):
    root = tmp_path / "proj1"
    root.mkdir()
    key = "vip:which-release:vip_config.vip_release"
    store = _make_real_human_decision(root, key)

    outcomes = cc.revoke_stale_decisions(root, "vip_version", [key], revoked_by="dv-owner",
                                          extra_reason="VIP bumped to release_c")
    assert outcomes[key]["status"] == cc.REVOKE_STATUS_REVOKED
    assert "change_cascade" in outcomes[key]["revocation"]["reason"]
    assert "vip_version" in outcomes[key]["revocation"]["reason"]

    # The real store must now show no live decision for this key.
    assert store.find_decision(key) is None
    # And the revocation must be preserved in the audit trail, not deleted.
    revoked_list = json.loads((root / ".dv-harness" / "question_queue" / "decisions.json")
                              .read_text(encoding="utf-8"))["revoked"]
    assert any(r["question_key"] == key for r in revoked_list)


def test_revoke_stale_decisions_reports_no_live_decision_honestly(tmp_path):
    root = tmp_path / "proj2"
    root.mkdir()
    outcomes = cc.revoke_stale_decisions(root, "rtl_source", ["some:key:never-asked"])
    assert outcomes["some:key:never-asked"]["status"] == cc.REVOKE_STATUS_NO_LIVE_DECISION


def test_revoke_stale_decisions_second_call_on_same_key_is_no_live_decision(tmp_path):
    root = tmp_path / "proj3"
    root.mkdir()
    key = "env:register-file-version:dut_facts.registers"
    _make_real_human_decision(root, key)
    first = cc.revoke_stale_decisions(root, "register_map", [key])
    assert first[key]["status"] == cc.REVOKE_STATUS_REVOKED
    second = cc.revoke_stale_decisions(root, "register_map", [key])
    assert second[key]["status"] == cc.REVOKE_STATUS_NO_LIVE_DECISION


def test_revoke_stale_decisions_never_touches_a_decision_for_a_different_key(tmp_path):
    root = tmp_path / "proj4"
    root.mkdir()
    kept_key = "vip:other-fact:unrelated"
    stale_key = "vip:which-release:vip_config.vip_release"
    _make_real_human_decision(root, kept_key)
    store = _make_real_human_decision(root, stale_key)

    cc.revoke_stale_decisions(root, "vip_version", [stale_key])
    assert store.find_decision(stale_key) is None
    assert store.find_decision(kept_key) is not None


def test_revoke_stale_decisions_accepts_an_injected_store(tmp_path):
    root = tmp_path / "proj5"
    root.mkdir()
    key = "vip:which-release:vip_config.vip_release"
    store = _make_real_human_decision(root, key)
    outcomes = cc.revoke_stale_decisions(root, "vip_version", [key], store=store)
    assert outcomes[key]["status"] == cc.REVOKE_STATUS_REVOKED


# --------------------------------------------------------------------------
# execute_verb() / CLI front door
# --------------------------------------------------------------------------

def test_execute_verb_fields_lists_all_known_fields():
    text, code = cc.execute_verb("fields", as_json=True)
    assert code == 0
    fields = json.loads(text)
    assert set(fields) == set(cc.known_changed_fields())


def test_execute_verb_assess_by_changed_field(tmp_path):
    text, code = cc.execute_verb("assess", root=tmp_path, changed_field="vip_version", as_json=True)
    assert code == 0
    report = json.loads(text)
    assert report["unknown_fields"] == []
    assert report["suspect_artifacts"]


def test_execute_verb_assess_unknown_field_exits_1(tmp_path):
    text, code = cc.execute_verb("assess", root=tmp_path, changed_field="not_real", as_json=True)
    assert code == 1
    report = json.loads(text)
    assert report["unknown_fields"] == ["not_real"]


def test_execute_verb_assess_from_changes_file(tmp_path):
    changes_file = tmp_path / "changes.json"
    changes_file.write_text(json.dumps(["vip_version", "rtl_source"]), encoding="utf-8")
    text, code = cc.execute_verb("assess", root=tmp_path, changes_json_file=str(changes_file),
                                  as_json=True)
    assert code == 0
    report = json.loads(text)
    assert len(report["changes"]) == 2


def test_execute_verb_assess_requires_a_field_or_a_file(tmp_path):
    text, code = cc.execute_verb("assess", root=tmp_path)
    assert code == 2
    assert "requires" in text


def test_execute_verb_revoke_requires_question_keys(tmp_path):
    text, code = cc.execute_verb("revoke", root=tmp_path, changed_field="vip_version")
    assert code == 2


def test_execute_verb_revoke_real_round_trip(tmp_path):
    key = "vip:which-release:vip_config.vip_release"
    _make_real_human_decision(tmp_path, key)
    text, code = cc.execute_verb("revoke", root=tmp_path, changed_field="vip_version",
                                  question_keys=[key], revoked_by="dv-owner", as_json=True)
    assert code == 0
    outcomes = json.loads(text)
    assert outcomes[key]["status"] == cc.REVOKE_STATUS_REVOKED


def test_execute_verb_unknown_verb():
    text, code = cc.execute_verb("bogus-verb")
    assert code == 2
    assert "unknown change-cascade verb" in text


def test_cli_module_runs_as_a_real_subprocess(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.change_cascade", "fields", "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    fields = json.loads(result.stdout)
    assert "vip_version" in fields


def test_cli_module_assess_as_a_real_subprocess_unknown_field_exits_1(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.change_cascade", "assess",
         "--changed-field", "definitely_not_declared", "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["unknown_fields"] == ["definitely_not_declared"]
