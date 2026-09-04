# SYOSCB-17/18 — per-protocol compare-strategy policy table + composite match-key schema

**Status: DONE**

Scope: SYOSCB-17 (COMPARE STRATEGY) and SYOSCB-18 (AXI MATCHING MUST NOT BE RAW
OBJECT COMPARE), Phase-1 planning machinery only. Nothing was copied out of
`D:\DV\Scoreboard\uvm_syoscb-1.0.2.4`, no SystemVerilog was written, and no
VCS/UVM build was invoked. The upstream tree was read read-only for evidence.

## What the audit found, and what was actually built

The audit's two verdicts were confirmed by my own re-check and both were acted on:

- **SYOSCB-17 — PARTIALLY_WIRED.** `syoscb_source_audit.py` already owned the
  three-value ordering vocabulary and `compare_class_for_ordering()`
  (`v50/dv_harness/syoscb_source_audit.py:172-175,583-601`), which resolves an
  ordering to a REAL upstream class read off a real audit. What did not exist
  anywhere was the **per-protocol starting-policy table** the document asks
  for. Re-grepped `connectivity.py`, `amba_fabric_discovery.py`,
  `amba_port_registry.py`, `amba_route_transform_predictor.py` and
  `syoscb_topology_plan.py`: no protocol→ordering-default table. Confirmed gap.
- **SYOSCB-18 — NEVER_BUILT.** `connectivity.SCOREBOARD_PLAN_FIELDS`'
  `matching_key` is one flat string with three canned single-field options
  (`v50/dv_harness/connectivity.py:3991-4001`, `:4220-4235`). Nothing decomposed
  it into route + master + AXI ID + read/write domain + ordering domain +
  sequence/burst. Confirmed gap.

One correction to the audit's own text, from the current tree: its SYOSCB-19/20
paragraph calls the transaction-level route/transform predictor NEVER_BUILT.
That is stale — `dv_harness/amba_route_transform_predictor.py` (1104 lines) was
committed earlier in this same sequence (`7670bb6`). My work builds on it rather
than duplicating it. Not in my scope to re-report beyond this note.

## What changed

**New: `v50/dv_harness/syoscb_compare_policy.py`** (~880 lines). A new module
rather than an extension of an existing one, because it is a genuinely new
layer: it IMPORTS and composes the existing primitives and re-derives nothing.
It imports from `syoscb_source_audit` (ordering vocabulary, class resolution,
`assert_no_emittable_sv`), `amba_transaction_ir` (`ir_field_applicability()`,
`protocol_signal_vocabulary()`, `AMBA_TRANSACTION_IR_FIELDS`),
`amba_route_transform_predictor` (`ROUTE_RESPONSIBILITIES`, ordering-domain
constants, prediction statuses), `connectivity` (`AMBA4_PROTOCOLS`,
`ACE_LITE_COHERENCY_SIGNALS`, `SCOREBOARD_PLAN_FIELDS`, `REQUIRED_HUMAN_INPUT`,
`render_markdown_table`), `amba_port_registry` (error base class) and
`syoscb_topology_plan` (`COMPARE_STRATEGY_DEFERRED`).

SYOSCB-17 half:

- `PROTOCOL_COMPARE_POLICY` — one entry per protocol in
  `connectivity.AMBA4_PROTOCOLS`, each carrying the document's own words, the
  line it was transcribed from (`…AMBA4_SyoSil_CCE_Research.md:4961/4964/4967/
  4970/4973/4976/4979/4982`), a starting ordering value from
  `syoscb_source_audit.ORDERING_VALUES`, a rationale, and `required_axes` (the
  match-key axes that make that starting policy SAFE).
- **No upstream class name is typed in the table.** SYOSCB-17's "use actual
  class/config names from source" is honored by resolving the class at call time
  through `compare_class_for_ordering()` against a real read-only audit.
  `assert_policy_table_resolves_to_real_classes()` holds the whole table against
  a real tree so a policy nothing upstream can execute fails now, not at Phase-2
  elaboration.
- `COMPARE_SELECTION_MECHANISM` — the real selection mechanism recorded as data:
  a UVM factory type override on `cl_syoscb_compare_base`
  (`src/cl_syoscb_compare.svh:65`), NOT a cfg field; `primary_queue`
  (`src/cl_syoscb_cfg.svh:30,197-216`) is the one real per-scoreboard knob.
- `resolve_compare_policy()` / `resolve_plan_compare_strategies()` — the latter
  is what `syoscb_topology_plan`'s `compare_strategy: DEFERRED_TO_SYOSCB_17`
  stamp was deferred TO. It reads the master count off the plan's own producer
  list and the ordering expectation off the group's own predictor-supplied
  `route_ordering_expectation`, so a resolution cannot contradict the plan a
  reviewer already read, and it does not mutate the plan.

SYOSCB-18 half:

