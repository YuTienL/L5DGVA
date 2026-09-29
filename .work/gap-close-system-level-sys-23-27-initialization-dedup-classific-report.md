# SYS-23..SYS-27 gap-close report — DONE

**Commit**: `bd088d7` `system-level(SYS-23..27): initialization-scope classification, shared-resource scheduling, parallelism model, scoreboard-reuse plan, cross-subsystem check plan`

**Test summary**: `dv_harness_tests/test_system_scheduling_plan.py` 65 passed; full relevant suite 359 passed (test_system_scheduling_plan, test_system_command_plan, test_system_resource_registry, test_system_resource_inventory, test_subsystem_architecture_and_command_contract, test_subsystem_discovery, test_source_authority), plus `test_system_level_soc_composition_wiring.py` 10 passed.

---

## 1. The audit's verdicts, re-verified before building

Every one of the audit's five verdicts was re-checked with my own grep/read, not
taken on trust. All five stand.

| Req | Audit verdict | Re-verified? | What I found |
|---|---|---|---|
| SYS-23 | NEVER_BUILT | yes | `grep -rn "SYSTEM_ONCE\|SUBSYSTEM_ONCE\|SCENARIO_ONCE\|SHARED_RESOURCE_COMMAND" --include=*.py .` → **zero hits** |
| SYS-24 | PARTIALLY_WIRED | yes | `tools/verification_flow/system_level_resource_contention_gate.py` is real (9 lines), registered at `dv_harness/gates.py:346`; it is a completeness check on an agent-supplied plan, no routing |
| SYS-25 | NEVER_BUILT (for the 6-value enum) | yes | `SERIALIZE_RESOURCE` / `ORDER_DEPENDENT` / `INTERRUPT_DEPENDENT` / `CLOCK_DOMAIN_DEPENDENT` → **zero hits**. The only prior `PARALLEL_SAFE` is `subsystem_command_contract.py:90`, a different (3-valued, per-command) thing |
| SYS-26 | PARTIALLY_WIRED | yes | `soc_environment_composer.end_to_end_scoreboard()` (lines 345–364) still unconditionally raises `NotImplementedError`; reuse holds only by omission |
| SYS-27 | PARTIALLY_WIRED | yes | `cross_subsystem_scenarios()` (lines 319–343) same; `grep -rn "scoreboard_integration\|cross_subsystem_check\|correlation_layer"` → **zero hits** |

One correction to the audit's framing, in its favour: it did not mention that the
prior step in this same sequence (`099ca15`) had already landed
`system_command_plan.py` with a real SYS-21 IR carrying `parallel_group` /
`serialization_group` / `shared_resource`, and `system_resource_registry.py`
(`d87c3b8`) with real `shared` / `consumer_subsystems` / `reuse_decision`. Those
are the two inputs this layer needed, so nothing here re-derives command facts
or resource sharing.

## 2. What changed

Five files, `+3482 / -0`.

| File | Change |
|---|---|
| `v50/dv_harness/system_scheduling_plan.py` | **new**, 1867 lines — the SYS-23..27 layer |
| `v50/dv_harness/schemas/system_scheduling_plan.schema.json` | **new**, 425 lines — the document schema, with four pinned `const`s that make a boundary violation unvalidatable |
| `v50/dv_harness_tests/test_system_scheduling_plan.py` | **new**, 1126 lines, 65 tests |
| `v50/dv_harness/system_command_plan.py` | +9 lines — one field (`clock_domain`) added to the IR's `derivation` block |
| `v50/dv_harness/cli.py` | +55 lines — the `system-scheduling-plan` verb (parser + dispatch) |

### Why a new module rather than an extension

SYS-23..27 all operate on the **join** of the SYS-21 IR (one row per SYSTEM
command) and the SYS-15 registry (one row per SYSTEM resource), and that join has
no natural home:

- `scp.build_system_command_ir()` takes a contract set and a routing plan, and no
  registry at all.
- `srr.build_system_resource_registry()` takes a resource analysis, and no command
  input at all.
