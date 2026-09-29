"""End-to-end tests for the exemptions READ path.

Context (2026-09-04 audit finding, re-verified before this file was
written): dv_harness/exemptions.py was real, schema-complete and
expiry-driven, but `grep -rn "load_exemptions_document|list_exemptions|
check_expiry|build_review_queue|find_expired|find_active"` across the repo
matched ONLY cli.py's own `exemptions` subcommand handlers and its test
file. Nothing in question_queue.py, gates.py, self_audit.py, degradation.py
or engine.py ever consulted exemptions.yaml. So the store was write-plus-
manual-CLI-read only, and the two guarantees the spec asks for -- an agent
does not re-litigate a check an exemption already covers, and a temporary
exemption does not silently become permanent -- were not wired into any
real flow.

These tests exercise the wire that closes that, end-to-end through the REAL
QuestionQueueStore against a REAL exemptions.yaml written by the REAL
add_exemption() on a real temp filesystem -- never a mock, never a
hand-built dict standing in for the store:

  1. an ACTIVE exemption self-resolves a question about that check_id
     (no human asked),
  2. an EXPIRED one does not -- the question comes back,
  3. a hard-trigger question is NOT suppressed by an exemption, but does
     carry it into the escalation,
  4. an expired exemption becomes a real Tier-3 blocking question with a
     Q-ID, idempotently.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from dv_harness import exemptions as ex
from dv_harness.question_queue import (
    EXEMPTION_EXPIRY_KEY_PREFIX,
    EXEMPTION_TIER1_REASON,
    QuestionQueueStore,
    TIER1_SELF_RESOLVE,
    TIER2_SAFE_ASSUME,
    TIER3_CANNOT_ASSUME,
    classify_tier,
    validate_question,
)

CHECK = "usb3_lfps_polling_timeout_assert"


def _opts():
    return [
        {"label": "Treat the disabled check as intentional", "rationale": "an exemption may cover it."},
        {"label": "Re-enable the check and investigate", "rationale": "it may be stale dead code."},
    ]


def _store(tmp_path: Path) -> QuestionQueueStore:
    # blackboard=object-less: the store defaults to a real Blackboard rooted
    # at tmp_path, which is fine -- it creates directories under tmp_path
    # only, and this exercises the real construction path callers use.
    return QuestionQueueStore(tmp_path)


def _write_exemption(tmp_path: Path, *, valid_until: str, check_id: str = CHECK,
                       eid: str | None = None, **extra) -> dict:
    entry = {
        "check_id": check_id,
        "reason": "VIP release does not implement the LFPS polling timeout counter",
        "basis_document": "docs/vip_ref/usb.md#lfps-timeout (VIP RN 2025.06 §4.2)",
        "owner": "dv-owner@example.com",
        "valid_until": valid_until,
    }
    if eid:
        entry["id"] = eid
    entry.update(extra)
    return ex.add_exemption(ex.default_exemptions_path(tmp_path), entry)


def _future() -> str:
    return (date.today() + timedelta(days=90)).isoformat()


def _past() -> str:
    return (date.today() - timedelta(days=30)).isoformat()


# --- find_active_exemption: the lookup itself --------------------------------

def test_find_active_exemption_returns_the_entry_for_a_live_valid_until(tmp_path):
    written = _write_exemption(tmp_path, valid_until=_future())
    got = ex.find_active_exemption(ex.default_exemptions_path(tmp_path), CHECK)
    assert got is not None
    assert got["id"] == written["id"]
    assert got["basis_document"] == written["basis_document"]


def test_find_active_exemption_returns_none_once_valid_until_has_passed(tmp_path):
    _write_exemption(tmp_path, valid_until=_past())
    assert ex.find_active_exemption(ex.default_exemptions_path(tmp_path), CHECK) is None


def test_find_active_exemption_returns_none_for_a_retired_entry(tmp_path):
    _write_exemption(tmp_path, valid_until=_future(), status="retired")
    assert ex.find_active_exemption(ex.default_exemptions_path(tmp_path), CHECK) is None


def test_find_active_exemption_never_matches_a_different_check_id(tmp_path):
    _write_exemption(tmp_path, valid_until=_future())
    path = ex.default_exemptions_path(tmp_path)
    # A prefix of the real id must not match -- check_id is a literal key.
    assert ex.find_active_exemption(path, "usb3_lfps") is None
    assert ex.find_active_exemption(path, CHECK + "_extra") is None


def test_find_active_exemption_picks_the_latest_valid_until_when_two_cover_one_check(tmp_path):
    near = (date.today() + timedelta(days=10)).isoformat()
    far = (date.today() + timedelta(days=300)).isoformat()
    _write_exemption(tmp_path, valid_until=near, eid="EXEMPT-0100")
    _write_exemption(tmp_path, valid_until=far, eid="EXEMPT-0101")
    got = ex.find_active_exemption(ex.default_exemptions_path(tmp_path), CHECK)
    assert got["id"] == "EXEMPT-0101"


def test_find_active_exemption_on_a_project_with_no_exemptions_file_is_none_not_an_error(tmp_path):
    assert ex.find_active_exemption(ex.default_exemptions_path(tmp_path), CHECK) is None


# --- classify_tier: where the exemption sits in the order --------------------

def test_active_exemption_resolves_a_non_hard_trigger_ask_at_tier1():
    result = classify_tier({"check_id": CHECK}, exemption={"id": "EXEMPT-0001"})
    assert result["tier"] == TIER1_SELF_RESOLVE
    assert result["reason"] == EXEMPTION_TIER1_REASON


def test_exemption_does_not_suppress_a_hard_trigger_but_is_cited_in_the_escalation():
    result = classify_tier({"affects_spec_intent": True}, exemption={"id": "EXEMPT-0001"})
    assert result["tier"] == TIER3_CANNOT_ASSUME
    assert "covered_by_active_exemption:EXEMPT-0001" in result["reason"]


def test_exemption_reason_is_distinguishable_from_a_persisted_human_answer():
    assert EXEMPTION_TIER1_REASON != "decisions_store_hit"


# --- the real ask path -------------------------------------------------------

def test_add_question_self_resolves_from_a_real_active_exemption_on_disk(tmp_path):
    written = _write_exemption(tmp_path, valid_until=_future())
    q = _store(tmp_path).add_question(
        domain="env",
        question="Assertion %s is disabled in this build. Should it be re-enabled?" % CHECK,
        context_path="tb/usb3_assertions.sv:120",
        options=_opts(), recommendation="Treat the disabled check as intentional",
        assumption_if_unanswered="leave it disabled",
        context={"check_id": CHECK},
    )
    assert q["tier"] == TIER1_SELF_RESOLVE
    assert q["tier_reason"] == EXEMPTION_TIER1_REASON
    assert q["status"] == "SELF_RESOLVED"
    assert q["blocking"] is False
    # The answer carries the actual engineering "why", the citation an agent
    # can go open, and the accountable owner -- not just "it's exempt".
    assert written["reason"] in q["answer"]
    assert written["basis_document"] in q["basis"]
    assert q["decided_by"] == written["owner"]
    assert q["exemption"]["id"] == written["id"]
    assert q["exemption"]["valid_until"] == written["valid_until"]
    validate_question(q)


def test_the_exemption_backed_answer_is_not_persisted_as_a_decision(tmp_path):
    """An exemption expires; a decisions-store entry does not. Minting one
    from the other would outlive the exemption and keep suppressing this
    question past its owner's own re-review date."""
    store = _store(tmp_path)
    _write_exemption(tmp_path, valid_until=_future())
    q = store.add_question(
        domain="env", question="Is %s deliberately off?" % CHECK,
        context_path="tb/usb3_assertions.sv:120", options=_opts(),
        recommendation="Treat the disabled check as intentional",
        assumption_if_unanswered="leave it disabled", context={"check_id": CHECK},
    )
    assert store.find_decision(q["question_key"]) is None


