"""dv_harness/uvm_generator/mipi_dphy_generator.py -- MIPI D-PHY lane
electrical-state-machine model generator (D-PHY ONLY -- see SCOPE below).

BUG FIX (2026-08-29, parity-audit follow-up): a parity audit of the MIPI
CSI-2/DSI coverage in this repo identified a real gap: no module modeled
"a D-PHY/C-PHY lane-and-timing state model (HS/LP transitions, escape
mode/ULPS)". CSI-2 and DSI both ride on a MIPI D-PHY (or, on newer designs,
C-PHY) physical layer, and neither protocol's packet-level correctness can
be checked without first knowing whether the underlying lane's Low-Power
(LP) / High-Speed (HS) / Escape-Mode / ULPS electrical-state transitions
are even legal. This module is the D-PHY half of closing that gap, built
the same way amba_fabric_generator.py closed the AMBA M x N gap: real,
computed Python algorithms (a typed-error-raising transition validator, a
sequence simulator) that an SV skeleton emitter then carries into real
generated text -- not just descriptive comments.

SCOPE -- D-PHY ONLY, C-PHY DELIBERATELY NOT ATTEMPTED THIS PASS:
MIPI D-PHY (2-wire-per-lane differential signaling, LP/HS electrical
states) and MIPI C-PHY (3-wire-per-lane-trio, ternary/trio symbol
encoding) are two DIFFERENT physical layers that CSI-2/DSI can both ride
on. This module implements D-PHY only. C-PHY's trio symbol-encoding table
(the wire-state-to-symbol mapping and its associated line-coding/mapping
rules) is a distinct, detailed piece of the public spec that this pass is
NOT confident enough to fabricate from memory -- getting D-PHY done
honestly beats guessing at a C-PHY symbol table and being wrong. C-PHY
needs its own dedicated pass with real spec-text verification of that
table before any code is written for it.

WHAT THIS DOES NOT DO (deliberately):
- Does not model C-PHY at all (see SCOPE above).
- Does not assert exact LP-line bit-timing constants (e.g. real
  nanosecond/UI values for HS-PREPARE, HS-ZERO, THS-SETTLE, TLPX, etc) --
  those are real spec numbers this pass is not confident enough to
  hardcode as fabricated-but-plausible constants. The state model here is
  purely about LEGAL/ILLEGAL top-level state transitions, not timing.
- Does not assert the exact LP-01/LP-00/LP-10 sub-sequence timing that
  distinguishes an HS-Request from an Escape-Mode entry at the electrical
  level -- ESCAPE_MODE is modeled as a single named top-level state
  reachable from STOP, without asserting the precise LP-symbol sequence
  numbers that gate real entry into it (see CONFIDENCE section below).
- Does not differentiate Clock-lane-specific vs Data-lane-specific state
  behavior (e.g. that only certain data lanes support Escape Mode in some
  real designs, or a clock lane's own HS/LP toggle nuances) -- this
  generator emits one shared top-level lane state graph applied
  per-lane-index; a real per-lane-role refinement would need to be added
  once that distinction is confirmed against current spec text/RTL.
- Does not bind actual DUT PHY register names, VIP class names, or any
  project-specific timing constant -- per CLAUDE.md's Evidence Truth Rule,
  none of that is assumed at generation time (see the
  PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE convention below, matching
  amba_fabric_generator.py's own use of it).
- compute_ecc() is NOT a verified implementation of the real CSI-2/DSI
  packet-header ECC bit assignments -- see its own docstring and the
  CONFIDENCE section below.

CONFIDENCE / NEEDS SPEC VERIFICATION:
1. C-PHY is entirely out of scope this pass (see SCOPE above) -- not a
   partial/best-effort attempt, a deliberate omission.
2. DPHY_TRANSITIONS models only the top-level state graph this pass is
   confident is a stable, public, well-known MIPI D-PHY concept (STOP as
   the common LP-11 hub state from which HS bursts, bus-turnaround, and
   Escape-Mode entry are all initiated, and to which each returns when
   done; ESCAPE_MODE as the gateway into ULPS). It deliberately does NOT
   assert: the exact LP-01/LP-00/LP-10 timing/symbol sequence that
   electrically distinguishes each of these entries from one another, any
   sub-states inside HS-Exit/LP-Yield, or any transition this pass is not
   confident is real (e.g. it does not claim HS_DATA can transition
   directly to ESCAPE_MODE, or TURNAROUND can transition directly to
   HS_REQUEST, without first returning to STOP) -- such transitions are
   simply omitted rather than guessed at.
3. compute_ecc(): the real MIPI CSI-2/DSI packet header uses a
   standardized Hamming-derived ECC-1 (single-bit-correct) code (Data-ID
   (8 bits) + Word-Count (16 bits) = 24 protected data bits, producing a
   real spec-defined 6-bit parity field, which together with 2 reserved
   bits forms the overall 32-bit packet header alongside the 26 bits of
   Data-ID+Word-Count+reserved -- hence "(32,26)"). This pass is NOT
   confident of the exact generator-matrix bit assignments (i.e. exactly
   which of the 24 data bits XOR together to form each of the 6 parity
   bits) well enough to fabricate them as if verified against current
   spec text. compute_ecc() below is therefore a CLEARLY-LABELED
   PLACEHOLDER: deterministic and fixed-width (structural properties this
   pass IS confident of), but NOT asserted to match the real standard's
   bit-exact parity values. It must be replaced with the verified real
   generator matrix (checked against current MIPI CSI-2/DSI spec text)
   before any production use that depends on ECC correctness/mismatch
   detection.
"""
from __future__ import annotations

