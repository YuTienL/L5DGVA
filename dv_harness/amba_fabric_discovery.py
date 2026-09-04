"""dv_harness/amba_fabric_discovery.py -- AMBA-7..14: trace every fabric port
AWAY from the fabric, across the structural elements between it and the real
transaction endpoint, and terminate in exactly one of ten reportable states.

WHY THIS IS A NEW MODULE, not more of `connectivity.py`
-------------------------------------------------------
`connectivity.py` owns per-interface CLASSIFICATION: AMBA-4's protocol verdict
from a port-name set, AMBA-5's dual-perspective roles from port direction,
AMBA-6's count table, and the T1-T4 bind-confidence tiers. Every one of those
answers a question about ONE module boundary in isolation. AMBA-7..14 asks a
structurally different question -- what is on the OTHER END of this port, three
wrappers and an arbiter away -- which needs a port-level connectivity GRAPH and
a traversal over it. That graph did not exist anywhere in this repo before this
module (see `verible_parser.py`'s instantiation/port-connection/continuous-
assign extraction, added for exactly this consumer).

So this module imports and COMPOSES `connectivity.py`'s primitives rather than
restating them:
  * `classify_amba_protocol()` is the ONLY protocol verdict used, re-run at
    each hop -- that is how a bridge crossing is detected (AMBA-11), and it is
    why no second protocol table exists here.
  * `determine_fabric_interface_roles()` is the ONLY role verdict used, so a
    traced endpoint's master/slave perspective has the same provenance
    `assert_role_provenance()` already demands of a matrix row.
  * `classify_bind_tier()` is the ONLY confidence classifier used. A bind
    candidate this module proposes carries a real `BindTier`, so an
    unresolved-protocol candidate lands at T4 (question queue) instead of
    being emitted, exactly as `enforce_bind_tier_policy()` requires.
  * `amba_signal_tokens()` / `ALL_AMBA_SIGNAL_NAMES` are the ONLY AMBA signal
    vocabulary -- this module adds no signal table of its own.

DISCOVERY AND PLANNING ONLY (AMBA-30 / AMBA-31)
-----------------------------------------------
Nothing here writes, renders, or returns a SystemVerilog `bind` statement. The
output is a *plan*: candidate bind LOCATIONS with priorities, tiers, evidence
and unresolved states, for a human to review. Emission stays behind
`uvm_generator/bind_mechanism_generator.py`'s existing gates, downstream of the
mandatory human review gate.

THE GRAPH MODEL
---------------
Elaboration produces one flat, hierarchical net graph:

  * A module's boundary PORT and the parent net wired to it are the SAME
    equipotential net (real SystemVerilog semantics), so a transparent wrapper
    -- however many layers deep -- is a single net class. That is what makes
    AMBA-7's "do not stop at a transparent wrapper" structural rather than
    heuristic: a wrapper simply does not break the net, and the wrapper's own
    boundary shows up as another attachment on the same class.
  * A continuous `assign` is NOT merged into the net class. It is a traversable
    EDGE with its own hop record, because AMBA-7 lists "wire assignments /
    aliases" among the things a trace crosses, and because merging them would
    fuse an AXI bundle to an APB bundle inside a bridge and destroy the one
    invariant AMBA-8 depends on (everything on one net class is the same
    protocol, so a P1/P2/P3 candidate can never sit across a protocol change).
  * Anything with real logic in it -- a mux, an arbiter, a register slice, a
    CDC, a converter, a bridge -- therefore breaks the net by construction, and
    must be CROSSED explicitly, which is where role classification happens.

WHAT THIS MODULE DELIBERATELY REFUSES TO GUESS
----------------------------------------------
A module exposing two AMBA bundles with no visible net-level path between them
(a black box, or a flat RTL module whose correspondence lives in procedural
logic a syntax-level parser cannot see) terminates the trace as AMBIGUOUS with
the missing evidence named. It is NOT rounded up to "bridge" or down to
"endpoint": both would be invented facts, and AMBA-14's own instruction is
"For unresolved status include exact reason and missing evidence. Never invent
endpoint hierarchy."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

from dv_harness import connectivity
from dv_harness.connectivity import (
    ALL_AMBA_SIGNAL_NAMES,
    AMBA_PROTOCOL_SIGNAL_ROLES,
    AMBA_PROTOCOL_UNRESOLVED,
    AMBA_SIGNAL_ROLE_ADDRESS,
    AMBA_SIGNAL_ROLE_DATA,
    AMBA_SIGNAL_ROLE_ID,
    AMBA_SIGNAL_ROLE_USER,
    CLOCK_RESET_RESOLVED,
    PASSIVE_INTERFACE,
    REQUIRED_HUMAN_INPUT,
    ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
    AMBA4_DISPLAY_NAMES,
    AmbaClassificationStatus,
    AmbaProtocolClassification,
    AmbaInterfaceRoles,
    BindTier,
    ConnectivityError,
    FABRIC_SIDE_MASTER_INTERFACE,
    FABRIC_SIDE_SLAVE_INTERFACE,
    VipInstanceRecord,
    amba_signal_role,
    amba_signal_tokens,
    amba_structural_match,
    assert_active_passive_vocabulary,
    build_protocol_interface_count_table,
    classify_amba_protocol,
    classify_bind_tier,
    determine_fabric_interface_roles,
    find_amba_clock_reset_ports,
    parse_bind_line,
    render_markdown_table,
    render_protocol_interface_count_table,
)
from dv_harness.phy_boundary import parse_port_width


class FabricDiscoveryError(ConnectivityError):
    """Raised for a malformed netlist input -- a missing top module, a
    hierarchy that does not terminate. Subclasses `ConnectivityError` so a
    caller already handling this pipeline's errors handles these too."""


#: Hard bound on hierarchical elaboration depth. A real SoC hierarchy is
#: nowhere near this deep; hitting it means the instance graph is cyclic
#: (module A instantiating module B instantiating module A), which is illegal
#: SystemVerilog and must be reported, never silently truncated.
MAX_ELABORATION_DEPTH = 64

#: Hard bound on trace hops away from a fabric port. Exceeding it terminates
#: that branch as TRACE_BLOCKED with the bound named, rather than looping.
MAX_TRACE_HOPS = 32

#: A peer instance counts as carrying the WHOLE interface (rather than a
#: fragment of it) once at least this fraction of the bundle's AMBA-named
#: signals reach it. Coverage is measured over AMBA signals ONLY, so shared
#: clock/reset nets -- which legitimately reach every instance in the design --
#: cannot make an unrelated block look like an interface peer.
#:
#: 0.5 rather than 1.0 because a real crossing element does not always take
#: every signal of a bundle (an arbiter may take the request channels and
#: drive responses back over separately-named nets). A peer below the fraction
#: is not discarded -- it is recorded as a PARTIAL peer, and a bundle whose
#: signals split across partial peers with no full peer is AMBIGUOUS.
BUNDLE_COVERAGE_FULL_FRACTION = 0.5


# ===========================================================================
# AMBA-14: trace termination status
#
# Exactly one primary status per port, from the doc's own ten. Defined here
# rather than in connectivity.py because it is this module's own vocabulary --
# the same house convention BindTier and GateStatus already follow.
# ===========================================================================

class TraceTerminationStatus(str, Enum):
    SOURCE_FOUND = "SOURCE_FOUND"
    DESTINATION_FOUND = "DESTINATION_FOUND"
    MULTIPLE_SOURCE = "MULTIPLE_SOURCE"
    MULTIPLE_DESTINATION = "MULTIPLE_DESTINATION"
    PROTOCOL_BRIDGE_FOUND = "PROTOCOL_BRIDGE_FOUND"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    TRACE_BLOCKED = "TRACE_BLOCKED"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    DESTINATION_NOT_FOUND = "DESTINATION_NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"


#: The statuses that leave a real question open. Every one of them MUST carry a
#: non-empty `reason` and `missing_evidence` -- enforced by
#: `assert_unresolved_states_explained()`, not left to reviewer diligence.
UNRESOLVED_TERMINATION_STATUSES = frozenset({
    TraceTerminationStatus.TRACE_BLOCKED,
    TraceTerminationStatus.SOURCE_NOT_FOUND,
    TraceTerminationStatus.DESTINATION_NOT_FOUND,
    TraceTerminationStatus.AMBIGUOUS,
})


# ===========================================================================
# AMBA-7: the structural elements a trace crosses, and what each one means
# ===========================================================================

class StructuralRole(str, Enum):
    """What a module sitting between the fabric and an endpoint actually is.

    The verdict is STRUCTURAL: how many AMBA bundles the module exposes, which
    of them have a visible net-level path to the arrival bundle, and whether
    the protocol changes across it. A module NAME never establishes any of
    these -- it can only add a T3 sub-role hint (`sub_role`), which is exactly
    the naming-heuristic tier `connectivity.classify_bind_tier()` already
    refuses to auto-accept."""
    TRANSACTION_ENDPOINT = "TRANSACTION_ENDPOINT"
    PROTOCOL_PRESERVING_ADAPTER = "PROTOCOL_PRESERVING_ADAPTER"
    PROTOCOL_BRIDGE = "PROTOCOL_BRIDGE"
    MUX_OR_ARBITER = "MUX_OR_ARBITER"
    DECODER_OR_INTERCONNECT = "DECODER_OR_INTERCONNECT"
    WIRE_ASSIGN_ALIAS = "WIRE_ASSIGN_ALIAS"
    OPAQUE_BLACK_BOX = "OPAQUE_BLACK_BOX"
    UNDECIDABLE_MULTI_BUNDLE = "UNDECIDABLE_MULTI_BUNDLE"


#: T3-only sub-role hints for a PROTOCOL_PRESERVING_ADAPTER. AMBA-7 names
#: register slices, pipelines, CDC blocks, clock/reset wrappers and width/ID
#: converters as distinct things to trace across; structurally they are
#: identical (one bundle in, one same-protocol bundle out), so the only
#: available discriminator is the instance/module name. That makes every
#: sub-role a naming heuristic, and it is tiered accordingly -- it NEVER
#: changes the structural role, the protocol, or a bind candidate's tier.
ADAPTER_SUB_ROLE_NAME_HINTS: tuple = (
    ("CDC_OR_CLOCK_RESET_WRAPPER", ("CDC", "SYNC", "ASYNC", "CLKRST", "CLOCK_RESET")),
    ("REGISTER_SLICE_OR_PIPELINE", ("REG_SLICE", "REGSLICE", "SKID", "PIPE", "PIPELINE")),
    ("WIDTH_CONVERTER", ("WIDTH", "DWIDTH", "UPSIZE", "DOWNSIZE", "UPSIZER", "DOWNSIZER")),
    ("ID_CONVERTER", ("ID_CONV", "IDCONV", "ID_WIDTH", "IDW")),
    ("TRANSPARENT_WRAPPER", ("WRAPPER", "WRAP")),
)


def adapter_sub_role_hint(module_name: str, instance_name: str = "") -> Optional[dict]:
    """A T3 naming hint for what KIND of protocol-preserving adapter this is.

    Returns None when no hint matches, which is the common and perfectly
    acceptable case -- a nameless adapter stays PROTOCOL_PRESERVING_ADAPTER.
    The returned dict always carries `requires_human_confirmation=True` and the
    matched token, so a report reader can see the verdict came from a name."""
    haystack = f"{module_name or ''}|{instance_name or ''}".upper()
    for sub_role, tokens in ADAPTER_SUB_ROLE_NAME_HINTS:
        for tok in tokens:
            if tok in haystack:
                tier = classify_bind_tier(naming_match=tok)
                return {
                    "sub_role": sub_role,
                    "matched_token": tok,
                    "tier": tier.tier.value,
                    "requires_human_confirmation": True,
                    "rationale": (
                        f"sub-role {sub_role} suggested by the name token {tok!r} in "
                        f"{haystack!r}. Naming heuristic only: it does not change the "
                        f"structural PROTOCOL_PRESERVING_ADAPTER verdict, the protocol "
                        f"classification, or any bind candidate's tier."),
                }
    return None


# ===========================================================================
# AMBA-8: VIP placement priority
# ===========================================================================

class VipPlacementPriority(str, Enum):
    """The doc's own preferred order. P1 is best, P4 the fallback.

    The ordering is realised structurally, not by preference-scoring: P1/P2/P3
    are positions found on the traced path between the fabric port and the real
    endpoint, and the trace never crosses a protocol change without terminating
    (see `StructuralRole.PROTOCOL_BRIDGE`), so no P1/P2/P3 candidate can ever
    sit beyond one -- AMBA-8's "do not push VIP beyond protocol conversion" is
    a property of the traversal, not a check bolted on afterwards."""
    P1_TRUE_IP_AMBA_BOUNDARY = "P1_TRUE_IP_AMBA_BOUNDARY"
    P2_IMMEDIATE_IP_WRAPPER = "P2_IMMEDIATE_IP_WRAPPER"
    P3_PROTOCOL_PRESERVING_ADAPTER = "P3_PROTOCOL_PRESERVING_ADAPTER"
    P4_BUS_FABRIC_PORT = "P4_BUS_FABRIC_PORT"


#: Best-first order, used for ranking. Deliberately derived from the enum's own
#: declaration order rather than restated, so adding a tier cannot desync them.
VIP_PLACEMENT_PRIORITY_ORDER: tuple = tuple(VipPlacementPriority)


def _priority_rank(p: VipPlacementPriority) -> int:
    return VIP_PLACEMENT_PRIORITY_ORDER.index(p)


#: AMBA-8's "do not push VIP beyond" list, as reasons a candidate position is
#: refused. Recorded on the trace so a reader sees WHY the best available
#: candidate is only P4.
PUSH_LIMIT_PROTOCOL_CONVERSION = "PROTOCOL_CONVERSION_BOUNDARY"
PUSH_LIMIT_NON_AMBA_ABSTRACTION = "NON_AMBA_ABSTRACTION_BOUNDARY"
PUSH_LIMIT_INACCESSIBLE_HIERARCHY = "INACCESSIBLE_HIERARCHY"
PUSH_LIMIT_SEMANTIC_DISCONTINUITY = "INTERFACE_SEMANTIC_DISCONTINUITY"


# ===========================================================================
# The RTL structural model (consumed from verible_parser, never hand-typed)
# ===========================================================================

#: Port name recorded for a POSITIONAL connection whose formal port could not
#: be resolved, because the instantiated module is not in the parsed source
#: set. A real, greppable sentinel rather than None, for the same reason
#: `connectivity.REQUIRED_HUMAN_INPUT` is one.
POSITIONAL_PORT_UNRESOLVED = "POSITIONAL_PORT_UNRESOLVED"


@dataclass
class InstanceDef:
    instance_name: str
    module_name: str
    #: list of (port_name_or_None, position, nets) exactly as parsed
    connections: list = field(default_factory=list)


@dataclass
class AssignEdge:
    """One continuous assignment, kept as a traversable edge rather than
    merged. `is_alias` is True only for a strict 1:1 net rename, the single
    case where the two sides are the same interface signal under two names."""
    lhs_nets: list
    rhs_nets: list
    text: str = ""

    @property
    def is_alias(self) -> bool:
        return len(self.lhs_nets) == 1 and len(self.rhs_nets) == 1


@dataclass
class ModuleDef:
    name: str
    port_directions: dict = field(default_factory=dict)   # port -> 'input'/'output'/'inout'/None
    port_order: list = field(default_factory=list)
    instances: list = field(default_factory=list)         # list[InstanceDef]
    assigns: list = field(default_factory=list)           # list[AssignEdge]
    #: port -> verible's own raw `data_type` text (`logic [31:0]`,
    #: `logic [DW-1:0]`, `logic`). Carried unparsed: turning it into a bit
    #: count is `phy_boundary.parse_port_width()`'s job, and it answers None
    #: for a parameterized range rather than guessing -- which is the honesty
    #: AMBA-15's width points depend on.
    port_data_types: dict = field(default_factory=dict)
    #: list of {name, type_text, default_text} -- verible's parsed parameter
    #: list, AMBA-15 point 12's evidence.
    parameters: list = field(default_factory=list)


