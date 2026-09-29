"""Real tests for dv_harness/first_time_user_onboarding.py.

Every fixture is built through the REAL producers this module reuses:
`dv_harness.storage.StateStore.event()` for CLI_ACCESS access-history
records (the exact call `cli.py` itself makes), and
`dv_harness.question_queue.QuestionQueueStore.add_question()` /
`answer_question()` for real question/decision records -- never a
hand-written events.jsonl line or decisions.json entry standing in for
what those real writers would produce.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dv_harness.storage import StateStore
from dv_harness.question_queue import QuestionQueueStore
import dv_harness.first_time_user_onboarding as ftuo


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _log_access(root: Path, user: str, ts: float) -> None:
    """Exactly what cli.py's own CLI_ACCESS logging does (see
    cli.py: `h.store.event({"ts": ..., "event": "CLI_ACCESS", ...})`)."""
    StateStore(root).event({"ts": ts, "event": "CLI_ACCESS", "cmd": "status",
                             "user": user, "host": "test-host"})


def _ask_tier3_question(store: QuestionQueueStore, *, question_key: str = "q-tier3") -> dict:
    """A real Tier-3 (cannot-assume) question: OPEN, blocking, requires a
    real human answer before it self-resolves."""
    return store.add_question(
        domain="env",
        question="Does dropping this transaction here match spec intent?",
        context_path="env.manifest.json#dut_facts.rtl.some_signal",
        options=["Yes, spec-legal drop", "No, a real DUT bug"],
        recommendation="Yes, spec-legal drop",
        assumption_if_unanswered="Treat as spec-legal until a human says otherwise.",
        question_key=question_key,
        context={"affects_spec_intent": True},
    )


def _ask_tier2_question(store: QuestionQueueStore, *, question_key: str = "q-tier2") -> dict:
    """A real Tier-2 (safe-to-assume) question: no hard trigger, low blast
    radius -> ASSUMED immediately, decided_by is the harness's own guess,
    never a human -- the negative-control fixture for
    real_prior_decisions_by_user()."""
    return store.add_question(
        domain="env",
        question="Is the default clock divider value acceptable for this smoke test?",
        context_path="env.manifest.json#dut_facts.rtl.clk_div",
        options=["Yes, default is fine", "No, override it"],
        recommendation="Yes, default is fine",
        assumption_if_unanswered="Use the default clock divider.",
        question_key=question_key,
        context={},
    )


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

def test_vocabulary_has_no_duplicates_and_matches_status_set():
    assert len(ftuo.DETECTION_STATUSES) == len(set(ftuo.DETECTION_STATUSES)) == 6
    assert ftuo.UNKNOWN_INSUFFICIENT_EVIDENCE in ftuo._EXPLANATORY_STATUSES
    assert ftuo.RETURNING_ANSWERED_BEFORE not in ftuo._EXPLANATORY_STATUSES
    # re-run the collision guard directly -- proves it does not merely pass
    # once at import time by accident
    ftuo.assert_no_verification_verdict_vocabulary()


def test_vocabulary_collision_guard_has_real_detection_power(monkeypatch):
    monkeypatch.setattr(ftuo, "DETECTION_STATUSES", ftuo.DETECTION_STATUSES + ("PASS",))
    with pytest.raises(AssertionError):
        ftuo.assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# sibling_harness_project_count
# ---------------------------------------------------------------------------

def test_sibling_project_count_excludes_root_and_non_harness_dirs(tmp_path: Path):
    parent = tmp_path / "workspace"
    root = parent / "proj_a"
    root.mkdir(parents=True)
    (root / ".dv-harness").mkdir()

    sib1 = parent / "proj_b"
    sib1.mkdir()
    (sib1 / ".dv-harness").mkdir()

    sib2 = parent / "not_a_harness_project"
    sib2.mkdir()  # no .dv-harness

    unrelated_file = parent / "readme.txt"
    unrelated_file.write_text("x", encoding="utf-8")

    count = ftuo.sibling_harness_project_count(root)
    assert count == 1  # only proj_b


def test_sibling_project_count_zero_with_no_siblings(tmp_path: Path):
    root = tmp_path / "lone_project"
    root.mkdir()
    (root / ".dv-harness").mkdir()
    assert ftuo.sibling_harness_project_count(root) == 0


def test_sibling_project_count_nonexistent_parent_is_honest_zero(tmp_path: Path):
    root = tmp_path / "does_not_exist_parent" / "proj"
    # root's own parent does not exist at all
    count = ftuo.sibling_harness_project_count(root)
    assert count == 0


def test_sibling_project_count_honors_explicit_parent_override(tmp_path: Path):
    root = tmp_path / "elsewhere" / "proj"
    root.mkdir(parents=True)
    scan_parent = tmp_path / "workspace"
    scan_parent.mkdir()
    other = scan_parent / "other_proj"
    other.mkdir()
    (other / ".dv-harness").mkdir()
    assert ftuo.sibling_harness_project_count(root, parent=scan_parent) == 1


# ---------------------------------------------------------------------------
# real_prior_decisions_by_user
# ---------------------------------------------------------------------------

def test_real_prior_decisions_by_user_finds_a_real_human_answer(tmp_path: Path):
    store = QuestionQueueStore(tmp_path)
    q = _ask_tier3_question(store, question_key="q-answered")
    assert q["status"] == "OPEN"
    store.answer_question(q["id"], answer="Yes, spec-legal drop",
                           basis="spec section 4.2 permits this drop",
                           decided_by="alice")

    hits = ftuo.real_prior_decisions_by_user(store, "alice")
    assert len(hits) == 1
    assert hits[0]["question_key"] == "q-answered"

    # a different user gets nothing
    assert ftuo.real_prior_decisions_by_user(store, "bob") == []


def test_real_prior_decisions_by_user_never_counts_a_tier2_auto_assumption(tmp_path: Path):
    """The negative control this module's own docstring names: a Tier-2
    auto-assumption is the harness's own guess, never evidence a HUMAN
    (any human) has answered anything."""
    store = QuestionQueueStore(tmp_path)
    q = _ask_tier2_question(store, question_key="q-assumed")
    assert q["status"] == "ASSUMED"
    assert q["decided_by"] == "dv_harness.question_queue(auto)"

    hits = ftuo.real_prior_decisions_by_user(store, "dv_harness.question_queue(auto)")
    assert hits == []
    hits_any_user = ftuo.real_prior_decisions_by_user(store, "alice")
    assert hits_any_user == []


# ---------------------------------------------------------------------------
# user_access_summary
# ---------------------------------------------------------------------------

def test_user_access_summary_none_when_nothing_recorded_at_all(tmp_path: Path):
    assert ftuo.user_access_summary(tmp_path, "alice") is None


def test_user_access_summary_reflects_real_logged_sessions(tmp_path: Path):
    _log_access(tmp_path, "alice", 1_000_000.0)
    summary = ftuo.user_access_summary(tmp_path, "alice")
    assert summary is not None
    assert summary["user"] == "alice"
    assert summary["session_count"] == 1

    # a second event far enough apart (> SESSION_GAP_SECONDS) starts a new
    # real, separate session
    from dv_harness.user_info import SESSION_GAP_SECONDS
    _log_access(tmp_path, "alice", 1_000_000.0 + SESSION_GAP_SECONDS + 100.0)
    summary2 = ftuo.user_access_summary(tmp_path, "alice")
    assert summary2["session_count"] == 2

    # an unrelated user still has no record
    assert ftuo.user_access_summary(tmp_path, "carol") is None


# ---------------------------------------------------------------------------
# detect_first_time_user -- the full evidence hierarchy
# ---------------------------------------------------------------------------

def test_detect_returning_answered_before_outranks_everything(tmp_path: Path):
    store = QuestionQueueStore(tmp_path)
    q = _ask_tier3_question(store)
    store.answer_question(q["id"], answer="Yes, spec-legal drop",
                           basis="cited in the spec", decided_by="alice")
    # even with only ONE access-history session on file (which alone would
    # read FIRST_TIME_ACCESS_HISTORY), a real prior decision wins.
    _log_access(tmp_path, "alice", 1_000_000.0)

    detection = ftuo.detect_first_time_user(tmp_path, "alice", store=store)
    assert detection["status"] == ftuo.RETURNING_ANSWERED_BEFORE
    assert detection["rendering_mode"] == ftuo.RENDERING_STANDARD
    assert ftuo.should_use_explanatory_rendering(detection) is False
    assert len(detection["evidence"]["prior_decisions_by_user"]) == 1


def test_detect_first_time_access_history_single_session_no_decision(tmp_path: Path):
    store = QuestionQueueStore(tmp_path)
    _log_access(tmp_path, "alice", 1_000_000.0)

    detection = ftuo.detect_first_time_user(tmp_path, "alice", store=store)
    assert detection["status"] == ftuo.FIRST_TIME_ACCESS_HISTORY
    assert detection["rendering_mode"] == ftuo.RENDERING_EXPLANATORY
    assert ftuo.should_use_explanatory_rendering(detection) is True


def test_detect_returning_access_history_two_sessions_no_decision(tmp_path: Path):
    from dv_harness.user_info import SESSION_GAP_SECONDS
    store = QuestionQueueStore(tmp_path)
    _log_access(tmp_path, "alice", 1_000_000.0)
    _log_access(tmp_path, "alice", 1_000_000.0 + SESSION_GAP_SECONDS + 500.0)

    detection = ftuo.detect_first_time_user(tmp_path, "alice", store=store)
    assert detection["status"] == ftuo.RETURNING_ACCESS_HISTORY
    assert detection["rendering_mode"] == ftuo.RENDERING_STANDARD


def test_detect_first_time_heuristic_no_evidence_anywhere(tmp_path: Path):
    workspace = tmp_path / "workspace"
    root = workspace / "proj"
    root.mkdir(parents=True)
    store = QuestionQueueStore(root)

    detection = ftuo.detect_first_time_user(root, "alice", store=store)
    assert detection["status"] == ftuo.FIRST_TIME_HEURISTIC
    assert detection["rendering_mode"] == ftuo.RENDERING_EXPLANATORY
    assert detection["evidence"]["sibling_harness_project_count"] == 0


def test_detect_returning_heuristic_sibling_project_exists(tmp_path: Path):
    workspace = tmp_path / "workspace"
    root = workspace / "proj_a"
    root.mkdir(parents=True)
    sib = workspace / "proj_b"
    sib.mkdir()
    (sib / ".dv-harness").mkdir()
    store = QuestionQueueStore(root)

    detection = ftuo.detect_first_time_user(root, "alice", store=store)
    assert detection["status"] == ftuo.RETURNING_HEURISTIC
    assert detection["rendering_mode"] == ftuo.RENDERING_STANDARD
    assert detection["evidence"]["sibling_harness_project_count"] == 1


def test_detect_default_user_is_env_var_driven(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("USER", "envuser")
    monkeypatch.delenv("USERNAME", raising=False)
    root = tmp_path / "proj"
    root.mkdir()
    detection = ftuo.detect_first_time_user(root)
    assert detection["user"] == "envuser"


# ---------------------------------------------------------------------------
# The required negative control: a genuine read failure on BOTH stronger
# evidence sources is honestly UNKNOWN, never guessed toward either side.
# ---------------------------------------------------------------------------

def test_detect_unknown_insufficient_evidence_on_real_read_failures(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()

    # Corrupt decisions.json for real (question_queue._read_json parses the
    # whole file as one JSON document, so malformed text really raises).
    qdir = root / ".dv-harness" / "question_queue"
    qdir.mkdir(parents=True)
    (qdir / "decisions.json").write_text("{ this is not valid json", encoding="utf-8")

    # Make events.jsonl unreadable for real: a directory in its place makes
    # opening it for text reading raise (PermissionError on Windows,
    # IsADirectoryError on POSIX -- both real OSError subclasses, no mock).
    dvdir = root / ".dv-harness"
    (dvdir / "events.jsonl").mkdir()

    detection = ftuo.detect_first_time_user(root, "alice")
    assert detection["status"] == ftuo.UNKNOWN_INSUFFICIENT_EVIDENCE
    assert detection["rendering_mode"] == ftuo.RENDERING_EXPLANATORY
    assert "decisions_read_error" in detection["evidence"]
    assert "access_history_read_error" in detection["evidence"]
    # never fabricated toward either RETURNING or FIRST_TIME
    assert detection["status"] not in (
        ftuo.RETURNING_ANSWERED_BEFORE, ftuo.RETURNING_ACCESS_HISTORY,
        ftuo.RETURNING_HEURISTIC, ftuo.FIRST_TIME_ACCESS_HISTORY,
        ftuo.FIRST_TIME_HEURISTIC,
    )


def test_a_decisions_read_failure_alone_still_falls_through_to_access_history(tmp_path: Path):
    """One real read failure (decisions.json) does NOT alone force UNKNOWN
    -- the module still consults the other real evidence source (access
    history) rather than giving up early."""
    root = tmp_path / "proj"
    root.mkdir()
    qdir = root / ".dv-harness" / "question_queue"
    qdir.mkdir(parents=True)
    (qdir / "decisions.json").write_text("{ not json", encoding="utf-8")

    from dv_harness.user_info import SESSION_GAP_SECONDS
    _log_access(root, "alice", 1_000_000.0)
    _log_access(root, "alice", 1_000_000.0 + SESSION_GAP_SECONDS + 10.0)

    detection = ftuo.detect_first_time_user(root, "alice")
    assert detection["status"] == ftuo.RETURNING_ACCESS_HISTORY
    assert "decisions_read_error" in detection["evidence"]


# ---------------------------------------------------------------------------
# Adapted question rendering
# ---------------------------------------------------------------------------

def test_render_question_for_user_standard_mode_matches_escalation_package(tmp_path: Path):
    from dv_harness.question_queue import build_escalation_package
    store = QuestionQueueStore(tmp_path)
    q = _ask_tier3_question(store)

    rendering = ftuo.render_question_for_user(store, q["id"], explanatory=False)
    assert rendering["rendering_mode"] == ftuo.RENDERING_STANDARD
    assert rendering["package"] == build_escalation_package(store.get_question(q["id"]))
    # standard rendering carries none of the explanatory fields
    assert "plain_summary" not in rendering
    assert "evidence" not in rendering


def test_render_question_for_user_explanatory_mode_reuses_request_clarification(tmp_path: Path):
    store = QuestionQueueStore(tmp_path)
    q = _ask_tier3_question(store)

    rendering = ftuo.render_question_for_user(store, q["id"], explanatory=True)
    assert rendering["rendering_mode"] == ftuo.RENDERING_EXPLANATORY
    assert rendering["question_id"] == q["id"]
    assert rendering["plain_summary"]
    assert rendering["evidence"]
    assert rendering["package"]["question_id"] == q["id"]


def test_explanatory_auto_rendering_never_writes_a_clarification_audit_entry(tmp_path: Path):
    """record=False is load-bearing: an automatic onboarding rendering must
    never be indistinguishable, in the real audit trail, from a human who
    actually asked "I don't understand this"."""
    from dv_harness.question_queue import list_clarification_requests
    store = QuestionQueueStore(tmp_path)
    q = _ask_tier3_question(store)

    ftuo.render_question_for_user(store, q["id"], explanatory=True)
    assert list_clarification_requests(store) == []
    assert not store.clarifications_path.exists()


def test_render_question_for_user_raises_keyerror_on_unknown_question(tmp_path: Path):
    store = QuestionQueueStore(tmp_path)
    with pytest.raises(KeyError):
        ftuo.render_question_for_user(store, "Q-ENV-DEADBEEF", explanatory=False)
    with pytest.raises(KeyError):
        ftuo.render_question_for_user(store, "Q-ENV-DEADBEEF", explanatory=True)


def test_render_question_markdown_standard_vs_explanatory(tmp_path: Path):
    store = QuestionQueueStore(tmp_path)
    q = _ask_tier3_question(store)

    standard = ftuo.render_question_for_user(store, q["id"], explanatory=False)
    md_standard = ftuo.render_question_markdown(standard)
    assert "Why we're asking" not in md_standard
    assert q["id"] in md_standard

    explanatory = ftuo.render_question_for_user(store, q["id"], explanatory=True)
    md_explanatory = ftuo.render_question_markdown(explanatory)
    assert "Why we're asking, in plain terms" in md_explanatory
    assert "Evidence behind each option" in md_explanatory
    assert "first time answering" in md_explanatory
    # the explanatory rendering still carries the same core 9-field block
    assert q["id"] in md_explanatory


# ---------------------------------------------------------------------------
# End-to-end: detector + rendering wired together
# ---------------------------------------------------------------------------

def test_render_questions_for_user_end_to_end_first_time(tmp_path: Path):
    # An isolated child of its own empty parent, matching
    # test_detect_first_time_heuristic_no_evidence_anywhere -- tmp_path
    # itself is shared across every test in this pytest session, and other
    # tests' own tmp dirs (siblings under tmp_path.parent) really do create
    # `.dv-harness` trees, which would otherwise pollute the project-count
    # heuristic this test is exercising.
    workspace = tmp_path / "workspace"
    root = workspace / "proj"
    root.mkdir(parents=True)
    store = QuestionQueueStore(root)
    q1 = _ask_tier3_question(store, question_key="q1")
    q2 = _ask_tier2_question(store, question_key="q2")  # ASSUMED, still "on file"

    result = ftuo.render_questions_for_user(root, user="alice", store=store)
    assert result["detection"]["status"] == ftuo.FIRST_TIME_HEURISTIC
    assert result["rendering_mode"] == ftuo.RENDERING_EXPLANATORY
    ids = {r["question_id"] for r in result["renderings"]}
    assert ids == {q1["id"], q2["id"]}
    for r in result["renderings"]:
        assert r["rendering_mode"] == ftuo.RENDERING_EXPLANATORY


def test_render_questions_for_user_end_to_end_returning(tmp_path: Path):
    store = QuestionQueueStore(tmp_path)
    prior = _ask_tier3_question(store, question_key="q-prior")
    store.answer_question(prior["id"], answer="Yes, spec-legal drop",
                           basis="spec citation", decided_by="alice")
    q_new = _ask_tier3_question(store, question_key="q-new")

    result = ftuo.render_questions_for_user(tmp_path, user="alice", store=store)
    assert result["detection"]["status"] == ftuo.RETURNING_ANSWERED_BEFORE
    assert result["rendering_mode"] == ftuo.RENDERING_STANDARD
    # only the still-open question is rendered (the prior one is ANSWERED,
    # not OPEN/ASSUMED)
    ids = {r["question_id"] for r in result["renderings"]}
    assert ids == {q_new["id"]}
    assert result["renderings"][0]["rendering_mode"] == ftuo.RENDERING_STANDARD


def test_render_questions_for_user_explicit_question_ids(tmp_path: Path):
    store = QuestionQueueStore(tmp_path)
    q1 = _ask_tier3_question(store, question_key="q1")
    _ask_tier3_question(store, question_key="q2")

    result = ftuo.render_questions_for_user(tmp_path, [q1["id"]], user="bob", store=store)
    assert [r["question_id"] for r in result["renderings"]] == [q1["id"]]


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_execute_verb_detect(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    code, payload = ftuo.execute_verb(root, "detect", user="alice")
    assert code == 1  # FIRST_TIME_HEURISTIC -> explanatory
    assert payload["status"] == ftuo.FIRST_TIME_HEURISTIC


def test_execute_verb_render_missing_question_id(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    code, payload = ftuo.execute_verb(root, "render", user="alice")
    assert code == 2
    assert payload["error"] == "MISSING_QUESTION_ID"


def test_execute_verb_render_real_question(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    store = QuestionQueueStore(root)
    q = _ask_tier3_question(store)
    code, payload = ftuo.execute_verb(root, "render", user="alice", question_id=q["id"])
    assert code == 1
    assert payload["rendering"]["rendering_mode"] == ftuo.RENDERING_EXPLANATORY
    assert "Why we're asking" in payload["markdown"]


def test_execute_verb_render_unknown_question(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    code, payload = ftuo.execute_verb(root, "render", user="alice", question_id="Q-ENV-DEADBEEF")
    assert code == 2
    assert payload["error"] == "QUESTION_NOT_FOUND"


def test_execute_verb_digest_no_questions_on_file(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    code, payload = ftuo.execute_verb(root, "digest", user="alice")
    assert code == 2
    assert payload["renderings"] == []


def test_execute_verb_unknown_verb(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    code, payload = ftuo.execute_verb(root, "bogus")
    assert code == 1
    assert payload["error"] == "UNKNOWN_VERB"


def test_cli_subprocess_detect(tmp_path: Path):
    import subprocess, sys
    root = tmp_path / "proj"
    root.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.first_time_user_onboarding", "detect",
         "--project-root", str(root), "--user", "alice"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == ftuo.FIRST_TIME_HEURISTIC