import json
from pathlib import Path

from .generator import sv_id
from ..qualification import QualificationTier


class DPHYError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# Named lane states -- stable, public, well-known MIPI D-PHY concepts only.
# Order below is also the SV enum encoding order used by MIPIDPHYGenerator.
# ---------------------------------------------------------------------------
DPHY_STATES: tuple = (
    "STOP",          # LP-11: idle/"Stop state" -- both lines driven LP-High; the common hub state.
    "HS_REQUEST",    # HS-Request: initiates a high-speed burst from STOP.
    "HS_PREPARE",    # HS-Prepare: differential HS driver preparation ahead of HS-Sync.
    "HS_SYNC",       # HS-Sync: HS synchronization sequence transmitted before HS payload data.
    "HS_DATA",       # HS-Data: the HS burst payload itself.
    "TURNAROUND",    # Bus-Turnaround (BTA): direction-reversal handshake on a bidirectional lane.
    "ESCAPE_MODE",   # Escape Mode: LP-encoded low-speed side-channel, entry sequence not asserted (see CONFIDENCE).
    "ULPS",          # Ultra-Low-Power State: entered via Escape Mode.
)
_STATE_SET = frozenset(DPHY_STATES)

# Legal top-level transition graph, dict-of-sets (state -> legal next states).
# Deliberately omits any transition this pass is not confident is real --
# see CONFIDENCE item 2 in the module docstring.
DPHY_TRANSITIONS: dict = {
    "STOP": {"HS_REQUEST", "TURNAROUND", "ESCAPE_MODE"},
    "HS_REQUEST": {"HS_PREPARE"},
    "HS_PREPARE": {"HS_SYNC"},
    "HS_SYNC": {"HS_DATA"},
    "HS_DATA": {"STOP"},
    "TURNAROUND": {"STOP"},
    "ESCAPE_MODE": {"STOP", "ULPS"},
    "ULPS": {"STOP"},
}


def validate_transition(state_from: str, state_to: str) -> None:
    """Pure, typed-error-raising validator -- same shape as this repo's
    other topology/graph validators (e.g. amba_fabric_generator.py's
    compute_address_regions): never silently accept an unknown state name
    or an omitted-from-DPHY_TRANSITIONS edge."""
    if state_from not in _STATE_SET:
        raise DPHYError("UNKNOWN_STATE", {"field": "state_from", "value": state_from, "known_states": list(DPHY_STATES)})
    if state_to not in _STATE_SET:
        raise DPHYError("UNKNOWN_STATE", {"field": "state_to", "value": state_to, "known_states": list(DPHY_STATES)})
    legal = DPHY_TRANSITIONS.get(state_from, set())
    if state_to not in legal:
        raise DPHYError("ILLEGAL_TRANSITION", {
            "state_from": state_from, "state_to": state_to,
            "legal_next_states": sorted(legal),
        })


