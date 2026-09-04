# SYS-18..22 gap-close: System architecture report + System command.txt PLAN + Command IR + collision detection

**Status: DONE**

Commit `099ca15` — `system-level(SYS-18..22): System architecture report, System command.txt PLAN, Command IR, collision detection`.

Test summary: **53 new tests in `dv_harness_tests/test_system_command_plan.py`, all passing; 304 passed across the full relevant suite** (`test_system_command_plan`, `test_subsystem_architecture_and_command_contract`, `test_system_resource_inventory`, `test_system_resource_registry`, `test_subsystem_discovery`, `test_source_authority`, `test_system_level_soc_composition_wiring`).

---

## The audit was stale on its own central claim — re-verified before building

The audit reported SYS-19 and SYS-21 `NEVER_BUILT`, giving as the reason that "SYS-8's `SubsystemCommandContract` also not existing (same grep, zero hits) — there is no per-subsystem command representation for a System-level router to reuse, so 'reuse, don't reinvent' has nothing to reuse from yet."

That is no longer true. `dv_harness/subsystem_command_contract.py` (830 lines) has existed since commit `22070c1`, earlier in this same sequential build pass. The audit predates it.

The **verdicts** still stand — a fresh grep for `SystemCommandIR` / `system_command_ir` / `system_command_id` / `CommandRouter` / `command_collision` across every `.py` in the tree returned zero — but the **reason inverts**, and that changed the design: SYS-19's "reuse, do not reinvent" has exactly the thing to reuse, so this layer composes the SYS-8 contract rather than building a parallel command representation.

Re-verified findings that did hold:

| Req | Audit verdict | Re-verified | Closed by |
|---|---|---|---|
| SYS-18 | PARTIALLY_WIRED | Confirmed — no System Control of any kind; grep for "Scenario Planner"/"CommandRouter" still zero | `build_system_architecture()` + `render_architecture_tree()` |
| SYS-19 | NEVER_BUILT | Confirmed (reason stale, see above) | `plan_system_command_reuse()` |
| SYS-20 | PARTIALLY_WIRED | Confirmed — non-interference real, router/adapter half absent | `assess_backward_compatibility()` |
| SYS-21 | NEVER_BUILT | Confirmed — zero hits, and `system_level_composition.schema.json` still dormant and about a different concern | `build_system_command_ir()` |
| SYS-22 | NEVER_BUILT | Confirmed | `detect_command_collisions()` + `escalate_command_collisions()` |

---

## What was built

New: `dv_harness/system_command_plan.py` (1632 lines), `dv_harness/schemas/system_command_plan.schema.json`, `dv_harness_tests/test_system_command_plan.py`.
Modified: `dv_harness/subsystem_command_contract.py` (+ its schema) — one field; `dv_harness/cli.py` — one verb.

### Why a new module rather than an extension

`subsystem_command_contract.py` was the obvious extend target and is the wrong granularity, checkably so. Its `command_name` is by its own contract "the macro name as it is actually written in the file, never a normalised or invented name", and `source_command_file` is one real file. SYS-21's `system_command_id` is namespaced **across** subsystems, and `parallel_group` / `serialization_group` / `priority` are system-level scheduling properties no single subsystem's file can state. Putting them on the contract would make a subsystem-local record carry system-level scheduling — and break SYS-20's own guarantee that a subsystem's representation is unchanged by System-level activity.

This follows the precedent `system_resource_registry.py` set for SYS-15..17. A test (`test_no_second_classifier_is_defined_here`) asserts the module defines no second command parser, concurrency resolver, contract-conflict detector or authority resolver, and that the layers below are imported rather than respelled.

### SYS-18 — architecture report

`build_system_architecture()` emits a node descriptor over real data, rendered as the requirement's own tree:

- **System Control's three components are `PLANNED_NOT_IMPLEMENTED`, always.** A parser/router, a scenario planner and a virtual sequencer are code, and code is SYS-40. The JSON schema enforces this with a conditional (`kind: SYSTEM_CONTROL` ⇒ `status` const), so a document claiming otherwise cannot validate.
- **Shared SoC Resources** come from the SYS-15 registry: `PROPOSED_FROM_REGISTRY` / `BLOCKED_PENDING_OWNERSHIP` / `NOT_PRESENT_IN_SELECTION`. The last is deliberately not silence — SYS-18 names six categories, and a tree omitting four would read as a complete statement about the structure.
- **One leaf per SELECTED subsystem, and no others.** Per SYS-14, only mapped shared-infrastructure types are hoisted; a PCIe VIP agent shared by two subsystems still gets no shared-resource node (tested).

