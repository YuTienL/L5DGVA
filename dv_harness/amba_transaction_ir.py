"""dv_harness/amba_transaction_ir.py -- SYOSCB-10 (AMBA TRANSACTION IR) and
SYOSCB-9 (AMBA PROTOCOL ADAPTER LAYER), as planning machinery rather than as
SystemVerilog.

WHAT THIS IS
------------
SYOSCB-10 asks for a common internal AMBA transaction representation, and says
so conditionally: "Create or extend a common internal AMBA Transaction IR ONLY
IF an equivalent representation does not already exist." The SYOSCB-9/10/11
audit answered that question by reading the repo: seven of the twenty-two
proposed fields already have a real identifier/value space in
`amba_port_registry.AMBA_PORT_REGISTRY_FIELDS`, and the other fifteen are
per-transaction RUNTIME values with no counterpart anywhere. This module is
that answer as code -- an IR whose registry-backed half is JOINED from the
registry by column name and never re-derived, so an IR field and the registry
column behind it cannot disagree.

`IR_FIELD_ORIGIN` is where that split lives, and it is checkable rather than
described: every `IR_ORIGIN_PORT_REGISTRY` field names a real
`AMBA_PORT_REGISTRY_FIELDS` column (asserted at import), and every other field
carries an explicit sentinel saying WHO fills it -- the Phase-2 adapter at
runtime, or the SYOSCB-12 route predictor -- never a plausible-looking blank.

"DO NOT FORCE PROTOCOL-INAPPLICABLE FIELDS" IS DERIVED, NOT TYPED
-----------------------------------------------------------------
SYOSCB-10's own constraint is enforced from `connectivity.py`'s existing
spec-fixed AMBA signal sets: a field is applicable to a protocol when that
protocol's real signal vocabulary contains a signal that WITNESSES it
(`burst_len` needs AWLEN/ARLEN or HBURST; `response` needs BRESP/RRESP, HRESP
or PSLVERR). There is deliberately no second AMBA signal table in this repo, so
`_assert_witness_tokens_known()` refuses at import if this module ever names a
signal `connectivity.ALL_AMBA_SIGNAL_NAMES` does not know. That is what keeps
"APB has no burst" a consequence of the signal sets a human already reviewed
rather than a claim typed here.

An unresolved protocol yields `IR_FIELD_APPLICABILITY_UNKNOWN` on every
protocol-conditional field -- not a default-applicable shape. A port whose
protocol nobody established cannot have its transaction shape decided, and
guessing one is how an adapter ends up populating a field the bus does not
have.

SYOSCB-9: A PLAN, AND ONLY FOR PROTOCOLS THAT REALLY EXIST
-----------------------------------------------------------
`plan_amba_adapters()` proposes one logical adapter per protocol the
AMBA_PORT_REGISTRY actually carries -- SYOSCB-8's "Do not instantiate support
for nonexistent protocols merely because the framework can model them",
enforced by `assert_no_adapter_for_absent_protocol()`. Each entry says which IR
fields that adapter must populate, which it must READ from the registry instead
of re-deriving, and which it must leave alone as inapplicable.

SYOSCB-9's "Search existing L5/VIP adapters first. Default = ENHANCE / REUSE
before ADD" is honored by making the search a real INPUT, and by keeping "no
search was performed" distinct from "a search found nothing": `None` yields
`REQUIRED_HUMAN_INPUT` (nobody looked yet), an empty list yields
`ADAPTER_VERDICT_ADD` (somebody looked, there is nothing to reuse). Collapsing
those two into one verdict would let an unperformed search read as a licence to
write new code.

PHASE-1 ONLY (SYOSCB-33 / SYOSCB-34)
------------------------------------
Nothing here emits SystemVerilog. The adapter entries are a plan a human
reviews; the real adapter class, and the real `cl_syoscb::add_item()` call it
would eventually make, are Phase-2 work gated on approval. Every rendered
artifact is run through `syoscb_source_audit.assert_no_emittable_sv()` and
`amba_fabric_discovery.assert_no_bind_statement()` for the same reason those
gates exist elsewhere: a planning artifact that renders compilable code is one
copy-paste away from being unreviewed testbench source.
"""
from __future__ import annotations

from dv_harness.amba_fabric_discovery import (
    BIND_CHECK_UNKNOWN_VALUE,
    MULTIPLE_BRANCH_PARENT_BIND,
    assert_no_bind_statement,
)
from dv_harness.amba_port_registry import (
    AMBA_PORT_REGISTRY_FIELDS,
    ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
    PortRegistryError,
)
from dv_harness.connectivity import (
    AHB_OPTIONAL_EVIDENCE_SIGNALS,
    ALL_AMBA_SIGNAL_NAMES,
    AMBA4_DISPLAY_NAMES,
    AMBA4_PROTOCOLS,
    AMBA_PROTOCOL_FAMILY,
    AXI4_LITE_EVIDENCE_SIGNALS,
    AXI4_STREAM_OPTIONAL_EVIDENCE_SIGNALS,
    AXI_USER_SIDEBAND_SIGNALS,
    EXTERNAL_ENDPOINT_MASTER,
    EXTERNAL_ENDPOINT_SLAVE,
    FABRIC_SIDE_MASTER_INTERFACE,
    FABRIC_SIDE_SLAVE_INTERFACE,
    PROTOCOL_FINGERPRINTS,
    REQUIRED_HUMAN_INPUT,
    render_markdown_table,
)
from dv_harness.syoscb_source_audit import assert_no_emittable_sv


