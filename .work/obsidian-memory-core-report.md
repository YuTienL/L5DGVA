# Obsidian+Git/Markdown Hybrid Engineering Memory — Foundational Layer (Workstream 1 of 4)

**Date**: 2026-09-03
**Scope**: Phases 2, 3, 7, 8 of the 25-phase spec, plus the core Phase 4–6 promotion-logic
wiring the task called out as foundational. Everything else (the Memory Agent, skill-mechanics
extension, git history/sync policy, dashboard/CLI surfacing) is explicitly out of scope for this
workstream and left for Workstreams 2–4.

## What was built

### New module: `dv_harness/memory_vault.py`

Placed as its own module (not folded into `memory.py` or `memory_router.py`) because it is a
genuinely separate concern — a Markdown/YAML representation and a pluggable provider interface —
that `memory_router.py` *imports*, exactly as the task suggested. `memory.py`'s JSON `MemoryStore`
remains completely untouched and is still the system of record; this module is strictly additive.

**Phase 2 — Obsidian CLI capability detection**
- `detect_obsidian_cli() -> dict`: real probe — `shutil.which("obsidian-cli"/"obsidian")`, then a
  list of real, existence-checked per-package-manager install paths (WinGet Links, Scoop shims,
  npm global, Chocolatey, `~/.local/bin`, `/usr/local/bin`) — then a real `--version`/`-v`
  subprocess call on whatever is found. **Not hardcoded**: verified by monkeypatching
  `shutil.which`+`subprocess.run` to simulate an installed CLI and confirming `installed`/
  `version`/`executable` correctly flip to the simulated values
  (`test_detect_obsidian_cli_is_a_real_probe_not_a_hardcoded_false`).
- **Real result on this machine** (unmocked, captured live during this work):
  ```json
  {"installed": false, "version": null, "executable": null, "vault_access": false,
   "search": "NOT_AVAILABLE", "read": "NOT_AVAILABLE", "create": "NOT_AVAILABLE",
   "update": "NOT_AVAILABLE", "properties": "NOT_AVAILABLE", "tags": "NOT_AVAILABLE",
   "links": "NOT_AVAILABLE", "status": "PARTIAL"}
  ```
  Matches the controller's own discovery exactly (`where obsidian-cli`/`where obsidian` both fail).
- **Design decision on `status`** (documented prominently because it resolves a real tension in
  the spec, not swept under the rug): Phase 8 explicitly requires every *operational* method
  (search/read/create/...) to stay `NOT_AVAILABLE` regardless of whether a CLI binary is found,
  because this codebase has never observed a real `obsidian-cli`'s command contract on any machine
  and guessing at subprocess syntax would risk silently fabricating results. Given that, `status`
  is defined to stay `PARTIAL` even when `installed: True` — a truthful "this machine has one"
  detection result is a different claim from "this adapter can do real work with it", and I chose
  not to conflate the two by flipping `status` to `READY` for a capability nothing here actually
  exercises. `status` only becomes BLOCKED on a genuine probing crash (wrapped in try/except,
  tested via a `shutil.which` side-effect); it is otherwise always PARTIAL, in either presence
  case — per spec, never BLOCKED merely for absence, and the real, fully-functional
  `FileSystemMarkdownAdapter` is always available regardless (see `HybridMemoryProvider` below).

**Phase 3 — DV-Knowledge Vault bootstrap**
- `VAULT_STRUCTURE` — the exact tree from the spec (`00_Inbox` … `07_Signoff/*`).
- `bootstrap_vault(vault_path) -> dict`: `mkdir(exist_ok=True)` only, everywhere — never removes or
  overwrites. Tested that a second bootstrap call over a vault containing a human-added file *and*
  a human-added custom folder leaves both completely untouched.
- `resolve_vault_path(project_root, cfg)`: reads `.dv-harness/config.json`'s new `memory.vault_path`.
  Never hardcoded — an empty/unset value (the shipped default) resolves to a project-relative
  `.dv-harness/vault`, not an external path this module invents. (The spec's own example config
  shows `"D:/DV/DV-Knowledge"` as an *illustration* of what a project might configure — the
  harness's own shipped default stays empty/project-relative, matching every other per-tier store's
  convention.)

