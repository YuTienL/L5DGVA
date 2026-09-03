# Gap close: Evidence Layer (logs / FSDB / coverage -> Distillation -> vip_distill.py -> verible -> DuckDB)

**Status: DONE** — commit `ddb8808`.

**Test summary**: 190 passed (`test_evidence_layer_wiring` [new, 13],
`test_evidence_db`, `test_evidence_db_wiring`, `test_vip_distill`,
`test_verible_parser`, `test_env_manifest`, `test_fsdb_report`,
`test_mcp_env_manifest_integration`, `test_mcp_read_only_boundary`,
`test_mcp_query_regression`), plus 56 passed across the CLI-surface tests
(`test_cli_adapter_command_resolution`, `test_cli_preflight`,
`test_cli_question_queue`, `test_cli_memory_commands`,
`test_active_stages_read_sites`) since a CLI subcommand's arguments changed.

---

## What the fresh re-verification found (and what had moved since the audit)

The audit's five stage verdicts were re-checked from scratch against the
current tree, not trusted. Three were still open exactly as described; one
had been closed by a concurrent workstream in the meantime; one was
correctly diagnosed as not a real edge.

| Stage | Audit verdict | Re-verified state | Action |
|---|---|---|---|
| 1. sim.log -> vip_distill -> DuckDB | broken at HEAD, fixed only in uncommitted tree | **Confirmed still broken at HEAD** | Committed the fix |
| 2. FSDB -> vip_distill -> DuckDB | REAL_BUT_DISCONNECTED | **Confirmed, zero live callers** | Wired |
| 3. coverage -> DuckDB | REAL_BUT_DISCONNECTED | **Already closed by another workstream** | No action (verified) |
| 4. vip_distill -> verible | ASPIRATIONAL (not a real edge) | **Confirmed — diagram layout, not dataflow** | No action (correct as-is) |
| 5. verible -> DuckDB | REAL_BUT_DISCONNECTED | **Confirmed, zero live callers** | Wired |
| 6. DuckDB read-back (`normalized_evidence` etc.) | regression_verdicts-only | **Confirmed, unchanged** | NEEDS_SEPARATE_EFFORT (out of scope) |

---

## 1. sim.log -> `distill_sim_log()` -> DuckDB — was BROKEN AT HEAD, now committed

Re-confirmed the audit's central finding with a direct HEAD read:

```
$ git show HEAD:dv_harness/evidence_db.py | grep -c insert_normalized_evidence
0          # before
2          # after ddb8808
```

Commit `06b3e68` landed `regression_reporter.py`'s caller
(`store.insert_normalized_evidence(envelope)`, now at
`regression_reporter.py:336`) and `test_evidence_db_wiring.py`'s tests, but
never committed `evidence_db.py`'s `normalized_evidence` table or its
`insert_normalized_evidence()` method. At HEAD, every real reconciliation
cycle reaching a job with a real `state.sim_log` raised
`AttributeError: 'EvidenceStore' object has no attribute
'insert_normalized_evidence'` straight into that call site's own
print-and-continue `try/except` — so the failure was invisible and the row
was never written.

The fix was the schema (`evidence_db.py`, `normalized_evidence` table) and
method already sitting uncommitted in the working tree, plus its five tests
in `test_evidence_db.py`. Both are now committed. The caller and its wiring
tests needed no change — they were already correct.

## 2. FSDB -> Distillation -> `vip_distill.py` -> DuckDB — wired

`vip_distill.distill_fsdbreport()` (`dv_harness/vip_distill.py:248`) had
**zero live call sites repo-wide** — a grep hit only its own definition,
docstrings, and `test_vip_distill.py` bodies. The project's only real
producer of fsdbreport output, `dv-harness fsdb-report`
(`dv_harness/cli.py`), ran the real `fsdbreport` binary via
`fsdb_report.run_fsdbreport()`, parsed it via
`fsdb_report.parse_fsdbreport_output()`, and then only printed or
file-dumped the raw JSON. The diagram's `FSDB -> Distillation -> DuckDB`
edge did not exist in code.

**Added**: `dv_harness/fsdb_report.py::ingest_report_to_evidence_db()`,
called from the `fsdb-report` command immediately after its existing parse.
It passes the **already-parsed** report to `distill_fsdbreport()` (never a
second parse of the same text), stores the envelope unchanged via
`insert_normalized_evidence()`, and adds the resulting `evidence_id` to the
command's own JSON output so an operator can join console output to the
DuckDB row.

Three new optional CLI arguments — `--topic`, `--job-id`, `--pattern` —
carry the row's provenance. Omitting them stores honest SQL NULLs rather
than inventing a job or pattern the run did not have. `verdict`/`counts`
likewise stay NULL, because fsdbreport is trace evidence, not a checker —
`distill_fsdbreport()`'s own deliberate design, preserved end to end.

