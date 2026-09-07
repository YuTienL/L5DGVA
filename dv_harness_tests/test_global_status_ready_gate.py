"""Tests for `dv_harness.global_status_ready_gate`.

The central proof is the negative control this item's own house style
requires: a `HarnessStatusIR` that is honestly all-UNKNOWN (nothing has been
read yet) is a STRUCTURALLY sound document -- `GLOBAL_STATUS_READY` and
`CLI_STATUS_READY` both read READY on it, because "can this bar be trusted
to render" is independent of "what does it currently say". Every other test
is a real negative control: one real GF-AT-28/schema/shape fact broken on an
otherwise-clean, real `HarnessStatusIR` instance (never a hand-typed fixture
pretending to be one), asserting the fold caught exactly that one defect on
exactly the gate(s) it belongs to -- proving the AND-formula, not merely
exercising it.
"""
import json

import pytest

from dv_harness import global_status_ready_gate as gsrg
from dv_harness import harness_status_ir as hsi


# ===========================================================================
# Real fixtures
# ===========================================================================

def _fresh_unknown_ir() -> hsi.HarnessStatusIR:
    """A real, freshly-constructed HarnessStatusIR -- every status field
    honestly UNKNOWN (the dataclass's own default factories), every evidence
    field honestly absent. This is exactly `unknown_harness_status_ir()`'s
    own reference shape."""
    return hsi.unknown_harness_status_ir()


def _partially_populated_ir() -> hsi.HarnessStatusIR:
    """A real IR with a handful of real, evidenced status/evidence fields
    populated (including several of CLI_REQUIRED_LEAF_PATHS), everything
    else left at its honest UNKNOWN/absent default -- proving GLOBAL_STATUS_
    READY does not require every leaf to be resolved, only that whatever IS
    resolved carries real evidence."""
    ir = hsi.HarnessStatusIR()
    ir.identity.project_id = hsi.EvidenceField(value="acme_usb3", fact_source="storage.StateStore.load")
    ir.identity.mode = hsi.EvidenceField(value="SUBSYSTEM_MODE", fact_source="environment_mode_router.resolve_environment_mode")
    ir.harness.state = hsi.known_field(hsi.HarnessStatus.RUNNING.value, fact_source="storage.StateStore.load")
    ir.harness.readiness = hsi.known_field(hsi.HarnessStatus.PARTIAL.value, fact_source="golden_flow_readiness.derive_golden_flow_readiness")
    ir.workflow.current_operation = hsi.EvidenceField(value="react_loop step 3", fact_source="react_loop.InnerReactLoop")
    ir.blockers.critical_failures = hsi.EvidenceField(value=0, fact_source="trend_analysis.detect_pattern_regressions")
    ir.blockers.human_gates = hsi.EvidenceField(value=1, fact_source="question_queue.QuestionQueueStore")
    ir.freshness.state = hsi.known_field(hsi.HarnessStatus.STALE.value, fact_source="loop_stale_detection.detect_loop_staleness")
    return ir


# ===========================================================================
# The central negative control: honest absence is structurally READY
# ===========================================================================

class TestFreshUnknownIrIsStructurallyReady:
    def test_global_status_ready_on_a_fresh_all_unknown_ir(self):
        result = gsrg.derive_global_status_ready_gates(_fresh_unknown_ir())
        assert result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["verdict"] == gsrg.GATE_READY
        assert result["summary"]["global_status_ready"] is True

    def test_cli_status_ready_on_a_fresh_all_unknown_ir(self):
        result = gsrg.derive_global_status_ready_gates(_fresh_unknown_ir())
        assert result["gates"][gsrg.GATE_CLI_STATUS_READY]["verdict"] == gsrg.GATE_READY
        assert result["summary"]["cli_status_ready"] is True

    def test_both_gates_ready_never_means_the_project_itself_is_ready(self):
        # derive_overall_status() over this same IR is UNKNOWN (GF-AT-28's own
        # negative control in harness_status_ir.py) -- this module's own
        # verdict is deliberately a DIFFERENT axis and must not be conflated.
        ir = _fresh_unknown_ir()
        overall = hsi.derive_overall_status(ir)
        assert overall.status == hsi.HarnessStatus.UNKNOWN.value
        result = gsrg.derive_global_status_ready_gates(ir)
        assert result["summary"]["global_status_ready"] is True


