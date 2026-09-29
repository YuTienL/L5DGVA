# SYS-15..SYS-17 gap close — SYSTEM_RESOURCE_REGISTRY + the two mandatory matrices

**Status: DONE**

Scope: SYS-15, SYS-16, SYS-17 of the "FIRST-CLASS DOMAIN EXTENSION — SYSTEM-LEVEL
VERIFICATION INTEGRATION WORKFLOW" section of
`D:/DV/Task/DV_Agent_Harness_L5/DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_SystemLevel_AMBA4_SyoSil_CCE_Research.md`
(lines 4275–4519; SYS-15..17 at lines 4363–4374). Discovery/analysis/planning/reporting
only — SYS-39's stop condition, never SYS-40.

Repo root for every path below: `D:\DV\Task\DV_Agent_Harness_L5\v50`.

---

## 1. Audit re-verification (the four claims this build rests on)

Each was re-checked against the real files rather than accepted from the task text, and
each is now held by a test rather than by this paragraph.

| Claim | Verdict | Evidence / holding test |
|---|---|---|
| SYS-15/16/17 all NEVER_BUILT | **Confirmed** | Repo-wide grep for `resource_id`, `consumer_subsystems`, `physical_hierarchy`, `SYSTEM_RESOURCE_REGISTRY`, `REUSE_SHARED`, `KEEP_INDEPENDENT`, `PASSIVE_ONLY`, `MERGE_ACCESS_PATH`, "Subsystem Integration Matrix", "Deduplication Matrix" over `dv_harness/`, `tools/`, `.claude/`, `docs/`: zero hits before this change. |
| The existing subsystem registry is a different GRANULARITY | **Confirmed** | `tools/real_env/system_level_validator.py`'s `REQUIRED` is exactly the six fields `name, environment_manifest, release_sha, qualification_state, interface_compatibility, clock_reset_compatibility`; `.dv-harness/soc-composer/subsystem_environment_registry_template.json` is `{"subsystems": []}`. Held by `test_the_subsystem_registry_template_is_still_six_field_subsystem_granularity`. |
| The real runtime `subsystem_environment_registry.json` is still absent | **Confirmed** | Same test asserts the file does not exist. |
| `connectivity.render_matrix_table()` is not parameterizable | **Confirmed** | It calls `build_connectivity_matrix()`, hardcoded to module-level `MATRIX_COLUMNS` (`connectivity.py:2404`, `:2506`, `:2520`); `MATRIX_COLUMNS` carries no `owner`/`consumer_subsystems`/`conflict_status`/`reuse_decision`/`shared`/`exclusive` column at all. Held by `test_the_connectivity_matrix_structurally_cannot_hold_a_registry_entry`. |

**One correction to the task's own framing, made deliberately and tested:** the step title
says "18-field". SYS-15's own sentence names **nineteen** fields
(`resource_id, resource_type, protocol, physical_hierarchy, role, owner,
consumer_subsystems, active_passive, shared, exclusive, clock, reset, address_domain,
source_environment, source_config, conflict_status, reuse_decision, evidence, confidence`).
`SYS15_FIELDS` follows the document, and
`test_sys15_fields_match_the_requirements_own_list_one_to_one` asserts `== 19` against the
requirement text copied verbatim into the test, so the code and the document cannot drift
apart in either direction.

## 2. What was built

### `dv_harness/system_resource_registry.py` (new, 1321 lines)

**Why a new module, not an extension.** Three registries were candidates for "extend" and
all three are a different granularity from SYS-15's:

- `subsystem_environment_registry.json` — one row per **ENVIRONMENT**, six
  identity/qualification fields, written only by `engine.py:1181`
  `_persist_subsystem_registry_entry()` on a gate-verified SIGNOFF PASS and validated
  against that six-field contract by `tools/real_env/system_level_validator.py`. Adding
  resource rows would break that validator.
- `connectivity.MATRIX_COLUMNS` — one row per **INTERFACE of ONE environment**, no
  subsystem-identifying column, so it structurally cannot express `owner` vs
  `consumer_subsystems`.
- SYS-15's registry — one row per **SYSTEM-LEVEL RESOURCE**, where the same physical
  resource seen in two subsystems' evidence collapses into ONE entry. Only expressible over
  N subsystems at once, so like `system_resource_inventory` (SYS-9..14) it has no
  single-subsystem home.

