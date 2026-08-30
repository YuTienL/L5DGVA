"""dv_harness/uvm_generator/canfd_arbitration_generator.py -- CAN-FD bus
arbitration + error-state-machine model generator for DV Agent Harness L5.

BUG FIX (2026-08-29, parity-audit follow-up): a protocol-parity audit found
that CAN-FD has no structural generator today, unlike AMBA
(dv_harness/uvm_generator/amba_fabric_generator.py) -- nothing in the repo
took a CAN-FD bus topology (a set of contending nodes + a bus name) and
actually computed the real, protocol-generic CAN-FD mechanics: bitwise
dominant/recessive arbitration resolution, the TEC/REC error-state machine
(active/passive/bus-off), or a generic CRC computation parameterized for the
CAN-FD CRC-15/17/21 widths. This module computes those algorithms for real in
Python (not just comments), then emits real SV skeleton code carrying the
computed values, plus a topology JSON and an environment_manifest.json entry
-- mirroring amba_fabric_generator.py's engineering style exactly: pure
functions with typed errors that refuse to silently produce a wrong/
incomplete result, real computed literals embedded in the emitted skeleton
text (not placeholders where a real value is knowable), and explicit
placeholders (never fabricated plausible-sounding constants) exactly where
current confidence is insufficient.

CONFIDENCE / NEEDS SPEC VERIFICATION
-------------------------------------
- Arbitration (dominant-bit-wins, lowest-identifier-wins, bit-by-bit
  resolution) and the CAN bus's open-drain wired-AND electrical behavior
  (dominant=logic 0 pulls the bus low regardless of how many nodes drive
  recessive=1) are core, universally-documented ISO 11898-1/-2 mechanics.
  Modeled here with high confidence.
- TEC/REC increment/decrement rules (TX_ERROR: +8, RX_ERROR: +1 nominal,
  TX_SUCCESS/RX_SUCCESS: -1 floored at 0) and the two canonical thresholds
  (TEC/REC > 127 -> ERROR_PASSIVE, TEC > 255 -> BUS_OFF) are the
  widely-documented headline rules. This module deliberately stops there.
  It does NOT model: the exact RX_ERROR "+8 for specific ack/form/bit
  errors" sub-classification (accepted here only as an opaque
  severity="normal"|"severe" flag the caller must already know, not derived
  from a real error-subtype classifier); the bus-off recovery sequence (128
  occurrences of 11 consecutive recessive bits); or any REC-specific
  post-error-passive recovery-count nuance beyond the two thresholds above.
  Each such gap is flagged inline at the point it would otherwise be
  silently assumed, and apply_error_event() refuses (typed error) to advance
  a state that is already BUS_OFF, rather than silently fabricating a
  recovery-sequence outcome it does not implement.
- CRC: the classic CAN CRC-15 generator polynomial (0x4599, i.e.
  x^15+x^14+x^10+x^8+x^7+x^4+x^3+1) is extremely widely and consistently
  documented and is used here as the default for poly_width=15 only. The
  CAN-FD CRC-17/CRC-21 generator polynomials are NOT hardcoded -- this
  module does not carry high enough confidence in a specific hex constant
  for those two widths to assert one without checking current ISO
  11898-1:2015 Annex text, so compute_crc() requires the caller to supply
  `polynomial` explicitly for poly_width in (17, 21) and raises a typed,
  clearly-labeled error otherwise instead of guessing.
- CAN identifier field widths (11-bit "STANDARD" / 29-bit "EXTENDED") are a
  stable, universally-documented ISO 11898-1 fact and are hardcoded with
  high confidence.
- Which CRC width (17 vs 21) a real CAN-FD frame uses depends on its data
  length code (DLC) per ISO 11898-1's FD frame format; this generator does
  not model per-frame DLC-based width selection -- `crc_width` is topology
  metadata the caller supplies, not derived here.

WHAT THIS DOES NOT DO (deliberately, matching amba_fabric_generator.py's own
convention for genuinely DUT/VIP-specific detail that cannot be assumed at
generation time): no VIP package/agent binding (uses the same
PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE convention as
examples/generated_pcie_uvm_env/environment_manifest.json), no stuff-bit
insertion/removal logic (bit-stuffing is real ISO 11898-1 mechanics but is
not implemented in this pass -- flagged here rather than half-implemented),
no dual-rate nominal/data bit-timing resync state machine (BRS resync timing
constants are DUT/oscillator-dependent, not generic constants this module
can assert), and no actual CRC-17/21 polynomial constant (see above). This
is a real, structurally-correct skeleton, not an attempt at a full
production-grade CAN-FD VIP.
"""
from __future__ import annotations

