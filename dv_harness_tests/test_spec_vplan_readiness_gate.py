"""Tests for dv_harness/spec_vplan_readiness_gate.py -- SPEC_VPLAN_READY."""
import ast
import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

from dv_harness import spec_vplan_readiness_gate as gate


def _code_only_tokens(src: str) -> str:
    """Reconstruct the source with all STRING and COMMENT tokens (docstrings,
    prose, comments) blanked out -- so a check below sees only real Python
    code, never a name merely discussed in the module's own prose. Mirrors
    the `tokenize`-based approach this repo's own test suite already uses
    for this exact kind of source-level governance check."""
    out = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok_type, tok_string, *_ in tokens:
            if tok_type in (tokenize.STRING, tokenize.COMMENT):
                continue
            out.append(tok_string)
    except tokenize.TokenizeError:
        return src
    return " ".join(out)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _cond(name, status, reason=""):
    return {"condition_name": name, "status": status, "reason": reason}


# ===========================================================================
# Core positive path
# ===========================================================================

def test_all_met_is_qualified():
    conditions = [
        _cond("spec_doc_map_no_orphans", gate.MET),
        _cond("requirement_contracts_all_complete", gate.MET),
        _cond("vplan_spec_delta_resolved", gate.MET),
    ]
    result = gate.evaluate_spec_vplan_readiness(conditions)
    assert result.status == gate.QUALIFIED
    assert result.spec_vplan_ready is True
    assert result.evaluated_count == 3
    assert result.blocking == []
    assert result.incomplete_evidence == []
    assert len(result.clear) == 3


def test_result_to_dict_shape():
    conditions = [_cond("only_condition", gate.MET, "all good")]
    result = gate.evaluate_spec_vplan_readiness(conditions)
    d = result.to_dict()
    assert d["schema_version"] == gate.SCHEMA_VERSION
    assert d["spec_vplan_ready"] is True
    assert d["status"] == gate.QUALIFIED
    assert d["evaluated_count"] == 1
    assert d["clear"][0]["condition_name"] == "only_condition"
    assert "checked_at" in d


# ===========================================================================
# Worst-wins / no-averaging discipline: negative controls
# ===========================================================================

def test_single_unmet_blocks_regardless_of_how_many_are_met():
    conditions = [_cond(f"clean_{i}", gate.MET) for i in range(20)]
    conditions.append(_cond("one_bad_requirement", gate.UNMET, "requirement REQ-9 is CONTRADICTORY"))
    result = gate.evaluate_spec_vplan_readiness(conditions)
    assert result.status == gate.NOT_QUALIFIED
    assert result.spec_vplan_ready is False
    assert len(result.blocking) == 1
    assert result.blocking[0]["condition_name"] == "one_bad_requirement"
    # Not averaged away: 20 clean conditions do not dilute the one UNMET.
    assert len(result.clear) == 20


def test_unknown_condition_produces_incomplete_evidence_not_qualified_or_not_qualified_word():
    conditions = [
        _cond("spec_doc_map_no_orphans", gate.MET),
        _cond("vplan_spec_delta_resolved", gate.UNKNOWN, "spec_vplan_delta.py not yet run"),
    ]
    result = gate.evaluate_spec_vplan_readiness(conditions)
    assert result.status == gate.INCOMPLETE_EVIDENCE
    assert result.spec_vplan_ready is False
    assert result.status != gate.QUALIFIED
    assert result.status != gate.NOT_QUALIFIED


def test_not_available_condition_also_produces_incomplete_evidence():
    conditions = [
        _cond("spec_doc_map_no_orphans", gate.MET),
        _cond("requirement_contracts_all_complete", gate.NOT_AVAILABLE, "no requirement_contract.json on disk"),
    ]
    result = gate.evaluate_spec_vplan_readiness(conditions)
    assert result.status == gate.INCOMPLETE_EVIDENCE
    assert result.spec_vplan_ready is False
    assert len(result.incomplete_evidence) == 1


def test_unmet_outranks_unknown_when_both_present():
    """A project with BOTH a confirmed-failing condition and an unresolved one
    is NOT_QUALIFIED, not the softer INCOMPLETE_EVIDENCE -- the confirmed
    failure is the more actionable, more urgent fact."""
    conditions = [
        _cond("confirmed_bad", gate.UNMET, "requirement REQ-3 is AMBIGUOUS"),
        _cond("not_yet_checked", gate.UNKNOWN, "spec_doc_map.py has not run yet"),
    ]
    result = gate.evaluate_spec_vplan_readiness(conditions)
    assert result.status == gate.NOT_QUALIFIED
    assert result.spec_vplan_ready is False


