"""CLAUDE.md's "Waveform Dump User Gate", verified against a REAL human
answer instead of an agent-attested string (2026-09-04, AI-mechanism #12
"AI Debug Closed Loop" gap closure).

The gap these tests exist for is a WIRING gap, not a logic one, so almost
nothing here tests `verify_dump_scope_confirmation()` in isolation -- that
function working was never in question. What was: on the autonomous path
`engine.loop()` dispatches a headless `claude -p --dangerously-skip-permissions`
subprocess with no live channel back to a human, so an in-flight
AskUserQuestion cannot be answered, and the only way past the old
non-empty-string check on `dump_scope_confirmed.confirmed_by` was the LLM
filling it in itself. The gate passed exactly when nobody had been asked.

So these tests drive the real path end to end: the real gate script as a
subprocess through the real `run_gate()`/`evaluate_stage_evidence()`, and a
real `DVHarness.loop()` over the real shipped `main_graph.json` and the real
`tools/` tree, against a real `QuestionQueueStore` on disk -- never a mock
store and never a hand-built decisions.json.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dv_harness import question_queue, waveform_dump_gate
from dv_harness.gates import evaluate_stage_evidence
from dv_harness.models import Status
from dv_harness.question_queue import QuestionQueueStore

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "verification_flow" / "focused_wave_debug_window_gate.py"

SCOPE = "top.usb_dev.ctrl"
LEVEL = "signal-level, block-scoped"
HUMAN = "dv_owner"

#: A rerun payload that is technically perfect -- correct WAVE=1/FSDB_START=0,
#: a stop exactly first_error_time_us+200, killed, identity preserved, real
#: evidence hash. Everything except who confirmed the dump scope.
_BASE_RERUN = {
    "deep_debug_required": True, "wave_mode": 1, "fsdb_start_us": 0,
    "first_error_time_us": 100, "fsdb_stop_us": 300.0,
    "simulation_stopped_at_fsdb_stop": True, "job_killed_or_terminated": True,
    "identity_preserved": True, "waveform_or_fsdbreport_evidence_hash": "h1",
}


def _rerun(confirmed_by, **overrides):
    payload = dict(_BASE_RERUN, dump_scope_confirmed={
        "scope": SCOPE, "level_or_depth": LEVEL, "confirmed_by": confirmed_by})
    payload.update(overrides)
    return payload


def _evidence_text(payload):
    return f"```dv-harness-evidence:focused_wave_debug_window_gate\n{json.dumps(payload)}\n```\n"


def _run_gate(project_root, payload):
    """The real gate script, invoked exactly as gates.run_gate() invokes it:
    a subprocess with cwd=<project root> (which is how it finds the question
    queue and the governance policy) and DV_HARNESS_PACKAGE_ROOT pointing at
    the importable package."""
    infile = Path(project_root) / "_rerun_payload.json"
    infile.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(GATE), "--rerun", str(infile)],
        cwd=str(project_root), capture_output=True, text=True, timeout=60,
        env={**os.environ, "DV_HARNESS_PACKAGE_ROOT": str(ROOT)})
    return proc.returncode, json.loads((proc.stdout or "").strip() or "{}")


def _ask(project_root, store=None):
    return waveform_dump_gate.ask_dump_scope_confirmation(
        project_root, scope=SCOPE, proposed_level_or_depth=LEVEL,
        failure_cone="usb_dev.ctrl LTSSM", store=store)


def _answer(store, qid, decided_by=HUMAN):
    return store.answer_question(qid, answer=f"APPROVE scope={SCOPE} level_or_depth={LEVEL}",
                                   basis="minimum sufficient for the LTSSM failure cone",
                                   decided_by=decided_by)


# ---------------------------------------------------------------------------
# 1. The gate itself, against a real question store on disk.
# ---------------------------------------------------------------------------

def test_agent_self_attested_confirmation_cannot_pass_the_gate():
    tmp = Path(tempfile.mkdtemp())
    try:
        # Exactly what a headless subprocess produces: every required field
        # present, confirmed_by a plausible string, nobody asked. This is the
        # payload that used to PASS.
        rc, detail = _run_gate(tmp, _rerun("user"))
        assert rc != 0
        assert detail["reason"] == waveform_dump_gate.REASON_NOT_ASKED, detail
        # The failure has to be actionable, not just correct: it must name the
        # Q-ID to create and the command that creates it.
        assert detail["question_id"].startswith("Q-ENV-")
        assert "waveform-dump-scope ask" in detail["remedy"]

        # An outright missing block, and a half-filled one, are still caught
        # by the pre-existing shape checks -- and now also carry the
        # needs_user_input flag gates.py routes on.
        rc, detail = _run_gate(tmp, dict(_BASE_RERUN))
        assert rc != 0 and detail["reason"] == "WAVEFORM_DUMP_SCOPE_NOT_CONFIRMED"
        assert detail["needs_user_input"] is True
        rc, detail = _run_gate(tmp, dict(_BASE_RERUN, dump_scope_confirmed={"scope": SCOPE}))
        assert rc != 0 and detail["reason"] == "WAVEFORM_DUMP_SCOPE_CONFIRMATION_INCOMPLETE"
        assert detail["needs_user_input"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_filed_but_unanswered_question_is_distinguished_from_never_asked():
    # Two different remedies (file it vs. answer it), so two different
    # reasons. A Tier-3 question writes no decision, so "no decision on file"
    # alone cannot tell them apart -- the questions store must be consulted.
    tmp = Path(tempfile.mkdtemp())
    try:
        record = _ask(tmp)
        assert record["tier"] == question_queue.TIER3_CANNOT_ASSUME, record
        assert record["blocking"] is True and record["status"] == "OPEN"
        assert record["answer"] is None, "a Tier-3 ask must not auto-answer itself"

        rc, detail = _run_gate(tmp, _rerun(HUMAN))
        assert rc != 0
        assert detail["reason"] == waveform_dump_gate.REASON_AWAITING_ANSWER, detail
        assert record["id"] in detail["remedy"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_harness_own_tier2_assumption_never_satisfies_the_gate():
    # The failure mode this whole change exists to prevent, one level deeper:
    # a decision DOES exist for the right question_key, but the harness wrote
    # it for itself. Same rule classify_tier() and
    # connectivity.apply_answered_questions() already apply -- reused, not
    # re-implemented, so there is one notion of "a human confirmed this".
    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        store.add_question(
            domain=waveform_dump_gate.WAVEFORM_DUMP_DOMAIN,
            question=waveform_dump_gate.WAVEFORM_DUMP_QUESTION,
            context_path=waveform_dump_gate.dump_scope_context_path(SCOPE),
            question_key=waveform_dump_gate.dump_scope_question_key(SCOPE),
            options=["APPROVE", "NARROW"], recommendation="APPROVE",
            assumption_if_unanswered="APPROVE",
            # A low-blast-radius framing is what makes classify_tier() mint a
            # Tier-2 auto-assumption instead of escalating.
            context={"blast_radius": "single_regression"})

        decision = store.find_decision(waveform_dump_gate.dump_scope_question_key(SCOPE))
        assert decision["current"]["source"] == "tier2_auto_assumption"

        rc, detail = _run_gate(tmp, _rerun("dv_harness.question_queue(auto)"))
        assert rc != 0
        assert detail["reason"] == waveform_dump_gate.REASON_NOT_HUMAN_ANSWERED, detail
        assert detail["decision_source"] == "tier2_auto_assumption"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_gate_passes_only_on_a_real_human_answer_correctly_attributed():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        record = _ask(tmp, store=store)
        _answer(store, record["id"])

        # Answered by dv_owner, but the block credits someone else: a real
        # decision cited with a false attribution is still not a confirmation.
        rc, detail = _run_gate(tmp, _rerun("someone_else"))
        assert rc != 0
        assert detail["reason"] == waveform_dump_gate.REASON_CONFIRMED_BY_MISMATCH, detail
        assert detail["decided_by"] == HUMAN

        rc, detail = _run_gate(tmp, _rerun(HUMAN))
        assert rc == 0 and detail["status"] == "PASS", detail

        # Attribution matching is case-insensitive, not case-fragile.
        rc, _ = _run_gate(tmp, _rerun(HUMAN.upper()))
        assert rc == 0

        # A different scope is a different decision -- one confirmation does
        # not silently authorize dumping something wider.
        wider = _rerun(HUMAN)
        wider["dump_scope_confirmed"]["scope"] = "top"
        rc, detail = _run_gate(tmp, wider)
        assert rc != 0 and detail["reason"] == waveform_dump_gate.REASON_NOT_ASKED, detail
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_window_and_kill_rules_still_enforced_after_a_real_confirmation():
    # The confirmation check must not have displaced the mechanics this gate
    # already enforced. With a genuine human answer on file, the FSDB window
    # math, the stop and the kill are all still checked.
    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        _answer(store, _ask(tmp, store=store)["id"])

        rc, detail = _run_gate(tmp, _rerun(HUMAN, fsdb_stop_us=5000))
        assert rc != 0 and detail["reason"] == "INVALID_FOCUSED_FSDB_STOP_WINDOW"
        assert detail["expected_stop_us"] == 300.0

        rc, detail = _run_gate(tmp, _rerun(HUMAN, job_killed_or_terminated=False))
        assert rc != 0 and detail["reason"] == "JOB_NOT_KILLED_AFTER_FOCUSED_CAPTURE"

        # The "cheap evidence was enough, no waveform at all" escape hatch is
        # unaffected: it never opens a dump, so it never needs a confirmation.
        rc, detail = _run_gate(tmp, {"deep_debug_required": False,
                                      "deep_debug_not_required_reason": "UVM_ERROR text was conclusive"})
        assert rc == 0 and detail["status"] == "PASS"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 2. The wiring: an unconfirmed dump scope must stop the REAL autonomous loop.
# ---------------------------------------------------------------------------

def _mk_project():
    """A temp project with the REAL shipped graph, agent profiles and gate
    scripts, so run_stage()/loop() execute the real gate subprocess rather
    than a stand-in."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


