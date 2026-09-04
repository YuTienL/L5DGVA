# Gap-close report — AI mechanism #10: "The 7 Expert Agent Roles"

**Verdict: DONE** (scope corrected from the audit's proposed plan — see "Where I
diverged from the audit plan", which is the most important section of this report).

**Test summary**: `test_agent_dispatch_map.py` (9 new) + `test_agent_roster_doc.py`
(2, one strengthened) = 11 passed; wider agent/dispatch/routing suite
(`test_graph_parallel_dispatch`, `test_multi_agent_timing`,
`test_agent_checkpoint_check`) 37 passed; both new guard assertions verified to
FAIL under real mutation (roster status flipped; `SIGNOFF` repointed to
`implementation-agent`), then restored.

---

## What I confirmed of the audit's evidence

Re-checked independently before touching anything, and it holds:

- The literal 7-name taxonomy exists nowhere in the repo except the audit-prompt
  file, and `dv_harness_tests/test_agent_roster_doc.py` actively forbids it in
  `ROSTER.md`.
- Per-stage agent dispatch is real and firing. `main_graph.json` now has **41**
  nodes (audit said 37 — it grew under concurrent work this session) carrying a
  `node.agent` field, flowing through `router.py` → `multi_agent.delegate()` →
  `agent_profile.load_agent_profile()` → `adapters/cli.py`'s real
  `claude --agent <name>` + per-agent `--allowedTools`/`--disallowedTools`.
- Separation of duties is genuinely enforced by tool scope: `review-agent`
  declares `disallowedTools: Edit, Write`, and `implementation-agent`'s node set
  never reaches `SIGNOFF`.

**Where my measurement differs from the audit**: the audit said "10 wired into
production dispatch". Machine-derived, it is **14 GRAPH_DISPATCHED of 22
registered profiles**, with **8 NOT_DISPATCHED** — and the audit only named one
of those 8 (`memory-agent`). The other seven are `IP_UVM_DV_Gen`,
`audit-change-governance-agent`, `issue_triage`,
`post-sim-command-log-validation-agent`, `preflight-resource-guard-agent`,
`simulation-semantic-validation-agent`, `verification-risk-experience-agent`.

## Where I diverged from the audit plan (and why)

The audit's fix plan items 1 and 2 were to **create** `architect-agent.md` and
`verification-agent.md` and repoint `ARCH_DISCOVERY` / `ARCH_CALIBRATION` /
`VERIFICATION_ARCHITECTURE` / `VPLAN` to them. **I did not do this, deliberately.**
Two reasons, both verified in code this pass:

1. **There is no functional gap to fix there.** Those nodes declare only
   `blackboard_write` (`architecture`, `verification_architecture`, `vplan`) —
   and Blackboard topics are written by the **engine**
   (`engine.py`'s `_write_blackboard_from_evidence`), not by an agent holding a
   `Write` tool. So `analysis-agent` being read-only does not block those stages
   from doing their job. Giving them a writer persona would widen write scope for
   zero functional gain.
2. **It would reintroduce the exact fiction the repo already rejected.** A prior
   pass (2026-08-31) concluded this taxonomy is poster-only and added a test
   forbidding it. Creating personas named after it to make the marketing phrase
   true is the "build a parallel mechanism" failure this pass was told to avoid.

Same reasoning for audit item 3: wiring a `KNOWLEDGE` node so `memory-agent`
gets dispatched would **duplicate** `memory_router.route_and_store()`, which
already fires on the real path from `engine.py` per CLAUDE.md's Engineering
Memory Policy. I took the audit's own option (b) instead.

**So what was the real gap?** Reframed from the evidence: the mechanism (per-stage
tool-scoped dispatch) works, but **nothing tied the role taxonomy to it**.
`ROSTER.md` listed all 22 profiles as one flat, undifferentiated list, with no way
to tell a role that really fires (`implementation-agent`, 4 real nodes) from a
profile with zero dispatch call sites anywhere (`memory-agent`). That ambiguity is
*why* an unreal 7-role taxonomy could be asserted about this repo and survive: with
a flat list, "we have an Architect Agent" is unfalsifiable, and answering it costs a
full audit pass of grepping — which is exactly what just happened. That is the
closable gap, and it is closed by making dispatch reality machine-derived and
test-enforced.

## What changed

**New — `dv_harness/agent_dispatch.py`**
`agent_dispatch_map(root)` derives, per registered agent, its real dispatch status
(`GRAPH_DISPATCHED` / `SUBGRAPH_DISPATCHED` / `WORKFLOW_DISPATCHED` /
`NOT_DISPATCHED`) plus the actual node ids / subgraph nodes / workflow callers,
read fresh from `main_graph.json`, `.dv-harness/graph/subgraphs/*.json` and
`.claude/workflows/*.js`. It reuses `stats_snapshot.list_agent_files()` and
**only reads** the tables the engine already dispatches from — it adds no node,
never delegates, never selects an agent. Workflow matching is deliberately
conservative (a known agent name inside a quoted string literal only), so a prose
mention in a comment is not over-credited as a call site.

**Rewritten — `.claude/agents/ROSTER.md`** (machine-generated from that map)
Every entry now carries its real ``Dispatch: `STATUS` `` plus the concrete node
ids it owns. Each of the 8 `NOT_DISPATCHED` profiles carries a verified *"How this
role really runs"* note — every one was grep-confirmed this pass, e.g.
`simulation-semantic-validation-agent` → the `simulation_semantic_validation_gate`
gate at `dv_harness/gates.py:200`; `verification-risk-experience-agent` →
`experience_applicability_gate` at `gates.py:351`;
`preflight-resource-guard-agent` → `dv_harness/preflight.py` exposed as
`dv-harness preflight` (`cli.py:272-292`). A new closing section records the real,
verified answer for each of the four recurring fictional roles (project-management,
architecture-owning, verification-planning, knowledge/memory-tier), described
without using the forbidden literal names, so the question does not have to be
re-litigated by grep every audit.

**Fixed — `docs/MEMORY_AGENT.md`**
Carried a stale count ("the other 19 real agents", really 21) and, worse, described
its worked example as *"dispatched by `debug-agent`"* — `debug-agent.md` never names
`memory-agent`, and nothing in the graph dispatches it. Replaced with an explicit
`NOT_DISPATCHED, by design` banner and corrected example framing.

**Strengthened — `dv_harness_tests/test_agent_roster_doc.py`**
The forbidden-taxonomy guard covered only 4 of the 7 names. Now covers all seven
(plus the `QA & Closure` spacing variant) with an explanatory failure message.

**New — `dv_harness_tests/test_agent_dispatch_map.py`** (9 tests)
The ones that matter for "wires the mechanism into the real path":
- `test_every_main_graph_node_agent_resolves_to_a_real_profile` — a `node.agent`
  with no `.claude/agents/<name>.md` makes `agent_profile.found` False, which makes
  `cli.py` **silently drop** the `--agent` flag and lose that role's tool scoping
  with no error. Now caught.
- `test_graph_dispatched_role_really_reaches_the_claude_agent_flag` — drives the
  REAL `ClaudeCLIAdapter.run()` with a real loaded profile and asserts the argv
  handed to subprocess actually carries `--agent review-agent` and
  `--disallowedTools Write/Edit`. This is end-to-end wiring, not the function in
  isolation.
- `test_separation_of_duties_writer_never_reaches_signoff` — the real claim behind
  "distinct expert roles": writer and signoff node sets are disjoint and signoff
  cannot write.
- `test_roster_dispatch_status_matches_the_real_graph` /
  `..._lists_the_real_node_ids_...` / `..._explains_how_every_non_dispatched_role_
  really_runs` — repointing a `node.agent` without updating `ROSTER.md` now breaks
  the build.
- `test_dispatch_map_is_derived_from_the_real_graph_not_hardcoded` — repoints
  `IMPLEMENT` in a tmp copy and asserts the map follows. Without this, roster/graph
  agreement would prove nothing.

## Verification

```
python -m pytest dv_harness_tests/test_agent_dispatch_map.py \
                 dv_harness_tests/test_agent_roster_doc.py -q
=> 11 passed

python -m pytest dv_harness_tests/test_agent_dispatch_map.py \
                 dv_harness_tests/test_agent_roster_doc.py \
                 dv_harness_tests/test_graph_parallel_dispatch.py \
                 dv_harness_tests/test_multi_agent_timing.py \
                 dv_harness_tests/test_agent_checkpoint_check.py -q
=> 37 passed
```

Mutation-checked (the tests really catch drift, then restored):
- flipped `memory-agent`'s roster status to `GRAPH_DISPATCHED` →
  `test_roster_dispatch_status_matches_the_real_graph` FAILED as intended.
- repointed `SIGNOFF` to `implementation-agent` in `main_graph.json` →
  `test_separation_of_duties_writer_never_reaches_signoff` and
  `test_roster_lists_the_real_node_ids_for_graph_dispatched_agents` both FAILED as
  intended. `git diff` clean after restore.

## Honest residuals

- **Pre-existing, not mine**: `test_doc_citation_check.py` has 2 failures from 3
  drifted citations in `docs/MEMORY_ARCHITECTURE.md` and `docs/MEMORY_SCHEMA.md`
  (files I did not touch). Verified as baseline by stashing my `docs/` edit and
  re-running: identical 2 failures, 3 drifted, 0 unverifiable. My edit is
  citation-neutral (I reworded one citation that the checker flagged
  `UNVERIFIABLE` to keep it so).
- The workflow-caller detection is a string-literal scan, not a JS parse. It is
  conservative by design (it can under-credit an agent named via a computed
  string, never over-credit a comment). Under-crediting surfaces as a visible
  `NOT_DISPATCHED` requiring a written note, not as a silent pass.
- This pass did **not** change any `node.agent` value. The dispatch table is
  exactly as it was; what changed is that it is now described accurately and
  guarded against drift.
- The audit's item 4 (whether `dv-lead` should be widened to cover more of
  `engine.py`'s stage-transition control) is **documented as a deliberate design
  decision** in ROSTER.md rather than changed. Making workflow control an LLM
  persona would trade a deterministic, replayable, testable state machine for a
  non-deterministic one; that is a real design question, not a wiring gap, and it
  should not be decided as a side effect of a naming pass.