def test_empty_conditions_list_is_incomplete_evidence_never_vacuously_qualified():
    result = gate.evaluate_spec_vplan_readiness([])
    assert result.status == gate.INCOMPLETE_EVIDENCE
    assert result.spec_vplan_ready is False
    assert result.evaluated_count == 0


def test_none_conditions_is_incomplete_evidence():
    result = gate.evaluate_spec_vplan_readiness(None)
    assert result.status == gate.INCOMPLETE_EVIDENCE
    assert result.spec_vplan_ready is False


# ===========================================================================
# Malformed-input negative controls -- must raise, never silently resolve
# ===========================================================================

def test_missing_condition_name_key_raises():
    with pytest.raises(gate.SpecVplanReadinessGateError) as exc:
        gate.evaluate_spec_vplan_readiness([{"status": gate.MET}])
    assert exc.value.reason == "MALFORMED_CONDITION_RECORD"


def test_missing_status_key_raises():
    with pytest.raises(gate.SpecVplanReadinessGateError) as exc:
        gate.evaluate_spec_vplan_readiness([{"condition_name": "x"}])
    assert exc.value.reason == "MALFORMED_CONDITION_RECORD"


def test_empty_condition_name_raises():
    with pytest.raises(gate.SpecVplanReadinessGateError) as exc:
        gate.evaluate_spec_vplan_readiness([_cond("   ", gate.MET)])
    assert exc.value.reason == "EMPTY_CONDITION_NAME"


def test_unrecognized_status_raises():
    with pytest.raises(gate.SpecVplanReadinessGateError) as exc:
        gate.evaluate_spec_vplan_readiness([_cond("x", "MAYBE")])
    assert exc.value.reason == "UNKNOWN_CONDITION_STATUS"
    assert "MAYBE" in exc.value.detail["status"]


def test_duplicate_condition_name_raises():
    with pytest.raises(gate.SpecVplanReadinessGateError) as exc:
        gate.evaluate_spec_vplan_readiness([
            _cond("same_name", gate.MET),
            _cond("same_name", gate.UNMET),
        ])
    assert exc.value.reason == "DUPLICATE_CONDITION_NAME"


def test_non_mapping_record_raises():
    with pytest.raises(gate.SpecVplanReadinessGateError) as exc:
        gate.evaluate_spec_vplan_readiness(["not_a_dict"])
    assert exc.value.reason == "MALFORMED_CONDITION_RECORD"


# ===========================================================================
# Vocabulary discipline
# ===========================================================================

def test_vocabularies_do_not_collide_with_models_status():
    # The import-time guard already ran at module import (would have raised);
    # re-assert it is callable and clean on demand too.
    gate.assert_no_verification_verdict_vocabulary()


def test_condition_and_verdict_vocabularies_are_disjoint_from_each_other():
    assert not (set(gate.CONDITION_STATUSES) & set(gate.GATE_VERDICTS))


def test_reason_is_carried_through_verbatim():
    result = gate.evaluate_spec_vplan_readiness([
        _cond("x", gate.UNMET, "very specific reason text"),
    ])
    assert result.blocking[0]["reason"] == "very specific reason text"


def test_reason_defaults_to_empty_string_when_absent():
    result = gate.evaluate_spec_vplan_readiness([{"condition_name": "x", "status": gate.MET}])
    assert result.clear[0]["reason"] == ""


# ===========================================================================
# Report formatting
# ===========================================================================

def test_format_readiness_report_names_blocking_and_incomplete_conditions():
    result = gate.evaluate_spec_vplan_readiness([
        _cond("bad_one", gate.UNMET, "req contradictory"),
        _cond("unknown_one", gate.UNKNOWN, "not run yet"),
    ])
    text = gate.format_readiness_report(result)
    assert "NOT_QUALIFIED" in text
    assert "bad_one" in text
    assert "req contradictory" in text


def test_format_readiness_report_qualified_lists_clear_conditions():
    result = gate.evaluate_spec_vplan_readiness([_cond("a", gate.MET), _cond("b", gate.MET)])
    text = gate.format_readiness_report(result)
    assert "QUALIFIED" in text
    assert "a" in text and "b" in text