- A SYS-24 scheduling row is one *(shared resource × the commands routed through
  it)* — a granularity neither can express.

This is the same reasoning `system_resource_registry.py` and
`system_command_plan.py` each recorded for themselves. A test
(`test_no_second_classifier_or_registry_is_defined_here`) asserts the module
defines no second command IR, collision detector, registry builder, relationship
classifier, concurrency resolver, contract builder or reuse decider.

### What is imported and composed, never re-derived

- `scp.build_system_command_ir()` — every command fact, including the
  cross-subsystem `parallel_safe` verdict `scc.resolve_cross_subsystem_concurrency()`
  already decided.
- `scp.detect_command_collisions()` — the duplicate findings SYS-23 classifies,
  **including their `evidence_by_subsystem` per-side citations**, which is exactly
  what SYS-23's "do not remove without evidence" rule needs. SYS-23 does not
  re-join command names across subsystems.
- `srr.build_system_resource_registry()` — which resources are shared, who
  consumes them, what was decided.
- `sri` — the resource TYPE vocabulary (`RT_MEMORY_MODEL`, `RT_DMA_MODEL`, …) and
  the inventory's own `dependencies.command_resource_ids` link.
- `tools/verification_flow/system_level_resource_contention_gate.py` — the real,
  already-wired gate, fed rather than duplicated.
- `soc_environment_composer` — probed at its boundary, not extended.

## 3. Per-requirement, what is now real

### SYS-23 — initialization deduplication

`classify_initialization_scope()` assigns one of the requirement's own five
values per IR entry, with a precedence documented and tested:

1. `SYSTEM_ONCE` — SYS-22 already found this command duplicated as a setup across
   ≥2 subsystems and its SYS-7 category is initializing.
2. `SHARED_RESOURCE_COMMAND` — any remaining command with contended
   cross-subsystem sharing; its execution count is a SYS-24 scheduling decision,
   not a dedup one.
