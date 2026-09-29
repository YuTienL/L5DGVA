"""dv_harness/amba_route_transform_predictor.py -- SYOSCB-12 (AMBA ROUTE /
TRANSFORM PREDICTOR) and SYOSCB-13 (ADDRESS MAP EVIDENCE), as Phase-1 planning
machinery.

WHAT THIS PREDICTS, AND WHAT IT DELIBERATELY DOES NOT
-----------------------------------------------------
SYOSCB-12 names ten responsibilities. This module answers the STRUCTURAL half
of each one: given the fabric topology discovery already established, does a
route exist, is it legal, and does the topology IMPLY a transform along it --
an ID extension, a data-width conversion, a burst split, a protocol bridge, a
response re-encoding, an ordering domain. It never predicts a per-transaction
value: "this AWADDR becomes that ADDR at the slave port" needs live traffic and
a fabric configuration nobody has read, and SYOSCB-12's own "Do not guess
routing" makes inventing one worse than reporting it missing.

That split is the module's whole contract, so it is a VALUE on every prediction
rather than a sentence in this docstring. `TRANSFORM_PREDICTED_FROM_TOPOLOGY`
and `TRANSFORM_NOT_IMPLIED` are the two structurally-decided outcomes;
`TRANSFORM_RUNTIME_PHASE_2` marks a responsibility whose SHAPE is decided here
and whose per-transaction value is Phase-2 work; `REQUIRED_HUMAN_INPUT` marks a
fact discovery genuinely never established. A caller that collapses the last
two loses exactly the distinction SYOSCB-33/34 is drawn along.

REUSE, NOT A SECOND ALGORITHM
------------------------------
Every computed quantity comes from a primitive that already exists and is
already tested. `compute_id_width()` supplies the fabric-side ID width the
extension is measured against, `compute_address_regions()` supplies the decode
regions, `build_scoreboard_matrix()` (through
`amba_port_registry.project_to_fabric_topology()`) supplies which
(master, slave) pairs are real, `amba_transaction_ir.ir_field_applicability()`
supplies "does this protocol have a burst length / a transaction id / a
response at all" from `connectivity.py`'s spec-fixed signal sets, and
`address_map_verifier.verify_address_map()` supplies SYOSCB-13's whole
three-independent-source method. Nothing here recomputes any of them a second
way, so a prediction cannot disagree with the artifact a human reviewed.

The genuinely new work is the DETECTION layer on top: comparing the two ends of
a route against each other. `compute_id_width()` sizes the interconnect's
output ID field but never said what happens to master m's id; this module turns
that same number into "the fabric prefixes N bits onto SRC_AXI's 4-bit id".

SYOSCB-13: EVIDENCE SUPPORTS, IT NEVER REPLACES
------------------------------------------------
`cross_check_address_map_evidence()` runs the real three-source verifier and
then JOINS its verified bases onto the traced topology.
`assert_address_map_does_not_replace_topology()` makes SYOSCB-13's last line
checkable: an address-map instance naming no traced endpoint is reported as an
unjoined finding and never becomes a slave. Address evidence corroborating a
traced slave is corroboration; address evidence CREATING one would be a
topology claim the address map has no standing to make.

PHASE-1 ONLY (SYOSCB-33 / SYOSCB-34)
------------------------------------
Nothing here emits SystemVerilog, and no prediction is written into
`connectivity.SCOREBOARD_PLAN_FIELDS`. `propose_scoreboard_plan_fields()`
returns PROPOSALS a human confirms through the existing row-lock gate --
`generate_scoreboard_entry()`'s "NEVER computes a default for ANY of the nine
fields" contract is not weakened by a predictor that would quietly compute one.
Every rendered artifact is run through `assert_no_emittable_sv()` and
`assert_no_bind_statement()`.
"""
from __future__ import annotations

from dv_harness.amba_fabric_discovery import (
    BIND_CHECK_UNKNOWN_VALUE,
    MULTIPLE_BRANCH_PARENT_BIND,
    assert_no_bind_statement,
)
from dv_harness.amba_port_registry import (
    ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
    PortRegistryError,
    project_to_fabric_topology,
    registry_endpoints,
)
from dv_harness.amba_transaction_ir import (
    IR_FIELD_APPLICABLE,
    ir_field_applicability,
)
from dv_harness.connectivity import (
    AMBA4_DISPLAY_NAMES,
    AMBA4_PROTOCOLS,
    AMBA_PROTOCOL_FAMILY,
    REQUIRED_HUMAN_INPUT,
    SCOREBOARD_PLAN_FIELDS,
    render_markdown_table,
)
from dv_harness.syoscb_source_audit import (
    ORDERING_IN_ORDER,
    ORDERING_OUT_OF_ORDER,
    assert_no_emittable_sv,
)
from dv_harness.uvm_generator.address_map_verifier import (
    DECODER_AUTHORITY_SOURCE,
    DOC_AUTHORITY_SOURCE,
    doc_disagreement_conflict,
    verify_address_map,
)
from dv_harness.uvm_generator.amba_fabric_generator import compute_id_width


class RouteTransformPredictorError(PortRegistryError):
    """A prediction request the topology cannot support, or a cross-check whose
    address evidence was used to alter the topology it was only meant to
    corroborate. Subclasses `PortRegistryError` so a caller already handling the
    AMBA_PORT_REGISTRY pipeline's errors handles these too."""


# ===========================================================================
# SYOSCB-12's ten responsibilities, and the four outcomes a prediction can have
# ===========================================================================

#: SYOSCB-12's own responsibility list, in the doc's order, as the keys this
#: module answers under. A tuple because it is the contract: predictions are
#: built by iterating it and `assert_predictions_complete()` checks against it,
#: so a responsibility cannot be quietly dropped from either end.
ROUTE_RESPONSIBILITIES: tuple = (
    "master_slave_route",
    "address_decode",
    "address_translation",
    "id_remap",
    "width_conversion",
    "burst_split_merge",
    "bridge_behavior",
    "expected_response",
    "routing_legality",
    "ordering_domain",
)

#: The discovered topology decided this structurally, and the entry carries the
#: numbers and the citations it was decided from.
TRANSFORM_PREDICTED_FROM_TOPOLOGY = "PREDICTED_FROM_TOPOLOGY"
#: The two ends of the route agree, so the topology implies no transform here.
#: A real finding, not an absence: "the widths match" is what tells a scoreboard
#: implementer not to model a conversion.
TRANSFORM_NOT_IMPLIED = "NO_TRANSFORM_IMPLIED"
#: The protocol at one or both ends does not carry this concept at all (a burst
#: length on APB, a transaction id on AHB). Derived from `connectivity.py`'s
#: signal sets through `ir_field_applicability()`, never typed here.
TRANSFORM_NOT_APPLICABLE = "NOT_APPLICABLE_FOR_PROTOCOL"
#: The SHAPE is settled here; the per-transaction VALUE needs live traffic and a
#: real adapter, which is Phase-2 work behind SYOSCB-33's gate. Deliberately not
#: REQUIRED_HUMAN_INPUT: nobody is being asked for anything, the work simply has
#: not been approved yet.
TRANSFORM_RUNTIME_PHASE_2 = "RUNTIME_PREDICTION_PHASE_2"
#: Discovery never established the fact this prediction needs. Reuses
#: `connectivity.REQUIRED_HUMAN_INPUT` so the harness has one sentinel for
#: "a human must supply this", not a second private one.
TRANSFORM_REQUIRED_HUMAN_INPUT = REQUIRED_HUMAN_INPUT

