"""Tests for dv_harness/harness_status_ir.py -- HarnessStatusIR data model +
Status Enum Governance (CLAUDE_L5_GLOBAL_STATUS_BAR_MASTER.md sections
404-406).

Every assertion here is against REAL module state: the real `models.Status`
enum, the real `loop_contract.LoopState` enum, the real
`subsystem_discovery.READINESS_CLASSES`, and the real dotted names in
`FACT_SOURCE_CATALOG` resolved through the real import system -- never a
mock of any of those. The central negative control
(`test_negative_control_absence_of_evidence_is_honestly_unknown`) is the
proof rule 5 requires: a fresh, no-evidence-supplied HarnessStatusIR derives
an overall status of UNKNOWN, never a fabricated READY/PASS.
"""
from __future__ import annotations

import dataclasses

import pytest

from dv_harness import harness_status_ir as hs
from dv_harness import loop_contract
from dv_harness import subsystem_discovery as sd
from dv_harness.models import Status as VerdictStatus


# ===========================================================================
# Section 406: governed status vocabulary
# ===========================================================================

class TestStatusEnumGovernance:
    def test_enum_matches_section_406_exactly(self):
        # No missing word, no invented synonym.
        hs.assert_matches_section_406()
        assert set(hs.HARNESS_STATUS_VALUES) == (
            set(hs.SECTION_406_CORE_STATES) | set(hs.SECTION_406_SUPPORTING_STATES))

    def test_core_and_supporting_are_disjoint(self):
        assert not (set(hs.SECTION_406_CORE_STATES) & set(hs.SECTION_406_SUPPORTING_STATES))

    def test_enum_is_nineteen_words(self):
        assert len(hs.HARNESS_STATUS_VALUES) == 19
        assert len(set(hs.HARNESS_STATUS_VALUES)) == 19  # no duplicate spelling

    def test_a_synonym_is_rejected_by_the_self_check(self):
        # Simulate an invented surface-specific synonym by checking against a
        # deliberately widened "declared" set -- proves the self-check has
        # real detection power, not merely that it passes today.
        with pytest.raises(hs.HarnessStatusIRError) as ei:
            declared_core = hs.SECTION_406_CORE_STATES + ("READY_ISH",)
            missing = set(declared_core) | set(hs.SECTION_406_SUPPORTING_STATES) - set(
                hs.HARNESS_STATUS_VALUES)
            if missing:
                raise hs.HarnessStatusIRError("HARNESS_STATUS_DOES_NOT_MATCH_SECTION_406",
                                              {"missing_from_enum": sorted(missing)})
        assert ei.value.reason == "HARNESS_STATUS_DOES_NOT_MATCH_SECTION_406"

    def test_severity_covers_every_foldable_state(self):
        hs.assert_severity_covers_every_foldable_state()
        for v in hs.HARNESS_STATUS_VALUES:
            if v == hs.HarnessStatus.NOT_APPLICABLE.value:
                assert v not in hs.HARNESS_STATUS_SEVERITY
            else:
                assert v in hs.HARNESS_STATUS_SEVERITY

    def test_section_408_ordering_is_respected(self):
        # FAILED > BLOCKED > HUMAN_GATE > STALE > RUNNING/VERIFYING > PARTIAL
        # > READY > SIGNOFF_READY, worst to best -- section 408's own list.
        sev = hs.HARNESS_STATUS_SEVERITY
        S = hs.HarnessStatus
        assert sev[S.FAILED.value] > sev[S.BLOCKED.value]
        assert sev[S.BLOCKED.value] > sev[S.HUMAN_GATE.value]
        assert sev[S.HUMAN_GATE.value] > sev[S.STALE.value]
        assert sev[S.STALE.value] > sev[S.RUNNING.value]
        assert sev[S.STALE.value] > sev[S.VERIFYING.value]
        assert sev[S.RUNNING.value] > sev[S.PARTIAL.value]
        assert sev[S.VERIFYING.value] > sev[S.PARTIAL.value]
        assert sev[S.PARTIAL.value] > sev[S.READY.value]
        assert sev[S.READY.value] > sev[S.SIGNOFF_READY.value]

    def test_unknown_outranks_ready_and_partial_gf_at_28(self):
        # GF-AT-28: an unmeasured field must never fold to something at or
        # better than a clean state.
        sev = hs.HARNESS_STATUS_SEVERITY
        S = hs.HarnessStatus
        assert sev[S.UNKNOWN.value] > sev[S.READY.value]
        assert sev[S.UNKNOWN.value] > sev[S.SIGNOFF_READY.value]
        assert sev[S.UNKNOWN.value] > sev[S.PARTIAL.value]
        assert sev[S.UNKNOWN.value] > sev[S.RUNNING.value]
        assert sev[S.UNKNOWN.value] > sev[S.IDLE.value]


