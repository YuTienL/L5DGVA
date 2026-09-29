"""Real tests for dv_harness/bounded_self_healing.py (spec section 243,
targeted_hardening/bounded_self_healing).

Every test drives the REAL `loop_budget.classify_failure()` trigger fact and
the REAL `ControlPlane` on a real temp project root -- nothing here hand-
constructs a `FailureClassification` or a fake approval record. The central
negative control (`test_no_approval_on_file_refuses_to_fabricate_authorized`)
proves the module refuses to authorize a self-heal when the one thing it
requires -- a real human approval -- is absent, rather than defaulting to
AUTHORIZED or silently guessing.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

from dv_harness import bounded_self_healing as sh
from dv_harness import loop_budget as lb
from dv_harness.control_plane import ControlPlane


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
TRANSIENT_TEXT = "Connection reset by peer"          # real loop_budget TRANSIENT rule
DETERMINISTIC_TEXT = "Error-[SE] Syntax error"        # real loop_budget DETERMINISTIC rule


def _transient_classification() -> lb.FailureClassification:
    c = lb.classify_failure(TRANSIENT_TEXT)
    assert c.failure_type == lb.FailureType.TRANSIENT.value  # sanity on the real trigger fact
    assert c.retryable is True
    return c


# --------------------------------------------------------------------------
# vocabulary hygiene
# --------------------------------------------------------------------------
def test_decisions_never_collide_with_models_status():
    # Already asserted at import time; calling it again proves it is a real,
    # callable check and not merely an import-time side effect nobody could
    # re-run.
    sh.assert_no_verification_verdict_vocabulary()


# --------------------------------------------------------------------------
# eligibility: the narrow, safe class, reusing loop_budget.classify_failure()
# --------------------------------------------------------------------------
def test_transient_classification_is_eligible():
    c = _transient_classification()
    assert sh.classify_self_healing_eligibility(c) is None


def test_deterministic_classification_is_not_eligible():
    c = lb.classify_failure(DETERMINISTIC_TEXT)
    assert c.failure_type == lb.FailureType.DETERMINISTIC.value
    reason = sh.classify_self_healing_eligibility(c)
    assert reason is not None
    assert "DETERMINISTIC" in reason


def test_retryable_but_non_transient_classification_is_still_not_eligible():
    """LICENSE is retryable=True in loop_budget.RETRYABLE_FAILURE_TYPES, but
    bounded self-healing's own scope is narrower than loop_budget's broader
    retryable set -- proves the module does not silently expand to every
    retryable class."""
    outcome = type("Outcome", (), {"name": "eda_license", "status": "FAIL",
                                    "detail": "no such feature exists"})()
    c = lb.classify_failure("license checkout failed", preflight_checks=[outcome])
    assert c.failure_type == lb.FailureType.LICENSE.value
    assert c.retryable is True  # real loop_budget fact: LICENSE is retryable
    reason = sh.classify_self_healing_eligibility(c)
    assert reason is not None
    assert "LICENSE" in reason


# --------------------------------------------------------------------------
# action_id: deterministic, content-derived
# --------------------------------------------------------------------------
def test_action_id_is_deterministic_and_content_derived():
    c = _transient_classification()
    a1 = sh.action_id_for("VERIFY", c.signature)
    a2 = sh.action_id_for("VERIFY", c.signature)
    assert a1 == a2
    a3 = sh.action_id_for("BUILD", c.signature)
    assert a3 != a1

    other = lb.classify_failure("timed out waiting for response")
    assert other.signature != c.signature
    a4 = sh.action_id_for("VERIFY", other.signature)
    assert a4 != a1


# --------------------------------------------------------------------------
# the central negative control: no approval on file refuses to fabricate
# --------------------------------------------------------------------------
def test_no_approval_on_file_refuses_to_fabricate_authorized(tmp_path: Path):
    c = _transient_classification()
    decision = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path)
    assert decision.decision == sh.DECISION_BLOCKED_NO_APPROVAL
    assert decision.authorized is False
    assert sh.HUMAN_APPROVAL_STAGE in decision.reason
    # And it never wrote a ledger row for this unapproved evaluation -- a
    # later real approval must still be able to reach AUTHORIZED (see
    # test_re_evaluation_after_approval_still_reaches_authorized below).
    ledger = sh.SelfHealingLedger(tmp_path)
    assert ledger.get(decision.action_id) is None


def test_ineligible_classification_never_persists_a_ledger_row(tmp_path: Path):
    c = lb.classify_failure(DETERMINISTIC_TEXT)
    decision = sh.evaluate_self_healing(c, "BUILD", root=tmp_path)
    assert decision.decision == sh.DECISION_NOT_ELIGIBLE
    ledger = sh.SelfHealingLedger(tmp_path)
    assert ledger.get(decision.action_id) is None


# --------------------------------------------------------------------------
# approval must NAME the real decision -- a blanket approval is refused
# --------------------------------------------------------------------------
def test_approval_with_no_matching_citation_is_blocked_as_mismatch(tmp_path: Path):
    c = _transient_classification()
    cp = ControlPlane(tmp_path)
    cp.approve(sh.HUMAN_APPROVAL_STAGE, note="yes, self-heal everything, always",
               reviewer_id="alice", reviewer_confidence="HIGH")
    decision = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path, control_plane=cp)
    assert decision.decision == sh.DECISION_BLOCKED_APPROVAL_MISMATCH
    assert decision.authorized is False
    # The blanket approval is untouched -- refusing on mismatch must not
    # consume an approval that never actually authorized this action.
    assert cp.get_approval(sh.HUMAN_APPROVAL_STAGE) is not None


def test_approval_citing_the_real_action_id_authorizes_and_is_consumed(tmp_path: Path):
    c = _transient_classification()
    action_id = sh.action_id_for("VERIFY", c.signature)
    cp = ControlPlane(tmp_path)
    cp.approve(sh.HUMAN_APPROVAL_STAGE, note=f"authorize {action_id} for this run",
               reviewer_id="alice", reviewer_confidence="HIGH")

    decision = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path, control_plane=cp)

    assert decision.decision == sh.DECISION_AUTHORIZED
    assert decision.authorized is True
    assert decision.approved_by == "alice"
    assert decision.approved_at is not None

    # The ledger really recorded it.
    ledger = sh.SelfHealingLedger(tmp_path)
    row = ledger.get(action_id)
    assert row is not None
    assert row["decision"] == sh.DECISION_AUTHORIZED

    # The approval was CONSUMED -- it cannot silently reauthorize anything
    # else without a fresh human decision.
    assert cp.get_approval(sh.HUMAN_APPROVAL_STAGE) is None


def test_approval_citing_only_the_signature_prefix_also_authorizes(tmp_path: Path):
    c = _transient_classification()
    sig_citation = c.signature[:sh.SIGNATURE_CITATION_LENGTH]
    cp = ControlPlane(tmp_path)
    cp.approve(sh.HUMAN_APPROVAL_STAGE,
               note=f"confirmed this is a real transient network flake, signature {sig_citation}",
               reviewer_id="bob", reviewer_confidence="MEDIUM")
    decision = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path, control_plane=cp)
    assert decision.decision == sh.DECISION_AUTHORIZED
    assert decision.approved_by == "bob"


# --------------------------------------------------------------------------
# re-evaluation after approval is granted must still be able to authorize
# --------------------------------------------------------------------------
def test_re_evaluation_after_approval_still_reaches_authorized(tmp_path: Path):
    c = _transient_classification()
    action_id = sh.action_id_for("VERIFY", c.signature)

    first = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path)
    assert first.decision == sh.DECISION_BLOCKED_NO_APPROVAL

    cp = ControlPlane(tmp_path)
    cp.approve(sh.HUMAN_APPROVAL_STAGE, note=f"approve {action_id}",
               reviewer_id="carol", reviewer_confidence="HIGH")

    second = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path, control_plane=cp)
    assert second.decision == sh.DECISION_AUTHORIZED


# --------------------------------------------------------------------------
# the one-time bound: a healed signature is never healed again
# --------------------------------------------------------------------------
def test_second_occurrence_of_a_healed_signature_is_blocked_already_healed(tmp_path: Path):
    c = _transient_classification()
    action_id = sh.action_id_for("VERIFY", c.signature)
    cp = ControlPlane(tmp_path)
    cp.approve(sh.HUMAN_APPROVAL_STAGE, note=f"approve {action_id}",
               reviewer_id="dave", reviewer_confidence="HIGH")
    first = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path, control_plane=cp)
    assert first.decision == sh.DECISION_AUTHORIZED

    # The identical failure recurs. Even with a brand-new, correctly-cited
    # approval on file, the ledger refuses a second heal of the same
    # (stage, signature).
    cp.approve(sh.HUMAN_APPROVAL_STAGE, note=f"approve {action_id} again",
               reviewer_id="dave", reviewer_confidence="HIGH")
    second = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path, control_plane=cp)
    assert second.decision == sh.DECISION_BLOCKED_ALREADY_HEALED
    assert second.authorized is False


def test_different_stage_is_a_different_action_and_may_heal_independently(tmp_path: Path):
    c = _transient_classification()
    cp = ControlPlane(tmp_path)

    a1 = sh.action_id_for("VERIFY", c.signature)
    cp.approve(sh.HUMAN_APPROVAL_STAGE, note=f"approve {a1}", reviewer_id="e",
               reviewer_confidence="HIGH")
    d1 = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path, control_plane=cp)
    assert d1.decision == sh.DECISION_AUTHORIZED

    a2 = sh.action_id_for("BUILD_DEBUG", c.signature)
    assert a2 != a1
    cp.approve(sh.HUMAN_APPROVAL_STAGE, note=f"approve {a2}", reviewer_id="e",
               reviewer_confidence="HIGH")
    d2 = sh.evaluate_self_healing(c, "BUILD_DEBUG", root=tmp_path, control_plane=cp)
    assert d2.decision == sh.DECISION_AUTHORIZED


# --------------------------------------------------------------------------
# ledger internals
# --------------------------------------------------------------------------
def test_ledger_record_refuses_to_overwrite_an_existing_row(tmp_path: Path):
    c = _transient_classification()
    action_id = sh.action_id_for("VERIFY", c.signature)
    decision = sh.SelfHealingDecision(
        decision=sh.DECISION_AUTHORIZED, stage="VERIFY", action_id=action_id,
        failure_signature=c.signature, failure_type=c.failure_type, reason="test")
    ledger = sh.SelfHealingLedger(tmp_path)
    ledger.record(decision)
    with pytest.raises(sh.SelfHealingLedgerError):
        ledger.record(decision)


def test_ledger_record_outcome_requires_an_existing_row(tmp_path: Path):
    ledger = sh.SelfHealingLedger(tmp_path)
    with pytest.raises(sh.SelfHealingLedgerError):
        ledger.record_outcome("SH-doesnotexist", outcome="PASS", evidence="job 123 PASSed")


def test_ledger_record_outcome_on_a_real_row(tmp_path: Path):
    c = _transient_classification()
    action_id = sh.action_id_for("VERIFY", c.signature)
    decision = sh.SelfHealingDecision(
        decision=sh.DECISION_AUTHORIZED, stage="VERIFY", action_id=action_id,
        failure_signature=c.signature, failure_type=c.failure_type, reason="test")
    ledger = sh.SelfHealingLedger(tmp_path)
    ledger.record(decision)
    row = ledger.record_outcome(action_id, outcome="PASS", evidence="job 123 PASSed on re-run")
    assert row["outcome"]["outcome"] == "PASS"
    # Persisted, not merely returned.
    assert ledger.get(action_id)["outcome"]["outcome"] == "PASS"


def test_ledger_survives_a_corrupt_file_as_unreadable_rather_than_crashing(tmp_path: Path):
    ledger_dir = tmp_path / ".dv-harness"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / sh.LEDGER_FILENAME).write_text("{not json", encoding="utf-8")
    ledger = sh.SelfHealingLedger(tmp_path)
    data = ledger._load()
    assert data.get("load_error") == "LEDGER_UNREADABLE"
    assert ledger.get("SH-anything") is None


# --------------------------------------------------------------------------
# structural guarantee: this module never dispatches/retries/submits/
# self-approves anything itself
# --------------------------------------------------------------------------
def _code_only_names(path: Path) -> set:
    """The set of real NAME tokens in this module's source -- STRING (so
    docstrings, which legitimately discuss `run_stage()`/`ControlPlane.
    approve()` in prose) and COMMENT tokens are excluded, so a mention in
    this file's own explanatory prose can never satisfy the check."""
    src = path.read_text(encoding="utf-8")
    names = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NAME:
            names.add(tok.string)
    return names


