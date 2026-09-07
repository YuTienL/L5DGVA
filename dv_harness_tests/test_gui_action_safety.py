"""dv_harness_tests/test_gui_action_safety.py -- proves the GUI Action Safety
Framework (dv_harness/gui_action_safety.py) against REAL evidence:

  - the real dashboard_auth.py dispatch tables (never mocked) for category
    coverage / required-permission cross-checks / drift detection,
  - a REAL POST /api/control dispatch, driven through the real
    gui_audit_log.wrap_dispatch() + dashboard._dispatch_control(), for the
    rollback-plan builder's positive path,
  - real negative controls proving an action with no evidence, no matching
    record, or a failed dispatch is reported honestly rather than guessed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import dashboard, dashboard_auth
from dv_harness import gui_action_safety as gas
from dv_harness import gui_audit_log


# ---------------------------------------------------------------------------
# Category / declaration shape
# ---------------------------------------------------------------------------

def test_exactly_11_categories():
    assert len(gas.ACTION_CATEGORIES) == 11
    assert len(set(gas.ACTION_CATEGORIES)) == 11


def test_21_real_actions_declared():
    # 8 non-control endpoints + 13 real control commands.
    assert len(gas.GUI_ACTION_DECLARATIONS) == 21


def test_every_declaration_carries_all_required_fields():
    for action_id, decl in gas.GUI_ACTION_DECLARATIONS.items():
        assert decl.action_id == action_id
        assert decl.category in gas.ACTION_CATEGORIES
        assert decl.scope and decl.scope.strip()
        assert decl.impact in gas.IMPACT_VALUES
        assert decl.required_role in dashboard_auth.ROLES
        assert isinstance(decl.reversible, bool)
        assert decl.rollback_plan_kind in gas.ROLLBACK_KINDS


def test_all_declarations_internally_consistent():
    violations = gas.validate_all_declarations()
    bad = {k: v for k, v in violations.items() if v}
    assert bad == {}


def test_category_coverage_is_total():
    # Re-running the import-time self-check must not raise.
    gas.assert_category_coverage_is_total()


# ---------------------------------------------------------------------------
# Reuse: required_permission must never be a second, independently-typed
# table -- it must always agree with dashboard_auth.required_role() itself.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_id", sorted(gas.GUI_ACTION_DECLARATIONS))
def test_required_permission_matches_dashboard_auth_directly(action_id):
    prefix = f"POST {dashboard_auth.CONTROL_ENDPOINT} "
    if action_id.startswith(prefix):
        cmd = action_id[len(prefix):]
        expected_role, expected_action = dashboard_auth.required_role(
            dashboard_auth.CONTROL_ENDPOINT, cmd)
    else:
        endpoint = action_id[len("POST "):]
        expected_role, expected_action = dashboard_auth.required_role(endpoint)
    assert expected_action == action_id
    assert gas.required_permission(action_id) == expected_role


def test_get_declaration_unknown_action_raises():
    with pytest.raises(gas.GuiActionSafetyError):
        gas.get_declaration("POST /api/does-not-exist")


# ---------------------------------------------------------------------------
# Coverage drift guard (mirrors dashboard_auth.py's own real drift proof)
# ---------------------------------------------------------------------------

def test_coverage_matches_real_dashboard_dispatch():
    # Must not raise against the REAL dashboard.py source on disk.
    gas.assert_coverage_matches_real_dispatch()


def test_coverage_drift_is_detected_on_a_stale_declared_endpoint(monkeypatch):
    # dashboard_auth's own two guards still pass (real dashboard.py is
    # untouched); this module's OWN 21-action table now claims an endpoint
    # dashboard.py does not really dispatch -- a real, isolated drift only
    # THIS module's comparison can catch.
    patched = dict(gas.GUI_ACTION_DECLARATIONS)
    fake = gas.GUIActionDeclaration(
        action_id="POST /api/some-new-endpoint", category=gas.CAT_HARNESS_LIFECYCLE,
        scope="fixture", impact=gas.IMPACT_STATE_MUTATION_REVERSIBLE,
        required_role="OPERATOR", reversible=True,
        rollback_plan_kind=gas.ROLLBACK_KIND_SCOPE_RESTORE,
    )
    patched[fake.action_id] = fake
    monkeypatch.setattr(gas, "GUI_ACTION_DECLARATIONS", patched)
    with pytest.raises(gas.GuiActionSafetyDriftError) as exc:
        gas.assert_coverage_matches_real_dispatch()
    assert "/api/some-new-endpoint" in str(exc.value)


def test_coverage_drift_is_detected_on_a_missing_declared_endpoint(monkeypatch):
    patched = dict(gas.GUI_ACTION_DECLARATIONS)
    del patched["POST /api/setup"]
    monkeypatch.setattr(gas, "GUI_ACTION_DECLARATIONS", patched)
    with pytest.raises(gas.GuiActionSafetyDriftError) as exc:
        gas.assert_coverage_matches_real_dispatch()
    assert "/api/setup" in str(exc.value)


def test_coverage_drift_is_detected_on_a_missing_control_command(monkeypatch):
    patched = dict(gas.GUI_ACTION_DECLARATIONS)
    del patched["POST /api/control PAUSE"]
    monkeypatch.setattr(gas, "GUI_ACTION_DECLARATIONS", patched)
    with pytest.raises(gas.GuiActionSafetyDriftError) as exc:
        gas.assert_coverage_matches_real_dispatch()
    assert "PAUSE" in str(exc.value)


def test_coverage_drift_is_detected_on_a_stale_control_command(monkeypatch):
    patched = dict(gas.GUI_ACTION_DECLARATIONS)
    fake = gas.GUIActionDeclaration(
        action_id="POST /api/control NEW_COMMAND", category=gas.CAT_RUN_CONTROL,
        scope="fixture", impact=gas.IMPACT_STATE_MUTATION_REVERSIBLE,
        required_role="OPERATOR", reversible=True,
        rollback_plan_kind=gas.ROLLBACK_KIND_SCOPE_RESTORE,
    )
    patched[fake.action_id] = fake
    monkeypatch.setattr(gas, "GUI_ACTION_DECLARATIONS", patched)
    with pytest.raises(gas.GuiActionSafetyDriftError) as exc:
        gas.assert_coverage_matches_real_dispatch()
    assert "NEW_COMMAND" in str(exc.value)


# ---------------------------------------------------------------------------
# Declaration-level internal-consistency validator, driven negatively
# ---------------------------------------------------------------------------

def test_validate_declaration_flags_reversible_with_not_reversible_kind():
    bad = gas.GUIActionDeclaration(
        action_id="POST /api/control PAUSE", category=gas.CAT_RUN_CONTROL,
        scope="fixture scope", impact=gas.IMPACT_STATE_MUTATION_REVERSIBLE,
        required_role="OPERATOR", reversible=True,
        rollback_plan_kind=gas.ROLLBACK_KIND_NOT_REVERSIBLE,
    )
    violations = gas.validate_declaration(bad)
    assert any("reversible=True" in v for v in violations)


def test_validate_declaration_flags_irreversible_with_scope_restore_kind():
    bad = gas.GUIActionDeclaration(
        action_id="POST /api/control APPROVE", category=gas.CAT_DECISION_APPROVAL,
        scope="fixture scope", impact=gas.IMPACT_GOVERNANCE_RECORD,
        required_role="APPROVER", reversible=False,
        rollback_plan_kind=gas.ROLLBACK_KIND_SCOPE_RESTORE,
    )
    violations = gas.validate_declaration(bad)
    assert any("reversible=False" in v for v in violations)


def test_validate_declaration_flags_stale_required_role():
    bad = gas.GUIActionDeclaration(
        action_id="POST /api/control PAUSE", category=gas.CAT_RUN_CONTROL,
        scope="fixture scope", impact=gas.IMPACT_STATE_MUTATION_REVERSIBLE,
        required_role="APPROVER",  # real role for PAUSE is OPERATOR
        reversible=True, rollback_plan_kind=gas.ROLLBACK_KIND_SCOPE_RESTORE,
    )
    violations = gas.validate_declaration(bad)
    assert any("disagrees with dashboard_auth.required_role()" in v for v in violations)


def test_validate_declaration_flags_unrecognized_category():
    bad = gas.GUIActionDeclaration(
        action_id="POST /api/control PAUSE", category="NOT_A_REAL_CATEGORY",
        scope="fixture scope", impact=gas.IMPACT_STATE_MUTATION_REVERSIBLE,
        required_role="OPERATOR", reversible=True,
        rollback_plan_kind=gas.ROLLBACK_KIND_SCOPE_RESTORE,
    )
    violations = gas.validate_declaration(bad)
    assert any("category" in v for v in violations)


def test_validate_declaration_flags_empty_scope():
    bad = gas.GUIActionDeclaration(
        action_id="POST /api/control PAUSE", category=gas.CAT_RUN_CONTROL,
        scope="   ", impact=gas.IMPACT_STATE_MUTATION_REVERSIBLE,
        required_role="OPERATOR", reversible=True,
        rollback_plan_kind=gas.ROLLBACK_KIND_SCOPE_RESTORE,
    )
    violations = gas.validate_declaration(bad)
    assert any("scope" in v for v in violations)


def test_declare_constructor_refuses_an_inconsistent_declaration():
    from dv_harness.gui_action_safety import _declare
    with pytest.raises(gas.GuiActionSafetyError):
        _declare(
            path="/api/control", control_command="PAUSE",
            category=gas.CAT_RUN_CONTROL, scope="x",
            impact=gas.IMPACT_STATE_MUTATION_REVERSIBLE,
            reversible=True, rollback_plan_kind=gas.ROLLBACK_KIND_NOT_REVERSIBLE,
        )


# ---------------------------------------------------------------------------
# Structural read-only guard
# ---------------------------------------------------------------------------

def test_module_only_reads_never_writes():
    gas.assert_module_only_reads()  # must not raise against the real source


def test_module_only_reads_has_real_detection_power(tmp_path):
    fake = tmp_path / "fake_gui_action_safety.py"
    fake.write_text("Path('x').write_text('boom')\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="write_text"):
        gas.assert_module_only_reads(fake)


# ---------------------------------------------------------------------------
# Rollback plan builder -- real evidence, real absence
# ---------------------------------------------------------------------------

def _init_project(root: Path) -> None:
    (root / ".dv-harness").mkdir(parents=True, exist_ok=True)


def test_rollback_plan_reversible_action_reads_real_recorded_evidence(tmp_path):
    root = tmp_path / "proj"
    _init_project(root)
    body = {"command": "PAUSE", "reason": "unit test pause"}
    result = gui_audit_log.wrap_dispatch(root, body, dashboard._dispatch_control)
    assert result["paused"] is True

    plan = gas.build_rollback_plan(root, "POST /api/control PAUSE")
    assert plan["status"] == gas.RB_STATUS_BUILT
    assert plan["applied"] is False
    assert plan["source_record"]["action"] == "PAUSE"
    entries_by_key = {e["scope_key"]: e for e in plan["entries"]}
    assert entries_by_key["paused"]["before_value"] is None
    assert entries_by_key["paused"]["after_value"] is True
    assert entries_by_key["paused"]["restore_action"] == "RESTORE_VALUE"
    assert entries_by_key["paused_reason"]["after_value"] == "unit test pause"


def test_rollback_plan_second_dispatch_reads_the_most_recent_record(tmp_path):
    root = tmp_path / "proj"
    _init_project(root)
    gui_audit_log.wrap_dispatch(root, {"command": "PAUSE", "reason": "first"}, dashboard._dispatch_control)
    gui_audit_log.wrap_dispatch(root, {"command": "RESUME"}, dashboard._dispatch_control)
    gui_audit_log.wrap_dispatch(root, {"command": "PAUSE", "reason": "second"}, dashboard._dispatch_control)

    plan = gas.build_rollback_plan(root, "POST /api/control PAUSE")
    entries_by_key = {e["scope_key"]: e for e in plan["entries"]}
    assert entries_by_key["paused_reason"]["after_value"] == "second"


def test_rollback_plan_not_reversible_action_never_fabricates_a_restore(tmp_path):
    root = tmp_path / "proj"
    _init_project(root)
    gui_audit_log.wrap_dispatch(
        root, {"command": "APPROVE", "stage": "VPLAN", "note": "looks good"},
        dashboard._dispatch_control)

    plan = gas.build_rollback_plan(root, "POST /api/control APPROVE")
    assert plan["status"] == gas.RB_STATUS_NOT_REVERSIBLE
    assert plan["entries"] == []
    assert plan["reason"]


def test_rollback_plan_no_evidence_route_for_non_control_endpoint(tmp_path):
    root = tmp_path / "proj"
    _init_project(root)
    plan = gas.build_rollback_plan(root, "POST /api/setup")
    assert plan["status"] == gas.RB_STATUS_NO_EVIDENCE_ROUTE
    assert plan["entries"] == []
    assert plan["applied"] is False


def test_rollback_plan_no_record_found_when_action_never_dispatched(tmp_path):
    root = tmp_path / "proj"
    _init_project(root)
    plan = gas.build_rollback_plan(root, "POST /api/control RESUME")
    assert plan["status"] == gas.RB_STATUS_NO_RECORD_FOUND
    assert plan["entries"] == []


def test_rollback_plan_dispatch_failed_reports_nothing_to_restore(tmp_path):
    root = tmp_path / "proj"
    _init_project(root)
    # REDIRECT with no "stage" raises ValueError inside _dispatch_control;
    # wrap_dispatch catches it and still records a structured ERROR entry.
    with pytest.raises(ValueError):
        gui_audit_log.wrap_dispatch(root, {"command": "REDIRECT"}, dashboard._dispatch_control)

    plan = gas.build_rollback_plan(root, "POST /api/control REDIRECT")
    assert plan["status"] == gas.RB_STATUS_DISPATCH_FAILED
    assert plan["entries"] == []


def test_rollback_plan_unknown_action_raises(tmp_path):
    with pytest.raises(gas.GuiActionSafetyError):
        gas.build_rollback_plan(tmp_path, "POST /api/nope")


def test_rollback_plan_never_mutates_the_project(tmp_path):
    root = tmp_path / "proj"
    _init_project(root)
    gui_audit_log.wrap_dispatch(root, {"command": "PAUSE"}, dashboard._dispatch_control)
    before_files = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    gas.build_rollback_plan(root, "POST /api/control PAUSE")
    gas.build_rollback_plan(root, "POST /api/control APPROVE")
    gas.build_rollback_plan(root, "POST /api/setup")
    after_files = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before_files == after_files


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_declarations_table_lists_every_action():
    table = gas.render_declarations_table()
    for action_id in gas.declared_actions():
        assert action_id in table


# ---------------------------------------------------------------------------
# CLI (real subprocess, matching this project's own convention)
# ---------------------------------------------------------------------------

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.gui_action_safety", *args],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True,
    )


def test_cli_declarations_json():
    proc = _run_cli("declarations", "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert len(data) == 21


def test_cli_validate_exits_zero_on_a_clean_table():
    proc = _run_cli("validate")
    assert proc.returncode == 0


def test_cli_coverage_exits_zero_against_the_real_repo():
    proc = _run_cli("coverage")
    assert proc.returncode == 0


def test_cli_rollback_plan_no_record_found(tmp_path):
    root = tmp_path / "proj"
    _init_project(root)
    proc = _run_cli("rollback-plan", "POST /api/control RESUME", "--root", str(root), "--json")
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == gas.RB_STATUS_NO_RECORD_FOUND


def test_cli_rollback_plan_built(tmp_path):
    root = tmp_path / "proj"
    _init_project(root)
    gui_audit_log.wrap_dispatch(root, {"command": "PAUSE"}, dashboard._dispatch_control)
    proc = _run_cli("rollback-plan", "POST /api/control PAUSE", "--root", str(root), "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["status"] == gas.RB_STATUS_BUILT
