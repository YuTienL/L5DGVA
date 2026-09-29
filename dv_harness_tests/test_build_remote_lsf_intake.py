"""Tests for dv_harness/build_remote_lsf_intake.py.

Per this project's Evidence Truth Rule and its own real-evidence testing
convention (see dv_harness_tests/test_preflight.py's own module docstring),
the central integration test drives the REAL `preflight.run_preflight()`
against a scripted Runner fed this project's own REAL captured lmstat/
bqueues/df/env-var transcripts (the exact same transcript text
test_preflight.py's own `REAL_*` constants carry -- copied here rather than
cross-imported, since dv_harness_tests is a package and test modules are not
meant to import one another's private helpers; the transcript CONTENT is
still the identical real 2026-09-03 captured evidence, not re-typed
fiction) -- so the resulting `PreflightResult` is a real object of the exact
shape `preflight.py`'s own test suite already trusts, not a hand-shaped
stand-in. Negative-control tests construct individual
`preflight.CheckOutcome`/`TransportDecision` objects directly, which is
legitimate for a narrow unit test of this module's own status-mapping rules
(never used to fabricate a claim about a real license/queue/relay server).
"""
from __future__ import annotations

import pytest

from dv_harness import build_remote_lsf_intake as brli
from dv_harness import intake_state
from dv_harness import preflight as pf
from dv_harness import question_queue


def _result(stdout="", ok=True, exit_code=0, error=None, stderr=""):
    return pf.CommandResult(ok=ok, exit_code=exit_code, stdout=stdout, stderr=stderr, error=error)


