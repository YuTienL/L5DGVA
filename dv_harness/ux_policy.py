"""dv_harness/ux_policy.py -- the three formal UX modes (GUIDED_MODE /
ENGINEER_MODE / EXPERT_MODE) as an interaction-policy layer over the ONE
existing L5DGVA workflow.

WHAT THIS IS NOT: a second DV workflow, a second Knowledge Brain, or a
duplicated per-mode orchestration engine. This module reuses the existing
`.dv-harness/` state files, `lifecycle.py`'s milestone tracking,
`question_queue.py`'s human-decision escalation vocabulary, and
`dashboard_auth.py`'s ranked-role pattern (VIEWER < OPERATOR < APPROVER)
-- it invents no parallel mechanism for anything those already do.

FOUR INDEPENDENT CONCEPTS (never conflated):
  - `UXMode`        -- how much is explained, how much confirmation is
                        asked, how aggressively autonomy proceeds.
  - `role`           -- free-text job-function string (e.g. "DV", "DE",
                        "DV_LEAD"). `UXPolicy.role_domain` derives the
                        DESIGN/VERIFICATION/SHARED authority axis from it
                        by prefix, reusing the DE/DV vocabulary the
                        DE/DV Role-Based HITL roadmap
                        (.work/phase3-dual-repo-consolidation/
                        M4_5_DE_DV_ROLE_BASED_HITL/) already froze.
  - `Authorization`  -- a ranked privilege level (JUNIOR < ENGINEER <
                        SENIOR < SIGNOFF), the same "ranked tuple + rank
                        dict, deny-by-default on the unmapped case" shape
                        `dashboard_auth.py`'s VIEWER/OPERATOR/APPROVER
                        already uses -- never derived from `UXMode`.
  - `AutonomyLevel`  -- a per-session autonomy CEILING (CONSERVATIVE /
                        STANDARD / AGGRESSIVE), defaulted from `UXMode`
                        but a ceiling only: `compute_action_disposition()`
                        still requires real evidence/confidence/
                        reversibility before it will ever return AUTO,
                        regardless of how permissive the ceiling is.

`compute_action_disposition()` is Section 7's own multi-factor formula,
implemented as an explicit, checkable decision table (never a black-box
score) over: UX mode's autonomy ceiling, role/authorization, and the
caller-supplied task risk/evidence-quality/confidence/impact/
reversibility/signoff-impact. EXPERT_MODE's ceiling never overrides an
action's own `required_authorization` -- Section 5's own "mode is not
equivalent to authorization" rule, enforced in code, not merely stated.

`resolve_i_dont_know()` is the GUIDED_MODE `I_DONT_KNOW` flow (Section 2):
walk caller-supplied evidence sources in order (Knowledge Brain, spec,
RTL, VIP docs, prior KC -- whatever the caller wires in) and escalate via
the G1-G5 gate table only once every source returns unresolved. This
module does not itself call `memory_router.py`/`source_authority.py` --
the caller supplies those as `evidence_sources` callables, exactly the
same "route a decision to a real existing mechanism, do not re-implement
it" discipline `RCA_ROLE_ROUTING.md` (the DE/DV HITL roadmap's own
routing table) already documents for RCA escalation.

PERSISTENCE: `.dv-harness/ux_policy.json`, a single small file distinct
from `lifecycle.json`/`state.json`/`control.json` -- switching UX mode
touches only this file (see `test_switching_mode_does_not_touch_other_
state_files`), so it can never lose lifecycle/evidence/regression state
by construction, not merely by convention.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

SCHEMA_VERSION = "1.0"


class UXPolicyError(ValueError):
    """Same reason/detail convention `IntakeModeError` already uses."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# UXMode
# ---------------------------------------------------------------------------

class UXMode(str, Enum):
    GUIDED = "GUIDED_MODE"
    ENGINEER = "ENGINEER_MODE"
    EXPERT = "EXPERT_MODE"


#: Section 15: backward-compatible default for an unspecified mode. Chosen
#: over GUIDED (too much unrequested explanation for an existing scripted
#: caller) and over EXPERT (an existing caller has almost certainly never
#: opted into "advanced controls / minimal safety text").
DEFAULT_UX_MODE = UXMode.ENGINEER


