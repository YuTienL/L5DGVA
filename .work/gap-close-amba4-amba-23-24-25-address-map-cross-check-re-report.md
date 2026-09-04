# AMBA-23 / AMBA-24 / AMBA-25 gap close — DONE

Scope: `D:/DV/Task/DV_Agent_Harness_L5/v50`. Discovery/planning/reporting only,
per the master prompt's own AMBA-30 (mandatory review gate) / AMBA-31 (implement
only after explicit approval) rules. No `bind` statement was written anywhere.

## Verdict movement

| Requirement | Audit verdict | Now |
|---|---|---|
| AMBA-23 ADDRESS MAP CROSS-CHECK | PARTIALLY_WIRED | WIRED_AND_FIRING |
| AMBA-24 CLOCK / RESET DOMAIN ANALYSIS | NEVER_BUILT | WIRED_AND_FIRING |
| AMBA-25 SCOREBOARD + PORT SCALING | PARTIALLY_WIRED | WIRED_AND_FIRING |

Commit: `413d33b amba(analysis): AMBA-23 address-map cross-check, AMBA-24
clock/reset domains, AMBA-25 port scaling` (2 files, +2674).

## What changed

One new module, `dv_harness/amba_fabric_analysis.py` (1788 lines), plus
`dv_harness_tests/test_amba_fabric_analysis.py` (886 lines, 48 tests). No
existing file was modified — every reuse point is an import.

A new module rather than more of `amba_fabric_discovery.py` because all three
requirements ask a structurally different question of the already-built
artifacts: AMBA-23 reconciles independent address-map EVIDENCE SOURCES,
AMBA-24 walks CLOCK and RESET nets (a different traversal over the same
`FabricNetlist` — driver-ward, not bundle-ward), AMBA-25 is registry
arithmetic. `amba_fabric_discovery.py` was already 2838 lines and owns the
AMBA-bundle traversal only.

### Reuse, not restatement

Every algorithm the audit named as reusable is imported and called, never
recomputed:

- `uvm_generator/amba_fabric_generator.compute_address_regions()` — the only
  overlap/gap/full-coverage validator (AMBA-23 completeness).
- `uvm_generator/amba_fabric_generator.build_scoreboard_matrix()` — the only
  M×N pair resolver; its `UNRESOLVED_PAIR` is surfaced as a hard refusal, not
  softened (AMBA-25).
- `uvm_generator/amba_fabric_generator.compute_id_width()` — the only ID-width
  formula (AMBA-25).
- `source_authority.resolve_conflict()` — the only conflict order (AMBA-23),
  the same one `address_map_verifier.py` routes its decoder-vs-doc
  disagreements through.
- `connectivity.find_amba_clock_reset_ports()` / `SignalTrace` /
  `classify_bind_tier()` / `render_markdown_table()` / `amba_signal_tokens()`
  — the only clock/reset port identifier, trace contract, tier classifier,
  table renderer and AMBA vocabulary (AMBA-24).
- `amba_port_registry.registry_endpoints()` — the only endpoint projection
  (AMBA-25).
- `amba_fabric_discovery.adapter_sub_role_hint()` / `assert_no_bind_statement()`
  / `find_bundle()` / `parse_instance_path()`.

`address_map_verifier.py` is deliberately NOT called: it answers an IP-level
question with a different mandatory second source (a BFM-access histogram).
Its POLICY — highest authority decides, a document never decides, a
disagreement is recorded rather than blocking — is what is reused, through the
`source_authority` order both defer to. That is stated in the module docstring.

### AMBA-23 — the asymmetry is implemented, not described

`AddressRegionClaim` carries the doc's six evidence sources
(`RTL_DECODER` / `FABRIC_GENERATED_CONFIGURATION` / `ADDRESS_MAP_PACKAGE` /
`CSR_DEFINITIONS` / `FIRMWARE_HEADERS` / `MEMORY_MAP_DOCUMENT`), each mapped
onto a real `AUTHORITY_ORDER` level, and refuses construction without a cited
`evidence` path — the same discipline `source_authority.SourceClaim` enforces.

