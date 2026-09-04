"""dv_harness/uvm_generator/protocol_model_layer.py -- the missing wire
between the five REAL protocol-model generators in this package and the one
official CREATE ENVIRONMENT entry point (2026-09-04, AI-mechanism re-audit
gap #13 "Generic multi-protocol DV Harness scope").

What was actually wrong (re-verified in the code before this module was
written, not restated from a report):

  - `pcie_ltssm_generator.py`, `canfd_arbitration_generator.py`,
    `mipi_dphy_generator.py`, `emmc_cmdq_generator.py` and
    `amba_fabric_generator.py` are real, unit-tested protocol models, and
    `protocol_capability.py` reports them as this harness's per-protocol
    capability on a production surface (`dashboard.py`'s Protocols card).
  - But `grep -rn "<model>_generator" --include=*.py .` found their ONLY
    non-test callers to be the five standalone `tools/generate_*.py`
    scripts. `create_environment.py` -- the entry point
    `tools/generate_protocol_uvm_environment.py` calls, which every
    `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` invokes -- imported none of
    them. A manifest carrying `protocol: "PCIe"` therefore produced exactly
    the same flat protocol-agnostic skeleton a manifest carrying
    `protocol: "Ethernet"` produced, and the LTSSM model reached the
    generated environment only if an agent happened to know to run a second,
    separate tool by hand.

That is the PARTIALLY_WIRED shape this audit looks for: the unit tests pass
while the production path never calls the code. This module closes it by
LAYERING each protocol's own model onto the generic skeleton inside the
existing entry point, reusing what already exists rather than adding a
parallel generator:

  - WHICH module implements a protocol comes from
    `protocol_capability.PROTOCOL_CAPABILITIES` (already the single
    code-derived answer to that question, already drift-checked by
    `--check`), never from a second table here.
  - HOW it is invoked is that entry's own `generator_class`, resolved through
    the import system by `protocol_capability.resolve_generator_class()`.
  - WHAT it is invoked with is the manifest's `protocol_model_topology` --
    real per-DUT facts (PCIe lane_width/gen_speed/role, D-PHY
    role/lane_count, CAN-FD id_format/node_ids, AMBA masters/slaves/
    addr_width). Each generator's own typed validator judges it; nothing is
    re-validated or defaulted here.

Three deliberate properties:

1. **A protocol with no model, and a manifest with no topology, still
   generate byte-identical SV.** USB -- the only DUT_PROVEN protocol -- has
   no protocol-model module by design (its behaviour lives in the main
   generator path), so it takes the NO_PROTOCOL_MODEL branch and nothing
   about its output changes. The only difference in any generated
   environment is a new `protocol_model` block inside
   environment_manifest.json, which is a RECORD of what was layered and what
   was not.

2. **A missing topology is recorded, never guessed and never silent.**
   lane_width/gen_speed/role are facts about a specific DUT; inventing them
   to make a layer fire would be the fabrication CLAUDE.md's Evidence Truth
   Rule forbids. So a PCIe manifest with no `protocol_model_topology` gets
   status PROTOCOL_MODEL_TOPOLOGY_NOT_SUPPLIED written into its own
   environment_manifest.json, naming the module that WOULD have run. The
   environment then cannot claim protocol modelling it does not have -- the
   same honesty contract `protocol_capability.py` enforces on the registry,
   applied to each generated environment.

3. **The model reaches the MAIN environment, not just a side directory.**
   Emitting `protocol_model/*.sv` alone would leave the generated
   testbench's own files unchanged. Where a model exposes a state graph
   (today: PCIe's `LTSSM_TRANSITIONS`) and the manifest names the real DUT
   signal that carries that state, this module compiles the graph into a
   `state_machine_checks` entry -- the EXISTING manifest-driven DSL
   `generator.assertions()` already consumes, whose own docstring says it
   generalizes precisely `pcie_ltssm_generator`'s hardcoded LTSSM-legality
   pattern -- so real LTSSM transition-legality SVA lands in
   `tb/env/<p>_assertions.sv`. No new emission path is invented for it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import protocol_capability
from ..protocol_router import resolve_protocol
from .generator import sv_id
from .protocol_env_generator import FILELIST_DIR, FILELIST_NAME

# Where a layered protocol model's own files land inside the generated
# environment. A separate subdirectory (not tb/env) because these are the
# protocol model's artifacts, emitted by a different generator with its own
# file naming, and mixing them into the skeleton's LAYOUT tree would make
# "which generator produced this file" unanswerable from the tree.
PROTOCOL_MODEL_DIR = "protocol_model"

# The manifest key carrying the per-DUT facts a protocol model needs. Its
# contents are that model's own topology schema verbatim -- this module never
# reshapes or validates them, so a topology written for the standalone tool
# works unchanged here.
TOPOLOGY_KEY = "protocol_model_topology"

STATUS_LAYERED = "PROTOCOL_MODEL_LAYERED"
STATUS_NO_MODEL = "NO_PROTOCOL_MODEL_FOR_PROTOCOL"
STATUS_NO_TOPOLOGY = "PROTOCOL_MODEL_TOPOLOGY_NOT_SUPPLIED"
STATUS_UNKNOWN_PROTOCOL = "PROTOCOL_NOT_IN_CAPABILITY_REGISTRY"


class ProtocolModelLayerError(ValueError):
    """A protocol model was asked for and could not be produced.

    Same typed-error convention as create_environment.py's own three errors
    and amba_fabric_generator.py's AddressMapError: a SCREAMING_SNAKE_CASE
    `reason` plus a concrete `detail` dict. Raised only when a topology WAS
    supplied and the model refused it -- an absent topology is a recorded
    status, not an error, because that is the state every manifest written
    before this module existed is in."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _resolve_capability(protocol: str):
    """The manifest's protocol string -> a real PROTOCOL_CAPABILITIES entry.

    Two lookups, in order, both already existing: the capability registry's
    own key/alias table (now case-insensitive), then
    `protocol_router.resolve_protocol()` -- the same evidence-driven
    classifier engine.py/router.py use -- for free-form spellings the
    registry does not carry ("USB3", "PCI Express", "AXI4"). Nothing is
    guessed beyond what those two already know."""
    cap = protocol_capability.capability_for(protocol)
    if cap is not None:
        return cap, "protocol_capability.capability_for"
    decision = resolve_protocol({"protocol_hint": protocol})
    if decision.get("resolved"):
        cap = protocol_capability.capability_for(decision["protocol"])
        if cap is not None:
            return cap, "protocol_router.resolve_protocol"
    return None, None