def test_module_never_calls_run_stage_or_dispatches_or_self_approves():
    module_path = Path(sh.__file__)
    names = _code_only_names(module_path)
    # Never dispatches/retries/submits anything itself.
    assert "run_stage" not in names
    assert "subprocess" not in names
    assert "bsub_submit_with_preflight" not in names
    assert "Popen" not in names
    # Never self-approves -- only get_approval()/clear_approval() are real
    # NAME tokens this module may use; "approve" as its own bare identifier
    # would mean a direct `.approve(...)` call, which this module never makes.
    assert "approve" not in names
    assert "can_signoff" not in names
    assert "HumanApprovalRequiredError" not in names
    assert "ProductionWriteNotAuthorizedError" not in names


# --------------------------------------------------------------------------
# front door
# --------------------------------------------------------------------------
def test_execute_verb_eligible_types(tmp_path: Path):
    code, payload = sh.execute_verb(tmp_path, "eligible-types")
    assert code == 0
    assert payload["eligible_failure_types"] == [lb.FailureType.TRANSIENT.value]
    assert payload["human_approval_stage"] == sh.HUMAN_APPROVAL_STAGE


def test_execute_verb_classify_eligible_and_ineligible(tmp_path: Path):
    code, payload = sh.execute_verb(tmp_path, "classify", text=TRANSIENT_TEXT)
    assert code == 0
    assert payload["self_healing_eligible"] is True
    assert payload["ineligible_reason"] is None

    code, payload = sh.execute_verb(tmp_path, "classify", text=DETERMINISTIC_TEXT)
    assert code == 0
    assert payload["self_healing_eligible"] is False
    assert payload["ineligible_reason"]


