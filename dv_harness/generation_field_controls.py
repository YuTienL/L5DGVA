"""dv_harness/generation_field_controls.py -- M6 Golden-Path Connectivity
Closure C1 (`CAP-M6-C1-001`) + GAP-V2-002 remediation (`CAP-M6-GAPV2002-001`):
the minimal, schema-preserving adapter/projection between the real
production intake a caller already has at `engine.DVHarness.start_lifecycle()`
call time (its own `protocols`/`role` arguments, and a project's own
already-recorded lifecycle facts) and `intake_field_resolution.py`'s
existing `FieldControl`/`EvidenceProducer` model.

WHY THIS MODULE EXISTS, and why it is not a second Field Resolution engine.
The Integration Prime Directive adoption audit found a real capability
island: `clarification_service.py` (`CAP-M6-CLARSVC-001`) is real, wired and
tested inside `start_lifecycle()`'s own dispatch, but no production caller
ever supplied it a real `FieldControl`. This module supplies real, concrete
fields for the pieces of production intake `start_lifecycle()` already
receives (or a caller can supply) but did not resolve. It imports
`FieldControl`/`EvidenceProducer`/`Candidate`/`SourceKind`/`Confidence` from
`intake_field_resolution.py` VERBATIM and defines zero new field-value
types -- it only builds `FieldControl`s and evidence producer functions, in
the exact shape that module's own `resolve_field()` already understands.

THE FIELD SET, and how it was derived (GAP-V2-002 remediation). Not
assumed -- derived from all 11 `.claude/skills/PROTOCOL_BUILDERS/*/
SKILL.md`'s own "Discover Before Generate" sections plus a direct read of
every downstream generation consumer's own manifest-key usage
(`dv_harness/uvm_generator/generator.py`, `protocol_env_generator.py`,
`protocol_model_layer.py`, `create_environment.py`). Full classification
in `.work/phase3-dual-repo-consolidation/M6_PREFLIGHT/
GAP_V2_002_FIELD_CONTROL_DERIVATION.md`. Summary of the two fields this
module actually governs, and why the others investigated are NOT here:

  - `protocol` (`EXISTING_CANONICAL_FIELD`, built by `CAP-M6-C1-001`):
    `create_environment()`'s own `request["protocol"]` /
    `_requested_subsystems()` input.
  - `role` (`NEW_GENERIC_CANONICAL_FIELD`, added by GAP-V2-002
    remediation): a real, actually-consumed manifest key
    (`generator.py`'s own `m.get('role', 'UNKNOWN')`, reused unchanged by
    `ProtocolEnvGenerator`), and present under some name (host/device,
    RC/EP/Switch, TX/RX, source/sink, master/slave, ...) in EVERY ONE of
    the 11 skills' own "Discover Before Generate" list -- a genuinely
    generic slot even though its vocabulary is protocol-specific,
    following exactly the same "protocol" field's own precedent.
  - `mode`/`topology` (`PROTOCOL_SPECIFIC_EXTENSION`, not governed here):
    real per-skill discovery items, but NO generic flat key for either is
    ever read by any downstream generator -- the closest real structure
    (`protocol_model_layer.TOPOLOGY_KEY`, `"protocol_model_topology"`) is
    itself a protocol-specific nested dict (PCIe's own `lane_width`/
    `gen_speed`/... shape), optional, and used by only 5 of 11 protocols.
    Inventing one generic `FieldControl` for a value with no generic
    shape would be exactly the kind of second, competing field model this
    module's own module-docstring commitment forbids.
  - `phy_boundary` (`EXISTING_CANONICAL_FIELD`, real, but NOT consumed by
    this generation path): already has a real Canonical producer
    (`phy_boundary.py`, joined by `intake_state.py`'s own `dut_boundary`
    category) -- but neither `create_environment()` nor
    `ProtocolEnvGenerator` reads a `phy_boundary`/`dut_boundary` key at
    all; the real consumer is the SEPARATE bind-generation tool
    (`bind_mechanism_generator.py`/`tools/generate_bind_mechanism.py`).
    Wiring it into THIS module would misrepresent which tool actually
    uses it.
  - `verification_level` (`CAP-M5M6-VLEVEL-001`, now a THIRD real
    `FieldControl` -- see `verification_level_field_control()` below):
    `lifecycle._FACT_KEYS` already reserved the fact key; this task wires
    it through the SAME `resolve_or_ask()` engine `protocol`/`role`
    already use, adapted (not blind-copied) from Parent's own real,
    tested `dv_harness/verification_level.py` (owner ruling D2) -- see
    that module's own docstring for the one deliberate departure (Parent's
    bespoke `ask_verification_level()`/`resolve_verification_level()` are
    NOT ported; this field goes through the one Canonical engine instead).
    `environment_mode_router.resolve_environment_mode()` now accepts the
    resolved value directly (`_resolve_with_level()`), adding the one real
    mode (`IP_MODE`) the subsystem-count-only decision could never produce.

WHY level-based mode selection is now wired, and why it still does not
redesign anything. `environment_mode_router.py` gained one new, optional,
backward-compatible evidence key (`verification_level`) -- absent, the
router is byte-identical to before this task; present, it selects the mode
directly rather than only from subsystem count. Governing `protocol`/
`role`/`verification_level` through Field Resolution/Clarification is
still the same non-overlapping concern it always was: it only ensures a
human is asked when neither the current call nor any prior lifecycle fact
says which protocol/role/level a generation request targets -- the router
extension and this module's own third `FieldControl` are additive, not a
rewrite of either `environment_mode_router.py`'s existing tested branches
or `intake_field_resolution.py`'s own resolution algorithm.

AUTO_DISCOVERY_FIRST. Both fields' producers read
`.dv-harness/lifecycle.json`'s own already-recorded facts (via
`lifecycle.LifecycleStore`, read-only) -- a real, already-existing source,
never a new discovery mechanism. A project that already declared a value
on an earlier `start` call resolves silently on every later call; only a
project that has never declared it, on any call, is asked.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import lifecycle as _lifecycle
from .intake_field_resolution import (
    Candidate,
    Confidence,
    EvidenceProducer,
    FieldControl,
    SourceKind,
    ValidationState,
)
from .verification_level import parse_level as _parse_verification_level

#: Matches `create_environment()`'s own `request["protocol"]` key (see
#: `_requested_subsystems()` in `dv_harness/uvm_generator/
#: create_environment.py`) -- never a new name.
PROTOCOL_FIELD_ID = "protocol"

#: Matches `generator.py`'s own `m.get('role', 'UNKNOWN')` manifest key,
#: reused unchanged by `ProtocolEnvGenerator.generate()`.
ROLE_FIELD_ID = "role"

#: Matches `lifecycle._FACT_KEYS`'s own pre-existing `verification_level`
#: key and `environment_mode_router.py`'s new `verification_level`
#: evidence key -- never a new name.
VERIFICATION_LEVEL_FIELD_ID = "verification_level"


def protocol_field_control() -> FieldControl:
    """`domain="env"` -- choosing which protocol/subsystem a verification
    environment targets is a verification-environment decision
    (`VERIFICATION_AUTHORITY`), not a DUT-RTL fact or a VIP's own internal
    configuration."""
    return FieldControl(
        field_id=PROTOCOL_FIELD_ID,
        required=True,
        domain="env",
        notes="which protocol/subsystem verification-environment generation targets",
        downstream_consumers=("uvm_generator.create_environment.create_environment",),
    )


def role_field_control() -> FieldControl:
    """`domain="env"`, same authority reasoning as `protocol_field_control()`
    -- which role the DUT plays in the protocol (host/device, RC/EP, TX/RX,
    ...) is a verification-environment decision, not a DUT-RTL fact by
    itself (the RTL may support either role; the environment being built
    targets one)."""
    return FieldControl(
        field_id=ROLE_FIELD_ID,
        required=True,
        domain="env",
        notes="which role the DUT plays in the protocol (host/device, RC/EP, TX/RX, "
              "master/slave, source/sink, ... -- vocabulary is protocol-specific, "
              "the slot is generic)",
        downstream_consumers=("uvm_generator.generator.m.get('role')",),
    )


def verification_level_field_control() -> FieldControl:
    """`domain="env"` -- which verification level a generation request
    targets is a verification-environment decision, and (owner ruling D2,
    preserved from Parent) a HUMAN decision specifically -- never inferred
    from a heuristic (see `verification_level.suggest_level()`'s own
    docstring: a recommendation only, never wired as an evidence producer
    below for exactly that reason)."""
    return FieldControl(
        field_id=VERIFICATION_LEVEL_FIELD_ID,
        required=True,
        domain="env",
        notes="which verification level (IP / SUBSYSTEM / SYSTEM_LEVEL) this "
              "generation request targets -- see dv_harness/verification_level.py",
        downstream_consumers=("environment_mode_router.resolve_environment_mode",),
    )


def _verification_level_validator(field_id: str, cand: Candidate):
    """Schema-level validation stricter than `default_validator()`'s bare
    non-blank check: a `verification_level` candidate must be one of the
    3 real, exact spellings `verification_level.parse_level()` accepts,
    never merely non-blank -- otherwise a typo ('IPS', 'Subsytem') would
    silently 'resolve' at Field Resolution only to fail later, more
    confusingly, at the router (`INVALID_VERIFICATION_LEVEL`)."""
    value = str(cand.value).strip()
    if not value:
        return ValidationState.INVALID, "blank value"
    if _parse_verification_level(value) is None:
        return ValidationState.INVALID, f"{value!r} is not one of IP / SUBSYSTEM / SYSTEM_LEVEL"
    return ValidationState.VALID, "valid verification-level spelling"


def declared_protocol_value(protocols: Sequence[str]) -> Optional[str]:
    """Projects a caller's own already-parsed `protocols` sequence (e.g.
    `cli.py`'s `start` command's `--protocols` flag, already split into a
    tuple before this module ever sees it) into the single string value
    `resolve_field()`'s `declared=` parameter expects. Multiple declared
    protocols join into one comma-joined value -- `create_environment()`'s
    own request assembly (a separate, later step; this module does not
    perform it) is free to re-split it, since a request is still one
    dict either way."""
    cleaned = [str(p).strip() for p in protocols if str(p).strip()]
    if not cleaned:
        return None
    return ",".join(sorted(cleaned))


def declared_role_value(role: Optional[str]) -> Optional[str]:
    """Projects a caller's own already-parsed `role` string (e.g. `cli.py`'s
    `--role` flag) into `resolve_field()`'s `declared=` parameter shape --
    a single value, never a list (a generation request targets one role)."""
    if role is None:
        return None
    cleaned = str(role).strip()
    return cleaned or None


def declared_verification_level_value(level: Optional[str]) -> Optional[str]:
    """Projects a caller's own already-parsed `level` string (`cli.py`'s
    pre-existing `--level` flag, `CAP-M6-DISPATCH-001`) into
    `resolve_field()`'s `declared=` parameter shape. Deliberately does NOT
    normalize/parse the spelling here (that is `_verification_level_
    validator()`'s own job, at schema-validation time, so an invalid
    spelling is reported as a real `ValidationState.INVALID` candidate,
    never silently dropped before it can be)."""
    if level is None:
        return None
    cleaned = str(level).strip()
    return cleaned or None


def _lifecycle_fact_candidate(root: Path, fact_key: str) -> List[Candidate]:
    store = _lifecycle.LifecycleStore(root)
    if not store.exists():
        return []
    data = store.load()
    recorded = data.get(fact_key)
    if not recorded:
        return []
    value = ",".join(sorted(str(p) for p in recorded)) if isinstance(recorded, (list, tuple)) \
        else str(recorded).strip()
    if not value:
        return []
    return [Candidate(
        value=value, kind=SourceKind.AUTO_DISCOVERED, source="lifecycle_facts",
        confidence=Confidence.HIGH,
        evidence_refs=(f".dv-harness/lifecycle.json:{fact_key}",),
    )]


def protocol_evidence_producers(root: Path) -> List[EvidenceProducer]:
    """One producer, step `existing_files` (the evidence ladder's first
    step) -- `.dv-harness/lifecycle.json` is exactly that: an existing file
    this project already wrote, never a fresh scan."""
    root = Path(root)

    def _fn(field_id: str, context: Dict[str, Any]) -> List[Candidate]:
        return _lifecycle_fact_candidate(root, "protocols")

    return [EvidenceProducer(step="existing_files", name="lifecycle_recorded_protocols", fn=_fn)]


def role_evidence_producers(root: Path) -> List[EvidenceProducer]:
    """Same shape as `protocol_evidence_producers()` -- reads
    `.dv-harness/lifecycle.json`'s own already-recorded `role` fact."""
    root = Path(root)

    def _fn(field_id: str, context: Dict[str, Any]) -> List[Candidate]:
        return _lifecycle_fact_candidate(root, "role")

    return [EvidenceProducer(step="existing_files", name="lifecycle_recorded_role", fn=_fn)]


def verification_level_evidence_producers(root: Path) -> List[EvidenceProducer]:
    """Same shape as `protocol_evidence_producers()` -- reads
    `.dv-harness/lifecycle.json`'s own already-recorded `verification_level`
    fact (the SAME fact key `CAP-M6-DISPATCH-001`'s own `--level` flag
    already writes there, `lifecycle._FACT_KEYS`). Deliberately does NOT
    also wire `verification_level.suggest_level()`'s own protocol-count
    heuristic as a producer here -- that would let the harness silently
    AUTO_DISCOVER (and therefore auto-resolve, for a field with no other
    candidate) a HUMAN decision from a bare guess, exactly what owner
    ruling D2 forbids. A recommendation is not evidence."""
    root = Path(root)

    def _fn(field_id: str, context: Dict[str, Any]) -> List[Candidate]:
        return _lifecycle_fact_candidate(root, "verification_level")

    return [EvidenceProducer(step="existing_files", name="lifecycle_recorded_verification_level", fn=_fn)]
