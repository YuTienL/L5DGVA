# SYS-28..SYS-32 gap close — cross-subsystem address map, clock/reset, scenario model, failure isolation and triage

**Status: DONE**

**Test summary:** 843 tests pass across every suite touched — 41 new in
`test_system_topology_analysis.py`, 32 new in `test_system_failure_triage.py`,
411 across the whole SYS-1..30 system-level suite, 237 across
memory_vault/evidence_db/lsf_client/job-memory (the `build_failure_signature()`
regression surface), and 154 across source_authority/question_queue/inference/
amba_fabric_generator/address_map_verifier (the reused primitives).

---

## What the audit found, and what changed

| Req | Audit verdict | Now |
|---|---|---|
| SYS-28 | PARTIALLY_WIRED — single-subsystem primitives real, cross-subsystem reconciler NEVER_BUILT; `ADDRESS_OVERLAP_*` existed only in a dead JS file | Real cross-subsystem reconciler in `dv_harness/system_topology_analysis.py`, calling `compute_address_regions()` per pair rather than re-deriving the arithmetic |
| SYS-29 | NEVER_BUILT for cross-subsystem; `clock_reset_compatibility` a self-attested string | Real pairwise clock/reset comparator + `clock_reset_compatibility_input()`, the computed value that string should carry |
| SYS-30 | PARTIALLY_WIRED — participation structure hard-gated, no scenario-shape schema | Real planning-time block/parallel-shape descriptor derived from the SYS-25 relationships and the SYS-21 IR; body pinned NOT_GENERATED |
| SYS-31 | PARTIALLY_WIRED — no `vip_agent`/`resource`/`system_scenario_id`, no N-sided record | `vip_agent`/`resource` added to `memory_vault.build_failure_signature()` (additive, omitted-when-absent); real SYSTEM-level wrapper in `dv_harness/system_failure_triage.py` |
| SYS-32 | NEVER_BUILT | Real locus + mechanism classifier that CONSULTS the SYS-15/22/24/25/28/29 documents and re-derives none of them |

---

## Files

**New**
- `dv_harness/system_topology_analysis.py` — SYS-28/29/30.
- `dv_harness/system_failure_triage.py` — SYS-31/32.
- `dv_harness/schemas/system_topology_analysis.schema.json`
- `dv_harness/schemas/system_failure_record.schema.json`
- `dv_harness/schemas/system_failure_triage.schema.json`
- `dv_harness_tests/test_system_topology_analysis.py` (41 tests)
- `dv_harness_tests/test_system_failure_triage.py` (32 tests)

**Modified (additive only — verified by `git diff`, zero deleted lines)**
- `dv_harness/memory_vault.py` — two optional kwargs on `build_failure_signature()`.
- `dv_harness/cli.py` — one new `system-topology-analysis` verb, mirroring the
  `system-command-plan` / `system-scheduling-plan` precedent (exit 2 on a real
  conflict so a CI step cannot read a conflicted topology as a clean run).

---

## The reuse decisions, and why each one is the reuse rather than a rewrite

**The overlap decision is `amba_fabric_generator.compute_address_regions()`'s,
not a second interval comparison.** `_pairwise_overlap()` builds the two-region
slave list and reads which `AddressMapError` that function raises:
`ADDRESS_MAP_OVERLAP` means they intersect, `ADDRESS_MAP_GAP` means they are
separated, and `ADDRESS_MAP_NOT_FULL_COVERAGE` (which this layer deliberately
ignores — two regions from two different subsystems have no obligation to span
an address space) means they are adjacent. This keeps ONE definition of
"overlap" in the repo, including its exclusive-end convention
(`cur.start < prev.end`) that exists to match
`fabric_topology_completeness_gate.py`. A test asserts the probe agrees with a
direct call on the same two regions, using perfectly adjacent regions — the
exact case a hand-written comparison usually gets wrong.

Per-subsystem self-consistency ("does ONE subsystem's map overlap itself?") is
likewise that function's verdict, recorded verbatim from the reason it raised,
and reported in its own `self_consistency` block rather than mixed into the
cross-subsystem table — an intra-subsystem defect is not a cross-subsystem
finding.

**Address parsing is `afg.parse_addr()`.** A test greps the module for any
`int(..., 0)`/`int(..., 16)` and fails if one appears.