TRANSFORM_STATUS_VALUES: tuple = (
    TRANSFORM_PREDICTED_FROM_TOPOLOGY,
    TRANSFORM_NOT_IMPLIED,
    TRANSFORM_NOT_APPLICABLE,
    TRANSFORM_RUNTIME_PHASE_2,
    TRANSFORM_REQUIRED_HUMAN_INPUT,
)

#: `build_scoreboard_matrix()`'s own two pair statuses, reused rather than
#: restated -- a route's legality IS that matrix cell.
ROUTE_LEGAL = "IMPLEMENTED"
ROUTE_WAIVED = "WAIVED"


def _entry(status: str, value, evidence) -> dict:
    """One responsibility's answer. `evidence` is always a list of citable
    strings, because a prediction with no stated basis is the guess SYOSCB-12
    forbids."""
    if status not in TRANSFORM_STATUS_VALUES:
        raise RouteTransformPredictorError("ROUTE_PREDICTION_UNKNOWN_STATUS", {
            "status": status, "allowed": list(TRANSFORM_STATUS_VALUES)})
    return {"status": status, "value": value,
            "evidence": [str(e) for e in (evidence or [])]}


# ===========================================================================
# Reading widths and protocols off a registry row, without guessing
# ===========================================================================

def registry_width(row: dict, field: str):
    """One of the registry's four width columns as an int, or `None` when the
    column never resolved.

    `None` is the point: `amba_port_registry` fills an unestablished width with
    `BIND_CHECK_UNKNOWN_VALUE`, and every detector below branches on `None` to
    REQUIRED_HUMAN_INPUT rather than substituting a plausible 32/64."""
    raw = (row or {}).get(field)
    if raw in (None, "", BIND_CHECK_UNKNOWN_VALUE, REQUIRED_HUMAN_INPUT):
        return None
    try:
        width = int(str(raw).strip(), 0)
    except (TypeError, ValueError):
        return None
    return width if width > 0 else None


def _protocol(row: dict) -> str:
    protocol = (row or {}).get("protocol")
    return protocol if protocol in AMBA4_PROTOCOLS else REQUIRED_HUMAN_INPUT


def _carries(protocol: str, ir_field: str) -> bool:
    """Does this protocol carry the concept behind an IR field at all?

    Answered through `amba_transaction_ir.ir_field_applicability()`, which
    derives it from `connectivity.py`'s spec-fixed AMBA signal vocabulary.
    Nothing in this file names an AMBA signal, so "APB has no burst" stays a
    consequence of a signal table a human already reviewed rather than a claim
    typed here -- and `test_burst_applicability_comes_from_connectivitys_signal_
    sets_not_from_this_module` keeps it that way."""
    if protocol not in AMBA4_PROTOCOLS:
        return False
    return ir_field_applicability(protocol)[ir_field]["status"] == IR_FIELD_APPLICABLE


def _port_label(row: dict) -> str:
    return str((row or {}).get("port_id") or "PORT_UNIDENTIFIED")


# ===========================================================================
# The transform detectors -- the genuinely new layer
# ===========================================================================

WIDTH_DOWNSIZE = "DOWNSIZE"
WIDTH_UPSIZE = "UPSIZE"


def detect_width_conversion(master_row: dict, slave_row: dict) -> dict:
    """Does the topology imply a data-width conversion along this route?

    Purely structural: the two registry rows' `data_width` columns compared
    against each other. A width AMBA-15 never established yields
    REQUIRED_HUMAN_INPUT -- a conversion silently assumed absent because a width
    was missing is a scoreboard that will never model the beats it should."""
    m_id, s_id = _port_label(master_row), _port_label(slave_row)
    m_w = registry_width(master_row, "data_width")
    s_w = registry_width(slave_row, "data_width")
    unknown = [f"{p}.data_width" for p, w in ((m_id, m_w), (s_id, s_w)) if w is None]
    if unknown:
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
            f"AMBA_PORT_REGISTRY never established {', '.join(unknown)}; a width "
            f"conversion cannot be ruled in or out without both ends"])
    if m_w == s_w:
        return _entry(TRANSFORM_NOT_IMPLIED, {"master_data_width": m_w, "slave_data_width": s_w}, [
            f"{m_id}.data_width == {s_id}.data_width == {m_w}"])
    wide, narrow = max(m_w, s_w), min(m_w, s_w)
    if wide % narrow:
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, {
            "master_data_width": m_w, "slave_data_width": s_w}, [
            f"{m_id}.data_width={m_w} and {s_id}.data_width={s_w} are not an integer "
            f"multiple of each other; AMBA width conversion is defined for integer "
            f"(power-of-two in practice) ratios, so this pair needs a human explanation "
            f"rather than a computed ratio"])
    return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
        "direction": WIDTH_DOWNSIZE if m_w > s_w else WIDTH_UPSIZE,
        "master_data_width": m_w, "slave_data_width": s_w,
        "ratio": wide // narrow}, [
        f"{m_id}.data_width={m_w} vs {s_id}.data_width={s_w}: the interconnect must "
        f"{'downsize' if m_w > s_w else 'upsize'} by {wide // narrow}x"])


BURST_SPLIT = "SPLIT"
BURST_MERGE = "MERGE"
BURST_SPLIT_TO_SINGLE_TRANSFERS = "SPLIT_TO_SINGLE_TRANSFERS"


