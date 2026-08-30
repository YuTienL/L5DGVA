"""dv_harness/uvm_generator/emmc_cmdq_generator.py -- eMMC/SD Command Queue
(CQ) tag-based out-of-order request/completion scoreboard model generator.

BUG FIX (2026-08-29, parity audit gap): the parity audit identified that
eMMC/MMC and SD/SDIO need "a CMDQ tag-based out-of-order request/completion
scoreboard (structurally different from AMBA's static M x N pairing)" --
dv_harness/uvm_generator/amba_fabric_generator.py's scoreboard model is a
static per-(master,slave)-pair matrix resolved once at generation time, which
is the WRONG shape for CMDQ: a real eMMC 5.1 Command Queue issues up to 32
independently-tagged requests (tag in [0,31], per JEDEC JESD84-B51) that can
each complete in ANY order relative to the others, and the thing that can go
wrong is a RUNTIME tag-lifecycle violation (reusing an outstanding tag,
completing a tag that was never issued, or leaving a tag outstanding at
end-of-test) -- not a static address-decode/connectivity resolution. This
module fills that gap with a real, generic tag-lifecycle state machine
(issue_tag/complete_tag/check_final_state) plus an SV scoreboard skeleton
that carries the same shape into simulation.

CONFIDENCE / NEEDS SPEC VERIFICATION
-------------------------------------
- issue_tag/complete_tag/check_final_state model ONLY the generic tag
  lifecycle (outstanding-set membership, legal issue/complete transitions,
  end-of-test drain check). This is standardized-shape-generic: any
  tag-based out-of-order in-flight-request protocol (eMMC CQ, NVMe SQ/CQ,
  etc.) needs exactly this bookkeeping, and the JEDEC eMMC 5.1 spec's "up to
  32 tags" (num_tags=32 default) is a well-known, stable public number. HIGH
  CONFIDENCE.
- hs200_tuning_step models ONLY the generic shape of an iterative
  sample-and-converge binary-search-style tuning loop (try a value, observe
  pass/fail, narrow the search window, converge on the stable window's
  center). This generic convergence shape is common to HS200/HS400 tuning
  per the eMMC spec's CMD21 (SEND_TUNING_BLOCK, HS200) / CMD19 (equivalent
  in some contexts) tuning sequence -- but the EXACT CMD21/CMD19 command
  sequencing, the exact number of tuning-block iterations the spec mandates,
  the exact tap-window pass/fail sampling protocol, and any exact bit/field
  encoding are explicitly NOT modeled here and are flagged
  NEEDS SPEC VERIFICATION in that function's own docstring. LOWER
  CONFIDENCE than the tag-lifecycle functions above -- do not treat
  hs200_tuning_step as a certified model of the real CMD21 sequence.
- EMMCCmdqGenerator emits a bus-signal-agnostic SV skeleton (generic
  issue/complete task names, a generic outstanding-tag bit-vector) --
  it does NOT invent real eMMC host-controller register names, real
  CQTDBR/CQTCN/CQIS-style register addresses, or a real VIP class name (see
  "WHAT THIS DOES NOT DO" below).

WHAT THIS DOES NOT DO (deliberately, matching amba_fabric_generator.py's own
convention for genuinely protocol/DUT-specific detail that cannot be assumed
at generation time): no real eMMC host-controller register names or
addresses (e.g. no invented CQTDBR/CQTCN/CQIS bit-field names -- those are
real eMMC HC spec register names but this generator does not claim to know
their exact current-project register map without current RTL/register-map
evidence), no VIP package/agent binding (uses the same
PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE convention as
amba_fabric_generator.py / examples/generated_pcie_uvm_env/
environment_manifest.json), no exact CMD21/CMD19 tuning command-sequencing
detail (see hs200_tuning_step's docstring), and no actual DUT waveform/
runtime evidence (that is runtime evidence, not something generation time
can produce) -- this is a real, structurally-correct skeleton, not an
attempt at a full production-grade eMMC CQ VIP.
"""
from __future__ import annotations

