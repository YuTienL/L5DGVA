"""Golden Subsystem Benchmark / KPI / Critical False-Architecture-Claim Metrics,
end to end (master prompt sections 299-301, 326-328).

Every extracted "doc" graded below is produced by the REAL producer functions
(`dv_harness.verification_architecture.build_checker_ir`/`build_scoreboard_ir`,
`dv_harness.design_architecture_ir.build_module_registry`/`build_instance_tree`/
`extract_fsm_candidates`) -- never hand-typed to merely LOOK like real IR
output. The central proof, `test_confidently_wrong_checker_is_a_false_positive`
and its scoreboard/FSM/instance-tree siblings, constructs a case where the
real extractor is CONFIDENTLY WRONG and asserts the grader calls it
CLAIM_FALSE_POSITIVE -- the metric this task exists to make honest and
never-averaged-away -- while a genuinely unresolved/unlinked record grades as
CLAIM_HONEST_ABSTENTION, never punished the same way.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from dv_harness import golden_subsystem_benchmark as gsb
from dv_harness import verification_architecture as va
from dv_harness import connectivity as conn
from dv_harness import design_architecture_ir as air


# ---------------------------------------------------------------------------
# Real-producer fixtures
# ---------------------------------------------------------------------------

def _checker_doc(*, linked: bool, mount_side: bool = True) -> dict:
    """A real `verification_architecture.build_checker_ir()` output list,
    wrapped the way `assemble_verification_architecture()` wraps it."""
    entries = [conn.generate_protocol_check_entry(
        "ep0_check", "usb3_vip", ["crc_check", "timeout_check"], {})]
    links = {}
    if linked:
        links["ep0_check"] = {
            "target_instance": "u_ep0",
            "mount_side": "POST_BRIDGE" if mount_side else None,
            "checker_domain": "REGISTER_CSR",
        }
    checkers = va.build_checker_ir(entries, links)
    return {"checker": [c.to_dict() for c in checkers]}


def _scoreboard_doc(*, boundary_agrees: bool, resolved: bool) -> dict:
    entry = conn.generate_scoreboard_entry(
        "ep0_scoreboard", [{"source": "u_epA.wdata", "sink": "u_epB.wdata"}],
        "seq_id",
        transformation_rules=[], reset_flush_behavior="FLUSH_ON_RESET",
        orphan_threshold=4, orphan_timeout="1us", ordering="IN_ORDER",
        ordering_tolerance_depth=0, legal_drop_conditions="none",
    )
    if resolved:
        boundary = {"u_epA.wdata": {"kind": "SERIAL"},
                    "u_epB.wdata": {"kind": "SERIAL" if boundary_agrees else "PARALLEL"}}
    else:
        boundary = None
    scoreboards = va.build_scoreboard_ir([entry], boundary)
    return {"scoreboard": [s.to_dict() for s in scoreboards]}


CLEAN_FSM_TEXT = textwrap.dedent("""\
    reg [1:0] state;
    always @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        state <= 2'd0;
      end else begin
        case (state)
          IDLE: begin
            if (data_in != 0)
              state <= BUSY;
          end
          BUSY: begin
            state <= DONE;
          end
          DONE: begin
            state <= IDLE;
          end
          default: state <= IDLE;
        endcase
      end
    end
    """)

AMBIGUOUS_FSM_TEXT = textwrap.dedent("""\
    reg [1:0] state;
    always @(posedge clk) begin
      case (state)
        IDLE: begin
          if (go)
            state <= BUSY;
          else
            state <= WAIT;
        end
        default: state <= IDLE;
      endcase
    end
    """)


def _design_doc_with_fsm(module_text: str) -> dict:
    """A real `modules[name]["fsm_extraction"]` shape, built from the real,
    pure `extract_fsm_candidates()` -- no verible subprocess required."""
    candidates = air.extract_fsm_candidates(module_text, "u_ctrl", ["state"])
    return {"modules": {"u_ctrl": {"fsm_extraction": {
        "status": "CANDIDATES_FOUND", "reason": None, "candidates": candidates,
    }}}}


def _instance_tree_doc(*, leaf_resolved: bool) -> dict:
    """A real `design_architecture_ir.build_module_registry()` +
    `build_instance_tree()` output, over hand-built parsed-file dicts in the
    exact shape those two PURE functions consume (no verible needed)."""
    leaf_module = "usb_ep_ctrl" if leaf_resolved else "usb_ep_ctrl_MISSING"
    parsed = [{
        "file_path": "top.sv", "status": "PARSED",
        "modules": [{
            "name": "usb_top", "ports": [], "parameters": [],
            "instances": [{"instance_name": "u_ep0", "module_name": leaf_module,
                           "connections": []}],
        }],
    }]
    if leaf_resolved:
        parsed.append({
            "file_path": "ep_ctrl.sv", "status": "PARSED",
            "modules": [{"name": "usb_ep_ctrl", "ports": [], "parameters": [],
                        "instances": []}],
        })
    registry, duplicates = air.build_module_registry(parsed)
    tree = air.build_instance_tree(registry, top_module="usb_top")
    return {"instance_tree": tree, "duplicate_modules": duplicates,
            "modules": {name: e["module"] for name, e in registry.items()}}


# ---------------------------------------------------------------------------
# Case/claim builders
# ---------------------------------------------------------------------------

def _claim(claim_id, ir_kind, match, field, expected_value, *,
          positive_values=(), abstention_values=(), module_name=None,
          note="see fixture project's checker-link table"):
    c = {
        "claim_id": claim_id, "ir_kind": ir_kind, "match": match, "field": field,
        "expected_value": expected_value,
        "positive_values": list(positive_values),
        "abstention_values": list(abstention_values),
        "note": note,
    }
    if module_name is not None:
        c["module_name"] = module_name
    else:
        c["module_name"] = None
    return c


def _case(case_id, extraction_kind, claims, *, fixture_ref="usb_ep0_subsystem",
          subsystem_id="usb_ep0", difficulty="INTERMEDIATE",
          qualification="SYNTHETIC_FIXTURE"):
    return {
        "case_id": case_id, "subsystem_id": subsystem_id,
        "extraction_kind": extraction_kind, "owner": "dv-lead@example.com",
        "source": "hand-curated for this test", "provenance": "unit test fixture",
        "known_ambiguity": "", "difficulty": difficulty, "qualification": qualification,
        "fixture_ref": fixture_ref, "claims": claims,
    }


def _dataset(dataset_id, version, cases, *, notes=""):
    return {
        "dataset_id": dataset_id, "version": version,
        "description": "golden subsystem benchmark test corpus",
        "owner": "dv-lead@example.com", "source": "unit test",
        "provenance": "synthetic, no real project", "notes": notes, "cases": cases,
    }


# ===========================================================================
# 1. Vocabulary separation
# ===========================================================================

def test_no_verification_verdict_vocabulary_collision():
    gsb.assert_no_verification_verdict_vocabulary()  # must not raise


def test_vocabulary_check_actually_detects_a_collision(monkeypatch):
    monkeypatch.setattr(gsb, "CLAIM_OUTCOMES", gsb.CLAIM_OUTCOMES + ("PASS",))
    with pytest.raises(gsb.GSValidationError):
        gsb.assert_no_verification_verdict_vocabulary()


# ===========================================================================
# 2. Claim / case / dataset validation
# ===========================================================================

def test_valid_case_and_dataset_pass_validation():
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status",
                   "RESOLVED", positive_values=["RESOLVED"],
                   abstention_values=["PARTIAL", "UNKNOWN"])
    case = _case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [claim])
    gsb.validate_case(case, index=0)
    gsb.validate_dataset(_dataset("ds", 1, [case]))


@pytest.mark.parametrize("mutate", [
    lambda c: c.pop("field"),
    lambda c: c.__setitem__("match", {}),
    lambda c: c.__setitem__("note", ""),
    lambda c: c.__setitem__("positive_values", "not-a-list"),
    lambda c: c.__setitem__("ir_kind", "not_a_real_ir_kind"),
])
def test_malformed_claim_is_rejected(mutate):
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status",
                   "RESOLVED", positive_values=["RESOLVED"], abstention_values=["UNKNOWN"])
    mutate(claim)
    with pytest.raises(gsb.GSValidationError):
        gsb.validate_claim(claim, index=0, extraction_kind=gsb.EK_VERIFICATION_ARCHITECTURE)


def test_fsm_claim_requires_module_name():
    claim = _claim("c1", "module_fsm_candidate", {"register_name": "state"}, "status",
                   "FSM_EXTRACTION_RESOLVED", positive_values=["FSM_EXTRACTION_RESOLVED"])
    claim["module_name"] = None
    with pytest.raises(gsb.GSValidationError):
        gsb.validate_claim(claim, index=0, extraction_kind=gsb.EK_DESIGN_ARCHITECTURE)


def test_non_fsm_claim_rejects_a_module_name():
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status",
                   "RESOLVED", positive_values=["RESOLVED"], module_name="u_ctrl")
    with pytest.raises(gsb.GSValidationError):
        gsb.validate_claim(claim, index=0, extraction_kind=gsb.EK_VERIFICATION_ARCHITECTURE)


def test_ir_kind_must_belong_to_its_extraction_kind():
    claim = _claim("c1", "instance_node", {"instance_name": "u_ep0"}, "resolved", True,
                   positive_values=[True])
    with pytest.raises(gsb.GSValidationError):
        # instance_node is a DESIGN_ARCHITECTURE ir_kind, not a VERIFICATION_ARCHITECTURE one
        gsb.validate_claim(claim, index=0, extraction_kind=gsb.EK_VERIFICATION_ARCHITECTURE)


def test_duplicate_claim_ids_in_one_case_are_rejected():
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status",
                   "RESOLVED", positive_values=["RESOLVED"])
    case = _case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [dict(claim), dict(claim)])
    with pytest.raises(gsb.GSValidationError):
        gsb.validate_case(case, index=0)


def test_bad_difficulty_and_qualification_are_rejected():
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status",
                   "RESOLVED", positive_values=["RESOLVED"])
    case = _case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [claim], difficulty="IMPOSSIBLE")
    with pytest.raises(gsb.GSValidationError):
        gsb.validate_case(case, index=0)
    case2 = _case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [claim],
                  qualification="MADE_UP")
    with pytest.raises(gsb.GSValidationError):
        gsb.validate_case(case2, index=0)


# ===========================================================================
# 3. grade_claim() against REAL producer output -- the central proof
# ===========================================================================

def test_correct_confident_checker_claim_is_a_match():
    doc = _checker_doc(linked=True)
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status",
                   "RESOLVED", positive_values=["RESOLVED"],
                   abstention_values=["PARTIAL", "UNKNOWN"])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_MATCH
    assert result["actual_value"] == "RESOLVED"


def test_confidently_wrong_checker_is_a_false_positive():
    """The real extractor confidently reports RESOLVED (a checker linked with
    both a target and a mount side), but golden ground truth says this
    checker should NOT have resolved at this target (e.g. it is actually
    mounted on the wrong side of a bridge, caught by a human review) --
    expected_value is PARTIAL. This is the critical, never-averaged-away
    case: a confident claim that is simply wrong."""
    doc = _checker_doc(linked=True)
    assert doc["checker"][0]["status"] == "RESOLVED"  # sanity: the real producer is confident
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status",
                   "PARTIAL", positive_values=["RESOLVED"],
                   abstention_values=["UNKNOWN"])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_FALSE_POSITIVE
    assert result["actual_value"] == "RESOLVED"


def test_unlinked_checker_is_an_honest_abstention_not_a_false_positive():
    """No checker_links entry at all -> the real extractor reports UNKNOWN.
    Ground truth expects RESOLVED, but UNKNOWN is a declared abstention value
    for this claim, so it must NOT be scored as a false positive -- an honest
    'I don't know' is not the dangerous failure mode this metric targets."""
    doc = _checker_doc(linked=False)
    assert doc["checker"][0]["status"] == "UNKNOWN"
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status",
                   "RESOLVED", positive_values=["RESOLVED"],
                   abstention_values=["PARTIAL", "UNKNOWN"])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_HONEST_ABSTENTION


