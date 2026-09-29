# SYOSCB-1 / SYOSCB-3 gap close: real read-only SyoSil source auditor + KC registration-payload builder

**Status: DONE.**

Scope: SYOSCB-1 (REQUIRED SOURCE DIRECTORY AUDIT) and SYOSCB-3 (KNOWLEDGE
CENTER REGISTRATION) only. Audit/planning machinery, per the SYOSCB-33 gate.
Nothing was copied out of `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`; no SystemVerilog
was written anywhere; no VCS/UVM build was invoked.

---

## What the prior audit found, and what this pass did about it

| Item | Prior verdict | Action |
|---|---|---|
| SYOSCB-1 | source inspectable, but the audit existed only as hand-typed prose | **Built** `dv_harness/syoscb_source_audit.py` -- the same sixteen checklist items answered by real code, reproducibly |
| SYOSCB-3 | PARTIALLY_WIRED -- `knowledge_center.py`'s `SUBSYSTEM_*` pattern confirmed as the template, no component shape existed | **Built** `THIRD_PARTY_COMPONENT_*` in `knowledge_center.py` + a payload builder, deliberately not published |
| SYOSCB-2 | PARTIALLY_WIRED -- correctly not vendored | **Enforced**: `assert_not_vendored()` now makes "still not vendored" a checked fact, run against the live repo in a test |
| SYOSCB-4 | NOT_AVAILABLE (no fork exists to evaluate) | unchanged; still a Phase-2-time decision, nothing built |

---

## Files changed

### NEW `dv_harness/syoscb_source_audit.py` (~740 lines)

Read-only auditor for an `uvm_syoscb` source tree, plus the SYOSCB-3
registration payload built from it.

