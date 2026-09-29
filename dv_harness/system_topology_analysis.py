"""SYS-28..SYS-30 of the System-Level Verification Integration workflow: the
cross-subsystem ADDRESS MAP ANALYSIS, the cross-subsystem CLOCK / RESET
INTEGRATION comparison, and the SYSTEM-LEVEL SCENARIO MODEL plan.

WHAT THIS MODULE IS NOT
-----------------------
Stated first, because it is the boundary this whole workflow exists inside.
Nothing here emits a System command.txt, a scenario body, a parallel block, a
System Virtual Sequencer, a command router/adapter, an address decoder, a
clock/reset generator or any System-Level UVM source.

  * SYS-28 CLASSIFIES cross-subsystem address relationships and NEVER
    relocates, remaps or reserves a range. Its only output is a table plus,
    for a real conflict, a question filed into the real question queue.
  * SYS-29 COMPARES two subsystems' clock and reset facts and NEVER
    generates, merges or renames a clock or reset. Its ownership column is a
    PROPOSAL whose status is pinned to PLANNED_NOT_IMPLEMENTED.
  * SYS-30 describes the SHAPE a multi-subsystem scenario would have -- which
    subsystems participate, which of their OWN existing commands would sit in
    a parallel block and which in a sequential one, and which statement
    vocabulary that shape is derived from. Every scenario's
    `scenario_body_status` is pinned to
    NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL. No command text is emitted,
    not even a fragment.

`assert_no_emitted_artifacts()` is the runtime check of all three, the schema
refuses a document that violates any of them, and tests assert both rather
than trusting this paragraph.

WHY A NEW MODULE RATHER THAN AN EXTENSION
-----------------------------------------
Every existing address-map and clock/reset primitive in this repo is
SINGLE-subsystem by construction, and that is not an oversight to be patched
in place -- it is what those functions mean:

  * `uvm_generator/amba_fabric_generator.compute_address_regions()` validates
    ONE fabric's own slave list against ONE `addr_width`, and its
    full-coverage rule ("the declared regions must span [0, 2**addr_width)")
    is only meaningful for one decoder. Two subsystems' address maps are not
    one fabric and must not be concatenated into one region list -- doing so
    would report a "gap" between two subsystems that legitimately occupy
    different parts of the SoC map.
  * `uvm_generator/address_map_verifier.verify_address_map()` corroborates ONE
    decoder's claimed bases against ONE BFM-access histogram. It has no
    second subsystem to compare against and no place to put one.
  * `phy_boundary.py`, `sys_regmap.py` and `init_seq.py` are one-DUT,
    one-interface, one-bind primitives; `sys_regmap`'s mode-determining bits
    and `init_seq`'s Gate-2 precondition evaluation say nothing about
    "subsystem A's clock versus subsystem B's".

So this module holds the CROSS-subsystem layer and re-derives none of their
arithmetic:

  * `_pairwise_overlap()` decides whether two regions intersect by CALLING
    `amba_fabric_generator.compute_address_regions()` on the two-region set
    and reading which `AddressMapError` it raises. That keeps one definition
    of "overlap" in this repo -- including its exclusive-end convention
    (`cur.start < prev.end`) -- instead of a second interval comparison here
    that could drift from the gate that convention exists to match.
  * Per-subsystem self-consistency (does ONE subsystem's own map overlap
    itself?) is likewise the existing function's verdict, recorded verbatim
    from the reason it raised.
  * `system_resource_inventory.RESOURCE_TYPE_TOKENS` supplies the
    memory/DMA/APB/AXI name vocabulary. No second token table.
  * Duplicate/conflicting clock-reset AGENT detection (SYS-29's second
    sentence) is READ from the SYS-15 registry's own
    `resource_type == CLOCK_RESET_AGENT` entries and their already-decided
    `conflict_status`/`reuse_decision`. SYS-29 does not re-run SYS-10/SYS-11.
  * SYS-30's block plan is built from `system_scheduling_plan`'s SYS-25 pair
    relationships and `system_command_plan`'s SYS-21 IR. It classifies no
    pair itself.
  * A cross-subsystem address CONFLICT escalates through
    `source_authority.escalate_conflict()` -- the same channel
    `address_map_verifier` and `system_command_plan` already use. There is no
    second conflict resolver here.

WHY AN OVERLAP IS NOT AUTOMATICALLY A BUG
-----------------------------------------
SYS-28's own vocabulary has FOUR values, and three of them describe an
overlap that is fine. Two subsystems whose command.txt files both reach a
shared DDR window overlap by design; two subsystems that both declare the
same APB configuration block overlap because it is the same block seen
twice. Reporting either as a conflict would train a reader to ignore the
column. So the classifier fires SHARED_MEMORY and ADDRESS_OVERLAP_VALID from
positive evidence, ADDRESS_OVERLAP_CONFLICT only as the residual of a real
intersection with no such evidence, and UNKNOWN whenever the inputs
themselves are in doubt -- including the case that is easiest to get wrong:
an overlap computed on top of a base address that a subsystem's OWN
`register_map_agreement` already reports as DISAGREES. An overlap derived
from a disputed base is not a finding about the two subsystems, it is a
finding about one subsystem's own two artifacts, and calling it a
cross-subsystem conflict would point the reader at the wrong pair entirely.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from . import subsystem_architecture_analysis as saa
from . import system_command_plan as scp
from . import system_resource_inventory as sri
from . import system_resource_registry as srr
from . import system_scheduling_plan as ssp
from .uvm_generator import amba_fabric_generator as afg

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "system_topology_analysis.schema.json"
SCHEMA_VERSION = "1.0"


# ===========================================================================
# SYS-28 vocabulary
# ===========================================================================

#: SYS-28's classification vocabulary, verbatim and in the requirement's own
#: order: "Detect ADDRESS_OVERLAP_VALID / ADDRESS_OVERLAP_CONFLICT /
#: SHARED_MEMORY / UNKNOWN." Four values. Held to that sentence by a test.
ADDRESS_OVERLAP_VALID = "ADDRESS_OVERLAP_VALID"
ADDRESS_OVERLAP_CONFLICT = "ADDRESS_OVERLAP_CONFLICT"
SHARED_MEMORY = "SHARED_MEMORY"
ADDRESS_UNKNOWN = "UNKNOWN"

SYS28_OVERLAP_CLASSES: tuple = (
    ADDRESS_OVERLAP_VALID, ADDRESS_OVERLAP_CONFLICT, SHARED_MEMORY, ADDRESS_UNKNOWN,
)

#: Precedence, most-doubtful first and most-specific-evidence next. UNKNOWN
#: leads deliberately: a pair whose inputs are unreadable or self-disputed
#: cannot be honestly called valid, shared or conflicting, and a classifier
#: that resolved such a pair to CONFLICT would be manufacturing a
#: cross-subsystem finding out of a single subsystem's internal inconsistency.
#: CONFLICT is last because it is the RESIDUAL -- "these two really intersect
#: and nothing explains why" -- not a signal of its own.
SYS28_PRECEDENCE: tuple = (
    ADDRESS_UNKNOWN, SHARED_MEMORY, ADDRESS_OVERLAP_VALID, ADDRESS_OVERLAP_CONFLICT,
)

#: SYS-28's first sentence: "Determine register/memory/DMA/APB/AXI ranges".
#: Five named kinds plus an honest residual.
RANGE_REGISTER = "REGISTER_RANGE"
RANGE_MEMORY = "MEMORY_RANGE"
RANGE_DMA = "DMA_RANGE"
RANGE_APB = "APB_RANGE"
RANGE_AXI = "AXI_RANGE"
RANGE_UNCLASSIFIED = "UNCLASSIFIED_RANGE"

SYS28_RANGE_KINDS: tuple = (
    RANGE_REGISTER, RANGE_MEMORY, RANGE_DMA, RANGE_APB, RANGE_AXI, RANGE_UNCLASSIFIED,
)

#: Bus-name evidence: the address-map entry's own `bus` field, a real input
#: contract field (see env_manifest.schema.json dut_facts.address_map).
_BUS_TO_RANGE_KIND: Dict[str, str] = {
    "apb": RANGE_APB, "apb2": RANGE_APB, "apb3": RANGE_APB, "apb4": RANGE_APB,
    "axi": RANGE_AXI, "axi3": RANGE_AXI, "axi4": RANGE_AXI, "axi4_lite": RANGE_AXI,
    "axi4-lite": RANGE_AXI, "axi_lite": RANGE_AXI, "ahb": RANGE_AXI, "ahb_lite": RANGE_AXI,
}

#: Name-token fallback. The memory and DMA token sets are READ OUT of
#: `system_resource_inventory.RESOURCE_TYPE_TOKENS` rather than retyped, so
#: this module cannot drift into a second opinion about which names evidence a
#: memory -- SYS-10's duplicate detection and SYS-28's SHARED_MEMORY verdict
#: must mean the same thing by "memory".
def _sri_tokens(resource_type: str) -> Tuple[str, ...]:
    for rt, tokens in sri.RESOURCE_TYPE_TOKENS:
        if rt == resource_type:
            return tuple(tokens)
    return ()


MEMORY_NAME_TOKENS: tuple = _sri_tokens(sri.RT_MEMORY_MODEL) + ("mem", "dram", "sram", "buffer")
DMA_NAME_TOKENS: tuple = _sri_tokens(sri.RT_DMA_MODEL)
APB_NAME_TOKENS: tuple = _sri_tokens(sri.RT_APB_MASTER) + ("apb",)
AXI_NAME_TOKENS: tuple = _sri_tokens(sri.RT_AXI_MASTER) + _sri_tokens(sri.RT_AXI_SLAVE) + ("axi", "ahb")
REGISTER_NAME_TOKENS: tuple = _sri_tokens(sri.RT_REGISTER_ACCESS_AGENT) + ("reg", "csr", "cfg", "ctrl")

#: The `addr_width` handed to `amba_fabric_generator.compute_address_regions()`
#: by `_pairwise_overlap()`. It affects ONLY that function's full-coverage
#: check, which this module deliberately ignores (two regions from two
#: different subsystems have no obligation to span an address space), so any
#: width wider than the addresses under test gives the same overlap answer.
#: 64 is used because the input contract's `base_address` is an unbounded
#: hex string.
PROBE_ADDR_WIDTH = 64

#: Which `register_map_agreement` value makes a base address itself disputed.
#: See the module docstring's closing paragraph for why this outranks a
#: conflict verdict rather than being reported beside one.
REGISTER_MAP_DISAGREES = "DISAGREES"

#: The authority tier a `dut_facts.address_map` entry occupies. Tier 4,
#: `register_file`, qualifier "dut": the manifest's own description of this
#: layer is a machine-readable address description cross-checked against
#: `dut_facts.registers`, which is exactly what tier 4 covers. Both sides of a
#: cross-subsystem address conflict are the same tier, so `resolve_conflict()`
#: returns UNDECIDABLE_SAME_AUTHORITY -- the correct answer. The authority
#: order cannot say which of two equally-real address maps is wrong, and this
#: module never asks it to; it escalates instead.
ADDRESS_MAP_AUTHORITY_SOURCE = "register_map"
ADDRESS_MAP_AUTHORITY_QUALIFIER = "dut"


# ===========================================================================
# SYS-28 -- interrupt mapping vocabulary
# ===========================================================================

INTERRUPT_LINE_SHARED = "INTERRUPT_LINE_SHARED_ACROSS_SUBSYSTEMS"
INTERRUPT_LINE_LOCAL = "INTERRUPT_LINE_SUBSYSTEM_LOCAL"
INTERRUPT_LINE_UNKNOWN = "UNKNOWN"
SYS28_INTERRUPT_VERDICTS: tuple = (
    INTERRUPT_LINE_SHARED, INTERRUPT_LINE_LOCAL, INTERRUPT_LINE_UNKNOWN,
)


# ===========================================================================
# SYS-29 vocabulary
# ===========================================================================

SAME_CLOCK_DOMAIN = "SAME_CLOCK_DOMAIN"
INDEPENDENT_CLOCK_DOMAIN = "INDEPENDENT_CLOCK_DOMAIN"
CONFLICTING_CLOCK_SOURCE = "CONFLICTING_CLOCK_SOURCE"
CONFLICTING_CLOCK_FREQUENCY = "CONFLICTING_CLOCK_FREQUENCY"
CDC_BOUNDARY = "CDC_BOUNDARY"
SAME_RESET_DOMAIN = "SAME_RESET_DOMAIN"
INDEPENDENT_RESET_DOMAIN = "INDEPENDENT_RESET_DOMAIN"
CONFLICTING_RESET_POLARITY = "CONFLICTING_RESET_POLARITY"
CONFLICTING_RESET_SEQUENCING = "CONFLICTING_RESET_SEQUENCING"
CLOCK_RESET_UNKNOWN = "UNKNOWN"

#: SYS-29's sentence is "Compare clock source/frequency, reset source/polarity/
#: sequencing, CDC dependencies", so the vocabulary keeps source, frequency,
#: polarity and sequencing as SEPARATE verdicts. Folding them into one
#: CONFLICTING value would name the pair without naming what a human has to go
#: and fix, and those four fixes are not the same fix.
SYS29_VERDICTS: tuple = (
    SAME_CLOCK_DOMAIN, INDEPENDENT_CLOCK_DOMAIN, CONFLICTING_CLOCK_SOURCE,
    CONFLICTING_CLOCK_FREQUENCY, CDC_BOUNDARY, SAME_RESET_DOMAIN,
    INDEPENDENT_RESET_DOMAIN, CONFLICTING_RESET_POLARITY,
    CONFLICTING_RESET_SEQUENCING, CLOCK_RESET_UNKNOWN,
)

#: Clock-side precedence: an outright disagreement about ONE named clock
#: outranks any statement about two differently-named ones, and a CDC boundary
#: outranks plain independence because "these two are unrelated" and "these two
#: are unrelated AND a shared address region crosses between them" are
#: different findings with different consequences.
SYS29_CLOCK_PRECEDENCE: tuple = (
    CLOCK_RESET_UNKNOWN, CONFLICTING_CLOCK_FREQUENCY, CONFLICTING_CLOCK_SOURCE,
    SAME_CLOCK_DOMAIN, CDC_BOUNDARY, INDEPENDENT_CLOCK_DOMAIN,
)

SYS29_RESET_PRECEDENCE: tuple = (
    CLOCK_RESET_UNKNOWN, CONFLICTING_RESET_POLARITY, CONFLICTING_RESET_SEQUENCING,
    SAME_RESET_DOMAIN, INDEPENDENT_RESET_DOMAIN,
)

#: SYS-29's last sentence: "System Level may own global clock/reset behavior;
#: subsystem-local resources remain local." A proposal, never an action --
#: hence the pinned status below, which the schema also pins.
OWNERSHIP_SYSTEM_GLOBAL_CANDIDATE = "SYSTEM_GLOBAL_OWNERSHIP_CANDIDATE"
OWNERSHIP_SUBSYSTEM_LOCAL = "REMAINS_SUBSYSTEM_LOCAL"
SYS29_OWNERSHIP_PROPOSALS: tuple = (
    OWNERSHIP_SYSTEM_GLOBAL_CANDIDATE, OWNERSHIP_SUBSYSTEM_LOCAL,
)
OWNERSHIP_STATUS = "PLANNED_NOT_IMPLEMENTED"


# ===========================================================================
# SYS-30 vocabulary
# ===========================================================================

BLOCK_PARALLEL = "PARALLEL_BLOCK"
BLOCK_SEQUENTIAL = "SEQUENTIAL_BLOCK"
SYS30_BLOCK_KINDS: tuple = (BLOCK_PARALLEL, BLOCK_SEQUENTIAL)

#: Pinned on every scenario in every produced document. A scenario BODY is
#: real System command.txt content; writing one is SYS-40 and needs a separate
#: explicit human approval this workflow does not obtain. The schema pins this
#: to a const, so a document carrying a generated body could not validate.
SCENARIO_BODY_NOT_GENERATED = "NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL"

#: SYS-30's own rule: "Derive syntax from existing subsystem semantics rather
#: than forcing a new language." The ONLY construct a multi-subsystem scenario
#: needs that no single subsystem's command.txt already has is a way to say
#: "these run together" and "these run in order". Both are named here as
#: PROPOSED, never emitted, and the derivation record proves every other token
#: in the plan came out of a real subsystem contract.
PROPOSED_SCENARIO_KEYWORDS: tuple = ("PARALLEL_BLOCK_MARKER", "SEQUENTIAL_BLOCK_MARKER")
PROPOSED_KEYWORD_STATUS = "PROPOSED_NOT_IMPLEMENTED"

PHASE_BOUNDARY = (
    "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- SYS-28..SYS-30 address-map "
    "reconciliation, clock/reset comparison and scenario-model PLANNING only. No "
    "System-Level environment, System command.txt, scenario body, parallel block, "
    "System Virtual Sequencer, command routing/adapter, address decoder or "
    "clock/reset generator is produced; that is SYS-40 and requires a separate "
    "explicit human approval."
)


class SystemTopologyAnalysisError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Guards
# ===========================================================================

def assert_no_emitted_artifacts(document: Mapping[str, Any]) -> None:
    """Runtime check of this module's own boundary, run on every document
    `build_system_topology_analysis()` returns.

    Refuses a document that: reports any generated artifact; carries a
    scenario whose body status is anything but NOT_GENERATED; carries a
    clock/reset ownership row whose status is anything but
    PLANNED_NOT_IMPLEMENTED; or carries any key whose name suggests emitted
    text (`scenario_body`, `command_txt`, `generated_source`).
    """
    if document.get("artifacts_generated"):
        raise SystemTopologyAnalysisError("ARTIFACT_GENERATION_ATTEMPTED", {
            "artifacts": list(document.get("artifacts_generated") or []),
        })
    scenarios = (document.get("system_scenario_model") or {}).get("scenarios") or []
    for scenario in scenarios:
        if scenario.get("scenario_body_status") != SCENARIO_BODY_NOT_GENERATED:
            raise SystemTopologyAnalysisError("SCENARIO_BODY_GENERATED", {
                "scenario_id": scenario.get("scenario_id"),
                "status": scenario.get("scenario_body_status"),
            })
        for forbidden in ("scenario_body", "command_txt", "generated_source",
                          "emitted_text", "sequence_body"):
            if forbidden in scenario:
                raise SystemTopologyAnalysisError("SCENARIO_BODY_GENERATED", {
                    "scenario_id": scenario.get("scenario_id"), "key": forbidden,
                })
    for row in (document.get("clock_reset_comparison") or {}).get("ownership_proposals") or []:
        if row.get("status") != OWNERSHIP_STATUS:
            raise SystemTopologyAnalysisError("CLOCK_RESET_OWNERSHIP_IMPLEMENTED", {
                "name": row.get("name"), "status": row.get("status"),
            })


# ===========================================================================
# SYS-28 -- per-subsystem region extraction (reuses amba_fabric_generator)
# ===========================================================================

def classify_address_range_kind(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-28's "Determine register/memory/DMA/APB/AXI ranges" for ONE region.

    WHY CONTENT IS TESTED BEFORE TRANSPORT, which is the one ordering decision
    here worth stating: SYS-28's own list mixes two orthogonal axes. MEMORY and
    DMA say what is AT the range; APB and AXI say how you REACH it. A DDR
    window hanging off an AXI port is both, and a classifier that trusted the
    declared bus first would type every AXI-attached memory as an AXI range --
    which would make `SHARED_MEMORY` unreachable for exactly the case it
    exists for, a DDR window two subsystems both use. So the memory/DMA
    content tokens are tested first, the DECLARED bus (real input-contract
    evidence, stronger than any name token) next, and register name tokens
    last as the weakest hint.

    The matched token AND the field it matched in are recorded as the basis,
    exactly as `subsystem_architecture_analysis.classify_component_roles()` and
    `system_resource_inventory.classify_resource_type()` already do. A row that
    matched nothing says so rather than defaulting into a kind.
    """
    haystack = " ".join(str(entry.get(f) or "") for f in ("name", "target", "description")).lower()
    for kind, tokens in ((RANGE_MEMORY, MEMORY_NAME_TOKENS), (RANGE_DMA, DMA_NAME_TOKENS)):
        for token in tokens:
            if token and token in haystack:
                return {"range_kind": kind, "basis": "CONTENT_NAME_TOKEN_MATCH",
                        "matched_token": token, "from_field": "name/target/description"}
    bus = str(entry.get("bus") or "").strip().lower()
    if bus:
        kind = _BUS_TO_RANGE_KIND.get(bus.replace("-", "_"))
        if kind:
            return {"range_kind": kind, "basis": f"DECLARED_BUS={bus}", "matched_token": bus,
                    "from_field": "bus"}
    for kind, tokens in ((RANGE_APB, APB_NAME_TOKENS), (RANGE_AXI, AXI_NAME_TOKENS),
                         (RANGE_REGISTER, REGISTER_NAME_TOKENS)):
        for token in tokens:
            if token and token in haystack:
                return {"range_kind": kind, "basis": "NAME_TOKEN_MATCH",
                        "matched_token": token, "from_field": "name/target/description"}
    return {"range_kind": RANGE_UNCLASSIFIED,
            "basis": "no memory/DMA content token, no declared bus and no name token matched",
            "matched_token": "", "from_field": ""}