def detect_burst_split_merge(master_row: dict, slave_row: dict,
                             width_conversion: dict) -> dict:
    """Does the topology imply a burst split or merge?

    Two independent causes, checked in the order they dominate: a destination
    protocol with no burst concept at all forces every beat into its own
    transfer regardless of widths (an AXI4 master behind an APB bridge), and a
    width conversion multiplies or divides the beat count."""
    m_id, s_id = _port_label(master_row), _port_label(slave_row)
    m_proto, s_proto = _protocol(master_row), _protocol(slave_row)
    if REQUIRED_HUMAN_INPUT in (m_proto, s_proto):
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
            "a burst expectation needs a resolved protocol at both ends; "
            f"{m_id}={m_proto}, {s_id}={s_proto}"])
    m_burst, s_burst = _carries(m_proto, "burst_len"), _carries(s_proto, "burst_len")
    if not m_burst and not s_burst:
        return _entry(TRANSFORM_NOT_APPLICABLE, None, [
            f"neither {AMBA4_DISPLAY_NAMES[m_proto]} nor {AMBA4_DISPLAY_NAMES[s_proto]} "
            f"carries a burst length"])
    if m_burst and not s_burst:
        return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
            "kind": BURST_SPLIT_TO_SINGLE_TRANSFERS}, [
            f"{AMBA4_DISPLAY_NAMES[m_proto]} carries a burst length and "
            f"{AMBA4_DISPLAY_NAMES[s_proto]} does not, so one master burst becomes N "
            f"single transfers at {s_id}"])
    if s_burst and not m_burst:
        return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {"kind": BURST_MERGE}, [
            f"{AMBA4_DISPLAY_NAMES[s_proto]} carries a burst length and "
            f"{AMBA4_DISPLAY_NAMES[m_proto]} does not, so single master transfers may "
            f"be presented as a burst at {s_id}"])
    if width_conversion["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT:
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
            "both ends carry a burst length, so the beat count follows the width "
            "conversion -- which is itself unresolved"] + width_conversion["evidence"])
    if width_conversion["status"] == TRANSFORM_NOT_IMPLIED:
        return _entry(TRANSFORM_NOT_IMPLIED, None, [
            f"equal data widths and a burst length on both ends: one {m_id} beat stays "
            f"one {s_id} beat"])
    conv = width_conversion["value"]
    kind = BURST_SPLIT if conv["direction"] == WIDTH_DOWNSIZE else BURST_MERGE
    return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
        "kind": kind, "beat_count_factor": conv["ratio"]}, [
        f"a {conv['ratio']}x {conv['direction'].lower()} between {m_id} and {s_id} "
        f"{'multiplies' if kind == BURST_SPLIT else 'divides'} the beat count by "
        f"{conv['ratio']}"])


def fabric_id_width(master_rows) -> dict:
    """The interconnect's output ID width, from `compute_id_width()`.

    Reused rather than recomputed: that function already encodes
    `W_out = ceil(log2(M)) + max_m(I_m)` and is already tested. A master whose
    `id_width` AMBA-15 never established makes the whole fabric-side width
    undecidable -- so this refuses for the fabric rather than dropping that
    master and computing a smaller, wrong W_out from the rest."""
    if not master_rows:
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
            "no traced master endpoint, so there is no fabric-side ID width to size"])
    unknown = [_port_label(r) for r in master_rows if registry_width(r, "id_width") is None]
    if unknown:
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
            f"AMBA_PORT_REGISTRY never established id_width for {', '.join(sorted(unknown))}; "
            f"dropping them would compute a narrower W_out than the fabric really needs"])
    masters = [{"id": _port_label(r), "id_width": registry_width(r, "id_width")}
               for r in master_rows]
    width = compute_id_width(masters)
    return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
        "fabric_id_width": width,
        "master_id_widths": {m["id"]: m["id_width"] for m in masters}}, [
        f"compute_id_width(): ceil(log2({len(masters)})) + "
        f"max({', '.join(str(m['id_width']) for m in masters)}) = {width}"])


def detect_id_remap(master_row: dict, slave_row: dict, fabric_id: dict) -> dict:
    """Does the topology imply an ID remap or extension along this route?

    `compute_id_width()` sizes the interconnect's output field; this turns that
    same number into the per-route statement it never made -- how many bits the
    fabric prefixes onto THIS master's id, and whether the slave port is narrow
    enough that the fabric must reissue rather than pass the id through."""
    m_id, s_id = _port_label(master_row), _port_label(slave_row)
    m_proto = _protocol(master_row)
    if m_proto == REQUIRED_HUMAN_INPUT:
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
            f"{m_id}'s protocol never resolved, so whether it carries a transaction id "
            f"at all is undecided"])
    if not _carries(m_proto, "transaction_id"):
        return _entry(TRANSFORM_NOT_APPLICABLE, None, [
            f"{AMBA4_DISPLAY_NAMES[m_proto]} carries no transaction id, so there is "
            f"nothing to remap"])
    if fabric_id["status"] != TRANSFORM_PREDICTED_FROM_TOPOLOGY:
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None,
                      ["the fabric-side ID width is undecided, so the extension this "
                       "master's id undergoes cannot be measured"] + fabric_id["evidence"])
    w_out = fabric_id["value"]["fabric_id_width"]
    m_w = registry_width(master_row, "id_width")
    s_w = registry_width(slave_row, "id_width")
    extension = w_out - m_w
    s_carries_id = _carries(_protocol(slave_row), "transaction_id")
    # Three different reasons a slave-side width can be absent, kept apart:
    # the slave protocol has no id at all, the id exists but nobody measured it,
    # or it is a real number. A bare None for the first two would make "APB has
    # no id" and "nobody established AXI's id width" look identical.
    value = {"master_id_width": m_w, "fabric_id_width": w_out,
             "extension_bits": extension,
             "slave_id_width": (s_w if s_w is not None else
                                (REQUIRED_HUMAN_INPUT if s_carries_id
                                 else TRANSFORM_NOT_APPLICABLE))}
    evidence = [f"{m_id}.id_width={m_w} against a fabric-side W_out={w_out}"]
    if s_w is None and s_carries_id:
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, value, evidence + [
            f"{s_id} carries a transaction id but AMBA_PORT_REGISTRY never established "
            f"its id_width, so whether the fabric must reissue at the slave port is "
            f"undecided"])
    if extension > 0:
        return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {**value, "kind": "EXTENSION"},
                      evidence + [
            f"the interconnect prefixes {extension} master-index bit(s) onto every "
            f"{m_id} id, so an id observed at {m_id} and the same transaction's id "
            f"inside the fabric are different values"])
    if s_w is not None and s_w < w_out:
        return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {**value, "kind": "SLAVE_REISSUE"},
                      evidence + [
            f"{s_id}.id_width={s_w} is narrower than the fabric's W_out={w_out}, so the "
            f"interconnect must reissue rather than pass the id through"])
    return _entry(TRANSFORM_NOT_IMPLIED, value, evidence + [
        f"W_out equals {m_id}.id_width and {s_id} is at least as wide, so the id passes "
        f"through unchanged"])


BRIDGE_PROTOCOL_FAMILY = "PROTOCOL_FAMILY_BRIDGE"
BRIDGE_SUB_PROTOCOL = "SUB_PROTOCOL_BRIDGE"


