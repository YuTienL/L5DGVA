# Poster-Gap Closing Round 2 — Design

Status: approved for implementation planning (2026-08-31)
Owner: peter.lin / yutien.lin01@gmail.com
Source evidence: `poster-capability-completeness-audit` workflow (22 items),
its corrected re-run for items 3/4/5/23, and the `dv-workflow-image-compliance-audit`
workflow (21 poster PNGs, 311 claims) — all completed 2026-08-31.

## 1. Problem

Two independent audits converged on the same pattern: DV Agent Harness
L5's core engine (inference, gates, graph, blackboard, memory stores,
multi-agent dispatch, ReAct loop) is substantially real and wired, but a
layer of poster/dashboard/doc claims built on top of it has drifted from
or was never grounded in the actual code. This spec closes the 9 items
the user explicitly selected from those findings, per this project's own
governance rule (close confirmed gaps together, not one at a time).

## 2. Goals — the 9 items

1. Live-recomputed stats (agent/skill/iron-rule/graph-node counts) so
   poster/doc numbers can be checked and corrected against a canonical
   source going forward.
2. Real interactivity for the dashboard's protocol selector, environment-
   mode panel, and iron-rules/qualification panel (currently real data,
   static rendering, self-admitted-non-functional per inline comments).
3. Real coverage-trend history: wire `append_coverage_history_sample()`
   into an actual COVERAGE_CLOSURE evaluation path so the trend chart has
   real multi-timestamp data instead of requiring a hand-dropped
   `history.json`.
4. A real human-facing waiver-authoring interface (`/api/waiver` +
   dashboard form) persisting to a store the existing waiver gates can
   read, instead of waivers only existing inside AI-agent-authored
   evidence blocks.
5. Signoff bundle completeness: `collect_signoff_bundle()` gains real UVM
   testbench source and a real test-suite/regression manifest, not just
   blackboard/vplan/telemetry/self-audit.
6. A real, structured FSDB evidence panel (not a waveform viewer — FSDB
   is a proprietary binary format with no public library) backed by real
   `fsdbreport -csv` output, replacing today's deliberate parse-stub.
7. `HYPOTHESIS` implemented for real (tied to the already-real
   `inference.py` confidence engine); `REVIEW` given logic genuinely
   distinct from `STATUS`.
8. Memory-tier wiring: extend `_promote_experience_knowledge`'s pattern to
   real Job/Project-tier write call sites, and add a real
   `MemoryRetriever.search()` read call into `run_stage()`.
9. Agent-taxonomy reference: no in-repo doc currently states the wrong
   "7 Expert Agent" taxonomy (confirmed by repo-wide grep) — add a short
   canonical real-agent-roster doc so future docs/posters have something
   accurate to check against, rather than "fixing" content that doesn't
   exist in-repo.

## 3. Non-goals (explicit exclusions, per user decision)

- Mobile app, SSH/Telnet remote-transport layer for Claude Web/Mobile
  (`remote_control.py`'s own docstring already states this is out of
  scope by design).
- Claiming or building multi-simulator support (Questa/Xcelium/
  Riviera-PRO) — the project is VCS-only; a skill file already instructs
  agents to ignore non-VCS files. Any doc still implying otherwise should
  be corrected to say VCS-only, not extended.
- CI/CD integration (Jenkins/GitLab CI/Docker) — never requested by any
  real project using this harness.
- Topology Composer / System Coverage (cross-protocol) / Performance &
  Analytics / Cross-Subsystem Virtual Sequencer — no generator, gate, or
  schema exists for any of these; they are separate, larger projects, not
  in scope for this pass.
- A real FSDB waveform *viewer* (signal timeline rendering) — technically
  infeasible without Synopsys's proprietary libraries; item 6 above is a
  structured text-evidence panel, not a waveform renderer.

## 4. Task Design

### Task 1 — Live stats introspection