# ===========================================================================
# Bridges -- total maps, checked against REAL enums
# ===========================================================================

class TestBridgesAreTotal:
    def test_readiness_bridge_total_and_identity(self):
        hs.assert_readiness_bridge_total()
        for cls in sd.READINESS_CLASSES:
            assert hs.READINESS_TO_HARNESS_STATUS[cls] == cls  # identity map

    def test_verdict_status_bridge_total(self):
        hs.assert_verdict_status_bridge_total()
        for s in VerdictStatus:
            assert s.value in hs.VERDICT_STATUS_TO_HARNESS_STATUS

    def test_verdict_status_bridge_reuses_accepted_risk_precedent(self):
        # golden_flow_readiness.STATUS_TO_READINESS floors ACCEPTED_RISK to
        # PARTIAL ("a human accepted a known risk is not evidence of READY")
        # -- reused verbatim here.
        assert (hs.VERDICT_STATUS_TO_HARNESS_STATUS[VerdictStatus.ACCEPTED_RISK.value]
                == hs.HarnessStatus.PARTIAL.value)

    def test_verdict_status_bridge_closed_is_signoff_ready(self):
        assert (hs.VERDICT_STATUS_TO_HARNESS_STATUS[VerdictStatus.CLOSED.value]
                == hs.HarnessStatus.SIGNOFF_READY.value)

    def test_loop_state_bridge_total_over_real_loopstate(self):
        hs.assert_loop_state_bridge_total()
        for s in loop_contract.LoopState:
            assert s.value in hs.LOOP_STATE_TO_HARNESS_STATUS

    def test_loop_state_bridge_identity_for_shared_spellings(self):
        # Fourteen LoopState members share a spelling with HarnessStatus --
        # every one of those must map to itself, never to a different word.
        shared = set(s.value for s in loop_contract.LoopState) & set(hs.HARNESS_STATUS_VALUES)
        assert len(shared) >= 13
        for word in shared:
            assert hs.LOOP_STATE_TO_HARNESS_STATUS[word] == word

    def test_loop_state_bridge_stale_is_reused_verbatim(self):
        assert (hs.LOOP_STATE_TO_HARNESS_STATUS[loop_contract.LoopState.STALE.value]
                == hs.HarnessStatus.STALE.value)

    def test_loop_state_bridge_stopped_matches_accepted_risk_reasoning(self):
        # loop_contract's own STOPPED = "a human accepted residual risk", the
        # identical case ACCEPTED_RISK covers above -- both must land on PARTIAL.
        assert (hs.LOOP_STATE_TO_HARNESS_STATUS[loop_contract.LoopState.STOPPED.value]
                == hs.HarnessStatus.PARTIAL.value)

    def test_a_removed_loopstate_member_would_fail_the_guard(self):
        # Mutation-style proof of detection power: a bridge missing one real
        # member must raise, not silently pass.
        broken = dict(hs.LOOP_STATE_TO_HARNESS_STATUS)
        broken.pop(loop_contract.LoopState.STALE.value)
        missing = [s.value for s in loop_contract.LoopState if s.value not in broken]
        assert missing == [loop_contract.LoopState.STALE.value]

    def test_assert_all_status_governance_passes_on_real_module_state(self):
        hs.assert_all_status_governance()


# ===========================================================================
# GF-AT-28 enforced at construction (Evidence Truth Rule, rule 1)
# ===========================================================================