def test_an_expired_exemption_no_longer_suppresses_the_question(tmp_path):
    """The valid_until guarantee, end-to-end: the same ask that self-resolved
    while the exemption was live comes back once it lapses."""
    _write_exemption(tmp_path, valid_until=_past())
    q = _store(tmp_path).add_question(
        domain="env", question="Is %s deliberately off?" % CHECK,
        context_path="tb/usb3_assertions.sv:120", options=_opts(),
        recommendation="Treat the disabled check as intentional",
        assumption_if_unanswered="leave it disabled", context={"check_id": CHECK},
    )
    assert q["tier"] == TIER2_SAFE_ASSUME
    assert q["tier_reason"] != EXEMPTION_TIER1_REASON
    assert "exemption" not in q


def test_a_question_carrying_no_check_id_is_never_matched_against_any_exemption(tmp_path):
    _write_exemption(tmp_path, valid_until=_future())
    q = _store(tmp_path).add_question(
        domain="env", question="Unrelated question about clock frequency",
        context_path="env.manifest.json#/dut_facts/clock_reset", options=_opts(),
        recommendation="Treat the disabled check as intentional",
        assumption_if_unanswered="assume 100MHz", context={},
    )
    assert q["tier_reason"] != EXEMPTION_TIER1_REASON
    assert "exemption" not in q


