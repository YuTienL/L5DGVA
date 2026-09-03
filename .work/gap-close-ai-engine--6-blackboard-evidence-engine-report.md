# Gap close — AI mechanism #6: Blackboard / Evidence Engine

**Verdict: DONE** (integration gap closed; the core mechanism needed no change)

Date: 2026-09-04. Scope: mechanism #6 only.

---

## 1. Re-verified the audit's evidence before touching anything

The audit's line numbers had shifted (engine.py is concurrently edited), so the code path was
re-located by grep rather than trusted:

- `dv_harness/engine.py:3196-3197` — inside `run_stage()`'s real PASS branch:
  `if node is not None and node.blackboard_write: self._write_blackboard_from_evidence(node, stage, evidence_blocks, result)`.
- `dv_harness/engine.py:2281` — `_write_blackboard_from_evidence()`, dispatching through
  `STAGE_BLACKBOARD_WRITERS` (engine.py:283) with `_bb_generic_fallback` for unmapped stages, and
  calling `self.blackboard.write(topic, value, source=stage)` per declared topic.
- `dv_harness/blackboard.py` — `write`/`read`/`snapshot` plus the findings registry
  (`upsert_finding`/`findings_counts`) and debug-loop history, all with real engine callers.
- Persisted evidence under `.dv-harness/blackboard/` (project/environment/hierarchy/
  protocol_inventory) with real stage `source` values.

**The Blackboard mechanism itself is WIRED_AND_FIRING and was not modified.**

The named gap also re-confirmed: `grep -n "env_manifest|question_queue|connectivity" dv_harness/engine.py`
returns nothing, and no node in `.dv-harness/graph/main_graph.json` declared any topic those
subsystems could write.

**One audit claim was stale and is corrected here (Evidence Truth Rule).** The audit said
`connectivity.py`'s gate evaluators have "zero real callers outside their own test file". That is
no longer true: a concurrent 2026-09-04 workstream landed `dv_harness/connectivity_check.py`, a
real standing runner wired to `just connectivity-check` / `connectivity-check-status` and to
`.github/workflows/dv-harness-ci.yml`, which calls `connectivity.run_machine_gates()` for real.
The audit's stated prerequisite for item 2 was therefore already satisfied, so that item was
closed in this pass rather than deferred.

## 2. What changed

Three write edges plus the reader half of each. Every write goes through the **existing**
`Blackboard.write()` on an **existing** real production entry point — no parallel mechanism, no
new store, no new engine hook.

| Topic | Written by (real entry point) | `source` |
|---|---|---|
| `env_manifest` | `dv-harness env-manifest generate` → `env_manifest.sync_to_blackboard()` | `env-manifest` |
| `open_questions_decisions` | `QuestionQueueStore._save_decisions()` (every decision write + every revocation) | `question_queue` |
| `connectivity_gates` | a real `just connectivity-check` gate run → `connectivity_check.sync_gates_to_blackboard()` | `connectivity-check` |

**`dv_harness/env_manifest.py`** — added `BLACKBOARD_TOPIC`, `summarize_for_blackboard()`,
`sync_to_blackboard()`. Deliberately a SUMMARY, not the manifest verbatim: the topic is serialized
into every reading stage's prompt by `engine._build_plan_section`, and `dut_facts.rtl.files` holds
the full per-module verible parse. Each layer's own `status`/`reason`/`source` survives verbatim
(a NOT_AVAILABLE stays NOT_AVAILABLE with its real reason, never a bare empty list that reads like
"captured, and there was nothing"); names and counts are added; parse trees are not.

**`dv_harness/question_queue.py`** — added `BLACKBOARD_TOPIC`, an injectable `blackboard`
constructor argument, and `_sync_decisions_to_blackboard()` called from `_save_decisions()`. That
is the single choke point `_persist_decision()` and `revoke_decision()` both already pass through,
so the topic cannot drift from `decisions.json` the way a second hand-called write could. Per-entry
`source` is preserved so a Tier-2 auto-assumption stays distinguishable from a real human answer.

  *Design correction made mid-pass:* the audit's plan implied injecting a board at the call site.
  Grep found **five** real production construction sites (`cli.py`, `connectivity.py` x2,
  `coverage_analysis.py`, `uvm_generator/run_profile_to_justfile.py`), only one of which this pass
  would have touched. A mirror the other four had to remember to switch on is the same
  "built but never wired" gap being closed, so the mirror **defaults ON** — omitting the argument
  resolves to a real `Blackboard` at the store's own project root, constructed lazily so merely
  constructing a store creates no directories.

