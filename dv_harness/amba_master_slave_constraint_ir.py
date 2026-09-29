"""dv_harness/amba_master_slave_constraint_ir.py -- a three-layer AMBA master/slave
constraint model, kept STRUCTURALLY SEPARATE on purpose:

  ProtocolLegalConstraintIR  -- what the AMBA-4 protocol spec allows IN GENERAL
                                (burst type/length/size legality, outstanding-
                                transaction legality, ordering, security-signal
                                legality). Never DUT-specific.
  DUTCapabilityConstraintIR  -- what THIS DUT actually IMPLEMENTS, from real
                                RTL/spec evidence only. A field this DUT's
                                capability was never confirmed for is UNKNOWN,
                                never assumed to match the protocol's general
                                maximum.
  ScenarioConstraintIR       -- what a specific test scenario may LEGALLY send,
                                derived from the first two: the protocol's
                                legality narrowed by the DUT's confirmed
                                capability, or `REQUIRES_HUMAN_CONFIRMATION`
                                where the DUT layer is not confirmed.

THE ONE RULE THIS MODULE EXISTS TO ENFORCE
-------------------------------------------
"Never infer a DUT capability from VIP capability alone." A VIP user
manual/example proves what the VIP CAN DRIVE, never what the DUT actually
implements. `assert_no_vip_sourced_dut_capability()` runs on every DUT
evidence item handed to `build_dut_capability_constraint_ir()` and RAISES --
loudly, before anything is built -- the moment a VIP-tagged source is offered
as DUT-capability evidence. There is no soft downgrade path for this one: a
VIP-sourced "confirmation" is not a weaker confirmation, it is not
confirmation at all.

WHY THREE OBJECTS AND NOT ONE FLAT RECORD
-------------------------------------------
Merging "what the protocol allows" and "what the DUT does" into one record is
exactly how a review artifact ends up asserting a DUT capability nobody
confirmed, dressed up as a protocol fact. `build_amba_master_slave_constraint_
model()` returns exactly three top-level keys and `assert_layers_structurally_
separate()` refuses a model that flattens a dimension onto the model's own top
level -- a structural guard, not merely a documented convention.

REUSE OVER REINVENT
--------------------
`ProtocolLegalConstraintIR`'s per-field APPLICABLE/NOT_APPLICABLE/UNKNOWN
status is READ, not re-derived: `amba_transaction_ir.ir_field_applicability()`
and `.protocol_signal_vocabulary()` already answer "does this AMBA-4 protocol
carry burst_type/burst_len/burst_size at all" from `connectivity.py`'s own
real, human-reviewed signal witness sets, and this module calls them directly
for the three burst-shaped dimensions rather than building a second witness
table for the same three facts. Only `security`'s witness set
(`SECURITY_WITNESS_SIGNALS`) is new here, because no existing IR in this repo
tracks a security/protection dimension at all -- it is checked against
`connectivity.ALL_AMBA_SIGNAL_NAMES` at import for the identical reason
`amba_transaction_ir._assert_witness_tokens_known()` checks its own witness
tokens: a signal name this repo's one AMBA signal table does not know would
silently witness nothing.

`vip_symbol_index.py`/`verible_parser.py` are NOT imported here: this module
takes DUT evidence as a generic, duck-typed record
(`{"dimension", "value", "source_kind", "citation"}`) rather than parsing RTL
itself, so a caller already holding a verible-parsed port table or a
`spec_doc_map.py`-shaped structural index can hand this module exactly the
facts it extracted without this module re-parsing anything. `spec_doc_map.py`
is not imported either (it is claimed by a concurrent batch); its
`structure_map.json` SHAPE is accepted as a generic `spec_structural_index`
parameter, used only to ENRICH a citation string with the register-chapter
page range a spec-cited fact falls inside -- never to invent a capability
value.

PHASE-1 ONLY
------------
This module builds a constraint MODEL a human/generator reads. It runs no
build, no simulation, no gate, and mints no approval; there is deliberately
no stage gate.
"""
from __future__ import annotations

from dv_harness.amba_transaction_ir import (
    IR_FIELD_APPLICABILITY_UNKNOWN,
    IR_FIELD_APPLICABLE,
    IR_FIELD_NOT_APPLICABLE,
    ir_field_applicability,
    protocol_signal_vocabulary,
)
from dv_harness.connectivity import (
    ALL_AMBA_SIGNAL_NAMES,
    AMBA4_PROTOCOLS,
    render_markdown_table,
)


