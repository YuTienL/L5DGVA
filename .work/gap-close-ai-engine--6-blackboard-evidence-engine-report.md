# Gap close — AI mechanism #6: Blackboard / Evidence Engine

**Verdict: DONE.**

Two real, concrete gaps named by the 2026-09-04 re-audit were closed for real in
`v50/`. The core mechanism itself was confirmed WIRED_AND_FIRING by re-reading the
cited evidence; nothing about the core write/read path was rebuilt or duplicated.

**Test summary:** the new
`dv_harness_tests/test_blackboard_automatic_path_and_concurrency.py` is 19 passed across
4 runs (stable); with `test_blackboard_subsystem_wiring.py` alongside it, **39 passed** on
the committed tree. Wider regression: the Blackboard/subsystem suites ran 177 passed / 2
failed and the engine suites (`test_engine_gates_and_routing.py`,
`test_graph_parallel_dispatch.py`, `test_harness_reliability.py`,
`test_active_stages_read_sites.py`, `test_stage_progress_display.py`,
`test_execution_preflight_wiring.py`, `test_multi_agent_timing.py`) ran 343 passed / 3
failed — every one of those 5 failures re-run green afterwards and none is this pass's;
see "Failures seen during regression" below.

---

## What I re-verified before changing anything

- `v50/dv_harness/blackboard.py` really is the whole mechanism (95 lines pre-change);
  `write()` was `p.write_text(json.dumps(...))` with `tempfile` imported on line 2 and
  used nowhere in the file.
- `engine.py:_advance_with_fanout()` really runs branches through a genuine
  `ThreadPoolExecutor`, and the `AgentTaskStore.acquire()` claim above it only guards
  same-topic collisions between fan-out branches, not the file operation.
- `engine.py` really had **zero** references to `env_manifest` / `question_queue` /
  `connectivity_check`; the real graph really does declare the three subsystem topics in
  seven nodes' `blackboard_read` (ARCH_DISCOVERY, PROJECT_MODEL, IMPLEMENT, BUILD_DEBUG,
  VERIFY, FAILURE_RECOVERY, SIGNOFF) and in **no** node's `blackboard_write`.
- `storage._atomic_replace()` and `question_queue._atomic_write_json()` already existed as
  the codebase's own atomic-write utilities — so this was a reuse job, not a new mechanism.

## Fix A — `Blackboard.write()` is atomic, `read()` is resilient

`v50/dv_harness/blackboard.py`

- `write()` now writes to a `tempfile.mkstemp()` file in the topic directory and
  `storage._atomic_replace()`s it into place, `finally` unlinking any survivor. The
  existing utility is **reused, not re-implemented**, so the Windows
  `os.replace()`/PermissionError retry that `state.json` and `decisions.json` already
  depend on covers the Blackboard too.
- `read()` retries `json.JSONDecodeError` / `UnicodeDecodeError` / `PermissionError` for a
  bounded budget (10 attempts, 0.01s escalating backoff), mirroring
  `dashboard._read_json_file()`'s idiom. It still **raises** on a persistently corrupt
  topic and returns `default` only for a genuinely absent one — reporting an unreadable
  topic as absent would present "no verification truth recorded" as a fact.
- `snapshot()` is unchanged and therefore inherits both.

## Fix B — the autonomous path now PRODUCES the three subsystem topics

The audit's Fix B suggested either an `expected_evidence` entry or a prompt instruction.
I used neither: a prompt instruction is prose an LLM is trusted to enact each time, which
CLAUDE.md's own Methodology Consolidation Rule rules out for an AI-architecture decision,
and an `expected_evidence` item flags absence without ever producing anything. Instead the
engine calls each subsystem's **real existing producer**, driven by the graph's own
declarations.