def _module_dicts(parse_results) -> Iterable[dict]:
    """Normalise whatever the caller has -- `verible_parser.FileParseResult`
    objects, their `to_dict()` form, a bare list of module dicts -- into module
    dicts. The same both-shapes tolerance `build_connectivity_matrix()` offers,
    so a persisted parse artifact and a live parse are interchangeable."""
    for result in parse_results or ():
        modules = getattr(result, "modules", None)
        if modules is None and isinstance(result, dict):
            modules = result.get("modules")
        if modules is None:
            modules = [result]
        for mod in modules:
            if isinstance(mod, dict):
                yield mod
                continue
            yield {
                "name": getattr(mod, "name", None),
                "ports": [vars(p) for p in getattr(mod, "ports", []) or []],
                "parameters": [vars(p) for p in getattr(mod, "parameters", []) or []],
                "instances": [
                    {
                        "instance_name": i.instance_name,
                        "module_name": i.module_name,
                        "connections": [vars(c) for c in i.connections or []],
                    }
                    for i in getattr(mod, "instances", []) or []
                ],
                "continuous_assigns": [
                    vars(a) for a in getattr(mod, "continuous_assigns", []) or []
                ],
            }


def build_module_index(parse_results) -> dict:
    """{module_name: ModuleDef} from real verible parse results.

    A module absent from this index is a BLACK BOX: its instantiation is still
    a real structural fact (the instance exists, its named connections are
    known), but nothing about its interior is. That distinction drives
    `StructuralRole.OPAQUE_BLACK_BOX` and TRACE_BLOCKED, and it is the reason
    an unparsed module is never quietly treated as an endpoint."""
    index: dict = {}
    for mod in _module_dicts(parse_results):
        name = mod.get("name")
        if not name:
            continue
        ports = mod.get("ports") or []
        index[name] = ModuleDef(
            name=name,
            port_directions={p.get("name"): p.get("direction")
                             for p in ports if p.get("name")},
            port_order=[p.get("name") for p in ports if p.get("name")],
            port_data_types={p.get("name"): p.get("data_type")
                             for p in ports if p.get("name")},
            parameters=[dict(p) for p in mod.get("parameters") or []],
            instances=[
                InstanceDef(
                    instance_name=i.get("instance_name"),
                    module_name=i.get("module_name"),
                    connections=[(c.get("port_name"), c.get("position"),
                                  list(c.get("nets") or []))
                                 for c in i.get("connections") or []],
                )
                for i in mod.get("instances") or []
                if i.get("instance_name")
            ],
            assigns=[
                AssignEdge(lhs_nets=list(a.get("lhs_nets") or []),
                           rhs_nets=list(a.get("rhs_nets") or []),
                           text=f"{a.get('lhs_text')} = {a.get('rhs_text')}")
                for a in mod.get("continuous_assigns") or []
            ],
        )
    return index


@dataclass
class PortAttachment:
    """One module-boundary port sitting on an equipotential net."""
    path: tuple          # hierarchical instance path; () is the top module itself
    module_name: str
    port: str

    @property
    def path_str(self) -> str:
        return "/".join(self.path) if self.path else "<top>"


@dataclass
class ElaboratedInstance:
    path: tuple
    module_name: str
    is_blackbox: bool
    port_names: list = field(default_factory=list)
    port_directions: dict = field(default_factory=dict)
    #: Both empty for a black box: an instantiation names ports and nets, never
    #: their declared types or the module's parameters. That emptiness is the
    #: real reason AMBA-15's width/parameterization points report UNKNOWN
    #: there, and it must not be confused with a parsed module that genuinely
    #: declares no parameters.
    port_data_types: dict = field(default_factory=dict)
    parameters: list = field(default_factory=list)

    @property
    def path_str(self) -> str:
        return "/".join(self.path) if self.path else "<top>"


class _UnionFind:
    def __init__(self):
        self._parent: dict = {}

    def find(self, key):
        parent = self._parent
        parent.setdefault(key, key)
        root = key
        while parent[root] != root:
            root = parent[root]
        while parent[key] != root:      # path compression
            parent[key], key = root, parent[key]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


class FabricNetlist:
    """The elaborated port-level connectivity graph AMBA-7..14 traverses.

    Built ONCE from a module index and a top module name; every trace runs
    against the same graph. Nets are keyed `(scope_path, net_name)` and merged
    across hierarchy boundaries, so `u_top_net`, `u_wrap/S_AXI_AWADDR` and
    `u_wrap/u_core/S_AXI_AWADDR` are one class -- which is precisely what makes
    a transparent wrapper transparent here without a naming rule."""

    def __init__(self, module_index: dict, top_module: str):
        if top_module not in module_index:
            raise FabricDiscoveryError("TOP_MODULE_NOT_PARSED", {
                "top_module": top_module,
                "known_modules": sorted(module_index),
                "hint": "the top module must be in the parsed source set; without its "
                        "body there is no hierarchy to elaborate",
            })
        self.modules = module_index
        self.top_module = top_module
        self.instances: dict = {}
        self.assign_edges: dict = {}       # scope path -> list[AssignEdge]
        self.attachments: dict = {}        # net class -> list[PortAttachment]
        self.split_connections: list = []  # non-1:1 (concatenated) port connections
        self.unresolved_positional: list = []
        self._uf = _UnionFind()
        self._elaborate((), top_module, 0)
        self._index_attachments()

    # -- elaboration --------------------------------------------------------

    def _elaborate(self, path: tuple, module_name: str, depth: int) -> None:
        if depth > MAX_ELABORATION_DEPTH:
            raise FabricDiscoveryError("ELABORATION_DEPTH_EXCEEDED", {
                "path": "/".join(path), "module": module_name,
                "max_depth": MAX_ELABORATION_DEPTH,
                "hint": "an instance hierarchy this deep means a cyclic instantiation, "
                        "which is illegal SystemVerilog -- reported rather than truncated",
            })
        mod = self.modules.get(module_name)
        self.instances[path] = ElaboratedInstance(
            path=path, module_name=module_name, is_blackbox=mod is None,
            port_names=list(mod.port_order) if mod else [],
            port_directions=dict(mod.port_directions) if mod else {},
            port_data_types=dict(mod.port_data_types) if mod else {},
            parameters=[dict(p) for p in mod.parameters] if mod else [],
        )
        if mod is None:
            return
        self.assign_edges[path] = list(mod.assigns)
        for inst in mod.instances:
            child_path = path + (inst.instance_name,)
            child_mod = self.modules.get(inst.module_name)
            child_ports: list = []
            for port_name, position, nets in inst.connections:
                if port_name is None:
                    if child_mod is not None and position is not None \
                            and position < len(child_mod.port_order):
                        port_name = child_mod.port_order[position]
                    else:
                        self.unresolved_positional.append({
                            "path": "/".join(child_path),
                            "module": inst.module_name,
                            "position": position,
                            "nets": list(nets),
                            "reason": "positional connection into a module that is not in "
                                      "the parsed source set, so which formal port this "
                                      "position names cannot be established",
                        })
                        port_name = POSITIONAL_PORT_UNRESOLVED
                child_ports.append(port_name)
                if len(nets) == 1:
                    self._uf.union((path, nets[0]), (child_path, port_name))
                elif len(nets) > 1:
                    # A concatenated/expression connection is not one
                    # equipotential net. Recorded as a real trace obstacle
                    # rather than joined to an arbitrary one of its operands.
                    self.split_connections.append({
                        "path": "/".join(child_path), "port": port_name,
                        "nets": list(nets),
                        "reason": "port driven by a multi-net expression (concatenation or "
                                  "operation); the connection is not a single equipotential "
                                  "net and cannot be followed as one",
                    })
            self._elaborate(child_path, inst.module_name, depth + 1)
            if child_mod is None:
                # Black box: its port list is only what the instantiation named.
                self.instances[child_path].port_names = [
                    p for p in child_ports if p != POSITIONAL_PORT_UNRESOLVED]

    def _index_attachments(self) -> None:
        for path, inst in self.instances.items():
            for port in inst.port_names:
                cls = self._uf.find((path, port))
                self.attachments.setdefault(cls, []).append(
                    PortAttachment(path=path, module_name=inst.module_name, port=port))

    # -- queries ------------------------------------------------------------

    def net_class(self, path: tuple, port: str):
        return self._uf.find((path, port))

    def attachments_on(self, classes) -> list:
        out: list = []
        for cls in classes:
            out.extend(self.attachments.get(cls, []))
        return out

    def instance(self, path: tuple) -> Optional[ElaboratedInstance]:
        return self.instances.get(path)

    def descendants_of(self, path: tuple) -> list:
        return [p for p in self.instances
                if len(p) > len(path) and p[:len(path)] == path]


def build_fabric_netlist(parse_results, top_module: str) -> FabricNetlist:
    """The one entry point from real parsed RTL to a traversable graph."""
    return FabricNetlist(build_module_index(parse_results), top_module)


# ===========================================================================
# Bundle grouping
#
# Grouping ports into interfaces is unavoidably prefix-based -- S00_AXI_AWADDR
# and S00_AXI_AWVALID belong together and nothing but their shared prefix says
# so. That is NOT the naming-based protocol classification AMBA-4 forbids: the
# name only decides WHICH GROUP a port is in, and the group's PROTOCOL verdict
# still comes from `classify_amba_protocol()`, i.e. from signal evidence alone.
# A group whose signal evidence is not AMBA is dropped, so a coincidental
# prefix cannot manufacture an interface.
# ===========================================================================

_TOKEN_SPLIT_RE = re.compile(r"([^A-Za-z0-9]+)")


def amba_bundle_prefix(port_name: str) -> Optional[str]:
    """The bundle prefix of one port, or None if the port carries no AMBA
    signal token at all.

    Works by locating the AMBA signal token INSIDE the port name and returning
    everything before it: `S00_AXI_AWVALID` -> `S00_AXI_`, `haddr` -> `` (the
    empty prefix, a real value meaning "unprefixed bundle"), `m0_pready` ->
    `m0_`. The token vocabulary is `connectivity.ALL_AMBA_SIGNAL_NAMES` -- this
    module owns no signal table."""
    upper = str(port_name).upper()
    parts = _TOKEN_SPLIT_RE.split(upper)
    # Scan right-to-left: the signal token is the LAST AMBA-named token, so
    # `AXI_AWADDR` gives prefix `AXI_` rather than stopping at a leading token
    # that happens to be spec-named.
    consumed = 0
    for idx in range(len(parts) - 1, -1, -1):
        tok = parts[idx]
        if not tok or _TOKEN_SPLIT_RE.fullmatch(tok):
            continue
        if amba_signal_tokens([tok]) & ALL_AMBA_SIGNAL_NAMES:
            consumed = sum(len(p) for p in parts[:idx])
            return str(port_name)[:consumed]
    return None


def group_ports_into_amba_bundles(port_names) -> dict:
    """{prefix: [port, ...]} for the AMBA-named ports of one module.

    Ports carrying no AMBA signal token (clocks, resets, sideband, proprietary
    signals) are absent from every bundle -- deliberately, since a shared clock
    net reaching every block in the design would otherwise make every block
    look like an interface peer of every other."""
    groups: dict = {}
    for port in port_names or ():
        prefix = amba_bundle_prefix(port)
        if prefix is None:
            continue
        groups.setdefault(prefix, []).append(port)
    return groups


@dataclass
class AmbaBundle:
    """One AMBA interface on one elaborated instance's boundary."""
    path: tuple
    module_name: str
    prefix: str
    ports: list
    classification: AmbaProtocolClassification
    roles: Optional[AmbaInterfaceRoles] = None

    @property
    def path_str(self) -> str:
        return "/".join(self.path) if self.path else "<top>"

    @property
    def interface_id(self) -> str:
        return f"{self.path_str}:{self.prefix}" if self.prefix else f"{self.path_str}:<unprefixed>"

    @property
    def protocol(self) -> str:
        return self.classification.protocol

    @property
    def display_name(self) -> str:
        return self.classification.display_name

    @property
    def resolved(self) -> bool:
        return self.classification.status == AmbaClassificationStatus.RESOLVED.value

    @property
    def fabric_side_role(self) -> str:
        return self.roles.fabric_side_role if self.roles \
            else ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS

    def to_dict(self) -> dict:
        return {
            "interface_id": self.interface_id,
            "instance_path": self.path_str,
            "module": self.module_name,
            "prefix": self.prefix,
            "ports": sorted(self.ports),
            "protocol": self.protocol,
            "display_name": self.display_name,
            "status": self.classification.status,
            "classification": self.classification.to_dict(),
            "roles": self.roles.to_dict() if self.roles else None,
        }


def _bundle_roles(netlist: FabricNetlist, path: tuple, ports: list,
                  protocol: str) -> Optional[AmbaInterfaceRoles]:
    """AMBA-5 roles for one bundle, from REAL per-signal port directions.

    Returns None when the instance is a black box (no declared directions at
    all) -- deliberately not an invented `inout`, since "we never saw a
    direction" and "the RTL declares inout" are different facts and AMBA-5's
    own unresolved state already distinguishes them."""
    inst = netlist.instance(path)
    if inst is None:
        return None
    directions = {p: inst.port_directions.get(p) for p in ports}
    usable = {p: d for p, d in directions.items()
              if str(d or "").strip().lower() in ("input", "output", "inout")}
    if not usable:
        return None
    return determine_fabric_interface_roles(protocol=protocol, signal_directions=usable)


def bundles_of(netlist: FabricNetlist, path: tuple) -> list:
    """Every AMBA bundle on one elaborated instance's boundary, protocol- and
    role-classified. A prefix group whose signal evidence classifies as
    NOT_AMBA is dropped; every other status (including partial/ambiguous) is
    KEPT, per AMBA-3's "do not silently omit partial interfaces"."""
    inst = netlist.instance(path)
    if inst is None:
        return []
    out: list = []
    for prefix, ports in sorted(group_ports_into_amba_bundles(inst.port_names).items()):
        classification = classify_amba_protocol(ports)
        if classification.status == AmbaClassificationStatus.NOT_AMBA.value:
            continue
        out.append(AmbaBundle(
            path=path, module_name=inst.module_name, prefix=prefix,
            ports=sorted(ports), classification=classification,
            roles=_bundle_roles(netlist, path, ports, classification.protocol),
        ))
    return out


def find_bundle(netlist: FabricNetlist, path: tuple, prefix: str) -> Optional[AmbaBundle]:
    for b in bundles_of(netlist, path):
        if b.prefix == prefix:
            return b
    return None


# ===========================================================================
# Trace records
# ===========================================================================

@dataclass
class TraceHop:
    """One structural element the trace crossed, with the evidence for its
    role. `role_tier` is a real `BindTier` value: T2 for a structurally
    established role, T3 for one resting on a naming hint, T4 for undecidable."""
    instance_path: str
    module_name: str
    role: str
    role_tier: str
    protocol: str
    rationale: str
    sub_role_hint: Optional[dict] = None
    bundle_prefix: str = ""

    def to_dict(self) -> dict:
        return {
            "instance_path": self.instance_path, "module": self.module_name,
            "role": self.role, "role_tier": self.role_tier, "protocol": self.protocol,
            "bundle_prefix": self.bundle_prefix, "rationale": self.rationale,
            "sub_role_hint": self.sub_role_hint,
        }


@dataclass
class VipBindCandidate:
    """A candidate VIP monitor/bind LOCATION -- never a bind statement.

    Carries a real `connectivity.BindTier`, so a candidate whose protocol never
    resolved lands at T4 and is routed to the question queue by the existing
    `enforce_bind_tier_policy()` rather than being emitted."""
    priority: str
    instance_path: str
    module_name: str
    bundle_prefix: str
    protocol: str
    ports: list
    bind_tier: str
    requires_human_confirmation: bool
    requires_question_queue_entry: bool
    rationale: str

    def to_dict(self) -> dict:
        return {
            "priority": self.priority, "instance_path": self.instance_path,
            "module": self.module_name, "bundle_prefix": self.bundle_prefix,
            "protocol": self.protocol, "ports": sorted(self.ports),
            "bind_tier": self.bind_tier,
            "requires_human_confirmation": self.requires_human_confirmation,
            "requires_question_queue_entry": self.requires_question_queue_entry,
            "rationale": self.rationale,
        }