**Phase 7 — Memory Note Schema**
- `MEMORY_NOTE_REQUIRED_FIELDS = [id, memory_level, protocol, status, confidence, created, updated]`,
  `MEMORY_NOTE_OPTIONAL_FIELDS = [subsystem, category, failure, project, rtl_sha, tb_sha,
  vip_vendor, vip_version, simulator, tags]`.
- `validate_note_frontmatter(fm) -> {"schema_status": "COMPLETE"|"PARTIAL", "missing_required": [...]}`
  — real validation, and `FileSystemMarkdownAdapter.create()`/`update()` bake `schema_status`
  straight into the note's own frontmatter, so incompleteness is visible on the file itself, not
  merely returned once and discarded.
  - **Confirmed a real, pre-existing production gap this way**: `engine.py`'s real
    `_promote_verified_fix_knowledge()` record has no `protocol` field, so every vault note it
    produces is honestly marked `schema_status: PARTIAL` (verified live — see Test Results below).
    This is not a bug I introduced; the vault write-through simply makes an existing schema gap
    visible where it was previously invisible (a bare JSON file with no schema check at all).
- `render_note_markdown()`/`parse_note_markdown()`: the real Symptom/Context/Hypothesis/Evidence/
  Root Cause/Fix/Verification/Confidence/Reusability/Known Limitations/Related Knowledge body
  template, with genuine `[[WikiLink]]` entries in Related Knowledge back to a record's
  `source_finding_id`/`source_engineering_memory_id`.
- Minimal, **intentionally scoped** YAML-frontmatter subset (`_scalar_dump`/`_scalar_load`/
  `_frontmatter_dumps`/`_frontmatter_loads`) — stdlib only. PyYAML is present in this dev
  environment but was deliberately **not** used: `requirements-harness.txt` states "Core harness
  uses Python standard library only" and PyYAML is not a declared harness dependency. The subset
  supports exactly what this schema needs (scalars + flat lists) and round-trips with itself
  (tested directly, including colons/quotes/newlines in values) — it is explicitly not, and must
  never be used as, a general YAML parser.

**Phase 8 — MemoryProvider interface + two real implementations + one composition layer**
- `MemoryProvider(ABC)`: `detect/status/search/read/create/update/delete/list_tags/list_links/
  get_properties/set_properties`.