import json
from pathlib import Path

from .generator import sv_id
from ..qualification import QualificationTier


# ---------------------------------------------------------------------------
# 1. Bitwise dominant/recessive arbitration resolution
# ---------------------------------------------------------------------------

class ArbitrationError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _validate_contenders(node_ids):
    if not node_ids:
        raise ArbitrationError("EMPTY_CONTENDER_LIST", {})

    seen = set()
    for entry in node_ids:
        if "node_id" not in entry or not str(entry["node_id"]):
            raise ArbitrationError("MISSING_NODE_ID", {"entry": entry})
        nid = entry["node_id"]
        if nid in seen:
            raise ArbitrationError("DUPLICATE_NODE_ID", {"node_id": nid})
        seen.add(nid)
        bits = entry.get("identifier_bits")
        if not bits or not isinstance(bits, str) or any(c not in "01" for c in bits):
            raise ArbitrationError("INVALID_IDENTIFIER_BITS", {"node_id": nid, "identifier_bits": bits})

    lengths = {len(entry["identifier_bits"]) for entry in node_ids}
    if len(lengths) != 1:
        raise ArbitrationError("IDENTIFIER_LENGTH_MISMATCH", {
            "lengths": {entry["node_id"]: len(entry["identifier_bits"]) for entry in node_ids},
        })
    return lengths.pop()


def resolve_arbitration(node_ids):
    """Resolves CAN bus arbitration among simultaneously-transmitting nodes.

    `node_ids`: list of {"node_id": str, "identifier_bits": "0/1 string"}.
    Dominant bit = '0' (a 0 always beats a 1: real ISO 11898-2 open-drain
    wired-AND bus electrical behavior -- if ANY contending node drives '0'
    at a given bit position, the bus reads '0' regardless of how many other
    nodes drive '1'). Bits are compared MSB-first (position 0 = first bit
    transmitted), matching CAN's transmission order. A node that transmits
    '1' at a bit position where the bus reads '0' (because some OTHER still-
    contending node drove '0' there) loses arbitration at that bit position
    and must stop transmitting -- it plays no further part in resolving
    later bit positions.

    Returns {"winner_node_id": str, "losers": [{"node_id": str,
    "lost_at_bit": int}, ...]} (losers in the order they dropped out).

    Raises ArbitrationError if the contender list is empty, a node_id is
    missing/duplicated, identifier_bits is missing/non-binary, contenders'
    identifier_bits are not all the same length (arbitration requires a
    shared, fixed identifier field width), or -- most importantly -- if two
    or more nodes have IDENTICAL identifier_bits all the way to the end (a
    real CAN bus can never resolve this: unique arbitration identifiers are
    a network-design precondition, not something this function may silently
    break a tie on)."""
    width = _validate_contenders(node_ids)
    if len(node_ids) == 1:
        return {"winner_node_id": node_ids[0]["node_id"], "losers": []}

    active = list(node_ids)
    losers = []
    for bit_pos in range(width):
        bits_here = {e["node_id"]: e["identifier_bits"][bit_pos] for e in active}
        bus_value = "0" if any(v == "0" for v in bits_here.values()) else "1"
        if bus_value == "0":
            losing_now = [e for e in active if bits_here[e["node_id"]] == "1"]
            for e in losing_now:
                losers.append({"node_id": e["node_id"], "lost_at_bit": bit_pos})
            active = [e for e in active if bits_here[e["node_id"]] == "0"]
        if len(active) <= 1:
            break

    if len(active) != 1:
        raise ArbitrationError("IDENTICAL_IDENTIFIERS_NO_WINNER", {
            "tied_node_ids": [e["node_id"] for e in active],
        })
    return {"winner_node_id": active[0]["node_id"], "losers": losers}


