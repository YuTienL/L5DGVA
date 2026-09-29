# Gap close: AI mechanism #11 Session Save/Restore

**Status: DONE** (2026-09-04 re-audit pass)

Supersedes this file's previous contents (the 2026-09-04 Ruling 3 / evidence-store
pass, still readable in git history). That pass is unchanged and still holds --
this one closes a different, smaller item the fresh re-audit surfaced.

## What the re-audit actually found

Verdict **WIRED_AND_FIRING**, and I re-confirmed the wiring myself before
touching anything rather than taking it on report:

- `engine.py:3638` calls `self._auto_checkpoint(stage, ...)` on every real stage
  transition; `_auto_checkpoint()` (`engine.py:2983-3009`) calls
  `session_snapshot.save_auto_checkpoint()` unless `config.json`'s
  `auto_checkpoint.enabled` is explicitly false.
- `cli.py:584/592/1765+` wires `save-session`/`restore-session` to the same
  `save_session()`/`restore_session()`.
- `test_harness_reliability.py::TestAutoCheckpoint` drives a real
  `h.run_stage(...)` and asserts a real `auto_*` snapshot lands on disk.

So mechanism #11 needed no wiring fix. 14 of the 16 required fields round-trip.
The re-audit named two PARTIAL fields. They are not the same kind of problem and
they are not resolved the same way here.

## Item 1 -- raw `command.txt` source: CLOSED

**The real gap.** Ruling 1 (2026-09-01) deliberately declines to *copy*
`project_input/08_command`, on the reasoning that it is durable project SOURCE
whose identity is already anchored by `state.json`'s `git_sha`. Declining to copy
it is right and is unchanged. What was wrong is that the snapshot then did not
so much as **name** it: the derived per-run catalog
(`generated/06_tests/command_catalog`) came back byte-for-byte while the source
it was derived FROM appeared nowhere in the manifest. And the git_sha anchor that
justified the omission is conditional -- it exists only if the project really
git-tracks `project_input/`, which `session_snapshot.py` cannot assume and never
checked. Where it does not, the content a run was driven by was both
unrecoverable *and* unidentifiable from the snapshot.

**The fix (`dv_harness/session_snapshot.py`), documented in place as Ruling 4:**

1. `SESSION_ARTIFACT_REFERENCE_DIRS` gains
   `"command_txt_source": "project_input/08_command"`. This is the EXISTING
   Ruling 2 reference mechanism reused verbatim -- path + size + streamed
   sha256, recorded into `manifest["artifact_references"]`, never copied, never
   restored over. No parallel capture path was built and
   `_collect_artifact_references()` needed no change at all: the one-line table
   entry rides the loop that already existed.
2. New `verify_artifact_references(project_root, manifest, keys=None)` re-hashes
   the live files and reports per file `MATCH` / `MODIFIED` / `MISSING` /
   `UNVERIFIABLE`, plus a worst-case roll-up per key. `UNVERIFIABLE` (no recorded
   sha256, e.g. over the hash size limit at save time) is deliberately never
   reported as `MATCH` -- the same discipline `restore_session()`'s existing
   `sha_match=None` already applies to the git SHA: an unknown comparison is not
   a passed one.
3. `restore_session()` returns it as `artifact_reference_verification`. Without
   this the manifest would hold the answer and nobody would ask it, which is what
   makes the reference worth more than a logged digest.
4. New `SESSION_VERIFIED_REFERENCE_KEYS = {"command_txt_source"}` scopes
   verification to that one key. FSDB/coverage stay record-only on purpose:
   re-hashing multi-GB dumps on every restore is exactly the slow, disk-thrashing
   behaviour Ruling 2 exists to prevent, and silently undoing it here would have
   been a real regression.

`dv_harness/cli.py`: the printed result already `json.dumps`es the whole dict, so
the new key surfaces with no change there. The one edit is that the
`SESSION_RESTORED` event now carries the per-key roll-up status, so "did this
restore resume against a modified command.txt" is answerable from
`.dv-harness/events.jsonl` / `dv-harness audit` rather than only from stdout that
nobody kept.

## Item 2 -- resolved runtime environment: NEEDS_SEPARATE_EFFORT

Not attempted, and deliberately not a same-pass fix. The gap is not that
`session_snapshot.py` fails to capture a resolved-environment record; it is that
**no such record exists anywhere in `dv_harness/`**. `preflight.py` computes its
checks live and persists nothing -- `run_preflight()` returns a `PreflightResult`
and no caller writes it. Adding the missing filename to `SESSION_FILES` is the
last and smallest step; everything before it is new capability.

