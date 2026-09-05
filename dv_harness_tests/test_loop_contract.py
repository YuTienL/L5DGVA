"""LoopContract (section 85) + the canonical loop state machine (section 86).

WHAT THESE TESTS ARE FOR. Not "an isolated function returns a value". The three
things that can actually go wrong with this mechanism are:

  1. the new LoopState vocabulary drifting out of agreement with the real
     `models.Status` / `capability_evolution.PROMOTION_STATES` vocabularies it
     bridges (tested by the totality assertions, which FAIL when a member is
     added to either side without a decision here);
  2. a contract describing a loop that no longer exists, or claiming a budget
     nothing enforces (tested by resolving every contract's driver entry point
     through the real import system, and by requiring every `None` budget to
     carry an honest reason);
  3. BUDGET_EXHAUSTED / OSCILLATING never actually being reachable on the real
     engine path -- the failure mode that would make this a vocabulary nobody
     produces.

(3) is driven end to end against a REAL `DVHarness.loop()` over the REAL shipped
`main_graph.json`, with the REAL `command_migration_integrity_gate.py`
subprocess judging the stage, in an isolated fixture project copy. The only
stubbed thing is the agent adapter, because the real one dispatches a `claude -p`
subprocess. Nothing here runs a build, a regression or an LSF submission:
COMMAND_PATTERN is an `implementation-route` node, chosen for exactly that
reason, and it is the fixture's only stage because it has no FAIL edge in the
real graph -- so a retry-exhausted `loop()` terminates deterministically instead
of walking on into the rest of the pipeline.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import capability_evolution as ce
from dv_harness import loop_contract as lc
from dv_harness.control_plane import ControlPlane
from dv_harness.models import Status
from dv_harness.storage import StateStore

from .controlled_experiment_fixture import (
    FIXTURE_STAGE,
    MIGRATION_FILE,
    MIGRATION_PAYLOAD,
    harness_factory,
    make_fixture_project,
)
from .test_capability_evolution_research_architect import _semantic_change_impact_fields


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def project():
    """An isolated fixture project: the real graph, one real gate script."""
    tmp = Path(tempfile.mkdtemp())
    try:
        yield make_fixture_project(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# Section 86: the state vocabulary and its bridge to models.Status
# --------------------------------------------------------------------------
def test_loop_state_carries_every_canonical_section_86_state():
    """Section 86 names 15 states in its chain plus RESUMING/STALE. All 17 must
    exist, spelled exactly as the section spells them."""
    expected = {
        "CREATED", "READY", "RUNNING", "VERIFYING", "CONVERGING", "PLATEAU",
        "OSCILLATING", "RETRY_WAIT", "BLOCKED", "HUMAN_GATE", "SUCCESS",
        "FAILED", "BUDGET_EXHAUSTED", "STOPPED", "CANCELLED", "RESUMING",
        "STALE",
    }
    assert {s.value for s in lc.LoopState} == expected


def test_status_mapping_is_total_in_both_directions():
    """The whole point of one bridge instead of two vocabularies: adding a
    models.Status member without deciding its loop meaning fails here."""
    lc.assert_status_mapping_total()


def test_capability_promotion_state_mapping_is_total():
    lc.assert_capability_state_mapping_total()


def test_the_states_this_vocabulary_actually_adds_are_exactly_the_audited_gap():
    """The gap this module closes, stated as data. `models.Status` genuinely
    covers HUMAN_GATE (via WAIT_USER), BLOCKED, RUNNING, SUCCESS (CLOSED),
    CONVERGING (PASS), READY (NOT_STARTED), RETRY_WAIT (RETRY/FAIL/PARTIAL) and
    STOPPED (ACCEPTED_RISK). These nine are the ones it does not express, and
    BUDGET_EXHAUSTED/PLATEAU/OSCILLATING are exactly the three the audit
    named."""
    assert {s.value for s in lc.LOOP_STATES_WITHOUT_STATUS_EQUIVALENT} == {
        "CREATED", "VERIFYING", "PLATEAU", "OSCILLATING", "FAILED",
        "BUDGET_EXHAUSTED", "CANCELLED", "RESUMING", "STALE",
    }


def test_transition_table_is_closed_and_covers_every_state():
    """Every state has a row; every named target is a real state."""
    for state in lc.LoopState:
        assert state.value in lc.LEGAL_LOOP_TRANSITIONS, state.value
    for src, targets in lc.LEGAL_LOOP_TRANSITIONS.items():
        for t in targets:
            assert t in lc.LOOP_STATE_VALUES, f"{src} -> {t}"


def test_terminal_states_have_no_outgoing_edges():
    for state in lc.TERMINAL_LOOP_STATES:
        assert lc.LEGAL_LOOP_TRANSITIONS[state.value] == (), state.value


def test_every_state_is_reachable_from_created():
    """A state nothing can reach is a vocabulary entry, not a state machine
    member. Walk the table from the only legal first state."""
    seen = {lc.LoopState.CREATED.value}
    frontier = [lc.LoopState.CREATED.value]
    while frontier:
        cur = frontier.pop()
        for nxt in lc.LEGAL_LOOP_TRANSITIONS[cur]:
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    assert seen == set(lc.LOOP_STATE_VALUES), (
        f"unreachable from CREATED: {sorted(set(lc.LOOP_STATE_VALUES) - seen)}")


def test_first_state_can_only_be_created():
    lc.assert_legal_loop_transition(None, lc.LoopState.CREATED.value)
    with pytest.raises(lc.IllegalLoopTransitionError):
        lc.assert_legal_loop_transition(None, lc.LoopState.RUNNING.value)


def test_illegal_and_unknown_transitions_raise():
    with pytest.raises(lc.IllegalLoopTransitionError):
        lc.assert_legal_loop_transition(lc.LoopState.SUCCESS.value,
                                        lc.LoopState.RUNNING.value)
    with pytest.raises(lc.IllegalLoopTransitionError):
        lc.assert_legal_loop_transition(lc.LoopState.CREATED.value, "NOT_A_STATE")


# --------------------------------------------------------------------------
# derive_loop_state(): precedence, and the two mappings with real reasoning
# --------------------------------------------------------------------------
def test_human_override_outranks_everything_including_a_spent_budget():
    """`engine.loop()` checks takeover FIRST, before the SIGNOFF gate and
    before run_stage(). The derivation must agree with the engine it
    describes."""
    assert lc.derive_loop_state(
        Status.FAIL.value, attempts=99, max_attempts=2,
        takeover_active=True) is lc.LoopState.HUMAN_GATE
    assert lc.derive_loop_state(
        Status.FAIL.value, attempts=99, max_attempts=2,
        paused=True) is lc.LoopState.STOPPED


def test_retry_budget_boundary_is_the_engines_own_condition():
    """engine.loop() retries while `ss['attempts'] <= max_retry`; the state
    flips at exactly the same point, not one either side of it."""
    assert lc.derive_loop_state(Status.PARTIAL.value, attempts=2, max_attempts=2) \
        is lc.LoopState.RETRY_WAIT
    assert lc.derive_loop_state(Status.PARTIAL.value, attempts=3, max_attempts=2) \
        is lc.LoopState.BUDGET_EXHAUSTED


def test_budget_exhaustion_outranks_an_oscillation_fingerprint():
    assert lc.derive_loop_state(Status.FAIL.value, attempts=9, max_attempts=2,
                                oscillating=True) is lc.LoopState.BUDGET_EXHAUSTED
    assert lc.derive_loop_state(Status.FAIL.value, attempts=1, max_attempts=2,
                                oscillating=True) is lc.LoopState.OSCILLATING


def test_oscillation_says_nothing_about_a_stage_that_passed():
    assert lc.derive_loop_state(Status.PASS.value, oscillating=True) \
        is lc.LoopState.CONVERGING


def test_a_stage_pass_is_converging_not_success():
    """SUCCESS is the LOOP's own machine-checkable done (overall_status ==
    CLOSED), not one node's verdict -- otherwise a run would claim a closed
    project once per stage."""
    assert lc.derive_loop_state(Status.PASS.value) is lc.LoopState.CONVERGING
    assert lc.derive_loop_state(Status.PASS.value, loop_done=True) is lc.LoopState.SUCCESS
    assert lc.derive_loop_state(Status.CLOSED.value) is lc.LoopState.SUCCESS


def test_accepted_risk_is_stopped_not_success():
    """A human accepting residual risk means the machine-checkable done was NOT
    met. SUCCESS would be a false claim."""
    assert lc.derive_loop_state(Status.ACCEPTED_RISK.value) is lc.LoopState.STOPPED


def test_unknown_status_raises_rather_than_defaulting():
    with pytest.raises(ValueError):
        lc.derive_loop_state("TOTALLY_PASSED_PROBABLY")


# --------------------------------------------------------------------------
# Section 85: the contracts, held against the code they describe
# --------------------------------------------------------------------------
def test_all_three_real_loops_have_a_contract():
    assert set(lc.loop_ids()) == {"verification_closure", "project_learning",
                                  "capability_evolution"}


def test_every_contract_validates_against_the_schema():
    for contract in lc.build_all_contracts().values():
        lc.validate_contract(contract)


def test_every_contracts_driver_resolves_through_the_import_system():
    """This is what stops a contract outliving the loop it documents: rename
    DVHarness.loop or memory_router.route_and_store and this fails."""
    for contract in lc.build_all_contracts().values():
        lc.assert_driver_resolvable(contract)


def test_a_contract_naming_a_driver_that_does_not_exist_is_refused():
    contract = lc.verification_closure_contract()
    contract.driver_entry_point = "DVHarness.loop_the_loop"
    with pytest.raises(lc.LoopContractValidationError):
        lc.assert_driver_resolvable(contract)


def test_verification_closure_budget_is_read_from_real_config_not_retyped():
    """Change policy.max_stage_retries and the contract changes with it -- the
    contract is derived, not hand-maintained."""
    cfg = {"policy": {"max_stage_retries": 7}, "claude": {"max_turns": 11}}
    contract = lc.verification_closure_contract(cfg)
    assert contract.budgets.max_failed_attempts == 7
    assert contract.retry.max_retries == 7
    assert "11" in contract.budget_sources["max_token_cost"]

    from dv_harness.config import DEFAULT_CONFIG
    assert lc.verification_closure_contract().budgets.max_failed_attempts == \
        DEFAULT_CONFIG["policy"]["max_stage_retries"]


def test_capability_contract_mirrors_the_real_promotion_state_machine():
    contract = lc.capability_evolution_contract()
    assert contract.state == list(ce.PROMOTION_STATES)
    assert ce.HUMAN_APPROVAL_STAGE in contract.human_gate
    assert contract.retry.non_retryable_failures == list(ce.TERMINAL_STATES)


def test_project_learning_contract_mirrors_the_real_confirmation_threshold():
    from dv_harness.memory_router import (ORGANIZATIONAL_MIN_CONFIRMATIONS,
                                          ENGINEERING_ADMISSION_CONFIDENCE_LEVELS,
                                          ENGINEERING_REUSABLE_CLAIM_FIELDS)
    contract = lc.project_learning_contract()
    assert contract.convergence.window == ORGANIZATIONAL_MIN_CONFIRMATIONS
    assert str(ORGANIZATIONAL_MIN_CONFIRMATIONS) in contract.machine_checkable_done
    for level in ENGINEERING_ADMISSION_CONFIDENCE_LEVELS:
        assert level in contract.verifier
    for claim in ENGINEERING_REUSABLE_CLAIM_FIELDS:
        assert claim in contract.verifier


def test_an_unbounded_budget_must_state_why_it_is_unbounded():
    """The honesty rule the JSON schema cannot express: a `None` budget with no
    entry in budget_sources would read to a human as a bound that exists."""
    contract = lc.verification_closure_contract()
    contract.budget_sources.pop("max_wall_time_seconds")
    with pytest.raises(lc.LoopContractValidationError) as exc:
        lc.validate_contract(contract)
    assert "max_wall_time_seconds" in str(exc.value)


def test_a_contract_missing_a_required_section_85_field_is_refused():
    payload = lc.verification_closure_contract().to_dict()
    payload["termination"].pop("budget")
    with pytest.raises(lc.LoopContractValidationError):
        lc.validate_contract(payload)


def test_contracts_round_trip_through_section_85_yaml():
    for loop_id in lc.loop_ids():
        original = lc.build_contract(loop_id)
        restored = lc.LoopContract.from_yaml(original.to_yaml())
        assert restored.to_dict() == original.to_dict()
        lc.validate_contract(restored)


def test_no_contract_claims_a_budget_this_harness_does_not_enforce():
    """The three budgets section 85 lists that this engine really implements
    are max_failed_attempts (verification closure) and max_change_scope
    (capability evolution). Everything else must be None with a reason -- a
    number here would make a loop look bounded when nothing bounds it."""
    enforced = {
        ("verification_closure", "max_failed_attempts"),
        ("capability_evolution", "max_change_scope"),
    }
    for contract in lc.build_all_contracts().values():
        for name, value in contract.to_dict()["budgets"].items():
            if value is not None:
                assert (contract.loop_id, name) in enforced, (
                    f"{contract.loop_id}.{name} claims a bound of {value!r}; "
                    f"name the code that enforces it or leave it None")


# --------------------------------------------------------------------------
# Oscillation, computed only from evidence the engine already persists
# --------------------------------------------------------------------------
def test_oscillation_needs_the_threshold_number_of_repeats():
    one = [{"failing_stage": "BUILD", "target_fail_edge": "BUILD_DEBUG"}]
    assert lc.detect_oscillation_from_debug_loop_history(one)["oscillating"] is False
    two = one * 2
    verdict = lc.detect_oscillation_from_debug_loop_history(two)
    assert verdict["oscillating"] is True
    assert verdict["repeated_fingerprints"] == {"BUILD|BUILD_DEBUG": 2}
    assert verdict["rounds_examined"] == 2


def test_two_different_failures_are_not_an_oscillation():
    entries = [{"failing_stage": "BUILD", "target_fail_edge": "BUILD_DEBUG"},
               {"failing_stage": "VERIFY", "target_fail_edge": "FAILURE_RECOVERY"}]
    assert lc.detect_oscillation_from_debug_loop_history(entries)["oscillating"] is False


def test_empty_history_is_not_an_oscillation_and_does_not_crash():
    assert lc.detect_oscillation_from_debug_loop_history([])["oscillating"] is False
    assert lc.detect_oscillation_from_debug_loop_history(
        [None, {}, "junk"])["oscillating"] is False


def test_plateau_is_reported_as_not_evaluated_never_as_absent(project):
    """A detector that never ran and a detector that found nothing are
    different facts. Collapsing them is how "we checked" becomes unearned."""
    state = StateStore(project).load()
    obs = lc.observe_verification_closure_loop(state, {"policy": {}})
    assert obs.plateau == lc.PLATEAU_NOT_EVALUATED
    assert "trend_analysis" in obs.note


# --------------------------------------------------------------------------
# The real engine path: a real loop(), a real gate, a real BUDGET_EXHAUSTED
# --------------------------------------------------------------------------
def _run_real_loop_to_retry_exhaustion(project: Path) -> "object":
    """Drive the REAL DVHarness.loop() over the REAL shipped graph until
    COMMAND_PATTERN's retry budget is spent.

    COMMAND_PATTERN has no FAIL edge in main_graph.json, so `graph_next(...,
    FAIL)` returns None and loop() returns right after recording the routing
    decision -- a deterministic stop, with no build/regression/LSF stage ever
    dispatched. The gate really runs: the fixture ships the real
    command_migration_integrity_gate.py and the stub adapter submits no
    evidence while MIGRATION_FILE is absent."""
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the command pattern migration")
    return h


def test_real_loop_reaches_budget_exhausted_and_records_it(project):
    h = _run_real_loop_to_retry_exhaustion(project)

    ss = h.state.stages[FIXTURE_STAGE]
    assert ss["status"] in (Status.FAIL.value, Status.PARTIAL.value, Status.RETRY.value)
    assert ss["attempts"] > h.cfg["policy"]["max_stage_retries"], (
        "the loop must actually have spent the retry budget")

    events = [json.loads(line) for line in
              (project / ".dv-harness" / "events.jsonl").read_text(
                  encoding="utf-8").splitlines() if line.strip()]
    observed = [e for e in events if e.get("event") == "LOOP_STATE_OBSERVED"]
    assert observed, "loop() recorded no LOOP_STATE_OBSERVED event"
    last = observed[-1]
    assert last["state"] == lc.LoopState.BUDGET_EXHAUSTED.value
    assert last["occasion"] == "RETRY_BUDGET_EXHAUSTED"
    assert last["loop_id"] == lc.VERIFICATION_CLOSURE_LOOP
    # The observation shows its work: the two real fields it was derived from.
    assert last["evidence"]["stage"] == FIXTURE_STAGE
    assert last["evidence"]["attempts"] > last["evidence"]["max_stage_retries"]


def test_observing_the_same_project_afterwards_agrees_with_the_recorded_event(project):
    """The CLI/observe path and the engine's own recorded event must not be two
    different answers about the same project."""
    _run_real_loop_to_retry_exhaustion(project)
    payload = lc.observe_all(project)
    obs = payload["observations"][lc.VERIFICATION_CLOSURE_LOOP]
    assert obs["state"] == lc.LoopState.BUDGET_EXHAUSTED.value
    assert obs["evidence"]["stage"] == FIXTURE_STAGE


def test_a_second_identical_failure_is_a_real_oscillation_fingerprint(project):
    """Two real retry-exhaustion rounds over the same node write two real
    `debug_loop_history` entries with the same (failing_stage,
    target_fail_edge) pair -- an oscillation fingerprint computed from records
    the engine wrote for its own reasons, not from anything typed for this
    test."""
    h = _run_real_loop_to_retry_exhaustion(project)
    h.state.stages[FIXTURE_STAGE]["attempts"] = 0
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the command pattern migration, second round")

    entries = (h.blackboard.read_debug_loop_history() or {}).get("entries") or []
    assert len(entries) >= 2
    verdict = lc.detect_oscillation_from_debug_loop_history(entries)
    assert verdict["oscillating"] is True

    obs = lc.observe_verification_closure_loop(
        h.state, h.cfg, debug_loop_entries=entries, stage=FIXTURE_STAGE)
    # Budget exhaustion still outranks it -- documented precedence, asserted.
    assert obs.state == lc.LoopState.BUDGET_EXHAUSTED.value
    assert obs.evidence["oscillation"]["oscillating"] is True


def test_a_real_gate_pass_observes_as_converging(project):
    """The positive control: the same fixture, the same real gate, with the
    migration manifest present. Without this, "BUDGET_EXHAUSTED" would only
    prove the fixture always fails."""
    (project / MIGRATION_FILE).write_text(json.dumps(MIGRATION_PAYLOAD), encoding="utf-8")
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.run_stage("verify the command pattern migration", stage=FIXTURE_STAGE)

    assert h.state.stages[FIXTURE_STAGE]["status"] == Status.PASS.value
    obs = lc.observe_verification_closure_loop(h.state, h.cfg, stage=FIXTURE_STAGE)
    assert obs.state == lc.LoopState.CONVERGING.value


def test_a_real_control_plane_pause_observes_as_stopped(project):
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    cp = ControlPlane(project)
    cp.pause("operator stopped the run")
    obs = lc.observe_verification_closure_loop(
        h.state, h.cfg, control_plane_state=cp.load(), stage=FIXTURE_STAGE)
    assert obs.state == lc.LoopState.STOPPED.value
    assert obs.evidence["paused"] is True


def test_a_real_takeover_observes_as_human_gate(project):
    h = harness_factory(project)
    cp = ControlPlane(project)
    cp.takeover(FIXTURE_STAGE, message="I am driving this one by hand")
    obs = lc.observe_verification_closure_loop(
        h.state, h.cfg, control_plane_state=cp.load(), stage=FIXTURE_STAGE)
    assert obs.state == lc.LoopState.HUMAN_GATE.value
    assert obs.evidence["takeover_active"] is True


def test_observability_failure_never_crashes_the_engine(project, monkeypatch):
    """Best-effort, like every sibling _record_* method: a broken observation
    must not turn an already-computed routing decision into a crash."""
    h = harness_factory(project)

    def boom(*a, **k):
        raise RuntimeError("blackboard on fire")

    monkeypatch.setattr(lc, "observe_verification_closure_loop", boom)
    assert h._record_loop_state_observation(FIXTURE_STAGE, occasion="TEST") is None
    events = [json.loads(line) for line in
              (project / ".dv-harness" / "events.jsonl").read_text(
                  encoding="utf-8").splitlines() if line.strip()]
    assert any(e.get("event") == "LOOP_STATE_OBSERVE_FAILED" for e in events)


# --------------------------------------------------------------------------
# The other two loops, observed from their own REAL state
# --------------------------------------------------------------------------
def test_a_real_capability_candidate_observes_at_created(root):
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    ce.persist_candidate(root, candidate)
    stored = ce.read_candidate(root, candidate["candidate_id"])
    obs = lc.observe_capability_evolution_loop(stored)
    assert obs.state == lc.LoopState.CREATED.value
    assert obs.evidence["candidate_id"] == candidate["candidate_id"]


def test_walking_the_real_promotion_states_walks_the_loop_states(root):
    """Driven through the REAL transition(), one legal governance state at a
    time -- no shortcut write, so each loop state observed was reached the way
    the state machine allows."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    ce.persist_candidate(root, candidate)
    seen = [lc.observe_capability_evolution_loop(candidate).state]
    for state in ("EVIDENCE_GATHERING", "PROPOSED", "EXPERIMENT_APPROVED", "EXPERIMENTING"):
        candidate = ce.transition(root, candidate, state, by="tester",
                                  reason=f"advance to {state}")
        seen.append(lc.observe_capability_evolution_loop(candidate).state)
    assert seen == ["CREATED", "RUNNING", "HUMAN_GATE", "READY", "RUNNING"]


