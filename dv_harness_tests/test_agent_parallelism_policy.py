"""Tests for dv_harness/agent_parallelism_policy.py -- section 244, the
POLICY layer (declared max_concurrent caps + task-class priority) on top of
`resource_orchestrator.py`'s real capacity/grant model.

Every license/queue fixture here is the REAL captured `lmutil lmstat` /
`bqueues` output `dv_harness_tests/test_preflight.py` already carries,
reached through `dv_harness_tests/test_resource_orchestrator.py`'s own
helper functions (IMPORTED, never re-typed) -- the same discipline that
module's own tests already follow. Nothing here contacts a live license
server, a live scheduler or a live LSF farm, and nothing submits, kills or
reserves a job.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import agent_parallelism_policy as app
from dv_harness import loop_budget
from dv_harness import resource_orchestrator as ro

from .test_resource_orchestrator import (
    _bqueues_with,
    _checks_with_seats,
    _license_outcome,
    _lmstat_with,
    _pressure,
    HEALTHY_LICENSE,
)

MODULE_PATH = Path(__file__).resolve().parents[1] / "dv_harness" / "agent_parallelism_policy.py"
MODULE_SRC = MODULE_PATH.read_text(encoding="utf-8")


def _pc(pid, stage, consumes=True, at="", slots=1, task_class=None, root=""):
    return app.PolicyContender(project_id=pid, stage=stage,
                               consumes_scarce_resource=consumes,
                               requested_at=at, slots_requested=slots,
                               task_class=task_class, root=root)


def _policy(priority_order=(app.TASK_CLASS_SIGNOFF_FAMILY, app.TASK_CLASS_EXECUTION,
                            app.TASK_CLASS_ANALYSIS),
           resource_caps=None) -> app.TaskClassPriorityPolicy:
    return app.TaskClassPriorityPolicy(
        schema_version=1, priority_order=tuple(priority_order),
        resource_caps=dict(resource_caps or {}))


# ==========================================================================
# The shipped default policy really loads and validates
# ==========================================================================
class TestDefaultPolicyFile:

    def test_the_shipped_policy_loads_and_declares_no_cap_by_default(self):
        policy = app.load_policy()
        assert policy.schema_version == 1
        assert list(policy.priority_order) == [
            app.TASK_CLASS_SIGNOFF_FAMILY, app.TASK_CLASS_EXECUTION, app.TASK_CLASS_ANALYSIS]
        assert policy.resource_caps == {}
        assert policy.source_path == str(app.DEFAULT_POLICY_PATH)


# ==========================================================================
# Policy validation: a malformed policy is refused, never assumed permissive
# ==========================================================================
class TestPolicyValidation:

    def _write(self, tmp_path, data) -> Path:
        p = Path(tmp_path) / "policy.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_a_missing_policy_file_is_refused(self):
        with pytest.raises(app.AgentParallelismPolicyError, match="no agent parallelism policy"):
            app.load_policy("/does/not/exist/policy.json")

    def test_invalid_json_is_refused(self, tmp_path):
        p = Path(tmp_path) / "policy.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(app.AgentParallelismPolicyError, match="not valid JSON"):
            app.load_policy(p)

    def test_wrong_schema_version_is_refused(self, tmp_path):
        p = self._write(tmp_path, {"schema_version": 2, "task_class_priority": ["A"]})
        with pytest.raises(app.AgentParallelismPolicyError, match="schema_version"):
            app.load_policy(p)

    def test_empty_task_class_priority_is_refused(self, tmp_path):
        p = self._write(tmp_path, {"schema_version": 1, "task_class_priority": []})
        with pytest.raises(app.AgentParallelismPolicyError, match="non-empty"):
            app.load_policy(p)

    def test_a_duplicate_task_class_is_refused(self, tmp_path):
        p = self._write(tmp_path, {"schema_version": 1,
                                   "task_class_priority": ["A", "A"]})
        with pytest.raises(app.AgentParallelismPolicyError, match="more than once"):
            app.load_policy(p)

    def test_a_non_string_task_class_entry_is_refused(self, tmp_path):
        p = self._write(tmp_path, {"schema_version": 1, "task_class_priority": ["A", 3]})
        with pytest.raises(app.AgentParallelismPolicyError, match="non-empty strings"):
            app.load_policy(p)

    def test_a_cap_with_no_reason_is_refused(self, tmp_path):
        """An uncited concurrency cap is exactly the unsupported number the
        Evidence Truth Rule forbids."""
        p = self._write(tmp_path, {
            "schema_version": 1, "task_class_priority": ["A"],
            "resources": {"eda_license": {"max_concurrent": 3}}})
        with pytest.raises(app.AgentParallelismPolicyError, match="no real reason"):
            app.load_policy(p)

    def test_a_boolean_max_concurrent_is_refused(self, tmp_path):
        """bool is an int subclass -- `true` must never silently read as 1."""
        p = self._write(tmp_path, {
            "schema_version": 1, "task_class_priority": ["A"],
            "resources": {"eda_license": {"max_concurrent": True, "reason": "x"}}})
        with pytest.raises(app.AgentParallelismPolicyError, match="positive integer"):
            app.load_policy(p)

    def test_a_non_positive_max_concurrent_is_refused(self, tmp_path):
        p = self._write(tmp_path, {
            "schema_version": 1, "task_class_priority": ["A"],
            "resources": {"eda_license": {"max_concurrent": 0, "reason": "x"}}})
        with pytest.raises(app.AgentParallelismPolicyError, match="positive integer"):
            app.load_policy(p)

    def test_a_valid_cap_loads_cleanly(self, tmp_path):
        p = self._write(tmp_path, {
            "schema_version": 1, "task_class_priority": ["SIGNOFF_FAMILY", "EXECUTION"],
            "resources": {"eda_license": {"max_concurrent": 3,
                                          "reason": "admin ceiling on concurrent VCS agents"}}})
        policy = app.load_policy(p)
        assert policy.resource_caps["eda_license"].max_concurrent == 3
        assert "admin ceiling" in policy.resource_caps["eda_license"].reason


# ==========================================================================
# Task-class resolution: DECLARED always wins; DERIVED is grounded in real
# facts already computed elsewhere in this codebase, never a new guess.
# ==========================================================================
class TestResolveTaskClass:

    def test_a_critical_stage_derives_signoff_family(self):
        task_class, resolution = app.resolve_task_class("SIGNOFF", True)
        assert task_class == app.TASK_CLASS_SIGNOFF_FAMILY
        assert resolution == app.RESOLUTION_DERIVED

    def test_execution_layer_work_derives_execution(self):
        task_class, resolution = app.resolve_task_class("BUILD_DEBUG", True)
        assert task_class == app.TASK_CLASS_EXECUTION
        assert resolution == app.RESOLUTION_DERIVED

    def test_non_consuming_work_derives_analysis(self):
        task_class, resolution = app.resolve_task_class("ARCH_DISCOVERY", False)
        assert task_class == app.TASK_CLASS_ANALYSIS
        assert resolution == app.RESOLUTION_DERIVED

    def test_a_project_configured_critical_stage_list_is_honoured(self):
        """The same override resource_orchestrator.arbitrate() itself takes."""
        task_class, _ = app.resolve_task_class("VERIFY", True, critical_stages=("VERIFY",))
        assert task_class == app.TASK_CLASS_SIGNOFF_FAMILY

    def test_an_explicit_declaration_always_wins_and_is_never_second_guessed(self):
        """RESEARCH work has no graph Stage at all (CLAUDE.md's own Research
        Front Door section), so it can never be DERIVED -- only DECLARED."""
        task_class, resolution = app.resolve_task_class(
            "SIGNOFF", True, declared="RESEARCH")
        assert task_class == "RESEARCH"
        assert resolution == app.RESOLUTION_DECLARED

    def test_a_blank_declared_task_class_is_refused(self):
        with pytest.raises(app.AgentParallelismPolicyError, match="non-empty string"):
            app.resolve_task_class("SIGNOFF", True, declared="   ")


# ==========================================================================
# apply_concurrency_cap(): narrows measured capacity, never widens it
# ==========================================================================
class TestConcurrencyCap:

    def test_no_declared_cap_leaves_measured_capacity_untouched(self):
        cap_free_policy = _policy(resource_caps={})
        measured = ro.FarmCapacity(slots_available=5, binding_constraint="license_free_seats")
        capped, info = app.apply_concurrency_cap(measured, cap_free_policy, "eda_license")
        assert capped is measured
        assert info["applied"] is False
        assert "never invented" in info["reason"]

    def test_a_tighter_declared_cap_narrows_measured_capacity(self):
        policy = _policy(resource_caps={
            "eda_license": app.ResourceConcurrencyCap(
                resource="eda_license", max_concurrent=2, reason="admin ceiling")})
        measured = ro.FarmCapacity(slots_available=5, binding_constraint="license_free_seats")
        capped, info = app.apply_concurrency_cap(measured, policy, "eda_license")
        assert capped.slots_available == 2
        assert capped.binding_constraint == "agent_parallelism_policy:eda_license"
        assert info["applied"] is True
        assert info["measured_slots_available"] == 5
        assert info["reason"] == "admin ceiling"

    def test_a_looser_declared_cap_never_widens_measured_capacity(self):
        """A cap can only narrow -- it must never be read as a claim of
        additional room resource_orchestrator never actually measured."""
        policy = _policy(resource_caps={
            "eda_license": app.ResourceConcurrencyCap(
                resource="eda_license", max_concurrent=99, reason="admin ceiling")})
        measured = ro.FarmCapacity(slots_available=5, binding_constraint="license_free_seats")
        capped, info = app.apply_concurrency_cap(measured, policy, "eda_license")
        assert capped.slots_available == 5
        assert info["applied"] is False
        assert "never widened" in info["reason"]

    def test_a_declared_cap_bounds_even_when_nothing_was_measured(self):
        """The genuinely new capability: resource_orchestrator's own rule for
        an UNMEASURED capacity is 'grant everything, do not invent scarcity'
        -- correct for a MEASUREMENT. A DECLARED administrative ceiling is a
        different kind of fact and this is the one place it can still bind."""
        policy = _policy(resource_caps={
            "farm": app.ResourceConcurrencyCap(resource="farm", max_concurrent=3, reason="admin cap")})
        unmeasured = ro.FarmCapacity()
        assert unmeasured.slots_available is None
        capped, info = app.apply_concurrency_cap(unmeasured, policy, "farm")
        assert capped.slots_available == 3
        assert info["applied"] is True
        assert info["measured_slots_available"] is None

    def test_a_cap_declared_for_a_different_resource_name_never_applies(self):
        policy = _policy(resource_caps={
            "lsf_queue": app.ResourceConcurrencyCap(resource="lsf_queue", max_concurrent=1,
                                                    reason="x")})
        measured = ro.FarmCapacity(slots_available=5)
        capped, info = app.apply_concurrency_cap(measured, policy, "eda_license")
        assert capped.slots_available == 5
        assert info["applied"] is False


# ==========================================================================
# Contender coercion: the same "declare it explicitly, never default it"
# discipline resource_orchestrator._coerce_request already applies.
# ==========================================================================
class TestCoerceContender:

    def test_missing_required_fields_are_refused(self):
        with pytest.raises(app.AgentParallelismPolicyError, match="missing required field"):
            app._coerce_contender({"stage": "SIGNOFF", "consumes_scarce_resource": True})

    def test_omitting_consumes_scarce_resource_is_refused(self):
        with pytest.raises(app.AgentParallelismPolicyError, match="consumes_scarce_resource"):
            app._coerce_contender({"project_id": "p", "stage": "SIGNOFF"})

    def test_a_zero_slot_contender_is_refused(self):
        with pytest.raises(app.AgentParallelismPolicyError, match="slots_requested"):
            app._coerce_contender(_pc("p", "SIGNOFF", slots=0))

    def test_a_blank_declared_task_class_is_refused(self):
        c = app.PolicyContender(project_id="p", stage="SIGNOFF",
                                consumes_scarce_resource=True, task_class="   ")
        with pytest.raises(app.AgentParallelismPolicyError, match="task_class"):
            app._coerce_contender(c)

    def test_a_dict_contender_round_trips_its_task_class(self):
        c = app._coerce_contender({"project_id": "p", "stage": "SIGNOFF",
                                   "consumes_scarce_resource": True,
                                   "task_class": "RESEARCH"})
        assert c.task_class == "RESEARCH"

    def test_a_non_dict_non_contender_is_refused(self):
        with pytest.raises(app.AgentParallelismPolicyError, match="PolicyContender or a dict"):
            app._coerce_contender(42)


# ==========================================================================
# The whole point: task-class priority orders GRANTs regardless of arrival
# order, negative-controlled against plain resource_orchestrator alone.
# ==========================================================================
class TestPolicyTieredArbitration:

    def _contenders(self):
        # EXECUTION work asked FIRST (older) -- FIFO alone would win it.
        exec_reqs = [_pc(f"exec{i}", "BUILD_DEBUG", at=f"2026-09-06T07:0{i}:00")
                    for i in range(3)]
        # SIGNOFF_FAMILY work asked LATER (younger).
        signoff_reqs = [_pc(f"signoff{i}", "SIGNOFF", at=f"2026-09-06T09:0{i}:00")
                       for i in range(3)]
        return exec_reqs, signoff_reqs

    def test_negative_control_plain_resource_orchestrator_lets_fifo_win(self):
        """The gap, demonstrated: with no measured pressure,
        prioritize_stage() gives SIGNOFF no special standing at all, so plain
        resource_orchestrator grants the OLDER, lower-importance work."""
        exec_reqs, signoff_reqs = self._contenders()
        plain_reqs = [ro.ResourceRequest(project_id=c.project_id, stage=c.stage,
                                         consumes_scarce_resource=True,
                                         requested_at=c.requested_at)
                     for c in exec_reqs + signoff_reqs]
        checks = _checks_with_seats(2)
        assert _pressure(*checks).level == loop_budget.PRESSURE_NONE
        plan = ro.orchestrate(plain_reqs, checks=checks, queue="vcs")
        granted = {a.project_id for a in plan.by_decision(ro.ALLOCATION_GRANTED)}
        assert granted == {"exec0", "exec1"}, granted

    def test_the_policy_layer_grants_signoff_family_first_regardless_of_arrival(self):
        exec_reqs, signoff_reqs = self._contenders()
        checks = _checks_with_seats(2)
        plan = app.orchestrate_with_policy(
            exec_reqs + signoff_reqs, resource_name="eda_license",
            checks=checks, queue="vcs")
        by_pid = {a.project_id: a for a in plan.allocations}
        granted = {a.project_id for a in plan.by_decision(ro.ALLOCATION_GRANTED)}
        assert granted == {"signoff0", "signoff1"}, granted   # FIFO within the tier
        assert by_pid["signoff0"].task_class == app.TASK_CLASS_SIGNOFF_FAMILY
        assert by_pid["signoff0"].task_class_resolution == app.RESOLUTION_DERIVED
        assert by_pid["signoff0"].policy_tier_rank == 0
        assert by_pid["exec0"].task_class == app.TASK_CLASS_EXECUTION
        assert by_pid["exec0"].policy_tier_rank == 1
        # The tier report shows capacity really carried over, exhausted.
        tier_names = [t["task_class"] for t in plan.tiers]
        assert tier_names == [app.TASK_CLASS_SIGNOFF_FAMILY, app.TASK_CLASS_EXECUTION]
        signoff_tier, exec_tier = plan.tiers
        assert signoff_tier["granted"] == 2
        assert exec_tier["granted"] == 0
        assert exec_tier["contenders"] == 3
        assert plan.capacity_cap["applied"] is False   # default policy declares no cap

    def test_within_one_tier_the_anti_monopoly_and_fifo_rules_still_apply(self):
        """Not re-implemented -- delegated verbatim to one real
        resource_orchestrator.arbitrate() call per tier."""
        reqs = [_pc("c", "BUILD_DEBUG", at="2026-09-06T09:00:00"),
               _pc("a", "BUILD_DEBUG", at="2026-09-06T09:00:00"),
               _pc("b", "BUILD_DEBUG", at="2026-09-06T09:00:00")]
        plan = app.orchestrate_with_policy(
            reqs, resource_name="eda_license", checks=_checks_with_seats(1), queue="vcs")
        assert [a.project_id for a in plan.allocations] == ["a", "b", "c"]

    def test_a_loop_budget_defer_is_still_carried_through_unchanged(self):
        """The policy layer decides ORDER between classes; it never overturns
        a real DEFER from loop_budget.prioritize_stage()."""
        checks = [_license_outcome(_lmstat_with(1000, 995))]   # ELEVATED pressure
        assert _pressure(*checks).level == loop_budget.PRESSURE_ELEVATED
        plan = app.orchestrate_with_policy(
            [_pc("p", "BUILD_DEBUG", at="2026-09-06T09:00:00")],
            resource_name="eda_license", checks=checks, queue="vcs")
        alloc = plan.allocations[0]
        assert alloc.decision == ro.ALLOCATION_DEFERRED
        assert alloc.priority == loop_budget.PRIORITY_DEFER

    def test_an_unranked_declared_task_class_is_processed_last_never_dropped(self):
        """A class no policy ever ranked is neither an error nor a guess: it
        is grouped into its own final tier."""
        reqs = [_pc("research", "SIGNOFF", at="2026-09-06T05:00:00",
                    task_class="RESEARCH"),
               _pc("routine", "BUILD_DEBUG", at="2026-09-06T09:00:00")]
        plan = app.orchestrate_with_policy(
            reqs, resource_name="eda_license", checks=_checks_with_seats(1), queue="vcs")
        by_pid = {a.project_id: a for a in plan.allocations}
        assert by_pid["research"].task_class == "RESEARCH"
        assert by_pid["research"].task_class_resolution == app.RESOLUTION_DECLARED
        assert by_pid["research"].policy_tier_rank is None
        # EXECUTION (ranked) beats an unranked class even though "research"
        # asked first and even names a critical-sounding stage.
        assert by_pid["routine"].decision == ro.ALLOCATION_GRANTED
        assert by_pid["research"].decision == ro.ALLOCATION_QUEUED
        tier_names = [t["task_class"] for t in plan.tiers]
        assert tier_names[-1] == "UNRANKED"

    def test_a_declared_concurrency_cap_narrows_the_whole_arbitration(self):
        policy = _policy(resource_caps={
            "eda_license": app.ResourceConcurrencyCap(
                resource="eda_license", max_concurrent=1, reason="admin ceiling of 1 agent")})
        reqs = [_pc("a", "SIGNOFF", at="2026-09-06T09:00:00"),
               _pc("b", "SIGNOFF", at="2026-09-06T09:01:00")]
        plan = app.orchestrate_with_policy(
            reqs, resource_name="eda_license", checks=_checks_with_seats(5), queue="vcs",
            policy=policy)
        assert plan.capacity["slots_available"] == 5           # the real measurement, unchanged
        assert plan.capacity_cap["applied"] is True
        assert plan.capacity_cap["declared_max_concurrent"] == 1
        granted = plan.by_decision(ro.ALLOCATION_GRANTED)
        assert len(granted) == 1 and granted[0].project_id == "a"

    def test_a_malformed_contender_in_the_list_is_refused(self):
        with pytest.raises(app.AgentParallelismPolicyError):
            app.arbitrate_with_policy(
                [{"project_id": "a", "stage": "SIGNOFF"}],   # no consumes_scarce_resource
                pressure=_pressure(), capacity=ro.FarmCapacity(), resource_name="eda_license")

    def test_resource_name_is_required(self):
        with pytest.raises(app.AgentParallelismPolicyError, match="resource_name"):
            app.arbitrate_with_policy(
                [], pressure=_pressure(), capacity=ro.FarmCapacity(), resource_name="")


# ==========================================================================
# Front door
# ==========================================================================
class TestExecuteVerb:

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_policy_verb_returns_the_loaded_policy(self):
        code, payload = app.execute_verb(self.tmp, "policy")
        assert code == 0
        assert payload["policy"]["schema_version"] == 1
        assert app.TASK_CLASS_SIGNOFF_FAMILY in payload["policy"]["priority_order"]
        assert payload["derivable_task_classes"] == list(app.DERIVABLE_TASK_CLASSES)

    def test_policy_verb_exits_2_on_an_invalid_policy_path(self, tmp_path):
        bad = Path(tmp_path) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        code, payload = app.execute_verb(self.tmp, "policy", policy_path=str(bad))
        assert code == 2 and payload["error"] == "POLICY_INVALID"

    def test_plan_requires_a_resource_name(self):
        code, payload = app.execute_verb(self.tmp, "plan")
        assert code == 1 and payload["error"] == "RESOURCE_NAME_REQUIRED"

    def test_plan_requires_a_requests_file(self):
        code, payload = app.execute_verb(self.tmp, "plan", resource_name="eda_license")
        assert code == 1 and payload["error"] == "REQUESTS_FILE_REQUIRED"

    def test_plan_over_a_requests_file_exits_2_when_someone_is_queued(self, tmp_path):
        p = Path(tmp_path) / "reqs.json"
        p.write_text(json.dumps([
            {"project_id": "a", "stage": "BUILD_DEBUG", "consumes_scarce_resource": True,
             "requested_at": "2026-09-06T08:00:00"},
            {"project_id": "b", "stage": "BUILD_DEBUG", "consumes_scarce_resource": True,
             "requested_at": "2026-09-06T09:00:00"},
        ]), encoding="utf-8")
        code, payload = app.execute_verb(
            self.tmp, "plan", requests_path=str(p), resource_name="eda_license",
            queue="vcs", checks=_checks_with_seats(1))
        assert code == 2
        assert payload["granted"] == 1 and payload["queued"] == 1
        assert "authorizes nothing" in payload["disclosure"]

    def test_plan_exits_0_when_nobody_is_held_back(self, tmp_path):
        p = Path(tmp_path) / "reqs.json"
        p.write_text(json.dumps([
            {"project_id": "a", "stage": "BUILD_DEBUG", "consumes_scarce_resource": True}]),
            encoding="utf-8")
        code, _ = app.execute_verb(
            self.tmp, "plan", requests_path=str(p), resource_name="eda_license",
            queue="vcs", checks=_checks_with_seats(20))
        assert code == 0

    def test_plan_reports_a_malformed_contender_rather_than_crashing(self, tmp_path):
        p = Path(tmp_path) / "reqs.json"
        p.write_text(json.dumps([{"project_id": "a", "stage": "S"}]), encoding="utf-8")
        code, payload = app.execute_verb(
            self.tmp, "plan", requests_path=str(p), resource_name="eda_license")
        assert code == 1 and payload["error"] == "MALFORMED_CONTENDER"

    def test_plan_reports_a_non_list_requests_file(self, tmp_path):
        p = Path(tmp_path) / "reqs.json"
        p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        code, payload = app.execute_verb(
            self.tmp, "plan", requests_path=str(p), resource_name="eda_license")
        assert code == 1 and payload["error"] == "REQUESTS_FILE_MUST_BE_A_JSON_LIST"

    def test_unknown_verb(self):
        code, payload = app.execute_verb(self.tmp, "grant-now")
        assert code == 1 and payload["error"] == "UNKNOWN_VERB"


class TestCliSubprocess:

    def test_policy_verb_runs_as_a_real_subprocess(self):
        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.agent_parallelism_policy", "policy"],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["policy"]["schema_version"] == 1

    def test_plan_verb_runs_as_a_real_subprocess(self, tmp_path):
        p = Path(tmp_path) / "reqs.json"
        p.write_text(json.dumps([
            {"project_id": "a", "stage": "BUILD_DEBUG", "consumes_scarce_resource": True}]),
            encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.agent_parallelism_policy", "plan",
             "--resource-name", "eda_license", "--requests", str(p)],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, timeout=60)
        # No --checks flag exists on this CLI, so nothing is measured; per
        # resource_orchestrator's own "do not invent scarcity" rule, an
        # unmeasured capacity grants everyone -- exit 0, nobody held back.
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["resource_name"] == "eda_license"
        assert payload["queued"] == 0 and payload["deferred"] == 0


# ==========================================================================
# Boundaries: reuse, not reinvention; nothing here submits or approves
# ==========================================================================
class TestBoundaries:

    def test_no_human_approval_gate_is_referenced(self):
        import io
        import tokenize

        toks = []
        with io.open(MODULE_PATH, encoding="utf-8") as fh:
            for tok in tokenize.generate_tokens(fh.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                                tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                    continue
                toks.append(tok.string)
        code_only = " ".join(toks)
        for token in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError"):
            assert token not in code_only, f"{token} must not be reached from this module"

    def test_nothing_here_submits_kills_or_modifies_a_job(self):
        for token in ("bsub", "bkill", "subprocess.run", "save_job_state",
                      "bsub_submit", "bsub_submit_with_preflight", "register_external_job"):
            assert token not in MODULE_SRC, f"{token} must not be reached from this module"

    def test_it_calls_the_real_arbitrate_rather_than_reimplementing_ranking(self):
        import ast

        tree = ast.parse(MODULE_SRC)
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "arbitrate" in called
        assert "def arbitrate(" not in MODULE_SRC   # not a second definition
        assert "def _coerce_request(" not in MODULE_SRC

    def test_it_defines_no_second_capacity_or_pressure_measurement(self):
        for token in ("lmutil", "Users of", "QUEUE_NAME", "parse_license_availability",
                      "parse_queue_capacity", "_parse_bqueues_output"):
            assert token not in MODULE_SRC, f"{token} suggests a second probe/parse here"
        assert "capacity_from_checks" in MODULE_SRC
        assert "pressure_from_checks" in MODULE_SRC