@dataclass
class ProtocolBridgeCrossing:
    """AMBA-11: BOTH sides of a protocol-changing boundary.

    Neither side's protocol is ever taken from the other: each is an
    independent `classify_amba_protocol()` verdict on that side's own signal
    set, which is exactly why "do not label a downstream APB endpoint as AXI"
    cannot be violated here by construction."""
    bridge_instance_path: str
    bridge_module: str
    upstream_protocol: str
    upstream_bundle_prefix: str
    upstream_ports: list
    downstream_protocol: str
    downstream_bundle_prefix: str
    downstream_ports: list
    rationale: str

    def to_dict(self) -> dict:
        return {
            "bridge_instance_path": self.bridge_instance_path,
            "bridge_module": self.bridge_module,
            "vip_a_upstream": {"protocol": self.upstream_protocol,
                               "bundle_prefix": self.upstream_bundle_prefix,
                               "ports": sorted(self.upstream_ports)},
            "vip_b_downstream": {"protocol": self.downstream_protocol,
                                 "bundle_prefix": self.downstream_bundle_prefix,
                                 "ports": sorted(self.downstream_ports)},
            "rationale": self.rationale,
        }


@dataclass
class TraceBranch:
    """One enumerated path away from the fabric port. AMBA-12/13 require every
    branch be listed, never one chosen arbitrarily, so a multi-source or
    multi-destination trace carries one of these per source/destination."""
    status: str
    hops: list = field(default_factory=list)              # list[TraceHop]
    endpoint_instance_path: str = ""
    endpoint_module: str = ""
    endpoint_protocol: str = ""
    candidates: list = field(default_factory=list)        # list[VipBindCandidate]
    reason: str = ""
    missing_evidence: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "hops": [h.to_dict() for h in self.hops],
            "endpoint_instance_path": self.endpoint_instance_path,
            "endpoint_module": self.endpoint_module,
            "endpoint_protocol": self.endpoint_protocol,
            "candidates": [c.to_dict() for c in self.candidates],
            "reason": self.reason,
            "missing_evidence": list(self.missing_evidence),
        }


#: Trace direction. Derived from the fabric bundle's own AMBA-5
#: FABRIC_SIDE_ROLE, never passed in as an opinion.
TRACE_TOWARD_MASTERS = "TOWARD_INITIATING_MASTERS"     # AMBA-9
TRACE_TOWARD_SLAVES = "TOWARD_DESTINATION_SLAVES"      # AMBA-10
TRACE_DIRECTION_UNRESOLVED = "TRACE_DIRECTION_UNRESOLVED"


@dataclass
class FabricPortTrace:
    """One fabric port's complete AMBA-7..14 result."""
    interface_id: str
    fabric_instance_path: str
    bundle_prefix: str
    fabric_protocol: str
    fabric_side_role: str
    direction: str
    status: str
    branches: list = field(default_factory=list)          # list[TraceBranch]
    bridges: list = field(default_factory=list)           # list[ProtocolBridgeCrossing]
    reason: str = ""
    missing_evidence: list = field(default_factory=list)
    push_limits: list = field(default_factory=list)
    #: AMBA-8's P4 fallback, present ONLY when no better position was found.
    fallback_candidates: list = field(default_factory=list)

    @property
    def best_candidate(self) -> Optional[VipBindCandidate]:
        ranked = self.ranked_candidates()
        return ranked[0] if ranked else None

    def ranked_candidates(self) -> list:
        """AMBA-8's preference order, best first. Ties (two P1s on two
        different branches of a MULTIPLE_SOURCE trace) are BOTH kept -- AMBA-12
        forbids arbitrarily choosing one source."""
        out = [c for br in self.branches for c in br.candidates] + list(self.fallback_candidates)
        out.sort(key=lambda c: (_priority_rank(VipPlacementPriority(c.priority)),
                                c.instance_path))
        return out

    def to_dict(self) -> dict:
        return {
            "interface_id": self.interface_id,
            "fabric_instance_path": self.fabric_instance_path,
            "bundle_prefix": self.bundle_prefix,
            "fabric_protocol": self.fabric_protocol,
            "fabric_side_role": self.fabric_side_role,
            "direction": self.direction,
            "status": self.status,
            "branches": [b.to_dict() for b in self.branches],
            "protocol_bridges": [b.to_dict() for b in self.bridges],
            "reason": self.reason,
            "missing_evidence": list(self.missing_evidence),
            "vip_placement_push_limits": list(self.push_limits),
            "fallback_vip_bind_candidates": [c.to_dict() for c in self.fallback_candidates],
            "ranked_vip_bind_candidates": [c.to_dict() for c in self.ranked_candidates()],
        }


# ===========================================================================
# The traversal itself (AMBA-7, AMBA-9, AMBA-10)
# ===========================================================================

def _classes_of(netlist: FabricNetlist, path: tuple, ports) -> set:
    return {netlist.net_class(path, p) for p in ports}


def _strict_ancestor_scopes(path: tuple) -> set:
    """The scopes ENCLOSING an instance, excluding its own interior.

    Used when following a bundle outward from a module boundary: the
    continuous assignments that legitimately continue that same interface are
    the renames in the scopes the net passes through, never the ones inside
    the module itself. Crossing a module's own internal assigns from outside
    would fuse the two sides of a bridge -- the exact thing keeping assigns
    unmerged at elaboration time exists to prevent."""
    return {path[:i] for i in range(len(path))}


def _self_and_descendant_scopes(netlist: FabricNetlist, path: tuple) -> set:
    """The scopes INSIDE an instance, including its own. Used when asking
    whether two of that instance's bundles are internally connected."""
    return {path} | {p for p in netlist.assign_edges
                     if len(p) > len(path) and p[:len(path)] == path}


def _expand_through_assigns(netlist: FabricNetlist, classes: set, scopes: set) -> tuple:
    """Grow a class set across continuous assignments in the given scopes,
    recording which ones were crossed. AMBA-7 lists "wire assignments /
    aliases" as things a trace must cross; they are crossed HERE, explicitly
    and reportably, rather than silently merged at elaboration time (which
    would fuse the two sides of a bridge into one net and break AMBA-8's
    protocol-preservation invariant)."""
    grown = set(classes)
    crossed: list = []
    changed = True
    while changed:
        changed = False
        for scope in scopes:
            edges = netlist.assign_edges.get(scope) or ()
            for edge in edges:
                lhs = {netlist.net_class(scope, n) for n in edge.lhs_nets}
                rhs = {netlist.net_class(scope, n) for n in edge.rhs_nets}
                if (lhs & grown and not rhs <= grown) or (rhs & grown and not lhs <= grown):
                    grown |= lhs | rhs
                    crossed.append({
                        "scope": "/".join(scope) if scope else "<top>",
                        "assign": edge.text,
                        "is_alias": edge.is_alias,
                    })
                    changed = True
    return grown, crossed


def _amba_ports(ports) -> list:
    return [p for p in ports if amba_bundle_prefix(p) is not None]


def _group_peers(netlist: FabricNetlist, classes: set, exclude_path: tuple) -> dict:
    """{instance_path: [PortAttachment]} for every module boundary on these
    nets other than the port we started from."""
    peers: dict = {}
    for att in netlist.attachments_on(classes):
        if att.path == exclude_path:
            continue
        peers.setdefault(att.path, []).append(att)
    return peers


def _maximal_paths(paths) -> list:
    """Collapse an ancestor chain to its deepest member.

    A transparent wrapper and the IP inside it sit on the SAME net, so both
    appear as peers. They are one endpoint at two depths, not two endpoints --
    and that depth ordering is exactly AMBA-8's P1/P2/P3 ladder, so it is kept
    (as the chain) rather than discarded."""
    out = []
    for p in paths:
        if p == ():
            continue
        if any(other != p and len(other) > len(p) and other[:len(p)] == p for other in paths):
            continue
        out.append(p)
    return sorted(out)


def _internal_path_evidence(netlist: FabricNetlist, path: tuple,
                            arrival_classes: set, target_classes: set) -> tuple:
    """Is there a visible internal path inside this instance between the bundle
    the trace arrived on and another of its bundles?

    Returns `(evidence_kind, found)`. Two evidence kinds, deliberately
    distinguished because they justify different confidence:
      * DIRECT_NET_OR_ALIAS -- a real net/continuous-assign path inside this
        module. Structural evidence: T2.
      * VIA_SUBINSTANCE -- both bundles touch the same sub-instance, whose own
        interior was not itself traversed. Weaker: T3, human confirmation.
    `(None, False)` means no visible path at all, which is NOT the same as "not
    connected" -- see this module's docstring on AMBIGUOUS."""
    if not target_classes:
        return None, False
    grown, _ = _expand_through_assigns(netlist, set(arrival_classes),
                                       _self_and_descendant_scopes(netlist, path))
    if grown & target_classes:
        return "DIRECT_NET_OR_ALIAS", True
    for sub in netlist.descendants_of(path):
        inst = netlist.instance(sub)
        sub_classes = _classes_of(netlist, sub, inst.port_names)
        if sub_classes & grown and sub_classes & target_classes:
            return "VIA_SUBINSTANCE", True
    return None, False


def _candidate_chain(netlist: FabricNetlist, chain_paths: list,
                     arrival_prefix_by_path: dict, *, endpoint_established: bool) -> list:
    """AMBA-8's P1/P2/P3 candidates for one endpoint chain, plus the reasons.

    P1 is the deepest boundary on the chain (the true IP AMBA boundary), P2 its
    immediate parent, P3 anything shallower still on the same protocol-
    preserving path.

    `endpoint_established=False` -- a branch that ended BLOCKED or AMBIGUOUS --
    demotes every position on the chain to P3. The boundary is still a real,
    observable, protocol-preserving place to watch, so it is worth proposing;
    but calling it P1 TRUE IP AMBA BOUNDARY would assert the very thing the
    branch just failed to establish."""
    candidates: list = []
    ordered = sorted(chain_paths, key=len, reverse=True)
    for idx, path in enumerate(ordered):
        prefix = arrival_prefix_by_path.get(path)
        bundle = find_bundle(netlist, path, prefix) if prefix is not None else None
        if bundle is None:
            continue
        if not endpoint_established:
            priority = VipPlacementPriority.P3_PROTOCOL_PRESERVING_ADAPTER
            why = ("an observable protocol-preserving position on the traced path. NOT "
                   "ranked P1/P2: this branch never established a real transaction "
                   "endpoint, so no boundary on it is known to be an IP boundary")
        elif idx == 0:
            priority = VipPlacementPriority.P1_TRUE_IP_AMBA_BOUNDARY
            why = ("deepest AMBA boundary on the traced net -- the real IP boundary, "
                   "AMBA-8's first preference")
        elif idx == 1:
            priority = VipPlacementPriority.P2_IMMEDIATE_IP_WRAPPER
            why = ("the immediate wrapper enclosing the IP boundary; same equipotential "
                   "net, so the interface is semantically identical there")
        else:
            priority = VipPlacementPriority.P3_PROTOCOL_PRESERVING_ADAPTER
            why = ("a protocol-preserving position on the same traced path, further from "
                   "the IP than its immediate wrapper")
        candidates.append(_make_candidate(bundle, priority, why))
    return candidates


def _make_candidate(bundle: AmbaBundle, priority: VipPlacementPriority,
                    why: str) -> VipBindCandidate:
    """Every candidate's tier comes from `connectivity.classify_bind_tier()`
    on this bundle's own structural match -- never from this module's opinion
    of how confident it feels."""
    tier = classify_bind_tier(structural_match=amba_structural_match(bundle.ports))
    return VipBindCandidate(
        priority=priority.value,
        instance_path=bundle.path_str,
        module_name=bundle.module_name,
        bundle_prefix=bundle.prefix,
        protocol=bundle.protocol,
        ports=list(bundle.ports),
        bind_tier=tier.tier.value,
        requires_human_confirmation=tier.requires_human_confirmation,
        requires_question_queue_entry=tier.requires_question_queue_entry,
        rationale=f"{why}. Tier from connectivity.classify_bind_tier(): {tier.rationale}",
    )


def _classify_hop(netlist: FabricNetlist, path: tuple, arrival_bundle: AmbaBundle,
                  arrival_classes: set, direction: str) -> dict:
    """What is this module, structurally, and where (if anywhere) does the
    transaction continue? Returns a dict with `role`, `tier`, `rationale`,
    `continuations` (list[AmbaBundle]) and `sub_role_hint`."""
    inst = netlist.instance(path)
    other_bundles = [b for b in bundles_of(netlist, path)
                     if b.prefix != arrival_bundle.prefix
                     and not (_classes_of(netlist, path, b.ports) & arrival_classes)]

    if not other_bundles:
        if inst.is_blackbox:
            # A black box with exactly one AMBA bundle IS the endpoint as far
            # as AMBA traffic is concerned: there is no second AMBA interface
            # for the transaction to continue through. Its interior being
            # unparsed does not change that, so this is a real endpoint, not a
            # blocked trace.
            return {"role": StructuralRole.TRANSACTION_ENDPOINT,
                    "tier": BindTier.T2_STRUCTURAL_MATCH,
                    "rationale": (f"{inst.module_name} is not in the parsed source set, but "
                                  f"its instantiation exposes exactly one AMBA bundle "
                                  f"({arrival_bundle.prefix!r}); there is no second AMBA "
                                  f"interface for a transaction to continue through, so this "
                                  f"is the transaction endpoint"),
                    "continuations": [], "sub_role_hint": None}
        return {"role": StructuralRole.TRANSACTION_ENDPOINT,
                "tier": BindTier.T2_STRUCTURAL_MATCH,
                "rationale": (f"{inst.module_name} exposes exactly one AMBA bundle "
                              f"({arrival_bundle.prefix!r}) on its boundary -- the "
                              f"transaction terminates here"),
                "continuations": [], "sub_role_hint": None}

    continuations: list = []
    evidence_kinds: set = set()
    unexplained: list = []
    for b in other_bundles:
        kind, found = _internal_path_evidence(
            netlist, path, arrival_classes, _classes_of(netlist, path, b.ports))
        if found:
            continuations.append(b)
            evidence_kinds.add(kind)
        else:
            unexplained.append(b)

    if not continuations:
        return {
            "role": StructuralRole.OPAQUE_BLACK_BOX if inst.is_blackbox
            else StructuralRole.UNDECIDABLE_MULTI_BUNDLE,
            "tier": BindTier.T4_UNDECIDABLE,
            "rationale": (
                f"{inst.module_name} exposes {len(other_bundles)} further AMBA bundle(s) "
                f"({[b.prefix for b in other_bundles]}) besides the one the trace arrived "
                f"on, but no net-level or continuous-assign path between them is visible "
                f"in the parsed source"
                + (" (the module is not in the parsed source set at all)"
                   if inst.is_blackbox else
                   " (their correspondence would be through procedural logic, which a "
                   "syntax-level parse cannot see)")
                + ". Whether the transaction continues through it cannot be established, "
                  "so it is reported as unresolved rather than rounded to 'bridge' or "
                  "'endpoint'."),
            "continuations": [], "sub_role_hint": None,
            "unexplained_bundles": unexplained,
        }

    tier = (BindTier.T2_STRUCTURAL_MATCH if evidence_kinds == {"DIRECT_NET_OR_ALIAS"}
            else BindTier.T3_NAMING_HEURISTIC)
    protocols = {b.protocol for b in continuations}
    arrival_protocol = arrival_bundle.protocol

    if any(p != arrival_protocol for p in protocols):
        return {"role": StructuralRole.PROTOCOL_BRIDGE, "tier": tier,
                "rationale": (
                    f"protocol changes across {inst.module_name}: the trace arrived on "
                    f"{arrival_bundle.display_name} and the connected bundle(s) classify as "
                    f"{sorted(protocols)}. Each side's protocol is an independent "
                    f"classify_amba_protocol() verdict on that side's own signals."),
                "continuations": continuations, "sub_role_hint": None}

    if len(continuations) > 1:
        role = (StructuralRole.MUX_OR_ARBITER if direction == TRACE_TOWARD_MASTERS
                else StructuralRole.DECODER_OR_INTERCONNECT)
        return {"role": role, "tier": tier,
                "rationale": (
                    f"{inst.module_name} connects the arrival bundle to "
                    f"{len(continuations)} further {arrival_bundle.display_name} bundle(s) "
                    f"({[b.prefix for b in continuations]}) -- a "
                    f"{'fan-in' if direction == TRACE_TOWARD_MASTERS else 'fan-out'} point. "
                    f"Every branch is enumerated; none is chosen."),
                "continuations": continuations, "sub_role_hint": None}

    hint = adapter_sub_role_hint(inst.module_name, path[-1] if path else "")
    return {"role": StructuralRole.PROTOCOL_PRESERVING_ADAPTER, "tier": tier,
            "rationale": (
                f"{inst.module_name} carries the transaction from bundle "
                f"{arrival_bundle.prefix!r} to {continuations[0].prefix!r} with the protocol "
                f"unchanged ({arrival_bundle.display_name}) -- a protocol-preserving "
                f"element, so the trace continues through it"),
            "continuations": continuations, "sub_role_hint": hint}


