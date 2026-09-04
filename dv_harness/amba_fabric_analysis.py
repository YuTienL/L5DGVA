"""dv_harness/amba_fabric_analysis.py -- AMBA-23, AMBA-24 and AMBA-25: the
three fabric-level ANALYSES that sit on top of an already-discovered topology.

AMBA-23  ADDRESS MAP CROSS-CHECK
AMBA-24  CLOCK / RESET DOMAIN ANALYSIS
AMBA-25  SCOREBOARD + PORT SCALING

WHY ONE MODULE, AND WHY NOT MORE OF `amba_fabric_discovery.py`
--------------------------------------------------------------
`amba_fabric_discovery.py` answers "what is on the other end of this AMBA
bundle" -- one traversal, over AMBA-signal net classes, terminating in AMBA-14's
ten states. All three requirements here are DIFFERENT questions asked of the
SAME already-built artifacts:

  * AMBA-23 reconciles several independent ADDRESS-MAP EVIDENCE SOURCES against
    each other and against the physically-traced topology. Nothing about it is
    a bundle traversal.
  * AMBA-24 traverses the netlist along CLOCK and RESET nets -- a different
    graph walk over the same `FabricNetlist`, following net drivers upward
    rather than AMBA bundles outward.
  * AMBA-25 is pure registry arithmetic: M x N pairing, per-port channels,
    protocol traffic policy and scheduling dependencies.

So this module IMPORTS and COMPOSES the existing primitives rather than
restating any of them:

  `uvm_generator/amba_fabric_generator.compute_address_regions()`
      the ONLY overlap / gap / full-coverage validator used (AMBA-23).
  `uvm_generator/amba_fabric_generator.build_scoreboard_matrix()`
      the ONLY M x N pair resolver used (AMBA-25).
  `uvm_generator/amba_fabric_generator.compute_id_width()`
      the ONLY ID-width formula used (AMBA-25).
  `source_authority.resolve_conflict()`
      the ONLY conflict-resolution order used (AMBA-23) -- the same mechanism
      `uvm_generator/address_map_verifier.py` already routes its decoder-vs-doc
      disagreements through, so "the document corroborates, it never decides"
      is one rule in one place rather than two similar ones.
  `connectivity.find_amba_clock_reset_ports()`
      the ONLY clock/reset PORT identifier used (AMBA-24). This module adds the
      DOMAIN analysis above it: where that port's signal comes from, at what
      polarity, and whether two bind points share a domain.
  `connectivity.SignalTrace`
      the ONLY trace data contract used (AMBA-24 frequency and measured reset
      polarity), the same one `evaluate_zero_time_connectivity()` consumes.
  `amba_port_registry.registry_endpoints()`
      the ONLY endpoint projection used (AMBA-25).

WHAT AMBA-23 ACTUALLY REQUIRES, AND THE ASYMMETRY THAT IS THE POINT
--------------------------------------------------------------------
The doc's own words: "Use only as supporting evidence. Physical RTL
connectivity remains mandatory for VIP bind planning."

That is an ASYMMETRY, and it is implemented as one here rather than described:

  * An address region whose owner was NEVER TRACED is recorded, reported, and
    then REFUSED as an input to bind planning (`NO_PHYSICAL_CONNECTIVITY`). A
    memory-map document naming a slave nobody could find in the RTL does not
    create that slave.
  * A traced slave port with NO address evidence at all is reported
    (`NO_ADDRESS_EVIDENCE`) and is STILL a legitimate bind-planning target,
    because the mandatory half -- physical connectivity -- is satisfied. An
    address map is supporting evidence; its absence is a gap in the report, not
    a veto on a physically-proven port.

`uvm_generator/address_map_verifier.py` is deliberately NOT called here.
It answers a different question with a different mandatory second source (a
BFM-access histogram at IP level); its POLICY -- highest-authority source
decides, a document never decides, a disagreement is recorded and escalated
rather than blocking -- is what this module reuses, through the same
`source_authority` order both of them defer to.

DISCOVERY AND PLANNING ONLY (AMBA-30 / AMBA-31)
-----------------------------------------------
Nothing here writes, renders or returns a SystemVerilog `bind` statement, and
every rendered report is self-checked with
`amba_fabric_discovery.assert_no_bind_statement()` for the same reason
AMBA-16..22's are.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dv_harness import amba_fabric_discovery as afd
from dv_harness.amba_fabric_discovery import (
    FabricDiscoveryError,
    MULTIPLE_BRANCH_PARENT_BIND,
    assert_no_bind_statement,
    find_bundle,
    parse_instance_path,
)
from dv_harness.amba_port_registry import (
    ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
    registry_endpoints,
)
from dv_harness.connectivity import (
    AMBA4_DISPLAY_NAMES,
    AMBA_FAMILY_CLOCK_SIGNALS,
    AMBA_FAMILY_RESET_SIGNALS,
    AMBA_PROTOCOL_FAMILY,
    AMBA_PROTOCOL_UNRESOLVED,
    CLOCK_RESET_RESOLVED,
    GENERIC_CLOCK_SIGNAL_TOKENS,
    GENERIC_RESET_SIGNAL_TOKENS,
    REQUIRED_HUMAN_INPUT,
    SignalTrace,
    amba_signal_tokens,
    classify_bind_tier,
    find_amba_clock_reset_ports,
    render_markdown_table,
)
from dv_harness.uvm_generator.amba_fabric_generator import (
    AddressMapError,
    ScoreboardMatrixError,
    build_scoreboard_matrix,
    compute_address_regions,
    compute_id_width,
    parse_addr,
)


class FabricAnalysisError(FabricDiscoveryError):
    """A malformed analysis input -- an address claim with no evidence, a
    registry that cannot be projected. Subclasses `FabricDiscoveryError` so a
    caller already handling the discovery pipeline's errors handles these."""


#: Display spelling -> `PROTOCOL_FINGERPRINTS` key, so a registry row (which
#: carries the doc's human-facing spelling, "AXI4-Lite") and a raw trace (which
#: carries "AXI4_LITE") both resolve to the same protocol family here. Derived
#: from `AMBA4_DISPLAY_NAMES` rather than restated, so a spelling cannot drift.
_PROTOCOL_KEY_BY_DISPLAY: dict = {v: k for k, v in AMBA4_DISPLAY_NAMES.items()}


def protocol_key(protocol: str) -> str:
    """The internal protocol key for either spelling. An unknown string is
    returned unchanged -- it will simply have no family, which is what makes
    every downstream verdict for it UNKNOWN rather than defaulted."""
    text = str(protocol or "")
    return _PROTOCOL_KEY_BY_DISPLAY.get(text, text)


def protocol_family(protocol: str) -> Optional[str]:
    return AMBA_PROTOCOL_FAMILY.get(protocol_key(protocol))


# ===========================================================================
# AMBA-23: ADDRESS MAP CROSS-CHECK
#
# "Where available inspect: RTL decoder / fabric generated configuration /
#  address-map package / CSR definitions / firmware headers / memory-map
#  documents. Use only as supporting evidence. Physical RTL connectivity
#  remains mandatory for VIP bind planning."
# ===========================================================================

#: The doc's own six evidence sources, each mapped onto a REAL
#: `source_authority.AUTHORITY_ORDER` level. The mapping is a judgment and is
#: therefore stated explicitly here rather than buried:
#:
#:   RTL decoder / fabric generated configuration -> `dut_rtl` (tier 3). Both
#:       are the design's own source: the decoder literally is the comparator,
#:       and a fabric's generated configuration is machine-emitted from the
#:       same topology that produced the RTL.
#:   address-map package / CSR definitions -> `register_file` (tier 4). Both
#:       are machine-readable register/address descriptions.
#:   firmware headers / memory-map documents -> `controller_doc` (tier 6). Both
#:       are downstream descriptions written for a consumer of the design, the
#:       same level `address_map_verifier.py` already assigns its register doc.
#:
#: Two sources sharing a level is deliberate and NOT a defect: an address-map
#: package disagreeing with a CSR definition genuinely is not decidable by the
#: authority order, and `resolve_conflict()` reports exactly that
#: (UNDECIDABLE_SAME_AUTHORITY) instead of this module inventing a sub-order.
ADDRESS_MAP_SOURCE_RTL_DECODER = "RTL_DECODER"
ADDRESS_MAP_SOURCE_FABRIC_CONFIGURATION = "FABRIC_GENERATED_CONFIGURATION"
ADDRESS_MAP_SOURCE_ADDRESS_MAP_PACKAGE = "ADDRESS_MAP_PACKAGE"
ADDRESS_MAP_SOURCE_CSR_DEFINITIONS = "CSR_DEFINITIONS"
ADDRESS_MAP_SOURCE_FIRMWARE_HEADERS = "FIRMWARE_HEADERS"
ADDRESS_MAP_SOURCE_MEMORY_MAP_DOCUMENT = "MEMORY_MAP_DOCUMENT"

ADDRESS_MAP_EVIDENCE_SOURCES: tuple = (
    (ADDRESS_MAP_SOURCE_RTL_DECODER, "dut_rtl"),
    (ADDRESS_MAP_SOURCE_FABRIC_CONFIGURATION, "dut_rtl"),
    (ADDRESS_MAP_SOURCE_ADDRESS_MAP_PACKAGE, "register_file"),
    (ADDRESS_MAP_SOURCE_CSR_DEFINITIONS, "register_file"),
    (ADDRESS_MAP_SOURCE_FIRMWARE_HEADERS, "controller_doc"),
    (ADDRESS_MAP_SOURCE_MEMORY_MAP_DOCUMENT, "controller_doc"),
)

_AUTHORITY_BY_SOURCE: dict = dict(ADDRESS_MAP_EVIDENCE_SOURCES)

#: Cross-check verdict for one owner's address region.
ADDRESS_REGION_AGREED = "AGREED"
ADDRESS_REGION_RESOLVED_BY_AUTHORITY = "RESOLVED_BY_AUTHORITY"
ADDRESS_REGION_UNDECIDABLE = "UNDECIDABLE_SAME_AUTHORITY"
ADDRESS_REGION_NO_ADDRESS_EVIDENCE = "NO_ADDRESS_EVIDENCE"

#: The physical-connectivity half of AMBA-23, which is the mandatory one.
PHYSICAL_CONNECTIVITY_CONFIRMED = "PHYSICAL_CONNECTIVITY_CONFIRMED"
PHYSICAL_CONNECTIVITY_ABSENT = "NO_PHYSICAL_CONNECTIVITY"

#: Completeness verdicts, from `compute_address_regions()`'s own outcomes.
ADDRESS_MAP_COMPLETE = "NO_GAP_NO_OVERLAP_FULL_COVERAGE"
ADDRESS_MAP_NOT_CHECKED = "NOT_CHECKED"


