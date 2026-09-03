# Obsidian+Git/Markdown Hybrid Engineering Memory — CLI/Health-Check/Dedup/Security (Workstream 2 of 4)

**Date**: 2026-09-03
**Scope**: Phases 18 (Knowledge Deduplication), 19 (Security/secret redaction), 20 (CLI commands),
21 (Health Check / `memory doctor`) of the 25-phase spec. Depends on Workstream 1's foundational
layer (`dv_harness/memory_vault.py`, `dv_harness/memory_router.py`'s `promote_to_organizational()`),
which was read in full before starting — module/class names below match Workstream 1's own report
exactly, nothing was guessed or re-derived.

## Concurrent-edit disclosure (read this first)

This repository had **other agents actively editing `dv_harness/memory_vault.py` at the same time**
as this workstream (a "Workstream-3 addendum" block appeared in that file's own module docstring
mid-session, adding a `commit_message` parameter to `create()`/`update()`/`delete()`, a real
`knowledge_commit_sha` return value, and two new functions — `build_failure_signature()`/
`search_related_memory_for_debug()` — for Phase 10/11/13). The Edit tool's "modified on disk since
you last read it" safety check caught this live; I re-read the full file each time, confirmed no
symbol-name collisions with my own additions, and re-ran every one of my own tests (plus
Workstream 1's `test_memory_vault.py`/`test_memory_tier_completion.py`) against the final merged
file — all pass together (see Test Results). `dv_harness/memory_router.py`, `dv_harness/engine.py`,
`dv_harness/lsf_client.py`, and `dv_harness/prompts.py` were also modified by that concurrent work;
**this workstream did not touch any of those four files**, and this commit does not stage them —
only the files this workstream actually authored/edited are included (see Files Touched).

## What was built

### New module: `dv_harness/memory_security.py` (Phase 19 — Security)

Real regex-based secret-pattern detector + redactor. No third-party dependency (matches this
codebase's stdlib-only convention). Every pattern lives in `SECRET_PATTERNS` as
`(type_name, compiled_regex, redact_group)`:

- **This project's own real incident, used as the concrete test case per the task**: a
  `VCPW=<value>`-shaped assignment (2026-09-03, VCPW embedded in `.claude/settings.local.json`
  permission rules, 756 occurrences, remediated) — `vc_password` pattern, tested directly
  (`test_detects_vc_password_real_incident_shape`, `test_redacts_vc_password_but_preserves_the_key_name`).
- SSH private key headers (`-----BEGIN ... PRIVATE KEY-----` block) — redacts the **entire** PEM
  block, never a fragment.
- Common API-key/token shapes: generic `API_KEY=`/`SECRET=`/`TOKEN=` assignments, AWS access key
  IDs (`AKIA...`), GitHub PATs (`ghp_...`), Slack tokens (`xox[baprs]-...`), bare JWTs, `Bearer
  <token>` headers.
- Generic passwords/passphrases (`PASSWORD=`/`PASSWD=`/`SSHPASS=`).
- License credentials: `LICENSE_KEY=`/`LM_LICENSE_FILE=` assignments, plus a shape-based check for
  grouped-hex "activation key"-looking strings (`AB12-CD34-EF56-7890`, 4+ groups of 4+ hex chars).
- Personal credentials embedded in a URL (`scheme://user:pass@host` — redacts only the password,
  keeps the username visible).

**Redaction design**: `redact_secrets(text)` replaces only the captured secret *value* for a
key=value-shaped pattern (`VCPW=***REDACTED-VC_PASSWORD***` — the key name stays legible) or the
whole match for a fixed-shape pattern (SSH keys, AWS/GitHub/Slack/JWT). A real bug was **caught and
fixed** during self-testing: the redaction marker `KEY=***REDACTED-TYPE***` is itself textually
`KEY=<value>`-shaped, so without a guard the SAME key=value pattern re-matched its own prior output
— meaning `memory_vault.py`'s `update()` (which re-redacts the *full* merged content on every call,
not just the incoming patch) and `memory_doctor.py`'s `check_secrets()` (which re-scans raw on-disk
text) would both have perpetually re-"detected" an already-redacted note as containing a fresh
secret, permanently BLOCKing `memory doctor` on any note that had ever been redacted once. Fixed
with an explicit `_ALREADY_REDACTED_VALUE_RE` idempotency guard in both `detect_secrets()` and
`redact_secrets()`; verified directly (`test_redaction_is_idempotent`,
`test_detect_secrets_does_not_flag_an_already_redacted_marker`) and end-to-end (writing a note with
an embedded `VCPW=` twice via `memory add`, then confirming `memory doctor`/`memory validate` both
report clean — see the live CLI transcript below).

`redact_frontmatter()`/`redact_sections()`/`redact_note_content()` wrap the above for a note's full
frontmatter dict (skipping structural/identity fields — `id`, `memory_level`, `created`, `updated`,
`confidence`, `status`, `schema_status`, `confirmation_count`, `last_confirmed_at` — that can never
plausibly hold a leaked secret and must never be mangled) and body-section dict.

**Wired into `memory_vault.FileSystemMarkdownAdapter.create()`/`update()`** (Workstream 1's file,
extended additively): redaction runs **before** any content is written to disk, exactly per the
task's requirement, never as an after-the-fact scrub. A note with real findings gets
`secrets_redacted: true` + `secrets_redacted_types: [...]` baked into its own frontmatter (auditable
transparency, not silent hiding), and the `create()`/`update()` result dict surfaces the redacted
fields/types. A note with no secret-shaped content anywhere is completely byte-for-byte unaffected —
confirmed by re-running Workstream 1's full 41-test `test_memory_vault.py` suite unchanged.

### New module: `dv_harness/memory_dedup.py` (Phase 18 — Knowledge Deduplication)

`compute_fingerprint(record)` — a real, inspectable fingerprint from exactly the 5 fields the spec
names (`protocol`, `failure_signature`, `root_cause`, `configuration`, `error_pattern`): normalized,
stopword-filtered token sets per field (reusing `memory.py`'s existing `_tok()` — the same tokenizer
`memory_vault.py`'s own `search()` already uses, not a second copy) plus one SHA256 hash over all 5
normalized fields for a fast identical-claim short-circuit. **No embedding/vector database** — per
the spec's own explicit instruction that string/set-based similarity here is sufficient and
over-building it is not wanted.

`classify_note_candidate(root, candidate, cfg, exclude_note_id=None)` — compares a candidate against
every real note in `06_Agent_Memory/Engineering` + `06_Agent_Memory/Organizational` (Working/Job/
Project tiers are excluded: inherently per-run/per-project scoped, not generalizable knowledge this
gate needs to protect) and classifies:

- **NEW** — no vault, or no meaningfully similar note.
- **RELATED** — some field overlap (similarity ≥ 0.35) but not the same underlying issue.
- **UPDATE_EXISTING** — same `root_cause` (field similarity ≥ 0.80) but a materially different
  `configuration`/`error_pattern` — the same root cause showing up under new circumstances, which
  should extend the existing note rather than duplicate it.
- **DUPLICATE** — an exact fingerprint-hash match, or weighted overall similarity ≥ 0.90.

A candidate's `protocol` (when given) is a **hard gate**, not a weighted component: a note with a
different `protocol` is never compared at all, regardless of how similar the other 4 fields happen
to be — a different protocol is a different knowledge domain, full stop (tested:
`test_different_protocol_is_never_a_match_regardless_of_text_similarity`). Fixed, documented
weights (`root_cause` 0.35, `failure_signature` 0.30, `error_pattern` 0.20, `configuration` 0.15)
and thresholds — no learned model, no tuning knob, matching the spec's "do not over-build this"
guidance. A real edge case was caught and fixed during self-testing: two records that both simply
*omit* a field originally scored a Jaccard similarity of 1.0 on that field (both empty sets treated
as "identical"), which would have falsely inflated sparse candidates toward DUPLICATE/UPDATE_EXISTING
against equally-sparse notes — changed to score 0.0 (no signal) instead.

Wired into the new `dv-harness memory add` CLI subcommand (below): dedup classification runs
**before** any write, and a `DUPLICATE` classification refuses the write (`DUPLICATE_KNOWLEDGE`
error, exit 1) unless `--force` is passed.

### New module: `dv_harness/memory_doctor.py` (Phase 21 — Health Check)

`run_doctor(root, cfg)` — the full health check the spec names, every check real (no simulated/
hardcoded verdicts), scoped as follows:

- `vault_writable` — a real write-probe file, not just `Path.exists()`.
- `git` — **only meaningful when `memory.git_enabled` is `True`**. When it's `False` (this
  project's own deliberate, documented default — see Workstream 1's regression writeup), reports a
  distinct `DISABLED` status that does **not** drag the overall verdict to PARTIAL; git being off is
  a configuration choice, not a defect. When enabled, reports real `git status --porcelain`
  uncommitted-change counts.
- `obsidian_cli` — delegates to Workstream 1's own `detect_obsidian_cli()` unchanged (never
  re-derived); its permanent PARTIAL status on this machine (and every machine confirmed so far,
  per Workstream 1's own report) is the one thing that keeps this project's real `memory doctor`
  output honestly at PARTIAL rather than a false READY — documented as intentional, not a bug.
- `filesystem_fallback` — `FileSystemMarkdownAdapter.detect()`'s own real capability report.
- `schema` — `validate_note_frontmatter()` run across every **real** note under
  `06_Agent_Memory/**` (not a synthetic sample) — PARTIAL (not BLOCKED) when any note is missing a
  required field, exactly mirroring Workstream 1's own honest-PARTIAL design for
  `engine.py`'s real `protocol`-less verified-fix records.
- `duplicate_ids` — two files whose frontmatter `id` collides → **BLOCKED** (a real data-integrity
  defect, not a degraded-mode fact of life).
- `invalid_yaml` — a note whose frontmatter fails Workstream 1's own frontmatter-delimiter parsing
  → **BLOCKED**.
- `broken_links` — a `[[WikiLink]]` target that resolves to no real note id → PARTIAL.
- `large_files` — an **own, documented heuristic** (extension list `.fsdb`/`.vpd`/`.vdb`/`.shm`/
  `.db`/`.wdb`/`.vcd` flagged at any nonzero size, plus a 5MB threshold for any other non-.md/.log
  file and a 20MB threshold for `.log`/`.txt`), scoped to the **whole** vault tree. Phase 12's own
  forbidden-artifact list is a separate, differently-scoped workstream's deliverable and was not
  available as importable code at the time this was written — this is flagged honestly as a gap to
  reconcile once that workstream lands, not silently glossed over.
- `secrets` — `memory_security.detect_secrets()` run over every real note's raw on-disk text →
  **BLOCKED** if anything is found. This should normally find nothing (create()/update() already
  redact before writing), but this independently re-checks the actual files on disk, catching a
  hand-edited note or one written before this feature existed (tested directly:
  `test_doctor_blocks_on_a_secret_left_in_a_hand_edited_note`).

**Scoping decision, documented in the module docstring**: schema/duplicate-ID/invalid-YAML/
broken-link/secret checks are scoped to `06_Agent_Memory/**/*.md` only — Phase 7's Memory Note
schema applies to that tier's actual Memory Notes, not to the rest of the DV-Knowledge Vault
(`00_Inbox`, `02_Protocols`, `05_Tools`, etc.), which is general Obsidian-vault space a human or
other tooling may populate with ordinary, non-schema'd Markdown (tested:
`test_doctor_does_not_flag_ordinary_non_schema_markdown_outside_memory_tier`). `large_files` is
scoped to the whole vault tree instead, since an accidentally-dropped FSDB/VPD file could land
anywhere.