def _direction_of(bundle: AmbaBundle) -> str:
    """AMBA-9 vs AMBA-10, from the bundle's own AMBA-5 fabric-side role."""
    role = bundle.fabric_side_role
    if role == FABRIC_SIDE_SLAVE_INTERFACE:
        return TRACE_TOWARD_MASTERS
    if role == FABRIC_SIDE_MASTER_INTERFACE:
        return TRACE_TOWARD_SLAVES
    return TRACE_DIRECTION_UNRESOLVED


def _not_found_status(direction: str) -> TraceTerminationStatus:
    return (TraceTerminationStatus.SOURCE_NOT_FOUND if direction == TRACE_TOWARD_MASTERS
            else TraceTerminationStatus.DESTINATION_NOT_FOUND)


def _found_status(direction: str) -> TraceTerminationStatus:
    return (TraceTerminationStatus.SOURCE_FOUND if direction == TRACE_TOWARD_MASTERS
            else TraceTerminationStatus.DESTINATION_FOUND)


def _multiple_status(direction: str) -> TraceTerminationStatus:
    return (TraceTerminationStatus.MULTIPLE_SOURCE if direction == TRACE_TOWARD_MASTERS
            else TraceTerminationStatus.MULTIPLE_DESTINATION)


def trace_fabric_port(netlist: FabricNetlist, fabric_path: tuple,
                      bundle_prefix: str) -> FabricPortTrace:
    """AMBA-7: trace ONE fabric port away from the fabric to its real
    transaction endpoint, and terminate in exactly one AMBA-14 status.

    `fabric_path` is the fabric interconnect's own hierarchical instance path
    (e.g. `("u_fabric",)`); `bundle_prefix` names one of its AMBA bundles (e.g.
    `"S00_AXI_"`), as returned by `bundles_of()`. Direction -- toward
    initiating masters (AMBA-9) or destination slaves (AMBA-10) -- is derived
    from that bundle's own AMBA-5 role, never supplied by the caller."""
    fabric_bundle = find_bundle(netlist, fabric_path, bundle_prefix)
    if fabric_bundle is None:
        raise FabricDiscoveryError("FABRIC_BUNDLE_NOT_FOUND", {
            "fabric_path": "/".join(fabric_path), "bundle_prefix": bundle_prefix,
            "known_prefixes": [b.prefix for b in bundles_of(netlist, fabric_path)],
        })

    direction = _direction_of(fabric_bundle)
    trace = FabricPortTrace(
        interface_id=fabric_bundle.interface_id,
        fabric_instance_path=fabric_bundle.path_str,
        bundle_prefix=bundle_prefix,
        fabric_protocol=fabric_bundle.protocol,
        fabric_side_role=fabric_bundle.fabric_side_role,
        direction=direction,
        status=TraceTerminationStatus.AMBIGUOUS.value,
    )

    if direction == TRACE_DIRECTION_UNRESOLVED:
        trace.reason = (
            "the fabric-side role of this port is unresolved (AMBA-5), so whether the "
            "trace should look for an initiating MASTER (AMBA-9) or a destination SLAVE "
            "(AMBA-10) cannot be established. Tracing without settling that would produce "
            "a SOURCE/DESTINATION label the evidence does not support.")
        trace.missing_evidence = [
            f"per-signal port directions for {fabric_bundle.interface_id} sufficient for "
            f"connectivity.resolve_fabric_request_direction() to settle the request "
            f"direction",
        ]
        return trace

    branches: list = []
    bridges: list = []
    visited: set = set()

    def explore(path: tuple, bundle: AmbaBundle, hops: list, depth: int) -> None:
        key = (path, bundle.prefix)
        if key in visited:
            branches.append(TraceBranch(
                status=TraceTerminationStatus.TRACE_BLOCKED.value, hops=list(hops),
                reason=f"structural loop: {bundle.interface_id} was already visited on this "
                       f"trace, so following it again would not terminate",
                missing_evidence=["a non-cyclic connectivity path, or elaboration-time "
                                  "evidence that resolves the loop"]))
            return
        visited.add(key)
        if depth > MAX_TRACE_HOPS:
            branches.append(TraceBranch(
                status=TraceTerminationStatus.TRACE_BLOCKED.value, hops=list(hops),
                reason=f"hop budget MAX_TRACE_HOPS={MAX_TRACE_HOPS} exhausted before an "
                       f"endpoint was reached",
                missing_evidence=["a shorter structural path, or a raised hop budget with "
                                  "a stated reason"]))
            return

        classes = _classes_of(netlist, path, bundle.ports)
        classes, crossed_assigns = _expand_through_assigns(
            netlist, classes, _strict_ancestor_scopes(path))
        for crossing in crossed_assigns:
            hops = hops + [TraceHop(
                instance_path=crossing["scope"], module_name="<continuous assign>",
                role=StructuralRole.WIRE_ASSIGN_ALIAS.value,
                role_tier=BindTier.T2_STRUCTURAL_MATCH.value,
                protocol=bundle.protocol, bundle_prefix=bundle.prefix,
                rationale=f"crossed continuous assignment {crossing['assign']!r} in scope "
                          f"{crossing['scope']} (alias={crossing['is_alias']})")]

        peers = _group_peers(netlist, classes, exclude_path=path)
        exits_design = () in peers
        internal_only = {p: a for p, a in peers.items()
                         if p != () and len(p) > len(fabric_path) and p[:len(fabric_path)] == fabric_path}
        external = {p: a for p, a in peers.items()
                    if p != () and p not in internal_only}

        amba_port_count = max(1, len(_amba_ports(bundle.ports)))
        coverage = {
            p: len({att.port for att in atts if amba_bundle_prefix(att.port) is not None})
            for p, atts in external.items()
        }
        full = {p for p, n in coverage.items()
                if n >= amba_port_count * BUNDLE_COVERAGE_FULL_FRACTION}
        partial = {p for p in external if p not in full and coverage.get(p, 0) > 0}

        if not full:
            if partial:
                branches.append(TraceBranch(
                    status=TraceTerminationStatus.AMBIGUOUS.value, hops=list(hops),
                    reason=(
                        f"the {bundle.display_name} bundle {bundle.interface_id} splits "
                        f"across {len(partial)} peer instance(s) "
                        f"({sorted('/'.join(p) for p in partial)}), none of which carries at "
                        f"least {BUNDLE_COVERAGE_FULL_FRACTION:.0%} of its AMBA signals. No "
                        f"single peer holds the whole interface, so no coherent endpoint can "
                        f"be named."),
                    missing_evidence=[
                        "which of the partial peers carries the transaction (an "
                        "elaboration-time or reviewer-supplied answer)",
                    ]))
                return
            if exits_design:
                branches.append(TraceBranch(
                    status=_not_found_status(direction).value, hops=list(hops),
                    reason=(f"the trace reaches the top module {netlist.top_module}'s own "
                            f"boundary ports: the endpoint is outside the parsed design"),
                    missing_evidence=[f"RTL for whatever drives {netlist.top_module}'s "
                                      f"{bundle.prefix!r} boundary ports"]))
                return
            if internal_only:
                branches.append(TraceBranch(
                    status=TraceTerminationStatus.INTERNAL_ONLY.value, hops=list(hops),
                    reason=(f"every peer on this net lies inside the fabric instance "
                            f"{'/'.join(fabric_path)} itself "
                            f"({sorted('/'.join(p) for p in internal_only)}); the port never "
                            f"reaches an endpoint outside the fabric")))
                return
            branches.append(TraceBranch(
                status=_not_found_status(direction).value, hops=list(hops),
                reason=(f"no module boundary other than {bundle.interface_id} sits on this "
                        f"interface's nets"),
                missing_evidence=["RTL connecting this fabric port to anything at all "
                                  "(it may be genuinely unconnected)"]))
            return

        for endpoint_path in _maximal_paths(list(full)):
            chain = sorted([p for p in full
                            if len(p) <= len(endpoint_path)
                            and endpoint_path[:len(p)] == p], key=len, reverse=True)
            arrival_prefix_by_path: dict = {}
            for p in chain:
                for b in bundles_of(netlist, p):
                    if _classes_of(netlist, p, b.ports) & classes:
                        arrival_prefix_by_path[p] = b.prefix
                        break
            arrival = find_bundle(netlist, endpoint_path,
                                  arrival_prefix_by_path.get(endpoint_path, ""))
            if arrival is None:
                branches.append(TraceBranch(
                    status=TraceTerminationStatus.TRACE_BLOCKED.value, hops=list(hops),
                    reason=(f"{'/'.join(endpoint_path)} sits on this interface's nets but "
                            f"no AMBA bundle of its own could be formed from the ports it "
                            f"connects through"),
                    missing_evidence=[f"the full port list of {'/'.join(endpoint_path)} "
                                      f"(it may be instantiated positionally into an "
                                      f"unparsed module)"]))
                continue

            verdict = _classify_hop(netlist, endpoint_path, arrival, classes, direction)
            hop = TraceHop(
                instance_path=arrival.path_str, module_name=arrival.module_name,
                role=verdict["role"].value, role_tier=verdict["tier"].value,
                protocol=arrival.protocol, bundle_prefix=arrival.prefix,
                rationale=verdict["rationale"], sub_role_hint=verdict.get("sub_role_hint"))
            chain_hops = hops + [hop]
            role = verdict["role"]

            if role == StructuralRole.TRANSACTION_ENDPOINT:
                candidates = _candidate_chain(netlist, chain, arrival_prefix_by_path,
                                              endpoint_established=True)
                branches.append(TraceBranch(
                    status=_found_status(direction).value, hops=chain_hops,
                    endpoint_instance_path=arrival.path_str,
                    endpoint_module=arrival.module_name,
                    endpoint_protocol=arrival.protocol,
                    candidates=candidates,
                    reason=verdict["rationale"]))
                continue

            if role == StructuralRole.PROTOCOL_BRIDGE:
                # The bridge's UPSTREAM boundary is a real, established AMBA
                # boundary of a real IP, so the P1/P2 ladder applies to it.
                # Only the downstream side is out of bounds, and that is
                # recorded separately as AMBA-11's VIP-B.
                candidates = _candidate_chain(netlist, chain, arrival_prefix_by_path,
                                              endpoint_established=True)
                for down in verdict["continuations"]:
                    bridges.append(ProtocolBridgeCrossing(
                        bridge_instance_path=arrival.path_str,
                        bridge_module=arrival.module_name,
                        upstream_protocol=arrival.protocol,
                        upstream_bundle_prefix=arrival.prefix,
                        upstream_ports=list(arrival.ports),
                        downstream_protocol=down.protocol,
                        downstream_bundle_prefix=down.prefix,
                        downstream_ports=list(down.ports),
                        rationale=verdict["rationale"]))
                trace.push_limits.append({
                    "limit": PUSH_LIMIT_PROTOCOL_CONVERSION,
                    "at": arrival.path_str,
                    "detail": (f"VIP is not pushed past {arrival.module_name}: the protocol "
                               f"changes there, so a downstream position would not be the "
                               f"same AMBA interface. AMBA-11's downstream side is recorded "
                               f"separately as VIP-B with its own protocol."),
                })
                branches.append(TraceBranch(
                    status=TraceTerminationStatus.PROTOCOL_BRIDGE_FOUND.value,
                    hops=chain_hops,
                    endpoint_instance_path=arrival.path_str,
                    endpoint_module=arrival.module_name,
                    endpoint_protocol=arrival.protocol,
                    candidates=candidates,
                    reason=verdict["rationale"]))
                continue

            if role in (StructuralRole.OPAQUE_BLACK_BOX,
                        StructuralRole.UNDECIDABLE_MULTI_BUNDLE):
                limit = (PUSH_LIMIT_INACCESSIBLE_HIERARCHY
                         if role == StructuralRole.OPAQUE_BLACK_BOX
                         else PUSH_LIMIT_SEMANTIC_DISCONTINUITY)
                trace.push_limits.append({
                    "limit": limit, "at": arrival.path_str,
                    "detail": verdict["rationale"]})
                branches.append(TraceBranch(
                    status=(TraceTerminationStatus.TRACE_BLOCKED.value
                            if role == StructuralRole.OPAQUE_BLACK_BOX
                            else TraceTerminationStatus.AMBIGUOUS.value),
                    hops=chain_hops,
                    endpoint_instance_path=arrival.path_str,
                    endpoint_module=arrival.module_name,
                    endpoint_protocol=arrival.protocol,
                    candidates=_candidate_chain(netlist, chain, arrival_prefix_by_path,
                                                endpoint_established=False),
                    reason=verdict["rationale"],
                    missing_evidence=[
                        f"the RTL body of {arrival.module_name}, or elaboration-time "
                        f"connectivity showing which of its AMBA bundles the transaction "
                        f"continues through",
                    ]))
                continue

            # Crossing element: keep tracing through every continuation.
            for cont in verdict["continuations"]:
                explore(endpoint_path, cont, chain_hops, depth + 1)

    explore(fabric_path, fabric_bundle, [], 0)

    trace.branches = branches
    trace.bridges = bridges
    if not any(b.candidates for b in branches):
        # AMBA-8's ladder must still terminate somewhere: when no
        # protocol-preserving position closer to a real endpoint was
        # established, the fabric port ITSELF is the P4 candidate. Emitting
        # nothing here would silently drop the port from the VIP plan, which
        # reads as "no VIP needed" rather than "nothing better than P4 found".
        trace.fallback_candidates = [_make_candidate(
            fabric_bundle, VipPlacementPriority.P4_BUS_FABRIC_PORT,
            "AMBA-8's P4 fallback: no protocol-preserving position closer to a real "
            "transaction endpoint was established for this port, so the bus fabric port "
            "itself is the only observable AMBA boundary available")]
    trace.status = _aggregate_status(branches, direction).value
    trace.reason = _aggregate_reason(trace.status, branches)
    trace.missing_evidence = sorted({m for b in branches for m in b.missing_evidence})
    return trace


def _aggregate_status(branches: list, direction: str) -> TraceTerminationStatus:
    """AMBA-14: exactly ONE primary status for the port, over however many
    branches were enumerated.

    A multi-branch trace is MULTIPLE_SOURCE / MULTIPLE_DESTINATION only when at
    least one branch really reached an endpoint. Several branches that all
    failed differently is not a fan-out finding -- it is AMBIGUOUS, and saying
    otherwise would report an enumeration of sources that was never
    established."""
    if not branches:
        return _not_found_status(direction)
    statuses = [b.status for b in branches]
    found = _found_status(direction).value
    resolved = [s for s in statuses if s == found]
    if len(branches) == 1:
        return TraceTerminationStatus(statuses[0])
    if len(resolved) > 1:
        return _multiple_status(direction)
    if len(resolved) == 1:
        # One real endpoint plus at least one unresolved branch: the unresolved
        # branch might be another source, so this is not a clean single find.
        return TraceTerminationStatus.AMBIGUOUS
    if all(s == TraceTerminationStatus.TRACE_BLOCKED.value for s in statuses):
        return TraceTerminationStatus.TRACE_BLOCKED
    if all(s == TraceTerminationStatus.PROTOCOL_BRIDGE_FOUND.value for s in statuses):
        return TraceTerminationStatus.PROTOCOL_BRIDGE_FOUND
    return TraceTerminationStatus.AMBIGUOUS