def detect_bridge_behavior(master_row: dict, slave_row: dict) -> dict:
    """Does a bridge sit on this route?

    Structural, from the two ends' protocols alone: a family change (AXI to APB)
    is a protocol bridge, and a sub-protocol change within one family (AXI4 to
    AXI4-Lite) is a feature-downgrade bridge. What the bridge DOES to an
    individual transaction stays Phase-2 -- this only establishes that one is
    there to be modelled."""
    m_id, s_id = _port_label(master_row), _port_label(slave_row)
    m_proto, s_proto = _protocol(master_row), _protocol(slave_row)
    if REQUIRED_HUMAN_INPUT in (m_proto, s_proto):
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
            f"a bridge is a protocol CHANGE, so both ends must be resolved; "
            f"{m_id}={m_proto}, {s_id}={s_proto}"])
    m_fam, s_fam = AMBA_PROTOCOL_FAMILY[m_proto], AMBA_PROTOCOL_FAMILY[s_proto]
    if m_fam != s_fam:
        return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
            "kind": BRIDGE_PROTOCOL_FAMILY,
            "master_protocol": m_proto, "slave_protocol": s_proto}, [
            f"{AMBA4_DISPLAY_NAMES[m_proto]} ({m_fam}) to "
            f"{AMBA4_DISPLAY_NAMES[s_proto]} ({s_fam}) crosses a protocol family, so a "
            f"bridge is on this route"])
    if m_proto != s_proto:
        return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
            "kind": BRIDGE_SUB_PROTOCOL,
            "master_protocol": m_proto, "slave_protocol": s_proto}, [
            f"{AMBA4_DISPLAY_NAMES[m_proto]} to {AMBA4_DISPLAY_NAMES[s_proto]} stays "
            f"inside the {m_fam} family but changes sub-protocol, so features the "
            f"master may use and the slave does not have are dropped or converted"])
    return _entry(TRANSFORM_NOT_IMPLIED, {"master_protocol": m_proto,
                                          "slave_protocol": s_proto}, [
        f"both ends are {AMBA4_DISPLAY_NAMES[m_proto]}, so no bridge is implied"])


def detect_expected_response(master_row: dict, slave_row: dict,
                             decode_error_regions) -> dict:
    """What response behavior the topology implies.

    Two structural facts, and nothing else: whether the two ends carry the same
    response signals (an AXI multi-code response channel against APB's single
    error flag is a re-encoding the scoreboard must model), and whether the
    address map declares a region a decode error is expected from. Which signals
    those are is read from the protocol's own vocabulary, never named here. What
    response a GIVEN transaction gets is runtime evidence."""
    m_id, s_id = _port_label(master_row), _port_label(slave_row)
    m_proto, s_proto = _protocol(master_row), _protocol(slave_row)
    if REQUIRED_HUMAN_INPUT in (m_proto, s_proto):
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
            f"a response expectation needs a resolved protocol at both ends; "
            f"{m_id}={m_proto}, {s_id}={s_proto}"])
    m_resp = ir_field_applicability(m_proto)["response"]
    s_resp = ir_field_applicability(s_proto)["response"]
    decode_error_owners = sorted({r["owner"] for r in (decode_error_regions or ())})
    if (m_resp["status"] != IR_FIELD_APPLICABLE
            and s_resp["status"] != IR_FIELD_APPLICABLE):
        return _entry(TRANSFORM_NOT_APPLICABLE, None, [
            f"neither {AMBA4_DISPLAY_NAMES[m_proto]} nor {AMBA4_DISPLAY_NAMES[s_proto]} "
            f"carries a response channel"])
    value = {"master_response_signals": list(m_resp["witnesses"]),
             "slave_response_signals": list(s_resp["witnesses"]),
             "decode_error_regions_declared": decode_error_owners}
    evidence = [f"{m_id} responds on {', '.join(m_resp['witnesses']) or '(none)'}; "
                f"{s_id} responds on {', '.join(s_resp['witnesses']) or '(none)'}"]
    if decode_error_owners:
        evidence.append(f"the address map declares decode-error region(s) "
                        f"{', '.join(decode_error_owners)}, so an access outside every "
                        f"slave region is expected to be answered with an error rather "
                        f"than dropped")
    if set(m_resp["witnesses"]) != set(s_resp["witnesses"]):
        return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY,
                      {**value, "kind": "RESPONSE_RE_ENCODING"}, evidence + [
            "the two ends encode a response differently, so the bridge's mapping from "
            "the slave's encoding to the master's is part of the expected behavior"])
    return _entry(TRANSFORM_RUNTIME_PHASE_2, value, evidence + [
        "both ends share one response encoding, so the SHAPE is settled; which response "
        "a given transaction receives is runtime evidence a Phase-2 predictor supplies"])


#: The ordering domain a route's transactions must be compared within. Named
#: separately from `syoscb_source_audit.ORDERING_VALUES` because they answer
#: different questions: this is the KEY transactions are grouped by, that is the
#: COMPARE ALGORITHM SyoSil runs inside a group (SYOSCB-17's decision).
ORDERING_DOMAIN_PER_ROUTE = "PER_ROUTE"
ORDERING_DOMAIN_PER_ROUTE_AND_ID = "PER_ROUTE_AND_TRANSACTION_ID"


def detect_ordering_domain(master_row: dict, slave_row: dict) -> dict:
    """The ordering domain this route's transactions live in.

    Structural and narrow on purpose. A protocol carrying a transaction id
    orders responses only WITHIN an id, so the domain key includes it and the
    route as a whole is out-of-order; a protocol with no id is strictly ordered.
    The reorder-window DEPTH is not derived and never will be here -- it is an
    outstanding-transaction configuration nobody discovered, so it is reported as
    REQUIRED_HUMAN_INPUT beside the domain rather than folded into it."""
    m_id, s_id = _port_label(master_row), _port_label(slave_row)
    m_proto = _protocol(master_row)
    if m_proto == REQUIRED_HUMAN_INPUT:
        return _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
            f"{m_id}'s protocol never resolved, so its ordering domain is undecided"])
    if _carries(m_proto, "transaction_id"):
        return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
            "domain_key": ORDERING_DOMAIN_PER_ROUTE_AND_ID,
            "route_ordering_expectation": ORDERING_OUT_OF_ORDER,
            "ordering_tolerance_depth": REQUIRED_HUMAN_INPUT}, [
            f"{AMBA4_DISPLAY_NAMES[m_proto]} carries a transaction id, so ordering "
            f"holds within an id and {m_id}->{s_id} as a whole may complete out of "
            f"order",
            "the reorder-window depth is an outstanding-transaction configuration "
            "discovery never established; SYOSCB-12 forbids guessing it"])
    return _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
        "domain_key": ORDERING_DOMAIN_PER_ROUTE,
        "route_ordering_expectation": ORDERING_IN_ORDER,
        "ordering_tolerance_depth": 0}, [
        f"{AMBA4_DISPLAY_NAMES[m_proto]} carries no transaction id, so every transfer "
        f"on {m_id}->{s_id} completes before the next begins"])


# ===========================================================================
# The per-route prediction
# ===========================================================================

def _rows_by_endpoint(rows) -> dict:
    """Traced endpoint hierarchy -> the registry row that established it.

    Mirrors `registry_endpoints()`'s own exclusions exactly -- an AMBA-11
    second-side row and a multiple-destination parent row establish no endpoint
    of their own -- so this index can never name an endpoint the topology
    projection does not."""
    index: dict = {}
    for row in rows or ():
        if row.get("amba11_second_side"):
            continue
        if row.get("vip_bind_hierarchy") == MULTIPLE_BRANCH_PARENT_BIND:
            continue
        path = row.get("endpoint_hierarchy")
        if not path or path == ENDPOINT_HIERARCHY_NOT_ESTABLISHED:
            continue
        index.setdefault(path, row)
    return index


