# exemptions.yaml system -- implementation report

## Status: DONE

## Concurrent-workstream safety (per task instructions)

- Checked `git status --short` and `git diff` on every shared file
  (`dv_harness/cli.py`, `dv_harness/config.py`) **before** the first edit.
  `cli.py` was clean; `config.py` already carried the sibling
  "evidence_db live wiring" workstream's uncommitted 14-line addition and
  was **not touched**.
- Did **not** touch `dv_harness/regression_reporter.py`,
  `dv_harness/evidence_db.py`, or `dv_harness/vip_distill.py`, per
  instruction.
- Mid-session, further sibling-workstream churn appeared in the working
  tree on its own (`dv_harness/session_snapshot.py` modified,
  `dv_harness/connectivity.py`, `dv_harness/degradation.py`, and
  `dv_harness/question_queue.py` created untracked, plus several
  `dv_harness_tests/test_evidence_db_wiring.py`-style additions). None of
  these were touched, read for editing, or depended on -- confirmed via
  `git diff --stat -- dv_harness/cli.py` showing exactly my own 95-line
  insertion and nothing else.
- No commit was made (not requested; nothing here required a git action to
  verify correctness, and creating one now would have meant staging a tree
  that also contains untracked sibling-workstream files, which is exactly
  the collision this session was told to avoid). All work is left as plain
  working-tree changes for the user/orchestrator to review and commit.

## What was built

1. **`dv_harness/schemas/exemptions.schema.json`** -- JSON Schema (draft
   2020-12), same rigor/style as
   `dv_harness/uvm_generator/schemas/run_profile.schema.json`
   (`$id`/`title`/`description`, `additionalProperties: false` throughout,
   a `$defs.exemption` sub-schema). Required per entry: `id`, `check_id`,
   `reason`, `basis_document`, `owner`, `valid_until`. `valid_until` is
   required, with no default and no alternate "no expiry" representation,
   and (per the independent-review fix below) must be a real,
   calendar-valid date -- per the user's own "有效期是關鍵欄位" requirement.
   **Correction (post-review, see addendum below): this does NOT make a
   permanent exemption structurally impossible** -- nothing stops an
   operator choosing a far-future `valid_until` (e.g. `9999-12-31`) as a
   de-facto permanent exemption. What the schema actually enforces is that
   an expiry date is always present and valid, not how far in the future it
   may be. Optional: `created_at`, `status` (`active`/`retired`),
   `protocol`, `notes`.

2. **`dv_harness/exemptions.py`** -- real module, not a stub:
   - `load_exemptions_document` / `save_exemptions_document` /
     `validate_exemptions_document` (jsonschema Draft202012Validator, same
     fail-closed contract as `run_profile.py`'s
     `RunProfileValidationError`).
   - `add_exemption(path, entry)` -- appends one entry, auto-generates
     `EXEMPT-NNNN` ids, stamps `created_at`, validates the **whole**
     resulting document before writing (a bad entry never reaches disk).
   - `is_expired` / `find_expired` / `find_active` / `check_expiry` -- the
     real, callable expiry-check function: given the current date and the
     exemptions file, returns entries whose `valid_until` has passed.
     `retired` entries are never reported expired.
   - `build_review_queue(path, as_of=None)` -- returns a list of
     `{exemption_id, check_id, reason, owner, basis_document, valid_until,
     expired_since, days_expired, as_of}` records for every currently
     expired entry.
   - `write_review_queue(queue, out_path)` -- persists that list as JSON to
     `.dv-harness/exemptions/review_queue.json` (default path via
     `default_review_queue_path()`), always writing the file even when
     empty.
   - The module's own docstring documents, explicitly and honestly, that
     `dv_harness/question_queue.py` does not exist yet, that this module
     does not depend on it, and that the JSON file above is the intended
     integration point for a future question-queue system to read from --
     matching the task's instruction not to invent that system.
   - Also documents its relationship to the pre-existing
     `dv_harness/waiver_store.py` (per-instance evidence waiver, no
     expiry) so the two are not confused or merged.

3. **CLI wiring in `dv_harness/cli.py`** -- `dv-harness exemptions
   {list, add, check, expire-report}`, added following the existing
   `knowledge`/`memory` subcommand-group conventions (a
   `sub.add_parser("exemptions")` with its own `add_subparsers`, one
   parser per verb, dispatch in the existing `elif args.cmd == ...` chain
   using `h.root` for the default project-scoped path). `check` and
   `expire-report` both `raise SystemExit(1)` when any entry is expired,
   `SystemExit(0)` otherwise -- the same CI-friendly nonzero-on-failure
   convention already used by the generated environment's
   `dv-check`/`run_all.sh` template scripts.

4. **`docs/EXEMPTIONS.md`** -- mechanism writeup plus a worked example
   built from a real, verifiable fact already in this repo:
   `dv_harness/uvm_generator/templates/sim_scripts/Makefile` (lines
   ~1501-1508 and the guard at line 3614) documents that unreachability
   coverage analysis (`UNR`) is deliberately compiled/run as its own
   separate, non-partitioned elaboration because it needs a separate VCS
   license and does not support `-partcomp` partition-compile mode. This
   is used as the doc's real `EXEMPT-0001` example (both as a YAML
   fragment and as the equivalent `dv-harness exemptions add` command),
   rather than a fabricated one.

## Tests

`dv_harness_tests/test_exemptions.py` -- 30 tests, all real (no mocks of
the module under test):
- Schema validation: valid document passes; each of the 6 required fields
  individually missing fails; `valid_until` specifically (the "key field")
  fails when omitted even with every other field present; malformed date
  string fails; unknown field rejected (`additionalProperties: false`);
  empty `basis_document` rejected.
