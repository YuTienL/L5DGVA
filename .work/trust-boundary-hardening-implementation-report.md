# Implementation Report: Self-Attestation Trust-Boundary Hardening

Implements `.work/trust-boundary-hardening-design-report.md` in full (all
items in its scope_boundary "IN SCOPE" list). Closes the gap where three
STAGE_GATES gates trusted self-reported JSON with nothing independently
recomputed behind it -- most concretely `signoff_bundle_completeness_gate.py`'s
`bundle_hash` field, which had zero real producer anywhere in the codebase
before this change.

## What was built

**1. `tools/verification_flow/_remote_transcript.py` (new shared helper).**
Factors the `REMOTE_HOST=`/`EXIT_CODE=`/`STATUS=` marker regexes and
parse-and-require logic out of `remote_execution_provenance_gate.py` into a
plain importable module (`TranscriptError`, `read_transcript`,
`parse_markers`, `read_and_parse_transcript`). `remote_execution_provenance_gate.py`
was refactored to call it -- its FAIL/PASS JSON shapes and exit codes are
byte-identical to before, confirmed by its own pre-existing test file
(`dv_harness_tests/test_remote_execution_provenance_gate.py`, 4/4 passing
unchanged). `server_sync_identity_gate.py`'s new SOURCE_ID mode reuses the
same helper against real md5sum transcripts rather than re-deriving the
regexes a second time.

**2. `dv_harness/signoff_export.py`: real `compute_bundle_hash()`.**
New function, modeled on `tools/remote/source_identity.py`'s
`aggregate_source_id` (sort `"{artifact}:{present}:{bundled_path}"` lines,
newline-join, sha256 hex digest). `collect_signoff_bundle()` now calls it for
real and writes the result into both its return dict (`bundle_hash` key,
purely additive) and `manifest.json`'s own on-disk content. Unit tests in
`dv_harness_tests/test_signoff_bundle_hash.py` mirror
`test_source_identity.py`'s style (order-independence, content-sensitivity,
real hex-digest shape, stable empty-input case).

**3. `signoff_bundle_completeness_gate.py`: real recomputation.**
Adds a required `bundle_dir` evidence field (a real
`collect_signoff_bundle()` `out_dir`). The gate reads the real
`bundle_dir/manifest.json` off disk, recomputes `compute_bundle_hash()` over
the real manifest list itself (importing `dv_harness.signoff_export` via the
existing `_ROOT = parents[2]; sys.path.insert` convention used elsewhere in
this directory), and FAILs with `BUNDLE_HASH_MISMATCH` unless the agent's
claimed `bundle_hash` equals that real recomputed value exactly. Also
requires the real manifest to carry a `self_audit_result` entry with
`present: true` -- the one artifact `collect_signoff_bundle()` always
generates fresh in-process, a tripwire that `bundle_dir` is real
signoff-export output and not a hand-crafted directory. The pre-existing
9-class evidence-completeness check and `final_verdict == PASS` check are
unchanged in behavior (same reasons/exit codes on the same inputs). New
tests in `dv_harness_tests/test_signoff_bundle_completeness_gate.py` cover:
the three pre-existing FAIL paths still firing identically, every new FAIL
branch (missing `bundle_dir`, manifest not found, malformed manifest, wrong
manifest shape, missing `self_audit_result`, hash mismatch), and two
full-real-path tests that call the actual `collect_signoff_bundle()` and
drive the gate script end-to-end to a genuine PASS and a genuine detected
tamper.

**4. `server_sync_identity_gate.py`: new SOURCE_ID mode.**
Dispatches on a new `identity_method` evidence field: absent or `"git_sha"`
runs the ORIGINAL code path byte-for-byte unchanged (confirmed by direct
tests and by the pre-existing `test_server_sync_requires_head_and_submodule_sha_identity`
engine-level test, unmodified and still passing). `"source_id"` requires two
real file paths, `local_md5sum_transcript_path` (existence-checked only) and
`remote_md5sum_transcript_path` (existence-checked AND required to carry the
real `remote_exec.py` marker shape via the shared `_remote_transcript.py`
helper, with `EXIT_CODE=0` required). Both are parsed via the real, already-
tested `tools/remote/source_identity.py` (`parse_md5sum_output`,
`compute_source_identity`), imported via the exact `sys.path` convention
`dv_harness_tests/test_source_identity.py` already establishes. The PASS/FAIL
verdict is driven only by the real `result["match"]`; an optional
self-reported `match`/`source_id` is cross-checked as defense-in-depth only
(`SOURCE_ID_CLAIM_MISMATCH` flag), never allowed to override the real
recomputation in either direction -- covered by
`test_source_id_mode_pass_decided_by_recomputation_not_self_reported_claim`
and its FAIL-direction mirror. Twelve new tests in
`dv_harness_tests/test_server_sync_identity_gate.py` cover both modes: PASS,
content mismatch, missing/malformed/nonzero-exit transcripts, empty
manifests, and the claim-vs-recomputation precedence tests.