- `dv_harness/engine.py`
  - `SUBSYSTEM_TOPIC_REFRESHERS` — a module-level table (`topic -> real producer`), lazily
    importing each subsystem so engine import stays cheap. A table rather than an if/elif
    chain specifically so a test can hold it against the real `main_graph.json`.
  - `DVHarness._refresh_declared_subsystem_topics(stage, node)` — iterates the node's own
    `blackboard_read` (never a hardcoded stage list), calls the registered producer,
    swallows any exception into a report, and records one `BLACKBOARD_TOPIC_REFRESH` event
    per stage carrying every outcome — including each honest absence and its reason.
  - Called from `run_stage()` **after** the DEGRADED and execution-preflight gates (a run
    making no judgment must not spend a connectivity gate run) and **before**
    `_emit_stage_start_display()` and `_gather_stage_context()`'s
    `blackboard.snapshot(node.blackboard_read)`, so both the human-facing entry checklist
    and the agent's prompt see the refreshed topics.
- `dv_harness/env_manifest.py` — `default_manifest_path()` (resolved through
  `context_budget`'s tier-2 always-resident declaration, the one place that owns that path,
  the same source `mcp/claude_md_index.manifest_rel_path()` uses) and
  `ensure_blackboard_topic()`, which **mirrors** an existing `env.manifest.json` via the
  existing `sync_to_blackboard()`. It never generates one: generation needs RTL /
  register-map / SoC-arch / testplan inputs the engine does not have, and inventing a
  manifest is exactly the fabrication the manifest's honesty contract forbids. No manifest
  → topic stays absent, `MANIFEST_NOT_GENERATED` + the real producing command is recorded.
  A schema-invalid manifest reports `MANIFEST_INVALID` and is not mirrored.
- `dv_harness/question_queue.py` — `QuestionQueueStore.ensure_blackboard_topic()`, which
  mirrors `decisions.json` through the existing single `_sync_decisions_to_blackboard()`
  choke point and writes no decision. Answering stays human-only ("由真人執行"); what this
  closes is that an EMPTY decision set is itself citable truth, distinct from "no record".
