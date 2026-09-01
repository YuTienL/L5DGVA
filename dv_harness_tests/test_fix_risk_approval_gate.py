"""Tests for tools/verification_flow/fix_risk_approval_gate.py's real
ControlPlane cross-check (2026-09-02, RE_AUDIT/FAILURE_RECOVERY
approval-gate audit).

Confirmed gap: dv_harness/engine.py's run_stage() has a real hard-stop that
forces a genuine human `dv-harness approve` call before PROMOTION_READINESS
and SIGNOFF can close (see cp.get_approval/ControlPlane.approve()). RE_AUDIT
had no counterpart -- fix_risk_approval_gate.py only checked that the
agent's own self-declared "approved_for_modify" boolean was True, which is
just JSON the SAME agent proposing the fix writes in its own reply.

This gate now additionally requires a real .dv-harness/control.json
approval record for RE_AUDIT (the exact same file/shape
dv_harness.control_plane.ControlPlane.approve()/get_approval() read and
write) whenever the plan's own risk_level is HIGH or its classification is
DUT_BUG (the classification vocabulary tools/senior_dv/failure_attribution.py
already uses) -- see the gate script's own module comment for the full
rationale. A TB_BUG/low-or-medium-risk fix is deliberately unaffected."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "fix_risk_approval_gate.py"


def _run_gate(root: Path, plan: dict):
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--plan", str(plan_path)],
        cwd=str(root), capture_output=True, text=True, timeout=30,
    )
    out = json.loads((r.stdout or "").strip() or "{}")
    return r.returncode, out


def _base_plan(**overrides):
    plan = {
        "root_cause_id": "RCA-1",
        "fix_plan": "add prefetch guard in ep0 fifo ctrl",
        "risk_assessment": "contained to ep0 datapath",
        "affected_scope": "usb_dev.ep0",
        "regression_plan": "rerun ep0 test suite",
        "rollback_plan": "revert commit c1",
        "root_cause_confidence": "HIGH",
        "risk_level": "LOW",
        "high_risk_reviewed": False,
        "approved_for_modify": True,
    }
    plan.update(overrides)
    return plan


def test_tb_bug_low_risk_fix_is_unaffected_by_control_plane_cross_check():
    # Regression: a routine TB_BUG/low-risk fix must NOT require a real
    # ControlPlane approval -- no .dv-harness/control.json exists at all
    # here, and the gate must still PASS purely off the agent-supplied plan,
    # exactly as before this hardening pass.
    tmp = Path(tempfile.mkdtemp())
    try:
        rc, out = _run_gate(tmp, _base_plan(classification="TB_BUG", risk_level="LOW"))
        assert rc == 0 and out["status"] == "PASS"
    finally:
        shutil.rmtree(tmp)


def test_dut_bug_fix_without_real_control_plane_approval_fails_closed():
    tmp = Path(tempfile.mkdtemp())
    try:
        rc, out = _run_gate(tmp, _base_plan(classification="DUT_BUG", risk_level="LOW"))
        assert rc == 6
        assert out["reason"] == "HIGH_RISK_FIX_WITHOUT_CONTROL_PLANE_APPROVAL"
    finally:
        shutil.rmtree(tmp)


def test_high_risk_fix_without_real_control_plane_approval_fails_closed():
    # Self-declared approved_for_modify:true alone is not enough once
    # risk_level is HIGH -- the whole point of this hardening pass.
    tmp = Path(tempfile.mkdtemp())
    try:
        rc, out = _run_gate(tmp, _base_plan(
            classification="TB_BUG", risk_level="HIGH", high_risk_reviewed=True))
        assert rc == 6
        assert out["reason"] == "HIGH_RISK_FIX_WITHOUT_CONTROL_PLANE_APPROVAL"
    finally:
        shutil.rmtree(tmp)


def test_high_risk_fix_passes_with_real_control_plane_approval():
    # A genuine `dv-harness approve RE_AUDIT` (via the real ControlPlane
    # class -- the SAME mechanism engine.py's own PROMOTION_READINESS/
    # SIGNOFF hard-stop reads) must unblock the exact same plan that just
    # failed closed above.
    from dv_harness.control_plane import ControlPlane
    tmp = Path(tempfile.mkdtemp())
    try:
        ControlPlane(tmp).approve("RE_AUDIT", note="reviewed", reviewer_id="alice")
        rc, out = _run_gate(tmp, _base_plan(
            classification="TB_BUG", risk_level="HIGH", high_risk_reviewed=True))
        assert rc == 0 and out["status"] == "PASS"
    finally:
        shutil.rmtree(tmp)


def test_dut_bug_fix_passes_with_real_control_plane_approval():
    from dv_harness.control_plane import ControlPlane
    tmp = Path(tempfile.mkdtemp())
    try:
        ControlPlane(tmp).approve("RE_AUDIT", note="reviewed", reviewer_id="alice")
        rc, out = _run_gate(tmp, _base_plan(classification="DUT_BUG", risk_level="LOW"))
        assert rc == 0 and out["status"] == "PASS"
    finally:
        shutil.rmtree(tmp)


def test_approval_for_a_different_stage_does_not_satisfy_re_audit_check():
    # A real approval exists, but it was never granted FOR RE_AUDIT -- must
    # not be treated as authorizing this DUT_BUG fix.
    from dv_harness.control_plane import ControlPlane
    tmp = Path(tempfile.mkdtemp())
    try:
        ControlPlane(tmp).approve("SIGNOFF", note="unrelated", reviewer_id="alice")
        rc, out = _run_gate(tmp, _base_plan(classification="DUT_BUG", risk_level="LOW"))
        assert rc == 6
        assert out["reason"] == "HIGH_RISK_FIX_WITHOUT_CONTROL_PLANE_APPROVAL"
    finally:
        shutil.rmtree(tmp)


def test_preexisting_checks_still_enforced_before_control_plane_cross_check():
    # The new cross-check is additive -- the original field-completeness/
    # confidence/self-declared-approval checks must still run and fail
    # first when they are the actual problem.
    tmp = Path(tempfile.mkdtemp())
    try:
        rc, out = _run_gate(tmp, _base_plan(approved_for_modify=False))
        assert rc == 5 and out["reason"] == "FIX_NOT_APPROVED_FOR_MODIFICATION"
    finally:
        shutil.rmtree(tmp)