def _regions_owned_by(regions, owner: str) -> list:
    """The decode regions `compute_address_regions()` assigned to one owner.

    The join key is the region's `owner`, which is the `id` a caller gave in
    `address_map_slaves` -- so an address map whose ids are not the traced
    endpoint hierarchies joins nothing, and the route reports its decode as
    REQUIRED_HUMAN_INPUT rather than silently matching the wrong slave."""
    return [r for r in (regions or ()) if r.get("owner") == owner]


def _addr(value) -> str:
    """Hex for a region bound. `project_to_fabric_topology()` carries the ints
    `compute_address_regions()` computed; an address rendered in decimal in a
    review artifact is one a reviewer has to convert before they can compare it
    with the RTL they are checking it against."""
    return hex(value) if isinstance(value, int) else str(value)


def predict_routes(rows, *, address_map_slaves=None, reserved_regions=None,
                   address_width=None, connectivity=None,
                   assume_full_connectivity: bool = False,
                   address_translations=None) -> list:
    """One SYOSCB-12 prediction per (master, slave) route the topology carries.

    The route set is not enumerated here: `project_to_fabric_topology()` is
    called, which runs `build_scoreboard_matrix()` on the registry's own traced
    endpoints. A pair neither accessible nor explicitly waived-with-evidence
    still raises out of that function, so a route this module reports is one the
    connectivity evidence already resolved.

    `address_translations` is SYOSCB-12's "address translation" evidence, as
    `[{"master", "slave", "kind", "detail", "evidence"}]`. It is an INPUT and
    has no default: whether an interconnect presents a slave the full system
    address or a base-relative offset is a fabric configuration fact, not a
    consequence of the topology, and computing one from the address map would be
    exactly the routing guess SYOSCB-12 forbids. Supply nothing and every route
    reports REQUIRED_HUMAN_INPUT for that responsibility.
    """
    topology = project_to_fabric_topology(
        rows, address_map_slaves=address_map_slaves, reserved_regions=reserved_regions,
        address_width=address_width, connectivity=connectivity,
        assume_full_connectivity=assume_full_connectivity)
    by_endpoint = _rows_by_endpoint(rows)
    master_rows = [by_endpoint[m] for m in topology["masters"] if m in by_endpoint]
    fabric_id = fabric_id_width(master_rows)
    regions = topology["address_map"]
    decode_error_regions = [r for r in regions if r.get("owner_kind") == "DECODE_ERROR"]
    translations = {(t.get("master"), t.get("slave")): t for t in (address_translations or ())}

    predictions: list = []
    for cell in topology["scoreboard_matrix"]:
        m_path, s_path = cell["master_id"], cell["slave_id"]
        m_row = by_endpoint.get(m_path) or {}
        s_row = by_endpoint.get(s_path) or {}
        m_id, s_id = _port_label(m_row), _port_label(s_row)

        legality = (_entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {"pair_status": ROUTE_LEGAL}, [
            f"build_scoreboard_matrix() resolved {m_path} -> {s_path} to IMPLEMENTED "
            f"from real connectivity evidence"])
            if cell["status"] == ROUTE_LEGAL else
            _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
                "pair_status": ROUTE_WAIVED,
                "waiver_evidence": cell.get("waiver_evidence")}, [
                f"build_scoreboard_matrix() resolved {m_path} -> {s_path} to WAIVED: "
                f"{cell.get('waiver_evidence')}",
                "an illegal route is still a prediction: traffic observed on it is a "
                "finding, not a transaction to match"]))

        owned = _regions_owned_by(regions, s_path)
        if owned:
            decode = _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
                "regions": [{"start_addr": _addr(r["start_addr"]),
                             "end_addr": _addr(r["end_addr"])} for r in owned]}, [
                f"compute_address_regions() assigns {s_path} "
                + ", ".join(f"[{_addr(r['start_addr'])}, {_addr(r['end_addr'])})"
                            for r in owned)])
        else:
            decode = _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
                f"no address region is owned by {s_path}; supply SYOSCB-13 address-map "
                f"evidence (see ADDRESS_MAP_EVIDENCE_TYPES) so the decode that selects "
                f"this slave is established rather than assumed"])

        translation_evidence = translations.get((m_path, s_path))
        if translation_evidence:
            translate = _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
                "kind": translation_evidence.get("kind"),
                "detail": translation_evidence.get("detail")},
                [str(translation_evidence.get("evidence") or
                     "address translation supplied with no citation")])
        else:
            translate = _entry(TRANSFORM_REQUIRED_HUMAN_INPUT, None, [
                f"no address-translation evidence was supplied for {m_path} -> {s_path}; "
                f"whether the interconnect presents {s_id} the full system address or a "
                f"base-relative offset is a fabric configuration fact the topology "
                f"cannot imply"])

        width = detect_width_conversion(m_row, s_row)
        prediction = {
            "route_id": f"{m_id}__TO__{s_id}",
            "master_endpoint": m_path,
            "slave_endpoint": s_path,
            "master_port_id": m_id,
            "slave_port_id": s_id,
            "master_protocol": _protocol(m_row),
            "slave_protocol": _protocol(s_row),
            "responsibilities": {
                "master_slave_route": _entry(TRANSFORM_PREDICTED_FROM_TOPOLOGY, {
                    "master_endpoint": m_path, "slave_endpoint": s_path}, [
                    f"AMBA_PORT_REGISTRY rows {m_id} and {s_id}, traced to {m_path} and "
                    f"{s_path}"]),
                "address_decode": decode,
                "address_translation": translate,
                "id_remap": detect_id_remap(m_row, s_row, fabric_id),
                "width_conversion": width,
                "burst_split_merge": detect_burst_split_merge(m_row, s_row, width),
                "bridge_behavior": detect_bridge_behavior(m_row, s_row),
                "expected_response": detect_expected_response(
                    m_row, s_row, decode_error_regions),
                "routing_legality": legality,
                "ordering_domain": detect_ordering_domain(m_row, s_row),
            },
        }
        prediction["unresolved_responsibilities"] = unresolved_responsibilities(prediction)
        predictions.append(prediction)

    assert_predictions_complete(predictions)
    return predictions


def unresolved_responsibilities(prediction: dict) -> list:
    """The responsibilities still waiting on a human.

    Deliberately NOT the NOT_APPLICABLE or RUNTIME_PHASE_2 entries: a concept
    the protocol does not have, and one whose owner simply has not been approved
    to run yet, are both settled facts. Only REQUIRED_HUMAN_INPUT is an open
    question somebody must answer."""
    return sorted(name for name, entry in (prediction.get("responsibilities") or {}).items()
                  if entry.get("status") == TRANSFORM_REQUIRED_HUMAN_INPUT)