- `MATCH_KEY_AXES` / `MATCH_KEY_AXIS_SPEC` — the document's own six axes in its
  own order (lines 4998-5003), plus the seventh SYOSCB-17 adds for ACE-Lite
  (coherency attributes, line 4979), labelled with its different source. Every
  axis names the real `AMBA_TRANSACTION_IR_FIELDS` that supply it and the real
  `ROUTE_RESPONSIBILITIES` that must normalize it first ("Normalize expected
  behavior before comparison", line 5005). Both are checked at import.
- `build_match_key_schema()` — per-axis availability derived entirely from
  `ir_field_applicability()`, never re-decided here; the ordering-domain axis is
  read off a real SYOSCB-12 prediction.
- `assert_not_raw_object_compare()` — SYOSCB-18's rule as an enforceable check:
  a proposed key that keeps none of the discriminating axes the protocol
  supplies is refused, citing the real code that makes it a raw compare
  (`cl_syoscb_compare_io.svh:117`, `_iop.svh:120`, `_ooo.svh:118`,
  `cl_syoscb_item.svh:44`).
- `assert_policy_required_axes_present()` — a starting policy whose own
  preconditions the schema cannot supply is refused (AXI4-Lite's IN_ORDER
  default needs `read_write_domain`; AXI's OUT_OF_ORDER needs
  `transaction_id`/`ordering_domain`; ACE-Lite needs a coherency axis the IR has
  no field for).
- `propose_scoreboard_plan_fields()` — extends `connectivity.
  SCOREBOARD_PLAN_FIELDS`' existing `matching_key` and `ordering` columns as
  PROPOSALS (`confirmed: False`), following
  `amba_route_transform_predictor.propose_scoreboard_plan_fields()`'s precedent
  exactly. `transformation_rules` is deliberately left to the predictor that
  already proposes into it — one proposer per column. **`connectivity.py` was
  not modified**: the field is the slot, the composite is the proposal, and
  editing that hot shared file was neither necessary nor safe with other agents
  active.

**New: `v50/dv_harness_tests/test_syoscb_compare_policy.py`** (63 tests).

## Missing-evidence cases tested honestly (not a happy path)

- Full AHB with an unknown master count → `REQUIRED_HUMAN_INPUT`, with both
  reasons stated (IN_ORDER false-FAILs a real multi-master AHB via
  `cl_syoscb_compare_io.svh:121`; IN_ORDER_PER_PRODUCER needs slave-side
  producer attribution that may itself be blocked).
- An unresolved protocol → `PROTOCOL_UNRESOLVED`, kept distinct from
  `REQUIRED_HUMAN_INPUT` (discovery gap, not a policy question), and only the
  protocol-DEPENDENT axes go undecided — route/master identity survives.
- ACE-Lite coherency → `NO_IR_FIELD_CARRIES_THIS_AXIS` with the real witness
  signals named: a declared IR gap for SYOSCB-9/10, not a dropped axis. Made
  consequential — ACE-Lite's own starting policy cannot be adopted because of it.
- The ordering-domain axis with no prediction → `REQUIRED_HUMAN_INPUT` naming
  its owner; normalization with no prediction → "unchecked", never "no transform".
- A scoreboard group whose masters do not share one protocol →
  `MIXED_PROTOCOL_GROUP`, both protocols named, no arbitration invented.
- A synthetic upstream tree implementing only io/iop → the table check raises
  rather than substituting a neighbouring algorithm.

Real-evidence tests: every `doc_line` is held against the real master-prompt
line; every cited upstream `file:line` is read from the real tree read-only; the
"no compare-selector field in `cl_syoscb_cfg`" claim is checked from the other
direction; the real parsed AMBA4 SoC fixture runs end to end (real RTL → trace →
AMBA_PORT_REGISTRY → predictions → plan → compare strategy + match key), and the
rendered report passes `assert_no_emittable_sv()` and `assert_no_bind_statement()`.

## Test summary

`63 passed` for the new test file; `629 passed in 63.12s` for the full relevant
suite (`test_syoscb_compare_policy`, `test_syoscb_topology_plan`,
`test_syoscb_source_audit`, `test_amba_route_transform_predictor`,
`test_amba_transaction_ir`, `test_amba_port_registry`,
`test_amba_fabric_discovery`, `test_amba_fabric_generator`, `test_connectivity`,
`test_address_map_verifier`).

## Constraints honored

No file under `D:\DV\Scoreboard` was copied, written or modified; it was read
read-only for citation evidence. No SystemVerilog was emitted. No VCS/UVM build
was run. No shared file (`connectivity.py`, `amba_port_registry.py`,
`amba_fabric_discovery.py`, `amba_scoreboard_env.py`, `CLAUDE.md`) was touched —
`git status` on all of them is clean. Only the two new files were committed, via
a pathspec commit, because another concurrent agent had unrelated work staged in
the index.

No scoreboard super-agent was added (SYOSCB-32): this is a module plus tests.
Phase-2 remains ungated — nothing here starts SYOSCB-34 work.
