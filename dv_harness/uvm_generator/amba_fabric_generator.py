"""dv_harness/uvm_generator/amba_fabric_generator.py -- real AMBA M x N
multi-master/multi-slave UVM environment skeleton generator.

BUG FIX (2026-08-28, plan-amba-mxn-generator design pass): "AMBA M x N 完整
支援" was aspirational -- .claude/skills/PROTOCOL_BUILDERS/
amba4-soc-environment-builder/SKILL.md has real, rigorous algorithmic prose
(deterministic address-decode overlap/gap/coverage check, an ID-width
formula, an M x N scoreboard/coverage completeness rule), and
tools/verification_flow/fabric_topology_completeness_gate.py is a real
VALIDATOR for a supplied topology JSON -- but nothing took M/N as parameters
and actually emitted UVM/SV files for a multi-master/multi-slave
interconnect. The only real SV-emitting generator in the repo (generator.py,
this module's sibling) is orphaned AND structurally single-agent (one
env/config/scoreboard/vseqr set per invocation) -- incapable of M x N output
even if wired up.

This module computes the REAL algorithms (address-decode overlap/gap/
full-coverage check, the ID-width formula, per-pair scoreboard-matrix
resolution) in Python -- not just comments -- then emits real SV skeleton
code carrying the computed values (module ports, an actual case-statement
address decoder, an M-wide sequencer array, a per-pair checker/covergroup
structure), plus a topology JSON that is schema-exact for
fabric_topology_completeness_gate.py.

WHAT THIS DOES NOT DO (deliberately, matching generator.py's own
"# Bind DUT and VIP interfaces from environment_manifest.json/current
evidence." convention for genuinely protocol/DUT-specific detail that cannot
be assumed): actual AXI/AHB/APB handshake signal names and burst/wrap/
exclusive/QoS logic (the sub-protocol is not yet discovered from RTL at
generation time -- the decoder below is deliberately bus-signal-agnostic:
`addr`/`slave_sel`, adapt to the discovered sub-protocol's real channel
names), VIP package/agent binding (uses the PLACEHOLDER_UNTIL_CURRENT_
VIP_EVIDENCE convention already established in
examples/generated_pcie_uvm_env/environment_manifest.json), scoreboard
comparison-rule bodies beyond structural per-pair pairing, and actual
DECERR-response coverage sampling (that is runtime evidence, not something
generation time can produce). This is a real, structurally-correct skeleton,
not an attempt at a full production-grade AMBA VIP -- that distinction is the
line CLAUDE.md's Evidence Truth Rule draws between "generated" and
"qualified".
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .generator import sv_id
from ..qualification import QualificationTier


def parse_addr(v):
    """Same semantics as fabric_topology_completeness_gate.py's parse_addr:
    int passthrough, or a string (optionally underscore-grouped, optionally
    0x/0b-prefixed) parsed via int(s, 0)."""
    if isinstance(v, int):
        return v
    s = str(v).strip().replace("_", "")
    return int(s, 0)


def compute_id_width(masters) -> int:
    """W_out_required = ceil(log2(M)) + max_m(I_m), per
    amba4-soc-environment-builder/SKILL.md's ID-width propagation rule.
    `masters` is a list of {"id": str, "id_width": int} dicts (this
    generator's own topology schema -- richer than the gate's flat id-string
    list). math.ceil(math.log2(1)) == 0, so M==1 needs no special case."""
    if not masters:
        raise ValueError("compute_id_width requires at least one master")
    m = len(masters)
    max_i = max(mm["id_width"] for mm in masters)
    return math.ceil(math.log2(m)) + max_i


class AddressMapError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def compute_address_regions(slaves, reserved_regions, addr_width: int):
    """Builds the sorted region list and validates it against the EXACT same
    adjacency semantics tools/verification_flow/fabric_topology_completeness_gate.py
    enforces: end is EXCLUSIVE (end = base + size, not the SKILL.md prose's
    "end = base+size-1"), confirmed by reading that gate's own comparisons
    (`cur.start < prev.end` == overlap, `cur.start > prev.end` == gap, so
    perfectly adjacent regions satisfy `cur.start == prev.end`). A region set
    that passes here is guaranteed to pass that gate's own check.

    Additionally enforces SKILL.md step (4)'s full [0, 2**addr_width)
    coverage requirement, which the gate itself does NOT check (the gate
    only checks no-gap/no-overlap between DECLARED regions, not that they
    span the whole address space) -- a deliberate, stricter generator-side
    check: a generator should never emit a topology with a silently unmapped
    residual region, even though the validator gate would let one slip through
    as long as no DECLARED regions overlap or gap against each other."""
    entries = []
    for s in slaves:
        base = parse_addr(s["base_addr"])
        size = parse_addr(s["size"])
        entries.append({"owner": s["id"], "owner_kind": "SLAVE", "start": base, "end": base + size})
    for r in (reserved_regions or []):
        base = parse_addr(r["base_addr"])
        size = parse_addr(r["size"])
        kind = "DECODE_ERROR" if r.get("decerr") else "RESERVED"
        entries.append({"owner": r["name"], "owner_kind": kind, "start": base, "end": base + size})

    if not entries:
        raise AddressMapError("SLAVE_WITHOUT_ADDRESS_RANGE", {"slaves": [s["id"] for s in slaves]})

    entries.sort(key=lambda e: e["start"])
    for prev, cur in zip(entries, entries[1:]):
        if cur["start"] < prev["end"]:
            raise AddressMapError("ADDRESS_MAP_OVERLAP", {
                "region_a": {"owner": prev["owner"], "start": prev["start"], "end": prev["end"]},
                "region_b": {"owner": cur["owner"], "start": cur["start"], "end": cur["end"]},
            })
        if cur["start"] > prev["end"]:
            raise AddressMapError("ADDRESS_MAP_GAP", {
                "after": {"owner": prev["owner"], "end": prev["end"]},
                "before": {"owner": cur["owner"], "start": cur["start"]},
                "gap_size": cur["start"] - prev["end"],
            })

    full_space = 1 << addr_width
    if entries[0]["start"] != 0 or entries[-1]["end"] != full_space:
        raise AddressMapError("ADDRESS_MAP_NOT_FULL_COVERAGE", {
            "expected_range": [0, full_space],
            "actual_start": entries[0]["start"], "actual_end": entries[-1]["end"],
        })

    return entries


class ScoreboardMatrixError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def build_scoreboard_matrix(masters, slaves, connectivity, assume_full_connectivity: bool):
    """Resolves every (master, slave) pair to IMPLEMENTED or WAIVED -- never
    guesses. Per CLAUDE.md's Evidence Truth Rule applied to generation time:
    a scoreboard/exclusion claim must come from real connectivity evidence
    (`connectivity`) or an explicit, opt-in `assume_full_connectivity` bulk
    declaration -- never fabricated silently. An unresolved pair (neither
    accessible nor explicitly excluded-with-evidence) is a hard FAIL, not a
    default guess in either direction.

    `connectivity`, if given: {master_id: {"accessible_slaves": [slave_id,...],
    "excluded": [{"slave_id":..., "waiver_evidence": str}, ...]}}."""
    matrix = []
    for m in masters:
        mid = m["id"]
        conn = (connectivity or {}).get(mid)
        accessible = set(conn.get("accessible_slaves", [])) if conn else set()
        excluded = {e["slave_id"]: e.get("waiver_evidence") for e in (conn.get("excluded", []) if conn else [])}
        for s in slaves:
            sid = s["id"]
            if assume_full_connectivity and connectivity is None:
                matrix.append({"master_id": mid, "slave_id": sid, "status": "IMPLEMENTED"})
                continue
            if conn is None:
                raise ScoreboardMatrixError("NO_CONNECTIVITY_EVIDENCE", {
                    "master_id": mid, "slave_id": sid,
                    "detail": "supply `connectivity` per-master evidence, or opt into "
                              "assume_full_connectivity=true for a bulk declaration",
                })
            if sid in excluded and excluded[sid]:
                matrix.append({"master_id": mid, "slave_id": sid, "status": "WAIVED",
                                "waiver_approved": True, "waiver_evidence": excluded[sid]})
            elif sid in accessible:
                matrix.append({"master_id": mid, "slave_id": sid, "status": "IMPLEMENTED"})
            else:
                raise ScoreboardMatrixError("UNRESOLVED_PAIR", {
                    "master_id": mid, "slave_id": sid,
                    "detail": "neither in accessible_slaves nor excluded-with-waiver_evidence",
                })
    return matrix


class AMBAFabricGenerator:
    def __init__(self, out_dir):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def generate(self, t: dict):
        fabric = sv_id(t.get("fabric_name", "amba_fabric"))
        w_id = compute_id_width(t["masters"])
        regions = compute_address_regions(t["slaves"], t.get("reserved_regions", []), t["addr_width"])
        matrix = build_scoreboard_matrix(t["masters"], t["slaves"], t.get("connectivity"),
                                          t.get("assume_full_connectivity", False))

        files = {}
        files[f"{fabric}_addr_decoder.sv"] = self.addr_decoder(t, fabric, regions)
        files[f"{fabric}_env_pkg.sv"] = self.env_pkg(t, fabric, w_id)
        files[f"{fabric}_config.sv"] = self.config(t, fabric)
        files[f"{fabric}_virtual_sequencer.sv"] = self.virtual_sequencer(t, fabric)
        files[f"{fabric}_base_vseq.sv"] = self.base_vseq(t, fabric)
        files[f"{fabric}_scoreboard_matrix.sv"] = self.scoreboard_matrix_sv(t, fabric, matrix)
        files[f"{fabric}_env.sv"] = self.env(t, fabric)
        smoke_tests = t.get("smoke_tests") or [{"name": "smoke"}]
        for st in smoke_tests:
            name = sv_id(st.get("name", "smoke"))
            files[f"{fabric}_{name}_test.sv"] = self.smoke_test(t, fabric, name)
        files["tb_top.sv"] = self.tb_top(t, fabric)
        files["filelist.f"] = "\n".join([
            f"{fabric}_env_pkg.sv", f"{fabric}_addr_decoder.sv", "tb_top.sv",
        ]) + "\n"

        manifest = dict(t)
        manifest["id_width_out"] = w_id
        manifest["generated_files"] = sorted(files.keys()) + ["environment_manifest.json", "fabric_topology.json"]
        manifest["qualification_status"] = QualificationTier.ENV_GENERATED.value
        manifest.setdefault("vip", {})["binding_status"] = "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        files["environment_manifest.json"] = json.dumps(manifest, indent=2)

        fabric_topology = {
            "masters": [m["id"] for m in t["masters"]],
            "slaves": [s["id"] for s in t["slaves"]],
            "scoreboard_matrix": matrix,
            "address_map": [
                {"owner": r["owner"], "owner_kind": r["owner_kind"],
                 "start_addr": hex(r["start"]), "end_addr": hex(r["end"])}
                for r in regions
            ],
        }
        files["fabric_topology.json"] = json.dumps(fabric_topology, indent=2)

        for name, content in files.items():
            (self.out / name).write_text(content, encoding="utf-8")
        return sorted(files.keys())

    def addr_decoder(self, t, fabric, regions):
        addr_width = t["addr_width"]
        num_slaves = len(t["slaves"])
        slave_index = {s["id"]: i for i, s in enumerate(t["slaves"])}
        cases = []
        for r in regions:
            if r["owner_kind"] != "SLAVE":
                continue
            idx = slave_index[r["owner"]]
            cases.append(
                f"      (addr >= {addr_width}'h{r['start']:x} && addr < {addr_width}'h{r['end']:x}): "
                f"slave_sel[{idx}] = 1'b1; // {r['owner']}"
            )
        cases_text = "\n".join(cases)
        return f"""// Address decoder for {fabric} -- computed from the validated address map