`cross_check_fabric_address_map(claims, traced_slaves, address_width=...)`
implements "use only as supporting evidence; physical RTL connectivity remains
mandatory" as an asymmetry:

- an owner named by evidence but never traced → `NO_PHYSICAL_CONNECTIVITY`,
  reported and REFUSED as a bind-planning input;
- a traced slave with no address evidence → `NO_ADDRESS_EVIDENCE`, reported and
  STILL usable, because the mandatory half is satisfied.

Two sources at the same authority level that disagree are
`UNDECIDABLE_SAME_AUTHORITY`, never broken by an invented sub-order — including
the case where one level holds two of this module's source TYPES (an RTL
decoder and a fabric configuration are both `dut_rtl`). Overlap/gap/coverage
failures are RECORDED on the result, not raised: this artifact is a report a
human reads at AMBA-30's gate.

`address_map_slaves_for_topology()` is the concrete wiring the registry's own
docstring left to its caller — it produces exactly the `address_map_slaves`
argument `amba_port_registry.project_to_fabric_topology()` asks for, filtered to
physically-confirmed owners, and
`assert_address_map_never_creates_a_slave()` guards the one way this can be
violated in practice.

### AMBA-24 — all seven determinations, none assumed

`_walk_domain()` follows a clock or reset net driver-ward over the same
`FabricNetlist`: a top-level input or an instance OUTPUT is a driver, a
transparent wrapper contributes only same-class `input` attachments (so it is
not a hierarchy step), and a continuous assign is a traversable edge.

The load-bearing design decision is domain IDENTITY:

```
@property
def domain_node(self):   # the NEAREST domain-starting element, not the origin
```

A divider's output and its own input share an origin (`<top>:CLK_REF`) but are
not the same clock domain; comparing origins would report every CDC in a
single-oscillator SoC as absent. Proven by
`test_a_divider_output_is_a_different_domain_from_its_own_input`.

Per bind point: clock hierarchy, clock frequency (measured from a real
`SignalTrace`, or a declared parameter tiered T3, or UNKNOWN), reset hierarchy,
reset polarity, sync/async reset, CDC/bridge path, and the endpoint-side /
fabric-side statement.

Reset polarity is the direct fix for the audit's finding that
`evaluate_zero_time_connectivity()` took `reset_active_low` as a caller
opinion. It is now DERIVED: the AMBA specification's own n-suffixed naming
(spec tier), a measured assert-then-release trace, or UNKNOWN with the missing
evidence named. Name and trace disagreeing is `NAME_AND_TRACE_DISAGREE` with
both sides kept, and `derived_reset_active_low()` — the function that supplies
Gate 2's argument — RAISES rather than defaulting on unknown or disputed. An
unsuffixed `ARESET` is explicitly not evidence of active-high.

Unresolved states are first-class: `AMBIGUOUS_CLOCK_OR_RESET_PORT` (a clock mux
with two candidate inputs), `NET_HAS_MULTIPLE_DRIVERS`,
`NET_HAS_NO_IDENTIFIABLE_DRIVER`, `DRIVEN_BY_MULTI_NET_EXPRESSION`,
`HOP_LIMIT_REACHED`, and `CDC_SUSPECTED_NO_CROSSING_ELEMENT_IDENTIFIED` (the
domains genuinely differ but no hop identifies itself as the crossing). Two
`DOMAIN_UNKNOWN` values are never equal.

Sync/async is answered only where structurally provable (a reset synchroniser
really in the chain, tiered T3 through `classify_bind_tier()`); otherwise
UNKNOWN naming the missing evidence, because always-block sensitivity lists are
not in a port/instance/assign-level parse. Stated, not implied away.

### AMBA-25 — the two halves the audit named as missing

`build_fabric_scaling_plan(rows, ...)` adds, on top of the reusable M×N core:

- **protocol bridges as a distinct two-sided node type** — `_bridge_nodes()`
  reads the AMBA-11 second-side row and its PARENT for the upstream protocol,
  so a downstream APB side is never labelled AXI, and a bridge is never counted
  as an endpoint;