def _region_from_entry(subsystem_id: str, entry: Mapping[str, Any]) -> Dict[str, Any]:
    """One address-map entry -> one interval, parsed with
    `amba_fabric_generator.parse_addr()` (the SAME parser
    `fabric_topology_completeness_gate.py` uses, so an address string this
    repo accepts anywhere is accepted here identically).

    `parsed` is False, with the reason kept, when the entry cannot be read.
    An unreadable region is carried as a row rather than dropped: silently
    omitting it would make a subsystem look like it declares nothing there.
    """
    kind = classify_address_range_kind(entry)
    region = {
        "subsystem_id": subsystem_id,
        "name": str(entry.get("name") or ""),
        "target": str(entry.get("target") or ""),
        "bus": str(entry.get("bus") or ""),
        "range_kind": kind["range_kind"],
        "range_kind_basis": kind["basis"],
        "register_map_agreement": str(entry.get("register_map_agreement") or "NOT_AVAILABLE"),
        "evidence": str(entry.get("evidence") or ""),
        "parsed": False,
        "parse_reason": "",
        "start": None,
        "end": None,
        "base_address": str(entry.get("base_address") or ""),
        "size_bytes": entry.get("size_bytes"),
    }
    try:
        start = afg.parse_addr(entry["base_address"])
        size = afg.parse_addr(entry["size_bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        region["parse_reason"] = f"{type(exc).__name__}: {exc}"
        return region
    if size <= 0:
        region["parse_reason"] = f"size_bytes must be positive, got {size}"
        return region
    region.update({"parsed": True, "start": start, "end": start + size})
    return region


def _self_consistency(regions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Does ONE subsystem's own address map overlap itself?

    The verdict is `compute_address_regions()`'s, not this module's: the same
    call, the same exclusive-end adjacency semantics, the same error reasons.
    ADDRESS_MAP_GAP and ADDRESS_MAP_NOT_FULL_COVERAGE are recorded but are NOT
    findings here -- a subsystem's address map is a view of part of an SoC and
    has no obligation to span [0, 2**64). Only ADDRESS_MAP_OVERLAP is a real
    intra-subsystem defect at this level.
    """
    usable = [r for r in regions if r["parsed"]]
    if not usable:
        return {"verdict": "NOT_EVALUATED", "reason": "no parseable region in this subsystem",
                "self_overlap": False, "detail": {}}
    slaves = [{"id": f"{r['subsystem_id']}::{r['name']}", "base_addr": r["start"],
               "size": r["end"] - r["start"]} for r in usable]
    try:
        afg.compute_address_regions(slaves, [], PROBE_ADDR_WIDTH)
        return {"verdict": "NO_SELF_OVERLAP", "reason": "regions are disjoint and adjacent",
                "self_overlap": False, "detail": {}}
    except afg.AddressMapError as exc:
        if exc.reason == "ADDRESS_MAP_OVERLAP":
            return {"verdict": exc.reason,
                    "reason": "this subsystem's own address map overlaps itself; "
                              "cross-subsystem verdicts built on it are reported but "
                              "the intra-subsystem defect is the first thing to fix",
                    "self_overlap": True, "detail": dict(exc.detail)}
        return {"verdict": "NO_SELF_OVERLAP", "reason":
                f"compute_address_regions() reported {exc.reason}, which is not an "
                "intra-subsystem defect for a partial SoC view", "self_overlap": False,
                "detail": {}}


def subsystem_address_regions(analysis: Mapping[str, Any]) -> Dict[str, Any]:
    """Every selected subsystem's own address regions, from the SYS-6 analysis
    each subsystem already produced (`fields.address_map`, itself sourced from
    that subsystem's `env.manifest.json dut_facts.address_map`). Nothing is
    re-read off disk here and no second address source is consulted.
    """
    per_subsystem: Dict[str, Any] = {}
    for result in analysis.get("per_subsystem") or []:
        sid = str(result.get("subsystem_id") or "")
        block = (result.get("fields") or {}).get("address_map") or {}
        status = block.get("status")
        regions = [_region_from_entry(sid, e) for e in (block.get("entries") or [])]
        per_subsystem[sid] = {
            "subsystem_id": sid,
            "evidence_status": status or saa.NOT_AVAILABLE,
            "evidence_source": str(block.get("source") or ""),
            "evidence_reason": str(block.get("reason") or ""),
            "regions": regions,
            "region_count": len(regions),
            "unparseable_count": sum(1 for r in regions if not r["parsed"]),
            "by_range_kind": {k: sum(1 for r in regions if r["range_kind"] == k)
                              for k in SYS28_RANGE_KINDS},
            "self_consistency": _self_consistency(regions),
            "declared_disagreement_count": int(block.get("disagreement_count") or 0),
        }
    return per_subsystem


def _pairwise_overlap(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Any]:
    """Do two regions intersect? Decided by CALLING
    `amba_fabric_generator.compute_address_regions()` on the two-region set,
    never by a second interval comparison written here.

    That function sorts by start and, for the single adjacent pair a
    two-element list produces, raises ADDRESS_MAP_OVERLAP when
    `cur.start < prev.end` (its exclusive-end convention, matched deliberately
    to `fabric_topology_completeness_gate.py`), ADDRESS_MAP_GAP when they are
    separated, and otherwise falls through to its full-coverage check -- whose
    ADDRESS_MAP_NOT_FULL_COVERAGE we ignore, because two regions out of two
    different subsystems have no obligation to span an address space. So the
    single question "do these intersect" is answered by which of its own
    errors it raises, and this repo keeps exactly one definition of overlap.
    """
    slaves = [
        {"id": f"A::{a['name']}", "base_addr": a["start"], "size": a["end"] - a["start"]},
        {"id": f"B::{b['name']}", "base_addr": b["start"], "size": b["end"] - b["start"]},
    ]
    try:
        afg.compute_address_regions(slaves, [], PROBE_ADDR_WIDTH)
    except afg.AddressMapError as exc:
        if exc.reason == "ADDRESS_MAP_OVERLAP":
            return {"overlaps": True, "probe_reason": exc.reason,
                    "probe_detail": dict(exc.detail),
                    "intersection_start": max(a["start"], b["start"]),
                    "intersection_end": min(a["end"], b["end"])}
        return {"overlaps": False, "probe_reason": exc.reason, "probe_detail": dict(exc.detail),
                "intersection_start": None, "intersection_end": None}
    return {"overlaps": False, "probe_reason": "DISJOINT_AND_ADJACENT", "probe_detail": {},
            "intersection_start": None, "intersection_end": None}


def _is_memory_region(region: Mapping[str, Any]) -> bool:
    return region["range_kind"] in (RANGE_MEMORY, RANGE_DMA)


def _normalized_name(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _interrupt_line_name(condition: str) -> str:
    """The signal name inside a `reference_pattern_audit.classify_wait()`
    condition. That field carries the whole expression as written
    (`top.dut.u_core.irq_done_evt`), and the thing an RTL port table can be
    compared against is its LAST hierarchy segment, not the full path -- two
    subsystems' testbenches reach the same interrupt through different
    hierarchies, so comparing full paths would report every shared line as
    two distinct ones."""
    text = str(condition or "").strip()
    for cut in ("==", "!=", "<=", ">=", "&&", "||", "(", ")", " "):
        text = text.replace(cut, " ")
    token = text.split()[0] if text.split() else ""
    return token.split(".")[-1].strip("~! ")


def _overlap_signals(a: Mapping[str, Any], b: Mapping[str, Any],
                     overlap: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every SYS-28 signal this region pair matches, each with the class it
    argues for and the basis it argues from. `classify_address_overlap()`
    picks one by `SYS28_PRECEDENCE` and keeps the rest in `also_matched` --
    a pair that is both a shared memory window AND sits on a base one
    subsystem's own register map disputes has two things wrong with it, and a
    single-valued column that dropped the second would be a worse report than
    one that never noticed it.
    """
    signals: List[Dict[str, Any]] = []
    disputed = [r for r in (a, b)
                if r["register_map_agreement"] == REGISTER_MAP_DISAGREES]
    if disputed:
        signals.append({
            "verdict": ADDRESS_UNKNOWN,
            "basis": ("base address disputed within " +
                      ", ".join(f"{r['subsystem_id']}::{r['name']}" for r in disputed) +
                      " -- its own dut_facts.address_map and dut_facts.registers "
                      "report DISAGREES, so an overlap computed on this base is a "
                      "finding about that subsystem's two artifacts, not about this pair"),
            "from_field": "register_map_agreement",
        })
    if _is_memory_region(a) and _is_memory_region(b):
        signals.append({
            "verdict": SHARED_MEMORY,
            "basis": (f"both regions are memory/DMA ranges "
                      f"({a['range_kind']} / {b['range_kind']}) and intersect: a window "
                      "two subsystems both reach is shared memory, not a conflict"),
            "from_field": "range_kind",
        })
    identical = a["start"] == b["start"] and a["end"] == b["end"]
    same_name = _normalized_name(a["name"]) == _normalized_name(b["name"]) and a["name"]
    if identical and same_name:
        signals.append({
            "verdict": ADDRESS_OVERLAP_VALID,
            "basis": (f"both subsystems declare the identical region {a['name']} at "
                      f"{hex(a['start'])}..{hex(a['end'])}: one block seen twice, not two "
                      "blocks colliding"),
            "from_field": "name+base_address+size_bytes",
        })
    if not signals:
        signals.append({
            "verdict": ADDRESS_OVERLAP_CONFLICT,
            "basis": (f"{a['subsystem_id']}::{a['name']} "
                      f"[{hex(a['start'])},{hex(a['end'])}) and "
                      f"{b['subsystem_id']}::{b['name']} "
                      f"[{hex(b['start'])},{hex(b['end'])}) intersect at "
                      f"[{hex(overlap['intersection_start'])},"
                      f"{hex(overlap['intersection_end'])}) with no shared-memory, "
                      "identical-region or disputed-base evidence explaining it"),
            "from_field": "base_address+size_bytes",
        })
    return signals


def classify_address_overlap(a: Mapping[str, Any], b: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """One cross-subsystem region pair -> one SYS-28 row, or None when the
    two do not intersect at all (a disjoint pair is not something SYS-28's
    four-value vocabulary has anything to say about; the summary counts them).
    """
    pair_id = "SYSADDR-" + hashlib.sha256("|".join(sorted((
        f"{a['subsystem_id']}::{a['name']}::{a['base_address']}",
        f"{b['subsystem_id']}::{b['name']}::{b['base_address']}",
    ))).encode("utf-8")).hexdigest()[:10].upper()

    if not a["parsed"] or not b["parsed"]:
        unreadable = [r for r in (a, b) if not r["parsed"]]
        return {
            "pair_id": pair_id,
            "subsystem_a": a["subsystem_id"], "region_a": a["name"],
            "subsystem_b": b["subsystem_id"], "region_b": b["name"],
            "range_kind_a": a["range_kind"], "range_kind_b": b["range_kind"],
            "verdict": ADDRESS_UNKNOWN,
            "basis": ("region(s) " +
                      ", ".join(f"{r['subsystem_id']}::{r['name']} ({r['parse_reason']})"
                                for r in unreadable) +
                      " could not be parsed as an address range, so no overlap verdict "
                      "is derivable for this pair"),
            "from_field": "base_address/size_bytes",
            "also_matched": [],
            "signals": [],
            "intersection_start": "", "intersection_end": "",
            "probe_reason": "NOT_PROBED_UNPARSEABLE_REGION",
            "escalation_required": False,
            "evidence": sorted({e for e in (a["evidence"], b["evidence"]) if e}),
        }

    overlap = _pairwise_overlap(a, b)
    if not overlap["overlaps"]:
        return None

    signals = _overlap_signals(a, b, overlap)
    matched = {s["verdict"] for s in signals}
    verdict = next((v for v in SYS28_PRECEDENCE if v in matched), ADDRESS_UNKNOWN)
    chosen = next(s for s in signals if s["verdict"] == verdict)
    return {
        "pair_id": pair_id,
        "subsystem_a": a["subsystem_id"], "region_a": a["name"],
        "subsystem_b": b["subsystem_id"], "region_b": b["name"],
        "range_kind_a": a["range_kind"], "range_kind_b": b["range_kind"],
        "verdict": verdict,
        "basis": chosen["basis"],
        "from_field": chosen["from_field"],
        "also_matched": sorted(matched - {verdict}),
        "signals": signals,
        "intersection_start": hex(overlap["intersection_start"]),
        "intersection_end": hex(overlap["intersection_end"]),
        "probe_reason": overlap["probe_reason"],
        # A real cross-subsystem conflict, and a pair whose base one side's own
        # artifacts dispute, are BOTH questions no automatic rule may close.
        "escalation_required": verdict in (ADDRESS_OVERLAP_CONFLICT, ADDRESS_UNKNOWN),
        "evidence": sorted({e for e in (a["evidence"], b["evidence"]) if e}),
    }


def reconcile_address_maps(analysis: Mapping[str, Any], *,
                           question_store: Any = None, now=None) -> Dict[str, Any]:
    """SYS-28 across every CROSS-SUBSYSTEM region pair in the selection.

    Pairs from the SAME subsystem are deliberately not classified here: a
    subsystem's map overlapping itself is an intra-subsystem defect, and it is
    already reported, with `compute_address_regions()`'s own verdict, in each
    subsystem's `self_consistency` block. Mixing the two would present a
    subsystem's own bug as a cross-subsystem finding.

    `question_store` (a `question_queue.QuestionQueueStore` or a project root):
    when supplied, every escalation-required row is filed through
    `source_authority.escalate_conflict()` -- the same channel
    `address_map_verifier.escalate_doc_disagreements()` and
    `system_command_plan.escalate_command_collisions()` already use. This
    function's return value is byte-identical with or without it.
    """
    per_subsystem = subsystem_address_regions(analysis)
    subsystem_ids = sorted(per_subsystem)

    rows: List[Dict[str, Any]] = []
    disjoint_pairs = 0
    for i, sid_a in enumerate(subsystem_ids):
        for sid_b in subsystem_ids[i + 1:]:
            for region_a in per_subsystem[sid_a]["regions"]:
                for region_b in per_subsystem[sid_b]["regions"]:
                    row = classify_address_overlap(region_a, region_b)
                    if row is None:
                        disjoint_pairs += 1
                        continue
                    rows.append(row)

    rows.sort(key=lambda r: (r["subsystem_a"], r["region_a"], r["subsystem_b"], r["region_b"]))
    by_verdict = {v: sum(1 for r in rows if r["verdict"] == v) for v in SYS28_OVERLAP_CLASSES}

    escalations: List[dict] = []
    if question_store is not None:
        escalations = escalate_address_conflicts(question_store, rows, now=now)

    return {
        "schema_version": SCHEMA_VERSION,
        "classes": list(SYS28_OVERLAP_CLASSES),
        "precedence": list(SYS28_PRECEDENCE),
        "range_kinds": list(SYS28_RANGE_KINDS),
        "per_subsystem": per_subsystem,
        "overlaps": rows,
        "summary": {
            "subsystem_count": len(subsystem_ids),
            "region_count": sum(v["region_count"] for v in per_subsystem.values()),
            "cross_subsystem_pairs_examined": sum(
                len(per_subsystem[a]["regions"]) * len(per_subsystem[b]["regions"])
                for i, a in enumerate(subsystem_ids) for b in subsystem_ids[i + 1:]),
            "overlapping_pairs": len(rows),
            "disjoint_pairs": disjoint_pairs,
            "by_verdict": by_verdict,
            "conflicts": by_verdict[ADDRESS_OVERLAP_CONFLICT],
            "subsystems_with_self_overlap": sorted(
                sid for sid, v in per_subsystem.items()
                if v["self_consistency"]["self_overlap"]),
            "escalations_filed": len(escalations),
            "regions_relocated": 0,
            "address_maps_modified": 0,
        },
        "escalations": [{"question_id": r.get("id") or r.get("question_id"),
                         "subject": r.get("question") or r.get("subject")}
                        for r in escalations],
    }


def escalate_address_conflicts(store, reconciliation_rows: Sequence[Mapping[str, Any]],
                               *, now=None) -> List[dict]:
    """File every escalation-required SYS-28 row into the REAL question queue
    through `source_authority.escalate_conflict()`.

    Both sides are the same authority tier (see
    ADDRESS_MAP_AUTHORITY_SOURCE's comment), so `resolve_conflict()` returns
    UNDECIDABLE_SAME_AUTHORITY -- the honest verdict. The 9-level order cannot
    say which of two equally-real address maps is wrong, and pretending it
    could is exactly the overreach `source_authority` exists to prevent. So
    the question goes to a human, with BOTH sides' evidence paths attached.

    `domain="dut"`: which of two DUT address maps is right is a designer
    question, the same routing `address_map_verifier.escalate_doc_
    disagreements()` uses for the same kind of disagreement.
    """
    from . import source_authority as sa

    records: List[dict] = []
    for row in reconciliation_rows or []:
        if not row.get("escalation_required"):
            continue
        claims = []
        for side in ("a", "b"):
            sid = row[f"subsystem_{side}"]
            region = row[f"region_{side}"]
            claims.append(sa.SourceClaim(
                source=ADDRESS_MAP_AUTHORITY_SOURCE,
                qualifier=ADDRESS_MAP_AUTHORITY_QUALIFIER,
                claim=f"{sid} maps {region} over this range",
                # Each side cites its own evidence, never a merged list: that
                # is what makes the question answerable by whoever receives it.
                evidence_path=(next((e for e in (row.get("evidence") or [])
                                     if sid in e), "")
                               or f"{sid} env.manifest.json dut_facts.address_map "
                                  f"entry {region}"),
            ))
        conflict = sa.resolve_conflict(claims)
        record = sa.escalate_conflict(
            store, conflict, domain="dut",
            subject=(f"Cross-subsystem address relationship {row['pair_id']} "
                     f"({row['verdict']}): {row['subsystem_a']}::{row['region_a']} vs "
                     f"{row['subsystem_b']}::{row['region_b']}"),
            context_path=row["pair_id"],
            extra_context={"affects_spec_intent": True,
                           "system_level_address_verdict": row["verdict"]},
            now=now)
        if record is not None:
            records.append(record)
    return records


# ===========================================================================
# SYS-28 -- interrupt mapping
# ===========================================================================

def reconcile_interrupt_maps(analysis: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-28's "interrupt mapping" half, over the SYS-6 `interrupts` field
    each subsystem already derived (RTL port hits AND command.txt interrupt
    waits -- both axes, reported separately, exactly as that field carries
    them).

    One row per distinct interrupt line name. A line named by two or more
    selected subsystems is SHARED -- which is a fact to surface, not a
    conflict to declare: a shared interrupt line is a normal SoC arrangement
    and only becomes a problem once two subsystems both drive it, which is
    SYS-10/SYS-15's question and is answered there, not re-answered here.
    """
    by_line: Dict[str, Dict[str, Any]] = {}
    unavailable: List[str] = []
    for result in analysis.get("per_subsystem") or []:
        sid = str(result.get("subsystem_id") or "")
        block = (result.get("fields") or {}).get("interrupts") or {}
        if block.get("status") == saa.NOT_AVAILABLE:
            unavailable.append(sid)
        for port in block.get("rtl_ports") or []:
            key = _normalized_name(port.get("port"))
            entry = by_line.setdefault(key, {"line": str(port.get("port") or ""),
                                             "subsystems": {}, "axes": set()})
            entry["subsystems"].setdefault(sid, []).append(
                f"RTL {port.get('module')}.{port.get('port')} ({port.get('evidence')})")
            entry["axes"].add("RTL_PORT")
        for wait in block.get("command_txt_waits") or []:
            signal = _interrupt_line_name(wait.get("condition") or "")
            key = _normalized_name(signal)
            if not key:
                continue
            entry = by_line.setdefault(key, {"line": str(signal), "subsystems": {},
                                             "axes": set()})
            entry["subsystems"].setdefault(sid, []).append(
                f"command.txt wait {wait.get('evidence') or signal}")
            entry["axes"].add("COMMAND_TXT_WAIT")

    rows: List[Dict[str, Any]] = []
    for key in sorted(by_line):
        entry = by_line[key]
        subsystems = sorted(entry["subsystems"])
        if len(subsystems) >= 2:
            verdict = INTERRUPT_LINE_SHARED
            reason = (f"{len(subsystems)} selected subsystems' own evidence names this "
                      "interrupt line; whether both DRIVE it is a SYS-10/SYS-15 "
                      "ownership question, decided there and not re-decided here")
        elif subsystems:
            verdict = INTERRUPT_LINE_LOCAL
            reason = "only one selected subsystem's evidence names this interrupt line"
        else:  # pragma: no cover - a line with no subsystem cannot be built above
            verdict, reason = INTERRUPT_LINE_UNKNOWN, "no subsystem evidence"
        rows.append({
            "line": entry["line"],
            "normalized_line": key,
            "verdict": verdict,
            "reason": reason,
            "subsystems": subsystems,
            "evidence_axes": sorted(entry["axes"]),
            "evidence": sorted({e for evs in entry["subsystems"].values() for e in evs})[:8],
        })

    by_verdict = {v: sum(1 for r in rows if r["verdict"] == v)
                  for v in SYS28_INTERRUPT_VERDICTS}
    return {
        "schema_version": SCHEMA_VERSION,
        "verdicts": list(SYS28_INTERRUPT_VERDICTS),
        "lines": rows,
        "summary": {
            "line_count": len(rows),
            "by_verdict": by_verdict,
            "shared_lines": [r["line"] for r in rows if r["verdict"] == INTERRUPT_LINE_SHARED],
            "subsystems_without_interrupt_evidence": sorted(unavailable),
            "interrupt_maps_modified": 0,
        },
    }


# ===========================================================================
# SYS-29 -- CLOCK / RESET INTEGRATION
# ===========================================================================

def _clock_reset_facts(analysis: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Each selected subsystem's own clock/reset facts, straight out of its
    SYS-6 `clock_reset` field (itself `env.manifest.json dut_facts.
    clock_reset`, whose input contract REQUIRES a reset's `active_level` --
    which is why a polarity comparison is possible at all rather than being
    guessed from a name)."""
    facts: Dict[str, Dict[str, Any]] = {}
    for result in analysis.get("per_subsystem") or []:
        sid = str(result.get("subsystem_id") or "")
        block = (result.get("fields") or {}).get("clock_reset") or {}
        facts[sid] = {
            "subsystem_id": sid,
            "evidence_status": block.get("status") or saa.NOT_AVAILABLE,
            "evidence_source": str(block.get("source") or ""),
            "evidence_reason": str(block.get("reason") or ""),
            "clocks": list(block.get("clocks") or []),
            "resets": list(block.get("resets") or []),
        }
    return facts


def _shared_address_regions(address_reconciliation: Optional[Mapping[str, Any]],
                            sid_a: str, sid_b: str) -> List[str]:
    """Which SYS-28 rows put these two subsystems on the same address range.
    Read from the SYS-28 output, never recomputed -- a CDC boundary is
    "a shared path crosses two clock domains", and the shared path is exactly
    what SYS-28 already found."""
    shared = []
    for row in (address_reconciliation or {}).get("overlaps") or []:
        if row["verdict"] not in (SHARED_MEMORY, ADDRESS_OVERLAP_VALID,
                                  ADDRESS_OVERLAP_CONFLICT):
            continue
        if {row["subsystem_a"], row["subsystem_b"]} == {sid_a, sid_b}:
            shared.append(row["pair_id"])
    return sorted(shared)


def _clock_pair_signals(sid_a: str, clock_a: Mapping[str, Any],
                        sid_b: str, clock_b: Mapping[str, Any],
                        shared_regions: Sequence[str]) -> List[Dict[str, Any]]:
    same_name = _normalized_name(clock_a.get("name")) == _normalized_name(clock_b.get("name"))
    signals: List[Dict[str, Any]] = []
    if same_name:
        freq_a, freq_b = clock_a.get("frequency_mhz"), clock_b.get("frequency_mhz")
        if freq_a is not None and freq_b is not None and float(freq_a) != float(freq_b):
            signals.append({
                "verdict": CONFLICTING_CLOCK_FREQUENCY,
                "basis": (f"one clock name ({clock_a.get('name')}) carries two "
                          f"frequencies: {sid_a} states {freq_a} MHz, {sid_b} states "
                          f"{freq_b} MHz"),
                "from_field": "frequency_mhz",
            })
        src_a, src_b = clock_a.get("source"), clock_b.get("source")
        if src_a and src_b and _normalized_name(src_a) != _normalized_name(src_b):
            signals.append({
                "verdict": CONFLICTING_CLOCK_SOURCE,
                "basis": (f"one clock name ({clock_a.get('name')}) is driven from two "
                          f"sources: {sid_a} states {src_a!r}, {sid_b} states {src_b!r}"),
                "from_field": "source",
            })
        signals.append({
            "verdict": SAME_CLOCK_DOMAIN,
            "basis": (f"both subsystems name the clock {clock_a.get('name')} and their "
                      "stated frequency and source do not disagree"),
            "from_field": "name",
        })
    else:
        if shared_regions:
            signals.append({
                "verdict": CDC_BOUNDARY,
                "basis": (f"{sid_a} clocks {clock_a.get('name')} while {sid_b} clocks "
                          f"{clock_b.get('name')}, and SYS-28 found them sharing "
                          f"{len(shared_regions)} address range(s) "
                          f"({', '.join(shared_regions[:3])}): a path crosses between "
                          "two domains"),
                "from_field": "name + SYS-28 shared address range",
            })
        signals.append({
            "verdict": INDEPENDENT_CLOCK_DOMAIN,
            "basis": (f"{sid_a} clocks {clock_a.get('name')} and {sid_b} clocks "
                      f"{clock_b.get('name')}; no evidence links them"),
            "from_field": "name",
        })
    return signals


def _reset_pair_signals(sid_a: str, reset_a: Mapping[str, Any],
                        sid_b: str, reset_b: Mapping[str, Any]) -> List[Dict[str, Any]]:
    same_name = _normalized_name(reset_a.get("name")) == _normalized_name(reset_b.get("name"))
    signals: List[Dict[str, Any]] = []
    if not same_name:
        return [{
            "verdict": INDEPENDENT_RESET_DOMAIN,
            "basis": (f"{sid_a} resets with {reset_a.get('name')} and {sid_b} with "
                      f"{reset_b.get('name')}; no evidence links them"),
            "from_field": "name",
        }]
    lvl_a, lvl_b = reset_a.get("active_level"), reset_b.get("active_level")
    if lvl_a and lvl_b and lvl_a != lvl_b:
        signals.append({
            "verdict": CONFLICTING_RESET_POLARITY,
            "basis": (f"one reset name ({reset_a.get('name')}) carries two polarities: "
                      f"{sid_a} states active-{lvl_a}, {sid_b} states active-{lvl_b}. An "
                      "assumed reset polarity holds a DUT in reset for a whole run while "
                      "every machine gate still reports PASS"),
            "from_field": "active_level",
        })
    sync_a, sync_b = reset_a.get("synchronous"), reset_b.get("synchronous")
    clk_a, clk_b = reset_a.get("clock"), reset_b.get("clock")
    if sync_a is not None and sync_b is not None and bool(sync_a) != bool(sync_b):
        signals.append({
            "verdict": CONFLICTING_RESET_SEQUENCING,
            "basis": (f"one reset name ({reset_a.get('name')}) is stated synchronous by "
                      f"one side and asynchronous by the other ({sid_a}={sync_a}, "
                      f"{sid_b}={sync_b})"),
            "from_field": "synchronous",
        })
    if clk_a and clk_b and _normalized_name(clk_a) != _normalized_name(clk_b):
        signals.append({
            "verdict": CONFLICTING_RESET_SEQUENCING,
            "basis": (f"one reset name ({reset_a.get('name')}) is sequenced against two "
                      f"different clocks: {sid_a} states {clk_a}, {sid_b} states {clk_b}"),
            "from_field": "clock",
        })
    signals.append({
        "verdict": SAME_RESET_DOMAIN,
        "basis": (f"both subsystems name the reset {reset_a.get('name')} and their "
                  "stated polarity, synchronicity and sequencing clock do not disagree"),
        "from_field": "name",
    })
    return signals


def _duplicate_clock_reset_agents(registry: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """SYS-29's "Detect duplicate/conflicting clock/reset agents", READ off the
    SYS-15 registry rather than re-derived.

    SYS-9..SYS-14 already inventoried every resource, classified every
    cross-subsystem relationship and decided every reuse; a registry entry of
    type CLOCK_RESET_AGENT with two or more consumer subsystems IS a duplicate
    clock/reset agent, and its `conflict_status` IS whether that duplicate
    conflicts. Re-running that classification here would be a second answer to
    a question already answered, and the two would eventually disagree.
    """
    rows: List[Dict[str, Any]] = []
    for entry in (registry or {}).get("entries") or []:
        if entry.get("resource_type") != sri.RT_CLOCK_RESET_AGENT:
            continue
        consumers = list(entry.get("consumer_subsystems") or [])
        rows.append({
            "registry_entry_id": entry.get("resource_id"),
            "consumer_subsystems": consumers,
            "duplicate": len(consumers) >= 2,
            "conflict_status": entry.get("conflict_status") or "",
            "reuse_decision": entry.get("reuse_decision") or "",
            "active_passive": entry.get("active_passive") or "",
            "system_owner": entry.get("owner") or "",
            "source": "SYS-15 system_resource_registry entry (not re-derived here)",
            "evidence": list(entry.get("evidence") or [])[:8],
        })
    rows.sort(key=lambda r: str(r["registry_entry_id"]))
    return rows


def _ownership_proposals(facts: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """SYS-29's last sentence, as a PROPOSAL table. A clock or reset named by
    two or more selected subsystems is a candidate for System-level ownership;
    one named by exactly one stays subsystem-local. Nothing is moved, merged
    or renamed -- `status` is pinned to PLANNED_NOT_IMPLEMENTED and both the
    schema and `assert_no_emitted_artifacts()` hold it there."""
    by_name: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for sid, block in sorted(facts.items()):
        for kind, items in (("CLOCK", block["clocks"]), ("RESET", block["resets"])):
            for item in items:
                key = (kind, _normalized_name(item.get("name")))
                entry = by_name.setdefault(key, {"kind": kind, "name": str(item.get("name") or ""),
                                                 "subsystems": set()})
                entry["subsystems"].add(sid)
    rows = []
    for key in sorted(by_name):
        entry = by_name[key]
        subsystems = sorted(entry["subsystems"])
        shared = len(subsystems) >= 2
        rows.append({
            "kind": entry["kind"],
            "name": entry["name"],
            "subsystems": subsystems,
            "proposal": (OWNERSHIP_SYSTEM_GLOBAL_CANDIDATE if shared
                         else OWNERSHIP_SUBSYSTEM_LOCAL),
            "reason": (f"named by {len(subsystems)} selected subsystems, so System level "
                       "MAY own its global behaviour -- a proposal for a human, not a move"
                       if shared else
                       "named by exactly one selected subsystem, so it remains "
                       "subsystem-local per SYS-29's own rule"),
            "status": OWNERSHIP_STATUS,
        })
    return rows


def compare_clock_reset_domains(analysis: Mapping[str, Any], *,
                                address_reconciliation: Optional[Mapping[str, Any]] = None,
                                registry: Optional[Mapping[str, Any]] = None,
                                ) -> Dict[str, Any]:
    """SYS-29 across every CROSS-SUBSYSTEM clock pair and reset pair.

    This is the real computation that SHOULD back the self-attested
    `clock_reset_compatibility` string both
    `tools/verification_flow/system_level_composition_gate.py` and
    `subsystem_environment_registration_gate.py` gate on today --
    `clock_reset_compatibility_input()` below turns this document into that
    field's value, so the gate can be fed a computed verdict instead of a
    typed-in one. It does not change either gate: wiring a gate to a new
    input is a behaviour change, and this step is analysis only.
    """
    facts = _clock_reset_facts(analysis)
    subsystem_ids = sorted(facts)

    clock_rows: List[Dict[str, Any]] = []
    reset_rows: List[Dict[str, Any]] = []
    for i, sid_a in enumerate(subsystem_ids):
        for sid_b in subsystem_ids[i + 1:]:
            block_a, block_b = facts[sid_a], facts[sid_b]
            shared_regions = _shared_address_regions(address_reconciliation, sid_a, sid_b)
            if (block_a["evidence_status"] != saa.DERIVED
                    or block_b["evidence_status"] != saa.DERIVED):
                missing = [s["subsystem_id"] for s in (block_a, block_b)
                           if s["evidence_status"] != saa.DERIVED]
                unknown_reason = (
                    f"clock/reset facts are {saa.NOT_AVAILABLE} for {missing}: "
                    "env.manifest.json dut_facts.clock_reset was not loaded, so no "
                    "comparison is derivable for this pair")
                clock_rows.append(_cr_row(sid_a, sid_b, "CLOCK", "", "",
                                          CLOCK_RESET_UNKNOWN, unknown_reason,
                                          "clock_reset.status", [], shared_regions))
                reset_rows.append(_cr_row(sid_a, sid_b, "RESET", "", "",
                                          CLOCK_RESET_UNKNOWN, unknown_reason,
                                          "clock_reset.status", [], shared_regions))
                continue
            for clock_a in block_a["clocks"]:
                for clock_b in block_b["clocks"]:
                    signals = _clock_pair_signals(sid_a, clock_a, sid_b, clock_b,
                                                  shared_regions)
                    clock_rows.append(_resolve_cr_row(
                        sid_a, sid_b, "CLOCK", str(clock_a.get("name") or ""),
                        str(clock_b.get("name") or ""), signals, SYS29_CLOCK_PRECEDENCE,
                        shared_regions,
                        [str(clock_a.get("evidence") or ""), str(clock_b.get("evidence") or "")]))
            for reset_a in block_a["resets"]:
                for reset_b in block_b["resets"]:
                    signals = _reset_pair_signals(sid_a, reset_a, sid_b, reset_b)
                    reset_rows.append(_resolve_cr_row(
                        sid_a, sid_b, "RESET", str(reset_a.get("name") or ""),
                        str(reset_b.get("name") or ""), signals, SYS29_RESET_PRECEDENCE,
                        shared_regions,
                        [str(reset_a.get("evidence") or ""), str(reset_b.get("evidence") or "")]))

    clock_rows.sort(key=lambda r: (r["subsystem_a"], r["subsystem_b"], r["name_a"], r["name_b"]))
    reset_rows.sort(key=lambda r: (r["subsystem_a"], r["subsystem_b"], r["name_a"], r["name_b"]))
    rows = clock_rows + reset_rows
    by_verdict = {v: sum(1 for r in rows if r["verdict"] == v) for v in SYS29_VERDICTS}
    conflicts = [r for r in rows if r["verdict"] in (
        CONFLICTING_CLOCK_FREQUENCY, CONFLICTING_CLOCK_SOURCE,
        CONFLICTING_RESET_POLARITY, CONFLICTING_RESET_SEQUENCING)]
    agents = _duplicate_clock_reset_agents(registry)

    return {
        "schema_version": SCHEMA_VERSION,
        "verdicts": list(SYS29_VERDICTS),
        "clock_precedence": list(SYS29_CLOCK_PRECEDENCE),
        "reset_precedence": list(SYS29_RESET_PRECEDENCE),
        "per_subsystem": facts,
        "clock_comparisons": clock_rows,
        "reset_comparisons": reset_rows,
        "clock_reset_agents": agents,
        "ownership_proposals": _ownership_proposals(facts),
        "summary": {
            "subsystem_count": len(subsystem_ids),
            "clock_pairs": len(clock_rows),
            "reset_pairs": len(reset_rows),
            "by_verdict": by_verdict,
            "conflicts": len(conflicts),
            "conflicting_pairs": sorted({f"{r['subsystem_a']}|{r['subsystem_b']}"
                                         for r in conflicts}),
            "cdc_boundaries": by_verdict[CDC_BOUNDARY],
            "duplicate_clock_reset_agents": sum(1 for a in agents if a["duplicate"]),
            "conflicting_clock_reset_agents": sum(
                1 for a in agents if a["conflict_status"] not in ("", srr.CONFLICT_NONE)),
            "system_global_ownership_candidates": sum(
                1 for r in _ownership_proposals(facts)
                if r["proposal"] == OWNERSHIP_SYSTEM_GLOBAL_CANDIDATE),
            "clocks_or_resets_modified": 0,
        },
    }


def _cr_row(sid_a: str, sid_b: str, kind: str, name_a: str, name_b: str,
            verdict: str, basis: str, from_field: str, also_matched: Sequence[str],
            shared_regions: Sequence[str], evidence: Sequence[str] = ()) -> Dict[str, Any]:
    pair_id = "SYSCR-" + hashlib.sha256(
        "|".join((kind, *sorted((f"{sid_a}::{name_a}", f"{sid_b}::{name_b}"))))
        .encode("utf-8")).hexdigest()[:10].upper()
    return {
        "pair_id": pair_id, "kind": kind,
        "subsystem_a": sid_a, "name_a": name_a,
        "subsystem_b": sid_b, "name_b": name_b,
        "verdict": verdict, "basis": basis, "from_field": from_field,
        "also_matched": list(also_matched),
        "shared_address_pairs": list(shared_regions),
        "evidence": sorted({e for e in evidence if e}),
    }


def _resolve_cr_row(sid_a: str, sid_b: str, kind: str, name_a: str, name_b: str,
                    signals: Sequence[Mapping[str, Any]], precedence: Sequence[str],
                    shared_regions: Sequence[str],
                    evidence: Sequence[str]) -> Dict[str, Any]:
    matched = {s["verdict"] for s in signals}
    verdict = next((v for v in precedence if v in matched), CLOCK_RESET_UNKNOWN)
    chosen = next((s for s in signals if s["verdict"] == verdict), None)
    row = _cr_row(sid_a, sid_b, kind, name_a, name_b, verdict,
                  chosen["basis"] if chosen else "no SYS-29 signal matched this pair",
                  chosen["from_field"] if chosen else "",
                  sorted(matched - {verdict}), shared_regions, evidence)
    row["signals"] = list(signals)
    return row


def clock_reset_compatibility_input(comparison: Mapping[str, Any]) -> Dict[str, Any]:
    """The COMPUTED value for the `clock_reset_compatibility` field that
    `tools/verification_flow/system_level_composition_gate.py` and
    `subsystem_environment_registration_gate.py` currently take on trust as a
    caller-supplied "PASS"/"FAIL" string.

    Returned as an input for a caller to pass to a gate, not written anywhere:
    changing what a hard gate reads is a behaviour change and SYS-28..30 is
    analysis. `computed_value` is FAIL when any real polarity/sequencing/
    frequency/source disagreement was found, PASS when the comparison ran and
    found none, and UNKNOWN when the underlying facts were NOT_AVAILABLE --
    the third being the state a two-valued string cannot express and which a
    caller must not silently report as PASS.
    """
    summary = comparison.get("summary") or {}
    by_verdict = summary.get("by_verdict") or {}
    if summary.get("conflicts"):
        value, reason = "FAIL", (
            f"{summary['conflicts']} real clock/reset disagreement(s) across "
            f"{summary.get('conflicting_pairs')}")
    elif by_verdict.get(CLOCK_RESET_UNKNOWN):
        value, reason = "UNKNOWN", (
            f"{by_verdict[CLOCK_RESET_UNKNOWN]} pair(s) could not be compared because a "
            "subsystem's own clock/reset facts were NOT_AVAILABLE")
    elif not (summary.get("clock_pairs") or summary.get("reset_pairs")):
        value, reason = "UNKNOWN", "no cross-subsystem clock or reset pair was comparable"
    else:
        value, reason = "PASS", (
            f"{summary.get('clock_pairs', 0)} clock pair(s) and "
            f"{summary.get('reset_pairs', 0)} reset pair(s) compared with no source, "
            "frequency, polarity or sequencing disagreement")
    return {
        "field": "clock_reset_compatibility",
        "computed_value": value,
        "reason": reason,
        "cdc_boundaries": summary.get("cdc_boundaries", 0),
        "gate_wired": False,
        "gate_wiring_note": (
            "computed for a caller to supply; system_level_composition_gate.py and "
            "subsystem_environment_registration_gate.py still read the caller-supplied "
            "field, and rewiring a hard gate is a behaviour change outside SYS-28..30's "
            "analysis-only scope"),
    }


# ===========================================================================
# SYS-30 -- SYSTEM-LEVEL SCENARIO MODEL
# ===========================================================================

def _pair_relationship_index(relationships: Mapping[str, Any]) -> Dict[Tuple[str, str], str]:
    index: Dict[Tuple[str, str], str] = {}
    for pair in (relationships or {}).get("pairs") or []:
        key = tuple(sorted((pair["command_a"], pair["command_b"])))
        index[key] = pair["relationship"]
    return index


def _block_plan(command_ids: Sequence[str],
                ir_by_id: Mapping[str, Mapping[str, Any]],
                pair_index: Mapping[Tuple[str, str], str]) -> List[Dict[str, Any]]:
    """Group a scenario's commands into PARALLEL/SEQUENTIAL blocks from the
    SYS-25 pair relationships ALREADY decided by
    `system_scheduling_plan.classify_parallelism_relationships()`.

    The rule is deliberately the most conservative one that still produces
    parallel blocks: a command joins the block being built only if its
    relationship to EVERY command already in it is PARALLEL_SAFE. Anything
    else -- a resource serialization, an ordering dependency, an interrupt
    handshake, a clock-domain crossing, or an UNKNOWN -- closes the block and
    starts a new one. UNKNOWN closing a block matters: a pair whose safety was
    not decidable must not be planned as parallel, because "we could not tell"
    and "we checked and it is safe" are different facts and only one of them
    licenses concurrency.

    Same-subsystem commands are never placed in one parallel block either: a
    command.txt is sequential by construction, so its own order is already
    stated and re-ordering it is not this plan's business.
    """
    blocks: List[Dict[str, Any]] = []
    current: List[str] = []

    def flush():
        if not current:
            return
        subsystems = sorted({ir_by_id[c]["source_subsystem"] for c in current})
        kind = BLOCK_PARALLEL if len(current) >= 2 else BLOCK_SEQUENTIAL
        blocks.append({
            "block_index": len(blocks),
            "block_kind": kind,
            "members": [{
                "system_command_id": c,
                "subsystem": ir_by_id[c]["source_subsystem"],
                "source_command": ir_by_id[c]["source_command"],
                "command_category": ir_by_id[c].get("command_category") or "",
            } for c in current],
            "participating_subsystems": subsystems,
            "basis": ("every pair in this block was classified PARALLEL_SAFE by SYS-25"
                      if kind == BLOCK_PARALLEL else
                      "a single command: nothing to run beside it in this block"),
        })
        current.clear()

    for command_id in command_ids:
        if not current:
            current.append(command_id)
            continue
        blocking = []
        for member in current:
            if ir_by_id[member]["source_subsystem"] == ir_by_id[command_id]["source_subsystem"]:
                blocking.append((member, "SAME_SUBSYSTEM_COMMAND_TXT_IS_SEQUENTIAL"))
                continue
            rel = pair_index.get(tuple(sorted((member, command_id))), ssp.REL_UNKNOWN)
            if rel != ssp.REL_PARALLEL_SAFE:
                blocking.append((member, rel))
        if blocking:
            reason = "; ".join(f"{m}:{r}" for m, r in blocking[:3])
            flush()
            blocks.append({
                "block_index": len(blocks),
                "block_kind": BLOCK_SEQUENTIAL,
                "members": [{
                    "system_command_id": command_id,
                    "subsystem": ir_by_id[command_id]["source_subsystem"],
                    "source_command": ir_by_id[command_id]["source_command"],
                    "command_category": ir_by_id[command_id].get("command_category") or "",
                }],
                "participating_subsystems": [ir_by_id[command_id]["source_subsystem"]],
                "basis": f"cannot join the preceding block: {reason}",
            })
        else:
            current.append(command_id)
    flush()
    return blocks


def _syntax_derivation(command_ids: Sequence[str],
                       ir_by_id: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """SYS-30's "Derive syntax from existing subsystem semantics rather than
    forcing a new language", as a checkable record rather than a claim.

    Every command in the plan is cited back to the subsystem contract it came
    from, so `derived_from_existing_subsystem_semantics` is a computed fact:
    it is True only when every planned command exists in the real SYS-21 IR.
    The two proposed block markers are listed explicitly as the ONLY constructs
    that are not already in some subsystem's own vocabulary, both
    PROPOSED_NOT_IMPLEMENTED.
    """
    categories = sorted({str(ir_by_id[c].get("command_category") or "") for c in command_ids} - {""})
    per_subsystem: Dict[str, List[str]] = {}
    for c in command_ids:
        per_subsystem.setdefault(ir_by_id[c]["source_subsystem"], []).append(
            ir_by_id[c]["source_command"])
    return {
        "derived_from_existing_subsystem_semantics": all(c in ir_by_id for c in command_ids),
        "reused_command_categories": categories,
        "reused_commands_by_subsystem": {k: sorted(set(v)) for k, v in sorted(per_subsystem.items())},
        "invented_command_count": 0,
        "proposed_keywords": [
            {"keyword": k, "status": PROPOSED_KEYWORD_STATUS,
             "reason": ("no single subsystem's command.txt has any way to say that two "
                        "subsystems' commands run together or in order, because a single "
                        "command.txt is sequential by construction; this is the only "
                        "construct the scenario shape needs that is not already there")}
            for k in PROPOSED_SCENARIO_KEYWORDS],
        "new_language_introduced": False,
    }


def plan_system_scenario_model(command_plan: Mapping[str, Any],
                               scheduling_plan: Mapping[str, Any],
                               ) -> Dict[str, Any]:
    """SYS-30: the SHAPE a multi-subsystem scenario would have, one entry per
    SYS-27 flow that `plan_cross_subsystem_checking()` already found
    SUPPORTED, plus one entry for every coupled subsystem pair it reported.

    Reuses, and re-decides nothing: the flows and their participating
    subsystems come from the SYS-27 plan, the pair relationships from the
    SYS-25 model, the commands from the SYS-21 IR. This function contributes
    exactly one thing neither of them has -- the block grouping -- and pins
    every scenario's body to NOT_GENERATED.
    """
    ir = command_plan.get("system_command_ir") or {"entries": []}
    ir_by_id = {e["system_command_id"]: e for e in ir.get("entries") or []}
    relationships = scheduling_plan.get("parallelism_model") or {"pairs": []}
    checking = scheduling_plan.get("cross_subsystem_checking") or {"flows": []}
    pair_index = _pair_relationship_index(relationships)

    candidates: List[Tuple[str, str, List[str]]] = []
    for flow in checking.get("flows") or []:
        if flow.get("verdict") != ssp.FLOW_SUPPORTED:
            continue
        candidates.append((flow["flow_id"], flow["flow"],
                           list(flow.get("participating_subsystems") or [])))
    for pair in (checking.get("summary") or {}).get("coupled_subsystem_pairs") or []:
        subsystems = sorted(pair)
        candidates.append(("COUPLED-" + "-".join(subsystems),
                           f"coupled subsystem pair {' + '.join(subsystems)}",
                           subsystems))

    scenarios: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for source_id, description, subsystems in candidates:
        subsystems = sorted(set(subsystems))
        command_ids = sorted(cid for cid, e in ir_by_id.items()
                             if e["source_subsystem"] in subsystems)
        scenario_id = "SYSSCEN-" + hashlib.sha256(
            "|".join([source_id, *subsystems]).encode("utf-8")).hexdigest()[:10].upper()
        if scenario_id in seen:
            continue
        seen.add(scenario_id)
        blocks = _block_plan(command_ids, ir_by_id, pair_index)
        cross_subsystem = len(subsystems) >= 2
        scenarios.append({
            "scenario_id": scenario_id,
            "derived_from": source_id,
            "description": description,
            "participating_subsystems": subsystems,
            "cross_subsystem": cross_subsystem,
            "composition_gate_note": (
                "" if cross_subsystem else
                "fewer than two participating subsystems: a scenario declared for this "
                "would be refused by system_level_composition_gate.py with "
                "NOT_CROSS_SUBSYSTEM_SCENARIO"),
            "command_count": len(command_ids),
            "block_plan": blocks,
            "parallel_block_count": sum(1 for b in blocks if b["block_kind"] == BLOCK_PARALLEL),
            "sequential_block_count": sum(1 for b in blocks if b["block_kind"] == BLOCK_SEQUENTIAL),
            "syntax_derivation": _syntax_derivation(command_ids, ir_by_id),
            "scenario_body_status": SCENARIO_BODY_NOT_GENERATED,
        })

    scenarios.sort(key=lambda s: s["scenario_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "block_kinds": list(SYS30_BLOCK_KINDS),
        "scenarios": scenarios,
        "summary": {
            "scenario_count": len(scenarios),
            "cross_subsystem_scenarios": sum(1 for s in scenarios if s["cross_subsystem"]),
            "parallel_blocks_planned": sum(s["parallel_block_count"] for s in scenarios),
            "scenario_bodies_generated": 0,
            "system_command_txt_written": 0,
            "new_language_introduced": False,
        },
    }


# ===========================================================================
# Composition
# ===========================================================================

def build_system_topology_analysis(analysis: Mapping[str, Any],
                                   integration_plan: Mapping[str, Any],
                                   command_plan: Mapping[str, Any],
                                   scheduling_plan: Mapping[str, Any],
                                   *,
                                   question_store: Any = None,
                                   selection: Optional[Mapping[str, Any]] = None,
                                   now=None) -> Dict[str, Any]:
    """SYS-28 -> SYS-29 -> SYS-30 over one SYS-5..8 analysis, one SYS-15..17
    integration plan, one SYS-18..22 command plan and one SYS-23..27
    scheduling plan. Reads only; this module holds no file writer at all."""
    registry = integration_plan.get("system_resource_registry") or {"entries": []}
    address = reconcile_address_maps(analysis, question_store=question_store, now=now)
    interrupts = reconcile_interrupt_maps(analysis)
    clock_reset = compare_clock_reset_domains(
        analysis, address_reconciliation=address, registry=registry)
    scenarios = plan_system_scenario_model(command_plan, scheduling_plan)

    selected = sorted((selection or {}).get("selected")
                      or analysis.get("subsystems")
                      or registry.get("subsystems") or [])

    document = {
        "schema_version": SCHEMA_VERSION,
        "selected_subsystems": selected,
        "address_map_reconciliation": address,
        "interrupt_map_reconciliation": interrupts,
        "clock_reset_comparison": clock_reset,
        "clock_reset_compatibility_input": clock_reset_compatibility_input(clock_reset),
        "system_scenario_model": scenarios,
        "composer_boundary": ssp.probe_composer_boundary(),
        "summary": {
            "selected_subsystems": selected,
            "address_regions": address["summary"]["region_count"],
            "address_overlaps": address["summary"]["overlapping_pairs"],
            "address_conflicts": address["summary"]["conflicts"],
            "shared_memory_windows": address["summary"]["by_verdict"][SHARED_MEMORY],
            "interrupt_lines": interrupts["summary"]["line_count"],
            "shared_interrupt_lines": len(interrupts["summary"]["shared_lines"]),
            "clock_reset_conflicts": clock_reset["summary"]["conflicts"],
            "cdc_boundaries": clock_reset["summary"]["cdc_boundaries"],
            "duplicate_clock_reset_agents": clock_reset["summary"]["duplicate_clock_reset_agents"],
            "scenarios_planned": scenarios["summary"]["scenario_count"],
            "scenario_bodies_generated": 0,
            "system_command_txt_written": 0,
            "topology_clean": (
                address["summary"]["conflicts"] == 0
                and clock_reset["summary"]["conflicts"] == 0
                and not address["summary"]["subsystems_with_self_overlap"]),
        },
        "artifacts_generated": [],
        "phase_boundary": PHASE_BOUNDARY,
    }
    assert_no_emitted_artifacts(document)
    return document


def analyze_system_topology(root, selected: Sequence[str], *,
                            declared: Optional[Mapping[str, Any]] = None,
                            knowledge_center_client: Any = None,
                            inventory_overlay_path=None,
                            question_store: Any = None,
                            ) -> Dict[str, Any]:
    """Front door: SYS-1 selection -> SYS-5..8 analysis -> SYS-9..14 resources
    -> SYS-15..17 registry -> SYS-18..22 commands -> SYS-23..27 scheduling ->
    SYS-28..30 topology/scenario analysis.

    The whole lower stack is reused through
    `system_scheduling_plan.plan_system_scheduling()`, which itself goes
    through `subsystem_discovery.require_explicit_selection()` -- so SYS-1's
    refusal to compose a set the user did not choose is not bypassed by
    adding a verb on top of it.
    """
    result = ssp.plan_system_scheduling(
        root, selected, declared=declared,
        knowledge_center_client=knowledge_center_client,
        inventory_overlay_path=inventory_overlay_path)
    topology = build_system_topology_analysis(
        result["synthesis"], result["integration_plan"], result["command_plan"],
        result["scheduling_plan"], question_store=question_store,
        selection=result["selection"])
    return {**result, "topology_analysis": topology}


# ===========================================================================
# Reporting
# ===========================================================================

def validate_system_topology_analysis(document: Mapping[str, Any]) -> None:
    """Validate a `build_system_topology_analysis()` document against the real
    JSON schema. Raises jsonschema.ValidationError on a violation."""
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)


def _cell(value: Any) -> str:
    """Markdown cell text with pipes escaped -- a value containing `|` must not
    silently gain a column."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_address_overlap_table(address: Mapping[str, Any]) -> str:
    header = ("| Subsystem A | Region A | Subsystem B | Region B | Kind A | Kind B | "
              "Verdict | Intersection | Basis |")
    lines = [header, "|" + "---|" * 9]
    for row in address.get("overlaps") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            row["subsystem_a"], row["region_a"], row["subsystem_b"], row["region_b"],
            row["range_kind_a"], row["range_kind_b"], row["verdict"],
            f"{row['intersection_start']}..{row['intersection_end']}"
            if row["intersection_start"] else "-",
            row["basis"])) + " |")
    if len(lines) == 2:
        lines.append("| _no cross-subsystem address overlap in this selection_ |" + " |" * 8)
    return "\n".join(lines)


def render_clock_reset_table(comparison: Mapping[str, Any]) -> str:
    header = "| Kind | Subsystem A | Name A | Subsystem B | Name B | Verdict | Basis |"
    lines = [header, "|" + "---|" * 7]
    for row in list(comparison.get("clock_comparisons") or []) + list(
            comparison.get("reset_comparisons") or []):
        lines.append("| " + " | ".join(_cell(v) for v in (
            row["kind"], row["subsystem_a"], row["name_a"], row["subsystem_b"],
            row["name_b"], row["verdict"], row["basis"])) + " |")
    if len(lines) == 2:
        lines.append("| _no cross-subsystem clock or reset pair in this selection_ |" + " |" * 6)
    return "\n".join(lines)


def render_scenario_model_table(scenarios: Mapping[str, Any]) -> str:
    header = ("| Scenario | Derived from | Subsystems | Commands | Parallel blocks | "
              "Sequential blocks | Body |")
    lines = [header, "|" + "---|" * 7]
    for scenario in scenarios.get("scenarios") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            scenario["scenario_id"], scenario["derived_from"],
            ", ".join(scenario["participating_subsystems"]), scenario["command_count"],
            scenario["parallel_block_count"], scenario["sequential_block_count"],
            scenario["scenario_body_status"])) + " |")
    if len(lines) == 2:
        lines.append("| _no supported cross-subsystem flow in this selection_ |" + " |" * 6)
    return "\n".join(lines)


def format_system_topology_report(document: Mapping[str, Any]) -> str:
    """The SYS-28..30 section of the Phase-1 report."""
    summary = document["summary"]
    address = document["address_map_reconciliation"]
    interrupts = document["interrupt_map_reconciliation"]
    clock_reset = document["clock_reset_comparison"]
    scenarios = document["system_scenario_model"]
    out = [
        "# SYSTEM-LEVEL TOPOLOGY ANALYSIS (SYS-28..SYS-30)",
        "",
        f"Selected subsystems: {', '.join(summary['selected_subsystems']) or '(none)'}",
        "",
        "## SYS-28 ADDRESS MAP ANALYSIS",
        "",
        f"{summary['address_regions']} region(s); "
        f"{address['summary']['cross_subsystem_pairs_examined']} cross-subsystem region "
        f"pair(s) examined; {summary['address_overlaps']} overlap(s); "
        f"{summary['address_conflicts']} conflict(s); "
        f"{summary['shared_memory_windows']} shared-memory window(s); "
        f"{address['summary']['escalations_filed']} question(s) filed.",
        "",
        render_address_overlap_table(address),
        "",
        "### Interrupt mapping",
        "",
        f"{interrupts['summary']['line_count']} interrupt line(s); "
        f"{summary['shared_interrupt_lines']} shared across subsystems.",
        "",
        "## SYS-29 CLOCK / RESET INTEGRATION",
        "",
        f"{clock_reset['summary']['clock_pairs']} clock pair(s) and "
        f"{clock_reset['summary']['reset_pairs']} reset pair(s) compared; "
        f"{summary['clock_reset_conflicts']} conflict(s); "
        f"{summary['cdc_boundaries']} CDC boundary/-ies; "
        f"{summary['duplicate_clock_reset_agents']} duplicate clock/reset agent(s) "
        "(read from the SYS-15 registry).",
        "",
        f"Computed `clock_reset_compatibility`: "
        f"{document['clock_reset_compatibility_input']['computed_value']} -- "
        f"{document['clock_reset_compatibility_input']['reason']}",
        "",
        render_clock_reset_table(clock_reset),
        "",
        "## SYS-30 SYSTEM-LEVEL SCENARIO MODEL",
        "",
        f"{summary['scenarios_planned']} scenario shape(s) planned; "
        f"{scenarios['summary']['parallel_blocks_planned']} parallel block(s); "
        f"{summary['scenario_bodies_generated']} scenario body/-ies generated; "
        f"{summary['system_command_txt_written']} System command.txt written.",
        "",
        render_scenario_model_table(scenarios),
        "",
        "## PHASE BOUNDARY",
        "",
        document["phase_boundary"],
    ]
    return "\n".join(out)