def test_a_hard_trigger_question_still_blocks_but_arrives_carrying_the_exemption(tmp_path):
    written = _write_exemption(tmp_path, valid_until=_future())
    q = _store(tmp_path).add_question(
        domain="env",
        question="%s is disabled and the test PASSes. Is that PASS real?" % CHECK,
        context_path="tb/usb3_assertions.sv:120", options=_opts(),
        recommendation="Re-enable the check and investigate",
        assumption_if_unanswered="treat the PASS as real",
        context={"check_id": CHECK, "affects_pass_fail_verdict": True},
    )
    assert q["tier"] == TIER3_CANNOT_ASSUME
    assert q["blocking"] is True
    assert q["status"] == "OPEN"
    assert "covered_by_active_exemption:%s" % written["id"] in q["tier_reason"]
    assert q["exemption"]["basis_document"] == written["basis_document"]
    validate_question(q)


def test_a_broken_exemptions_file_fails_toward_asking_not_toward_suppressing(tmp_path):
    """A store nobody can read must never grant a suppression."""
    path = ex.default_exemptions_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema_version: '1.0'\nexemptions:\n  - id: BROKEN\n", encoding="utf-8")
    with pytest.raises(ex.ExemptionValidationError):
        ex.list_exemptions(path)
    q = _store(tmp_path).add_question(
        domain="env", question="Is %s deliberately off?" % CHECK,
        context_path="tb/usb3_assertions.sv:120", options=_opts(),
        recommendation="Treat the disabled check as intentional",
        assumption_if_unanswered="leave it disabled", context={"check_id": CHECK},
    )
    assert q["tier_reason"] != EXEMPTION_TIER1_REASON
    assert "exemption" not in q


# --- expired exemption -> a real blocking question ---------------------------

def test_escalate_expired_exemptions_files_a_real_blocking_question(tmp_path):
    written = _write_exemption(tmp_path, valid_until=_past())
    store = _store(tmp_path)
    filed = store.escalate_expired_exemptions()

    assert len(filed) == 1
    q = filed[0]
    assert q["tier"] == TIER3_CANNOT_ASSUME
    assert q["blocking"] is True
    assert q["status"] == "OPEN"
    assert q["id"].startswith("Q-ENV-")
    assert q["question_key"] == "%s:%s" % (EXEMPTION_EXPIRY_KEY_PREFIX, written["id"])
    # The record carries what a human needs to act without opening the file.
    assert written["owner"] in q["question"]
    assert written["basis_document"] in q["question"]
    assert written["valid_until"] in q["question"]
    assert {o["label"] for o in q["options"]} == {"renew", "retire", "re-enable-the-check"}
    # An expired exemption must NOT also be cited as still covering the check.
    assert "exemption" not in q
    validate_question(q)

    # It is really in the queue, blocking, as any other Tier-3 ask.
    assert [x["id"] for x in store.list_questions(blocking=True)] == [q["id"]]


def test_escalate_expired_exemptions_is_idempotent_across_reruns(tmp_path):
    _write_exemption(tmp_path, valid_until=_past())
    store = _store(tmp_path)
    assert len(store.escalate_expired_exemptions()) == 1
    assert store.escalate_expired_exemptions() == []
    assert store.escalate_expired_exemptions() == []
    assert len(store.list_questions()) == 1


def test_escalate_expired_exemptions_ignores_active_and_retired_entries(tmp_path):
    _write_exemption(tmp_path, valid_until=_future(), check_id="live_check", eid="EXEMPT-0200")
    _write_exemption(tmp_path, valid_until=_past(), check_id="retired_check",
                      eid="EXEMPT-0201", status="retired")
    _write_exemption(tmp_path, valid_until=_past(), check_id="lapsed_check", eid="EXEMPT-0202")
    filed = _store(tmp_path).escalate_expired_exemptions()
    assert [q["question_key"] for q in filed] == ["%s:EXEMPT-0202" % EXEMPTION_EXPIRY_KEY_PREFIX]


def test_escalate_expired_exemptions_refreshes_the_documented_review_queue_json(tmp_path):
    written = _write_exemption(tmp_path, valid_until=_past())
    _store(tmp_path).escalate_expired_exemptions()
    out = ex.default_review_queue_path(tmp_path)
    assert out.is_file()
    import json
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert [e["exemption_id"] for e in payload["entries"]] == [written["id"]]


