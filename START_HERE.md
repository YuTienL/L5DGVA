# START HERE — AI Agent Harness L5

**This is the canonical entry point for this repository.** Every other root
`.md` file is either a pointer back to this page or a deeper-detail reference
linked from a section below — if you land on any other doc first, come back
here.

## What this is

AI Agent Harness L5 is a governed, evidence-driven DV (Design Verification)
workflow harness for Claude Code. It drives a UVM/protocol verification
project — from a single IP/Block up through Subsystem, Multi-Subsystem, and
Full-SoC scope — through a fixed 35-stage pipeline (`ENV_CHECK` → `INTAKE` →
… → `SIGNOFF`, defined in `dv_harness/models.py::Stage`), dispatching each
stage as a Claude Code subprocess call. What makes it a *harness* rather than
just a prompt: three independently-wired mechanisms (Graph routing, Hard
Gates, Human Control Plane — see below) decide what actually happens next,
instead of trusting the LLM's own claim that a stage passed.

As of this session, no real DUT has been run end-to-end through the engine —
what's verified is the harness's own mechanics (unit tests: 155 passing under
`dv_harness_tests/`; CLI; dashboard). Treat any protocol as `BUILDER_AVAILABLE`,
not `PRODUCTION_QUALIFIED`, until it has real DUT/VIP execution evidence
behind it (see Evidence Truth Rule below and `.dv-harness/qualification/protocol_capability_registry.json`).

## Quick command reference (chat-layer pseudo-commands)

```
CREATE ENVIRONMENT
MODE = SUBSYSTEM_MODE
TARGET = PCIe / USB / Ethernet / MIPI / AMBA4 / ...
```
```
CREATE ENVIRONMENT
MODE = SYSTEM_LEVEL_MODE
SELECT = completed subsystem environments
GOAL = cross-subsystem/system use-cases
```
```
CREATE ENVIRONMENT
MODE = SUBSYSTEM_MODE
TARGET = NEW_INTERFACE
INPUT = RTL + Spec + registers + PHY docs + VIP if available
```
These are typed into an interactive `claude` session (see CLAUDE.md), distinct
from the stateful `dv-harness` CLI/dashboard below -- REMOTE_CONTROL_MODE.md
covers controlling an already-running harness, not a third ENV mode.

## Getting started

**CLI** — from the project root:
```
python -m dv_harness --project-root . status
```
returns current stage/status as JSON. To actually drive a run through Claude
Code:
```
.\START_DV_HARNESS.ps1 -ProjectRoot . -Goal "<your DV goal>" [-Loop]
```
(runs `python -m dv_harness --project-root <root> start --goal <goal> [--loop]`
after verifying `claude` is on `PATH`). Every workflow must first declare its
Execution Mode — see Core Operating Rules below.

**Web GUI** — `dv_harness/dashboard.py` is a dependency-free `http.server`
app (no third-party pip dependency) started with:
```
python -m dv_harness.dashboard --project-root .
```
or `.\START_DV_HARNESS_DASHBOARD.ps1 -ProjectRoot .`, served at
`http://127.0.0.1:8765` (port from `.dv-harness/config.json`'s
`dashboard.port`). This session's dashboard work made the API real rather
than mock: `/api/state`, `/api/lsf` + `/api/lsf/jobs[/<id>]`, `/api/audit`,
`/api/graph` (all 35 stages + status, derived from live `state.json`, with a
"you are here" highlight), `/api/de-explain`, `/api/running`, plus
POST `/api/setup`, `/api/start`, `/api/control`, `/api/config`. The frontend
renders status tiles, LSF tiles, findings tiles, and the graph view with
✓/✗/▶/○ icons — deliberately does **not** show a fabricated "confidence"
number, since no such field exists in `HarnessState` and inventing one would
violate the Evidence Truth Rule below.

Both the CLI and the dashboard read/write the same on-disk state under
`.dv-harness/` — there is no separate GUI-only state.

**Install into a target project:** `.\INSTALL.ps1 -ProjectRoot <target>`
(copies `.claude/` in, backs up any existing one, runs preflight + workflow
init). Known issue: on Windows PowerShell 5.1 this currently fails with a
`char:18 '??*'` parse error (missing BOM in `.claude/tools/dv-readiness.ps1`)
— see `PACKAGE/USER_MANUAL.md`'s FAQ for the verified workaround.

## Core operating rules (from `CLAUDE.md`)

- **Execution Mode Gate.** Every workflow must begin by explicitly declaring
  `LOCAL_ANALYSIS` (local file analysis only — no server, no VCS) or
  `REMOTE_EXECUTION` (server/simulation access). Mixed work is split into
  explicit phases; local static findings must never be described as
  runtime/simulation evidence.