class TestPartiallyPopulatedIrIsAlsoReady:
    def test_global_and_cli_ready_with_real_evidenced_fields(self):
        result = gsrg.derive_global_status_ready_gates(_partially_populated_ir())
        assert result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["verdict"] == gsrg.GATE_READY
        assert result["gates"][gsrg.GATE_CLI_STATUS_READY]["verdict"] == gsrg.GATE_READY

    def test_to_dict_shape_is_accepted_identically_to_the_real_object(self):
        ir = _partially_populated_ir()
        as_obj = gsrg.derive_global_status_ready_gates(ir)
        as_dict = gsrg.derive_global_status_ready_gates(ir.to_dict())
        assert as_obj["summary"] == as_dict["summary"]


# ===========================================================================
# Negative controls -- one real defect at a time
# ===========================================================================

class TestSchemaVersionCurrent:
    def test_stale_schema_version_blocks_global_status_ready(self):
        doc = _fresh_unknown_ir().to_dict()
        doc["schema_version"] = "0.9"
        result = gsrg.derive_global_status_ready_gates(doc)
        assert result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["verdict"] == gsrg.GATE_NOT_READY
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["schema_version_current"]["status"] == gsrg.COND_BLOCKED

    def test_missing_schema_version_is_unknown_not_blocked(self):
        doc = _fresh_unknown_ir().to_dict()
        del doc["schema_version"]
        result = gsrg.derive_global_status_ready_gates(doc)
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["schema_version_current"]["status"] == gsrg.COND_UNKNOWN
        assert result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["verdict"] == gsrg.GATE_INCOMPLETE_EVIDENCE

    def test_current_schema_version_is_clear(self):
        doc = _fresh_unknown_ir().to_dict()
        assert doc["schema_version"] == hsi.SCHEMA_VERSION
        result = gsrg.derive_global_status_ready_gates(doc)
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["schema_version_current"]["status"] == gsrg.COND_CLEAR


class TestStatusGovernanceIntact:
    def test_governance_failure_is_caught_and_blocks(self, monkeypatch):
        def _boom():
            raise hsi.HarnessStatusIRError("SIMULATED_GOVERNANCE_FAILURE", {})
        monkeypatch.setattr(hsi, "assert_all_status_governance", _boom)
        result = gsrg.derive_global_status_ready_gates(_fresh_unknown_ir())
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["status_governance_intact"]["status"] == gsrg.COND_BLOCKED
        assert result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["verdict"] == gsrg.GATE_NOT_READY

    def test_real_governance_holds_today(self):
        # No monkeypatch -- the REAL assert_all_status_governance() really
        # passes right now, proving this condition is not vacuously CLEAR.
        result = gsrg.derive_global_status_ready_gates(_fresh_unknown_ir())
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["status_governance_intact"]["status"] == gsrg.COND_CLEAR


class TestLeafShapeMatchesCatalog:
    def test_a_missing_leaf_is_caught_as_extra_catalog_entry(self):
        doc = _fresh_unknown_ir().to_dict()
        del doc["identity"]["mode"]
        result = gsrg.derive_global_status_ready_gates(doc)
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["leaf_shape_matches_catalog"]["status"] == gsrg.COND_BLOCKED
        assert "identity.mode" in cond["leaf_shape_matches_catalog"]["catalog_entries_for_absent_leaves"]
        assert result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["verdict"] == gsrg.GATE_NOT_READY

    def test_an_extra_leaf_is_caught_as_missing_catalog_entry(self):
        doc = _fresh_unknown_ir().to_dict()
        doc["identity"]["bogus_leaf"] = {"value": None, "fact_source": None, "available": False}
        result = gsrg.derive_global_status_ready_gates(doc)
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["leaf_shape_matches_catalog"]["status"] == gsrg.COND_BLOCKED
        assert "identity.bogus_leaf" in cond["leaf_shape_matches_catalog"]["leaves_with_no_catalog_entry"]

    def test_a_correctly_shaped_document_is_clear(self):
        result = gsrg.derive_global_status_ready_gates(_fresh_unknown_ir())
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["leaf_shape_matches_catalog"]["status"] == gsrg.COND_CLEAR