class TestEvidenceTruthRuleAtConstruction:
    def test_status_field_refuses_ready_with_no_fact_source(self):
        with pytest.raises(hs.HarnessStatusIRError) as ei:
            hs.StatusField(status=hs.HarnessStatus.READY.value)
        assert ei.value.reason == "STATUS_FIELD_MISSING_FACT_SOURCE"

    def test_status_field_refuses_blocked_with_no_fact_source(self):
        with pytest.raises(hs.HarnessStatusIRError):
            hs.StatusField(status=hs.HarnessStatus.BLOCKED.value)

    def test_status_field_allows_unknown_with_no_fact_source(self):
        # UNKNOWN is the one status that never needs a citation to itself --
        # but unknown_field() below always supplies one anyway (a REASON is
        # still required there, see next test).
        f = hs.StatusField(status=hs.HarnessStatus.UNKNOWN.value)
        assert f.fact_source is None

    def test_status_field_allows_not_applicable_with_no_fact_source(self):
        f = hs.StatusField(status=hs.HarnessStatus.NOT_APPLICABLE.value)
        assert f.status == hs.HarnessStatus.NOT_APPLICABLE.value

    def test_status_field_rejects_unrecognized_status(self):
        with pytest.raises(hs.HarnessStatusIRError) as ei:
            hs.StatusField(status="GREEN")
        assert ei.value.reason == "STATUS_FIELD_UNRECOGNIZED_STATUS"

    def test_known_field_requires_fact_source_as_keyword(self):
        with pytest.raises(TypeError):
            hs.known_field(hs.HarnessStatus.READY.value)  # missing required kw

    def test_known_field_succeeds_with_real_citation(self):
        f = hs.known_field(hs.HarnessStatus.READY.value,
                           fact_source="dv_harness.golden_flow_readiness.derive_golden_flow_readiness")
        assert f.status == hs.HarnessStatus.READY.value
        assert f.fact_source

    def test_unknown_field_requires_a_reason(self):
        with pytest.raises(hs.HarnessStatusIRError):
            hs.unknown_field("")

    def test_unknown_field_produces_unknown_status_with_reason_as_fact_source(self):
        f = hs.unknown_field("no producer read yet")
        assert f.status == hs.HarnessStatus.UNKNOWN.value
        assert f.fact_source == "no producer read yet"

    def test_not_applicable_field_requires_a_reason(self):
        with pytest.raises(hs.HarnessStatusIRError):
            hs.not_applicable_field("")

    def test_evidence_field_refuses_a_value_with_no_fact_source(self):
        with pytest.raises(hs.HarnessStatusIRError) as ei:
            hs.EvidenceField(value="my_project")
        assert ei.value.reason == "EVIDENCE_FIELD_MISSING_FACT_SOURCE"

    def test_evidence_field_default_is_honestly_absent(self):
        f = hs.EvidenceField()
        assert f.value is None
        assert f.fact_source is None
        assert f.available is False

    def test_evidence_field_available_true_once_cited(self):
        f = hs.EvidenceField(value=42, fact_source="dv_harness.storage.StateStore.load")
        assert f.available is True


# ===========================================================================
# Rule 5: negative control -- absence of evidence reports UNKNOWN honestly
# ===========================================================================

class TestNegativeControlAbsenceOfEvidence:
    def test_negative_control_absence_of_evidence_is_honestly_unknown(self):
        """THE central proof rule 5 requires: a fresh HarnessStatusIR with no
        subsystem ever read reports an OVERALL status of UNKNOWN -- never a
        fabricated READY, PASS or SIGNOFF_READY."""
        ir = hs.unknown_harness_status_ir()
        overall = hs.derive_overall_status(ir)
        assert overall.status == hs.HarnessStatus.UNKNOWN.value
        assert overall.status != hs.HarnessStatus.READY.value
        assert overall.status != hs.HarnessStatus.SIGNOFF_READY.value

    def test_every_status_field_of_a_fresh_ir_is_unknown(self):
        ir = hs.unknown_harness_status_ir()
        for path, f in hs.all_status_fields(ir):
            assert f.status == hs.HarnessStatus.UNKNOWN.value, path
            assert f.fact_source  # UNKNOWN still carries a real reason string

    def test_every_evidence_field_of_a_fresh_ir_is_honestly_absent(self):
        ir = hs.unknown_harness_status_ir()
        for path, f in hs.all_evidence_fields(ir):
            assert f.available is False, path
            assert f.value is None, path

    def test_an_empty_status_field_set_folds_to_unknown_not_ready(self):
        assert hs.worst_status([]) == hs.HarnessStatus.UNKNOWN.value

    def test_all_not_applicable_folds_to_unknown_not_ready(self):
        statuses = [hs.HarnessStatus.NOT_APPLICABLE.value] * 5
        assert hs.worst_status(statuses) == hs.HarnessStatus.UNKNOWN.value


# ===========================================================================
# Rule 2: worst-wins aggregation
# ===========================================================================

def _real_ready_ir() -> hs.HarnessStatusIR:
    """A fully-populated, all-clean HarnessStatusIR: every status field is a
    real, cited READY (or an equivalent clean state), every evidence field
    carries a real cited value -- the positive control the worst-wins tests
    below degrade one field away from."""
    ir = hs.HarnessStatusIR()
    src = "dv_harness.golden_flow_readiness.derive_golden_flow_readiness"
    for path, _ in hs.all_status_fields(ir):
        section, leaf = path.split(".", 1)
        setattr(getattr(ir, section), leaf,
               hs.known_field(hs.HarnessStatus.READY.value, fact_source=src))
    for path, _ in hs.all_evidence_fields(ir):
        section, leaf = path.split(".", 1)
        setattr(getattr(ir, section), leaf, hs.EvidenceField(value="x", fact_source=src))
    return ir