def _aggregate_reason(status: str, branches: list) -> str:
    if len(branches) == 1:
        return branches[0].reason
    per = "; ".join(f"[{b.status}] {b.reason}" for b in branches)
    return f"{len(branches)} branch(es) enumerated, none chosen: {per}"


# ===========================================================================
# AMBA-9 / AMBA-10: the two directional entry points
# ===========================================================================

def trace_fabric_slave_interface_to_masters(netlist: FabricNetlist, fabric_path: tuple,
                                            bundle_prefix: str) -> FabricPortTrace:
    """AMBA-9. Refuses a bundle whose fabric-side role is not SLAVE_INTERFACE:
    calling the slave-side trace on a master-side port would relabel a
    destination as a source, which is precisely the invented fact AMBA-14's
    "never invent endpoint hierarchy" forbids."""
    return _directional_trace(netlist, fabric_path, bundle_prefix,
                              FABRIC_SIDE_SLAVE_INTERFACE, TRACE_TOWARD_MASTERS)


def trace_fabric_master_interface_to_slaves(netlist: FabricNetlist, fabric_path: tuple,
                                            bundle_prefix: str) -> FabricPortTrace:
    """AMBA-10, the mirror of AMBA-9."""
    return _directional_trace(netlist, fabric_path, bundle_prefix,
                              FABRIC_SIDE_MASTER_INTERFACE, TRACE_TOWARD_SLAVES)


def _directional_trace(netlist: FabricNetlist, fabric_path: tuple, bundle_prefix: str,
                       required_role: str, expected_direction: str) -> FabricPortTrace:
    bundle = find_bundle(netlist, fabric_path, bundle_prefix)
    if bundle is None:
        raise FabricDiscoveryError("FABRIC_BUNDLE_NOT_FOUND", {
            "fabric_path": "/".join(fabric_path), "bundle_prefix": bundle_prefix})
    role = bundle.fabric_side_role
    if role != required_role and role != ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS:
        raise FabricDiscoveryError("WRONG_FABRIC_SIDE_ROLE_FOR_TRACE_DIRECTION", {
            "interface": bundle.interface_id,
            "fabric_side_role": role,
            "required_fabric_side_role": required_role,
            "expected_direction": expected_direction,
            "hint": "AMBA-9 traces fabric SLAVE interfaces toward initiating masters and "
                    "AMBA-10 traces fabric MASTER interfaces toward destination slaves; "
                    "use trace_fabric_port() if the direction is genuinely in question",
        })
    return trace_fabric_port(netlist, fabric_path, bundle_prefix)


def trace_all_fabric_ports(netlist: FabricNetlist, fabric_path: tuple) -> list:
    """AMBA-7's "mandatory per interface": trace EVERY AMBA bundle on the
    fabric instance, in a stable order. An interface whose direction or
    protocol never resolved still gets a trace record with its unresolved
    status -- omitting it would be exactly the silent drop AMBA-3 forbids."""
    return [trace_fabric_port(netlist, fabric_path, b.prefix)
            for b in bundles_of(netlist, fabric_path)]


# ===========================================================================
# Reporting / hand-off (still discovery-only: no bind statement anywhere)
# ===========================================================================

def assert_unresolved_states_explained(traces) -> None:
    """AMBA-14: "For unresolved status include exact reason and missing
    evidence." Enforced, not requested -- an unresolved trace with an empty
    reason or no missing evidence raises rather than reaching a report where a
    reader would read the silence as "nothing to say"."""
    for trace in traces or ():
        status = TraceTerminationStatus(trace.status)
        if status not in UNRESOLVED_TERMINATION_STATUSES:
            continue
        if not (trace.reason or "").strip():
            raise FabricDiscoveryError("UNRESOLVED_TRACE_WITHOUT_REASON", {
                "interface": trace.interface_id, "status": trace.status})
        if not trace.missing_evidence:
            raise FabricDiscoveryError("UNRESOLVED_TRACE_WITHOUT_MISSING_EVIDENCE", {
                "interface": trace.interface_id, "status": trace.status,
                "reason": trace.reason})


def summarize_trace_terminations(traces) -> dict:
    """Every one of AMBA-14's ten statuses, always, including the zero counts.
    A status absent from a fabric is a fact the summary should state, the same
    property AMBA-6's count table already has."""
    counts = {s.value: 0 for s in TraceTerminationStatus}
    for trace in traces or ():
        counts[trace.status] = counts.get(trace.status, 0) + 1
    return counts


def render_endpoint_trace_report(traces) -> str:
    """The human-review artifact for AMBA-30's gate. Text only -- no `bind`
    statement is rendered here or anywhere else in this module."""
    lines = ["# AMBA-7..14 Fabric Port Endpoint Trace", ""]
    counts = summarize_trace_terminations(traces)
    lines.append("## Trace termination status summary (AMBA-14)")
    lines.append("")
    lines.append("| status | ports |")
    lines.append("|---|---|")
    for status in TraceTerminationStatus:
        lines.append(f"| {status.value} | {counts.get(status.value, 0)} |")
    lines.append("")
    for trace in traces or ():
        lines.append(f"## {trace.interface_id} ({trace.fabric_protocol})")
        lines.append("")
        lines.append(f"- FABRIC_SIDE_ROLE: {trace.fabric_side_role}")
        lines.append(f"- trace direction: {trace.direction}")
        lines.append(f"- PRIMARY STATUS: **{trace.status}**")
        if trace.reason:
            lines.append(f"- reason: {trace.reason}")
        for missing in trace.missing_evidence:
            lines.append(f"- MISSING EVIDENCE: {missing}")
        for limit in trace.push_limits:
            lines.append(f"- VIP NOT PUSHED PAST {limit['at']}: {limit['limit']} -- "
                         f"{limit['detail']}")
        for idx, branch in enumerate(trace.branches, 1):
            lines.append(f"- branch {idx} [{branch.status}]: "
                         + " -> ".join(f"{h.instance_path}({h.role})" for h in branch.hops))
        for bridge in trace.bridges:
            lines.append(f"- PROTOCOL BRIDGE at {bridge.bridge_instance_path}: "
                         f"VIP-A upstream {bridge.upstream_protocol} / "
                         f"VIP-B downstream {bridge.downstream_protocol}")
        for cand in trace.ranked_candidates():
            lines.append(f"- CANDIDATE {cand.priority} @ {cand.instance_path} "
                         f"[{cand.protocol}] tier={cand.bind_tier}")
        lines.append("")
    lines.append("Discovery and planning only. No bind statement is proposed, emitted or "
                 "implied by this report (AMBA-30 / AMBA-31): a human reviews these "
                 "candidate locations before any UVM/VIP code is generated or modified.")
    return "\n".join(lines)


def discovered_topology_ids(traces) -> dict:
    """The masters/slaves ID lists AMBA-16/18/19/22's artifacts (and
    `tools/verification_flow/fabric_topology_completeness_gate.py`) are shaped
    around, derived from real traced endpoints.

    Deliberately NOT a full topology document: `scoreboard_matrix` and
    `address_map` are the downstream steps' own outputs (AMBA-23/25, computed
    by `uvm_generator/amba_fabric_generator.py`'s existing
    `build_scoreboard_matrix()` / `compute_address_regions()`), and inventing
    them here would be the duplicate-algorithm failure this module exists to
    avoid. Only endpoints whose trace really resolved are listed; an
    unresolved port contributes to `unresolved` instead, so a topology built
    from this can never quietly claim a master nobody traced."""
    masters, slaves, unresolved = [], [], []
    for trace in traces or ():
        found = _found_status(trace.direction).value if trace.direction in (
            TRACE_TOWARD_MASTERS, TRACE_TOWARD_SLAVES) else None
        resolved_branches = [b for b in trace.branches if found and b.status == found]
        if not resolved_branches:
            unresolved.append({"interface": trace.interface_id, "status": trace.status,
                               "reason": trace.reason})
            continue
        for branch in resolved_branches:
            entry = branch.endpoint_instance_path
            if trace.direction == TRACE_TOWARD_MASTERS:
                if entry not in masters:
                    masters.append(entry)
            elif entry not in slaves:
                slaves.append(entry)
    return {"masters": masters, "slaves": slaves, "unresolved": unresolved}


# ===========================================================================
# AMBA-15: VIP BIND LOCATION VALIDATION
#
# Thirteen named checks against one candidate bind LOCATION. Every one answers
# from real elaborated-RTL evidence or answers UNKNOWN -- AMBA-15's own
# instruction ("Use UNKNOWN where not provable") is the whole design constraint
# here, because the alternative failure mode is a checklist that reads
# all-green because six of its rows quietly defaulted.
#
# No check here proposes, writes or implies a `bind` statement: the outputs are
# a validation record and a readiness verdict a human reads at AMBA-30's gate.
# ===========================================================================

#: One check's outcome.
BIND_CHECK_KNOWN = "KNOWN"
BIND_CHECK_UNKNOWN = "UNKNOWN"
#: The property does not exist for this protocol (AXI4-Lite has no ID width),
#: so UNKNOWN would send a reviewer looking for a fact that cannot be found.
BIND_CHECK_NOT_APPLICABLE = "NOT_APPLICABLE"
#: Not merely unproven -- disproven. A bind location whose hierarchy does not
#: exist, or whose signals are not individually reachable, is not a location a
#: human can approve, and it must not be able to average out to PARTIAL.
BIND_CHECK_FAILED = "FAILED"

#: AMBA-15's thirteen points, in the doc's own order and numbering. The tuple
#: is the contract: a validation record is built by iterating it, so a check
#: cannot be silently skipped and a renderer cannot omit a row.
BIND_LOCATION_CHECK_POINTS: tuple = (
    (1, "hierarchy_exists", "hierarchy exists"),
    (2, "amba_signals_exist", "AMBA signals exist"),
    (3, "interface_complete", "interface sufficiently complete"),
    (4, "protocol_identified", "protocol identified"),
    (5, "roles_identified", "endpoint/fabric roles identified"),
    (6, "clock_known", "clock known"),
    (7, "reset_known", "reset known"),
    (8, "address_width_known", "address width known if applicable"),
    (9, "data_width_known", "data width known"),
    (10, "id_width_known", "ID width known if applicable"),
    (11, "user_width_known", "USER widths known where applicable"),
    (12, "parameterization_known", "parameterization known where relevant"),
    (13, "uvm_accessible", "bind/observe accessibility from UVM"),
)

#: AMBA-18's bind-readiness vocabulary. Deliberately NOT `BindTier`: a tier is
#: how much CONFIDENCE the evidence supports for a location, readiness is how
#: much of the required evidence was found at all. A T2 structural match whose
#: clock and reset are unknown is high-confidence and not ready, and one
#: vocabulary cannot say both.
BIND_READINESS_READY = "READY"
BIND_READINESS_PARTIAL = "PARTIAL"
BIND_READINESS_BLOCKED = "BLOCKED"
BIND_READINESS_UNKNOWN = "UNKNOWN"
BIND_READINESS_VALUES: tuple = (BIND_READINESS_READY, BIND_READINESS_PARTIAL,
                                BIND_READINESS_BLOCKED, BIND_READINESS_UNKNOWN)

#: AMBA-15's own word for an unprovable value, used in every `value` field so a
#: JSON dump of a checklist never carries a bare null a reader could mistake
#: for a missing key.
BIND_CHECK_UNKNOWN_VALUE = "UNKNOWN"


def parse_instance_path(path_str) -> tuple:
    """The inverse of `ElaboratedInstance.path_str` -- `"u_a/u_b"` -> `("u_a",
    "u_b")`, and the top module's `"<top>"` (or `""`) -> `()`.

    Exists because the records AMBA-15..20 consume (`VipBindCandidate`,
    `TraceBranch`) carry instance paths as display STRINGS, including ones
    re-loaded from a persisted artifact, while the netlist is keyed on tuples."""
    text = str(path_str or "").strip()
    if not text or text == "<top>":
        return ()
    return tuple(p for p in text.split("/") if p)


@dataclass
class BindLocationCheck:
    """One of AMBA-15's thirteen points, answered."""
    point: int
    key: str
    label: str
    status: str
    value: str
    evidence: str

    def to_dict(self) -> dict:
        return {"point": self.point, "key": self.key, "label": self.label,
                "status": self.status, "value": self.value, "evidence": self.evidence}


@dataclass
class BindLocationValidation:
    """AMBA-15's complete checklist for ONE candidate bind location."""
    instance_path: str
    module_name: str
    bundle_prefix: str
    protocol: str
    checks: list = field(default_factory=list)     # list[BindLocationCheck]

    @property
    def by_key(self) -> dict:
        return {c.key: c for c in self.checks}

    def value_of(self, key: str) -> str:
        check = self.by_key.get(key)
        return check.value if check else BIND_CHECK_UNKNOWN_VALUE

    @property
    def readiness(self) -> str:
        """AMBA-18's READY/PARTIAL/BLOCKED/UNKNOWN for this location.

        BLOCKED dominates: one disproven check is not offset by twelve
        satisfied ones. READY requires every APPLICABLE check known -- a
        NOT_APPLICABLE point is not a gap, so an APB4 slave is not held below
        READY for having no ID width."""
        statuses = [c.status for c in self.checks]
        if BIND_CHECK_FAILED in statuses:
            return BIND_READINESS_BLOCKED
        applicable = [s for s in statuses if s != BIND_CHECK_NOT_APPLICABLE]
        if not applicable:
            return BIND_READINESS_UNKNOWN
        known = sum(1 for s in applicable if s == BIND_CHECK_KNOWN)
        if known == len(applicable):
            return BIND_READINESS_READY
        if known == 0:
            return BIND_READINESS_UNKNOWN
        return BIND_READINESS_PARTIAL

    @property
    def unknown_points(self) -> list:
        return [c.label for c in self.checks if c.status == BIND_CHECK_UNKNOWN]

    @property
    def failed_points(self) -> list:
        return [c.label for c in self.checks if c.status == BIND_CHECK_FAILED]

    def to_dict(self) -> dict:
        return {
            "instance_path": self.instance_path, "module": self.module_name,
            "bundle_prefix": self.bundle_prefix, "protocol": self.protocol,
            "readiness": self.readiness,
            "checks": [c.to_dict() for c in self.checks],
            "unknown_points": self.unknown_points,
            "failed_points": self.failed_points,
        }

    def render_checklist(self) -> str:
        """All thirteen rows, always -- a point that could not be answered is a
        visible UNKNOWN row, never an absent one."""
        rows = [{"point": str(c.point), "check": c.label, "status": c.status,
                 "value": c.value, "evidence": c.evidence} for c in self.checks]
        return render_markdown_table(
            [("point", "#"), ("check", "Check"), ("status", "Status"),
             ("value", "Value"), ("evidence", "Evidence")],
            rows, aligns={"point": "right"})


def _check(point_key: str, status: str, value: str, evidence: str) -> BindLocationCheck:
    point, key, label = next(p for p in BIND_LOCATION_CHECK_POINTS if p[1] == point_key)
    return BindLocationCheck(point=point, key=key, label=label, status=status,
                             value=value, evidence=evidence)