# ---------------------------------------------------------------------------
# 2. Error-state machine (TEC/REC, active/passive/bus-off)
# ---------------------------------------------------------------------------

class ErrorStateError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


_MODES = ("ERROR_ACTIVE", "ERROR_PASSIVE", "BUS_OFF")
_EVENTS = ("TX_ERROR", "RX_ERROR", "TX_SUCCESS", "RX_SUCCESS")
_SEVERITIES = ("normal", "severe")

# The two canonical, widely-documented thresholds. See module docstring's
# CONFIDENCE section: nothing more granular than these two is modeled.
ERROR_PASSIVE_THRESHOLD = 127  # TEC or REC > 127 -> ERROR_PASSIVE
BUS_OFF_THRESHOLD = 255        # TEC > 255 -> BUS_OFF (REC alone never causes bus-off)


def apply_error_event(state: dict, event: str, severity: str = "normal") -> dict:
    """Pure state-transition function for CAN's error-state machine.

    `state`: {"tec": int>=0, "rec": int>=0, "mode": one of _MODES}.
    `event`: one of _EVENTS.
    `severity`: "normal" (default) or "severe" -- ONLY consulted for
    RX_ERROR. SIMPLIFICATION (documented, not hidden): the real spec
    distinguishes RX_ERROR's REC increment by the specific error subtype
    (ack/form/bit errors count +8 in some conditions, other receive errors
    count +1) -- that subtype is not always knowable at this abstraction
    level, so this function accepts the caller's own severity judgement
    instead of deriving it. TX_ERROR is always +8 regardless of `severity`
    (the real spec does not have a TX_ERROR severity split); `severity` is
    silently ignored for events other than RX_ERROR.

    Rules applied (see module docstring CONFIDENCE section for what is
    deliberately NOT modeled beyond these):
      TX_ERROR:    tec += 8
      RX_ERROR:    rec += 1 (severity="normal") or += 8 (severity="severe")
      TX_SUCCESS:  tec -= 1, floored at 0
      RX_SUCCESS:  rec -= 1, floored at 0 (this floor-by-exactly-1 rule
                   applies uniformly regardless of how degraded the node
                   currently is -- there is no larger single-event recovery
                   jump modeled here)
      mode:        tec > 255              -> BUS_OFF
                   tec > 127 or rec > 127  -> ERROR_PASSIVE
                   else                    -> ERROR_ACTIVE

    Refuses (ErrorStateError) to process any event against a state whose
    mode is already BUS_OFF: real bus-off recovery requires observing 128
    occurrences of 11 consecutive recessive bits (ISO 11898-1), which this
    function does not implement -- silently continuing to apply TX/RX
    deltas to a bus-off node would fabricate a recovery/behavior this module
    does not actually model."""
    if not isinstance(state, dict) or "tec" not in state or "rec" not in state or "mode" not in state:
        raise ErrorStateError("INVALID_STATE_SCHEMA", {"state": state})
    tec, rec, mode = state["tec"], state["rec"], state["mode"]
    if not isinstance(tec, int) or isinstance(tec, bool) or tec < 0:
        raise ErrorStateError("INVALID_TEC", {"tec": tec})
    if not isinstance(rec, int) or isinstance(rec, bool) or rec < 0:
        raise ErrorStateError("INVALID_REC", {"rec": rec})
    if mode not in _MODES:
        raise ErrorStateError("INVALID_MODE", {"mode": mode})
    if event not in _EVENTS:
        raise ErrorStateError("INVALID_EVENT", {"event": event})
    if severity not in _SEVERITIES:
        raise ErrorStateError("INVALID_SEVERITY", {"severity": severity})
    if mode == "BUS_OFF":
        raise ErrorStateError("BUS_OFF_RECOVERY_NOT_MODELED", {
            "detail": "apply_error_event does not model the ISO 11898-1 bus-off "
                      "recovery sequence (128 x 11 consecutive recessive bits); "
                      "a BUS_OFF state is terminal for this function.",
        })

    if event == "TX_ERROR":
        tec = tec + 8
    elif event == "RX_ERROR":
        rec = rec + (8 if severity == "severe" else 1)
    elif event == "TX_SUCCESS":
        tec = max(0, tec - 1)
    elif event == "RX_SUCCESS":
        rec = max(0, rec - 1)

    if tec > BUS_OFF_THRESHOLD:
        new_mode = "BUS_OFF"
    elif tec > ERROR_PASSIVE_THRESHOLD or rec > ERROR_PASSIVE_THRESHOLD:
        new_mode = "ERROR_PASSIVE"
    else:
        new_mode = "ERROR_ACTIVE"

    return {"tec": tec, "rec": rec, "mode": new_mode}


