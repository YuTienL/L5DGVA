# SYOSCB-29/30 gap close: architecture representation + 29-item Phase-1 report

**Status: DONE**

Commit `bc559c0` — `syoscb(SYOSCB-29/30): architecture tree + the 29-item Phase-1
report assembler`. Two new files, nothing else touched.

Test summary: `python -m pytest dv_harness_tests/test_syoscb_phase1_report.py` →
**34 passed**; the full SYOSCB + AMBA suite
(`test_syoscb_phase1_report/_source_audit/_topology_plan/_compare_policy/_result_taxonomy`,
`test_amba_discovery_report/_fabric_discovery/_port_registry/_vip_bind_plan/
_transaction_ir/_route_transform_predictor/_fabric_analysis/_fabric_generator`,
`test_protocol_capability`) → **655 passed**. Plus every test that enumerates
`dv_harness/*.py` (so a new module could break it) and the trust-vocabulary
separation test — `test_connectivity.py`, `test_harness_reliability.py`,
`test_mcp_read_only_boundary.py`, `test_graph_runtime_removed.py`,
`test_confidence_vocabulary_separation.py` → **312 passed**. 967 relevant tests
green. `pyflakes` clean on both new files.

The whole-repo `pytest dv_harness_tests` was started and had not finished within
this pass's budget; it is also confounded right now by another agent's in-flight
edits to `engine.py`/`stage_profile_report.py` (see Concurrency below), so its
result would not be attributable to this change either way. The 967 tests above
are the ones this change can actually affect: `syoscb_phase1_report.py` is a new
module imported by nothing but its own test.

---

## The handed-in audit was stale; re-verified before building

The audit report for this step said "no implementing code exists anywhere in the
repo" for the Route Predictor / adapters / SyoSil branches and that `find -iname
"*syoscb*"` returns zero hits. That was true when it was written and is no longer
true: prior steps of this same sequence (`git log`: `98f94da`, `891533a`,
`7670bb6`, `4cdc913`, `9b66f51`, `0850735`) landed real modules. Re-verified with
`wc -l`:

| module | lines | requirement |
|---|---|---|
| `dv_harness/syoscb_source_audit.py` | 1132 | SYOSCB-1/3 |
| `dv_harness/amba_transaction_ir.py` | 763 | SYOSCB-9/10 |
| `dv_harness/amba_route_transform_predictor.py` | 1104 | SYOSCB-12/13 |
| `dv_harness/syoscb_topology_plan.py` | 981 | SYOSCB-14/15/16 |
| `dv_harness/syoscb_compare_policy.py` | 1310 | SYOSCB-17/18 |
| `dv_harness/syoscb_result_taxonomy.py` | 745 | SYOSCB-21/22 |

So the audit's own recommendation ("render the other five branches as label-only
stub leaves tagged NOT_YET_BUILT") would have UNDER-reported: seven of the nine
SYOSCB-29 branches now have real artifacts to project. The tree projects them and
reserves `NOT_BUILT_PHASE_2_ONLY` for the two things that genuinely have no
implementation anywhere (Expected Transaction Generator / Actual Transaction
Collector).

The parts of the audit that were still accurate and were followed exactly:
`_tree_child_lines()` is the one ASCII-tree primitive (it lives at
`amba_fabric_discovery.py:2534`, not `connectivity.py:2534` as cited); a second
tree renderer must not be built; item 29 should replicate
`capability_evolution.render_stop_report()`'s checklist-gated shape rather than
call it.

---

## What was built

`dv_harness/syoscb_phase1_report.py` (new). It derives **nothing new about the
design**: every fact comes from the module that owns it, called through that
module's own renderer.

### SYOSCB-29 — architecture representation

`build_architecture_tree(...)` → `ArchitectureRepresentation` (entries +
per-branch status), `render_architecture_tree()` → the ASCII tree via
`afd._tree_child_lines()`, `assert_architecture_tree_covers_spec()`,
`unpopulated_architecture_branches()`.

`SYOSCB29_SPEC` is the document's tree verbatim (`:5240-5284`). The renderer
checks the FINISHED text against it, not the tuple against itself — the same
discipline `amba_discovery_report.assert_report_section_order()` uses, and it
really catches a dropped branch (tested).

Real output against the real parsed AMBA4 fixture + the real read-only
uvm_syoscb tree (excerpt):

```
DV Agent Harness L5
|-- AMBA Transaction Normalization
|   |-- AXI3 Adapter = NOT_PRESENT_IN_FABRIC
|   |-- AXI4 Adapter = ADD_NEW_ADAPTER
|   |   |-- PORTS = U_FABRIC_M00_AXI, U_FABRIC_M01_AXI, ...
|   \-- APB4 Adapter = ADD_NEW_ADAPTER
|-- AMBA Route / Transform Predictor
|   |-- Address Decode = 12 resolved / 0 open
|   |-- ID Transform = 6 resolved / 0 open
|-- AMBA Scoreboard
|   |-- Expected Transaction Generator
|   |   |-- STATUS = NOT_BUILT_PHASE_2_ONLY
|   \-- SyoSil UVM SCB
|       |-- Queue Engine = 6 planned queue(s)
|       |-- In-Order Compare = cl_syoscb_compare_io
|       |   \-- EVIDENCE = src/cl_syoscb_compare_io.svh:20 (read-only)
\-- Evidence
    |-- Route Error = ROUTE_ERROR, ID_MAPPING_ERROR
    |-- NOT_NAMED_BY_SYOSCB29 = BURST_ERROR, PROTOCOL_TRANSFORM_ERROR, UNKNOWN
