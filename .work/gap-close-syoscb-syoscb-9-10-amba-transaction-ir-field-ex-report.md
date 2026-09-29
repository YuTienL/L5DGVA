# SYOSCB-9 / SYOSCB-10 gap close — AMBA Transaction IR + adapter-layer plan

**Result: DONE**

**Test summary:** 51 new tests in `dv_harness_tests/test_amba_transaction_ir.py` pass;
584 passed across the full AMBA + SyoSil + connectivity suites
(`test_amba_transaction_ir` + `test_amba_port_registry` + `test_amba_fabric_discovery` +
`test_amba_vip_bind_plan` + `test_amba_fabric_generator` + `test_amba_fabric_analysis` +
`test_amba_discovery_report` + `test_syoscb_source_audit` + `test_connectivity`).

Commit: `891533a syoscb(SYOSCB-9/10): AMBA Transaction IR joined onto AMBA_PORT_REGISTRY
+ adapter plan` (two new files, 1356 insertions, no shared file touched).

---

## What the audit asked for, and what was built

The audit's verdict was NEVER_BUILT for both items, with one concrete
recommendation: roughly five to seven of SYOSCB-10's twenty-two proposed fields
already have a real identifier/value space in `amba_port_registry.py`'s
nineteen-column row and must be designed as JOINS against it rather than as a
second parallel vocabulary; the remaining fifteen (every per-transaction runtime
value) are genuinely new. That is exactly the split the new module encodes.

`dv_harness/amba_transaction_ir.py` (763 lines, new) — a clearly-scoped module
that IMPORTS and composes the existing primitives rather than copying their
logic:

| Reused primitive | Used for |
|---|---|
| `amba_port_registry.AMBA_PORT_REGISTRY_FIELDS` | `IR_REGISTRY_JOIN_COLUMN`'s target columns, asserted at import |
| `amba_port_registry.ENDPOINT_HIERARCHY_NOT_ESTABLISHED` | the refusal to substitute a last-known path for an endpoint |
| `amba_port_registry.PortRegistryError` | base class of `AmbaTransactionIrError` |
| `connectivity` AMBA signal sets (`AHB_OPTIONAL_EVIDENCE_SIGNALS`, `AXI4_LITE_EVIDENCE_SIGNALS`, `AXI4_STREAM_OPTIONAL_EVIDENCE_SIGNALS`, `AXI_USER_SIDEBAND_SIGNALS`, `PROTOCOL_FINGERPRINTS`, `AMBA_PROTOCOL_FAMILY`, `ALL_AMBA_SIGNAL_NAMES`) | per-protocol field applicability, derived not typed |
| `connectivity.REQUIRED_HUMAN_INPUT`, `render_markdown_table`, endpoint/fabric role constants | sentinel, rendering, observation-point precedence |
| `amba_fabric_discovery.BIND_CHECK_UNKNOWN_VALUE`, `MULTIPLE_BRANCH_PARENT_BIND`, `assert_no_bind_statement` | unknown-clock detection, parent-row handling, artifact gate |
| `syoscb_source_audit.assert_no_emittable_sv` | artifact gate (reused, not re-implemented) |

### SYOSCB-10 — the IR

* `AMBA_TRANSACTION_IR_FIELDS` carries the doc's own 22 fields in the doc's own order.
* `IR_FIELD_ORIGIN` splits them three ways and every entry is checkable:
  `JOINED_FROM_AMBA_PORT_REGISTRY` (7 fields — `protocol`, `master_port_id`,
  `slave_port_id`, `source_hierarchy`, `destination_hierarchy`, `clock_domain`,
  `source_evidence`), `POPULATED_BY_PROTOCOL_ADAPTER_AT_RUNTIME` (11), and
  `DERIVED_BY_ROUTE_TRANSFORM_PREDICTOR` (4 — `original_id`, `fabric_id`,
  `route_id`, `expected_actual`, i.e. SYOSCB-12 territory named by owner rather
  than left as a blank column). `_assert_join_columns_exist()` runs at import, so
  renaming a registry column breaks loudly here instead of silently reading empty.
* **"Do not force protocol-inapplicable fields" is derived, not asserted.** A
  conditional field applies to a protocol when that protocol's real signal
  vocabulary (its `PROTOCOL_FINGERPRINTS` required set plus its family's optional
  evidence set) contains a signal that witnesses it. `_assert_witness_tokens_known()`
  refuses at import if this module ever names a signal `connectivity.ALL_AMBA_SIGNAL_NAMES`
  does not already know — there is still exactly one AMBA signal table in this repo.
  Consequences, all test-pinned: APB loses `byte_enable`/`burst_*`/`transaction_id`/`response`;
  APB3 regains `response` (PSLVERR); APB4 regains `byte_enable` (PSTRB); AXI4-Lite
  loses `burst_*` and every ID field; AXI4-Stream loses `address` and `response`
  but keeps `transaction_id` (TID) and `byte_enable` (TSTRB/TKEEP); AHB loses
  `byte_enable` and IDs but keeps `burst_*` via HBURST/HSIZE.