# ---------------------------------------------------------------------------
# 3. Generic CRC computation (polynomial division mod 2)
# ---------------------------------------------------------------------------

class CRCError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# Default generator polynomial per width, given as the low `poly_width` bits
# (leading x^poly_width coefficient is implicit = 1), matching standard CRC
# convention. ONLY poly_width=15 has a default here -- see module docstring
# CONFIDENCE section for why 17/21 are deliberately absent.
_DEFAULT_POLYNOMIALS = {
    15: 0x4599,  # classic CAN CRC-15: x^15+x^14+x^10+x^8+x^7+x^4+x^3+1 (ISO 11898-1)
}
_SUPPORTED_WIDTHS = (15, 17, 21)


def compute_crc(bits: str, poly_width: int, polynomial: int = None) -> str:
    """Generic CRC via standard bitwise polynomial long division (the
    "append poly_width zero bits, then divide" construction, mod-2
    arithmetic) -- a pure, well-defined, protocol-agnostic algorithm, not
    CAN-specific magic. `poly_width` may be any positive int (the algorithm
    itself has no CAN-specific restriction); CANFDArbitrationGenerator is
    the layer that restricts CAN-FD topology's `crc_width` to the three
    CAN-FD-relevant widths (15/17/21) via _validate_crc_width. Returns the
    remainder as a string of '0'/'1' of length `poly_width`.

    `bits`: the message bit sequence to checksum, as a '0'/'1' string.
    `polynomial`: optional explicit generator polynomial, given as the low
    `poly_width` bits (the leading x^poly_width coefficient is implicit=1).
    If omitted, a default is used ONLY for poly_width=15 (0x4599, the
    well-documented classic CAN CRC-15 polynomial). For any other width
    `polynomial` MUST be supplied by the caller from currently-verified
    spec text -- this function does not hardcode a CRC-17/21 constant it is
    not highly confident in (see module docstring); omitting it raises
    CRCError("POLYNOMIAL_NOT_VERIFIED", ...) rather than guessing."""
    if not isinstance(bits, str) or not bits or any(c not in "01" for c in bits):
        raise CRCError("INVALID_BIT_STRING", {"bits": bits})
    if not isinstance(poly_width, int) or isinstance(poly_width, bool) or poly_width <= 0:
        raise CRCError("INVALID_POLY_WIDTH", {"poly_width": poly_width})

    if polynomial is None:
        polynomial = _DEFAULT_POLYNOMIALS.get(poly_width)
        if polynomial is None:
            raise CRCError("POLYNOMIAL_NOT_VERIFIED", {
                "poly_width": poly_width,
                "detail": f"no default CRC-{poly_width} generator polynomial is hardcoded here "
                          "(NEEDS SPEC VERIFICATION against current ISO 11898-1:2015 Annex text) -- "
                          "supply `polynomial` explicitly.",
            })
    if not isinstance(polynomial, int) or isinstance(polynomial, bool) or not (0 <= polynomial < (1 << poly_width)):
        raise CRCError("INVALID_POLYNOMIAL", {"polynomial": polynomial, "poly_width": poly_width})

    # Full (poly_width+1)-bit polynomial string, leading bit = implicit 1.
    poly_bits = format(polynomial | (1 << poly_width), f"0{poly_width + 1}b")
    work = list(bits) + ["0"] * poly_width  # augmented dividend: message + poly_width zero bits
    n = len(bits)
    for i in range(n):
        if work[i] == "1":
            for j in range(poly_width + 1):
                work[i + j] = "1" if work[i + j] != poly_bits[j] else "0"
    return "".join(work[n:])