def resolve_ux_mode(mode: "UXMode | str") -> UXMode:
    if isinstance(mode, UXMode):
        return mode
    try:
        return UXMode(str(mode).strip().upper() if str(mode).strip().upper().endswith("_MODE")
                      else f"{str(mode).strip().upper()}_MODE")
    except ValueError:
        raise UXPolicyError("UNKNOWN_UX_MODE", {
            "mode": mode, "known_modes": [m.value for m in UXMode]})


# ---------------------------------------------------------------------------
# Authorization -- ranked, deny-by-default, same shape as dashboard_auth.py's
# VIEWER/OPERATOR/APPROVER (reused convention, not reused code: that module
# is scoped to the dashboard's own HTTP endpoints, this one to workflow
# actions -- different resource, same pattern).
# ---------------------------------------------------------------------------

class Authorization(str, Enum):
    JUNIOR = "JUNIOR"
    ENGINEER = "ENGINEER"
    SENIOR = "SENIOR"
    SIGNOFF = "SIGNOFF"


AUTHORIZATION_ORDER = (Authorization.JUNIOR, Authorization.ENGINEER,
                        Authorization.SENIOR, Authorization.SIGNOFF)
AUTHORIZATION_RANK = {a: i for i, a in enumerate(AUTHORIZATION_ORDER)}

#: Never derived from UXMode -- a caller who does not state one gets the
#: LOWEST rank, so an unspecified authorization can never accidentally
#: authorize a consequential action (deny-by-default, same discipline
#: `dashboard_auth.UNMAPPED_ACTION_ROLE` already applies).
DEFAULT_AUTHORIZATION = Authorization.JUNIOR


def resolve_authorization(value: "Authorization | str | None") -> Authorization:
    if value is None:
        return DEFAULT_AUTHORIZATION
    if isinstance(value, Authorization):
        return value
    try:
        return Authorization(str(value).strip().upper())
    except ValueError:
        raise UXPolicyError("UNKNOWN_AUTHORIZATION", {
            "authorization": value, "known": [a.value for a in AUTHORIZATION_ORDER]})


# ---------------------------------------------------------------------------
# AutonomyLevel -- a per-session CEILING, defaulted from UXMode but never
# itself sufficient to authorize AUTO (see compute_action_disposition()).
# ---------------------------------------------------------------------------