class AmbaTransactionIrError(PortRegistryError):
    """An IR template that forces a protocol-inapplicable field, an adapter
    planned for a protocol no discovered port speaks, or a template missing one
    of SYOSCB-10's fields. Subclasses `PortRegistryError` so a caller already
    handling the AMBA_PORT_REGISTRY pipeline's errors handles these too."""


# ===========================================================================
# SYOSCB-10's field list
# ===========================================================================

#: SYOSCB-10's "logical fields may include" list, verbatim and in the doc's own
#: order. A tuple because it is the contract: templates are built by iterating
#: it and `assert_ir_templates_complete()` checks against it, so a field cannot
#: be quietly dropped from either end.
AMBA_TRANSACTION_IR_FIELDS: tuple = (
    "protocol",
    "master_port_id",
    "slave_port_id",
    "source_hierarchy",
    "destination_hierarchy",
    "transaction_type",
    "address",
    "data",
    "byte_enable",
    "burst_type",
    "burst_len",
    "burst_size",
    "transaction_id",
    "original_id",
    "fabric_id",
    "response",
    "sequence_number",
    "timestamp",
    "route_id",
    "clock_domain",
    "expected_actual",
    "source_evidence",
)

#: The field is READ OFF an AMBA_PORT_REGISTRY column. Nothing about it is
#: recomputed here, so it cannot disagree with the registry a human reviewed.
IR_ORIGIN_PORT_REGISTRY = "JOINED_FROM_AMBA_PORT_REGISTRY"
#: A per-transaction runtime value only a monitor/adapter can supply. Genuinely
#: new -- the registry's `address_width` is a static bit count, not an address.
IR_ORIGIN_ADAPTER_RUNTIME = "POPULATED_BY_PROTOCOL_ADAPTER_AT_RUNTIME"
#: A routing/comparison decision the SYOSCB-12 route-and-transform predictor
#: owns. No code in this repo computes one today; naming the owner is how this
#: stays a declared gap rather than a silently empty column.
IR_ORIGIN_ROUTE_PREDICTOR = "DERIVED_BY_ROUTE_TRANSFORM_PREDICTOR"

#: Which of AMBA_PORT_REGISTRY_FIELDS supplies each registry-backed IR field.
#: Verified against the real registry schema at import, so renaming a registry
#: column breaks loudly here instead of silently producing an empty IR field.
IR_REGISTRY_JOIN_COLUMN: dict = {
    "protocol": "protocol",
    # Both port ids join the SAME column: the observation point supplies the
    # near side, and the far side is a routing question, not a second column.
    "master_port_id": "port_id",
    "slave_port_id": "port_id",
    "source_hierarchy": "endpoint_hierarchy",
    "destination_hierarchy": "endpoint_hierarchy",
    "clock_domain": "clock",
    "source_evidence": "source_evidence",
}

IR_FIELD_ORIGIN: dict = {
    **{f: IR_ORIGIN_PORT_REGISTRY for f in IR_REGISTRY_JOIN_COLUMN},
    "transaction_type": IR_ORIGIN_ADAPTER_RUNTIME,
    "address": IR_ORIGIN_ADAPTER_RUNTIME,
    "data": IR_ORIGIN_ADAPTER_RUNTIME,
    "byte_enable": IR_ORIGIN_ADAPTER_RUNTIME,
    "burst_type": IR_ORIGIN_ADAPTER_RUNTIME,
    "burst_len": IR_ORIGIN_ADAPTER_RUNTIME,
    "burst_size": IR_ORIGIN_ADAPTER_RUNTIME,
    "transaction_id": IR_ORIGIN_ADAPTER_RUNTIME,
    "response": IR_ORIGIN_ADAPTER_RUNTIME,
    "sequence_number": IR_ORIGIN_ADAPTER_RUNTIME,
    "timestamp": IR_ORIGIN_ADAPTER_RUNTIME,
    # The three predictor-owned fields. `original_id`/`fabric_id` are the two
    # halves of an ID REMAP, which is a fabric behavior nobody observes at a
    # single port: an adapter sees one id, and which of the two roles it plays
    # is only decidable once both ends of the route are known.
    "original_id": IR_ORIGIN_ROUTE_PREDICTOR,
    "fabric_id": IR_ORIGIN_ROUTE_PREDICTOR,
    "route_id": IR_ORIGIN_ROUTE_PREDICTOR,
    "expected_actual": IR_ORIGIN_ROUTE_PREDICTOR,
}


# ===========================================================================
# Per-protocol applicability, derived from connectivity.py's signal sets
# ===========================================================================

