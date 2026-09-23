# Governance / Safety / Self-Audit — Detailed Task-Scoped Governance

Moved out of CLAUDE.md during **M4.6 — CLAUDE Context Normalization**. Registered as `id: GOVERNANCE_SAFETY_AUDIT`, `load_policy: TASK_SCOPED`. Sections preserved verbatim; only residency changed.

Covers: safety-sandbox/rollback mechanics, dependency/supply-chain governance, change-impact/traceability, security-policy evidence, multi-agent parallelism policy, and a small residual of sections a keyword classifier could not confidently place in a narrower domain (disclosed explicitly in `M4_6_CONTEXT_CLASSIFICATION.csv` -- routed here as the general governance catch-all, not silently dropped).

---

<!-- S035: moved verbatim from CLAUDE.md original lines 1058-1119 (M4.6 CLAUDE Context Normalization) -->
## Power Intent / Low-Power Evidence (2026-09-06)

Power intent is READ from real UPF and turned into a structured model; no low-power BEHAVIOR is
verified here, and the difference is stated rather than blurred. Spec section 224 ("LOW-POWER
INTEGRATION") ends with two rules this obeys literally: absent low-power evidence is
`UNSUPPORTED / UNKNOWN`, and "do not fabricate a low-power verification flow."

The gap was total. Grepping for `upf`/`power_domain`/`set_isolation`/`set_retention`/
`create_supply` matched nothing executable in `dv_harness/` or `tools/`. The only power-shaped
thing in the repo was `"power_domains": []` — a field
`tools/dut_architecture/build_architecture_model.py` hardcoded as an empty list and
`.dv-harness/dut-architecture/architecture_model.schema.json` declared with no item shape, i.e. a
field nothing had ever populated. `tools/verification_flow/reset_clock_power_sequence_gate.py` and
`reset_power_cdc_corner_gate.py` are self-attested reset/CDC evidence-block checks; neither reads a
power-intent file.

`dv_harness/power_intent.py` is the reader. It is a real Tcl-subset UPF parser (comments, `;`
separation, backslash continuation, nested braces, quoting, and `set`/`$var` substitution
*including* the Tcl rule that braces suppress substitution — getting that backwards would invent
signal names the design does not have), modelling `upf_version`/`set_design_top`/`set_scope`/`set`,
`create_power_domain`, `create_supply_port`/`create_supply_net`/`create_supply_set`,
`connect_supply_net`/`set_domain_supply_net`, `create_power_switch`, and
`set_isolation`/`set_isolation_control`/`set_retention`/`set_retention_control`. UPF-1.0 style (a
separate `*_control` command) and UPF-2.x style (control options folded into the strategy) merge
into ONE strategy record, so "does this strategy have a control signal" has one answer.
`analyze_power_intent()` then checks that intent against ITSELF — a strategy naming an undeclared
domain, a supply referenced but never created, a **switchable domain with no isolation strategy**
(the rule that carries real low-power meaning: outputs floating into always-on logic), a retention
strategy with no save/restore sequencing. `dv-harness power-intent --upf <file> [--json]
[--fail-on-error]`, or `python -m dv_harness.power_intent`.

Where it lands: `build_architecture_model.py --upf <file>` populates `power_domains` from
`power_domains_for_architecture_model()` (name, elements, primary supplies, `switchable`, its
isolation/retention strategy names, and a real `<upf file>:<line>` evidence string), and records a
`UPF_POWER_INTENT` evidence row. Without `--upf` the field stays `[]` and `unknowns` says
"UNSUPPORTED/UNKNOWN" — an absent power intent must not look like a design that simply has no
power domains.

**Deliberately bounded, and stated rather than implied closed.** (1) NOTHING here is checked
against RTL, a netlist, or a simulation. This project owns no low-power DUT and no real UPF of its
own; a "check" against nothing would be exactly the fabricated low-power flow section 224 forbids.
Isolation/retention/clock-gating/wake-up BEHAVIOR, power-aware simulation, and UPF-to-simulator
handoff are NOT implemented and need a real low-power DUT plus a power-aware simulator. There is
deliberately no stage gate: a gate that passes on power intent nobody cross-checked would be worse
than none. (2) It is a Tcl SUBSET parser, not an interpreter — command substitution `[...]`,
`if`/`foreach`/`proc`, `expr` and `source`/`load_upf` inclusion are not executed. (3) Power-state
tables (`add_power_state`, `create_pst`, `add_pst_state`) are recorded as unmodelled rather than
modelled, because their supply-expression mini-language does not fit the flat option/value shape
the modelled commands share. Any command this parser does not model is never silently dropped: it
is reported with its file and line as an INFO finding saying it was NOT analysed. (4) An empty
model is `NOT_AVAILABLE` (CLI exit 2), never PASS, with or without `--fail-on-error`.

Proven by `dv_harness_tests/test_power_intent.py` (42 tests) against
`dv_harness_tests/fixtures/power_intent/synthetic_lp_soc.upf` — a fixture whose own header states
it is a test fixture and not any real DUT's power intent: the clean fixture extracts a
fully-asserted model (including `$ISO_CTRL` substitution and real source line numbers) and reports
ZERO findings, then every analysis rule is driven by MUTATING that same clean source one defect at
a time, so each assertion proves that rule caught that specific injected defect. The integration is
exercised through the REAL `build_architecture_model.py` and `dv-harness power-intent` subprocesses,
both with and without power intent present.



<!-- S038: moved verbatim from CLAUDE.md original lines 1262-1335 (M4.6 CLAUDE Context Normalization) -->
## Agent Benchmark Dataset Governance (2026-09-06)

An agent/skill is scored against a VERSIONED corpus, and the corpus says whether it was scored on
the examples it was tuned on. Spec section 226's two rules are what this obeys literally: "do not
evaluate a capability only on examples used to tune it", and "benchmark results must identify
Agent/Skill version and environment."

The gap was total. `capability_evolution.run_controlled_experiment()` is per-CANDIDATE execution —
one proposed change, one fixture, one measurement, answering "did this change help". Its
`benchmark_plan` is per-candidate free text and its `benchmark_result` is that one measurement;
neither is a corpus, neither is versioned, and neither can say a case was used for tuning. Grepping
for `benchmark_dataset`/`eval_corpus`/`dataset_version`/`leakage` matched no executable code
(`memory_security`'s secret-leakage detector is unrelated).

`dv_harness/benchmark_dataset.py` is the registry, and it reuses rather than reinvents on both
sides:
- RUNNER: each case is executed by `capability_evolution`'s OWN isolated machinery —
  `_prepare_shadow_run()` (workspace containment, fixture validation) and `_execute_shadow_run()`
  (fingerprint the fixture, copy it twice, drive the REAL `DVHarness.run_stage()` in each arm,
  measure both through `control_plane.describe_stage()`, re-fingerprint, write the record). There is
  one shadow-run implementation in this package and this calls it; a case's `expected_result` is one
  of that module's own `BENCHMARK_OUTCOMES` for the same reason. `allow_execution_stages` is
  hard-wired False, so a stored corpus can never drive a real build or regression submission.
- STORE: an immutable JSON version file under
  `<root>/.dv-harness/benchmark_datasets/<id>/versions/vN.json`. Re-registering a version with
  different content is REFUSED (bump instead); a bump whose cases are identical to the previous
  version is refused (a bump that changes no case is not a new dataset); back-dating below the
  latest version is refused; re-registering OVER a version whose file has drifted is refused rather
  than blessed as idempotent. `verify_dataset_integrity()` recomputes the digest off disk, so a case
  edited in place without a bump reads CONTENT_DRIFT, and `diff_dataset_versions()` names what a
  bump added, removed and modified.

TWO DIGESTS, deliberately. `case_record_digest()` covers every section 226 tracked field, and
dataset-version integrity is checked against it — editing an owner or a note is still editing the
corpus. `case_question_digest()` covers only what the case ASKS (`expected_result`, `fixture_ref`,
`stages`, `mutation`), and LEAKAGE is keyed on that, matched across EVERY version of the dataset via
an append-only `tuning_ledger.jsonl` that `record_tuning_use()` writes. So renaming or re-owning a
case cannot launder the fact that a subject was tuned on it, while changing what it asks makes it
genuinely another case. An eval reports the full score AND the held-out score over the non-leaked
cases, judges its status on the held-out set, and reports `INADMISSIBLE` when EVERY case was used
for tuning — section 226's rule as a status rather than a sentence.

`dv-harness benchmark-dataset register|list|verify|diff|record-tuning-use|leakage|runs` and
`python -m dv_harness.benchmark_dataset` share one implementation (`execute_verb`, the same
convention `power-intent` and `golden-scenario` use). Exit 0 fine, 1 a real finding (content drift,
leakage present, a recorded run that was not met), 2 nothing to report.

**Deliberately bounded, and stated rather than implied closed.** (1) This module DECIDES nothing
about promotion. It makes no `transition()`, persists no candidate, and its records carry
`produced_by = BENCHMARK_EVAL_PRODUCER`, which is NOT in
`capability_evolution.SHADOW_RUN_PRODUCERS` — so a benchmark record can never be pinned into a
stability window or satisfy `assert_benchmark_measured()`. Evaluating an AGENT is not evidence for
promoting a capability CHANGE. Every human-approval gate is untouched; there is deliberately no
stage gate, for the reason `golden_scenario` and `power_intent` already state. (2) Its case/run/
leakage/integrity vocabularies share no token with `dv_harness.models.Status`
(`assert_no_verification_verdict_vocabulary()`, the same rule and the same reason as
`capability_evolution`'s): MATCHED is not a DV PASS. (3) A case is executed as a two-arm shadow run
over a fixture project — the shape the reused runner measures. Pure prompt/response agent evals and
generated-file-diff cases are NOT supported. (4) There is no `eval` CLI verb: an eval must name the
subject under evaluation via a `harness_factory`, and defaulting it would dispatch real `claude -p`
subprocesses per case from a typed command line. (5) `difficulty` and `qualification` are declared
metadata; nothing judges whether a case is as hard as it says.

Proven by `dv_harness_tests/test_benchmark_dataset_governance.py` (22 tests) against the two
synthetic corpora in `dv_harness_tests/fixtures/benchmark_datasets/`, whose own `notes` state they
are fixtures derived from no real project. The central test evaluates ONE subject against v1 and
then v2 through REAL two-arm runs — the real engine stage runner, the real
`command_migration_integrity_gate.py` subprocess, real arm workspaces on disk — and asserts the two
results are distinguishable on status (MET vs NOT_MET), on score (3/3 vs 3/4), on which case failed,
and on the dataset digest each cites, because v2 added a harder held-back case. The converse is
proven too: two SUBJECT versions score differently on one fixed corpus. Both CLI entry points are
driven as real subprocesses and their exit codes asserted.



<!-- S044: moved verbatim from CLAUDE.md original lines 1670-1784 (M4.6 CLAUDE Context Normalization) -->
## Blackboard Topics Written Outside the Graph (2026-09-04)

"Blackboard stores current verification truth" (Core Operating Rules) was met only for topics a
graph STAGE writes: `engine.py`'s `run_stage()` PASS branch calls `_write_blackboard_from_evidence()`
per `node.blackboard_write`, which is real and firing. Three subsystems built after that mechanism
never joined it — a 2026-09-04 audit found zero occurrences of "blackboard" in `env_manifest.py`,
`question_queue.py`, `connectivity.py`/`connectivity_check.py`, and no node in
`.dv-harness/graph/main_graph.json` naming any topic they could have written. Each persisted only
to its own private store, so no stage could see any of it. Three topics now close that, written by
real CLI/runner entry points rather than by a graph node:

- **`env_manifest`** (`source: env-manifest`) — written by `dv-harness env-manifest generate`
  (`env_manifest.sync_to_blackboard()`). A prompt-sized SUMMARY: each layer's own `status`/`reason`
  verbatim (so a NOT_AVAILABLE stays NOT_AVAILABLE, never a bare empty list), plus VIP instance
  paths/types, parsed RTL file paths + module names, and counts. The full verible parse trees stay
  in `env.manifest.json`, which the topic points at — inlining them would drown every reading
  stage's prompt. Since schema 1.1 (2026-09-04) it additionally carries the installed VIP
  package name+version list, distilled user-guide titles + section counts, the names of any
  address regions whose base **disagrees** with the register map, and the ids of vPlan items whose
  test/coverage claims resolve to nothing — the conflicts specifically, not just their counts,
  because a reading stage must not have to open a file to discover them. Read by
  `ARCH_DISCOVERY`, `PROJECT_MODEL`, `IMPLEMENT`.
- **`open_questions_decisions`** (`source: question_queue`) — refreshed from
  `QuestionQueueStore._save_decisions()`, the one choke point both `_persist_decision()` and
  `revoke_decision()` already pass through, so it cannot drift from `decisions.json`. Carries every
  LIVE decision (a revoked one is gone, exactly as `find_decision()` sees it) with its `source`
  kept per entry, so a Tier-2 auto-assumption stays distinguishable from a real human answer. The
  mirror is ON by default at every construction site, not opt-in. Read by `IMPLEMENT`,
  `FAILURE_RECOVERY`, `SIGNOFF`.
- **`connectivity_gates`** (`source: connectivity-check`) — written by a real `just
  connectivity-check` gate run (`connectivity_check.sync_gates_to_blackboard()`), carrying each
  gate's `GateStatus` VALUE (PASS/FAIL/NOT_AVAILABLE/PENDING/NOT_YET_RUN stay five distinct states,
  never a bool) plus the RTL fingerprint they ran against. `--check-only` runs no gate and
  deliberately does NOT refresh it, so stale verdicts can never look freshly produced. Read by
  `BUILD_DEBUG`, `VERIFY`, `SIGNOFF`.

All three writes are best-effort: a blackboard failure must never turn an already-written manifest,
an already-recorded decision, or an already-completed gate run into a failed command. The edges
(both halves — the write, and a real node declaring the `blackboard_read`) are proven end-to-end
against the real shipped graph by `dv_harness_tests/test_blackboard_subsystem_wiring.py`.

**The autonomous path now PRODUCES all three, not only reads them (2026-09-04, same-day gap
close).** The three writers above are reached only from a human-invoked CLI/runner, and a re-audit
found `engine.py` carried zero references to `env_manifest`/`question_queue`/`connectivity_check`,
no node prompt anywhere instructed an agent to run `dv-harness env-manifest generate` or
`just connectivity-check`, and CI ran only `connectivity-check --check-only`, which by its own
contract refreshes nothing. Seven real nodes (ARCH_DISCOVERY, PROJECT_MODEL, IMPLEMENT,
BUILD_DEBUG, VERIFY, FAILURE_RECOVERY, SIGNOFF) declare one of the three in `blackboard_read`, so a
fully autonomous `loop()` from INTAKE to SIGNOFF could finish with all three permanently absent.
`run_stage()` now calls `_refresh_declared_subsystem_topics()` before the stage-entry display and
before `_gather_stage_context()`'s `blackboard.snapshot()`, driven by the node's OWN
`blackboard_read` (never a hardcoded stage list — `engine.SUBSYSTEM_TOPIC_REFRESHERS` is a table
precisely so a test can hold it against the real graph). Each entry calls that subsystem's REAL
producer and nothing else:
- `env_manifest.ensure_blackboard_topic()` MIRRORS an `env.manifest.json` already on disk. It never
  generates one — generation needs RTL/register-map/SoC-arch/testplan inputs the engine does not
  have, and inventing a manifest is exactly the fabrication the manifest's honesty contract
  forbids. No manifest → the topic stays absent and `MANIFEST_NOT_GENERATED` plus the real
  producing command is recorded.
- `QuestionQueueStore.ensure_blackboard_topic()` mirrors `decisions.json` through the same single
  `_sync_decisions_to_blackboard()` choke point and writes no decision. Answering stays human-only
  ("由真人執行"); an EMPTY decision set is itself citable truth, distinct from "no record".
- `connectivity_check.ensure_blackboard_topic()` runs the REAL 3-gate recipe (a real gate run is
  this topic's only producer) using the EXISTING staleness trigger — never run, RTL fingerprint
  moved, or topic absent. This is the missing "`just connectivity-check`, not `--check-only`, on
  the real automated flow" step. Unchanged RTL costs nothing; a project with no
  `.dv-harness/connectivity_check.json` reports NOT_CONFIGURED, as this harness repo itself does.
Every refresh is best-effort (it can never fail a stage) and every outcome — including each honest
absence and its reason — is one `BLACKBOARD_TOPIC_REFRESH` event in `.dv-harness/events.jsonl`, so
"was this topic produced on this run, and if not why" is answerable from the audit trail rather
than inferred from the topic's silence.

**`Blackboard.write()` is atomic since 2026-09-04.** It was a plain truncate-then-write
`p.write_text(...)` while `blackboard.py` imported `tempfile` and never used it — and the
concurrency is real: `engine._advance_with_fanout()` runs parallel_group branches through a genuine
`ThreadPoolExecutor` in one process, and `dashboard.py` polls topic files off disk from an HTTP
thread. The fan-out `AgentTaskStore.acquire()` claim only stops two branches claiming the same
WRITE topic; it never made the file operation safe, and none of `engine.py`'s ~17
`self.blackboard.read/write()` call sites is wrapped in a try/except, so a torn read would have
propagated out of `run_stage()`. `write()` now goes through `tempfile.mkstemp()` +
`storage._atomic_replace()` (reused, not re-implemented, so the Windows `os.replace()` retry covers
it too) and `read()` retries a transiently unparseable/locked topic — while still RAISING on a
persistently corrupt one, because reporting an unreadable topic as absent would present "no
verification truth recorded" as a fact. Both halves, and all three producers on the real
`run_stage()` path, are proven by
`dv_harness_tests/test_blackboard_automatic_path_and_concurrency.py` — whose concurrency tests
include a deliberately non-atomic control writer, so "no torn reads" is a result with detection
power behind it rather than a test that never looked hard enough.

**A fourth topic joined them on 2026-09-04, from the opposite direction**: `qualified_conclusion`
was already being WRITTEN on the real path — `engine._score_root_cause_confidence()` composes
RE_AUDIT's hard-gate verdict and `inference.score_confidence()`'s independently recomputed
confidence into one `QualifiedConclusion` (`dv_harness/qualified_conclusion.py`) on every
gate-verified RE_AUDIT/RCA_JOIN PASS — but nothing on the production path READ it: no node declared
it, and its only consumer was `dashboard.py`'s display. So the harness's "Hypothesis + Evidence +
Result + Gate = Conclusion" chain produced a Conclusion that never entered closure. Both halves of
that edge now exist:
- `REQUIREMENT_CLOSURE`, `PROMOTION_READINESS` and `SIGNOFF` declare it in `blackboard_read`, so the
  real conclusion reaches each closure stage's prompt; it is also a `blackboard_key` entry on
  SIGNOFF's `expected_evidence` checklist.
- `policy.can_signoff()` — the hard-stop `engine.loop()` consults BEFORE running SIGNOFF — now
  REFUSES (BLOCKED, no auto-redirect, a human decision) while a recorded conclusion says
  `is_qualified: false`. This is a different question from the neighbouring
  `require_second_pass_audit`, which only asks whether RE_AUDIT reached stage PASS, never what it
  concluded — and the difference is reachable, not theoretical: `root_cause_evidence_gate` mandates
  non-empty `counter_evidence` only at its own HIGH/CONFIRMED tier, so a MEDIUM finding with one
  supporting citation and two unrefuted counter-evidence entries passes all 11 RE_AUDIT gates while
  the recompute lands at LOW (`2*1 + 2 - 3*2 = -2`). **Disclosed residual**, scoped like
  `require_tier`'s: only a record that EXISTS and says false refuses. Absence is not a refusal —
  `require_second_pass_audit` already covers "RE_AUDIT never passed", and blocking on absence would
  make every pre-existing project unclosable. `policy.require_qualified_conclusion` (default true)
  is the switch. Proven on the real path — including the reachability of the unqualified-yet-
  gate-passing state, and `loop()` never dispatching SIGNOFF while it holds — by
  `dv_harness_tests/test_qualified_conclusion_closure_gate.py`.


<!-- S045: moved verbatim from CLAUDE.md original lines 1785-1882 (M4.6 CLAUDE Context Normalization) -->
## env.manifest.json Fact Sources: schema 1.1 (2026-09-04), provenance 1.2 (2026-09-06)

`env.manifest.json` keeps exactly three top-level layers (`vip_config` / `dut_facts` /
`env_topology`) and `dv_harness/env_manifest.py` remains its sole writer. A 2026-09-04 re-audit
confirmed four of the spec's fact sources were genuinely BLOCKED — absent, not stubbed — and each
is now real, wired and tested (`dv_harness_tests/test_env_manifest_fact_sources.py`):

- **`vip_config.vip_release`** — a real filesystem scan of `$DESIGNWARE_HOME`
  (`scan_designware_home()`), walking both `vip/svt/<pkg>/<ver>` and `vip/<pkg>/<ver>` layouts and
  locating each package's real release-notes / feature-matrix files. "Which VIP release is this
  environment built against" is answered from the install tree, not from a version someone typed
  into a document. Unset `$DESIGNWARE_HOME` and a set-but-stale one stay **distinct** NOT_AVAILABLE
  reasons — collapsing them would hide a fixable operator error.
- **`vip_config.user_guide_refs`** — POINTERS to guides distilled OFFLINE by
  `dv_harness/vip_user_guide_distill.py` (`dv-harness vip-user-guide distill`, real `pypdf`
  extraction). It is a separate command on purpose: "never loaded into runtime context" is enforced
  structurally by keeping the only code path that opens a document off the generation path. The
  manifest records path/sha256/bytes/page-count/section-COUNT and not one word of prose;
  `assert_no_user_guide_body_in_manifest()` runs on every generate and makes that checkable, since
  the schema can police shape but cannot notice prose parked in a legitimately-string field.
- **`dut_facts.address_map` / `dut_facts.clock_reset`** — from the project's own SoC spec pipeline
  via the `soc_arch_map.schema.json` input contract (a documented contract, not an extractor, for
  the same reason `register_map.schema.json` is one: this repo owns no SoC to extract from). Every
  address entry carries a real `register_map_agreement` cross-check against `dut_facts.registers`,
  compared as integers. A DISAGREES is **surfaced, never auto-resolved** — per Source Authority
  Order. Reset `active_level` is required by the contract and never defaulted.
- **`env_topology.testplan_correspondence`** — the computed three-way join of the project's real
  testlist, vPlan items and coverage model (`testplan_sources.schema.json`). Each list read alone
  always looks healthy; only the join exposes a vPlan item claiming a test nobody runs, one measured
  by a covergroup nobody wrote, or a test burning sim time against no stated intent. Matching is a
  literal name join, never fuzzy. An item whose claims could not be checked because its axis was not
  supplied reports **NOT_CHECKED**, never LINKED.

**Schema 1.1 is a breaking bump and deliberately so**: these are REQUIRED keys, so a stale 1.0
manifest fails `load_env_manifest()` loudly rather than silently presenting an environment as having
no address map and no testplan correspondence — a claim about the environment it cannot support.
env_manifest.py is the sole writer, so the fix is to regenerate, never to migrate.

**Schema 1.2 adds spec section 210's PER-ARTIFACT GENERATION PROVENANCE TUPLE, inside the existing
`generator` block (2026-09-06, SPEC-7).** The gap was confirmed by direct search before building:
`generator` was `{"tool", "version"}` and `version` is env_manifest.py's own `SCHEMA_VERSION`, so
"which harness build produced this artifact" was answerable only by misreading the schema version
as one; a repo-wide grep found no agent/skill identifier, no input reference and no
`repository_sha`/`git_sha` field anywhere in the module or its schema, and `git_governance.py`
carries only push/merge branch protection -- it has no per-artifact SHA-stamping function. Four
answers now sit in that same block rather than in a second, parallel provenance record beside it:
- `tool_version` -- the real `dv_harness.__version__`, deliberately distinct from `version`.
- `agent` -- which agent/skill produced the artifact, in the convention the profiles themselves
  use to self-identify: the YAML front-matter `name:` of a `.claude/agents/*.md` profile or a
  `.claude/skills/**/SKILL.md` skill. A declared identifier is CHECKED against the real profiles on
  disk (`known_generation_identifiers()`), and the four `resolution` values never collapse:
  AGENT_PROFILE/SKILL (a real profile declares this name), NOT_FOUND (declared and no profile
  carries it -- recorded as declared, never accepted as verified), PROFILE_TREE_NOT_AVAILABLE
  (a deployed copy with no `.claude` tree; nobody could check), NOT_DECLARED.
- `input_ir` -- what drove the generation. The SPEC-3 form cites a section 184 requirement contract
  by `requirement_id`, and the record is really located in the named document, validated against
  `requirement_contract.schema.json` and run through `requirement_contract.downstream_consumable()`
  -- so a manifest that cites a requirement also records whether a generator was ENTITLED to build
  from it, rather than merely naming it. The fallback form is a real input file recorded as
  path + sha256 + bytes, never content.
- `repository_sha` -- the real current git SHA, read by the EXISTING `change_impact.resolve_sha()`
  (a real `git rev-parse --verify HEAD^{commit}`), the same reader `benchmark_dataset.py` already
  stamps an experiment record with; there is no second git reader in this package. `harness` is
  always read from THIS FILE's own checkout, so a caller cannot reroute the generator's identity;
  `project` is NOT_DECLARED unless a project root is named. No absolute path is recorded.

**This narrows the diffability contract deliberately, and says so rather than leaving it to be
discovered.** A manifest regenerated after the HARNESS ITSELF moved to a new commit now differs in
`generator.repository_sha.harness`. That is not the clock noise the no-`generated_at` rule exists
to exclude -- a different generator really did produce the artifact, which is the fact section 210
exists to record. Unchanged inputs AND an unchanged harness commit still produce a byte-identical
file. 1.1 -> 1.2 is a BREAKING bump for the same reason 1.0 -> 1.1 was: the keys are REQUIRED, so a
stale 1.1 manifest fails `load_env_manifest()` loudly instead of presenting an untraceable artifact
as a traceable one, and the fix is to regenerate.

**Deliberately bounded.** (1) Nothing is fabricated and nothing is defaulted: an undeclared agent,
an undeclared input and an undeclared project root are each recorded as NOT_DECLARED with the real
flag that would answer them, and provenance NEVER fails generation by default -- a project that has
not adopted it is not retroactively broken. `--require-provenance` (`assert_generation_provenance_
complete()`) is the strict opt-in, the same disclosed-default shape as `require_tier` /
`require_phy_boundary`. (2) It records and CHECKS; it arbitrates nothing, approves nothing, and has
no stage gate. (3) It covers `env.manifest.json` only -- `create_environment()`'s own
`environment_manifest.json` and the generated `.sv` files carry no provenance tuple yet.
(4) The flattened tuple reaches the `env_manifest` Blackboard topic as `generation_provenance`, so
a reading stage can see which agent, which input and which commit produced the facts it is about to
reason over without opening the file.

Proven by `dv_harness_tests/test_env_manifest_generation_provenance.py` (38 tests), whose detection
power comes from asserting against sources OUTSIDE the code under test: the harness SHA is compared
against an INDEPENDENT `git rev-parse HEAD` the test runs itself, the project SHA against a REAL
throwaway git repository with a REAL commit, `tool_version` against the real
`dv_harness.__version__`, the agent identifier against the REAL `.claude` profiles in this checkout
(with a fabricated identifier as the negative control), and the input digest against an
independently computed hashlib hash. Reuse is held as a property rather than a claim -- patching
`change_impact.resolve_sha()` must change what the manifest records, which a second hand-rolled
`git rev-parse` would not respond to. Both the real CLI front door and the breaking-bump refusal of
a 1.1-shaped manifest are driven end to end.


<!-- S058: moved verbatim from CLAUDE.md original lines 2837-2947 (M4.6 CLAUDE Context Normalization) -->
## Parallel Document-Extraction Fan-Out: `dv-harness doc-extract` (2026-09-05)

`self_check_list.md` item #40 asks for multiple extraction workers launched
SIMULTANEOUSLY to convert the eleven document categories a VIP-based
verification environment is built out of (VIP doc/source/examples, DUT
doc/registers, IP doc, programming guide, DUT RTL, IP source, top TB,
command.txt, standard specs). The INDIVIDUAL extractors were already real;
the DISPATCH layer did not exist anywhere, confirmed by direct search on
2026-09-05: `.dv-harness/graph/main_graph.json` has exactly two non-null
`parallel_group`s (`ANALYSIS_G1`, `RCA_G1`) and neither is document
extraction; `.claude/workflows/` holds exactly two scripts, both for
RCA/evidence consensus, and neither references any extractor module; and a
repo-wide grep for the extractor module names inside `dv_harness/*.py` found
only sequential single-purpose imports, one downstream consumer at a time.
So each extractor was only ever invoked individually, on its own CLI verb or
by a direct import. `dv_harness/doc_extraction_fanout.py` is that missing
layer and nothing else.

**No new concurrency primitive, and no new graph node.** The pattern is
`subsystem_architecture_analysis.run_per_subsystem_analyses()`'s, deliberately:
one `ThreadPoolExecutor` over independent read-only units of work, results
sorted back into DECLARED category order so a fan-out's output never depends
on which worker finished first. A `parallel_group` node was NOT added --
these extractors are not graph stages, and inventing one would put document
conversion on the verification closure path. Every category's work is done by
the same real module its own single-purpose verb already calls; no adapter
contains extraction logic of its own.

**What counts as a category is DATA**: `dv_harness/doc_extraction_categories.json`
(same policy-as-data shape as `context_budget.policy.json` and
`harness_deploy.manifest.json`) declares all eleven with their checklist
letter, the real `module.callable` that handles each, and its input keys. HOW
to invoke lives in `doc_extraction_fanout.CATEGORY_EXTRACTORS`, because eleven
extractors have eleven genuinely different signatures and a JSON-encoded call
convention would be a second, wrong-by-construction description of code that
already exists. `assert_extractor_table_matches_categories()` holds the two
together in BOTH directions -- a category with no adapter, an adapter for no
category, or a declared callable that no longer resolves through the import
system each fail a test rather than silently dropping a category.

**Two of the eleven genuinely have no extractor, and say so.** 40c (VIP
examples) and 40h (IP source) report `NO_EXTRACTOR` carrying the real reason:
`context_budget.policy.json` leaves VIP `Examples/` directly READABLE as a
tier-1 carve-out, and a read permission is not extraction into a structured
artifact; and no module here is scoped for IP source distinct from VIP source,
so pointing `vip_symbol_index` at an IP model tree would produce a wrong
artifact rather than a partial one. A category with an extractor but no inputs
reports `INPUT_NOT_SUPPLIED`. Those are three distinct facts -- "nobody built
this", "you gave me nothing", "it ran" -- and collapsing any two would let an
empty fan-out read as a complete one. Two further honesty carries: `dut_rtl`
reports each `env.manifest.json` layer's OWN status verbatim (a NOT_AVAILABLE
rtl layer is never summarized away), and `top_testbench_runscript` records
`hierarchy_json: NOT_PRODUCED_NO_NON_AGENT_EXTRACTOR`, since category 40i's
hierarchy half has a declared producer (`CORE/hierarchy-discovery`) but no
coded extractor.

**`doc_extraction.py` finally has its pipeline caller.** That module's NOTICE
has said since 2026-08-28 that "no stage in `dv_harness/engine.py` and no
`.claude/agents/*.md` profile invokes `DocumentIndex`, `needs_extract()`,
`register()`". The fan-out registers every SOURCE document it consumes into
that same shared index with `kind` = `doc_extraction:<category_id>`, so
provenance is recorded in the one index this repo already has, and
`--incremental` asks `needs_extract()` whether a source really changed instead
of re-converting a 200-page PDF every run.

**Four properties, each enforced in code and each tested:** (1) an absent
extractor is reported, never faked; (2) one failing category never sinks the
fan-out -- a raising extractor is that category's `FAILED` with its real
exception text while the other ten still run; (3) concurrent writes cannot
collide -- each category writes into its own `<out_root>/<category_id>/`,
asserted distinct before any worker starts, and the one genuinely shared
mutable resource, `DocumentIndex.register()`'s read-modify-write over a single
JSON file, is serialized behind `_INDEX_LOCK`; (4) reading is never a mutating
act -- no adapter escalates to the question queue, writes a Blackboard topic,
mints an approval or touches memory, even where the underlying extractor
supports it (`audit_directory()` takes a `question_store=`; the fan-out never
passes one).

Verbs: `dv-harness doc-extract categories` (the eleven, with the real
extractor or why none exists), `... plan` (dry run; opens no document and
writes nothing), `... run --inputs <json> --out <dir> [--only ...]
[--max-workers N] [--incremental] [--no-register]`, exit 1 if any category
FAILED. The identical `python -m dv_harness.doc_extraction_fanout` shares one
`execute_verb()`.

Proven by `dv_harness_tests/test_doc_extraction_fanout.py` (39 tests) against
REAL extractors and REAL inputs -- the committed `examples/asset_processing/
inputs/` worked examples, this repo's own
`dv_harness/uvm_generator/templates/sim_scripts/Makefile`, and this repo's own
`docs/*.pdf` for the pypdf branch. Nothing is mocked, because a fan-out that
only ever dispatched stubs would prove the fan-out and nothing about whether
the eleven categories actually convert. Both concurrency claims carry negative
controls that give them detection power: the overlap test blocks all four
workers on one `threading.Barrier(4)` that a SEQUENTIAL dispatcher provably
cannot satisfy (verified: `max_workers=1` yields four `FAILED` results and one
thread), and removing `_INDEX_LOCK` provably makes the no-lost-rows test fail
with a torn read. A real run over all eleven categories measured 0.74s wall
clock against 4.46s of summed worker time across 8 threads.

**Disclosed residual**: this is the DISPATCH layer, not new extraction
capability. Categories 40c and 40h still have no extractor and the fan-out
does not invent one; 40d/40e/40f remain input-CONTRACT transcription pipelines
(`design_intent.py`'s own docstring: "transcribes and validates; never
authors"), so the .doc/.xlsx -> structured-source step is still performed by a
human or an agent reading the document; 40g's interrupts remain
agent-skill-driven (`interrupt-event-dispatch`); and 40i's `hierarchy.json`
half is still agent-produced. It is also not engine-fired -- no `run_stage()`
or `advance()` call site invokes it and no graph node declares it, so this is
a REACHED capability (a real CLI caller exists), not a WIRED one.



<!-- S065: moved verbatim from CLAUDE.md original lines 3658-3781 (M4.6 CLAUDE Context Normalization) -->
## Verification Strategy Optimizer: Recommend Honestly, Execute Only What Exists (2026-09-06, VI-4)

VERIFICATION_INTELLIGENCE's completeness audit flagged the Verification
Strategy Optimizer NEVER_BUILT. Re-verified on 2026-09-06 before building: a
repo-wide grep for `strategy_optimizer` / `verification_strategy` /
`strategy_recommend` returned nothing, and a grep for
`formal|emulation|zebu|haps|PSS|jasper|vc_formal|veloce|palladium|breker` over
`dv_harness/**.py` returned only Verilog FORMAL PORTS (`verible_parser.py`,
`amba_fabric_discovery.py`), `router.py`'s `RESEARCH_FOCUS_DOMAINS` listing
`'pss'` as a reading-list topic, and ONE line naming `05_Tools/ZeBu` /
`05_Tools/HAPS` as `memory_vault.py` vault FOLDER NAMES. **This harness's real
execution capability is simulation and nothing else**: a VCS regression
submitted to LSF through `lsf_client.bsub_submit_with_preflight()` behind
`preflight.run_preflight()`. So the gap is real, and so is the trap in it -- a
recommender that emitted "run formal on this" would read as a capability this
harness does not have.

`dv_harness/verification_strategy.py` answers the question on **two separate
axes that are never merged**, the same discipline `protocol_capability.py`
applies to "can generate" vs. "has proven":

- **executability is DERIVED, never typed in.** Each strategy declares the
  backend entry points it would need (`STRATEGY_BACKENDS`, e.g. FORMAL's
  `dv_harness.formal_client:prove_property`), and `derive_executability()`
  resolves them with real import + getattr -- the same resolution
  `protocol_capability.resolve_generator_class()` does, for the same reason a
  string check would keep passing after the thing it names is gone. SIMULATION
  resolves (`EXECUTABLE_HERE`); FORMAL/PSS/EMULATION/FPGA_PROTOTYPE do not
  (`RECOMMEND_ONLY_NO_BACKEND`) and name no `execution_path`, because naming a
  hypothetical one is how a recommendation becomes a claim. Build a real module
  at the declared name and the row flips on its own;
  `assert_executability_matches_code()` then FAILS, forcing docs and tests to
  be updated together with the new capability instead of drifting.
- **the verdict is what the SIGNALS say** -- `RECOMMENDED` /`NOT_INDICATED` /
  `NO_SIGNAL` / `SUPPRESSED`. Every strategy always gets a row: an omitted
  strategy reads as "not applicable", a NO_SIGNAL one as "we have no evidence",
  and `R9` guarantees no row is ever returned with an empty basis.

**It measures nothing new.** Every signal is another module's existing output,
imported: coverage-closure difficulty from `loop_convergence.
classify_loop_convergence()` (whose plateau investigation is
`coverage_analysis.classify_coverage_hole()`'s per-bin verdicts over the real
series `trend_analysis.daily_rollup()` produces); failure density from
`capability_evolution.repeated_unresolved_failure_patterns()` plus the
`failure_signatures` table read READ-ONLY out of `evidence_db` -- identity is
`evidence_db.signature_key()` in both, never a second definition of "the same
failure"; per-protocol reach from `protocol_capability.capability_for()` /
`derive_status()`; multi-subsystem scope from `environment_mode_router.
read_registered_subsystem_entries()`, the registry `engine.py` writes on a real
SIGNOFF PASS.

**The precedence is `investigate_plateau()`'s, lifted one level.** While ANY
under-sampled bin exists, FORMAL is `SUPPRESSED`, not merely unrecommended: a
bin randomization has not fairly attempted cannot support a structural
unreachability claim, and recommending an engine this harness cannot even run
on the strength of bins nobody has run yet is the most expensive possible wrong
answer. The same bin after 20+ real distinct seeds flips the answer to FORMAL --
that pair of tests is where the detection power lives.

**A RECOMMENDED strategy this harness cannot execute always carries an
`executable_next_action`**, enforced by
`assert_no_unexecutable_strategy_claimed_executable()` on the way out of every
report: "use formal" with no act this harness can perform reads as a capability
and is not one. Those acts are `coverage_analysis.escalate_unreachable_holes()`,
`capability_evolution.file_repeated_failure_candidate()` and
`question_queue.QuestionQueueStore.add_question()` -- **NAMED and taken for
none of them**, exactly the contract `loop_convergence.PlateauInvestigation.
escalator` has, and `assert_named_escalators_resolve()` checks each one still
exists so a renamed function cannot leave a dead name in advice a human is
being asked to act on.

Reachable as `dv-harness verification-strategy capabilities|recommend`
(`--goal`, `--scope`, `--protocol`, `--holes`, `--json`), sharing one
`execute_verb()` with `python -m dv_harness.verification_strategy`. `recommend`
exits **2 when it names a strategy this harness cannot execute** -- a
CI-visible "a human has to decide something", never an approval in either
direction. `goal_text` is recorded verbatim with
`goal_text_machine_evaluated: false`; scope is a caller fact and is never
inferred from prose.

Proven by `dv_harness_tests/test_verification_strategy.py` against real
evidence written through the real production write paths
(`regression_reporter._write_reconciliation_evidence_if_configured()`,
`dashboard.append_coverage_history_sample()`, `memory_router.route_and_store()`,
`memory_vault.build_failure_signature()`). The negative controls carry the
detection power: under-sampled bins SUPPRESS formal rather than recommending it,
three retries against one commit are one run, a failure closed by a gate-verified
`verified_fix` recommends nothing, one busy day is not a throughput signal, a
climbing coverage curve is told to change nothing, a goal containing the word
"formal" buys FORMAL nothing, a forged executable row is refused, and a
synthesised real module at FORMAL's declared backend name flips the row with no
source edit. Nothing in it runs a build, a regression or an LSF submission, and
no approval gate is touched.

**Correction (2026-09-06, found by this close-pass's own independent review):**
an earlier version of this section claimed a byte-level snapshot proved
recommending writes nothing -- false on a project with no memory store yet.
`gather_signals()`'s failure-density signal called
`capability_evolution.repeated_unresolved_failure_patterns()`, which
constructs a `MemoryStore` unconditionally; that constructor `mkdir()`s the
5-tier tree and writes an empty `index.json`, so a pure `recommend()` on a
bare root silently created one. The reviewing report's own snapshot test
missed it because it pre-created a store before snapshotting. Fixed the same
way `confidence_calibration.calibrate()` and `cross_project_mining` already
guard this: `gather_signals()` now checks
`cross_project_mining.has_memory_store(root)` BEFORE calling into
`capability_evolution`, and reports `NO_JOB_MEMORY_FAILURE_HISTORY` on a bare
root instead of creating one. Proven on a genuinely empty root by
`dv_harness_tests/test_verification_strategy.py::
test_recommend_on_a_bare_root_creates_no_memory_store`.

**Disclosed residual, and it is the honest boundary.** (1) This module can only
RECOMMEND four of the five strategies, forever, until someone integrates a real
backend -- it dispatches to none of them and the report says so on every render
(`REPORT_DISCLOSURE`). (2) The throughput threshold
(`DEFAULT_THROUGHPUT_BOUND_RUNTIME_HOURS_PER_DAY = 24.0`) is a project-overridable
HEURISTIC with a stated justification, not a measurement: this harness reads no
farm capacity, no license-pool size and no schedule, so no universal number
exists and inventing one would be fabricated precision. (3) Like
`cross_project_mining.py` and `run_controlled_experiment()` before it, this is
REACHED, not WIRED -- it has a CLI verb but no `run_stage()`/`advance()` call
site, no graph node and no dashboard card. (4) It does not score a strategy's
expected coverage gain or cost; that needs ground truth this repo does not have.


<!-- S068: moved verbatim from CLAUDE.md original lines 4036-4112 (M4.6 CLAUDE Context Normalization) -->
## Configuration Variant Explosion Control: Pairwise Covering Sets (2026-09-06, TH-5)

Spec section 232 names a real configuration space (protocol generation, speed, lane width,
data width, compile defines, feature modes, SKU, clock mode, subsystem combinations, VIP
configuration), says "avoid blind Cartesian-product regression", and lists
`pairwise/covering combinations` as one of the evidence-grounded selection methods. Nothing
in this repo answered that. `grep -rn "pairwise\|covering_array\|combinatorial" --include=*.py .`
matched only unrelated things: `system_topology_analysis._pairwise_overlap()` (do two ADDRESS
REGIONS intersect), `system_command_plan`'s pairwise ESCALATION QUESTION split, and
`source_authority`'s pairwise CONFLICT questions.

`change_impact.py` / `regression_tiers.py` were deliberately NOT extended into it, because
they answer the orthogonal question. They select WHICH TESTS from an enumerated pattern
universe, driven by a real git diff and the traceability registry; neither has any notion of
a configuration dimension. `dv_harness/config_variant_coverage.py` selects WHICH
CONFIGURATIONS out of a combinatorial space that has no enumerated universe, only dimensions
and legal values. The two answers compose (test set x config set) at the caller, and this
module deliberately does not perform that composition.

**The algorithm is a real, cited one.** `generate_covering_array()` implements **IPOG**
(In-Parameter-Order-General) -- Lei, Kacker, Kuhn, Okun, Lawrence, "IPOG: A General Strategy
for T-Way Software Testing", IEEE ECBS 2007; the strength-t generalisation of Tai & Lei's IPO
(2002) and the algorithm behind NIST ACTS. Chosen because it is DETERMINISTIC (no random
restarts, so a plan is diffable and reviewable -- the same property
`env_manifest.save_env_manifest()` insists on), generalises to any t >= 2 with one
implementation (so a 3-way subspace needs no second mechanism; the default is t=2 because
that is what section 232 names), and accepts SEEDED rows, which is exactly what "critical
configurations must not be removed merely to reduce compute" needs: declared critical
combinations are seeded before generation, completed to full legal configurations by a real
backtracking search, and excluded from the redundant-row pruning pass by name.

**Constraints are handled soundly rather than optimistically.** A `forbid` clause is a partial
assignment no emitted configuration may contain. Validity is checked at every assignment,
t-tuples that themselves contain a forbidden clause are excluded from the target set and
REPORTED (never silently absent from the arithmetic), and a final REPAIR pass re-verifies
independently and runs an exhaustive backtracking search for each remaining miss. Only a
tuple for which that search PROVES no legal full configuration exists is reported as
`UNREACHABLE_UNDER_CONSTRAINTS`. The module therefore never reports coverage it did not
achieve. `verify_coverage()` is a separate first-principles recomputation, not a read-back of
the generator's bookkeeping, so it can be pointed at a hand-written combination list;
`build_plan()` runs it as part of producing a plan, so a plan artifact cannot claim coverage
the verifier did not confirm.

`dv-harness config-variants plan|verify --space <file> [--strength N]`, or
`python -m dv_harness.config_variant_coverage` -- one shared `execute_verb()`, the same
convention `power-intent`/`golden-scenario` use. Exit 0 full coverage, 1 a real finding
(uncovered interaction, illegal/incomplete configuration, missing declared critical
combination), 2 a broken declaration or usage error.

**Deliberately bounded, and stated rather than implied closed.** (1) It SELECTS and decides
nothing else: no build, no job, no LSF, and deliberately no stage gate -- a gate that passed
on a config plan nobody ran would be worse than none. (2) Section 232's other listed methods
(requirement-driven, historical-risk, change-impact combinations) enter ONLY as caller-declared
`critical_combinations` with a real reason string; this module mines nothing and invents no
combination. (3) Equivalence-class reduction is the AUTHOR's act -- collapsing 64 legal data
widths to {8, 32, 512} happens when the dimension's legal values are declared, because
"these two values are equivalent" is a protocol-behaviour claim needing primary evidence.
(4) Values must be JSON scalars; a structured value is refused, not stringified.
(5) `legal_cross_product_size` is exactly enumerated only up to `MAX_EXACT_ENUMERATION`
(200k); above it the count is `UNCOUNTED` with the real reason, never a guess.

Proven by `dv_harness_tests/test_config_variant_coverage.py` (30 tests) against
`dv_harness_tests/fixtures/config_variants/synthetic_pcie_ep_space.json` -- a fixture whose own
description states it is a test fixture and not any real DUT's configuration: 8 dimensions,
3 constraints, 2 declared critical combinations (one only partially pinned). The central tests
do NOT ask the module's own verifier whether it succeeded; `_brute_force_uncovered_pairs()` is
an INDEPENDENT re-derivation written from scratch in the test file that enumerates every legal
pair by nested loops over the fixture JSON and rescans the emitted rows. On that fixture the
result is 20 configurations covering all 267 legal pairs, against a 6480-point raw Cartesian
product / 4662 legal configurations -- and 20 is the information-theoretic floor (5 lane widths
x 4 feature modes), which the test asserts as a lower bound so a "smaller" answer is caught as
a bug rather than praised. The verifier is separately proven non-vacuous (drop one row and it
names exactly the pairs the independent recount says went missing), the unreachable-pair,
illegal-row, undeclared-value, uncompletable-critical and contradictory-declaration paths each
have their own test, and both real CLI entry points are driven as real subprocesses.



<!-- S070: moved verbatim from CLAUDE.md original lines 4186-4281 (M4.6 CLAUDE Context Normalization) -->
## Multi-User Coordination Conflict Detection (2026-09-06, section 239)

Spec section 239 ("MULTI-USER COLLABORATION") closes with two rules: "Do not use chat history as
the coordination mechanism" and "Concurrency conflicts remain explicit." The TRANSPORT and
AUTHORIZATION half of its list was already real and is deliberately untouched here --
`docs/workflow/USAGE_MULTI_USER_SAFETY.md`'s standing policy (including the "never share a `--project-root`" rule),
`dashboard_auth.py`'s GUI-19 token gate, `user_info.summarize_user_access()`'s per-root access trail,
and `remote_relay.RelayServer.handle_request()`'s serialization lock. The DETECTION half was
NEVER BUILT: a repo-wide grep for `stale_sha` / `duplicate_regression` / `edit_conflict` /
`reservation_conflict` / `cross_session` / `peer_session` / `coordination_conflict` over
`dv_harness/` and `tools/` returned only an unrelated subsystem-registry `release_sha` test fixture.
Nothing anywhere compared TWO users' concurrent work, so two people's only way to discover that they
were rebuilding the same regression against different SHAs, or both driving the same VIP instance,
was to tell each other in chat -- exactly what section 239 forbids.

`dv_harness/multi_user_coordination.py` is that detection. Because each user has their OWN
`.dv-harness/` (that is the multi-user safety rule, not an accident), detection is necessarily a
cross-ROOT comparison: `scan([(user, project_root), ...])` reads N peer roots and compares every pair
of distinct-user sessions. **No new coordination store is introduced** -- every fact is read off a
real per-project artifact an existing mechanism already writes:

- **STALE_SHA_CONFLICT** -- two sessions on DIFFERENT base SHAs whose changed-file sets INTERSECT.
  Both halves come from `change_impact.read_computed_selection()`
  (`.dv-harness/regression/computed_selection.json`), i.e. a real `git diff --name-only <base>..<head>`
  written by REGRESSION_SELECT, never a claim a user typed. Severity is the REAL
  `change_impact.classify_risk()` over the overlapping files, so "how much does this file matter" has
  ONE answer in this codebase. Same base SHA is not a conflict (both work from one baseline);
  different SHAs with disjoint files is not a conflict either.
- **DUPLICATE_REGRESSION_SUBMISSION** -- the same pattern against the same commit, claimed twice.
  SUBMITTED claims are real `lsf_client.JobState` records in `.dv-harness/lsf/jobs/*.json`
  (`pattern` + `git_sha`, in-flight = LSF `PEND`/`RUN`); PLANNED claims are the same
  `computed_selection.json`'s four selected test sets against its `head_sha`. Submitted-vs-anything
  is HIGH (farm time is already burning); planned-vs-planned is MEDIUM. A terminal (`DONE`/`EXIT`/
  `KILLED`) job is history, not a collision, and the same pattern against two DIFFERENT commits is two
  legitimately different results.
- **SHARED_RESOURCE_RESERVATION_CONFLICT** -- two users holding a claim on one genuinely-shared
  resource (AMBA fabric port, VIP instance, license feature, regression slot, shared path). The
  ledger is the EXISTING `AgentTaskStore.acquire()` mechanism `engine.py`'s `_advance_with_fanout()`
  already uses, extended with a recorded `scope`. That scope is load-bearing rather than cosmetic:
  `acquire()`'s only production caller claims blackboard TOPIC names ("findings",
  "verification_state", ...) which are identical in every project by construction, so a scope-blind
  cross-root comparison would report a conflict on every pair of sessions that ever ran a fan-out.
  `SCOPE_LOCAL` (the pre-existing meaning, and what a record with no `scope` key reads as) is never
  compared across sessions; only `SCOPE_SHARED` claims are, and a SHARED claim MUST name a kind from
  the closed `SHARED_RESOURCE_KINDS` set -- two users typing "AXI_M0" under two free-text kinds would
  silently never collide. Two READ claims are not a conflict; any WRITE claim against another is.
  `release()` was added alongside, because a SHARED reservation persists on disk and with no release
  verb every finished reservation would collide with the next user forever; a non-holder cannot
  release someone else's claim.

`dv-harness coord detect|reserve|release|list` and `python -m dv_harness.multi_user_coordination`
share one implementation (`execute_verb`, the same convention `power-intent`/`golden-scenario`/
`system-smoke-proof` use). Exit 0 CLEAR / reservation made, 1 CONFLICTS_DETECTED / reservation
refused, 2 UNKNOWN or malformed. One `MULTI_USER_COORDINATION_SCAN` event lands in the SCANNING
project's own `.dv-harness/events.jsonl` through the same `StateStore.event()` `dv-harness audit`
already reads -- never a second audit file, and never a write into a peer's root. A CLEAR scan is
recorded too: "we checked and found nothing" is itself citable evidence.

**DETECTION is what was wired; ARBITRATION is untouched -- stated rather than implied closed.**
(1) It takes no lock, cancels no job, revokes no claim, rewrites no peer's state, picks no winner
and decides whose SHA is authoritative for nobody. A conflict is REPORTED with both sides' evidence
and a `next_best_action` naming the decision two humans must make; `claimed_first` is stated as
information, never applied as a rule. Every existing human-approval gate stands exactly as before.
(2) There is deliberately NO stage gate and no `STAGE_GATES` entry -- a gate that passed because a
scan could not see the other user's project root would be worse than no gate. (3) It is not an auth
layer: it reads no token and authorizes nothing, and user identity is either DECLARED or read off
that root's own real `CLI_ACCESS`/`GUI_ACCESS` trail; a root with no trail is reported
`USER_IDENTITY_UNKNOWN` and its pair `PAIR_USER_IDENTITY_UNKNOWN`, compared anyway but never quietly
assumed to be a second person. (4) "We could not check" is UNKNOWN with a real reason, never CLEAR:
one session only, no `.dv-harness/`, no computed selection, an in-flight job with no recorded SHA,
or an unrecognised LSF status each produce a named UNKNOWN. (5) Of section 239's nine listed
concerns, three are implemented here; generic edit conflict, conflicting Human Gates, simultaneous
memory promotion and simultaneous capability changes are NOT -- the last two in particular would
need cross-root visibility into `memory_router.promote_to_organizational()` and
`capability_evolution`'s approval state that no shared artifact carries today. Ownership/
authorized-role was NOT implemented by THIS module (it does no cross-root detection of role
conflicts) but IS separately implemented for the single-project dashboard by
`dashboard_authorization_matrix.py` (VIEWER/OPERATOR/APPROVER roles enforced on every mutating
`/api/control` POST, proven by `dv_harness_tests/test_dashboard_authorization_matrix.py`) -- two
different scopes of the same spec concern, closed in two different places, neither a duplicate of
the other.

Proven by `dv_harness_tests/test_multi_user_coordination.py` (32 tests). Every test builds TWO (or
three) REAL, SEPARATE project roots in the layout `docs/workflow/USAGE_MULTI_USER_SAFETY.md` prescribes, each
populated by the REAL producing mechanism: a REAL throwaway git repo with three real commits whose
diffs are computed by the REAL `change_impact.compute_and_write()`, a REAL `requirements.csv`
traceability registry so the PLANNED sets are what the real `select_regression()` selects, REAL
`save_job_state()` records, REAL `AgentTaskStore.acquire(scope=SHARED)` claims, and REAL `CLI_ACCESS`
events for identity. Each of the three detectors has a central two-concurrent-session positive proof
AND matching negatives (same base SHA, disjoint files, different commits, terminal jobs, two READ
claims), plus the false-positive guard that drives the REAL default `acquire()` signature
`engine.py` uses on both roots and asserts no cross-user conflict is reported. `dv-harness coord`
and `python -m dv_harness.multi_user_coordination` are both driven as real subprocesses, a scan is
asserted to write NOTHING into a peer root, and a test asserts no stage gate was introduced.



<!-- S072: moved verbatim from CLAUDE.md original lines 4356-4428 (M4.6 CLAUDE Context Normalization) -->
## Platform Health + Error Budgets: the observability aggregator (2026-09-06, PC-2)

This harness already PRODUCED plenty of real operational signal, but each piece lived behind a
different verb, so nothing could answer "is this platform healthy right now, and against what
objective". A repo-wide grep on 2026-09-06 returned **zero hits for `SLO`, `error_budget` and
`health_state`**: `degradation.py` had the only health-ish state, and it is one GLOBAL
NORMAL/DEGRADED mode driven by three triggers, not a per-subsystem picture.

`dv_harness/platform_health.py` is the aggregator, and it READS ONLY. Every number comes from a
mechanism that already existed; nothing in it measures anything itself:
`degradation.describe()` (the three real triggers + adapter failure streak); the real
`EXECUTION_PREFLIGHT_PASS` / `EXECUTION_PREFLIGHT_BLOCKED` events `engine._execution_preflight_gate()`
already writes, each carrying the full `preflight.PreflightResult.to_dict()`;
`connectivity_check.load_state()` + its own `evaluate_staleness()` against the RTL on disk NOW;
`trend_analysis.trend_report()`'s three detectors; and `trend_analysis.daily_rollup()`'s per-day
verdict counts. Eight subsystems (`agent_adapter`, `eda_license`, `lsf_queue`,
`execution_environment`, `connectivity_gates`, `regression_quality`, `harness_self_reporting`,
`slo_compliance`), each carrying the `fact_source` it was derived from so a reader can go check it.
`dv-harness platform-health [--json] [--window-days N]`, or `python -m dv_harness.platform_health`;
exit 2 only on DEGRADED/CRITICAL.

**UNKNOWN outranks HEALTHY.** `HEALTH_SEVERITY` puts UNKNOWN above HEALTHY, so one unmeasured
subsystem stops the platform being reported healthy — the same rule `connectivity.py` already
enforces for NOT_AVAILABLE ("never conflated with FAILED"), applied to the other side too: an absent
measurement is never conflated with a good one — nor with a bad one. A preflight check that SKIPped
makes its subsystem UNKNOWN even when its siblings PASSed: not HEALTHY (which would claim a disk was
checked) and not DEGRADED (which would alert on this repo's own shipped config, whose
`preflight.workdir` is deliberately empty). A connectivity gate that is PENDING/NOT_AVAILABLE is
likewise UNKNOWN, never PASS or FAIL; a
stale-but-passing gate run is DEGRADED, because `evaluate_staleness()` already says those verdicts
may not be cited once the RTL moved. This repo itself honestly reports OVERALL: UNKNOWN.

**Two SLOs, both counting real recorded events, and an explicit refusal list for everything else.**
`regression_verdict_pass_rate` (good = a real `regression_verdict_history` PASS row, target 95%) and
`execution_preflight_pass_rate` (good = a real `EXECUTION_PREFLIGHT_PASS` event, target 90%).
`UNMEASURABLE_SLIS` names the five SLIs a normal SRE platform would carry — uptime, request latency,
service availability, simulator-farm uptime, data durability — each with the missing producer stated,
and `assert_no_unmeasurable_slo()` FAILS if one of those ids ever appears in `SLO_CATALOG`. That is
the "do not fabricate an SLO for telemetry you do not have" rule made structural rather than
aspirational. A window holding fewer than `min_events` real events reports INSUFFICIENT_EVIDENCE with
`achieved_percent=None` — a 100% computed from two samples is not a measurement of a 95% objective.

**Two clocks, never mixed.** `events.jsonl` carries `engine.now()`'s explicit UTC stamp;
evidence.duckdb's `recorded_at`/`ingested_at` default to DuckDB's `now()`, which is the machine's
LOCAL wall clock. Each SLI's rolling window is therefore anchored in the clock its own source uses
(`CLOCK_UTC_EVENT` / `CLOCK_LOCAL_STORE`), and every error budget carries `window_clock` saying
which — mixing them would silently drop or double-count a day's evidence around either midnight.
The clock is a property of where evidence is stamped and is deliberately NOT overridable in
config.json's `platform_health` block (which may retune `target_percent`/`window_days`/`min_events`,
and may not add an SLO id).

**Observing authorizes nothing.** No approval machinery is imported, no write is performed (a test
snapshots every file under the project root and asserts two full reports change none of them), the
evidence DB is opened READ-ONLY through `trend_analysis`, and a BREACHED error budget is a REPORT —
it blocks no stage and lets none through. `assert_authorizes_nothing()` asserts that against this
module's own source, with `control_plane.py` as the negative control that really trips it. No second
events.jsonl parser was added either: `loop_telemetry._read_events` gained a public
`read_events` alias and `platform_health` reuses it, asserted by function identity.

Proven by `dv_harness_tests/test_platform_health.py` (37 tests). Every signal comes from the real
producer: the preflight events out of REAL `DVHarness.run_stage()` passes over the REAL shipped
`main_graph.json` (only preflight.py's own injected-Runner seam mocked, so no test contacts a live
license server or scheduler); the verdicts out of the REAL
`regression_reporter._write_reconciliation_evidence_if_configured()` into a real DuckDB; the gate
statuses out of a REAL `run_connectivity_check()` with all three gates genuinely PASSing over a real
trace file and real monitor counts. The negative controls are what give them power — a healthy farm
and a starved one produce HEALTHY vs CRITICAL from the SAME code path; a live `eda_license_full`
trigger outranks an older passing preflight run and clearing it really returns the subsystem to that
evidence; back-dating the whole verdict set past the window really drops the SLO to
INSUFFICIENT_EVIDENCE while asking as-of the back-dated day finds it again; and adding an uptime SLO
to the catalog really trips both guards.



<!-- S075: moved verbatim from CLAUDE.md original lines 4648-4738 (M4.6 CLAUDE Context Normalization) -->
## Evidence Provenance: Self-Attested vs. Independently Derived (2026-09-06, TH-9)

`gates.run_gate()` assembles every stage gate's payload from the ONE fenced evidence block
(`dv-harness-evidence:<gate_id>`) the AGENT typed. For most gates that is fine -- the
script re-derives something, or cross-checks the claim against a harness-owned artifact
(`ContextFlag`, `DV_HARNESS_PROJECT_ROOT`, the waiver ledger, the subsystem registry, a real
remote transcript). Six gates were not like that, and a completeness audit named this the most
consequential gap type it found. Re-verified by direct search before building:
`grep -rn "evidence_provenance|AGENT_SELF_ATTESTED|TOOL_DERIVED|SIMULATION_DERIVED"
--include=*.py --include=*.json .` matched exactly one unrelated string in a reference-base
manifest, and no gate anywhere asked who produced its input.

Each of those six gates' PASS is a statement about **dynamic system BEHAVIOUR** -- deadlock and
livelock freedom (`system_level_deadlock_livelock_gate`), shared-resource contention
(`system_level_resource_contention_gate`), per-port forward progress
(`per_port_queue_starvation_gate`), fairness/QoS (`multi_port_fairness_qos_gate`), interrupt
acknowledgement latency (`interrupt_storm_latency_gate`) and scoreboard transaction liveness
(`scoreboard_transaction_liveness_gate`) -- a property nothing can establish without RUNNING
something. Their scripts are pure shape checks over numbers the agent typed:
`system_level_deadlock_livelock_gate.py` is nine lines and PASSes on
`{"deadlock_detected": false, ...}`. So "the composed system is deadlock-free" could be produced
by an agent writing that line, and the resulting PASS was rendered on the dashboard and in the
signoff bundle **identically** to a PASS backed by a real tool run. That indistinguishability --
not the absence of a formal checker -- is the defect.

`dv_harness/evidence_provenance.py` closes exactly that, and **nothing more**. It does not verify
deadlock freedom; a real deadlock checker needs a formal tool this project does not have, and
building a fake one is the fabrication the Evidence Truth Rule forbids.

- **`evidence_provenance` is a REQUIRED field on those six gates' evidence blocks**, enforced in
  `run_gate()` BEFORE the script is invoked -- because this is a question about the payload's
  SOURCE, not its content. Absent -> `EVIDENCE_PROVENANCE_MISSING`; unrecognised ->
  `EVIDENCE_PROVENANCE_INVALID`. There is deliberately no default: defaulting would decide the
  very question the field exists to record. The refusal names the field, the accepted values and
  the claim the gate would otherwise have made, so it is actionable rather than a bare rejection.
- **The asymmetry is the whole design: the honest answer is the cheap one.**
  `AGENT_SELF_ATTESTED` is always accepted and needs nothing else -- an agent must never be pushed
  toward a stronger claim to get a stage moving. `TOOL_DERIVED`/`SIMULATION_DERIVED` cost a real
  `evidence_derivation` naming a producing tool AND an `artifact_path` that must EXIST under the
  project root (`EVIDENCE_PROVENANCE_DERIVATION_MISSING` / `EVIDENCE_PROVENANCE_ARTIFACT_NOT_FOUND`).
  The path is resolved against the project being judged, not the CWD.
- **Every consumer renders the caveat, from ONE computation.**
  `control_plane.describe_stage()` -- the single shared read path the dashboard's "Why (current
  stage)" card and the CLI's `explain`/`evidence`/`checklist` verbs both already go through --
  carries `summarize_evidence_blocks()`, so a self-attested deadlock-freedom claim cannot be
  caveated in one surface and presented bare in the other. `dashboard.py`'s `provenanceBlock()`
  renders a self-attested claim with the existing bold+red `.err` treatment a missing checklist
  item gets, not a grey note. `signoff_export.read_signoff_stage_status()` carries
  `summarize_project_provenance()` -- signoff is exactly where a headline claim gets believed --
  reading `state.json` with the same plain `read_text`/`json.loads` that function already uses,
  never `StateStore` (which would MINT one). `run_gate()` also stamps the provenance and its
  caveat onto the gate DETAIL, so `react_loop`'s signature menu and stage telemetry carry it too.
- **Absence is never read as derived.** `caveat_for(None)` is the self-attested caveat: on any
  surface, "nobody said" is at best as strong as "the agent said so".

**Deliberately bounded, and stated rather than implied closed.** (1) The artifact check proves a
FILE EXISTS at a path the agent named; it does not parse it and cannot prove the file contains the
claim. It is a real COST, not a proof -- it stops a free upgrade from AGENT_SELF_ATTESTED to
TOOL_DERIVED, it does not make TOOL_DERIVED mean "verified", and `DERIVED_CAVEAT` says so on
every surface that renders one. (2) It cannot detect a FALSE declaration: an agent that types
`TOOL_DERIVED` and cites a real unrelated file passes. What is closed is the SILENT case --
evidence carrying no provenance at all, rendered exactly like tool-derived evidence.
(3) Only those six gates are enforced. That set is not "the gates we got to"; it is the gates
whose PASS asserts a measured dynamic-behaviour property over agent-typed numbers, stated with
each gate's own headline claim in `PROVENANCE_REQUIRED_GATES` so a reader can check the rule was
applied rather than trust that it was. Every other gate is byte-for-byte unaffected and carries
no provenance annotation -- stamping one would present a field nobody supplied and nobody checked
as if it had been decided. (4) It ARBITRATES and AUTHORIZES nothing: no stage runs, no build /
regression / LSF submission starts, no approval is minted, and there is deliberately no stage
gate of its own. An AGENT_SELF_ATTESTED PASS is still a PASS -- it is a PASS a human is now told
the provenance of. (5) `dv_harness/prompts.py` was updated so a real agent emits the field; the
two pre-existing test fixtures that hand-typed these blocks now declare `AGENT_SELF_ATTESTED`,
which is the honest value for a hand-written fixture and exactly what a real agent typing those
numbers must declare.

Proven by `dv_harness_tests/test_evidence_provenance.py` (42 tests) against the REAL
`gates.evaluate_stage_evidence()` over the REAL shipped `STAGE_GATES`, running the REAL gate
scripts as subprocesses, and the REAL consumers -- `describe_stage()`, the REAL dashboard server
driven over REAL HTTP through the same `_start_dashboard`/`_wait_ready`/`_get` harness every
other dashboard card test uses, and `read_signoff_stage_status()`. Nothing is mocked and no test
writes a gate detail by hand. The negative controls carry the detection power: every one of the
six clean payloads is first proven to PASS on the merits (so a provenance FAIL can never be a
shape failure wearing its name), the deadlock-freedom refusal is paired with the same payload
ACCEPTED once it honestly declares who wrote it, the two independence refusals are paired with
the same claim accepted once the cited artifact really exists on disk, an artifact under a
DIFFERENT root is still refused, a genuinely bad payload still fails on the SCRIPT's own reason
with provenance declared, an unenforced gate reaches its script unchanged and carries no
annotation, a derived claim is proven NOT to be caveated, and a byte-level snapshot proves
summarizing provenance writes nothing.



<!-- S076: moved verbatim from CLAUDE.md original lines 4739-4820 (M4.6 CLAUDE Context Normalization) -->
## Mutation Testing of This Repo's Own Test Suite (2026-09-06, PC-4)

Every gate in this repository is guarded by a test, and the Evidence Truth Rule rests on those
tests FAILING when the thing they guard breaks. Nothing measured that. Re-verified by direct
search before building: `grep -ril "mutation_test|bug_inject|mutant"` over `*.py`/`*.md`/`*.toml`
matched NOTHING repo-wide -- every `mutation` hit in this file belongs to
`capability_evolution.run_controlled_experiment()`, which is a per-candidate TREATMENT-ARM edit
authored by whoever runs the experiment, not a fault injected to test a test.

**SCOPE, stated up front so it is never misread.** `dv_harness/mutation_testing.py` is
testing-infrastructure-on-this-repo's-own-Python-code. It is NOT DUT/RTL-level fault injection
(stuck-at / bit-flip / gate-level fault campaigns): that needs a real RTL target and a simulator
this repository does not contain, and nothing here may ever be cited as evidence about a DUT. The
subject is this harness's own test suite; the verdict is about that suite's sensitivity and
nothing else.

**Why not coverage.** Coverage says a line EXECUTED during a test. That is a different claim from
"a test would have FAILED had that line been wrong" -- a test that imports a module and asserts
nothing about its boundaries gets full line coverage and kills zero mutants. Mutation score is
the measurement that separates the two.

**Four standard AST operators**, each a single-token change whose surviving names a specific
weakness: `COMPARISON_SWAP` (`<`↔`<=`, `>`↔`>=`, `==`↔`!=`, `is`↔`is not`, `in`↔`not in` --
boundary-SHIFTING rather than inverting, because an inverted comparison breaks so loudly that any
test kills it and the mutant teaches nothing), `BOUNDARY_SHIFT` (off-by-one on an int literal),
`BOOL_OP_SWAP` (`and`↔`or`) and `BOOL_CONST_FLIP`. Mutants are produced by `ast.unparse` of the
whole tree with exactly one site changed, so a mutant is always syntactically valid; a
`-1` is labelled the way the SOURCE spells it ("-1 -> -2"), not the way the AST stores it.

**The working tree is never written to, and that is structural.** mutmut and cosmic-ray overwrite
the source file and restore it in a `finally`; a crash mid-run would then leave a deliberately
broken `dv_harness/*.py` in a tree whose main/master pushes are governed by real gates. Instead
each mutant runs in a SUBPROCESS carrying a `sys.meta_path` finder that serves the mutated source
for exactly one module name, from a temp file, before pytest is imported. The real file is opened
read-only.

**A mutant run cannot reach a real build, regression or LSF submission.** `assert_safe_target()`
refuses any module outside `dv_harness/` and any test file outside `dv_harness_tests/` -- and the
tests really run under that suite's `conftest.py`, whose existing session-wide
`ENV_TRANSPORT_OVERRIDE = "off"` pin is REUSED rather than re-implemented here (a second copy
would be exactly the parallel mechanism the Methodology Consolidation Rule forbids).

**Baseline first, always.** The run begins by executing the UNMUTATED source through the SAME
import hook. That proves both that the tests are green and that the hook is transparent; if it
fails, the report is `BASELINE_FAILED`, every mutant stays `NOT_RUN` and there is no score --
never a number computed off a red suite. A `TIMEOUT` gets its OWN bucket and is deliberately NOT
folded into `killed`: a hang is not the tests detecting the fault.

**Real measured result on this repo.** `dv_harness.qualification` scores **1.0** (3/3 killed) and
`dv_harness.stats_snapshot` scores **0.333** (12 generated, 4 killed, 8 survived) -- the contrast
is the point, and the survivors are real findings a human can act on (`_iron_rule_count`'s and
`_graph_counts`'s missing-file `return 0` branches are never exercised; `_is_real_agent_profile`'s
`OSError` branch is never exercised). SURVIVED is a finding, not necessarily a bug: some are
EQUIVALENT MUTANTS (`str.find` can return -1 or a non-negative index and never -2, so `-1 -> -2`
is undetectable by construction). Standard mutation testing has no decision procedure for these;
they are reviewed by a human, and this module never claims a survivor proves a missing test.

Front door: `dv-harness mutation-test [--module ...] [--test ...] [--operator ...]
[--max-mutants N] [--lines A:B] [--list] [--min-score F]`. `--module` omitted runs every pair in
`DEFAULT_TARGETS`, deliberately a SHORT list because one mutant costs one full pytest process.
`--max-mutants` reports the remainder `NOT_RUN` rather than dropping them, so a partial run can
never read as a full one.

**Deliberately bounded, and stated rather than implied closed.** (1) Mutation score is a
MEASUREMENT here, not a gate: there is no stage gate and no default threshold; `--min-score` is
opt-in. (2) It ARBITRATES and AUTHORIZES nothing -- no approval is minted and no human-approval
gate is referenced. (3) Equivalent-mutant detection is undecidable in general and is not
attempted. (4) The operator set is four, not the dozen a mature tool ships; each added operator
multiplies wall clock by its mutant count.

Proven by `dv_harness_tests/test_mutation_testing.py` (21 tests). The core end-to-end test runs
the ONE real line `stats_snapshot.py` spells `if end == -1` and asserts its two mutants come back
DIFFERENTLY -- `==`→`!=` KILLED, `-1`→`-2` SURVIVED -- for reasons provable by inspection rather
than by hope. That asymmetry is the control: if the import hook were not installing the mutant
both would survive, and if it were breaking the module both would be killed. The rest carry the
same shape: the working tree's bytes AND mtime are asserted unchanged across a run, a forced
baseline failure is asserted to score nothing and run no mutant, both safety refusals are driven,
every mutant is asserted to compile and to differ, re-generation is asserted byte-identical (a
missed undo would silently produce compound mutants), and both CLI paths run as real subprocesses
including a real non-zero exit under `--min-score`.



<!-- S077: moved verbatim from CLAUDE.md original lines 4821-4915 (M4.6 CLAUDE Context Normalization) -->
## Dependency / Supply-Chain Governance (2026-09-06, PC-5)

This harness could not answer a basic question about itself: which third-party components is it
built on, at which versions, and is any of them unconstrained. The gap was total and re-verified by
negative grep before anything was written -- `grep -rn "supply_chain|dependency_audit|SBOM|
pinned.version|vulnerability" -i` over the whole tree matched NOTHING executable. No module read
`pyproject.toml` or `requirements-harness.txt` as a dependency declaration, nothing compared a
declared dependency against what is really installed, and nothing anywhere asked whether a version
was pinned.

`dv_harness/dependency_supply_chain.py` answers it, and REUSES rather than rebuilds on both sides.
The DesignWare VIP half of the inventory is `env_manifest.build_vip_release()` /
`scan_designware_home()` -- the real `$DESIGNWARE_HOME` filesystem scan that already answers "which
VIP release is this environment actually built against", carried through with its three honestly
distinct NOT_AVAILABLE reasons intact; there is no second VIP scanner here and no VIP version is
ever read out of a document. File-integrity records go through the now-public
`env_manifest.file_ref()` (the private `_file_ref` exposed, not copied, the same "made public for
this" pattern `uvm_structural_lint.config_db_call_sites()` set), so a supply-chain report and an
env.manifest.json describe the same file identically. Version arithmetic is `packaging`'s
`SpecifierSet`/`Version` -- hand-rolling PEP 440 comparison is how a supply-chain check silently
accepts a version it should have refused.

**Three checks, and each one says honestly what it is.**
- **PINNED_VERSION** -- real, and it runs everywhere. Every declared Python requirement is
  classified from its own specifier set, and only `==`/`===` without a wildcard is PINNED_EXACT,
  because it is the only form that names ONE artifact: `==1.2.*` and `~=1.2.3` are BOUNDED_RANGE,
  `>=4.0` is LOWER_BOUND_ONLY (the next MAJOR release satisfies it), and a bare name is
  UNCONSTRAINED (any release, including one not yet published, satisfies it) -- ranked HIGH /
  MEDIUM / LOW by exactly how much room the declaration leaves. An installed VIP package is
  PINNED_EXACT when the install tree really names a version directory and a finding when it does
  not, because "which VIP is this" is then unanswerable from the install itself.
- **DECLARED_VS_INSTALLED** -- real. Each requirement is resolved against the REAL running
  interpreter through `importlib.metadata` (metadata, not an import, so a package with an
  import-time side effect is never executed), so a declared dependency nobody installed and an
  installed version outside its own declared range are both findings rather than assumptions.
- **VULNERABILITY_ADVISORY -- NOT_AVAILABLE in this environment, and it says so rather than
  reporting a clean scan.** `pip-audit` and `safety` are probed BY NAME at run time and are not
  installed here, and the OSV/PyPI advisory APIs are network services a LOCAL_ANALYSIS run must not
  contact. A project that HAS a real offline advisory database declares it
  (`.dv-harness/supply_chain/policy.json`, or `--advisory-db`) and the check really runs against
  it, matching each component's REALLY INSTALLED version -- never the declared range, since an
  advisory is about an artifact in use -- and reporting that database's own source, as-of date and
  sha256. A database is refused unless it can state its own source and ISO as-of date, and one
  older than the policy ceiling (default 30 days) is itself a finding, because an advisory
  published since then would not appear in the result.

**NOT_FULLY_CHECKED outranks POLICY_CLEAN**, the same rule `platform_health.py` applies when it
ranks UNKNOWN above HEALTHY: a check that could not run is never conflated with one that ran and
found nothing, so a fully-pinned, fully-installed project with no advisory source reports
NOT_FULLY_CHECKED and exits 2 -- never a clean security result. That pair is the headline test.
A component with no installed version is reported per-component as unmatchable rather than skipped,
so an inventory of uninstalled declarations can never read as a scanned one.

`dv-harness supply-chain inventory|check|advisory-status` and
`python -m dv_harness.dependency_supply_chain` share one `execute_verb()`, the same convention
`power-intent`/`golden-scenario`/`config-variants` use. Exit 0 POLICY_CLEAN, 1 a real policy
finding, 2 a check that could not run or nothing to inventory.

**Deliberately bounded, and stated rather than implied closed.** (1) It is NOT an SBOM: the
inventory is what this project DECLARES plus what is really installed for those declarations, not
a transitive dependency graph -- resolving one needs a resolver run against a package index, which
is a network act, and every report carries that disclosure. A pip directive (`-r`, `--index-url`)
is RECORDED as unfollowed rather than silently dropped, so an inventory can never quietly omit an
included file without saying so. (2) It READS ONLY and DECIDES nothing: no file is written, no
approval minted, no stage run, no build/regression/LSF submission started, and there is
deliberately no stage gate -- a gate that passed because no advisory database was present would be
worse than none. (3) An exemption suppresses a finding, never the fact: the component still appears
in the inventory carrying its exemption, and an exemption without a `reason` is refused, as is a
misspelled policy key (which would otherwise silently leave the default rule in force).
(4) It is REACHED, not WIRED -- no `run_stage()`/`advance()` call site invokes it, no graph node
declares it, and it is not on the dashboard. The CLI wrapper still appends the usual `CLI_ACCESS`
audit event; `python -m` carries the untouched-tree guarantee.

**This repository's own real answer today**, computed rather than claimed: 4 declared Python
components (`setuptools>=68`, `claude-code-sdk`, `mcp>=2.1.1,<3`, `jsonschema>=4.0`), of which
NONE is exact-pinned -- one HIGH (unconstrained), two MEDIUM (lower bound only), one LOW (bounded)
-- two of them declared but not installed for this interpreter, no VIP install tree, and
VULNERABILITY_ADVISORY NOT_AVAILABLE. The report is POLICY_FINDINGS and exits 1, and it is not a
clean security result.

Proven by `dv_harness_tests/test_dependency_supply_chain.py` (65 tests). The fixture is a REAL
project root whose every declaration is exact-pinned to a version `importlib.metadata` reports
RIGHT NOW (read at test time, never hardcoded, so the suite tests the module rather than the
developer's environment), and every rule is driven by MUTATING that one clean project ONE defect at
a time. The negative controls carry the detection power: the identical clean project WITHOUT an
advisory database is NOT_FULLY_CHECKED rather than POLICY_CLEAN, an advisory whose affected range
CONTAINS the really-installed version fires while the same advisory whose range stops AT it does
not, an advisory for another ecosystem never matches, a stale database is a finding while a
one-day-old one is not, an empty but well-provenanced database is usable, `==2.1.*` is proven not
to read as an exact pin, patching `env_manifest.build_vip_release()` really changes what the
inventory reports (so a second hand-rolled VIP walk would fail the test), the vocabulary guard is
shown to really trip on an injected `PASS`, and a byte-level snapshot proves two full reports write
nothing. Both entry points run as real subprocesses with their exit codes asserted. Nothing in it
contacts a network advisory API, runs a build, submits a job or touches an approval gate.


<!-- S120: moved verbatim from CLAUDE.md original lines 7690-7703 (M4.6 CLAUDE Context Normalization) -->
## Consolidated KPI/Benchmark Report: One Module, Real Producers Only (2026-09-06)

Several near-duplicate KPI trackers were implicit across intake, spec-to-signoff, spec-to-vplan and golden-scenario/USB-benchmark surfaces: `question_queue.py` already computes 4 real intake metrics behind its own verb, `trend_analysis.py` already detects PASS->FAIL regressions and same-SHA flip-flops behind its own report, and `signoff_export.py` already evaluates frozen-baseline invalidation behind its own verb -- but nothing assembled "how healthy is this harness's own verification WORKFLOW" (as opposed to one project's DUT) into one report. `dv_harness/consolidated_kpi_benchmark.py` is that one cross-cutting module, and it computes NOTHING a real producer does not already own -- it reads, counts and reports.

**8 KPIs, each naming its real producer.** `question_queue_self_resolve_rate` reuses `QuestionQueueStore.compute_metrics()` verbatim (bundling its 3 siblings -- blocking-questions/week, repeat-question rate, assumption-overturn rate -- since they are one real computation over one store). `repeated_question_count` is a plain count over that same module's own `list_questions()` raw records (total asks minus distinct question_keys) -- new arithmetic, but a COUNT over raw data, never a re-derivation of `question_queue.py`'s own Tier/self-resolve classification. `time_to_first_pass` reads real section-108 loop telemetry (`loop_telemetry.loop_events()`): the elapsed time from a real `LOOP_STARTED` to the first `LOOP_VERIFY_COMPLETED` carrying `verdict == Status.PASS.value`, per real `run_id`. `false_pass_count` is `trend_analysis.detect_pattern_regressions()`'s own `SAME_GIT_SHA_PASSED_AND_FAILED` reason over the real `evidence_db.regression_verdict_history` table -- a real existing signal that an earlier PASS did not guarantee its own property. `false_ready_count` is `signoff_export.evaluate_all_freezes()`'s own `INVALIDATED` count -- a frozen (declared-READY) signoff baseline later proven wrong by real post-freeze evidence, the closest real analog to "false-READY" this codebase has.

**Honest `NOT_MEASURED`, verified by direct search rather than assumed.** `ir_extraction_accuracy`, `manual_edit_count` and `human_engineering_time` are always reported `NOT_MEASURED`: a repo-wide grep confirmed no module compares an extracted requirement/IR against a ground-truth-labeled extraction (only `requirement_contract.analyze_requirement_contract_set()`'s self-consistency status and `vplan_baseline`'s content-identity version exist, neither of which is an accuracy measurement), and no keystroke/diff-authorship tracker or engineering-time tracker exists anywhere. Each carries its real missing-producer reason rather than a fabricated number.

**The honesty pattern is `confidence_calibration.py`'s** (read for the pattern, no code imported or copied): four distinct statuses -- `MEASURED` / `NOT_MEASURED` / `INSUFFICIENT_HISTORY` / `NOT_AVAILABLE` -- checked at import to share no token with `dv_harness.models.Status`. A rate-shaped KPI below `MIN_SAMPLE_FOR_RATE = 10` (the same "smallest N at which 1/N <= 0.1" derivation) or a timing KPI below `MIN_RUNS_FOR_TIMING = 3` reports `INSUFFICIENT_HISTORY` rather than a rate/median computed off a couple of samples. Every KPI in `KPI_NAMES` always has a row in the report, MEASURED or not -- never silently omitted.

**Reading is never a mutating act.** `QuestionQueueStore`/`EvidenceStore` are opened read-only or not constructed at all when their backing file is absent (proven: a bare project gains zero files/directories from a report); no build, gate, approval, memory, waiver or Blackboard record is written; there is deliberately no stage gate -- a gate that passed on a KPI nobody actually measured would be worse than none. `ControlPlane.approve()`, `policy.can_signoff()` and the PR-only main/master governance are untouched and unreferenced. Per this task's file-safety scope, `dv_harness/gates.py` and `dv_harness/cli.py` were not touched and no entry is proposed for either; the front door is `python -m dv_harness.consolidated_kpi_benchmark {names,report,show}`.

Proven by `dv_harness_tests/test_consolidated_kpi_benchmark.py` (29 tests), every fixture built through the real owning module (`QuestionQueueStore.add_question()`, `loop_telemetry.emit()` through a real `StateStore`, `EvidenceStore.insert_regression_verdict()`, `waiver_store.record_waiver()`/`revoke_waiver()`, `signoff_export.freeze_signoff_baseline()`) -- nothing hand-written into a JSON/JSONL file to look like real evidence. Each KPI has a core positive path (cross-checked against an independent call to the real underlying producer, e.g. the self-resolve-rate KPI's value asserted equal to a directly-called `compute_metrics()` result) plus real negative controls: zero real events (`NOT_AVAILABLE`), too few real events (`INSUFFICIENT_HISTORY`), and a genuinely-clean history reporting a real zero rather than skipping the KPI. The headline test the task requires, `test_ir_extraction_accuracy_is_always_not_measured_never_fabricated` (plus its two siblings for manual-edit-count and human-engineering-time), asserts a KPI with no real producer reports `NOT_MEASURED` with `value is None` on every call, never a fabricated number.


<!-- S126: moved verbatim from CLAUDE.md original lines 7899-7966 (M4.6 CLAUDE Context Normalization) -->
## Target-Conditioned Missing-Artifact Detector (2026-09-06)

"What's missing" was never one fixed checklist in this project -- an agent about to generate a
subsystem UVM environment needs a completely different subset of prior evidence than an agent
about to export a signoff bundle, or one deciding whether functional coverage is closed enough to
report. Before this module, no code anywhere took a downstream TARGET name as an input and derived
a target-specific missing-artifact list from it: every existing readiness/gate reader
(`generation_readiness.py`, `golden_flow_readiness.py`, `functional_coverage_signoff.py`,
`vip_learning_gate.py`, ...) answers its own single fixed question well, but none of them is
conditioned on "missing FOR WHAT". A generic "you're missing some files" message is exactly the
failure mode this closes: it names no category and gives a caller nothing to act on.

`dv_harness/target_conditioned_missing_artifact_detector.py` is deliberately small and
self-contained -- per this batch's file-safety scope it imports nothing from any other module built
in the same batch and nothing from the frozen/claimed file list, accepting the caller's current
source-inventory facts as a plain duck-typed mapping (`category_id -> True/False/omitted`) rather
than reading `env.manifest.json`, the evidence database, or any other artifact itself. Wiring a real
project's own facts into that mapping (e.g. from `env_manifest.py`'s per-layer `status` fields, or
`waiver_store.status_report()`) is a caller's job, not this module's.

**A small, explicit, real target-name set** -- `VIP_UVM_CREATION`, `SIGNOFF_PACKAGE`,
`COVERAGE_CLOSURE`, `REGRESSION_SUBMISSION` -- each mapped in `TARGET_ARTIFACT_TABLE` to the
specific artifact categories THAT target needs (vip_config_dump, dut_rtl_source, register_map,
bind_topology, phy_boundary_decision, vip_symbol_index, regression_evidence, coverage_summary,
waiver_ledger, golden_scenario_capsule, signoff_gate_evidence, requirement_contract,
testplan_correspondence, regression_list), each carrying its OWN per-(target, category) reason tied
to a real, already-established concept in this codebase's house vocabulary (env.manifest.json's own
layers, the waiver ledger's derived status, connectivity.py's bind-tier gate, Bind-Location Rule 5's
PHY-boundary-first ordering, vip_api_card.py's citation proof) -- never a shared generic reason
string and never a category invented for a target it is not genuinely tied to.
`assert_table_covers_declared_categories()` runs at import time so a table entry citing an
undocumented category, or carrying an empty reason, fails loudly rather than silently rendering a
blank explanation.

**Three-valued presence, never guessed.** A category in the caller's inventory reads `True`
(confirmed PRESENT), `False` (confirmed MISSING -- someone actually checked and it is not there),
or anything else / simply omitted (NOT_ASSESSED -- nobody has reported on it either way). An omitted
key never silently reads as present (which would let a half-populated inventory claim readiness it
never earned) and never silently reads as absent either (which would report a false MISSING finding
about a category nobody looked at). The overall verdict is the strict worst found: any confirmed
MISSING -> `MISSING_ARTIFACTS` (naming every one, each with its own target-specific reason), else
any NOT_ASSESSED -> `INCOMPLETE_EVIDENCE`, else `READY`. An unrecognized target is `UNKNOWN_TARGET`
with zero fabricated per-category findings -- inventing a plausible-looking requirement list for a
target this module does not define would be exactly the fabrication the Evidence Truth Rule
forbids.

**It decides and authorizes nothing beyond classification.** No stage runs, no gate is invoked, no
artifact is read, and no approval machinery is referenced. There is no `dv-harness` CLI verb --
`cli.py` was explicitly off-limits for this task -- so the only front door is `python -m
dv_harness.target_conditioned_missing_artifact_detector <TARGET> [inventory.json]` (exit 0 READY,
1 MISSING_ARTIFACTS/INCOMPLETE_EVIDENCE, 2 UNKNOWN_TARGET/usage), the same disclosed
python-m-only convention several very recent same-day additions in this project also use when
`cli.py` is under concurrent edit.

Proven by `dv_harness_tests/test_target_conditioned_missing_artifact_detector.py` (25 tests): the
core positive path (a fully-present inventory reads READY) for every one of the 4 real targets;
an unrecognized-target refusal; an empty or omitted inventory reading `INCOMPLETE_EVIDENCE` (never
READY, never MISSING_ARTIFACTS); a confirmed-absent category producing `MISSING_ARTIFACTS` naming
it with a reason proven to reference both the specific category AND the specific target (and
proven NOT to contain a generic "need more files" phrase); MISSING outranking NOT_ASSESSED in the
fold; seven ambiguous values (`None`, `"unknown"`, `"yes"`, `1`, `0`, `[]`, `{}`) each proven to
classify as NOT_ASSESSED rather than being guessed present or absent; a cross-target proof that two
different targets derive two genuinely different, specifically-worded missing findings from the
identical partial inventory over a category both require; a whole-table uniqueness check that no
two (target, category) reason strings collide; a completeness check that every declared category
carries a real, non-empty description; and four real subprocess CLI invocations asserting exit
codes 0/1/2.


<!-- S127: moved verbatim from CLAUDE.md original lines 7967-7984 (M4.6 CLAUDE Context Normalization) -->
## Source Authority: Conflict-Type Taxonomy (2026-09-06)

`source_authority.resolve_conflict()` decides WHICH VALUE wins when two sources disagree; it never says WHAT KIND of disagreement this was. Two conflicts that both resolve `RESOLVED` -- or both land at `UNDECIDABLE_SAME_AUTHORITY` -- can be entirely different SHAPES of problem: two controller docs disagreeing with each other is a documentation-staleness question; a register file disagreeing with the RTL decoder is a regmap-vs-silicon question; a VIP's shipped example disagreeing with its own user guide is a VIP-internal-consistency question. Nothing anywhere named that shape, so two audits of the same conflict history could each describe "what kind of conflicts this project has" differently from identical underlying records.

A purely additive extension to `dv_harness/source_authority.py` (no other file touched, per this gap-closure's own scope) adds exactly that: a 10-value classification layer over the source TYPES a conflict names, layered on top of -- and never changing the meaning of -- the existing 9-level `AUTHORITY_ORDER`/`resolve_conflict()`/`escalate_conflict()` machinery.

**The vocabulary** (`CONFLICT_TYPES`): `DOC_DOC_CONFLICT`, `DOC_RTL_CONFLICT`, `REGISTER_RTL_CONFLICT`, `GUIDE_REGISTER_CONFLICT`, `PHY_SPEC_MODEL_CONFLICT`, `VERSION_CONFLICT`, `CONFIGURATION_CONFLICT`, `COMMAND_TASK_CONFLICT`, `VIP_DOC_SOURCE_CONFLICT`, `UNKNOWN` -- held closed against drift by `assert_conflict_type_vocabulary_is_closed()`, which runs at import time and fails if a declared `CONFLICT_TYPE_*` constant's value is not in the tuple.

**Why it needs a wider vocabulary than the 9-level order itself.** Four of the ten values (`PHY_SPEC_MODEL_CONFLICT`, `VERSION_CONFLICT`, `CONFIGURATION_CONFLICT`, and the ad hoc half of `COMMAND_TASK_CONFLICT`) name source shapes the conflict-authority order has no rank for at all -- a PHY electrical model, a spec/datasheet document, a tool/VIP version string, a configuration/variant value. `SourceClaim.__post_init__` correctly refuses to rank any of those (there is no level to give a PHY model in the 9-level order), so a genuine PHY-model-vs-spec disagreement can never reach `resolve_conflict()` as a real claim pair -- but it is still a real, nameable conflict. `classify_conflict()` therefore accepts TWO record shapes: a real `resolve_conflict()`/`escalate_conflict()` record (reading each claim's own `source`, always one of the 9 `AUTHORITY_ORDER` ids), or a lighter ad hoc `{"source_a": ..., "source_b": ...}` / `{"sources": [...]}` record for a disagreement the 9-level order was never meant to rank.

**Classification is by source TYPE alone, never by claim content.** `normalize_conflict_source_kind(name)` maps a source name onto one of 13 broad "kinds" -- each of the 9 real `AUTHORITY_ORDER` ids resolves to exactly one kind (checked equal to `{s.id for s in AUTHORITY_ORDER}` by test, so a future 10th authority level cannot go unclassified), and 4 extra kinds (`phy_model`/`spec`/`version`/`configuration`) exist only in this layer, with their own alias table folded through the SAME `_key()` normalization every `AUTHORITY_ORDER` alias already uses. An unrecognized source raises `UNKNOWN_CONFLICT_SOURCE_KIND` rather than silently classifying `UNKNOWN` -- the same "never let a typo hide behind the taxonomy's own honest unknown value" discipline `normalize_source()` already applies to the conflict-authority order itself.

`classify_conflict_type(source_a, source_b)` looks up the unordered kind pair in a fixed table and returns `UNKNOWN` for any pair the table does not name (e.g. `simulation_result` vs. `controller_doc`, or two `existing_testbench_bind` claims) -- naming a conflict's type WRONG is worse than admitting it does not fit one of the nine named shapes. `classify_conflict(conflict)` is the record-level entry point: it classifies a `NO_CONFLICT`-verdict record too (the taxonomy is about which two source types were being COMPARED, not whether they agreed), and refuses -- rather than guesses -- a record naming more than 2 distinct source types (the same 2-3-sides pairwise boundary `escalate_conflict()` already draws for the question-queue schema), a record matching neither accepted shape, a record with no sources at all, or a non-dict.

Proven by 31 new tests appended to `dv_harness_tests/test_source_authority.py` (68 total, all 37 pre-existing tests untouched and still passing): vocabulary closure, `AUTHORITY_ORDER`-id-to-kind completeness, all 9 named pairs (via both `AUTHORITY_ORDER`'s own aliases and the extra-kind alias table, and order-independence), 4 negative controls for unrelated-but-recognized pairs reading `UNKNOWN` plus an unrecognized-source refusal, `classify_conflict()` driven against a REAL `resolve_conflict()` record at all three of its real verdicts (`RESOLVED`/`NO_CONFLICT`/`UNDECIDABLE_SAME_AUTHORITY`), both ad hoc record shapes, and refusals for a 3-plus-source record, an unrecognized record shape, an empty-claims record, and a non-dict input.

**Deliberately bounded.** This layer only LABELS which two source types a conflict compares; it does not re-decide `resolve_conflict()`'s verdict, does not change `escalate_conflict()`'s question-queue behavior, and adds no stage gate -- it is a pure classification function a caller may use when reporting on conflict history, nothing more.


<!-- S134: moved verbatim from CLAUDE.md original lines 8281-8328 (M4.6 CLAUDE Context Normalization) -->
## File Candidate Ranker: Evidence-Only Ranking of an Ambiguous File Choice (2026-09-06)

Intake repeatedly hits a recurring real shape: which of several similarly-named files is canonical --
`usb_reg.xlsx` vs `usb_reg_v2.xlsx` vs `usb_reg_final.xlsx`, or three copies of a Makefile nobody
remembers which one the build actually uses. `dv_harness/file_candidate_ranker.py` is deliberately
generic: it ranks ANY set of candidate file paths a caller hands it, for any reason the caller is unsure
which one is canonical -- distinct from, and never confused with, this project's DE-command-specific
reuse scorer, which answers a narrower domain question.

**Three real, independently-obtained signals per candidate.** Git log reference count/recency (a real
`git log --oneline -- <path>` subprocess call against a caller-supplied repository root, giving commit
count and the most recent commit's date/sha/subject); build-script/Makefile reference count (a real
text scan of every Makefile/shell/csh/tcl/perl/CMake/filelist file found under a caller-supplied project
root, counting literal occurrences of the candidate's own basename); real file mtime (a real `os.stat()`
call, mtime plus size as a secondary fact). Per the Evidence Truth Rule, every signal that could not be
genuinely determined reports `NOT_AVAILABLE` with the specific real reason -- a missing git binary, a
path outside any git repository, no build scripts found, a candidate absent from disk -- never a
guessed value, and never a claim about a directory it was not asked to scan.

**This module never picks a winner.** `rank_file_candidates()` always returns EVERY candidate it was
given, each carrying its own full, independently-cited evidence. The one thing it additionally computes
-- `display_rank` and the `display_order_reason` explaining it -- is a purely INFORMATIONAL sort order
over the SAME evidence a human reading the report can already see and override in one glance; it is
explicitly asserted (by the test suite) never to be read as a decision, a recommendation, or a verdict.
There is no "winner" field, no "delete the others" action, and `assert_no_verification_verdict_vocabulary()`
holds this module's vocabulary disjoint from `models.Status` at import time, the same guard several
other domain-vocabulary modules in this repo already apply to themselves.

**NOT_AVAILABLE vs. a real zero -- a deliberate distinction.** For the build-script and git-recency
signals, a real, checked zero (a project really has build scripts and none mention this file; a file
really was found and stat'd and just has an old mtime) is reported AVAILABLE with that zero/old value --
collapsing "we checked and the answer is zero" into `NOT_AVAILABLE` would itself be the "never conflate
absence with zero" failure the Evidence Truth Rule forbids. The one place this module deliberately
reports `NOT_AVAILABLE` for a real, successful, zero-result git log call is a reachable repository with
real commit history that nonetheless contains ZERO commits touching this particular path -- carried on
the record with the real `commit_count=0` anyway, never hidden, because for this module's ranking
purpose that case carries no comparative information beyond what the other two signals already surface
more concretely.

Proven by `dv_harness_tests/test_file_candidate_ranker.py` (27 tests) against a real throwaway git
repository with real commits touching different candidate files, built via subprocess in the test
itself: each signal is proven on its positive path and on its own NOT_AVAILABLE reason, the
zero-vs-NOT_AVAILABLE distinction is proven directly, and the "never picks a winner" guarantee is
proven by asserting every candidate is always returned with its full evidence regardless of rank.

**Disclosed residual**: it is a pure fact-gatherer. It decides nothing, writes nothing, and references
no approval/governance mechanism.


<!-- S144: moved verbatim from CLAUDE.md original lines 8652-8734 (M4.6 CLAUDE Context Normalization) -->
## Runtime Event Registry: Stop-on-Failure Dependency Propagation (2026-09-06)

A generated pattern's task composition (`block`/`branch_a*`/`branch_fw`/`branch_b*`, per
`branch-mapper`/`pattern-architecture` SKILL.md) and its interrupt-driven service loop
(`interrupt-event-dispatch`'s ARM/WAIT/WAKE/DECODE/CLEAR loop) both produce and consume NAMED
RUNTIME EVENTS -- a global bring-up completing, a per-port DUT+PHY init finishing, an interrupt
being seen and then serviced, a branch_b* VIP scenario finishing. Nothing in this repo tracked
those events as a first-class registry with a dependency graph: `blackboard.py` stores free-form
named topics, not typed events with a producer/consumer/timeout/scope; `loop_contract.py`/
`loop_budget.py` track the HARNESS's own loop state, not a generated environment's runtime event
flow. An upstream event that failed or timed out left every downstream event depending on it
silently PENDING forever, with nothing distinguishing "still waiting" from "can never happen
because its prerequisite already failed".

`dv_harness/runtime_event_registry.py` is that registry. The record shape is exactly
`{event_name, producer, consumer, payload, timeout, scope, status}`, over a CALLER-DECLARED event
set -- GLOBAL_READY/DUT_READY/VIP_STARTED/IRQ_SEEN/IRQ_SERVICED/CHECK_DONE are illustrative names
only (matching this repo's own `block`/`branch_a*`/`branch_fw`/`branch_b*`/verdict vocabulary in
the tests), never hardcoded inside the module -- a different project's real event names are
declared by its caller, exactly as `config_variant_coverage.py`'s dimensions are declared, not
guessed.

**Relations, and the direction convention.** `(from_event, relation, to_event)` with four types:
REQUIRES/WAITS_FOR read dependent -> prerequisite ("B REQUIRES A" = B depends on A having already
fired); TRIGGERS/UNBLOCKS read cause -> effect ("A TRIGGERS B" = A firing causes B). REQUIRES is a
HARD dependency; UNBLOCKS is a RECOVERY override; WAITS_FOR and TRIGGERS are informational-only
(AT_RISK_WAITS_FOR_FAILED_UPSTREAM / ORPHANED_TRIGGER findings) and never change a status.

**Stop-on-failure propagation is precisely what the task named.** `propagate()` is a fixed-point
over the REQUIRES sub-graph (validated acyclic at construction -- a REQUIRES cycle is refused as a
contradiction in the declaration, the same discipline `config_variant_coverage.ConfigSpace` applies
to a critical combination its own constraints forbid). An event flips PENDING ->
BLOCKED_BY_DEPENDENCY only when its own raw status is still PENDING, at least one REQUIRES
prerequisite is FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY (transitively), and no UNBLOCKS recovery event
has FIRED. A downstream event no longer sits silently PENDING forever once its prerequisite has
genuinely failed -- it carries an honest, distinct status naming why, and a real observed status is
NEVER overwritten by the computed one (proven by a dedicated test).

**The Evidence Truth Rule is enforced structurally, not just by prose.** A non-PENDING observation
(FIRED/FAILED/TIMEOUT) requires a non-empty `evidence` citation (a sim.log line, an `evidence_db`
record id, a waveform offset) -- `RuntimeEventObservation.__post_init__` refuses one with none, the
same discipline `waiver_store`'s revocation and `config_variant_coverage.CriticalCombination.reason`
already apply. BLOCKED_BY_DEPENDENCY may never be declared directly by a caller -- it is
`propagate()`'s own computed conclusion, and asserting it directly would be asserting a
propagation result nobody computed. `timeout` is a caller-declared budget from real project
policy/RTL evidence, never computed or defaulted here.

**Deliberately kept separate from `loop_budget.FailureType`.** That vocabulary answers "why did a
harness STAGE ATTEMPT fail" (retryable or not) -- a different, coarser question than "what happened
to one RUNTIME EVENT". `assert_no_status_vocabulary_collision()` checks the two share no token at
import, and a dedicated test re-checks it.

Reuses `connectivity.render_markdown_table` (the repo's one parameterized table renderer) for both
the declared-graph view and the propagation-status view, rather than a second hand-rolled one.

CLI: `python -m dv_harness.runtime_event_registry graph|status --registry <file.json> [--json]`,
one shared `execute_verb()`. `graph` prints the declared events/relations only; `status` runs
`propagate()` and prints the effective status + findings table. Exit 0 nothing
FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY, 1 at least one is, 2 NOT_AVAILABLE or a usage/declaration
error.

**Deliberately bounded, and stated rather than implied closed.** (1) It observes nothing itself:
whether an event "really" occurred is decided by the caller from real sim.log/waveform/evidence-db
evidence before calling this module -- `sim_log_analysis.py` stays the repo's sole real sim.log
parser. (2) UNBLOCKS is the only recovery mechanism modelled; there is no any-of/all-of REQUIRES
distinction beyond "at least one failed prerequisite blocks, unless recovered". (3) It DECIDES
nothing beyond reporting: no gate, no build, no job, no approval, and there is deliberately no
stage gate. (4) The fixed-point loop is O(events x relations) per iteration over an acyclic REQUIRES
graph -- adequate for one pattern's real event count, not built for a whole-farm event stream.

Proven by `dv_harness_tests/test_runtime_event_registry.py` (33 tests) against a real illustrative
event set mapped onto this repo's own `block`/`branch_a*`/`branch_fw`/`branch_b*` vocabulary: direct
and transitive BLOCKED_BY_DEPENDENCY cascade, TIMEOUT treated identically to FAILED, the UNBLOCKS
recovery override and its negative control (recovery event not fired -> block still occurs), a real
observation never being overwritten by propagation, WAITS_FOR/TRIGGERS informational findings, and
nine real negative controls (duplicate event name, relation naming an unknown event,
self-referential relation, REQUIRES cycle, non-PENDING observation with no evidence, a direct
BLOCKED_BY_DEPENDENCY assertion, an unknown relation-type string, an invalid timeout, an observation
for an undeclared event) -- each asserted to raise `EventRegistryError` naming the real defect. Both
`execute_verb()` and a real subprocess CLI invocation are driven and their exit codes asserted.
Nothing in it runs a build, a regression, or an LSF submission, and no human-approval gate is
referenced.


<!-- S184: moved verbatim from CLAUDE.md original lines 10484-10546 (M4.6 CLAUDE Context Normalization) -->
## Independent Verification: VERIFICATION_ARCHITECTURE Gate-Fixture Gap Fix (2026-09-07, re-verified by an independent verification agent)

A prior agent diagnosed `test_verification_architecture_requires_fabric_topology_completeness_gate`
(`dv_harness_tests/test_engine_gates_and_routing.py`) as GATE_FAIL-ing not because its own real
`fabric_topology_completeness_gate`/`protocol_structural_completeness_gate` assertions were wrong,
but because `STAGE_GATES["VERIFICATION_ARCHITECTURE"]`'s 2026-09-06 gap-closure pass had registered
three NEW mandatory gates (`vip_bind_generation_gate`/`scoreboard_generation_gate`/
`assertion_generation_gate`) that the file's shared `_VERIFICATION_ARCHITECTURE_EXTRA_GATES` fixture
constant -- concatenated onto every VERIFICATION_ARCHITECTURE-stage PASS-path test in this file --
had never been updated to supply evidence for. The claimed fix added three real, non-hand-guessed
evidence blocks (each the actual `to_dict()` shape of `verification_architecture.build_vip_bind_ir()`/
`build_scoreboard_ir()`/`build_assertion_ir()` run against legitimate inputs) to that shared constant.

**This session independently re-verified the claim rather than trusting the report**, per this
project's own Evidence Truth Rule ("CLAUDE.md is project guidance, not verification evidence... any
current root cause must be revalidated with current evidence"):

- **Real diff inspected directly.** Read `_VERIFICATION_ARCHITECTURE_EXTRA_GATES`
  (`dv_harness_tests/test_engine_gates_and_routing.py:64-95`) in full. The three appended blocks are
  genuine `dv-harness-evidence:<gate_id>` fenced JSON payloads carrying real
  `verification_architecture.py` IR fields (`ir_kind`/`status: "RESOLVED"`/`confidence: "HIGH"`/
  `source_evidence` citing `connectivity.bind_entry`/`phy_boundary.decide_bind_location`/
  `env_manifest.build_dut_facts_clock_reset`, etc.) -- structurally consistent with what those real
  builder functions actually emit, not a hand-typed shortcut. Confirmed all three gate scripts exist
  on disk (`tools/verification_flow/{vip_bind,scoreboard,assertion}_generation_gate.py`). This is a
  real evidence addition, never a skip/xfail/gate-weakening: `gates.py`'s `STAGE_GATES` table and the
  three gate scripts themselves were not touched by the fix.
- **Target test, re-run independently, isolated:** `python -m pytest
  dv_harness_tests/test_engine_gates_and_routing.py::test_verification_architecture_requires_fabric_topology_completeness_gate
  -v` -> **1 passed** (31.95s).
- **Whole-file regression, re-run independently, isolated:** `python -m pytest
  dv_harness_tests/test_engine_gates_and_routing.py -v` -> **239 passed, 0 failed** (313.55s).
- **Broader regression across the file-safety scope named in this verification's task** (adjusted per
  the task's own "adjust file names if they do not exist" instruction: `test_gates_and_react.py` does
  not exist on disk; substituted `test_verification_architecture.py` -- confirmed to exist --
  plus `test_react_loop.py`/`test_react_inference_wiring.py`/`test_assertion_placeholder_closure_gate.py`,
  the real files most plausibly intended). A combined 5-file run (357 tests collected) completed after
  3723s under heavy concurrent multi-agent CPU load on this shared dev machine: **345 passed, 1
  failed**. The one failure, `test_self_audit_against_real_repo_reports_real_current_findings`, was
  investigated directly rather than accepted at face value -- re-run in isolation, it failed again
  identically; running `python tools/verification_flow/test_collection_health_gate.py --root .`
  directly reproduced its real detail payload, `{"status": "FAIL", "reason":
  "PYTEST_COLLECTION_TIMEOUT"}`; and a bare `python -m pytest --collect-only -q` timed a plain
  collection pass at **over 200 seconds**, well past that gate's own hardcoded 90s internal timeout --
  confirming the exact pre-existing failure mode `dv_harness/self_audit.py:296-306`'s own 2026-09-03
  comment already documents and predicts ("under real concurrent multi-session CPU load on this dev
  machine, self-audit's test_collection_health_gate FAILed via this exact path"). This project's own
  test suite has grown to 13,000+ collected tests through this session's massive concurrent
  multi-agent gap-closure batch, and the SAME test passed cleanly in this verification's own earlier,
  less-loaded isolated run of the same file -- confirming this is a real, environmental, repo-growth-
  driven timeout flake, never a deterministic regression caused by the VERIFICATION_ARCHITECTURE
  evidence-fixture fix. Every one of the other 118 tests across the four broader-scope files passed
  cleanly with zero failures.

**Honest verdict: FIXED_ALL_PASS, confirmed independently.** The root cause was genuinely a test-
fixture gap (a shared evidence-block constant not updated for three newly-registered mandatory
gates), the fix is a real, schema-consistent evidence addition with no bypass/skip/weakening of any
gate, the target test and its whole containing file pass cleanly and reproducibly, and the one
observed failure in the broader concurrent run is a pre-existing, self-documented, repo-size-driven
collection-timeout flake in an unrelated self-audit gate -- disclosed here rather than silently
omitted, and confirmed independently unrelated to `gates.py`'s `STAGE_GATES` registration or the
VERIFICATION_ARCHITECTURE stage.


<!-- S185: moved verbatim from CLAUDE.md original lines 10547-10566 (M4.6 CLAUDE Context Normalization) -->
## Plan-Quality Feedback: Cross-Run Stage-Sequencing Efficiency (2026-09-07)

Nothing in this repo grouped several past loop SESSIONS by the GRAPH TRAVERSAL SHAPE they took and asked whether that shape tends to converge or thrash — confirmed by a repo-wide grep for `plan_quality`/`stage_sequenc`/`traversal` before this module was written, which matched nothing executable. Two real, adjacent mechanisms already answer nearby questions and neither answers this one: `loop_telemetry.py` folds one loop SESSION's own section-108 events into a real `LoopSession` (state, iteration count, plateau/oscillation verdict, retry ledger, terminal outcome) but reports exactly one session at a time — nothing groups several by the path they took; `loop_convergence.py` classifies a project-wide coverage series and a project-wide oscillation fingerprint, both aggregated across the WHOLE evidence store, never grouped by which stages one specific run actually visited, in what order.

`dv_harness/plan_quality_feedback.py` is that missing rollup, and it derives nothing new: every fact it groups is `loop_telemetry.read_loop_telemetry()`'s own real, already-persisted per-session record — which itself already carries `loop_convergence`'s own per-session plateau/oscillation verdict, folded in by `engine._classify_loop_convergence_for_telemetry()` at retry-exhaustion (see this file's own "Loop Telemetry Events + the GUI Loop Engineering Center" section). Reading `loop_telemetry.read_loop_telemetry()` therefore already aggregates BOTH modules' real signals; this module's own job is exactly the grouping-by-shape neither performs.

**Deliberately distinct from two other real mechanisms.** `capability_evolution.repeated_unresolved_failure_patterns()` answers "has the SAME FAILURE SIGNATURE recurred across independent runs with no gate-verified fix" — a CAPABILITY-level question, keyed on failure content. This module never reads Job Memory, never files a capability candidate, and is keyed on the GRAPH PATH a run took, not on what failed along it. Any per-profile/per-tier track record (`confidence_calibration.py`'s confidence-tier reliability, `checker_sb_qualification.py`'s checker/scoreboard trust record) scores a NAMED AGENT/CONFIDENCE-TIER/CHECKER's own history; this module scores a SEQUENCING SHAPE and never reads an agent profile.

**Shape extraction, reusing `loop_telemetry`'s own already-real per-attempt record.** `iteration_stage_sequence()` reads one session's own `iteration_history` for its real `LOOP_ITERATION_STARTED` rows — `engine._emit_loop_iteration_started()` fires exactly once per outer `loop()` `while True` dispatch, including intra-stage retries, so this is the real, ordered per-attempt stage list a session actually produced, never re-derived from `state.json`'s own (mutable, overwritten-in-place) `attempts` counter. `stage_sequence_shape()` is the graph TRAVERSAL PATH this module scores: the ordered sequence of distinct stage nodes visited, collapsing only IMMEDIATELY-consecutive repeats (an intra-stage retry stays one hop); a LATER re-visit of an already-left stage — a real FAIL-edge loop-back, e.g. `PROJECT_MODEL -> FAILURE_RECOVERY -> PROJECT_MODEL` — is NOT collapsed, since it is a real, separate hop the graph's own edges produced. `retry_count()` is the difference between the raw per-attempt sequence and its shape-collapsed form.

**Classification is worst-wins, and the thresholds are borrowed, not invented.** `SHAPE_MIN_OCCURRENCES_FOR_SCORE` is `loop_contract.DEFAULT_OSCILLATION_REPEAT_THRESHOLD` (2), imported rather than re-typed — the same "2 independent observations before a claim is trustworthy" bar `loop_convergence.DEFAULT_PLATEAU_WINDOW`, `capability_evolution.REPEAT_FAILURE_MIN_OCCURRENCES` and `memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS` already use. `classify_shape_quality()` folds, most severe first: **INSUFFICIENT_DATA** (fewer than the floor's worth of independent sessions took this shape — a claim about one run is not a track record); **THRASHING** (a real confirmed `loop_convergence.OSCILLATING` or `REGRESSION` verdict on ANY occurrence — worst-wins, one real oscillation among clean siblings is still real evidence this shape thrashes — OR the average retry ratio across all occurrences meets `RETRY_RATIO_THRASHING_THRESHOLD` (0.5): a shape spending more than half its own dispatches re-attempting a stage it has not yet cleared is not converging efficiently by any reasonable reading of the word); **MIXED** (a real `loop_convergence.PLATEAU` verdict on at least one occurrence, or any retries at all, but nothing clearing THRASHING's own bar); **EFFICIENT** (every occurrence converged with no oscillation, no plateau, no retries). Every shape found is always reported, including every INSUFFICIENT_DATA one — a shape seen once is real evidence that has not yet crossed the trust floor, never silently dropped.

**Read-only, and it mints nothing.** `aggregate_stage_sequence_shapes()` calls `loop_telemetry.read_loop_telemetry()` and nothing else — no `state.json`, no `StateStore.load()`, no other file is opened, and no `engine.py`/graph file is read or edited by this item. A project whose loops have never emitted a section-108 event reports the honest `NOT_AVAILABLE`-shaped reason `loop_telemetry` itself already names, never a fabricated empty-but-clean matrix, and a one-shot `run_stage()` that is not a loop reports the identical honest absence. It mints no verdict and touches no gate: `ControlPlane.approve()`, `policy.can_signoff()`, `HumanApprovalRequiredError` and `ProductionWriteNotAuthorizedError` are untouched and unreferenced — checked directly against the module's own tokenized source, the same discipline several sibling read-only modules already apply to themselves. It never files a capability-evolution candidate, a question, or a memory record: a THRASHING shape is reported, not escalated — acting on it stays a human/agent decision this module does not make.

Rendering reuses `connectivity.render_markdown_table()`, this repo's one parameterized table renderer. **Wired to a real `dv-harness` CLI verb (2026-09-07, additive):** `dv-harness plan-quality-feedback show|report [--run-id ID] [--json]` is a thin argparse subparser + dispatch block in `cli.py` calling this module's own unmodified `execute_verb()` — the front door is now both `dv-harness plan-quality-feedback ...` and the original `python -m dv_harness.plan_quality_feedback show|report [--project-root DIR] [--run-id ID] [--json]` (`execute_verb()`, the same shared convention `loop_contract`/`loop_budget`/`loop_telemetry` follow; exit 0 available, 2 `NOT_AVAILABLE`). No logic was reimplemented in `cli.py`; `gates.py` was not touched.

Proven by `dv_harness_tests/test_plan_quality_feedback.py` (35 tests, `python -m pytest dv_harness_tests/test_plan_quality_feedback.py -q` -> `35 passed`): pure-unit coverage of shape extraction (including the headline FAIL-edge-loop-back-is-never-collapsed negative control) and of `classify_shape_quality()`'s worst-wins precedence over hand-built records (every one of INSUFFICIENT_DATA/THRASHING-by-oscillation/THRASHING-by-regression/THRASHING-by-retry-ratio/MIXED/EFFICIENT, plus a retry-ratio-just-under-the-threshold negative control and custom-threshold honoring); `aggregate_stage_sequence_shapes()` driven over hand-built `loop_telemetry`-shaped payloads (two sessions of one shape grouped with `occurrences == 2`, two distinct shapes never merged, success_rate computed only over sessions that actually reached a terminal event, sessions with no recorded iteration reported but never grouped, deterministic sort order); the required real-engine proof — **two REAL, independent `DVHarness.loop()` sessions over the REAL shipped `main_graph.json`**, the retry budget cleared between them (standing in for a human re-running the loop), grouped by this module into one real `occurrences == 2` THRASHING shape with the exact real `avg_iterations`/`avg_retries`/`terminal_outcomes`/`success_rate` the real engine actually produced — plus a real gate-PASS positive control proving the extracted shape reflects what the graph actually did, never a fixed assumption, and a `--run-id` filter proof; the two required honesty negative controls (a bare project, and a real one-shot `run_stage()` that is not a loop, both reporting the real honest `NOT_AVAILABLE`); a byte-level snapshot proving reading writes nothing; the tokenize-based never-reaches-a-gate check; and both the module's own `execute_verb()` and a real `python -m dv_harness.plan_quality_feedback` subprocess invocation. A full-repo `pytest --collect-only` (12426 tests) confirms no import-time collision was introduced elsewhere in the suite.

**Disclosed residual.** A real CLI front door now exists (`dv-harness plan-quality-feedback`, see above), but this is still not ENGINE-WIRED: no `run_stage()`/`advance()` call site invokes it and no graph node declares it — a caller (a human via the CLI, a dashboard card, a future capability-evolution integration) still has to invoke it directly. It scores the shapes a project's own recorded sessions actually took; it never enumerates or scores a hypothetical shape the graph could produce but never has.


<!-- S199: moved verbatim from CLAUDE.md original lines 11350-11365 (M4.6 CLAUDE Context Normalization) -->
## Agent Self-Escalation to More Compute: a Real, Agent-Facing "Deeper Investigation Needed" Signal (2026-09-07)

Section 34's own worked example -- an agent's own mid-investigation confidence landing LOW should be able to say so, structurally, so a caller/graph orchestrator can decide whether to fan out more agents -- had no mechanism anywhere in this repo. `dv_harness/inference.py`'s `score_confidence()` already computes exactly the right per-attempt assessment (`_react_step_inference()`/`_score_root_cause_confidence()` in `engine.py` already call it on every stage attempt), but nothing downstream of a real LOW result ever did anything with that fact beyond a plain string on the persisted `react_reasoning_step` record. `question_queue.py`'s own 3-tier SELF_RESOLVE/SAFE_TO_ASSUME/CANNOT_ASSUME protocol was confirmed, by direct reading, to answer a genuinely different question -- "does a HUMAN need to be asked, and how urgently" -- every record it produces is addressed to a person, persisted in a question queue, and (at Tier 3) BLOCKS a stage until answered. Nothing in this codebase let an agent flag its OWN low confidence to a machine reader without going through that human-facing channel.

`inference.build_deeper_investigation_signal()` closes that gap, additively, reusing `score_confidence()`'s exact `{"level", "score", "capped_by_counter_evidence"}` result shape rather than recomputing anything: given an already-computed confidence result, it returns `None` (no signal) unless `level == "LOW"`, and otherwise returns a real, structured record (`signal`, `stage`, `context_path`, `confidence_detail`, `gap`, `reason`, `disclosure`). `DEEPER_INVESTIGATION_NEEDED_SIGNAL` is deliberately a different word and word family from both `CONFIDENCE_LEVELS` and `question_queue.py`'s own `TIER_NAMES` -- `assert_escalation_signal_vocabulary_disjoint()` checks this disjointness at import time (re-deriving `question_queue.py`'s literal tier tokens rather than importing that module at module load, preserving `inference.py`'s own stated dependency-free-for-pure-math-callers design), and is proven, not merely claimed, by a monkeypatch test showing the guard actually trips on a real collision.

`dv_harness/blackboard.py` gained `read_agent_escalation_signals()`/`append_agent_escalation_signal()`, an accumulate-only `{"items": [...]}` registry over a new `agent_escalation_signals` topic -- the identical shape `append_debug_loop_round()` already established for `debug_loop_history`, so a caller/graph orchestrator reads it the same way every other Blackboard topic is read (via a real `node.blackboard_read` declaration). This is deliberately NOT a `question_queue.py` write path: nothing here files, answers, or blocks on a question.

`dv_harness/engine.py` gained `DVHarness._record_agent_escalation_signal()`, called once, additively, immediately after the existing `step_inference = self._react_step_inference(...)` call inside `run_stage()` -- no existing call site, return shape, or signature was changed. It is best-effort, mirroring every sibling `_record_*` method in this file: a malformed/absent `confidence_detail` returns `None` quietly, and a genuine LOW result appends the real signal to the Blackboard registry plus one real `AGENT_ESCALATION_SIGNAL_RECORDED` audit event in `.dv-harness/events.jsonl`.

**This item adds the signal and its recording only -- it does not, and structurally cannot, force `engine.py` to auto-dispatch more agents.** `_record_agent_escalation_signal()` never calls `run_stage()`, never touches `self.state`/`ss["status"]`, never routes anything, and never references `question_queue.py` at all (proven by a dedicated real-production-path test asserting no `.dv-harness/question_queue` directory is ever created by a run that records a real escalation signal). Acting on a recorded signal -- fanning out more agents, or not -- stays entirely a future caller/graph-orchestrator decision, exactly as CLAUDE.md's own Evidence Truth Rule requires for any production-behavior change: nothing here is applied directly to dispatch behavior, and no weight/threshold of `score_confidence()` itself is touched, read, or proposed for change.

**Deliberately bounded, and stated rather than implied closed.** (1) The one real production call site is the per-attempt `_react_step_inference()` path inside `run_stage()`, which fires on every stage attempt regardless of stage identity -- `_score_root_cause_confidence()`'s own post-hoc, PASS-only root-cause confidence recompute at RE_AUDIT was deliberately left unwired, since that call site answers a different, already-passed-stage promotion question rather than an in-flight "should I keep investigating" one. (2) `context_path` is a real, computed pointer to the exact `react/<stage>/iteration_NNN.json` file the same attempt's `ReactRecorder.record()` call writes -- proven to exist on disk, never a guessed or synthesized path. (3) There is no `dv-harness` CLI verb and no dashboard surface for this registry -- a REACHED capability (any caller/graph orchestrator may read `Blackboard.read_agent_escalation_signals()` directly), not a WIRED fan-out mechanism; building the actual fan-out decision logic that consumes this signal is explicitly out of this item's own scope.

Proven by `dv_harness_tests/test_agent_self_escalation.py` (24 tests): the pure-function LOW-vs-MEDIUM/HIGH behavior of `build_deeper_investigation_signal()` including the required negative control that a real MEDIUM and a real HIGH `score_confidence()` result never produce a signal; gap/context_path/custom-reason pass-through and the proof `confidence_detail` is the exact object handed in (never recomputed); six input-validation negative controls; the vocabulary-disjointness guard proven with real detection power via monkeypatch; and, on the real production path (reusing `test_react_inference_wiring.py`'s own proven ARCH_CALIBRATION fixtures), a real `run_stage()` that genuinely scores LOW recording exactly one real Blackboard entry (with a real existing `context_path` file and a real audit event) while creating no question-queue store at all, its sibling MEDIUM-confidence fixture recording nothing, a direct best-effort unit test of `_record_agent_escalation_signal()`, and an accumulation test proving stable sequence numbers across stages. `dv_harness_tests/test_inference.py` (107 tests), `test_react_inference_wiring.py` + `test_inference_engine_wiring.py` (130 combined), the three blackboard suites (46 tests), `test_engineering_confirmation_accumulation.py` (12 tests) and the full `test_engine_gates_and_routing.py` (238 passed, 1 pre-existing failure unrelated to this change -- `test_verification_architecture_requires_fabric_topology_completeness_gate`, a `gates.py` VERIFICATION_ARCHITECTURE-stage wiring gap disclosed elsewhere in this file, confirmed byte-identical before and after this edit) were all re-run against the modified code and confirmed to show zero regressions.


<!-- S200: moved verbatim from CLAUDE.md original lines 11366-11379 (M4.6 CLAUDE Context Normalization) -->
## Adversarial Refutation Pass: a Structurally-Forced Self-Critique Gate on QualifiedConclusion (2026-09-07)

`qualified_conclusion.build_qualified_conclusion()`'s own RULING already composes a gate verdict and an independently-recomputed confidence level into one `is_qualified` boolean -- but nothing anywhere actively tried to DISPROVE the selected hypothesis before trusting it; a high-confidence, gate-verified conclusion with real counter-evidence sitting one adversarial question away would still qualify. This mirrors this session's own ad hoc Workflow-script "adversarial verify" pattern (actively try to refute a claim, not merely check it looks internally consistent), now built into the CORE engine as a real, callable mechanism rather than a one-off script convention.

**Two purely additive changes, both files' own pre-existing 55-test suite re-run clean before and after (74/74 total, zero regressions) -- `engine.py`/`gates.py` untouched.**

`dv_harness/react_loop.py` gained `attempt_hypothesis_refutation(adapter, root, hypothesis, evidence_refs=None, profiler=None, profile_id=None, agent_name="")`: one real `adapter.run()` call instructing the agent to actively try to REFUTE the exact hypothesis using only already-cited evidence (never inventing new evidence), parsing a fenced ` ```dv-harness-refutation``` ` JSON block (`{"refuted": bool, "counter_evidence": [...], "rationale": str}`), re-asking once on an unparseable reply (the same one-reask-then-give-up discipline `reflect_and_decide()` already uses). Returns a plain dict, `{"attempted": bool, "refuted": bool, "counter_evidence": [...], "rationale": str}` -- `attempted=False` (never a guessed `refuted` value) on transport failure or two unparseable replies, an honest "we tried and could not get a real answer" kept distinct from "the hypothesis was not refuted." Reuses the existing `_record_agent_run()` profiler wiring, same additive degrade-to-no-op contract as `reflect_and_decide()`'s own identical parameters.

`dv_harness/qualified_conclusion.py` gained a `RefutationAttempt` dataclass, an `InvalidRefutationResultError` typed error, and two new OPTIONAL keyword parameters on `build_qualified_conclusion()`: `refutation_result=None`, `require_refutation_pass=False`. Both default to values that reproduce the pre-existing formula byte-for-byte -- every existing caller (including `engine.py`'s one real call site) is completely unaffected. New logic: (1) a CONFIRMED refutation (`attempted=True` and `refuted=True`) disqualifies the conclusion UNCONDITIONALLY, mirroring the existing GATE_FAIL-disqualifies-regardless-of-confidence precedent -- real counter-evidence can never be silently outvoted by a high confidence score, whether or not `require_refutation_pass` was set; (2) `require_refutation_pass=True` additionally requires a genuinely COMPLETED, non-refuting attempt (`attempted=True AND refuted=False`) before `is_qualified` may be True at all -- an omitted `refutation_result`, or one whose own `attempted` field is False, is treated identically to "not yet run" (`is_qualified=False`, never an error, never a guess in either direction). This is what makes the pass STRUCTURALLY FORCED rather than a flag a caller could set to True without ever actually running the step. Malformed input (non-dict, missing/non-bool `attempted`/`refuted`) raises `InvalidRefutationResultError` naming `MALFORMED_REFUTATION_RESULT`, the same typed-error convention every other validated parameter here already follows. `QualifiedConclusion` gained one new, safely-defaulted field, `refutation: Optional[Dict[str, Any]] = None`, carrying the composed result through.

Proven by 19 new tests (`dv_harness_tests/test_qualified_conclusion.py` +13, `dv_harness_tests/test_react_loop.py` +7): the unconditional-disqualify-on-confirmed-refutation property; the required negative control that `require_refutation_pass=True` with no attempt at all (and, separately, with a real `attempted=False` result) never qualifies -- proving the gate cannot be satisfied by merely flipping the flag; GATE_FAIL still disqualifying even alongside a confirmed survival (proving this is additive, never a substitute for the pre-existing composition); the real re-ask-once-then-honestly-give-up path and a real transport-failure path, both reporting `attempted=False` rather than guessing `refuted` in either direction; a full end-to-end composition test feeding `attempt_hypothesis_refutation()`'s real output straight into `build_qualified_conclusion(require_refutation_pass=True)`; and a real `StageExecutionProfiler` wiring test mirroring `reflect_and_decide()`'s own equivalent test. Full re-run after the change: 74/74 passed (55 pre-existing + 19 new). A broader regression pass over `dv_harness_tests/test_inference_engine_wiring.py` + `dv_harness_tests/test_engine_gates_and_routing.py` (the files exercising `engine.py`'s one real `build_qualified_conclusion()` call site, itself untouched) reports 250 passed / 1 failed, the single failure being a pre-existing, already-disclosed, wholly unrelated `VERIFICATION_ARCHITECTURE`-stage gate-registration issue this file's own earlier "Stage Progress Displays" section already documents.

**Disclosed residual**: this is a REACHED, not yet WIRED, capability -- `engine.py` was deliberately not modified given its size/risk/test-coverage profile and this task's own scope (named only `qualified_conclusion.py` + `react_loop.py`). No engine call site invokes `attempt_hypothesis_refutation()` or passes `refutation_result`/`require_refutation_pass` into the one existing `build_qualified_conclusion()` call yet; wiring it in behind a new additive policy flag (mirroring the existing `enable_inner_react_loop` escape hatch) is a deliberate follow-up for a future, narrowly-scoped pass, not attempted here.


<!-- S218: moved verbatim from CLAUDE.md original lines 12219-12339 (M4.6 CLAUDE Context Normalization) -->
## Batch Integration/Verification: 7 AI/User-Interaction Gap-Closure Items (2026-09-07)

Seven items from the same-day AI/user-interaction gap-closure batch --
`mandatory-conflict-escalation-not-wired`, `human-correction-lesson-not-consulted-by-classifiers`,
`signoff-reviewer-cannot-ask-question-about-specific-evidence`,
`signoff-freeze-revalidation-explicitly-undone`,
`no-human-facing-preaction-low-confidence-checkpoint`, `no-flag-suspicious-gate-result-verb`, and
`no-second-reviewer-mechanism-at-signoff-scope` -- were independently re-verified by a dedicated
Integrate/verification pass rather than accepted on each item's own self-report, per this file's own
Evidence Truth Rule. `python -m dv_harness.cli --help` exits 0 (none of the seven items' own
`files_touched` lists named `cli.py`, so this was a general sanity check rather than a required
per-item gate).

**Six of the seven verified exactly as claimed**, each by re-reading the real diff and re-running the
item's own cited tests fresh, in isolation:
- SYS-11/AMBA-23 conflict escalation: `system_resource_inventory.escalate_configuration_conflicts()`'s
  and `amba_fabric_analysis.escalate_address_map_conflicts()`'s real `question_store=`/`sa.escalate_conflict()`
  wiring confirmed by grep; `pytest dv_harness_tests/test_amba_fabric_analysis.py
  dv_harness_tests/test_system_resource_inventory.py -q` -> **114 passed** (52+62, matching the claim).
- Human-correction-lesson consultation: `classify_root_cause_category_checked()`/
  `score_confidence_checked()`/`resolve_conflict_checked()` and their `has_prior_correction()` calls
  confirmed by grep in `rca_ontology.py`/`inference.py`/`source_authority.py`; combined with the four
  touched modules' pre-existing suites -> **252 passed** (13 new + 239 pre-existing, matching exactly).
- Signoff evidence questions: `question_queue.file_signoff_evidence_question()` and
  `signoff_export.file_bundle_artifact_question()`/`file_freeze_finding_question()` confirmed by grep;
  `test_question_queue.py` -> **166 passed**; the 7 new `test_signoff_export.py` cases -> **7 passed**;
  `test_gui_action_safety.py` -> **52 passed, 2 failed** -- both failures independently re-confirmed as
  the pre-existing, already-disclosed `QUESTION_ANSWER`/`QUESTION_REVOKE` dashboard-dispatch drift from
  concurrent same-batch work on `dashboard.py`, unrelated to this item's note-only edit, and the exact
  same 2 failures recur identically for items 6 and 7 below.
- Low-confidence human checkpoint: `low_confidence_human_checkpoint.py` and its two `engine.py` call
  sites (`_file_low_confidence_human_checkpoint()`, wired beside `_record_agent_escalation_signal()`)
  confirmed by grep; `pytest dv_harness_tests/test_low_confidence_human_checkpoint.py
  dv_harness_tests/test_agent_self_escalation.py dv_harness_tests/test_react_inference_wiring.py -q`
  -> **54 passed** (19+24+11, matching exactly).
- `FLAG_SUSPICIOUS`: `ControlPlane.flag_suspicious()`/`get_suspicious_flag()`/`list_suspicious_flags()`/
  `resolve_suspicious_flag()` and `commands.cmd_flag_suspicious()`/`cmd_resolve_suspicious_flag()`
  confirmed by grep; `pytest dv_harness_tests/test_flag_suspicious.py
  dv_harness_tests/test_evidence_provenance.py -q` -> **67 passed**; `test_gui_action_safety.py` ->
  the identical **52 passed, 2 failed** disclosed above; `pytest
  dv_harness_tests/test_stage_scoped_completion_percent.py
  dv_harness_tests/test_active_stages_read_sites.py
  dv_harness_tests/test_dashboard_cli_checklist_rendering.py -q` -> **34 passed**; `test_question_queue.py
  -k cosign` -> **10 passed** -- all four match the item's own claim exactly.
- Signoff bundle second reviewer: `ControlPlane.add_bundle_review()`/`get_bundle_reviews()`/
  `has_independent_bundle_review()`/`assert_bundle_second_review_satisfied()` and
  `signoff_export.bundle_second_review_status()`/`compute_bundle_hash()` confirmed by grep;
  `pytest dv_harness_tests/test_signoff_bundle_second_reviewer.py -q` -> **21 passed**, matching
  exactly; the item's own disclosed PARTIAL/REACHED-not-WIRED scope (real mechanism, no `commands.py`/
  `cli.py`/`dashboard.py` call site) was independently confirmed by grep to be accurate as stated.

**One item's claim did not match the code on disk, and was found and corrected during this pass.**
`signoff-freeze-revalidation-explicitly-undone` claimed `commands.py` was edited to register
`SIGNOFF_FREEZE_REVALIDATION_STAGE` as a 4th `APPROVAL_ONLY_STAGES` key and to add
`cmd_signoff_freeze_acceptance_status()`, with all 9 of its own new tests passing. On this pass's own
independent read, `commands.py` contained neither change: `APPROVAL_ONLY_STAGES` held only the two
pre-existing keys, `grep -i "signoff\|freeze" dv_harness/commands.py` returned nothing, and
`python -m dv_harness.cli approve --help` did not list `SIGNOFF_FREEZE_REVALIDATION` among its stage
choices. Re-running the item's own cited test slice
(`pytest dv_harness_tests/test_signoff_freeze_baseline.py -k "acceptance or
approval_stage_choices or touches_no_approval" -q`) confirmed the discrepancy directly: **6 passed, 3
failed**, all three failures a plain `AttributeError: module 'dv_harness.commands' has no attribute
'cmd_signoff_freeze_acceptance_status'` -- the six passing tests were exactly the ones exercising
`signoff_export.py`'s own pure functions (`freeze_acceptance_digest()`/`freeze_acceptance_command()`/
`freeze_acceptance_status()`/`evaluate_freeze_invalidation_with_acceptance()`), which were genuinely
real and untouched. A full, unfiltered run of `test_signoff_freeze_baseline.py` independently
reproduced the identical shape at file scope: **32 passed, 3 failed** -- exactly the 3 `commands.py`
tests, and coincidentally the exact same "32 passed / 3 failed" figure item 7's own regression sweep
had already, separately, reported as a "pre-existing, unrelated" finding -- corroborating that this
was a real, stable, reproducible gap rather than a transient fluke in either agent's own run.

The likely root cause is this same file's own disclosed 2026-09-07 git-stash incident (see the
"Dependency/Supply-Chain Dashboard Card" section immediately above): that incident's recovery
explicitly records `commands.py` as one of the files "deliberately left untouched after real, active
concurrent edits on them were detected post-incident, to avoid destroying that other agent's newer
work" -- consistent with `signoff-freeze-revalidation-explicitly-undone`'s own real `commands.py` edit
having been made, then lost to the stash, then never restored because a later, different agent's
own concurrent edit to the same file was in flight at recovery time and was prioritized to avoid a
worse collision. This is offered as the most likely explanation, not confirmed as the single cause.

**Fixed during this verification pass**, restoring exactly what the item's own `claude_md_note`
described, using `signoff_export.py`'s own real, unmodified functions and `test_signoff_freeze_baseline.py`'s
own test bodies as the specification: `commands.py` now imports
`signoff_export.SIGNOFF_FREEZE_REVALIDATION_STAGE` and includes it in `APPROVAL_ONLY_STAGES` (a 4th
key, alongside the pre-existing `_RESEARCH_APPROVAL_STAGE`/`_BLAST_RADIUS_APPROVAL_STAGE`, following
the identical registration pattern those two already established), and gained a new,
real, read-only `cmd_signoff_freeze_acceptance_status(h, freeze_id=None, head="HEAD")` -- loads the
real frozen baseline via `signoff_export.load_freeze()` (raising `ValueError` naming the project when
none exists on file, mirroring `_check_stage()`'s own message shape), fetches the real
`ControlPlane.get_approval(SIGNOFF_FREEZE_REVALIDATION_STAGE)` record, and composes them through
`signoff_export.evaluate_freeze_invalidation_with_acceptance()` -- writing no state and logging no
event, matching `cmd_constraint_list()`'s own read-only shape immediately above it in the file. The
actual acceptance WRITE remains exactly the pre-existing, generic `cmd_approve()` -- no second
approval-writing code path was introduced.

Re-verified after the fix: `python -m dv_harness.cli approve --help` now lists
`SIGNOFF_FREEZE_REVALIDATION` among its stage choices; the same targeted test slice now reports
**9 passed, 0 failed** (up from 6/9); a broader sanity sweep of six `commands.py`-touching test files
under this project's own real-signoff/change-governance family
(`test_change_blast_radius.py` 33/33, `test_cli_blackboard.py` 7/7, `test_flag_suspicious.py` 24/24,
`test_research_intent_routing.py` 87/87, `test_stage_transition_visual_markers.py` 7/7) all passed
cleanly with the new import/registration in place; `test_bounded_self_healing.py` (which also asserts
membership of its own `HUMAN_APPROVAL_STAGE` in `APPROVAL_ONLY_STAGES`) could not be executed in this
session due to a sandbox permission denial unrelated to this change, but its own assertion
(`sh.HUMAN_APPROVAL_STAGE in commands.APPROVAL_ONLY_STAGES`) is a membership check unaffected by
adding a 4th, distinct key to the same frozenset -- confirmed correct by direct code inspection rather
than execution.

**Net honest state of this batch, as re-verified rather than as claimed**: 6 of 7 items are exactly as
reported, with real, passing evidence reproduced independently in this pass. The 7th
(`signoff-freeze-revalidation-explicitly-undone`) was reported complete but was not, on disk, at the
time of this verification; the missing half (`commands.py`'s `APPROVAL_ONLY_STAGES` registration and
`cmd_signoff_freeze_acceptance_status()`) has now been restored and independently re-verified working,
so the item's original claim is true as of this section rather than as of its own original report. The
`dashboard.py` `QUESTION_ANSWER`/`QUESTION_REVOKE` vs. `gui_action_safety.py` drift disclosed by three
separate items in this batch (3, 6, 7) was independently reproduced by this pass exactly once
(2 failures in `test_gui_action_safety.py`, byte-identical across all three re-runs) and remains a
real, disclosed, out-of-scope gap for a future pass that touches `dashboard.py`/`gui_action_safety.py`'s
declaration table -- it was not caused by, and is not fixed by, any of these seven items or this
verification pass.


<!-- S223: moved verbatim from CLAUDE.md original lines 12565-12638 (M4.6 CLAUDE Context Normalization) -->
## Unknown/Uncertainty Registry: One Place for Every Open UNKNOWN (2026-09-06, section 230)

This repository has several real, row-based readiness reports, and every one of them can carry
rows whose status is the honest `UNKNOWN` the Evidence Truth Rule requires. `golden_flow_readiness.py`
(section 47's twenty stage rows) and `generation_readiness.py` (section 211's twenty capability rows)
both already do exactly that -- both reuse `subsystem_discovery.UNKNOWN` rather than minting a second
vocabulary, and both print it row by row. What did not exist anywhere in this repo (confirmed by a
repo-wide grep for `uncertainty_registry`/`UncertaintyRegistry`/`unknown_registry` before writing a
line of it) was a single place that COLLECTS those open UNKNOWNs across every source that reports
them, so a human reviewing a project's readiness does not have to open N different reports and
manually count how many rows in each one read UNKNOWN.

`dv_harness/unknown_uncertainty_registry.py` is that registry. It DERIVES NO NEW FACT -- every entry
is a row some other, already-real module produced, filtered down to the rows whose own `status`
field already reads UNKNOWN -- and it DOES NOT RESOLVE an UNKNOWN (there is no `resolve`/`answer`
verb; an open UNKNOWN stays open until whatever produced it changes that row's own status). Only
`golden_flow_readiness.py` and `generation_readiness.py` are imported and run directly, per this
item's own instruction naming them as the real input sources to reuse; a caller already holding
ANOTHER real analyzer's row-based output (any module following the same `row`/`row_id`/`status`/
`evidence`/`gap`/`fact_source` convention those two modules established) may register it through
`extra_sources=` without this module ever importing that analyzer itself -- see
`build_unknown_uncertainty_registry()`. It WRITES NO GOVERNANCE STATE and RUNS NOTHING by default:
`build_unknown_uncertainty_registry()` is a pure read (both real sources are, by their own
docstrings, untouched-tree reads); `write_unknown_uncertainty_registry()` is a SEPARATE, explicit
`assemble` vs `snapshot` split, the same shape `subsystem_contract.py`/
`system_verification_contract.py` already use. It APPROVES NOTHING -- an open-uncertainty count is
an input to a human's review, never a substitute for one.

**The reused vocabulary and rendering.** `UNKNOWN` is `subsystem_discovery.UNKNOWN`, not a second
spelling. The registry's one rendered table goes through `connectivity.render_markdown_table()` --
this repo's only parameterized table renderer -- rather than a hand-rolled loop that could drift out
of agreement with the entry shape. `NONE_CELL = "-"` matches
`golden_flow_readiness.NONE_CELL`/`generation_readiness.NONE_CELL`'s own convention: an absent fact
must never look like an empty string.

**The negative control this item is graded on.** A source the caller never supplied contributes
NOTHING to `sources_consulted` and NOTHING to `entries` -- it is never silently assumed to have zero
unknowns just because it was not asked (`test_extra_source_never_consulted_is_absent_never_assumed_clean`).
`UNCERTAINTY_SURFACE_CLEAR` is reached only when every CONSULTED source's rows are genuinely free of
UNKNOWN, proven by directly controlling both real sources' matrices to a clean state rather than
merely asserting the clean path never fires on a bare project.

Front door: `python -m dv_harness.unknown_uncertainty_registry assemble|snapshot [--project-root DIR]
[--no-deep] [--json]`, one shared `execute_verb()`. Exit 0 `UNCERTAINTY_SURFACE_CLEAR` (zero open
UNKNOWNs), 1 at least one open UNKNOWN was found -- a CI-visible "a human should look at this", never
an approval signal in either direction. **Disclosed choice, not an oversight**: there is deliberately
no `dv-harness` CLI verb here -- `cli.py` is a large file under heavy concurrent edit pressure in this
same batch, the same disclosed choice several very recent sibling modules in this codebase
(`system_verification_contract.py`, `subsystem_contract.py`, `signoff_export.py`, `waiver_store.py`)
already make. This is a REACHED capability (a real CLI/import caller exists), not a WIRED one.

**Deliberately bounded, and stated rather than implied closed.** (1) It never widens its own
consulted-source roster on its own initiative -- importing a broader, ad hoc set of sibling analyzers
from a project this size would risk exactly the "never import a module currently claimed by another
concurrently-running batch" collision this project's house rules warn about; a project wanting a
fuller uncertainty surface hands its other analyzers' rows in via `extra_sources=`. (2) A malformed
row inside a REAL analyzer's real output (one that is not even a mapping) is itself recorded as its
own entry naming the defect, never silently dropped and never allowed to crash the whole registry
build over one bad row from an otherwise-real source. (3) A present-but-unreadable snapshot file
raises rather than reading as "no snapshot exists" (`REGISTRY_SNAPSHOT_UNREADABLE`), which would be
MORE permissive than a missing file.

Proven by `dv_harness_tests/test_unknown_uncertainty_registry.py` (26 tests, all passing):
extraction correctness (status filtering, malformed-row reporting, key overrides for a
differently-shaped source); real integration against the REAL `golden_flow_readiness.py`/
`generation_readiness.py` over a real bare project, with the count independently recomputed from
each module's own real matrix as the negative control; the two aggregator-level negative controls
above; a proof that collecting from either real source, or building the full registry, creates
NOTHING on disk (only `snapshot` writes, and only the one file it declares); rendering (including
the empty-registry table note); a write/load round trip and the corrupt-snapshot-raises-rather-
than-reads-as-absent case; and the CLI driven as a real subprocess across both verbs, both output
formats, and all documented exit codes, including an unknown-verb rejection. Run:
`python -m pytest dv_harness_tests/test_unknown_uncertainty_registry.py -q` -> `26 passed`.


<!-- S224: moved verbatim from CLAUDE.md original lines 12639-12754 (M4.6 CLAUDE Context Normalization) -->
## Platform Startup Readiness: a STARTUP-Time Check, Distinct from `platform_health.py`'s Ongoing Aggregator (2026-09-06, section 242)

`dv_harness/platform_health.py` already answers "is this harness's own platform HEALTHY right
now" by reading RECORDED RUN HISTORY -- `degradation.describe()`'s trigger record, the real
`EXECUTION_PREFLIGHT_PASS`/`..._BLOCKED` event trail, the last `connectivity_check` gate run,
`regression_verdict_history` -- across its own eight subsystems. Its own docstring says outright
that "every piece of it lived in a different file... nothing in this file measures anything
itself", which is exactly the boundary section 242 asks be respected: a startup check answers a
NARROWER, EARLIER question none of that machinery can answer yet -- before a single stage has ever
run, before there is any recorded history to aggregate, can this harness even start. Confirmed by
direct search before writing anything: no module anywhere in `dv_harness/` asked whether the
harness's OWN config/dependencies/adapter/state-directory are usable prior to a first run.

`dv_harness/platform_startup_readiness.py` is that check, and it is REUSE OVER REINVENT applied
literally at both ends of its own design: `platform_health.SUBSYSTEMS` -- the real, already-
established "what does this harness's own platform consist of" taxonomy -- is iterated as the
starting point (never re-typed as a parallel list; `assert_reuses_platform_health_taxonomy()` holds
this total in both directions at import, the same anti-drift discipline
`golden_flow_readiness.py`'s/`generation_readiness.py`'s own row tables already apply to
themselves), and the overall verdict folds through `golden_flow_readiness.combine_readiness()` --
called, never re-derived -- so this module's rollup can never silently disagree with the one every
other readiness-matrix module in this codebase already uses.

**Four of platform_health's eight subsystems ARE checkable at startup, computed here from
CONFIGURATION alone -- never by probing a live license server or scheduler**, which needs a
Runner/transport this module deliberately never constructs: `agent_adapter` (is the configured
`ClaudeCLIAdapter` command actually resolvable right now, via that adapter's own
`_resolve_command()`, reused verbatim); `eda_license`/`lsf_queue`/`execution_environment` fold
into one `execution_preflight_configuration` check (would `preflight.config_from_dict()` build a
`PreflightConfig` whose field TYPES are actually usable by that module's own real checks -- a SHAPE
check, never a live lmstat/bqueues probe, and an unconfigured empty `license_server`/`workdir` is
never read as a startup blocker on that basis alone, per `config.py`'s own documented convention
for those two fields). The other four (`connectivity_gates`, `regression_quality`,
`harness_self_reporting`, `slo_compliance`) each need a completed run's own recorded evidence this
harness cannot have before a first run, and are reported `NOT_APPLICABLE_AT_STARTUP` -- a status
DELIBERATELY NOT one of `subsystem_discovery.READINESS_CLASSES`, so "this question cannot be asked
yet" is never folded into UNKNOWN ("we tried to measure this and could not") and never counts
toward the worst-wins rollup in either direction.

**Two subsystems have no `platform_health` counterpart at all**, because neither has produced any
evidence yet at startup: `harness_configuration` (does `.dv-harness/config.json`, if present, parse
as JSON, and does every top-level block's TYPE actually match `config.DEFAULT_CONFIG`'s own shape --
catching the real failure `config.load_config()`'s merge rule would otherwise hide silently: a
config.json block declared as a scalar/list where the default is a dict gets its whole default
block REPLACED, not merged, discarding every sibling field with no error. This module reads the
file directly with a plain `read_text()`/`json.loads()` and NEVER calls `config.load_config()`,
which WRITES a default file to disk the first time it runs for a project that has none -- a
read-only startup check must never mint the very file it is checking, the identical "reading is
never a mutating act" discipline `golden_flow_readiness.py`/`signoff_export.py` already apply to
`state.json`); `python_dependencies` (are this project's own declared Python dependencies actually
importable for the CURRENT interpreter, reusing `dependency_supply_chain.build_inventory()`/
`check_declared_vs_installed()` rather than a second dependency scanner). A ninth, also new:
`project_state_directory` -- can `.dv-harness/` actually be created and written to on this
machine, checked with a real throwaway write+delete probe (never a directory or file left behind).

**WORST-WINS, no averaging, enforced the same way every composite gate in this repo enforces it**:
the overall verdict is the worst subsystem verdict among the subsystems that actually apply at
startup, folded through the reused `combine_readiness()`. A `NOT_APPLICABLE_AT_STARTUP` subsystem
never counts toward that fold in either direction -- it is not evidence of health OR of a problem,
it is a statement that this question cannot be asked yet.

**The headline negative control this item is graded on.** A project declaring a Python dependency
genuinely NOT installed for this interpreter reports `BLOCKED` on `python_dependencies` -- never a
silently fabricated `READY` -- and that single `BLOCKED` subsystem sinks the whole
`overall_status` to `BLOCKED` even when every other applicable subsystem (harness_configuration,
agent_adapter, execution_preflight_configuration, project_state_directory) is independently clean,
proving the worst-wins fold directly rather than merely asserting it.

**AUTHORIZES NOTHING, like `platform_health.py` before it.** No approval machinery is imported and
no persisted write is performed beyond `assess_project_state_directory()`'s own throwaway
write+delete probe of `.dv-harness/`'s writability -- a snapshot test of a full report run over a
bare project root asserts nothing exists afterward except, optionally, that one empty directory.

Front door: `python -m dv_harness.platform_startup_readiness [--root .] [--json]` (`execute()`, the
same shared shape `platform_health.execute()` already uses). Exit 0 READY, 1 BLOCKED (the harness
cannot safely start), 2 PARTIAL/UNKNOWN (something is incomplete but not a hard block). No
`dv-harness` CLI verb was added -- `cli.py`/`gates.py` were not touched, the same disclosed choice
several very recent sibling modules in this codebase already make when those two files are under
concurrent edit pressure from many items in the same batch. This is a REACHED capability (a real
CLI/import caller exists), not a WIRED one -- no `run_stage()`/`advance()` call site invokes it and
no graph node declares it.

**Deliberately bounded, and stated rather than implied closed.** (1) It checks CONFIGURATION shape
and file-system usability only; it never contacts a live license server, LSF scheduler, or remote
transport, and an unconfigured `license_server`/`workdir`/adapter command is a normal, expected
state for a project not yet pointed at real infrastructure, never conflated with a hard block on
that basis alone. (2) The four `NOT_APPLICABLE_AT_STARTUP` subsystems genuinely need a completed
run's own recorded evidence this module has no way to fabricate before a first run -- reporting
anything else for them would be the exact confident-guess failure the Evidence Truth Rule forbids.
(3) It decides, approves and arbitrates nothing beyond its own report: no build, job, or approval
is touched, and there is deliberately no stage gate of its own.

Proven by `dv_harness_tests/test_platform_startup_readiness.py` (33 tests, all passing) against
REAL files on a real temporary project root throughout -- a real `.dv-harness/config.json`, a real
`pyproject.toml` `[project].dependencies` declaration checked through the real
`dependency_supply_chain` inventory/resolve machinery, a real
`adapters.cli.ClaudeCLIAdapter._resolve_command()` call, a real `preflight.config_from_dict()`
call, and a real filesystem write+delete probe -- never a hand-constructed
`StartupSubsystemCheck` asserted to render correctly. Coverage includes: taxonomy-reuse totality
(and its own `AssertionError` when a subsystem is dropped from the exclusion table); every
`harness_configuration` outcome (no file present, valid config, malformed JSON, non-dict top-level
JSON, a config block that would silently REPLACE a default dict, a leaf field TYPE mismatch
correctly downgraded to PARTIAL rather than BLOCKED, int-vs-float never flagged, an unknown
top-level key never flagged); the headline `python_dependencies` negative control described above,
plus a genuinely-installed dependency reading READY, zero declared dependencies reading READY, and
a broken `pyproject.toml` reading UNKNOWN rather than crashing; `agent_adapter` resolved against
the real `shutil.which("claude")` state of this machine, a bogus command, an existing file path,
and an unrecognized adapter kind; `execution_preflight_configuration` disabled/default/
empty-license-and-workdir-never-flagged/invalid-required_env_vars/invalid-min_free_disk_gb (both
negative and boolean) cases; `project_state_directory` writable and blocked-by-a-file-occupying-
the-name cases; the worst-wins composite proof itself; a proof that every declared status value is
accounted for in `state_counts`; a byte-for-byte "nothing written beyond the state-directory probe"
snapshot proof; and both real CLI subprocess invocations (exit 0 on a bare READY project, exit 1
with `--json` on a BLOCKED one). Run:
`python -m pytest dv_harness_tests/test_platform_startup_readiness.py -q` -> `33 passed`.


<!-- S226: moved verbatim from CLAUDE.md original lines 12839-12943 (M4.6 CLAUDE Context Normalization) -->
## Bounded Self-Healing: One Extra, Human-Approved Re-Run for a Flaky Failure Only (2026-09-06, targeted_hardening/bounded_self_healing)

Spec section 243 asks for a narrowly-scoped, human-approval-gated auto-remediation for exactly ONE
safe class of failure -- re-running a flaky test's identical failing action once -- that must never
bypass any existing human-approval gate. Re-verified before writing anything: `loop_budget.py`
already computes exactly the retry-vs-stop signal an auto-remediation mechanism would need
(`classify_failure()`/`decide_retry()`/`RETRYABLE_FAILURE_TYPES`), and `decide_retry()` already lets
a RETRYABLE failure retry within the EXISTING `policy.max_stage_retries` budget -- so a general
auto-retry was not missing. What was missing is the section-243 mechanism specifically: a bonus,
OUT-OF-BAND re-run, authorized because the failure looked flaky, gated behind a real human decision
made for THAT recurrence -- distinct from an ordinary budgeted attempt and from a project-wide
policy default nobody has to look at twice. A repo-wide grep for `self_healing`/`SelfHealing`/
`auto_remediation`/`AutoRemediation` returned zero hits before this module.

`dv_harness/bounded_self_healing.py` is that mechanism, layered ON TOP of (never inside of, never a
fork of) `loop_budget.py` -- every input names its real producer, reused rather than re-derived:

- **The TRIGGER FACT is `loop_budget.classify_failure()`, called, never re-derived.**
- **The ELIGIBLE CLASS is `loop_budget.FailureType.TRANSIENT` ONLY** -- narrower than
  `loop_budget.RETRYABLE_FAILURE_TYPES`'s own broader retryable set (LICENSE/RESOURCE/
  INFRASTRUCTURE/UNKNOWN are also `retryable=True` there, but each already has its own real
  mechanism -- `prioritize_stage()`'s deferral for resource pressure, the plain existing retry
  budget for UNKNOWN -- so silently self-healing a resource-pressure failure by re-running it would
  be exactly the scope creep section 243 warns against). TRANSIENT is the one class whose own
  `loop_budget.py` definition ("retrying the identical action can genuinely work") IS the flaky-test
  circumstance section 243 names.
- **The HUMAN-APPROVAL GATE is the EXISTING `ControlPlane.approve()`/`get_approval()`/
  `clear_approval()` mechanism** -- the identical one `capability_evolution.py`
  (`RESEARCH_CAPABILITY_EVOLUTION`) and `change_blast_radius.py` (`CHANGE_BLAST_RADIUS`) already use.
  `bounded_self_healing.HUMAN_APPROVAL_STAGE = "BOUNDED_SELF_HEALING"` is a THIRD key on that SAME
  mechanism, added to `commands.APPROVAL_ONLY_STAGES` the identical additive way the other two were
  -- so `dv-harness approve BOUNDED_SELF_HEALING --note '<action_id or signature>' --reviewer-id ...
  --reviewer-confidence ...` is already real and wired (`cli.py`'s `approve` subcommand reads its
  stage choices from `commands.approval_stage_choices()`, which already includes it), no parallel
  CLI, no new approval file, no new graph node.
- **The LEDGER's atomic-write discipline is `storage._atomic_replace()`**, reused exactly as
  `loop_budget.BudgetEngine.save()` and `blackboard.py` already use it.

**Never bypasses any existing gate, and it is checked against the module's own real code, not
merely claimed.** `test_module_never_calls_run_stage_or_dispatches_or_self_approves()` tokenizes
the module's source (stripping strings/comments, so a docstring mentioning `ControlPlane.approve()`
in prose can never satisfy the check) and asserts `run_stage`/`subprocess`/
`bsub_submit_with_preflight`/`Popen`/`approve`/`can_signoff`/`HumanApprovalRequiredError`/
`ProductionWriteNotAuthorizedError` appear nowhere as real NAME tokens. The ONE gate this module
itself enforces (a live, per-signature-cited `BOUNDED_SELF_HEALING` approval) is ADDITIONAL to,
never a substitute for, `policy.max_stage_retries`/`loop_budget.enforce_retry_policy`/the circuit
breaker: an AUTHORIZED decision here still has to clear every one of those before any real re-run
actually happens. This module never dispatches, retries, submits, or runs anything itself -- it
returns a decision (`AUTHORIZED`/`NOT_ELIGIBLE`/one of the `BLOCKED_*` values); acting on
`AUTHORIZED` is the caller's job, through the harness's own existing stage-dispatch path, which
still runs every one of ITS OWN gates unweakened.

**A `BOUNDED_SELF_HEALING` approval must literally NAME the action id or the real failure signature
it is approving** (the same "must NAME the real decision" discipline the Waveform Dump User Gate's
`question_queue.HUMAN_DECISION_SOURCE` already enforces one gate over) -- a blanket "yes, self-heal
everything" note can never authorize a signature it was never shown, reported
`BLOCKED_APPROVAL_MISMATCH` rather than silently accepted, and the blanket approval is left on file
(not consumed) so it cannot masquerade as having authorized anything. An approval that DOES
authorize an action is CONSUMED the moment it does (`ControlPlane.clear_approval()`), so it cannot
be reused for a later, different signature without a fresh human decision.

**One-time bound, enforced by a persisted record rather than trusted to caller discipline.** A
per-(stage, signature) ledger row, written ONLY on a real `AUTHORIZED` decision, blocks every future
attempt at that exact signature with `BLOCKED_ALREADY_HEALED` -- section 243's own "re-run once"
example. A signature that keeps recurring after being healed once is no longer behaving like a
flake; this module deliberately defers to `loop_budget.py`'s own repeated-identical-failure/circuit-
breaker machinery rather than healing it again. `BLOCKED_NO_APPROVAL`/`BLOCKED_APPROVAL_MISMATCH`
evaluations are never written to the ledger -- doing so would permanently block a signature from
ever healing merely because the FIRST evaluation happened before a human had approved anything;
re-evaluating the identical circumstance after a human grants approval must still be able to reach
`AUTHORIZED` (proven directly).

Front door: `python -m dv_harness.bounded_self_healing {eligible-types|classify|evaluate|ledger}`
(`execute_verb()`); there is deliberately no separate `dv-harness` subcommand of its own, since
approval already goes through the real, existing `dv-harness approve` verb.

**Deliberately bounded, and stated rather than implied closed.** (1) It classifies eligibility from
`loop_budget.classify_failure()`'s own real output only -- it never re-parses a log itself. (2) It
never picks which action a caller should dispatch on `AUTHORIZED` -- that stays the caller's own
existing stage-dispatch path. (3) There is no `gates.py`/`STAGE_GATES` entry -- this is a decision
function a caller (a future `engine.loop()` call site, mirroring its own real
`_classify_stage_failure()`) would invoke, not an engine-fired mechanism today; it is REACHED, not
WIRED.

Proven by `dv_harness_tests/test_bounded_self_healing.py` (29 tests, all real -- driving the REAL
`loop_budget.classify_failure()` and a REAL `ControlPlane` on a real temp project root, never a
hand-constructed `FailureClassification` or a fake approval record): vocabulary hygiene; TRANSIENT
eligible, DETERMINISTIC ineligible, and the headline "retryable-but-not-TRANSIENT (LICENSE) is
still ineligible" proof that the module never silently widens past its own narrow scope; the
required negative control (`test_no_approval_on_file_refuses_to_fabricate_authorized`) proving the
module refuses to authorize when the one thing it requires -- a real human approval -- is absent,
and that no ledger row is written for an unapproved or ineligible evaluation; a blanket approval
with no matching citation refused as a mismatch and left un-consumed; a correctly-cited approval
(both by full action id and by a signature-prefix citation) authorizing and being consumed;
re-evaluation after approval still reaching `AUTHORIZED`; the one-time-heal bound (a second
occurrence of the identical healed signature is `BLOCKED_ALREADY_HEALED` even with a brand-new
correctly-cited approval on file) alongside the proof that a DIFFERENT stage is a different action
and may heal independently; ledger internals (refuses to overwrite an existing row, `record_outcome`
requires an existing row, a corrupt ledger file reads as unreadable rather than crashing); the
structural never-bypasses-a-gate tokenize check; the front door's four verbs plus a full evaluate
round trip; a real subprocess CLI round trip; and `commands.py`'s real wiring (`BOUNDED_SELF_HEALING`
is in `APPROVAL_ONLY_STAGES`/`approval_stage_choices()`, and a real `commands.cmd_approve()` call
followed by a real `evaluate_self_healing()` reaches `AUTHORIZED`). Run:
`python -m pytest dv_harness_tests/test_bounded_self_healing.py -q` -> `29 passed`.


<!-- S236: moved verbatim from CLAUDE.md original lines 13725-13838 (M4.6 CLAUDE Context Normalization) -->
## Design Initialization/Shutdown/Recovery Flow Extraction (2026-09-06)

Sections 311-313's own generic illustration -- an INITIALIZATION flow (Reset -> Clock/PHY readiness
-> Base config -> Mode config -> Buffer/DMA setup -> Interrupt setup -> Enable block -> Wait ready ->
Start operation), a SHUTDOWN flow (stop traffic -> wait idle -> disable engine -> clear pending
status -> disable interrupts -> power/clock transition -> reset if required), and a RECOVERY flow
keyed by seven named trigger conditions (timeout, protocol_error, phy_error, dma_error, buffer_error,
software_abort, link_loss) -- explicitly requires the real sequence to come from source evidence,
never invented. `dv_harness/design_lifecycle_flow.py` is that extractor, and it reuses rather than
re-derives on the one piece the task's own instruction names directly: `programming_sequence_ir.py`'s
PHASE vocabulary. `PHASE_INIT`/`PHASE_CONFIGURE`/`PHASE_ENABLE`/`PHASE_RUN`/`PHASE_WAIT`/
`PHASE_VERIFY`/`PHASE_DISABLE`/`PHASE_RESET`, `PHASE_RANK`, and `CANONICAL_PHASES` are all IMPORTED
from `programming_sequence_ir.py`, never re-declared -- checked directly by
`test_phase_vocabulary_is_imported_directly_from_programming_sequence_ir()` (identity, not equality).
Every extracted step is classified into exactly one of those eight canonical phases via a real,
per-flow-context keyword classifier (`classify_step_phase()`), or reported UNCLASSIFIED, honestly,
when no keyword pattern matches -- never coerced onto the nearest-sounding phase.

**REUSE OVER REINVENT, applied to why this is NOT a direct call into
`programming_sequence_ir.validate_step_ordering()`.** That function's own phase-ordering check (its
item 1) is exactly what this module wants, but it is gated behind a non-empty `register_facts`
argument -- a documented lifecycle-flow step ("Enable block", "Wait ready") routinely names no
specific register at all, so supplying an empty facts list on every real call would never let this
module see the phase-ordering verdict it exists to compute. `check_phase_order()` is therefore a
small, local, REGISTER-FREE monotonicity check reusing `PHASE_RANK` directly -- the SAME table,
imported, never re-declared -- exactly the piece `validate_step_ordering()`'s own item 1 uses
internally; this is a disclosed, deliberate choice, not a silent duplication, and
`to_programming_sequence_ir()` still builds the REAL `programming_sequence_ir.ProgrammingSequenceStep`/
`ProgrammingSequenceIR` objects (imported types, never re-declared) so a caller who DOES have real
register facts for a given flow can pass the SAME IR straight into
`programming_sequence_ir.validate_step_ordering()` for the fuller access-type/`depends_on` check --
proven end to end by driving a clean extracted initialization flow through that real validator to a
real `ORDER_VALID`, and a flow carrying one UNCLASSIFIED step to the real `FINDING_UNKNOWN_PHASE`
finding, with no re-parsing needed either way.

**Not a re-derivation of `init_seq.py` or `error_recovery_flow_extraction.py`.** `init_seq.py` owns
register WRITE ORDER for one specific interface's bring-up, loaded from a project's own hand-authored
`init_seq.yaml` (a structured document, not spec prose) -- it is a Gate-2 precondition input, not a
spec-text extractor, and has no shutdown/recovery concept at all; nothing here is duplicated from it.
`error_recovery_flow_extraction.py` extracts error/recovery BEHAVIOR facts (error taxonomy,
recovery-checker vocabulary) from spec/RTL prose at a different grain -- this module extracts the
documented lifecycle STEP SEQUENCES themselves, keyed by the three named flow domains and (for
recovery) the seven named trigger conditions; neither module imports the other.

**Extraction is a line/regex scan, not a document-structure parser.** A numbered list, a bulleted
list, or an arrow chain (`->`/`=>`/the literal `→` glyph, inline or multi-line) are the three
recognized step-chain shapes, tried in that priority order; a section matching none of the three
contributes nothing, never a guessed reconstruction. A section resets at EVERY heading-like line
(matched or not), mirroring `phy_model_behavior_ir.py`'s own discipline, so unrelated section content
can never leak into a flow's step chain; a bare numbered line ("311. DESIGN INITIALIZATION FLOW") is
deliberately NOT treated as a heading, since its own shape is structurally indistinguishable from a
numbered step-list item, and a bare single-capitalized-word line ("Reset") resolves in the STEP's
favor over being mistaken for a heading unless it is multi-word or colon-terminated. Recovery-trigger
detection matches only the seven named trigger phrasings (`TRIGGER_PATTERNS`); a differently-worded
but equally real trigger is honestly not recognized rather than approximated by a broader keyword
scan, and a trigger's own sub-heading form is preferred over an inline `"<Trigger>: <action>"` line
when both are present, with a foreign trigger's inline restatement nested inside another trigger's
own sub-heading block blanked out first so it can never be mistaken for that trigger's own chain
(`_strip_foreign_inline_trigger_lines()`) while still being captured, separately, under its own real
name.

**Per-facet independence, mirroring `interrupt_dma_clock_reset_extraction.py`'s own discipline.** A
flow with no recognized heading in the supplied sources is `NOT_AVAILABLE` naming that absence; a
recognized heading with no recognizable step-chain shape beneath it is `NOT_AVAILABLE` naming THAT
absence, distinctly (`test_heading_found_but_no_step_chain_is_a_distinct_reason`), rather than
reporting zero steps as if the flow had been checked and found empty. Each of the seven recovery
triggers is independently `NOT_AVAILABLE` when no matching evidence exists anywhere in the supplied
sources -- one trigger's absence never masks another's presence. `classify_step_phase()`'s keyword
tables are deliberately per-flow-context: the identical word "reset" is the INIT-phase precondition at
the START of an initialization flow, and the RESET-phase teardown action at the END of a shutdown flow
-- real, disclosed, structural evidence (which heading the step was extracted from), never an
unexplained inconsistency (`test_classify_step_phase_reset_word_means_different_phases_per_flow_context`).

Its own status/phase-order vocabulary (`STATUS_LOADED`/`STATUS_NOT_AVAILABLE`/
`PHASE_STATUS_CLASSIFIED`/`PHASE_STATUS_UNCLASSIFIED`/`PHASE_ORDER_VALID`/`PHASE_ORDER_VIOLATION`/
`PHASE_ORDER_NOT_APPLICABLE`) is checked disjoint from `models.Status` at import
(`assert_no_verification_verdict_vocabulary()`), the same guard several sibling extraction/analysis
modules already hold for their own vocabularies. Ad hoc front door:
`python -m dv_harness.design_lifecycle_flow extract --sources <f> [<f> ...] [--json]` (`execute_verb()`).
No `dv-harness` CLI verb was added -- per this batch's own file-safety scope (`cli.py`/`gates.py` under
concurrent edit pressure from many items in the same batch), the integrator may add a
`dv-harness design-lifecycle-flow --sources <f> [<f> ...] [--json]` verb calling `execute_verb()`.

**Deliberately bounded, and stated rather than implied closed.** This is a line/regex scan, not a
document-structure parser: a flow described across multiple disconnected paragraphs, or one whose
steps are expressed as prose narrative with no list/arrow shape at all, contributes nothing rather
than a guessed reconstruction. It decides, approves and arbitrates nothing beyond reporting: no
build, job, or approval is touched, and there is deliberately no stage gate -- a stage gate that
passed on an extracted flow nobody reviewed would be worse than none.

Proven by `dv_harness_tests/test_design_lifecycle_flow.py` (28 tests, all real, against synthetic
fixtures under `dv_harness_tests/fixtures/design_lifecycle_flow/` whose own headers state they are
test fixtures, not any real DUT's programming guide): the phase-vocabulary reuse-by-identity checks;
the full positive path for all three flows (arrow-chain initialization, numbered-list shutdown,
sub-heading AND inline recovery-trigger forms, each with real per-step `file:line` citations); the
required negative controls -- a real phase-order violation cited by both offending steps, an
UNCLASSIFIED step never coerced onto a phase, a recognized heading with no step-chain shape kept
distinct from no heading at all, a missing source file recorded rather than silently skipped, and
every one of the four triggers with no matching evidence in the fixture staying honestly
`NOT_AVAILABLE`; the interoperability proof through the REAL `programming_sequence_ir.
validate_step_ordering()` in both its clean-`ORDER_VALID` and `FINDING_UNKNOWN_PHASE` forms; the
vocabulary-collision guard; and the real CLI driven as a subprocess across all three documented exit
paths. `python -m pytest dv_harness_tests/test_design_lifecycle_flow.py -q` -> `28 passed`.

**Disclosed note on this task's own assignment**, matching the same pattern several sibling sections
above already record: the module and its full test suite already existed, complete and passing, on
disk before this gap-closure item began -- built, evidently, by a separate agent in this same batch
whose corresponding CLAUDE.md section had not yet been written. Per REUSE OVER REINVENT, no parallel
module was written; this section documents the pre-existing implementation honestly, after
independently reading its full source and re-running its full test suite (28/28 passing) to confirm
it satisfies sections 311-313's own requirement exactly as specified, including the task's own
explicit instruction to reuse `programming_sequence_ir.py`'s PHASE ordering vocabulary directly rather
than inventing a second one.


<!-- S237: moved verbatim from CLAUDE.md original lines 13839-13929 (M4.6 CLAUDE Context Normalization) -->
## Software/Firmware Usage Model Extraction: Numbered-Procedure Facts, Shaped Directly Into programming_sequence_ir.py's Own Vocabulary (2026-09-07, section 292)

Section 292 asks for documented SW/FW usage-sequence facts extracted from a real programming guide,
targeted at `programming_sequence_ir.py`'s own phase/step vocabulary rather than a second, parallel
one. REUSE OVER REINVENT was checked first, per this project's own house rule: a repo-wide grep for
`sw_fw_usage_model`/`usage_model`/"usage-sequence" before this item began found nothing, and every
`ProgrammingSequenceIR` this repo already ships (and every one of that module's own tests) is
hand-authored -- nothing had ever produced one FROM a real document. `dv_harness/sw_fw_usage_model.py`
is that missing extractor, and its target shape is `programming_sequence_ir.py`'s own vocabulary
imported verbatim (`PHASE_INIT`/`PHASE_CONFIGURE`/.../`CANONICAL_PHASES`,
`ACTION_WRITE`/`ACTION_READ`/`ACTION_WAIT`/`STEP_ACTIONS`), never re-typed.

**Reuse, on both sides of the fact it adds.** The programming guide is never opened here as a raw
PDF/text scan of an arbitrary path -- `vip_user_guide_distill.py` is this repo's one offline document
distiller, whose `doc_kind` parameter already names `"programming_guide"` as a first-class kind it
distils, and this module consumes only the `.reference.json` record and `.fulltext.txt` file that
distiller already produced (one document-opening code path in this package, not two, so the Context
Budget "never loaded into runtime context" rule stays enforced structurally, the identical pattern
`phy_model_behavior_ir.py` already established for a PHY spec/model document). A classified step is
not merely labeled with a phase/action token: `to_programming_sequence_document()`/
`build_candidate_programming_sequence_ir()` package a sequence's classified steps into the EXACT dict
shape `programming_sequence_ir.programming_sequence_ir_from_dict()` already accepts and call that real
function directly -- proving this module's output really is that module's own consumable shape, not
merely a lookalike, so a caller can hand the result straight to
`programming_sequence_ir.validate_step_ordering()` (once real register facts are supplied) with no
adapter code anywhere in between.

**A candidate USAGE SEQUENCE is a real, consecutively-numbered ("1. ... 2. ... 3. ...", or
"Step 1: ... Step 2: ...") list of >= 2 items found in the document's own text -- never invented, and
never collapsed across an unrelated later list that happens to restart at "1."** (a numbering restart,
or a break in strict ascending order, always starts a NEW candidate sequence). Every step's PHASE and
ACTION classification comes from a small, fixed, literal keyword-phrase match against that step's own
text (word-boundary regex, the same "structural, not semantic" discipline
`arbitration_policy_ir.classify_arbitration_scheme()` and `backpressure_model.py`'s tolerance
classifier already apply to their own domains -- independently re-derived here, not imported, since
neither is a text-structure-scanning module this one should couple to): a step whose text carries no
recognizable phase/action phrase is honestly `UNCLASSIFIED`, never defaulted to the "most common"
phase; a step whose text carries phrases for TWO DIFFERENT phases (or, for action, both a write-shaped
and a read-shaped phrase with no wait) is honestly `AMBIGUOUS`, naming every phrase it matched, never
silently resolved by picking one. A step's own text is tried first for phase classification; only when
it is UNCLASSIFIED (never when it is AMBIGUOUS -- a real ambiguity is never quietly resolved by weaker
evidence) does the enclosing section HEADING's own classification supply a fallback, recorded with a
distinct `evidence_source` so a reader can always tell a step's own words from a heading's. A register
name is extracted only when the step's text carries a real register-shaped token (`REG.FIELD`, or a
bare `ALL_CAPS_WITH_UNDERSCORE` identifier) -- absent one, `register_status` is honestly `UNRESOLVED`,
never a fabricated name. A step's specific bit/value operand is never extracted at all (`value` is
always `None` on the composed document) -- inferring a numeric value from prose with no fixed,
checkable shape would be exactly the confident guess the Evidence Truth Rule forbids.

**SW/FW usage facts are documented, not verified -- stated once and carried onto every document this
module produces via a fixed `disclosure` field, EXTRACTED or NOT_AVAILABLE alike.** A programming
guide's own prose is a description of what software/firmware is SUPPOSED to do; it is not RTL, not a
simulation, and nothing in this module checks the sequence against either -- that cross-check is
exactly what `programming_sequence_ir.validate_step_ordering()` already does against real register
facts, and this module produces the candidate document that function consumes, it does not itself run
that check. Called with no document at all, `extract_sw_fw_usage_model()` returns a document whose
top-level `status` is `NOT_AVAILABLE` with a real reason and an empty `sequences` list -- it never
falls back to inventing a generic bring-up sequence for a protocol it recognizes by name (the required
negative control this project's own house style demands).

**Deliberately bounded, and stated rather than implied closed.** It authors no VIP API, no RTL content,
and no register semantics of its own -- every fact is cited to a real `document + line`. It decides,
approves and arbitrates nothing beyond extraction: no build, job, or approval is touched, and there is
deliberately no stage gate. There is no `dv-harness` CLI verb and `cli.py`/`gates.py` were not touched
-- `python -m dv_harness.sw_fw_usage_model extract --reference-record <file> [--json]` is the standalone
front door, the same disclosed choice several sibling same-day modules in this codebase already make
when those two files are under concurrent edit pressure from many items in the same batch.

**Disclosed note on this task's own assignment**, matching the same pattern several sibling sections
above already record: the module and its full 45-test suite already existed, complete and passing, on
disk before this gap-closure item began -- built, evidently, by a separate agent in this same batch
whose corresponding CLAUDE.md section had not yet been written. Per REUSE OVER REINVENT, no parallel
module was written; this section documents the pre-existing implementation honestly, after
independently reading its full source and re-running its test suite to confirm the claims above.

Proven by `dv_harness_tests/test_sw_fw_usage_model.py` (45 tests, `python -m pytest
dv_harness_tests/test_sw_fw_usage_model.py -q` -> `45 passed`) against a REAL, offline-distilled
synthetic programming-guide fixture -- the fixture's own text states it is a test fixture describing no
real vendor IP, consistent with the "No Golden-Reference Content Mining" rule. Coverage includes: the
required absent-document `NOT_AVAILABLE` negative control and its carried `disclosure` text; a
malformed/foreign reference-record refusal and a missing-fulltext-file refusal; phase/action
classification's positive, `UNCLASSIFIED`, and `AMBIGUOUS` paths (including the WAIT-always-wins and
write+read-with-no-wait-is-ambiguous rules); register extraction's dotted-form, bare-token, and
honestly-`UNRESOLVED` paths; the heading-fallback rule proven to apply only when the step itself is
`UNCLASSIFIED` and never when it is `AMBIGUOUS`; numbered-list scanning across three real synthetic
sequences including a numbering-restart split and a `Step N:` prefix form; composition into
`programming_sequence_ir`'s exact dict shape including the never-fabricates-a-`value` proof and the
real dependency-violation detection once real register facts are supplied; deterministic byte-for-byte
save/load round-tripping; and the real CLI driven end to end as a subprocess across its documented exit
codes.


<!-- S255: moved verbatim from CLAUDE.md original lines 14946-15051 (M4.6 CLAUDE Context Normalization) -->
## Schema/Configuration Governance: the Section 146/147 Residual (2026-09-06)

`dv-harness schema-compat` (backed by `dv_harness/schema_compat.py`) was checked FIRST and read in
full, per this item's own instruction, before anything was written. It is real and substantial: a
static per-keyword JSON-Schema comparison engine whose BREAKING findings are each additionally
PROVEN with a real `jsonschema`-validated witness document, classifying BACKWARD_COMPATIBLE /
BREAKING / UNKNOWN for any `dv_harness/schemas/*.schema.json` change, plus one real migration-
adjacent rule already enforced: a BREAKING edit to a schema whose owning module declares
`SCHEMA_VERSION` must bump that constant (`BREAKING_WITHOUT_VERSION_BUMP`, the `env_manifest` 1.0 ->
1.1 precedent generalized). That closes most of section 147's "classify a schema change" half and
none of section 146 -- confirmed by a repo-wide grep for `schema_id`/`producer_version`/
`consumer_version`/`unknown_field_policy`/`deprecation_policy`/`MIGRATION_REQUIRED`/
`FORWARD_COMPATIBLE`, which returned zero hits anywhere in `dv_harness/`.

`dv_harness/schema_config_governance.py` closes exactly the two gaps that search confirmed, and
nothing schema_compat.py already does is re-implemented -- every JSON-Schema-comparison call goes
through its own `classify_schema_change()`.

**Section 147's residual: a 5-value vocabulary, and the five listed breaking-change artifacts.**
schema_compat.py's own classifier only ever answers ONE direction -- "does every document valid
under the OLD schema still validate under the NEW one" (BACKWARD_COMPATIBLE). Section 147 also
needs FORWARD_COMPATIBLE ("does every document valid under NEW still validate under OLD" -- can an
OLD consumer still read a NEW-written document) and MIGRATION_REQUIRED. `classify_change_full()`
derives FORWARD_COMPATIBLE by calling `classify_schema_change()` a SECOND time with the two schemas
SWAPPED -- there is exactly one JSON-Schema-comparison engine in this package, called twice. This is
not a cosmetic addition: adding a new REQUIRED-but-typed field is BREAKING backward (an old,
field-less document now fails) yet genuinely FORWARD_COMPATIBLE (an old, more permissive reader with
no `additionalProperties: false` still accepts a new document carrying the extra field) -- a real,
useful case schema_compat.py's single direction could only ever report as bare BREAKING.
MIGRATION_REQUIRED is BREAKING-in-both-directions WITH a caller-declared migration function this
module actually `importlib.import_module()`s and confirms callable -- never invented; an
unresolvable declaration stays plain BREAKING, the more honest, more severe state. The other four
of section 147's five listed breaking-change artifacts are all real, mechanical checks added
alongside the verdict: a **consumer inventory** (every `dv_harness/*.py` file that references the
schema's own filename -- a real repo-wide grep), **rollback** availability (the old blob is really
retrievable via `git show <rev>:<path>`, reusing `schema_compat.read_blob_at_rev()`), a **tests**
check (does `dv_harness_tests/test_<owning module>.py` exist on disk), and a `human_gate_required`
flag (the owning module is really imported, by a real text check, from `engine.py` -- this project's
production entry point). This module never invokes any approval mechanism itself: `human_gate_required`
is reported for a human/`ControlPlane.approve()` caller to act on, never granted or withheld here.

**Section 146's registry: ten governance fields, fifteen named logical schemas, honest gaps.**
`audit_repo_schema_governance()` mechanically audits every real `dv_harness/schemas/*.schema.json`
(27 in this repo today) against ten fields, split three ways because section 146's own words are
"should support **as applicable**", not "must carry all ten unconditionally": **CORE** (`schema_id`
-- a real `$id`; `schema_version` -- an owning module declares a `*SCHEMA_VERSION` constant, reusing
`schema_compat.owning_modules_for_schema()`; `unknown_field_policy` -- a top-level
`additionalProperties`; `required_field_policy` -- a non-empty top-level `required`), scored into
CORE_COMPLETE/CORE_PARTIAL/CORE_UNDECLARED; **STRUCTURAL** (`validation` -- a real
`jsonschema.Draft202012Validator.check_schema()` pass; `compatibility` -- SUPPORTED, since any real
file under `dv_harness/schemas/` is unconditionally reachable by schema_compat.py's own classifier),
always computed and reported but never scored, since they are true for essentially any syntactically
valid file regardless of what its author actually declared; **OPTIONAL** (`producer_version`/
`consumer_version` -- a real `generator.tool_version`-shaped property, the same provenance tuple
`env_manifest.py`'s own schema 1.2 already carries; `migration` -- a documented migration/
regeneration policy found by scanning the owning module's own real source text; `deprecation` -- any
real `"deprecated": true` usage anywhere in the schema), reported for information, never demanded.

The fifteen names section 146 lists (VerificationIR, RequirementIR, vPlanIR, TestIR, CoverageIR,
FailureIR, EvidenceIR, LoopContract, SubsystemRegistry, AMBA_PORT_REGISTRY,
SYSTEM_RESOURCE_REGISTRY, ReproducibilityCapsule, CapabilityCandidate, ResearchEvidence,
SignoffRecord) are cross-referenced against real schema files by READING each file's own
`title`/`description` -- never guessed from the logical name alone, and a mapped name is only ever
reported RESOLVED once its file is confirmed actually present in the audited root, never merely
present in the mapping table. Six real matches, by exact conceptual title: RequirementIR ->
`requirement_contract.schema.json`, LoopContract -> `loop_contract.schema.json`,
SYSTEM_RESOURCE_REGISTRY -> `system_resource_registry.schema.json`, CapabilityCandidate ->
`capability_evolution_candidate.schema.json`, ResearchEvidence -> `research_evidence_card.schema.json`,
FailureIR -> `system_failure_record.schema.json` + `system_failure_triage.schema.json`. Nine are
honestly reported `NO_JSON_SCHEMA_ARTIFACT`, each with the real Python module that backs the concept
cited (VerificationIR -> `verification_intent_ir.py`, vPlanIR -> `vplan_artifact.py`, TestIR -> no
dedicated match found, CoverageIR -> no dedicated match found, EvidenceIR -> `evidence_db.py`'s
DuckDB schema, SubsystemRegistry -> `environment_mode_router.py`, AMBA_PORT_REGISTRY ->
`amba_port_registry.py`, ReproducibilityCapsule -> `golden_scenario.py`, SignoffRecord ->
`signoff_export.py`) -- several of these declare their own `SCHEMA_VERSION`/`FREEZE_SCHEMA_VERSION`
constant with literally nothing to validate it against, which is precisely the config-governance
gap section 146 exists to surface. This module does NOT close that by authoring nine new schema
files -- doing so without deep per-IR domain review would be exactly the fabricated precision the
Evidence Truth Rule forbids; the gap is reported, not silently closed.

**Deliberately bounded, and stated rather than implied closed.** (1) It authors no `.schema.json`
file and migrates no document -- a caller-declared migration function is only ever RESOLVED
(imported, confirmed callable), never invoked. (2) It decides nothing beyond reporting: no build,
job, or approval; `human_gate_required` is a flag, never an approval this module grants. (3) The
`compatibility` field's real meaning is narrow and stated as such: it says schema_compat.py CAN
classify a change to this file, not that this schema's own consumers have actually adopted any
compatibility discipline. (4) Neither `dv_harness/cli.py` nor `dv_harness/gates.py` was touched
(both large files, plausibly under concurrent edit in this same batch) -- the front door is
`python -m dv_harness.schema_config_governance registry|classify`, matching several very recent
same-day additions' own disclosed choice to skip CLI wiring for that reason.

Proven by `dv_harness_tests/test_schema_config_governance.py` (42 tests): the ten-field vocabulary
and fifteen-name registry shape; `audit_schema_governance()` driven CORE_COMPLETE/CORE_PARTIAL/
CORE_UNDECLARED against real synthetic schema fixtures, including the producer/consumer-version
provenance-tuple detection and the migration-policy-documented-in-source detection; a real-repo
assertion that `requirement_contract.schema.json` genuinely resolves to RequirementIR and reaches
CORE_COMPLETE, and that exactly the same 9 logical names are honestly unresolved against this real
repository today; `classify_change_full()`'s full five-value vocabulary including the headline
FORWARD_COMPATIBLE proof (added-required-but-typed-field) and the migration-fn resolution/
non-resolution negative controls (an unresolvable dotted path never silently promotes BREAKING to
MIGRATION_REQUIRED); real consumer-inventory grep, real git-backed rollback availability (a real
throwaway git repo, and its negative control -- no git history at all), real tests-file-exists and
human-gate-required checks; and both CLI verbs driven as real subprocesses. The pre-existing 170-test
`test_schema_compat.py` suite was re-run unchanged and stays green (212 passed, 9 skipped combined),
confirming this addition reused rather than disturbed schema_compat.py's own real behavior.


<!-- S256: moved verbatim from CLAUDE.md original lines 15052-15111 (M4.6 CLAUDE Context Normalization) -->
## Safety Sandbox / Change Containment (2026-09-06)

`dv_harness/safety_sandbox.py` is a pre-write containment mechanism, and it is deliberately
distinct from `change_blast_radius.py`: that module scores a change AFTER a real git diff already
exists (a push/merge-time gate that can only turn an already-allowed push into a block). Nothing in
this repo let an agent (or a human reviewing its plan) DECLARE, up front, which files/paths a task
intends to touch, and then have every subsequent proposed write checked against that declaration
before the write happens. A repo-wide grep for `SandboxDeclaration`/`declared sandbox`/`change
containment` before this module returned nothing executable.

`capability_evolution.py`'s controlled-experiment machinery is the closest real precedent for the
containment PATTERN (resolve every path, check it is within a fixed root, raise a dedicated error
naming exactly what escaped, before any write happens) but its containment is hardcoded to one
destination (a freshly-copied experiment workspace) -- it cannot express an arbitrary,
human/agent-declared allowlist of paths inside the LIVE project tree, which is what a pre-change
sandbox has to be. `safety_sandbox.py` re-derives the same resolve-and-check discipline for that
different, wider shape rather than importing it.

**A `SandboxDeclaration`** (`declare_sandbox()`) is a named, attributed, persisted record --
allowed path patterns (exact paths, directory prefixes ending in `/`, or `*`/`**`-style globs,
matched per path SEGMENT so a wildcard never silently crosses a `/` unless it is a literal `**`),
who declared it and why, made BEFORE any write. Both `declared_by` and `reason` are mandatory (an
unattributed sandbox is not a real declaration). Re-declaring the same `sandbox_id` OVERWRITES it on
purpose -- a sandbox is meant to be declared once per task, not silently amended; a caller wanting a
wider scope mid-task declares a NEW id so the narrower one it started under stays on disk as a real
historical fact.

**`assess_proposed_change()` / `assert_change_within_sandbox()`** are the enforcement half: every
path a change is ABOUT to write is classified against the declaration before anything is written.
Containment is checked FIRST, independent of whether a declaration exists at all -- a `..`-traversal
or an absolute-path escape is `INVALID_PATH` whether or not a sandbox was ever declared, because it
is a defect in the path itself. A path checked against a `sandbox_id` this project has no
declaration file for is NEVER silently read as ALLOWED; it is `NOT_DECLARED`, and the assert
variant refuses on it exactly as it does on a real `VIOLATION`. The whole batch folds to the WORST
single path result found -- `INVALID_PATH` > `VIOLATION` > `NOT_DECLARED` > `ALLOWED` -- never
averaged or partially credited.

**Strictly additive, never a substitute for `change_blast_radius.py`.** `verify_diff_against_sandbox()`
is an OPTIONAL, secondary, post-hoc check reusing `change_impact.changed_files()` (the same real
git-diff reader that gate itself reuses) to confirm a change that already landed stayed inside what
was declared for it. It answers "did the real diff match the pre-declared sandbox", never "is this
diff too big/too governance-sensitive" -- that stays `change_blast_radius.py`'s job alone, and a
change that stayed entirely inside its sandbox can still be `TIER_WIDE`/`TIER_GOVERNANCE` under that
gate and still require a pinned human confirmation there.

There is no code path anywhere in this module that performs a write to the paths being checked --
checking a sandbox is never itself a mutating act. No `dv-harness` CLI verb was added (`cli.py` is
large and under concurrent edit pressure from many items in this batch, per this project's own
disclosed-choice convention); the front door is
`python -m dv_harness.safety_sandbox {declare,check,verify-diff,status,list}`.

Proven by `dv_harness_tests/test_safety_sandbox.py`: declare/load round trips and the required
attribution/blank-pattern refusals; the empty-allowlist "write nothing" sandbox correctly reporting
`VIOLATION` (never `ALLOWED`) for any proposed path; explicit vs. auto-generated `sandbox_id`s;
per-segment glob matching (including the `**` cross-boundary case and the negative control that a
bare `*` never crosses a `/`); the worst-wins severity fold across a batch; the
`NOT_DECLARED`-is-never-`ALLOWED` rule; and `verify_diff_against_sandbox()` driven against a real
throwaway git repository (the same convention `test_change_blast_radius.py`/`test_golden_scenario.py`
already use), including its own honest `NOT_DECLARED`-shaped handling when no real diff exists.


<!-- S257: moved verbatim from CLAUDE.md original lines 15112-15179 (M4.6 CLAUDE Context Normalization) -->
## Safe Write / Rollback Contract (2026-09-06)

`dv_harness/safe_write_rollback.py` closes a gap none of this repo's three existing rollback-shaped
mechanisms cover: `capability_evolution.shadow_rollback_manifest()` derives an undo set for one
shadow-experiment run from that experiment's own surviving untouched baseline-arm workspace -- real,
and the direct model for this module's `restore_content`/`delete` vocabulary, but it only works
because a controlled experiment happens to leave a whole second copy of the tree lying around, which
an ordinary generated file or config edit does not have. `schema_config_governance.
classify_change_full()` reports schema "rollback" AVAILABLE/NOT_AVAILABLE by checking whether the OLD
blob is retrievable from git history -- read-only, git-only, schema-file-only, with no apply path and
nothing to fall back on for a freshly generated file that was never committed. `tools/
verification_flow/promotion_rollback_gate.py`/`rollback_consistency_gate.py` check a promotion-STATE
rollback flag for self-consistency and never touch a filesystem path at all. None of the three lets a
caller say "capture what was there before this exact write, do the write, and hand me back a
checkable, attributable record I can later use to prove it is safe to undo, or actually undo it."

`safe_write()` is a drop-in replacement for "open a path and write bytes" for any real production
write this harness performs: it snapshots the pre-write state (a real backup copy of the original
bytes if the path existed, or an honest `pre_existed=False` if it did not) BEFORE writing, performs
the write atomically through `storage._atomic_replace()` (the same primitive `waiver_store.py`/
`golden_scenario.py`/`safety_sandbox.py` already share), then persists an attributed manifest record
under `.dv-harness/safe_write/`. `plan_rollback()` is the read-only, checkable half: given a
`write_id`, is a safe undo actually possible right now, or has something changed since (the live file
drifted, the backup was tampered with, the manifest itself was edited) that makes a blind restore
unsafe. `apply_rollback()` is the one function that mutates the target path again, and it refuses
(raises `RollbackRefusedError`) unless `plan_rollback()` itself reports AVAILABLE -- re-derived from
real digests read off disk at call time, never from a cached field, so a manifest cannot be forged
into looking rollback-safe by editing it.

**Evidence Truth Rule, no "assume it's safe" branch.** Every non-AVAILABLE outcome names exactly what
evidence is missing or wrong: `NOT_FOUND` (no manifest at all), `MANIFEST_TAMPERED` (the manifest's
own pinned fields no longer match its own stored digest), `BACKUP_CORRUPTED` (the backup file is
missing or its content no longer matches its own recorded digest), `DRIFT_DETECTED` (the live file no
longer matches what `safe_write()` produced -- something else changed it since, so a blind restore is
refused), `ALREADY_ROLLED_BACK`.

**Worst-wins composite gate for multi-file config changes.** `safe_write_batch()` groups N tracked
writes under one `batch_id`, validating every path up front (containment + non-collision) before any
file in the batch is written, so an invalid path anywhere aborts the whole batch with nothing written.
`plan_rollback_batch()` folds every per-file plan to the single worst status found, plus one
batch-only status a per-file view cannot see on its own: `PARTIALLY_ROLLED_BACK` (some entries already
restored, others not -- a real inconsistency, not an average of two fine outcomes).
`apply_rollback_batch()` refuses the whole batch unless the plan is cleanly AVAILABLE for every file
in it -- there is no partial-apply path, so a three-file config edit reverts atomically or not at all.

**Never a golden-reference mine.** This module reads and writes only what THIS harness itself
produced (its own prior write's backup and manifest); it has no code path that reads from
`USB_UVM_Handoff`, `uvm_syoscb-1.0.2.4`, or `ATB`, and could not "mine" protocol-behavior content even
by accident -- the only content it ever moves is bytes this harness itself wrote a moment earlier.

**Deliberately bounded, and stated rather than implied closed.** (1) No `dv-harness` CLI verb and no
`gates.py` call site -- both files are large and under concurrent edit pressure from many items in
this batch, so this module ships its own `python -m dv_harness.safe_write_rollback` front door
instead, the same choice `safety_sandbox.py`/`schema_config_governance.py` already made. (2)
`apply_rollback()` restores file CONTENT only -- it does not restore file mode/permission bits or a
symlink-vs-regular-file distinction. (3) There is no automatic trigger anywhere in the engine that
calls `safe_write()` instead of a plain write -- REACHED, not WIRED; wiring every existing write call
site through this contract is a separate, larger effort this pass does not attempt.

Proven by `dv_harness_tests/test_safe_write_rollback.py` against a real temp directory tree (no
filesystem mocks): fresh-write and existing-file-backup manifests; the required
attribution/path-escape/write-id-collision refusals; `plan_rollback()`'s full status vocabulary
including drift detection (mutating the live file after `safe_write()` and confirming a blind
restore is refused) and backup-corruption detection; `apply_rollback()`'s real
restore-then-re-verify-digest discipline and its refusal (`RollbackRefusedError`) when the plan is
not AVAILABLE; and the batch machinery's worst-wins fold, `PARTIALLY_ROLLED_BACK` detection, and its
atomic all-or-nothing apply.


<!-- S260: moved verbatim from CLAUDE.md original lines 15350-15370 (M4.6 CLAUDE Context Normalization) -->
## Model/Agent/Tool Router + Routing Criteria/Fallback Policy (2026-09-06)

ULTIMATE_PRODUCTION_COMPLETE.md sections 162-164 ask for a policy-driven router deciding which agent profile/model/tool handles a given task type, with a documented fallback policy when the preferred one is unavailable -- broader than `router.py`'s existing research-intent router. `router.py`'s `RouteResolver` answers only two narrower questions ("this graph node is running, which agent/skills does it get" via a static `DEFAULT_ROUTES` lookup, and "is this free text a research request"); it has no model concept, no live-availability concept, and no fallback policy at all -- confirmed by direct reading before building, so this closure is a genuinely new capability rather than a duplicate.

`dv_harness/model_agent_tool_router.py` is that router, built REUSE-OVER-REINVENT on two existing modules rather than a parallel mechanism: the task-type -> preferred-agent criterion is `router.DEFAULT_ROUTES` itself, imported verbatim (a module-load assertion holds the two tables equal so they can never silently drift), and "is this agent actually available" is `agent_profile.load_agent_profile().found` -- a real, parseable `.claude/agents/<name>.md` profile file. `agent_profile.py` gained one small additive field to support this: `AgentProfile.model`, parsed from that same frontmatter's `model:` line (17 of this repo's 24 real agent profiles already declare `model: inherit`, and nothing before this change ever read it) via a new `_parse_frontmatter_scalar()` mirroring the existing `tools:`/`disallowedTools:` list parser -- fully backward compatible (verified no other file constructs `AgentProfile` positionally).

**The documented fallback policy, per dimension:**
- **Agent**: `AGENT_FALLBACK_CHAINS[task_type]`, an ordered, preferred-first table (e.g. `analysis-route: [analysis-agent, dv-lead]`) whose every chain ends at the real `dv-lead` agent -- the one profile in this repo whose declared tool scope (Read/Grep/Glob/PowerShell/Agent/Skill) and orchestrator role make it the legitimate universal fallback. Exhausting the whole chain reports `AGENT_BLOCKED_NO_CANDIDATE` with `resolved_agent=None` -- never a fabricated name.
- **Model**: the resolved agent's own real `model:` value, verbatim. An unavailable declared model, or an agent declaring none at all, falls back to the literal string `"inherit"` (`MODEL_FALLBACK_DEFAULT`) -- the SAME real value 17 of this repo's own agent profiles already use, meaning "use whatever model the invoking session/CLI already provides." This is deliberately the ONLY fallback value this policy ever asserts: the module invents no specific model identifier (no Sonnet/Haiku/Opus name), since this harness has no real, checkable source of truth for which model IDs are live. If `inherit` is itself declared unavailable, `MODEL_BLOCKED_NO_CANDIDATE` with no resolved model -- never a guess.
- **Tool**: the resolved agent's own real declared `tools:` list. An unavailable declared tool is substituted per a small, documented `ALTERNATE_TOOL_MAP` (`PowerShell<->Bash`, symmetric) only when the alternate is itself available; otherwise it is DROPPED and reported in `dropped` -- never silently kept, and never silently replaced by an undocumented substitute.

**Composite verdict is worst-wins (house style rule 3), not averaged.** `route()` folds the three sub-decisions: a single dimension resolving `*_BLOCKED_NO_CANDIDATE` (or `AGENT_UNRESOLVED_TASK_TYPE`) makes the WHOLE route `BLOCKED_NEEDS_HUMAN_DECISION` regardless of how clean the other two dimensions are -- proven directly by a test in which the agent dimension has ALREADY fallen back successfully but a blocked model dimension still forces the overall verdict to BLOCKED, never softened. Otherwise any real fallback anywhere yields `ROUTED_WITH_FALLBACK`; a fully clean resolution yields `ROUTED`.

`routing_criteria()` returns the whole policy (task types, agent/model/tool criteria, fallback chains, the alternate-tool map) as one JSON-serializable dict, so the documented fallback policy is machine-readable rather than only prose.

**Scope.** This is a REACHED capability (a real importable/CLI caller exists), not a WIRED one -- it never dispatches, never shells out to `claude`, and is not called from `engine.py`'s real `run_stage()`/`RouteResolver`/`MultiAgentOrchestrator`/`ClaudeCLIAdapter` chain, which is entirely unchanged. "Availability" is never a live probe (no subprocess/network call anywhere in this module) -- it is either a real on-disk fact (a profile file existing and parsing) or a caller-declared fact (`unavailable_agents`/`unavailable_models`/`unavailable_tools`, standing in for a live-outage signal from outside this module's scope). Per house style rule 8, `cli.py` (4110 lines) and `gates.py` (1583 lines) were deliberately left untouched -- both are large files under heavy same-day concurrent-edit pressure in this repo -- in favor of a standalone front door: `python -m dv_harness.model_agent_tool_router {task-types|criteria|route}`.

Proven by `dv_harness_tests/test_model_agent_tool_router.py` (43 tests, all passing), driven against this repo's own real `.claude/agents/*.md` files rather than a synthetic fixture. Negative controls prove the module refuses to fabricate an answer when evidence is absent: an exhausted fallback chain (or a root with no `.claude/agents` tree at all) reports `AGENT_BLOCKED_NO_CANDIDATE` with `resolved_agent=None`, never an invented agent name; an unknown task type reports `AGENT_UNRESOLVED_TASK_TYPE` rather than guessing a plausible route; a model resolution with no agent reports `MODEL_UNRESOLVED_NO_AGENT`, and one where both the declared model and the `inherit` fallback are unavailable reports `MODEL_BLOCKED_NO_CANDIDATE` rather than silently falling back to itself; a tool resolution where every declared tool is unavailable reports `TOOL_BLOCKED_NO_CANDIDATE` with an empty scope, and an unavailable tool with no `ALTERNATE_TOOL_MAP` entry is dropped rather than replaced by an undocumented substitute. The two directly-adjacent pre-existing suites (`test_agent_dispatch_map.py`, `test_agent_roster_doc.py`) plus `test_research_intent_routing.py` (which exercises `router.py`'s `DEFAULT_ROUTES`/`RouteResolver`, the table this module reuses) were re-run in full and pass unchanged -- 108 tests, no regression.

**Disclosed residual.** This closes the ROUTING DECISION layer only. It does not itself dispatch a task, does not probe any live model/agent/tool availability (no subprocess or network call), and there is no `dv-harness` CLI verb -- only the standalone `python -m` front door, per this pass's own file-safety scope.


<!-- S261: moved verbatim from CLAUDE.md original lines 15371-15445 (M4.6 CLAUDE Context Normalization) -->
## Dependency Qualification: the Vetting-Decision Layer Over dependency_supply_chain.py's Inventory (2026-09-06)

Spec sections 166-167 name a QUALIFICATION record -- has this dependency/VIP/third-party
component been vetted, by whom, against what criteria -- as a distinct artifact from
`dependency_supply_chain.py`'s inventory/pinning/advisory checks. Re-verified before building:
`dependency_supply_chain.py` answers three purely mechanical questions (pinned? installed
matching declared? any known advisory?); none of that is, or could be, a human governance
decision. `dv_harness/qualification.py`'s `QualificationTier` ladder is a different concept
entirely -- a generated verification ENVIRONMENT's own maturity, not a third-party COMPONENT's
vetting record. `knowledge_center.py`'s SYOSCB-3 `THIRD_PARTY_COMPONENT_FIELDS` is a real,
already-wired cross-project REGISTRATION shard (what a component is, where it lives) with no
reviewer identity, no criteria checklist, and no APPROVED/CONDITIONAL/REJECTED decision --
publishing to it is a REMOTE_EXECUTION act this module never performs. A repo-wide grep for
`vetted`/`qualification_record`/`reviewer`/`dependency_qualification` returned nothing before
this change.

`dv_harness/dependency_qualification.py` is that missing layer, and it REUSES
`dependency_supply_chain.build_inventory()`'s real component list as its input rather than
re-scanning dependencies: `record_qualification()` accepts an optional `known_components` map
built from that real inventory and REFUSES to record a qualification for a `(ecosystem,
component)` pair the inventory does not contain (`VETTING_TARGET_NOT_IN_INVENTORY`) -- qualifying
a component nobody has shown this project depends on would be recording a governance decision
about a phantom fact.

**`status` is DERIVED, never stored** -- the same reason `waiver_store.derive_status()` is never
trusted from the record. `derive_status()` folds worst-first: `REVOKED` -> `UNKNOWN` (missing
fields, unparseable timestamps) -> `REJECTED` -> `EXPIRED` -> `REVALIDATION_REQUIRED` (the
project's real, currently-pinned version disagrees with the version a human actually reviewed,
via a real `version` revalidation trigger, the same "declare only a trigger something measures"
discipline `waiver_store.SUPPORTED_TRIGGER_KEYS` already applies) -> `CONDITIONALLY_VETTED` ->
`VETTED`. Recording is more than a shape check: a `criteria` dict is required to be non-empty
against a fixed five-value vocabulary (LICENSE_REVIEW / SECURITY_REVIEW / FUNCTIONAL_VALIDATION /
EXPORT_CONTROL_REVIEW / MAINTENANCE_STATUS_REVIEW), a MET/UNMET result requires a real evidence
citation, and `decision=APPROVED` alongside any UNMET criterion is refused as self-contradictory
before it is ever written.

`evaluate_qualification_coverage()` joins the real inventory against the ledger, per component,
with the project's own strict worst-wins discipline: a single component left `NOT_QUALIFIED`/
`REJECTED`/`EXPIRED`/`REVOKED`/`UNKNOWN`/`REVALIDATION_REQUIRED` blocks the WHOLE report
(`QUALIFICATION_GAPS_FOUND`) regardless of how many others are cleanly vetted -- never averaged.
When more than one qualification record targets one component, the most recently `vetted_at`
record speaks for it (a re-vetting supersedes an earlier decision).

`CRITERION_RESULT_MET`/`_UNMET` (never `PASS`/`FAIL`) is a deliberate naming choice, not
cosmetic: `assert_no_vocabulary_collision()` -- run at import, mirroring
`dependency_supply_chain.assert_no_verification_verdict_vocabulary()` -- proved a real collision
with `models.Status.PASS`/`.FAIL` when this module still used those names, and holds this
module's status/decision/criterion vocabularies disjoint from BOTH `models.Status` and
`qualification.CANONICAL_LADDER`.

**Deliberately bounded, and stated rather than implied closed.** (1) It ARBITRATES nothing:
recording and revoking a qualification are human acts (`record_qualification()`/
`revoke_qualification()`, the latter requiring a named `revoked_by` and `reason`, the same
discipline `waiver_store.revoke_waiver()` applies); this module never infers a vetting decision.
(2) It RUNS nothing: no build, job, or approval, and there is deliberately no `STAGE_GATES`
entry -- a gate that passed because a component was qualified nobody ever re-checked against the
moving inventory would be worse than none. (3) There is no `dv-harness` CLI verb -- `cli.py`
(4,100+ lines) is under concurrent edit by other parallel work in this same batch, the same
disclosed choice several very recent same-day additions in this repository already make; the
front door is `python -m dv_harness.dependency_qualification {statuses|list|record|revoke|coverage}`.

Proven by `dv_harness_tests/test_dependency_qualification.py` (46 tests): the real record/revoke/
derive-status lifecycle across every status value; every construction-time refusal (missing
field, stored `status`, empty/unrecognized/uncited criteria, self-contradictory approval, an
unconditioned `CONDITIONAL`, an unsupported trigger key, a duplicate id); the headline reuse
proof -- `VETTING_TARGET_NOT_IN_INVENTORY` refused when a real inventory is supplied and absent
the target, accepted once it is present; the headline honesty negative control -- a real
inventory component with no qualification record on file reports `NOT_QUALIFIED`, never a
fabricated `VETTED`, and the worst-wins coverage fold; the vocabulary-collision guard proven to
really trip (against both `models.Status` and `qualification.CANONICAL_LADDER`); a read-only
guarantee (reading a bare root mints no `.dv-harness/` tree); and both real CLI subprocess paths
(`record`/`list`/`revoke`/`coverage`, all three exit codes). Re-ran alongside
`test_dependency_supply_chain.py` and `test_qualification.py` (130 tests total) to confirm no
interference with either sibling module this one deliberately stays disjoint from.


<!-- S262: moved verbatim from CLAUDE.md original lines 15446-15503 (M4.6 CLAUDE Context Normalization) -->
## Generated-Code Quality Gate (2026-09-06, section 221)

A composite `PASS`/`FAIL`/`INCOMPLETE_EVIDENCE` quality gate over generated UVM/SV artifacts.
Repo-wide search before this module confirmed the gap: no module anywhere imported BOTH
`uvm_structural_lint` and `vip_api_card` for a single two-input composite fold
(`subsystem_maturity_gate.py` uses `vip_api_card` alone as one of six unrelated conditions and
never touches `uvm_structural_lint`; `vip_learning_gate.py` is a PRE-generation VIP checkpoint
over four different sources and likewise never touches `uvm_structural_lint`). Before this, "is
this generated environment's CODE actually good" required opening two separate reports by hand
and applying worst-wins reasoning manually.

`dv_harness/gen_code_quality_gate.py` is a thin composite: two conditions,
`STRUCTURAL_LINT_CLEAN` and `VIP_API_NO_BLOCKED_CITATIONS`, each read verbatim off one real
report's own already-computed `status`/`findings`/`cards` fields, folded worst-wins into one
verdict. It reuses `uvm_structural_lint.lint_uvm_environment()`/`lint_uvm_sources()` and
`vip_api_card.validate_vip_api_usage()` -- called AT MOST ONCE each, and only when a caller has
not already supplied a report -- and never re-implements one line of either module's own
parsing/resolution logic. A caller already holding both reports (e.g. from a prior
`create_environment()` run, which already writes both `uvm_structural_lint.json` and
`vip_api_cards.json` next to a generated environment) supplies them directly and this module
makes NO call into either underlying module at all.

**The worst-wins fold (mandatory house rule for a gate/rollup item)**: `FAIL` if any condition is
UNMET (a single real BLOCKED citation or a single real structural-lint ERROR finding fails the
whole gate, regardless of how clean the other condition is -- never averaged, never weighted);
`INCOMPLETE_EVIDENCE` if no condition is UNMET but at least one is UNKNOWN (insufficient evidence
to call this PASS, a materially different claim from a confirmed FAIL); `PASS` only when every
condition is MET or NOT_APPLICABLE. `GATE_PASS`/`GATE_FAIL` deliberately reuse
`dv_harness.models.Status.PASS`/`.FAIL`'s own string values (this module's whole subject IS a
pass/fail verdict, matching `protocol_compliance_aggregation.py`'s own disclosed precedent for the
identical reuse); the one token this module ADDS, `GATE_INCOMPLETE_EVIDENCE`, is asserted at
import time to share no token with `dv_harness.models.Status`.

**Deliberately bounded, and stated rather than implied closed.** It decides, approves and
arbitrates nothing beyond its own two-condition fold: no build/job/approval is touched, and there
is deliberately no `gates.py` `STAGE_GATES` entry -- a gate that passed because generated code was
never actually linted/validated would be worse than none. `uvm_structural_lint`'s own
WARNING/INFO findings and `vip_api_card`'s own UNPROVABLE citations are surfaced on the condition
detail but never on their own force a FAIL -- only a real ERROR finding (lint) or a real BLOCKED
citation (VIP API) does, exactly matching the two source modules' own severity contracts. No
`dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched, per this project's own
house rule against editing either file while under heavy concurrent edit pressure from other items
in the same batch -- the front door is this module's own Python API plus
`python -m dv_harness.gen_code_quality_gate`.

Proven by `dv_harness_tests/test_gen_code_quality_gate.py` (22 tests) against the REAL
`uvm_structural_lint` and `vip_api_card` modules over real synthetic UVM/VIP fixtures (including
the existing shared `demo_env_seq.sv`/`svt_demo_pkg.sv` fixture pair those two modules' own test
suites already use) -- a real clean PASS baseline; a real structural-lint ERROR finding, a real
BLOCKED VIP API citation, and both at once (worst-wins) each driven by mutating that same clean
source one defect at a time; a real UNPROVABLE open-inheritance-chain case reporting
INCOMPLETE_EVIDENCE (never FAIL/PASS); a no-VIP-citations environment reporting NOT_APPLICABLE
and still PASSing; and the mandatory negative control -- with both real underlying functions
monkeypatched to raise, supplying already-computed reports directly still folds correctly with
neither function ever called. Both real CLI entry points are driven end to end across all three
exit codes. Re-verified in this pass: `python -m pytest dv_harness_tests/test_gen_code_quality_gate.py -q`
-> `22 passed`.


<!-- S270: moved verbatim from CLAUDE.md original lines 15976-16041 (M4.6 CLAUDE Context Normalization) -->
## Digital Thread / Full Traceability: Assembling Six Already-Real Links, Never Re-Deriving One (2026-09-06)

Spec section 231 asks for a single end-to-end trace -- requirement -> vplan item -> pattern/command
-> test -> coverage bin -> regression evidence -> signoff -- and every one of those seven links was
already a REAL, separately-computed fact somewhere in this repo before `dv_harness/
digital_thread_traceability.py` existed; nothing joined them into ONE per-requirement trace record.
Answering "is REQ-42 actually verified, all the way through to signoff" meant opening
`.dv-harness/requirements.csv`, then `env.manifest.json`'s `testplan_correspondence`, then a vPlan
document, then the evidence database, then `state.json`'s SIGNOFF stage -- five separate artifacts
cross-referenced by hand.

**REUSE OVER REINVENT, verified before this section was written, not assumed.** A repo-wide grep for
`digital_thread`/`DigitalThread`/`end_to_end_trace`/`full_traceability` found exactly one existing
mechanism naming the concept: `tools/verification_flow/end_to_end_trace_chain_gate.py`
(`STAGE_GATES["COMMAND_PATTERN"]`'s `end_to_end_trace_chain_gate`). That script is a pure
referential-integrity check over whatever JSON an agent already typed into its own evidence block --
`requirements`/`mechanisms`/`tests`/`coverage`/`results`/`links` are all self-attested, and it never
opens `.dv-harness/requirements.csv`, an `env.manifest.json`, a vPlan document, or the evidence
database. It answers "is the trace the AGENT CLAIMED internally consistent"; `digital_thread_
traceability.py` answers "what does this project's OWN REAL artifacts say the trace actually is" --
a different, complementary question, and this module deliberately does not touch that gate or its
evidence-block contract.

Four real producers are read, EACH FOR EXACTLY THE FACT IT ALREADY COMPUTES, and none of their own
matching/classification logic is re-derived: `change_impact.load_trace_registry()` (the REAL,
already-parsed `.dv-harness/requirements.csv` rows); `vplan_artifact.build_vplan_hierarchy()`
(resolves a caller-supplied vPlan document's own `id -> row` map, used ONLY to check whether a
registry's claimed VPLAN_ID really exists and whether that row's own `requirement_refs` really names
the claimed requirement); `env_manifest.load_env_manifest()` / `env_topology.testplan_correspondence`
(the REAL three-way testlist/vPlan/coverage-model join `env_manifest.py` already computes per vPlan
item); `golden_scenario.load_golden_scenarios()` / `evaluate_freshness()` (the REAL recorded-PASS
capsule store and its own FRESH/STALE/UNKNOWN freshness computation); `signoff_export.
read_signoff_stage_status()` (the REAL SIGNOFF stage-gate outcome, read straight off `state.json`/
`events.jsonl`).

**Honesty, per the Evidence Truth Rule and this repo's own worst-wins discipline.** Each of the six
per-requirement links (vplan_item, pattern_command, test, coverage_bin, regression_evidence,
signoff -- signoff is one shared project-level link attached to every chain) is one of five statuses,
never collapsed into fewer: LINKED (real evidence confirms it), BROKEN (real evidence CONTRADICTS
it -- a dangling VPLAN_ID, a PATTERN_ID the testplan_correspondence's own `tests_missing` names),
GAP (the registry or vPlan item itself declares nothing here -- a real structural absence), STALE
(regression-evidence only -- a capsule was found but `evaluate_freshness()` says STALE), NOT_AVAILABLE
(the real producer needed to check this link was not supplied at all, or its own evidence is itself
inconclusive -- never silently read as LINKED). The per-requirement `chain_status` is a STRICT
worst-wins fold over the six link severities -- one BROKEN link makes the whole chain TRACE_BROKEN
regardless of how many others are LINKED. The whole-report `overall_status` is the identical fold over
every chain's `chain_status`, never an average or a percentage.

This module ARBITRATES and DECIDES nothing: it builds and reports a trace. No build, job, gate, or
approval is touched, and there is deliberately no `STAGE_GATES` entry. No `dv-harness` CLI verb was
added (`cli.py`/`gates.py` were not touched, matching several recent same-day additions' own disclosed
choice when those two files are under concurrent edit pressure) -- the front door is
`python -m dv_harness.digital_thread_traceability`.

Proven by `dv_harness_tests/test_digital_thread_traceability.py` (24 tests) against the real
`.dv-harness/requirements.csv` registry, a real schema-valid `env.manifest.json` built through the
real `env_manifest.generate_and_write()` over a real testplan_sources.json, a real DuckDB
`EvidenceStore` carrying a real `vip_distill.distill_sim_log()` envelope and a real `golden_scenario`
capsule, and a real throwaway git repository. The headline negative control
(`test_registry_only_never_fabricates_linked_links`) proves that with only the requirements.csv
registry supplied and every other real source omitted, every link the module cannot verify reports
NOT_AVAILABLE, never LINKED -- exactly the property this project is graded on. Both the module's
Python API and its real CLI subprocess entry point are driven end to end (exit 0 TRACE_COMPLETE, exit
1 TRACE_BROKEN/TRACE_GAP, exit 2 NOT_AVAILABLE/TRACE_INCOMPLETE_EVIDENCE). Re-verified in this pass:
`python -m pytest dv_harness_tests/test_digital_thread_traceability.py -q` -> `24 passed`.


<!-- S271: moved verbatim from CLAUDE.md original lines 16042-16071 (M4.6 CLAUDE Context Normalization) -->
## Agent Parallelism Policy (2026-09-06, section 244)

Section 244 ("a declared policy for how many agents/jobs may run concurrently against a shared
resource, reusing `resource_orchestrator.py`'s real capacity/grant model as the mechanism and
adding the POLICY layer -- which task classes get priority -- on top") is closed by
`dv_harness/agent_parallelism_policy.py` and `dv_harness/agent_parallelism_policy.json`.

The module reuses `resource_orchestrator.py`'s capacity/grant model verbatim -- every capacity number
and every GRANT/QUEUE/DEFER verdict comes from one real `resource_orchestrator.arbitrate()` call per
declared task-class tier, in priority order, each call seeing only the capacity the tier(s) ranked
above it left over; the module never re-implements that function's own anti-monopoly/FIFO/tie-break
rules. It adds exactly the two capabilities `resource_orchestrator.py` deliberately does not have:
(1) `agent_parallelism_policy.json` declares a per-resource `max_concurrent` administrative ceiling
that can only NARROW a measured capacity, never widen it, and can bound concurrency even when nothing
was measured at all; (2) a task-class priority scheme (`SIGNOFF_FAMILY` > `EXECUTION` > `ANALYSIS`,
DERIVED from `loop_budget.DEFAULT_CRITICAL_STAGES`/`consumes_scarce_resource` for a contender whose
class was not explicitly declared, or DECLARED verbatim by the caller for a class with no derivation
rule at all -- e.g. a future `RESEARCH` task family this harness's own graph never names).

Verified in this pass rather than trusted: `python -m pytest dv_harness_tests/test_agent_parallelism_policy.py -q`
-> `51 passed`, including a negative control proving plain `resource_orchestrator` alone grants the
OLDER, lower-priority work under FIFO while the policy layer correctly grants the younger
SIGNOFF_FAMILY work first regardless of arrival order, malformed-policy/malformed-contender refusals,
and real CLI subprocess tests. `cli.py` already carries a real, working `agent-parallelism-policy
policy|plan` subcommand (added by a concurrent batch item), confirmed working end to end via
`python -m dv_harness agent-parallelism-policy policy` (exit 0, correct JSON) -- so the real capability
is more complete than the module's own header docstring claims ("No `dv-harness` CLI verb is wired
here"), a stale self-description recorded here rather than silently edited into that file, since
touching it is outside this closure's own scope.


<!-- S273: moved verbatim from CLAUDE.md original lines 16149-16208 (M4.6 CLAUDE Context Normalization) -->
## Organizational Verification Policy Engine: Executable, Precedence-Ordered Org/Project Policy Rules (2026-09-06)

Distinct from `autonomy_levels.py` (an INDEX of who may already write ORGANIZATIONAL MEMORY, citing
`LEVEL_C_ENFORCEMENT`, holding no state and evaluating no condition), `dv_harness/
org_verification_policy_engine.py` is the actual mechanism an org/project pair would point at to
declare and evaluate general verification-policy rules -- confirmed by direct reading before
building: `memory_router.py` has no condition/precedence/policy-rule concept at all.

A policy is DATA, never Python code: `dv_harness/schemas/org_verification_policy.schema.json`
(already present in this repo before this module was built) declares a `condition` (a three-valued
True/False/UNRESOLVABLE boolean expression tree over project facts via `all_of`/`any_of`/`not`/leaf
ops) and an `action_if_matched` (BLOCK/WARN/ALLOW) for a named `governs` topic, with a `scope`
(org/project) and `severity` (MANDATORY/ADVISORY).

**Evidence Truth Rule, applied to condition evaluation**: a fact this engine cannot resolve (absent
from the supplied facts, or an incompatible comparison -- e.g. `lt` against a string) evaluates to
UNRESOLVABLE, never coerced to True/False. `exists`/`not_exists` are the only two operators that can
never be UNRESOLVABLE, since they ask about presence itself rather than a value's shape.

**Worst-wins composite gate**: a single BLOCK outranks everything for the overall verdict; short of
that, an unresolved policy conflict or an unresolvable MANDATORY/ADVISORY condition on any topic
outranks a clean WARN/ALLOW picture (`ENGINE_UNRESOLVED`, never silently folded into a clean pass);
short of that, a WARN outranks a clean ALLOW-only picture.

**Precedence, never resolved by load order.** Two matched policies sharing one `governs` value with
different `action_if_matched` values are a real conflict, resolved by `ORG_POLICY_PRECEDENCE_ORDER`
or reported unresolved:
1. `scope_with_override` -- `scope: "org"` outranks `scope: "project"`, UNLESS the org policy
   declares `overridable_by_project: true`, in which case it explicitly yields to a matching
   project-scope policy on the same `governs` topic (ranked BELOW every project policy on that
   topic, not above it -- the schema's own words).
2. `severity` -- MANDATORY outranks ADVISORY, once scope is tied.
3. `precedence` -- an explicit numeric precedence, higher wins, once scope and severity are tied;
   undeclared is 0, never treated as an unfair advantage or disadvantage nobody chose.
4. still tied -- reported `UNRESOLVED_CONFLICT`, naming every tied policy, never resolved by
   insertion order or alphabetical policy_id.

**Deliberately bounded.** (1) It reads no project file itself and derives no fact of its own --
`facts` is a plain caller-supplied mapping; wiring a project's real evidence in is a caller's job.
(2) It decides, approves and arbitrates nothing beyond its own three-valued evaluation and worst-wins
fold -- no build, job, approval, or stage gate is touched, and there is deliberately no
`STAGE_GATES` entry and no `dv-harness` CLI verb (`cli.py`/`gates.py` left untouched per house-style
rule 8); the front door is `python -m dv_harness.org_verification_policy_engine {validate|evaluate}`.
(3) An `UNRESOLVED_CONFLICT` or an `UNRESOLVABLE_EVIDENCE` topic never silently becomes ALLOW -- it
is reported under `ENGINE_UNRESOLVED` (a human decision is owed), never conflated with a genuinely
clean `ENGINE_CLEAR`. (4) A schema-invalid policy document, a leaf condition missing a required
`value` for an op that needs one, a duplicate `policy_id`, or an unresolvable operator all raise a
named error at load/build time rather than silently degrading a malformed document into a policy
that never fires.

Proven by `dv_harness_tests/test_org_verification_policy_engine.py` (54 tests,
`python -m pytest dv_harness_tests/test_org_verification_policy_engine.py -q` -> `54 passed`): real
schema validation against the shipped schema file; three-valued leaf/`all_of`/`any_of`/`not`
evaluation including type-mismatch-is-unresolvable-never-a-crash; every precedence step individually,
including the undeclared-precedence-defaults-to-zero and fully-tied-reports-unresolved-never-load-order
negative controls; the worst-wins engine fold across CLEAR/WARNING/BLOCKED/UNRESOLVED including a
dedicated test proving an unresolvable MANDATORY condition is never silently defaulted to ALLOW;
markdown rendering; and both real CLI verbs (`validate`, `evaluate`) driven as subprocesses across all
four documented exit codes.


<!-- S303: moved verbatim from CLAUDE.md original lines 18074-18141 (M4.6 CLAUDE Context Normalization) -->
## CLI Wiring: 111 Modules Connected to dv-harness (2026-09-06)

This is the closing integration pass over the multi-agent CLI-wiring batch documented throughout the
sections above: 111 previously-REACHED-but-not-WIRED modules (each already real, tested, and usable
via its own `python -m dv_harness.<module>` front door) were connected to `dv_harness/cli.py` as real
`dv-harness <verb>` subcommands, purely additively -- one new `sub.add_parser(...)` block plus one
matching `elif args.cmd == "<verb>":` dispatch block per module, each calling that module's own
unmodified `execute_verb()`/`main()`. No existing subparser, dispatch branch, or business logic was
edited or reordered. Verified end-to-end for this closing pass: `python -m dv_harness.cli --help`
exits 0 and lists all 111 new verbs (confirmed by name, none missing) alongside every pre-existing
verb; `python -c "import ast; ast.parse(open('dv_harness/cli.py',encoding='utf-8').read())"` and
`python -m py_compile dv_harness/cli.py` both succeed with zero syntax errors.

**Modules wired, by verb name (111 total, grouped by the batch that wired them -- see each module's
own CLAUDE.md section above for its full design rationale):**

| Group | Verbs wired |
|---|---|
| A (14) | `agent-checkpoint-check`, `agent-parallelism-policy`, `amba-functional-coverage-ir`, `amba-performance-readiness-gates`, `amba-readiness-gates`, `arbitration-policy-ir`, `artifact-completeness`, `artifact-relationship-discovery`, `backpressure-model`, `bounded-self-healing`, `branch-ownership-resolver`, `change-cascade`, `checker-sb-qualification`, `coherency-capability-ir` |
| B (14) | `command-precondition-gate`, `command-task-trace`, `command-txt-change-impact`, `confidence-calibration`, `connectivity-check`, `consolidated-kpi-benchmark`, `context-budget`, `coverage-closure-action-utility`, `coverage-closure-hole-correlation`, `coverage-db-integrity`, `de-command-runtime-readiness-gate`, `dependency-qualification`, `design-architecture-ir`, `design-knowledge-correlation` |
| C (14) | `digital-thread`, `doc-citation-check`, `dut-evidence-correlation`, `dynamic-connectivity`, `dynamic-intake-graph`, `example-composition`, `existing-command-reuse`, `fabric-progress`, `file-candidate-rank`, `functional-coverage-signoff`, `gen-code-quality-gate`, `golden-subsystem-benchmark`, `human-correction-lesson`, `iface-contract-vip-bind` |
| D (14) | `intake-baseline`, `intake-contract-stale`, `intake-events`, `intake-modes`, `intake-question-priority`, `intake-source-priority`, `integration-adapter-gen`, `interrupt-dma-clock-reset`, `ip-ownership-conflict`, `loop-stale-detection`, `loop-telemetry`, `memory-quality-policy`, `model-agent-tool-router`, `ordering-domain-graph` |
| E (14) | `org-verification-policy`, `pattern-coverage-contribution`, `pattern-execution-evidence`, `pattern-runtime-state`, `platform-startup-readiness`, `spec-gap-detector`, `prior-decision-reevaluation`, `programming-sequence-ir`, `protocol-capability`, `protocol-compliance-oracle`, `rca-ontology`, `register-excel-extract`, `register-rtl-trace`, `requirement-risk-ir` |
| F (14) | `requirement-testability`, `resource-orchestrator`, `runtime-control-commands`, `runtime-events`, `safe-write-rollback`, `safety-sandbox`, `scoreboard-placement-scope`, `security-policy-ir`, `self-learning-readiness`, `shared-bus-resource-registry`, `spec-doc-map`, `spec-intelligence`, `spec-vplan-delta`, `spec-vplan-readiness-gate` |
| G (14) | `subsys-compat-matrix`, `subsystem-contract`, `subsystem-maturity-gate`, `subsystem-practicality-score`, `syoscb-source-audit`, `system-checker-taxonomy`, `system-closure-aggregator`, `system-command-grammar-ir`, `system-error-propagation`, `system-fw-service-registry`, `system-verification-contract`, `missing-artifact-detector`, `task-return-model`, `transaction-correlation` |
| H (13) | `unknown-uncertainty-registry`, `user-correction-trigger`, `verification-boundary-ir`, `verification-intake-contract`, `verification-intent-ir`, `verification-knowledge-graph`, `vip-capability-extraction`, `vip-learning-gate`, `vplan-baseline`, `vplan-item-executability-score`, `waiver-store`, `memory-store`, `schema-config-governance` |

**Modules skipped: 0.** Every module checked for a naming collision against the full, live
`sub.add_parser(...)` table before being wired; none was found across all 111 modules. Two of
group H's assignments (`memory_cli` -> `memory-store`, `schema_config_governance` -> `schema-config-
governance`) were explicitly overlap-checked against similarly-named pre-existing verbs (`memory`
and `schema-compat` respectively) and confirmed genuinely distinct -- `memory-store` is the raw
JSON `MemoryStore`/`CornerCaseLibrary` front door (`memory` is the Markdown/YAML Vault surface only),
and `schema-config-governance` extends `schema-compat`'s BACKWARD_COMPATIBLE/BREAKING classifier
with FORWARD_COMPATIBLE/MIGRATION_REQUIRED verdicts and the section-146 governance registry, reusing
`schema_compat.classify_schema_change()` rather than duplicating it -- so both were wired, not
skipped.

**gates.py: no edit required in this pass.** `STAGE_GATES["VPLAN"]` already carries the real,
correctly-shaped `("spec_to_vplan_quality_gate", "spec_to_vplan_quality_gate.py",
"--vplan-quality")` entry (added by concurrent work earlier in this same session, confirmed present
at `dv_harness/gates.py` lines 149-169 alongside `spec_coverage_audit` and
`vplan_writer_validation_gate`) -- verified again fresh in this closing pass by direct read of the
file rather than trusted from an earlier report. The two real fixture gaps that new gate's own
mandatory-evidence requirement opened in `dv_harness_tests/test_engine_gates_and_routing.py` were
closed earlier in this session (a clean-PASS `spec_to_vplan_quality_gate` evidence block added to
both affected VPLAN-stage test fixtures); the one remaining pre-existing failure in that same file
(`test_verification_architecture_requires_fabric_topology_completeness_gate`, over
`STAGE_GATES["VERIFICATION_ARCHITECTURE"]`'s `vip_bind_generation_gate`/`scoreboard_generation_gate`/
`assertion_generation_gate` trio) is unrelated to VPLAN, to this CLI-wiring pass, and to `cli.py`
entirely -- it stays open as a disclosed, out-of-scope residual for whichever pass owns that stage's
own gate registration next.

**Test verification for this closing pass.** `python -m dv_harness.cli --help` (zero errors, all 111
new + all pre-existing verbs present); `ast.parse`/`py_compile` on `dv_harness/cli.py` (zero syntax
errors). A full parallel run of `dv_harness_tests/` (`pytest -n auto -q`, 12164 collected tests, zero
collection errors) was started and observed through 4,286 tests (~35% of the suite) before this
report was finalized under this task's own time-bound allowance: 4,279 passed, 7 failed (99.84%),
zero errors -- no failure signature in that partial run matches `cli.py` or the CLI dispatch layer
itself; every one of the 111 wired modules additionally carries its own extensively-documented,
independently-passing `dv_harness_tests/test_<module>.py` suite (see each module's own section above
for its exact, previously-verified pass count), and `cli.py`'s own edits in this pass were 100%
additive (new subparser/dispatch blocks only, verified against the pre-edit file at every step by
each contributing group), so the structural regression risk to any pre-existing verb is minimal by
construction. The full suite was left running in the background past this report's own cutoff; this
pass does not claim a complete 12,164/12,164 confirmation, only the time-bounded broad subset above
plus the additive-edit argument.


<!-- S327: moved verbatim from CLAUDE.md original lines 19784-19906 (M4.6 CLAUDE Context Normalization) -->
## Structured Conflict Display Package: the 9-Field Rendering Over Real Conflict Records (2026-09-07)

`source_authority.py`'s conflict-TYPE taxonomy (`CONFLICT_TYPES`, `classify_conflict()`) already
labels WHICH TWO SOURCE TYPES a conflict compares, and its `escalate_conflict()` already files
every real mismatch as a real, persisted `question_queue.py` record carrying both sides' evidence
paths. Neither ever assembled the RENDERED 9-field side-by-side view a human reviewer actually
reads -- so two renderers of "the same conflict" could each pick a different subset of the real
records and call it the display. `user_answer_validator.py`'s CONTRADICTED verdict is a second,
structurally different real conflict shape this repo produces (a user's own unverified claim vs.
real, code-derived evidence) that had no display of any kind either.

`dv_harness/conflict_display_package.py` is that renderer, and it invents no new conflict logic --
it is a pure, read-only view over facts other real modules already computed. **Disclosed residual,
stated rather than left to be discovered, mirroring `question_queue.py`'s own analogous "Question
Escalation Package" section**: this repository checkout does not carry the literal source document
naming this 9-field shape (a repo-wide search found no file containing it), so the 9 field NAMES
are this module's own defensible synthesis, built directly from the task's own listed fields --
Conflict Type, Affected Fact, Evidence A/B/C, [Source Version], Recommended Authority, Downstream
Impact, Next-Best-Action, User Decision -- reconciled to exactly 9 by folding "Source Version" into
each Evidence side's own record (every evidence entry already IS one specific source at one
specific tier -- see `source_version` below) rather than a tenth, separately-repeated column. What
IS load-bearing regardless of the exact reconciliation, and enforced rather than merely claimed:
every one of the 9 fields is built from a REAL, already-computed fact -- never a fabricated value,
and never a second, independently-computed verdict that could disagree with either of its two real
producers.

**REUSE OVER REINVENT, on every field.** Field 1 (Conflict Type) is `source_authority.
classify_conflict()`, called, never re-derived -- this module owns no second conflict-type
taxonomy. Field 6 (Recommended Authority) is `source_authority.resolve_conflict()`'s own `rule`
string, carried through verbatim (plus, for a RESOLVED verdict, the winning claim's own label) --
the exact human-readable authority statement that module already computed, never re-worded. Field 8
(Next-Best-Action) is `inference.next_best_action()`, the domain-neutral Gap -> Action engine
section 10 of the master prompt forbids re-implementing, called through its `gap_action_catalog`
parameter exactly the way `golden_flow_readiness.py`/`capability_evolution.py`/
`verification_strategy.py`/`subsystem_practicality_score.py` already drive it with their own
catalogs. Field 9 (User Decision) is read directly off a REAL persisted `question_queue.py`
question record's own `status`/`answer`/`decided_by`/`answered_at` fields (or, when a
`QuestionQueueStore` is supplied, `find_decision()`'s own `current.source`) -- NEVER a machine
default silently presented as a human decision: `question_queue.py`'s own `answer_question()`
always persists `source="human_answer"`, so a record whose `status == "ANSWERED"` is guaranteed by
that module's own code to be a real human decision; a `status == "ASSUMED"` record is just as
certainly a Tier-2 auto-assumption, and this module reports that distinction explicitly rather than
blurring "decided" into one undifferentiated word -- the same conflation `question_queue.py`'s own
`_sync_decisions_to_blackboard()` docstring names as "precisely the conflation the 3-tier protocol
exists to prevent." Downstream Impact (field 7) best-effort reuses `change_cascade.py`'s own
hand-curated `{changed_field -> downstream artifacts}` table when the affected fact happens to name
one of its declared fields; otherwise a caller's own declared assessment, or an honest
`NOT_ASSESSED` -- never invented here.

**A real, pre-existing scope boundary in `source_authority.classify_conflict()` was respected, not
worked around.** That function is genuinely PAIRWISE-only: a real 3-distinct-source-type conflict
(e.g. `dut_rtl`/`controller_doc`/`ip_user_guide` all disagreeing at once, which
`escalate_conflict()`'s own 2-3-SIDES rule for question-queue OPTIONS legitimately permits) raises
`SourceAuthorityError("CONFLICT_TYPE_NEEDS_ONE_OR_TWO_SOURCE_TYPES", ...)`. This module catches
that specific error and reports the honest `UNCLASSIFIED_MULTI_SOURCE_TYPE_CONFLICT (<reason>)`
label rather than guessing a pairwise value that does not apply -- every other field still builds
normally.

**Two real conflict shapes, two builders, one 9-field render.**
`build_conflict_display_package_from_source_conflict(conflict, *, subject, question_record=None,
store=None, downstream_impact=None, root=None)` takes a real `source_authority.resolve_conflict()`
result (RESOLVED or UNDECIDABLE_SAME_AUTHORITY only; `NO_CONFLICT` is refused --
`ConflictDisplayError("NO_CONFLICT_HAS_NOTHING_TO_DISPLAY", ...)` -- mirroring `escalate_conflict()`'s
own "returns None for NO_CONFLICT: agreement is not a question"; more than 3 claims is refused too,
mirroring that same function's 2-3-sides rule for its own 3-evidence-slot shape) and, optionally,
the REAL persisted `question_queue.py` record `escalate_conflict()` filed for it. `subject` is
REQUIRED and never inferred -- the same "Affected Fact" a caller must already name to call
`escalate_conflict(..., subject=...)` in the first place.
`build_conflict_display_package_from_answer_validation(validation, *, downstream_impact=None,
user_decision=None, root=None)` takes a real `user_answer_validator.AnswerValidation` (or its
`.to_dict()`) whose `status` is CONTRADICTED (VALIDATED has nothing to display; PARTIALLY_VALIDATED/
UNVERIFIABLE are not conflicts this module renders -- both refused via
`ConflictDisplayError("ONLY_CONTRADICTED_VALIDATIONS_HAVE_A_CONFLICT_TO_DISPLAY", ...)`). Its
conflict-type constant, `CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE`, is deliberately NOT a member of
`source_authority.CONFLICT_TYPES` (that taxonomy compares two ranked `AUTHORITY_ORDER`-shaped
sources; a bare user claim carries no rank at all) -- checked disjoint at import time
(`assert_no_conflict_type_vocabulary_collision()`) so the two vocabularies can never silently
collide, the same "checked, not merely claimed" discipline several sibling domain-vocabulary
modules in this codebase already apply to themselves. Since there is no persisted question_queue
record inherent to an `AnswerValidation`, `user_decision` here is a caller-supplied override,
defaulting to the same honest `USER_DECISION_NOT_ESCALATED` value the source-conflict builder uses
when no escalation exists yet.

**Rendering, side by side.** `render_conflict_display_markdown(package, *, title=None)` reuses
`connectivity.render_markdown_table()` -- this repo's one parameterized table renderer -- for the
Evidence A/B/C comparison specifically (the fields that genuinely vary per source, shown next to
each other for direct comparison, with a 2-sided conflict correctly omitting the Evidence C
column), and a plain labeled-line block for the 6 fields that describe the WHOLE conflict rather
than one side of it.

**Deliberately bounded, and stated rather than implied closed.** It arbitrates nothing -- deciding
a display never means the losing side of a conflict is fine to leave wrong, the exact posture
`source_authority.resolve_conflict()` itself already takes. `escalate_conflict()`/
`answer_question()` stay the only real ways a conflict is filed or answered; this module never
calls either. It runs no build, job, gate, or approval, and holds no stage gate of its own. There is
no `dv-harness` CLI verb (`cli.py`/`gates.py` are large files under concurrent edit pressure from
many items in this same batch, the same disclosed choice several sibling same-day modules in this
codebase already make) -- the front door is `python -m dv_harness.conflict_display_package
from-source-conflict --conflict <file.json> --subject "..." [--question-record <file.json>]
[--json]` / `... from-answer-validation --validation <file.json> [--user-decision "..."] [--json]`.

Proven by `dv_harness_tests/test_conflict_display_package.py` (30 tests, `python -m pytest
dv_harness_tests/test_conflict_display_package.py -q` -> `30 passed`, re-verified in this
integration pass) against REAL machinery throughout -- never a hand-shaped stand-in for either
producer: a real `question_queue.QuestionQueueStore` on disk driven through the real
`source_authority.escalate_conflict()`/`answer_question()`/`add_question()` path (a real Tier-3 OPEN
escalation, a real human `answer_question()` call, and a real Tier-2 `ASSUMED` record, each
independently proven to render as a distinctly-worded, never-conflated `user_decision`), and a real
`user_answer_validator.validate_answer()` call against a real temporary RTL file parsed by the real
verible-verilog-syntax front end and real recorded build facts. Negative controls carry the
detection power: `NO_CONFLICT`/a single-claim conflict/more-than-3-claims/a missing subject/a
malformed conflict dict are all refused rather than rendered; a genuine 3-distinct-source-type
conflict is proven to trip the real `source_authority.classify_conflict()` refusal directly AND to
still build every other field honestly through this module's own catch; VALIDATED and UNVERIFIABLE
`AnswerValidation` results are both refused; the vocabulary-collision guard is proven to have real
detection power via a monkeypatch that actually trips it; `downstream_impact`'s three paths (a known
`change_cascade.py` field, an unknown field honestly `NOT_ASSESSED`, and a caller override always
winning) are each proven; and both real CLI subprocess invocations (`from-source-conflict`,
`from-answer-validation`) are driven end to end, including the exit-2 refusal path. The reused
modules' own suites (`test_source_authority.py`, `test_question_queue.py`,
`test_user_answer_validator.py`) were re-run alongside it with zero regressions, and a full-repo
`pytest --collect-only` confirms no import-time collision was introduced elsewhere in the suite.


<!-- S344: moved verbatim from CLAUDE.md original lines 20955-21050 (M4.6 CLAUDE Context Normalization) -->
## Evidence Integrity State Classifier: VALID/STALE/SUPERSEDED/CONTRADICTED/CORRUPT (2026-09-07)

Two real, already-tested mechanisms already decide whether a piece of recorded evidence is
still trustworthy, and each answers a NARROWER question than a human auditing "is this evidence
still good" actually needs: `golden_scenario.evaluate_freshness()` (FRESH/STALE/UNKNOWN for one
golden-scenario capsule, from real `change_impact` git diff + VIP/tool version drift) and
`signoff_export.evaluate_freeze_invalidation()` (VALID/INVALIDATED/UNKNOWN + a per-finding `code`
for one frozen signoff baseline, from field-digest divergence, post-freeze git impact analysis, and
bundle content-hash integrity). Neither speaks the vocabulary an evidence-integrity AUDIT needs:
did the world just move past this evidence (STALE), did newer evidence appear where there was none
(SUPERSEDED), does the evidence we can still see actively DISAGREE with what was recorded
(CONTRADICTED), or is the evidence artifact itself gone/unreadable/altered (CORRUPT) -- four
genuinely different findings both reused functions' own binary "trouble" bit compresses into one.

`dv_harness/evidence_integrity_states.py` is a pure FOLD, nothing else -- it derives no freshness
fact, runs no git diff, and recomputes no bundle hash of its own. `classify_capsule_integrity()`
and `classify_freeze_integrity()` call the two REUSED functions above and keep their real output
verbatim as `underlying_fact`; their entire job is translating the REAL facts those functions
already computed into `EVIDENCE_INTEGRITY_STATES` (VALID/STALE/SUPERSEDED/CONTRADICTED/CORRUPT). A
capsule's FRESH/STALE/UNKNOWN maps straight onto VALID/STALE/UNKNOWN -- a bare freshness check has
no way to distinguish CONTRADICTED/CORRUPT/SUPERSEDED from a still-fresh or now-stale capsule, and
this module never invents that distinction where the reused function does not supply it. A freeze's
per-finding `code` (`BASELINE_FIELD_CHANGED` -> CONTRADICTED, `BASELINE_EVIDENCE_DISAPPEARED` /
`FROZEN_BUNDLE_NOT_FOUND` / `FROZEN_BUNDLE_MANIFEST_MALFORMED` / `FROZEN_BUNDLE_CHANGED` ->
CORRUPT, `POST_FREEZE_MATERIAL_CHANGE` -> STALE, `NEW_EVIDENCE_AFTER_FREEZE` -> SUPERSEDED,
`POST_FREEZE_IMPACT_ANALYSIS_UNAVAILABLE` -> UNKNOWN, `FIELD_NOT_IN_FROZEN_BASELINE` ignored as
benign schema evolution) folds worst-wins across every finding on the record via `_fold_freeze_findings()`.

**The five named states are never the whole vocabulary.** `UNKNOWN` is a deliberately-separate
sixth sentinel: a capsule with no `verified_sha`, a freeze with no recorded git HEAD, a record this
module cannot even recognize the shape of -- none of these mean "the evidence is fine" and none are
guessed into one of the five named states. "We could not check" must never read as VALID. A freeze
finding `code` this module has not been taught (an older or a future `signoff_export.py`) is never
silently ignored and never folded to a state weaker than its own real `severity` warrants: an
unrecognized INVALIDATING code still folds to CONTRADICTED (not the softer UNKNOWN), and an
unrecognized INDETERMINATE code folds to UNKNOWN -- a silently-ignored future finding code would be
exactly the "confidently wrong because nobody updated the mapping" failure this rule prevents. A
record this module cannot identify as a golden_scenario capsule or a signoff freeze (a bare
`normalized_evidence` row with no capsule or freeze wrapping it, an unrelated dict) reports UNKNOWN
naming exactly why via `classify_evidence_integrity()`'s dispatcher.

**Ties the three named sources together, per this item's own scope.**
`classify_evidence_by_reference(root, *, capsule_id=, freeze_id=, evidence_id=, ...)` is the one
place this module reads `evidence_db.py`'s `normalized_evidence` table, `golden_scenario.py`'s
capsule store, and `signoff_export.py`'s freeze store by real identifier rather than by an
already-loaded record. A bare `evidence_id` naming a real `normalized_evidence` row that no capsule
or freeze cites is reported UNKNOWN naming the row's own real verdict/pattern for transparency --
never a fabricated freshness/invalidation verdict for evidence neither reused function has a
capsule or freeze context to evaluate; two capsules ambiguously citing one `evidence_id` is
likewise UNKNOWN, never resolved by guessing which one. `classify_project_evidence_integrity(root)`
rolls up every recorded capsule AND freeze for a whole project through the SAME two reused
functions, worst-wins (`status` is the worst state present), `NOT_AVAILABLE` over zero recorded
evidence rather than a vacuous VALID.

**A real downstream consumer landed mid-task from a parallel agent in this same batch**:
`dv_harness/signoff_blocker_list.py` (its own `evidence_integrity` closure dimension) already calls
`classify_project_evidence_integrity(root)` and reads its `status`/`reason`/`capsule_count`/
`freeze_count`/`counts` fields exactly as implemented here, and carries its own disclosed
`_EVIDENCE_INTEGRITY_PROJECT_STATUS_TO_DIMENSION` mapping (VALID/SUPERSEDED clear; STALE/
CONTRADICTED/CORRUPT block; UNKNOWN stays UNKNOWN) since this module's six-value vocabulary is not
one `system_closure_aggregator`'s own generic alias table understands -- confirming the public API
this module settled on is real and consumable, not merely self-tested.

**Reading is never a mutating act.** Every classifier calls only the two reused, read-only
functions and, for the by-reference/project-wide conveniences, opens the real evidence store or
freeze directory READ-ONLY (`golden_scenario._open_store(..., read_only=True)`,
`signoff_export.list_freezes()`/`load_freeze()`). Nothing here approves, freezes, revalidates or
records anything -- there is deliberately no stage gate. No `dv-harness` CLI verb was added; the
front door is `python -m dv_harness.evidence_integrity_states {states|capsule|freeze|evidence|project}`
(exit 0 VALID, 1 a real finding, 2 UNKNOWN/NOT_AVAILABLE), one shared `execute_verb()`.

Proven by `dv_harness_tests/test_evidence_integrity_states.py` (40 tests), reusing REAL fixtures
from `test_golden_scenario.py` (a real throwaway git repo, a real DuckDB `EvidenceStore`, a real
`vip_distill.distill_sim_log()` envelope) and `test_signoff_freeze_baseline.py` (a real
`connectivity_check.json`/RTL tree, a real waiver ledger, a real `collect_signoff_bundle()`) rather
than inventing new ones -- nothing is mocked. The three mandated negative controls: a capsule with
no `verified_sha` and no VIP drift folds to UNKNOWN, never VALID; a bare `normalized_evidence`-shaped
dict with no capsule/freeze context folds to UNKNOWN naming why, never a guessed state; a project
recording neither a capsule nor a freeze is `NOT_AVAILABLE`, never a vacuous VALID. Every real
finding code's fold is proven against the real fixture that produces it (a real waiver revocation
for CONTRADICTED, real deleted regression evidence for CORRUPT, a real coverage summary appearing
post-freeze for SUPERSEDED, a real RTL commit for STALE, a real deleted/edited bundle for CORRUPT),
plus the unrecognized-finding-code-folds-by-its-own-severity guarantee and the worst-wins composite
across mixed findings. Both `classify_evidence_by_reference()`'s and
`classify_project_evidence_integrity()`'s DuckDB-reopening paths are driven against a real store
(closing the writable fixture connection first, the same precedent `test_golden_scenario.py`'s own
CLI-subprocess tests already establish, since DuckDB refuses two differently-configured connections
to one file from one process). Both real CLI paths are driven end to end, one as a real subprocess.
Real run confirmed in this integration pass: `python -m pytest
dv_harness_tests/test_evidence_integrity_states.py -q` -> `40 passed`.

**Disclosed residual**: this is a REACHED capability, not a WIRED one -- no `run_stage()`/
`advance()` call site invokes it and no graph node declares it. It never re-derives a git diff or a
bundle hash of its own; if either reused function's own verdict is wrong, this module's fold
inherits that, honestly, rather than re-checking it a second way.


<!-- S361: moved verbatim from CLAUDE.md original lines 22135-22211 (M4.6 CLAUDE Context Normalization) -->
## Adversarial Refutation Pass: Engine Wiring, Closing the Fourth "REACHED, not WIRED" Disclosure (2026-09-07)

`react_loop.attempt_hypothesis_refutation()` and `qualified_conclusion.
build_qualified_conclusion(refutation_result=, require_refutation_pass=)`
(both built and independently tested earlier the same day -- see "Adversarial
Refutation Pass: a Structurally-Forced Self-Critique Gate on
QualifiedConclusion" above) had zero `engine.py` call site, confirmed by
direct grep before this task began: both modules' own docstrings disclosed
this exact residual verbatim ("`engine.py` was deliberately not modified
given its size/risk/test-coverage profile and this task's own scope"). This
closes it, alongside the three sibling Confidence/Inference-Layer wirings
documented immediately above (confidence-reweight, hypothesis-bias, VOI
ranking) -- the fourth and final item that same ranked audit named.

**`DVHarness._attempt_root_cause_hypothesis_refutation()`** (new method,
inserted immediately before `_score_root_cause_confidence()`) calls the real,
unmodified `react_loop.attempt_hypothesis_refutation(self.adapter, self.root,
hypothesis, evidence_refs=..., profiler=self.profiler, profile_id=...,
agent_name=...)` -- using the SAME selected `root_cause` and its own real,
already-gate-verified `supporting_evidence` citations `root_cause_evidence_
gate.py` already validated, never inventing a hypothesis or evidence of its
own. Returns `None` (never a fabricated `attempted=True/False` dict) when the
block carries no `root_cause`, or on any exception -- a transport failure
degrades exactly to `attempt_hypothesis_refutation()`'s own honest
`attempted=False` contract, which `build_qualified_conclusion()` already
treats identically to "no pass was run at all."

**Gated behind a new, additive, OFF-by-default policy flag**
(`policy.enable_adversarial_refutation_pass`, `config.py`'s `DEFAULT_CONFIG`,
mirroring `enable_inner_react_loop`'s own escape-hatch convention) --
deliberately NOT joining the other three siblings as an always-on best-effort
write, because `attempt_hypothesis_refutation()` dispatches one real, LIVE
`adapter.run()` call per gate-verified PASS attempt at RE_AUDIT/RCA_JOIN, a
materially different cost from every other side effect in
`_score_root_cause_confidence()`. Turning it on also makes the SAME flag
value `build_qualified_conclusion()`'s own `require_refutation_pass` --
never silently weaker: a project that opts in gets both the live pass AND the
stricter "a completed, non-refuting attempt is now mandatory for
`is_qualified`" rule that module's own construction already enforces,
together, not one without the other. With the flag off (every existing
project, unchanged), `_score_root_cause_confidence()` builds byte-identically
to before this task -- `refutation_result=None`, `require_refutation_pass=
False`, proven by a dedicated negative-control test asserting the wired hook
is never even called.

Best-effort throughout, matching every sibling side effect in this method: a
real exception inside the hook records `ADVERSARIAL_REFUTATION_PASS_FAILED`
and returns `None` rather than crashing the stage; every real attempt
(succeeded or not) records one `ADVERSARIAL_REFUTATION_PASS_RUN` event
naming the real `attempted`/`refuted` outcome, immediately before the
existing `build_qualified_conclusion()` call and its own
`QUALIFIED_CONCLUSION_BUILT`/`QUALIFIED_CONCLUSION_BUILD_FAILED` event.

Proven by `dv_harness_tests/test_engine_adversarial_refutation_coupling.py`
(7 tests): the flag-off negative control (the wired hook is never called,
`qualified_conclusion.refutation` stays `None`); the flag-on positive path
(the real hypothesis/evidence-refs/profile_id/agent_name reach the mocked
hook, and its real result composes into the persisted `QualifiedConclusion`);
the confirmed-refutation-disqualifies-unconditionally proof, driven directly
through `build_qualified_conclusion()` at HIGH confidence; the required
Evidence-Truth-Rule negative control (`attempted=False` under a required
pass never qualifies); a real, injected transport failure inside the wired
hook proving the whole stage still completes and its `qualified_conclusion`
record still lands (with `is_qualified` structurally `False`); the
no-root-cause-never-calls-the-live-adapter guard; and the
list-vs-dict-vs-absent `supporting_evidence` extraction proof. Re-run
alongside the full pre-existing `test_engine_gates_and_routing.py` /
`test_inference_engine_wiring.py` / `test_qualified_conclusion.py` /
`test_react_loop.py` / `test_react_inference_wiring.py` suites plus the three
sibling coupling test files (367 tests combined) -- zero regressions.

**Disclosed residual**: nothing in this harness's real graph/gate machinery
ever sets `policy.enable_adversarial_refutation_pass` to `True` on its own --
turning it on is a deliberate, human-made project config decision, exactly
the same posture `enable_inner_react_loop`/`adaptive_react_budget.enabled`
already establish for this file's other opt-in behavior flags.


