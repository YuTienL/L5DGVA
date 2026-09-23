# Intake / Clarification / Question — Detailed Task-Scoped Governance

Moved out of CLAUDE.md during **M4.6 — CLAUDE Context Normalization**. Registered as `id: INTAKE_CLARIFICATION_QUESTION`, `load_policy: TASK_SCOPED`. Sections preserved verbatim; only residency changed.

Covers: OpenSpec/intake mechanics, the question queue, clarification loops, answer validation, and intake-lifecycle events.

---

<!-- S049: moved verbatim from CLAUDE.md original lines 2057-2154 (M4.6 CLAUDE Context Normalization) -->
## Per-Protocol Capability: Two Questions, Never One Label (2026-09-04)

"Which protocols can this harness generate for" and "which protocols has it ever PROVEN" are
different questions, and until 2026-09-04 one field answered both wrongly.
`.dv-harness/qualification/protocol_capability_registry.json` carried
`"status": "REAL_GENERATION_READY"` plus `"generation_capability": "REAL_CODE_GENERATOR_AVAILABLE"`
for all 11 protocols. For Ethernet, eDP and UCIe there is no protocol-specific Python module at
all behind that claim -- only the flat protocol-agnostic skeleton every protocol gets, plus a
`builder_profile.json` under `.dv-harness/universal-protocol-platform/builders/` that no code
reads (`grep -rln "builder_profile" --include=*.py .` returns nothing; the whole builders tree is
inert metadata). This was not inert prose either: `dashboard.py`'s `_protocol_registry()` renders
that registry as the project's real protocol readiness and `_qualification_tier_reached()` derives
the Qualification-Tiers card from it, so the overstatement reached a production surface.

`dv_harness/protocol_capability.py` splits the collapsed label into three separately-checkable
facts and derives every one from code rather than from a typed-in string:

- **generic skeleton** -- `uvm_generator/protocol_env_generator.py`, real for every protocol. That
  half of the old claim was true and stays true.
- **protocol model generator** -- a module that computes something protocol-SPECIFIC. There are
  five, covering eight protocol keys: `pcie_ltssm_generator` (PCIe), `mipi_dphy_generator`
  (MIPI_CSI2/MIPI_DSI -- the D-PHY electrical layer only, both packet layers unmodelled),
  `canfd_arbitration_generator` (CAN_FD), `amba_fabric_generator` (AMBA4, the only one imported by
  production-adjacent code, via `address_map_verifier.py`), `emmc_cmdq_generator` (eMMC/SD_SDIO,
  the protocol-agnostic tag lifecycle). Every entry is verified to resolve through the import
  system and to have its standalone tool on disk before it is reported; anything else reports
  `NONE`. Each partial model names its own unmodelled layers in `does_not_model` (e.g. AMBA's
  `ace_lite_coherency`/`axi_stream`, PCIe's `tlp_layer`/`config_space`), so partial-ness is data,
  not a footnote.
- **DUT proof** -- `dut_proof` paths that must EXIST. Only USB has any, and USB is therefore the
  only `DUT_PROVEN` protocol. Point the field at a path that is not there and the status drops.

`capability_status` (what generation code EXISTS: `GENERIC_SKELETON_ONLY` /
`PROTOCOL_MODEL_PARTIAL` / `PROTOCOL_MODEL_COMPLETE` / `DUT_PROVEN`) is deliberately a **separate
vocabulary from `qualification.py`'s 8-tier ladder** (how far a generated environment has been
PROVEN), sharing no token with it -- PCIe having the deepest protocol model in the repo while
sitting at `BUILDER_AVAILABLE` is exactly why one field could not carry both.

The registry is generated, not hand-maintained: edit the module, then
`python -m dv_harness.protocol_capability --sync`. `--check` exits 2 on any disagreement and is
called by `tools/universal_protocol/protocol_status.py`, which now **refuses to print at all**
rather than report a readiness the code does not back -- a status command that can print a stale
overstatement is how this one survived. `dashboard.py`'s Protocols card carries both statuses per
tile with the module name on hover. The same split was applied to
`.dv-harness/semantic-models/*.json`, which asserted the identical collapsed value in ten more
files nothing reads.

