# SPEC-6 — REMOVE_DUPLICATE, SYS-17's eighth decision value (spec section 198)

**Status: DONE**

**Test summary:** 618 passed, 0 failed — `test_system_resource_registry.py` (59,
including 5 new), plus every other system-level suite
(`test_system_resource_inventory.py`, `test_system_scheduling_plan.py`,
`test_system_command_plan.py`, `test_system_topology_analysis.py`,
`test_system_regression_readiness_and_phase1_report.py`,
`test_system_level_track_b_gate_crosscheck.py`, `test_generation_readiness.py`,
`test_system_build_proof.py`, `test_system_failure_triage.py`,
`test_soc_environment_composer.py`, `test_subsystem_discovery.py`,
`test_subsystem_architecture_and_command_contract.py`).

---

## 1. Gap independently re-verified before building

| Claim | Verified how | Result |
|---|---|---|
| Spec section 198 lists REMOVE_DUPLICATE | Read `CLAUDE_DV_Agent_Harness_L5_SPEC_TO_SYSTEM_UVM_COMPLETE.md:6617-6628` — the `Decisions:` block under SYSTEM_RESOURCE_REGISTRY | **Confirmed.** Eight values, one per line: REUSE_SHARED / KEEP_INDEPENDENT / PASSIVE_ONLY / **REMOVE_DUPLICATE** / RECONFIGURE / MERGE_ACCESS_PATH / BLOCKED / UNKNOWN |
| The code had only seven | `grep -rn "REMOVE_DUPLICATE"` over `dv_harness/`, `tools/`, `dv_harness_tests/`, `.claude/`, `docs/` | **Zero hits.** `system_resource_registry.SYS17_DECISIONS` was the seven-value tuple; `DECISION_SEVERITY` and `schemas/system_resource_registry.schema.json`'s enum matched it; the drift-guard test `test_sys17_decision_vocabulary_is_closed_and_verbatim` pinned the seven-value sentence |
| PASSIVE_ONLY was standing in for it | Read `decide_reuse()`'s `REL_MONITOR_ONLY_DUPLICATE` branch | **Confirmed and it is a genuinely different decision.** The branch returned PASSIVE_ONLY unconditionally with reason "both may observe and neither drives" — i.e. *keep the second monitor*. REMOVE_DUPLICATE is *delete it*. There was no code path anywhere that could recommend removing a redundant agent |

## 2. What was built

### The distinction, and why it needed real logic rather than a new constant

Both decisions apply to the SAME SYS-11 relationship class,
`MONITOR_ONLY_DUPLICATE` (physical identity established + both sides PASSIVE).
The question that separates them is whether the second monitor can still
*observe* something the first cannot. Getting that wrong in the REMOVE
direction destroys real observability — a checker, a covergroup, a protocol
view — and a simulation that quietly stops observing something does not
announce it.

`system_resource_registry.classify_duplicate_observability(relationship, a, b)`
is the classifier. It reaches `REDUNDANT_ZERO_UNIQUE_OBSERVABILITY` only on
**positive, complete** evidence; every other state, including "nothing was
captured", is `UNIQUE_OBSERVABILITY_POSSIBLE` → PASSIVE_ONLY. Three checks,
each reading evidence a mechanism already in this repo produces:

1. **Both sides carry a real captured configuration**
   (`configuration.config_field_count > 0`, i.e. a live vip_config dump reached
   `env_manifest.build_vip_config()` for that instance). A monitor's enabled
   checks, coverage groups and analysis depth ARE configuration; with none
   captured, "these observe the same things" is an assumption. This is the
   check that stops an absence of evidence reading as evidence of redundancy.
2. **The two `configuration_hash` values are EQUAL.** That hash
   (`system_resource_inventory._config_hash`) covers the whole field map, so
   equality means identical field SETS and identical values. This is
   deliberately **strictly stronger than SYS-10's own `configuration` signal**,
   which compares only the keys both sides happen to share and therefore
   reports AGREE for a monitor carrying an extra `coverage_enable` the other
   lacks — exactly the shape of a covergroup only one monitor has.
3. **SYS-10's `protocol` signal AGREEs.** Identical configuration of two
   decoders nobody established decode the same protocol is not identical
   observability, and an unclassified protocol is not an agreement.

`intended_function` is deliberately **not** a check: SYS-10 lists it as
name-derived and forbids deciding a duplicate on class names alone. It is
reported in the basis for the human, never used to reach REDUNDANT.

### Wiring — every consumer of the existing seven values