def _role_width_check(point_key: str, role: str, instance: ElaboratedInstance,
                      bundle: Optional[AmbaBundle], protocol: str) -> BindLocationCheck:
    """AMBA-15 points 8-11: one signal role's bit width, read off the real
    declared port types.

    The width parser is `phy_boundary.parse_port_width()` -- imported, not
    re-implemented, because it already answers None (rather than a defaulted 1)
    for a parameterized `[DW-1:0]` range, and a second width parser in this
    repo would be a second chance to disagree about that.

    Two ports of the same role that disagree (`AWADDR[31:0]` against
    `ARADDR[15:0]`) is UNKNOWN with both widths named, never the first one
    found: a fabric port whose read and write address widths differ is a real
    finding, and silently reporting one of them would erase it."""
    applicable_roles = AMBA_PROTOCOL_SIGNAL_ROLES.get(protocol)
    if applicable_roles is not None and role not in applicable_roles:
        return _check(point_key, BIND_CHECK_NOT_APPLICABLE, "N/A",
                      f"{protocol} has no {role.lower()} signals")
    ports = [p for p in (bundle.ports if bundle else []) if amba_signal_role(p) == role]
    if not ports:
        if applicable_roles is None:
            return _check(point_key, BIND_CHECK_UNKNOWN, BIND_CHECK_UNKNOWN_VALUE,
                          f"protocol unresolved and no {role.lower()} signal is present "
                          "on this interface, so neither the width nor its "
                          "applicability is established")
        return _check(point_key, BIND_CHECK_UNKNOWN, BIND_CHECK_UNKNOWN_VALUE,
                      f"{protocol} has {role.lower()} signals but none is present on "
                      "this interface")
    widths: dict = {}
    unresolved: list = []
    for port in sorted(ports):
        width = parse_port_width(instance.port_data_types.get(port))
        if width is None:
            unresolved.append(f"{port}={instance.port_data_types.get(port)!r}")
        else:
            widths.setdefault(width, []).append(port)
    if unresolved:
        return _check(point_key, BIND_CHECK_UNKNOWN, BIND_CHECK_UNKNOWN_VALUE,
                      "declared width could not be resolved to literal bounds for "
                      + ", ".join(unresolved))
    if len(widths) > 1:
        detail = "; ".join(f"{w}: {', '.join(ps)}" for w, ps in sorted(widths.items()))
        return _check(point_key, BIND_CHECK_UNKNOWN, BIND_CHECK_UNKNOWN_VALUE,
                      f"{role.lower()} signals of this interface disagree on width -- "
                      + detail)
    width = next(iter(widths))
    return _check(point_key, BIND_CHECK_KNOWN, str(width),
                  "declared port width of " + ", ".join(sorted(ports)))


def _clock_reset_check(point_key: str, kind: str, verdict: dict) -> BindLocationCheck:
    if verdict["status"] == CLOCK_RESET_RESOLVED:
        return _check(point_key, BIND_CHECK_KNOWN, verdict["port"],
                      f"{kind} port on this instance, matched {verdict['evidence']}")
    if verdict["candidates"]:
        return _check(point_key, BIND_CHECK_UNKNOWN, BIND_CHECK_UNKNOWN_VALUE,
                      f"{len(verdict['candidates'])} candidate {kind} ports and no "
                      "evidence which drives this interface: "
                      + ", ".join(verdict["candidates"]))
    return _check(point_key, BIND_CHECK_UNKNOWN, BIND_CHECK_UNKNOWN_VALUE,
                  f"no port on this instance carries a {kind} name")


def _uvm_accessibility_check(netlist: FabricNetlist, path_str: str,
                             instance: ElaboratedInstance,
                             bundle: Optional[AmbaBundle]) -> BindLocationCheck:
    """AMBA-15 point 13: can a UVM interface handle actually observe these
    signals at this location.

    Structural, not a guess: the obstacles are the ones the elaboration
    genuinely recorded -- a port whose formal name could not be resolved
    (`POSITIONAL_PORT_UNRESOLVED`), and a port driven by a concatenation or
    expression rather than one equipotential net, which is not a signal a
    monitor can be pointed at.

    It deliberately does NOT check this project's Bind-Location Rules 1-4 (bare
    module name vs. full path, generate-loop targets, the centralized
    `*_bind.sv` file). Those govern how a bind statement is WRITTEN, and
    AMBA-30/AMBA-31 hold every bind statement behind human review -- nothing in
    this module is authorised to write one, so nothing here validates one."""
    ports = set(bundle.ports if bundle else [])
    if POSITIONAL_PORT_UNRESOLVED in instance.port_names:
        return _check("uvm_accessible", BIND_CHECK_FAILED, "PORT_NAMES_UNRESOLVED",
                      f"{path_str} has positional connections into an unparsed module, "
                      "so which formal port each signal is cannot be established")
    split = [s for s in netlist.split_connections
             if s["path"] == path_str and s["port"] in ports]
    if split:
        return _check("uvm_accessible", BIND_CHECK_UNKNOWN, BIND_CHECK_UNKNOWN_VALUE,
                      "driven by a multi-net expression rather than one net: "
                      + ", ".join(sorted(s["port"] for s in split)))
    if not ports:
        return _check("uvm_accessible", BIND_CHECK_FAILED, "NO_SIGNALS",
                      "no AMBA bundle at this location to observe")
    if instance.is_blackbox:
        return _check("uvm_accessible", BIND_CHECK_UNKNOWN, BIND_CHECK_UNKNOWN_VALUE,
                      f"the hierarchy path {path_str} exists, but module "
                      f"{instance.module_name} is not in the parsed source set, so "
                      "whether its boundary exposes these signals individually (rather "
                      "than through a SystemVerilog interface port) is not established")
    return _check("uvm_accessible", BIND_CHECK_KNOWN, path_str,
                  f"{len(ports)} individually-named ports on a real elaborated "
                  "instance path, each on a single equipotential net")


def validate_vip_bind_location(netlist: FabricNetlist, instance_path,
                               bundle_prefix: str) -> BindLocationValidation:
    """AMBA-15's thirteen-point validation of one proposed bind location.

    `instance_path` may be a tuple or the display string a `VipBindCandidate`
    carries. The location is validated against the ELABORATED netlist, so
    "hierarchy exists" means this exact instance path was really elaborated
    from parsed RTL -- not that a module of that name exists somewhere."""
    path = instance_path if isinstance(instance_path, tuple) \
        else parse_instance_path(instance_path)
    instance = netlist.instance(path)
    path_str = "/".join(path) if path else "<top>"
    if instance is None:
        # Every remaining point rests on the instance existing. Reporting them
        # as twelve UNKNOWNs would suggest twelve separate things to go find
        # out, when there is exactly one.
        checks = [_check("hierarchy_exists", BIND_CHECK_FAILED, "NOT_FOUND",
                         f"{path_str} is not an elaborated instance of top module "
                         f"{netlist.top_module}")]
        checks += [_check(key, BIND_CHECK_FAILED, "NOT_EVALUATED_HIERARCHY_MISSING",
                          "not evaluated: the bind location itself does not exist")
                   for _, key, _ in BIND_LOCATION_CHECK_POINTS[1:]]
        return BindLocationValidation(instance_path=path_str, module_name="",
                                      bundle_prefix=bundle_prefix,
                                      protocol=AMBA_PROTOCOL_UNRESOLVED, checks=checks)

    bundle = find_bundle(netlist, path, bundle_prefix)
    classification = bundle.classification if bundle else None
    protocol = bundle.protocol if bundle else AMBA_PROTOCOL_UNRESOLVED
    checks: list = []

    checks.append(_check("hierarchy_exists", BIND_CHECK_KNOWN, path_str,
                         f"elaborated instance of module {instance.module_name} under "
                         f"top module {netlist.top_module}"))

    if bundle and bundle.ports:
        checks.append(_check(
            "amba_signals_exist", BIND_CHECK_KNOWN, f"{len(bundle.ports)} signals",
            "AMBA-named ports on this boundary: "
            + ", ".join(sorted(classification.evidence_signals))))
    else:
        checks.append(_check(
            "amba_signals_exist", BIND_CHECK_FAILED, "NONE",
            f"no AMBA bundle with prefix {bundle_prefix!r} on {path_str}"))

    if classification is None:
        checks.append(_check("interface_complete", BIND_CHECK_FAILED, "NO_INTERFACE",
                             "there is no interface here to be complete"))
        checks.append(_check("protocol_identified", BIND_CHECK_FAILED, "NO_INTERFACE",
                             "there is no interface here to classify"))
    elif classification.status == AmbaClassificationStatus.RESOLVED.value:
        checks.append(_check("interface_complete", BIND_CHECK_KNOWN, "COMPLETE",
                             "every core signal of the "
                             f"{classification.family} family is present"))
        checks.append(_check("protocol_identified", BIND_CHECK_KNOWN,
                             classification.display_name,
                             "; ".join(classification.discriminators)
                             or "signal-set classification"))
    else:
        missing = ", ".join(classification.missing_signals) or "none named"
        checks.append(_check("interface_complete", BIND_CHECK_UNKNOWN,
                             BIND_CHECK_UNKNOWN_VALUE,
                             f"{classification.status}; missing: {missing}"))
        checks.append(_check("protocol_identified", BIND_CHECK_UNKNOWN,
                             BIND_CHECK_UNKNOWN_VALUE,
                             f"{classification.status}; candidates: "
                             + (", ".join(classification.candidates) or "none")))

    roles = bundle.roles if bundle else None
    if roles is not None and roles.resolved:
        checks.append(_check("roles_identified", BIND_CHECK_KNOWN,
                             f"{roles.fabric_side_role} / {roles.external_endpoint_role}",
                             roles.direction_evidence))
    elif roles is not None:
        checks.append(_check("roles_identified", BIND_CHECK_UNKNOWN,
                             BIND_CHECK_UNKNOWN_VALUE,
                             roles.unresolved_reason or "direction evidence did not "
                             "settle which perspective this interface holds"))
    else:
        checks.append(_check("roles_identified", BIND_CHECK_UNKNOWN,
                             BIND_CHECK_UNKNOWN_VALUE,
                             f"module {instance.module_name} declares no port "
                             "directions (not in the parsed source set), so neither "
                             "perspective can be derived"))

    clock_reset = find_amba_clock_reset_ports(protocol, bundle_prefix, instance.port_names)
    checks.append(_clock_reset_check("clock_known", "clock", clock_reset["clock"]))
    checks.append(_clock_reset_check("reset_known", "reset", clock_reset["reset"]))

    checks.append(_role_width_check("address_width_known", AMBA_SIGNAL_ROLE_ADDRESS,
                                    instance, bundle, protocol))
    checks.append(_role_width_check("data_width_known", AMBA_SIGNAL_ROLE_DATA,
                                    instance, bundle, protocol))
    checks.append(_role_width_check("id_width_known", AMBA_SIGNAL_ROLE_ID,
                                    instance, bundle, protocol))
    checks.append(_role_width_check("user_width_known", AMBA_SIGNAL_ROLE_USER,
                                    instance, bundle, protocol))

    if instance.is_blackbox:
        checks.append(_check("parameterization_known", BIND_CHECK_UNKNOWN,
                             BIND_CHECK_UNKNOWN_VALUE,
                             f"module {instance.module_name} is not in the parsed "
                             "source set, so its parameter list is unknown"))
    elif instance.parameters:
        named = ", ".join(f"{p.get('name')}={p.get('default_text')}"
                          for p in instance.parameters)
        checks.append(_check("parameterization_known", BIND_CHECK_KNOWN,
                             f"{len(instance.parameters)} parameters",
                             "declared parameters: " + named))
    else:
        checks.append(_check("parameterization_known", BIND_CHECK_KNOWN, "NONE",
                             f"module {instance.module_name} is parsed and declares "
                             "no parameters"))

    checks.append(_uvm_accessibility_check(netlist, path_str, instance, bundle))
    return BindLocationValidation(instance_path=path_str,
                                  module_name=instance.module_name,
                                  bundle_prefix=bundle_prefix, protocol=protocol,
                                  checks=checks)


# ===========================================================================
# AMBA-16..20: the four mandated review artifacts
#
# All four are derived from the SAME `FabricPortTrace` list and the same
# AMBA-15 validations -- never recomputed independently -- so the bind matrix,
# the unresolved table, the summary counts, the tree and the VIP instance plan
# cannot disagree with each other about a port. Every one is a planning
# document a human reads at AMBA-30's gate; none emits SystemVerilog.
# ===========================================================================

def _display_protocol(protocol: str) -> str:
    """The doc's own spelling ("AXI4-Lite", not "AXI4_LITE") for any
    human-facing table."""
    return AMBA4_DISPLAY_NAMES.get(protocol, protocol)


def _bundle_of_trace(netlist: FabricNetlist, trace: FabricPortTrace) -> Optional[AmbaBundle]:
    return find_bundle(netlist, parse_instance_path(trace.fabric_instance_path),
                       trace.bundle_prefix)


def _external_endpoint_role(bundle: Optional[AmbaBundle]) -> str:
    if bundle is None or bundle.roles is None:
        return ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS
    return bundle.roles.external_endpoint_role


#: Worst-first, for aggregating several branches' readiness into the one status
#: their parent fabric port carries. A port with one BLOCKED branch is not a
#: READY port, and a port whose branches are half-planned is PARTIAL at best.
_READINESS_SEVERITY = {BIND_READINESS_BLOCKED: 0, BIND_READINESS_UNKNOWN: 1,
                       BIND_READINESS_PARTIAL: 2, BIND_READINESS_READY: 3}


def _worst_readiness(values) -> str:
    vals = [v for v in values if v in _READINESS_SEVERITY]
    if not vals:
        return BIND_READINESS_UNKNOWN
    return min(vals, key=lambda v: _READINESS_SEVERITY[v])


def _cap_below_ready(readiness: str) -> str:
    """READY means "nothing further is needed before a human approves this
    location". A port with an open AMBA-12/13 branch choice does not qualify
    however clean each branch is, so its readiness is held at PARTIAL."""
    return BIND_READINESS_PARTIAL if readiness == BIND_READINESS_READY else readiness


#: AMBA-16's twelve mandated columns, in the doc's own order. `(key, header)`
#: pairs: the key is what a JSON row carries, the header is what the markdown
#: table prints.
AMBA16_MATRIX_COLUMNS: tuple = (
    ("fabric_port", "Fabric Port"),
    ("protocol", "Protocol"),
    ("fabric_role", "Fabric Role"),
    ("external_endpoint_role", "External Endpoint Role"),
    ("endpoint", "Endpoint"),
    ("trace_path", "Trace Path"),
    ("proposed_vip_bind_hierarchy", "Proposed VIP Bind Hierarchy"),
    ("vip_role", "VIP Role"),
    ("clock", "Clock"),
    ("reset", "Reset"),
    ("confidence", "Confidence"),
    ("status", "Status"),
)

#: What a parent row of a MULTIPLE_SOURCE / MULTIPLE_DESTINATION port carries
#: instead of a bind hierarchy. AMBA-12/13 forbid choosing one branch, so the
#: parent names none of them and the child rows carry the real candidates.
MULTIPLE_BRANCH_PARENT_BIND = "MULTIPLE_CANDIDATE_LOCATIONS_SEE_CHILD_ROWS"


def _candidate_cells(netlist: FabricNetlist, candidate: Optional[VipBindCandidate]) -> dict:
    """The five columns that come from a proposed bind LOCATION, plus the
    AMBA-15 validation they were read out of."""
    if candidate is None:
        return {
            "proposed_vip_bind_hierarchy": REQUIRED_HUMAN_INPUT,
            "vip_role": REQUIRED_HUMAN_INPUT,
            "clock": BIND_CHECK_UNKNOWN_VALUE,
            "reset": BIND_CHECK_UNKNOWN_VALUE,
            "confidence": REQUIRED_HUMAN_INPUT,
            "status": BIND_READINESS_BLOCKED,
            "validation": None,
        }
    path = parse_instance_path(candidate.instance_path)
    validation = validate_vip_bind_location(netlist, path, candidate.bundle_prefix)
    bundle = find_bundle(netlist, path, candidate.bundle_prefix)
    # The VIP watches the CANDIDATE interface, not the fabric port -- for a
    # bind pushed out to a CPU's own master port those are opposite
    # perspectives, and reporting the fabric port's role here would describe
    # the wrong end of the link.
    vip_role = (bundle.roles.vip_role if bundle and bundle.roles and bundle.roles.vip_role
                else ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS)
    return {
        "proposed_vip_bind_hierarchy": f"{candidate.instance_path}:{candidate.bundle_prefix}",
        "vip_role": vip_role,
        "clock": validation.value_of("clock_known"),
        "reset": validation.value_of("reset_known"),
        "confidence": candidate.bind_tier,
        "status": validation.readiness,
        "validation": validation,
    }


