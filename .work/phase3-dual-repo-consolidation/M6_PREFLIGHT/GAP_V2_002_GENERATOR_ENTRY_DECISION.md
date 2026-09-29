# GAP-V2-002 Human Decision Gate — `tools/generate_protocol_uvm_environment.py`

Analysis only, per explicit instruction — no code changed, no option chosen.
`PROCESS_CWD = D:/DV/Task/L5_DGVA`, `CURRENT_HEAD = ece23bd1dfb7ed7d905bc253ef64222e28ba3645`,
working tree clean before and after this analysis. All 5 frozen sources
(Parent/v50/b7a/b7b/b8) re-verified unchanged, byte-identical to every
prior checkpoint SHA this session.

## 1. Real callers — traced exhaustively

Exhaustive repo-wide search for the literal string
`generate_protocol_uvm_environment` across `*.py *.md *.json *.sh *.ps1`
(every category the dispatch names: CLI, agents, skills, Claude/project
instructions, workflow/graph, tests, scripts, dashboard, Native Claude
integration, other Python callers).

```
REAL_CALLERS = 13
  11  .claude/skills/PROTOCOL_BUILDERS/*/SKILL.md
       (amba4-soc, canfd, edp, emmc, ethernet, mipi-csi, mipi-dsi, pcie,
       sd, ucie, usb -- every one instructs an agent to run this script
       as its own final "Generate / Integrate" step)
   2  dv_harness_tests/test_protocol_env_generator.py,
       dv_harness_tests/test_system_level_soc_composition_wiring.py
       (real `subprocess.run([sys.executable, ".../generate_protocol_
       uvm_environment.py", ...])` calls -- regression tests proving the
       CLI script itself works, not production usage)

UNKNOWN_RUNTIME_CALLERS = 0
```

Checked and confirmed **zero** references in: `dv_harness/cli.py` (no
`dv-harness` subcommand wraps this script), `dv_harness/dashboard.py` (no
HTTP endpoint), `dv_harness/skill_resolver.py`/`router.py`/`multi_agent.py`
(no code-level skill-dispatch mechanism names it or the
`PROTOCOL_BUILDERS` directory — the one hit in
`dv_harness/claude_reference_graph.py` is a discoverability keyword
mapping for humans/agents searching the repo, not an invocation path).
Every other match (`generation_readiness.py`, `signoff_export.py`,
`uvm_generator/generator.py`, `CLAUDE.md`, various `.work/*.md` reports)
is a citation in prose/docstring text, confirmed by direct read, never a
call.

`CLAUDE.md` itself (line ~1025, dated 2026-09-04, predates this session's
M6 work) states plainly: *"the one official CREATE ENVIRONMENT entry
point, `tools/generate_protocol_uvm_environment.py` (the script all ten
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` invoke)"* — this is a
deliberately designed entry point, not an accident or a forgotten
artifact, under the governance model that existed before `CAP-M6-
CLARSVC-001`/`CAP-M6-C1-001` built the OpenSpec/lifecycle-based Golden
Workflow this session.

## 2. Tracing the calling AI agent/skill — real executable path, not documentation alone

All 11 `SKILL.md` files share one structure (confirmed by direct read of
`usb-environment-builder/SKILL.md` in full, and a `grep` cross-check of
all 11):

```
## Evidence Inputs        -- inspect current DUT RTL/source, spec, PHY docs,
                              VIP manual, project config
## Discover Before Generate -- protocol-specific facts (e.g. USB: host/
                              device role, USB2/USB3 mode, port topology,
                              PHY/controller boundary)
## Generate / Integrate    -- run tools/generate_protocol_uvm_environment.py
## Mandatory Gates         -- protocol_builder_registry_conformance_gate,
                              Naming & Comment Hygiene, Evidence Truth Gate,
                              Multi-Agent Evidence Consensus, Independent
                              Synthesis, "Environment Manifest approval
                              when topology is uncertain/high impact",
                              Compile PASS, Smoke Simulation PASS, Exact
                              SHA/evidence provenance
```

Traced each item against the REAL executable path, not inferred from the
prose:

| Item | Real mechanism found | Verdict |
|---|---|---|
| Project attach/rehydration | none -- no `lifecycle.py`/`LifecycleStore` reference anywhere in the 11 skill files or the target script | **ABSENT** |
| Intake | "Evidence Inputs"/"Discover Before Generate" sections -- real, substantive, PROMPT-level instructions to the invoking agent | **PRESENT, but prompt-enforced only** (an LLM agent is trusted to follow it; no code verifies it happened) |
| Auto Discovery | same as Intake | **PRESENT, prompt-enforced only** |
| Field Resolution | none -- no `intake_field_resolution.FieldControl`/`resolve_field()` reference anywhere in this call chain | **ABSENT** (a structurally different, code-enforced mechanism built by `CAP-M5-ATL007-001`/`CAP-M6-CLARSVC-001`, never wired here) |
| Clarification | none -- no `clarification_service`/`question_queue.add_question()` reference in the 11 skill files or the script | **ABSENT** |
| HumanGate | "Environment Manifest approval when topology is uncertain/high impact" is named as a Mandatory Gate, but a repo-wide grep for `Environment Manifest approval`/`environment_manifest_approval` found **zero** code implementing it -- it is prose only, not backed by `question_queue.py`'s real Tier-3 escalation or any other persisted, auditable mechanism | **ABSENT as a code-enforced gate; a prompt-level instruction only** |
| Task Boundary | none -- no `task_boundary_conformance` reference | **ABSENT** |
| Lifecycle state transition | none -- the script's own `main()` never touches `.dv-harness/lifecycle.json` | **ABSENT** |
| A real, code-backed gate DOES exist | `protocol_builder_registry_conformance_gate.py` (real Python, real tests, wired into `dv_harness/gates.py`'s `STAGE_GATES["PROTOCOL_CAPABILITY"]`) -- but it validates the AGENT'S OWN SELF-REPORTED checklist/evidence-citation profile, cross-checked for internal consistency and a keyword-plausibility signal against the declared protocol; it does not independently re-derive the evidence itself, and nothing in this call chain requires it to have run before `tools/generate_protocol_uvm_environment.py` is invoked | **REAL but SELF-ATTESTED, and its own Stage (`PROTOCOL_CAPABILITY`) is not proven to precede this script's invocation in the skill-invoked path** |

`CALLING_AGENT_HAS_REAL_GOVERNED_INTAKE = MIXED` — real, substantive
evidence-gathering discipline exists at the PROMPT level (an agent
following the skill faithfully does inspect real DUT/spec/VIP evidence
before generating), but **zero** of it is the SAME code-enforced
mechanism (`lifecycle.py`/`intake_field_resolution.py`/
`clarification_service.py`/`question_queue.py`/`task_boundary_
conformance.py`) the M6 Golden Workflow built. The one real, code-backed
gate that exists (`protocol_builder_registry_conformance_gate`) checks
self-attestation, not independently-verified ground truth, and is not
provably sequenced before this script's own invocation by any code this
task could find.

## 3. Current authority — evidence, not assumption

```
CURRENT_TOOL_ROLE = AMBIGUOUS
```

Justification for `AMBIGUOUS` over the other four:

- **Not cleanly `NORMAL_WORKFLOW_ENTRY`**: a normal workflow entry in this
  program's own established vocabulary (`start_lifecycle()`) means
  convergence on `lifecycle.py`'s real state machine, `question_queue.py`'s
  real HumanGate, and `task_boundary_conformance.py`'s real check. None of
  the three exists in this call chain, at the code level, ever.
- **Not cleanly `INTERNAL_GENERATION_PRIMITIVE`**: that would mean the
  tool is invoked ONLY beneath an already-governed lifecycle (the way
  `create_environment()` itself now legitimately is, from `engine.py`'s
  own generation branch, `CAP-M6-C1-001`). This script is invoked directly
  by an agent/skill with no such precondition, checked or enforced.
- **Not cleanly `AUTHORIZED_LOW_LEVEL_BYPASS`**: that requires an
  explicit, non-default, scoped, auditable declaration (this program's own
  established pattern: `start --advanced`/`run-stage --advanced`, each
  recording a real `LifecycleStore.record_bypass()` entry). No such
  declaration exists for this script anywhere.
- **Not cleanly `UNCONTROLLED_BYPASS`** either, in the sense that word
  usually carries in this program (a forgotten, negligent, undocumented
  gap): this script is a DELIBERATELY DESIGNED entry point,
  `CLAUDE.md`'s own resident text calls it "the one official CREATE
  ENVIRONMENT entry point," and 11 real skill files with real (if
  prompt-level) discovery/evidence/gate discipline invoke it on purpose.
  Calling it "uncontrolled" would understate the real governance that
  does exist at the prompt layer.

The honest classification is a genuine hybrid the dispatch's own
5-value vocabulary anticipates exactly for this case: real, intentional
governance exists, but not the SAME governed mechanism the current Golden
Workflow uses, and no code connects the two.

## 4. Option A — converge on the Canonical governed lifecycle

**Architecture**: `AI Agent/Skill -> start_lifecycle() -> Intake/Field
Resolution/HITL -> Dispatch -> generation`. Concretely: each of the 11
`SKILL.md` files' own "Generate / Integrate" step would call
`DVHarness(root).start_lifecycle(goal, protocols=[...],
generation_request=<manifest>, generation_out_dir=<out>)` (the real,
tested, `CAP-M6-C1-001` mechanism) instead of shelling out to `tools/
generate_protocol_uvm_environment.py` directly. No recursion risk:
`start_lifecycle()` already calls `create_environment()` directly, never
back into itself or into this script.

**Impact**:
- 11 `SKILL.md` files' own "Generate / Integrate" section would need
  rewriting (a real, moderate-size doc-and-behavior change, not a
  one-line edit — each skill's own manifest-assembly step would need to
  become a `start_lifecycle()` call with the right kwargs).
- `tools/generate_protocol_uvm_environment.py` would become vestigial for
  this call path (still usable directly for the 2 existing regression
  tests, or deleted/kept as a low-level primitive per Option B).
- The skill's own real "Discover Before Generate" step would need to feed
  its findings into `generation_field_controls.py`-shaped `FieldControl`s
  or a `generation_request` manifest — today `generation_field_controls.py`
  only governs ONE field (`protocol`); the richer per-protocol discovery
  (role, mode, topology, PHY boundary) an agent currently gathers would
  either stay ungoverned inside the `generation_request` manifest dict (no
  worse than today) or would need its own new `FieldControl`s (a bigger,
  currently out-of-scope expansion of `generation_field_controls.py`).
- Every project using a `PROTOCOL_BUILDERS` skill would gain a real
  `.dv-harness/lifecycle.json` and enter the M6 Golden Workflow's own
  state machine, whether or not the agent/user wanted the FULL DV
  lifecycle (regression, signoff, etc.) — a real behavior/scope change for
  every current caller, not merely an internal refactor.

## 5. Option B — internal generation primitive, callers migrate to the governed entry

**Architecture**: normal callers (the 11 skills) migrate to calling
`start_lifecycle(generation_request=...)` (same as Option A's own
architecture change for the SKILL layer), but `tools/generate_protocol_
uvm_environment.py` itself is RE-LABELED (not necessarily deleted) as an
internal primitive — its own docstring/header would say so explicitly,
the same way `run-stage`/`.loop()` remain reachable internal primitives
under `CAP-M6-DISPATCH-001`'s own policy. The 2 existing regression tests
that call it via `subprocess` continue to work unchanged (they exercise
the primitive directly, exactly as `test_start_lifecycle_dispatch.py`
exercises `run_stage()` directly for low-level coverage).

**Impact**: functionally identical migration cost to Option A for the 11
skill files (the real work — rewriting "Generate / Integrate" — is the
same). The difference from Option A is purely a labeling/contract
question: does the script's own continued existence, after migration,
carry an explicit "internal primitive, not a supported standalone entry
point" contract (documented, perhaps with a runtime warning), or is it
simply retired? This task does not resolve that secondary question either
— it is downstream of whichever of A/B/C is chosen.

## 6. Option C — explicit, authorized low-level bypass

**Architecture**: `tools/generate_protocol_uvm_environment.py` keeps its
current, unmodified behavior, but gains an explicit, auditable "this is a
declared bypass" contract matching `CAP-M6-DISPATCH-001`'s own established
policy shape: printed/logged non-default warning, a real recorded event
(the script would need to write a `LIFECYCLE_BYPASS`-shaped record
somewhere — today it has no `.dv-harness/` write path of its own at all,
so this would be new, real code, not a documentation change), and an
explicit statement in all 11 `SKILL.md` files that this is a scoped,
authorized bypass of the Canonical lifecycle, not a second qualified
workflow.

**Impact**: the smallest CODE change of the three options (add an
audit-event write + a header/doc statement; no `SKILL.md` behavior
change), but it is the option this dispatch's own instructions most
directly warn against choosing "merely for backward compatibility
convenience" — and this task found no OTHER concrete engineering need for
it (no performance requirement, no offline/no-lifecycle use case
documented anywhere in the 11 skills or the script) beyond preserving the
current, already-working call shape. If that is nonetheless the real
reason (a genuine engineering need this analysis did not surface — e.g.
the `IP_UVM_DV_Gen`-style workflows may deliberately want a
lifecycle-free, single-shot tool for CI/batch use outside any project's
own `.dv-harness/` state), only a human with that context can confirm it.

## 7. Prime Directive test, per option

| Principle | Option A (converge) | Option B (primitive + caller migration) | Option C (authorized bypass) |
|---|---|---|---|
| `CONNECT_BEFORE_EXPAND` | Satisfies directly -- connects a real, currently-disconnected production edge | Satisfies directly, same connection | Does NOT connect it -- formalizes the disconnection instead |
| `OPERATIONAL_BEFORE_CLAIMED` | Requires the migration to be REAL (WIRED+TRIGGERED+CONSUMED in production for all 11 skills), not merely claimed -- a real, non-trivial verification burden | Same requirement, same burden | N/A -- no new OPERATIONAL claim is made; the current, honest "this bypasses governance" claim becomes explicit instead of implicit |
| `CLOSE_THE_LOOP` | Closes it for generation triggered via a skill | Same | Does not close it; the loop stays open by design, disclosed |
| `NO_CAPABILITY_ISLANDS` | Removes the island | Removes the island | The island remains, but stops being an UNDISCLOSED one -- becomes a documented, bounded exception, closer to (but not identical to) `run-stage --advanced`'s own accepted island-with-a-name |
| `FIND_FIX_VERIFY` | This IS the fix, if chosen -- but doing it without a human confirming the real per-skill discovery-to-FieldControl mapping (section 4's own disclosed gap) risks a well-intentioned but incomplete fix, exactly what P5 warns against doing without real verification | Same risk/benefit as A | Does not "fix" the underlying disconnect; converts an undisclosed gap into a disclosed, scoped one -- itself a legitimate P5 outcome when a real engineering need justifies keeping the bypass (this task did not confirm one) |
| `ONE_GENERIC_DE_DV_WORKFLOW` | Reinforces it -- one workflow, all entry points converge | Same | Preserves a second, parallel entry point outside the one workflow, indefinitely |
| `ONE_CANONICAL_INTAKE_ENGINE` | Reinforces it | Same | Preserves a second, un-integrated discovery mechanism (the skill's own "Discover Before Generate") permanently outside the Canonical one |
| `ONE_CANONICAL_FIELD_RESOLUTION_ENGINE` | Requires care (section 4): must route the skill's richer discovery through the EXISTING engine, not invent a second one for the extra fields it discovers today | Same requirement | Not implicated -- the skill's own discovery stays exactly as informal as it is today, never claiming to be the canonical engine |
| `UNCONTROLLED_BYPASSES_TARGET = 0` | Reduces real uncontrolled bypasses toward the target | Same | Does NOT reduce it toward 0 in the strict sense (a bypass still exists) -- but converts it from `UNCONTROLLED` to a named, `AUTHORIZED` one, which is what the target's own name (`UNCONTROLLED`, not `NO_BYPASSES`) implies is the accepted end state for a genuinely justified case |

## 8. Decision Report Fields

```
GAP_V2_002_STATUS = HUMAN_DECISION_REQUIRED

REAL_CALLERS = 13  (11 .claude/skills/PROTOCOL_BUILDERS/*/SKILL.md +
  2 subprocess-level regression tests; 0 CLI/dashboard/workflow-graph/
  code-level callers)