IR_FIELD_APPLICABLE = "APPLICABLE"
IR_FIELD_NOT_APPLICABLE = "NOT_APPLICABLE_FOR_PROTOCOL"
#: The protocol itself never resolved, so its transaction shape is undecided.
#: Deliberately NOT folded into NOT_APPLICABLE: "this bus has no burst length"
#: and "nobody established what this bus is" are different facts, and only the
#: second one is a discovery gap a human can close.
IR_FIELD_APPLICABILITY_UNKNOWN = "UNKNOWN_PROTOCOL_UNRESOLVED"

#: Signals whose PRESENCE in a protocol's own vocabulary witnesses that the
#: field exists on that protocol. Every token is checked against
#: `connectivity.ALL_AMBA_SIGNAL_NAMES` at import -- this module names no AMBA
#: signal the repo's one signal table does not already know.
IR_FIELD_WITNESS_SIGNALS: dict = {
    "address": frozenset({"AWADDR", "ARADDR", "HADDR", "PADDR"}),
    "data": frozenset({"WDATA", "RDATA", "HWDATA", "HRDATA",
                       "PWDATA", "PRDATA", "TDATA"}),
    # AHB encodes the active byte lanes in HSIZE+HADDR and has no strobe, which
    # is why no H-signal appears here.
    "byte_enable": frozenset({"WSTRB", "PSTRB", "TSTRB", "TKEEP"}),
    "burst_type": frozenset({"AWBURST", "ARBURST", "HBURST"}),
    # AHB carries beat count and burst kind in the same HBURST field.
    "burst_len": frozenset({"AWLEN", "ARLEN", "HBURST"}),
    "burst_size": frozenset({"AWSIZE", "ARSIZE", "HSIZE"}),
    "transaction_id": frozenset({"AWID", "ARID", "BID", "RID", "TID"}),
    # An ID must exist before a remap of it can be tracked, so both halves of
    # the remap share the id witnesses.
    "original_id": frozenset({"AWID", "ARID", "BID", "RID", "TID"}),
    "fabric_id": frozenset({"AWID", "ARID", "BID", "RID", "TID"}),
    "response": frozenset({"BRESP", "RRESP", "HRESP", "PSLVERR"}),
}

#: Fields that exist on every AMBA protocol because they describe the transfer
#: or its provenance rather than a bus signal. `transaction_type` is here on
#: purpose: every protocol distinguishes a read from a write (AXI4-Stream's
#: single direction included, as its own transaction type), so there is no
#: protocol for which the field is meaningless.
PROTOCOL_INDEPENDENT_IR_FIELDS: frozenset = frozenset(
    set(AMBA_TRANSACTION_IR_FIELDS) - set(IR_FIELD_WITNESS_SIGNALS))

#: Signals a protocol carries beyond the REQUIRED set `PROTOCOL_FINGERPRINTS`
#: matches on. A fingerprint is a minimum match, not a vocabulary: AXI4 really
#: does have WSTRB even though no fingerprint needs it to recognise AXI4, and
#: AHB really does have HRESP/HBURST even though a fingerprint match must not
#: require them.
_FAMILY_OPTIONAL_SIGNALS: dict = {
    "AHB": AHB_OPTIONAL_EVIDENCE_SIGNALS,
    "APB": frozenset(),
    "AXI_MM": AXI_USER_SIDEBAND_SIGNALS | AXI4_LITE_EVIDENCE_SIGNALS,
    "AXI_STREAM": AXI4_STREAM_OPTIONAL_EVIDENCE_SIGNALS,
}


def _assert_witness_tokens_known() -> None:
    """Every witness signal must be one `connectivity.ALL_AMBA_SIGNAL_NAMES`
    already knows. Runs at import, because a witness token this repo's signal
    table does not carry would silently witness nothing and quietly turn a real
    field into NOT_APPLICABLE on every protocol."""
    unknown = sorted({t for tokens in IR_FIELD_WITNESS_SIGNALS.values()
                      for t in tokens} - set(ALL_AMBA_SIGNAL_NAMES))
    if unknown:
        raise AmbaTransactionIrError("IR_WITNESS_SIGNAL_UNKNOWN_TO_CONNECTIVITY", {
            "signals": unknown,
            "hint": "connectivity.py holds the repo's only AMBA signal table; add the "
                    "signal there rather than naming one here that nothing else knows"})


def _assert_join_columns_exist() -> None:
    missing = sorted(set(IR_REGISTRY_JOIN_COLUMN.values()) - set(AMBA_PORT_REGISTRY_FIELDS))
    if missing:
        raise AmbaTransactionIrError("IR_JOIN_COLUMN_NOT_IN_PORT_REGISTRY", {
            "columns": missing,
            "hint": "an IR field may only join a real AMBA_PORT_REGISTRY column; a renamed "
                    "column must be renamed here too, not silently read as empty"})


def _assert_every_field_has_an_origin() -> None:
    missing = [f for f in AMBA_TRANSACTION_IR_FIELDS if f not in IR_FIELD_ORIGIN]
    if missing:
        raise AmbaTransactionIrError("IR_FIELD_WITHOUT_ORIGIN", {"fields": missing})