**Conflict escalation is `source_authority.escalate_conflict()`.** Both sides of
a cross-subsystem address conflict are the same authority tier (tier 4,
`register_file`, qualifier `dut` — `dut_facts.address_map` is a machine-readable
address description cross-checked against `dut_facts.registers`), so
`resolve_conflict()` returns `UNDECIDABLE_SAME_AUTHORITY`, which is the honest
answer: the 9-level order cannot say which of two equally-real address maps is
wrong. `domain="dut"`, the same routing `address_map_verifier.escalate_doc_
disagreements()` uses. Idempotent — a re-run over unchanged maps re-mints the
same Q-IDs, asserted by a test.

**The memory/DMA/APB/AXI name vocabulary is
`system_resource_inventory.RESOURCE_TYPE_TOKENS`**, read out of that tuple
rather than retyped, so SYS-10's duplicate detection and SYS-28's SHARED_MEMORY
verdict cannot come to mean different things by "memory".

**SYS-29's duplicate/conflicting clock-reset AGENT half is READ off the SYS-15
registry** (`resource_type == CLOCK_RESET_AGENT`, with its already-decided
`conflict_status`/`reuse_decision`). SYS-9..14 already inventoried, classified
and decided; re-running that here would be a second answer to a settled
question.

**SYS-30 consumes the SYS-25 pair relationships and the SYS-21 IR** and
classifies no pair itself. Its only contribution is the block grouping.

**SYS-31's symptom shape is `memory_vault.build_failure_signature()`'s**, and
SYS-32's prior evidence is `search_related_memory_for_debug()`'s and its
confidence is `inference.score_confidence()`'s. Tests grep both new modules for
a second definition of any of them.

---

## The design decisions worth arguing about

**An overlap is not automatically a bug, and three of SYS-28's four values say
so.** Two subsystems reaching one DDR window overlap by design; two declaring
the same APB block overlap because it is one block seen twice. So SHARED_MEMORY
and ADDRESS_OVERLAP_VALID fire from positive evidence and
ADDRESS_OVERLAP_CONFLICT is the RESIDUAL of a real intersection nothing
explains. Reporting every overlap as a conflict is how a column gets ignored.

**UNKNOWN leads the precedence, and that is the case most easily got wrong.** An
overlap computed on top of a base a subsystem's own `register_map_agreement`
already reports as `DISAGREES` is a finding about that subsystem's two
artifacts, not about the pair — calling it a cross-subsystem conflict points the
reader at entirely the wrong two things. The shared-memory reading such a pair
ALSO matched survives in `also_matched` rather than being dropped: a pair with
two things wrong with it should report both.

**Content is classified before transport.** SYS-28's own list mixes two
orthogonal axes — MEMORY/DMA say what is AT a range, APB/AXI say how you reach
it. A DDR window on an AXI port is both, and trusting the declared bus first
would type every AXI-attached memory as an AXI range, making SHARED_MEMORY
unreachable for exactly the case it exists for. So memory/DMA content tokens are
tested first, the declared `bus` field (real input-contract evidence) next, and
register name tokens last.

**SYS-29 keeps four separate conflict verdicts** (clock source, clock frequency,
reset polarity, reset sequencing) rather than one CONFLICTING value. Those are
four different fixes, and a single value would name the pair without naming any
of them.

**`clock_reset_compatibility_input()` is three-valued and NOT wired into the
gate.** `system_level_composition_gate.py` and
`subsystem_environment_registration_gate.py` read a caller-supplied
`"PASS"/"FAIL"` string today with nothing computing it. This is the real
computation behind that field, returned as an INPUT a caller may supply —
rewiring a hard gate to read a new source is a behaviour change and this step is
analysis. UNKNOWN is the third value precisely because the two-valued field
cannot express "the facts were NOT_AVAILABLE", and a caller must never report
that as PASS. `gate_wired` is pinned `false` in the schema so this stays honest.

**SYS-30's block rule is the most conservative one that still produces parallel
blocks.** A command joins the block being built only if its relationship to
every command already in it is PARALLEL_SAFE; anything else — including
UNKNOWN — closes the block. UNKNOWN closing a block matters: "we could not tell"
and "we checked and it is safe" are different facts and only one licenses
concurrency. Two commands of ONE subsystem are never placed in one parallel
block, because a command.txt is sequential by construction and re-ordering it is
not this layer's business.