- `audit_syoscb_source(root)` -> `SyoscbSourceAudit`: version (from the first
  non-comment line of `VERSION.txt`, so the 18-line Apache header is not
  reported as a version number), SPDX license + copyright with `file:line`
  citations, the package compile unit and its `` `include `` order **in source
  order** (in this library the include sequence *is* the compile order --
  only `pk_syoscb.sv` is fed to the compiler), the class inventory with roles,
  the compare-algorithm mapping, macros, producer APIs, analysis ports,
  tests/examples/scripts/docs, upstream known limitations, and the UVM
  dependency.
- `audit_checklist()` answers **all sixteen** SYOSCB-1 items FOUND/NOT_FOUND
  with evidence; `unanswered_audit_items()` names the gaps so a NOT_FOUND is a
  visible finding rather than an empty cell.
- `compare_class_for_ordering()` bridges `connectivity.SCOREBOARD_PLAN_FIELDS`'
  existing `ordering` field to a real upstream class -- a missing ordering
  returns `REQUIRED_HUMAN_INPUT` with a reason instead of silently
  substituting another algorithm.
- `assert_source_unmodified()` / `assert_not_vendored()` / `assert_no_emittable_sv()`.
- `python -m dv_harness.syoscb_source_audit <root> [--json] [--registration-payload]
  [--l5-destination P] [--assert-not-vendored REPO]`.

**Reuse, not reimplementation** (the audit's own instruction, and SYOSCB-31's):
`vip_symbol_index.index_source_text()` is the only SV scanner (declarations and
locations only, never a method body -- `assert_no_bodies_retained()` is run on
the result); `connectivity.BindTier` is the only confidence vocabulary;
`connectivity.REQUIRED_HUMAN_INPUT` the only unknown sentinel;
`connectivity.render_markdown_table()` renders every table;
`amba_scoreboard_env.InspectedFile` is the read-only-proof record, imported
rather than re-declared. No new agent, no new store, no new confidence scale.

Role classification has three descending routes: a UVM base class that settles
the role (T2), an `extends` edge to an already-classified in-tree class (T2 --
this is what makes `cl_syoscb_queue_std` a queue on structure), and a class-NAME
token (T3, never auto-accepted). Anything else is `UNCLASSIFIED` at T4.

### MODIFIED `dv_harness/knowledge_center.py` (+94 lines, two pure-insertion hunks)

`THIRD_PARTY_COMPONENT_CATEGORY` / `_KIND` / `_FIELDS`,
`normalize_component_record()`, and `KnowledgeCenterClient.component_record()` /
`record_component()` -- the `SUBSYSTEM_*` pattern applied a second time over the
**same** `add`/`search` verbs, same broker, same shard lifecycle. Separate
category because a vendored library has no `COMMAND_TXT`/`REGRESSION_STATUS`
and searching one shard for the other would return neither. This is SYOSCB-3's
"Do not create a parallel knowledge store" honored by construction.

### NEW `dv_harness_tests/test_syoscb_source_audit.py` (43 tests)

---

## Real evidence produced by the new code (not hand-typed)

`python -m dv_harness.syoscb_source_audit D:/DV/Scoreboard/uvm_syoscb-1.0.2.4
--registration-payload --assert-not-vendored .`

- VERSION `1.0.2.4` (`VERSION.txt:19`), LICENSE `Apache-2.0` (`LICENSE.txt`),
  COPYRIGHT `Copyright (c) 2014 SyoSil ApS` (`NOTICE.txt:13`), 234 files audited,
  fingerprint `04e77b5f7ba6679f383ad801f7a08db1910441cd36bf46e0bc7794c9eee498d8`.
- All sixteen checklist items FOUND; `UNANSWERED ITEMS: (none)`.
- 15-entry compile order `src/pk_syoscb.sv:406..420`, `cl_syoscb_cfg_pl.svh`
  first, `cl_syoscb.svh` last; UVM 1.2 from `Makefile:29`.
- Ordering map: `IN_ORDER -> cl_syoscb_compare_io` (`src/cl_syoscb_compare_io.svh:20`),
  `IN_ORDER_PER_PRODUCER -> cl_syoscb_compare_iop` (`:20`),
  `OUT_OF_ORDER -> cl_syoscb_compare_ooo` (`:20`).
- 14 producer-API declarations cited to `file:line`; 5 upstream known limitations.
- Registration payload built with `BUILD_STATUS=NOT_BUILT_PHASE_2_APPROVAL_REQUIRED`
  and exactly one blocker: `L5_DESTINATION` (a SYOSCB-2 decision that happens
  after the SYOSCB-33 gate -- writing a plausible path there today would publish
  a location nothing is at). **Nothing was published.**
- `--assert-not-vendored .` passed: the repository contains no upstream file by
  name or by content digest.

---

## Tests -- including the missing-evidence half

Two synthetic fixture trees written by the test itself (never copied from
anywhere): a complete one, and a **degraded** one with no `VERSION.txt`, no
`LICENSE`/`NOTICE`, no `RELEASE_NOTES`, and no out-of-order compare class.

Honest-failure coverage specifically:
- `test_degraded_tree_reports_required_human_input_never_a_guess`
- `test_degraded_tree_names_exactly_which_checklist_items_are_unanswered`
  (exactly `{license_copyright_provenance, version_metadata}` -- everything the
  tree *does* answer still answers; a degraded tree must not collapse into a
  blanket "nothing found")
- `test_a_missing_ordering_is_reported_not_substituted`
- `test_registration_blockers_name_every_gap_on_a_degraded_tree`
- `test_missing_root_raises_rather_than_reporting_an_empty_library`
- `test_assert_source_unmodified_passes_then_catches_a_real_change` / `..._a_disappearance`
- `test_assert_not_vendored_catches_a_RENAMED_copy_by_content_digest` (the name
  check alone is evadable; this is why both detectors exist)
- `test_assert_no_emittable_sv_actually_fires_on_a_class_declaration`
- `test_no_method_body_text_is_retained` (the fixture's method bodies contain
  `$sformatf`, a message string and an `exist_queue` call, so the check has
  detection power; the one documented exception is macro IDENTIFIER collection)
- `test_building_the_payload_performs_no_transport` (`_remote_exec_module` is
  monkeypatched to raise)

Plus 7 tests against the REAL tree, skipped if it is absent -- version, license,
class inventory, 15-entry compile order, all three orderings, five known
limitations, the live-repo not-vendored assertion, and a subprocess CLI run that
compares every upstream file's mtime before and after to prove nothing was written.

**Test summary: 43 passed in `dv_harness_tests/test_syoscb_source_audit.py`
(9 of them against the real `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`, confirmed
executed, not skipped); 238 passed across the related suites
(test_knowledge_center, test_amba_port_registry, test_amba_fabric_discovery,
test_amba_fabric_generator, test_knowledge_layer_git_and_duckdb,
test_amba_vip_bind_plan, test_syoscb_source_audit).**

---

## Hard constraints, all honored

- Nothing copied/vendored from `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4` -- and this
  is now an assertion run against the live repository, not a promise.
- No SystemVerilog written; `assert_no_emittable_sv()` runs on the module's own
  rendered report before it is returned.
- No VCS/UVM build invoked, no live Knowledge Center write.
- No new agent added (SYOSCB-32); no `.claude/agents/` file touched.
- Shared-file discipline: `knowledge_center.py` was unmodified in the working
  tree before this pass (`git status` checked first); its diff is two
  pure-insertion hunks, both this change's.