def test_execute_verb_classify_requires_text(tmp_path: Path):
    code, payload = sh.execute_verb(tmp_path, "classify")
    assert code == 1
    assert payload["error"] == "TEXT_REQUIRED"


def test_execute_verb_evaluate_requires_text_and_stage(tmp_path: Path):
    code, payload = sh.execute_verb(tmp_path, "evaluate")
    assert code == 1
    assert payload["error"] == "TEXT_REQUIRED"

    code, payload = sh.execute_verb(tmp_path, "evaluate", text=TRANSIENT_TEXT)
    assert code == 1
    assert payload["error"] == "STAGE_REQUIRED"


def test_execute_verb_evaluate_full_round_trip(tmp_path: Path):
    code, payload = sh.execute_verb(tmp_path, "evaluate", text=TRANSIENT_TEXT, stage="VERIFY")
    assert code == 1
    assert payload["decision"] == sh.DECISION_BLOCKED_NO_APPROVAL

    action_id = payload["action_id"]
    ControlPlane(tmp_path).approve(sh.HUMAN_APPROVAL_STAGE, note=f"approve {action_id}",
                                    reviewer_id="frank", reviewer_confidence="HIGH")
    code, payload = sh.execute_verb(tmp_path, "evaluate", text=TRANSIENT_TEXT, stage="VERIFY")
    assert code == 0
    assert payload["decision"] == sh.DECISION_AUTHORIZED