// (compute_address_regions), not a placeholder. Deliberately bus-agnostic
// port names (addr/slave_sel), since the specific AXI/AHB/APB sub-protocol's
// real channel names are not yet known at generation time -- adapt this
// skeleton's ports to the discovered sub-protocol's actual read/write
// address channels.
module {fabric}_addr_decoder #(
  parameter int ADDR_WIDTH = {addr_width},
  parameter int NUM_SLAVES = {num_slaves}
)(
  input  logic [ADDR_WIDTH-1:0] addr,
  output logic [NUM_SLAVES-1:0] slave_sel,
  output logic                  decode_err
);
  always_comb begin
    slave_sel = '0;
    decode_err = 1'b0;
    unique case (1'b1)
{cases_text}
      default: decode_err = 1'b1;
    endcase
  end
endmodule
"""

    def env_pkg(self, t, fabric, w_id):
        m = len(t["masters"])
        max_i = max(mm["id_width"] for mm in t["masters"])
        includes = "\n".join(f'  `include "{fabric}_{name}.sv"' for name in
                              ("config", "virtual_sequencer", "base_vseq", "scoreboard_matrix", "env"))
        return f"""package {fabric}_env_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  // W_out_required = ceil(log2(M)) + max(I_m) = ceil(log2({m})) + {max_i} = {w_id}
  localparam int ID_WIDTH_OUT = {w_id};
{includes}
endpackage
"""

    def config(self, t, fabric):
        return f"""class {fabric}_config extends uvm_object;
  `uvm_object_utils({fabric}_config)
  int unsigned num_masters = {len(t["masters"])};
  int unsigned num_slaves = {len(t["slaves"])};
  function new(string name="{fabric}_config"); super.new(name); endfunction
endclass
"""

    def virtual_sequencer(self, t, fabric):
        m = len(t["masters"])
        handles = "\n".join(f'  uvm_sequencer_base m_seqr[{m}]; // one per master, M={m}')
        return f"""class {fabric}_virtual_sequencer extends uvm_sequencer #(uvm_sequence_item);
  `uvm_component_utils({fabric}_virtual_sequencer)
{handles}
  function new(string name="{fabric}_virtual_sequencer", uvm_component parent=null);
    super.new(name, parent);
  endfunction
endclass
"""

    def base_vseq(self, t, fabric):
        masters = t["masters"]
        fork_bodies = "\n".join(
            f'      fork begin : m_{sv_id(mm["id"])}\n'
            f'        // master {mm["id"]}: drive its own traffic on p_sequencer.m_seqr[{i}]\n'
            f'      end join_none'
            for i, mm in enumerate(masters)
        )
        return f"""class {fabric}_base_vseq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils({fabric}_base_vseq)
  `uvm_declare_p_sequencer({fabric}_virtual_sequencer)
  function new(string name="{fabric}_base_vseq"); super.new(name); endfunction
  virtual task body();
    // Real M-way parallel-master structure (M={len(masters)}), not a single
    // linear task -- each master's sub-sequence forks independently.
{fork_bodies}
    wait fork;
  endtask
endclass
"""

    def scoreboard_matrix_sv(self, t, fabric, matrix):
        checkers = []
        cross_ignore = []
        for entry in matrix:
            mid, sid = entry["master_id"], entry["slave_id"]
            if entry["status"] == "IMPLEMENTED":
                checkers.append(f"  // checker chk_{sv_id(mid)}_{sv_id(sid)}: {mid} -> {sid}")
            else:
                cross_ignore.append(
                    f"    ignore_bins waived_{sv_id(mid)}_{sv_id(sid)} = "
                    f"binsof(cp_master) intersect {{{[m['id'] for m in t['masters']].index(mid)}}} && "
                    f"binsof(cp_slave) intersect {{{[s['id'] for s in t['slaves']].index(sid)}}}; "
                    f"// WAIVED: {entry.get('waiver_evidence', '')}"
                )
        checkers_text = "\n".join(checkers) or "  // no IMPLEMENTED pairs"
        ignore_text = "\n".join(cross_ignore)
        return f"""class {fabric}_scoreboard_matrix extends uvm_scoreboard;
  `uvm_component_utils({fabric}_scoreboard_matrix)
  // One checker per IMPLEMENTED (master x slave) pair -- {len(t["masters"])} x {len(t["slaves"])}
  // = {len(t["masters"]) * len(t["slaves"])} total pairs, {sum(1 for e in matrix if e["status"] == "IMPLEMENTED")} IMPLEMENTED,
  // {sum(1 for e in matrix if e["status"] == "WAIVED")} WAIVED (see ignore_bins below).
{checkers_text}
  function new(string name="{fabric}_scoreboard_matrix", uvm_component parent=null);
    super.new(name, parent);
  endfunction

  covergroup cg_ms_cross;
    cp_master: coverpoint master_idx {{ bins m[] = {{[0:{len(t["masters"]) - 1}]}}; }}
    cp_slave:  coverpoint slave_idx  {{ bins s[] = {{[0:{len(t["slaves"]) - 1}]}}; }}
    cross cp_master, cp_slave {{
{ignore_text if ignore_text else "      // no WAIVED pairs"}
    }}
  endgroup
  int unsigned master_idx, slave_idx;
endclass
"""

    def env(self, t, fabric):
        return f"""class {fabric}_env extends uvm_env;
  `uvm_component_utils({fabric}_env)
  {fabric}_config cfg;
  {fabric}_virtual_sequencer vseqr;
  {fabric}_scoreboard_matrix sb;

  function new(string name="{fabric}_env", uvm_component parent=null); super.new(name, parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#({fabric}_config)::get(this, "", "cfg", cfg))
      cfg = {fabric}_config::type_id::create("cfg");
    vseqr = {fabric}_virtual_sequencer::type_id::create("vseqr", this);
    sb = {fabric}_scoreboard_matrix::type_id::create("sb", this);
    // Bind DUT and VIP interfaces from environment_manifest.json/current evidence.
  endfunction
endclass
"""

    def smoke_test(self, t, fabric, name):
        return f"""class {fabric}_{name}_test extends uvm_test;
  `uvm_component_utils({fabric}_{name}_test)
  {fabric}_env env;
  function new(string name="{fabric}_{name}_test", uvm_component parent=null); super.new(name, parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env = {fabric}_env::type_id::create("env", this);
  endfunction
  task run_phase(uvm_phase phase);
    {fabric}_base_vseq vseq;
    phase.raise_objection(this);
    vseq = {fabric}_base_vseq::type_id::create("vseq");
    vseq.start(env.vseqr);
    phase.drop_objection(this);
  endtask
endclass
"""

    def tb_top(self, t, fabric):
        clk = (t.get("clocks") or [{"name": "clk"}])[0].get("name", "clk")
        rst = (t.get("resets") or [{"name": "rst_n"}])[0].get("name", "rst_n")
        return f"""module tb_top;
  import uvm_pkg::*;
  import {fabric}_env_pkg::*;
  logic {clk};
  logic {rst};
  initial begin {clk}=0; forever #5 {clk}=~{clk}; end
  initial begin {rst}=0; #100; {rst}=1; end
  // Bind DUT master/slave interfaces and {fabric}_addr_decoder from
  // environment_manifest.json/current evidence.
  initial run_test();
endmodule
"""