**`dv_harness/connectivity_check.py`** — added `BLACKBOARD_TOPIC` and
`sync_gates_to_blackboard()`, called from inside `run_connectivity_check()`'s `if write:` block.
Each gate's `GateStatus` **value** is recorded (PASS / FAIL / NOT_AVAILABLE / PENDING /
NOT_YET_RUN stay five distinct states, never collapsed to a bool — CLAUDE.md requires
NOT_AVAILABLE and PENDING never be conflated with FAILED), together with the RTL fingerprint they
ran against. `--check-only` runs no gate and deliberately does **not** refresh the topic, so stale
verdicts can never look freshly produced.

**`dv_harness/cli.py`** (hand-scoped edits; file was already `M` from concurrent work) — the
`env-manifest generate` branch now calls `sync_to_blackboard`, and `question-queue` constructs its
store with the real `h.blackboard`.

**`.dv-harness/graph/main_graph.json`** — the reader half. A topic nothing reads is half an edge.
7 nodes gained a `blackboard_read` entry (diff is 7 changed lines, nothing else):

- `env_manifest` → `ARCH_DISCOVERY`, `PROJECT_MODEL`, `IMPLEMENT`
- `connectivity_gates` → `BUILD_DEBUG`, `VERIFY`, `SIGNOFF`
- `open_questions_decisions` → `IMPLEMENT`, `FAILURE_RECOVERY`, `SIGNOFF`

**`CLAUDE.md`** — new "Blackboard Topics Written Outside the Graph (2026-09-04)" section
documenting the three topics, their sources, their honesty contracts and their readers.

All three writes are best-effort: a blackboard failure must never turn an already-written manifest,
an already-recorded decision, or an already-completed gate run into a failed command.

## 3. Tests

New: `dv_harness_tests/test_blackboard_subsystem_wiring.py` (20 tests). These deliberately do not
re-test any subsystem's internals — those already had suites and were never the gap. Every test
drives a REAL production entry point (`dv_harness.cli.main()` for the two CLI commands,
`connectivity_check.main()` for the runner) and asserts a real `.dv-harness/blackboard/<topic>.json`
exists on disk with a real `source`. The graph tests assert against the REAL shipped
`.dv-harness/graph/main_graph.json` (a fixture graph would pass while the shipped one stayed
unwired), and one test exercises `Blackboard.snapshot(node.blackboard_read)` — the exact call
engine.py makes to put a topic into a stage's prompt.

Notable coverage beyond "the file appears": NOT_AVAILABLE reasons survive; the topic is
cross-checked against the manifest/decisions.json the same run wrote (not against a hand-written
expectation); verible parse trees are asserted ABSENT from the topic; re-generation refreshes
rather than leaving a stale snapshot; a revoked decision disappears; a Tier-2 assumption stays
distinguishable from a human answer; `--check-only` and `write=False` write nothing.