_assert_witness_tokens_known()
_assert_join_columns_exist()
_assert_every_field_has_an_origin()


def protocol_signal_vocabulary(protocol: str) -> frozenset:
    """Every AMBA signal one of the ten AMBA-4 protocols carries -- the
    fingerprint's REQUIRED signals plus its family's optional ones.

    Returns an empty set for a protocol outside `AMBA4_PROTOCOLS` (including
    `AMBA_PROTOCOL_UNRESOLVED`); callers must treat an empty vocabulary as
    "undecided", never as "carries nothing"."""
    if protocol not in AMBA4_PROTOCOLS:
        return frozenset()
    optional = _FAMILY_OPTIONAL_SIGNALS.get(AMBA_PROTOCOL_FAMILY.get(protocol), frozenset())
    return frozenset(PROTOCOL_FINGERPRINTS[protocol]) | frozenset(optional)


def ir_field_applicability(protocol: str) -> dict:
    """Per-field applicability for one protocol: `{field: {status, witnesses,
    reason}}`, covering every one of SYOSCB-10's fields."""
    vocabulary = protocol_signal_vocabulary(protocol)
    resolved = protocol in AMBA4_PROTOCOLS
    out: dict = {}
    for field in AMBA_TRANSACTION_IR_FIELDS:
        witnesses = IR_FIELD_WITNESS_SIGNALS.get(field)
        if witnesses is None:
            out[field] = {
                "status": IR_FIELD_APPLICABLE, "witnesses": [],
                "reason": "protocol-independent: describes the transfer or its provenance, "
                          "not a bus signal"}
            continue
        if not resolved:
            out[field] = {
                "status": IR_FIELD_APPLICABILITY_UNKNOWN, "witnesses": [],
                "reason": f"protocol {protocol!r} is not one of the ten AMBA-4 "
                          f"classifications, so this field's applicability is undecided"}
            continue
        found = sorted(witnesses & vocabulary)
        if found:
            out[field] = {"status": IR_FIELD_APPLICABLE, "witnesses": found,
                          "reason": f"{protocol} carries {', '.join(found)}"}
        else:
            out[field] = {
                "status": IR_FIELD_NOT_APPLICABLE, "witnesses": [],
                "reason": f"{protocol} carries none of {', '.join(sorted(witnesses))}"}
    return out


# ===========================================================================
# One IR template per registry port
# ===========================================================================

#: The port is where an external MASTER drives the fabric, so a transaction
#: observed here has this port as its master side.
IR_OBSERVED_AT_MASTER_SIDE = "MASTER_SIDE"
#: The port drives an external SLAVE; a transaction observed here has this port
#: as its slave side.
IR_OBSERVED_AT_SLAVE_SIDE = "SLAVE_SIDE"
#: Neither the endpoint's own role nor the fabric-side role settled which side
#: of a transaction this port observes.
IR_OBSERVATION_POINT_UNRESOLVED = "OBSERVATION_POINT_UNRESOLVED"

#: What a field holds when the party that fills it does not exist yet. Real
#: values, never blanks: an empty cell in a review artifact reads as an
#: oversight, and these three are each a different, citable reason.
IR_VALUE_ADAPTER_RUNTIME = "RUNTIME_VALUE_FROM_PROTOCOL_ADAPTER"
IR_VALUE_PREDICTOR_DERIVED = "AWAITING_ROUTE_TRANSFORM_PREDICTOR"
IR_VALUE_NOT_APPLICABLE = IR_FIELD_NOT_APPLICABLE


def observation_point(row: dict) -> str:
    """Which side of a transaction a monitor at this port observes.

    Uses the SAME precedence `amba_port_registry.registry_endpoints()` uses --
    the endpoint's own AMBA-5 role first, the fabric-side role as fallback --
    because the two are opposite perspectives on one link, not independent
    facts. A parent row of a multiple-destination port observes nothing of its
    own; its branch rows carry the real endpoints."""
    if row.get("vip_bind_hierarchy") == MULTIPLE_BRANCH_PARENT_BIND:
        return IR_OBSERVATION_POINT_UNRESOLVED
    role = row.get("endpoint_role")
    if role == EXTERNAL_ENDPOINT_MASTER:
        return IR_OBSERVED_AT_MASTER_SIDE
    if role == EXTERNAL_ENDPOINT_SLAVE:
        return IR_OBSERVED_AT_SLAVE_SIDE
    if row.get("fabric_role") == FABRIC_SIDE_SLAVE_INTERFACE:
        return IR_OBSERVED_AT_MASTER_SIDE
    if row.get("fabric_role") == FABRIC_SIDE_MASTER_INTERFACE:
        return IR_OBSERVED_AT_SLAVE_SIDE
    return IR_OBSERVATION_POINT_UNRESOLVED


def _established_hierarchy(row: dict):
    """The row's endpoint path, or None when the trace never established one.

    `amba_port_registry` already refuses to put a last-known path in
    `endpoint_hierarchy`; this only has to respect that refusal rather than
    reach around it for `last_known_hierarchy`."""
    path = row.get("endpoint_hierarchy")
    if not path or path == ENDPOINT_HIERARCHY_NOT_ESTABLISHED:
        return None
    return path