class AutonomyLevel(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    STANDARD = "STANDARD"
    AGGRESSIVE = "AGGRESSIVE"


DEFAULT_AUTONOMY_BY_MODE = {
    UXMode.GUIDED: AutonomyLevel.CONSERVATIVE,
    UXMode.ENGINEER: AutonomyLevel.STANDARD,
    UXMode.EXPERT: AutonomyLevel.AGGRESSIVE,
}


# ---------------------------------------------------------------------------
# Per-mode derived interaction-policy fields (Sections 2-4, 11)
# ---------------------------------------------------------------------------

_EXPLANATION_LEVEL = {UXMode.GUIDED: "FULL", UXMode.ENGINEER: "CONCISE", UXMode.EXPERT: "ON_REQUEST"}
_CONFIRMATION_POLICY = {UXMode.GUIDED: "CONFIRM_MOST_ACTIONS",
                         UXMode.ENGINEER: "CONFIRM_EXCEPTIONS_ONLY",
                         UXMode.EXPERT: "CONFIRM_ONLY_WHEN_GATED"}
_EVIDENCE_DETAIL = {UXMode.GUIDED: "PROGRESSIVE_DISCLOSURE",
                    UXMode.ENGINEER: "SUMMARY",
                    UXMode.EXPERT: "FULL_INTERNAL_STATE"}
_PROACTIVE_GUIDANCE = {UXMode.GUIDED: True, UXMode.ENGINEER: False, UXMode.EXPERT: False}
_ESCALATION_BEHAVIOR = {UXMode.GUIDED: "OFFER_ASK_DE_ASK_SENIOR_DV",
                        UXMode.ENGINEER: "ESCALATE_ON_AMBIGUITY_OR_RISK",
                        UXMode.EXPERT: "ESCALATE_ONLY_AT_MANDATORY_GATE"}


# ---------------------------------------------------------------------------
# UXPolicy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UXPolicy:
    mode: UXMode
    role: str = "DV"
    authorization: Authorization = DEFAULT_AUTHORIZATION
    autonomy_level: Optional[AutonomyLevel] = None  # None => derived from mode

    def __post_init__(self):
        object.__setattr__(self, "mode", resolve_ux_mode(self.mode))
        object.__setattr__(self, "authorization", resolve_authorization(self.authorization))
        if self.autonomy_level is None:
            object.__setattr__(self, "autonomy_level", DEFAULT_AUTONOMY_BY_MODE[self.mode])
        elif isinstance(self.autonomy_level, str):
            object.__setattr__(self, "autonomy_level", AutonomyLevel(self.autonomy_level.strip().upper()))

    # -- derived, read-only interaction-policy fields --
    @property
    def explanation_level(self) -> str:
        return _EXPLANATION_LEVEL[self.mode]

    @property
    def confirmation_policy(self) -> str:
        return _CONFIRMATION_POLICY[self.mode]

    @property
    def evidence_detail(self) -> str:
        return _EVIDENCE_DETAIL[self.mode]

    @property
    def proactive_guidance(self) -> bool:
        return _PROACTIVE_GUIDANCE[self.mode]

    @property
    def escalation_behavior(self) -> str:
        return _ESCALATION_BEHAVIOR[self.mode]

    @property
    def role_domain(self) -> str:
        """DE | DV | SHARED, derived from the free-text `role` by prefix --
        the same DE/DV abbreviation Section 5's own examples use
        (`ROLE = DV`, `ROLE = DV_LEAD`). Distinct from an ACTION's or
        GATE's `authority_domain`/`owner_domain` (DESIGN/VERIFICATION/
        SHARED, the DE_DV_AUTHORITY_MATRIX.csv vocabulary) -- a person's
        role and a decision's authority domain are related but not the
        same field, kept as two spellings on purpose so neither is ever
        silently substituted for the other."""
        r = (self.role or "").strip().upper()
        has_de = r.startswith("DE") or "_DE_" in f"_{r}_" or r.endswith("_DE")
        has_dv = r.startswith("DV") or "_DV_" in f"_{r}_" or r.endswith("_DV")
        if has_de and has_dv:
            return "SHARED"
        if has_de:
            return "DE"
        if has_dv:
            return "DV"
        return "SHARED"

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode.value,
            "role": self.role,
            "authorization": self.authorization.value,
            "autonomy_level": self.autonomy_level.value,
        }


def load_ux_policy_from_dict(doc: dict) -> UXPolicy:
    return UXPolicy(
        mode=doc.get("mode", DEFAULT_UX_MODE.value),
        role=doc.get("role", "DV"),
        authorization=doc.get("authorization"),
        autonomy_level=doc.get("autonomy_level"),
    )


# ---------------------------------------------------------------------------
# Persistence -- a single small file distinct from lifecycle/state/control.
# Same atomic tmpfile + replace convention as config.save_config()/
# dashboard_auth.issue_session_token().
# ---------------------------------------------------------------------------

UX_POLICY_FILENAME = "ux_policy.json"


def ux_policy_path(project_root: Path) -> Path:
    return Path(project_root) / ".dv-harness" / UX_POLICY_FILENAME