- `ObsidianAdapter`: real `detect()`/`status()`; every other method returns a clear
  `{"ok": False, "status": "NOT_AVAILABLE", "reason": ..., "fallback": "FileSystemMarkdownAdapter"}`
  — per the spec's explicit "thin adapter" design. The `reason` string itself differs honestly
  depending on real detection state ("not installed" vs. "detected but not yet wired against a
  confirmed contract"), tested for both branches.
- `FileSystemMarkdownAdapter`: the real, fully-functional implementation. Every method genuinely
  operates on Markdown+YAML files — verified end-to-end (create → read → update partial-section-preserving
  → delete; search by protocol/tag/property/exact/keyword-text/empty-query/wiki-link-traversal;
  `list_tags`/`list_links` forward+backlinks; `get_properties`/`set_properties`). Search uses `rg`
  (confirmed present on this machine at `%LOCALAPPDATA%\Microsoft\WinGet\Links\rg.exe`) as an
  optional candidate-file prefilter when a text/exact term is given, with a full Python filesystem
  scan as the always-correct fallback (tested explicitly with `rg` forced absent via mock — same
  correct result). No embedding/vector database anywhere. Optional git integration
  (`git_enabled`): repo-local `git init` + `user.name`/`user.email` (never touches global git
  config) + a real commit per create/update/delete, gated behind `shutil.which("git")` so it never
  becomes a hard dependency; tested for real when `git` is present, skipped otherwise via
  `pytest.skip`.
- `HybridMemoryProvider`: composes both. **Design decision, not literal-instruction-following on
  autopilot** — the spec says "Obsidian used opportunistically if status() ever reports READY,
  filesystem otherwise", but because `ObsidianAdapter`'s operational methods are *unconditionally*
  `NOT_AVAILABLE` by the Phase 8 "thin adapter" design (even when `status()` were ever READY), a
  provider-level all-or-nothing pick keyed only on `status()` would silently stop writing anything
  real the instant a future machine's CLI is merely detected. `HybridMemoryProvider` instead makes
  the Obsidian-vs-filesystem choice **per call**: try Obsidian only when its `status()` is READY,
  and fall back to the filesystem adapter for that same call whenever the Obsidian result itself
  reports `NOT_AVAILABLE`. Verified directly: a mocked `ObsidianAdapter` reporting `status="READY"`
  but returning `NOT_AVAILABLE` from `create()` still results in a real file being written by the
  filesystem adapter (`test_hybrid_provider_falls_back_to_filesystem_when_obsidian_reports_ready_but_op_not_available`);
  a mocked Obsidian call that genuinely succeeds is used as-is with no duplicate filesystem write
  (`test_hybrid_provider_uses_obsidian_result_when_it_genuinely_succeeds`). This is what
  `get_active_provider()` returns and what the future Memory Agent should hold — never a bare
  adapter — so "Obsidian opportunistically, filesystem otherwise" is a real, always-safe guarantee
  rather than a one-time gamble.
- `get_active_provider(project_root, cfg)`: the factory. Bootstraps the vault, honors
  `memory.obsidian_cli == "disabled"` (skip Obsidian probing entirely, return the filesystem
  adapter directly) vs. `"auto"` (always probe, always safely degrade).

### `dv_harness/config.py`

Added a `memory` section to `DEFAULT_CONFIG`:
```json
"memory": {"provider": "hybrid", "vault_path": "", "obsidian_cli": "auto", "git_enabled": false}
```
`vault_path` empty by default (never hardcoded — same convention as `knowledge_center.remote_root`).
**`git_enabled` defaults `false`**, a deliberate deviation from the spec's illustrative example
config (which showed `"git_enabled": true`) — see the regression finding below for why.

### `dv_harness/memory_router.py` — Phase 4–6 core wiring

1. **Additive vault write-through** on `ENGINEERING_MEMORY` and `ORGANIZATIONAL_MEMORY` promotion
   only (per the task's explicit scope — `CORNER_CASE_LIBRARY` deliberately excluded, tested).
   `_maybe_write_vault_note()` mirrors the exact same gate as `_maybe_share()` (an explicit
   `cfg={}` opts out of every cfg-driven additive behavior, not just shared-KC push) and the exact
   same never-break-the-local-write guarantee (wrapped in try/except; a forced
   `get_active_provider` crash still leaves the real JSON record on disk and reports
   `vault_write: {"ok": false, "error": "VAULT_WRITE_FAILED", ...}` rather than raising — tested).
   For `ORGANIZATIONAL_MEMORY`, the vault write is only attempted once the shared-KC push itself
   actually reports `"ok": true` — a `NOT_CONFIGURED` push never had a real promotion happen, so
   there's nothing yet worth mirroring.

2. **Real `confirmation_count`/`last_confirmed_at` enforcement.** Full-repo grep confirmed, as the
   task flagged as a real possibility: `MemoryGC.confirm()`/`CornerCaseLibrary.confirm()` existed
   with zero real call sites anywhere in the codebase (`client.confirm(...)` in `cli.py` is
   `KnowledgeCenterClient.confirm`, an unrelated shared-store concept). Wired a real trigger:
   `_add_or_confirm_engineering()` — a second `route_and_store()` call landing on an ACTIVE
   engineering-tier record with the same `protocol` and (case-insensitive, exact-string, no fuzzy
   matching) `root_cause` now calls `MemoryGC.confirm()` on the *existing* record instead of
   creating a duplicate, and reports `confirmed_existing: true`. Tested: same-claim/different-casing
   dedups to one file with `confirmation_count == 1`; different protocol or different root_cause
   never dedups; a record missing either field (as engine.py's real `verified_fix` records
   currently do — see below) never attempts a match, byte-for-byte identical to pre-existing
   behavior.
   - **Honestly scoped limitation, not glossed over**: `engine.py`'s real
     `_promote_verified_fix_knowledge()` record doesn't currently include `protocol`, so this real,
     tested dedup/confirm path isn't yet reachable from that specific production call site — a
     separately-scoped follow-up (adding `protocol` to that record construction), not something
     fixable from `memory_router.py` alone.

3. **`promote_to_organizational(root, memory_id, confidence_inputs, cfg, kind)`** — the Phase 5/6
   promotion gate, Engineering → Organizational, three independent required gates:
   - **Qualitative hard precondition**, re-checked at promotion time (not merely trusted from
     however the record first reached the engineering tier, since a plain
     `route_and_store(kind="root_cause"/"debug_lesson")` call never validates anything). Real
     finding while building this: **two structurally different, both-real "genuinely verified"
     evidence shapes coexist in this codebase's engineering tier** —
     `MemoryConsolidator.from_closed_finding()`'s `{single_sim, regression, reaudit}` shape, and
     `engine.py`'s RE_AUDIT-gate shape (`{targeted_reproducer_passed, broader_regression_passed,
     new_failures_introduced, target_pre_fix_result, target_post_fix_result, replay_equivalent}`).
     `_verification_is_gate_validated()` recognizes both real shapes rather than inventing a third
     canonical one neither real write path uses (tested directly against both shapes, and against
     a record satisfying neither).
   - **Quantitative score**: `inference.score_confidence()` (the exact existing function, per the
     spec's explicit instruction not to build a parallel scoring system) on caller-supplied
     evidence-strength inputs; requires `level == "HIGH"`.
   - **Repeated confirmation**: `confirmation_count >= ORGANIZATIONAL_MIN_CONFIRMATIONS` (= 2).
     Tested: a freshly-CLOSED/VERIFIED record with zero confirmations is correctly rejected
     (`INSUFFICIENT_CONFIRMATION`) even though it already passes gates 1 and 2 — one creation event
     is not "repeated confirmation".
   On success, delegates to the existing `route_and_store()` (so all existing
   routing/sharing/vault-write-through behavior applies unchanged) — this function only decides
   *whether* to call it. Never raises for an ordinary gate miss; only for an unknown `memory_id`.

## Real regression found and fixed during this work

Defaulting `memory.git_enabled` to `true` (matching the spec's illustrative example config)
**broke 10 pre-existing tests** on a full-suite run: every `route_and_store()` call that
auto-loads config (the common case — most callers omit `cfg`) started a real `git init` + commit
inside each test's temp vault directory, and on Windows a plain `shutil.rmtree()` of a directory
containing a real `.git` tree fails with `PermissionError` on git's read-only object files —
exactly the "re-run the full existing memory test suite" check the task asked for caught this
before it shipped. Fixed by defaulting `git_enabled: false` (opt-in, matching
`knowledge_center.enabled`/`self_tuning.enabled`'s existing opt-in convention) — re-ran the full
suite after the fix with zero failures. This is documented as a deliberate, evidence-driven
deviation from the spec's example config, not an oversight.

## Test results

- New file `dv_harness_tests/test_memory_vault.py`: **41 tests, all passing** — covers every item
  above (detection real-probe + simulated-installed + crash-safety; bootstrap creation +
  non-destructive re-run; vault path resolution; schema validation COMPLETE/PARTIAL; frontmatter
  round-trip incl. special characters; `ObsidianAdapter` NOT_AVAILABLE + differing reasons;
  `FileSystemMarkdownAdapter` full CRUD + folder-by-level + search variants (protocol/tag/property/
  text/exact/empty/no-match) + rg-present and rg-forced-absent parity + tags/links + git
  integration on/off; `HybridMemoryProvider` fallback/pass-through/uses-real-obsidian-result;
  `get_active_provider` auto/disabled modes; router vault write-through on both destinations +
  failure-never-breaks-local-write + cfg={} opt-out; real confirm-dedup (positive, two negative
  cases, and the "fields absent" pre-existing-behavior-preserved case); `promote_to_organizational`
  (tier/status guards, both real verification shapes, neither-shape rejection, low-confidence
  rejection, insufficient-confirmation rejection at 0 and 1, full success path); two regression
  spot-checks of pre-existing credential-rejection and corner-case routing behavior).
- One pre-existing test updated (not behavior-changed): `test_memory_tier_completion.py`'s
  `test_route_and_store_actually_uses_the_named_tier_classes_not_just_the_base_store` did an exact
  dict-equality check on the `ORGANIZATIONAL_MEMORY` result; now pops the new, additive
  `vault_write` key before that comparison (with a comment explaining why), since the whole point
  of this workstream is that this key is new.
- **Full existing memory-adjacent suite** (`test_memory_tier_completion`, `test_engine_gates_and_routing`,
  `test_knowledge_center`, `test_inference_engine_wiring`, `test_react_working_memory_bridge`, plus
  the new file): **341 passed, 0 failed**.
- **Entire repository test suite** (`pytest` at repo root, all 102+ files): **1918 passed, 0 failed**
  (18m55s) — confirms the additive write-through and dedup/confirm logic changed nothing about any
  pre-existing behavior beyond the one intentionally-updated assertion above.

## Files touched

- **New**: `dv_harness/memory_vault.py`, `dv_harness_tests/test_memory_vault.py`
- **Modified**: `dv_harness/config.py` (added `memory` section), `dv_harness/memory_router.py`
  (vault write-through, confirm-dedup, `promote_to_organizational`),
  `dv_harness_tests/test_memory_tier_completion.py` (one assertion updated for the new additive key)

## Explicitly out of scope for this workstream (left for Workstreams 2–4)

- `.claude/skills/CORE/memory-consolidation` (and siblings) mechanics extension — Phase 16, a
  separate workstream per the task's own framing ("do not create new, differently-named skills");
  I read them and grounded `promote_to_organizational()`'s qualitative gate in their existing
  policy text, but did not edit the skill files themselves.
- `.claude/agents/memory-agent.md` — Phase 17, explicitly "genuinely needs a new file" per the
  task, a separate workstream.
- CLI/dashboard surfacing of vault status/search (`memory_cli.py`, `dashboard.py`) — not requested
  by this task's scope; `get_active_provider()`/`MemoryProvider` are ready for a future workstream
  to wire in without any interface changes.
- Real Obsidian CLI operation wiring — intentionally deferred until a real CLI's command contract
  is actually observed on some machine (see `ObsidianAdapter`'s docstring); the detection layer is
  ready to report `installed: true` truthfully the moment that happens.

## Module/class names for downstream workstreams

- Module: `dv_harness.memory_vault`
- Interface: `MemoryProvider` (abstract: `detect/status/search/read/create/update/delete/
  list_tags/list_links/get_properties/set_properties`)
- Implementations: `ObsidianAdapter`, `FileSystemMarkdownAdapter`, `HybridMemoryProvider`
- Factory: `get_active_provider(project_root, cfg=None) -> MemoryProvider`
- Bootstrap/schema: `bootstrap_vault`, `resolve_vault_path`, `VAULT_STRUCTURE`,
  `validate_note_frontmatter`, `render_note_markdown`, `parse_note_markdown`,
  `MEMORY_NOTE_REQUIRED_FIELDS`, `MEMORY_NOTE_OPTIONAL_FIELDS`, `MEMORY_NOTE_BODY_SECTIONS`
- Record mapping: `build_frontmatter_from_memory_record`, `build_sections_from_memory_record`
- Router additions (`dv_harness.memory_router`): `promote_to_organizational`,
  `ORGANIZATIONAL_MIN_CONFIRMATIONS`
