"""dv_harness/uvm_generator/pcie_ltssm_generator.py -- PCIe Link Training and
Status State Machine (LTSSM) model generator for DV Agent Harness L5.

BUG FIX (2026-08-29, parity-audit gap): a protocol-parity audit found that
PCIe had no LTSSM state-machine generator at all -- link training/retry/
timeout/rate-negotiation behavior (a core, protocol-defining PCIe mechanism)
was entirely unmodeled anywhere in dv_harness/uvm_generator. This module adds
a real, checkable Python model of the LTSSM's TOP-LEVEL state graph (legal
transitions, a pure validator, a sequence-of-events checker usable as
scoreboard logic) plus an SV state-register/transition-check module skeleton
generator, mirroring amba_fabric_generator.py's engineering style: real
computed values driving generated SV text, typed errors that refuse to
silently produce a wrong/incomplete result, and an explicit, honest boundary
between "modeled with confidence" and "not modeled, flagged".

CONFIDENCE / NEEDS SPEC VERIFICATION
-------------------------------------
What IS modeled with confidence (stable, public, widely-published PCIe Base
Spec facts, unlikely to be wrong regardless of spec revision):
  - The 11 top-level LTSSM states: Detect, Polling, Configuration, L0, L0s,
    L1, L2, Recovery, Disabled, Loopback, Hot Reset.
  - A conservative subset of the top-level legal-transition graph between
    those states (see LTSSM_TRANSITIONS below). Every edge included here is
    one that appears consistently across public PCIe LTSSM overview diagrams
    (the Detect/Polling/Configuration training sequence into L0, L0's
    L0s/L1/Recovery fan-out, L1->L2 deep-power-down, Recovery as the
    retrain-and-return-to-L0-or-fail-to-Detect hub, and Disabled/Hot Reset as
    broadly-reachable states with a Detect-only return path).
  - Legal PCIe link widths (x1/x2/x4/x8/x12/x16/x32) -- a stable, published
    Link Width field encoding, not a guessed number.
  - CRC-32 (the IEEE 802.3 / zlib polynomial) as a GENERIC reusable checksum
    primitive.

What is DELIBERATELY NOT modeled here, because exact certainty was not
reached (each omission is a conscious choice, not an oversight):
  - Any LTSSM SUB-STATE (Polling.Active / Polling.Compliance /
    Polling.Configuration, Configuration.Linkwidth.Start/Accept/Complete/Idle,
    Recovery.RcvrLock/RcvrCfg/Idle/Speed, L1.Idle/PllLock, etc.) and any
    sub-state timeout/counter constant (e.g. the exact microsecond/symbol-time
    values for Polling or Recovery timeouts). These are real, numerous, and
    revision-sensitive spec details this pass is NOT confident enough to
    assert -- each is a candidate for a single opaque placeholder sub-state
    (see `LTSSM_SUBSTATE_PLACEHOLDER` below) rather than a fabricated number.
  - Exact TS1/TS2 ordered-set bit/symbol encodings, exact rate-negotiation
    (Gen1/2/3/4/5) symbol-rate or equalization-phase timing constants, and
    the exact scrambling/8b10b/128b130b framing details -- all out of scope.
  - Two top-level edges that are plausible but were NOT included because
    confidence was insufficient: Recovery->Configuration (link-width/rate
    renegotiation can plausibly re-enter Configuration in some sub-state
    flows, but this is not confidently a TOP-LEVEL-diagram edge) and any
    edge INTO Loopback (Loopback is real and exited back to Detect, but which
    top-level states may directly enter it was not confidently known here).
    Both are flagged as candidates for a future spec-verification pass, not
    silently guessed into the transition table.
  - TLP/DLLP-specific CRC (LCRC) and end-to-end CRC (ECRC) polynomials --
    `compute_lane_crc` below is a GENERIC CRC-32 wrapper only, explicitly NOT
    a PCIe-spec-exact LCRC/ECRC implementation.

WHAT THIS DOES NOT DO (matching amba_fabric_generator.py's own convention):
actual PHY/MAC signal names, register names/addresses, or VIP class bindings
(uses the same PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE convention already
established elsewhere in this repo), exact sub-state timers/counters (see
above), and TLP/DLLP-layer CRC (see above) -- this is a real, structurally
honest top-level LTSSM skeleton, not an attempt at a full production-grade
PCIe LTSSM VIP.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

from .generator import sv_id
from ..qualification import QualificationTier


# ---------------------------------------------------------------------------
# Top-level LTSSM state graph
# ---------------------------------------------------------------------------

# Deterministic order used for SV enum emission (dict/set iteration order is
# not something generated source text should ever depend on for human
# readability).
LTSSM_STATE_ORDER = (
    "DETECT", "POLLING", "CONFIGURATION", "L0", "L0S", "L1", "L2",
    "RECOVERY", "DISABLED", "LOOPBACK", "HOT_RESET",
)
LTSSM_STATES = frozenset(LTSSM_STATE_ORDER)

# Placeholder used by generators/consumers that need to represent "some real
# sub-state exists here, but this pass does not assert which one or its
# timing" -- see the CONFIDENCE section above. Deliberately opaque: never
# treat this as a real spec-defined sub-state name.
LTSSM_SUBSTATE_PLACEHOLDER = "NEEDS_SPEC_VERIFICATION_SUBSTATE"

# States from which Recovery may be entered to retrain the link (Recovery is
# the spec's common "re-establish/retrain the link" hub, reachable from L0/
# L0s/L1 -- deliberately NOT from L2: L2 is the deepest, aux-power-only sleep
# state, and exiting it requires a full re-detect (L2->Detect below), not an
# in-place retrain, so L2->RECOVERY is intentionally excluded rather than
# added by a blanket rule).
_RECOVERY_SOURCES = ("L0", "L0S", "L1")

# The "normal" (non-Hot-Reset, non-Disabled) top-level edges. Every edge here
# is one this pass is confident is a real, published LTSSM transition -- see
# the module docstring's CONFIDENCE section for what was deliberately
# omitted instead of guessed.
_BASE_TRANSITIONS: dict[str, set[str]] = {
    "DETECT": {"POLLING"},
    "POLLING": {"CONFIGURATION", "DETECT"},
    "CONFIGURATION": {"L0", "DETECT"},
    "L0": {"L0S", "L1", "RECOVERY"},
    "L0S": {"L0", "RECOVERY"},
    "L1": {"L2", "RECOVERY"},
    "L2": {"DETECT"},
    "RECOVERY": {"L0", "DETECT"},
    "DISABLED": {"DETECT"},
    "LOOPBACK": {"DETECT"},
    "HOT_RESET": {"DETECT"},
}

# States that may enter Recovery (retrain) -- folded into _BASE_TRANSITIONS
# above via _RECOVERY_SOURCES rather than duplicated by hand.
for _src in _RECOVERY_SOURCES:
    _BASE_TRANSITIONS[_src].add("RECOVERY")

# Per the task's own directed, explicitly-confident rule: "any state ->
# Hot Reset" and "any state -> Disabled". Applied to every OPERATIONAL state
# (i.e. every state except Hot Reset and Disabled themselves -- neither of
# those transitions to the other or to itself is asserted here).
_OPERATIONAL_STATES = tuple(s for s in LTSSM_STATE_ORDER if s not in ("HOT_RESET", "DISABLED"))
for _src in _OPERATIONAL_STATES:
    _BASE_TRANSITIONS[_src].add("HOT_RESET")
    _BASE_TRANSITIONS[_src].add("DISABLED")

# Public, immutable transition table: state -> frozenset of legal targets.
LTSSM_TRANSITIONS: dict[str, frozenset] = {
    state: frozenset(targets) for state, targets in _BASE_TRANSITIONS.items()
}

assert set(LTSSM_TRANSITIONS.keys()) == LTSSM_STATES  # every state has a row, none silently missing


# ---------------------------------------------------------------------------
# Typed error + pure validators
# ---------------------------------------------------------------------------

class LTSSMError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def validate_transition(state_from: str, state_to: str) -> bool:
    """Pure function: True if state_to is a legal target of state_from per
    LTSSM_TRANSITIONS. Raises LTSSMError -- never returns False -- so a
    caller can never accidentally ignore an illegal transition by forgetting
    to check a boolean return value.

    LTSSMError("UNKNOWN_LTSSM_STATE", ...) if either state is not one of the
    11 modeled top-level states (e.g. a typo, or a sub-state name that
    should have been mapped to LTSSM_SUBSTATE_PLACEHOLDER first).
    LTSSMError("ILLEGAL_LTSSM_TRANSITION", ...) if both states are known but
    state_to is not in state_from's legal-target set."""
    if state_from not in LTSSM_STATES:
        raise LTSSMError("UNKNOWN_LTSSM_STATE", {"field": "state_from", "state": state_from,
                                                   "known_states": sorted(LTSSM_STATES)})
    if state_to not in LTSSM_STATES:
        raise LTSSMError("UNKNOWN_LTSSM_STATE", {"field": "state_to", "state": state_to,
                                                   "known_states": sorted(LTSSM_STATES)})
    if state_to not in LTSSM_TRANSITIONS[state_from]:
        raise LTSSMError("ILLEGAL_LTSSM_TRANSITION", {
            "from": state_from, "to": state_to,
            "legal_targets": sorted(LTSSM_TRANSITIONS[state_from]),
        })
    return True