- **per-protocol traffic policy** — AXI_MM / AXI_STREAM / AHB parallel, APB
  serialized, by protocol FAMILY so a new sub-protocol inherits correctly; an
  unresolved protocol gets `REQUIRED_HUMAN_INPUT`, never a default;
- **the scheduling-interlock rule** — `_interlocks()` lists EVERY master pair
  with an explicit verdict and claims an interlock only for a concrete
  dependency (a shared slave, or a shared serialized segment). Every other pair
  is `NO_INTERLOCK` with the reason written down, so adding cross-port ordering
  elsewhere contradicts a finding rather than filling a silence;
- protocol-annotated pairs (`master_protocol` / `slave_protocol` /
  `protocol_crossing`), `assert_every_port_has_its_own_channel()`, and
  `compute_id_width()` reporting `REQUIRED_HUMAN_INPUT` when any master's
  AMBA-15 `id_width` check answered UNKNOWN.

Size-agnosticism is tested, not asserted: `test_the_plan_scales_to_any_fabric_size`
is parameterized over 1×1, 2×2, 3×4 and 5×3.

## Tests

`dv_harness_tests/test_amba_fabric_analysis.py` — 48 tests, no skips. AMBA-24
runs against a REAL `verible-verilog-syntax` parse of a synthetic AMBA4 SoC
(two AXI4 masters, an AXI4 slave behind a CDC wrapper, an APB4 peripheral
behind an AXI-to-APB bridge, a PLL, a divider, a reset synchroniser). Both the
clean and the genuinely ambiguous cases are exercised: a double-driven clock
net, a two-input clock mux, an undriven reset, an untraced address-map owner,
two equal-authority sources that disagree, an unresolvable scoreboard pair, a
name-vs-trace polarity disagreement, a non-constant clock period.

Real output from the fixture (not a fabricated expectation):

```
u_ddr:S_AXI_          clk u_div:CLK_OUT <- u_pll:PLL_CLK <- <top>:CLK_REF
                      cdc CDC_CROSSING_IDENTIFIED   side ENDPOINT_SIDE_OF_CDC
u_apb_bridge:M_APB_   cdc NO_CDC_ON_PATH            bridge BIND_IS_DOWNSTREAM_OF_BRIDGE
u_cpu:M_AXI_          rst u_rst_sync:ARESETN_OUT <- <top>:RSTN_EXT  sync SYNCHRONIZED_RELEASE
```

**One-line test summary**: 48 new tests pass; 202 pass across the five AMBA
suites (`test_amba_fabric_analysis` + `test_amba_fabric_discovery` +
`test_amba_port_registry` + `test_amba_fabric_generator` +
`test_amba_vip_bind_plan`); 308 pass across
`test_connectivity` / `test_connectivity_check` / `test_address_map_verifier` /
`test_source_authority`.

## AMBA-30 / AMBA-31 compliance

`test_no_bind_statement_is_ever_emitted` runs
`amba_fabric_discovery.assert_no_bind_statement()` over the new module's own
source AND over all three rendered reports;
`test_the_fixture_itself_contains_no_bind_statement` runs it over the synthetic
RTL. Nothing downstream of `AMBA_PORT_REGISTRY` is auto-applied — the module
produces review artifacts and refuses to guess.

## Notes for the next step

- `dv_harness/amba_fabric_analysis.py` is not yet reachable from a CLI verb or
  from `connectivity_check.py`'s standing runner. That is deliberate for this
  step (the audit's scope was the analysis itself), and is the natural next
  wiring point alongside the rest of the AMBA-1..29 pipeline.
- `industrial/` and `PACKAGE/` still carry no `dv_harness/amba_*.py` at all —
  none of the prior AMBA steps in this sequence synced them either, so this
  step follows the same convention rather than diverging mid-sequence. The
  CLAUDE.md sync rule covers `.claude/` skills/workflows, which this step did
  not touch.
- Per the task's own scope note, `.claude/skills/CORE/branch-mapper/SKILL.md`'s
  "AMBA-as-Primary-DUT" UNTESTED label is AMBA-26's business, not this step's,
  and was left alone.

## Files

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\amba_fabric_analysis.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_amba_fabric_analysis.py` (new)