def save_ux_policy(project_root: Path, policy: UXPolicy) -> None:
    p = ux_policy_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="ux_policy.", suffix=".json", dir=str(p.parent))
    import os
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(policy.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_ux_policy(project_root: Path) -> UXPolicy:
    p = ux_policy_path(project_root)
    if not p.exists():
        return UXPolicy(mode=DEFAULT_UX_MODE)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UXPolicy(mode=DEFAULT_UX_MODE)
    if not isinstance(doc, dict):
        return UXPolicy(mode=DEFAULT_UX_MODE)
    return load_ux_policy_from_dict(doc)


def switch_mode(policy: UXPolicy, new_mode: "UXMode | str") -> UXPolicy:
    """Section 10: switch UX mode without losing anything else, and without
    EXPERT_MODE silently escalating authorization -- `authorization` is
    carried over unchanged, `autonomy_level` is re-derived for the new mode
    only if the caller never explicitly overrode it (tracked simply by
    always re-deriving here; an explicit override the caller wants kept
    across a mode switch should be re-applied by the caller after this
    call, an intentional, visible two-step rather than a hidden merge)."""
    resolved = resolve_ux_mode(new_mode)
    return UXPolicy(mode=resolved, role=policy.role, authorization=policy.authorization)


# ---------------------------------------------------------------------------
# G1-G5 Human Gates (DE/DV Role-Based HITL roadmap, Section 6) -- the first
# REAL, callable implementation of the gate table that roadmap named; the
# CSV under .work/phase3-dual-repo-consolidation/M4_5_DE_DV_ROLE_BASED_HITL/
# DE_DV_AUTHORITY_MATRIX.csv remains the governance record, this is the
# runtime data structure a caller actually dispatches against.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HumanGate:
    gate_id: str
    name: str
    owner_domain: str  # DESIGN | VERIFICATION | SHARED


HUMAN_GATES: tuple = (
    HumanGate("G1", "Design Intent / Spec Ambiguity", "DESIGN"),
    HumanGate("G2", "Verification Strategy", "VERIFICATION"),
    HumanGate("G3", "RTL Functional Change", "DESIGN"),
    HumanGate("G4", "Coverage / Waiver", "VERIFICATION"),
    HumanGate("G5", "Final Readiness / Signoff", "SHARED"),
)

_GATE_BY_DOMAIN = {}
for _g in HUMAN_GATES:
    _GATE_BY_DOMAIN.setdefault(_g.owner_domain, _g)


def gate_for_domain(domain: str) -> HumanGate:
    """The first-registered gate for a given authority domain -- a caller
    that needs a specific named gate (G1 vs G3, both DESIGN) should name it
    directly; this is the sane default when only the domain is known."""
    try:
        return _GATE_BY_DOMAIN[domain]
    except KeyError:
        raise UXPolicyError("UNKNOWN_AUTHORITY_DOMAIN", {
            "domain": domain, "known_domains": sorted(_GATE_BY_DOMAIN)})


# ---------------------------------------------------------------------------
# Section 7: dynamic, multi-factor action disposition
# ---------------------------------------------------------------------------

class ActionDisposition(str, Enum):
    AUTO = "AUTO"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    HUMAN_GATE = "HUMAN_GATE"
    BLOCKED = "BLOCKED"


_LEVELS = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "NONE": -1}


@dataclass(frozen=True)
class ActionContext:
    """The named factors Section 7 lists, plus which authority domain this
    action belongs to and (optionally) the minimum Authorization it needs --
    the two pieces of information no UX-mode/risk formula alone can supply,
    since they describe the ACTION, not the interaction style around it."""
    name: str
    risk: str                 # LOW | MEDIUM | HIGH
    evidence_quality: str     # LOW | MEDIUM | HIGH
    confidence: str           # LOW | MEDIUM | HIGH
    impact: str               # LOW | MEDIUM | HIGH
    reversible: bool
    signoff_impact: str       # NONE | LOW | MEDIUM | HIGH
    authority_domain: str     # DESIGN | VERIFICATION | SHARED
    required_authorization: Optional[Authorization] = None


@dataclass(frozen=True)
class DispositionResult:
    disposition: ActionDisposition
    reason: str
    gate_owner_domain: Optional[str] = None


