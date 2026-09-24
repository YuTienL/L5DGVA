---
name: amba4-soc-environment-builder
description: Build a production-oriented AMBA4 SoC Multi-Master × Multi-Slave UVM verification environment from current DUT/spec/VIP evidence and integrate it into the common Harness lifecycle.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# AMBA4 SoC Multi-Master × Multi-Slave Environment Builder

## Evidence Inputs
Must inspect current DUT RTL/source, applicable specification, PHY documentation, programming/register guides,
VIP manual/examples/source/class reference, and current project configuration.

## Discover Before Generate
- AXI3/AXI4/AXI4-Lite/AXI-Stream/AHB/AHB-Lite/APB3/APB4
- master/slave topology
- address map
- ID namespace
- clock/reset domains

## Generate / Integrate

**Use the real generator — do not hand-write this from scratch.**
`dv_harness/uvm_generator/amba_fabric_generator.py` (`AMBAFabricGenerator`) already
implements every algorithm below in Python (address-decode overlap/gap/full-coverage,
ID-width formula, per-pair scoreboard-matrix resolution) and emits a schema-exact
topology JSON plus real UVM/SV skeleton files. Once master/slave/address-map/
connectivity evidence is discovered (previous section), build the topology JSON per
`dv_harness_tests/test_amba_fabric_generator.py`'s fixtures and run:
```
python tools/generate_amba_fabric_environment.py --topology <topology.json> --out <dir>
```
Read that module's own docstring "WHAT THIS DOES NOT DO" section first — it does not
invent AXI/AHB/APB channel/handshake signal names or VIP bindings; those still come
from current evidence, supplied into the topology JSON, never fabricated.

Since 2026-09-04 that same topology can instead be carried as a
`protocol_model_topology` block inside the environment manifest, and the
governed generation entry point layers the fabric model onto the generic
skeleton in one run (see `dv_harness/uvm_generator/protocol_model_layer.py`):
`dv-harness start --goal "<goal>" --protocols amba4 --dut-role <role>
--generate --generate-out <dir> --generate-manifest <m.json>`
(GAP-V2-002: same governed Field Resolution/Clarification path every other
`PROTOCOL_BUILDERS` skill converges on; `tools/generate_protocol_uvm_
environment.py` itself, which this used to call directly, is now an
INTERNAL_GENERATION_PRIMITIVE beneath it). Use that when the fabric is
part of an environment being generated; the standalone
`generate_amba_fabric_environment.py` command above stays correct for
generating the fabric model on its own, unaffected by this remediation.

- master/slave registries
- Concurrent multi-branch bus arbitration: when block-level traffic and multiple branch_a{N} DUT-side
  branches run concurrently on the same AMBA bus, treat each branch's driver as an independent AMBA
  master in the M×N model — never assume one branch has exclusive/uncontended bus access just because
  it is the only branch currently being authored. `branch_topology_gate.py` requires a
  `cross_branch_bus_model` (shared_resources + arbitration_policy) whenever more than one DUT-side
  branch exists on an AMBA protocol.
- Address decoder model — deterministic non-overlap/coverage check (note: `end` below is EXCLUSIVE,
  i.e. `end = base+size`, matching `fabric_topology_completeness_gate.py`'s actual enforced comparison
  — not the inclusive `base+size-1` an earlier draft of this rule used):
  1) sort {slave_id, base, size} by base; end = base+size
  2) FAIL if any entries[i].end > entries[i+1].base (overlap)
  3) every address-space gap between adjacent ranges must map to an explicit
     RTL/spec "reserved" or "default-slave DECERR" declaration; undeclared
     gap = FAIL
  4) union(mapped ranges, declared-reserved ranges) must equal the full
     [0, 2^ADDR_WIDTH-1] space with zero residual — no silent unmapped region
  5) add a coverage bin per declared-reserved region confirming the DUT's
     actual DECERR/SLVERR response was observed for at least one access into it
- ID-width propagation (deterministic, compute once M/I_m known from RTL):
  W_out_required = ceil(log2(M)) + max_m(I_m)
  Verify against RTL/decoder-side ID port width. FAIL if RTL width < W_out_required
  (aliasing risk). If interconnect uses a different scheme than master-index
  append, capture the actual scheme from RTL and re-derive W_out from it instead
  of assuming this formula — this formula is the standard construction, not a
  substitute for reading the actual merge logic.
- outstanding/ordering/interleave
- exclusive access
- QoS
- backpressure
- dependency/barrier
- parallel virtual sequences
- Scoreboard/coverage matrix — deterministic completeness gate (bookkeeping only;
  exclusion content itself remains DUT-specific and must come from current
  RTL/decoder/permission evidence, not assumed):
  1) Build one (master × slave) cross covergroup with M*N cross bins.
  2) Every bin must end in exactly one state: hit (>0 samples) OR
     ignore_bins/illegal_bins carrying an inline justification comment citing
     the specific RTL/decoder/permission evidence for exclusion.
  3) Completeness = (count(hit bins) + count(justified-excluded bins)) == M*N.
     Any bin left in neither state is a FAIL — treat as a missing scenario,
     not an acceptable gap.
  4) Re-derive the exclusion set from current RTL/decoder/permission evidence
     each time topology changes; do not carry forward a prior exclusion list
     from memory without revalidation (per Evidence Truth Rule).
  5) This matrix's hit/excluded status must also satisfy the
     fabric_topology_completeness_gate JSON schema at the VERIFICATION_ARCHITECTURE
     stage (status IMPLEMENTED/WAIVED/NOT_APPLICABLE, waivers need
     waiver_approved+waiver_evidence) — the covergroup states above are the SV-level
     authoring guide; the JSON schema is what the harness gate actually enforces.
     Keep them in sync.
- cross-master/slave scenarios
- smoke tests

## Mandatory Gates
- protocol_builder_registry_conformance_gate (discover/build checklist coverage)
- Evidence Truth Gate
- Multi-Agent Evidence Consensus
- Independent Synthesis
- Environment Manifest approval when topology is uncertain/high impact
- Compile PASS
- Smoke Simulation PASS
- Exact SHA / evidence provenance

Never reuse protocol-specific USB/PCIe/Ethernet/etc. content as truth for another protocol.
Only common UVM infrastructure/patterns may be reused.
