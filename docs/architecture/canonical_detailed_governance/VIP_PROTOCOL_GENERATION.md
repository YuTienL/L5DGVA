# VIP / Protocol / Generation — Detailed Task-Scoped Governance

Moved out of CLAUDE.md during **M4.6 — CLAUDE Context Normalization** (canonical L5DGVA migration program). This document is registered in `dv_harness/governance_registry.json` as `id: VIP_PROTOCOL_GENERATION`, `load_policy: TASK_SCOPED`. Every section below is preserved **verbatim** from its original CLAUDE.md location (byte-for-byte, no rewriting) -- only its residency changed, never its content or authority. Each section header below records the exact original CLAUDE.md line range for traceability.

Covers: VIP/UVM generation, protocol/register/RTL evidence extraction, vPlan, coverage, AMBA/AXI fabric, DE command.txt/pattern/scenario architecture, checker/scoreboard/assertion placement, signoff/waiver, and design-intelligence extraction.

---

<!-- S034: moved verbatim from CLAUDE.md original lines 1008-1057 (M4.6 CLAUDE Context Normalization) -->
## UVM Structural Lint (2026-09-06)

Generated UVM is checked STRUCTURALLY, by a real parser, before it costs a compile. The gap this
closed was total, not partial: `dv_harness/verible_parser.py` parses RTL only (its extraction is
kModuleDeclaration/kPortDeclaration shaped), and `uvm_generator/bind_verification_lint.py` lints
elaboration/simulation REPORT TEXT. Grepping the repo for `uvm_component_utils`/`uvm_object_utils`
returned only generator EMIT sites — nothing ever read a generated `.sv` back. A generated
environment's first structural feedback was a VCS compile, i.e. exactly the expensive path spec
section 220 exists to run in front of.

`dv_harness/uvm_structural_lint.py` is that check. It reuses the REAL verible front end already in
this repo (`verible_parser.run_export_json()` plus that module's now-public tree-walk helpers) —
there is no second SystemVerilog parser in this package. Every call site's BOUNDARY comes from
verible's tree; only an already-isolated callee identifier path (`uvm_config_db#(T)::set`,
`phase.raise_objection`, `env.mon.ap.connect`) is matched as a string. Five checks, chosen because
a parse can DECIDE them without elaboration: factory registration (present, right family, naming
itself), UVM phase-method signatures (void function vs. task, exactly one `uvm_phase` argument),
config_db set/get key matching, TLM `*_port` connection completeness, and objection raise/drop
balance.

Where it runs: `create_environment()` — the one real CREATE ENVIRONMENT entry point — lints what it
just generated, returns the report as `structural_lint` and writes it to
`<out_dir>/uvm_structural_lint.json`. Non-blocking by default (a new check must not turn a
previously-working generation into a hard failure); a manifest may set `"strict_structural_lint":
true` to make ERROR findings raise `StructuralLintFailedError`, which
`tools/generate_protocol_uvm_environment.py` surfaces as exit 5. Ad hoc:
`dv-harness uvm-lint --env-dir <dir> [--json] [--fail-on-error]`.

**Deliberately bounded, and stated rather than implied closed.** It is a parser, not an
elaborator: generate/`ifdef conditions are not evaluated, parameters are not resolved, and a class
extending a base this parse never saw (a VIP class such as `svt_usb_agent`) is recorded
UNCLASSIFIED and NOT flagged — an unknown base cannot prove a missing registration. Both config_db
findings are WARNING, never ERROR, because an unmatched key is an absence this analysis cannot
prove (the missing half may live in VIP code, a project's own top test, or behind a run-time-built
key); ERROR is reserved for defects provable from the analysed sources alone. A `.svh` that does
not parse standalone is a WARNING (`bind_mechanism_generator.py` legitimately emits
top-module-scope `dv_uvm_hook.svh`), a `.sv` that does not is an ERROR. When verible cannot be run
the status is NOT_AVAILABLE with a real reason — never PASS. The other seven concerns section 220
lists (analysis-port semantics, sequencer/driver linkage, virtual-interface binding, package/import
dependencies, duplicate definitions, duplicate active drivers, illegal hierarchy assumptions) are
NOT implemented; several need elaboration-time truth this parse does not have.

Proven by `dv_harness_tests/test_uvm_structural_lint.py`: a clean synthetic environment reports
zero findings, every rule is then driven by MUTATING that same clean source one defect at a time
(so each assertion proves the lint caught that specific injected defect), and the real
`examples/generated_pcie_uvm_env/` and `examples/generated_usb_real_evidence_v12/` — environments
this project's own generator really produced — report no ERROR findings, because a lint that fires
on genuine generator output would be unusable no matter how many synthetic defects it catches.



<!-- S036: moved verbatim from CLAUDE.md original lines 1120-1176 (M4.6 CLAUDE Context Normalization) -->
## Golden Scenario / Reference Capsule (2026-09-06)

A "golden scenario" is a persisted claim that test T, at seed S, in configuration C, was verified
PASS against a specific commit — and spec section 225's own rule is what makes it worth
persisting: "Golden does not mean permanent. Relevant RTL/spec/tool/config changes can make a
capsule STALE." Grepping for `golden_scenario`/`GoldenScenario`/`reference capsule` matched nothing
executable. Two similarly-shaped mechanisms already existed and are deliberately NOT what this is:
`golden_flow_readiness.py` (section 47's readiness MATRIX over the harness's own twenty workflow
STAGES — no per-test record, no recorded SHA, no staleness concept), and
`system_regression_plan.CAT_KNOWN_GOOD_SUBSYSTEM_TESTS` (SYS-33's per-SUBSYSTEM planning category,
recomputed from the subsystem registry's qualification_state on every call, never persisted and
never asked whether the RTL moved since).

`dv_harness/golden_scenario.py` is the capsule store, and it reuses rather than reinvents on both
sides:
- BACKING STORE: one new `golden_scenarios` table in the REAL
  `evidence_db.EvidenceStore`, alongside `jobs`/`normalized_evidence`, keyed on `capsule_id` with
  the same idempotent-upsert-by-natural-key convention every other table there uses — not a second
  evidence format. `record_golden_scenario()` REFUSES a capsule whose `evidence_id` is not an
  existing `normalized_evidence` row (the real `vip_distill.py` envelope), whose recorded verdict is
  not a real PASS, or whose `test_name` disagrees with that row's own `pattern`. `job_id`/`protocol`
  are filled in from that row and `verified_sha` from the real `jobs.git_sha` of the job the
  evidence belongs to, so section 225's "DUT/TB SHA" is read off real evidence rather than typed.
- FRESHNESS: computed, never stored — a stored flag is wrong the instant someone commits.
  `evaluate_freshness()` runs the REAL `change_impact.changed_files()` (a real
  `git diff --name-only <verified_sha>..HEAD`) and the REAL `change_impact.classify_risk()`
  HIGH/MEDIUM/LOW path model that the regression-selection chain already uses, so "did the design
  move" has ONE answer in this codebase. HIGH (design RTL) or MEDIUM (testbench/sequence/
  command.txt/config) inside the capsule's declared `watched_paths` ⇒ STALE naming the files; LOW
  (docs, `.dv-harness`/`.claude` bookkeeping) does not. A recorded VIP/tool version that no longer
  matches a caller-supplied current one ⇒ STALE with no git change at all.

`dv-harness golden-scenario record|list|status` and `python -m dv_harness.golden_scenario` share one
implementation (`execute_verb`, the same convention `power-intent` uses). Exit 0 recorded / all
FRESH, 1 at least one STALE, 2 UNKNOWN or nothing recorded.

**Deliberately bounded, and stated rather than implied closed.** (1) "We could not check" is
UNKNOWN, never FRESH: no git, an unresolvable recorded SHA, a failed diff, or no recorded SHA all
report UNKNOWN with the real reason. (2) An empty `watched_paths` widens the scope to the WHOLE
repo rather than emptying it (`scope: WHOLE_REPO_NO_WATCHED_PATHS_DECLARED`) — this module's
failure mode is "calls a still-good capsule stale", never the reverse. (3) It DECIDES nothing: it
runs no test, submits no job, and there is deliberately no stage gate — a gate that passed on a
capsule nobody re-ran would be worse than none. FRESH is an input to a human's reuse decision.
(4) An evidence.duckdb predating this table is opened read-only (which skips schema DDL by design),
so it reports NOT_AVAILABLE rather than crashing. (5) The capsule is recorded by a deliberate
`record` call; nothing auto-mints capsules from passing runs, because "which passes are worth
keeping as golden" is a judgment this module does not make.

Proven by `dv_harness_tests/test_golden_scenario.py` (21 tests) against a REAL throwaway git
repository with real commits, a REAL DuckDB EvidenceStore, a REAL `vip_distill.distill_sim_log()`
envelope for a synthetic sim.log in this project's own FINAL CHECK epilogue format, and a REAL
`JobState` row: the central test records a capsule against a real PASS, asserts FRESH, then makes a
REAL RTL commit and asserts the SAME capsule is STALE naming that file at HIGH risk — with the
stored row untouched, because freshness is derived. Both CLI entry points are driven as real
subprocesses and their exit codes asserted.



<!-- S067: moved verbatim from CLAUDE.md original lines 3932-4035 (M4.6 CLAUDE Context Normalization) -->
## Canonical Requirement Contract + Status Vocabulary (2026-09-06, SPEC-3)

Spec section 184's CANONICAL REQUIREMENT CONTRACT is now a real schema, and its
five-value status vocabulary (COMPLETE / PARTIAL / AMBIGUOUS / CONTRADICTORY /
UNKNOWN) is enforced against the requirement's own content rather than trusted
from the field. The gap was total: `grep -rn "Canonical Requirement Contract"`
matched NOTHING repo-wide, and no module or schema named
`requirement_contract`/`RequirementContract` existed.

The closest pre-existing mechanism,
`tools/verification_flow/spec_to_vplan_requirement_quality_gate.py`, checks FIVE
fields (`spec_ref`/`feature`/`expected_behavior`/`verification_method`/
`coverage_goal`) plus an ambiguity rule and an UNSUPPORTED_BY_DUT rule. Section
184 names FIFTEEN, and the eight it adds -- Protocol, Configuration,
Precondition, Observability, Checker, Coverage Intent, Priority, Criticality --
are exactly the ones a downstream generator needs and would otherwise re-derive
from prose. That gate had no status vocabulary at all, so "this requirement is
CONTRADICTORY and a human must arbitrate" was not expressible: a requirement was
implicitly either complete or a gate failure.

`dv_harness/requirement_contract.py` + `dv_harness/schemas/
requirement_contract.schema.json` are the contract, following `env_manifest.py`'s
schema-versioning convention (module-level `SCHEMA_VERSION`, sibling schema file,
fail-closed `RequirementContractValidationError` rather than a False/None
return). Vocabularies are IMPORTED, not re-typed: `priority` is
`memory.CORNER_CASE_RISK_TIERS` (P0..P3), `confidence` is
`inference.CONFIDENCE_LEVELS` plus UNKNOWN. `criticality`
(BLOCKER/MAJOR/MINOR/UNKNOWN) is genuinely new -- nothing here had a
consequence-of-failure axis -- and is deliberately a DIFFERENT axis from
priority's scheduling one.

**What makes it more than a shape check.** `status` is a field an agent fills in
about its own extraction work, so by the Evidence Truth Rule it is a judgment,
not evidence. `derive_status()` RE-DERIVES it from the record's own content
(worst-first: unresolved contradiction -> unresolved ambiguity -> untrusted
confidence or nothing verifiable -> unresolved field -> COMPLETE), and
`analyze_requirement_contract()` rejects a status the content does not support.
Two rules carry the weight:
- `STATUS_OVERCLAIMED` -- COMPLETE declared while a field is still absent,
  empty, or a placeholder (`UNKNOWN`/`TBD`/`N/A`/`?`/lowercase `none`). Uppercase
  `NONE` is RESOLVED, but only for `configuration`/`precondition`, where "there
  genuinely is no dependency" is a decision rather than an evasion.
- `UNRESOLVED_BLOCKER_HIDDEN` -- an ambiguity or contradiction the record FILED
  ITSELF, stepped over by a status that is neither AMBIGUOUS nor CONTRADICTORY.
  Section 32's "unresolved requirements remain visible as gaps" as code. Filing a
  question does NOT close an ambiguity; only explicit `resolved: true` alongside
  real resolution text does.
Declaring a status WEAKER than the content supports stays legal (honest
conservatism) and is reported as a WARNING, never an error.
`downstream_consumable()` is the decision the contract exists to make: only
COMPLETE with zero ERROR findings may feed a generator.

**ARBITRATION IS NOT HERE.** A CONTRADICTORY requirement STOPS at CONTRADICTORY.
The contract requires a contradiction to name at least TWO conflicting sources
and refuses to let the requirement feed a generator; nothing picks which source
wins. Same boundary `system_resource_inventory`'s driver-conflict DETECTION
keeps against ownership ARBITRATION, for the same reason.

Where it runs: `spec_to_vplan_requirement_quality_gate.py` is EXTENDED, not
replaced. A record declaring `contract_schema_version` gets the contract check
(new exit 6 `REQUIREMENT_CONTRACT_VIOLATION`); every record without it stays on
the original code path with its original exit codes 2/3/4/5 byte-identical, so a
project that has not migrated is never retroactively failed. A contract record is
validated by the new layer INSTEAD of the old five-field one, because the two
shapes spell the same content differently (`req_id`/`expected_behavior` vs
`requirement_id`/`expected_result`) and the old layer would fail it for fields the
contract deliberately renamed. The new layer is FAIL-CLOSED on its own
unavailability (exit 7) -- unlike the opportunistic cross-checks in the
`system_level_*` gates, because the record EXPLICITLY asked to be held to the
richer contract and silently skipping would turn a stricter declaration into a
weaker gate. Ad hoc: `dv-harness requirement-contract --requirements <file>
[--json] [--fail-on-error]`, or `python -m dv_harness.requirement_contract`
(0 clean, 1 ERROR findings, 2 NOT_AVAILABLE -- nothing in the contract shape is
never a clean PASS).

**Deliberately bounded, and stated rather than implied closed.** (1) It reads a
requirement RECORD. It does not parse specifications, does not extract
requirements from prose, and does not check a requirement against RTL, a register
map, or a simulation -- it answers "is this requirement internally coherent,
honestly statused, and safe to generate from". Section 184's spec-parser /
requirement-normalizer / register-parser responsibilities are NOT implemented
here. (2) The contract is not yet PRODUCED by anything: no generator in this repo
emits contract-shaped records, so the gate layer is dormant until a project
supplies them. That is deliberate -- minting fabricated contract records to make
the mechanism "have fired" is exactly what the registry-entry disclosure above
refuses. (3) `gates.py`'s `JUDGMENT_FIELDS` was NOT extended with the contract's
`status`: that opt-in DV-review-cosign mechanism is off by default and three
concurrent close-passes were editing `gates.py`, so it is left for a pass that
owns that file.

Proven by `dv_harness_tests/test_requirement_contract.py` (96 tests): ONE clean,
fully-populated synthetic requirement is asserted COMPLETE and finding-free, then
every rule is driven by MUTATING that same clean record ONE defect at a time, so
each assertion proves that rule caught that specific injected defect. All five
status values are each derived from real content and asserted self-consistent and
correctly (non-)consumable; every one of the fifteen fields is deleted in turn and
asserted rejected by the schema AND named by the analysis. The gate half is driven
as a REAL subprocess over REAL files -- including the headline case: a record that
would have PASSED the pre-2026-09-06 gate (it carries all five old fields) is
REJECTED for claiming COMPLETE with `checker: "TBD"` -- plus the older shape's
four original exit codes, a mixed document, and the fail-closed
validator-unavailable path.



<!-- S069: moved verbatim from CLAUDE.md original lines 4113-4185 (M4.6 CLAUDE Context Normalization) -->
## VIP API Card / Unprovable-API BLOCKED (2026-09-06)

Spec section 187's VIP API flow ends with a stop condition -- "If API cannot be proven:
UNKNOWN / BLOCKED" -- and before this it existed in this repo ONLY as prose instruction to an
LLM. `.claude/skills/CORE/vip-scenario-branch/SKILL.md` says 禁止憑猜測 invent VIP
API/class/sequence and lists the same example -> manual -> source -> class-reference ladder;
`pcie-environment-builder` repeats it. Grepping the tree for `VIPApiCard`, `vip_api_card`,
`validate_vip_api_usage` or `UNPROVABLE` matched NOTHING executable: no artifact, and no code
path anywhere rejected or even flagged a VIP API call the harness could not prove exists. A
generated sequence citing a hallucinated `svt_usb_agent.reconfigur()` left the generator
byte-identically to one citing the real method, and the first thing that would notice was a
VCS compile.

`dv_harness/vip_api_card.py` is that check, and it reuses `vip_symbol_index.py` rather than
rebuilding it -- there is no second SystemVerilog scanner here. That module already indexes a
VIP source tree into real class/method DECLARATIONS with a real `file:line` each, but by its
own docstring's insistence it is a NAVIGATION aid: `find_symbol()` answers "where do I read
about this name", and nothing had ever asked it the validation question. `index_source_text()`
is imported for both halves: reading the VIP index, and discovering the classes the validated
sources declare THEMSELVES (so a generated `usb_base_vseq` under a `usb_`-prefixed VIP index is
never mistaken for a fabricated VIP class).

A **VIPApiCard** is one record per VIP API citation: which VIP class/method was cited, where
the generated code cites it, the real `file:line` the index resolved it to, which class in the
inheritance chain actually declares it, and a status. Four statuses, and **BLOCKED is narrow on
purpose**: it requires the receiver's declared type to be a class the index really contains,
the member to be absent from that class's entire indexed inheritance chain, every non-indexed
base in that chain to be a declared base-library class (`uvm_*`) so the world is CLOSED, and
the member not to be one of the documented SystemVerilog/UVM base-library methods. A fabricated
VIP CLASS name (in the index's own naming scope, absent from it, not declared locally) is
likewise BLOCKED. A chain that leaves the index into an unknown non-library base yields
UNPROVABLE -- section 187's "UNKNOWN", which is not a pass and is never silently dropped.
The VIP naming scope is DERIVED from the real index (`derive_vip_scope_prefixes()`), never
hardcoded: nothing in this module knows the string "svt".

Where it runs: `create_environment()` -- the one real CREATE ENVIRONMENT entry point -- validates
what it just generated whenever the manifest names `vip_symbol_index: <path>`, returns the report
as `vip_api_validation` and writes the artifact to `<out_dir>/vip_api_cards.json`. Non-blocking by
default (same reason `uvm_structural_lint` is); `"strict_vip_api": true` makes BLOCKED citations
raise `VipApiUnprovableError`. Ad hoc: `dv-harness vip-api-check --source <dir> --index <index.json>`
or `python -m dv_harness.vip_api_card` (exit 0 PROVEN, 1 BLOCKED, 2 NOT_AVAILABLE, 3 UNPROVABLE --
the last non-fatal unless `--strict-unprovable`).

**Deliberately bounded, and stated rather than implied closed.** (1) PROPERTY access
(`cfg.some_field`) is NOT decided: `vip_symbol_index._FIELD_RE` indexes only a restricted set of
data types, so a field's absence from the index does not prove the field does not exist. Only
method CALLS, class TYPE citations and `Class::` scope citations are judged, and a `Class::MEMBER`
citation decides the CLASS half only (the index models no enum constants, parameters or typedefs).
(2) A call whose receiver type this scan cannot resolve mints no card at all -- unresolved is our
ignorance, not the generator's error. (3) The single false-positive risk is an incomplete
`BASE_LIBRARY_METHODS` allowlist; that list can only DOWNGRADE a finding, so an omission produces a
false BLOCKED and never a false PROVEN, which is why the generation-path wiring is non-blocking
unless opted in. (4) The index must be an index of the VIP the environment actually binds --
validating against some other VIP's index correctly reports every real call as unprovable, which is
why the wiring is an explicit manifest opt-in and not a discovered default. (5) It is a
declaration-level line scan, the same graceful-degradation technique and for the same reason
`vip_symbol_index` uses one; a construct it cannot understand contributes no citation, never a guess.
(6) It DECIDES nothing beyond reporting: no build, no job, no approval, no stage gate.

Proven by `dv_harness_tests/test_vip_api_card.py` (26 tests) against a REAL index built by the REAL
indexer over `examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv` (this repo's existing
synthetic VIP source) and `dv_harness_tests/fixtures/vip_api/demo_env_seq.sv`, a clean generated
sequence whose every citation is really declared there: the clean baseline is all-PROVEN with each
card's `resolved_line` asserted to be a line that really declares it, then every rule is driven by
MUTATING that same clean source one fabrication at a time. The false-positive directions are tested
separately -- a locally-declared class, a base-library method, an unresolvable receiver, fabricated
names inside comments/strings, an open inheritance chain (UNPROVABLE, not BLOCKED, with the SAME
index blocking the same fabrication on a closed-chain class), and `examples/generated_pcie_uvm_env/`
(an environment this project's own generator really produced) reporting zero findings against an
unrelated VIP's index. The real `create_environment()` dispatch and both real CLI entry points are
driven end to end, including the `strict_vip_api` raise.



<!-- S073: moved verbatim from CLAUDE.md original lines 4429-4518 (M4.6 CLAUDE Context Normalization) -->
## Waiver Ledger Is the Source of Truth for the Waiver Gates (2026-09-06, TH-7)

Spec section 237 (WAIVER EXPIRATION / REVALIDATION) names a waiver record and a five-value status
vocabulary (VALID / REVALIDATION_REQUIRED / EXPIRED / REVOKED / UNKNOWN), and rules that "relevant
Spec/RTL/config/tool changes can invalidate or require revalidation of a waiver". Both halves of
that existed here and were not connected, which `dv_harness/waiver_store.py`'s own docstring and
`dashboard.py`'s own Waiver Authoring note both disclosed in as many words: "there is no fixed
harness code path today that reads a waivers store from a known location before invoking a gate",
and "this store is not wired into any gate script's own `--waivers` input today".

The consequence was that a waiver was SELF-ATTESTED end to end. `gates.run_gate()` assembled every
waiver gate's payload from the agent's own fenced ```dv-harness-evidence:<gate_id>``` block, so the
same agent wrote both the waiver and the evidence that the waiver was still valid — and an expired
waiver did not get re-flagged, it simply stopped being mentioned. The store, meanwhile, had a
4-field schema (`gate_id`/`item_id`/`approved`/`evidence`) that shared not one field name with what
the three gates read and carried no status concept at all.

**The three real gates now read the ledger.** `waiver_scope_consistency_gate`,
`waiver_revision_freshness_gate` and `waiver_revalidation_gate` import `dv_harness.waiver_store`
through the DV_HARNESS_PACKAGE_ROOT env var `run_gate()` already supplied for exactly this, plus a
new `DV_HARNESS_PROJECT_ROOT` (`gates._gate_env()`) naming which project they are judging. That is
harness-supplied with the same trust property as a `ContextFlag` — never read from agent text, so a
gate cannot be pointed at a fabricated root to dodge it. It is an env var rather than a
`ContextFlag` because two of the three scripts take a single whole-payload flag and converting them
to the multi-flag form would change the evidence-block shape every existing project's prompt emits.

Whenever `.dv-harness/waivers/waivers.json` EXISTS it is authoritative: the records evaluated are
the ledger's, projected into each script's own field names by the single `_projection()` that knows
how the three spell the same waiver, and an agent-cited `waiver_id` the ledger has no record of
FAILs `WAIVER_NOT_IN_STORE` — nobody approved it, so it exempts nothing. A ledger waiver is
re-evaluated on EVERY run, which is the whole point: when it expires the requirement it was waiving
is re-flagged whether or not anyone mentions it. The three gates' own pre-existing checks
(`INCOMPLETE_WAIVER_SCOPE`, `WAIVER_ATTEMPTS_TO_HIDE_ACTIVE_FAILURE`, `WAIVER_APPLIED_OUTSIDE_SCOPE`,
`WAIVER_REVISION_STALE`, `STALE_WAIVER_AFTER_REVISION_CHANGE`) are untouched and still run over
those records — the store supplies the records, it does not replace the checks.

**`status` is DERIVED on every read and REFUSED as a stored field**, the same reason
`golden_scenario.evaluate_freshness()` computes freshness rather than storing it: a stored status is
wrong the instant the expiry passes or the revision moves. `derive_status()` decides worst-first
(REVOKED → UNKNOWN → EXPIRED → REVALIDATION_REQUIRED → VALID), so a human's revocation outranks the
clock. EXPIRED and REVALIDATION_REQUIRED map onto `waiver_revalidation_gate.py`'s OWN pre-existing
reason tokens rather than synonyms for them.

**"We could not check" is never VALID.** A record missing section 237's fields is UNKNOWN naming
them; so is one declaring neither an expiry nor a revalidation trigger (nothing about it can go
stale, so nothing can show it is still good), and so is an unparseable timestamp. The original
4-field record the dashboard form used to write is still accepted and never dropped — it is real
human intent — but it reads UNKNOWN for exactly that reason, and the form now offers the section 237
fields so a human can record a checkable waiver.

**A trigger nothing measures cannot be declared.** `SUPPORTED_TRIGGER_KEYS` is
`spec_revision`/`rtl_hash`/`revision` and `record_waiver()` refuses anything else by name, because
`GATE_STATUS_CONTEXT` records which gate really measures what — expiry only in
`waiver_revalidation_gate` (the only one `run_gate()` hands a harness-clock `--now` ContextFlag),
spec_revision/rtl_hash only in `waiver_revision_freshness_gate`. All three run in the same
REQUIREMENTS_TRACEABILITY stage, so between them every declared trigger and the expiry really are
checked; `assert_trigger_coverage()` runs at import so adding a trigger key without a gate that
measures it fails a test rather than producing a waiver that reads VALID forever. A gate is never
handed a fact it did not observe, so it can never decide a status on one.

**Deliberately bounded, and stated rather than implied closed.** (1) A project with NO ledger keeps
the original agent-attested behaviour and the original exit codes byte-identically — adopting the
store is a project's decision and an un-migrated project is never retroactively failed. This
repository itself has never recorded a waiver, asserted by a test so that adopting one here cannot
silently change the pre-existing gate test's meaning. (2) It ARBITRATES nothing: it revokes no
waiver, revalidates none, grants no approval and picks no winner. Recording and revoking are human
acts (`revoke_waiver()` requires both a named human and a reason, the discipline
`loop_budget.reset()` applies to clearing a spend). (3) The other three waiver-consuming gates
(`coverage_hole_regeneration_gate`, `coverage_hole_to_test_generation_gate`,
`sequence_coverage_closure_gate`) are NOT wired: they read coverage-hole and sequence payloads whose
shapes are a different domain, and section 237 is about the waiver record itself. (4) There is no
`dv-harness` CLI verb — `cli.py` was being modified by concurrent work in the same session — so the
front door is `python -m dv_harness.waiver_store statuses|list|status` (exit 0 clear, 1 a waiver is
not VALID, 2 no ledger) plus the dashboard form.

Proven by `dv_harness_tests/test_waiver_store_gate_wiring.py` (41 tests), which drives the REAL
`gates.evaluate_stage_evidence()` over the REAL shipped `STAGE_GATES["REQUIREMENTS_TRACEABILITY"]`
entries, running the REAL gate scripts as subprocesses against a REAL ledger on disk — nothing
mocked. The central test records a waiver that has EXPIRED and has the agent declare NO waivers at
all (exactly what a self-attested flow produces once a waiver becomes inconvenient); the stage FAILs
`WAIVER_EXPIRED` naming that waiver, and the ledger names the requirement that is no longer waived.
Its negative control is the identical ledger, agent text and gates with only the expiry moved,
reaching a real PASS. The rest carry the same shape: a fabricated citation is refused while citing a
real ledger waiver is not, a revoked waiver is refused, a moved rtl_hash requires revalidation and
real revalidation evidence clears it, each of the five statuses is derived from real content, an
un-migrated project's original PASS and `WAIVER_REVISION_STALE` paths are asserted unchanged, and a
byte-level snapshot proves reading writes nothing. Nothing in it runs a build, a regression or an
LSF submission, and no human-approval gate is touched.



<!-- S074: moved verbatim from CLAUDE.md original lines 4519-4647 (M4.6 CLAUDE Context Normalization) -->
## Signoff Freeze / Baseline + Post-Freeze Invalidation (2026-09-06, TH-8)

Spec section 238 asks for two things at signoff, and `dv_harness/signoff_export.py` had
neither. It packaged ARTIFACTS -- eleven candidate files copied into a bundle, gate-aware
since 2026-09-04 -- but carried none of section 238's fifteen named BASELINE fields (spec
version, requirement/vPlan version, DUT SHA, TB SHA, agent/skill versions, VIP/tool
versions, schema/policy versions, configuration, test list, coverage databases, assertion
status, waivers, evidence hashes/references, dashboard snapshot, reproducibility capsules),
and nothing anywhere implemented its closing rule that "post-freeze material changes trigger
impact analysis and invalidate/revalidate affected signoff evidence". Re-verified by direct
search before building: `grep -rn "freeze|frozen" --include=*.py dv_harness/ tools/` matched
only `frozenset`. Worse, `compute_bundle_hash()` hashes `artifact:present:bundled_path` --
artifact PRESENCE, never CONTENT -- so a bundled file could be replaced wholesale without
moving the bundle hash.

Three additions, all inside `signoff_export.py`; there is no second exporter and no second
freeze store.

**`capture_baseline()` derives all fifteen fields from REAL producers, or says why not.**
Nothing is a typed-in version string. `dut_sha` is `connectivity_check.compute_rtl_fingerprint()`
over the project's own declared `rtl_sources` -- the SAME content fingerprint the standing
`just connectivity-check` recipe uses to decide the RTL moved, never a git SHA standing in for
RTL content (a git SHA moves when a README moves). `tb_sha` is the content of whatever
`_find_tb_source_dir()` -- the bundle's own discovery function -- located, so the frozen TB SHA
and the bundled `tb_source/` can never describe different trees. `waivers` is
`waiver_store.status_report()`'s DERIVED per-waiver status (TH-7's ledger), which is what makes
a waiver EXPIRING after signoff a detectable post-freeze change. `reproducibility_capsules` is
`golden_scenario.load_golden_scenarios()`; `evidence_hashes` is the `normalized_evidence`
`evidence_id` set, i.e. `vip_distill`'s own deterministic content hashes; `assertion_status` is
the real `assertion_failure`/`uvm_fatal_count` on each recorded `lsf_client.JobState`;
`vip_tool_versions` is `env.manifest.json`'s `vip_config.vip_release` with its OWN status/reason
carried verbatim; `agent_skill_versions` and `schema_policy_versions` are content identities over
the real `.claude/skills` + `.claude/agents` trees and `dv_harness/schemas` + the policy JSONs,
resolved through `harness_deploy.collect_local_files()`. Every aggregate goes through
`source_identity.aggregate_source_id()` -- the same primitive `harness_deploy` and
`server_sync_identity_gate` already use; there is no second aggregation rule here.
`SECTION_238_FIELDS` and `BASELINE_CAPTURES` are held equal in BOTH directions by
`assert_baseline_covers_section_238()` at import, so a field can never be silently dropped from a
freeze record and a sixteenth can never be quietly added.

**Two fields are honestly NOT_AVAILABLE by construction, and say why.** `spec_version` has no
artifact producer in this codebase at all -- the only `spec_revision` anywhere is agent-attested
evidence-block text in `prompts.py`, and freezing an agent's own claim as a baseline FACT is what
the Evidence Truth Rule forbids; a human may declare one, which is recorded as `attested: true`,
`machine_verified: false`. `dashboard_snapshot` has no snapshot artifact: `dashboard.py` renders
live from state.json, the blackboard topics, the coverage summary and the LSF job records on every
request, and every one of those is already frozen by another field, so re-deriving a "snapshot"
would present a rendering of already-frozen inputs as independent evidence.

**`evaluate_freeze_invalidation()` is the check, and it is three independent comparisons,
worst-wins.** (1) All fifteen fields are re-derived NOW by the same capture functions and compared
by digest; a CAPTURED field that moved, or that can no longer be captured at all, INVALIDATES,
while a field that was NOT_AVAILABLE at freeze and is CAPTURED now is INDETERMINATE -- evidence
appearing after a signoff is a real change but not proof the frozen evidence went wrong.
(2) Post-freeze impact analysis is the REAL `change_impact.changed_files()` +
`classify_risk()` over the freeze's recorded git HEAD, run exactly as
`golden_scenario.evaluate_freshness()` runs it, so "did the design move" has ONE answer in this
codebase: HIGH/MEDIUM changed files INVALIDATE and are named with their risk, LOW (docs,
`.dv-harness`/`.claude` bookkeeping) do not -- which matters because a signoff export writes into
`.dv-harness/` itself. (3) The frozen bundle's `manifest.json` is re-read and
`compute_bundle_hash()` recomputed INDEPENDENTLY; a bundle that moved INVALIDATES, one that is
gone is INDETERMINATE. The verdict is DERIVED on every read and never stored -- a stored verdict
is wrong the instant someone commits, the same reason `golden_scenario` computes freshness and
`waiver_store` derives status. "We could not check" is never VALID: no git, no recorded HEAD, an
unavailable diff or a missing bundle each produce a named finding and UNKNOWN.

**The bundle gained a content half without breaking the gate that reads it.** Each manifest entry
now carries `content_sha256` (a file's sha256, a directory's aggregate). It is deliberately a
FOURTH key and NOT material for `compute_bundle_hash()`: that function's contract is the artifact
list, `signoff_bundle_completeness_gate.py` recomputes it independently off `manifest.json`, and
widening it would change every previously-computed bundle_hash and break that gate for existing
bundles.

**Where it fires.** `collect_signoff_bundle(freeze=None)` -- the default -- freezes exactly when
the bundle is `SIGNOFF_GATE_VERIFIED`, i.e. when the 9 real `STAGE_GATES["SIGNOFF"]` gates really
passed. That makes `engine._export_signoff_bundle()`, the one production caller that produces a
gate-verified bundle, the real WIRED producer of section 238's "at signoff, capture a frozen
reproducible baseline" -- with no engine change and no second entry point. A
`PRE_SIGNOFF_GATE_INPUT` bundle is deliberately NOT frozen: freezing a baseline the gates never
accepted would mint exactly the indistinguishable-from-verified artifact `bundle_kind` exists to
prevent. Records land in `.dv-harness/signoff/freezes/<freeze_id>.json` (the project's own state
directory, never a new parallel state root, and never only inside a bundle that can be deleted),
with a copy in the bundle and one real `SIGNOFF_BASELINE_FROZEN` event in the same
`.dv-harness/events.jsonl` `dv-harness audit` already reads.

**It RECORDS and REPORTS; it arbitrates and authorizes nothing.** No stage runs, no gate is
invoked, no build/regression/LSF submission is started, and there is deliberately no stage gate --
a gate that passed because a freeze had not been recorded, or failed because one had, would be
worse than none. REVALIDATION is a human act: an INVALIDATED report names exactly what diverged
and what would have to be revalidated, and revalidates nothing itself. `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()` and the PR-only main/master governance are
untouched and unreferenced, asserted against the module's own source by a test. A standalone
freeze RECOMPUTES a bundle's hash off its manifest rather than trusting the value written in the
file.

Front door: `python -m dv_harness.signoff_export fields|baseline|freeze|list|status`
(`execute_verb()`, the same convention `power-intent`/`golden-scenario`/`waiver-store` use);
exit 0 clear, 1 a freeze is INVALIDATED, 2 nothing to report or a refusal. `freeze` REQUIRES
`--frozen-by`: an unattributable baseline is not a signoff baseline.

Proven by `dv_harness_tests/test_signoff_freeze_baseline.py`, whose fixtures are REAL throwaway
git repositories with real commits, a real RTL tree the REAL `compute_rtl_fingerprint()`
fingerprints, a real waiver ledger written through the REAL `waiver_store.record_waiver()`, real
job records, and real bundles produced by the REAL `collect_signoff_bundle()` -- nothing mocked.
The central test freezes a bundle, asserts VALID, then changes the fixture's RTL and commits it,
and asserts the SAME frozen record now reads INVALIDATED naming `dut_sha` AND
`rtl/usb3_link_ctrl.v` at its real HIGH risk, with the record byte-identical on disk. The negative
controls are what give it detection power: an unchanged fixture is VALID, a committed
documentation-only change does NOT invalidate, revoking a waiver invalidates with no git change at
all, evidence that disappears invalidates while evidence that APPEARS is UNKNOWN rather than
INVALIDATED, a bundle that is gone is UNKNOWN while one that was edited is INVALIDATED, a project
with no git history is UNKNOWN rather than VALID, stripping `content_sha256` reproduces the
identical `bundle_hash` (so the completeness gate is provably unaffected), a PRE_SIGNOFF bundle
mints no freeze while a gate-verified one does, and a byte-level snapshot proves evaluating a
freeze writes nothing.

**Disclosed residual.** (1) There is no `dv-harness` CLI verb -- `cli.py` was being modified by
concurrent work in the same session -- so the ad-hoc door is `python -m dv_harness.signoff_export`
plus the auto-freeze on the real gate-verified path. (2) `spec_version` and `dashboard_snapshot`
are structurally NOT_AVAILABLE for the reasons above; closing either needs a producer this repo
does not have. (3) This repository's own baseline honestly captures 4 of 15 fields today (it has
no RTL tree, no generated TB, no VIP install, no waiver ledger and no coverage database of its
own) -- the mechanism is proven against real fixtures, not made to look complete by writing
fabricated artifacts into this project's real audit trail. (4) It detects; it does not
re-baseline: there is no "revalidate" verb, because deciding that an invalidated signoff is
acceptable is a human judgment, and minting a fresh freeze over a changed project is just
`freeze` again with a human named on it.



<!-- S078: moved verbatim from CLAUDE.md original lines 4916-4933 (M4.6 CLAUDE Context Normalization) -->
## Subsystem Verification Contract Aggregator (2026-09-06)

A subsystem's verification truth -- which spec/DUT/TB it was verified against, which protocols/interfaces it exercises, what its requirements say, its vPlan/test/coverage correspondence, whether regression passed, whether SIGNOFF happened and against what frozen baseline, which evidence and reproducibility capsules back it, which waivers apply -- already existed as real, separately-queryable facts across `env_manifest.py`, `requirement_contract.py`, `golden_scenario.py`, `signoff_export.py` and `waiver_store.py`. Nothing assembled them into ONE record; two audits of the same project could describe a subsystem's "verification contract" differently even from identical underlying facts.

`dv_harness/subsystem_contract.py` is that assembly, and it is a pure aggregator: every field is read through an already-real function this repo ships, never re-derived. `spec_version`/`dut_sha`/`tb_sha` come from `signoff_export.capture_baseline()` (LIVE, not the frozen copy -- that function is already section 238's tested reader for these three identities). `protocols`/`interfaces`/`vplan_tests_coverage` come from `env_manifest.load_env_manifest()` + `summarize_for_blackboard()` (the same prompt-sized summary the `env_manifest` Blackboard topic already carries): `protocols` is the distinct `vip_type` values off `vip_config.vip_instances`, `interfaces` is those instances' own `instance_path` bindings, and `vplan_tests_coverage` is `env_topology.testplan_correspondence` verbatim with its own COMPUTED/PARTIAL/NOT_AVAILABLE status. `requirements` goes through `requirement_contract.execute_verb()` over a caller-named or conventionally-located requirement-contract JSON file (this repo has no fixed producer path for that artifact yet, the same disclosed boundary `generation_readiness.py`'s Spec Parsing / Requirement IR row already states -- an absent file is reported `NOT_AVAILABLE` naming exactly what was checked). `regression` is `regression_reporter.load_jobs()` + `dashboard._lsf_summary()`, the same real per-job LSF summary `golden_flow_readiness.py`'s LSF Regression row already reads. `signoff` carries the real-time `signoff_export.read_signoff_stage_status()` PLUS -- only when one was ever recorded -- the frozen `signoff_export.load_freeze()` baseline and its `evaluate_freeze_invalidation()` verdict; a project that never froze a baseline reports `NO_SIGNOFF_FREEZE_RECORDED` rather than a live re-capture standing in for "the signoff baseline" section 238 names. `evidence_references`/`reproducibility_capsules` share one `golden_scenario._open_store()`-opened `EvidenceStore`: the former is the real `normalized_evidence` rows (same table/columns `golden_scenario._fetch_normalized_evidence()` reads, unfiltered here), the latter is `golden_scenario.evaluate_store_freshness()` -- the real capsule list AND its real FRESH/STALE/UNKNOWN verdict. `waivers` is `waiver_store.status_report()` EXPLICITLY (not `signoff_export`'s digest-only waiver capture), because this contract wants the full per-waiver DERIVED status (VALID/EXPIRED/REVALIDATION_REQUIRED/REVOKED/UNKNOWN, TH-7).

**Subsystem scope.** Naming `--subsystem` consults `environment_mode_router.read_registered_subsystem_entries()` -- the real registry `engine._persist_subsystem_registry_entry()` writes only on a gate-verified SIGNOFF PASS for that subsystem. A match narrows the manifest lookup to that entry's own `environment_manifest` path; no match records the honest, named `SUBSYSTEM_NOT_REGISTERED` and falls back to the project's own default `env.manifest.json` -- most subsystem-mode/IP-level projects never reach a registered SIGNOFF and still have a real single-environment contract worth assembling. Omitting `--subsystem` assembles the project-scope contract.

**`unknowns` is the honesty surface.** Every field that could not be assembled lands there as `{"field", "reason"}`, never silently dropped or defaulted to an empty-but-present value; `completeness` (`COMPLETE`/`PARTIAL`/`NOT_AVAILABLE`) is scored against the fixed `TRACKED_ASPECTS` denominator, and the subsystem-scope-resolution unknown (a fact about the REQUEST, not about a contract field) deliberately never inflates that count.

**Read-only, with one explicit write.** `assemble_subsystem_contract()` mints no `.dv-harness/` tree, `StateStore`, evidence database, or waiver ledger where none exists -- every reader it calls already honours that contract on its own (`default_manifest_path()` returns `None` rather than generating; `read_signoff_stage_status()` reads state.json with a plain `json.loads`, never `StateStore.load()`; `golden_scenario._open_store()` returns `None` for an absent evidence.duckdb; `waiver_store.status_report()` reports `NO_WAIVER_STORE` rather than minting a ledger). `write_subsystem_contract()` / the `snapshot` verb is a separate, explicit act that persists the record to `.dv-harness/subsystem_contract.json`; `assemble` never writes. Both share `execute_verb()` (0 COMPLETE, 1 PARTIAL, 2 NOT_AVAILABLE/usage error), exposed as `python -m dv_harness.subsystem_contract assemble|snapshot [--subsystem ...] [--manifest ...] [--requirements ...] [--db ...] [--json]`. No `dv-harness` CLI verb was added -- `cli.py` was concurrently in use by other parallel work this session, the same reason several recent modules (`signoff_export`, `waiver_store`, `dependency_supply_chain`) also stay `python -m` only. It DECIDES, ARBITRATES and WRITES NO GOVERNANCE STATE: no stage runs, no gate is invoked, no approval is minted, and there is deliberately no stage gate -- a gate that passed because a contract record existed, or failed because one did not, would be worse than none.

**A real, pre-existing defect was found (and NOT fixed, out of this task's scope) while wiring this in**: `signoff_export._capture_evidence_hashes()` indexes `EvidenceStore.query()`'s plain tuple rows (`fetchall()`) with string keys (`r["evidence_id"]`), which raises `TypeError` the first time a project's `normalized_evidence` table actually holds rows -- apparently never exercised by that function's own test suite, which only covers the empty/absent-database paths. `capture_baseline()` bundles all fifteen section-238 fields into one call, so this contract's use of it for `spec_version`/`dut_sha`/`tb_sha` would otherwise crash the whole assembly whenever real evidence exists. `assemble_subsystem_contract()` now wraps that call and degrades those three fields to a named `NOT_AVAILABLE` (citing the real exception) instead of raising -- proven by `test_capture_baseline_failure_degrades_to_not_available_never_crashes`, which reproduces the trigger with a real evidence row. The underlying `signoff_export.py` defect itself is unfixed and should be closed in a follow-up touching that file.

`dv-harness subsystem-contract` has no dashboard card and no graph node -- this is a REACHED capability (a real CLI/import caller exists), not a WIRED one.

Proven by `dv_harness_tests/test_subsystem_contract.py` (37 tests) against real producers throughout: a real schema-valid `env.manifest.json` (via `env_manifest.generate_and_write()` with a real vip_config dump + testplan_sources file), a real waiver via `waiver_store.record_waiver()`, a real DuckDB `EvidenceStore` carrying a real `vip_distill.distill_sim_log()` envelope and a real `golden_scenario` capsule, a real LSF job JSON, a real `signoff_export.freeze_signoff_baseline()` freeze, and a real `subsystem_environment_registry.json`. Negative controls: a bare/uninitialized root (every tracked aspect honestly `NOT_AVAILABLE`, nothing fabricated, no `.dv-harness/` tree created), a manifest present but schema-invalid, an overclaimed (COMPLETE-with-a-placeholder-field) requirement record surfacing as FAIL rather than being smoothed into PASS, an LSF job with no `dv_analysis_status` (LSF DONE is not DV PASS), an expired waiver reported `WAIVERS_NOT_VALID` rather than collapsed into `NOT_AVAILABLE`, an `evidence.duckdb` that exists but holds zero rows, no signoff freeze recorded, a subsystem name requested but never registered (falls back to the project manifest), and the `capture_baseline()` crash-resilience case above. Both CLI verbs are driven as real subprocesses with their exit codes asserted.


<!-- S079: moved verbatim from CLAUDE.md original lines 4934-5018 (M4.6 CLAUDE Context Normalization) -->
## Functional Coverage Signoff Rollup: Closure = Covered + ApprovedWaiver + ProvenUnreachable (2026-09-06)

"Is functional coverage closed enough to sign off" was answerable today only by a human reading
three unrelated artifacts by hand: the waiver ledger (`waiver_store.py`), the coverage hole
classifier (`coverage_analysis.py`), and the testplan/coverage correspondence
(`env_manifest.py`'s `testplan_correspondence`, cross-checked against the real recorded numbers
in `evidence_db.EvidenceStore`). Nothing joined the three into one Closure percentage or one
FUNCTIONAL_COVERAGE_SIGNOFF_READY verdict, so two audits of the same project could disagree about
the same facts -- the same gap `golden_flow_readiness.py` and `platform_health.py` already closed
for their own domains. `dv_harness/functional_coverage_signoff.py` is that rollup, following their
same convention: one `analyze_functional_coverage_signoff()` function, `execute()` returning
`(exit_code, report, text)`, and `python -m dv_harness.functional_coverage_signoff` as the front
door (no `cli.py` verb was added -- that file was under concurrent edit by other parallel
2026-09-06 work, the same reason several sibling additions that day name for skipping CLI wiring).

**Formula, over the coverage bins the project's own testplan declares (`coverage_present` in
`env_manifest.py`'s `testplan_correspondence`) and that have a real recorded number in
`evidence_db.EvidenceStore`'s `coverage_samples` table (never the live, possibly stale
`summary.json` -- the same table `dashboard._ingest_coverage_summary_to_evidence_db()` lands into
in the first place):**

    Closure % = 100 * (Covered_bins + ApprovedWaiver_bins + ProvenUnreachable_bins)
                / Total_declared_goal_bins

`Covered_bins` is `sum(bins_hit)` over those declared, recorded categories.
`ApprovedWaiver_bins` credits a category's `bins_missing` when `waiver_store.status_report()`
reports at least one waiver whose `item` field literally names that coverage bin (a name join,
never fuzzy -- the same discipline `env_manifest.py`'s own testplan/coverage join already applies)
with status `VALID`. `ProvenUnreachable_bins` credits a category classified
`UNREACHABLE_STIMULUS` by the real `coverage_analysis.classify_coverage_hole()` -- fed the
project's own recorded `root_cause_classification` claim, read from the real COVERAGE_CLOSURE
stage's `coverage_hole_regeneration_gate` evidence block through `gates.extract_evidence_blocks()`,
never invented -- **and only once a real human has ANSWERED the escalation question
`STRUCTURALLY_UNREACHABLE`** (`question_queue.QuestionQueueStore.answer_question()`, the one path
that reaches `status == "ANSWERED"`; a Tier-2 auto-assumption or Tier-1 self-resolution is never
consulted). A later reconsideration overrides an earlier confirmation: only the most recently
ANSWERED record for that bin's `coverage/<id>` context_path decides. An `INSUFFICIENT_SEED_ATTEMPTS`
hole (an under-sampled bin, per that same classifier's own seed-attempt floor) NEVER counts here,
by construction: `classify_coverage_hole()` only reaches `UNREACHABLE_STIMULUS` once the seed floor
clears, so "not enough seeds yet" and "structurally unreachable" can never be credited through the
same path. A waiver takes priority when both apply to one category -- credited once, never twice.

`FUNCTIONAL_COVERAGE_SIGNOFF_READY` is true only when: the evidence database and at least one
declared bin are available; every declared bin carries a real recorded number (a declared bin with
NO recorded evidence at all reports `INCOMPLETE_EVIDENCE` and refuses readiness -- a percentage
computed only over the bins somebody happened to measure must never stand in for the whole
project's closure); Closure reaches 100%; and no waiver matching ANY declared bin -- whether or not
it is the one being credited -- carries status EXPIRED, REVOKED or UNKNOWN (a bad waiver "in the
mix" blocks signoff even when the measured Closure already reads 100%, and even when the waiver
targets an already-fully-covered bin).

**Honest absence, never a silent 0 or 100.** An absent evidence database makes the WHOLE report
`NOT_AVAILABLE` (Covered/Total both derive from it, so there is nothing left to compute); an
absent waiver ledger is reported `NOT_AVAILABLE` for that one input but contributes a real,
disclosed zero credit and zero blocking rather than crashing the computation -- a project that has
not adopted the waiver ledger is never retroactively failed, the same disclosed-default shape
`waiver_store.py`'s own gate wiring already uses. An absent `env.manifest.json` widens the declared
scope to every category the evidence database has ever recorded, with the real reason stated,
rather than reporting an empty or fabricated scope.

**Deliberately bounded, and stated rather than implied closed.** (1) It decides, approves and
arbitrates nothing: no stage runs, no gate script is invoked, no waiver is recorded or revoked, no
question is asked or answered, and no approval is minted -- the verdict is an input to a human's
signoff decision, exactly like `golden_flow_readiness.py`'s matrix and `platform_health.py`'s
health report. (2) A `REVALIDATION_REQUIRED` waiver neither counts toward closure (only `VALID`
does) nor blocks signoff (only `EXPIRED`/`REVOKED`/`UNKNOWN` do), per this module's own literally
stated formula. (3) There is no `cli.py` verb yet -- `python -m
dv_harness.functional_coverage_signoff` is the only front door.

Proven by `dv_harness_tests/test_functional_coverage_signoff.py` (11 tests), every input produced
by its real owning module rather than hand-shaped to look like one: `waiver_store.record_waiver()`
for the ledger, `EvidenceStore.insert_coverage_sample()`/`insert_job_state()` for the recorded
numbers and seed history, `env_manifest.generate_env_manifest()` over a real schema-valid
testplan-sources document for the declared scope, and the real `coverage_analysis.
escalate_unreachable_stimulus()` + `QuestionQueueStore.answer_question()` round trip for a proven
hole. The negative controls carry the detection power: an EXPIRED waiver blocks signoff even at a
measured 100% closure; an under-sampled hole (real seed history present, only 3 of the required 20
distinct seeds) is never credited even when the agent claims it is unreachable; a claimed-unreachable
hole whose real escalation question was left unanswered is never credited; a design owner's later
reconsideration (revoke + re-answer the opposite way) correctly overrides an earlier confirmation; a
testplan-declared bin with zero recorded evidence reports `INCOMPLETE_EVIDENCE` rather than silently
excluding it from the goal; and a real `python -m dv_harness.functional_coverage_signoff` subprocess
is driven to exit codes 0 (ready), 1 (a real, non-ready finding) and 2 (essential input
`NOT_AVAILABLE`).


<!-- S080: moved verbatim from CLAUDE.md original lines 5019-5086 (M4.6 CLAUDE Context Normalization) -->
## Subsystem Practicality Score: a 10-Dimension Maturity Rollup (2026-09-06)

This project has at least four real per-domain readiness/quality readers -- `generation_readiness.py`'s
twenty capability rows, `golden_flow_readiness.py`'s twenty stage rows, `loop_convergence.py`'s
convergence/plateau/oscillation classifier, `confidence_calibration.py`'s tier-reliability report, plus
`coverage_analysis.py`'s hole/percent analysis -- and no single number that answered "how practically
mature is this subsystem's verification environment, across all of that, right now". Two people reading
the same project's dashboard could each hand-average a different subset of those signals and report a
different maturity claim. A repo-wide grep for `practicality_score`/`maturity.*rollup`/
`subsystem.*maturity` matched nothing before this module.

`dv_harness/subsystem_practicality_score.py` is the rollup, and it is deliberately thin: it computes
nothing a real producer has not already computed. Every one of its 10 weighted dimensions (spec
correctness 10%, DUT discovery 10%, VIP mapping 10%, UVM generation quality 10%, single-test proof 10%,
regression reliability 10%, failure closure 10%, coverage/protocol closure 15%,
traceability/evidence/reproducibility 10%, usability 5%) reads the ALREADY-DERIVED verdict of one
existing module -- never raw evidence, never a second parse of a coverage/DUT/VIP file -- and maps that
verdict onto a 0-100 score through one fixed, documented rule. `spec_correctness`/`dut_discovery`/
`vip_mapping`/`uvm_generation_quality` read `generation_readiness.py`'s own rows;
`single_test_proof`/`regression_reliability`/`usability` read `golden_flow_readiness.py`'s rows (usability
combining its `dashboard` + `claude_cli_integration` rows through that module's own `combine_readiness()`);
`failure_closure` reads `loop_convergence.classify_loop_convergence()`'s verdict;
`coverage_protocol_closure` reads coverage state through the SAME `dashboard._read_coverage_state()`
reader `golden_flow_readiness.py`'s own coverage rows already use; `traceability_evidence_reproducibility`
reads `confidence_calibration.calibrate()`. Every dimension's `fact_source` names the real reader it
calls, and `assert_fact_sources_resolvable()` resolves every one through the import system at test time --
the same anti-drift check `generation_readiness.py`/`golden_flow_readiness.py` already run on their own
rows.

**The weight=0 rule is the actual point of this module.** A weighted average that silently treats a
dimension nobody could measure as a 0 (an unearned FAIL) or a 100 (an unearned PASS) is fabricated
precision -- exactly what the Evidence Truth Rule forbids. A dimension whose real producer reports
absence (an UNKNOWN row, a plateau classifier with no series, `confidence_calibration`'s
NOT_AVAILABLE/INSUFFICIENT_HISTORY, an unreadable/absent coverage summary) is marked NOT RESOLVABLE: its
declared weight drops to 0 for THIS report, its score stays `None` (never defaulted), and the real reason
the underlying producer gave is carried through verbatim. The overall score is a weighted average over
only the RESOLVABLE dimensions, renormalized to their own weight -- and `measured_weight_percent` reports,
next to it and never folded into it, how much of the declared 100% that renormalization actually covers.
A 100/100 score measured over 10% of the declared weight is not the same claim as one measured over all
of it, and this report never lets the two look alike.

**It reads only.** No stage runs, no gate is invoked, no build/regression/LSF job starts, and it writes
no state or governance record of its own -- `derive_subsystem_practicality_score()`, `execute_verb()`, and
`render_practicality_matrix()` are all reads over reports that are themselves read-only rollups.
`ControlPlane.approve()`, `policy.can_signoff()`, `assert_human_approval()`,
`HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError` and the PR-only main/master governance
are untouched and uncalled from here. There is deliberately no stage gate: a gate that passed on a
maturity SCORE nobody reviewed would be worse than none. It deliberately does NOT import
`subsystem_maturity_gate.py` -- both modules derive their conditions independently from the same
underlying real sources, so the two files' change histories stay independent.

Front door: `python -m dv_harness.subsystem_practicality_score score|matrix --root <dir> [--json]`. No
`dv-harness` CLI verb was added -- `cli.py` is a large existing argparse tree and, per this task's own
guidance, wiring was skipped in favor of the standalone `python -m` front door.

Proven by `dv_harness_tests/test_subsystem_practicality_score.py` (23 tests): every dimension is driven
through its real owning module (a real `generation_readiness` project state, a real
`golden_flow_readiness` state.json, a real coverage summary, a real `confidence_calibration` corpus)
rather than a hand-shaped stand-in, and the weight=0 rule is proven both ways -- an unmeasurable
dimension never drags the score toward 0 or 100, and `measured_weight_percent` correctly shrinks when a
dimension is dropped. `assert_fact_sources_resolvable()` is proven to fail on a renamed reader.

**Disclosed residual**, mirroring `subsystem_maturity_gate.py`'s own: one rolled-up producer,
`golden_flow_readiness.derive_golden_flow_readiness()`, materializes a default
`.dv-harness/config.json`/`control.json` the first time it runs over a project that already has
`state.json` but no `config.json` yet -- a pre-existing behavior of that module, inherited rather than
introduced here, and out of this module's own scope to fix.


<!-- S081: moved verbatim from CLAUDE.md original lines 5087-5110 (M4.6 CLAUDE Context Normalization) -->
## Subsystem Maturity Gates: 9.0 / 9.5 / 10.0 (2026-09-06)

Three named maturity levels are now real composite qualification gates rather than a document a human assembles by hand. `dv_harness/subsystem_maturity_gate.py` derives every condition from an already-real producer this project has; it is a COMPOSITE CHECK, not a new measurement layer, and it deliberately does NOT import `subsystem_practicality_score.py` -- both files derive their conditions independently from the same underlying real sources, so the two items' change histories stay independent.

**Six conditions, each resolved through the import system.** `assert_fact_sources_resolvable()` mirrors `golden_flow_readiness`'s own pattern exactly: a condition citing a renamed/removed function fails a test rather than silently reporting a fabricated MET.
- `golden_flow_spec_to_uvm_to_pass` -- `golden_flow_readiness.derive_golden_flow_readiness()`'s own `spec_in`/`requirement_extraction`/`vip_uvm_generation`/`single_test_proof` rows, all READY.
- `system_smoke_proof_ready` -- `system_build_proof.py`'s `SYSTEM_READY` verdict, read from a caller-supplied real `SmokeProofReport.to_dict()` (this module never assembles the ladder's own heavy inputs -- composed sources, filelists, fsdb -- itself).
- `zero_vip_api_hallucination` -- `vip_api_card.validate_vip_api_usage()`, zero BLOCKED citations, either from an already-written `vip_api_cards.json` artifact or run fresh over supplied sources + a VIP symbol index.
- `bind_validation_clean` -- `connectivity.assert_bind_entry_tier_allows_emission()`/`BindTierError`: no unresolved T3 (unconfirmed naming-heuristic) or T4 (undecidable) bind entries.
- `regression_evidence_exists` -- real `evidence_db.EvidenceStore` rows (`jobs`, `normalized_evidence`).
- `false_pass_count_zero` -- **always `NOT_MEASURABLE`**, honestly. Re-verified by direct search before writing this condition: neither `golden_scenario.py` nor `requirement_contract.py` (the two modules most likely to carry one) persists a COUNT of confirmed false-PASS verdicts over a qualification set; `tools/verification_flow/false_pass_resistance_gate.py` is a per-stage, agent-attested evidence-block shape check, not a count. Inventing a counter would be exactly the fabrication the Evidence Truth Rule forbids -- this condition names the search and reports the honest gap instead.

**The vocabulary is checked disjoint from `models.Status`, not merely chosen carefully.** A condition's outcome (`MET`/`UNMET`/`NOT_AVAILABLE`/`NOT_MEASURABLE`) and the gate's own verdict (`QUALIFIED`/`NOT_QUALIFIED`/`INCOMPLETE_EVIDENCE`) are asserted at import time (`assert_no_verification_verdict_vocabulary()`) to share no token with `models.Status` -- the same guard `capability_evolution.py`/`benchmark_dataset.py`/`dependency_supply_chain.py` already apply to their own domain vocabularies.

**Levels form a strictly monotonic ladder** (`assert_levels_are_monotonic()`): 9.0's required conditions are a real subset of 9.5's, which are a real subset of 10.0's. A `NOT_MEASURABLE` required condition never blocks `QUALIFIED` (there is nothing this project could do today to make `false_pass_count_zero` MET, so blocking on it would make 10.0 permanently unreachable rather than honestly disclosed) but is always carried on the report's `disclosed_caveats` list, so a `QUALIFIED` 10.0 verdict is never silently read as "every dimension was checked and clean". An `UNMET` required condition makes the level `NOT_QUALIFIED`; a `NOT_AVAILABLE` one (evidence genuinely missing/not supplied) makes it `INCOMPLETE_EVIDENCE` instead -- a level this gate could not evaluate is a different fact from one it evaluated and found wanting, and the test suite's headline negative control proves a real gate-shaped FAIL produces `NOT_QUALIFIED`, never the softer `INCOMPLETE_EVIDENCE`.

**It reads only.** No stage runs, no gate script is invoked, no build/regression/LSF job starts, and there is deliberately no stage gate of its own -- a `QUALIFIED` verdict is an input to a human's qualification decision, never a substitute for one.

Front door: `python -m dv_harness.subsystem_maturity_gate conditions|evaluate --level {9.0,9.5,10.0} --root <dir> [--json] [--vip-api-cards ...] [--bind-topology ...] [--evidence-db ...] [--smoke-proof-report ...]`. No `dv-harness` CLI verb was added -- `cli.py` is a large existing argparse tree and, per this task's own guidance, wiring was skipped in favor of the standalone `python -m` front door, the same disclosed choice several very recent same-day additions in this repo have made.

Proven by `dv_harness_tests/test_subsystem_maturity_gate.py` (39 tests) against real evidence throughout: a real `.dv-harness/state.json` (via `storage.StateStore`) plus a real uploaded document for the golden-flow condition; a real DuckDB `EvidenceStore` carrying a real `lsf_client.JobState` row and a real `vip_distill.distill_sim_log()` envelope for the regression-evidence condition; the real shipped VIP symbol index (`examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv`) and the real clean `demo_env_seq.sv` fixture, mutated one fabrication at a time, for the VIP-API condition; the real shipped `examples/generated_usb_real_evidence_v1/manifest_inputs/usb_bind_topology.json` plus real T4/unconfirmed-T3 entries run through `connectivity`'s real tier gate for the bind condition; and a real `system_build_proof.SmokeProofReport` dataclass's own real `.to_dict()` for the smoke-proof condition (that ladder's own mechanics are proven end-to-end elsewhere by `test_system_build_proof.py`; this suite proves only this gate's consumption of that real report shape). Negative controls: a renamed fact_source is refused, a vocabulary collision is refused, a non-monotonic ladder is refused, a real gate-shaped FAIL makes a level `NOT_QUALIFIED` (never merely `INCOMPLETE_EVIDENCE`), no evidence at all is `INCOMPLETE_EVIDENCE` (never `NOT_QUALIFIED`), and `false_pass_count_zero` is asserted to never block a 10.0 `QUALIFIED` verdict while still appearing under `disclosed_caveats`. Both CLI verbs are driven as real subprocesses, including a real exit-2 `INCOMPLETE_EVIDENCE` case. The read-only invariant is held to the exact precedent `test_golden_flow_readiness.py` already established (existing files' content is unchanged; a brand-new `config.json`/`control.json` may still appear, because `derive_golden_flow_readiness()`'s own `five_level_memory` row materializes a default config for any project whose `.dv-harness` tree exists but has no config yet -- a pre-existing side effect of the module being composed, out of this module's own scope to change).

**Deliberately bounded, and stated rather than implied closed.** (1) It never re-runs `system_build_proof`'s heavy ladder itself -- a caller must actually run it and hand this gate the real report. (2) `false_pass_count_zero` can never resolve to `MET` in this codebase today; 10.0 can still be `QUALIFIED`, but always with that gap disclosed, never silently cleared. (3) There is no `dv-harness` CLI verb, by deliberate choice per this task's own escape hatch. (4) It does not import or read `subsystem_practicality_score.py`, by deliberate design, to keep the two files' change histories independent.


<!-- S083: moved verbatim from CLAUDE.md original lines 5163-5228 (M4.6 CLAUDE Context Normalization) -->
## Golden Scenario Qualification Set: Test-Category Completeness (2026-09-06)

`golden_scenario.py`'s capsule store answers "is this specific test's PASS still fresh"; it had no
way to answer the adjacent completeness question a Golden Subsystem Test Set needs: "across the
whole subsystem, have we ever recorded a golden capsule for each KIND of proven result -- a clean
pass, a known DUT bug, a known TB bug, a known VIP-side issue, a caught protocol violation, a
timeout, a coverage hole, a waiver, a register test, a perf test?" Nothing in the module carried a
category concept at all.

This is deliberately NOT a new store. `GoldenScenario` gained one new optional field,
`category`, drawn from a fixed 10-value vocabulary (`QUALIFICATION_SET_CATEGORIES`:
`known_pass`/`known_dut_fail`/`known_tb_fail`/`known_vip_fail`/`protocol_violation`/`timeout`/
`coverage_hole`/`waiver`/`register`/`perf`), appended after the existing `watched_paths` field so no
existing capsule field's meaning, shape or position changed. `validate_capsule()` rejects a declared
category outside that vocabulary; an unset category stays legal, since a capsule MAY declare one,
never must.

**Persisted without touching `evidence_db.py`.** `category` is not one of that module's own known
`golden_scenarios` columns, and this gap-closure's file scope was `golden_scenario.py` only. Rather
than widen `evidence_db.py`'s column list, `golden_scenario.py` persists the new field through
`EvidenceStore`'s own already-public `query()` method -- the SAME raw-SQL seam
`_fetch_normalized_evidence()`/`_fetch_job_git_sha()` already use to read through the store.
`_ensure_category_column()` runs an idempotent `ALTER TABLE golden_scenarios ADD COLUMN category
VARCHAR`, checked first via `duckdb_columns()` (the identical catalog-introspection convention
`evidence_db._golden_scenario_rows()` already uses to check for the TABLE itself, applied here to a
column), and only against a writable store. `record_golden_scenario()` calls it and then UPDATEs the
row; `_attach_categories()` reads the column back on `load_golden_scenario()`/
`load_golden_scenarios()`. A store that never gained the column -- one predating this feature, or one
written to directly through `insert_golden_scenario()` bypassing `record_golden_scenario()` --
reports every capsule's category as `None` rather than raising: "we could not check" must never look
like "uncategorized by choice", and it never crashes either.

**The completeness check itself is a pure function over already-loaded capsules, not a second
query.** `missing_categories(capsules, required=QUALIFICATION_SET_CATEGORIES)` returns which
required categories have zero capsules declaring them, in `required`'s own order. A capsule with no
declared category, or one carrying a value outside the fixed vocabulary, counts toward NONE of the
required categories -- it is never silently credited to one, the same "an uncategorized/out-of-scope
fact must not be read as a fact" discipline this project applies everywhere else.
`qualification_set_report(store, required=...)` wraps it into a `COMPLETE`/`INCOMPLETE` report
(status, per-category present counts, the missing list, total capsule count, and how many capsules
are uncategorized) over the real store; an empty store is INCOMPLETE with every category missing,
never a vacuous COMPLETE over nothing. `dv-harness golden-scenario qualification-set` (and the
identical `python -m dv_harness.golden_scenario qualification-set`) share the module's existing
`execute_verb()`: exit 0 COMPLETE, 1 INCOMPLETE.

**Deliberately bounded.** (1) This checks what has ALREADY been recorded; it mines no requirement,
runs no test, and makes no claim about which categories a given subsystem SHOULD have -- exactly the
same boundary `golden_flow_readiness.py` and `power_intent.py` already draw between "did this
connect" and "should this exist". (2) There is no stage gate: a gate that passed on a qualification
set nobody actually populated would be worse than none. (3) Categorization is a deliberate
`record_golden_scenario()` call's own field, same as everything else in a capsule -- nothing here
auto-classifies a passing run into a category.

Proven by 15 new tests in `dv_harness_tests/test_golden_scenario.py` (36 total, the original 21
untouched and still passing): category-vocabulary rejection/acceptance in `validate_capsule()` and
`capsule_from_json()`; `missing_categories()`'s positive path, its "all present" empty result, and
two negative controls (an uncategorized capsule credits nothing; an out-of-vocabulary category
credits nothing); a real round trip of `category` through `record_golden_scenario()` and
`load_golden_scenario()`/`load_golden_scenarios()` against the real DuckDB store; an uncategorized
capsule round-tripping as `None`; the negative control proving a store whose `category` column was
never added still loads cleanly with `None` rather than crashing; `qualification_set_report()` on an
empty store, a partial real store, and a complete real store (all 10 categories genuinely recorded);
the `qualification-set` CLI verb driven end to end as a real subprocess (partial -> exit 1 naming the
real missing categories, then complete -> exit 0); and the CLI `record` verb's real rejection (exit
2, `CapsuleValidationError` named) of an unrecognized category.


<!-- S085: moved verbatim from CLAUDE.md original lines 5287-5365 (M4.6 CLAUDE Context Normalization) -->
## Coverage DB Merge Integrity Gate (2026-09-06)

Coverage merge -- rolling several regression runs' coverage databases into one signoff-counted
total -- had no integrity check anywhere in this repo. A repo-wide grep before building confirmed
it: nothing named `coverage_merge`/`merge_integrity`/`coverage_db` existed, and
`coverage_analysis.py`'s own docstring already discloses the boundary this respects -- it trusts a
coverage summary JSON "that has ALREADY been reduced to plain JSON by whatever real coverage tool
the project uses", and does not ask whether that file is what it claims to be, or whether the files
being merged came from compatible tooling.

`dv_harness/coverage_db_integrity.py` is that check, and reuses rather than reinvents on both
halves:

- **Content fingerprint.** `connectivity_check.py`'s `compute_rtl_fingerprint()` already does this
  for RTL, but checked first and confirmed RTL-specific by construction (it walks declared
  `rtl_sources` globs), and its per-file hasher `_hash_file()` is a private module helper never
  published for reuse. `env_manifest.py`'s `file_ref()` -- public since 2026-09-06 precisely "so a
  supply-chain report and an env.manifest.json describe the same file identically", and already
  reused by `dependency_supply_chain.py` -- is the same sha256-of-file primitive, so this module
  imports it rather than writing a third hasher, and combines per-file digests using
  `compute_rtl_fingerprint()`'s own scheme (sorted relative path + digest folded into one sha256),
  generalized to any file or directory. `verify_fingerprint_claim()` recomputes this from real bytes
  on disk and compares it against whatever the merge request CLAIMS the coverage DB's fingerprint to
  be -- the same "recompute and compare against a prior claim" shape `connectivity_check.py`'s own
  staleness trigger uses for RTL, here detecting a coverage DB substituted or altered after it was
  staged for merge.
- **Tool/config compatibility.** Checked first whether any real producer records a coverage
  DATABASE's own tool/version identity: `coverage_analysis.parse_coverage_summary()`'s schema is
  `{"categories": [{"name","percent","bins_total","bins_hit"}]}` -- no tool/version field, and that
  function actively DISCARDS any extra key a raw summary might carry, so reading an ad hoc field out
  of one would be inventing a field this project's own parser throws away. What IS real:
  `env_manifest.py`'s `generator.tool_version` (schema 1.2's per-artifact provenance, the real
  `dv_harness.__version__`) and `vip_config.vip_release` (the real `$DESIGNWARE_HOME` filesystem
  scan). Neither is per-coverage-DB by itself, so a merge request associates each entry with the
  env.manifest.json its own run produced, and `analyze_tool_config_compatibility()` compares those
  two real fields across every entry being merged. An entry with no associated manifest contributes
  `NOT_AVAILABLE` identity, named as such, never a fabricated agreement.

**Three verdicts, never two collapsed into one.** `MERGE_ALLOWED` (every fingerprint claim matched,
every recorded identity agreed), `MERGE_BLOCKED` (a real finding -- a mismatch or a proven tool/VIP
disagreement, each named), `MERGE_NOT_VERIFIABLE` (no finding, but something could not be checked --
no claim to compare a fingerprint against, or an entry with no associated manifest). Collapsing the
last two would erase the Evidence Truth Rule's "never collapse two different kinds of unknown into
one value" distinction -- the same INVALIDATED-vs-INDETERMINATE split `signoff_export.py` keeps and
the EXPIRED-vs-UNKNOWN split `waiver_store.py` keeps. What both share, and the reason neither is a
silent pass: only `MERGE_ALLOWED` exits 0 (`fingerprint`/`check` verbs: 0 allowed, 1 blocked, 2 not
verifiable) -- an unverifiable merge is never silently counted toward signoff any more than a proven
-incompatible one is.

`python -m dv_harness.coverage_db_integrity fingerprint --db-path <path>` (compute one coverage DB's
real content fingerprint) and `... check --merge-request <file.json>` (`{"entries":
[{"db_path","claimed_fingerprint"?,"env_manifest_path"?,"label"?}, ...]}`) share one
`execute_verb()`, the same convention `waiver_store.py`/`signoff_export.py` follow. No `dv-harness`
CLI verb was added: `cli.py` is a ~4100-line argparse tree under concurrent modification by other
work in this same session, the identical reason those two modules also stayed ad hoc.

**Deliberately bounded, and stated rather than implied closed.** This module never opens a real
coverage database (UCIS/urg/vdb) and never parses coverage bins -- that boundary belongs to whatever
real coverage tool already reduced it to the JSON `coverage_analysis.py` consumes, and reading one
here would be exactly the "no such parser, do not invent one" limit that module's own docstring
states. It fingerprints FILE CONTENT and compares already-real recorded facts only. It ARBITRATES
nothing: no merge is performed, no coverage total is computed, and there is deliberately no stage
gate -- a gate that passed on a merge nobody actually verified would be worse than none.

Proven by `dv_harness_tests/test_coverage_db_integrity.py` (33 tests) against real coverage-DB
directories/files on disk and REAL schema-valid env.manifest.json files produced through the real
`generate_env_manifest()`/`save_env_manifest()` pipeline over synthetic `$DESIGNWARE_HOME` trees
(the same fixture shape `test_env_manifest_fact_sources.py` already uses) -- nothing hand-typed as a
manifest stand-in. Every positive path carries a matching negative control: a coverage DB mutated
after its fingerprint was claimed (MISMATCH, then `MERGE_BLOCKED` naming the entry), two entries
recording the same VIP package at two different versions (`INCOMPATIBLE`, then `MERGE_BLOCKED`), a
partial view where only one of two entries recorded identity (`NOT_AVAILABLE`, never a fabricated
`COMPATIBLE`), no claims/manifests at all (`MERGE_NOT_VERIFIABLE`, never `MERGE_ALLOWED`), a manifest
failing schema validation, and a malformed merge-request document. One test independently
recomputes the fingerprint from scratch with plain `hashlib` (never calling back into the module
under test) to prove the combination scheme is real, and one patches `env_manifest.file_ref` to
prove it is genuinely called rather than re-implemented. Both CLI verbs are driven as real
subprocesses with their exit codes asserted for all three verdicts.


<!-- S089: moved verbatim from CLAUDE.md original lines 5568-5635 (M4.6 CLAUDE Context Normalization) -->
## IP-Level VIP-vs-Legacy-BFM Ownership Conflict Check (2026-09-06)

`system_resource_inventory.py`'s SYS-11/SYS-12 ACTIVE_DRIVER_CONFLICT machinery is a
CROSS-SUBSYSTEM mechanism by construction -- its own docstring states the gap it closes is that no
single-subsystem check has "any rows to match against" a second subsystem, and every entry point
takes multiple subsystems' evidence at once. That left a narrower, real question unanswered at
plain IP-level intake (a single subsystem, before any SoC composition exists): does THIS ONE
subsystem's own environment declare a real VIP agent AND a legacy hand-written BFM/driver BOTH
ACTIVE on the same interface/port? `connectivity.find_active_bind_target_collisions()` -- the
already-shipped single-matrix version of SYS-12's rule -- comes close but requires BOTH colliding
rows to carry a real VIP (`_row_has_vip()`), so a row whose `vip_type` is a `NO_VIP_MARKERS` value
(exactly what a hand-written, non-VIP driver looks like in that schema) is excluded from the check
entirely, confirmed by direct reading before building.

`dv_harness/ip_ownership_conflict.py` closes exactly that gap. It reuses vocabulary rather than
inventing a second spelling for the same concept: a real conflict's finding record carries
`system_resource_inventory.REL_DRIVER_CONFLICT` / `INTEGRATION_STOPPED` / `SYS12_PREFERRED_MODEL`
verbatim, and `connectivity.ACTIVE_INTERFACE`/`PASSIVE_INTERFACE`/`NO_VIP_MARKERS`/
`build_connectivity_matrix()` are the same active/passive vocabulary and matrix normaliser
`system_resource_inventory.py` itself imports.

**What it reads.** The VIP side is real evidence: `env.manifest.json`'s own
`vip_config.vip_instances` (the schema `env_manifest.parse_vip_config_dump()` already writes --
`instance_path`/`vip_type`/`config_fields`), excluding any entry whose `vip_type` is a
`NO_VIP_MARKERS` value -- the identical exclusion `system_resource_inventory.py`'s own resource
builder applies ("an interface with no VIP is not a resource"). The legacy BFM/driver side has NO
real producer anywhere in this codebase (confirmed by direct search before building), so it is
honestly a caller-declared input, `legacy_bfm_declarations` -- the same status
`SubsystemResourceSources.declared_physical_interfaces` already carries elsewhere ("a project's own
explicit statement... a human's decision, never this module's inference"). Each declared entry's
`port_id` must equal a real `instance_path` EXACTLY -- no fuzzy or name-derived matching, applying
SYS-10's own "do not decide by names alone" to the match key itself. A VIP instance's own
active/passive state is not carried by `vip_config.vip_instances` at all; an optional
`connectivity_rows` input (real rows in `connectivity.build_connectivity_matrix()`'s own shape)
resolves it, using the SAME match-candidate convention (`bind_target`, then `dut_instance`, then
`"dut_instance.interface"`) `system_resource_inventory._build_resources_for_subsystem()` already
uses the other direction. Omitting it never invents an active/passive value -- the affected pair
reports UNDETERMINED instead.

**Four honest statuses**, deliberately distinct from SYS-11's seven relationship classes (this
module's `STATUS_CONFLICT` is checked NOT to collide with `REL_DRIVER_CONFLICT`, the token it
stands beside): `CONFLICT` (a real VIP and a legacy driver both ACTIVE on one port),
`CLEAR` (legacy driver(s) declared and checked, none collide), `NOT_APPLICABLE` (no legacy
BFM/driver declared at all -- the honest common case for a subsystem built entirely on VIP), and
`UNKNOWN` (an active legacy driver shares a real VIP's port but the VIP's own active/passive state
could not be resolved -- never silently read as CLEAR).

**Detection only, exactly like its cross-subsystem sibling.** It never picks a winner between the
VIP and the legacy driver, never disables an agent, never edits an environment, and references no
approval/governance mechanism -- a conflict record names SYS-12's preferred resolution model as
text for a human, and nothing here acts on it.

No `dv-harness` CLI verb was wired (`cli.py`'s argparse tree is large and this check has no clean
home in it yet, the same disclosed choice several recent modules made) -- front door is
`python -m dv_harness.ip_ownership_conflict --env-manifest <path> [--legacy-bfm <path>]
[--connectivity-rows <path>] [--json]`, one shared `execute_verb()`. Exit 0 CLEAR, 1 CONFLICT,
2 NOT_APPLICABLE or UNKNOWN.

Proven by `dv_harness_tests/test_ip_ownership_conflict.py` (16 tests): the real conflict path
(including a multi-entry case where one real conflict outranks an unrelated clear declaration), a
vocabulary-reuse assertion that the finding cites `system_resource_inventory`'s own tokens
verbatim, and seven negative controls -- no legacy declared, a passive legacy driver, a passive
VIP, an unmatched `port_id` (proving no fuzzy matching), a mutate-one-defect control that turns the
conflicting fixture's real VIP into a `NO_VIP_MARKERS` value and asserts the same port/legacy pair
no longer conflicts, an undeclared/invalid legacy `active_passive`, and an active legacy driver
with no `connectivity_rows` supplied (must read UNKNOWN, never a guessed CONFLICT or CLEAR). Three
tests drive the real CLI as a subprocess and assert its exit codes.


<!-- S090: moved verbatim from CLAUDE.md original lines 5636-5682 (M4.6 CLAUDE Context Normalization) -->
## Configuration Variant Explosion Control: vPlan-Stage Wiring (2026-09-06, TH-5 follow-up)

`config_variant_coverage.py`'s IPOG covering-array generator (see its own CLAUDE.md section
above) required a caller to hand-build `ConfigDimension`/`ConfigSpace` objects, or a full space
JSON file, before it could plan anything -- so a vPlan-generation caller sitting on a section 184
requirement's declared configuration had no direct path in. `plan_from_requirement_configuration()`
closes exactly that gap, and only that gap: it is a thin adapter, not new algorithm work. It
shapes a caller-supplied mapping of dimension name -> legal values (plus optional
`constraints`/`critical_combinations` in the module's own existing raw shapes) into the raw dict
`config_space_from_dict()` already parses, then calls `build_plan()` -- both pre-existing,
tested mechanisms, unchanged.

**Checked against the real schema rather than guessed, and the two disagree.**
`dv_harness/schemas/requirement_contract.schema.json`'s `configuration` field is `contract_text`
-- a free-text STRING (section 184's "Configuration"; `NONE` is legal for "no dependency"), never
a structured dict. So this adapter does NOT parse a requirement record's `configuration` string
field itself: doing so would mean inventing a natural-language parser and guessing at a
dimension/value split the contract does not encode, which the Evidence Truth Rule forbids. It
takes the dimension->values mapping as a caller-supplied input instead -- something a vPlan
generator would already have had to extract from one or more requirements' configuration/
precondition text by some other, requirement-content-aware mechanism this module does not
implement or claim to. `requirement_id` is carried through only as PROVENANCE (each dimension's
`source`, the plan's own `space_id`/`description`), never as something this function reads
requirement content from.

Every plan it returns is independently re-verified exactly like every other plan this module
emits, because `build_plan()` (unchanged) is what actually produces it -- there is no second,
weaker code path for requirement-sourced plans. `ConfigSpaceError` (the module's one real error
type) is raised, never swallowed, on a missing/malformed configuration mapping or on anything
`config_space_from_dict()`/`build_plan()` itself would refuse (duplicate dimension, illegal or
uncompletable critical combination, and so on).

No existing public API in `config_variant_coverage.py` was touched -- this is one new function.

Proven by 7 new tests appended to `dv_harness_tests/test_config_variant_coverage.py` (37 total,
all passing): an independent brute-force pairwise-coverage recount against a synthetic 3-dimension
requirement configuration (never trusting the module's own verifier), requirement_id/no-
requirement_id provenance labelling, constraints/critical_combinations pass-through, three
malformed-mapping negative controls (empty mapping, `None`, a dimension whose values is a bare
scalar instead of a list), and a negative control proving the adapter still surfaces rather than
swallows the existing "no legal completion for a declared critical combination" refusal.

**Deliberately bounded, and stated rather than implied closed.** This is REACHED, not WIRED:
nothing in `requirement_contract.py` or any generator calls `plan_from_requirement_configuration()`
yet, and no CLI verb or graph node was added -- a vPlan-generation caller must invoke it
directly.


<!-- S092: moved verbatim from CLAUDE.md original lines 5733-5795 (M4.6 CLAUDE Context Normalization) -->
## Branch Ownership Resolver: block/branch_a*/branch_fw/branch_b* Ownership as Code (2026-09-06)

CLAUDE.md's own Engineering Discipline Rules already state, in prose, which task-composition layer
owns which kind of operation ("Architecture-conformance audit": `block` = SoC global initial tasks;
`branch_a*` = DUT+PHY initial tasks per port; `branch_fw` = the FW service loop per port; `branch_b*`
= VIP-driven parallel tasks) and requires an explicit, RTL-evidence-based arbitration policy for any
concurrent shared-resource access across `block`/`branch_a*` ("Concurrent bus arbitration"). Neither
rule was checkable: nothing in this repo classified a proposed action's ownership tier from its
declared nature, and nothing validated an EXISTING branch assignment against these rules for a
single proposed action -- `tools/verification_flow/branch_topology_gate.py` (this repo's own
canonical-naming authority per `amba_discovery_report.py`'s header) checks only that a whole branch
SET is complete for a declared port count, a different question.

`dv_harness/branch_ownership_resolver.py` closes that. `classify_operation_ownership(operation_kind,
per_port=, driven_by=, arbitration_policy=)` classifies a proposed action's ownership as
GLOBAL/DUT/FW/VIP from a fixed, skill-grounded taxonomy of five fixed-tier operation kinds
(`SOC_GLOBAL_ONE_SHOT_INIT`, `DUT_PHY_PORT_BRINGUP`, `FW_EVENT_SERVICE_LOOP`,
`VIP_DRIVEN_TEST_BODY`, `VIP_DRIVEN_DATA_TRANSFER`, each cited directly to pattern-architecture
SKILL.md section 1) plus two CONTEXT-DEPENDENT kinds (`RAW_DUT_REGISTER_WRITE`,
`SHARED_RESOURCE_ARBITRATED_ACCESS`) whose tier depends on caller-declared `per_port`/`driven_by`/
`arbitration_policy` facts and resolves to AMBIGUOUS, naming the missing or contradictory fact,
when those are absent or inconsistent -- never a guessed tier. An operation kind outside the
taxonomy reports UNKNOWN.

`validate_branch_assignment(branch_label, operation_kind, ...)` then validates an EXISTING
assignment: it first checks `branch_label` against the canonical naming this repo's own
`branch_topology_gate.py` already established (`block`/`branch_a{i}`/`branch_fw`/`branch_b{i}`,
underscore-separated, 0-indexed, reusing `amba_discovery_report.L5_BRANCH_BLOCK`/`L5_BRANCH_FW`/
`l5_branch_a`/`l5_branch_b` rather than re-deriving it) -- a legacy or malformed label is INVALID
under `ARCH_CONFORMANCE_NAMING_VIOLATION` regardless of the operation. It then compares the
operation's classified tier against the tier the branch label implies, reporting INVALID with a
named rule (e.g. `VIP_DRIVEN_WORK_ASSIGNED_TO_BRANCH_A`, `RAW_DUT_OPERATION_ASSIGNED_TO_BRANCH_B`,
`FW_SERVICE_LOOP_DUPLICATED_IN_BRANCH_B` -- the task's three headline examples, plus every other
tier-pair mismatch) whenever they disagree, VALID when they agree, and AMBIGUOUS whenever the
operation's own classification could not be resolved -- an assignment can never be judged correct
or incorrect without first knowing what the operation actually is.

**Deliberately bounded, and stated rather than implied closed.** This module reads no RTL, no VIP
index and no command.txt file: an operation's nature (is it VIP-driven, is it per-port, who issues
it) is a DECLARED input the caller supplies from its own real evidence, never derived here -- per
the Evidence Truth Rule, there is no source in this repo that could tell this module, from a bare
register address or macro name, which task group issues a given write. It DECIDES nothing beyond
reporting: no build, no job, no approval, and there is deliberately no stage gate. It also does not
check a branch SET's completeness (that stays `branch_topology_gate.py`'s job) or verify an
arbitration policy's own RTL grounding (`SHARED_RESOURCE_ARBITRATED_ACCESS` resolves once a policy
is DECLARED; whether that policy is actually correct against the real arbiter RTL is not checked
here).

Ad hoc: `python -m dv_harness.branch_ownership_resolver classify|validate --payload <json>` (exit 0
RESOLVED/VALID, 1 AMBIGUOUS/INVALID, 2 UNKNOWN or a usage error for `classify`; 0 VALID, 1 INVALID,
2 AMBIGUOUS for `validate`). No `dv-harness` CLI verb is registered -- that integration is out of
this task's scope.

Proven by `dv_harness_tests/test_branch_ownership_resolver.py` (39 tests) against a real
command.txt-shaped two-port USB-style pattern fixture and a real legacy-naming sibling fixture in a
real small directory tree: core positive paths for every fixed-tier and context-dependent kind; all
7 tier-pair INVALID combinations including the task's three headline examples verbatim; naming
negatives (the dash-separated legacy label pulled from the real fixture, an uppercase category tag,
an unrelated string, a missing label); 8 classify-level negative controls (unrecognized/missing
operation kind, missing per_port, contradictory driven_by, contradictory per_port, missing
arbitration_policy, unrecognized driven_by) each asserted to land on AMBIGUOUS/UNKNOWN rather than a
guessed tier; and a real CLI subprocess run asserting its exit code and JSON output.


<!-- S093: moved verbatim from CLAUDE.md original lines 5796-5861 (M4.6 CLAUDE Context Normalization) -->
## Existing-Command Reuse Score: Rank, Never Force a Guess (2026-09-06)

`.claude/skills/CORE/command-inventory/SKILL.md` already treats existing DE `command.txt` as a
"reusable capability baseline" and requires a `.dv-workflow/command_inventory.csv` inventory, but
nothing in this repo actually RANKED that inventory against a new vPlan-driven need -- the skill
says "reuse it" in prose and left the comparison to whoever was authoring the new command.txt.
`dv_harness/existing_command_reuse_score.py` is that comparison.

It deliberately never imports `de_command_style_learning.py` (a concurrently-built module in this
same batch that learns DE command-naming style and would emit `DECommandRegistryIR`-shaped
records) or assumes its exact field names. `existing_commands` is accepted as a plain list of
dicts, read through an alias-tolerant `_get()` table so it works equally against that module's
eventual shape, against `subsystem_command_contract.py`'s SYS-8 contract fields
(`command_name`/`command_category`/`arguments`/`branch_layer`/`source_command_file`), and against
a literal `.dv-workflow/command_inventory.csv` row turned into a dict
(`COMMAND`/`PARAMETERS`/`SOURCE`/`HANDLER`/`VIP_SEQUENCE`/`STATUS`/`CONFIDENCE`) -- fields it does
not recognise are simply not used for scoring, never guessed at.

**Four ranking dimensions, exactly as specified**: (1) semantic-name match -- a deterministic
LEXICAL Jaccard token-overlap over name/description/category/keywords, explicitly NOT an
embedding/ML model (none exists in this codebase, and inventing one would be exactly the
unverifiable machinery the Evidence Truth Rule forbids); (2) argument-shape compatibility --
position-aligned role comparison when arguments are structured `{position, role}` records (the
same `role` vocabulary `subsystem_command_contract.schema.json` already uses), degrading to a
raw-token comparison when only a flat `PARAMETERS` string/list is available, with the two forms
kept distinguishable in the report; (3) branch-ownership compatibility -- the canonical
`block`/`branch_a*`/`branch_fw`/`branch_b*` vocabulary from `pattern-architecture/SKILL.md` and
`branch-mapper/SKILL.md`. These four layers genuinely do different things, so a branch-family
MISMATCH excludes a candidate from ranking entirely rather than merely scoring it low; a
non-canonical label (e.g. `BranchA0`) is still resolved to its family but flagged
`LEGACY_NON_CANONICAL_NAMING`, per the Engineering Discipline Rules' "legacy/pre-v8 naming ...
must be flagged and corrected, not silently left in place"; (4) real historical PASS evidence --
read read-only from `evidence_db.py`'s `regression_verdict_history` table (the same table
`golden_scenario.evaluate_freshness()` and `trend_analysis.detect_pattern_regressions()` already
read), keyed by whichever of a candidate's declared `pattern` / `command_name` / the stem of
`source_command_file` actually has recorded rows, tried in that priority order. A candidate with
no recorded rows reports `NO_RECORDED_HISTORY`, never a fabricated pass rate of 0 or 1, and
contributes zero to the composite score the same way a genuinely all-failing history does -- the
numbers can coincide, but the machine-readable `status` and the human-readable reason never do.

**NO_REUSE_CANDIDATE, never a forced low-confidence pick.** A candidate must clear TWO
independent bars: `composite_score >= MIN_PLAUSIBLE_SCORE` (0.20 of the four weighted
dimensions), AND real, non-zero evidence on at least one of the two *observable* dimensions
(semantic-name overlap or argument-shape overlap) -- branch-family agreement alone, or the
zero-contribution of "no recorded history," can never manufacture a plausible match on their own.
When nothing clears both bars, `evaluate_reuse()` reports `NO_REUSE_CANDIDATE` with a named
reason (`NO_EXISTING_COMMANDS_SUPPLIED` / `INSUFFICIENT_NEED_DESCRIPTION` /
`NO_PLAUSIBLE_MATCH`) instead of returning the least-bad candidate as if it were a finding.

**It decides, approves, builds, and runs nothing** -- no stage gate, no write, no self-attested
`STATUS`/`CONFIDENCE` field from a candidate is ever treated as PASS evidence (carried through
verbatim as `declared_status`/`declared_confidence` for a human's information only; the only real
evidence is a `regression_verdict_history` row). `python -m
dv_harness.existing_command_reuse_score --need-file ... --commands-file ... [--root ...] [--json]`
is the ad hoc front door.

Proven by `dv_harness_tests/test_existing_command_reuse_score.py` (37 tests) against a REAL
`evidence_db.EvidenceStore` with real `insert_regression_verdict()` rows -- never a hand-written
history dict. Negative controls carry the detection power: branch-family agreement alone (with
zero name/argument overlap) is refused as a plausible match, an all-mismatched candidate set and
an empty/malformed candidate set both report `NO_REUSE_CANDIDATE` with the real reason, a failing
recorded history scores strictly lower than an identical passing one, a missing evidence database
never invents a pass rate, and both `command_inventory.csv`-style uppercase field dicts and
`subsystem_command_contract.py`-style lowercase field dicts are scored identically through the
alias table.


<!-- S094: moved verbatim from CLAUDE.md original lines 5862-5873 (M4.6 CLAUDE Context Normalization) -->
### pattern-ir-assembly: PatternIR assembly from a duck-typed ScenarioIR shape, with ordering-convention validation

`dv_harness/pattern_ir_assembly.py` assembles a `PatternIR` -- the `global`/`dut`/`fw_policy`/`vip`/`check` command lists that back a command.txt-shaped pattern -- from a generic, duck-typed ScenarioIR-shaped input, without importing `verification_intent_ir.py` or `vplan_artifact.py` (both owned by a concurrent batch). The five `PatternIR` layers map 1:1 onto `.claude/skills/CORE/pattern-architecture/SKILL.md`'s real vocabulary: `global` = `block`, `dut` = `branch_a*`, `fw_policy` = `branch_fw`, `vip` = `branch_b*`, `check` = verdict/`FINAL_CHECK`.

**What it will not invent.** `global_commands`/`dut_commands`/`fw_policy_commands` are accepted only as caller-supplied, already-evidenced pass-through content -- per `pattern-architecture/SKILL.md` section 5 point 8, that content must come from real DUT RTL/PHY docs, which this module has none of, so it never synthesizes any. The one derivation this module does make -- routing a ScenarioIR item's `stimulus`/`coverage_intent` fields to `vip` and its `checker` field to `check` by default (overridable per item via `layer_overrides`) -- is documented in the module as a stated structural convention, not a claimed fact read off any RTL/VIP source.

**Honest failure over guessing.** An item with none of `stimulus`/`checker`/`coverage_intent` present, a `layer_overrides` value naming an unrecognized layer, a caller-supplied command entry with no text, or a `declared_order` that names an unknown layer, omits one, or duplicates one, is reported into `PatternIR.unclassified` or as `ORDER_STATUS_AMBIGUOUS` -- never silently dropped or defaulted. A `scenario_ir` argument (or a declared items list inside it) whose shape cannot be iterated at all raises `PatternIrAssemblyError` with a distinct `reason` string, rather than being treated as zero items.

**Ordering validation, cited to the skill.** `validate_layer_ordering()` compares a project-declared alternate layer order against `DEFAULT_LAYER_ORDER = (global, dut, fw_policy, vip, check)` -- `pattern-architecture/SKILL.md` section 4's ordering that 'stays fixed in every real instance' -- and reports named, cited risks for deviations matching that skill's load-bearing rules: `GLOBAL_NOT_FIRST`/`DUT_BEFORE_GLOBAL` (block must complete before anything else starts), `FW_POLICY_AFTER_VIP` (branch_fw must launch before any branch_b* that could need it), `CHECK_BEFORE_VIP` (verdict must follow branch_b*'s join). Any other deviation still gets a named-but-generic `LAYER_ORDER_DEVIATION_UNCLASSIFIED` risk rather than silent acceptance. Independently of ordering, it flags section 2's central trap -- `join_any` on the branch_b* fork being safe only while branch_a* never returns on its own -- as `JOIN_ANY_WITH_BRANCH_FW` when branch_fw is known to exist as its own branch (citing the skill's USB job-98520 false-pass regression), `JOIN_ANY_BRANCH_FW_PRESENCE_UNKNOWN` when that fact is genuinely unknown, and `JOIN_ANY_REQUIRES_JUSTIFICATION` even when branch_fw is confirmed absent. `risks` can be non-empty even when the ordering `status` itself is `PASS`/`DEFAULT_ORDER_ASSUMED` -- callers must check `risks`, not only `status`.

Tested by `dv_harness_tests/test_pattern_ir_assembly.py` (20 tests): the positive path assembling a real 2-item enumeration-style fixture into all five layers with correct counts and preserved objective/port traceability; a `layer_overrides` case routing a field to a non-default layer; five negative controls (no-intent-fields item, unknown-layer override, three unrecognized `scenario_ir` shapes, a non-list `items` value, a command entry missing text); and eleven ordering/join-mode tests covering `PASS`/`AMBIGUOUS_DECLARED_ORDER`/`DEVIATION_RISK`, every named risk, and all three presence states of the join_any trap. Run: `python -m pytest dv_harness_tests/test_pattern_ir_assembly.py -q`.


<!-- S095: moved verbatim from CLAUDE.md original lines 5874-5946 (M4.6 CLAUDE Context Normalization) -->
## VIP Capability Extraction: Config / Transaction / Scenario-Pattern / Checker / Coverage IRs (2026-09-06)

`vip_symbol_index.py` already turns a VIP source tree into real class/method/config-field/
analysis-port DECLARATIONS with a real `file:line` each, but by its own docstring's insistence it
is a NAVIGATION aid -- `find_symbol()` answers "where do I read about this name". Nothing in this
repo ever asked the next question a generator or a gap-analysis actually needs answered: of
everything a VIP declares, which classes are its CONFIG objects, which are TRANSACTIONS, which are
reusable SCENARIO PATTERNS, which are CHECKING capability (monitors/scoreboards), and which are
COVERAGE capability -- and, for each answer, how sure are we, on what real evidence.

`dv_harness/vip_capability_extraction.py` is that classifier, reading a REAL `vip_symbol_index`
document (via `vip_symbol_index.build_symbol_index()`/`load_symbol_index()`, called read-only --
never a second indexer) and classifying every indexed class into one of five capability IRs
(`VIPConfigIR`/`VIPTransactionIR`/`VIPScenarioPatternIR`/`VIPCheckerCapabilityIR`/
`VIPCoverageCapabilityIR`) using two heuristics computed directly over that index: a NAMING
heuristic (the class name's final underscore-delimited token against a disjoint suffix table,
asserted disjoint at import) and an INHERITANCE heuristic (the class's real inheritance chain,
walked via `vip_api_card.inheritance_chain()` -- reused, not reimplemented -- against a small,
genuinely unambiguous set of UVM base-class-library markers: `uvm_sequence_item`/`uvm_transaction`
-> transaction, `uvm_sequence`/`uvm_virtual_sequence` -> scenario pattern -- generalizing "a class
extending a known svt_*_sequence base is a scenario-pattern candidate" to any chain that terminates
there, directly or through an intermediate VIP-declared base sequence -- and `uvm_monitor`/
`uvm_scoreboard` -> checker). Config and coverage are deliberately NAMING-ONLY: `uvm_object` is far
too generic a base to distinguish a config object from a callback or a transaction some VIPs build
on `uvm_object` directly, and asserting a marker for it would be exactly the invented specificity
this module exists to refuse.

**Every classified item carries a qualification tag from a closed 5-level vocabulary, reusing
`vip_api_card.py`'s confidence discipline rather than inventing a second, incompatible one**:
`PROJECT_PROVEN` / `VIP_DOCUMENTED` / `VIP_EXAMPLE_MATCHED` / `INFERRED_FROM_NAMING` / `UNKNOWN`.
Every classified item defaults to `INFERRED_FROM_NAMING` regardless of how strongly naming and
inheritance agree (`basis: NAME_AND_INHERITANCE_AGREE` / `NAME_ONLY` / `INHERITANCE_ONLY`) --
promotion to one of the three stronger tags always requires a real cited `file:line` or
document+heading, never the strength of the heuristic match alone: `PROJECT_PROVEN` needs a real
citation of the class in caller-supplied project source (via `vip_api_card.extract_api_citations()`,
reused); `VIP_EXAMPLE_MATCHED` needs the same over caller-supplied VIP `Examples/` source;
`VIP_DOCUMENTED` needs the class name to appear as a real heading in a `<stem>.reference.md` file
`vip_user_guide_distill.distill_user_guide()` already produces (its literal "## Section index"
table only -- never the full-text extract or any prose). Priority when more than one corroborates:
`PROJECT_PROVEN > VIP_DOCUMENTED > VIP_EXAMPLE_MATCHED`.

**When naming and inheritance heuristics DISAGREE, the item is never guessed into either side.** It
is reported separately (`report.ambiguous`, `ir_type: AMBIGUOUS_CAPABILITY_CANDIDATE`,
`qualification: UNKNOWN`) naming both conflicting signals, and it can never be promoted past
UNKNOWN -- corroborating evidence cannot resolve which of two disagreeing categories is correct. A
class matching neither heuristic (e.g. a driver or agent class -- neither is one of the five
tracked capabilities) is counted in `unclassified_class_names`, never forced into one of the five
IRs.

`classify_vip_source(roots, protocol, ...)` calls the REAL indexer over source roots in one step;
`load_index_and_classify(index_path, ...)` classifies an already-built index. Ad hoc:
`python -m dv_harness.vip_capability_extraction --index <index.json> [--project-source ...]
[--example-source ...] [--user-guide-reference-md ...] [--out-dir ...] [--json]` (exit 0 classified
cleanly, 1 an ambiguous candidate is present, 2 NOT_AVAILABLE/nothing classified).

**Deliberately bounded, and stated rather than implied closed.** (1) This is a heuristic classifier
over DECLARATIONS; it proves nothing about behaviour. (2) Coverage classification is naming-only and
structurally weak: `vip_symbol_index` does not index covergroups at all, so a bare `covergroup` block
with no enclosing class is invisible here exactly as it is to the indexer it reads. (3) It decides
nothing beyond classification: no build, no job, no approval, no stage gate, and it weakens no
human-approval gate anywhere.

Proven by `dv_harness_tests/test_vip_capability_extraction.py` (13 tests) against the REAL synthetic
VIP fixture `examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv` (the same fixture
`vip_api_card`'s own tests use): a clean baseline classifies four real classes into their correct IR
types with the correct `basis`, then asserts NOTHING is promoted past `INFERRED_FROM_NAMING` with no
corroboration supplied; each promotion path is then proven individually (including a REAL
`vip_user_guide_distill.distill_user_guide()` run for `VIP_DOCUMENTED`) and combined in one
priority-ordering test. The negative controls carry the detection power: a class whose name says
CONFIG but whose inheritance chain says SCENARIO_PATTERN is reported ambiguous with `UNKNOWN`, never
guessed into either category; a class matching neither heuristic is left unclassified; an empty index
reports `NOT_AVAILABLE`, never a clean pass. Both real CLI paths are driven as real subprocesses.


<!-- S096: moved verbatim from CLAUDE.md original lines 5947-6020 (M4.6 CLAUDE Context Normalization) -->
## New-Command Creation Gate: command_generation_gate.py (2026-09-06)

An agent free to author a new DE command.txt at any time has no incentive to ever reuse one, and a
new command assigned to the wrong branch-ownership tier reproduces exactly the drift
`branch_ownership_resolver.py`'s own header names as a confirmed real incident class. Nothing in
this repo refused command CREATION itself before this -- `.claude/skills/CORE/command-inventory/
SKILL.md` and the Engineering Discipline Rules' "command.txt change-impact check" both require an
EXISTING command change to be checked against the inventory, but neither stopped a brand-new
command.txt from being authored with no reuse check at all.

`tools/verification_flow/command_generation_gate.py` is that refusal point, and it imports two
real, just-built modules rather than re-deriving either judgment: `dv_harness.
existing_command_reuse_score.evaluate_reuse()` (the four-dimension reuse ranking: semantic-name
match, argument-shape compatibility, branch-ownership compatibility, real `evidence_db.py`
regression history) and `dv_harness.branch_ownership_resolver.validate_branch_assignment()` (the
`block`/`branch_a*`/`branch_fw`/`branch_b*` ownership-tier classifier, grounded in
`.claude/skills/CORE/pattern-architecture/SKILL.md` and `.claude/skills/CORE/branch-mapper/
SKILL.md`). REUSE OVER REINVENT applies to this gate's own construction, not only to the command it
judges -- it never re-implements a shred of either module's ranking/classification logic.

**Three conditions, all required, any one failing BLOCKS creation.** (a)
`existing_command_reuse_score.evaluate_reuse()` must report `NO_REUSE_CANDIDATE` for the proposed
command's own declared need against the caller-supplied `existing_commands` inventory --
`REUSE_CANDIDATES_FOUND` BLOCKS naming the exact top candidate that module found, never a ranking
this gate invents. (b) `branch_ownership_resolver.validate_branch_assignment()` must report
`VALID` for the proposed command's declared `branch_layer` against its declared `operation_kind`
(+ `per_port`/`driven_by`/`arbitration_policy`) -- `INVALID` (wrong tier, or non-canonical naming)
and `AMBIGUOUS` (the operation's nature could not be resolved from what was declared) both BLOCK;
an unresolved ownership question is not a lesser finding than a wrong one. (c) The task must be
IMPLEMENTABLE given the evidence actually supplied -- checked by this gate alone, since neither
imported module asks this question: a non-placeholder `implementation_plan`, at least one real
`source_citations` entry, and a `grounding_basis` drawn from the primary-source vocabulary the
Engineering Discipline Rules already name for this command's own RESOLVED ownership tier (VIP
examples/user manual/source/class reference for a VIP-owned command; DUT RTL/PHY documents/
programming guide/register documentation for a DUT/FW/GLOBAL-owned one) -- directly
operationalizing "branch-B / VIP pattern changes: query VIP examples... FIRST" and "branch-A /
branch_fw changes: query DUT RTL source... FIRST" rather than inventing a fourth vocabulary. A
grounding basis for the WRONG tier is treated the same as no grounding at all: citing the wrong
kind of primary source is evidence about a different command, not weaker evidence for this one.

**What it does not do.** It writes no command.txt, picks no reuse candidate, decides no branch
label, runs no build/regression/LSF job, and does not itself verify that a cited source citation is
TRUE -- per the Evidence Truth Rule, it can check that real-looking evidence was cited and is
internally consistent with the declared ownership tier, never that "VIP user guide section 4.2"
actually says what the agent claims. Fabricating a VIP API/class/sequence, RTL content, or
command.txt semantics remains this project's #1 defect risk and is not something a shape check over
agent-typed text can prove or disprove; this gate narrows where an agent is ALLOWED to skip citing
evidence at all, it does not verify the citations themselves.

Standalone-shaped like `assertion_generation_gate.py`/`scoreboard_generation_gate.py` (one real
`dv-harness-evidence:command_generation_gate` payload, `--command-request <file>`, one PASS/BLOCKED/
FAIL verdict, no state written), but registered in `dv_harness/gates.py`'s `STAGE_GATES` under
`COMMAND_PATTERN` alongside `command_migration_integrity_gate` -- new-command creation and existing-
command migration are the same stage's two questions ("should this command.txt exist at all" vs.
"does this command.txt change respect the inventory"). Exit codes: 0 PASS; 3 a malformed/incomplete
payload (`MALFORMED_PAYLOAD`/`MISSING_PROPOSED_COMMAND`/`MALFORMED_EXISTING_COMMANDS`/
`MISSING_OWNERSHIP_DECLARATION`/`MALFORMED_REUSE_NEED`); 4 `REUSABLE_COMMAND_EXISTS`; 5
`BRANCH_OWNERSHIP_NOT_VALID`; 6 `TASK_NOT_IMPLEMENTABLE`; 2 `DEPENDENCY_UNAVAILABLE` (the two
imported modules failed to import -- fails closed rather than silently passing, the same discipline
`waiver_revalidation_gate.py` applies when its own dependency is missing).

Proven by `dv_harness_tests/test_command_generation_gate.py` (15 tests), every one driving the real
script as a subprocess (never an in-process call, never a mock of either imported module): a clean
PASS with an empty existing-command inventory, a second PASS exercising the REAL reuse-score import
against a real (branch-incompatible, correctly excluded) existing command; a real reusable command
found and named as the BLOCKING candidate; a VIP-driven operation wrongly assigned to `branch_a*`
(INVALID, naming `VIP_DRIVEN_WORK_ASSIGNED_TO_BRANCH_A`); an under-specified shared-resource access
that must read AMBIGUOUS rather than guess a tier; a legacy non-canonical branch label
(`ARCH_CONFORMANCE_NAMING_VIOLATION`); missing source citations; a placeholder implementation plan;
a grounding basis for the wrong ownership tier; an unrecognized grounding basis; and three malformed-
payload negative controls (missing `proposed_command`, missing `ownership`, `existing_commands` not
a list). Real output: `python -m pytest dv_harness_tests/test_command_generation_gate.py -q` -> `15
passed`.


<!-- S097: moved verbatim from CLAUDE.md original lines 6021-6075 (M4.6 CLAUDE Context Normalization) -->
## DE Command Task Trace: Four-Leg Declaration-Level Cross-Reference (2026-09-06)

`command-generator/SKILL.md` already declares the traceability chain this repo is supposed to keep --
`REQ -> VP_ID -> SCENARIO -> COMMAND_ID -> HANDLER -> VIP_SEQUENCE -> CHECKER -> COVERAGE ->
TEST/REGRESSION` -- and the CSV shape that is supposed to carry it. Nothing in this repo answered "for
THIS DE command, where in the real generated files does that chain actually land":
`command_migration_integrity_gate.py` checks a declared mapping's own JSON shape and command-catalog
identity, but never opens the generated `.sv`/`.svh`/pattern-text files a HANDLER/CHECKER cell names.
`dv_harness/command_task_trace.py` does exactly that lookup, for one real generated environment
(`env_dir`) at a time, and reports what it actually FOUND -- never what the mapping CLAIMS.

**Four legs, matching this project's own real generated shapes** (confirmed against
`examples/generated_usb_real_evidence_v1/` -- `patterns_registry/dv_uvm_pattern_pool.svh`'s
case-dispatch, `patterns_registry/pattern_list.txt`'s `NAME SUITE FILE` registry rows, and
`bind/dv_uvm_hook.svh`'s real `` `define CPUWRITE1B dv_uvm_cpuwrite1b `` bridge-macro redirect -- not
invented here): **TASK_MACRO** (the command resolves to a real Verilog `task`/`` `define ``, directly,
through a case-dispatch statement, or through a `patterns_registry`-shaped text mapping); **UVM_BRIDGE**
(a real UVM API call or this project's own `dv_uvm_*` bridge-task convention, reached directly or
through one level of `` `define `` redirection); **VIP_API** (a `// VIP:` citation comment -- the real
convention this project's own hand-converted patterns already use -- or, when the caller declares
`vip_prefixes`, an identifier carrying that prefix); **CHECKER** (a `` `*CHECK*(...) `` macro citing
the command or its resolved handler, or a scoreboard/checker/assertion-named file referencing either).

`trace_command()`/`trace_commands()` report a per-command status: `TRACE_COMPLETE` (all four legs
resolved, unambiguously), `TRACE_PARTIAL` (at least one leg absent, or any leg's textual match was
AMBIGUOUS), `BLOCKED` (`env_dir`/command name itself unusable), `NOT_FOUND` (leg 1 found nothing at
all -- there is no command to trace).

**The one rule that matters most: this is a DECLARATION-LEVEL TEXTUAL CROSS-REFERENCE ONLY**, exactly
the bound `uvm_structural_lint.py` already states for its own parser-level checks -- it cannot prove
elaboration-time behavior. `` `ifdef ``/generate conditions are not evaluated, a macro redirect is
followed exactly one level, and two textually-conflicting declarations of the same name (two
`task <cmd>` in two different files, two case-dispatch entries resolving the same command string to two
different handler names) are a genuine ambiguity this analysis cannot resolve -- `_overall_status()`
therefore never reports `TRACE_COMPLETE` while any leg is ambiguous, whatever the other three legs
found. A leg with no evidence is `NOT_FOUND`, never silently upgraded to a guess.

**Reuse, not reinvention.** The real UVM/VIP-body parsing engine in this repo is `verible_parser.py`'s
subprocess wrapper around `verible-verilog-syntax`, and this module imports ONLY that (read-only) --
never `vip_symbol_index.py`, `vip_api_card.py`, or `uvm_structural_lint.py`. Verible is used for exactly
one thing: OPTIONAL enrichment of a single, unambiguous direct `task <cmd>` citation with its real
parsed signature; its absence never blocks a trace, it only means that one enrichment is skipped.

Proven by `dv_harness_tests/test_command_task_trace.py` (22 tests) against small real synthetic
generated-environment fixtures shaped like this project's own real `examples/generated_usb_real_evidence_v1/`
layout, including the real case-dispatch and `patterns_registry` conventions: each of the four legs is
proven both on a clean resolved case and on its own negative control (an absent leg, an ambiguous
double-declaration, a macro redirect followed exactly one level and no further), and `TRACE_COMPLETE` is
proven to never fire while any leg is ambiguous, whatever the other three legs found.

**Disclosed residual**: this closes command-to-generated-file traceability only. It does not run a
build, a simulation, or a gate of its own, and it does not participate in the New-Command Creation Gate
(`command_generation_gate.py`) or any other stage gate -- it is a standalone lookup, callable ad hoc via
`python -m dv_harness.command_task_trace`.


<!-- S098: moved verbatim from CLAUDE.md original lines 6076-6204 (M4.6 CLAUDE Context Normalization) -->
## Verification Architecture IR: VIP/Checker/Scoreboard/Assertion Placement (2026-09-06)

Nothing in this repo answered "is this VIP/checker/scoreboard/assertion placed
where the evidence says it should be" as a single typed record with a real
confidence and a real reason. `env_manifest.py` already captures which VIP is
configured and which release is installed; `connectivity.py` already
4-tier-classifies bind confidence and has planning-entry generators for
protocol checks (`generate_protocol_check_entry()`) and data-integrity
scoreboards (`generate_scoreboard_entry()`); `phy_boundary.py` already decides
at which layer one PHY<->controller boundary may bind. What was missing was
the record that ties a placement decision back to that evidence with an
honest status/confidence, and a comparator that walks a whole subsystem's
worth of those records looking for a placement that contradicts the evidence
it was built from.

`dv_harness/verification_architecture.py` is that layer: 5 typed IRs
(`VipSelectionIR`, `VipBindIR`, `ScoreboardIR`, `CheckerIR`, `AssertionIR`),
each an EXTENSION of an existing producer's own dict shape (the original dict
is kept verbatim as `raw`; new typed fields sit alongside it) plus a common
`status`/`confidence`/`source_evidence` trio. Confidence is
`inference.CONFIDENCE_LEVELS` (HIGH/MEDIUM/LOW) plus one honest addition,
UNKNOWN ("no evidence to grade this record") -- never a second confidence
vocabulary, per the same discipline `test_confidence_vocabulary_separation.py`
already holds `connectivity.classify_bind_tier()` and `question_queue.
classify_tier()` to.

- **VipSelectionIR** extends one `env_manifest.build_vip_config()`
  `vip_instances` entry with the bind-tier evidence a caller already computed
  (`connectivity.classify_bind_tier()`, accepted duck-typed so this module
  never re-derives a tier of its own) and the matching installed-package
  version from `env_manifest.build_vip_release()`.
- **VipBindIR** extends the existing bind-entry shape
  (`target_instance`/`ports`/`reason`/`tier`, the same shape
  `connectivity.enforce_bind_tier_policy()` already validates) with a
  `phy_boundary.decide_bind_location()` boundary decision and a NEW
  wrapper/bridge CHAIN classification: `derive_wrapper_bridge_chain()` walks a
  caller-declared hop list and classifies each hop WRAPPER (a clean single-kind
  boundary on both sides -- a passthrough) or BRIDGE (a MIXED boundary --
  `phy_boundary.classify_boundary()`'s own documented "typical of a
  bridge/wrapper module" shape) or UNCLASSIFIED (no evidence -- never guessed
  from a name, extending Bind-Location Rule 5's naming-evidence discipline
  from one boundary pair to a whole chain).
- **CheckerIR** extends `connectivity.generate_protocol_check_entry()`'s
  `protocol_check` shape with a caller-declared link to the bind target it
  watches and which side of a bridge (if any) it mounts on.
- **ScoreboardIR** extends `connectivity.generate_scoreboard_entry()`'s
  `data_integrity_scoreboard` shape (including its real `unfilled_fields` via
  `unfilled_plan_fields()`) with `assess_scoreboard_comparability()`: `False`
  ONLY when real `phy_boundary`-derived boundary-kind evidence for the two
  endpoints actually disagrees; `None`/UNKNOWN with no boundary evidence
  supplied -- never a guessed `True`.
- **AssertionIR** has no pre-existing producer to extend, so its `raw` is the
  caller-supplied candidate itself (this module authors NO assertion content,
  per No Golden-Reference Content Mining). Its `clock_domain_match`/
  `reset_domain_match` are checked against the real
  `env_manifest.build_dut_facts_clock_reset()` clock/domain map; when that
  layer is not LOADED both are honestly `None`, never a claimed match.

`detect_placement_conflicts()` derives all six required conflicts purely from
already-computed IR fields: **VIP_AFTER_BRIDGE** (a VIP instance path under a
bind target whose chain crosses a bridge), **CHECKER_WRONG_SIDE_OF_BRIDGE** (a
checker declaring `mount_side=PRE_BRIDGE` for a target whose chain already
shows `BRIDGE_IN_PATH` -- a checker mounted AT the target can only observe the
POST_BRIDGE side), **ASSERTION_WRONG_CLOCK_DOMAIN** /
**WRONG_RESET_DOMAIN** (AssertionIR's own real domain-match verdict),
**SCOREBOARD_INPUTS_NOT_COMPARABLE** (ScoreboardIR's own comparability
verdict), **DUPLICATE_ACTIVE_VIP** (two selections sharing one instance path
where neither is affirmatively PASSIVE -- two passive monitors sharing a path
is not flagged). `detect_intra_subsystem_duplicates()` adds the intra-subsystem
duplicate check: **VIP_CHECKER_DUPLICATES_SVA** (a checker's own enabled
built-in check name matches an assertion's declared `checked_property` on the
same target), **SCOREBOARD_DUPLICATES_CHECKER** (a data-integrity-named
checker and a scoreboard share an endpoint), **DUPLICATE_SCOREBOARD_PATH** (two
scoreboards declare the identical endpoint pair).

Five rendering functions produce the required output matrices (VIP Bind,
Interface-to-Verification, Function-to-Checker, Assertion Placement,
Scoreboard Architecture), all through `connectivity.render_markdown_table()`
-- the repo's one parameterized markdown-table renderer; no second one was
added. `assemble_verification_architecture()` is the one-call entry point
producing all five IR lists, both comparators, and all five matrices, and
`validate_verification_architecture()` checks the result against
`dv_harness/schemas/verification_architecture.schema.json`.

**Deliberately bounded, and stated rather than implied closed.** (1) This
module imports only `inference.py`/`connectivity.py`/`phy_boundary.py` --
stable modules outside both this task's own 23-agent batch and the
separately-running 12-agent batch. Several real facts a fuller pipeline would
supply (hierarchy hops between a DUT top and a bind target, which checker
mounts on which side of a bridge, which VIP instance is ACTIVE vs PASSIVE) are
accepted as plain caller-supplied dicts, never pulled from another
concurrently-built module's output; a future richer hierarchy-walk producer
(e.g. a `subsystem_contract.py`) could supply `chain_by_target` directly
without this module importing it. (2) It authors NO VIP API, RTL content, or
assertion/scoreboard/checker CONTENT -- it only assembles and cross-checks
PLACEMENT metadata a caller already declared or a real producer already
computed. (3) `assess_scoreboard_comparability()` and the wrapper/bridge chain
classifier are conservative by construction: absent evidence is UNKNOWN, never
guessed comparable/wrapper. (4) There is deliberately no stage gate registered
in `gates.py` by this task -- the 3 standalone generation gates below are
independent scripts an integrator wires in.

Three STANDALONE generation gates (not registered in `gates.py`), each
checking one IR list's completeness before its generation step may proceed:
`tools/verification_flow/vip_bind_generation_gate.py` (every `vip_bind` record
`status: RESOLVED` and not named by a `VIP_AFTER_BRIDGE` finding),
`scoreboard_generation_gate.py` (every `scoreboard` record `status: RESOLVED`,
no `unfilled_fields`, `comparable` not `false`), `assertion_generation_gate.py`
(every `assertion` record `status: RESOLVED`, `clock_domain_match`/
`reset_domain_match` not `false`). Same file shape as
`assertion_placeholder_closure_gate.py` (argparse, one JSON arg, one JSON
status line, non-zero exit on FAIL).

Proven by `dv_harness_tests/test_verification_architecture.py` (42 tests)
against REAL producer output throughout: a real `vip_config_dump.json` parsed
by `env_manifest.build_vip_config()`, a real synthetic `$DESIGNWARE_HOME` tree
scanned by `build_vip_release()`, a real `soc_arch_map.json` loaded by
`build_dut_facts_clock_reset()`, a real synthetic PHY/controller port table
classified by `phy_boundary.classify_boundary()`/`decide_bind_location()`
(including a genuine MIXED/bridge boundary), and real
`connectivity.classify_bind_tier()`/`generate_protocol_check_entry()`/
`generate_scoreboard_entry()` calls. Every one of the six placement conflicts
and three intra-subsystem duplicates has both a positive detection test and a
negative control (wrong VIP location elsewhere, correct bridge side, agreeing
boundary kinds, PASSIVE-only duplicates, differing checked properties,
differing endpoints) proving the comparator does not over-fire. The three
standalone gates are driven as real subprocesses to both PASS and FAIL.



<!-- S100: moved verbatim from CLAUDE.md original lines 6217-6235 (M4.6 CLAUDE Context Normalization) -->
### Design Source Inventory -- registry table + discovery-order (2026-09-06)

**Gap.** No source-registry table existed anywhere in this codebase: nothing recorded, per design source, its type/version/content hash/authority tier/freshness status in one place. Grep for `source_id`/`SOURCE_REGISTRY`/`DISCOVERY_ORDER` found zero hits before this closure.

**What's new -- `dv_harness/design_source_inventory.py`.**
- A registry row shape `{source_id, type, version, hash, authority, status, last_checked}` built by `evaluate_source()`/`build_source_registry()`, accepting `SourceEntry` or a plain duck-typed dict per source.
- Status vocabulary: the task's three (`CURRENT`/`STALE`/`SUPERSEDED`) plus two honest additions the evidence-truth rule requires (`NOT_AVAILABLE` -- path missing/unreadable; `UNKNOWN` -- no recorded_hash yet to compare against). Decided worst-first: SUPERSEDED (explicit `superseded_by`) > NOT_AVAILABLE > UNKNOWN > CURRENT/STALE by real sha256 content-hash comparison (own `_sha256_file`/`_sha256_tree`, modeled in spirit on `signoff_export.compute_bundle_hash()`'s manifest-hash shape and `golden_scenario.evaluate_freshness()`'s worst-wins structure -- neither imported). This module persists no snapshot itself; `recorded_hash`/`superseded_by` are caller-supplied from whatever owns the last inventory run.
- Authority tier is resolved **by import only** against `source_authority.authority_source()`/`authority_rank()` (that module is unedited). A source with no `authority_hint`, or an unresolvable one, reports `NOT_APPLICABLE` with a real reason rather than a forced/guessed tier -- not every discovery kind (e.g. `ask_user`, `git_history`) sits on the 9-tier conflict-resolution axis at all.
- A new, explicitly-distinct **DISCOVERY-order** table, `DISCOVERY_ORDER` (10 kinds: repo files on disk, existing UVM environment, build scripts/Makefile, RTL/PHY source, register files, specs/datasheets, VIP examples, regression lists, git history, ask the user) and `discovery_check_order(fact_name, available_kinds)`, answering "which kind of source to check first for a fact not yet known" -- a THIRD mechanism alongside `source_authority.AUTHORITY_ORDER` (conflict resolution) and `tools/verification_flow/evidence_source_priority_gate.py`'s `ORDER` (a coarser 9-item discovery list for that tool's own trace-validation use case), with the three-way distinction spelled out in the module docstring rather than left implicit, mirroring how `source_authority.py` already documents its own near-collision with the gate module.

**Deliberately NOT covered (bounded, disclosed).** No repo-walking/source-discovery scanner (callers supply `path`); no snapshot persistence (recorded_hash/superseded_by are caller-supplied each call); no forcing of every discovery kind onto an authority tier.

**Reused, not reinvented.** `source_authority.authority_source()`/`authority_rank()` (import only, unedited).

**Real test proving it.** `dv_harness_tests/test_design_source_inventory.py` (24 tests, `python -m pytest dv_harness_tests/test_design_source_inventory.py -q` -> `24 passed`): DISCOVERY_ORDER shape/filtering, authority resolution matching `source_authority` directly, sha256 hashing verified against raw `hashlib`, plus five negative controls -- mutated content must not read CURRENT, a missing recorded_hash must not read CURRENT, a missing path must not read CURRENT/STALE, a superseded source must not read CURRENT even on a hash match, and unknown-kind/empty-field inputs must raise rather than silently pass.

**Suggested CLI verb (for the integrator; not added here):** `dv-harness design-source-inventory --sources <sources.json> [--snapshot <prior_registry.json>]` -> prints `build_source_registry()`'s JSON, exit 1 if any row is `STALE`.



<!-- S101: moved verbatim from CLAUDE.md original lines 6236-6280 (M4.6 CLAUDE Context Normalization) -->
## Requirement Contract: Ambiguous-Language Detection + Cross-Source Contradiction (2026-09-06)

`dv_harness/requirement_contract.py` gains two purely-additive checks on top of its existing
`derive_status()`/`STATUS_OVERCLAIMED`/`UNRESOLVED_BLOCKER_HIDDEN` machinery (read first, unchanged
by this addition; no existing field, status value, or precedence rule changed meaning).

**(a) Ambiguous-language detector.** `detect_ambiguous_language(text)` matches a real word list
(`AMBIGUOUS_LANGUAGE_PHRASES`: normally, typically, generally, usually, as needed, as appropriate,
appropriate, should generally, in most cases, in some cases, as applicable, if necessary, where
applicable, under normal conditions, reasonable, roughly, approximately, etc., and so on, and the
like, or similar) against `expected_result`/`checker` text, case-insensitively, longest phrase first
so "should generally" is cited whole rather than shadowed by "generally". This is a DIFFERENT fact
from the existing `ambiguities` array: that array records an ambiguity someone already FILED; this
finds hedging prose that reads as resolved but nobody filed yet. It surfaces as a new
`AMBIGUOUS_LANGUAGE_DETECTED` WARNING in `analyze_requirement_contract()`, citing the matched
phrase and field -- it does NOT feed `derive_status()`, so a requirement's status is unaffected
until a human/agent files it as a real `ambiguities` entry (the existing, unchanged path to
AMBIGUOUS).

**(b) Cross-source contradiction.** `cross_source_contradictions(records)` groups contract-shaped
records by `feature` (this schema's closest analogue to a cross-document spec_ref) and, for every
pair sharing one, compares `expected_result`/`configuration` on resolved, stripped/casefolded text.
A genuine disagreement is a new `CROSS_SOURCE_CONTRADICTION` WARNING in
`analyze_requirement_contract_set()`, alongside the existing DUPLICATE_REQUIREMENT_ID check --
duplicate ids are one identity colliding; this is two different ids making incompatible claims. It
never mutates a record and never writes into either record's own `contradictions` array: filing a
contradiction stays a human/producer act, the same ARBITRATION boundary this module already keeps.

**Deliberately additive, not a redefinition.** Both new findings are WARNING severity, so
`downstream_consumable()` (which counts only ERROR findings) is unaffected, and a requirement's
declared/derived status is unaffected until filed as a real `ambiguities`/`contradictions` entry.
No CLI or gate change was needed: both functions are consumed through the existing
`analyze_requirement_contract()`/`analyze_requirement_contract_set()` entry points already called by
`dv-harness requirement-contract` and by `tools/verification_flow/spec_to_vplan_requirement_quality_gate.py`
(untouched), so the new findings surface automatically.

Proven by 24 new tests in `dv_harness_tests/test_requirement_contract.py` (120 total, up from 96),
following the file's existing mutation-driven discipline: phrase detection/citation, the
longest-phrase-wins de-dup rule, a "status/consumability unchanged" proof, the
placeholder-vs-hedging-language distinction; agreeing/disagreeing feature pairs, case/whitespace
insensitivity on both the feature key and the cosmetic-difference check, unresolved-field
exclusion, single-record/legacy-record non-participation, a 3-way group's every pairwise
disagreement, and a no-mutation/no-auto-filing proof. The full pre-existing 96-test suite was run
unchanged first (all pass) before any new test was added.


<!-- S102: moved verbatim from CLAUDE.md original lines 6281-6344 (M4.6 CLAUDE Context Normalization) -->
## Requirement-to-RTL Evidence Correlation (2026-09-06)

A requirement can NAME a DUT-facing fact -- an interrupt, a clock/reset signal, a mode, a feature --
and nothing in this repo checked whether that name corresponds to anything the DUT actually has.
`env_manifest.py` already assembles exactly the facts needed to answer that (RTL ports/signals/
parameters via `verible_parser.to_dict()`, registers/fields via the register-map input contract,
clocks/resets and address regions via the SoC-arch-map input contract); `dv_harness/dut_evidence_
correlation.py` reads that assembled manifest, read-only through the existing `env_manifest.
load_env_manifest()`, and does the join. It parses nothing itself -- there is no second RTL parser,
register-map reader or SoC-arch-map reader here.

**Input is deliberately duck-typed**, per this batch's file-safety scope: a declared fact is a plain
dict (`item_id`/`fact_type`/`name`, optional `aliases`/`expected`) rather than an import of
`requirement_contract.py`'s `RequirementContract`, even though that module already exists in this
repo. A caller sitting on a real, schema-validated, COMPLETE `requirement_contract` record builds
this module's `items` list from that record's own `feature`/`protocol`/`precondition`/`observability`
text -- this module does not parse that prose itself, the same "transcription, never extraction from
scratch" boundary `doc_extraction_fanout.py` already states for 40d/40e/40f.

**Five-status verdict, never collapsed**: `RTL_CONFIRMED` (an exact name match in an available
layer, no attribute disagreement), `RTL_CONTRADICTS_SPEC` (an exact match, but a declared attribute
-- active_level, frequency_mhz, direction, access, width, reset_value, base_address, bus,
synchronous -- disagrees with the manifest's real recorded value; this module reports the
disagreement and arbitrates nothing, the same boundary `requirement_contract.py` keeps for a
CONTRADICTORY requirement), `RTL_PARTIAL` (a case-insensitive substring match only -- a plausible,
unproven correspondence), `RTL_NOT_FOUND` (every layer relevant to the fact_type was available and
searched; a real negative), `NOT_AVAILABLE` (every relevant layer was itself NOT_AVAILABLE, or
`env.manifest.json` does not exist at all -- per the Evidence Truth Rule this is never conflated with
RTL_NOT_FOUND: "we looked and it is not there" and "we could not look" are different claims).

**Evidence is cited from what the upstream producer actually recorded, never fabricated.** RTL ports/
signals/parameters and register/field entries carry no source line anywhere upstream
(`verible_parser.to_dict()`'s dataclasses and `register_map.schema.json` record name/type/access
only), so this module cites the real file path plus a structural locator (module/port,
block/register/field) instead of inventing a line number neither producer recorded. Where the
upstream fact DOES carry a real evidence string with a line (`clock_reset`'s clocks/resets and
`address_map`'s entries, sourced from `soc_arch_map.schema.json`'s own `evidence` field), that string
is cited verbatim.

**Deliberately bounded, and stated rather than implied closed.** (1) Matching is name-based
(exact / case-insensitive substring) only, never semantic -- no fuzzy edit-distance, no synonym
table; a caller must supply the RTL-shaped name as `name` or an `alias`. (2) It decides nothing
beyond the verdict: no build, job, approval, stage gate, or memory write -- it reads
`env.manifest.json` once, read-only. (3) An unrecognised `fact_type` is never rejected or silently
narrowed -- it searches every `dut_facts` layer (the same breadth as "feature") and the report
carries a warning naming the unrecognised value. (4) It is REACHED, not WIRED: there is no
`dv-harness` CLI verb yet (front door is `python -m dv_harness.dut_evidence_correlation`), no
`run_stage()`/`advance()` call site invokes it, and no graph node declares it.

Proven by `dv_harness_tests/test_dut_evidence_correlation.py` (20 tests) against a real,
schema-valid `env.manifest.json` built through the real `env_manifest.generate_and_write()` over a
real verible-parsed RTL fixture, a real register-map JSON and a real soc-arch-map JSON -- nothing
hand-written. Positive path: exact RTL port / clock+reset / register+field matches, and an alias
resolving a name the RTL does not literally carry. Negative controls, each proven rather than
asserted: a fabricated name reads RTL_NOT_FOUND; a mutated reset polarity, clock frequency and
register access each read RTL_CONTRADICTS_SPEC naming expected-vs-actual; a substring-only match
reads RTL_PARTIAL and is never upgraded; a missing manifest file and a `None` path both report
NOT_AVAILABLE for every item; a manifest whose relevant layers are honestly NOT_AVAILABLE is
distinguished from a real RTL_NOT_FOUND; a malformed item raises `DutEvidenceCorrelationError`; an
invalid on-disk manifest propagates `env_manifest.EnvManifestValidationError` rather than being
swallowed. Both the module's Python API and its CLI subprocess entry point (exit 0/1/2) are driven
end to end.



<!-- S103: moved verbatim from CLAUDE.md original lines 6345-6423 (M4.6 CLAUDE Context Normalization) -->
## vPlan Freeze / Baseline: a Second Freeze, One Shared Vocabulary (2026-09-06)

`signoff_export.py`'s section-238 baseline names fifteen project-wide identity fields but none
of them is specifically about the vPlan/requirement/configuration triad a vPlan-focused freeze
needs: which spec version a vPlan was written against, which version of the section-184
Canonical Requirement Contract fed it, which configuration-variant IR it was planned over, and
exactly which vPlan items (by count and content) existed at freeze time. `grep -rn
"vplan.*freeze\|freeze.*vplan" --include=*.py .` matched nothing before this change --
`signoff_export.py`'s own freeze covers a whole project's signoff evidence, not a vPlan
document's own identity.

`dv_harness/vplan_baseline.py` mirrors `signoff_export.py`'s content-hash freeze/invalidation
PATTERN -- worst-wins, "we could not check" is never VALID -- scoped to four vPlan-specific
fields instead of section 238's fifteen: `spec_version` (the vPlan document's own
`spec_revision`, or a human-declared attested value), `requirement_ir_version` (content identity
over records `requirement_contract.declares_contract_shape()` confirms are genuinely in the
section-184 contract shape), `configuration_ir_version` (content identity of a caller-named
configuration-IR JSON document), and `vplan_items` (item count plus a content-hash aggregate
keyed by `req_id`/`item_id`).

**Reuse, not reinvention.** Every multi-item digest goes through the real
`tools/remote/source_identity.aggregate_source_id()`, reached the same way
`signoff_export._aggregate()` reaches it (`from .harness_deploy import aggregate_source_id`) --
there is no second hashing scheme. The freeze vocabulary (`CAPTURED`/`NOT_AVAILABLE`/
`FREEZE_VALID`/`FREEZE_INVALIDATED`/`FREEZE_UNKNOWN`/`SEV_INVALIDATING`/`SEV_INDETERMINATE`/
`MATERIAL_CHANGE_RISKS`) is IMPORTED directly from `signoff_export.py`, never re-typed --
`signoff_export.py` itself is untouched, so a freeze verdict means the same three words whether
it names a vPlan baseline or a whole-project signoff baseline. Post-freeze impact analysis reuses
the same `change_impact.changed_files()`/`classify_risk()`/`resolve_sha()` chain
`signoff_export.evaluate_freeze_invalidation()` and `golden_scenario.evaluate_freshness()`
already use, so "did the project move since this was frozen" has ONE answer across every freeze
mechanism in this codebase.

**Deliberately NOT imported: `config_variant_coverage.py`.** At write time it was under
concurrent edit by a separate batch of agents, so `configuration_ir_version` accepts a generic,
duck-typed JSON document (any project's configuration-variant IR, whatever produced it) and
hashes its real content rather than validating its internal legality (no dimension/constraint/
critical-combination checking -- that stays `config_variant_coverage.py`'s job). A caller may
later validate the same file through `config_variant_coverage.load_config_space()` before naming
it here; this field would then simply be hashing an already-validated document, with no change
needed in this module.

**Unlike `signoff_export`'s fields, none of the three input files has a fixed conventional path
under a project root** -- a vPlan/requirement-IR/configuration-IR file can live anywhere a caller
names it. The frozen record therefore carries the EXACT paths supplied at capture time, and
re-derivation at evaluation time re-reads those same paths; a file that moved or vanished since
the freeze is exactly a `BASELINE_EVIDENCE_DISAPPEARED` finding, never a silent re-pointing at a
different file. Freeze records live at `.dv-harness/vplan_baseline/freezes/<freeze_id>.json` --
deliberately NOT inside `.dv-harness/vplan/`, which `signoff_export.collect_signoff_bundle()`
already copies wholesale into a signoff bundle.

**Deliberately bounded, and stated rather than implied closed.** (1) This module DECIDES and
ARBITRATES nothing: no stage runs, no gate is invoked, no build/regression/LSF submission
starts, and there is deliberately no stage gate. (2) `configuration_ir_version` is a content-
identity field only -- it validates nothing about a configuration space's legality. (3) No
`dv-harness` CLI verb exists yet; the front door is `python -m dv_harness.vplan_baseline
fields|baseline|freeze|list|status`, the same `execute_verb()` convention `signoff_export`/
`power-intent`/`golden-scenario` already follow.

Proven by `dv_harness_tests/test_vplan_baseline.py` (27 tests) against a REAL throwaway git
repository with real commits, a real vPlan JSON document, a real requirement-contract-shaped
records file, and a real configuration-IR JSON document -- nothing mocked. The central proofs are
that a field-content change invalidates independently of git (naming exactly the changed field,
with the frozen record on disk byte-unchanged) and that a real git commit of a HIGH-risk RTL file
invalidates independently of field content -- proving the two invalidation mechanisms fire on
their own. A negative control proves a project with no recorded git HEAD reads `FREEZE_UNKNOWN`,
never `FREEZE_VALID` -- "we could not check" is never a pass. A reuse-proof test independently
reconstructs the `vplan_items` manifest and feeds it to a freshly-loaded copy of
`tools/remote/source_identity.py`, asserting byte-identical digests. An AST-based test proves no
`import`/`from ... import` node anywhere in the module names `config_variant_coverage`.

If a `dv-harness` CLI verb is added, the suggested entry (not wired by this change) is:

```python
elif args.cmd == "vplan-baseline":
    from dv_harness.vplan_baseline import execute_verb
    sys.exit(execute_verb(args.rest))
```


<!-- S104: moved verbatim from CLAUDE.md original lines 6424-6483 (M4.6 CLAUDE Context Normalization) -->
## Spec-to-vPlan Transform Quality Gate (2026-09-06)

`tools/verification_flow/spec_to_vplan_quality_gate.py` is a new standalone STAGE_GATES script,
deliberately separate from `spec_to_vplan_requirement_quality_gate.py`. That gate checks PER-
REQUIREMENT completeness (five required fields on one requirement record, plus its own
`contract_schema_version`/`requirement_contract.py` layer for records that opt into the richer
15-field contract). Nothing in this repo checked the SPEC-TO-VPLAN TRANSFORM as a whole -- whether
the set of vPlan items an agent produced from a spec actually covers that spec, and whether every
contradiction/ambiguity the agent itself flagged while doing that transform was actually closed
rather than quietly dropped. This gate is that check, and only that check.

Evidence shape (all keys optional; absent reads as empty): `spec_items[]` (`spec_id`,
`criticality`), `vplan_items[]` (`vplan_id`, `traces_to: [spec_id, ...]`), `contradictions[]` and
`ambiguities[]` (`*_id`, `description`, `resolved`/`resolution`/`open_question`). Four rules,
checked in this priority order (most severe first -- a run carrying several kinds of defect
reports its worst one as `reason`, while `findings` still names every kind found in one pass):

1. **zero-critical-omission** -- a P0/BLOCKER/CRITICAL spec item with no `vplan_items[].traces_to`
   entry naming it is `CRITICAL_OMISSION` (exit 3). Criticality is what makes this stronger than an
   ordinary traceability gap: the point of flagging it critical is that it may not merely be noticed
   later.
2. **zero-unresolved-contradiction** -- a filed contradiction with no `resolved: true`, no real
   `resolution` text, and no named `open_question` is `UNRESOLVED_CONTRADICTION` (exit 4). This gate
   never decides which side of a contradiction is correct -- arbitration stays a human/source-
   authority decision, the same boundary `source_authority.py` and `requirement_contract.py` already
   keep between detecting a conflict and resolving it -- it only refuses to let one pass silently.
3. **zero-unresolved-ambiguity** -- the identical shape over `ambiguities[]`, the same
   "resolution/open_question, or FAIL" discipline `spec_to_vplan_requirement_quality_gate.py`
   already applies per-requirement, applied here across the whole vPlan.
4. **zero-traceability-gap** -- everything else the spec<->vplan mapping leaves open: a
   non-critical spec item nobody traced to, a vPlan item whose `traces_to` is empty, or a vPlan
   item's trace target naming a `spec_id` that does not exist in `spec_items[]` at all (a dangling
   reference, never trusted as a real link).

`spec_items` empty (or absent) reports `NO_SPEC_ITEMS` (exit 2) rather than a vacuous PASS -- there
is nothing to check omission or traceability against. Non-dict entries in any list are skipped
rather than crashing the gate.

**Deliberately bounded.** This is a pure structural/consistency check over the fields the agent
supplies, the same discipline every sibling script in this directory follows (e.g.
`coverage_quality_gate.py`): it proves the SET the agent produced is internally coherent -- every
critical spec item covered, every filed contradiction/ambiguity actually closed, every trace target
real -- not that any individual spec/vplan claim is true against a real specification document or
DUT. No spec text, requirement content, or VIP/RTL behavior is invented or read here, and it decides
and arbitrates nothing beyond reporting.

Proven by `dv_harness_tests/test_spec_to_vplan_quality_gate.py` (14 tests) driving the gate as a
REAL subprocess: one clean fully-covered payload passes with zero findings, then each of the four
rules is driven by MUTATING that same clean payload one defect at a time (plus NO_SPEC_ITEMS,
priority ordering under simultaneous defects, an alternate resolution path, malformed-entry
graceful-skip, and output determinism), so each assertion proves that rule caught that specific
injected defect.

**Not yet wired into `gates.py`'s `STAGE_GATES`** -- that edit is left for the integrator. The
entry fits the `VPLAN` stage, alongside `spec_coverage_audit` and `vplan_writer_validation_gate`:

```python
("spec_to_vplan_quality_gate", "spec_to_vplan_quality_gate.py", "--vplan-quality"),
```


<!-- S105: moved verbatim from CLAUDE.md original lines 6484-6546 (M4.6 CLAUDE Context Normalization) -->
## Coverage Hole Taxonomy: 12 Categories + Per-Hole Evidence Citation (2026-09-06)

`coverage_analysis.classify_coverage_hole()` answers exactly one question -- which of 4 ROOT
CAUSES (MISSING_TEST / INSUFFICIENT_CONSTRAINT / UNREACHABLE_STIMULUS /
INSUFFICIENT_SEED_ATTEMPTS) explains an uncovered bin -- and is left completely untouched by this
change: nothing renames, removes, or reroutes those 4 values, and the function itself is not
edited. What was missing is a wider vocabulary for the STRUCTURE of the hole itself: is this even a
real open gap (an illegal/ignore bin misreported as one), a cross-coverage combination whose
individual axes are both already covered, specific to one configuration, a timing/transition
window, a register bitfield combination, already carved out by an on-record waiver, or corroborated
(or contradicted) by a real recorded golden-scenario PASS -- and nothing cited, per hole, the real
evidence source behind whichever classification was reached.

`classify_coverage_hole_taxonomy()` runs `classify_coverage_hole()` first, byte-for-byte unchanged
(embedded as `root_cause_verdict`), and only ADDS a widened classification on top, falling back to
that exact base verdict (named, never silently dropped) whenever none of 8 new categories' real
declared evidence is present. Precedence, most structurally certain first: `ILLEGAL_BIN_
MISCLASSIFIED_AS_HOLE` (a data-quality override -- the hole's own `bin_kind` names an illegal/ignore
bin, so it is not a real gap at all) > `WAIVED_HOLE_EXCLUDED` (reuses the exact `hole["waived"]`
field `escalate_unreachable_holes()` already reads) > `REGISTER_FIELD_COMBINATION_HOLE` (a declared
register name plus >= 2 field names) > `CROSS_COVERAGE_ONLY_UNCOVERED` (declared `cross_axes` whose
individual categories are each already >= threshold in the real `parse_coverage_summary()` output
the caller supplies as `parsed_summary`) > `TIMING_WINDOW_HOLE` (a transition `bin_kind` or a real
`timing_window_ns`) > `CONFIG_SPECIFIC_HOLE` (`hit_in_configs` a real, non-empty, PROPER subset of
`legal_configs`) > `GOLDEN_SCENARIO_STALE_EVIDENCE_HOLE` (a real `golden_scenario` capsule recorded
for a linked pattern -- via the existing `patterns_for_coverage_id()` -- whose
`evaluate_freshness()` reports STALE against current git HEAD) > `NO_GOLDEN_SCENARIO_EVIDENCE_
FOR_LINKED_PATTERN` (base root-cause is INSUFFICIENT_CONSTRAINT/UNREACHABLE_STIMULUS but no golden
capsule was EVER recorded for any linked pattern, so that expensive claim carries no corroborating
verified-PASS history). None of the 8 fires without the hole record (or the coverage tool that
produced it) declaring the specific real field each one needs -- an absent field is honestly "does
not apply", never a guess.

`build_hole_evidence_record()`/`build_hole_evidence_records()` are the citation half: one record per
hole naming, for whichever classification was reached, the REAL source it came from -- always
`requirements_registry` (`patterns_for_coverage_id()`) and `evidence_db.jobs`
(`count_seed_attempts()`/`seed_history_available()`, the same tally the base verdict already
computed), plus whichever `hole_declared_field` / `coverage_summary.categories` / `golden_scenario`
citation the fired rule used. An `evidence` list carrying only the two universal entries is a
legitimate, honestly-reported result (fell back to the base verdict with no additional evidence),
not a failure to look.

**Deliberately bounded.** This module still parses no real UCIS/urg coverage database (unchanged
scope, stated in the module's own top-of-file docstring): every new category is derived from a
field the hole record (or whatever coverage tool produced it) itself declares, never invented from a
`coverage_id` string. `CROSS_COVERAGE_ONLY_UNCOVERED` additionally needs the caller to supply
`parsed_summary` (a real `parse_coverage_summary()` result); without it, that category never fires.
Reuses `golden_scenario.load_golden_scenarios()`/`evaluate_freshness()` and `evidence_db.
EvidenceStore` exactly as the module's pre-existing `count_seed_attempts()`/`seed_history_
available()` already do -- read-only, degrading to an honest empty/None result (never raising) when
no evidence DB or `golden_scenarios` table exists. No CLI verb or `gates.py` `STAGE_GATES` entry was
added; none was requested and `gates.py`/`cli.py` were not touched.

Proven by `dv_harness_tests/test_coverage_analysis.py` (42 tests total: the original 21 untouched
plus 21 new). Each of the 8 categories has a positive test plus a negative control (a
register-field hole with only 1 field, a cross-axis hole whose axis is not fully covered, a
cross-axis hole with no `parsed_summary` at all, a config hole hit in every legal configuration, a
config hole whose "hit" set is not even a subset of "legal", and illegal-bin precedence winning over
a simultaneous `waived` flag). Two tests drive a REAL throwaway git repo, a real `EvidenceStore`, a
real `vip_distill.distill_sim_log()` envelope and a real `golden_scenario.record_golden_scenario()`
capsule, proving `GOLDEN_SCENARIO_STALE_EVIDENCE_HOLE` fires only after a real RTL commit inside the
capsule's watched paths and not before.


<!-- S106: moved verbatim from CLAUDE.md original lines 6547-6623 (M4.6 CLAUDE Context Normalization) -->
## Cross-Subsystem Coverage IR: Boundary Resolution on Top of the Real 6-Value Taxonomy (2026-09-06)

`dv_harness/cross_subsystem_coverage_ir.py` answers a coverage-hole question the existing system
taxonomy never asked: verified first, not assumed -- a repo-wide grep for
`cross_subsystem_coverage`/`CrossSubsystemCoverageIR` found nothing, and
`system_failure_taxonomy.classify_system_coverage_hole()` already ships the real, tested 6-value
system coverage-hole taxonomy this item names verbatim (`SUBSYSTEM_GAP`/`INTEGRATION_GAP`/
`RESOURCE_GAP`/`SCENARIO_GAP`/`ERROR_PATH_GAP`/`COVERAGE_MODEL_GAP`, plus the honest
`UNCLASSIFIED_COVERAGE_HOLE` fallback), including its own priority-ordered classification and its
own scope/`subsystem_ids` reading. A second grep (`classify_system_coverage_hole`) confirmed no
other module in this project had ever called it -- the only prior reuse of
`system_failure_taxonomy.py` is `rca_ontology.py`'s disjointness check against its DIFFERENT
`FAILURE_CATEGORIES` vocabulary, a different axis entirely. So `classify_system_coverage_hole()`
already tells a caller a hole's CATEGORY, including whether its own declared scope makes it
cross-subsystem, but it answers that per-HOLE, in isolation: it never says WHICH specific pair(s)
of subsystems a cross-subsystem hole actually spans, and it never rolls several holes up onto a
per-BOUNDARY view.

**REUSE OVER REINVENT, applied literally -- this module invents no second coverage-hole-category
vocabulary.** `classify_cross_subsystem_hole()` calls `classify_system_coverage_hole()` for every
hole's category verbatim (`COVERAGE_HOLE_CATEGORIES`/`UNCLASSIFIED_COVERAGE_HOLE` are the SAME
objects, checked by identity, not merely equal value, in this module's own test suite) and adds
only the one real fact that function does not compute: which concrete subsystem-pair BOUNDARY (or
boundaries) a hole's own declared `subsystem_ids` actually name, plus a rollup of holes onto those
boundaries.

**Boundary resolution is a genuinely new, three-value vocabulary** (`BOUNDARY_RESOLVED`/
`BOUNDARY_UNRESOLVED_INSUFFICIENT_SUBSYSTEM_IDS`/`BOUNDARY_NOT_APPLICABLE`), because
`system_failure_taxonomy.py` has no boundary concept at all -- and it is decided from an
INDEPENDENT piece of evidence from the one that decided the category. A hole classified
`INTEGRATION_GAP` because it declared `scope: "cross_subsystem"` but never actually NAMED which
subsystems are involved gives this module nothing to resolve a real pair from, and it is reported
`UNRESOLVED_INSUFFICIENT_SUBSYSTEM_IDS` -- never a guessed or synthetic placeholder pair such as
`("UNKNOWN", "UNKNOWN")`. Symmetrically, a hole whose category is NOT `INTEGRATION_GAP` (a
`RESOURCE_GAP` or `ERROR_PATH_GAP`) can still name two or more real `subsystem_ids` -- a
shared-resource or error-path gap genuinely can span a specific pair of subsystems even though
`classify_system_coverage_hole()`'s own category priority order resolved a different, more
specific category for it first -- so boundary resolution is decided purely from the hole's own
real, declared `subsystem_ids`/`subsystem_id` count, independent of which category won. A hole
naming fewer than two real subsystem ids, and never claiming a cross-subsystem scope either, is
honestly `NOT_APPLICABLE` (there was never a boundary question to ask).

`CrossSubsystemCoverageIR.boundary_matrix()`/`category_totals()`/`unresolved_boundary_hole_ids()`
are pure reductions of the already-computed per-hole records -- nothing here is computed a second,
disagreeing way from `holes`. `render_boundary_matrix_markdown()` reuses
`connectivity.render_markdown_table()` (this repo's one parameterized table renderer) rather than
a second hand-rolled table loop, and `assert_no_verification_verdict_vocabulary()` holds this
module's own boundary-status vocabulary (plus the reused category vocabulary) disjoint from
`dv_harness.models.Status` at import time, the same guard several sibling taxonomy/IR modules in
this project already apply to their own vocabularies.

**What this module does not do.** It performs no coverage-tool parsing (that stays
`coverage_analysis.py`'s and `evidence_db.py`'s job -- neither is imported here); it never decides
which subsystem "owns" a boundary gap or which fix a human should pursue; it runs no build, gate,
or approval, and there is deliberately no stage gate. A boundary/category rollup here is an input
to a human's coverage-closure review, never a substitute for one. There is no `dv-harness` CLI verb
(`cli.py`/`gates.py` untouched) -- the front door is `python -m
dv_harness.cross_subsystem_coverage_ir --holes <file.json> [--json]`, exit 0 clean, 1 a real
unresolved-boundary finding, 2 an unreadable/malformed input file.

Proven by `dv_harness_tests/test_cross_subsystem_coverage_ir.py` (31 tests,
`python -m pytest dv_harness_tests/test_cross_subsystem_coverage_ir.py -q` -> `31 passed`): the
category vocabulary is proven to be the SAME object as `system_failure_taxonomy`'s (identity, not
equality), and `classify_cross_subsystem_hole()`'s category/matched_field/reason are proven equal
to a direct, independent call into `classify_system_coverage_hole()` over the identical hole. The
required negative control is the headline proof: a declared `scope: "cross_subsystem"` hole naming
zero or one real subsystem id is `BOUNDARY_UNRESOLVED_INSUFFICIENT_SUBSYSTEM_IDS`, never a
fabricated pair -- proven separately from the RESOURCE_GAP/ERROR_PATH_GAP-still-resolves-a-real-
boundary tests that prove category and boundary are genuinely independent axes. Further coverage:
multi-subsystem pairwise boundary enumeration (2 and 3 ids), order-independence and de-duplication
of boundary pairs, single-subsystem and no-subsystem-info `NOT_APPLICABLE` cases, malformed-input
refusals (`None`/non-dict hole, `None`/non-list holes, a non-dict entry inside a holes list), the
full-IR reductions (`boundary_matrix`/`category_totals`/`unresolved_boundary_hole_ids`/`to_dict`)
proven over a 5-hole fixture spanning every boundary status, markdown rendering including the
empty-boundary-matrix note, and four CLI subprocess tests covering the clean/unresolved/unreadable/
malformed-JSON paths.


<!-- S107: moved verbatim from CLAUDE.md original lines 6624-6698 (M4.6 CLAUDE Context Normalization) -->
## Register-Map Excel/CSV Extraction: Real Transcription for register_map.schema.json (2026-09-06)

`register_map.schema.json`'s own description names why it existed only as a documented INPUT
CONTRACT rather than a live extractor: "No live RAL model exists in dv_harness itself ... which is
exactly why this is a documented input contract rather than a live extractor." A real project has
had to hand-author that JSON from a RAL export, an IP-XACT conversion, or a programming-guide
transcription. A repo-wide grep for `openpyxl`/`xlsx`/`Excel` before this change matched only
unrelated document handling (`doc_extraction.py`'s suffix set, `vplan_writer`'s `.xlsx` output) --
nothing read a register-map SPREADSHEET, which is how many real programming guides and RAL exports
actually arrive.

`dv_harness/register_excel_extract.py` is that transcription step, and only that -- it never
invents a register. A spreadsheet row is either transcribed from real cells or its defect is
reported and that row/field is excluded, never silently dropped and never filled with a guessed
placeholder.

**Reuse, not a second schema or a second validator.** The output SHAPE is register_map.schema.json
itself: `to_register_map_document()` builds a document from the extracted `RegisterIR` and validates
it through the REAL `env_manifest.validate_register_map()` -- there is no second register-map
validator in this module. The CURRENT access-type vocabulary is read LIVE from
`register_map.schema.json`'s own `$defs.access_kind.enum` at run time
(`schema_access_kind_enum()`), never hardcoded, so a future additive schema widening needs no code
change here to be picked up.

**Access-type normalization is deliberately two separate questions.** `normalize_access_type()`
folds SPELLING variants ("R/W", "Read-Write", "read write") onto one short canonical token -- a
formatting normalization only. Whether that token is one of the schema's currently-declared eight
values (RW/RO/WO/W1C/RW1C/RC/WC/W1S) is answered separately, against the schema file read at run
time, so the two concerns can never be conflated. This project's real fixture spreadsheet uses
`RS` (read-to-set: reading the field also sets it, distinct from `RC`'s read-clears) -- a real access
semantic the schema does not yet declare. The extractor normalizes it correctly as a token but
never coerces it onto an existing value or silently drops it: it is preserved verbatim in the
`RegisterIR` and reported in `schema_widening_candidates`, naming exactly which register/field used
it, so a human/integrator can decide whether to widen the schema additively. Per this task's
file-safety scope, `register_map.schema.json` itself was NOT edited here -- the proposed additive
enum value (`"RS"`) is recorded in this task's own report for an integrator to add, rather than
applied unilaterally to a schema file other production modules (`env_manifest.py`,
`build_dut_facts_registers()`) also depend on.

**Bounded, honestly.** No `openpyxl` installed -> `NOT_AVAILABLE` naming the real `ImportError`,
never a crash. Missing file, legacy binary `.xls` (openpyxl reads `.xlsx`/`.xlsm` only, not the
pre-2007 binary format), an unreadable workbook, no recognizable header row, or missing required
columns (`Register Name`/`Offset`) -> `NOT_AVAILABLE`/`PARSE_ERROR` with the real reason, and zero
registers surviving parsing is `PARSE_ERROR`, never a silently-empty "success". A row-level defect
(unparseable offset/bit-range, an access-type string that is not even a plausible mnemonic, a field
row with no preceding register-defining row) excludes only that row/field -- recorded in
`row_errors` -- and the file's status becomes `PARTIAL` rather than the whole extraction failing or
a bad row being guessed into a register. Offsets/reset values require a `0x`/trailing-`h` hex form or
plain decimal digits -- a bare un-prefixed hex string is read as decimal, a stated limitation rather
than a guessed interpretation. `to_register_map_document()` additionally excludes any
register/field whose access type is not in the CURRENT schema enum, or whose width is not one of the
schema's declared widths (8/16/32/64/128), from the schema-conformant document it hands to
`env_manifest.validate_register_map()` -- never force-mapping it onto the nearest existing value --
while the full fact stays present in the plain `RegisterIR` this module returns, so nothing is lost,
only kept out of what is presented as already schema-valid.

There is no `dv-harness` CLI verb here (`cli.py` is out of this task's file-safety scope, per the
same disclosed-scope convention several concurrent 2026-09-06 additions already use) -- the front
door is `python -m dv_harness.register_excel_extract <path> [--sheet] [--block] [--base-address]
[--json]` (exit 0 clean, 1 `PARSE_ERROR`, 2 `NOT_AVAILABLE`).

Proven by `dv_harness_tests/test_register_excel_extract.py` (42 tests) against a REAL `.xlsx`
fixture built with `openpyxl` in the test file itself (plus a CSV variant): a clean multi-register,
multi-field extraction with mixed reset/access values and the `RS` widening-candidate detection,
absolute-address computation from a supplied base address, and twelve negative controls (missing
file, simulated openpyxl absence, legacy `.xls`, unsupported extension, empty workbook, missing
required headers, all-rows-malformed, a bad offset excluding only that register, a bad bit-range
excluding only that field, an orphan field row, unrecognized access-type text, an unknown sheet
name) -- each proving the defect is reported and nothing fabricated. The schema-bridge is proven
separately: the clean extraction validates against the real schema end to end, `RS`-typed content is
excluded from the schema-conformant document while schema-legal content survives, and a corrupted
width excludes its register with a named reason. Both real CLI exit-code paths are driven as real
subprocesses. Ran `python -m pytest dv_harness_tests/test_register_excel_extract.py -q`: **42
passed**.


<!-- S108: moved verbatim from CLAUDE.md original lines 6699-6811 (M4.6 CLAUDE Context Normalization) -->
## Programming Sequence IR: Phase Ordering + Register-Dependency Validation (2026-09-06)

`dv_harness/programming_sequence_ir.py` models a programming sequence as an ordered list of
steps carrying a canonical PHASE (`INIT -> CONFIGURE -> ENABLE -> {RUN/WAIT/VERIFY/DISABLE, any
order among themselves} -> RESET`) and validates that ordering against a register-facts input --
the piece `init_seq.py` genuinely does not have. `init_seq.py`'s own `validate_init_seq()` checks
schema shape and kind-conditional required fields (a `wait_condition` needs a `timeout_us`, etc.);
it has no phase concept and no register-dependency concept at all, and `directed_test_steps()`
resolves a step's register name to an absolute address without ever asking whether writing that
register at that point in the sequence is itself legal. Nothing in `init_seq.py` was duplicated
or modified to build this.

**Register facts are duck-typed, deliberately not imported from `register_excel_extract.py`**
(owned by a separate concurrent workstream). `register_facts_from_dicts()` accepts the same shape
that module's real `RegisterIR.to_dict()` output already carries -- `name`/`offset`/`access_type`
(the same canonical short access mnemonics `normalize_access_type()` produces: RW, RO, WO, W1C,
RW1C, RC, WC, W1S, RS) -- plus one field neither existing module carries yet, `depends_on` (a list
of register names that must be written earlier in the sequence). Once the two modules are wired
together, `extract_register_map(...)`'s registers can be passed straight through with zero
translation code, `depends_on` defaulting to `[]` for a source that carries no such column.

**Three independent checks, over a real DAG and a real canonical phase order, not merely a shape
check.** (1) Phase-order monotonicity against the canonical rank table --
`PHASE_ORDER_VIOLATION`/`UNKNOWN_PHASE`. (2) Access-type legality per step action (`write` against
a register whose access_type is not write-legal, `read` against one not read-legal) --
`ACCESS_TYPE_MISMATCH`/`UNKNOWN_REGISTER`/`UNKNOWN_ACCESS_TYPE` (the last a WARNING, never assumed
illegal for an access mnemonic this module has simply never seen). (3) Register dependency
ordering from each fact's own `depends_on` -- a real DFS cycle-detection pass over the facts'
dependency graph reports a circular claim once (`DEPENDENCY_CYCLE`), a dependency naming a
register absent from the facts entirely is `DANGLING_DEPENDENCY`, and a register written before
its own declared dependency was written earlier in THIS sequence is
`DEPENDENCY_NOT_YET_SATISFIED`.

**Evidence Truth Rule, applied precisely.** No register facts supplied -> `NOT_AVAILABLE` (never a
silent pass claiming a check that never ran); an IR with zero steps -> `NOT_APPLICABLE`. Only with
real facts and real steps does a genuine `ORDER_VALID`/`ORDER_INVALID` verdict become possible.
The vocabulary is deliberately NOT `PASS`/`FAIL` (both real `models.Status` members) --
`assert_no_verification_verdict_vocabulary()` checks this module's status and finding codes share
no token with `models.Status` at import time, the same discipline
`dependency_supply_chain.py`/`capability_evolution.py`/`verification_strategy.py` already hold.

**Deliberately bounded, and stated rather than implied closed.** It validates ORDERING/
DEPENDENCY/ACCESS-LEGALITY only -- it does not resolve absolute addresses (that is
`init_seq.py`'s `directed_test_steps()` job) and runs no simulation. It is a standalone module
with no `gates.py`/`cli.py` wiring yet (file-safety scope for this batch): ad hoc via
`python -m dv_harness.programming_sequence_ir validate --sequence <file> [--facts <file>]
[--json]`. If a stage gate or CLI verb is wanted, `gates.py`'s STAGE_GATES has no entry for this
today; a candidate entry would run this module's `execute_verb()` against the project's own
sequence/facts artifacts once those exist.

Proven by `dv_harness_tests/test_programming_sequence_ir.py` (25 tests, no mocks): a clean 7-step
fixture with a real 4-register `depends_on` chain passes with zero findings; both honest-absence
statuses are exercised; 8 negative controls each mutate the clean fixture one specific way
(phase regression, unknown phase, unknown register, write-to-RO, read-from-WO, unknown-access-type
as warning-not-fail, unsatisfied dependency, dangling dependency, a real dependency cycle reported
exactly once); 6 construction-time refusals (non-contiguous indices, a non-wait step missing its
register, a bad action, a fact with no name, a non-list `depends_on`, a document with no name);
and 3 tests drive the real CLI as a subprocess asserting exit 0/1/2.

**Extension (2026-09-06, register_dependency_misuse_graph): project-wide dependency graph + illegal
sequence catalog, now with real test coverage.** The module's own docstring already described a
`RegisterDependencyGraph` (built by `build_register_dependency_graph()` from a REUSED `RegisterFact`
list -- there is no parallel register-identity shape anywhere in this extension) that generalizes
the per-sequence dependency check above into a real, queryable graph across a project's FULL
register set, independent of any one sequence: `dependencies()`/`dependents()`/
`transitive_dependencies()`/`transitive_dependents()`/`topological_order()`/`detect_cycle()`/
`dangling_dependencies()`, reusing the SAME `_detect_dependency_cycle()` cycle detector
`validate_step_ordering()` already used internally rather than a second implementation. Alongside
it, `IllegalSequencePattern` + `load_illegal_sequence_catalog()` + `check_illegal_sequences()` add a
catalog of DOCUMENTED misuse knowledge `depends_on` cannot express on its own (a mutual-exclusion
ordering with no dependency relationship, say) -- every catalog entry requires a real, non-empty
`evidence` citation and is refused otherwise, the same citation-required discipline
`design_intent.py` already applies to its own `backpressure_conditions`.
`validate_step_ordering()`'s existing, keyword-only `illegal_sequence_catalog` parameter (default
`None`, so every pre-extension caller's behavior stays byte-for-byte unchanged) folds catalog
findings into the existing report; `check_illegal_sequences()` is also directly callable standalone,
needing no register facts at all.

This code existed in the module (with a dated docstring note) before this gap-closure pass, but
carried ZERO tests exercising it -- a repo-wide check confirmed the original 25-test suite never
referenced `RegisterDependencyGraph`/`IllegalSequencePattern`/`check_illegal_sequences` at all. That
gap is now closed: `dv_harness_tests/test_programming_sequence_ir.py` grew to **58 tests** (33 new,
all passing, no mocks). New coverage: `RegisterDependencyGraph`'s `dependencies()`/`dependents()`
distinguishing a known-empty answer from an unknown-register `None` (never conflated); transitive
closure in both directions; `detect_cycle()` finding a real 3-node cycle (and reporting `None` on a
clean acyclic graph); `dangling_dependencies()` over the whole register set; `topological_order()`
producing a real, order-checked valid write order on an acyclic graph and refusing a partial/
best-effort order (reporting `None` plus the real cycle) when one cannot exist; `to_report()`'s
bundled shape. `build_register_dependency_graph()`'s own honesty contract is proven directly: no
facts (`None` or `[]`) reports `STATUS_GRAPH_NOT_AVAILABLE` with a real reason rather than a vacuous
"empty but available" graph -- the negative control proving this module refuses to fabricate an
answer when evidence is absent, mirroring `validate_step_ordering()`'s own `NOT_AVAILABLE` contract
one layer up. The catalog half is proven equally directly: `illegal_sequence_pattern_from_dict()`
refuses a missing/empty `evidence` citation, fewer than 2 registers, an empty register name, and an
unrecognized `severity`; `load_illegal_sequence_catalog()` refuses a duplicate `pattern_id`;
`check_illegal_sequences()` is proven to match a real subsequence both contiguously and
non-contiguously, to find nothing on a reversed (legal) order, and to report per-pattern severity
verbatim; `validate_step_ordering(..., illegal_sequence_catalog=...)` is proven to fold a real
documented-illegal-sequence finding into `ORDER_INVALID` while every catalog-omitted caller's report
stays identical to before (`illegal_sequence_catalog_size == 0`). The CLI's `graph` verb (already
present in `execute_verb()`/`main()` before this pass, likewise untested) is now driven as a real
subprocess across all three of its documented exit codes (0 clean, 1 a real cycle or dangling
dependency, 2 `NOT_AVAILABLE`/missing `--facts`), and the `validate` verb's `--catalog` flag is
proven end to end over real JSON files on disk. `dv_harness_tests/test_usage_recipe_catalog.py` (37
tests, which delegates its own ordering validation into this module's `validate_step_ordering()`)
was re-run unchanged and still passes, confirming the added tests introduced no regression to that
real consumer.

Still standalone with no `gates.py`/`cli.py` (`dv-harness`) wiring, per this batch's own file-safety
scope -- unchanged from the original note above; only the standalone `python -m
dv_harness.programming_sequence_ir` front door's own `graph` verb (already shipped) is what gained
real test coverage here, not a new CLI surface.


<!-- S109: moved verbatim from CLAUDE.md original lines 6812-6894 (M4.6 CLAUDE Context Normalization) -->
## Usage Recipe Catalog: Documented Step-by-Step Recipes over Programming Sequence IR (2026-09-06)

`dv_harness/usage_recipe_catalog.py` assembles named, documented USAGE
RECIPES -- a recipe = an ordered set of `programming_sequence_ir.py`
`ProgrammingSequenceStep`s plus its own required `purpose` and `citation` --
as a distinct, higher-level artifact over that module's per-sequence facts.
Nothing in this repo previously packaged step ordering into a purpose-cited,
named, re-usable unit a generated user guide or DV engineer could hand
someone ("here is how to bring the link up, per programming-guide section
4.2"); `programming_sequence_ir.py` itself only validates ONE declared
sequence's raw step ordering, with no purpose/citation concept at all.

**Pure reuse, no parallel step-ordering logic.** A recipe's steps ARE
`programming_sequence_ir.ProgrammingSequenceStep` instances -- either parsed
via `programming_sequence_ir.programming_sequence_ir_from_dict()` (wrapped as
a throwaway one-field document, so the real index-contiguity/action/register
checks run in the one place that already owns them:
`usage_recipe_from_dict()`), or sliced directly, by real `step.index`, from
an EXISTING `ProgrammingSequenceIR`'s own steps
(`usage_recipe_from_sequence_slice()`, order-preserving only -- indices must
be strictly ascending, since a recipe reordering its source sequence would
misrepresent what that sequence actually does). Ordering validation
(`validate_recipe_ordering()`) builds a `ProgrammingSequenceIR` from a
recipe's steps and calls `programming_sequence_ir.validate_step_ordering()`
directly -- the phase/access-type/dependency/documented-illegal-sequence
checks are not reimplemented at any grain.

**Evidence Truth Rule on assembly, unchanged honesty on validation.** A
recipe with no `purpose`, no `citation`, or zero steps is refused at
construction (`UsageRecipeError`) -- mirroring
`programming_sequence_ir.IllegalSequencePattern`'s identical uncited-claim
refusal. Validating a recipe with no register facts supplied still reports
`programming_sequence_ir.STATUS_NOT_AVAILABLE` completely unchanged (never a
fabricated `ORDER_VALID` just because a recipe is documented). A slice
inherits the source sequence's phase-monotonicity for free (a subsequence of
a non-decreasing sequence is itself non-decreasing) but NOT its dependency
satisfaction -- dropping an earlier step a later, kept step's `depends_on`
relied on honestly re-surfaces `DEPENDENCY_NOT_YET_SATISFIED`, proven by
`test_slice_recipe_can_honestly_surface_a_broken_dependency_chain`.

**Worst-wins catalog-wide rollup.** `UsageRecipeCatalog` (build/get/
`recipes_touching_register()`/`to_catalog_report()`) holds many named
recipes; `validate_catalog_ordering()` validates every recipe against the
SAME register facts and rolls the per-recipe statuses into ONE overall status
via `_rollup_catalog_status()`, worst-wins, never averaged: any
`ORDER_INVALID` recipe fails the whole rollup
(`RECIPE_CATALOG_ORDER_INVALID`) regardless of how many others are clean;
short of that, any `NOT_AVAILABLE`/`NOT_APPLICABLE` recipe still blocks an
honest `RECIPE_CATALOG_ALL_VALID` claim
(`RECIPE_CATALOG_INCOMPLETE_EVIDENCE`); an empty catalog reports
`RECIPE_CATALOG_EMPTY`, never a vacuous all-valid. Own vocabulary
(`STATUS_CATALOG_*`/`STATUS_RECIPE_CATALOG_*`/`STATUS_RECIPE_NOT_FOUND`)
shares no token with `models.Status`, checked at import time the same way
`programming_sequence_ir.py` checks its own.

**Deliberately bounded.** This module assembles and validates ORDERING of
caller-documented recipes -- it never decides which steps of a real sequence
deserve to become a recipe (a human/documentation judgment) and mines no
golden-reference environment for recipe content; every recipe's steps and
citation come from whatever the caller actually supplies. No `gates.py`/
`cli.py` wiring yet (same disclosed file-safety-scope choice
`programming_sequence_ir.py` already made): the front door is
`python -m dv_harness.usage_recipe_catalog catalog --recipes <file> [--json]`
and
`python -m dv_harness.usage_recipe_catalog validate --recipes <file>
[--recipe-id <id>] [--facts <file>] [--catalog <file>] [--json]`.

Proven by `dv_harness_tests/test_usage_recipe_catalog.py` (37 tests, no
mocks): recipe assembly from both a raw dict and a real sequence slice;
6 Evidence-Truth-Rule assembly-time refusals (missing/empty purpose, missing/
empty citation, zero steps, missing recipe_id) plus 5 slice-specific
refusals (non-ascending indices, duplicate index, unknown index, empty
indices, missing citation); delegated ordering validation proven both clean
and broken (a real `ACCESS_TYPE_MISMATCH`), plus the no-facts
`NOT_AVAILABLE`-never-fabricated-`ORDER_VALID` negative control; catalog
build/lookup/duplicate-id refusal/register cross-reference/empty-catalog
report; 4 rollup unit tests proving worst-wins precedence (INVALID beats
INCOMPLETE_EVIDENCE beats ALL_VALID, empty beats vacuous-valid) plus one
integration test; and 6 CLI subprocess tests covering `catalog`/`validate`
(single-recipe and whole-catalog) across all documented exit codes. Ran
`python -m pytest dv_harness_tests/test_usage_recipe_catalog.py -q`: **37
passed**.


<!-- S110: moved verbatim from CLAUDE.md original lines 6895-6960 (M4.6 CLAUDE Context Normalization) -->
## Interrupt / DMA / Clock-Reset Fact Extraction from Real Source Text (2026-09-06)

`dv_harness/interrupt_dma_clock_reset_extraction.py` extracts interrupt architecture (source
list; priority/masking scheme *if stated*), DMA architecture (channel count; descriptor model
*if stated*), and a clock/reset FACT EXTENSION, all read from whatever real spec/programming-
guide/RTL text a caller actually supplies -- never invented. The gap: nothing in this repo read
raw RTL/spec prose for these three facts; `env_manifest.build_dut_facts_clock_reset()` reads a
`soc_arch_map.schema.json` INPUT CONTRACT (a human-authored file), explicitly declaring itself
an input contract and not an extractor because "dv_harness owns no SoC to extract from". This
module is the sibling extractor that docstring points at: it reads real supplied text directly.

**Shape-compatible, not shared code.** Reset entries carry the SAME field names as
`dut_facts.clock_reset`'s resets (`name`/`active_level`/`synchronous`/`clock`/`clock_resolved`/
`evidence`/`description`), independently re-derived here (never imported) since the source
differs entirely -- RTL/spec TEXT here, `soc_arch_map.json` there. `active_level` is likewise
never defaulted: a reset is reported only when its sensitivity-list or first-`if` idiom proves a
polarity.

**Line-scan, not a parser, mirroring `vip_symbol_index.py`'s discipline rather than requiring a
verible binary** (a spec/programming-guide document is not SystemVerilog at all, so a
parser-only approach could never read the prose half of this task). Interrupt sources come from
RTL port declarations whose name matches an irq/intr/interrupt convention; DMA channel count from
an RTL parameter named for a channel count or an explicit "N DMA channels" sentence; the
descriptor model from a real `typedef struct packed {...} <name>;` whose closing name contains
"desc"; clock/reset from `always`/`always_ff` sensitivity lists (an async reset's edge appears in
the sensitivity list itself) and, for a synchronous idiom, the block's own bounded first `if`.

**Priority and masking are bounded to EXPLICIT statement forms on purpose** -- an ordered `>`
chain, a "X has the highest/lowest priority" sentence, an explicit mask/enable-register sentence
-- and are NEVER inferred from the interrupt source list or a register's name, per this task's own
"never infer a priority scheme or channel count that is not written down" instruction and
CLAUDE.md's No Golden-Reference Content Mining / Evidence Truth Rule. Every one of the six facets
(interrupt sources, priority scheme, masking scheme, DMA channel count, DMA descriptor model,
clock/reset facts) carries its OWN status/reason, so one facet's absence never masks another's
presence, and a missing/unreadable source file is recorded rather than raised.

Reachable as `extract_interrupt_dma_clock_reset(source_paths)` / `python -m
dv_harness.interrupt_dma_clock_reset_extraction extract --sources <f> [<f> ...] [--json]` (exit 0
LOADED, 2 NOT_AVAILABLE). No `dv-harness` CLI verb was added (out of this task's file-safety
scope, which forbade editing `cli.py`) -- see the suggested snippet for the integrator.

**Deliberately bounded, and stated rather than implied closed.** (1) It is a regex line-scan, not
a compiler: preprocessor conditionals, multi-line macro expansions, and continuation forms its
patterns do not anticipate contribute no citation, never a wrong one. (2) Priority/masking
extraction only recognises three literal English sentence shapes; a differently-worded but
equally explicit statement is honestly NOT_AVAILABLE rather than guessed at. (3) Reset
synchronicity/polarity is decided only from the two RTL shapes a sensitivity list and its
immediate first `if` can prove; any other idiom is skipped, never guessed at either polarity.
(4) Naming-convention matching (irq/intr/interrupt; rst/reset) is substring-based against a fixed
vocabulary; a differently-named signal is honestly NOT_AVAILABLE rather than guessed from a wider
synonym list this project has no evidence for. (5) There is deliberately no stage gate: this
module reports facts and makes no PASS/FAIL verdict, the same disclosed-bound several sibling
extractors (`golden_scenario.py`, `power_intent.py`) already state.

Proven by `dv_harness_tests/test_interrupt_dma_clock_reset_extraction.py` (11 tests) against
real synthetic fixtures under `dv_harness_tests/fixtures/interrupt_dma_clock_reset/` (their own
headers say they are fixtures, not any real DUT/spec): a positive path asserting every facet's
exact extracted value and file:line evidence, and negative controls proving no interrupt ports
reports NOT_AVAILABLE rather than an empty pass, a document with no priority/masking/DMA language
reports every facet independently NOT_AVAILABLE, a reset signal name that does not match the
reset naming convention is never guessed as a reset even though it is the block's literal first
`if` (while the real clock fact is still reported), a mutated fixture with the channel-count
parameter removed reports that facet NOT_AVAILABLE while the untouched descriptor model still
loads, and missing/absent source files are handled honestly. Both real CLI invocations are driven
as subprocesses.


<!-- S111: moved verbatim from CLAUDE.md original lines 6961-7050 (M4.6 CLAUDE Context Normalization) -->
## Error Behavior / Recovery Flow Extraction from Real Source Text (2026-09-06)

`dv_harness/error_recovery_flow_extraction.py` extracts error/recovery BEHAVIOR FACTS from
whatever real spec/programming-guide/RTL text a caller actually supplies -- never invented --
combining `spec_doc_map.py`'s real structural document index with
`interrupt_dma_clock_reset_extraction.py`'s own declaration-level line-scan pattern, applied to
error/recovery vocabulary instead of that module's interrupt/DMA/clock-reset vocabulary (this
task's own instruction, matched to the letter).

**REUSE OVER REINVENT, checked before writing anything.** `verification_intent_ir.py`'s
`plan_error_recovery()` states outright, in its own docstring and constant name
(`ERROR_TARGET_UNKNOWN`), that "this harness has no evidence producer for either [performance or
error_recovery]" and always returns that sentinel -- this module is the missing producer that
docstring names. `potential_spec_gap_detector.py` classifies already-EXTRACTED requirement
RECORDS for a missing error<->recovery PAIRING (a gap-analysis over structured requirements,
never a raw-text extractor). `system_checker_taxonomy.py`'s `RECOVERY_CHECKER` classifies a
caller-supplied CHECKER description, not spec/RTL prose. None of the three reads real source text
for error/recovery facts, which is exactly this module's job.

**Two real mechanisms, kept deliberately separate, never merged into one scan.** (1)
STRUCTURAL: `spec_doc_map.extract_spec_doc_map()` (imported, called through its real public API)
turns a spec/programming-guide document into a real, mechanically-detected section index; this
module filters that index's own `sections` list for a heading whose TITLE names an
error/fault/exception/recovery keyword and reports each match's real heading/number/level/page as
`error_recovery_chapters` -- WHERE an error/recovery discussion structurally lives, never what it
says. Because `extract_spec_doc_map()` requires a real `out_dir` to write its two structure-only
artifacts into, this facet is attempted only when a caller supplies `structural_index_dir` --
omitting it is an honest `NOT_AVAILABLE` on this ONE facet, never a silent skip disguised as
"nothing found", and never a `mkdir()` a caller did not ask for. (2) DECLARATION-LEVEL LINE SCAN:
exactly `interrupt_dma_clock_reset_extraction.py`'s own graceful-degradation discipline -- RTL
port declarations and plain prose sentences a caller supplies are scanned line by line for
EXPLICIT statement forms; a construct or sentence this scan does not recognise contributes
NOTHING, never a guessed fact. This half never touches `spec_doc_map.py`, whose own contract
forbids it from ever extracting or persisting body prose.

**Three line-scan facets, each bounded to explicit evidence on purpose.** `error_conditions` --
RTL port declarations whose NAME matches an err/error/fault/alarm/excp/exception naming
convention; records the name/direction/width/description the RTL actually declares, makes no
claim about severity or recoverability. `recovery_statements` -- an EXPLICIT sentence naming both
a real recovery trigger word (recover/recovery/recoverable) and a real recovery-mechanism keyword
(reset/retry/reinitialize/clear/power-cycle/resend/resynchronize) in the same line; a recovery
mechanism is NEVER inferred from the mere presence of an error condition. Automatic-vs-manual is
classified ONLY from an explicit word in that same sentence
(automatic(ally)/self-clear(s)/internally for automatic; software/firmware/manual(ly)/host
must/cpu must/driver must for manual) -- a statement naming neither is honestly
`RECOVERY_MECHANISM_STATED`, who performs it is never guessed. `error_recovery_links` -- an
explicit statement tying ONE named error condition to ITS OWN recovery action, bounded to two
literal statement forms ("<X> error requires <Y>" and "on a/an <X> error, ...
shall/will/automatically <Y>"); a general recoverability statement fitting neither form
contributes to `recovery_statements` only, never a guessed link.

Reachable as `extract_error_recovery_flow(source_paths, structural_index_dir=None)` / `python -m
dv_harness.error_recovery_flow_extraction extract --sources <f> [<f> ...]
[--structural-index-dir <d>] [--json]` (exit 0 LOADED, 2 NOT_AVAILABLE). No `dv-harness` CLI verb
was added -- out of this task's own file-safety scope, which forbade editing `cli.py`/`gates.py`
(both large files under concurrent edit pressure from many items in this same batch), matching the
same disclosed choice `interrupt_dma_clock_reset_extraction.py` and several other sibling
same-day extractors already make.

**Deliberately bounded, and stated rather than implied closed.** (1) A regex line-scan, not a
compiler or an NLP model: multi-sentence/multi-paragraph recovery flows, `` `ifdef `` conditionals,
and any statement form these patterns do not anticipate contribute no citation rather than a
wrong one. (2) `error_recovery_links` is bounded to exactly two literal statement forms; a
differently-worded but equally explicit link is honestly absent from `error_recovery_links` (it
still surfaces via `recovery_statements` if it names a trigger+mechanism pair) rather than
guessed into one of the two recognised shapes. (3) `RTL_SUFFIXES`/`TEXT_SUFFIXES`/
`classify_source()`/the port-declaration regex are independently re-derived here rather than
imported from `interrupt_dma_clock_reset_extraction.py`, the same "re-derive a small primitive
rather than import a sibling module's private shape" discipline several modules in this codebase
already follow, so this module carries no import-time coupling to a sibling that may itself be
under concurrent edit. (4) There is deliberately no stage gate: this module reports facts and
makes no PASS/FAIL verdict, the same disclosed bound `golden_scenario.py`/`power_intent.py`/
`interrupt_dma_clock_reset_extraction.py` already state for themselves. (5) This module decides
nothing beyond reporting: no build, job, approval, or stage gate is touched.

Proven by `dv_harness_tests/test_error_recovery_flow_extraction.py` (15 tests) against real
synthetic fixtures under `dv_harness_tests/fixtures/error_recovery_flow/` (their own headers say
they are fixtures, not any real DUT/spec): a positive path asserting every one of the four facets'
exact extracted values and `file:line`/`#section:` evidence, including the real
`spec_doc_map`-backed structural chapter index (with a real assertion that its own real
structure-only artifact was written to disk, proving actual reuse of that module's public API
rather than a stub); and negative controls proving the module reports honest `NOT_AVAILABLE`
rather than fabricating a recovery mechanism, an automatic/manual classification, a link, or a
structural chapter when the supplied text does not state one -- including a document naming a
watchdog error with a bare "may recover after a reset" sentence, proven to classify as the generic
`RECOVERY_MECHANISM_STATED` rather than being guessed automatic or manual. Both real CLI
invocations (`--json`, `--structural-index-dir`, a no-sources usage error) are driven as real
subprocesses. Ran `python -m pytest dv_harness_tests/test_error_recovery_flow_extraction.py -q`
-> `15 passed`.


<!-- S112: moved verbatim from CLAUDE.md original lines 7051-7128 (M4.6 CLAUDE Context Normalization) -->
## PHY Model Behavior IR: Documented Architecture Facts, Never Silicon (2026-09-06)

`dv_harness/phy_boundary.py` already answers a STRUCTURAL question from real RTL: at which layer
(serial vs. parallel) a bind may mount. It carries no notion of the PHY's own DOCUMENTED
behaviour -- what training/link-startup states a real PHY specification names, what it actually
says about TX/RX capability, what power states it names. Nothing in this repository read a PHY
spec/model document for those facts before this module. `dv_harness/phy_model_behavior_ir.py` is
that extractor, and it reuses rather than reinvents on both sides of the fact it adds:

- The PHY DOCUMENT is never opened here as a raw PDF/text scan. `dv_harness/vip_user_guide_distill.py`
  is this repo's one offline document distiller (real `pypdf` extraction, or pre-extracted text);
  this module consumes the `.reference.json` record + `.fulltext.txt` file that distiller already
  produces for a real PHY spec/model document (`doc_kind="protocol_spec"`/`"programming_guide"`) --
  one document-opening code path in this package, not two, and the Context Budget rule ("never
  loaded into runtime context") stays enforced structurally by staying off it.
- The RTL-derived serial/parallel BOUNDARY is read, not re-derived. `dv_harness/phy_boundary.py`
  (read-only -- never edited by this module) already answers "at which layer may a bind mount";
  its own JSON output is accepted verbatim as the optional `phy_boundary_doc` input, validated
  with its own `validate_phy_boundary()`, and merged in as `boundary_context`. No second RTL/
  port-width classifier was written.

**Extraction is STRUCTURAL, never semantic.** A small, disclosed set of section-marker regexes
(generic across protocols -- "link training", "transmitter", "receiver", "power state", the same
genericity discipline `phy_boundary.py`'s own `_STRONG_CORE_RE`/`_WEAK_CORE_RE` token matching
already applies to RTL port names) decides which document SECTION a line sits in, and a small set
of line-shape patterns ("ID: description" / "ID&nbsp;&nbsp;description" for named facts, a
bulleted/numbered list item for capability text) decides which lines inside that section are
candidate facts. The current section resets at EVERY heading-like line, matched or not -- proven
by a test that an unrelated, recognized heading's content never leaks into the previous section's
fact list. Nothing here asserts what a training stage, a TX capability, or a power state IS for
any protocol; it only locates where the DOCUMENT ITSELF already says so, with a real
`document + fulltext_path + line` citation on every item that a reader can open and verify.

**PHY MODEL BEHAVIOR IS NOT SILICON**, stated once and carried onto every document this module
produces (EXTRACTED or NOT_AVAILABLE alike) via a fixed `disclosure` field: neither a digital PHY
model nor specification prose demonstrates analog/electrical correctness of a real PHY
implementation -- timing margins, signal integrity, jitter, voltage levels, and eye diagrams are
NOT verified, measured, or claimed correct by anything in this artifact.

**Absent PHY doc/model reports NOT_AVAILABLE for every field, never a guess.** Called with no
document at all, `extract_phy_model_behavior_ir()` returns a schema-valid document whose top-level
`status` and all four fact fields (`training_link_startup_stages`, `tx_capabilities`,
`rx_capabilities`, `power_states`) are NOT_AVAILABLE with a real reason. A document that IS
supplied but whose text contains no recognizable section for a category reports
`NO_MARKER_SECTION_DETECTED` -- kept honestly distinct from `MARKER_SECTION_FOUND_NO_ITEMS` (the
section exists, but no item-shaped line was found inside it); neither is ever a false `FOUND`.

New schema `dv_harness/schemas/phy_model_behavior_ir.schema.json` (Draft 2020-12), following
`phy_boundary.py`'s own fail-closed `PhyModelBehaviorIRValidationError` / deterministic
`save`/`load` convention.

**Deliberately bounded, and stated rather than implied closed.** (1) This module never opens a
raw PDF/text file itself -- a caller distils the real PHY document with
`vip_user_guide_distill.distill_user_guide()` first. (2) The section-marker vocabulary is a small,
fixed, generic set; a document using an entirely different section-naming convention honestly
reports `NO_MARKER_SECTION_DETECTED`. (3) The heading detector recognizes only a numbered `X.Y`
section-number pattern or a short ALL-CAPS line -- proven (`test_a_bare_numbered_list_item_is_not_
mistaken_for_a_heading`) to NOT mistake a bare numbered list item ("1. Detect") for a heading, the
false-positive direction that would wrongly cut a real section's items off. (4) Extraction is
line-based; a fact expressed as free multi-line prose with no bullet/"ID: description" shape is
honestly not captured rather than paraphrased. (5) It reads and reports only -- no build, no
simulation, no approval, no stage gate, and no human-approval/governance mechanism is touched.

Proven by `dv_harness_tests/test_phy_model_behavior_ir.py` (22 tests) against a real
`vip_user_guide_distill.distill_user_guide()` call over a synthetic `.txt` PHY-spec fixture whose
own text states it is a test fixture describing no real IP, and real
`phy_boundary.extract_phy_boundary()` calls for the `boundary_context` tests. Positive path: all
four categories found with correct names/text, every citation verified against the real full-text
file. Negative controls: no document supplied, a malformed reference-record dict, a missing
reference-record path, a missing full-text file on disk, a tampered full-text file (hash-mismatch
detected without blocking extraction), a document with no matching section anywhere, a document
with a matching section but no item lines (shown distinct from the "no section at all" case), a
bare numbered list item proven not mistaken for a heading, the anti-leakage property across a
following unrelated recognized heading, an invalid `phy_boundary_doc` refused rather than trusted,
and a schema-valid-but-internally-`NOT_AVAILABLE` `phy_boundary_doc` carried through honestly
rather than silently dropped. `python -m pytest dv_harness_tests/test_phy_model_behavior_ir.py -q`
-> `22 passed`.


<!-- S113: moved verbatim from CLAUDE.md original lines 7129-7210 (M4.6 CLAUDE Context Normalization) -->
## Design Architecture IR: Full Instance Tree + Bounded FSM Literal Scan (2026-09-06)

`dv_harness/verible_parser.py` already extracts, per RTL FILE, each module's ports/parameters/
module-level signals plus its instantiations and continuous assigns -- its own docstring: "module/
port/signal hierarchy, not a full elaboration/semantic model". Nothing in this repo turned that
per-FILE fact set into one architecture-wide picture: a MULTI-FILE module registry, a full recursive
INSTANCE TREE (not merely one module's own flat instance list, which is all `env_manifest.py`'s
`build_dut_facts_rtl()` -- the closest existing consumer -- ever assembles), and any notion of a
module's internal FSM/control-flow shape. Re-verified by grep before building: no module or symbol
named `ArchitectureIR`/`instance_tree`/`fsm_candidate` existed anywhere.

`dv_harness/design_architecture_ir.py` is both real, tractable extensions, built entirely on TOP of
verible_parser.py's own output (a read-only import -- this module never re-parses SystemVerilog and
never re-implements verible_parser's tree-walk):

- **Full instance tree.** `build_module_registry()` folds every parsed file's modules into one
  name-keyed registry (first occurrence wins, deterministically by sorted file_path; a module name
  declared in more than one file is reported in `duplicate_modules`, never silently overwritten --
  this is intentionally NOT `system_build_proof.py`'s real system-merge-collision analysis, which is
  a different, already-real mechanism this module does not duplicate or extend). `build_instance_tree()`
  then recursively resolves every instantiation's `module_name` against that registry, all the way
  down, carrying each level's real ports/parameters and this instantiation's real port connections.
  An instance whose module was not supplied to this build (an external module, a VIP BFM, a std cell)
  is an honest, common, EXPECTED fact -- reported as an unresolved leaf naming the real reason, never
  an error and never silently dropped. A genuine instantiation CYCLE (A instantiates B, B instantiates
  A -- writable, if unusual, RTL) is detected by tracking the ancestor path and stopped rather than
  recursed forever.
- **Best-effort FSM/control-flow literal scan -- deliberately NOT elaboration.**
  `extract_fsm_candidates()` is a regex/light-parse scan over the raw SOURCE TEXT of one module --
  text verible_parser.py already isolated as that module's own byte span via its public `node_span()`
  -- looking for `always @(posedge <clk>...)` blocks containing a `case` statement. It is not a
  second SystemVerilog parser: no generate/`ifdef resolution, no expression evaluation, no proof
  that the case-keyed identifier is really a register beyond "it is (or is not) among this module's
  own verible-extracted module-level signal declarations". Every candidate carries an explicit
  status from a closed vocabulary -- `FSM_EXTRACTION_RESOLVED` only when the case-key is a single
  plain identifier that IS a declared module-level signal, every non-default case item has exactly
  one distinct resolvable self-assignment target, and the case block actually closed with a real
  `endcase` this scan could find; anything short of that is `FSM_EXTRACTION_PARTIAL` (an
  ambiguity/registration problem) or `FSM_EXTRACTION_UNPARSEABLE` (this scan could not close the
  block it found), and a posedge block with no case in its window is `NOT_APPLICABLE`. A module with
  no matching pattern at all reports `NOT_AVAILABLE` with a real reason. A guessed state machine is
  never presented as a confirmed one. `//`/`/* */` comments and `"..."` string literals are blanked
  out (length- and newline-preserving) before any regex runs, so a stray `case`/`endcase` spelled
  inside a comment or string cannot corrupt the depth-counted matching -- a real false-positive class
  for a literal scan, and one this module is explicit about handling rather than ignoring.

Front door: `python -m dv_harness.design_architecture_ir --rtl <f> [--rtl <f> ...] [--top-module NAME]
[--out ir.json] [--json]` (`execute_verb()`, the same shared-implementation convention
`power-intent`/`golden-scenario` use). There is no `dv-harness` CLI verb for this yet -- see the
disclosed residual below. Exit 0 the IR was built (at least one module parsed), 2 NOT_AVAILABLE (no
files supplied, or nothing could be parsed from any of them).

**Deliberately bounded, and stated rather than implied closed.** (1) This is DECLARATION/
PATTERN-LEVEL extraction, not elaboration-time proof: no generate/`ifdef condition is evaluated, no
parameter value is resolved, and a signal declared inside a procedural block is invisible to the FSM
scan for the same reason verible_parser.py's own signal extraction deliberately does not surface it.
(2) Only the FIRST `case`/`casex`/`casez` statement in each `always @(posedge ...)` block's own
best-effort window (bounded by the next `always` header or the module's end) is scanned; a second,
sibling case in the same always block is not examined. (3) Case-item labels are matched at the start
of a line for identifiers/`default`/sized literals only; a comma-joined multi-label line is captured
as one combined label rather than split. (4) `duplicate_modules` is a name-collision report only, not
a merge-collision analysis -- `system_build_proof.py` already owns that different, deeper question.
(5) It decides, approves and arbitrates nothing: no build, gate, approval, or stage gate of any kind
-- reading is the only act, matching `golden_scenario.py`/`power_intent.py`'s own precedent that a
pure extraction module carries deliberately no stage gate.

Proven by `dv_harness_tests/test_design_architecture_ir.py` (30 tests). The FSM literal scan is a
PURE function tested directly against hand-written SystemVerilog snippets (no verible dependency):
a clean resolved FSM, plus real negative controls for every one of the four non-RESOLVED statuses
(ambiguous next-state, unresolved state, missing endcase, a case key that is neither declared nor a
plain identifier) and a comment/string-literal robustness control (a fake `case`/`endcase` spelled
inside a `//`/`/* */` comment and a string literal does not corrupt the real block's depth count).
Everything needing real module boundaries runs the REAL `verible-verilog-syntax` subprocess (skipped,
never faked, on a machine without it): a real 3-level instance hierarchy (leaf/mid/top) with a real
external black-box instance and a real FSM in the top module resolves end to end -- correct depths,
ports, connections, and FSM states/transitions/line numbers read off the real verible-parsed span --
plus real controls for a duplicate module name across two files, a genuine mutual-instantiation cycle
(proven not to recurse forever), a `top_module` override and its unknown-name error, a real syntax
error in one file among several (isolated, not fatal to the others), an unrunnable verible binary, an
unreadable file, no files supplied, and the CLI subprocess (`--json`, `--out`, a missing required
argument, and an unknown `--top-module` exiting 2).


<!-- S115: moved verbatim from CLAUDE.md original lines 7300-7390 (M4.6 CLAUDE Context Normalization) -->
## Spec Intelligence: SCHEMA + Validation/Re-Derivation Gate (2026-09-06)

Turning protocol prose into requirements is inherently an LLM-reading-a-document act, not
something this codebase can compute the way `verible_parser.py` computes RTL facts. Building a
fake "spec understander" would be exactly the fabrication the Evidence Truth Rule forbids.
`dv_harness/spec_intelligence.py` is therefore the CONTRACT an extraction result must satisfy to
be trusted downstream, not an extractor: a real, mechanical document structure index (SpecMap),
plus a real, mechanical validation/re-derivation gate over whatever an agent (or a future
extractor) claims it found about a set of atomic requirements and the relations between them --
the same discipline `requirement_contract.py` already applies to one requirement record, lifted
to a SET plus its cross-requirement relations.

**Two vocabularies reused, not re-invented, exactly as the task required.** Every atomic
requirement IS a `requirement_contract.py` canonical-contract record
(`contract_schema_version` required); it is validated by `validate_requirement_contract()` and
analysed by `analyze_requirement_contract()` -- imported and called, never re-typed -- so its
COMPLETE/PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN status is that module's own, re-derived by that
module's own `derive_status()` (a fully hand-mutated fixture reproduces `STATUS_OVERCLAIMED`
through this module to prove the call is real, not restated). The extraction batch declares
`evidence_provenance` in `evidence_provenance.py`'s own AGENT_SELF_ATTESTED/TOOL_DERIVED/
SIMULATION_DERIVED vocabulary -- the field name, the accepted-values tuple and the
independently-derived set are all imported, never re-spelled. Reading a spec is, honestly, almost
always AGENT_SELF_ATTESTED; that is accepted for free, and a TOOL_DERIVED/SIMULATION_DERIVED claim
costs a real on-disk artifact under the project root, exactly as that module's own six-gate
enforcement charges for an independently-derived claim.

**SpecMap layers on `vip_user_guide_distill.py`; it performs no PDF/text extraction of its own.**
That module is this repo's one real document distiller and already produces a numbered-heading
section index with real page/char-offset evidence. `build_spec_map()` reads back that module's
OWN rendered `.reference.md` section table (never re-running heading detection) and adds two new
mechanical scans over the already-produced full-text extract: `Table N.M` caption locations, and a
keyword flag on which section headings are register chapters. A SpecMap therefore carries
sections/tables/register-chapter LOCATIONS only -- headings, table captions, page numbers,
character offsets -- and never one sentence of the document's own body text, the same discipline
`vip_symbol_index.py` keeps against retaining method bodies (asserted directly: the JSON-dumped
SpecMap record is checked to contain none of the fixture's own prose sentences).

**Two genuinely new vocabularies, because nothing in this repo names either.** Relation kinds
(`DUPLICATES`/`REFINES`/`EXTENDS`/`CONFLICTS_WITH`) and derivation tags (`EXPLICIT`/
`IMPLICIT_HIGH_CONFIDENCE`/`IMPLICIT_REVIEW_REQUIRED`). Both are RE-DERIVED, not trusted:
- A declared `DUPLICATES`/undeclared-duplicate claim is cross-checked against the requirements'
  own RESOLVED `feature`/`stimulus`/`expected_result` text via `difflib.SequenceMatcher`
  (`requirement_similarity()`, gated through `requirement_contract.is_resolved()` so "nothing
  resolved to compare" is `None`, never a fabricated `0.0`). A `DUPLICATES` claim with low
  similarity is flagged (`DUPLICATES_SIMILARITY_LOW`); a near-identical undeclared pair is flagged
  the other way (`POSSIBLE_UNDECLARED_DUPLICATE_PAIR`, guarded by `MAX_DEDUP_SCAN_SIZE` so the
  O(n^2) scan is skipped-and-said-so rather than unbounded on a large batch).
- A `CONFLICTS_WITH` relation is cross-checked against the underlying contract's own re-derived
  status: it must correspond to at least one side deriving `CONTRADICTORY`
  (`requirement_contract.derive_status()`, called), or it is reported as filed nowhere the
  contract itself would show it (`CONFLICT_RELATION_NOT_FILED_IN_CONTRACT`).
- `IMPLICIT_REVIEW_REQUIRED` requires the underlying requirement to itself derive AMBIGUOUS or
  CONTRADICTORY through `derive_status()` -- i.e. a real, filed, unresolved ambiguity/contradiction
  in `requirement_contract.py`'s own `ambiguities`/`contradictions` arrays, never a second
  free-floating "open question" flag nobody else can see. `EXPLICIT` requires a real verbatim
  `source.quote`; both IMPLICIT_* values require a `derivation_basis` naming what explicit
  material the inference rests on; `IMPLICIT_HIGH_CONFIDENCE` requires the contract's own
  `confidence` field to actually say HIGH/MEDIUM.
- Same-pair contradictory declarations (`DUPLICATES` and `CONFLICTS_WITH` on one pair) and
  self-reference/unknown-endpoint relations are refused as ERRORs.

**Dependency graph is genuinely new code** (no generic DAG utility exists in this repo for this
shape): nodes are validated requirement ids, edges are the four relation kinds, and only the two
HIERARCHICAL kinds (`REFINES`/`EXTENDS`) feed cycle detection and a deterministic topological order
(Kahn's algorithm) -- `DUPLICATES`/`CONFLICTS_WITH` are symmetric facts about a pair and are
reported as edges but never fed into ordering, proven by a dedicated negative control.

**Deliberately bounded, and stated rather than implied closed.** (1) This module extracts nothing
from a spec document: every atomic-requirement/relation test in its suite hand-constructs the
extraction document, exactly as its own docstring requires, because claiming this code
"understood" a spec would be the fabrication the Evidence Truth Rule forbids. (2) It ARBITRATES
nothing: a CONTRADICTORY/CONFLICTS_WITH pair stops there, the same ARBITRATION boundary
`requirement_contract.py` already keeps. (3) There is deliberately no stage gate and no
`dv-harness` CLI verb yet (`cli.py`/`gates.py` are reserved for the integration step) -- the ad hoc
front door is `python -m dv_harness.spec_intelligence spec-map|analyze`. (4) The similarity
thresholds (`DUPLICATE_SIMILARITY_LOW_THRESHOLD = 0.5`, `POSSIBLE_UNDECLARED_DUPLICATE_THRESHOLD =
0.92`) are stated heuristics, not measured constants -- this repo has no labelled corpus of true
duplicate/non-duplicate requirement pairs to calibrate them against.

Proven by `dv_harness_tests/test_spec_intelligence.py` (54 tests): a positive control (a clean
hand-built extraction document passes with zero findings), real negative controls for every rule
above (missing/invalid/unresolvable evidence provenance in both directions, schema-invalid and
non-contract-shaped atomic records, a real `requirement_contract.py` `STATUS_OVERCLAIMED` surfacing
through this module unmodified, every relation rule, a real detected REFINES cycle versus a real
acyclic topological order, and the dedup similarity checks in both directions), and the ONE
genuinely mechanical half -- SpecMap -- driven end to end over real synthetic `.txt` fixtures
through the real `vip_user_guide_distill.distill_user_guide()`, including a document with no
headings at all (honest empty structure) and a refusal when a real producer's own output file is
missing from disk. Both CLI entry points are driven as real subprocesses with their exit codes
asserted.


<!-- S116: moved verbatim from CLAUDE.md original lines 7391-7478 (M4.6 CLAUDE Context Normalization) -->
## Verification Intent IR: the Semantic Bridge Between a Requirement and a Generator (2026-09-06)

Master-prompt gap: nothing in this repo turned a `requirement_contract.py`-shaped requirement into
the INTERPRETIVE shape a downstream generator (vPlan writer, scenario planner, checker/coverage
generator) actually needs -- what is the test's objective, what stimulus does it imply, what should
check it, what should be covered -- let alone a per-domain reading across the structural categories
a real DV requirement routinely cuts across (state-machine, register/CSR, interrupt, reset/clock,
error/recovery, low-power, performance). A repo-wide grep for `verification_intent_ir` /
`VerificationIntentIR` / "semantic bridge" matched nothing. `dv_harness/verification_intent_ir.py` is
that bridge, one record per requirement, and it is deliberately NOT a requirement extractor, a spec
parser, a scenario generator, or a simulation runner -- it reads one requirement record plus whatever
real DUT evidence a caller supplies and emits an interpretive record, never a generated artifact.

**REUSE OVER REINVENT, one producer per domain, four of seven with real DUT evidence wired in.**
`state_machine` reads `protocol_capability.capability_for()`/`derive_status()` -- the real,
code-derived answer to which protocols carry a state-graph model module (e.g. PCIe's
`ltssm_top_level_state_graph`) -- never a second state model. `register_csr` reads
`sys_regmap.required_preconditions()`/`unverifiable_bits()`, scoped to the requirement's own
`protocol`/`feature` as the governed interface -- the same mode-determining-bit classification
`init_seq.py`'s Gate-2 precondition check already uses. `interrupt` and `reset_clock` share ONE real
`interrupt_dma_clock_reset_extraction.extract_interrupt_dma_clock_reset()` call over caller-supplied
RTL/spec text, reading its own `interrupt_architecture`/`clock_reset_extension` blocks verbatim.
`low_power` DIRECTLY reuses `power_intent.py`'s UPF model: a caller may hand in an already-computed
`analyze_power_intent()` report, or `upf_paths` for this module to call the SAME two real functions
itself -- never a re-derivation of power facts. Its `dut_evidence_status` is `power_intent`'s own
PASS/FAIL/NOT_AVAILABLE value, **preserved verbatim rather than translated** into this module's own
vocabulary (disclosed via a `status_vocabulary_source` field naming the different vocabulary), because
section 224's own UNSUPPORTED/UNKNOWN framing is exactly what its NOT_AVAILABLE already means and
remapping it would blur that distinction rather than keep it honest.

**`performance` and `error_recovery` have NO evidence producer anywhere in this harness**, and say
so rather than guessing: no module here derives a throughput/latency/bandwidth target or an
acceptable-error-rate/recovery-time bound from any real source, so both domains always report
`PERFORMANCE_TARGET_UNKNOWN` / `ERROR_TARGET_UNKNOWN` with an empty `dut_evidence` and no source --
proven (by mutation, not by inspection) to stay that way even when every OTHER domain's real evidence
is supplied in the same call, so no combination of real inputs can accidentally manufacture a target.

**Every field is `evidence_provenance.AGENT_SELF_ATTESTED`, and it is not a caller option.** Turning
a requirement's prose into "drive this, check that, cover this" is an interpretive act, not a
measurement -- `evidence_provenance.py`'s vocabulary is imported (never re-typed), and
`VerificationIntentIR.__post_init__()` hardcodes the field and its caveat text regardless of what a
caller passes, because this record's interpretive nature is a fact about what the module IS. That is
a DIFFERENT question from each domain's own DUT evidence: where a real producer exists, that
producer's own real facts and own real status vocabulary are carried through unchanged -- the
INTERPRETATION of what those facts mean for a test stays self-attested; the facts themselves are not.

**Applicability is a structural fact only for `state_machine`/`register_csr`.** Those two need a
requirement to NAME a protocol/interface to look anything up for, so an unresolved one (checked via
the reused `requirement_contract.is_resolved()`, never re-typed sentinel logic) reports
`NOT_APPLICABLE` -- deliberately distinct from `NOT_AVAILABLE` (a domain that was asked and found
nothing). The other five domains are always attempted, gated only on real evidence being supplied.
This module never infers domain relevance from keyword-matching a requirement's prose -- that would
itself be exactly the interpretive overreach the AGENT_SELF_ATTESTED marking exists to flag, not
something a status field could quietly do on its own.

**`requirement_contract.py`'s own verdict on the source requirement is carried through, not
re-derived.** `declares_contract_shape()`/`downstream_consumable()` are imported and reported as
`requirement_contract_status`, so a reader sees in one place whether the SOURCE requirement was
itself fit to generate from, without this module repeating that fifteen-field analysis.

**A module-level vocabulary guard, run at import.** `assert_no_verification_verdict_vocabulary()`
proves this module's own `DUT_EVIDENCE_FOUND`/`DUT_EVIDENCE_PARTIAL`/`PERFORMANCE_TARGET_UNKNOWN`/
`ERROR_TARGET_UNKNOWN` tokens never collide with `models.Status` -- the same discipline
`capability_evolution.py` and `benchmark_dataset.py` already apply to their own vocabularies --
deliberately excluding `NOT_AVAILABLE`/`NOT_APPLICABLE` (this repo's own shared honest-status
convention, not `models.Status` members) and excluding `power_intent`'s PASS/FAIL/NOT_AVAILABLE
passthrough, which is a disclosed, deliberate verbatim reuse rather than a second vocabulary.

**Deliberately bounded, and stated rather than implied closed.** (1) It ARBITRATES and GENERATES
nothing -- no scenario, command.txt, checker or covergroup content is emitted, and there is
deliberately no stage gate. (2) It never re-derives a DUT fact a real module already computes; every
`dut_evidence` block is that producer's own output. (3) No JSON schema file accompanies this IR --
nothing in this repo persists or validates against it yet, so one now would be an artifact kept in
sync with nobody. (4) It has a real CLI (`python -m dv_harness.verification_intent_ir --requirements
<file> [--source-paths ...] [--sys-regmap ...] [--upf ...] [--json]`, exit 0 built / 2 nothing to
build or a supplied input unusable) but no `dv-harness` verb yet and no engine call site -- a REACHED
capability, not a WIRED one, in the same sense several 2026-09-06 additions above already disclose.

Proven by `dv_harness_tests/test_verification_intent_ir.py` (37 tests), against the real
`synthetic_lp_soc.upf` power-intent fixture, a real small RTL fixture built per test for
`interrupt_dma_clock_reset_extraction`'s real line-scanner, a real schema-validated `sys_regmap.json`
-shaped document, and the real `protocol_capability` registry (PCIe's real state-graph model as the
positive control, USB_2_3x's real `model=None` entry as the negative control for "no state model").
Every domain carries at least 3 real negative controls (absent input, malformed input, a structurally
inapplicable requirement), `performance`/`error_recovery` are proven to stay TARGET_UNKNOWN even with
every other domain's real evidence supplied, and a monkeypatch test proves the vocabulary-collision
guard has real detection power rather than merely not tripping by accident.


<!-- S118: moved verbatim from CLAUDE.md original lines 7580-7593 (M4.6 CLAUDE Context Normalization) -->
## vPlan Artifact: Schema + Hierarchy + 9-Dimension Completeness + 15-Value Gap Taxonomy (2026-09-06)

A vPlan (verification plan) is a hierarchy of rows -- sections/features (containers) and leaf verification items -- each of which should carry a requirement link, a verification method, coverage/checker/test linkage, an owner and a priority. Nothing in this repo turned that shape into a checkable artifact: a repo-wide grep for `vplan_artifact`/`VPlanCompletenessReport` matched nothing, and the closest existing mechanism, `env_manifest.py`'s `testplan_correspondence`, answers a narrower, different question -- does a name-matched join of an EXISTING testlist/vPlan/coverage model line up -- over a project's own real `env.manifest.json`. It has no notion of vPlan HIERARCHY, no independent per-dimension status, and no gap taxonomy or next-best-action wiring.

`dv_harness/vplan_artifact.py` is that schema, hierarchy and analysis. It reuses rather than re-mints: `subsystem_discovery`'s READY/PARTIAL/BLOCKED/UNKNOWN readiness words (the same four `golden_flow_readiness.py`/`generation_readiness.py` already reuse), `verification_strategy.STRATEGIES` (SIMULATION/FORMAL/PSS/EMULATION/FPGA_PROTOTYPE) as the known verification-method vocabulary, `memory.CORNER_CASE_RISK_TIERS` (P0..P3) as the priority vocabulary (the same scale `requirement_contract.py`'s own `priority` field already uses), `inference.next_best_action()` through a NEW `VPLAN_GAP_ACTION_CATALOG` (the domain-neutral Gap -> Next-Best-Action engine section 10 forbids re-implementing), and `connectivity.render_markdown_table()` for the optional matrix render.

**Genuinely new**: the vPlan row schema (`validate_vplan_row`/`validate_vplan_document`, fail-closed via `VPlanArtifactValidationError` for a STRUCTURAL defect only); the hierarchy builder (`build_vplan_hierarchy`, a single-parent-pointer tree-walk detecting duplicate ids, orphan parent references and cycles as reported gaps, never raised, since these are semantic-but-shape-valid facts); the NINE independent completeness dimensions (`analyze_vplan_completeness`/`VPlanCompletenessReport`) -- HIERARCHY_INTEGRITY, REQUIREMENT_COVERAGE, VERIFICATION_METHOD_ASSIGNMENT, COVERAGE_MODEL_LINKAGE, CHECKER_LINKAGE, TEST_STIMULUS_LINKAGE, OWNERSHIP_ASSIGNMENT, PRIORITY_ASSIGNMENT, INTENT_CROSS_CONSISTENCY -- each scored, gapped and reasoned about independently and NEVER averaged/weighted/folded into one number, the same non-collapsing-status discipline `requirement_contract.py`'s five-value status vocabulary and `golden_flow_readiness.py`'s per-row Status column already hold; and the FIFTEEN-value gap taxonomy (`GAP_TAXONOMY`), each code mapped to exactly one dimension (`GAP_TO_DIMENSION`) and a severity (`GAP_SEVERITY`: BLOCKED for a structural/false-claim defect such as a dangling reference or a cycle, PARTIAL for an honest absence such as an unmapped requirement or a missing owner) -- both mappings held total by `assert_gap_taxonomy_total()` at import time, so a future edit that adds a gap without wiring it fails a test rather than silently reporting `UNKNOWN` severity.

**Why this takes generic dict/list input rather than importing a real producer.** Per this batch's file-safety scope, this module must not import `spec_intelligence.py` or `verification_intent_ir.py` -- both are owned by OTHER, concurrently-running tasks in this same batch. `vplan_rows`, `requirements` and `verification_intents` are therefore accepted as plain lists of dicts, documented at the top of `analyze_vplan_completeness()` as the shape either sibling module's real output would need to be reduced to (e.g. `{"id": rec.requirement_id}` / `{"id": rec.intent_id, "verification_method": rec.method}`) to feed this analysis with no change to this module's own logic once either lands.

**Deliberately bounded, stated rather than implied closed.** It reads a vPlan RECORD (plus optional requirement/intent records); it does not parse a specification, does not extract vPlan rows from prose, and does not check a vPlan against RTL, a register map, or a real coverage database. Coverage/checker/test-stimulus linkage (dimensions 4-6) is evaluated ONLY over leaf rows whose declared `verification_method` is coverage/test-relevant (`SIMULATION`/`EMULATION`/`PSS` for coverage+checker; `SIMULATION`/`EMULATION` for test-stimulus, since PSS generates its own scenarios rather than citing a pre-existing test) -- a `FORMAL`-only vPlan reports those three dimensions honestly `UNKNOWN` with zero applicable rows rather than a fabricated `READY`. `requirements`/`verification_intents` cross-checks report `UNKNOWN` with a real reason when the caller supplies `None`, never a silent clean pass. It DECIDES, APPROVES and RUNS nothing: no stage executes, no gate script is invoked, no file is written, and there is deliberately no `STAGE_GATES` entry -- a completeness report is an input to a human's vPlan-review decision, exactly like `golden_flow_readiness.py`'s and `generation_readiness.py`'s own matrices. `ControlPlane.approve()`, `policy.can_signoff()`, `assert_human_approval()` and the PR-only main/master governance are untouched and unreferenced.

Proven by `dv_harness_tests/test_vplan_artifact.py` (37 tests): the clean positive path across all 9 dimensions over a fully-populated fixture (two container sections, three leaves spanning SIMULATION/FORMAL/EMULATION); taxonomy/dimension totality self-checks; and real negative controls for every one of the 15 gap codes -- a duplicate row id, an orphan parent reference, a 3-node `parent_id` cycle (all `BLOCKED` on `HIERARCHY_INTEGRITY`), a dangling requirement/intent reference (`BLOCKED`, proven distinct from the honest `PARTIAL` of an unmapped requirement/unreferenced intent), an unrecognized `verification_method`, the FORMAL-only honest-`UNKNOWN` case for dimensions 4-6, a missing owner/priority, an unrecognized priority value, a row/intent `verification_method` contradiction, next-best-action wiring returning exactly the present gap codes with `source == "vplan_artifact"` and never touching the filesystem, schema-validation rejections (non-mapping row, missing id, non-string-list field, non-list document), and the empty-vplan case reporting `UNKNOWN` -- never a fabricated `READY` -- across every one of the 9 dimensions.


<!-- S119: moved verbatim from CLAUDE.md original lines 7594-7689 (M4.6 CLAUDE Context Normalization) -->
## Spec/vPlan Semantic Delta: Per-Requirement ADDED/MODIFIED/REMOVED/REVALIDATION_REQUIRED (2026-09-06)

Nothing in this repo compared two requirement-IR snapshots to say which individual requirements
changed and how. `grep -rn "spec_vplan_delta\|requirement.*delta\|semantic.*diff" --include=*.py .`
matched nothing executable before this module.

**A genuinely different axis from `change_impact.py`, confirmed by reading it rather than assumed.**
`change_impact.py`'s own docstring is explicit: it computes a real `git diff --name-only
<base>..<head>` over FILES, resolved to RTL modules via the evidence DB and to REQ_ID/VPLAN_ID/
PATTERN_ID/COVERAGE_ID via the real `.dv-harness/requirements.csv` traceability registry
(`load_trace_registry()`). It has no notion of a requirement record's own CONTENT and never opens two
requirement documents to compare them -- "which files changed on disk, and which tests does that
reach." A spec revision can rewrite a requirement's expected behaviour with zero git diff in this
project at all (the source is a spec document, which may live outside this repo's own history), and
that file-diff axis is structurally blind to it. `dv_harness/spec_vplan_delta.py` answers the
question `change_impact.py` cannot: given two requirement-IR SNAPSHOTS (a previously-recorded
baseline and a freshly re-extracted current set), which INDIVIDUAL requirement changed and how,
independent of any file-system diff. The two compose at a caller (file-diff selects regression scope;
content-diff selects which vPlan items need re-authoring); neither subsumes the other. Also distinct
from `vplan_baseline.py`, which freezes a whole vPlan document's identity as ONE aggregate hash with a
single VALID/REVALIDATION_REQUIRED/... verdict over the entire set -- this module reports a
structured PER-REQUIREMENT classification of what moved and how, a granularity `vplan_baseline.py`'s
own docstring explicitly leaves to "a project's own vPlan tooling."

**No requirement-IR producer is guaranteed to exist yet, so `before`/`after` are generic, duck-typed
parameters** -- a list of dicts, or a dict carrying a top-level `requirements` list (the same document
convention `requirement_contract.execute_verb()` already uses, reused rather than inventing a second
one). Identity is resolved from `requirement_id` (section 184's spelling), then `req_id` (the
traceability registry's / older-shape spelling), then `id`, or a caller-declared `identity_field`.

**Five statuses, four of them requested, the fifth kept for honest accounting.** ADDED/REMOVED --
identity present in only one snapshot. MODIFIED -- at least one CONTENT field (the requirement's
actual behavioural claim) differs. REVALIDATION_REQUIRED -- content is byte-identical but a
PROVENANCE field differs (source citation, confidence, priority/criticality, a filed ambiguity/
contradiction, schema version) -- the behaviour nobody rewrote, but the evidence backing it moved, so
a human should re-confirm the extraction still holds. Spelled identically to `waiver_store.py`'s own
`WAIVER_STATUSES` entry of the same name (this project's established word for "neither provably fine
nor provably wrong"), though a distinct axis here. UNCHANGED -- nothing differs; reported so "nothing
changed" is never indistinguishable from "we didn't check."

**Which fields count as CONTENT vs. PROVENANCE is shape-agnostic, not a special case per record
shape.** `content_fields_for()` treats every field present in either record as content UNLESS it is in
`REVALIDATION_ONLY_FIELD_NAMES` (source/confidence/status/priority/criticality/ambiguities/
contradictions/support_status/design_evidence/contract_schema_version/notes/revision/spec_revision/
extracted_at/extracted_by/confirmed_by) -- `requirement_contract.CONTRACT_TEXT_FIELDS` (feature/
protocol/configuration/precondition/stimulus/expected_result/observability/checker/coverage_intent)
fall out as content with no separate contract-shaped code path, since none of them is in that set. A
caller may override `content_fields`/`revalidation_fields` entirely for a different IR shape.
`classify_requirement_delta()` is worst-wins: a real content difference -> MODIFIED, checked FIRST, so
a simultaneous content+provenance edit is never demoted to a mere revalidation note. None, an
all-whitespace string, and a missing key are normalized equal, so re-serialization noise (an explicit
`""` where the other side simply omitted the key) never manufactures a false MODIFIED.

**vPlan linkage is READ, never invented.** When a caller supplies `root`, every non-UNCHANGED
requirement is cross-referenced against the REAL `.dv-harness/requirements.csv` registry via
`change_impact.load_trace_registry()` (imported, not re-parsed), attaching the real VPLAN_ID/
SCENARIO_ID/COMMAND_ID/PATTERN_ID/COVERAGE_ID the registry already asserts. Three honestly distinct
outcomes: `NOT_REQUESTED` (no root given -- the caller chose not to ask), `NO_REGISTRY_ROW` (asked;
the registry -- including one that does not exist on disk at all -- has nothing for this id), and
`LINKED` (a real row found). **Also reuses, never re-derives**: when both sides of a delta declare the
section-184 contract shape (`requirement_contract.declares_contract_shape()`), the REAL
`requirement_contract.derive_status()` is called on each side and any movement in the requirement's
own re-derived COMPLETE/PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN status is surfaced as
`derived_status_delta` -- extra evidence, never part of the four-status classification itself, and
absent entirely for a non-contract-shaped record.

`python -m dv_harness.spec_vplan_delta --before <baseline.json> --after <current.json> [--root <dir>]
[--json]`, sharing one `execute_verb()` with the module's own callers. Exit 0 NO_DELTA, 1 DELTA_FOUND
(a real ADDED/MODIFIED/REMOVED/REVALIDATION_REQUIRED item exists), 2 NOT_AVAILABLE (a file could not
be read, or both snapshots are empty -- never a clean pass on nothing).

**Deliberately bounded, and stated rather than implied closed.** (1) It compares two ALREADY-EXTRACTED
requirement-IR snapshots; it does not parse a spec document into requirement-IR records itself -- that
extraction problem has no canonical producer in this repo yet, which is exactly why `before`/`after`
are generic parameters rather than a call into one. (2) It never arbitrates which snapshot is "right"
when both look equally complete -- the same boundary `requirement_contract.py` keeps for
CONTRADICTORY requirements. (3) It writes nothing and runs no gate: no approval is minted, no stage
advances, and there is deliberately no `STAGE_GATES` entry -- a gate that passed because nobody
supplied a baseline yet would be worse than none. (4) An unresolvable identity is reported (a
`duplicate_identities`/`unidentified_records` count), never silently dropped from the total.

Proven by `dv_harness_tests/test_spec_vplan_delta.py` (20 tests) against synthetic requirement-IR
fixtures constructed directly (some declaring the real section-184 contract shape, some fully
generic), since no requirement-IR producer is guaranteed to exist. Negative controls: an
empty-string-vs-missing field is not a false MODIFIED; a real content change outranks a simultaneous
provenance change; a duplicate identity is reported, never silently merged; an unidentified record is
counted, never dropped; both-empty inputs report NOT_AVAILABLE, never a pass; a caller-declared
`identity_field` is honored; `derived_status_delta` is present and correct only for contract-shaped
records. Three tests write a REAL `.dv-harness/requirements.csv` and cross-check the resulting linkage
against `change_impact.load_trace_registry()` called directly, including the honest
NO_REGISTRY_ROW-vs-no-registry-file distinction. A sanity test confirms `change_impact.py` has no
content-diff function of its own and that its real entry point needs actual git plumbing (`NO_GIT`
over a bare directory with no `.git`). Both the module's Python API and its
`python -m dv_harness.spec_vplan_delta` CLI (including `--root`) are driven end to end, the CLI as
real subprocesses with DELTA_FOUND/NO_DELTA/NOT_AVAILABLE exit codes asserted.


<!-- S121: moved verbatim from CLAUDE.md original lines 7704-7715 (M4.6 CLAUDE Context Normalization) -->
## Protocol Compliance Aggregation: Scoreboard PASS Never Outranks a Real Checker Violation (2026-09-06)

This harness has no formal protocol-checker TOOL, and `dv_harness/protocol_compliance_aggregation.py` does not build one -- verified before writing anything: `vip_distill.py`'s real `SOURCE_KINDS` is exactly `("sim_log", "job_record", "fsdbreport", "combined")`, with no `"protocol_checker"` kind, and none of its `detail` dicts (epilogue/signatures/counts/lsf_status/sim_status/topic/fsdbreport) ever carries a checker-specific verdict field; `dv_harness/uvm_generator/protocol_model_layer.py` -- the other real module this task named to read -- carries no `verdict`/`checker`/`PASS`/`FAIL`/`violation` token at all (it compiles LTSSM state-transition legality into SVA assertions; it produces no runtime checker RESULT). So a real protocol-checker verdict, distinct from the scoreboard verdict `vip_distill.py` already normalizes, is not something this repository's own evidence pipeline produces today, and this module says so rather than inventing one.

What it builds is only the AGGREGATION RULE: given a stage's real scoreboard PASS/FAIL verdict (the real, already-normalized `vip_distill.py` envelope's own `verdict` field, read via `evidence_db.py`'s real `normalized_evidence` table -- reusing its real column list rather than re-parsing evidence a second way) plus, IF a real protocol-checker verdict is present in the SAME evidence set, that verdict too -- **a scoreboard PASS alongside a real protocol-checker violation is still an overall FAIL**, and **absent protocol-checker evidence reports `NOT_CHECKED`, distinct from `CLEAN`/`PASS`, never assumed clean**. `_decide_overall()`'s priority order: a real checker FAIL overrides everything (including a scoreboard PASS and even an absent scoreboard); otherwise a scoreboard FAIL is overall FAIL; no scoreboard evidence at all is `NOT_AVAILABLE`, never a default PASS; either side carrying a real-but-unrecognized verdict string is `UNKNOWN`, never rounded to PASS or FAIL; scoreboard PASS + checker PASS is PASS; scoreboard PASS + checker `NOT_CHECKED` is still PASS, but the report always carries `protocol_checker_status: "NOT_CHECKED"` alongside it so it can never be read as a verified-clean protocol result.

`SCOREBOARD_PASS_VERDICTS`/`SCOREBOARD_FAIL_VERDICTS` cite the same real `vip_distill.py` verdict vocabulary `golden_scenario.py`'s own `PASS_VERDICTS` already documents, independently restated rather than imported: `golden_scenario.py` is one of the files a separate, already-running batch of agents is concurrently editing, and this module deliberately imports neither it nor any other file under concurrent edit in either running batch. `load_normalized_evidence_rows()` queries the real `evidence_db.py` `normalized_evidence` table directly (positional-tuple results zipped against the real, verified column order, avoiding a known real fetchall()-as-dict indexing defect disclosed elsewhere in this codebase) and re-shapes rows back into the real `vip_distill.py` envelope dict shape. `extract_verdicts_from_evidence_set()` is duck-typed over any sequence of such dicts, so it consumes evidence in memory, evidence read back from a real database, or -- once a real protocol-checker producer is ever built -- that producer's own output, without importing a module that does not exist yet. `PROTOCOL_CHECKER_DETAIL_KEYS` (`protocol_checker_verdict`/`vip_checker_verdict`/`checker_verdict`, read from a normalized_evidence row's own free-form `detail` dict) is a disclosed, honest EXTENSION POINT -- explicitly not a claim that any real producer writes one today.

**Deliberately bounded, and stated rather than implied closed.** (1) No formal protocol-checker tool exists or was built here, per this task's own instruction -- the module aggregates whatever real checker evidence a future tool might one day produce, and honestly reports `NOT_CHECKED` until one does. (2) There is deliberately no stage gate and no `gates.py`/`cli.py` change -- this task's scope was the aggregation module alone; a `dv-harness` verb or `STAGE_GATES` entry, if ever wanted, is for a separate integration step. (3) It decides and authorizes nothing beyond reporting: no approval/governance mechanism is referenced.

Proven by `dv_harness_tests/test_protocol_compliance_aggregation.py` (20 tests) against a REAL DuckDB `EvidenceStore` and REAL `vip_distill.distill_sim_log()` envelopes for both a PASSING and a FAILING synthetic sim.log in this project's own documented FINAL CHECK epilogue format -- never hand-typed evidence shaped to look real. The central proof records a real scoreboard-PASS row and a checker-violation row (this repo's honest extension-point shape) against the SAME `job_id` in one real `evidence.duckdb`, and asserts the aggregation reads back out as an overall FAIL. Negative controls: no scoreboard evidence never reads as PASS; an unrecognized scoreboard or checker verdict string reads UNKNOWN, never PASS; a real checker FAIL overrides even an absent scoreboard; fsdbreport rows (which vip_distill.py's own docstring says carry no verdict concept) never contribute a scoreboard verdict even if one is stray-present; an unrelated job's evidence never bleeds into another job's aggregation; and a bare, just-initialized evidence database reports `NOT_AVAILABLE`, never a false clean PASS.


<!-- S122: moved verbatim from CLAUDE.md original lines 7716-7788 (M4.6 CLAUDE Context Normalization) -->
## Spec/Datasheet Structural Map: `dv_harness/spec_doc_map.py` (2026-09-06)

`vip_user_guide_distill.py` already turns a VIP user guide PDF into a bounded, offline reference
artifact. Nothing in this repo did the analogous thing for the OTHER document family a
verification environment is built from -- the DUT's own spec/datasheet/programming-guide PDFs.
`env_manifest.py`'s Tier-1 policy already denies raw PDF originals into runtime context and names
`vip_user_guide_distill.py` as the route forward for a VIP user guide, but a DUT spec PDF had no
route at all: an agent asking "what page is the register map chapter on" or "where is Table 4-3"
had no bounded artifact to answer from and no honest way to get one short of opening the whole PDF.

`dv_harness/spec_doc_map.py` closes that, extending `vip_user_guide_distill.py`'s real `pypdf`
extraction PATTERN -- the same `pypdf.PdfReader(...).pages[i].extract_text()` call, the same
"raise rather than silently produce an empty/partial artifact" discipline, the same
mechanically-detected numbered-heading regex idea -- without editing that file. It deliberately
does not import from it either: this task's contract narrows extraction to STRUCTURE ONLY (never a
full-text extract, even as a targeted-read byproduct), while `vip_user_guide_distill.py`'s own
contract always ALSO writes a `.fulltext.txt`; there is no narrower public entry point in that
module to call instead of its always-wider `distill_user_guide()`. So this module re-derives the
~15 lines of straightforward `pypdf` usage rather than importing another module's private helpers
or forcing a wider artifact than this task allows.

**What it extracts, mechanically, never by interpretation.** A numbered heading ("4.3.1 Link
Training") or a "Chapter N: Title" heading, a Table caption ("Table 4-1: Register Summary"), and --
computed from those -- a register-CHAPTER's page range: a chapter-level (`level == 1`, no dot in
its number) heading whose own title contains a word-bounded `register(s)?`/`register map`/`csr`
match, bounded from its own detected start page to the page before the next detected chapter's
start page (or the document's last page for the final chapter). The word-boundary match is
deliberate: a chapter titled "Registration Procedures" must not be credited as a register-map
chapter merely for sharing a substring, and a dedicated negative-control test proves it is not.
Register-titled SUBSECTIONS still appear in the plain section index but are never given their own
page range, because a subsection's true end is ambiguous from a mechanical scan alone. Table
CONTENT (rows, fields) is never read -- only the caption line and its page.

**Two artifacts per document, both structure-only, and there is deliberately no full-text
byproduct at all** -- unlike `vip_user_guide_distill.py`, which always produces one:
`<stem>.structure_map.json` (schema-versioned record: section index, table index, register-chapter
ranges, source/extractor identity) and `<stem>.structure_map.md` (the same content as a
human-readable navigation table). Neither file contains one word of document body prose; a test
asserts the persisted record and markdown never contain the fixture's own prose sentences.

**Extractor honesty.** A `.pdf` source requires `pypdf`; when it is not installed,
`extract_spec_doc_map()` raises `SpecDocMapError` naming the real missing dependency rather than
silently producing an empty/partial structure map. A missing source file and an unsupported suffix
raise the same way. `execute_verb()` -- the CLI/reporting layer -- turns any of those into the
honest `status: "NOT_AVAILABLE"` this task's contract requires, carrying the real exception text. A
`.txt`/`.md` (pre-extracted) source is read directly and records
`method="pre_extracted_text_structure_scan"`; page numbers are honestly `null` on that path, since
no real page boundary exists to report.

**Deliberately bounded, and stated rather than implied closed.** (1) Heading/caption detection is a
line-pattern scan, not layout/typography analysis -- an un-numbered heading with no "Chapter"
keyword contributes nothing, and that is a real, reported zero rather than a guess (proven by a
dedicated no-structure fixture). (2) It decides nothing beyond reporting: no build, job, approval,
or stage gate is touched, and there is deliberately no `STAGE_GATES` entry -- a structural map is an
input to a human/agent's later targeted reading, never a verification verdict. (3) There is no
`dv-harness` CLI verb (`cli.py` is out of this task's file-safety scope); the front door is
`python -m dv_harness.spec_doc_map extract|show`.

Proven by `dv_harness_tests/test_spec_doc_map.py` (17 tests) against REAL PDFs built with
`reportlab` and read back with real `pypdf` -- never a hand-typed byte string. The core positive
test builds a real 3-page synthetic "DUT spec" PDF (chapter 1 Overview, chapter 4 Register Map with
a subsection and a table, chapter 5 Electrical Characteristics with its own table) and asserts the
section index, table index, and the single register-chapter's computed `[2, 2]` page range, plus
that no prose sentence from the fixture ever appears in either persisted artifact. Negative
controls: a structure-free PDF reports real zeros rather than crashing or guessing; a
"Registration Procedures" chapter is proven NOT to be credited as a register chapter
(word-boundary detection power); a missing source file, an unsupported suffix, a simulated missing
`pypdf` dependency, and a malformed/foreign JSON record are all refused with the real reason rather
than silently accepted; a `.txt` source reports honestly `null` pages throughout; and both
`execute_verb()` and the real `python -m dv_harness.spec_doc_map` CLI (both verbs, plus the
NOT_AVAILABLE exit-2 path) are driven end to end, including as real subprocesses.



<!-- S128: moved verbatim from CLAUDE.md original lines 7985-8046 (M4.6 CLAUDE Context Normalization) -->
## Register-to-RTL Trace: the Parser-vs-Elaboration Boundary, Applied to Registers (2026-09-06)

A register field's declared control/status meaning (`register_map.schema.json`'s own `fields[].name`/
`description`) had no code path connecting it to the RTL a generated environment actually binds
against. The closest neighbours both operate one level away: `sys_regmap.py` derives mode-determining
control bits for a Gate-2 precondition, and `connectivity.py` derives bind-location/tier confidence for
a whole INTERFACE -- neither asks "does the RTL this project parsed even contain a signal this specific
register field's name plausibly refers to". A repo-wide grep for `register_rtl_trace`/
`RegisterRtlTrace`/`TRACE_CONFIRMED`/`TRACE_PARTIAL` matched nothing executable before this module.

`dv_harness/register_rtl_trace.py` attempts that trace, using `verible_parser.py`'s existing
declaration-level parse -- import only, read-only, no second SystemVerilog parser in this package.

**The parser-vs-elaboration boundary drives every status this module can report**, the same discipline
`uvm_structural_lint.py` already applies to its own declaration-level limits, applied here to registers
instead of UVM classes. `verible_parser.py` parses SOURCE TEXT into a syntax tree; it never elaborates
-- it does not resolve a `generate`/`ifdef` condition, does not evaluate a parameter, does not simulate
a single clock edge, and does not know what value any signal ever actually carries. So the STRONGEST
claim this module can ever make is "a signal (or port) with this name exists in the parsed sources, and
it is wired to something (not just an unused local declaration)". That proves the NAME is real and
REFERENCED. It never proves that signal is the field's control/status logic at run time, that the
field's declared semantics match what the RTL actually does with it, or that the wiring is reachable
under the design's real configuration. `TRACE_CONFIRMED` is this module's ceiling, not a claim of
verified behavior -- and it is worded that way in every `TRACE_CONFIRMED` result's own `reason` text.

**Four statuses, and the rule that keeps them honest.** `TRACE_CONFIRMED`: exactly one RTL site (port
or signal) matches the searched name exactly (case/underscore-normalized), and that site is REFERENCED
elsewhere in the parsed sources (a port, or an internal signal appearing in a continuous assign's or an
instance connection's own net list) -- unambiguous existence plus reference, nothing stronger.
`TRACE_PARTIAL`: a plausible reference exists but is AMBIGUOUS -- more than one exact-name site, an
exact-name site that is only a bare unused declaration, or only a substring/fuzzy name match -- never
silently upgraded to `TRACE_CONFIRMED` no matter how plausible the fuzzy match looks; this is the
module's one hard rule. `TRACE_NOT_FOUND`: a real search was performed over real parsed RTL and no
matching site, exact or fuzzy, was found anywhere. `BLOCKED`: the trace could not be ATTEMPTED at all
(no field name to search for, no parsed RTL supplied, or verible itself could not produce a parse) --
distinct from `TRACE_NOT_FOUND` on purpose, since "we never looked" must never be reported as "we
looked and found nothing".

**Input is deliberately duck-typed and independent of any other concurrently-developed module.** This
file imports only `verible_parser.py` and `env_manifest.py`'s existing `load_register_map()` /
`RegisterMapValidationError` -- both established modules outside the batch this task was built in.
Register fields may be handed in as plain dicts (the shape `register_map.schema.json`'s own `fields[]`
entries already have, optionally carrying `register_name`/`block_name` context and an extra
`rtl_signal_hint` key for a document-stated expected RTL signal name) or as `RegisterFieldRef`
instances built from one.

`trace_register_field()`/`trace_register_fields()` trace one or many fields; `collect_rtl_sites()` and
`parse_rtl_sources()` build the searchable RTL corpus once for reuse across many fields rather than
re-parsing per field. `python -m dv_harness.register_rtl_trace` is the front door
(`execute_verb()`/`main()`), rendering a report via `format_report()`/`summarize_trace()`.

Proven by `dv_harness_tests/test_register_rtl_trace.py` (31 tests) against small real synthetic RTL
fixtures parsed through the real verible subprocess: `TRACE_CONFIRMED` is proven only on an unambiguous
exact-name, referenced site; the ambiguity rule is proven directly -- two conflicting declarations of
the same signal name, and an exact-name-but-unused declaration, both stay `TRACE_PARTIAL` and never
upgrade; `BLOCKED` is proven distinct from `TRACE_NOT_FOUND` on an empty/unparseable corpus versus a
real search that found nothing.

**Disclosed residual**: this closes register-field-to-RTL-name traceability only, at the parser's own
declaration-level ceiling. It runs no build, no simulation, and no gate of its own -- ad hoc via
`python -m dv_harness.register_rtl_trace`.


<!-- S129: moved verbatim from CLAUDE.md original lines 8047-8110 (M4.6 CLAUDE Context Normalization) -->
## Change-Cascade Impact Table: "What Does This Change Make Suspect?" (2026-09-06)

This project produces a great many derived artifacts off a small set of upstream facts -- a VIP
release, a chunk of DUT RTL, a register map, an address map, a bind topology, a UPF power-intent file,
a requirement record, a waiver, a configuration-variant space, a subsystem registry entry, a
testplan/vPlan correspondence. Each of those facts already has a real producer somewhere in this
codebase, and several producers already compute a NARROW, re-derive-one-thing staleness check of their
own (`golden_scenario.evaluate_freshness()` for one capsule, `waiver_store.derive_status()` for one
waiver, `signoff_export.evaluate_freeze_invalidation()` for one frozen baseline). None of them, and
nothing anywhere in this repo, answered the WIDER question a human or an agent actually has the instant
one of those upstream facts changes: "which OTHER already-computed artifacts across this whole harness
does that change make suspect, and why, specifically enough to know what to re-run?" A repo-wide grep
for `change_cascade`/`ChangeCascade`/`downstream_artifact`/`cascade_impact` matched nothing executable
before this module. An agent who bumped a VIP version had no single place to be told that the VIP API
cards, the connectivity gate verdicts, and any golden scenario capsule watching that tool version were
all now suspect -- each fact individually WAS discoverable by reading three different modules' own
narrow staleness logic, but nothing joined them into one lookup keyed on "what changed".

`dv_harness/change_cascade.py` is that lookup, and only that. It is a small, hand-curated
`CHANGE_CASCADE_TABLE`: `{changed_field -> downstream artifacts}`, each downstream entry citing its own
real `producing_module` -- so the citation is checkable rather than trusted prose.
`assert_producing_modules_resolve()` holds every cited module to the same "does the cited module really
import" discipline `protocol_capability.py`'s registry and `golden_flow_readiness.py`'s row table
already apply to themselves. `known_changed_fields()` lists the declared vocabulary;
`cascade_for_changed_field()` answers one field; `assess_changes()` takes a plain, duck-typed iterable
(a bare field-name string, or any dict/object carrying a `field` key/attribute) and reports the combined
impact. It does NOT itself re-derive any staleness verdict -- that stays each artifact's own real
producer's job -- and it never widens the table by guessing: an undeclared `changed_field` reports
`UNKNOWN_FIELD` naming the real declared fields, never a silently empty "nothing downstream" result, so
an unmapped change reads as unknown impact, never zero impact.

**Reuse, not reinvention, of `question_queue.py`'s revocation mechanism.** When a changed field
invalidates the very fact an earlier Tier-2 auto-assumption or human answer was keyed on, the sanctioned
undo is already real: `QuestionQueueStore.revoke_decision()`. `revoke_stale_decisions()` is a thin,
explicit caller of that existing function -- it invents no second decisions store and no second
revocation mechanic. It is deliberately NOT automatic: this module has no way to know, for an arbitrary
project, which `question_key` strings that project's own question-queue callers used for a decision a
given field change now invalidates (question-key naming is each caller's own convention), so guessing
one would be exactly the fabrication the Evidence Truth Rule forbids. A caller who already knows which
decision(s) a change invalidated supplies those `question_key` strings explicitly, and this module
performs the real revocation call one key at a time, treating "nothing was on file for that key"
(`revoke_decision()`'s own `KeyError`) as an honest `NO_LIVE_DECISION` outcome rather than an error.

**Decoupled from every other concurrently-developed module, on purpose.** Several other gap-closure
items built alongside this one would be natural upstream producers of "what changed" (a real
diff-detection module, a subsystem change-request tracker, ...). None of them is imported here --
`assess_changes()` takes a plain, duck-typed iterable so a future detector's real output can be handed
to this function unmodified, once that detector exists, as long as each of its records names the field
it changed. Until then, a caller (human, agent, or a hand-rolled diff check) supplies the list of
changed fields directly.

Front door: `python -m dv_harness.change_cascade assess|revoke --root <dir> [--json]`
(`execute_verb()`/`main()`), rendering via `format_cascade_report()`/`format_revoke_outcomes()`.

Proven by `dv_harness_tests/test_change_cascade.py` (26 tests): every declared `changed_field` is
proven to resolve to real, importable `producing_module` citations; an undeclared field is proven to
report `UNKNOWN_FIELD` rather than a silent empty result; `revoke_stale_decisions()` is proven against a
real `QuestionQueueStore` on disk, including the honest `NO_LIVE_DECISION` outcome for a key nothing was
ever filed under; and `assess_changes()` is proven over both bare strings and dict/object entries.

**Disclosed residual**: it records and reports, and arbitrates nothing -- no approval/governance
mechanism is referenced. There is deliberately no stage gate. Revoking a decision is always an explicit,
caller-supplied act; nothing here auto-revokes on its own initiative.


<!-- S130: moved verbatim from CLAUDE.md original lines 8111-8122 (M4.6 CLAUDE Context Normalization) -->
## Requirement Risk IR (`dv_harness/requirement_risk_ir.py`)

Scores one requirement across six risk factors -- `complexity`, `change_frequency`, `bug_history`, `customer_impact`, `observability_difficulty`, `protocol_criticality` -- and, per the Evidence Truth Rule, never blends them into an opaque number without saying which of three honest states each factor is actually in:

- **MEASURED** -- `change_frequency` is the only mechanically-produced factor. It runs `git log --oneline -- <source_file>` under `project_root` through a read-only, degrade-never-raise `_git()` wrapper (the same contract as `trend_analysis._git()`/`change_impact._git()`, reimplemented locally rather than imported, since this module accepts `requirement_facts` as a fully generic/duck-typed parameter and never imports `requirement_contract.py` or any sibling module), then buckets the real commit count onto a documented 1-5 scale (0 commits -> 1, 1-2 -> 2, 3-5 -> 3, 6-10 -> 4, 11+ -> 5). Missing git, a timeout, a non-git-repo root, a nonexistent root, or missing `source_file`/`project_root` all degrade to `NOT_AVAILABLE` with a real reason -- never a guessed score. A real zero-commit result for a path that genuinely has no history is still `MEASURED` (score 1): that count is real evidence, not absent evidence.
- **DECLARED** -- `complexity`, `customer_impact`, `observability_difficulty`, and `protocol_criticality` have no mechanical producer anywhere in this repo. Each is read only from the caller's `requirement_facts` (dict `.get` or attribute access), validated as a real integer in `[1, 5]` (booleans explicitly rejected despite being an `int` subclass in Python), and reported `DECLARED` -- visibly distinct from a measured value. A missing or invalid declaration is `NOT_AVAILABLE`, never silently defaulted to a middle-of-scale guess.
- **NOT_AVAILABLE always** -- `bug_history` has no real producer anywhere in this repo (verified by repo-wide grep before this module was written: no defect tracker, no bug database, no incident log) and, per this task's own explicit rule, has no legitimate caller-declaration path either. `bug_history_factor()` always returns `NOT_AVAILABLE` and ignores any `bug_history` key a caller's facts might happen to carry.

`assess_requirement_risk(requirement_facts, *, source_file=None, project_root=None)` returns a `RequirementRiskProfile` with a `composite_score` computed as the mean of only the AVAILABLE factors, always reported alongside `available_factor_count`, `missing_factors`, and `coverage` (`"N/6"`) so a partial profile can never be mistaken for a complete one. `format_risk_report()` renders it for humans; a thin `main()` CLI (`python -m dv_harness.requirement_risk_ir --facts-file ... --source-file ... --project-root ...`) follows the same argparse shape as `change_cascade.py`/`golden_scenario.py`. The module reads and reports only -- it writes nothing, gates nothing, and takes no governance action.

Tested in `dv_harness_tests/test_requirement_risk_ir.py` (20 tests) against a real throwaway git repository built via subprocess (mirroring `test_trend_analysis.py`'s `rtl_repo` fixture), with real, distinct commit counts driving real bucket assignments, plus negative controls for every `NOT_AVAILABLE` degradation path (missing git inputs, non-git directory, nonexistent root, missing/invalid/out-of-range/boolean declared values) and a dedicated check that `bug_history` stays `NOT_AVAILABLE` even when a caller's facts supply one.


<!-- S131: moved verbatim from CLAUDE.md original lines 8123-8206 (M4.6 CLAUDE Context Normalization) -->
## Potential Spec-Gap Detector: 5 Structural-Absence Patterns Over a Requirement Set (2026-09-06)

A specification can be internally consistent sentence-by-sentence and still be STRUCTURALLY
incomplete: it defines what happens when a transfer completes, never what happens when it errors;
defines an enable bit, never a disable path; defines an interrupt being asserted, never how it is
cleared; defines a reset, never what happens to whatever was already in flight when that reset
lands; defines an error condition, never a recovery path back out. Nothing in this repo asked that
question over a requirement SET. `requirement_contract.py` (section 184) checks whether a SINGLE
requirement record is internally coherent -- its own fifteen fields present, its own declared
status honestly re-derived from its own content -- and never compares one requirement against
another. `spec_vplan_delta.py` and the `spec_to_vplan_*` gates compare a spec against a vPlan, a
different axis entirely. A repo-wide search before building confirmed no code anywhere paired a
"normal condition" requirement against an "error condition" one, an "enable" against a "disable",
an "interrupt assert" against an "interrupt clear", a "reset" against "in-flight operation
behavior", or an "error condition" against "error recovery".

`dv_harness/potential_spec_gap_detector.py` closes exactly that, and only that. It is deliberately
narrow, duck-typed, and self-contained: it imports nothing from `dv_harness` (not even
`dv_harness.models`) and nothing from any other module in this batch, so it stays fully decoupled
from whichever concurrently-running effort eventually owns the canonical requirement-set shape. A
"requirement" is any `Mapping` carrying free text under `text`/`description`/`expected_behavior`/
`condition`/`behavior`/`spec_text`/`requirement_text`, optionally an id under `id`/`req_id`/
`requirement_id`/`name`, and optionally an explicit correlation key under `subject`/`signal`/
`feature`/`operation`/`condition_name` (preferred over anything derived from prose, since a
human-declared subject is a stronger signal than this module's own guess). A requirement with no
usable text contributes nothing and is recorded as skipped, never silently dropped or guessed at.

**Classification is a lexical keyword scan over each requirement's own text -- a heuristic, stated
as one, never a certainty.** Nine fixed-vocabulary flags (normal-condition, error-condition,
enable, disable, interrupt-assert, interrupt-clear, reset, in-flight-operation-behavior,
error-recovery) are each derived from a small, explicit phrase list, matched with `\b`
word-boundary regex for single tokens (so "incomplete" is never mistaken for "complete", and
"unable" never for "enable" -- each inflected form is listed separately) and substring matching
for multi-word phrases. Every fired flag carries the exact matched phrase(s) as its evidence, so a
finding is always inspectable against the real text it was raised from.

**Pairing runs on a same-subject test, not "does the counterpart word appear anywhere in the
set".** A requirement's subject is its own declared correlation field if present, tokenized, or
-- absent one -- the significant (stopword- and classification-keyword-filtered) tokens of its own
text. Two requirements are judged to concern the same subject only when their significant-token
sets clear a conservative Jaccard-overlap bar (`SUBJECT_MATCH_THRESHOLD = 0.34`), deliberately
guarding against manufacturing a false pairing out of shared spec-prose vocabulary the way a looser
bar would. A requirement that already states both halves of a pair in its own text (e.g. "a soft
reset asserted while a DMA transfer is already in progress shall abort the transfer and
reinitialize registers") is self-satisfying and raises no finding -- this module never demands a
well-written single requirement be artificially split in two to avoid a false gap.

**Every finding is `POTENTIAL_SPEC_GAP`, structurally, not merely by convention.**
`SpecGapFinding.status` is pinned to that one literal string by its own `__post_init__` --
constructing a finding with any other status raises `ValueError` -- so "never auto-promote a
detected gap to an approved requirement" is a property the code enforces rather than a documented
intent a caller could quietly violate. The module's status/gap-type vocabulary
(`NOT_AVAILABLE`/`GAPS_DETECTED`/`NO_GAPS_DETECTED`/`POTENTIAL_SPEC_GAP` plus the five gap-type
names) is checked disjoint at import time from a small literal set of verification-verdict tokens
(`PASS`/`FAIL`/`BLOCKED`/`ACCEPTED_RISK`/`WAIT_USER`/`RETRY`/`NEEDS_USER_INPUT`) by
`assert_no_verification_verdict_vocabulary()` -- the same discipline several sibling modules apply
against `dv_harness.models.Status`, applied here against a literal list since this module
deliberately imports nothing from `dv_harness`.

Front door: `python -m dv_harness.potential_spec_gap_detector <requirements.json> [--json]`
(accepts a bare JSON list, or `{"requirements": [...]}`); exit 0 no gaps, 1 gaps detected, 2 usage
error or nothing usable to analyze. No `dv-harness` CLI verb was added and `gates.py`/`cli.py` were
not touched, per this task's own file-safety scope.

**Deliberately bounded, and stated rather than implied closed.** (1) This is NOT a spec parser: it
takes an already-extracted requirement set and never reads a raw specification document, RTL, or a
register map itself. (2) It cannot prove a gap is real -- prose using vocabulary this module's
keyword lists do not recognize will not be flagged, and unrelated requirements that happen to
overlap two keyword lists could in principle produce a spurious pairing; every finding is
`POTENTIAL_SPEC_GAP` for exactly this reason, never a word that would read as a proven absence.
(3) It decides, approves, and arbitrates nothing: no build, job, or approval is touched, there is
deliberately no stage gate, and it authors no fix -- closing a real gap is a human writing a new
requirement, never this module.

Proven by `dv_harness_tests/test_potential_spec_gap_detector.py` (26 tests): one positive-detection
case per pattern; matching-pair negative controls per pattern (including a self-satisfying
single-requirement case and a fallback-derived-subject case with no explicit `subject` field
supplied); an unrelated-subjects control proving a gap still fires when no real counterpart exists
elsewhere in the set; empty-list/`None`-input and no-usable-text-skipped controls reporting
`NOT_AVAILABLE` honestly rather than a fabricated clean pass; a no-classifiable-content control
reporting `NO_GAPS_DETECTED`; structural-pinning tests proving `SpecGapFinding` refuses a
non-`POTENTIAL_SPEC_GAP` status and an unrecognized gap type; and real subprocess CLI tests
covering all three exit codes plus the `{"requirements": [...]}` wrapper form.


<!-- S132: moved verbatim from CLAUDE.md original lines 8207-8220 (M4.6 CLAUDE Context Normalization) -->
## SPEC_VPLAN_READY: Composite Readiness for the Spec-to-vPlan Pipeline Stage (2026-09-06)

This project already has two composite "is X ready" conjunctions built on the identical worst-wins discipline, and neither answers the question a caller working the SPEC-TO-VPLAN pipeline stage actually needs: `verification_intake_contract.py`'s `INTAKE_READY` is a whole-PROJECT capstone across every sub-domain intake touches, and `subsystem_maturity_gate.py`'s 9.0/9.5/10.0 levels are a whole-SUBSYSTEM maturity ladder spanning golden-flow connectivity, system smoke-proof, VIP-API provability, bind-tier cleanliness and regression evidence. Neither has any notion of "is the step that turns a parsed specification into a vPlan/requirement-contract artifact ready to drive generation, done" -- a project could be `SPEC_VPLAN_READY` while its overall `INTAKE_READY` is still `False` (a later sub-domain has not caught up), and a subsystem could clear `SPEC_VPLAN_READY` for every one of its constituent specs while sitting nowhere near 9.0 maturity (which needs conditions this gate never touches at all). A repo-wide search for `SPEC_VPLAN_READY`/`spec_vplan_ready` matched nothing executable before this: `tools/verification_flow/spec_to_vplan_quality_gate.py` and `spec_to_vplan_requirement_quality_gate.py` are per-requirement-record shape checks, not a composite verdict over a named condition set.

`dv_harness/spec_vplan_readiness_gate.py` is that composite gate, and it is deliberately a third, independent mechanism rather than an import of either neighbour -- both `verification_intake_contract.py` and `subsystem_maturity_gate.py` (along with `functional_coverage_signoff.py`, whose own Closure rollup uses the identical shape one level down) were concurrently-building batch items this module was scoped to never import. What is reused is the DISCIPLINE those modules already state as a design principle rather than a function this file could call without also importing whichever fixed condition set that module hardcodes: worst-wins, no-averaging, one unresolved condition among a hundred clean ones still blocks. `evaluate_spec_vplan_readiness()` takes a caller-assembled, caller-named list of `{"condition_name", "status", "reason"?}` records -- this module hardcodes NONE of them, since which conditions belong to "is spec-to-vplan done" (spec/doc mapping, requirement-contract completeness, vPlan/spec-delta resolution, and others) depends on whichever real per-domain producers a given project has wired.

**The fold is strictly worst-wins, two tiers deep**, over a condition-status vocabulary of `MET`/`UNMET`/`UNKNOWN`/`NOT_AVAILABLE` and a gate-verdict vocabulary of `QUALIFIED`/`NOT_QUALIFIED`/`INCOMPLETE_EVIDENCE` (both checked disjoint from `models.Status` at import time, the identical guard `subsystem_maturity_gate.py` applies to itself, reimplemented rather than imported since that module is off the import list here): any `UNMET` condition makes the whole gate `NOT_QUALIFIED` outright, regardless of how many others are `MET` and regardless of whether any other condition is `UNKNOWN`/`NOT_AVAILABLE` too -- a single unresolved requirement or vPlan gap is never diluted into a percentage or an average. Only once no condition is `UNMET` does any `UNKNOWN`/`NOT_AVAILABLE` condition make the result `INCOMPLETE_EVIDENCE` -- this task's own instruction stated in code: an unresolved-evidence condition is a third, honestly distinct outcome, never silently read as either a pass or a confirmed failure. Every condition `MET` is the only path to `QUALIFIED`. An absent or empty condition list is `INCOMPLETE_EVIDENCE` with a real reason, never a vacuous `QUALIFIED` over zero conditions measured -- the same "an empty input is UNKNOWN, never READY" rule this project's other composite folds already state. A malformed record (missing `condition_name`/`status`, an empty name, an unrecognized status, or a name repeated by an earlier record in the same list) raises `SpecVplanReadinessGateError` naming exactly what was wrong, rather than being silently dropped or resolved by picking one.

**It reads only.** No stage runs, no gate script is invoked, no build/regression/LSF job starts, and it writes no state/control/approval file of its own -- `ControlPlane.approve()`, `policy.can_signoff()`, `assert_human_approval()` and the PR-only main/master governance are untouched and unreferenced, checked against the module's own real code (not its prose, which legitimately discusses these mechanisms by name as precedent) by a tokenize-based test. A `QUALIFIED` verdict is an input to a human's decision that the spec-to-vplan stage is done, never a substitute for one, and there is deliberately no stage gate of its own.

Front door: `python -m dv_harness.spec_vplan_readiness_gate statuses|verdicts|evaluate --conditions <file> [--json]` (no `dv-harness` CLI verb -- `cli.py` and `gates.py` are on this batch's never-touch list, the same disclosed choice several very recent same-day additions in this repo have also made). Exit 0 `QUALIFIED`, 1 `NOT_QUALIFIED`, 2 `INCOMPLETE_EVIDENCE` or a usage/malformed-input error.

Proven by `dv_harness_tests/test_spec_vplan_readiness_gate.py` (33 tests): the core positive path; the headline no-averaging negative control (20 clean conditions plus one `UNMET` still reads `NOT_QUALIFIED`); `UNKNOWN` and `NOT_AVAILABLE` each independently proven to produce `INCOMPLETE_EVIDENCE`; `UNMET` proven to outrank `UNKNOWN` when both are present in one condition set; an empty/`None` condition list proven `INCOMPLETE_EVIDENCE`; five malformed-record negative controls each raising the correct named error; a real `ast.parse` of the module's own import statements proving it never imports `verification_intake_contract`/`subsystem_maturity_gate`/`functional_coverage_signoff`; and four real `python -m` subprocess invocations asserting all three exit codes plus JSON shape.


<!-- S133: moved verbatim from CLAUDE.md original lines 8221-8280 (M4.6 CLAUDE Context Normalization) -->
## vPlan Item Executability Score: a Third, Distinct Readiness Axis (2026-09-06)

This repo already has two real per-vPlan-adjacent readers, and neither answered this module's question.
`vplan_artifact.py` scores a vPlan ROW across nine independent dimensions (requirement link, hierarchy
integrity, ownership, coverage/checker/test linkage, ...), each READY/PARTIAL/BLOCKED/UNKNOWN, never
averaged into one number -- by design, because folding nine independently-meaningful axes into one score
would let a caller mistake a vPlan that is BLOCKED on one axis and READY on the other eight for a vPlan
that is "mostly fine". `subsystem_practicality_score.py` rolls up ten whole-SUBSYSTEM maturity signals
into one weighted 0-100 score, read off already-derived module verdicts, never per item. Neither answers
"for THIS ONE vPlan item, how far along is turning it into a runnable generated test -- has anything
even been identified, is it mapped to real implementation artifacts yet, and if so is that mapping still
open on unresolved questions?" A repo-wide grep for `executability`/`implementation_readiness`/
`IDENTIFIED_UNMAPPED` matched nothing before this module.

**A five-value scale, deliberately five fixed points rather than a percent.** `0 NO_EVIDENCE` -- the
item carries no identity and no mapping fact was even supplied to check. `20 IDENTIFIED_UNMAPPED` -- the
item is known to exist but zero of its declared mapping facts are present. `50 PARTIALLY_MAPPED` --
some, but not all, declared mapping facts are present. `80 MAPPED_OPEN_QUESTIONS` -- every declared
mapping fact is present, but at least one open question against the item remains unresolved.
`100 FULLY_READY` -- every declared mapping fact is present and no open question remains. A percent-style
score invites averaging across items and across `vplan_artifact.py`'s nine completeness dimensions,
exactly the collapsing this module exists to avoid being read as -- five named, ordered checkpoints are
a status, not a measurement, the same non-numeric-but-ordered discipline `requirement_contract.py`'s
five-value status vocabulary and `waiver_store.py`'s five-value waiver status already use.

**Duck-typed input, on purpose.** Per this batch's file-safety scope this module must not import
`vplan_artifact.py`, `verification_intent_ir.py`, or any other in-flight sibling module, and must not
assume any of their still-moving internal shapes. A vPlan item is accepted as a plain mapping carrying
whatever identity fields a caller has, a `mapping_facts` value (a `{fact_name: bool}` dict, a list of
`{"name"/"fact": ..., "present"/"mapped"/"done"/"satisfied": bool}` records, or a bare list of
fact-name strings each counted present -- callers using the bare-string form should also declare
`required_mapping_facts` so a fact never even asked about can be told apart from one asked about and
found absent), an `open_questions` list, and a `blockers` list. Nothing here decides what a "mapping
fact" IS -- unlike `vplan_artifact.py`'s nine named dimensions, this module mints no second opinion
about what "coverage-linked" or "checker-linked" means; it only counts how many of whatever facts the
caller declared are present, which keeps it correct today and automatically compatible with whatever
shape a future generator (or `vplan_artifact.py` itself) produces, by converting that shape's own facts
into this same plain form at the call site.

**The one rule this module exists to enforce: score and blocker are never merged.** A vPlan item can be
scored 100 (`FULLY_READY`: every mapping fact present, no open question outstanding) and STILL carry a
separately-flagged CRITICAL blocker (e.g. a caller-recorded "this sequence's DUT register write was
proven wrong by RTL evidence" finding). `score_item_executability()` never folds a blocker into the
numeric score, and never suppresses, downgrades, or even reads a blocker to decide the score --
blockers are collected and reported on the SAME record, in their own field, and
`assert_score_never_hides_a_critical_blocker()` is a standing check any caller can run over a report
before trusting a high score alone.

`score_item_executability()`/`score_vplan_items()` score one or many items; `render_executability_matrix()`
renders the report; `python -m dv_harness.vplan_item_executability_score` is the front door.

Proven by `dv_harness_tests/test_vplan_item_executability_score.py` (29 tests): each of the five scale
points is proven from its own real input shape, all three `mapping_facts` input forms (dict, record list,
bare-string list with `required_mapping_facts`) are proven equivalent, and the headline negative control
proves a 100/`FULLY_READY` item still surfaces its own recorded CRITICAL blocker unchanged and
unsuppressed.

**Disclosed residual**: it counts caller-declared facts; it does not decide what a mapping fact means,
and it references no approval/governance mechanism.


<!-- S136: moved verbatim from CLAUDE.md original lines 8374-8429 (M4.6 CLAUDE Context Normalization) -->
## Scoreboard Placement Scope: an 8-Value Taxonomy for Where a Compare Sits (2026-09-06)

A repo-wide grep for `PORT_LOCAL`/`FUNCTION_LOCAL`/`BLOCK_LOCAL`/`CROSS_PORT`/`DMA_PATH`/`MEMORY_PATH`/
`INTERRUPT_PATH`/`END_TO_END` and for `scoreboard_placement_scope`/`ScoreboardPlacementScope` found
nothing -- no scoreboard placement-scope vocabulary existed anywhere in this repo.
`amba_scoreboard_env.py` carries an adjacent but DIFFERENT vocabulary (`ENV_ROLE_SCOREBOARD`/
`ENV_ROLE_SUBSCRIBER`/`ENV_ROLE_PREDICTOR`/...) answering "what UVM CLASS ROLE does this component
play" -- never "where does its compare operation sit relative to the DUT's ports/paths", the different
question `dv_harness/scoreboard_placement_scope.py` answers.

**Deliberately standalone.** This module accepts related project facts (what a scoreboard compares;
what project evidence says about a VIP-adjacent component) as generic, duck-typed dict parameters
rather than importing `connectivity.py`, `amba_scoreboard_env.py`, or any `syoscb_*` module owned by
concurrent work elsewhere -- every function here takes plain dicts with documented keys and imports
nothing else from this package.

**Eight scope values, one fixed precedence order.** `SCOPE_VALUES` is exactly `PORT_LOCAL`,
`FUNCTION_LOCAL`, `BLOCK_LOCAL`, `CROSS_PORT`, `DMA_PATH`, `MEMORY_PATH`, `INTERRUPT_PATH`, `END_TO_END`.
Classification precedence (most architecturally specific first, so a compare that is both e.g.
cross-port and on a DMA path is named `DMA_PATH` rather than the less informative `CROSS_PORT`) is
`SCOPE_PRECEDENCE`: `END_TO_END > INTERRUPT_PATH > DMA_PATH > MEMORY_PATH > CROSS_PORT > PORT_LOCAL >
FUNCTION_LOCAL > BLOCK_LOCAL`.

**The Evidence Truth Rule, applied to a taxonomy classifier.** A scope is asserted ONLY from an
explicit, caller-declared fact (a boolean "does this compare span the DMA engine", an integer port
count, or a direct `declared_scope` tag already validated against `SCOPE_VALUES`) -- never from
free-text guessing over a prose description, which would be exactly the "confident guess" the Evidence
Truth Rule forbids. A `compare_description`/`project_evidence` dict carrying none of the recognised
fact keys, or carrying only explicitly-False/absent facts, yields `STATUS_UNVERIFIABLE` naming the
absence -- never a defaulted or inferred scope. A malformed fact (wrong type, an unrecognised
`declared_scope` value) is a caller error and raises `ScoreboardPlacementScopeError` rather than being
silently coerced or dropped.

**The SyoSil/similar default rule, stated explicitly rather than assumed.** A SyoSil-originated (or
declared-similar) VIP scoreboard component -- the real-world SYOSCB family -- is architecturally a
generic, reusable, protocol-agnostic QUEUE-BASED compare engine: a VIP plugs its own transaction streams
into a SYOSCB queue instance, and the queue instance itself carries no inherent knowledge of where in
the DUT's topology that comparison sits. So when such a component is DECLARED present
(`vip_adjacent_compare_engine_declared: true`, or a naming `component_vendor`/`component_kind`/
`component_name`) and the compare description carries no placement fact of its own, this module reports
that one true thing it does know (a queue/compare engine) rather than a bare `STATUS_UNVERIFIABLE` --
but any REAL project evidence overriding that default always wins, and the default is never presented as
a measured placement fact.

`classify_scoreboard_scope()` is the entry point; `python -m dv_harness.scoreboard_placement_scope` is
the front door (`execute_verb()`/`main()`).

Proven by `dv_harness_tests/test_scoreboard_placement_scope.py` (34 tests): each of the 8 scope values
is proven from its own declared fact, the precedence order is proven directly (a compare declared both
cross-port and DMA-path resolves to `DMA_PATH`), the SyoSil default is proven both to fire on an absent
placement fact and to be overridden by real conflicting project evidence, and a malformed
`declared_scope` value is proven to raise rather than silently coerce.

**Disclosed residual**: it classifies from caller-declared facts only -- it derives no fact of its own
and references no approval/governance mechanism.


<!-- S137: moved verbatim from CLAUDE.md original lines 8430-8465 (M4.6 CLAUDE Context Normalization) -->
## DE Command Review Package: a Renderer, Never a Recovery Engine (2026-09-06)

`dv_harness/de_command_review_package.py` renders the DE (Design/Verification Engineer) Command Review
Package: a markdown table pairing each EXISTING command token recovered from a legacy command.txt-style
pattern file against what this repo's own recovery evidence says about it, so a human DE can confirm or
correct that recovered meaning before it becomes machine-trusted anywhere downstream.

**This module is a RENDERER ONLY.** It never recovers a command's meaning, never infers a branch owner,
and never invents a compatibility verdict or a timing value -- it takes a generic, duck-typed list of
dict-like rows already produced by whatever upstream recovery step ran (elsewhere in this batch, or by
hand), validates the two fields a review package cannot honestly omit, and defers all table shape/style
to `connectivity.render_markdown_table()` -- this repo's only parameterized table renderer. No other new
module from this batch is imported.

**Columns, fixed order.** Existing Command (the literal token from the source file, verbatim); Recovered
Meaning (what upstream recovery believes the command does); Branch Owner (which of the four fixed
task-composition layers this command's effect belongs to -- `block`, `branch_a{i}`, `branch_fw`, or
`branch_b{i}`, the exact vocabulary `.claude/skills/CORE/branch-mapper/SKILL.md` and
`.claude/skills/CORE/pattern-architecture/SKILL.md` already define; a value outside this vocabulary is
rejected loudly rather than rendered, because a wrong owner routes review to nobody); Task; Preconditions;
Expected Effect; Compatibility (upstream recovery's own verdict, rendered verbatim, never computed here);
Open Ambiguity (left blank only when the input row genuinely has nothing there, never defaulted to a
fabricated "none").

**Evidence Truth Rule**: a row missing its `existing_command` identity, or carrying a `branch_owner`
string outside the four-layer vocabulary, is a hard validation error (`DECommandReviewPackageError`),
never silently dropped or coerced. Every other field renders exactly what the row already holds.

Proven by `dv_harness_tests/test_de_command_review_package.py` (13 tests): the four-layer vocabulary
validation is proven both ways (a real layer name renders, an invalid one raises), missing-optional-field
rendering is proven to fall back to `render_markdown_table()`'s own empty-cell behavior, and the renderer
is proven to never compute or infer a value the input rows do not already carry.

**Disclosed residual**: it renders; it does not recover, infer, or approve anything, and references no
approval/governance mechanism.


<!-- S139: moved verbatim from CLAUDE.md original lines 8511-8549 (M4.6 CLAUDE Context Normalization) -->
## Pattern Execution Evidence: Per-Dispatched-Task Records, Read from Real Log Narration Only (2026-09-06)

`evidence_db.py`'s `normalized_evidence` table (and `golden_scenario.py` on top of it) records evidence
at PER-TEST granularity: one row per (job, pattern) with one overall verdict. `dv_harness/pattern_execution_evidence.py`
is a finer granularity underneath that: one record per DISPATCHED TASK inside a single command.txt/pattern
run -- the `block`/`branch_a{i}`/`branch_fw`/`branch_b{i}` task-composition layers
`.claude/skills/CORE/pattern-architecture/SKILL.md` and `.claude/skills/CORE/branch-mapper/SKILL.md`
already define, reused verbatim here, never re-derived or renamed. Per this task's own instruction, this
is a DIFFERENT, more granular per-dispatch vocabulary than `loop_budget.FailureType`'s ten-class retry
taxonomy -- that module classifies why a whole STAGE failed for a retry-vs-stop decision; this module
records what one TASK inside one pattern run actually did, and the two are never merged.

**The Evidence Truth Rule, applied literally.** Every `start_time`/`end_time` this module reports is a
REAL `@ <time>` value lifted off a REAL log line that genuinely mentions that task's name next to a
lifecycle verb (the same "UVM_INFO ... @ <time>: <reporter> [<ID>] starting <name>" / "... complete"
narration convention `sim_log_analysis.py`'s own tested fixtures already use). A sim.log that never
narrates a task by name at this granularity yields NO records for it, never a guessed or interpolated
timestamp -- `granularity_status` says so explicitly at the report level, and every per-field absence
carries `NOT_AVAILABLE` plus a real reason rather than a default.

**Reuse over reinvent.** The actual marker scan, signature normalization, and severity/category
classification is 100% `sim_log_analysis.parse_sim_log()`/`classify_signatures()`, called read-only over
the TEXT SLICE between a task's own start/end line -- there is no second log-marker scanner in this
module, and `connectivity.render_markdown_table()` renders the report, so there is no second table
renderer either.

Proven by `dv_harness_tests/test_pattern_execution_evidence.py` (24 tests, organized into classes): task
lifecycle extraction is proven to find real start/end narration and to yield an empty map when none
exists; branch-layer classification is proven for every canonical name and to raise on an unrecognized
one; a clean branch, a branch with a real scoreboard mismatch, and cross-branch isolation (a mismatch
inside `branch_b1`'s window never leaks into `branch_b0`'s record) are all proven against real narrated
log text; a hung task is proven to NEVER fabricate an end time; an omitted command and a narration line
missing a real timestamp both report `NOT_AVAILABLE` rather than a guess; and the file-reading wrapper is
proven to survive a stray non-UTF-8 byte.

**Disclosed residual**: this closes per-dispatch execution evidence at whatever granularity the real
sim.log narration actually supports -- it never densifies a log that says less than the record shape
asks for.


<!-- S140: moved verbatim from CLAUDE.md original lines 8550-8603 (M4.6 CLAUDE Context Normalization) -->
## DE Command Runtime Readiness Gate: Joining Three Already-Real Sources into One Verdict (2026-09-06)

`runtime_event_registry.py` answers "what is this EVENT's status" (with REQUIRES/WAITS_FOR/TRIGGERS/
UNBLOCKS stop-on-failure propagation) and `command_precondition_gate.py` answers "may THIS COMMAND be
dispatched right now, given the registry's real event state" -- both real, both tested, both real
gap-closures from this same workflow run. Neither answered the question a runtime dispatcher actually
needs before it starts issuing an entire generated pattern's worth of `block`/`branch_a*`/`branch_fw`/
`branch_b*` commands: "given the registry's current state, every declared command's dispatch readiness,
AND whatever the branch/grammar-authoring side of the pipeline independently concluded about this same
pattern, is this pattern's runtime execution actually READY, or is it BLOCKED, and by what,
specifically?" Nothing in this repo joined those three real sources into one verdict.
`dv_harness/de_command_runtime_readiness_gate.py` is that join.

**A thin aggregator over three already-real inputs, reusing each one's own vocabulary and computation
rather than re-deriving any of them.** (1) `RuntimeEventRegistry.propagate()` is called EXACTLY ONCE
here (never re-run per command), producing the real `PropagationReport` this module reads for both its
own event-level blockers (an event that is itself FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY, whether or not
any command declares it as a precondition) and the shared basis every command's precondition check is
evaluated against -- `command_precondition_gate.evaluate_command_preconditions()` is called directly with
that one shared report, the exact pattern that module's own docstring recommends for evaluating several
commands against one registry state, and the reason this module does not call
`evaluate_dispatch_readiness()` itself, which would silently re-run `propagate()` a second time. (2) The
real per-command `CommandDispatchStatus` (READY/BLOCKED/UNKNOWN_PRECONDITION) is read verbatim; a command
not READY is a blocker, named with that command's own real reason text. (3) A caller-supplied, DUCK-TYPED
`branch_grammar_results` value -- the branch/grammar-authoring side's own conclusion about this same
pattern (e.g. `branch_ownership_resolver.validate_branch_assignment()`'s VALID/INVALID/AMBIGUOUS, or
`command_generation_gate.py`'s own PASS/BLOCKED-shaped payload) -- this module never imports either, or
any other module from that sibling "DE Command / Branch Architecture" batch, precisely because that
batch may or may not have finished when this one runs; it accepts whatever shape arrives as generic,
alias-tolerant records (any of `command_id`/`command_name`/`name`/`id`/`identifier` for who the finding is
about; any of `status`/`verdict`/`result`/`branch_status`/`ownership_status` for the finding itself; any
of `reason`/`detail`/`message`/`rationale` for why). A record whose status string is not one of a small,
explicit, case-insensitive recognized-PASS vocabulary is a blocker, quoting the real status string
verbatim -- an unrecognized or absent status is never assumed passing, the same "an event absent from the
registry is UNRESOLVED, never assumed satisfied" discipline `runtime_event_registry.py` already applies
one layer down.

**The composite verdict is BLOCKED iff ANY of the three sources reports a real blocker**; it is PASS only
when the registry's propagated event state has no blocking event, every declared command is READY, and
every supplied branch/grammar-side result (if any were supplied at all -- supplying none is legal, since
the sibling batch may not have run yet) reports a recognized pass status. Every blocker is named
individually and by its real source, so a reader never has to guess which of the three layers is the
reason.

Proven by `dv_harness_tests/test_de_command_runtime_readiness_gate.py` (25 tests): the composite verdict
is proven BLOCKED from each of the three sources independently and PASS only when all three are clean;
`propagate()` is proven called exactly once even across many commands; the alias-tolerant record parsing
is proven across several field-name variants; and an absent/unrecognized branch-grammar status is proven
to block rather than pass by default.

**Disclosed residual**: this module has no `gates.py` `STAGE_GATES` entry yet -- wiring one in is a
follow-up integration step, not part of this module's own scope. It aggregates; it authorizes nothing,
and references no approval/governance mechanism.


<!-- S141: moved verbatim from CLAUDE.md original lines 8604-8621 (M4.6 CLAUDE Context Normalization) -->
## VIP Example Composition: a 7-Condition Composability Gate (2026-09-06)

Composing several already-qualified VIP examples into ONE scenario -- e.g. a USB3 host example plus a USB3 device example, or a host example plus an unrelated protocol's monitor example -- had no compatibility check anywhere in this repo. `vip_capability_extraction.py` classifies individual VIP source CLASSES with a qualification tag; `env_manifest.py` records which VIP instances are configured in ONE already-generated environment; `ip_ownership_conflict.py` and `system_resource_inventory.py`'s SYS-11/SYS-12 machinery flag ownership conflicts for a single subsystem or across already-composed SoC subsystems. None of them answers the earlier, narrower question this module answers: given a caller-declared SET of individually-qualified VIP examples about to be combined into one scenario, are they actually compatible with each other -- checked against seven concrete conditions -- before any of that content is merged into a single command.txt/scenario body.

`dv_harness/example_composition.py` is that gate. Per this batch's file-safety scope it imports NOTHING from `vip_capability_extraction.py`, `ip_ownership_conflict.py`, or `system_resource_inventory` (concurrently-owned or separately-existing mechanisms this module deliberately does not duplicate) -- `examples` is a plain, alias-tolerant list of dicts, the same general shape `vip_capability_extraction.py` would produce for a qualified VIP artifact record, widened with the composition-specific facts this task names. It does not itself decide whether an example is qualified; that judgment belongs to whatever produced the record. Composing means: given examples the caller already asserts are individually usable, are they usable TOGETHER.

**Seven conditions, every one a pure structural comparison of caller-declared facts, never a semantic judgment about protocol behaviour.** (1) VIP version -- examples sharing one normalised `vip_type` must declare the same `vip_version` (scoped by package identity, never by link). (2) Role -- on one logical link, at most one example may declare a role this module recognises as ACTIVE (HOST/MASTER/INITIATOR/DRIVER/ACTIVE/ROOT_COMPLEX/RC/REQUESTER); an unrecognised role never blocks and is never assumed either way. (3) Protocol mode -- examples on one logical link must declare the identical protocol mode. (4) Agent config -- for every `agent_config` field two or more examples on one link both declare, the values must agree; a field only one side declares is never compared. (5) Sequencer ownership -- two or more examples declaring the SAME explicit sequencer/interface/bind path and both resolving to an ACTIVE driver (declared, or inferred from the fixed ACTIVE/PASSIVE role vocabulary) is a real ownership collision; an unresolved active status is reported separately and never forced into a conflict. (6)/(7) Reset/clock assumptions -- two or more examples naming the SAME reset/clock signal must agree on its declared active_level/synchronous (reset) or frequency_mhz/period_ns/edge (clock) facts.

**The one deliberate, disclosed design choice: `_link_key()`'s fallback.** Conditions 2-4 are scoped to one caller-declared logical link (`link_id`/`interface_id`/`port_id`, falling back to a declared `sequencer_path`, falling back further to one shared `UNSPECIFIED_LINK` bucket when neither is declared). That last fallback is deliberate: when an example set gives this module no way to tell two examples apart as independent ports, treating them as unrelated would be an unearned assumption of independence, so they are conservatively grouped together and a real disagreement among them is surfaced rather than hidden behind absent disambiguating evidence. A caller composing a genuine independent multi-port scenario must declare `link_id`/`port_id`/`sequencer_path` to tell the ports apart -- the same evidence this module would need to do so correctly.

**Never resolves a conflict, only names the pair.** Every conflict is reported as `status: BLOCKED` naming the exact conflicting pair (both examples' declared identities) and the specific disagreeing value(s) -- never silently merged, never averaged, and this module never picks a winner between two conflicting examples; that stays a human/caller decision, the same ARBITRATION boundary `requirement_contract.py` and `design_knowledge_correlation.py` already keep for their own conflict findings.

Malformed input is reported and excluded, never silently absorbed: a non-dict entry, an entry with no resolvable identity, and every entry sharing a duplicate identity all land in `malformed_examples` rather than participating in composition (a duplicate identity excludes ALL entries sharing it, never picking one to keep). Fewer than two valid, uniquely-identified examples reports `NOT_AVAILABLE` naming the real count; `examples` itself not being a list/tuple raises `CompositionInputError`.

**Deliberately bounded, and stated rather than implied closed.** This module builds no VIP API, no RTL content, and no scenario/command.txt body; it runs no build/regression/LSF job, and there is deliberately no `STAGE_GATES` entry -- a gate that passed on a composition nobody actually generated from would be worse than none. There is no `dv-harness` CLI verb (`cli.py`/`gates.py` are out of this batch's file-safety scope); the front door is `python -m dv_harness.example_composition compose --examples <file.json> [--json]` (exit 0 COMPOSED, 1 BLOCKED, 2 NOT_AVAILABLE).

Proven by `dv_harness_tests/test_example_composition.py` (26 tests): a clean, fully-compatible USB3 host+device pair composes with zero findings and a no-mutation proof over the input, then each of the 7 conditions is driven to a real, named-pair `BLOCKED` conflict by mutating one fact at a time off that same clean baseline, each paired with a negative control proving the check does not over-fire (different-vip_type examples never compared on version, two independent HOSTs on genuinely different declared links never conflict on role while two with no link information at all DO -- the disclosed fallback's detection power, an active driver sharing a path with a passive one is not an ownership conflict, an unresolved active status is reported but never forced into a conflict, differently-named reset signals are never compared, and clock numeric tolerance never manufactures a false conflict from float representation noise). Three malformed-input controls (non-dict entry, missing identity, duplicate identity excluding both), an insufficient-examples control, a non-sequence-input refusal, and three real CLI subprocess invocations asserting exit codes 0/1/2 round out the suite. Ran `python -m pytest dv_harness_tests/test_example_composition.py -q` -> `26 passed`.


<!-- S142: moved verbatim from CLAUDE.md original lines 8622-8637 (M4.6 CLAUDE Context Normalization) -->
## Per-Pattern Marginal Coverage Contribution: Attribution the Aggregate Curve Cannot Give (2026-09-06)

`loop_convergence.py`'s own docstring is explicit about its own boundary: its coverage series is `trend_analysis.daily_rollup()`'s bins-weighted, PROJECT-WIDE `coverage_percent` curve -- one number per day, aggregated across every pattern that ran that day -- and that module "never attributes movement to one pattern". It can tell you the project is CONVERGING, PLATEAU'd, or OSCILLATING; it cannot tell you which pattern moved the needle, by how much, at what runtime/failure cost. `dv_harness/pattern_coverage_contribution.py` answers that different, narrower question: for ONE named pattern, what new coverage bins (and, of those, which new cross-coverage bins are independently meaningful rather than fully explained by their own already-covered single-axis bins) did its own run(s) contribute, and at what real runtime/failure cost -- never an aggregate curve, always attributed to the one pattern named.

**The real gap, found by grepping `evidence_db.py`'s schema before writing a line of code, per this batch's own instruction.** `coverage_samples` (`insert_coverage_sample()`) is this project's one real coverage-sample store, and its real columns are `(id, category_name, percent, bins_total, bins_hit, sample_timestamp, source, ingested_at)` -- there is **no `pattern` column**. In production, `dashboard._ingest_coverage_summary_to_evidence_db()` passes the `summary.json` PATH as `source`, never a pattern name. `evidence_db.py`'s OTHER real per-pattern table, `jobs`, DOES carry a real `pattern` column plus `runtime_seconds`/`uvm_error_count`/`uvm_fatal_count`/`assertion_failure`/`simulator_crash` -- real, already-attributable evidence needing no new linkage. So the honest state of this project's evidence store is: runtime and failure evidence per pattern already exists; coverage-BIN evidence exists only as an un-attributed, project-wide checkpoint sequence. This module reuses `coverage_samples`/`jobs` EXACTLY as recorded (no new column, no write path -- every read goes through `EvidenceStore(db_path, read_only=True).query()` with an explicit column list zipped back into named dicts, the same convention `protocol_compliance_aggregation.py`'s `load_normalized_evidence_rows()` already established) and asks the ONE additional real fact the schema cannot supply on its own: which checkpoint (`source` value) belongs to which pattern's run. That fact arrives as a required, explicit, caller-declared `sample_attribution` (`[{"source", "pattern"}, ...]`) -- the same "accept an explicit caller-declared fact the real evidence store cannot supply, rather than invent one" discipline `ip_ownership_conflict.py`'s `legacy_bfm_declarations` and `existing_command_reuse_score.py`'s `existing_commands` already use. A pattern with no attributed checkpoint, and no `jobs` rows, has recorded NOTHING this project's evidence store can attribute to it, and reports `NOT_AVAILABLE` for its contribution -- never an estimated or zero delta.

**Mechanics.** `group_into_checkpoints()` groups real `coverage_samples` rows by their own `source` field into chronologically-ordered checkpoints (ordered by the real DuckDB `id` sequence -- never trusted by wall-clock `sample_timestamp`/`ingested_at` resolution). `compute_pattern_coverage_contribution(db_path, pattern, sample_attribution, cross_definitions=None)` walks checkpoints in order, and for each one attributed to `pattern` diffs every category's `bins_hit` against the state immediately prior (baseline 0 for a category never seen before that point), summing `new_bins_hit` across all of the pattern's own checkpoints. A negative delta (bins un-hit between checkpoints, however unusual) is never counted toward `new_bins_hit` (floored at 0) but is still honestly surfaced in `regressed_categories` -- never silently hidden. `coverage_delta_percent` is a bins-weighted percent movement over only the categories the pattern actually touched. Runtime/failures come straight from real `jobs` rows filtered by `pattern`. `cost` is ALWAYS reported `NOT_AVAILABLE` with a real cited reason: a repo-wide check before writing this module found no per-job compute/license-usage cost producer anywhere in this codebase -- `loop_budget.py`'s own CLAUDE.md section states plainly that "max_compute / max_license_usage / max_token_cost ... have no producer in this harness at all" -- so inventing one here would be exactly the fabrication the Evidence Truth Rule forbids. Overall status is `MEASURED` only when both the coverage side and the runtime/failure side were measured; `PARTIALLY_MEASURED` when only one was; `NOT_AVAILABLE` when neither was -- three honestly distinct states, never averaged or collapsed.

**"Meaningful crosses only", built independently rather than importing a claimed file.** `coverage_analysis.py` already has a private `_cross_axes()`/`_cross_axes_all_covered()` pair solving almost exactly this same question (used there to classify a `CROSS_COVERAGE_ONLY_UNCOVERED` coverage hole) -- but `coverage_analysis.py` was one of this batch's own claimed/never-import files, so `classify_cross_coverage_meaningfulness()` re-derives the identical, small, generic logic directly over plain `{"percent","bins_total","bins_hit"}` category dicts (the same shape `coverage_samples` rows already carry) rather than importing a claimed module or leaving the helper unbuilt. It flags a caller-declared cross-coverage bin (`{"cross_name", "axes": [axis1, axis2, ...]}`) `FULLY_EXPLAINED_BY_AXES` (skip-worthy) ONLY when EVERY declared axis is a real, matched, `>= 100%`-covered category in the supplied snapshot; a missing or unmeasurable axis reads `UNKNOWN_AXIS_COVERAGE` and is NEVER treated as fully-explained -- absence of proof that the axes explain the cross is never read as proof they do, so an unprovable cross bin's new hits still count toward `new_crosses_hit`. Meaningfulness is evaluated against the coverage state as it stood immediately BEFORE the pattern's own contribution began, not the final project-wide state -- "already fully explained" means already, prior to this pattern's own run.

**Status vocabulary is asserted disjoint from `dv_harness.models.Status` at import time** (`MEASURED`/`PARTIALLY_MEASURED`/`NOT_AVAILABLE`, `CROSS_MEANINGFUL`/`CROSS_FULLY_EXPLAINED`/`CROSS_UNKNOWN`) -- the same guard `capability_evolution.py`/`benchmark_dataset.py`/`subsystem_maturity_gate.py` already run on their own vocabularies (`PARTIAL` was caught colliding with `Status.PARTIAL` during this module's own test run and renamed to `PARTIALLY_MEASURED` before landing).

**Deliberately bounded, and stated rather than implied closed.** (1) It never writes to `evidence_db.py` -- no `insert_*` method is ever called from this module, and it constructs `EvidenceStore` only in `read_only=True` mode. (2) It arbitrates nothing and runs no gate; there is deliberately no stage gate. (3) `cost` can never resolve to a real measured value in this codebase today -- disclosed rather than silently omitted. (4) It is REACHED, not WIRED: there is a `python -m dv_harness.pattern_coverage_contribution` front door but no `dv-harness` CLI verb, no `run_stage()`/`advance()` call site, and no graph node.

Proven by `dv_harness_tests/test_pattern_coverage_contribution.py` (17 tests), every coverage-sample and job row populated exclusively through `evidence_db.py`'s own real `insert_coverage_sample()`/`insert_job_state()` methods -- never a hand-written store row. The core positive path drives two patterns' real checkpoints (one improving a cross bin whose axes are NOT both yet fully covered, proving `INDEPENDENTLY_MEANINGFUL` rather than a fabricated skip) through real job runtime/failure evidence. Negative controls: no attribution and no jobs -> `NOT_AVAILABLE` (never a fabricated zero, asserted by checking the key is simply absent); coverage-only measured -> `PARTIALLY_MEASURED`; jobs-only measured -> `PARTIALLY_MEASURED`; a malformed attribution entry and an ambiguous same-source-two-patterns attribution both raise `PatternCoverageContributionError`; a wholly absent evidence.duckdb reports `NOT_AVAILABLE` without crashing; a real coverage regression between checkpoints is reported honestly in `regressed_categories` and never counted as new; a cross bin whose axis category cannot be found at all reads `UNKNOWN_AXIS_COVERAGE` and still counts toward `new_crosses_hit` (never silently skipped); and multiple checkpoints attributed to the same pattern are correctly summed. Both real CLI exit-code paths (`MEASURED` -> 0, `NOT_AVAILABLE` -> 2) are driven as real subprocesses.


<!-- S143: moved verbatim from CLAUDE.md original lines 8638-8651 (M4.6 CLAUDE Context Normalization) -->
## Coverage-Closure Action Utility: Rank Actions, Gate Correctness/Risk Before Cost (2026-09-06)

Plenty of per-hole coverage ANALYSIS exists in this repo (`coverage_analysis.classify_coverage_hole()`'s four root causes, `classify_coverage_hole_taxonomy()`'s twelve structural categories) and plenty of per-project READINESS rollups (`generation_readiness.py`, `golden_flow_readiness.py`, `subsystem_practicality_score.py`), but nothing RANKED a set of proposed coverage-closure remediation actions against each other. A coverage-closure effort routinely has more candidate actions (write a directed test, relax an over-constrained sequence, add a waiver, escalate as unreachable) than budget to pursue at once, and nothing ordered that list by expected value. A repo-wide grep for `coverage_closure_action`/`expected_coverage_gain` before this module matched nothing executable.

`dv_harness/coverage_closure_action_utility.py` ranks a duck-typed list of candidate actions by `utility = expected_coverage_gain x requirement_priority x risk_coverage / cost`. `evidence_db.py`'s real `coverage_samples` table (read, never imported, before designing this) is keyed by `category_name`/`percent`/`bins_total`/`bins_hit` -- a coverage tool's own per-category rollup, with no candidate-action, requirement-priority, risk-coverage, or cost concept at all. There is no mechanical producer anywhere in this repo for any of the four factors this formula needs, so -- exactly as `requirement_risk_ir.py` established for its own four caller-declared risk factors -- every factor here is accepted only as an explicit caller declaration and reported with status `DECLARED`, visibly distinct from a `MEASURED` value, never re-derived and never defaulted to a guessed number when absent or invalid (that reports `NOT_AVAILABLE` instead).

**The document's own explicit rule is enforced as code, not merely described: "a cheap-but-wrong action must never outrank a correct one regardless of cost."** Two caller-declared judgments -- `correctness_status` (CONFIRMED_CORRECT/FLAGGED_INCORRECT/UNVERIFIED) and `risk_status` (ACCEPTABLE_RISK/HIGH_RISK/UNVERIFIED), each independent of the `risk_coverage` utility factor (which measures how much risk surface an action addresses, a benefit; `risk_status` asks whether taking the action is itself dangerous, a gate) -- are resolved and applied by `_gate_candidates()` **before** any utility factor, including cost, is ever read for that candidate. A `FLAGGED_INCORRECT`/`HIGH_RISK` action is moved to a separate `excluded` bucket carrying `utility_score=None` and named exclusion reasons -- it is never scored, never ranked with a fabricated low score, and never merely penalized; its declared factors are still reported alongside for audit transparency. Only once gating has removed every flagged action does `_compute_utility()` run for the survivors, and only then does a genuine utility tie among survivors get broken by cost (ascending, cheaper first) and finally by `action_id` for full determinism -- an ordering this module's own call sequence makes structurally impossible to reverse (cost is never read before the gate has decided eligibility). An action with neither flag declared defaults to `UNVERIFIED` on both axes and is NOT excluded -- exclusion is reserved for an explicit flag, never inferred from silence, per the Evidence Truth Rule's ban on treating absence as a finding. An action missing a required utility factor, or declaring an invalid one (zero, negative, boolean, non-numeric, NaN/inf), or declaring an unrecognized gate-status string, is reported `UNRANKABLE` in a third bucket rather than given a fabricated default.

Front door: `python -m dv_harness.coverage_closure_action_utility --candidates-file <file.json> [--json]` (exit 0 all ranked/excluded, 1 at least one candidate is unrankable). No `dv-harness` CLI verb was added and `gates.py`/`cli.py`/`CLAUDE.md` were not touched, per this task's own file-safety scope; this module imports nothing from `dv_harness` itself, including no file from the concurrently-running batch, accepting a candidate action only as a generic duck-typed mapping/object.

Proven by `dv_harness_tests/test_coverage_closure_action_utility.py` (24 tests): the core positive path ranking three candidates by the exact formula; the two headline negative controls proving a cheap/enormous-utility action flagged `FLAGGED_INCORRECT`/`HIGH_RISK` is excluded entirely and never outranks a correct/safe modest-utility one (a case constructed so the wrong action's utility, if computed, would rank #1); a both-flags-together case; cost breaking a genuine utility tie only among gate-cleared candidates, plus a deterministic `action_id` final tie-break; six invalid-factor-value negative controls (0, negative, bool, non-numeric, NaN, inf); a missing-factor negative control; two invalid-gate-string negative controls (proven `UNRANKABLE`, never silently defaulted or silently accepted); an empty-candidate-list refusal (never a vacuous ranking); duck-typed dict vs. attribute-object acceptance; `action_id`/`id`/positional-placeholder fallback; rationale pass-through; the report renderer naming all three buckets; and two real `python -m dv_harness.coverage_closure_action_utility` subprocess CLI runs asserting exit codes 0 and 1. `python -m pytest dv_harness_tests/test_coverage_closure_action_utility.py -q` -> `24 passed`.
</content>



<!-- S145: moved verbatim from CLAUDE.md original lines 8735-8789 (M4.6 CLAUDE Context Normalization) -->
## Task Return Model: "No Silent Command Failure" (2026-09-06)

Every task this harness's `command.txt`/pattern architecture dispatches -- one per
`block`/`branch_a*`/`branch_fw`/`branch_b*` branch (see `branch-mapper/SKILL.md`'s
Initialization Task Hierarchy and the AMBA M x N arbitration prose it operationalizes) --
must resolve to a real, evidence-grounded outcome, never an assumed one. Nothing in this
repo checked that before: `loop_budget.FailureType` classifies WHY a STAGE-level retry
failed, a coarser, different question about the harness's own retry loop, and nothing
cross-checked a declared list of dispatched tasks against what a sim.log actually recorded.

`dv_harness/task_return_model.py` is that cross-check. Given a declared task list (a
`task_id` per entry, optionally its `block`/`branch_a*`/`branch_fw`/`branch_b*` layer and
dispatch command) and a real sim.log, `cross_check_task_outcomes()` resolves each declared
task to exactly one of seven outcomes: `PASS` / `FAIL` / `TIMEOUT` / `UNSUPPORTED` /
`INVALID_ARGUMENT` / `ENVIRONMENT_ERROR` / `SILENT_FAILURE_SUSPECTED`. The first six are
canonical dispatch outcomes; `SILENT_FAILURE_SUSPECTED` is not a seventh normal one -- it is
what this module reports when the log gives it no way to determine one of the six, so a
dispatched task that produced no recorded outcome is FLAGGED as suspect rather than silently
treated as PASS or silently treated as FAIL (either would be fabrication). It is a
deliberately DIFFERENT, more granular per-dispatch vocabulary from `loop_budget.FailureType`
and the two are never merged.

**No project in this repo had ever emitted a per-task dispatch-outcome line into a sim.log**,
confirmed by direct grep before building -- so this module defines and documents its OWN
recognized convention, `TASK_RESULT: <task_id> => <OUTCOME>` (case-insensitive, tolerant of
`->`/`:`/`,` separators and PASSED/FAILED/TIMED_OUT/NOT_SUPPORTED/ENV_ERROR spellings), the
same way `sim_log_analysis.SEVERITY_ORDER` states of itself that it is this module's own
enum, not a pre-existing project-wide one. A real dispatch layer must be made to emit lines
in this shape for its tasks to be recognized; until then every declared task in a project's
sim.log honestly resolves to `SILENT_FAILURE_SUSPECTED`, which is the correct, non-fabricated
answer.

`sim_log_analysis.py` is imported READ-ONLY for `parse_epilogue()` (the job-level FINAL
CHECK summary, carried as supplementary context only, never used to override a per-task
verdict). `render_task_outcome_table()` reuses `connectivity.render_markdown_table()`.

**Never guesses between disagreeing or absent evidence.** No occurrence at all -> honest
"no recorded outcome"; an occurrence with an unrecognized outcome token -> not treated as
evidence of any specific canonical outcome; two occurrences for the same task disagreeing on
outcome -> reported as an unresolvable conflict naming both values found, never picked
between. A duplicate, missing, or malformed declared `task_id` is a hard
`TaskReturnModelError`, never silently repaired.

**Deliberately bounded.** This module reads a sim.log and reports; it runs no build, no
regression, no LSF submission, mints no approval, and has no stage gate of its own. There is
no `dv-harness` CLI verb (`cli.py` is out of scope); the ad hoc front door is
`python -m dv_harness.task_return_model --tasks <tasks.json> --log <sim.log> [--json]`.

Proven by `dv_harness_tests/test_task_return_model.py` (24 tests) against a small synthetic
sim.log carrying one real `TASK_RESULT` line per canonical outcome plus one declared task
(`branch_a3_init`) with no recorded outcome at all -- the required silent-failure fixture.
Negative controls: an unrecognized outcome token, conflicting outcomes for one task, and a
task_id that is a substring of another never cross-matching. Both the library API and the
real CLI subprocess are exercised, including its exit-code semantics.


<!-- S146: moved verbatim from CLAUDE.md original lines 8790-8873 (M4.6 CLAUDE Context Normalization) -->
## Shared Bus Resource Registry: Intra-Subsystem branch_fw-vs-branch_a* Race Detection (2026-09-06)

`.claude/skills/CORE/branch-mapper/SKILL.md`'s "AMBA M x N Mapping" section and Initialization Task
Hierarchy item 4 require that a `branch_a{i}` touching a resource shared with other `branch_a*` (or,
by the same class, with the shared `branch_fw` service loop) carry an explicit, real-RTL-evidence
arbitration policy -- never an assumption. `.claude/skills/CORE/pattern-architecture/SKILL.md` section
3.1 names the concrete failure mode this operationalizes: two independent task groups reaching one
physical bus sequencer through two DIFFERENT named locks/semaphores can be interleaved by the
arbitration layer in an order neither author controls, silently overwriting one side's write. That
section's own illustration is `block`/`branch_a*` (DUT-driven) vs `branch_b*` (VIP-driven); the
identical class of race applies to `branch_fw` vs `branch_a*`, because `branch_fw` is deliberately
launched immediately after `branch_a*` starts -- specifically so it can respond "while [a sibling]
port's bring-up is still running" (the same skill, same citation) -- meaning `branch_fw`'s own
event-service loop can genuinely be writing a shared register (e.g. acknowledging/clearing a
genuinely-shared INTERRUPT_CONTROLLER bit) at the exact moment a sibling port's `branch_a{i}` is still
writing a different shared resource (a common PHY config block, a shared reset controller, a shared
APB/AXI master's arbitrated slave).

`dv_harness/shared_bus_resource_registry.py` is that detector, and it is a genuinely DIFFERENT scope
from the two nearest-looking modules, stated explicitly rather than left to be inferred:
`system_resource_inventory.py` (SYS-9..14) is CROSS-SUBSYSTEM / SoC-level -- it collapses two
different ENVIRONMENTS' resource records into one and its DRIVER_CONFLICT means "two subsystems' VIP
agents both drive one interface"; `ip_ownership_conflict.py` is single-subsystem but a static
IDENTITY/ownership question ("is a real VIP agent AND a legacy hand-written BFM/driver both ACTIVE
on one interface", decided once). Neither models a named lock/semaphore at all, and neither asks
whether two TASK GROUPS within one running pattern can reach one resource CONCURRENTLY. This module
is INTRA-subsystem bus ARBITRATION: a runtime task-composition-concurrency question, not an identity
question.

**Evidence, honestly.** No producer anywhere in this codebase extracts "which named lock a
`branch_a{i}`/`branch_fw` task holds while writing register X" from a real `command.txt` pattern or
RTL -- there is no SystemVerilog pattern-body parser in `dv_harness/` (patterns are agent-authored per
`pattern-architecture`'s own checklist). Per the identical honesty `ip_ownership_conflict.py`'s
`legacy_bfm_declarations` already applies, WHICH task group programs WHICH resource under WHICH named
lock is therefore CALLER-DECLARED (`resource_declarations`), never inferred here, and every declared
programmer record REQUIRES a real `evidence` citation (a pattern file:line, or the RTL/PHY doc line
the branch-mapper/interrupt-event-dispatch sourcing rules already require). A declaration with no
evidence, or a `task_group` outside the canonical `block`/`branch_a{i}`/`branch_fw`/`branch_b{i}`
vocabulary (CLAUDE.md's Architecture-conformance audit rule), is marked invalid and drives an honest
`UNKNOWN` status rather than a silent `CLEAR` -- and a non-canonical name is deliberately NEVER read as
proof that a `branch_fw`/`branch_a*` role is ABSENT (a naming defect is not evidence of absence), which
is the one subtlety this module's own TDD negative control caught: an unrecognized `task_group` string
now reports `UNKNOWN_INSUFFICIENT_EVIDENCE`, not a false `NO_CONFLICT`. No timing value,
interrupt-priority scheme, or arbitration WINNER is ever invented -- the module only ever states THAT
two branches can reach a resource without a common real named lock, never WHICH write would win an
interleave. `connectivity_rows` is an optional real `connectivity.build_connectivity_matrix()` input,
used only to resolve a declared resource's real hierarchy path (never invented when absent), via the
identical bind_target-match convention `ip_ownership_conflict.py` already uses the other direction.

**Reuse over reinvent.** `connectivity.render_markdown_table()` renders the mandatory registry table --
no fourth hand-rolled table loop. `loop_budget.FailureType` was read for contrast only, per this
batch's own instruction, and is NOT merged with this module's vocabulary: `CONFLICT_*`/`LOCK_POLICY_*`
is a new, deliberately more granular per-dispatch taxonomy for this different concern.

**Vocabulary.** Report `status`: `CONTENTION` / `CLEAR` / `NOT_APPLICABLE` / `UNKNOWN` (mirroring
`ip_ownership_conflict.py`'s own 4-status shape -- `UNKNOWN` is the Evidence-Truth-Rule-mandated honest
status for untrustworthy/insufficient declarations). Per-resource `conflict_status`: `FW_A_RACE` /
`NO_CONFLICT` / `NOT_APPLICABLE` / `UNKNOWN_INSUFFICIENT_EVIDENCE`. `lock_policy`:
`SINGLE_SHARED_LOCK` / `DISTINCT_LOCKS_PER_TASK_GROUP` / `NO_LOCK_DECLARED` /
`PARTIAL_LOCK_DECLARATION` / `SINGLE_PROGRAMMER_NO_ARBITRATION_NEEDED`. `resource_type` is one of the
task's own four named classes (`APB_AXI_MASTER` / `INTERRUPT_CONTROLLER` / `SHARED_RESET` /
`SHARED_PHY_CONFIG`) or `UNCLASSIFIED` -- caller-declared, never guessed from a resource's name, and an
unrecognized value is carried through verbatim with `resource_type_recognized: false` rather than
silently coerced. A racing entry's `conflicting_owners` names the real branch ids, declared lock names
and evidence citations on BOTH sides of every non-agreeing branch_fw/branch_a* pair.

**Detection only, matching the sibling modules' own stated boundary.** This module never picks a lock,
never edits a pattern file, never invents a lock name, and never touches any approval/governance
mechanism -- a human aligns the racing branches onto one real named lock, from real RTL/pattern
evidence. Front door: `python -m dv_harness.shared_bus_resource_registry --resource-declarations
<file> [--connectivity-rows <file>] [--json]` (no `dv-harness` CLI verb wired; exit 0 `CLEAR` / 1
`CONTENTION` / 2 `NOT_APPLICABLE`-or-`UNKNOWN`).

Proven by `dv_harness_tests/test_shared_bus_resource_registry.py` (31 tests): canonical task-group
classification (including 8 non-canonical negative forms), the core branch_fw-vs-branch_a* race
(mismatched-lock and both-sides-no-lock variants), the positive control (a genuinely shared named lock
reports `CLEAR`), five negative controls (no declarations, a single-programmer resource, a
branch_a-only pair correctly out of this module's scope, a non-canonical task_group name correctly
yielding `UNKNOWN` rather than a false `CLEAR`, missing evidence yielding `UNKNOWN`), a real race still
detected despite a second invalid declaration on the same resource, duplicate-resource-id refusal,
overall-status precedence, `lock_policy` unit checks, connectivity-rows enrichment (present and
absent), `resource_type` honesty, rendering, and 3 real CLI subprocess invocations asserting exit codes
1/0/2.


<!-- S147: moved verbatim from CLAUDE.md original lines 8874-8949 (M4.6 CLAUDE Context Normalization) -->
## Per-Pattern Runtime Execution State Machine (2026-09-06)

`dv_harness/pattern_runtime_state_machine.py` is a per-PATTERN execution state machine:
`CREATED -> PARSED -> VALIDATED -> READY -> RUNNING -> WAITING -> CHECKING ->
PASS/FAIL/TIMEOUT/BLOCKED/CANCELLED`, with legal-transition enforcement
(`assert_legal_transition()`/`advance_pattern_state()` raise `IllegalPatternTransitionError`
on any jump not present in the module's TOTAL `LEGAL_TRANSITIONS` table -- e.g. CREATED
straight to PASS -- and on any transition attempted from a terminal state).

**This tracks one `command.txt`/pattern file's own execution lifecycle**, at the granularity
`pattern-architecture/SKILL.md` describes: `block -> branch_a* -> branch_fw -> fork/join of
branch_b* -> verdict/FINAL_CHECK`. CREATED/PARSED/VALIDATED/READY are the file's pre-run states;
RUNNING/WAITING/CHECKING are in-flight (a `branch_b*` fork sitting on its own `join` -- never
`join_any`, per that skill's section 2 -- then the FINAL_CHECK verdict step); the five terminal
states are this one pattern's own outcome. RUNNING is legally allowed to skip WAITING straight to
CHECKING (section 4: whether `branch_b*` forks at all varies with test intent), and WAITING never
returns to RUNNING (this tracks the pattern's own top-level phase, not `branch_fw`'s internal
ARM/WAIT/WAKE/DECODE/CLEAR cycling, which `interrupt-event-dispatch/SKILL.md` already owns).

**Deliberately a SEPARATE vocabulary from `loop_contract.LoopState`, with NO bridge built.**
`LoopState` answers "where is this LOOP -- the whole verification-closure process across many
stages/patterns/regression cycles -- as a control process, right now"; `PatternRuntimeState`
answers "where is THIS ONE PATTERN's own execution, right now" -- a question meaningful many
times within a single loop iteration. No member name means the same thing across the two
vocabularies (this module's PASS/FAIL are one pattern's own FINAL_CHECK/scoreboard verdict;
`LoopState` has no PASS/FAIL at all, by design, precisely so the two are never conflated), and a
forced mapping between them would misrepresent one as the other -- exactly the caution
`loop_contract.py`'s own docstring gives for `Status` vs. `LoopState`, applied here one more time
in the other direction. No `STATUS_TO_LOOP_STATE`-style bridge exists or is planned for this pair.

**Also deliberately distinct, and reused rather than merged, from `sim_log_analysis`'s triage
categories and `loop_budget.FailureType`.** Those classify WHY a dispatch failed, at the loop's
own per-stage-attempt retry-budget granularity. This module's states are WHEN, in one pattern's
own lifecycle, execution currently sits -- an orthogonal, finer-grained axis. This module REUSES
`sim_log_analysis.parse_epilogue()`/`classify_signatures()` as its sole evidence reader (no second
marker scan) and never imports or extends `loop_budget.FailureType`.

**Terminal-verdict observation is evidence-derived, never fabricated.**
`derive_observed_terminal_verdict(log_text)` reads one real sim.log and reports exactly what that
log's own evidence supports: a real FINAL CHECK epilogue `VERDICT: PASSED|FAILED` line when
present (this project's own documented FINAL_CHECK convention); absent that, a real fatal/error/
scoreboard-mismatch/assertion marker reports FAIL, or a real timeout/deadlock marker reports
TIMEOUT; a log carrying none of the above -- ends cleanly, with zero errors, and states no verdict
at all -- is reported `SILENT_FAILURE_SUSPECTED` (never defaulted to PASS), which is exactly
`pattern-architecture/SKILL.md` section 2's own documented join/join_any silent-early-pass trap
("the run ends cleanly, with zero errors, because nothing had a chance to fail yet") read back as
a runtime observation; empty log text reports `NOT_AVAILABLE`. `apply_observed_verdict()` composes
this with the enforcement layer: it refuses to guess a state when no terminal verdict is
supported (returns unapplied, record untouched), and it still enforces `LEGAL_TRANSITIONS` even
against real terminal evidence -- having sim.log evidence for the END does not excuse skipping the
recorded MIDDLE.

Also included: `render_pattern_state_table()` (reuses `connectivity.render_markdown_table()`, this
repo's only parameterized table renderer), and a small atomic-replace-backed JSON store
(`load_records()`/`save_records()` under `<root>/.dv-harness/pattern_runtime/records.json`, reusing
`storage._atomic_replace()`).

**Deliberately bounded.** (1) It DECIDES and ARBITRATES nothing beyond one pattern's own recorded
phase -- no build, no job, no LSF submission, no approval, and there is no stage gate. (2) A
pattern that reaches a terminal state is re-run as a fresh record (a new `create_pattern_record()`
call), not resumed in place -- unlike a persistent loop session, one pattern's own runtime state
carries no partial progress worth preserving across a restart. (3) It is REACHED, not WIRED: there
is no `dv-harness` CLI verb (`cli.py` was not touched, per this batch's file-safety scope) -- the
front door is `python -m dv_harness.pattern_runtime_state_machine {states|show|list|observe}` --
and no `run_stage()`/`advance()` call site or graph node invokes it.

Proven by `dv_harness_tests/test_pattern_runtime_state_machine.py` (33 tests): totality of
`LEGAL_TRANSITIONS` over every state; the full happy-path progression to PASS; RUNNING legally
skipping WAITING; 8 negative controls including the task's own named example (CREATED straight to
PASS rejected), no transition legal from a terminal state, and WAITING never returning to RUNNING;
all four real `derive_observed_terminal_verdict()` outcomes, including the central "clean log with
no epilogue/markers is SILENT_FAILURE_SUSPECTED, never PASS" assertion; `apply_observed_verdict()`
composing evidence with enforcement (including refusing real terminal evidence against a record
that skipped its recorded middle); table rendering; and the JSON store's round-trip, bare-root and
corrupt-store paths.


<!-- S148: moved verbatim from CLAUDE.md original lines 8950-8998 (M4.6 CLAUDE Context Normalization) -->
## Runtime CONTROL-Command Closed Vocabulary (2026-09-06)

command.txt/pattern files carry an explicit rule -- "do not create unrestricted scripting
behavior in command.txt" -- that nothing in this repo enforced. `dv_harness/
runtime_control_commands.py` closes it: it validates that any statement it classifies as a
CONTROL command belongs to the CLOSED vocabulary `WAIT / POLL / REPEAT / BOUNDED_LOOP / SYNC /
BARRIER` (else `ILLEGAL_CONTROL_COMMAND`), and that `REPEAT`/`BOUNDED_LOOP` -- the two vocabulary
words that name an iteration count -- declare a real bound argument (else
`ILLEGAL_UNBOUNDED_LOOP`, even when the command's own name is `BOUNDED_LOOP`: the label is never
trusted over its own argument).

**Reuse, not reinvention.** Parsing is entirely delegated to the existing, real
`reference_pattern_audit.extract_command_statements()` parser -- this module never re-parses
command.txt text of its own. A statement is CONTROL-classified either (a) unconditionally, when
its real `.category` (already computed by that module) is `C_CONTROL_FLOW` or `C_SYNCHRONIZATION`
-- native `repeat`/`while`/`for`/`forever`/`if`/`fork`/`join`/`disable`/`wait(...)`/`@(...)`/`#...`
used DIRECTLY, which IS the "unrestricted scripting" the rule forbids -- or (b) for a backtick
macro/model-task call, via a disclosed NAME-EVIDENCE classification against
`CONTROL_INTENT_NAME_TOKENS`, in the exact convention `reference_pattern_audit.classify_wait()`
already established (a cited heuristic, never proof), because that module's own `_categorize()`
deliberately leaves a bare macro call `C_UNCLASSIFIED` -- it cannot know a macro's purpose from its
name, and real command.txt control-flow is overwhelmingly expressed via backtick macros (per
`pattern-architecture/SKILL.md`'s own USB illustrations), so a check limited to the two existing
native categories would miss almost every real control command. Report rendering reuses
`connectivity.render_markdown_table` (the repo's one parameterized table renderer).
`loop_budget.FailureType` (a DIFFERENT, harness-stage-failure taxonomy) is deliberately not merged
with this module's per-dispatch vocabulary.

**Evidence Truth Rule.** A statement not recognized as control-shaped is absent from the report,
never silently "passed". A file that cannot be read/parsed is `NOT_AVAILABLE`, never a fabricated
`CLEAN`. The "declared bound" check only asks whether a non-empty argument token exists in the
count position -- it cannot resolve `` `define ``d constants to a finite value, and this module
invents no "this literal value means unbounded" sentinel convention, since no such convention has
been observed in this project's own evidence.

`analyze_control_commands(path_or_statements)` / `classify_control_commands(statements)` /
`render_control_commands_markdown(report)`; CLI: `python -m dv_harness.runtime_control_commands
--command-file <file> [--json]` (exit 0 CLEAN, 1 a real violation, 2 NOT_AVAILABLE). It decides
nothing beyond reporting -- no build, no job, no approval, and deliberately no stage gate.

Proven by `dv_harness_tests/test_runtime_control_commands.py` (23 tests) against real
command.txt-shaped synthetic files parsed by the real `reference_pattern_audit`
parser: the clean six-word positive path; register/model-task macros never misclassified as
control; out-of-vocabulary control-intent macros and raw native `while`/`fork`/`join` each flagged
`ILLEGAL_CONTROL_COMMAND`; bare `` `BOUNDED_LOOP ``, empty-parens `` `BOUNDED_LOOP() ``, bare
`` `REPEAT ``, and native `repeat()` each flagged `ILLEGAL_UNBOUNDED_LOOP` (including the explicit
"legal name, no declared bound" case); a missing file reporting `NOT_AVAILABLE` rather than a
fabricated `CLEAN`; and the real CLI driven as real subprocesses for all three exit codes.


<!-- S149: moved verbatim from CLAUDE.md original lines 8999-9054 (M4.6 CLAUDE Context Normalization) -->
## DE Command Registry Semantic Diff: `command_txt_change_impact.py` (2026-09-06)

The Engineering Discipline Rules' "command.txt change-impact check" (restated from
`.claude/skills/CORE/command-inventory/SKILL.md`) requires re-checking `.dv-workflow/
command_inventory.csv` against existing command.txt/scenario cases after every
generator/schema change -- a FILE-PRESENCE / regression-selection question already
answered by `change_impact.py`'s real git-diff-driven selection machinery. It never asked
the narrower question this module answers: given two actual snapshots of a DE command
registry (before/after some edit), which individual commands' own DEFINITIONS changed,
and how.

`dv_harness/command_txt_change_impact.py` is a semantic diff over two
DECommandRegistryIR-shaped snapshots, accepted purely as duck-typed dicts/lists -- it
never imports `de_command_style_learning.py` (the real producer of that shape, owned by
a separate concurrent effort) or `spec_vplan_delta.py` (whose semantic-diffing PATTERN it
mirrors with its own parallel logic, never shared code, since the two modules diff
structurally different things). Every field (command id, parameters, protocol,
semantic_role, handler, vip_sequence, effects, deprecated/status, source) is resolved
through a small alias table that tracks FOUND vs. NOT-FOUND separately from a real empty
value, so a field a producer has not yet stabilized never gets silently misread as
unchanged.

**Vocabulary**: UNCHANGED / ARGUMENT_CHANGE / SEMANTIC_CHANGE / NEW_COMMAND /
REMOVED_COMMAND / DEPRECATED / AMBIGUOUS -- deliberately disjoint from both
`models.Status` and `loop_budget.FailureType` (checked by
`assert_no_verification_verdict_vocabulary()`, not merely claimed). Precedence,
worst-first: an explicit deprecated signal wins; else any semantic-facet difference
(including reinstatement out of deprecation); else a positional parameter-list
difference (parameter ORDER is load-bearing for a command.txt macro/task call, so this
never sorts by name); else any facet this module could not resolve on both sides ->
AMBIGUOUS, never silently read as UNCHANGED; else UNCHANGED.

**Never fabricates a rename.** A command whose id disappears from the old snapshot and a
differently-spelled replacement in the new one are always reported as one
REMOVED_COMMAND plus one NEW_COMMAND -- matching them by guessed similarity would be
exactly the invented linkage the Evidence Truth Rule forbids.

Reuses `connectivity.render_markdown_table()` for its markdown rendering -- no new table
renderer. There is no `dv-harness` CLI verb (`cli.py` was out of scope for this batch);
the front door is `execute_verb()`/`main()`, runnable as
`python -m dv_harness.command_txt_change_impact --old <old.json> --new <new.json>
[--json]` (exit 0 nothing concerning, 1 a concerning verdict present, 2 unreadable/
unparseable input). It runs, builds, submits and approves nothing.

Proven by `dv_harness_tests/test_command_txt_change_impact.py` (34 tests): the core
UNCHANGED baseline, NEW_COMMAND/REMOVED_COMMAND (with a dedicated no-guessed-rename
negative control), ARGUMENT_CHANGE for added/reordered/retyped parameters,
SEMANTIC_CHANGE (including one that outranks a simultaneous argument change and one
proving whitespace-only `effects` reformatting is NOT a false positive), DEPRECATED
(flag and status-string forms, plus reinstatement folding into SEMANTIC_CHANGE), four
AMBIGUOUS negative controls (schema-gap fields, missing parameters, duplicate
command_id, an unresolved facet that must not default to UNCHANGED), unindexable/
malformed records reported rather than dropped, a genuinely unparseable snapshot
raising rather than reading as an empty registry, all three accepted container shapes,
and the real CLI driven as a subprocess.


<!-- S150: moved verbatim from CLAUDE.md original lines 9055-9119 (M4.6 CLAUDE Context Normalization) -->
## Command Precondition Gate (2026-09-06)

`runtime_event_registry.py` (built earlier in this same workflow run) tracks NAMED RUNTIME EVENTS
with REQUIRES/WAITS_FOR/TRIGGERS/UNBLOCKS dependency propagation and answers "what is this event's
status" -- it deliberately does not answer the adjacent question a command dispatcher must ask
before launching a `block`/`branch_a*`/`branch_fw`/`branch_b*` task
(`.claude/skills/CORE/branch-mapper/SKILL.md`'s Initialization Task Hierarchy,
`.claude/skills/CORE/pattern-architecture/SKILL.md`'s five-layer shape): "does THIS COMMAND's own
declared precondition SET currently hold?" A repo-wide search found no code joining a command's own
declared prerequisite names to the registry's real event states -- `command_error_taxonomy.py`
classifies a dispatch's FAILURE text after the fact, and `init_seq.py`'s
`evaluate_gate2_preconditions()` is a different, narrower mode-bit/register precondition check for
connectivity Gate 2, not a general per-command runtime-event precondition gate.

`dv_harness/command_precondition_gate.py` closes exactly that, and reuses rather than reinvents:
a command declares its own precondition NAMES (GLOBAL_READY/DUT_READY/FW_READY/VIP_READY/
MODE_VALID/RESET_DEASSERTED/PHY_READY are illustrative examples only -- never a hardcoded universal
list; a project's real names are declared by its caller exactly as `runtime_event_registry`'s own
event set is), and each is checked against a real `RuntimeEventRegistry.propagate()`'s EFFECTIVE
(post-propagation) status -- computed once per evaluation, never re-derived or guessed. This module
invents no interrupt-priority scheme, no arbitration policy and no timing value, and parses no
sim.log itself; whether an event "really" fired stays `runtime_event_registry`'s own caller-supplied,
evidence-cited fact.

**Vocabulary: exactly READY / BLOCKED / UNKNOWN_PRECONDITION**, deliberately distinct from both
`runtime_event_registry.EventStatus` (checked disjoint at import via
`assert_no_dispatch_status_vocabulary_collision()`, the same discipline
`runtime_event_registry.assert_no_status_vocabulary_collision()` applies one level down) and
`command_error_taxonomy`'s eleven-value per-dispatch-failure classification. Per-command status folds
worst-first: any precondition resolving to a known event that is FAILED/TIMEOUT/
BLOCKED_BY_DEPENDENCY makes the command BLOCKED (real evidence outranks everything else); else any
precondition naming NO event in the registry at all makes it UNKNOWN_PRECONDITION -- never silently
assumed satisfied; else any known event still PENDING (declared, not yet observed to fire) makes it
BLOCKED in the classic process-scheduling sense ("waiting on a condition that hasn't occurred");
else, every declared precondition FIRED (or none declared at all) makes it READY. Every verdict
carries the full per-precondition evidence (`known`/`effective_status`/`raw_status`/`reason`) so an
UNKNOWN_PRECONDITION or BLOCKED finding is never lost even when another precondition on the same
command is fine.

`dv-harness` `cli.py` was under concurrent modification by other parallel gap-closure work this same
session, so no `cli.py` verb was added -- the front door is
`python -m dv_harness.command_precondition_gate list|check --commands <commands.json>
[--registry <events.json>] [--out <path>] [--json]`, one shared `execute_verb()`. `list` needs only
the command declarations; `check` runs `registry.propagate()` once and evaluates every declared
command against that single propagated state. Exit 0 every command READY, 1 at least one BLOCKED or
UNKNOWN_PRECONDITION, 2 NOT_AVAILABLE or a usage/declaration error.

**Deliberately bounded, and stated rather than implied closed.** (1) It decides nothing beyond
reporting: no dispatch is actually performed, no build/job/approval, and there is deliberately no
stage gate. (2) A precondition name is matched EXACTLY against a declared event name -- no fuzzy or
prefix matching, no alias table. (3) It evaluates one registry's state at one point in time; it is
not a subscription or re-poller and reports no history.

Proven by `dv_harness_tests/test_command_precondition_gate.py` (30 tests) against a real
`RuntimeEventRegistry` matching this repo's own `block`/`branch_a*`/`branch_fw`/`branch_b*`
vocabulary: the core READY path, a genuinely FAILED precondition, a `BLOCKED_BY_DEPENDENCY` cascade
(reading the real EFFECTIVE, post-propagation status rather than the raw one), a TIMEOUT
precondition, a still-PENDING precondition (BLOCKED but distinctly, via `awaiting_preconditions`
rather than `blocking_preconditions`), an unresolved precondition name (UNKNOWN_PRECONDITION, never
silently READY), and the headline mixed case proving BLOCKED outranks UNKNOWN_PRECONDITION when a
command declares both kinds of trouble at once. Declaration-level negative controls (blank
command_id, blank/duplicate precondition names, malformed JSON, missing files) and the vocabulary
disjointness assertion are also covered, plus both real CLI verbs driven as real subprocesses with
their exit codes asserted.


<!-- S151: moved verbatim from CLAUDE.md original lines 9120-9200 (M4.6 CLAUDE Context Normalization) -->
## System Readiness Gates: Eight Named Composite Gates Over SYS-37's Own Evidence (2026-09-06)

`system_readiness.derive_system_readiness()` already folds SYS-37's ten named inputs (subsystem
readiness, shared-resource conflicts, command compatibility, scoreboard compatibility, address map,
clock/reset, VIP dedup resolution, build integration, scenario availability, regression evidence)
into ONE READY/PARTIAL/BLOCKED/UNKNOWN verdict -- correct for "can this composition be integrated at
all", and the wrong shape for "WHICH concern is what is actually stopping it". A caller staring at
one PARTIAL verdict over ten inputs still has to open the `inputs` list by hand to find the single
CONCERN among them. `dv_harness/system_readiness_gates.py` is that missing layer: eight NAMED
composite gates, each a real AND-formula over a domain-scoped subset of SYS-37's own real inputs
(plus SYS-35's real version-pin `restorable` field and SYS-33's real regression-plan `entry_count`),
computing nothing new -- every fact is read verbatim off `derive_system_readiness()`'s already-real
result, imported and called read-only.

**Every one of SYS-37's ten inputs is owned by exactly one of the first seven gates, never
re-derived twice, never dropped**: `SUBSYSTEM_SELECTION_READY` (a non-empty SYS-1 selection, all
SYS-4 READY -- `subsystem_readiness`); `RESOURCE_RECONCILIATION_READY` (SYS-24 shared-resource
scheduling clean, SYS-11/12/17 VIP-dedup/ownership clean -- `shared_resource_conflicts`,
`vip_dedup_resolution`); `COMMAND_COMPATIBILITY_READY` (SYS-18..22 command-plan collisions/mode
preservation clean -- `command_compatibility`); `SCOREBOARD_COMPOSITION_READY` (SYS-26 scoreboard
reuse clean AND the cross-subsystem topology facts a correlation layer needs -- SYS-28 address map,
SYS-29 clock/reset -- are themselves clean -- `scoreboard_compatibility`, `address_map`,
`clock_reset`); `BUILD_COMPOSITION_READY` (SYS-4's per-subsystem build presence clean AND SYS-35's
version pin is genuinely restorable -- `build_integration`, plus a real check of
`build_composition_version_pin()`'s own `restorable` field); `REGRESSION_PLAN_READY` (SYS-4's
regression-evidence factor clean, SYS-30 cross-subsystem scenarios exist to regress, AND SYS-33's
plan really derived at least one entry -- `regression_evidence`, `scenario_availability`, plus a
real check of `build_system_regression_plan()`'s own `entry_count`); `ERROR_HANDLING_READY` (SYS-37's
own closing rule made checkable: the VIP-dedup input -- the one whose BLOCKED status IS "an
unresolved DRIVER_CONFLICT or a blocked dedup decision" -- is clean, AND no SYS-37 input at all is
BLOCKED); `SYSTEM_SIGNOFF_READY` (every one of the above seven gates READY, AND SYS-37's own overall
`system_readiness` verdict is READY).

**The same worst-wins, no-averaging discipline this project already applies everywhere**
(`subsystem_maturity_gate.py`, `functional_coverage_signoff.py`, `spec_vplan_readiness_gate.py`) is
enforced by one shared `_fold()`: a single condition that is BLOCKED or CONCERN makes the WHOLE gate
`NOT_READY` regardless of how many other conditions on that gate are clean -- two clean conditions
and one blocked one is not "mostly ready". A condition genuinely absent evidence for (no scheduling
plan was supplied, no version pin exists because nothing was selected) is UNKNOWN, and -- when
nothing worse is present on that gate -- makes the WHOLE gate `INCOMPLETE_EVIDENCE`, a THIRD value
distinct from both `READY` and `NOT_READY`. This is GF-AT-28 as a hard constraint on this module
specifically: a Critical UNKNOWN must never silently become READY, and it must equally never be
reported as a confirmed NOT_READY it was never proven to be. Only when every required condition on a
gate is CLEAR does that gate report `READY`. `GATE_VERDICTS = (READY, NOT_READY,
INCOMPLETE_EVIDENCE)` is asserted, at import time, to share no token with `dv_harness.models.Status`
-- the same guard several sibling composite-gate modules already apply to their own vocabularies.

**File-safety scope was held exactly**: the only imports are `dv_harness.system_readiness` (the
real, pre-existing, non-claimed module this task named) and `dv_harness.models` (for the
vocabulary-collision guard); nothing from the concurrent batch's claimed-file list or any other new
module in this batch is imported, and `gates.py`/`cli.py`/`CLAUDE.md` are untouched.

This module authorizes nothing beyond reporting -- exactly like SYS-37 itself, a `SYSTEM_SIGNOFF_READY`
verdict here is an input to the SYS-39 human-approval gate, never a substitute for it. No stage runs,
no gate script is invoked, no build/regression/LSF job starts, no approval is minted, and there is no
`gates.py`/`STAGE_GATES` entry.

Proven by `dv_harness_tests/test_system_readiness_gates.py` (16 tests): the core positive path drives
the REAL `system_readiness.derive_system_readiness()` over a fully-populated, all-clear synthetic
SYS-1/17/18-22/24/26/28/29/30/33/35 evidence set (built directly against each real `_xxx_input()`
helper's own documented CLEAR condition) and asserts every one of the eight named gates reports
READY; a GF-AT-28 control drives `derive_system_readiness()` over completely empty evidence (every
SYS-37 input UNKNOWN) and asserts every gate reads `INCOMPLETE_EVIDENCE`, never `READY`; six further
real negative controls each flip exactly one real fact -- a BLOCKED subsystem, a blocking command
collision, an address-map conflict, an unresolved `DRIVER_CONFLICT`, an unpinned subsystem, zero
cross-subsystem scenarios, a zero-entry regression plan, and a missing regression plan -- with
everything else left clean, and assert the fold caught exactly that one defect on exactly the
gate(s) that own it while every unaffected gate stays READY. Structural tests hold the
vocabulary-collision guard, the exactly-eight-named-gates invariant, and the malformed-input/
unrecognized-condition-status refusals.

**Deliberately bounded, and stated rather than implied closed.** (1) It derives no new SYS-level fact
of its own -- every condition traces to a real `system_readiness.py`/SYS-35/SYS-33 value, never
re-computed. (2) There is no `dv-harness` CLI verb and no `STAGE_GATES` entry (per this task's own
file-safety scope, `gates.py`/`cli.py` were not touched) -- the front door is
`system_readiness_gates.derive_system_readiness_gates()` /
`derive_system_readiness_gates_from_assessment()`, a REACHED capability rather than a WIRED one, in
the same sense several other 2026-09-06 additions above disclose. (3) It arbitrates nothing: an
unresolved active-driver conflict still names SYS-12's preferred model as text for a human; nothing
here picks a winner.


<!-- S152: moved verbatim from CLAUDE.md original lines 9201-9307 (M4.6 CLAUDE Context Normalization) -->
## System Error Propagation IR: Tracing a Real Cross-Subsystem Blast Radius (2026-09-06)

`system_topology_analysis.py`'s SYS-28/SYS-29 machinery already computes the only real
cross-subsystem RELATIONSHIPS this repository has: which address regions two subsystems
physically share or collide over, which interrupt line names two or more subsystems' own
evidence both name, and which clock/reset names two subsystems share (or cross a shared-address
path between). Nothing in this repo turned those relationships into a PROPAGATION graph, or
asked "if subsystem X faults with condition Y, which OTHER subsystems does the topology's own
evidence actually show could be affected, and has each of those affected subsystems got a real
declared recovery action on file?" `dv_harness/system_error_propagation.py` is exactly that trace
and nothing else.

Per this addition's own file-safety scope, it never imports `system_topology_analysis.py` (or
`system_resource_inventory.py`). It accepts a `topology` parameter that is a generic, duck-typed
Mapping shaped like that module's real `build_system_topology_analysis()` output --
`address_map_reconciliation.overlaps`, `interrupt_map_reconciliation.lines`,
`clock_reset_comparison.clock_comparisons`/`reset_comparisons` -- read by plain dict access, never
by importing that module's classes or re-deriving its own analysis. A caller already holding a
real topology document may pass it here verbatim.

**A propagation edge is minted ONLY from a topology verdict that module's own signal functions
already treat as a proven coupling, never from its own honest "could not tell" values.** Address:
`SHARED_MEMORY` / `ADDRESS_OVERLAP_VALID` / `ADDRESS_OVERLAP_CONFLICT` count; SYS-28's own
`UNKNOWN` (a data-quality defect inside ONE subsystem's own artifacts, per that module's
`_overlap_signals()` docstring) is excluded -- asserting a path on it would manufacture a
cross-subsystem finding out of a single subsystem's internal inconsistency, exactly the failure
mode that module's own comment warns against. Interrupt: only
`INTERRUPT_LINE_SHARED_ACROSS_SUBSYSTEMS` rows become edges (every pairwise combination among the
row's own `subsystems` list). Clock/reset: `SAME_CLOCK_DOMAIN` / `CONFLICTING_CLOCK_SOURCE` /
`CONFLICTING_CLOCK_FREQUENCY` and `CDC_BOUNDARY` (clock), `SAME_RESET_DOMAIN` /
`CONFLICTING_RESET_POLARITY` / `CONFLICTING_RESET_SEQUENCING` (reset) -- the first three of each
group fire only when both subsystems name the IDENTICAL signal (a real shared net, whatever the
two sides' stated frequency/source/polarity/sequencing then say), and `CDC_BOUNDARY` is a real
SYS-28 shared-address path crossing two differently-named clock domains. `INDEPENDENT_CLOCK_
DOMAIN`/`INDEPENDENT_RESET_DOMAIN` and either family's shared `UNKNOWN` are excluded.

**Propagation is real graph reachability, not "every other subsystem".** `bfs_reachable()` runs a
real breadth-first search from the origin over only the edge kinds relevant to the declared
error-condition kind (`CONDITION_TO_EDGE_KINDS`: `ADDRESS_DECODE_FAULT`/`BUS_ERROR`/
`DMA_CORRUPTION` -> shared-address edges only; `INTERRUPT_STORM` -> shared-interrupt-line edges
only; `RESET_ASSERTION` -> shared-reset-domain edges only; `CLOCK_LOSS` -> shared-clock-domain
edges only; `CDC_VIOLATION` -> clock-domain-crossing plus shared-clock/reset edges; `GENERIC`, or
any condition kind this module does not recognize, uses every edge kind -- the widest set, never a
narrower guess). A subsystem the graph does not actually connect to the origin under those edge
kinds is never reported as affected, which is the direct enforcement of "never assert propagation
reaches a subsystem the topology does not actually show a path to." Multiple hops are followed
(a real chain of proven edges), each affected subsystem's report carrying the real edge chain that
reaches it.

**A declared recovery/response action per subsystem has no real producer anywhere in this
codebase** (confirmed by direct search before building: no `recovery_action`/`expected_response`/
`error_handler` field exists in `env_manifest.py`'s schema or any sibling module's output), so it
is honestly a CALLER-SUPPLIED input -- the same status `ip_ownership_conflict.py`'s
`legacy_bfm_declarations` and `system_resource_inventory.SubsystemResourceSources.declared_
physical_interfaces` already carry for their own no-producer facts. `resolve_declared_response()`
grades each affected subsystem's record into one of four statuses -- `RESPONSE_DECLARED` (a real,
non-placeholder recovery-action text), `NO_RESPONSE_DECLARED` (no matching record at all, or a
record with no usable text), `RESPONSE_PLACEHOLDER_ONLY` (a value like `TBD`/`N/A`/`unknown`/`?`),
`RESPONSE_EXPLICITLY_DECLARED_NONE` (a record explicitly stating `declares_response: false`) --
and only `RESPONSE_DECLARED` satisfies the chain.

**The Recovery Chain vocabulary is this batch's own rule 8, enforced in code rather than restated
in prose.** `RECOVERY_CHAIN_COMPLETE` fires only when EVERY affected subsystem carries
`RESPONSE_DECLARED`; a single missing, placeholder, or explicitly-none response among any number
of otherwise-clean ones makes the WHOLE chain `RECOVERY_CHAIN_INCOMPLETE`, naming exactly which
subsystem(s) are missing -- never silently folded into COMPLETE, and never defaulted to "assume
recovered" when no `declared_responses` input was supplied at all. Zero affected subsystems is the
honestly distinct `NO_PROPAGATION_DETECTED` (the topology shows the error contained to its origin
-- nothing was actually verified, so it is never presented as if it were a checked-and-clean
COMPLETE). An origin the topology does not name anywhere, or an empty topology carrying no
subsystem evidence in any of its three blocks, reports `NOT_AVAILABLE` rather than a guessed
trace.

`assert_no_verification_verdict_vocabulary()` (imported from the stable `dv_harness.models`, not a
claimed-batch file) holds every one of this module's own vocabularies -- the four Recovery Chain
statuses, the four response statuses, the eight condition kinds, the five edge kinds -- disjoint
from `models.Status`, the same discipline several sibling modules already apply to their own
vocabularies.

**Deliberately bounded, and stated rather than implied closed.** (1) It never arbitrates which
subsystem's declared response is correct, never decides a propagation path should be architecturally
broken, and never picks an error-handling strategy -- detection and reporting only. (2) It never
invents a declared response: an absent `declared_responses` input reads every affected subsystem as
`NO_RESPONSE_DECLARED`, never an assumed recovery. (3) It reuses SYS-28/SYS-29's own already-computed
verdicts verbatim and computes no address/interrupt/clock/reset relationship of its own -- if the
supplied topology's own analysis is wrong, this module's trace inherits that, honestly, rather than
re-deriving a second opinion. (4) There is no `dv-harness` CLI verb (`cli.py`/`gates.py` untouched,
per this batch's file-safety scope) -- the front door is
`python -m dv_harness.system_error_propagation trace --origin ... --condition ... --topology ...
[--declared-responses ...] [--json]`.

Proven by `dv_harness_tests/test_system_error_propagation.py` (15 tests) against small synthetic
topology fixtures shaped exactly like `system_topology_analysis.py`'s real output: the positive path
(a shared-memory edge propagates an `ADDRESS_DECODE_FAULT` to one real neighbor with a complete
recovery chain), plus real negative controls -- a missing declared response reads
`RECOVERY_CHAIN_INCOMPLETE` rather than `COMPLETE`; condition-relevant edge-kind filtering (an
`INTERRUPT_STORM` never follows a shared-address edge even when one is present, and a `CDC_VIOLATION`
uses the clock-domain-crossing edge but never a plain shared-address one); an honest SYS-28/SYS-29
`UNKNOWN`/`INDEPENDENT_*` verdict is never treated as a proven path; an origin absent from the
topology and an empty topology both report `NOT_AVAILABLE`; a real multi-hop transitive BFS chain is
followed correctly, with a placeholder (`"TBD"`) response graded the same as a genuinely missing one;
an explicitly-declared-no-response record is reported distinctly from a genuinely absent one; an
unrecognized condition kind is treated as `GENERIC` with a named unknown rather than guessed; and
malformed-input refusals (an empty origin, a non-mapping topology). The real CLI is driven as three
subprocesses asserting exit codes 0 (`RECOVERY_CHAIN_COMPLETE`), 1 (`RECOVERY_CHAIN_INCOMPLETE`), and
2 (`NOT_AVAILABLE`).


<!-- S153: moved verbatim from CLAUDE.md original lines 9308-9324 (M4.6 CLAUDE Context Normalization) -->
## Subsystem Adapter IR: a Fixed 8-Operation Facade Over Real Task/Sequence Names (2026-09-06)

Every subsystem-mode verification environment this project builds already carries its own real, generated task/sequence names -- an `init_seq.py`-style directed test step, a `branch_b*`-driven VIP sequence, a hand-authored `command.txt` task, each following that particular subsystem's own naming convention. Nothing anywhere spoke a FIXED, cross-subsystem vocabulary of logical operations against those real names: a caller wanting to "start this subsystem" or "wait until it is ready" had no single place to ask that question without first learning the specific subsystem's own naming scheme. Building a second task/sequence catalog from scratch, or guessing a plausible task name for an operation nobody actually declared, would be exactly the "invent a stub implementation" the Evidence Truth Rule forbids.

`dv_harness/subsystem_adapter_ir.py` is the facade, and only the facade. `LOGICAL_OPERATIONS` is a fixed, import-time-pinned 8-value tuple (`configure`/`start`/`stop`/`reset`/`wait_ready`/`execute`/`monitor`/`get_status`) -- `assert_logical_operations_fixed()` runs at import and fails loudly if a future edit silently widens, narrows, reorders-with-duplicates, or otherwise drifts the vocabulary. `build_subsystem_adapter_ir(mapping_entries, subsystem_name=None)` accepts a duck-typed list of `{operation, existing_task_or_sequence_name}` records -- plain dicts or any object exposing `.get()`, never a dict subclass requirement -- and resolves each of the 8 fixed operations to exactly one `OperationResolution`:

- **RESOLVED** -- the caller supplied a real, non-empty (after whitespace-trimming) task/sequence name for this logical operation. The name is carried through verbatim, trimmed only; this module never rewrites, normalizes, or "corrects" it.
- **UNSUPPORTED_OPERATION** -- no real mapped task/sequence exists for this operation, whether because the caller's mapping never mentioned it at all, or because it was mentioned with an empty/whitespace-only name (a legitimate explicit "we have nothing for this" declaration). Both paths report the identical honest status and reason, and neither ever synthesizes a fabricated task/sequence name to fill the gap -- the module's one hard rule, restated from its own governing instruction: never invent a stub for a missing mapping.

An operation named in `mapping_entries` that falls OUTSIDE the fixed eight-operation vocabulary is never silently dropped: it is collected into `unrecognized_mappings` on the resulting `SubsystemAdapterIR`, carrying its own real reason, and it never resolves (or leaves unsupported) any of the eight real logical operations -- a caller reading the IR can always see and correct a mis-named mapping rather than have it silently vanish.

**Malformed or ambiguous input is a hard, named error, never a silent repair.** A non-sequence `mapping_entries`, an entry that is not mapping-shaped at all, an entry with a missing or blank `operation`, an entry whose `existing_task_or_sequence_name` key is entirely ABSENT (deliberately distinct from being present as an empty string, which is a legitimate "explicitly unmapped" declaration), or the same operation mapped more than once across one caller-supplied list, each raise `SubsystemAdapterIRError` with a distinct `code`/`detail` -- mirroring `task_return_model.TaskReturnModelError`'s "never silently repaired" discipline for the identical reason: silently resolving a duplicate or malformed declaration on the caller's behalf would hide a real authoring defect from the person who needs to see it. `resolve()`/`is_supported()` likewise reject a request for an operation outside the fixed vocabulary rather than reporting a fabricated `UNSUPPORTED_OPERATION` for a question this module was never asked to answer.

**Deliberately bounded, and stated rather than implied closed.** This module imports nothing else from `dv_harness` -- verified directly against its own import statements -- so it stays usable regardless of which concurrently-built module eventually owns producing a real mapping for a given subsystem; every mapping is accepted as a generic, duck-typed record rather than a specific producer's typed output. It authors no task/sequence body and validates nothing about whether a resolved name is itself syntactically or semantically correct against the underlying environment -- that is a downstream generator's job. It runs no build, no simulation, no LSF submission, mints no approval, and holds no stage gate of its own; it only resolves a caller-supplied mapping against the fixed 8-operation vocabulary and reports, honestly, what that mapping does and does not cover.

Proven by `dv_harness_tests/test_subsystem_adapter_ir.py` (20 tests): fixed-vocabulary sanity plus two mutation-style negative controls proving the import-time drift/duplicate assertion has real detection power; the full-mapping positive path (all 8 operations resolved, names trimmed-but-never-otherwise-rewritten); an empty mapping list (all 8 honestly unsupported); the never-mentioned-vs-explicitly-empty-name distinction (both `UNSUPPORTED_OPERATION`, with distinguishable `reason` text); an unrecognized operation name reported without ever bleeding into a real operation's resolution; `resolve()`/`is_supported()` rejecting an out-of-vocabulary request; six negative controls for malformed/ambiguous input; and a genuinely duck-typed (non-dict, `.get()`-only) mapping-record object proving the input contract is real duck-typing rather than dict-only support in disguise. Run: `python -m pytest dv_harness_tests/test_subsystem_adapter_ir.py -q` -> `20 passed`.


<!-- S154: moved verbatim from CLAUDE.md original lines 9325-9340 (M4.6 CLAUDE Context Normalization) -->
## System Failure Taxonomy: SYSTEM-INTEGRATION Failures, Boundary Localization, Coverage-Hole Scope (2026-09-06)

Three real, closely-related classification mechanisms, one module, because they answer questions at the SAME grain -- the SYSTEM/multi-subsystem-composition level, not the per-command-dispatch level `command_error_taxonomy.py` already owns (eleven categories, one per failed command/task call) and not the per-stage-retry level `loop_budget.FailureType` already owns (ten categories feeding a retry-vs-stop decision). Nothing in this repo classified a failure at the grain a COMPOSED multi-subsystem environment actually breaks at -- a merge collision during system build, a cross-subsystem address-map disagreement, two active VIP agents driving one port, a scoreboard mismatch that only shows up once two subsystems' transactions are compared together. `dv_harness/system_failure_taxonomy.py` is that missing coarser layer.

**(a) A 14-value SYSTEM-INTEGRATION failure taxonomy** (`SUBSYSTEM_FAILURE`, `INTEGRATION_FAILURE`, `ROUTING_FAILURE`, `RESOURCE_CONTENTION_FAILURE`, `ADDRESS_MAP_FAILURE`, `CLOCK_RESET_FAILURE`, `COMMAND_COMPATIBILITY_FAILURE`, `BUILD_COMPOSITION_FAILURE`, `SCOREBOARD_COMPOSITION_FAILURE`, `VIP_DEDUP_FAILURE`, `ERROR_PROPAGATION_FAILURE`, `TIMING_FAILURE`, `CONFIGURATION_FAILURE`, `RECOVERY_FAILURE`) plus the honest `UNCLASSIFIED` fallback. `classify_system_integration_failure(text)` is a pure, regex-rule-based classifier over whatever real failure text a caller already has (a `system_build_proof`-shaped merge report line, a cross-subsystem gate's own rejection text, a composed environment's sim.log excerpt) -- it reads no file and runs no subprocess itself, matching `command_error_taxonomy.py`'s own house style (a fixed `CLASSIFICATION_ORDER`, most structurally specific rule first, each rule citing the exact matched evidence substring and 1-indexed line). An unmatched text is `UNCLASSIFIED`, never forced into one of the fourteen named categories. `TIMING_FAILURE` classifies already-REPORTED timing/race-relationship violation TEXT (a setup/hold violation citation, a race condition, a glitch) -- it measures nothing and runs no timing analysis of its own, so it is not the Performance Verification this entire gap-closure batch deferred; it is a text classifier over evidence some other, already-real tool produced.

**Deliberately DIFFERENT, coarser scope than its two nearest neighbours, stated explicitly rather than left to be discovered.** `command_error_taxonomy.py`'s eleven categories answer "why did THIS ONE command/task dispatch fail". `loop_budget.FailureType`'s ten categories answer "why did THIS STAGE'S RETRY exhaust". This module answers "what KIND of SYSTEM/multi-subsystem-composition failure is this" -- a different, wider grain neither of those two is built to express. Because both of those modules were claimed by a concurrently-running batch of this project's own gap-closure work, this module imports neither: the non-collision is instead asserted against a literal, hand-transcribed copy of each module's own published category vocabulary (`assert_disjoint_from_command_error_taxonomy()` / `assert_disjoint_from_loop_budget_failure_type()`, both run at import time), the same "state the distinction in code, do not silently assume it" discipline several other pairs of near-adjacent vocabularies in this project already apply to themselves. A third guard, `assert_disjoint_from_verification_verdict_vocabulary()`, imports `dv_harness.models.Status` (a small, stable, unclaimed enum, safe to import) to prove this module's full vocabulary -- both taxonomies plus the boundary-localization status words -- never collides with a real stage verdict.

**(b) Root-cause BOUNDARY localization, never a claimed root cause.** `localize_failure_boundary(subsystem_io_map, connections=None)` takes a caller-supplied, fully duck-typed per-subsystem input/output correctness map (each subsystem declaring its own input and output as `CORRECT`/`INCORRECT`/`UNKNOWN`, via either a string-shaped or a bool-shaped record) and names the NARROWEST subsystem boundary the evidence actually proves -- exactly one subsystem whose input is confirmed `CORRECT` and whose output is confirmed `INCORRECT` is the only case that narrows (`status: "NARROWED"`, that subsystem named as `boundary`). Zero such subsystems, more than one, or a real contradiction across a caller-declared direct connection (an upstream `CORRECT` output paired with a downstream `INCORRECT` input on the same wire, or the reverse) all report `status: "UNDETERMINED"` with `boundary: None` and the real candidate set or contradiction cited in `reason` -- never a guessed single subsystem. This is the module's one hard rule: it never claims a specific root cause the input data does not prove, per this batch's own Evidence Truth Rule (rule 8: a Critical UNKNOWN must never silently become a resolved finding).

**(c) A 6-value system coverage-hole taxonomy** (`SUBSYSTEM_GAP`, `INTEGRATION_GAP`, `RESOURCE_GAP`, `SCENARIO_GAP`, `ERROR_PATH_GAP`, `COVERAGE_MODEL_GAP`) plus the honest `UNCLASSIFIED_COVERAGE_HOLE` fallback, via `classify_system_coverage_hole(hole)` over a caller-declared, duck-typed hole record (`coverage_model_missing`, `involves_shared_resource`, `involves_error_path`, `scope`/`subsystem_ids`/`subsystem_id`, `scenario_category_missing`). **Deliberately a different, coarser-grained taxonomy from `coverage_analysis.classify_coverage_hole()`'s four per-BIN root causes** (`MISSING_TEST`/`INSUFFICIENT_CONSTRAINT`/`UNREACHABLE_STIMULUS`/`INSUFFICIENT_SEED_ATTEMPTS`, plus this project's own twelve-value structural extension) -- that mechanism answers "why is ONE coverage bin unhit", read off a real coverage-tool summary and a real seed-attempt count; this module answers "what KIND of system-level gap does a coverage hole represent" (scoped to one subsystem, spanning an integration path, a shared-resource scenario, an error path, a whole missing scenario category, or a coverage MODEL that was never even defined). The six category names share no token with `coverage_analysis`'s vocabulary, and `coverage_analysis.py` is on this batch's claimed-file list, so it is never imported here either -- the two mechanisms compose at a caller rather than one subsuming the other.

**What this module does not do.** It classifies and localizes; it never decides which subsystem to fix, never arbitrates a resource-ownership conflict (that stays `system_resource_inventory.py`'s SYS-11/SYS-12 territory, deliberately not imported here since it is not named by this task), never retries anything, never spends a budget, never decides PASS/FAIL for a stage, and touches no human-approval gate. It performs no file I/O and no subprocess call anywhere in the module -- every input across all three mechanisms is a plain, generic/duck-typed parameter.

Proven by `dv_harness_tests/test_system_failure_taxonomy.py` (58 tests): vocabulary shape/disjointness including a mutation test proving the disjoint guards have real detection power against a real `command_error_taxonomy`/`loop_budget` category name; one positive-match test per each of the fourteen failure categories plus honest-fallback and rejection negative controls (empty text, unmatched text, `None`/non-string input) plus two priority-ordering tests proving `CLASSIFICATION_ORDER` is actually honoured when two categories' markers co-occur in one text; boundary localization's single-candidate narrowing (both string- and bool-shaped input), zero-candidate cases (with and without a blocking `UNKNOWN`), a multiple-independent-candidate `UNDETERMINED`, a real cross-connection contradiction, an unresolvable-connection-ignored-not-assumed case, and six malformed-input negative controls; and one positive test per each of the six coverage-hole categories plus two priority-conflict tests and malformed-input negative controls. Run: `python -m pytest dv_harness_tests/test_system_failure_taxonomy.py -q` -> `58 passed`.


<!-- S155: moved verbatim from CLAUDE.md original lines 9341-9400 (M4.6 CLAUDE Context Normalization) -->
## System Checker Taxonomy: a 9-Value SYSTEM-Scope Classification (2026-09-06)

Nothing in this repo named what KIND of property a SYSTEM-level (cross-subsystem/SoC-composition)
checker verifies. `verification_architecture.py`'s `CheckerIR` already extends
`connectivity.generate_protocol_check_entry()`'s per-checker shape with a target-instance/
mount-side/status/confidence record, but it answers a narrower, different-altitude question: "is
THIS ONE checker correctly bound and linked within ITS OWN subsystem" -- it has no notion of what
KIND of system-level concern the checker exists to verify, and it is deliberately scoped to a
SINGLE subsystem's own bind target. Nothing else in the codebase named a system-scope checker-type
vocabulary at all: a repo-wide grep for `DATA_FLOW_CHECKER`/`system_checker_taxonomy` before this
change matched nothing.

`dv_harness/system_checker_taxonomy.py` is that vocabulary, and it is EXPLICITLY a different,
SYSTEM-scope taxonomy from `verification_architecture.py`'s per-SUBSYSTEM `CheckerIR` -- stated in
the module's own docstring rather than left to be inferred, and enforced by never importing that
module (or any other claimed/concurrent-batch file) at all. Nine categories:
`DATA_FLOW_CHECKER`, `RESOURCE_ARBITRATION_CHECKER`, `ADDRESS_ROUTING_CHECKER`,
`CLOCK_RESET_SEQUENCING_CHECKER`, `COMMAND_COMPATIBILITY_CHECKER`, `BUILD_INTEGRITY_CHECKER`,
`SCOREBOARD_COMPOSITION_CHECKER`, `RECOVERY_CHECKER`, `ERROR_PROPAGATION_CHECKER` -- chosen to
match this project's own real SYSTEM-scope mechanisms in PROSE, without importing any of them:
`system_resource_inventory.py`'s ACTIVE_DRIVER_CONFLICT detection is a real
RESOURCE_ARBITRATION_CHECKER concern, `system_build_proof.py`'s `analyze_system_merge()`
duplicate-package/type/factory-collision checks are a real BUILD_INTEGRITY_CHECKER concern, and
`system_topology_analysis.py`'s address-region facts are a real ADDRESS_ROUTING_CHECKER concern --
this module never re-derives or duplicates any of that logic; it only names the KIND of checker a
caller's description describes.

**Classification-only, over a duck-typed description, evidence-based rather than guessed.**
`classify_system_checker(description)` accepts a bare string, a dict, or any object exposing
`checker_name`/`description`/`verifies`/`notes`/`text` fields and/or an explicit
`declared_checker_type`. An explicit declaration -- validated against the nine-value vocabulary,
with an unrecognized value raising `SystemCheckerTaxonomyError` rather than silently falling back
to keyword inference -- always wins. Absent one, classification falls back to a real, cited
KEYWORD match over the description's own free text, checked in a fixed, documented
`CLASSIFICATION_ORDER` (most structurally distinctive vocabulary first -- BUILD_INTEGRITY_CHECKER
and RESOURCE_ARBITRATION_CHECKER's terms are least likely to appear incidentally; DATA_FLOW_CHECKER's
broader vocabulary is checked last). A description matching nothing is honestly
`UNCLASSIFIED_SYSTEM_CHECKER` with no matched evidence -- never forced into one of the nine on a
weak guess. `RECOVERY_CHECKER` (`recover*`) and `ERROR_PROPAGATION_CHECKER` (`propagat*`) are kept
on deliberately disjoint keyword roots so a description naming both is resolved by
`CLASSIFICATION_ORDER`, never by accident. `assert_disjoint_from_verification_verdict_vocabulary()`
holds the nine-value vocabulary (plus `UNCLASSIFIED_SYSTEM_CHECKER`) disjoint from
`dv_harness.models.Status` at call time, the same guard several sibling taxonomy modules
(`command_error_taxonomy.py`) already apply to their own vocabularies.

**Deliberately bounded.** It classifies a caller-supplied description only -- it reads no file,
parses no RTL/UVM source, and runs no build/gate/approval; there is deliberately no stage gate. No
`dv-harness` CLI verb was added (`cli.py`/`gates.py` were out of this task's file-safety scope) --
the front door is `python -m dv_harness.system_checker_taxonomy {types|classify}`.

Proven by `dv_harness_tests/test_system_checker_taxonomy.py` (33 tests): the positive path for all
nine categories via keyword inference and via explicit declaration (including a declaration
overriding conflicting keyword text, and a `verifies` field accepting a list of phrases); negative
controls for an unclassifiable description, empty/whitespace-only input, an unrecognized/malformed
declared value (each raising rather than silently coercing), an unrelated dict with no recognized
fields, and a dedicated proof that RECOVERY_CHECKER and ERROR_PROPAGATION_CHECKER never
cross-classify on overlapping error-handling prose; the `CLASSIFICATION_ORDER`/
`SYSTEM_CHECKER_TYPES` totality assertion and the `models.Status` disjointness guard; and both the
in-process `execute_verb()` (all three exit codes) and a real `python -m` subprocess invocation.


<!-- S156: moved verbatim from CLAUDE.md original lines 9401-9416 (M4.6 CLAUDE Context Normalization) -->
### pattern_fragment_ir.py -- reusable pattern-fragment extraction for later system-level composition

`dv_harness/pattern_fragment_ir.py` converts a reusable PORTION of an existing subsystem pattern -- never a whole scenario -- into a `PatternFragmentIR`: a small, composable record carrying `preconditions`, `postconditions`, `resources_used`, and `produced_events`/`consumed_events`, so a later system-level composition step has something concrete to reason about instead of re-reading raw pattern text.

**Explicitly distinct from two real, easy-to-confuse modules.** `pattern_ir_assembly.py` assembles the FULL `PatternIR` for ONE scenario -- its `global`/`dut`/`fw_policy`/`vip`/`check` five-layer command lists, built from a whole ScenarioIR-shaped item list; it answers "what does this entire scenario's pattern look like, laid out into its five fixed layers". `example_composition.py` composes multiple already-qualified WHOLE VIP EXAMPLES (a host example plus a device example, say) into one scenario, gated by a 7-condition example-level compatibility check (VIP version, role, protocol mode, agent config, sequencer ownership, reset/clock assumptions). `pattern_fragment_ir.py` answers a narrower, different question than either: given ONE existing pattern's command list and a caller-declared PORTION of it -- an index range, or a marker-delimited slice, never the whole thing by default -- extract that portion as a self-describing fragment carrying what resources it touches, what events it needs already asserted before it runs, and what it leaves behind. It never assembles a scenario's five PatternIR layers and never checks VIP-example-level compatibility. Per this batch's file-safety scope it imports nothing from `pattern_ir_assembly.py`, `example_composition.py`, or any other claimed batch file; `fragment_source` is accepted as a plain duck-typed object via a locally re-derived tolerant-alias field-access helper, not an imported one.

**Selection.** `extract_pattern_fragment(fragment_source, *, fragment_range=None, start_marker=None, end_marker=None, declared_preconditions=None, declared_postconditions=None, fragment_id=None)` resolves the fragment's command slice one of three ways: an explicit `(start, end)` half-open index pair (`SELECTION_EXPLICIT_RANGE`), a `start_marker`/`end_marker` inclusive text-matched pair (`SELECTION_MARKER_RANGE`), or, when neither is supplied, the entire source command list -- honestly flagged `SELECTION_WHOLE_SOURCE_USED_NO_RANGE_DECLARED` with `covers_entire_source=True` rather than silently pretending a portion was declared. An unrecognisable `fragment_source` (no list-shaped commands field under any known alias), an invalid or out-of-range `fragment_range`, an incomplete marker pair, or a marker that is never found each raise a typed `PatternFragmentIrError` carrying a specific reason code (`SOURCE_COMMANDS_NOT_LIST`, `INVALID_FRAGMENT_RANGE`, `MARKER_PAIR_INCOMPLETE`, `START_MARKER_NOT_FOUND`, `END_MARKER_NOT_FOUND`, `EMPTY_FRAGMENT_SELECTION`) -- never a silent fallback to selecting nothing or everything.

**Precondition/postcondition derivation (Evidence Truth Rule applied).** Every fact reported is read directly off the fragment's own command entries via aliased duck-typed fields (`resource`/`resources`/`uses_resource`/`driver`/`agent`; `produces_event`/`produced_event`/`emits_event`/`emits`/`produces`; `consumes_event`/`required_event`/`requires_event`/`waits_for_event`/`consumes`). Given the fragment's own produced-event and consumed-event sets, a consumed event NOT also produced within the same fragment becomes a derived precondition (`DERIVED_UNRESOLVED_CONSUMED_EVENT`) -- something the fragment assumes true on entry that it alone cannot supply; a produced event NOT also consumed within the same fragment becomes a derived postcondition (`DERIVED_UNCONSUMED_PRODUCED_EVENT`) -- something it leaves behind for whatever composes with it later. This is a plain set-difference over the fragment's own declared events, assuming no internal ordering guarantee beyond "declared inside this fragment" (consistent with a fragment being reusable, not a fully sequenced scenario) -- it never invents an event no command actually declared. Callers may additionally pass `declared_preconditions`/`declared_postconditions` (plain strings or small dicts) for facts a human or upstream tool already knows are true but no event field mechanically proves; these are kept tagged `DECLARED`, distinct from and never deduplicated against the `DERIVED_*` entries, since a declared fact and a mechanically-derived one naming the same event remain two different pieces of evidence.

**Absence-of-evidence is a distinct, honest status, never a silently-defaulted empty result.** `resource_evidence_status` and `event_evidence_status` are each `EVIDENCE_DERIVED` when at least one command in the fragment declared that kind of field, or `EVIDENCE_NOT_AVAILABLE` when none did -- kept separate from a legitimately-computed empty `resources_used`/`produced_events`/`consumed_events` list, so "nothing was declared" and "something was declared and none of it applies here" are never collapsed into one indistinguishable outcome. A command with no `text` field at all is collected into `unclassified_commands` and downgrades the fragment's overall `status` from `COMPLETE` to `PARTIAL_TEXT_EVIDENCE`, never silently dropped.

**Composition-facing structural chain check.** `check_fragment_chain_readiness(fragments, *, order=None)` takes an ordered list of `PatternFragmentIR`-shaped fragments -- a caller's declared composition order for a candidate system-level pattern -- and reports, per fragment, whether each of its `DERIVED_UNRESOLVED_CONSUMED_EVENT` preconditions is `COVERED` (an earlier fragment in that order produced or postconditioned the same event) or `UNCOVERED`, plus a per-fragment `chain_status` of `NO_PRECONDITIONS` / `ALL_COVERED` / `HAS_UNCOVERED_PRECONDITIONS`. An explicit `order` argument naming a different set of fragment ids than `fragments` actually holds raises `PatternFragmentIrError("ORDER_MISMATCH", ...)` rather than silently reordering or dropping a fragment; an empty `fragments` list raises `PatternFragmentIrError("EMPTY_FRAGMENT_LIST", ...)`. This is a purely structural event-graph check over caller-declared event names -- it never asserts, and must never be read as asserting, that the resulting composed multi-fragment pattern is behaviourally correct; it only reports whether the produced/consumed event graph is self-consistent in the declared order, reporting `UNCOVERED` rather than guessing a precondition is satisfied when no earlier fragment actually supplies it.

**Tests.** `dv_harness_tests/test_pattern_fragment_ir.py` (16 tests, all passing): the core positive path (explicit-range extraction with correctly derived resources/events/preconditions/postconditions off a real 4-command USB3 port-enumeration-shaped pattern fixture), declared-condition merging alongside derived ones, marker-based selection producing the same result as the equivalent explicit range, the whole-source-used honest flag, the NOT_AVAILABLE-vs-computed-empty distinction for a fragment with resources but no event fields, the unclassified-command status downgrade, six negative controls (non-list commands field, start>=end range, out-of-bounds range, incomplete marker pair, start marker not found, end marker not found) each asserting the specific `PatternFragmentIrError` reason code, and four `check_fragment_chain_readiness` tests (all-covered in correct declared order, uncovered when the producing fragment is omitted, empty-fragment-list error, order-mismatch error).


<!-- S157: moved verbatim from CLAUDE.md original lines 9417-9483 (M4.6 CLAUDE Context Normalization) -->
## SYOSCB-2/33 Phase-2 Vendoring: Human-Approved, Enforced Rather Than Promised (2026-09-06)

SYOSCB-1/3's earlier gap-close pass (see `.work/gap-close-syoscb-syoscb-1-3-real-read-only-syosil-source--report.md`)
built a real, read-only auditor for the upstream `uvm_syoscb-1.0.2.4` tree and deliberately left the
Phase-2 vendoring decision open, gated behind SYOSCB-33 human review, with `assert_not_vendored()`
enforcing (not merely documenting) that no upstream file existed in this repository until that gate
opened. The project owner explicitly approved that gate in-session on 2026-09-06: vendor the real
upstream tree at `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4` into this repository as read-only reference
material, the same convention already used for `reference/USB_UVM_Handoff`.

**What was done.** The upstream tree (234 files: `src/`, `tb/`, `docs/`, `LICENSE.txt`, `NOTICE.txt`,
`VERSION.txt`, `RELEASE_NOTES.txt`, the three vendor Makefiles) was copied VERBATIM into
`reference/uvm_syoscb-1.0.2.4/` -- byte-for-byte, nothing edited, nothing renamed. Re-running the real
`syoscb_source_audit.py` auditor against the new in-repo copy reproduces the identical facts the
original upstream audit found (version `1.0.2.4`, license `Apache-2.0`, copyright `SyoSil ApS`), which is
itself a real integrity check: an edited or truncated copy would have audited differently.

**The Phase-2 gate is now a real, on-disk approval record, not a verbal go-ahead.**
`dv_harness/syoscb_vendoring_approval.json` carries `approved: true`, `l5_destination:
"reference/uvm_syoscb-1.0.2.4"`, who approved it, when, and the real upstream source path -- a
structured fact `assert_not_vendored()` can read, not prose a future reader has to trust.
`load_vendoring_approval()` reads it (returning `None` on a genuinely absent file, and raising on a
present-but-malformed one -- a broken approval record must never be read as "no approval", which would
make the check MORE permissive on a parse failure than on a missing file).

**`assert_not_vendored()` gained a narrow, structural exemption -- not a bypass.** It now accepts an
optional `approval` record; a name/content hit is EXEMPT only when it resolves under that record's own
`l5_destination` AND the record's `approved` field is truthy -- every hit outside that exact destination,
or any hit at all when `approved` is false (a draft/revoked record), still raises exactly as before. Every
approved hit is additionally reported back under `approved_vendored` in the result -- never silently
absorbed into a bare CLEAN, so a reader can always see WHAT was approved, not just that a check passed.
Passing no `approval` argument (every pre-existing caller) preserves the original all-or-nothing behavior
byte-for-byte. The CLI's `--assert-not-vendored` now auto-loads the real approval record for the target
root before checking, so `python -m dv_harness.syoscb_source_audit ... --assert-not-vendored <root>`
keeps meaning something once a project has vendored an approved component, rather than becoming
permanently unusable the moment Phase 2 actually happens.

**No other file in this repository was touched.** `dv_harness/knowledge_center.py`'s
`THIRD_PARTY_COMPONENT_*` shape (built in the SYOSCB-1/3 pass) is unchanged; a registration PAYLOAD can
now be built with the real `L5_DESTINATION` filled in (`--l5-destination reference/uvm_syoscb-1.0.2.4`,
confirmed to no longer report an `L5_DESTINATION` blocker) but was deliberately NOT published to the
remote Knowledge Center this session -- that is a REMOTE_EXECUTION act requiring the SSH/Remote Transport
Connection Intake gate, out of scope for a LOCAL_ANALYSIS vendoring pass. `BUILD_STATUS` correctly stays
`NOT_BUILT_PHASE_2_APPROVAL_REQUIRED`: vendoring is not compiling, and nobody has run a VCS/UVM build
against this copy yet.

Proven by `dv_harness_tests/test_syoscb_source_audit.py` (47 tests, up from 43): the pre-existing test
that asserted the live repository carried NO upstream copy was replaced with one asserting the ONLY
copy present is the real, approved one, reported (not hidden) under `approved_vendored`; a new test
proves a SECOND, unapproved copy placed anywhere else in the same repository is still caught by name;
`load_vendoring_approval()` is proven to return `None` on a genuinely absent record and to raise on a
malformed one; and an approval record whose own `approved` field is `false` is proven to exempt nothing.
The full pre-existing suite (43 tests) plus the related `test_knowledge_center.py`,
`test_amba_port_registry.py`, `test_amba_fabric_discovery.py`, `test_amba_fabric_generator.py`,
`test_knowledge_layer_git_and_duckdb.py`, and `test_amba_vip_bind_plan.py` (196 tests combined) were
re-run in full and pass unchanged.

**Disclosed residual, stated rather than implied closed.** (1) This closes SYOSCB-2's vendoring decision
and SYOSCB-33's approval-enforcement mechanism only. SYOSCB-4 (evaluating whether to fork the upstream
library) remains `NOT_AVAILABLE` -- no fork exists, and none was created here. (2) The vendored copy is
reference material under the same "No Golden-Reference Content Mining" discipline as
`reference/USB_UVM_Handoff` -- it may be used to check structural/organizational conformance or as a
real compare-engine dependency once a generator actually integrates it, never mined for protocol-behavior
content to paste into generated output. (3) Knowledge Center publication (`record_component()`) was not
performed -- the payload can be built locally at any time; publishing it is a separate, explicitly
REMOTE_EXECUTION act for a future session that has established that connection.


<!-- S158: moved verbatim from CLAUDE.md original lines 9484-9542 (M4.6 CLAUDE Context Normalization) -->
## ATB (AutoTestBench) Golden AMBA Reference: Human-Approved Vendoring (2026-09-06)

A real, previously-unlabeled reference tree at `D:/DV/Task/DV_Agent_Harness_L5/L3` -- `coretop/` and
`soc/`, the latter including a real SyoSil-based scoreboard under `soc/uvc/scb/` -- was renamed to `ATB`
(AutoTestBench) by explicit user instruction, then explicitly approved by the project owner for Phase-2
vendoring into this repository as read-only reference material, the same SYOSCB-2/33 approval pattern
this session already established and enforced in code for the pristine upstream SyoSil release (see the
section above).

**What was done.** The real ATB tree (145 files, 1.6MB) was copied VERBATIM into `reference/ATB/` --
`diff -rq` against the original confirmed byte-for-byte identical content, 145/145 files, with no
edits. `dv_harness/atb_vendoring_approval.json` records the real approval (who, when, source path,
destination path, and the rename history from `L3` to `ATB`) in the same structured shape
`dv_harness/syoscb_vendoring_approval.json` already established for the SyoSil vendoring decision -- a
fact a caller can read, not prose to be trusted.

**Purpose, stated explicitly so it is never misread as license to mine it.** ATB is a golden,
already-integrated AMBA M x N SoC bus reference architecture -- it exists to ground and validate this
harness's own AMBA generation and analysis capability against a real, working example (structural/
organizational conformance checking, and as a real dependency once a generator actually integrates its
scoreboard), the same "No Golden-Reference Content Mining" discipline already applied to
`reference/USB_UVM_Handoff`: never a source to copy protocol-behavior content FROM for a different
project's generated output.

**Relationship to the separately-vendored pristine SyoSil release, stated explicitly since they could be
confused.** `reference/uvm_syoscb-1.0.2.4/` (vendored earlier this session) is the clean upstream SyoSil
library release on its own. `reference/ATB/soc/uvc/scb/` is a DIFFERENT artifact -- a real, already
-integrated golden testbench environment that happens to USE a SyoSil-based scoreboard -- and the two
trees are not expected to be byte-identical (ATB's copy may be an older revision, or may carry
project-specific configuration around it). Any module reading ATB for its own SyoSil-adjacent content
should say which of the two trees it is reading from, never conflate them.

**Disclosed residual**: like the SyoSil vendoring, this is REACHED, not automated -- there is no code
path that auto-detects and vendors a reference tree on its own; a human decision preceded both. Whether
ATB's own third-party components (the vendored SyoSil scoreboard inside it) carry their own separate
license/notice obligations beyond what the pristine `uvm_syoscb-1.0.2.4` release already discloses was
not independently re-audited in this pass -- `dv_harness/atb_reference_inventory.py` (built the same
session, see its own section) is the read-only audit layer for this tree going forward.

**ATB is exempt from this project's general "no live simulator" performance disclaimer -- a distinction
recorded here explicitly, per the project owner's own clarification, so a future session does not have
to rediscover it.** Every Performance-domain module built this session (`amba_performance_calculator.py`,
`amba_performance_requirement_checker.py`, `amba_performance_classification.py`,
`amba_performance_readiness_gates.py`) is bounded by the fact that THIS HARNESS, in general, owns no live
simulator or formal tool -- every number those modules touch must be CALLER-supplied, never measured by
the harness itself. ATB is different: it is a real, already-integrated, working AMBA M x N testbench
environment -- once a future session actually builds and runs ATB (a real VCS/UVM invocation, its own
Execution Mode declaration and, if remote, its own SSH/Remote Transport Connection Intake gate, exactly
like any other REMOTE_EXECUTION work in this project), the resulting `fsdb_report.py`-derived timing/
latency/bandwidth numbers ARE real, measured ground truth for that environment -- not a caller-declared
assumption a Performance-domain module has to treat with the same suspicion it applies to a project with
no live testbench at all. A future ATB-integration module may therefore be designed to EXPECT a real
measured performance artifact to exist once ATB has actually been run, rather than defaulting to
NOT_AVAILABLE the way this session's generic Performance modules must. This does not relax the Evidence
Truth Rule -- it still applies in full: the numbers must still come from a REAL fsdbreport/simulation
artifact ATB actually produced, never estimated or invented on ATB's behalf either. Nothing in this
session ran or built ATB; this paragraph only removes a false generalization for whichever future session
does.


<!-- S159: moved verbatim from CLAUDE.md original lines 9543-9668 (M4.6 CLAUDE Context Normalization) -->
## ATB Reference Inventory: Capability Discovery + the Reuse-Then-Block Rule (2026-09-06)

`syoscb_source_audit.py` already answers "what does this one third-party library
contain" for the real upstream `uvm_syoscb` tree. Nothing answered the question one
level up, over the real ATB (AutoTestBench, formerly named "L3", renamed this
session) reference tree at `D:/DV/Task/DV_Agent_Harness_L5/ATB`: what capabilities
does a whole reference ENVIRONMENT contain, which of them are actually wired into it,
which are present but never plugged in, which have drifted from what this project
already vendored elsewhere, and -- for any capability a caller genuinely needs --
whether it can be reused from here, reused from an already-approved vendored copy, or
must be reported BLOCKED because neither exists. `dv_harness/atb_reference_inventory.py`
is that inventory, entirely read-only, and the root it audits is always a caller
parameter, never hardcoded, so a future caller may point it at a different reference
tree.

**Reuse, not reinvention, on every structural layer.** Classes come from
`vip_symbol_index.index_source_text()`, exactly as `syoscb_source_audit.py` already
uses it -- declarations and `file:line` only, `assert_no_bodies_retained()` run over
the result. Module-shaped constructs (a bind connector module, a DUT-wrapper or
testbench-top module) come from `verible_parser.parse_file()`, best-effort: a machine
with no real `verible-verilog-syntax` on PATH degrades this one layer to an honest
`module_discovery_status: "NOT_AVAILABLE"` with a real reason -- never a silent zero
read as "none exist" -- while class and interface discovery are unaffected either way.
`amba_scoreboard_env.InspectedFile` is the same read-only-proof record
`syoscb_source_audit.py` already reuses, so "which files did we read, and were they
unchanged afterward" (`assert_source_unmodified()`) has one shape in this repo rather
than two. The one construct neither reused tool indexes -- a top-level `interface`
declaration, which is how every real ATB bind interface is actually shaped -- gets a
small, local, declaration-line-only regex scan mirroring the identical discipline
(name + location, never a signal list or a body).

**The status vocabulary is derived from real, checkable evidence, never guessed.**
`PROVEN` / `IMPLEMENTED_UNPROVEN` / `PARTIAL` / `PRESENT_UNUSED` / `DUPLICATE` /
`STALE` / `MISSING` / `BLOCKED` / `UNKNOWN`. `DUPLICATE` fires only on a genuine
same-NAME collision within one SUBSYSTEM (`coretop` vs `soc`) -- the two reference
environments' own, by-design duplicate copies of one bind interface across
subsystems are never flagged. `IMPLEMENTED_UNPROVEN` requires a real reference from a
file OUTSIDE the capability's own kind-directory (`scb/`, `cb/`, `seq/`, `bind/`) in
the same subsystem -- either by symbol name or by its own declaring filename being
`` `include ``d, since a real ATB bind interface is wired in by filename, not by the
interface's own bare symbol. `PRESENT_UNUSED` is everything else that was found.
`UNKNOWN` is reserved for a genuine cross-tool disagreement -- a name verible reports
as a `module` that the class/interface scan ALSO reports as a class or interface
elsewhere in the tree -- never resolved by picking one. `PROVEN` is never
self-assigned by discovery: `apply_proof_evidence()` is the ONLY path to it, and it
requires a real, non-empty, caller-declared citation naming the exact capability
(and refuses to promote a `DUPLICATE` on the strength of one, since the ambiguity
must be resolved first). `PARTIAL`/`MISSING` come from `evaluate_expected_capabilities()`
against a caller-DECLARED expectation list -- this module invents no universal
family list of its own.

**The literal reuse-then-block rule, as code.** `resolve_capability_reuse(name,
manifest, approval_records, project_root)`: (1) if ATB already has the named
capability, prefer reusing IT -- `REUSE_LOCAL_ATB_CAPABILITY`, citing ATB's own
`file:line`; (2) else, if a real, already-APPROVED
`dv_harness/*vendoring_approval*.json`-shaped record's own `l5_destination` tree
(structurally scanned the same declaration-only way) contains the capability, reuse
THAT -- `REUSE_VENDORED_REFERENCE_COPY`, citing the approving record and the real
vendored `file:line`; (3) else `BLOCKED_NOTHING_TO_REUSE`, naming every location this
function actually checked and found nothing at. There is no fourth branch that
proceeds with nothing. `find_project_vendoring_approval_records()` reads --
generically, by glob, never one hardcoded filename -- every such record on disk and
fails closed (raises, never silently skips) on one that is malformed, mirroring
`syoscb_source_audit.load_vendoring_approval()`'s own reasoning (re-derived locally,
never imported, since that module is on this batch's claimed-file list).
`evaluate_drift_against_vendored()` compares a known-family capability's real content
against this project's own already-approved vendored copy of that SAME family
(gated by a `component_hint`, so a record whose destination happens to be a
wholesale mirror of ATB itself can never trivially "match itself" and hide a real
drift finding against the true upstream) -- `STALE` when they genuinely differ,
naming both real files and both real sha256 digests, and explicitly never claiming
which side is newer; that stays a human decision.

**Real findings, over the real tree, used directly by this module's own tests**
(guarded `@real_source`-style so the suite still passes on a machine without ATB):
every SyoSil scoreboard capability under `ATB/soc/uvc/scb/` is genuinely
`PRESENT_UNUSED` -- internally self-consistent, but referenced by nothing anywhere
else in the real `soc` environment, independently confirmed by grep before the
assertion was written; ATB's own bind interfaces genuinely ARE wired in (a real
`` `include `` from `soc/bench/uvm_soc_tb.sv`) and read `IMPLEMENTED_UNPROVEN`;
`ATB/soc/uvc/scb/cl_syoscb_queue_std.svh` genuinely differs in content (a different
copyright year, a different base class) from this project's own already-approved
`reference/uvm_syoscb-1.0.2.4/src/cl_syoscb_queue_std.svh`, a real `STALE` finding
with no fixture involved; `cl_syoscb_report_catcher.svh` exists ONLY in the vendored
reference copy and not in ATB itself, a real `REUSE_VENDORED_REFERENCE_COPY`
resolution.

**A stale assumption in this module's own governing task, corrected by current
evidence rather than by trusting the prompt** (the Evidence Truth Rule applied to
this module's own build, not only to what it audits): mid-task, `dv_harness/
atb_vendoring_approval.json` and a full verbatim mirror at `reference/ATB` were found
to ALREADY exist on disk -- created by a different, concurrently-running agent in
this same multi-agent session, not by this module. Because
`find_project_vendoring_approval_records()` discovers every vendoring-approval-shaped
record by a generic glob rather than one hardcoded filename, it picked this real
record up automatically with no code change, and `atb_vendoring_approval_status()`
reports it honestly (`approved: true`, citing that real file) rather than asserting
the now-superseded "no approval exists". This module created neither artifact and
copies nothing from ATB itself, ever -- both are read, never written, and the two
real-evidence tests that depend on that specific record's presence carry a second,
independent `skipif` guard on it so the suite still passes in a checkout where it is
absent.

**Deliberately bounded, and stated rather than implied closed.** (1) It DECIDES
nothing beyond reporting: no file is copied, no build/job/approval is touched, and
there is no stage gate. (2) `PROVEN` requires a real caller-declared citation this
module cannot manufacture on its own -- ATB has no evidence store of its own wired to
it, and this module builds none. (3) Module-level (RTL-shaped) discovery is
best-effort and needs a real `verible-verilog-syntax` on PATH; its absence narrows
what can be classified, never what silently reads as "found". (4) Duplicate
detection, family drift, and the reuse-then-block rule all operate on DECLARATION-
LEVEL structural facts only -- none of it proves behavioral correctness, and none of
it decides which of two diverging copies is authoritative. (5) No `dv-harness` CLI
verb was added and `gates.py`/`cli.py`/`CLAUDE.md` were not touched, per this batch's
explicit file-safety scope; the front door is the module's own Python API,
`discover_atb_capabilities()`/`resolve_capability_reuse()`/`atb_vendoring_approval_status()`.

Proven by `dv_harness_tests/test_atb_reference_inventory.py` (46 tests): a synthetic,
ATB-shaped fixture drives every classification rule (duplicate, cross-subsystem
non-duplicate, kind-directory-scoped wiring, cross-tool ambiguity, drift, the three
reuse-then-block branches, malformed-approval-record refusals) one defect at a time,
and a family of `@real_source`-guarded tests runs the identical logic over the real
ATB tree and the real, already-approved `reference/uvm_syoscb-1.0.2.4` copy, proving
the module's real findings rather than only a fixture shaped to please it. `python -m
pytest dv_harness_tests/test_atb_reference_inventory.py -q` -> `46 passed`.


<!-- S160: moved verbatim from CLAUDE.md original lines 9669-9752 (M4.6 CLAUDE Context Normalization) -->
## AMBA Master/Slave Constraint IR: Three Layers, Never Merged (2026-09-06)

A test scenario's "what may I legally send on this AMBA interface" question conflates three genuinely
different facts whenever it is answered as one number: what the AMBA-4 protocol spec allows in
general, what THIS DUT actually implements, and what a specific scenario may therefore legally send.
Nothing in this repo modeled the middle fact at all, and nothing kept the three separate.
`amba_transaction_ir.py` already answers "is burst_type/burst_len/burst_size APPLICABLE for this
protocol" from `connectivity.py`'s real signal witness sets, but it stops at applicability -- it
carries no LEGAL VALUE for an applicable field (what burst lengths AXI4 actually permits, what
outstanding-transaction/ordering/security legality a protocol carries), and it has no DUT-capability
concept at all: every AMBA IR in this repo up to now was protocol-general or per-registry-row, never
"what did we actually confirm THIS DUT implements".

`dv_harness/amba_master_slave_constraint_ir.py` is three deliberately separate IRs over six
dimensions (burst_type, burst_len, burst_size, outstanding, ordering, security):

- **ProtocolLegalConstraintIR** -- general AMBA-4 legality, never DUT-specific. Applicability for the
  three burst-shaped dimensions is READ, not re-derived, from `amba_transaction_ir.
  ir_field_applicability()`/`protocol_signal_vocabulary()` -- there is no second witness table for
  those three facts. `outstanding`/`ordering`/`security` are dimensions no prior IR modeled; `security`
  gets its own new witness set (`SECURITY_WITNESS_SIGNALS = {AWPROT, ARPROT, PPROT}`, checked against
  `connectivity.ALL_AMBA_SIGNAL_NAMES` at import the same way `amba_transaction_ir._assert_witness_
  tokens_known()` checks its own) -- deliberately excluding AHB's HPROT, since the classic AMBA AHB
  spec defines it as privileged/bufferable/cacheable access, not a secure/non-secure bit (that arrived
  only with AHB5, untracked here). Legal VALUES (AXI4 INCR up to 256 beats, FIXED/WRAP capped at 16;
  AXI3 every burst type capped at 16; AHB's HBURST-encoded discrete lengths; a single-outstanding hard
  cap for AHB/APB; per-ID-ordered/cross-ID-unordered-permitted for AXI) are cited to the real, public
  AMBA AXI/AHB/APB protocol specifications -- external published facts, not a project-specific
  fabrication.
- **DUTCapabilityConstraintIR** -- what THIS DUT actually implements, from real RTL/spec evidence
  only. **The one hard rule this module exists to enforce**: "never infer a DUT capability from VIP
  capability alone -- a VIP manual proves what the VIP CAN drive, never what the DUT actually
  implements." `assert_no_vip_sourced_dut_capability()` runs on every DUT evidence item before
  anything is built and RAISES, loudly, the moment any item's `source_kind` names a VIP origin -- there
  is no downgrade path; a VIP-sourced "confirmation" is not a weaker confirmation, it is refused
  outright. Only a fixed allowlist of real evidence kinds (`rtl_port`/`rtl_parameter`/`rtl_register`/
  `register_map`/`spec_document`/`programming_guide`/`human_confirmation`/`register_rtl_trace`) counts
  toward `DUT_CAPABILITY_CONFIRMED`; an unrecognized source, or no evidence at all, leaves the field
  `DUT_CAPABILITY_UNKNOWN` -- never defaulted to the protocol's general maximum. Two real citations for
  one field that disagree report `DUT_CAPABILITY_AMBIGUOUS_CONFLICTING_EVIDENCE` rather than being
  silently resolved by picking one. `verible_parser.py`/`spec_doc_map.py` are not imported (the latter
  is claimed by a concurrent batch); a `spec_doc_map.py`-shaped structural index is accepted as a
  generic `spec_structural_index` parameter used ONLY to enrich a citation's page number with its
  detected register-chapter range, never to invent a capability value.
- **ScenarioConstraintIR** -- what a scenario may legally send, derived from the first two. A field
  the protocol layer rules NOT_APPLICABLE passes through untouched, the DUT layer never even
  consulted. A field the protocol permits but the DUT layer never confirmed is
  `REQUIRES_HUMAN_CONFIRMATION` -- never silently assumed to match the protocol's general legality,
  the field-level enforcement of this module's one hard rule. A DUT-confirmed field is narrowed
  against protocol legality; a DUT claim that falls OUTSIDE what the protocol allows (a claimed
  300-beat AXI4 INCR burst against the protocol's own 256-beat ceiling, more than one outstanding
  transaction claimed on AHB, an ordering claim looser than the protocol requires, a non-power-of-two
  transfer size) is `DUT_CAPABILITY_CONTRADICTS_PROTOCOL_LEGALITY` -- reported as a real finding, never
  silently narrowed to whatever happens to fit.

**The three layers are never merged into one flat record, enforced rather than merely documented.**
`build_amba_master_slave_constraint_model()` returns exactly `{"protocol_legal", "dut_capability",
"scenario_constraint"}`, and `assert_layers_structurally_separate()` is a real structural guard: it
raises `CONSTRAINT_MODEL_FLATTENED` the moment a dimension name (`burst_type`, `outstanding`, ...)
appears on the model's own top level, and `CONSTRAINT_MODEL_NOT_THREE_LAYERS` if the model's keys are
not exactly the three layer names.

**Deliberately bounded, and stated rather than implied closed.** (1) It builds a constraint MODEL a
human/generator reads; it runs no build, no simulation, and there is deliberately no stage gate. (2)
`ace_lite_coherency` (AWSNOOP/ARSNOOP/AWDOMAIN/ARDOMAIN/AWBAR/ARBAR) and AXI4-Stream's TID/TDEST
interleave-depth legality are explicitly NOT modeled (`unmodeled_notes`), the same disclosed-gap
convention `protocol_capability.py`'s `does_not_model` already uses. (3) Combining a DUT-confirmed
value against protocol legality is a real, typed comparison per dimension shape (burst-type-set
intersection, per-burst-type range narrowing, power-of-two validation, an ordering-strictness table
letting a DUT be stricter but never looser than a protocol requires) -- there is no generic "is this
smaller" fallback that could silently accept an incompatible shape.

Proven by `dv_harness_tests/test_amba_master_slave_constraint_ir.py` (26 tests): the positive path for
all three layers and the full model; the critical VIP-evidence-forbidden rule (via both the builder
and the assert function directly); an unconfirmed DUT capability never assumed; a DUT claim exceeding
protocol legal maximum flagged as contradiction (burst length, outstanding count, ordering, and
non-power-of-two size each get their own negative control); conflicting evidence citations reported
ambiguous rather than resolved; an unresolved protocol reporting UNKNOWN on every dimension;
unknown-dimension evidence and mismatched-protocol layers each raising; and the structural-separation
guard catching both a flattened model and a model missing a layer. Only `dv_harness.amba_transaction_ir`
and `dv_harness.connectivity` (both pre-existing, non-claimed) are imported -- no claimed-batch file or
other new-this-batch module. `python -m pytest dv_harness_tests/test_amba_master_slave_constraint_ir.py
-q` -> 26 passed.


<!-- S162: moved verbatim from CLAUDE.md original lines 9769-9857 (M4.6 CLAUDE Context Normalization) -->
## Arbitration Policy IR: Scheme Classification + Starvation-Risk Detection (2026-09-06)

The Engineering Discipline Rules already state a hard project rule ("Concurrent bus arbitration":
APB/AXI transactions across `block`/`branch_a*`/other branches sharing a resource "must have an
explicit, RTL-evidence-based arbitration policy modeled"), but nothing in this repo ever classified
WHAT that policy actually is, or asked whether it can starve a requester. A repo-wide grep
(`FIXED_PRIORITY`/`ROUND_ROBIN`/`WEIGHTED_ROUND_ROBIN`/`AGE_BASED`/`QOS_BASED`/`arbitration_scheme`/
`ArbitrationPolicy`) returned zero hits before this module. The real AMBA/SyoSil family
(`amba_fabric_discovery.py`, `amba_port_registry.py`, `amba_fabric_analysis.py`,
`amba_transaction_ir.py`, `amba_route_transform_predictor.py`, `amba_scoreboard_env.py`) discovers
fabric topology, ports, transactions and route transforms -- none of them names or classifies an
arbitration SCHEME, and `shared_bus_resource_registry.py` (built earlier in this same batch)
detects a concurrency RACE between two task groups over a shared lock without asking what the
underlying arbiter's own real policy is. `dv_harness/arbitration_policy_ir.py` fills exactly that
one narrow gap and nothing else.

**The Evidence Truth Rule, applied literally: a scheme is classified ONLY from real evidence TEXT
the caller supplies (an RTL comment, an arbiter module's header, a spec/programming-guide paragraph)
-- never from a component/instance/module NAME alone.** `component_name`/`fabric_name` are accepted
purely as LABELS for the result; `classify_arbitration_scheme()` never reads either when deciding a
scheme, proven directly by a dedicated negative-control test (a component literally named
`round_robin_arbiter_inst` whose supplied evidence text describes FIXED_PRIORITY arbitration
classifies FIXED_PRIORITY, not the name-implied scheme; the same component with NO evidence text at
all stays honestly `NOT_AVAILABLE`, never defaulted from the name). Absent evidence text, or
evidence text matching none of the five real schemes' own phrase vocabulary, is honestly
`NOT_AVAILABLE`/UNKNOWN -- never a guessed scheme. Evidence citing more than one genuinely distinct
scheme (with no containment relationship between the matched phrases) is honestly
`AMBIGUOUS`/UNKNOWN, naming every scheme it found, rather than picking one arbitrarily.

**Classification is a literal phrase match, not a keyword/name heuristic.** Each of the five real
schemes (FIXED_PRIORITY, ROUND_ROBIN, WEIGHTED_ROUND_ROBIN, AGE_BASED, QOS_BASED) is recognised only
via a small, fixed list of literal, case-insensitive phrases that unambiguously name that scheme's
arbitration behaviour (e.g. "weighted round robin arbitration", "fixed priority arbitration",
"arbitrated according to qos"). Text using different wording is honestly UNKNOWN rather than guessed
via a broader keyword scan -- narrower recognition is the deliberate, disclosed trade for never
fabricating a scheme the evidence does not actually state. One real, documented de-duplication rule
exists: a WEIGHTED_ROUND_ROBIN phrase (e.g. "weighted round robin arbitration") necessarily contains
the literal substring "round robin arbitration", which the plain ROUND_ROBIN phrase list also
matches as a real substring -- this is containment, not ambiguity, so WEIGHTED_ROUND_ROBIN (the more
specific, more informative fact) wins and plain ROUND_ROBIN is dropped from the matched set in that
one case only. Every other combination of two or more distinct matched schemes is reported
AMBIGUOUS, naming both.

**Starvation-risk detection never invents a fairness bound.** `extract_fairness_bound()` looks for a
declared service-window/fairness bound in the SAME evidence text the scheme was classified from (a
"maximum wait of N cycles", "no requester shall wait more than N cycles", "bounded to N grants",
"starvation-free within N cycles", or "fairness bound of N cycles" style statement) -- never a
second, separately-supplied number, and never a value this module computes on its own. Absent such a
bound in the evidence, this module never fabricates one: if the classified scheme is FIXED_PRIORITY
and the caller's DECLARED request pattern states a continuously-active high-priority requester
alongside a present lower-priority requester, that is real, general arbitration theory (not
RTL-specific) -- fixed-priority arbitration with continuous high-priority traffic can deny a
lower-priority requester indefinitely with no fairness mechanism on record to bound it -- reported
`POTENTIAL_STARVATION`; otherwise, with no bound on record, the honest answer is `UNKNOWN` (there is
no evidence either way, and reporting `BOUNDED` would be an unearned claim). When a bound IS found,
it is compared against the caller's own DECLARED request pattern -- specifically
`max_grants_between_service`, a real caller-supplied worst-case wait figure (from a real simulation
measurement, a formal proof, or a documented worst-case analysis; this module performs none of those
itself and never derives this number). A pattern within the bound is `BOUNDED`; one exceeding it is
`POTENTIAL_STARVATION`; a bound with no such figure supplied at all is honestly `UNKNOWN`.

**File-safety / reuse note.** Per this batch's isolation rule, this module imports nothing from any
other file in this project -- not `amba_fabric_analysis.py`, not `shared_bus_resource_registry.py`,
not any other new module in this batch. `evidence_text`, `request_pattern`, `fabric_name`/
`component_name` are all accepted as generic, duck-typed parameters (`request_pattern` tolerates a
plain dict or any attribute-bearing object via a small `.get()`-or-`getattr()` reader, the same
convention `requirement_risk_ir.py`'s `_lookup()` already established, re-derived locally here rather
than imported).

**What this module deliberately does not do**: it does not read RTL or a spec document itself (the
caller supplies the evidence text); it does not model a real arbiter's cycle-accurate grant
sequence; it does not decide a fairness bound is CORRECT, only whether a declared pattern fits inside
a declared bound; it never invents a fairness bound, a request pattern, or a scheme the evidence does
not literally state; it writes nothing, gates nothing, and approves nothing. There is deliberately no
stage gate and no `dv-harness` CLI verb (`gates.py`/`cli.py` are untouched, per this batch's own
file-safety scope) -- the front door is `python -m dv_harness.arbitration_policy_ir --evidence-file
<file> [--request-pattern-file <file>] [--fabric-name ...] [--component-name ...] [--json]`.

Proven by `dv_harness_tests/test_arbitration_policy_ir.py` (24 tests): one positive control per real
scheme; NOT_AVAILABLE for absent/blank/unrecognized evidence text; the component-name-never-drives-
classification negative control (both with conflicting evidence present and with no evidence at all);
the WRR/round-robin de-duplication proof; a genuine two-scheme AMBIGUOUS case naming both;
`extract_fairness_bound()`'s positive path across five real phrasings plus its negative controls;
starvation-risk BOUNDED/POTENTIAL_STARVATION/UNKNOWN driven across every bound-present/bound-absent x
FIXED_PRIORITY/other-scheme combination, an invalid-observed-value refusal, and a duck-typed request-
pattern object; the combined `ArbitrationPolicyIR` builder (including the ambiguous-scheme case
correctly never triggering the FIXED_PRIORITY-only starvation rule); report rendering; and two real
CLI invocations (JSON output and default text output).


<!-- S163: moved verbatim from CLAUDE.md original lines 9858-9935 (M4.6 CLAUDE Context Normalization) -->
## QoS Policy IR + Ordering Contention Verification (2026-09-06)

Nothing in this repo modelled per-master QoS-level/priority/weight facts or checked whether a
declared QoS ordering was actually observed at runtime. A repo-wide search before writing this
confirmed the gap: `multi_port_fairness_qos_gate.py` (referenced by name in this file's own
Engineering Discipline Rules section) is a per-stage, agent-attested shape check over free-text
evidence, not a typed IR; nothing else in `dv_harness/` names `qos_level`/`qos_policy`/a
per-master priority mapping. `dv_harness/qos_policy_ir.py` is that missing IR, and it is
deliberately narrow: a QoS-level/priority/weight mapping built from real caller-supplied
spec/RTL evidence, plus a contention-verification helper -- nothing more.

**Every QoS fact requires a real evidence citation, enforced rather than trusted.**
`build_qos_policy_ir()` takes a duck-typed list of per-master records
(`master_id`/`qos_level`/`priority`/`weight`/`evidence`/`source`) and REFUSES (raising
`QoSPolicyIRError`) any entry carrying a `master_id` with no non-empty `evidence` string -- a
QoS priority/weight claim with no cited spec/RTL source is exactly the unsupported claim the
Evidence Truth Rule forbids. A `priority`, when declared, must be a real (non-bool) `int`; a
`weight`, when declared, a real (non-bool) number; either wrong type is a hard refusal, never a
silently coerced value. An entry that legitimately declares no QoS fact at all (a master named
but not yet assigned a tier) is NOT an error: it is recorded with the honest
`NO_QOS_FACTS_DECLARED` status, kept visibly distinct from a malformed record.

**A bare numeric priority is never guessed into an ordering.** `derive_priority_ordering()`
turns a policy's declared `priority` numbers into a rank ordering (with tie-groups for masters
sharing one value) ONLY when the caller has explicitly declared `priority_convention` --
`HIGHER_IS_HIGHER_PRIORITY` or `LOWER_IS_HIGHER_PRIORITY` -- and at least two masters carry a
real priority value. Different real conventions genuinely disagree here (AMBA AXI QoS: higher
value wins; a hand-rolled arbitration-priority register: often the opposite), and guessing wrong
would silently invert every downstream contention verdict. Absent a declared convention or
enough priority data, it reports `ORDERING_NOT_AVAILABLE` with the real reason -- never a
fabricated ordering. A caller who already holds a directly-declared ordering (a spec table) may
skip derivation entirely.

**`verify_qos_contention()` is the ordinal check the task asked for, and only that.** Given a
declared ordering (highest precedence first; a nested list denotes an explicit priority tie, and
two tied masters are NEVER flagged against each other) and a caller-supplied list of
transaction-order records (`master_id`/`position`/`window_id?`), it groups records sharing one
`window_id` into a single real contention scenario and reports one of three honest verdicts,
never a fourth invented value and never collapsed into two: `VIOLATED` (a strictly-higher-ranked
master's transaction was observed at a LATER ordinal `position` than a strictly-lower-ranked
master's, within the same window -- a real ordering violation, both sides' positions cited);
`VERIFIED` (no violation, and at least one window genuinely compared two or more masters both
present in the declared ordering -- a real, checked pass); `UNKNOWN` (nothing was actually
comparable -- every window was empty, single-master, or every master in it was absent from the
declared ordering). A master absent from the ordering is reported separately per window
(`unknown_masters`) and never forced into a comparison it has no declared rank for.

**Deliberately, explicitly NOT a performance check.** Per this batch's own instruction,
Performance Verification (any numeric latency/bandwidth/throughput target) is entirely out of
scope for this session. `position` is documented and enforced as a pure caller-supplied ORDINAL
index -- a grant order or scoreboard sequence number, never a timestamp or cycle count -- and
this module computes, stores, and claims no numeric performance value anywhere. QoS ordering
correctness is treated as the purely relative/ordinal question it is, kept structurally separate
from any timing claim.

**Deliberately bounded, and stated rather than implied closed.** (1) It authors no QoS
level/priority/weight fact of its own -- every value is transcribed from a caller-supplied,
evidence-cited record, exactly the "transcribe, never author" boundary several sibling
extraction modules in this codebase already draw. (2) It performs no RTL/spec parsing itself and
imports nothing else from `dv_harness` -- inputs are plain, duck-typed dicts/objects, so it stays
usable regardless of which future extractor eventually produces a real per-master QoS/priority
fact set. (3) It decides, approves, and arbitrates nothing beyond its own three-verdict report:
no build, job, or approval is touched, and there is deliberately no stage gate -- a contention
verdict is an input to a human's arbitration-review decision, never a substitute for one. (4) It
is a standalone module with no `dv-harness` CLI verb, no graph node, and no `gates.py` entry (out
of this task's own file-safety scope) -- reachable only by direct import.

Proven by `dv_harness_tests/test_qos_policy_ir.py` (29 tests): the core positive path
(policy construction, priority-ordering derivation with and without declared ties, a verified
contention window); real negative controls for every validation rule (missing/blank evidence,
missing master_id, duplicate master_id, invalid/bool priority and weight types, an unrecognized
priority convention, insufficient data for ordering derivation with and without a declared
convention); a real inverted-priority `VIOLATED` case citing both sides' positions; the
tied-masters-never-flagged and unknown-masters-never-compared negative controls; default-window
grouping when no `window_id` is declared; multi-window isolation (one window `VERIFIED`, a
sibling window `VIOLATED`, in one report); and malformed-transaction-record refusals (missing
master_id, non-int/bool position, invalid window_id).


<!-- S164: moved verbatim from CLAUDE.md original lines 9936-9953 (M4.6 CLAUDE Context Normalization) -->
## Coherency Capability IR: ACE-Style Behavioral Capability, Never Inferred From a Protocol Name (2026-09-06)

`syoscb_compare_policy.py` already has a `_coherency_axis()` function, and `dv_harness/coherency_capability_ir.py` deliberately does NOT import it -- reading it first is exactly what confirmed the two answer different questions at different scopes. `_coherency_axis()` decides one narrow, SyoSil-specific fact: whether `AMBA_TRANSACTION_IR_FIELDS` has a slot for a coherency signal at all, so it can fill one field (`coherency_attributes`) of a compare-key schema (`MATCH_KEY_AXES`) -- and it correctly reports `AXIS_NO_IR_FIELD` for every protocol whose signal vocabulary carries an ACE-Lite signal, because no IR field exists to hold one. It was never meant to, and does not, model coherency BEHAVIOR.

`coherency_capability_ir.py` is a full behavioral capability model, a different and larger scope: four independently classified axes -- snoop-type support, coherency-domain membership, barrier-transaction support, and dirty/clean cache-line tracking -- each carrying its own status, evidence basis, and citation, answering "what can this DUT/interface actually DO" rather than "does a compare-key schema have a slot for this". Nothing in this module reads, imports, or re-derives anything from `syoscb_compare_policy.py`.

**The Evidence Truth Rule is enforced structurally, not only stated.** "ACE support must never be assumed from an AXI base protocol" is a property of `classify_axis(axis_name, evidence)`'s own signature -- it takes no `protocol` argument at all, so no code path can let a protocol string influence an axis's classification. `protocol`/`dut_name` are accepted only by `build_coherency_capability_ir()`, recorded on the resulting IR as informational context, and never consulted by classification -- proven directly (`test_axis_classification_never_reads_the_protocol_field`) by driving identical evidence under three different declared protocol strings and asserting byte-identical axis results, and by a companion test proving a bare `protocol="AXI_MM"` declaration with zero evidence still reports every axis `CAP_UNKNOWN`, never a guessed `NOT_SUPPORTED`.

Every axis is classified from exactly one of three real evidence kinds, each requiring a real citation: (1) `simulation_observed_values` -- real waveform/sim.log evidence that the capability's encoding was actually driven, the strongest proof this module recognizes; (2) `spec_statement` -- an explicit, cited spec/programming-guide sentence, either direction; (3) `signals_present`/`signals_checked` -- a real observed signal set compared against this module's own FIXED ACE/ACE-Lite witness-signal vocabulary (`AXIS_WITNESS_SIGNALS` -- ARSNOOP/AWSNOOP for snoop type; ARDOMAIN/AWDOMAIN plus the AC snoop channel for domain membership; ARBAR/AWBAR/WACK/RACK for barrier transactions; CRRESP plus the CR/CD channels for dirty/clean tracking -- the same "witness signal proves the field" convention `amba_transaction_ir.py`'s own `IR_FIELD_WITNESS_SIGNALS` already uses). A witness signal present proves `CAP_SUPPORTED`; the FULL witness set checked (a real superset, not a partial grep) and confirmed absent proves `CAP_NOT_SUPPORTED` -- a partial signal list can never manufacture a false-negative conclusion, proven directly. Absent all three, the honest answer is `CAP_UNKNOWN`, never a default. `CAP_NOT_APPLICABLE` is reachable only through an explicit caller `declared_not_applicable` (a real reason plus citation) -- never inferred by this module from a protocol name or family.

The whole-IR rollup (`derive_overall_capability()`) is worst-wins, the same "an unresolved fact must never silently disappear into an average" discipline this project applies everywhere: any axis at `CAP_UNKNOWN` forces the overall verdict to `COHERENCY_CAPABILITY_UNKNOWN` regardless of how many other axes are clean.

**File-safety scope held exactly.** This module imports nothing from the claimed file list or any other new module in this batch -- only `dv_harness.models.Status` (a stable, unclaimed module, imported solely to run `assert_no_verification_verdict_vocabulary()` at import time, holding this module's status/evidence-basis/overall vocabularies disjoint from a real stage verdict) and `dv_harness.connectivity.render_markdown_table` (this repo's one parameterized table renderer, reused rather than a fourth hand-rolled table loop -- also unclaimed and pre-existing outside this batch). No `dv-harness` CLI verb was added and `gates.py`/`cli.py`/`CLAUDE.md` were not touched, per this task's own file-safety scope; the front door is `python -m dv_harness.coherency_capability_ir --evidence <file.json> [--json]` (exit 0 every axis determined, 1 at least one axis `CAP_UNKNOWN`, 2 malformed/unreadable input).

**Deliberately bounded, and stated rather than implied closed.** This module classifies four capability axes from evidence a caller already has; it parses no RTL, runs no verible subprocess, and reads no waveform itself -- producing that evidence (a real port parse, a real VIP config dump, a real sim.log capture) is a caller's job. It decides, approves and arbitrates nothing beyond its own classification: no build, no job, no approval, and there is deliberately no stage gate -- a `CoherencyCapabilityIR` is an input to a human's coverage/architecture decision, never a substitute for one.

Proven by `dv_harness_tests/test_coherency_capability_ir.py` (31 tests): the positive path for all three evidence kinds (RTL signal presence, full-enumeration confirmed absence, spec statement both directions, simulation-observed values, declared-not-applicable); the two headline Evidence-Truth-Rule proofs described above; nine negative controls (an unknown axis name, a missing citation for each of the four evidence-declaration shapes, a partial signal enumeration proven unable to manufacture a false `NOT_SUPPORTED`, non-mapping evidence, an unrecognized axis key in a full evidence document); all four overall-rollup combinations (full support, no support, partial, not-applicable, and unknown-outranks-a-partially-clean picture); table rendering and IR-completeness checks; and four real CLI subprocess invocations covering all three exit codes plus a JSON round-trip. `python -m pytest dv_harness_tests/test_coherency_capability_ir.py -q` -> `31 passed`.


<!-- S165: moved verbatim from CLAUDE.md original lines 9954-9965 (M4.6 CLAUDE Context Normalization) -->
## AMBA command.txt extension (dv_harness/amba_command_txt_extension.py, 2026-09-06)

de_command_style_learning.py (this session) already classifies a DE command.txt line GENERICALLY -- what kind of statement it is, and a GLOBAL/DUT/FW/VIP branch-owner guess. It has no notion of AMBA fabric semantics at all: which master issued a transaction, which address region the transaction's address falls in beyond a bare number, or whether the statement executes inside a fork/join block alongside other masters' traffic running in parallel. amba_command_txt_extension.py closes that gap with a narrow, AMBA-specific compiler over the same kind of command record, answering four independent questions per command: operation (WRITE / READ / a recognized-but-neither macro / a structural non-transaction line / genuinely unclassifiable), master (which named master issued it), region (which named address region its address falls in), and parallel-group (which fork/join nesting group, if any, it executes inside).

The module is deliberately built to duck-type its input rather than import either de_command_style_learning.py or pattern_ir_assembly.py -- both are concurrent, differently-scoped modules in this same batch, and this batch's own file-safety rule forbids importing either. Every command record is therefore a plain dict (or any attribute-bearing object), read through small alias tables for its text (raw_text/text/source_text/line/statement/raw), its macro name (command_name/macro/name/command/statement_name), its operation (operation/semantic_operation/op), its master (master/master_name), its address (address/addr/base_address), its arguments (arguments/args), and its position (line_no/line_number/order/index). An explicit field always takes precedence over anything this module derives from raw text, so a producer that already resolved a fact is never second-guessed, and a producer that resolved nothing still gets an honest classification from the record's own text.

Master and region resolution never invent a value: master_registry and region_map are supplied entirely by the caller (real facts from wherever that caller's own project keeps them -- e.g. a fabric-discovery or port-registry artifact reduced to plain dicts before being handed in), and this module is only ever the compiler that reads a command's text against that data. An unrecognized master or region name reports one of several honestly DIFFERENT UNKNOWN-family statuses rather than a single catch-all or a guessed default: MASTER_UNKNOWN_NO_TOKEN (nothing master-shaped could even be extracted), MASTER_UNKNOWN_NO_REGISTRY_SUPPLIED (a candidate token was found but no registry was given to confirm it against), and MASTER_UNKNOWN_NOT_IN_REGISTRY (a candidate token was found and a registry was given, but the token matches nothing in it) are three different findings a reviewer needs to see differently. The region side adds a fourth honest outcome the master side cannot have: REGION_AMBIGUOUS_MULTIPLE_MATCH, when the caller's own region_map itself claims an address from more than one entry -- this module refuses to pick a winner rather than guess. Address parsing accepts only a real Verilog-style sized literal (32'h0002_0100) or an explicit integer/string address field, and explicitly refuses (reporting None with a cited reason) any literal carrying X/Z don't-care bits, rather than silently resolving them to zero.

Parallel-group membership is derived only from literal fork/join/join_any/join_none keyword text found in the records' own raw source (matched whole-word, so an identifier like forklift is never mistaken for the keyword), tracked as a real nesting stack across the ordered record sequence -- never inferred from a naming convention, and never guessed from record adjacency alone. An unbalanced join with no open fork, or a fork left unclosed at the end of the stream, is recorded as a warning on the compiled report rather than silently ignored or force-closed. Records are compiled in the order given unless every record in the batch carries a resolvable position field, in which case they are re-sorted by it -- a caller's own file order is never silently reshuffled by a guess about which field means "position" when that guess would be ambiguous.

Reuse is scoped tightly: AmbaCommandTxtExtensionReport.render_markdown() reuses dv_harness.connectivity.render_markdown_table, the repository's one parameterized table renderer, imported lazily inside the method rather than at module load. assert_no_verification_verdict_vocabulary() imports dv_harness.models lazily to check, rather than merely claim, that this module's four status vocabularies (OPERATION_STATUSES, MASTER_STATUSES, REGION_STATUSES, PARALLEL_GROUP_STATUSES) share no token with the harness's stage-gate Status verdict vocabulary. Neither de_command_style_learning.py, pattern_ir_assembly.py, nor any other file from this batch's claimed-file-safety list is imported anywhere in the module. The module performs no discovery of a project's own masters, slaves, or address map (that is amba_fabric_discovery.py/amba_port_registry.py's job, neither imported nor re-derived here), decides no VIP API, RTL content, or arbitration/security/QoS policy, and contains no performance/timing analysis of any kind. Tests live in dv_harness_tests/test_amba_command_txt_extension.py (22 cases: vocabulary hygiene, the core positive resolved-write/resolved-read/parallel-group path, and negative controls for every UNKNOWN/AMBIGUOUS status, a malformed region_map entry, a non-sequence input, and explicit-field precedence).


<!-- S166: moved verbatim from CLAUDE.md original lines 9966-9969 (M4.6 CLAUDE Context Normalization) -->
## AMBA Readiness Gates: the 9 Named Composite Gates from Section 71 (2026-09-06)

Section 71 of the AMBA M x N golden-flow source document names nine composite readiness gates and spells each out as a literal AND-formula in sections 72-80: L3_REFERENCE_READY, AMBA_PORT_REGISTRY_READY, AMBA_CONSTRAINT_READY, AMBA_CONNECTIVITY_READY, AMBA_VIP_BIND_READY, AMBA_SCOREBOARD_READY, AMBA_COVERAGE_READY, AMBA_TEST_GENERATION_READY, AMBA_SIGNOFF_READY. dv_harness/amba_readiness_gates.py is the evaluator, transcribing every AND-term verbatim from the document and applying this project's standard worst-wins discipline: a single UNMET condition blocks the whole gate as NOT_READY regardless of other clean conditions; UNKNOWN/NOT_AVAILABLE (or a condition never supplied at all) makes the gate INCOMPLETE_EVIDENCE rather than either READY or NOT_READY. AMBA_TEST_GENERATION_READY references three other gates as AND-terms; all nine are evaluated in the document's fixed order so those sub-gates are already computed, with an explicit caller override always outranking the derived value. Proven by 26 tests in dv_harness_tests/test_amba_readiness_gates.py covering the positive path, worst-wins negative controls, cross-gate propagation, malformed-input refusals, and CLI subprocess exit codes.


<!-- S167: moved verbatim from CLAUDE.md original lines 9970-9989 (M4.6 CLAUDE Context Normalization) -->
## Fabric Progress IR: Deadlock/Livelock Risk Over a Caller-Declared Wait Graph (2026-09-06)

This project's real AMBA/SyoSil integration family (amba_fabric_discovery.py, amba_port_registry.py, amba_fabric_analysis.py, amba_transaction_ir.py, amba_route_transform_predictor.py, amba_scoreboard_env.py, syoscb_*) already models fabric TOPOLOGY, TRANSACTION content, and ROUTING/TRANSFORM prediction -- none of it asks whether a caller-declared wait-for relationship among fabric agents forms a real CIRCULAR WAIT, and none of it tracks credit/outstanding-transaction counts toward exhaustion. A repo-wide check found no deadlock/livelock/circular_wait/credit_exhaust/outstanding_exhaust detector anywhere -- "deadlock" appeared only inside free-text failure-classifier regexes in system_failure_taxonomy.py/command_error_taxonomy.py, which classify already-REPORTED failure TEXT and neither build nor walk a dependency graph. dv_harness/fabric_progress_ir.py is that missing analysis, and only that.

Two independent, real graph/arithmetic analyses over facts a caller already has -- never self-derived from RTL, a VIP transaction stream, or any other producer in this project. analyze_resource_dependency_cycle(facts) takes a generic list of {resource, held_by, waiting_for} records: resource is the arbitrated fabric resource the fact is about (a port, a shared bus, a buffer slot, an arbitration grant), held_by is the agent presently holding it, and waiting_for names zero, one, or several OTHER resources that same holder is blocked waiting to acquire. This module never invents a circular-wait scenario -- it builds a resource-to-holder map from the caller's own resource/held_by pairs, resolves each waiting_for entry to the holder of that named resource, and runs real cycle detection over the resulting holder-level wait-for graph. analyze_credit_outstanding(facts) takes a generic list of {resource, credit_available, credit_max, outstanding_count, outstanding_limit} records (all fields but resource optional); exhaustion is decided from the caller's OWN numbers -- credit_available <= 0 is CREDIT_EXHAUSTED, outstanding_count >= outstanding_limit is OUTSTANDING_EXHAUSTED -- neither threshold, neither axis's presence, nor either number is invented here.

analyze_fabric_progress() composes both into one FabricProgressIR, folding an overall_status by strict WORST-WINS (a real risk finding on EITHER axis outranks everything; an evidence GAP on either axis, with no real risk found anywhere, outranks a clean report on both) -- the same no-averaging discipline golden_flow_readiness.combine_readiness()/spec_vplan_readiness_gate.py/system_readiness_gates.py already apply to their own composite folds, never re-derived a second way here.

The Evidence Truth Rule, applied literally: never claim deadlock-freedom (or exhaustion-freedom) from an INCOMPLETE graph. A waiting_for entry naming a resource this module has no {resource, held_by} fact for at all, or one whose holder is AMBIGUOUS (two facts declare two different holders for the same resource -- a real evidence conflict this module never arbitrates, the same arbitration boundary requirement_contract.py/design_knowledge_correlation.py already keep for their own conflicting-claim findings), is reported as an UNRESOLVED dependency. Finding zero cycles over a graph carrying even one unresolved dependency reports INSUFFICIENT_EVIDENCE, never NO_CYCLE_DETECTED -- an absence of proof is not proof of absence.

Proven by dv_harness_tests/test_fabric_progress_ir.py (33 tests): a real injected circular-wait cycle is detected; a clean acyclic graph reports NO_CYCLE_DETECTED; an unresolved dependency (a named resource with no fact, or an ambiguous dual-holder claim) is proven to force INSUFFICIENT_EVIDENCE rather than a false-clean result; both credit and outstanding exhaustion are proven from real caller numbers on both the exhausted and non-exhausted sides; and the worst-wins composite fold is proven against every combination of risk-found/gap/clean on both axes.

Disclosed residual: this module builds and analyzes a graph over facts it is handed -- it derives no topology or dependency fact of its own from RTL or a live simulation, and references no approval/governance mechanism.

**Extension (2026-09-07, System Deadlock/Contention Analysis, item sys_deadlock_contention): a third, genuinely contention-specific metric, added additively.** Re-verified before writing anything: fabric_progress_ir.py's two original analyses already cover deadlock (circular-wait detection) and exhaustion (credit/outstanding limits), but neither computes CONTENTION -- how many distinct agents are concurrently racing to acquire one specific resource. A resource can be heavily contended (three agents all queued on one arbitration grant) with zero cycle anywhere in the graph and with its own credit/outstanding counters perfectly healthy; nothing in the original module, or anywhere else in this repo's real fabric-progress/AMBA family, reported that fact. `analyze_resource_contention(facts)` closes exactly that gap, reusing the identical `resource_dependency_facts` shape and the same `_parse_resource_dependency_facts()`/`_build_holders_by_resource()` helpers `analyze_resource_dependency_cycle()` already uses (the holder-resolution block was extracted into a shared `_build_holders_by_resource()` helper so there is one definition of "who holds this resource, according to the facts" rather than two) -- no new graph shape, no new caller-facing input. A resource with two or more distinct concurrent waiters is `CONTENDED`; this module invents no severity threshold beyond that real count, and never arbitrates an ambiguous holder declaration here either -- a contended resource whose own holder is ambiguous (two conflicting `held_by` facts) is reported with `holder: None`, `ambiguous_holder: True`, never a guessed single holder, the same arbitration boundary the original cycle detector already keeps.

`analyze_fabric_progress()` now composes all THREE analyses (unchanged signature, unchanged positional arguments -- `resource_contention` is derived by re-running the new analysis over the same `resource_dependency_facts` argument already passed in) into one `FabricProgressIR`, whose `overall_status` fold is still strict worst-wins, now over three axes instead of two: a real risk finding on ANY of deadlock/exhaustion/contention outranks everything; an evidence gap on any axis, with no real risk found anywhere, outranks a clean report on all three. `CONTENTION_STATUSES` (`NO_CONTENTION_DETECTED`/`CONTENTION_DETECTED`/`INSUFFICIENT_EVIDENCE`) and `RESOURCE_CONTENTION_STATUSES` (`CONTENDED`/`NOT_CONTENDED`) are added to the same `assert_no_verification_verdict_vocabulary()` disjointness check the original two vocabularies already pass. Every pre-existing test and CLI exit-code contract is untouched and still passes byte-for-byte, because no fixture in the original 33-test suite ever declared two distinct waiters on one resource; the new axis is silent (`NO_CONTENTION_DETECTED`) on all of them.

Proven by 9 new tests appended to `dv_harness_tests/test_fabric_progress_ir.py` (42 total, all passing): two distinct waiters on one resource is real contention; a single waiter is not; a real 2-node circular wait over the identical facts reads contention-free (proving the two analyses are genuinely independent findings, not a relabeling of one another); a contended resource with an ambiguous holder never guesses a holder; empty/malformed/`None` facts are handled with the same honesty discipline (`INSUFFICIENT_EVIDENCE`/raise) the sibling analyses already apply; and the composed report is proven to reach `PROGRESS_RISK_DETECTED` from contention ALONE, with the dependency and credit/outstanding axes both independently clean, confirming the worst-wins fold actually reaches this third axis. Run: `python -m pytest dv_harness_tests/test_fabric_progress_ir.py -q` -> `42 passed`.


<!-- S168: moved verbatim from CLAUDE.md original lines 9990-10005 (M4.6 CLAUDE Context Normalization) -->
## Security Policy IR: an Access Matrix Built Only From Cited Evidence (2026-09-06)

A repo-wide grep for SecurityPolicyIR, security_policy, TrustZone, secure_privileged, access_matrix, S_NS/ARM_TZ, and the real AMBA/SyoSil/system module family (amba_fabric_discovery.py, amba_port_registry.py, amba_fabric_analysis.py, amba_transaction_ir.py, amba_route_transform_predictor.py, amba_scoreboard_env.py, syoscb_compare_policy.py, syoscb_topology_plan.py, syoscb_result_taxonomy.py, syoscb_phase1_report.py, syoscb_source_audit.py, system_resource_inventory.py, system_topology_analysis.py, system_scheduling_plan.py) found no security/privilege PERMISSION concept anywhere in this repo: the AMBA family models fabric topology, transaction routing, and route-transform prediction, never a security axis; the SyoSil family models scoreboard compare/topology/result-taxonomy, an unrelated domain; the system_* family models cross-subsystem resource ownership and topology, not per-access security policy. dv_harness/security_policy_ir.py is new, standalone territory -- it imports nothing from any of those files or from any other new module built in this same batch; its only import is dv_harness.models, for the vocabulary-disjointness check several sibling modules already run against it.

A SecurityPolicyIR is a set of caller-declared ACCESS RULES, each stating an ALLOWED or DENIED decision for a (master, region, secure, privileged) combination -- or a wildcard subset of it -- together with a REQUIRED, non-empty evidence citation (a spec section, an RTL file:line, a register programming-guide reference). A rule with no evidence citation is refused outright (SecurityPolicyIRError) rather than silently accepted: an uncited access-permission claim is exactly the "confident guess" the Evidence Truth Rule forbids, and getting a security-permission fact wrong is higher-consequence than most facts this harness handles. Nothing here infers a decision from a master/region NAME, a naming convention, or any other heuristic -- every decision traces to a rule a caller explicitly declared, with its citation carried through to every classification result that uses it.

An access combination no declared rule covers is classified UNKNOWN -- never defaulted to ALLOWED (a fail-open default-allow guess on a security matrix is exactly the kind of silent default this project forbids) and never defaulted to DENIED either (that would fabricate a security decision nobody declared). A caller MAY declare an explicit, cited default_decision for the whole matrix (e.g. "undeclared regions/masters default DENY, per <spec citation>") -- applied only when no specific rule matches, always distinguishable in the result from a matched-rule decision, and itself requires a citation like any other rule.

Two rules of equal specificity naming the SAME access combination with DIFFERENT decisions is a genuine, uncited-into-agreement CONFLICT -- this module never picks a winner (no source-authority order is declared here; that arbitration, if wanted, belongs to a caller invoking a real conflict-resolution mechanism such as source_authority.py, deliberately not imported here). A conflict classifies as UNKNOWN and names both conflicting rules and their citations.

The negative-test verification helper checks that a supplied test result actually OBSERVED a denial for an access the matrix says should be denied -- it never assumes a negative test passed just because a verdict field says so; it looks for the real observed evidence of the denial (e.g. a recorded error response, an assertion firing) rather than trusting a bare PASS label.

Proven by dv_harness_tests/test_security_policy_ir.py (34 tests): a matched rule classifies correctly with its citation carried through; an uncited rule is refused at construction; an uncovered combination is UNKNOWN both with and without a declared default; a conflicting pair of equal-specificity rules is proven UNKNOWN naming both; and the negative-test verification helper is proven to distinguish a real observed denial from a bare PASS-labeled result that never actually exercised the denial path.

Disclosed residual: this module classifies from caller-declared, cited rules only -- it derives no security fact of its own from RTL or a live simulation, arbitrates no conflict, and references no approval/governance mechanism.


<!-- S169: moved verbatim from CLAUDE.md original lines 10006-10019 (M4.6 CLAUDE Context Normalization) -->
## AMBA Performance Calculator: Pure Arithmetic Over Caller-Supplied Numbers, Never an Invented Peak (2026-09-06)

This harness has no live simulator and no formal tool, so its only real timing evidence is whatever an already-produced artifact (`fsdb_report.py` output, a sim.log, or a caller-supplied trace record) already contains. Nothing in this repo did the ONE-LEVEL-ABOVE-`fsdb_report.py` arithmetic a performance report needs: bandwidth/throughput/latency-percentile/outstanding-count/stall-ratio/utilization computation over real, already-extracted numbers, with the three rules this domain's fabrication risk demands enforced in code rather than left as a docstring promise. `dv_harness/amba_performance_calculator.py` is that arithmetic layer, and only that.

**Three rules, enforced as code, not prose.** (a) A numeric threshold/target is NEVER invented — `evaluate_against_target()` reports `NOT_APPLICABLE`, never a fabricated pass/fail, whenever no caller-declared `target_value` exists. (b) An unprovable peak/baseline/metric yields `UNKNOWN`, never a computed-looking number — every function returns a typed result (`MetricResult`/`LatencyPercentileReport`/`OutstandingStatsResult`/`TargetEvaluationResult`) carrying an explicit `status` in `{COMPUTED, UNKNOWN, NOT_APPLICABLE}` (asserted disjoint from `dv_harness.models.Status` at import time), and an empty/missing input list always reports `UNKNOWN` with a real reason rather than a silent zero or a crash. `bandwidth_utilization()` is the sharpest instance: it MUST report `UNKNOWN` when no caller-supplied, already-proven peak bandwidth is provided — it never divides against an invented or reverse-engineered ceiling. (c) Functional correctness ALWAYS outranks a performance PASS — `decide_overall_verdict()` is a hard PRECEDENCE branch over the real `models.Status.PASS`/`FAIL` vocabulary (reused, not re-spelled): a functional FAIL is the overall verdict regardless of how good the performance numbers are, and a performance PASS can never promote a functionally-incorrect result to an overall PASS. This is a branch, never a weighted score.

**Data shapes.** `LatencyDefinitionIR` states what "latency" means for a measurement (`ISSUE_TO_FIRST_BEAT` / `ISSUE_TO_LAST_BEAT` / `REQUEST_TO_RESPONSE`) — NEVER assumed, mandatory on every latency-percentile call, because different callers mean different things by "latency" and silently picking one would misrepresent whichever quantity the underlying evidence actually measured. `PerformanceSampleIR` is one real observed transaction/window sample (counts, byte sizes, start/end timestamps, all caller-supplied — this module never derives one itself). `PortPerformanceIR`/`PathPerformanceIR` are per-port/per-path aggregates built by `aggregate_port_performance()`, which calls only the module's own pure functions — no metric is ever computed a second, disagreeing way. `PerformanceWindowIR` is a time window over which samples were aggregated; `PerformanceCurveIR` is an ordered series of windows for a future ramp/saturation curve — this module only HOLDS that data shape, it does not generate the ramp itself (that needs a live traffic generator, explicitly out of scope: this harness has no live simulator to validate one against).

**Pure functions, each over real caller-supplied numbers only**: `compute_bandwidth`/`compute_throughput` (bytes or transactions over time), `compute_latency_percentiles` (p50/p90/p95/p99 via linear-interpolation percentile arithmetic, no third-party dependency, mandatory `latency_definition`), `compute_outstanding_stats` (average/peak over a real list of observed outstanding counts), `compute_stall_ratio`/`compute_utilization` (stalled-or-busy cycles over total cycles, both caller-supplied — an over-1.0 ratio is reported as real evidence with a data-quality `reason` rather than clamped or hidden), `bandwidth_utilization`, `evaluate_against_target`, and `decide_overall_verdict`.

**Deliberately bounded, and stated rather than implied closed.** It never reads an FSDB/waveform file, never monitors a live signal, never generates traffic, and never runs a simulation — all explicitly out of scope for this batch. It decides nothing beyond the one hard precedence rule in (c): no gate, no approval, no build/regression/LSF submission, and there is deliberately no stage gate.

Proven by `dv_harness_tests/test_amba_performance_calculator.py` (51 tests) against small real synthetic transaction-trace fixtures built directly in the test file: core positive paths for every function; the required negative controls proving UNKNOWN on an empty/missing sample list rather than a crash or a fabricated zero; the headline `bandwidth_utilization`-is-UNKNOWN-with-no-peak-supplied test; `evaluate_against_target`'s NOT_APPLICABLE-with-no-target test; and the functional-correctness-outranks-performance test (functional FAIL + performance PASS still reads overall FAIL), plus its sibling proving an unresolved/unrecognized functional verdict is never silently promoted to PASS by a good performance number. `python -m pytest dv_harness_tests/test_amba_performance_calculator.py -q` → `51 passed`.


<!-- S170: moved verbatim from CLAUDE.md original lines 10020-10101 (M4.6 CLAUDE Context Normalization) -->
## AMBA Performance Requirement Checker: PASS/FAIL Against a Declared Requirement, Functional Correctness Always Outranks a Performance PASS (2026-09-06)

`amba_performance_calculator.py` (built earlier in this same batch) computes real performance
METRICS from caller-supplied samples and already carries one generic threshold-comparison
primitive, `evaluate_against_target()` -- but that function speaks in `meets_target: bool` and
its own `COMPUTED`/`UNKNOWN`/`NOT_APPLICABLE` metric-status vocabulary, not in this project's
real PASS/FAIL verdict vocabulary, and it has no notion of a REQUIREMENT as a persisted, typed
object, nor of functional correctness ever overriding it. `dv_harness/
amba_performance_requirement_checker.py` is the thin requirement layer that sits directly on
top of it, reusing `evaluate_against_target()` for the actual comparison arithmetic rather than
re-implementing it -- there remains exactly one place in this package that decides "does this
number clear this threshold".

**A requirement is ALWAYS caller/spec-declared, never invented.** `PerformanceRequirementIR` is
a frozen dataclass (`requirement_id`, `metric_name`, `target_value`, `comparison`, `unit`,
optional `source`) whose `__post_init__` refuses to construct an instance missing
`target_value`, `comparison`, or `unit`, or carrying an unrecognized `comparison` operator or a
non-numeric/boolean `target_value` -- rule (a) enforced at the object's own construction
boundary, not merely documented. The case where NO requirement exists for a metric at all is
modeled by never building a placeholder IR: `check_against_requirement()` accepts
`requirement=None` and reports `NOT_APPLICABLE`, checked BEFORE the measured value is even
consulted, so "nobody declared a threshold" is never misread as "we tried to measure something
and failed" (the opposite precedence `evaluate_against_target()` would otherwise apply, since
that function checks a missing observed value first).

**The measured value may be almost anything a caller already has, and an unresolvable shape
raises rather than guesses.** `check_against_requirement(measured, metric_name, requirement=None,
functional_verdict=None)` resolves `measured` via `_resolve_measured_value()`: a bare
`int`/`float` is used directly; a MetricResult-shaped object (anything carrying both `.status`
and `.value`, duck-typed rather than isinstance-checked) is honored ONLY when its own status is
the calculator's real `STATUS_COMPUTED` token (imported, never re-typed) -- an `UNKNOWN`/
`NOT_APPLICABLE`/unrecognized status on the metric yields `None` plus that metric's own `reason`,
never a value silently read as zero; a dict or any object exposing a `metric_name` field (the
shape a real `PortPerformanceIR`/`PathPerformanceIR` and `metric_name="bandwidth"` naturally
produces) is resolved one level deep by the same two rules. A measured value this module has no
honest way to read a number out of (a bare list, a bool, a dict missing the named field entirely
in some cases, an object with neither the field nor a numeric/MetricResult shape) either raises
`PerformanceRequirementCheckerError` (a genuine caller-usage bug) or reports `UNKNOWN` (an
honestly incomplete measurement) -- the module's docstring and tests draw that line explicitly:
malformed shape is a raise, missing-but-well-shaped evidence is `UNKNOWN`.

**Rule (c), functional correctness always outranks a performance PASS, is a hard precedence in
code, never a weighted score.** `functional_verdict` is optional and, when supplied, must be one
of `models.Status.PASS`/`models.Status.FAIL` (this project's one real verification-verdict
vocabulary, reused verbatim rather than a second spelling) -- anything else raises. When it IS a
real `FAIL`, the returned `status` is forced to `FAIL` UNCONDITIONALLY, regardless of what the
performance comparison found, including `NOT_APPLICABLE` or `UNKNOWN`: a high-performance but
functionally-incorrect transaction is still an overall FAIL no matter how good, absent, or
unmeasured its performance numbers are. When `functional_verdict` is `None` (the caller is not
asking this call to consider functional correctness at all) or a real `PASS`, the returned
`status` equals the performance comparison's own verdict unchanged -- a functional PASS never
elevates an unmeasured or failing performance result into an overall PASS. Both the raw
`performance_status` and the (possibly overridden) overall `status` are carried on
`PerformanceRequirementCheckResult`, so a reader can always see whether an overall FAIL came from
the performance comparison itself or from the functional-correctness override.

**Reuse, not reinvent.** This module imports `amba_performance_calculator`'s own
`STATUS_COMPUTED`/`STATUS_NOT_APPLICABLE`/`STATUS_UNKNOWN` tokens and its
`evaluate_against_target()` function directly rather than re-typing a second comparison
arithmetic or a second metric-status vocabulary, and imports `models.Status` for the PASS/FAIL
half exactly as the calculator module already does. It never reads an FSDB/waveform file, never
simulates anything, never parses a sim.log, and performs no gate/approval/build/regression/LSF
action -- pure arithmetic and classification over numbers a caller already extracted, directly or
via the calculator layer.

Proven by `dv_harness_tests/test_amba_performance_requirement_checker.py` (24 tests, real
synthetic numeric traces only): `PerformanceRequirementIR` construction refusals for every
missing/malformed mandatory field; core PASS/FAIL positive paths; `NOT_APPLICABLE`-never-a-
failure with and without a measured value present; `UNKNOWN`-never-a-fabricated-number both for a
plain missing measured value and for a real `bandwidth_utilization()` result that is honestly
`STATUS_UNKNOWN` because no peak bandwidth was supplied (propagated through this checker, never
computed into a percentage); real `PortPerformanceIR`-shaped measured values via
`aggregate_port_performance()`, with real samples and with none; dict and nested-MetricResult-in-
dict measured shapes; the three required functional-correctness-outranks-performance cases (a
functional FAIL overriding a performance PASS, a `NOT_APPLICABLE` result, and an `UNKNOWN`
result), the negative control that a functional PASS never elevates a performance FAIL, and the
omitted-`functional_verdict` no-op case; plus negative controls for an invalid functional-verdict
string, an unresolvable measured-value shape, a bare bool measured value, and a dict missing the
named field reporting `UNKNOWN` rather than raising. Real run:
`python -m pytest dv_harness_tests/test_amba_performance_requirement_checker.py -q` ->
`24 passed`.


<!-- S172: moved verbatim from CLAUDE.md original lines 10116-10205 (M4.6 CLAUDE Context Normalization) -->
## AMBA Performance Modules: Standalone Front Doors + `dv-harness` CLI Wiring (2026-09-07)

An audit phase re-verified this project's own governing claim before trusting it: `grep -n
"^def main\|__main__\|execute_verb"` over `amba_performance_calculator.py`,
`amba_performance_classification.py`, and `amba_performance_requirement_checker.py` returned zero
matches, while `amba_performance_readiness_gates.py` already carried a real `execute_verb()`/
`main()`/`if __name__ == "__main__":` triple (lines 528-617) and a real, wired `dv-harness
amba-performance-readiness-gates` verb (`cli.py:2354-2358, 6248-6249`). The confirmed gap was
narrower than "not wired into `cli.py`" -- the pattern several dozen other CLAUDE.md sections
describe as a deliberate, disclosed choice: three of the four modules had **no CLI-callable entry
point at all**, standalone or wired. They were pure importable Python APIs, usable only via direct
import (by `dashboard.py`'s AMBA Per-Port Performance Center / AMBA Performance Trend View cards,
and by their own test suites).

**Task A -- standalone front doors, mirroring `amba_performance_readiness_gates.py`'s own real
pattern exactly.** Each of the three modules gained an `execute_verb(argv)`/`main()`/
`if __name__ == "__main__":` triple, argparse subcommands over the module's own already-real pure
functions -- no new arithmetic, no new classification logic, no new comparison arithmetic:

- `amba_performance_calculator.py`: `bandwidth`/`throughput`/`latency-percentiles`/`outstanding`/
  `stall-ratio`/`utilization`/`bandwidth-utilization`/`evaluate-target`/`overall-verdict`/
  `aggregate-port`, each calling exactly one of `compute_bandwidth()`/`compute_throughput()`/
  `compute_latency_percentiles()`/`compute_outstanding_stats()`/`compute_stall_ratio()`/
  `compute_utilization()`/`bandwidth_utilization()`/`evaluate_against_target()`/
  `decide_overall_verdict()`/`aggregate_port_performance()` unchanged.
- `amba_performance_classification.py`: `saturation`/`bottleneck`/`anomaly`/`regression-delta`/
  `fairness`/`overall-verdict`, each calling exactly one of `classify_saturation()`/
  `identify_bottleneck_candidate()`/`detect_anomaly()`/`compute_regression_delta()`/
  `compute_jains_fairness_index()`/`decide_overall_performance_verdict()` unchanged.
- `amba_performance_requirement_checker.py`: `check`, calling `check_against_requirement()`
  unchanged, building a `PerformanceRequirementIR` from CLI flags only when `--target` is
  supplied (with `--requirement-id` and `--unit` then required -- a requirement is never invented
  with a missing field, mirroring that dataclass's own `__post_init__` refusal) and reading a
  measured value from `--measured-value` (a bare number) or `--measured-file` (a JSON number/dict,
  read by `_resolve_measured_value()` unchanged).

Every result is a real dataclass instance, printed via `dataclasses.asdict()` (JSON with `--json`,
or a plain `key: value` listing by default) -- never a re-serialization that could disagree with
the object's own real fields. Exit codes follow each module's own status vocabulary honestly
(never a silent success for an unresolved result): `COMPUTED`/a real `PASS`/a real non-alarming
classification (`NOT_SATURATED`/`NO_ANOMALY`/`IMPROVED`/`UNCHANGED`) exits 0; `UNKNOWN`/
`NOT_APPLICABLE`/`FAIL`/a real finding needing attention (`SATURATED`/`ANOMALY_DETECTED`/
`REGRESSED`/`INDETERMINATE`/`INCONCLUSIVE`) exits 1; a malformed argument or unreadable/invalid
JSON input file exits 2, printing `NOT_AVAILABLE: <reason>` to stderr rather than a bare
traceback.

**Task B -- `dv-harness` CLI verbs, purely additive.** `cli.py` gained three new
`sub.add_parser(...)` blocks (`amba-performance-calc`, `amba-performance-classify`,
`amba-performance-check-requirement`) immediately before the existing
`amba-performance-readiness-gates` subparser, and three matching `elif args.cmd == "...":`
dispatch blocks immediately before that verb's own dispatch block -- following the *exact*
established convention that verb's own dispatch already uses (reconstruct the equivalent argv
from the parsed CLI flags, then `raise SystemExit(<module>.execute_verb(<reconstructed_argv>))`).
No existing subparser, dispatch branch, or business logic in `cli.py` was touched, reordered, or
reformatted. All flags a caller might need across every one of the three modules' own verbs are
declared once on each new top-level subparser (an argparse convenience over reconstructing a
nested-subcommand CLI, not a second copy of any module's own logic); a flag irrelevant to the
verb actually requested is simply never forwarded into the reconstructed argv.

Verified end to end, not merely wired: `python -m dv_harness.cli --help` lists all three new
verbs alongside every pre-existing one; `dv-harness amba-performance-calc bandwidth
--total-bytes 1000 --duration-seconds 2 --json`, `dv-harness amba-performance-classify anomaly
--observed-value 5 --baseline-min 1 --baseline-max 3 --json`, and `dv-harness
amba-performance-check-requirement check --metric-name bandwidth --measured-value 900
--requirement-id REQ1 --target 1000 --unit bytes_per_second --json` were each driven as real
subprocess invocations through the `dv-harness` entry point and produced the identical real
dataclass output (and exit code) their standalone `python -m dv_harness.<module>` front doors
produce.

**Deliberately bounded, and stated rather than implied closed.** This closes the CLI-callability
gap only -- it adds no new arithmetic, no new classification rule, and no new comparison logic to
any of the three modules; every verb is pure argparse plumbing over an already-real, already-tested
function. `amba_performance_readiness_gates.py` was not touched (it already had both halves). No
`gates.py` `STAGE_GATES` entry was added for any of the three -- none of them is, or was asked to
be, a stage gate; they remain callable computation/classification utilities, now reachable both by
import and from the command line.

Re-verified against the full, real, pre-existing test suite for this whole family (no test file was
added or edited, since no production logic changed): `python -m pytest
dv_harness_tests/test_amba_performance_calculator.py
dv_harness_tests/test_amba_performance_classification.py
dv_harness_tests/test_amba_performance_requirement_checker.py
dv_harness_tests/test_amba_performance_readiness_gates.py
dv_harness_tests/test_dashboard_amba_performance_center.py
dv_harness_tests/test_dashboard_amba_performance_trend_view.py -q` -> `181 passed`, byte-identical
to the audit's own pre-change baseline. `python -m pytest
dv_harness_tests/test_cli_adapter_command_resolution.py dv_harness_tests/test_cli_blackboard.py
dv_harness_tests/test_cli_preflight.py dv_harness_tests/test_cli_question_queue.py -q` ->
`36 passed`, confirming the purely-additive `cli.py` edit disturbs no other verb.


<!-- S173: moved verbatim from CLAUDE.md original lines 10206-10220 (M4.6 CLAUDE Context Normalization) -->
## AMBA Performance Readiness Gates: BUS_PERFORMANCE_READY / BUS_PERFORMANCE_SIGNOFF_READY (2026-09-06)

Two composite gates -- `BUS_PERFORMANCE_READY` and `BUS_PERFORMANCE_SIGNOFF_READY` -- each a real AND-formula over caller-supplied condition inputs, `dv_harness/amba_performance_readiness_gates.py` matches this project's other composite-gate modules (`amba_readiness_gates.py`, `subsystem_maturity_gate.py`, `functional_coverage_signoff.py`, `spec_vplan_readiness_gate.py`, `system_readiness_gates.py`) in shape and discipline. This is the highest fabrication-risk domain in this project -- performance -- and this harness has no live simulator and no formal timing tool, so this module never computes, measures, or estimates a single performance number: it only folds already-real `{"condition_name": ..., "status": ...}` records a caller supplies. It deliberately imports NOTHING from `amba_performance_calculator.py`, `amba_performance_requirement_checker.py`, or `amba_performance_classification.py` -- it never assumes any of those three modules exist, ran, or finished cleanly in the same batch. Whatever those modules concluded reaches this gate only as a generic, duck-typed condition record naming their conceptual output (e.g. `Performance_Target_Declared`, `Performance_Requirement_Evaluation_Complete`) -- this module never inspects a waveform, a sim.log, or an `fsdb_report.py` output itself, and never decides what counts as satisfying a named condition.

**Three fabrication-risk rules are enforced IN CODE here, never left as a docstring promise.** (a) A numeric threshold/target is NEVER invented by this module -- it has no field anywhere for a number; a caller either supplies a condition record saying whether a target was declared (`Performance_Target_Declared`: MET/UNMET/UNKNOWN/NOT_AVAILABLE) or the whole performance dimension is marked `NOT_APPLICABLE` for a project/path that is not performance-critical. (b) An unprovable peak/baseline/metric condition yields UNKNOWN/NOT_AVAILABLE, which this module folds to `INCOMPLETE_EVIDENCE` -- never a computed-looking percentage, never silently promoted to READY (GF-AT-28), and never forced into a confirmed NOT_READY it was never proven to be. (c) Functional correctness ALWAYS outranks a performance PASS -- every gate's own AND-formula includes a `Functional_Correctness_Confirmed` term; because the fold is a strict AND (worst-wins, never averaged or weighted), a functionally-incorrect transaction blocks the WHOLE gate as NOT_READY regardless of how many performance conditions on that same gate read MET -- a hard precedence enforced by the fold's own arithmetic, never a score a high performance number could outweigh.

**Discipline matches this project's other composite-gate modules: worst-wins, never averaged.** A single UNMET condition blocks the WHOLE gate as NOT_READY regardless of how many other conditions on that gate are clean. Only once no condition is UNMET does an UNKNOWN/NOT_AVAILABLE condition -- or a condition nobody supplied evidence for at all -- make the gate `INCOMPLETE_EVIDENCE` rather than either READY or NOT_READY. An explicit, CALLER-DECLARED `NOT_APPLICABLE` outcome is supported for a project/path that is not performance-critical -- never inferred by this module from the condition list itself (there is no rule like "no performance conditions supplied means not applicable", which would silently read an unmeasured project as one with nothing to measure); it is only ever produced when the caller explicitly declares `not_applicable=True` with a real, non-empty `reason`.

`BUS_PERFORMANCE_SIGNOFF_READY`'s own AND-formula names `BUS_PERFORMANCE_READY` as one of its terms, exactly as `AMBA_TEST_GENERATION_READY` names three earlier gates in `amba_readiness_gates.py`: the two gates are evaluated in a fixed order (READY, then SIGNOFF_READY) so that sub-gate reference is already computed by the time it is needed, and an explicit caller-supplied condition record naming `BUS_PERFORMANCE_READY` directly always outranks the derived sub-gate verdict -- the same "real evidence outranks a derived value" precedence this project's Source Authority Order already applies everywhere else.

Proven by `dv_harness_tests/test_amba_performance_readiness_gates.py` (31 tests): the positive path for both gates; the worst-wins negative control (a single UNMET condition blocks the gate regardless of how many others are clean); the functional-correctness-outranks-performance headline proof; `INCOMPLETE_EVIDENCE` proven distinct from `NOT_READY` on an UNKNOWN/absent condition; the explicit caller-declared `NOT_APPLICABLE` path proven never self-inferred; and `BUS_PERFORMANCE_SIGNOFF_READY`'s sub-gate reference proven to use a caller override when supplied and the derived `BUS_PERFORMANCE_READY` value otherwise.

**Disclosed residual**: this module folds caller-supplied conditions only -- it derives no performance fact of its own, runs no build/regression/LSF submission, and references no approval/governance mechanism.



<!-- S174: moved verbatim from CLAUDE.md original lines 10221-10234 (M4.6 CLAUDE Context Normalization) -->
## AMBA Fabric Graph IR: Typed Multi-Node Topology + Multi-Path Route Enumeration (2026-09-06)

Every prior AMBA IR in this repo either models a whole fabric as a FLAT collection (the AMBA_PORT_REGISTRY's one row per port, amba_master_slave_constraint_ir.py's Batch 9 three-layer per-(master,slave) constraint record) or predicts a route's TRANSFORMS structurally (amba_route_transform_predictor.py's ten SYOSCB-12 responsibilities per (master, slave) pair, resolved through build_scoreboard_matrix()). None of them models the fabric's own internal STRUCTURE as a graph of typed components, and none of them can represent more than one physical route between one master and one slave without collapsing it to a single answer. dv_harness/amba_fabric_graph_ir.py is that missing layer, and it is deliberately NOT amba_master_slave_constraint_ir.py extended -- it is never imported, and that module's flat constraint-model shape is accepted only as a generic, unrelated caller parameter if a caller happens to hold one alongside a fabric graph.

AMBAFabricGraphIR: twelve real internal-fabric-component kinds, plus two endpoint kinds, all caller-declared and validated against a closed vocabulary. FABRIC_NODE_KINDS is exactly crossbar/arbiter/decoder/bridge/width_converter/id_converter/clock_converter/register_slice/firewall/address_translator/coherent_node/memory_controller -- the real set this domain's components come in, never inferred from an instance name or a protocol family, and an unrecognized kind is a hard AMBAFabricGraphError rather than a silent coercion to the nearest-sounding one. master_endpoint/slave_endpoint are modeled as a SEPARATE, smaller vocabulary (ENDPOINT_NODE_KINDS) rather than folded into the twelve, because "this node IS a crossbar" and "this node IS where a master's traffic enters the fabric" are different kinds of fact a reader must never confuse when reading a rendered node table. Every node and edge requires a real, non-empty evidence citation (NODE_WITHOUT_EVIDENCE/EDGE_WITHOUT_EVIDENCE), and an edge naming a node id the caller never declared is refused (EDGE_REFERENCES_UNKNOWN_NODE) rather than silently dropped.

The one hard rule this module exists to enforce: a reconfigurable/dynamic claim must be grounded in real evidence that reconfiguration actually exists, never inferred from a fabric protocol alone. assert_no_ungrounded_reconfigurable_claim() runs on every node before a graph is built and raises RECONFIGURABLE_CLAIM_WITHOUT_GROUNDED_EVIDENCE unless a node declaring reconfigurable: True (or dynamic: True) also cites at least one evidence item whose source_kind is a real register/RTL/spec/human-confirmation source (ALLOWED_RECONFIG_EVIDENCE_SOURCE_KINDS -- deliberately restated locally rather than imported from amba_master_slave_constraint_ir.py's own analogous DUT-evidence allowlist, since that module is off-limits to import from this batch). There is no soft downgrade path: an AXI decoder is never assumed reconfigurable merely because AXI decoders often are, the same "not a weaker confirmation, not confirmation at all" posture that module's own VIP-evidence rule already takes one layer down.

AMBAPathIR: every caller-declared route preserved, never collapsed. build_amba_path_ir() never traverses the graph to INVENT a route -- doing so would assert a route is real merely because the graph's edges make it topologically possible, exactly the routing guess amba_route_transform_predictor.py's own "Do not guess routing" already forbids one level up. A route is reported only because a caller declared one (a RouteFact: master_id/slave_id/an optional ordered hops list/a required, non-empty evidence), and when the caller's own real topology evidence names more than one distinct route for one (master, slave) pair, AMBAPathIR.paths_for() returns every one of them, in declaration order, never deduplicated or narrowed to one. assert_declared_multiplicity_preserved() is a structural self-check proving exactly that: the number of PathIR entries reported for a pair equals the number of route facts the caller declared for it. A route's own hop sequence, when supplied alongside a real graph, is cross-checked against the graph's real edges -- a disagreement is reported as INCONSISTENT_WITH_GRAPH, citing exactly which hop or hop-pair the graph does not actually connect, and is never a reason to silently trust the route or to drop it from the report; a route with no hops, or no graph supplied at all, is honestly CONSISTENCY_NOT_CHECKED rather than a fabricated pass.

Phase-1 only: this module builds an IR a human/generator reads. It runs no build, no simulation, and mints no approval; there is deliberately no stage gate. It reuses connectivity.render_markdown_table() for both its node/edge report and its route-enumeration report rather than a third hand-rolled table renderer.

Proven by dv_harness_tests/test_amba_fabric_graph_ir.py (20 tests): the full twelve-kind vocabulary and an unknown-kind refusal; a real multi-node graph spanning several kinds; five construction-time negative controls (no evidence on a node/edge, an edge referencing an undeclared node, a duplicate node id, a node with no id); the headline reconfigurable-claim rule proven both ways (an ungrounded claim refused, a claim grounded in a real register-field citation accepted, and the dynamic alias checked identically); and the multi-path family -- two genuinely distinct declared routes for one pair both preserved with correct hop sequences and consistency status, a single-route pair reporting exactly one path, an unqueried pair reporting zero rather than erroring, a route with hops the graph does not connect reported as a finding but still preserved, a route naming a node absent from the graph likewise reported, and a deliberately-broken build proving assert_declared_multiplicity_preserved() has real detection power against an actual collapse.


<!-- S175: moved verbatim from CLAUDE.md original lines 10235-10315 (M4.6 CLAUDE Context Normalization) -->
## Ordering-Domain Graph: Real Nodes, Real Domains, Declared Preservation Edges Only (2026-09-06)

Nothing in this repo modeled an ordering domain as a first-class object with real membership and
real relationships to OTHER domains. `amba_route_transform_predictor.detect_ordering_domain()`
already answers a narrower, PER-ROUTE question -- given one (master, slave) pair, is that one
route's own transaction stream in-order or out-of-order, decided from whether the protocol carries
a transaction id. It has no notion of a domain as a named, evidenced object with membership, and no
notion of a relationship BETWEEN two domains: "does domain A's completion order say anything about
domain B's". `arbitration_policy_ir.py` (Batch 9, deliberately not imported here) answers yet
another different question -- a fabric's flat, per-arbiter ARBITRATION SCHEME classified from
evidence text, never a cross-domain ordering relationship. A repo-wide grep
(`ordering_domain_graph`/`OrderingDomainGraph`/`preservation_edge`) returned zero hits before this
module.

`dv_harness/ordering_domain_graph.py` is that graph: which real ordering domains exist, which real
node/master belongs to which domain, and which declared, DIRECTED ordering-preservation
relationship holds between two domains -- built strictly from caller-supplied, evidence-cited
facts, never inferred from a fabric protocol name, a topology shape, or a naming convention.

**The Evidence Truth Rule, applied literally to every one of the three declaration shapes.** A
domain (`OrderingDomain`: `domain_id` + mandatory `evidence`), a node-to-domain membership
(`NodeMembership`: `node_id`/`domain_id` + mandatory `evidence`), and a directed preservation edge
(`PreservationEdge`: `from_domain`/`to_domain`/`preservation` in `{PRESERVED, NOT_PRESERVED,
UNKNOWN}` + mandatory `evidence`) all REFUSE construction (`OrderingDomainGraphError`) with no
citation -- the same discipline `security_policy_ir.py` already applies to an uncited access rule.
A domain declaring `reconfigurable=True` (its membership/scope can change at runtime) additionally
REQUIRES a separately-cited `reconfiguration_evidence` naming the real control mechanism -- a
register field, a documented mode switch -- and is refused otherwise. This is the module's own
governing rule, enforced at the dataclass's own construction boundary rather than left as prose: a
"reconfigurable"/"dynamic" claim must never be inferred from a fabric protocol family alone.

**Two conflicting evidence shapes, both surfaced rather than resolved.** A node declared a member
of more than one domain is not an error -- a bridge component genuinely can sit in two ordering
domains at once -- but it is always a recorded `MULTI_DOMAIN_MEMBERSHIP` finding, since a comparison
touching that node must consider every one of its domains, never only one.
`assert_predictions_complete`-style completeness is applied the other way for edges: two
declarations of the SAME directed `(from_domain, to_domain)` pair disagreeing on their preservation
value is a real `CONTRADICTORY_EDGE` finding, and the resolved edge reads UNKNOWN citing both sides
-- this module never arbitrates which declaration is correct, the same ARBITRATION boundary
`requirement_contract.py`/`design_knowledge_correlation.py`/`security_policy_ir.py` already keep
for their own conflicting-claim findings.

**Queries refuse to fabricate a guarantee nobody declared.** `query_domain_preservation()` answers
"does ordering preservation hold from A into B" only from a directly-declared edge in that exact
direction: it never infers the reverse direction from a forward declaration (a bridge can easily
preserve order one way and reorder the other), and it never computes a transitive answer across
three or more domains (A preserving into B and B preserving into C does not imply A preserves into
C -- that would be an additional fact about the compare/merge stage between B and C nobody
declared). Both refusals are proven by dedicated negative-control tests, since a fabricated
transitive/reverse guarantee is exactly the confident-wrong-answer failure mode this module exists
to prevent. `query_node_pair_ordering()` sweeps every declared-domain pairing between two nodes
(covering the multi-domain-membership case honestly) and reports `UNKNOWN_NODE` for a node with no
declared membership at all, never a guessed relationship.

**Reuse / file-safety.** This module imports nothing from `arbitration_policy_ir.py` and nothing
from any other new module in this batch (verified by AST inspection at build time); it reuses only
`dv_harness.connectivity.render_markdown_table()` (this repo's one parameterized table renderer,
pre-existing outside this batch) for its optional markdown rendering, and `dv_harness.models.Status`
solely to assert this module's own vocabulary (preservation values, finding kinds, query statuses)
shares no token with a real stage verdict (`assert_no_verification_verdict_vocabulary()`, run at
import).

**Deliberately bounded.** It discovers no fabric topology, port, or master/slave fact of its own --
node identity is a caller's own AMBA-family discovery pipeline's job; it never computes a
reorder-window depth or an outstanding-transaction bound; it decides, approves and arbitrates
nothing: no build, job, or approval is touched, and there is deliberately no stage gate and no
`dv-harness` CLI verb (`cli.py`/`gates.py` untouched, per this batch's file-safety scope) -- the
front door is the module's own Python API plus a small `python -m
dv_harness.ordering_domain_graph --facts-file <file.json> [--json]` reporting wrapper.

Proven by `dv_harness_tests/test_ordering_domain_graph.py` (33 tests): the core positive
build/query path (domain membership, multi-domain-membership finding, reconfigurable-domain
grounding); orphan-domain and self-loop-edge findings; the headline
"reconfigurable-without-grounding-evidence is refused" negative control and its blank-string
sibling; five further uncited-declaration refusals (domain, membership, edge, an unrecognized
preservation value, a duplicate domain id); a real contradictory-edge case proven reported (never
arbitrated) with the resolved edge reading UNKNOWN citing both sides; the no-reverse/no-transitivity
proof for `query_domain_preservation()`; honest `UNKNOWN_DOMAIN`/`UNKNOWN_NODE`/`NO_DOMAIN_DECLARED`
results for every query against something never declared; a JSON round-trip proof; and CLI
subprocess invocations (JSON and markdown output, exit code).


<!-- S176: moved verbatim from CLAUDE.md original lines 10316-10381 (M4.6 CLAUDE Context Normalization) -->
## Address-Map Integrity Checker: Overlap / Unmapped-Hole / Illegal-Burst Arithmetic (2026-09-06)

This project's existing AMBA-23 mechanism (`uvm_generator/amba_fabric_generator.
compute_address_regions()`, "the ONLY overlap / gap / full-coverage validator used")
was read first, per REUSE OVER REINVENT, and confirmed genuinely unfit for this task's own
scope: it is a GENERATION-TIME validator that RAISES on the FIRST overlap/gap it finds (one
finding, never a full report) and REQUIRES the region set to cover the entire
`[0, 2**addr_width)` address space -- correct discipline for a generator that must never emit
a topology with a silently-unmapped residual region, wrong for a caller-declared address map
that may legitimately have reserved gaps and needs every finding reported at once, not just
the first. Nothing in this repo modeled illegal-transfer legality (a burst crossing a 4KB
boundary, or crossing a declared protocol-region boundary) at all. `dv_harness/
address_map_integrity_checker.py` is a deliberately SEPARATE module for this narrower, pure-
arithmetic question, reusing only `amba_fabric_generator.parse_addr()` for address-string
parsing (int, or an optionally underscore-grouped, optionally 0x/0b-prefixed string) so this
module cannot silently parse an address differently from the rest of the AMBA family.

**Three checks, matching the task's own three items, every finding citing the real values that
triggered it.** (a) `check_overlaps()` -- pairwise interval intersection over all declared
regions, each finding carrying both real regions (owner/base/size/end) and the real
overlapping sub-range -- never a generic "overlap exists". (b) `check_unmapped_holes()` --
regions are merged via a running-max-end coverage merge (so a large region fully containing a
smaller declared one never manufactures a phantom hole against it, unlike a naive
adjacent-pair scan); every real gap between merged coverage groups cites the real bounding
region on each side (`region_before`/`region_after`, `None` only at the true start/end of a
declared `address_space_bits` span). (c) `check_transfer_legality()` -- a caller-declared
transaction (`address` plus `length`, or `burst_len`+`beat_size`) is checked against both a
4KB-boundary crossing (the real AMBA AXI/AHB rule that a single burst must never cross a 4KB
address boundary) and a declared PROTOCOL-REGION boundary crossing, grouped by each region's
own `protocol_region` field (defaulting to that region's `owner` when undeclared, so two
regions of one owner but different bus segments are never silently merged, and two regions
sharing one DECLARED protocol region -- e.g. two banks of one memory -- are correctly never
flagged just for having different owners).

**Evidence Truth Rule, applied to a domain with no UNKNOWN/NOT_AVAILABLE vocabulary of its
own.** A transaction whose target range touches no declared region at all, or only PART of its
range, is reported as the honest, distinct `TRANSFER_TARGETS_UNMAPPED_ADDRESS` /
`TRANSFER_PARTIALLY_UNMAPPED` finding -- never silently assumed legal, since "legal" is a claim
this module must never make without a real declared region to check against. A region or
transaction missing a required field (owner, base, size, a resolvable length, a parseable
address) is refused outright (`AddressMapIntegrityError`, fail-closed) rather than silently
defaulted or guessed. An explicitly empty region list is legal (an honest "nothing declared
yet" state, distinct from `regions=None`, which is refused as nothing having been supplied at
all).

`analyze_address_map(regions, transactions=None, address_space_bits=None)` is the one entry
point, folding `status` to `FAIL` iff a real overlap or illegal-transfer finding exists;
unmapped holes are always reported but never force `FAIL` on their own, since a declared gap
(reserved space) is a normal engineering fact, not a defect.

**Deliberately bounded, and stated rather than implied closed.** No RTL/VIP discovery, no
fabric-topology derivation, and no performance/timing value of any kind are computed here --
all out of scope for this whole batch. There is no `dv-harness` CLI verb and no `gates.py`
entry (out of this task's own file-safety scope); the front door is the module's own Python
API.

Proven by `dv_harness_tests/test_address_map_integrity_checker.py` (28 tests): positive paths
for all three checks (including the negative control that two owners sharing one declared
protocol region are never flagged crossing it, and that a large containing region never
manufactures a phantom hole against a region it fully covers); the two honest-unmapped-address
tests (a transaction touching nothing declared, and one only partially covered, both reported
rather than assumed legal); 7 negative controls for malformed region/transaction input; and 4
tests on the combined `analyze_address_map()` entry point including its `render_text()`
rendering. `python -m pytest dv_harness_tests/test_address_map_integrity_checker.py -q` ->
`28 passed`.


<!-- S177: moved verbatim from CLAUDE.md original lines 10382-10391 (M4.6 CLAUDE Context Normalization) -->
## Dynamic Connectivity IR: Runtime-Reconfigurable Routing, Never Inferred From the Fabric Being AMBA (2026-09-06)

Batch 9's real AMBA/SyoSil family already models connectivity STRUCTURALLY and once, as discovered: `amba_fabric_discovery.py`/`amba_port_registry.py` establish which master/slave ports exist and how they bind; `amba_route_transform_predictor.py` (SYOSCB-12/13) then predicts, from that fixed topology, whether a route exists and what transform the topology implies along it (ID extension, width conversion, burst split/merge, bridge behavior, ordering domain). None of it asks whether the fabric's own address decode or route selection can CHANGE while the design runs -- every prediction is over a single, fixed decode the harness read once. `dv_harness/dynamic_connectivity_ir.py` is a DynamicConnectivityIR for exactly that missing question, kept deliberately separate: it imports nothing from the AMBA/SyoSil family or from any other new module in this same batch -- only `connectivity.render_markdown_table()` (the repo's one parameterized table renderer) and `models.Status` (for the vocabulary-disjointness check several sibling modules already run against it).

**The fabrication-risk rule is enforced two layers deep, not merely stated.** `classify_path_reconfigurability()` takes only two evidence records per path -- a `ControllingMechanism` (a real register/field name plus a REQUIRED, non-empty evidence citation; construction raises `DynamicConnectivityIRError` on an empty citation, the same "a rule with no evidence citation is refused outright" discipline `security_policy_ir.AccessRule` already applies) and/or a `StaticRoutingClaim` (the symmetric cited "this path is fixed" claim) -- and never accepts a protocol/fabric-name parameter at all, so a path's declared `protocol` field can never influence its classification (proven directly: identical evidence under five different declared protocol strings, including `"AXI4"`, produces byte-identical results). A declared mechanism is promoted to `RECONFIGURABLE_CONFIRMED` only when its OWN evidence text matches a closed, literal phrase list stating it actually controls routing/decode (`"controls address decode"`, `"selects the destination slave"`, ...) -- a mechanism whose evidence names an unrelated register (an IRQ mask, say) is refused and reported `UNKNOWN_MECHANISM_NOT_EVIDENCED_AS_ROUTING_CONTROL` rather than promoted on the strength of the caller's own label, mirroring `arbitration_policy_ir.classify_arbitration_scheme()`'s "never from a name alone" discipline. The symmetric rule holds for `STATIC_CONFIRMED`. With neither evidence type supplied, the result is `UNKNOWN_NO_EVIDENCE` -- never defaulted to static or dynamic on the strength of the fabric being an AMBA fabric in general. Declaring BOTH a mechanism and a static claim for one path is `AMBIGUOUS_CONFLICTING_EVIDENCE`; this module never arbitrates which side wins, the same boundary `security_policy_ir.classify_access()` keeps for a same-specificity rule conflict.

`DynamicConnectivityPath`/`DynamicConnectivityIR` wrap the classifier into a full model over caller-declared, duck-typed path dicts (`build_dynamic_connectivity_paths()`/`build_dynamic_connectivity_ir()`), with `to_dict()`/`to_row()`/`summary()`/`render_markdown()` and a `python -m dv_harness.dynamic_connectivity_ir statuses|classify` front door (exit 0 every path resolved, 1 any UNKNOWN/AMBIGUOUS, 2 malformed input) -- no `dv-harness` CLI verb was added and `gates.py`/`cli.py` were untouched, per this task's own file-safety scope. It decides, approves, and arbitrates nothing beyond its own classification: no build, no job, no approval, and there is deliberately no stage gate.

Proven by `dv_harness_tests/test_dynamic_connectivity_ir.py` (24 tests): the core positive path for both `RECONFIGURABLE_CONFIRMED` and `STATIC_CONFIRMED`; the headline no-evidence-never-defaulted test and its path-level counterpart; the protocol-never-consulted test across five declared protocols including the task's own named "AMBA fabric alone" scenario; both "declared but not evidenced" negative controls (an unrelated register, an unrelated static citation); the both-declared conflict; five construction-refusal tests (empty evidence, empty register name, empty path identity fields); `build_dynamic_connectivity_paths()`'s mixed-status batch build, malformed-index reporting, and non-list refusal; markdown rendering including the empty-IR honest-note case; and all three CLI exit codes.


<!-- S178: moved verbatim from CLAUDE.md original lines 10392-10407 (M4.6 CLAUDE Context Normalization) -->
## Transaction Correlation IR: Response Matching, Data-Beat Association, Burst Split/Merge Linkage, and Logical Transaction Reconstruction (2026-09-06, extended 2026-09-06 for SYOSCB-11)

`amba_transaction_ir.py` (SYOSCB-10) already gives one AMBA transaction a typed shape -- `transaction_id`, `original_id`, `fabric_id`, `sequence_number`, `route_id` -- and `amba_route_transform_predictor.py` (SYOSCB-12) already DETECTS, per route, whether the topology implies a burst split or merge (`detect_burst_split_merge()`) from a width-conversion/protocol-applicability comparison of the two ends. Both were read first, read-only, before writing a line of this module, and neither tracks a CROSS-TRANSACTION link: the IR gives one transaction fields to CARRY an id, never says which OTHER transaction record shares it or which response record answers which request record; the predictor says a route implies a split/merge EVENT, never says which of the real sub-transactions later observed on that route are that event's actual children. `dv_harness/transaction_correlation_ir.py` is the correlation/bookkeeping layer that sits on top of both, and reuses rather than reimplements either -- `BURST_SPLIT`/`BURST_MERGE`/`BURST_SPLIT_TO_SINGLE_TRANSFERS`/`TRANSFORM_PREDICTED_FROM_TOPOLOGY` are imported directly from `amba_route_transform_predictor.py` so there is exactly one spelling of "what kind of split/merge event this is" in this repo, and its detection logic is never duplicated: this module only accepts a caller-supplied detected event (typically that function's own return shape) and correlates real, already-observed sub-transactions against it.

**Three mechanisms, each gated by a real evidence citation.** Every request/response/data-beat/sub-transaction record must carry a non-empty `evidence` list or the module refuses to build a decision from it (`TransactionCorrelationIRError`) -- a correlation decision is never built from an uncited record, and never from a component/port name or a plausible-looking default.

- `correlate_responses(requests, responses)` groups by `(scope, transaction_id)` -- `scope` is a caller-declared channel/route key so two unrelated ports sharing one bare id value, or two protocols carrying no id at all (every item's `transaction_id` is `None`), are never cross-matched -- and, within a group holding more than one still-open item, matches strictly by ascending `sequence_number`: the real AMBA rule that transactions sharing one id complete in FIFO issue order. A group missing `sequence_number` on more than one still-open member cannot be safely ordered and is reported `RESPONSE_AMBIGUOUS_ORDER_WITHIN_ID_GROUP` rather than matched by list position. A response with no outstanding request in its group is `RESPONSE_UNMATCHED_NO_OUTSTANDING_REQUEST`; a request with no response yet is `REQUEST_PENDING_NO_RESPONSE_YET`.
- `associate_data_beats(transactions, data_beats)` joins beats to a transaction by a real shared per-beat id when the caller supplies one (AXI3's WID-style), or by a persistent per-scope FIFO cursor when beats carry none at all (AXI4's W channel). A transaction declaring no `expected_beat_count` can never be judged "full" by counting alone, so it permanently blocks its FIFO queue -- every beat that would otherwise queue behind it is honestly `BEAT_UNKNOWN_TRANSACTION_LENGTH` rather than guessed onto the next transaction in program order (the cursor never advances past a length-unknown target). Per-transaction rollup reports `DATA_ASSOCIATION_COMPLETE`/`PARTIAL`/`EXCESS_BEATS`/`UNKNOWN_LENGTH`/`NO_BEATS_OBSERVED`.
- `link_burst_split_merge(detected_event, parent_transaction, child_transactions)` links real observed children back to a parent by plain address-tiling arithmetic over each record's own `address`/`total_bytes` -- contiguous coverage of the parent's `[address, address+total_bytes)` range, count checked against the event's own `beat_count_factor` when the predictor supplied one -- never by trusting an unverified shared correlation-key string. An event whose own `status` is not `TRANSFORM_PREDICTED_FROM_TOPOLOGY`, or whose `kind` is none of the three split/merge kinds this repo recognizes, is honestly `LINKAGE_NOT_APPLICABLE`: this module never attempts to link children to an event that never claimed a split/merge in the first place. Reports `LINKAGE_CONFIRMED`/`PARTIAL_ADDRESS_RANGE_NOT_FULLY_COVERED`/`CONFLICT`/`INSUFFICIENT_EVIDENCE`/`NOT_APPLICABLE`.

**SYOSCB-11 (2026-09-06): a fourth mechanism, purely additive, closing the one real gap a verify-first pass found in the three above.** The assigned item asked for "reconstructing a full logical AXI transaction from split beats/responses as ONE record." Mechanisms (1) and (2) above already do the real correlation WORK that needs -- matching a response to its request, and associating every data beat to its transaction -- but neither, nor mechanism (3), ever produced a SINGLE combined record answering "what do we currently know about this one logical transaction, end to end"; a caller had to run all three separately and cross-reference their outputs by hand. `reconstruct_logical_transactions(transaction_records, response_entries, data_report, burst_linkage_by_ref=None)` closes exactly that composition gap and nothing more: it is a pure JOIN over records the caller has already correlated with the three existing functions -- it re-derives no correlation decision of its own, and never claims a transaction is complete on any dimension it was not handed real, already-computed evidence for. Each `transaction_records` entry carries a `transaction_ref` (joined against `data_report`'s own `TransactionDataAssociation.transaction_ref`) and a `request_ref` (joined against `response_entries`' own `ResponseCorrelationEntry.request_ref`), plus the same required `evidence` citation every other record in this module needs. The composed `LogicalAxiTransactionIR.status` is the WORST (least-complete) of the real statuses it was built from, never a guess: `LOGICAL_TXN_RESPONSE_AMBIGUOUS_ORDER`/`LOGICAL_TXN_PENDING_NO_RESPONSE_YET` outrank data completeness; `LOGICAL_TXN_UNKNOWN_DATA_LENGTH`/`LOGICAL_TXN_EXCESS_DATA_BEATS`/`LOGICAL_TXN_PARTIAL_DATA` outrank a caller-supplied burst-linkage verdict; an optional `burst_linkage_by_ref` entry (typically `link_burst_split_merge()`'s own return value for a transaction that is itself a declared split/merge parent -- its `parent_ref` is cross-checked to match, a mismatch is refused as a caller data-integrity defect) that is neither `LINKAGE_CONFIRMED` nor `LINKAGE_NOT_APPLICABLE` reports `LOGICAL_TXN_BURST_LINKAGE_UNCONFIRMED` rather than letting a real open linkage question hide inside an otherwise-clean record. A transaction whose declared refs resolve to NEITHER a real response-correlation entry NOR a real data-association entry is honestly `LOGICAL_TXN_INSUFFICIENT_EVIDENCE`, naming exactly which half is missing, rather than silently reported complete or dropped. Only `LOGICAL_TXN_COMPLETE` requires every joined dimension to have genuinely resolved clean.

**Deliberately bounded, and stated rather than implied closed.** It does not discover fabric topology, ports, or protocols (`amba_fabric_discovery.py`/`amba_port_registry.py`'s job); it does not decide whether a route implies a split/merge at all (`amba_route_transform_predictor.py`'s job, called by the caller before this module ever runs); it does not read RTL, a waveform, or a sim.log itself -- every record is a plain, caller-supplied fact; it writes nothing, gates nothing, and approves nothing, and there is deliberately no stage gate. No `dv-harness` CLI verb was added (`cli.py` untouched, per this batch's file-safety scope); the front door is `python -m dv_harness.transaction_correlation_ir {responses|data|linkage|reconstruct}`.

Proven by `dv_harness_tests/test_transaction_correlation_ir.py` (45 tests, up from 30): response correlation's FIFO-by-id matching (including the no-id-protocol case and two-scope isolation) plus its ambiguous-order negative control; data association's beat-id and no-id FIFO paths plus the unknown-length permanent-blocking negative control (the one genuine logic defect this TDD pass caught and fixed: an earlier draft wrongly let the FIFO cursor advance past a length-unknown transaction instead of blocking every subsequent beat behind it); burst linkage's CONFIRMED/PARTIAL/CONFLICT/INSUFFICIENT_EVIDENCE/NOT_APPLICABLE paths, including one test that drives the REAL `amba_route_transform_predictor.detect_width_conversion()`/`detect_burst_split_merge()` over a genuine AXI4 128-bit-to-32-bit downsize to produce an authentic `BURST_SPLIT` event (factor=4) before linking it against synthetic address-tiled children, and a companion test proving `LINKAGE_NOT_APPLICABLE` against that same predictor's real `TRANSFORM_NOT_IMPLIED` result for a same-width route; and (SYOSCB-11) `TestLogicalTransactionReconstruction`'s 15 tests -- a complete record joining a real matched response and a real complete data association with the real union of every contributing evidence citation; the pending-outranks-complete-data precedence proof; ambiguous-order surfaced rather than resolved; partial/unknown-length/excess-data data statuses each reported (the excess-beat case is exercised against a directly-constructed `DataAssociationReport`, since `associate_data_beats()`'s own FIFO cursor never actually lets a real `got > expected` rollup occur, confirmed against section 2's own `test_excess_beats_reported_never_silently_accepted`); a confirmed burst-parent linkage folded into a COMPLETE record and an unconfirmed one blocking completeness even with a matched response and complete data; the burst-linkage parent-ref-mismatch refusal; both insufficient-evidence negative controls (no response-correlation entry, no data-association entry); duplicate-ref and missing-evidence refusals; report rendering including the empty-list case; and a real `python -m dv_harness.transaction_correlation_ir reconstruct` CLI subprocess run end to end.


<!-- S179: moved verbatim from CLAUDE.md original lines 10408-10421 (M4.6 CLAUDE Context Normalization) -->
## Outstanding Capability IR: a Granular Structural Breakdown, Never a Guessed Limit (2026-09-06)

Batch 9's `amba_master_slave_constraint_ir.py` models AMBA outstanding-transaction legality as ONE of its six fixed protocol-legal/DUT-capability/scenario-constraint dimensions -- a single flat `outstanding` notion inside that module's three-layer model. It never asked the more granular questions a real fabric/port capability record needs answered separately: is the limit different for reads vs writes, is there a per-ID cap distinct from a global in-flight cap, what does the SLAVE side accept (which can differ from what a master issues), what does the FABRIC itself impose (often tighter than either endpoint), and what does an intervening BRIDGE impose (a width-conversion/protocol-bridge stage frequently caps outstanding depth independently of both endpoints -- the exact class of behavior `amba_route_transform_predictor.py` already detects at the route level, though this module does not import or re-derive that detection; it only reserves a field a caller populates once such an analysis confirms a bridge exists).

`dv_harness/outstanding_capability_ir.py` is that finer-grained structural breakdown: `OutstandingCapabilityIR` over seven independent fields -- `read_max`, `write_max`, `per_id_limit`, `global_limit`, `slave_accept_limit`, `fabric_limit`, `bridge_limit`. Per this batch's strict file-safety scope it is a STANDALONE structure and does not import `amba_master_slave_constraint_ir.py` or any other new-batch module -- a caller already holding both IRs may cross-reference them at the call site (e.g. treating this module's finer fields as a refinement of that module's flat `outstanding` dimension for the same master/slave pair); this module performs no such cross-reference itself.

**Every field defaults to UNKNOWN/NOT_AVAILABLE -- never a guessed limit, enforced at construction rather than merely documented.** Three statuses are kept honestly distinct: `OUTSTANDING_CAPABILITY_UNKNOWN` (nobody has ever supplied evidence for this field -- the default), `OUTSTANDING_CAPABILITY_NOT_AVAILABLE` (evidence was genuinely sought and could not be confirmed -- requires its own real, non-empty reason string, refused otherwise), and `OUTSTANDING_CAPABILITY_CONFIRMED` (a real integer value backed by a non-empty evidence citation AND a recognized evidence kind -- `rtl_parameter`/`rtl_port`/`register_map`/`register_field`/`spec_document`/`programming_guide`/`human_confirmation`). A numeric value supplied with no citation, a non-integer or negative value, or an unrecognized evidence kind (e.g. a VIP example or manual) all raise `OutstandingCapabilityError` at construction -- an uncited outstanding-transaction limit is exactly the unsupported claim the Evidence Truth Rule forbids, and this module never accepts one silently.

`build_outstanding_capability_ir(field_inputs=...)` is the sanctioned constructor (never build the frozen dataclass by hand): each of the seven field names maps to `None`/`"UNKNOWN"` (stays UNKNOWN), a `{"status": "NOT_AVAILABLE", "reason": ...}` dict, or a `{"value": <int>, "evidence": ..., "evidence_kind": ...}` dict. `render_outstanding_capability_markdown()` reuses `connectivity.render_markdown_table()` -- this repo's one parameterized table renderer -- rather than a second hand-rolled table loop.

**Deliberately bounded, and stated rather than implied closed.** It builds a structured capability record a human/generator reads; it runs no build, no simulation, and mints no approval, and there is deliberately no stage gate -- a gate that passed on a capability record nobody supplied real evidence for would be worse than none. It performs no RTL/spec parsing itself and imports nothing from any other new module in this batch, so it stays usable regardless of which future extractor eventually produces the per-field evidence it validates.

Proven by `dv_harness_tests/test_outstanding_capability_ir.py` (23 tests): the default-all-UNKNOWN core positive path; real CONFIRMED-field construction across every recognized evidence kind; NOT_AVAILABLE proven distinct from UNKNOWN via separate accessor buckets (`unknown_fields()`/`not_available_fields()`); markdown rendering and `to_dict()` shape; and the required negative controls proving the module refuses to fabricate a limit -- missing evidence, an unrecognized evidence kind, a non-integer or bool or negative value, a bare NOT_AVAILABLE with no reason, an unknown field name (both at construction and via `field_by_name()`), a malformed field-spec shape, and a non-mapping `field_inputs` argument. Run: `python -m pytest dv_harness_tests/test_outstanding_capability_ir.py -q` -> `23 passed`.


<!-- S180: moved verbatim from CLAUDE.md original lines 10422-10435 (M4.6 CLAUDE Context Normalization) -->
## Backpressure Model: Legal Stall Tolerance, from Literal Cited Evidence Only (2026-09-06)

`design_intent.py` already models `backpressure_conditions` -- a documented, citation-required list of conditions under which backpressure/stalling is LEGAL AT ALL (a boolean per named condition: "is stalling here permitted, yes/no, per this spec section"). Nothing in this repo answered the adjacent, narrower quantitative question a scoreboard/checker actually needs next: GIVEN that a stall is legal on this named channel, HOW LONG may it legally last -- a bounded number of cycles/wait-states, or an explicitly unbounded stall the spec/RTL evidence permits -- and whether a caller-supplied OBSERVED worst-case stall stays within that bound. A repo-wide grep for `stall_tolerance`/`legal_backpressure`/`BackpressureToleranceIR` returned zero hits before this module. The real AMBA/SyoSil family (`amba_fabric_discovery.py`, `amba_port_registry.py`, `amba_fabric_analysis.py`, `amba_transaction_ir.py`, `amba_route_transform_predictor.py`, `amba_scoreboard_env.py`) discovers fabric topology, ports, transactions and route transforms -- none classifies a channel's legal stall duration, and this session's own `arbitration_policy_ir.py` classifies an ARBITER's scheme/starvation risk, a different concern (who gets granted next, not how long a handshake channel may legally hold VALID/READY apart). `dv_harness/backpressure_model.py` is that missing classifier.

**The Evidence Truth Rule, applied literally.** A channel's tolerance is classified ONLY from real evidence TEXT the caller supplies (an RTL comment, a protocol/programming-guide paragraph, a register/timing-spec sentence) -- never from the CHANNEL NAME alone. `AXI_AW`/`AHB_HREADY`/`APB_PREADY`/`GENERIC_VALID_READY` are fixed, exhaustive labels this module classifies against; none carries an assumed legal-stall duration from the protocol's own general reputation (e.g. "AXI READY may always be held low indefinitely" is a real architectural fact about some AMBA protocols, but this module refuses to assert it unless the caller's own supplied evidence text states it for THIS channel) -- proven directly by a dedicated negative-control test: a channel literally named `AXI_AW` with no supplied evidence text classifies `NOT_AVAILABLE`, never a guessed `UNBOUNDED`. Evidence text matching neither a bounded nor an unbounded phrase is honestly `NOT_AVAILABLE`. Evidence citing BOTH a bounded stall AND an unbounded stall for the same channel (no containment relationship between the two claims) is honestly `AMBIGUOUS`, naming both matched phrases, rather than picking one.

**Classification is a literal phrase match, not a keyword/name heuristic** -- the same discipline `arbitration_policy_ir.classify_arbitration_scheme()` already applies to its own five-scheme vocabulary, reused here for the two-class BOUNDED/UNBOUNDED vocabulary. `BOUNDED_STALL_PATTERNS` are a small, fixed list of literal, case-insensitive regex phrases capturing a real declared integer cycle/wait-state count (e.g. "maximum stall of N cycles", "must assert READY within N cycles", "up to N wait states", "stall no more than N clock cycles"). `UNBOUNDED_STALL_PHRASES` are a small, fixed list of literal phrases stating no bound exists (e.g. "may stall indefinitely", "no bound on the number of wait states", "unbounded backpressure is legal"). Text using different wording is honestly `NOT_AVAILABLE` rather than guessed via a broader keyword scan -- narrower recognition is the deliberate, disclosed trade for never fabricating a tolerance the evidence does not literally state.

**Stall-violation detection never invents an observed value.** `detect_stall_violation()` compares a `ChannelToleranceResult` already classified from real evidence against a caller-DECLARED observed worst-case stall duration (a real simulation/waveform measurement, or a formal-proof/documented worst-case figure; this module performs none of those measurements itself and never derives this number). A `NOT_AVAILABLE`/`AMBIGUOUS` tolerance can never judge a violation (honestly `UNKNOWN` -- there is no resolved bound, or two disagreeing claims, to compare against); an `UNBOUNDED` tolerance can never be violated by construction (`WITHIN_TOLERANCE`, since no bound exists to exceed); a `BOUNDED` tolerance compares the caller's real observed figure against the extracted cycle count -- within it is `WITHIN_TOLERANCE`, exceeding it is `VIOLATION`. An absent observed value against a resolved bound is `UNKNOWN`, never assumed compliant.

Proven by `dv_harness_tests/test_backpressure_model.py` (29 tests): each of the four fixed channel labels is proven classified from real cited bounded and unbounded phrases; the channel-name-alone negative control (`AXI_AW` with no evidence text stays `NOT_AVAILABLE`); the `AMBIGUOUS` dual-claim case; violation detection proven on both `WITHIN_TOLERANCE` and `VIOLATION` from real caller-declared observed figures, plus `UNKNOWN`/`WITHIN_TOLERANCE`-by-construction on `NOT_AVAILABLE`/`AMBIGUOUS`/`UNBOUNDED` tolerances respectively.

**Disclosed residual**: this module classifies from caller-supplied evidence TEXT only -- it performs no RTL parsing, no waveform measurement, and no simulation of its own, and references no approval/governance mechanism.


<!-- S181: moved verbatim from CLAUDE.md original lines 10436-10445 (M4.6 CLAUDE Context Normalization) -->
## Verification Boundary IR: 10-Class Taxonomy + Cited 7-Role Ownership (2026-09-06)

Nothing in this repo modeled a verification BOUNDARY as a first-class, taxonomized object carrying its own ownership record. The closest-looking mechanisms answer different, narrower questions: `amba_scoreboard_env.py`'s `ENV_ROLE_SCOREBOARD`/`ENV_ROLE_SUBSCRIBER`/`ENV_ROLE_PREDICTOR`/... is a UVM-component-ROLE vocabulary scoped to which class plays which role INSIDE one generated AMBA scoreboard's own component tree -- never a per-boundary ownership record across seven fixed named responsibilities, and never a 10-value boundary-class taxonomy at all; `verification_architecture.py`'s `CheckerIR`/`ScoreboardIR`/`VipBindIR`/`VipSelectionIR`/`AssertionIR` extend other real producers' own dict shapes with placement/confidence facts (is THIS checker correctly bound and linked), a different question from "what class of boundary is this, and who -- cited -- owns each of its seven fixed responsibilities". `dv_harness/verification_boundary_ir.py` is that missing layer.

**Classification, and ownership, both require a real citation -- enforced at construction, never merely documented.** A boundary's `boundary_class` (one of the fixed `EXTERNAL_PROTOCOL`/`REGISTER_CSR`/`DMA`/`INTERRUPT`/`CLOCK_RESET`/`MEMORY_MAPPED`/`COHERENT`/`POWER_DOMAIN`/`DEBUG`/`INTERNAL_FUNCTIONAL` values) requires a real, non-empty `class_evidence` citation -- `build_verification_boundary_ir()` refuses (`VerificationBoundaryIrError`) to construct an IR without one, the same "an uncited claim is refused outright" discipline `security_policy_ir.AccessRule` and `arbitration_policy_ir.classify_arbitration_scheme()` already apply to their own domains, independently re-applied here rather than imported (per this task's own instruction, neither sibling module is imported). Each of the 7 fixed roles (`active_driver`, `monitor`, `predictor`, `checker`, `scoreboard`, `coverage_owner`, `performance_owner`) is populated ONLY from a caller-declared `owner` plus its own real, non-empty `evidence` citation; an owner declared with no citation (or with only whitespace) is refused the same way. A role nobody has cited an owner for -- the honest common case for a project mid-intake -- reports `ROLE_UNKNOWN`: never defaulted to a literal `"none"` string, and never guessed from the boundary's own class (a `DEBUG` boundary is never assumed to lack a `performance_owner` just because that seems plausible for a debug interface -- proven directly by a dedicated test that cites a real owner for exactly that role/class pairing and confirms it is honored once cited).

**Deliberately bounded, and stated rather than implied closed.** It classifies a boundary and records ownership; it never arbitrates a conflicting ownership claim (two callers citing two different owners for one role on one boundary is a question this module does not resolve), and it authors no VIP/RTL/checker/scoreboard content. There is no stage gate and no `dv-harness` CLI verb (`cli.py`/`gates.py`/`CLAUDE.md` untouched, per this task's own file-safety scope) -- the front door is `python -m dv_harness.verification_boundary_ir classes|roles|build`.

Proven by `dv_harness_tests/test_verification_boundary_ir.py` (35 tests): the core positive path (fully-assigned, partially-assigned, and no-roles-declared boundaries); the list-builder form with per-index error naming; a JSON round-trip proof; both real CLI entry points driven as subprocesses; and negative controls for every refusal this module makes -- an owner with no evidence, an owner with blank evidence, an unrecognized role name, an unrecognized boundary class, an uncited/blank/`None` boundary-class citation, non-string owner/evidence types, and a malformed `role_inputs` shape.


<!-- S182: moved verbatim from CLAUDE.md original lines 10446-10465 (M4.6 CLAUDE Context Normalization) -->
## System Verification Contract Aggregator (2026-09-06)

A system composed of several subsystems needs the sibling rollup to `subsystem_contract.py`'s single-subsystem record: N subsystem contracts plus the real cross-subsystem facts `system_topology_analysis.py` (address/interrupt/clock-reset reconciliation, scenario planning), `system_resource_inventory.py` (SYS-9..14 shared-resource/active-driver-conflict analysis) and `system_command_plan.py` (SYS-18..22 command routing/collision analysis) already compute, assembled into ONE record. Without it, "is this system verified" required a human to open four different documents and manually cross-reference them, and two audits of the same system could describe its verification contract differently even from identical facts.

`dv_harness/system_verification_contract.py` is that assembly, and it is a pure aggregator that performs NO cross-subsystem analysis of its own: `system_topology_analysis.py` already decides address/interrupt/clock-reset conflicts, `system_resource_inventory.py` already decides ACTIVE_DRIVER_CONFLICT and shared-resource relationships, `system_command_plan.py` already decides command routing/collisions -- this module reads what those readers already produced and reports it verbatim, or `NOT_AVAILABLE` with the real reason when a caller did not supply it.

**Strict no-cross-import scope, enforced by a dedicated test.** Per this batch's file-safety rule, the module never imports `subsystem_contract.py`, `system_topology_analysis.py`, `system_resource_inventory.py`, or `system_command_plan.py` -- it accepts their real output SHAPES as generic/duck-typed parameters instead: a list of subsystem-contract-shaped dicts; a `system_topology_analysis.build_system_topology_analysis()`-shaped document (its own `summary` block read verbatim: address_regions/overlaps/conflicts, shared_memory_windows, interrupt_lines, clock_reset_conflicts, cdc_boundaries, scenarios_planned, topology_clean); a `system_resource_inventory.real_cross_subsystem_findings()`-shaped record (its own `CROSSCHECK_AVAILABLE`/`CROSSCHECK_UNAVAILABLE` status vocabulary, restated as plain string literals rather than imported names, plus `driver_conflicts`/`automatic_integration_allowed`/`blocking_decisions`/`preferred_model` carried through unchanged -- this module never picks a winner between conflicting active drivers); and a `system_command_plan.build_system_command_plan()`-shaped document (its own `summary` block: system_commands, collisions/blocking_collisions, subsystem_modes_preserved, command_plan_clean). This means the module is independently testable against synthetic fixtures and never assumes any of those four modules ran in this same process -- a caller with only some of the four inputs on hand still gets an honest, partial rollup rather than an import-time failure. An `ast`-based test parses the module's own source and asserts none of the four forbidden module names appears as an import.

**Per-subsystem-contract honesty.** Each entry in the caller-supplied subsystem-contracts list is read for its own `completeness` (COMPLETE/PARTIAL/NOT_AVAILABLE, `subsystem_contract.py`'s own vocabulary), `subsystem.resolved_name`/`requested`, `unknowns` count, and `spec_version`/`dut_sha`/`tb_sha`/`signoff.stage.stage_status` field statuses. A non-mapping entry, or one carrying no recognizable `completeness` field, is reported `UNKNOWN_SHAPE` with a specific reason rather than crashing or being silently skipped. A subsystem contract that is merely `PARTIAL` -- a real, already-visible fact about that subsystem -- is never treated as an "unknown" by this aggregator; only `NOT_AVAILABLE`/`UNKNOWN_SHAPE` entries are, the same distinction `subsystem_contract.py` itself draws between a field it could not assemble and one whose real value happens to be incomplete.

**`unknowns` is the honesty surface**, scored against a fixed `TRACKED_ASPECTS` denominator of exactly four (`subsystem_contracts`, `system_topology`, `system_resource_registry`, `system_command_registry`) -- never a list a caller can silently widen or narrow. `completeness` is `COMPLETE` (zero unknowns), `NOT_AVAILABLE` (all four unknown -- a bare/uninitialized rollup), or `PARTIAL` (anything between).

**Read-only, with one explicit write.** `assemble_system_verification_contract()` mints no store or `.dv-harness/` tree. `write_system_verification_contract()` / the `snapshot` verb is a separate, explicit act persisting the record to `.dv-harness/system_verification_contract.json`; `assemble` never writes. Both share `execute_verb()` (0 COMPLETE, 1 PARTIAL, 2 NOT_AVAILABLE/usage error), exposed as `python -m dv_harness.system_verification_contract assemble|snapshot [--subsystem-contracts <file>] [--topology <file>] [--resource-registry <file>] [--command-registry <file>] [--system-name ...] [--json]` -- each JSON input file is a bare array/object matching its real producer's own shape, since this module reads no live project state itself. No `dv-harness` CLI verb was added -- `cli.py`/`gates.py`/`CLAUDE.md` were out of this task's file-safety scope, the same disclosed choice several sibling same-day modules already make. It DECIDES, ARBITRATES and WRITES NO GOVERNANCE STATE: no stage runs, no gate is invoked, no approval is minted, and there is deliberately no stage gate -- a gate that passed because a contract record existed, or failed because one did not, would be worse than none.

`dv-harness system-verification-contract` has no dashboard card and no graph node -- this is a REACHED capability (a real CLI/import caller exists), not a WIRED one.

Proven by `dv_harness_tests/test_system_verification_contract.py` (20 tests): a full COMPLETE positive path over real-shaped fixtures for all four inputs; a legitimately-PARTIAL subsystem contract correctly excluded from `unknowns`; the required negative controls -- a bare call with nothing supplied reports every one of the four tracked aspects `NOT_AVAILABLE` with a real reason and never fabricates COMPLETE (the central proof the module refuses to claim a fact when required evidence is absent), a malformed subsystem-contract entry reports `UNKNOWN_SHAPE` without crashing, an unavailable resource-registry input carries its real `CROSSCHECK_UNAVAILABLE` reason through rather than reading as clean, a topology document missing its `summary` block, an unrecognized resource-registry status string, and a wrong-type command-registry input -- plus completeness-threshold boundaries, write/snapshot behavior (including a refusal on a nonexistent root and a proof that `assemble` writes nothing), `execute_verb()` and real `python -m` subprocess CLI runs at both the COMPLETE and NOT_AVAILABLE exit codes, and the AST-based cross-import restriction test.

**Disclosed residual**: this is a pure aggregation module with no live project-reading of its own -- it never queries `env.manifest.json`, an evidence database, or the subsystem registry directly; all four inputs must be supplied by the caller as already-assembled documents (in-memory dicts via the Python API, or JSON files via the CLI). It performs no cross-subsystem arbitration (an ACTIVE_DRIVER_CONFLICT's `preferred_model` is carried through as text for a human, never resolved). There is no `dv-harness` CLI verb and no `STAGE_GATES`/dashboard wiring, per this task's own file-safety scope.


<!-- S183: moved verbatim from CLAUDE.md original lines 10466-10483 (M4.6 CLAUDE Context Normalization) -->
## System Closure Aggregator: Strict Worst-Wins Over Twelve Named Dimensions (2026-09-06)

Nothing in this repo rolled up a project's closure state across all of its closure-relevant domains into one honest verdict. Plenty of per-domain closure mechanisms already exist -- `functional_coverage_signoff.py`'s Closure formula, `waiver_store.py`'s five-value waiver status, `golden_scenario.py`'s per-test freshness, `signoff_export.py`'s frozen-baseline invalidation, `system_error_propagation.py`'s recovery-chain completeness, `system_build_proof.py`'s merge-collision analysis, `amba_performance_readiness_gates.py`'s BUS_PERFORMANCE gates, `security_policy_ir.py`'s access classification, `arbitration_policy_ir.py`'s starvation-risk classification, `change_impact.py`'s risk classification -- but nothing joined them into one `SYSTEM_CLOSURE_STATUS`, and a caller wanting that answer had to open every one of those modules by hand and manually apply the same no-averaging discipline each of them already states as a design principle on its own.

`dv_harness/system_closure_aggregator.py` is that rollup, and it is deliberately a thin one: it computes nothing any of those real per-domain modules already compute. Per this batch's own file-safety scope it imports NONE of `functional_coverage_signoff.py`, `waiver_store.py`, `system_error_propagation.py`, or any other claimed/new-batch module -- each of the twelve fixed dimensions (`functional_coverage`, `protocol_coverage`, `requirement_closure`, `waiver_status`, `regression_status`, `evidence_integrity`, `error_propagation`, `build_composition`, `performance_closure`, `security_closure`, `arbitration_closure`, `change_impact_closure`) is accepted as a generic, duck-typed `{dimension_name, status}` record instead -- a plain dict or any attribute-bearing object -- the caller's own reduction of whichever real per-domain module actually decided that dimension's closure state.

**Strict worst-wins, never averaged -- the one rule this module exists to enforce.** A single dimension reporting UNMET/open BLOCKS overall closure (`SYSTEM_CLOSURE_STATUS = "NOT_CLOSED"`) regardless of how many of the other eleven are clean -- an 11/12 clean picture is still `NOT_CLOSED`. Only once no dimension is UNMET does an UNKNOWN/NOT_AVAILABLE dimension -- or one never supplied at all -- make the whole rollup `INCOMPLETE_EVIDENCE`, a THIRD value honestly distinct from both `CLOSED` and `NOT_CLOSED` (the same GF-AT-28 "a Critical UNKNOWN must never silently become READY" discipline, applied here to closure rather than readiness). `NOT_APPLICABLE` is the one status that clears WITHOUT counting as missing evidence -- a caller's real, declared "this dimension does not apply here" fact, never confused with "nobody looked". Only `CLOSED` requires every one of the twelve to have genuinely resolved to `MET` or `NOT_APPLICABLE`; a dimension the caller never mentions at all is reported `NOT_SUPPLIED` (distinct from an explicit `UNKNOWN`) and folds the same way into `INCOMPLETE_EVIDENCE` -- it can never silently default to `MET`.

`normalize_dimension_status()` maps a caller's real, heterogeneous status vocabulary (`PASS`/`FAIL`/`BLOCKED`/`READY`/`EXPIRED`/`VIOLATED`/...) onto five recognized tokens (`MET`/`UNMET`/`UNKNOWN`/`NOT_AVAILABLE`/`NOT_APPLICABLE`) via a fixed alias table, the same "accept the real producer's own spelling, normalize once, never re-derive a second vocabulary" discipline `protocol_compliance_aggregation.py`'s own `SCOREBOARD_PASS_VERDICTS`/`CHECKER_PASS_VERDICTS` already apply one domain over. An unrecognized raw string is honestly `UNKNOWN`, never guessed toward MET or UNMET. Two conflicting submissions for the same fixed dimension are reported `AMBIGUOUS_CONFLICTING_SUBMISSIONS` -- this module never arbitrates which one is right, the same ARBITRATION boundary `requirement_contract.py`/`design_knowledge_correlation.py` already keep for their own conflicting-claim findings -- and folds the same way into `INCOMPLETE_EVIDENCE`. A record naming a dimension outside the fixed twelve is reported in `unrecognized_records`, never silently dropped.

**Every dimension is ALWAYS reported individually, never collapsed into a bare pass/fail count.** `aggregate_system_closure()`'s result carries `dimensions`, all twelve, in fixed order, each with its own `normalized_status`/`raw_statuses`/`reasons`/`supplied` -- a reader can always see exactly which dimension is the real blocker or gap rather than only a summary count. `CLOSED`'s own token is a deliberate, disclosed reuse of `dv_harness.models.Status.CLOSED` -- the same disclosed-reuse precedent `protocol_compliance_aggregation.py`'s `OVERALL_PASS`/`OVERALL_FAIL` already set for `Status.PASS`/`Status.FAIL` -- checked at import against any UNDISCLOSED collision by `assert_no_extra_verdict_vocabulary_collision()`.

`render_system_closure_markdown()` reuses `connectivity.render_markdown_table()` (this repo's one parameterized table renderer) for its dimension-by-dimension view; `python -m dv_harness.system_closure_aggregator --dimensions <file.json> [--markdown]` is the front door (exit 0 `CLOSED`, 1 `NOT_CLOSED`, 2 `INCOMPLETE_EVIDENCE` or a usage error). No `dv-harness` CLI verb was added and `gates.py`/`cli.py` were not touched, per this task's own file-safety scope.

**Deliberately bounded, and stated rather than implied closed.** It decides nothing beyond the rollup itself: no build, no gate, no job, no LSF submission, and no approval is minted -- there is deliberately no stage gate, since a `SYSTEM_CLOSURE_STATUS` is an input to a human's closure/signoff review, never a substitute for one. It reads nothing from disk on its own beyond the CLI's own `--dimensions` file; every fact reaches it as a plain caller-supplied value.

Proven by `dv_harness_tests/test_system_closure_aggregator.py` (44 tests): the core positive path (all twelve MET/NOT_APPLICABLE -> CLOSED, individually reported, order-stable regardless of input order); the headline worst-wins negative controls (a single UNMET blocks with eleven clean, UNMET outranks a simultaneous UNKNOWN, multiple UNMET all named); the required "refuses to claim a fact when evidence is absent" proofs (a single UNKNOWN/NOT_AVAILABLE dimension, a dimension never supplied at all, and a wholly empty input all correctly report `INCOMPLETE_EVIDENCE` rather than a fabricated `CLOSED` or `NOT_CLOSED`); conflicting-vs-agreeing duplicate submissions; unrecognized-dimension-name handling; `normalize_dimension_status()` parametrized over real sibling-module vocabulary plus case/whitespace tolerance; duck-typed attribute-object input; markdown rendering; and six CLI subprocess tests covering all three exit codes plus malformed JSON input.


<!-- S210: moved verbatim from CLAUDE.md original lines 11807-11822 (M4.6 CLAUDE Context Normalization) -->
## Interface Contract / VIP Bind Validator (2026-09-06, section 219)

**Gap.** A project declares, somewhere upstream of generation (a vPlan row, a spec-derived interface list, a human-authored intent doc), that interface X is protocol P, direction D, and exposes signal bundle S. Section 219 asks whether the VIP bind this harness's own tooling can already find actually connects a module whose real RTL evidence agrees with that declaration. Nothing in this repo answered that before: a bind statement could target a module whose real port list is missing half the declared signal bundle, or whose real structural evidence resolves to a different AMBA protocol than a vPlan row claims, and no code path would ever notice. A repo-wide grep for `interface_contract`/`iface_contract`/`bind_validator` before writing this module matched nothing executable; `connectivity_check.py` (the standing 3-gate runner) and `dynamic_connectivity_ir.py` (runtime-reconfigurable routing) are both real, adjacent systems that do not answer this question either.

**Reuse over reinvent -- deliberately the opposite of a fourth binding validator.** `dv_harness/iface_contract_vip_bind_validator.py` adds no second bind-tier classifier, no second protocol-fingerprint table, and no second status vocabulary:

- Bind evidence is `connectivity.grep_existing_binds()` + `connectivity.find_existing_bind_for_target()` verbatim -- this validator checks only an ALREADY-DECIDED bind (connectivity.py's own T1_ALREADY_DECIDED tier: a real `bind` statement already on disk). A target instance with no such statement has nothing "actually connected" to check against and is reported `UNPROVABLE`, never guessed from a T2/T3 structural/naming CANDIDATE -- those remain `connectivity.py`'s own planning pipeline. Every resolved bind is still run through the real `classify_bind_tier()` so the card carries the same tier/rationale vocabulary rather than a second "how sure are we" scale.
- Protocol/signal evidence over the bound module's real (verible-extracted) ports is `connectivity.build_interface_fingerprints()`, `connectivity.classify_amba_protocol()` (the ten `AMBA4_PROTOCOLS`) and `connectivity.match_protocol_fingerprint()` (everything else in `PROTOCOL_FINGERPRINTS`), imported and called, never reimplemented. Direction is `connectivity.determine_role_from_port_direction()` applied to the one real port a contract names as its `anchor_signal` -- deliberately NOT a reimplementation of the deeper multi-signal `determine_fabric_interface_roles()`/`AmbaInterfaceRoles` system, which is out of this task's scope and would itself have been the "fourth validator" this task warns against.
- The status vocabulary is `vip_api_card.py`'s own five values, imported directly rather than re-spelled: `PROVEN` (declared axis agrees with real evidence) / `BLOCKED` (real evidence provably contradicts the declared axis) / `UNPROVABLE` (insufficient evidence either way) / `OUT_OF_SCOPE` (the contract declared nothing to check on that axis) / `NOT_AVAILABLE` (nothing decided at all). The worst-wins fold is applied twice, at both levels vip_api_card.py already applies it once: axis -> card (`BLOCKED > UNPROVABLE > PROVEN`, `OUT_OF_SCOPE` excluded from the fold) and card -> whole-report, so one `BLOCKED` axis on one interface fails that card, and one `BLOCKED` card fails the whole report, regardless of how many others are clean.

**What it validates, per declared interface:** a `DeclaredInterfaceContract` (`interface`, `target_instance`, and independently-optional `protocol`/`direction`+`anchor_signal`/`signals`) is checked against the real bind's `bound_module`'s real ports on three independent axes -- every declared `signals` entry must be a real present port (missing ones are named, per-signal); the declared `protocol` is checked against the real `classify_amba_protocol()`/`match_protocol_fingerprint()` verdict (an AMBA protocol declared against a port set that resolves `NOT_AMBA` is `BLOCKED`, not merely unproven; a resolved-but-different protocol is `BLOCKED` naming what was actually resolved; ambiguous/partial AMBA evidence and a non-AMBA fingerprint's partial-but-nonzero match are both `UNPROVABLE`, never rounded up to a hard contradiction against `PROTOCOL_FINGERPRINTS`' own admittedly-illustrative non-AMBA entries); and the declared `direction` is checked against the real recorded `PortInfo.direction` of the named `anchor_signal`. There is no fixed producer in this repo yet for a signal-list/protocol/direction interface declaration (the same disclosed boundary `subsystem_contract.py`'s `requirements` field and `spec_vplan_readiness_gate.py`'s condition list already state for their own caller-assembled inputs), so the contract set is accepted as a caller-supplied JSON record list rather than fetched by import.

**Read-only, no `dv-harness` CLI verb.** It emits no `bind` statement, writes no SystemVerilog, approves nothing. Front door is `python -m dv_harness.iface_contract_vip_bind_validator --contracts <file> [--bind-root <dir>] [--modules <file>] [--json] [--strict-unprovable]`; `cli.py`/`gates.py` were not touched, matching several sibling same-day additions' own disclosed choice. Exit 0 `PROVEN`, 1 `BLOCKED`, 2 `NOT_AVAILABLE`, 3 `UNPROVABLE` (non-blocking by default, same convention `vip_api_card.py`'s CLI already uses).

Proven by `dv_harness_tests/test_iface_contract_vip_bind_validator.py` (23 tests, `python -m pytest dv_harness_tests/test_iface_contract_vip_bind_validator.py -q` -> `23 passed`): a clean contract validated against a REAL bind statement (grepped by the real `connectivity.grep_existing_binds()` from a real temp `.sv` file) and REAL `verible_parser.ModuleInfo`/`PortInfo` evidence reports `PROVEN` on every axis, including the real `file:line` bind citation and the real derived VIP role; each `BLOCKED` rule is then driven by mutating exactly one fact away from that clean baseline (a fabricated signal, a wrong declared protocol against real AXI4 evidence, an AMBA protocol declared with zero AMBA evidence present, a wrong declared direction) with the other two axes proven to stay independently `PROVEN` in the same run; the full honesty surface is exercised as its own negative control (no bind found, bound-module ports not supplied, every axis left undeclared, an anchor signal absent from the real ports, partial non-AMBA structural evidence read as `UNPROVABLE` rather than `BLOCKED`, an unrecognized protocol name, zero contracts supplied); the whole-report worst-wins fold (one `BLOCKED` interface among clean ones still fails the report); three malformed-input negative controls (a missing required field, a duplicate interface name, a non-dict record) each raising the named `InterfaceContractError`; and the real `python -m` CLI subprocess across all four exit codes plus its `--json` output. `dv_harness_tests/test_connectivity.py` and `dv_harness_tests/test_vip_api_card.py` (the two modules this reuses) were re-run alongside it with no regressions (283 passed total), and a full-repo `pytest --collect-only` (10037 tests) confirms the new module introduces no import-time collision anywhere else in the suite.


<!-- S211: moved verbatim from CLAUDE.md original lines 11823-11840 (M4.6 CLAUDE Context Normalization) -->
## Golden Subsystem Benchmark / KPI / Critical False-Architecture Metrics (2026-09-06, sections 299-301 / 326-328)

**Gap.** Sections 299-301 (VIP_SCOREBOARD_CHECKER_ASSERTION.md) and 326-328 (SUBSYSTEM_DESIGN_INTELLIGENCE.md -- the same shape, aimed at design extraction rather than verification architecture) both ask the same question: grade a real extractor's placement/architecture CLAIMS about a subsystem against hand-curated golden ground truth, as a versioned benchmark with a KPI, and -- the critical, never-averaged-away property -- surface every case where the extractor was CONFIDENTLY WRONG. A repo-wide grep for `golden_subsystem`/`false_positive_claim`/`ground_truth` before writing anything matched nothing executable. `dv_harness/verification_architecture.py` (VIP/checker/scoreboard/assertion placement IRs) and `dv_harness/design_architecture_ir.py` (instance tree + FSM literal scan) are the two real extractors this task names; neither is re-implemented here -- `dv_harness/golden_subsystem_benchmark.py` only reads whichever of the two real, already-produced documents a caller supplies and grades named fields on named records against curated ground truth.

**Reuse, stated precisely.** `dv_harness/benchmark_dataset.py` (section 226) already built the versioned-corpus + train/test-leakage MECHANISM this task is told to reuse "as the vehicle rather than inventing a second benchmark harness." What is literally imported and unmodified: the generic `_sha256_text`/`_safe_id`/`_now` helpers, and -- because they are genuinely generic, not stage-mutation-specific -- its `DIFFICULTIES`/`QUALIFICATIONS` case-metadata vocabularies and its `INTEGRITY_*`/`LEAKAGE_*` result vocabularies, so a case here and a case in the section-226 corpus report integrity/leakage in the exact same words. What is deliberately NOT forced through `benchmark_dataset.py`'s own `register_dataset_version()`/`validate_case()`/`run_benchmark_eval()`, and why: that schema's execution-shaped fields are hard-bound to a different question. `expected_result` there must be one of `capability_evolution.BENCHMARK_OUTCOMES` (`IMPROVED`/`UNCHANGED`/`DEGRADED`/`INCONCLUSIVE`) -- a before/after CANDIDATE-EXPERIMENT vocabulary that does not mean, and must never be bent to mean, "this architecture claim was correct" -- and `mutation` must be a non-empty declarative shadow-run content diff, meaningless for grading a claim against ground truth. Populating those fields with inert placeholders just to pass validation would itself be exactly the kind of fabricated-shape workaround the Evidence Truth Rule exists to catch, and `benchmark_dataset.py`'s own docstring already discloses this shape as unsupported ("Cases that need a different execution shape ... are NOT supported"). So this module carries its own small versioned registry and append-only tuning ledger, structurally a direct port of `benchmark_dataset.py`'s three version-registration refusal rules (same-version-different-content refused, back-dated-version refused, no-op-bump refused) and its question-digest-keyed leakage design, sized to a case whose real content is `subsystem_id` + `extraction_kind` + a list of golden claim specs.

**Claim grading.** One `GoldenClaimSpec` names which IR list (`ir_kind`) to search, a `match` dict identifying exactly one record, a `field` on that record, the ground-truth `expected_value`, and two curator-declared, closed-per-claim value sets drawn from the real producer's own documented vocabulary (never invented by this module): `positive_values` (the field's confident/affirmative values, e.g. `["RESOLVED"]` or `[True]`) and `abstention_values` (the field's honest-abstention values, e.g. `["UNKNOWN", "PARTIAL", "NOT_AVAILABLE"]` or `[None]`). `grade_claim()` classifies, over `CLAIM_OUTCOMES` (a vocabulary checked at import to share no token with `dv_harness.models.Status`, the same discipline `capability_evolution`/`benchmark_dataset` already hold): `actual == expected` -> `CLAIM_MATCH`; `actual` in the claim's own `abstention_values` -> `CLAIM_HONEST_ABSTENTION` (a coverage gap, never scored as wrong -- an honest "don't know" must never be punished like a confident wrong answer); `actual` in `positive_values` but wrong -> `CLAIM_FALSE_POSITIVE`, the headline critical case (the extractor confidently asserted a checker is mounted, a scoreboard is comparable, an assertion's clock domain matches, an FSM resolved cleanly, or an instance resolved to a named module -- and was wrong); any other non-abstaining wrong value -> `CLAIM_FALSE_NEGATIVE`; a named target record that does not exist in the extracted doc -> `CLAIM_TARGET_MISSING`; an unresolvable/ambiguous match or a field absent on the resolved record -> `CLAIM_PATH_ERROR` (a corpus defect, never silently treated as a match).

**KPI, always reported, never omitted for being zero.** `summarize_claims()` reports `false_positive_architecture_claim_rate` (the headline metric) and `claim_accuracy` over the GRADEABLE claims only (`MATCH+FALSE_POSITIVE+FALSE_NEGATIVE`, so an abstention-heavy corpus cannot dilute the rate that matters), plus `honest_abstention_rate`/`target_missing_rate` as coverage signals and a `path_error_count` that should be zero in a clean corpus. A zero-denominator run reports `kpi_status: "NOT_AVAILABLE"`, never a fabricated `0.0`.

**Worst-wins, per the house rule.** `claim_verdict()` never averages: a single held-out `CLAIM_FALSE_POSITIVE` anywhere makes the whole case's (and, folded up, the whole run's) status `FALSE_POSITIVE_DETECTED`, full stop, regardless of how many other claims matched cleanly -- the same strict worst-wins discipline every composite gate in this repo already holds itself to, applied here to "does this extractor ever make a confidently wrong architecture claim on a golden subsystem".

**The eval is pure comparison, not a subprocess dispatch.** Unlike `benchmark_dataset.py` (which deliberately omits an `eval` CLI verb because running one would dispatch real `claude -p` subprocesses per case), `run_golden_subsystem_eval()` grades a caller-supplied `{case_id: <real extracted doc>}` mapping against the stored corpus -- never runs a simulator, build, regression, LSF job, verible, or either real extractor itself. A case whose extracted doc is absent is recorded `CASE_NOT_EXECUTED`, never silently skipped or graded against a fabricated stand-in. This makes exposing `eval` on the CLI safe, and it is exposed: `python -m dv_harness.golden_subsystem_benchmark {register,list,verify,diff,record-tuning-use,leakage,eval,runs}`. Per this task's file-safety scope, `dv_harness/gates.py` and `dv_harness/cli.py` were not touched -- no stage gate, no `dv-harness` verb -- matching `golden_scenario.py`/`power_intent.py`/`benchmark_dataset.py`'s own precedent that a pure grading/extraction module carries deliberately no stage gate.

**Deliberately bounded, and stated rather than implied closed.** (1) A claim's `match` spec must resolve to exactly one record; an ambiguous match is a corpus defect (`CLAIM_PATH_ERROR`), never resolved by picking "the first one". (2) `positive_values`/`abstention_values` are curator-declared per claim, not derived from the real module's status vocabulary by this module -- a curator who mis-declares them mis-grades their own case; this module does not second-guess a claim's own declared value sets. (3) This module never runs, imports for execution, or re-implements either real extractor -- grading is comparison over a caller-supplied document only. (4) There is no per-corpus JSON schema file (matching `benchmark_dataset.py`'s own Python-only validation, no sibling `.schema.json`).

Proven by `dv_harness_tests/test_golden_subsystem_benchmark.py` (60 tests, `python -m pytest dv_harness_tests/test_golden_subsystem_benchmark.py -q` -> `60 passed`) against REAL producer output throughout -- never hand-typed to merely look real: `verification_architecture.build_checker_ir()`/`build_scoreboard_ir()` driven through real `connectivity.generate_protocol_check_entry()`/`generate_scoreboard_entry()`/`assess_scoreboard_comparability()` calls, and `design_architecture_ir.build_module_registry()`/`build_instance_tree()`/`extract_fsm_candidates()` (the same pure-function, no-verible-required pattern `test_design_architecture_ir.py`'s own FSM tests use) driven over hand-built parsed-file dicts in that module's own documented shape. The central proofs (`test_confidently_wrong_checker_is_a_false_positive`, `test_scoreboard_confidently_comparable_but_wrong_is_false_positive`, `test_confidently_resolved_fsm_with_wrong_ground_truth_states_is_false_positive`, `test_instance_confidently_marked_resolved_but_wrong_module_is_false_positive`) each construct a real extractor output that is confidently wrong and assert `CLAIM_FALSE_POSITIVE`, with siblings proving an honestly-abstaining record (`UNKNOWN`/`PARTIAL`/unresolved) is never punished the same way (`CLAIM_HONEST_ABSTENTION`). `test_eval_detects_false_positive_and_worst_wins_over_the_whole_run` proves the worst-wins fold end to end: one false-positive claim fails the whole run even though a sibling claim in the same case is clean. Negative controls cover every non-happy path: `CLAIM_TARGET_MISSING`, `CLAIM_PATH_ERROR` (unknown field, ambiguous match, missing IR list), the version-registry's three refusal rules plus on-disk `CONTENT_DRIFT` detection, leakage `CLEAN`/`PARTIAL_LEAKAGE`/`FULLY_LEAKED` (including a rename-survives/substance-change-clears proof of the question-digest leakage key), `CASE_NOT_EXECUTED` when no extracted doc is supplied, `INADMISSIBLE` when the only case was tuned on, and a mandated vocabulary-collision test that mutates the module's own `CLAIM_OUTCOMES` tuple to include `"PASS"` and asserts `assert_no_verification_verdict_vocabulary()` actually raises. Both CLI entry points (`execute_verb`/`main`) are driven as real subprocesses across register/list/verify/leakage/eval/runs, including one asserting the real `python -m` `eval` verb exits 1 and prints `FALSE_POSITIVE_DETECTED` for a genuinely wrong scoreboard claim.


<!-- S213: moved verbatim from CLAUDE.md original lines 11857-11872 (M4.6 CLAUDE Context Normalization) -->
## Timing Requirement Extraction: Documented Setup/Hold/Latency Bounds From Text, Never A Measured Value (2026-09-06, section 289)

**Gap.** Section 289 asks for DOCUMENTED timing requirements -- a stated setup/hold/latency bound written down in a spec/programming-guide/RTL comment -- extracted as structural facts with real citations, explicitly kept distinct from the live-simulator-dependent Performance Verification item this same batch already deferred (see `amba_performance_calculator.py`/`amba_performance_classification.py`/`amba_performance_requirement_checker.py`'s own shared "over real, CALLER-SUPPLIED numbers only" framing, all three built earlier in this batch over numbers a run already produced). A repo-wide grep for `timing_requirement`, `setup_time`, `hold_time`, `tsu`/`thold`, `TimingRequirement`, and "section 289" before writing anything matched nothing executable.

**Reuse over reinvent -- two real siblings read in full, neither extended.** `dv_harness/system_failure_taxonomy.py`'s `TIMING_FAILURE` classifies ALREADY-REPORTED violation TEXT from a log/report -- a setup/hold violation citation, a race condition, a glitch that something else (a simulator, a linter) already found and wrote down; its own comment says outright it "measures nothing and runs no timing analysis of its own" and answers "did a timing failure get reported", never "what bound did the spec state before any run happened". `dv_harness/interrupt_dma_clock_reset_extraction.py` is the closest real MECHANISM sibling: a declaration-level, caller-supplied-text line-scan over RTL and prose, bounded to explicit statement forms, with an honest per-facet `NOT_AVAILABLE` when nothing explicit is found. `dv_harness/timing_requirement_extraction.py` reuses that same discipline (and independently re-declares its small `RTL_SUFFIXES`/`TEXT_SUFFIXES`/`classify_source()` shape rather than importing three constants from a sibling extractor) but extracts a structurally different fact -- a numeric timing bound with a comparison direction and unit, not an interrupt/DMA/clock-reset topology fact -- so it is its own module, not an extension of that one.

**The measured-vs-documented boundary is enforced structurally, not only stated.** `TimingRequirementFact` carries exactly one number, `value`, and it is always the DOCUMENTED bound a line states -- there is no sibling field anywhere in this module for an observed/measured/simulated result, so nothing here could even be wired to a live comparison by accident. Every line-scan additionally runs `_MEASURED_VALUE_EXCLUSION_RE` (observed/measured/simulat*/waveform/sim.log/actual) BEFORE any requirement pattern is tried, so a sentence reporting what a run produced is skipped outright even when it also uses "setup"/"hold"/"latency" and a directional-looking word -- proven directly by `test_measured_or_observed_language_is_never_extracted_as_a_requirement`, which plants "Simulation observed setup margin of 6 ns ..." next to a real documented 5 ns bound in the same fixture and asserts only the documented one survives extraction.

**A bound is extracted only when one line states three things together, never fewer.** (1) a recognized keyword (`setup time`/`tSU`, `hold time`/`tHOLD`/`tHD`, or `latency`); (2) a real number with a recognized unit (ps/ns/us/ms, or a cycle count -- never unit-converted, since converting cycles to time needs a clock period this module has no evidence for); (3) an explicit directional cue spelling out which way the bound goes (at least/minimum/`>=`, or shall-not-exceed/must-not-exceed/maximum/`<=`, or exactly/`==`). A keyword with no number ("the setup time is TBD"), a number with no directional cue ("latency is 50 ns" -- ambiguous whether that is a ceiling, a floor, or a typical value), or a cue with no keyword contributes nothing -- never a guessed comparison, unit, or value. A subject (the signal pair a bound applies to) is populated only from two explicit textual forms (`between X and Y`, `for X relative to Y`) and is honestly `None`, not omitted and not guessed, otherwise.

**The fact structurally refuses to be built without a citation.** `TimingRequirementFact.__post_init__` raises `TimingRequirementExtractionError` for a missing/blank `evidence` (a `path:line` citation), a missing/blank `text` (the raw source line), an unrecognized `kind`/`comparison`, or a `value` that is missing, non-numeric, or a bare bool -- the same "mandatory field enforced in code, not only in a docstring" discipline `amba_performance_requirement_checker.PerformanceRequirementIR` and `qos_policy_ir.build_qos_policy_ir()` already hold themselves to, so a caller building a fact by hand (bypassing the scanner) cannot construct one that skips a citation either.

**Deliberately bounded, and stated rather than implied closed.** (1) This is a regex line-scan, not a timing analyzer or an NLP understander -- a construct spanning an unusual continuation these patterns do not anticipate contributes no citation rather than a wrong one, exactly `interrupt_dma_clock_reset_extraction.py`'s own disclosed limit. (2) Bounded to the three kinds section 289 names (SETUP/HOLD/LATENCY); a different timing concept (clock-to-out, propagation delay, recovery/removal time) is out of this module's scope rather than silently folded into one of the three. (3) It never runs, imports, or calls into any of the three real performance modules, and produces no value shaped to be fed into `amba_performance_requirement_checker.check_against_requirement()` as a MEASURED value -- a caller who legitimately wants to check a real measured latency against a documented bound may build a `PerformanceRequirementIR` from one of THIS module's facts as the requirement side of that comparison; this module never performs the comparison itself. (4) It is a standalone module with no `dv-harness` CLI verb and no `gates.py`/`cli.py` edit -- both are large files under concurrent edit pressure in this same multi-agent batch, the same disclosed choice several recent modules in this codebase already make; front door is `python -m dv_harness.timing_requirement_extraction extract --sources <f> [<f> ...] [--json]`.

Proven by `dv_harness_tests/test_timing_requirement_extraction.py` (19 tests, `python -m pytest dv_harness_tests/test_timing_requirement_extraction.py -q` -> `19 passed`) against real synthetic fixtures under `dv_harness_tests/fixtures/timing_requirement_extraction/` (each file's own header states it is synthetic, never mined from any real protocol spec, VIP, or the vendored `uvm_syoscb`): the positive path extracts a real setup bound, hold bound, and two independent latency bounds (one in cycles, one in ns) each with the correct comparison, unit, subject, and `path:line` citation; the central negative control proves an "observed"/"simulation" sentence carrying the same keyword and a nearby number is never extracted; two further negative controls prove a keyword with no number and a number with no directional cue both extract nothing; a fully blank-of-timing-language fixture reports `NOT_AVAILABLE` at every level (top, `timing_requirements`, and each of the three `by_kind` entries); source-handling negative controls cover no sources supplied and a missing file; extraction from a real `.sv` comment line (not just `.txt` prose) and a two-source combination are both proven directly; and seven direct `TimingRequirementFact` construction tests prove the dataclass itself refuses a missing citation, missing text, an unrecognized kind, an unrecognized comparison, a missing value, a bare-bool value, and a missing unit. Both CLI paths (`--json` LOADED exit 0, NOT_AVAILABLE exit 2, no-args usage-error exit 2) are driven as real `python -m` subprocesses. A full-repo `pytest --collect-only` (11186 tests) confirms the new module introduces no import-time collision anywhere else in the suite.


<!-- S216: moved verbatim from CLAUDE.md original lines 12096-12167 (M4.6 CLAUDE Context Normalization) -->
## Integration Adapter Generation: Adapter Glue Code From an Already-Resolved SubsystemAdapterIR (2026-09-06)

`dv_harness/subsystem_adapter_ir.py` (see its own section above) resolves a caller-supplied
mapping against the FIXED 8-operation logical vocabulary (configure/start/stop/reset/wait_ready/
execute/monitor/get_status) and reports, per operation, RESOLVED (a real mapped task/sequence name,
carried through verbatim) or UNSUPPORTED_OPERATION (no real mapping exists, and no stub is
synthesized). That module's own docstring is explicit about where it stops: "It authors no
task/sequence body and validates nothing about whether a resolved task/sequence name is itself
syntactically or semantically correct... that is this batch's other, separately-scoped modules' job
(or a downstream generator's)." A repo-wide check confirmed no such downstream generator existed
anywhere in this codebase before this item -- REUSE OVER REINVENT was applied before writing a line
of code: `subsystem_adapter_ir.py` already covers the resolution half completely and is left
untouched; `dv_harness/integration_adapter_gen.py` is the additive generation step it names but does
not perform.

**What it generates, and what it refuses to invent.** Not protocol-behavior content -- "No
Golden-Reference Content Mining" forbids that, and this module never authors what a task/sequence
actually DOES. What it generates is mechanical GLUE: for each of the 8 fixed logical operations, a
`` `define `` macro redirect from a fixed facade macro name (`DV_ADAPTER_<OPERATION>`) to the real,
already-resolved task/sequence name. This is the same "macro redirect, placed before the real
definitions it forwards to" wiring convention `dv_harness/uvm_generator/
bind_mechanism_generator.py`'s `emit_hook_svh()` already establishes for this project's DV_UVM hook
-- reused here for the fixed 8-operation vocabulary rather than invented from scratch.

A RESOLVED operation's macro forwards, byte-for-byte, to the caller's own real mapped name (after
`assert_resolved_name_is_callable_identifier()` confirms it is at least a syntactically plausible
SystemVerilog callable -- the one piece of validation `subsystem_adapter_ir.py`'s own docstring
explicitly leaves to "a downstream generator"). An UNSUPPORTED_OPERATION NEVER gets a fabricated
task/sequence name: its macro forwards instead to a generated, deterministically-named failure task
(`dv_adapter_unsupported_operation_<subsystem>_<operation>`) whose body does nothing but
`` `uvm_fatal `` with the resolved IR's own real, honest `reason` text for why no mapping exists --
so a caller who accidentally wires an unmapped operation into a running environment gets a loud,
traceable failure at the point of use, never a silently-invented no-op or a plausible-sounding
guessed call.

**The one piece of validation this module adds on top of resolution.**
`assert_resolved_name_is_callable_identifier()` refuses a RESOLVED name that is empty, contains
whitespace, or carries any character outside a legal identifier in any dotted segment (including an
empty segment from a leading/trailing/doubled `.`) -- `IntegrationAdapterGenError` names the
operation and the offending name/segment rather than silently emitting a macro redirect to invalid
text. `unsupported_operation_task_name()` builds the deterministic failure-task name ONLY from the
real subsystem name and the real (fixed-vocabulary) operation name -- never from anything a
caller's mapping did or did not supply for the operation, since by definition nothing real was
supplied.

`build_and_generate_adapter_glue(mapping_entries, subsystem_name=None, out_path=None)` is the
end-to-end entry point: resolve (via the untouched `subsystem_adapter_ir.build_subsystem_adapter_ir()`)
then generate, in one call, propagating any `SubsystemAdapterIRError` unmodified rather than
swallowing or reinterpreting a resolution-time refusal. `write_adapter_glue_svh()` writes the
generated `.svh` to a real path on disk.

**Deliberately no `cli.py`/`gates.py` edit.** Per this batch's own disclosed-choice convention
(matching several other recent modules in this codebase that made the identical choice when
`cli.py`/`gates.py` were under concurrent edit pressure from many other items in the same batch),
this item ships a standalone front door instead: `python -m dv_harness.integration_adapter_gen
<mapping_file> [--subsystem-name NAME] [--out PATH]` (`execute_verb()`/`main()`), accepting a JSON
file that is either a bare list of `{operation, existing_task_or_sequence_name}` mapping entries or
an object carrying `mapping_entries` and optionally `subsystem_name`. Exit 0 on a successful
generation (even one carrying UNSUPPORTED_OPERATION findings -- those are an honest, reportable
fact about the mapping, not a generator failure), 1 on a resolution/generation error, 2 on a usage
error (bad JSON, missing file, wrong shape).

**Deliberately bounded, and stated rather than implied closed.** (1) It never authors a task/
sequence body -- only a macro redirect and, for an unsupported operation, a one-line
`` `uvm_fatal `` failure stub. (2) It decides, approves and arbitrates nothing beyond generation: no
build, no simulation, no LSF submission, no approval, and there is deliberately no stage gate. (3)
It never re-implements or re-guesses `subsystem_adapter_ir.py`'s own resolution logic -- every
generation call goes through that module's real, untouched `build_subsystem_adapter_ir()`.

Proven by `dv_harness_tests/test_integration_adapter_gen.py` (30 tests): naming-helper determinism
(`facade_macro_name`/`unsupported_operation_task_name`, including the no-subsystem-name case);


<!-- S225: moved verbatim from CLAUDE.md original lines 12755-12838 (M4.6 CLAUDE Context Normalization) -->
## Advanced Coverage Closure Intelligence: Cross-Hole Correlation + Multi-Hole Action Identification (2026-09-06)

Section 236 asks for an intelligence layer on top of two already-real, already-tested mechanisms:
`coverage_closure_action_utility.rank_coverage_closure_actions()` (a correctness/risk-gated,
four-factor utility ranking over candidate coverage-closure actions) and
`coverage_analysis.classify_coverage_hole_taxonomy()` (the real 12-category structural taxonomy for
one hole, citing its own real evidence). Both already answer their own question well -- which ACTION
has the highest expected value after excluding anything flagged wrong or dangerous, and which
STRUCTURAL category one hole falls into -- and neither ever compares two holes to each other or asks
whether a single proposed action would close more than one of them. A coverage-closure effort with
many open holes and several candidate actions routinely has holes sharing a REAL, already-declared
root cause (the same register, the same cross-coverage axis, the same requirements-linked pattern,
the same missing configuration variant), where one directed test or constraint relaxation can close
several of them at once. A repo-wide grep for `cross_hole`/`hole_correlation`/`multi_hole`/
`closes_holes` before this module was written matched nothing executable anywhere in this repo.

`dv_harness/coverage_closure_hole_correlation.py` is that intelligence layer, and it re-derives
neither underlying mechanism -- `classify_coverage_hole_taxonomy()` is called once per hole
unchanged, and `rank_coverage_closure_actions()`'s own rank/utility_score/correctness-risk gate is
read verbatim (via its own `_lookup`/`_resolve_action_id` helpers, imported rather than
reimplemented, so an action_id computed here can never silently diverge from the one that module
assigned to the identical candidate).

**Correlation is never guessed from the taxonomy label; only from four real, already-declared
evidence facts, reused rather than re-derived**: `SHARED_REGISTER` (two holes declare the identical
`register_name`), `SHARED_CROSS_AXIS` (their declared `cross_axes` lists share a member),
`SHARED_LINKED_PATTERN` (they trace, via `classify_coverage_hole_taxonomy()`'s own real
`linked_patterns` -- the requirements-registry linkage that module already computed -- to the
identical PATTERN_ID), `SHARED_MISSING_CONFIG` (both declare `hit_in_configs`/`legal_configs` and are
both missing coverage in the identical configuration name). Two holes classified into the same
12-category taxonomy value for entirely unrelated reasons are never assumed correlated on that
strength alone -- proven directly by a dedicated negative-control test.

**Which action closes which hole is always a caller declaration, never inferred.** A candidate action
may declare a `closes_holes` list of coverage_id strings (the field name itself overridable via
`closes_holes_field`); one declaring none is honestly `NOT_DECLARED`, never assumed to close zero
holes as if that were a measured fact. A declared coverage_id absent from the supplied hole set is
honestly `unknown_hole_ids`, never silently dropped and never treated as correlated with anything.

**The intelligence layer: BUNDLE STATUS.** For an action declaring two or more real, known holes,
every pairwise combination is checked against the real correlation groups above:
`CORRELATED_MULTI_HOLE` (every pair shares real evidence -- a genuine cluster-closing candidate),
`PARTIALLY_CORRELATED_MULTI_HOLE` (some pairs do, some do not), `UNCORRELATED_MULTI_HOLE_BUNDLE`
(none do -- an action claiming to close several holes with no real shared cause between any of them,
worth a second look before trusting the bundle).

**This module's own instance of the project's worst-wins composite-gate rule.** `rank_coverage_closure_actions()`'s
own rank/utility_score, and -- critically -- its correctness/risk GATE (an action flagged
`FLAGGED_INCORRECT` or `HIGH_RISK` is excluded from ranking entirely, before cost or anything else is
considered) are read here verbatim and never recomputed. `high_value_multi_hole_actions` is an
ADDITIONAL, clearly-labelled advisory lens over already-RANKED (i.e. already gate-cleared) actions
only -- a correlated multi-hole bundle whose action was EXCLUDED for being flagged incorrect or
high-risk, or was UNRANKABLE for a missing utility factor, is never promoted into that list on the
strength of how many holes it claims to close: a single UNMET/BLOCKED condition (here, the utility
module's own gate) must make the whole recommendation fail regardless of how attractive another
dimension (hole count) makes it look.

Ad hoc: `dv-harness` was not touched (per the standard escape hatch when the CLI file is under
concurrent edit pressure) -- the front door is `python -m dv_harness.coverage_closure_hole_correlation
--root <dir> --holes-file <file.json> --candidates-file <file.json> [--closes-holes-field ...]
[--parsed-summary-file ...] [--json]`.

**Deliberately bounded, and stated rather than implied closed.** It does not classify a hole (that
stays `classify_coverage_hole_taxonomy()`'s job, called unchanged), it does not rank an action's
utility or apply the correctness/risk gate (that stays `rank_coverage_closure_actions()`'s job,
called unchanged), and it does not decide which action a project should actually pursue -- it only
surfaces, from real declared evidence, which holes are genuinely related and which already-ranked
actions would close more than one of them at once. It writes nothing, approves nothing, and gates no
stage.

Proven by `dv_harness_tests/test_coverage_closure_hole_correlation.py` (26 tests): all four
correlation-group kinds detected from real declared evidence (including a real
`requirements.csv`-backed `SHARED_LINKED_PATTERN` group and case/whitespace-tolerant register
matching), the headline negative control that two holes sharing no real evidence are never
fabricated as correlated even when one action claims to close both, all three bundle-status values
plus `BUNDLE_SINGLE_HOLE`/`BUNDLE_NOT_DECLARED`/`BUNDLE_REFERENCES_ONLY_UNKNOWN_HOLES`, an
EXCLUDED (`FLAGGED_INCORRECT`) action with enormous utility factors still correctly excluded from the
high-value view despite closing two genuinely correlated holes, an UNRANKABLE action likewise never
promoted, a proof that the underlying utility ranking's own order is never reordered by hole count,
malformed-input refusals (missing/duplicate coverage_id, malformed hole, invalid `closes_holes`
declaration, an action not present in the supplied ranking), report rendering, and both real CLI exit
paths (`--json` and default text) driven as real subprocesses. Run:
`python -m pytest dv_harness_tests/test_coverage_closure_hole_correlation.py -q` -> `26 passed`.


<!-- S228: moved verbatim from CLAUDE.md original lines 13043-13105 (M4.6 CLAUDE Context Normalization) -->
## SystemScoreboardIR: System-Scope Scoreboard Composition, Reusing scoreboard_placement_scope.py's 8-Value Taxonomy (2026-09-06)

`dv_harness/system_scoreboard_ir.py` answers a system-scope question none of this project's other
scoreboard mechanisms answer: for a declared cross-subsystem interaction (a shared DMA engine, a
shared interrupt chain, a shared memory controller, an explicit end-to-end claim, or a directly
declared scope), does it need a cross-subsystem/end-to-end scoreboard at all, and if so does one
already exist that actually covers it. `verification_architecture.ScoreboardIR` (documented above)
is explicitly a DIFFERENT, narrower mechanism: it extends `connectivity.generate_scoreboard_entry()`'s
own per-subsystem `data_integrity_scoreboard` shape with structural comparability evidence for ONE
scoreboard inside ONE subsystem's own environment, with no notion of a SET of subsystems or of
whether an end-to-end scoreboard exists at all -- `system_scoreboard_ir.py` never imports it, and
accepts a per-subsystem `ScoreboardIR.to_dict()` output only as a generic, duck-typed
`existing_scoreboards` entry if a caller happens to have one.

**Reuses, never re-derives, `scoreboard_placement_scope.py`'s 8-value taxonomy.**
`SCOPE_VALUES`/`SCOPE_PRECEDENCE`/`SCOPE_DEFINITIONS` and the evidence-gated
`classify_scoreboard_scope()` are imported and called directly -- applied to TWO different kinds of
caller-declared fact: (1) a cross-subsystem interaction's own required compare scope, and (2) an
already-declared scoreboard's own actual compare scope -- then asks whether (2) satisfies (1). The
ONE legitimate subsumption recognised is `SCOPE_END_TO_END` (defined as spanning stimulus injection
through the final observed system-level effect); every other scope pairing must match EXACTLY -- a
`DMA_PATH`-scoped scoreboard never counts as covering an `INTERRUPT_PATH`-scoped requirement, and vice
versa. A genuinely multi-subsystem interaction whose own scope facts resolve to a single-block-local
scope (`PORT_LOCAL`/`FUNCTION_LOCAL`/`BLOCK_LOCAL`) is reported as a real `SCOPE_CONTRADICTION`
finding, never silently accepted. Four never-collapsed per-interaction composition statuses:
`COVERED` / `GAP_NO_COVERING_SCOREBOARD` / `REQUIREMENT_UNVERIFIABLE` (the interaction is real but
carries no recognised placement-scope fact -- honestly unresolved, never assumed covered) /
`SCOPE_CONTRADICTION`. A project declaring zero cross-subsystem interactions reports the whole IR
`NOT_APPLICABLE`, never a vacuous `COMPLETE` or a fabricated `INCOMPLETE`. Overall status folds
worst-wins: a single non-`COVERED` interaction makes the whole IR `SYSTEM_SCOREBOARD_COMPOSITION_INCOMPLETE`
regardless of how many others are `COVERED`.

**Deliberately bounded, and stated rather than implied closed.** It discovers no interaction and no
scoreboard of its own -- `system_interactions`/`existing_scoreboards` are entirely caller-declared,
duck-typed facts, the natural real sources being a project's own `system_topology_analysis.py`/
`system_resource_inventory.py` output and its generated scoreboard plan/`env.manifest.json`, neither
imported here. It never arbitrates a genuinely conflicting fact (`ScoreboardPlacementScopeError`
propagates rather than being swallowed). It never emits a scoreboard, a compare-key schema, or any
SV/UVM content -- `soc_environment_composer.end_to_end_scoreboard()`'s own deliberate
`NotImplementedError` stub boundary is untouched and uncrossed; this module only analyses whether
such content is architecturally NEEDED and, if so, whether something claiming to be it already
exists. There is no `dv-harness` CLI verb and `gates.py`/`cli.py` were not touched, per this task's
own file-safety scope -- front door is `python -m dv_harness.system_scoreboard_ir scopes|build`.

Proven by `dv_harness_tests/test_system_scoreboard_ir.py` (36 tests, `python -m pytest
dv_harness_tests/test_system_scoreboard_ir.py -q` -> `36 passed`): the reused 8-value taxonomy and
the vocabulary-collision guard against `models.Status`; every one of the four composition statuses
including the exact-scope-match-only subsumption rule (`DMA_PATH` never covering `INTERRUPT_PATH`),
the single-block-local scope contradiction, the unresolved-requirement-never-covered proof, and the
SyoSil-adjacent defaulted-scope case (only satisfied by an `END_TO_END`-scoped scoreboard); the
worst-wins overall fold across a mixed covered/gap interaction set; a covering scoreboard required to
be a real superset of every declared subsystem, not a partial match; duplicate-interaction-id and
malformed-input-type refusals; markdown rendering via the reused
`connectivity.render_markdown_table()`; and the real CLI (`scopes`/`build`) driven as subprocesses
across all four documented exit paths (COMPLETE, INCOMPLETE, NOT_APPLICABLE, malformed-input error).

**Disclosed note on this task's own assignment.** This module and its full test suite already
existed, complete and passing, on disk before this gap-closure item began -- built, evidently, by a
separate agent in this same batch (or an earlier pass of it) whose corresponding CLAUDE.md section
had not yet been written. Per REUSE OVER REINVENT, no parallel module was written; this section
documents the pre-existing implementation honestly, after independently reading its full source and
re-running its test suite to confirm the 36/36 pass reported above.


<!-- S229: moved verbatim from CLAUDE.md original lines 13106-13203 (M4.6 CLAUDE Context Normalization) -->
## System Signoff Package: a System-Scope Bundle Over Multiple Subsystem Contracts, Reusing signoff_export.py's Bundle Mechanics (2026-09-06)

`signoff_export.collect_signoff_bundle()` is a single-project (subsystem-scope, IP-level) signoff
bundle: it copies real artifacts off ONE project root, computes ONE `bundle_hash`, and stamps a
`SIGNOFF_GATE_VERIFIED`/`PRE_SIGNOFF_GATE_INPUT` kind from that one project's own real SIGNOFF
stage-gate status. Nothing in this repo assembled the SYSTEM-scope sibling: several real,
already-real per-subsystem `SubsystemVerificationContract` records (`subsystem_contract.py`) plus
the system-level rollups (`system_verification_contract.py`'s cross-subsystem topology/resource/
command reconciliation, `system_closure_aggregator.py`'s twelve-dimension worst-wins closure fold)
assembled into ONE exportable package a human can hand to a system-level signoff review.
`dv_harness/system_signoff_package.py` is that package, and it writes no second bundler.

**REUSE OVER REINVENT, applied to the bundle mechanics themselves.** Every one of the three inputs
is produced by its own already-real, already-tested module, called directly:
`subsystem_contract.assemble_subsystem_contract()` once per named subsystem;
`system_verification_contract.assemble_system_verification_contract()` once, over the real
subsystem-contract records this module just assembled; `system_closure_aggregator.
aggregate_system_closure()` once, over a caller-supplied list of `{dimension_name, status}` closure
records (this module invents none of the twelve dimensions' values). The BUNDLE MECHANICS --
never a second, parallel bundler -- are the exact ones `signoff_export.collect_signoff_bundle()`
already established, imported directly: `signoff_export.compute_bundle_hash(manifest)` (the real,
independently-recomputable manifest-hash function) and `signoff_export._artifact_content_digest()`
(the same file-or-directory content hasher that function itself calls). Every manifest entry this
module writes carries the IDENTICAL four-key shape (`artifact`/`present`/`bundled_path`/
`content_sha256`) `collect_signoff_bundle()`'s own `record()` closure produces, so a reader (or a
future completeness gate) parses a system-scope manifest.json exactly the way it already parses a
project-scope one -- proven directly by cross-checking this module's own `bundle_hash` against an
INDEPENDENT call into `signoff_export.compute_bundle_hash()` over the same manifest.

**What this module adds on top of that reused mechanics.** `package_kind` --
`SYSTEM_SIGNOFF_GATE_VERIFIED` only when EVERY assembled subsystem contract's own real
`signoff.stage.gate_verified` is true AND the closure rollup's own real `overall_status` is
`CLOSED` -- worst-wins across BOTH facts, this project's own composite-gate discipline applied one
level up: a single subsystem whose own SIGNOFF gate never passed, or a single closure dimension
left open, makes the WHOLE package `PRE_SYSTEM_SIGNOFF_GATE_INPUT` regardless of how clean
everything else is, and ZERO assembled subsystems never reads as gate-verified either (proven: a
bare root with no subsystems requested still reports `PRE_SYSTEM_SIGNOFF_GATE_INPUT`, never a
vacuous verified kind over nothing). `require_system_signoff_pass=True` turns that into a hard
refusal that writes NOTHING at all, not even an empty `out_dir` -- the identical "refusal writes
nothing" contract `collect_signoff_bundle()` already keeps. A `subsystem_index` names every
subsystem this package attempted to assemble, whether LIVE_ASSEMBLED (this module called
`subsystem_contract.assemble_subsystem_contract()` itself against `root`) or CALLER_SUPPLIED (a
caller already held a subsystem-contract-shaped record and handed it in directly -- the same
duck-typed acceptance `system_verification_contract.py` itself already extends to its own
`subsystem_contracts` parameter). A subsystem whose LIVE assembly raised is recorded honestly --
`present: False` in the manifest, the real exception text in `subsystem_index`, and it is EXCLUDED
from what `system_verification_contract.py`/`system_closure_aggregator.py` see, exactly as
`collect_signoff_bundle()` never fabricates a missing artifact.

**Evidence Truth Rule.** Nothing here invents a subsystem's completeness, a gate-verified status,
or a closure verdict. A subsystem with nothing on disk to assemble from still produces a real
(honestly `NOT_AVAILABLE`/`PARTIAL`) contract record -- `subsystem_contract.
assemble_subsystem_contract()`'s own contract, not this module's -- and that honest incompleteness
is what keeps `package_kind` at `PRE_SYSTEM_SIGNOFF_GATE_INPUT` rather than being silently rounded
up.

**Deliberately bounded, and stated rather than implied closed.** It DECIDES, ARBITRATES and WRITES
NO GOVERNANCE STATE beyond the package directory itself: no stage runs, no gate script is invoked,
no build/regression/LSF submission starts, no approval is minted, and no cross-subsystem
resource/ownership conflict is resolved (a `driver_conflicts`/`blocking_decisions` finding inside
the system-verification-contract section is carried through as text for a human, exactly as
`system_verification_contract.py` itself already states). There is deliberately no `STAGE_GATES`
entry -- a gate that passed because a package existed, or failed because one did not, would be
worse than none. No `dv-harness` CLI verb was added -- `cli.py`/`gates.py` are large files under
heavy edit pressure from many concurrent items in this same batch -- the front door is
`python -m dv_harness.system_signoff_package collect --root <dir> --out-dir <dir> [--subsystem NAME
...] [--subsystem-contracts <file>] [--topology <file>] [--resource-registry <file>]
[--command-registry <file>] [--closure-dimensions <file>] [--system-name NAME]
[--require-system-signoff-pass] [--json]` (exit 0 `SYSTEM_SIGNOFF_GATE_VERIFIED`, 1
`PRE_SYSTEM_SIGNOFF_GATE_INPUT`, 2 REFUSED or a usage error). This is a REACHED capability (a real
CLI/import caller exists), not a WIRED one.

Proven by `dv_harness_tests/test_system_signoff_package.py` (17 tests, all passing): the bare-root
no-subsystems negative control (never fabricates verified); a real LIVE_ASSEMBLED subsystem over a
bare root reported honestly incomplete, cross-checked directly against
`subsystem_contract.assemble_subsystem_contract()`'s own real return value; the manifest-shape and
`bundle_hash`-reuse proof against an independent `signoff_export.compute_bundle_hash()` call;
`content_sha256` verified against real file bytes on disk; the required negative control -- a
subsystem whose real assembly RAISES is reported absent (`present: False`, the real exception text)
and never crashes the whole package, and its failure is proven to never leak into
`system_verification_contract`'s own count of real assembled contracts; caller-supplied
precontracts bundled with a `__supplied` filename suffix; the worst-wins proofs (one ungated
subsystem blocks an otherwise-all-clean package; one open closure dimension blocks an
otherwise-all-gate-verified package); `require_system_signoff_pass`'s refusal-writes-nothing
contract on both the refused and the succeeding path; unsafe-subsystem-name sanitization into
distinct, collision-free filenames that never escape the `subsystems/` bundle directory; a
precontract carrying no declared identity named positionally; and four real CLI subprocess
invocations covering the PRE_SYSTEM_SIGNOFF_GATE_INPUT, SYSTEM_SIGNOFF_GATE_VERIFIED, text-output,
and malformed-input-refusal paths.

**Disclosed note on this task's own assignment.** This module and its full test suite already
existed, complete and passing, on disk before this gap-closure item began -- built, evidently, by a
separate agent in this same batch (its own file header already carries the full design rationale
summarized above) whose corresponding CLAUDE.md section had not yet been written. Per REUSE OVER
REINVENT, no parallel module was written; this section documents the pre-existing implementation
honestly, after independently reading its full source and re-running its test suite (17/17 passing)
to confirm the claims above.


<!-- S232: moved verbatim from CLAUDE.md original lines 13372-13493 (M4.6 CLAUDE Context Normalization) -->
## RTL Data-Path Extraction: Continuous-Assign + Bounded Always-Block Assignment Scan (2026-09-06)

Sections 257-262's data-path question -- "which signals feed which combinational/sequential logic"
-- had two real, narrow answers already in this codebase and no general one. `verible_parser.py`
already extracts each module's real continuous `assign` statements with `lhs_nets`/`rhs_nets`
resolved from the real syntax tree; two real consumers already exist for that fact, but both narrow
it to their own purpose -- `amba_fabric_discovery.py`/`amba_fabric_analysis.py` trace a bus signal
through a 1:1 wire-rename alias while building a fabric route, and `register_rtl_trace.py` asks
whether a specific register-field NAME is referenced anywhere in a module's RTL. Neither exposes the
continuous-assign fact as a general "signal X feeds signal Y" record, and neither says anything at
all about PROCEDURAL (always-block) assignments -- `verible_parser.py`'s own docstring is explicit
that signals/statements declared or assigned INSIDE a procedural block are deliberately not
surfaced. `design_architecture_ir.py` adds exactly one procedural-content extraction on top of
`verible_parser.py`: a best-effort literal scan for `always @(posedge ...)` blocks containing a
`case`, scoped narrowly to FSM-candidate detection. It never asks the wider question this module
answers: for an ORDINARY (not FSM-shaped) always block, which signals on the right-hand side of an
assignment feed which signal on the left, and which of those blocks is combinational vs. sequential
vs. an explicit latch. `rtl_control_flow_extraction.py` already answers that classification question
(`block_kind`, if/else-if shape, case shape) but deliberately stops at structural SHAPE and carries
no signal-level LHS/RHS fact at all.

`dv_harness/rtl_data_path_extraction.py` extends BOTH existing extractions rather than re-deriving
either. `extract_continuous_assign_data_path()` reads `verible_parser.py`'s own already-parsed
`ContinuousAssignInfo` records (`lhs_nets`/`rhs_nets`) and reports each one as a single
COMBINATIONAL source->target fact -- no re-parsing, the identical primitive the two existing
consumers already use, exposed here as a general data-path fact rather than narrowed to
fabric-route-tracing or register-name-lookup. `extract_always_block_data_path()` reuses
`rtl_control_flow_extraction.py`'s own always-block HEADER scan and `_classify_block_kind`
classifier VERBATIM (imported, never reimplemented, so this module's own "combinational vs.
sequential" answer can never disagree with that module's) and adds the one piece this repo did not
have anywhere else: a bounded literal scan for `<lvalue> (<=|=) <rvalue>;` assignment STATEMENTS
inside each block's own body, reporting the base signal name(s) written (targets) and read
(sources), plus any signal referenced inside the lvalue's OWN bit-select/part-select index (e.g.
`mem[i] <= x;` reports `i` as an additional data-path source, since it selects WHICH bits are
written).

**Same declaration/pattern-level ceiling `design_architecture_ir.py` already discloses for its own
FSM scan, stated identically here rather than re-argued.** The procedural half is a literal/regex
scan over SOURCE TEXT (the continuous-assign half is real syntax-tree evidence, and is reported with
a different `evidence_source` value so a reader can tell the two apart) -- not a second
SystemVerilog parser and not an elaborator. No expression is evaluated, no `generate`/`` `ifdef ``
condition is resolved, no parameter value is resolved, and no proof is ever offered that a
referenced identifier really IS a signal in scope beyond an OPTIONAL cross-check against a
caller-supplied `known_signal_names` set -- when that set is not supplied, every `*_unrecognized`
field is `None`, never a guessed empty/full list, because "not checked" and "checked and found
nothing unrecognized" are different facts. Before scanning for assignment statements, every `if
(...)`/`else if (...)`/`while (...)`/`for (...)`/`case[xz]? (...)` HEADER's own parenthesised
content is blanked out one level deep (length- and newline-preserving, exactly like
`design_architecture_ir._strip_noise_preserve_offsets()`, reused for comments/strings first) -- this
is what keeps a comparison operator inside a condition (`if (a <= b) ...`) from being
mis-recognised as an assignment statement's own `<=`, and an assignment inside a `for (...)` loop's
own header (`for (i = 0; ...)`) is deliberately excluded (loop-index bookkeeping, not a data-path
fact). This module never claims elaboration-time proof of anything: it reports a PATTERN found in
source text (or a real syntax-tree fact for the continuous-assign half), never a proof that the
reported edge is actually exercised, actually correct, or the ONLY path by which a target is ever
written.

**What it reports, per module**: `continuous_assigns` (one COMBINATIONAL_CONTINUOUS_ASSIGN fact per
real `assign`), `always_blocks` (one entry per `always`/`always_ff`/`always_comb`/`always_latch`
header found, carrying the same `block_kind`/`block_kind_reason` `rtl_control_flow_extraction.py`
would report for that identical block, plus every assignment statement found inside it -- or,
honestly, none, when the block genuinely contains no assignment statement this scan's fixed pattern
recognises), and `facts` (both kinds flattened into one uniform-shape list -- `kind`,
`evidence_source`, `block_kind`, `operator`, `targets`, `sources`, `lhs_text`, `rhs_text`, `line` --
the direct "which signals feed this target" query surface; `signals_feeding()`/`signals_fed_by()`
are thin reads over this list, not a second extraction). A module with no continuous assign and no
always block at all reports the whole `data_path_extraction` block `NOT_AVAILABLE` with a real
reason rather than a silently empty `DATA_PATH_EXTRACTED` -- the required negative control proving
the module refuses to fabricate an answer when evidence is absent.

`parse_rtl_file()` wraps ONE real verible run over a file and attaches `data_path_extraction` to
each real parsed module (an unreadable file, an unrunnable verible binary, or a real syntax error
each report a distinct honest status rather than a fabricated one); `build_data_path_ir()` is the
one real multi-file entry point, isolating one file's real syntax error from sinking the whole
build. `save_data_path_ir()` / `format_report()` / `execute_verb()` / `main()` are the standalone
front door: `python -m dv_harness.rtl_data_path_extraction --rtl <f> [--rtl <f> ...] [--verible-bin
...] [--out ir.json] [--json]` (exit 0 the IR was built, 2 NOT_AVAILABLE). No `dv-harness` CLI verb
was wired and `cli.py`/`gates.py` were not touched -- the same disclosed choice several recent
same-day modules in this codebase already make when those two files are under concurrent edit
pressure from many items in the same batch.

**Deliberately bounded, and stated rather than implied closed.** (1) A generate-block-guarded or
`` `ifdef ``-guarded always block or assign is reported exactly as written -- its guard condition is
never evaluated, matching `verible_parser.py`'s and `design_architecture_ir.py`'s own documented
stance. (2) The assignment-statement pattern recognises a plain identifier lvalue, an
indexed/bit-selected lvalue, and a concatenation lvalue split on top-level commas only -- it does
NOT recognise a compound assignment operator (`+=`, `-=`, ...). (3) Only ONE assignment statement's
worth of text is matched at a time via a non-overlapping scan. (4) It decides, approves and
arbitrates nothing beyond reporting: no build, job, or approval is touched, and there is
deliberately no stage gate.

**Disclosed note on this task's own assignment, matching the same pattern several sibling sections
above already record.** The module and its full test suite already existed, complete and passing,
on disk before this gap-closure item began -- built, evidently, by a separate agent in this same
batch whose corresponding CLAUDE.md section had not yet been written. Per REUSE OVER REINVENT, no
parallel module was written; this section documents the pre-existing implementation honestly, after
independently reading its full source and confirming, by direct test, that it already satisfies this
item's assigned scope (declaration/pattern-level data-path extraction over both continuous-assign
and always-block sources, never claiming elaboration-time proof) rather than a narrower or wider
one.

Proven by `dv_harness_tests/test_rtl_data_path_extraction.py` (28 tests,
`python -m pytest dv_harness_tests/test_rtl_data_path_extraction.py -q` -> `28 passed` in this
environment, verible-verilog-syntax present so every real-verible-integration test ran rather than
skipped): pure-function unit tests for the always-block assignment scan and the continuous-assign
fact builder against hand-written SystemVerilog snippets and hand-built verible-shaped dicts (no
verible dependency at all), including the required negative control (no continuous assign and no
always block reports `NOT_AVAILABLE` with a real reason and an empty `facts` list, never a
fabricated `DATA_PATH_EXTRACTED`), the headline boundary proof that a comparison operator sitting
inside an `if`/`else if` CONDITION is never mistaken for a real non-blocking assignment and that
signals used only inside that condition never leak into the real assignments' own data-path facts,
the for-loop-header-exclusion proof, indexed-lvalue index-as-source reporting, concatenation-lvalue
multi-target reporting, sized-literal/system-task exclusion from signal references,
comment/string-noise robustness, and the `known_signal_names` annotate-never-filter contract (both
supplied and omitted). Everything needing real module boundaries then runs the REAL
`verible-verilog-syntax` subprocess against real files written to `tmp_path`: a real module
combining a continuous assign and a real reset/sequential always block, a module with no data path
at all, isolating one real syntax error among several files, a JSON round trip, and the real CLI
subprocess (`--json`, `--out`, and the required-argument-error path). Re-running
`test_design_architecture_ir.py` (30 tests) and `test_rtl_control_flow_extraction.py` (28 tests)
alongside this suite (86 tests combined) confirms zero regressions to either reused module.


<!-- S234: moved verbatim from CLAUDE.md original lines 13585-13666 (M4.6 CLAUDE Context Normalization) -->
## Cross-Subsystem Scenario Parallel-Execution Scheduling (2026-09-07, SYS-25 extension)

The assigned gap was "SystemResourceArbitrationEngine / parallelism scheduler" -- SYS-25's own
"parallelism model", triaged as partially covered by `system_scheduling_plan.py`, with the instruction
to verify that module first and extend it additively rather than replace it.

**REUSE OVER REINVENT, verified rather than assumed.** `system_scheduling_plan.py` already carried a
complete, real "SCENARIO-LEVEL PARALLEL EXECUTION SCHEDULING" section (`scenario_command_ids()`,
`evaluate_scenario_pair_parallel_safety()`, `schedule_scenario_parallel_execution()`,
`render_scenario_parallel_schedule_table()`) from an earlier pass over this same module -- the exact
capability this item asks for: a scheduler deciding which cross-subsystem SCENARIOS (not command
pairs -- SYS-25 already classifies those, and its own docstring says so: "SYS-25 classifies
command-pair RELATIONSHIPS. It schedules nothing") may be dispatched concurrently, given real
shared-resource conflicts. Two things were missing, and both are why this looked like unfinished work
rather than a closed capability: **zero references anywhere in `dv_harness_tests/`** (a repo-wide grep
for `schedule_scenario_parallel_execution`, `evaluate_scenario_pair_parallel_safety` and
`scenario_command_ids` found only the one source file) and **zero CLAUDE.md section** describing it.
So the real work this pass did was verification and closure, not reinvention: trace the evidence chain
to confirm the code's own claim is true, then add the real tests this project's house style requires
before any module counts as done.

**The evidence chain, traced end to end.** The scheduler's own comment claims it re-derives nothing and
reads only this module's already-computed SYS-24 `shared_resource_scheduling` and SYS-25
`parallelism_model` documents. Traced by hand: `plan_shared_resource_scheduling()`'s
`resource_analysis` argument is `system_command_plan.plan_system_commands()`'s own `resource_analysis`
key, which is `system_resource_registry.plan_system_integration()`'s own `resource_analysis` key, which
is `sri.analyze_selected_subsystem_resources(...)["resource_analysis"]` verbatim --
`system_resource_inventory.py` itself, unmodified. So "given `system_resource_inventory.py`'s real
shared-resource conflicts" (this item's own phrasing) is not aspirational: `_command_resource_links()`
reads `sri`'s own `dependencies.command_resource_ids` link, and a scenario pair that both route through
one SYS-24-named shared access point reports `SCENARIO_SERIALIZE_SHARED_RESOURCE` citing that same
resource key.

**What was added.** 16 real tests in `dv_harness_tests/test_system_scheduling_plan.py` (81 passed,
zero skipped, `python -m pytest dv_harness_tests/test_system_scheduling_plan.py -q`), reusing this
suite's own PCIE/USB/LONER synthetic command.txt fixtures rather than inventing a fourth fixture set, so
a scenario-level verdict is checked against a command-level verdict this file already established:
- both scenario shapes `scenario_command_ids()` accepts -- a plain `command_ids` list, and the real
  `system_topology_analysis.plan_system_scenario_model()` (SYS-30) shape whose commands live inside
  `block_plan[].members[].system_command_id`;
- the worst-wins precedence itself (`SCENARIO_SERIALIZE_SHARED_SUBSYSTEM` >
  `SCENARIO_SERIALIZE_SHARED_RESOURCE` > `SCENARIO_SERIALIZE_COMMAND_DEPENDENCY` >
  `SCENARIO_UNKNOWN_PENDING_EVIDENCE` > `SCENARIO_PARALLEL_SAFE`), including a pair that matches BOTH
  the SYS-24 shared-access-point signal and a SYS-25 non-parallel-safe command-pair signal, proving the
  more restrictive one wins while the other is kept in `also_matched`, never silently dropped;
- the two REQUIRED negative controls: a scenario naming a command absent from the SYS-21 IR the
  parallelism model was built from (a typo, or evidence this harness never extracted) reports
  `SCENARIO_UNKNOWN_PENDING_EVIDENCE`, never a guessed `SCENARIO_PARALLEL_SAFE`; and a scenario naming
  no command at all reports the same honest `UNKNOWN` rather than defaulting to safe;
- stable, order-independent scenario-pair ids (`evaluate_scenario_pair_parallel_safety(a, b, ...)` and
  `(b, a, ...)` produce the identical `SCENPAIR-` id);
- `schedule_scenario_parallel_execution()` over three scenarios covers exactly the three unordered
  pairs once each, and its `scenario_execution_boundary` text is checked to still say no job is
  submitted and no scenario body, block, sequencer or arbiter is generated -- the same SYS-40 boundary
  the rest of this module holds;
- `render_scenario_parallel_schedule_table()`'s empty-input placeholder and its real multi-pair render;
- a from-field allowlist check across every signal in a real multi-signal verdict, so a future edit
  that quietly adds a second resource-sharing or command-pair model at this layer would fail loudly
  rather than passing unnoticed.

No source line in `system_scheduling_plan.py` needed to change: the implementation was already correct
against every case this pass could construct, so this is closure of an already-real capability, not a
bug fix.

**Disclosed residual, honestly.** Nothing in this repository CALLS the scheduler yet.
`system_topology_analysis.plan_system_scenario_model()` (SYS-30) is the one real producer of scenario
records in this codebase -- it already builds real `scenario_id`/`participating_subsystems`/
`block_plan` entries -- but `build_system_topology_analysis()` never calls
`schedule_scenario_parallel_execution()` against its own `scenarios["scenarios"]` list, so no report in
this repo currently surfaces an end-to-end scenario-pair verdict. Wiring it in would add a key to
`build_system_topology_analysis()`'s document, which is schema-validated
(`system_topology_analysis.schema.json`, `"additionalProperties": false` at the top level) and already
covered by its own large test suite -- a different module's surface than the one this item names, and
one that plausibly belongs to whichever item covers SYS-28..30 rather than this SYS-25 item. Crossing
into it was left undone rather than risked under this item's bounded scope, matching this project's own
"Deliberately bounded" convention elsewhere. `cli.py` (6,255 lines) and `gates.py` were not touched,
per this batch's own instruction: `system_scheduling_plan.py` already has a real front door
(`dv-harness system-scheduling-plan`) for the SYS-23..27 report, and the scenario scheduler is
reachable today only by direct import (`from dv_harness import system_scheduling_plan as ssp;
ssp.schedule_scenario_parallel_execution(scenarios, ir, scheduling, relationships)`) -- the same
disclosed choice several sibling standalone modules in this codebase already made.


<!-- S241: moved verbatim from CLAUDE.md original lines 14156-14252 (M4.6 CLAUDE Context Normalization) -->
## Signoff Blocker List: the Real "9-Item" Derivation Over Three Real Sources (2026-09-07)

Sections 342-402 (`CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md`) are cited as naming a specific 9-item
signoff-blocker list, but that document is not present anywhere in this checkout -- a repo-wide
`Glob`/`grep` for that filename and for any "9-item"/"nine-item" blocker enumeration (`signoff_blocker`,
`SIGNOFF_BLOCKER`, `blocker_list`) before writing anything matched nothing executable. Per the Evidence
Truth Rule this module never fabricates a specific named list it cannot cite; instead it derives its own
"9-item" list mechanically from what IS real and on disk: `system_closure_aggregator.CLOSURE_DIMENSIONS`
is a fixed, already-vetted 12-name closure taxonomy, and exactly THREE of those twelve already have
their own individually-named, more specific real source in this same task brief -- `functional_coverage`
(`functional_coverage_signoff.py`'s own Closure verdict), `waiver_status` (`waiver_store.py`'s own
`status_report()`), and `evidence_integrity` (`evidence_integrity_states.py`, this batch's sibling item).
Removing exactly those three from the real, fixed twelve leaves exactly NINE remaining names, verbatim
from `CLOSURE_DIMENSIONS`: `protocol_coverage`, `requirement_closure`, `regression_status`,
`error_propagation`, `build_composition`, `performance_closure`, `security_closure`,
`arbitration_closure`, `change_impact_closure`. `dv_harness/signoff_blocker_list.py`'s own
`BLOCKER_CATEGORIES` is that residual nine, and `_assert_nine_item_derivation()` (run at import) holds
the `12 = 3 + 9` arithmetic as a real, testable check rather than a comment that can silently drift --
the same "found nothing executable, so build the mechanism from the real named sources instead"
precedent `golden_subsystem_benchmark.py`/`intake_events.py` already set for an unwritten master
enumeration.

**What the module actually reads -- read-only aggregation, nothing invented.**
`derive_signoff_blockers(root)` reads the three natively-resolved sources itself: `waiver_store.
status_report(root)` (UNMET the instant any recorded waiver is not VALID, naming every offending
waiver_id; MET when the store exists and every waiver is VALID, including zero recorded; NOT_AVAILABLE
with no ledger at all); `functional_coverage_signoff.analyze_functional_coverage_signoff(root)` (MET only
on a real SIGNOFF_READY, UNMET on OPEN/BLOCKED_BY_WAIVER naming the real closure_percent/blocking
waivers, UNKNOWN on INCOMPLETE_EVIDENCE, NOT_AVAILABLE when its own inputs are unavailable); and
`evidence_integrity_states.classify_project_evidence_integrity(root)` -- discovered, mid-task, to
already be real and present in this checkout (this batch's sibling item landed from a parallel agent
in this same batch). That module's own six-value project rollup (VALID/STALE/SUPERSEDED/CONTRADICTED/
CORRUPT/UNKNOWN, or a real NOT_AVAILABLE over zero recorded evidence) is not a vocabulary
`system_closure_aggregator`'s own generic alias table is taught to read, so `signoff_blocker_list.py`
carries its own small, disclosed mapping (`_EVIDENCE_INTEGRITY_PROJECT_STATUS_TO_DIMENSION`): VALID and
the sibling module's own-documented "merely-informational" SUPERSEDED both clear (MET);
STALE/CONTRADICTED/CORRUPT each a real, named integrity defect and block (UNMET); UNKNOWN stays UNKNOWN.
A caller already holding a real `evidence_integrity_states` report may pass it directly via
`evidence_integrity_report`; absent that, the one real call is tried and ANY failure (an import error,
an exception from the call) reports NOT_AVAILABLE -- **the module's own required negative control**: the
sibling module or its call being unavailable never silently reads as clear or blocked.

The remaining nine `BLOCKER_CATEGORIES` have no real source named anywhere in this task -- this module
does not invent one. A caller with real evidence for any of them supplies it via
`residual_dimension_records`, the exact generic `{dimension_name, status}` shape
`system_closure_aggregator.aggregate_system_closure()` already accepts; supplying nothing is honestly
`NOT_SUPPLIED`, never a guessed MET. All twelve records are folded through `aggregate_system_closure()`
ITSELF -- imported, not re-implemented -- so the worst-wins rule (a single UNMET dimension blocks the
whole rollup regardless of how many others are clean; an UNKNOWN/NOT_AVAILABLE/NOT_SUPPLIED dimension is
honestly `INCOMPLETE_EVIDENCE`, never silently CLOSED or NOT_CLOSED) is the SAME rule, not a second
implementation that could drift out of agreement with it. `signoff_status` reuses
`system_closure_aggregator`'s own CLOSED/NOT_CLOSED/INCOMPLETE_EVIDENCE vocabulary verbatim.

**The real, human-facing headline.** `signoff_blockers` is every dimension the fold actually found UNMET
right now, individually, with its real reason(s) and (for the three natively-resolved dimensions) the
underlying detail a human needs to act on it (which waiver, which coverage bin) -- never collapsed into
a bare count, never padded to nine/twelve entries when fewer are actually open, and never omitted for
being empty. `incomplete_evidence_dimensions` is kept honestly separate: a dimension nobody has evidence
for yet is NOT a blocker (that would be an unearned "something is wrong" claim about evidence nobody
supplied), mirroring `system_closure_aggregator.py`'s own `blocking_dimensions`/`incomplete_dimensions`
split. A caller-supplied residual record naming one of the three natively-resolved dimensions is not
dropped: it is forwarded through unchanged, so a genuine disagreement with this module's own derivation
surfaces as `AMBIGUOUS_CONFLICTING_SUBMISSIONS` (system_closure_aggregator's own arbitration boundary)
rather than this module silently picking one.

This module decides, approves and arbitrates nothing: no build, gate script, regression, or LSF job
runs; no waiver is recorded or revoked; no approval is minted; nothing is written to disk. There is
deliberately no `STAGE_GATES` entry and no `dv-harness` CLI verb -- `gates.py`/`cli.py`/`dashboard.py`
are large, actively-edited files outside this task's own file-safety scope, the same disclosed choice
several recent modules in this project already make. Front door: `python -m
dv_harness.signoff_blocker_list --project-root <dir> [--residual-dimensions <file.json>]
[--evidence-integrity <file.json>] [--markdown]` (exit 0 CLOSED, 1 NOT_CLOSED, 2 INCOMPLETE_EVIDENCE or a
usage/read error).

Proven by `dv_harness_tests/test_signoff_blocker_list.py` (35 tests, `python -m pytest
dv_harness_tests/test_signoff_blocker_list.py -q` -> `35 passed`) against REAL producers throughout --
waivers through the real `waiver_store.record_waiver()`, coverage numbers in a real DuckDB
`EvidenceStore` via `insert_coverage_sample()`, the declared coverage-goal scope through a real,
schema-valid `env.manifest.json` built by `env_manifest.generate_env_manifest()` -- the identical
fixture recipe `test_functional_coverage_signoff.py`'s own suite already established, reused rather than
reinvented. The 9-item derivation itself is proven directly (exact size, no overlap with the three
natively-resolved names, exact partition of the real 12, and the import-time guard shown to actually
raise on a broken partition). The central negative controls: a bare project with none of the three
sources present and no caller-supplied residual records reports zero blockers and
`INCOMPLETE_EVIDENCE` overall, never a fabricated blocker and never a silently-CLOSED verdict; the
`evidence_integrity_states` call failing (simulated via monkeypatch, standing in for the sibling module
being genuinely absent) reports `NOT_AVAILABLE`, never a guessed clear or blocked verdict, and is never
counted as a blocker while genuinely unmeasured; an expired waiver blocks signoff and names the specific
waiver_id; a partial coverage closure blocks signoff with the real percent; one genuinely UNMET residual
dimension among an otherwise-clean twelve still reads the whole rollup NOT_CLOSED (worst-wins) and is
the only entry in `signoff_blockers`; a caller-supplied conflicting record for a natively-resolved
dimension surfaces `AMBIGUOUS_CONFLICTING_SUBMISSIONS` rather than being silently dropped or
arbitrated; and all six of `evidence_integrity_states`'s own real status values are proven to map onto
the correct MET/UNMET/UNKNOWN/NOT_AVAILABLE dimension status, one parametrized case per value. Both CLI
exit-code paths (0 CLOSED, 1 NOT_CLOSED, 2 INCOMPLETE_EVIDENCE/usage error) are driven as real
subprocesses.


<!-- S243: moved verbatim from CLAUDE.md original lines 14335-14399 (M4.6 CLAUDE Context Normalization) -->
## CPUREAD Byte-Shift Correction Checker (2026-09-06, self_check_list.md #25)

Nothing in this repo checked whether a project's CPUREAD task/bridge implementation performs the
byte-shift correction an unaligned sub-word read needs -- confirmed by direct grep
(`byte_shift`/`cpuread` across `dv_harness/`/`tools/`) before writing anything: the only real hits
were `bind_mechanism_generator.py`'s own docstrings *naming* CPUREAD/CPUWRITE bridge tasks, never a
check of what those tasks actually DO with an unaligned address.

**What "byte-shift correction" means here, grounded in real evidence, not assumed.**
`reference/USB_UVM_Handoff/uvm/tb/top/usb_apb_arb.sv` -- this project's own real reference
implementation -- dispatches every CPU-side APB access at a WORD-ALIGNED address
(`{addr[31:2], 2'b00}`) regardless of the macro's own transfer width, because the underlying bus
always returns a full 32-bit word. For a sub-word read (`READ1B`/`READ2B`) the returned word is
therefore NOT yet the requested byte/halfword -- it still has to be shifted into the correct lane
using the address's own low bits, exactly as the real model this bridge stands in for already does
(cited in the module's own docstring: `MODEL_ALL.v:2031 rdata <= prdata[raddr[1:0]*8 +: 8];  //
GSIHOSTREAD1B`) and which `usb_apb_arb.sv` itself reproduces: `READ1B`'s `int lane = addr[1:0]; ...
data = 32'(tmp[8*lane +: 8]);`, `READ2B`'s `32'(tmp[16*lane[1] +: 16]);`, and `READ4B`'s plain
`data = tmp;` -- no shift, because a full 32-bit word needs no byte-lane correction at all.

`dv_harness/cpuread_byte_shift_checker.py` is the generalizable checker, and it reuses this
project's own real task-resolution machinery rather than writing a second one: `command_task_trace.
trace_command()`'s TASK_MACRO leg is the ONLY thing that decides how a DE command name resolves
inside a real generated environment; this module never re-derives that resolution, and a leg it
reports AMBIGUOUS or NOT_FOUND is reported as exactly that, never guessed past.
`de_command_style_learning.build_de_command_registry()` is reused (via `discover_cpuread_commands()`)
to find which CPUREAD-shaped commands a real DE `command.txt`-style file actually contains, filtered
to DUT-side register-read context through `reference_pattern_audit._classify_context`. The ONE new
step this module adds on top of the TASK_MACRO leg is following a macro-redirect target ONE level
further (reusing `command_task_trace`'s own `_TASK_BODY_RE_TMPL` task-body regex) to locate the real
task body, then a new evidence-based CORRECTNESS check (does the output-data assignment reference the
address argument, or a local variable derived from it, combined with a `*8`/`*16` lane-select or
shift).

**Grounded against real generated output, not assumed.** `audit_apb_bridge_entries_byte_shift()` runs
this module's byte-shift analysis over `bind_mechanism_generator.emit_apb_bridge_tasks_sv()`'s own
REAL generated task text for a `direction="READ"` entry. Doing so is itself a real, disclosed finding
of this gap-close: that generator's current READ-direction template (`data = req.{data_field};`)
references the VIP data field only and never the address argument at all, so this checker correctly
reports `BYTE_SHIFT_MISSING` for any sub-word entry built from it -- disclosed here rather than
silently left unmentioned, and left for a future gap-close item.

**Evidence Truth Rule, applied via a closed status vocabulary that never collapses "could not
decide" into a verdict**: `BYTE_SHIFT_PRESENT` / `BYTE_SHIFT_MISSING` /
`NOT_APPLICABLE_FULL_WORD_TRANSFER` / `WIDTH_UNKNOWN` / `ARGUMENTS_UNKNOWN` / `COMMAND_NOT_FOUND` /
`AMBIGUOUS_TASK_RESOLUTION` (proven by a dedicated negative-control test to never be silently
resolved into a guess) / `TASK_BODY_NOT_LOCATED` / `BLOCKED`.

Proven by `dv_harness_tests/test_cpuread_byte_shift_checker.py` (24 tests, all passing): direct
positive/negative controls against `usb_apb_arb.sv`'s real `READ1B`/`READ2B`/`READ4B` bodies; DUT-vs-
HOST context filtering; end-to-end audits over bare-identifier and hierarchical macro-redirect shapes,
a command absent from the environment, and two conflicting `task CPUREAD1B` declarations across two
files (`AMBIGUOUS_TASK_RESOLUTION`, never a guessed verdict); and the real-generator grounding test
against `bind_mechanism_generator.emit_apb_bridge_tasks_sv()`'s own output. Regression-checked against
`test_command_task_trace.py`, `test_de_command_style_learning.py`, `test_reference_pattern_audit.py`
(54 combined) and `test_bind_mechanism_generator.py` (35), all still passing. Re-verified fresh by
this integration pass: `python -m pytest dv_harness_tests/test_cpuread_byte_shift_checker.py -q` ->
24 passed.

**Disclosed residual**: this module is a standalone checker (no `dv-harness` CLI verb, no
`gates.py`/`STAGE_GATES` entry, no engine call site -- a REACHED capability, not a WIRED one). It
never fixes a detected `BYTE_SHIFT_MISSING` finding, and it does not verify that
`DEFAULT_WORD_BYTES = 4` is correct for every project -- it is an explicit, overridable parameter,
defaulted from this project's own real 32-bit APB evidence, never a silent universal assumption.


<!-- S244: moved verbatim from CLAUDE.md original lines 14400-14454 (M4.6 CLAUDE Context Normalization) -->
## UVM Bridge Task Body Generation: Real APB-Sequence-Calling, Never a Bare Placeholder (2026-09-06)

Audit-first finding (self_check_list.md #27): `dv_harness/uvm_generator/bind_mechanism_generator.py`
had exactly two emitters -- `emit_bind_sv()` (evidence-gated `bind` statements) and `emit_hook_svh()`
(macro redirect table + a caller-supplied `top_scope_decls` string + `initial run_test();`). Neither
ever generated the BODY of a CPUREAD/CPUWRITE bridge task: `emit_hook_svh()` only redirects, e.g.,
`` `define CPUWRITE1B dv_uvm_cpuwrite1b ``, and drops in whatever `top_scope_decls` text a caller
supplies verbatim. The one real generated example this repo ships,
`examples/generated_usb_real_evidence_v1/bind/dv_uvm_hook.svh:18`, confirmed the consequence: a bare
`// TODO_PLACEHOLDER: bridge instance(s) connecting dv_uvm_cpuwrite*b to the real DUT register-write
path go here -- not yet designed in this pass`. So the confirmed gap was not "raw pin-level bridging
instead of real APB-sequence-calling" -- it was that **no bridge task body of either kind had ever
actually been generated**.

`ApbBridgeTaskError` / `validate_apb_bridge_entries()` / `emit_apb_bridge_tasks_sv()` close it,
additively, in the same file and with the same evidence discipline `emit_bind_sv()`/
`validate_bind_entries()` already established: every VIP sequencer path, transaction class, and
field name in `bridge_entries` must be caller-supplied evidence, never invented -- a
missing/duplicate/invalid field is a hard `ApbBridgeTaskError`, never a silently emitted or guessed
task body. The emitted task body is a real UVM sequence-item dispatch --
`uvm_create_on(req, <cited sequencer>)` / `req.randomize() with {...cited fields...}` /
`<cited sequencer>.execute_item(req)` -- using only standard, project-agnostic UVM API (never a raw
pin-level force/deposit, and never a fabricated VIP field/class name). This is deliberately the
minimal generic default, not a reimplementation of a project's own richer arbiter-plus-persistent-
sequence design (the real `USB_UVM_Handoff/uvm/tb/seq/usb_apb_bridge_seq.sv` +
`uvm/tb/top/usb_apb_arb.sv` pattern) -- that reference was read to ground what "real
APB-sequence-calling" means architecturally, never mined for its USB-specific content, per No
Golden-Reference Content Mining. The output is designed to be handed straight to `emit_hook_svh()`'s
existing `top_scope_decls` parameter, closing the exact `TODO_PLACEHOLDER` gap the shipped example
carries.

Proven by 15 tests appended to `dv_harness_tests/test_bind_mechanism_generator.py` (35 total, all
passing, re-verified fresh by this integration pass: `python -m pytest
dv_harness_tests/test_bind_mechanism_generator.py -q` -> 35 passed): positive emission for both WRITE
and READ directions; 9 missing-required-field negative controls (parametrized); invalid-direction and
duplicate-task-name refusals; a cited-xact-type-field-without-a-matching-enum negative control; the
crux assertion set proving the emitted task actually calls a real UVM sequence item against the real
cited sequencer with a negative control that no `force`/`deposit` text appears anywhere in the
emitted task body; and an integration test proving the bridge-task output composes directly into
`emit_hook_svh()` and eliminates the `TODO_PLACEHOLDER`. `dv_harness_tests/test_connectivity.py` and
`dv_harness_tests/test_uvm_structural_lint.py` were re-run alongside it (266 tests, 301 combined) with
no regressions.

**Deliberately bounded, and stated rather than implied closed.** (1) This closes the code-path gap
(a real generator function now exists and is evidence-gated); it does not itself wire
`emit_apb_bridge_tasks_sv()` into `create_environment()`'s or `protocol_env_generator.py`'s real
manifest-driven generation flow, and no manifest schema field was added to carry `bridge_entries` for
a project to declare them from -- that wiring, and the corresponding manifest-schema addition, is a
follow-up integration step, not part of this audit-first close. (2) It emits a generic, single-item
`execute_item()`-based bridge, not the richer persistent-sequence-plus-arbiter architecture a project
may already have hand-authored -- that remains a legitimate, separately-evidenced project-specific
alternative this generator does not attempt to reproduce. (3) No live simulator, build, regression, or
LSF job was run to verify the emitted SystemVerilog compiles; verification here is limited to the real
text this generator produces matching the required UVM API shape, per this task's own scope.


<!-- S248: moved verbatim from CLAUDE.md original lines 14615-14672 (M4.6 CLAUDE Context Normalization) -->
## System FW Service Registry: Per-SYSTEM branch_fw Ownership Across Composed Subsystems (2026-09-06)

CLAUDE_L5_SYSTEM_LEVEL_COMPOSITION_FACTORY.md asks for a per-SYSTEM (not per-subsystem) registry of
`branch_fw` service-loop ownership across composed subsystems. The gap sat between two existing
modules, neither of which answered it: `shared_bus_resource_registry.py` detects a `branch_fw`-vs-
`branch_a*` race, but strictly INTRA-subsystem, with no concept of a SYSTEM composed of several
subsystems at all; `system_resource_inventory.py` (SYS-9..14) is CROSS-SUBSYSTEM, but its resource
taxonomy's `FIRMWARE_AGENT` is a classified VIP/UVM component instance, a completely different thing
from `branch_fw` (a `command.txt` pattern TASK-COMPOSITION role -- the per-port service loop, per
`pattern-architecture` SKILL.md section 1) -- nothing in that module validates a branch LABEL against
the `block`/`branch_a*`/`branch_fw`/`branch_b*` ownership rules.

`dv_harness/system_fw_service_registry.py` closes exactly that gap, reusing rather than reinventing
both halves it needs. FW classification/validation of a declared `branch_label` (is it the canonical,
correctly-tiered `branch_fw`?) is `branch_ownership_resolver.validate_branch_assignment()`, called
directly. Cross-subsystem evidence (system-level ACTIVE_DRIVER_CONFLICT,
STOP_AUTOMATIC_INTEGRATION/HOLD_PENDING_EVIDENCE, SAME_PHYSICAL/SHARED_LOGICAL relationships) is
`system_resource_inventory.real_cross_subsystem_findings()`'s own output, consumed through its own
status vocabulary (`CROSSCHECK_AVAILABLE`/`CROSSCHECK_UNAVAILABLE`, imported by name). Neither
mechanism is re-derived.

**Evidence, honestly.** No `command.txt`/pattern-body parser exists anywhere in this codebase, so
WHICH real `resource_id`(s) a subsystem's `branch_fw` loop writes is a CALLER-DECLARED fact
(`fw_owned_resource_ids`), never inferred. A subsystem declaring none reports the honest
`NOT_APPLICABLE_NO_FW_RESOURCES_DECLARED`, never a false `CLEAR`. When no `cross_subsystem_findings`
were supplied, or the supplied findings report `CROSSCHECK_UNAVAILABLE`, every entry's cross-subsystem
status is the honest `UNKNOWN_CROSS_SUBSYSTEM_ANALYSIS_UNAVAILABLE` -- never silently treated as clear.

**Worst-wins composite verdict.** This module is a per-SYSTEM rollup/gate: the overall `status` is the
single worst entry status across every declared subsystem, never an average or a majority vote
(`_ENTRY_SEVERITY_ORDER`/`_worst_entry_status()` are the one place severity order is defined and
applied). One subsystem with an invalid `branch_fw` assignment, or one whose `branch_fw`-owned
resource is system-level driver-conflicted, fails the whole registry regardless of how many other
subsystems are clean.

**Scope boundary -- detection/recording only.** It never edits a pattern file, never renames a branch,
never arbitrates a resource-ownership conflict (that stays `system_resource_inventory.py`'s SYS-11/12
territory), and touches no approval/governance mechanism. No file I/O or subprocess call anywhere in
its analysis path -- every input is a plain dict/list; `find_system_fw_service_registry_for_root()` is
the one thin convenience wrapper that calls the real `system_resource_inventory` front door for a real
project root.

No `dv-harness` CLI verb was wired -- `cli.py`/`gates.py` are out of scope, the same disclosed choice
several recent same-day modules already make. Front door: `python -m
dv_harness.system_fw_service_registry --input <file.json> [--json]` (0 CLEAR, 1 BLOCKED, 2
UNKNOWN/HELD/NOT_APPLICABLE).

Proven by `dv_harness_tests/test_system_fw_service_registry.py` (30 tests): every test drives the real
`build_system_fw_service_registry()`, which itself drives the real
`branch_ownership_resolver.validate_branch_assignment()` -- never a mock. Negative controls prove the
module reports UNKNOWN/NOT_APPLICABLE rather than a fabricated CLEAR when evidence is absent (declared
`fw_owned_resource_ids` with no cross-subsystem findings supplied; a `CROSSCHECK_UNAVAILABLE` findings
block). Worst-wins is proven directly (one BLOCKED subsystem among clean siblings still fails the whole
registry; BLOCKED beats UNKNOWN beats HELD beats CLEAR). Reuse is proven by a static source check (no
second branch-name regex defined in this module) and a direct value-equality check against
`validate_branch_assignment()`'s own real output. The real CLI is driven as a subprocess across all
documented exit codes.


<!-- S249: moved verbatim from CLAUDE.md original lines 14673-14727 (M4.6 CLAUDE Context Normalization) -->
## SystemScenarioIR / SystemScenarioGraph: a Typed Scenario Record + Dependency Graph, Reusing SYS-30 and pattern_fragment_ir.py (2026-09-07)

`system_topology_analysis.py`'s SYS-30 half already answers "what SHAPE would a multi-subsystem
scenario have" -- one scenario record per SYS-27-supported flow or SYS-25-coupled subsystem pair,
complete with a PARALLEL/SEQUENTIAL block plan and a syntax-derivation record, every scenario's
`scenario_body_status` pinned to `NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL`. Nothing turned that
scenario LIST into a typed record a consumer could reason about without re-discovering its dict shape,
and nothing asked whether two cross-subsystem scenarios in one selection actually DEPEND on each other
-- a repo-wide grep for `SystemScenarioIR`/`SystemScenarioGraph`/`scenario_dependency` matched nothing,
and `pattern_ir_assembly.py`'s own "ScenarioIR" was confirmed to be an unrelated, narrower per-subsystem
shape (one scenario's own five `PatternIR` layers), never a system-scope multi-subsystem record.

`dv_harness/system_scenario_ir.py` closes both gaps, and re-derives neither module it builds on:

- **`SystemScenarioIR`** wraps one SYS-30 scenario record verbatim -- every field not added here
  (participating subsystems, the block plan, the syntax-derivation record, the pinned body status) is
  read straight off that record. `build_system_scenario_ir()` REFUSES to construct one whose
  `scenario_body_status` has drifted off the pinned value, or that carries any body-shaped key
  (`scenario_body`/`command_txt`/...) -- the exact boundary `system_topology_analysis.py`'s own
  `assert_no_emitted_artifacts()` enforces one level up, inherited rather than restated weaker.
- **Structural subsystem coupling** (`derive_subsystem_coupling_edges()`) is a real, mechanically-derived
  `SHARES_SUBSYSTEMS` edge between two scenarios in one selection whose own `participating_subsystems`
  lists intersect -- explicitly never read as an ordering decision (that stays SYS-24's shared-resource
  scheduling question, already `system_resource_registry.py`'s/`system_scheduling_plan.py`'s job).
- **Dependency-chain readiness** (`check_system_scenario_dependency_readiness()`/
  `build_system_scenario_graph()`) CALLS `pattern_fragment_ir.check_fragment_chain_readiness()`
  directly -- never reimplements it. A `SystemScenarioIR` is adapted into that function's own fragment
  shape (`_as_fragment_shaped()`); a caller-declared cross-scenario precondition/postcondition is
  retagged onto that function's `DERIVED_UNRESOLVED_CONSUMED_EVENT`/`DERIVED_UNCONSUMED_PRODUCED_EVENT`
  source values (never its `DECLARED` one, which that function treats as an already-known-true fact
  needing no earlier supplier) -- a deliberate, disclosed reuse of that tag's own documented meaning
  over a caller-declared fact rather than a mechanically-derived one, since SYS-21's `system_command_ir`
  entries carry no produced/consumed event field at all to derive one from mechanically.

**Evidence Truth Rule.** Every declared precondition/postcondition requires a real, non-empty `reason`
citation; `build_system_scenario_ir()` refuses one that lacks it. A scenario model planning zero
scenarios (an honest SYS-30 state) builds a graph with an empty scenario list and a trivially-covered
dependency report, never an error.

**Deliberately bounded.** No new arithmetic over address maps, clock/reset domains or command routing
is performed -- every non-added field is SYS-30's own. There is no `dv-harness` CLI verb
(`cli.py`/`gates.py` untouched, per this repo's own disclosed convention when those files are under
concurrent batch-edit pressure); the front door is `python -m dv_harness.system_scenario_ir` plus
`build_system_scenario_graph_from_plans()` for a caller already holding a real command/scheduling plan
pair.

Proven by `dv_harness_tests/test_system_scenario_ir.py` (33 tests), every scenario fixture built
through the REAL `system_topology_analysis.plan_system_scenario_model()` over a small hand-built
command/scheduling plan pair -- never a hand-typed scenario dict. Negative controls: a malformed/
duplicate scenario record, a body status pried off its pinned value, a forbidden body-shaped key, and
an uncited declared precondition/postcondition (missing `event` or `reason`) are all refused. Genuine
delegation to `pattern_fragment_ir.py` is proven directly: its own `ORDER_MISMATCH` error surfaces
verbatim through this module's wrapper. The dependency-chain check is proven to distinguish a covered
vs. uncovered scenario order over a real declared A-B/B-C link dependency sharing subsystem B.


<!-- S250: moved verbatim from CLAUDE.md original lines 14728-14771 (M4.6 CLAUDE Context Normalization) -->
## SystemCommandGrammarIR: System-Scope Command-Formatting-Convention Composition (2026-09-06/07)

`dv_harness/system_command_grammar_ir.py` answers a system-scope question no other module in this
codebase asks: when several subsystems each carry their own real DE `command.txt`-style FORMATTING
convention (separator style, argument format, comment format, phase markers, ordering rules -- the
same five facets `de_command_style_learning.CommandStyleIR` already pattern-detects, one IR per
subsystem's own file), do those subsystems' conventions actually AGREE closely enough to call the
composed SYSTEM one coherent grammar, or do two or more of them genuinely DISAGREE?

**Reused, not re-derived.** The module imports `de_command_style_learning.CommandStyleIR`/
`learn_command_style` directly and composes their already-detected per-facet values; it performs no
`command.txt` parsing of its own. It is explicitly a different grain from
`system_command_plan.py` (SYS-18..22), which answers whether a command NAME routes correctly and
whether command SEMANTICS collide across subsystems -- never FORMATTING style; this module adds
nothing to that module's own SYS-22 collision vocabulary and never imports it.

**Per-facet composition, never collapsed.** Each of the five facets independently resolves to one of
`UNIFORM` (every subsystem with real evidence agrees), `AMBIGUOUS` (the subsystems with evidence agree,
but at least one other subsystem has none), `CONFLICTING` (two or more subsystems with real evidence
genuinely disagree -- `system_convention` stays `None`; this module never picks a winner), or
`NOT_AVAILABLE` (no subsystem has evidence for that facet at all). The system-level verdict is
worst-wins over the five facets (CONFLICTING beats AMBIGUOUS beats a real per-facet NOT_AVAILABLE,
which is treated as a confirmed benign absence rather than a defect, matching this project's own
composite-gate convention of never letting an averaged fold hide a genuine problem in one facet).

`_assert_absence_tokens_current()` runs at import and re-verifies, against a real empty-file call into
`learn_command_style()`, that this module's own hand-copied absence-token table
(`NOT_AVAILABLE`/`NOT_FOUND`, since the two token spellings genuinely differ across the five facets in
the underlying module) has not drifted out of sync with the real producer -- a defensive check this
module's own docstring credits to exactly this kind of hand-copied-table drift risk.

There is no `dv-harness` CLI verb (`cli.py`/`gates.py` untouched, matching this repo's own disclosed
convention under concurrent batch-edit pressure); front door is
`python -m dv_harness.system_command_grammar_ir --subsystem ID=PATH [--subsystem ID=PATH ...] [--json]`
(exit 0 UNIFORM/NOT_AVAILABLE, 1 CONFLICTING).

Proven by `dv_harness_tests/test_system_command_grammar_ir.py` (20 tests): the absence-token
self-check against a real `learn_command_style()` call; each of the four per-facet statuses, including
a genuine CONFLICTING separator-convention disagreement between two synthetic subsystems and an
AMBIGUOUS case where only some subsystems have evidence; the honest NOT_AVAILABLE-vs-defect distinction
in the worst-wins fold; and the real CLI driven end to end. Every fixture is a small synthetic
`command.txt`-style file built inline in the test file, never real project content, matching
`test_de_command_style_learning.py`'s own precedent.


<!-- S251: moved verbatim from CLAUDE.md original lines 14772-14809 (M4.6 CLAUDE Context Normalization) -->
## SystemTransactionIR: Composing amba_transaction_ir.py's Per-Fabric Facts Across Subsystems (2026-09-07)

`amba_transaction_ir.py` (SYOSCB-10) already gives one AMBA fabric's per-port transaction a typed
22-field shape (`AMBA_TRANSACTION_IR_FIELDS`), built per `AMBA_PORT_REGISTRY` row via
`build_transaction_ir_template()`/`build_transaction_ir_templates()`. That module is entirely
SINGLE-FABRIC / SINGLE-SUBSYSTEM scope by construction -- it has no notion of a second, separately-
composed subsystem's fabric existing at all. `dv_harness/system_transaction_ir.py` is the missing
system-scope layer, composing N subsystems' own ALREADY-BUILT `amba_transaction_ir` per-fabric
templates (caller-supplied, never rebuilt or discovered by this module) across caller-declared,
evidence-cited `system_transaction_links` (real facts naming which two subsystems' ports form one
cross-subsystem transaction path).

**Reuses the field shape literally, never a second vocabulary.** For each link it echoes all 22 reused
fields side by side from each side's own already-computed `{value, origin}` facts -- never merging or
arbitrating a genuine cross-fabric disagreement (e.g. an AXI4 master bridged to an APB slave
legitimately disagreeing on `protocol`) -- and reports one of three honest statuses per link
(`LINK_BOTH_SIDES_RESOLVED` / `LINK_SIDES_PARTIALLY_RESOLVED` / `LINK_UNKNOWN_PORT`), reusing
`amba_transaction_ir.unresolved_ir_fields()`/`assert_ir_templates_complete()` verbatim rather than
re-deriving completeness. A project declaring no cross-subsystem links reports `NOT_APPLICABLE` (never
a vacuous COMPLETE or fabricated INCOMPLETE). Worst-wins folding for the whole-IR overall status,
matching every composite IR/gate in this codebase. Imports nothing from
`amba_route_transform_predictor.py` (route/transform prediction stays that module's job) or
`transaction_correlation_ir.py` (cross-transaction correlation stays that module's job).

No `dv-harness` CLI verb was added and `gates.py`/`cli.py`/`CLAUDE.md` were not touched (file-safety
scope, matching several sibling same-day modules' own disclosed choice); front door is
`python -m dv_harness.system_transaction_ir fields|build`.

Proven by `dv_harness_tests/test_system_transaction_ir.py` (37 tests): a real cross-protocol bridge
disagreement is reported with both distinct values rather than merged/picked; a real discovery gap on
either side (unresolved `clock_domain` via `BIND_CHECK_UNKNOWN_VALUE`, unresolved
`destination_hierarchy` via `ENDPOINT_HIERARCHY_NOT_ESTABLISHED`) is surfaced honestly rather than
silently treated as resolved; an unknown `(subsystem, port)` reference on either side of a link reports
`LINK_UNKNOWN_PORT` rather than a guess; a malformed per-fabric template (missing the mandated `fields`
key) is refused via the real `amba_transaction_ir.assert_ir_templates_complete()` rather than silently
accepted; and worst-wins folding is proven directly. The pre-existing `test_amba_transaction_ir.py`
suite (51 tests) was re-run unchanged and still passes, confirming no regression to the reused module.


<!-- S252: moved verbatim from CLAUDE.md original lines 14810-14858 (M4.6 CLAUDE Context Normalization) -->
## SystemVirtualSequencer: Per-Subsystem Composition Mode Under a System-Level Virtual Sequencer (2026-09-07)

A record of how each REGISTERED subsystem's own virtual sequencer should compose under one
SYSTEM-LEVEL virtual sequencer, derived from `verification_architecture.py`'s already-computed
`VipBindIR` wrapper/bridge chain classification -- never re-derived here. Two real, adjacent
mechanisms already touch "system virtual sequencer" and neither answers this question:
`uvm_generator/soc_environment_composer.py`'s `_build_virtual_sequencer_fields()` is the real
GENERATOR (one `<protocol>_virtual_sequencer` field per registered subsystem, protocol-blind), and
`generation_readiness.py`'s `system_virtual_sequencer` row only checks that the composer's own
functions resolve through the import system -- a capability-existence check. Neither asks whether a
given subsystem's own bind chain to the DUT crosses a real protocol/width conversion point, which
determines whether the system-level virtual sequence can safely reuse that subsystem's own
virtual-sequencer handle directly.

`dv_harness/system_virtual_sequencer.py` is that record. It reuses
`verification_architecture.build_vip_bind_ir()`'s output verbatim -- reading only a supplied
`VipBindIR`'s `chain_classification`/`target_instance`/`chain_path`/`source_evidence` fields, imported
from `verification_architecture.CHAIN_CLASSIFICATIONS` for the vocabulary check rather than a second
copy of it. Class/field naming reuses `uvm_generator.generator.sv_id()` -- the SAME identifier-
normalization function the real generator's own `_build_virtual_sequencer_fields()` uses, so a name
this module reports can never disagree with what the generator would actually emit.

**Worst-wins composite gates, folded twice.** Per-subsystem `composition_mode` folds ALL of that
subsystem's own supplied `VipBindIR` records worst-first: a single `BRIDGE_IN_PATH` chain anywhere
makes the WHOLE subsystem `ADAPTER_REQUIRED`; absent any bridge, a single `UNKNOWN` chain makes it
`COMPOSITION_UNDETERMINED`; only when every chain is `DIRECT`/`WRAPPER_ONLY` does it read
`DIRECT_HANDLE`; a subsystem with no `VipBindIR` evidence at all is honestly `NOT_AVAILABLE`. The
whole-system rollup applies the identical worst-wins rule one level up over every subsystem's own
`composition_mode`. Zero subsystems supplied is `NOT_AVAILABLE`, never a vacuous READY over nothing.

**What this module does not do -- deliberately bounded.** It is a RECORD, not a generator: it writes
no `.sv` file, emits no UVM source, and never calls `soc_environment_composer.
compose_soc_environment()`. "ADAPTER_REQUIRED" names the fact that one is needed and cites the real
bridge evidence, never inventing what that adapter's sequence body should do. It reads no RTL, VIP
source, or spec document itself -- every fact traces to a `VipBindIR` a caller already built.

Front door: `python -m dv_harness.system_virtual_sequencer --subsystems <file.json> [--json]
[--markdown]` (exit 0 `READY_DIRECT_COMPOSITION`, 1 `ADAPTER_REQUIRED`, 2
`INCOMPLETE_EVIDENCE`/`NOT_AVAILABLE`/usage error). No `dv-harness` CLI verb was added and
`cli.py`/`gates.py` were not touched.

Proven by `dv_harness_tests/test_system_virtual_sequencer.py` (33 tests), built through the REAL
`verification_architecture.build_vip_bind_ir()` pipeline (real bind entries, real hop lists classified
by that module's own `classify_wrapper_bridge_hop()`) rather than a hand-typed stand-in for a
VipBindIR's own shape: the worst-wins fold at both levels, both real-instance and `.to_dict()`-shape
input acceptance, the naming-convention agreement with `uvm_generator.generator.sv_id()`, the
vocabulary guard's real detection power (monkeypatched to prove it actually trips), markdown/JSON
rendering, and all four CLI exit codes driven as real subprocesses.


<!-- S253: moved verbatim from CLAUDE.md original lines 14859-14916 (M4.6 CLAUDE Context Normalization) -->
## SystemConfigurationIR: System-Level Configuration-Explosion Control Over Several Subsystems' Own Spaces (2026-09-07)

`config_variant_coverage.py` (section 232) already implements a real, deterministic, constraint-aware
IPOG covering-array engine, but only at the scope of ONE configuration space. Nothing in this repo
composed MULTIPLE subsystems' own configuration spaces (their own protocol/speed/lane-width/feature-
mode/SKU dimensions) into a single SYSTEM-LEVEL plan, the cross-subsystem sibling to what
`environment_mode_router.py` already recognises for environment GENERATION (SYSTEM_LEVEL_MODE).

`dv_harness/system_configuration_ir.py` builds NO second combinatorial engine. Composing "system
level" here means one thing: take N subsystems' own `ConfigDimension`/`Constraint`/
`CriticalCombination` declarations (the SAME dataclasses `config_variant_coverage.py` already defines
and validates), NAMESPACE each subsystem's dimension names (`<subsystem_id>.<dimension_name>`) so two
subsystems can each legally have their own `speed_mode` dimension without colliding, fold the whole
namespaced set -- plus any caller-declared CROSS-subsystem constraints/critical combinations -- into
ONE `config_variant_coverage.ConfigSpace`, and hand that space straight to the real, already-tested
`config_variant_coverage.build_plan()` (IPOG generation + its own independent `verify_coverage()`
recount). Every line of actual combinatorial-selection logic lives in exactly one place in this
codebase, unchanged by this module.

**Why namespacing, not a flat merge.** Two subsystems very often declare a dimension with the
identical NAME (`speed_mode`, `clock_mode`) meaning something different to each. Silently merging them
would either raise a spurious duplicate-dimension error or, worse, silently conflate two unrelated
axes into one. A cross-subsystem constraint MUST be declared using the same namespaced keys -- an
unnamespaced key simply fails `config_space_from_dict()`'s own existing "unknown dimension" check,
the same as any other mistake.

**System-level means at least two subsystems**, the identical `MIN_SUBSYSTEMS_FOR_SYSTEM_LEVEL = 2`
threshold `environment_mode_router.resolve_environment_mode()` already draws between SUBSYSTEM_MODE
and SYSTEM_LEVEL_MODE for environment generation.

**The one genuinely new piece of logic: independent per-subsystem projection re-verification.** IPOG's
own strength-t coverage guarantee over the composed namespaced space already mathematically implies
same-subsystem pairwise coverage, but this module never trusts that implication on its own strength --
`verify_subsystem_projection_coverage()` projects the composed plan's emitted combinations back onto
each subsystem's own dimensions and re-runs the REAL, unmodified `config_variant_coverage.
target_tuples()`/`verify_coverage()` over a smaller, local space built from ONLY that subsystem's own
local constraints/criticals (cross-subsystem constraints are deliberately excluded from the local
re-check, since they say nothing about whether this subsystem's own pairs are covered). `status` on
the returned plan is the worst of the system-level plan's own status and every subsystem's own
projection-coverage status -- worst-wins, never averaged.

**Deliberately bounded.** It does not discover a subsystem's own configuration dimensions (a caller
input, exactly the same "declared, not invented" contract `config_variant_coverage.ConfigDimension`
already has); it does not decide which subsystems belong in a composition (`environment_mode_router.py`'s
job); it does not decide which tests to run for a configuration; it runs no build, submits no job, and
has no stage gate. There is no `dv-harness` CLI verb (`cli.py`/`gates.py` untouched); front door is
`python -m dv_harness.system_configuration_ir plan --space <system_config.json> [--strength N]
[--out PATH] [--json]` (exit 0 full coverage across the system plan AND every subsystem's own
independent re-verification, 1 a real coverage finding, 2 a malformed document).

Proven by `dv_harness_tests/test_system_configuration_ir.py` (30 tests): namespacing correctness and
its collision refusal; cross-subsystem constraint/critical-combination composition using namespaced
keys; the at-least-two-subsystems refusal; the independent per-subsystem projection re-verification
proven to actually recompute (not merely read back) coverage over a real projected combination set,
including the strength-capping behavior for a single-dimension subsystem; the worst-wins status fold
across the system-level plan and every subsystem's own projection report; and the real CLI driven end
to end across all three documented exit codes.


<!-- S263: moved verbatim from CLAUDE.md original lines 15504-15583 (M4.6 CLAUDE Context Normalization) -->
## Protocol Compliance Oracle: Is the GENERATED Stimulus Itself Protocol-Legal (2026-09-06, section 222)

Section 222 asks a question distinct from `protocol_compliance_aggregation.py`'s: that module
aggregates an ALREADY-COMPUTED scoreboard/checker verdict that came out of a real simulation run,
and is never imported here. `dv_harness/protocol_compliance_oracle.py` instead checks, statically
and BEFORE (or independent of) any simulation, whether a GENERATED sequence/pattern's own declared
stimulus -- a plain list of transaction dicts a generator produced -- is itself protocol-legal. It
never reads a scoreboard verdict, a sim.log, or any evidence database.

**REUSE OVER REINVENT is the whole point of this module -- it invents no protocol rule of its
own.** Every legality fact is read from two existing, real modules: `amba_transaction_ir.
ir_field_applicability(protocol)` (SYOSCB-10's real, connectivity-signal-witnessed answer to
"does this AMBA-4 protocol even HAVE this field", applied here to EVERY one of the 22 real
`AMBA_TRANSACTION_IR_FIELDS`, catching a stimulus that forces a value onto a field the protocol
does not carry at all -- an address on AXI4-Stream, say); and `amba_master_slave_constraint_ir.
build_protocol_legal_constraint_ir(protocol)` -- Layer 1 (protocol-legal) of that module's
three-layer constraint model, read for its real legal value per `burst_type`/`burst_len`/
`burst_size`/`outstanding`/`ordering`/`security`, never the DUT-capability or scenario-constraint
layers. Neither imported module is modified; both are read-only.

**Three-level verdict, worst-wins, never collapsed.** Per FIELD, per TRANSACTION, per PATTERN --
a single ILLEGAL field makes its whole transaction ILLEGAL regardless of how many other fields are
legal; a single ILLEGAL transaction makes the whole pattern ILLEGAL regardless of how many other
transactions are clean. `FIELD_NOT_APPLICABLE` is deliberately excluded from the fold order (a
protocol simply not carrying a dimension is a benign fact, never outranking a real `FIELD_LEGAL`).

**Every absent-evidence case is an honestly distinct status, never a fabricated pass.**
`FIELD_PROTOCOL_UNRESOLVED` (the protocol itself could not be resolved),
`FIELD_APPLICABILITY_ONLY_NO_VALUE_RULE` (a field is applicable but this module has no per-value
rule for it -- `address`/`data`/`transaction_id`/etc., deliberately out of scope; address-map
legality stays `address_map_integrity_checker.py`'s job), and `FIELD_NOT_CHECKED_INSUFFICIENT_
EVIDENCE` (a dimension this module DOES have a value rule for, but the caller supplied no evidence
to apply it -- e.g. `check_pattern_outstanding()`'s `concurrent_groups` or `check_pattern_
ordering()`'s per-transaction `sequence_number`/`completion_sequence`). Because
`FIELD_APPLICABILITY_ONLY` outranks `FIELD_LEGAL` in the fold, a realistic transaction declaring
fields with no per-value rule correctly reports that status rather than a fabricated `FIELD_LEGAL`
-- `FIELD_LEGAL` is reserved for a transaction whose every declared field was BOTH applicable AND
actually value-checked.

**`stimulus_id` vs. `transaction_id`, deliberately never conflated.** A caller's own free-text
display label for one generated stimulus record is a different key from `transaction_id`, the real
`AMBA_TRANSACTION_IR_FIELDS` bus-level ID (AWID/ARID/BID/RID/TID) `check_pattern_ordering()`'s
per-ID grouping uses. Reports/citations always use `stimulus_id`; per-ID ordering grouping always
uses `transaction_id`.

**Pattern-level (stream) checks never invent an assumption.** `check_pattern_outstanding()` can
only ever find a violation on a hard-capped protocol (AHB/APB); an uncapped one (AXI-family) is
honestly `FIELD_NOT_APPLICABLE` (no protocol-imposed ceiling; a real bound is a DUT ID-width fact
this module never invents). Absent caller-declared `concurrent_groups` evidence, it reports
`FIELD_NOT_CHECKED` rather than assuming no concurrency. `check_pattern_ordering()` requires each
transaction to carry both `sequence_number` (real issue order) and this module's own
`completion_sequence` field (its required temporal evidence, since no prior IR models completion
order); a transaction missing either is excluded and reported, never silently treated as
compliant, and a pair whose same-ID/different-ID grouping cannot be determined is reported under
`insufficient_id_evidence` rather than assumed to share an implicit ID. Fewer than two
transactions overall is `FIELD_NOT_APPLICABLE` (nothing to order among); fewer than two carrying
the needed temporal evidence, when two or more transactions genuinely exist, is the honestly
different `FIELD_NOT_CHECKED`.

**Standalone front door, no `cli.py`/`gates.py` edit.** `python -m dv_harness.
protocol_compliance_oracle --pattern <file.json> [--json]` (exit 0 FIELD_LEGAL, 1 FIELD_ILLEGAL,
2 anything else -- never a clean exit for a verdict this module did not actually earn), matching
several other same-day modules' own disclosed choice to skip CLI wiring when `cli.py`/`gates.py`
are large files under concurrent edit pressure. There is deliberately no stage gate: this module
runs no build, no simulation, and mints no approval.

Proven by `dv_harness_tests/test_protocol_compliance_oracle.py` (53 tests), every check exercising
the REAL `amba_transaction_ir.py` applicability facts and the REAL `amba_master_slave_constraint_
ir.py` protocol-legal layer -- nothing mocked or hand-shaped to look like those modules' output.
Several tests are deliberate negative controls proving the oracle refuses to fabricate a clean
verdict when the evidence needed to reach one is absent (no concurrency evidence, no temporal
ordering evidence, an unresolved protocol) -- per the Evidence Truth Rule. Re-verified in this
pass: `python -m pytest dv_harness_tests/test_protocol_compliance_oracle.py -q` -> `53 passed`.

**Deliberately bounded, and stated rather than implied closed.** `address`/`data`/`byte_enable`
values are never range-checked here (a different, address-map-specific domain --
`address_map_integrity_checker.py`'s job, not imported here since this module's scope is
protocol-field legality, not address-map legality). It never runs a build, a simulation, or a
regression, and mints no stage gate.


<!-- S267: moved verbatim from CLAUDE.md original lines 15768-15842 (M4.6 CLAUDE Context Normalization) -->
## Control-Flow / Combinational-Sequential Logic-Intent Extraction (2026-09-06)

`verible_parser.py` is explicitly declaration-level only (its own docstring: signals declared
inside a procedural block "are deliberately NOT surfaced", and no always block's own sensitivity
list or body text is exposed at all). `design_architecture_ir.py` adds exactly ONE procedural-
content extraction on top of that: a best-effort literal scan for `always @(posedge ...)` blocks
containing a `case`, scoped narrowly to FSM-candidate detection (state register, states,
transitions -- see that module's own `extract_fsm_candidates()`). Nothing in this repo extracted
the WIDER, more basic control-flow/logic-intent fact set a design reviewer or a downstream
generator needs about an always block that is not trying to be an FSM: is this block combinational
or sequential? does it contain an if/else-if priority chain, and does it terminate with an `else`
(or a `case` with a `default`)? does a combinational block's own missing `else`/`default` look,
structurally, like it risks latch inference?

`dv_harness/rtl_control_flow_extraction.py` closes that gap by EXTENDING (never duplicating)
`design_architecture_ir.py`'s own FSM-literal-scan pattern: its comment/string blanking
(`_strip_noise_preserve_offsets`), depth-counted `case`/`endcase` matching (`_CASE_OPEN_RE`/
`_find_case_block`), one-always-block-at-a-time bounded windows, and closed status vocabulary are
imported and reused verbatim, never re-implemented. It applies that pattern to the wider always-
block family (`always`/`always_ff`/`always_comb`/`always_latch`) and to CONTROL-FLOW SHAPE rather
than FSM shape, and adds the one genuinely new piece of machinery that pattern never needed: a
depth-tracked if/else-if/else CHAIN walk (`_scan_control_tokens()`/`_extract_if_chain()`). It
never re-derives design_architecture_ir.py's own FSM state/transition extraction -- a module's FSM
candidates stay that module's own job.

**What it reports, per always block.** `block_kind`: `SEQUENTIAL` (a real clock-edge sensitivity),
`COMBINATIONAL` (`always_comb`, `@*`/`@(*)`, or an explicit signal-list sensitivity with no edge
keyword), `LATCH_EXPLICIT` (`always_latch`), or `UNCLASSIFIED_SENSITIVITY` (no `@(...)`/`@*` clause
this scan's fixed patterns can find -- never guessed). `if_chain`: whether a top-level if/else-if
chain was found, its branch count, and whether it ends in a terminal `else`, via a depth counter
over `begin`/`end`/`case.../endcase` tokens that starts at 0 at the always block's own opening;
only `else if`/`else` tokens later found at the SAME depth continue the chain. `case_shape`:
whether a top-level `case`/`casex`/`casez` was found (reusing `design_architecture_ir.py`'s own
`_CASE_OPEN_RE`/`_find_case_block` unchanged) and whether it carries a `default`. `findings`: zero
or more named, cited structural findings -- `LATCH_INFERENCE_RISK_CANDIDATE` (a `COMBINATIONAL`
block whose if-chain lacks a terminal `else`, or whose case lacks a `default`) and
`PRIORITY_STRUCTURE_NO_TERMINAL_ELSE` (a `SEQUENTIAL` block's if-chain with no terminal `else` --
informational, not a risk). Every finding's own `reason` text says a literal scan proves only a
STRUCTURAL absence, never that the block is actually incomplete (an unconditional assignment
elsewhere in the block, which this scan does not track, could still make it complete).

**Boundary, stated rather than implied closed.** This is a literal/regex scan over source text,
not a second SystemVerilog parser and not an elaborator: no expression is evaluated, no
`generate`/`` `ifdef `` condition is resolved, and no data-flow/assignment-coverage proof is
attempted. Only the FIRST if/else-if/else chain and the FIRST top-level `case` in one always
block's own bounded window are examined, mirroring `design_architecture_ir.py`'s own "only the
first case/casex/casez statement is scanned" bound. Chain continuation is judged purely from a
`begin`/`end`/`case.../endcase` token-count depth, never from real block parsing -- the same class
of honest limitation that module's own case/endcase depth counter already carries. `//`/`/* */`
comments and `"..."` string literals are blanked before any regex runs, reusing
`_strip_noise_preserve_offsets()` unchanged. A generate-block- or `` `ifdef ``-guarded always block
is reported exactly as written, matching `verible_parser.py`'s and `design_architecture_ir.py`'s
own documented stance of never evaluating a guard condition.

Front door: standalone `python -m dv_harness.rtl_control_flow_extraction --rtl <f> [--rtl <f> ...]
[--out ir.json] [--json]` (`execute_verb()`/`main()`, wrapping `verible_parser.py`'s real per-file
parse output directly rather than `design_architecture_ir.py`'s own orchestration, since this
module needs only each module's own source span, not ports/params/signals/instances). No
`dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched -- a standalone front door,
matching several recent modules in this codebase that made the identical disclosed choice.

Proven by `dv_harness_tests/test_rtl_control_flow_extraction.py` (28 tests): the pure-function
classification/if-chain/case-shape scan is unit-tested directly against hand-written SystemVerilog
snippets with no verible dependency at all, including the required negative controls -- a module
with no always block at all reports `NOT_AVAILABLE` rather than a fabricated
`CONTROL_FLOW_EXTRACTED` over an empty list; an always block with no sensitivity clause reports
`UNCLASSIFIED_SENSITIVITY` with zero findings rather than a guessed kind; a `case` with no
`endcase` reports `UNPARSEABLE` with `has_default: None` rather than a fabricated finding; and a
stray `case`/`else` spelled inside a comment or string literal never corrupts the real scan.
Everything needing real module boundaries (`parse_rtl_file()`/`build_control_flow_ir()`, and both
CLI subprocess entry points) is driven against the REAL `verible-verilog-syntax` binary over real
files written to `tmp_path`, and is skipped (never faked) on a machine without it on PATH --
including a real multi-file build that isolates one file's real syntax error without sinking the
other's PASS.


<!-- S274: moved verbatim from CLAUDE.md original lines 16209-16270 (M4.6 CLAUDE Context Normalization) -->
## Semantic Change Impact Engine: WHAT an RTL Diff Actually Changed, Not Just Which Files It Touched (2026-09-06)

`change_impact.py`'s existing machinery (`classify_risk()`, `compute_change_impact()`) computes
impact purely from a real `git diff --name-only` FILE LIST resolved against changed file PATHS
(suffix/path-segment/RTL-parse module-name lookup) -- a comment-only edit to a `.sv` file and a
commit that deletes that same file's only DUT output port score byte-for-byte identically today (same
HIGH risk, same confidence, same regression selection), because nothing downstream of
`classify_risk()` ever opens the diff's own content. Confirmed by direct search before writing:
`change_blast_radius.py` widens the identical file-path reasoning to an import-closure ("how far does
a changed FILE reach"), never a content diff; `command_txt_change_impact.py`/`spec_vplan_delta.py`
semantic-diff a DE command registry and a requirement-contract set respectively -- real semantic
diffs, but over structured records, not RTL/SV source text, and neither imports or is imported by
this module. This is the first place in the repo that reasons about WHAT a code-level diff actually
changed.

`semantic_diff_rtl_file()`/`compute_semantic_change_impact()` are additive to `change_impact.py`,
changing nothing about `compute_change_impact()`'s/`select_regression()`'s existing
confidence/`expand_to_full_regression`/selection behaviour, and reuse `verible_parser.py`'s real
declaration-level parse at both revisions (a real `git show <sha>:<path>`, written to a throwaway
temp file and really parsed by verible -- never a diff-text guess). Every change reported is one real,
cited before/after structural fact: a module added/removed, a port added/removed/re-directioned/
re-typed, a parameter added/removed/re-typed/re-defaulted, a module-level signal added/removed/
re-typed. Scope is declaration-level only, the exact "module/port/signal hierarchy, not a full
elaboration/semantic model" bound `verible_parser.py` already states for itself -- anything living
inside a procedural block (an `always_ff`'s own logic, an assertion body, a case statement) is
invisible here exactly as it is invisible to `verible_parser.py`, and is honestly reported as
`BODY_ONLY_CHANGE` ("the declared interface did not move, but the file's content did, by a means this
parser cannot see inside") -- never silently folded into "nothing changed".

`INTERFACE_IMPACTING_CHANGE_KINDS` draws the same external-contract-vs-internal-implementation line
`phy_boundary.py`/`connectivity.py` already draw one layer down for a different purpose: ports/
parameters (and a module's own existence) are the contract a testbench/bind/instantiating parent can
depend on; a module-level signal declared but never exposed as a port is not, since nothing outside
the module can ever legally reference it by name.

**Honesty, worst-wins in the one direction that matters here**: an unverifiable file (verible
missing, a real syntax error at either revision, `git show` failing) is `NOT_AVAILABLE` -- collected
in `unverifiable_files` and NEVER counted as "no interface change", the Evidence Truth Rule's "an
absence of proof about a diff's content must never read as proof the diff was safe" applied here
specifically. Only files whose suffix is in `_RTL_SUFFIXES` (the exact set `classify_risk()` already
uses, imported not re-typed) are semantically diffed; every other changed file is reported under
`non_rtl_files_skipped`, never silently dropped.

**Deliberately additive and REACHED, not WIRED**: no `engine.py` call site invokes it, the same
"prefer a standalone front door over touching a large, concurrently-edited engine/gates/cli module"
choice several sibling 2026-09-06 additions in this project already disclose. Front door:
`compute_semantic_change_impact()` directly, or `python -m dv_harness.change_impact semantic-diff
--root <dir> --base <sha> [--head <sha>] [--json]`.

Proven by `dv_harness_tests/test_change_impact_semantic_diff.py` (16 tests,
`python -m pytest dv_harness_tests/test_change_impact_semantic_diff.py -q` -> `16 passed`) against a
REAL throwaway git repository with real commits: no-git-repo and an unresolvable base both report
`NOT_AVAILABLE` honestly; a non-RTL file is skipped and named rather than silently dropped; a
simulated verible-unavailable path never fabricates an answer; a genuinely added/removed file reports
`FILE_ADDED`/`FILE_REMOVED` naming every module it takes with it, never diffed against nothing;
byte-identical content reports `FILE_UNCHANGED_STRUCTURALLY`; a real port-width change, a real
added+removed port pair, and a real parameter-default change are each detected and cited; an
internal-signal-only change is proven NOT interface-impacting; a comment-only edit reports
`BODY_ONLY_CHANGE`; a real injected syntax error at one revision reports `NOT_AVAILABLE` rather than a
guess; the whole-diff aggregator correctly sums across multiple files; and both CLI exit-code paths
(`interface_impacting` present vs. absent) are driven as real subprocesses.


<!-- S278: moved verbatim from CLAUDE.md original lines 16537-16587 (M4.6 CLAUDE Context Normalization) -->
## External/Internal Interface Classification: an Additive Pass Over the Instance Tree (2026-09-07)

Spec section 283 asks whether each RTL port crosses the DUT top boundary (EXTERNAL) or connects
module-to-module only (INTERNAL). Nothing in this repo answered that before: `phy_boundary.py`
classifies a SERIAL-vs-PARALLEL PHY-boundary (which layer a monitor may mount at -- a real,
adjacent, but different axis) and `verification_boundary_ir.py` classifies a caller-DECLARED
verification boundary into a 10-value taxonomy with no RTL parsing at all. Neither answers "is
this port a real chip-level pin, or does it only ever wire one instantiated module to another".

`dv_harness/iface_classification.py` closes it as a REUSE-first, additive pass over
`design_architecture_ir.py`'s already-built full instance tree -- it imports that module and
never re-parses RTL or invokes verible itself. The classification rule is deliberately
STRUCTURAL, not signal-level: a port belongs to a MODULE, and a module's whole port list is
classified from that module's own ROLE in the already-built tree. `ROLE_TOP` (a root of the
instance tree -- the DUT top, explicitly forced via `top_module` or structurally derived as
"never instantiated by anything else this build parsed") makes every one of its ports
`EXTERNAL`. `ROLE_SUBMODULE` (reached only as a resolved instantiated child at depth >= 1)
makes every one of its ports `INTERNAL`. Two roles are honestly `UNKNOWN`, never guessed:
`ROLE_AMBIGUOUS` (a module that is BOTH a root in one tree AND an instantiated child in
another -- reachable only through a genuine instantiation CYCLE among the parsed modules, where
`build_instance_tree()` itself falls back to reporting every parsed module as its own root) and
`ROLE_UNREACHED` (a module parsed into the registry but never appearing anywhere in the actual
instance tree -- dead/unreferenced RTL, or a structural root excluded by an explicit
`top_module` override). A submodule port that happens to be wired straight through to a
top-level port (a genuine pass-through) is still reported `INTERNAL`: it is the submodule's own
port, and whether that net is *also* reachable from the boundary is a different,
connectivity-level question this module does not attempt.

**Deliberately bounded, and stated rather than implied closed.** (1) This is a pure,
hierarchy-position classification, never a net-level trace -- no second parser, no signal
graph. (2) An unresolved instance (a module_name never parsed -- an external module, a VIP BFM,
a std cell) contributes no port data at all, since this build never parsed its port list. (3)
It reads and reports only: no build, no simulation, no gate, no approval. (4) There is no
`dv-harness` CLI verb and `gates.py`/`cli.py` were not touched, per this task's own instruction
to prefer a standalone front door when those files are under concurrent edit pressure -- the
front door is `python -m dv_harness.iface_classification --rtl <f> [--top-module NAME]
[--json]`, mirroring `design_architecture_ir.py`'s own identical disclosed choice.

Proven by `dv_harness_tests/test_iface_classification.py` (21 tests): a pure-function suite over
hand-built `instance_tree` shapes (two-level hierarchy, a module instantiated twice, a
multi-top forest, the root-and-child-elsewhere ambiguity, an unresolved child contributing
nothing, malformed-input refusal) plus a real-verible integration suite reusing
`test_design_architecture_ir.py`'s own fixture shapes: the real 3-file leaf/mid/top hierarchy
(top's own ports EXTERNAL, mid/leaf's INTERNAL, the unresolved `ext_blackbox` instance
contributing no module entry at all), a real `top_module` override (the previously-structural
root correctly becomes `ROLE_UNREACHED`/`UNKNOWN`, never still called EXTERNAL), a real mutual
`mod_a`/`mod_b` instantiation cycle (both modules correctly `ROLE_AMBIGUOUS`/`UNKNOWN`), and the
required negative control proving a module the built tree never reaches is reported `UNKNOWN`
rather than a fabricated EXTERNAL or INTERNAL. Both `execute_verb()` and a real
`python -m dv_harness.iface_classification` subprocess are driven end to end.


<!-- S279: moved verbatim from CLAUDE.md original lines 16588-16686 (M4.6 CLAUDE Context Normalization) -->
## Parameter/Define Extraction: Real RTL Parameter Citations + `` `define `` Constant Facts (2026-09-07, section 284)

`dv_harness/verible_parser.py` already extracted, per module, the real declared parameter list
(`ParamInfo(name, type_text, default_text)`) off its own real syntax tree -- but until this item,
`ParamInfo` carried no line number at all, so no consumer could cite a real file:line for one
specific parameter without re-scanning source text itself (confirmed by reading the dataclass and
`_extract_params()` before writing a line here). And nothing in this repo extracted preprocessor
`` `define `` constants as a general fact, as distinct from `command_task_trace.py`'s/
`cpuread_byte_shift_checker.py`'s narrow `` `define NAME TARGET `` lookup for ONE specific command's
macro-redirect target. `memory_buffer_arch_extraction.py` (section 274) reads the same `ParamInfo`
list too, but only as an ingredient to resolve a memory array's depth/width -- it never lists "every
parameter this module declares" as its own fact and never touches `` `define `` at all. Re-verified
by grep before building: no `param_define`/`ParamDefine`/`ParameterFact`/`DefineFact` symbol existed
anywhere.

Two real, independent halves, matching this item's own two source kinds:

- **Real RTL parameters, each with a real citation.** A small, additive, backward-compatible change
  to `verible_parser.py` itself: `ParamInfo` gained a new `line: Optional[int] = None` field,
  appended LAST with a default so every existing positional-construction call site (verified by grep
  -- `test_memory_buffer_arch_extraction.py`'s three) stayed valid, computed in `_extract_params()`
  off the real `kParamDeclaration` node's own byte span via the identical `source.count("\n", 0,
  start) + 1` convention `command_task_trace.py` already uses elsewhere in this codebase -- never a
  second line-counting scheme. `dv_harness/param_define_extraction.py`'s
  `extract_module_parameters()` then wraps `verible_parser.parse_file()` (still the one real
  SystemVerilog front end this package has; never re-parsed) and reports every real parameter with
  its real `file:line`, name, type text and default text verbatim -- a module that declares none
  honestly reports `PARAMETERS_NOT_AVAILABLE`, never a fabricated parameter. A parameter's
  `default_text` is reported AS DECLARED, never resolved to a number here -- that numeric-resolution
  question stays section 274's own, different, already-real job for the one case it needs it.
- **Real `` `define `` constants, why a line-scan and not verible_parser.py.** `` `define `` is a
  PREPROCESSOR directive verible's own real syntax tree does not model as a first-class node at all
  (confirmed against `verible_parser.py`'s own module docstring, which never mentions it) -- the
  identical rationale `interrupt_dma_clock_reset_extraction.py`'s own docstring already states for
  why IT is a line-scan rather than a verible_parser.py consumer. `extract_defines_from_text()` reads
  the RAW file text directly (never verible), blanks `//`/`/* */` comments and `"..."` string
  literals length- and newline-preserving first (the identical lexical-hygiene technique
  `design_architecture_ir.py`'s FSM scan already uses, independently re-implemented at a few lines
  here rather than imported -- matching this codebase's own established convention of each
  extraction module owning its own small bounded regex helper, the same way
  `memory_buffer_arch_extraction.py`/`rtl_data_path_extraction.py`/`amba_command_txt_extension.py`
  each already do), then classifies every `` `define `` into a small, closed, honest vocabulary:
  `DEFINE_CONSTANT_FOUND` (an object-like macro with real replacement text, reported verbatim, never
  evaluated), `DEFINE_FUNCTION_LIKE_SKIPPED` (a `(...)`-parameterized macro -- not a constant, cited
  but never given a fabricated value), `DEFINE_GUARD_NO_VALUE` (a bare include-guard/flag macro, kept
  honestly distinct from a constant with an empty value this scan cannot produce), and
  `DEFINE_MULTILINE_NOT_CAPTURED` (a backslash-continued directive -- name and citation still
  reported, value never wrongly joined or truncated into a guess).

Front door: `python -m dv_harness.param_define_extraction <f.sv> [<f.sv> ...] [--verible-bin BIN]
[--json]` (exit 0 at least one real parameter or `` `define `` fact was found, 2 `NOT_AVAILABLE`
across the board). No `dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched,
matching this item's own house-style instruction and several recent sibling modules' same disclosed
choice. Rendering reuses `connectivity.render_markdown_table()` (this repo's one parameterized table
renderer). A `param_define_extraction`-vs-`dv_harness.models.Status` vocabulary-collision guard runs
at import, the same discipline `memory_buffer_arch_extraction.py` already established.

**A real regression this additive field surfaced, and fixed.** `dv_harness/schemas/
env_manifest.schema.json`'s `dut_facts.rtl` parameters sub-schema was `additionalProperties: false`
with no `line` property, so `env_manifest.py`'s own real jsonschema validation started rejecting
every manifest containing RTL parameters the moment `ParamInfo.line` existed (`vars(p)` picks up
every dataclass field automatically). Caught by re-running this repo's own existing
`test_env_manifest.py` before declaring done -- not assumed safe. Fixed by adding
`"line": {"type": ["integer", "null"]}` to that one sub-schema, deliberately NOT `required` (so a
manifest written before this change, still missing the key entirely, keeps validating).
`evidence_db.py`'s separate `rtl_parameters` DuckDB table still has no `line` column -- a disclosed
residual, out of this item's real scope, and untouched here.

**Deliberately bounded, and stated rather than implied closed.** (1) No `` `ifdef ``/`` `ifndef ``/
`` `undef `` resolution of any kind for `` `define `` -- a guarded or later-undef'd define is reported
exactly as textually present, unconditionally, matching every sibling extraction module's own
disclosed scope. (2) No redefinition merging: a name defined more than once (same file or across
files) yields multiple independent `DefineFact`s, each with its own real citation, never
deduplicated. (3) No parameter value resolution (see above). (4) No generate/`` `ifdef `` elaboration
for parameters either, matching `verible_parser.py`'s own documented declaration-level scope. (5) It
reads and reports only -- no build, simulation, job, approval, or stage gate of any kind is touched.

Proven by `dv_harness_tests/test_param_define_extraction.py` (20 tests): Tier 1 pure unit tests drive
`extract_module_parameters()`/`extract_defines_from_text()` directly against hand-built
`ModuleInfo`/`ParamInfo` objects and raw text (no subprocess); Tier 2 exercises the real end-to-end
pipeline through a real `verible-verilog-syntax` subprocess (skipped, never faked, when it is not on
PATH). Negative controls: a module verible really parsed but that declares no parameters
(`PARAMETERS_NOT_AVAILABLE`, not a fabricated one); a `ParamInfo` whose line could not be resolved
(`PARAM_LINE_NOT_AVAILABLE`, never a guessed line); a `` `define `` spelled inside a `//` comment, a
`/* */` block comment, and a `"..."` string literal, all proven NOT reported as real directives; a
backslash-continued `` `define `` proven NOT guess-joined; an unreadable RTL file honestly
`DEFINES_FILE_UNAVAILABLE` rather than a silent empty "no defines" result; and a nonexistent verible
binary honestly `PARAMS_FILE_UNAVAILABLE` while the independent `` `define `` scan (which needs no
verible at all) still succeeds on the same file. `python -m pytest
dv_harness_tests/test_param_define_extraction.py -q` -> `20 passed`. The additive `verible_parser.py`/
`env_manifest.schema.json` changes were then re-verified against this repo's own full at-risk
regression surface (`test_env_manifest.py`, `test_verible_parser.py`,
`test_memory_buffer_arch_extraction.py`, `test_design_architecture_ir.py`, `test_evidence_db.py`,
`test_evidence_layer_wiring.py`, `test_dut_evidence_correlation.py`, plus every other test file
importing `verible_parser`) -- 165 passed, 0 failed. One unrelated, pre-existing failure
(`test_syoscb_phase1_report.py::test_section_four_really_runs_the_not_vendored_scan`, about this
environment's real SYOSCB vendoring state, unconnected to RTL parameters/defines) was confirmed
reproducible in isolation and left untouched.


<!-- S280: moved verbatim from CLAUDE.md original lines 16687-16746 (M4.6 CLAUDE Context Normalization) -->
## Subsystem Compatibility Matrix: a Pairwise Rollup Over SYS-9..14 + ip_ownership_conflict.py (2026-09-06, section 233)

Section 233 asks for a matrix of which subsystem PAIRS are known-compatible for composition.
`system_resource_inventory.py`'s SYS-9..14 chain already computes exactly the evidence a pairwise
matrix needs, but only ever renders it as a flat relationship LIST plus a single project-wide
`ACTIVE_DRIVER_CONFLICT` verdict -- there is no per-PAIR rollup anywhere, and a human wanting "can
subsystem A compose with subsystem C specifically" had to read the whole relationship list by hand
and mentally group it. `ip_ownership_conflict.py`'s IP-level VIP-vs-legacy-BFM check answers a
different, narrower question (is ONE subsystem internally clean, before any composition exists at
all) that SYS-9..14 cannot see by construction -- but an internally conflicted subsystem cannot
honestly be called a "known-compatible" composition partner for ANY other subsystem, so
`dv_harness/subsys_compat_matrix.py` folds that per-subsystem fact into every pair the conflicted
subsystem appears in.

**REUSE OVER REINVENT: no new analysis, only a rollup.** This module computes nothing SYS-9..14 or
`ip_ownership_conflict.py` did not already compute. It calls `system_resource_inventory.
analyze_selected_subsystem_resources()` -- the real SYS-1 -> SYS-5..8 -> SYS-9..14 front door, so
SYS-1's refusal to analyze an unselected/not-on-disk set is not bypassed -- and reads the resulting
`relationships` list, each of which already carries `subsystem_a`/`subsystem_b` (assigned by
`classify_resource_relationship()`, never re-derived here by parsing a resource_id string). It
calls `ip_ownership_conflict.analyze_ip_ownership_conflict()` once per subsystem, fed the REAL
`env.manifest.json` path each subsystem's own SYS-6 analysis already resolved. It deliberately does
NOT call `system_resource_inventory.real_cross_subsystem_findings()` -- that function's own
gate-facing flattening drops `subsystem_a`/`subsystem_b` attribution, since its two real callers
(the two SYSTEM_LEVEL gate scripts and the SoC composer) never need "which two subsystems,
specifically". This module calls the fuller analysis one layer below the flattening -- the SAME
real SYS-9..14 computation that function itself wraps, not a second, parallel analysis.

**Five honest pair statuses, worst-wins.** `SUBSYSTEM_SELF_CONFLICT_BLOCKS_COMPOSITION` (either
subsystem in the pair carries its own unresolved `ip_ownership_conflict.STATUS_CONFLICT` -- outranks
every cross-subsystem finding); `CROSS_SUBSYSTEM_DRIVER_CONFLICT` (SYS-9..14 found a real
`REL_DRIVER_CONFLICT`/`REL_CONFIGURATION_CONFLICT` relationship between the pair's own resources --
SYS-12's stop rule, applied per pair); `UNKNOWN` (a `REL_UNKNOWN` relationship, or either
subsystem's own IP-ownership self-check came back `STATUS_UNKNOWN`, or a self-check was requested
with no `env.manifest.json` to run it against -- never silently promoted to COMPATIBLE);
`SHARED_RESOURCE_REQUIRES_REVIEW` (a real `REL_SAME_PHYSICAL`/`REL_SHARED_LOGICAL` relationship
with no ACTIVE-driver conflict, so SYS-12 does not stop it, but a human should still review the
arbitration model); `COMPATIBLE` (real evidence was checked and none of the above fired --
`known_compatible: true` is set ONLY here, since "known compatible" is a positive claim this module
never makes without positive evidence). A subsystem for which no `ip_ownership_inputs` were
supplied at all gets that self-check reported `NOT_REQUESTED`, distinct from `UNKNOWN` and never
forcing a pair to `UNKNOWN` on its own -- mirroring `ip_ownership_conflict.py`'s own honest default
(no legacy driver declared is the common, clean case for a subsystem built entirely on VIP).

**Scope boundary -- rollup only, never arbitration.** This module picks no winner between two
active drivers and resolves no shared-resource contention -- SYS-12's own `preferred_model` text is
carried through on every blocking pair for the human who must decide. It builds no system
environment, submits no build/regression, and touches no approval/governance mechanism. There is no
`dv-harness` CLI verb (`cli.py`/`gates.py` untouched, matching several sibling same-day modules'
own disclosed choice) -- the front door is `execute_verb()`/`python -m dv_harness.
subsys_compat_matrix`.

Proven by `dv_harness_tests/test_subsys_compat_matrix.py` (19 tests, `python -m pytest
dv_harness_tests/test_subsys_compat_matrix.py -q` -> `19 passed`), verified in this pass against
the real `system_resource_inventory.py`/`ip_ownership_conflict.py` machinery over synthetic
multi-subsystem project fixtures -- covering every one of the five pair statuses, the worst-wins
precedence between a self-conflict and a cross-subsystem finding, the `NOT_REQUESTED` honesty
default, and the whole-matrix rollup's own MATRIX_ALL_COMPATIBLE/SOME_PAIRS_NEED_REVIEW/BLOCKED/
INCOMPLETE_EVIDENCE/NOT_AVAILABLE vocabulary.


<!-- S281: moved verbatim from CLAUDE.md original lines 16747-16804 (M4.6 CLAUDE Context Normalization) -->
## Requirement Testability (2026-09-06, section 218)

Section 218's own question is different from the one `requirement_contract.py`'s five-value status
already answers: that module's COMPLETE/PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN status is about
whether the fifteen fields are RESOLVED (present, non-placeholder) and whether a filed ambiguity/
contradiction is being stepped over. It is silent on a different, real defect: a requirement can be
schema-COMPLETE, every field resolved with real prose, `derive_status()` genuinely returning
COMPLETE -- and still be UNTESTABLE, because its `expected_result`/`checker`/`observability` text
never names anything a checker/monitor could actually compare against ("the system shall behave
correctly", "performance shall be acceptable"). `unresolved_fields()`/`is_resolved()` treat that
prose as fully RESOLVED (not a placeholder, not TBD, not empty), so nothing in that module ever
flags it. `dv_harness/requirement_testability.py` answers this second question without touching
`requirement_contract.py`'s own status field or `derive_status()` precedence in any way.

**A deliberately DISJOINT three-value vocabulary** (checked at import against both
`requirement_contract.py`'s five status values and `dv_harness.models.Status`'s ten verdict values
via `assert_no_status_vocabulary_collision()`): `TESTABLE` (the record's own text names a checkable
condition -- a comparison, a concrete value, an explicit checker/assertion/scoreboard mechanism --
AND an observable signal -- a named register/signal or an explicit observation mechanism; both, not
either); `UNTESTABLE_PROSE` (checker/expected_result/observability text is present and resolved but
reads as purely qualitative/subjective prose with no checkable condition and no observable signal
detected anywhere); `INDETERMINATE` (neither could be honestly concluded -- every relevant field is
unresolved, or the evidence is a genuine mix of one signal present and the other absent -- never
forced into either of the other two, and never silently defaulted to TESTABLE).

**Detection is heuristic, stated as such.** `detect_checkable_condition()`/
`detect_observable_signal()`/`detect_untestable_prose_phrases()` are pattern scans (comparison
operators, concrete numeric/hex/timing literals, named SIGNAL_LIKE tokens, explicit checker/
observation-mechanism keywords, a fixed list of subjective quality phrases), not a semantic parse.
A requirement using different, equally concrete wording these patterns do not recognize reports
INDETERMINATE rather than a wrong classification in either direction -- a false TESTABLE (missing a
real defect) is a worse failure mode than an honest INDETERMINATE, so the patterns are written
narrow rather than broad. REUSE OVER REINVENT: `is_resolved()`/`declares_contract_shape()`/
`detect_ambiguous_language()` are all imported from `requirement_contract.py`, never re-typed, so
whether a field counts as "there is text here to evaluate" answers identically in both modules.

**ARBITRATION IS NOT HERE.** This module classifies; it never edits a record, never resolves an
ambiguity/contradiction, and never changes `requirement_contract.py`'s own `status` field. A
CONTRADICTORY or AMBIGUOUS requirement (per that module's own derivation) is still independently
scored for testability here -- "is this requirement internally coherent" and "is this requirement's
content actually checkable" are orthogonal questions.

**Deliberately bounded, and stated rather than implied closed.** This module reads a requirement
RECORD's own text; it does not parse a specification, does not consult RTL/VIP/simulation evidence,
and does not decide whether a *named* observable signal genuinely exists in a real design (that is
`dut_evidence_correlation.py`'s job, not imported here to keep this module's own dependency surface
small). It has no stage gate, and no existing gate script or CLI verb was edited to reach it -- the
standalone `python -m dv_harness.requirement_testability` front door is deliberately how it is
reached, mirroring the disclosed choice several very recent same-day additions in this project have
already made when `cli.py`/`gates.py` are under concurrent edit pressure from many other items in
the same batch.

Proven by `dv_harness_tests/test_requirement_testability.py` (32 tests, `python -m pytest
dv_harness_tests/test_requirement_testability.py -q` -> `32 passed`), verified in this pass against
real `requirement_contract`-shaped records: the TESTABLE/UNTESTABLE_PROSE/INDETERMINATE positive
paths, the vocabulary-disjointness guard, and negative controls proving the module never re-derives
or edits `requirement_contract.py`'s own status field.


<!-- S283: moved verbatim from CLAUDE.md original lines 16864-16904 (M4.6 CLAUDE Context Normalization) -->
## CSR Checker Placement Rule -- extends verification_architecture.py's Existing Domain-Placement Table (2026-09-07)

This item's own agent produced no result. Investigated directly: there is no standalone
`csr_checker_placement.py` module anywhere in this repo, and the concept -- "a register/CSR checker
must be mounted at the bind target whose real, caller-declared functional-domain classification is
REGISTER_CSR" -- already lives inside `dv_harness/verification_architecture.py`'s own
`CHECKER_DOMAIN_PLACEMENT_RULES` table (added 2026-09-06 to that file, per its own module docstring
under "NAMED PER-DOMAIN CHECKER-PLACEMENT RULES"), as ONE of five named per-domain rules
(`REGISTER_CSR`/`INTERRUPT`/`DMA`/`STATE`/`TIMING`), each mapping to its own `finding_kind`
(`CSR_CHECKER_WRONG_TARGET_DOMAIN` for the CSR case) and a written rationale. No CLAUDE.md section
had ever documented this addition -- confirmed by grep for `CHECKER_DOMAIN_PLACEMENT_RULES`/
`checker_domain`/`CSR_CHECKER_WRONG_TARGET_DOMAIN` before this section was written, all zero hits --
so this section closes that documentation gap rather than building a duplicate module.

`CheckerIR`'s pre-existing `target_instance`/`mount_side` fields already answer ONE generic,
structural placement question for any checker -- which bridge side it mounts on. What the 2026-09-06
addition supplies is a NAMED rule PER PROTOCOL DOMAIN: a register/CSR checker belongs on the CSR bus
target, an interrupt checker on the interrupt line, a DMA checker on the DMA master, a state-machine
checker on the FSM-owning target, a timing/handshake checker within the timed clock/reset domain --
five distinct claims, not one generic "is this linked" question. `CheckerIR` gained an optional,
caller-declared `checker_domain` field (checked against the five-value `CHECKER_DOMAINS` vocabulary
at construction, raising `VerificationArchitectureError` on anything else), and
`check_checker_domain_placement()` is the comparator: a checker declaring `checker_domain=<domain>`
must be linked (via `target_instance`) to a bind target whose OWN real, caller-declared
functional-domain classification (`target_domain_by_instance`) is the identical domain -- the same
"declared field vs. declared map, never inferred from a name" shape `ASSERTION_WRONG_CLOCK_DOMAIN`/
`WRONG_RESET_DOMAIN` already use for clock/reset. Absent either fact (no declared `checker_domain`
on the checker, or no entry for its `target_instance` in `target_domain_by_instance`) the comparator
reports nothing for that checker -- an unresolved domain-placement question is UNKNOWN, never
guessed toward either agreement or conflict. `check_checker_domain_placement()` is called from
`detect_placement_conflicts()` exactly like the pre-existing clock/reset-domain checks, so a CSR
(or any of the other four domains') mismatch surfaces in the same `findings` list every other
placement conflict already does.

No source code change was made in this pass -- the mechanism already exists and already passes its
own tests, verified directly: `python -m pytest dv_harness_tests/test_verification_architecture.py -q`
-> `61 passed`, of which 22 are domain-placement-specific
(`python -m pytest dv_harness_tests/test_verification_architecture.py -k "domain or csr" -q` ->
`22 passed`). The gap this section closes is purely the missing CLAUDE.md record for a real,
already-tested code addition.


<!-- S284: moved verbatim from CLAUDE.md original lines 16905-16976 (M4.6 CLAUDE Context Normalization) -->
## Feature Enablement Matrix: Parameter/Config-Bit -> Named Feature, Only From Cited Evidence (2026-09-07)

Section 285 asks for a matrix of which RTL parameters/config bits enable which named feature, built
ONLY from real, cited evidence (a parameter name plus a spec/comment citation proving what it
enables) -- never guessed from a parameter's name alone, matching this project's established
anti-naming-inference discipline (`arbitration_policy_ir.py`'s and `coherency_capability_ir.py`'s
identical rule). A repo-wide grep for `feature_enablement`/`enablement_matrix`/`EnablementMatrix`
returned zero hits before this module. Three near-neighbour modules were read first, per REUSE OVER
REINVENT, and each answers a genuinely different question: `sys_regmap.py`'s
`required_preconditions()`/`unverifiable_bits()` decide whether a MODE-DETERMINING bit's precondition
is met before a connectivity Gate-2 check, never what named capability a bit turns on;
`register_rtl_trace.py` proves whether a register FIELD NAME corresponds to a real, referenced RTL
signal (declaration-level existence), never what feature that field enables;
`design_knowledge_correlation.py` correlates arbitrary cross-source facts generically, with no
parameter/feature vocabulary of its own. None needed extending -- this was a genuine, narrow gap.

`dv_harness/feature_enablement_matrix.py` is that matrix, built entirely from scratch as a standalone
module (it imports only `connectivity.render_markdown_table`, this repo's one parameterized table
renderer, and `models.Status` for a vocabulary-disjointness check -- nothing from `sys_regmap.py`,
`register_rtl_trace.py`, `arbitration_policy_ir.py`, `coherency_capability_ir.py`, or any other
concurrently-built module, to stay collision-free in a low-collision but still multi-agent batch).

**The Evidence Truth Rule, applied literally and identically to `arbitration_policy_ir.py`'s own
rule**: `classify_feature_enablement()` matches a fixed, literal, case-insensitive enablement-phrase
list ("enable bit for X", "must be set to enable X", "when set, ... enables X", "controls whether X
is enabled", the generic "enables X") against caller-supplied evidence TEXT ONLY --
`parameter_name`/`config_bit` are accepted purely as LABELS and are never read when deciding a
feature, proven directly by a dedicated negative-control test: a parameter literally named
`usb3_enable` whose supplied evidence states it enables PCIe Gen3 mode classifies PCIe Gen3 mode, not
the name-implied USB3; the same parameter with NO evidence at all stays honestly `NOT_AVAILABLE`.
Evidence matching none of the fixed phrases is likewise `NOT_AVAILABLE` -- narrower recognition is the
deliberate, disclosed trade for never fabricating an enablement relationship the evidence does not
literally state. Two or more genuinely distinct features cited for one parameter (after
whitespace/case normalization) are honestly `AMBIGUOUS`, naming every one -- this module never
arbitrates which citation is correct, the same boundary `requirement_contract.py`/
`design_knowledge_correlation.py`/`security_policy_ir.py` already keep for their own conflicting-claim
findings. Precedence-ordered patterns are checked against non-overlapping spans per excerpt so one
real sentence is never double-counted as two disagreeing claims by two patterns matching the same
text.

**Every cited evidence excerpt requires a real, non-empty citation, enforced at construction** --
`EvidenceExcerpt.__post_init__` refuses to build with real text but no citation, the same "an uncited
claim is refused outright" discipline `security_policy_ir.AccessRule`/`qos_policy_ir`/
`arbitration_policy_ir` already apply to their own domains. `build_feature_enablement_matrix()`
refuses a duplicate `(parameter_name, config_bit)` declaration and every malformed-input shape
(missing/blank parameter name, non-string config bit, non-list evidence, a non-mapping fact).
`overall_status()` folds the whole matrix worst-wins -- a single AMBIGUOUS entry outranks any number
of clean RESOLVED entries, and short of that a single NOT_AVAILABLE entry outranks an otherwise fully
RESOLVED matrix -- matching this project's universal no-averaging composite-gate rule.

**Deliberately bounded, and stated rather than implied closed.** It does not read RTL or a spec
document itself (the caller supplies the evidence text, exactly as `arbitration_policy_ir.py` does);
it does not decide a parameter's legal values or precondition (`sys_regmap.py`'s job); it does not
prove a parameter/bit corresponds to a real RTL signal (`register_rtl_trace.py`'s job); it decides,
approves and arbitrates nothing beyond its own classification and fold -- no build, job, or approval
is touched, and there is deliberately no stage gate. No `dv-harness` CLI verb or `gates.py`
`STAGE_GATES` entry was added -- both files are large and were left untouched per this task's own
house rule against editing them under batch edit pressure; the front door is
`python -m dv_harness.feature_enablement_matrix build --parameters <file.json> [--json]` (exit 0
RESOLVED, 1 AMBIGUOUS, 2 NOT_AVAILABLE/malformed). This is a REACHED capability, not a WIRED one.

Proven by `dv_harness_tests/test_feature_enablement_matrix.py` (39 tests, `python -m pytest
dv_harness_tests/test_feature_enablement_matrix.py -q` -> `39 passed`): the headline negative control
(name-conflicting-with-evidence never drives classification, and no-evidence never guesses from the
name) plus a second negative control (unrecognized evidence text stays `NOT_AVAILABLE`); every real
enablement phrase classified positively with its citation preserved; same-feature multi-citation
merging vs. different-feature AMBIGUOUS (both cited, never arbitrated); every construction-time and
build-time malformed-input refusal; the worst-wins `overall_status()` fold; markdown rendering; and
real end-to-end CLI subprocess invocations across all three documented exit codes plus the
wrapper-object input form. A full-repo `pytest --collect-only` (12100 tests, zero errors) confirms no
import-time collision was introduced elsewhere in the suite.


<!-- S285: moved verbatim from CLAUDE.md original lines 16977-17056 (M4.6 CLAUDE Context Normalization) -->
## Mode Extraction: Mode-Select Register Fields + Documented Legal Values (2026-09-06/07, section 286)

Spec section 286 (`CLAUDE_L5_SUBSYSTEM_DESIGN_INTELLIGENCE.md`) asks for real declared operating-MODE
facts -- a mode-select register field and its documented legal values -- extracted by reusing
`register_rtl_trace.py`'s and `sys_regmap.py`'s existing mode-bit machinery rather than a parallel
extractor. `dv_harness/mode_extraction.py` is exactly that, and only that: it imports both modules and
adds no second mode-bit classifier or RTL tracer of its own.

**Reuse, verified before writing anything.** `sys_regmap.py` already classifies every MODE-DETERMINING
bit in a real `sys_regmap.json` document (`iter_mode_determining_bits()`/`mode_determining_bits()`),
including a `control_kind` vocabulary that already distinguishes `*_select` kinds (`mux_select`/
`phy_select`/`pinmux_select` -- a field that picks ONE of several alternative configurations) from
plain enable/release kinds (`clock_enable`/`reset_release`/`power_enable`). `mode_select_bits()`
narrows that machinery's own result to the `*_select` subset -- the literal "mode-select register
field" this item names -- with `_assert_mode_select_kinds_known()` cross-checking the narrowing table
against the LIVE `sys_regmap.schema.json` `control_kind` enum at import time, so a future rename/
removal there fails loudly rather than silently narrowing or widening this module's scope.
`register_rtl_trace.py`'s `trace_register_field()`/`collect_rtl_sites()`/`parse_rtl_sources()` are
called directly for the RTL half, reusing that module's own four-status honesty vocabulary
(`TRACE_CONFIRMED`/`TRACE_PARTIAL`/`TRACE_NOT_FOUND`/`BLOCKED`) verbatim. Neither shared module was
edited -- `sys_regmap.schema.json` is read by several other concurrently-built extraction modules this
same session, and widening it for one narrow item would have been a wider-blast-radius change than
this item needs.

**Documented legal values are a caller-supplied, cited declaration -- never a schema edit.**
`sys_regmap.schema.json`'s own `field` definition carries exactly one documented value per
mode-determining bit (`required_value`, a Gate-2 precondition fact), never a full legal-value
enumeration for a multi-bit `*_select` field (e.g. a real `PHY_MODE_SEL[1:0]` field whose programming
guide documents `0x0=USB2_ONLY`/`0x1=USB3_ONLY`/`0x2=DUAL_ROLE`/`0x3=RESERVED`). No field anywhere in
this repository carries that enumeration, so `ModeValueDeclaration` is a plain, duck-typed,
CITATION-REQUIRED caller declaration rather than a schema change: construction refuses
(`ModeExtractionError`) without a real, non-empty citation and at least one real, non-duplicate
value/label pair -- an uncited "documented" value is exactly the unsupported claim the Evidence Truth
Rule forbids. A mode-select bit with no matching declaration reports the honest `NOT_DOCUMENTED`
status, never a fabricated value; two declarations naming the same (block, register, field) triple
report `CONFLICTING_DECLARATIONS`, citing both, and this module never arbitrates which one is correct
-- the same ARBITRATION boundary `requirement_contract.py`/`design_knowledge_correlation.py` already
keep for their own conflicting-claim findings. A separately-present Gate-2 `required_value` is
cross-checked against the documented legal-value set (`cross_check_required_value()`); a real
disagreement is reported as a finding, never resolved by picking one.

**Six-way worst-first status, never averaged.** `MODE_FACT_CONFLICTING_DECLARATIONS` (a real
contradiction between two documented sources) outranks `MODE_FACT_RTL_BLOCKED` (we never looked at
RTL) outranks `MODE_FACT_RTL_NOT_FOUND` (we looked and found nothing) outranks
`MODE_FACT_VALUES_NOT_DOCUMENTED` outranks `MODE_FACT_RTL_UNCONFIRMED` (an ambiguous RTL match) --
only a field clearing every one of those reads `MODE_FACT_CONFIRMED`.

**Deliberately bounded, and stated rather than implied closed.** Section 286 additionally lists entry/
exit sequencing, restricted operations and per-value interface lists as things to extract per mode.
This item's own assigned scope is narrower ("a mode-select register field and its documented legal
values"), and this module stays inside that scope honestly: `governs_interfaces`/
`applies_to_all_interfaces` (already-real `sys_regmap.py` facts) are carried through as a disclosed
PARTIAL answer to "valid interfaces", never presented as a full answer to section 286's wider list.
Entry/exit sequencing and restricted-operation lists are NOT extracted here -- they would need a real
controller-doc narrative extractor (closer to `design_intent.py`'s own cited `modes` list, which this
module deliberately does not import or duplicate: a narrative mode name like "HOST"/"DEVICE" is a
different fact from a register-field-level mode-select bit) or a real programming-sequence extractor
(`programming_sequence_ir.py`), neither of which this item names or this module reaches into. It
decides nothing beyond reporting a per-bit record: no build, no job, no approval, no memory write, and
there is deliberately no stage gate -- a gate that passed on a trace/declaration this module itself
says is ambiguous, conflicting or undocumented would be worse than none. There is no `dv-harness` CLI
verb: `cli.py`/`gates.py` are both large files under heavy concurrent edit in this same multi-agent
session, matching this project's own house convention of a standalone `python -m
dv_harness.mode_extraction` front door in that circumstance.

Proven by `dv_harness_tests/test_mode_extraction.py` (41 tests, `python -m pytest
dv_harness_tests/test_mode_extraction.py -q` -> `41 passed`): the mode-select-kind narrowing (with a
real negative control excluding `clock_enable`/`not_mode_determining` fields) and its live-schema
cross-check; every `ModeValueEntry`/`ModeValueDeclaration` construction refusal (bad hex value, missing
label, no citation, no values, missing identity, duplicate value, malformed dict shapes); the
required-value cross-check agreeing/disagreeing/absent cases; the full `extract_declared_modes()` path
against real, small synthetic sys_regmap/RTL fixtures (never real project content) driven through the
REAL `verible-verilog-syntax` subprocess (skipped, never mocked, on a machine without it) for CONFIRMED,
NOT_DOCUMENTED, CONFLICTING_DECLARATIONS, RTL_BLOCKED-with-no-corpus, and RTL_NOT_FOUND outcomes, plus
interface scoping, an unmatched-declaration report, an empty-document empty-report case, and
`sys_regmap.SysRegmapValidationError` propagation (fail-closed, matching `sys_regmap.py`'s own
discipline); markdown rendering; and the real `python -m dv_harness.mode_extraction` CLI driven through
`execute_verb()`/`main()` across its documented exit codes (0 confirmed, 1 a real finding, 2 a usage or
validation error).


<!-- S286: moved verbatim from CLAUDE.md original lines 17057-17125 (M4.6 CLAUDE Context Normalization) -->
## Performance Function Extraction: Documented Performance-Formula Facts, Never a Measurement (2026-09-07, section perf_function_extraction)

Nothing in this repo previously answered whether the DUT's own RTL or spec/programming-guide TEXT
already SAYS how a block computes a performance-related quantity -- "this block computes throughput
as (bytes_transferred / cycles_elapsed)", "Latency is defined as the number of cycles from request
issue to first response beat" -- as a plain, cited, human-authored FACT about the design, never a
measurement. `amba_performance_calculator.py` is pure ARITHMETIC over caller-supplied observed
numbers and its own CLAUDE.md section is explicit that it "never reads an FSDB/waveform file, never
monitors a live signal, never generates traffic, and never runs a simulation" -- a structurally
different, prior question from the one this module answers. `dv_harness/perf_function_extraction.py`
closes that narrow gap, and only that gap: it imports nothing from
`amba_performance_calculator.py`, `amba_performance_requirement_checker.py`,
`amba_performance_classification.py`, `amba_performance_readiness_gates.py`, `fsdb_report.py`, or
`sim_log_analysis.py`, and never evaluates any extracted formula text (no `eval`/`exec`/arithmetic of
any kind is performed on a matched expression anywhere in this module, proven directly by an
AST-based negative-control test).

**Why a line-scan, mirroring `interrupt_dma_clock_reset_extraction.py` rather than a document
distiller.** This fact can legitimately appear in either an RTL comment
(`// throughput_mbps = (num_beats * DATA_WIDTH_BYTES) / cycles_elapsed;`) or spec/programming-guide
prose ("This block computes throughput as the number of bytes transferred divided by the number of
elapsed cycles."), so this module takes the same real-file, declaration-level line-scan approach
`interrupt_dma_clock_reset_extraction.py` already established for the identical "may live in RTL OR
in prose" shape. A statement is recognised ONLY in one of three explicit, disclosed forms: (a) an
ASSIGNMENT-shaped line whose left-hand identifier itself names a recognised performance metric
(`throughput_mbps = ...`); (b) a VERB-FIRST sentence naming a compute/calculate/derive/measure/define
verb, then a metric keyword, then an explicit `as`/`by`/`via` introducing the definition/formula text
("computes throughput as ..."); (c) the symmetric METRIC-FIRST sentence form ("Throughput is computed
as ..."). A bare metric-keyword mention with no verb and no `as`/`by`/`via`/`=` tail (`// TODO: add a
throughput counter`) contributes nothing -- graceful degradation, never an invented fact. The metric
vocabulary is a small, fixed, disclosed set (THROUGHPUT, BANDWIDTH, LATENCY, UTILIZATION -- covering
"utilization"/"occupancy" -- and IOPS); a statement naming a performance concept outside this
vocabulary is honestly not recognised rather than guessed into the nearest-sounding bucket, and
nothing here infers a fact from a register/signal NAME alone -- only from the recognised statement
SHAPE.

Every reported fact carries the literal (possibly truncated) source line plus a real `<path>:<line>`
citation. `extract_performance_function_facts()` reads real files only (never fabricates), honestly
recording a missing/unreadable source per-file rather than silently skipping it or raising past the
caller; `status` is `NOT_AVAILABLE` when no source paths were supplied, when none of the supplied
paths could be read, or when every supplied source was read but contained no recognised
performance-function statement -- three distinct, honestly-worded reasons, never a single generic
"nothing found". Every document carries a fixed `PERF_FUNCTION_DISCLOSURE` string stating plainly
that these are documented facts, never a measurement, mirroring `phy_model_behavior_ir.py`'s own
`PHY_NOT_SILICON_DISCLOSURE` convention.

**Deliberately bounded, and stated rather than implied closed.** Computing, measuring or estimating a
single performance NUMBER is explicitly out of scope and stays `amba_performance_calculator.py`'s job
-- Performance Verification (any numeric latency/bandwidth/throughput TARGET or live measurement)
remains out of scope for this whole extraction, per the governing session's own stated exclusion. This
is a regex line-scan, not an NLP understander: a construct spanning an unusual continuation these
patterns do not anticipate contributes no citation rather than a wrong one. It reads and reports
only -- no build, job, or approval is touched, and there is deliberately no stage gate. No
`dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched, matching several sibling
modules' own disclosed choice under the same concurrent-edit-pressure file-safety scope -- the front
door is `python -m dv_harness.perf_function_extraction extract --sources <f> [<f> ...] [--json]`.

Proven by `dv_harness_tests/test_perf_function_extraction.py` (22 tests, re-run for this audit:
`python -m pytest dv_harness_tests/test_perf_function_extraction.py -q` -> `22 passed`): all three
recognised statement forms extracted with correct metric/formula/citation from both RTL comments and
spec prose; the required negative controls -- a bare metric mention with no formula never becomes a
fact (both in RTL and in prose), and an assignment whose left-hand name does not itself name a metric
is never a fact; source-handling honesty (no sources, all-missing sources, a mix of present and
missing sources, an unrecognized file suffix still read rather than silently skipped); the
`NOT_AVAILABLE`-with-real-reason path when sources are read but nothing recognised is found; the
disclosure string always present; direct proof the module never imports the arithmetic/measurement
modules and never calls `eval`/`exec` (AST-walked, not just grepped); and the real CLI driven as a
subprocess across its `--json`/`NOT_AVAILABLE`/usage-error exit-code paths.


<!-- S287: moved verbatim from CLAUDE.md original lines 17126-17141 (M4.6 CLAUDE Context Normalization) -->
## Design Intelligence Completeness Matrix: Register/PHY/Architecture Completeness Map + Worst-Wins Gate (documented retroactively, 2026-09-07)

`dv_harness/design_completeness_gate.py` (already present in the repo, `dv_harness_tests/test_design_completeness_gate.py` already passing at 59 tests) is the completeness rollup over this whole Design Intelligence extraction family's own outputs -- which of the real extraction categories a project has actually produced REAL FACTS for, versus NOT_AVAILABLE/UNKNOWN, worst-wins folded into one verdict, mirroring `golden_flow_readiness.py`'s own pattern one domain over. This section is being added now purely as a documentation catch-up: the module and its tests were already real and already passing; nothing in `dv_harness/` needed to change to satisfy this item, and no second, parallel completeness module was written alongside it (per the REUSE OVER REINVENT rule, duplicating an already-satisfying module would have been the wrong outcome).

**Thirteen rows, each naming its own real extractor.** `register_map` (`register_excel_extract.extract_register_map`), `register_rtl_trace` (`register_rtl_trace.trace_register_fields`/`parse_rtl_sources`), `phy_boundary` (`phy_boundary.extract_phy_boundary`), `phy_model_behavior` (`phy_model_behavior_ir.extract_phy_model_behavior_ir`), `architecture_ir` (`design_architecture_ir.build_architecture_ir`), `interrupt_dma_clock_reset`, `programming_sequence`, `verification_intent`, `dut_evidence_correlation`, `design_knowledge_correlation`, `design_source_inventory`, `spec_doc_map`, and `power_intent`. `assert_fact_sources_resolvable()` (run at test time, mirroring `golden_flow_readiness.py`'s own twenty-row anti-drift check) resolves every declared `fact_source` dotted path through the live import system, so a row whose extractor was since renamed away fails loudly instead of silently reporting a fabricated status.

**Reuse, not reinvention.** The READY/PARTIAL/BLOCKED/UNKNOWN vocabulary and `combine_readiness()` are imported verbatim from `golden_flow_readiness.py` -- not re-derived -- so the two modules can never silently disagree about what "worst-wins" means. `connectivity.render_markdown_table()` renders the matrix; there is no second hand-rolled table loop.

**Never fabricates.** Every one of the 13 `_probe_*` functions takes the caller's per-category real inputs (or none) and returns one of the four readiness classes: no input supplied -> `UNKNOWN` ("never even attempted"), a genuine parse/consistency failure -> `BLOCKED` with the real exception or defect text, a real-but-incomplete result -> `PARTIAL`, and only a real, complete, usable fact set -> `READY`. A probe's own exception is caught and reported as `BLOCKED` rather than crashing the whole matrix or dropping the row -- every declared row always appears in the output, "UNKNOWN" and "omitted" are never allowed to look alike.

**Worst-wins, held over 13 categories.** `derive_design_intelligence_completeness()` folds every row's status through the reused `combine_readiness()`: the whole project's `design_intelligence_completeness` verdict is `READY` only when every one of the 13 categories produced real, usable facts -- a single `BLOCKED`/`UNKNOWN` row drags the whole verdict down regardless of how many others are clean, never averaged or weighted away.

**Deliberately bounded, already disclosed by the module itself.** It derives nothing an existing extractor doesn't already compute -- every probe is a pure read over caller-supplied, project-declared inputs (there is no canonical on-disk path for a register-map spreadsheet or a PHY spec PDF the way there is for `.dv-harness/state.json`). It writes no state, runs nothing, and approves nothing (`authorizes: "nothing"` is stated in every matrix it produces). There is deliberately no `STAGE_GATES` entry and no `dv-harness` CLI verb -- per the house rule against editing `cli.py`/`gates.py` while under heavy concurrent edit pressure, the front door is the standalone `python -m dv_harness.design_completeness_gate --inputs <inputs.json> [--json]` script.

Proven by `dv_harness_tests/test_design_completeness_gate.py` (59 tests, re-run for this item and confirmed passing): row/probe-set consistency and duplicate-id self-checks; the anti-drift `assert_fact_sources_resolvable()` check plus a negative control proving a monkeypatched-away fact source is caught; a no-input-at-all run reporting every one of the 13 rows `UNKNOWN` and the whole matrix `UNKNOWN` (never a fabricated `READY`); a clean positive path and a genuine-defect negative control (missing file, empty workbook, malformed document/record, a real cross-source conflict, a fabricated register-to-RTL name) for every one of the 13 categories, each landing on its documented readiness class. Re-run together with `dv_harness_tests/test_golden_flow_readiness.py` (98 tests total) to confirm the reused readiness vocabulary and `combine_readiness()` fold introduce zero regression to the sibling module this one mirrors.


<!-- S288: moved verbatim from CLAUDE.md original lines 17142-17217 (M4.6 CLAUDE Context Normalization) -->
## Design Intelligence Maturity Gates: 9.0 / 9.5 / 10.0 (2026-09-06, verified 2026-09-07)

`dv_harness/design_intel_maturity_gates.py` mirrors `subsystem_maturity_gate.py`'s own real 9.0/9.5/10.0
monotonic-ladder pattern (strict monotonic requirement sets, worst-wins folding, a NOT_MEASURABLE
condition disclosed but never blocking, the same four-value condition vocabulary and three-value gate
verdict checked disjoint from `models.Status` at import time) -- applied to a DIFFERENT family entirely:
this project's "Design Intelligence" module family (`design_source_inventory.py`,
`design_architecture_ir.py`, `design_intent.py`, `design_knowledge_correlation.py`). Per its own
governing instruction, `subsystem_maturity_gate.py` is deliberately NEVER imported or modified here --
confirmed by a direct grep of the module's own import statements -- so the two files' change histories
stay independent and neither can accidentally regress the other's ladder.

**Six conditions, each one call into a real, already-existing producer function, confirmed by direct
search before writing any evaluation logic:**
- `architecture_ir_built` -- `design_architecture_ir.build_architecture_ir()`'s real parsed-RTL module
  registry + instance tree, UNMET on an unresolved duplicate-module-name collision.
- `source_registry_current` -- `design_source_inventory.build_source_registry()`, MET only when every
  declared source is confirmed CURRENT (never STALE/SUPERSEDED/NOT_AVAILABLE/UNKNOWN).
- `intent_extracted_with_citations` -- `design_intent.validate_intent()`: schema-valid, and every
  legal-drop/backpressure condition already REQUIRES a real document+section citation to validate at
  all.
- `constraints_extracted_with_units` -- `design_intent.validate_constraints()`: schema-valid, every
  numeric timing/electrical bound carries a unit.
- `knowledge_correlation_clean` -- `design_knowledge_correlation.correlate()` reports zero
  conflicts/gaps/documented-vs-implemented mismatches across the project's own extracted design facts.
- `source_discovery_completeness` -- **always `NOT_MEASURABLE`, honestly.** A repo-wide grep for a
  design-source auto-discovery scanner (`design_source_discover|walk_project_sources|repo_walk`) found
  nothing beyond `design_source_inventory.py`'s own docstring ("never writes or reads a snapshot store
  itself") and an unrelated VIP-source discoverer in `vip_capability_extraction.py`. No producer
  anywhere in this codebase can confirm the DECLARED source set is COMPLETE (only whether the declared
  entries are current) -- inventing a completeness counter here would be exactly the fabrication the
  Evidence Truth Rule forbids, so this condition names the search and reports the honest gap instead.

**Monotonic ladder, enforced at import** (`assert_levels_are_monotonic()`): `LEVEL_9_0 =
{architecture_ir_built, intent_extracted_with_citations}`; `LEVEL_9_5` adds `{source_registry_current,
constraints_extracted_with_units}`; `LEVEL_10_0` adds `{knowledge_correlation_clean,
source_discovery_completeness}`. A `NOT_MEASURABLE` required condition never blocks `QUALIFIED` (10.0
would otherwise be permanently unreachable) but is always carried on `disclosed_caveats`, so a
`QUALIFIED` 10.0 verdict is never silently read as "every extraction dimension was checked and clean."
An `UNMET` required condition always makes the level `NOT_QUALIFIED` (never softened to
`INCOMPLETE_EVIDENCE`); a `NOT_AVAILABLE` one (evidence genuinely missing) makes it
`INCOMPLETE_EVIDENCE` instead.

**It reads only.** No RTL is parsed, no document is validated, and no sources are correlated by this
module itself -- every condition either calls a real producer or reports honestly that the caller
supplied nothing to check. No stage runs, no build/regression/LSF job is submitted, and there is
deliberately no stage gate: a `QUALIFIED` verdict is an input to a human's qualification decision,
never a substitute for one.

Front door: `python -m dv_harness.design_intel_maturity_gates conditions|evaluate --level {9.0,9.5,10.0}
--root <dir> [--json] [--rtl-file ...] [--source-entries ...] [--intent-doc ...]
[--constraints-doc ...] [--knowledge-sources ...]`. No `dv-harness` CLI verb was added -- `cli.py`/
`gates.py` are large files under concurrent edit pressure from many items in this same batch, the same
disclosed choice several sibling same-day modules in this codebase already make.

Proven by `dv_harness_tests/test_design_intel_maturity_gates.py` (37 tests, re-run and confirmed
passing 2026-09-07): every condition driven against real evidence -- real parsed RTL via the real
verible front end (clean and duplicate-module-name cases), a real source registry (confirmed-CURRENT
and STALE cases), real schema-validated intent/constraints documents (valid, undeclared-transition-
state, missing-citation, and missing-unit negative controls), and real
`design_knowledge_correlation.correlate()` calls (agreeing sources, a real conflict, a real gap).
Negative controls give the suite its detection power: no RTL/no source entries/no documents each
report `NOT_AVAILABLE` rather than a fabricated `MET`; a real gate-shaped defect produces
`NOT_QUALIFIED`, never the softer `INCOMPLETE_EVIDENCE`; a renamed `fact_source` is refused rather than
silently reported MET; `source_discovery_completeness` is proven to never block a 10.0 `QUALIFIED`
verdict while still always appearing under `disclosed_caveats`; a direct AST-level test confirms
`subsystem_maturity_gate` is never imported; and `evaluate()` is proven to write nothing to disk. Both
CLI verbs are driven as real subprocesses, including a real exit-2 `INCOMPLETE_EVIDENCE` case.

**Deliberately bounded, and stated rather than implied closed.** (1) `source_discovery_completeness`
can never resolve to `MET` in this codebase today -- 10.0 can still be `QUALIFIED`, but always with
that gap disclosed, never silently cleared. (2) There is no `dv-harness` CLI verb, by deliberate choice
given `cli.py`'s own concurrent-edit pressure in this batch. (3) It does not import or read
`subsystem_maturity_gate.py`, by deliberate design, to keep the two items' change histories
independent.


<!-- S291: moved verbatim from CLAUDE.md original lines 17307-17320 (M4.6 CLAUDE Context Normalization) -->
## Per-Artifact Completeness: a Genuinely Different Axis From Per-Target Missing-Artifact Detection (2026-09-06)

Section 16's own instruction was to verify first whether `target_conditioned_missing_artifact_detector.py`'s real per-TARGET missing-artifact detection (4 named targets: VIP_UVM_CREATION/SIGNOFF_PACKAGE/COVERAGE_CLOSURE/REGRESSION_SUBMISSION) already substantially covers this section, and to add only a genuinely different completeness axis if one remained. It answers a per-(target, category) presence question at whole-category granularity (`vip_config_dump` present/absent/not-assessed) -- it never asks whether a category marked PRESENT is itself internally complete, or merely a half-populated stand-in.

`dv_harness/artifact_completeness.py` closes exactly that remaining axis, additively, and reuses rather than duplicates: it imports `target_conditioned_missing_artifact_detector.ARTIFACT_CATEGORY_DESCRIPTIONS` directly rather than re-declaring the category vocabulary, so there remains exactly one place in this repo naming the real artifact-category list. `ARTIFACT_REQUIRED_SUBFACTS` maps each of those same 14 categories to 2 concrete, named sub-facts a real downstream consumer in this codebase actually needs (e.g. `register_map` needs both `register_fields_present` and `register_access_types_present`; `waiver_ledger` needs `waiver_ledger_present` and `every_waiver_has_expiry_or_trigger`) -- never a generic "needs more content" placeholder, and `assert_table_covers_declared_categories()` runs at import to fail loudly on an unrecognized category, an empty sub-fact list, a duplicate `subfact_id`, or a blank reason.

**Three-valued sub-fact presence, never guessed -- the identical discipline the per-target module applies one level up, reapplied here at the sub-fact level.** A sub-fact in the caller's inventory is `True` (confirmed PRESENT), `False` (confirmed MISSING), or anything else/omitted (NOT_ASSESSED); an omitted key is never silently read as present or as absent. **The overall verdict per artifact is the strict worst of what was found**, per this project's Worst-Wins Composite Gates house rule: any confirmed-MISSING sub-fact makes the whole artifact `ARTIFACT_INCOMPLETE` (naming every missing sub-fact with its own reason) regardless of how many others are present; with none missing but at least one NOT_ASSESSED, the status is `ARTIFACT_ASSESSMENT_INCOMPLETE`; only when every required sub-fact reports confirmed-present does it read `ARTIFACT_COMPLETE`. An unrecognized category is `ARTIFACT_UNKNOWN_CATEGORY` with zero fabricated sub-fact findings.

This module decides and authorizes nothing beyond classification: it reads no file, runs no build/job/gate, and there is deliberately no stage gate. No `dv-harness` CLI verb was added -- `cli.py`/`gates.py` were out of this task's file-safety scope, the same disclosed choice several sibling same-day modules in this codebase already make -- the front door is `python -m dv_harness.artifact_completeness <CATEGORY> [subfact_inventory.json]` (exit 0 `ARTIFACT_COMPLETE`, 1 `ARTIFACT_INCOMPLETE`/`ARTIFACT_ASSESSMENT_INCOMPLETE`, 2 `ARTIFACT_UNKNOWN_CATEGORY`/usage error).

Proven by `dv_harness_tests/test_artifact_completeness.py` (37 tests, re-run alongside the pre-existing `test_target_conditioned_missing_artifact_detector.py`'s own 25 by this integration pass: `python -m pytest dv_harness_tests/test_artifact_completeness.py dv_harness_tests/test_target_conditioned_missing_artifact_detector.py -q` -> `62 passed`): the core positive path per real category; a reuse proof that every declared category is a real `target_conditioned_missing_artifact_detector` category (never a second, drifting vocabulary); the required negative controls -- an unrecognized category, an empty/omitted inventory (`ARTIFACT_ASSESSMENT_INCOMPLETE`, never `ARTIFACT_COMPLETE` or `ARTIFACT_INCOMPLETE`), a confirmed-absent sub-fact naming it specifically, MISSING outranking NOT_ASSESSED, and seven ambiguous values (`None`/`"unknown"`/`"yes"`/`1`/`0`/`[]`/`{}`) each proven to classify as NOT_ASSESSED rather than being guessed present or absent; a cross-category proof that two categories derive genuinely different sub-fact sets; uniqueness checks over every reason string and every subfact_id; the `assess_all_artifacts()` batch form only assessing what the caller actually supplied; and four real CLI subprocess invocations covering all three exit codes.

**Disclosed provenance**: this module was built by a separate, concurrently-running agent within the same multi-agent batch that also assigned this item; it was found complete and already passing when this item's own work began, and re-verified rather than duplicated, per this project's REUSE OVER REINVENT and low-collision-batch house rules.


<!-- S299: moved verbatim from CLAUDE.md original lines 17745-17831 (M4.6 CLAUDE Context Normalization) -->
## Fact-Type-Contextual Source Precedence: an Additive Override Layer Over source_authority.py (2026-09-07, dut_discovery)

`design_source_inventory.py`'s registry resolved every row's authority tier through
`source_authority.authority_source()` unconditionally -- the SAME fixed 9-level order for
every fact kind. That is correct for the overwhelming majority of what this project resolves
(functional-behavior conflicts: RTL should outrank a doc about what the silicon actually
does), but it is not universally correct: a project's own TIMING budget (setup/hold windows,
clock frequency, electrical levels) is routinely contracted in the controller doc/programming
guide/datasheet, and an RTL `//` comment restating it is a convenience note that can silently
drift from that contract -- exactly the real, in-repo grounding `timing_requirement_
extraction.py`'s own module docstring already states for why it extracts documented timing
bounds from spec/programming-guide text rather than trusting RTL comments. For a fact of that
kind, the fixed order gets the conflict backwards.

`dv_harness/contextual_source_precedence.py` is the missing layer, and it is strictly
ADDITIVE -- `source_authority.py` was not edited, and `source_authority.AUTHORITY_ORDER`'s
object identity is asserted unchanged by this module's own test suite. Every declared
override (`FACT_TYPE_OVERRIDES`, currently one entry: `"timing"`) is a real PERMUTATION of the
SAME 9 canonical ids `AUTHORITY_ORDER` already defines -- `FactTypeOverride.__post_init__`
refuses construction on a subset, a duplicate, or an invented id -- so this module can never
invent a tenth authority level or silently drop one of the nine. The Evidence Truth Rule is
enforced at the override's own construction boundary: an override with no non-empty `evidence`
citation is refused outright, the same discipline `security_policy_ir.AccessRule`/
`arbitration_policy_ir.ControllingMechanism` already apply to their own caller-declared facts
-- proven by a dedicated negative-control test (`test_override_refuses_construction_with_no_
evidence`).

**A fact type with no declared override -- including "functional", the task's own worked
example of the deliberately-unchanged case -- reduces to EXACTLY `source_authority.
resolve_conflict()`'s own result**, proven directly rather than merely asserted:
`test_no_override_reduces_to_exactly_source_authority_resolve_conflict()` runs the identical
`SourceClaim` pair through both `source_authority.resolve_conflict()` and this module's
`resolve_conflict_for_fact_type(claims, "functional")` and asserts byte-identical
verdict/winner/evidence_paths. `resolve_conflict_for_fact_type()` mirrors `resolve_conflict()`'s
own NO_CONFLICT/RESOLVED/UNDECIDABLE_SAME_AUTHORITY algorithm exactly (reusing `SourceClaim`
itself for every validation guarantee, never re-implemented), swapping only WHICH order breaks
the tie -- `contextual_sort_key()` reuses `source_authority.sort_key()` purely to obtain and
validate the register-file DUT-then-Global subrank, so there remains exactly one place in this
codebase that knows that tie-break.

**The reversal itself is proven, not merely described**:
`test_timing_fact_type_reverses_the_winner_versus_base_order()` resolves one real disagreeing
`dut_rtl`/`controller_doc` claim pair through `source_authority.resolve_conflict()` (winner:
`dut_rtl`, the base order) and through `resolve_conflict_for_fact_type(claims, "timing")`
(winner: `controller_doc`, the override) -- both winners' AND losers' evidence paths are
carried through in either case, since a reversed winner never means the loser's evidence is
dropped, mirroring `source_authority.escalate_conflict()`'s own "carries both sides' evidence"
contract.

**`design_source_inventory.py` gained one new, optional field** (`SourceEntry.fact_type`,
default `None`) threaded through `evaluate_source()` into `_resolve_authority()`. Omitting it
-- every pre-existing caller -- is proven byte-identical to this function's behaviour before
the override layer existed (`test_source_entry_without_fact_type_is_byte_identical_to_before`):
the same `rank`/`id`/`doc_phrase`/`status`/`reason`, plus one new key,
`authority_order_used: None`. A real `fact_type` reports the CONTEXTUAL rank instead, naming
which order actually decided it (`"PER_FACT_TYPE_OVERRIDE"` or `"BASE_AUTHORITY_ORDER"`) rather
than leaving a reader to infer it from the number alone.

**Deliberately bounded.** It arbitrates nothing -- deciding which VALUE wins a fact-type-
contextual conflict never means the losing artifact is fine to leave wrong, the identical
posture `source_authority.resolve_conflict()` itself takes; escalating a genuine disagreement
to a human stays `source_authority.escalate_conflict()`'s own job, untouched and unreferenced
here. It decides, approves and arbitrates nothing beyond ranking: no build, job, or approval is
touched, and there is deliberately no stage gate. There is no `dv-harness` CLI verb -- `cli.py`/
`gates.py` were not touched, per this batch's own file-safety scope; the front door is
`python -m dv_harness.contextual_source_precedence describe`.

Proven by `dv_harness_tests/test_contextual_source_precedence.py` (34 tests,
`python -m pytest dv_harness_tests/test_contextual_source_precedence.py -q` -> `34 passed`):
every override-construction refusal (no evidence, blank evidence, empty fact_type, a subset, a
duplicate, an invented id) paired with the one legitimate permutation-with-evidence positive
case and an alias-normalization case; `contextual_rank`/`contextual_sort_key` falling back to
the base order for `None`/`""`/`"functional"`/any undeclared fact type, and raising (never
fabricating) on an unrecognised source name; the register-file DUT-then-Global tie-break reuse
proof; the no-override-agrees-with-base-order proof across all three verdicts (RESOLVED,
UNDECIDABLE, NO_CONFLICT); the timing-override reversal proof; the required
same-source-still-UNDECIDABLE-under-an-override negative control (an override reorders tiers,
it never invents a same-tier tie-break); the `source_authority.AUTHORITY_ORDER` object-identity
guarantee; and the full `design_source_inventory.py` integration (byte-identical no-`fact_type`
behaviour, fallback for an undeclared fact type, the reversed rank under `"timing"`, both
`AUTHORITY_NOT_APPLICABLE` paths still carrying the new key, and a mixed-fact-type batch
through `build_source_registry()`). The pre-existing `dv_harness_tests/test_design_source_
inventory.py` (24 tests) and `dv_harness_tests/test_source_authority.py` (68 tests) suites were
re-run alongside it with zero regressions (92 passed), and a full-repo
`pytest --collect-only` (12415 tests) confirms no import-time collision was introduced
elsewhere in the suite.


<!-- S300: moved verbatim from CLAUDE.md original lines 17832-17909 (M4.6 CLAUDE Context Normalization) -->
## Architecture-Choice Ranking: Multiple Valid Bind Locations, Ranked Not Guessed (2026-09-07)

`connectivity.py`'s Gate 1/2/3 are binary PASS/FAIL checks over ONE already-chosen candidate
bind, and `phy_boundary.decide_bind_location()` likewise returns exactly one decision for one
PHY<->controller pair. Neither has ever had to choose BETWEEN two or more candidates that are
each individually valid (a DUT exposing the same functional interface at more than one
hierarchy level -- a raw PHY-facing port and a re-exported port one wrapper up, say) -- so
nothing in this repo ever compared two VALID bind locations against each other and said which
one is architecturally better, only whether one candidate is bindable at all.

`dv_harness/architecture_choice_ranking.py` closes exactly that, reusing three real producers
rather than re-deriving any of them. Bindability itself is never re-decided: each candidate
carries a caller-supplied `bind_decision` dict -- the real, unmodified output of
`phy_boundary.decide_bind_location()` for that candidate's own boundary -- and only its
`bindable` field is read. Wrapper/bridge hop counting reuses
`verification_architecture.derive_wrapper_bridge_chain()` verbatim (the same WRAPPER/BRIDGE/
UNCLASSIFIED per-hop classification `VipBindIR.chain_classification` is built from); a real
`BRIDGE`-classified hop is a real protocol/width conversion point a monitor mounted past it
would observe converted, not original, signals. "Cleaner clock-domain alignment" is read
literally off `verification_boundary_ir.py`'s own fixed `BoundaryClass` taxonomy: a candidate's
chain may carry zero or more CITED `VerificationBoundaryIR` declarations (built through
`verification_boundary_ir.build_verification_boundary_ir()`, unmodified, so an uncited
classification is refused exactly the way that module already refuses one), and this module
counts how many classify `CLASS_CLOCK_RESET` -- that module's own documented meaning for "a
clock-domain or reset-sequencing boundary (CDC, reset deassertion order)" -- i.e. how many real,
cited clock-domain crossings a candidate's bind chain traverses.

**Ranking order, matching the task's own stated priority.** Ascending, best first: (1) fewer
real `BRIDGE`-classified hops; (2) fewer real cited clock-domain crossings; (3) fewer total
hops (a tie-break); (4) `candidate_id`, for full determinism when every real signal ties.

**Evidence Truth Rule, applied to the ranking itself.** A candidate whose `bind_decision` never
reports `bindable: True` is not a "valid bind location" at all -- it is EXCLUDED, with a real
named reason (`NO_BIND_DECISION_SUPPLIED` / `BIND_DECISION_MISSING_BINDABLE_FIELD` /
`BIND_DECISION_NOT_BINDABLE`), and never ranked. Absent `boundary_declarations` for a candidate
(the key omitted entirely) is recorded as `clock_domain_crossing_status = "NOT_DECLARED"`, kept
honestly distinct from an explicit, caller-supplied EMPTY list (`"these are the hops I checked
and none are cited CLOCK_RESET boundaries"`, a genuinely stronger fact, classified `ASSESSED`
with `count == 0`) and from `"PARTIAL"` (some declarations were cited and counted, others were
malformed/uncited and are named in `boundary_declaration_errors` rather than silently dropped or
silently counted). Fewer than two valid candidates is reported as a real, distinct status
(`NO_VALID_BIND_LOCATION` / `SINGLE_VALID_BIND_LOCATION`) rather than a fabricated ranking over
nothing to compare.

**Deliberately bounded.** This module picks no bind target, emits no `bind` statement, and
authors no RTL/VIP content -- it only enumerates and ranks candidates a caller already built.
`phy_boundary.py`'s own bind-location decision for any one candidate is untouched; this module
never overrides `bindable`, it only compares several candidates that are each already
`bindable: True`. It decides, approves and arbitrates nothing beyond the ranking; there is
deliberately no stage gate. No `dv-harness` CLI verb was added and `cli.py`/`gates.py` were not
touched, per this batch's own file-safety scope -- the front door is `python -m
dv_harness.architecture_choice_ranking --candidates <file.json> [--json]`.

Proven by `dv_harness_tests/test_architecture_choice_ranking.py` (30 tests,
`python -m pytest dv_harness_tests/test_architecture_choice_ranking.py -q` -> `30 passed`)
against REAL evidence for the reuse claims: `phy_boundary.classify_boundary()`/
`decide_bind_location()` are called for real to produce a genuine PARALLEL, bindable
`bind_decision`, and a genuine MIXED boundary classification is fed through
`verification_architecture`'s own chain classifier to prove it really lands on `BRIDGE`;
`verification_boundary_ir.build_verification_boundary_ir()` is called for real (through this
module's own counting helper) to prove a `CLOCK_RESET`-classified boundary is really counted as
a crossing and an `EXTERNAL_PROTOCOL`-classified one is not. The required negative control,
`test_no_boundary_declarations_is_honestly_not_declared_never_zero_assessed`, proves an omitted
`boundary_declarations` key is never silently read as "zero crossings confirmed" -- it stays
`NOT_DECLARED` with `clock_domain_crossings is None` -- paired with
`test_explicit_empty_boundary_declarations_is_assessed_zero_distinct_from_not_declared` proving
an explicit empty list is honestly the stronger, different fact. Ranking-order tests cover every
tie-break level individually; exclusion tests cover all three exclusion reasons plus the
zero-valid and exactly-one-valid report statuses; malformed-input tests cover every shape defect
(missing/blank/duplicate `candidate_id`, non-list `candidates`, non-dict candidate/
`bind_decision`/`chain_hops`/`boundary_declarations`) raising rather than being silently
skipped; and both real CLI exit-code paths (`--json` and default markdown rendering, plus the
malformed-input exit-2 path) are driven end to end. The reused modules'
own suites (`test_verification_boundary_ir.py`, `test_verification_architecture.py`,
`test_connectivity.py`, 360 tests combined with this module's own) were re-run alongside it with
zero regressions, and a full-repo `pytest --collect-only` (12426 tests) confirms no import-time
collision was introduced elsewhere in the suite.


<!-- S301: moved verbatim from CLAUDE.md original lines 17910-17998 (M4.6 CLAUDE Context Normalization) -->
## DUT Power-State Transition Graph: Built Only From Documented Sequences (2026-09-07)

`power_intent.py` is a real UPF reader and self-consistency analysis over power DOMAINS, SUPPLY
topology, and SWITCH/ISOLATION/RETENTION strategies -- its own module docstring is explicit about a
boundary it deliberately never crosses: "Power STATE tables (`add_power_state`, `create_pst`,
`add_pst_state`) are parsed as unsupported-but-recorded rather than modelled." So a UPF file can name
real power states, but nothing there turns them into a TRANSITION GRAPH -- which state may legally
move to which other state, and under what documented trigger. `dv_harness/
dut_power_state_transition_graph.py` closes exactly that gap, and only that gap: it does not import
or edit `power_intent.py` at all.

**Structurally never simulation-derived, and disclosed as such on every report.** This project owns
no live simulator and no low-power DUT of its own (`power_intent.py`'s own docstring says so in as
many words), so a transition graph derived by actually exercising a DUT through its state machine is
not something this harness can honestly produce. What it CAN produce is a graph built from what a
real spec/programming-guide document already SAYS about legal transitions -- an arrow chain, a
"From X to Y" sentence, or a From/To transition table -- never a claim about what silicon or RTL
actually does. `GRAPH_NOT_SIMULATION_DISCLOSURE` is carried on every report (LOADED or
NOT_AVAILABLE) this module produces.

**`spec_doc_map.py`'s real role here is DISCOVERY, not extraction, and it is never imported.** That
module's own docstring is explicit that it retains NO body prose, ever -- its `.structure_map.json`
can tell a caller WHERE a power-state section or a transition table lives (a heading, a table
caption, a real page number), never what it says. This module is the sibling that then reads the
real TEXT a caller supplies at that location, exactly the same "spec/programming-guide TEXT a caller
supplies" convention `design_lifecycle_flow.py`/`interrupt_dma_clock_reset_extraction.py`/
`perf_function_extraction.py` already use. Its own heading-detection helper is re-derived locally
(never imported from `design_lifecycle_flow.py`), per this codebase's own established convention
that each extraction module owns its own small bounded regex helper (`memory_buffer_arch_
extraction.py`, `rtl_data_path_extraction.py`, `amba_command_txt_extension.py` each already do the
same) and per `spec_doc_map.py`'s own stated reasons for staying independent of
`vip_user_guide_distill.py` (scope, and independent testability in a multi-agent batch).

**Three real, disclosed edge shapes, tried per line inside a heading-detected power-state/power-mode
section -- a line matching none of them contributes nothing, never a guessed edge.** (1) An ARROW
line (`D0 -> D1`, `D0 <-> D3`), with an optional trailing `(trigger)` / `: trigger` /
`on <event>`/`when <condition>` annotation; a bidirectional arrow yields TWO edges, both citing the
same line and both flagged `bidirectional_pair: true`, since the same trigger text may not apply
identically in both directions. (2) A "From X to Y[,:] <trigger>" sentence, the real prose form a
power-management chapter routinely uses instead of a diagram. (3) A Markdown-table row under a real
`From | To | Trigger` (or `.../Condition/Event`) header. No domain reasoning is performed anywhere:
a state's NAME is never validated against a known vocabulary, and two differently-cased state names
(`"D0"` vs `"d0"`) are two different nodes -- merging them incorrectly would silently misrepresent
the document's own distinct names as one.

**Graph facts computed from the extracted edges are mechanical, never a domain claim.** `nodes` is
the union of every `from_state`/`to_state` actually named by a real edge -- a state is never
independently "declared". `terminal_states` (no outgoing edge) and `source_states` (no incoming
edge) are a real degree count, presented only as the structural fact a reader can interpret
themselves -- never labelled "illegal deadlock" or "legal entry point". `has_cycle` is a real
DFS-based cycle detection (`detect_cycle()`) over the extracted directed graph -- a genuinely
computed property, and a real power-state machine legitimately having a cycle (e.g. ACTIVE <-> IDLE)
is never treated as a defect. `default_state` is populated ONLY from an explicit, cited "default/
initial power state is X" or "reset (power) state is X" sentence found in the same section text;
absent one, it is honestly `None` with `default_state_status = "NOT_DOCUMENTED"` -- never inferred
from graph structure (e.g. "the state with the most incoming edges is probably the default"), which
would be exactly the confident guess the Evidence Truth Rule forbids.

**Evidence Truth Rule, applied at every layer, mirroring `design_lifecycle_flow.py`'s own
discipline.** Zero sources supplied, every supplied source unreadable, no power-state/power-mode
heading found anywhere, and a heading found with no recognizable edge shape beneath it are each a
distinct, honestly-worded `NOT_AVAILABLE` reason -- never collapsed into one generic "nothing found".
A missing/unreadable file is recorded per-source rather than silently skipped or raised past the
caller.

**Deliberately bounded, and stated rather than implied closed.** (1) This is a line/regex scan, not a
document-structure parser or a diagram-image reader -- a transition described only as an embedded
state-diagram IMAGE, or as prose narrative with none of the three recognized shapes, contributes
nothing rather than a guessed reconstruction. (2) It decides, approves and arbitrates nothing beyond
reporting: no build, job, or approval is touched, and there is deliberately no stage gate. (3) There
is no `dv-harness` CLI verb and `cli.py`/`gates.py` were not touched, matching this project's own
disclosed convention for a standalone module built while those two files are under concurrent edit
pressure in a multi-agent batch -- the front door is `python -m
dv_harness.dut_power_state_transition_graph extract --sources <f> [<f> ...] [--json]`.

Proven by `dv_harness_tests/test_dut_power_state_transition_graph.py` (19 tests, all real, against
small synthetic fixtures built inline -- never mined from any real vendor spec or this project's own
vendored `USB_UVM_Handoff`/`uvm_syoscb-1.0.2.4`/`ATB` reference trees, per No Golden-Reference Content
Mining): all three edge shapes extracted with correct citations, including the bidirectional-arrow
two-edge case and the default-state sentence found inside the same section; the negative control that
content under an UNRELATED heading (e.g. `IRQ_A -> IRQ_B` under "Interrupt Handling") is never
extracted as a power-state transition; real cycle detection on both a genuine 3-state cycle and an
acyclic 2-edge chain; terminal/source-state degree facts; every `NOT_AVAILABLE` reason (no sources, an
unreadable source, no heading at all, a heading with no recognizable edge shape) proven distinct and
honest; the `default_state_status = "NOT_DOCUMENTED"` honesty path when no citing sentence exists; the
`models.Status` vocabulary-collision guard; and the real CLI driven both in-process
(`execute_verb()`) and as a real `python -m dv_harness.dut_power_state_transition_graph` subprocess.
`python -m pytest dv_harness_tests/test_dut_power_state_transition_graph.py -q` -> `19 passed`.


<!-- S302: moved verbatim from CLAUDE.md original lines 17999-18073 (M4.6 CLAUDE Context Normalization) -->
## DUT Errata/Known-Issues Correlation to RTL (2026-09-07, dut_errata_correlation)

No module anywhere discovered or parsed an errata/known-issues document, let alone correlated a
named erratum to the specific RTL region/register it affects -- a repo-wide grep for
`errata`/`known_issue`/`ERR-` before this module returned nothing executable. An agent asking "does
erratum ERR-042 in the vendor's silicon errata sheet still apply to the register block this
environment binds against" had no bounded artifact to answer from and no honest way to get one short
of opening the whole document and re-deriving the RTL correspondence by hand every time.

`dv_harness/dut_errata_correlation.py` closes it, reusing rather than reinventing on both halves:

- **Structural extraction reuses `spec_doc_map.py`'s own PATTERN, not its code** (that module is not
  imported, for the same independent-testability reasoning its own docstring already gives for not
  importing `vip_user_guide_distill.py`): the same real `pypdf.PdfReader(...).pages[i].extract_text()`
  call, the same "raise rather than silently produce a partial artifact" discipline
  (`ErrataDocumentError`, mirroring `SpecDocMapError`), the same mechanically-detected line-pattern
  regex idea, and the same two-artifact-pair convention (`<stem>.errata_index.json` /
  `<stem>.errata_index.md`). What is detected differs because the document family differs: ERRATUM
  header lines ("Erratum 12: Title", "Errata ID: ERR-042 - Title", a bare "ERR042: Title") and, within
  each erratum's own bounded text block, LABELED evidence fields ("Affected Register: CTRL0",
  "Silicon Revision: A0, A1", "Workaround: ..."). A label is matched by its own text, never by what
  its value says -- the identical discipline spec_doc_map.py's heading/caption regexes already state.
  Only a short (<=300 char) excerpt of an erratum's non-labeled lines is persisted -- never the full
  description/workaround prose -- the same "structure, not a document-body dump" contract.
- **Correlation reuses `dut_evidence_correlation.py` directly**, a real import of a stable,
  already-shipped module: every cited affected-component name is turned into that module's own
  declared-fact item shape (`fact_type="feature"`, searching every dut_facts layer) and handed to its
  unmodified `correlate_item()`. This module adds nothing to that module's own five-status verdict; it
  only rolls several citations' worth of it up into ONE honest per-erratum status, since one erratum
  can legitimately cite more than one affected component: `RTL_LOCATED` (a real exact match exists),
  `RTL_PARTIALLY_LOCATED` (only an unproven substring match), `RTL_NOT_LOCATED` (every citation was
  searched and none found -- a real negative), `NO_AFFECTED_COMPONENT_CITED` (the erratum's own text
  named nothing to correlate), `NOT_AVAILABLE` (a citation exists but no manifest was available to
  check it against -- never collapsed into `RTL_NOT_LOCATED`, "we could not look" is a different claim
  from "we looked and it is not there").

`analyze_errata(source_path, manifest_path, out_dir=None)` is the one-shot front door this task's own
"reporting NOT_AVAILABLE honestly when no errata document is supplied" requirement is enforced by: a
`None`/empty/nonexistent `source_path`, or one `extract_errata_document()` genuinely cannot open
(missing pypdf, an unsupported suffix), reports the honest top-level `NOT_AVAILABLE` with the real
reason and correlates nothing -- never a silent clean pass over zero errata.

**Deliberately bounded, and stated rather than implied closed.** (1) Erratum-header detection is
bounded to three real, conventional shapes; a document using a different convention (a flowed table,
a numbered-heading style) contributes zero detected errata, reported as a real honest zero. (2)
Labeled-field detection is bounded to a small, explicit label vocabulary, and only the first
`MAX_BLOCK_LINES` (250) lines following a detected header are scanned. (3) Affected-component NAME
matching against RTL/registers is entirely `dut_evidence_correlation.py`'s own job -- this module's
own name-based / no-fuzzy-synonym / no-semantic-matching limits apply here identically. (4) It decides
nothing beyond reporting: no build, job, approval, or stage gate is touched, and there is no
stage-gate entry for it. No `dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched,
per house rule 7 -- the front door is `python -m dv_harness.dut_errata_correlation
{extract|correlate|analyze|show}`.

Proven by `dv_harness_tests/test_dut_errata_correlation.py` (25 tests) against a REAL synthetic
3-erratum PDF built with `reportlab` (never a real vendor's errata sheet) and a REAL env.manifest.json
built through `env_manifest.generate_and_write()` over a real verible-parsed RTL file and a real
register-map JSON. Coverage includes both real header forms, labeled-field extraction (affected
component, silicon revision, workaround presence, status), the excerpt cap and the never-persists-full-
prose proof, the honest real-zero case (a document with no recognisable erratum header), a real exact
RTL/register match (`RTL_LOCATED`), a fabricated affected-component name against an available manifest
(`RTL_NOT_LOCATED`), an erratum citing nothing (`NO_AFFECTED_COMPONENT_CITED`), a real substring-only
match (`RTL_PARTIALLY_LOCATED`, never upgraded), the required negative control -- no manifest supplied
at all reads `NOT_AVAILABLE`, never silently collapsed into `RTL_NOT_LOCATED` -- and the mandatory
`analyze_errata()` "no document supplied" contract (`None`, empty string, and a genuinely missing file
all report `NOT_AVAILABLE`). Both the module's Python API and its real `python -m` CLI (all four verbs,
their documented exit codes, and a real subprocess round trip) are driven end to end. Re-ran
`test_dut_evidence_correlation.py` (24 tests) and `test_spec_doc_map.py` (13 tests) alongside it to
confirm neither reused module regressed; a full-repo `pytest --collect-only` (12539 tests) confirms no
import-time collision was introduced elsewhere in the suite.

**Disclosed residual.** This is REACHED, not WIRED: no `run_stage()`/`advance()` call site invokes it
and no graph node declares it -- a caller (a human, a future doc-extraction fan-out entry, a dashboard
card) invokes it directly.


<!-- S308: moved verbatim from CLAUDE.md original lines 18414-18512 (M4.6 CLAUDE Context Normalization) -->
## VIP ScenarioPatternIR <-> command.txt branch_b* Correspondence, Audit-First (2026-09-07)

**Audit finding, confirmed by direct search before any code was written.** No mechanism in this
repo cross-checked that a real command.txt/pattern file's `branch_b*` (VIP-owned) sequence usages
actually correspond to a real, classified `VIPScenarioPatternIR` entry. `vip_capability_
extraction.py` classifies VIP-indexed classes into `IR_VIP_SCENARIO_PATTERN` -- a purely STATIC
classification over the VIP's OWN declared classes -- and a repo-wide grep for
`IR_VIP_SCENARIO_PATTERN`/`VIPScenarioPatternIR` before this closure found exactly one file using
that IR type: the classifier itself. `command_task_trace.py`'s VIP_API leg finds a `// VIP:`
citation inside an already-GENERATED environment's own `.sv`/`.svh` files -- it never reads a
command.txt file's own text and has no `VIPScenarioPatternIR` record set to check a citation
against. `de_command_style_learning.py` already guesses a per-statement `branch_owner` (GLOBAL/
DUT/FW/VIP) from a command.txt's own text, including a real name-evidence VIP-sequence guess for a
`MODEL_TASK_CALL` statement -- but it never cross-checks that guess against `vip_capability_
extraction.py`'s real classification; its own docstring states its scope stops at "what does this
file's OWN text say". So the gap was real, exactly as prior triage anticipated.

`dv_harness/scenario_pattern_command_txt_correspondence.py` closes it, built entirely on REUSE
rather than a fourth parallel report shape: `vip_config_field_usage_coverage.py` is the real,
existing PRECEDENT for this exact SHAPE of cross-check (`VIPConfigIR` declared fields vs. real
command.txt usage) -- this module follows its same two-directional used/unused-plus-fabrication-
risk report, its same honest `NOT_AVAILABLE` discipline, and its same word-boundary name-evidence
matching, applied to the missing `IR_VIP_SCENARIO_PATTERN` axis instead of inventing a new shape.

**What "branch_b* usage" means, and why it is not a second branch-label scanner.** This module
never scans for literal `fork ... : branch_b0` block labels -- that would be a second, competing
branch-ownership heuristic sitting beside `de_command_style_learning.py`'s own real one. A
"branch_b* sequence usage" is defined here, honestly and narrowly, as a real command.txt/pattern
statement that module's own `build_de_command_registry()` classified `kind == K_MODEL_TASK_CALL`
AND `branch_owner == BRANCH_OWNER_VIP` -- that module's own cited, name-evidence guess. A
statement it could not confidently classify VIP-owned is never treated as a `branch_b*` usage
here either, inheriting that module's own honesty rather than re-deriving a stronger (or weaker)
one -- disclosed, not hidden: a real dispatch shaped differently (a bare macro call whose sequence
name lives only in an argument, never a dotted `MODEL_TASK_CALL`) is invisible to this module too.

**Two match kinds, never conflated.** `PRIMARY_TASK_SEGMENT_EXACT` -- the usage's own dotted
MODEL_TASK_CALL name (e.g. `` `HOST_SEQ.svt_demo_base_sequence ``) has a task segment (the text
after the last `.`) exactly equal to a declared class's real `class_name` -- the strongest evidence
this module can produce. `TEXT_OR_ARGUMENT_REFERENCE` -- the class name appears, word-boundary
matched, in the usage's own raw statement text or one of its arguments -- weaker evidence, carried
and labeled as such. A usage matching neither is `CORRESPONDENCE_NOT_FOUND` -- the real
fabrication-risk finding this module exists to surface: a command.txt statement this project's own
heuristic believes is a VIP-sequence dispatch, naming something no real, classified
`VIPScenarioPatternIR` class in the supplied classification set corresponds to. This is never proof
the named VIP sequence does not exist anywhere in the real VIP -- only that it does not correspond
to anything the SUPPLIED classification (built over whatever VIP source that caller actually
indexed) found; a narrower/incomplete VIP index under-classifies, and this module inherits that
honestly rather than assuming a wider index than was actually built.

**The reverse direction, symmetrically honest.** A real, classified `VIPScenarioPatternIR` class
that no `branch_b*` usage in the scanned command.txt/pattern set ever names is
`NOT_USED_IN_COMMAND_TXT` -- mirroring `vip_config_field_usage_coverage.py`'s own DEAD_OR_UNUSED
discipline for fields, applied here to classes. A project whose real command.txt files genuinely
contain zero `branch_b*` usage at all is not silently reported `NOT_AVAILABLE` for that reason
alone -- real files WERE scanned, and "this VIP declares scenario patterns nobody's command.txt
ever dispatches" is itself a real, actionable, `ANALYZED` finding.

**The fabrication risk, and how this module refuses it.** `CORRESPONDENCE_NOT_FOUND` and
`NOT_USED_IN_COMMAND_TXT` are never asserted from silence -- both are reported only after this
module has REALLY built at least one real `DECommandRegistryIR` from a real, readable command.txt/
pattern file, and every finding's own `reason` names exactly how many real files were checked.
Supplying zero scenario-pattern records, zero command files, or command files that all fail to read
makes the WHOLE report `NOT_AVAILABLE` with a real, distinct reason -- never a report that quietly
claims every usage is a fabrication, or every declared pattern is dead, because nothing was
actually checked.

Ad hoc: `python -m dv_harness.scenario_pattern_command_txt_correspondence --capability-report
<vip_capability_extraction.json> --command-file <path> [--command-file <path> ...] [--out-dir DIR]
[--json]` (exit 0 every usage corresponds and every pattern is used, 1 a real
`CORRESPONDENCE_NOT_FOUND`/`NOT_USED_IN_COMMAND_TXT` finding, 2 `NOT_AVAILABLE`). No `dv-harness`
CLI verb was added and `cli.py`/`gates.py` were not touched, matching this project's own disclosed
choice for a standalone module built while those two files are under concurrent edit pressure in a
multi-agent batch. It decides nothing beyond reporting: no build, job, approval, or stage gate is
touched, and there is deliberately no stage gate.

Proven by `dv_harness_tests/test_scenario_pattern_command_txt_correspondence.py` (17 tests) against
the REAL synthetic `svt_demo_base_sequence` VIP fixture this repo already ships (the same one
`vip_config_field_usage_coverage.py`'s own tests reuse), classified by the real, unmodified
`vip_capability_extraction` pipeline: every absence-of-evidence path; the headline positive
(`PRIMARY_TASK_SEGMENT_EXACT` match, both sides marked correctly) and negative (a fabricated
sequence name reported `CORRESPONDENCE_NOT_FOUND`, with the real declared pattern correctly staying
`NOT_USED_IN_COMMAND_TXT`) controls; the weaker `TEXT_OR_ARGUMENT_REFERENCE` match kind; a
word-boundary substring-never-matches negative control; the required negative control proving a
real but non-VIP-owned (`branch_owner == GLOBAL`) `MODEL_TASK_CALL` statement is never treated as a
`branch_b*` usage at all, confirming this module's own reuse of `de_command_style_learning.py`'s
real heuristic rather than a looser scan of its own; multi-file scanning; a malformed-record
refusal; the real on-disk `vip_capability_extraction.json` reuse path; and both real CLI entry
points (all three documented exit codes) driven as real subprocesses. Re-ran
`test_vip_capability_extraction.py`/`test_de_command_style_learning.py`/`test_vip_config_field_
usage_coverage.py`/`test_command_task_trace.py` alongside it (72 tests) to confirm neither reused
module regressed; a full-repo `pytest --collect-only` (12791 tests) confirms no import-time
collision was introduced elsewhere in the suite.

**Disclosed residual.** This is REACHED, not WIRED: no `run_stage()`/`advance()` call site invokes
it and no graph node declares it -- a caller (a human, a future gate, a dashboard card) invokes it
directly. `branch_b*` scope is exactly `de_command_style_learning.py`'s own real `MODEL_TASK_CALL`
+ `branch_owner == VIP` heuristic; a real VIP-sequence dispatch shaped differently is invisible to
this module, exactly as it is invisible to the module it reuses.


<!-- S309: moved verbatim from CLAUDE.md original lines 18513-18638 (M4.6 CLAUDE Context Normalization) -->
## Multi-VIP Cooperation Architecting: When a DUT+PHY Topology Genuinely Needs Two Cooperating VIP Instances (2026-09-07)

`ip_ownership_conflict.py`'s own docstring states its scope precisely: "does THIS ONE subsystem's
own environment declare a real VIP agent AND a legacy hand-written BFM/driver BOTH active on the
SAME interface/port?" -- a single-interface, VIP-vs-legacy-BFM CONFLICT check. It has no notion of
TWO real VIP instances at TWO DIFFERENT interfaces that legitimately both belong there and must
work TOGETHER -- a dual-role USB port switching between host and device mode, a hub's upstream
(device-facing) and downstream (host-facing) ports, a bridge/repeater with two link partners. A
repo-wide grep for `multi_vip`/`MultiVip`/`vip_cooperation`/`host_device`/`host-side.*device-side`
before this module returned nothing executable.

`dv_harness/multi_vip_cooperation_architecting.py` closes that gap, and re-derives nothing any
existing module already computes -- every real fact is read straight off a producer this project
already ships:

- **VIP instance identity** -- `ip_ownership_conflict.real_vip_instances()`, imported verbatim: the
  SAME `env.manifest.json` `vip_config.vip_instances` reader, excluding the SAME
  `connectivity.NO_VIP_MARKERS` entries. No second VIP-instance extractor exists in this module.
- **VIP role per interface** -- `connectivity.determine_role_from_port_direction()`, called on the
  interface's own real declared RTL port direction -- never guessed from an interface's own label (a
  port declared `interface_id="host"` whose real direction disagrees is not trusted over the
  direction; construction refuses a missing/invalid direction rather than silently defaulting one).
- **PHY-boundary bindability per interface** -- `phy_boundary.extract_phy_boundary()` /
  `decide_bind_location()`, called on real parsed RTL module ports (accepting either a caller-supplied
  already-computed doc, or `phy_module`+`controller_module`+a shared `rtl_modules` list, the identical
  duck-typed convention `verification_architecture.py` already established for the same producer).
  This module derives no SERIAL/PARALLEL/MIXED verdict of its own.
- **Bind-chain / bridge classification** -- `verification_architecture.build_vip_bind_ir()` /
  `derive_wrapper_bridge_chain()`, called per cooperating pair's own real bind targets.
- **Shared virtual-sequencer composition mode** -- `system_virtual_sequencer.
  build_subsystem_composition()`, called DIRECTLY on the cooperating pair's own `VipBindIR` list,
  treating the pair as the "subsystem" that module's own API already accepts. That module's own
  worst-wins `DIRECT_HANDLE`/`ADAPTER_REQUIRED`/`COMPOSITION_UNDETERMINED`/`NOT_AVAILABLE` fold IS
  this task's own "shared virtual-sequencer needs" answer -- reused, not reinvented.
- **Sequencing dependency** -- `runtime_event_registry.RuntimeEventRegistry`/`propagate()`, this
  project's own real, tested stop-on-failure dependency-propagation engine, applied to one real event
  per cooperating interface (`<interface_id>::VIP_LINK_READY`). This module builds the events; it
  NEVER invents which one depends on which -- a real, cited `REQUIRES`/`WAITS_FOR`/`TRIGGERS`/
  `UNBLOCKS` relation between two interfaces' events must be supplied by the caller (a spec citation,
  an RTL mode-arbitration reference) before any sequencing dependency is reported; absent one, the
  honest answer is `NOT_DECLARED`, never a guessed ordering.
- Table rendering reuses `connectivity.render_markdown_table()`.

**Evidence Truth Rule: cooupling is never guessed from a name.** Exactly ONE coupling kind is
structurally DERIVED with no interpretation required: two interfaces declaring the IDENTICAL real
`bind_target` are, by definition, the same physical DUT+PHY instance (`SHARED_PHY_INSTANCE`) -- the
real dual-role-port case (proven directly: two interfaces named `host_mode`/`device_mode` sharing one
`bind_target` auto-derive the fact, citing the real shared instance path). Every OTHER coupling kind
(`SHARED_CLOCK_RESET_DOMAIN`/`INTERNAL_SIGNAL_PATH`/`MODE_SELECT_SHARED_CONTROL`/
`SHARED_ADDRESS_REGION`) must be caller-declared with a real, non-empty evidence citation -- an
uncited coupling claim is refused at construction, matching this project's own
`arbitration_policy_ir.py`/`qos_policy_ir.py`/`security_policy_ir.py` discipline for their own
domains. Two structurally unrelated interfaces with no coupling fact at all are never treated as
cooperating -- the honest `NO_MULTI_VIP_COOPERATION_DETECTED` common case.

**Four honest per-pair cooperation statuses, never collapsed.** `COOPERATION_REQUIRED` only when BOTH
interfaces' own real PHY-boundary evidence says a monitor may legitimately bind there
(`VIP_REQUIRED_BINDABLE`/`VIP_REQUIRED_NOT_BOUND`) AND a real coupling fact links them.
`COOPERATION_UNCONFIRMED_NOT_BINDABLE` when a real boundary verdict says one side is explicitly NOT
bindable (SERIAL-only/UNDECIDABLE) -- proven directly against a real SERIAL-only synthetic PHY pair.
`COOPERATION_UNKNOWN_INSUFFICIENT_EVIDENCE` when no real boundary evidence exists for one side at all
-- checked BEFORE `NOT_BINDABLE` so "we could not check" is never conflated with "confirmed not
bindable". Only a `COOPERATION_REQUIRED` pair gets a full sequencing/composition architecture built;
the other two report `architecture_status: NOT_APPLICABLE` rather than a fabricated one.

**`architecture_status` treats a real BLOCKED sequencing finding as ARCHITECTED, not incomplete.**
Proven directly: a real observed `TIMEOUT` on one interface's event, propagated by the real
`RuntimeEventRegistry.propagate()`, reports `DECLARED_BLOCKED` with the real `BLOCKED_BY_DEPENDENCY`
finding -- and `architecture_status` still reads `ARCHITECTED`, since the dependency STRUCTURE is
real and known; whether it currently holds is a separate, additional fact carried in the same record,
never a reason to call the architecture itself incomplete. `ARCHITECTURE_INCOMPLETE` is reserved for
the case nothing at all was declared to answer the question (`NOT_DECLARED` sequencing, or an
unresolved `COMPOSITION_UNDETERMINED`/`NOT_AVAILABLE` composition mode).

**Whole-record `overall_status` is worst-wins over every reported pair** -- `COOPERATION_DETECTED_
ARCHITECTURE_INCOMPLETE` (a real cooperation requirement exists but is not fully architected yet)
outranks `COOPERATION_ARCHITECTED` (fully resolved, including a real `ADAPTER_REQUIRED` composition --
proven against a real MIXED/bridge hierarchy hop) outranks `INSUFFICIENT_EVIDENCE` (every reported
pair was uncertain) outranks the honest `NO_MULTI_VIP_COOPERATION_DETECTED` default.

**Scope boundary -- architecture record only, never content or arbitration.** This module authors no
VIP API, sequence body, or RTL content (No Golden-Reference Content Mining) -- `ADAPTER_REQUIRED`
names the fact that an adapter is needed and cites the real bridge evidence; it never invents what
that adapter's sequence should do. It picks no winner between two active drivers -- that stays
`ip_ownership_conflict.py`'s/`system_resource_inventory.py`'s own territory, untouched here. It
decides, approves and arbitrates nothing: no build, job, or approval is touched, and there is
deliberately no stage gate. No `dv-harness` CLI verb was added -- `cli.py`/`gates.py`/`dashboard.py`
were explicitly out of scope for this task (several concurrent workflows were actively editing those
files); the front door is `python -m dv_harness.multi_vip_cooperation_architecting --input <file.json>
[--json] [--markdown]` (exit 0 `COOPERATION_ARCHITECTED`/`NO_MULTI_VIP_COOPERATION_DETECTED`, 1
`COOPERATION_DETECTED_ARCHITECTURE_INCOMPLETE`, 2 `INSUFFICIENT_EVIDENCE`/malformed input).

Proven by `dv_harness_tests/test_multi_vip_cooperation_architecting.py` (31 tests,
`python -m pytest dv_harness_tests/test_multi_vip_cooperation_architecting.py -q` -> `31 passed`),
every structural input built through a REAL producer -- the identical synthetic PHY/controller port
pair fixture `test_verification_architecture.py`'s own `host_vip`/`dev_vip` scenario already uses for
`phy_boundary.extract_phy_boundary()`, a real `ip_ownership_conflict.real_vip_instances()`-shaped
env.manifest.json, real `verification_architecture.build_vip_bind_ir()` and `system_virtual_
sequencer.build_subsystem_composition()` calls, and a real `runtime_event_registry.
RuntimeEventRegistry.propagate()` run -- nothing hand-shaped to merely look like a producer's output.
Negative controls carry the detection power: no coupling evidence at all never fabricates a
cooperation finding; an uncited coupling claim, a coupling fact naming an undeclared interface, an
unrecognized coupling kind, a duplicate interface id, a half-declared PHY-boundary pair
(`phy_module` with no `controller_module`), a bad `dut_port_direction`, an out-of-scope/uncited/
unrecognized sequencing relation, and an unrecognized observation status are all refused rather than
silently coerced; a real SERIAL-only boundary and a real no-boundary-evidence case are each proven to
land on their own distinct honest status rather than being promoted to `COOPERATION_REQUIRED`; and the
vocabulary-collision guard is proven to have real detection power via monkeypatch. All four CLI exit
codes are driven as real subprocesses. The reused-module suites (`test_ip_ownership_conflict.py`,
`test_verification_architecture.py`, `test_system_virtual_sequencer.py`,
`test_runtime_event_registry.py`, `test_connectivity.py` -- 377 tests combined) were re-run and pass
unchanged, and a full-repo `pytest --collect-only` (12763 tests) confirms no import-time collision was
introduced elsewhere in the suite.

**Disclosed residual**: this is a REACHED capability, not a WIRED one -- no `run_stage()`/`advance()`
call site invokes it and no graph node declares it. Beyond the one structurally-derived
`SHARED_PHY_INSTANCE` kind, coupling detection is entirely caller-declared; this module performs no
RTL data-flow tracing of its own to discover an `INTERNAL_SIGNAL_PATH`/`MODE_SELECT_SHARED_CONTROL`/
`SHARED_ADDRESS_REGION` coupling automatically -- a project wanting one of those derived would need a
separate extractor (e.g. `mode_extraction.py`'s real mode-select-field evidence, or
`address_map_integrity_checker.py`'s real overlap detection) to supply the citation this module then
accepts. Sequencing-dependency observation support (`sequencing_observations`) covers only the
`RuntimeEventObservation` shape that module already defines; this module runs no simulation and reads
no sim.log/waveform itself to produce one.



<!-- S310: moved verbatim from CLAUDE.md original lines 18639-18759 (M4.6 CLAUDE Context Normalization) -->
## Orphaned/Leaked-Fork Detection: branch_b* Dispatch-Then-Wait Pairing (2026-09-07, de_command_txt)

`.claude/skills/CORE/pattern-architecture/SKILL.md` section 3.5 names a real, recurring trap class:
a `branch_b*`-internal non-blocking VIP-sequence DISPATCH needs a paired, explicit WAIT for that
specific dispatch's completion before the branch that dispatched it is allowed to report a result
-- "the pairing is a property of the dispatch call itself... and it recurs inside `branch_b*`
bodies themselves, not just at the top-level fork." Confirmed by direct reading before building:
nothing in this repo checked that. `command_task_trace.py`'s own module docstring already states its
VIP_API/UVM_BRIDGE legs are "DECLARATION-LEVEL TEXTUAL CROSS-REFERENCE ONLY" -- they answer "does a
VIP API get cited somewhere in this command's resolved body", never "does this specific non-blocking
dispatch have a paired wait before the branch concludes". The one existing check anywhere near this
question, `uvm_generator/templates/sim_scripts/check/pattern_rules.py`'s R7 rule, is a WHOLE-FILE
COUNT check ("if `FORK_SEQ appears anywhere and `WAIT_SEQ_ALL appears nowhere, fail") -- it cannot
see the partial-pairing case this module exists to catch (three `FORK_SEQ dispatches, one
`WAIT_SEQ_ALL, so the last two dispatches are still orphaned), because it never scopes to a
branch_b* region or walks dispatches in program order. `shared_bus_resource_registry.py` is a
different, INTRA-subsystem bus-arbitration RACE detector (branch_fw vs. branch_a*, over
CALLER-DECLARED resource facts, explicitly because "there is no SystemVerilog pattern-body parser
anywhere in dv_harness/") -- a different question at a different scope, and is not extended here.

`dv_harness/orphaned_fork_detection.py` closes it, and reuses rather than reinvents the one real
statement-level parser this codebase already has: `reference_pattern_audit.
extract_command_statements()` (the SYS-7 comment-stripped, classified command.txt parse -- K_MACRO_
CALL / K_BLOCK_BEGIN / K_BLOCK_END / K_FORK / K_JOIN, each carrying a real per-statement `line`
citation and a real per-statement `block_depth`, the nesting depth AT that statement, already
computed by that module's own begin/end/fork/join depth-tracking). This module never re-derives
comment stripping, bracket-depth tracking, or macro-call classification -- it imports and calls that
one function to get the statement stream, then adds exactly the two things that function does not
do: locating `begin : branch_b*` region boundaries, and walking dispatch/wait statements in program
order within one located region.

**Region location reuses the parser's own already-computed depth, never a second counter.**
`find_branch_b_regions()` matches each `K_BLOCK_BEGIN` statement's own `.text` against
`^begin\s*:\s*(branch_b\d*)\b` (canonical 0-indexed `branch_b{i}` per `branch_ownership_resolver.py`'s
own naming rule, plus the real legacy bare `branch_b` shape `pattern_rules.py`'s own docstring
documents for the older two-branch shape -- naming CONFORMANCE stays that module's job, not this
one's, so a legacy label is still scoped and checked, never skipped) and records that statement's own
`block_depth` as the region's depth `D`. The region's close is the first subsequent `K_BLOCK_END`/
`K_JOIN` statement whose OWN `block_depth` equals `D` -- a balanced-parens property the reused
parser's depth field already guarantees, so no stack or counter is re-implemented here. A begin with
no such close found before end-of-file is `REGION_NEVER_CLOSED`, an honest, distinct, more severe
finding -- never silently treated as spanning to EOF, which could hide a real trap behind a wait call
that was never actually reachable from inside that branch.

**Pairing semantics match what `WAIT_SEQ_ALL` actually means, not a naive count.** `` `WAIT_SEQ_ALL ``
joins EVERY currently-outstanding forked sequence at once (the macro's own name says so, and it is
the one real, evidence-cited macro pair `pattern_rules.py`'s own R7 rule text already documents:
"real concurrency needs `FORK_SEQ, and every `FORK_SEQ needs a `WAIT_SEQ_ALL"), so ONE wait call
legitimately pairs with SEVERAL preceding dispatches -- proven directly by a dedicated test
(`test_one_wait_call_legitimately_pairs_with_several_preceding_dispatches`) that a naive 1:1
count-mismatch check would have wrongly flagged. A dispatch is PAIRED iff at least one wait statement
occurs LATER by real line number, in program order, WITHIN THE SAME REGION -- a wait sitting after the
region has already closed does not count, the module's own concrete instance of section 3.5's own
point that pairing "is a property of the dispatch call itself, not something the surrounding fork/join
at a higher layer can substitute for" (proven by
`test_a_wait_call_after_the_region_has_already_closed_does_not_pair`). `` `RUN_SEQ ``-shaped macros are
deliberately NOT treated as a dispatch: this codebase's own real evidence
(`pattern_rules.py`'s `USB_EVIDENCE` pattern) uses `` `FORK_SEQ ``/`` `RUN_SEQ\w* `` interchangeably only
as "this pattern touches the target IP" evidence, never as proof `` `RUN_SEQ `` is non-blocking, and
inventing that semantic distinction would be a guess this module refuses to make. A project whose own
real convention differs may override `dispatch_pattern`/`wait_pattern` with its own compiled regex
over the macro's backtick-prefixed name (proven by
`test_custom_dispatch_and_wait_patterns_are_honored_not_ignored`) -- never guessed or widened past the
one real, cited default on this module's own initiative.

**The Evidence Truth Rule's negative control**: an unclosed region (`REGION_NEVER_CLOSED`) never
receives a fabricated pairing verdict -- `findings` stays empty and neither `ALL_DISPATCHES_PAIRED`
nor `ORPHANED_DISPATCH_FOUND` is ever reported for it, even when a real `` `WAIT_SEQ_ALL `` genuinely
exists in the unbounded remainder of the file (proven by
`test_unclosed_region_is_reported_honestly_and_never_gets_a_fabricated_pairing_verdict`). A file with
no `branch_b*` region at all is `NOT_APPLICABLE`, kept honestly distinct from `CLEAN` (nothing to check
is not the same claim as "checked and found nothing wrong"). A region with dispatches but zero wait
calls anywhere orphans every one of them; a region with no dispatch at all is trivially
`NO_DISPATCH_FOUND`, never a fabricated finding.

**Declaration-level bound, stated rather than implied closed**, the same bound
`command_task_trace.py`/`uvm_structural_lint.py` already state for their own textual scans: this is a
program-order scan, not an elaborator -- no `` `ifdef ``/generate condition is evaluated, and a wait
sitting inside an `if`/`case` branch that can never actually execute is still counted as pairing
evidence. A `begin : branch_b<N>` label combined with a dispatch macro call on the exact same physical
line (never the convention this codebase's own real templates use) is a known limitation of the
reused parser's single-line-flush behaviour and is not special-cased here.

**Detection only.** This module never edits a pattern file, never invents a wait call, never picks
which dispatch a missing wait "should" pair with, and never touches a build/regression/LSF job or any
human-approval/governance mechanism. There is deliberately no stage gate and no `dv-harness` CLI verb
(`cli.py`/`gates.py` untouched, per this project's own disclosed convention for a standalone module
built while those two files are under concurrent edit pressure from other work in this same batch) --
the front door is `python -m dv_harness.orphaned_fork_detection --file <f> [--file <f> ...] | --dir
<dir> [--glob *.txt] [--json]`.

Proven by `dv_harness_tests/test_orphaned_fork_detection.py` (24 tests, all synthetic fixtures built
directly in the test file, never mined from any real project's command.txt/pattern content, matching
`test_reference_pattern_audit.py`'s own established convention): the vocabulary-collision guard's real
detection power (a real `dv_harness.models.Status` token deliberately injected trips it); the
clean-pairing and multi-dispatch-one-wait positive paths; the headline orphaned-dispatch-after-the-
last-wait case (the exact gap R7's whole-file count check cannot see); zero-wait-orphans-every-
dispatch; the wait-after-region-close negative pairing proof (section 3.5's own named point, made
concrete); the two required honest-absence negative controls (`REGION_NEVER_CLOSED` and
`NOT_APPLICABLE`, neither ever silently reads as a clean pass); multiple independent regions in one
file each evaluated on their own; the legacy bare `branch_b` label still scoped and checked; the
dispatch/wait pattern override; real file-level I/O (`analyze_pattern_file()` against a real temp
file, `UNREADABLE` on a missing path); the low-level `find_branch_b_regions()` driven directly against
a REAL `reference_pattern_audit.extract_command_statements()` parse (proving reuse rather than a
second parser); a full `analyze_pattern_directory()` end-to-end rollup over a real synthetic directory
(clean/findings/not-applicable files mixed, with the correct worst-wins overall status); and the real
CLI driven end to end across its `--file`/`--dir`/`--json` paths and all three documented exit codes.
`python -m pytest dv_harness_tests/test_orphaned_fork_detection.py -q` -> `24 passed`; a full-repo
`pytest --collect-only` (12708 tests) confirms no import-time collision was introduced elsewhere in
the suite, and `test_reference_pattern_audit.py` (13 tests, the module this one reuses) was re-run
alongside it and remains unmodified and passing.

**Disclosed residual.** This is REACHED, not WIRED -- no `run_stage()`/`advance()` call site invokes
it and no graph node declares it, and no `gates.py`/`STAGE_GATES` entry was added. It never checks a
DIFFERENT class of dispatch (a raw `` `uvm_do* ``/`.start_item()`-based fork with no macro wrapper, a
project-specific non-`` `FORK_SEQ `` convention with no override supplied) -- only the one real,
cited macro pair this codebase already documents by default, and whatever a caller explicitly
overrides it to. It never runs against a generated environment automatically; a caller (a human, a
future `command_generation_gate.py` extension, a stage gate) invokes it directly over real generated
pattern files.


<!-- S312: moved verbatim from CLAUDE.md original lines 18818-18882 (M4.6 CLAUDE Context Normalization) -->
## branch_fw Internal State Verifier: ARM/WAIT/WAKE/DECODE/CLEAR Against Real Generated Text (2026-09-07)

`pattern_runtime_state_machine.py` tracks per-PATTERN state only, and its own module docstring
explicitly disclaims branch_fw's internal `interrupt-event-dispatch/SKILL.md` ARM/WAIT/WAKE/DECODE/CLEAR
loop as a separate, already-generalized loop owned elsewhere. `runtime_event_registry.py` likewise only
carries a caller-DECLARED event set with no notion of this five-state shape at all. A repo-wide grep
confirmed neither module -- nor anything else in this repo -- ever opened a real generated
`command.txt`/pattern file and checked that the five states the SKILL's own worked example names
(ARM -> WAIT -> WAKE -> DECODE -> CLEAR) are genuinely present, in that order.

`dv_harness/branch_fw_internal_state_verifier.py` closes exactly that gap, reusing rather than
reinventing on every axis. `command_task_trace.trace_command()`'s TASK_MACRO leg is the ONLY thing
that decides how a branch_fw command/task NAME resolves inside a real generated environment; this
module's own `_locate_task_body()` follows that leg's citations one hop further (direct declaration,
case-dispatch handler, `` `define `` macro redirect, or a `patterns_registry`-mapped file) using
`command_task_trace._TASK_BODY_RE_TMPL` verbatim -- the same reuse shape `cpuread_byte_shift_
checker.py` already established for this exact leg. Statement extraction and classification over the
located body is entirely `reference_pattern_audit.extract_command_statements()`/`classify_wait()`;
this module's own WAIT-state evidence IS that function's real `INTERRUPT_EVENT_WAIT` verdict, never a
second interrupt-vs-plain-wait classifier -- and requiring that real classification is exactly what
grounds "this is genuinely branch_fw's own loop," not a bare textual resemblance to five arbitrary
words.

**Evidence per state, never averaged into a fabricated verdict.** ARM is a real `REGISTER_WRITE`
before WAIT's own line citing an arm/enable/trigger/mask token in its comment/arguments (a small,
disclosed, cited vocabulary -- no token match anywhere before WAIT is honestly `UNKNOWN`, never "the
nearest write must be it"). WAKE is the worked example's own specific shape: a real bracket-matched
`fork`/`join_any` pair genuinely ENCLOSING the WAIT statement (found by a real forward/backward
bracket match over the body's own FORK/JOIN statement stream, never assumed from program order) -- a
plain `wait(...)` with no enclosing fork, or a fork closing with plain `join`/`join_none`, is honestly
`UNKNOWN`; this module never credits a wait's own textual completion as a documented WAKE event.
DECODE is the first `REGISTER_READ` after the WAKE (or, when WAKE is `UNKNOWN`, WAIT) anchor. CLEAR
is a `REGISTER_WRITE` after DECODE, evidenced either by targeting the SAME register address DECODE
just read (the real write-1-to-clear shape) or by a clear/ack/w1c token citation --
`reference_pattern_audit.build_ordering_constraints()` deliberately never emits this read-then-write
relation ("read-then-anything carries no ordering obligation," its own comment); this module is the
first thing in this repo that decides that specific question, for this one cited purpose.

**Worst-wins order verification.** A genuine order violation among the states this module could
determine (checked via a dedicated helper that compares each consecutive pair in ARM/WAIT/WAKE/
DECODE/CLEAR order) always outranks an honest "incomplete" report. Only when every determinable
state's own line is strictly ascending, AND all five states were determined, does the loop read
`ALL_STATES_VERIFIED_IN_ORDER`.

Deliberately bounded: it reads real generated text only and decides nothing beyond its own five-state
report -- no build, job, or approval is touched, and there is deliberately no stage gate. There is no
`dv-harness` CLI verb and `cli.py`/`gates.py` were not touched, per this batch's own scope
restriction -- the front door is `python -m dv_harness.branch_fw_internal_state_verifier --env-dir
<dir> --command <name>` (resolved via `command_task_trace`) or `--file <path>` (a whole pattern file
that IS one branch_fw body), both real, read-only, and exit-code-driven (0 verified, 1 a real order
violation, 2 incomplete/unresolvable).

Proven by `dv_harness_tests/test_branch_fw_internal_state_verifier.py` (21 tests): the full positive
loop verified in order; every honest-`UNKNOWN` negative control (no interrupt-classified wait at all
cascading WAIT/WAKE/DECODE/CLEAR to `UNKNOWN`, a missing ARM token never guessed from proximity, a
wait not enclosed by any fork/join never credited as WAKE, a fork closing with the wrong join kind
citing exactly what was found, missing DECODE/CLEAR after a real WAKE); both CLEAR evidence paths
(same-address and token-cited); the ordering helper proven directly against a hand-built out-of-order
state list; and the full `command_task_trace` resolution path -- direct declaration, one-level macro
redirect, `AMBIGUOUS_TASK_RESOLUTION`, `COMMAND_NOT_FOUND`, `BLOCKED` -- plus a real CLI subprocess
round trip. The reused modules' own suites (`test_command_task_trace.py`,
`test_reference_pattern_audit.py`, `test_cpuread_byte_shift_checker.py`, 59 tests) were re-run
alongside it with zero regressions. `python -m pytest
dv_harness_tests/test_branch_fw_internal_state_verifier.py -q` -> `21 passed`.


<!-- S313: moved verbatim from CLAUDE.md original lines 18883-18953 (M4.6 CLAUDE Context Normalization) -->
## Real-Generated-File Layer-Ordering Verification: Actual Text, Not Declared Intent (2026-09-07)

`pattern_ir_assembly.validate_layer_ordering()` only ever validates a caller-SUPPLIED
`declared_order` list against `DEFAULT_LAYER_ORDER` -- it never opens a real generated file.
`branch_ownership_resolver.py`'s own module docstring says so outright: "Neither function reads
RTL, a VIP index, or a command.txt file... this module reasons over that declaration, it does not
derive it." `tools/verification_flow/branch_topology_gate.py` (cited by that module as "the single
source of truth for the canonical form") likewise reads only a caller-declared JSON `topology`
document's `branches` list, never a real file's own text. So nothing in this repository had ever
confirmed that a real generated pattern file's own statements are actually laid out in the required
order, as opposed to merely being DECLARED that way in some separate, possibly-stale manifest.

`dv_harness/real_file_layer_ordering_verification.py` is that missing check, scoped exactly to the
task's own three layers -- `block`, `branch_a*`, `branch_fw` (`pattern_ir_assembly.LAYER_GLOBAL` /
`LAYER_DUT` / `LAYER_FW_POLICY`). It reuses two real vocabularies rather than inventing either a
second one: `pattern_ir_assembly.DEFAULT_LAYER_ORDER`'s first three entries, imported and asserted
consistent at import time (`REQUIRED_LAYER_SUBSEQUENCE`), and `amba_discovery_report.py`'s
`L5_BRANCH_BLOCK`/`L5_BRANCH_FW`/`l5_branch_a` -- the exact canonical-naming source
`branch_ownership_resolver.py` already cites as this repo's single source of truth after three-to-four
incompatible naming conventions were once found coexisting here.

**Evidence, never a bare word search.** A canonical label is recognised only in a real structural
position this project's own command.txt-shaped fixtures already establish as evidence of an actual
launch/declaration site (see `dv_harness_tests/test_branch_ownership_resolver.py`'s own
`CANONICAL_PATTERN_TXT`): a whole-token argument inside a backtick-macro call's parentheses
(`` `SOC_GLOBAL_INIT(block)``, `` `USB_FORK_PORT_BRINGUP(branch_a0, branch_a1)``,
`` `USB_FORK_FW_SERVICE(branch_fw)``), a label immediately followed by `:` at line start, a
SystemVerilog named-block form (`begin : branch_fw`), or a `task <label>(...)` declaration. Comments
and string literals are blanked out (length- and newline-preserving, so real line numbers never
shift) before any regex runs, the same discipline `design_architecture_ir.py`'s own FSM literal scan
already applies for the identical false-positive reason -- a canonical label spelled only inside a
`//` comment or a `"..."` string is never counted as evidence. Only the FIRST real occurrence of each
canonical label counts as that layer's genesis line: `branch_fw` is documented
(`pattern-architecture/SKILL.md` section 1) as legitimately idempotent against being invoked more
than once, so a later real re-launch is not itself a defect this module reports.

**Three honest, never-collapsed statuses**, checked disjoint from `dv_harness.models.Status` at
import time: `FILE_ORDER_CONFIRMED` (all three layers found, real genesis lines strictly increasing
in the required order); `FILE_ORDER_VIOLATION` (all three found, but out of order -- names the exact
offending pair and both real cited line numbers); `LAYER_NOT_FOUND` (one or more layers has no real,
structurally-recognised occurrence anywhere in the file -- never silently treated as "in order" and
never guessed). `verify_actual_layer_order(text, path=...)` is the pure-function core;
`verify_file(path)` reads a real file from disk.

**Deliberately bounded, and stated rather than implied closed.** This is a declaration-level
line/regex scan, not a SystemVerilog parser and not an elaborator -- a real project using an entirely
different macro-authoring convention than the one this repo's own fixtures establish (or a
pre-canonical, legacy-naming file, like this project's own real
`examples/generated_usb_real_evidence_v1/tb/patterns/common/USB2_con_vip.txt`, which never spells
`block`/`branch_a*`/`branch_fw` at all) honestly reports `LAYER_NOT_FOUND` rather than a fabricated
confirmed order. It decides, approves and arbitrates nothing beyond reporting: no build, job, or
approval is touched, and there is deliberately no stage gate. No `dv-harness` CLI verb was added and
`cli.py`/`gates.py` were not touched, per this task's own instruction that both files are under
concurrent edit pressure from other work in this same batch -- the front door is
`python -m dv_harness.real_file_layer_ordering_verification <file> [--json]` (exit 0 CONFIRMED, 1
VIOLATION, 2 LAYER_NOT_FOUND/NOT_AVAILABLE), matching several sibling same-day modules' own disclosed
choice under the identical constraint.

Proven by `dv_harness_tests/test_real_file_layer_ordering_verification.py` (28 tests): the canonical
positive path against this project's own established real command.txt-shaped fixture convention;
comment/string-literal blindness and the bare-English-word-"block" negative control; the
first-genesis-line-only rule proven against a real repeated `branch_fw` re-launch; a real
out-of-order file and a real file genuinely missing `branch_fw`, each reported honestly; named-block
and `task` declaration forms; and a real negative-control run against this project's own real,
pre-canonical legacy example file, correctly reporting `LAYER_NOT_FOUND` rather than a fabricated
confirmed order. `execute_verb()`/CLI driven both in-process and as two real `python -m` subprocess
invocations across all three exit codes. The reused modules' own regression suites
(`test_pattern_ir_assembly.py`, `test_branch_ownership_resolver.py`, `test_amba_discovery_report.py`
-- 121 tests) were re-run alongside it with zero regressions. `python -m pytest
dv_harness_tests/test_real_file_layer_ordering_verification.py -q` -> `28 passed`.


<!-- S314: moved verbatim from CLAUDE.md original lines 18954-19031 (M4.6 CLAUDE Context Normalization) -->
## Shared VIP Sequencer Registry: Intra-Subsystem branch_b*-vs-branch_b* Race Detection (2026-09-07)

`shared_bus_resource_registry.py` implements exactly ONE conflict type: `branch_fw` (the shared
per-port FW/event-service loop) racing a `branch_a{i}` (a per-port DUT+PHY bring-up task) over one
shared BUS resource, with no common named lock. That module's own docstring states its detection
scope is specifically that one pair, and its own `derive_conflict_status()` deliberately reports
`NO_CONFLICT` for a resource shared only among several `branch_a*` (or only ever touched by
`branch_b*`) -- calling those OUT of its own scope, not uncovered.

`dv_harness/shared_vip_sequencer_registry.py` is the sibling module `pattern-architecture` 3.1
itself illustrates with its own worked example (`block`/`branch_a*` DUT-driven vs `branch_b*`
VIP-driven): TWO DIFFERENT `branch_b{i}` bodies -- e.g. `branch_b0`'s and `branch_b1`'s own
VIP-driven parallel scenario tasks -- can both reach ONE shared VIP agent/sequencer instance AT
THE SAME TIME, through two DIFFERENT named locks/sequencer-ownership tokens the arbitration layer
can then interleave in an order neither branch's author controls -- the identical failure mode,
one task-group pair over. Neither `shared_bus_resource_registry.py` nor
`system_resource_inventory.py`/`ip_ownership_conflict.py` models a `branch_b*`-vs-`branch_b*` pair
at all: this module closes exactly, and only, that gap.

**Reuse over reinvent, verified.** `classify_task_group()` and `normalize_programmers()` are
imported and used VERBATIM from `shared_bus_resource_registry.py` (proven by object-identity
assertion in the test suite) -- they are generic over the whole `block`/`branch_a{i}`/`branch_fw`/
`branch_b{i}` vocabulary, not FW/A-specific, so importing them here is genuine reuse. That module's
own `_locks_agree()`/`derive_lock_policy()` are module-private, so the tiny "two programmers are
serialized only when both name the same real lock; an absent lock never agrees with anything,
including another absent lock" rule is restated locally rather than imported across a private
boundary -- everything else is reused.

**Evidence, honestly.** No producer in this codebase extracts "which named lock a `branch_b{i}`
task holds while driving VIP agent/sequencer X" from a real `command.txt` pattern or VIP source --
there is no SystemVerilog pattern-body parser anywhere in `dv_harness/`. WHICH `branch_b{i}` body
programs WHICH shared VIP construct under WHICH named lock is therefore CALLER-DECLARED
(`sequencer_declarations`), never inferred, and every declared programmer record REQUIRES a real
`evidence` citation. A declaration with no evidence, or naming a `task_group` outside the canonical
vocabulary, is marked invalid and drives an honest `UNKNOWN` status rather than a silent `CLEAR` --
and a non-canonical name is deliberately NEVER read as proof a second `branch_b*` role is ABSENT (a
naming defect is not evidence of absence), the same subtlety the sibling module's own TDD negative
control caught. Two declarations for the SAME `branch_b{i}` index are never compared against each
other (not a race between two DIFFERENT bodies) and report `NO_CONFLICT` naming that this module's
scope is specifically two different bodies; a resource shared only among `branch_a*`/`branch_fw`/
`block` programmers with no `branch_b*` body at all is likewise explicitly out of scope and reports
`NO_CONFLICT`, never a fabricated verdict about a pairing this module was not asked to judge.
`connectivity_rows` is an OPTIONAL second input, used only to resolve a declared construct's real
hierarchy path (never invented when absent), via the identical bind_target-match convention the
sibling module already uses.

**Vocabulary.** Report `status`: `CONTENTION` / `CLEAR` / `NOT_APPLICABLE` / `UNKNOWN` (mirroring
the sibling module's own 4-status shape). Per-construct `conflict_status`: `BRANCH_B_RACE` /
`NO_CONFLICT` / `NOT_APPLICABLE` / `UNKNOWN_INSUFFICIENT_EVIDENCE`. `lock_policy` reuses the
identical 5-value vocabulary. `resource_type` is caller-declared from a fixed set (`VIP_AGENT` /
`VIP_SEQUENCER` / `VIP_VIRTUAL_SEQUENCER`) or `UNCLASSIFIED` -- never guessed from a construct's
name, and an unrecognized value is carried through verbatim with `resource_type_recognized: false`.
A racing entry's `conflicting_owners` names the real branch ids, declared lock names and evidence
citations on BOTH sides of every non-agreeing `branch_b{i}`-vs-`branch_b{j}` pair (`i != j`).

**Detection only, matching the sibling module's own stated boundary.** This module never picks a
lock, never edits a pattern file, never invents a lock name, and never touches any
approval/governance mechanism -- a human aligns the racing `branch_b*` bodies onto one real named
lock, from real VIP/pattern evidence. Front door: `python -m
dv_harness.shared_vip_sequencer_registry --sequencer-declarations <file>
[--connectivity-rows <file>] [--json]` (no `dv-harness` CLI verb wired, per this batch's own
instruction not to edit `cli.py`/`gates.py`; exit 0 `CLEAR` / 1 `CONTENTION` / 2
`NOT_APPLICABLE`-or-`UNKNOWN`).

Proven by `dv_harness_tests/test_shared_vip_sequencer_registry.py` (24 tests): a reuse-by-identity
proof against `shared_bus_resource_registry.py`'s own functions; the core `branch_b0`-vs-`branch_b1`
race (mismatched-lock and both-sides-no-lock variants); the positive control (a genuinely shared
named lock across three `branch_b*` bodies reports `CLEAR`); eight negative controls (no
declarations, a single-programmer resource, the same `branch_b` index declared twice correctly out
of scope, a `branch_a*`-only pair correctly out of scope, a non-canonical `task_group` name
correctly yielding `UNKNOWN` rather than a false `CLEAR`, missing evidence yielding `UNKNOWN`, a
real race still detected despite a third invalid declaration on the same construct,
duplicate-resource-id refusal); overall-status precedence across multiple entries; `lock_policy`
unit checks; connectivity-rows enrichment (present and absent); `resource_type` honesty; rendering;
and 3 real CLI subprocess invocations asserting exit codes 1/0/2. The sibling module's own 31-test
suite was re-run alongside it (55 passed combined, no regression). `python -m pytest
dv_harness_tests/test_shared_vip_sequencer_registry.py -q` -> `24 passed`.


<!-- S315: moved verbatim from CLAUDE.md original lines 19032-19071 (M4.6 CLAUDE Context Normalization) -->
## Pattern IR Assembly: branch_fw-vs-branch_a* Relative Launch-Timing Window (2026-09-07, audit-first extension)

`pattern_ir_assembly.py`'s `validate_layer_ordering()` was audited against its assigned item -- does
it catch a `branch_fw` launched only after `branch_a*` fully COMPLETES, rather than "immediately
after `branch_a*` starts" per `.claude/skills/CORE/pattern-architecture/SKILL.md` section 1 ("must
be launched before any branch that could possibly need it", USB illustration: "port 0 can attach and
need a responder while port 1's bring-up is still running", `common/soc_run.svh:118-124`).
**Confirmed real gap**: `FW_POLICY_AFTER_VIP` and the whole `declared_order` mechanism operate on a
single ORDINAL POSITION per layer in a flat 5-element list (`global`/`dut`/`fw_policy`/`vip`/
`check`). That representation can only ask "is `fw_policy` positioned before or after `vip`/
`global`/`check`" -- it has no way to represent a `branch_fw` launch STATEMENT sitting after a
*blocking* join on `branch_a*`'s own bring-up versus alongside `branch_a*`'s own non-blocking
dispatch. Both the correct shape and the buggy one read as the identical `dut` -> `fw_policy`
ordinal pair, so the existing check is structurally blind to this specific trap.

Closed additively, not by a new module. `validate_layer_ordering()` (and `assemble_pattern_ir()`,
via the same top-level-config fallback convention `vip_join_mode`/`declared_order` already use)
gained a new, optional, keyword-only `fw_launch_timing` parameter over a closed, CALLER-SUPPLIED-ONLY
vocabulary (`FW_TIMING_CONCURRENT_WITH_DUT_START` / `FW_TIMING_AFTER_DUT_COMPLETION` /
`FW_TIMING_UNKNOWN`) -- per the Evidence Truth Rule, this module has no evidence of its own about a
real command.txt's fork/join structure, so the check runs ONLY when a caller supplies that real
fact, never inferred from `declared_order`. `FW_TIMING_AFTER_DUT_COMPLETION` produces the new, cited
`FW_LAUNCHED_AFTER_DUT_COMPLETION` risk; `FW_TIMING_UNKNOWN` produces the honest
`FW_LAUNCH_TIMING_UNKNOWN` (never silently treated as safe); an unrecognized value is flagged
conservatively (`FW_LAUNCH_TIMING_UNRECOGNIZED_VALUE`) rather than ignored; and declaring a timing
fact alongside `branch_fw_present=False` is reported as an explicit contradiction
(`FW_LAUNCH_TIMING_CONTRADICTS_ABSENT_BRANCH_FW`) rather than one fact silently overriding the
other. Omitting the new keyword (every pre-existing caller) leaves the function's result
byte-for-byte unchanged -- proven by a dedicated backward-compatibility test, and confirmed safe by
a repo-wide grep showing no other module imports or calls `pattern_ir_assembly`'s functions.

Proven by `dv_harness_tests/test_pattern_ir_assembly.py` (28 tests, the original 20 untouched and
still passing, plus 8 new): the no-risk-when-omitted backward-compat case, the clean concurrent case,
the confirmed-buggy `AFTER_DUT_COMPLETION` case with its citation, the honest `UNKNOWN` case proven
distinct from the buggy finding, the unrecognized-value negative control, the
`branch_fw_present=False` contradiction negative control, a real combination with an independent
ordinal `FW_POLICY_AFTER_VIP` deviation proving the two checks are genuinely independent and neither
masks the other, and an end-to-end `assemble_pattern_ir()` test surfacing the new risk via top-level
config. `python -m pytest dv_harness_tests/test_pattern_ir_assembly.py -q` -> `28 passed`.


<!-- S316: moved verbatim from CLAUDE.md original lines 19072-19139 (M4.6 CLAUDE Context Normalization) -->
## PHY-Revision Re-Architect Trigger: a Real Diff/Versioning Mechanism Over phy_boundary.py's Stateless Decisions (2026-09-07)

`phy_boundary.extract_phy_boundary()`/`classify_boundary()` compute ONE PHY<->controller boundary/bind-
location decision per call -- stateless, per the module's own docstring. Nothing in this repo asked the
follow-up question a real bind/architecture decision needs answered LATER: has the PHY module's real
RTL changed since that decision was made, such that it needs re-evaluation.
`dv_harness/phy_revision_staleness.py` is that missing diff/versioning layer, built ON TOP of
`phy_boundary.py` rather than inside it -- `phy_boundary.py` is imported nowhere by this module and was
not edited, matching the precedent `phy_model_behavior_ir.py`/`dynamic_connectivity_ir.py`/
`architecture_choice_ranking.py` already set for extending that module's family without touching the
file itself.

**Three real primitives reused, never a fourth hasher or a second flagging mechanism.** (1) Which real
file(s) declare the PHY module is read off the same verible-parsed `dut_facts.rtl.files[]` shape
`phy_boundary.py` itself consumes (`file_path` + `modules[].name`) -- never a second RTL parse and
never a filename guess. (2) The content fingerprint reuses `env_manifest.file_ref()` (the same public
sha256-of-file primitive `dependency_supply_chain.py`/`coverage_db_integrity.py` already reuse),
combined via `connectivity_check.compute_rtl_fingerprint()`'s own scheme (sorted relative path + digest
folded into one sha256), scoped to only the file(s) that declare the PHY module rather than a project's
whole `rtl_sources` glob set. An empty or entirely-missing file set is honestly `NOT_AVAILABLE`, never
a vacuous constant fingerprint that would compare equal forever -- the identical anti-vacuous rule
`connectivity_check.run_connectivity_check()` already enforces. (3) Flagging an EXISTING decision as
needing re-evaluation reuses, for a `kind="architecture_decision"` Project Memory record, the real,
already-tested `memory.MemoryGC.flag_stale()` -- the same mechanism this project already uses for
"needing revalidation... it has aged past `knowledge_center.max_age_days`", applied here to a third real
trigger: the PHY module's own real RTL content moved. `MemoryStore` is constructed only when
`cross_project_mining.has_memory_store()` already confirms a real store exists -- never minted merely
by asking whether a decision needs re-evaluation.

**Two decision kinds, one record shape.** A `PhyRevisionDecisionRecord` (`build_phy_revision_decision_record()`,
persisted under `.dv-harness/phy_revision_decisions/<decision_id>.json`) carries the PHY module name, the
real declaring file(s), and the real fingerprint computed from those files AT decision time, plus a
caller-declared `decision_ref` naming what the decision actually is: `{"kind": "phy_boundary_bind", ...}`
for a stateless `phy_boundary.json` bind decision (a stale evaluation reports
`NEEDS_REVALIDATION_REPORTED_ONLY` naming the real re-extraction step -- this module never mutates that
generated document), or `{"kind": "architecture_decision", "memory_id": "..."}` for a real Project Memory
record (a stale evaluation calls `MemoryGC.flag_stale()` on that exact record -- the real, checkable
mutation).

**Four honest staleness statuses, never two collapsed into one.** `UP_TO_DATE` (recomputed now ==
recorded), `PHY_RTL_CHANGED` (a real, proven content difference), `PHY_SOURCE_FILES_UNAVAILABLE` (the
declared source file(s) could not be re-hashed right now -- moved, deleted; "we could not check" is
never silently read as "unchanged"), `RECORD_MISSING_FINGERPRINT` (a malformed/hand-edited record).
`needs_reevaluation` is False ONLY for `UP_TO_DATE` -- the same "an unresolved unknown outranks a clean
'not stale'" discipline `loop_stale_detection.py`/`intake_contract_stale_detection.py` already apply.

**Deliberately bounded, and stated rather than implied closed.** This module decides, approves and
arbitrates nothing beyond its own staleness evaluation and the one real `MemoryGC.flag_stale()` write it
may perform: no build, job, or approval is touched, and there is deliberately no `STAGE_GATES` entry. No
`dv-harness` CLI verb was added and `cli.py`/`gates.py`/`dashboard.py` were not touched, per this task's
own instruction -- the front door is `python -m dv_harness.phy_revision_staleness {fingerprint|record|evaluate|scan}`.

Proven by `dv_harness_tests/test_phy_revision_staleness.py` (38 tests, all real, re-verified against a
fresh run in this pass: `python -m pytest dv_harness_tests/test_phy_revision_staleness.py -q` ->
`38 passed`): real content-hash computation over real files, real change/missing-file detection
(including a negative control proving an unrelated file's edit never flips a PHY-module decision stale
-- the fingerprint stays correctly scoped to only the PHY module's own declaring file(s)), all three
RTL-input shapes (`env.manifest.json`, `dut_facts.rtl`, bare file list) accepted identically,
decision-record build/save/list/load round trips, the required negative control that a project with no
memory store never has one fabricated merely by asking whether a decision needs re-evaluation, a real
`MemoryGC.flag_stale()` mutation proven via a fresh `MemoryStore.get()` re-read (including the real
`stale_reason` citing the real fingerprint mismatch), a kind-mismatch guard proven to leave an unrelated
real memory record completely untouched, a batch scan across mixed decision kinds, and CLI subprocess
coverage for all four verbs across their documented exit codes. Regression re-run alongside it,
confirmed unaffected: `dv_harness_tests/test_cross_project_mining.py`,
`dv_harness_tests/test_env_manifest.py` (53 combined) and
`dv_harness_tests/test_memory_tier_integrity_and_admission.py` (36) -- 89 passed, 0 failed.


<!-- S317: moved verbatim from CLAUDE.md original lines 19140-19219 (M4.6 CLAUDE Context Normalization) -->
## VIP Configuration-Field Usage Coverage (2026-09-07)

`vip_capability_extraction.py`'s VIPConfigIR classifies WHICH VIP-indexed classes are shaped like
config objects, and carries each config class's own declared `config_fields` -- name/data_type/
file/line, taken straight from `vip_symbol_index.py`'s real declaration scan. It answers a purely
STATIC question: "is this class a config object, and how sure are we". It never asks whether any of
the individual FIELDS that class declares are ever actually touched anywhere in a real project's own
command.txt/pattern files -- confirmed a genuine gap by direct grep before writing anything
(`usage_coverage`/`field_usage`/`exercised`/`dead.*field` matched nothing in `dv_harness/`).

`dv_harness/vip_config_field_usage_coverage.py` closes exactly that, and builds no second VIP indexer
or command.txt parser: `vip_capability_extraction.IR_VIP_CONFIG` / `VIPCapabilityExtractionReport.
by_ir_type()` are the ONLY way this module ever obtains the config-class/field list (read-only, never
re-derived -- `config_records_from_capability_report()` for an in-memory report,
`config_records_from_capability_report_dict()` for a written `vip_capability_extraction.json`), and
`reference_pattern_audit.extract_command_statements()` is the ONLY way it ever reads a command.txt/
pattern file -- the same real, comment-aware, bracket-depth-tracking statement parser SYS-7's own
command-inventory machinery already uses.

**"EXERCISED" is real NAME-EVIDENCE, stated as narrowly as that.** A field is EXERCISED when its
literal declared name appears, as a whole identifier (word-boundary matched, so a field named `en` is
never mistaken for a hit inside `wr_en_field`), inside a real command STATEMENT's own comment-stripped
CODE text -- never inside that statement's trailing comment, since a comment mention is materially
weaker evidence than a real code reference. Exactly like `reference_pattern_audit.classify_wait()`'s
own `matched_tokens` classification, this is never a claim that the matched statement is the thing
that actually configures the field -- VIP config fields are usually set from SystemVerilog UVM code
this module never reads, not from command.txt, so a field this module marks DEAD_OR_UNUSED may still
be legitimately set elsewhere; this module's own scope is strictly "does the field's name appear
anywhere in the real command.txt/pattern set supplied".

**DEAD_OR_UNUSED is never asserted from silence.** A field is reported DEAD_OR_UNUSED only after this
module has REALLY scanned at least one real command.txt/pattern file and found no match -- the
report's own `command_files_scanned` count and each field's own `reason` text name exactly how many
real files were checked. Supplying zero config records, zero command files, or command files that all
fail to read (the real path does not exist, a real permission error, a real decode error -- named
per-file in `unreadable_command_files`, never silently swallowed) makes the WHOLE report
`NOT_AVAILABLE` with a real, distinct reason (`NO_VIP_CONFIG_IR_RECORDS_SUPPLIED` /
`NO_COMMAND_TXT_PATTERN_FILES_SUPPLIED` / `NO_COMMAND_TXT_PATTERN_FILE_COULD_BE_READ` /
`VIP_CONFIG_IR_RECORDS_DECLARE_NO_CONFIG_FIELDS`) -- never a report that quietly claims every field is
dead because nothing was actually checked. A single bad path among otherwise-good ones is recorded in
`unreadable_command_files` and never sinks the scan of the rest.

**Deliberately a different vocabulary from `vip_capability_extraction.py`'s own.** That module's
5-level qualification (PROJECT_PROVEN/VIP_DOCUMENTED/VIP_EXAMPLE_MATCHED/INFERRED_FROM_NAMING/UNKNOWN)
answers "how sure are we this CLASS really is a config object". This module's own, deliberately
separate 2-value vocabulary (EXERCISED/DEAD_OR_UNUSED) answers a completely different question about
each individual FIELD. A class can be PROJECT_PROVEN and still declare ten DEAD_OR_UNUSED fields; the
two vocabularies are never merged.

`dv-harness` was not wired -- `cli.py`/`gates.py`/`dashboard.py` were explicitly out of scope for this
batch. Front door: `python -m dv_harness.vip_config_field_usage_coverage --capability-report
<vip_capability_extraction.json> --command-file <f> [--command-file <f> ...] [--max-evidence N]
[--out-dir <dir>] [--json]` -- exit 0 every declared field EXERCISED, 1 a real DEAD_OR_UNUSED finding,
2 NOT_AVAILABLE/usage error.

**Deliberately bounded, and stated rather than implied closed.** (1) This is a NAME-EVIDENCE textual
scan over declaration-stripped statement CODE, never a semantic proof that the matched statement is
the thing that actually configures the field, and never a claim the field is unused elsewhere
(SystemVerilog UVM test code, a `.f` filelist macro define, or any source this module does not read).
(2) A generic/short field name (`id`, `en`, `mode`) can genuinely co-occur with an unrelated identifier
of the same name elsewhere in a command.txt -- this module reports the real match it found; it never
judges whether that match is semantically meaningful. (3) It decides nothing beyond reporting: no
build, no job, no approval, no stage gate.

Proven by `dv_harness_tests/test_vip_config_field_usage_coverage.py` (18 tests) against the REAL
synthetic VIP fixture `examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv` (the same fixture
`vip_capability_extraction`'s own tests use) classified through the real, unmodified
`vip_capability_extraction.extract_vip_capabilities()` pipeline: the required absence-of-evidence
negative controls (no config records, no command files, every command file unreadable, a bad path
among good ones, a class declaring zero config fields, a malformed record with no class_name raising
rather than silently guessing); real EXERCISED classification with a real file:line:detail citation and
the three unmentioned sibling fields correctly staying DEAD_OR_UNUSED with a cited reason; the word-
boundary negative controls (a substring occurrence inside a longer identifier on both sides is never
counted); the comment-only-mention negative control; evidence bounded by `max_evidence`; multiple
command files all scanned and correctly attributed; and reuse of a real on-disk
`vip_capability_extraction.json` via `config_records_from_capability_report_dict()`. Both real CLI
entry points are driven as real subprocesses across all three exit codes, including `--out-dir`
artifact writing. `python -m pytest dv_harness_tests/test_vip_config_field_usage_coverage.py
dv_harness_tests/test_vip_capability_extraction.py -q` -> `31 passed`.


<!-- S318: moved verbatim from CLAUDE.md original lines 19220-19302 (M4.6 CLAUDE Context Normalization) -->
## Cross-Environment VIP Version Drift Detection (2026-09-07)

`example_composition.check_vip_version_compatibility()` already compares VIP versions -- but ONLY
among the examples named in ONE composition request, i.e. within one scenario a caller is about to
assemble. It has no notion of a PROJECT that has already built several SEPARATE subsystem
environments over time, each with its own real, independently-scanned `env.manifest.json`
(`env_manifest.py`'s `vip_config.vip_release` layer -- a real `$DESIGNWARE_HOME` filesystem scan,
never a version typed into a document). Two subsystems can each look internally consistent --
subsystem A was built last month against `usb_svt/R-2019.06`, subsystem B was built this week
against `usb_svt/R-2020.12` -- and nothing in this repo ever compared the two. Confirmed a genuine
gap by direct search before writing anything: a repo-wide grep for `vip_version_drift`/
`version_drift` matched only `golden_scenario.py`'s own `_version_drift()`, a different, narrower
mechanism answering "has THIS ONE recorded golden capsule's own VIP versions moved since it was
verified" -- never a cross-subsystem comparison.

`dv_harness/vip_version_drift_detection.py` closes that gap, and invents no new VIP-version fact of
its own. It reuses `env_manifest.load_env_manifest()`/`EnvManifestValidationError` (the one real
reader+validator for an env.manifest.json document) and the already-real `vip_config.vip_release`
layer that document carries (`status`, `packages: [{name, version, install_path, ...}]`, built by
`env_manifest.build_vip_release()`/`scan_designware_home()`). Multi-subsystem discovery reuses
`environment_mode_router.read_registered_subsystem_entries()` -- the real runtime subsystem registry
(`.dv-harness/soc-composer/subsystem_environment_registry.json`, written only by `engine.py`'s
`_persist_subsystem_registry_entry()` on a real, gate-verified SIGNOFF PASS), whose entries already
carry each subsystem's own `environment_manifest` path -- never a second registry. A caller may
instead supply an explicit `{subsystem_name: manifest_path}` mapping, which REPLACES registry
discovery entirely (a real, distinct caller fact, never merged with it).

**"Same protocol's VIP" means the same real package directory name, never a guessed name
correlation.** `scan_designware_home()`'s own `name` field is a package's real, on-disk directory
name in `$DESIGNWARE_HOME` (e.g. `usb_svt`) -- a single protocol's VIP package by construction of how
`dw_vip_setup` lays out an install tree. This module groups packages ACROSS subsystems by that real,
normalised `name` -- never by inventing a correspondence between a package's directory name and a
`vip_config.vip_instances[].vip_type` UVM class name, a different naming domain entirely. Inventing
that correspondence would be exactly the "confident guess" the Evidence Truth Rule forbids, the same
discipline `arbitration_policy_ir.py`/`coherency_capability_ir.py`/`feature_enablement_matrix.py`
already apply: never infer identity from a name alone when two names live in different vocabularies
with no real, cited link between them.

**A shared package name reported by two or more DISTINCT subsystems whose real `version` values
disagree (exact string equality; `None` -- "no version directory" -- is itself a real, distinct
value, never treated as equal to a real version string) is a `VipVersionDriftFinding`**, citing every
subsystem's own real version and `install_path`. A package reported by only one subsystem has
nothing to compare against and is silently excluded -- that is not drift. This module never decides
which subsystem's version is "correct" -- the same ARBITRATION boundary every comparison-only module
in this codebase keeps.

**The Evidence Truth Rule, applied to the overall verdict, worst-wins.** `DRIFT_DETECTED` (a real
conflicting-version finding, reported regardless of how many OTHER subsystems could or could not be
checked) outranks `INCOMPLETE_EVIDENCE` (two or more subsystems WERE compared and agree, but at
least one OTHER declared subsystem's own `vip_release` layer could not be scanned at all -- kept
honestly distinct from a clean pass, since that unchecked subsystem might have drifted too) outranks
`NOT_AVAILABLE` (zero subsystems supplied, or fewer than two carry usable SCANNED evidence -- nothing
to compare) which is itself distinct from `NO_DRIFT` (every declared subsystem carries real SCANNED
evidence and no shared package disagrees). `assert_no_status_vocabulary_collision()` holds this
module's overall-status vocabulary disjoint from `dv_harness.models.Status` at import time.

**Deliberately bounded.** It discovers no subsystem of its own beyond the real registry (or an
explicit caller-declared manifest map); it never generates, builds, or runs anything; it never edits
an env.manifest.json; it decides, approves and arbitrates nothing -- there is deliberately no stage
gate. Per this task's own file-safety scope, `dv_harness/cli.py`, `dv_harness/gates.py` and
`dv_harness/dashboard.py` were not touched -- the front door is this module's own Python API plus
`python -m dv_harness.vip_version_drift_detection --root <dir> [--manifests name=path[,...]]
[--json]` (exit 0 NO_DRIFT, 1 DRIFT_DETECTED, 2 INCOMPLETE_EVIDENCE/NOT_AVAILABLE/usage error).

Proven by `dv_harness_tests/test_vip_version_drift_detection.py` (31 tests), every manifest built
through the real `env_manifest.generate_and_write()` over real synthetic `$DESIGNWARE_HOME` trees
(the same `dw_vip_setup`-shaped fixture layout `test_env_manifest_fact_sources.py`'s own
`fake_designware_home` fixture already establishes) -- never a hand-typed manifest dict. The required
negative control, `test_overall_status_incomplete_evidence_never_fabricates_no_drift`, proves the
module refuses to fabricate `NO_DRIFT` when a third declared subsystem's own manifest cannot be read,
even though the two comparable subsystems genuinely agree. Further coverage: a real conflicting-
version finding cited with both subsystems' real versions/install paths; a package used by only one
subsystem never flagged; a `None`-vs-real version treated as a genuine, cited conflict; a schema-
invalid or missing manifest reported `NOT_AVAILABLE` with the real reason (the manifest's own
`vip_config.vip_release.reason` carried through verbatim when the layer itself was never scanned);
real registry discovery (including two malformed registry entries correctly skipped) and the explicit-
manifest-override-replaces-registry proof; the vocabulary-collision guard's real detection power; and
five real CLI subprocess invocations covering all three exit codes plus `--json`/default-text output
and a malformed `--manifests` argument. `python -m pytest
dv_harness_tests/test_vip_version_drift_detection.py -q` -> `31 passed`. A full-repo
`pytest --collect-only` (12539 tests, zero errors) confirms no import-time collision was introduced
elsewhere in the suite.


<!-- S320: moved verbatim from CLAUDE.md original lines 19315-19413 (M4.6 CLAUDE Context Normalization) -->
## VIP Erratum/Known-Limitations Correlation (2026-09-06/07, vip_erratum_correlation)

No erratum/known-limitations parser or cross-reference existed anywhere in this repo before this
change -- confirmed by a repo-wide grep for `erratum`/`known.limitation`/`KnownLimitation` returning
zero hits outside this module. `vip_capability_extraction.py` classifies a VIP's own SOURCE
declarations into config/transaction/scenario/checker/coverage capability shapes; `vip_learning_gate.py`
composes four pre-generation VIP checkpoints (API provability, PHY boundary, bind tier, env-manifest
vip_config status). Neither reads a VIP DOCUMENT for a documented limitation, and neither asks whether
a project's own real usage of that VIP actually touches the affected feature.

`dv_harness/vip_erratum_correlation.py` closes this gap, reusing rather than reinventing on both
sides, mirroring the exact document-reuse pattern `phy_model_behavior_ir.py` already established for
its own PHY-spec-behaviour extraction one document family over:

- **The VIP document is never opened here as a raw PDF/text scan.** `vip_user_guide_distill.py` is
  this repo's ONE offline document distiller; this module consumes only the `.reference.json` record
  and the `.fulltext.txt` sidecar that distiller already produced (`load_reference_record()` / a
  supplied `reference_record` dict). There is one document-opening code path in this package, not two,
  keeping the Context Budget's "never loaded into runtime context" rule enforced structurally.
- **Project usage of a VIP feature is never re-discovered.** It is a caller-supplied, evidence-cited
  list of usage facts (`{id, kind, exercises_features, evidence}`) -- the same "accept an explicit
  caller-declared fact the real evidence store cannot supply, rather than invent one" discipline
  `ip_ownership_conflict.py`'s `legacy_bfm_declarations` and `existing_command_reuse_score.py`'s
  `existing_commands` already establish. `validate_usage_facts()` REFUSES construction
  (`VipErratumCorrelationError`) on any fact missing `id`, a non-empty `exercises_features` list, or a
  non-blank `evidence` citation -- an uncited "this pattern exercises feature X" claim is exactly the
  unsupported claim the Evidence Truth Rule forbids.

**What counts as an erratum entry, and why it cannot be a guess.** The scan is STRUCTURAL, not
semantic, the same discipline `phy_model_behavior_ir.py` already applies: a small, disclosed set of
section-marker keywords (`errata`, `known issue(s)`, `known limitation(s)`, `restriction(s)`,
`caveat(s)`, `workaround(s)`) decides which document SECTION a line sits in (reset at every
heading-like line, never left "sticky" across an unrelated section), and a line-shape scan (an
"ID: description" row, or a bulleted/numbered list item) decides which lines inside that section are
candidate entries. A document written with none of these conventions is honestly reported via
`NOT_AVAILABLE` naming whether no marker section was found at all or a marker section was found with no
recognizable item lines -- never guessed. Every entry carries the literal (possibly truncated) source
line plus a real `document + fulltext_path + line` citation.

**Affected-feature extraction is two-tier, and the weaker tier is labelled as weaker.** An entry's own
text sometimes states its affected feature explicitly ("... affects the LPM exit-latency logic.",
"This restriction applies to burst-mode transfers.", "... when using non-standard packet sizes.") -- a
small, fixed, literal phrase list (`_AFFECTS_PHRASE_RE` / `_WHEN_USING_RE` / `_IN_MODE_RE`) recognises
that form and extracts the feature verbatim, tagged `PHRASE_MATCH`. Absent an explicit phrase, many
real errata tables use the row's own ID/label column AS the feature/area name ("USB3 LPM: exit latency
may exceed spec ..."); this module falls back to that label ONLY when it does not itself look like a
bare issue-tracker id (`_looks_like_pure_id()` -- "ERR-042", "KI3", "Issue #12", "1.2.3", "Known Issue
5"), tagged `ID_LABEL_INFERRED` -- a disclosed, weaker tag, never conflated with an explicit statement.
An entry for which neither source yields a feature name is honestly `NOT_ANNOTATED`: this module never
invents one from the description's general prose, and `correlate_entry()` reports
`UNRESOLVABLE_NO_AFFECTED_FEATURE` for it regardless of how many usage facts were supplied -- the
required negative control proving the module refuses to fabricate an answer when evidence is absent.

**Correlation is literal, never semantic.** `correlate_entry()` matches an entry's own extracted
`affected_feature` against a usage fact's own declared `exercises_features` list by normalized
(lower-cased, alphanumeric-only) exact/substring comparison ONLY -- the same discipline
`dut_evidence_correlation.py`'s `_match_kind()` already applies one domain over. No fuzzy edit-distance,
no synonym table, no embedding.

**The four-status verdict**: `CORRELATED` (a supplied usage fact's own declared feature overlaps the
entry's affected feature, citing the real usage-fact evidence); `NOT_CORRELATED` (usage facts were
supplied and none matches -- a real negative, not an absence of evidence); `NOT_AVAILABLE` (no usage
facts were supplied at all -- "we could not check" is never collapsed into `NOT_CORRELATED`);
`UNRESOLVABLE_NO_AFFECTED_FEATURE` (the entry itself carries no extractable affected-feature name).

**Deliberately bounded, and stated rather than implied closed.** (1) It never mines a golden-reference
environment for erratum CONTENT -- every entry traces to a real document a caller distilled themselves.
(2) It never picks which usage fact is "the" reason a limitation is safe to ignore -- `CORRELATED`
only reports that a real declared usage overlaps the affected feature; whether that overlap is
actually a risk stays a human decision. (3) It is a regex line-scan, not a document-structure parser --
the same disclosed bound `interrupt_dma_clock_reset_extraction.py`/`error_recovery_flow_extraction.py`/
`timing_requirement_extraction.py` already state for themselves: an erratum row (and its
"affects"/"applies to" clause) must sit on ONE physical line of the extracted full-text; a row whose
real PDF extraction wrapped across multiple lines contributes only what its own single matched line
states, never a guessed join of the following continuation line. (4) It decides, approves and
arbitrates nothing beyond reporting: no build, job, or approval is touched, and there is deliberately
no stage gate. No `dv-harness` CLI verb was added -- `cli.py`/`gates.py` are out of this task's
file-safety scope, the same disclosed choice several sibling same-day modules in this codebase already
make; the front door is `python -m dv_harness.vip_erratum_correlation --reference-record <path>
[--usage-facts <file.json>] [--json]` (exit 0 every resolvable entry correlated, 1 at least one real
`NOT_CORRELATED` finding, 2 `NOT_AVAILABLE`/a malformed usage fact).

Proven by `dv_harness_tests/test_vip_erratum_correlation.py` (39 tests) against a synthetic errata-sheet
fixture (its own text states it is a test fixture describing no real vendor VIP) run through the real
`vip_user_guide_distill.distill_user_guide()` pipeline: vocabulary-collision guard against
`models.Status`; all four `NOT_AVAILABLE` absent/malformed-document paths; the two honest-absence
extraction states (no marker section at all vs. a marker section with no recognizable item lines); real
multi-entry extraction with real per-line citations and cross-section isolation (a Compliance-section
bullet never leaks into Known Limitations); all three affected-feature extraction paths plus the
pure-ID-label negative control and the non-ID label-inferred fallback, both proven against
`_looks_like_pure_id()` directly; every `validate_usage_facts()` refusal case plus propagation of that
refusal through `build_erratum_correlation()`; all four `correlate_entry()` verdicts including a genuine
no-overlap negative control; full-report composition proving one erratum `CORRELATED` and a sibling
`NOT_CORRELATED` in the same run, plus an all-`NOT_AVAILABLE` run when no usage facts are supplied at
all; and the CLI front door driven both in-process (all three exit codes, `--json` output) and as a real
`python -m` subprocess. `dv_harness_tests/test_phy_model_behavior_ir.py` and
`dv_harness_tests/test_dut_evidence_correlation.py` were re-run alongside it (81 tests combined) to
confirm no regression to either sibling module this one's design was drawn from.


<!-- S321: moved verbatim from CLAUDE.md original lines 19414-19485 (M4.6 CLAUDE Context Normalization) -->
## VIP Example Composition: Condition 8, DUT Topology Applicability (2026-09-07 gap-close)

`example_composition.py`'s original 7 conditions (VIP version, role, protocol mode, agent config,
sequencer ownership, reset assumptions, clock assumptions) all validate examples AGAINST EACH
OTHER. Confirmed by re-reading the module in full before writing anything: none of them ever asks
whether ONE example's own declared structure corresponds to anything in the project's REAL DUT
topology before that example is trusted as a compatibility reference at all. An example whose
declared bind target is a hallucinated/stale/wrong DUT instance path would pass all seven existing
conditions cleanly (nothing else in the example set disagrees with a fact nobody else mentions) and
be composed and trusted regardless.

**Condition 8, `DUT_TOPOLOGY_APPLICABLE`, closes exactly that gap, additively.** A new
alias-tolerant field, `dut_target_instance` (aliases include `target_instance` -- the exact
vocabulary `connectivity.py`'s own bind-entry contract already uses for this concept, per this
file's own Bind-Location Rules, reused rather than a second name for the same fact), is checked by
`check_dut_topology_applicability()` against a caller-supplied,
`design_architecture_ir.build_architecture_ir()`-shaped instance-tree document. Per this batch's
own file-safety/duck-typing convention, `example_composition.py` does not import
`design_architecture_ir.py` itself -- it only consumes the real dict SHAPE that module's own
`build_architecture_ir()` produces, exactly the same duck-typed-input discipline the rest of this
file already commits to.

**A real, longest-contiguous-suffix match, never a whole-path assumption and never a fabricated
match.** A testbench-level declared path commonly carries a leading TB-top prefix the DUT-only
topology never parsed (`tb_top.dut_wrapper.chip.core.usb0`), so the check finds the longest tail of
the declared path that exactly equals a real, contiguous chain of instance names anywhere in the
tree, rather than requiring the whole path to match from an assumed root. A declared path with two
or more segments requires a real match of at least 2 segments -- a single coincidental common
instance name (`core`, `if`, `clk`) can never manufacture a false CLEAR on its own; a
single-segment declared path needs only that one real match. Zero real match at all is the finding
this condition exists to catch, reported per-example (never a pair, since this is inherently a
single-example check against external evidence, not a comparison between two examples) via a new
`_single_entry()` helper that keeps `format_composition_report()`'s existing `conflict['pair']`
rendering working unmodified for all 8 conditions. Absent a real, successfully-BUILT topology
document, the condition is honestly `COND_STATUS_NOT_APPLICABLE` -- an example's DUT-target
structure was simply never checked, never assumed clean by omission, matching the Evidence Truth
Rule.

**Wired additively, every pre-existing caller unaffected.** `COND_DUT_TOPOLOGY_APPLICABILITY` was
appended to `CONDITIONS`/`CONDITION_CHECKS`/`CONDITION_DESCRIPTIONS`, so
`assert_conditions_complete()` still holds all three sets total (now 8/8/8).
`evaluate_vip_example_composition()` gained an optional `dut_topology: Optional[Any] = None`
keyword -- every pre-existing call site that supplies no second argument is byte-for-byte
unaffected, and condition 8 simply reports its own honest `NOT_APPLICABLE` for them, exactly as the
existing `test_clean_compatible_pair_composes()` (which iterates `report["conditions"].values()`
asserting `conflicts == []` for every condition, including this new one) already proves.
`execute_verb()`/`main()` gained an optional `--dut-topology <file.json>` CLI flag. `cli.py` was
**not** touched (out of this batch's own file-safety scope): its own pre-existing
`dv-harness example-composition` subcommand (wired by a separate, concurrently-running workflow)
still calls the same `main()` unchanged and keeps working -- it simply does not yet forward
`--dut-topology`, a disclosed residual for whichever pass next has `cli.py` in scope.

**Deliberately bounded, and stated rather than implied closed.** This condition validates
STRUCTURAL presence only -- a real chain of instance names actually appearing somewhere in the
project's own parsed DUT RTL -- never protocol behavior, never whether the VIP interface bound at
that instance is semantically correct for the claimed role. It builds no VIP API, no RTL content,
and runs no build/verible/simulation itself; the topology document must already be built and
supplied by the caller, matching every other duck-typed-input convention this module already
follows.

Proven by 13 new tests appended to `dv_harness_tests/test_example_composition.py` (37 total, the
original 26 untouched and still passing): NOT_APPLICABLE with no topology supplied and with a
topology supplied but no example declaring a target; CLEAR on a real full-path match and on a
path carrying a TB-only prefix (the suffix-match proof); BLOCKED naming the exact example on a
fabricated path; the required negative control that a lone coincidental single-segment match is
never treated as evidence for a 2+-segment declared path; a single-segment declared path needing
only one real match; an honestly `NOT_APPLICABLE` result when the supplied topology's own `status`
is not `"BUILT"`; and two real CLI subprocess invocations exercising `--dut-topology` to both a
real BLOCKED (exit 1) and a real CLEAR/COMPOSED (exit 0) outcome. `python -m pytest
dv_harness_tests/test_example_composition.py -q` -> `37 passed`.



<!-- S323: moved verbatim from CLAUDE.md original lines 19562-19664 (M4.6 CLAUDE Context Normalization) -->
## Register Reset-Value Correlation: register_excel_extract.py vs register_rtl_trace.py (2026-09-07)

Cross-checks a register/field's DOCUMENTED reset VALUE (`register_excel_extract.py`'s transcribed
spreadsheet `reset_value`) against REAL RTL reset logic (a literal assignment inside a real
`always`/`always_ff` block's own reset-testing `if`-branch), reusing `register_rtl_trace.py` to
decide which real RTL site a register/field's name resolves to. A repo-wide grep for
`register_reset_value_correlation`/`RegisterResetCorrelation`/`reset_value_correlation` matched
nothing executable before this change -- both source modules exist and are heavily used elsewhere
in this repo, but nothing joined them on this specific axis. `dut_evidence_correlation.py`, the
nearest-looking mechanism, was read in full and confirmed to answer a DIFFERENT question: it
compares a caller-DECLARED "expected" `reset_value` against `env_manifest.py`'s register-map layer
(a hand-authored/transcribed document), never against real RTL reset-branch logic at all.

**REUSE OVER REINVENT, on both halves.** `register_rtl_trace.trace_register_field()` /
`parse_rtl_sources()` / `collect_rtl_sites()` are called directly, unmodified, to decide whether a
real, unambiguous RTL site exists for a register/field's name -- this module never re-derives that
existence/ambiguity decision, and only a real `TRACE_CONFIRMED` result (one exact, referenced site)
is ever handed to the reset-value scan; `TRACE_PARTIAL`/`TRACE_NOT_FOUND`/`BLOCKED` are reported
straight through as `UNKNOWN`, citing `register_rtl_trace.py`'s own reason text.
`verible_parser.run_export_json()`/`find_all_nonoverlapping()`/`node_span()` are the SAME real
verible front end + module-span primitives `design_architecture_ir.py`'s own FSM literal scan
already uses -- there is no second SystemVerilog parser in this package. This module needed the
raw module TEXT to scan for a reset-branch assignment, which neither `register_rtl_trace.RtlSite`
nor `verible_parser.ModuleInfo` ever carries (confirmed by reading both: no source line, no span,
anywhere upstream -- `dut_evidence_correlation.py`'s own docstring already states this same absence
for register/field entries), so it independently re-derives `design_architecture_ir.
parse_rtl_file()`'s small "verible-parsed module -> its own source span -> module_text" primitive
(the same "re-derive a small primitive rather than import a sibling module's private shape"
discipline several modules in this repo already follow) rather than importing that module wholesale
for an unrelated FSM-extraction feature.

**The parser-vs-elaboration boundary, restated because it drives every status this module can
report**, exactly as `register_rtl_trace.py`'s own module docstring already states it for its own
ceiling: a literal reset-branch scan can prove that SOURCE TEXT assigns a signal a specific literal
value inside what looks like a reset-testing `if`; it can never prove that assignment actually
executes as the design's real reset value (a `generate`/`` `ifdef `` condition is never evaluated,
a parameter reference is never resolved, no clock edge is ever simulated). `MATCH`/`MISMATCH` is
this module's honest reading of two DOCUMENTED/DECLARED facts against each other, never a claim
about verified silicon behavior.

**MATCH / MISMATCH / UNKNOWN, honestly, per register (and per field).** `MATCH`: the RTL trace is
`TRACE_CONFIRMED` for exactly one site, this module's own reset-branch literal scan of that site's
own module resolves to exactly one unambiguous literal value, the spreadsheet documents a reset
value, and the two integers agree. `MISMATCH`: all of the above resolved, and the two integers
DISAGREE -- this module reports the disagreement and never decides which side is right (the same
ARBITRATION boundary `dut_evidence_correlation.py`'s own docstring keeps for a
`RTL_CONTRADICTS_SPEC` finding -- Source Authority Order stays a separate, untouched mechanism).
`UNKNOWN`: any one of the four real facts this comparison needs (a documented reset value, a
`TRACE_CONFIRMED` RTL site, a real module source span for that site, an unambiguous literal
reset-branch assignment inside it) is missing, ambiguous, unparseable, or could not be determined --
including the case where the RTL trace itself could not be ATTEMPTED at all
(`register_rtl_trace.py`'s own `BLOCKED`). Every `UNKNOWN` carries the real, specific reason (plus
finer-grained `trace_status`/`rtl_finding` sub-fields) -- never a shared "unknown" a reader would
have to guess the cause of.

**The reset-branch literal scan is a bounded regex line-scan, never a compiler.** It is scoped
strictly to ONE sequential `always`/`always_ff` block's own window (between it and the next always
header, or the module's end) and, inside that, to the block's own FIRST `if` that tests a
reset-named signal (the identical "the block's own first real conditional" convention
`interrupt_dma_clock_reset_extraction.py` already uses for reset-polarity detection) -- its THEN
body, depth-tracked over `begin`/`end` (or, absent a `begin`, the single statement up to its own
`;`). A `generate`/`` `ifdef ``-guarded assignment is scanned exactly as written; an X/Z/`?`-valued
literal (`'bx`, `'hz`), a non-literal RHS (an expression, a parameter reference, a macro), or a
reset branch this scan cannot close all report `UNKNOWN` (`UNPARSEABLE`/unresolved) rather than a
guessed integer. A reset-branch assignment appearing in MORE THAN ONE always block for the same
target signal, disagreeing on the literal value, is `UNKNOWN` naming the ambiguity -- never
resolved by picking the first one found. Verilog literal parsing (`parse_verilog_literal()`)
handles sized literals (`8'h00`, `1'b0`, `32'd10`, underscore-grouped), `0x`-prefixed hex, and
plain decimal -- never a guess for anything outside that grammar.

No `dv-harness` CLI verb was added -- `cli.py`/`gates.py` were NOT touched, per this batch's
file-safety scope (out-of-scope, several concurrent agents editing those files); the front door is
a standalone `python -m dv_harness.register_reset_value_correlation`, the identical disclosed
choice `register_excel_extract.py` and `register_rtl_trace.py` themselves already make. Front door:
`python -m dv_harness.register_reset_value_correlation --register-source <xlsx_or_csv> --rtl <f>
[--rtl <f> ...] [--verible-bin BIN] [--json]` (exit 0 clean, 1 a real MISMATCH, 2 the register
source could not be read/extracted).

Proven by `dv_harness_tests/test_register_reset_value_correlation.py` (41 tests): pure-function
tests for `parse_verilog_literal()` (every recognized literal shape, plus X/Z-bit and
expression/parameter-reference refusal) and for `find_rtl_reset_assignments()`/
`resolve_rtl_reset_value()` (async reset, sync reset, single-statement reset, no-reset-branch,
X-bit `UNPARSEABLE`, two-always-blocks `AMBIGUOUS`, and a direct proof the window bound between
consecutive always blocks prevents cross-block leakage); pure tests for `compare_reset_values()`
covering `MATCH`/`MISMATCH` and every `UNKNOWN` branch. End-to-end tests build a REAL openpyxl
`.xlsx` register-map spreadsheet plus REAL synthetic RTL and drive the real
`verible-verilog-syntax` subprocess: a register whose documented and RTL values agree (`MATCH`),
one that disagrees (`MISMATCH`), one with no documented reset value (`UNKNOWN`), one with no
matching RTL signal anywhere (`UNKNOWN`, `TRACE_NOT_FOUND`), a cross-module ambiguous-name case
(`UNKNOWN`, `TRACE_PARTIAL`), and register FIELDS correlated alongside their parent register. The
REQUIRED negative control (`test_no_rtl_paths_at_all_reports_unknown_never_a_fabricated_match`)
proves that supplying zero RTL paths makes `register_rtl_trace.py` report `BLOCKED` for every
register with a documented value, and this module reports every one of them `UNKNOWN` rather than
fabricating a `MATCH`/`MISMATCH` from absent evidence. `module_source_spans()`/
`build_module_span_index()` failure paths (missing file, a real verible syntax error, an unrunnable
verible binary) each report an honest error and empty span list rather than a silent partial
result. Both the Python API and the real CLI subprocess (all three documented exit codes) are
driven end to end. The two reused modules' own regression suites
(`dv_harness_tests/test_register_excel_extract.py`, `dv_harness_tests/test_register_rtl_trace.py`,
73 tests) were re-run and pass unchanged, confirming this module only imports them and edits
neither. Ran `python -m pytest dv_harness_tests/test_register_reset_value_correlation.py -q` ->
41 passed.


<!-- S332: moved verbatim from CLAUDE.md original lines 20069-20166 (M4.6 CLAUDE Context Normalization) -->
## Holistic Clock/Reset/Power Consistency: the Chosen Bind Set as ONE WHOLE, Not Pairwise (2026-09-07)

Every existing clock/reset/power consistency check in this codebase evaluates ONE record at a time.
`connectivity.py`'s Bind-Location Rule 3 (clock/reset through the bind's own port list, never an XMR)
is reviewed per bind statement. `verification_architecture.AssertionIR.clock_domain_match`/
`reset_domain_match` compares ONE assertion candidate's own declared clock/reset domain against
`env_manifest.build_dut_facts_clock_reset()`'s map. `power_intent.analyze_power_intent()` checks the
UPF model against ITSELF (a switchable domain has an isolation strategy, a supply reference resolves)
with no notion of which RTL instances a chosen environment's own binds actually observe. None of them
ever asks whether the FULL set of binds a chosen environment architecture mounts is collectively
consistent with the DUT's clock/reset dependency structure and power-domain topology taken as one
whole. `dv_harness/holistic_clock_reset_power_consistency.py` is that missing whole-set check.

**No `clock_reset_dependency_graph.py` module exists anywhere in this repo** (confirmed by grep before
writing a line of this file). The real evidence shape with that content is `env_manifest.
build_dut_facts_clock_reset()`'s dict -- also produced identically by `interrupt_dma_clock_reset_
extraction.py`'s `clock_reset_extension` block -- which already models the dependency this module needs
AS a graph without ever being a class: each reset entry carries a `clock` field naming the clock it
synchronises to and a `clock_resolved` verdict (RESOLVED / UNKNOWN_CLOCK / NOT_SPECIFIED). This module
reads that dict verbatim (caller-supplied, never re-parsed) and treats it as a real dependency graph:
clocks are nodes, and every `clock_resolved == "RESOLVED"` reset is a real edge to its clock.
`power_intent.py` is imported directly and used for real: the real `PowerIntent.domains` (each carrying
its real `-elements` RTL scope paths), the real, already-tested `PowerIntent.switchable_domains()`
method, and the real `.isolation`/`.retention` lists `analyze_power_intent()` itself reads -- a caller
must hand this module the actual object `power_intent.extract_power_intent()` produces, type-checked
and refused if it is a hand-shaped dict instead. Per-bind clock/reset PORT identification reuses
`connectivity.find_amba_clock_reset_ports()` verbatim -- the same real, tokenizing tiered resolver
AMBA-15 built for one interface bundle, applied here to a bind entry's own `ports` list (the same
3-field shape `bind_mechanism_generator.validate_bind_entries()` already consumes). This module derives
no SERIAL/PARALLEL/MIXED verdict of its own and re-implements no switchable/isolation logic -- both
stay `power_intent.py`'s own job.

**What "collectively consistent" means, concretely and genuinely whole-set rather than pairwise.**
Every declared power domain carrying at least one bound RTL instance (matched by real `-elements`
scope-path containment, NEVER by name alone, and never inferred for a domain declared only with
`-include_scope` and no explicit `-elements` -- this module does not track UPF's own `set_scope`
nesting, and asserting broad coverage from an absent element list would be exactly the unearned claim
the Evidence Truth Rule forbids) is checked as one GROUP: if the domain is switchable (a real power
switch drives it, via the real `switchable_domains()` method) and carries no non-`no_isolation`
isolation strategy, every bind mounted inside it is flagged TOGETHER in one finding naming the whole
group -- a fact only visible once the whole membership is known, never from one bind alone. The group's
own set of topology-resolved reset names is compared as a SET: more than one distinct declared reset
name observed across one physical power domain's own bind membership is reported. Every clock the
DUT's own topology declares is checked against the WHOLE bind set (directly referenced, or reached
through a dependent reset via the reset->clock graph edge) for whether ANY bind in the chosen
architecture exercises it at all. A bind whose structurally-identified reset resolves to a real
declared reset the topology itself could not tie to a clock is flagged, connecting a whole-topology
fact (the document's own unresolved dependency) to a specific chosen bind.

**Evidence Truth Rule, proven by a dedicated negative control.** With neither `clock_reset_facts` nor a
real `PowerIntent` supplied, every evidence-dependent finding code
(`POWER_DOMAIN_RESET_SET_INCONSISTENT`, `SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION`,
`BIND_TARGET_NOT_IN_ANY_DECLARED_POWER_DOMAIN`, `CLOCK_DOMAIN_NOT_EXERCISED_BY_ANY_BIND`,
`RESET_CLOCK_UNRESOLVED_REFERENCED_BY_BIND`, `BIND_PORT_NOT_IN_DECLARED_CLOCK_RESET_TOPOLOGY`) is
proven absent from the report -- only the bind's-own-port-list structural check (Bind-Location Rule 3
risk: no structurally-recognisable clock/reset port in this bind's own ports) still runs, since it
needs no topology at all. The report always states `clock_reset_topology_available`/
`power_intent_available` explicitly rather than leaving absence to be inferred.

**What this module does not do.** It emits no `bind` statement, decides no bind target, and authors no
RTL/UPF content. It never re-parses UPF (stays `power_intent.py`'s job) and never re-derives clock/
reset facts from RTL (stays `env_manifest.py`'s/`interrupt_dma_clock_reset_extraction.py`'s job). It
ARBITRATES nothing -- a domain with genuinely different reset networks feeding different sub-blocks is
a real, legitimate design, and this module reports the fact for a human to judge, never resolves it.
There is deliberately no stage gate: no build, job, or approval is touched.

No `dv-harness` CLI verb was added and `cli.py`/`gates.py`/`dashboard.py`/`question_queue.py` were not
touched, per this batch's own file-safety scope -- the front door is `python -m
dv_harness.holistic_clock_reset_power_consistency --bind-entries <file.json> [--clock-reset-facts
<file.json>] [--upf <f> [<f> ...]] [--json]` (exit 0 CONSISTENT, 1 INCONSISTENCIES_FOUND, 2
NOT_AVAILABLE/usage error), sharing one `execute_verb()`/`main()`.

Proven by `dv_harness_tests/test_holistic_clock_reset_power_consistency.py` (29 tests, re-verified
fresh in this pass: `python -m pytest dv_harness_tests/test_holistic_clock_reset_power_consistency.py -q`
-> `29 passed`) against real evidence throughout: the repo's own real synthetic UPF fixture
(`dv_harness_tests/fixtures/power_intent/synthetic_lp_soc.upf`, explicitly labelled a test fixture, not
any real DUT's power intent) parsed by the real `power_intent.extract_power_intent()`, small inline
synthetic UPF text built the same documented way for a switchable-domain-without-isolation case, and
plain dicts in the real `env_manifest.build_dut_facts_clock_reset()` shape. The headline required
negative control (`test_no_topology_evidence_never_fabricates_topology_or_power_findings`) is described
above; further negative controls prove a single reset name within one domain group never flags, a
domain with zero bind members produces no group finding, an `-include_scope`-only domain (the real
fixture's own `PD_TOP`) is never matched to any instance, `PowerIntent()` with no domains declared
never flags membership, and a malformed or non-dict bind entry is skipped and reported rather than
crashing the whole report. Reuse is proven directly: a bind referencing only a reset (no recognisable
clock port) still counts as exercising that reset's own clock via the dependency-graph edge; a
switchable-but-isolated domain (the real fixture's `PD_PERIPH`) never flags
`SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION`; a switchable-and-unisolated synthetic domain with two bind
members produces exactly ONE finding naming both, never one per bind. The CLI is driven as real
subprocesses across all three exit codes, including a full `--upf`+`--clock-reset-facts` end-to-end
run. `python -m pytest dv_harness_tests/test_connectivity.py dv_harness_tests/test_power_intent.py -q`
(276 tests) was re-run alongside it with zero regressions, and a full-repo `pytest --collect-only`
(12808 tests) confirms no import-time collision was introduced elsewhere in the suite.

**Disclosed residual.** This is REACHED, not WIRED: no `run_stage()`/`advance()` call site invokes it
and no graph node declares it -- a caller (a human, a future generation-readiness row, a dashboard
card) invokes it directly, or via the standalone CLI, over a real chosen bind set it already has.


<!-- S338: moved verbatim from CLAUDE.md original lines 20553-20660 (M4.6 CLAUDE Context Normalization) -->
## Clock/Reset Dependency Graph: a Standalone Queryable Object, Closing the Open Item (2026-09-07)

CLAUDE.md's own "Open Item: Clock/Reset Dependency Graph (incl. multi-die/partition topology)"
section recorded this as genuinely open: no module named `clock_reset_dependency_graph` (or any
close variant) existed anywhere in this repository, confirmed by grep before this file was written
-- independently re-confirmed by `dv_harness/holistic_clock_reset_power_consistency.py`'s own module
docstring, which states outright ("checked by grep before writing a line of this file") that the
nearest real evidence shapes are `env_manifest.build_dut_facts_clock_reset()` and
`interrupt_dma_clock_reset_extraction.py`'s `clock_reset_extension` block -- both already model a
per-clock/per-reset DEPENDENCY (each reset carries a `clock` field and a `clock_resolved`
RESOLVED/UNKNOWN_CLOCK/NOT_SPECIFIED verdict) but neither exposes it as a queryable GRAPH object, and
neither models MULTI-DIE or PARTITION topology at all. `holistic_clock_reset_power_consistency.py`
reads the same dict and treats it as a graph for its own narrower whole-bind-set-consistency
purpose, but carries no multi-die/partition concept and is explicitly not a general-purpose
dependency-graph module.

`dv_harness/clock_reset_dependency_graph.py` is that missing module, and it reuses that same real
evidence shape verbatim -- never re-parsing RTL or UPF itself, and never re-deriving the two real
dependency-graph consumers' own logic. `build_clock_reset_dependency_graph()` builds a
`ClockResetDependencyGraph` from three independent, caller-supplied inputs, each with its own
honest-absence story:

- **`clock_reset_facts`** -- a real `env_manifest.build_dut_facts_clock_reset()`-shaped dict (or the
  identically-shaped `interrupt_dma_clock_reset_extraction.py` `clock_reset_extension` block, proven
  interchangeable by a dedicated test), read verbatim. Clocks become `CLOCK` nodes, resets become
  `RESET` nodes, and every `clock_resolved == "RESOLVED"` reset gets a real `SYNCHRONIZES_TO` edge to
  its clock -- exactly `holistic_clock_reset_power_consistency.py`'s own reused pattern. Absent,
  malformed, or non-`"LOADED"`-status input makes `clock_reset_topology_available` False with a real,
  distinct reason; the graph still builds with zero clock/reset nodes, never silently treated as "no
  dependencies exist".
- **`power_intent`** -- the NEW power-domain axis: a real, type-checked `power_intent.PowerIntent`
  object (`power_intent.extract_power_intent()`'s own output; a hand-shaped dict is refused outright
  with `ClockResetDependencyGraphError`, mirroring `holistic_clock_reset_power_consistency.py`'s
  identical refusal for the identical reason). Its real `.domains` become `POWER_DOMAIN` nodes and its
  real, already-tested `.switchable_domains()` method decides each domain's `switchable` flag -- no
  UPF parsing is re-derived here. An optional, entirely caller-declared `domain_power_scope` dict
  (`{domain_name: [clock/reset node ids it powers]}`) adds real `POWERS` edges; a reference to an
  unknown domain or node is reported in `findings`, never silently dropped and never fabricated.
- **`partition_assignment`** -- the genuinely NEW multi-die/partition dimension this task named: a
  plain, optional dict the caller supplies mapping a node id to a partition/die id string, NEVER
  inferred (nothing in this repository currently extracts per-die/per-partition facts from RTL, so
  inventing one here would be exactly the fabrication the Evidence Truth Rule forbids). Absent it,
  every cross-partition query returns the honest, distinct `NO_PARTITION_DATA_AVAILABLE` status --
  proven by the headline negative control: a graph carrying real, resolved clock/reset dependencies
  but zero partition data must report that status, never an empty-but-clean `cross_partition_findings`
  list, which would read as "checked, found none" when in fact nothing was ever checked. With real
  partition data supplied, `cross_partition_dependencies()` and the concretely-named
  `resets_in_partition_depending_on_clock_in_partition()` report every real `SYNCHRONIZES_TO` edge
  whose two endpoints sit in genuinely different declared partitions -- a real, new finding a flat,
  partition-blind graph cannot surface -- while an edge touching a node this assignment never mentions
  is reported under `edges_with_unknown_partition`, never silently dropped and never counted as either
  same-partition or cross-partition.

**Real query methods, per the task's own required list.** `resets_depending_on_clock(clock_name)`;
`clock_for_reset(reset_name)` (returns a real, honest status -- RESOLVED/UNKNOWN_CLOCK/NOT_SPECIFIED/
RESET_NOT_FOUND -- and never fabricates a clock name for an unresolved dependency); `traverse(node_id,
direction)` (a real BFS over the graph's own edges, forward or backward, returning an empty list --
never an error -- for a node this graph never built); and `unresolved_dependency_report()`, which
applies the Evidence Truth Rule's "never collapse two different kinds of absence into one answer" one
level down: UNKNOWN_CLOCK (the topology names a clock that does not exist) and NOT_SPECIFIED (no clock
was ever declared) are kept in two separate lists, never merged into one generic "unresolved" bucket,
and a reset whose recorded `clock_resolved` value is neither of the three known ones is surfaced under
`other_unrecognized_status` rather than silently dropped.

**Declaration-level graph wrapper, never an elaborator**, stated explicitly in the module's own
docstring per house rule 5: it parses no RTL and no UPF itself, evaluates no `generate`/`` `ifdef ``
condition, runs no simulation, and proves no formal property -- every fact it graphs was already
produced by `env_manifest.py`, `interrupt_dma_clock_reset_extraction.py`, or `power_intent.py`. It
emits no `bind` statement, authors no RTL/UPF content, and arbitrates nothing it finds (a real
cross-partition dependency is reported for a human to judge, never resolved). There is deliberately no
stage gate: no build, job, or approval is touched anywhere in this file. No `dv-harness` CLI verb was
added and `cli.py`/`gates.py`/`dashboard.py` were not touched, per this project's own house rule
against editing those files while under concurrent edit pressure -- the front door is a standalone
`python -m dv_harness.clock_reset_dependency_graph --clock-reset-facts <file.json> [--upf <f> [<f>
...]] [--partition-assignment <file.json>] [--domain-power-scope <file.json>] [--json]` (exit 0 the
clock/reset topology axis was loaded, 2 `NOT_AVAILABLE`/usage error).

Proven by `dv_harness_tests/test_clock_reset_dependency_graph.py` (38 tests,
`python -m pytest dv_harness_tests/test_clock_reset_dependency_graph.py -q` -> `38 passed`): the
required negative controls for all three independent honest-absence stories (no clock/reset facts, a
malformed type, a non-`LOADED` status, no power intent, a hand-shaped power-intent dict refused, no
partition data with the headline never-fabricated-empty-cross-partition-list proof); real node/edge
construction from both real producer shapes (`env_manifest.py`'s and
`interrupt_dma_clock_reset_extraction.py`'s identically-shaped dict); real power-domain nodes built
from the repo's own real synthetic UPF fixture (`dv_harness_tests/fixtures/power_intent/
synthetic_lp_soc.upf`) parsed by the real `power_intent.extract_power_intent()`, including a real
proof that `PD_PERIPH` is switchable (a real power switch drives it) and `PD_TOP` is not; every query
method exercised on its positive path and its honest-absence path; the unresolved-dependency report's
three-way split (`unknown_clock`/`not_specified`/`other_unrecognized_status`, never merged); the
partition-topology suite's own required negative control plus a real, concrete cross-die finding, the
symmetric-query proof that the converse direction genuinely finds nothing (never a fabricated symmetric
result), the edge-touching-a-partition-unknown-node case, and the distinction between
`partition_assignment=None` (not supplied) and an explicitly-supplied empty dict (supplied, but
uninformative); JSON round-tripping and markdown rendering on both an empty and a fully-populated
graph; and the real CLI driven as subprocesses across its documented exit codes, including a full
`--upf`+`--partition-assignment` end-to-end run. `python -m pytest
dv_harness_tests/test_holistic_clock_reset_power_consistency.py dv_harness_tests/test_power_intent.py
dv_harness_tests/test_env_manifest.py dv_harness_tests/test_interrupt_dma_clock_reset_extraction.py -q`
(113 tests) was re-run alongside it with zero regressions, and a full-repo `pytest --collect-only`
(13366 tests) confirms no import-time collision was introduced elsewhere in the suite.

**Disclosed residual.** This closes the item's own stated real gap -- a standalone, queryable
clock<->reset dependency graph with nodes for clocks/resets/power domains and an added multi-die/
partition-topology dimension. It is REACHED, not WIRED: no `run_stage()`/`advance()` call site
invokes it and no graph node declares it -- a caller (a human, a future generation-readiness row, a
dashboard card) invokes it directly, or via the standalone CLI, over real clock/reset facts, a real
`PowerIntent` object, and (optionally) a real caller-declared partition assignment it already has.


<!-- S339: moved verbatim from CLAUDE.md original lines 20661-20728 (M4.6 CLAUDE Context Normalization) -->
## Legal Parameter-Combination Extraction from RTL (2026-09-07, legal_param_combination_extraction) -- CLOSES the prior open item

**Closes** "Open Item: Legal Parameter-Combination Extraction from RTL (2026-09-07, dut_discovery)"
above: that note's own gap -- a parser-level scanner proving which COMBINATIONS of two-or-more RTL
parameters the source text itself states are legal/illegal -- is now real,
`dv_harness/legal_param_combination_extraction.py`.

**Reuse, checked first.** `param_define_extraction.py` extracts each parameter's own declared default
ONE AT A TIME and has no notion of a combination; this module does not duplicate it, but reuses its
same real front end, `verible_parser.py` (`run_export_json`/`find_all_nonoverlapping`/`node_span`/
`extract_modules`, the identical public aliases `design_architecture_ir.py`'s own `parse_rtl_file()`
already established as the supported cross-module reuse contract), to get each module's REAL declared
parameter names and REAL module-text span -- never a second SystemVerilog parser. `config_variant_
coverage.py` generates a covering plan over a CALLER-DECLARED space and derives no legality from RTL
at all; not touched, not duplicated. The comment/string-literal blanking discipline (length/newline-
preserving, offsets stay aligned) is the same technique `design_architecture_ir.py`'s FSM scan and
`param_define_extraction.py`'s `` `define `` scan already use, independently re-implemented here at a
few lines per this codebase's own established per-module convention.

**What it recognizes, real and bounded.** Two construct shapes, both scanned by one shared
`_scan_if_chain()`: (a) `GENERATE_IF_COMBINATION_GUARD` -- a `generate` block whose first real token
(optionally through one `begin`) is an `if`/`else if`/`else` chain; (b) `ELABORATION_ERROR_
COMBINATION_GUARD` -- an `initial` block shaped identically. Only a branch whose condition references
TWO OR MORE of the module's own real declared parameter names (cross-checked against the real
`ParamInfo.name` list, never guessed from spelling or case) becomes a site: a branch with no
`$error`/`$fatal` in its body is `LEGAL_COMBINATION_PROVEN`; a branch whose body calls `$error`/
`$fatal` is `ILLEGAL_COMBINATION_PROVEN`. A trailing bare `else` (no condition of its own) is never
turned into a site of its own, even carrying `$error` -- naming which combination it covers would
require synthesizing the negation of every prior condition, which this parser-level scan will not do
(the Evidence Truth Rule forbids fabricating a combination no condition text actually names).

**Evidence Truth Rule, concretely.** Exactly three site verdicts: `LEGAL_COMBINATION_PROVEN` /
`ILLEGAL_COMBINATION_PROVEN` / `NOT_AVAILABLE`. Two absence shapes are kept deliberately distinct and
never collapsed: a module with NO recognizable construct at all reports `NOT_AVAILABLE` at the MODULE
level with an EMPTY `sites` list; a construct this scan found the SHAPE of but could not close (an
unmatched `generate`/`endgenerate`, an unbalanced `if (...)` condition, an unclosed `begin`/`end` or
single-statement body) reports its own `NOT_AVAILABLE` SITE (module status stays `COMBINATION_SITES_
FOUND`, because a real, if unresolved, site does exist) -- proven by a dedicated test asserting both
shapes side by side. A condition referencing fewer than two real declared parameters is out of scope
by definition (not a site at all, not an error). `fold_combination_verdicts()` provides the mandatory
worst-wins composite (house rule 4): a single real `ILLEGAL_COMBINATION_PROVEN` or `NOT_AVAILABLE`
outranks any number of clean `LEGAL_COMBINATION_PROVEN` sites; an empty input folds to `NOT_AVAILABLE`,
never a clean pass.

**Boundary, stated rather than implied closed.** Declaration/parser-level only -- no `` `ifdef ``/
macro/generate-loop evaluation, no live simulation, no formal proof, and `LEGAL_COMBINATION_PROVEN`
means "the source text takes this branch's real content path", never "this was elaborated/simulated
and it worked". The qualifying `if` must be the FIRST non-whitespace token after `generate`/`initial`
(optionally through one `begin`) -- a block whose first real statement is something else (confirmed by
a dedicated `genvar i;`-before-`if` test) is a disclosed SILENT MISS, not a reported site. Only one
if-chain is scanned per `generate`/`initial` anchor. No cross-file constraint resolution. Matching
several other recent modules, `cli.py`/`gates.py`/`dashboard.py` were not touched (concurrent edit
pressure this session); the front door is standalone `python -m dv_harness.legal_param_combination_
extraction`, confirmed live via `--help`.

Proven by `dv_harness_tests/test_legal_param_combination_extraction.py` (25 tests, all against inline
synthetic RTL fixtures, never vendor content): both construct shapes (legal + illegal branches,
`$error` and `$fatal`, bare-`initial if` and `initial begin if...end`), a comment/string-literal
false-positive negative control, a genuine no-construct module, an unclosed-generate and an
unclosed-condition negative control (both honest per-site `NOT_AVAILABLE`), two out-of-scope negative
controls (single-parameter condition; two-SIGNAL zero-parameter condition), the module-status
distinct-absence-shapes test, file-read/verible-unavailable honest-failure controls, the vocabulary-
collision guard, four `fold_combination_verdicts()` worst-wins tests, and 4 real end-to-end tests
through the live `verible-verilog-syntax` binary (v0.0-4150-gfe58e708) proving real file:line
citations. `python -m pytest dv_harness_tests/test_legal_param_combination_extraction.py -q` ->
`25 passed`; re-run together with `test_param_define_extraction.py`/`test_design_architecture_ir.py`
(75 total) to confirm no interference.


<!-- S340: moved verbatim from CLAUDE.md original lines 20729-20748 (M4.6 CLAUDE Context Normalization) -->
## VIP Callback/Hook Extraction: the Sixth Capability IR, VIPCallbackHookIR (2026-09-07)

`vip_capability_extraction.py` already classifies a real `vip_symbol_index` into five capability IRs (VIPConfigIR/VIPTransactionIR/VIPScenarioPatternIR/VIPCheckerCapabilityIR/VIPCoverageCapabilityIR) via a NAMING heuristic (a small, disjoint suffix table, asserted disjoint at import) + an INHERITANCE heuristic (`vip_api_card.inheritance_chain()`, reused not reimplemented) + a 5-level qualification tag (PROJECT_PROVEN/VIP_DOCUMENTED/VIP_EXAMPLE_MATCHED/INFERRED_FROM_NAMING/UNKNOWN). Nothing in that module -- or anywhere else in this repo -- classified a VIP-indexed class as CALLBACK or EXTENSION-POINT shaped, the real UVM convention where a project extends `uvm_callback` and declares virtual "hook" methods a testbench overrides, invoked via `uvm_callback_iter`/`` `uvm_do_callbacks ``.

`dv_harness/vip_callback_hook_extraction.py` is that sixth capability, `VIPCallbackHookIR`, built as a SIBLING module rather than an edit to the (large, already-shipped) original -- callback/hook classification is a structurally different concept from the other five (neither a data-shape nor a behaviour-shape capability), and every mechanism this module needs from the original is IMPORTED and CALLED, never reimplemented: `vip_symbol_index.validate_symbol_index()`, `vip_api_card.index_classes_by_name()`/`inheritance_chain()`, the SAME 5-level qualification constants (imported by reference, not re-declared), the corroborating-evidence helpers (`_read_sources()`/`_citation_evidence()`/`_user_guide_evidence()`), and the OTHER five capabilities' own real naming-suffix table and inheritance-marker table -- used ONLY to detect a genuine cross-capability disagreement, never duplicated.

**The naming heuristic, checked disjoint at import.** `_CALLBACK_NAME_SUFFIXES = ("cb", "callback", "hook")`, checked disjoint from `vip_capability_extraction.py`'s OWN already-disjoint suffix table via `assert_callback_suffix_disjoint_from_existing()` -- run for real at import, and proven by a dedicated test to raise `RuntimeError` when a deliberate collision (e.g. `"cfg"`, already claimed by the config category) is introduced, giving the disjointness guarantee real detection power rather than merely never firing.

**The inheritance heuristic, grounded in real UVM base-class terminology, never a fictional marker.** Two real, closed signals: (1) `UVM_CALLBACK_BASE_CLASS_MARKER` -- the chain's terminal base is `uvm_callback` (the real base every project-defined callback class extends) or `uvm_callback_iter` (the real UVM utility class used to walk a `uvm_callbacks#(T,CB)` pool); (2) `STRUCTURAL_EXTENSION_POINT_VIRTUAL_METHODS` -- attempted ONLY when the terminal base did not already match one of the other five capabilities' own real inheritance markers (never second-guessing an already-established classification), requiring the class to be declared `virtual class` AND declare at least one `virtual`/`extern` `function`/`task` whose name is NOT one of a real, closed set of UVM base-class-library PHASE method names (`build_phase`, `run_phase`, `report_phase`, ...) -- excluding phase overrides is what keeps an ordinary virtual UVM component (a driver, a monitor -- both routinely declare `virtual function build_phase(...)`/`virtual task run_phase(...)` as their ONLY virtual methods) from being misclassified as callback/hook-shaped merely for using the `virtual` keyword UVM's own component base classes already require.

**When naming and inheritance disagree, in EITHER direction, never guessed into either side.** This module's own naming/inheritance signals are mutually exclusive with the OTHER FIVE capabilities' own naming/inheritance signals on any single class (by the disjointness guarantees above), so disagreement means this module's own heuristic affirmatively says CALLBACK_HOOK while the other five's own naming or inheritance heuristic affirmatively says something else. Both directions are checked and reported as an ambiguous candidate (`qualification: UNKNOWN`, `ir_type: AMBIGUOUS_CAPABILITY_CANDIDATE` -- the SAME sentinel `vip_capability_extraction.IR_AMBIGUOUS`, reused not re-declared) naming both conflicting signals -- never silently classified into either side. A class matching NEITHER of this module's own two heuristics is counted in `unclassified_class_names`, never forced into `VIPCallbackHookIR`.

**Qualification, promoted only on real evidence, unchanged rule.** Every classified item defaults to `INFERRED_FROM_NAMING` regardless of how strongly naming and inheritance agree; promotion to `PROJECT_PROVEN`/`VIP_DOCUMENTED`/`VIP_EXAMPLE_MATCHED` always requires the SAME real cited `file:line` (project/example usage) or document+heading (distilled VIP user-guide reference) evidence the original module already requires, via its own real citation scanners, called here unmodified.

**Deliberately bounded, and stated rather than implied closed.** (1) This is a DECLARATION-LEVEL/PARSER-LEVEL extractor over a real `vip_symbol_index`, never an elaborator: no `generate`/`` `ifdef `` condition is evaluated, no method body is read (the index it reads already retains none), no live simulation and no formal proof -- `is_virtual`/`is_extern`/method `kind` are exactly the declaration-level facts `vip_symbol_index.py` already records. (2) The structural fallback is intentionally conservative: it fires only when a class's own declared methods clear the phase-name exclusion, and only when no stronger, already-established inheritance marker from the other five capabilities already explains the class. A VIP using an entirely different, project-specific callback convention is honestly left unclassified rather than guessed. (3) It decides nothing beyond classification: no build, job, approval, or stage gate, and it weakens no human-approval gate anywhere.

The real synthetic VIP fixture this repo already ships, `examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv` (the same fixture `vip_capability_extraction`'s own tests use), previously declared no callback-shaped class at all -- extended with one real class, `svt_demo_report_cb extends uvm_callback`, declaring two real virtual extension-point methods (`post_report`, `pre_close`), per this module's own house rule 6 ("extend it if it declares no callback-shaped class yet"). The two pre-existing tests whose exact-set assertions this extension affects (`test_vip_capability_extraction.py`'s `unclassified_class_names` check, `test_asset_processing_artifacts.py`'s indexed-class-name check) were updated to include the new class -- both confirming it is correctly left UNCLASSIFIED by the OLD five-capability module (its name suffix `cb` and its base `uvm_callback` match neither of the five's own suffix nor marker tables), which is itself a real proof point that the old and new modules do not silently overlap. The real, mechanically-produced worked-example markdown (`examples/asset_processing/generated/vip_ref/demo.md`) was regenerated via the real `vip_symbol_index.write_vip_ref()` call (never hand-edited) to reflect the new indexed class and its real `file:line` citations.

Proven by `dv_harness_tests/test_vip_callback_hook_extraction.py` (18 tests): the real `svt_demo_report_cb` class classified correctly (`NAME_AND_INHERITANCE_AGREE`, real `file:line` citation) with every promotion rule (`PROJECT_PROVEN`/`VIP_DOCUMENTED`/`VIP_EXAMPLE_MATCHED`, and their combined priority) driven one at a time; the headline negative control that EVERY other real class in the shared fixture -- including the two `virtual class`-shaped ones (`svt_demo_driver`, `svt_demo_agent`) that could plausibly be mistaken for an extension point -- is correctly left unclassified; both directions of naming-vs-inheritance disagreement reported ambiguous with `UNKNOWN`, never guessed; the structural extension-point fallback proven positively (a real non-phase virtual method on a `virtual class` with no callback-shaped name or base) and negatively (a `virtual class` whose only virtual methods are real UVM phase overrides, proving the phase-exclusion has real detection power); the disjoint-suffix-table import-time assertion proven to catch a real introduced collision; an empty index reporting `NOT_AVAILABLE` rather than a clean pass; a missing index file raising rather than reporting a clean result; and both real CLI entry points (`python -m dv_harness.vip_callback_hook_extraction`) driven as real subprocesses. Real run: `python -m pytest dv_harness_tests/test_vip_callback_hook_extraction.py -q` -> `18 passed`. All nine directly-affected existing suites (293 tests combined, including the extended shared fixture's own consumers) re-verified passing.


<!-- S342: moved verbatim from CLAUDE.md original lines 20804-20863 (M4.6 CLAUDE Context Normalization) -->
## Subsystem Verification Center + System Integration Center + Compatibility (2026-09-07)

`dashboard.py` gained a GUI card surfacing four already-real modules' own reports over one
project's registered-subsystem set: `subsystem_contract.py` (per-subsystem verification
contract), `system_verification_contract.py` (the cross-subsystem rollup), `ip_ownership_
conflict.py` (per-subsystem VIP-vs-legacy-BFM ownership check), and `system_resource_
inventory.py`'s real SYS-9..14 cross-subsystem compatibility findings. This item's own
item-implementation report for this batch carried placeholder text (`item_id: "test"`,
`real_evidence_summary: "test"`, `claude_md_section_markdown: "test section"`, no
module/test paths at all); the real route/card/test file were found already present and
correct on disk when this integration pass read `dashboard.py` and its test file directly, so
this section is a hand-written, honest record of that real code rather than an appended
placeholder.

**REUSE OVER REINVENT: this card computes nothing itself.** Unlike the Design Knowledge/
Requirement-vPlan cards, this card needs no caller-supplied file to do real work:
`subsystem_contract.assemble_subsystem_contract()` and `system_resource_inventory.
real_cross_subsystem_findings()` are both self-sufficient over this project's own real
registered-subsystem set (`environment_mode_router.read_registered_subsystem_entries()`,
written only on a gate-verified SIGNOFF PASS) and its own `env.manifest.json`/`evidence.duckdb`/
waiver ledger -- called live, on every request, never re-derived here. An optional
`.dv-harness/subsystem_system_verification/inputs.json` overlay supplies the handful of facts
this repo has no fixed producer path for yet: a caller-declared `legacy_bfm_declarations`/
`connectivity_rows` per subsystem for `ip_ownership_conflict.py` (that module's own docstring:
"there is no real producer for this fact in this codebase"), and a real
`system_topology_analysis.py`-/`system_command_plan.py`-shaped document for
`system_verification_contract.py`'s own topology/command_registry sections, which that module
deliberately never imports or derives itself -- the same "accept an explicit caller-declared
fact rather than invent one" convention `design_knowledge_correlation.py`'s `sources.json`
already establishes. Absent that overlay, those specific sections honestly report
`NOT_APPLICABLE`/`NOT_AVAILABLE` rather than a fabricated pass.

**Evidence Truth Rule.** With no subsystem registered and no `env.manifest.json` anywhere, the
project-scope `subsystem_contract` record is still honestly assembled (never crashed on),
`ip_ownership_conflict.py` reports `NOT_APPLICABLE` (no manifest to check), and
`system_resource_inventory.py`'s cross-subsystem findings honestly report
`TRACK_B_ANALYSIS_UNAVAILABLE` (fewer than two subsystems) -- never a fabricated CLEAR/COMPLETE
verdict. A malformed `inputs.json` surfaces `MALFORMED_INPUTS_FILE` rather than a bare 500. A
declared legacy BFM sharing an ACTIVE port with a real VIP instance surfaces as a real ownership
question rather than being silently smoothed into CLEAR -- and, absent the `connectivity_rows`
`ip_ownership_conflict.py` would need to conclusively judge ownership, the honest `UNKNOWN`
status is reported (never a guessed CLEAR or CONFLICT).

Nothing here mints an approval, runs a stage, or invokes a gate -- every one of the four
underlying modules is read-only by its own documented contract; there is deliberately no write
endpoint of its own.

Proven by `dv_harness_tests/test_dashboard_subsystem_system_verification_center.py` (5 tests,
driven over a real dashboard server on a free local port, re-verified fresh by this integration
pass: `python -m pytest
dv_harness_tests/test_dashboard_subsystem_system_verification_center.py -q` -> `5 passed`): the
honest bare-project state described above; the malformed-inputs-file negative control; a real
registered subsystem with a real `env.manifest.json` served byte-for-byte identical (modulo the
real wall-clock `assembled_at` stamp) to direct calls into `subsystem_contract.
assemble_subsystem_contract()`/`ip_ownership_conflict.analyze_ip_ownership_conflict()`, proving
the endpoint reads the real modules rather than re-deriving anything; a declared legacy-BFM
ownership question surfaced honestly as `UNKNOWN` with no `connectivity_rows` supplied; and the
card proven served in the page HTML and wired into the existing `load()` poll loop, carrying its
own "Read-only" note.