def test_execute_verb_ledger(tmp_path: Path):
    code, payload = sh.execute_verb(tmp_path, "ledger")
    assert code == 0
    assert payload["actions"] == {}


def test_execute_verb_unknown_verb(tmp_path: Path):
    code, payload = sh.execute_verb(tmp_path, "not-a-real-verb")
    assert code == 1
    assert payload["error"] == "UNKNOWN_VERB"


# --------------------------------------------------------------------------
# real subprocess CLI
# --------------------------------------------------------------------------
def _run_cli(args, root: Path):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.bounded_self_healing", *args,
         "--project-root", str(root)],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=60,
    )


def test_cli_eligible_types_subprocess(tmp_path: Path):
    proc = _run_cli(["eligible-types"], tmp_path)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["human_approval_stage"] == "BOUNDED_SELF_HEALING"


def test_cli_evaluate_round_trip_subprocess(tmp_path: Path):
    proc = _run_cli(["evaluate", "--text", TRANSIENT_TEXT, "--stage", "VERIFY"], tmp_path)
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["decision"] == "BLOCKED_NO_APPROVAL"
    action_id = payload["action_id"]

    ControlPlane(tmp_path).approve("BOUNDED_SELF_HEALING", note=f"approve {action_id}",
                                    reviewer_id="grace", reviewer_confidence="HIGH")

    proc = _run_cli(["evaluate", "--text", TRANSIENT_TEXT, "--stage", "VERIFY"], tmp_path)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["decision"] == "AUTHORIZED"


# --------------------------------------------------------------------------
# commands.py wiring: the real, already-existing `dv-harness approve` verb
# --------------------------------------------------------------------------
def test_commands_approval_stage_choices_includes_bounded_self_healing():
    from dv_harness import commands
    assert sh.HUMAN_APPROVAL_STAGE in commands.APPROVAL_ONLY_STAGES
    assert sh.HUMAN_APPROVAL_STAGE in commands.approval_stage_choices()


def test_commands_cmd_approve_accepts_bounded_self_healing_stage(tmp_path: Path):
    from dv_harness import commands

    events = []

    class _StubStore:
        def event(self, ev):
            events.append(ev)

    class _StubHarness:
        root = tmp_path
        store = _StubStore()

    h = _StubHarness()
    entry = commands.cmd_approve(h, sh.HUMAN_APPROVAL_STAGE, note="SH-deadbeef1234abcd",
                                  reviewer_id="heidi", reviewer_confidence="HIGH")
    assert entry["stage"] == sh.HUMAN_APPROVAL_STAGE
    assert entry["reviewer_id"] == "heidi"
    assert events and events[0]["cmd"] == "approve"

    # And the real evaluate_self_healing() now sees it.
    c = _transient_classification()
    action_id = sh.action_id_for("VERIFY", c.signature)
    # Re-approve citing the real action id this time (the stub call above
    # used a placeholder note only to prove the CLI-layer wiring accepts the
    # stage at all).
    ControlPlane(tmp_path).approve(sh.HUMAN_APPROVAL_STAGE, note=f"approve {action_id}",
                                    reviewer_id="heidi", reviewer_confidence="HIGH")
    decision = sh.evaluate_self_healing(c, "VERIFY", root=tmp_path)
    assert decision.decision == sh.DECISION_AUTHORIZED
