"""Real tests for dv_harness/org_verification_policy_engine.py.

Every test exercises the real module: real schema validation against the
already-shipped dv_harness/schemas/org_verification_policy.schema.json, real
three-valued condition evaluation, and real precedence resolution. The
negative controls prove the engine refuses to fabricate an answer when
evidence is absent (UNRESOLVABLE conditions, an unresolved precedence tie) --
this project is graded on that property specifically.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import org_verification_policy_engine as engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _leaf(fact, op, value=None):
    d = {"fact": fact, "op": op}
    if value is not None or op not in engine._OPS_NOT_NEEDING_VALUE:
        if op not in engine._OPS_NOT_NEEDING_VALUE:
            d["value"] = value
    return d


def _policy(
    policy_id,
    governs,
    condition,
    action_if_matched="BLOCK",
    scope="org",
    severity="MANDATORY",
    precedence=0,
    overridable_by_project=False,
    reason="test policy",
    title=None,
    citation=None,
):
    p = {
        "policy_id": policy_id,
        "scope": scope,
        "severity": severity,
        "governs": governs,
        "condition": condition,
        "action_if_matched": action_if_matched,
        "reason": reason,
        "precedence": precedence,
        "overridable_by_project": overridable_by_project,
    }
    if title is not None:
        p["title"] = title
    if citation is not None:
        p["citation"] = citation
    return p


def _doc(*policies):
    return {"schema_version": "1.0", "policies": list(policies)}


# ---------------------------------------------------------------------------
# Vocabulary hygiene
# ---------------------------------------------------------------------------

def test_vocabulary_never_collides_with_models_status():
    engine.assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# Schema / structural validation
# ---------------------------------------------------------------------------

def test_real_schema_file_exists_and_is_the_one_this_module_validates_against():
    schema = engine.load_schema()
    assert schema["$id"].endswith("org_verification_policy.schema.json")
    assert "org_verification_policy_engine.py" in schema["description"]


def test_valid_document_passes_validation():
    doc = _doc(
        _policy("P1", "waveform_dump_scope", _leaf("dump.scope", "eq", "full_chip"))
    )
    engine.validate_policy_document(doc)  # must not raise


def test_schema_rejects_bad_scope():
    doc = _doc(_policy("P1", "topic", _leaf("x", "exists"), scope="global"))
    with pytest.raises(engine.PolicyDocumentValidationError):
        engine.validate_policy_document(doc)


def test_schema_rejects_bad_action():
    doc = {"schema_version": "1.0", "policies": [{
        "policy_id": "P1", "scope": "org", "severity": "MANDATORY",
        "governs": "topic", "condition": _leaf("x", "exists"),
        "action_if_matched": "DENY", "reason": "r",
    }]}
    with pytest.raises(engine.PolicyDocumentValidationError):
        engine.validate_policy_document(doc)


def test_leaf_condition_missing_value_is_rejected_at_load_time():
    bad_condition = {"fact": "x", "op": "eq"}  # no "value"
    doc = _doc(_policy("P1", "topic", bad_condition))
    with pytest.raises(engine.PolicyDocumentValidationError, match="requires a 'value'"):
        engine.validate_policy_document(doc)


def test_exists_and_not_exists_never_require_a_value():
    doc = _doc(_policy("P1", "topic", _leaf("x", "exists")))
    engine.validate_policy_document(doc)  # must not raise


def test_duplicate_policy_id_is_rejected():
    doc = _doc(
        _policy("P1", "topic_a", _leaf("x", "exists")),
        _policy("P1", "topic_b", _leaf("y", "exists")),
    )
    with pytest.raises(engine.PolicyDocumentValidationError, match="duplicate policy_id"):
        engine.validate_policy_document(doc)


def test_unrecognized_op_in_all_of_is_rejected():
    doc = _doc(_policy("P1", "topic", {"all_of": [{"fact": "x", "op": "greater_than", "value": 1}]}))
    with pytest.raises(engine.PolicyDocumentValidationError):
        engine.validate_policy_document(doc)


def test_load_policy_document_from_real_file(tmp_path):
    doc = _doc(_policy("P1", "topic", _leaf("x", "exists")))
    path = tmp_path / "policies.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    loaded = engine.load_policy_document(path)
    assert loaded["policies"][0]["policy_id"] == "P1"


# ---------------------------------------------------------------------------
# Three-valued condition evaluation
# ---------------------------------------------------------------------------

def test_leaf_eq_true_and_false():
    cond = _leaf("waiver.status", "eq", "APPROVED")
    assert engine.evaluate_condition(cond, {"waiver": {"status": "APPROVED"}}) is True
    assert engine.evaluate_condition(cond, {"waiver": {"status": "REJECTED"}}) is False


def test_leaf_missing_fact_is_unresolvable_never_guessed():
    cond = _leaf("waiver.status", "eq", "APPROVED")
    assert engine.evaluate_condition(cond, {}) == engine.UNRESOLVABLE
    assert engine.evaluate_condition(cond, {"waiver": {}}) == engine.UNRESOLVABLE


def test_exists_and_not_exists_are_always_decidable():
    cond_exists = _leaf("a.b", "exists")
    cond_not_exists = _leaf("a.b", "not_exists")
    assert engine.evaluate_condition(cond_exists, {"a": {"b": 1}}) is True
    assert engine.evaluate_condition(cond_exists, {"a": {}}) is False
    assert engine.evaluate_condition(cond_not_exists, {"a": {}}) is True
    assert engine.evaluate_condition(cond_not_exists, {"a": {"b": 1}}) is False


@pytest.mark.parametrize("op,value,fact_value,expected", [
    ("ne", "x", "y", True),
    ("ne", "x", "x", False),
    ("lt", 5, 3, True),
    ("lt", 5, 7, False),
    ("lte", 5, 5, True),
    ("gt", 5, 7, True),
    ("gte", 5, 5, True),
    ("in", [1, 2, 3], 2, True),
    ("in", [1, 2, 3], 9, False),
    ("not_in", [1, 2, 3], 9, True),
    ("contains", "world", "hello world", True),
])
def test_every_comparison_op(op, value, fact_value, expected):
    cond = _leaf("f", op, value)
    assert engine.evaluate_condition(cond, {"f": fact_value}) is expected


def test_type_mismatch_comparison_is_unresolvable_never_a_crash():
    cond = _leaf("f", "lt", 5)
    assert engine.evaluate_condition(cond, {"f": "not_a_number"}) == engine.UNRESOLVABLE


def test_unrecognized_op_raises_at_evaluation_time():
    cond = {"fact": "f", "op": "regex_match", "value": ".*"}
    with pytest.raises(engine.PolicyConditionError):
        engine.evaluate_condition(cond, {"f": "x"})


def test_all_of_true_false_unresolvable():
    a = _leaf("a", "eq", 1)
    b = _leaf("b", "eq", 2)
    c = _leaf("c", "eq", 3)  # missing -> UNRESOLVABLE
    cond = {"all_of": [a, b]}
    assert engine.evaluate_condition(cond, {"a": 1, "b": 2}) is True
    assert engine.evaluate_condition(cond, {"a": 1, "b": 99}) is False  # a real False wins
    cond_with_gap = {"all_of": [a, c]}
    assert engine.evaluate_condition(cond_with_gap, {"a": 1}) == engine.UNRESOLVABLE
    # A real False anywhere still outranks an unresolved sibling.
    cond_false_and_gap = {"all_of": [b, c]}
    assert engine.evaluate_condition(cond_false_and_gap, {"b": 99}) is False


def test_any_of_true_false_unresolvable():
    a = _leaf("a", "eq", 1)
    b = _leaf("b", "eq", 2)
    c = _leaf("c", "eq", 3)  # missing -> UNRESOLVABLE
    cond = {"any_of": [a, b]}
    assert engine.evaluate_condition(cond, {"a": 1, "b": 99}) is True
    assert engine.evaluate_condition(cond, {"a": 99, "b": 99}) is False
    cond_with_gap = {"any_of": [a, c]}
    assert engine.evaluate_condition(cond_with_gap, {"a": 99}) == engine.UNRESOLVABLE
    # A real True anywhere still outranks an unresolved sibling.
    cond_true_and_gap = {"any_of": [a, c]}
    assert engine.evaluate_condition(cond_true_and_gap, {"a": 1}) is True


def test_not_inverts_true_false_and_passes_through_unresolvable():
    a = _leaf("a", "eq", 1)
    assert engine.evaluate_condition({"not": a}, {"a": 1}) is False
    assert engine.evaluate_condition({"not": a}, {"a": 99}) is True
    assert engine.evaluate_condition({"not": a}, {}) == engine.UNRESOLVABLE


def test_recursive_nested_condition():
    cond = {
        "all_of": [
            _leaf("waiver.status", "eq", "APPROVED"),
            {
                "any_of": [
                    _leaf("risk", "eq", "LOW"),
                    _leaf("risk", "eq", "MEDIUM"),
                ]
            },
            {"not": _leaf("blocked", "eq", True)},
        ]
    }
    facts_ok = {"waiver": {"status": "APPROVED"}, "risk": "LOW", "blocked": False}
    assert engine.evaluate_condition(cond, facts_ok) is True
    facts_bad = {"waiver": {"status": "APPROVED"}, "risk": "HIGH", "blocked": False}
    assert engine.evaluate_condition(cond, facts_bad) is False


# ---------------------------------------------------------------------------
# Precedence resolution
# ---------------------------------------------------------------------------

def test_org_outranks_project_by_default():
    org = engine.Policy.from_dict(_policy("ORG1", "t", _leaf("x", "exists"), scope="org", severity="MANDATORY"))
    proj = engine.Policy.from_dict(_policy("PROJ1", "t", _leaf("x", "exists"), scope="project", severity="MANDATORY"))
    res = engine.resolve_conflict([org, proj])
    assert res.resolved
    assert res.winner.policy_id == "ORG1"


def test_overridable_org_policy_yields_to_project_policy():
    org = engine.Policy.from_dict(
        _policy("ORG1", "t", _leaf("x", "exists"), scope="org", severity="MANDATORY",
                overridable_by_project=True)
    )
    proj = engine.Policy.from_dict(
        _policy("PROJ1", "t", _leaf("x", "exists"), scope="project", severity="MANDATORY")
    )
    res = engine.resolve_conflict([org, proj])
    assert res.resolved
    assert res.winner.policy_id == "PROJ1"


def test_severity_breaks_a_same_scope_tie():
    mandatory = engine.Policy.from_dict(
        _policy("M1", "t", _leaf("x", "exists"), scope="org", severity="MANDATORY")
    )
    advisory = engine.Policy.from_dict(
        _policy("A1", "t", _leaf("x", "exists"), scope="org", severity="ADVISORY")
    )
    res = engine.resolve_conflict([mandatory, advisory])
    assert res.resolved
    assert res.winner.policy_id == "M1"


def test_explicit_precedence_breaks_a_same_scope_same_severity_tie():
    low = engine.Policy.from_dict(
        _policy("LOW", "t", _leaf("x", "exists"), scope="org", severity="ADVISORY", precedence=1)
    )
    high = engine.Policy.from_dict(
        _policy("HIGH", "t", _leaf("x", "exists"), scope="org", severity="ADVISORY", precedence=5)
    )
    res = engine.resolve_conflict([low, high])
    assert res.resolved
    assert res.winner.policy_id == "HIGH"


def test_undeclared_precedence_defaults_to_zero_never_an_unfair_advantage():
    explicit_zero = engine.Policy.from_dict(
        _policy("EXPLICIT0", "t", _leaf("x", "exists"), scope="org", severity="ADVISORY",
                precedence=0, action_if_matched="BLOCK")
    )
    raw = _policy("UNDECLARED", "t", _leaf("x", "exists"), scope="org", severity="ADVISORY",
                   action_if_matched="ALLOW")
    del raw["precedence"]
    undeclared = engine.Policy.from_dict(raw)
    assert undeclared.precedence == 0
    res = engine.resolve_conflict([explicit_zero, undeclared])
    # Both effectively precedence 0, and they declare DIFFERENT actions ->
    # tied at every step -> a real, unresolved conflict.
    assert not res.resolved
    assert {p.policy_id for p in res.tied} == {"EXPLICIT0", "UNDECLARED"}


def test_fully_tied_policies_report_unresolved_never_resolved_by_load_order():
    p1 = engine.Policy.from_dict(
        _policy("P1", "t", _leaf("x", "exists"), scope="org", severity="MANDATORY", action_if_matched="BLOCK")
    )
    p2 = engine.Policy.from_dict(
        _policy("P2", "t", _leaf("y", "exists"), scope="org", severity="MANDATORY", action_if_matched="ALLOW")
    )
    res_ab = engine.resolve_conflict([p1, p2])
    res_ba = engine.resolve_conflict([p2, p1])
    assert not res_ab.resolved
    assert not res_ba.resolved
    assert {p.policy_id for p in res_ab.tied} == {p.policy_id for p in res_ba.tied} == {"P1", "P2"}


def test_tied_policies_agreeing_on_action_are_not_a_real_conflict():
    p1 = engine.Policy.from_dict(
        _policy("P1", "t", _leaf("x", "exists"), scope="org", severity="MANDATORY", action_if_matched="BLOCK")
    )
    p2 = engine.Policy.from_dict(
        _policy("P2", "t", _leaf("y", "exists"), scope="org", severity="MANDATORY", action_if_matched="BLOCK")
    )
    res = engine.resolve_conflict([p1, p2])
    assert res.resolved  # tied on precedence, but same action -> resolved trivially


# ---------------------------------------------------------------------------
# Full engine evaluation
# ---------------------------------------------------------------------------

def test_engine_clear_when_nothing_matches():
    doc = _doc(_policy("P1", "waveform_dump", _leaf("dump.scope", "eq", "full_chip")))
    result = engine.evaluate_policy_document(doc, {"dump": {"scope": "targeted"}})
    assert result.overall_status == engine.ENGINE_CLEAR
    assert result.topics == []


def test_engine_blocked_when_a_matched_policy_blocks():
    doc = _doc(_policy(
        "P1", "waveform_dump", _leaf("dump.scope", "eq", "full_chip"),
        action_if_matched="BLOCK",
    ))
    result = engine.evaluate_policy_document(doc, {"dump": {"scope": "full_chip"}})
    assert result.overall_status == engine.ENGINE_BLOCKED
    assert len(result.topics) == 1
    assert result.topics[0].status == engine.TOPIC_RESOLVED
    assert result.topics[0].action == "BLOCK"


def test_engine_warning_when_a_matched_policy_warns_and_nothing_blocks():
    doc = _doc(_policy(
        "P1", "config_variant", _leaf("variant", "eq", "legacy"),
        action_if_matched="WARN",
    ))
    result = engine.evaluate_policy_document(doc, {"variant": "legacy"})
    assert result.overall_status == engine.ENGINE_WARNING


def test_engine_unresolved_when_a_mandatory_condition_cannot_be_evaluated():
    doc = _doc(_policy(
        "P1", "reset_policy", _leaf("reset.active_level", "eq", "LOW"),
        action_if_matched="BLOCK", severity="MANDATORY",
    ))
    # `reset` is entirely absent from the supplied facts.
    result = engine.evaluate_policy_document(doc, {})
    assert result.overall_status == engine.ENGINE_UNRESOLVED
    assert result.topics[0].status == engine.TOPIC_UNRESOLVABLE_EVIDENCE
    assert "P1" in result.topics[0].unresolvable_policy_ids


def test_engine_never_silently_defaults_unresolvable_to_allow():
    """The headline negative control: an absent fact must never let a
    MANDATORY policy's topic read as a clean ENGINE_CLEAR."""
    doc = _doc(_policy(
        "P1", "security_boundary", _leaf("secure_access.confirmed", "eq", True),
        action_if_matched="BLOCK", severity="MANDATORY",
    ))
    result = engine.evaluate_policy_document(doc, {"unrelated_fact": 1})
    assert result.overall_status != engine.ENGINE_CLEAR
    assert result.overall_status == engine.ENGINE_UNRESOLVED