def _near_far(point: str, near_value, near_reason: str, far_field: str):
    """The (near-side, far-side) pair for a field whose two ends are the two
    ports of one transaction. The near side is known at the observation point;
    the far side is a ROUTING decision and belongs to the SYOSCB-12
    predictor."""
    near = ({"value": near_value, "evidence": [near_reason]} if near_value is not None
            else {"value": REQUIRED_HUMAN_INPUT,
                  "evidence": [near_reason + " -- not established by the trace"]})
    far = {"value": IR_VALUE_PREDICTOR_DERIVED,
           "evidence": [f"{far_field} is the far end of the route; SYOSCB-12 route "
                        f"prediction owns it and is NEVER_BUILT today"]}
    if point == IR_OBSERVED_AT_MASTER_SIDE:
        return near, far
    if point == IR_OBSERVED_AT_SLAVE_SIDE:
        return far, near
    unresolved = {"value": REQUIRED_HUMAN_INPUT,
                  "evidence": ["observation point unresolved: neither endpoint_role nor "
                               "fabric_role settled which side of a transaction this port "
                               "observes"]}
    return dict(unresolved), dict(unresolved)


def build_transaction_ir_template(row: dict) -> dict:
    """One SYOSCB-10 IR template for one AMBA_PORT_REGISTRY row.

    A TEMPLATE, not a transaction: it says, per field, who fills it and with
    what -- a registry column joined by name, a runtime value the Phase-2
    adapter must supply, a predictor output that does not exist yet, or
    `REQUIRED_HUMAN_INPUT` where the registry itself never settled the fact."""
    protocol = row.get("protocol") or REQUIRED_HUMAN_INPUT
    port_id = row.get("port_id") or REQUIRED_HUMAN_INPUT
    point = observation_point(row)
    applicability = ir_field_applicability(protocol)
    hierarchy = _established_hierarchy(row)

    master_port, slave_port = _near_far(
        point, port_id if port_id != REQUIRED_HUMAN_INPUT else None,
        f"AMBA_PORT_REGISTRY {port_id}.port_id at the {point}", "the opposite port id")
    source_hier, dest_hier = _near_far(
        point, hierarchy,
        f"AMBA_PORT_REGISTRY {port_id}.endpoint_hierarchy", "the opposite endpoint hierarchy")

    clock = row.get("clock")
    if not clock or clock == BIND_CHECK_UNKNOWN_VALUE:
        clock_entry = {"value": REQUIRED_HUMAN_INPUT,
                       "evidence": [f"AMBA_PORT_REGISTRY {port_id}.clock is "
                                    f"{BIND_CHECK_UNKNOWN_VALUE}; AMBA-15 point 6 never "
                                    f"established this port's clock"]}
    else:
        clock_entry = {"value": clock,
                       "evidence": [f"AMBA_PORT_REGISTRY {port_id}.clock"]}

    joined = {
        "protocol": ({"value": protocol,
                      "evidence": [f"AMBA_PORT_REGISTRY {port_id}.protocol"]}
                     if protocol in AMBA4_PROTOCOLS else
                     {"value": REQUIRED_HUMAN_INPUT,
                      "evidence": [f"AMBA_PORT_REGISTRY {port_id}.protocol is {protocol!r}, "
                                   f"not one of the ten AMBA-4 classifications"]}),
        "master_port_id": master_port,
        "slave_port_id": slave_port,
        "source_hierarchy": source_hier,
        "destination_hierarchy": dest_hier,
        "clock_domain": clock_entry,
        "source_evidence": {"value": list(row.get("source_evidence") or []),
                            "evidence": [f"AMBA_PORT_REGISTRY {port_id}.source_evidence, "
                                         f"reused verbatim rather than re-worded"]},
    }

    fields: dict = {}
    for field in AMBA_TRANSACTION_IR_FIELDS:
        origin = IR_FIELD_ORIGIN[field]
        applies = applicability[field]
        if applies["status"] == IR_FIELD_NOT_APPLICABLE:
            entry = {"value": IR_VALUE_NOT_APPLICABLE, "evidence": [applies["reason"]]}
        elif applies["status"] == IR_FIELD_APPLICABILITY_UNKNOWN:
            # The protocol never resolved, so whether this field exists at all
            # is undecided. Handing it a runtime sentinel would invite an
            # adapter to populate a field the bus may not have -- the exact
            # forcing SYOSCB-10 forbids -- so it goes to a human instead.
            entry = {"value": REQUIRED_HUMAN_INPUT, "evidence": [applies["reason"]]}
        elif origin == IR_ORIGIN_PORT_REGISTRY:
            entry = dict(joined[field])
        elif origin == IR_ORIGIN_ADAPTER_RUNTIME:
            entry = {"value": IR_VALUE_ADAPTER_RUNTIME,
                     "evidence": [f"per-transaction runtime value; the {protocol} adapter "
                                  f"populates it (SYOSCB-9, Phase-2)"]}
        else:
            entry = {"value": IR_VALUE_PREDICTOR_DERIVED,
                     "evidence": ["SYOSCB-12 route/transform predictor owns this field; "
                                  "no code in this repo computes one today"]}
        fields[field] = {"origin": origin, "applicability": applies["status"],
                         "applicability_reason": applies["reason"],
                         "witnesses": list(applies["witnesses"]), **entry}

    template = {
        "port_id": port_id,
        "protocol": protocol,
        "observation_point": point,
        "fields": fields,
        # Join keys back to the artifacts this template was built from, so a
        # reviewer can walk template -> registry row -> AMBA-16 matrix row.
        "row_id": row.get("row_id"),
        "fabric_port": row.get("fabric_port"),
    }
    template["unresolved_fields"] = unresolved_ir_fields(template)
    return template