class TestNoStatusFieldMissingEvidence:
    def test_a_claimed_status_with_no_fact_source_blocks(self):
        ir = _fresh_unknown_ir()
        # Bypass StatusField.__post_init__ by mutating the already-built
        # object directly -- exactly the "reconstructed from storage/
        # transport, never re-validated" scenario this condition exists for.
        ir.harness.state.status = hsi.HarnessStatus.READY.value
        ir.harness.state.fact_source = None
        result = gsrg.derive_global_status_ready_gates(ir)
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["no_status_field_missing_evidence"]["status"] == gsrg.COND_BLOCKED
        assert "harness.state" in cond["no_status_field_missing_evidence"]["violating_leaves"]
        assert result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["verdict"] == gsrg.GATE_NOT_READY

    def test_this_same_violation_also_blocks_cli_status_ready(self):
        # harness.state is one of CLI_REQUIRED_LEAF_PATHS -- the violation
        # must surface on the CLI gate too, both through the folded
        # GLOBAL_STATUS_READY condition and through its own per-leaf check.
        ir = _fresh_unknown_ir()
        ir.harness.state.status = hsi.HarnessStatus.READY.value
        ir.harness.state.fact_source = None
        result = gsrg.derive_global_status_ready_gates(ir)
        assert result["gates"][gsrg.GATE_CLI_STATUS_READY]["verdict"] == gsrg.GATE_NOT_READY
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_CLI_STATUS_READY]["conditions"]}
        assert cond["leaf_present:harness.state"]["status"] == gsrg.COND_BLOCKED

    def test_an_unknown_status_field_with_no_fact_source_is_fine(self):
        # UNKNOWN/NOT_APPLICABLE fields are exempt from the citation
        # requirement by construction (harness_status_ir.py's own rule) --
        # this condition must not over-fire on the honest default shape.
        ir = _fresh_unknown_ir()
        assert ir.harness.state.status == hsi.HarnessStatus.UNKNOWN.value
        ir.harness.state.fact_source = None
        result = gsrg.derive_global_status_ready_gates(ir)
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["no_status_field_missing_evidence"]["status"] == gsrg.COND_CLEAR


class TestNoEvidenceFieldMissingSource:
    def test_a_claimed_value_with_no_fact_source_blocks(self):
        ir = _fresh_unknown_ir()
        ir.identity.project_id.value = "acme_usb3"
        ir.identity.project_id.fact_source = None
        result = gsrg.derive_global_status_ready_gates(ir)
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["no_evidence_field_missing_source"]["status"] == gsrg.COND_BLOCKED
        assert "identity.project_id" in cond["no_evidence_field_missing_source"]["violating_leaves"]
        assert result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["verdict"] == gsrg.GATE_NOT_READY

    def test_this_blocks_cli_status_ready_via_the_folded_condition(self):
        # identity.project_id is a CLI-required leaf, but as an EvidenceField
        # it is not independently re-checked by _leaf_present_condition --
        # proving CLI_STATUS_READY still correctly blocks through its own
        # folded-in GLOBAL_STATUS_READY condition rather than missing it.
        ir = _fresh_unknown_ir()
        ir.identity.project_id.value = "acme_usb3"
        ir.identity.project_id.fact_source = None
        result = gsrg.derive_global_status_ready_gates(ir)
        assert result["gates"][gsrg.GATE_CLI_STATUS_READY]["verdict"] == gsrg.GATE_NOT_READY
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_CLI_STATUS_READY]["conditions"]}
        assert cond[gsrg.GATE_GLOBAL_STATUS_READY]["status"] == gsrg.COND_BLOCKED

    def test_an_absent_value_needs_no_fact_source(self):
        ir = _fresh_unknown_ir()
        assert ir.identity.project_id.value is None
        result = gsrg.derive_global_status_ready_gates(ir)
        cond = {c["condition"]: c for c in
                result["gates"][gsrg.GATE_GLOBAL_STATUS_READY]["conditions"]}
        assert cond["no_evidence_field_missing_source"]["status"] == gsrg.COND_CLEAR


# ===========================================================================
# _leaf_present_condition -- unit-level, both branches
# ===========================================================================

