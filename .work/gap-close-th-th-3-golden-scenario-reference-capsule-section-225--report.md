# TH-3 — Golden Scenario / Reference Capsule (spec section 225)

**Status: DONE**
**Tests: `dv_harness_tests/test_golden_scenario.py` 21 passed; neighbouring suites
(`test_evidence_db.py`, `test_evidence_db_wiring.py`, `test_resource_cost_autonomy.py`,
`test_cli_preflight.py`) 71 passed.**

## 1. Gap re-verified independently before building

- `grep -rln "golden_scenario\|GoldenScenario\|golden scenario\|reference capsule\|ReferenceCapsule"`
  over `--include=*.py --include=*.md --include=*.json` across `v50/` returned **nothing**.
  Confirmed NEVER_BUILT.
- Confirmed DISTINCT from `dv_harness/golden_flow_readiness.py` — read its module docstring: it is
  section 47's GOLDEN FLOW READINESS MATRIX over the harness's own twenty workflow STAGES
  ("is this stage connected with evidence right now"). No per-test record, no recorded SHA, no
  staleness concept.
- Confirmed DISTINCT from `system_regression_plan.CAT_KNOWN_GOOD_SUBSYSTEM_TESTS` — read
  `system_regression_plan.py:95,250-290`: SYS-33's per-SUBSYSTEM regression-plan category, derived
  fresh from the subsystem registry's `qualification_state` + SYS-4 readiness factors on every call.
  Nothing is persisted, and it never asks whether the RTL moved since a PASS.
- Spec text re-read at
  `CLAUDE_L5_SPEC_TO_SYSTEM_UVM_TARGETED_HARDENING.md:7496-7532` (capsule field list + the
  "Golden does not mean permanent" staleness rule).

## 2. What was built

### `dv_harness/golden_scenario.py` (new)

`GoldenScenario` dataclass carrying section 225's capsule fields one-for-one (capsule_id,
project/subsystem, protocol, requirements, verified_sha = the section's "DUT/TB SHA", vip_versions,
configuration, command_txt_inputs, test/sequence/seed, expected_result, evidence_id,
known_limitations, watched_paths). `freshness` is deliberately **not** a stored field.

- `record_golden_scenario(store, capsule)` — validates against the REAL evidence store and refuses,
  in order: a malformed capsule (`CapsuleValidationError`), an `evidence_id` that is not an existing
  `normalized_evidence` row (`EvidenceNotFoundError`), a row whose verdict is not a real PASS
  (`EvidenceNotPassingError`), a row whose `pattern` disagrees with the capsule's `test_name`
  (`EvidenceMismatchError`). `job_id`/`protocol` are filled from that row; `verified_sha` from the
  real `jobs.git_sha` of the job that evidence belongs to.
- `evaluate_freshness(root, capsule, head=..., current_vip_versions=..., diff=...)` — FRESH / STALE /
  UNKNOWN derived from **real git history** via the existing `change_impact.changed_files()` (a real
  `git diff --name-only <verified_sha>..HEAD`) and the existing `change_impact.classify_risk()`
  HIGH/MEDIUM/LOW path model. HIGH (design RTL) or MEDIUM (testbench/sequence/command.txt/config)
  inside `watched_paths` ⇒ STALE, naming each triggering file and its risk. LOW (docs,
  `.dv-harness`/`.claude` bookkeeping) ⇒ not stale. A recorded VIP/tool version that no longer
  matches a caller-supplied current one ⇒ STALE with no git change at all.
- `evaluate_store_freshness()` — whole-store report whose `status` is the WORST outcome present.
- `execute_verb()` + `main()` — shared by `dv-harness golden-scenario record|list|status` and
  `python -m dv_harness.golden_scenario` (the same one-implementation convention `power-intent`
  uses). Exit 0 recorded / all FRESH, 1 at least one STALE, 2 UNKNOWN or nothing recorded.

### `dv_harness/evidence_db.py` (extended, not duplicated)

One new `golden_scenarios` table in `_SCHEMA_STATEMENTS`, alongside `jobs`/`normalized_evidence`,
plus `insert_golden_scenario()` (idempotent upsert on `capsule_id`, the same natural-key convention
every other table there uses), `get_golden_scenario()`, `list_golden_scenarios()`. List/dict fields
are stored as JSON text, the same convention `insert_job_memory_record()` already uses. A read-only
connection against an `evidence.duckdb` predating this table returns `[]` (checked via
`duckdb_tables()`) rather than raising `CatalogException` — found by running the new CLI against
this repo's own real evidence DB.