# ---------------------------------------------------------------------------
# 4. Generator: topology -> SV skeletons + topology JSON + manifest
# ---------------------------------------------------------------------------

class TopologyError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# Real, stable ISO 11898-1 identifier field widths (high confidence -- see
# module docstring CONFIDENCE section).
ID_FORMAT_WIDTHS = {"STANDARD": 11, "EXTENDED": 29}


def resolve_id_width(t: dict) -> int:
    """Exactly one of `id_width` (explicit int) or `id_format`
    ("STANDARD"|"EXTENDED") must be given -- a CAN bus's identifier field
    width is a bus-wide property (every node on the bus uses the same
    format), not something this generator may guess or default silently."""
    has_width = "id_width" in t
    has_format = "id_format" in t
    if has_width and has_format:
        raise TopologyError("AMBIGUOUS_ID_WIDTH_SPEC", {
            "detail": "supply exactly one of id_width or id_format, not both",
        })
    if has_width:
        w = t["id_width"]
        if not isinstance(w, int) or isinstance(w, bool) or w <= 0:
            raise TopologyError("INVALID_ID_WIDTH", {"id_width": w})
        return w
    if has_format:
        fmt = t["id_format"]
        if fmt not in ID_FORMAT_WIDTHS:
            raise TopologyError("UNKNOWN_ID_FORMAT", {"id_format": fmt, "known": sorted(ID_FORMAT_WIDTHS)})
        return ID_FORMAT_WIDTHS[fmt]
    raise TopologyError("MISSING_ID_WIDTH_OR_FORMAT", {
        "detail": "topology must supply either id_width (int) or id_format (STANDARD|EXTENDED)",
    })


def _validate_node_ids(t: dict):
    node_ids = t.get("node_ids")
    if not node_ids or not isinstance(node_ids, list):
        raise TopologyError("MISSING_NODE_IDS", {"node_ids": node_ids})
    seen = set()
    for nid in node_ids:
        if not isinstance(nid, str) or not nid:
            raise TopologyError("INVALID_NODE_ID", {"node_id": nid})
        if nid in seen:
            raise TopologyError("DUPLICATE_NODE_ID", {"node_id": nid})
        seen.add(nid)
    return node_ids


def _validate_crc_width(t: dict) -> int:
    crc_width = t.get("crc_width", 17)  # 17 is the more common CAN-FD default (payload <=16B); see docstring
    if crc_width not in _SUPPORTED_WIDTHS:
        raise TopologyError("UNSUPPORTED_CRC_WIDTH", {"crc_width": crc_width, "supported": _SUPPORTED_WIDTHS})
    return crc_width


