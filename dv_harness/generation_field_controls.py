"""dv_harness/generation_field_controls.py -- M6 Golden-Path Connectivity
Closure C1 (CAP-M6-C1-001): the minimal, schema-preserving adapter/projection
between the real production intake a caller already has at
`engine.DVHarness.start_lifecycle()` call time (its own pre-existing
`protocols` argument, and a project's own already-recorded lifecycle facts)
and `intake_field_resolution.py`'s existing `FieldControl`/`EvidenceProducer`
model.

WHY THIS MODULE EXISTS, and why it is not a second Field Resolution engine.
The Integration Prime Directive adoption audit found a real capability
island: `clarification_service.py` (`CAP-M6-CLARSVC-001`) is real, wired and
tested inside `start_lifecycle()`'s own dispatch, but no production caller
ever supplied it a real `FieldControl` -- `start_lifecycle()`'s own
`field_controls` parameter defaulted to `()` and nothing populated it. This
module supplies exactly ONE real, concrete field for the one piece of
production intake `start_lifecycle()` already receives but does not resolve:
which protocol/subsystem a verification-environment-generation request
targets (`create_environment.create_environment()`'s own `request["protocol"]`
key). It imports `FieldControl`/`EvidenceProducer`/`Candidate`/`SourceKind`/
`Confidence` from `intake_field_resolution.py` VERBATIM and defines zero new
field-value types -- it only builds one `FieldControl` and one evidence
producer function, in the exact shape that module's own `resolve_field()`
already understands.

WHY "protocol", not `level`/`protocols`-as-a-whole-fact. `CAP-M6-DISPATCH-001`
and this program's Constitution both explicitly leave `VerificationLevel`
(IP_MODE/SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE branching) unimplemented and out of
scope -- `environment_mode_router.py` is not touched by this module. This
module is narrower: it governs a single, already-real value
(`create_environment()`'s `request["protocol"]` / `_requested_subsystems()`
input) through Field Resolution/Clarification, which is a distinct,
non-overlapping concern from level-based mode selection. It does not decide
IP vs. SUBSYSTEM vs. SYSTEM_LEVEL; it only ensures a human is asked when
NEITHER the current call NOR any prior lifecycle fact says which
protocol/subsystem to generate for.

AUTO_DISCOVERY_FIRST. `protocol_evidence_producers()`'s one producer reads
`.dv-harness/lifecycle.json`'s own already-recorded `protocols` fact (via
`lifecycle.LifecycleStore`, read-only) -- a real, already-existing source,
never a new discovery mechanism. A project that already declared its
protocol on an earlier `start` call resolves silently on every later call;
only a project that has NEVER declared it, on ANY call, is asked.
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

#: The one field this module governs. Matches `create_environment()`'s own
#: `request["protocol"]` key (see `_requested_subsystems()` in
#: `dv_harness/uvm_generator/create_environment.py`) -- never a new name.
PROTOCOL_FIELD_ID = "protocol"


def protocol_field_control() -> FieldControl:
    """The one, fixed `FieldControl` this module ever builds. `domain="env"`
    -- choosing which protocol/subsystem a verification environment targets
    is a verification-environment decision (`VERIFICATION_AUTHORITY`), not a
    DUT-RTL fact or a VIP's own internal configuration."""
    return FieldControl(
        field_id=PROTOCOL_FIELD_ID,
        required=True,
        domain="env",
        notes="which protocol/subsystem verification-environment generation targets",
        downstream_consumers=("uvm_generator.create_environment.create_environment",),
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


def _lifecycle_protocol_candidate(root: Path) -> List[Candidate]:
    store = _lifecycle.LifecycleStore(root)
    if not store.exists():
        return []
    data = store.load()
    recorded = data.get("protocols")
    if not recorded:
        return []
    value = ",".join(sorted(str(p) for p in recorded)) if isinstance(recorded, (list, tuple)) \
        else str(recorded).strip()
    if not value:
        return []
    return [Candidate(
        value=value, kind=SourceKind.AUTO_DISCOVERED, source="lifecycle_facts",
        confidence=Confidence.HIGH,
        evidence_refs=(".dv-harness/lifecycle.json:protocols",),
    )]


def protocol_evidence_producers(root: Path) -> List[EvidenceProducer]:
    """One producer, step `existing_files` (the evidence ladder's first
    step) -- `.dv-harness/lifecycle.json` is exactly that: an existing file
    this project already wrote, never a fresh scan."""
    root = Path(root)

    def _fn(field_id: str, context: Dict[str, Any]) -> List[Candidate]:
        return _lifecycle_protocol_candidate(root)

    return [EvidenceProducer(step="existing_files", name="lifecycle_recorded_protocols", fn=_fn)]