### `dv_harness/cli.py` (one parser block + one dispatch branch)

`dv-harness golden-scenario record|list|status [--json-file|--capsule-id|--head|--db|--vip-version|--json]`.

### `CLAUDE.md`

New dated section "Golden Scenario / Reference Capsule (2026-09-06)", stating what it is, what it
reuses, and the five disclosed bounds below.

## 3. Governance / safety

- **No existing human-approval gate touched.** Nothing was weakened, and this mechanism adds no
  gate: there is deliberately no stage gate, because a gate that passed on a capsule nobody re-ran
  would be worse than none. FRESH is an input to a human's reuse decision.
- **Nothing runs, builds, submits or approves.** No VCS invocation, no LSF submission, no
  regression, no state/approval write. Only read-only `git` (through `change_impact._git`'s
  existing degrade-never-raise wrapper) and the evidence DuckDB.
- All testing was against synthetic fixtures: throwaway `tmp_path` git repositories and a synthetic
  sim.log written in this project's own documented FINAL CHECK epilogue format.

## 4. Deliberately bounded / deferred (stated, not implied closed)

1. "We could not check" is **UNKNOWN, never FRESH** — no git, an unresolvable recorded SHA, a
   failed diff, or no recorded SHA at all each report UNKNOWN with the real reason.
2. Empty `watched_paths` widens scope to the WHOLE repo (`WHOLE_REPO_NO_WATCHED_PATHS_DECLARED`),
   never narrows it to nothing. The failure mode is "calls a still-good capsule stale", never the
   reverse.
3. **Nothing auto-mints capsules** from passing runs. "Which passes are worth keeping as golden" is
   a judgment this module does not make; recording is a deliberate `record` call.
4. Staleness is derived from **path risk**, not from semantic RTL analysis — an RTL commit that
   provably cannot affect the capsule still marks it STALE. Narrowing that would require
   module-level impact analysis this module does not attempt (and would risk the wrong direction).
5. "spec/tool change" from section 225's staleness sentence is covered only for the VIP/tool
   versions a caller reports (`--vip-version TOOL=VERSION`); this module never guesses a tool
   version, and a tool the caller does not report on is simply not evaluated.

## 5. Test evidence

`dv_harness_tests/test_golden_scenario.py` — 21 tests, all against real machinery (a real throwaway
git repo with real commits, a real DuckDB `EvidenceStore`, a real `vip_distill.distill_sim_log()`
envelope, a real `lsf_client.JobState` row):

- `test_rtl_change_makes_capsule_stale` — the section 225 round trip: record against a real PASS →
  FRESH → make a REAL RTL commit → the SAME capsule is STALE naming
  `rtl/usb3_link/usb3_link_ctrl.v` at HIGH risk, with the stored row untouched.
- Refusals proven: missing evidence, a real FAILED sim.log (verdict read from the real distiller,
  not hand-set), evidence for a different test, a non-PASS `expected_result`, an unknown JSON field.
- `test_documentation_change_does_not_stale_a_capsule`, `test_vip_config_change_...`,
  `test_change_outside_watched_paths_...` (scoped FRESH vs. unscoped STALE on the same commit),
  `test_vip_version_drift_stales_a_capsule_with_no_git_change`.
- UNKNOWN branches: unresolvable SHA, outside a git repo, no recorded SHA; plus
  "version drift still stales an unevaluatable capsule".
- `test_re_recording_the_same_capsule_updates_one_row`, `test_store_report_takes_the_worst_outcome`,
  `test_read_only_store_predating_the_table_reports_no_capsules`.
- Both CLI entry points driven as REAL subprocesses with asserted exit codes (record 0, status 0
  FRESH, status 1 STALE after a real RTL commit, status 2 with no evidence DB).

Command run: `python -m pytest dv_harness_tests/test_golden_scenario.py -q -p no:randomly`
→ **21 passed in 515s**.
Neighbouring: `python -m pytest dv_harness_tests/test_evidence_db.py
dv_harness_tests/test_evidence_db_wiring.py dv_harness_tests/test_resource_cost_autonomy.py
dv_harness_tests/test_cli_preflight.py -q -p no:randomly` → **71 passed in 521s**.