import json
from pathlib import Path

from .generator import sv_id
from ..qualification import QualificationTier


class CMDQError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def issue_tag(outstanding, tag: int, num_tags: int = 32):
    """Pure function: issue a CMDQ request on `tag`.

    `outstanding` is a set/list of currently-outstanding tag ints (not
    mutated -- the updated set is returned). Per JEDEC eMMC 5.1 Command
    Queue: tag must be in [0, num_tags) (default num_tags=32, the spec's
    "up to 32 tags" limit), and reusing a tag that is already outstanding
    (its prior request has not yet completed) is a real protocol violation,
    not a benign no-op.
    """
    outstanding_set = set(outstanding)
    if not (0 <= tag < num_tags):
        raise CMDQError("TAG_OUT_OF_RANGE", {
            "tag": tag, "num_tags": num_tags,
            "detail": f"tag must be in [0, {num_tags})",
        })
    if tag in outstanding_set:
        raise CMDQError("TAG_ALREADY_OUTSTANDING", {
            "tag": tag, "outstanding": sorted(outstanding_set),
            "detail": "tag reused before its prior completion -- real CMDQ protocol violation",
        })
    outstanding_set.add(tag)
    return outstanding_set


def complete_tag(outstanding, tag: int):
    """Pure function: accept a completion for `tag`, in ANY order relative
    to other outstanding tags (that is the whole point of CMDQ out-of-order
    completion -- unlike AMBA's static M x N pairing, there is no fixed
    request/response ordering to check here, only tag-set membership).

    Raises CMDQError("COMPLETION_FOR_UNISSUED_TAG", ...) if `tag` is not
    currently outstanding (either it was never issued, or it already
    completed once and this is a duplicate/spurious completion) -- a real
    bug either way, and this function deliberately does not try to
    distinguish the two causes since `outstanding` alone cannot tell them
    apart; the caller's error `detail` carries the current outstanding set
    so a caller with fuller history can classify it themselves.
    """
    outstanding_set = set(outstanding)
    if tag not in outstanding_set:
        raise CMDQError("COMPLETION_FOR_UNISSUED_TAG", {
            "tag": tag, "outstanding": sorted(outstanding_set),
            "detail": "completion for a tag that was never issued, or was already completed",
        })
    outstanding_set.remove(tag)
    return outstanding_set


def check_final_state(outstanding):
    """End-of-test drain check: any nonempty `outstanding` at end-of-test is
    a real bug (a request that was issued but never completed -- a lost/
    stuck completion, or a request the DUT silently dropped). Returns a
    sorted list of stuck tags; an empty list means the tag lifecycle drained
    cleanly."""
    return sorted(set(outstanding))