def simulate_training_sequence(events: list) -> dict:
    """The checker logic a scoreboard would use to catch an illegal link-
    training transition observed on the DUT: given an ORDERED list of
    {"from": str, "to": str} transition attempts, apply validate_transition
    to each in sequence and stop at the FIRST illegal one.

    Continuing to "validate" events after the first illegal transition would
    mean checking claimed transitions against a DUT state that is no longer
    known to be real -- once one transition is illegal, later "from" states
    downstream of it are not trustworthy evidence (CLAUDE.md's Evidence Truth
    Rule: memory/assumption is not current evidence). So this stops there,
    exactly like a real scoreboard should on the first spec violation.

    Returns:
      {
        "steps": [{"index": i, "from": f, "to": t, "legal": bool,
                    ["reason": ..., "detail": ...] if illegal}, ...],
        "state_history": [states actually visited, up to the halt point],
        "halted_at_index": int or None,
        "illegal_transition": None or {"index", "from", "to", "reason", "detail"},
        "completed": bool,  # True iff every event validated legal
      }
    """
    if not events:
        raise LTSSMError("EMPTY_EVENT_SEQUENCE", {})

    steps = []
    state_history = [events[0]["from"]]
    illegal = None
    for i, ev in enumerate(events):
        f, t = ev["from"], ev["to"]
        try:
            validate_transition(f, t)
        except LTSSMError as exc:
            steps.append({"index": i, "from": f, "to": t, "legal": False,
                           "reason": exc.reason, "detail": exc.detail})
            illegal = {"index": i, "from": f, "to": t, "reason": exc.reason, "detail": exc.detail}
            break
        steps.append({"index": i, "from": f, "to": t, "legal": True})
        state_history.append(t)

    return {
        "steps": steps,
        "state_history": state_history,
        "halted_at_index": illegal["index"] if illegal else None,
        "illegal_transition": illegal,
        "completed": illegal is None,
    }


