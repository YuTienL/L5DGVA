# Gap-close report — Phase 11 (Regression Integration) + Phase 12 (Large Artifact Policy) + Phase 19 (Security)

**Status: DONE**

Execution mode: LOCAL_ANALYSIS + local implementation/test. No remote/LSF/VCS
execution was attempted; every LSF-driven test drives the real production code
path with `bjobs` mocked only at the `_run_bjobs()` subprocess-wrapper
boundary.

Test summary: `26 passed` in the new
`dv_harness_tests/test_memory_write_guard_and_job_evidence.py`, plus every
suite that touches a memory write, all green after the final refactor —
`test_engine_gates_and_routing.py` (239), the memory/vault/react/knowledge set
(187), `test_lsf_client.py` + `test_regression_reporter.py` (106),
evidence/vip/tier/cli-memory (84), doctor/security/tier (56), debug-flow (44).

**The one full-suite failure I did not cause, verified rather than assumed:**
`test_cli_pueue.py` (5 tests) fails here because the pueue *daemon* is not
running — a direct `python -m dv_harness.cli … pueue add …` returns
`{"error": "PUEUED_NOT_AVAILABLE"}` (exit 1), and that file's `pytest.mark.skipif`
guard only checks for the `pueue` *binary*, not a live `pueued`. It references
no memory API at all. Three other failures seen mid-run
(`test_context_budget.py`, `test_protocol_router.py`,
`test_regression_reporter.py::TestWatcherLifecycle`) were transient states of
other workflows' in-flight edits and now pass on re-run.

---

## 1. Phase 19 — reject-by-kind sub-part: **READY, re-confirmed, no change**

Re-verified myself, not taken on trust:

- `dv_harness/memory_router.py:576-577` — `route_memory()` returns `"REJECT"`
  for `kind in ("credential","password","token","secret")`.
- `dv_harness/memory_router.py:125-126` — `route_and_store()` raises
  `ValueError("route_memory: record rejected (credential/secret-like kind),
  not persisted")` before any store is touched.

(The audit cited `memory_router.py:473-474`/`111-112`; the mechanism is
identical, the file has since grown — current line numbers above.)

## 2. Phase 19 — content-level secret redaction: **BLOCKED → BUILT**

The audit's finding reproduced exactly: `dv_harness/memory_security.py`'s real
detector was wired only into the Markdown *mirror*
(`memory_vault.FileSystemMarkdownAdapter.create()/update()`), and
`dv_harness/memory.py` contained zero references to it. Every record write
lands in the durable JSON store first — and `WORKING_MEMORY` (every react-loop
reasoning step) is excluded from the vault mirror by design
(`memory_router._VAULT_WRITE_THROUGH_DESTINATIONS`), so it was scanned by
nothing, ever.

Built:

- `memory_security.redact_record()` (new) — recursive redaction over a JSON
  memory record, returning `(redacted_copy, findings)` with a dotted
  `field` path (`prior_related_knowledge[0].frontmatter.summary`) per finding.
  Recursion is required, not decorative: this repo's real records nest
  free-text several levels down (`prior_related_knowledge` is a list of dicts,
  `evidence` is caller-supplied, working-memory hypotheses are prose).
  `_RECORD_SKIP_KEYS` protects structural/identity fields — notably
  `memory_id`/`ccl_id`, which a license-key-shaped id would otherwise get
  rewritten by, breaking every upsert/index/vault-note id keyed on it.
- `memory._guard_record_before_write()` (new) — called from **both**
  `MemoryStore.add()` (`memory.py:200`, covering all five tiers) and
  `CornerCaseLibrary.add()` (`memory.py:613`, a separate file store that
  bypasses MemoryStore *and* is pushed to the shared cross-user Knowledge
  Center via `_SHAREABLE_DESTINATIONS`). Stamps `secrets_redacted` /
  `secrets_redacted_types` onto the record when anything matched.
- Ordering is deliberate and tested: **redact first, then bound size** —
  truncating first can split a multi-line SSH PEM block so its BEGIN/END-anchored
  pattern no longer matches, leaving real key material in the surviving text
  (`test_secrets_are_redacted_before_truncation_not_after`).

## 3. Phase 12 — write-time size/content gate: **PARTIAL → COMPLETED**

New module `dv_harness/memory_artifact_policy.py` — Phase 12's policy in one
place, enforced at write time rather than only by writer discipline plus
`memory_doctor`'s post-hoc scan (which only ever walked the Markdown vault tree
and structurally could not see `.dv-harness/memory/**/*.json`).

Two deliberately different severities:

