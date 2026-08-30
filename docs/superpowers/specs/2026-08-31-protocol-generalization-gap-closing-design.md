# Protocol-Generalization Cross-Cutting Gap Closing — Design

Status: approved for implementation planning (2026-08-31)
Owner: peter.lin / yutien.lin01@gmail.com
Source evidence: `protocol-coverage-capability-audit` workflow (2026-08-30/31,
run ID `wf_4436dd7e-9e2`), 8 independent per-protocol audits + 1 synthesis,
covering PCIe, Ethernet, MIPI CSI-2, MIPI DSI, eMMC/MMC, SD/SDIO, CAN-FD,
AMBA SoC Bus (AXI/AHB/APB).

## 1. Problem

The audit found the harness's core architecture (manifest-driven generator
DSL, `STAGE_GATES` pipeline, intake schema) is genuinely protocol-agnostic
in its executable logic — not starting from zero for any of the 8
protocols audited, and several already have real dedicated generator
modules (`pcie_ltssm_generator.py`, `emmc_cmdq_generator.py`,
`canfd_arbitration_generator.py`, `amba_fabric_generator.py`). But every
one of the 8 protocols came back `NEEDS_TARGETED_GAP_CLOSING`, and 6 of the
audit's 8 identified cross-cutting gaps recur across most/all protocols —
per this project's own `CLAUDE.md` rule ("Once a real deficiency/weakness/
gap is confirmed by evidence... it must be closed by launching multi-agent
implementation work on all currently-known confirmed gaps together, not
queued one-at-a-time"), these get closed in one coordinated pass.

Two of the audit's 8 cross-cutting gaps are explicitly **out of scope**
for this spec (split out during brainstorming, per explicit user decision,
because they are real net-new capabilities, not wiring/cleanup fixes):

- Real SystemVerilog covergroup/coverpoint emission (today `coverage()`
  only emits `// COVER:` comments for every protocol) — needs its own
  design (coverage model, bin-definition source).
- A per-class UVM agent/driver/monitor emitter (`tb/agents` is empty for
  every protocol by the generator's own documented design) — same reason.

## 2. Goals

Close the remaining 6 cross-cutting gaps in one coordinated pass:

1. Archive self-flagged-dead duplicate skill directories.
2. Resolve the `generator.py` vs. `protocol_env_generator.py` wiring
   contradiction — `ProtocolEnvGenerator` becomes the one official entry
   point (explicit user decision).
3. Remove the two hardcoded `'USB_REFERENCE'` / `'USB_STANDARD_REFERENCE'`
   literals from gate pass/fail logic; replace with protocol-parametric
   evidence-class names.
4. Add the missing eMMC/MMC/SD-SDIO routes to `CORE/protocol-router`.
5. Cross-link each protocol's dedicated generator module into its own
   builder `SKILL.md`'s generator list.
6. Add protocol-specific evidence fields to `intake_readiness.py` for
   AMBA (fabric/topology) and SD/SDIO (UHS/CCCR/tuning).

## 3. Non-goals

- Covergroup/coverpoint emission and per-class agent emitters (§1) — future
  specs.
- Does not touch the remote-execution/relay work
  (`2026-08-30-persistent-remote-relay-design.md`) — unrelated subsystem,
  already a separate in-flight spec.
- Does not attempt an end-to-end pilot generation for any of the 8
  protocols with real VIP/RTL evidence — the audit's own
  `recommended_next_step` explicitly gates that on this fix pass landing
  first, and on the user supplying real per-protocol source material,
  which is a data-availability question this spec cannot resolve.
- Does not change any protocol's actual generated *content* (sequences,
  scoreboard checks, register maps) — every change here is wiring,
  cleanup, or gate/schema generalization, never protocol-behavior
  authoring, so `CLAUDE.md`'s "No Golden-Reference Content Mining" rule is
  not implicated.

## 4. Task Design

All six tasks touch **disjoint files** (verified against the audit's
`evidence_files` lists) — genuinely independent, no ordering dependency,
suitable for parallel subagent-driven execution.

### Task 1 — Archive dead duplicate skills