# ---------------------------------------------------------------------------
# Generic CRC wrapper (NOT PCIe LCRC/ECRC -- see module docstring)
# ---------------------------------------------------------------------------

def compute_lane_crc(bits) -> int:
    """Minimal, generic CRC-32 (the IEEE 802.3 / zlib/binascii polynomial,
    0xEDB88320 reflected form) wrapper over `bits`.

    `bits` may be:
      - bytes/bytearray: used directly as the byte stream to checksum.
      - an iterable of 0/1 ints: packed MSB-first into bytes (zero-padded on
        the right to a byte boundary) before checksumming.

    NOT IMPLEMENTED HERE, deliberately (out of scope for this pass, correctly
    flagged rather than guessed): PCIe's actual TLP LCRC and end-to-end ECRC
    polynomials/bit-ordering are protocol-specific and were not verified with
    confidence in this pass. This function is a generic reusable primitive
    only -- do not treat its output as a real PCIe LCRC/ECRC value."""
    if isinstance(bits, (bytes, bytearray)):
        data = bytes(bits)
    else:
        bit_list = list(bits)
        if not all(b in (0, 1) for b in bit_list):
            raise LTSSMError("INVALID_CRC_INPUT", {
                "detail": "bits must be bytes/bytearray, or an iterable of 0/1 ints",
            })
        pad = (-len(bit_list)) % 8
        bit_list = bit_list + [0] * pad
        out = bytearray()
        for i in range(0, len(bit_list), 8):
            byte = 0
            for b in bit_list[i:i + 8]:
                byte = (byte << 1) | b
            out.append(byte)
        data = bytes(out)
    return zlib.crc32(data) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Topology validation