def build_transaction_ir_templates(rows) -> list:
    """One template per registry row, validated before it is returned."""
    templates = [build_transaction_ir_template(r) for r in rows or ()]
    assert_ir_templates_complete(templates)
    for template in templates:
        assert_no_inapplicable_field_forced(template)
    return templates


def unresolved_ir_fields(template: dict) -> list:
    """The IR fields still holding `REQUIRED_HUMAN_INPUT` -- i.e. the ones the
    AMBA_PORT_REGISTRY genuinely never settled.

    Deliberately NOT the runtime/predictor sentinels: those are fields with a
    known owner who has not run yet, which is a different thing from a fact
    discovery failed to establish and a human must supply."""
    return sorted(f for f, entry in (template.get("fields") or {}).items()
                  if entry.get("value") == REQUIRED_HUMAN_INPUT)


def assert_ir_templates_complete(templates) -> None:
    """Every one of SYOSCB-10's fields present on every template, each with an
    origin, an applicability status and a value. An absent key is how a
    downstream consumer ends up defaulting a field nobody decided."""
    for template in templates or ():
        fields = template.get("fields") or {}
        missing = [f for f in AMBA_TRANSACTION_IR_FIELDS if f not in fields]
        if missing:
            raise AmbaTransactionIrError("IR_TEMPLATE_INCOMPLETE", {
                "port_id": template.get("port_id"), "missing_fields": missing})
        for field, entry in fields.items():
            blank = [k for k in ("origin", "applicability", "value")
                     if entry.get(k) in (None, "")]
            if blank:
                raise AmbaTransactionIrError("IR_FIELD_ENTRY_INCOMPLETE", {
                    "port_id": template.get("port_id"), "field": field,
                    "missing_keys": blank,
                    "hint": "use the explicit REQUIRED_HUMAN_INPUT / runtime / predictor "
                            "sentinels rather than leaving a key empty"})


def assert_no_inapplicable_field_forced(template: dict) -> None:
    """SYOSCB-10: "Do not force protocol-inapplicable fields."

    A field this protocol does not have must hold `NOT_APPLICABLE_FOR_PROTOCOL`
    and nothing else -- not a runtime sentinel that invites an adapter to fill
    it, and not a plausible zero."""
    offenders = [
        {"field": f, "value": e.get("value"), "reason": e.get("applicability_reason")}
        for f, e in (template.get("fields") or {}).items()
        if e.get("applicability") == IR_FIELD_NOT_APPLICABLE
        and e.get("value") != IR_VALUE_NOT_APPLICABLE]
    if offenders:
        raise AmbaTransactionIrError("IR_INAPPLICABLE_FIELD_FORCED", {
            "port_id": template.get("port_id"), "protocol": template.get("protocol"),
            "fields": offenders,
            "hint": "SYOSCB-10 forbids forcing a field the protocol does not carry; leave "
                    "it at NOT_APPLICABLE_FOR_PROTOCOL"})


# ===========================================================================
# SYOSCB-9: the adapter-layer plan
# ===========================================================================

ADAPTER_VERDICT_REUSE = "REUSE_EXISTING_ADAPTER"
ADAPTER_VERDICT_ENHANCE = "ENHANCE_EXISTING_ADAPTER"
ADAPTER_VERDICT_ADD = "ADD_NEW_ADAPTER"
#: SYOSCB-9's "Search existing L5/VIP adapters first" has not been performed.
#: Distinct from ADD on purpose -- see the module docstring.
ADAPTER_VERDICT_SEARCH_NOT_PERFORMED = REQUIRED_HUMAN_INPUT

#: The upstream API a Phase-2 adapter's output must eventually reach, cited from
#: the real read-only source rather than restated as code. Named here so the
#: plan says what shape the adapter's product has to be: SyoSil ingests a
#: `uvm_sequence_item`, so the IR above is the FIELD CONTRACT such an item must
#: satisfy, not a replacement for it.
SYOSIL_INGEST_BOUNDARY = (
    "cl_syoscb::add_item(queue_name, producer, uvm_sequence_item) "
    "-- uvm_syoscb-1.0.2.4 src/cl_syoscb.svh:58; the item is wrapped by "
    "cl_syoscb_item (src/cl_syoscb_item.svh:22) and delivered through "
    "cl_syoscb_subscriber::write() (src/cl_syoscb_subscriber.svh:42)")


