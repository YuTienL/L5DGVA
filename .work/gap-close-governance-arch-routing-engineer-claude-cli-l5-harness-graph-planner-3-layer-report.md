# Gap-close: Routing — Engineer → Claude CLI → L5 Harness Graph/Planner → 3 Layers

**Date:** 2026-09-04
**Scope:** the architecture diagram's fan-out arrows from the L5 Harness
Graph/Planner (`dv_harness/engine.py`'s `run_stage()` / `loop()`) into the
Knowledge, Governance, and Execution layers.
**Verdict:** **DONE** — one real, in-scope gap closed (Planner → Execution
Layer); one skill-file gap closed; one finding confirmed as
**NO_ACTION_NEEDED** (Planner → Governance is intended architecture, already
disclosed in CLAUDE.md); one finding confirmed **already real**
(Planner → Knowledge).

**Test summary:** `dv_harness_tests/test_execution_preflight_wiring.py` —
17/17 pass, and 8 of them fail when the new `run_stage()` call site is
mutated out (mutation-verified, not vacuous); the surrounding
preflight/engine/LSF suites pass unchanged.

---

## 1. Re-confirmation of the audit's evidence (checked myself, not taken on trust)

| Audit claim | Re-checked | Result |
|---|---|---|
| `engine.py` never imports `git_governance`, `lsf_client`, `pueue_client`, `evidence_db` | grep over the whole file | **Confirmed.** The only pre-existing hits were a `preflight.LocalCommandRunner()` prose comment (line ~478) and `run_stage()`'s own docstring naming `dv-harness lsf-submit`. |
| `memory_vault` IS imported and called from the Planner's flow | `engine.py:15` import + `_gather_stage_context()` call chain | **Confirmed.** Knowledge Layer needs no work. |
| Only 2 of 6 preflight checks reach the Planner, via `_degraded_gate()` → `degradation.evaluate()` | read `_degraded_gate()` and `degradation.py:245-270` | **Confirmed.** `degradation` imports only `check_license` / `check_queue_health`; `run_preflight()`'s full suite had **zero** callers in `engine.py`. |
| `devops-pipeline` SKILL.md names no real tool surface | read the file | **Confirmed.** Zero mentions of `just`, `pueue`, `preflight`, `lsf-submit`, `bsub`, `sbatch`. |
| Git hooks are installed | `git config --get core.hooksPath` → `tools/git-hooks`; both hook files present | **Confirmed** (CLAUDE.md's own text still says "NOT YET INSTALLED as of 2026-09-03" — stale, see §5). |
| `GIT_PUSH` / `BUILD` / `REGRESSION` are live graph nodes with the cited skills | parsed `.dv-harness/graph/main_graph.json` | **Confirmed.** `vcs-build` on `DE_BASELINE_REPRODUCTION`/`BUILD`/`BUILD_DEBUG`; `devops-pipeline` on `SERVER_SYNC`/`REGRESSION`/`INFRA_RECOVERY`. |

---

## 2. Edge: Planner → Knowledge Layer — **NO_ACTION_NEEDED**

Already `REAL_AND_CONNECTED` for the part that exists, and the two caveats the
audit raised are both correctly out of scope for a wiring fix:

- **Obsidian CLI is a capability-probe stub** — that is `memory_vault.py`'s own
  declared, documented state (`NOT_AVAILABLE` by module docstring), not an
  accidental disconnection. Making it operational is a new capability, not a
  wire.
- **DuckDB not reached from the Knowledge edge** — correct by design; DuckDB
  belongs to the Evidence Layer and is the subject of a separate effort
  (`06b3e68`). Wiring it into `memory_vault.py` would build a parallel path,
  not connect an existing one.

No file touched.

---

## 3. Edge: Planner → Governance Layer — **NO_ACTION_NEEDED** (intended, disclosed architecture)

The audit itself offered option (a): accept that git hooks are the correct
enforcement point. Re-reading CLAUDE.md's **"gh CLI + PR-Only Governance
Policy (2026-09-03)"** section settles it — the architecture is *explicitly
layered and explicitly written down*:

1. **Primary:** server-side branch protection (authoritative; "holds even if a
   local hook is missing or bypassed").
2. **Secondary:** `tools/git-hooks/pre-push` + `pre-merge-commit` →
   `dv-harness git-guard` → `dv_harness/git_governance.py`.

A direct `run_stage()` → `git_governance.evaluate_pre_push()` call (the
audit's option (b)) would be **strictly weaker and a parallel mechanism**:

- It would only cover pushes the harness knows about (the `GIT_PUSH` stage),
  while the hook covers **every** push from any tool, including ones the agent
  makes mid-stage from an unrelated node — which is precisely the case a
  governance gate exists for.
- The task's own instruction is to prefer wiring real existing pieces over
  building parallel mechanisms. The hook path is already installed and live in
  this working tree.
- Governance output **already** lands in the Planner's shared audit substrate:
  `cli.py`'s `git-guard` handler writes `GIT_GUARD_DECISION` into the same
  `StateStore`/`events.jsonl` `engine.py` uses. The layers are connected —
  through the shared evidence log, which is what the diagram's Evidence Layer
  box is for.

No file touched. (The diagram/doc correction the audit suggested is a
documentation edit to a file two other concurrent workflows are actively
editing — see §5.)

---

## 4. Edge: Planner → Execution Layer — **DONE** (gap closed)

### The gap, precisely

`run_preflight()` — the full 6-check suite (`lmutil lmstat`, `bqueues`,
`hostname`, `df -Pk`, `test -d`/`-w`, csh `$?VAR` env probe) — was reachable
**only** from `dv-harness preflight` and `dv-harness lsf-submit`, i.e. from two
CLI subcommands that a stage transition never reaches. The Planner's own flow
touched preflight only through `_degraded_gate()`'s 2-check slice, and only to
decide whether to skip an LLM judgment call — never to gate a build/regression
dispatch. So the diagram's "Planner → Execution Layer → Preflight Agent" arrow
had no code-level dispatch.

### What changed

**`dv_harness/engine.py`**
- New `DVHarness._execution_preflight_gate(stage)`, plus
  `_execution_preflight_cfg()` / `_execution_preflight_skills()` and the
  `EXECUTION_PREFLIGHT_SKILLS` constant.
- Called from `run_stage()` immediately after `_degraded_gate()` — i.e. **after**
  the TAKEOVER and dry-run short-circuits (a human holding the stage, and a
  read-only planning pass, must both stay possible while the farm is down), and
  **before** `_emit_stage_start_marker()` / `attempts += 1` / `adapter.run()`.
- New `self.execution_preflight_runner = None` injection seam in `__init__`,
  mirroring the existing `degradation_runner`.
- Behaviour: for a stage whose **real graph node** declares `vcs-build` or
  `devops-pipeline`, it runs `preflight.run_preflight()` against the project's
  existing `preflight` config block. On `BLOCKED` it parks the stage in
  `WAIT_USER` with the real `blocked_on` names in `blocking_reason`, writes an
  `EXECUTION_PREFLIGHT_BLOCKED` event (carrying the whole `PreflightResult`) to
  `.dv-harness/events.jsonl`, takes an auto-checkpoint, and returns before any
  agent is dispatched. On `PASS` it writes `EXECUTION_PREFLIGHT_PASS` and falls
  through.

**`dv_harness/config.py`** — new `execution_preflight` block:
`{"enabled": true, "probe_resources": false, "skills": ["devops-pipeline", "vcs-build"]}`.
It says only *when* to run the gate, never *what* to check — the checks come
from the shared `preflight` block, so there is no second place to configure
them.

**`.claude/skills/CORE/devops-pipeline/SKILL.md`** — new "Real CLI Surface"
section naming this project's actual, verified entry points (`just preflight` /
`build` / `verify` / `run` / `regress` / `pipeline` from the real `justfile`;
`dv-harness preflight`; `dv-harness lsf-submit` as the **only** real `bsub`
entry point; `dv-harness lsf*` monitoring; `dv-harness pueue add|chain|…` as
*local* orchestration, explicitly not farm submission), plus a note that the
harness now enforces preflight before dispatching this skill's stages. This
brings the agent-mediated Execution path up to the concreteness
`CORE/git-push-gate/SKILL.md` already has for Governance. Every command cited
was verified to exist (`justfile` recipe list, `cli.py` `add_parser` calls) —
nothing invented, honouring the skill's own "若 project 沒有實際 CI server/tool
config，不得 invent".

**`docs/ENGINE_STAGE_LIFECYCLE.md`** — new step `0c` in the run_stage lifecycle
table, new §4a documenting the gate, updated §5 interaction ordering and §6
test inventory.

### Design decisions worth stating

- **Scope from the graph, not a hardcoded stage list.** The gate reads
  `node.skills` from `.dv-harness/graph/main_graph.json`, so a project that adds
  its own build node inherits the gate for free, and a node-less/legacy stage is
  a silent no-op rather than a crash.
- **This does not replace `lsf_client.bsub_submit_with_preflight()`.** That
  remains the authoritative gate immediately before a real `bsub`, and keeps
  `require_license_configured=True`. The new gate is earlier and cheaper: it
  saves the *agent dispatch* (a real `claude` subprocess with full tool access),
  not the job submission. A test asserts the submission-time gate is unweakened.
- **`probe_resources` OFF by default**, for exactly the reason `config.py`
  already gives for `degradation.probe_resources`: the checks shell out to real
  EDA/scheduler binaries that exist only server-side, and reading "command not
  found" as a jammed farm would be a **fabricated BLOCK**. A server-side
  deployment turns it on; a PC-side one in REMOTE_EXECUTION mode assigns
  `preflight.RemoteRelayCommandRunner()` to `execution_preflight_runner`, which
  arms the gate on its own (an explicitly injected transport is itself the
  statement that a real probe is possible here — and is the seam every test
  drives a pure mock through).
- **Fails open on crash.** An unreachable probe leaves the stage running
  normally rather than stranding the harness — the same best-effort discipline
  `_degraded_gate()` and `_auto_checkpoint()` already apply.

### Tests — `dv_harness_tests/test_execution_preflight_wiring.py` (17 tests)

These are **edge** tests, not another round of unit tests: `preflight.py` was
already covered in isolation (`test_preflight.py`) and at the submission
boundary (`test_preflight_lsf_wiring.py`). What was untested was the
connection.

- `run_stage()` on `BUILD` really issues `preflight.py`'s **own** command
  strings (`lmutil lmstat -a -c 2900@host-a`, `bqueues vcs`, `hostname`, the
  `VCS_HOME` presence probe) over the injected transport, with the same call
  count `run_preflight()` itself would make — proving the aggregate gate is
  called, not a subset or a reimplementation.
- Changing only the shared `preflight` block changes the real probe
  (`bqueues regress_q`) — proving config reuse, not a second config.
- A starved-license `BLOCKED` verdict returns before `adapter.run()`
  (`_ExplodingAdapter` makes any dispatch a hard failure), parks `WAIT_USER`,
  spends **no** retry budget, and `loop()` does not advance past it.
- The decision lands in the shared `.dv-harness/events.jsonl` audit trail with
  the full `PreflightResult` — the same substrate `GIT_GUARD_DECISION` uses.
- A healthy verdict lets the stage dispatch normally and records
  `EXECUTION_PREFLIGHT_PASS` with `preflight.py`'s own full check set.
- Scope is asserted against the **real** project graph: the resolved
  execution-layer stages are exactly `{DE_BASELINE_REPRODUCTION, BUILD,
  BUILD_DEBUG, SERVER_SYNC, REGRESSION, INFRA_RECOVERY}`, and `INTAKE` never
  probes the farm.
- Config discipline: probe off by default is a real no-op; an injected
  transport alone arms it; `enabled:false` is a full bypass; a crashing probe
  never becomes an unbreakable block; TAKEOVER and dry-run still outrank the
  gate (a dry-run must not probe the farm).

All license/queue/env fixtures are the **real captured** outputs already used
by `test_preflight.py` / `test_harness_reliability.py`, imported rather than
re-typed, so the suites cannot drift and no test contacts a live license
server, scheduler, or host.

**Mutation check:** replacing the new `run_stage()` call site with `blocked =
None` makes **8 of the 17** fail. The tests measure the connection, not the
pieces.

---

## 5. Deliberately not touched (concurrent-workflow hygiene)

Other agents were editing this tree during this pass (a 14-AI-mechanism
audit+close workflow and a live remote USB build). `dv_harness/engine.py`
carried foreign in-flight hunks, so it was committed with a hand-scoped patch
(`git diff` → trim to my hunks → `git apply --cached --check` → `--cached`)
rather than a broad `git add`. `config.py`, `docs/ENGINE_STAGE_LIFECYCLE.md`
and the skill file contained only my hunks and were staged directly.

**Left for someone else:** `CLAUDE.md`'s governance section still says the git
hooks are "NOT YET INSTALLED as of 2026-09-03", but `git config --get
core.hooksPath` now returns `tools/git-hooks` and both hook files exist — the
text is stale by one day. That is a shared file another active workflow is
editing, and the staleness is in the direction of understating enforcement (not
overclaiming it), so it is reported here rather than edited from this pass.

---

## Bottom line

| Diagram edge | Before | After |
|---|---|---|
| Planner → Knowledge Layer | REAL_AND_CONNECTED | unchanged (no gap) |
| Planner → Governance Layer | REAL_BUT_DISCONNECTED as a *direct* call | unchanged — **intended**: hooks are the enforcement point, and Governance output already reaches the Planner's shared events log |
| Planner → Execution Layer | 2 of 6 preflight checks, for a different purpose; `run_preflight()` unreachable from a stage | **REAL_AND_CONNECTED** — `run_stage()` now calls `preflight.run_preflight()` for BUILD/REGRESSION-family stages and blocks the agent dispatch on a real BLOCKED verdict |