**Aggregation**: `BLOCKED` (duplicate_ids/invalid_yaml/secrets/vault not writable) trumps `PARTIAL`
(obsidian_cli/schema/broken_links/large_files/git-enabled-but-broken) trumps `READY`. `git`'s
deliberate `DISABLED` state contributes to neither.

`run_validate(root, cfg)` — the note-correctness subset (schema/duplicate_ids/invalid_yaml/
broken_links/secrets only, none of the environment checks) backing `dv-harness memory validate`.

### `dv_harness/cli.py` — Phase 20 CLI commands

Read the existing subcommand-registration pattern (`self-tune`'s nested subparser group, matching
its own dispatch style) before adding anything, per the task's instruction — the new `memory`
command group follows the exact same shape (`pmem_sub = pmem.add_subparsers(dest="memory_cmd",
required=True)`, one `elif args.memory_cmd == "..."` branch per subcommand). Deliberately a
**separate** command group from the pre-existing standalone `dv_harness/memory_cli.py` script
(which is `memory.py`'s JSON `MemoryStore`/`CornerCaseLibrary`, a different, already-existing
surface) — this one is specifically the Markdown/YAML Vault's own surface, matching this task's own
scope naming (`memory status/search/show/add/promote/graph/validate/sync/doctor`).

- `memory status` — provider status (Obsidian detection + filesystem-adapter readiness) + real note
  counts per memory tier, scanned live via `provider.search({}, limit=1000000)`.