def _branch_candidate(trace: FabricPortTrace,
                      branch: Optional[TraceBranch]) -> Optional[VipBindCandidate]:
    """The best candidate for one branch, falling back to AMBA-8's P4 (the
    fabric port itself) so a branch that found nothing better still names a
    real, watchable boundary rather than dropping out of the plan."""
    pool = list(branch.candidates) if branch is not None else []
    pool += list(trace.fallback_candidates)
    if not pool:
        return None
    return sorted(pool, key=lambda c: (_priority_rank(VipPlacementPriority(c.priority)),
                                       c.instance_path))[0]


def _endpoint_cell(trace: FabricPortTrace, branch: Optional[TraceBranch]) -> str:
    """The endpoint, or -- when there is none -- the AMBA-14 status saying why.
    An empty cell would read as "not looked into"."""
    if branch is not None and branch.endpoint_instance_path:
        return f"{branch.endpoint_instance_path} ({branch.endpoint_module})"
    return f"{trace.status} (no endpoint established)"


def build_fabric_vip_bind_matrix(netlist: FabricNetlist, traces) -> list:
    """AMBA-16's mandatory primary output: one row per fabric port, plus child
    rows for every branch of a multiple-source / multiple-destination port.

    Every traced fabric port appears, including one whose trace resolved
    nothing -- AMBA-16 says "every fabric port must appear", and a port silently
    absent from the matrix is the omission that makes the whole artifact
    unreviewable.

    Rows carry `row_id`/`parent_row_id` beyond the twelve rendered columns, so
    `connectivity.RowLockStore` can lock and diff them per row with no changes
    of its own -- it is already generic over `(row_id, dict)`."""
    rows: list = []
    for trace in traces or ():
        bundle = _bundle_of_trace(netlist, trace)
        base = {
            "fabric_port": trace.interface_id,
            "protocol": _display_protocol(trace.fabric_protocol),
            "fabric_role": trace.fabric_side_role,
            "external_endpoint_role": _external_endpoint_role(bundle),
            "trace_status": trace.status,
            "row_id": trace.interface_id,
            "parent_row_id": None,
        }
        multi = trace.status in (TraceTerminationStatus.MULTIPLE_SOURCE.value,
                                 TraceTerminationStatus.MULTIPLE_DESTINATION.value)
        if multi and trace.branches:
            children: list = []
            for idx, branch in enumerate(trace.branches, 1):
                cells = _candidate_cells(netlist, _branch_candidate(trace, branch))
                child = dict(base)
                child.update({
                    "row_id": f"{trace.interface_id}#branch{idx}",
                    "parent_row_id": trace.interface_id,
                    "fabric_port": f"{trace.interface_id} [branch {idx}]",
                    "endpoint": _endpoint_cell(trace, branch),
                    # The bare hierarchy, alongside the rendered `endpoint`
                    # cell: AMBA-22's `endpoint_hierarchy` column is a path a
                    # downstream consumer resolves, not display text, and
                    # re-parsing it back out of "path (module)" in another
                    # module would be a second place to get it wrong.
                    "endpoint_instance_path": branch.endpoint_instance_path or "",
                    "trace_path": " -> ".join(h.instance_path for h in branch.hops) or "-",
                    "trace_status": branch.status,
                })
                child.update(cells)
                children.append(child)
            parent = dict(base)
            parent.update({
                "endpoint": f"{len(children)} branches enumerated below "
                            f"({trace.status})",
                "endpoint_instance_path": MULTIPLE_BRANCH_PARENT_BIND,
                "trace_path": "-",
                "proposed_vip_bind_hierarchy": MULTIPLE_BRANCH_PARENT_BIND,
                "vip_role": REQUIRED_HUMAN_INPUT,
                "clock": BIND_CHECK_UNKNOWN_VALUE,
                "reset": BIND_CHECK_UNKNOWN_VALUE,
                # Not a tier: which of several enumerated branches to watch is
                # a verification-architecture decision, not a confidence one.
                "confidence": REQUIRED_HUMAN_INPUT,
                # Capped below READY even when every branch validates cleanly:
                # AMBA-12/13 leave the choice of which branches to observe to a
                # human, so the PORT still has an open decision on it. Calling
                # it READY would claim a decision nobody has made.
                "status": _cap_below_ready(
                    _worst_readiness(c["status"] for c in children)),
                "validation": None,
            })
            rows.append(parent)
            rows.extend(children)
            continue
        branch = trace.branches[0] if trace.branches else None
        row = dict(base)
        row.update({
            "endpoint": _endpoint_cell(trace, branch),
            "endpoint_instance_path": (branch.endpoint_instance_path or "") if branch else "",
            "trace_path": (" -> ".join(h.instance_path for h in branch.hops)
                           if branch else "-") or "-",
        })
        row.update(_candidate_cells(netlist, _branch_candidate(trace, branch)))
        rows.append(row)
        rows.extend(_bridge_second_side_rows(netlist, trace, base))
    return rows


def _bridge_second_side_rows(netlist: FabricNetlist, trace: FabricPortTrace,
                             base: dict) -> list:
    """AMBA-11's VIP-B: one subordinate row per protocol bridge the trace
    crossed, carrying the DOWNSTREAM side's own protocol and its own candidate
    location.

    Recorded here, and deliberately NOT auto-planned as a VIP instance
    (`amba11_second_side` makes `build_vip_instance_plan()` skip it): AMBA-11
    says to record both sides but to "recommend both only when justified by
    verification goals", so the downstream side is evidence a reviewer decides
    on, not a VIP the plan asks for on its own initiative.

    The downstream protocol is the bridge's own independent classification --
    it is never inherited from the upstream side, which is what makes "do not
    label a downstream APB endpoint as AXI" impossible to violate here."""
    out: list = []
    for idx, bridge in enumerate(trace.bridges or (), 1):
        bridge_path = parse_instance_path(bridge.bridge_instance_path)
        bundle = find_bundle(netlist, bridge_path, bridge.downstream_bundle_prefix)
        candidate = _make_candidate(
            bundle, VipPlacementPriority.P1_TRUE_IP_AMBA_BOUNDARY,
            "AMBA-11 VIP-B: the downstream side of the protocol bridge this port's "
            "trace terminated at") if bundle else None
        row = dict(base)
        row.update({
            "row_id": f"{trace.interface_id}#bridge{idx}",
            "parent_row_id": trace.interface_id,
            "amba11_second_side": True,
            "fabric_port": f"{trace.interface_id} [AMBA-11 VIP-B @ "
                           f"{bridge.bridge_instance_path}]",
            "protocol": _display_protocol(bridge.downstream_protocol),
            "fabric_role": (bundle.fabric_side_role if bundle
                            else ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS),
            "external_endpoint_role": _external_endpoint_role(bundle),
            "endpoint": f"{bridge.bridge_instance_path} ({bridge.bridge_module}) "
                        "downstream side -- what lies beyond it is a separate trace",
            "endpoint_instance_path": bridge.bridge_instance_path,
            "trace_path": f"{trace.fabric_instance_path} -> "
                          f"{bridge.bridge_instance_path}",
            "trace_status": TraceTerminationStatus.PROTOCOL_BRIDGE_FOUND.value,
        })
        row.update(_candidate_cells(netlist, candidate))
        out.append(row)
    return out


def render_fabric_vip_bind_matrix(rows) -> str:
    """AMBA-16's table in the doc's exact twelve-column shape."""
    return render_markdown_table(list(AMBA16_MATRIX_COLUMNS), rows,
                                 empty_note="(no fabric port was traced)")


def parent_matrix_rows(rows) -> list:
    """The one-row-per-fabric-port view of the matrix. Counting over the raw
    row list would count a multiple-destination port once per branch."""
    return [r for r in rows or () if not r.get("parent_row_id")]


# ===========================================================================
# AMBA-17: UNRESOLVED PORT TABLE (mandatory even when empty)
# ===========================================================================

AMBA17_UNRESOLVED_COLUMNS: tuple = (
    ("fabric_port", "Fabric Port"),
    ("protocol", "Protocol"),
    ("fabric_role", "Fabric Role"),
    ("trace_result", "Trace Result"),
    ("last_known_hierarchy", "Last Known Hierarchy"),
    ("why_not_found", "Why Endpoint/Bind Not Found"),
    ("missing_evidence", "Missing Evidence"),
    ("next_best_action", "Next-Best-Action"),
)

#: One next action per AMBA-14 termination state. A table keyed on the state
#: rather than free prose per port means the advice cannot silently differ
#: between two ports that failed for the same reason.
NEXT_BEST_ACTION_BY_STATUS: dict = {
    TraceTerminationStatus.SOURCE_NOT_FOUND.value:
        "Add the missing driver's RTL to the parse set, or confirm the initiating master "
        "is outside the parsed design and watch the fabric boundary itself (AMBA-8 P4).",
    TraceTerminationStatus.DESTINATION_NOT_FOUND.value:
        "Add the missing target's RTL to the parse set, or confirm the destination slave "
        "is outside the parsed design and watch the fabric boundary itself (AMBA-8 P4).",
    TraceTerminationStatus.TRACE_BLOCKED.value:
        "Supply the unparsed module's RTL (or at minimum its port list) so the trace can "
        "continue through it; do not assume it is the endpoint.",
    TraceTerminationStatus.AMBIGUOUS.value:
        "Human review: the correspondence between this module's interfaces is not visible "
        "at syntax level. Confirm which bundles correspond before any VIP is placed.",
    TraceTerminationStatus.MULTIPLE_SOURCE.value:
        "Confirm which of the enumerated sources need independent VIP observation "
        "(AMBA-12 forbids collapsing them to one); each child row is a separate decision.",
    TraceTerminationStatus.MULTIPLE_DESTINATION.value:
        "Confirm which of the enumerated destinations need independent VIP observation "
        "(AMBA-13 forbids claiming a single final slave); each child row is a separate "
        "decision.",
    TraceTerminationStatus.INTERNAL_ONLY.value:
        "Confirm whether this fabric-internal interface needs VIP observation at all; if "
        "it does, the internal peer is the bind location.",
}

#: Used when the TRACE resolved but the proposed bind LOCATION did not pass
#: AMBA-15 -- a different failure from an unresolved trace, and one whose next
#: action is about evidence at the bind point rather than about the traversal.
NEXT_BEST_ACTION_BIND_BLOCKED = (
    "The endpoint was traced, but the bind location failed AMBA-15 validation. Resolve "
    "the failed checks listed under 'Why Endpoint/Bind Not Found' before proposing this "
    "location to a reviewer.")
NEXT_BEST_ACTION_NO_CANDIDATE = (
    "No watchable AMBA boundary was found for this port at any AMBA-8 priority. Confirm "
    "whether the interface is observable at all, or route it to the question queue.")


def _last_known_hierarchy(trace: FabricPortTrace) -> str:
    """The deepest point the trace actually reached -- AMBA-17's own
    requirement that an unresolved row still says where it got to."""
    deepest = ""
    for branch in trace.branches:
        for hop in branch.hops:
            if len(hop.instance_path.split("/")) > len(deepest.split("/")) or not deepest:
                deepest = hop.instance_path
    return deepest or trace.fabric_instance_path


def build_unresolved_fabric_port_table(netlist: FabricNetlist, traces,
                                       matrix_rows=None) -> list:
    """AMBA-17: every fabric port whose endpoint OR whose bind location is not
    established, with the reason, the missing evidence and a next action.

    Two distinct populations, deliberately in one table because AMBA-17's
    column set fits both and a reviewer wants one list of "what is not ready":
    a port whose AMBA-14 trace ended in an unresolved state, and a port whose
    trace resolved but whose proposed bind location failed an AMBA-15 check
    (or has no candidate location at all)."""
    rows = matrix_rows if matrix_rows is not None else \
        build_fabric_vip_bind_matrix(netlist, traces)
    by_port = {r["row_id"]: r for r in rows}
    out: list = []
    for trace in traces or ():
        row = by_port.get(trace.interface_id)
        unresolved_trace = trace.status in {s.value for s in UNRESOLVED_TERMINATION_STATUSES}
        blocked_bind = bool(row) and row.get("status") == BIND_READINESS_BLOCKED
        if not (unresolved_trace or blocked_bind):
            continue
        why: list = []
        missing = list(trace.missing_evidence)
        if unresolved_trace and trace.reason:
            why.append(trace.reason)
        validation = (row or {}).get("validation")
        if blocked_bind and validation is not None:
            why.extend(f"AMBA-15 check failed: {p}" for p in validation.failed_points)
            missing.extend(c.evidence for c in validation.checks
                           if c.status == BIND_CHECK_FAILED)
        if blocked_bind and validation is None and not unresolved_trace:
            why.append("no VIP bind candidate location was found for this port")
        if unresolved_trace:
            action = NEXT_BEST_ACTION_BY_STATUS.get(trace.status, REQUIRED_HUMAN_INPUT)
        elif validation is None:
            action = NEXT_BEST_ACTION_NO_CANDIDATE
        else:
            action = NEXT_BEST_ACTION_BIND_BLOCKED
        out.append({
            "fabric_port": trace.interface_id,
            "protocol": _display_protocol(trace.fabric_protocol),
            "fabric_role": trace.fabric_side_role,
            "trace_result": trace.status,
            "last_known_hierarchy": _last_known_hierarchy(trace),
            "why_not_found": "; ".join(why) or REQUIRED_HUMAN_INPUT,
            "missing_evidence": "; ".join(dict.fromkeys(missing)) or "-",
            "next_best_action": action,
            "row_id": trace.interface_id,
        })
    return out


def render_unresolved_fabric_port_table(rows) -> str:
    """AMBA-17's table, rendered even when empty -- "every fabric port
    resolved" and "this table was never produced" must not look alike to a
    reviewer."""
    return render_markdown_table(
        list(AMBA17_UNRESOLVED_COLUMNS), rows,
        empty_note="(none -- every traced fabric port reached a resolved endpoint and a "
                   "validated bind location)")


# ===========================================================================
# AMBA-18: TOPOLOGY SUMMARY
# ===========================================================================

def _fabric_interface_records(netlist: FabricNetlist, traces) -> list:
    """One AMBA-6-shaped record per traced fabric port, for the count table.

    Plain dicts rather than `AmbaFabricInterface` objects on purpose: a bundle
    on a black-box instance has no port directions and therefore no
    `AmbaInterfaceRoles` at all, and `build_protocol_interface_count_table()`
    already accepts this dict shape (it is the form a re-loaded artifact takes)
    and already counts a role-unresolved interface in the totals without
    filing it as slave or master."""
    records: list = []
    for trace in traces or ():
        bundle = _bundle_of_trace(netlist, trace)
        records.append({
            "interface": trace.interface_id,
            "protocol": trace.fabric_protocol,
            "status": (bundle.classification.status if bundle
                       else AmbaClassificationStatus.UNRESOLVED_PARTIAL_EVIDENCE.value),
            "fabric_side_role": trace.fabric_side_role,
        })
    return records


def build_amba_topology_summary(netlist: FabricNetlist, traces,
                                matrix_rows=None) -> dict:
    """AMBA-18: the port totals, the per-protocol counts across all ten AMBA-4
    protocols, and the READY/PARTIAL/BLOCKED/UNKNOWN bind-readiness tally.

    The counts are `connectivity.build_protocol_interface_count_table()`'s --
    the AMBA-6 table, reused rather than recomputed, so AMBA-6 and AMBA-18 can
    never report different totals for the same fabric. Readiness is tallied
    over PARENT rows only: a multiple-destination port is one port, not one per
    branch."""
    table = build_protocol_interface_count_table(_fabric_interface_records(netlist, traces))
    rows = matrix_rows if matrix_rows is not None else \
        build_fabric_vip_bind_matrix(netlist, traces)
    readiness = {value: 0 for value in BIND_READINESS_VALUES}
    for row in parent_matrix_rows(rows):
        status = row.get("status")
        readiness[status] = readiness.get(status, 0) + 1
    return {
        "total_fabric_slave_ports": table["total_fabric_slave_ports"],
        "total_fabric_master_ports": table["total_fabric_master_ports"],
        "total_amba_ports": table["total_amba_ports"],
        "protocol_counts": table,
        "bind_readiness": readiness,
        "trace_terminations": summarize_trace_terminations(traces),
    }