def _adapter_id(protocol: str) -> str:
    return f"{protocol}_TRANSACTION_ADAPTER"


def discovered_protocols(rows) -> list:
    """Every protocol the AMBA_PORT_REGISTRY really carries, in AMBA-4's own
    order. An unresolved-protocol row contributes nothing: SYOSCB-8 forbids
    supporting a protocol on no evidence, and "unresolved" is not evidence of
    any particular one."""
    present = {r.get("protocol") for r in rows or ()}
    return [p for p in AMBA4_PROTOCOLS if p in present]


def plan_amba_adapters(rows, existing_adapters=None) -> list:
    """SYOSCB-9's adapter plan: one entry per protocol the registry really
    carries.

    `existing_adapters` is the result of SYOSCB-9's mandated search, as
    `[{"protocol", "identifier", "evidence", "covers_ir_fields"}]`. Pass `None`
    when no search has been performed -- the verdict is then
    `REQUIRED_HUMAN_INPUT`, never `ADD`, because "nobody looked" must not read
    as "there is nothing to reuse"."""
    by_protocol: dict = {}
    for adapter in existing_adapters or ():
        by_protocol.setdefault(adapter.get("protocol"), []).append(adapter)

    plans: list = []
    for protocol in discovered_protocols(rows):
        ports = [r for r in rows if r.get("protocol") == protocol]
        applicability = ir_field_applicability(protocol)
        applicable = [f for f in AMBA_TRANSACTION_IR_FIELDS
                      if applicability[f]["status"] == IR_FIELD_APPLICABLE]
        populate = [f for f in applicable
                    if IR_FIELD_ORIGIN[f] == IR_ORIGIN_ADAPTER_RUNTIME]
        joined = [f for f in applicable if IR_FIELD_ORIGIN[f] == IR_ORIGIN_PORT_REGISTRY]
        predicted = [f for f in applicable
                     if IR_FIELD_ORIGIN[f] == IR_ORIGIN_ROUTE_PREDICTOR]
        inapplicable = [f for f in AMBA_TRANSACTION_IR_FIELDS
                        if applicability[f]["status"] == IR_FIELD_NOT_APPLICABLE]

        candidates = by_protocol.get(protocol, [])
        if existing_adapters is None:
            verdict = ADAPTER_VERDICT_SEARCH_NOT_PERFORMED
            rationale = ("SYOSCB-9 requires searching existing L5/VIP adapters first; no "
                         "search result was supplied, so REUSE/ENHANCE/ADD is undecided")
            reuse_evidence: list = []
        elif not candidates:
            verdict = ADAPTER_VERDICT_ADD
            rationale = (f"a real search covering {len(existing_adapters)} existing "
                         f"adapter(s) found none accepting {protocol}")
            reuse_evidence = []
        else:
            covered = set()
            for adapter in candidates:
                covered |= set(adapter.get("covers_ir_fields") or ())
            gap = [f for f in populate if f not in covered]
            verdict = ADAPTER_VERDICT_ENHANCE if gap else ADAPTER_VERDICT_REUSE
            rationale = (f"existing adapter(s) "
                         f"{', '.join(str(a.get('identifier')) for a in candidates)} accept "
                         f"{protocol}" + (f" but populate none of {gap}" if gap else
                                          " and populate every runtime IR field"))
            reuse_evidence = [str(a.get("evidence")) for a in candidates if a.get("evidence")]

        plans.append({
            "adapter_id": _adapter_id(protocol),
            "protocol": protocol,
            "display_name": AMBA4_DISPLAY_NAMES[protocol],
            "port_ids": [r.get("port_id") for r in ports],
            "verdict": verdict,
            "rationale": rationale,
            "reuse_evidence": reuse_evidence,
            "ir_fields_to_populate": populate,
            "ir_fields_joined_from_registry": joined,
            "ir_fields_from_predictor": predicted,
            "ir_fields_not_applicable": inapplicable,
            "syosil_ingest_boundary": SYOSIL_INGEST_BOUNDARY,
            "implementation_status": "PHASE_2_ONLY_NO_SV_EMITTED_HERE",
        })
    return plans


def assert_no_adapter_for_absent_protocol(plans, rows) -> None:
    """SYOSCB-8: "Do not instantiate support for nonexistent protocols merely
    because the framework can model them." An adapter planned for a protocol no
    discovered port speaks is exactly that."""
    present = set(discovered_protocols(rows))
    offenders = [p.get("adapter_id") for p in plans or ()
                 if p.get("protocol") not in present]
    if offenders:
        raise AmbaTransactionIrError("ADAPTER_PLANNED_FOR_ABSENT_PROTOCOL", {
            "adapter_ids": sorted(offenders), "protocols_present": sorted(present),
            "hint": "plan an adapter only for a protocol the AMBA_PORT_REGISTRY really "
                    "carries; the framework being able to model one is not evidence"})