### SYS-19 — routing/namespacing plan, no command.txt

One row per subsystem command saying which **existing** subsystem parser/agent/sequence a System-level command would route to. Every target is copied from the SYS-8 contract (tested field-by-field against it). Three verdicts: `REUSES_SUBSYSTEM_SEMANTICS`, `AMBIGUOUS_NAMESPACE`, `TARGET_UNRESOLVED` — the last reported rather than guessed, because naming a target nobody identified is inventing the mapping SYS-19 forbids inventing.

**`::` is the separator, and the reason is now evidence rather than a comment.** Real command names contain `.` — a model task call is written `` `GMODEL.GLOBAL_INIT `` — so a `.`-joined namespace gives `PCIE.GMODEL.GLOBAL_INIT`, in which no adapter can tell where the namespace ends. A test holds that. The SYS-7 grammar truncates a macro name at `::`, so `AMBIGUOUS_NAMESPACE` is unreachable through it today; the guard is kept and tested directly against a constructed contract, because a contract can also arrive from a declared `command_inventory.csv` overlay and a future grammar change must fail loudly rather than silently emit unsplittable names.

### SYS-20 — backward compatibility, in two halves

Half one is **checkable rather than asserted**: every `source_command_file`'s sha256 is recorded, and a test re-hashes each file on disk after the whole run and compares. Half two names the adapter (`<SID>_command_adapter`), states its mechanism — strip the namespace prefix, hand the subsystem's own parser the byte-identical token — and marks it `PLANNED_NOT_IMPLEMENTED` / `generated: false`. A subsystem with even one ambiguous command is `SUBSYSTEM_MODE_AT_RISK` rather than folded into a clean total.

### SYS-21 — the IR, all 17 fields, all derived

`SYS21_FIELDS` is the requirement's own sentence verbatim, held to it by a drift-guard test and to the JSON schema's `required` list. `build_system_command_ir()` computes every field from the SYS-8 contract — SYS-21's own closing rule is that users should not have to write this IR manually — and a test asserts each command fact equals its contract's.

Two fields are **honestly unfilled**: `priority` (a SYS-24 scheduling decision across subsystems) and `timeout` (a `#100` delay is not a timeout; an unbounded `wait` has none). Both carry a sentinel naming what would decide them, pinned by schema `const`. `completion_condition` by contrast *is* derived — from the contract's own interrupt/postcondition evidence, with the basis recorded beside it. `parallel_group`/`serialization_group` are a *naming* of the verdict `resolve_cross_subsystem_concurrency()` already reached, not a second concurrency classifier; a serialization group is named after the contended resource so two contending commands land in the same group by construction (tested).

### SYS-22 — twelve collision classes, and the escalation question the audit got right

The twelve classes are read off SYS-22's own sentence and held to it by a test. Four detectors feed it, and the first **refines existing output rather than re-deriving it**: `scc.detect_contract_conflicts()`'s resource joins are mapped into the finer vocabulary, never recomputed.

**On `source_authority`:** the audit was right that `resolve_conflict()` cannot *classify* this — two subsystems' command.txt files are both tier-2 `reference_command_txt`, so it lands on `UNDECIDABLE_SAME_AUTHORITY` every time and has no vocabulary for collision type. That part is genuinely new domain logic here, and a test proves the same-tier verdict directly so the design reason cannot quietly go stale.

But the audit's recommendation to bypass `source_authority` entirely and call `question_queue` directly was one step too far. `escalate_conflict()` **is** the right reuse target, because `UNDECIDABLE_SAME_AUTHORITY` is precisely the verdict it is built to file: it carries both evidence paths, runs `assert_both_evidence_paths_present()` before persisting, derives an idempotent Q-ID from the finding, and routes the owner through `route_owner`. It is the same function `reference_pattern_audit.py` uses for its host/DUT asymmetry — whose two sides are *also* both tier-2. Writing a second escalation path beside it would be the duplicate mechanism this codebase refuses elsewhere. This also reconciles the step's own title ("extending source_authority.py escalation") with the audit's correct classification finding.