**Negative check (the point of the pass).** With the three sync call sites temporarily disabled
(`cli.py`'s `sync_to_blackboard`, `_save_decisions`'s `_sync_decisions_to_blackboard`,
`run_connectivity_check`'s `sync_gates_to_blackboard`) and restored programmatically,
**14 of the 20 tests fail**. The 6 that still pass are exactly the ones that should be independent
of those lines: the 4 graph-declaration/pinning tests, the `write=False` test, and the
"constructing a store creates no directories" test. So these tests measure the edge, not the
isolated functions.

**Test summary — everything relevant passes.**
- `dv_harness_tests/test_blackboard_subsystem_wiring.py`: 20 passed.
- Every suite covering a touched module: `test_env_manifest`, `test_question_queue`,
  `test_cli_question_queue`, `test_connectivity`, `test_connectivity_check`, `test_cli_blackboard`,
  `test_evidence_layer_wiring`, `test_mcp_env_manifest_integration`, `test_bind_verification_lint`,
  `test_bind_mechanism_generator`, `test_coverage_analysis`, `test_run_profile_to_justfile`, and
  `test_source_authority` (a sixth `QuestionQueueStore` construction site landed from a concurrent
  workstream mid-pass and is covered by the default-on mirror): 336 + 266 + 55 passed, 0 failed.
- `dv_harness_tests/test_engine_gates_and_routing.py` in full — the suite that exercises the real
  graph and the real-repo self-audit, i.e. the one most exposed to the `main_graph.json` edit:
  238 passed, 1 flake (below).
- Both CI steps that could see the graph change: `dv-harness self-audit` exit 0,
  `python -m dv_harness.connectivity_check --check-only` exit 0 (NOT_CONFIGURED — this repo has no
  RTL tree).

**Full-suite runs and the failures in them, all attributed, none from this change.** Two full
`dv_harness_tests` runs (3348 tests) were driven to 73% and 60% before being stopped; a complete
run takes ~100 min on this loaded machine. Every failure seen in either run was identified and
attributed:

- `test_cli_pueue.py` (5-6) and `test_pueue_client.py::TestRealPueueIntegration` (6) — a
  machine-level environment condition, not code. `dv-harness pueue add` returns
  `{"error": "PUEUED_NOT_AVAILABLE"}` and probing directly gives `Failed to connect to the daemon
  on 127.0.0.1:6924`. A `pueued.exe` IS running but wedged, with ~28 orphaned `pueue.exe` clients
  piled up from today's concurrent usage. The suites' skip guard only checks that the `pueue`
  BINARY exists, not that the daemon answers, so an unreachable daemon fails instead of skipping.
  Worth fixing separately (restart `pueued`, reap the orphans, widen the skipif to probe the
  daemon); nothing in this change touches pueue.
- `test_engine_gates_and_routing.py::test_self_audit_against_real_repo_reports_real_current_findings`,
  `test_cli_remote_control.py::test_bootstrap_lands_on_running_and_is_idempotent_safe`,
  `test_git_hooks_e2e.py::...test_agent_push_to_master_is_blocked_by_git_itself` — all three are
  real-subprocess tests that **pass cleanly when re-run without other pytest processes competing**
  (verified individually). The first fails on `test_collection_health_gate` == FAIL, and that gate
  shells out to `pytest --collect-only`; querying it directly right now returns
  `{"status": "PASS"}`. These are load/contention flakes in a tree several workstreams are editing
  concurrently, not regressions.

## 4. Deliberately NOT done in this pass

The audit's framing of the MCP server (`dv_harness/mcp/`) as "heavily used" is not supported by
evidence — it has no `cli.py` command, no `.mcp.json`, no launcher, and no caller outside
`dv_harness_tests/`. Giving it a blackboard edge would be wiring a dormant server to a live
channel, which is the wrong order of operations. **Making the MCP server actually runnable is a
separate effort** and is not a Blackboard problem: it needs a real entry point (launcher +
`.mcp.json` registration + a `dv-harness mcp-serve` command) decided on its own merits first. Only
after it has a real caller does a `get_topology`-sourced blackboard topic mean anything.

## 5. Follow-up noted, not a defect

A concurrent workstream is expanding `env_manifest.py` in the working tree right now (adding
`vip_config.vip_release`, `vip_config.user_guide_refs`, `dut_facts.address_map`,
`dut_facts.clock_reset`). `summarize_for_blackboard()` names the fields it mirrors explicitly, so
those new layers simply do not appear in the `env_manifest` topic yet — a graceful degrade, not a
break: the 20 wiring tests were re-run against that in-flight version and all pass. Whoever lands
those layers should add them to the summary (and only the names/counts/status, per the
prompt-size rule this function documents). Deliberately not done here, because extending a
summary against an uncommitted moving target would conflict with their pass.