class TestLeafPresentConditionUnit:
    def test_absent_leaf_is_unknown(self):
        cond = gsrg._leaf_present_condition({}, "identity.project_id")
        assert cond["status"] == gsrg.COND_UNKNOWN

    def test_present_clean_status_leaf_is_clear(self):
        doc = {"harness": {"state": {"status": hsi.HarnessStatus.READY.value,
                                     "value": None, "fact_source": "engine.py", "detail": None}}}
        cond = gsrg._leaf_present_condition(doc, "harness.state")
        assert cond["status"] == gsrg.COND_CLEAR

    def test_present_status_leaf_missing_evidence_is_blocked(self):
        doc = {"harness": {"state": {"status": hsi.HarnessStatus.READY.value,
                                     "value": None, "fact_source": None, "detail": None}}}
        cond = gsrg._leaf_present_condition(doc, "harness.state")
        assert cond["status"] == gsrg.COND_BLOCKED

    def test_present_unknown_status_leaf_never_needs_evidence(self):
        doc = {"harness": {"state": {"status": hsi.HarnessStatus.UNKNOWN.value,
                                     "value": None, "fact_source": None, "detail": None}}}
        cond = gsrg._leaf_present_condition(doc, "harness.state")
        assert cond["status"] == gsrg.COND_CLEAR

    def test_present_evidence_leaf_is_clear_regardless_of_its_own_source(self):
        # EvidenceField leaves are not independently re-checked here --
        # that is no_evidence_field_missing_source's job, exercised project
        # wide; this per-leaf check answers only "does it exist".
        doc = {"identity": {"project_id": {"value": "x", "fact_source": None, "available": False}}}
        cond = gsrg._leaf_present_condition(doc, "identity.project_id")
        assert cond["status"] == gsrg.COND_CLEAR


# ===========================================================================
# Malformed input
# ===========================================================================

class TestMalformedInput:
    def test_a_non_ir_non_mapping_is_refused(self):
        with pytest.raises(gsrg.GlobalStatusReadyGateError):
            gsrg.derive_global_status_ready_gates(["not", "a", "document"])

    def test_an_unrecognized_condition_status_is_refused(self):
        with pytest.raises(gsrg.GlobalStatusReadyGateError):
            gsrg._condition("bogus", "NOT_A_REAL_STATUS", "evidence")


# ===========================================================================
# Structural / vocabulary guarantees
# ===========================================================================

class TestStructuralGuarantees:
    def test_gate_vocabulary_never_collides_with_models_status(self):
        from dv_harness.models import Status
        status_values = {member.value for member in Status}
        assert set(gsrg.GATE_VERDICTS).isdisjoint(status_values)

    def test_exactly_two_named_gates_declared(self):
        assert len(gsrg.GATE_NAMES) == 2
        assert len(set(gsrg.GATE_NAMES)) == 2
        assert gsrg.GATE_NAMES == (gsrg.GATE_GLOBAL_STATUS_READY, gsrg.GATE_CLI_STATUS_READY)

    def test_cli_required_leaf_paths_are_all_real_ir_leaves(self):
        real_leaves = {p for p, _ in hsi.iter_leaf_fields(_fresh_unknown_ir())}
        for path in gsrg.CLI_REQUIRED_LEAF_PATHS:
            assert path in real_leaves

    def test_render_and_format_do_not_raise_and_carry_every_gate_name(self):
        result = gsrg.derive_global_status_ready_gates(_partially_populated_ir())
        table = gsrg.render_global_status_ready_gates_table(result)
        report = gsrg.format_global_status_ready_gates_report(result)
        for name in gsrg.GATE_NAMES:
            assert name in table
            assert name in report

    def test_authorizes_nothing_is_stated_on_every_result(self):
        result = gsrg.derive_global_status_ready_gates(_fresh_unknown_ir())
        assert "NOTHING" in result["authorizes"]


# ===========================================================================
# CLI front door
# ===========================================================================

class TestExecuteVerbFrontDoor:
    def test_execute_verb_reads_a_real_json_document(self, tmp_path):
        doc = _partially_populated_ir().to_dict()
        p = tmp_path / "harness_status_ir.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        text, code = gsrg.execute_verb(str(p))
        assert code == 0
        assert "GLOBAL_STATUS_READY" in text

    def test_execute_verb_exit_code_reflects_a_real_block(self, tmp_path):
        doc = _fresh_unknown_ir().to_dict()
        doc["schema_version"] = "0.0"
        p = tmp_path / "stale.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        _, code = gsrg.execute_verb(str(p))
        assert code == 1

    def test_execute_verb_json_mode(self, tmp_path):
        doc = _fresh_unknown_ir().to_dict()
        p = tmp_path / "doc.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        text, code = gsrg.execute_verb(str(p), as_json=True)
        assert code == 0
        parsed = json.loads(text)
        assert parsed["summary"]["global_status_ready"] is True

    def test_main_handles_a_missing_file_gracefully(self):
        rc = gsrg.main(["/no/such/file.json"])
        assert rc == 2