Everything below **imports and composes** the SYS-9..14 layer; nothing is re-derived.
`test_no_second_relationship_classifier_or_conflict_rule_is_defined_here` asserts the
module defines no `classify_resource_relationship` / `apply_active_driver_conflict_rule` /
`evaluate_shared_vip_promotion` / `compare_resources` / `detect_duplicate_resources` of its
own, and that the relationship vocabulary is imported rather than respelled.

**SYS-15 — `build_system_resource_registry(analysis)`.**
- Members collapse into one entry by **union-find**, so identity is transitive: A≡B and
  B≡C yields one entry, not two overlapping ones (`test_identity_is_transitive_so_three_subsystems_make_one_entry`).
- Merges only on `MERGING_RELATIONSHIPS` = SAME_PHYSICAL / DRIVER_CONFLICT /
  CONFIGURATION_CONFLICT / MONITOR_ONLY_DUPLICATE. **SHARED_LOGICAL_RESOURCE and UNKNOWN
  deliberately do NOT merge** — SYS-11's own reason string for SHARED_LOGICAL says physical
  equivalence is *not* established, and collapsing on that would make the authority assert
  something nothing proved. They become a `related_entries` cross-reference instead
  (`test_a_shared_logical_pair_is_cross_referenced_not_merged`).
- A **within-subsystem** active bind-target collision merges too, from
  `connectivity.find_active_bind_target_collisions()`'s per-subsystem output: two ACTIVE
  rows of one matrix claiming one bind target are two agents on ONE interface, and holding
  two entries would present that interface as two consumable resources
  (`test_a_within_subsystem_collision_makes_one_entry_not_two`).
- `owner` and `consumer_subsystems` are genuinely different fields and follow the
  **decision**, never the consumer count: a two-agent collision inside one subsystem has
  exactly one consumer, and naming that subsystem the owner would report ownership as
  settled at the moment SYS-12 stopped integration because it is not.
- A field its members disagree on is reported as `DISAGREEMENT(a,b)` — comma-separated,
  because these values land in markdown cells and a literal pipe splits the row silently
  (`test_a_pipe_in_real_data_does_not_split_a_rendered_row`).
- `confidence` is `inference.score_confidence()`, the one scorer in the codebase.
  `exclusive`/`shareable` disagreements are deliberately **not** counted as
  counter-evidence: both are DERIVED from active/passive, so the healthy
  active-driver + passive-monitor case necessarily disagrees on them, and scoring that as a
  contradiction would cap the confidence of exactly the least problematic pairs
  (`test_an_active_passive_pair_is_not_scored_as_a_contradiction`).
- Entry ids are `SYSRES::<type>::<key>`, a shape deliberately different from SYS-9's
  subsystem-local `<SUBSYS>::<hier>::<iface>`, with a hard `DUPLICATE_REGISTRY_ENTRY_ID`
  raise if two groups ever key to one id.

**SYS-17 — `decide_reuse()` + `build_vip_deduplication_matrix()`.** SYS-13's promotion
vocabulary and SYS-17's Decision vocabulary are *not* the same list (one answers "may this
be promoted", the other "what do we do with this pair"), so this is a real translation. It
is written **once** and feeds both SYS-15's `reuse_decision` field and SYS-17's Decision
column — `test_the_registry_and_the_dedup_table_never_disagree_about_a_decision` holds
them to each other. Precedence, most-restrictive first: DRIVER_CONFLICT→BLOCKED;
subsystem-specific VIP (SYS-14)→KEEP_INDEPENDENT; INDEPENDENT→KEEP_INDEPENDENT;
CONFIGURATION_CONFLICT→RECONFIGURE (naming the action, never a winner — the escalation
returned UNDECIDABLE_SAME_AUTHORITY); MONITOR_ONLY_DUPLICATE→PASSIVE_ONLY;
SAME_PHYSICAL→REUSE_SHARED when SYS-13 says promotable, else PASSIVE_ONLY under the one
active driver, else UNKNOWN; SHARED_LOGICAL→MERGE_ACCESS_PATH unless SYS-12 HELD it;
UNKNOWN→UNKNOWN. A final override blocks any identity-asserting pair whose resource sits in
SYS-12's stopped set, and deliberately does *not* apply to an INDEPENDENT pair
(`test_a_stopped_resource_cannot_be_laundered_clean_by_a_second_pair` and its converse).