class _FakeAdapter:
    """Stands in for the headless `claude -p` subprocess: it returns a fixed
    response and, crucially, records how many times the loop dispatched it."""

    def __init__(self, text):
        self.text = text
        self.calls = 0

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        from dv_harness.adapters.base import AgentResult
        self.calls += 1
        return AgentResult(ok=True, text=self.text, raw={}, session_id="sess-1")


def test_unconfirmed_dump_scope_stops_the_real_loop_at_wait_user_without_retrying():
    from dv_harness.engine import DVHarness

    tmp = _mk_project()
    try:
        h = DVHarness(tmp)
        # A self-attested confirmation -- the best a headless subprocess can
        # do, and what it will keep producing however many times it is re-run.
        h.adapter = _FakeAdapter("targeted rerun done.\n" + _evidence_text(_rerun("user")))
        h.set_stage("WAVE_ANALYSIS")
        h.loop("root-cause the LTSSM timeout")

        ss = h.state.stages["WAVE_ANALYSIS"]
        assert ss["status"] == Status.WAIT_USER.value, ss
        assert h.state.overall_status == Status.WAIT_USER.value

        # The stop must tell the human exactly what to answer.
        reason = ss["blocking_reason"]
        assert "NEEDS_USER_INPUT" in reason
        expected_qid = question_queue.make_question_id(
            waveform_dump_gate.WAVEFORM_DUMP_DOMAIN, waveform_dump_gate.dump_scope_question_key(SCOPE))
        assert expected_qid in reason, reason
        assert "waveform-dump-scope ask" in reason, reason

        # This is the half that a plain GATE_FAIL would have got wrong: a
        # question no human can answer mid-run must not burn max_stage_retries
        # first and then take the graph's FAIL edge with the question still
        # open. Exactly one dispatch, and the loop is still parked here.
        assert h.adapter.calls == 1, f"loop retried an unanswerable question {h.adapter.calls} times"
        assert h.state.current_stage == "WAVE_ANALYSIS"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_loop_gets_past_the_gate_once_a_real_human_answers():
    # The other half of the same wire: the WAIT_USER stop is a resumable
    # checkpoint, not a dead end. Same project, same evidence mechanics, one
    # real `question-queue answer` in between.
    from dv_harness.engine import DVHarness

    tmp = _mk_project()
    try:
        h = DVHarness(tmp)
        store = QuestionQueueStore(tmp, blackboard=h.blackboard)
        record = _ask(tmp, store=store)
        _answer(store, record["id"])

        h.adapter = _FakeAdapter("targeted rerun done.\n" + _evidence_text(_rerun(HUMAN)))
        h.set_stage("WAVE_ANALYSIS")
        h.run_stage("root-cause the LTSSM timeout")

        assert h.state.stages["WAVE_ANALYSIS"]["status"] == Status.PASS.value, \
            h.state.stages["WAVE_ANALYSIS"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. The ASK half on the AUTONOMOUS path: parking at WAIT_USER is only half a
#    round-trip if the question the run is blocked on was never filed.
#    `waveform_dump_gate.ask_dump_scope_confirmation()` had exactly one caller
#    in the repo -- cli.py's human-typed `dv-harness waveform-dump-scope ask`
#    -- so a headless `claude -p` run that did not shell out to it left the
#    human an EMPTY queue and a blocking_reason to hand-reconstruct the ask
#    from. engine._file_waveform_dump_scope_question() closes that.
# ---------------------------------------------------------------------------

def _filed_events(root):
    p = Path(root) / ".dv-harness" / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("event") == "WAVEFORM_DUMP_SCOPE_QUESTION_FILED"]