| Site | Change |
|---|---|
| `system_resource_registry.REMOVE_DUPLICATE` / `SYS17_DECISIONS` | New value, inserted in the document's own order (after PASSIVE_ONLY) |
| `DECISION_SEVERITY` | `PASSIVE_ONLY: 3 < REMOVE_DUPLICATE: 4`, remaining values shifted. **PASSIVE_ONLY outranks REMOVE_DUPLICATE deliberately**: in a 3+ member group one pair proving redundancy says nothing about a third member, and deleting an agent is the less reversible act, so the KEEP answer wins the entry-level fold and the redundant pair stays visible as its own SYS-17 row |
| `decide_reuse()` | The `MONITOR_ONLY_DUPLICATE` branch now consults the classifier; both outcomes carry the classifier's reason verbatim, so a PASSIVE_ONLY now says *why* it was kept |
| `decide_reuse()` return | New `duplicate_observability` (verdict + reason + basis; `None` for every other relationship class), `interchangeable_copies`, `retention_choice` |
| SYS-17 dedup matrix rows | The three new fields carried into each row's `detail`, so the mandated table shows why a duplicate was kept or called redundant without re-deriving it |
| `schemas/system_resource_registry.schema.json` | `reuse_decision` enum + a description stating the PASSIVE_ONLY/REMOVE_DUPLICATE distinction |
| `system_scheduling_plan.py` | **Real behavioural need, not cosmetic.** SYS-24's branch was `elif decision == srr.PASSIVE_ONLY: → SCHED_PASSIVE_NO_ARBITRATION`. A REMOVE_DUPLICATE entry would have fallen through to `SCHED_SINGLE_SHARED_ACCESS_POINT` and proposed a shared System sequencer/driver/queue for a resource **nobody drives**. New `PASSIVE_NO_ARBITRATION_DECISIONS = {PASSIVE_ONLY, REMOVE_DUPLICATE}` |
| `system_readiness.py:703`, `system_phase1_report.py:401`, `system_regression_plan.py`, `system_topology_analysis.py`, `system_command_plan.py` | **Verified no change needed** — each tests `!= KEEP_INDEPENDENT`, `== BLOCKED`, or iterates `SYS17_DECISIONS` generically, so REMOVE_DUPLICATE flows through correctly. `tools/verification_flow/reference_uvm_compatibility_gate.py`'s `reuse_decision=="REUSE"` is an unrelated field of a different gate |

## 3. Human-approval / arbitration boundaries — all intact

- **No arbitration added.** A REMOVE_DUPLICATE decision names BOTH
  interchangeable copies (`interchangeable_copies`) and explicitly refuses to
  pick one (`RETENTION_NOT_ARBITRATED`: the two were proven equivalent on every
  compared signal, so the choice carries no engineering content and belongs to
  the human). Asserted by test.
- **Active-driver ownership untouched.** `DRIVER_CONFLICT → BLOCKED` and SYS-12's
  stop override are byte-identical; REMOVE_DUPLICATE is reachable only from
  `MONITOR_ONLY_DUPLICATE`, i.e. two PASSIVE monitors, where no driver exists.
  A stopped/held resource still overrides to BLOCKED (MONITOR_ONLY_DUPLICATE is
  in `MERGING_RELATIONSHIPS`).
- **SYS-39/40 boundary untouched.** Every decision still carries
  `recommendation_only: True`; the reason text names removal as SYS-40.
  `artifacts_modified: False` and `PHASE_BOUNDARY` unchanged. Nothing generates,
  modifies or deletes any environment file. No `ControlPlane.approve`,
  `HumanApprovalRequiredError` or `ProductionWriteNotAuthorizedError` is
  referenced by any changed line.
- **No build / regression / LSF submission.** All tests are synthetic fixtures
  under `tmp_path`; nothing touched the real
  `subsystem_environment_registry.json` (legitimately empty in this repo).

## 4. Tests (5 new, all driving the real SYS-9..SYS-17 stack)

Fixtures differ ONLY in the evidence the classifier reads, so each assertion
proves that evidence is what moved the decision.

| Test | Proves |
|---|---|
| `test_two_identically_configured_monitors_are_remove_duplicate` | **Positive:** two PASSIVE monitors, both with a real 3-field captured config, identical hashes, protocol AGREE → REMOVE_DUPLICATE; basis values asserted from the real analysis; both copies named and retention NOT arbitrated |
| `test_a_monitor_with_a_config_field_the_other_lacks_stays_passive_only` | **The discriminating negative.** Asserts SYS-10's own `configuration` signal is AGREE here — so the pre-existing signal alone could NOT have separated this from the redundant case — while the whole-field hashes differ (3 fields vs 2) → PASSIVE_ONLY, nothing proposed for removal |
| `test_one_side_with_no_captured_config_cannot_prove_redundancy` | Half the evidence is not the evidence; reason names "side B" |
| `test_identical_config_on_an_unclassified_protocol_stays_passive_only` | The config half matched; the protocol half (UNKNOWN, not AGREE) withheld the decision |
| `test_a_redundant_monitor_pair_needs_no_shared_access_point` | Real `build_system_scheduling_plan()` over a real REMOVE_DUPLICATE entry lands at `SCHED_PASSIVE_NO_ARBITRATION`, `NO_ACCESS_POINT`, `arbitration_policy_required: False` |

Two existing tests strengthened: `test_two_passive_monitors_...` (the no-config
case) now additionally asserts the `duplicate_observability` reason that keeps
it PASSIVE_ONLY, and `test_keeping_a_monitor_outranks_removing_it_in_the_entry_level_fold`
pins the severity ordering. The drift guard
`test_sys17_decision_vocabulary_is_closed_and_verbatim` now holds the code and
the JSON-schema enum against the document's eight-value list.

## 5. Deferred / not done

Nothing from this gap's scope. Two adjacent things deliberately left alone:

- **`.dv-harness/dashboard.py`** — out of scope for this pass by instruction.
- **`gates.py` `JUDGMENT_FIELDS`** — not extended with `reuse_decision`; three
  concurrent passes were editing that file, and REMOVE_DUPLICATE is a planning
  recommendation, not a gate verdict.

## 6. Files changed

- `dv_harness/system_resource_registry.py`
- `dv_harness/schemas/system_resource_registry.schema.json`
- `dv_harness/system_scheduling_plan.py`
- `dv_harness_tests/test_system_resource_registry.py`
