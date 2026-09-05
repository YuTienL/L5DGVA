"""Tests for dv_harness/resource_orchestrator.py -- VI-5, global cross-job /
cross-project EDA resource orchestration.

Every license/queue fixture here is the REAL captured `lmutil lmstat` /
`bqueues` output `dv_harness_tests/test_preflight.py` already uses (gathered
2026-09-03 against the real project license server/queue), IMPORTED from that
module rather than re-typed, and mutated only in the numbers that carry the
meaning under test -- the same discipline `test_harness_reliability.py` and
`test_loop_budget.py` already follow. No test here contacts a live license
server, a live scheduler or a live LSF farm, and nothing here submits, kills or
reserves a job: `orchestrate()`'s LSF listing arrives through an injected
`job_lister`/`live_jobs`, and the module's own source is asserted to contain no
submission verb.

The multi-job LSF state is a clearly-labelled FIXTURE: `_bjobs_records()`
builds `lsf_client.discover_live_jobs()`-shaped dicts (job_id / stat / queue /
exec_host / job_name / submit_time). This project has no multi-job farm to
measure, and the cross-job arbitration decision is exercised against that
fixture rather than against a fabricated claim about a real farm.
"""
import ast
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import loop_budget, preflight
from dv_harness import resource_orchestrator as ro
from dv_harness.memory import MemoryStore

from .test_preflight import (
    REAL_BQUEUES_VCS_OPEN_ACTIVE,
    REAL_LMSTAT_VCS_HEADER,
    _ScriptedRunner,
    _result as _res,
)

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "dv_harness" / "resource_orchestrator.py"
MODULE_SRC = MODULE_PATH.read_text(encoding="utf-8")


