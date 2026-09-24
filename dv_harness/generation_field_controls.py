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
  - `verification_level` (`EXISTING_CANONICAL_FIELD`, deliberately NOT
    built here): `lifecycle._FACT_KEYS` already reserves it; resolving it
    through Field Resolution is `CAP-M5M6-VLEVEL-001`'s own explicitly
    separate, not-yet-authorized scope -- out of bounds for this module
    by the same standing rule `CAP-M6-DISPATCH-001`/`CAP-M6-C1-001` both
    already respected.

WHY NOT level-based mode selection. `environment_mode_router.py` is not
touched by this module. Governing `protocol`/`role` through Field
Resolution/Clarification is a distinct, non-overlapping concern from
IP/SUBSYSTEM/SYSTEM_LEVEL mode branching -- it only ensures a human is
asked when neither the current call nor any prior lifecycle fact says
which protocol/role a generation request targets.

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
)

#: Matches `create_environment()`'s own `request["protocol"]` key (see
#: `_requested_subsystems()` in `dv_harness/uvm_generator/
#: create_environment.py`) -- never a new name.
PROTOCOL_FIELD_ID = "protocol"

#: Matches `generator.py`'s own `m.get('role', 'UNKNOWN')` manifest key,
#: reused unchanged by `ProtocolEnvGenerator.generate()`.
ROLE_FIELD_ID = "role"


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