def assert_predictions_complete(predictions) -> None:
    """Every one of SYOSCB-12's ten responsibilities answered on every route,
    each with a legal status and a stated basis. An absent key is how a
    downstream consumer ends up defaulting a transform nobody decided."""
    for prediction in predictions or ():
        answers = prediction.get("responsibilities") or {}
        missing = [r for r in ROUTE_RESPONSIBILITIES if r not in answers]
        if missing:
            raise RouteTransformPredictorError("ROUTE_PREDICTION_INCOMPLETE", {
                "route_id": prediction.get("route_id"), "missing": missing})
        extra = sorted(set(answers) - set(ROUTE_RESPONSIBILITIES))
        if extra:
            raise RouteTransformPredictorError("ROUTE_PREDICTION_UNKNOWN_RESPONSIBILITY", {
                "route_id": prediction.get("route_id"), "responsibilities": extra,
                "hint": "SYOSCB-12 names ten responsibilities; a prediction carrying an "
                        "eleventh is answering a question the doc did not ask"})
        for name, entry in answers.items():
            if entry.get("status") not in TRANSFORM_STATUS_VALUES:
                raise RouteTransformPredictorError("ROUTE_PREDICTION_UNKNOWN_STATUS", {
                    "route_id": prediction.get("route_id"), "responsibility": name,
                    "status": entry.get("status"),
                    "allowed": list(TRANSFORM_STATUS_VALUES)})
            if not entry.get("evidence"):
                raise RouteTransformPredictorError("ROUTE_PREDICTION_WITHOUT_EVIDENCE", {
                    "route_id": prediction.get("route_id"), "responsibility": name,
                    "hint": "SYOSCB-12's 'Do not guess routing' means every answer, "
                            "including a NO_TRANSFORM_IMPLIED one, states what it was "
                            "decided from"})


#: A responsibility whose answer is COMPUTED FROM another responsibility's
#: answer, rather than from the registry directly. Only one such pair exists:
#: a beat count follows the data-width ratio. `id_remap` is not in this table
#: because its input (`fabric_id_width()`) is a fabric-wide quantity, not one of
#: the ten per-route responsibilities -- it carries that dependency inside its
#: own detector instead.
DERIVED_RESPONSIBILITY_INPUTS: dict = {"burst_split_merge": "width_conversion"}


def assert_no_route_guessed(predictions) -> None:
    """No prediction may claim a structurally-decided transform while the answer
    it was computed from is itself REQUIRED_HUMAN_INPUT.

    A derived answer that outlived its own missing input is precisely the guess
    SYOSCB-12 forbids -- and it is the failure mode a detector chain makes easy,
    because the derived detector still has a plausible default to fall back on."""
    for prediction in predictions or ():
        answers = prediction.get("responsibilities") or {}
        for derived, source in DERIVED_RESPONSIBILITY_INPUTS.items():
            if (answers.get(derived, {}).get("status") == TRANSFORM_PREDICTED_FROM_TOPOLOGY
                    and answers.get(source, {}).get("status")
                    == TRANSFORM_REQUIRED_HUMAN_INPUT):
                raise RouteTransformPredictorError("ROUTE_PREDICTION_DERIVED_FROM_UNKNOWN", {
                    "route_id": prediction.get("route_id"),
                    "responsibility": derived, "derived_from": source,
                    "hint": "a derived prediction must inherit its source's "
                            "REQUIRED_HUMAN_INPUT rather than outliving it"})


# ===========================================================================
# Feeding the existing scoreboard-plan schema -- as PROPOSALS
# ===========================================================================

#: Which `connectivity.SCOREBOARD_PLAN_FIELDS` columns a route prediction can
#: inform. Only three: the predictor establishes routes, transforms and an
#: ordering domain, and has nothing to say about legal drops, reset flush or the
#: orphan thresholds. Checked against the real schema at import so a renamed
#: column breaks loudly here rather than proposing into a field that no longer
#: exists.
PREDICTOR_INFORMED_PLAN_FIELDS: tuple = (
    "endpoint_pairs", "ordering", "transformation_rules",
)


def _assert_informed_fields_are_real() -> None:
    unknown = sorted(set(PREDICTOR_INFORMED_PLAN_FIELDS) - set(SCOREBOARD_PLAN_FIELDS))
    if unknown:
        raise RouteTransformPredictorError("PREDICTOR_PLAN_FIELD_NOT_IN_SCHEMA", {
            "fields": unknown,
            "hint": "the predictor extends connectivity.SCOREBOARD_PLAN_FIELDS; it must "
                    "not invent a second scoreboard-plan vocabulary"})


_assert_informed_fields_are_real()


def propose_scoreboard_plan_fields(predictions) -> dict:
    """What the predictions PROPOSE for the existing scoreboard-plan schema.

    Proposals, and the return shape says so on every entry. `connectivity.
    generate_scoreboard_entry()`'s contract is that it never computes a default
    for any of its nine fields, and a predictor that quietly filled `ordering`
    and `transformation_rules` would defeat the row-lock confirm gate rather
    than feed it. Every entry therefore carries `confirmed: False` and the basis
    a human confirms it from -- `unfilled_plan_fields()` still reports the real
    entry's fields as unfilled until somebody answers.
    """
    pairs = [{"source": p["master_endpoint"], "sink": p["slave_endpoint"]}
             for p in predictions or ()
             if p["responsibilities"]["routing_legality"]["value"]["pair_status"]
             == ROUTE_LEGAL]
    orderings = {}
    transforms = []
    for prediction in predictions or ():
        ordering = prediction["responsibilities"]["ordering_domain"]
        if ordering["status"] == TRANSFORM_PREDICTED_FROM_TOPOLOGY:
            orderings[prediction["route_id"]] = {
                "route_ordering_expectation": ordering["value"]["route_ordering_expectation"],
                "domain_key": ordering["value"]["domain_key"],
                "ordering_tolerance_depth": ordering["value"]["ordering_tolerance_depth"],
                "basis": ordering["evidence"],
            }
        for name in ("address_translation", "id_remap", "width_conversion",
                     "burst_split_merge", "bridge_behavior", "expected_response"):
            entry = prediction["responsibilities"][name]
            if entry["status"] != TRANSFORM_PREDICTED_FROM_TOPOLOGY:
                continue
            transforms.append({"route_id": prediction["route_id"], "transform": name,
                               "value": entry["value"], "basis": entry["evidence"]})
    return {
        "endpoint_pairs": {"proposal": pairs, "confirmed": False,
                           "basis": "routes build_scoreboard_matrix() resolved to "
                                    "IMPLEMENTED from real connectivity evidence"},
        "ordering": {"proposal": orderings, "confirmed": False,
                     "basis": "structural ordering domain per route; the compare "
                              "ALGORITHM is SYOSCB-17's separate decision"},
        "transformation_rules": {"proposal": transforms, "confirmed": False,
                                 "basis": "transforms the discovered topology implies; "
                                          "each carries the numbers it was derived from"},
    }


def assert_plan_proposals_are_not_confirmations(proposals: dict) -> None:
    """A proposal that marked itself confirmed would be the predictor answering
    the row-lock gate on the human's behalf."""
    claimed = sorted(f for f, entry in (proposals or {}).items() if entry.get("confirmed"))
    if claimed:
        raise RouteTransformPredictorError("PREDICTOR_PROPOSAL_CLAIMS_CONFIRMATION", {
            "fields": claimed,
            "hint": "only a human answering the question queue confirms a "
                    "SCOREBOARD_PLAN_FIELDS value; a predictor proposes"})