class _ScriptedRunner:
    """A pure-mock Runner: returns the next canned CommandResult for each
    call, in order. Mirrors dv_harness_tests/test_preflight.py's own
    identically-named helper -- preflight.py's own design goal is that every
    Runner is injectable and pure, so this module's tests never make a live
    call to license/scheduler infrastructure either."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def __call__(self, cmd, timeout=60):
        self.calls.append((cmd, timeout))
        if not self._results:
            raise AssertionError(f"_ScriptedRunner ran out of canned results at call: {cmd!r}")
        return self._results.pop(0)


# Real captured transcripts, identical to dv_harness_tests/test_preflight.py's
# own REAL_* fixtures (see that module's docstring for full provenance:
# gathered live 2026-09-03 against this project's real remote DV server over
# an already-READY persistent relay).
REAL_BQUEUES_VCS_OPEN_ACTIVE = (
    "QUEUE_NAME      PRIO STATUS          MAX JL/U JL/P JL/H NJOBS  PEND   RUN  SUSP\n"
    "vcs              30  Open:Active       -    -    -    -    12     0    12     0\n"
)

REAL_LMSTAT_VCS_HEADER = (
    "lmutil - Copyright (c) 1989-2009 Acresso Software Inc. All Rights Reserved.\n"
    "Flexible License Manager status on Thu 9/3/2026 14:19\n"
    "License server status: 2900@host-a\n"
    "    License file(s) on host-a: /home/eda/flexlm/host-a/synopsys/license.dat:\n"
    "     host-a: license server UP (MASTER) v10.8\n"
    "Vendor daemon status (on host-a):\n"
    "   snpslmd: UP v11.19\n"
    "Feature usage info:\n"
    "Users of VCSRuntime:  (Total of 99 licenses issued;  Total of 0 licenses in use)\n"
    "Users of VCSCompiler:  (Total of 99 licenses issued;  Total of 0 licenses in use)\n"
)

REAL_DF_WORKDIR = (
    "Filesystem                               1024-blocks       Used  Available Capacity Mounted on\n"
    "f200.icatchtek.com.tw:/ifs/proj1/svcacct  5368709120 3709058368 1659650752      70% /home/svcacct\n"
)

REAL_ENV_ALL_SET = "VCS_HOME_SET\nUVM_HOME_SET\nVERDI_HOME_SET\n"


ENV_OWNER = question_queue.route_owner("env")


def _real_full_preflight_pass() -> pf.PreflightResult:
    """Drives the REAL preflight.run_preflight() against this project's own
    real captured transcripts (license UP w/ headroom, queue Open:Active,
    workdir present+writable+enough space, all 3 env vars set) -> a real
    all-PASS PreflightResult."""
    cfg = pf.PreflightConfig(
        queue="vcs", workdir="/home/svcacct/DV/UVM/USB/usb_uvm/sim",
        license_server="2900@host-a", license_features=["VCSRuntime"],
        min_free_disk_gb=1.0,
    )
    runner = _ScriptedRunner([
        _result(stdout=REAL_LMSTAT_VCS_HEADER),                       # eda_license
        _result(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),                 # lsf_queue_health
        _result(stdout="host-c\n"),                                  # host_reachability
        _result(stdout=REAL_DF_WORKDIR),                              # disk_space
        _result(stdout="DIR_EXISTS\nDIR_WRITABLE\n"),                 # workdir
        _result(stdout=REAL_ENV_ALL_SET),                             # eda_env_vars
    ])
    return pf.run_preflight(cfg, runner=runner)


# ---------------------------------------------------------------------------
# real end-to-end: a genuine all-PASS preflight run -> AUTO_RESOLVED fields
# ---------------------------------------------------------------------------

class TestRealPreflightAllPass:
    def test_all_six_checks_map_to_auto_resolved_with_real_evidence(self):
        result = _real_full_preflight_pass()
        assert result.overall == "PASS"
        records = brli.fields_from_preflight(result)
        by_field = {r.field: r for r in records}
        for field_name, check_name in brli.FIELD_TO_CHECK_NAME.items():
            rec = by_field[field_name]
            assert rec.category == brli.CATEGORY
            assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
            assert rec.confidence == "HIGH"
            assert rec.value == "PASS"
            assert rec.source == f"preflight:{check_name}"
            assert rec.owner == ENV_OWNER
            assert rec.reason  # real detail text carried through

    def test_readiness_ready_true_when_transport_also_confirmed(self):
        result = _real_full_preflight_pass()
        decision = pf.TransportDecision(
            requested="auto", resolved=pf.TRANSPORT_LOCAL, available=True,
            reason="auto: running where the real license/scheduler binaries exist on PATH.",
            evidence={"local": {"ready": True}},
        )
        records = brli.fields_from_preflight(result, decision)
        readiness = brli.evaluate_build_remote_lsf_readiness(records)
        assert readiness.ready is True
        assert readiness.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
        assert len(readiness.fields) == len(brli.FIELD_NAMES)

    def test_merge_into_intake_state_preserves_existing_fields_and_adds_new_ones(self):
        result = _real_full_preflight_pass()
        decision = pf.TransportDecision(
            requested="auto", resolved=pf.TRANSPORT_LOCAL, available=True,
            reason="auto: running where the real license/scheduler binaries exist on PATH.",
            evidence={"local": {"ready": True}},
        )
        base = intake_state.IntakeState([
            intake_state.IntakeFieldRecord(
                field="dut_rtl", category="general", value="rtl_ok", source="env_manifest:dut_facts.rtl",
                confidence="HIGH", status=intake_state.IntakeFieldStatus.AUTO_RESOLVED.value,
                reason="present",
            ),
        ])
        merged = brli.merge_into_intake_state(base, result, decision)
        assert merged.get("dut_rtl") is not None  # untouched original field survives
        assert merged.get("lsf_configured") is not None
        assert merged.category_status(brli.CATEGORY) == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
        # base is not mutated
        assert base.get("lsf_configured") is None

    def test_merge_with_no_transport_decision_leaves_category_missing_worst_wins(self):
        # The transport field defaults to MISSING when no TransportDecision is
        # supplied, and MISSING outranks AUTO_RESOLVED in the worst-wins fold
        # -- an unresolved fact must never be hidden by five resolved ones.
        result = _real_full_preflight_pass()
        base = intake_state.IntakeState([])
        merged = brli.merge_into_intake_state(base, result)
        assert merged.category_status(brli.CATEGORY) == intake_state.IntakeFieldStatus.MISSING.value


# ---------------------------------------------------------------------------
# a real FAIL check must BLOCK, never be smoothed over
# ---------------------------------------------------------------------------

class TestRealPreflightWithAFail:
    def test_a_real_lsf_queue_fail_blocks_only_that_field_and_the_category(self):
        cfg = pf.PreflightConfig(
            queue="vcs", workdir="/home/svcacct/DV/UVM/USB/usb_uvm/sim",
            license_server="2900@host-a", license_features=["VCSRuntime"],
            min_free_disk_gb=1.0,
        )
        closed_queue = (
            "QUEUE_NAME      PRIO STATUS          MAX JL/U JL/P JL/H NJOBS  PEND   RUN  SUSP\n"
            "vcs              30  Closed:Inactive   -    -    -    -     0     0     0     0\n"
        )
        runner = _ScriptedRunner([
            _result(stdout=REAL_LMSTAT_VCS_HEADER),
            _result(stdout=closed_queue),
            _result(stdout="host-c\n"),
            _result(stdout=REAL_DF_WORKDIR),
            _result(stdout="DIR_EXISTS\nDIR_WRITABLE\n"),
            _result(stdout=REAL_ENV_ALL_SET),
        ])
        result = pf.run_preflight(cfg, runner=runner)
        assert result.overall == "BLOCKED"
        assert result.blocked_on == ["lsf_queue_health"]

        records = brli.fields_from_preflight(result)
        by_field = {r.field: r for r in records}
        assert by_field["lsf_configured"].status == intake_state.IntakeFieldStatus.BLOCKED.value
        assert by_field["lsf_configured"].confidence == "HIGH"
        assert "Closed" in by_field["lsf_configured"].reason or "vcs" in by_field["lsf_configured"].reason
        # every OTHER field stays AUTO_RESOLVED -- a single FAIL never bleeds
        # into an unrelated field's own real evidence.
        for field_name in brli.FIELD_TO_CHECK_NAME:
            if field_name == "lsf_configured":
                continue
            assert by_field[field_name].status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value

        readiness = brli.evaluate_build_remote_lsf_readiness(records)
        assert readiness.ready is False
        assert readiness.status == intake_state.IntakeFieldStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# negative controls: absent evidence must never be fabricated into a pass
# ---------------------------------------------------------------------------

class TestNegativeControlsAbsentEvidence:
    def test_no_preflight_result_at_all_yields_missing_for_every_check_field(self):
        records = brli.fields_from_preflight(None, None)
        by_field = {r.field: r for r in records}
        for field_name in brli.FIELD_TO_CHECK_NAME:
            rec = by_field[field_name]
            assert rec.status == intake_state.IntakeFieldStatus.MISSING.value
            assert rec.confidence == "UNKNOWN"
            assert rec.value is None
            assert "preflight.run_preflight()" in rec.reason
        assert by_field[brli.TRANSPORT_FIELD_NAME].status == intake_state.IntakeFieldStatus.MISSING.value

        readiness = brli.evaluate_build_remote_lsf_readiness(records)
        assert readiness.ready is False
        assert readiness.status == intake_state.IntakeFieldStatus.MISSING.value

    def test_a_skip_check_is_missing_never_a_fabricated_not_applicable(self):
        # SKIP is a real, deliberate "this did not run" -- never silently
        # promoted to NOT_APPLICABLE (that would be exactly the silent
        # default the Evidence Truth Rule forbids).
        result = pf.PreflightResult(
            overall="PASS",
            checks=[pf.CheckOutcome(name="disk_space", status="SKIP",
                                     detail="no workdir configured; disk-space check skipped.")],
            blocked_on=[],
        )
        records = brli.fields_from_preflight(result)
        by_field = {r.field: r for r in records}
        rec = by_field["disk_space_sufficient"]
        assert rec.status == intake_state.IntakeFieldStatus.MISSING.value
        assert rec.confidence == "UNKNOWN"
        assert rec.value == "SKIP"
        assert "workdir configured" in rec.reason

    def test_an_unrecognized_check_status_string_is_unknown_not_a_guess(self):
        result = pf.PreflightResult(
            overall="PASS",
            checks=[pf.CheckOutcome(name="eda_license", status="WARN", detail="ambiguous vendor output")],
            blocked_on=[],
        )
        records = brli.fields_from_preflight(result)
        by_field = {r.field: r for r in records}
        rec = by_field["eda_license_available"]
        assert rec.status == intake_state.IntakeFieldStatus.UNKNOWN.value
        assert rec.confidence == "UNKNOWN"
        assert "WARN" in rec.reason

    def test_a_dict_shaped_preflight_result_is_accepted_identically(self):
        result = _real_full_preflight_pass()
        as_dict = result.to_dict()
        records_from_obj = brli.fields_from_preflight(result)
        records_from_dict = brli.fields_from_preflight(as_dict)
        assert [(r.field, r.status, r.value) for r in records_from_obj] == \
               [(r.field, r.status, r.value) for r in records_from_dict]

    def test_malformed_preflight_result_shape_raises_rather_than_silently_skipping(self):
        with pytest.raises(TypeError):
            brli.fields_from_preflight(preflight_result=42)
        with pytest.raises(TypeError):
            brli.fields_from_preflight(preflight_result={"no_checks_key": True})


# ---------------------------------------------------------------------------
# TransportDecision mapping
# ---------------------------------------------------------------------------

class TestTransportDecisionMapping:
    def test_confirmed_local_transport_is_auto_resolved(self):
        decision = pf.TransportDecision(
            requested="local", resolved=pf.TRANSPORT_LOCAL, available=True,
            reason="local transport explicitly requested (LOCAL_COMMANDS_PRESENT).",
            evidence={"local": {"ready": True}},
        )
        rec = brli._field_from_transport_decision(decision)
        assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
        assert rec.confidence == "HIGH"
        assert rec.value == pf.TRANSPORT_LOCAL

    def test_explicit_off_request_is_not_applicable(self):
        decision = pf.resolve_transport(requested=pf.TRANSPORT_OFF)
        rec = brli._field_from_transport_decision(decision)
        assert rec.status == intake_state.IntakeFieldStatus.NOT_APPLICABLE.value
        assert rec.confidence == "HIGH"
        assert rec.value == pf.TRANSPORT_OFF

    def test_unknown_requested_transport_string_is_blocked_as_a_config_defect(self):
        decision = pf.resolve_transport(requested="bogus_transport")
        rec = brli._field_from_transport_decision(decision)
        assert rec.status == intake_state.IntakeFieldStatus.BLOCKED.value
        assert rec.confidence == "HIGH"
        assert "unknown transport" in rec.reason

    def test_auto_with_nothing_confirmed_is_missing_never_a_confirmed_negative(self):
        decision = pf.resolve_transport(
            requested=pf.TRANSPORT_AUTO,
            env={},  # no VCHOST/VCHOP
            which=lambda _cmd: None,  # nothing on PATH
        )
        assert decision.resolved == pf.TRANSPORT_NONE
        rec = brli._field_from_transport_decision(decision)
        assert rec.status == intake_state.IntakeFieldStatus.MISSING.value
        assert rec.confidence == "UNKNOWN"

    def test_no_transport_decision_supplied_is_missing(self):
        rec = brli._field_from_transport_decision(None)
        assert rec.status == intake_state.IntakeFieldStatus.MISSING.value
        assert rec.value is None


# ---------------------------------------------------------------------------
# owner routing reuses question_queue.route_owner, never a hand-typed string
# ---------------------------------------------------------------------------

class TestOwnerRouting:
    def test_default_owner_is_the_real_env_route(self):
        records = brli.fields_from_preflight(None)
        assert all(r.owner == question_queue.route_owner("env") for r in records)

    def test_explicit_owner_override_is_honored(self):
        records = brli.fields_from_preflight(None, owner="custom-owner")
        assert all(r.owner == "custom-owner" for r in records)


# ---------------------------------------------------------------------------
# category readiness ignores foreign-category records (a caller may pass a
# whole IntakeState.records list)
# ---------------------------------------------------------------------------

class TestCategoryScoping:
    def test_foreign_category_records_are_ignored(self):
        decision = pf.TransportDecision(
            requested="auto", resolved=pf.TRANSPORT_LOCAL, available=True,
            reason="auto: running where the real license/scheduler binaries exist on PATH.",
            evidence={"local": {"ready": True}},
        )
        own = brli.fields_from_preflight(_real_full_preflight_pass(), decision)
        foreign = intake_state.IntakeFieldRecord(
            field="dut_rtl", category="general", value=None, source="env_manifest:dut_facts.rtl",
            confidence="UNKNOWN", status=intake_state.IntakeFieldStatus.BLOCKED.value,
            reason="unrelated failing field in a different category",
        )
        readiness = brli.evaluate_build_remote_lsf_readiness(list(own) + [foreign])
        assert readiness.ready is True
        assert len(readiness.fields) == len(brli.FIELD_NAMES)