3. `REPEATABLE` — evidence of >1 invocation in its own file (derived from the
   contract's own `address_dependency` / argument profile, cited), or an
   observing category.
4. `SUBSYSTEM_ONCE` — initializing, unshared, unduplicated.
5. `SCENARIO_ONCE` — everything else with a category.
6. `REPEATABLE` again as the residual, because it is the only one of the five
   whose consequence is to change nothing, which is what "no evidence" requires.

**There is no `REMOVE` action anywhere.** `SYS23_DEDUP_ACTIONS` is
`(KEEP, DEDUPLICATION_CANDIDATE_PENDING_HUMAN_DECISION)`, the schema pins that
enum, and a candidate additionally requires a real citation from ≥2 different
subsystems.

### SYS-24 — shared resource scheduling

`plan_shared_resource_scheduling()` emits one row per shared physical agent,
naming a single `PROPOSED_SHARED_ACCESS_POINT::…` whose `access_point_status` is
schema-pinned to `PLANNED_NOT_IMPLEMENTED`.

**Two real evidence axes, reconciled.** The environment axis (a registry entry
marked `SHARED_ACROSS_SUBSYSTEMS`, built from connectivity matrices) and the
command axis (a contract's `shared_resource_dependency`, built from command.txt).
The `BFM:DUT_SIDE` two subsystems both drive is invisible to a connectivity
matrix (no subsystem column); a registry entry with no command link cannot say
which commands would route. Where the SYS-9 inventory link joins them, they
become **one** row citing both axes.

`_scheduling_constraints()` records the real field each constraint came from
(registry `exclusive`/`active_passive`/`protocol`/`clock`/`reset`, contract
`contention`). No derivable constraint → `UNKNOWN_PENDING_EVIDENCE`, never a
default policy. A `BLOCKED` registry decision →
`NOT_SCHEDULABLE_PENDING_OWNERSHIP_RESOLUTION`.

`check_no_global_serialization()` implements SYS-24's second sentence as a check
with **demonstrated detection power** — a control test feeds it a fabricated
violation and asserts it fires.

`resource_contention_gate_input()` derives the `shared_resources` half of the
already-wired gate's evidence block from real registry/contract evidence; a test
runs that gate as a real subprocess. `scenarios` stays empty and says why
(inventing `contention_testcase_ids` would fabricate verification evidence).

### SYS-25 — parallelism model

`classify_parallelism_relationships()` classifies every **cross-subsystem**
command pair into the requirement's own six values, precedence most-restrictive
first, with every losing signal kept in `also_matched`.

One correction made during the build, worth recording: the first cut used SYS-8's
`ordering_constraints` as an ORDER_DEPENDENT signal. Those edges are *within one
file*, so matching an edge's `other_command` against another subsystem's
identically named command would claim a cross-subsystem order neither file
states, from a shared macro name alone — precisely the name-only inference
SYS-10 rules out. That signal was removed; only a `PRECEDING_INITIALIZATION`
precondition qualifies, which is the same disturber rule
`scp._ordering_collisions()` already applies for SYS-22. A test
(`test_a_same_named_within_file_ordering_edge_never_creates_a_cross_subsystem_order`)
holds it.

### SYS-26 — scoreboard integration

Per-subsystem `REUSE_EXISTING_SUBSYSTEM_SCOREBOARD` rows, plus a named
`PROPOSED_SYSTEM_SCOREBOARD_CORRELATION_LAYER` pinned to
`PLANNED_NOT_IMPLEMENTED`.

The audit's own observation — that in `soc_environment_composer` "no monolithic
replacement" is true *by omission* rather than by a guard — is closed here as a
distinction that matters: `subsystem_scoreboard_modified` and
`replaced_by_monolithic_scoreboard` are fields both `assert_no_emitted_artifacts()`
and the schema refuse when true, so the guarantee is now **checkable** rather than
merely structurally unreachable.

The missing prerequisite CLAUDE.md names (the cross-subsystem topology
descriptor) is itemised `address_map` / `interrupt_map` / `dma_map` against real
registry evidence, so a selection carrying real address regions but no interrupt
map reports that difference instead of one blanket "not available".

### SYS-27 — cross-subsystem checking

All six of SYS-27's own candidate flows, held verbatim by a drift guard, each
evaluated for architectural support: every endpoint must be matched by a
*different* selected subsystem (whole-token name match with an optional trailing
digit run, labelled as a NAME basis); every intermediate must be a real registry
entry of one of `sri`'s own resource types. A supported flow gets a list of what
a real check would **need**, every input `NOT_AVAILABLE` with its reason;
`check_content_status` is schema-pinned to
`NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL`.

## 4. The SYS-39/SYS-40 boundary — enforced, not asserted

The hard constraint was respected in full. **No** System-Level UVM source, System
command.txt, System Virtual Sequencer, command routing/adapter, shared
sequencer/driver/queue, scoreboard content or cross-subsystem check content was
written anywhere outside a throwaway test fixture, and
`cross_subsystem_scenarios()` / `end_to_end_scoreboard()` / `system_coverage()`
were **not touched** — they still raise `NotImplementedError`.

That is enforced rather than claimed:

- `probe_composer_boundary()` **calls all three stubs** and records that each
  raised `NotImplementedError`. The record is in every produced document and in
  the rendered report; a stub that had been filled in flips `boundary_intact` to
  `False` and the CLI to exit 2. This is the audit's "referencing the intentional
  NotImplementedError boundary without crossing it" as a live check rather than a
  comment.
- `assert_no_emitted_artifacts()` raises on: a removal action, an unevidenced
  candidate, a built access point, a modified or replaced subsystem scoreboard,
  an implemented correlation layer, generated check content, any non-empty
  `artifacts_generated`. Each has a test.
- The schema pins four `const`s (`PLANNED_NOT_IMPLEMENTED` ×2, `false` ×2,
  `NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL`) plus `maxItems: 0` on
  `artifacts_generated` and `scenarios`.
- `test_this_module_holds_no_file_writer_at_all` — the module contains **zero**
  `.write_text(` / `.write_bytes(` / `open(` / `mkdir(`. Unlike SYS-15..17's
  layer, which persists a registry, this one persists nothing.
- `test_a_full_run_leaves_every_subsystem_tree_byte_identical` — byte-for-byte
  snapshot comparison across a full run.
- `test_the_rendered_report_contains_no_systemverilog` — the report is scanned
  for `module`/`endmodule`/`class`/`task`/`` `uvm_ `` etc.
- A real CLI subprocess run after which both synthetic subsystem trees are
  byte-identical and no `system_command.txt`, `soc_command.txt` or System-Level
  `.sv` exists anywhere.

## 5. Tests — the hard cases

65 tests. Fixtures are **imported** from the SYS-5..8 and SYS-18..22 suites, not
copied, so the layers cannot drift into separate fixture shapes. The genuinely
ambiguous/conflicting cases the task required:

- One initialization invoked by two subsystems → `SYSTEM_ONCE` +
  `DEDUPLICATION_CANDIDATE` with a real `command.txt:line` from **each** side.
- The same finding cited by only **one** side → stays `KEEP` (detection power for
  the evidence rule).
- Two subsystems actively driving one DUT-side BFM → one named access point.
- The same pair only **READING** one block → no access point, and never
  `SHARED_RESOURCE_COMMAND`.
- A registry entry `BLOCKED` by a driver conflict → unschedulable, and
  `scheduling_plan_clean` goes `False`.
- A third independent subsystem never serialized with the contending pair,
  **plus** a control test that feeds the check a fabricated violation and asserts
  it fires.
- A pair matching `SERIALIZE_RESOURCE` **and** `INTERRUPT_DEPENDENT` at once →
  precedence winner, loser kept in `also_matched`.
- An interrupt handshake over read-only sharing (so `INTERRUPT_DEPENDENT` is
  reached on its own, not only as a runner-up).
- A clock-domain crossing over one shared address (a different clock *alone* is
  the normal case and correctly is not a dependency).
- Two subsystems whose files both contain `CPUREAD4B` → **no** cross-subsystem
  order from the shared name.
- A supported vs. endpoint-absent vs. intermediate-absent SYS-27 flow; one
  subsystem refused as both ends of a cross-subsystem flow; a single-participant
  flow flagged against `system_level_composition_gate`'s
  `NOT_CROSS_SUBSYSTEM_SCENARIO`.
- Six drift guards holding `SYS23_CLASSES`, `SYS25_RELATIONSHIPS`,
  `SYS25_PRECEDENCE` and the six SYS-27 flows to the master prompt's own
  sentences **and** to the JSON schema's enums.

## 6. Honest limits

- The `clock_domain` addition to `scp`'s IR derivation is one line of data
  plumbing, not a new derivation — `_clock_domain()` still owns the answer,
  including its `UNRESOLVED`/`NOT_APPLICABLE` status, which is copied verbatim.
- SYS-24's `routed_commands` is empty (with a stated reason) for a registry entry
  the SYS-9 inventory supplies no `command_resource_ids` link for. That is an
  honest absence; guessing the link by name would be the substring inference this
  codebase refuses elsewhere.
- SYS-27's endpoint matching is a **name**-token match and is labelled as one in
  every record. The intermediate half is structural (a registry entry of that
  type either exists or does not).
- This harness repo still has no real multi-subsystem project, so every registry
  entry in the tests is synthetic and `.dv-harness/soc-composer/subsystem_environment_registry.json`
  remains legitimately absent — re-verified, only `_template.json` is on disk.
- Nothing here closes SYS-26/27 for real. Cross-subsystem scoreboard and check
  **content** remains SYS-40, gated on a separate explicit human approval this
  workflow does not obtain.

## 7. Front door

```
dv-harness system-scheduling-plan --select A --select B [--command-inventory CSV] [--json]
```

Routes through `scp.plan_system_commands()` → `srr.plan_system_integration()` →
`sri.analyze_selected_subsystem_resources()` →
`subsystem_discovery.require_explicit_selection()`, so SYS-1's refusal to compose
an unselected set is not bypassed. Exits 2 while independent subsystems would be
globally serialized, any shared resource is unschedulable pending ownership, or
the composer's cross-subsystem stubs have stopped raising.
