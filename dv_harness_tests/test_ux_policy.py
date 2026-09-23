"""Real tests for dv_harness/ux_policy.py -- the three formal UX modes
(GUIDED_MODE/ENGINEER_MODE/EXPERT_MODE) as a policy layer over the ONE
existing L5DGVA workflow, never a second workflow.

No mocking: exercises the real UXPolicy dataclass, compute_action_disposition(),
resolve_i_dont_know(), and the G1-G5 gate table directly.
"""
from pathlib import Path

import pytest

from dv_harness import ux_policy as ux


# ---------------------------------------------------------------------------
# Mode / Role / Authorization / Autonomy are independent concepts (Section 5)
# ---------------------------------------------------------------------------

def test_ux_mode_role_authorization_are_independent_fields():
    policy = ux.UXPolicy(
        mode=ux.UXMode.EXPERT, role="DV_LEAD",
        authorization=ux.Authorization.JUNIOR,
        autonomy_level=ux.AutonomyLevel.STANDARD,
    )
    # EXPERT mode does NOT imply SIGNOFF authorization -- they are stored
    # and read back completely independently.
    assert policy.mode == ux.UXMode.EXPERT
    assert policy.authorization == ux.Authorization.JUNIOR


def test_role_domain_derives_de_dv_shared_from_free_text_role():
    assert ux.UXPolicy(mode=ux.UXMode.ENGINEER, role="DV").role_domain == "DV"
    assert ux.UXPolicy(mode=ux.UXMode.ENGINEER, role="DV_LEAD").role_domain == "DV"
    assert ux.UXPolicy(mode=ux.UXMode.ENGINEER, role="DE").role_domain == "DE"
    assert ux.UXPolicy(mode=ux.UXMode.ENGINEER, role="DE_ARCHITECT").role_domain == "DE"
    assert ux.UXPolicy(mode=ux.UXMode.ENGINEER, role="DE_DV_LEAD").role_domain == "SHARED"


def test_default_authorization_and_autonomy_are_derived_but_overridable():
    guided = ux.UXPolicy(mode=ux.UXMode.GUIDED, role="DV")
    engineer = ux.UXPolicy(mode=ux.UXMode.ENGINEER, role="DV")
    expert = ux.UXPolicy(mode=ux.UXMode.EXPERT, role="DV")
    assert guided.autonomy_level == ux.AutonomyLevel.CONSERVATIVE
    assert engineer.autonomy_level == ux.AutonomyLevel.STANDARD
    assert expert.autonomy_level == ux.AutonomyLevel.AGGRESSIVE
    # Authorization is never derived from mode -- always defaults to the
    # lowest rank unless the caller explicitly states otherwise.
    assert expert.authorization == ux.Authorization.JUNIOR


# ---------------------------------------------------------------------------
# Derived interaction-policy fields per mode (Sections 2-4)
# ---------------------------------------------------------------------------

def test_guided_mode_interaction_policy():
    p = ux.UXPolicy(mode=ux.UXMode.GUIDED, role="DV")
    assert p.explanation_level == "FULL"
    assert p.proactive_guidance is True
    assert p.evidence_detail == "PROGRESSIVE_DISCLOSURE"


def test_engineer_mode_interaction_policy():
    p = ux.UXPolicy(mode=ux.UXMode.ENGINEER, role="DV")
    assert p.explanation_level == "CONCISE"
    assert p.proactive_guidance is False
    assert p.evidence_detail == "SUMMARY"


def test_expert_mode_interaction_policy():
    p = ux.UXPolicy(mode=ux.UXMode.EXPERT, role="DV")
    assert p.explanation_level == "ON_REQUEST"
    assert p.proactive_guidance is False
    assert p.evidence_detail == "FULL_INTERNAL_STATE"


# ---------------------------------------------------------------------------
# Section 15: backward-compatible default
# ---------------------------------------------------------------------------

def test_default_mode_is_engineer_for_backward_compatibility():
    assert ux.DEFAULT_UX_MODE == ux.UXMode.ENGINEER


# ---------------------------------------------------------------------------
# Section 7: dynamic, multi-factor action disposition
# ---------------------------------------------------------------------------

