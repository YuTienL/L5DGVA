# SYS-33..SYS-38 gap close — system regression plan, KC update, version pinning, change impact, readiness, and the 22-item Phase-1 report

**Result: DONE.** Commit `a8c0f20`.

**Test summary:** 49 new tests in
`dv_harness_tests/test_system_regression_readiness_and_phase1_report.py` pass, and
the 532-test sibling suite (subsystem discovery / architecture+contract /
resource inventory / resource registry / command plan / scheduling plan /
topology analysis / failure triage / SoC composition wiring / environment mode
router / knowledge center / syoscb source audit) still passes unchanged.

---

## Scope re-check before building

The supplied audit was **stale on its framing and wrong on one number**, both
re-verified rather than assumed:

- It describes SYS-15/17/19-21/26/30 as "unbuilt", which was true when it was
  written. `git log` shows this same sequence has since landed `d87c3b8`
  (SYS-15..17), `099ca15` (SYS-18..22), `bd088d7` (SYS-23..27) and `ae6496d`
  (SYS-28..32). So SYS-38 had real artifacts to compose, and SYS-33/36 had real
  scenarios/resources/commands to join against. This step builds **on** them.
- **SYS-37 has TEN inputs, not nine.** The audit says nine. The requirement's own
  sentence (`…SystemLevel_AMBA4_SyoSil_CCE_Research.md:4459`) names subsystem
  readiness, shared-resource conflicts, command compatibility, scoreboard
  compatibility, address map, clock/reset, VIP dedup resolution, build
  integration, scenario availability, regression evidence. A derivation over nine
  would have silently dropped one. `SYS37_INPUTS` is held to ten by an
  import-time check and by a test quoting the sentence.

Everything else the audit found real was re-confirmed and **joined, not
reimplemented**.

---

## What changed

| File | Change |
|---|---|
| `dv_harness/system_regression_plan.py` | **new**, 1087 lines — SYS-33 regression plan + SYS-36 change-impact producer |
| `dv_harness/system_readiness.py` | **new**, 987 lines — SYS-35 pinning + SYS-37 readiness + SYS-34 record builder |
| `dv_harness/system_phase1_report.py` | **new**, 1010 lines — SYS-38's 22 sections + SYS-39's stop |
| `dv_harness/knowledge_center.py` | **extended**, +139 — SYS-34 typed accessor (third one, same pattern as SYS-3's and SYOSCB-3's) |
| `dv_harness/cli.py` | **extended**, +74 — `dv-harness system-phase1-report` |
| `dv_harness_tests/test_system_regression_readiness_and_phase1_report.py` | **new**, 1182 lines — 49 tests |

### SYS-33 — SYSTEM REGRESSION (was NEVER_BUILT)

Eight categories verbatim from the requirement's own sentence, all present in
`by_category` even when empty (an empty one carries its reason — a category
silently missing is indistinguishable from one with nothing in it, and only one
is a finding). Every entry cites the artifact row it came from and carries
`execution_status = PLANNED_NOT_EXECUTED`.

"Do not blindly concatenate" is a **check**: exclusions are recorded with the
producing layer's own verdict (SYS-22 `blocks_integration`, SYS-23
`DEDUPLICATION_CANDIDATE`, SYS-24 `NOT_SCHEDULABLE`, SYS-30's own
`composition_gate_note`), `concatenation_check` reports the universe beside the
count, and `assert_not_blind_concatenation()` raises only on the shape a
concatenation really has — everything in **and** nothing saying why.

Selection classes are `regression_tiers.CLASS_*`, reused rather than a fifth
vocabulary for the same idea.

### SYS-34 — KNOWLEDGE CENTER UPDATE (was WIRED as mechanism, DORMANT for this use)

Third typed accessor in `knowledge_center.py`, beside `SUBSYSTEM_*` and
`THIRD_PARTY_COMPONENT_*`: same broker, same `add`/`search` verbs, same
staleness/confirm/deprecate lifecycle. No parallel store, no broker change.