- `dv_harness/connectivity_check.py` — `ensure_blackboard_topic()`, which runs the **real**
  `run_connectivity_check()` 3-gate recipe (a real gate run is this topic's only producer,
  so no second value-shape writer was created) using the **existing** staleness trigger:
  never run, RTL fingerprint moved, or topic absent. This is the missing "`just
  connectivity-check`, not `--check-only`, on the real automated flow" step. Unchanged RTL
  costs nothing; no `.dv-harness/connectivity_check.json` → `NOT_CONFIGURED`, which is what
  this harness repo itself honestly is.

Every refresh is best-effort — the same discipline the three sync functions already apply
to their own writes — and can never fail a stage.

## Tests

`v50/dv_harness_tests/test_blackboard_automatic_path_and_concurrency.py` (19 tests, new).

Part A runs a `ThreadPoolExecutor` harness shaped like `_advance_with_fanout()`'s real
usage, and is deliberately **three-way** so the positive results have detection power:

1. a control `_NonAtomicBlackboard` (the pre-fix truncate-then-write, window widened to a
   deterministic 5ms) really does produce `JSONDecodeError`s under an unretried reader —
   without this, "no torn reads" would be indistinguishable from a test that never looked;
2. the real writer, under **identical** load, produces none;
3. the real `read()`, against that same non-atomic writer, survives with zero errors.

Plus: no temp files left behind; a write that dies mid-serialization leaves the previous
value intact; a permanently corrupt topic still raises rather than reading as absent;
`snapshot()` inherits the same behavior.

Part B drives the **real** `DVHarness.run_stage()` against the **real** shipped
`main_graph.json` — which is exactly what `test_blackboard_subsystem_wiring.py` cannot
show, because every test there invokes the CLI/runner itself:

- IMPLEMENT produces `open_questions_decisions` with **no CLI invoked**;
- ARCH_DISCOVERY mirrors an on-disk manifest into `env_manifest` with no CLI invoked;
- VERIFY runs the real 3 gates and produces `connectivity_gates`, cross-checked against the
  runner's own state file and report;
- the refreshed topics are present in the `blackboard.snapshot(node.blackboard_read)` that
  reaches the stage prompt;
- INTAKE (declaring none of them) produces none and emits no event — scoping proven;
- an unproducible topic stays absent with the real reason and command in the audit trail;
- a broken producer does not stop the stage;
- gates are not re-run on unchanged RTL, and are re-run with reason `RTL_CHANGED` on a real
  content change;
- graph-coverage guards: every subsystem topic the real graph reads has a registered
  producer, and none of them is written by any node's PASS branch.

## Documentation

`v50/CLAUDE.md`, "Blackboard Topics Written Outside the Graph (2026-09-04)" — two added
paragraphs: the autonomous path now producing all three (with each producer's explicit
limit), and `Blackboard.write()`'s atomicity plus `read()`'s retry, including why a
persistently corrupt topic still raises.

## Failures seen during regression — NOT caused by this pass

**Two schema failures (now fixed by their own workstream).**
`test_blackboard_subsystem_wiring.py::test_env_manifest_topic_agrees_with_the_manifest_and_omits_parse_trees`
and `test_env_manifest.py::test_full_manifest_dut_facts_rtl_layer_round_trips_and_is_schema_valid`
failed with `env_manifest.schema.json validation failed: at dut_facts/rtl/files/0/modules/0:
Additional properties are not allowed ('continuous_assigns', 'instances' were unexpected)`.

Attribution checked mechanically, not assumed: `git show HEAD:dv_harness/verible_parser.py`
contained **zero** occurrences of those keys while the working-tree copy contained them —
an uncommitted concurrent AMBA-fabric-discovery change. That workstream has since committed
a matching `dv_harness/schemas/env_manifest.schema.json` edit, and
`test_blackboard_subsystem_wiring.py` is now green (39/39 with the new file). This pass
touched neither the parser nor the schema, and its `env_manifest.py` change is purely
additive (two new functions, no change to any generation path).

**Three self-audit failures (transient).**
`test_engine_gates_and_routing.py`'s `test_self_audit_against_real_repo_reports_real_current_findings`
and its two `self_audit` CLI siblings failed during a 42-minute run — one `'FAIL' == 'PASS'`
and two `subprocess.TimeoutExpired` after 30s. These drive `dv-harness self-audit` against
the REAL repo, which at that moment had five concurrent workstreams' files mid-write, on
this environment's known-slow subprocess shell. Re-run afterwards: **all 8 `self_audit`
tests pass** (61s). Not a code failure.

## Concurrency discipline in this shared tree

`dv_harness/engine.py` and `CLAUDE.md` both carried another agent's in-flight uncommitted
work at commit time (a stage-progress-display workstream in `engine.py`, a "Research Stage
Boundaries" section in `CLAUDE.md`). Both were committed with hand-scoped `-U0` patches
containing only this pass's hunks, applied through a temporary index so a concurrently
staged AMBA workstream was not swept into this commit. The other agents' work was left
exactly where it was, staged and unstaged.

## Not attempted, and why

Nothing here required a separate effort. Two things were deliberately NOT done:

- **No prompt-text instruction** telling an agent to run `dv-harness env-manifest generate`
  or `just connectivity-check`. Prose an LLM is trusted to enact each time is the failure
  class CLAUDE.md's Methodology Consolidation Rule names; the code path is the fix.
- **No `expected_evidence` gate on the three topics.** They are honestly unproducible in
  some real projects (no RTL tree, no manifest inputs, no human answer yet), so gating on
  presence would block legitimate runs. The absence is instead surfaced twice — the
  pre-existing stage-entry checklist renders a missing `blackboard_read` topic as an unmet
  input, and the new `BLACKBOARD_TOPIC_REFRESH` event records why it could not be produced.