## 3. coverage -> DuckDB — already closed, no action taken

The audit found `insert_coverage_sample()` unwired, citing
`.work/evidence-db-wiring-step2-report.md:187`. **That is no longer true**,
and I verified the live path rather than the report:

```
engine.py:3209  self._append_coverage_history_sample(stage, evidence_blocks)
engine.py:1579    -> dashboard.append_coverage_history_sample(self.root, float(percent))
dashboard.py:1576   -> _ingest_coverage_summary_to_evidence_db(root, timestamp=timestamp)
dashboard.py:1542     -> store.insert_coverage_sample(category, ...)
```

This fires on every real `COVERAGE_CLOSURE` PASS, is committed at HEAD, and
routes through `coverage_analysis.parse_coverage_summary()`. Nothing to do.

Note the diagram edge as literally drawn — coverage *through vip_distill.py*
— is still not real and should not be made real: `vip_distill.py` has no
coverage function and `SOURCE_KINDS` has no coverage member. Coverage has
its own typed `coverage_samples` table; routing it through an evidence
envelope built for pass/fail/count-bearing sources would lose structure, not
gain it. The diagram's box is a layer label, not a required call.

## 4. `vip_distill.py` -> verible — confirmed not a real edge, deliberately not built

Re-confirmed: `grep -i verible dv_harness/vip_distill.py` returns nothing,
and the two modules have no coupling in either direction. The diagram's
vertical stacking is layout, not dataflow — they are two independent
producers that both target `evidence_db.py` (`normalized_evidence` vs.
`rtl_modules`). Manufacturing a call between them would be inventing a
mechanism to match a picture. Left alone, and stage 5 below is what the
picture actually means.

## 5. verible -> parsers -> DuckDB — wired

`evidence_db.insert_rtl_parse()` and its four traceability tables
(`rtl_modules`/`rtl_ports`/`rtl_signals`/`rtl_parameters`) were real and
tested against real verible-derived JSON, and
`verible_parser.run_export_json()` really shells out to
`verible-verilog-syntax --export_json --printtree` — but **no path called
both together outside test bodies**. Both
`.work/evidence-db-wiring-step1-report.md` and `step2-report.md` list
`insert_rtl_parse` explicitly as "remains unwired". The only real verible
caller, `dv-harness env-manifest generate`, routed its parse into
`env.manifest.json` and nowhere else.

**Added**: `dv_harness/env_manifest.py::ingest_rtl_parse_to_evidence_db()`,
called from that command after the manifest is written. It reads
`manifest["dut_facts"]["rtl"]["files"]` — verbatim
`verible_parser.to_dict(parse_file(...))` per file, exactly the shape
`insert_rtl_parse()` documents — so **verible is not re-run and RTL is not
re-parsed**.