- **Hard reject** (`EmbeddedArtifactError`, nothing written) for content that
  can only be a raw dump: a NUL byte, or `$enddefinitions` + `$dumpvars`
  together (a VCD body). Truncating those would just keep a smaller piece of a
  violation.
- **Truncate and record** for oversized free text (`MAX_RECORD_FIELD_CHARS`
  8000 / `MAX_RECORD_FIELD_LINES` 200) — a pasted sim.log is legitimate content
  in the wrong place. Head **and tail** are kept, because a sim.log's UVM
  epilogue (`UVM_FATAL = n` / `VERDICT:`) sits at the very end; the middle is
  replaced by an explicit marker naming the policy, and the affected field
  names are stamped on as `large_artifact_truncated`.

`memory_doctor.py` now imports `FORBIDDEN_ARTIFACT_EXTENSIONS` /
`LARGE_FILE_SIZE_BYTES` / `HUGE_LOG_SIZE_BYTES` from that module instead of
keeping its own duplicate list, and its module docstring's stale claim
("Phase 12's forbidden-artifact list … was not yet available as importable
code") was removed and replaced with the real write-time/post-hoc split.

## 4. Phase 12 — `evidence: {sim_log, fsdb, coverage, lsf_job}` shape: **PARTIAL → COMPLETED, with one disclosed boundary**

`memory_artifact_policy.build_evidence_reference()` is the one shared builder
for that spec-named block. It accepts **paths and ids only** and raises
`EmbeddedArtifactError` on a multi-line or content-sized value — so handing it
a log *body* instead of a log *path* fails loudly rather than quietly building
an "evidence reference" that is itself the artifact. Absent keys are omitted,
never written as `None` (the same convention `_upsert_job_tier_memory_record()`
already uses for seed/fsdb_path, so "not captured" is distinguishable from
"captured as null").

Wired into `lsf_client._upsert_job_tier_memory_record()`, so every Job Memory
record now carries `evidence: {sim_log, fsdb, lsf_job, run_dir}`.

**Disclosed boundary (not BLOCKED, and not closeable here honestly):**
`coverage` is not populated, because **no code path anywhere in this repo
records a per-job coverage-database path** — grep-confirmed: the only hits for
`.vdb`/`coverage_db`/`urg` are `memory_doctor`'s forbidden-extension list and
`coverage_analysis.py:5`, which explicitly refuses to fabricate one. The key
stays in `EVIDENCE_REFERENCE_FIELDS` so a future real coverage producer has one
agreed name to write to instead of inventing a second. Writing `coverage: null`
would be exactly the null placeholder this record's own convention forbids.

## 5. Phase 11 — per-job confidence never computed: **PARTIAL → COMPLETED**

Confirmed the audit's finding: `confidence` is a real field of the JSON record,
of the vault-note frontmatter, and a ranking term in
`MemoryRetriever.search()` — and the job-tier write path never set it, so every
Job Memory record ever written carried the literal string `"UNKNOWN"`.

`lsf_client._score_job_memory_confidence()` (new) computes it through
`inference.score_confidence()` — the function CLAUDE.md's Engineering Memory
Policy already names as *the* quantitative confidence input, not a second
scheme. Every input is read off real evidence already on `JobState`:

| input | derivation |
|---|---|
| `independent_sources_count` | how many genuinely different sources agree: a terminal `bjobs` status; a determinate PASS/FAIL `sim_status` (only ever set from a real sim.log epilogue parse); a marker-level signal (UVM_ERROR/UVM_FATAL/assertion/crash/terminal signature) |
| `evidence_refs_verified` | the cited `sim_log` path actually **exists on disk** (real filesystem check) |
| `counter_evidence_count` | `1` when `sim_status == "PASS"` *and* a real failure marker is present — CLAUDE.md's "LSF DONE is not equal to DV PASS" hazard in reverse |
| `multi_agent_consensus_count` | honestly `0` — no multi-agent evidence acquisition happens at this layer |

The result plus its inputs is stored as `confidence_basis`, so the level is
traceable rather than asserted. Both this and the evidence block are built
inside a best-effort `try/except` in `_upsert_job_tier_memory_record()`,
matching the module's existing discipline: its first call site
(`reconcile_batch()`) does not wrap it, so a problem computing an *added*
field must never break an already-completed, already-saved reconciliation — the
core job record is still written either way, and an omitted confidence falls
back to `MemoryStore.add()`'s honest `"UNKNOWN"` default rather than a
fabricated level. Proven on the real path: a fully-evidenced
FAILED job scores 8 → `HIGH`; a bare bjobs-only terminal status scores 2 →
`LOW`; a swept-away sim.log path scores `evidence_refs_verified: False`; a
`VERDICT: PASSED` epilogue that also declares `UVM_FATAL = 1` scores 5 →
`MEDIUM`.

## 6. Phase 11 — no per-job view carried the spec's nine columns: **PARTIAL → COMPLETED**

Confirmed: `failure_signature`/`prior_related_knowledge` lived only inside the
JOB_MEMORY JSON record and were surfaced by no per-job view (grep-confirmed
zero hits in `regression_reporter.py`/`dashboard.py`/`cli.py`).

- `lsf_client.job_tier_memory_id()` / `JOB_TIER_MEMORY_ID_TEMPLATE` — the
  deterministic id now has one definition instead of an inline f-string at the
  writer and a re-spelling at every reader.
- `lsf_client.load_job_tier_memory_record()` — read-only, best-effort join
  source; a project with no memory store yet returns `None` rather than
  breaking a snapshot.
- `lsf_client.format_failure_signature()` — one-line rendering of a
  `build_failure_signature()` dict for the table (`EXIT/FATAL=1/ERR=5`).
  Deliberately **not** `evidence_db.signature_key()`: that is a sha256 dedup
  key, unreadable to the engineer reading the table.
- `lsf_client.to_snapshot_row(..., job_memory=...)` — optional; without it the
  row keeps its exact pre-existing eight keys (asserted by a test).
- `regression_reporter.attach_job_memory_columns()` + a widened
  `render_snapshot()` — the periodic regression table now carries
  **Confidence / Failure Signature / Prior** alongside
  Job / Pattern / LSF / DV Analysis / UVM_ERR / UVM_FATAL / Agent Action.
  A job with no memory record renders `-` ("not computed"), never a fabricated
  level. Wired at both real render sites (`run_reconciliation_cycle()` — joined
  *after* both memory writers have run this cycle — and `_run_one_cycle()`'s
  no-vcuser fallback).

Real rendered output from `test_a_pass_verdict_contradicted_by_a_fatal_marker_caps_confidence`:

```
Job        Pattern / Combination    LSF    DV Analysis  UVM_ERR  UVM_FATAL  Confidence  Failure Signature  Prior  Agent Action / Note
903        usb_lfps                 EXIT   PASS         0        1          MEDIUM      EXIT/FATAL=1       0      monitoring
```

## 7. Sub-items left as-is (correct already)

- Phase 11's `job_result`/`job_failure` routing, the deterministic upsert key,
  the second (epilogue-parse) call site, and the "Debug Agent must always
  re-verify" property (`search_related_memory_for_debug()` is read-only and no
  code path copies a prior fix into a new job's record) — all re-confirmed
  real, unchanged.
- Phase 12's path-only `JobState.sim_log`/`fsdb_path`, `sim_log_analysis`'s
  count+signature extraction, `vip_distill`/`evidence_db`'s
  reference-plus-condensed-evidence shape, and `memory_doctor.check_large_files()`
  — all re-confirmed real, unchanged apart from the constants now having one
  home.

---

## Files changed

| file | change |
|---|---|
| `dv_harness/memory_artifact_policy.py` | **new** — Phase 12 policy: write-time record gate, evidence-reference builder, forbidden-artifact list |
| `dv_harness/memory_security.py` | `redact_record()` + `_RECORD_SKIP_KEYS`; module docstring now names both real wiring points |
| `dv_harness/memory.py` | `_guard_record_before_write()`, called from `MemoryStore.add()` and `CornerCaseLibrary.add()` |
| `dv_harness/memory_doctor.py` | imports the shared Phase 12 constants; stale "not yet available as importable code" docstring removed |
| `dv_harness/lsf_client.py` | `_score_job_memory_confidence()`, `job_tier_memory_id()`, `load_job_tier_memory_record()`, `format_failure_signature()`, `to_snapshot_row(job_memory=…)`, `evidence` block on the job record |
| `dv_harness/regression_reporter.py` | `attach_job_memory_columns()`; three new snapshot columns; wired at both render sites |
| `dv_harness_tests/test_memory_write_guard_and_job_evidence.py` | **new** — 26 tests |

Concurrency discipline: `regression_reporter.py` carried another workflow's
in-flight hunk (`_escalate_uvm_fatal_burst_if_needed`'s `regression_tiers`
change), so it was staged via the hand-scoped patch technique
(`git diff` → trim to my four hunks → `git apply --cached --check` → `--cached`),
never a broad `git add`. `CLAUDE.md`, `dv_harness/cli.py`,
`dv_harness/memory_router.py` and `dv_harness/memory_vault.py` were not
modified at all.