# ---------------------------------------------------------------------------

# x1/x2/x4/x8/x12/x16/x32 -- the published PCIe Link Width field encoding
# values, a stable structural fact (not a guessed number).
VALID_LANE_WIDTHS = frozenset({1, 2, 4, 8, 12, 16, 32})
VALID_ROLES = frozenset({"RC", "EP"})


class LTSSMTopologyError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def validate_ltssm_topology(t: dict) -> None:
    lane_width = t.get("lane_width")
    if lane_width not in VALID_LANE_WIDTHS:
        raise LTSSMTopologyError("INVALID_LANE_WIDTH", {
            "lane_width": lane_width, "valid_lane_widths": sorted(VALID_LANE_WIDTHS),
        })
    role = t.get("role")
    if role not in VALID_ROLES:
        raise LTSSMTopologyError("INVALID_ROLE", {"role": role, "valid_roles": sorted(VALID_ROLES)})
    gen_speed = t.get("gen_speed")
    if not isinstance(gen_speed, str) or not gen_speed.strip():
        # gen_speed is deliberately treated as an OPAQUE plain-string label
        # (per task spec) -- no attempt is made here to validate it against a
        # GT/s numeric table, since exact per-generation rate constants are
        # exactly the kind of spec-exact detail this pass is not confident
        # enough to hardcode. Only "is it a non-empty string" is checked.
        raise LTSSMTopologyError("INVALID_GEN_SPEED_LABEL", {"gen_speed": gen_speed})


# ---------------------------------------------------------------------------
# SV generator
# ---------------------------------------------------------------------------