Move (not delete — `v50` has no git, so there is no undo) every
self-flagged-dead duplicate under:
- `.claude/skills/UNIVERSAL_PROTOCOL/*-production-builder`
- `.claude/skills/REAL_PROJECT_GENERATION/*-complete-env-generator`
- `.claude/skills/REAL_ENV_GENERATION/*-real-env-generator`

for the 7 affected protocols (PCIe, Ethernet, MIPI CSI-2, MIPI DSI, eMMC,
SD/SDIO, AMBA — CAN-FD's audit did not flag duplicates in these three
trees) into `.claude/skills/_deprecated/<original-relative-path>/`,
preserving each directory's internal structure.

**Before moving each one**, grep for its skill `name:` (from its
`SKILL.md` frontmatter) across `.dv-harness/builder/
protocol_builder_registry.json`, every `.claude/skills/**/SKILL.md`
(router/dispatch references), and `.claude/agents/*.md`. If any live
reference is found, stop and report it instead of moving that skill — the
audit's "self-flagged dead" claim must be re-verified at move time, not
trusted blindly from a report written hours earlier.

**Acceptance**: after the moves, `dv-harness self-audit` (the existing 23
harness self-audit gates) shows no new failures compared to a pre-change
baseline run, and a repo-wide grep for each moved skill's directory name
under its old path returns nothing outside `_deprecated/`.

### Task 2 — Resolve generator wiring contradiction

`protocol_env_generator.py`'s `ProtocolEnvGenerator` is the one official
generation entry point (confirmed live via `tools/
generate_protocol_uvm_environment.py`). `dv_harness/uvm_generator/
generator.py`'s top-level flat `generate()` orchestration is internal/
deprecated relative to that CLI path (its lower-level emit methods stay in
use — they're composed by `ProtocolEnvGenerator`, per the audit's
generator_dsl_gap finding — only the flat top-level orchestration function
itself is deprecated, not the file).

Fix every stale/contradictory notice found by the audit so all of them
agree with this:
- `generator.py`'s own header NOTICE (currently claims outright orphaned —
  correct to "flat `generate()` orchestration deprecated; emit methods
  remain live via `ProtocolEnvGenerator` composition").
- `.claude/agents/IP_UVM_DV_Gen.md`'s conflicting claim (MIPI DSI audit
  finding) that cites `generator.py` as the authoritative direct entry
  point — correct to point at `ProtocolEnvGenerator`/the CLI instead.
- Any other file a repo-wide grep for `"orphaned"` near `generator.py`
  turns up that makes a wiring claim.

**Acceptance**: a fresh repo-wide grep for wiring-status claims about
`generator.py` (`orphaned`, `not wired`, `authoritative`, `entry point` in
its neighborhood) shows a single consistent story across every file that
makes one.

### Task 3 — Generalize hardcoded USB evidence literals

`tools/verification_flow/input_source_contract_gate.py`'s `required` set
currently includes the literal `"USB_REFERENCE"`; `tools/
verification_flow/master_requirement_completeness_gate.py`'s `REQ` set
currently includes the literal `"USB_STANDARD_REFERENCE"`. Both gates run
for every protocol via `STAGE_GATES['DISCOVERY']` /
`STAGE_GATES['REQUIREMENT_CLOSURE']`.

Rename to protocol-parametric evidence-class names —
`"PRIMARY_PROTOCOL_REFERENCE"` and `"PROTOCOL_STANDARD_REFERENCE"`
respectively — satisfied by whatever primary spec/manual evidence tag the
current protocol's intake actually supplies (VIP user manual/class
reference for branch-B, DUT/PHY programming guide for branch-A, per
`CLAUDE.md`'s existing sourcing rules), not tied to any protocol name.

**Acceptance**: existing unit tests for these two gate scripts (add if
none exist) pass with a non-USB protocol's evidence payload using the new
key name, and fail (as `MISSING_EVIDENCE`, not a crash) when that key is
absent — mirroring current behavior, just renamed.

### Task 4 — Add missing protocol-router routes