It is also not merely "add a writer", because `check_env_vars()`
(`preflight.py:608`) checks env var **presence** only, by design:
`_build_env_check_command()` emits `$?VAR` / `[ -z "${VAR+x}" ]` presence tests
and its docstring records that `printenv`/`env`/`set`/`export` are blocked
outright by the persistent relay's own credential-inspection filter. Capturing
resolved VALUES means emitting commands that echo environment variable contents
on a remote DV server -- which runs straight into CLAUDE.md's standing rule that
credentials must never be printed, echoed, or written into any evidence block,
log, or gate payload. That needs a deliberate design decision about an allowlist
of safe-to-record variables, not a wiring change made in passing.

Scoped follow-up effort:
1. Decide and document an explicit allowlist of environment values that may be
   resolved and persisted (`$VCS_HOME`, license server host, `hostname`, tool
   versions), with everything else recorded by NAME only as today.
2. Add a value-resolving check to `preflight.py` restricted to that allowlist,
   respecting the existing csh/tcsh vs sh branch and the relay's command filter.
3. Persist a real `PreflightResult` (e.g. `.dv-harness/preflight_result.json`) on
   every run, with the resolved values and the timestamp/host they were resolved
   on.
4. Only then add that filename to `session_snapshot.SESSION_FILES`.
5. Verify: a real preflight run followed by save/restore shows the exact resolved
   values surviving, not just the config-level names `config.json`'s
   `preflight`/`execution_preflight` blocks already round-trip today.

## Verification

Negative reproduction first -- with the one table entry removed, the 6 new tests
fail with `KeyError: 'command_txt_source'` (4 in `test_session_and_info.py`, 2 in
`test_harness_reliability.py`), so they have real detection power rather than
passing vacuously. Entry restored, all pass.

New tests, all against the real functions:

- **On the PRODUCTION path, not just the function** (`test_harness_reliability.py`,
  `TestAutoCheckpoint`): a real `h.run_stage(...)` -> `_auto_checkpoint()` ->
  `save_auto_checkpoint()` transition produces a checkpoint whose manifest
  carries the real sha256 of the raw `command.txt` -- and still copies no
  `command.txt` anywhere, so Ruling 1 is proven intact on that same path.
- **The risk case end to end**: checkpoint via real `run_stage()`, edit the raw
  source afterwards, restore -> `status == "MODIFIED"`, and the live file keeps
  the operator's newer content (reported, never reverted).
- `test_session_and_info.py`: real hash on save; `MATCH` unchanged; `MISSING` when
  deleted (kept distinct from MODIFIED -- different operator action);
  `UNVERIFIABLE` rather than `MATCH` when no hash was recorded; restore never
  writes back into `project_input/`; an absent source dir is an absence, not a
  fabricated `MATCH`; verification never re-hashes FSDB; and the real CLI
  `restore-session` both prints the drift and leaves it on the
  `SESSION_RESTORED` event.
- The pre-existing `test_save_session_excludes_project_input_command_raw` was
  renamed to `..._never_copies_...` and strengthened (it now also asserts no
  `command.txt` exists anywhere under the snapshot), so adding the reference
  cannot quietly become a copy later.

**Test summary: 213 passed, 0 failed** -- `test_session_and_info.py` (57),
`test_harness_reliability.py` (42), and the adjacent suites that touch
`session_snapshot`/`cli` (`test_dashboard_interactive.py`,
`test_agent_checkpoint_check.py`, `test_active_stages_read_sites.py`,
`test_react_inference_wiring.py`, `test_debug_flow_memory.py` -- 114).

Also run against this repo's own live tree: a real `save_session()` here produced
a `command_txt_source` reference and `verify_artifact_references()` returned
`MATCH` (temporary session deleted immediately afterwards, no production file
touched).

**Disclosed, in the same spirit as the re-audit's own caveat**: this repo's
`project_input/08_command/` contains only a scaffolding `raw/.gitkeep`, because
this meta-repo has no real DUT and no real command.txt. The mechanism is real and
proven by the tests above against a real `run_stage()`; like several other
mechanisms here it has simply never had a real command.txt of its own to
identify. That is "no occasion to fire here", not "unreachable".

## Not in scope

Mechanism #13 (generic multi-protocol scope) and #14 (subsystem-to-SoC
generation) are untouched, per the pass's own framing.