def test_compile_repair_low_risk_reversible_is_auto():
    p = ux.UXPolicy(mode=ux.UXMode.ENGINEER, role="DV")
    d = ux.compute_action_disposition(
        p, action=ux.ActionContext(
            name="compile_repair", risk="LOW", evidence_quality="HIGH",
            confidence="HIGH", impact="LOW", reversible=True,
            signoff_impact="NONE", authority_domain="VERIFICATION",
        ))
    assert d.disposition == ux.ActionDisposition.AUTO


def test_rtl_functional_modification_high_impact_routes_to_de_human_gate():
    p = ux.UXPolicy(mode=ux.UXMode.EXPERT, role="DV_LEAD",
                     authorization=ux.Authorization.SIGNOFF)
    d = ux.compute_action_disposition(
        p, action=ux.ActionContext(
            name="rtl_functional_modification", risk="HIGH",
            evidence_quality="HIGH", confidence="HIGH", impact="HIGH",
            reversible=False, signoff_impact="NONE",
            authority_domain="DESIGN",
        ))
    assert d.disposition == ux.ActionDisposition.HUMAN_GATE
    assert d.gate_owner_domain == "DESIGN"


def test_coverage_waiver_signoff_impact_routes_to_dv_human_gate():
    p = ux.UXPolicy(mode=ux.UXMode.ENGINEER, role="DV")
    d = ux.compute_action_disposition(
        p, action=ux.ActionContext(
            name="coverage_waiver", risk="MEDIUM", evidence_quality="HIGH",
            confidence="HIGH", impact="MEDIUM", reversible=True,
            signoff_impact="HIGH", authority_domain="VERIFICATION",
        ))
    assert d.disposition == ux.ActionDisposition.HUMAN_GATE
    assert d.gate_owner_domain == "VERIFICATION"


def test_low_confidence_or_low_evidence_never_auto_regardless_of_mode():
    for mode in (ux.UXMode.GUIDED, ux.UXMode.ENGINEER, ux.UXMode.EXPERT):
        p = ux.UXPolicy(mode=mode, role="DV")
        d = ux.compute_action_disposition(
            p, action=ux.ActionContext(
                name="ambiguous_step", risk="LOW", evidence_quality="LOW",
                confidence="LOW", impact="LOW", reversible=True,
                signoff_impact="NONE", authority_domain="VERIFICATION",
            ))
        assert d.disposition != ux.ActionDisposition.AUTO, mode


def test_expert_mode_does_not_bypass_authorization():
    """Section 5's own governing example: EXPERT_MODE + JUNIOR authorization
    must not auto-grant a SIGNOFF-tier action."""
    p = ux.UXPolicy(mode=ux.UXMode.EXPERT, role="DV",
                     authorization=ux.Authorization.JUNIOR)
    d = ux.compute_action_disposition(
        p, action=ux.ActionContext(
            name="signoff_approve", risk="LOW", evidence_quality="HIGH",
            confidence="HIGH", impact="LOW", reversible=True,
            signoff_impact="NONE", authority_domain="VERIFICATION",
            required_authorization=ux.Authorization.SIGNOFF,
        ))
    assert d.disposition in (ux.ActionDisposition.HUMAN_GATE, ux.ActionDisposition.BLOCKED)


def test_guided_mode_never_defaults_bare_auto_for_a_material_action():
    """GUIDED_MODE's autonomy ceiling is CONSERVATIVE -- even a nominally
    low-risk material action stays REVIEW_REQUIRED so the mentor-style
    explanation actually gets shown."""
    p = ux.UXPolicy(mode=ux.UXMode.GUIDED, role="DV")
    d = ux.compute_action_disposition(
        p, action=ux.ActionContext(
            name="generate_test", risk="LOW", evidence_quality="HIGH",
            confidence="HIGH", impact="MEDIUM", reversible=True,
            signoff_impact="NONE", authority_domain="VERIFICATION",
        ))
    assert d.disposition == ux.ActionDisposition.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# G1-G5 human gates (Section 6)
# ---------------------------------------------------------------------------

def test_g_gates_have_the_five_named_owners():
    owners = {g.gate_id: g.owner_domain for g in ux.HUMAN_GATES}
    assert owners["G1"] == "DESIGN"
    assert owners["G2"] == "VERIFICATION"
    assert owners["G3"] == "DESIGN"
    assert owners["G4"] == "VERIFICATION"
    assert owners["G5"] == "SHARED"