@dataclass(frozen=True)
class AddressRegionClaim:
    """One evidence source stating one owner's address region, WITH the
    file:line it was read from.

    `evidence` is mandatory and enforced at construction for the same reason
    `source_authority.SourceClaim` enforces `evidence_path`: an uncited address
    region is not evidence, and checking for it at the far end is already too
    late. `owner` must be the SAME identifier the traced topology uses (an
    endpoint hierarchy path), because matching an address region to a physical
    port by anything looser than identity is how a document's slave name gets
    silently attached to the wrong RTL instance."""
    source_type: str
    owner: str
    base: int
    size: int
    evidence: str

    def __post_init__(self):
        if self.source_type not in _AUTHORITY_BY_SOURCE:
            raise FabricAnalysisError("ADDRESS_MAP_UNKNOWN_EVIDENCE_SOURCE", {
                "source_type": self.source_type,
                "legal_values": [s for s, _ in ADDRESS_MAP_EVIDENCE_SOURCES],
                "hint": "AMBA-23 names exactly six evidence sources; a seventh needs a "
                        "stated authority level, not a silent default"})
        if not str(self.owner or "").strip():
            raise FabricAnalysisError("ADDRESS_MAP_CLAIM_HAS_NO_OWNER", {
                "source_type": self.source_type})
        if not str(self.evidence or "").strip():
            raise FabricAnalysisError("ADDRESS_MAP_CLAIM_CITES_NO_EVIDENCE", {
                "source_type": self.source_type, "owner": self.owner,
                "hint": "file:line, or the real artifact path. An uncited address region "
                        "may not enter the cross-check."})
        object.__setattr__(self, "base", parse_addr(self.base))
        object.__setattr__(self, "size", parse_addr(self.size))
        if self.size <= 0:
            raise FabricAnalysisError("ADDRESS_MAP_CLAIM_NON_POSITIVE_SIZE", {
                "source_type": self.source_type, "owner": self.owner,
                "size": self.size})

    @property
    def region(self) -> tuple:
        return (self.base, self.size)

    @property
    def authority_source(self) -> str:
        return _AUTHORITY_BY_SOURCE[self.source_type]

    def to_dict(self) -> dict:
        return {"source_type": self.source_type, "owner": self.owner,
                "base": self.base, "base_hex": hex(self.base),
                "size": self.size, "size_hex": hex(self.size),
                "authority_source": self.authority_source,
                "evidence": self.evidence}


@dataclass
class AddressRegionCrossCheck:
    """One owner's reconciled region plus the physical-connectivity verdict
    that decides whether it may drive VIP bind planning."""
    owner: str
    status: str
    physical_connectivity: str
    base: Optional[int] = None
    size: Optional[int] = None
    deciding_source: str = ""
    agreeing_sources: list = field(default_factory=list)
    disagreeing_sources: list = field(default_factory=list)
    claims: list = field(default_factory=list)           # list[AddressRegionClaim]
    authority_verdict: Optional[dict] = None
    reason: str = ""

    @property
    def usable_for_bind_planning(self) -> bool:
        """AMBA-23's mandatory half, and ONLY that half: an owner is usable
        when it was physically traced. A traced owner with no address evidence
        stays usable -- the address map is supporting evidence, and its absence
        is a reported gap, not a veto on a physically-proven port."""
        return self.physical_connectivity == PHYSICAL_CONNECTIVITY_CONFIRMED

    @property
    def has_decided_region(self) -> bool:
        return self.base is not None and self.size is not None

    def to_dict(self) -> dict:
        return {
            "owner": self.owner, "status": self.status,
            "physical_connectivity": self.physical_connectivity,
            "usable_for_bind_planning": self.usable_for_bind_planning,
            "base": self.base, "base_hex": hex(self.base) if self.base is not None else None,
            "size": self.size, "size_hex": hex(self.size) if self.size is not None else None,
            "deciding_source": self.deciding_source,
            "agreeing_sources": list(self.agreeing_sources),
            "disagreeing_sources": [dict(d) for d in self.disagreeing_sources],
            "claims": [c.to_dict() for c in self.claims],
            "authority_verdict": self.authority_verdict,
            "reason": self.reason,
        }

    def render_cells(self) -> dict:
        return {
            "owner": self.owner,
            "base": hex(self.base) if self.base is not None else REQUIRED_HUMAN_INPUT,
            "size": hex(self.size) if self.size is not None else REQUIRED_HUMAN_INPUT,
            "status": self.status,
            "deciding_source": self.deciding_source or "-",
            "agreeing": ", ".join(self.agreeing_sources) or "-",
            "disagreeing": ", ".join(
                f"{d['source_type']}={hex(d['base'])}+{hex(d['size'])}"
                for d in self.disagreeing_sources) or "-",
            "physical_connectivity": self.physical_connectivity,
            "evidence": " | ".join(f"{c.source_type}@{c.evidence}" for c in self.claims) or "-",
        }


@dataclass
class AddressMapCrossCheck:
    """AMBA-23's complete result: every owner from either side of the join."""
    regions: list = field(default_factory=list)           # list[AddressRegionCrossCheck]
    completeness_status: str = ADDRESS_MAP_NOT_CHECKED
    completeness_detail: dict = field(default_factory=dict)
    address_width: Optional[int] = None

    @property
    def bind_planning_owners(self) -> list:
        return [r.owner for r in self.regions if r.usable_for_bind_planning]

    @property
    def refused_owners(self) -> list:
        """Address regions that name an owner nobody traced. Reported, never
        used -- AMBA-23's "physical RTL connectivity remains mandatory"."""
        return [r.owner for r in self.regions
                if r.physical_connectivity == PHYSICAL_CONNECTIVITY_ABSENT]

    @property
    def owners_without_address_evidence(self) -> list:
        return [r.owner for r in self.regions
                if r.status == ADDRESS_REGION_NO_ADDRESS_EVIDENCE]

    @property
    def undecided_owners(self) -> list:
        return [r.owner for r in self.regions if r.status == ADDRESS_REGION_UNDECIDABLE]

    def to_dict(self) -> dict:
        return {
            "regions": [r.to_dict() for r in self.regions],
            "completeness_status": self.completeness_status,
            "completeness_detail": dict(self.completeness_detail),
            "address_width": self.address_width,
            "bind_planning_owners": self.bind_planning_owners,
            "refused_owners": self.refused_owners,
            "owners_without_address_evidence": self.owners_without_address_evidence,
            "undecided_owners": self.undecided_owners,
        }


def _authority_verdict(claims) -> dict:
    """`source_authority.resolve_conflict()` over the claims for one owner.

    Imported inside the function, exactly as `address_map_verifier.py` does, so
    this module stays importable in an environment where the question-queue
    dependency chain is not wanted."""
    from dv_harness.source_authority import SourceClaim, resolve_conflict

    return resolve_conflict([
        SourceClaim(source=c.authority_source,
                    claim=f"{c.owner} occupies [{hex(c.base)}, {hex(c.base + c.size)})",
                    evidence_path=c.evidence,
                    detail={"source_type": c.source_type, "base": c.base, "size": c.size})
        for c in claims
    ])


def _reconcile_one_owner(owner: str, claims: list, traced: bool) -> AddressRegionCrossCheck:
    physical = (PHYSICAL_CONNECTIVITY_CONFIRMED if traced
                else PHYSICAL_CONNECTIVITY_ABSENT)
    if not claims:
        return AddressRegionCrossCheck(
            owner=owner, status=ADDRESS_REGION_NO_ADDRESS_EVIDENCE,
            physical_connectivity=physical,
            reason="this endpoint was traced from real RTL connectivity but no address-map "
                   "evidence source names it. AMBA-23 makes the address map SUPPORTING "
                   "evidence, so this is a reported gap, not a block on bind planning.")
    distinct = {c.region for c in claims}
    if len(distinct) == 1:
        base, size = next(iter(distinct))
        return AddressRegionCrossCheck(
            owner=owner, status=ADDRESS_REGION_AGREED, physical_connectivity=physical,
            base=base, size=size,
            deciding_source=sorted(c.source_type for c in claims)[0],
            agreeing_sources=sorted(c.source_type for c in claims), claims=list(claims),
            reason=f"{len(claims)} evidence source(s) state the same region")

    verdict = _authority_verdict(claims)
    if verdict["verdict"] == "RESOLVED":
        winner_source = verdict["winner"]["source"]
        winners = [c for c in claims if c.authority_source == winner_source]
        # A single strictly-highest authority level can still hold two of this
        # module's source TYPES (an RTL decoder and a fabric configuration are
        # both `dut_rtl`). If those two disagree the order cannot break the tie
        # either, and saying it did would be the invented fact this whole
        # pipeline exists to avoid.
        if len({c.region for c in winners}) > 1:
            return AddressRegionCrossCheck(
                owner=owner, status=ADDRESS_REGION_UNDECIDABLE,
                physical_connectivity=physical, claims=list(claims),
                authority_verdict=verdict,
                disagreeing_sources=[{"source_type": c.source_type, "base": c.base,
                                      "size": c.size, "evidence": c.evidence}
                                     for c in claims],
                reason=f"two sources at the same authority level ({winner_source}) state "
                       "different regions; the authority order cannot break that tie")
        win = winners[0]
        return AddressRegionCrossCheck(
            owner=owner, status=ADDRESS_REGION_RESOLVED_BY_AUTHORITY,
            physical_connectivity=physical, base=win.base, size=win.size,
            deciding_source=win.source_type,
            agreeing_sources=sorted({c.source_type for c in claims
                                     if c.region == win.region}),
            disagreeing_sources=[{"source_type": c.source_type, "base": c.base,
                                  "size": c.size, "evidence": c.evidence}
                                 for c in sorted(claims, key=lambda c: c.source_type)
                                 if c.region != win.region],
            claims=list(claims), authority_verdict=verdict,
            reason=f"{win.source_type} ({win.authority_source}) outranks the disagreeing "
                   "source(s); the lower-authority sources corroborate, they never decide")

    return AddressRegionCrossCheck(
        owner=owner, status=ADDRESS_REGION_UNDECIDABLE, physical_connectivity=physical,
        claims=list(claims), authority_verdict=verdict,
        disagreeing_sources=[{"source_type": c.source_type, "base": c.base,
                              "size": c.size, "evidence": c.evidence}
                             for c in sorted(claims, key=lambda c: c.source_type)],
        reason=verdict.get("rule") or "the authority order cannot decide between these "
                                      "sources; a human must")


