# AMBA-21 / AMBA-22 gap close — scoreboard reference environment analysis + AMBA_PORT_REGISTRY

**Result: DONE**

Both requirements were audited `NEVER_BUILT` and both are now real, callable, tested code.

## What changed

### New — `dv_harness/amba_scoreboard_env.py` (AMBA-21, ~640 lines)

Read-only inspection of a user-supplied UVM scoreboard / reference environment, and
the map from each proposed VIP monitor to a real scoreboard ingress.

- `analyze_scoreboard_environment(roots)` → `ScoreboardEnvAnalysis`: classes with their
  roles, ingress points, per-component assumptions, and a sha256 per inspected file.
- Class roles (`classify_env_class`) come from the REAL `extends` chain walked
  transitively (`soc_axi_scoreboard → soc_scoreboard_base → uvm_scoreboard`) and are
  tiered with `connectivity.BindTier`: T2 structural, T3 name-only, T4 undecidable. No
  second confidence vocabulary was introduced.
- Ingress discovery lists `uvm_analysis_export` / `uvm_analysis_imp*` /
  `uvm_tlm_analysis_fifo` plus a `uvm_subscriber`'s implicit library export, and
  deliberately excludes `uvm_analysis_port` (it sends; a monitor connected there could
  never carry a transaction).
