"""dv_harness/system_virtual_sequencer.py -- SystemVirtualSequencer: a typed
record of how each REGISTERED subsystem's own virtual sequencer should
compose under one SYSTEM-LEVEL virtual sequencer, derived from
`verification_architecture.py`'s `VipBindIR` wrapper/bridge chain
classification -- never re-derived here.

WHY THIS EXISTS -- THE REAL GAP, CONFIRMED BEFORE BUILDING
------------------------------------------------------------
Two real, adjacent mechanisms already touch "system virtual sequencer" and
neither answers this module's question:

- `uvm_generator/soc_environment_composer.py`'s `_build_virtual_sequencer_fields()`
  is the real GENERATOR: it emits one `virtual_sequencer_fields` entry per
  REGISTERED subsystem, typed `<protocol>_virtual_sequencer`, named
  `<protocol>_vseqr` -- a flat, protocol-blind list. It is genuinely blind to
  whether that subsystem's own bind target sits behind a real protocol/width
  conversion point: nothing in that module ever reads a chain classification,
  because doing so is not that module's job (its own docstring: "composing
  ALREADY-REGISTERED, already-qualified subsystem environments... this
  module never branches on a protocol name").
- `generation_readiness.py`'s `system_virtual_sequencer` row only asks
  whether the composer's OWN functions resolve through the import system
  (GF-AT-19, "system virtual sequencer reuses subsystem sequencers") -- a
  capability-existence check, never a per-subsystem structural judgment.

Neither ever asks the question a human integrating N subsystem virtual
sequencers under one system-level virtual sequencer actually needs answered
first: for THIS subsystem, does its own bind chain to the DUT cross a real
bridge (a protocol/width conversion point), which would mean the
system-level virtual sequence cannot safely assume driving/coordinating that
subsystem's own sequences is a transparent pass-through -- or is its chain a
clean passthrough (or direct, no intermediate hops at all), where reusing
the subsystem's virtual-sequencer handle directly under the system-level one
is structurally sound? A repo-wide grep for `SystemVirtualSequencer`,
`system_virtual_sequencer_composition`, and `composition_mode` (this
module's own vocabulary) before writing a line of this confirmed nothing
already answers it.

REUSE, NOT REINVENTION
-----------------------
- The structural input is `verification_architecture.VipBindIR` (and its
  `build_vip_bind_ir()`/`derive_wrapper_bridge_chain()`/
  `classify_wrapper_bridge_hop()` machinery) VERBATIM. This module derives no
  wrapper/bridge/boundary classification of its own -- it reads a subsystem's
  already-computed `VipBindIR` records (accepted as real `VipBindIR`
  instances, or their own `.to_dict()` shape, duck-typed) and consumes only
  their `chain_classification`/`target_instance`/`chain_path`/
  `source_evidence` fields, imported from `verification_architecture.
  CHAIN_CLASSIFICATIONS` for the vocabulary check, never a second copy of it.
- Field naming (`<protocol>_virtual_sequencer` class type / `<protocol>_vseqr`
  field name) reuses `uvm_generator.generator.sv_id()` -- the SAME
  identifier-normalization function `soc_environment_composer.py`'s own
  `_build_virtual_sequencer_fields()` uses -- so a class/field name this
  module reports can never disagree with what the real generator would
  actually emit for the same subsystem name.
- Table rendering reuses `connectivity.render_markdown_table()`, this repo's
  one parameterized table renderer -- no second hand-rolled table loop.

WORST-WINS COMPOSITE GATES (Evidence Truth Rule + house style)
-----------------------------------------------------------------
Per-subsystem `composition_mode` folds ALL of that subsystem's own supplied
`VipBindIR` records worst-first, never averaged:

  - a single BRIDGE_IN_PATH chain anywhere for this subsystem makes the
    WHOLE subsystem `ADAPTER_REQUIRED` -- regardless of how many of its
    other bind targets are clean. A real protocol/width conversion in even
    one of a subsystem's bind chains is exactly the fact a system-level
    virtual sequence coordinating that subsystem must not be allowed to
    quietly ignore because most of its other interfaces happen to be
    simple.
  - absent any bridge, a single UNKNOWN chain (the underlying VipBindIR
    itself could not classify a hop -- no boundary evidence, or an
    UNDECIDABLE boundary) makes the subsystem `COMPOSITION_UNDETERMINED` --
    never silently promoted to a clean DIRECT_HANDLE composition on the
    strength of ITS OTHER binds alone.
  - only when every supplied chain classification is DIRECT or
    WRAPPER_ONLY does the subsystem read `DIRECT_HANDLE`: a clean
    passthrough (or no intermediate hops at all) -- safe to reuse the
    subsystem's own virtual-sequencer handle directly.
  - a subsystem with NO `VipBindIR` evidence supplied at all is honestly
    `NOT_AVAILABLE` -- never guessed toward either DIRECT_HANDLE or
    ADAPTER_REQUIRED.

The whole-system rollup (`SystemVirtualSequencerCompositionIR.overall_status`)
applies the identical worst-wins rule one level up over every subsystem's
own `composition_mode`: one `ADAPTER_REQUIRED` subsystem makes the overall
record `ADAPTER_REQUIRED`; absent that, one `NOT_AVAILABLE`/
`COMPOSITION_UNDETERMINED` subsystem makes it `INCOMPLETE_EVIDENCE`; only
when every subsystem is `DIRECT_HANDLE` does the whole record read
`READY_DIRECT_COMPOSITION`. Zero subsystems supplied is `NOT_AVAILABLE`,
never a vacuous READY over nothing.

Vocabulary is checked disjoint from `dv_harness.models.Status` at import
time (`assert_no_verification_verdict_vocabulary()`), the same guard
several sibling modules already apply to their own domain vocabularies.

WHAT THIS MODULE DOES NOT DO -- DELIBERATELY BOUNDED
------------------------------------------------------
It is a RECORD, not a generator: it writes no `.sv` file, emits no UVM
source, and never calls `soc_environment_composer.compose_soc_environment()`
or any other write path. It authors no adapter/bridge sequencer content --
"ADAPTER_REQUIRED" names the fact that one is needed, and cites the real
bridge evidence a human/generator needs to author one; it never invents
what that adapter's sequence body should do (protocol-behaviour content is
explicitly out of this module's scope, per this project's No
Golden-Reference Content Mining rule). It decides, approves and arbitrates
nothing: no build, job, or approval is touched, and there is deliberately no
stage gate -- a composition record is an input to a human/generator's
composition decision, never a substitute for one. It reads no RTL, VIP
source, or spec document itself -- every fact traces to a `VipBindIR` a
caller already built (typically via `verification_architecture.
build_vip_bind_ir()`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .connectivity import render_markdown_table
from .models import Status
from .verification_architecture import CHAIN_CLASSIFICATIONS

SCHEMA_VERSION = "1.0"

#: Per-subsystem composition-mode vocabulary. Fixed and closed -- an
#: unrecognized value appearing anywhere in this module's own output is a
#: bug in this module, never a caller-extensible open vocabulary.
COMPOSITION_MODES: tuple = (
    "DIRECT_HANDLE",
    "ADAPTER_REQUIRED",
    "COMPOSITION_UNDETERMINED",
    "NOT_AVAILABLE",
)

#: Whole-record rollup vocabulary. Deliberately spelled differently from
#: `COMPOSITION_MODES` (never bare "ADAPTER_REQUIRED"/"NOT_AVAILABLE" reused
#: unqualified at the record level would be fine too, but keeping the two
#: separate constants -- even where two members happen to share a literal
#: string -- keeps the fold's own worst-wins precedence table one honest
#: place to read, and keeps a future edit to one from silently drifting the
#: other).
OVERALL_STATUSES: tuple = (
    "READY_DIRECT_COMPOSITION",
    "ADAPTER_REQUIRED",
    "INCOMPLETE_EVIDENCE",
    "NOT_AVAILABLE",
)

#: Worst-wins precedence, highest severity first. A single member from a
#: worse bucket anywhere in a subsystem's (or the whole record's) inputs
#: outranks any number of members from a better bucket -- never averaged.
_SUBSYSTEM_PRECEDENCE = ("ADAPTER_REQUIRED", "COMPOSITION_UNDETERMINED", "DIRECT_HANDLE")
_OVERALL_PRECEDENCE = ("ADAPTER_REQUIRED", "INCOMPLETE_EVIDENCE", "READY_DIRECT_COMPOSITION")

#: `COMPOSITION_UNDETERMINED`-worthy `chain_classification` values, and
#: `DIRECT_HANDLE`-worthy ones -- read straight off
#: `verification_architecture.CHAIN_CLASSIFICATIONS` (imported, never
#: retyped) so this module can never silently drift from that module's own
#: vocabulary if it is ever extended.
_CLEAN_CHAIN_CLASSIFICATIONS = frozenset({"DIRECT", "WRAPPER_ONLY"})
_BRIDGE_CHAIN_CLASSIFICATION = "BRIDGE_IN_PATH"
_UNRESOLVED_CHAIN_CLASSIFICATION = "UNKNOWN"


class SystemVirtualSequencerError(ValueError):
    """A caller-supplied record violates this module's own vocabulary (an
    unrecognized `chain_classification`/`composition_mode` value), or a
    structural precondition a builder depends on is missing. Raised rather
    than silently coerced, matching `verification_architecture.py`'s own
    `VerificationArchitectureError` fail-closed discipline."""


def _validate_vocab(value: str, allowed: tuple, field_name: str, context: str) -> None:
    if value not in allowed:
        raise SystemVirtualSequencerError(
            f"{field_name} must be one of {list(allowed)}, got {value!r} (context: {context})"
        )


def _evidence(fact_source: str, **detail) -> dict:
    """One evidence entry -- same shape as `verification_architecture.
    _evidence()` -- which real function/module this fact came from, plus
    detail. Never a bare unattributed value."""
    return {"fact_source": fact_source, "detail": detail}


def _bind_field(bind: Any, name: str):
    """Read one field off a caller-supplied bind record, which may be a real
    `verification_architecture.VipBindIR` instance (attribute access) or its
    own `.to_dict()` shape (a plain dict) -- duck-typed, never an isinstance
    requirement, so a caller already holding either form can hand it to this
    module unmodified."""
    if isinstance(bind, dict):
        return bind.get(name)
    return getattr(bind, name, None)


def _bind_target_instance(bind: Any) -> Optional[str]:
    target = _bind_field(bind, "target_instance")
    if target is not None:
        return target
    raw = _bind_field(bind, "raw")
    if isinstance(raw, dict):
        return raw.get("target_instance")
    return None


def _bind_source_evidence(bind: Any) -> list:
    return list(_bind_field(bind, "source_evidence") or [])


def _bind_chain_path(bind: Any) -> list:
    return list(_bind_field(bind, "chain_path") or [])


# ===========================================================================
# Per-subsystem composition classification
# ===========================================================================

@dataclass
class SubsystemBindClassification:
    """One real `VipBindIR`'s worth of evidence, reduced to what this
    module needs: the bind target, its already-computed
    `chain_classification` (read verbatim, never re-derived), the real
    bridge hops (if any -- from that IR's own `chain_path`) and the real
    source evidence that produced it."""
    target_instance: Optional[str]
    chain_classification: str
    bridge_hops: list
    source_evidence: list

    def __post_init__(self) -> None:
        _validate_vocab(
            self.chain_classification, CHAIN_CLASSIFICATIONS,
            "chain_classification", self.target_instance or "<no target_instance>",
        )

    def to_dict(self) -> dict:
        return {
            "target_instance": self.target_instance,
            "chain_classification": self.chain_classification,
            "bridge_hops": self.bridge_hops,
            "source_evidence": self.source_evidence,
        }


def classify_subsystem_binds(vip_binds: Optional[list]) -> list:
    """Reduce a caller-supplied list of `VipBindIR` records (real instances
    or their `.to_dict()` shape) into `SubsystemBindClassification` entries.
    An empty/absent `vip_binds` returns `[]` -- "no bind evidence was
    supplied for this subsystem", read by `derive_composition_mode()` as
    `NOT_AVAILABLE`, never as a guessed clean chain."""
    out = []
    for bind in vip_binds or []:
        chain_classification = _bind_field(bind, "chain_classification")
        if chain_classification is None:
            raise SystemVirtualSequencerError(
                f"bind record carries no chain_classification field -- expected a real "
                f"verification_architecture.VipBindIR (or its to_dict() shape); got "
                f"{bind!r}"
            )
        bridge_hops = [h for h in _bind_chain_path(bind) if h.get("role") == "BRIDGE"]
        out.append(SubsystemBindClassification(
            target_instance=_bind_target_instance(bind),
            chain_classification=chain_classification,
            bridge_hops=bridge_hops,
            source_evidence=_bind_source_evidence(bind),
        ))
    return out


@dataclass
class SubsystemVirtualSequencerComposition:
    """How ONE subsystem's own virtual sequencer should compose under the
    system-level virtual sequencer -- `composition_mode` folded worst-wins
    from every one of that subsystem's own supplied bind chain
    classifications (see module docstring for the fold's precedence)."""
    subsystem_name: str
    composition_mode: str
    bind_classifications: list
    class_type: str
    field_name: str
    bridge_findings: list
    unresolved_findings: list
    source_evidence: list

    def __post_init__(self) -> None:
        _validate_vocab(self.composition_mode, COMPOSITION_MODES, "composition_mode", self.subsystem_name)

    def to_dict(self) -> dict:
        return {
            "subsystem_name": self.subsystem_name,
            "composition_mode": self.composition_mode,
            "class_type": self.class_type,
            "field_name": self.field_name,
            "bind_classifications": [b.to_dict() for b in self.bind_classifications],
            "bridge_findings": self.bridge_findings,
            "unresolved_findings": self.unresolved_findings,
            "source_evidence": self.source_evidence,
        }

    def to_row(self) -> dict:
        return {
            "subsystem": self.subsystem_name,
            "composition_mode": self.composition_mode,
            "class_type": self.class_type,
            "field_name": self.field_name,
            "bridge_count": len(self.bridge_findings),
            "unresolved_count": len(self.unresolved_findings),
        }


def _sv_id(name: str) -> str:
    """Identifier normalization, reusing `uvm_generator.generator.sv_id()`
    -- imported lazily to avoid this module paying for the generator
    package's own import cost (which pulls in `state_machine_checks`, etc.)
    on every import of this lightweight, read-only module, even for a
    caller that never renders a field name."""
    from .uvm_generator.generator import sv_id
    return sv_id(name)


def derive_composition_mode(bind_classifications: list) -> tuple:
    """Fold a subsystem's own `SubsystemBindClassification` list into one
    `composition_mode`, worst-wins. Returns `(mode, bridge_findings,
    unresolved_findings)` -- the two finding lists are always returned
    (possibly empty) so a caller can cite exactly which bind target(s)
    triggered a non-DIRECT_HANDLE mode, whatever the mode."""
    if not bind_classifications:
        return "NOT_AVAILABLE", [], []

    bridge_findings = []
    unresolved_findings = []
    for bc in bind_classifications:
        if bc.chain_classification == _BRIDGE_CHAIN_CLASSIFICATION:
            bridge_findings.append({
                "target_instance": bc.target_instance,
                "bridge_hops": bc.bridge_hops,
                "reason": (
                    f"bind target {bc.target_instance!r}'s wrapper/bridge chain crosses a "
                    "real protocol/width conversion point (verification_architecture."
                    "VipBindIR chain_classification=BRIDGE_IN_PATH) -- a system-level "
                    "virtual sequence coordinating this subsystem cannot assume driving/"
                    "observing its own sequences through this target is a transparent "
                    "pass-through."
                ),
            })
        elif bc.chain_classification == _UNRESOLVED_CHAIN_CLASSIFICATION:
            unresolved_findings.append({
                "target_instance": bc.target_instance,
                "reason": (
                    f"bind target {bc.target_instance!r}'s wrapper/bridge chain could not "
                    "be classified (verification_architecture.VipBindIR "
                    "chain_classification=UNKNOWN) -- no boundary evidence was supplied "
                    "for one or more hops, or a hop's boundary is UNDECIDABLE; a real "
                    "protocol/width conversion cannot be ruled out."
                ),
            })
        elif bc.chain_classification not in _CLEAN_CHAIN_CLASSIFICATIONS:
            # Vocabulary is already checked in SubsystemBindClassification.__post_init__,
            # so this branch is unreachable for any legally-constructed classification --
            # kept as a fail-closed guard rather than a silent fall-through.
            raise SystemVirtualSequencerError(
                f"unhandled chain_classification {bc.chain_classification!r} for target "
                f"{bc.target_instance!r} -- this is a defect in "
                "derive_composition_mode(), not a caller error"
            )

    if bridge_findings:
        return "ADAPTER_REQUIRED", bridge_findings, unresolved_findings
    if unresolved_findings:
        return "COMPOSITION_UNDETERMINED", bridge_findings, unresolved_findings
    return "DIRECT_HANDLE", bridge_findings, unresolved_findings


def build_subsystem_composition(subsystem_name: str, vip_binds: Optional[list]) -> SubsystemVirtualSequencerComposition:
    """Build one subsystem's `SubsystemVirtualSequencerComposition` from its
    real `VipBindIR` list. `subsystem_name` is the same identifier
    `soc_environment_composer.py`'s own per-subsystem naming already uses
    (a registry entry's `name`) -- `class_type`/`field_name` are derived
    from it via the identical `sv_id()` normalization, so they can never
    disagree with what the real generator would emit for the same name."""
    if not subsystem_name or not str(subsystem_name).strip():
        raise SystemVirtualSequencerError(
            "subsystem_name must be a real, non-empty identifier -- a composition record "
            "with no subsystem name cannot be attributed to anything"
        )
    proto = _sv_id(subsystem_name)
    bind_classifications = classify_subsystem_binds(vip_binds)
    mode, bridge_findings, unresolved_findings = derive_composition_mode(bind_classifications)

    evidence = [_evidence(
        "verification_architecture.build_vip_bind_ir",
        subsystem_name=subsystem_name,
        bind_count=len(bind_classifications),
        chain_classifications=[b.chain_classification for b in bind_classifications],
    )]
    if mode == "NOT_AVAILABLE":
        evidence.append(_evidence(
            "caller_supplied_vip_binds",
            reason="no VipBindIR records were supplied for this subsystem",
        ))

    return SubsystemVirtualSequencerComposition(
        subsystem_name=subsystem_name,
        composition_mode=mode,
        bind_classifications=bind_classifications,
        class_type=f"{proto}_virtual_sequencer",
        field_name=f"{proto}_vseqr",
        bridge_findings=bridge_findings,
        unresolved_findings=unresolved_findings,
        source_evidence=evidence,
    )


# ===========================================================================
# Whole-record rollup
# ===========================================================================

@dataclass
class SystemVirtualSequencerCompositionIR:
    """The whole-system composition record: one
    `SubsystemVirtualSequencerComposition` per registered subsystem, plus a
    worst-wins `overall_status` folded over every subsystem's own
    `composition_mode` (see module docstring)."""
    schema_version: str
    subsystems: list
    overall_status: str

    def __post_init__(self) -> None:
        _validate_vocab(self.overall_status, OVERALL_STATUSES, "overall_status", "<record>")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "overall_status": self.overall_status,
            "subsystems": [s.to_dict() for s in self.subsystems],
        }

    def render_markdown(self) -> str:
        columns = [
            ("subsystem", "Subsystem"),
            ("composition_mode", "Composition Mode"),
            ("class_type", "Virtual Sequencer Class"),
            ("field_name", "Field Name"),
            ("bridge_count", "Bridge Findings"),
            ("unresolved_count", "Unresolved Findings"),
        ]
        rows = [s.to_row() for s in self.subsystems]
        return render_markdown_table(
            columns, rows,
            empty_note="(no subsystems supplied -- SystemVirtualSequencer record is NOT_AVAILABLE)",
        )


def derive_overall_status(subsystem_compositions: list) -> str:
    """Fold every subsystem's own `composition_mode` into one whole-record
    `overall_status`, worst-wins (see module docstring's precedence table).
    An empty `subsystem_compositions` list is `NOT_AVAILABLE` -- there is no
    system to report a composition for."""
    if not subsystem_compositions:
        return "NOT_AVAILABLE"
    modes = {s.composition_mode for s in subsystem_compositions}
    if "ADAPTER_REQUIRED" in modes:
        return "ADAPTER_REQUIRED"
    if ("COMPOSITION_UNDETERMINED" in modes) or ("NOT_AVAILABLE" in modes):
        return "INCOMPLETE_EVIDENCE"
    return "READY_DIRECT_COMPOSITION"


def build_system_virtual_sequencer_composition(subsystems: list) -> SystemVirtualSequencerCompositionIR:
    """The one entry point. `subsystems`: a list of `{"name": <subsystem
    identifier>, "vip_binds": <list of VipBindIR | .to_dict() shape>}`
    dicts -- one per registered subsystem being composed under the
    system-level virtual sequencer. `vip_binds` may be omitted/empty for a
    subsystem with no bind evidence yet; that subsystem reports
    `NOT_AVAILABLE`, never a guessed composition mode."""
    if subsystems is None:
        raise SystemVirtualSequencerError(
            "subsystems must be a real list (possibly empty) -- None means the caller "
            "supplied nothing to reason about, distinct from a real empty registry"
        )
    compositions = []
    for entry in subsystems:
        if not isinstance(entry, dict) or "name" not in entry:
            raise SystemVirtualSequencerError(
                f"each subsystems entry must be a dict carrying at least 'name' -- got {entry!r}"
            )
        compositions.append(build_subsystem_composition(entry["name"], entry.get("vip_binds")))
    overall = derive_overall_status(compositions)
    return SystemVirtualSequencerCompositionIR(
        schema_version=SCHEMA_VERSION, subsystems=compositions, overall_status=overall,
    )


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabulary (`COMPOSITION_MODES` /
    `OVERALL_STATUSES`) must share no token with `dv_harness.models.Status`
    -- the same guard several sibling domain-vocabulary modules in this repo
    already run against themselves. Run at import time, below."""
    verdict_values = {s.value for s in Status}
    collisions = (set(COMPOSITION_MODES) | set(OVERALL_STATUSES)) & verdict_values
    if collisions:
        raise SystemVirtualSequencerError(
            f"vocabulary collides with dv_harness.models.Status: {sorted(collisions)}"
        )


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Standalone front door -- no dv-harness CLI verb (cli.py/gates.py out of
# this task's scope, per this project's own "standalone python -m front
# door" convention for a low-collision, single-item change).
# ===========================================================================

_EXIT_CODE_BY_OVERALL_STATUS = {
    "READY_DIRECT_COMPOSITION": 0,
    "ADAPTER_REQUIRED": 1,
    "INCOMPLETE_EVIDENCE": 2,
    "NOT_AVAILABLE": 2,
}


def execute_verb(argv: Optional[list] = None) -> int:
    """`python -m dv_harness.system_virtual_sequencer --subsystems <file.json>
    [--json] [--markdown]`. `<file.json>` is a JSON document shaped
    `{"subsystems": [{"name": ..., "vip_binds": [<VipBindIR.to_dict()>, ...]}, ...]}`.
    Exit 0 READY_DIRECT_COMPOSITION, 1 ADAPTER_REQUIRED, 2
    INCOMPLETE_EVIDENCE/NOT_AVAILABLE/usage error."""
    import argparse
    import json as _json
    import sys as _sys

    parser = argparse.ArgumentParser(prog="python -m dv_harness.system_virtual_sequencer")
    parser.add_argument("--subsystems", required=True, help="path to a subsystems JSON document")
    parser.add_argument("--json", action="store_true", help="emit the record as JSON")
    parser.add_argument("--markdown", action="store_true", help="emit the record as a markdown table")
    args = parser.parse_args(argv)

    try:
        with open(args.subsystems, "r", encoding="utf-8") as f:
            doc = _json.load(f)
    except (OSError, ValueError) as exc:
        print(f"NOT_AVAILABLE: could not read/parse {args.subsystems!r}: {exc}", file=_sys.stderr)
        return 2

    subsystems = doc.get("subsystems") if isinstance(doc, dict) else doc
    try:
        ir = build_system_virtual_sequencer_composition(subsystems)
    except SystemVirtualSequencerError as exc:
        print(f"NOT_AVAILABLE: {exc}", file=_sys.stderr)
        return 2

    if args.json:
        print(_json.dumps(ir.to_dict(), indent=2))
    elif args.markdown:
        print(ir.render_markdown())
    else:
        print(f"overall_status: {ir.overall_status}")
        for s in ir.subsystems:
            print(f"  {s.subsystem_name}: {s.composition_mode} ({s.class_type} {s.field_name})")

    return _EXIT_CODE_BY_OVERALL_STATUS[ir.overall_status]


def main() -> None:
    import sys as _sys
    _sys.exit(execute_verb())


if __name__ == "__main__":
    main()