def cross_check_fabric_address_map(claims, traced_slaves, *, address_width=None,
                                   reserved_regions=None) -> AddressMapCrossCheck:
    """AMBA-23 for a whole fabric.

    `claims` is an iterable of `AddressRegionClaim`. `traced_slaves` is the list
    of slave endpoint identifiers AMBA-7..14 actually traced -- pass
    `amba_port_registry.registry_endpoints(rows)["slaves"]` or
    `amba_fabric_discovery.discovered_topology_ids(traces)["slaves"]`; both name
    endpoints the same way, and nothing else may be passed here, because the
    whole point of the check is that this list came from physical RTL
    connectivity and not from an address map.

    `address_width`, when given, additionally runs the completeness math --
    `compute_address_regions()`, unchanged and unreimplemented, so a region set
    that passes here is guaranteed to pass
    `tools/verification_flow/fabric_topology_completeness_gate.py`. Its
    overlap/gap/coverage failure is RECORDED, not raised: this is a discovery
    report a human reads at AMBA-30's gate, and a fabric with a real address
    gap must produce a report naming the gap rather than an exception instead
    of a report.
    """
    by_owner: dict = {}
    for claim in claims or ():
        if not isinstance(claim, AddressRegionClaim):
            raise FabricAnalysisError("ADDRESS_MAP_CLAIM_WRONG_TYPE", {
                "got": type(claim).__name__,
                "hint": "build an AddressRegionClaim so the evidence citation and the "
                        "source type are validated at construction"})
        by_owner.setdefault(claim.owner, []).append(claim)

    traced = list(dict.fromkeys(traced_slaves or ()))
    traced_set = set(traced)
    result = AddressMapCrossCheck(address_width=address_width)
    for owner in traced + [o for o in sorted(by_owner) if o not in traced_set]:
        result.regions.append(_reconcile_one_owner(
            owner, by_owner.get(owner, []), owner in traced_set))

    if address_width is None:
        result.completeness_status = ADDRESS_MAP_NOT_CHECKED
        result.completeness_detail = {
            "reason": "no address_width supplied, so [0, 2**addr_width) coverage cannot be "
                      "checked; overlap and gap between declared regions are equally "
                      "undefined without the space they live in"}
        return result

    usable = [r for r in result.regions
              if r.usable_for_bind_planning and r.has_decided_region]
    if not usable:
        result.completeness_status = ADDRESS_MAP_NOT_CHECKED
        result.completeness_detail = {
            "reason": "no physically-traced owner has a decided address region, so there is "
                      "no map to check for gaps or overlaps",
            "owners_without_address_evidence": result.owners_without_address_evidence,
            "undecided_owners": result.undecided_owners}
        return result
    try:
        regions = compute_address_regions(
            [{"id": r.owner, "base_addr": r.base, "size": r.size} for r in usable],
            reserved_regions, address_width)
    except AddressMapError as exc:
        result.completeness_status = exc.reason
        result.completeness_detail = dict(exc.detail)
        return result
    result.completeness_status = ADDRESS_MAP_COMPLETE
    result.completeness_detail = {"region_count": len(regions),
                                  "checked_by": "amba_fabric_generator.compute_address_regions"}
    return result


def address_map_slaves_for_topology(crosscheck: AddressMapCrossCheck) -> list:
    """The `address_map_slaves` argument
    `amba_port_registry.project_to_fabric_topology()` asks its caller for --
    built ONLY from owners that passed AMBA-23's mandatory physical-connectivity
    half and whose region is actually decided.

    This is the concrete wiring the registry's own docstring left to the
    caller ("an address map is AMBA-23's evidence... not something a port
    registry can know"). An owner refused here never reaches the topology
    document, so a memory-map document cannot introduce a slave into the
    projected topology that no trace ever found."""
    return [{"id": r.owner, "base_addr": r.base, "size": r.size}
            for r in crosscheck.regions
            if r.usable_for_bind_planning and r.has_decided_region]


def assert_address_map_never_creates_a_slave(crosscheck: AddressMapCrossCheck,
                                             traced_slaves) -> None:
    """Guard for the one way AMBA-23 can be violated in practice: an
    address-map-only owner leaking into the topology.

    Cheap, and it is the check that keeps this whole section honest -- it
    re-derives anything, it just refuses to let the projection name an owner
    the physical trace never produced."""
    traced_set = set(traced_slaves or ())
    leaked = [s["id"] for s in address_map_slaves_for_topology(crosscheck)
              if s["id"] not in traced_set]
    if leaked:
        raise FabricAnalysisError("ADDRESS_MAP_OWNER_WITHOUT_PHYSICAL_CONNECTIVITY", {
            "owners": leaked, "traced_slaves": sorted(traced_set),
            "hint": "AMBA-23: address-map sources are supporting evidence only; physical "
                    "RTL connectivity remains mandatory for VIP bind planning"})


_ADDRESS_MAP_COLUMNS: tuple = (
    ("owner", "Owner (traced endpoint)"),
    ("base", "Base"),
    ("size", "Size"),
    ("status", "Cross-Check"),
    ("deciding_source", "Deciding Source"),
    ("agreeing", "Agreeing"),
    ("disagreeing", "Disagreeing"),
    ("physical_connectivity", "Physical RTL Connectivity"),
    ("evidence", "Evidence"),
)


def render_address_map_cross_check(crosscheck: AddressMapCrossCheck) -> str:
    return render_markdown_table(
        list(_ADDRESS_MAP_COLUMNS), [r.render_cells() for r in crosscheck.regions],
        empty_note="(no address-map evidence and no traced slave endpoint)")


def render_address_map_cross_check_report(crosscheck: AddressMapCrossCheck) -> str:
    lines = [
        "# AMBA-23 Address Map Cross-Check", "",
        "Evidence sources inspected: "
        + ", ".join(s for s, _ in ADDRESS_MAP_EVIDENCE_SOURCES) + ".", "",
        "Address-map evidence is SUPPORTING only. Physical RTL connectivity remains "
        "mandatory for VIP bind planning, so an owner named by a document but never "
        "traced is reported below and refused as a bind-planning input.", "",
        render_address_map_cross_check(crosscheck), "",
        f"Completeness ([0, 2**{crosscheck.address_width}) coverage, no gap, no overlap): "
        f"{crosscheck.completeness_status}", "",
    ]
    if crosscheck.completeness_detail:
        lines += ["```", str(crosscheck.completeness_detail), "```", ""]
    if crosscheck.refused_owners:
        lines += ["## Address regions refused for bind planning "
                  "(no physical RTL connectivity)", "",
                  "\n".join(f"- {o}" for o in crosscheck.refused_owners), ""]
    if crosscheck.owners_without_address_evidence:
        lines += ["## Traced endpoints with no address-map evidence "
                  "(reported gap, NOT a block)", "",
                  "\n".join(f"- {o}" for o in crosscheck.owners_without_address_evidence), ""]
    if crosscheck.undecided_owners:
        lines += ["## Owners whose sources disagree and the authority order cannot decide",
                  "", "\n".join(f"- {o}" for o in crosscheck.undecided_owners), ""]
    text = "\n".join(lines)
    assert_no_bind_statement(text)
    return text


# ===========================================================================
# AMBA-24: CLOCK / RESET DOMAIN ANALYSIS
#
# "For each bind point report: clock hierarchy / clock frequency if provable /
#  reset hierarchy / reset polarity / sync-async reset if provable / CDC-bridge
#  path between endpoint and fabric. State whether bind is endpoint-side or
#  fabric-side of CDC/bridge."
#
# All seven are answered. The ones a syntax-level RTL parse genuinely cannot
# establish answer UNKNOWN with the missing evidence NAMED -- the same
# discipline AMBA-15's checklist already follows, and the direct fix for the
# previous state of affairs, where a caller PASSED IN `reset_active_low` as an
# opinion and `evaluate_zero_time_connectivity()` believed it.
# ===========================================================================

#: How far a clock/reset net is followed toward its source before the walk is
#: reported as bounded rather than looping.
MAX_DOMAIN_WALK_HOPS = 32

#: What terminated a clock/reset source walk.
DOMAIN_SOURCE_PRIMARY_INPUT = "PRIMARY_INPUT"
DOMAIN_SOURCE_INSTANCE_OUTPUT = "INSTANCE_OUTPUT"
DOMAIN_SOURCE_CONTINUOUS_ASSIGN = "CONTINUOUS_ASSIGN"

DOMAIN_WALK_RESOLVED = "RESOLVED"
DOMAIN_WALK_NO_PORT = "NO_CLOCK_OR_RESET_PORT"
DOMAIN_WALK_AMBIGUOUS_PORT = "AMBIGUOUS_CLOCK_OR_RESET_PORT"
DOMAIN_WALK_UNDRIVEN = "NET_HAS_NO_IDENTIFIABLE_DRIVER"
DOMAIN_WALK_MULTIPLE_DRIVERS = "NET_HAS_MULTIPLE_DRIVERS"
DOMAIN_WALK_EXPRESSION_DRIVEN = "DRIVEN_BY_MULTI_NET_EXPRESSION"
DOMAIN_WALK_HOP_LIMIT = "HOP_LIMIT_REACHED"

#: A domain identity that could not be established. Compared for equality
#: nowhere -- two UNKNOWN domains are NOT the same domain, and treating them as
#: one is how a CDC gets reported as absent.
DOMAIN_UNKNOWN = "DOMAIN_UNKNOWN"


@dataclass
class DomainNode:
    """One element of a clock or reset hierarchy, nearest the bind point
    first."""
    path: str
    module: str
    port: str
    kind: str
    evidence: str

    def to_dict(self) -> dict:
        return {"path": self.path, "module": self.module, "port": self.port,
                "kind": self.kind, "evidence": self.evidence}


@dataclass
class DomainChain:
    """AMBA-24's "clock hierarchy" / "reset hierarchy" for one bind point."""
    kind: str                    # "clock" | "reset"
    status: str
    port: str = ""
    nodes: list = field(default_factory=list)      # list[DomainNode]
    reason: str = ""
    missing_evidence: list = field(default_factory=list)
    candidates: list = field(default_factory=list)

    @property
    def source_node(self) -> Optional[DomainNode]:
        """The far end of the walk -- the ultimate origin (a primary input, or
        a generator with no clock input of its own). This is the HIERARCHY's
        terminus, and it is deliberately NOT the domain identity."""
        return self.nodes[-1] if self.nodes else None

    @property
    def domain_node(self) -> Optional[DomainNode]:
        """The NEAREST element that starts a clock (or reset) domain.

        A PLL, divider, mux or gate OUTPUT begins a new domain; so does a
        primary input. A 1:1 continuous assignment does NOT -- it is a rename,
        and `FabricNetlist` already models a hierarchical port connection the
        same way -- so assign nodes are skipped here.

        Using the nearest generator rather than the ultimate origin is the
        whole point: a divider's output and its own input share an origin
        (`<top>:CLK_REF`) but are emphatically not the same clock domain, and
        comparing origins would report every CDC in a single-oscillator SoC as
        absent.

        Known limitation, stated rather than implied away: verible reports a
        bit-select's base name, so `assign clk_div = counter[3];` is
        indistinguishable here from a 1:1 rename. The walk then continues onto
        `counter`, which has no clock driver, and the domain resolves to
        UNKNOWN rather than to a wrong answer."""
        if self.status != DOMAIN_WALK_RESOLVED:
            return None
        for node in self.nodes:
            if node.kind in (DOMAIN_SOURCE_PRIMARY_INPUT, DOMAIN_SOURCE_INSTANCE_OUTPUT):
                return node
        return None

    @property
    def domain_id(self) -> str:
        """The identity two bind points are compared on. `DOMAIN_UNKNOWN` when
        the walk did not reach a domain-starting element -- deliberately never
        equal to another `DOMAIN_UNKNOWN`, which callers must honour by testing
        `is_known_domain()` before comparing."""
        node = self.domain_node
        if node is None:
            return DOMAIN_UNKNOWN
        return f"{node.path}:{node.port}"

    def is_known_domain(self) -> bool:
        return self.domain_id != DOMAIN_UNKNOWN

    @property
    def hierarchy_text(self) -> str:
        if not self.nodes:
            return self.status
        return " <- ".join(f"{n.path}:{n.port}" for n in self.nodes)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "status": self.status, "port": self.port,
                "domain_id": self.domain_id, "hierarchy": self.hierarchy_text,
                "nodes": [n.to_dict() for n in self.nodes], "reason": self.reason,
                "missing_evidence": list(self.missing_evidence),
                "candidates": list(self.candidates)}


