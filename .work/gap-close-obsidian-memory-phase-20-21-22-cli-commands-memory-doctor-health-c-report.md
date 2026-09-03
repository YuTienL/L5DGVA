# Gap-close: Phase 20 + 21 + 22 (CLI Commands / memory doctor Health Check / Tests)

**Verdict: NO_ACTION_NEEDED**

Date: 2026-09-04
Scope: Phase 20 (`memory` CLI subcommands), Phase 21 (`memory doctor` health check),
Phase 22 (14 numbered integration tests).
Nothing was BLOCKED and no PARTIAL in this scope was of the small/boundable kind, so
no code was written and no commit was made. This pass is a live re-confirmation of the
incoming audit's evidence, performed independently against the current working tree.

---

## Concurrency note (line numbers moved, substance did not)

Other workflows are concurrently editing `dv_harness/cli.py` and have since committed
changes to `dv_harness/memory_doctor.py`, so the incoming audit's cited line numbers no
longer resolve. I re-located every cited item by content and re-verified it. Critically:

```
$ git diff --stat dv_harness/cli.py
 dv_harness/cli.py | 39 ++++++++++++++++++++++++++++++++++++++-
$ git diff -U0 dv_harness/cli.py | grep -n 'memory'
(no output)
```

The uncommitted `cli.py` diff contains **zero** memory-related hunks — the ~86/~221-line
offset is entirely from another workflow's unrelated additions above the memory block.
No file was modified by me.

---

## Phase 20 — CLI Commands: **READY** (re-confirmed)

`memory` is a subparser group on the existing `dv_harness/cli.py` argparse tree — not a
parallel CLI framework. Group defined at `dv_harness/cli.py:801`, subparsers at
`dv_harness/cli.py:804`, dispatched in `main()` at `dv_harness/cli.py:1854-2012`.

All 9 subcommands present and wired to real backing code (verified by reading the
handler bodies, not just the parser definitions):

| Command | Parser def | Handler | Backing call |
|---|---|---|---|
| `memory status` | cli.py:806 | cli.py:1854 | `mv.get_active_provider(...).status()` |
| `memory search` | cli.py:809 | cli.py:1871 | `provider.search(query, limit=...)` |
| `memory show` | cli.py:833 | cli.py:1897 | `provider.read(args.note_id)` |
| `memory add` | cli.py:836 | cli.py:1902 | `memory_dedup.classify_note_candidate()` → `provider.create()` |
| `memory promote` | cli.py:853 | cli.py:1931 | `memory_router.promote_to_organizational()` |
| `memory graph` | cli.py:865 | cli.py:1956 | BFS over `provider.list_links()` |
| `memory validate` | cli.py:870 | cli.py:1983 | `memory_doctor.run_validate()` |
| `memory sync` | cli.py:874 | cli.py:1987 | `mv.bootstrap_vault()` + `mv._commit_vault_change()` |
| `memory doctor` | cli.py:878 | cli.py:2012 | `memory_doctor.run_doctor()` |

### Live runs (this pass, real project vault, 9 real notes)

Read-only subcommands run directly against the real vault:

- `python -m dv_harness memory doctor` → real JSON, `overall: PARTIAL`, 11-check breakdown.
- `python -m dv_harness memory status` → `provider: hybrid`, `status: READY`, with the
  Obsidian sub-provider honestly reporting `PARTIAL` / `NOT_AVAILABLE` per capability.
- `python -m dv_harness memory search "usb" --limit 2` → real matched note
  `MEM-0953BEC4D8` with full frontmatter and a real `score`.
- `python -m dv_harness memory validate` → `overall: PARTIAL`, `partial_reasons: ["schema"]`.
- `python -m dv_harness memory show MEM-0953BEC4D8` → real note frontmatter + path.
- `python -m dv_harness memory graph MEM-0953BEC4D8` → `{"root": ..., "nodes": [...], "edges": []}`
  (correct: that note genuinely has no wiki links).

The three **mutating** subcommands (`add`, `promote`, `sync`) I deliberately did **not**
run against the real project vault, since this pass must not modify state. They are
instead covered by real temp-dir CLI tests in
`dv_harness_tests/test_cli_memory_commands.py`, which exercise the actual `main()`
dispatch path: `test_memory_add_writes_a_note_and_reports_new_classification` (:59),
`test_memory_add_refuses_a_duplicate_without_force` (:85),
`test_memory_add_with_force_writes_the_duplicate_anyway` (:101),
`test_memory_promote_succeeds_through_all_gates` (:206),
`test_memory_promote_reports_gate_failure_reason_and_exits_nonzero` (:222),
`test_memory_sync_reports_disabled_when_git_not_enabled` (:188). All pass.

---

## Phase 21 — Health Check (`memory doctor`): **READY** (re-confirmed)

`run_doctor()` at `dv_harness/memory_doctor.py:289`, aggregating via `_aggregate()` at
`:258` (BLOCKED > PARTIAL > READY). Every check function re-located and confirmed:

| Spec requirement | Function |
|---|---|
| Vault exists / writable | `check_vault_writable()` :92 |
| Git status | `check_git()` :103 |
| Obsidian CLI detected | `check_obsidian()` :132 |
| Filesystem fallback | `check_filesystem_fallback()` :146 |
| Schema valid | `check_schema()` :152 |
| Duplicate IDs | `check_duplicate_ids()` :168 |
| Invalid YAML | `check_invalid_yaml()` :181 |
| Broken wiki links | `check_broken_links()` :186 |
| Large files | `check_large_files()` :200 |
| Secret leakage | `check_secrets()` :223 |
| Missing required metadata | folded into `check_schema()`'s per-note `missing_required` list |