# ===========================================================================
# SYOSCB-13: address map evidence
# ===========================================================================

#: SYOSCB-13's seven possible evidence types, each mapped to the
#: `verify_address_map()` argument it is supplied through and to its level in
#: `source_authority.AUTHORITY_ORDER`. Written as a table because the doc's own
#: "Prefer direct implementation evidence when sources conflict" is then a
#: mechanical comparison of two ranks rather than a judgment: an RTL decoder
#: (tier 3) beats a specification (tier 6), always, in the same order the rest of
#: this harness already resolves conflicts by.
#:
#: `fabric generated configuration` and `firmware headers` have no purpose-built
#: parser in this repo -- they are supplied through the generic
#: `register_doc_entries` slot, which takes any `{instance, base, doc_ref}`. That
#: is a naming gap and is recorded as one here rather than left for a reader to
#: discover by finding no parser.
ADDRESS_MAP_EVIDENCE_TYPES: tuple = (
    {"evidence_type": "fabric RTL decoder",
     "verifier_argument": "decoder_entries",
     "authority_source": DECODER_AUTHORITY_SOURCE,
     "ingestion": "PURPOSE_BUILT",
     "note": "the address comparator itself, cited file:line -- verify_address_map()'s "
             "mandatory primary source"},
    {"evidence_type": "fabric generated configuration",
     "verifier_argument": "register_doc_entries",
     "authority_source": "controller_doc",
     "ingestion": "GENERIC_DOC_SLOT",
     "note": "no purpose-built parser exists; supplied as a generic doc entry"},
    {"evidence_type": "address-map package",
     "verifier_argument": "register_doc_entries",
     "authority_source": "register_file",
     "ingestion": "GENERIC_DOC_SLOT",
     "note": "a machine-readable package outranks a written document; pass "
             "doc_source='register_file' to escalate_doc_disagreements() so the "
             "conflict is ranked at its real tier"},
    {"evidence_type": "CSR database",
     "verifier_argument": "register_doc_entries",
     "authority_source": "register_file",
     "ingestion": "GENERIC_DOC_SLOT",
     "note": "same tier as an address-map package, for the same reason"},
    {"evidence_type": "firmware headers",
     "verifier_argument": "register_doc_entries",
     "authority_source": "controller_doc",
     "ingestion": "GENERIC_DOC_SLOT",
     "note": "no purpose-built parser exists; supplied as a generic doc entry"},
    {"evidence_type": "specification",
     "verifier_argument": "register_doc_entries",
     "authority_source": DOC_AUTHORITY_SOURCE,
     "ingestion": "GENERIC_DOC_SLOT",
     "note": "corroboration only -- verify_address_map()'s source 3, which never decides"},
    {"evidence_type": "existing verification configuration",
     "verifier_argument": "bfm_access_histogram",
     "authority_source": "reference_command_txt",
     "ingestion": "PURPOSE_BUILT",
     "note": "the BFM access histogram -- verify_address_map()'s mandatory source 2, "
             "which refuses a decoder base no pattern exercises"},
)


def _assert_evidence_authority_sources_known() -> None:
    """Every evidence type must name a source `source_authority` really knows.
    Runs at import: a typo would silently make an evidence type unrankable, and
    SYOSCB-13's "prefer direct implementation evidence" is exactly a ranking."""
    from dv_harness import source_authority as sa

    unknown = []
    for spec in ADDRESS_MAP_EVIDENCE_TYPES:
        try:
            sa.authority_source(spec["authority_source"])
        except sa.SourceAuthorityError:
            unknown.append(spec["evidence_type"])
    if unknown:
        raise RouteTransformPredictorError("ADDRESS_MAP_EVIDENCE_SOURCE_UNKNOWN", {
            "evidence_types": unknown,
            "hint": "name a source source_authority.AUTHORITY_ORDER already carries "
                    "rather than a private label only this module understands"})


_assert_evidence_authority_sources_known()

ADDRESS_EVIDENCE_CORROBORATES = "CORROBORATES_TRACED_SLAVE"
#: The traced slave is real; nobody supplied an address for it. The topology is
#: unaffected -- this is a decode gap, not a topology gap.
ADDRESS_EVIDENCE_MISSING = "NO_ADDRESS_EVIDENCE_FOR_TRACED_SLAVE"
#: The address evidence names something the trace never established as an
#: endpoint. Reported, never joined: see
#: `assert_address_map_does_not_replace_topology()`.
ADDRESS_EVIDENCE_UNJOINED = "ADDRESS_MAP_INSTANCE_NOT_IN_TOPOLOGY"


def cross_check_address_map_evidence(rows, decoder_entries, bfm_access_histogram, *,
                                     register_doc_entries=None, question_store=None,
                                     endpoint_of_instance=None) -> dict:
    """SYOSCB-13, by running the real three-source verifier and joining its
    result onto the traced topology.

    `verify_address_map()` is called directly -- its decoder/histogram/document
    method, its refusal of a zero-access base, its DISAGREES recording and its
    optional question-queue escalation are reused whole, not reimplemented. This
    function adds only the join SYOSCB-13 asks for on top: which traced slave
    each verified base belongs to.

    `endpoint_of_instance` maps a verifier `instance` name to the traced endpoint
    hierarchy it is. Without it the join is exact string equality, and a verified
    entry that matches nothing is reported as `ADDRESS_EVIDENCE_UNJOINED` rather
    than silently becoming a new slave.
    """
    verified = verify_address_map(decoder_entries, bfm_access_histogram,
                                 register_doc_entries, question_store)
    endpoints = registry_endpoints(rows)
    traced_slaves = list(endpoints["slaves"])
    mapping = dict(endpoint_of_instance or {})

    joined: dict = {}
    unjoined: list = []
    for entry in verified:
        endpoint = mapping.get(entry["instance"], entry["instance"])
        if endpoint in traced_slaves:
            joined.setdefault(endpoint, []).append(entry)
        else:
            unjoined.append({"instance": entry["instance"], "base_hex": entry["base_hex"],
                             "resolved_endpoint": endpoint,
                             "decoder_evidence": entry["decoder_evidence"],
                             "status": ADDRESS_EVIDENCE_UNJOINED})

    per_slave = []
    for slave in traced_slaves:
        entries = joined.get(slave) or []
        per_slave.append({
            "slave_endpoint": slave,
            "status": ADDRESS_EVIDENCE_CORROBORATES if entries else ADDRESS_EVIDENCE_MISSING,
            "verified_entries": entries,
            "doc_statuses": sorted({e["doc_status"] for e in entries}),
        })

    return {
        "traced_slaves": traced_slaves,
        "per_slave": per_slave,
        "unjoined_address_evidence": unjoined,
        "verified_entries": verified,
        "slaves_without_address_evidence": [s["slave_endpoint"] for s in per_slave
                                            if s["status"] == ADDRESS_EVIDENCE_MISSING],
    }