def _assign_driver(netlist, cls):
    """The continuous assign, if any, whose LHS sits on this net class.

    A continuous assign is deliberately NOT merged into a net class by
    `FabricNetlist` (see its docstring); for a CLOCK net that is exactly the
    behaviour needed -- `assign clk_div = clk_cnt[0];` really is a new domain,
    and merging it would erase the divider."""
    hits = []
    for scope, edges in netlist.assign_edges.items():
        for edge in edges:
            for lhs in edge.lhs_nets:
                if netlist.net_class(scope, lhs) == cls:
                    hits.append((scope, edge))
    return hits


def _walk_domain(netlist, path: tuple, port: str, kind: str) -> DomainChain:
    """Follow one clock or reset net from a bind point toward its source.

    The driver of a net class is the attachment that DRIVES it: a top-level
    input port, or an instance OUTPUT port. Every transparent wrapper on the
    path contributes only `input` attachments on the same merged class, which
    is why a wrapper chain does not appear as a hierarchy step and a real
    generator does."""
    chain = DomainChain(kind=kind, status=DOMAIN_WALK_RESOLVED, port=port)
    cur_path, cur_port = path, port
    for _ in range(MAX_DOMAIN_WALK_HOPS):
        cls = netlist.net_class(cur_path, cur_port)
        drivers = []
        for att in netlist.attachments_on([cls]):
            inst = netlist.instance(att.path)
            direction = inst.port_directions.get(att.port) if inst else None
            if att.path == () and direction == "input":
                drivers.append((att, DOMAIN_SOURCE_PRIMARY_INPUT))
            elif att.path != () and direction == "output":
                drivers.append((att, DOMAIN_SOURCE_INSTANCE_OUTPUT))
        assigns = _assign_driver(netlist, cls)
        if not drivers and not assigns:
            chain.status = DOMAIN_WALK_UNDRIVEN
            chain.reason = (
                f"the {kind} net at {'/'.join(cur_path) or '<top>'}:{cur_port} has no "
                "top-level input, no instance output and no continuous assignment "
                "driving it in the parsed source set")
            chain.missing_evidence.append(
                "the driver of this net is outside the parsed source set, or is procedural "
                "logic a port/instance/assign-level parse does not model")
            return chain
        if len(drivers) + len(assigns) > 1:
            chain.status = DOMAIN_WALK_MULTIPLE_DRIVERS
            chain.candidates = sorted(
                [f"{a.path_str}:{a.port}" for a, _ in drivers]
                + [f"{'/'.join(s) or '<top>'}:{e.text}" for s, e in assigns])
            chain.reason = (
                f"{len(chain.candidates)} things drive this {kind} net and nothing "
                "establishes which is the real source; choosing one would invent a "
                "clock hierarchy")
            return chain
        if drivers:
            att, source_kind = drivers[0]
            inst = netlist.instance(att.path)
            chain.nodes.append(DomainNode(
                path=att.path_str, module=inst.module_name if inst else "",
                port=att.port, kind=source_kind,
                evidence=f"{att.port} is an {'input' if source_kind == DOMAIN_SOURCE_PRIMARY_INPUT else 'output'} "
                         f"port of {att.path_str} on this net class"))
            if source_kind == DOMAIN_SOURCE_PRIMARY_INPUT:
                return chain
            # An instance drives this net: continue from ITS own same-kind
            # input, which is what makes a PLL/divider/mux a real hierarchy
            # STEP rather than a terminus.
            upstream = _same_kind_inputs(netlist, att.path, kind, exclude=att.port)
            if not upstream:
                return chain           # a genuine source (oscillator, generator)
            if len(upstream) > 1:
                chain.status = DOMAIN_WALK_AMBIGUOUS_PORT
                chain.candidates = sorted(upstream)
                chain.reason = (
                    f"{att.path_str} drives this {kind} and has {len(upstream)} candidate "
                    f"{kind} inputs; which one it is derived from is not established by "
                    "the port list alone")
                chain.missing_evidence.append(
                    f"which of {', '.join(sorted(upstream))} {att.path_str} derives its "
                    f"output {kind} from")
                return chain
            cur_path, cur_port = att.path, upstream[0]
            continue
        scope, edge = assigns[0]
        if len(edge.rhs_nets) != 1:
            chain.status = DOMAIN_WALK_EXPRESSION_DRIVEN
            chain.reason = (f"this {kind} net is driven by the multi-net expression "
                            f"{edge.text!r}; it has no single upstream net to follow")
            chain.missing_evidence.append(
                f"which operand of {edge.text!r} is the {kind} source")
            return chain
        chain.nodes.append(DomainNode(
            path="/".join(scope) or "<top>", module=netlist.instance(scope).module_name
            if netlist.instance(scope) else "", port=edge.rhs_nets[0],
            kind=DOMAIN_SOURCE_CONTINUOUS_ASSIGN,
            evidence=f"continuous assignment {edge.text!r}"))
        cur_path, cur_port = scope, edge.rhs_nets[0]
    chain.status = DOMAIN_WALK_HOP_LIMIT
    chain.reason = (f"the {kind} source walk exceeded {MAX_DOMAIN_WALK_HOPS} hops, which "
                    "means a combinational loop rather than a real hierarchy")
    return chain


def _same_kind_inputs(netlist, path: tuple, kind: str, exclude: str = "") -> list:
    """The instance's own input ports that carry a clock (or reset) name token.

    Uses `connectivity`'s vocabulary, never a second one: the generic token set
    is the same one `find_amba_clock_reset_ports()` falls back to."""
    spec = set()
    for fam_tokens in (AMBA_FAMILY_RESET_SIGNALS if kind == "reset"
                       else AMBA_FAMILY_CLOCK_SIGNALS).values():
        spec |= set(fam_tokens)
    tokens = spec | set(GENERIC_RESET_SIGNAL_TOKENS if kind == "reset"
                        else GENERIC_CLOCK_SIGNAL_TOKENS)
    inst = netlist.instance(path)
    if inst is None:
        return []
    out = []
    for p in inst.port_names:
        if p == exclude or inst.port_directions.get(p) != "input":
            continue
        if amba_signal_tokens([p]) & tokens:
            out.append(p)
    return out


# -- clock frequency --------------------------------------------------------

CLOCK_FREQUENCY_MEASURED = "MEASURED_FROM_TRACE"
CLOCK_FREQUENCY_DECLARED = "DECLARED_PARAMETER"
CLOCK_FREQUENCY_UNKNOWN = "UNKNOWN"
CLOCK_FREQUENCY_NOT_CONSTANT = "TRACE_PERIOD_NOT_CONSTANT"
CLOCK_FREQUENCY_INSUFFICIENT_SAMPLES = "TRACE_HAS_FEWER_THAN_TWO_RISING_EDGES"

#: Parameter-name tokens that declare a frequency or period. A parameter is
#: DECLARED evidence, never a measurement: it is what the designer wrote, and
#: the tier says so.
_FREQUENCY_PARAM_TOKENS: tuple = ("FREQ", "FREQUENCY", "CLK_PERIOD", "PERIOD", "CLK_FREQ")


def measure_clock_period(trace: SignalTrace, signal: str) -> dict:
    """AMBA-24's "clock frequency if provable", from the real
    `connectivity.SignalTrace` contract `evaluate_zero_time_connectivity()`
    already consumes.

    A period is claimed ONLY when at least two rising edges are present and
    every measured interval is identical. A trace whose intervals differ is
    reported as NOT_CONSTANT with the observed set -- a clock that is gated,
    ramping, or being switched between sources during the window is a real
    finding, and averaging it into one number would erase it."""
    samples = [(t, v) for t, v in (trace.samples.get(signal) or [])
               if str(v) in ("0", "1")]
    rising = [t for (pt, pv), (t, v) in zip(samples, samples[1:])
              if pv == "0" and v == "1"]
    if len(rising) < 2:
        return {"status": CLOCK_FREQUENCY_INSUFFICIENT_SAMPLES,
                "period": None, "rising_edge_count": len(rising),
                "evidence": f"{len(rising)} rising edge(s) of {signal!r} in the trace"}
    periods = sorted({b - a for a, b in zip(rising, rising[1:])})
    if len(periods) > 1:
        return {"status": CLOCK_FREQUENCY_NOT_CONSTANT, "period": None,
                "observed_periods": periods, "rising_edge_count": len(rising),
                "evidence": f"{signal!r} shows {len(periods)} distinct periods "
                            f"({periods}) across {len(rising)} rising edges"}
    return {"status": CLOCK_FREQUENCY_MEASURED, "period": periods[0],
            "rising_edge_count": len(rising),
            "evidence": f"{len(rising)} rising edges of {signal!r}, all "
                        f"{periods[0]} trace-time-units apart"}


def _declared_frequency(netlist, chain: DomainChain) -> Optional[dict]:
    """A frequency/period PARAMETER on the clock source instance, if one exists
    with a literal default. Declared evidence: tiered T3 through
    `connectivity.classify_bind_tier()` -- it is what a name says, and a
    parameter overridden at instantiation would make it wrong."""
    for node in chain.nodes:              # nearest domain-starting element first
        inst = netlist.instance(parse_instance_path(node.path))
        for param in (inst.parameters if inst else []):
            name = str(param.get("name") or "")
            if not (amba_signal_tokens([name]) & set(_FREQUENCY_PARAM_TOKENS)):
                continue
            default = str(param.get("default_text") or "").strip()
            try:
                value = parse_addr(default)
            except (TypeError, ValueError):
                continue
            tier = classify_bind_tier(naming_match=name)
            return {"status": CLOCK_FREQUENCY_DECLARED, "parameter": name, "value": value,
                    "tier": tier.tier.value, "requires_human_confirmation": True,
                    "evidence": f"parameter {name} = {default} declared on "
                                f"{node.path} ({inst.module_name})"}
    return None