New module `dv_harness/stats_snapshot.py` exposing `compute_stats(root) ->
dict` with `agent_count`, `skill_count`, `iron_rule_count`,
`graph_node_count`, `graph_edge_count`:
- `agent_count`: `len(list((root/'.claude'/'agents').glob('*.md')))`.
- `skill_count`: count `SKILL.md` under `.claude/skills/` **excluding**
  any path containing `_deprecated` — reuse the same exclusion logic
  `skill_resolver.py` already has (import/reuse, don't reimplement).
- `iron_rule_count`: same regex `dashboard.py:_iron_rules_count` already
  uses (`re.findall(r"(?m)^## 鐵則 \d+", text)` against
  `.claude/skills/CORE/iron-rules/SKILL.md`) — extract into
  `stats_snapshot.py` and have `dashboard.py` import it instead of
  duplicating, per DRY.
- `graph_node_count`/`graph_edge_count`: `len(graph.get("nodes",[]))` /
  `len(graph.get("edges",[]))` from `.dv-harness/graph/main_graph.json`.

Wire it to a new `dv-harness stats` CLI subcommand (JSON output) and a new
`/api/stats` dashboard GET route. Acceptance: running it against the
current repo produces the real current counts (verify against a fresh
manual count at implementation time — this spec doesn't hardcode the
expected numbers since they'll keep changing).

### Task 2 — Dashboard real interactivity (#8/#9/#12)

Read `dashboard.py`'s current `protocoltiles`/`envmodetiles`/
`ironrulestiles` rendering (around lines 700-730 per Round 1 research —
verify exact lines fresh, this file may have shifted) and their inline
comments ("not a functional selector", "No field anywhere tracks which
mode the CURRENT run used", "a reference legend, not this run's data")
before changing anything.

- **Protocol selector**: make each tile a real clickable element that
  sets the Goal field's protocol-scoping (or a dedicated hidden field the
  backend already reads) rather than purely decorative text.
- **Env-mode panel**: read the CURRENT run's actual mode from real state
  (`.dv-harness/state.json` or wherever `execution_mode`/environment mode
  is recorded for the active run — confirm the real field name first) and
  visually highlight it, replacing the static always-both-shown legend.
- **Iron-rules panel**: render live iron-rule count/tier data with real
  CSS-class-driven color coding (e.g. a `badge-pass`/`badge-fail` class
  keyed off real tier value), not a flat text legend.

### Task 3 — Coverage trend real data

Find the real COVERAGE_CLOSURE stage evaluation path (`gates.py`'s
`STAGE_GATES['COVERAGE_CLOSURE']` entries, evaluated via
`evaluate_stage_evidence`/`run_gate` in `engine.py`'s `run_stage()`).
Add a call to `append_coverage_history_sample()` (or `dashboard`'s
wrapper) at the point a COVERAGE_CLOSURE stage evidence block reports a
real coverage percent — mirror the exact calling convention
`_promote_experience_knowledge` already uses for its own auto-write hook
(same file, same function-injection pattern), so this is additive to
`run_stage()`, not a new independent code path.

### Task 4 — Waiver authoring interface

New store `.dv-harness/waivers/waivers.json` (list of waiver records).
New `POST /api/waiver` endpoint in `dashboard.py` accepting
`{gate_id, item_id, approved, evidence, ...}` and appending to that
store. New dashboard form (gate_id dropdown, item_id text, evidence
textarea, submit). Read each of the six waiver-consuming gate scripts'
exact expected input shape (documented in Round 1 research — reverify at
implementation time) and confirm/adjust field names so a dashboard-
authored record is genuinely consumable — if a gate script currently has
no code path that reads from this new shared store at all (each takes
its own `--waivers`/`--holes` file per invocation today), this task also
adds a thin adapter so the shared store's content reaches that argument,
without changing the gate scripts' own pass/fail logic.

### Task 5 — Signoff bundle completeness

Read `dv_harness/signoff_export.py`'s `collect_signoff_bundle()` fully.
Add two new candidates:
- UVM testbench source: locate the real generated-environment output
  directory (check `ProtocolEnvGenerator`'s actual output structure —
  `tb/agents,env,seq,tests,top` per its own docstring — and/or
  `examples/generated_*_uvm_env/`) and copy the `tb/` tree into the
  bundle when it exists; report its absence explicitly (matching the
  existing `pattern_registry` "correctly reported absent" pattern) when
  it doesn't, never fabricate placeholder content.
- Test-suite/regression manifest: check `regression_list_manager.py` and
  `pattern_registry_generator.py` for the real regression-list/pattern-
  registry artifact path and include it the same way.

### Task 6 — FSDB structured evidence panel

`dv_harness/fsdb_report.py`'s `parse_fsdbreport_output()` is currently a
deliberate stub (`parsed: False`). Per the confirmed-real usage already
recorded in `.claude/skills/CORE/dv-workflow/SKILL.md` (2026-08-29 entry),
the real working invocation is `fsdbreport f.fsdb -period <T> -level 1
-csv`. Implement real CSV parsing of that output into structured
`{signal, timestamp, value}` (or equivalent) records. Add a
`GET /api/fsdb-report?path=...` dashboard endpoint and a queryable panel
(signal name filter, time-range filter) rendering the parsed records as a
table — explicitly NOT a waveform/timeline graphic (infeasible per Non-
goals). Check `dv_harness_tests/test_fsdb_report.py` for existing fixture
format before writing the parser, to match established test conventions.

### Task 7 — HYPOTHESIS real implementation, REVIEW differentiation

In `dv_harness/remote_control.py`: add `"HYPOTHESIS"` to
`ALLOWED_COMMANDS`. Add a corresponding legal-transition row in
`tools/verification_flow/remote_state_transition_gate.py` (read its exact
current table structure first). Implement `HYPOTHESIS`'s effect: record a
hypothesis record and call the already-real, already-wired
`inference.score_confidence()`/`identify_gap()`/`next_best_action()`
(exact signatures confirmed in `engine.py`'s `_score_root_cause_confidence`)
against it, returning/persisting the scored result. Give `REVIEW` real
logic distinct from `STATUS`: surface the current stage's actual evidence
blocks, confidence score, and gate verdict (read-only, no state
transition) rather than today's identical-to-STATUS no-op.

### Task 8 — Memory-tier wiring

In `dv_harness/engine.py`: read `_promote_experience_knowledge`'s exact
current call convention fully (verify past line ~365, not fully read in
Round 1 research). Add two new, analogous auto-write call sites following
the SAME pattern (build a `kind`-tagged record, call
`memory_router.route_and_store`):
- A Job-tier write triggered by real LSF job reconciliation (find the
  real `lsf-reconcile` code path in `lsf_client.py`/`cli.py`).
- A Project-tier write triggered by a PROJECT_MODEL-stage PASS (mirror
  the STAGE_GATES-driven trigger `_promote_experience_knowledge` already
  uses for its own stage).

Add one `MemoryRetriever.search()` call early in `run_stage()` (near the
existing `bb_snapshot = self.blackboard.snapshot(...)` call) to inject
relevant memory results into the stage prompt — additive, must not change
existing prompt-building behavior when no relevant memory exists (empty
result list is a no-op, not an error).

### Task 9 — Agent-taxonomy reference doc

Confirmed: no in-repo doc currently states the wrong "PM/Architect/
Developer/Verification/Regression/QA&Closure/Knowledge Agent" taxonomy —
that exists only in external poster PNGs. Add a short new reference doc
(e.g. `.claude/agents/ROSTER.md`) listing the real 16 agent files and each
one's actual role (from its frontmatter `description:`), generated or
verifiable via Task 1's `stats_snapshot.py` agent-listing logic, so future
poster/doc authors have a canonical, checkable source instead of writing
a taxonomy that doesn't correspond to any real file.

## 5. File-overlap / sequencing note

`dashboard.py` is touched by Tasks 1, 2, 3 (call site only, not the
dashboard file itself for Task 3), 4, and 6. Per this project's own
subagent-driven-development practice, tasks execute sequentially (one
implementer at a time, never parallel dispatch), so file overlap across
tasks is not a conflict risk — only an ordering consideration. Recommended
order: 1 (stats, smallest, unlocks Task 9) → 9 (trivial doc, depends on
1's agent-listing logic) → 2 (dashboard interactivity) → 4 (waiver, new
dashboard section) → 6 (FSDB panel, new dashboard section) → 3 (coverage
wiring, engine-side) → 5 (signoff bundle) → 7 (HYPOTHESIS/REVIEW) → 8
(memory wiring). Non-dashboard tasks (5, 7, 8) can be reordered freely.

## 6. Testing Strategy

Every task gets real tests exercising real behavior (subprocess-invoked
gate scripts, real file I/O against tmp_path, no mocks), consistent with
this project's established practice. Dashboard-touching tasks (1, 2, 4, 6)
need at minimum a test that starts the dashboard's handler logic (or
calls the underlying `_read_*`/`compute_*` functions directly, matching
existing `test_dashboard_interactive.py` conventions) and asserts on real
JSON/HTML output — read that existing test file's patterns before writing
new tests, to stay consistent.

## 7. Consolidation

Per the Methodology Consolidation Rule: after all 9 tasks land, sync
`.claude/` and the touched `dv_harness`/`tools` files to `industrial` and
`PACKAGE`, using the corrected Task-7-redo approach from the prior plan
(explicit file list + real content-diff verification, never a
self-reported claim) — this time within the same repo (no worktree-vs-
main-checkout source mismatch is possible here since there's no separate
worktree involved unless one is created for this plan too).

## 8. Open questions carried into implementation planning

- Task 2's exact current line numbers in `dashboard.py` need a fresh read
  at implementation time (the file may have shifted since Round 1
  research).
- Task 3's exact real field name for "current run's active mode" needs
  verification against `.dv-harness/state.json`'s actual schema.
- Task 4's exact adapter mechanism for feeding the shared waiver store
  into each gate's own `--waivers`/`--holes` argument needs confirming
  which layer currently assembles that argument (agent-evidence-block
  time, per Round 1 research's tentative finding) before finalizing.
- Task 8's exact `_promote_experience_knowledge` behavior past line ~365
  needs a fresh full read before extending its pattern.