def hs200_tuning_step(state: dict, sample_result: bool) -> dict:
    """LOWER-CONFIDENCE, generic model of an iterative sample-and-converge
    tuning control loop -- the GENERIC shape common to HS200/HS400 tap/delay
    tuning (per the eMMC spec's CMD21/CMD19 tuning sequence), implemented as
    a plain binary-search-style window-narrowing convergence algorithm.

    NEEDS SPEC VERIFICATION: this function does NOT claim exact eMMC
    register/command-index fidelity. In particular, NOT modeled here and
    left for a caller with real spec/register evidence to add: the exact
    CMD21 (SEND_TUNING_BLOCK) vs CMD19 command selection and sequencing,
    the exact number of tuning iterations or retry rules the spec mandates,
    the exact tuning-block data pattern/comparison, and any exact
    register-level tap-value encoding. Only the generic "try a value in a
    search window, get pass/fail, narrow the window, converge on the stable
    window's center" shape is modeled, as a conservative placeholder.

    `state`: {"low": int, "high": int, "current_tap": int, "converged": bool,
    "final_tap": int|None} -- `low`/`high` bound the current candidate
    window (inclusive), `current_tap` is the tap value just sampled.
    `sample_result`: True if `current_tap` passed the tuning sample, False
    if it failed.

    Returns the updated state dict. Convergence rule (generic
    binary-search-on-a-window): a failing sample narrows the window by
    excluding the failing side (below current_tap if the search direction
    is narrowing from below, else above); once low == high the window has
    converged to a single stable tap and `converged` is set True with
    `final_tap` set to that value.
    """
    if state.get("converged"):
        return dict(state)

    low = state["low"]
    high = state["high"]
    current_tap = state["current_tap"]

    if sample_result:
        # This tap passed -- it can anchor a narrower window on the
        # passing side; narrow from below (assume monotonic pass region
        # from current_tap upward, a conservative generic assumption --
        # NEEDS SPEC VERIFICATION against the real tuning-block pass
        # pattern for this project's specific tap-window shape).
        low = current_tap
    else:
        # This tap failed -- exclude it and everything below it from the
        # window (same conservative monotonic assumption as above).
        high = current_tap - 1

    if low >= high:
        final_tap = min(low, high) if low != high else low
        return {
            "low": low, "high": high, "current_tap": final_tap,
            "converged": True, "final_tap": final_tap,
        }

    next_tap = (low + high) // 2
    return {
        "low": low, "high": high, "current_tap": next_tap,
        "converged": False, "final_tap": None,
    }