def analyze_clock_frequency(netlist, chain: DomainChain, signal_traces=None,
                            time_unit_seconds=None) -> dict:
    """Measurement first, declaration second, UNKNOWN last -- never a default.

    `time_unit_seconds` converts a measured period into Hz. Without it the
    period is reported in the trace's own time units and NO frequency is
    stated, because a `SignalTrace` carries no unit and inventing one would be
    the fabricated fact this whole pipeline exists to prevent."""
    result = {"status": CLOCK_FREQUENCY_UNKNOWN, "frequency_hz": None, "period": None,
              "evidence": "", "reason": ""}
    trace = (signal_traces or {}).get(chain.port) if chain.port else None
    if trace is not None:
        measured = measure_clock_period(trace, chain.port)
        result.update(measured)
        if measured["status"] == CLOCK_FREQUENCY_MEASURED:
            if time_unit_seconds:
                result["frequency_hz"] = 1.0 / (measured["period"] * time_unit_seconds)
            else:
                result["reason"] = (
                    "period measured in trace time units; no time_unit_seconds was "
                    "supplied, so a frequency in Hz is not stated rather than assumed")
            return result
    declared = _declared_frequency(netlist, chain)
    if declared is not None:
        result.update(declared)
        return result
    if not result["reason"]:
        result["reason"] = (
            "no signal trace for this clock and no frequency/period parameter with a "
            "literal default on its source instance; AMBA-24 asks for the frequency only "
            "'if provable'")
    return result


# -- reset polarity, sync/async --------------------------------------------

RESET_ACTIVE_LOW = "ACTIVE_LOW"
RESET_ACTIVE_HIGH = "ACTIVE_HIGH"
RESET_POLARITY_UNKNOWN = "UNKNOWN"
RESET_POLARITY_DISAGREEMENT = "NAME_AND_TRACE_DISAGREE"

#: The AMBA specifications define ONLY the n-suffixed, active-LOW reset. A port
#: spelled with that exact name is spec evidence (T2-grade), not a naming
#: guess -- which is why it is kept separate from the generic `_N` heuristic
#: below.
_AMBA_SPEC_ACTIVE_LOW_TOKENS: frozenset = frozenset(
    t for tokens in AMBA_FAMILY_RESET_SIGNALS.values() for t in tokens if t.endswith("N"))
_AMBA_SPEC_UNSUFFIXED_TOKENS: frozenset = frozenset(
    t for tokens in AMBA_FAMILY_RESET_SIGNALS.values() for t in tokens
    if not t.endswith("N"))
_GENERIC_ACTIVE_LOW_TOKENS: frozenset = frozenset({"RSTN", "RESETN", "NRST", "NRESET"})

RESET_SYNC_SYNCHRONIZED = "SYNCHRONIZED_RELEASE"
RESET_SYNC_UNKNOWN = "UNKNOWN"

#: Naming hints for a reset synchroniser in the reset hierarchy. Tiered through
#: `classify_bind_tier()` exactly like `adapter_sub_role_hint()`'s: a name is
#: never allowed to establish a structural fact on its own.
RESET_SYNCHRONIZER_NAME_HINTS: tuple = (
    "RST_SYNC", "RESET_SYNC", "RSTSYNC", "RESETSYNC", "SYNCHRONIZER", "SYNC")


def analyze_reset_polarity(chain: DomainChain, signal_traces=None) -> dict:
    """AMBA-24's "reset polarity", DERIVED rather than assumed.

    This is the direct replacement for passing `reset_active_low` into
    `connectivity.evaluate_zero_time_connectivity()` as a caller opinion: the
    polarity now comes from the AMBA spec's own port naming, from a real
    measured trace, or from neither -- in which case it is UNKNOWN and the
    caller must ask, not default.

    Name and trace disagreeing is reported as a DISAGREEMENT with both sides
    kept. Silently preferring either one is how a design whose reset really was
    re-polarised inside a wrapper gets a green Gate-2 result on a reset that
    never releases."""
    port = chain.port
    tokens = amba_signal_tokens([port]) if port else set()
    name_polarity, name_tier, name_evidence = RESET_POLARITY_UNKNOWN, None, ""
    if tokens & _AMBA_SPEC_ACTIVE_LOW_TOKENS:
        name_polarity = RESET_ACTIVE_LOW
        name_tier = "AMBA_SPECIFICATION"
        name_evidence = (f"{port} carries the AMBA-specified reset name "
                         f"{sorted(tokens & _AMBA_SPEC_ACTIVE_LOW_TOKENS)[0]}, which the "
                         "specification defines as active LOW")
    elif tokens & _GENERIC_ACTIVE_LOW_TOKENS:
        name_polarity = RESET_ACTIVE_LOW
        name_tier = classify_bind_tier(naming_match=port).tier.value
        name_evidence = (f"{port} carries an n-suffixed reset name; naming heuristic only, "
                         "it requires human confirmation")
    elif tokens & _AMBA_SPEC_UNSUFFIXED_TOKENS:
        name_evidence = (f"{port} drops the AMBA spec's n suffix. The specification defines "
                         "only the active-LOW form, so a missing suffix is not evidence of "
                         "active HIGH -- it is no evidence at all")

    trace_polarity, trace_evidence = RESET_POLARITY_UNKNOWN, ""
    trace = (signal_traces or {}).get(port) if port else None
    if trace is not None:
        values = [str(v) for _, v in (trace.samples.get(port) or []) if str(v) in ("0", "1")]
        squashed = [v for i, v in enumerate(values) if i == 0 or v != values[i - 1]]
        if squashed == ["0", "1"]:
            trace_polarity = RESET_ACTIVE_LOW
            trace_evidence = f"{port} is held 0 then released to 1 exactly once in the trace"
        elif squashed == ["1", "0"]:
            trace_polarity = RESET_ACTIVE_HIGH
            trace_evidence = f"{port} is held 1 then released to 0 exactly once in the trace"
        else:
            trace_evidence = (f"{port} shows the value sequence {squashed} -- not a single "
                              "assert-then-release, so the trace establishes no polarity")

    if (name_polarity != RESET_POLARITY_UNKNOWN
            and trace_polarity != RESET_POLARITY_UNKNOWN
            and name_polarity != trace_polarity):
        return {"polarity": REQUIRED_HUMAN_INPUT, "status": RESET_POLARITY_DISAGREEMENT,
                "name_polarity": name_polarity, "trace_polarity": trace_polarity,
                "name_evidence": name_evidence, "trace_evidence": trace_evidence,
                "evidence_tier": name_tier,
                "reason": "the port name and the measured trace state opposite polarities; "
                          "one of them describes a reset that was re-polarised on the way "
                          "here, and only a human can say which"}
    polarity = (trace_polarity if trace_polarity != RESET_POLARITY_UNKNOWN
                else name_polarity)
    status = polarity
    if polarity == RESET_POLARITY_UNKNOWN:
        return {"polarity": RESET_POLARITY_UNKNOWN, "status": RESET_POLARITY_UNKNOWN,
                "name_polarity": name_polarity, "trace_polarity": trace_polarity,
                "name_evidence": name_evidence, "trace_evidence": trace_evidence,
                "evidence_tier": name_tier,
                "reason": "neither the port name nor a measured trace establishes the "
                          "polarity; supply a trace of this reset or a designer statement"}
    return {"polarity": polarity, "status": status, "name_polarity": name_polarity,
            "trace_polarity": trace_polarity, "name_evidence": name_evidence,
            "trace_evidence": trace_evidence, "evidence_tier": (
                "MEASURED_TRACE" if trace_polarity != RESET_POLARITY_UNKNOWN else name_tier),
            "reason": ""}


def derived_reset_active_low(polarity_result: dict) -> bool:
    """The `reset_active_low` argument of
    `connectivity.evaluate_zero_time_connectivity()`, from AMBA-24's DERIVED
    polarity instead of a caller's opinion.

    Raises rather than defaulting when the polarity is unknown or disputed:
    Gate 2's whole claim is "this reset really releases", and answering it from
    an assumed polarity is the failure mode this function exists to remove."""
    polarity = polarity_result.get("polarity")
    if polarity == RESET_ACTIVE_LOW:
        return True
    if polarity == RESET_ACTIVE_HIGH:
        return False
    raise FabricAnalysisError("RESET_POLARITY_NOT_ESTABLISHED", {
        "status": polarity_result.get("status"),
        "reason": polarity_result.get("reason"),
        "hint": "AMBA-24 requires the polarity be reported, and Gate 2 requires it be "
                "TRUE; supply a signal trace of this reset or a designer statement rather "
                "than assuming active-low"})


def analyze_reset_synchronization(chain: DomainChain) -> dict:
    """AMBA-24's "sync/async reset if provable".

    Provable here means: a reset SYNCHRONISER instance really sits in the reset
    hierarchy this walk produced. Whether the receiving flops sample the reset
    synchronously is a property of an always-block sensitivity list, which a
    port/instance/assign-level parse does not model at all -- so that case is
    UNKNOWN with the missing evidence named, never guessed from the design's
    general style."""
    for node in chain.nodes:
        haystack = f"{node.module or ''}|{node.path}".upper()
        for hint in RESET_SYNCHRONIZER_NAME_HINTS:
            if hint in haystack:
                tier = classify_bind_tier(naming_match=hint)
                return {"status": RESET_SYNC_SYNCHRONIZED, "instance": node.path,
                        "module": node.module, "matched_token": hint,
                        "tier": tier.tier.value, "requires_human_confirmation": True,
                        "evidence": f"{node.path} ({node.module}) sits in this reset's "
                                    f"hierarchy and its name carries {hint!r}",
                        "reason": ""}
    return {"status": RESET_SYNC_UNKNOWN, "instance": "", "module": "", "matched_token": "",
            "tier": None, "requires_human_confirmation": True, "evidence": "",
            "reason": "no reset synchroniser was found in this reset's hierarchy, and "
                      "whether the receiving flops sample the reset synchronously lives in "
                      "always-block sensitivity lists that a port/instance/assign-level "
                      "parse does not model",
            "missing_evidence": ["the always-block sensitivity list of the flops this reset "
                                 "drives, or a designer statement"]}


# -- CDC / bridge path, and which side the bind is on -----------------------

CDC_NONE_ON_PATH = "NO_CDC_ON_PATH"
CDC_CROSSING_IDENTIFIED = "CDC_CROSSING_IDENTIFIED"
CDC_SUSPECTED_UNIDENTIFIED = "CDC_SUSPECTED_NO_CROSSING_ELEMENT_IDENTIFIED"
CDC_UNKNOWN = "UNKNOWN"

BIND_SIDE_NO_CDC = "SAME_DOMAIN_AS_FABRIC_AND_ENDPOINT"
BIND_SIDE_FABRIC = "FABRIC_SIDE_OF_CDC"
BIND_SIDE_ENDPOINT = "ENDPOINT_SIDE_OF_CDC"
BIND_SIDE_INTERMEDIATE = "INTERMEDIATE_DOMAIN_BETWEEN_FABRIC_AND_ENDPOINT"
BIND_SIDE_UNKNOWN = "UNKNOWN"

BRIDGE_NONE_ON_PATH = "NO_PROTOCOL_BRIDGE_ON_PATH"
BRIDGE_UPSTREAM_OF_BIND = "BIND_IS_UPSTREAM_OF_BRIDGE"
BRIDGE_DOWNSTREAM_OF_BIND = "BIND_IS_DOWNSTREAM_OF_BRIDGE"