- **Evidence Truth Rule.** `CLAUDE.md`, memory, and prior agent summaries are
  not current evidence. Truth priority: current RTL/source > current
  waveform/FSDB measurement > current sim.log/assertion/scoreboard evidence >
  current register/programming state > versioned PHY/register/VIP docs >
  historical memory. If any doc (including this one) conflicts with current
  evidence, current evidence wins and the doc must be updated.
- **LSF DONE ≠ DV PASS.** A live `bjobs` DONE/EXIT never auto-promotes
  `sim_status` — `dv_harness/lsf_client.py::reconcile_job()` flags it
  `ANALYSIS_OWED` instead. One submitted LSF job = one isolated Job Agent
  context; kills are exact-`JOB_ID` only, never wildcard.
- **Waveform defaults to OFF.** Normal simulation/regression runs FSDB OFF;
  VIP trace/report may be enabled independently. Escalating to targeted FSDB
  on a first failure requires a user-confirmed dump scope/level first (see
  `.dv-harness/governance/waveform_dump_policy.json`).

## Core mechanisms (verified against current code)

- **Graph routing.** `.dv-harness/graph/main_graph.json` (37 nodes, 48
  edges) is read by `dv_harness/policy.py::graph_next()`, which is the real
  routing authority: a stage's PASS/FAIL/PARTIAL outcome is looked up in the
  graph to pick the next stage — e.g. a `BUILD`/`REGRESSION_MONITOR` failure
  triages through `BUILD_DEBUG`/`INFRA_RECOVERY` before full
  `FAILURE_RECOVERY` RCA, and `can_signoff()` can auto-redirect to
  `SERVER_SYNC`/`IMPLEMENT` on a SHA mismatch or open findings rather than
  just blocking.
- **Hard Gates.** `dv_harness/gates.py::STAGE_GATES` currently maps **28 of
  the 35 stages** to **137 gate-script invocations**, drawn from 183
  deterministic, stdlib-only validator scripts under `tools/`. A stage's
  Claude response must emit a ```dv-harness-evidence:<gate_id>``` fenced
  block; the engine runs the named gate script against that evidence and
  only promotes the stage to PASS if the gate exits clean — a successful
  Claude subprocess call alone is never treated as a PASS. (`PROTOCOL_CAPABILITY`
  and part of `VERIFICATION_ARCHITECTURE`'s `observability_sufficiency_gate`
  remain intentionally unwired pending contract verification — check
  `gates.py` directly for the current list, not an older doc's stage/gate
  counts, which predate this session's gate-wiring expansion.)
- **Human Control Plane.** `dv_harness/control_plane.py` persists
  `.dv-harness/control.json` and implements 12 verbs with real CLI
  subcommands `engine.py` actually reads and obeys every loop iteration:
  `status`, `explain`, `pause`/`resume`, `takeover`/`release-takeover`,
  `redirect`, `approve`, `evidence`, `correct`, `constraint`, `cosign`,
  `audit`. `takeover` is checked first in both `loop()` and `run_stage()`,
  so a human can hold a stage even against a direct CLI bypass of the loop —
  this is the concrete implementation of "Human Override is always valid."
- **Self-Audit.** `dv_harness/self_audit.py` runs 22 real gate scripts that
  check the HARNESS'S OWN registry/skill/pipeline/protocol-catalog
  consistency (not DUT evidence) via `dv-harness self-audit [--all|--gate ID]`
  and `GET /api/self-audit` on the dashboard -- both call the same shared
  implementation. Use this to check the harness's own configuration health,
  separate from any DUT verification run.
- **Memory Hierarchy.** `dv_harness/memory.py` implements five levels —
  working / job / project / engineering / organizational — kept distinct
  from the `Blackboard` (current-run truth, not historical). New knowledge
  records are routed by `dv_harness/memory_router.py::route_and_store()` to
  the right memory level, to the `Blackboard`, to Claude's own project
  memory (surfaced as an action, not written directly), to the
  `CornerCaseLibrary`, or rejected outright if it looks credential-like.
  `MemoryRetriever.search()` ranks by Context/Protocol/Symptom/Evidence
  Strength plus Recency (exponential decay, ~90-day half-life).

## Environment Generation Mode

Before `CREATE ENVIRONMENT`, pick a mode (also in `CLAUDE.md`):
- **SUBSYSTEM_MODE** — build one protocol/subsystem environment (PCIe, USB,
  Ethernet, MIPI CSI-2/DSI, CAN-FD, AMBA4, eMMC, SD/SDIO, eDP, UCIe, or a new
  interface/spec via the plugin onboarding flow).
- **SYSTEM_LEVEL_MODE** — select/reuse completed subsystem environments and
  compose a Full-SoC/System-Level environment; a missing subsystem routes
  back through SUBSYSTEM_MODE first, then returns to composition.

Full procedural detail: `CREATE_ENVIRONMENT.md`.

## Where deeper detail lives

- **`PACKAGE/README.md` and `PACKAGE/USER_MANUAL.md`** (in the sibling
  `D:\DV\Task\DV_Agent_Harness_L5\PACKAGE` directory, built this session) —
  the most rigorously fact-checked reference: every command output in
  `USER_MANUAL.md` was actually run against the packaged code, not written
  from memory. Read these for the full CLI subcommand list, the dashboard's
  complete control surface, and a stage-by-stage walkthrough.
- **`dv_harness_tests/`** — the package's own pytest suite (3 files, 132
  tests) is executable documentation of exactly what the engine, gates, and
  control plane currently guarantee. When in doubt about behavior, the test
  file is more current than any prose doc.