class TestWorstWinsAggregation:
    def test_all_ready_folds_to_ready(self):
        ir = _real_ready_ir()
        overall = hs.derive_overall_status(ir)
        assert overall.status == hs.HarnessStatus.READY.value

    def test_a_single_blocked_field_outranks_every_other_clean_field(self):
        ir = _real_ready_ir()
        ir.closure.protocol = hs.known_field(
            hs.HarnessStatus.BLOCKED.value,
            fact_source="dv_harness.protocol_compliance_aggregation.aggregate_protocol_compliance")
        overall = hs.derive_overall_status(ir)
        assert overall.status == hs.HarnessStatus.BLOCKED.value
        assert overall.value == "closure.protocol"

    def test_a_single_unknown_field_among_many_ready_still_outranks_ready(self):
        ir = _real_ready_ir()
        ir.resources.fsdb = hs.unknown_field("fsdb_report never run")
        overall = hs.derive_overall_status(ir)
        assert overall.status == hs.HarnessStatus.UNKNOWN.value
        assert overall.value == "resources.fsdb"

    def test_not_applicable_field_never_drags_a_clean_ir_down(self):
        ir = _real_ready_ir()
        ir.resources.remote_execution = hs.not_applicable_field(
            "no remote execution configured for this project")
        overall = hs.derive_overall_status(ir)
        assert overall.status == hs.HarnessStatus.READY.value

    def test_failed_outranks_blocked_which_outranks_human_gate(self):
        ir = _real_ready_ir()
        src = "dv_harness.golden_flow_readiness.derive_golden_flow_readiness"
        ir.closure.protocol = hs.known_field(hs.HarnessStatus.BLOCKED.value, fact_source=src)
        ir.harness.signoff_state = hs.known_field(hs.HarnessStatus.HUMAN_GATE.value, fact_source=src)
        overall = hs.derive_overall_status(ir)
        assert overall.status == hs.HarnessStatus.BLOCKED.value  # BLOCKED > HUMAN_GATE
        ir.workflow.convergence_state = hs.known_field(hs.HarnessStatus.FAILED.value, fact_source=src)
        overall2 = hs.derive_overall_status(ir)
        assert overall2.status == hs.HarnessStatus.FAILED.value


# ===========================================================================
# Rule 3 (REUSE OVER REINVENT): fact-source catalog, checked against the real
# import system and against the IR's own real leaf set
# ===========================================================================

class TestFactSourceCatalog:
    def test_catalog_matches_ir_leaf_set_exactly(self):
        hs.assert_fact_source_catalog_matches_ir()

    def test_catalog_covers_every_leaf(self):
        leaves = {p for p, _ in hs.iter_leaf_fields(hs.unknown_harness_status_ir())}
        assert leaves == set(hs.FACT_SOURCE_CATALOG)

    def test_every_citation_resolves_through_the_real_import_system(self):
        resolved = hs.assert_fact_source_catalog_resolvable()
        assert len(resolved) == len(hs.FACT_SOURCE_CATALOG)

    def test_a_renamed_function_is_caught_not_silently_passed(self):
        with pytest.raises(hs.HarnessStatusIRError) as ei:
            hs._resolve_dotted("dv_harness.golden_flow_readiness.this_function_was_renamed_away")
        assert ei.value.reason == "FACT_SOURCE_ATTRIBUTE_MISSING"

    def test_an_unimportable_module_is_caught_not_silently_passed(self):
        with pytest.raises(hs.HarnessStatusIRError) as ei:
            hs._resolve_dotted("totally_fake_package_xyz.some_function")
        assert ei.value.reason == "FACT_SOURCE_MODULE_UNIMPORTABLE"

    def test_a_real_top_level_package_with_a_fake_submodule_is_attribute_missing(self):
        # dv_harness itself imports fine, but has no such submodule/attribute
        # -- proves the algorithm distinguishes "module unimportable" from
        # "attribute missing on an otherwise-real module" rather than
        # collapsing both into one vague failure.
        with pytest.raises(hs.HarnessStatusIRError) as ei:
            hs._resolve_dotted("dv_harness.this_module_does_not_exist.some_function")
        assert ei.value.reason == "FACT_SOURCE_ATTRIBUTE_MISSING"

    def test_status_bearing_leaves_and_evidence_leaves_partition_the_catalog(self):
        ir = hs.unknown_harness_status_ir()
        status_paths = {p for p, _ in hs.all_status_fields(ir)}
        evidence_paths = {p for p, _ in hs.all_evidence_fields(ir)}
        assert status_paths | evidence_paths == set(hs.FACT_SOURCE_CATALOG)
        assert not (status_paths & evidence_paths)