def _clock_chain_at(netlist, path_str: str, bundle_prefix: str, protocol: str,
                    kind: str = "clock") -> DomainChain:
    """The clock (or reset) chain of one location, from
    `find_amba_clock_reset_ports()`'s verdict -- the SAME port identification
    AMBA-15's checklist used, so a domain analysis can never disagree with the
    checklist a human approved about which port the clock is."""
    path = parse_instance_path(path_str)
    inst = netlist.instance(path)
    if inst is None:
        return DomainChain(kind=kind, status=DOMAIN_WALK_NO_PORT,
                           reason=f"{path_str} is not an elaborated instance")
    verdict = find_amba_clock_reset_ports(
        protocol_key(protocol), bundle_prefix, inst.port_names)[kind]
    if verdict["status"] != CLOCK_RESET_RESOLVED:
        chain = DomainChain(
            kind=kind,
            status=(DOMAIN_WALK_AMBIGUOUS_PORT if verdict["candidates"]
                    else DOMAIN_WALK_NO_PORT),
            candidates=list(verdict["candidates"]),
            reason=f"find_amba_clock_reset_ports() returned {verdict['status']} for "
                   f"{path_str}:{bundle_prefix}")
        chain.missing_evidence.append(
            f"which port of {path_str} is this interface's {kind}")
        return chain
    return _walk_domain(netlist, path, verdict["port"], kind)


@dataclass
class BindPointDomainAnalysis:
    """AMBA-24's six per-bind-point determinations plus the seventh, the
    side-of-CDC/bridge statement."""
    row_id: str
    bind_location: str
    protocol: str
    clock: DomainChain
    reset: DomainChain
    clock_frequency: dict
    reset_polarity: dict
    reset_synchronization: dict
    cdc: dict
    bridge: dict
    bind_side: str

    def to_dict(self) -> dict:
        return {
            "row_id": self.row_id, "bind_location": self.bind_location,
            "protocol": self.protocol,
            "clock_hierarchy": self.clock.to_dict(),
            "clock_frequency": dict(self.clock_frequency),
            "reset_hierarchy": self.reset.to_dict(),
            "reset_polarity": dict(self.reset_polarity),
            "reset_synchronization": dict(self.reset_synchronization),
            "cdc_path": dict(self.cdc),
            "bridge_path": dict(self.bridge),
            "bind_side": self.bind_side,
        }

    def render_cells(self) -> dict:
        freq = self.clock_frequency
        freq_cell = (f"{freq['frequency_hz']:.6g} Hz" if freq.get("frequency_hz")
                     else (f"period={freq['period']}" if freq.get("period") is not None
                           else freq.get("status", CLOCK_FREQUENCY_UNKNOWN)))
        return {
            "bind_location": self.bind_location,
            "protocol": self.protocol,
            "clock_hierarchy": self.clock.hierarchy_text,
            "clock_frequency": freq_cell,
            "reset_hierarchy": self.reset.hierarchy_text,
            "reset_polarity": self.reset_polarity.get("polarity", RESET_POLARITY_UNKNOWN),
            "reset_sync": self.reset_synchronization.get("status", RESET_SYNC_UNKNOWN),
            "cdc_path": self.cdc.get("status", CDC_UNKNOWN),
            "bind_side": self.bind_side,
        }


def _bind_location_of(row: dict) -> tuple:
    """`(instance_path, bundle_prefix)` from a matrix or registry row's
    `proposed_vip_bind_hierarchy` / `vip_bind_hierarchy` cell, or `(None, None)`
    for a row that proposes none."""
    text = str(row.get("proposed_vip_bind_hierarchy")
               or row.get("vip_bind_hierarchy") or "")
    if not text or text == MULTIPLE_BRANCH_PARENT_BIND or text == REQUIRED_HUMAN_INPUT:
        return (None, None)
    path, _, prefix = text.rpartition(":")
    return (path or text, prefix)


def _identify_cdc(netlist, trace, fabric_domain: str, bind_domain: str,
                  endpoint_domain: str, protocol: str) -> dict:
    """Which element on the traced path changes clock domain.

    A domain CHANGE is established structurally (two different resolved source
    nodes); WHICH element performs it is then looked for among the hops the
    trace already recorded, using the CDC sub-role hint
    `amba_fabric_discovery.adapter_sub_role_hint()` already produces. A change
    with no identifiable element is reported as SUSPECTED, never as absent."""
    if DOMAIN_UNKNOWN in (fabric_domain, bind_domain, endpoint_domain):
        return {"status": CDC_UNKNOWN, "crossing_instances": [],
                "fabric_domain": fabric_domain, "bind_domain": bind_domain,
                "endpoint_domain": endpoint_domain,
                "reason": "at least one of the fabric, bind and endpoint clock domains "
                          "could not be resolved, so whether a CDC lies between them is "
                          "not established"}
    if fabric_domain == bind_domain == endpoint_domain:
        return {"status": CDC_NONE_ON_PATH, "crossing_instances": [],
                "fabric_domain": fabric_domain, "bind_domain": bind_domain,
                "endpoint_domain": endpoint_domain,
                "reason": "the fabric port, the proposed bind location and the endpoint "
                          "all resolve to one clock source"}
    crossings = []
    for hop in (trace.branches[0].hops if (trace and trace.branches) else ()):
        hint = afd.adapter_sub_role_hint(hop.module_name, hop.instance_path)
        if hint and hint["sub_role"] == "CDC_OR_CLOCK_RESET_WRAPPER":
            crossings.append({"instance_path": hop.instance_path,
                              "module": hop.module_name,
                              "matched_token": hint["matched_token"],
                              "tier": hint["tier"],
                              "requires_human_confirmation": True})
    if crossings:
        return {"status": CDC_CROSSING_IDENTIFIED, "crossing_instances": crossings,
                "fabric_domain": fabric_domain, "bind_domain": bind_domain,
                "endpoint_domain": endpoint_domain,
                "reason": "the clock domains differ across this path and a CDC element was "
                          "found on it (naming hint -- confirm with the designer)"}
    return {"status": CDC_SUSPECTED_UNIDENTIFIED, "crossing_instances": [],
            "fabric_domain": fabric_domain, "bind_domain": bind_domain,
            "endpoint_domain": endpoint_domain,
            "reason": "the clock domains genuinely differ across this path but no element "
                      "on the traced hop list identifies itself as the crossing; the "
                      "crossing exists and its location is not established"}


def _bind_side(cdc: dict) -> str:
    status = cdc["status"]
    if status == CDC_NONE_ON_PATH:
        return BIND_SIDE_NO_CDC
    if status == CDC_UNKNOWN:
        return BIND_SIDE_UNKNOWN
    fabric, bind, endpoint = cdc["fabric_domain"], cdc["bind_domain"], cdc["endpoint_domain"]
    if bind == fabric:
        return BIND_SIDE_FABRIC
    if bind == endpoint:
        return BIND_SIDE_ENDPOINT
    return BIND_SIDE_INTERMEDIATE


def analyze_bind_point_domains(netlist, row: dict, trace=None, *, signal_traces=None,
                               time_unit_seconds=None) -> BindPointDomainAnalysis:
    """AMBA-24 for ONE proposed bind point (one AMBA-16 matrix row or AMBA-22
    registry row)."""
    bind_path, bind_prefix = _bind_location_of(row)
    protocol = str(row.get("protocol") or AMBA_PROTOCOL_UNRESOLVED)
    if bind_path is None:
        unavailable = DomainChain(
            kind="clock", status=DOMAIN_WALK_NO_PORT,
            reason="this row proposes no single bind location (AMBA-12/13 leave the choice "
                   "of branch to a human), so there is no location to analyse")
        reset_unavailable = DomainChain(kind="reset", status=DOMAIN_WALK_NO_PORT,
                                        reason=unavailable.reason)
        return BindPointDomainAnalysis(
            row_id=str(row.get("row_id") or row.get("port_id") or ""),
            bind_location=REQUIRED_HUMAN_INPUT, protocol=protocol,
            clock=unavailable, reset=reset_unavailable,
            clock_frequency={"status": CLOCK_FREQUENCY_UNKNOWN, "frequency_hz": None,
                             "period": None, "reason": unavailable.reason},
            reset_polarity={"polarity": RESET_POLARITY_UNKNOWN,
                            "status": RESET_POLARITY_UNKNOWN,
                            "reason": unavailable.reason},
            reset_synchronization={"status": RESET_SYNC_UNKNOWN,
                                   "reason": unavailable.reason},
            cdc={"status": CDC_UNKNOWN, "crossing_instances": [],
                 "fabric_domain": DOMAIN_UNKNOWN, "bind_domain": DOMAIN_UNKNOWN,
                 "endpoint_domain": DOMAIN_UNKNOWN, "reason": unavailable.reason},
            bridge={"status": BRIDGE_NONE_ON_PATH, "bridges": []},
            bind_side=BIND_SIDE_UNKNOWN)

    clock = _clock_chain_at(netlist, bind_path, bind_prefix, protocol, "clock")
    reset = _clock_chain_at(netlist, bind_path, bind_prefix, protocol, "reset")

    fabric_domain, endpoint_domain = DOMAIN_UNKNOWN, DOMAIN_UNKNOWN
    if trace is not None:
        fabric_domain = _clock_chain_at(
            netlist, trace.fabric_instance_path, trace.bundle_prefix,
            trace.fabric_protocol, "clock").domain_id
        branch = trace.branches[0] if trace.branches else None
        if branch is not None and branch.endpoint_instance_path:
            endpoint_bundle = find_bundle(
                netlist, parse_instance_path(branch.endpoint_instance_path),
                bind_prefix)
            endpoint_domain = _clock_chain_at(
                netlist, branch.endpoint_instance_path,
                endpoint_bundle.prefix if endpoint_bundle else bind_prefix,
                branch.endpoint_protocol or protocol, "clock").domain_id

    cdc = _identify_cdc(netlist, trace, fabric_domain, clock.domain_id, endpoint_domain,
                        protocol)
    bridges = [b.to_dict() for b in (trace.bridges if trace else ())]
    bridge = {"status": BRIDGE_NONE_ON_PATH if not bridges
              else (BRIDGE_DOWNSTREAM_OF_BIND if row.get("amba11_second_side")
                    else BRIDGE_UPSTREAM_OF_BIND),
              "bridges": bridges}
    return BindPointDomainAnalysis(
        row_id=str(row.get("row_id") or row.get("port_id") or ""),
        bind_location=f"{bind_path}:{bind_prefix}", protocol=protocol,
        clock=clock, reset=reset,
        clock_frequency=analyze_clock_frequency(netlist, clock, signal_traces,
                                                time_unit_seconds),
        reset_polarity=analyze_reset_polarity(reset, signal_traces),
        reset_synchronization=analyze_reset_synchronization(reset),
        cdc=cdc, bridge=bridge, bind_side=_bind_side(cdc))