**5. `dv_harness/prompts.py`: SERVER_SYNC and SIGNOFF stage instructions.**
`STAGE_INSTRUCTIONS[Stage.SERVER_SYNC.value]` now documents both the
existing `git_sha` evidence shape (with the now-optional `identity_method`
field) and the new `source_id` shape (the two real transcript-path fields,
what the gate actually checks, and the known PC-side residual limitation).
`STAGE_INSTRUCTIONS[Stage.SIGNOFF.value]` now documents the required
`bundle_dir` field and that `bundle_hash` must equal a real recomputation,
not an arbitrary string. `STAGE_DE_EXPLAINER` (the separate plain-language
explainer channel) was intentionally left untouched -- it is provably
side-channel-only per `test_de_explainer_is_additive_and_does_not_change_agent_prompt`,
and the design only asked for the actual stage-instruction evidence text
agents act on.

`run_identity_consistency_gate.py` was left untouched, per the design's
explicit ruling (no real per-repo mechanism exists to independently
recompute `canonical_build_hash`; the natural fix needs a persistence point
that doesn't exist yet).

## Rulings made

- **RULING (manifest.json shape):** promoted `manifest.json`'s on-disk
  content from a bare list to `{"manifest": [...], "bundle_hash": "..."}` so
  `bundle_hash` has a real, independently-re-readable location for the gate
  to recompute against. This is the one place existing behavior visibly
  changed (one pre-existing assertion in `test_signoff_export.py` was
  updated accordingly); no other code in the repo depends on `manifest.json`'s
  exact shape (checked via repo-wide grep -- `dashboard.py`/`cli.py` only
  check existence or forward the whole `collect_signoff_bundle()` return
  dict verbatim).
- **RULING (evidence-class-to-artifact mapping):** left unmapped, exactly as
  the design specifies -- no real mapping from the 9 self-attested evidence
  classes to `collect_signoff_bundle()`'s 10 real candidate artifacts exists
  anywhere in this codebase; inventing one would be exactly the kind of
  plausible-but-unverified content CLAUDE.md's Evidence Truth Rule warns
  against.
- **RULING (gate re-invocation):** the gate reads the already-produced
  `manifest.json` rather than re-invoking `collect_signoff_bundle()` fresh
  inside the gate process, per the design's explicit call -- re-invocation
  would re-run real file-copy I/O plus a fresh `self_audit.run_self_audit()`
  inside `run_gate()`'s 30s subprocess timeout. Documented in the gate's
  module docstring as a hardening follow-up, not v1.
- **RULING (PC-side md5sum transcript authenticity):** `local_md5sum_transcript_path`
  is checked only for real-file existence, exactly as `remote_execution_provenance_gate.py`
  already accepts for its own `transcript_path` -- no PowerShell/WSL/certutil
  transport-marker convention exists anywhere in this project to verify
  local-side capture authenticity, and inventing one here (untested, no real
  sample) would violate the Evidence Truth Rule. Documented in the gate's
  module docstring as a known, accepted residual limitation.
- **RULING (unrecognized `identity_method`):** added a defensive
  `UNKNOWN_IDENTITY_METHOD` FAIL branch for any value other than `"git_sha"`/
  `"source_id"` -- not explicitly specified by the design, but consistent
  with "never silently downgrade" and cheap to add; documented in-code.
- **RULING (`run_identity_consistency_gate.py`):** left completely
  unextended, per the design's explicit ruling under "Open questions" --
  documented again here as instructed.

## Test results

- New/modified test files run in isolation: `test_remote_transcript_helper.py`
  (7), `test_server_sync_identity_gate.py` (12), `test_signoff_bundle_completeness_gate.py`
  (12), `test_signoff_bundle_hash.py` (4), `test_signoff_export.py` (11, one
  updated), `test_remote_execution_provenance_gate.py` (4, unchanged) --
  56/56 passed.
- Full existing suite, `python -m pytest dv_harness_tests/ -q` (1412 tests,
  17m15s): **1411 passed, 1 failed.** The one failure,
  `test_graph_parallel_dispatch.py::test_engine_dispatches_all_three_branches_concurrently_and_joins`,
  is a pre-existing wall-clock-timing assertion (`span < SLEEP * 1.8`, i.e.
  three 0.25s-sleeping threads must jointly finish within 0.45s) in a file
  this change never touches (`git log` shows it untouched since the initial
  commit; `git status` confirms no diff). It failed here because the full
  1412-test run -- including this feature's own 169-gate `--help` subprocess
  smoke test and many other subprocess-heavy tests -- was still consuming
  CPU on this machine at the moment this test's threads ran. Confirmed as an
  environment-load flake, not a regression: re-run in isolation immediately
  afterward (`test_graph_parallel_dispatch.py`, all 6 tests, system otherwise
  idle) passed cleanly (`6 passed in 4.56s`). No code in this change touches
  threading, the engine's dispatch/join logic, or this test file.

## Concerns / residual gaps

- The PC-side local md5sum transcript has no authenticity marker convention
  (accepted design limitation, documented above and in-code) -- an agent
  could in principle hand-fabricate `local_md5sum_transcript_path`'s content
  since only the remote leg is transcript-marker-verified. This mirrors an
  identical, already-accepted limitation in `remote_execution_provenance_gate.py`.
- `signoff_bundle_completeness_gate.py`'s 9-class evidence-completeness
  check remains entirely self-attested (unmapped to real artifacts, by
  design-doc ruling) -- only the `bundle_hash`/`bundle_dir` cross-check is
  now real.
- `run_identity_consistency_gate.py` remains entirely self-attested, by
  explicit design-doc ruling; a durable persistence point for
  `server_sync_identity_gate`'s real recomputed `source_id`/`head_sha` would
  be the natural next step to close that gate for real.