def test_partial_checker_graded_as_false_negative_when_not_declared_abstention():
    """A checker linked to a target but with no mount_side is PARTIAL. If a
    curator's claim declares only UNKNOWN as an abstention value (treating
    PARTIAL as a distinct, definite-but-wrong answer), a PARTIAL actual value
    when RESOLVED was expected reads FALSE_NEGATIVE, not FALSE_POSITIVE:
    the extractor under-claimed, it did not over-claim."""
    doc = _checker_doc(linked=True, mount_side=False)
    assert doc["checker"][0]["status"] == "PARTIAL"
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status",
                   "RESOLVED", positive_values=["RESOLVED"], abstention_values=["UNKNOWN"])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_FALSE_NEGATIVE


def test_target_missing_when_ground_truth_names_a_record_that_does_not_exist():
    doc = _checker_doc(linked=True)
    claim = _claim("c1", "checker", {"interface_row_id": "ep99_check_NEVER_EXTRACTED"},
                   "status", "RESOLVED", positive_values=["RESOLVED"])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_TARGET_MISSING


def test_path_error_on_unknown_field():
    doc = _checker_doc(linked=True)
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"},
                   "this_field_does_not_exist", "RESOLVED", positive_values=["RESOLVED"])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_PATH_ERROR


def test_path_error_on_ambiguous_match():
    entries = [conn.generate_protocol_check_entry("ep0_check", "usb3_vip", ["crc"], {}),
               conn.generate_protocol_check_entry("ep0_check_2", "usb3_vip", ["crc"], {})]
    checkers = va.build_checker_ir(entries, {})
    # force a genuine ambiguity: both records share a common field value
    docs = [c.to_dict() for c in checkers]
    for d in docs:
        d["vip_type"] = "usb3_vip"
    doc = {"checker": docs}
    claim = _claim("c1", "checker", {"vip_type": "usb3_vip"}, "status", "RESOLVED",
                   positive_values=["RESOLVED"])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_PATH_ERROR