**The five protocol models are now REACHED FROM the one generation entry point (2026-09-04,
same-day gap close).** Splitting the claim honestly left a second, separate problem standing: a
grep for each protocol-model module's non-test callers found only its own standalone
`tools/generate_*.py` script. `uvm_generator/create_environment.py` -- what
`tools/generate_protocol_uvm_environment.py` calls, and what every
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` invokes -- imported none of them, so a
`protocol: "PCIe"` manifest produced byte-for-byte the same protocol-agnostic skeleton a
`protocol: "Ethernet"` manifest produced, and the LTSSM model reached a generated environment only
if an agent happened to know to run a second tool by hand. Their unit tests passed the whole time;
that is the PARTIALLY_WIRED shape. `dv_harness/uvm_generator/protocol_model_layer.py` is the wire:
- WHICH module implements a protocol comes from `PROTOCOL_CAPABILITIES` (already the one
  code-derived answer, already drift-checked), and HOW to invoke it from that entry's new
  `generator_class`, which `--check` now resolves through the import system -- so a renamed class
  fails the drift check instead of a generation run.
- WHAT it runs on is the manifest's `protocol_model_topology`, that model's own topology schema
  verbatim (the same dict its standalone tool takes). Each model's own validator judges it; a
  rejected topology raises `ProtocolModelLayerError` naming the model's own reason rather than
  emitting a skeleton the caller would read as the modelled environment they asked for.
- The model reaches the MAIN environment, not just a `protocol_model/` subdirectory: where it
  exposes a state graph (today PCIe's `LTSSM_TRANSITIONS`) and the manifest names the real DUT
  signal carrying that state, the graph is compiled through the EXISTING `state_machine_checks`
  DSL -- whose own docstring says it generalizes exactly this -- into real transition-legality SVA
  in `tb/env/<p>_assertions.sv`, and the model's package is PREPENDED to the environment filelist
  so it compiles before the file typed against it.
- **Nothing is defaulted and no absence is silent.** lane_width/gen_speed/role and a state-signal
  name are DUT facts. A manifest without them still generates, but its own
  `environment_manifest.json` carries a `protocol_model` record saying
  `PROTOCOL_MODEL_TOPOLOGY_NOT_SUPPLIED` and naming the module that would have run -- the same
  honesty contract this section applies to the registry, applied per generated environment. USB
  (no protocol-model module by design) and Ethernet (none exists) record `NO_PROTOCOL_MODEL_FOR_
  PROTOCOL` with their real `capability_status`, and every SV file USB generates stays
  byte-identical.
Proven -- including a byte-comparison against the standalone tool's own generator call, so a future
reimplementation-instead-of-reuse fails -- by
`dv_harness_tests/test_protocol_model_layer_wiring.py`.

**Scope boundary, stated so it is not read as more**: this closes the CLAIM and the WIRING, not
the capability. No non-USB protocol is proven against a real DUT by any of this -- the layered
output has still never been compiled or bound -- and the "Non-USB topology
variants" above remain UNTESTED. The recommended bounded first non-USB pilot is still PCIe -- its
Root-Complex/Endpoint asymmetry reuses the proven `block/branch_a*/branch_fw/branch_b*`
architecture directly (no new untested topology doc needed first, unlike AMBA-as-primary-DUT or
CSI-2/DSI simplex streaming), it is the only protocol with a generated example artifact
(`examples/generated_pcie_uvm_env/`, which `examples/NOTICE_SCAFFOLDING_ONLY.md` correctly labels
an unconnected never-compiled skeleton), and its remaining gap is narrow and named: bind one real
PCIe RTL DUT, run the 3 machine gates against it, and extend past LTSSM into TLP/config-space.

Proven -- including that the two real consumers carry the split claim and that a re-overstated
registry is refused rather than reported -- by `dv_harness_tests/test_protocol_capability.py`.



<!-- S087: moved verbatim from CLAUDE.md original lines 5439-5491 (M4.6 CLAUDE Context Normalization) -->
## Question Escalation Package: the 9-Field Structured View (spec section 32) (2026-09-06)

`question_queue.py`'s own persisted question record (`question.schema.json`) already carries every
fact a human-facing escalation needs -- id, domain, question, context_path, options, recommendation,
assumption_if_unanswered, owner, tier, blocking -- accumulated one Part-B mechanism at a time across
this module's history. What did not exist was a single, NAMED 9-field VIEW assembling exactly those
facts into the shape a human reviewer (or a digest/GUI renderer) actually reads, so two renderers of
"the same escalation" could each pick a different subset of the raw record and call it the package.

**Disclosed residual, stated rather than left to be discovered**: this repository checkout does not
carry the literal spec-section-32 document text (a repo-wide search found no file containing it), so
the 9 field NAMES (`ESCALATION_PACKAGE_FIELDS`: `question_id`, `category`, `context`,
`question_text`, `options`, `recommended_option`, `default_if_unanswered`, `owner`, `urgency`) are
this module's own defensible synthesis -- built from established human-in-the-loop escalation
practice and this module's own existing, already-tested vocabulary (domain/owner/tier routing,
options-with-rationale, the Tier-2 assumption-if-unanswered contract) -- rather than a verbatim
transcription of a document this checkout does not have. What IS load-bearing regardless of the
exact names, and enforced rather than merely claimed: every one of the 9 fields is a REAL,
already-persisted fact from a record `add_question()` / `build_multiple_choice_question()` already
produced -- never a fabricated value, and never a second, independently-filed record.

**No parallel filing mechanism.** `build_escalation_package(record)` is a pure, read-only PROJECTION
of an existing record (the same "a generated view of a real store is never a second source of truth"
discipline this module's own `decisions.md` already applies to `decisions.json`) -- it is never
written back into `questions.json`, so `question.schema.json`'s `additionalProperties: false`
contract is untouched and no schema_version bump is required. `QuestionQueueStore.
get_escalation_package(question_id)` is the store's own existing `get_question()` read path plus this
projection -- no second lookup. Both `add_question()` (used directly, and by `escalate_conflict()` in
`source_authority.py`) and `build_multiple_choice_question()` are the ONLY two filing mechanisms this
projection ever reads from; a record built by hand (missing a required key) is refused rather than
silently projected with a gap.

`urgency` (field 9) is DERIVED from the record's own `tier` -- never an independently-declared value
that could drift from the tier a caller actually got escalated at: Tier 3 (blocking) ->
`BLOCKING_AWAITING_HUMAN_ANSWER`; Tier 2 -> `NON_BLOCKING_TIME_BOXED_ASSUMPTION_LOGGED` (this
module's own Tier-2 contract language, "logged and continues" -- see `add_question()`'s Tier-2
branch); Tier 1 -> `INFORMATIONAL_ALREADY_SELF_RESOLVED` (never actually escalated to a human at
all). A record carrying a `tier` outside the 3 known values raises rather than reporting a guessed
urgency. `render_escalation_package_markdown()` renders one package as a single labeled block (the
same "one labeled field per line" shape `QuestionQueueStore._render_decisions_md()` already uses for
a per-decision block), for a digest/GUI renderer that wants ONE consistent block per escalated
question rather than reformatting the raw record itself.

Proven by `dv_harness_tests/test_question_queue.py` (11 of its 78 tests): the 9-field shape and fixed
order; every field traced 1:1 back to the real persisted record; urgency derived correctly at all 3
tiers; the negative-control property this function exists to guarantee -- `build_escalation_package()`
refuses to fabricate a package from an incomplete record, a non-dict record, or a record carrying an
unrecognized tier, raising `QuestionValidationError` rather than a bare `KeyError` or a silently
partial package; `get_escalation_package()` proven to reuse the store's own `get_question()` path and
to raise `KeyError` on an unknown id (matching `answer_question()`'s own sibling raise); a package
built from a `build_multiple_choice_question()`-filed record; a byte-level proof that building a
package never persists `escalation_package` into `questions.json`; and full markdown-field coverage.


<!-- S088: moved verbatim from CLAUDE.md original lines 5492-5567 (M4.6 CLAUDE Context Normalization) -->
## Intake Source Priority: a 10-Step DISCOVERY Ladder, Distinct from the Conflict Order (2026-09-06)

`source_authority.py`'s own module docstring already records a real lesson: its 9-level
`AUTHORITY_ORDER` (which of two already-read, disagreeing sources wins) and
`tools/verification_flow/evidence_source_priority_gate.py`'s 9-item `ORDER` (which source to
consult FIRST for a fact not yet known) had already been mis-identified once, purely because both
lists happened to be the same length. `dv_harness/intake_source_priority.py` is a THIRD list --
another DISCOVERY order, but a wider, more general 10-step intake ladder (repo files already on
disk, existing UVM environment already generated, build scripts/Makefile, RTL/PHY source, register
files, specs/datasheets, VIP examples, regression lists, git history, ask the user) -- built
deliberately not to repeat that mistake with either existing list.

**The lookup.** `next_sources_to_check(fact_name, available_sources)` takes a fact not yet known
plus which of the 10 kinds are actually AVAILABLE for the current project, and returns those kinds
in discovery-priority order, highest first -- never re-deriving a new order per fact (the ladder is
the same ten steps for every fact, exactly as the reference gate's own `ORDER` applies uniformly).
It refuses an empty fact name, refuses an empty availability list rather than silently defaulting to
"ask the user", and refuses an unrecognized source name via `normalize_intake_source()` rather than
silently dropping it. "Ask the user" can never be returned ahead of an offered higher-priority
source -- that falls straight out of filtering the ladder by rank.

**The required cross-check, and why it is not "zero shared vocabulary".**
`assert_distinct_from_known_discovery_and_conflict_orders()` mirrors
`source_authority.assert_doc_matches_code()`'s "parse the real artifact, never eyeball it" pattern,
but asserts DIFFERENCE rather than agreement. Three checks: (1) length differs from BOTH
`source_authority.AUTHORITY_ORDER` (9) and the pre-existing gate script's `ORDER` (9) -- this ladder
is 10 by design, so it cannot repeat the exact length-coincidence that caused the earlier
mis-identification; (2) no CANONICAL id of either this table or `source_authority.AUTHORITY_ORDER`
silently resolves through the OTHER table's own lookup, checked in both directions -- deliberately
NOT a "zero alias overlap" rule, since the two tables legitimately discuss some of the same real
artifacts (RTL, register files, VIP examples) and an ordinary synonym like "rtl" or "makefile"
appearing in both tables' own `aliases` is expected and harmless; only a table's own canonical id
being silently accepted by the other table's normalize function is the dangerous case that would
let a shared caller confuse the two; (3) a live re-parse of the gate script's real `ORDER` constant
confirms this ladder's ten phrases are not that list's nine, word for word. The gate script's module
is never imported for this comparison: it calls `argparse.parse_args()` at module level with no
`if __name__ == "__main__":` guard, so importing it outside its own CLI invocation raises/exits
immediately -- `parse_evidence_source_priority_gate_order()` instead regex-extracts the literal
`ORDER = [...]` list from that file's real source text on disk, the same "read the real artifact,
never re-type it" discipline `source_authority.parse_documented_order()` already applies to
`docs/RUN_PROFILE.md`'s prose paragraph.

A real defect surfaced building this: an early draft's aliases for `rtl_phy_source`/
`register_files`/`specs_datasheets`/`vip_examples` included `dut_rtl`/`register_file`/
`controller_doc`/`vip_example` -- literally `source_authority.AUTHORITY_ORDER`'s own canonical ids
-- which the canonical-id cross-resolution check exists precisely to catch, and did.

**Deliberately bounded, and stated rather than implied closed.** (1) This module ORDERS a
caller-declared availability set; it discovers nothing itself -- no filesystem scan, no RTL parse,
no git read. Whether a source kind is actually "available" for a project is a fact the caller must
supply (e.g. from `env_manifest.py`'s own layer statuses, a real directory listing, or a human's own
knowledge), never inferred here. (2) It ARBITRATES and AUTHORIZES nothing: no stage runs, no gate is
invoked, and there is deliberately no `dv-harness` CLI subcommand -- `cli.py`'s existing argparse
tree has no natural home for a small standalone lookup table, so the front door is
`python -m dv_harness.intake_source_priority order|next|self-check` only, per this project's own
"skip the CLI wiring when it would be awkward" rule. Exit 0 = a non-`ask_user` source is available
to check next / self-check passed; 1 = a real finding (`ask_user` is the ONLY available source --
i.e. a human must be asked); 2 = nothing to report (no sources declared, an unrecognized source, or
a self-check failure). (3) It is not wired into any stage, gate, or the engine's own discovery flow
-- no `run_stage()`/`advance()` call site invokes it and no graph node declares it, so this is a
standalone module a caller imports or shells out to, not an engine-fired one.

Proven by `dv_harness_tests/test_intake_source_priority.py` (30 tests): the positive path (all 10
steps in the task-specified order, alias resolution, `next_sources_to_check()`'s ordering and its
"same available set, same order regardless of fact" property), and negative controls including an
empty fact name, an empty availability list (must refuse rather than default to `ask_user`), an
unknown available source (must refuse rather than silently drop), a duplicated available source, the
canonical-id cross-resolution checks against the REAL `source_authority.AUTHORITY_ORDER` in both
directions, phrase-set disjointness, a real subprocess proof that importing the gate script's module
really does fail (justifying why this module parses its text instead), and two mutation-style checks
proving the length/content cross-checks against the gate script's `ORDER` have genuine detection
power (a fabricated 10-item `ORDER` and a fabricated identical-content `ORDER` each trip their
intended, distinct error). Both the module functions and the `python -m` CLI (all three exit codes)
are exercised as real calls/subprocesses. The pre-existing `dv_harness_tests/test_source_authority.py`
suite (37 tests) was re-run and still passes unchanged.


<!-- S099: moved verbatim from CLAUDE.md original lines 6205-6216 (M4.6 CLAUDE Context Normalization) -->
## Intake State: One Per-Field Record Joining Manifest + Decisions + Bind Tiers (2026-09-06)

`dv_harness/intake_state.py` answers "what does this project's intake actually know about field X, and from where" as one `IntakeFieldRecord` per field -- `{value, source, confidence, status, last_validated, owner}` -- joining three real sources that previously had to be read separately: env.manifest.json's own per-layer `status`/`reason` (`env_manifest.py`), a real `question_queue.QuestionQueueStore.find_decision()` (read-only; this module never files or answers a question itself), and `connectivity.py`'s `BindTier` vocabulary for per-bind-entry confidence. Status is one of AUTO_RESOLVED / USER_CONFIRMED / PARTIAL / CONTRADICTED / MISSING / BLOCKED / UNKNOWN / NOT_APPLICABLE -- a human answer (`question_queue.HUMAN_DECISION_SOURCE`) always outranks the harness's own Tier-2 auto-assumption, and a Tier-2 guess never downgrades a fact already computed from a real source; a field where a human's filed answer disagrees with an already-computed value reports CONTRADICTED rather than being silently overwritten as if the two agreed.

`evaluate_uvm_generation_ready()` is a hard refusal gate over six named blocking categories -- DUT boundary, VIP unresolved, active-driver conflict, critical bind, build env, known-PASS test -- folded worst-wins per category (`IntakeState.category_status()`); a category with zero fields recorded at all folds to MISSING, never "ready by omission". `already_resolved(intake_state, field_name)` is the do-not-ask helper: a caller should check this BEFORE calling `question_queue.QuestionQueueStore.add_question()` for a field, since this module never files questions itself.

Three of the six blocking categories are deliberately duck-typed rather than imported, each documented with its intended real producer in the module docstring: `dut_boundary` accepts `phy_boundary.py`'s own `{status, bind_decision: {bindable, mount_layer, rationale}}` shape without importing that module; `active_driver_conflicts` accepts a generic `{resource, status, reason}` list standing in for `system_resource_inventory.real_cross_subsystem_findings()`; `known_pass_tests` accepts a generic `{test_name, verdict, reason}` list standing in for `golden_scenario.py`'s recorded capsules -- not imported because `golden_scenario.py` was, at the time this module was built, one of four files a separate concurrently-running batch was editing. `connectivity.py` and `env_manifest.py` are imported directly for their real vocabularies (`BindTier`/`GateStatus`, layer `status`/`reason`), since neither was part of that concurrently-edited set.

Deliberately bounded: this module JOINS and REPORTS only. It files no question, runs no gate script, writes no state/blackboard/approval record, and holds no stage gate of its own -- `evaluate_uvm_generation_ready()` only refuses or allows a caller's next action.

Proven by `dv_harness_tests/test_intake_state.py` (41 tests): env.manifest layers are built through the REAL `env_manifest.py` producer functions over real fixture `register_map.json`/`soc_arch_map.json`/`testplan_sources.json` (including a genuine register/address-map base-address disagreement and a genuine broken vPlan test reference, both producing real CONTRADICTED verdicts, not fabricated ones); DUT-boundary facts are the real `phy_boundary.classify_boundary()`/`decide_bind_location()` output for both a PARALLEL (bindable) and a SERIAL (BLOCKED) case; bind-tier facts are classified through real `connectivity.BindTier` values across T1-T4, including a negative control where a fabricated (non-`human_answer`) confirmation source still BLOCKS; question_queue decisions are produced by driving a real `QuestionQueueStore` through its real `add_question()`/`answer_question()` API, never a hand-written decision record. Negative controls prove absent evidence never reads as resolved: a state built from nothing refuses on all six blocking categories, and flipping just one category back to BLOCKED in an otherwise-fully-resolved state still refuses generation as a whole.


<!-- S123: moved verbatim from CLAUDE.md original lines 7789-7802 (M4.6 CLAUDE Context Normalization) -->
## Verification Intake Contract: the Whole-Project Lifecycle + INTAKE_READY Conjunction (2026-09-06)

Every sub-domain intake mechanism in this project answers its own narrow question well (`env_manifest.py`'s 3-layer manifest, `question_queue.py`'s ask/decide lifecycle, `connectivity.py`'s bind-tier gate, `requirement_contract.py`'s per-requirement status, `golden_scenario.py`'s per-test freshness, `waiver_store.py`'s per-waiver status). Nothing sat one level above them and answered the capstone question a human actually has to ask before generation or signoff can begin: "across every domain intake touches, where is THIS PROJECT's intake right now, and is it actually ready?" A repo-wide grep for `VerificationIntakeContract`/`INTAKE_READY`/`intake_contract` before writing this module matched nothing executable.

`dv_harness/verification_intake_contract.py` is exactly two things, nothing more:

1. **A lifecycle state machine for the whole intake effort**, not any single domain's local state. Thirteen states in the task's own order -- `CREATED -> DISCOVERING -> CORRELATING -> QUESTION_PENDING -> USER_INPUT_RECEIVED -> VALIDATING -> CONFLICT -> PARTIAL -> BLOCKED -> READY_FOR_REVIEW -> BASELINED -> STALE -> REVALIDATING` -- with a real, closed `TRANSITIONS` graph enforcing legal moves (`assert_legal_transition()` on every transition; an illegal jump such as `CREATED` straight to `VALIDATING` raises `IntakeContractError("ILLEGAL_STATE_TRANSITION", ...)` naming the real legal next states). `READY_FOR_REVIEW` is explicitly non-terminal, per spec: it carries five outgoing edges (three send the contract back to earlier work -- `DISCOVERING`/`CORRELATING`/`VALIDATING` -- plus a fresh `QUESTION_PENDING` and forward approval to `BASELINED`). That idea is generalized rather than special-cased: `assert_no_absorbing_state()` runs at import time and proves EVERY state (not only `READY_FOR_REVIEW`) has at least one real outgoing edge -- even `BASELINED` has a real edge to `STALE`, so a baselined contract can be invalidated by a later spec/RTL/config change exactly the way `signoff_export.py`'s frozen baseline can (this module accepts that resulting `STALE` transition; it does not itself decide staleness -- that decision belongs to `golden_scenario.evaluate_freshness()`/`signoff_export.evaluate_freeze_invalidation()`, which this module deliberately does not import).

2. **INTAKE_READY: a conjunction of caller-named critical conditions, never an average.** `evaluate_intake_readiness(conditions)` takes a caller-assembled list of `{"name", "status"}` records (status one of `MET`/`UNMET`/`UNKNOWN`/`NOT_APPLICABLE` -- `MET`/`NOT_APPLICABLE` clear, `UNMET`/`UNKNOWN` both block, deliberately undistinguished: "this failed" and "we could not tell" are both reasons a human must not be told the project is ready). `ready` is `True` iff the blocking list is empty -- one single `UNMET`/`UNKNOWN` condition among any number of clean ones still reports `NOT_READY` naming that one condition, never diluted into a percentage. This is the same worst-wins, no-averaging discipline `golden_flow_readiness.combine_readiness()` already applies one row at a time ("BLOCKED is worse than UNKNOWN on purpose... must not be averaged away"), generalized here over an open-ended, caller-declared condition set rather than a fixed twenty rows -- which conditions exist is never hardcoded, since they come from other, separately-building modules (env manifest completeness, requirement contract completeness, connectivity bind-tier clearance, golden scenario freshness, waiver validity, VIP API provability, and others). An empty condition list reports `NOT_AVAILABLE` with `ready=False`, never a vacuous `READY` over zero conditions. A duplicate condition name, an unrecognized status, or a malformed record all raise `IntakeContractError` rather than being silently dropped or resolved by guessing.

**Deliberately bounded, and stated rather than implied closed.** This module imports NOTHING else from `dv_harness` -- proven by an AST-based test -- because it was built as the capstone of a batch in which several sibling intake modules (`intake_state.py`, `requirement_contract.py`, `golden_scenario.py`, `waiver_store.py`, and others) were concurrently in flux or on this batch's own never-touch list; every sub-domain fact is accepted as a generic, duck-typed parameter (a plain dict or list) rather than fetched by import. It never runs a stage, invokes a gate script, submits a build/regression/LSF job, or writes an approval/governance record -- `ControlPlane.approve()`, `policy.can_signoff()`, `assert_human_approval()` and the PR-only main/master governance are untouched and unreferenced in code (asserted by a tokenize-based test that strips this module's own explanatory docstrings before checking, since the docstrings legitimately name what this module does NOT do). It does not decide what a `CONFLICT` between two domains means or which side wins -- the same "ARBITRATION IS NOT HERE" boundary `requirement_contract.py` already draws for its own `CONTRADICTORY` status. It persists nothing to disk on its own: `VerificationIntakeContract` is a plain in-memory record; a caller decides how (or whether) to serialize it. There is deliberately no `dv-harness` CLI verb and no edit to `gates.py`/`cli.py`/`CLAUDE.md` -- the front door is `python -m dv_harness.verification_intake_contract states|transitions|evaluate`, the same ad hoc fallback several sibling 2026-09-06 modules already use.

Proven by `dv_harness_tests/test_verification_intake_contract.py` (34 tests): a full realistic lifecycle traversal exercising every real loop this project's own intake work actually takes (a `CONFLICT`, a `PARTIAL`, a `BLOCKED`, a human sending a reviewed `READY_FOR_REVIEW` contract back before approving, and a `BASELINED` contract going `STALE` and being `REVALIDATED`); a mutation-style test proving the import-time transition-table guards have real detection power (a state popped from the table, a state made absorbing, a target pointed at a non-existent state each trip the guard that names that specific defect); the headline no-averaging proof (99 clean conditions plus 1 `UNMET` still reports `NOT_READY` naming exactly that one condition); 8 further INTAKE_READY negative controls; the `require_intake_ready` opt-in gate on the `READY_FOR_REVIEW` edge; and CLI subprocess tests for all three verbs and all three exit codes.


<!-- S124: moved verbatim from CLAUDE.md original lines 7803-7820 (M4.6 CLAUDE Context Normalization) -->
## Intake Question Priority: Ask-Gating Table, Next-Best-Question Ranking, and Batching (2026-09-06)

Three small, related mechanisms an intake flow needs whenever a real 3-tier ask-a-human queue (`question_queue.py`) accumulates pending questions faster than a human can answer them, and nothing in this repo decided any of the three: whether a given pending question is even worth asking given what the harness already believes and what getting it wrong would cost, which of several worth-asking questions to surface FIRST, and how to group several LOW-stakes questions into one round without ever letting a high-stakes one hide inside a batch. `dv_harness/intake_question_priority.py` is all three, and it deliberately does not import `question_queue.py` at all -- this task's own scope named that boundary explicitly, so pending-question data arrives as a generic list of dicts and every fact this module needs (confidence, criticality, the four ranking factors, a declared topic key, an `architecture_defining` flag) is read directly off the caller's own dict rather than coupled to that module's schema.

**(a) The gating table is 16 explicit cells, not a computed risk score.** `CONFIDENCE_LEVELS = (LOW, MEDIUM, HIGH, UNKNOWN)` crossed with `CRITICALITY_LEVELS = (MINOR, MAJOR, BLOCKER, UNKNOWN)` -- a fourth "we do not honestly know" value on both axes so an absent or unrecognized fact is never silently guessed into a numeric axis. `GATING_TABLE` spells out all 16 `(confidence, criticality) -> (ASK|DO_NOT_ASK, reason)` pairs by hand, matching this task's own two worked examples verbatim: `(HIGH, MINOR)` and `(HIGH, MAJOR)` are the only "non-critical" DO_NOT_ASK cells, and `(MEDIUM, BLOCKER)` is ASK. Two deliberate asymmetries carry real weight: BLOCKER criticality is ASK at every confidence level including HIGH (an architecture-defining decision is confirmed regardless of how sure the harness already is, the same posture `connectivity.py`'s Bind-Location Tier 3/4 rules already take), and UNKNOWN on either axis is always ASK -- an unclassified criticality is never read as evidence it is safe to skip, and an unclassified confidence is never read as evidence the harness is sure. `gate_question()` normalizes a raw value to UNKNOWN (flagged `*_recognized: False`) rather than raising, and `gate_pending_questions()` runs it over a whole list.

**(b) Next-best-question ranking is exactly the stated formula, and nothing this module invents.** `score_question()` computes `blocking_value * downstream_impact * expected_confidence_gain / user_effort` over four caller-supplied numeric factors -- their real meaning and measurement is entirely the caller's, per this task's own instruction not to invent how they are measured. A missing factor, a non-numeric one (a `bool` is explicitly rejected, since it is a Python `int` subclass), a negative weight, or a `user_effort` that is not strictly positive (the divisor) all report `UNVERIFIABLE` naming the real bad field, never a placeholder score. `rank_questions()` sorts the scorable subset descending (question-id tie-break for determinism) and reports the unrankable subset alongside it, never dropped.

**(c) Batching groups only what was explicitly declared safe to group.** `classify_batch_risk()` treats ONLY an explicitly-declared `MINOR` criticality (with no `architecture_defining: true` flag) as LOW/batchable; BLOCKER, MAJOR, an explicit `architecture_defining` flag, and an absent/unrecognized criticality are all HIGH risk -- deliberately stricter than the gating table's own MAJOR handling, because merging several questions into one round changes what a human reads together. `build_question_batches()` groups LOW-risk questions sharing a caller-declared topic key (`topic`/`related_topic`/`related_group`/`group_key` -- never an inferred/NLP-derived relatedness, which this module does not attempt), splits an oversized group deterministically when `max_batch_size` is given, and places every HIGH-risk question in a batch of exactly one regardless of topic overlap -- the property this task's "NEVER batches an architecture-defining/high-risk question with anything else" rule requires, and it is asserted directly (including the case where the same topic is shared with an otherwise-batchable MINOR question).

`analyze_pending_questions()` composes all three in the natural order (gate, then rank and batch only the to-ask subset -- a DO_NOT_ASK question is never scheduled at all), with `render_report_text()` and a `python -m dv_harness.intake_question_priority` front door (no `dv-harness` CLI verb was wired and neither `cli.py` nor `gates.py` was touched, per this batch's file-safety scope).

**Deliberately bounded.** It reads no file, writes no state, files no question, answers no question, runs no build/regression/LSF job, and touches no approval/governance mechanism -- it computes three small decisions over data the caller supplies and nothing else. It does not decide what a question's confidence/criticality/four ranking factors/topic actually ARE; those are read verbatim off the caller's dict, exactly as `question_queue.py` itself is the authority on its own records.

Proven by `dv_harness_tests/test_intake_question_priority.py` (35 tests): the gating table's full behavior including both of this task's own worked examples, BLOCKER-always-asks-regardless-of-confidence, UNKNOWN-on-either-axis-always-asks, and unrecognized-value normalization; the ranking formula plus six negative controls (missing factor, non-numeric, boolean-rejected, zero/negative `user_effort`, negative weight, unrankable-never-dropped); the batching rule's grouping plus negative controls (a BLOCKER question never merged even sharing a topic, an `architecture_defining`-flagged MINOR question never merged even sharing a topic, a topic-less LOW-risk question never guessed into a group, MAJOR/UNKNOWN questions never grouped even sharing a topic, `max_batch_size` splitting in original order, a non-positive `max_batch_size` refused); the integrated pipeline; and three real CLI subprocess invocations asserting exit codes 0/1/2.

**Disclosed residual**: this is a standalone, non-wired module by design -- no `dv-harness` CLI verb, no graph node, no stage gate, and no import of `question_queue.py`'s real `QuestionQueueStore`. A caller integrating it with the real queue must translate that store's records into the generic dict shape this module expects itself. The four ranking factors' real-world measurement is entirely undefined by this module, as instructed. "Closely related" for batching is a caller-declared topic-key match only; no semantic/NLP relatedness is computed.


<!-- S125: moved verbatim from CLAUDE.md original lines 7821-7898 (M4.6 CLAUDE Context Normalization) -->
## Intake Baseline: a Freeze Over the Twelve Pre-Generation Facts (2026-09-06)

`signoff_export.py`'s SIGNOFF FREEZE / BASELINE (spec section 238) freezes fifteen
POST-verification fields at signoff. Nothing froze the narrower, earlier set of facts a project
commits to at INTAKE time, before generation begins: which DUT top/boundary was declared, the
DUT/TB content identity, the source file hashes the environment was built against, which VIP was
declared, the bind-topology hash, the reference-UVM hash, the DE `command.txt` hash, the
known-test list, and how many critical unknowns/conflicts remained unresolved and how many user
decisions were on record at that moment. Two intake environments that look identical on paper
could silently diverge on any of these without anything noticing.

`dv_harness/intake_baseline.py` mirrors `signoff_export.py`'s freeze pattern -- content-hash
based, worst-wins VALID/INVALIDATED/UNKNOWN, "we could not check" is never VALID -- over exactly
these twelve facts, and reuses rather than reinvents its one real primitive:
`source_identity.aggregate_source_id()` (the identical `tools/remote/` sys.path convention
`harness_deploy.py` and `signoff_export.py`'s own `_aggregate()` already establish) folds every
multi-file or list-shaped fact into one deterministic digest -- there is no second hashing scheme
anywhere in this module.

**Deliberately decoupled from every other intake-adjacent module.** Every one of the twelve facts
is accepted as a generic, duck-typed parameter (a plain `{field_name: value}` dict) rather than
discovered by importing `env_manifest.py`/`connectivity_check.py`/`question_queue.py`/
`source_authority.py`/`signoff_export.py` itself -- a caller who already has these facts in hand
(an intake agent, a CLI script, a future generator) can freeze them without this module needing to
know which other mechanism produced them. Four field-shape captors match what each fact actually
is: a **declared fact** (`dut_top_boundary`, `vip_declaration`) hashed via canonical sorted-key
JSON; a **hash-or-files** fact (`dut_sha`, `tb_sha`, `source_file_hashes`, `bind_topology_hash`,
`reference_uvm_hash`, `de_command_txt_hash`) that accepts an already-computed hex digest, a raw
content string to hash, or a real `{path: hash-or-content}` multi-file mapping folded through
`aggregate_source_id()`; a **list** fact (`known_test_list`) folded through that same primitive;
and a **count** fact (the three unresolved-unknowns/conflicts/decisions counters), which honestly
rejects `None`, a `bool`, a non-int, or a negative value as `NOT_AVAILABLE` rather than coercing
it. `assert_intake_fields_have_captors()` holds the declared field list and the captor table equal
in both directions at import.

**Freeze, then re-derive -- never store -- the verdict.** `freeze_intake_baseline(root, facts,
frozen_by=...)` records one immutable JSON baseline under `.dv-harness/intake/baselines/
<freeze_id>.json` (an unattributable freeze is refused) and touches nothing else -- no
`state.json`, no `events.jsonl`, no approval mechanism. `evaluate_intake_freeze_invalidation()`
never trusts a stored verdict; it re-derives VALID/INVALIDATED/UNKNOWN on every call from two
independent, worst-wins checks: (1) each of the twelve fields re-captured NOW against what was
frozen, by digest -- a field that changed or whose evidence disappeared INVALIDATES, while new
evidence appearing after the freeze is INDETERMINATE (a real change, not proof the frozen evidence
was wrong); (2) the frozen record's own self-integrity -- its stored `freeze_id` is independently
recomputed from its stored baseline and compared, so a hand-edited record is caught rather than
trusted. `evaluate_all_intake_freezes()` reports the worst status across every freeze on file for
a project.

`python -m dv_harness.intake_baseline fields|baseline|freeze|list|status` shares one
`execute_verb()`, the same convention `power-intent`/`golden-scenario`/`signoff_export` use; exit
0 clear/VALID, 1 INVALIDATED, 2 NOT_AVAILABLE/UNKNOWN/refusal. No `dv-harness` CLI verb was added
(`cli.py` was under concurrent edit by other parallel gap-closure work in this same session, the
same reason several sibling additions stayed `python -m`-only that day).

**Deliberately bounded, and stated rather than implied closed.** (1) It discovers nothing itself:
whether a DUT SHA or a bind-topology hash is real is entirely the caller's declaration: there is no
filesystem scan, no RTL parse, and no git read anywhere in this module. (2) It ARBITRATES and
AUTHORIZES nothing: no stage runs, no gate is invoked, and there is deliberately no stage gate -- a
gate that passed because an intake baseline existed, or failed because one did not, would be
worse than none. REVALIDATION (deciding an INVALIDATED intake baseline is still acceptable to
proceed from) is a human act this module does not perform. (3) It is REACHED, not WIRED: no
`run_stage()`/`advance()` call site invokes it and no graph node declares it, so a caller must
invoke it directly or through the CLI.

Proven by `dv_harness_tests/test_intake_baseline.py` (52 tests): positive capture of all twelve
fields, honest `NOT_AVAILABLE` handling across every captor's negative shapes (`None`, empty,
wrong Python type, a rejected bool/negative count), order-independence and content-sensitivity of
every digest, a direct proof that the multi-file digest equals an INDEPENDENTLY-imported call to
`source_identity.aggregate_source_id()` (so a future reimplementation-instead-of-reuse fails), a
real freeze/list/load round trip against a throwaway directory, the central freeze-invalidation
proof (unchanged facts stay VALID; a changed DUT SHA is INVALIDATED naming the field; evidence
disappearing is INVALIDATED; new evidence appearing is INDETERMINATE/UNKNOWN and never
invalidating; a hand-tampered frozen record is caught by the self-integrity recompute; a
malformed/empty frozen record reads UNKNOWN, never VALID), `evaluate_all_intake_freezes()`'s
worst-wins behaviour across multiple recorded freezes, and the real `python -m
dv_harness.intake_baseline` CLI driven as a subprocess through every verb with all three exit
codes exercised.


<!-- S135: moved verbatim from CLAUDE.md original lines 8329-8373 (M4.6 CLAUDE Context Normalization) -->
## User Answer Validator: Checking a Raw Intake Answer Against Real Evidence (2026-09-06)

Intake conversations collect free-text answers such as "DUT top = usb_core" or "build includes file
usb3_link_ctrl.v". Nothing in this repo checked such an answer against anything real: an agent (or a
human) typing the answer was the only source for it, so a wrong or hallucinated answer would sit in the
intake record indistinguishable from a correct one. Per the Evidence Truth Rule, a claim like this must
be checked against a real producer, and where it genuinely cannot be checked the module must say so
honestly rather than accept it as true by default. `dv_harness/user_answer_validator.py` is that check.

**Reuse, not reinvention, on both halves.** Module/file EXISTENCE inside a supplied RTL file set is
answered by running the real `verible_parser.parse_file()` against each supplied file -- the same
verible-verilog-syntax front end `env_manifest.py` itself extends -- and checking whether the claimed
module name is really among what verible extracted; this module parses RTL through no other path.
Build INCLUSION is answered by reading `env_manifest.py`'s own already-recorded `dut_facts.rtl` facts
(via `build_dut_facts_rtl()` or a real `env.manifest.json` loaded through `load_env_manifest()`) and
checking whether the claimed file appears among the paths that were REALLY parsed into that manifest --
this module never re-parses a build's file list itself and never re-derives what "the build" is.

**Four honest statuses, never collapsed into three.** `VALIDATED` -- the claim matches real evidence
exactly. `PARTIALLY_VALIDATED` -- real evidence supports a WEAKER form of the same claim (a module of
that name exists but under different letter case; a file of that name is recorded but at a different
path than claimed) -- a real, disclosed, weaker match, never silently promoted to `VALIDATED` and never
silently dropped. `CONTRADICTED` -- real evidence was fully consulted and the claim is false: the named
module is absent from every RTL file this module could successfully parse, or the named file is absent
from every path recorded in the build facts. `UNVERIFIABLE` -- this module could not check the claim at
all: no RTL file set or build facts were supplied, the real verible binary could not be run, some
supplied RTL failed to parse and the claim was not found among what DID parse (so absence there is not
proof of absence overall -- reporting `CONTRADICTED` in that case would be an unearned claim), or the
answer's own text could not be parsed into a checkable claim in the first place. `UNVERIFIABLE` is never
silently accepted as `VALIDATED`.

`extract_claim()` parses raw answer text into a checkable `AnswerClaim`; `check_module_existence()` and
`check_build_inclusion()` are the two real evidence checks; `validate_answer()` is the combined entry
point. It does not decide which intake answer is "the" answer, does not write to any question queue,
decision store, or manifest, and does not run any build, job, or LSF submission -- it reads two
already-real evidence sources and reports what they say.

Proven by `dv_harness_tests/test_user_answer_validator.py` (24 tests): a claimed module present in real
parsed RTL is `VALIDATED`; a case-mismatched or wrong-path match is `PARTIALLY_VALIDATED`; a genuinely
absent module/file is `CONTRADICTED`; missing inputs, an unparseable answer, and a real verible parse
failure with no match found among what did parse are all `UNVERIFIABLE`, distinctly from `CONTRADICTED`.

**Disclosed residual**: this is a distinct consumer from `dut_evidence_correlation.py` (which validates
REQUIREMENTS, not raw intake answers). It decides nothing beyond its own four-status report.


<!-- S212: moved verbatim from CLAUDE.md original lines 11841-11856 (M4.6 CLAUDE Context Normalization) -->
## Intake Events: the Fixed 18-Event INTAKE_* Taxonomy (2026-09-06)

`loop_telemetry.py`'s section-108 taxonomy (see "Loop Telemetry Events" above) is this project's real precedent for a fixed, closed event vocabulary written through the SAME `storage.StateStore.event()` every subsystem in this harness already uses -- no second audit file, ever. Section 34 asks for the intake-domain equivalent: a fixed 18-event `INTAKE_*` taxonomy, wired into real transitions of `intake_state.py` and `verification_intake_contract.py`. Neither module emitted a single event before this change -- both say so in their own docstrings ("this module mints no `.dv-harness/` state of its own" / "writes no state/blackboard/approval record"), and a repo-wide grep for `INTAKE_[A-Z_]+`, `intake_events_taxonomy`, `Intake Events`, and "section 34" found no in-repo document naming a fixed INTAKE_* vocabulary at all -- unlike section 108, whose nineteen names this checkout could transcribe from a real prior specification, no such external text is discoverable here.

**The eighteen names are DERIVED, 1:1, from the two named modules' own real surfaces -- never invented for a fact neither module produces.** `dv_harness/intake_events.py` maps 13 events onto `verification_intake_contract.IntakeContractState`'s own 13-state lifecycle (`CREATED -> DISCOVERING -> CORRELATING -> QUESTION_PENDING -> USER_INPUT_RECEIVED -> VALIDATING -> CONFLICT -> PARTIAL -> BLOCKED -> READY_FOR_REVIEW -> BASELINED -> STALE -> REVALIDATING`), one event named for the state being ENTERED per real transition -- the identical convention `loop_telemetry.LOOP_STATE_TO_EVENT` already uses for `LoopState`. The remaining 5 cover `intake_state.py`'s own real per-run findings: one `INTAKE_STATE_BUILT` summary per `build_intake_state()` call, one `INTAKE_FIELD_BLOCKED`/`INTAKE_FIELD_CONTRADICTED` per field that ACTUALLY carries that status (never for the five routine statuses -- AUTO_RESOLVED/USER_CONFIRMED/PARTIAL/MISSING/UNKNOWN/NOT_APPLICABLE mint no event of their own), and the two mutually-exclusive terminal outcomes of `evaluate_uvm_generation_ready()`. `assert_intake_event_taxonomy_total()` (run at import) holds this structurally rather than by comment: the state mapping is total over `IntakeContractState` in both directions, the eighteen names partition exactly into the 13-and-5 split with no overlap and no orphan, and the tuple really is eighteen names long with no duplicate.

**Emission is opt-in, with a `store: Any = None` keyword added to `create_contract()`/`transition_contract()` (verification_intake_contract.py) and `build_intake_state()`/`evaluate_uvm_generation_ready()` (intake_state.py), default `None` on every one.** `storage.StateStore.__init__()` itself `mkdir()`s `.dv-harness/` the first time it is constructed, so unconditionally opening one from inside either module would mint a project tree merely because a caller asked a QUESTION ("is this project's intake ready") -- exactly the fabricated side effect `golden_flow_readiness.py`/`confidence_calibration.py` already refuse for the identical reason, and exactly the boundary both modules' own docstrings already promise ("mints no state of its own"). A caller who wants the real, persistent audit trail constructs a real `StateStore` themselves (as `engine.py` already does for every other subsystem) and passes it in; every pre-existing call site of all four functions in this repo passes no `store` and is byte-for-byte unaffected -- proven directly by two negative-control tests asserting `.dv-harness/` is never created when `store` is omitted. Every emitter is best-effort, mirroring `engine.py`'s own `_emit_loop_event()` two-level try/except exactly: a real emission failure records `INTAKE_EVENT_EMIT_FAILED` (deliberately NOT one of the eighteen -- a failure to observe intake is not one of the eighteen things being observed) and never turns an already-computed transition/build/readiness result into a crash.

**The reader half reuses, rather than re-implements, `loop_telemetry.read_events()`** -- the same public generic events.jsonl parser `platform_health.py` already reuses instead of adding a third one beside it and `dashboard._tail_events()`. `read_intake_events()` filters that shared reader's output down to the eighteen names; a monkeypatch test proves the delegation is real, not a second parser dressed up to look like a call-through.

Front door: `python -m dv_harness.intake_events names|events` (`execute_verb()`, the same shared convention `loop_contract`/`loop_budget`/`loop_telemetry` follow). No `dv-harness` CLI verb and no `gates.py`/`cli.py` edit -- both are large files under concurrent edit pressure in this same multi-agent session, the same disclosed choice several recent modules in this codebase already make.

**Deliberately bounded, and stated rather than implied closed.** (1) This module derives no intake fact of its own -- every field on every event is read off an already-computed `VerificationIntakeContract`/`IntakeState`/`UvmGenerationReadiness` object, never recomputed here. (2) It does not decide whether intake is ready, whether a transition is legal, or which field is BLOCKED/CONTRADICTED -- those verdicts stay entirely `verification_intake_contract.py`'s/`intake_state.py`'s own; this module only reports them. (3) It writes nothing but events, and it authorizes nothing: no approval, no question, no Blackboard topic, no state file. (4) It is REACHED, not WIRED: no `run_stage()`/`advance()` call site invokes either module at all (both remain, as their own CLAUDE.md sections already disclose, capstone/joining modules a caller invokes directly), so nothing in this harness automatically supplies `store=` today -- a caller wanting the real audit trail must pass one explicitly.

Proven by `dv_harness_tests/test_intake_events.py` (26 tests, `python -m pytest dv_harness_tests/test_intake_events.py -q` -> `26 passed`; the pre-existing `test_intake_state.py` (41 tests) and `test_verification_intake_contract.py` (34 tests) suites were re-run in full alongside it with zero regressions). The taxonomy's totality/partition/no-duplicate guarantees are proven directly; `emit()`'s refusal of a name outside the eighteen is proven the same way `loop_telemetry.emit()`'s own refusal test already is. The real wiring is proven end to end: a full real 23-transition lifecycle walk through `transition_contract(..., store=...)` (the same path `test_verification_intake_contract.py`'s own central test already drives) is asserted to produce the exact ordered event sequence `INTAKE_CONTRACT_STATE_TO_EVENT` predicts, with every one of the 13 contract-state events produced by that one real path; a real T4-undecidable bind entry plus a real `env_manifest.build_dut_facts_address_map()` disagreement (never a hand-typed CONTRADICTED record) drives `INTAKE_FIELD_BLOCKED`/`INTAKE_FIELD_CONTRADICTED`, with a paired negative control proving a clean build emits `INTAKE_STATE_BUILT` and zero fabricated field findings; the six-blocking-category refusal path and the real all-six-resolved readiness path (both reusing `test_intake_state.py`'s own real fixture recipes -- a real VIP-release filesystem scan, a real T1 bind, a real Gate-1 PASS) each prove exactly one of `INTAKE_GENERATION_READY`/`INTAKE_GENERATION_BLOCKED` fires, never both, never neither. A real `_FailingStore` whose `.event()` always raises proves a real `create_contract()`/`transition_contract()` result is still returned, unharmed, on a genuine emission failure. Both real CLI verbs are driven as real subprocesses.


<!-- S289: moved verbatim from CLAUDE.md original lines 17218-17292 (M4.6 CLAUDE Context Normalization) -->
## Artifact Relationship Discovery: Real Shared-Identifier Matching Across Intake Sources (2026-09-06)

CLAUDE_L5_INTAKE_MASTER.md section 6 asks for discovering real relationships between intake
artifacts (a register-map file referencing a block also described in a spec doc, and similar
cases), using `design_source_inventory.py`'s real registry rows as input, reporting a
relationship only when a real shared identifier/citation proves it. `dv_harness/
artifact_relationship_discovery.py` is that mechanism.

**REUSE OVER REINVENT was checked first.** A repo-wide grep for `artifact_relationship`/
`relationship_discovery`/`ArtifactRelationship`/`discover_relationships` found nothing
executable before this module was built. Two similarly-shaped mechanisms exist and were
deliberately NOT reused: `design_knowledge_correlation.py` correlates FACTS a caller has
already reduced to `{fact_key, value}` pairs and joins on the caller's own `fact_key` -- it
never discovers that two pieces of ARTIFACT CONTENT share an identifier in the first place;
`doc_citation_check.py` checks that a Markdown doc's own `file.py:line` citations still point
at the symbol they claim to -- a citation-drift checker over prose that already names a
specific file:line, not a discovery mechanism for relationships nobody has cited yet.

**Every extracted identifier comes from a real producer, never a filename or a caller-declared
`type` string.** Dispatch is by real file suffix. RTL (`.v`/`.sv`/`.svh`) goes through the real
`verible_parser.parse_file()` -- module/parameter/port names, each carrying a real structural
locator (`module:<name>`, `module:<m>/parameter:<p>`). JSON goes through the real
`env_manifest.load_register_map()`, schema-validated against `register_map.schema.json` --
block/register/field names, carrying a `block:<b>/register:<r>/field:<f>` locator. Plain
text/Markdown is line-scanned for designed-looking tokens (underscore-joined, ALL_CAPS, or
CamelCase, past a disclosed stopword list and a minimum core length) with a real `line:<n>`
citation. A `.pdf` is never opened raw (per the Context Budget Tier-1 `NEVER-*` rule) -- it is
resolved by reading the real `<stem>.fulltext.txt` sibling `vip_user_guide_distill.
distill_user_guide()` already produces; absent that sibling, the row is honestly
`NOT_AVAILABLE` naming the real distill command, never a silently empty contribution.

**A relationship is reported only when a real identifier is shared, normalized (case-folded,
never fuzzy), between two artifacts' own extracted sets -- and the anti-false-positive rule
keeps a shared prose TOKEN from manufacturing a relationship on its own.** A NAMED ENTITY (a
real parsed RTL module/parameter/port, or a real register-map block/register/field) matching
on either side is always reportable; a match where BOTH sides are only weak line-scanned
TOKENS is refused, because two spec documents sharing an ordinary word is not evidence of a
real relationship. `discover_relationships()` takes a bare row list (or the full
`build_source_registry()`-shaped dict via `discover_relationships_from_registry()`), reuses a
caller-supplied `extraction_results` cache across calls, and reports every unresolved artifact
honestly rather than silently omitting it from the relationship graph.

**Deliberately bounded.** This module discovers no artifact of its own -- its rows come
entirely from `design_source_inventory.build_source_registry()` or an equivalent caller-
supplied row list in that shape. It decides, approves and arbitrates nothing (no build, no
job, no approval, and there is deliberately no stage gate -- a discovered relationship is an
input to a human/agent's intake review, never a verification verdict). It never mines a
golden-reference environment for protocol-behavior content -- every identifier it reports
comes from the current project's own artifacts.

Front door: `dv-harness artifact-relationship-discovery --sources <file> [--json]`, and the
identical `python -m dv_harness.artifact_relationship_discovery --sources <file> [--json]`
(one shared `main()`). Exit 0 when at least one relationship is discovered, 1 when none is,
2 on a malformed/unreadable sources file.

Proven by `dv_harness_tests/test_artifact_relationship_discovery.py` (25 tests, re-run by this
integration pass: `python -m pytest dv_harness_tests/test_artifact_relationship_discovery.py -q`
-> `25 passed`, including two gated on a real `verible-verilog-syntax` binary and genuinely
exercised rather than skipped on this machine): per-kind extraction from a real register-map
JSON, real verible-parsed RTL, a real plain-text scan (including stopword exclusion), and the
real `vip_user_guide_distill.py` fulltext-sibling PDF route (both present and absent); the
headline worked example -- a real register-map block name (a NAMED ENTITY) matched against a
real citing token in a spec doc, reported as a relationship with both sides' real kinds and
locators; the negative control that gives the anti-false-positive rule its detection power
(two spec docs sharing only a generic scanned token are confirmed NOT related, with the token's
real extraction on both sides independently verified so the absence of a relationship is the
rule firing, not an extraction failure); a real cross-module RTL-to-RTL parameter-name match
(`LANE_WIDTH` shared between two independently-parsed modules) proving matching is not limited
to text-scanned tokens; unresolved-artifact honesty; extraction-result cache reuse; the real
`build_source_registry()` integration path; markdown rendering; and the CLI's three exit codes.

**Wiring note.** `dv-harness artifact-relationship-discovery` is registered in `cli.py`'s
argparse tree, sharing one implementation with the standalone `python -m` entry point --
confirmed working end to end (`python -m dv_harness.cli artifact-relationship-discovery --help`).


<!-- S290: moved verbatim from CLAUDE.md original lines 17293-17306 (M4.6 CLAUDE Context Normalization) -->
## Dynamic Intake Graph: a Live View Joining Intake Fields + Artifact-Relationship Edges (2026-09-06)

`intake_state.py` already joins env.manifest.json's per-layer facts, `question_queue.py` decisions and `connectivity.py` bind tiers into one per-field `IntakeFieldRecord` set -- but it stays a FLAT field list. Nothing in this repo let a caller see the whole intake surface as one connected structure: which fields group into which category, and which fields (or external artifacts) relate to one another. `dv_harness/dynamic_intake_graph.py` (section 7) is that graph VIEW, and it computes no intake fact of its own.

**REUSE, not reinvention, on every fact it graphs.** Every FIELD node's `status`/`confidence`/`value`/`source`/`owner`/`reason` is the real `intake_state.IntakeFieldRecord` `intake_state.build_intake_state()` already produced. Every CATEGORY node's rollup is `IntakeState.category_status()`'s own worst-wins fold, called through verbatim -- never re-derived a second way, and `evaluate_uvm_generation_ready()`'s six-category refusal gate is not duplicated here. A category with zero recorded fields still gets a node, honestly `MISSING` via that same real fold, reusing `intake_state.BLOCKING_CATEGORIES` -- a category this run never saw must never disappear from view.

**`artifact_relationship_discovery.py` was built concurrently in this same batch, after this module's own docstring first recorded (correctly, at the time) that it did not exist.** The two modules answer genuinely different questions and stay deliberately separate rather than merged: that module discovers real shared-identifier relationships BETWEEN ARTIFACTS (an RTL module, a register-map block/register/field, a cited text token), keyed by `source_id`; this module joins intake FIELDS, keyed by field name. `edges_from_artifact_relationships()` is the small, purely-reshaping bridge between them -- it takes that module's own real `RelationshipDiscoveryReport` (or its `.to_dict()`, or a bare relationship list) and reshapes each already-discovered, already-evidenced relationship into this module's own duck-typed edge shape (`{"from", "to", "relation", "evidence"}`), carrying the real matched identifier as `relation` (`SHARES_IDENTIFIER:<name>`) and folding both sides' real `name (kind) @ locator` citations into `evidence` -- it computes zero new relationship logic of its own. A caller with only an `IntakeState` and no artifact-relationship report at all still gets a real, honestly partial graph (FIELD/CATEGORY nodes only; `sources_used["relationship_edges"]` stays `False`, never fabricated `True`).

**EVIDENCE TRUTH RULE, applied throughout.** A relationship edge naming an endpoint no `IntakeFieldRecord` ever recorded still gets a real `RELATES_TO` edge, but the endpoint becomes an honest `ARTIFACT` stub node -- never silently coerced into an existing FIELD it does not actually name. A missing `relation` is recorded as `"UNSPECIFIED_RELATION"`, never a guessed verb. `graph_connectivity_report()` is honestly `NOT_APPLICABLE` over an `IntakeState` with zero records, rather than a fabricated clean pass. `impacted_neighbors()` for a field name this graph never saw returns `NOT_AVAILABLE`, never an empty-but-clean neighbor list indistinguishable from "checked, found nothing".

**Deliberately bounded.** No relation-kind taxonomy is invented -- relation text is opaque to this module, grouped/counted by whatever string the caller (or the adapter) supplied. No question is filed, no gate invoked, no build/regression/LSF job started, no state/blackboard/approval record written -- the same "JOINS and REPORTS" boundary `intake_state.py` itself keeps. No `dv-harness` CLI verb (`cli.py` is out of this task's file-safety scope, matching several sibling same-day modules' own disclosed choice); the front door is `python -m dv_harness.dynamic_intake_graph --intake-state <file> [--relationships <file>] [--json]`.

Proven by `dv_harness_tests/test_dynamic_intake_graph.py` (28 tests, re-run by this integration pass: `python -m pytest dv_harness_tests/test_dynamic_intake_graph.py -q` -> `28 passed`): every FIELD/CATEGORY fact is built through the real `intake_state.build_intake_state()` (with real `phy_boundary.classify_boundary()`/`decide_bind_location()` output feeding `dut_boundary`, never a hand-written `IntakeFieldRecord`), including the blocking-category-with-zero-fields negative control (still `MISSING`, never silently omitted). The artifact-relationship integration is proven against a REAL `artifact_relationship_discovery.discover_relationships()` call over two real files on disk (a schema-valid register-map JSON and a text doc genuinely sharing a register name), asserting the adapted edge, the resulting ARTIFACT stub nodes, and the `SHARES_IDENTIFIER:` relation citing the real evidence -- paired with negative controls proving no-shared-identifier reports zero edges (never fabricated) and a malformed/incomplete relationship entry raises rather than silently degrading. CLI success/failure paths (malformed intake-state file, malformed relationships file) are driven as real subprocesses.


<!-- S292: moved verbatim from CLAUDE.md original lines 17321-17379 (M4.6 CLAUDE Context Normalization) -->
## Intake Modes: FAST / STANDARD / STRICT / SIGNOFF (2026-09-06/07)

Section 17 asks for a declared intake rigor MODE that changes which `intake_state.py` fields/categories
are mandatory before generation may proceed, reusing `verification_intake_contract.py`'s own `INTAKE_READY`
conjunction rather than a fixed one-size rule. `dv_harness/intake_modes.py` is that mode layer, built and
verified as part of this same multi-agent batch (found already complete under REUSE OVER REINVENT's own
mandatory pre-check; this section documents rather than duplicates it).

**Two mechanisms reused verbatim, zero new readiness engine.** `IntakeState.category_status()` (worst-wins
per-category fold) and `verification_intake_contract.evaluate_intake_readiness()` (the `INTAKE_READY`
conjunction) are called unmodified; this module's only job is building that function's `conditions` list
DIFFERENTLY per declared mode. `STANDARD`'s `required_categories` is `intake_state.BLOCKING_CATEGORIES`
verbatim -- proven, not merely asserted, identical in scope to the pre-existing
`evaluate_uvm_generation_ready()` fixed rule on both a passing and a failing state. `FAST` requires only
`dut_boundary`/`build_env` (a five-second sanity check, never a generation-readiness claim). `STRICT` adds
the seventh category, `general` (DUT RTL/registers/address-map/clock-reset, VIP user-guide refs, component
hierarchy, config_db trace, testplan correspondence) -- every category `build_intake_state()` ever
populates. `SIGNOFF` shares STRICT's category coverage but switches AXIS: one condition per RECORDED FIELD
across the whole `IntakeState` rather than one per category, so a human doing final sign-off sees the exact
blocking field, not only the category name -- proven to never disagree with STRICT's own boolean verdict
over the identical state, only in diagnostic granularity. `assert_modes_monotonically_increasing()` runs at
import and checks the table's own internal consistency (each mode's required-category set is a real
superset of the previous mode's, and SIGNOFF genuinely widens granularity rather than narrowing scope).

**Status-vocabulary bridge, held total.** `IntakeFieldStatus`'s eight values fold onto
`verification_intake_contract.CONDITION_STATUSES`' four (`MET`/`UNMET`/`UNKNOWN`/`NOT_APPLICABLE`) via a
documented, total mapping (`AUTO_RESOLVED`/`USER_CONFIRMED` -> MET; `NOT_APPLICABLE` -> NOT_APPLICABLE;
`BLOCKED`/`CONTRADICTED` -> UNMET; `MISSING`/`UNKNOWN`/`PARTIAL` -> UNKNOWN), asserted total at import
against the real `IntakeFieldStatus` enum so a future status value would fail loudly rather than silently
falling through unmapped.

**The negative control this project is graded on.** An `IntakeState` carrying zero records never reads
READY under any of the four modes: the category-granularity modes (FAST/STANDARD/STRICT) still build one
condition per required category, each honestly folding MISSING (via `category_status()`'s own worst-wins
rule over no evidence) into UNKNOWN, so they report `NOT_READY` naming every required category as
blocking; SIGNOFF's field-granularity conditions are built directly off the (here, empty) record list, so
an empty state gives it nothing to evaluate and it reports the honest `NOT_AVAILABLE`, never a vacuous
READY.

Ad hoc front door only, per this batch's own `cli.py`/`gates.py` avoidance rule (both files under heavy
concurrent edit pressure across this batch): `python -m dv_harness.intake_modes modes|conditions|evaluate
[--mode ...] [--intake-state <path>] [--json]`, sharing one `execute_verb()`. Exit 0 READY, 1 NOT_READY,
2 NOT_AVAILABLE or a usage error.

**Deliberately bounded, and stated rather than implied closed.** It builds conditions and reads
`IntakeState`; it runs no gate script, writes no state/blackboard/approval record, files no question, and
holds no stage gate of its own -- the same boundary `intake_state.py`'s own
`evaluate_uvm_generation_ready()` already draws, one mode-selection layer higher. `cli.py`/`gates.py` are
untouched.

Proven by `dv_harness_tests/test_intake_modes.py` (29 tests, re-run by this integration pass: `python -m pytest
dv_harness_tests/test_intake_modes.py -q` -> `29 passed`): the mode table's own monotonicity and
STANDARD-equals-BLOCKING_CATEGORIES identity; the status-mapping totality and per-value correctness; the
empty-state negative control above; FAST-passing-where-STANDARD-fails; STANDARD agreeing with the legacy
`evaluate_uvm_generation_ready()` rule on both PASS and FAIL states; STRICT catching a `general`-category
defect STANDARD's six categories cannot see; SIGNOFF-vs-STRICT boolean agreement with finer blocking-name
granularity; a real `IntakeState.to_dict()` round trip via `load_intake_state()`; and the CLI driven both
in-process and as a real `python -m dv_harness.intake_modes` subprocess.


<!-- S293: moved verbatim from CLAUDE.md original lines 17380-17458 (M4.6 CLAUDE Context Normalization) -->
## Incremental/Resume Intake: STALE -> REVALIDATING, Driven From Real Evidence (2026-09-06)

Section 18 asks whether `verification_intake_contract.py`'s own 13-state lifecycle
(`... -> BASELINED -> STALE -> REVALIDATING`) already covers incremental/resume intake, or
whether a genuine gap remains. Re-verified directly before writing anything: the lifecycle
itself is real and already correct -- `TRANSITIONS[BASELINED] == (STALE,)`,
`assert_no_absorbing_state()` proves `STALE` carries a real outgoing edge to `REVALIDATING`, and
that module's own docstring already reasons about *why* the edge exists ("a baselined contract
can be invalidated by a later spec/RTL/config change ... this module does not re-implement that
decision, it only accepts the caller's resulting STALE transition once made"). What was
genuinely missing -- confirmed by a repo-wide grep for
`intake_stale`/`IntakeContractStale`/`intake_contract_stale` before this closure, which matched
nothing executable -- was a real DETECTOR: nothing anywhere ever produced that `STALE`
transition from real evidence, so a contract baselined months ago against RTL/spec that has
since moved would report `BASELINED` forever unless a human happened to notice and hand-typed
the transition themselves.

`dv_harness/intake_contract_stale_detection.py` is that detector, mirroring
`loop_stale_detection.py`'s own proven pattern for `LoopState.STALE` one module over, applied to
intake contracts specifically. Two independently-computed real signals, worst-wins:

- **TIME-BASED** -- how long ago this contract was last transitioned INTO `BASELINED`, read
  directly off the contract's own `state_history` (never a second store), compared against a
  DECLARED staleness window (`config.json`'s `policy.intake_stale_after_seconds`, or this
  module's own documented `DEFAULT_INTAKE_STALE_AFTER_SECONDS` -- a week, not the loop module's
  24h, because an intake baseline is a slower-moving commitment and reusing the loop module's own
  default would be exactly the "reuse a number, not just a discipline" mistake this project's own
  precedent warns against).
- **ENVIRONMENT-MOVED** -- the project's real current git HEAD has moved, by a REAL
  `git diff --name-only` computed through `change_impact.changed_files()` -- the exact function
  `loop_stale_detection.py`, `golden_scenario.evaluate_freshness()` and
  `signoff_export.evaluate_freeze_invalidation()` already reuse for the identical "did the design
  move" question at three other layers -- classified through the SAME `change_impact.
  classify_risk()` HIGH/MEDIUM/LOW ladder those three callers already use. The recorded baseline
  SHA is read from a caller-declared `contract.sub_domains["baseline_git_sha"]` convention or an
  explicit `recorded_sha` override; neither present is honestly `UNKNOWN`, never a guessed
  "nothing moved".

STALE from either signal outranks everything; absent that, an UNKNOWN signal (no real
baseline-event evidence, no recorded SHA, no git) outranks a clean NOT_STALE -- "we could not
check" is never silently read as "we checked and it is fine". `apply_stale_transition()` drives
the real move ONLY through `verification_intake_contract.transition_contract()`'s own,
already-enforced `assert_legal_transition()` (refusing anything but a real `BASELINED` contract,
exactly as a hand-typed call would), and refuses to act unless handed a real `detect_
intake_contract_staleness()` result whose status is `STALE`. `detect_and_maybe_transition()`
detects, then applies the transition only when the evidence says STALE AND the contract is still
legally eligible (`BASELINED`) -- a contract a human already moved on, or already `STALE`, is
left untouched. It mints no `.dv-harness/` tree of its own (`config.json` read with a plain,
tolerant `json.loads()`, never `config.load_config()`, which would create one) and runs no stage,
gate, build, job, or approval. Front door: `python -m dv_harness.intake_contract_stale_detection
window|detect` (no `dv-harness` CLI verb, per this task's own scope).

Proven by `dv_harness_tests/test_intake_contract_stale_detection.py` (32 tests) against REAL
machinery throughout -- a real throwaway git repository with real commits (environment-moved
staleness is derived from a genuine `git diff` between two real SHAs, a real HIGH-risk RTL commit
correctly flips a clean contract STALE while a LOW-risk doc-only commit does not), real plain
JSON `config.json` files on disk, and real `VerificationIntakeContract` objects driven through the
real, unmodified `create_contract()`/`transition_contract()` -- never a hand-shaped stand-in for
either. The mandated negative control
(`test_combined_unknown_never_fabricated_as_not_stale_on_a_never_baselined_contract`) proves a
fresh, never-baselined contract in a bare project with no git repository reports the combined
verdict `UNKNOWN`, never a fabricated `NOT_STALE`, and mints no `.dv-harness/` tree in the
process. `apply_stale_transition()` is proven both to drive a real legal move into `STALE` (and
from there on into a real `REVALIDATING`, exercising section 18's own "every state has a real
outgoing edge" guarantee) and to refuse a non-`STALE` report, a report against a contract not
currently `BASELINED`, and a contract a human already moved on from underneath that decision. The
CLI front door is driven as a real subprocess across both verbs and all documented exit codes.
Re-run by this integration pass alongside the pre-existing `dv_harness_tests/test_verification_intake_contract.py` (34
tests, unmodified, unaffected): `python -m pytest
dv_harness_tests/test_verification_intake_contract.py
dv_harness_tests/test_intake_contract_stale_detection.py -q` -> `66 passed`.

**Disclosed provenance**: both files already existed on disk (with full docstrings and a
passing test suite) by the time this item was picked up in this same multi-agent batch --
re-verified rather than assumed. Per REUSE OVER REINVENT, no second, parallel module was
written; this section documents the real, already-satisfied capability rather than a new one, and
supplies the CLAUDE.md entry the module's own docstring already implied but the live file was
still missing.


<!-- S295: moved verbatim from CLAUDE.md original lines 17531-17621 (M4.6 CLAUDE Context Normalization) -->
## Intake Audit / Provenance Record: Structured Who/What/When Over intake_state.py (2026-09-07)

`intake_state.py` already carries `source`/`confidence`/`owner` per intake field, and its
`_apply_decision_overlay()` already reads a real `question_queue.QuestionQueueStore.
find_decision()` result's full structured provenance -- `current.decided_by`/`current.decided_at`/
`current.source`/`current.basis`/`current.question_id_of_answer`, plus the complete `history` list
of every prior decision for that question_key (including whether a Tier-2 auto-assumption was
later `overturned` by a human). But it then COMPRESSES all of that into one human-readable `reason`
string and an overwritten `owner` field before returning the `IntakeFieldRecord` -- a caller holding
only the resulting `IntakeState` has no structured way to recover WHO decided a field, WHEN, on what
BASIS, under which real Q-ID, or whether an earlier machine guess was later corrected, only prose.
That is the real, narrow gap this section closes: a structured, per-fact provenance record
(who/what/when established it), reusing `intake_state.py`'s own `source`/`confidence`/`owner` as
the base rather than re-deriving them.

`dv_harness/intake_audit_provenance.py` closes it WITHOUT touching `intake_state.py` and without
re-implementing any of its overlay/resolution logic: `build_intake_audit_provenance(intake_state,
question_store=None, field_question_keys=None)` calls the exact SAME one sanctioned read
`intake_state.py` itself is restricted to -- `QuestionQueueStore.find_decision()`, never
`add_question()`/`answer_question()` -- using the SAME `question_store`/`field_question_keys` a
caller already built for `intake_state.build_intake_state()`, and folds the real decision record it
gets back together with the real `IntakeFieldRecord` it already has. There is no second decision
store and no second overlay algorithm; only a second, more structured READ of the one real decision
`intake_state.py` already consulted.

**"Established" is derived from `intake_state.py`'s OWN documented status vocabulary, never
re-defined.** A field is ESTABLISHED whenever its status is anything other than MISSING ("no
evidence was supplied at all") or UNKNOWN ("evidence was supplied but is inconclusive") --
AUTO_RESOLVED/USER_CONFIRMED/PARTIAL/CONTRADICTED/BLOCKED/NOT_APPLICABLE all mean *something*
concrete was determined, even a blocking or conflicting determination. A field that was never
established gets `established_by = None` and `established_by_status = NOT_ESTABLISHED` -- never a
guessed owner or a fabricated timestamp.

**A closed, five-value `established_by_status` (WHO), never a guess beyond what real evidence
supports**: `HUMAN` (a real decision found -- or the field's own status is USER_CONFIRMED, which
`intake_state.py`'s own docstring guarantees means a real human decision is on file -- whose
`current.source` is `question_queue.HUMAN_DECISION_SOURCE`); `TIER2_ASSUMPTION` (a real decision
found with `current.source == TIER2_AUTO_ASSUMPTION_SOURCE` -- a harness-side guess, explicitly
never attributed to a person); `SYSTEM_COMPUTED` (established directly from a real producer --
env_manifest/connectivity/phy_boundary/a Gate-1 result/a caller-supplied list -- with no
question_queue decision involved); `UNVERIFIABLE` (the field's status is CONTRADICTED, which can
come from EITHER two disagreeing computed sources OR a human disagreeing with a computed value per
`intake_state.py`'s own design, and no `question_store` was supplied to this module to tell the two
apart -- reported honestly rather than defaulted either way, the Evidence Truth Rule applied to this
module's own output); `NOT_ESTABLISHED` (MISSING/UNKNOWN).

**WHAT (`established_via`)** is `record.source` reused verbatim, plus -- only when a real decision
was actually found -- the real question_queue mechanism and Q-ID that confirmed/contradicted/
strengthened it (`confirmed_by=question_queue:human_answer(question_id=...)`, etc., one verb per
`intake_state.py` status so "confirmed" and "contradicted" are never spelled the same way).
**WHEN (`established_at`)** is the decision's own real `decided_at` when found, else the base
record's own `last_validated` when the base module set one, else `None` with
`established_at_status = "UNKNOWN"` -- deliberately never back-filled from the batch's own
`generated_at` (`IntakeState.generated_at`, carried separately on the report as
`state_generated_at`), since that is a fact about when the REPORT was built, not about when any one
fact was established, and conflating the two would misrepresent a computed fact with no per-fact
timestamp evidence as though it had one.

Deliberately bounded, and stated rather than implied closed: this module JOINS AND REPORTS ONLY,
exactly `intake_state.py`'s own restraint restated -- it files no question, answers no question,
runs no gate, and writes no state/blackboard/approval record. It mints no `.dv-harness/` event of
its own; `intake_events.py`'s eighteen-event taxonomy is a fixed, closed vocabulary this module does
not widen. Precision is bounded by the caller's own inputs: omitting `question_store`/
`field_question_keys` (the same opt-in shape `intake_state.build_intake_state()` itself uses)
narrows `HUMAN`/`TIER2_ASSUMPTION` down to the honest `UNVERIFIABLE`/`SYSTEM_COMPUTED` split
described above rather than silently guessing which applies.

No `dv-harness` CLI verb was added, and `cli.py`/`gates.py` were not touched -- the ad hoc front
door is `python -m dv_harness.intake_audit_provenance` via its `execute_verb()` (the same
shared-convention shim `loop_contract`/`loop_budget`/`intake_events` already use), or the module's
own `build_intake_audit_provenance()` called directly from any Python caller.

Proven by `dv_harness_tests/test_intake_audit_provenance.py` (14 tests, re-run by this integration
pass alongside the pre-existing `test_intake_state.py` (41 tests) and `test_intake_events.py` (26
tests) suites: `python -m pytest dv_harness_tests/test_intake_state.py
dv_harness_tests/test_intake_events.py dv_harness_tests/test_intake_audit_provenance.py -q` ->
`81 passed`, 0 regressions) against real production code throughout, matching `test_intake_state.py`'s
own discipline: a real `question_queue.QuestionQueueStore` driven through its real `add_question()`/
`answer_question()` API on a throwaway root, real `env_manifest.build_dut_facts_registers()`/
`build_dut_facts_address_map()` calls (including a genuine base-address disagreement producing a
real CONTRADICTED status), and real `connectivity.BindTier` values -- never a hand-written decision
or field record. The negative controls are what give it detection power: a MISSING field reports
`NOT_ESTABLISHED` with `established_by=None`; a CONTRADICTED field with no lookup supplied at all
reports the honest `UNVERIFIABLE` (never guessed HUMAN or SYSTEM_COMPUTED); the identical field with
an empty-but-supplied lookup that genuinely finds no decision correctly upgrades to
`SYSTEM_COMPUTED` (confidently ruling out human involvement because the lookup was actually
checked, not merely absent); a BLOCKED bind entry is proven still `established` (never silently read
as absent); and a real Tier-2 auto-assumption is proven distinct from a real human decision
(`TIER2_ASSUMPTION`, never `HUMAN`, never attributed to a person's name). `intake_state.py` and
`intake_events.py` were both left byte-for-byte untouched.


<!-- S311: moved verbatim from CLAUDE.md original lines 18760-18817 (M4.6 CLAUDE Context Normalization) -->
## Intake Plain-Language Summary: One-Shot Confirmation Over intake_baseline.py's Own Fields (2026-09-07)

`intake_baseline.py`'s `capture_intake_baseline()`/`freeze_intake_baseline()` produce structured
JSON over the twelve pre-generation intake facts, but nothing rendered a plain-language "here is
everything I now believe about your project -- confirm or correct" summary before the baseline
locked in. A repo-wide grep for `plain_language`/`plain-language`/`confirm or correct`/
`one-shot confirmation` before this module was written matched only unrelated docstring hits in
`de_command_review_package.py` and `session_snapshot.py` -- neither renders an intake summary.

`dv_harness/intake_plain_summary.py` is that renderer, and it captures no fact of its own: it reads
ONLY the real `capture_intake_baseline()`/`freeze_intake_baseline()` record's own fields, reusing
`intake_baseline.py`'s public `INTAKE_FIELDS`/`FIELD_CAPTORS`/`CAPTURED`/`NOT_AVAILABLE` directly
rather than re-declaring the field list. Per-field SHAPE (declared-fact / hash-or-files / list /
count) is classified by the identity (`__name__`) of the real captor `FIELD_CAPTORS` already points
at -- never a second, independently-maintained field->shape table that could silently drift out of
sync with `intake_baseline.py`'s own four captors. `FIELD_CATEGORIES`' membership is asserted at
import to be an exact partition of `INTAKE_FIELDS`, so a future field added there without a matching
entry here fails loudly rather than silently vanishing from the rendered summary.

**The Evidence Truth Rule, applied to rendering rather than capture.** A CAPTURED field's own real
`detail` is described honestly per its real shape (a declared value, a real file count, a real test
count, a real number) -- never a placeholder. When `intake_baseline.py`'s own `_MAX_INLINE_DETAIL_
CHARS` cap already dropped the inline value (`*_truncated` present in `detail`), that absence is
reported as exactly that ("too large to show inline"), never silently rounded to a guessed summary.
A NOT_AVAILABLE field's own real `reason` code is translated to a plain phrase and the field is
listed under "Open items needing your confirmation or correction" -- never silently omitted. A
malformed record (no `fields` key, a non-dict entry for a declared field, an unrecognized `status`
value) is refused (`IntakeSummaryError`) or rendered as an honestly-labeled "malformed record" open
item, never guessed past.

Accepts either shape: a raw `capture_intake_baseline()` result, or a `freeze_intake_baseline()`
result (detected via its own `baseline` key wrapping the identical fields shape, rendering the real
`freeze_id`/`frozen_by`/`frozen_at`/`note` alongside). An unfrozen record states plainly "this
baseline has NOT been frozen yet -- nothing has locked in."

**Deliberately bounded.** It never captures, freezes, evaluates, or invalidates a baseline itself --
only renders one a caller already produced. It decides, approves and arbitrates nothing: no build,
job, or approval is touched, and there is deliberately no stage gate. No `dv-harness` CLI verb was
added and `cli.py`/`gates.py` were not touched, per this project's own disclosed convention for a
standalone module -- the front door is `python -m dv_harness.intake_plain_summary render --file
<path.json>` (exit 0 every fact captured, 1 at least one open item remains, 2 a missing/unreadable/
malformed file).

Proven by `dv_harness_tests/test_intake_plain_summary.py` (32 tests, all real, built on real
`capture_intake_baseline()`/`freeze_intake_baseline()` output rather than a hand-typed stand-in for
either shape): category/label/shape coverage self-checks; a fully-captured baseline showing every
real value with no fabricated placeholder; the required negative control -- an empty-facts capture
reports all twelve fields honestly NOT CAPTURED with their real reason phrases, never a fabricated
partial-success claim; every captured-value shape (declared fact, multi-file hash, precomputed
hash, raw-content hash, test list, count) described from real detail; three truncation-honesty
tests (a large declared value, a large file map, a large test list each report "too large to show
inline" rather than guessing); frozen-record metadata rendering (with and without a note); a
partially-captured freeze still listing its real open items; `open_field_names()`'s canonical-order
contract; five malformed-record refusal/honesty tests; and a real CLI subprocess round trip across
all three documented exit codes. `python -m pytest dv_harness_tests/test_intake_plain_summary.py -q`
-> `32 passed`; `dv_harness_tests/test_intake_baseline.py` (52 tests, unmodified) re-run alongside it
confirms no regression to the module this one reuses.


<!-- S326: moved verbatim from CLAUDE.md original lines 19746-19783 (M4.6 CLAUDE Context Normalization) -->
## Question "Why Am I Being Asked This" Grounding: Closing the Disclosed Residual (2026-09-08)

`dv_harness/question_why_grounding.py` is exactly the follow-up the "'Why Am I Being Asked This'
Grounding" section above named: "a thin, explicitly-named wrapper over `request_clarification()`/
`build_escalation_package()` rather than a third, independently-derived explanation mechanism." It
computes no new fact about a question record, no new plain-English translation, and no new evidence
citation logic -- `explain_why_asked(store, question_id)` is a pure re-shaping of `question_queue.
request_clarification(store, question_id, record=False)`'s own real return value into a
purpose-named `{"question_id", "why", "evidence", "package"}` shape.

**Why a distinct entry point rather than callers reaching for `request_clarification()` directly.**
That function's own framing is REACTIVE: a human signals "I don't understand this question I was
already asked", and by default that signal is itself recorded as a real audit entry
(`record=True`) in `store.clarifications_path`. "Why am I being asked this" is a genuinely
different, PROACTIVE use -- the same grounding context shown *before* anyone attempts to answer,
with no implication anyone was confused and nothing filed as if they were.
`explain_why_asked()` therefore always calls the reused function with `record=False`; a dedicated
AST-walking test proves this module's own source contains no call to `add_question()`/
`answer_question()`/`_atomic_write_json()` or any other write-shaped primitive at all -- never
merely claimed.

Deliberately bounded: no question is ever filed or answered here, and nothing is decided --
`render_why_asked_markdown()` reuses the same "one labeled section per block" shape
`render_clarification_markdown()`/`render_escalation_package_markdown()` already establish, under
a "why" heading rather than a "clarification" one. There is no `dv-harness` CLI verb
(`cli.py`/`gates.py` were not touched, matching this session's own established convention for a
standalone module built while those files are under concurrent edit pressure) -- the front door is
`python -m dv_harness.question_why_grounding explain --root <dir> --question-id <id> [--json]`.

Proven by `dv_harness_tests/test_question_why_grounding.py` (11 tests): the headline reuse proof
(every field matches `request_clarification()`'s own real output, including the exact hard-trigger
plain-English translation and per-option evidence citation); the never-writes-`clarifications.json`
negative control (across two consecutive calls); a never-mutates-`questions.json` proof; the
unknown-question-id refusal; the missing-rationale honesty negative control; the Tier-2
machine-guess note; markdown rendering; the structural never-writes AST guard; and three real CLI
invocations (JSON, markdown, and the exit-2 refusal path). Re-run alongside the full pre-existing
`test_question_queue.py` suite (177 tests combined) -- zero regressions.


<!-- S328: moved verbatim from CLAUDE.md original lines 19907-19972 (M4.6 CLAUDE Context Normalization) -->
## Proactive Answer-Suggestion Mode (Suggest-Then-Confirm) (2026-09-07)

This item's own item-implementation agent produced no real evidence -- its report carried
placeholder `real_evidence_summary: "test"` and `claude_md_section_markdown: "test"`, with no
module/test paths at all. Rather than append that placeholder or leave the item silently
unrecorded, this integration pass independently searched `dv_harness/question_queue.py` (the
module this capability would naturally live in, since a suggested answer must be filed as part of
a question record) and found the capability was, in fact, already built -- evidently by a different
concurrent agent in this same multi-agent batch whose own report never reached this integration
step, or whose corresponding CLAUDE.md entry was never written. The code was independently read in
full and its real tests independently re-run before writing this section.

`question_queue.py` gained a real "suggest-then-confirm" evidence-citation contract, additive to
the existing options/recommendation shape and enforced the same way `normalize_grounding_evidence()`
already enforces its own citation requirement. A `suggested_answer` (schema key already present in
`question.schema.json`, `additionalProperties: false`) is a `{value, source_module, source_path,
rationale?}` dict, normalized and validated by `normalize_suggested_answer()`: `None` stays `None`
(never fabricated from the question's own text or a guessed default); a real suggestion REQUIRES
`value` (which must equal the question's own `recommendation` -- enforced in `validate_question()`
as a cross-field rule JSON Schema alone cannot express, so a suggestion can never silently diverge
from what the question actually recommends), `source_module` (restricted to
`SUGGESTED_ANSWER_SOURCE_MODULES = {"env_manifest", "design_source_inventory"}` -- the only two real
evidence producers this mode currently derives an answer from, never an open string a reader could
not go check), and `source_path` (WHERE in that producer's own real output the value was read). A
suggested value with no citation of its own evidence source is refused outright
(`QuestionValidationError`) -- exactly the unsupported claim the Evidence Truth Rule forbids.

**Two real derivation functions, neither re-parsing or re-deriving what their own source module
already computed.** `derive_suggested_answer_from_env_manifest(manifest, path, *, rationale=None)`
walks an already-loaded `env_manifest.load_env_manifest()` document down a caller-supplied path and
returns `None` -- never a guessed value -- unless the path's own most-specific fact-layer node
reports a real evidence-PRESENT `status` (`_ENV_MANIFEST_PRESENT_STATUSES`), correctly distinguishing
a COMPOSITE layer's own top-level `status` (e.g. `vip_config`'s own zero-time-dump status) from a
genuinely independent SUB-layer's own separate status (`vip_config.vip_release`'s own real
`$DESIGNWARE_HOME` scan result) so one unrelated absent fact can never wrongly gate an available one.
`derive_suggested_answer_from_design_source_inventory(rows, source_id, *, field="version",
rationale=None)` reads one already-evaluated `design_source_inventory.build_source_registry()` row
and suggests a value ONLY when that row's own real `status` is `STATUS_CURRENT` -- a STALE/
SUPERSEDED/NOT_AVAILABLE/UNKNOWN source is never suggested, since that module's own docstring is
explicit that a source whose content may have moved since it was last checked must not be trusted as
if it still described reality.

**`build_suggest_then_confirm_options(suggested_answer, *, alternative_labels=None)`** is the
caller-facing convenience that turns an already-derived suggestion into the exact `options`/
`recommendation` shape `add_question()` needs: the suggested value as one option (its own
`rationale` citing the real `source_module`/`source_path`), plus 0-2 real caller-declared
alternatives (never invented here), `recommendation` pinned to the suggested value so the
cross-field check passes by construction, and a hard refusal if the resulting option count would
fall outside `question.schema.json`'s own 2-3 cap or if an "alternative" merely repeats the
suggested value itself.

**Deliberately bounded, and stated rather than implied closed.** This mode can currently derive a
suggestion from exactly two real evidence producers -- a project whose relevant fact lives
elsewhere (a register-map spreadsheet, a spec document) gets no suggestion and falls back to the
existing plain options/recommendation flow, honestly, rather than a guessed one. It never lowers
the bar for what counts as a real answer -- a suggestion is still just one more pre-researched
option with its own cited rationale; a human still confirms or corrects it through the ordinary
`answer_question()` path, and nothing here auto-answers a question on a suggestion's own strength.

Proven by 42 real tests inside `dv_harness_tests/test_question_queue.py` (re-verified in this
integration pass: `python -m pytest dv_harness_tests/test_question_queue.py -q -k "suggest or
Suggest"` -> `42 passed`), and the full file (`python -m pytest dv_harness_tests/test_question_queue.py
-q` -> `157 passed`) confirms no regression to the rest of the module. There is no `dv-harness` CLI
verb dedicated to this mode; it is reached through `add_question(**build_suggest_then_confirm_
options(...))` directly.


<!-- S329: moved verbatim from CLAUDE.md original lines 19973-20045 (M4.6 CLAUDE Context Normalization) -->
## Session-Level Question-Order Strategy: `session_question_sequencer.py` (2026-09-07)

`intake_question_priority.rank_questions()` scores each pending question in isolation --
`blocking_value * downstream_impact * expected_confidence_gain / user_effort` -- and sorts the
whole batch by that one number. It never asks a different, real question a human staring at a
pile of several pending questions actually has: "if I answer THIS one first, does that make
several of the OTHERS unnecessary?" A question whose own per-question score is merely middling can
still be the single best one to ask FIRST if answering it is expected to let two or three other
pending questions self-resolve (skip being asked at all, e.g. via `question_queue.py`'s own
Tier-1 self-resolve path) -- pure per-question ranking has no way to express that, since it never
looks at relationships BETWEEN questions at all.

`dv_harness/session_question_sequencer.py` adds exactly that missing layer -- a SESSION-LEVEL
sequencer -- and nothing else. It never re-derives `rank_questions()`'s own scoring formula: every
per-question score used here is read straight out of that function's real return value (or a
caller-supplied ranking result it already computed), reused rather than recomputed.

Per this project's own established convention (`intake_question_priority.py`'s own module
docstring gives the identical reasoning for itself), this module does not import `question_queue.py`
either: pending-question data arrives as a generic list of dicts, so it can be exercised against
ANY caller's notion of a "pending question" without coupling to that module's schema. A question's
expectation that answering it would let other pending questions self-resolve is read from a
caller-declared field (`unlocks`/`downstream_unlocks`/`expected_unlocks` -- the first present of
the three) -- this module NEVER infers that a question would unlock another one from the two
questions' own content, topic, or wording; that would be exactly the invented relatedness
`intake_question_priority.build_question_batches()`'s own docstring already refuses to guess for
topic-based batching, applied here to a stronger, more consequential claim.

**The algorithm.** `build_unlock_graph()` turns every question's own declared unlock list into a
directed edge (question_id -> unlocked_question_id), validated against the real batch: a declared
target absent from the batch is never silently counted -- it is reported as an
`UNKNOWN_UNLOCK_TARGET` finding and excluded from the graph, and a question declaring itself as its
own unlock target is reported `SELF_UNLOCK_IGNORED` and likewise excluded. `compute_downstream_
reach()` walks that graph breadth-first from every question to the full set of OTHER questions
transitively reachable via declared unlock edges -- a real, finite computation even over a graph
containing a cycle (A unlocks B, B unlocks A): a visited-set BFS can never loop forever and a cycle
collapses to exactly the reachable set it really describes, never a double-counted or fabricated
larger one. `sequence_questions()` then orders the whole batch by `(downstream_reach_count DESC,
has_a_real_score, base_score DESC, question_id ASC)` -- downstream reach is the PRIMARY key (the
"unblock the maximum downstream work first" strategy), and the reused per-question score is the
tie-break among questions that would unlock an equal number of others. A question `rank_questions()`
itself could not score at all (a missing/invalid factor) is never silently dropped or given a
fabricated numeric score to sort by: it stays in the sequence, carrying its own real UNVERIFIABLE
reason, and is placed AFTER every equally-reach-count question that DOES carry a real score --
never ahead of one, and never silently treated as worthless either.

`sequence_session_queue()` is the full-pipeline convenience entry point: it runs
`intake_question_priority.analyze_pending_questions()` (gate -> rank -> batch, all reused verbatim,
none of it re-derived here) and then sequences the same to-ask subset using that call's own
already-computed ranking, so a DO_NOT_ASK question is never sequenced, exactly as it is never
ranked or batched by the reused pipeline.

**Deliberately bounded, and stated rather than implied closed.** It reads no file, writes no state,
files no question, answers no question, gates nothing (Tier/ask-vs-do-not-ask stays
`intake_question_priority.gate_pending_questions()`'s own job, reused verbatim), batches nothing
(that stays `build_question_batches()`'s own job), and invents no relationship between two
questions the caller did not itself declare. There is no `dv-harness` CLI verb and `cli.py`/
`gates.py` were not touched, per this batch's own file-safety scope -- the front door is
`python -m dv_harness.session_question_sequencer --pending-questions <file.json> [--max-batch-size
N] [--json]` (exit 0 every question gated/ranked/sequenced cleanly, 1 an unrankable question or
unlock-graph finding exists, 2 a usage error).

Proven by `dv_harness_tests/test_session_question_sequencer.py` (34 tests, `python -m pytest
dv_harness_tests/test_session_question_sequencer.py -q` -> `34 passed`, re-verified in this
integration pass): question-id assignment matching `intake_question_priority._question_id()`'s own
logic byte-for-byte; the unlock graph's `UNKNOWN_UNLOCK_TARGET`/`SELF_UNLOCK_IGNORED` negative
controls; a real cycle in the unlock graph proven to terminate and collapse to its true reachable
set rather than looping or double-counting; the ordering rule proven across every tie-break level
(reach count, has-a-score, score value, question_id); an unscoreable question proven to sort after
its equally-reach-count scored siblings rather than being dropped or given a fabricated score; and
the full `sequence_session_queue()` pipeline driven end to end, plus the real CLI subprocess across
all three documented exit codes.


<!-- S333: moved verbatim from CLAUDE.md original lines 20167-20269 (M4.6 CLAUDE Context Normalization) -->
## Answer-Inconsistency / Fatigue Detection: a Sequence Detector Over user_answer_validator.py + intake_baseline.py (2026-09-07)

Nothing in this repo looked at a whole intake SESSION's worth of answers together.
`user_answer_validator.py` checks exactly one raw answer against real RTL/build evidence
at a time and reports VALIDATED/PARTIALLY_VALIDATED/CONTRADICTED/UNVERIFIABLE -- a real,
per-answer signal, but with no notion of a SEQUENCE: an agent (or a tired human) could
contradict an earlier answer, or could start producing a run of CONTRADICTED/UNVERIFIABLE
answers as a session drags on, and nothing would ever notice the pattern across the
session. `intake_baseline.py` freezes the twelve intake facts a project commits to, on
demand, but nothing ever suggested WHEN a human should actually use that freeze as a
stop-and-review point. A repo-wide grep for `fatigue`/`inconsistency_detect`/
`answer_inconsistency`/`save_and_resume` before this module was written matched nothing.

`dv_harness/answer_inconsistency_fatigue_detection.py` is that sequence detector, and it
reuses both named modules unmodified rather than reinventing either half.

**Per-answer signal: `user_answer_validator.validate_answer()`, called once per answer,
never re-implemented.** `validate_session_answers()` walks a session's raw answers in
order (each a bare string, or a dict that may override `rtl_files`/`dut_facts_rtl`/
`manifest` per-answer -- a real intake session's evidence typically accumulates as more of
the project is discovered) and reads `AnswerValidation.claim_type`/`.target`/`.status`
straight off that module's own real result -- this is the "contradiction detection" reuse
point the task itself requires: `user_answer_validator.py`'s own CONTRADICTED status
(checked against real RTL/build evidence) IS the per-answer signal.

**Two independent, honestly-scoped signals, never collapsed into one.** (1)
SELF-CONTRADICTION -- a real, checkable logical conflict INDEPENDENT of whether any RTL/
build evidence was ever supplied: a design has exactly one "DUT top module", so two
answers in the same session both claiming to state it, with two different (case/
whitespace-normalized) module names, are a genuine contradiction regardless of whether
either name can currently be checked against real RTL. This is deliberately narrow -- an
ORDINARY `CLAIM_MODULE_EXISTENCE` claim ("module X exists") is NEVER treated as
contradicting a different module's existence claim, since a real design legitimately has
many modules; only the explicit "DUT top"/"top module" phrasing (a real, project-singular
fact) is compared across the session, proven by a dedicated negative-control test.
`detect_contradictions()` walks each singular field's answers in session order and
reports EVERY real disagreement against the most recently established value, so a session
that flip-flops A -> B -> A reports both the A-vs-B and the B-vs-A disagreement. (2)
DEGRADING-QUALITY (FATIGUE) TREND -- two independent, disclosed-heuristic checks over the
real CONTRADICTED/UNVERIFIABLE ("bad") signal already produced by `user_answer_validator.py`:
a real run of >= `FATIGUE_MIN_CONSECUTIVE_BAD` (3) consecutive bad answers at the tail of
the session, and a real first-half-vs-second-half bad-RATE increase of >=
`FATIGUE_RATE_INCREASE_THRESHOLD` (0.34, a declared heuristic, never a measured constant --
the same disclosed-heuristic convention `potential_spec_gap_detector.py`'s own
`SUBJECT_MATCH_THRESHOLD` already uses). Both thresholds sit one above this project's own
recurring "2 independent observations" floor (`REPEAT_FAILURE_MIN_OCCURRENCES`/
`ORGANIZATIONAL_MIN_CONFIRMATIONS`/`STABILITY_WINDOW_MIN_RUNS`), since a run of 2 bad
answers can be explained by one bad answer with a good neighbour on either side, while a
run of 3 cannot.

**INSUFFICIENT_DATA is never silently read as clean.** `analyze_session_fatigue()` folds
worst-wins: a real self-contradiction (`STATUS_CONTRADICTORY`) is reported regardless of
session length -- even two answers can genuinely contradict each other, and a real
contradiction is never diluted by "not enough data yet"; absent that, a real fatigue trend
(`STATUS_FATIGUE`); absent that, `STATUS_NO_PATTERN` only when the session was actually
long enough (>= `FATIGUE_MIN_CONSECUTIVE_BAD`) for a check to have genuinely run and found
nothing; a session shorter than that reports the honest, distinct `STATUS_INSUFFICIENT_DATA`
-- never a fabricated "checked and clean" result for a check that never actually ran. A
second required negative control proves an all-`UNVERIFIABLE` session (no rtl_files/
dut_facts_rtl/manifest supplied at all) still counts those answers as "bad" for the fatigue
trend rather than silently treating an evidence-absent answer as if it were validated.

**Save-and-resume checkpoint: `intake_baseline.freeze_intake_baseline()`, called
unmodified, only when there is a real reason to.** `recommend_checkpoint()` decides
whether a checkpoint should be OFFERED from a real `SessionFatigueReport` --
`recommended=True` only for `STATUS_CONTRADICTORY`/`STATUS_FATIGUE`, never for
`STATUS_INSUFFICIENT_DATA` or a clean session. `offer_save_and_resume_checkpoint()`
REFUSES (raises `ValueError`) to write anything when the report found no real reason and
the caller did not explicitly pass `force=True` -- proven directly, including a byte-level
proof (`ib.list_intake_freezes(tmp_path) == []`) that a refusal never writes a file. When
it does proceed, it composes the real fatigue rationale into `intake_baseline.py`'s own
existing `note` field and calls that module's real, unmodified freeze function --
`intake_baseline.py`'s own `frozen_by` requirement (an unattributable freeze is not a
freeze) is proven to still apply unweakened.

**What this module does not do.** It does not decide which of two contradicting answers is
correct -- that stays a human decision, the same ARBITRATION boundary this project's other
conflict-detecting modules already keep. It runs no build, job, gate, or approval, and it
does not itself decide which evidence is correct for a given answer -- that stays
`user_answer_validator.py`'s own job, reused unchanged. No `dv-harness` CLI verb was added
and `cli.py`/`gates.py`/`question_queue.py` were not touched, per this item's own scope --
the front door is `python -m dv_harness.answer_inconsistency_fatigue_detection analyze
--answers <file.json> [--manifest <file>] [--dut-facts-rtl <file>] [--json]` (exit 0
`STATUS_NO_PATTERN`, 1 `STATUS_CONTRADICTORY`/`STATUS_FATIGUE`, 2 `STATUS_INSUFFICIENT_DATA`
or a usage/refusal error).

Proven by `dv_harness_tests/test_answer_inconsistency_fatigue_detection.py` (32 tests, no
verible binary required anywhere -- every module-existence claim is exercised with no
rtl_files supplied at all, and every build-inclusion claim is checked against a plain,
hand-built `dut_facts_rtl` dict): the reuse of `validate_answer()` and its per-answer
override contract; both required negative controls (`STATUS_INSUFFICIENT_DATA` never
fabricated as clean/fatigue; an all-`UNVERIFIABLE` session's answers never silently
dropped from the bad-rate); every contradiction case including the flip-flop and the
different-ordinary-modules non-conflict; every fatigue-trend case including the
single-bad-answer-is-not-a-tail-run and flat-bad-rate-never-a-trend negative controls; the
worst-wins fold (contradiction outranks fatigue even when both are present); the full
checkpoint-offer lifecycle including the refuses-and-writes-nothing proof, the real
on-disk freeze round trip read back through `intake_baseline.list_intake_freezes()`, the
`force=True` override, and `intake_baseline.py`'s own `frozen_by` refusal still applying;
and the real CLI driven as a subprocess across all three documented exit codes plus two
malformed-input refusals. Re-verified in this integration pass: `python -m pytest
dv_harness_tests/test_answer_inconsistency_fatigue_detection.py -q` -> `32 passed`.


<!-- S334: moved verbatim from CLAUDE.md original lines 20270-20342 (M4.6 CLAUDE Context Normalization) -->
## Question Queue: Second-Human Review / Co-Sign of a Recorded Tier-3 Decision (2026-09-07)

`question_queue.py`'s own 3-tier protocol trusts a SINGLE human's recorded answer once
`current.source == HUMAN_DECISION_SOURCE` -- by design, and that rule is untouched by this
addition. Nothing in this module let a SECOND human reviewer record that they independently
reviewed and co-sign an already-recorded Tier-3 answer before some downstream consumer treats it
as trusted -- a real, distinct gap from the existing `control_plane.ControlPlane.add_cosign()`
mechanism, which co-signs a `gates.py` Tier-5 JUDGMENT_FIELDS gate-evidence field, never a
`question_queue` decision. `QuestionQueueStore.add_decision_cosign()` / `get_decision_cosigns()` /
`is_decision_cosigned()` close it, additively, in the same file.

**Never weakens or bypasses the existing sourcing rule -- enforced, not merely stated.**
`add_decision_cosign()` requires the LIVE decision for a `question_key` to already carry
`current.source == HUMAN_DECISION_SOURCE` (`CosignNotApplicableError` otherwise, including when
no live decision exists at all): co-signing a `tier2_auto_assumption` -- the harness's own
machine guess, per `_is_human_decision()`'s own docstring -- would be exactly the backdoor into
human-sourced trust this feature must refuse. `reviewer_id` must be a real, different person from
the original `current.decided_by` (`ValueError` otherwise) -- a co-sign is a second, independent
review, not the original decider re-affirming their own answer. A co-sign is purely additive
metadata appended to a new `entry["cosigns"]` list; `current`/`history` -- the fields
`classify_tier()`, `find_redundant_decision()`, `_is_human_decision()` and `_persist_decision()`
actually consult -- are never touched, so a HUMAN_DECISION_SOURCE decision stays fully trusted
with or without a co-sign, and a repeat Tier-3-triggering ask of the same `question_key` still
self-resolves at Tier 1 off the unchanged human answer either way.

**Staleness is keyed on the exact `answer` TEXT, not a synthetic Q-ID, deliberately.**
`make_question_id()` derives a Q-ID from `question_key` alone, so it is IDENTICAL across every
answer ever given to the same `question_key`, including two genuinely different answer texts --
using it as the co-sign's coverage key would have let a stale co-sign silently keep covering a
since-corrected answer. `is_decision_cosigned()` instead checks whether a co-sign's own recorded
`cosigns_answer` equals the LIVE decision's current `answer` text, the same exact-value discipline
`ControlPlane.add_cosign()` already applies to its own gate-evidence values. A decision genuinely
re-answered differently (the same `question_key`, a real correction) is reported honestly: the old
co-sign stays on `get_decision_cosigns()`'s list for the audit trail, but `is_decision_cosigned()`
reads False until a fresh co-sign covers the new answer. A `revoke_decision()` followed by a fresh
`answer_question()` starts a brand-new entry with no `cosigns` at all, so a co-sign never survives
that path either.

**Surfaced honestly, additively, on both existing report surfaces.** `decisions.md` gains one new
line per decision naming any live co-signer(s) of the CURRENT answer, or explicitly stating that
an existing co-sign does not cover the current answer (never silently omitted). The
`open_questions_decisions` Blackboard topic gains one new honest `cosigned` boolean per entry,
computed from the same in-hand `entry`/`current` data already being iterated (no extra disk read
per key) -- never inferred into `source`, so a reading stage that wants the stronger two-human
guarantee checks this field itself; every other field in that topic is unchanged.

**Deliberately bounded.** This is DETECTION/RECORDING only: `add_decision_cosign()` never
arbitrates, never overwrites `current`, and enforces no downstream policy of its own -- a caller
wanting to REQUIRE a co-sign before trusting a Tier-3 answer checks `is_decision_cosigned()`
itself; nothing in `classify_tier()`/`add_question()`/`answer_question()` was changed to require
one, by design, since making a co-sign mandatory by default would be exactly the "weakens the
existing rule" failure this item forbids. There is no `dv-harness` CLI verb and no `gates.py`/
`cli.py` edit for this addition -- the front door is the Python API on `QuestionQueueStore`
directly.

Proven by `dv_harness_tests/test_question_queue.py` (10 cosign-specific tests plus the full file,
re-verified in this integration pass: `python -m pytest dv_harness_tests/test_question_queue.py -q
-k cosign` -> `10 passed`; full file `python -m pytest dv_harness_tests/test_question_queue.py -q`
-> `157 passed`, zero failures -- the one pre-existing, unrelated `TestBuildSuggestThenConfirm
Options` failure this item's own real_evidence_summary disclosed at build time has since been
resolved by concurrent work in this same batch, confirmed by this integration pass's own fresh
re-run): the happy path (record, `is_decision_cosigned()` True, `get_decision_cosigns()` returns
it); the required negative control -- co-signing a real Tier-2 auto-assumption is refused with
`CosignNotApplicableError`, and `is_decision_cosigned()`/`get_decision_cosigns()` both stay
honestly empty afterward; no live decision at all is refused the same way; a blank `reviewer_id`
and the original decider co-signing their own answer are both refused with `ValueError`; `current`/
`history` are proven byte-identical before and after a co-sign, and a repeat Tier-3-triggering ask
is proven to still self-resolve at Tier 1 off the unchanged human answer regardless of a co-sign's
presence; a genuine re-answer with a different answer text is proven to make an existing co-sign go
stale (kept on the audit trail, but no longer "live-covering") while a revoke+reanswer is proven to
drop it entirely; and both `decisions.md` and the real `Blackboard` `open_questions_decisions` topic
are proven to report the co-sign, and the stale case, honestly.


<!-- S335: moved verbatim from CLAUDE.md original lines 20343-20417 (M4.6 CLAUDE Context Normalization) -->
## First-Time-User Onboarding: Detector + Adapted Question Rendering (2026-09-07)

No mechanism anywhere adapted question phrasing/explanation depth for a user new to this system --
a repo-wide grep for `first_time`/`onboarding`/`tutorial`/`new_user` before this module was written
matched nothing relevant (`gates.py`'s `protocol_onboarding_gate` is a different concept entirely:
protocol-*documentation* completeness, not user experience level). `dv_harness/
first_time_user_onboarding.py` closes it, reusing two already-real mechanisms rather than building
a third question-answering or question-rendering engine: `dv_harness/user_info.py`'s
`summarize_user_access()` (the real, already-tested per-project CLI_ACCESS/GUI_ACCESS-derived
session rollup) and `dv_harness/question_queue.py`'s `request_clarification()` (a real,
already-tested EXPANDED rendering of one persisted question -- a plain-English restatement of
`tier_reason` plus every option's own pre-researched rationale -- that today a human has to
explicitly ask for by name; see this file's own "Question Rephrasing / Clarification Loop" section
above).

**The detector, in order of evidence strength, never a single fixed rule and never a guess when
evidence is absent:** (1) DIRECT -- does this project's own `.dv-harness/question_queue/
decisions.json` already carry a LIVE decision whose `current.decided_by == user` AND
`current.source == HUMAN_DECISION_SOURCE`, i.e. has this user literally answered an intake question
here before? A Tier-2 `tier2_auto_assumption` entry is never counted -- it is this harness's own
guess, not evidence the user has answered anything (proven by a dedicated negative-control test).
(2) REAL ACCESS-HISTORY (`user_info.py`): when the direct check finds nothing, does this user's own
real, session-gap-inferred `session_count` for this project reach 2 (real evidence of at least one
earlier, gap-separated visit), or is the one session on record their first? (3) PROJECT-COUNT
HEURISTIC: only once NEITHER per-user source found anything at all -- count real sibling
directories next to the project root that carry their own `.dv-harness/` tree, a plain,
self-contained, filesystem-evidenced, deliberately-disclosed-as-weaker proxy for "has this
workspace set this harness up before". (4) A genuine READ FAILURE on BOTH stronger sources (a real
malformed `decisions.json` plus a real unreadable `events.jsonl`) is the required negative control:
honestly `UNKNOWN_INSUFFICIENT_EVIDENCE`, never silently defaulted toward either side. Six statuses
total (`RETURNING_ANSWERED_BEFORE` / `RETURNING_ACCESS_HISTORY` / `RETURNING_HEURISTIC` /
`FIRST_TIME_ACCESS_HISTORY` / `FIRST_TIME_HEURISTIC` / `UNKNOWN_INSUFFICIENT_EVIDENCE`), checked at
import to share no token with `dv_harness.models.Status`.

**Rendering policy is kept explicitly separate from the raw evidence-based `status`**
(`should_use_explanatory_rendering()`): true for both FIRST_TIME_* statuses AND for the honest
`UNKNOWN_INSUFFICIENT_EVIDENCE` status -- a deliberate, disclosed conservative default
(over-explaining costs a returning user a few extra lines; under-explaining costs a genuine
first-time user real confusion). The raw status is never fabricated toward FIRST_TIME to reach this
outcome. `render_question_for_user()` then either renders `build_escalation_package()`'s existing
9-field STANDARD view unchanged, or reuses `request_clarification(..., record=False)` verbatim for
the EXPLANATORY_FIRST_TIME mode -- `record=False` is load-bearing: this is an automatic,
policy-driven rendering choice, not a human explicitly asking for clarification, so it must never
mint a `clarifications.json` audit entry that falsely claims one did (proven directly by a dedicated
test). `render_questions_for_user()` wires the detector and the rendering mode together end to end
over every OPEN/ASSUMED question on file.

**Deliberately bounded, and stated rather than implied closed.** This module answers no question
itself (only a human, via `QuestionQueueStore.answer_question()`, does that), files no question,
runs no build/regression/LSF job, and touches no approval/governance mechanism -- there is
deliberately no stage gate. `question_queue.py` and `user_info.py` were both re-read fresh
immediately before this work and were NOT modified -- only their existing public/quasi-public
surface (`_load_decisions()`, `summarize_user_access()`, `request_clarification()`,
`build_escalation_package()`, `render_escalation_package_markdown()`) is reused. There is no
`dv-harness` CLI verb -- `cli.py`/`gates.py`/`dashboard.py` were left untouched per this batch's own
instruction -- the front door is the standalone `python -m dv_harness.first_time_user_onboarding
{detect|render|digest}`.

Proven by `dv_harness_tests/test_first_time_user_onboarding.py` (33 tests, re-verified in this
integration pass: `python -m pytest dv_harness_tests/test_first_time_user_onboarding.py -q` ->
`33 passed`) against real producers throughout: a real `QuestionQueueStore` driven through
`add_question()`/`answer_question()` for both Tier-2 (auto-assumed) and Tier-3 (human-answered)
fixtures, and real `StateStore(...).event()` CLI_ACCESS records for access-history fixtures --
never hand-written JSON standing in for what those real writers produce. The mandated negative
control drives a genuinely malformed `decisions.json` (a real `JSONDecodeError`) together with a
genuinely unreadable `events.jsonl` (a real directory in its place, raising a real
`PermissionError`/`IsADirectoryError` -- no mocking) to the honest `UNKNOWN_INSUFFICIENT_EVIDENCE`
status, never guessed toward either side; a companion test proves a single read failure on only one
source still falls through to the other real evidence source. Further negative controls: a Tier-2
auto-assumption's `decided_by` is proven never counted as a real human answer; a real prior decision
is proven to outrank weaker access-history/heuristic evidence; the sibling-project heuristic is
proven to exclude the root itself and non-`.dv-harness` directories and to report an honest zero on
a nonexistent parent. The full pre-existing `dv_harness_tests/test_question_queue.py` suite was
re-run and passes unchanged, confirming this addition disturbs neither reused module.