def plan_protocol_model(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Decide, without touching the filesystem, what protocol model (if any)
    this manifest earns. Returns the record written into the generated
    environment_manifest.json as its `protocol_model` block."""
    protocol = str(manifest.get("protocol") or "")
    cap, resolved_by = _resolve_capability(protocol)

    if cap is None:
        return {
            "status": STATUS_UNKNOWN_PROTOCOL,
            "requested_protocol": protocol,
            "known_protocols": list(protocol_capability.known_protocols()),
            "reason": (
                "no PROTOCOL_CAPABILITIES entry and no protocol_router alias matches this "
                "protocol string, so whether a protocol model exists for it is unknown -- "
                "the generic skeleton was generated and nothing protocol-specific was claimed"
            ),
        }

    record: Dict[str, Any] = {
        "protocol": cap.protocol,
        "requested_protocol": protocol,
        "resolved_by": resolved_by,
        "capability_status": protocol_capability.derive_status(cap),
    }

    if cap.model is None:
        record.update({
            "status": STATUS_NO_MODEL,
            "protocol_model_generator": "NONE",
            "reason": (
                f"protocol_capability.PROTOCOL_CAPABILITIES declares no protocol-model module "
                f"for {cap.protocol}; only the protocol-agnostic skeleton applies"
            ),
        })
        return record

    record.update({
        "protocol_model_generator": cap.model.module,
        "protocol_model_tool": cap.model.tool,
        "models": list(cap.model.models),
        "does_not_model": list(cap.model.does_not_model),
    })

    topology = manifest.get(TOPOLOGY_KEY)
    if not isinstance(topology, dict) or not topology:
        record.update({
            "status": STATUS_NO_TOPOLOGY,
            "reason": (
                f"{cap.model.module} is real and would have been layered onto this "
                f"environment, but the manifest supplies no {TOPOLOGY_KEY!r}. Its fields are "
                f"per-DUT facts (see that module's own topology validator) and are never "
                f"defaulted here"
            ),
            "required_manifest_key": TOPOLOGY_KEY,
        })
        return record

    record["status"] = STATUS_LAYERED
    return record


# --- state-graph -> state_machine_checks -------------------------------------
# A protocol model's state graph reaches the MAIN generated environment only
# through the already-wired state_machine_checks DSL. One provider per model
# that HAS such a graph, keyed by the module name protocol_capability already
# declares -- an explicit, named table rather than duck-typing across five
# modules with five different internal shapes. Models with no state graph
# (AMBA's address decode, eMMC's tag lifecycle) are simply absent from it and
# layer their files only.

# The manifest topology field naming the real DUT signal that carries the
# modelled state. Required for the injection and never inferred: a signal
# name is RTL evidence, and generator.assertions() would otherwise emit an
# assertion against a signal nobody confirmed exists.
STATE_SIGNAL_KEY = "ltssm_state_signal"


def _pcie_ltssm_state_machine_check(topology: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from . import pcie_ltssm_generator as pcie

    state_signal = topology.get(STATE_SIGNAL_KEY)
    if not state_signal or not str(state_signal).strip():
        return None
    name = sv_id(topology.get("name", "pcie_ltssm"))
    return {
        "assertion_name": f"{name}_transition_legal_check",
        "kind": "valid_transition_table",
        "state_signal": str(state_signal),
        # The SV enum type the layered pcie_ltssm_pkg.sv actually declares --
        # the same `name` both are derived from, so the assertion and the
        # package it types against cannot drift apart.
        "state_type": f"{name}_ltssm_pkg::ltssm_state_e",
        "states": list(pcie.LTSSM_STATE_ORDER),
        "transitions": {s: sorted(pcie.LTSSM_TRANSITIONS[s]) for s in pcie.LTSSM_STATE_ORDER},
        "evidence": (
            "Generated from dv_harness.uvm_generator.pcie_ltssm_generator.LTSSM_TRANSITIONS, "
            "the same table the layered "
            f"{PROTOCOL_MODEL_DIR}/{name}_ltssm_pkg.sv's ltssm_transition_legal() function is "
            "generated from. Top-level LTSSM states only -- sub-states and timeout constants "
            "are unmodelled (see that module's CONFIDENCE section)."
        ),
    }


STATE_MACHINE_CHECK_PROVIDERS = {
    "dv_harness.uvm_generator.pcie_ltssm_generator": _pcie_ltssm_state_machine_check,
}


def inject_state_machine_checks(manifest: Dict[str, Any], record: Dict[str, Any]) -> Optional[str]:
    """Compile the layered model's state graph into the manifest's
    `state_machine_checks` list, so `generator.assertions()` emits real
    protocol-legality SVA into `tb/env/<p>_assertions.sv`.

    Returns the injected assertion_name, or None when this model has no state
    graph or the manifest did not name the real state signal. Mutates
    `manifest` in place -- it is create_environment.py's own private copy of
    the request, never the caller's dict."""
    if record.get("status") != STATUS_LAYERED:
        return None
    provider = STATE_MACHINE_CHECK_PROVIDERS.get(record.get("protocol_model_generator"))
    if provider is None:
        record["state_machine_check"] = {
            "injected": False,
            "reason": "this protocol model exposes no state-transition graph",
        }
        return None

    entry = provider(manifest.get(TOPOLOGY_KEY) or {})
    if entry is None:
        record["state_machine_check"] = {
            "injected": False,
            "reason": (
                f"{TOPOLOGY_KEY}.{STATE_SIGNAL_KEY} not supplied -- the DUT signal carrying the "
                f"modelled state is RTL evidence and is never inferred, so no assertion was "
                f"emitted against a signal nobody confirmed"
            ),
            "required_topology_field": STATE_SIGNAL_KEY,
        }
        return None

    entries = list(manifest.get("state_machine_checks") or [])
    existing = {sv_id(str(e.get("assertion_name"))) for e in entries
                if isinstance(e, dict) and e.get("assertion_name")}
    if sv_id(entry["assertion_name"]) in existing:
        # A manifest that already carries a hand-written check under this name
        # wins: it is author-supplied evidence about this specific DUT, and
        # overwriting it would silently replace a human's assertion with a
        # generated one. generator.assertions() would also raise
        # DUPLICATE_ASSERTION_NAME on two entries sharing a name.
        record["state_machine_check"] = {
            "injected": False,
            "reason": "the manifest already carries a state_machine_checks entry with this name",
            "assertion_name": entry["assertion_name"],
        }
        return None

    entries.append(entry)
    manifest["state_machine_checks"] = entries
    record["state_machine_check"] = {
        "injected": True,
        "assertion_name": entry["assertion_name"],
        "emitted_into": "tb/env/<protocol>_assertions.sv",
        "state_signal": entry["state_signal"],
    }
    return entry["assertion_name"]


# --- emission ----------------------------------------------------------------


def emit_protocol_model_files(out_dir, manifest: Dict[str, Any],
                              record: Dict[str, Any]) -> List[str]:
    """Run the resolved protocol-model generator into
    `<out_dir>/protocol_model/` and return the emitted paths, relative to
    out_dir (the same relative-path vocabulary ProtocolEnvGenerator returns).

    Called BEFORE the skeleton is generated, for two reasons: a topology the
    model refuses then leaves no half-written environment behind (nothing but
    an empty protocol_model/ directory), and the emitted file list is in the
    record by the time ProtocolEnvGenerator serialises it into
    environment_manifest.json. `add_protocol_model_to_filelist()` is the
    matching after-step, since the filelist does not exist until the skeleton
    is written.

    Returns [] for every non-layered status. Raises ProtocolModelLayerError
    when a supplied topology is refused by the model's own validator -- the
    caller asked for a protocol model and cannot be handed a skeleton that
    looks like one."""
    if record.get("status") != STATUS_LAYERED:
        return []

    cap = protocol_capability.capability_for(record["protocol"])
    model = cap.model
    generator_class = protocol_capability.resolve_generator_class(model)
    target = Path(out_dir) / PROTOCOL_MODEL_DIR
    topology = manifest.get(TOPOLOGY_KEY) or {}
    try:
        emitted = generator_class(target).generate(dict(topology))
    except ValueError as exc:
        # Every one of these generators raises its own typed ValueError
        # subclass carrying .reason/.detail. Re-raised in this module's own
        # vocabulary WITH the original reason preserved, so the caller learns
        # which protocol model refused and why, not just that generation
        # failed somewhere.
        raise ProtocolModelLayerError("PROTOCOL_MODEL_TOPOLOGY_REJECTED", {
            "protocol": record["protocol"],
            "protocol_model_generator": model.module,
            "model_reason": getattr(exc, "reason", str(exc)),
            "model_detail": getattr(exc, "detail", None),
        }) from exc

    relative = [f"{PROTOCOL_MODEL_DIR}/{name}" for name in emitted]
    record["generated_files"] = relative
    return relative


def add_protocol_model_to_filelist(out_dir, relative: List[str]) -> None:
    """Add the layered model's compilable sources to the environment's own
    filelist. Without this the emitted `.sv` files exist but nothing compiles
    them, and the generated `<p>_assertions.sv` would reference a package
    (`..._ltssm_pkg`) that is not in the compile unit.

    PREPENDED, not appended: an SV package must be compiled before the file
    that references its type, and the model's package is a dependency of the
    skeleton (the injected assertion types against
    `<name>_ltssm_pkg::ltssm_state_e`), never the other way round.

    Only `.sv` files are added: the models also emit topology/manifest JSON,
    which is evidence, not source."""
    out_dir = Path(out_dir)
    sources = _model_compile_order(out_dir, relative)
    if not sources:
        return
    path = out_dir / FILELIST_DIR / FILELIST_NAME
    if not path.exists():
        return
    existing = path.read_text(encoding="utf-8").splitlines()
    merged = [s for s in sources if s not in existing] + existing
    path.write_text("\n".join(merged) + "\n", encoding="utf-8")


def _model_compile_order(out_dir: Path, relative: List[str]) -> List[str]:
    """The model's `.sv` sources in COMPILE order.

    `generate()` returns its file names sorted alphabetically, which is a
    display order, not a compile order. Where the model also emitted its own
    `filelist.f` (pcie/canfd/amba/mipi all do) that file IS its declared
    compile order -- pkg before the module that imports it -- so it is used
    verbatim rather than re-derived by a rule this module would have to keep
    correct for five generators."""
    declared = out_dir / PROTOCOL_MODEL_DIR / "filelist.f"
    known = {r for r in relative if r.endswith(".sv")}
    ordered: List[str] = []
    if declared.exists():
        for line in declared.read_text(encoding="utf-8").splitlines():
            entry = f"{PROTOCOL_MODEL_DIR}/{line.strip()}"
            if entry in known and entry not in ordered:
                ordered.append(entry)
    for entry in relative:
        if entry in known and entry not in ordered:
            ordered.append(entry)
    return ordered