```

**Three refusals to round up**, each with its own test:

1. `NOT_PRESENT_IN_FABRIC` is a claim about the fabric and may only be made when
   a real AMBA_PORT_REGISTRY supports it. With no registry every adapter leaf
   falls back to `ARTIFACT_NOT_SUPPLIED` — a fabricated negative is still a
   fabrication. (This was a real bug in my first draft, caught by writing the
   empty-input test first.)
2. The generator and collector render `NOT_BUILT_PHASE_2_ONLY`. The plan's real
   per-side queue counts appear underneath as the nearest real evidence, which is
   a deliberately weaker claim than "the collector exists".
3. SYOSCB-29's six `Evidence` leaves are **coarser** than
   `ScoreboardResult`'s fourteen values. The mapping is explicit and the three
   values no leaf names are rendered as their own leaf.
   `_assert_every_result_is_placed()` runs at import, so a future fifteenth
   taxonomy value is a hard failure here rather than a silent disappearance from
   the tree a human reviews at the gate.

### SYOSCB-30 — the 29 sections

`SYOSCB30_SECTIONS` is the doc's list verbatim (`:5294-5322`).
`build_syoscb_phase1_report(...)` takes every artifact as an optional keyword;
every omission renders a NOT SUPPLIED note **naming the function that would fill
it**. `render_syoscb_phase1_report()` self-checks three ways: section order
against the finished text, `assert_no_bind_statement()`, and
`assert_no_emittable_sv()`.

| sections | source |
|---|---|
| 6, 7, 9, 10, 11, 12, 13 | existing `amba_fabric_discovery` / `amba_port_registry` renderers |
| 14, 15 | `amba_fabric_analysis` (lazy import, one-way dependency, same as `amba_discovery_report`) |
| 16 | `amba_scoreboard_env.render_scoreboard_env_report()` |
| 19, 20 | `amba_transaction_ir` |
| 21 | `amba_route_transform_predictor` |
| 22 | `syoscb_topology_plan` |
| 23 | `syoscb_compare_policy` |
| 2, 3, 17, 18, 25, 26 | `syoscb_source_audit`'s real read-only audit, re-cut per section |
| 1, 4, 5, 8, 24, 27, 28, 29 | new here |

New-section notes:

- **1** is a real `import_module()` check over the 14 modules that implement the
  capability, plus `protocol_capability.derive_status()` — not a typed-in claim.
- **4** really executes `assert_not_vendored(repo_root, audit)` (name check +
  content-digest check against the audit's own hashes) and reports the result.
- **5** stays `REQUIRED_HUMAN_INPUT` unless a human supplies a path.
- **18** derives protocol-agnosticism by looking for an AMBA token in the real
  audited class names, so it cannot become a stale claim about a library that
  grew one.
- **24** (`build_scoreboard_test_plan()`) derives test intents as (real
  scoreboard group × 5 intents) from the SYOSCB-14 plan. A group blocked on
  slave-side producer attribution yields intents marked `REQUIRED_HUMAN_INPUT`
  with the reason attached — a stress test over a scoreboard that cannot say
  which master produced an item reports noise, not a failure.
- **25** is `NOT_AVAILABLE`, stated as such and distinguished from NEVER_BUILT:
  SYOSCB-25/26 need a real VCS/UVM toolchain run against a vendored copy, which
  is Phase-2-only. What Phase 1 *can* establish read-only — compile order,
  package name, UVM dependency, upstream vendor makefiles — is reported.
- **28** (`collect_open_blockers()`) aggregates each owning module's own
  `unresolved_*`/`unanswered_*` function. Adding a question there makes it appear
  here for free; nothing is re-derived.
- **29** replicates `capability_evolution.render_stop_report()`'s shape.

### SYOSCB-33's gate (section 29)

`SYOSCB33_GATE_LINES` is the doc's eleven lines verbatim (`:5384-5394`). Nine of
them are claims about work and each maps to one precondition;
`build_phase1_gate_checklist()` **derives** every value from a real artifact —
there is no argument a caller can set, so a checklist an agent could fill in for
itself does not exist. `render_phase1_gate_report()` raises rather than printing
"AMBA ADAPTER PLAN COMPLETE" over an adapter plan nobody finished, and the
refusal names what is missing.

What "COMPLETE" means is stated in the code and tested: a plan is complete when it
EXISTS and has an entry for everything it was asked about, *including entries that
honestly read `REQUIRED_HUMAN_INPUT`*. Requiring zero open questions would make
the gate unreachable on any real fabric and would push a planner toward guessing
values to clear it. Two preconditions are stricter because their owning module
defines an unanswered item as an incomplete artifact rather than an open question:
the SYOSCB-1 checklist (a file never read) and the SYOSCB-10 adapter verdict (the
mandated search never performed). A rendered gate additionally prints its own open
item count, so nine COMPLETE lines can never be read as "nothing is open".

---

## Hard constraints — how each was honored

- **Nothing copied from `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`.** The module reads
  it only through `syoscb_source_audit`'s existing read-only audit, and cites
  declarations as `file:line`. `test_nothing_from_the_upstream_tree_is_copied_into_this_module`
  asserts the module source carries no `class cl_syoscb`, no `endclass`, no
  `` `include ``. Section 4 additionally runs `assert_not_vendored()` over the
  whole repository on every report build.