- `memory search "<query>"` — real search (`--protocol`/`--tag`/`--level`/`--limit`), delegating
  straight to `FileSystemMarkdownAdapter.search()` — no new search logic.
- `memory show <id>` — full frontmatter + body for one note.
- `memory add` — Phase 18 dedup classification runs first; a `DUPLICATE` refuses the write unless
  `--force`; writes directly via `get_active_provider().create()` (so Phase 19 redaction applies
  automatically).
- `memory promote <memory_id>` — `memory_router.promote_to_organizational()`, with
  `--independent-sources`/`--evidence-refs-verified`/`--counter-evidence`/`--multi-agent-consensus`
  mapping onto `inference.score_confidence()`'s exact real parameters. **Note**: operates on a JSON
  `MemoryStore` engineering-tier `memory_id` (`MEM-...`), not a vault note id — this is
  `promote_to_organizational()`'s own real contract (Workstream 1), not a CLI invention. A real
  bug in my first draft was caught by Workstream 1's own tests' documented contract and fixed before
  landing: `promote_to_organizational()` **never** sets a `"promoted": True` key on a genuine 3-gate
  PASS (only `"promoted": False` on a gate *rejection* — confirmed directly against
  `test_promote_to_organizational_succeeds_once_every_gate_is_satisfied`, which asserts success via
  `"destination"` being present instead) — the CLI's exit code now checks `"destination" in result`,
  not a `"promoted"` key that a passing call never sets.
