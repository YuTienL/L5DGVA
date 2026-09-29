# verible --export_json Structured RTL Parsing + DuckDB Evidence Store

**Task scope**: install verible + the DuckDB Python package; build
`dv_harness/verible_parser.py` (real verible `--export_json` structured
parse of a synthesized, minimal .sv fixture) and `dv_harness/evidence_db.py`
(a real DuckDB-backed evidence store with a schema mirroring this project's
own real job/regression/coverage/failure-signature/traceability data
shapes); wire one real, minimal ingestion path; add real tests; report.

Status: **DONE**


## 1. Tool installation (real, verified)

### verible

No `winget` package exists for verible under any name (`winget search
verible`, `winget search "chipsalliance"`, and `winget show google.verible`
all returned "找不到符合輸入條件的套件" / exit 20 — confirmed searched, not
assumed). Verible's own official distribution channel for Windows is a
prebuilt binary attached to its GitHub releases
(`chipsalliance/verible`), so that is the real channel used here:

```
$ curl -sL -o verible.zip \
    https://github.com/chipsalliance/verible/releases/download/v0.0-4163-g6cce8f19/verible-v0.0-4163-g6cce8f19-win64.zip
$ unzip -o -q verible.zip
```

The 11 `verible-*.exe` binaries were copied into
`C:\Users\peter.lin\bin` (already on this machine's `PATH`). Real,
live verification:

```
$ verible-verilog-syntax.exe --version
Version	v0.0-4150-gfe58e708
Commit-Timestamp	2026-08-28T14:44:33Z
Built	2026-08-28T15:30:12Z
```

(the `--version` string differs slightly from the release tag because
verible embeds its own build-time git description of the exact commit that
built that specific binary — both are real, from the same asset).

`--export_json` and `--printtree` were confirmed present in
`verible-verilog-syntax --helpfull` before any code was written against
them, and the exact success/error JSON shapes below were captured from a
real invocation, not assumed from documentation.

### DuckDB

```
$ pip install duckdb
Successfully installed duckdb-1.5.5
$ python -c "import duckdb; print(duckdb.__version__)"
1.5.5
```

This project has no virtualenv (`requirements-harness.txt`: "Core harness
uses Python standard library only"); `duckdb` is now installed into the
one global interpreter this project runs against (`C:\Python314\python`,
Python 3.14.4), the same interpreter `dv-harness`/pytest already use.


## 2. `dv_harness/verible_parser.py`

Real end-to-end entry point: `parse_file(path) -> FileParseResult`, which
shells out to a real `verible-verilog-syntax --export_json --printtree
<path>` subprocess, parses its real JSON output, and walks the real
verible syntax-tree node shape to recover a module/port/parameter/signal
hierarchy. `to_dict()` gives a plain-JSON-serializable form that
`evidence_db.insert_rtl_parse()` consumes directly.

**Real tree shape, confirmed live** (not guessed from docs) against a
synthesized fixture (`module fifo_ctrl` with 2 parameters, 8 ports, 3
module-level signals — never real project RTL, which is proprietary and
lives only on the remote server, per CLAUDE.md's Evidence Truth Rule / No
Golden-Reference Content Mining):

- Success: `{"<path>": {"tree": {"children": [...], "tag": "..."}}}`.
  Every node is a dict; an internal node has a `"children"` list (with
  `null` placeholders for elided grammar slots) and a `"tag"` naming the
  grammar production (`kModuleDeclaration`, `kPortDeclaration`,
  `kDataType`, ...); a leaf has no `"children"`, only `"start"`/`"end"`
  byte offsets and a `"tag"` (a fixed keyword/punctuation leaf's tag IS its
  text, e.g. `tag=="input"`; a variable leaf like `SymbolIdentifier` or
  `TK_DecNumber` carries a separate `"text"`).
- Real syntax error (a deliberately truncated `module broken(\n input
  logic clk\n` fixture): `{"<path>": {"errors": [{"column":0,"line":2,
  "phase":"parse","text":"<EOF>"}]}}`, **no `"tree"` key at all**, nonzero
  exit code.

The extractor recovers parameter/port/signal type and dimension text by
slicing the **original source text** at a subtree's own recursively
computed (min-start, max-end) span, rather than re-deriving it from the
expression grammar — robust to any expression shape verible's grammar
allows (e.g. a parameterized `[WIDTH-1:0]` packed range, or a
`kFunctionCall`-shaped `[DEPTH-1:0]` unpacked array bound) without this
module modeling SystemVerilog expression syntax itself.

Module-level signal scope is deliberate: only `kModuleItemList`'s **direct**
`kDataDeclaration` children are surfaced, never anything nested inside a
procedural block (`always_ff`/`always_comb`/`initial`) — that is exactly
what "signal hierarchy" means at this module's scope, per the task's own
"module/port/signal hierarchy" wording.

**Two real bugs found and fixed via the test suite** (both would have
silently produced wrong data, not a loud failure — worth stating plainly):

1. The parameter-list container's real tag is `kFormalParameterList`, not
   the plausible-but-wrong `kParamDeclarationList` first guessed — caught
   immediately because the first test run genuinely returned an empty
   `parameters` list for a fixture with two real parameters.
2. **CRLF byte-offset drift** (Windows-specific, would have silently
   corrupted every type-text/dimension-text extraction on any file saved
   with `\r\n` line endings — which is the default for `Path.write_text()`
   on Windows without `newline=""`): verible's `start`/`end` offsets are
   raw byte offsets into the file **exactly as it sits on disk**, `\r`
   included. Python's default text-mode read applies universal-newline
   translation (`\r\n` -> `\n`), silently shortening the in-memory string
   by one character per preceding line — every span-based slice past the
   first affected line then drifts by a growing offset. Concrete confirmed
   symptom before the fix: `ports_by_name["clk"].data_type` came back as
   `"c    "` instead of `"logic"`. Fixed by reading the source with
   `newline=""` in `parse_file()` so the in-memory string stays
   byte-for-byte aligned with verible's own offsets regardless of the
   file's line-ending convention. All 11 tests in
   `test_verible_parser.py` were red before this fix and are green after.

Real parse output for the fixture (`fifo_ctrl`, via `to_dict()`):

```json
{
  "modules": [{
    "name": "fifo_ctrl",
    "parameters": [
      {"name": "DEPTH", "type_text": "int", "default_text": "16"},
      {"name": "WIDTH", "type_text": "int", "default_text": "8"}
    ],
    "ports": [
      {"name": "clk", "direction": "input", "data_type": "logic"},
      {"name": "wr_data", "direction": "input", "data_type": "logic [WIDTH-1:0]"},
      {"name": "rd_data", "direction": "output", "data_type": "logic [WIDTH-1:0]"},
      "... 5 more ports ..."
    ],
    "signals": [
      {"name": "mem", "data_type": "logic [WIDTH-1:0]", "unpacked_dims": "[0:DEPTH-1]"},
      {"name": "wr_ptr", "data_type": "logic [3:0]", "unpacked_dims": null},
      {"name": "rd_ptr", "data_type": "logic [3:0]", "unpacked_dims": null}
    ]
  }]
}
```


## 3. `dv_harness/evidence_db.py`

A DuckDB-backed evidence store at `.dv-harness/evidence/evidence.duckdb`
(mirroring the project's existing `.dv-harness/lsf`, `.dv-harness/memory`
dot-dir convention). Every table mirrors a **real** data shape already
produced elsewhere in this codebase — read in full before designing this
schema, not invented:

| Table | Mirrors (real source, read first) |
|---|---|
| `jobs` | `lsf_client.JobState` — every field, 1:1 (the real per-job on-disk state `.dv-harness/lsf/jobs/<id>.json` already holds) |
| `job_memory_records` | the real `kind in ("job_result","job_failure")` record dict `lsf_client._upsert_job_tier_memory_record()` builds and routes through `memory_router.route_and_store()` |
| `failure_signatures` | the real dict `memory_vault.build_failure_signature()` returns, aggregated by a stable SHA-256 of that dict so a recurring failure shape accumulates one row (`occurrence_count`/`first_seen`/`last_seen`) instead of one row per occurrence |
| `regression_verdicts` | the real one-pattern-per-line PASS semantics of `uvm_generator.regression_list_manager.record_verdict()`/`apply_verdict_to_file()` — a queryable mirror of `regression.list`, gaining a real `recorded_at` the flat file has no room for |
| `coverage_samples` | the real per-category shape `coverage_analysis.parse_coverage_summary()` validates (`name`/`percent`/`bins_total`/`bins_hit`) plus `append_history_sample()`'s real `timestamp` field |
| `rtl_modules` / `rtl_ports` / `rtl_signals` / `rtl_parameters` (traceability) | `verible_parser.FileParseResult`/`ModuleInfo`/`PortInfo`/`SignalInfo`/`ParamInfo` — the real structured output of §2 above |

Deliberately **not** built: a full ETL pipeline, a generic catch-all
"events" table, or any speculative column with no real producer in this
codebase today.

**Real bug found and fixed while proving the ingestion path**: DuckDB's
`INSERT ... ON CONFLICT (...) DO UPDATE SET col = current_timestamp`
raises `BinderException: Table "..." does not have a column named
"current_timestamp"` — DuckDB's parser treats the bare `current_timestamp`
keyword as a column reference inside a `DO UPDATE SET`/`ON CONFLICT`
`VALUES` clause specifically (confirmed via a minimal reproduction outside
this module), even though the identical keyword works fine as a plain
`INSERT` value or a `DEFAULT` clause. Fixed by using `now()` (an
unambiguous function call) everywhere in this module instead — every
`DEFAULT`/upsert timestamp now uses `now()`.

**Real ingestion path proven end to end** (not a full ETL — one real
record of each shape, inserted, then read back and re-inserted to prove
upsert/aggregation semantics):

```python
from dv_harness.evidence_db import EvidenceStore
from dv_harness.lsf_client import JobState
from dv_harness.verible_parser import parse_file, to_dict

store = EvidenceStore(".dv-harness/evidence/evidence.duckdb")
store.insert_job_state(JobState(job_id=123456, pattern="usb3_lfps_basic",
                                 lsf_status="EXIT", sim_status="FAIL",
                                 uvm_error_count=3, uvm_fatal_count=1, ...))
store.insert_job_memory_record({  # the real lsf_client job_failure shape
    "memory_id": "JOB-123456-TERMINAL-RECONCILE", "kind": "job_failure",
    "job_id": 123456, "failure_signature": {...}, ...
})
store.insert_regression_verdict("usb3_lfps_basic", False, job_id=123456)
store.insert_coverage_sample({"name": "fsm_state", "percent": 60.0,
                               "bins_total": 10, "bins_hit": 6})
store.insert_rtl_parse(to_dict(parse_file("fifo_ctrl.sv")))
```

Verified real read-back (excerpted from the actual run):

```
jobs               [(123456, 'usb3_lfps_basic', 'EXIT', 'FAIL', 3)]
job_memory_records [('JOB-123456-TERMINAL-RECONCILE', 'job_failure', 123456, True)]
failure_signatures [('eb494634...', 2, 'usb3_lfps_basic', True)]   # occurrence_count=2 after 2 inserts
regression_verdicts[('usb3_lfps_basic', False, 123456)]
coverage_samples   [('fsm_state', 60.0, 10, 6, 'urg_merge')]
rtl_modules        [(1, 'fifo_ctrl', '...fifo_ctrl.sv')]
rtl_ports          8 rows (clk/rst_n/wr_data/wr_en/rd_data/rd_valid/full/empty)
rtl_signals        [(1, 'mem', 'logic [WIDTH-1:0]', '[0:DEPTH-1]'), (1, 'wr_ptr', ...), (1, 'rd_ptr', ...)]
rtl_parameters     [(1, 'DEPTH', 'int', '16'), (1, 'WIDTH', 'int', '8')]
```


## 4. Tests

`dv_harness_tests/test_verible_parser.py` (11 tests) and
`dv_harness_tests/test_evidence_db.py` (21 tests), all real (no mocked
subprocess, no mocked DuckDB connection):

```
$ python -m pytest dv_harness_tests/test_verible_parser.py dv_harness_tests/test_evidence_db.py -v
...
11 passed  (test_verible_parser.py)
21 passed  (test_evidence_db.py)
```

`verible`-dependent tests are guarded with
`@pytest.mark.skipif(shutil.which("verible-verilog-syntax") is None, ...)`
so this suite degrades to an honestly-reported skip (never a fabricated
pass) on a machine without verible on `PATH`; `duckdb`-dependent tests use
`pytest.importorskip("duckdb")` the same way. On this machine, with both
tools genuinely installed, every test actually ran (none skipped).

Full-suite import safety was also checked (this task only *added* two new
files, touching nothing else): `python -m pytest --collect-only -q` still
collects the project's full **2277** tests with no collection errors.


## 5. Scope boundaries respected

- No real project RTL was used anywhere — only a synthesized, minimal,
  valid `fifo_ctrl` fixture (a small FIFO controller with parameters,
  8 ports, a memory array, and pointer registers), per CLAUDE.md's
  Evidence Truth Rule and No Golden-Reference Content Mining.
- No full ETL pipeline was built — `evidence_db.py` exposes exactly one
  insert function per real record shape, proven with one real sample each,
  not a scheduled/triggered ingestion pipeline.
- Nothing under `dv_harness/memory_vault.py`, `memory_security.py`,
  `memory_dedup.py`, `memory_doctor.py`, or `session_snapshot.py` was
  touched, per the controller's explicit instruction that this is fresh,
  already-reviewed work from the same session.
- Files this task actually modifies: `dv_harness/verible_parser.py` (new),
  `dv_harness/evidence_db.py` (new),
  `dv_harness_tests/test_verible_parser.py` (new),
  `dv_harness_tests/test_evidence_db.py` (new), and this report. Nothing
  else in the working tree was touched by this task, confirmed via
  `git status --short` immediately before committing — every other
  pending change in the working tree belongs to other concurrent
  workstreams (lmstat/scheduler preflight, gh CLI governance, vip_distill,
  etc.) from the same overall spec, none of it altered here.


## 6. What a future task should build on this (not built here, out of scope)

- No caller in the real engine flow (`engine.py`/`regression_reporter.py`)
  yet calls `evidence_db.insert_job_state()`/`insert_job_memory_record()`
  automatically on a real reconcile cycle — this task proves the ingestion
  path works with real sample data, it does not wire it into the live
  reconciliation loop. A future task should decide where in
  `regression_reporter.run_reconciliation_cycle()` /
  `lsf_client._upsert_job_tier_memory_record()` a real `EvidenceStore`
  write belongs, alongside the existing JSON-file writes (additive, not a
  replacement — the JSON files remain this project's real source of
  truth per its existing Working/Job/Engineering memory-tier design).
- No CLI subcommand (`dv-harness evidence-*`) was added — out of this
  task's stated scope ("a real, minimal ingestion path ... do not build a
  full ETL pipeline").