A collision spanning more than two subsystems is split into **pairwise** questions, which `escalate_conflict()`'s own docstring prescribes — it refuses more than 3 sides rather than truncating, because dropping a side drops its evidence path. Tested with three subsystems.

Every finding carries `evidence_by_subsystem` — one real citation list per side, because a single merged list cannot satisfy `assert_both_evidence_paths_present()`.

---

## Two defects found and fixed during the build, worth recording

**1. `ORDERING_CONFLICT` over-fired 6× on a 2-subsystem fixture.** The first cut emitted one row per (resource × dependent command), but every `REGISTER_ACCESS` command in a file shares the same preceding initialization, so one finding was restated six times — the same "trains its users to ignore it" failure the SYS-8 suite already warns about for read/read sharing. Now one finding per (initialization, subsystem pair), and it additionally requires the other subsystem to be able to *disturb* what the precondition established (re-invokes the same initialization, or writes a resource that initialization targets), which makes it a real finding rather than a restatement of `SHARED_RESOURCE_CONTENTION`. 12 collisions → 7 on the same fixture.

**2. Same-address writes were labelled `CONFLICTING_ADDRESS_SETUP` regardless of value.** `scc`'s `ADDRESS_WRITE_COLLISION` branch now deliberately **defers** to the value-aware detector, which performs the same join over the same records *plus* the values. Emitting both would label a same-value duplicate a "conflicting address setup" — the exact misleading finding the value comparison exists to prevent.

Fix 2 required the one change to someone else's module: `_address_dependency()` grew a `written_values` field. The aggregated `arguments` profile folds every invocation together — for a command writing three addresses, `arguments[1].distinct_values` holds three values with nothing saying which went where. Two subsystems writing `32'h1` and `32'h7` to one address is a **conflicting register write**; both writing `32'h1` is a **duplicated initialization**. Different findings, different remedies, and only the pairing separates them. The field is added in the module that already owns the derivation, read from position 1 of a register write — the same macro shape `_argument_profile()` reads its ADDRESS/VALUE roles from, so the two agree by construction. Both cases are held by tests.

---

## Phase boundary (SYS-39/SYS-40) — enforced, not described

No System command.txt, System Command Parser/Router, Scenario Planner, Virtual Sequencer, command adapter or System-Level UVM source is generated; no subsystem environment is touched. Unlike SYS-15..17's module, which persists a planning registry, **this module holds no file writer at all**.

Six tests enforce it:

1. byte-for-byte tree snapshot across a full run — unchanged;
2. the rendered report scanned for real SystemVerilog tokens (`endmodule`, `endclass`, `` `uvm_ ``, `::type_id::create`, `initial begin`, …);
3. the module contains no `.write_text(` / `.write_bytes(` / `open(`;
4. `assert_no_emitted_artifacts()` refuses an emitted command.txt, a generated adapter, and an implemented System Control node — which the JSON schema also cannot validate;
5. `soc_environment_composer`'s `cross_subsystem_scenarios()` / `end_to_end_scoreboard()` / `system_coverage()` still raise `NotImplementedError`;
6. a real `--escalate` CLI subprocess run after which both subsystem trees are byte-identical, no `system_command.txt` or `soc_command.txt` exists anywhere, and every `.sv` in the tree is still the empty fixture.

---

## Front door

```
dv-harness system-command-plan --select SUBSYS_A --select SUBSYS_B [--escalate] [--json]
```

Goes through `subsystem_discovery.require_explicit_selection()`, so SYS-1's refusal is not bypassed. Exits **2** while any collision blocks integration, any subsystem mode is at risk, or any System command name is ambiguous — a System command.txt must not be synthesised on that plan, so a CI step must not read it as a clean run.

---

## Scope note

SYS-23 (initialization deduplication: `SYSTEM_ONCE` / `SUBSYSTEM_ONCE` / `SCENARIO_ONCE` / `REPEATABLE` / `SHARED_RESOURCE_COMMAND`) is deliberately **not** built here — it is the next step's scope. SYS-22 reports a duplicate; deciding what to do with one is SYS-23, whose own rule is that a command is not removed without evidence. That boundary is asserted by a test: a duplicate collision carries `blocks_integration: false`.

## Git hygiene

Every modified file was staged via the hand-scoped patch technique (`git diff` → `git apply --cached --check` → `--cached`). The patch contained exactly 4 hunks, all mine; no concurrent agent's work was staged. Commit touches exactly 6 files.