def render_amba_topology_summary(summary: dict) -> str:
    """AMBA-18's three totals, the ten protocol rows, and the readiness tally."""
    lines = ["### Port counts and per-protocol breakdown (AMBA-18)", "",
             render_protocol_interface_count_table(summary["protocol_counts"]).rstrip(),
             "", "### Bind readiness", ""]
    lines.append(render_markdown_table(
        [("readiness", "Bind Readiness"), ("ports", "Fabric Ports")],
        [{"readiness": value, "ports": summary["bind_readiness"].get(value, 0)}
         for value in BIND_READINESS_VALUES],
        aligns={"ports": "right"}))
    lines += ["", "### Trace termination status (AMBA-14)", ""]
    lines.append(render_markdown_table(
        [("status", "Termination Status"), ("ports", "Fabric Ports")],
        [{"status": status.value,
          "ports": summary["trace_terminations"].get(status.value, 0)}
         for status in TraceTerminationStatus],
        aligns={"ports": "right"}))
    return "\n".join(lines)


# ===========================================================================
# AMBA-19: TOPOLOGY TREE
# ===========================================================================

#: The literal ASCII connectors AMBA-19's example uses. A mermaid flowchart of
#: the same information already exists (`connectivity.render_hierarchy_diagram()`)
#: and is kept -- it is the right artifact for a rendered document, while this
#: is the one the doc mandates and the one that survives a plain-text review
#: comment.
TREE_BRANCH = "|-- "
TREE_LAST_BRANCH = "\\-- "
TREE_PIPE = "|   "
TREE_BLANK = "    "


def _tree_child_lines(entries: list, prefix: str) -> list:
    """Render `[(label, [children...]), ...]` under one parent, with the last
    entry closing its branch."""
    lines: list = []
    for idx, (label, children) in enumerate(entries):
        last = idx == len(entries) - 1
        lines.append(prefix + (TREE_LAST_BRANCH if last else TREE_BRANCH) + label)
        lines.extend(_tree_child_lines(
            children, prefix + (TREE_BLANK if last else TREE_PIPE)))
    return lines


def render_topology_tree(netlist: FabricNetlist, traces, matrix_rows=None) -> str:
    """AMBA-19's discovered-hierarchy tree.

    `<fabric port> : <protocol> / <fabric role>` -> `<endpoint>` ->
    `VIP_BIND_CANDIDATE = <hierarchy>`, and an unresolved branch shows its last
    known hierarchy and its trace status, exactly as AMBA-19 requires.

    The candidate line says CANDIDATE, and says it in a form
    `connectivity.parse_bind_line()` does not recognise as a bind statement,
    because AMBA-30 holds every bind behind human review and a plan artifact
    that reads like emitted code is how that gate gets skipped by accident."""
    rows = matrix_rows if matrix_rows is not None else \
        build_fabric_vip_bind_matrix(netlist, traces)
    by_id = {r["row_id"]: r for r in rows}
    entries: list = []
    for trace in traces or ():
        label = (f"{trace.interface_id} : {_display_protocol(trace.fabric_protocol)} / "
                 f"{trace.fabric_side_role}")
        children: list = []
        multi = trace.status in (TraceTerminationStatus.MULTIPLE_SOURCE.value,
                                 TraceTerminationStatus.MULTIPLE_DESTINATION.value)
        branch_rows = [(idx, branch,
                        by_id.get(f"{trace.interface_id}#branch{idx}"
                                  if multi else trace.interface_id))
                       for idx, branch in enumerate(trace.branches, 1)]
        if not branch_rows:
            children.append((f"UNRESOLVED [{trace.status}]", [
                (f"LAST_KNOWN_HIERARCHY = {_last_known_hierarchy(trace)}", []),
                (f"REASON = {trace.reason or REQUIRED_HUMAN_INPUT}", []),
            ]))
        for idx, branch, row in branch_rows:
            grandchildren: list = []
            bind = (row or {}).get("proposed_vip_bind_hierarchy")
            if bind and bind not in (REQUIRED_HUMAN_INPUT, MULTIPLE_BRANCH_PARENT_BIND):
                grandchildren.append(
                    (f"VIP_BIND_CANDIDATE = {bind} "
                     f"[{(row or {}).get('confidence')}, {(row or {}).get('status')}]", []))
            else:
                grandchildren.append((f"VIP_BIND_CANDIDATE = {REQUIRED_HUMAN_INPUT}", []))
            if branch.endpoint_instance_path:
                endpoint_label = (f"{branch.endpoint_instance_path} "
                                  f"({branch.endpoint_module}) [{branch.status}]")
            else:
                endpoint_label = f"UNRESOLVED [{branch.status}]"
                grandchildren.insert(0, (
                    f"LAST_KNOWN_HIERARCHY = "
                    f"{branch.hops[-1].instance_path if branch.hops else trace.fabric_instance_path}",
                    []))
                grandchildren.insert(1, (
                    f"REASON = {branch.reason or trace.reason or REQUIRED_HUMAN_INPUT}", []))
            if multi:
                endpoint_label = f"branch {idx}: {endpoint_label}"
            children.append((endpoint_label, grandchildren))
        entries.append((label, children))
    return "\n".join(["BUS_FABRIC"] + _tree_child_lines(entries, ""))


# ===========================================================================
# AMBA-20: VIP INSTANCE PLAN
# ===========================================================================

AMBA20_VIP_PLAN_COLUMNS: tuple = (
    ("vip_id", "VIP_ID"),
    ("protocol", "Protocol"),
    ("endpoint", "Endpoint"),
    ("vip_mode", "VIP Mode"),
    ("active_passive", "Active/Passive"),
    ("master_slave_monitor", "Master/Slave/Monitor"),
    ("bind_hierarchy", "Bind Hierarchy"),
    ("clock", "Clock"),
    ("reset", "Reset"),
    ("scoreboard_connection", "Scoreboard Connection"),
    ("status", "Status"),
)

#: AMBA-20's "Default topology observation: PASSIVE MONITOR". A vocabulary
#: rather than a comment: `assert_vip_plan_defaults_passive()` below refuses a
#: row that leaves it without naming the driving requirement.
VIP_MODE_PASSIVE_MONITOR = "PASSIVE_MONITOR"
VIP_MODE_ACTIVE_DRIVER = "ACTIVE_DRIVER"
VIP_MSM_MONITOR = "MONITOR"

_VIP_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9]+")


def _vip_id(index: int, protocol: str, instance_path: str, bundle_prefix: str) -> str:
    """A stable, readable VIP_ID: the index keeps it unique, the rest makes it
    greppable back to the location it names."""
    where = _VIP_ID_SAFE_RE.sub("_", f"{instance_path}_{bundle_prefix}").strip("_").upper()
    return f"VIP_{index:02d}_{protocol}_{where}"


def build_vip_instance_plan(netlist: FabricNetlist, traces, matrix_rows=None) -> list:
    """AMBA-20's eleven-column VIP instance plan, one row per proposed VIP.

    Derived from AMBA-16's matrix rows, never re-traced, so a VIP row and its
    matrix row cannot disagree about clock, reset or readiness. A matrix row
    with no candidate location produces NO VIP row -- it is already in
    AMBA-17's unresolved table, and a VIP instance naming
    `REQUIRED_HUMAN_INPUT` as its bind hierarchy would be a planned instance
    with nowhere to sit. An AMBA-11 second-side (VIP-B) row is likewise
    recorded in the matrix but not planned here, per AMBA-11's "recommend both
    only when justified by verification goals".

    `Scoreboard Connection` is `REQUIRED_HUMAN_INPUT` by construction: which
    scoreboard a monitor feeds is AMBA-21/AMBA-25's output, computed by
    `uvm_generator/amba_fabric_generator.build_scoreboard_matrix()` from an
    approved topology, and guessing it here would pre-empt the review gate.

    Rows also carry `vip_type` and `active_passive` under
    `connectivity`'s own matrix vocabulary, so the existing
    `assert_active_passive_vocabulary()` / `matrix_vip_instance_records()` /
    `check_vip_instance_count_matches_active_interfaces()` chain accepts them
    with no changes."""
    rows = matrix_rows if matrix_rows is not None else \
        build_fabric_vip_bind_matrix(netlist, traces)
    plan: list = []
    for row in rows:
        bind = row.get("proposed_vip_bind_hierarchy")
        if not bind or bind in (REQUIRED_HUMAN_INPUT, MULTIPLE_BRANCH_PARENT_BIND):
            continue
        if row.get("amba11_second_side"):
            continue
        instance_path, _, bundle_prefix = bind.partition(":")
        validation = row.get("validation")
        protocol = validation.protocol if validation is not None else AMBA_PROTOCOL_UNRESOLVED
        vip_id = _vip_id(len(plan) + 1, protocol, instance_path, bundle_prefix)
        plan.append({
            "vip_id": vip_id,
            "protocol": _display_protocol(protocol),
            "endpoint": row.get("endpoint"),
            "vip_mode": VIP_MODE_PASSIVE_MONITOR,
            "active_passive": PASSIVE_INTERFACE,
            "master_slave_monitor": VIP_MSM_MONITOR,
            "bind_hierarchy": bind,
            "clock": row.get("clock"),
            "reset": row.get("reset"),
            "scoreboard_connection": REQUIRED_HUMAN_INPUT,
            "status": row.get("status"),
            # Beyond the eleven rendered columns, for the existing
            # connectivity-matrix helpers and for row-level locking.
            "vip_type": f"{protocol}_VIP",
            "row_id": vip_id,
            "source_row_id": row.get("row_id"),
            "observed_endpoint_role": row.get("external_endpoint_role"),
            "driving_requirement": None,
        })
    return plan


def assert_vip_plan_defaults_passive(plan) -> None:
    """AMBA-20: "Do not default ACTIVE unless verification architecture
    explicitly requires driving."

    Enforced rather than stated. An ACTIVE row must name the driving
    requirement that justifies it; without one, the row is refused. The
    `active_passive` vocabulary itself is `connectivity`'s
    (`assert_active_passive_vocabulary()`), run here so a plan cannot carry a
    third value that silently drops out of every count."""
    assert_active_passive_vocabulary(plan)
    for row in plan or ():
        mode = row.get("vip_mode")
        active = (row.get("active_passive") == "active"
                  or mode == VIP_MODE_ACTIVE_DRIVER)
        if not active:
            continue
        if not str(row.get("driving_requirement") or "").strip():
            raise FabricDiscoveryError("VIP_ACTIVE_WITHOUT_DRIVING_REQUIREMENT", {
                "vip_id": row.get("vip_id"), "vip_mode": mode,
                "active_passive": row.get("active_passive"),
                "hint": "AMBA-20 defaults to PASSIVE MONITOR; an ACTIVE VIP must name "
                        "the verification-architecture requirement that needs it to "
                        "drive, in 'driving_requirement'",
            })


def vip_instance_records_from_plan(plan) -> list:
    """The plan as real `connectivity.VipInstanceRecord`s, so it can be fed to
    the existing `check_vip_instance_count_matches_active_interfaces()` without
    a second record type."""
    return [VipInstanceRecord(vip_type=str(r.get("vip_type")),
                              instance_path=str(r.get("bind_hierarchy")),
                              active_passive=str(r.get("active_passive")))
            for r in plan or ()]


def render_vip_instance_plan(plan) -> str:
    return render_markdown_table(
        list(AMBA20_VIP_PLAN_COLUMNS), plan,
        empty_note="(no VIP instance is proposed: no fabric port reached a validated "
                   "bind location)")


# ===========================================================================
# The AMBA-15..20 review artifact, assembled
# ===========================================================================

@dataclass
class VipBindPlan:
    """Everything AMBA-16..20 mandate, computed once from one trace set."""
    traces: list
    matrix: list
    unresolved: list
    summary: dict
    vip_instances: list
    tree: str

    def to_dict(self) -> dict:
        return {
            "fabric_port_to_vip_bind_matrix": [
                {k: v for k, v in row.items() if k != "validation"} for row in self.matrix],
            "bind_location_validations": [
                row["validation"].to_dict() for row in self.matrix
                if row.get("validation") is not None],
            "unresolved_fabric_ports": list(self.unresolved),
            "topology_summary": self.summary,
            "topology_tree": self.tree,
            "vip_instance_plan": list(self.vip_instances),
        }


def build_vip_bind_plan(netlist: FabricNetlist, traces) -> VipBindPlan:
    """AMBA-15..20 in one pass over one trace set.

    The order matters and is the doc's: validate the locations (AMBA-15) while
    building the matrix (AMBA-16), derive the unresolved table (AMBA-17), the
    summary (AMBA-18), the tree (AMBA-19) and the VIP plan (AMBA-20) FROM that
    same matrix. Nothing is recomputed from the netlist a second time, so the
    five artifacts are guaranteed consistent with each other."""
    assert_unresolved_states_explained(traces)
    matrix = build_fabric_vip_bind_matrix(netlist, traces)
    plan = VipBindPlan(
        traces=list(traces or ()),
        matrix=matrix,
        unresolved=build_unresolved_fabric_port_table(netlist, traces, matrix),
        summary=build_amba_topology_summary(netlist, traces, matrix),
        vip_instances=build_vip_instance_plan(netlist, traces, matrix),
        tree=render_topology_tree(netlist, traces, matrix),
    )
    assert_vip_plan_defaults_passive(plan.vip_instances)
    return plan


def assert_no_bind_statement(text: str) -> None:
    """Nothing this module renders may be a `bind` statement.

    The test is `connectivity.parse_bind_line()` -- the repo's one definition
    of what a bind statement is -- so this assertion cannot drift from the
    grep that finds real binds in real source. AMBA-30/AMBA-31 put every bind
    behind a human review gate; a planning report that accidentally rendered
    emittable SystemVerilog would be a way past it."""
    for lineno, line in enumerate(str(text or "").splitlines(), 1):
        parsed = parse_bind_line(line)
        if parsed:
            raise FabricDiscoveryError("BIND_STATEMENT_IN_DISCOVERY_ARTIFACT", {
                "line_number": lineno, "line": line.strip(), "parsed": list(parsed),
                "hint": "AMBA-15..20 are discovery/planning artifacts; a bind statement "
                        "may only be written after AMBA-31's explicit human approval",
            })


def render_vip_bind_plan_report(plan: VipBindPlan) -> str:
    """The single human-review artifact AMBA-30's gate is held against.

    Self-checked: the finished text is run through `assert_no_bind_statement()`
    before it is returned, so this function cannot return a report carrying an
    emittable bind."""
    lines = ["# AMBA-15..20 Fabric Port to VIP Bind Plan", "",
             "## AMBA-18. Topology summary", "",
             render_amba_topology_summary(plan.summary), "",
             "## AMBA-16. Fabric port to VIP bind matrix", "",
             render_fabric_vip_bind_matrix(plan.matrix), "",
             "## AMBA-17. Unresolved fabric ports", "",
             render_unresolved_fabric_port_table(plan.unresolved), "",
             "## AMBA-19. Discovered topology tree", "", "```", plan.tree, "```", "",
             "## AMBA-20. VIP instance plan", "",
             render_vip_instance_plan(plan.vip_instances), "",
             "## AMBA-15. Bind location validation (13 points per location)", ""]
    for row in plan.matrix:
        validation = row.get("validation")
        if validation is None:
            continue
        lines += [f"### {row['fabric_port']} -> {validation.instance_path}:"
                  f"{validation.bundle_prefix} [{validation.readiness}]", "",
                  validation.render_checklist(), ""]
    lines.append(
        "Discovery and planning only. No bind statement is proposed, emitted or implied "
        "by this report (AMBA-30 / AMBA-31): a human reviews these candidate locations, "
        "this VIP instance plan and every unresolved port above before any UVM/VIP code "
        "is generated or modified.")
    text = "\n".join(lines)
    assert_no_bind_statement(text)
    return text
