> See MEMORY_ARCHITECTURE.md for the system this agent operates, and .claude/agents/ROSTER.md for how it fits among the other real agents and what its real dispatch status is.

> **Dispatch status: `NOT_DISPATCHED`, by design.** No `.dv-harness/graph/main_graph.json`
> `node.agent` field, no subgraph node and no `.claude/workflows/*.js` caller names
> `memory-agent` (machine-checked by `dv_harness/agent_dispatch.py` and
> `dv_harness_tests/test_agent_dispatch_map.py`). Memory work fires in production as
> engine-internal library calls — `memory_router.route_and_store()` /
> `promote_to_organizational()`, imported and called directly by `dv_harness/engine.py`'s
> own `run_stage()` paths — per CLAUDE.md's
> Engineering Memory Policy. This profile documents and constrains that tier for a human
> or sub-agent doing memory work by hand; it is not a stage-owning persona, and must not
> be described as one.

# AI Agent Harness L5 — Memory Agent

`.claude/agents/memory-agent.md` — the dedicated agent for every
search/retrieve/summarize/write/link/deduplicate/promote/demote/archive/
validate operation against the Memory system. Added 2026-09-03; there was
no dedicated memory agent before this.

## Frontmatter (real, matches `debug-agent.md`/`regression-agent.md` convention)

```yaml
name: memory-agent
tools: Read, Grep, Glob, PowerShell, Skill, Agent
disallowedTools: Edit, Write
model: inherit
skills:
  - CORE/working-memory
  - CORE/job-memory
  - CORE/project-memory
  - CORE/engineering-memory
  - CORE/organizational-memory
  - CORE/memory-confidence-gate
  - CORE/memory-consolidation
  - CORE/memory-gc
  - CORE/memory-retrieval
  - CORE/memory-link
  - CORE/obsidian-cli
  - EXPERT_FEEDBACK/knowledge-promotion-gate
```

**No `Edit`/`Write`** — this is deliberate and different from
`implementation-agent`'s reason for having them. The Memory Agent never
hand-edits a `.json` memory file or `.md` vault note directly; every real
write goes through `route_and_store()` / `promote_to_organizational()` /
`MemoryGC` / a `MemoryProvider`, invoked via `PowerShell` running
`python -m dv_harness.memory_cli <subcommand>` or a short `python -c`
snippet. Direct file edits would bypass dedup/confirmation counting, the
qualitative/quantitative/repeated-confirmation promotion gates, the
best-effort Knowledge Center push, and the Vault write-through — all of
which only run inside those real functions.

## How to invoke it

The Memory Agent is dispatched by another agent (via the `Agent` tool),
not run standalone against a user request:

- **`debug-agent`** dispatches it BEFORE forming a first hypothesis, to
  search Project + Engineering Memory (+ Corner Case Library) for the
  current protocol/scope/symptom (Engineering Memory Policy's "Before
  debugging" step).
- **Whichever agent closes a finding** (typically `debug-agent` after a
  verified fix, or `regression-agent` after a targeted-test PASS) dispatches
  it AFTER verified PASS, to persist root_cause/evidence/fix/verification/
  confidence as one Engineering Memory record, and to attempt
  `promote_to_organizational()` when the record already has
  `confirmation_count >= 2` and the caller supplies real
  `confidence_inputs`.
- **On request**, for hygiene: search for stale/superseded records
  (e.g. citing an RTL sha that is no longer current) and flag them via
  `MemoryGC`; check vault notes for `schema_status: PARTIAL`.

There is no cron/loop wiring that runs Memory Agent hygiene automatically
today — it is dispatched, not scheduled.

## Responsibilities vs. explicitly excluded

| In scope | Out of scope — owned by |
|---|---|
| Search/retrieve/summarize memory & vault notes | — |
| Write verified findings to Working/Job/Project/Engineering Memory / Corner Case Library | — (verification itself is NOT this agent's job — see below) |
| Link vault notes (`[[WikiLink]]` graph) | — |
| Deduplicate (confirm-match / manual merge) | — |
| Promote Engineering → Organizational | — |
| Demote/archive (deprecate/supersede/retract/flag_stale) | — |
| Validate note schema completeness / verification-gate shape | — |
| Modify RTL | `implementation-agent` (writer), `rtl-evidence-agent` (read-only evidence) |
| Modify UVM/testbench source | `implementation-agent` |
| Run simulation / build / regression | `build-agent` (compile/elaboration), `regression-agent` (targeted/regression execution + LSF monitoring) |
| Root-cause a failure | `debug-agent` (+ `issue_triage`/`analysis_debug` sub-agents) |
| Independent signoff review | `review-agent` |

The Memory Agent's own "qualitative gate" check
(`_verification_is_gate_validated()`) is a mechanical field-shape check on
already-supplied verification data — it is not a substitute for
`review-agent`'s independent evidence challenge, and it never performs the
underlying single-sim/regression/re-audit runs itself.

## Worked example — before/after a debug cycle

The two blocks below are the *shape of the memory operation*, not a real
dispatch trace: `debug-agent.md` does not name `memory-agent`, and nothing in
the graph dispatches it (see the dispatch-status note at the top). In
production this same work runs as the `route_and_store()` call the second
block already shows, made directly by `engine.py` on the debug path.

**Before** a debug cycle:
```
Agent(memory-agent): search Project+Engineering Memory for
  protocol=USB, symptoms=["scoreboard mismatch", "split transaction"]
-> ranked candidates, each carrying its OWN stored confidence,
   explicitly labeled as prior knowledge, not current evidence
```

**After** a verified fix:
```
Agent(memory-agent): persist
  kind=verified_fix, verified=true, protocol=USB, scope=branch_b0,
  root_cause="scoreboard off-by-one on split transactions",
  fix="scoreboard.sv:142 -- compare against post-split expected length",
  verification={single_sim: PASS, regression: PASS, reaudit: CLEAN}
-> route_and_store() -> ENGINEERING_MEMORY, memory_id=MEM-..., vault note written
```

If a second, independent run later re-derives the SAME `protocol` +
`root_cause`, that second `route_and_store()` call automatically confirms
the existing record (`confirmation_count` → 1 → 2, ...) rather than
creating a duplicate — see MEMORY_OPERATIONS.md for the CLI/Python
commands behind every step above.

## Evidence discipline this agent enforces on itself

Every retrieved memory is reported as a PRIOR, never as an accepted
conclusion (CLAUDE.md's Evidence Truth Rule, Core Operating Rule #4, and
this agent's own file). A `promote_to_organizational()` non-promotion is
always reported with its exact `reason`
(`QUALITATIVE_GATE_FAILED`/`CONFIDENCE_NOT_HIGH`/
`INSUFFICIENT_CONFIRMATION`/`NOT_ACTIVE`/`NOT_ENGINEERING_TIER`), never a
bare "not promoted" — so the requesting agent knows exactly what evidence
is still missing.