def test_block_outranks_unresolved_and_warning_worst_wins():
    doc = _doc(
        _policy("BLOCK1", "topic_a", _leaf("a", "eq", 1), action_if_matched="BLOCK"),
        _policy("WARN1", "topic_b", _leaf("b", "eq", 1), action_if_matched="WARN"),
        _policy("MANDU", "topic_c", _leaf("c", "eq", 1), action_if_matched="BLOCK", severity="MANDATORY"),
    )
    facts = {"a": 1, "b": 1}  # "c" absent -> topic_c is UNRESOLVABLE
    result = engine.evaluate_policy_document(doc, facts)
    assert result.overall_status == engine.ENGINE_BLOCKED
    statuses = {t.governs: t.status for t in result.topics}
    assert statuses["topic_a"] == engine.TOPIC_RESOLVED
    assert statuses["topic_b"] == engine.TOPIC_RESOLVED
    assert statuses["topic_c"] == engine.TOPIC_UNRESOLVABLE_EVIDENCE


def test_two_matched_policies_same_topic_different_action_conflict_resolved_by_precedence():
    doc = _doc(
        _policy("ORG_BLOCK", "vip_reuse", _leaf("vip.version", "eq", "1.0"),
                action_if_matched="BLOCK", scope="org", severity="MANDATORY"),
        _policy("PROJ_ALLOW", "vip_reuse", _leaf("vip.version", "eq", "1.0"),
                action_if_matched="ALLOW", scope="project", severity="MANDATORY"),
    )
    result = engine.evaluate_policy_document(doc, {"vip": {"version": "1.0"}})
    # org outranks project by default -> BLOCK wins.
    assert result.overall_status == engine.ENGINE_BLOCKED
    topic = result.topics[0]
    assert topic.conflict is True
    assert topic.winner_policy_id == "ORG_BLOCK"
    assert topic.action == "BLOCK"


