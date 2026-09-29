"""dv_harness/multi_vip_cooperation_architecting.py -- detects when a real
DUT+PHY topology genuinely requires MULTIPLE VIP instances to cooperate (a
host-side VIP plus a device-side VIP, for example) and architects their real
inter-relationship: a sequencing dependency between them, and whether they
may share ONE virtual sequencer directly or need an adapter -- all from real
topology evidence, never guessed.

WHY THIS IS DIFFERENT FROM `ip_ownership_conflict.py`
--------------------------------------------------------
`ip_ownership_conflict.py`'s own module docstring states its scope precisely:
"does THIS ONE subsystem's own environment declare a real VIP agent AND a
legacy hand-written BFM/driver BOTH active on the SAME interface/port?" --
a single-interface, VIP-vs-legacy-BFM CONFLICT check. It has no notion of
TWO real VIP instances at TWO DIFFERENT interfaces that legitimately both
belong there and must work TOGETHER -- a dual-role USB port switching
between host and device mode, a hub's upstream (device-facing) and
downstream (host-facing) ports, a bridge/repeater with two link partners.
That is a real, unanswered question this module closes: not "do two owners
collide on one interface" but "does this topology need two cooperating
owners across two interfaces, and if so, how do they relate."

REUSE OVER REINVENT -- every real fact comes from an existing, tested module
------------------------------------------------------------------------------
- VIP instance identity: `ip_ownership_conflict.real_vip_instances()`,
  imported verbatim -- the SAME `env.manifest.json` `vip_config.vip_instances`
  reader, excluding the SAME `connectivity.NO_VIP_MARKERS` entries. This
  module adds no second VIP-instance extractor.
- VIP role per interface: `connectivity.determine_role_from_port_direction()`,
  called on the interface's own real declared RTL port direction -- never
  guessed from an interface's name (a port named "host" whose direction says
  otherwise is not trusted over the direction).
- PHY-boundary bindability per interface: `phy_boundary.extract_phy_boundary()`
  / `decide_bind_location()`, called on real parsed RTL module ports (or
  accepted as an already-computed doc a caller supplies, the same duck-typed
  convention `verification_architecture.py` already established) -- this
  module derives no serial/parallel/MIXED boundary verdict of its own.
- Bind-chain / bridge classification: `verification_architecture.
  build_vip_bind_ir()` / `derive_wrapper_bridge_chain()`, called per
  cooperating pair's own real bind targets -- reused, not re-derived.
- Shared virtual-sequencer composition mode: `system_virtual_sequencer.
  build_subsystem_composition()`, called directly on the cooperating pair's
  own `VipBindIR` list. That module's own worst-wins DIRECT_HANDLE /
  ADAPTER_REQUIRED / COMPOSITION_UNDETERMINED / NOT_AVAILABLE fold IS the
  "shared virtual-sequencer needs" answer this task asks for -- this module
  does not invent a second composition-mode judgment, it treats the
  cooperating VIP pair as the "subsystem" that module's own API already
  accepts.
- Sequencing dependency: `runtime_event_registry.RuntimeEventRegistry` /
  `propagate()` -- this project's own real, tested stop-on-failure
  dependency-propagation engine, applied here to one real event per
  cooperating interface ("this interface's link is ready"). This module
  builds the events; it NEVER invents which one depends on which -- a real,
  cited `REQUIRES`/`WAITS_FOR`/`TRIGGERS`/`UNBLOCKS` relation between two
  interfaces' events must be supplied by the caller (a spec/programming-guide
  citation, an RTL mode-arbitration reference) before any sequencing
  dependency is reported; absent one, the honest answer is `NOT_DECLARED`,
  never a guessed ordering.
- Table rendering: `connectivity.render_markdown_table()`, this repo's one
  parameterized table renderer.

EVIDENCE TRUTH RULE -- COOPLING IS NEVER GUESSED FROM A NAME
-----------------------------------------------------------------
Two interfaces are never treated as cooperating merely because their
declared ids/labels sound related ("host"/"device"). Exactly one coupling
fact is DERIVED structurally, with no interpretation required: two
interfaces that declare the IDENTICAL real `bind_target` are, by definition,
the SAME physical DUT+PHY instance (`SHARED_PHY_INSTANCE`) -- the real
dual-role-port case. Every OTHER coupling kind (`SHARED_CLOCK_RESET_DOMAIN`,
`INTERNAL_SIGNAL_PATH`, `MODE_SELECT_SHARED_CONTROL`, `SHARED_ADDRESS_REGION`)
must be declared by the caller with a real, non-empty evidence citation (an
RTL file:line, a spec section, a register/mode-select reference) -- an
uncited coupling claim is refused at construction, matching this project's
own `arbitration_policy_ir.py`/`qos_policy_ir.py`/`security_policy_ir.py`
discipline for their own domains.

SCOPE BOUNDARY -- ARCHITECTURE RECORD ONLY, NEVER CONTENT OR ARBITRATION
----------------------------------------------------------------------------
This module authors no VIP API, sequence body, or RTL content (No
Golden-Reference Content Mining). `ADAPTER_REQUIRED` names the fact that an
adapter is needed and cites the real bridge evidence; it never invents what
that adapter's sequence should do. It picks no winner between two active
drivers -- that stays `ip_ownership_conflict.py`'s/`system_resource_
inventory.py`'s own territory, untouched here. It decides, approves and
arbitrates nothing: no build, job, or approval is touched, and there is
deliberately no stage gate -- a cooperation record is an input to a human's
architecture decision, never a substitute for one.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import phy_boundary as pb
from . import system_virtual_sequencer as svs
from . import verification_architecture as va
from .connectivity import ConnectivityError, determine_role_from_port_direction, render_markdown_table
from .ip_ownership_conflict import real_vip_instances
from .models import Status
from .runtime_event_registry import (
    EventRegistryError,
    EventRelationDecl,
    EventRelationType,
    EventStatus,
    RuntimeEventDef,
    RuntimeEventObservation,
    RuntimeEventRegistry,
)

SCHEMA_VERSION = "1.0"

#: The one auto-derivable coupling kind (`SHARED_PHY_INSTANCE`, from real
#: equal `bind_target`s) plus four kinds that must be caller-declared with a
#: real evidence citation -- see module docstring's Evidence Truth Rule
#: section. Closed and fixed -- an unrecognized kind is refused, never
#: silently accepted as a fifth flavor of "related somehow".
COUPLING_KINDS: tuple = (
    "SHARED_PHY_INSTANCE",
    "SHARED_CLOCK_RESET_DOMAIN",
    "INTERNAL_SIGNAL_PATH",
    "MODE_SELECT_SHARED_CONTROL",
    "SHARED_ADDRESS_REGION",
)

#: Per-interface "does this interface even legitimately need its own VIP"
#: verdict, derived from real PHY-boundary bindability
#: (`phy_boundary.decide_bind_location()`) plus whether a real VIP instance
#: is already matched to its bind target.
VIP_NEED_STATUSES: tuple = (
    "VIP_REQUIRED_BINDABLE",
    "VIP_REQUIRED_NOT_BOUND",
    "NOT_BINDABLE",
    "NOT_AVAILABLE",
)

#: Per-pair "does the topology genuinely require these two VIPs to
#: cooperate" verdict. `COOPERATION_REQUIRED` is the only status this module
#: will build a full sequencing/composition architecture for -- the other
#: two are honest "could not confirm" states, never silently promoted.
COOPERATION_STATUSES: tuple = (
    "COOPERATION_REQUIRED",
    "COOPERATION_UNCONFIRMED_NOT_BINDABLE",
    "COOPERATION_UNKNOWN_INSUFFICIENT_EVIDENCE",
)

#: Whether a `COOPERATION_REQUIRED` pair's own relationship (sequencing +
#: composition) has actually been architected from real evidence, or is
#: still missing a piece a human must supply.
ARCHITECTURE_STATUSES: tuple = (
    "ARCHITECTED",
    "ARCHITECTURE_INCOMPLETE",
    "NOT_APPLICABLE",
)

#: Whether a real, direct sequencing relation was declared between a given
#: pair's own two readiness events, and -- if so -- whether the current
#: (caller-supplied, real) observations show it currently blocked.
SEQUENCING_STATUSES: tuple = (
    "DECLARED_CLEAN",
    "DECLARED_BLOCKED",
    "NOT_DECLARED",
)

#: Whole-record rollup, worst-wins (see `derive_overall_status()`).
OVERALL_STATUSES: tuple = (
    "COOPERATION_DETECTED_ARCHITECTURE_INCOMPLETE",
    "COOPERATION_ARCHITECTED",
    "INSUFFICIENT_EVIDENCE",
    "NO_MULTI_VIP_COOPERATION_DETECTED",
)

#: Which `VIP_NEED_STATUSES` a pair may resolve `COOPERATION_REQUIRED` from.
_VIP_NEEDS_INDICATING_REQUIRED = frozenset({"VIP_REQUIRED_BINDABLE", "VIP_REQUIRED_NOT_BOUND"})

_EVENT_SUFFIX = "::VIP_LINK_READY"


class MultiVipCooperationError(ValueError):
    """A caller-supplied record violates this module's own vocabulary (an
    unrecognized coupling kind / relation type / status), or a structural
    precondition (an undeclared interface, an uncited coupling/sequencing
    claim, a duplicate interface id) is missing. Raised rather than silently
    coerced, matching `verification_architecture.py`'s/`system_virtual_
    sequencer.py`'s own fail-closed discipline."""


def _validate_vocab(value: Any, allowed: tuple, field_name: str, context: str) -> None:
    if value not in allowed:
        raise MultiVipCooperationError(
            f"{field_name} must be one of {list(allowed)}, got {value!r} (context: {context})"
        )


def _evidence(fact_source: str, **detail) -> dict:
    return {"fact_source": fact_source, "detail": detail}


def _nonempty(value: Any) -> bool:
    return bool(value) and bool(str(value).strip())


def _event_name(interface_id: str) -> str:
    return f"{interface_id}{_EVENT_SUFFIX}"


# ===========================================================================
# Declared inputs
# ===========================================================================

@dataclass
class DeclaredInterface:
    """One real DUT+PHY interface a caller declares as part of the topology
    under analysis. `dut_port_direction` and `bind_target` are the only two
    facts this module treats as load-bearing evidence; everything else is
    optional supporting evidence for a deeper PHY-boundary/chain evaluation.

    `phy_boundary_doc`: an already-computed `phy_boundary.extract_phy_
    boundary()` (or `.decide_bind_location()`-carrying) document, accepted
    directly when a caller already has one. Absent that, supplying
    `phy_module`+`controller_module`+the shared `rtl_modules` argument to
    `build_multi_vip_cooperation()` makes this module call
    `phy_boundary.extract_phy_boundary()` itself. Supplying neither leaves
    this interface's PHY-boundary evidence honestly `NOT_AVAILABLE`.
    """
    interface_id: str
    dut_port_direction: str
    bind_target: str
    clock: Optional[str] = None
    reset: Optional[str] = None
    phy_module: Optional[str] = None
    controller_module: Optional[str] = None
    hierarchy_hops: Optional[list] = None
    bind_tier: Optional[Any] = None
    phy_boundary_doc: Optional[dict] = None

    def __post_init__(self) -> None:
        if not _nonempty(self.interface_id):
            raise MultiVipCooperationError("a declared interface needs a non-empty interface_id")
        if not _nonempty(self.dut_port_direction):
            raise MultiVipCooperationError(
                f"interface {self.interface_id!r} declares no dut_port_direction -- a VIP role can "
                "never be derived without the real RTL port direction"
            )
        if not _nonempty(self.bind_target):
            raise MultiVipCooperationError(
                f"interface {self.interface_id!r} declares no bind_target -- there is no real "
                "instance path to match against a VIP instance or a PHY boundary"
            )
        if bool(self.phy_module) != bool(self.controller_module):
            raise MultiVipCooperationError(
                f"interface {self.interface_id!r} declares only one of phy_module/controller_module "
                "-- both or neither are required to extract a real PHY boundary"
            )


@dataclass
class CouplingFact:
    """One real, cited relationship between two declared interfaces.
    `derived=True` marks a fact this module computed structurally
    (`SHARED_PHY_INSTANCE` from equal `bind_target`s); every other fact must
    be caller-declared with a real, non-empty `evidence` citation."""
    interface_a: str
    interface_b: str
    coupling_kind: str
    evidence: str
    derived: bool = False

    def __post_init__(self) -> None:
        if self.interface_a == self.interface_b:
            raise MultiVipCooperationError(
                f"a coupling fact cannot relate interface {self.interface_a!r} to itself"
            )
        _validate_vocab(self.coupling_kind, COUPLING_KINDS, "coupling_kind",
                         f"{self.interface_a}/{self.interface_b}")
        if not _nonempty(self.evidence):
            raise MultiVipCooperationError(
                f"coupling fact between {self.interface_a!r} and {self.interface_b!r} "
                f"({self.coupling_kind}) carries no evidence citation -- an uncited coupling claim "
                "is refused, matching this project's Evidence Truth Rule"
            )

    def pair_key(self) -> Tuple[str, str]:
        return tuple(sorted((self.interface_a, self.interface_b)))  # type: ignore[return-value]

    def to_dict(self) -> dict:
        return {
            "interface_a": self.interface_a, "interface_b": self.interface_b,
            "coupling_kind": self.coupling_kind, "evidence": self.evidence, "derived": self.derived,
        }


# ===========================================================================
# Per-interface resolution
# ===========================================================================

def resolve_vip_role(dut_port_direction: str) -> str:
    """`connectivity.determine_role_from_port_direction()`, called and its
    real error wrapped -- never silently swallowed."""
    try:
        return determine_role_from_port_direction(dut_port_direction)
    except ConnectivityError as exc:
        raise MultiVipCooperationError(
            f"could not derive a VIP role from dut_port_direction {dut_port_direction!r}: {exc}"
        ) from exc


def resolve_phy_boundary(interface: DeclaredInterface, rtl_modules: Optional[list]) -> dict:
    """A real `phy_boundary.py`-shaped document for this interface: the
    caller's own pre-computed doc when supplied, else a real
    `phy_boundary.extract_phy_boundary()` call when the module pair + RTL
    are available, else an honest NOT_AVAILABLE stub -- never a guessed
    boundary."""
    if interface.phy_boundary_doc is not None:
        return interface.phy_boundary_doc
    if interface.phy_module and interface.controller_module and rtl_modules:
        return pb.extract_phy_boundary(rtl_modules, interface.phy_module, interface.controller_module)
    return {
        "status": "NOT_AVAILABLE",
        "reason": (
            "no phy_boundary_doc supplied and no phy_module/controller_module+rtl_modules were "
            "declared for this interface -- PHY-boundary bindability was never evaluated"
        ),
        "bind_decision": {"bindable": None, "mount_layer": None},
    }


def _matched_vip(interface: DeclaredInterface, vip_instances: List[dict]) -> Optional[dict]:
    """Exact `instance_path == bind_target` match only -- no fuzzy or
    name-derived matching, per this project's own `ip_ownership_conflict.py`
    precedent for the identical match key."""
    for inst in vip_instances:
        if inst.get("instance_path") == interface.bind_target:
            return inst
    return None


def classify_vip_need(phy_boundary_doc: dict, matched_vip: Optional[dict]) -> str:
    """Whether THIS interface, on its own, genuinely needs a real VIP:
    `VIP_REQUIRED_BINDABLE`/`VIP_REQUIRED_NOT_BOUND` only when the real
    PHY-boundary evidence says a monitor may bind there at all
    (`bind_decision.bindable is True`); `NOT_BINDABLE` when it explicitly is
    not (SERIAL-only/UNDECIDABLE); `NOT_AVAILABLE` when no real boundary
    evidence exists to decide either way."""
    status = (phy_boundary_doc or {}).get("status")
    bind_decision = (phy_boundary_doc or {}).get("bind_decision") or {}
    bindable = bind_decision.get("bindable")
    if status != "EXTRACTED":
        return "NOT_AVAILABLE"
    if bindable is True:
        return "VIP_REQUIRED_BINDABLE" if matched_vip else "VIP_REQUIRED_NOT_BOUND"
    if bindable is False:
        return "NOT_BINDABLE"
    return "NOT_AVAILABLE"


# ===========================================================================
# Coupling detection
# ===========================================================================

def derive_structural_coupling(interfaces: Sequence[DeclaredInterface]) -> List[CouplingFact]:
    """The ONE coupling kind this module derives without a caller citation:
    two interfaces declaring the IDENTICAL real `bind_target` are, by
    definition, the same physical DUT+PHY instance -- the real dual-role-port
    case (one physical connection, two logical VIP roles)."""
    facts: List[CouplingFact] = []
    for a, b in combinations(interfaces, 2):
        if a.bind_target == b.bind_target:
            facts.append(CouplingFact(
                interface_a=a.interface_id, interface_b=b.interface_id,
                coupling_kind="SHARED_PHY_INSTANCE",
                evidence=(
                    f"structurally derived: interfaces {a.interface_id!r} and {b.interface_id!r} "
                    f"both declare the identical bind_target {a.bind_target!r} -- the same real "
                    "physical DUT+PHY instance, not two independent interfaces"
                ),
                derived=True,
            ))
    return facts


def build_coupling_facts(
        interfaces: Sequence[DeclaredInterface],
        declared_coupling_facts: Optional[Sequence[Any]],
) -> List[CouplingFact]:
    """Structural facts plus caller-declared ones, every caller-declared fact
    checked to name real, declared interfaces."""
    ids = {i.interface_id for i in interfaces}
    facts = derive_structural_coupling(interfaces)
    for raw in declared_coupling_facts or []:
        if isinstance(raw, CouplingFact):
            cf = raw
        else:
            try:
                cf = CouplingFact(**raw)
            except TypeError as exc:
                raise MultiVipCooperationError(f"malformed coupling-fact entry: {exc}") from exc
        if cf.interface_a not in ids or cf.interface_b not in ids:
            raise MultiVipCooperationError(
                f"coupling fact names an undeclared interface: {cf.interface_a!r}/{cf.interface_b!r} "
                f"-- declared interfaces are {sorted(ids)}"
            )
        facts.append(cf)
    return facts


def _group_by_pair(facts: Sequence[CouplingFact]) -> Dict[Tuple[str, str], List[CouplingFact]]:
    grouped: Dict[Tuple[str, str], List[CouplingFact]] = {}
    for f in facts:
        grouped.setdefault(f.pair_key(), []).append(f)
    return grouped


def classify_cooperation(need_a: str, need_b: str) -> str:
    """Cooperation is `COOPERATION_REQUIRED` only when BOTH interfaces
    genuinely, on real PHY-boundary evidence, need a VIP. A missing evidence
    side is `COOPERATION_UNKNOWN_INSUFFICIENT_EVIDENCE`, checked before
    `NOT_BINDABLE` -- "we could not check one side" must never be read as
    "one side is confirmed not bindable"."""
    if need_a == "NOT_AVAILABLE" or need_b == "NOT_AVAILABLE":
        return "COOPERATION_UNKNOWN_INSUFFICIENT_EVIDENCE"
    if need_a == "NOT_BINDABLE" or need_b == "NOT_BINDABLE":
        return "COOPERATION_UNCONFIRMED_NOT_BINDABLE"
    if need_a in _VIP_NEEDS_INDICATING_REQUIRED and need_b in _VIP_NEEDS_INDICATING_REQUIRED:
        return "COOPERATION_REQUIRED"
    return "COOPERATION_UNKNOWN_INSUFFICIENT_EVIDENCE"  # pragma: no cover -- exhaustive by construction


# ===========================================================================
# Sequencing dependency -- runtime_event_registry.py, reused verbatim
# ===========================================================================

def _to_observation(raw: Any) -> RuntimeEventObservation:
    if isinstance(raw, RuntimeEventObservation):
        return raw
    if not isinstance(raw, dict):
        raise MultiVipCooperationError(f"a sequencing observation must be a dict or RuntimeEventObservation, got {raw!r}")
    status_raw = raw.get("status")
    try:
        status = EventStatus(str(status_raw))
    except ValueError:
        raise MultiVipCooperationError(
            f"observation status {status_raw!r} is not one of {[s.value for s in EventStatus]}"
        )
    try:
        return RuntimeEventObservation(status=status, evidence=raw.get("evidence", ""),
                                        observed_at=raw.get("observed_at"))
    except EventRegistryError as exc:
        raise MultiVipCooperationError(f"invalid sequencing observation: {exc}") from exc


def build_sequencing_registry(
        cooperating_ids: Sequence[str],
        coupling_by_iface: Dict[str, set],
        sequencing_relations: Optional[Sequence[dict]],
        sequencing_observations: Optional[Dict[str, Any]],
) -> RuntimeEventRegistry:
    """One `RuntimeEventRegistry` covering every interface that participates
    in at least one real coupling fact -- one event per interface
    (`<interface_id>::VIP_LINK_READY`), `consumer` set to its real coupling
    partner(s). Relations are built ONLY from caller-declared, cited
    `sequencing_relations` entries -- this function never invents which
    interface depends on which."""
    ids = set(cooperating_ids)
    events = []
    for iface_id in cooperating_ids:
        consumers = tuple(sorted(coupling_by_iface.get(iface_id) or ())) or ("cooperating_virtual_sequencer",)
        events.append(RuntimeEventDef(
            event_name=_event_name(iface_id), producer=iface_id, consumer=consumers,
            source=(
                f"multi_vip_cooperation_architecting: interface {iface_id!r} participates in a "
                "declared/derived coupling fact"
            ),
        ))

    relations = []
    for rel in sequencing_relations or []:
        from_iface = rel.get("from_interface")
        to_iface = rel.get("to_interface")
        relation_raw = rel.get("relation")
        reason = rel.get("reason") or ""
        if from_iface not in ids or to_iface not in ids:
            raise MultiVipCooperationError(
                f"sequencing relation names an interface outside this cooperation set: "
                f"{from_iface!r}/{to_iface!r} not in {sorted(ids)}"
            )
        if not _nonempty(reason):
            raise MultiVipCooperationError(
                f"sequencing relation {from_iface!r} {relation_raw!r} {to_iface!r} carries no real "
                "reason citation -- an uncited sequencing claim is refused"
            )
        try:
            relation = EventRelationType(str(relation_raw))
        except ValueError:
            raise MultiVipCooperationError(
                f"sequencing relation type {relation_raw!r} is not one of "
                f"{[r.value for r in EventRelationType]}"
            )
        relations.append(EventRelationDecl(
            from_event=_event_name(from_iface), relation=relation,
            to_event=_event_name(to_iface), reason=reason,
        ))

    observations = {}
    for iface_id, raw_obs in (sequencing_observations or {}).items():
        if iface_id not in ids:
            raise MultiVipCooperationError(
                f"sequencing observation names unknown/uncooperating interface {iface_id!r}"
            )
        observations[_event_name(iface_id)] = _to_observation(raw_obs)

    try:
        return RuntimeEventRegistry(
            registry_id="multi_vip_cooperation", events=tuple(events), relations=tuple(relations),
            observations=observations,
            description=(
                "Sequencing-dependency graph over cooperating VIP interfaces' own readiness events, "
                "built by multi_vip_cooperation_architecting.py."
            ),
        )
    except EventRegistryError as exc:
        raise MultiVipCooperationError(f"sequencing dependency declaration is invalid: {exc}") from exc


def _pair_sequencing_status(
        registry: Optional[RuntimeEventRegistry], report, a_id: str, b_id: str,
) -> Tuple[str, list]:
    """Whether a real, direct relation was declared between `a_id`'s and
    `b_id`'s own events (`NOT_DECLARED` if not -- a relation declared
    elsewhere in the same registry does not count for THIS pair), and, if
    so, whether the current effective/raw status of either event shows a
    real block/failure."""
    if registry is None:
        return "NOT_DECLARED", []
    a_event, b_event = _event_name(a_id), _event_name(b_id)
    direct = [r for r in registry.relations if {r.from_event, r.to_event} == {a_event, b_event}]
    if not direct:
        return "NOT_DECLARED", []
    is_blocked = (
        report.effective_status.get(a_event) == EventStatus.BLOCKED_BY_DEPENDENCY.value
        or report.effective_status.get(b_event) == EventStatus.BLOCKED_BY_DEPENDENCY.value
        or report.raw_status.get(a_event) in (EventStatus.FAILED.value, EventStatus.TIMEOUT.value)
        or report.raw_status.get(b_event) in (EventStatus.FAILED.value, EventStatus.TIMEOUT.value)
    )
    findings = [f for f in report.findings if f.get("event") in (a_event, b_event)]
    return ("DECLARED_BLOCKED" if is_blocked else "DECLARED_CLEAN"), findings


# ===========================================================================
# Shared virtual-sequencer composition -- verification_architecture.py +
# system_virtual_sequencer.py, reused verbatim
# ===========================================================================

def pair_virtual_sequencer_composition(
        a: DeclaredInterface, b: DeclaredInterface, phy_boundary_docs: Dict[str, dict],
) -> dict:
    """Treat the cooperating (a, b) pair as one "subsystem" and hand its real
    bind entries to `verification_architecture.build_vip_bind_ir()` then
    `system_virtual_sequencer.build_subsystem_composition()` -- reused
    verbatim, never re-derived, per module docstring."""
    bind_entries = []
    boundary_by_target: Dict[str, dict] = {}
    chain_by_target: Dict[str, list] = {}
    for iface in (a, b):
        entry: Dict[str, Any] = {
            "target_instance": iface.bind_target, "ports": [],
            "reason": f"cooperating VIP bind for interface {iface.interface_id!r}",
        }
        if iface.bind_tier is not None:
            entry["tier"] = iface.bind_tier
        bind_entries.append(entry)
        doc = phy_boundary_docs.get(iface.interface_id) or {}
        if doc.get("status") == "EXTRACTED" and iface.bind_target not in boundary_by_target:
            boundary_by_target[iface.bind_target] = doc.get("bind_decision") or {}
        if iface.hierarchy_hops and iface.bind_target not in chain_by_target:
            chain_by_target[iface.bind_target] = iface.hierarchy_hops

    try:
        vip_binds = va.build_vip_bind_ir(bind_entries, boundary_by_target or None, chain_by_target or None)
        composition = svs.build_subsystem_composition(
            f"{a.interface_id}__{b.interface_id}", vip_binds)
    except (va.VerificationArchitectureError, svs.SystemVirtualSequencerError) as exc:
        raise MultiVipCooperationError(
            f"could not derive virtual-sequencer composition for {a.interface_id!r}/"
            f"{b.interface_id!r}: {exc}"
        ) from exc
    return composition.to_dict()


# ===========================================================================
# Whole record
# ===========================================================================

@dataclass
class VipCooperationRelationship:
    interface_a: str
    interface_b: str
    coupling_facts: list
    cooperation_status: str
    architecture_status: str
    sequencing_dependency: dict
    virtual_sequencer_composition: dict
    source_evidence: list

    def __post_init__(self) -> None:
        ctx = f"{self.interface_a}/{self.interface_b}"
        _validate_vocab(self.cooperation_status, COOPERATION_STATUSES, "cooperation_status", ctx)
        _validate_vocab(self.architecture_status, ARCHITECTURE_STATUSES, "architecture_status", ctx)
        _validate_vocab(self.sequencing_dependency.get("status"), SEQUENCING_STATUSES,
                         "sequencing_dependency.status", ctx)

    def to_dict(self) -> dict:
        return {
            "interface_a": self.interface_a, "interface_b": self.interface_b,
            "coupling_facts": self.coupling_facts,
            "cooperation_status": self.cooperation_status,
            "architecture_status": self.architecture_status,
            "sequencing_dependency": self.sequencing_dependency,
            "virtual_sequencer_composition": self.virtual_sequencer_composition,
            "source_evidence": self.source_evidence,
        }

    def to_row(self) -> dict:
        return {
            "interface_a": self.interface_a, "interface_b": self.interface_b,
            "cooperation_status": self.cooperation_status,
            "architecture_status": self.architecture_status,
            "sequencing_status": self.sequencing_dependency.get("status"),
            "composition_mode": self.virtual_sequencer_composition.get("composition_mode"),
        }


@dataclass
class MultiVipCooperationIR:
    schema_version: str
    interfaces: list
    relationships: list
    overall_status: str
    source_evidence: list

    def __post_init__(self) -> None:
        _validate_vocab(self.overall_status, OVERALL_STATUSES, "overall_status", "<record>")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "overall_status": self.overall_status,
            "interfaces": self.interfaces,
            "relationships": [r.to_dict() for r in self.relationships],
            "source_evidence": self.source_evidence,
        }

    def render_markdown(self) -> str:
        columns = [
            ("interface_a", "Interface A"), ("interface_b", "Interface B"),
            ("cooperation_status", "Cooperation"), ("architecture_status", "Architecture"),
            ("sequencing_status", "Sequencing"), ("composition_mode", "Vseqr Composition"),
        ]
        rows = [r.to_row() for r in self.relationships]
        return render_markdown_table(
            columns, rows,
            empty_note="(no coupled interface pairs -- no multi-VIP cooperation detected)",
        )


def derive_overall_status(relationships: Sequence[VipCooperationRelationship]) -> str:
    """Worst-wins over every reported pair. No coupled pairs at all is the
    honest common case (a single-VIP topology -- `ip_ownership_conflict.py`'s
    own territory, not this module's). A `COOPERATION_REQUIRED` pair whose
    architecture is not yet complete outranks a fully-architected one, which
    in turn outranks a pair this module could only report as uncertain."""
    if not relationships:
        return "NO_MULTI_VIP_COOPERATION_DETECTED"
    required = [r for r in relationships if r.cooperation_status == "COOPERATION_REQUIRED"]
    if required:
        if any(r.architecture_status == "ARCHITECTURE_INCOMPLETE" for r in required):
            return "COOPERATION_DETECTED_ARCHITECTURE_INCOMPLETE"
        return "COOPERATION_ARCHITECTED"
    return "INSUFFICIENT_EVIDENCE"


def build_multi_vip_cooperation(
        interfaces: Sequence[Any],
        env_manifest: Optional[dict] = None,
        rtl_modules: Optional[list] = None,
        declared_coupling_facts: Optional[Sequence[Any]] = None,
        sequencing_relations: Optional[Sequence[dict]] = None,
        sequencing_observations: Optional[Dict[str, Any]] = None,
) -> MultiVipCooperationIR:
    """The one entry point.

    `interfaces`: a list of `DeclaredInterface` (or their constructor kwargs
    as plain dicts) -- every real interface in scope for this topology.
    `env_manifest`: a real env.manifest.json dict (or any dict carrying its
    `vip_config` layer), read through `ip_ownership_conflict.
    real_vip_instances()` -- never re-parsed here.
    `rtl_modules`: real parsed RTL modules (flat list, or
    `dut_facts.rtl.files` shape) for interfaces that declare `phy_module`+
    `controller_module` but no pre-computed `phy_boundary_doc`.
    `declared_coupling_facts`: `CouplingFact` (or kwargs) beyond the
    structurally-derived `SHARED_PHY_INSTANCE` ones.
    `sequencing_relations`: `{"from_interface", "relation", "to_interface",
    "reason"}` entries -- real, cited ordering facts between two
    interfaces' own readiness events.
    `sequencing_observations`: optional `{interface_id: {"status", "evidence",
    "observed_at"}}` real observations of those events.
    """
    if not interfaces:
        raise MultiVipCooperationError("at least one declared interface is required")

    try:
        ifaces = [i if isinstance(i, DeclaredInterface) else DeclaredInterface(**i) for i in interfaces]
    except TypeError as exc:
        raise MultiVipCooperationError(f"malformed declared-interface entry: {exc}") from exc
    ids = [i.interface_id for i in ifaces]
    if len(set(ids)) != len(ids):
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        raise MultiVipCooperationError(f"duplicate interface_id(s): {dupes}")

    vip_instances = real_vip_instances(env_manifest or {})
    phy_boundary_docs = {i.interface_id: resolve_phy_boundary(i, rtl_modules) for i in ifaces}

    per_interface = []
    vip_need: Dict[str, str] = {}
    for i in ifaces:
        role = resolve_vip_role(i.dut_port_direction)
        matched = _matched_vip(i, vip_instances)
        doc = phy_boundary_docs[i.interface_id]
        need = classify_vip_need(doc, matched)
        vip_need[i.interface_id] = need
        per_interface.append({
            "interface_id": i.interface_id,
            "dut_port_direction": i.dut_port_direction,
            "bind_target": i.bind_target,
            "vip_role": role,
            "matched_vip_instance": matched.get("instance_path") if matched else None,
            "matched_vip_type": matched.get("vip_type") if matched else None,
            "phy_boundary_status": doc.get("status"),
            "phy_boundary_bindable": (doc.get("bind_decision") or {}).get("bindable"),
            "phy_boundary_reason": doc.get("reason"),
            "vip_need": need,
        })

    by_id = {i.interface_id: i for i in ifaces}
    coupling_facts = build_coupling_facts(ifaces, declared_coupling_facts)
    grouped = _group_by_pair(coupling_facts)

    coupling_by_iface: Dict[str, set] = {}
    for f in coupling_facts:
        coupling_by_iface.setdefault(f.interface_a, set()).add(f.interface_b)
        coupling_by_iface.setdefault(f.interface_b, set()).add(f.interface_a)
    cooperating_ids = sorted({iid for pair in grouped for iid in pair})

    registry: Optional[RuntimeEventRegistry] = None
    report = None
    if cooperating_ids:
        registry = build_sequencing_registry(
            cooperating_ids, coupling_by_iface, sequencing_relations, sequencing_observations)
        report = registry.propagate()

    relationships: List[VipCooperationRelationship] = []
    for pair in sorted(grouped):
        a_id, b_id = pair
        facts = grouped[pair]
        a, b = by_id[a_id], by_id[b_id]
        cooperation_status = classify_cooperation(vip_need[a_id], vip_need[b_id])
        seq_status, seq_findings = _pair_sequencing_status(registry, report, a_id, b_id)
        composition = pair_virtual_sequencer_composition(a, b, phy_boundary_docs)

        if cooperation_status == "COOPERATION_REQUIRED":
            if seq_status != "NOT_DECLARED" and composition["composition_mode"] in (
                    "DIRECT_HANDLE", "ADAPTER_REQUIRED"):
                architecture_status = "ARCHITECTED"
            else:
                architecture_status = "ARCHITECTURE_INCOMPLETE"
        else:
            architecture_status = "NOT_APPLICABLE"

        relationships.append(VipCooperationRelationship(
            interface_a=a_id, interface_b=b_id,
            coupling_facts=[f.to_dict() for f in facts],
            cooperation_status=cooperation_status,
            architecture_status=architecture_status,
            sequencing_dependency={
                "status": seq_status,
                "findings": seq_findings,
                "propagation": report.to_dict() if report is not None else None,
            },
            virtual_sequencer_composition=composition,
            source_evidence=[
                _evidence("connectivity.determine_role_from_port_direction"),
                _evidence("ip_ownership_conflict.real_vip_instances"),
                _evidence("phy_boundary.decide_bind_location"),
                _evidence("verification_architecture.build_vip_bind_ir"),
                _evidence("system_virtual_sequencer.build_subsystem_composition"),
                _evidence("runtime_event_registry.RuntimeEventRegistry.propagate"),
            ],
        ))

    overall = derive_overall_status(relationships)
    return MultiVipCooperationIR(
        schema_version=SCHEMA_VERSION, interfaces=per_interface, relationships=relationships,
        overall_status=overall,
        source_evidence=[
            _evidence("ip_ownership_conflict.real_vip_instances", vip_instance_count=len(vip_instances)),
            _evidence("declared_and_derived_coupling_facts", count=len(coupling_facts)),
        ],
    )


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabulary must share no token with
    `dv_harness.models.Status` -- the same guard several sibling
    domain-vocabulary modules in this repo already run against themselves."""
    verdict_values = {s.value for s in Status}
    vocab = (
        set(COUPLING_KINDS) | set(VIP_NEED_STATUSES) | set(COOPERATION_STATUSES)
        | set(ARCHITECTURE_STATUSES) | set(SEQUENCING_STATUSES) | set(OVERALL_STATUSES)
    )
    collisions = vocab & verdict_values
    if collisions:
        raise MultiVipCooperationError(
            f"vocabulary collides with dv_harness.models.Status: {sorted(collisions)}"
        )


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Standalone front door -- no dv-harness CLI verb (cli.py/gates.py/
# dashboard.py are explicitly out of scope for this task -- several other
# concurrent workflows are actively editing those specific files).
# ===========================================================================

_EXIT_CODE_BY_OVERALL_STATUS = {
    "COOPERATION_ARCHITECTED": 0,
    "NO_MULTI_VIP_COOPERATION_DETECTED": 0,
    "COOPERATION_DETECTED_ARCHITECTURE_INCOMPLETE": 1,
    "INSUFFICIENT_EVIDENCE": 2,
}


def execute_verb(argv: Optional[list] = None) -> int:
    """`python -m dv_harness.multi_vip_cooperation_architecting --input
    <file.json> [--json] [--markdown]`. `<file.json>` is a JSON document
    shaped `{"interfaces": [...], "env_manifest": {...}, "rtl_modules": [...],
    "coupling_facts": [...], "sequencing_relations": [...],
    "sequencing_observations": {...}}` (every key but `interfaces` optional).
    Exit 0 COOPERATION_ARCHITECTED/NO_MULTI_VIP_COOPERATION_DETECTED,
    1 COOPERATION_DETECTED_ARCHITECTURE_INCOMPLETE,
    2 INSUFFICIENT_EVIDENCE/usage or validation error."""
    import argparse
    import json as _json
    import sys as _sys

    parser = argparse.ArgumentParser(prog="python -m dv_harness.multi_vip_cooperation_architecting")
    parser.add_argument("--input", required=True, help="path to an input JSON document")
    parser.add_argument("--json", action="store_true", help="emit the record as JSON")
    parser.add_argument("--markdown", action="store_true", help="emit the record as a markdown table")
    args = parser.parse_args(argv)

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            doc = _json.load(f)
    except (OSError, ValueError) as exc:
        print(f"NOT_AVAILABLE: could not read/parse {args.input!r}: {exc}", file=_sys.stderr)
        return 2

    try:
        ir = build_multi_vip_cooperation(
            interfaces=doc.get("interfaces") or [],
            env_manifest=doc.get("env_manifest"),
            rtl_modules=doc.get("rtl_modules"),
            declared_coupling_facts=doc.get("coupling_facts"),
            sequencing_relations=doc.get("sequencing_relations"),
            sequencing_observations=doc.get("sequencing_observations"),
        )
    except MultiVipCooperationError as exc:
        print(f"ERROR: {exc}", file=_sys.stderr)
        return 2
    except (TypeError, KeyError, AttributeError) as exc:
        print(f"ERROR: malformed input document: {exc}", file=_sys.stderr)
        return 2

    if args.json:
        print(_json.dumps(ir.to_dict(), indent=2))
    elif args.markdown:
        print(ir.render_markdown())
    else:
        print(f"overall_status: {ir.overall_status}")
        for r in ir.relationships:
            print(f"  {r.interface_a} <-> {r.interface_b}: {r.cooperation_status} / "
                  f"{r.architecture_status} (seq={r.sequencing_dependency['status']}, "
                  f"vseqr={r.virtual_sequencer_composition['composition_mode']})")

    return _EXIT_CODE_BY_OVERALL_STATUS[ir.overall_status]


def main() -> None:
    import sys as _sys
    _sys.exit(execute_verb())


if __name__ == "__main__":
    main()