def simulate_lane_sequence(events, start_state: str = "STOP") -> dict:
    """Sequence simulator: walks `events` (a list of target state names) from
    `start_state`, applying validate_transition at each step, and STOPS at
    the first illegal transition (does not keep simulating past a broken
    lane sequence). Returns a dict:
      {"ok": bool, "visited": [states...], "final_state": str,
       "error": {"reason":..., "detail":...} or None}
    `visited` always includes `start_state` and every state successfully
    transitioned into before any failure; it never includes the rejected
    target state itself."""
    if start_state not in _STATE_SET:
        raise DPHYError("UNKNOWN_STATE", {"field": "start_state", "value": start_state, "known_states": list(DPHY_STATES)})
    state = start_state
    visited = [state]
    for target in events:
        try:
            validate_transition(state, target)
        except DPHYError as exc:
            return {"ok": False, "visited": visited, "final_state": state,
                     "error": {"reason": exc.reason, "detail": exc.detail}}
        state = target
        visited.append(state)
    return {"ok": True, "visited": visited, "final_state": state, "error": None}


# ---------------------------------------------------------------------------
# compute_ecc: CLEARLY-LABELED PLACEHOLDER -- see CONFIDENCE item 3 above.
# NOT the verified real CSI-2/DSI packet-header ECC generator matrix.
# ---------------------------------------------------------------------------
ECC_DATA_WIDTH_BITS = 24   # Data-ID (8) + Word-Count (16), the real protected field width.
ECC_PARITY_WIDTH_BITS = 6  # Real spec-defined parity field width; bit ASSIGNMENTS are the unverified part.


def compute_ecc(header_bits: int) -> int:
    """PLACEHOLDER -- NEEDS SPEC VERIFICATION before production use.

    Real CSI-2/DSI packet headers protect a 24-bit Data-ID+Word-Count field
    with a standardized 6-bit Hamming-derived ECC-1 (single-bit-correct)
    code. This function is NOT that verified code: it does not implement
    the real per-parity-bit XOR generator matrix (this pass is not
    confident enough in the exact bit assignments to fabricate them -- see
    CONFIDENCE item 3 in the module docstring). It DOES honestly implement
    the two structural properties this pass IS confident of:
      - fixed output width: always returns a value in [0, 2**ECC_PARITY_WIDTH_BITS).
      - deterministic: identical input always yields identical output.
    Do not use this for real single-bit-error detection/correction, and do
    not test it against a hand-computed real spec example -- that would
    require the verified generator matrix this function deliberately does
    not claim to have.
    """
    if not isinstance(header_bits, int) or isinstance(header_bits, bool):
        raise DPHYError("INVALID_HEADER_TYPE", {"expected": "int", "got": type(header_bits).__name__})
    if header_bits < 0 or header_bits >= (1 << ECC_DATA_WIDTH_BITS):
        raise DPHYError("HEADER_WIDTH_OUT_OF_RANGE", {
            "value": header_bits, "expected_width_bits": ECC_DATA_WIDTH_BITS,
        })
    # Deterministic fold of the 24 data bits down to ECC_PARITY_WIDTH_BITS,
    # NOT the real per-bit XOR generator matrix. Placeholder only.
    parity_mask = (1 << ECC_PARITY_WIDTH_BITS) - 1
    folded = 0
    remaining = header_bits
    while remaining:
        folded ^= remaining & parity_mask
        remaining >>= ECC_PARITY_WIDTH_BITS
    return folded & parity_mask