def unresolved_adapter_plans(plans) -> list:
    """Adapter entries whose REUSE/ENHANCE/ADD decision is still open."""
    return [p for p in plans or ()
            if p.get("verdict") == ADAPTER_VERDICT_SEARCH_NOT_PERFORMED]


# ===========================================================================
# Reporting
# ===========================================================================

def render_ir_field_contract(protocol: str) -> str:
    """SYOSCB-10's field list for one protocol, with each field's owner and its
    applicability derived from that protocol's real signal vocabulary."""
    applicability = ir_field_applicability(protocol)
    rows = [{"field": f,
             "origin": IR_FIELD_ORIGIN[f],
             "registry_column": IR_REGISTRY_JOIN_COLUMN.get(f, "-"),
             "applicability": applicability[f]["status"],
             "basis": applicability[f]["reason"]}
            for f in AMBA_TRANSACTION_IR_FIELDS]
    return render_markdown_table(
        [("field", "IR Field"), ("origin", "Filled By"),
         ("registry_column", "AMBA_PORT_REGISTRY Column"),
         ("applicability", "Applicability"), ("basis", "Basis")], rows)


def render_ir_template_table(templates) -> str:
    rows = [{"port_id": t["port_id"], "protocol": t["protocol"],
             "observation_point": t["observation_point"],
             "unresolved": ", ".join(t["unresolved_fields"]) or "(none)"}
            for t in templates or ()]
    return render_markdown_table(
        [("port_id", "port_id"), ("protocol", "protocol"),
         ("observation_point", "Observed Side"),
         ("unresolved", "Fields Still REQUIRED_HUMAN_INPUT")], rows,
        empty_note="(no registry row, so no IR template)")


def render_adapter_plan_table(plans) -> str:
    rows = [{"adapter_id": p["adapter_id"], "display_name": p["display_name"],
             "port_ids": ", ".join(p["port_ids"]),
             "verdict": p["verdict"],
             "populate": ", ".join(p["ir_fields_to_populate"]),
             "not_applicable": ", ".join(p["ir_fields_not_applicable"]) or "(none)"}
            for p in plans or ()]
    return render_markdown_table(
        [("adapter_id", "Adapter"), ("display_name", "Protocol"),
         ("port_ids", "Ports Served"), ("verdict", "REUSE / ENHANCE / ADD"),
         ("populate", "IR Fields It Must Populate"),
         ("not_applicable", "Fields It Must NOT Force")], rows,
        empty_note="(no AMBA-4 protocol resolved on any port, so no adapter is planned)")


def render_amba_transaction_ir_report(templates, plans) -> str:
    """The SYOSCB-9 / SYOSCB-10 review artifact.

    Self-checked against both emission gates, for the reason SYOSCB-33 exists:
    a Phase-1 planning document that rendered compilable SystemVerilog would be
    a way past the approval gate that stands between this plan and any code."""
    protocols = sorted({t["protocol"] for t in templates or ()
                        if t["protocol"] in AMBA4_PROTOCOLS})
    unresolved = [t for t in templates or () if t["unresolved_fields"]]
    open_adapters = unresolved_adapter_plans(plans)

    lines = ["# SYOSCB-9 / SYOSCB-10 AMBA Transaction IR and Adapter Plan", "",
             f"{len(templates or ())} IR template(s), one per AMBA_PORT_REGISTRY row; "
             f"{len(plans or ())} adapter(s) planned for the "
             f"{len(protocols)} AMBA-4 protocol(s) actually discovered "
             f"({', '.join(AMBA4_DISPLAY_NAMES[p] for p in protocols) or 'none'}).", "",
             "## IR templates per port", "", render_ir_template_table(templates), "",
             "## Adapter plan (SYOSCB-9)", "", render_adapter_plan_table(plans), ""]
    for protocol in protocols:
        lines += [f"## IR field contract -- {AMBA4_DISPLAY_NAMES[protocol]}", "",
                  render_ir_field_contract(protocol), ""]
    if unresolved:
        lines += ["## Ports whose IR cannot be completed from discovery alone", "",
                  render_markdown_table(
                      [("port_id", "port_id"), ("fields", "Fields")],
                      [{"port_id": t["port_id"],
                        "fields": ", ".join(t["unresolved_fields"])} for t in unresolved]),
                  ""]
    if open_adapters:
        lines += ["## Adapters whose REUSE/ENHANCE/ADD decision is still open", "",
                  render_markdown_table(
                      [("adapter_id", "Adapter"), ("rationale", "Why")],
                      [{"adapter_id": p["adapter_id"], "rationale": p["rationale"]}
                       for p in open_adapters]), ""]
    lines.append(
        "Phase-1 planning only (SYOSCB-33). No adapter, IR or predictor code is emitted "
        "here; the upstream ingest boundary these adapters would eventually reach is "
        f"{SYOSIL_INGEST_BOUNDARY}, cited read-only and never vendored (SYOSCB-2 / "
        "SYOSCB-34).")
    text = "\n".join(lines)
    assert_no_emittable_sv(text, label="SYOSCB-9/10 IR and adapter plan")
    assert_no_bind_statement(text)
    return text