- **`.claude/skills/`** — protocol builders (`USB`, `PCIe`, `Ethernet`,
  `MIPI`, `AMBA`, `CAN`, `SOC_BUILDERS`, …) and core workflow skills
  (`CORE`, `DUT_ARCHITECTURE`, `OBSERVABILITY`, `VPLAN_INTAKE`,
  `VPLAN_DRIVEN`, `QUALIFICATION`, `EXPERT_FEEDBACK`, `EXTENSIBILITY`,
  `REFERENCE_BASE`, `SENIOR_DV_REASONING`, `ENVIRONMENT_ROUTER`,
  `SOC_COMPOSITION`, `UNIFIED_REAL_ENV`, `UNIVERSAL_PROTOCOL`,
  `REAL_PROJECT_GENERATION`, `REAL_ENV_GENERATION`).
- **`SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md`** — the fuller narrative of
  the senior-DV-engineer operating model and golden closed loop.
- **`VERIFICATION_ARCHITECTURE_MECHANISM_FIRST.md`** — the detailed,
  step-numbered source of truth for verification workflow *order*
  (Architecture Discovery/Calibration before vPlan finalization — mechanism
  before test generation).
- **`FINAL_PACKAGE_INDEX.md`** — capability-group index and current
  skills/agents/iron-rules counts.
- **`CHANGELOG_v0_to_v50.md`** — what actually changed this session versus
  the untouched `v0/` baseline (gate wiring, engine bug fixes, memory router
  wiring, `lsf_client.py`, dashboard rework, graph routing) — read this
  before trusting any older doc's specific numbers or claims.
- **`DUT_ARCHITECTURE_DISCOVERY_AND_CALIBRATION.md`,
  `SCOREBOARD_CHECKER_ASSERTION_ANALYZER.md`,
  `VPLAN_INTAKE_WIZARD.md`, `VPLAN_DRIVEN_SPEC_COVERAGE.md`,
  `STAGE_EXECUTION_PROFILE.md`, `GIT_DEVOPS_ONE_PAGE.md`,
  `REMOTE_CONTROL_MODE.md`, `SOC_SYSTEM_LEVEL_COMPOSER.md`,
  `OPERATING_MODES.md`, `EVIDENCE_TRUTH_RULE.md`,
  `DV_EXPERT_FEEDBACK_CLOSED_LOOP.md`, `WORKFLOW_CLOSURE_ONE_PAGE.md`,
  `PROTOCOL_SUPPORT_MATRIX.md`, `LSF_PER_JOB_AGENT_MONITORING_v16_1.md`,
  `LSF_STRICT_PER_JOB_IRON_RULES_v19_1.md` — standalone one-page mechanism
  references, each still accurate for the narrow topic it covers; not
  duplicated at length here to avoid yet another copy drifting out of sync.
- **`REMOTE_LOGIN_GUIDE.md`** — connecting to the Linux DV server via the
  persistent relay (`tools/remote/`): starting/reconnecting a relay,
  `remote_exec.py` usage, the `VCWORKDIR` vs. `--project-root` distinction.
- **`KNOWLEDGE_CENTER_GUIDE.md`** — the shared cross-user Knowledge Center
  (`/home/svcacct/AI/DB`): setup, commands, and why it is safe for
  concurrent multi-user writes (`fcntl.flock` + atomic writes in
  `tools/knowledge_center/broker.py`).
- **`DEBUG_WORKFLOW_GUIDE.md`** — the end-to-end loop for debugging a
  `UVM_ERROR` in a DE's own generated VIP environment from PC-side Claude
  Code: evidence gathering, the Waveform Dump Gate, DE approval points,
  running simulation in the DE's own `DVWORKDIR`, and redeploying a
  regenerated environment.
- **`USAGE_MULTI_USER_SAFETY.md`** — the single place that answers "is it
  safe for multiple people to use the shared `/home/svcacct/AI/Agent`
  deployment at the same time," layer by layer (Knowledge Center: yes;
  relay command execution: yes as of 2026-09-02; relay shared shell state:
  only with `--cwd`; per-project `.dv-harness/` runtime state: never share
  a `--project-root`).

Every other root `.md` not listed above is either superseded (banner at the
top says so and names the current doc) or a quick-start variant that now
redirects to `CREATE_ENVIRONMENT.md`.
