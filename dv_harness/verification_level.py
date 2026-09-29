"""dv_harness/verification_level.py -- the three official L5 verification
levels (IP / SUBSYSTEM / SYSTEM_LEVEL) and the domain vocabulary that
decides what each one means for generation.

CAP-M5M6-VLEVEL-001, Prime Directive V2 production connectivity. Adapted
(not blind-copied) from Parent's real, tested
`D:\\DV\\Task\\DV_Agent_Harness_L5\\dv_harness\\verification_level.py`
(owner ruling D2, dated 2026-09-21) -- confirmed real and wired there
(`environment_mode_router.py`, `engine.py`, `intake_routing.py`, and
Parent's own "Standard Flow" intake modules all import it;
`test_verification_level.py`, 119 lines, 12 real tests, all independently
re-run in Parent's own tree before being trusted here).

ONE DELIBERATE DEPARTURE FROM PARENT (never silently propagated): Parent's
own `verification_level.py` also defines `ask_verification_level()`/
`resolve_verification_level()`, a bespoke resolve/ask mechanism built
directly on `question_queue.py`. Canonical does not carry those two
functions over -- canonical's own, richer OpenSpec Field Resolution engine
(`intake_field_resolution.py` + `clarification_service.py`, built this
session by `CAP-M6-CLARSVC-001`) already does exactly that job, for
`protocol`/`role` (`dv_harness/generation_field_controls.py`). Porting
Parent's own separate resolve/ask pair would create a second Field
Resolution engine for this one field alone -- exactly what
`ONE_CANONICAL_FIELD_RESOLUTION_ENGINE` forbids. `verification_level`
becomes a third `FieldControl` in `generation_field_controls.py` instead,
resolved through the SAME `clarification_service.resolve_or_ask()` every
other generation field already uses. This module keeps only the
resolution-engine-agnostic domain vocabulary: the enum, the semantics
table, the exact-spelling parser, and the (never-resolving)
recommendation heuristic -- all four are pure functions of no side effects,
safe to reuse verbatim regardless of which engine calls them.

Who decides. The level is a HUMAN decision (owner ruling D2, preserved).
`suggest_level()` returns a recommendation only -- it is never handed to
`resolve_field()` as an evidence producer (that would silently auto-resolve
a human decision from a bare protocol-count guess); a caller may cite it
in a question's own recommendation text, but resolution still requires the
same DECLARED-or-human-answer path every other required field already
requires (`intake_field_resolution.resolve_field()`'s own evidence-based
resolution, never a heuristic-based one for this field).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Optional


class VerificationLevel(str, Enum):
    IP = "IP"
    SUBSYSTEM = "SUBSYSTEM"
    SYSTEM_LEVEL = "SYSTEM_LEVEL"


@dataclass(frozen=True)
class LevelSemantics:
    intake_mode: str
    environment_mode: str
    topology_model: str
    min_subsystems: int
    description: str


LEVEL_SEMANTICS: Dict[VerificationLevel, LevelSemantics] = {
    VerificationLevel.IP: LevelSemantics(
        intake_mode="IP",
        environment_mode="IP_MODE",
        topology_model="single_dut_with_vip",
        min_subsystems=0,
        description="One IP/DUT with its VIP; no subsystem registry is involved."),
    VerificationLevel.SUBSYSTEM: LevelSemantics(
        intake_mode="SUBSYSTEM",
        environment_mode="SUBSYSTEM_MODE",
        topology_model="multi_ip_interconnect",
        min_subsystems=1,
        description="A subsystem: several IPs on an interconnect, one environment."),
    VerificationLevel.SYSTEM_LEVEL: LevelSemantics(
        intake_mode="SYSTEM_LEVEL",
        environment_mode="SYSTEM_LEVEL_MODE",
        topology_model="multi_subsystem_composition",
        min_subsystems=2,
        description="Two or more completed subsystem environments composed together."),
}

_SPELLINGS: Dict[str, VerificationLevel] = {
    "IP": VerificationLevel.IP, "IP_LEVEL": VerificationLevel.IP,
    "SUBSYSTEM": VerificationLevel.SUBSYSTEM,
    "SYSTEM_LEVEL": VerificationLevel.SYSTEM_LEVEL,
}


def parse_level(text: Any) -> Optional[VerificationLevel]:
    """Exact-spelling parse; anything else is None (never guessed)."""
    if isinstance(text, VerificationLevel):
        return text
    if not isinstance(text, str):
        return None
    key = text.strip().upper().replace("-", "_").replace(" ", "_")
    if key.endswith("_MODE"):
        key = key[: -len("_MODE")]
    return _SPELLINGS.get(key)


def suggest_level(protocols: Iterable[str]) -> Dict[str, Any]:
    """A recommendation only. One (or zero) protocol looks like a
    single-subsystem build (this project's own real precedent since before
    VerificationLevel existed: `environment_mode_policy.json`'s own
    SUBSYSTEM_MODE examples list -- PCIe, USB, Ethernet, ... -- are all
    ONE-protocol builds); two or more protocols look like a composition.
    Never a decision -- see `generation_field_controls.py`'s own
    `verification_level_field_control()`, which never wires this as an
    evidence producer for exactly that reason."""
    distinct = {str(p).strip().lower() for p in protocols if str(p).strip()}
    if len(distinct) >= 2:
        return {"suggested": VerificationLevel.SYSTEM_LEVEL,
                "reason": f"{len(distinct)} protocols named ({sorted(distinct)})"}
    return {"suggested": VerificationLevel.SUBSYSTEM,
            "reason": "zero or one protocol named"}
