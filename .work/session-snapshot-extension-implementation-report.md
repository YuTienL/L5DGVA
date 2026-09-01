# Session-Snapshot Extension: seed/dut_version/tb_version + command.txt/FSDB/coverage

## Summary

The 2026-09-01 AI-mechanism architecture audit found `dv_harness/session_snapshot.py`'s
`save_session()`/`restore_session()` real and proven (2 saved sessions exist on disk:
`.dv-harness/sessions/2026-08-30_usb_gap_closing_progress/` and
`.dv-harness/sessions/_pre_restore_1788099898/`), but flagged several claimed snapshot
fields as absent by omission: `dut_version`, `tb_version`, simulation seed, command.txt
content, FSDB references, and coverage data. This change closes each gap with real,
wired code and tests — no fabricated evidence, no placeholder fields.

## What was built

**1. `seed` (JobState, `dv_harness/lsf_client.py`)**

A same-day prior audit ("memory-engine-schema-completion") had already found JobState
had no dedicated `seed`/`fsdb_path` field and worked around it with regex extraction
from `JobState.options` free text at memory-write time only (never persisted on the
job record itself). This change promotes both to first-class `JobState` fields:

- `JobState.seed: Optional[str]`, `JobState.fsdb_path: Optional[str]` (new dataclass
  fields, default `None`; `.dv-harness/lsf/job_state_schema.json` updated to match,
  since the module's own docstring promises the two stay in sync).
- Real writer: `dv-harness lsf-submit --seed/--fsdb-path` (`cli.py`) — job-submission
  time is exactly the point a caller naturally already knows the seed. When the flags
  are omitted, the CLI falls back to the existing `extract_seed_from_options()`/
  `extract_fsdb_path_from_options()` regex extraction against `--options` text (now
  renamed from `_extract_*` to public names since `cli.py` now calls them across the
  module boundary — a cross-cutting cleanup, not a behavior change).
- Second real writer: `register_external_job()` gained optional `seed=`/`fsdb_path=`
  kwargs, for a job submitted outside `bsub_submit()` (e.g. wrapping the generated
  environment's own `lsf_regress.sh`, which already assigns a real per-job `$SEED`).
- `_write_job_tier_memory_on_terminal_reconcile()` now prefers the first-class field,
  falling back to options-text extraction only for a JobState that never got the
  structural field populated (an older on-disk record, or a caller that passed neither).

**2. `dut_version` / `tb_version` (project-level, `HarnessState` in `dv_harness/models.py`)**

RULING: placed on `HarnessState` alongside `git_sha`/`server_sha` (same "same
regression batch must use the same source/build/config identity" CLAUDE.md rule,
naming the DUT/TB revision rather than this harness repo's own git SHA). Real writer:
`DVHarness._sync_dut_tb_version_from_blackboard()` (`engine.py`), a read-only derived
mirror of the blackboard `"verification_state"` topic's `results[]` — populated *only*
from VERIFY stage's real, gate-enforced `test_result_provenance_gate` evidence
(`tools/verification_flow/test_result_provenance_gate.py` REQUIRES non-empty
`rtl_revision`/`tb_revision` on every accepted result), so this is always
gate-validated evidence, mirroring the existing `state.project` /
`_sync_project_from_blackboard()` pattern exactly (including "never blank out a known
value with an unknown one"). `session_manifest.json` now surfaces both fields.

**Bug found and fixed while wiring this**: `DVHarness._protocol_router_evidence()` read
blackboard topic `"verify"`, which nothing in the engine ever writes (VERIFY's real
topic is `"verification_state"`, and its value is not nested one level deeper the way
the old code assumed). `failing_test_name` was silently always `None` regardless of
real VERIFY results — no existing test exercised this path end-to-end
(`test_protocol_router.py` only calls `resolve_protocol()` directly with a synthetic
evidence dict). Fixed to read the topic actually written, with the correct shape, and
added a regression test (`test_protocol_router_evidence_reads_the_topic_verify_actually_writes`).

**3. `SESSION_EXTRA_DIRS` / `SESSION_ARTIFACT_REFERENCE_DIRS` (`dv_harness/session_snapshot.py`)**

Two new, explicitly-named lists — kept separate from `SESSION_DIRS` because every
`SESSION_DIRS` entry resolves relative to `.dv-harness/`, while command.txt/FSDB/
coverage live directly under `project_root` (`generated/...`, `project_input/...`),
a structurally different root.

- **RULING 1 (command.txt/scenario content — copied wholesale):** the audit named two
  candidate locations, `generated/06_tests` and `project_input/08_command`. Only
  `generated/06_tests/command_catalog` is included — it is the harness's own
  per-run-*generated* scenario/command catalog, the same CURRENT-RUN tier as
  `plans`/`react`/`agents`. `project_input/08_command` is deliberately **excluded**:
  it is durable project *source* material (the raw command.txt handed over once at
  onboarding, analogous to `project_input/02_dut` RTL, which this module has never
  copied either) — copying it every save would not track "what changed this run" and
  would grow every snapshot for no run-state benefit. `save_session()`/
  `restore_session()` copy/restore this directory symmetrically, under
  `dest/"extra"/<relpath>` so it never collides with `.dv-harness`-rooted content.

- **RULING 2 (FSDB waveform / coverage — reference only, never copied):** these are
  exactly the large, often multi-GB binary artifact this module's own top-of-file
  design comment implies a lightweight CURRENT-RUN snapshot was never meant to carry.
  Instead, `save_session()` records a **reference** — relative path + size + streamed
  sha256 — for every file found under `generated/10_runtime/waveform` and
  `generated/11_coverage` (when they exist) into `session_manifest.json`'s new
  `artifact_references` field. A file larger than `ARTIFACT_REFERENCE_HASH_SIZE_LIMIT_BYTES`
  (200 MB) is listed by path+size only, with `hash_skipped_reason` stated honestly
  (never a fabricated digest) — hashing a many-GB dump on every save would defeat the
  point of a lightweight snapshot. `restore_session()` never touches these two
  directories (there is nothing to restore for a reference-only entry — restoring an
  old session must never delete/replace the live tree's current FSDB/coverage).

The module's top-of-file "CURRENT-RUN layer only" design comment is preserved and
extended in place, with both rulings recorded inline as code comments, not just in
this report.

## Rulings (verbatim, also in commit messages)

- RULING: `dut_version`/`tb_version` land on `HarnessState`, sourced from VERIFY's
  gate-validated `test_result_provenance_gate` evidence via a new
  `_sync_dut_tb_version_from_blackboard()`, mirroring the existing `state.project`
  reconciliation pattern — never a fabricated/derived value.
- RULING: `seed`/`fsdb_path` become first-class `JobState` fields, written explicitly
  at `lsf-submit` (or `register_external_job()`), with the existing options-text
  regex extraction demoted to an honest fallback for legacy/incomplete records.
- RULING 1 (session_snapshot): only `generated/06_tests/command_catalog` is a
  `SESSION_EXTRA_DIRS` entry (current-run generated content); `project_input/08_command`
  is durable source material and is deliberately excluded.
- RULING 2 (session_snapshot): FSDB/coverage are reference-only (path+size+sha256 in
  `session_manifest.json`), never copied — a lightweight snapshot must not become a
  slow, disk-doubling one on every save.

## Tests

New/updated tests, all passing:

- `dv_harness_tests/test_lsf_client.py`: `JobState.seed`/`fsdb_path` round-trip via
  `save_job_state`/`load_job_state`; `register_external_job()` seed/fsdb_path
  pass-through and default-None; first-class field takes precedence over options-text
  extraction in `_write_job_tier_memory_on_terminal_reconcile`, and the fallback still
  fires for a legacy options-only record; CLI-level `lsf-submit --seed/--fsdb-path`
  (explicit, options-fallback, and neither-given) exercised in-process via
  `cli.main()` with `bsub_submit` patched out.
- `dv_harness_tests/test_memory_tier_completion.py`: updated in place for the
  `extract_seed_from_options`/`extract_fsdb_path_from_options` rename (behavior
  unchanged, only the import/call names).
- `dv_harness_tests/test_engine_gates_and_routing.py`: `state.dut_version`/`tb_version`
  derived-view round trip through a real `_write_blackboard_from_evidence()` VERIFY
  write (plus a reload-from-disk check); "last result wins, never blanks a known
  value" case; the `_protocol_router_evidence()` bug-fix regression test.
- `dv_harness_tests/test_session_and_info.py`: `SESSION_EXTRA_DIRS` save+restore
  round trip for `generated/06_tests/command_catalog`; `project_input/08_command`
  confirmed excluded; missing-dir no-op case; `artifact_references` computed with
  real sha256 for both `fsdb`/`coverage` keys and confirmed the binary content is
  never duplicated into the snapshot; oversized-file hash-skip behavior; restore
  never touches the live FSDB directory.

Full existing suite (`dv_harness_tests`, ~1580 tests) run to confirm zero regressions
— see the accompanying structured result for the pass/fail count from this run.

## Concerns / residual gaps

- `generated/06_tests/command_catalog`, `generated/10_runtime/waveform`, and
  `generated/11_coverage` are all empty scaffolding in this repo instance (per
  `generated/NOTICE_SCAFFOLDING_ONLY.md`) — the new code paths are covered by tests
  that create real fixture files under a temp `project_root`, not by this repo's own
  live data, since none exists to exercise here.
- The generated environment's own `lsf_regress.sh` (shell, not Python) assigns a real
  per-pattern `$SEED` but has no Python-side call site today that forwards it into
  `register_external_job(seed=...)` — the kwarg exists and is tested, but nothing in
  this repo currently calls it with a real seed from that script. Wiring that
  end-to-end would mean either teaching `regression_reporter.py` to parse
  `lsf_regress.sh`'s own `$LOGDIR/lsf/<suite>_<seed>.jobs` state file, or having a
  future version of that shell script call back into `dv-harness lsf-submit`/a new
  registration hook directly — left as a clearly-scoped follow-up, not invented here.
- `ARTIFACT_REFERENCE_HASH_SIZE_LIMIT_BYTES` (200 MB) is a judgment call, not a value
  derived from any documented requirement; it is easy to change if a real deployment's
  FSDB/coverage files run larger and hashing time becomes a problem in practice.
