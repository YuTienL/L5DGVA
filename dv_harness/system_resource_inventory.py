"""SYS-9..SYS-14 of the System-Level Verification Integration workflow: the
CROSS-SUBSYSTEM resource inventory, duplicate VIP/agent detection, resource
relationship classification, the active-driver conflict rule, shared-VIP
promotion evaluation, and subsystem-ownership preservation.

WHY A NEW MODULE RATHER THAN AN EXTENSION
-----------------------------------------
`connectivity.py` owns the connectivity matrix and its arithmetic, and every
one of its identity checks is CLOSED-WORLD over exactly one matrix:
`verify_matrix_self_check_identity(rows, exemptions)` proves
sum(verified interfaces) == sum(VIP instances) + sum(exemptions) inside ONE
subsystem's rows. `MATRIX_COLUMNS` carries no subsystem-identifying field at
all, so a caller who concatenated two subsystems' rows would have nothing to
key a "same resource, seen twice" comparison on -- a CPU AXI Master appearing
once in a PCIe environment's matrix (1 interface, 1 VIP -> identity holds) and
again in a USB environment's matrix (1 interface, 1 VIP -> identity holds)
passes both self-checks 2-for-2 with the duplicate never surfaced, because the
function is never handed both matrices at once.

That is the gap this module closes, and it is a structural one: the capability
operates on N subsystems' evidence simultaneously and therefore has no
single-subsystem home. Everything here IMPORTS and COMPOSES the existing
primitives rather than restating them:

  * `connectivity.verify_matrix_self_check_identity()` is run PER SUBSYSTEM
    before anything is compared across subsystems -- the within-one-matrix
    arithmetic stays exactly where it lives, and its verdict is carried into
    the inventory rather than recomputed.
  * `connectivity.find_amba_clock_reset_ports()` resolves an interface's real
    clock and reset ports from the RTL port list. SYS-10's "compare
    clock/reset" is answered from that, never from a name guess here.
  * `connectivity.find_active_bind_target_collisions()` is SYS-12's rule
    applied WITHIN one matrix; this module calls it per subsystem and then
    applies the same rule ACROSS subsystems.
  * `inference.score_confidence()` is the one confidence formula in the
    codebase (see `inference.py`'s own note on vocabulary separation, held by
    `dv_harness_tests/test_confidence_vocabulary_separation.py`). SYS-9's
    CONFIDENCE field is that function's output; no second scorer is defined.
  * `subsystem_command_contract`'s flat prefixed resource-id namespace
    (`BFM:HOST_SIDE`, `MODEL:SMEMMODEL`, ...) is the command-layer evidence
    axis for SYS-10's "driver ownership" signal -- built for exactly this
    handoff.
  * `uvm_generator.amba_fabric_generator.parse_addr()` parses every address
    here, so address arithmetic has one definition with one set of semantics.
  * `subsystem_architecture_analysis.classify_component_roles()` classifies
    UVM components; this module does not re-implement a role classifier.
  * `source_authority` is how a configuration disagreement between two
    subsystems is escalated -- not a second conflict resolver.

SCOPE BOUNDARY (SYS-39 / SYS-40)
--------------------------------
Discovery, analysis, planning and reporting ONLY. Nothing here generates
System-Level UVM source, a System command.txt, a System Virtual Sequencer, or
any command routing/adapter, and nothing writes into a subsystem's own
environment. `evaluate_shared_vip_promotion()` produces a RECOMMENDATION for a
human to review; promoting a resource for real is SYS-40 and needs its own
explicit approval that this workflow does not obtain.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import connectivity as conn
from . import inference
from . import source_authority as sa
from . import subsystem_command_contract as scc
from .uvm_generator.amba_fabric_generator import parse_addr

# ---------------------------------------------------------------------------
# SYS-9 vocabulary
# ---------------------------------------------------------------------------

#: SYS-9's own field list, verbatim and in its own order:
#: "Capture RESOURCE_ID, TYPE, PROTOCOL, ROLE, HIERARCHY, ACTIVE/PASSIVE,
#:  CONFIGURATION, OWNER_SUBSYSTEM, SHAREABLE, EXCLUSIVE, CLOCK, RESET,
#:  ADDRESS DOMAIN, DEPENDENCIES, EVIDENCE, CONFIDENCE."
#: Held against that sentence by a test so the requirement and the code cannot
#: drift apart in either direction.
SYS9_FIELDS: tuple = (
    "resource_id",
    "resource_type",
    "protocol",
    "role",
    "hierarchy",
    "active_passive",
    "configuration",
    "owner_subsystem",
    "shareable",
    "exclusive",
    "clock",
    "reset",
    "address_domain",
    "dependencies",
    "evidence",
    "confidence",
)

#: SYS-9's enumeration list ("VIP agents, UVM agents, CPU/BUS masters, APB/AHB/
#: AXI masters, AXI slaves, register access agents, memory models, DMA models,
#: interrupt agents, clock/reset agents, virtual sequencers, scoreboards,
#: reference models, address maps") as a closed type vocabulary, plus the
#: firmware agent SYS-13 names and an explicit UNCLASSIFIED.
RT_VIP_AGENT = "VIP_AGENT"
RT_UVM_AGENT = "UVM_AGENT"
RT_CPU_BUS_MASTER = "CPU_BUS_MASTER"
RT_APB_MASTER = "APB_MASTER"
RT_AHB_MASTER = "AHB_MASTER"
RT_AXI_MASTER = "AXI_MASTER"
RT_AXI_SLAVE = "AXI_SLAVE"
RT_REGISTER_ACCESS_AGENT = "REGISTER_ACCESS_AGENT"
RT_MEMORY_MODEL = "MEMORY_MODEL"
RT_DMA_MODEL = "DMA_MODEL"
RT_INTERRUPT_AGENT = "INTERRUPT_AGENT"
RT_CLOCK_RESET_AGENT = "CLOCK_RESET_AGENT"
RT_VIRTUAL_SEQUENCER = "VIRTUAL_SEQUENCER"
RT_SCOREBOARD = "SCOREBOARD"
RT_REFERENCE_MODEL = "REFERENCE_MODEL"
RT_ADDRESS_MAP = "ADDRESS_MAP"
RT_FIRMWARE_AGENT = "FIRMWARE_AGENT"
RT_UNCLASSIFIED = "UNCLASSIFIED"

RESOURCE_TYPES: tuple = (
    RT_VIP_AGENT, RT_UVM_AGENT, RT_CPU_BUS_MASTER, RT_APB_MASTER, RT_AHB_MASTER,
    RT_AXI_MASTER, RT_AXI_SLAVE, RT_REGISTER_ACCESS_AGENT, RT_MEMORY_MODEL,
    RT_DMA_MODEL, RT_INTERRUPT_AGENT, RT_CLOCK_RESET_AGENT, RT_VIRTUAL_SEQUENCER,
    RT_SCOREBOARD, RT_REFERENCE_MODEL, RT_ADDRESS_MAP, RT_FIRMWARE_AGENT,
    RT_UNCLASSIFIED,
)

#: SYS-13's own promotable list: "CPU AXI Master, APB Master, AHB Master, SoC
#: Register Access, DDR/Memory Model, Interrupt Controller, Clock/Reset,
#: Firmware Agent". A type outside this set is NOT_ELIGIBLE for System-Level
#: ownership no matter how strong its equivalence evidence is -- SYS-14's
#: "only shared SoC infrastructure should be promoted".
SHARED_SOC_INFRASTRUCTURE_TYPES: frozenset = frozenset({
    RT_CPU_BUS_MASTER, RT_APB_MASTER, RT_AHB_MASTER, RT_AXI_MASTER,
    RT_REGISTER_ACCESS_AGENT, RT_MEMORY_MODEL, RT_INTERRUPT_AGENT,
    RT_CLOCK_RESET_AGENT, RT_FIRMWARE_AGENT,
})

#: SYS-14's own list of subsystem-specific protocol families ("PCIe, USB, CSI2,
#: DSI, Ethernet, CAN-FD, eMMC, SD/SDIO"). A resource whose protocol is one of
#: these stays inside its subsystem even when it looks shared: a second PCIe
#: environment's PCIe VIP is not SoC infrastructure.
SUBSYSTEM_SPECIFIC_PROTOCOL_TOKENS: tuple = (
    "pcie", "pci_e", "usb", "csi2", "csi-2", "mipi_csi", "dsi", "mipi_dsi",
    "ethernet", "enet", "canfd", "can_fd", "can-fd", "emmc", "mmc", "sdio", "sd_",
)

#: Type classification tokens, most specific first. Matched against the VIP
#: type name, then the hierarchy path, and the matched token AND field are
#: recorded as the basis on every row -- the same discipline
#: `subsystem_architecture_analysis.classify_component_roles()` uses. This is
#: the FALLBACK: a row carrying a real AMBA protocol and a resolved role is
#: classified structurally instead (see `classify_resource_type()`), and
#: SYS-10 never decides a duplicate on this classifier's output alone.
RESOURCE_TYPE_TOKENS: tuple = (
    (RT_VIRTUAL_SEQUENCER, ("virtual_sequencer", "vsequencer", "vseqr", "virt_seqr")),
    (RT_REFERENCE_MODEL, ("reference_model", "ref_model", "refmodel", "golden_model")),
    (RT_SCOREBOARD, ("scoreboard", "_scbd", "_sb")),
    (RT_CLOCK_RESET_AGENT, ("clock_reset", "clk_rst", "clkrst", "reset_agent", "clock_agent")),
    (RT_INTERRUPT_AGENT, ("interrupt", "_irq", "intr_agent", "intc")),
    (RT_DMA_MODEL, ("dma", "descriptor_engine", "scatter_gather")),
    (RT_MEMORY_MODEL, ("memory_model", "mem_model", "memmodel", "ddr", "lpddr", "sram_model")),
    (RT_REGISTER_ACCESS_AGENT, ("reg_access", "register_access", "ral_agent",
                                "reg_agent", "regmodel_adapter")),
    (RT_FIRMWARE_AGENT, ("firmware", "_fw_", "fw_agent", "cpu_fw")),
    (RT_CPU_BUS_MASTER, ("cpu_axi", "cpu_master", "cpu_bus", "soc_master", "system_master")),
    (RT_APB_MASTER, ("apb_master", "apb_mst")),
    (RT_AHB_MASTER, ("ahb_master", "ahb_mst")),
    (RT_AXI_MASTER, ("axi_master", "axi_mst")),
    (RT_AXI_SLAVE, ("axi_slave", "axi_slv")),
    (RT_ADDRESS_MAP, ("address_map", "addr_map", "decoder_map")),
    (RT_VIP_AGENT, ("svt_", "_vip", "vip_")),
    (RT_UVM_AGENT, ("agent", "_agt")),
)

#: Which AMBA protocol family a MASTER-role interface belongs to. Used for the
#: STRUCTURAL branch of `classify_resource_type()`: a row whose `protocol` came
#: from `connectivity.classify_amba_protocol()` (real RTL port-name evidence)
#: and whose role came from `determine_role_from_port_direction()` (real port
#: direction) is typed from those two facts, not from its instance name.
_AMBA_MASTER_TYPE: Dict[str, str] = {
    "APB": RT_APB_MASTER, "APB3": RT_APB_MASTER, "APB4": RT_APB_MASTER,
    "AHB": RT_AHB_MASTER, "AHB_LITE": RT_AHB_MASTER,
    "AXI3": RT_AXI_MASTER, "AXI4": RT_AXI_MASTER, "AXI4_LITE": RT_AXI_MASTER,
    "AXI4_STREAM": RT_AXI_MASTER, "ACE_LITE": RT_AXI_MASTER,
}
_AMBA_SLAVE_TYPE: Dict[str, str] = {
    "AXI3": RT_AXI_SLAVE, "AXI4": RT_AXI_SLAVE, "AXI4_LITE": RT_AXI_SLAVE,
    "ACE_LITE": RT_AXI_SLAVE,
}

# --- SHAREABLE / EXCLUSIVE ---------------------------------------------------
# Three-valued on purpose. SHAREABLE_CONDITIONAL is the interesting state and
# the one a two-valued field would destroy: an ACTIVE CPU AXI Master is not
# freely shareable (two drivers on one interface is SYS-12's forbidden case)
# and not un-shareable either (SYS-12's own preferred model is exactly to
# share one through a System shared agent). Collapsing it into either YES or
# NO would state something SYS-12 does not.
SHAREABLE_YES = "SHAREABLE_YES"
SHAREABLE_CONDITIONAL = "SHAREABLE_VIA_SYSTEM_SHARED_AGENT"
SHAREABLE_NO = "SHAREABLE_NO"
SHAREABLE_UNKNOWN = "SHAREABLE_UNKNOWN"

EXCLUSIVE_YES = "EXCLUSIVE_YES"
EXCLUSIVE_NO = "EXCLUSIVE_NO"
EXCLUSIVE_UNKNOWN = "EXCLUSIVE_UNKNOWN"

UNRESOLVED = "UNRESOLVED"

# ---------------------------------------------------------------------------
# SYS-10 comparison signals
# ---------------------------------------------------------------------------

AGREE = "AGREE"
DISAGREE = "DISAGREE"
SIGNAL_UNKNOWN = "UNKNOWN"

#: SYS-10's own comparison list, verbatim: "Compare protocol, role, physical
#: interface, hierarchy, clock/reset, address domain, configuration, driver
#: ownership, active/passive mode, intended function."
IDENTITY_SIGNALS: tuple = (
    "protocol",
    "role",
    "physical_interface",
    "hierarchy",
    "clock_reset",
    "address_domain",
    "configuration",
    "driver_ownership",
    "active_passive",
    "intended_function",
)

#: SYS-10's hard rule, as a data structure rather than a comment: "Do not
#: decide duplicates by class names alone." `intended_function` is where VIP
#: type / UVM class-name equality lands (the resource-type classifier is a
#: name-token matcher in its fallback branch), so a pair whose ONLY agreeing
#: signal is this one can never be classified as a duplicate -- it reports
#: UNKNOWN with reason NAME_EVIDENCE_ONLY.
NAME_DERIVED_SIGNALS: frozenset = frozenset({"intended_function"})

#: Signals that, when they AGREE, are evidence the two resources are literally
#: ONE physical thing. SYS-13's "Require physical/logical equivalence
#: evidence" is enforced as: at least one of these must AGREE before any
#: promotion is recommended.
PHYSICAL_IDENTITY_SIGNALS: frozenset = frozenset({
    "physical_interface", "hierarchy", "driver_ownership"})

#: Signals that, when they AGREE, are evidence the two resources serve one
#: LOGICAL function even if physical identity was never proven -- and, when
#: they DISAGREE, are positive evidence they are two different things. That
#: second direction is why the veto in `classify_resource_relationship()` is
#: restricted to THIS set: two independently-generated environments name their
#: own trees independently, so two different hierarchy paths or bind targets
#: are weak evidence of difference, while two different PROTOCOLS or two
#: disjoint ADDRESS DOMAINS really do describe two different resources.
LOGICAL_IDENTITY_SIGNALS: frozenset = frozenset({
    "protocol", "role", "clock_reset", "address_domain"})

#: The signals that can actually IDENTIFY a resource, as opposed to merely
#: describing it. `role` has two values and `clock_reset` is commonly one
#: subsystem-wide name, so two resources agreeing on them is corroboration and
#: not identification -- an SoC where every AXI master shares `core_clk` would
#: otherwise report every pair of them as a duplicate. `active_passive` and
#: `intended_function` are excluded for the same reason plus, for the latter,
#: SYS-10's explicit "do not decide duplicates by class names alone".
DISCRIMINATING_SIGNALS: frozenset = PHYSICAL_IDENTITY_SIGNALS | {
    "protocol", "address_domain"}

# ---------------------------------------------------------------------------
# SYS-11 relationship classes
# ---------------------------------------------------------------------------

REL_SAME_PHYSICAL = "SAME_PHYSICAL_RESOURCE"
REL_SHARED_LOGICAL = "SHARED_LOGICAL_RESOURCE"
REL_INDEPENDENT = "INDEPENDENT_RESOURCE"
REL_MONITOR_ONLY_DUPLICATE = "MONITOR_ONLY_DUPLICATE"
REL_CONFIGURATION_CONFLICT = "CONFIGURATION_CONFLICT"
REL_DRIVER_CONFLICT = "DRIVER_CONFLICT"
REL_UNKNOWN = "UNKNOWN"

RELATIONSHIP_CLASSES: tuple = (
    REL_SAME_PHYSICAL, REL_SHARED_LOGICAL, REL_INDEPENDENT,
    REL_MONITOR_ONLY_DUPLICATE, REL_CONFIGURATION_CONFLICT,
    REL_DRIVER_CONFLICT, REL_UNKNOWN,
)

# ---------------------------------------------------------------------------
# SYS-12 integration statuses
# ---------------------------------------------------------------------------

INTEGRATION_ALLOWED = "AUTOMATIC_INTEGRATION_ALLOWED"
INTEGRATION_STOPPED = "STOP_AUTOMATIC_INTEGRATION_UNTIL_OWNERSHIP_RESOLVED"
INTEGRATION_HELD = "HOLD_PENDING_PHYSICAL_EQUIVALENCE_EVIDENCE"

#: SYS-12's own preferred model, carried as PLANNING TEXT that a human reads.
#: Nothing in this module builds any part of it -- a System shared agent and a
#: System Virtual Sequencer are SYS-40 artifacts behind a separate approval.
SYS12_PREFERRED_MODEL = (
    "SYSTEM SHARED AGENT -> System Virtual Sequencer -> subsystem requests through "
    "one shared driver. Recorded as the requirement's preferred resolution for a "
    "human to decide on; NOTHING in this module creates a shared agent, a virtual "
    "sequencer or a routing adapter -- that is SYS-40.")

# ---------------------------------------------------------------------------
# SYS-13 promotion decisions
# ---------------------------------------------------------------------------

PROMOTE_TO_SYSTEM_SHARED = "PROMOTE_TO_SYSTEM_SHARED"
KEEP_INDEPENDENT = "KEEP_INDEPENDENT"
BLOCKED_PENDING_OWNERSHIP = "BLOCKED_PENDING_OWNERSHIP_RESOLUTION"
BLOCKED_PENDING_EQUIVALENCE = "BLOCKED_PENDING_PHYSICAL_OR_LOGICAL_EQUIVALENCE_EVIDENCE"
NOT_ELIGIBLE_NOT_SOC_INFRASTRUCTURE = "NOT_ELIGIBLE_NOT_SHARED_SOC_INFRASTRUCTURE"
NOT_ELIGIBLE_SUBSYSTEM_SPECIFIC = "NOT_ELIGIBLE_SUBSYSTEM_SPECIFIC_VIP"

PROMOTION_DECISIONS: tuple = (
    PROMOTE_TO_SYSTEM_SHARED, KEEP_INDEPENDENT, BLOCKED_PENDING_OWNERSHIP,
    BLOCKED_PENDING_EQUIVALENCE, NOT_ELIGIBLE_NOT_SOC_INFRASTRUCTURE,
    NOT_ELIGIBLE_SUBSYSTEM_SPECIFIC,
)

# SYS-14 ownership verdicts.
OWNERSHIP_KEEP_IN_SUBSYSTEM = "KEEP_IN_SUBSYSTEM"
OWNERSHIP_PROMOTION_CANDIDATE = "CANDIDATE_FOR_SYSTEM_PROMOTION"


class SystemResourceInventoryError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


# ===========================================================================
# Inputs
# ===========================================================================

@dataclass
class SubsystemResourceSources:
    """The real artifacts ONE subsystem contributes to the cross-subsystem
    inventory. Three layers, each of which answers a different SYS-10 signal
    and none of which is sufficient alone:

      * `connectivity_matrix_path` -- the physical/structural axis
        (bind_target, vip_type, protocol, fabric_side_role, active_passive).
      * `env_manifest_path` -- the configuration axis
        (`vip_config.vip_instances[].config_fields`), the clock/reset axis
        (`dut_facts.clock_reset`) and the address-domain axis
        (`dut_facts.address_map`).
      * the SYS-8 contract set (supplied separately, once, for all
        subsystems) -- the command-behaviour axis for driver ownership.

    `declared_*` fields are a project's own explicit statements and beat every
    derivation. A declared physical-interface id is the ONLY way to state
    "these two subsystems' interfaces are the same SoC pin" when the two
    environments do not share a bind target -- and stating it is a human's
    decision, never this module's inference.
    """
    subsystem_id: str
    environment_root: str = ""
    env_manifest_path: str = ""
    connectivity_matrix_path: str = ""
    release_sha: str = ""
    declared_physical_interfaces: Dict[str, str] = field(default_factory=dict)
    declared_address_domains: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    declared_interface_clocks: Dict[str, Dict[str, str]] = field(default_factory=dict)
    declared_command_resource_ids: Dict[str, List[str]] = field(default_factory=dict)


def _conventional_matrix_path(environment_root: str) -> str:
    """Where a generated environment's connectivity matrix lives, by the
    convention `connectivity.ARTIFACT_FILENAMES` itself defines. Reused rather
    than re-spelled so this module and `emit_connectivity_artifacts()` cannot
    come to disagree about the filename."""
    if not environment_root:
        return ""
    name = conn.ARTIFACT_FILENAMES["matrix_manifest"]
    for rel in (Path(".dv-harness") / name, Path(name), Path(".dv-workflow") / name):
        candidate = Path(environment_root) / rel
        if candidate.is_file():
            return str(candidate)
    return ""


def sources_from_analysis(result: Mapping[str, Any], *,
                          declared: Optional[Mapping[str, Any]] = None,
                          registry_entry: Optional[Mapping[str, Any]] = None,
                          ) -> SubsystemResourceSources:
    """Build one subsystem's resource sources from its SYS-5/SYS-6 analysis
    result (`subsystem_architecture_analysis.analyze_subsystem_architecture()`).

    The analysis already resolved this subsystem's environment root and
    env.manifest.json path; taking them from there rather than re-resolving
    them is what keeps the SYS-6 report and the SYS-9 inventory describing the
    same environment. OWNER_SUBSYSTEM's `release_sha` comes from the real
    registry entry when one exists -- never from the environment tree, which
    cannot vouch for its own version.
    """
    declared = dict(declared or {})
    inputs = dict(result.get("inputs") or {})
    env_root = str(result.get("environment_root") or inputs.get("environment_root") or "")
    return SubsystemResourceSources(
        subsystem_id=str(result.get("subsystem_id") or ""),
        environment_root=env_root,
        env_manifest_path=str(inputs.get("env_manifest_path") or ""),
        connectivity_matrix_path=str(declared.get("connectivity_matrix_path")
                                     or _conventional_matrix_path(env_root)),
        release_sha=str((registry_entry or {}).get("release_sha") or ""),
        declared_physical_interfaces=dict(declared.get("physical_interfaces") or {}),
        declared_address_domains=dict(declared.get("address_domains") or {}),
        declared_interface_clocks=dict(declared.get("interface_clocks") or {}),
        declared_command_resource_ids=dict(declared.get("command_resource_ids") or {}),
    )


# ===========================================================================
# SYS-9: per-subsystem resource enumeration
# ===========================================================================

def _config_hash(config_fields: Mapping[str, Any]) -> str:
    payload = json.dumps(config_fields, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def classify_resource_type(*, vip_type: str = "", hierarchy: str = "",
                           protocol: str = "", role: str = "",
                           fabric_side_role: str = "",
                           uvm_role: str = "") -> Dict[str, Any]:
    """SYS-9's TYPE, with the evidence that decided it.

    TWO branches, and which one fired is recorded because SYS-10 treats them
    differently:

      STRUCTURAL -- the row carries a real AMBA protocol from
        `connectivity.classify_amba_protocol()` (RTL port-name evidence) and a
        real role from `determine_role_from_port_direction()` (RTL port
        direction). AXI4 + master is an AXI master because of what the ports
        are and which way they point, not because something is called
        `u_axi_m`.
      NAME_TOKEN -- nothing structural was available, so this falls back to a
        token match over the VIP type and the hierarchy path. SYS-10's
        `intended_function` signal is derived from TYPE and is therefore
        listed in NAME_DERIVED_SIGNALS: a duplicate is never decided on it
        alone.

    Returns UNCLASSIFIED rather than a plausible guess when neither branch
    produces an answer.
    """
    protocol = str(protocol or "")
    # connectivity's own two role vocabularies, matched literally rather than
    # by a loose "master" substring: `determine_role_from_port_direction()`
    # emits `vip_role=master_initiator` / `vip_role=slave_responder`, and
    # `determine_fabric_interface_roles()` emits MASTER_INTERFACE /
    # SLAVE_INTERFACE. Anything else (including AMBIGUOUS_FROM_DIRECTION_ALONE
    # and ROLE_UNRESOLVED_...) settles neither, and falls through to the
    # name-token branch rather than being forced into a side.
    role_l = str(role or "")
    fabric_l = str(fabric_side_role or "")
    is_master = ("master_initiator" in role_l
                 or fabric_l == conn.FABRIC_SIDE_MASTER_INTERFACE)
    is_slave = ("slave_responder" in role_l
                or fabric_l == conn.FABRIC_SIDE_SLAVE_INTERFACE)

    if protocol in _AMBA_MASTER_TYPE and is_master:
        return {"resource_type": _AMBA_MASTER_TYPE[protocol],
                "type_basis": "AMBA_PROTOCOL_AND_PORT_DIRECTION",
                "matched_token": protocol, "matched_field": "protocol+role"}
    if protocol in _AMBA_SLAVE_TYPE and is_slave:
        return {"resource_type": _AMBA_SLAVE_TYPE[protocol],
                "type_basis": "AMBA_PROTOCOL_AND_PORT_DIRECTION",
                "matched_token": protocol, "matched_field": "protocol+role"}

    if uvm_role:
        mapped = {"virtual_sequencer": RT_VIRTUAL_SEQUENCER,
                  "scoreboard": RT_SCOREBOARD,
                  "reference_model": RT_REFERENCE_MODEL,
                  "agent": RT_UVM_AGENT}.get(str(uvm_role))
        if mapped:
            return {"resource_type": mapped,
                    "type_basis": "UVM_COMPONENT_ROLE",
                    "matched_token": str(uvm_role), "matched_field": "uvm_role"}

    for field_name, value in (("vip_type", vip_type), ("hierarchy", hierarchy)):
        low = str(value or "").lower()
        if not low:
            continue
        for resource_type, tokens in RESOURCE_TYPE_TOKENS:
            hit = next((t for t in tokens if t in low), "")
            if hit:
                return {"resource_type": resource_type,
                        "type_basis": "NAME_TOKEN_MATCH",
                        "matched_token": hit, "matched_field": field_name}
    return {"resource_type": RT_UNCLASSIFIED, "type_basis": "NO_STRUCTURAL_OR_NAME_EVIDENCE",
            "matched_token": "", "matched_field": ""}


def derive_shareable_exclusive(active_passive: str, resource_type: str) -> Dict[str, Any]:
    """SYS-9's SHAREABLE and EXCLUSIVE, DERIVED from the active/passive
    evidence and the type -- never typed in.

    The rule is SYS-12's own: an ACTIVE agent drives a physical interface, and
    two active agents must never independently drive one. So active implies
    EXCLUSIVE_YES. Whether it is nonetheless SHAREABLE depends on whether it is
    the kind of thing SYS-13 says may be promoted: shared SoC infrastructure is
    SHAREABLE_VIA_SYSTEM_SHARED_AGENT (SYS-12's preferred model), anything else
    is SHAREABLE_NO. A PASSIVE monitor drives nothing, so any number of them
    may observe one interface -- SHAREABLE_YES, EXCLUSIVE_NO.
    """
    value = str(active_passive or "").strip().lower()
    if value == conn.ACTIVE_INTERFACE:
        shareable = (SHAREABLE_CONDITIONAL if resource_type in SHARED_SOC_INFRASTRUCTURE_TYPES
                     else SHAREABLE_NO)
        return {"shareable": shareable, "exclusive": EXCLUSIVE_YES,
                "basis": "ACTIVE -- drives the interface, so it holds it exclusively "
                         "(SYS-12); shareable only through a System shared agent, and "
                         "only for shared SoC infrastructure (SYS-13)"}
    if value == conn.PASSIVE_INTERFACE:
        return {"shareable": SHAREABLE_YES, "exclusive": EXCLUSIVE_NO,
                "basis": "PASSIVE -- observes without driving, so any number of monitors "
                         "may share this interface"}
    return {"shareable": SHAREABLE_UNKNOWN, "exclusive": EXCLUSIVE_UNKNOWN,
            "basis": f"active_passive is {active_passive!r}, not "
                     f"{sorted(conn.ACTIVE_PASSIVE_VALUES)} -- shareability cannot be "
                     f"derived without knowing whether this resource drives"}


def _rtl_module_ports(manifest: Mapping[str, Any]) -> Dict[str, List[str]]:
    """module name -> its real port names, from `dut_facts.rtl` (verible)."""
    out: Dict[str, List[str]] = {}
    for file_entry in ((manifest.get("dut_facts") or {}).get("rtl") or {}).get("files") or []:
        for module in file_entry.get("modules") or []:
            name = str(module.get("name") or "")
            if name:
                out[name] = [str(p.get("name") or "") for p in (module.get("ports") or [])]
    return out


def resolve_clock_reset(*, hierarchy: str, interface: str, protocol: str,
                        module_ports: Mapping[str, Sequence[str]],
                        clock_reset_layer: Mapping[str, Any],
                        declared: Optional[Mapping[str, str]] = None,
                        ) -> Dict[str, Any]:
    """SYS-9's CLOCK and RESET for one resource, and therefore SYS-10's
    "compare clock/reset" signal.

    Three tiers, strongest first, and the tier is always recorded:

      1. DECLARED -- the project stated this interface's clock and reset.
      2. RTL_PORT_EVIDENCE -- `connectivity.find_amba_clock_reset_ports()`
         resolves the real clock and reset PORTS of this interface's bundle
         from the owning module's full port list. That function is the single
         definition of which port names count as an AMBA family's clock and
         reset; this module does not restate it.
      3. SINGLE_CLOCK_DOMAIN_IN_SUBSYSTEM -- the subsystem's own
         `dut_facts.clock_reset` declares exactly one clock (and/or exactly one
         reset). Then every resource in it is in that domain by elimination.
         This is a derivation, not a guess: with two clocks it does NOT fire.

    Anything else reports UNRESOLVED with a reason. An unresolved clock makes
    SYS-10's clock_reset signal UNKNOWN, which is the honest outcome -- it
    never rounds to "the same".
    """
    declared = dict(declared or {})
    if declared.get("clock") or declared.get("reset"):
        return {"clock": str(declared.get("clock") or UNRESOLVED),
                "reset": str(declared.get("reset") or UNRESOLVED),
                "basis": "DECLARED_BY_PROJECT"}

    leaf = str(hierarchy or "").split(".")[-1]
    ports: List[str] = []
    matched_module = ""
    for module, names in module_ports.items():
        if module and (module == leaf or module in str(hierarchy or "")):
            ports, matched_module = list(names), module
            break
    if ports:
        found = conn.find_amba_clock_reset_ports(str(protocol or ""), str(interface or ""), ports)
        clock = found["clock"].get("port") or UNRESOLVED
        reset = found["reset"].get("port") or UNRESOLVED
        if clock != UNRESOLVED or reset != UNRESOLVED:
            return {"clock": clock, "reset": reset,
                    "basis": f"RTL_PORT_EVIDENCE via connectivity.find_amba_clock_reset_ports "
                             f"on module {matched_module}",
                    "clock_detail": found["clock"], "reset_detail": found["reset"]}

    if str(clock_reset_layer.get("status") or "") == "LOADED":
        clocks = list(clock_reset_layer.get("clocks") or [])
        resets = list(clock_reset_layer.get("resets") or [])
        clock = str(clocks[0]["name"]) if len(clocks) == 1 else UNRESOLVED
        reset = str(resets[0]["name"]) if len(resets) == 1 else UNRESOLVED
        if clock != UNRESOLVED or reset != UNRESOLVED:
            return {"clock": clock, "reset": reset,
                    "basis": "SINGLE_CLOCK_DOMAIN_IN_SUBSYSTEM -- dut_facts.clock_reset "
                             f"declares {len(clocks)} clock(s) and {len(resets)} reset(s), "
                             "so a single one is this resource's by elimination"}
        return {"clock": UNRESOLVED, "reset": UNRESOLVED,
                "basis": f"UNRESOLVED -- dut_facts.clock_reset declares {len(clocks)} clocks "
                         f"and {len(resets)} resets and no per-interface evidence assigns "
                         f"this resource to one of them"}
    return {"clock": UNRESOLVED, "reset": UNRESOLVED,
            "basis": "UNRESOLVED -- no declared interface clock, no RTL port list for this "
                     "resource's module, and dut_facts.clock_reset is not LOADED"}


def resolve_address_domain(*, hierarchy: str, protocol: str, resource_type: str,
                           address_map_layer: Mapping[str, Any],
                           declared: Optional[Sequence[Mapping[str, Any]]] = None,
                           ) -> Dict[str, Any]:
    """SYS-9's ADDRESS DOMAIN: which address regions this resource reaches.

    Every address is parsed with `amba_fabric_generator.parse_addr()`, and the
    interval convention is that module's own (`end = base + size`, exclusive),
    so an overlap computed here means the same thing an overlap computed by
    `compute_address_regions()` means.

    `status` is three-valued, and the third value is the one that stops false
    positives: RESOLVED (a declaration, or the address map's own `bus` column
    naming this resource's protocol), COARSE (the resource is a bus master and
    the address map has no `bus` column at all, so the only honest statement is
    "somewhere in this subsystem's map"), UNRESOLVED. A COARSE domain is
    reported but is deliberately NOT compared across subsystems: two whole
    subsystem maps overlapping says nothing about whether one master reaches
    the other's regions, and treating it as agreement would make every pair of
    bus resources look like a duplicate.
    """
    entries = list(address_map_layer.get("entries") or [])
    if declared:
        regions = _regions_from_entries(declared)
        return {"status": "RESOLVED", "basis": "DECLARED_BY_PROJECT", "regions": regions}
    if str(address_map_layer.get("status") or "") != "LOADED" or not entries:
        return {"status": UNRESOLVED, "regions": [],
                "basis": "UNRESOLVED -- dut_facts.address_map is not LOADED for this "
                         "subsystem (see env_manifest.build_dut_facts_address_map)"}

    proto = str(protocol or "").replace("_", "").replace("-", "").lower()
    buses = {str(e.get("bus") or "") for e in entries}
    on_bus = [e for e in entries
              if proto and str(e.get("bus") or "").replace("_", "").replace("-", "").lower() == proto]
    if on_bus:
        return {"status": "RESOLVED", "basis": "ADDRESS_MAP_BUS_COLUMN",
                "regions": _regions_from_entries(on_bus)}
    if buses == {""} and (resource_type in SHARED_SOC_INFRASTRUCTURE_TYPES
                          or resource_type in (RT_AXI_SLAVE,)):
        return {"status": "COARSE", "basis": "SUBSYSTEM_WIDE_ADDRESS_MAP -- no `bus` column "
                                             "on any entry, so which regions THIS resource "
                                             "reaches is not stated; not compared across "
                                             "subsystems",
                "regions": _regions_from_entries(entries)}
    return {"status": UNRESOLVED, "regions": [],
            "basis": f"UNRESOLVED -- {len(entries)} address-map entries, none whose `bus` is "
                     f"{protocol!r} (buses present: {sorted(b for b in buses if b) or 'none'})"}


def _regions_from_entries(entries: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    regions = []
    for entry in entries:
        try:
            base = parse_addr(entry["base_address"])
            size = parse_addr(entry["size_bytes"])
        except (KeyError, ValueError, TypeError):
            continue
        regions.append({"name": str(entry.get("name") or ""), "start": base,
                        "end": base + size, "bus": entry.get("bus"),
                        "target": entry.get("target")})
    regions.sort(key=lambda r: (r["start"], r["name"]))
    return regions


def _link_command_resources(*, hierarchy: str, vip_type: str,
                            contract_resource_names: Mapping[str, str],
                            declared: Optional[Sequence[str]] = None,
                            ) -> List[Dict[str, Any]]:
    """Which SYS-8 command-layer resource ids this env-layer resource is.

    The link is what lets SYS-10's `driver_ownership` signal use the
    command.txt evidence axis at all: `subsystem_command_contract` knows that
    two subsystems both WRITE `BFM:HOST_SIDE`, but not that `BFM:HOST_SIDE` is
    the same thing as `chip.cpu.axi_m`. A DECLARED link is authoritative; a
    derived one requires the contract resource's name to appear as a WHOLE
    dot-separated segment of the hierarchy path (or to equal the VIP type),
    never a substring -- `MODEL:MEM` must not link itself to
    `chip.memory_ctrl` on three shared letters. The basis is recorded either
    way so a reviewer can see which kind of link carried a finding.
    """
    if declared:
        return [{"resource_id": rid, "link_basis": "DECLARED_BY_PROJECT"}
                for rid in sorted(set(declared))]
    segments = {s for s in str(hierarchy or "").split(".") if s}
    vip = str(vip_type or "").strip()
    links = []
    for rid, name in sorted(contract_resource_names.items()):
        if not name:
            continue
        if name in segments:
            links.append({"resource_id": rid, "link_basis": "HIERARCHY_SEGMENT_EXACT_MATCH",
                          "matched": name})
        elif vip and name == vip:
            links.append({"resource_id": rid, "link_basis": "VIP_TYPE_EXACT_MATCH",
                          "matched": name})
    return links


def _load_connectivity_rows(path: str) -> Tuple[List[Dict[str, Any]], str]:
    """The rows of one subsystem's persisted connectivity matrix, plus a
    status string. A matrix that does not load is a real finding, reported --
    not an empty resource list that would read as "this subsystem has no
    resources"."""
    if not path:
        return [], "NO_CONNECTIVITY_MATRIX_PATH"
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        return [], f"CONNECTIVITY_MATRIX_UNREADABLE: {type(exc).__name__}: {exc}"
    except ValueError as exc:
        return [], f"CONNECTIVITY_MATRIX_NOT_JSON: {exc}"
    rows = doc.get("rows")
    if not isinstance(rows, list):
        return [], "CONNECTIVITY_MATRIX_CARRIES_NO_rows_LIST"
    return [dict(r) for r in rows], "LOADED"


def build_subsystem_resource_inventory(sources: SubsystemResourceSources, *,
                                       contract_set: Optional[Mapping[str, Any]] = None,
                                       ) -> Dict[str, Any]:
    """SYS-9 for ONE subsystem: every resource, against SYS-9's own 16-field
    list, stamped with OWNER_SUBSYSTEM.

    OWNER_SUBSYSTEM is the field the connectivity matrix structurally cannot
    carry (`MATRIX_COLUMNS` has no subsystem column) and the one every
    cross-subsystem comparison downstream is keyed on. It is taken from the
    SOURCE the row was read from -- never inferred from a path or a name -- so
    two subsystems' rows can never be confused for each other's after being
    put in one list.

    The within-one-subsystem arithmetic is NOT re-derived here:
    `connectivity.verify_matrix_self_check_identity()` is run over this
    subsystem's own rows and its verdict recorded. A matrix that fails its own
    identity is reported with the failure, and its resources still enumerated
    -- refusing to inventory it would hide the very duplicate a reviewer is
    looking for.
    """
    resources: List[Dict[str, Any]] = []
    evidence_paths: List[str] = []

    rows, matrix_status = _load_connectivity_rows(sources.connectivity_matrix_path)
    if matrix_status == "LOADED":
        evidence_paths.append(sources.connectivity_matrix_path)

    self_check: Dict[str, Any] = {"status": "NOT_RUN", "reason": matrix_status}
    bind_collisions: List[Dict[str, Any]] = []
    if rows:
        try:
            self_check = dict(conn.verify_matrix_self_check_identity(rows))
            self_check["status"] = "PASS"
        except conn.ConnectivityError as exc:
            self_check = {"status": "FAIL", "reason": getattr(exc, "reason", str(exc)),
                          "detail": getattr(exc, "detail", {})}
        # SYS-12's rule applied WITHIN this one matrix, before anything is
        # compared across subsystems: two active rows claiming one bind target
        # are two active drivers on one physical interface just as surely as
        # two subsystems' rows would be.
        bind_collisions = conn.find_active_bind_target_collisions(rows)

    manifest: Dict[str, Any] = {}
    manifest_status = "NO_ENV_MANIFEST_PATH"
    if sources.env_manifest_path:
        try:
            from . import env_manifest
            manifest = env_manifest.load_env_manifest(sources.env_manifest_path)
            manifest_status = "LOADED"
            evidence_paths.append(sources.env_manifest_path)
        except Exception as exc:  # a real artifact that will not load is a finding
            manifest_status = f"ENV_MANIFEST_UNREADABLE: {type(exc).__name__}: {exc}"

    vip_config = manifest.get("vip_config") or {}
    dut_facts = manifest.get("dut_facts") or {}
    clock_reset_layer = dut_facts.get("clock_reset") or {}
    address_map_layer = dut_facts.get("address_map") or {}
    module_ports = _rtl_module_ports(manifest)
    config_by_path = {str(v.get("instance_path") or ""): dict(v.get("config_fields") or {})
                      for v in (vip_config.get("vip_instances") or [])}
    vip_type_by_path = {str(v.get("instance_path") or ""): str(v.get("vip_type") or "")
                        for v in (vip_config.get("vip_instances") or [])}

    contract_resource_names = _contract_resource_names(contract_set, sources.subsystem_id)
    writes_by_resource = _contract_writes(contract_set, sources.subsystem_id)

    def _emit(*, kind_evidence: str, hierarchy: str, interface: str, vip_type: str,
              protocol: str, role: str, fabric_side_role: str, active_passive: str,
              bind_target: str, config_fields: Mapping[str, Any],
              uvm_role: str = "", extra_evidence: Sequence[str] = ()) -> Dict[str, Any]:
        type_info = classify_resource_type(
            vip_type=vip_type, hierarchy=hierarchy, protocol=protocol, role=role,
            fabric_side_role=fabric_side_role, uvm_role=uvm_role)
        share = derive_shareable_exclusive(active_passive, type_info["resource_type"])
        clocks = resolve_clock_reset(
            hierarchy=hierarchy, interface=interface, protocol=protocol,
            module_ports=module_ports, clock_reset_layer=clock_reset_layer,
            declared=sources.declared_interface_clocks.get(hierarchy)
            or sources.declared_interface_clocks.get(interface))
        domain = resolve_address_domain(
            hierarchy=hierarchy, protocol=protocol,
            resource_type=type_info["resource_type"],
            address_map_layer=address_map_layer,
            declared=sources.declared_address_domains.get(hierarchy))
        links = _link_command_resources(
            hierarchy=hierarchy, vip_type=vip_type,
            contract_resource_names=contract_resource_names,
            declared=sources.declared_command_resource_ids.get(hierarchy))
        physical_id = (sources.declared_physical_interfaces.get(f"{hierarchy}::{interface}")
                       or sources.declared_physical_interfaces.get(hierarchy)
                       or sources.declared_physical_interfaces.get(interface) or "")

        evidence = [kind_evidence] + [e for e in extra_evidence if e]
        # SYS-9's CONFIDENCE, from the ONE confidence formula in this codebase
        # (inference.score_confidence). independent sources = how many distinct
        # real artifacts contributed a field to this record; counter-evidence =
        # fields whose evidence contradicted itself.
        independent = sum(1 for present in (
            matrix_status == "LOADED",
            manifest_status == "LOADED" and bool(config_fields),
            clocks["basis"].startswith(("DECLARED", "RTL_PORT_EVIDENCE",
                                        "SINGLE_CLOCK_DOMAIN")),
            domain["status"] in ("RESOLVED", "COARSE"),
        ) if present)
        counter = int(str(self_check.get("status")) == "FAIL")
        confidence = inference.score_confidence(
            independent_sources_count=independent,
            evidence_refs_verified=bool(evidence_paths),
            counter_evidence_count=counter,
            multi_agent_consensus_count=0)

        record = {
            "resource_id": f"{sources.subsystem_id}::{hierarchy}::{interface}",
            "resource_type": type_info["resource_type"],
            "protocol": protocol or conn.PROTOCOL_NOT_CLASSIFIED,
            "role": role or UNRESOLVED,
            "hierarchy": hierarchy,
            "active_passive": active_passive,
            "configuration": {"config_fields": dict(config_fields),
                              "config_field_count": len(config_fields),
                              "configuration_hash": _config_hash(config_fields),
                              "source": ("env.manifest.json vip_config.vip_instances"
                                         if config_fields else manifest_status)},
            "owner_subsystem": sources.subsystem_id,
            "shareable": share["shareable"],
            "exclusive": share["exclusive"],
            "clock": clocks["clock"],
            "reset": clocks["reset"],
            "address_domain": domain,
            "dependencies": {
                "clock": clocks["clock"], "reset": clocks["reset"],
                "command_resource_ids": links,
                "written_by_this_subsystems_commands": sorted(
                    l["resource_id"] for l in links
                    if l["resource_id"] in writes_by_resource),
            },
            "evidence": evidence,
            "confidence": confidence["level"],
            # Non-SYS-9 provenance carried beside the mandated fields, never
            # instead of them: a verdict whose basis is not recorded next to it
            # cannot be checked.
            "type_basis": type_info["type_basis"],
            "type_matched_token": type_info["matched_token"],
            "type_matched_field": type_info["matched_field"],
            "shareable_basis": share["basis"],
            "clock_reset_basis": clocks["basis"],
            "bind_target": bind_target,
            "interface": interface,
            "fabric_side_role": fabric_side_role,
            "physical_interface_id": physical_id,
            "owner_release_sha": sources.release_sha,
            "confidence_detail": confidence,
        }
        missing = [f for f in SYS9_FIELDS if f not in record]
        if missing:  # structural bug, not a data condition
            raise SystemResourceInventoryError("SYS9_FIELD_MISSING", {"fields": missing})
        return record

    seen_paths = set()
    for row in rows:
        vip_type = str(row.get("vip_type") or "")
        if vip_type.strip().upper() in conn.NO_VIP_MARKERS:
            # An interface with no VIP is not a RESOURCE -- it is a gap, and
            # connectivity's own exemption machinery already accounts for it.
            continue
        hierarchy = str(row.get("dut_instance") or "")
        interface = str(row.get("interface") or "")
        bind_target = str(row.get("bind_target") or "")
        config = (config_by_path.get(bind_target) or config_by_path.get(hierarchy)
                  or config_by_path.get(f"{hierarchy}.{interface}") or {})
        seen_paths.update({bind_target, hierarchy, f"{hierarchy}.{interface}"} & set(config_by_path))
        resources.append(_emit(
            kind_evidence=f"{sources.connectivity_matrix_path}#{hierarchy}::{interface}",
            hierarchy=hierarchy, interface=interface, vip_type=vip_type,
            protocol=str(row.get("protocol") or ""), role=str(row.get("role") or ""),
            fabric_side_role=str(row.get("fabric_side_role") or ""),
            active_passive=str(row.get("active_passive") or ""),
            bind_target=bind_target, config_fields=config,
            extra_evidence=[sources.env_manifest_path] if config else []))

    # VIP instances the matrix never mentioned. A VIP present in the live
    # config dump but absent from the matrix is exactly the kind of resource a
    # cross-subsystem duplicate hides behind, so it is inventoried rather than
    # dropped -- with active_passive UNKNOWN, because the dump does not say.
    for instance_path, config in sorted(config_by_path.items()):
        if instance_path in seen_paths or not instance_path:
            continue
        resources.append(_emit(
            kind_evidence=(f"{sources.env_manifest_path}"
                           f"#vip_config.vip_instances::{instance_path}"),
            hierarchy=instance_path, interface="", vip_type=vip_type_by_path.get(instance_path, ""),
            protocol="", role="", fabric_side_role="",
            active_passive="", bind_target=instance_path, config_fields=config))

    resources.sort(key=lambda r: r["resource_id"])
    return {
        "subsystem_id": sources.subsystem_id,
        "environment_root": sources.environment_root,
        "release_sha": sources.release_sha,
        "resources": resources,
        "resource_count": len(resources),
        "connectivity_matrix_path": sources.connectivity_matrix_path,
        "connectivity_matrix_status": matrix_status,
        "env_manifest_path": sources.env_manifest_path,
        "env_manifest_status": manifest_status,
        "matrix_self_check": self_check,
        "within_subsystem_bind_collisions": bind_collisions,
        "evidence_paths": sorted(set(p for p in evidence_paths if p)),
        "artifacts_modified": False,
    }


def _contract_resource_names(contract_set: Optional[Mapping[str, Any]],
                             subsystem_id: str) -> Dict[str, str]:
    """SYS-8 resource id -> its bare name, for the subsystem's own contracts."""
    out: Dict[str, str] = {}
    for contract in ((contract_set or {}).get("contracts") or []):
        if str(contract.get("subsystem_id")) != subsystem_id:
            continue
        for resource in contract.get("required_resources") or []:
            out[str(resource["resource_id"])] = str(resource.get("name") or "")
    return out


def _contract_writes(contract_set: Optional[Mapping[str, Any]],
                     subsystem_id: str) -> Dict[str, List[str]]:
    """SYS-8 resource id -> the contracts of THIS subsystem that WRITE it."""
    out: Dict[str, List[str]] = {}
    for contract in ((contract_set or {}).get("contracts") or []):
        if str(contract.get("subsystem_id")) != subsystem_id:
            continue
        for resource in contract.get("required_resources") or []:
            if resource.get("access") == "WRITE":
                out.setdefault(str(resource["resource_id"]), []).append(
                    scc.contract_id(contract))
    return out


def build_cross_subsystem_inventory(sources: Sequence[SubsystemResourceSources], *,
                                    contract_set: Optional[Mapping[str, Any]] = None,
                                    ) -> Dict[str, Any]:
    """SYS-9 across every selected subsystem at once -- the step that has no
    single-subsystem home.

    Refuses a source list with a repeated subsystem_id: two entries claiming
    one OWNER_SUBSYSTEM would make every resource_id ambiguous, which is the
    exact failure this field exists to prevent.
    """
    sources = list(sources)
    names = [s.subsystem_id for s in sources]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise SystemResourceInventoryError("DUPLICATE_SUBSYSTEM_ID_IN_SOURCES", {
            "subsystem_ids": duplicates,
            "hint": "OWNER_SUBSYSTEM must identify exactly one environment; two sources "
                    "sharing an id make every resource_id ambiguous"})
    per_subsystem = [build_subsystem_resource_inventory(s, contract_set=contract_set)
                     for s in sources]
    resources = [r for inv in per_subsystem for r in inv["resources"]]
    return {
        "subsystems": names,
        "per_subsystem": per_subsystem,
        "resources": resources,
        "resource_count": len(resources),
        "resources_by_owner": {inv["subsystem_id"]: inv["resource_count"]
                               for inv in per_subsystem},
        "artifacts_modified": False,
    }


# ===========================================================================
# SYS-10: duplicate VIP / agent detection
# ===========================================================================

def _signal(verdict: str, basis: str, **detail) -> Dict[str, Any]:
    return dict({"verdict": verdict, "basis": basis}, **detail)


def _hierarchy_related(a: str, b: str) -> Optional[str]:
    if not a or not b:
        return None
    if a == b:
        return "IDENTICAL_HIERARCHY_PATH"
    a_parts, b_parts = a.split("."), b.split(".")
    if a_parts[:len(b_parts)] == b_parts or b_parts[:len(a_parts)] == a_parts:
        return "ANCESTOR_DESCENDANT_HIERARCHY_PATH"
    return None


def _regions_overlap(a: Sequence[Mapping[str, Any]],
                     b: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Overlapping [start, end) pairs, using the exclusive-end convention
    `amba_fabric_generator.compute_address_regions()` enforces."""
    hits = []
    for ra in a:
        for rb in b:
            lo, hi = max(ra["start"], rb["start"]), min(ra["end"], rb["end"])
            if lo < hi:
                hits.append({"a": ra["name"], "b": rb["name"],
                             "overlap_start": lo, "overlap_end": hi})
    return hits


def compare_resources(a: Mapping[str, Any], b: Mapping[str, Any], *,
                      contract_set: Optional[Mapping[str, Any]] = None,
                      ) -> Dict[str, Any]:
    """SYS-10's comparison, signal by signal, for one pair of resources owned
    by two DIFFERENT subsystems.

    Each of SYS-10's ten named signals gets AGREE / DISAGREE / UNKNOWN and a
    basis. UNKNOWN is a first-class outcome, not a rounding of DISAGREE: "we
    could not tell whether these share a clock" and "these are on different
    clocks" are opposite findings, and collapsing them is how a dedup
    mechanism produces confident nonsense.
    """
    signals: Dict[str, Dict[str, Any]] = {}

    # protocol -- connectivity's RTL-signal classifier, never a name.
    pa, pb = str(a["protocol"]), str(b["protocol"])
    unclassified = {conn.PROTOCOL_NOT_CLASSIFIED, "", conn.AMBA_PROTOCOL_UNRESOLVED}
    if pa in unclassified or pb in unclassified:
        signals["protocol"] = _signal(
            SIGNAL_UNKNOWN, "at least one row was never put through "
            "connectivity.classify_amba_protocol(), or its evidence did not settle a "
            "protocol", a=pa, b=pb)
    else:
        signals["protocol"] = _signal(AGREE if pa == pb else DISAGREE,
                                      "connectivity classify_amba_protocol() result",
                                      a=pa, b=pb)

    # role -- derived from real DUT port direction.
    ra, rb = str(a["role"]), str(b["role"])
    # AMBIGUOUS_FROM_DIRECTION_ALONE and ROLE_UNRESOLVED_... are connectivity's
    # own "the evidence did not settle this" values, not roles. Two of them
    # matching as strings is not two resources agreeing about anything.
    unresolved_roles = (UNRESOLVED, "", conn.ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS)
    if (ra in unresolved_roles or rb in unresolved_roles
            or "AMBIGUOUS_FROM_DIRECTION_ALONE" in ra
            or "AMBIGUOUS_FROM_DIRECTION_ALONE" in rb):
        signals["role"] = _signal(SIGNAL_UNKNOWN, "role unresolved on at least one side",
                                  a=ra, b=rb)
    else:
        same = ra.split()[0].lower() == rb.split()[0].lower()
        signals["role"] = _signal(AGREE if same else DISAGREE,
                                  "connectivity determine_role_from_port_direction() result",
                                  a=ra, b=rb)

    # physical interface -- the strongest signal, and the only one that can
    # come from a human declaration.
    ida, idb = str(a.get("physical_interface_id") or ""), str(b.get("physical_interface_id") or "")
    bta, btb = str(a.get("bind_target") or ""), str(b.get("bind_target") or "")
    if ida and idb:
        signals["physical_interface"] = _signal(
            AGREE if ida == idb else DISAGREE,
            "DECLARED_PHYSICAL_INTERFACE_MAP", a=ida, b=idb)
    elif bta and btb:
        signals["physical_interface"] = _signal(
            AGREE if bta == btb else DISAGREE,
            "IDENTICAL_BIND_TARGET -- two independently generated environments naming "
            "one absolute hierarchy path is real structural evidence, not a name match",
            a=bta, b=btb)
    else:
        signals["physical_interface"] = _signal(
            SIGNAL_UNKNOWN, "no declared physical-interface id and no bind target on at "
                            "least one side; a project declaration would settle this",
            a=ida or bta, b=idb or btb)

    # hierarchy
    relation = _hierarchy_related(str(a["hierarchy"]), str(b["hierarchy"]))
    if not a["hierarchy"] or not b["hierarchy"]:
        signals["hierarchy"] = _signal(SIGNAL_UNKNOWN, "hierarchy path missing on one side",
                                       a=a["hierarchy"], b=b["hierarchy"])
    elif relation:
        signals["hierarchy"] = _signal(AGREE, relation, a=a["hierarchy"], b=b["hierarchy"])
    else:
        signals["hierarchy"] = _signal(DISAGREE, "UNRELATED_HIERARCHY_PATHS",
                                       a=a["hierarchy"], b=b["hierarchy"])

    # clock / reset
    ca, cb = str(a["clock"]), str(b["clock"])
    sa_, sb_ = str(a["reset"]), str(b["reset"])
    if UNRESOLVED in (ca, cb) and UNRESOLVED in (sa_, sb_):
        signals["clock_reset"] = _signal(SIGNAL_UNKNOWN,
                                         "clock and reset unresolved on at least one side",
                                         a=[ca, sa_], b=[cb, sb_])
    else:
        pairs = [(ca, cb), (sa_, sb_)]
        comparable = [(x, y) for x, y in pairs if UNRESOLVED not in (x, y)]
        if not comparable:
            signals["clock_reset"] = _signal(SIGNAL_UNKNOWN, "no comparable clock/reset pair",
                                             a=[ca, sa_], b=[cb, sb_])
        else:
            same = all(x == y for x, y in comparable)
            signals["clock_reset"] = _signal(
                AGREE if same else DISAGREE,
                f"{a['clock_reset_basis']} vs {b['clock_reset_basis']}",
                a=[ca, sa_], b=[cb, sb_])

    # address domain -- COARSE domains are deliberately not compared.
    da, db = a["address_domain"], b["address_domain"]
    if da["status"] != "RESOLVED" or db["status"] != "RESOLVED":
        signals["address_domain"] = _signal(
            SIGNAL_UNKNOWN,
            f"address domains are {da['status']} / {db['status']}; a COARSE "
            "(subsystem-wide) domain is not evidence about one resource's reach",
            a=da["status"], b=db["status"])
    else:
        overlaps = _regions_overlap(da["regions"], db["regions"])
        signals["address_domain"] = _signal(
            AGREE if overlaps else DISAGREE,
            "interval overlap using amba_fabric_generator.parse_addr and its "
            "exclusive-end convention",
            overlaps=overlaps[:8],
            a=[r["name"] for r in da["regions"]][:8],
            b=[r["name"] for r in db["regions"]][:8])

    # configuration
    fa = dict(a["configuration"]["config_fields"])
    fb = dict(b["configuration"]["config_fields"])
    shared_keys = sorted(set(fa) & set(fb))
    if not shared_keys:
        signals["configuration"] = _signal(
            SIGNAL_UNKNOWN,
            "no config field captured on both sides (a live vip_config dump is what "
            "produces them -- see env_manifest.build_vip_config)",
            a_field_count=len(fa), b_field_count=len(fb))
    else:
        differing = [{"field": k, "a": fa[k], "b": fb[k]} for k in shared_keys if fa[k] != fb[k]]
        signals["configuration"] = _signal(
            DISAGREE if differing else AGREE,
            "env.manifest.json vip_config.vip_instances[].config_fields",
            shared_field_count=len(shared_keys), differing=differing[:8])

    # driver ownership -- the COMMAND-layer axis, independent of the matrix.
    signals["driver_ownership"] = _driver_ownership_signal(a, b, contract_set)

    # active / passive
    aa, ab = str(a["active_passive"]).lower(), str(b["active_passive"]).lower()
    if aa not in conn.ACTIVE_PASSIVE_VALUES or ab not in conn.ACTIVE_PASSIVE_VALUES:
        signals["active_passive"] = _signal(SIGNAL_UNKNOWN,
                                            "active/passive not in connectivity's vocabulary "
                                            "on at least one side", a=aa, b=ab)
    else:
        signals["active_passive"] = _signal(AGREE if aa == ab else DISAGREE,
                                            "connectivity matrix active_passive column",
                                            a=aa, b=ab)

    # intended function -- THE NAME-DERIVED SIGNAL. Listed in
    # NAME_DERIVED_SIGNALS and never sufficient on its own.
    ta, tb = str(a["resource_type"]), str(b["resource_type"])
    if RT_UNCLASSIFIED in (ta, tb):
        signals["intended_function"] = _signal(SIGNAL_UNKNOWN,
                                               "resource type unclassified on one side",
                                               a=ta, b=tb)
    else:
        signals["intended_function"] = _signal(
            AGREE if ta == tb else DISAGREE,
            f"resource type ({a['type_basis']} / {b['type_basis']}) -- NAME-DERIVED in its "
            f"fallback branch, so SYS-10 forbids deciding a duplicate on this alone",
            a=ta, b=tb)

    missing = [s for s in IDENTITY_SIGNALS if s not in signals]
    if missing:
        raise SystemResourceInventoryError("SYS10_SIGNAL_MISSING", {"signals": missing})

    agreeing = [s for s in IDENTITY_SIGNALS if signals[s]["verdict"] == AGREE]
    disagreeing = [s for s in IDENTITY_SIGNALS if signals[s]["verdict"] == DISAGREE]
    return {
        "resource_a": a["resource_id"], "resource_b": b["resource_id"],
        "subsystem_a": a["owner_subsystem"], "subsystem_b": b["owner_subsystem"],
        "signals": {s: signals[s] for s in IDENTITY_SIGNALS},
        "agreeing_signals": agreeing,
        "disagreeing_signals": disagreeing,
        "unknown_signals": [s for s in IDENTITY_SIGNALS
                            if signals[s]["verdict"] == SIGNAL_UNKNOWN],
        "structural_agreeing_signals": [s for s in agreeing if s not in NAME_DERIVED_SIGNALS],
        "identity_agreeing_signals": [s for s in agreeing if s in DISCRIMINATING_SIGNALS],
        "physical_identity_signals_agreeing": [s for s in agreeing
                                               if s in PHYSICAL_IDENTITY_SIGNALS],
        "logical_identity_signals_agreeing": [s for s in agreeing
                                              if s in LOGICAL_IDENTITY_SIGNALS],
        "logical_identity_signals_disagreeing": [s for s in disagreeing
                                                 if s in LOGICAL_IDENTITY_SIGNALS],
    }


def _driver_ownership_signal(a: Mapping[str, Any], b: Mapping[str, Any],
                             contract_set: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """SYS-10's "driver ownership" signal, from the SYS-8 contract set.

    This is a genuinely independent evidence axis from everything else in the
    comparison: it asks what the two subsystems' real command.txt files DO,
    not how their environments are wired. Two subsystems whose commands both
    WRITE one SYS-8 resource id are both claiming to drive it, which is the
    "PCIe and USB both contain a CPU AXI Master" shape SYS-10 exists for --
    detected from behaviour, not from either VIP's class name.
    """
    links_a = {l["resource_id"] for l in a["dependencies"]["command_resource_ids"]}
    links_b = {l["resource_id"] for l in b["dependencies"]["command_resource_ids"]}
    if not contract_set or not links_a or not links_b:
        return _signal(SIGNAL_UNKNOWN,
                       "no SYS-8 contract set, or this resource is not linked to any "
                       "command-layer resource id (declare command_resource_ids to settle it)",
                       a=sorted(links_a), b=sorted(links_b))
    writes_a = set(_contract_writes(contract_set, str(a["owner_subsystem"])))
    writes_b = set(_contract_writes(contract_set, str(b["owner_subsystem"])))
    common_written = sorted((links_a & links_b) & writes_a & writes_b)
    if common_written:
        return _signal(AGREE,
                       "both subsystems' command.txt WRITE the same SYS-8 resource id "
                       "(subsystem_command_contract required_resources access=WRITE)",
                       common_written_resource_ids=common_written,
                       a=sorted(links_a), b=sorted(links_b))
    if (links_a & writes_a) and (links_b & writes_b) and not (links_a & links_b):
        return _signal(DISAGREE,
                       "each subsystem's command.txt writes a DIFFERENT command-layer "
                       "resource; these are two distinct drivers",
                       a=sorted(links_a & writes_a), b=sorted(links_b & writes_b))
    return _signal(SIGNAL_UNKNOWN,
                   "the linked command-layer resources are not written by both subsystems, "
                   "so the command evidence does not establish shared driver ownership",
                   a=sorted(links_a), b=sorted(links_b))


def detect_duplicate_resources(inventory: Mapping[str, Any], *,
                               contract_set: Optional[Mapping[str, Any]] = None,
                               ) -> List[Dict[str, Any]]:
    """SYS-10, MANDATORY: every candidate duplicate across the selected
    subsystems, each with its full ten-signal comparison.

    A candidate is any pair of resources owned by DIFFERENT subsystems with at
    least one AGREEING signal. Same-subsystem pairs are excluded on purpose:
    SYS-10 is about "the same physical CPU AXI Master appearing in both a PCIe
    and a USB subsystem", and a subsystem's own internal duplicates are what
    `connectivity.verify_matrix_self_check_identity()` and
    `find_active_bind_target_collisions()` already cover per subsystem (both
    are run in `build_subsystem_resource_inventory()`).
    """
    resources = list(inventory["resources"])
    pairs: List[Dict[str, Any]] = []
    for i, a in enumerate(resources):
        for b in resources[i + 1:]:
            if a["owner_subsystem"] == b["owner_subsystem"]:
                continue
            comparison = compare_resources(a, b, contract_set=contract_set)
            if comparison["agreeing_signals"]:
                pairs.append(comparison)
    pairs.sort(key=lambda c: (c["resource_a"], c["resource_b"]))
    return pairs


# ===========================================================================
# SYS-11: resource relationship classification
# ===========================================================================

def classify_resource_relationship(comparison: Mapping[str, Any], *,
                                   resources_by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
                                   ) -> Dict[str, Any]:
    """SYS-11: classify one apparent duplicate into exactly one of the seven
    classes, most specific true statement first.

    The decision table, and why it is ordered this way:

      1. Physical identity established (a declared physical-interface id, a
         shared bind target, or shared driver ownership from the command
         layer) -- then refine:
           a. both ACTIVE -> DRIVER_CONFLICT. This outranks a configuration
              disagreement because SYS-12's stop rule is triggered by the two
              drivers, not by their settings; the configuration finding is
              still carried in the record.
           b. configurations DISAGREE -> CONFIGURATION_CONFLICT.
           c. both PASSIVE -> MONITOR_ONLY_DUPLICATE. Two monitors on one
              interface are a duplicate but not a hazard.
           d. otherwise -> SAME_PHYSICAL_RESOURCE.
      2. No physical identity, and a LOGICAL identity signal DISAGREES ->
         INDEPENDENT_RESOURCE. Two different protocols, or two disjoint
         address domains, are positive evidence of two different resources.
         Only this set vetoes: two independently-generated environments name
         their own trees independently, so differing hierarchy paths or bind
         targets are weak evidence of difference, not strong.
      3. ADDRESS DOMAIN agrees (a real overlap of concrete ranges) plus at
         least one more logical signal -> SHARED_LOGICAL_RESOURCE. The address
         overlap is required because `role` has two values and `clock_reset`
         is commonly one subsystem-wide name: "same protocol, same role" alone
         makes every AXI4 master in an SoC a candidate.
      4. No DISCRIMINATING signal agrees at all, and the class names match ->
         UNKNOWN / NAME_EVIDENCE_ONLY. SYS-10's own sentence: "Do not decide
         duplicates by class names alone."
      5. Anything else -> UNKNOWN, with what would settle it.
    """
    signals = comparison["signals"]
    resources_by_id = dict(resources_by_id or {})
    agreeing = comparison["agreeing_signals"]
    structural_agree = comparison["structural_agreeing_signals"]
    identity_agree = comparison["identity_agreeing_signals"]
    physical = comparison["physical_identity_signals_agreeing"]
    logical = comparison["logical_identity_signals_agreeing"]
    logical_disagree = comparison["logical_identity_signals_disagreeing"]

    a = resources_by_id.get(comparison["resource_a"], {})
    b = resources_by_id.get(comparison["resource_b"], {})
    aa = str(a.get("active_passive", "")).lower()
    ab = str(b.get("active_passive", "")).lower()
    both_active = aa == conn.ACTIVE_INTERFACE and ab == conn.ACTIVE_INTERFACE
    both_passive = aa == conn.PASSIVE_INTERFACE and ab == conn.PASSIVE_INTERFACE
    config_disagrees = signals["configuration"]["verdict"] == DISAGREE

    if physical and both_active:
        relationship, reason = REL_DRIVER_CONFLICT, (
            f"physical identity established by {physical} and BOTH resources are ACTIVE "
            "-- two agents would independently drive one physical interface"
            + (f"; their configurations also disagree on "
               f"{[d['field'] for d in signals['configuration'].get('differing', [])]}"
               if config_disagrees else ""))
    elif physical and config_disagrees:
        relationship, reason = REL_CONFIGURATION_CONFLICT, (
            f"physical identity established by {physical}, but the two environments "
            f"configure it differently: "
            f"{[d['field'] for d in signals['configuration'].get('differing', [])]}")
    elif physical and both_passive:
        relationship, reason = REL_MONITOR_ONLY_DUPLICATE, (
            f"physical identity established by {physical} and both resources are PASSIVE "
            "-- two monitors observing one interface, a duplicate but not a driver hazard")
    elif physical:
        relationship, reason = REL_SAME_PHYSICAL, (
            f"physical identity established by {physical}; at most one side drives, so "
            "there is no active-driver conflict")
    elif logical_disagree:
        relationship, reason = REL_INDEPENDENT, (
            f"no physical-identity evidence, and the logical identity signal(s) "
            f"{logical_disagree} DISAGREE -- two resources with different protocol, "
            "role, clock domain or address domain are two different things, however "
            "similarly they are named")
    elif signals["address_domain"]["verdict"] == AGREE and len(logical) >= 2:
        relationship, reason = REL_SHARED_LOGICAL, (
            f"no physical-identity evidence, but the address domains genuinely overlap "
            f"and {logical} agree -- one logical function served in two subsystems. "
            "Physical equivalence is NOT established")
    elif not identity_agree:
        relationship, reason = REL_UNKNOWN, (
            "NAME_EVIDENCE_ONLY -- no discriminating signal "
            f"({sorted(DISCRIMINATING_SIGNALS)}) agrees; the agreeing signal(s) "
            f"{agreeing} only describe the two resources, and the type match is "
            "name-derived. SYS-10 forbids deciding a duplicate on class names alone; "
            "a declared physical-interface id, a shared bind target, a resolved "
            "address domain or a live vip_config dump would settle it")
    else:
        relationship, reason = REL_UNKNOWN, (
            f"agreeing discriminating signals {identity_agree} are insufficient for "
            f"physical identity ({sorted(PHYSICAL_IDENTITY_SIGNALS)}) and the address "
            f"domains do not establish shared logical use; unknown signals: "
            f"{comparison['unknown_signals']}")

    return {
        "resource_a": comparison["resource_a"], "resource_b": comparison["resource_b"],
        "subsystem_a": comparison["subsystem_a"], "subsystem_b": comparison["subsystem_b"],
        "relationship": relationship,
        "reason": reason,
        "physical_identity_evidence": physical,
        "logical_identity_evidence": logical,
        "identity_evidence": identity_agree,
        "name_evidence_only": (not identity_agree
                               and signals["intended_function"]["verdict"] == AGREE),
        "structural_agreeing_signals": structural_agree,
        "both_active": both_active,
        "configuration_disagrees": config_disagrees,
        "comparison": comparison,
    }


def classify_relationships(comparisons: Sequence[Mapping[str, Any]],
                           resources_by_id: Mapping[str, Mapping[str, Any]],
                           ) -> List[Dict[str, Any]]:
    out = [classify_resource_relationship(c, resources_by_id=resources_by_id)
           for c in comparisons]
    out.sort(key=lambda r: (r["relationship"], r["resource_a"], r["resource_b"]))
    return out


# ===========================================================================
# SYS-12: active driver conflict rule
# ===========================================================================

def apply_active_driver_conflict_rule(relationships: Sequence[Mapping[str, Any]],
                                      inventory: Mapping[str, Any],
                                      ) -> Dict[str, Any]:
    """SYS-12: "Two active agents must never independently drive the same
    physical interface. On DRIVER_CONFLICT, stop automatic integration of that
    resource until ownership is resolved."

    Applied from BOTH sources, which is the point -- SYS-12 says two active
    agents, not two subsystems:

      * ACROSS subsystems, from SYS-11's DRIVER_CONFLICT verdicts.
      * WITHIN one subsystem, from `connectivity.find_active_bind_target_
        collisions()` run over that subsystem's own matrix in
        `build_subsystem_resource_inventory()`. Two active rows in ONE matrix
        claiming one bind target passed every existing check before this,
        because nothing anywhere asserted bind_target uniqueness.

    An unproven-but-active pair (SHARED_LOGICAL_RESOURCE or UNKNOWN with both
    sides active) is HELD rather than STOPPED: the honest statement is that we
    cannot yet say whether it is one interface, and auto-integrating on that
    basis would be the guess SYS-10 forbids.

    Returns a decision per affected resource. It DECIDES nothing about the
    implementation -- SYS12_PREFERRED_MODEL is carried as text for a human.
    """
    decisions: List[Dict[str, Any]] = []
    stopped: set = set()
    held: set = set()

    for rel in relationships:
        if rel["relationship"] == REL_DRIVER_CONFLICT:
            stopped.update({rel["resource_a"], rel["resource_b"]})
            decisions.append({
                "scope": "CROSS_SUBSYSTEM",
                "integration_status": INTEGRATION_STOPPED,
                "relationship": rel["relationship"],
                "resources": [rel["resource_a"], rel["resource_b"]],
                "subsystems": sorted({rel["subsystem_a"], rel["subsystem_b"]}),
                "reason": rel["reason"],
                "preferred_model": SYS12_PREFERRED_MODEL,
            })
        elif rel["both_active"] and rel["relationship"] in (REL_SHARED_LOGICAL, REL_UNKNOWN):
            held.update({rel["resource_a"], rel["resource_b"]})
            decisions.append({
                "scope": "CROSS_SUBSYSTEM",
                "integration_status": INTEGRATION_HELD,
                "relationship": rel["relationship"],
                "resources": [rel["resource_a"], rel["resource_b"]],
                "subsystems": sorted({rel["subsystem_a"], rel["subsystem_b"]}),
                "reason": ("both resources are ACTIVE and may or may not be one physical "
                           "interface; " + rel["reason"]),
                "preferred_model": SYS12_PREFERRED_MODEL,
            })

    for per in inventory.get("per_subsystem") or []:
        for collision in per.get("within_subsystem_bind_collisions") or []:
            ids = [f"{per['subsystem_id']}::{r}" for r in collision["rows"]]
            stopped.update(ids)
            decisions.append({
                "scope": "WITHIN_SUBSYSTEM",
                "integration_status": INTEGRATION_STOPPED,
                "relationship": REL_DRIVER_CONFLICT,
                "resources": ids,
                "subsystems": [per["subsystem_id"]],
                "bind_target": collision["bind_target"],
                "reason": ("two ACTIVE rows of this subsystem's own connectivity matrix "
                           f"claim bind target {collision['bind_target']!r} "
                           "(connectivity.find_active_bind_target_collisions)"),
                "preferred_model": SYS12_PREFERRED_MODEL,
            })

    decisions.sort(key=lambda d: (d["integration_status"], d["scope"], d["resources"]))
    return {
        "decisions": decisions,
        "stopped_resource_ids": sorted(stopped),
        "held_resource_ids": sorted(held - stopped),
        "automatic_integration_allowed": not stopped and not held,
        "rule": ("SYS-12 -- two active agents must never independently drive the same "
                 "physical interface; on DRIVER_CONFLICT stop automatic integration of "
                 "that resource until ownership is resolved"),
        "preferred_model": SYS12_PREFERRED_MODEL,
    }


def escalate_configuration_conflicts(relationships: Sequence[Mapping[str, Any]],
                                     resources_by_id: Mapping[str, Mapping[str, Any]],
                                     *, question_store: Any = None,
                                     now=None) -> List[Dict[str, Any]]:
    """Route each CONFIGURATION_CONFLICT through the EXISTING 9-level Source
    Authority Order rather than inventing a second conflict resolver.

    Both claims come from a live `vip_config` dump, which is a real simulation
    artifact -- authority tier 1. Two tier-1 claims that disagree is exactly
    `resolve_conflict()`'s UNDECIDABLE_SAME_AUTHORITY case, and its answer is
    the right one: the order cannot break a tie inside one level, so a human
    must. Producing a "winner" here would be the overreach `source_authority`
    exists to prevent.

    `question_store` (a `question_queue.QuestionQueueStore` or a project-root
    path): when supplied, every real conflict this produces is additionally
    filed through `source_authority.escalate_conflict()` -- the SAME channel
    `system_topology_analysis.escalate_address_conflicts()`,
    `address_map_verifier.escalate_doc_disagreements()` and
    `reference_pattern_audit.escalate_asymmetries()` already use, never a
    second escalation mechanism. `source_authority.py`'s own docstring calls
    escalating a RESOLVED or UNDECIDABLE_SAME_AUTHORITY verdict "mandatory,
    not advisory" -- before this, this function only ever produced the first
    half (the resolved verdict) and never actually escalated it. The
    persisted record's own real id is carried back as this entry's
    `question_id`, the exact field `system_phase1_report.
    collect_open_questions()` already reads from this list and, before this,
    never received. Omitting `question_store` (the default) keeps this
    function's return value byte-identical to before.
    """
    out: List[Dict[str, Any]] = []
    for rel in relationships:
        if rel["relationship"] != REL_CONFIGURATION_CONFLICT:
            continue
        a = resources_by_id[rel["resource_a"]]
        b = resources_by_id[rel["resource_b"]]
        differing = rel["comparison"]["signals"]["configuration"].get("differing") or []
        for entry in differing:
            claims = [
                sa.SourceClaim(
                    source="simulation_result",
                    claim=f"{entry['field']}={entry['a']!r}",
                    evidence_path=f"{a['evidence'][0]} (vip_config dump, "
                                  f"{a['owner_subsystem']})",
                    detail={"subsystem": a["owner_subsystem"],
                            "resource_id": a["resource_id"]}),
                sa.SourceClaim(
                    source="simulation_result",
                    claim=f"{entry['field']}={entry['b']!r}",
                    evidence_path=f"{b['evidence'][0]} (vip_config dump, "
                                  f"{b['owner_subsystem']})",
                    detail={"subsystem": b["owner_subsystem"],
                            "resource_id": b["resource_id"]}),
            ]
            conflict = sa.resolve_conflict(claims)
            record: Dict[str, Any] = {
                "resource_a": rel["resource_a"], "resource_b": rel["resource_b"],
                "field": entry["field"],
                "conflict": conflict,
            }
            if question_store is not None:
                filed = sa.escalate_conflict(
                    question_store, conflict, domain="dut",
                    subject=(f"SYS-11 configuration conflict on {entry['field']} between "
                             f"{rel['resource_a']} and {rel['resource_b']}"),
                    context_path=f"{rel['resource_a']}::{rel['resource_b']}::{entry['field']}",
                    extra_context={"affects_spec_intent": True,
                                   "sys11_configuration_conflict": True},
                    now=now)
                if filed is not None:
                    record["question_id"] = filed.get("id")
            out.append(record)
    return out


# ===========================================================================
# SYS-13 / SYS-14: shared VIP promotion, subsystem ownership preservation
# ===========================================================================

def _is_subsystem_specific(resource: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-14's test: is this a subsystem-specific protocol VIP that must stay
    inside its subsystem? Matched against the protocol, the owner subsystem's
    own name and the resource hierarchy, with the matched token recorded."""
    for field_name in ("protocol", "owner_subsystem", "hierarchy", "resource_id"):
        low = str(resource.get(field_name) or "").lower()
        hit = next((t for t in SUBSYSTEM_SPECIFIC_PROTOCOL_TOKENS if t in low), "")
        if hit:
            return {"subsystem_specific": True, "matched_token": hit,
                    "matched_field": field_name}
    return {"subsystem_specific": False, "matched_token": "", "matched_field": ""}


def evaluate_shared_vip_promotion(relationships: Sequence[Mapping[str, Any]],
                                  resources_by_id: Mapping[str, Mapping[str, Any]],
                                  conflict_rule: Mapping[str, Any],
                                  ) -> List[Dict[str, Any]]:
    """SYS-13: "Evaluate genuinely shared resources for System-Level ownership
    ... Require physical/logical equivalence evidence; matching names are
    insufficient."

    Every one of those three clauses is a real gate here:

      * "genuinely shared" -- the pair must have a SYS-11 relationship that
        asserts sharing at all.
      * "for System-Level ownership" -- the resource type must be in
        SHARED_SOC_INFRASTRUCTURE_TYPES, which is SYS-13's own list, and must
        not be a subsystem-specific protocol VIP (SYS-14).
      * "matching names are insufficient" -- a pair whose relationship is
        UNKNOWN because the evidence was name-only can never be promoted; it
        is BLOCKED_PENDING_EQUIVALENCE with the specific artifact that would
        settle it.

    A DRIVER_CONFLICT is BLOCKED_PENDING_OWNERSHIP, not promoted: SYS-12 stops
    automatic integration of that resource first, and a promotion decision on
    a resource whose ownership is unresolved would step straight past that stop.

    EVERY result is a RECOMMENDATION. Promoting a resource for real -- creating
    a System shared agent and routing subsystem requests through it -- is
    SYS-40 and requires a separate explicit human approval.
    """
    stopped = set(conflict_rule.get("stopped_resource_ids") or [])
    out: List[Dict[str, Any]] = []
    for rel in relationships:
        a = resources_by_id[rel["resource_a"]]
        b = resources_by_id[rel["resource_b"]]
        types = {a["resource_type"], b["resource_type"]}
        specific_a, specific_b = _is_subsystem_specific(a), _is_subsystem_specific(b)

        if specific_a["subsystem_specific"] or specific_b["subsystem_specific"]:
            hit = specific_a if specific_a["subsystem_specific"] else specific_b
            decision, reason = NOT_ELIGIBLE_SUBSYSTEM_SPECIFIC, (
                f"SYS-14: subsystem-specific protocol VIP (token {hit['matched_token']!r} "
                f"in {hit['matched_field']}) stays inside its subsystem; only shared SoC "
                "infrastructure is promoted")
        elif not (types & SHARED_SOC_INFRASTRUCTURE_TYPES) or len(types) != 1:
            decision, reason = NOT_ELIGIBLE_NOT_SOC_INFRASTRUCTURE, (
                f"resource types {sorted(types)} are not one entry of SYS-13's promotable "
                f"list {sorted(SHARED_SOC_INFRASTRUCTURE_TYPES)}")
        elif rel["relationship"] == REL_INDEPENDENT:
            decision, reason = KEEP_INDEPENDENT, (
                "SYS-11 classified these as INDEPENDENT_RESOURCE -- there is nothing "
                "shared to promote")
        elif (rel["resource_a"] in stopped or rel["resource_b"] in stopped
              or rel["relationship"] == REL_DRIVER_CONFLICT):
            decision, reason = BLOCKED_PENDING_OWNERSHIP, (
                "SYS-12 stopped automatic integration of this resource until ownership is "
                "resolved; a promotion decision may not step past that stop")
        elif rel["relationship"] in (REL_SAME_PHYSICAL, REL_MONITOR_ONLY_DUPLICATE):
            decision, reason = PROMOTE_TO_SYSTEM_SHARED, (
                f"physical equivalence established by {rel['physical_identity_evidence']}, "
                f"relationship {rel['relationship']}, and the type is SYS-13 shared SoC "
                "infrastructure. RECOMMENDATION ONLY -- creating the shared agent is SYS-40")
        elif rel["relationship"] == REL_CONFIGURATION_CONFLICT:
            decision, reason = BLOCKED_PENDING_EQUIVALENCE, (
                "the two environments configure this same physical resource differently; "
                "one shared agent cannot hold two configurations. Resolve the "
                "configuration disagreement (escalated through source_authority) first")
        else:
            decision, reason = BLOCKED_PENDING_EQUIVALENCE, (
                f"relationship {rel['relationship']} does not establish physical or logical "
                f"equivalence"
                + (" -- the agreeing evidence was NAME-ONLY, and SYS-13 states that "
                   "matching names are insufficient" if rel["name_evidence_only"] else "")
                + ". A declared physical-interface id, a shared bind target, or a live "
                  "vip_config dump on both sides would settle it")

        out.append({
            "resource_a": rel["resource_a"], "resource_b": rel["resource_b"],
            "subsystems": sorted({rel["subsystem_a"], rel["subsystem_b"]}),
            "resource_types": sorted(types),
            "relationship": rel["relationship"],
            "decision": decision,
            "reason": reason,
            "physical_identity_evidence": rel["physical_identity_evidence"],
            "logical_identity_evidence": rel["logical_identity_evidence"],
            "recommendation_only": True,
            "implementation_phase": "SYS-40 (requires separate explicit human approval)",
        })
    out.sort(key=lambda p: (p["decision"], p["resource_a"], p["resource_b"]))
    return out


def apply_ownership_preservation(inventory: Mapping[str, Any],
                                 promotions: Sequence[Mapping[str, Any]],
                                 ) -> Dict[str, Any]:
    """SYS-14: "Keep subsystem-specific VIP within its subsystem where
    possible. Only shared SoC infrastructure should be promoted. Avoid
    unnecessary refactoring."

    Preservation is recorded as a PER-RESOURCE DECISION with its reason, not as
    a property of doing nothing. Today's composer preserves everything because
    it never promotes anything at all; that satisfies SYS-14's letter
    vacuously. A resource that stays in its subsystem BECAUSE it is a PCIe VIP
    and not SoC infrastructure is a different, checkable statement.

    Raises when a subsystem-specific protocol VIP appears in the promotion set:
    that is SYS-14's rule being violated, and a rule that only warns is not a
    rule.
    """
    promoted_ids = {rid for p in promotions if p["decision"] == PROMOTE_TO_SYSTEM_SHARED
                    for rid in (p["resource_a"], p["resource_b"])}
    by_id = {r["resource_id"]: r for r in inventory["resources"]}

    violations = []
    for rid in sorted(promoted_ids):
        specific = _is_subsystem_specific(by_id[rid])
        if specific["subsystem_specific"]:
            violations.append({"resource_id": rid, **specific})
    if violations:
        raise SystemResourceInventoryError("SYS14_SUBSYSTEM_SPECIFIC_VIP_PROMOTED", {
            "violations": violations,
            "hint": "SYS-14: only shared SoC infrastructure may be promoted; a "
                    "subsystem-specific protocol VIP stays inside its subsystem"})

    decisions = []
    for resource in inventory["resources"]:
        rid = resource["resource_id"]
        specific = _is_subsystem_specific(resource)
        if rid in promoted_ids:
            verdict, reason = OWNERSHIP_PROMOTION_CANDIDATE, (
                "recommended for System-Level shared ownership on physical-equivalence "
                "evidence (SYS-13); the recommendation is not an action")
        elif specific["subsystem_specific"]:
            verdict, reason = OWNERSHIP_KEEP_IN_SUBSYSTEM, (
                f"subsystem-specific protocol VIP (token {specific['matched_token']!r} in "
                f"{specific['matched_field']}) -- SYS-14 keeps it inside "
                f"{resource['owner_subsystem']}")
        elif resource["resource_type"] not in SHARED_SOC_INFRASTRUCTURE_TYPES:
            verdict, reason = OWNERSHIP_KEEP_IN_SUBSYSTEM, (
                f"type {resource['resource_type']} is not on SYS-13's shared SoC "
                "infrastructure list")
        else:
            verdict, reason = OWNERSHIP_KEEP_IN_SUBSYSTEM, (
                "shared SoC infrastructure by type, but no cross-subsystem duplicate of it "
                "was established, so there is nothing to share it WITH")
        decisions.append({
            "resource_id": rid,
            "owner_subsystem": resource["owner_subsystem"],
            "resource_type": resource["resource_type"],
            "ownership": verdict,
            "reason": reason,
            # SYS-14's "avoid unnecessary refactoring", as a field rather than
            # a promise: nothing in this workflow proposes restructuring a
            # subsystem environment, and the report says so per resource.
            "refactoring_proposed": False,
        })
    decisions.sort(key=lambda d: d["resource_id"])
    return {
        "decisions": decisions,
        "kept_in_subsystem": sum(1 for d in decisions
                                 if d["ownership"] == OWNERSHIP_KEEP_IN_SUBSYSTEM),
        "promotion_candidates": sorted(promoted_ids),
        "refactoring_proposed_anywhere": False,
        "rule": ("SYS-14 -- keep subsystem-specific VIP within its subsystem; only shared "
                 "SoC infrastructure is promoted; avoid unnecessary refactoring"),
    }


# ===========================================================================
# Orchestration
# ===========================================================================

PHASE_BOUNDARY = (
    "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- SYS-9..SYS-14 inventory, duplicate "
    "detection, relationship classification, conflict rule, promotion evaluation and "
    "ownership preservation are analysis and planning only. No System-Level "
    "environment, System command.txt, System Virtual Sequencer, shared agent or "
    "command routing/adapter is generated, and no subsystem environment is modified. "
    "That is SYS-40 and requires a separate explicit human approval.")


def build_cross_subsystem_resource_analysis(
        sources: Sequence[SubsystemResourceSources], *,
        contract_set: Optional[Mapping[str, Any]] = None,
        question_store: Any = None, now=None) -> Dict[str, Any]:
    """SYS-9 -> SYS-10 -> SYS-11 -> SYS-12 -> SYS-13 -> SYS-14 over one
    selected subsystem set. Reads only; writes nothing anywhere -- UNLESS
    `question_store` is supplied, in which case a real SYS-11 configuration
    conflict is additionally filed into the question queue via
    `escalate_configuration_conflicts()`'s own `question_store` argument.
    Omitting it (the default) keeps this function's behavior unchanged."""
    inventory = build_cross_subsystem_inventory(sources, contract_set=contract_set)
    by_id = {r["resource_id"]: r for r in inventory["resources"]}
    comparisons = detect_duplicate_resources(inventory, contract_set=contract_set)
    relationships = classify_relationships(comparisons, by_id)
    conflict_rule = apply_active_driver_conflict_rule(relationships, inventory)
    escalations = escalate_configuration_conflicts(
        relationships, by_id, question_store=question_store, now=now)
    promotions = evaluate_shared_vip_promotion(relationships, by_id, conflict_rule)
    ownership = apply_ownership_preservation(inventory, promotions)

    by_relationship: Dict[str, int] = {c: 0 for c in RELATIONSHIP_CLASSES}
    for rel in relationships:
        by_relationship[rel["relationship"]] += 1
    by_decision: Dict[str, int] = {d: 0 for d in PROMOTION_DECISIONS}
    for promotion in promotions:
        by_decision[promotion["decision"]] += 1

    return {
        "inventory": inventory,
        "duplicate_candidates": comparisons,
        "relationships": relationships,
        "active_driver_conflict_rule": conflict_rule,
        "configuration_conflict_escalations": escalations,
        "promotion_evaluation": promotions,
        "ownership_preservation": ownership,
        "summary": {
            "subsystems": inventory["subsystems"],
            "resource_count": inventory["resource_count"],
            "resources_by_owner": inventory["resources_by_owner"],
            "duplicate_candidate_count": len(comparisons),
            "relationships_by_class": by_relationship,
            "driver_conflicts": by_relationship[REL_DRIVER_CONFLICT],
            "stopped_resources": len(conflict_rule["stopped_resource_ids"]),
            "held_resources": len(conflict_rule["held_resource_ids"]),
            "automatic_integration_allowed": conflict_rule["automatic_integration_allowed"],
            "promotions_by_decision": by_decision,
            "promotion_candidates": len(ownership["promotion_candidates"]),
        },
        "artifacts_modified": False,
        "phase_boundary": PHASE_BOUNDARY,
    }


def analyze_selected_subsystem_resources(root, selected: Sequence[str], *,
                                         declared: Optional[Mapping[str, Any]] = None,
                                         knowledge_center_client: Any = None,
                                         inventory_overlay_path=None,
                                         question_store: Any = None,
                                         now=None,
                                         ) -> Dict[str, Any]:
    """Front door: SYS-1 selection -> SYS-5..8 per-subsystem analyses ->
    SYS-9..14 cross-subsystem resource analysis.

    The SYS-5..8 layer is reused whole rather than re-implemented: it already
    resolves each subsystem's environment root and env.manifest.json, enforces
    SYS-5's isolation rule, and produces the SYS-8 contract set this module
    needs for its driver-ownership signal.

    `question_store`/`now` pass straight through to
    `build_cross_subsystem_resource_analysis()`; omitted (the default), this
    front door's own real callers -- the two SYSTEM_LEVEL gate scripts and the
    SoC composer, via `real_cross_subsystem_findings()` below -- keep filing
    nothing, exactly as before this parameter existed.
    """
    from . import subsystem_architecture_analysis as saa
    declared = dict(declared or {})
    analysis = saa.analyze_selected_subsystems(
        root, selected, declared=declared, knowledge_center_client=knowledge_center_client,
        inventory_overlay_path=inventory_overlay_path)
    registry = {str(r["subsystem"]): r for r in
                analysis["selection"]["discovery"]["candidates"]}
    sources = [
        sources_from_analysis(
            result,
            declared=declared.get(result["subsystem_id"]),
            registry_entry={"release_sha": registry.get(result["subsystem_id"], {})
                            .get("version_sha", "")})
        for result in analysis["synthesis"]["per_subsystem"]]
    resource_analysis = build_cross_subsystem_resource_analysis(
        sources, contract_set=analysis["synthesis"]["contract_set"],
        question_store=question_store, now=now)
    return {"selection": analysis["selection"], "synthesis": analysis["synthesis"],
            "resource_analysis": resource_analysis}


# ===========================================================================
# SYSTEM_LEVEL gate / composer cross-check (2026-09-05)
# ===========================================================================
#
# WHY THIS LIVES HERE. Everything above is reachable only from human-typed
# `dv-harness system-*` CLI verbs. The things that actually DECIDE whether a
# composed system-level environment is allowed to exist -- the fourteen
# tools/verification_flow/system_level_*.py gate scripts wired into
# gates.py's STAGE_GATES["SYSTEM_LEVEL"], and
# uvm_generator/soc_environment_composer.compose_soc_environment() -- imported
# none of it: every one of those gates was a pure JSON-shape check over an
# agent's OWN evidence text, so a hand-typed "shared_resources: []" passed
# while the real analysis above, run over the same subsystems, found two
# ACTIVE agents driving one physical interface.
#
# These two functions are that missing wire, and nothing more. They add no new
# analysis: `real_cross_subsystem_findings()` calls
# `analyze_selected_subsystem_resources()` above (which is itself the SYS-1 ->
# SYS-5..8 -> SYS-9..14 front door, so SYS-1's refusal to analyze a set the
# user did not select is not bypassed), and the two `crosscheck_*` functions
# are pure comparisons of an agent's declaration against what that real
# analysis found.
#
# HUMAN ARBITRATION IS PRESERVED. A DRIVER_CONFLICT still STOPS at BLOCKED and
# still needs a human to decide which subsystem owns the interface --
# `apply_active_driver_conflict_rule()`'s SYS12_PREFERRED_MODEL is carried
# through as text for that human to read. Nothing here picks a winner, resolves
# a conflict, or promotes a resource: the only thing that changed is that a
# conflict now blocks a gate instead of being invisible to it.

CROSSCHECK_AVAILABLE = "TRACK_B_ANALYSIS_AVAILABLE"
CROSSCHECK_UNAVAILABLE = "TRACK_B_ANALYSIS_UNAVAILABLE"

#: Cross-check verdicts. FAIL is reserved for a declaration the real analysis
#: CONTRADICTS -- never for a declaration it merely cannot corroborate.
CROSSCHECK_PASS = "PASS"
CROSSCHECK_FAIL = "FAIL"
CROSSCHECK_SKIPPED = "SKIPPED_ANALYSIS_UNAVAILABLE"

#: The relationship classes that mean "these two subsystems really do reach the
#: same resource" -- the ones an agent claiming an empty `shared_resources`
#: list is contradicting. MONITOR_ONLY_DUPLICATE is deliberately excluded: two
#: passive monitors on one interface share an observation point, not a
#: contended resource, and neither needs an arbitration policy.
SHARED_RELATIONSHIP_CLASSES: tuple = (REL_SAME_PHYSICAL, REL_SHARED_LOGICAL)


#: Wall-clock budget a GATE gives this analysis, in seconds. gates.run_gate()
#: runs every gate script with `timeout=30` and does NOT catch the resulting
#: subprocess.TimeoutExpired -- an analysis that outran that ceiling would turn
#: a stage evaluation into a crash. 20 leaves margin for interpreter start,
#: JSON I/O and the gate's own layer-1 checks. Overrunning it is reported as
#: ANALYSIS_TIMED_OUT (i.e. "not checked"), never as a clear result.
GATE_CROSSCHECK_BUDGET_SECONDS = 20.0


def real_cross_subsystem_findings(root, selected: Optional[Sequence[str]] = None, *,
                                  declared: Optional[Mapping[str, Any]] = None,
                                  budget_seconds: Optional[float] = None,
                                  ) -> Dict[str, Any]:
    """Run the REAL SYS-9..SYS-14 cross-subsystem analysis for a project root
    and flatten it to the handful of facts a gate script or the SoC composer
    needs to check a declaration against.

    `selected` defaults to the REAL registered subsystem set
    (`environment_mode_router.read_registered_subsystem_names()`, written only
    by engine.py's `_persist_subsystem_registry_entry()` on a gate-validated
    SIGNOFF PASS) -- harness evidence, never the caller's claim.

    `budget_seconds` bounds the analysis's wall clock; the two gate scripts
    pass GATE_CROSSCHECK_BUDGET_SECONDS because they run under run_gate()'s own
    30s subprocess timeout. The default None means "no budget", which is what
    the composer wants: a composition is not on a gate's clock, and silently
    skipping the check that stops it composing over a driver conflict would be
    the worse failure.

    Returns `status` CROSSCHECK_UNAVAILABLE, with a concrete `reason`, whenever
    the analysis could not be run over real evidence: fewer than two subsystems
    resolve, SYS-1 refuses the selection (typically because a selected
    subsystem's environment is not on disk to analyze), the analysis raises, or
    it outran its budget. UNAVAILABLE is an honest "nothing was checked", never
    a silent "clear" -- the callers below treat it as SKIPPED, not PASS. The
    broad exception catch is deliberate and bounded: this is a cross-check
    bolted onto verdicts that already stand on their own, so an unexpected
    failure inside it must degrade to "not checked" rather than crash a gate
    subprocess or a composition.
    """
    if budget_seconds is None:
        return _cross_subsystem_findings(root, selected, declared)

    import threading
    box: List[Dict[str, Any]] = []
    # A daemon thread: if the analysis outruns the budget it is abandoned
    # rather than joined, and the interpreter is free to exit around it. It
    # only ever READS (analyze_selected_subsystem_resources writes nothing
    # anywhere), so an abandoned one cannot leave a half-written artifact.
    worker = threading.Thread(
        target=lambda: box.append(_cross_subsystem_findings(root, selected, declared)),
        daemon=True)
    worker.start()
    worker.join(budget_seconds)
    if box:
        return box[0]
    return {"status": CROSSCHECK_UNAVAILABLE, "reason": "ANALYSIS_TIMED_OUT",
            "subsystems": [], "budget_seconds": budget_seconds}


def _cross_subsystem_findings(root, selected: Optional[Sequence[str]],
                              declared: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The analysis itself. Split out only so the budget wrapper above has one
    callable to run; every behaviour is documented on the public function."""
    root = Path(root)
    unavailable = lambda reason, **detail: dict(  # noqa: E731 - one shape, four call sites
        {"status": CROSSCHECK_UNAVAILABLE, "reason": reason, "subsystems": []}, **detail)

    try:
        from .environment_mode_router import read_registered_subsystem_names
        names = [str(s) for s in (selected if selected is not None
                                  else read_registered_subsystem_names(root)) if str(s).strip()]
    except Exception as exc:  # pragma: no cover - unreadable/malformed registry
        return unavailable("REGISTRY_UNREADABLE", detail=f"{type(exc).__name__}: {exc}")

    if len(names) < 2:
        return unavailable("FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE", subsystems=names)

    try:
        result = analyze_selected_subsystem_resources(root, names, declared=declared)
    except Exception as exc:
        return unavailable("ANALYSIS_FAILED", subsystems=names,
                           detail=f"{type(exc).__name__}: {exc}")

    selection = result["selection"]
    if not selection.get("selection_admissible"):
        # An analysis over environments that are not really on disk proves
        # nothing about them; saying so is the honest verdict.
        return unavailable(selection.get("refusal_reason") or "SELECTION_NOT_ADMISSIBLE",
                           subsystems=names,
                           not_ready=[r["subsystem"] for r in selection.get("not_ready") or []])

    analysis = result["resource_analysis"]
    rule = analysis["active_driver_conflict_rule"]
    shared = [rel for rel in analysis["relationships"]
              if rel["relationship"] in SHARED_RELATIONSHIP_CLASSES]
    return {
        "status": CROSSCHECK_AVAILABLE,
        "subsystems": names,
        "resource_count": analysis["summary"]["resource_count"],
        "driver_conflicts": analysis["summary"]["driver_conflicts"],
        "automatic_integration_allowed": rule["automatic_integration_allowed"],
        "stopped_resource_ids": list(rule["stopped_resource_ids"]),
        "held_resource_ids": list(rule["held_resource_ids"]),
        "blocking_decisions": [d for d in rule["decisions"]
                               if d["integration_status"] != INTEGRATION_ALLOWED],
        "shared_resource_ids": sorted({rid for rel in shared
                                       for rid in (rel["resource_a"], rel["resource_b"])}),
        "shared_relationships": [
            {"resource_a": rel["resource_a"], "resource_b": rel["resource_b"],
             "relationship": rel["relationship"], "reason": rel["reason"]}
            for rel in shared],
        "preferred_model": rule["preferred_model"],
    }


def _blocked_detail(findings: Mapping[str, Any]) -> Dict[str, Any]:
    """The shared FAIL payload for a Track-B integration block. Names the real
    resources and carries SYS-12's preferred model as the text a HUMAN reads
    before arbitrating -- this is a stop, not a resolution."""
    return {
        "subsystems": findings["subsystems"],
        "driver_conflicts": findings["driver_conflicts"],
        "stopped_resource_ids": findings["stopped_resource_ids"],
        "held_resource_ids": findings["held_resource_ids"],
        "blocking_decisions": findings["blocking_decisions"],
        "human_arbitration_required": True,
        "preferred_model": findings["preferred_model"],
    }


def crosscheck_declared_contention_plan(declared_plan: Mapping[str, Any],
                                        findings: Mapping[str, Any]) -> Dict[str, Any]:
    """Hold `system_level_resource_contention_gate`'s agent-supplied plan
    against `real_cross_subsystem_findings()`.

    Two FAIL conditions, both flat contradictions rather than judgement calls:

      1. `ACTIVE_DRIVER_CONFLICT_UNRESOLVED` -- the real analysis stopped or
         held automatic integration (two ACTIVE agents on one physical
         interface, or an unproven-but-both-active pair). No contention policy
         an agent can type resolves that; it needs a human to decide ownership.
      2. `SHARED_RESOURCES_CONTRADICTED` -- the plan declares NO shared
         resources at all while the real analysis found SAME_PHYSICAL_RESOURCE
         / SHARED_LOGICAL_RESOURCE relationships between the composed
         subsystems. This is the hand-typed "all clear" case.

    A NON-empty `shared_resources` list whose names do not line up with the
    real resource ids is reported as `unmatched_shared_resource_ids` and does
    NOT fail: an agent names resources in project vocabulary ("DDR",
    "APB_BUS") while a resource id is `SUBSYS::hierarchy::interface`, and
    failing on that mismatch would be a naming heuristic pretending to be
    evidence.
    """
    if findings.get("status") != CROSSCHECK_AVAILABLE:
        return {"status": CROSSCHECK_SKIPPED, "reason": findings.get("reason", ""),
                "subsystems": findings.get("subsystems", [])}

    if not findings["automatic_integration_allowed"]:
        return {"status": CROSSCHECK_FAIL, "reason": "ACTIVE_DRIVER_CONFLICT_UNRESOLVED",
                **_blocked_detail(findings)}

    declared_shared = [str(r) for r in (declared_plan.get("shared_resources") or [])]
    if findings["shared_resource_ids"] and not declared_shared:
        return {"status": CROSSCHECK_FAIL, "reason": "SHARED_RESOURCES_CONTRADICTED",
                "subsystems": findings["subsystems"],
                "declared_shared_resources": declared_shared,
                "real_shared_resource_ids": findings["shared_resource_ids"],
                "shared_relationships": findings["shared_relationships"]}

    tokens = [t.lower() for t in declared_shared]
    unmatched = [rid for rid in findings["shared_resource_ids"]
                 if not any(t and t in rid.lower() for t in tokens)]
    return {"status": CROSSCHECK_PASS, "subsystems": findings["subsystems"],
            "real_shared_resource_ids": findings["shared_resource_ids"],
            "unmatched_shared_resource_ids": unmatched}


def crosscheck_declared_composition(declared_composition: Mapping[str, Any],
                                    findings: Mapping[str, Any]) -> Dict[str, Any]:
    """Hold `system_level_composition_gate`'s agent-supplied composition
    against `real_cross_subsystem_findings()`.

    That gate's per-subsystem `interface_compatibility` / `clock_reset_
    compatibility` "PASS" strings are the agent's own assertion that these
    subsystems can be composed. The one thing the real cross-subsystem analysis
    can flatly contradict is exactly that: an unresolved active-driver
    ownership conflict between two of the composed subsystems means the set is
    NOT composable yet, whatever the evidence block says. Fails with
    `ACTIVE_DRIVER_CONFLICT_UNRESOLVED` and stops at BLOCKED pending human
    arbitration.

    Only subsystems this composition actually names are analyzed, so a conflict
    between two registered subsystems that this composition does not include
    cannot block it.
    """
    if findings.get("status") != CROSSCHECK_AVAILABLE:
        return {"status": CROSSCHECK_SKIPPED, "reason": findings.get("reason", ""),
                "subsystems": findings.get("subsystems", [])}
    if not findings["automatic_integration_allowed"]:
        return {"status": CROSSCHECK_FAIL, "reason": "ACTIVE_DRIVER_CONFLICT_UNRESOLVED",
                "declared_subsystems": [str(s.get("name")) for s
                                        in (declared_composition.get("selected_subsystems") or [])
                                        if isinstance(s, Mapping)],
                **_blocked_detail(findings)}
    return {"status": CROSSCHECK_PASS, "subsystems": findings["subsystems"],
            "real_shared_resource_ids": findings["shared_resource_ids"]}


# ===========================================================================
# Reporting
# ===========================================================================

def render_resource_inventory_table(inventory: Mapping[str, Any]) -> str:
    """SYS-9's inventory as markdown. OWNER_SUBSYSTEM is deliberately the
    SECOND column: it is the field the per-subsystem connectivity matrix
    cannot carry, and the one that makes every row below unambiguous."""
    lines = ["| RESOURCE_ID | OWNER_SUBSYSTEM | TYPE | PROTOCOL | ROLE | ACTIVE/PASSIVE | "
             "SHAREABLE | EXCLUSIVE | CLOCK | RESET | ADDRESS DOMAIN | CONFIDENCE |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in inventory["resources"]:
        domain = r["address_domain"]
        domain_text = (f"{domain['status']}({len(domain['regions'])})"
                       if domain["regions"] else domain["status"])
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            r["resource_id"], r["owner_subsystem"], r["resource_type"], r["protocol"],
            r["role"], r["active_passive"] or UNRESOLVED, r["shareable"], r["exclusive"],
            r["clock"], r["reset"], domain_text, r["confidence"]))
    return "\n".join(lines)


def render_relationship_table(relationships: Sequence[Mapping[str, Any]]) -> str:
    lines = ["| RESOURCE A | RESOURCE B | RELATIONSHIP | PHYSICAL EVIDENCE | REASON |",
             "|---|---|---|---|---|"]
    for rel in relationships:
        lines.append("| {} | {} | {} | {} | {} |".format(
            rel["resource_a"], rel["resource_b"], rel["relationship"],
            ",".join(rel["physical_identity_evidence"]) or "none",
            rel["reason"].replace("\n", " ")[:180]))
    return "\n".join(lines)


def format_resource_report(analysis: Mapping[str, Any]) -> str:
    """The SYS-9..SYS-14 deliverable. Reporting only -- this function emits no
    SystemVerilog, no command.txt and no routing table."""
    summary = analysis["summary"]
    out = ["# CROSS-SUBSYSTEM RESOURCE INVENTORY AND DEDUPLICATION (SYS-9..SYS-14)", "",
           f"- subsystems: {summary['subsystems']}",
           f"- resources inventoried: {summary['resource_count']} "
           f"({summary['resources_by_owner']})",
           f"- duplicate candidates compared: {summary['duplicate_candidate_count']}",
           f"- driver conflicts: {summary['driver_conflicts']}; "
           f"resources stopped: {summary['stopped_resources']}; "
           f"held: {summary['held_resources']}",
           f"- automatic integration allowed: "
           f"{summary['automatic_integration_allowed']}", ""]

    for per in analysis["inventory"]["per_subsystem"]:
        check = per["matrix_self_check"]
        out.append(f"- {per['subsystem_id']}: matrix {per['connectivity_matrix_status']}, "
                   f"manifest {per['env_manifest_status']}, "
                   f"within-subsystem self-check {check.get('status')}"
                   + (f" ({check.get('reason')})" if check.get("status") != "PASS" else ""))
    out += ["", "## SYS-9 RESOURCE INVENTORY", "",
            render_resource_inventory_table(analysis["inventory"]), ""]

    out += ["## SYS-10 / SYS-11 RESOURCE RELATIONSHIPS", "",
            f"relationships by class: {summary['relationships_by_class']}", ""]
    if analysis["relationships"]:
        out += [render_relationship_table(analysis["relationships"]), ""]
    else:
        out += ["(no cross-subsystem pair had a single agreeing identity signal -- this is "
                "an absence of candidates, not a proof that no duplicate exists)", ""]

    rule = analysis["active_driver_conflict_rule"]
    out += ["## SYS-12 ACTIVE DRIVER CONFLICT RULE", "", rule["rule"], ""]
    for decision in rule["decisions"]:
        out.append(f"- [{decision['integration_status']}] {decision['scope']} "
                   f"{decision['resources']}: {decision['reason']}")
    if not rule["decisions"]:
        out.append("- no active-driver conflict detected across or within the selected "
                   "subsystems")
    out += ["", f"preferred model: {rule['preferred_model']}", ""]

    if analysis["configuration_conflict_escalations"]:
        out += ["## CONFIGURATION CONFLICTS ESCALATED (source_authority)", ""]
        for esc in analysis["configuration_conflict_escalations"]:
            out.append(f"- {esc['field']}: {esc['conflict']['verdict']} -- "
                       f"{esc['conflict']['rule']}")
        out.append("")

    out += ["## SYS-13 SHARED VIP PROMOTION EVALUATION", "",
            f"decisions: {summary['promotions_by_decision']}", ""]
    for promotion in analysis["promotion_evaluation"]:
        out.append(f"- [{promotion['decision']}] {promotion['resource_a']} vs "
                   f"{promotion['resource_b']}: {promotion['reason']}")
    if not analysis["promotion_evaluation"]:
        out.append("- no shared-resource candidate to evaluate")

    ownership = analysis["ownership_preservation"]
    out += ["", "## SYS-14 SUBSYSTEM OWNERSHIP PRESERVATION", "", ownership["rule"],
            f"- kept in their own subsystem: {ownership['kept_in_subsystem']}"
            f"/{len(ownership['decisions'])}",
            f"- promotion candidates: {ownership['promotion_candidates'] or 'none'}",
            f"- refactoring proposed anywhere: "
            f"{ownership['refactoring_proposed_anywhere']}",
            "", "## PHASE BOUNDARY", "", analysis["phase_boundary"]]
    return "\n".join(out)
