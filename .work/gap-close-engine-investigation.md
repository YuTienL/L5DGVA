# Gap-Close Engine Investigation (3 small independent gaps)

Session date: 2026-09-03. Investigates 3 engine-level gaps flagged by an earlier 8-AI-engine
wiring audit. Each finding below is based on direct file:line reads and full-tree greps, not
inference from the audit's own summary text.

---

## 1. `graph_runtime.py` — orphaned inside `dv_harness/`, but NOT wholly unused project-wide

### Real current state

- `dv_harness/graph_runtime.py:1-6` already carries a NOTICE header (added 2026-08-28) stating
  the module is "NOT invoked by any executing code path in dv_harness/ or .claude/agents/*.md" —
  so the "delete vs. warn" question was already answered once with **warn**, before this audit.
- Grep confirms zero real imports anywhere under `dv_harness/` or `dv_harness_tests/`:
  ```
  grep -rn "graph_runtime" --include=*.py dv_harness dv_harness_tests .claude
  ```
  only matches are **comments** referencing the module by name in `dv_harness/engine.py:29-32`
  and `dv_harness/graph.py:14-15` (both explaining why `GraphRuntime` was deliberately *not*
  imported wholesale — `engine.py` instead re-derives the same wiring directly inside
  `run_stage()`, reusing the underlying modules `graph_runtime.py` also uses).
- **However**, a full-repo grep (not scoped to `dv_harness/`) finds a real, live import:
  `DV_GRAPH_STATUS.ps1:4` —
  ```powershell
  python -c "...from dv_harness.graph_runtime import GraphRuntime;r=GraphRuntime(Path(os.environ['DVROOT']));print(json.dumps(r.gstate.data,...))"
  ```
  This script is **not a stray file** — it is a documented, user-facing entry point:
  `.dv-workflow/inventory.json` and `README_DV_AGENT_HARNESS_v16.md:11-12` list it right next to
  `START_DV_HARNESS.ps1` as the standard way to check graph status:
  ```
  .\START_DV_HARNESS.ps1 -ProjectRoot . -Goal "..." -Loop
  .\DV_GRAPH_STATUS.ps1
  ```