"Active Driver Conflict" is three-valued — `YES` / `NO` / `UNPROVEN_BOTH_ACTIVE` — and
computed independently of the Decision. Two ACTIVE agents whose physical identity is not
established are the dangerous middle case; reporting them NO is how a real conflict gets
integrated (`test_active_driver_conflict_is_three_valued_and_unproven_is_not_no`).

**SYS-16 — `build_subsystem_integration_matrix()`.** One row per selected subsystem, its
nine columns verbatim. `selection` (SYS-1..4) and `synthesis` (SYS-5..8) are optional; a
column they would answer reports `NOT_AVAILABLE`, never a zero and never READY, because
"nobody looked" and "we looked and found none" are opposite findings — SYS-6's own
DERIVED/NOT_AVAILABLE/NOT_APPLICABLE status is preserved through the Scoreboard cell.
Readiness comes from `subsystem_discovery`'s existing SYS-4 verdict; no second readiness
classifier. "Every selected subsystem must appear" is
`assert_every_selected_subsystem_present()`, which **raises** — a table that silently omits
a subsystem reads as a complete statement about the selection.

**Rendering.** SYS-16 and SYS-17 are markdown renderers in this module, following the
mandated-table precedent already set by `subsystem_discovery.render_discovery_table()`
(SYS-1's six columns) and `system_resource_inventory.render_*_table()` (SYS-9/SYS-11) —
*not* an extension of `connectivity.render_matrix_table()`, which the audit confirmed is a
fixed-width ASCII renderer hardcoded to `MATRIX_COLUMNS` and would have had to change what
every existing caller gets. `connectivity.py` was therefore **not modified** by this step.

### Other files

- `dv_harness/schemas/system_resource_registry.schema.json` (new) — the entry contract,
  whose `required` list is SYS-15's 19 fields verbatim; two tests hold `SYS15_FIELDS` and
  `SYS17_DECISIONS` to the schema, and `test_the_persisted_registry_validates_against_its_own_schema`
  validates a real produced registry against it.
- `.dv-harness/soc-composer/system_resource_registry_template.json` (new) — the empty
  template, mirroring the existing `subsystem_environment_registry_template.json`
  convention. The real runtime file is *not* created in this repo.
- `dv_harness/cli.py` (+64 lines, two hunks) — `dv-harness system-integration-plan
  --select A --select B [--write-registry] [--json]`. It goes through
  `system_resource_inventory.analyze_selected_subsystem_resources()` →
  `subsystem_discovery.require_explicit_selection()`, so SYS-1's refusal is not bypassed,
  and exits **2** while any SYS-17 Decision is BLOCKED or any Integration Status is a
  BLOCKED_* class.

## 3. The SYS-39/SYS-40 boundary

No System-Level UVM source, System command.txt, System Virtual Sequencer, shared agent or
command routing/adapter is generated anywhere, and no subsystem environment is modified.
Five tests enforce that rather than a comment claiming it:

- `test_a_full_sys15_17_run_modifies_no_file_anywhere` — byte-for-byte tree snapshot
  across a full registry + both matrices + report run.
- `test_the_report_contains_no_systemverilog_and_no_command_txt_content`.
- `test_no_system_level_uvm_or_command_txt_source_is_emitted_by_this_module` — including
  that the module contains exactly **one** `.write_text(` call and zero `open(`, and that
  the one write is the registry writer.
- `test_the_soc_composer_cross_subsystem_stubs_still_raise` — `cross_subsystem_scenarios()`
  / `end_to_end_scoreboard()` / `system_coverage()` still raise `NotImplementedError`;
  they were not touched.
- `test_the_cli_write_registry_flag_persists_only_the_planning_document` — after a real
  `--write-registry` subprocess run, both subsystem environment trees are byte-identical
  and the subsystem registry beside it still holds exactly its six fields.

The registry carries `authority_scope: "PLANNING_ONLY"` on its face,
`write_system_resource_registry()` refuses anything else, and nothing in this module reads
the file back to apply it. Every `owner`, `reuse_decision` and `system_owner` is a
recommendation; the phase boundary string says so and travels with the artifact.

## 4. Tests

`dv_harness_tests/test_system_resource_registry.py` — **53 tests**, every fixture
synthetic and inside `tmp_path`. The subsystem builders are imported from
`test_system_resource_inventory` rather than copied, so the two layers cannot drift into
two different fixture shapes.

Deliberately not a happy path — the carrying cases are the conflicting and ambiguous ones:
two subsystems both actively driving one CPU AXI Master (each subsystem's own connectivity
self-check passing 2-for-2, asserted in the test); the same pair with one side passive
(REUSE_SHARED with a *proposed* System owner); the same physical resource configured
differently (RECONFIGURE, two differing `configuration_hash` values, escalation verdict
UNDECIDABLE_SAME_AUTHORITY); a third subsystem joining the same resource; two passive
monitors (PASSIVE_ONLY, never REUSE_SHARED); two subsystems whose SoC address ranges
genuinely overlap (SHARED_LOGICAL cross-referenced, not merged; both active → HELD →
BLOCKED with ADC `UNPROVEN_BOTH_ACTIVE`); a PCIe VIP pair that must never be promoted; two
ACTIVE rows inside one subsystem's own matrix; a clean pair on a stopped resource that must
not launder it; and the converse, an INDEPENDENT pair that must not be blocked by an
unrelated stop. Plus five drift guards holding `SYS15_FIELDS` / `SYS16_COLUMNS` /
`SYS17_COLUMNS` / `SYS17_DECISIONS` to the requirement's own sentences and to the JSON
schema, and two real CLI subprocess runs.

**Test summary:** 53 new tests pass; the full `dv_harness_tests` suite passes apart from
11 documented pre-existing `pueued`-daemon environmental failures and one load-sensitive
dashboard timing test that passes in isolation.

### Runs

The suite takes well over an hour on this machine, so it was run in three non-overlapping
blocks (concurrent pytest processes were found to poison each other — an earlier run with
three in flight produced 7 failures that did not reproduce when run alone, which is why
every number below comes from a run that had the machine to itself):

| Run | Result |
|---|---|
| `test_system_resource_registry.py` (new) | **53 passed** |
| `-k "cli or discovery or subsystem or system or connectivity or composer or soc"` — every suite touching `cli.py`, the new module, connectivity, soc-composer | **1030 passed**, 5 failed + 6 errors, all `pueued` |
| `test_environment_mode_router` / `test_environment_mode_selection_gate` / `test_graph_runtime_removed` / `test_mcp_read_only_boundary` / `test_job_memory_evidence_mirror` — the suites that enumerate `dv_harness/*.py`, `schemas/*.json` or `.dv-harness/soc-composer/` and could have been perturbed by four new files | **53 passed** |
| Files `test_a*`–`test_e*` (51 files) | **1628 passed, 6 failed** |
| Files `test_e*`–`test_s*` | **2965 passed, 6 errors, 0 failed** |
| Files `test_s*`–`test_w*` (45 files, includes both new and SYS-9..14 suites) | **1067 passed, 0 failed** |

Every failure across all of it:

- `test_cli_pueue.py` ×5 and `test_pueue_client.py::TestRealPueueIntegration` ×6 errors —
  all one root cause printed verbatim by the fixture, `AssertionError: real pueued did not
  come up`. `pueued` is on PATH (`/c/Users/peter.lin/bin/pueued`) but the daemon does not
  start in this environment. Documented as pre-existing in at least four prior `.work`
  reports in this repo; nothing in this change references pueue.
- `test_dashboard_interactive.py::test_start_loop_true_advances_through_multiple_stages_in_background`
  — a background-timing test. Re-run alone: **1 passed in 54.33s**. Load-sensitive, not
  caused by this change (which adds no engine, graph or dashboard code).

## 5. Commit

`d87c3b8` — *system-level(SYS-15..17): SYSTEM_RESOURCE_REGISTRY + the two mandatory
matrices*.

Files: `dv_harness/system_resource_registry.py` (new),
`dv_harness/schemas/system_resource_registry.schema.json` (new),
`dv_harness_tests/test_system_resource_registry.py` (new),
`.dv-harness/soc-composer/system_resource_registry_template.json` (new),
`dv_harness/cli.py` (+64, two hunks, scope-staged via `git apply --cached`).

## 6. Not done here (out of scope, named rather than implied closed)

- SYS-18..38 (System-Level architecture descriptor, command routing plan, scoreboard
  integration plan, address-map analysis, clock/reset domain comparison, traceability,
  version pinning, …) — later steps of this same sequence.
- SYS-40's implementation half. Nothing in this step may be auto-applied; acting on a
  registry entry requires a separate explicit human approval this workflow does not obtain.
- `soc_environment_composer.cross_subsystem_scenarios()` / `end_to_end_scoreboard()` /
  `system_coverage()` remain `NotImplementedError` on purpose and were not touched.