UNKNOWN_RUNTIME_CALLERS = 0

CALLING_AGENT_HAS_REAL_GOVERNED_INTAKE = MIXED
  -- real, substantive Evidence-Inputs/Discover-Before-Generate discipline
  exists at the PROMPT level in all 11 skills, verified by direct read,
  not inferred; ZERO of it is the same code-enforced mechanism
  (lifecycle.py/intake_field_resolution.py/clarification_service.py/
  question_queue.py/task_boundary_conformance.py) the M6 Golden Workflow
  uses; the one real code-backed gate in this chain
  (protocol_builder_registry_conformance_gate) validates agent
  self-attestation, not independent evidence, and its own Stage
  (PROTOCOL_CAPABILITY) is not provably sequenced before this script's
  invocation by any code found.

CURRENT_TOOL_ROLE = AMBIGUOUS
  -- deliberately designed (CLAUDE.md's own "official entry point"
  framing, dated 2026-09-04, pre-dating this session's M6 work) with real
  prompt-level governance, but zero code-level connection to the Canonical
  lifecycle/HumanGate/Task-Boundary mechanism, and no explicit/recorded/
  scoped bypass declaration either -- does not cleanly fit
  NORMAL_WORKFLOW_ENTRY, INTERNAL_GENERATION_PRIMITIVE,
  AUTHORIZED_LOW_LEVEL_BYPASS, or (the negligent-gap sense of)
  UNCONTROLLED_BYPASS without misrepresenting the real evidence found.

OPTION_A_IMPACT = Converges all 11 SKILL.md files onto start_lifecycle();
  removes the capability island and the un-governed second call path;
  requires real, verified migration of each skill's own richer per-
  protocol discovery into FieldControl-shaped evidence (a real expansion
  of generation_field_controls.py beyond its current single `protocol`
  field, itself new scope, not yet built); every project using a builder
  skill gains a real lifecycle.json and enters the Golden Workflow's own
  state machine, a real behavior change for every current caller.

OPTION_B_IMPACT = Same migration work and same island-removal outcome as
  Option A for the 11 skills; additionally re-labels the script itself as
  an internal primitive (documentation/contract change only) rather than
  retiring it, preserving the 2 existing subprocess-level regression
  tests' own direct-primitive coverage unchanged, mirroring this
  program's own accepted run-stage/.loop() "internal primitive, not
  deleted" precedent.

OPTION_C_IMPACT = Smallest code change (an audit-event write this script
  does not currently have, plus explicit bypass language in CLAUDE.md and
  all 11 SKILL.md files); does not close the capability island; this
  analysis found no concrete, currently-documented engineering need for
  keeping generation lifecycle-free (no CI/batch/offline use case
  documented anywhere in the 11 skills or the script) beyond preserving
  the existing call shape -- if such a need is real, only a human with
  that context (e.g. how IP_UVM_DV_Gen or similar workflows are actually
  operated day to day) can confirm it; this task did not find it in the
  repo's own evidence.

ARCHITECTURE_CONFLICTS = 0
  -- no option, correctly implemented, would create create_environment.py-
  as-orchestrator inversion or lifecycle recursion; Options A/B's own
  architecture (Agent/Skill -> start_lifecycle -> generation) is the same
  direction CAP-M6-C1-001 already established and verified for CLI/
  dashboard. The real open question is migration completeness/scope (the
  FieldControl expansion noted above), not a structural conflict.

PRODUCTION_CONNECTIVITY_IMPACT = Today, M6_PRODUCTION_CONNECTED_STAGES=8
  counts only the CLI/dashboard -> start_lifecycle() -> create_environment()
  edge (CAP-M6-C1-001). Options A/B would add a SECOND real production
  entry point (the 11 skills) reaching the same governed mechanism,
  genuinely widening production connectivity beyond today's count, but
  ONLY once the FieldControl-expansion gap above is also closed with real
  evidence (P5 discipline: a claimed connection must be verified, not
  merely wired). Option C leaves PRODUCTION_CONNECTIVITY_IMPACT = NONE for
  this edge -- it remains outside the measured Golden Workflow, by
  disclosed design rather than by accident.

RECOMMENDED_OPTIONS_SUPPORTED_BY_EVIDENCE = A or B
  (without choosing between them for you): both are equally well-supported
  by the evidence found -- neither creates an architecture conflict, both
  remove the real, confirmed capability island, and the difference between
  them (delete vs. relabel-and-keep the script as an internal primitive)
  is a secondary packaging question, not a governance one. Option C is
  supported ONLY if a real, currently-undocumented engineering need for a
  lifecycle-free generation path exists -- this analysis did not find one,
  so recommending C would require new evidence this task does not have.

CAP_M5M6_VLEVEL_001_STARTED = NO
```

## STOP

Analysis complete. No option chosen. No code, skill, or documentation file
modified by this task. Waiting for the human decision among A / B / C (or
a different resolution this analysis did not anticipate).