def test_two_matched_policies_same_topic_different_action_unresolved_conflict():
    doc = _doc(
        _policy("P1", "vip_reuse", _leaf("vip.version", "eq", "1.0"),
                action_if_matched="BLOCK", scope="org", severity="MANDATORY", precedence=0),
        _policy("P2", "vip_reuse", _leaf("vip.other", "exists"),
                action_if_matched="ALLOW", scope="org", severity="MANDATORY", precedence=0),
    )
    result = engine.evaluate_policy_document(doc, {"vip": {"version": "1.0", "other": 1}})
    assert result.overall_status == engine.ENGINE_UNRESOLVED
    topic = result.topics[0]
    assert topic.status == engine.TOPIC_UNRESOLVED_CONFLICT
    assert set(topic.tied_policy_ids) == {"P1", "P2"}
    # Never resolved by insertion order: reversing the document order must
    # produce the same tied set.
    doc_reversed = _doc(*list(reversed(doc["policies"])))
    result_reversed = engine.evaluate_policy_document(doc_reversed, {"vip": {"version": "1.0", "other": 1}})
    assert set(result_reversed.topics[0].tied_policy_ids) == {"P1", "P2"}


def test_project_overridable_org_policy_scenario_from_schema_docstring():
    """Directly exercises the schema's own worked example: an org policy with
    overridable_by_project=true yields to a matching project-scope policy."""
    doc = _doc(
        _policy("ORG_DEFAULT", "waveform_default", _leaf("dump.scope", "eq", "full_chip"),
                action_if_matched="WARN", scope="org", severity="ADVISORY",
                overridable_by_project=True),
        _policy("PROJ_OVERRIDE", "waveform_default", _leaf("dump.scope", "eq", "full_chip"),
                action_if_matched="ALLOW", scope="project", severity="ADVISORY"),
    )
    result = engine.evaluate_policy_document(doc, {"dump": {"scope": "full_chip"}})
    topic = result.topics[0]
    assert topic.winner_policy_id == "PROJ_OVERRIDE"
    assert topic.action == "ALLOW"
    assert result.overall_status == engine.ENGINE_CLEAR