def test_autonomous_loop_files_the_question_it_parks_on_and_a_human_answer_closes_it():
    """The full round-trip, all of it on the real path: real shipped graph,
    real gate subprocess, real QuestionQueueStore on disk. Nothing hand-files
    the question -- `loop()` does -- and the answer is given against the Q-ID
    the ENGINE minted, not one the test constructed."""
    from dv_harness.engine import DVHarness

    tmp = _mk_project()
    try:
        h = DVHarness(tmp)
        store = QuestionQueueStore(tmp, blackboard=h.blackboard)
        assert store.list_questions() == [], "precondition: the queue starts empty"

        # The best a headless subprocess can do: a self-attested confirmation.
        h.adapter = _FakeAdapter("targeted rerun done.\n" + _evidence_text(_rerun("user")))
        h.set_stage("WAVE_ANALYSIS")
        h.loop("root-cause the LTSSM timeout")

        assert h.state.stages["WAVE_ANALYSIS"]["status"] == Status.WAIT_USER.value
        assert h.adapter.calls == 1, "an unanswerable question must still not be retried"

        # The gap: before this wiring the queue was still empty here.
        filed = store.list_questions()
        assert len(filed) == 1, filed
        q = filed[0]
        assert q["id"] == question_queue.make_question_id(
            waveform_dump_gate.WAVEFORM_DUMP_DOMAIN,
            waveform_dump_gate.dump_scope_question_key(SCOPE)), q
        assert q["tier"] == question_queue.TIER3_CANNOT_ASSUME and q["blocking"] is True
        assert q["status"] == "OPEN" and q["answer"] is None
        # It describes the dump the AGENT actually proposed, read off the very
        # evidence block the gate just rejected -- not a placeholder.
        assert q["context_path"] == waveform_dump_gate.dump_scope_context_path(SCOPE)
        assert SCOPE in q["recommendation"] and LEVEL in q["recommendation"]
        # And it is the queue's own blocking view, i.e. what a digest reports.
        assert [b["id"] for b in store.list_questions(blocking=True, status="OPEN")] == [q["id"]]

        # The park now names the ONE command that unblocks the run.
        reason = h.state.stages["WAVE_ANALYSIS"]["blocking_reason"]
        assert f"question-queue answer {q['id']}" in reason, reason

        # Real audit trail, not just state.
        events = _filed_events(tmp)
        assert len(events) == 1 and events[0]["question_id"] == q["id"], events
        assert events[0]["scope"] == SCOPE and events[0]["level_or_depth"] == LEVEL

        # The human answers the ENGINE-minted Q-ID. Nothing else changes.
        _answer(store, q["id"])
        h.adapter = _FakeAdapter("targeted rerun done.\n" + _evidence_text(_rerun(HUMAN)))
        h.run_stage("root-cause the LTSSM timeout")
        assert h.state.stages["WAVE_ANALYSIS"]["status"] == Status.PASS.value, \
            h.state.stages["WAVE_ANALYSIS"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_question_already_waiting_is_not_re_filed_by_a_second_loop_pass():
    # add_question() APPENDS rather than deduping on the derived id, so an
    # unconditional re-file would grow duplicate records and re-arm
    # digest_batch_id for a question a human is already sitting on. This is
    # verify_dump_scope_confirmation()'s REASON_AWAITING_ANSWER case, and the
    # engine uses the identical "is it already on file" predicate.
    from dv_harness.engine import DVHarness

    tmp = _mk_project()
    try:
        h = DVHarness(tmp)
        store = QuestionQueueStore(tmp, blackboard=h.blackboard)
        already = _ask(tmp, store=store)

        h.adapter = _FakeAdapter("targeted rerun done.\n" + _evidence_text(_rerun("user")))
        h.set_stage("WAVE_ANALYSIS")
        h.loop("root-cause the LTSSM timeout")
        h.loop("root-cause the LTSSM timeout")

        assert h.state.stages["WAVE_ANALYSIS"]["status"] == Status.WAIT_USER.value
        ids = [q["id"] for q in store.list_questions()]
        assert ids == [already["id"]], ids
        assert _filed_events(tmp) == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_nothing_is_filed_when_the_agent_declared_no_scope_or_no_level():
    # WAVEFORM_DUMP_SCOPE_NOT_CONFIRMED / _CONFIRMATION_INCOMPLETE are agent
    # error, not a missing human decision: a question that cannot say what
    # dump is proposed cannot be answered yes/no. The loop must still park
    # (that behavior is unchanged), but it must not file an unanswerable
    # question -- and it must not file a WAVEFORM question for an unrelated
    # stage's NEEDS_USER_INPUT either.
    from dv_harness.engine import DVHarness

    for payload in (dict(_BASE_RERUN),
                    dict(_BASE_RERUN, dump_scope_confirmed={"scope": SCOPE}),
                    dict(_BASE_RERUN, dump_scope_confirmed={"level_or_depth": LEVEL})):
        tmp = _mk_project()
        try:
            h = DVHarness(tmp)
            h.adapter = _FakeAdapter("targeted rerun done.\n" + _evidence_text(payload))
            h.set_stage("WAVE_ANALYSIS")
            h.loop("root-cause the LTSSM timeout")

            assert h.state.stages["WAVE_ANALYSIS"]["status"] == Status.WAIT_USER.value, payload
            assert QuestionQueueStore(tmp).list_questions() == [], payload
            assert _filed_events(tmp) == [], payload
            # An INTAKE-shaped NEEDS_USER_INPUT carries no waveform block at
            # all, so the same helper is a no-op for it.
            assert h._file_waveform_dump_scope_question("INTAKE", {}) is None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def test_stage_evaluation_routes_dump_scope_stalls_to_needs_user_input():
    # The gates.py half in isolation, against the real ROOT (which has no
    # question store, so nothing here can be confirmed): every dump-scope
    # confirmation shape must reach the NEEDS_USER_INPUT verdict that
    # engine.run_stage() maps to WAIT_USER -- while an unrelated failure of
    # the SAME gate stays an ordinary GATE_FAIL the agent is expected to fix.
    for payload in (dict(_BASE_RERUN), _rerun("user"),
                    dict(_BASE_RERUN, dump_scope_confirmed={"scope": SCOPE})):
        verdict, reasons = evaluate_stage_evidence(ROOT, "WAVE_ANALYSIS", _evidence_text(payload))
        assert verdict == "NEEDS_USER_INPUT", (payload, verdict, reasons)

    not_a_user_question = dict(_BASE_RERUN)
    not_a_user_question.pop("deep_debug_required")
    verdict, reasons = evaluate_stage_evidence(ROOT, "WAVE_ANALYSIS", _evidence_text(not_a_user_question))
    assert verdict == "GATE_FAIL", (verdict, reasons)
    assert any("FOCUSED_WAVE_RERUN_WITHOUT_NEED" in str(r) for r in reasons)