def analyze_all_bind_point_domains(netlist, rows, traces=None, *, signal_traces=None,
                                   time_unit_seconds=None) -> list:
    """AMBA-24 for every row of the AMBA-16 matrix / AMBA-22 registry.

    Every row is analysed, including one that proposes no bind location -- the
    same rule AMBA-16 applies to the matrix itself. A row silently absent from
    this table is the omission that makes a domain report unreviewable."""
    by_interface = {t.interface_id: t for t in traces or ()}
    out = []
    for row in rows or ():
        key = str(row.get("fabric_port") or "").split(" [")[0]
        out.append(analyze_bind_point_domains(
            netlist, row, by_interface.get(key), signal_traces=signal_traces,
            time_unit_seconds=time_unit_seconds))
    return out


_DOMAIN_COLUMNS: tuple = (
    ("bind_location", "Bind Point"),
    ("protocol", "Protocol"),
    ("clock_hierarchy", "Clock Hierarchy"),
    ("clock_frequency", "Clock Frequency"),
    ("reset_hierarchy", "Reset Hierarchy"),
    ("reset_polarity", "Reset Polarity"),
    ("reset_sync", "Sync/Async Reset"),
    ("cdc_path", "CDC / Bridge Path"),
    ("bind_side", "Bind Side"),
)


def render_clock_reset_domain_table(analyses) -> str:
    return render_markdown_table(
        list(_DOMAIN_COLUMNS), [a.render_cells() for a in analyses or ()],
        empty_note="(no bind point was analysed)")


def render_clock_reset_domain_report(analyses) -> str:
    lines = ["# AMBA-24 Clock / Reset Domain Analysis", "",
             f"{len(analyses or ())} bind point(s).", "",
             render_clock_reset_domain_table(analyses), ""]
    unknown = [a for a in analyses or ()
               if a.reset_polarity.get("polarity") in (RESET_POLARITY_UNKNOWN,
                                                       REQUIRED_HUMAN_INPUT)]
    if unknown:
        lines += ["## Bind points whose reset polarity is not established", "",
                  "Gate 2 (`connectivity.evaluate_zero_time_connectivity`) must NOT be run "
                  "for these with an assumed polarity -- supply a trace of the reset or a "
                  "designer statement.", "",
                  "\n".join(f"- {a.bind_location}: {a.reset_polarity.get('reason', '')}"
                            for a in unknown), ""]
    suspected = [a for a in analyses or ()
                 if a.cdc.get("status") == CDC_SUSPECTED_UNIDENTIFIED]
    if suspected:
        lines += ["## Clock-domain crossings whose crossing element is not identified", "",
                  "\n".join(f"- {a.bind_location}: {a.cdc['fabric_domain']} -> "
                            f"{a.cdc['bind_domain']} -> {a.cdc['endpoint_domain']}"
                            for a in suspected), ""]
    text = "\n".join(lines)
    assert_no_bind_statement(text)
    return text


# ===========================================================================
# AMBA-25: SCOREBOARD + PORT SCALING
#
# "Final design must support variable fabric size and mixed protocols. Use
#  registry-driven per-port scoreboard architecture. Support: multiple masters
#  / multiple slaves / mixed protocols / protocol bridges / parallel
#  AXI/AHB/Stream traffic / serialized APB where architecture requires. Avoid
#  cross-port scheduling interlocks unless actual protocol/resource dependency
#  requires them."
# ===========================================================================

TRAFFIC_POLICY_PARALLEL = "PARALLEL"
TRAFFIC_POLICY_SERIALIZED = "SERIALIZED"
TRAFFIC_POLICY_UNKNOWN = REQUIRED_HUMAN_INPUT

#: AMBA-25's own grouping, by protocol FAMILY so a new sub-protocol of a known
#: family inherits the right policy instead of silently falling to UNKNOWN.
#: APB is serialized because the protocol has one outstanding transfer per
#: bus segment -- there is nothing for a scoreboard to interleave.
PROTOCOL_TRAFFIC_POLICY: dict = {
    "AXI_MM": TRAFFIC_POLICY_PARALLEL,
    "AXI_STREAM": TRAFFIC_POLICY_PARALLEL,
    "AHB": TRAFFIC_POLICY_PARALLEL,
    "APB": TRAFFIC_POLICY_SERIALIZED,
}

INTERLOCK_REQUIRED = "ORDERING_REQUIRED"
INTERLOCK_NOT_REQUIRED = "NO_INTERLOCK"
INTERLOCK_DEPENDENCY_SHARED_SLAVE = "SHARED_SLAVE_RESOURCE"
INTERLOCK_DEPENDENCY_SERIALIZED_SEGMENT = "SHARED_SERIALIZED_BUS_SEGMENT"


@dataclass
class FabricScalingPlan:
    """AMBA-25's registry-driven, size-agnostic scoreboard/port architecture."""
    masters: list = field(default_factory=list)
    slaves: list = field(default_factory=list)
    bridges: list = field(default_factory=list)
    scoreboard_matrix: list = field(default_factory=list)
    per_port_channels: list = field(default_factory=list)
    traffic_policies: list = field(default_factory=list)
    interlocks: list = field(default_factory=list)
    id_width: dict = field(default_factory=dict)
    unresolved_ports: list = field(default_factory=list)

    @property
    def fabric_size(self) -> dict:
        return {"masters": len(self.masters), "slaves": len(self.slaves),
                "bridges": len(self.bridges), "pairs": len(self.scoreboard_matrix)}

    @property
    def mixed_protocol(self) -> bool:
        return len({e["protocol"] for e in self.masters + self.slaves}) > 1

    def to_dict(self) -> dict:
        return {
            "fabric_size": self.fabric_size, "mixed_protocol": self.mixed_protocol,
            "masters": [dict(m) for m in self.masters],
            "slaves": [dict(s) for s in self.slaves],
            "bridges": [dict(b) for b in self.bridges],
            "scoreboard_matrix": [dict(p) for p in self.scoreboard_matrix],
            "per_port_channels": [dict(c) for c in self.per_port_channels],
            "traffic_policies": [dict(t) for t in self.traffic_policies],
            "interlocks": [dict(i) for i in self.interlocks],
            "id_width": dict(self.id_width),
            "unresolved_ports": [dict(u) for u in self.unresolved_ports],
        }


def traffic_policy_for(protocol: str) -> dict:
    family = protocol_family(protocol)
    policy = PROTOCOL_TRAFFIC_POLICY.get(family, TRAFFIC_POLICY_UNKNOWN)
    return {"protocol": protocol, "family": family or REQUIRED_HUMAN_INPUT,
            "policy": policy,
            "rationale": ("AMBA-25 groups AXI/AHB/Stream traffic as parallel and APB as "
                          "serialized where architecture requires"
                          if policy != TRAFFIC_POLICY_UNKNOWN else
                          "this interface's protocol never resolved, so no traffic policy "
                          "may be assumed for it")}


def _endpoint_protocols(rows) -> tuple:
    """`endpoint hierarchy -> protocol` from the registry, plus the conflicts.

    Two registry rows naming the same endpoint with different protocols is a
    real finding (a dual-protocol endpoint, or a mis-traced one) and is
    reported as `REQUIRED_HUMAN_INPUT` with both spellings, never silently
    resolved to whichever row came first."""
    seen: dict = {}
    for row in rows or ():
        if row.get("amba11_second_side"):
            continue
        path = row.get("endpoint_hierarchy")
        if not path or path == ENDPOINT_HIERARCHY_NOT_ESTABLISHED:
            continue
        seen.setdefault(path, set()).add(str(row.get("protocol") or AMBA_PROTOCOL_UNRESOLVED))
    protocols, conflicts = {}, []
    for path, values in seen.items():
        if len(values) == 1:
            protocols[path] = next(iter(values))
        else:
            protocols[path] = REQUIRED_HUMAN_INPUT
            conflicts.append({"endpoint": path, "protocols": sorted(values)})
    return protocols, conflicts


def _port_id_by_endpoint(rows) -> dict:
    out: dict = {}
    for row in rows or ():
        if row.get("amba11_second_side"):
            continue
        path = row.get("endpoint_hierarchy")
        if path and path != ENDPOINT_HIERARCHY_NOT_ESTABLISHED:
            out.setdefault(path, row.get("port_id"))
    return out


def _bridge_nodes(rows) -> list:
    """AMBA-25's "protocol bridges" as a DISTINCT node type.

    A bridge is two-sided (AMBA-11's own "record BOTH sides" rule) and has no
    representation in a masters/slaves-only schema, which is exactly the gap
    this list closes. The upstream protocol is read from the bridge row's
    PARENT row -- never inherited downward -- so "do not label a downstream APB
    endpoint as AXI" stays impossible here too."""
    by_row_id = {r.get("row_id"): r for r in rows or ()}
    out = []
    for row in rows or ():
        if not row.get("amba11_second_side"):
            continue
        parent = by_row_id.get(row.get("parent_row_id")) or {}
        out.append({
            "port_id": row.get("port_id"),
            "bridge_instance": row.get("last_known_hierarchy")
                               or row.get("endpoint_hierarchy"),
            "upstream_protocol": parent.get("protocol") or REQUIRED_HUMAN_INPUT,
            "downstream_protocol": row.get("protocol") or REQUIRED_HUMAN_INPUT,
            "upstream_traffic_policy": traffic_policy_for(
                parent.get("protocol") or "")["policy"],
            "downstream_traffic_policy": traffic_policy_for(
                row.get("protocol") or "")["policy"],
            "scoreboard_channel": row.get("scoreboard_channel"),
        })
    return out


def _interlocks(masters, slaves, matrix, bridges) -> list:
    """AMBA-25: "Avoid cross-port scheduling interlocks unless actual
    protocol/resource dependency requires them."

    Implemented as a REFUSAL by default. Every unordered master pair is listed
    with an explicit verdict, and an interlock is claimed only where a concrete
    dependency exists:

      * both masters reach the same slave -- a real shared resource;
      * both reach a slave behind the same SERIALIZED (APB) bridge segment --
        the segment itself admits one transfer at a time.

    Every other pair is `NO_INTERLOCK` with the reason stated, so a scoreboard
    architecture that adds cross-port ordering anyway is contradicting a
    written finding rather than filling a silence."""
    reach: dict = {}
    for pair in matrix:
        if pair.get("status") == "IMPLEMENTED":
            reach.setdefault(pair["master_id"], set()).add(pair["slave_id"])
    serialized_slaves = {
        s["endpoint"] for s in slaves
        if traffic_policy_for(s["protocol"])["policy"] == TRAFFIC_POLICY_SERIALIZED}
    serialized_slaves |= {b["bridge_instance"] for b in bridges
                          if b["downstream_traffic_policy"] == TRAFFIC_POLICY_SERIALIZED}
    ids = [m["endpoint"] for m in masters]
    out = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = sorted(reach.get(a, set()) & reach.get(b, set()))
            shared_serialized = sorted(set(shared) & serialized_slaves)
            if shared_serialized:
                out.append({"master_a": a, "master_b": b, "verdict": INTERLOCK_REQUIRED,
                            "dependency": INTERLOCK_DEPENDENCY_SERIALIZED_SEGMENT,
                            "shared_resources": shared_serialized,
                            "rationale": "both masters reach a serialized (APB-family) "
                                         "segment that admits one transfer at a time"})
            elif shared:
                out.append({"master_a": a, "master_b": b, "verdict": INTERLOCK_REQUIRED,
                            "dependency": INTERLOCK_DEPENDENCY_SHARED_SLAVE,
                            "shared_resources": shared,
                            "rationale": "both masters reach the same slave, an actual "
                                         "shared resource dependency"})
            else:
                out.append({"master_a": a, "master_b": b, "verdict": INTERLOCK_NOT_REQUIRED,
                            "dependency": None, "shared_resources": [],
                            "rationale": "no shared slave and no shared serialized segment; "
                                         "AMBA-25 forbids a cross-port scheduling interlock "
                                         "without an actual dependency"})
    return out