`record_system_composition()` **refuses** `PHASE_1_PLAN_AWAITING_USER_APPROVAL`.
SYS-34's first four words are "After successful integration"; this shard is read
across projects and users, and a plan published there would later read as *this
composition was built and passed*. `build_system_composition_record()` fills every
field from real artifacts and pins that phase — only a SYS-40 caller that really
integrated can re-stamp it.

### SYS-35 — SUBSYSTEM VERSION PINNING (was PARTIALLY_WIRED)

Per-subsystem `release_sha` pinning was already real and gate-enforced; none of it
is rebuilt. What could not exist is the **composition-level** snapshot, and the
reason is structural: `_persist_subsystem_registry_entry()` is
insert-or-replace-**by-name**, so a file whose every row is overwritten in place
cannot also record what composition X was built from.

`.dv-harness/soc-composer/system_composition_pins.json` sits **beside** it,
append-only, keyed by a `composition_id` derived from the pinned set itself —
re-pinning an unchanged set is idempotent; a moved sha mints a new snapshot
alongside the old rather than destroying it. An unpinned subsystem is **recorded**,
never omitted: a snapshot silently missing one would restore a different
composition than it claims.

### SYS-36 — CHANGE IMPACT (was PARTIALLY_WIRED, attestation-only)

`compute_subsystem_change_impact()` is the producer the gate had none of. It
reuses `change_impact.changed_files()` (the one `git diff` in this repo, with its
degrade-never-raise contract intact) once per subsystem, inside **that
subsystem's own tree**, against **that subsystem's own registered
`release_sha`** — resolving that sha in this repo would either fail or, worse,
succeed against unrelated history. `classify_risk()` supplies the per-path risk.

It cannot be an extension of `change_impact.py`: that function takes one repo
root, one base ref and a flat `requirements.csv`; SYS-36 is N subsystems, N base
refs, joined against the SYS-15 registry / SYS-21 IR / SYS-26 scoreboards /
SYS-30 scenarios.

`build_change_impact_gate_input()` emits exactly the `--impact` payload
`system_level_change_impact_gate.py` reads — computed, not attested.
`select_targeted_system_regression()` narrows only when **every** subsystem
produced a real diff, and always retains `MANDATORY_SIGNOFF` and scope-unknown
entries (expand, never shrink).

### SYS-37 — SYSTEM ENVIRONMENT READINESS (was PARTIALLY_WIRED)

Reuses SYS-4's four words (`subsystem_discovery.READINESS_CLASSES`) with the same
precedence one level down — BLOCKED outranks everything; all-UNKNOWN is UNKNOWN,
never PARTIAL; one unknown input keeps a composition out of READY. Per-**input**
status is a separate four-value vocabulary because *is this artifact on disk* and
*is this integration concern clean* are different questions: an address map that
exists and contains a conflict is neither PRESENT-and-fine nor ABSENT.

SYS-37's closing sentence is enforced by reading `srr.CONFLICT_DRIVER` — the one
place that concept has a name, already decided by SYS-11/12.

### SYS-38 / SYS-39 — the 22-item report and the stop (was NEVER_BUILT)

`build_system_phase1_report()` **computes nothing**. Every body is another
module's own renderer on that module's own document, so the report cannot hold a
second opinion about anything it reports. Three guards run on the **finished
text** — 22 headings once each in order, no `bind` statement (via
`connectivity.parse_bind_line()`), no emittable SV — because checking the section
tuple would only prove the tuple agrees with itself.

An unfillable section renders a `NOT SUPPLIED` note naming the call that fills
it, never disappears. SYS-39's stop is **data**, verified line-by-line, and
**unconditional**: a READY composition stops on the same terms as a BLOCKED one,
because the stop is about who decides, not how the analysis came out.

---

## Hard constraint honoured