The "missing required metadata" fold-in is confirmed present in real output, not just in
source — the live run emits per-note entries of the form
`{"note_id": "MEM-0953BEC4D8", "path": "...", "missing_required": ["protocol"]}`.
This is the equivalent-design case the task description covers: functionally present
under a different structure, so it is reported READY rather than rebuilt to literally
match the spec's key naming.

A **new 11th check has appeared since the incoming audit** —
`check_memory_store_index()` at `:234`, added by the sibling
`memory(obsidian-memory-phase-11-12-19)` commit (`93ecf3e`). It is additive and passes;
it explains the run_doctor line drift from 254 → 289.

### Not a hardcoded verdict

The live run returns `overall: PARTIAL` from two **genuine, data-driven** findings:

- `obsidian_cli: PARTIAL` — `installed: false`, with the check's own reason string
  disclosing this as an expected permanent state on this machine, with the filesystem
  adapter as the real always-available write path.
- `schema: PARTIAL` — 5 real notes missing `protocol`, each named with its real path.

Meanwhile `vault_writable`, `git` (`enabled: true`, `uncommitted_changes: 0`),
`filesystem_fallback` all return READY in the same run. A mixed verdict from real vault
state is the proof the aggregation is live rather than stamped.

**Assessment of the PARTIALs**: neither is a gap in Phase 21. `obsidian_cli: PARTIAL` is
the disclosed Obsidian-CLI-absent boundary the task description explicitly says to leave
as-is. `schema: PARTIAL` is the health check **correctly reporting a true fact about
existing note data** — the doctor working, not the doctor being incomplete. Editing those
5 notes to make the doctor go green would be falsifying the health signal, so I did not.

---

## Phase 22 — Tests: **READY** (re-confirmed)

`dv_harness_tests/test_obsidian_memory_final_integration.py` maps 1:1 to the 14 spec
cases by name. Re-run live this pass:

```
$ python -m pytest dv_harness_tests/test_obsidian_memory_final_integration.py -q
..............                                                           [100%]
14 passed in 12.29s
```

| # | Required case | Test | Line |
|---|---|---|---|
| 1 | No Obsidian CLI → filesystem fallback | `test_case_01_no_obsidian_cli_falls_back_to_filesystem_pass` | :91 |
| 2 | Obsidian CLI exists → adapter | `test_case_02_obsidian_cli_present_is_detected_SIMULATED` | :114 |
| 3 | Create note | `test_case_03_create_note` | :153 |
| 4 | Search note | `test_case_04_search_note` | :172 |
| 5 | Update note | `test_case_05_update_note` | :192 |
| 6 | YAML parse | `test_case_06_yaml_frontmatter_parse_round_trip` | :213 |
| 7 | Wiki link | `test_case_07_wiki_link_forward_and_backlinks` | :242 |
| 8 | Memory promotion | `test_case_08_memory_promotion_engineering_to_organizational` | :263 |
| 9 | Duplicate detection | `test_case_09_duplicate_detection` | :336 |
| 10 | Invalid note rejection | `test_case_10_invalid_note_rejection` | :365 |
| 11 | Secret redaction | `test_case_11_secret_redaction` | :386 |
| 12 | Git metadata | `test_case_12_git_metadata` | :414 |
| 13 | Session save | `test_case_13_session_save` | :445 |
| 14 | Session restore | `test_case_14_session_restore` | :473 |

Zero missing cases.

**Case 2 remains correctly disclosed.** It is the named boundary, not a hidden gap: no
real Obsidian binary exists on this machine (Case 1 proves that with an unmocked probe),
so `shutil.which`/`subprocess.run` are monkeypatched purely to prove
`detect_obsidian_cli()` is a genuine probe rather than a hardcoded `False`. The real
`ObsidianAdapter` remains a deliberately-unwired stub that still honestly reports
`NOT_AVAILABLE` even against a "detected" CLI. Per the task's rule on disclosed
boundaries, left as-is.

### Supporting suite

```
$ python -m pytest dv_harness_tests/test_memory_vault.py dv_harness_tests/test_memory_doctor.py \
    dv_harness_tests/test_memory_dedup.py dv_harness_tests/test_memory_security.py \
    dv_harness_tests/test_cli_memory_commands.py -q
101 passed in 27.63s
```

Matches the incoming audit exactly. All real: temp-dir filesystem and git operations, no
hardcoded results.

---

## Summary

| Sub-item | Incoming verdict | Re-confirmed verdict | Action |
|---|---|---|---|
| Phase 20 — 9 CLI subcommands | READY | **READY** | none |
| Phase 21 — `memory doctor` health check | READY | **READY** (now 11 checks) | none |
| Phase 22 — 14 integration tests | READY | **READY** | none |

**NO_ACTION_NEEDED.** No BLOCKED items existed. The two PARTIAL signals inside this scope
(`obsidian_cli`, `schema`) are the doctor honestly reporting real machine and real data
state — the mechanism functioning, not gaps in it — and the Case 2 SIMULATED label is the
disclosed Obsidian-absent boundary. No files were modified, no stale code was found in
scope, and therefore no commit was made.

**Test summary:** no change made; re-ran existing suites as verification —
14 passed (Phase 22 integration) and 101 passed (supporting memory suites), plus 6 live
read-only CLI subcommand invocations against the real 9-note project vault.
