"""dv_harness/question_why_grounding.py -- a thin, explicitly-named wrapper
over question_queue.request_clarification()/build_escalation_package(),
closing CLAUDE.md's own "'Why Am I Being Asked This' Grounding" disclosed
residual.

Every test drives a REAL `QuestionQueueStore` on `tmp_path`, populated
through the real `add_question()` API -- never a hand-typed record --
mirroring `test_question_queue.py`'s own `request_clarification()` test
class this module reuses.
"""
from __future__ import annotations

import ast
import json

import pytest

from dv_harness.question_queue import QuestionQueueStore, build_escalation_package
from dv_harness.question_why_grounding import (
    QuestionWhyGroundingError,
    explain_why_asked,
    execute_verb,
    render_why_asked_markdown,
)


def _opts():
    return [
        {"label": "Configure as bus slave/responder",
         "rationale": "DUT port direction at this boundary is master-only."},
        {"label": "Configure as bus master/initiator",
         "rationale": "fallback if DUT is actually the responder."},
    ]


def _tier3_question(store):
    return store.add_question(
        domain="dut", question="Is this DUT boundary master or slave?",
        context_path="rtl/usb3_link_ctrl.v:120", options=_opts(),
        recommendation="Configure as bus slave/responder",
        assumption_if_unanswered="assume slave (single regression)",
        context={"affects_pass_fail_verdict": True},  # Tier-3
    )


def test_explain_why_asked_reuses_request_clarifications_own_computation(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = _tier3_question(store)

    explanation = explain_why_asked(store, q["id"])

    assert explanation["question_id"] == q["id"]
    # No new evidence/plain-English logic exists here -- this module's own
    # values must be exactly request_clarification()'s real real output.
    assert explanation["package"] == build_escalation_package(q)
    assert any(line == f"Question: {q['question']}" for line in explanation["why"])
    assert any("PASS or FAIL" in line for line in explanation["why"])
    for opt in q["options"]:
        assert any(opt["label"] in line and opt["rationale"] in line
                   for line in explanation["evidence"])


def test_explain_why_asked_never_writes_the_clarifications_file(tmp_path):
    """The headline distinction from request_clarification()'s own default
    (record=True): this is a PROACTIVE "why" render, never a "a human
    signaled confusion" event -- it must never mint or append to
    store.clarifications_path."""
    store = QuestionQueueStore(tmp_path)
    q = _tier3_question(store)

    explain_why_asked(store, q["id"])
    assert not store.clarifications_path.exists()

    # Calling it twice still writes nothing.
    explain_why_asked(store, q["id"])
    assert not store.clarifications_path.exists()


def test_explain_why_asked_never_mutates_the_question_record(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = _tier3_question(store)
    before = store.questions_path.read_text(encoding="utf-8")

    explain_why_asked(store, q["id"])

    after = store.questions_path.read_text(encoding="utf-8")
    assert before == after
    assert len(json.loads(after)["questions"]) == 1


def test_explain_why_asked_unknown_id_raises_the_named_error(tmp_path):
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(QuestionWhyGroundingError):
        explain_why_asked(store, "Q-DUT-00000000")


def test_explain_why_asked_never_fabricates_a_missing_option_rationale(tmp_path):
    # Negative control, mirroring request_clarification()'s own: an option
    # with no rationale on file must be reported as honestly absent, never
    # filled in with an invented explanation.
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p",
        options=["bare label a", "bare label b"],
        recommendation="bare label a", assumption_if_unanswered="a",
        context={"affects_pass_fail_verdict": True},
    )
    explanation = explain_why_asked(store, q["id"])
    assert "bare label a: (no additional rationale on file)" in explanation["evidence"]
    assert "bare label b: (no additional rationale on file)" in explanation["evidence"]


def test_explain_why_asked_tier2_notes_it_is_a_machine_guess(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="q", context_path="p", options=_opts(),
        recommendation="Configure as bus slave/responder", assumption_if_unanswered="a",
        context={},  # no hard trigger, low blast radius -> Tier-2 auto-assume
    )
    explanation = explain_why_asked(store, q["id"])
    assert any("machine guess, not a human answer" in line for line in explanation["why"])


def test_render_why_asked_markdown_carries_the_real_fields(tmp_path):
    store = QuestionQueueStore(tmp_path)
    q = _tier3_question(store)
    explanation = explain_why_asked(store, q["id"])

    text = render_why_asked_markdown(explanation)
    assert f"Why you're being asked: {q['id']}" in text
    assert "In plain terms:" in text
    assert "Evidence already found, per option:" in text
    assert q["recommendation"] in text
    for line in explanation["why"]:
        assert line in text
    for line in explanation["evidence"]:
        assert line in text


def test_module_never_writes_to_questions_or_clarifications_files():
    """Structural guard: this module's own source contains no write-shaped
    call to either store artifact -- mirroring the same AST-based
    never-writes proof several sibling read-only modules in this project
    already establish for themselves."""
    import dv_harness.question_why_grounding as qwg

    src = open(qwg.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    forbidden = {"add_question", "answer_question", "revoke_decision",
                 "add_decision_cosign", "_atomic_write_json"}
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            called.add(node.attr)
        elif isinstance(node, ast.Name):
            called.add(node.id)
    assert not (called & forbidden), f"forbidden write call(s) found: {called & forbidden}"


def test_cli_explain_prints_json_and_exits_zero(tmp_path, capsys):
    store = QuestionQueueStore(tmp_path)
    q = _tier3_question(store)

    rc = execute_verb(["explain", "--root", str(tmp_path), "--question-id", q["id"], "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["question_id"] == q["id"]
    assert not store.clarifications_path.exists()


def test_cli_explain_default_renders_markdown(tmp_path, capsys):
    store = QuestionQueueStore(tmp_path)
    q = _tier3_question(store)

    rc = execute_verb(["explain", "--root", str(tmp_path), "--question-id", q["id"]])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"Why you're being asked: {q['id']}" in out


def test_cli_explain_unknown_id_exits_two(tmp_path, capsys):
    rc = execute_verb(["explain", "--root", str(tmp_path), "--question-id", "Q-DUT-00000000"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "REFUSED"