class EMMCCmdqGenerator:
    """Analogous to AMBAFabricGenerator: takes a topology JSON (num_tags,
    whether HS200/HS400 tuning modeling is requested) and emits an SV CMDQ
    scoreboard module skeleton, a topology JSON, and an
    environment_manifest.json entry."""

    def __init__(self, out_dir):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def generate(self, t: dict):
        name = sv_id(t.get("module_name", "emmc_cmdq_scoreboard"))
        num_tags = t.get("num_tags", 32)
        if not isinstance(num_tags, int) or num_tags <= 0:
            raise CMDQError("INVALID_NUM_TAGS", {"num_tags": num_tags})
        include_tuning = bool(t.get("include_hs200_tuning", False))

        files = {}
        files[f"{name}.sv"] = self.scoreboard_sv(t, name, num_tags, include_tuning)

        manifest = dict(t)
        manifest["num_tags"] = num_tags
        manifest["include_hs200_tuning"] = include_tuning
        manifest["generated_files"] = sorted(files.keys()) + [
            "environment_manifest.json", "emmc_cmdq_topology.json",
        ]
        manifest["qualification_status"] = QualificationTier.ENV_GENERATED.value
        manifest.setdefault("vip", {})["binding_status"] = "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        files["environment_manifest.json"] = json.dumps(manifest, indent=2)

        topology = {
            "module_name": name,
            "num_tags": num_tags,
            "include_hs200_tuning": include_tuning,
            "scoreboard_shape": "TAG_BASED_OUT_OF_ORDER",
        }
        files["emmc_cmdq_topology.json"] = json.dumps(topology, indent=2)

        for fname, content in files.items():
            (self.out / fname).write_text(content, encoding="utf-8")
        return sorted(files.keys())

    def scoreboard_sv(self, t, name, num_tags, include_tuning):
        tuning_task = self._tuning_task_sv(name) if include_tuning else (
            "  // HS200/HS400 tuning modeling not requested for this topology\n"
            "  // (include_hs200_tuning=false) -- see hs200_tuning_step's Python\n"
            "  // model for the generic converge-on-a-window shape if needed later."
        )
        return f"""// {name}: eMMC/SD CQ tag-based out-of-order request/completion scoreboard.
// Structurally different from AMBA's static M x N pairing (see
// amba_fabric_generator.py's scoreboard_matrix): this tracks a per-tag
// outstanding bit vector across NUM_TAGS in-flight requests, each of which
// may complete in any order relative to the others (JEDEC eMMC 5.1 Command
// Queue, up to 32 tags). Bus-signal-agnostic port names (issue_tag/
// issue_valid/complete_tag/complete_valid) -- the real eMMC host-controller
// register names (e.g. CQTDBR/CQTCN/CQIS-style doorbell/completion
// registers) are deliberately NOT invented here; bind this skeleton's tasks
// to the discovered project's actual register-map evidence.
module {name} #(
  parameter int NUM_TAGS = {num_tags}
)(
  input logic clk,
  input logic rst_n,
  input logic issue_valid,
  input logic [$clog2(NUM_TAGS)-1:0] issue_tag,
  input logic complete_valid,
  input logic [$clog2(NUM_TAGS)-1:0] complete_tag,
  output logic protocol_error
);
  // outstanding[i] == 1 means tag i has been issued and not yet completed.
  logic [NUM_TAGS-1:0] outstanding;

  initial outstanding = '0;

  // task automatic do_issue: mirrors the Python issue_tag() lifecycle rule
  // -- TAG_ALREADY_OUTSTANDING is a real protocol violation, not a no-op.
  task automatic do_issue(input int tag);
    if (outstanding[tag]) begin
      protocol_error = 1'b1;
      $error("{name}: TAG_ALREADY_OUTSTANDING tag=%0d", tag);
    end else begin
      outstanding[tag] = 1'b1;
    end
  endtask

  // task automatic do_complete: mirrors the Python complete_tag() lifecycle
  // rule -- COMPLETION_FOR_UNISSUED_TAG covers both "never issued" and
  // "already completed" (an already-outstanding-cleared tag reads the same
  // as never-issued from `outstanding` alone).
  task automatic do_complete(input int tag);
    if (!outstanding[tag]) begin
      protocol_error = 1'b1;
      $error("{name}: COMPLETION_FOR_UNISSUED_TAG tag=%0d", tag);
    end else begin
      outstanding[tag] = 1'b0;
    end
  endtask

  // task automatic check_final_state: end-of-test drain check -- mirrors
  // the Python check_final_state() rule that any nonempty outstanding set
  // at end-of-test is a real bug (issued but never completed).
  task automatic check_final_state();
    if (outstanding != '0) begin
      protocol_error = 1'b1;
      $error("{name}: STUCK_TAGS_AT_END_OF_TEST outstanding=%b", outstanding);
    end
  endtask

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      outstanding <= '0;
      protocol_error <= 1'b0;
    end else begin
      if (issue_valid) do_issue(issue_tag);
      if (complete_valid) do_complete(complete_tag);
    end
  end

{tuning_task}
endmodule
"""

    def _tuning_task_sv(self, name):
        return f"""  // task automatic tuning_step: LOWER-CONFIDENCE generic placeholder for
  // the HS200/HS400 CMD21/CMD19 tuning sequence's converge-on-a-window
  // shape -- see hs200_tuning_step()'s Python docstring for the full
  // NEEDS SPEC VERIFICATION notice. Do NOT treat this task as an exact
  // model of the real CMD21 sequencing; it is a structural placeholder
  // only, to be replaced once current spec/register evidence is available.
  task automatic tuning_step(input int low, input int high, input int current_tap,
                              input bit pass_result, output int next_low, output int next_high,
                              output int next_tap, output bit converged);
    // NEEDS SPEC VERIFICATION: exact CMD21/CMD19 sequencing, exact tuning
    // iteration count, exact tap-window pass pattern are not modeled here.
    if (pass_result) begin
      next_low = current_tap;
      next_high = high;
    end else begin
      next_low = low;
      next_high = current_tap - 1;
    end
    if (next_low >= next_high) begin
      converged = 1'b1;
      next_tap = (next_low < next_high) ? next_low : next_high;
    end else begin
      converged = 1'b0;
      next_tap = (next_low + next_high) / 2;
    end
  endtask
"""