class PCIeLTSSMGenerator:
    """Analogous to AMBAFabricGenerator: takes a topology JSON (lane_width,
    gen_speed as an opaque string label, role RC|EP), emits an SV LTSSM
    state-register + transition-check module skeleton, a topology JSON, and
    an environment_manifest.json entry -- all derived directly from
    LTSSM_TRANSITIONS so the emitted SV legality table and the Python model
    above can never silently drift apart."""

    def __init__(self, out_dir):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def generate(self, t: dict):
        validate_ltssm_topology(t)
        name = sv_id(t.get("name", "pcie_ltssm"))

        files = {}
        files[f"{name}_ltssm_pkg.sv"] = self.ltssm_pkg(t, name)
        files[f"{name}_ltssm_state_reg.sv"] = self.ltssm_state_reg(t, name)
        files["filelist.f"] = "\n".join([f"{name}_ltssm_pkg.sv", f"{name}_ltssm_state_reg.sv"]) + "\n"

        ltssm_topology = {
            "states": list(LTSSM_STATE_ORDER),
            "transitions": {s: sorted(LTSSM_TRANSITIONS[s]) for s in LTSSM_STATE_ORDER},
            "lane_width": t["lane_width"],
            "gen_speed": t["gen_speed"],
            "role": t["role"],
        }
        files["ltssm_topology.json"] = json.dumps(ltssm_topology, indent=2)

        manifest = dict(t)
        manifest["ltssm_states"] = list(LTSSM_STATE_ORDER)
        manifest["generated_files"] = sorted(files.keys()) + ["environment_manifest.json"]
        manifest["qualification_status"] = QualificationTier.ENV_GENERATED.value
        manifest.setdefault("vip", {})["binding_status"] = "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        manifest["substate_note"] = (
            "Sub-states are NOT modeled with real names/timeouts in this pass "
            f"(see module docstring); any sub-state is a '{LTSSM_SUBSTATE_PLACEHOLDER}' placeholder."
        )
        files["environment_manifest.json"] = json.dumps(manifest, indent=2)

        for fname, content in files.items():
            (self.out / fname).write_text(content, encoding="utf-8")
        return sorted(files.keys())

    def ltssm_pkg(self, t, name):
        enum_members = ", ".join(LTSSM_STATE_ORDER)
        case_lines = []
        for state in LTSSM_STATE_ORDER:
            targets = sorted(LTSSM_TRANSITIONS[state])
            targets_text = ", ".join(targets)
            case_lines.append(f"      {state}: return (to_state inside {{{targets_text}}});")
        case_text = "\n".join(case_lines)
        return f"""// {name}_ltssm_pkg.sv -- LTSSM top-level state enum + transition-legality
// function, generated DIRECTLY from dv_harness/uvm_generator/
// pcie_ltssm_generator.py's LTSSM_TRANSITIONS table (see that module's
// docstring for the CONFIDENCE / NEEDS SPEC VERIFICATION boundary). Sub-
// states are deliberately NOT enumerated here -- see LTSSM_SUBSTATE_PLACEHOLDER
// in the Python model; adapt this enum with real sub-states only once their
// exact spec names/timing have been verified against current spec evidence.
package {name}_ltssm_pkg;
  typedef enum {{ {enum_members} }} ltssm_state_e;

  // Same legality rule as Python's validate_transition() / LTSSM_TRANSITIONS
  // -- kept in lockstep with the Python model by construction (this text is
  // generated from that same table, not hand-duplicated).
  function automatic bit ltssm_transition_legal(ltssm_state_e from_state, ltssm_state_e to_state);
    case (from_state)
{case_text}
      default: return 1'b0;
    endcase
  endfunction
endpackage
"""

    def ltssm_state_reg(self, t, name):
        return f"""// {name}_ltssm_state_reg.sv -- LTSSM state register + transition-legality
// check skeleton. LANE_WIDTH/GEN_SPEED/ROLE come from the supplied topology
// ({t["lane_width"]} lane(s), gen_speed="{t["gen_speed"]}" (opaque label, not
// interpreted as a GT/s number -- see module docstring), role={t["role"]}).
// Task-based (not always_comb) because a real transition request/ack
// protocol is inherently sequential -- adapt the request/ack handshake to
// the actual DUT LTSSM control interface once discovered from current RTL.
module {name}_ltssm_state_reg #(
  parameter int LANE_WIDTH = {t["lane_width"]}
)(
  input  logic clk,
  input  logic rst_n,
  input  logic req_valid,
  input  {name}_ltssm_pkg::ltssm_state_e req_next_state,
  output {name}_ltssm_pkg::ltssm_state_e state_q,
  output logic illegal_transition_flag
);
  import {name}_ltssm_pkg::*;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_q <= DETECT;
      illegal_transition_flag <= 1'b0;
    end else if (req_valid) begin
      if (ltssm_transition_legal(state_q, req_next_state)) begin
        state_q <= req_next_state;
        illegal_transition_flag <= 1'b0;
      end else begin
        // Illegal transition observed: hold state, raise the flag for the
        // scoreboard/checker layer (see simulate_training_sequence()'s
        // Python-side equivalent) rather than silently accepting it.
        illegal_transition_flag <= 1'b1;
      end
    end
  end
endmodule
"""