class MIPIDPHYGenerator:
    """Analogous to AMBAFabricGenerator: takes a lane topology JSON and
    emits (1) an SV lane-state-register + transition-check module skeleton
    carrying the real DPHY_STATES/DPHY_TRANSITIONS values computed above,
    (2) a topology JSON, and (3) an environment_manifest.json entry. D-PHY
    only, per the module docstring's SCOPE section."""

    def __init__(self, out_dir):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def _validate_topology(self, t: dict) -> None:
        role = t.get("role")
        if role not in ("TX", "RX"):
            raise DPHYError("INVALID_ROLE", {"role": role, "expected": ["TX", "RX"]})
        lane_count = t.get("lane_count")
        if not isinstance(lane_count, int) or isinstance(lane_count, bool) or lane_count < 1:
            raise DPHYError("INVALID_LANE_COUNT", {"lane_count": lane_count, "expected": "int >= 1"})

    def generate(self, t: dict):
        self._validate_topology(t)
        module = sv_id(t.get("module_name", "mipi_dphy"))
        lane_count = t["lane_count"]
        role = t["role"]

        files = {}
        files[f"{module}_lane_state.sv"] = self.lane_state_module(t, module, lane_count, role)

        dphy_topology = {
            "module_name": module,
            "role": role,
            "lane_count": lane_count,
            "states": list(DPHY_STATES),
            "transitions": {k: sorted(v) for k, v in DPHY_TRANSITIONS.items()},
        }
        files["dphy_topology.json"] = json.dumps(dphy_topology, indent=2)

        manifest = dict(t)
        manifest["module_name"] = module
        manifest["states"] = list(DPHY_STATES)
        manifest["generated_files"] = sorted(files.keys()) + ["environment_manifest.json"]
        manifest["qualification_status"] = QualificationTier.ENV_GENERATED.value
        manifest.setdefault("vip", {})["binding_status"] = "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        manifest["cphy_status"] = "OUT_OF_SCOPE_THIS_PASS"
        manifest["ecc_status"] = "PLACEHOLDER_NEEDS_SPEC_VERIFICATION"
        files["environment_manifest.json"] = json.dumps(manifest, indent=2)

        for name, content in files.items():
            (self.out / name).write_text(content, encoding="utf-8")
        return sorted(files.keys())

    def lane_state_module(self, t, module, lane_count, role):
        enum_lines = "\n".join(f"    {name} = {i}," for i, name in enumerate(DPHY_STATES))
        # Real computed case-statement legality check, built from
        # DPHY_TRANSITIONS -- not a hand-authored placeholder table.
        case_lines = []
        for state in DPHY_STATES:
            legal = sorted(DPHY_TRANSITIONS.get(state, set()))
            if legal:
                or_terms = " || ".join(f"lane_next_state[i] == {s}" for s in legal)
                case_lines.append(f"        {state}: legal = ({or_terms});")
            else:
                case_lines.append(f"        {state}: legal = 1'b0; // no legal outgoing transition modeled")
        case_text = "\n".join(case_lines)
        return f"""// {module}_lane_state -- D-PHY ONLY (C-PHY out of scope this pass, see
// mipi_dphy_generator.py module docstring). role={role}, lane_count={lane_count}.
// Legal-transition case statement below is generated directly from
// DPHY_TRANSITIONS -- every arm mirrors the Python dict-of-sets exactly.
typedef enum logic [2:0] {{
{enum_lines}
}} dphy_lane_state_e;

module {module}_lane_state #(
  parameter int LANE_COUNT = {lane_count}
)(
  input  logic clk,
  input  logic rst_n,
  input  dphy_lane_state_e lane_next_state [LANE_COUNT],
  output dphy_lane_state_e lane_state [LANE_COUNT],
  output logic illegal_transition [LANE_COUNT]
);
  // Bind real per-lane LP/HS electrical drive signals from
  // environment_manifest.json/current evidence -- deliberately not
  // fabricated here (see WHAT THIS DOES NOT DO in the module docstring).
  genvar i;
  generate
    for (i = 0; i < LANE_COUNT; i++) begin : g_lane
      logic legal;
      always_comb begin
        legal = 1'b0;
        unique case (lane_state[i])
{case_text}
        endcase
      end
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
          lane_state[i] <= STOP;
          illegal_transition[i] <= 1'b0;
        end else if (lane_next_state[i] != lane_state[i]) begin
          if (legal) lane_state[i] <= lane_next_state[i];
          illegal_transition[i] <= !legal;
        end
      end
    end
  endgenerate
endmodule
"""