- So `graph_runtime.py` is not "harmless since unused" as the audit assumed — it is reachable
  from a real, documented command. The problem is what that command actually shows once reached:
  `GraphRuntime.__init__` (`dv_harness/graph_runtime.py:17`) reads/writes
  `.dv-harness/graph/graph_state.json` via `GraphState`, a completely separate on-disk record
  from the one the real engine drives (`.dv-harness/state.json` via `StateStore`/`HarnessState`,
  used by `engine.py`'s `run_stage()`). `dv_harness/graph.py:13-17`'s own NOTICE already says
  this explicitly: "`.dv-harness/graph/graph_state.json` on disk is a stray artifact of a
  standalone GraphRuntime invocation, disconnected from the real `.dv-harness/state.json`
  HarnessState that engine.py actually drives."
- Confirmed on disk in this project: `.dv-harness/graph/graph_state.json` is stale —
  `{"active_nodes": ["ENV_CHECK"], "completed_nodes": [], "blocked_nodes": [], "node_results":
  {}, "iteration": 0}`, last modified 2026-08-27, never updated since — while the real
  `.dv-harness/state.json` (`current_stage: "ENV_CHECK"`, `overall_status: "PASS"`, real
  `git_sha`, non-zero `closure_iteration`, etc.) is actively maintained (last modified
  2026-09-02 21:54). The two happen to agree on `current_stage` by coincidence today, but
  `node_results`/`iteration`/`completed_nodes` are permanently frozen at their initial empty
  state — running `DV_GRAPH_STATUS.ps1` at any point after the first stage would silently show
  a misleadingly stale/empty graph view alongside a matching-looking `active_nodes` field.
- The real, live equivalent already exists: `dv-harness status` (`dv_harness/cli.py:103,490-491`,
  `print(h.summary())`) reads the actual `HarnessState` the engine drives.

### Recommended fix

This is not a pure "delete vs. add a header warning" choice — a header warning already exists on
`graph_runtime.py` itself, and blind deletion would silently break the documented
`DV_GRAPH_STATUS.ps1` command. The real fix is to close the gap end-to-end:

1. Retarget `DV_GRAPH_STATUS.ps1` to call the real, live status source instead of
   `GraphRuntime`/`GraphState` — e.g. shell out to `dv-harness status` (or a small python
   one-liner reading `.dv-harness/state.json` via `StateStore`), matching what `cli.py`'s
   `status` subcommand already does.
2. Once nothing references it, delete `dv_harness/graph_runtime.py` and the stray
   `.dv-harness/graph/graph_state.json` artifact (they exist purely to back the now-retargeted
   script). `GraphDefinition`/`GraphState` in `graph.py` should stay — `GraphDefinition` is
   genuinely used by `engine.py`/`policy.py` per `graph.py`'s own NOTICE; only the unused
   `GraphState` class and the `graph_runtime.py` module built on top of it are removable.
3. Update `README_DV_AGENT_HARNESS_v16.md`'s `DV_GRAPH_STATUS.ps1` mention if its output shape
   changes.

If a fast turnaround is preferred over the full fix, the minimum-safe interim step is to extend
`DV_GRAPH_STATUS.ps1`'s own output (or a comment above it) with an explicit "this view is
disconnected from the live engine state" warning — but this only papers over a documented command
that produces misleading output; it does not close the gap.

---

## 2. `protocol_decision` / `environment_mode_decision` — never persisted to any on-disk record

### Real current state

- Both are computed once per stage attempt in `dv_harness/engine.py:1876-1878`:
  ```python
  route_info["protocol_decision"] = resolve_protocol(self._protocol_router_evidence(user_goal))
  route_info["environment_mode_decision"] = resolve_environment_mode(
      self._environment_mode_router_evidence())
  ```
  (`resolve_protocol` in `dv_harness/protocol_router.py:175-214`, `resolve_environment_mode` in
  `dv_harness/environment_mode_router.py:88-163` — both return plain JSON-serializable dicts.)
- Full-tree grep for both terms:
  ```
  grep -rn "protocol_decision\|environment_mode_decision" dv_harness/*.py dv_harness_tests/*.py
  ```
  finds them **only** in:
  - `engine.py:440,442` — formatted into `_build_plan_section()`'s prompt text (the ephemeral
    string sent to the LLM adapter, never written to disk).
  - `engine.py:1876-1878` — the computation itself.
  - `engine.py:1952` — a transient local read (`kc_protocol = ...`) used only to build a
    Knowledge Center search query string for that one call; not persisted.
  - `dv_harness_tests/test_protocol_and_environment_mode_engine_wiring.py:9-10,50` — a test that
    explicitly asserts these are "load-bearing, not write-only metadata" **in the prompt only**;
    it does not assert or exercise any on-disk persistence.
  - Confirmed **zero** hits in any `.json`/state file under `.dv-harness/`.
  So the audit's "0 grep hits on disk" claim is accurate: these two decisions genuinely exist
  only as local Python variables folded into the one-shot LLM prompt string, then discarded.

### The established pattern for a comparable decision (route/skill resolution)

- `route_info["route"]`/`route_info["agent"]` (from `self.router.resolve(node)`,
  `engine.py:1863`) is the directly comparable "resolver decision" the audit pointed at. It is
  **partially** persisted already, via the exact same call site pattern this fix should reuse:
  `engine.py:2262-2276`, `self.react.record(...)` — called once per stage attempt, after the
  adapter call:
  ```python
  self.react.record(
      node=stage, iteration=ss["attempts"],
      reason_summary=_reason_summary(route_info, plan, bb_snapshot),
      action={"adapter": type(self.adapter).__name__,
              "agent": route_info["agent"] if route_info else None,
              "resume_session": resume},
      ...
  )
  ```
  `ReactRecorder.record()` (`dv_harness/react.py:57-60`) writes this as a real on-disk record at
  `.dv-harness/react/<node>/iteration_NNN.json`, and additionally pushes a projection into the
  Working Memory tier via `memory_router.route_and_store()` (`react.py:62-91`) — this is the
  established, already-real "make a resolver decision auditable" mechanism in this codebase
  (confirmed by `react.py`'s own header NOTICE, itself the product of an earlier
  "real-but-unwired" audit correction).