def test_path_error_when_extracted_doc_missing_the_ir_list():
    claim = _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status", "RESOLVED",
                   positive_values=["RESOLVED"])
    result = gsb.grade_claim({}, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_PATH_ERROR


# --- scoreboard (boolean claim) --------------------------------------------

def test_scoreboard_confidently_comparable_but_wrong_is_false_positive():
    doc = _scoreboard_doc(boundary_agrees=True, resolved=True)
    assert doc["scoreboard"][0]["comparable"] is True
    claim = _claim("c1", "scoreboard", {"scoreboard_id": "ep0_scoreboard"}, "comparable",
                   False, positive_values=[True], abstention_values=[None])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_FALSE_POSITIVE


def test_scoreboard_correctly_flags_incomparable_endpoints_is_a_match():
    doc = _scoreboard_doc(boundary_agrees=False, resolved=True)
    assert doc["scoreboard"][0]["comparable"] is False
    claim = _claim("c1", "scoreboard", {"scoreboard_id": "ep0_scoreboard"}, "comparable",
                   False, positive_values=[True], abstention_values=[None])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_MATCH


def test_scoreboard_no_boundary_evidence_is_honest_abstention():
    doc = _scoreboard_doc(boundary_agrees=True, resolved=False)
    assert doc["scoreboard"][0]["comparable"] is None
    claim = _claim("c1", "scoreboard", {"scoreboard_id": "ep0_scoreboard"}, "comparable",
                   True, positive_values=[True], abstention_values=[None])
    result = gsb.grade_claim(doc, gsb.EK_VERIFICATION_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_HONEST_ABSTENTION


# --- design architecture: FSM ------------------------------------------

def test_clean_resolved_fsm_matches_ground_truth():
    doc = _design_doc_with_fsm(CLEAN_FSM_TEXT)
    cand = doc["modules"]["u_ctrl"]["fsm_extraction"]["candidates"][0]
    assert cand["status"] == "FSM_EXTRACTION_RESOLVED"
    claim = _claim("c1", "module_fsm_candidate", {"register_name": "state"}, "status",
                   "FSM_EXTRACTION_RESOLVED", positive_values=["FSM_EXTRACTION_RESOLVED"],
                   abstention_values=["FSM_EXTRACTION_PARTIAL", "FSM_EXTRACTION_UNPARSEABLE"],
                   module_name="u_ctrl")
    result = gsb.grade_claim(doc, gsb.EK_DESIGN_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_MATCH


def test_confidently_resolved_fsm_with_wrong_ground_truth_states_is_false_positive():
    """The real scan resolves this FSM cleanly (a confident, definite claim).
    Ground truth (e.g. from a manual RTL review) says the ACTUAL state set
    is different (a state this scan mis-split or missed) -- so a claim on
    the `states` field itself catches a confidently-wrong structural claim,
    not merely the coarse status field."""
    doc = _design_doc_with_fsm(CLEAN_FSM_TEXT)
    claim = _claim("c1", "module_fsm_candidate", {"register_name": "state"}, "states",
                   ["IDLE", "BUSY", "DONE", "WAIT"],  # ground truth: a 4th state exists
                   positive_values=[],  # any definite non-abstention list is a "confident claim"
                   abstention_values=[], module_name="u_ctrl")
    # states is a list -- not equal, not in abstention_values ([]), not in
    # positive_values ([]) either => falls to FALSE_NEGATIVE by this claim's
    # own declared (empty) positive_values. Demonstrate the FALSE_POSITIVE
    # path instead with the status field, which IS declared positive:
    status_claim = _claim("c2", "module_fsm_candidate", {"register_name": "state"}, "status",
                          "FSM_EXTRACTION_PARTIAL",  # ground truth: this should NOT be clean
                          positive_values=["FSM_EXTRACTION_RESOLVED"],
                          abstention_values=[], module_name="u_ctrl")
    result = gsb.grade_claim(doc, gsb.EK_DESIGN_ARCHITECTURE, status_claim)
    assert result["outcome"] == gsb.CLAIM_FALSE_POSITIVE
    result2 = gsb.grade_claim(doc, gsb.EK_DESIGN_ARCHITECTURE, claim)
    assert result2["outcome"] == gsb.CLAIM_FALSE_NEGATIVE


def test_ambiguous_fsm_is_honestly_partial_not_penalized_as_false_positive():
    doc = _design_doc_with_fsm(AMBIGUOUS_FSM_TEXT)
    cand = doc["modules"]["u_ctrl"]["fsm_extraction"]["candidates"][0]
    assert cand["status"] == "FSM_EXTRACTION_PARTIAL"  # IDLE has 2 candidate next states
    claim = _claim("c1", "module_fsm_candidate", {"register_name": "state"}, "status",
                   "FSM_EXTRACTION_RESOLVED", positive_values=["FSM_EXTRACTION_RESOLVED"],
                   abstention_values=["FSM_EXTRACTION_PARTIAL"], module_name="u_ctrl")
    result = gsb.grade_claim(doc, gsb.EK_DESIGN_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_HONEST_ABSTENTION


def test_fsm_claim_target_missing_when_module_never_built():
    doc = _design_doc_with_fsm(CLEAN_FSM_TEXT)
    claim = _claim("c1", "module_fsm_candidate", {"register_name": "state"}, "status",
                   "FSM_EXTRACTION_RESOLVED", positive_values=["FSM_EXTRACTION_RESOLVED"],
                   module_name="u_module_never_parsed")
    result = gsb.grade_claim(doc, gsb.EK_DESIGN_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_TARGET_MISSING


# --- design architecture: instance tree ---------------------------------

def test_instance_resolves_to_correct_module_is_a_match():
    doc = _instance_tree_doc(leaf_resolved=True)
    claim = _claim("c1", "instance_node", {"instance_name": "u_ep0"}, "module_name",
                   "usb_ep_ctrl", positive_values=[])
    result = gsb.grade_claim(doc, gsb.EK_DESIGN_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_MATCH


def test_instance_confidently_marked_resolved_but_wrong_module_is_false_positive():
    """The real instance-tree builder marks this instantiation `resolved:
    True` (a confident, definite claim -- the module WAS found among the
    parsed set). Ground truth says resolution should have failed (e.g. the
    fixture project under-declared its RTL file list and this instance
    should be an honest unresolved leaf) -- expected False. `resolved=True`
    is exactly the kind of confident-but-wrong claim this metric exists to
    catch."""
    doc = _instance_tree_doc(leaf_resolved=True)
    claim = _claim("c1", "instance_node", {"instance_name": "u_ep0"}, "resolved", False,
                   positive_values=[True], abstention_values=[])
    result = gsb.grade_claim(doc, gsb.EK_DESIGN_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_FALSE_POSITIVE


def test_unresolved_instance_leaf_is_honest_abstention():
    doc = _instance_tree_doc(leaf_resolved=False)
    claim = _claim("c1", "instance_node", {"instance_name": "u_ep0"}, "resolved", True,
                   positive_values=[True], abstention_values=[False])
    result = gsb.grade_claim(doc, gsb.EK_DESIGN_ARCHITECTURE, claim)
    assert result["outcome"] == gsb.CLAIM_HONEST_ABSTENTION


# ===========================================================================
# 4. summarize_claims() / claim_verdict() -- worst-wins KPI
# ===========================================================================

def test_summarize_claims_reports_headline_kpi_and_never_omits_zero():
    results = [
        {"outcome": gsb.CLAIM_MATCH}, {"outcome": gsb.CLAIM_MATCH},
        {"outcome": gsb.CLAIM_FALSE_POSITIVE}, {"outcome": gsb.CLAIM_HONEST_ABSTENTION},
    ]
    s = gsb.summarize_claims(results)
    assert s["kpi_status"] == "MEASURED"
    assert s["gradeable_claims"] == 3
    assert s["false_positive_architecture_claim_rate"] == pytest.approx(1 / 3, rel=1e-3)
    assert s["counts"][gsb.CLAIM_TARGET_MISSING] == 0  # zero, never omitted


def test_summarize_claims_empty_is_not_available_never_fabricated_zero():
    s = gsb.summarize_claims([])
    assert s["kpi_status"] == "NOT_AVAILABLE"
    assert s["false_positive_architecture_claim_rate"] is None
    assert s["claim_accuracy"] is None


def test_summarize_claims_all_abstention_is_not_available_gradeable_kpi():
    """Only abstentions -> gradeable_claims == 0 -> the rate that MATTERS
    (false-positive rate) must be NOT_AVAILABLE, never silently reported 0.0
    as if the extractor had been graded and found clean."""
    s = gsb.summarize_claims([{"outcome": gsb.CLAIM_HONEST_ABSTENTION}] * 3)
    assert s["kpi_status"] == "NOT_AVAILABLE"
    assert s["false_positive_architecture_claim_rate"] is None
    assert s["honest_abstention_rate"] == 1.0


def test_claim_verdict_is_worst_wins_false_positive_beats_everything():
    results = [{"outcome": gsb.CLAIM_MATCH}] * 50 + [{"outcome": gsb.CLAIM_FALSE_POSITIVE}]
    assert gsb.claim_verdict(results) == gsb.GS_RUN_FALSE_POSITIVE_DETECTED


def test_claim_verdict_false_negative_only_when_no_false_positive():
    results = [{"outcome": gsb.CLAIM_MATCH}, {"outcome": gsb.CLAIM_FALSE_NEGATIVE}]
    assert gsb.claim_verdict(results) == gsb.GS_RUN_FALSE_NEGATIVE_ONLY


def test_claim_verdict_clean_when_only_matches_and_abstentions():
    results = [{"outcome": gsb.CLAIM_MATCH}, {"outcome": gsb.CLAIM_HONEST_ABSTENTION}]
    assert gsb.claim_verdict(results) == gsb.GS_RUN_CLEAN


def test_claim_verdict_not_available_when_nothing_gradeable():
    results = [{"outcome": gsb.CLAIM_TARGET_MISSING}, {"outcome": gsb.CLAIM_PATH_ERROR}]
    assert gsb.claim_verdict(results) == gsb.GS_RUN_NOT_AVAILABLE


# ===========================================================================
# 5. Versioned registry -- the reused corpus mechanism
# ===========================================================================

def _basic_claim():
    return _claim("c1", "checker", {"interface_row_id": "ep0_check"}, "status", "RESOLVED",
                  positive_values=["RESOLVED"], abstention_values=["UNKNOWN", "PARTIAL"])


def test_register_then_load_round_trips(tmp_path):
    ds = _dataset("ds1", 1, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    stored = gsb.register_dataset_version(tmp_path, ds)
    assert stored["version"] == 1
    assert stored["previous_version"] is None
    loaded = gsb.load_dataset(tmp_path, "ds1")
    assert loaded["content_digest"] == stored["content_digest"]
    assert gsb.list_datasets(tmp_path) == ["ds1"]
    assert gsb.list_versions(tmp_path, "ds1") == [1]


def test_reregister_same_version_same_content_is_idempotent(tmp_path):
    ds = _dataset("ds1", 1, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    a = gsb.register_dataset_version(tmp_path, ds)
    b = gsb.register_dataset_version(tmp_path, json.loads(json.dumps(ds)))
    assert a["content_digest"] == b["content_digest"]


def test_reregister_same_version_different_content_is_refused(tmp_path):
    ds = _dataset("ds1", 1, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    gsb.register_dataset_version(tmp_path, ds)
    ds2 = _dataset("ds1", 1, [_case("case-2", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    with pytest.raises(gsb.GSVersionConflictError):
        gsb.register_dataset_version(tmp_path, ds2)


def test_back_dated_version_is_refused(tmp_path):
    ds1 = _dataset("ds1", 1, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    gsb.register_dataset_version(tmp_path, ds1)
    ds2 = _dataset("ds1", 2, [_case("case-2", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    gsb.register_dataset_version(tmp_path, ds2)
    ds_backdated = _dataset("ds1", 1, [_case("case-3", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    with pytest.raises(gsb.GSVersionConflictError):
        gsb.register_dataset_version(tmp_path, ds_backdated)


def test_no_op_bump_is_refused(tmp_path):
    ds1 = _dataset("ds1", 1, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    gsb.register_dataset_version(tmp_path, ds1)
    ds2 = _dataset("ds1", 2, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    with pytest.raises(gsb.GSVersionConflictError):
        gsb.register_dataset_version(tmp_path, ds2)


def test_verify_dataset_integrity_detects_drift(tmp_path):
    ds = _dataset("ds1", 1, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    gsb.register_dataset_version(tmp_path, ds)
    clean = gsb.verify_dataset_integrity(tmp_path, "ds1", 1)
    assert clean["status"] == gsb.INTEGRITY_OK

    path = gsb.version_path(tmp_path, "ds1", 1)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    on_disk["cases"][0]["known_ambiguity"] = "edited in place, no bump"
    path.write_text(json.dumps(on_disk), encoding="utf-8")
    drifted = gsb.verify_dataset_integrity(tmp_path, "ds1", 1)
    assert drifted["status"] == gsb.INTEGRITY_DRIFT
    assert "case-1" in drifted["drifted_case_ids"]

    with pytest.raises(gsb.GSVersionConflictError):
        gsb.register_dataset_version(tmp_path, ds)  # re-registering over drift is refused


def test_diff_dataset_versions_names_added_removed_modified(tmp_path):
    case1 = _case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])
    ds1 = _dataset("ds1", 1, [case1])
    gsb.register_dataset_version(tmp_path, ds1)

    case1_modified = _case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()],
                           subsystem_id="usb_ep0_v2")
    case2 = _case("case-2", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])
    ds2 = _dataset("ds1", 2, [case1_modified, case2])
    gsb.register_dataset_version(tmp_path, ds2)

    diff = gsb.diff_dataset_versions(tmp_path, "ds1", 1, 2)
    assert diff["bumped"] is True
    assert diff["added_case_ids"] == ["case-2"]
    assert diff["modified_case_ids"] == ["case-1"]
    assert diff["removed_case_ids"] == []


def test_missing_dataset_raises_not_found(tmp_path):
    with pytest.raises(gsb.GSNotFoundError):
        gsb.load_dataset(tmp_path, "does-not-exist")


# ===========================================================================
# 6. Leakage tracking
# ===========================================================================

def test_leakage_report_clean_with_no_tuning_uses(tmp_path):
    ds = _dataset("ds1", 1, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    gsb.register_dataset_version(tmp_path, ds)
    report = gsb.leakage_report(tmp_path, "ds1", subject_id="agent-x", subject_version="1.0")
    assert report["status"] == gsb.LEAKAGE_CLEAN
    assert report["leaked_count"] == 0


def test_leakage_report_partial_then_full(tmp_path):
    other_claim = _claim("c1", "checker", {"interface_row_id": "OTHER_EP"}, "status",
                         "RESOLVED", positive_values=["RESOLVED"])
    ds = _dataset("ds1", 1, [
        _case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()]),
        _case("case-2", gsb.EK_VERIFICATION_ARCHITECTURE, [other_claim]),
    ])
    gsb.register_dataset_version(tmp_path, ds)
    gsb.record_tuning_use(tmp_path, "ds1", "case-1", subject_id="agent-x",
                          subject_version="1.0", used_for="prompt calibration")
    partial = gsb.leakage_report(tmp_path, "ds1", subject_id="agent-x", subject_version="1.0")
    assert partial["status"] == gsb.LEAKAGE_PARTIAL
    assert partial["leaked_case_ids"] == ["case-1"]

    gsb.record_tuning_use(tmp_path, "ds1", "case-2", subject_id="agent-x",
                          subject_version="1.0", used_for="prompt calibration")
    full = gsb.leakage_report(tmp_path, "ds1", subject_id="agent-x", subject_version="1.0")
    assert full["status"] == gsb.LEAKAGE_FULL


def test_leakage_is_keyed_on_substance_not_case_id():
    """Renaming a case (case_id changes) but keeping the same extraction_kind
    / fixture_ref / claims must carry the SAME question digest -- leakage
    survives a rename. Changing the claims changes the question digest --
    leakage is NOT carried over."""
    claim = _basic_claim()
    case_a = _case("case-A", gsb.EK_VERIFICATION_ARCHITECTURE, [claim])
    case_a_renamed = _case("case-B", gsb.EK_VERIFICATION_ARCHITECTURE, [claim])
    assert gsb.case_question_digest(case_a) == gsb.case_question_digest(case_a_renamed)

    claim2 = _claim("c1", "checker", {"interface_row_id": "OTHER"}, "status", "RESOLVED",
                    positive_values=["RESOLVED"])
    case_a_changed = _case("case-A", gsb.EK_VERIFICATION_ARCHITECTURE, [claim2])
    assert gsb.case_question_digest(case_a) != gsb.case_question_digest(case_a_changed)


def test_tuning_use_for_unknown_case_is_refused(tmp_path):
    ds = _dataset("ds1", 1, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    gsb.register_dataset_version(tmp_path, ds)
    with pytest.raises(gsb.GSNotFoundError):
        gsb.record_tuning_use(tmp_path, "ds1", "case-does-not-exist", subject_id="a",
                              subject_version="1", used_for="x")


# ===========================================================================
# 7. run_golden_subsystem_eval() -- end to end, real producer output
# ===========================================================================

def _eval_dataset():
    checker_claim = _claim(
        "checker-status", "checker", {"interface_row_id": "ep0_check"}, "status",
        "RESOLVED", positive_values=["RESOLVED"], abstention_values=["PARTIAL", "UNKNOWN"],
        note="fixture project's checker-link table names u_ep0/POST_BRIDGE")
    scoreboard_claim = _claim(
        "scoreboard-comparable", "scoreboard", {"scoreboard_id": "ep0_scoreboard"},
        "comparable", False, positive_values=[True], abstention_values=[None],
        note="the fixture's phy_boundary table shows the two endpoints as different "
             "boundary kinds (SERIAL vs PARALLEL) -- ground truth: NOT comparable")
    case = _case("va-case-1", gsb.EK_VERIFICATION_ARCHITECTURE,
                [checker_claim, scoreboard_claim])
    return _dataset("va-golden-subsystems", 1, [case])


def test_eval_clean_run_when_extractor_matches_ground_truth(tmp_path):
    gsb.register_dataset_version(tmp_path, _eval_dataset())
    doc = {**_checker_doc(linked=True), **_scoreboard_doc(boundary_agrees=False, resolved=True)}
    record = gsb.run_golden_subsystem_eval(
        tmp_path, "va-golden-subsystems",
        subject={"subject_id": "va-extractor", "subject_version": "1.0.0"},
        extracted_docs_by_case={"va-case-1": doc})
    assert record["status"] == gsb.GS_RUN_CLEAN
    assert record["summary"]["false_positive_architecture_claim_rate"] == 0.0
    assert record["leakage"]["status"] == gsb.LEAKAGE_CLEAN
    # persisted to disk
    runs = gsb.read_eval_runs(tmp_path, "va-golden-subsystems")
    assert len(runs) == 1
    assert runs[0]["run_id"] == record["run_id"]


def test_eval_detects_false_positive_and_worst_wins_over_the_whole_run(tmp_path):
    """Ground truth says this scoreboard's endpoints are NOT comparable. The
    real extractor confidently reports comparable=True (agreeing boundary
    kinds) -- a confidently WRONG, positive claim. This single false
    positive must fail the WHOLE run's status, even though the checker
    claim in the same case is clean -- worst-wins, never averaged."""
    gsb.register_dataset_version(tmp_path, _eval_dataset())
    doc = {**_checker_doc(linked=True),
          **_scoreboard_doc(boundary_agrees=True, resolved=True)}  # comparable actually True
    record = gsb.run_golden_subsystem_eval(
        tmp_path, "va-golden-subsystems",
        subject={"subject_id": "va-extractor", "subject_version": "1.0.0"},
        extracted_docs_by_case={"va-case-1": doc})
    assert record["status"] == gsb.GS_RUN_FALSE_POSITIVE_DETECTED
    assert record["summary"]["false_positive_architecture_claim_rate"] == pytest.approx(0.5)
    fp_claims = [c for c in record["cases"][0]["claims"] if c["outcome"] == gsb.CLAIM_FALSE_POSITIVE]
    assert len(fp_claims) == 1
    assert fp_claims[0]["claim_id"] == "scoreboard-comparable"


def test_eval_case_not_executed_when_extracted_doc_missing(tmp_path):
    gsb.register_dataset_version(tmp_path, _eval_dataset())
    record = gsb.run_golden_subsystem_eval(
        tmp_path, "va-golden-subsystems",
        subject={"subject_id": "va-extractor", "subject_version": "1.0.0"},
        extracted_docs_by_case={})
    assert record["cases"][0]["case_verdict"] == gsb.CASE_NOT_EXECUTED
    assert record["cases"][0]["executed"] is False
    assert record["status"] == gsb.GS_RUN_NOT_AVAILABLE


def test_eval_inadmissible_when_the_only_case_was_used_for_tuning(tmp_path):
    gsb.register_dataset_version(tmp_path, _eval_dataset())
    gsb.record_tuning_use(tmp_path, "va-golden-subsystems", "va-case-1",
                          subject_id="va-extractor", subject_version="1.0.0",
                          used_for="prompt tuning for checker-link detection")
    doc = {**_checker_doc(linked=True), **_scoreboard_doc(boundary_agrees=True, resolved=True)}
    record = gsb.run_golden_subsystem_eval(
        tmp_path, "va-golden-subsystems",
        subject={"subject_id": "va-extractor", "subject_version": "1.0.0"},
        extracted_docs_by_case={"va-case-1": doc})
    assert record["status"] == gsb.GS_RUN_INADMISSIBLE


def test_eval_refuses_to_run_without_subject_identity(tmp_path):
    gsb.register_dataset_version(tmp_path, _eval_dataset())
    with pytest.raises(gsb.GSValidationError):
        gsb.run_golden_subsystem_eval(
            tmp_path, "va-golden-subsystems", subject={},
            extracted_docs_by_case={"va-case-1": {}})


def test_eval_refuses_a_drifted_dataset(tmp_path):
    gsb.register_dataset_version(tmp_path, _eval_dataset())
    path = gsb.version_path(tmp_path, "va-golden-subsystems", 1)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    on_disk["cases"][0]["known_ambiguity"] = "edited in place"
    path.write_text(json.dumps(on_disk), encoding="utf-8")
    with pytest.raises(gsb.GSVersionConflictError):
        gsb.run_golden_subsystem_eval(
            tmp_path, "va-golden-subsystems",
            subject={"subject_id": "x", "subject_version": "1"},
            extracted_docs_by_case={})


def test_format_eval_report_mentions_status_and_case(tmp_path):
    gsb.register_dataset_version(tmp_path, _eval_dataset())
    doc = {**_checker_doc(linked=True), **_scoreboard_doc(boundary_agrees=True, resolved=True)}
    record = gsb.run_golden_subsystem_eval(
        tmp_path, "va-golden-subsystems",
        subject={"subject_id": "va-extractor", "subject_version": "1.0.0"},
        extracted_docs_by_case={"va-case-1": doc})
    text = gsb.format_eval_report(record)
    assert "va-golden-subsystems" in text
    assert "va-case-1" in text
    assert gsb.GS_RUN_CLEAN in text


# ===========================================================================
# 8. CLI (execute_verb / main) -- driven as real subprocesses
# ===========================================================================

def test_cli_register_list_verify_via_subprocess(tmp_path):
    import subprocess
    import sys

    ds = _dataset("cli-ds", 1, [_case("case-1", gsb.EK_VERIFICATION_ARCHITECTURE, [_basic_claim()])])
    ds_file = tmp_path / "ds.json"
    ds_file.write_text(json.dumps(ds), encoding="utf-8")

    root_dir = Path(__file__).resolve().parents[1]

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.golden_subsystem_benchmark", *args,
             "--root", str(tmp_path)],
            cwd=str(root_dir), capture_output=True, text=True, timeout=60,
        )

    r = run("register", "--dataset-id", "cli-ds", "--json-file", str(ds_file))
    assert r.returncode == 0, r.stderr
    assert "registered cli-ds v1" in r.stdout

    r = run("list")
    assert r.returncode == 0, r.stderr
    assert "cli-ds" in r.stdout

    r = run("verify", "--dataset-id", "cli-ds")
    assert r.returncode == 0, r.stderr
    assert "INTACT" in r.stdout

    r = run("leakage", "--dataset-id", "cli-ds", "--subject-id", "agent-x",
           "--subject-version", "1.0")
    assert r.returncode == 0, r.stderr
    assert "CLEAN" in r.stdout


def test_cli_eval_via_subprocess_detects_false_positive(tmp_path):
    import subprocess
    import sys

    ds_file = tmp_path / "ds.json"
    ds_file.write_text(json.dumps(_eval_dataset()), encoding="utf-8")
    docs_file = tmp_path / "docs.json"
    doc = {**_checker_doc(linked=True), **_scoreboard_doc(boundary_agrees=True, resolved=True)}
    docs_file.write_text(json.dumps({"va-case-1": doc}), encoding="utf-8")

    root_dir = Path(__file__).resolve().parents[1]

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.golden_subsystem_benchmark", *args,
             "--root", str(tmp_path)],
            cwd=str(root_dir), capture_output=True, text=True, timeout=60,
        )

    r = run("register", "--dataset-id", "va-golden-subsystems", "--json-file", str(ds_file))
    assert r.returncode == 0, r.stderr

    r = run("eval", "--dataset-id", "va-golden-subsystems", "--subject-id", "va-extractor",
           "--subject-version", "1.0.0", "--extracted-docs-file", str(docs_file))
    assert r.returncode == 1, r.stdout + r.stderr
    assert gsb.GS_RUN_FALSE_POSITIVE_DETECTED in r.stdout

    r = run("runs", "--dataset-id", "va-golden-subsystems")
    assert r.returncode == 1, r.stderr
    assert "va-golden-subsystems" in r.stdout


def test_cli_unknown_verb_and_missing_args_report_usage_errors(tmp_path):
    text, code = gsb.execute_verb("bogus-verb", root=tmp_path)
    assert code == 2
    text2, code2 = gsb.execute_verb("verify", root=tmp_path)  # missing --dataset-id
    assert code2 == 2