* **An unresolved protocol is not defaulted.** It yields
  `UNKNOWN_PROTOCOL_UNRESOLVED` on every conditional field and sends its value to
  `REQUIRED_HUMAN_INPUT` — deliberately distinct from `NOT_APPLICABLE_FOR_PROTOCOL`,
  because "this bus has no burst length" and "nobody established what this bus is"
  are different facts and only the second is a closable discovery gap.
* **Near/far split.** A monitor at one port knows its own side of a transaction;
  the opposite port id and opposite endpoint hierarchy are routing decisions that
  belong to the SYOSCB-12 predictor and say so by name.

### SYOSCB-9 — the adapter plan (no SV)

* `plan_amba_adapters()` proposes one logical adapter per protocol the
  AMBA_PORT_REGISTRY really carries, and `assert_no_adapter_for_absent_protocol()`
  enforces SYOSCB-8's "do not instantiate support for nonexistent protocols".
* Each entry separates what the adapter must POPULATE (runtime fields) from what
  it must READ from the registry (joined fields) from what the predictor owns
  from what it must NOT force (inapplicable fields).
* SYOSCB-9's "Search existing L5/VIP adapters first. Default = ENHANCE / REUSE
  before ADD" is kept honest by making the search a real input and keeping two
  states apart: `existing_adapters=None` (nobody looked) → `REQUIRED_HUMAN_INPUT`;
  `[]` (looked, found nothing) → `ADD`; a partial match → `ENHANCE`, never `ADD`.
* `SYOSIL_INGEST_BOUNDARY` cites the real upstream API read-only —
  `cl_syoscb::add_item(queue_name, producer, uvm_sequence_item)` at
  `uvm_syoscb-1.0.2.4 src/cl_syoscb.svh:58`, wrapped by `cl_syoscb_item`
  (`src/cl_syoscb_item.svh:22`) and delivered via `cl_syoscb_subscriber::write()`
  (`src/cl_syoscb_subscriber.svh:42`) — so the plan states what shape a Phase-2
  adapter's product must have without emitting any of it.

---

## Evidence that the missing-evidence paths are real

Per this project's own hard-won lesson, the honest-failure cases are tested, not
only the happy path:

* `test_an_unknown_clock_becomes_required_human_input_not_a_guessed_domain`
* `test_an_unestablished_endpoint_hierarchy_is_not_replaced_by_a_last_known_path`
* `test_an_unresolved_protocol_leaves_every_conditional_field_to_a_human`
* `test_an_unresolved_observation_point_leaves_both_ends_open`
* `test_no_search_performed_is_not_reported_as_nothing_to_reuse`
* `test_forcing_an_inapplicable_field_is_refused`
* `test_an_adapter_planned_for_a_protocol_no_port_speaks_is_refused`
* `test_a_runtime_field_is_not_counted_as_missing_evidence` (the inverse: a field
  with a known owner who has not run yet must NOT be reported as missing evidence)

The real-fixture half runs the REAL verible-parsed multi-master/multi-slave AMBA4
SoC through the REAL `build_amba_port_registry()`; five of its seven fabric ports
are deliberately unresolvable (protocol bridge, two-way fan-out, unparsed black
box, unconnected port), and the IR reports their hierarchy as
`REQUIRED_HUMAN_INPUT` rather than inventing one. That fixture also surfaced a
real fact the first draft of the test got wrong: the registry carries an AMBA-11
second-side APB4 row alongside its AXI4 fabric ports, so the plan correctly emits
two adapters (AXI4 + APB4) and none of the other eight protocols.

---

## Hard constraints — all honored

* **Nothing copied from `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`.** The tree was read
  read-only for the three API citations above. `test_the_module_never_reads_or_copies_the_upstream_syoscb_tree`
  asserts the module contains no `D:/DV/Scoreboard` path and no file-opening call
  at all.
* **No SystemVerilog emitted.** `test_no_emittable_sv_anywhere` runs
  `syoscb_source_audit.assert_no_emittable_sv()` and
  `amba_fabric_discovery.assert_no_bind_statement()` over the module's own source
  and over every artifact it renders.
* **No VCS/UVM build invoked.** The only external tool used is
  `verible-verilog-syntax`, already this repo's parser, on the existing synthetic
  RTL fixture.
* **No new agent.** SYOSCB-32 honored by adding none; `.claude/agents/` untouched.
* **Concurrency.** Another agent had five files staged in the shared index
  throughout. The commit was built in a temporary `GIT_INDEX_FILE` seeded from
  `HEAD` containing only the two new paths, so their staged work was neither
  committed nor disturbed (verified after: still staged, my files clean).

---

## Scope boundaries left open (deliberately, and named)

* **SYOSCB-11 (AXI logical transaction reconstruction)** is untouched. The IR names
  the fields a reconstructed transaction would carry; nothing here reconstructs
  AW/W/B/AR/R from channel handshakes, tracks outstanding transactions, or models
  WLAST/RLAST/backpressure. That remains NEVER_BUILT and is its own step.
* **SYOSCB-12 route/transform predictor** is referenced by name as the owner of
  four IR fields and of every far-side value; it does not exist yet.
* **The real adapter class** (a `uvm_sequence_item` producer feeding
  `cl_syoscb::add_item()`) is Phase-2/SYOSCB-34 work behind the SYOSCB-33 human
  approval gate, and every plan entry carries
  `implementation_status: PHASE_2_ONLY_NO_SV_EMITTED_HERE`.