class CANFDArbitrationGenerator:
    def __init__(self, out_dir):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def generate(self, t: dict):
        bus = sv_id(t.get("bus_name", "canfd_bus"))
        node_ids = _validate_node_ids(t)
        id_width = resolve_id_width(t)
        crc_width = _validate_crc_width(t)
        num_nodes = len(node_ids)

        files = {}
        files[f"{bus}_arbitration_tb.sv"] = self.arbitration_tb(t, bus, node_ids, id_width)
        files[f"{bus}_error_state_machine.sv"] = self.error_state_machine(t, bus)
        files["filelist.f"] = "\n".join([
            f"{bus}_arbitration_tb.sv", f"{bus}_error_state_machine.sv",
        ]) + "\n"

        topology = {
            "bus_name": bus,
            "node_ids": node_ids,
            "num_nodes": num_nodes,
            "id_width": id_width,
            "crc_width": crc_width,
        }
        if "id_format" in t:
            topology["id_format"] = t["id_format"]
        files["canfd_topology.json"] = json.dumps(topology, indent=2)

        manifest = dict(t)
        manifest["bus_name"] = bus
        manifest["id_width"] = id_width
        manifest["crc_width"] = crc_width
        manifest["num_nodes"] = num_nodes
        manifest["generated_files"] = sorted(files.keys()) + ["environment_manifest.json"]
        manifest["qualification_status"] = QualificationTier.ENV_GENERATED.value
        manifest.setdefault("vip", {})["binding_status"] = "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        if crc_width != 15:
            manifest["crc_polynomial_status"] = "NEEDS_SPEC_VERIFICATION"  # see compute_crc() docstring
        files["environment_manifest.json"] = json.dumps(manifest, indent=2)

        for name, content in files.items():
            (self.out / name).write_text(content, encoding="utf-8")
        return sorted(files.keys())

    def arbitration_tb(self, t, bus, node_ids, id_width):
        num_nodes = len(node_ids)
        node_list_comment = "\n".join(f"  //   [{i}] {nid}" for i, nid in enumerate(node_ids))

        # Illustrative worked example computed by a REAL call to
        # resolve_arbitration() at generation time (synthetic identifier
        # bits, clearly labeled -- NOT derived from real DUT configuration,
        # since the topology only supplies node_ids, not per-node
        # identifier values). Demonstrates the contract this module's SV
        # logic implements, with literal computed numbers, not fabricated
        # ones.
        example_nodes = node_ids[:min(3, num_nodes)]
        example = None
        if len(example_nodes) >= 2:
            synth = []
            for i, nid in enumerate(example_nodes):
                bit_pattern = format(i, f"0{id_width}b")
                synth.append({"node_id": nid, "identifier_bits": bit_pattern})
            example = resolve_arbitration(synth)
            example_lines = [f"  //   node {e['node_id']!r} identifier_bits={synth[i]['identifier_bits']!r}"
                              for i, e in enumerate(synth)]
            example_comment = (
                "  // ILLUSTRATIVE EXAMPLE (synthetic identifier_bits, not real DUT config) --\n"
                "  // computed via a real resolve_arbitration() call at generation time:\n"
                + "\n".join(example_lines) + "\n"
                f"  //   -> winner: {example['winner_node_id']!r}, losers: {example['losers']!r}"
            )
        else:
            example_comment = "  // (fewer than 2 nodes -- no arbitration contention to illustrate)"

        return f"""// CAN-FD bitwise dominant/recessive arbitration resolver for bus
// '{bus}' -- {num_nodes} contending node(s):
{node_list_comment}
//
// Real ISO 11898-2 electrical behavior: the CAN bus is an open-drain,
// dominant-low (dominant='0') wired-AND bus. A bit position's resolved bus
// value is therefore exactly the bitwise AND of every still-contending
// node's driven bit at that position (AND==0 whenever ANY node drives 0).
// A node driving '1' ("recessive") while the resolved bus value is '0'
// ("dominant") has lost arbitration at that bit and must stop driving for
// the remainder of this identifier field -- this mirrors
// resolve_arbitration() in canfd_arbitration_generator.py exactly (single
// source of truth for the algorithm).
{example_comment}
module {bus}_arbitration_tb #(
  parameter int NUM_NODES = {num_nodes},
  parameter int ID_WIDTH  = {id_width}
)(
  input  logic [ID_WIDTH-1:0] node_id_bits [NUM_NODES], // node_id_bits[k][ID_WIDTH-1] driven first (MSB-first)
  output logic [ID_WIDTH-1:0] bus_id_bits,               // wired-AND resolved bus value, MSB-first
  output logic [NUM_NODES-1:0] lost_arbitration          // sticky: node k lost at some bit position
);
  logic [NUM_NODES-1:0] still_contending;
  integer bit_idx, node_idx;

  always_comb begin
    logic bit_val;
    still_contending = '1;
    lost_arbitration = '0;
    for (bit_idx = ID_WIDTH-1; bit_idx >= 0; bit_idx = bit_idx - 1) begin
      bit_val = 1'b1;
      for (node_idx = 0; node_idx < NUM_NODES; node_idx = node_idx + 1)
        if (still_contending[node_idx])
          bit_val = bit_val & node_id_bits[node_idx][bit_idx];
      bus_id_bits[bit_idx] = bit_val;
      for (node_idx = 0; node_idx < NUM_NODES; node_idx = node_idx + 1)
        if (still_contending[node_idx] && node_id_bits[node_idx][bit_idx] == 1'b1 && bit_val == 1'b0) begin
          lost_arbitration[node_idx] = 1'b1;
          still_contending[node_idx] = 1'b0;
        end
    end
  end
endmodule
"""

    def error_state_machine(self, t, bus):
        # Real, computed worked examples (actual apply_error_event() calls
        # at generation time), embedded as literal comments -- not
        # fabricated numbers. Demonstrates both threshold crossings.
        ex1_before = {"tec": 120, "rec": 0, "mode": "ERROR_ACTIVE"}
        ex1_after = apply_error_event(ex1_before, "TX_ERROR")
        ex2_before = {"tec": 250, "rec": 0, "mode": "ERROR_PASSIVE"}
        ex2_after = apply_error_event(ex2_before, "TX_ERROR")

        return f"""// CAN error-state machine (TEC/REC, active/passive/bus-off) for bus
// '{bus}'. Mirrors apply_error_event() in canfd_arbitration_generator.py
// exactly (single source of truth for the counter/threshold rules) --
// see that function's docstring for the full CONFIDENCE / NEEDS SPEC
// VERIFICATION caveats (only the two canonical thresholds are modeled;
// RX_ERROR's severity split is an opaque caller-supplied flag, not a
// derived error-subtype classification; bus-off recovery is NOT modeled).
//
// Worked examples (real apply_error_event() calls at generation time):
//   {ex1_before} + TX_ERROR -> {ex1_after}
//   {ex2_before} + TX_ERROR -> {ex2_after}
module {bus}_error_state_machine (
  input  logic       clk,
  input  logic       rst_n,
  input  logic       tx_error,        // pulse: this node's transmission errored
  input  logic       rx_error,        // pulse: this node flagged a receive error
  input  logic       rx_error_severe, // qualifies rx_error: severity="severe" -> rec += 8 instead of +1
  input  logic       tx_success,      // pulse: successful transmission completion
  input  logic       rx_success,      // pulse: successful reception completion
  output logic [8:0] tec,             // Transmit Error Counter
  output logic [8:0] rec,             // Receive Error Counter
  output logic [1:0] mode             // 0=ERROR_ACTIVE 1=ERROR_PASSIVE 2=BUS_OFF
);
  localparam logic [1:0] ERROR_ACTIVE = 2'd0, ERROR_PASSIVE = 2'd1, BUS_OFF = 2'd2;
  localparam int ERROR_PASSIVE_THRESHOLD = {ERROR_PASSIVE_THRESHOLD};
  localparam int BUS_OFF_THRESHOLD       = {BUS_OFF_THRESHOLD};

  // NEEDS SPEC VERIFICATION / NOT MODELED: bus-off recovery (128 occurrences
  // of 11 consecutive recessive bits, ISO 11898-1) -- once mode==BUS_OFF
  // this skeleton holds state (see the guard below) rather than fabricating
  // a recovery outcome.
  //
  // NOTE: mode below is computed from tec/rec values assigned THIS SAME
  // cycle via non-blocking assignment, so it reads the PRE-update counters
  // (one-cycle lag vs. a same-cycle combinational derivation) -- adapt if a
  // same-cycle mode is required.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tec  <= '0;
      rec  <= '0;
      mode <= ERROR_ACTIVE;
    end else if (mode == BUS_OFF) begin
      // placeholder: recovery sequence not modeled, hold state.
    end else begin
      if (tx_error)        tec <= tec + 9'd8;
      else if (tx_success)  tec <= (tec > 9'd0) ? tec - 9'd1 : 9'd0;
      if (rx_error)        rec <= rec + (rx_error_severe ? 9'd8 : 9'd1);
      else if (rx_success)  rec <= (rec > 9'd0) ? rec - 9'd1 : 9'd0;

      if (tec > BUS_OFF_THRESHOLD[8:0])
        mode <= BUS_OFF;
      else if (tec > ERROR_PASSIVE_THRESHOLD[8:0] || rec > ERROR_PASSIVE_THRESHOLD[8:0])
        mode <= ERROR_PASSIVE;
      else
        mode <= ERROR_ACTIVE;
    end
  end
endmodule
"""