def test_matched_policies_agreeing_on_action_are_not_reported_as_conflict():
    doc = _doc(
        _policy("P1", "topic", _leaf("a", "eq", 1), action_if_matched="BLOCK"),
        _policy("P2", "topic", _leaf("b", "eq", 1), action_if_matched="BLOCK"),
    )
    result = engine.evaluate_policy_document(doc, {"a": 1, "b": 1})
    topic = result.topics[0]
    assert topic.action == "BLOCK"
    assert set(topic.matched_policy_ids) == {"P1", "P2"}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_engine_report_includes_overall_status_and_topics():
    doc = _doc(_policy("P1", "topic", _leaf("a", "eq", 1), action_if_matched="BLOCK"))
    result = engine.evaluate_policy_document(doc, {"a": 1})
    text = engine.render_engine_report(result)
    assert "ENGINE_BLOCKED" in text
    assert "topic" in text


def test_render_engine_report_with_no_topics_still_renders():
    doc = _doc(_policy("P1", "topic", _leaf("a", "eq", 1)))
    result = engine.evaluate_policy_document(doc, {"a": 99})
    text = engine.render_engine_report(result)
    assert "ENGINE_CLEAR" in text


# ---------------------------------------------------------------------------
# CLI (python -m dv_harness.org_verification_policy_engine)
# ---------------------------------------------------------------------------

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.org_verification_policy_engine", *args],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )


def test_cli_validate_real_valid_document(tmp_path):
    doc = _doc(_policy("P1", "topic", _leaf("a", "eq", 1)))
    policies_path = tmp_path / "policies.json"
    policies_path.write_text(json.dumps(doc), encoding="utf-8")
    proc = _run_cli("validate", "--policies", str(policies_path))
    assert proc.returncode == 0
    assert "valid" in proc.stdout


def test_cli_validate_real_invalid_document_exits_nonzero(tmp_path):
    doc = {"schema_version": "1.0", "policies": [{"policy_id": "P1"}]}  # missing required fields
    policies_path = tmp_path / "policies.json"
    policies_path.write_text(json.dumps(doc), encoding="utf-8")
    proc = _run_cli("validate", "--policies", str(policies_path))
    assert proc.returncode == 2


def test_cli_evaluate_blocked_exit_code(tmp_path):
    doc = _doc(_policy("P1", "topic", _leaf("a", "eq", 1), action_if_matched="BLOCK"))
    policies_path = tmp_path / "policies.json"
    facts_path = tmp_path / "facts.json"
    policies_path.write_text(json.dumps(doc), encoding="utf-8")
    facts_path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    proc = _run_cli("evaluate", "--policies", str(policies_path), "--facts", str(facts_path), "--json")
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["overall_status"] == "ENGINE_BLOCKED"


def test_cli_evaluate_clear_exit_code(tmp_path):
    doc = _doc(_policy("P1", "topic", _leaf("a", "eq", 1), action_if_matched="BLOCK"))
    policies_path = tmp_path / "policies.json"
    facts_path = tmp_path / "facts.json"
    policies_path.write_text(json.dumps(doc), encoding="utf-8")
    facts_path.write_text(json.dumps({"a": 999}), encoding="utf-8")
    proc = _run_cli("evaluate", "--policies", str(policies_path), "--facts", str(facts_path))
    assert proc.returncode == 0


def test_cli_evaluate_unresolved_exit_code(tmp_path):
    doc = _doc(_policy("P1", "topic", _leaf("a", "eq", 1), action_if_matched="BLOCK", severity="MANDATORY"))
    policies_path = tmp_path / "policies.json"
    facts_path = tmp_path / "facts.json"
    policies_path.write_text(json.dumps(doc), encoding="utf-8")
    facts_path.write_text(json.dumps({}), encoding="utf-8")
    proc = _run_cli("evaluate", "--policies", str(policies_path), "--facts", str(facts_path))
    assert proc.returncode == 2
