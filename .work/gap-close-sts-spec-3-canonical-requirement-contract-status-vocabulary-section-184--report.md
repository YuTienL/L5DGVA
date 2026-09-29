# SPEC-3 -- Canonical Requirement Contract + status vocabulary (spec section 184)

**Result: DONE**

**Test summary:** `dv_harness_tests/test_requirement_contract.py` 96 passed;
regression over everything touched: `test_engine_gates_and_routing.py` +
`test_hard_gate_script_smoke.py` + `test_master_requirement_completeness_gate.py`
418 passed (11m02s), and `test_cli_cross_project.py` +
`test_cli_memory_commands.py` + `test_cli_question_queue.py` +
`test_harness_reliability.py` + `test_env_manifest.py` 107 passed.

## 1. Independent re-verification (before building)

- `grep -rn "Canonical Requirement Contract"` over the whole repo (`.py`/`.md`):
  **0 hits**.
- `grep -rln "requirement_contract\|RequirementContract"`: **1 hit**, and it is
  the workflow script that dispatched this task
  (`.work/workflow_scripts/spec_to_system_gap_close.js`) -- i.e. nothing in
  `dv_harness/`, `tools/`, `dv_harness_tests/` or `dv_harness/schemas/`.
- `grep -rln "CONTRADICTORY" --include=*.py`: 3 hits, none of them a requirement
  status vocabulary -- `connectivity.py`'s
  `AmbaClassificationStatus.AMBIGUOUS_CONTRADICTORY_EVIDENCE` (AMBA protocol
  classification) and `REQUEST_DIRECTION_CONTRADICTORY` (fabric signal
  direction), and `protocol_structural_completeness_gate.py`'s
  `CONTRADICTORY_SPEED_FLAG_DECLARATION` (USB speed flags).
- The closest existing mechanism, read in full:
  `tools/verification_flow/spec_to_vplan_requirement_quality_gate.py` was a
  14-line script checking FIVE fields (`spec_ref`, `feature`,
  `expected_behavior`, `verification_method`, `coverage_goal`) plus an
  ambiguity rule and an `UNSUPPORTED_BY_DUT` rule. It has no
  Protocol/Configuration/Precondition/Observability/Checker/Coverage
  Intent/Priority/Criticality field and no status vocabulary whatsoever.
- Spec section 184 read directly at
  `CLAUDE_DV_Agent_Harness_L5_SPEC_TO_SYSTEM_UVM_COMPLETE.md:6162-6202`.

**Gap confirmed real and total.**

Note on the field count: the task brief said "14 named fields" but then listed
fifteen, and section 184's own block lists fifteen lines (ID / Source / Feature /
Protocol / Configuration / Precondition / Stimulus / Expected Result /
Observability / Checker / Coverage Intent / Priority / Criticality / Confidence /
Status). All **fifteen** are implemented, and a test asserts both the exact tuple
and `len(...) == 15`.

## 2. What was built

### `dv_harness/requirement_contract.py` (new, 646 lines)
- `SCHEMA_VERSION`/`CONTRACT_SCHEMA_VERSION`, sibling `SCHEMA_PATH`, fail-closed
  `RequirementContractValidationError` -- `env_manifest.py`'s schema-versioning
  convention, including its `_validate_against()` jsonschema shape.
- `RequirementContract` dataclass with section 184's fifteen fields in the
  document's own order, plus carriers (`ambiguities`, `contradictions`,
  `support_status`, `design_evidence`, `notes`). `from_dict()` validates by
  default so an instance cannot exist over content that did not validate;
  `to_dict()` emits deterministic field order (no `sort_keys`), matching
  `env_manifest.py`'s diffability rule.
- `REQUIREMENT_STATUSES` = the five values verbatim, with `STATUS_DEFINITIONS`
  carried alongside.
- **Vocabulary reuse, not re-typing** (Methodology Consolidation Rule):
  `PRIORITY_VALUES` is imported from `memory.CORNER_CASE_RISK_TIERS`,
  `CONFIDENCE_VALUES` from `inference.CONFIDENCE_LEVELS` (+ `UNKNOWN`). A test
  asserts both identities so they cannot drift. `criticality`
  (BLOCKER/MAJOR/MINOR/UNKNOWN) is genuinely new -- this repo had no
  consequence-of-failure axis -- and is documented as a deliberately different
  axis from priority's scheduling one.