def test_observing_human_gate_authorizes_nothing(root):
    """The boundary. Producing a HUMAN_GATE observation must not make the real
    approval gate any easier to pass."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    ce.persist_candidate(root, candidate)
    candidate = ce.transition(root, candidate, "EVIDENCE_GATHERING", by="tester", reason="x")
    candidate = ce.transition(root, candidate, "PROPOSED", by="tester", reason="x")
    assert lc.observe_capability_evolution_loop(candidate).state == \
        lc.LoopState.HUMAN_GATE.value
    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.assert_human_approval(root, candidate)
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(root, candidate)


def test_a_candidate_with_a_foreign_status_is_refused_not_guessed():
    with pytest.raises(ValueError):
        lc.observe_capability_evolution_loop({"candidate_id": "X", "current_status": "PASS"})


def test_a_real_memory_routing_result_observes_the_learning_loop(root):
    """Driven through the REAL memory_router.route_and_store(), against a real
    MemoryStore on disk -- the destination observed is the one the router
    actually chose."""
    from dv_harness.memory_router import route_and_store

    result = route_and_store(root, {
        "kind": "react_reasoning_step",
        "summary": "hypothesis refined from the LFPS timeout evidence",
    }, cfg={})
    obs = lc.observe_project_learning_loop(result)
    assert obs.state == lc.LoopState.RUNNING.value
    assert obs.evidence["destination"] == result["destination"]


def test_an_admission_rejection_observes_as_blocked():
    """A record demoted by an admission gate really did fail a gate; reporting
    it as merely "in the loop" would hide that."""
    obs = lc.observe_project_learning_loop({
        "destination": "WORKING_MEMORY",
        "engineering_admission_rejected": ["NO_EVIDENCE"],
    })
    assert obs.state == lc.LoopState.BLOCKED.value
    assert obs.evidence["admission_rejections"] == ["engineering_admission_rejected"]


def test_confirmations_remaining_comes_from_the_real_threshold():
    from dv_harness.memory_router import ORGANIZATIONAL_MIN_CONFIRMATIONS
    obs = lc.observe_project_learning_loop(
        {"destination": "ENGINEERING_MEMORY"}, confirmation_count=1)
    assert obs.state == lc.LoopState.CONVERGING.value
    assert obs.evidence["confirmations_remaining"] == ORGANIZATIONAL_MIN_CONFIRMATIONS - 1


def test_an_unknown_memory_destination_is_refused_not_guessed():
    with pytest.raises(ValueError):
        lc.observe_project_learning_loop({"destination": "SOMEWHERE_ELSE"})


# --------------------------------------------------------------------------
# The front door
# --------------------------------------------------------------------------
def test_execute_verb_states_list_show_observe(project):
    code, states = lc.execute_verb(project, "states", cfg={})
    assert code == 0 and len(states["loop_states"]) == 17

    code, listing = lc.execute_verb(project, "list", cfg={})
    assert code == 0 and len(listing["loops"]) == 3

    code, shown = lc.execute_verb(project, "show",
                                  loop_id=lc.CAPABILITY_EVOLUTION_LOOP, cfg={})
    assert code == 0 and shown["loop_id"] == lc.CAPABILITY_EVOLUTION_LOOP

    code, yaml_payload = lc.execute_verb(project, "show",
                                         loop_id=lc.PROJECT_LEARNING_LOOP,
                                         cfg={}, fmt="yaml")
    assert code == 0 and "loop_id: project_learning" in yaml_payload["yaml"]

    code, observed = lc.execute_verb(project, "observe", cfg={"policy": {}})
    assert code == 0 and set(observed["observations"]) == set(lc.loop_ids())


def test_execute_verb_refuses_an_unknown_loop_and_verb(project):
    code, payload = lc.execute_verb(project, "show", loop_id="the_other_loop", cfg={})
    assert code == 1 and payload["error"] == "UNKNOWN_LOOP_ID"
    code, payload = lc.execute_verb(project, "show", cfg={})
    assert code == 1 and payload["error"] == "LOOP_ID_REQUIRED"
    code, payload = lc.execute_verb(project, "sync", cfg={})
    assert code == 1 and payload["error"] == "UNKNOWN_VERB"


def test_observe_reports_an_honest_absence_rather_than_a_guess(project):
    payload = lc.observe_all(project, cfg={"policy": {}})
    for loop_id in (lc.CAPABILITY_EVOLUTION_LOOP, lc.PROJECT_LEARNING_LOOP):
        entry = payload["observations"][loop_id]
        assert entry["state"] == "NOT_OBSERVABLE"
        assert entry["reason"]


def test_cli_verb_is_registered_and_dispatches(project):
    """The module being importable is not the same as it being reachable. This
    drives the real argparse tree in cli.py."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(project),
         "loop-contract", "list"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert {l["loop_id"] for l in json.loads(out.stdout)["loops"]} == set(lc.loop_ids())