`CORE/protocol-router/SKILL.md`'s primary-route list omits eMMC, MMC, and
SD/SDIO despite `.dv-harness/builder/protocol_builder_registry.json`
already having full registry entries for them (confirmed by the audit).
Add the three missing routes, matching the existing entries' format
exactly (same registry-lookup pattern already used for PCIe/Ethernet/
etc. — read the current file to match its exact structure before editing,
do not invent a new format).

**Acceptance**: every protocol key present in
`protocol_builder_registry.json` has a corresponding route in
`protocol-router/SKILL.md` — a small grep-diff check between the two
files' protocol-key sets shows an empty symmetric difference.

### Task 5 — Cross-link dedicated generators into builder skills

Three builder skills each already ask an agent to hand-build logic that a
dedicated generator module already implements:
- `.claude/skills/PROTOCOL_BUILDERS/pcie-environment-builder/SKILL.md` —
  add a reference to `dv_harness/uvm_generator/pcie_ltssm_generator.py`
  (LTSSM transition model) in its generator list, with a one-line note on
  when to invoke it (LTSSM/link-training content).
- `.claude/skills/PROTOCOL_BUILDERS/emmc-environment-builder/SKILL.md` —
  add a reference to `dv_harness/uvm_generator/emmc_cmdq_generator.py`
  (CMDQ/tuning content).
- `.claude/skills/PROTOCOL_BUILDERS/canfd-environment-builder/SKILL.md` —
  add a reference to `dv_harness/uvm_generator/canfd_arbitration_generator.py`
  (arbitration/BRS/ESI/error-state content).

**Acceptance**: each of the three `SKILL.md` files' generator/tooling list
names its dedicated module by exact file path, with a sentence on which
content category it covers — not just an added file path with no context
for when an agent should reach for it over the generic DSL.

### Task 6 — Add missing intake evidence fields

`tools/vplan/intake_readiness.py` (or the appropriate
`interactive_evidence_intake_gate.py` companion, whichever actually owns
the field schema — confirm by reading both before editing) gets two new
protocol-specific evidence fields, each optional/inert for protocols that
don't need them (never required for e.g. USB or PCIe):

- AMBA: a fabric/topology evidence field (master/slave list, address map,
  fabric interconnect description) — required only when
  `execution_mode`/protocol context indicates an AMBA SoC-bus target.
- SD/SDIO: a UHS-mode/CCCR/tuning evidence field — required only when the
  protocol context indicates SD/SDIO.

**Acceptance**: an AMBA-context intake payload missing the new fabric
field now fails INTAKE with a clear `missing` reason (not silently passing
through to fail later at `VERIFICATION_ARCHITECTURE`, which is the exact
problem the audit flagged); a non-AMBA payload is unaffected by the new
field's absence.

## 5. Testing Strategy

- Tasks 3, 4, 6 are pure code/schema changes — TDD via `dv_harness_tests/`,
  one test file per touched gate/router/intake script, failing test first.
- Tasks 1, 2, 5 are file-move/documentation-consistency changes — verified
  by grep-based "no dangling reference" / "no contradictory claim" checks
  (exact greps specified per task above) plus a full `dv-harness
  self-audit` run before and after, diffed for new failures.
- No task in this spec touches remote execution, real VCS/LSF, or any
  Linux DV server path — everything here is local file/skill/gate edits,
  matching Execution Mode: LOCAL_ANALYSIS for the whole pass.

## 6. Consolidation

Per the Methodology Consolidation Rule: after these six tasks land, sync
`.claude/` (skills, including the new `_deprecated/` tree) to the
`industrial` and `PACKAGE` deliverable trees, same as any other engine/
skill change — this is itself a plan task, not a followup to remember
separately.

## 7. Open questions carried into implementation planning

- Exact current format of `CORE/protocol-router/SKILL.md`'s route table
  (Task 4) needs to be read fresh at implementation time — this spec
  intentionally does not guess its structure.
- Whether `intake_readiness.py` or `interactive_evidence_intake_gate.py`
  is the right file to own the two new fields (Task 6) needs the same
  fresh read before editing.