def _code_only(path: Path) -> str:
    """The module's CODE tokens, with every comment and string literal
    dropped -- the same technique test_loop_budget.py already uses, for the
    same reason: this module's prose deliberately names the gates and the
    submission verbs it stays away from."""
    import io
    import tokenize

    toks = []
    with io.open(path, encoding="utf-8") as fh:
        for tok in tokenize.generate_tokens(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                            tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                continue
            toks.append(tok.string)
    return " ".join(toks)


MODULE_CODE = _code_only(MODULE_PATH)


# --------------------------------------------------------------------------
# Real-transcript fixtures, mutated only where the meaning under test lives
# --------------------------------------------------------------------------
def _lmstat_with(issued: int, in_use: int, feature: str = "VCSRuntime") -> str:
    """The real captured lmstat text with ONE feature's counts replaced."""
    old = (f"Users of {feature}:  (Total of 99 licenses issued;  "
           f"Total of 0 licenses in use)")
    assert old in REAL_LMSTAT_VCS_HEADER, "real fixture no longer carries the expected row"
    return REAL_LMSTAT_VCS_HEADER.replace(
        old,
        f"Users of {feature}:  (Total of {issued} licenses issued;  "
        f"Total of {in_use} licenses in use)")


def _bqueues_with(max_jobs, njobs: int, run: int = None) -> str:
    """The real captured bqueues row with a real MAX/NJOBS declared.

    The captured PRODUCTION queue reports MAX as `-` (no limit), which is
    itself under test below; this is what a capacity-limited queue looks like,
    and it is how most tests here bound capacity WITHOUT also moving the
    license-headroom pressure reading -- capacity and pressure are two
    different facts and a test that moved both at once would not show which
    one produced the decision."""
    run = njobs if run is None else run
    return (
        "QUEUE_NAME      PRIO STATUS          MAX JL/U JL/P JL/H NJOBS  PEND   RUN  SUSP\n"
        f"vcs              30  Open:Active     {'-' if max_jobs is None else max_jobs:>3}"
        f"    5    -    -  {njobs:>4}     0  {run:>4}     0\n"
    )


REAL_BQUEUES_VCS_MAX_20 = _bqueues_with(20, 12)

#: A healthy license reading: 99 issued, none in use. Headroom 1.0, so
#: `loop_budget.pressure_from_checks()` reports PRESSURE_NONE and the ONLY
#: thing bounding the grant set in those tests is the queue.
HEALTHY_LICENSE = REAL_LMSTAT_VCS_HEADER


def _license_outcome(stdout: str) -> preflight.CheckOutcome:
    cfg = preflight.PreflightConfig(license_server="2900@host-a", queue="vcs",
                                    license_features=["VCSRuntime"])
    return preflight.check_license(_ScriptedRunner([_res(stdout=stdout)]), cfg)


def _queue_outcome(stdout: str) -> preflight.CheckOutcome:
    cfg = preflight.PreflightConfig(license_server="2900@host-a", queue="vcs")
    return preflight.check_queue_health(_ScriptedRunner([_res(stdout=stdout)]), cfg)


def _bjobs_records(*specs) -> list:
    """`lsf_client.discover_live_jobs()`-shaped FIXTURE records.

    Clearly labelled as a fixture: this project has no multi-job LSF farm, so
    the cross-job state under test is synthetic. The SHAPE is the real one --
    the exact keys `discover_live_jobs()` builds from a real `bjobs -json`
    response -- so the code under test reads it exactly as it would read the
    farm."""
    out = []
    for job_id, stat in specs:
        out.append({"job_id": job_id, "stat": stat, "queue": "vcs",
                    "exec_host": "host-b", "job_name": f"sim_{job_id}",
                    "submit_time": "Sep  6 09:00"})
    return out


def _checks_with_seats(free_slots: int):
    """A REAL pair of preflight outcomes whose only scarcity is queue slots.

    The license reads healthy (PRESSURE_NONE), so nothing here is deferred by
    LOOP-3's section-92 rule and the grant set is bounded by capacity alone --
    which is exactly the decision this module adds."""
    return [_license_outcome(HEALTHY_LICENSE),
            _queue_outcome(_bqueues_with(20, 20 - free_slots))]


def _req(pid, stage, consumes=True, root="", at="", slots=1):
    return ro.ResourceRequest(project_id=pid, stage=stage,
                              consumes_scarce_resource=consumes,
                              root=root, requested_at=at, slots_requested=slots)


def _pressure(*checks):
    return loop_budget.pressure_from_checks(list(checks))


# ==========================================================================
# preflight's new queue-capacity parse (the data source, not a second probe)
# ==========================================================================
class TestQueueCapacityParse:

    def test_real_production_queue_reports_no_max_as_none_never_zero(self):
        """The REAL captured queue prints MAX as `-`. Reading that as 0 would
        defer every job on the farm, so it must be None."""
        row = preflight.parse_queue_capacity(REAL_BQUEUES_VCS_OPEN_ACTIVE, "vcs")
        assert row["status"] == "Open:Active"
        assert row["MAX"] is None
        assert row["NJOBS"] == 12
        assert row["RUN"] == 12
        assert row["PEND"] == 0

    def test_a_real_max_and_per_user_limit_are_read(self):
        row = preflight.parse_queue_capacity(REAL_BQUEUES_VCS_MAX_20, "vcs")
        assert row["MAX"] == 20
        assert row["JL/U"] == 5
        assert row["NJOBS"] == 12

    def test_column_position_comes_from_the_header_not_a_fixed_index(self):
        """`bqueues -o` lets a site reorder columns. A hardcoded index would
        silently read PEND as MAX; resolving from the header must not."""
        reordered = (
            "QUEUE_NAME      STATUS          NJOBS  MAX PRIO  PEND   RUN\n"
            "vcs             Open:Active        12   20   30     0    12\n"
        )
        row = preflight.parse_queue_capacity(reordered, "vcs")
        assert row["MAX"] == 20
        assert row["NJOBS"] == 12

    def test_unknown_queue_is_none_not_an_empty_capacity(self):
        assert preflight.parse_queue_capacity(REAL_BQUEUES_VCS_MAX_20, "regress") is None

    def test_check_queue_health_still_reaches_the_same_verdict(self):
        """Extending the parse must not move the PASS/FAIL boundary."""
        assert _queue_outcome(REAL_BQUEUES_VCS_OPEN_ACTIVE).status == "PASS"
        closed = REAL_BQUEUES_VCS_OPEN_ACTIVE.replace("Open:Active", "Closed:Inact")
        assert _queue_outcome(closed).status == "FAIL"

    def test_queue_pass_now_carries_its_raw_output_for_capacity_rederivation(self):
        out = _queue_outcome(REAL_BQUEUES_VCS_MAX_20)
        assert out.status == "PASS"
        assert "QUEUE_NAME" in (out.evidence or ""), "PASS path must carry the real bqueues text"


# ==========================================================================
# Capacity, measured from the real checks only
# ==========================================================================
class TestCapacity:

    def test_scarcest_feature_is_the_binding_constraint(self):
        """A run needs every feature it uses, so the pool that bounds how many
        more jobs can start is the tightest one -- not the sum."""
        text = _lmstat_with(99, 97, "VCSRuntime")
        text = text.replace(
            "Users of VCSCompiler:  (Total of 99 licenses issued;  Total of 0 licenses in use)",
            "Users of VCSCompiler:  (Total of 99 licenses issued;  Total of 40 licenses in use)")
        cap = ro.capacity_from_checks([_license_outcome(text)], queue="vcs")
        assert cap.license_feature == "VCSRuntime"
        assert cap.license_free_seats == 2
        assert cap.slots_available == 2
        assert cap.binding_constraint == "license_free_seats"

    def test_queue_can_be_the_binding_constraint_instead_of_the_license(self):
        cap = ro.capacity_from_checks(
            [_license_outcome(_lmstat_with(99, 0)), _queue_outcome(REAL_BQUEUES_VCS_MAX_20)],
            queue="vcs")
        assert cap.license_free_seats == 99
        assert cap.queue_slots_free == 8      # MAX 20 - NJOBS 12
        assert cap.slots_available == 8
        assert cap.binding_constraint == "queue_slots_free"

    def test_nothing_measured_is_unmeasured_not_zero(self):
        cap = ro.capacity_from_checks([], queue="vcs")
        assert cap.slots_available is None
        assert cap.measured is False
        assert "do not invent scarcity" in cap.sources["slots_available_reason"]

    def test_a_failing_license_check_yields_no_capacity_number_and_says_why(self):
        """A starved pool is PRESSURE_CRITICAL, which every contender already
        reads through prioritize_stage(). Restating it as capacity 0 would
        double-count one fact."""
        starved = _lmstat_with(99, 99)
        out = _license_outcome(starved)
        assert out.status == "FAIL"
        cap = ro.capacity_from_checks([out], queue="vcs")
        assert cap.license_free_seats is None
        assert cap.slots_available is None
        assert "did not PASS" in cap.sources["license"]["free_seats_reason"]

    def test_the_queue_name_is_read_from_the_checks_own_detail_when_not_supplied(self):
        """A caller handing over outcomes without also naming the queue must
        still get a capacity -- read from the check's OWN `queue '<name>'`
        wording, never from a hardcoded default that could name a queue the
        outcome is not about."""
        cap = ro.capacity_from_checks([_queue_outcome(REAL_BQUEUES_VCS_MAX_20)])
        assert cap.queue == "vcs"
        assert cap.queue_slots_free == 8
        assert cap.slots_available == 8

    def test_live_jobs_are_observed_but_never_subtracted(self):
        """lmstat in_use and bqueues NJOBS already count the running jobs.
        Subtracting them again would manufacture scarcity."""
        live = _bjobs_records((1, "RUN"), (2, "RUN"), (3, "PEND"), (4, "DONE"), (5, "EXIT"))
        cap = ro.capacity_from_checks([_license_outcome(_lmstat_with(99, 89))],
                                      queue="vcs", live_jobs=live)
        assert cap.live_jobs_observed == 3      # DONE/EXIT hold no slot
        assert cap.slots_available == 10        # unchanged by the observation


# ==========================================================================
# THE cross-job decision: N contenders against ONE measured capacity
# ==========================================================================
class TestBoundedGrantSet:

    def _five_contenders(self):
        return [_req(f"proj{i}", "BUILD_DEBUG", at=f"2026-09-06T09:0{i}:00")
                for i in range(5)]

    def test_negative_control_loop_budget_alone_grants_all_five(self):
        """The gap, demonstrated. `prioritize_stage()` takes one stage and one
        pressure reading and has no argument through which a second job could
        be visible, so with two free seats it still returns PROCEED five
        times. That is what the orchestrator has to bound."""
        checks = _checks_with_seats(2)
        pressure = _pressure(*checks)
        assert pressure.level == loop_budget.PRESSURE_NONE
        verdicts = [loop_budget.prioritize_stage(
            r.stage, pressure, consumes_scarce_resource=True).decision
            for r in self._five_contenders()]
        assert verdicts == [loop_budget.PRIORITY_PROCEED] * 5

    def test_five_contenders_two_free_seats_grants_exactly_two(self):
        plan = ro.orchestrate(self._five_contenders(), checks=_checks_with_seats(2),
                              queue="vcs")
        assert plan.capacity["slots_available"] == 2
        granted = plan.by_decision(ro.ALLOCATION_GRANTED)
        queued = plan.by_decision(ro.ALLOCATION_QUEUED)
        assert len(granted) == 2, [a.to_dict() for a in plan.allocations]
        assert len(queued) == 3
        assert plan.slots_committed == 2
        # FIFO within the tier: the two oldest requests won.
        assert [a.project_id for a in granted] == ["proj0", "proj1"]

    def test_the_grant_set_shrinks_with_the_measured_capacity(self):
        """Same five contenders, a genuinely scarcer reading, fewer grants --
        so the bound really is read from the measurement."""
        for free, expect in ((4, 4), (1, 1)):
            plan = ro.orchestrate(self._five_contenders(),
                                  checks=_checks_with_seats(free), queue="vcs")
            assert plan.capacity["slots_available"] == free
            assert len(plan.by_decision(ro.ALLOCATION_GRANTED)) == expect

    def test_unmeasured_capacity_grants_everything_and_says_so(self):
        """Do not invent scarcity: nothing measured must never defer real work."""
        plan = ro.orchestrate(self._five_contenders(), checks=[], queue="vcs")
        assert plan.capacity["measured"] is False
        assert len(plan.by_decision(ro.ALLOCATION_GRANTED)) == 5
        assert plan.by_decision(ro.ALLOCATION_QUEUED) == []
        assert "no capacity bound is claimed" in plan.allocations[0].reason

    def test_a_head_of_line_request_is_not_jumped_by_a_smaller_one(self):
        """Granting the small one because it happens to fit would invert the
        ranking and let the large one starve indefinitely."""
        big = _req("big", "BUILD_DEBUG", at="2026-09-06T09:00:00", slots=4)
        small = _req("small", "BUILD_DEBUG", at="2026-09-06T09:05:00", slots=1)
        plan = ro.orchestrate([big, small], checks=_checks_with_seats(2), queue="vcs")
        by_pid = {a.project_id: a for a in plan.allocations}
        assert by_pid["big"].decision == ro.ALLOCATION_QUEUED
        assert by_pid["small"].decision == ro.ALLOCATION_QUEUED
        assert "head of the line" in by_pid["big"].reason.lower()
        assert plan.slots_committed == 0

    def test_work_consuming_none_of_the_resource_is_granted_and_charged_nothing(self):
        """Deferring a pure analysis stage would delay the project and free
        nothing -- the same reasoning prioritize_stage() rule 2 applies one
        level down, lifted to the grant set."""
        reqs = [_req("analysis", "ARCH_DISCOVERY", consumes=False, at="2026-09-06T09:09:00"),
                _req("build_a", "BUILD_DEBUG", at="2026-09-06T09:00:00"),
                _req("build_b", "BUILD_DEBUG", at="2026-09-06T09:01:00")]
        plan = ro.orchestrate(reqs, checks=_checks_with_seats(1), queue="vcs")
        by_pid = {a.project_id: a for a in plan.allocations}
        assert plan.capacity["slots_available"] == 1
        assert by_pid["analysis"].decision == ro.ALLOCATION_GRANTED
        assert by_pid["build_a"].decision == ro.ALLOCATION_GRANTED
        assert by_pid["build_b"].decision == ro.ALLOCATION_QUEUED
        assert plan.slots_committed == 1     # the analysis stage charged nothing


class TestRanking:

    def test_the_critical_tier_separates_only_under_measured_pressure(self):
        """Both halves of the honest behaviour, in one test.

        The tier is `loop_budget.prioritize_stage()`'s, not a second rule
        here, and that function escalates a signoff-family stage to
        PROCEED_CRITICAL only under measured pressure. So with NO pressure a
        SIGNOFF contender is an ordinary tier-1 contender and FIFO decides --
        inventing a permanent priority for it would be a rule section 92 does
        not state. Once pressure is real, the tier separates them."""
        reqs = [_req("routine", "BUILD_DEBUG", at="2026-09-06T08:00:00"),
                _req("closing", "SIGNOFF", at="2026-09-06T11:00:00")]

        calm = ro.orchestrate(reqs, checks=_checks_with_seats(1), queue="vcs")
        calm_by_pid = {a.project_id: a for a in calm.allocations}
        assert calm.pressure["level"] == loop_budget.PRESSURE_NONE
        assert calm_by_pid["routine"].priority == loop_budget.PRIORITY_PROCEED
        assert calm_by_pid["closing"].priority == loop_budget.PRIORITY_PROCEED
        assert calm_by_pid["routine"].decision == ro.ALLOCATION_GRANTED   # FIFO
        assert calm_by_pid["closing"].decision == ro.ALLOCATION_QUEUED

        tight = ro.orchestrate(reqs, checks=[_license_outcome(_lmstat_with(1000, 995))],
                               queue="vcs")
        tight_by_pid = {a.project_id: a for a in tight.allocations}
        assert tight.pressure["level"] == loop_budget.PRESSURE_ELEVATED
        assert tight_by_pid["closing"].priority == loop_budget.PRIORITY_PROCEED_CRITICAL
        assert tight_by_pid["closing"].decision == ro.ALLOCATION_GRANTED
        assert tight_by_pid["routine"].decision == ro.ALLOCATION_DEFERRED

    def test_negative_control_without_pressure_the_same_pair_both_proceed(self):
        """The critical tier only decides the ORDER; it is not a claim that
        SIGNOFF is special whenever there is room for both."""
        reqs = [_req("routine", "BUILD_DEBUG", at="2026-09-06T08:00:00"),
                _req("closing", "SIGNOFF", at="2026-09-06T11:00:00")]
        plan = ro.orchestrate(reqs, checks=_checks_with_seats(20), queue="vcs")
        assert all(a.decision == ro.ALLOCATION_GRANTED for a in plan.allocations)

    def test_a_project_already_holding_farm_slots_ranks_below_one_holding_none(self):
        """The anti-monopoly signal that exists ONLY at this level: no per-job
        check can see how much of the farm the asking project already has."""
        tmp = Path(tempfile.mkdtemp())
        try:
            hog, newcomer = tmp / "hog", tmp / "newcomer"
            for r, ids in ((hog, [101, 102, 103]), (newcomer, [])):
                d = r / ".dv-harness" / "lsf" / "jobs"
                d.mkdir(parents=True)
                for jid in ids:
                    (d / f"{jid}.json").write_text(json.dumps({"job_id": jid}), encoding="utf-8")
            live = _bjobs_records((101, "RUN"), (102, "RUN"), (103, "PEND"), (999, "RUN"))
            # The hog asked FIRST, so FIFO alone would have granted it.
            reqs = [_req("hog", "BUILD_DEBUG", root=str(hog), at="2026-09-06T08:00:00"),
                    _req("newcomer", "BUILD_DEBUG", root=str(newcomer),
                         at="2026-09-06T10:00:00")]
            plan = ro.orchestrate(reqs, checks=_checks_with_seats(1), queue="vcs", live_jobs=live)
            by_pid = {a.project_id: a for a in plan.allocations}
            assert by_pid["hog"].held_slots == 3
            assert by_pid["newcomer"].held_slots == 0
            assert by_pid["newcomer"].decision == ro.ALLOCATION_GRANTED
            assert by_pid["hog"].decision == ro.ALLOCATION_QUEUED
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_negative_control_no_live_listing_leaves_the_fairness_key_inert(self):
        """'Nobody looked' is not 'this project holds nothing'. With no
        listing the ranking must fall back to FIFO, not silently treat every
        project as holding zero and reorder on a fact nobody measured."""
        tmp = Path(tempfile.mkdtemp())
        try:
            hog = tmp / "hog"
            d = hog / ".dv-harness" / "lsf" / "jobs"
            d.mkdir(parents=True)
            for jid in (101, 102, 103):
                (d / f"{jid}.json").write_text(json.dumps({"job_id": jid}), encoding="utf-8")
            reqs = [_req("hog", "BUILD_DEBUG", root=str(hog), at="2026-09-06T08:00:00"),
                    _req("newcomer", "BUILD_DEBUG", root=str(tmp / "newcomer"),
                         at="2026-09-06T10:00:00")]
            plan = ro.orchestrate(reqs, checks=_checks_with_seats(1), queue="vcs")
            by_pid = {a.project_id: a for a in plan.allocations}
            assert by_pid["hog"].held_slots is None
            assert by_pid["hog"].decision == ro.ALLOCATION_GRANTED     # FIFO wins
            assert by_pid["newcomer"].decision == ro.ALLOCATION_QUEUED
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_partially_measured_fairness_signal_ranks_nothing(self):
        """One project measurable, one not (its request names no root). Reading
        the unknown as 0 would let a project nobody measured beat one measured
        at three; sorting it last would penalise it for a measurement this
        harness failed to take. Neither happens -- the term goes inert for
        everyone and FIFO decides."""
        tmp = Path(tempfile.mkdtemp())
        try:
            hog = tmp / "hog"
            d = hog / ".dv-harness" / "lsf" / "jobs"
            d.mkdir(parents=True)
            for jid in (101, 102, 103):
                (d / f"{jid}.json").write_text(json.dumps({"job_id": jid}), encoding="utf-8")
            live = _bjobs_records((101, "RUN"), (102, "RUN"), (103, "RUN"))
            reqs = [_req("hog", "BUILD_DEBUG", root=str(hog), at="2026-09-06T08:00:00"),
                    _req("rootless", "BUILD_DEBUG", at="2026-09-06T10:00:00")]
            plan = ro.orchestrate(reqs, checks=_checks_with_seats(1), queue="vcs",
                                  live_jobs=live)
            by_pid = {a.project_id: a for a in plan.allocations}
            assert by_pid["hog"].held_slots == 3
            assert by_pid["rootless"].held_slots is None
            # FIFO, not the half-measured fairness term.
            assert by_pid["hog"].decision == ro.ALLOCATION_GRANTED
            assert by_pid["rootless"].decision == ro.ALLOCATION_QUEUED
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_request_declaring_no_arrival_time_cannot_jump_ahead_of_one_that_does(self):
        reqs = [_req("undated", "BUILD_DEBUG"),
                _req("dated", "BUILD_DEBUG", at="2026-09-06T23:59:00")]
        plan = ro.orchestrate(reqs, checks=_checks_with_seats(1), queue="vcs")
        by_pid = {a.project_id: a for a in plan.allocations}
        assert by_pid["dated"].decision == ro.ALLOCATION_GRANTED
        assert by_pid["undated"].decision == ro.ALLOCATION_QUEUED

    def test_the_plan_is_deterministic_under_input_reordering(self):
        reqs = [_req("c", "BUILD_DEBUG", at="2026-09-06T09:00:00"),
                _req("a", "BUILD_DEBUG", at="2026-09-06T09:00:00"),
                _req("b", "BUILD_DEBUG", at="2026-09-06T09:00:00")]
        checks = _checks_with_seats(1)
        first = ro.orchestrate(list(reqs), checks=checks, queue="vcs").to_dict()
        second = ro.orchestrate(list(reversed(reqs)), checks=checks, queue="vcs").to_dict()
        assert first["allocations"] == second["allocations"]
        assert [a["project_id"] for a in first["allocations"]] == ["a", "b", "c"]


class TestLoopBudgetDecisionIsNeverOverturned:

    def test_a_loop_budget_defer_is_carried_through_unchanged(self):
        """Under ELEVATED pressure LOOP-3 defers non-critical consuming work.
        This module records that verdict and never converts it to a grant."""
        checks = [_license_outcome(_lmstat_with(1000, 995))]   # 0.5% headroom
        pressure = _pressure(*checks)
        assert pressure.level == loop_budget.PRESSURE_ELEVATED
        plan = ro.orchestrate([_req("p", "BUILD_DEBUG", at="2026-09-06T09:00:00")],
                              checks=checks, queue="vcs")
        alloc = plan.allocations[0]
        assert alloc.decision == ro.ALLOCATION_DEFERRED
        assert alloc.priority == loop_budget.PRIORITY_DEFER
        assert alloc.priority_reason == loop_budget.prioritize_stage(
            "BUILD_DEBUG", pressure, consumes_scarce_resource=True).reason
        assert alloc.rank is None      # a deferred contender is not ranked for capacity

    def test_a_deferred_contender_frees_capacity_for_a_critical_one(self):
        checks = [_license_outcome(_lmstat_with(1000, 995))]
        reqs = [_req("routine", "BUILD_DEBUG", at="2026-09-06T08:00:00"),
                _req("closing", "SIGNOFF", at="2026-09-06T09:00:00")]
        plan = ro.orchestrate(reqs, checks=checks, queue="vcs")
        by_pid = {a.project_id: a for a in plan.allocations}
        assert by_pid["routine"].decision == ro.ALLOCATION_DEFERRED
        assert by_pid["closing"].decision == ro.ALLOCATION_GRANTED

    def test_critical_pressure_from_a_starved_pool_defers_ordinary_work(self):
        checks = [_license_outcome(_lmstat_with(99, 99))]
        assert _pressure(*checks).level == loop_budget.PRESSURE_CRITICAL
        plan = ro.orchestrate([_req("p", "VERIFY", at="2026-09-06T09:00:00")],
                              checks=checks, queue="vcs")
        assert plan.allocations[0].decision == ro.ALLOCATION_DEFERRED


# ==========================================================================
# Cross-PROJECT contenders, off the registry this codebase already has
# ==========================================================================
def _make_project(root: Path, *, stage: str, skills, started_at="") -> None:
    (root / ".dv-harness" / "graph").mkdir(parents=True, exist_ok=True)
    # A real MemoryStore with a real record: the registry refuses a root with
    # no store, and its identity-collision guard needs real memory_ids to
    # compare, so an empty store would make that guard untestable.
    MemoryStore(root).add("project", {"kind": "note", "text": f"seed for {root.name}"})
    graph = {"nodes": [{"id": stage, "route": "r", "agent": "a", "skills": list(skills)}],
             "edges": []}
    (root / ".dv-harness" / "graph" / "main_graph.json").write_text(
        json.dumps(graph), encoding="utf-8")
    (root / ".dv-harness" / "state.json").write_text(json.dumps({
        "current_stage": stage,
        "stages": {stage: {"stage": stage, "status": "RUNNING", "started_at": started_at}},
    }), encoding="utf-8")


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


class TestCrossProjectContenders:

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.host = self.tmp / "host"
        self.host.mkdir()

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _register(self, name, **kw):
        root = self.tmp / name
        root.mkdir()
        _make_project(root, **kw)
        from dv_harness.cross_project_mining import ProjectRegistry
        ProjectRegistry(self.host).register(root, project_id=name)
        return root

    def test_consumption_is_derived_from_real_node_skills_not_the_stage_name(self):
        """A stage-name guess is exactly what prioritize_stage()'s own
        docstring forbids. Two projects sit on the SAME stage id; only the one
        whose node really declares an execution-layer skill consumes."""
        self._register("builder", stage="BUILD_DEBUG",
                       skills=list(ro.execution_preflight_skills())[:1],
                       started_at="2026-09-06T09:00:00")
        self._register("reader", stage="BUILD_DEBUG", skills=["doc-review"],
                       started_at="2026-09-06T09:01:00")
        reqs, skipped = ro.contenders_from_registry(self.host)
        assert skipped == []
        by_pid = {r.project_id: r for r in reqs}
        assert by_pid["builder"].consumes_scarce_resource is True
        assert by_pid["reader"].consumes_scarce_resource is False
        assert by_pid["builder"].requested_at == "2026-09-06T09:00:00"

    def test_a_project_with_no_state_is_skipped_with_a_real_reason(self):
        """Inventing a contender for it would put a project into an
        arbitration it never asked to join."""
        root = self.tmp / "quiet"
        root.mkdir()
        MemoryStore(root).add("project", {"kind": "note", "text": "seed"})
        from dv_harness.cross_project_mining import ProjectRegistry
        ProjectRegistry(self.host).register(root, project_id="quiet")
        reqs, skipped = ro.contenders_from_registry(self.host)
        assert reqs == []
        assert skipped[0]["reason"] == "NO_STATE_JSON_OR_NO_CURRENT_STAGE"

    def test_a_stage_absent_from_that_projects_graph_is_skipped_not_guessed(self):
        root = self.tmp / "odd"
        root.mkdir()
        _make_project(root, stage="BUILD_DEBUG", skills=["vcs-build"])
        state = json.loads((root / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
        state["current_stage"] = "A_STAGE_THIS_GRAPH_DOES_NOT_HAVE"
        (root / ".dv-harness" / "state.json").write_text(json.dumps(state), encoding="utf-8")
        from dv_harness.cross_project_mining import ProjectRegistry
        ProjectRegistry(self.host).register(root, project_id="odd")
        reqs, skipped = ro.contenders_from_registry(self.host)
        assert reqs == []
        assert skipped[0]["reason"] == "STAGE_NOT_FOUND_IN_PROJECT_GRAPH"

    def test_one_store_registered_twice_cannot_become_two_contenders(self):
        """The registry's OWN identity guard, reused rather than reimplemented:
        two contenders out of one audit trail would be a fabricated
        cross-project contention."""
        from dv_harness.cross_project_mining import (ProjectRegistry,
                                                     ProjectIdentityCollisionError)
        a = self._register("a", stage="BUILD_DEBUG", skills=["vcs-build"])
        clone = self.tmp / "clone"
        shutil.copytree(a, clone)
        with pytest.raises(ProjectIdentityCollisionError):
            ProjectRegistry(self.host).register(clone, project_id="clone")
        reqs, _ = ro.contenders_from_registry(self.host)
        assert [r.project_id for r in reqs] == ["a"]

    def test_two_real_projects_arbitrate_against_one_seat(self):
        """End to end: two separately-built real project trees, contenders
        derived from what is really on their disks, one measured seat."""
        self._register("early", stage="BUILD_DEBUG", skills=["vcs-build"],
                       started_at="2026-09-06T08:00:00")
        self._register("late", stage="BUILD_DEBUG", skills=["vcs-build"],
                       started_at="2026-09-06T12:00:00")
        reqs, _ = ro.contenders_from_registry(self.host)
        plan = ro.orchestrate(reqs, checks=_checks_with_seats(1), queue="vcs")
        by_pid = {a.project_id: a for a in plan.allocations}
        assert by_pid["early"].decision == ro.ALLOCATION_GRANTED
        assert by_pid["late"].decision == ro.ALLOCATION_QUEUED

    def test_arbitrating_writes_nothing_into_any_contending_project(self):
        """Reading is never a mutating act -- asserted byte for byte, so a
        future edit that persists a reservation fails here."""
        a = self._register("a", stage="BUILD_DEBUG", skills=["vcs-build"],
                           started_at="2026-09-06T08:00:00")
        b = self._register("b", stage="BUILD_DEBUG", skills=["vcs-build"],
                           started_at="2026-09-06T09:00:00")
        before = (_tree_digest(a), _tree_digest(b))
        reqs, _ = ro.contenders_from_registry(self.host)
        ro.orchestrate(reqs, checks=_checks_with_seats(1), queue="vcs")
        assert (_tree_digest(a), _tree_digest(b)) == before


# ==========================================================================
# Front door
# ==========================================================================
class TestExecuteVerb:

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ranking_rule_is_printable_data_not_only_a_docstring(self):
        code, payload = ro.execute_verb(self.tmp, "ranking-rule")
        assert code == 0
        assert len(payload["ranking_rule"]) == 4
        assert payload["decisions"] == list(ro.ALLOCATION_DECISIONS)

    def test_capacity_exits_2_when_nothing_was_measured(self):
        code, payload = ro.execute_verb(self.tmp, "capacity", checks=[], queue="vcs")
        assert code == 2 and payload["measured"] is False

    def test_capacity_exits_0_on_a_real_measurement(self):
        code, payload = ro.execute_verb(
            self.tmp, "capacity", checks=[_license_outcome(_lmstat_with(99, 90))], queue="vcs")
        assert code == 0 and payload["slots_available"] == 9

    def test_plan_over_a_requests_file_exits_2_when_a_contender_is_held_back(self):
        p = self.tmp / "reqs.json"
        p.write_text(json.dumps([
            {"project_id": "a", "stage": "BUILD_DEBUG", "consumes_scarce_resource": True,
             "requested_at": "2026-09-06T08:00:00"},
            {"project_id": "b", "stage": "BUILD_DEBUG", "consumes_scarce_resource": True,
             "requested_at": "2026-09-06T09:00:00"},
        ]), encoding="utf-8")
        code, payload = ro.execute_verb(
            self.tmp, "plan", requests_path=str(p), queue="vcs",
            checks=_checks_with_seats(1))
        assert code == 2
        assert payload["granted"] == 1 and payload["queued"] == 1
        assert "authorizes nothing" in payload["disclosure"]

    def test_plan_exits_0_when_nobody_is_held_back(self):
        p = self.tmp / "reqs.json"
        p.write_text(json.dumps([
            {"project_id": "a", "stage": "BUILD_DEBUG", "consumes_scarce_resource": True},
        ]), encoding="utf-8")
        code, _ = ro.execute_verb(self.tmp, "plan", requests_path=str(p), queue="vcs",
                                  checks=_checks_with_seats(20))
        assert code == 0

    def test_an_empty_registry_is_no_contenders_not_an_empty_plan(self):
        code, payload = ro.execute_verb(self.tmp, "plan")
        assert code == 2 and payload["error"] == "NO_CONTENDERS"

    def test_a_request_omitting_consumes_scarce_resource_is_refused(self):
        """Defaulting it either way would either defer analysis work that frees
        nothing, or grant execution work no capacity was checked for."""
        p = self.tmp / "reqs.json"
        p.write_text(json.dumps([{"project_id": "a", "stage": "BUILD_DEBUG"}]),
                     encoding="utf-8")
        code, payload = ro.execute_verb(self.tmp, "plan", requests_path=str(p))
        assert code == 1 and payload["error"] == "MALFORMED_REQUEST"

    def test_a_zero_slot_request_is_refused(self):
        with pytest.raises(ro.ResourceOrchestratorError):
            ro.arbitrate([{"project_id": "a", "stage": "S",
                           "consumes_scarce_resource": True, "slots_requested": 0}],
                         pressure=_pressure(), capacity=ro.FarmCapacity())

    def test_unknown_verb(self):
        code, payload = ro.execute_verb(self.tmp, "allocate-now")
        assert code == 1 and payload["error"] == "UNKNOWN_VERB"


# ==========================================================================
# Boundaries: authorizes nothing, submits nothing, probes nothing itself
# ==========================================================================
class TestBoundaries:

    def test_no_human_approval_gate_is_referenced(self):
        """Not one line of the approval boundary may be reached from here.

        Scanned over CODE only, by the same tokenize approach
        `test_loop_budget.py::test_this_module_touches_no_approval_mechanism`
        established: docstrings and comments legitimately NAME these gates
        (saying which ones stay untouched is the point of that prose), so
        scanning raw text would assert the opposite of what this means."""
        for token in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError",
                      "approve"):
            assert token not in MODULE_CODE, f"{token} must not be reached from this module"

    def test_nothing_here_submits_kills_or_modifies_a_job(self):
        """An orchestrator that could submit would be a far worse defect than
        the gap it closes: it would turn a ranking statement into an action no
        preflight gate stood in front of."""
        for token in ("bsub", "bkill", "subprocess", "system", "save_job_state",
                      "bsub_submit", "bsub_submit_with_preflight", "register_external_job"):
            assert token not in MODULE_CODE, f"{token} must not be reached from this module"

    def test_it_defines_no_second_license_or_queue_parse(self):
        """The resource facts must arrive through preflight's own parses --
        two parses of one lmstat output is two answers to one question."""
        for token in ("lmutil", "Users of", "QUEUE_NAME", "_parse_lmstat_output",
                      "_parse_bqueues_output"):
            assert token not in MODULE_CODE, f"{token} suggests a second probe/parse here"
        assert "parse_license_availability" in MODULE_CODE
        assert "parse_queue_capacity" in MODULE_CODE

    def test_it_calls_loop_budget_rather_than_restating_its_rules(self):
        tree = ast.parse(MODULE_SRC)
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "prioritize_stage" in called
        assert "pressure_from_checks" in called

    def test_orchestrate_probes_nothing_without_an_injected_transport(self):
        """With no checks and no runner it must measure nothing and claim
        nothing -- never read a missing binary as a full farm."""
        plan = ro.orchestrate([_req("a", "BUILD_DEBUG")], checks=None)
        assert plan.pressure["level"] == loop_budget.PRESSURE_UNKNOWN
        assert plan.capacity["measured"] is False

    def test_an_injected_runner_reaches_preflights_own_checks_via_degradation(self):
        """The one probing path, exercised: an explicitly injected transport
        goes through `degradation.probe_resources()`, i.e. `check_license()` /
        `check_queue_health()` themselves. Asserted by the REAL command strings
        the injected runner was asked to run -- if this module ever grew a
        probe of its own, those commands would not be preflight's."""
        runner = _ScriptedRunner([_res(stdout=_lmstat_with(20, 18)),
                                  _res(stdout=_bqueues_with(20, 15))])
        plan = ro.orchestrate([_req("a", "BUILD_DEBUG", at="2026-09-06T08:00:00"),
                               _req("b", "BUILD_DEBUG", at="2026-09-06T09:00:00"),
                               _req("c", "BUILD_DEBUG", at="2026-09-06T10:00:00")],
                              cfg={"preflight": {"license_server": "2900@host-a",
                                                 "queue": "vcs",
                                                 "license_features": ["VCSRuntime"]}},
                              runner=runner, queue="vcs")
        issued = [cmd for cmd, _timeout in runner.calls]
        assert any("lmstat" in c and "2900@host-a" in c for c in issued), issued
        assert any(c.startswith("bqueues") for c in issued), issued
        # 20 licenses with 18 out is 2 free at 10% headroom (NOT below the
        # 0.10 pressure fraction, so nothing is deferred); the queue has 5.
        # The license is the binding constraint and exactly two are granted.
        assert plan.pressure["level"] == loop_budget.PRESSURE_NONE
        assert plan.capacity["binding_constraint"] == "license_free_seats"
        assert plan.capacity["slots_available"] == 2
        assert len(plan.by_decision(ro.ALLOCATION_GRANTED)) == 2
        assert len(plan.by_decision(ro.ALLOCATION_QUEUED)) == 1

    def test_a_failing_job_lister_is_not_observed_rather_than_an_empty_farm(self):
        def boom(_vcuser):
            raise RuntimeError("bjobs not found on PATH")

        plan = ro.orchestrate([_req("a", "BUILD_DEBUG")],
                              checks=[_license_outcome(_lmstat_with(99, 0))],
                              queue="vcs", vcuser="svcacct", job_lister=boom)
        assert plan.capacity["live_jobs_observed"] is None
        assert "no live LSF listing supplied" in plan.capacity["sources"]["live_jobs"]["note"]

    def test_the_default_job_lister_is_the_real_discover_live_jobs(self):
        """Reuse, not a second bjobs caller -- asserted without invoking it."""
        import inspect

        from dv_harness import lsf_client
        src = inspect.getsource(ro._default_job_lister)
        assert "discover_live_jobs" in src
        assert callable(lsf_client.discover_live_jobs)

    def test_allocation_vocabulary_does_not_collide_with_status_or_priority(self):
        from dv_harness.models import Status
        statuses = {s.value for s in Status}
        priorities = {loop_budget.PRIORITY_PROCEED, loop_budget.PRIORITY_PROCEED_CRITICAL,
                      loop_budget.PRIORITY_DEFER}
        assert not (set(ro.ALLOCATION_DECISIONS) & statuses)
        # DEFERRED is deliberately distinct from loop_budget's DEFER verb.
        assert not (set(ro.ALLOCATION_DECISIONS) & priorities)