- Assumptions (`address_map_assumptions`, `ordering`, `ordering_tolerance_depth`,
  `outstanding_transactions`, `protocol_specific_assumptions` — the first four are
  `connectivity.SCOREBOARD_PLAN_FIELDS`' own vocabulary) are `REQUIRED_HUMAN_INPUT` **by
  construction**, each carrying the candidate declarations that bear on it cited by
  `file:line`. A declaration-level scan retains no method body, so inventing a value
  would be the dishonest option; naming where the answer lives is the honest one.
- `assert_sources_unmodified()` makes AMBA-21's "do not modify during discovery"
  **checkable**: every inspected file's sha256 is recorded at scan time and re-verified
  on demand. A modified file and a deleted file are distinct failures.
- `map_vip_monitors_to_scoreboard_ingress()` produces one row per planned VIP, always.
  Narrowing is protocol then endpoint; two survivors is `INGRESS_AMBIGUOUS_MULTIPLE_CANDIDATES`
  naming both candidates with locations, never an arbitrary pick — the same rule AMBA-12/13
  apply to a multiple-source trace. `INGRESS_NOT_FOUND` and
  `NO_SCOREBOARD_ENVIRONMENT_SUPPLIED` are separate, honestly-reported states.

### New — `dv_harness/amba_port_registry.py` (AMBA-22, ~460 lines)

`build_amba_port_registry(netlist, traces, plan, ingress_mapping)` emits AMBA-22's
nineteen mandated fields per row, **joined from artifacts already computed** rather than
re-derived: the AMBA-16 matrix row (fabric_port/protocol/roles/bind hierarchy/clock/reset/
trace_status/readiness/confidence), the AMBA-15 checklist carried on that same row
(address/data/id/user widths and every evidence sentence), the AMBA-20 VIP plan
(`vip_mode`), and AMBA-21's mapping (`scoreboard_channel`). A registry row therefore
cannot disagree with the matrix, checklist or VIP plan a human reviewed.

- `port_id` is derived from the real hierarchical interface id (`U_FABRIC_S00_AXI`), and
  `assert_no_generic_port_ids()` refuses `master0`/`slave1`-shaped ids unless
  `project_convention_allows_generic=True` is passed deliberately — AMBA-22's own naming
  rule as enforced code.
- `endpoint_hierarchy` is filled ONLY from a trace that really established an endpoint.
  A blocked branch's `u_opaque` is kept beside it as `last_known_hierarchy`, never
  promoted into the endpoint column — AMBA-14's "never invent endpoint hierarchy".
- `assert_registry_complete()` requires all nineteen fields non-empty on every row and a
  valid readiness value; unknowns must be visible sentinels, never missing keys.
- `project_to_fabric_topology()` projects DOWN into
  `tools/verification_flow/fabric_topology_completeness_gate.py`'s exact
  `masters`/`slaves`/`scoreboard_matrix`/`address_map` schema, using
  `amba_fabric_generator.build_scoreboard_matrix()` and `compute_address_regions()` —
  those algorithms are reused, not reimplemented. With no address map supplied the
  projection carries an empty one and the gate correctly refuses, rather than fabricating
  a map that would pass. `assert_projection_agrees_with_traces()` cross-checks the
  registry's endpoints against `discovered_topology_ids()` computed independently from the
  traces.

### Extended (additive, +109 lines total across 3 files)

- `dv_harness/vip_symbol_index.py`: a new `_ANALYSIS_PORT_RE` captures parameterized TLM
  analysis declarations (`uvm_analysis_port#(T) ap;`) into a new per-class
  `analysis_ports` key with `kind`/`direction` derived from the UVM base type only —
  the exact hole the audit identified in `_FIELD_RE`. `assert_no_bodies_retained()` now
  covers those fields too; `find_symbol()` resolves them. Split out rather than folded
  into `_FIELD_RE` because an analysis port is a connection point, not a config knob.
- `dv_harness/schemas/vip_symbol_index.schema.json`: new optional `analysis_ports` /
  `analysis_port_entry` (optional, so an index written before this key still validates).
- `dv_harness/amba_fabric_discovery.py`: AMBA-16 matrix rows now also carry
  `endpoint_instance_path` (the bare hierarchy alongside the rendered `endpoint` cell),
  so AMBA-22 reads a path instead of re-parsing display text. Purely additive.

## AMBA-30 / AMBA-31 compliance

No bind statement is written anywhere. `test_no_bind_statement_anywhere` runs
`connectivity.parse_bind_line()` — the repo's single definition of what a bind statement
is — over both new modules' own source, over both rendered reports, and over the
synthetic scoreboard fixture. `render_amba_port_registry_report()` self-checks with
`assert_no_bind_statement()` before returning. The only synthetic fixtures live inside the
new test file.

## Tests

`dv_harness_tests/test_amba_port_registry.py` — 50 tests, all passing. The RTL half
imports `test_amba_vip_bind_plan.write_fixture` (a REAL `verible-verilog-syntax` parse of a
synthetic 2-master / 5-slave-port AMBA4 SoC) rather than copying it, so the registry is
proven against the same seven fabric ports AMBA-15..20 were: two clean, plus a protocol
bridge, a two-way `MULTIPLE_DESTINATION` fan-out, an unparsed black box (`TRACE_BLOCKED`)
and an unconnected port (`DESTINATION_NOT_FOUND`). The scoreboard half is real UVM class
source **with method bodies**, so the no-body-retention check has something to catch.

Ambiguous / unresolved coverage specifically: ambiguous ingress (two equally-plausible
scoreboards), no-matching-protocol ingress, no-environment-at-all, `TRACE_BLOCKED` and
`DESTINATION_NOT_FOUND` ports never inventing an endpoint, a `MULTIPLE_DESTINATION` parent
row held at `REQUIRED_HUMAN_INPUT` with both branches listed, a parameterized width staying
`UNKNOWN`, a cyclic `extends` chain terminating at T4, a source modified mid-discovery, and
a projection with no connectivity evidence refusing to guess.

**Test summary:** every suite that touches what I changed passes — the AMBA suites,
`test_connectivity.py`, and all three `vip_symbol_index` consumers
(`test_asset_processing_artifacts.py`, `test_context_budget.py`,
`test_four_key_judgments_enforcement.py`): **589 passed**; plus
`test_env_manifest*.py`, `test_vip_distill.py`, `test_bind_mechanism_generator.py`,
`test_connectivity_check.py`, `test_protocol_capability.py`: **149 passed**.

Whole repo (`python -m pytest dv_harness_tests -q -p no:randomly -n 8`, 37 min):
**4278 passed, 14 failed**. None of the 14 is in this change's blast radius — none of
those test files imports `amba_scoreboard_env`, `amba_port_registry`,
`amba_fabric_discovery` or `vip_symbol_index` (verified by grep). They fall into two
buckets, both belonging to the other workflows concurrently active in this repo:
memory/git state (`test_debug_flow_memory`, `test_memory_dedup_write_path`,
`test_memory_doctor` — all `'NOTHING_TO_COMMIT' == 'COMMITTED'` against a worktree other
agents are committing to; `test_justfile::test_every_memory_cli_subcommand_has_a_recipe`
against a dirty `cli.py`), and subprocess/parallelism artifacts
(`test_cli_pueue` `TimeoutExpired`, `test_graph_parallel_dispatch` `WinError 5`,
`test_engine_gates_and_routing` `TimeoutExpired`, `test_rca_multi_agent_fanout` timing,
`test_dashboard_interactive`).

## Not done here (scope boundary)

`amba_scoreboard_env` / `amba_port_registry` are REACHED (real importable callers and
tests) but not yet WIRED into `connectivity_check.py`'s standing runner or any CLI verb —
that belongs with AMBA-27..29's reporting wiring, not with AMBA-21/22. The
`branch-mapper/SKILL.md` "UNTESTED" label is AMBA-26's item per the task brief and was
deliberately left alone.
