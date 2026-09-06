"""Tests for dv_harness/verification_intake_contract.py -- the whole-project
VerificationIntakeContract lifecycle state machine and the INTAKE_READY
conjunction over caller-named critical conditions.

Every test drives the real module functions directly (no mocks: the module
under test has no external dependency to mock -- it imports nothing else in
dv_harness by design, per its own scope). The core positive path drives a
full, realistic lifecycle traversal including the loops a real intake effort
actually takes (a CONFLICT, a PARTIAL, a BLOCKED, a human sending
READY_FOR_REVIEW back, and a BASELINED contract going STALE and being
REVALIDATED). Negative controls prove illegal jumps are refused, ambiguous
condition input is refused rather than guessed at, and INTAKE_READY really is
a conjunction rather than an average.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import verification_intake_contract as vic


# ===========================================================================
# Lifecycle vocabulary / transition-table self-consistency
# ===========================================================================

def test_all_thirteen_states_present_in_task_order():
    assert vic.TASK_ORDERED_STATES == (
        "CREATED", "DISCOVERING", "CORRELATING", "QUESTION_PENDING",
        "USER_INPUT_RECEIVED", "VALIDATING", "CONFLICT", "PARTIAL", "BLOCKED",
        "READY_FOR_REVIEW", "BASELINED", "STALE", "REVALIDATING",
    )
    assert len(vic.TASK_ORDERED_STATES) == 13
    assert set(vic.TASK_ORDERED_STATES) == {s.value for s in vic.IntakeContractState}


def test_transition_table_is_total_and_closed():
    # Every state is a key, every target is a real state -- re-runs the same
    # guard the module already asserts at import time, proving it is a real,
    # callable check and not merely an import-time side effect.
    vic.assert_transition_table_total()


def test_no_absorbing_state_every_state_has_a_way_out():
    vic.assert_no_absorbing_state()
    for state, targets in vic.TRANSITIONS.items():
        assert targets, f"{state} has no outgoing edge"


def test_ready_for_review_is_explicitly_non_terminal():
    targets = vic.legal_next_states(vic.IntakeContractState.READY_FOR_REVIEW.value)
    # Non-terminal: it can go forward to BASELINED...
    assert vic.IntakeContractState.BASELINED.value in targets
    # ...or backward, to any of three earlier stages -- these are the "sent
    # back by a human" edges the task requires.
    assert vic.IntakeContractState.DISCOVERING.value in targets
    assert vic.IntakeContractState.CORRELATING.value in targets
    assert vic.IntakeContractState.VALIDATING.value in targets
    assert len(targets) >= 4


def test_transition_table_guards_detect_a_broken_table():
    # Prove the guards have real detection power rather than trivially
    # passing on the shipped table: construct deliberately-broken tables and
    # assert each guard raises for the specific defect it names.
    original = dict(vic.TRANSITIONS)
    try:
        vic.TRANSITIONS.pop(vic.IntakeContractState.STALE.value)
        with pytest.raises(vic.IntakeContractError) as ei:
            vic.assert_transition_table_total()
        assert ei.value.reason == "TRANSITION_TABLE_INCOMPLETE"
    finally:
        vic.TRANSITIONS.clear()
        vic.TRANSITIONS.update(original)

    try:
        vic.TRANSITIONS[vic.IntakeContractState.BASELINED.value] = ()
        with pytest.raises(vic.IntakeContractError) as ei:
            vic.assert_no_absorbing_state()
        assert ei.value.reason == "ABSORBING_STATE_FOUND"
        assert vic.IntakeContractState.BASELINED.value in ei.value.detail["states"]
    finally:
        vic.TRANSITIONS.clear()
        vic.TRANSITIONS.update(original)

    try:
        vic.TRANSITIONS[vic.IntakeContractState.CREATED.value] = ("NOT_A_REAL_STATE",)
        with pytest.raises(vic.IntakeContractError) as ei:
            vic.assert_transition_table_total()
        assert ei.value.reason == "TRANSITION_TABLE_TARGETS_UNKNOWN_STATE"
    finally:
        vic.TRANSITIONS.clear()
        vic.TRANSITIONS.update(original)


# ===========================================================================
# Core positive path: a full, realistic lifecycle traversal
# ===========================================================================

def test_full_realistic_lifecycle_traversal_including_loops():
    c = vic.create_contract("proj-usb31", sub_domain_data={"env_manifest": {"schema": "seed"}})
    assert c.state == "CREATED"
    assert c.sub_domains["env_manifest"] == {"schema": "seed"}

    c = vic.transition_contract(c, "DISCOVERING", reason="begin discovery")
    c = vic.transition_contract(c, "CORRELATING", reason="cross-domain facts gathered",
                                sub_domain_data={"connectivity_bind_entries": [{"tier": "T1"}]})
    assert "connectivity_bind_entries" in c.sub_domains

    # A correlation-time ambiguity sends the contract to ask a human.
    c = vic.transition_contract(c, "QUESTION_PENDING", reason="ambiguous DUT boundary")
    c = vic.transition_contract(c, "USER_INPUT_RECEIVED", reason="human answered",
                                sub_domain_data={"question_queue_decisions": [{"answer": "PHY present"}]})
    c = vic.transition_contract(c, "VALIDATING", reason="re-validate with the human's answer")

    # First validation attempt finds a real cross-domain disagreement.
    c = vic.transition_contract(c, "CONFLICT", reason="env manifest vs register map disagree")
    c = vic.transition_contract(c, "CORRELATING", reason="re-correlate after conflict noted")
    c = vic.transition_contract(c, "VALIDATING", reason="re-validate")

    # Second validation attempt is only partially resolved.
    c = vic.transition_contract(c, "PARTIAL", reason="some fields still unresolved")
    c = vic.transition_contract(c, "DISCOVERING", reason="go find the missing facts")
    c = vic.transition_contract(c, "CORRELATING", reason="re-correlate")
    c = vic.transition_contract(c, "VALIDATING", reason="re-validate")

    # Third attempt is blocked outright (e.g. a T4 bind entry).
    c = vic.transition_contract(c, "BLOCKED", reason="undecidable bind entry")
    c = vic.transition_contract(c, "QUESTION_PENDING", reason="escalate the blocker")
    c = vic.transition_contract(c, "USER_INPUT_RECEIVED", reason="human resolved it")
    c = vic.transition_contract(c, "VALIDATING", reason="final re-validate")

    # Clean at last.
    c = vic.transition_contract(c, "READY_FOR_REVIEW", reason="all conditions clear")
    assert c.state == "READY_FOR_REVIEW"

    # Non-terminal: a human sends it BACK for one more look before approving.
    c = vic.transition_contract(c, "CORRELATING", reason="human wants one more cross-check",
                                by="reviewer_a")
    c = vic.transition_contract(c, "VALIDATING", reason="re-validate")
    c = vic.transition_contract(c, "READY_FOR_REVIEW", reason="clean again")

    c = vic.transition_contract(c, "BASELINED", reason="human approved", by="reviewer_a")
    assert c.state == "BASELINED"

    # A later RTL/spec change is discovered (by whatever staleness detector a
    # caller runs -- this module only accepts the resulting transition).
    c = vic.transition_contract(c, "STALE", reason="RTL moved since baseline")
    c = vic.transition_contract(c, "REVALIDATING", reason="begin revalidation")
    c = vic.transition_contract(c, "VALIDATING", reason="re-run validation")
    c = vic.transition_contract(c, "READY_FOR_REVIEW", reason="clean after revalidation")
    c = vic.transition_contract(c, "BASELINED", reason="re-approved", by="reviewer_a")
    assert c.state == "BASELINED"

    # Every hop is recorded, in order, with the real from/to/reason/by.
    hops = [(h["from"], h["to"]) for h in c.state_history]
    assert hops[0] == (None, "CREATED")
    assert hops[-1] == ("READY_FOR_REVIEW", "BASELINED")
    assert len(c.state_history) == len(hops)
    # sub_domains accumulated across the whole traversal, never clobbered.
    assert set(c.sub_domains) >= {"env_manifest", "connectivity_bind_entries", "question_queue_decisions"}


def test_transition_never_mutates_the_input_contract():
    c0 = vic.create_contract("proj-1")
    c1 = vic.transition_contract(c0, "DISCOVERING", reason="go")
    assert c0.state == "CREATED"
    assert c1.state == "DISCOVERING"
    assert c0 is not c1
    assert c0.state_history is not c1.state_history


# ===========================================================================
# Negative controls: illegal transitions must be REFUSED, never guessed
# ===========================================================================

def test_illegal_jump_skipping_discovery_and_correlation_is_refused():
    c = vic.create_contract("proj-2")
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.transition_contract(c, "VALIDATING", reason="skip ahead")
    assert ei.value.reason == "ILLEGAL_STATE_TRANSITION"
    assert ei.value.detail["from"] == "CREATED"
    assert ei.value.detail["to"] == "VALIDATING"
    assert "DISCOVERING" in ei.value.detail["legal_next_states"]


def test_baselined_cannot_jump_back_to_correlating_directly():
    # BASELINED's only legal edge is STALE -- proves the machine really
    # constrains a "finished-looking" state too, not only early ones.
    c = vic.create_contract("proj-3")
    c = vic.transition_contract(c, "DISCOVERING", reason="r")
    c = vic.transition_contract(c, "CORRELATING", reason="r")
    c = vic.transition_contract(c, "VALIDATING", reason="r")
    c = vic.transition_contract(c, "READY_FOR_REVIEW", reason="r")
    c = vic.transition_contract(c, "BASELINED", reason="r")
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.transition_contract(c, "CORRELATING", reason="illegal")
    assert ei.value.reason == "ILLEGAL_STATE_TRANSITION"
    assert ei.value.detail["legal_next_states"] == ["STALE"]


def test_transition_to_unrecognized_state_string_is_refused():
    c = vic.create_contract("proj-4")
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.transition_contract(c, "NOT_A_REAL_STATE", reason="typo")
    assert ei.value.reason == "UNKNOWN_INTAKE_CONTRACT_STATE"


def test_legal_next_states_of_unrecognized_state_is_refused():
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.legal_next_states("BOGUS")
    assert ei.value.reason == "UNKNOWN_INTAKE_CONTRACT_STATE"


def test_create_contract_refuses_an_unrecognized_seed_state_via_dataclass_guard():
    with pytest.raises(vic.IntakeContractError):
        vic.VerificationIntakeContract(contract_id="x", state="MADE_UP")


def test_empty_contract_id_is_refused():
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.create_contract("   ")
    assert ei.value.reason == "EMPTY_CONTRACT_ID"


# ===========================================================================
# require_intake_ready opt-in guard on the READY_FOR_REVIEW edge
# ===========================================================================

def test_require_intake_ready_blocks_ready_for_review_when_not_ready():
    c = vic.create_contract("proj-5")
    c = vic.transition_contract(c, "DISCOVERING", reason="r")
    c = vic.transition_contract(c, "CORRELATING", reason="r")
    c = vic.transition_contract(c, "VALIDATING", reason="r")
    bad_readiness = vic.evaluate_intake_readiness([
        {"name": "dut_boundary", "status": "MET"},
        {"name": "vip_resolution", "status": "UNMET", "reason": "not resolved"},
    ])
    assert bad_readiness.ready is False
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.transition_contract(c, "READY_FOR_REVIEW", reason="attempt", by="agent",
                                require_intake_ready=True, readiness=bad_readiness)
    assert ei.value.reason == "INTAKE_NOT_READY_FOR_REVIEW"
    # Without the opt-in, the same transition is allowed (disclosed default).
    c2 = vic.transition_contract(c, "READY_FOR_REVIEW", reason="attempt without the opt-in")
    assert c2.state == "READY_FOR_REVIEW"


def test_require_intake_ready_allows_ready_for_review_when_all_clear():
    c = vic.create_contract("proj-6")
    c = vic.transition_contract(c, "DISCOVERING", reason="r")
    c = vic.transition_contract(c, "CORRELATING", reason="r")
    c = vic.transition_contract(c, "VALIDATING", reason="r")
    good_readiness = vic.evaluate_intake_readiness([
        {"name": "dut_boundary", "status": "MET"},
        {"name": "vip_resolution", "status": "NOT_APPLICABLE"},
    ])
    assert good_readiness.ready is True
    c = vic.transition_contract(c, "READY_FOR_REVIEW", reason="clean",
                                require_intake_ready=True, readiness=good_readiness)
    assert c.state == "READY_FOR_REVIEW"


def test_require_intake_ready_with_no_readiness_supplied_is_refused():
    c = vic.create_contract("proj-6b")
    c = vic.transition_contract(c, "DISCOVERING", reason="r")
    c = vic.transition_contract(c, "CORRELATING", reason="r")
    c = vic.transition_contract(c, "VALIDATING", reason="r")
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.transition_contract(c, "READY_FOR_REVIEW", reason="no readiness supplied",
                                require_intake_ready=True)
    assert ei.value.reason == "INTAKE_NOT_READY_FOR_REVIEW"


# ===========================================================================
# INTAKE_READY: conjunction, never an average -- the headline property
# ===========================================================================

def test_intake_ready_true_when_every_condition_is_met_or_not_applicable():
    result = vic.evaluate_intake_readiness([
        {"name": "dut_boundary", "status": "MET"},
        {"name": "vip_resolution", "status": "MET"},
        {"name": "active_driver_conflict", "status": "NOT_APPLICABLE",
         "reason": "single-driver project"},
        {"name": "critical_bind", "status": "MET"},
    ])
    assert result.ready is True
    assert result.status == vic.READY
    assert result.blocking == []
    assert result.evaluated_count == 4


def test_single_unmet_condition_among_ninety_nine_clean_ones_blocks_readiness():
    # This is the headline "no averaging" proof: 99 clean conditions and one
    # UNMET condition must still report NOT ready, never a rounded-up pass.
    conditions = [{"name": f"cond_{i}", "status": "MET"} for i in range(99)]
    conditions.append({"name": "known_pass_test", "status": "UNMET",
                       "reason": "no test has ever reached PASS for this environment"})
    result = vic.evaluate_intake_readiness(conditions)
    assert result.ready is False
    assert result.status == vic.NOT_READY
    assert result.evaluated_count == 100
    assert len(result.blocking) == 1
    assert result.blocking[0]["name"] == "known_pass_test"
    assert len(result.clear) == 99


def test_unknown_status_condition_blocks_exactly_like_unmet():
    result = vic.evaluate_intake_readiness([
        {"name": "a", "status": "MET"},
        {"name": "b", "status": "UNKNOWN", "reason": "could not resolve"},
    ])
    assert result.ready is False
    assert result.blocking[0]["name"] == "b"
    assert result.blocking[0]["status"] == "UNKNOWN"


def test_empty_condition_list_reports_not_available_never_a_vacuous_ready():
    result = vic.evaluate_intake_readiness([])
    assert result.ready is False
    assert result.status == vic.NOT_AVAILABLE
    assert result.evaluated_count == 0

    result_none = vic.evaluate_intake_readiness(None)
    assert result_none.status == vic.NOT_AVAILABLE
    assert result_none.ready is False


def test_unrecognized_condition_status_is_refused_not_silently_defaulted():
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.evaluate_intake_readiness([{"name": "a", "status": "PROBABLY_FINE"}])
    assert ei.value.reason == "UNKNOWN_CONDITION_STATUS"
    assert ei.value.detail["name"] == "a"


def test_duplicate_condition_name_is_refused_not_silently_resolved():
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.evaluate_intake_readiness([
            {"name": "dut_boundary", "status": "MET"},
            {"name": "dut_boundary", "status": "UNMET"},
        ])
    assert ei.value.reason == "DUPLICATE_CONDITION_NAME"
    assert ei.value.detail["name"] == "dut_boundary"


def test_malformed_condition_record_missing_status_key_is_refused():
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.evaluate_intake_readiness([{"name": "a"}])
    assert ei.value.reason == "MALFORMED_CONDITION_RECORD"


def test_malformed_condition_record_not_a_mapping_is_refused():
    with pytest.raises(vic.IntakeContractError) as ei:
        vic.evaluate_intake_readiness(["just_a_string"])
    assert ei.value.reason == "MALFORMED_CONDITION_RECORD"


# ===========================================================================
# Serialization / to_dict
# ===========================================================================

def test_contract_to_dict_round_trips_the_essential_fields():
    c = vic.create_contract("proj-7", sub_domain_data={"waivers": [{"id": "W1"}]})
    c = vic.transition_contract(c, "DISCOVERING", reason="go", by="agent_x")
    d = c.to_dict()
    assert d["contract_id"] == "proj-7"
    assert d["state"] == "DISCOVERING"
    assert d["sub_domains"] == {"waivers": [{"id": "W1"}]}
    assert len(d["state_history"]) == 2
    assert d["state_history"][-1]["by"] == "agent_x"
    # Must be JSON-serializable end to end (a real downstream consumer need).
    json.dumps(d)


def test_readiness_result_to_dict():
    result = vic.evaluate_intake_readiness([{"name": "a", "status": "MET"}])
    d = result.to_dict()
    assert d["ready"] is True
    assert d["status"] == "READY"
    json.dumps(d)


# ===========================================================================
# No governance/approval mechanism is referenced from this module's own source
# ===========================================================================

def _code_tokens_excluding_strings_and_comments(path):
    """Re-tokenizes the real source with every STRING/COMMENT token dropped,
    the same approach `test_loop_budget.py` established in this codebase for
    checking a module's own CODE (never its prose docstrings) against a
    forbidden-token list."""
    import io
    import tokenize
    with open(path, "rb") as f:
        toks = tokenize.tokenize(f.readline)
        kept = [t.string for t in toks
                if t.type not in (tokenize.STRING, tokenize.COMMENT, tokenize.NL,
                                  tokenize.NEWLINE, tokenize.ENCODING, tokenize.INDENT,
                                  tokenize.DEDENT)]
    return " ".join(kept)


def test_module_references_no_human_approval_or_governance_machinery():
    # The module's own DOCSTRINGS legitimately name these (explaining what
    # this module deliberately does NOT do) -- what must never appear is a
    # real reference to one of them in actual CODE.
    code = _code_tokens_excluding_strings_and_comments(vic.__file__)
    forbidden = [
        "ControlPlane", "can_signoff", "assert_human_approval",
        "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError",
        "git_governance",
    ]
    for token in forbidden:
        assert token not in code, f"unexpected governance reference in code: {token}"


def test_module_imports_nothing_else_from_dv_harness_per_its_own_scope():
    import ast
    src = Path(vic.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    dv_harness_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "dv_harness" in (node.module or ""):
            dv_harness_imports.append(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("dv_harness"):
                    dv_harness_imports.append(alias.name)
    assert dv_harness_imports == [], (
        f"this module must accept sub-domain data as generic parameters, never import another "
        f"dv_harness module: found {dv_harness_imports}")


# ===========================================================================
# Front door: python -m dv_harness.verification_intake_contract
# ===========================================================================

def _run_module(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.verification_intake_contract", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=60)


def test_cli_states_verb(tmp_path):
    proc = _run_module(["states"], Path(__file__).resolve().parents[1])
    assert proc.returncode == 0
    assert "CREATED" in proc.stdout
    assert "REVALIDATING" in proc.stdout


def test_cli_transitions_verb(tmp_path):
    root = Path(__file__).resolve().parents[1]
    proc = _run_module(["transitions", "--state", "READY_FOR_REVIEW"], root)
    assert proc.returncode == 0
    assert "BASELINED" in proc.stdout
    assert "CORRELATING" in proc.stdout


def test_cli_transitions_verb_unknown_state_exits_2(tmp_path):
    root = Path(__file__).resolve().parents[1]
    proc = _run_module(["transitions", "--state", "BOGUS"], root)
    assert proc.returncode == 2


def test_cli_evaluate_verb_ready(tmp_path):
    conditions_path = tmp_path / "conditions.json"
    conditions_path.write_text(json.dumps([
        {"name": "dut_boundary", "status": "MET"},
        {"name": "vip_resolution", "status": "NOT_APPLICABLE"},
    ]), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    proc = _run_module(["evaluate", "--conditions", str(conditions_path), "--json"], root)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "READY"


def test_cli_evaluate_verb_not_ready_exits_1(tmp_path):
    conditions_path = tmp_path / "conditions.json"
    conditions_path.write_text(json.dumps([
        {"name": "dut_boundary", "status": "MET"},
        {"name": "known_pass_test", "status": "UNMET", "reason": "never passed"},
    ]), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    proc = _run_module(["evaluate", "--conditions", str(conditions_path)], root)
    assert proc.returncode == 1
    assert "known_pass_test" in proc.stdout


def test_cli_evaluate_verb_empty_conditions_exits_2(tmp_path):
    conditions_path = tmp_path / "conditions.json"
    conditions_path.write_text("[]", encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    proc = _run_module(["evaluate", "--conditions", str(conditions_path)], root)
    assert proc.returncode == 2