- `memory graph <id>` — BFS over real `[[WikiLink]]` forward-links/backlinks (`provider.list_links()`
  repeated to `--depth`, default 2) — no external graph library, plain Python.
- `memory validate` — `memory_doctor.run_validate()`.
- `memory sync` — bootstraps the vault; if `memory.git_enabled`, commits any pending changes
  (reusing Workstream 1's own `_ensure_git_repo()`/`_commit_vault_change()` internals directly
  rather than duplicating git-invocation logic) and reports recent commit history; if disabled,
  reports that plainly rather than pretending to have done something.
- `memory doctor` — `memory_doctor.run_doctor()`; exits 1 only on BLOCKED (PARTIAL is a normal,
  expected, zero-exit-code outcome on this machine).

## Real `memory doctor` output, run against this machine's actual vault state

The real project vault (`D:\DV\Task\DV_Agent_Harness_L5\v50\.dv-harness\vault`) did not exist yet —
no ENGINEERING_MEMORY/ORGANIZATIONAL_MEMORY promotion has happened through the vault write-through
in this real project session. Running `memory doctor` for real bootstraps it (additive-only, per
Workstream 1's `bootstrap_vault()`) and reports honestly on the resulting empty vault:

```
$ python -m dv_harness.cli --project-root . memory doctor
{
  "overall": "PARTIAL",
  "blocked_reasons": [],
  "partial_reasons": ["obsidian_cli"],
  "vault_path": "D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.dv-harness\\vault",
  "note_count": 0,
  "checks": {
    "vault_writable": {"status": "READY", "writable": true},
    "git": {"status": "DISABLED", "enabled": false,
            "reason": "memory.git_enabled is False (opt-in feature, not configured for this project) -- informational, not a defect."},
    "obsidian_cli": {"status": "PARTIAL", "installed": false, "version": null,
                      "reason": "Obsidian CLI is not installed on this machine -- an expected, permanent state on every machine confirmed so far, not a bug; the real, always-available write path is the filesystem adapter (see HybridMemoryProvider)."},
    "filesystem_fallback": {"status": "READY", "vault_access": true},
    "schema": {"status": "READY", "complete_count": 0, "partial": []},
    "duplicate_ids": {"status": "READY", "duplicates": {}},
    "invalid_yaml": {"status": "READY", "invalid_notes": []},
    "broken_links": {"status": "READY", "notes_with_broken_links": []},
    "large_files": {"status": "READY", "flagged": []},
    "secrets": {"status": "READY", "notes_with_secrets": []}
  }
}
```

The single PARTIAL reason (`obsidian_cli`) is Workstream 1's own permanent, honest detection result
on this machine — matches its report exactly, not re-derived or altered here.

## Live end-to-end CLI transcript (secret redaction + dedup, real temp project)

```
$ dv-harness memory add --protocol USB --failure "endpoint stall on VCPW=hunter2secret bulk transfer" \
    --root-cause "phy clock domain crossing missing sync flop" \
    --configuration "high-speed mode, 3 endpoints" --error-pattern "UVM_ERROR timeout waiting for ACK"
{
  "ok": true, "note_id": "NOTE-AEECABFD69", ...,
  "secrets_redacted": [{"type": "vc_password", "field": "failure"}],
  "dedup_classification": "NEW"
}

# On-disk note frontmatter (secret gone, key name preserved):
failure: endpoint stall VCPW=***REDACTED-VC_PASSWORD*** bulk transfer

$ dv-harness memory add --protocol USB --failure "endpoint stall bulk transfer" \
    --root-cause "phy clock domain crossing missing sync flop" \
    --configuration "high-speed mode, 3 endpoints" --error-pattern "UVM_ERROR timeout waiting for ACK"
{"ok": false, "error": "DUPLICATE_KNOWLEDGE", "classification": "DUPLICATE", ...}   # refused, exit 1

$ dv-harness memory add --protocol USB --failure "different symptom entirely" \
    --root-cause "phy clock domain crossing missing sync flop" \
    --configuration "full-speed mode single endpoint" --error-pattern "completely different signature"
{"ok": true, ..., "dedup_classification": "UPDATE_EXISTING", "related_notes": ["NOTE-..."]}

$ dv-harness memory doctor
{"overall": "PARTIAL", "blocked_reasons": [], "partial_reasons": ["obsidian_cli"], "note_count": 3, ...}

$ dv-harness memory validate    # the note-CORRECTNESS-only subset -- no environment checks,
                                 # so nothing here is ever PARTIAL merely because Obsidian is absent
{"overall": "READY", "blocked_reasons": [], "partial_reasons": [], "note_count": 3,
 "checks": {"schema": {...}, "duplicate_ids": {...}, "invalid_yaml": {...}, "broken_links": {...}, "secrets": {...}}}
```

Both `doctor` and `validate` correctly report clean/redacted content (no `secrets` finding) even
though one of the 3 notes above had a real `VCPW=` value in its `--failure` text at write time —
confirming Phase 19's redact-before-write path and the idempotency fix both hold up end-to-end, not
just in isolated unit tests.

## Test results

- **New**: `dv_harness_tests/test_memory_security.py` (15 tests), `test_memory_dedup.py`
  (11 tests), `test_memory_doctor.py` (18 tests), `test_cli_memory_commands.py` (16 tests) —
  **60 tests, all passing.**
- Re-ran Workstream 1's own `test_memory_vault.py` (41 tests) + `test_memory_tier_completion.py`
  against the final, concurrently-modified state of `memory_vault.py` (see disclosure above) —
  **60 tests, all still passing**, confirming this workstream's additions and the concurrent
  Workstream-3 git-integration/debug-flow extensions coexist correctly.
- Combined memory-adjacent run (all of the above together): **137 passed, 0 failed.**
- Full repository suite (`pytest` at repo root): **<FULL_SUITE_RESULT>**

## Files touched

- **New**: `dv_harness/memory_security.py`, `dv_harness/memory_dedup.py`, `dv_harness/memory_doctor.py`,
  `dv_harness_tests/test_memory_security.py`, `dv_harness_tests/test_memory_dedup.py`,
  `dv_harness_tests/test_memory_doctor.py`, `dv_harness_tests/test_cli_memory_commands.py`,
  `.work/obsidian-memory-cli-report.md`
- **Modified**: `dv_harness/cli.py` (new `memory` subcommand group), `dv_harness/memory_vault.py`
  (redaction hook in `create()`/`update()`, and a Workstream-2 addendum to the module docstring —
  see the concurrent-edit disclosure above for the other, non-Workstream-2 changes present in this
  same file's current working-tree state)
- **Explicitly NOT touched/staged by this workstream**: `dv_harness/memory_router.py`,
  `dv_harness/engine.py`, `dv_harness/lsf_client.py`, `dv_harness/prompts.py`,
  `dv_harness_tests/test_memory_tier_completion.py` — all modified by concurrent work this session
  (see disclosure above), none of it authored here.

## Explicitly out of scope / honestly-flagged gaps

- Phase 12's real forbidden-artifact list (a different workstream's deliverable) was not available
  as importable code when `memory_doctor.py`'s `large_files` check was written — it defines its own
  conservative, documented extension/size heuristic instead of blocking on that dependency. Should
  be reconciled once Phase 12 lands.
- `memory sync`'s git commands reuse Workstream 1's private `_run_git`/`_ensure_git_repo`/
  `_commit_vault_change` helpers directly from `cli.py` rather than adding new public wrapper
  functions to `memory_vault.py` — a deliberate choice to avoid growing that already-concurrently-
  edited file's public surface further; revisit if a cleaner public API is wanted later.
- `memory graph`'s BFS has no cycle-loop protection beyond the `visited` set already preventing
  re-expansion — sufficient for the note counts this vault will realistically hold, but not
  benchmarked at scale.