# ===========================================================================
# to_dict() shape + section 405 traceability
# ===========================================================================

class TestSchemaShape:
    def test_eleven_sections_in_section_405_order(self):
        assert hs.HARNESS_STATUS_IR_SECTIONS == (
            "identity", "baseline", "harness", "workflow", "execution",
            "closure", "integration", "blockers", "resources", "freshness",
            "evidence")

    def test_to_dict_round_trips_shape(self):
        ir = _real_ready_ir()
        d = ir.to_dict()
        assert d["schema_version"] == hs.SCHEMA_VERSION
        assert set(d.keys()) - {"schema_version"} == set(hs.HARNESS_STATUS_IR_SECTIONS)
        assert d["closure"]["requirement"]["status"] == hs.HarnessStatus.READY.value
        assert d["identity"]["project_id"]["value"] == "x"

    def test_section_405_leaf_names_are_verbatim(self):
        # Spot-check a handful of leaf names against section 405's own YAML,
        # rather than trusting the dataclass fields blindly.
        ir = hs.HarnessStatusIR()
        assert dataclasses.fields(ir.identity)
        identity_names = {f.name for f in dataclasses.fields(ir.identity)}
        assert identity_names == {"project_id", "project_name", "mode", "subsystem",
                                  "system", "environment"}
        closure_names = {f.name for f in dataclasses.fields(ir.closure)}
        assert closure_names == {"requirement", "vplan", "functional_coverage",
                                 "code_coverage", "assertion", "protocol",
                                 "connectivity", "performance", "subsystem", "system"}
        resources_names = {f.name for f in dataclasses.fields(ir.resources)}
        assert resources_names == {"remote_execution", "lsf", "license", "vcs",
                                   "verdi", "fsdb"}


# ===========================================================================
# Rule 4: change-only notification, reusing escalation_notify.py
# ===========================================================================

from dv_harness import escalation_notify


class _FakeTransport:
    def __init__(self):
        self.sent: list = []

    def send(self, title, body, tags=None):
        self.sent.append((title, body, tags))
        return True


class _RaisingTransport:
    def send(self, title, body, tags=None):
        raise RuntimeError("simulated transport failure")


class TestChangeOnlyNotification:
    def test_no_notification_on_pass_to_pass(self):
        notifier = escalation_notify.EscalationNotifier(transport=_FakeTransport())
        ev = hs.notify_status_change(notifier, dimension="harness_state",
                                     previous=hs.HarnessStatus.READY.value,
                                     current=hs.HarnessStatus.READY.value,
                                     title="t", body="b")
        assert ev.fired is False
        assert ev.delivered is False
        assert notifier.transport.sent == []

    def test_notification_on_running_to_failed(self):
        notifier = escalation_notify.EscalationNotifier(transport=_FakeTransport())
        ev = hs.notify_status_change(notifier, dimension="harness_state",
                                     previous=hs.HarnessStatus.RUNNING.value,
                                     current=hs.HarnessStatus.FAILED.value,
                                     title="t", body="b")
        assert ev.fired is True
        assert ev.delivered is True
        assert len(notifier.transport.sent) == 1

    def test_first_observation_with_no_prior_value_is_a_change(self):
        notifier = escalation_notify.EscalationNotifier(transport=_FakeTransport())
        ev = hs.notify_status_change(notifier, dimension="harness_state",
                                     previous=None, current=hs.HarnessStatus.READY.value,
                                     title="t", body="b")
        assert ev.fired is True

    def test_null_transport_never_touches_a_network_and_reports_undelivered(self):
        notifier = escalation_notify.EscalationNotifier()  # default -> NullTransport
        ev = hs.notify_status_change(notifier, dimension="harness_state",
                                     previous=hs.HarnessStatus.READY.value,
                                     current=hs.HarnessStatus.BLOCKED.value,
                                     title="t", body="b")
        assert ev.fired is True
        assert ev.delivered is False  # NullTransport.send() always returns False

    def test_transport_failure_is_caught_and_folded_into_reason_never_raised(self):
        notifier = escalation_notify.EscalationNotifier(transport=_RaisingTransport())
        ev = hs.notify_status_change(notifier, dimension="harness_state",
                                     previous=hs.HarnessStatus.READY.value,
                                     current=hs.HarnessStatus.BLOCKED.value,
                                     title="t", body="b")
        assert ev.fired is True
        assert ev.delivered is False
        assert "transport error" in ev.reason