- `derive_status()` -- re-derives the status from the record's own CONTENT,
  worst-first: unresolved contradiction -> unresolved ambiguity -> untrusted
  confidence or nothing verifiable -> unresolved field -> COMPLETE.
- `is_resolved()` -- a field is UNRESOLVED when absent, empty, or a placeholder
  (`UNKNOWN`/`TBD`/`TBD.`/`N/A`/`na`/`?`/lowercase `none`). Uppercase `NONE` is
  RESOLVED, but only for `configuration`/`precondition`.
- `analyze_requirement_contract()` -- 12 finding codes, ERROR/WARNING/INFO
  severities.
- `analyze_requirement_contract_set()` -- adds `DUPLICATE_REQUIREMENT_ID` and a
  per-status rollup; skips records not in the contract shape.
- `downstream_consumable()` -- the decision the contract exists to make: only
  COMPLETE with zero ERROR findings may feed a generator.
- `execute_verb()` + `main()` -- the `power_intent`/`golden_scenario` convention;
  exit 0 clean / 1 ERROR / 2 NOT_AVAILABLE.

### `dv_harness/schemas/requirement_contract.schema.json` (new)
Draft 2020-12, `additionalProperties:false`, all fifteen fields required, the
five-value `status` enum, the P0..P3 / BLOCKER..UNKNOWN / HIGH..UNKNOWN enums, a
`provenance` `$def` requiring a real `document`, and `ambiguities` /
`contradictions` item shapes (a contradiction's `conflicting_sources` is where
the "at least two disagreeing sources" rule lives).

### `tools/verification_flow/spec_to_vplan_requirement_quality_gate.py` (EXTENDED)
- Layer 1: the original five-field / ambiguity / UNSUPPORTED_BY_DUT checks, with
  **exit codes 2/3/4/5 unchanged**, applied to records that do NOT declare
  `contract_schema_version`.
- Layer 2: records that DO declare it are schema-validated and analysed via
  `dv_harness.requirement_contract`, new exit 6
  `REQUIREMENT_CONTRACT_VIOLATION`.
- Contract records are validated by layer 2 **instead of** layer 1's five-field
  check, because the shapes rename the same content (`req_id`/
  `expected_behavior` vs `requirement_id`/`expected_result`); running layer 1
  over a contract record would fail it for fields the contract deliberately
  renamed. Records in the old shape are byte-identically unaffected.
- **Fail-closed on its own unavailability** (exit 7,
  `REQUIREMENT_CONTRACT_VALIDATOR_UNAVAILABLE`). Deliberately different from the
  opportunistic `SKIPPED_ANALYSIS_UNAVAILABLE` convention in the `system_level_*`
  gates: there the analysis is offered, here the record explicitly asked to be
  held to the richer contract, so skipping would turn a stricter declaration into
  a weaker gate.
- Same `DV_HARNESS_PACKAGE_ROOT` / `parents[2]` sys.path pattern the
  `system_level_*` gates already established.

### `dv_harness/cli.py`
New `dv-harness requirement-contract --requirements <f> [--json]
[--fail-on-error]`, one shared implementation with
`python -m dv_harness.requirement_contract`.

### `CLAUDE.md`
New section "Canonical Requirement Contract + Status Vocabulary (2026-09-06,
SPEC-3)" recording the mechanism, its arbitration boundary, and its stated
limits.

### `dv_harness_tests/test_requirement_contract.py` (new, 96 tests)
One clean synthetic requirement asserted COMPLETE and finding-free, then every
rule driven by MUTATING that same record one defect at a time:
- All **five status values** each derived from real content, each asserted
  self-consistent and correctly (non-)consumable
  (`test_every_one_of_the_five_status_values_is_reachable_and_self_consistent`).
- **Every one of the fifteen fields** deleted in turn and asserted (a) rejected
  by the schema and (b) named by the analysis -- two parametrized tests.
- Every text field asserted to downgrade COMPLETE->PARTIAL when set to a
  placeholder; nine placeholder spellings asserted.
- `STATUS_OVERCLAIMED`, `UNRESOLVED_BLOCKER_HIDDEN` (contradiction and ambiguity
  variants), the weaker-status WARNING, the ambiguity/contradiction/source/
  vocabulary rules, duplicate ids, the carried-over UNSUPPORTED_BY_DUT rule,
  input purity.