def test_escalation_and_renewal_close_the_loop(tmp_path):
    """The whole point of valid_until, end to end: an exemption lapses ->
    the harness stops honouring it AND raises a blocking question -> the
    owner renews it -> the harness honours it again."""
    path = ex.default_exemptions_path(tmp_path)
    _write_exemption(tmp_path, valid_until=_past(), eid="EXEMPT-0300")
    store = _store(tmp_path)

    assert len(store.escalate_expired_exemptions()) == 1
    q_before = store.add_question(
        domain="env", question="Is %s deliberately off?" % CHECK,
        context_path="tb/usb3_assertions.sv:120", options=_opts(),
        recommendation="Treat the disabled check as intentional",
        assumption_if_unanswered="leave it disabled", context={"check_id": CHECK})
    assert q_before["tier_reason"] != EXEMPTION_TIER1_REASON

    # The owner re-confirms with a new expiry (a NEW entry, per the schema's
    # own "superseded/re-approved" note -- the history is not rewritten).
    _write_exemption(tmp_path, valid_until=_future(), eid="EXEMPT-0301")

    assert store.escalate_expired_exemptions() == []
    assert ex.find_active_exemption(path, CHECK)["id"] == "EXEMPT-0301"
    q_after = store.add_question(
        domain="env", question="Is %s deliberately off, revisited?" % CHECK,
        context_path="tb/usb3_assertions.sv:121", options=_opts(),
        recommendation="Treat the disabled check as intentional",
        assumption_if_unanswered="leave it disabled", context={"check_id": CHECK})
    assert q_after["tier_reason"] == EXEMPTION_TIER1_REASON
    assert q_after["exemption"]["id"] == "EXEMPT-0301"


# --- CLI: `dv-harness exemptions escalate` -----------------------------------

import subprocess  # noqa: E402
import sys  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _run_cli(tmp: Path, *args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60, encoding="utf-8",
    )


def test_cli_escalate_files_a_blocking_question_and_exits_nonzero(tmp_path):
    import json
    r = _run_cli(tmp_path, "exemptions", "add",
                  "--check-id", "lapsed_check", "--reason", "temporary IP-tooling workaround",
                  "--basis-document", "TICKET-4242", "--owner", "alice",
                  "--valid-until", "2020-01-01")
    assert r.returncode == 0, r.stderr

    r2 = _run_cli(tmp_path, "exemptions", "escalate", "--as-of", "2026-09-03")
    assert r2.returncode == 1, r2.stdout + r2.stderr
    payload = json.loads(r2.stdout)
    assert payload["expired_count"] == 1
    assert payload["newly_filed_count"] == 1
    assert payload["questions"][0]["blocking"] is True
    assert payload["questions"][0]["tier"] == 3

    # It really landed in the real queue, visible to the real CLI reader.
    r3 = _run_cli(tmp_path, "question-queue", "list", "--blocking")
    assert r3.returncode == 0, r3.stderr
    assert payload["questions"][0]["id"] in r3.stdout


def test_cli_escalate_still_exits_nonzero_on_a_rerun_that_files_nothing(tmp_path):
    """Idempotence must not turn into a CI step that starts passing just
    because the question already exists -- the exemption is still expired
    and still unanswered."""
    import json
    assert _run_cli(tmp_path, "exemptions", "add",
                     "--check-id", "lapsed_check", "--reason", "r", "--basis-document", "b",
                     "--owner", "alice", "--valid-until", "2020-01-01").returncode == 0
    assert _run_cli(tmp_path, "exemptions", "escalate", "--as-of", "2026-09-03").returncode == 1
    r = _run_cli(tmp_path, "exemptions", "escalate", "--as-of", "2026-09-03")
    assert r.returncode == 1
    payload = json.loads(r.stdout)
    assert payload["expired_count"] == 1
    assert payload["newly_filed_count"] == 0


def test_cli_escalate_exits_zero_when_nothing_expired(tmp_path):
    import json
    assert _run_cli(tmp_path, "exemptions", "add",
                     "--check-id", "future_check", "--reason", "r", "--basis-document", "b",
                     "--owner", "alice", "--valid-until", "2099-01-01").returncode == 0
    r = _run_cli(tmp_path, "exemptions", "escalate", "--as-of", "2026-09-03")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["newly_filed_count"] == 0