def compute_action_disposition(policy: UXPolicy, *, action: ActionContext) -> DispositionResult:
    """Explicit, checkable decision table -- never a black-box score.
    Order matters: authorization and signoff-impact checks run FIRST,
    because Section 5's "mode is not equivalent to authorization" rule
    must hold regardless of how permissive the UX mode's autonomy ceiling
    is (this is what makes `test_expert_mode_does_not_bypass_authorization`
    pass even under EXPERT/AGGRESSIVE)."""
    # 1. Authorization floor -- an action's own required tier is never
    #    satisfied by UX mode or autonomy ceiling, only by the caller's
    #    real Authorization.
    if action.required_authorization is not None:
        if AUTHORIZATION_RANK[policy.authorization] < AUTHORIZATION_RANK[action.required_authorization]:
            return DispositionResult(
                ActionDisposition.HUMAN_GATE,
                f"requires {action.required_authorization.value} authorization, "
                f"caller has {policy.authorization.value}",
                gate_owner_domain=action.authority_domain,
            )

    # 2. A material signoff impact always routes to the owning domain's gate.
    if _LEVELS.get(action.signoff_impact, -1) >= _LEVELS["MEDIUM"]:
        return DispositionResult(
            ActionDisposition.HUMAN_GATE,
            f"signoff_impact={action.signoff_impact}",
            gate_owner_domain=action.authority_domain,
        )

    # 3. High impact + irreversible always routes to the owning domain's gate.
    if _LEVELS.get(action.impact, -1) >= _LEVELS["HIGH"] and not action.reversible:
        return DispositionResult(
            ActionDisposition.HUMAN_GATE,
            "impact=HIGH and not reversible",
            gate_owner_domain=action.authority_domain,
        )
    if _LEVELS.get(action.impact, -1) >= _LEVELS["HIGH"]:
        return DispositionResult(
            ActionDisposition.HUMAN_GATE,
            "impact=HIGH",
            gate_owner_domain=action.authority_domain,
        )

    # 4. Weak evidence or low confidence never auto-executes, in any mode.
    if action.evidence_quality == "LOW" or action.confidence == "LOW":
        return DispositionResult(
            ActionDisposition.REVIEW_REQUIRED,
            f"evidence_quality={action.evidence_quality}, confidence={action.confidence}",
        )

    # 5. High risk needs review even when otherwise reversible/low-impact.
    if action.risk == "HIGH":
        return DispositionResult(ActionDisposition.REVIEW_REQUIRED, "risk=HIGH")

    # 6. The UX mode's autonomy ceiling gates AUTO -- GUIDED never grants
    #    bare AUTO to anything above the most trivial (LOW risk + LOW/NONE
    #    impact) action, matching the mentor-style "explain, don't just do".
    if policy.autonomy_level == AutonomyLevel.CONSERVATIVE:
        if action.risk == "LOW" and _LEVELS.get(action.impact, -1) <= _LEVELS["LOW"] and action.reversible:
            return DispositionResult(ActionDisposition.AUTO, "GUIDED ceiling permits trivial reversible action")
        return DispositionResult(ActionDisposition.REVIEW_REQUIRED, "GUIDED autonomy ceiling")

    # 7. STANDARD/AGGRESSIVE: low risk + reversible auto-executes.
    if action.risk == "LOW" and action.reversible:
        return DispositionResult(ActionDisposition.AUTO, "low risk, reversible, within autonomy ceiling")

    return DispositionResult(ActionDisposition.REVIEW_REQUIRED, "default: no AUTO rule matched")


# ---------------------------------------------------------------------------
# I_DONT_KNOW evidence-retrieval-then-escalation (Section 2)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IDontKnowResult:
    resolved: bool
    escalated: bool
    answer: Optional[str] = None
    sources_checked: tuple = ()
    escalation: Optional[HumanGate] = None


def resolve_i_dont_know(
    question: str,
    *,
    evidence_sources: Sequence[Callable[[str], Optional[str]]] = (),
    authority_domain: str = "SHARED",
) -> IDontKnowResult:
    """Walk `evidence_sources` in the caller-supplied order (Knowledge Brain
    first, then spec/RTL/VIP docs, then prior KC -- whatever the caller
    wires in, per this module's own docstring). The first source to return a
    non-None answer resolves the question; if every source returns None,
    escalate to the named authority domain's human gate. `I_DONT_KNOW` is
    never a failure -- `IDontKnowResult` has no error/failure field at all,
    only `resolved`/`escalated`."""
    checked: List[str] = []
    for source in evidence_sources:
        checked.append(getattr(source, "__name__", repr(source)))
        answer = source(question)
        if answer is not None:
            return IDontKnowResult(resolved=True, escalated=False, answer=answer,
                                    sources_checked=tuple(checked))
    gate = gate_for_domain(authority_domain)
    return IDontKnowResult(resolved=False, escalated=True, answer=None,
                            sources_checked=tuple(checked), escalation=gate)


# ---------------------------------------------------------------------------
# CLI status banner (Section 9's own exact example shape)
# ---------------------------------------------------------------------------

def render_status_banner(policy: UXPolicy, *, level: str = "", protocol: str = "") -> str:
    lines = ["L5DGVA"]
    if level:
        lines.append(f"Level       : {level}")
    if protocol:
        lines.append(f"Protocol    : {protocol}")
    lines.append(f"UX Mode     : {policy.mode.value}")
    lines.append(f"Role        : {policy.role}")
    lines.append(f"Authorization: {policy.authorization.value}")
    return "\n".join(lines)