- **No SystemVerilog emitted.** `render_syoscb_phase1_report()` runs
  `assert_no_emittable_sv()` and `assert_no_bind_statement()` on its own output
  before returning, and the real-fixture test re-runs both.
- **No VCS/UVM build invoked.** Section 25 is the report's own statement of why
  that is Phase-2-only.
- **Synthetic fixtures only inside the new unit test** (`master()`/`slave()`
  registry rows borrowed from `test_amba_route_transform_predictor.py` so a row
  has exactly the columns a real one does).

## Concurrency

`git status` showed another agent mid-edit on `dv_harness/engine.py`,
`dv_harness/stage_profile_report.py` and a new `dv_harness/stage_progress_display.py`.
None was touched. This change is two NEW files and the commit staged exactly those
two paths — no broad `git add`, and no shared file needed a hand-scoped patch
because no shared file was modified.

## Not done here, deliberately

- Wiring a `SYOSCB_AMBA_SCOREBOARD_PHASE_1` stage id into
  `commands.APPROVAL_ONLY_STAGES` so `dv-harness approve` can record a durable
  ControlPlane approval. That is SYOSCB-33's own step, it touches a shared file
  another agent is not editing but which is outside this step's SYOSCB-29/30
  scope, and `amba_discovery_report._render_review_gate()` sets the precedent of
  rendering AMBA-30's gate text without one. Section 29 is the report half; the
  durable-approval half is a clean follow-on.
- No CLI entry point. Like the other three AMBA4/SYOSCB modules, this is a real,
  tested, callable Python API reached only by tests today (DORMANT with respect
  to `dv_harness/cli.py`). Adding a `dv-harness` verb for the whole SYOSCB Phase-1
  chain is one coherent follow-on for all of them, not a per-module one.
- No new agent (SYOSCB-32) and no new graph node.