- Load/save/add: missing file loads as an empty valid document; `add`
  round-trips through real YAML on disk (re-read independently); auto-ID
  increments and rejects a duplicate explicit id; `add` without
  `valid_until` refuses the write and leaves no partial file.
- Expiry detection: a not-yet-expired entry (`valid_until` in the future)
  stays active; a genuinely-expired entry (`valid_until` in the past) is
  flagged; `valid_until == as_of` is still the last valid (non-expired)
  day; a `retired` entry is never flagged regardless of date;
  `check_expiry()` reports correct active/expired counts over a mixed set.
- Review queue real content shape: `build_review_queue()` returns only the
  expired entries with every documented field populated and correct
  values (`days_expired` arithmetic checked exactly);
  `write_review_queue()` writes a real JSON file, including the empty-set
  case (file still written, `entries: []`).
- CLI subcommands via real subprocess dispatch (`python -m dv_harness.cli
  --project-root <tmp> exemptions ...`), mirroring
  `test_cli_blackboard.py`'s established style: `add` then `list`
  round-trip; `add` missing a required flag fails at the argparse level;
  `check` exits 0 with nothing expired / exits 1 with something expired;
  `expire-report` writes the real `review_queue.json` file to disk and
  exits 1 when something expired, exits 0 (with an empty-but-present file)
  when nothing is.

## Verification run (self-executed)

```
python -m pytest dv_harness_tests/test_exemptions.py -q
....................................... 
30 passed in 23.59s
```

Also re-ran three pre-existing CLI test files
(`test_cli_blackboard.py`, `test_cli_pueue.py`, `test_cli_git_guard.py`,
22 tests) after the `cli.py` edit to confirm no regression to the existing
argparse/dispatch structure: **22 passed**.

## Test summary (one line)

30/30 new tests pass (schema validation, expiry detection incl. both a
not-yet-expired and a genuinely-expired case, all 4 CLI subcommands, and
review-queue file content shape); 22/22 pre-existing CLI tests re-run
clean, no regression.

## Files touched/created

- `dv_harness/exemptions.py` (new)
- `dv_harness/schemas/exemptions.schema.json` (new)
- `dv_harness/cli.py` (modified -- additive only, 95 lines, verified via
  `git diff --stat`)
- `docs/EXEMPTIONS.md` (new)
- `dv_harness_tests/test_exemptions.py` (new)
- `.work/exemptions-yaml-report.md` (this report)

## Addendum: independent-review fixes (2026-09-03, NEEDS_FIX -> fixed)

An independent review found 1 real bug and 2 overclaims in the work above.
All 3 required items fixed before this work was committed:

1. **Real bug**: `validate_exemptions_document()` built a
   `jsonschema.Draft202012Validator(schema)` with no `format_checker`
   attached, so the schema's declared `"format": "date"` on `valid_until`
   was never actually enforced (format is annotation-only without one) --
   only the `pattern` regex ran, which a calendar-invalid date like
   `"2026-02-30"` satisfies. That let `add_exemption()` write an
   unrecoverable entry to disk, then crash `is_expired()`/
   `build_review_queue()` (and therefore `dv-harness exemptions check`)
   with an unhandled `ValueError` from `date.fromisoformat()`. Fixed by
   attaching `jsonschema.FormatChecker()` (built in, no new dependency) to
   the validator -- `add_exemption()` now rejects `"2026-02-30"` up front,
   before any write. Also defensively guarded `is_expired()`'s and
   `build_review_queue()`'s own `date.fromisoformat()` calls (new
   `_parse_valid_until()` helper) so a hand-edited-on-disk or legacy bad
   file still fails with a clean, catchable `ExemptionValidationError`
   rather than a raw traceback. `dv-harness exemptions {add,list,check,
   expire-report}` now catch `ExemptionValidationError` in `cli.py` and
   print a clean one-line message + exit 1, instead of letting it propagate
   as a raw traceback (same convention as `run-profile`'s
   `RunProfileValidationError` handling). New tests reproduce the exact
   review repro (`valid_until="2026-02-30"`) both via `add_exemption()` and
   via a hand-written bad file being checked.
2. **Overclaim**: "there is no schema-legal way to author a permanent,
   never-expiring exemption" (this report, `exemptions.schema.json`'s
   description, `exemptions.py`'s docstring) was false --
   `valid_until: "9999-12-31"` validates fine and is a de-facto permanent
   exemption. Reworded in all 3 locations to state accurately what IS
   enforced: `valid_until` must always be present and be a real,
   calendar-valid date; nothing prevents an operator from choosing a
   far-future date as a de-facto permanent exemption. No max-horizon schema
   constraint was added -- see this report's own reasoning above (not
   requested, and adding one is a product decision about what "too far in
   the future" means, not a mechanical validation fix).
3. **Stale doc**: `exemptions.py`'s docstring and `docs/EXEMPTIONS.md` both
   said `dv_harness/question_queue.py` "does NOT exist in this repo yet" --
   a sibling concurrent workstream created it since this report was
   written. Corrected both to state the module now exists but does not yet
   consume this module's review-queue output (confirmed via
   `grep -n "review_queue\|exemption" dv_harness/question_queue.py`
   returning no matches).

Test count after these fixes: `dv_harness_tests/test_exemptions.py` --
**32 passed** (30 original + 2 new: the calendar-invalid-date repro via
`add_exemption()`, and via a hand-written bad file checked through
`check_expiry()`).