No System-Level UVM source, no System command.txt, no System Virtual Sequencer,
no command routing/adapter, and nothing written into
`soc_environment_composer.cross_subsystem_scenarios()` /
`end_to_end_scoreboard()` / `system_coverage()` — all three still raise
`NotImplementedError`. Enforced, not promised:

- `assert_nothing_executed()` refuses a plan claiming a run, a job or a testlist;
- `render_system_phase1_report()` refuses a bind statement or compilable SV;
- a CLI test snapshots both subsystem environment trees byte-for-byte across a
  real subprocess run and asserts no `system_command.txt` / `soc_command.txt` /
  `system_scoreboard.sv` / `system_virtual_sequencer.sv` /
  `system_address_decoder.sv` appears anywhere;
- a library-level test asserts `produce_phase1_report()` leaves the project tree
  bit-identical (the pin file is a separate, explicit `--write-pin`).

Synthetic fixtures (fake registry entries, fake command.txt pairs, fake address
maps, real throwaway git repos) live only inside the test file.

---

## Why the tests have detection power

- **known-good** — one subsystem registered *and* PASS-evidenced beside one that
  is neither, so the exclusion is real and names its failing half.
- **command selection** — asserts `planned | excluded == the whole IR` and
  `planned ∩ blocked == ∅` against SYS-22's own verdicts, not a hardcoded list.
- **active-driver conflict** — the control is *isolated*. The imported topology
  fixture carries three **other** real conflicts (an address overlap, two
  clock/reset disagreements, three blocking command collisions), so a naive
  "clean stack is not BLOCKED" control would have passed for the wrong reason.
  The test asserts the VIP-dedup input and the active-driver record specifically.
- **READY reachability** — a separate test proves READY is reachable at all, then
  flips one input to CONCERN (→ PARTIAL) and one to BLOCKED (→ BLOCKED). A
  derivation that could never return its best value would be indistinguishable
  from a broken one.
- **SYS-36** — real `git init` + real post-release commit per subsystem tree, so
  the diff is a real `git diff`; beside a subsystem with no `release_sha` that
  must come back `NO_REGISTERED_RELEASE_SHA` and force the full plan.
- **the gate** — the produced payload is run through the **real**
  `system_level_change_impact_gate.py` subprocess (exit 0 / PASS), and a
  deliberately broken payload through the same script (exit 3 /
  `MISSING_IMPACTED_RERUN_SCENARIOS`). A gate that would pass anything is not
  evidence.
- **reuse** — a test greps all three new modules for a second
  `subprocess.run`, a second `"diff"`, or a second `int(..., 16)` and fails on
  any of them.

---

## New entry point

```
dv-harness --project-root <root> system-phase1-report --select PCIE --select USB [--write-pin] [--escalate] [--json]
```

Exit 0 only when the selection is admissible **and** SYS-37 derived READY;
otherwise 2. The exit code is not an approval signal in either direction —
SYS-39 stops for an explicit human decision whatever it returns.

---

## Disclosed residuals

1. **`--head-rev` is settable; the base is not.** SYS-36 always diffs from the
   registered `release_sha`. A pin the caller could move is not a pin.
2. **`system_level_change_impact_gate.py` is unchanged.** It is still
   attestation-only by construction — it validates whatever JSON it is handed.
   What changed is that a real producer now exists for that JSON. Wiring the gate
   to *require* this producer's provenance would be a hard-gate behaviour change,
   which is out of scope for an analysis step; the honest state is that the
   payload can now be derived and is tested against the real gate both ways.
3. **`build_integration` at Phase 1 is a question about inputs, not a build.** No
   System-Level filelist exists to compile because writing one is SYS-40; the
   input reports `system_filelist: NOT_WRITTEN_SYS40_REQUIRES_HUMAN_APPROVAL`.
4. **This repo's own registry is still legitimately empty.**
   `.dv-harness/soc-composer/subsystem_environment_registry.json` does not exist
   here — this harness has no multi-subsystem project of its own. Every mechanism
   is proven against real fixtures; none was made to "have fired" here by writing
   fabricated entries into this project's real audit trail.
