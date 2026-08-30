"""dv_harness/qualification.py -- canonical qualification-status vocabulary.

BUG FIX (2026-08-28, plan-qualification-vocab design pass): this project had
at least 4 incompatible "qualification status" vocabularies describing the
same underlying concept (how proven/trustworthy is a generated verification
environment):
  A. .dv-harness/qualification/protocol_qualification_policy.json's 8-tier
     ladder (BUILDER_AVAILABLE .. PRODUCTION_QUALIFIED) -- the most complete,
     but previously unread by any code (its own JSON was pure unread prose).
  B. protocol_capability_registry.json's status string + separate
     production_qualified bool.
  C. system_level_composition_gate.py / system_level_validator.py /
     protocol_qualification_status_gate.py's narrower 3-value subset
     (SMOKE_QUALIFIED/REGRESSION_QUALIFIED/PRODUCTION_QUALIFIED) -- genuinely
     live and gate-enforced, kept as an intentional subset here, not merged
     away.
  D. protocol_qualification_ladder_gate.py's own 4-tier
     UNQUALIFIED..PRODUCTION_QUALIFIED (self-audit-only, NO_SOURCE_DATA today).

This module makes Vocab A real (Python constants, not just unread JSON) and
gives it a code-enforced mapping down to Vocab C's narrower subset, so a
canonical status can be checked for system-level-composition eligibility
without hand-rolling the comparison at every call site.
"""
from __future__ import annotations

from enum import Enum


class QualificationTier(str, Enum):
    BUILDER_AVAILABLE = "BUILDER_AVAILABLE"
    EVIDENCE_READY = "EVIDENCE_READY"
    ENV_GENERATED = "ENV_GENERATED"
    COMPILE_QUALIFIED = "COMPILE_QUALIFIED"
    SMOKE_QUALIFIED = "SMOKE_QUALIFIED"
    PROTOCOL_QUALIFIED = "PROTOCOL_QUALIFIED"
    REGRESSION_QUALIFIED = "REGRESSION_QUALIFIED"
    PRODUCTION_QUALIFIED = "PRODUCTION_QUALIFIED"


# Ordered lowest -> highest. Matches protocol_qualification_policy.json's own
# `labels` list exactly (see test_qualification.py's drift guard).
CANONICAL_LADDER: tuple = tuple(t.value for t in QualificationTier)

# Vocab C: the narrower subset used specifically for system-level composition
# gating (system_level_composition_gate.py / system_level_validator.py /
# protocol_qualification_status_gate.py). Intentionally a SUBSET, not the
# full 8-tier ladder -- SMOKE-level-and-below granularity does not matter for
# a cross-subsystem composition decision.
SYSTEM_LEVEL_STATES: tuple = ("SMOKE_QUALIFIED", "REGRESSION_QUALIFIED", "PRODUCTION_QUALIFIED")

# JUDGMENT CALL (flagged by plan-qualification-vocab, needs DV-lead sign-off
# if this project's semantics disagree): PROTOCOL_QUALIFIED sits between
# SMOKE_QUALIFIED and REGRESSION_QUALIFIED on the canonical ladder but has no
# distinct Vocab-C bucket of its own. It floor-collapses to SMOKE_QUALIFIED
# here -- never claim more system-level-composition readiness than proven,
# per CLAUDE.md's Evidence Truth Rule -- rather than rounding up to
# REGRESSION_QUALIFIED.
_FLOOR_MAP = {
    "SMOKE_QUALIFIED": "SMOKE_QUALIFIED",
    "PROTOCOL_QUALIFIED": "SMOKE_QUALIFIED",
    "REGRESSION_QUALIFIED": "REGRESSION_QUALIFIED",
    "PRODUCTION_QUALIFIED": "PRODUCTION_QUALIFIED",
}


def is_canonical(value) -> bool:
    return value in CANONICAL_LADDER


def tier_index(value: str) -> int:
    """Position on the canonical ladder (0 = BUILDER_AVAILABLE, 7 =
    PRODUCTION_QUALIFIED). Raises ValueError with a clear message if `value`
    is not one of the 8 canonical tokens."""
    try:
        return CANONICAL_LADDER.index(value)
    except ValueError:
        raise ValueError(
            f"{value!r} is not a canonical qualification tier; expected one of {CANONICAL_LADDER}"
        ) from None


def map_to_system_level_state(canonical_status: str) -> str:
    """Vocab A -> Vocab C. Raises ValueError if canonical_status is below
    SMOKE_QUALIFIED (BUILDER_AVAILABLE/EVIDENCE_READY/ENV_GENERATED/
    COMPILE_QUALIFIED have no system-level-composition-eligible
    representation -- there is nothing to floor them to)."""
    tier_index(canonical_status)  # validates canonical membership first
    mapped = _FLOOR_MAP.get(canonical_status)
    if mapped is None:
        raise ValueError(
            f"{canonical_status!r} is below SMOKE_QUALIFIED and has no system-level "
            f"composition state -- this subsystem is not yet eligible for system-level use"
        )
    return mapped


def validate_system_level_state(value) -> bool:
    return value in SYSTEM_LEVEL_STATES