# ===========================================================================
# execute_verb() / CLI front door
# ===========================================================================

def test_execute_verb_statuses():
    text, code = gate.execute_verb("statuses")
    assert code == 0
    for s in gate.CONDITION_STATUSES:
        assert s in text


def test_execute_verb_verdicts_json():
    text, code = gate.execute_verb("verdicts", as_json=True)
    assert code == 0
    parsed = json.loads(text)
    assert set(parsed) == set(gate.GATE_VERDICTS)


def test_execute_verb_evaluate_requires_conditions_path():
    text, code = gate.execute_verb("evaluate")
    assert code == 2
    assert "requires --conditions" in text


def test_execute_verb_evaluate_qualified_exit_0(tmp_path):
    p = tmp_path / "conditions.json"
    p.write_text(json.dumps([_cond("a", gate.MET)]), encoding="utf-8")
    text, code = gate.execute_verb("evaluate", conditions_path=str(p))
    assert code == 0
    assert "QUALIFIED" in text


def test_execute_verb_evaluate_not_qualified_exit_1(tmp_path):
    p = tmp_path / "conditions.json"
    p.write_text(json.dumps([_cond("a", gate.UNMET)]), encoding="utf-8")
    text, code = gate.execute_verb("evaluate", conditions_path=str(p))
    assert code == 1


def test_execute_verb_evaluate_incomplete_evidence_exit_2(tmp_path):
    p = tmp_path / "conditions.json"
    p.write_text(json.dumps([_cond("a", gate.UNKNOWN)]), encoding="utf-8")
    text, code = gate.execute_verb("evaluate", conditions_path=str(p))
    assert code == 2
    assert "INCOMPLETE_EVIDENCE" in text


def test_execute_verb_evaluate_malformed_reports_error_exit_2(tmp_path):
    p = tmp_path / "conditions.json"
    p.write_text(json.dumps([{"condition_name": "a", "status": "BOGUS"}]), encoding="utf-8")
    text, code = gate.execute_verb("evaluate", conditions_path=str(p))
    assert code == 2
    assert "UNKNOWN_CONDITION_STATUS" in text


def test_execute_verb_unknown_verb():
    text, code = gate.execute_verb("bogus_verb")
    assert code == 2
    assert "unknown verb" in text


def test_real_subprocess_evaluate_qualified(tmp_path):
    p = tmp_path / "conditions.json"
    p.write_text(json.dumps([_cond("spec_ok", gate.MET)]), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.spec_vplan_readiness_gate",
         "evaluate", "--conditions", str(p), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    assert parsed["status"] == "QUALIFIED"
    assert parsed["spec_vplan_ready"] is True


def test_real_subprocess_evaluate_not_qualified(tmp_path):
    p = tmp_path / "conditions.json"
    p.write_text(json.dumps([_cond("spec_bad", gate.UNMET, "bad")]), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.spec_vplan_readiness_gate",
         "evaluate", "--conditions", str(p), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr
    parsed = json.loads(proc.stdout)
    assert parsed["status"] == "NOT_QUALIFIED"


def test_real_subprocess_statuses_verb():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.spec_vplan_readiness_gate", "statuses"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "MET" in proc.stdout


# ===========================================================================
# Governance-boundary discipline: never touches human-approval machinery
# ===========================================================================

def test_module_source_never_references_approval_or_control_plane_machinery():
    src = Path(gate.__file__).read_text(encoding="utf-8")
    code_only = _code_only_tokens(src)
    forbidden_tokens = [
        "ControlPlane", "can_signoff", "assert_human_approval",
        "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError",
    ]
    for tok in forbidden_tokens:
        assert tok not in code_only, f"unexpected governance token found in real code: {tok}"


def test_module_never_imports_forbidden_batch_siblings():
    """The module's actual `import`/`from ... import` statements must never
    name a batch sibling this task forbids importing -- checked via a real
    AST parse of the module's imports, not a substring scan of its own prose
    (which legitimately DISCUSSES those modules by name as precedent)."""
    tree = ast.parse(Path(gate.__file__).read_text(encoding="utf-8"))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
    forbidden_modules = {
        "verification_intake_contract", "subsystem_maturity_gate",
        "functional_coverage_signoff",
    }
    assert not (imported_modules & forbidden_modules), (
        f"must not import forbidden batch sibling(s): {imported_modules & forbidden_modules}")