def assert_address_map_does_not_replace_topology(cross_check: dict, rows) -> None:
    """SYOSCB-13: "Address-map evidence supports but does not replace topology
    evidence."

    Checkable rather than promised: the cross-check's slave list must still be
    exactly the one the traces produced. An unjoined address-map instance is a
    finding a human resolves (a naming mismatch, or a slave the trace missed) --
    it must never enlarge the topology on the address map's word alone."""
    from_traces = registry_endpoints(rows)["slaves"]
    if sorted(cross_check.get("traced_slaves") or []) != sorted(from_traces):
        raise RouteTransformPredictorError("ADDRESS_MAP_ALTERED_TOPOLOGY", {
            "from_cross_check": sorted(cross_check.get("traced_slaves") or []),
            "from_traces": sorted(from_traces),
            "hint": "address-map evidence corroborates a traced slave; it never adds one"})


def address_map_conflicts(cross_check: dict, *, doc_source: str = DOC_AUTHORITY_SOURCE) -> list:
    """SYOSCB-13's "Prefer direct implementation evidence when sources conflict",
    resolved mechanically.

    Every DISAGREES entry is handed to `address_map_verifier.
    doc_disagreement_conflict()`, which runs the real `source_authority`
    resolution -- so the winner is decided by the 9-level order this harness
    already uses, not by a rule local to this module."""
    conflicts = []
    for slave in cross_check.get("per_slave") or ():
        for entry in slave.get("verified_entries") or ():
            if entry.get("doc_status") != "DISAGREES":
                continue
            resolution = doc_disagreement_conflict(entry, doc_source=doc_source)
            conflicts.append({"slave_endpoint": slave["slave_endpoint"],
                              "instance": entry["instance"],
                              "base_hex": entry["base_hex"],
                              "resolution": resolution})
    return conflicts


# ===========================================================================
# Reporting
# ===========================================================================

def render_route_prediction_table(predictions) -> str:
    rows = [{"route_id": p["route_id"],
             "master": p["master_endpoint"], "slave": p["slave_endpoint"],
             "legality": p["responsibilities"]["routing_legality"]["value"]["pair_status"],
             "bridge": p["responsibilities"]["bridge_behavior"]["status"],
             "width": p["responsibilities"]["width_conversion"]["status"],
             "id_remap": p["responsibilities"]["id_remap"]["status"],
             "unresolved": ", ".join(p["unresolved_responsibilities"]) or "(none)"}
            for p in predictions or ()]
    return render_markdown_table(
        [("route_id", "Route"), ("master", "Master Endpoint"), ("slave", "Slave Endpoint"),
         ("legality", "Legality"), ("bridge", "Bridge"), ("width", "Width Conversion"),
         ("id_remap", "ID Remap"), ("unresolved", "Still REQUIRED_HUMAN_INPUT")], rows,
        empty_note="(no traced master/slave pair, so no route is predicted)")


def render_responsibility_detail(prediction: dict) -> str:
    rows = [{"responsibility": name,
             "status": prediction["responsibilities"][name]["status"],
             "value": str(prediction["responsibilities"][name]["value"]),
             "basis": " | ".join(prediction["responsibilities"][name]["evidence"])}
            for name in ROUTE_RESPONSIBILITIES]
    return render_markdown_table(
        [("responsibility", "SYOSCB-12 Responsibility"), ("status", "Status"),
         ("value", "Value"), ("basis", "Basis")], rows)


def render_address_map_evidence_types() -> str:
    return render_markdown_table(
        [("evidence_type", "SYOSCB-13 Evidence Type"),
         ("verifier_argument", "verify_address_map() Argument"),
         ("authority_source", "Authority Source"), ("ingestion", "Ingestion"),
         ("note", "Note")], list(ADDRESS_MAP_EVIDENCE_TYPES))


def render_address_map_cross_check(cross_check: dict) -> str:
    rows = [{"slave": s["slave_endpoint"], "status": s["status"],
             "bases": ", ".join(e["base_hex"] for e in s["verified_entries"]) or "-",
             "doc": ", ".join(s["doc_statuses"]) or "-"}
            for s in (cross_check or {}).get("per_slave") or ()]
    return render_markdown_table(
        [("slave", "Traced Slave"), ("status", "Address Evidence"),
         ("bases", "Decoder-Verified Base(s)"), ("doc", "Document Corroboration")], rows,
        empty_note="(no traced slave, so there is nothing for address evidence to "
                   "corroborate)")


def render_route_transform_report(predictions, cross_check=None) -> str:
    """The SYOSCB-12 / SYOSCB-13 review artifact.

    Self-checked against both emission gates, for the reason SYOSCB-33 exists: a
    Phase-1 planning document that rendered compilable SystemVerilog would be a
    way past the approval gate standing between this plan and any code."""
    open_routes = [p for p in predictions or () if p["unresolved_responsibilities"]]
    lines = ["# SYOSCB-12 / SYOSCB-13 AMBA Route and Transform Prediction", "",
             f"{len(predictions or ())} route(s) predicted from the AMBA_PORT_REGISTRY's "
             f"own traced topology. Every answer below is STRUCTURAL -- what the "
             f"discovered topology implies -- never a per-transaction prediction against "
             f"real traffic.", "",
             "## Routes", "", render_route_prediction_table(predictions), ""]
    for prediction in predictions or ():
        lines += [f"### {prediction['route_id']}", "",
                  render_responsibility_detail(prediction), ""]
    lines += ["## SYOSCB-13 address-map evidence types", "",
              render_address_map_evidence_types(), ""]
    if cross_check is not None:
        lines += ["## SYOSCB-13 address-map cross-check", "",
                  render_address_map_cross_check(cross_check), ""]
        if cross_check.get("unjoined_address_evidence"):
            lines += ["Address-map instances naming no traced endpoint (reported, never "
                      "joined -- address evidence supports topology, it does not replace "
                      "it):", "",
                      render_markdown_table(
                          [("instance", "Instance"), ("base_hex", "Base"),
                           ("decoder_evidence", "Decoder Evidence")],
                          cross_check["unjoined_address_evidence"]), ""]
    if open_routes:
        lines += ["## Routes whose prediction cannot be completed from discovery alone", "",
                  render_markdown_table(
                      [("route_id", "Route"), ("unresolved", "Responsibilities")],
                      [{"route_id": p["route_id"],
                        "unresolved": ", ".join(p["unresolved_responsibilities"])}
                       for p in open_routes]), ""]
    lines.append(
        "Phase-1 planning only (SYOSCB-33). No predictor, adapter or scoreboard code is "
        "emitted here, and nothing above is written into a scoreboard plan: every "
        "proposal reaches connectivity.SCOREBOARD_PLAN_FIELDS only through a human "
        "confirming it (SYOSCB-34).")
    text = "\n".join(lines)
    assert_no_emittable_sv(text, label="SYOSCB-12/13 route and transform prediction")
    assert_no_bind_statement(text)
    return text
