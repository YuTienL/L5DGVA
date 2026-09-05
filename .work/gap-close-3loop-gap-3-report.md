# Gap 3 -- Auto-generated Golden-Flow Readiness Matrix (§47) -- **DONE**

**Test summary:** `dv_harness_tests/test_golden_flow_readiness.py` 38 passed;
run together with the three capability-evolution suites (`test_capability_evolution_auto_discovery.py`,
`test_capability_evolution_controlled_experiment.py`, `test_capability_evolution_research_architect.py`)
**116 passed, 0 failed**; full `dv_harness_tests` suite re-run for regressions.

> Filename note: the requested report path `.work/gap-close-3loop-gap 3:-report.md`
> contains a `:`, which NTFS treats as an alternate-data-stream separator (the
> previous pass's `.work/gap-close-3loop-gap 2` is a 0-byte artifact of exactly
> that). This file is the real report at a sanitized path.

---

## What was built

### `dv_harness/golden_flow_readiness.py` (new, 1286 lines)

Section 47's twenty-row matrix -- `Golden Flow Stage | Status | Evidence | Gap |
Next-Best-Action` -- rendered from sources that were **already real**. Nothing in
the module re-derives a fact an existing reader supplies.

**Per-row fact sources (all pre-existing, all resolved through the import system
by `assert_fact_sources_resolvable()`):**

| Row | Real source(s) |
|---|---|
| Spec In | `dashboard._read_json_file` (state.json), `dashboard._uploaded_files`, `gates.effective_stage_gates` |
| Requirement Extraction | state.json REQUIREMENTS_TRACEABILITY + its real gate list |
| Verification IR | PROJECT_MODEL + `gates.extract_evidence_blocks` on its `project_model_topology_completeness_gate` block |
| Verification Contract | VERIFICATION_ARCHITECTURE + its 14 real gates |
| vPlan / Traceability | VPLAN + `env_manifest.default_manifest_path`/`load_env_manifest` -> `env_topology.testplan_correspondence` |
| Protocol/Topology Discovery | PROTOCOL_CAPABILITY + ARCH_DISCOVERY + `dashboard._protocol_registry` |
| VIP/UVM Generation | IMPLEMENT + `protocol_capability.STATUS_GENERIC_SKELETON_ONLY` over that registry |
| Single-Test Proof | BUILD **and** VERIFY |
| LSF Regression | REGRESSION + `regression_reporter.load_jobs` + `dashboard._lsf_summary` |
| Failure Triage | FAILURE_RECOVERY + `dashboard._failure_attribution` |
| Coverage Collection | `dashboard._read_coverage_state` |
| Coverage Hole Analysis | + `coverage_analysis.identify_holes` |
| Next-Best-Test | `coverage_analysis.classify_coverage_hole` |
| Coverage Closure Loop | COVERAGE_CLOSURE + `loop_contract.observe_all` |
| 100% Verification Closure | REQUIREMENT_CLOSURE + `dashboard._coverage_credit` + `dashboard._qualified_conclusion` |
| Signoff Evidence | `signoff_export.read_signoff_stage_status` |
| Dashboard | `dashboard.serve`, `dashboard_auth.session_file` |
| Claude CLI Integration | `config.load_config` + `adapters.cli.ClaudeCLIAdapter._resolve_command` |
| Obsidian CLI Integration | `memory_doctor.check_obsidian` |
| Five-Level Memory | `dashboard._read_memory_center_state`, `dashboard._locally_stored_memory_levels` |

**Reuse, not parallel mechanism:**
- Status vocabulary is `subsystem_discovery`'s READY/PARTIAL/BLOCKED/UNKNOWN --
  the same four words `system_readiness.py` already reused one level up. No fifth
  set of four strings.
- `STATUS_TO_READINESS` is asserted **total over `models.Status`** at import
  (`assert_status_mapping_total()`), the same anti-drift shape `loop_contract.py`
  uses for its own bridge. `ACCEPTED_RISK` floors to PARTIAL, never READY.
- The Next-Best-Action column is produced by the **real
  `inference.next_best_action()`** through its `gap_action_catalog` parameter --
  the same domain-neutral engine `capability_evolution.py` drives with
  `RESEARCH_GAP_ACTION_CATALOG`. A test spies on that call site to prove it.
- The table is rendered by `connectivity.render_markdown_table()`, this repo's
  only parameterized table renderer.
- `_assert_rows_match_section_47()` compares the declared labels against a
  transcription of the specification's own twenty, not against themselves; the
  negative control test proves that check fails when a row is dropped.

**Read-only, proven:**
- `state.json` via `dashboard._read_json_file()` rather than `StateStore.load()`
  (which mints one) -- the same reasoning `signoff_export.read_signoff_stage_status()`
  already records for itself.
- `config.load_config()` skipped for a project with no `config.json` (it
  materializes a default); the identical deep copy of `DEFAULT_CONFIG` that
  branch returns is used instead, minus the write.
- `loop_contract.observe_all()` and `dashboard._read_memory_center_state()` (both
  reach `StateStore`/`load_config`) are called only when the project is already
  initialized.
- `gates.effective_stage_gates()` falls back to `gates.STAGE_GATES` for an
  uninitialized tree, because its self-tuning overlay reader mkdirs.
- Test `test_producing_the_report_writes_nothing_for_a_project_that_never_ran`
  asserts `list(project.rglob("*")) == []` after a full run; a real-subprocess
  test asserts the same for `python -m dv_harness.golden_flow_readiness`.
- `test_producing_the_report_invokes_no_gate_subprocess` monkeypatches
  `gates.run_gate` to raise.

**Human-approval boundary: untouched.** The module has no write path to any
approval record, does not import or call `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()` or
`assert_no_production_write_authorized()`, and its own payload states
`"authorizes": "nothing"`. Exit 2 unless every row is READY -- a CI signal, not
an approval signal.

### `dv-harness golden-flow-readiness [--json]` (cli.py, +28 lines)

Follows the `loop-contract` convention exactly: one shared `execute()` behind
both the CLI subcommand and `python -m dv_harness.golden_flow_readiness`, so
there is no second handler over the same behaviour. A test drives both as real
subprocesses and asserts their row/status/gap output is identical.

### `dv_harness_tests/test_golden_flow_readiness.py` (new, 38 tests)

End-to-end against **real artifacts written by their real writers** -- a real
`storage.StateStore` state.json, real `.dv-harness/lsf/jobs/*.json`, a real
coverage `summary.json`, a real `MemoryStore.add()` record, a real protocol
capability registry, a real uploaded document -- and the CLI driven as a real
subprocess. Negative controls (what gives it detection power):

- an LSF job at `lsf_status: DONE` with no `dv_analysis_status` does **not** read
  as passing (LSF DONE != DV PASS);
- a DV-confirmed FAIL **blocks** the row;
- an INTAKE PASS with no document on disk does **not** close Spec In;
- a PROJECT_MODEL PASS with no IR evidence block does **not** close Verification IR;
- BUILD PASS alone does **not** close Single-Test Proof;
- a malformed coverage summary is BLOCKED (`BINS_HIT_EXCEEDS_TOTAL`), not "no
  coverage yet";
- an existing-but-invalid `env.manifest.json` surfaces as a gap, not as absence;
- dropping a row from `ROWS` fails the section-47 check;
- renaming a `fact_source` fails `assert_fact_sources_resolvable()`.

### `CLAUDE.md` (+85 lines)

One section documenting the mechanism, the reuse, the read-only guarantee (with
the CLI-wrapper `CLI_ACCESS` bootstrap disclosed precisely), and the residual.

---

## Real output against this repo (v50)

`python -m dv_harness.golden_flow_readiness --project-root .` -> exit 2,
**PARTIAL** (2 ready / 3 partial / 0 blocked / 15 unknown), with real data
flowing: `11 protocol(s) registered`, `8/11 protocol(s) with a protocol-specific
model` (gap names Ethernet, UCIe, eDP_DisplayPort), `verification_closure loop
state=CONVERGING`, `4/5 level(s) hold at least one record` (gap names
`organizational`). Verified via `git status` before/after that the run made no
repo-visible change.

---

## Deferred (honest scope statement)

- **§55 SELF-LEARNING READINESS MATRIX (22 rows)** is NOT built. It is a
  different row set over different sources (research cards, the 11-state
  capability-evolution machine, contradiction/supersede handling, revalidation,
  rollback/decision history), and several of those rows have no single existing
  reader today. Producing a half-sourced version would be exactly the
  fabrication this module exists to prevent. §47 -- the "Golden-Flow Readiness
  Matrix" this gap names -- is complete.
- **§49 dashboard exposure** is not wired. The task specified a CLI subcommand,
  and `dashboard.py` was under concurrent modification by the GUI gap-close
  workflow; adding an endpoint there would have collided. The module is a clean
  drop-in for a future `GET /api/golden-flow-readiness`.
- **Not engine-fired.** No `run_stage()`/`advance()` call site invokes it and no
  graph node declares it -- a REACHED capability, not a WIRED one, stated as
  such in CLAUDE.md.

---

## Concurrency handling

`dv_harness/cli.py` and `CLAUDE.md` both carried other passes' in-flight edits
(and the index changed mid-session -- commit `996c5cc` landed while this work was
in progress, and the `doc-extract` pass's staged hunks returned to the worktree).
Both files were staged with the hand-scoped patch technique:
`git diff > patch` -> trim to my hunks only (byte-exact write; Python's
`write_text` CRLF translation corrupts a patch on Windows) ->
`git apply --cached --check --recount` -> `git apply --cached --recount`.
Verified afterwards that the other passes' hunks remain unstaged in the worktree
(`CLAUDE.md +110`, `cli.py +44` still unstaged) and that only my two cli.py hunks
and my one CLAUDE.md hunk are in the commit.