# ---------------------------------------------------------------------------
# I_DONT_KNOW evidence-retrieval-then-escalation (Section 2)
# ---------------------------------------------------------------------------

def test_i_dont_know_walks_evidence_sources_before_escalating():
    calls = []

    def source_a(question):
        calls.append("source_a")
        return None  # unresolved

    def source_b(question):
        calls.append("source_b")
        return "found it"  # resolved

    result = ux.resolve_i_dont_know(
        "How many endpoints?", evidence_sources=[source_a, source_b])
    assert calls == ["source_a", "source_b"]
    assert result.resolved is True
    assert result.answer == "found it"
    assert result.escalated is False


def test_i_dont_know_escalates_when_all_evidence_sources_are_exhausted():
    def source_a(question):
        return None

    result = ux.resolve_i_dont_know(
        "How many endpoints?", evidence_sources=[source_a],
        authority_domain="SHARED")
    assert result.resolved is False
    assert result.escalated is True
    assert result.escalation.owner_domain == "SHARED"


def test_i_dont_know_is_not_treated_as_a_failure():
    """A caller-facing check: the result object never carries an 'error' or
    'failure' flag for a legitimate I_DONT_KNOW -- only resolved/escalated."""
    result = ux.resolve_i_dont_know("q", evidence_sources=[])
    assert not hasattr(result, "error")
    assert not hasattr(result, "failure")


# ---------------------------------------------------------------------------
# Persistence + mode switching preserves everything else (Section 10)
# ---------------------------------------------------------------------------

def test_save_and_load_round_trips(tmp_path: Path):
    p = ux.UXPolicy(mode=ux.UXMode.EXPERT, role="DV_LEAD",
                     authorization=ux.Authorization.SIGNOFF)
    ux.save_ux_policy(tmp_path, p)
    loaded = ux.load_ux_policy(tmp_path)
    assert loaded == p


def test_load_ux_policy_returns_default_when_none_persisted(tmp_path: Path):
    loaded = ux.load_ux_policy(tmp_path)
    assert loaded.mode == ux.DEFAULT_UX_MODE


def test_switching_mode_does_not_touch_other_state_files(tmp_path: Path):
    (tmp_path / ".dv-harness").mkdir()
    lifecycle_file = tmp_path / ".dv-harness" / "lifecycle.json"
    lifecycle_file.write_text('{"milestone": "M3"}', encoding="utf-8")
    before = lifecycle_file.read_text(encoding="utf-8")

    p1 = ux.UXPolicy(mode=ux.UXMode.GUIDED, role="DV")
    ux.save_ux_policy(tmp_path, p1)
    p2 = ux.load_ux_policy(tmp_path)
    p2 = ux.switch_mode(p2, ux.UXMode.EXPERT)
    ux.save_ux_policy(tmp_path, p2)

    after = lifecycle_file.read_text(encoding="utf-8")
    assert before == after
    assert ux.load_ux_policy(tmp_path).mode == ux.UXMode.EXPERT


def test_switch_mode_refuses_when_authorization_would_be_bypassed():
    """Switching TO expert must not silently escalate authorization --
    Section 10's own 'switching to EXPERT_MODE must not bypass it' rule."""
    p = ux.UXPolicy(mode=ux.UXMode.GUIDED, role="DV",
                     authorization=ux.Authorization.JUNIOR)
    switched = ux.switch_mode(p, ux.UXMode.EXPERT)
    assert switched.authorization == ux.Authorization.JUNIOR


# ---------------------------------------------------------------------------
# CLI banner rendering (Section 9)
# ---------------------------------------------------------------------------

def test_render_status_banner_shows_mode_role_authorization():
    p = ux.UXPolicy(mode=ux.UXMode.GUIDED, role="DV",
                     authorization=ux.Authorization.JUNIOR)
    text = ux.render_status_banner(p, level="SUBSYSTEM", protocol="USB")
    assert "GUIDED_MODE" in text
    assert "DV" in text
    assert "JUNIOR" in text
    assert "SUBSYSTEM" in text
    assert "USB" in text