def _id_width(masters, rows) -> dict:
    """AMBA-25's ID-width consequence of a variable master count, via
    `amba_fabric_generator.compute_id_width()` -- the one formula, reused."""
    widths = {}
    for row in rows or ():
        path = row.get("endpoint_hierarchy")
        if not path:
            continue
        raw = str(row.get("id_width") or "")
        if raw.isdigit():
            widths[path] = int(raw)
    unknown = [m["endpoint"] for m in masters if m["endpoint"] not in widths]
    if unknown or not masters:
        return {"status": REQUIRED_HUMAN_INPUT, "value": None,
                "masters_without_id_width": unknown,
                "reason": "compute_id_width() needs every master's own ID width; a master "
                          "whose AMBA-15 id_width check answered UNKNOWN cannot be "
                          "defaulted to a number"}
    value = compute_id_width([{"id": m["endpoint"], "id_width": widths[m["endpoint"]]}
                              for m in masters])
    return {"status": "COMPUTED", "value": value,
            "formula": "ceil(log2(M)) + max_m(I_m)",
            "master_id_widths": {m["endpoint"]: widths[m["endpoint"]] for m in masters},
            "computed_by": "amba_fabric_generator.compute_id_width"}


def build_fabric_scaling_plan(rows, *, connectivity=None,
                              assume_full_connectivity: bool = False) -> FabricScalingPlan:
    """AMBA-25 from an AMBA-22 registry, for ANY fabric size.

    Nothing here is indexed by a fixed M or N: masters and slaves come from
    `registry_endpoints()`, the pairing from `build_scoreboard_matrix()`'s own
    loop, and every per-port artifact is keyed by the registry's real
    `port_id`. A two-by-two and a three-by-four fabric take the same path.

    `connectivity` / `assume_full_connectivity` are passed straight through to
    `build_scoreboard_matrix()`, which raises `UNRESOLVED_PAIR` for a pair that
    is neither evidenced nor waived -- reused rather than softened, because
    guessing a pair is exactly what that error exists to prevent.
    """
    endpoints = registry_endpoints(rows)
    protocols, conflicts = _endpoint_protocols(rows)
    port_ids = _port_id_by_endpoint(rows)

    def _nodes(paths):
        return [{"endpoint": p, "port_id": port_ids.get(p) or REQUIRED_HUMAN_INPUT,
                 "protocol": protocols.get(p, REQUIRED_HUMAN_INPUT)} for p in paths]

    masters, slaves = _nodes(endpoints["masters"]), _nodes(endpoints["slaves"])
    try:
        matrix = build_scoreboard_matrix([{"id": m["endpoint"]} for m in masters],
                                         [{"id": s["endpoint"]} for s in slaves],
                                         connectivity, assume_full_connectivity)
    except ScoreboardMatrixError as exc:
        raise FabricAnalysisError("AMBA25_SCOREBOARD_MATRIX_UNRESOLVED", {
            "reason": exc.reason, "detail": exc.detail,
            "hint": "supply per-master accessible_slaves/excluded evidence, or opt into "
                    "assume_full_connectivity; AMBA-25 may not guess a pair"}) from exc

    by_endpoint = {m["endpoint"]: m for m in masters}
    by_endpoint.update({s["endpoint"]: s for s in slaves})
    annotated = []
    for pair in matrix:
        mp = by_endpoint.get(pair["master_id"], {}).get("protocol", REQUIRED_HUMAN_INPUT)
        sp = by_endpoint.get(pair["slave_id"], {}).get("protocol", REQUIRED_HUMAN_INPUT)
        known = REQUIRED_HUMAN_INPUT not in (mp, sp)
        annotated.append({**pair, "master_protocol": mp, "slave_protocol": sp,
                          "protocol_crossing": (mp != sp) if known else REQUIRED_HUMAN_INPUT})

    bridges = _bridge_nodes(rows)
    channels = [{"port_id": r.get("port_id"), "fabric_port": r.get("fabric_port"),
                 "protocol": r.get("protocol"),
                 "scoreboard_channel": r.get("scoreboard_channel"),
                 "vip_mode": r.get("vip_mode"),
                 "is_bridge_second_side": bool(r.get("amba11_second_side"))}
                for r in rows or ()
                if r.get("vip_bind_hierarchy") != MULTIPLE_BRANCH_PARENT_BIND]
    policies = [{"port_id": c["port_id"], **traffic_policy_for(c["protocol"] or "")}
                for c in channels]
    return FabricScalingPlan(
        masters=masters, slaves=slaves, bridges=bridges, scoreboard_matrix=annotated,
        per_port_channels=channels, traffic_policies=policies,
        interlocks=_interlocks(masters, slaves, annotated, bridges),
        id_width=_id_width(masters, rows),
        unresolved_ports=list(endpoints["unresolved"]) + conflicts)


def assert_every_port_has_its_own_channel(plan: FabricScalingPlan) -> None:
    """AMBA-25's "registry-driven per-port scoreboard architecture", enforced.

    Two ports sharing one scoreboard channel is the exact failure a per-port
    architecture exists to prevent: two interfaces' transactions land in one
    comparator and a mismatch on either is attributed to both.
    `REQUIRED_HUMAN_INPUT` is exempt -- it is the honest "nothing has
    established this yet" value AMBA-21/22 already use, and many ports may
    legitimately carry it at once."""
    seen: dict = {}
    duplicates = []
    for entry in plan.per_port_channels:
        channel = entry.get("scoreboard_channel")
        if not channel or channel == REQUIRED_HUMAN_INPUT:
            continue
        if channel in seen:
            duplicates.append({"scoreboard_channel": channel,
                               "port_ids": [seen[channel], entry.get("port_id")]})
        seen[channel] = entry.get("port_id")
    if duplicates:
        raise FabricAnalysisError("AMBA25_SCOREBOARD_CHANNEL_SHARED_BY_TWO_PORTS", {
            "duplicates": duplicates,
            "hint": "AMBA-25 requires a registry-driven PER-PORT scoreboard architecture; "
                    "two ports on one channel merges their transaction streams"})


_SCALING_PAIR_COLUMNS: tuple = (
    ("master_id", "Master"),
    ("master_protocol", "Master Protocol"),
    ("slave_id", "Slave"),
    ("slave_protocol", "Slave Protocol"),
    ("status", "Pair"),
    ("protocol_crossing", "Protocol Crossing"),
    ("waiver_evidence", "Waiver Evidence"),
)

_SCALING_CHANNEL_COLUMNS: tuple = (
    ("port_id", "port_id"),
    ("fabric_port", "Fabric Port"),
    ("protocol", "Protocol"),
    ("policy", "Traffic Policy"),
    ("scoreboard_channel", "Scoreboard Channel"),
    ("vip_mode", "VIP Mode"),
)

_SCALING_BRIDGE_COLUMNS: tuple = (
    ("port_id", "port_id"),
    ("bridge_instance", "Bridge Instance"),
    ("upstream_protocol", "Upstream"),
    ("downstream_protocol", "Downstream"),
    ("upstream_traffic_policy", "Upstream Policy"),
    ("downstream_traffic_policy", "Downstream Policy"),
)

_SCALING_INTERLOCK_COLUMNS: tuple = (
    ("master_a", "Master A"),
    ("master_b", "Master B"),
    ("verdict", "Verdict"),
    ("dependency", "Dependency"),
    ("shared", "Shared Resources"),
    ("rationale", "Rationale"),
)


def render_fabric_scaling_report(plan: FabricScalingPlan) -> str:
    size = plan.fabric_size
    policy_by_port = {p["port_id"]: p["policy"] for p in plan.traffic_policies}
    channel_rows = [{**c, "policy": policy_by_port.get(c["port_id"], TRAFFIC_POLICY_UNKNOWN)}
                    for c in plan.per_port_channels]
    interlock_rows = [{**i, "shared": ", ".join(i["shared_resources"]) or "-",
                       "dependency": i["dependency"] or "-"} for i in plan.interlocks]
    lines = [
        "# AMBA-25 Scoreboard + Port Scaling", "",
        f"Fabric size: {size['masters']} master(s) x {size['slaves']} slave(s) = "
        f"{size['pairs']} scoreboard pair(s); {size['bridges']} protocol bridge(s). "
        f"Mixed protocols: {plan.mixed_protocol}.", "",
        "## Per-pair scoreboard matrix", "",
        render_markdown_table(list(_SCALING_PAIR_COLUMNS), plan.scoreboard_matrix,
                              empty_note="(no master/slave pair was resolved)"), "",
        "## Registry-driven per-port scoreboard channels", "",
        render_markdown_table(list(_SCALING_CHANNEL_COLUMNS), channel_rows,
                              empty_note="(no port in the registry)"), "",
        "## Protocol bridges (both sides recorded, AMBA-11)", "",
        render_markdown_table(list(_SCALING_BRIDGE_COLUMNS), plan.bridges,
                              empty_note="(no protocol bridge on any traced path)"), "",
        "## Cross-port scheduling interlocks", "",
        "AMBA-25: avoid cross-port scheduling interlocks unless an actual protocol or "
        "resource dependency requires them. Every master pair is listed with an explicit "
        "verdict so that adding an interlock elsewhere contradicts a written finding "
        "rather than filling a silence.", "",
        render_markdown_table(list(_SCALING_INTERLOCK_COLUMNS), interlock_rows,
                              empty_note="(fewer than two masters, so no pair to order)"),
        "",
        f"ID width: {plan.id_width.get('status')}"
        + (f" = {plan.id_width['value']} ({plan.id_width.get('formula')})"
           if plan.id_width.get("value") is not None else ""), "",
    ]
    if plan.unresolved_ports:
        lines += ["## Ports and endpoints this plan could not place", "",
                  "\n".join(f"- {u}" for u in plan.unresolved_ports), ""]
    lines.append(
        "This plan is a review artifact. It proposes a scoreboard architecture and names "
        "no bind statement; nothing here is emitted into any environment before AMBA-30's "
        "human review and AMBA-31's explicit approval.")
    text = "\n".join(lines)
    assert_no_bind_statement(text)
    return text