- Today `action` only carries `agent` (and `resume_session`) — not `route`, and not either of
  `protocol_decision`/`environment_mode_decision`. So even the comparable "route resolution"
  case is only half-persisted, and the two decisions in question are 0%-persisted.

### Recommended fix

Add the three missing fields to the same `action` dict already being written at
`engine.py:2266-2269`, at the existing `self.react.record(...)` call site — no new persistence
mechanism needed, this is a one-call-site change:

```python
action={"adapter": type(self.adapter).__name__,
        "agent": route_info["agent"] if route_info else None,
        "route": route_info["route"] if route_info else None,
        "protocol_decision": (route_info or {}).get("protocol_decision"),
        "environment_mode_decision": (route_info or {}).get("environment_mode_decision"),
        "resume_session": resume},
```

This makes both decisions land in the real, already-existing on-disk record
(`.dv-harness/react/<node>/iteration_NNN.json`) once per stage attempt — auditable after the
fact exactly like `route_info["agent"]` already is, matching the codebase's own established
pattern instead of inventing a new one (e.g. a bespoke Blackboard write or a new events.jsonl
field), and it is guarded by the same `if node is not None:` this call site already sits inside,
so it fires exactly when `protocol_decision`/`environment_mode_decision` were actually computed
(both are set together at `engine.py:1876-1878`, inside the same `if node is not None:` block).

---

## 3. `current_evidence_required` — set on every memory/corner-case record, read nowhere

### Real current state

- Set (always to `True`, via `setdefault`/`.setdefault`, never explicitly `False` anywhere in
  the codebase) at three write sites, all in `dv_harness/memory.py`:
  - `memory.py:37` — `MemoryStore.add()`, every record in every tier (working/job/project/
    engineering/organizational).
  - `memory.py:167` — `MemoryConsolidator.from_closed_finding()`, the write path for a
    fully-validated "engineering" record (only reachable after `single_sim PASS` +
    `regression PASS/NOT_REQUIRED` + `reaudit CLEAN`, per `memory.py:148-155`).
  - `memory.py:286` — `CornerCaseLibrary.add()`, every corner-case record.
- Full-tree grep for the flag:
  ```
  grep -rn "current_evidence_required" dv_harness/*.py dv_harness/uvm_generator/*.py \
      dv_harness/vplan_writer/*.py dv_harness/adapters/*.py dv_harness_tests/*.py .claude
  ```
  returns **zero** matches outside `memory.py`'s three write sites — confirmed, no read site
  anywhere in engine code, gates, CLI, dashboard, or tests. The only other place it appears at
  all is as static example data: `examples/verification_memory/MEM_USB2_FS_MPS.json:29`
  (`"current_evidence_required": true`), which itself confirms the value never varies in
  practice — every record ever produced or hand-authored in this repo has it hardcoded `true`.
- A directly comparable, **actually wired** "revalidate before trusting" mechanism already
  exists for `CornerCaseLibrary` records — `gates.py:881-915`, `_ccl_reuse_verified()` — used by
  `_check_judgment_fields()`'s `REUSED_CCL:<id>` co-sign-skip path (`gates.py:962-975`). It
  requires `status == "ACTIVE"`, an unexpired `revalidate_by`, and real
  `evidence.runtime_evidence_hash`/`evidence.semantic_verdict` — i.e. exactly the CLAUDE.md
  Evidence Truth Rule concept ("revalidate before trusting") this flag's name suggests, but
  **built using different, more specific fields** (`status`, `revalidate_by`,
  `evidence.*`) instead of `current_evidence_required`. Notably, `_ccl_reuse_verified` does not
  consult `current_evidence_required` even though `CornerCaseLibrary.add()` sets it on every
  record it verifies — the one real reuse-gate in this codebase was built without it.