- **The gate driven as a REAL subprocess**: the four original exit codes
  preserved; the old shape unchanged; a clean contract record passing; a mixed
  document routing each record to its own layer; and the **headline case** --
  a record carrying all five old fields (so the pre-2026-09-06 gate would have
  PASSED it) is REJECTED for claiming COMPLETE with `checker: "TBD"`.
- The fail-closed exit-7 path driven with `DV_HARNESS_PACKAGE_ROOT` pointed at an
  empty directory and `PYTHONPATH` stripped.
- Both CLI entry points driven as real subprocesses with asserted exit codes.

## 3. Human-approval gates: unchanged

Nothing in this pass touches `HumanApprovalRequiredError`,
`ProductionWriteNotAuthorizedError`, `ControlPlane.approve`, or SYS-39/40's
stop-before-generating-real-system-artifacts boundary. No build, regression or
LSF submission was triggered; every test runs against synthetic in-memory records
and `tmp_path` files.

**Arbitration is DETECTION only, by construction.** A CONTRADICTORY requirement
stops at CONTRADICTORY: the contract requires it to name at least two conflicting
sources, `downstream_consumable()` refuses it, and nothing picks a winner.
`test_arbitration_is_never_performed_here` asserts the analysis output contains
no `winner`/`chosen`/`selected_source`/`arbitrated`/`auto_resolved` field.

## 4. Shared-file discipline

`git status` was checked before touching anything. `dv_harness/cli.py` was found
to have been concurrently modified by another close-pass (adding a
`config-variants` verb). Rather than a broad `git add`, my cli.py change was
staged hand-scoped: `git show HEAD:dv_harness/cli.py` -> apply only my two hunks
-> `git hash-object -w` -> `git update-index --cacheinfo`, leaving the other
pass's working-tree changes untouched and unstaged. Verified: the staged cli.py
diff is 34 insertions with **zero** `config-variants` lines.
`dv_harness/dashboard.py` was not touched. `.dv-harness/events.jsonl` was left
unstaged.

## 5. Deliberately NOT built (scoped down / deferred), and why

1. **`gates.py`'s `JUDGMENT_FIELDS` was NOT extended** with the contract's
   `status`/`confidence`. It would be the semantically right home for them (they
   are agent judgments), but that mechanism is the opt-in
   `require_dv_review_cosign` path which is OFF by default, and three concurrent
   close-passes were editing `gates.py` this session. Adding a no-op-by-default
   entry was not worth a four-way collision on that file. Recorded in CLAUDE.md.
2. **Nothing PRODUCES contract-shaped records yet.** No generator in this repo
   emits them, so the new gate layer is dormant until a project supplies them.
   This is deliberate and disclosed rather than papered over: minting fabricated
   contract records into this project's evidence to make the mechanism "have
   fired" is precisely what the existing registry-entry disclosure in CLAUDE.md
   refuses to do. The mechanism is proven to fire on real records via the real
   gate subprocess.
3. **Section 184's other responsibilities are NOT implemented**: spec-parser,
   requirement-normalizer, register-parser, feature/dependency extraction. This
   module reads a requirement RECORD; it does not extract requirements from prose
   and does not check a requirement against RTL, a register map, or a simulation.
   Those need a real spec-ingestion pipeline that is a separate, much larger
   effort.

## 6. Commits

- `275e3a6` feat(spec): canonical requirement contract + 5-value status
  vocabulary (section 184) -- the module, schema, extended gate, tests, CLAUDE.md
  section, and this report.
- `88b9e84` feat(spec): expose `dv-harness requirement-contract` verb -- the
  cli.py hunk, which was lost between staging and commit when the concurrent
  `config-variants` close-pass restored `dv_harness/cli.py` from HEAD. Detected
  by re-checking `git show HEAD:dv_harness/cli.py` after committing, re-applied
  with the same hand-scoped HEAD-blob technique, and verified: the committed
  cli.py carries my two hunks and **zero** `config-variants` lines, so the other
  pass's working-tree work was neither committed nor destroyed.

Final state re-verified after both commits:
`test_requirement_contract.py` 96 passed; working-tree `cli.py` parses and
carries both passes' changes.