**`vip_agent`/`resource` are OMITTED from the failure signature when absent, not
written as nulls.** `evidence_db.signature_key()` hashes the whole dict, so
always-present keys would have changed every signature this repo has ever
computed and silently orphaned the accumulated
`occurrence_count`/`first_seen`/`last_seen` rows on the `failure_signatures`
table. Omitted-when-absent keeps a caller that supplies neither byte-identical,
while a caller that DOES name a VIP agent gets a genuinely different signature —
which is correct, since the same UVM_ERROR from two different agents is two
failure shapes. A test pins the default dict's exact key set and asserts the key
is unchanged against a literal.

**SYS-32 reports NOT_CONSULTED separately from consulted-and-empty.** Four of
its seven causes are decided by documents a caller may not have supplied.
Without that distinction an unsupplied address reconciliation would read exactly
like "no address conflict exists", which would quietly promote every unexamined
failure to GENUINE_SOC_INTEGRATION_BUG. The residual's own basis string names
the unconsulted sources.

**Every cause match is evidence-linked, never name-only.** A cause fires only
when the FAILING record's own `resource`/`vip_agent`/`command` value appears in
the upstream row. A `NOT_CAPTURED` dimension contributes nothing, and the
command match is exact-or-`::`-suffix, never substring — that is SYS-10's "do
not decide duplicates by class names alone" applied to triage. Both have
explicit control tests: a driver conflict elsewhere in the registry is NOT
attributed to a failure naming a different resource, and a command named `WRITE`
does NOT link to a pair containing `PCIE_SS::CPUWRITE4B`.

---

## The SYS-39/SYS-40 boundary

Nothing here emits System-Level UVM source, a System command.txt, a scenario
body, a parallel block, a System Virtual Sequencer, a command router/adapter, an
address decoder or a clock/reset generator. Enforced three ways, not asserted:

1. `assert_no_emitted_artifacts()` runs on every produced document and refuses a
   generated artifact, a scenario carrying a body (or a `scenario_body`/
   `command_txt`/`generated_source` key), or an ownership proposal whose status
   left `PLANNED_NOT_IMPLEMENTED`. `assert_not_collapsed()` is the SYS-31
   equivalent. Tests drive all four failure paths.
2. The schemas pin the boundary as `const`: `scenario_body_status`,
   `invented_command_count: 0`, `new_language_introduced: false`,
   ownership `status`, `regions_relocated: 0`, `address_maps_modified: 0`,
   `interrupt_maps_modified: 0`, `clocks_or_resets_modified: 0`,
   `scenario_bodies_generated: 0`, `system_command_txt_written: 0`,
   `generic_system_failure_records: 0`, `root_cause_decided: false`,
   `failures_fixed: 0`, `failures_waived: 0`, and `artifacts_generated`
   `maxItems: 0`. A document that crossed the line could not validate.
3. `probe_composer_boundary()` is called into every topology document, so
   `soc_environment_composer`'s three `NotImplementedError` stubs still raising
   is a CHECKED fact in every produced report rather than a comment that can go
   stale. They are untouched by this build.

The real-CLI end-to-end test runs a real subprocess through the whole SYS-1 →
SYS-30 stack against a real synthetic two-subsystem project and asserts both
subsystem environment trees are byte-identical afterwards, that no
`system_command.txt`/`soc_command.txt`/`system_scoreboard.sv`/
`system_virtual_sequencer.sv`/`system_address_decoder.sv` exists anywhere in the
tree, and that every `.sv` file still contains only its fixture placeholder.

---

## What is REACHED, not WIRED — disclosed rather than implied closed

- `dv-harness system-topology-analysis` is a real CLI front door (a real caller
  exists, exit 2 on a real conflict), and `system_failure_triage` is importable
  and tested, but **no graph node dispatches either**. This matches the
  SYS-15..27 layers' own state exactly; wiring a stage is a behaviour change
  this step did not take.
- `clock_reset_compatibility_input()` is computed but **not read by either
  gate** — see above for why that is deliberate.
- This repo's `.dv-harness/soc-composer/subsystem_environment_registry.json`
  is still legitimately absent (re-verified: the real CLI run reports
  `0 registered`), so every number in this report comes from synthetic
  fixtures. The mechanisms are proven to fire on a real two-subsystem project
  tree the CLI test builds; they were not made to "have fired" here by writing
  fabricated registry entries into this project's real audit trail.
- SYS-31's ten dimensions are proven preserved on a record this layer BUILDS.
  No production caller composes one yet — `lsf_client.py`'s job record is still
  one-job/one-subsystem, as it should be; joining N of them into a System record
  needs a real System scenario to run, which is SYS-40.