- Separately, `MemoryRetriever.search()` results (`relevant_memory`, `memory.py:103-143`) are
  surfaced into every stage prompt via `prompts.py:2753-2763`, but the Evidence Truth Rule is
  enforced there with a **hardcoded, uniform** disclaimer string appended once per prompt
  regardless of which records are present or what any individual record's
  `current_evidence_required` value is — the exact same pattern repeats for
  `kc_search_results` at `prompts.py:2764-2775`. Per-record variation of this flag would have no
  way to change that text today even if it existed.
- There is no `REUSED_MEM:<id>`-style citation/skip mechanism for plain `MemoryStore`
  ("engineering" tier etc.) records anywhere — unlike `CornerCaseLibrary`, a `MemoryStore`
  record is only ever surfaced as informational prompt context (`relevant_memory` above), never
  cited by an agent to bypass a gate requirement. So there is no existing enforcement point for
  it to plug into on the `MemoryStore` side at all.

### Assessment: was this meant to gate reuse, and is it fixable in place?

The name and the write-time context (`MemoryConsolidator.from_closed_finding` only creates a
record after single_sim/regression/reaudit all pass) strongly suggest this was meant to be a
per-record "must still be revalidated with current evidence before being trusted" discriminator
— i.e. exactly the mechanism `_ccl_reuse_verified` independently reinvented using different
fields. But as implemented it cannot do that job:

1. **It never varies.** Every write site only ever sets it to `True` via `setdefault`; there is
   no code path anywhere that sets it to `False`. A boolean that is always the same value carries
   no information — adding a read site today would be a no-op check that always evaluates the
   same way for every record.
2. **The mechanism it would gate doesn't exist for most of what it's set on.** `MemoryStore`
   ("working"/"job"/"project"/"engineering"/"organizational") records have no
   citation/skip-gate consumer at all (only `relevant_memory` prompt-surfacing, which is already
   uniformly disclaimed). Only `CornerCaseLibrary` has a real skip-gate
   (`_ccl_reuse_verified`), and it was built to use `status`/`revalidate_by`/`evidence.*`
   instead — this flag was superseded before it ever got wired in, the same "real-but-unwired,
   then replaced by a differently-shaped real mechanism" pattern CLAUDE.md's own
   `dv_harness_poster_gap_reaudit_2026_08_29` memory already warns to check for.

**Conclusion: this is a genuinely abandoned/superseded design field on `MemoryStore` records**
(tiers written via `memory.py:37,167`) — recommend leaving it alone or removing it there; forcing
a read site for a flag that can never be `False` would add a permanently-true condition to
whatever it's wired into, which is not real enforcement.

The one place a small, real, non-forced enforcement point does exist is `CornerCaseLibrary`
(`memory.py:286` write site + `gates.py:881-915` read site), because it already has a genuine
reuse-skip gate. If closing this is desired there specifically, the smallest real wiring is:

- Give `current_evidence_required` an actual `False`-setter: in
  `CornerCaseLibraryConsolidator.from_resolved_corner_case()` (`memory.py:483-498`) — the one
  write path that already requires real `resolution.test_mapping` /
  `resolution.semantic_verdict` / `resolution.runtime_evidence_hash` before creating the record
  — set `record["current_evidence_required"] = False`, since that record is created *from*
  genuine current evidence at write time.
- Add a symmetric check to `_ccl_reuse_verified()` (`gates.py:894`, alongside the existing
  `status != "ACTIVE"` check): reject reuse when `rec.get("current_evidence_required", True)` is
  still `True` — i.e. a corner case hand-added via the bare `CornerCaseLibrary.add()` path
  (which leaves the flag at its default `True`) cannot be cited via `REUSED_CCL:<id>` to skip
  co-sign, only one that went through the real validated-resolution write path can.

This is offered as the smallest concrete wiring *if* the team wants the flag to do something —
it is not applied here, since it also changes CCL write-path behavior (a design decision, not a
pure bug fix) and the honest finding is that the flag was abandoned once `_ccl_reuse_verified`
was built without it, not that it is silently broken.