**One real defect this wiring exposed and had to solve.**
`insert_rtl_parse()` is deliberately append-only (sequence id +
`parsed_at`, keeping a file's parse history as it really changed), and
`env-manifest generate` is a command engineers re-run routinely against
untouched RTL. Naively connecting the two grows duplicate module/port rows
on every regeneration and corrupts any count query over them — a test
caught this immediately (`assert 2 == 1`). The bridge now skips a file whose
exact `(file_path, source_sha256, verible_version)` parse identity is
already stored: identical bytes parsed by the identical tool cannot yield a
different result. A real RTL edit changes `source_sha256` and genuinely does
append a new parse — both halves of that contract are tested. The dedup
lives in the bridge, not in `insert_rtl_parse()`, because that method's
append-only contract is already relied on and tested elsewhere.

## Placement discipline for both new bridges

Each bridge lives in the module that owns its **producer** — not in
`vip_distill.py` (whose AST-enforced test
`test_module_does_not_import_orchestration_or_memory_modules()` permanently
forbids it importing `evidence_db`, so the store half could never live
there) and not in the store. That is the same placement the two
already-working bridges use:
`regression_reporter._write_normalized_evidence_if_configured()` for
sim.log, `dashboard._ingest_coverage_summary_to_evidence_db()` for
coverage. No new parallel mechanism was introduced.

Both are best-effort with print-and-continue, matching every other
evidence-store write in the project: a missing duckdb, a locked file, or a
disabled store can never fail the real `fsdb-report` or `env-manifest`
run that already produced its real output. `vip_distill`/`evidence_db` are
imported **inside** the functions in `fsdb_report.py` — `vip_distill`
imports `fsdb_report` at its own module scope, so a top-level import back
would be a hard circular import. A test pins that down.

---

## Tests — proving the connection, not the halves

New file: `dv_harness_tests/test_evidence_layer_wiring.py` (13 tests).

Every behavioral test drives the **real production entry point** —
`dv_harness.cli.main()` for the actual `dv-harness fsdb-report` and
`dv-harness env-manifest generate` commands — and then reads a real row back
out of a real DuckDB file with real SQL. None of them re-test either half in
isolation; a test that still passed with the CLI call deleted would prove
nothing about the edge, which is precisely the failure mode that let these
edges stay unwired while both endpoints were "tested".

The strongest of them,
`test_cli_env_manifest_duckdb_rows_agree_with_the_manifest_it_wrote`, asserts
the two destinations of the *same* verible parse against **each other** —
`env.manifest.json` vs. the DuckDB rows, on `module_name`, `file_path`,
`source_sha256`, `verible_version`, ports and signals — a cross-check no
per-side unit test can structurally make.

Also covered: idempotent re-run on both edges; a real RTL edit appending a
genuinely new parse; NULL-preservation for fsdbreport's absent
verdict/counts; `evidence_db.enabled: false` leaving the real run intact and
creating no DB file; a failed `fsdbreport` writing no row rather than a
fabricated "we looked and saw nothing" record; and static assertions that
both bridges have real non-test call sites in `cli.py`.

**What is real vs. substituted, stated in the test module's own docstring**:
verible is REAL (the binary is installed here — real subprocess against a
synthesized minimal `.sv` fixture, never proprietary project RTL, and
skipped rather than faked when absent); DuckDB is REAL (a real
`.dv-harness/evidence/evidence.duckdb` on disk); `vip_distill`,
`fsdb_report` parsing and `evidence_db` are REAL and unmodified. The **only**
substituted piece is the `fsdbreport` binary itself — a proprietary Synopsys
Verdi tool that exists only on the Linux DV server, as `fsdb_report.py`'s own
module docstring already records. Everything downstream of it in the test is
the real code path.

---

## Remaining, deliberately not attempted

**DuckDB read-back for `normalized_evidence` / `rtl_modules` /
`coverage_samples` — NEEDS_SEPARATE_EFFORT.** `dv_harness/mcp/regression_queries.py`
is still hard-scoped to `SELECT ... FROM regression_verdicts` (line 29). So
the rows this commit makes land are written but not yet readable back toward
Debug/RCA or the Memory Agent. The audit itself flagged this as downstream of
this pass's scope, and it is: it is the *consumption* edge of a different
diagram layer, it needs new fixed query shapes designed against the
read-only-verb boundary that `test_mcp_read_only_boundary.py` enforces, and
it needs its own decision about which shapes Debug/RCA actually wants. Not a
wiring fix. Untouched here.

**The pipeline has still never run against real project evidence.**
Re-confirmed: no `.duckdb` file exists in the repo, `.dv-harness/lsf/jobs/`
holds only a `README.md`, and `.dv-harness/lsf/watcher.log` shows
`discover_live_jobs failed: bjobs not found on PATH` with `SUMMARY: Total: 0`
throughout — this machine has no LSF, so `run_reconciliation_cycle()` has
never had a real job to distill here. That is an environment fact, not a code
gap, and it is unchanged by this commit. What changed is that the code paths
are now complete and end-to-end tested, so a real build on the DV server will
actually land rows instead of silently swallowing an `AttributeError`.

---

## Concurrency

Other agents were committing to this repo throughout this pass. `cli.py` was
shared: its diff carried five hunks, only two of them mine. I hand-scoped
them (`git diff` -> trim to my hunks -> `git apply --cached --check` ->
`git apply --cached`) rather than staging the file, and staged the other five
files individually. The final staged diff was exactly 6 files / 761
insertions, all mine. One earlier `git reset` attempt hit another agent's
`index.lock` and was abandoned rather than forced; their subsequent commit
(`a8d97f2`) landed intact, and their remaining in-flight edits to `cli.py`,
`regression_reporter.py`, `engine.py` and others are still uncommitted in the
working tree, untouched.

## Files changed (`ddb8808`)

- `dv_harness/evidence_db.py` — `normalized_evidence` table + `insert_normalized_evidence()` (the uncommitted HEAD-level fix)
- `dv_harness/fsdb_report.py` — `ingest_report_to_evidence_db()`
- `dv_harness/env_manifest.py` — `ingest_rtl_parse_to_evidence_db()`
- `dv_harness/cli.py` — both call sites; `--topic`/`--job-id`/`--pattern` on `fsdb-report`
- `dv_harness_tests/test_evidence_db.py` — 5 tests for the committed schema/method
- `dv_harness_tests/test_evidence_layer_wiring.py` — new, 13 connection tests