class AmbaMasterSlaveConstraintError(Exception):
    """A constraint model this module refuses to build: DUT capability evidence
    that is VIP-sourced, an unrecognized dimension, a malformed evidence value,
    or a constraint model whose three layers were flattened onto one record."""

    def __init__(self, code: str, detail=None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


# ===========================================================================
# The six constraint dimensions -- fixed, never per-project
# ===========================================================================

#: Every one of the six dimensions this IR models, in a fixed order. A tuple
#: because it is the contract every layer is built and validated against.
DIMENSIONS: tuple = ("burst_type", "burst_len", "burst_size", "outstanding",
                     "ordering", "security")

# --- Protocol-legal-layer statuses (reused from amba_transaction_ir) ------
# IR_FIELD_APPLICABLE / IR_FIELD_NOT_APPLICABLE / IR_FIELD_APPLICABILITY_UNKNOWN

# --- DUT-capability-layer statuses ----------------------------------------
DUT_STATUS_CONFIRMED = "DUT_CAPABILITY_CONFIRMED"
#: No real RTL/spec evidence confirms this field for this DUT. NEVER defaulted
#: to the protocol's general legality -- that is exactly the inference this
#: module's one hard rule forbids.
DUT_STATUS_UNKNOWN = "DUT_CAPABILITY_UNKNOWN"
#: Two or more real evidence citations for the same field disagree. Kept
#: distinct from UNKNOWN: evidence exists, it just does not agree yet, and a
#: human must reconcile it before this field can be treated as confirmed.
DUT_STATUS_AMBIGUOUS = "DUT_CAPABILITY_AMBIGUOUS_CONFLICTING_EVIDENCE"

# --- Scenario-constraint-layer statuses -----------------------------------
SCENARIO_STATUS_LEGAL = "SCENARIO_LEGAL"
#: The protocol layer says this field is inapplicable; the scenario may never
#: exercise it regardless of anything the DUT layer says.
SCENARIO_STATUS_NOT_APPLICABLE = IR_FIELD_NOT_APPLICABLE
SCENARIO_STATUS_PROTOCOL_UNRESOLVED = IR_FIELD_APPLICABILITY_UNKNOWN
#: The protocol permits this field, but the DUT's own capability for it was
#: never confirmed. A scenario must not assume the DUT implements the
#: protocol's general maximum -- this is the field-level enforcement of the
#: module's one hard rule.
SCENARIO_STATUS_REQUIRES_CONFIRMATION = "REQUIRES_HUMAN_CONFIRMATION"
#: The DUT's own confirmed capability falls OUTSIDE what the protocol legally
#: allows (a claimed burst length beyond the protocol's own maximum, a claimed
#: outstanding depth beyond a single-outstanding protocol's hard cap, ordering
#: looser than the protocol requires). A real, citable finding -- never
#: silently narrowed into something that happens to fit.
SCENARIO_STATUS_CONTRADICTION = "DUT_CAPABILITY_CONTRADICTS_PROTOCOL_LEGALITY"


# ===========================================================================
# Layer 1: ProtocolLegalConstraintIR -- general AMBA-4 protocol legality
# ===========================================================================

#: Security/protection witness signals. Modeled narrowly and deliberately: only
#: the signals the real AMBA AXI/APB specifications define a SECURE/NON-SECURE
#: meaning for. AHB's HPROT is NOT included -- the classic AMBA AHB
#: specification defines HPROT as privileged/bufferable/cacheable access
#: attributes, not a secure/non-secure bit (that arrived only with AHB5, which
#: this repo's signal sets do not track) -- so asserting a security dimension
#: for AHB from HPROT alone would overclaim a semantic this repo's own AHB
#: signal table has no evidence for.
SECURITY_WITNESS_SIGNALS: frozenset = frozenset({"AWPROT", "ARPROT", "PPROT"})


def _assert_security_witness_tokens_known() -> None:
    unknown = sorted(SECURITY_WITNESS_SIGNALS - set(ALL_AMBA_SIGNAL_NAMES))
    if unknown:
        raise AmbaMasterSlaveConstraintError("SECURITY_WITNESS_SIGNAL_UNKNOWN_TO_CONNECTIVITY", {
            "signals": unknown,
            "hint": "connectivity.py holds the repo's only AMBA signal table; add the signal "
                    "there rather than naming one here that nothing else knows"})


_assert_security_witness_tokens_known()

#: `outstanding` legality for AHB/APB-family protocols: a single-master
#: interface issues one address phase at a time (a hard, protocol-general
#: cap), so this is a plain int rather than the ID-bounded sentinel below.
_SINGLE_OUTSTANDING = 1

#: `outstanding` legality for an ID-bearing AXI-family protocol: the protocol
#: itself mandates no numeric ceiling -- the real bound is the master's own
#: ID width and the slave's B/R-channel capacity, both DUT facts, not protocol
#: facts. Kept as a dict (never a bare string) so `_combine_dimension()` can
#: tell it apart from AHB/APB's hard int cap by `isinstance` alone.
_ID_WIDTH_BOUNDED_OUTSTANDING = {
    "kind": "ID_WIDTH_BOUNDED", "cross_id_bound": "NOT_MANDATED_BY_PROTOCOL"}
#: `outstanding` legality for AXI4-Lite: no ID field, so responses must return
#: in request order, but the protocol does not force a single-outstanding
#: restriction the way AHB/APB's fully synchronous transfer does.
_NO_ID_STRICT_ORDER_OUTSTANDING = {
    "kind": "NO_ID_STRICT_ORDER_MULTIPLE_PERMITTED", "cross_id_bound": "N/A_NO_ID_FIELD"}

ORDERING_STRICT_PROGRAM_ORDER = "STRICT_PROGRAM_ORDER"
ORDERING_PER_ID = "PER_ID_ORDERED_CROSS_ID_UNORDERED_PERMITTED"
ORDERING_IN_ORDER_STREAM = "IN_ORDER_WITHIN_STREAM_TID_INTERLEAVE_PERMITTED_IF_TID_PRESENT"

#: A DUT is legally allowed to be MORE ordered (stricter) than a protocol
#: requires, never less. Keyed by the protocol's own required token; the value
#: is the set of DUT-declared ordering tokens that satisfy that requirement.
ORDERING_LEGAL_DUT_VALUES: dict = {
    ORDERING_STRICT_PROGRAM_ORDER: frozenset({ORDERING_STRICT_PROGRAM_ORDER}),
    ORDERING_PER_ID: frozenset({ORDERING_PER_ID, ORDERING_STRICT_PROGRAM_ORDER}),
    ORDERING_IN_ORDER_STREAM: frozenset({ORDERING_IN_ORDER_STREAM, ORDERING_STRICT_PROGRAM_ORDER}),
}

_AHB_FACTS = {
    "burst_type": {
        "value": frozenset({"SINGLE", "INCR", "WRAP4", "WRAP8", "WRAP16",
                            "INCR4", "INCR8", "INCR16"}),
        "basis": ["AMBA AHB protocol specification: HBURST[2:0] encodes SINGLE / "
                  "INCR / WRAP4 / INCR4 / WRAP8 / INCR8 / WRAP16 / INCR16"]},
    "burst_len": {
        "value": {"SINGLE": (1, 1), "INCR": (1, None), "WRAP4": (4, 4), "INCR4": (4, 4),
                  "WRAP8": (8, 8), "INCR8": (8, 8), "WRAP16": (16, 16), "INCR16": (16, 16)},
        "basis": ["AMBA AHB protocol specification: WRAPx/INCRx bursts are exactly x "
                  "beats; undefined-length INCR carries no protocol-mandated maximum "
                  "(max=None means master-defined, not unbounded-by-evidence)"]},
    "burst_size": {
        "value": "power_of_two_bytes_up_to_bus_data_width",
        "basis": ["AMBA AHB protocol specification: HSIZE encodes a power-of-two "
                  "transfer size not exceeding the interface's configured data width"]},
    "outstanding": {
        "value": _SINGLE_OUTSTANDING,
        "basis": ["AMBA AHB protocol specification: one address phase is issued at a "
                  "time on a single AHB interface; at most one transaction outstanding"]},
    "ordering": {
        "value": ORDERING_STRICT_PROGRAM_ORDER,
        "basis": ["AHB carries no transaction-ID field; transactions complete strictly "
                  "in issue order"]},
}

_APB_FACTS = {
    "outstanding": {
        "value": _SINGLE_OUTSTANDING,
        "basis": ["AMBA APB protocol specification: a fully synchronous, "
                  "non-pipelined bus; at most one transaction outstanding"]},
    "ordering": {
        "value": ORDERING_STRICT_PROGRAM_ORDER,
        "basis": ["APB has no transaction-ID field and no pipelining; transactions "
                  "complete strictly in issue order"]},
}

_AXI_MM_BASE_FACTS = {
    "outstanding": {
        "value": dict(_ID_WIDTH_BOUNDED_OUTSTANDING),
        "basis": ["AMBA AXI protocol specification: the protocol mandates no numeric "
                  "outstanding-transaction ceiling; the real bound is the master's ID "
                  "width and the slave's channel capacity, both DUT facts"]},
    "ordering": {
        "value": ORDERING_PER_ID,
        "basis": ["AMBA AXI protocol specification: transactions sharing one ID "
                  "complete in issue order; transactions with different IDs may "
                  "complete in any order"]},
    "security": {
        "value": "AxPROT[1]",
        "basis": ["AMBA AXI protocol specification: AWPROT[1]/ARPROT[1] encode "
                  "Secure / Non-secure access"]},
}

#: The `PROTOCOL_LEGAL_FACTS` table: per-protocol, per-dimension legal facts,
#: as an EXTERNAL, published-spec citation -- never a project-specific
#: fabrication. Populated only for dimensions a real evidence-driven
#: applicability check (`ir_field_applicability()` / `SECURITY_WITNESS_
#: SIGNALS`) actually reports APPLICABLE for that protocol; the builder below
#: never looks a fact up for a NOT_APPLICABLE/UNKNOWN dimension.
PROTOCOL_LEGAL_FACTS: dict = {
    "AHB": dict(_AHB_FACTS),
    # AHB-Lite is the single-master profile of the same protocol: identical
    # per-transaction burst/size/outstanding/ordering legality, just without
    # the multi-master arbitration signals this IR does not model.
    "AHB_LITE": dict(_AHB_FACTS),
    "APB": dict(_APB_FACTS),
    "APB3": dict(_APB_FACTS),
    "APB4": {**_APB_FACTS, "security": {
        "value": "PPROT[0]",
        "basis": ["AMBA APB4 protocol specification: PPROT[0] encodes Secure / "
                  "Non-secure access"]}},
    "AXI3": {
        **_AXI_MM_BASE_FACTS,
        "burst_type": {
            "value": frozenset({"FIXED", "INCR", "WRAP"}),
            "basis": ["AMBA AXI3 protocol specification: AxBURST encodes FIXED / "
                      "INCR / WRAP"]},
        "burst_len": {
            "value": {"FIXED": (1, 16), "INCR": (1, 16), "WRAP": (1, 16)},
            "basis": ["AMBA AXI3 protocol specification: AxLEN is 4 bits (length = "
                      "value+1); every burst type is limited to 1-16 beats"]},
        "burst_size": {
            "value": "power_of_two_bytes_up_to_bus_data_width",
            "basis": ["AMBA AXI3 protocol specification: AxSIZE encodes a "
                      "power-of-two transfer size not exceeding the data bus width"]},
    },
    "AXI4": {
        **_AXI_MM_BASE_FACTS,
        "burst_type": {
            "value": frozenset({"FIXED", "INCR", "WRAP"}),
            "basis": ["AMBA AXI4 protocol specification: AxBURST encodes FIXED / "
                      "INCR / WRAP"]},
        "burst_len": {
            "value": {"FIXED": (1, 16), "WRAP": (1, 16), "INCR": (1, 256)},
            "basis": ["AMBA AXI4 protocol specification: AxLEN is 8 bits; FIXED and "
                      "WRAP bursts remain limited to 1-16 beats, INCR extends to "
                      "1-256 beats"]},
        "burst_size": {
            "value": "power_of_two_bytes_up_to_bus_data_width",
            "basis": ["AMBA AXI4 protocol specification: AxSIZE encodes a "
                      "power-of-two transfer size not exceeding the data bus width"]},
    },
    "AXI4_LITE": {
        "outstanding": {
            "value": dict(_NO_ID_STRICT_ORDER_OUTSTANDING),
            "basis": ["AMBA AXI4-Lite protocol specification: no ID field, so "
                      "multiple outstanding transactions are permitted only in "
                      "strict request order"]},
        "ordering": {
            "value": ORDERING_STRICT_PROGRAM_ORDER,
            "basis": ["AMBA AXI4-Lite protocol specification: with no ID field, "
                      "responses return in strict request order"]},
        "security": dict(_AXI_MM_BASE_FACTS["security"]),
    },
    "ACE_LITE": {
        # ACE-Lite's memory-mapped transaction legality is AXI4's; its
        # coherency extension (AWSNOOP/ARSNOOP/AWDOMAIN/ARDOMAIN/AWBAR/ARBAR)
        # is deliberately NOT modeled here -- see `unmodeled_notes` below.
        **_AXI_MM_BASE_FACTS,
        "burst_type": {
            "value": frozenset({"FIXED", "INCR", "WRAP"}),
            "basis": ["AMBA ACE-Lite protocol specification: layered on an AXI4 "
                      "memory-mapped interface; AxBURST encodes FIXED / INCR / WRAP"]},
        "burst_len": {
            "value": {"FIXED": (1, 16), "WRAP": (1, 16), "INCR": (1, 256)},
            "basis": ["AMBA ACE-Lite protocol specification: same AxLEN legality as "
                      "the underlying AXI4 interface"]},
        "burst_size": {
            "value": "power_of_two_bytes_up_to_bus_data_width",
            "basis": ["AMBA ACE-Lite protocol specification: same AxSIZE legality "
                      "as the underlying AXI4 interface"]},
    },
    "AXI4_STREAM": {
        "ordering": {
            "value": ORDERING_IN_ORDER_STREAM,
            "basis": ["AMBA AXI4-Stream protocol specification: a single stream "
                      "(one TID) is strictly ordered; interleaving across distinct "
                      "TID streams is permitted where TID is present"]},
    },
}

#: What each protocol's constraint MODEL deliberately does not cover, so a
#: caller reading `unmodeled_notes` never mistakes silence for a claim of
#: coverage. Empty for every protocol without a stated gap.
UNMODELED_NOTES: dict = {
    "ACE_LITE": ["ace_lite_coherency: AWSNOOP/ARSNOOP/AWDOMAIN/ARDOMAIN/AWBAR/ARBAR "
                "legality is not modeled by this IR"],
    "AXI4_STREAM": ["AXI4-Stream sideband width/interleave-depth legality "
                    "(TID/TDEST) is not modeled by this IR"],
}


def _protocol_legal_fact(protocol: str, dim: str) -> dict:
    facts = PROTOCOL_LEGAL_FACTS.get(protocol, {}).get(dim)
    if facts is None:
        raise AmbaMasterSlaveConstraintError("PROTOCOL_LEGAL_FACT_MISSING", {
            "protocol": protocol, "dimension": dim,
            "hint": "a dimension an applicability check reports APPLICABLE must have a "
                    "real, cited legal-value entry in PROTOCOL_LEGAL_FACTS"})
    return facts


def build_protocol_legal_constraint_ir(protocol: str) -> dict:
    """`ProtocolLegalConstraintIR` for one protocol: what AMBA-4 permits in
    general, for each of the six dimensions, never mentioning this or any
    other DUT.

    Reuses `amba_transaction_ir.ir_field_applicability()` for the three
    burst-shaped dimensions -- there is no second witness table for them in
    this module -- and this module's own `SECURITY_WITNESS_SIGNALS` for
    `security`. `outstanding`/`ordering` are dimensions no prior IR in this
    repo modeled at all, so their applicability is computed here directly."""
    fields: dict = {}
    unmodeled = list(UNMODELED_NOTES.get(protocol, ()))

    if protocol not in AMBA4_PROTOCOLS:
        for dim in DIMENSIONS:
            fields[dim] = {
                "status": IR_FIELD_APPLICABILITY_UNKNOWN, "legal_value": None,
                "basis": [f"protocol {protocol!r} is not one of the ten AMBA-4 "
                          f"classifications, so its general legality is undecided"]}
        return {"protocol": protocol, "fields": fields, "unmodeled_notes": unmodeled}

    burst_applicability = ir_field_applicability(protocol)
    for dim in ("burst_type", "burst_len", "burst_size"):
        applies = burst_applicability[dim]
        if applies["status"] != IR_FIELD_APPLICABLE:
            fields[dim] = {"status": applies["status"], "legal_value": None,
                           "basis": [applies["reason"]]}
        else:
            facts = _protocol_legal_fact(protocol, dim)
            fields[dim] = {"status": IR_FIELD_APPLICABLE, "legal_value": facts["value"],
                           "basis": list(facts["basis"])}

    vocabulary = protocol_signal_vocabulary(protocol)
    security_witness = sorted(SECURITY_WITNESS_SIGNALS & vocabulary)
    if security_witness:
        facts = _protocol_legal_fact(protocol, "security")
        fields["security"] = {"status": IR_FIELD_APPLICABLE, "legal_value": facts["value"],
                              "basis": list(facts["basis"]) +
                                       [f"witnessed by {security_witness}"]}
    else:
        fields["security"] = {
            "status": IR_FIELD_NOT_APPLICABLE, "legal_value": None,
            "basis": [f"{protocol} carries none of {sorted(SECURITY_WITNESS_SIGNALS)}"]}

    if protocol == "AXI4_STREAM":
        fields["outstanding"] = {
            "status": IR_FIELD_NOT_APPLICABLE, "legal_value": None,
            "basis": ["AXI4-Stream has no address-phase request/response "
                      "transaction; an outstanding-transaction count is not a "
                      "meaningful concept for a continuous stream"]}
    else:
        facts = _protocol_legal_fact(protocol, "outstanding")
        fields["outstanding"] = {"status": IR_FIELD_APPLICABLE, "legal_value": facts["value"],
                                 "basis": list(facts["basis"])}

    facts = _protocol_legal_fact(protocol, "ordering")
    fields["ordering"] = {"status": IR_FIELD_APPLICABLE, "legal_value": facts["value"],
                          "basis": list(facts["basis"])}

    return {"protocol": protocol, "fields": fields, "unmodeled_notes": unmodeled}


# ===========================================================================
# Layer 2: DUTCapabilityConstraintIR -- what THIS DUT actually implements
# ===========================================================================

#: The only sanctioned real-evidence source kinds. A VIP-tagged source is
#: never in this set (and is refused loudly regardless, see
#: `assert_no_vip_sourced_dut_capability`) -- this set is the POSITIVE
#: allowlist of what actually counts as DUT evidence.
ALLOWED_DUT_EVIDENCE_SOURCE_KINDS: frozenset = frozenset({
    "rtl_port", "rtl_parameter", "rtl_register", "rtl_localparam",
    "register_map", "spec_document", "programming_guide",
    "human_confirmation", "register_rtl_trace",
})


def _is_allowed_source_kind(source_kind) -> bool:
    if not source_kind:
        return False
    return str(source_kind).strip().lower() in ALLOWED_DUT_EVIDENCE_SOURCE_KINDS


def assert_no_vip_sourced_dut_capability(dut_evidence) -> None:
    """The module's one hard rule: a VIP manual/example proves what the VIP can
    DRIVE, never what the DUT actually implements. Any evidence item whose
    `source_kind` names a VIP origin is refused before anything is built --
    there is no downgrade path, only a raise."""
    offenders = [{"dimension": item.get("dimension") if isinstance(item, dict) else None,
                  "source_kind": item.get("source_kind") if isinstance(item, dict) else None}
                 for item in (dut_evidence or ())
                 if isinstance(item, dict) and "vip" in str(item.get("source_kind") or "").lower()]
    if offenders:
        raise AmbaMasterSlaveConstraintError("DUT_CAPABILITY_FROM_VIP_EVIDENCE_FORBIDDEN", {
            "offenders": offenders,
            "hint": "a VIP manual/example proves what the VIP CAN drive, never what the DUT "
                    "actually implements; cite real RTL evidence (rtl_port/rtl_parameter/"
                    "rtl_register) or real DUT spec/programming-guide evidence instead"})


def _format_citation(item: dict, spec_structural_index) -> str:
    """The evidence item's own citation, optionally enriched with a
    `spec_doc_map.py`-shaped structural index's register-chapter page range --
    never used to invent a value, only to make an already-cited page more
    useful to a reader. Silently leaves the citation untouched on any
    malformed or absent structural index."""
    citation = str(item.get("citation") or "").strip()
    page = item.get("page")
    if page is None or not isinstance(spec_structural_index, dict):
        return citation
    chapters = (spec_structural_index.get("register_chapters")
               or spec_structural_index.get("registerChapters") or [])
    if not isinstance(chapters, (list, tuple)):
        return citation
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        start = chapter.get("start_page")
        end = chapter.get("end_page")
        if start is None or end is None:
            continue
        try:
            in_range = start <= page <= end
        except TypeError:
            continue
        if in_range:
            title = chapter.get("title") or chapter.get("heading") or "register-map chapter"
            return (f"{citation} (page {page}, within detected {title!r} spanning "
                    f"pages {start}-{end})")
    return citation


def build_dut_capability_constraint_ir(protocol: str, dut_evidence=None,
                                       spec_structural_index=None) -> dict:
    """`DUTCapabilityConstraintIR` for one protocol on one DUT: what this DUT
    actually implements, per dimension, each entry citing the real evidence it
    rests on.

    `dut_evidence` is a list of `{"dimension", "value", "source_kind",
    "citation", "page"?}` records. A field with no recognized-source citation
    is `DUT_STATUS_UNKNOWN` -- never defaulted to the protocol's general
    legality. Two recognized citations disagreeing on the same field's value
    are `DUT_STATUS_AMBIGUOUS`, not silently resolved by picking one.

    `spec_structural_index` is accepted read-only, in the shape
    `spec_doc_map.py` produces (never imported), and used only to enrich a
    citation's own page number with the register-chapter it falls inside."""
    dut_evidence = list(dut_evidence or ())
    assert_no_vip_sourced_dut_capability(dut_evidence)

    by_dim: dict = {dim: [] for dim in DIMENSIONS}
    for item in dut_evidence:
        if not isinstance(item, dict):
            raise AmbaMasterSlaveConstraintError("DUT_EVIDENCE_ITEM_NOT_A_DICT", {"item": item})
        dim = item.get("dimension")
        if dim not in DIMENSIONS:
            raise AmbaMasterSlaveConstraintError("DUT_EVIDENCE_UNKNOWN_DIMENSION", {
                "dimension": dim, "known_dimensions": list(DIMENSIONS)})
        by_dim[dim].append(item)

    fields: dict = {}
    for dim in DIMENSIONS:
        items = by_dim[dim]
        recognized = [i for i in items if _is_allowed_source_kind(i.get("source_kind"))]
        unrecognized_citations = [i.get("citation") for i in items if i not in recognized]
        if not recognized:
            fields[dim] = {
                "status": DUT_STATUS_UNKNOWN, "value": None,
                "evidence": [c for c in unrecognized_citations if c],
                "reason": "no recognized real RTL/spec evidence citation confirms this DUT "
                          "capability; a scenario must never assume it matches the protocol's "
                          "general legality"}
            continue
        values = [i["value"] for i in recognized]
        citations = [_format_citation(i, spec_structural_index) for i in recognized]
        if len(set(_hashable(v) for v in values)) > 1:
            fields[dim] = {
                "status": DUT_STATUS_AMBIGUOUS, "value": values, "evidence": citations,
                "reason": "multiple real evidence citations disagree on this DUT capability; "
                          "resolve the disagreement before treating it as confirmed"}
        else:
            fields[dim] = {"status": DUT_STATUS_CONFIRMED, "value": values[0],
                           "evidence": citations,
                           "reason": "confirmed by real RTL/spec evidence"}
    return {"protocol": protocol, "fields": fields}


def _hashable(value):
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    if isinstance(value, (list, set, frozenset)):
        return tuple(sorted(_hashable(v) for v in value))
    return value


# ===========================================================================
# Layer 3: ScenarioConstraintIR -- what a scenario may legally send
# ===========================================================================

def _combine_dimension(dim: str, protocol_value, dut_value):
    """The protocol's general legality narrowed by the DUT's confirmed
    capability, for one dimension. Returns `(status, value, reason)`; never
    silently accepts a DUT value that falls outside protocol legality --
    that is `SCENARIO_STATUS_CONTRADICTION`, reported, never hidden."""
    if dim == "burst_type":
        if not isinstance(dut_value, (set, frozenset)):
            raise AmbaMasterSlaveConstraintError("DUT_BURST_TYPE_VALUE_NOT_A_SET",
                                                 {"value": dut_value})
        illegal = set(dut_value) - set(protocol_value)
        if illegal:
            return (SCENARIO_STATUS_CONTRADICTION, None,
                    f"DUT declares support for burst type(s) {sorted(illegal)}, which this "
                    f"protocol's legality does not define")
        return (SCENARIO_STATUS_LEGAL, frozenset(dut_value),
                "DUT-confirmed subset of the protocol-legal burst types")

    if dim == "burst_len":
        if not isinstance(dut_value, dict):
            raise AmbaMasterSlaveConstraintError("DUT_BURST_LEN_VALUE_NOT_A_DICT",
                                                 {"value": dut_value})
        combined: dict = {}
        problems: list = []
        for burst_type, dut_range in dut_value.items():
            if burst_type not in protocol_value:
                problems.append(f"burst type {burst_type!r} is not protocol-legal for this "
                                f"protocol")
                continue
            p_min, p_max = protocol_value[burst_type]
            d_min, d_max = dut_range
            # A DUT claim outside what the protocol itself allows is a
            # CONTRADICTION, never silently narrowed to whatever happens to
            # fit -- claiming a 300-beat INCR burst on a protocol whose own
            # maximum is 256 is not "really 256", it is an impossible claim.
            if d_min < p_min:
                problems.append(f"burst type {burst_type!r}: DUT-declared minimum "
                                f"{d_min} is below this protocol's legal minimum {p_min}")
                continue
            if p_max is not None and (d_max is None or d_max > p_max):
                problems.append(f"burst type {burst_type!r}: DUT-declared range {dut_range} "
                                f"exceeds this protocol's legal maximum {p_max}")
                continue
            combined[burst_type] = (d_min, d_max)
        if problems:
            return (SCENARIO_STATUS_CONTRADICTION, None, "; ".join(problems))
        return (SCENARIO_STATUS_LEGAL, combined,
                f"protocol-legal range narrowed to DUT-confirmed burst length(s): "
                f"{sorted(combined)}")

    if dim == "burst_size":
        if not isinstance(dut_value, (set, frozenset)):
            raise AmbaMasterSlaveConstraintError("DUT_BURST_SIZE_VALUE_NOT_A_SET",
                                                 {"value": dut_value})
        non_power_of_two = sorted(v for v in dut_value if v <= 0 or (v & (v - 1)) != 0)
        if non_power_of_two:
            return (SCENARIO_STATUS_CONTRADICTION, None,
                    f"DUT declares transfer size(s) {non_power_of_two}, which are not a "
                    f"legal power-of-two byte count")
        return (SCENARIO_STATUS_LEGAL, frozenset(dut_value),
                "DUT-confirmed transfer size(s); the protocol imposes no fixed numeric "
                "ceiling beyond power-of-two alignment to the bus data width")

    if dim == "outstanding":
        if isinstance(dut_value, bool) or not isinstance(dut_value, int) or dut_value < 1:
            raise AmbaMasterSlaveConstraintError("DUT_OUTSTANDING_VALUE_NOT_A_POSITIVE_INT",
                                                 {"value": dut_value})
        if isinstance(protocol_value, int) and dut_value > protocol_value:
            return (SCENARIO_STATUS_CONTRADICTION, None,
                    f"DUT declares up to {dut_value} outstanding transaction(s), but this "
                    f"protocol permits at most {protocol_value}")
        return (SCENARIO_STATUS_LEGAL, dut_value, "DUT-confirmed outstanding-transaction depth")

    if dim == "ordering":
        legal_set = ORDERING_LEGAL_DUT_VALUES.get(protocol_value, frozenset({protocol_value}))
        if dut_value not in legal_set:
            return (SCENARIO_STATUS_CONTRADICTION, None,
                    f"DUT declares ordering behaviour {dut_value!r}, which is looser than "
                    f"this protocol's required ordering {protocol_value!r} (a DUT may only "
                    f"be as strict or stricter than required, never looser)")
        return (SCENARIO_STATUS_LEGAL, dut_value,
                "DUT-confirmed ordering behaviour (at least as strict as this protocol "
                "requires)")

    if dim == "security":
        return (SCENARIO_STATUS_LEGAL, dut_value,
                "DUT-confirmed security-checking behaviour; the protocol only guarantees "
                "the security/protection signal's presence, not what the DUT does with it")

    raise AmbaMasterSlaveConstraintError("UNKNOWN_DIMENSION", {"dimension": dim})


def build_scenario_constraint_ir(protocol_legal_ir: dict, dut_capability_ir: dict) -> dict:
    """`ScenarioConstraintIR`: what a scenario may legally send, derived from
    the first two layers and never asserting anything neither of them
    supports.

    A dimension the protocol layer marks NOT_APPLICABLE (or UNKNOWN, for an
    unresolved protocol) passes that status straight through -- the DUT layer
    is never consulted for a field the protocol itself rules out. A dimension
    the protocol permits but the DUT layer never confirmed is
    `REQUIRES_HUMAN_CONFIRMATION`, never silently assumed to match the
    protocol's general maximum."""
    protocol = protocol_legal_ir.get("protocol")
    if protocol != dut_capability_ir.get("protocol"):
        raise AmbaMasterSlaveConstraintError("PROTOCOL_MISMATCH_BETWEEN_LAYERS", {
            "protocol_legal_ir_protocol": protocol,
            "dut_capability_ir_protocol": dut_capability_ir.get("protocol")})

    fields: dict = {}
    for dim in DIMENSIONS:
        p_entry = protocol_legal_ir["fields"][dim]
        if p_entry["status"] != IR_FIELD_APPLICABLE:
            fields[dim] = {"status": p_entry["status"], "value": None,
                           "reason": (p_entry["basis"][0] if p_entry["basis"]
                                      else "not applicable")}
            continue
        d_entry = dut_capability_ir["fields"][dim]
        if d_entry["status"] != DUT_STATUS_CONFIRMED:
            fields[dim] = {
                "status": SCENARIO_STATUS_REQUIRES_CONFIRMATION, "value": None,
                "reason": (f"protocol legally permits {p_entry['legal_value']!r} for {dim}, "
                          f"but this DUT's own capability is {d_entry['status']} -- a "
                          f"scenario must never assume the DUT implements the protocol's "
                          f"general legality; obtain real RTL/spec evidence or route to a "
                          f"human")}
            continue
        status, value, reason = _combine_dimension(dim, p_entry["legal_value"], d_entry["value"])
        fields[dim] = {"status": status, "value": value, "reason": reason}
    return {"protocol": protocol, "fields": fields}


# ===========================================================================
# The three-layer model -- structurally kept separate, enforced not just
# documented
# ===========================================================================

_MODEL_LAYER_KEYS: frozenset = frozenset({"protocol_legal", "dut_capability", "scenario_constraint"})


def assert_layers_structurally_separate(model: dict) -> None:
    """The one structural guarantee this module makes: the three layers stay
    three separate records. Refuses a model whose top level is not exactly
    the three layer keys, and refuses one where a dimension name has been
    merged onto the model's own top level -- the exact flattening this
    module's docstring warns against, caught rather than merely avoided by
    convention."""
    keys = set(model.keys())
    for dim in DIMENSIONS:
        if dim in keys:
            raise AmbaMasterSlaveConstraintError("CONSTRAINT_MODEL_FLATTENED", {
                "dimension": dim,
                "hint": "a dimension must live under one of the three layer keys, never "
                        "merged onto the model's own top level"})
    if keys != _MODEL_LAYER_KEYS:
        raise AmbaMasterSlaveConstraintError("CONSTRAINT_MODEL_NOT_THREE_LAYERS", {
            "keys": sorted(keys), "expected": sorted(_MODEL_LAYER_KEYS)})


def build_amba_master_slave_constraint_model(protocol: str, dut_evidence=None,
                                             spec_structural_index=None) -> dict:
    """The full three-layer model for one protocol on one DUT: `protocol_legal`,
    `dut_capability` and `scenario_constraint`, each a separate object."""
    protocol_legal = build_protocol_legal_constraint_ir(protocol)
    dut_capability = build_dut_capability_constraint_ir(protocol, dut_evidence,
                                                        spec_structural_index)
    scenario_constraint = build_scenario_constraint_ir(protocol_legal, dut_capability)
    model = {"protocol_legal": protocol_legal, "dut_capability": dut_capability,
            "scenario_constraint": scenario_constraint}
    assert_layers_structurally_separate(model)
    return model


# ===========================================================================
# Reporting
# ===========================================================================

def render_constraint_model_report(model: dict) -> str:
    """One review table per layer, using `connectivity.render_markdown_table()`
    -- this repo's one parameterized table renderer, not a second one."""
    assert_layers_structurally_separate(model)
    protocol = model["protocol_legal"]["protocol"]

    def _rows(layer_key: str, value_key: str, reason_key: str) -> list:
        layer = model[layer_key]
        return [{"dimension": dim, "status": layer["fields"][dim]["status"],
                 "value": layer["fields"][dim].get(value_key),
                 "reason": (layer["fields"][dim].get(reason_key) or
                           "; ".join(layer["fields"][dim].get("basis") or []))}
                for dim in DIMENSIONS]

    columns = [("dimension", "Dimension"), ("status", "Status"),
              ("value", "Value"), ("reason", "Basis / Reason")]
    lines = [f"# AMBA Master/Slave Constraint Model -- {protocol}", "",
            "## Layer 1: Protocol-Legal Constraint (general AMBA-4 legality)", "",
            render_markdown_table(columns, _rows("protocol_legal", "legal_value", "reason")), "",
            "## Layer 2: DUT-Capability Constraint (this DUT's confirmed evidence only)", "",
            render_markdown_table(columns, _rows("dut_capability", "value", "reason")), "",
            "## Layer 3: Scenario Constraint (protocol legality narrowed by DUT capability)", "",
            render_markdown_table(columns, _rows("scenario_constraint", "value", "reason")), ""]
    notes = model["protocol_legal"].get("unmodeled_notes") or []
    if notes:
        lines += ["## Not modeled by this IR", ""] + [f"- {n}" for n in notes] + [""]
    return "\n".join(lines)
